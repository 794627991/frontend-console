#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DevTools CDP 基础设施（v3.5.187）——WebView2 调试协议直连客户端。

设计（designer 方案定稿）：
- 无连接池、无常驻、用完即弃：每次调用 = /json/list 现查 target → 新建
  WS → 执行 → close。页面刷新 targetId 会变，缓存连接必踩 stale；
  建连 ~10ms 可忽略，无状态天然自愈。
- websocket-client 懒导入（函数级 try/except，照抄 hiklink_bot HAS_WS
  模式）——已随 exe 打包（前端控制台.spec hiddenimports），源码模式
  hiklink 生产在用；不用 devtools 工具就零导入开销。
- CDP 端口仅在调试模式开启（run_debug.bat / HARNESS_DEBUG_WEB=1，固定
  9222；main.py:1043）——用户拍板 P0b 维持调试专用，正式版报明确指引。
"""
import json
import os
import time
import urllib.request

STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
ENDPOINT_FILE = os.path.join(STATE_DIR, "endpoint.json")
_DEBUG_PORT = 9222          # run_debug.bat 固定端口（main.py 硬编码）

_ws = None                  # 懒导入缓存（websocket 模块）


def _load_ws():
    """websocket-client 懒导入；缺失抛 WsMissing（MCP 侧映射安装指引）。"""
    global _ws
    if _ws is None:
        try:
            import websocket          # noqa: F401  websocket-client
        except ImportError:
            raise WsMissing()
        _ws = websocket
    return _ws


class DevtoolsError(Exception):
    """CDP 调用基类——message 即用户可读中文文案。"""


class WsMissing(DevtoolsError):
    def __init__(self):
        super().__init__("websocket-client 未安装——源码模式请 pip install "
                         "websocket-client；exe 分发不应出现此错误")


class CdpUnavailable(DevtoolsError):
    def __init__(self):
        # a473：CDP 两路开启——run_debug.bat（调试模式）或配置键 web_cdp
        #（设置→终端设置→「AI 网页操作」打开并重启，正常启动也带端口）
        super().__init__("CDP 端口未开启。两种开启方式：① 用 run_debug.bat "
                         "启动（调试模式）；② 设置→终端设置→「AI 网页操作"
                         "（CDP）」开关打开并重启工具")


class TargetNotFound(DevtoolsError):
    def __init__(self, targets_summary):
        super().__init__("未找到工具页面 target。现有 targets：\n%s\n"
                         "窗口可能刚关闭或页面未加载完，稍候重试"
                         % (targets_summary or "（无）"))


class CdpError(DevtoolsError):
    def __init__(self, msg, code="generic"):
        super().__init__(msg)
        self.code = code        # "expr"=页面表达式异常 | "generic"=传输/协议


def find_cdp(timeout=1.0):
    """探活 CDP 端口：调试模式固定 9222。返回端口或抛 CdpUnavailable。"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/json/version" % _DEBUG_PORT,
                timeout=timeout) as r:
            if r.status == 200:
                return _DEBUG_PORT
    except Exception:
        pass
    raise CdpUnavailable()


def list_targets(cdp_port, timeout=3.0):
    """GET /json/list → 全部 target 列表（dict）。"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/json/list" % cdp_port,
                timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        raise CdpError("读取 target 列表失败: %r" % e)


def find_page_target(cdp_port, backend_origin):
    """过滤工具主页面 target（type=page 且 url 以后端 origin 开头）。
    返回 target dict；零命中抛 TargetNotFound（带全部 targets 摘要）。"""
    targets = [t for t in list_targets(cdp_port)
               if t.get("type") == "page"]
    hits = [t for t in targets
            if str(t.get("url", "")).startswith(backend_origin)]
    if not hits:
        summary = "\n".join(
            "  - [%s] %s" % (t.get("type", "?"),
                             (t.get("title") or t.get("url") or "?")[:60])
            for t in targets[:8])
        raise TargetNotFound(summary)
    return hits[0]          # 多命中（理论不出现）取第一个


class CdpSession(object):
    """单次 CDP WS 会话（上下文管理器，用完即弃）。
    send 按 id 匹配响应，途中事件帧喂 collector（无则丢弃）——
    这是「事件与响应交错」的正解；collect = 订阅窗口。"""

    def __init__(self, cdp_port, target_id, timeout=3.0):
        self._ws_mod = _load_ws()
        self._url = "ws://127.0.0.1:%d/devtools/page/%s" % (cdp_port, target_id)
        self._timeout = timeout
        self._ws = None
        self._mid = 0
        self._collector = None        # collect 期间的事件回调 fn(evt)

    def __enter__(self):
        ws_mod = self._ws_mod
        try:
            self._ws = ws_mod.create_connection(
                self._url, timeout=self._timeout,
                suppress_origin=True)
        except ws_mod.WebSocketBadStatusException as e:
            raise CdpError("WS 握手被拒 (%s)——页面可能刚刷新（target 已换），"
                           "直接重试即可" % e)
        except Exception as e:
            raise CdpError("WS 连接失败: %r——页面可能刚刷新，直接重试即可" % e)
        return self

    def __exit__(self, *exc):
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        return False

    def send(self, method, params=None, timeout=10.0):
        """同步命令：发 method 等匹配 id 的响应，返回 result dict。
        途中事件帧喂 collector（在订阅窗口内）或丢弃。超时/断连抛 CdpError。"""
        if self._ws is None:
            raise CdpError("WS 未连接")
        self._mid += 1
        mid = self._mid
        try:
            self._ws.send(json.dumps({"id": mid, "method": method,
                                      "params": params or {}}))
        except Exception as e:
            raise CdpError("WS 发送失败: %r——页面可能刚刷新，直接重试即可" % e)
        deadline = time.time() + timeout
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise CdpError("页面无响应（%s 超时 %.0fs）——可能导航中或忙，"
                               "重试或先 devtools_screenshot 看状态"
                               % (method, timeout))
            try:
                raw = self._ws.recv()
            except Exception as e:
                raise CdpError("WS 读取失败: %r——页面可能刚刷新，直接重试即可" % e)
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("id") == mid:
                if msg.get("error"):
                    raise CdpError("CDP 错误: %s" % json.dumps(
                        msg["error"], ensure_ascii=False)[:300], code="expr")
                return msg.get("result") or {}
            if msg.get("method") and self._collector:
                try:
                    self._collector(msg)
                except Exception:
                    pass
            # 其余事件（非订阅期）丢弃

    def collect(self, seconds, on_event):
        """订阅窗口：seconds 内收到的事件喂 on_event（阻塞至 deadline）。"""
        prev = self._collector
        self._collector = on_event
        closed = False
        try:
            ws_mod = self._ws_mod
            deadline = time.time() + max(0.5, min(60.0, seconds))
            while time.time() < deadline:
                try:
                    self._ws.settimeout(0.5)
                    raw = self._ws.recv()
                except ws_mod.WebSocketTimeoutException:
                    continue          # 窗口内正常超时，续等
                except Exception:
                    # v3.5.187r1 全审G2：断连（页面刷新/关闭）不再空转到 deadline
                    closed = True
                    break
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("method"):
                    try:
                        on_event(msg)
                    except Exception:
                        pass
        finally:
            if closed:
                try:
                    on_event({"method": "_cdp_disconnected", "params": {}})
                except Exception:
                    pass
            self._collector = prev
            try:
                self._ws.settimeout(self._timeout)
            except Exception:
                pass


def evaluate(js_expression, timeout=10.0, max_len=4000):
    """便捷封装：找 CDP→找 target→Runtime.evaluate（awaitPromise+
    returnByValue）→返回截断文本。供 mcp_server 五工具共用。"""
    port = find_cdp()
    info = {}
    try:
        with open(ENDPOINT_FILE, encoding="utf-8") as f:
            info = json.loads(f.read())
    except Exception:
        pass
    origin = "http://127.0.0.1:%s" % info.get("port", "")
    with CdpSession(port, find_page_target(port, origin)["id"]) as cs:
        try:
            res = cs.send("Runtime.evaluate", {
                "expression": js_expression,
                "returnByValue": True, "awaitPromise": True,
            }, timeout=timeout)
        except CdpError as e:
            if getattr(e, "code", "") == "expr":
                raise CdpError("表达式异常: %s" % e)
            raise
        if res.get("exceptionDetails"):
            ed = res["exceptionDetails"]
            txt = (ed.get("exception", {}).get("description")
                   or ed.get("text") or "未知异常")
            raise CdpError("表达式异常: %s" % txt[:500])
        r = res.get("result", {})
        if r.get("subtype") == "unserializable":
            out = str(r.get("description", ""))
        else:
            v = r.get("value")
            out = v if isinstance(v, str) else json.dumps(
                v, ensure_ascii=False, default=str)
        if len(out) > max_len:
            out = out[:max_len] + "\n…（已截断，全长 %d 字符）" % len(out)
        return out


def page_target_origin_probe():
    """mcp_server 前置：返回 (cdp_port, target_id, origin) 或抛对应异常。"""
    port = find_cdp()
    info = {}
    try:
        with open(ENDPOINT_FILE, encoding="utf-8") as f:
            info = json.loads(f.read())
    except Exception:
        pass
    origin = "http://127.0.0.1:%s" % info.get("port", "")
    t = find_page_target(port, origin)
    return port, t["id"], origin
