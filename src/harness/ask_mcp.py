# -*- coding: utf-8 -*-
"""交互式提问 MCP server（harness 会话内，stdio）。

Claude Code 在 `-p`（headless）下把 AskUserQuestion / ExitPlanMode 从工具表里
摘掉了——模型想调用也没有该工具，二进制里的原话是 "tool requires user
interaction; no prompt available in headless mode"。所以 harness 会话里的
「给你几个选项、你选一个」这条路必须自己铺。

铺法：用 --mcp-config 注册本文件为 MCP server，它只暴露一个工具
`ask_user`。模型调用它 → 本进程向工具后端的 /api/harness/ask/reply 长轮询
等用户作答 → 前端把选项渲染成可点卡片 → 用户点选提交 → 后端唤醒这里 →
把答案作为工具返回值交回模型。模型看到的就是一次普通的工具调用结果。

为什么是「长轮询」而不是「挂起后由后端主动唤醒」：本进程与后端是两个进程，
MCP 协议又只有 stdin/stdout 一条同步通道（tools/call 必须就地返回结果），
所以「等」只能靠 HTTP 轮询实现。请求在工具调用发出的那一刻就发出去，
用户实际作答几乎总在几秒内，轮询间隔 1s 对用户无感。

后端地址从 ~/.serialconsole_pro/endpoint.json 读（与 mcp_server.py 同一套
服务发现，工具启动时写入）。sid 由 --mcp-config 的 env 传入，用于让后端
定位到是哪个 harness 会话在问。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
ENDPOINT_FILE = os.path.join(STATE_DIR, "endpoint.json")

# 后端地址与 sid：env 优先（--mcp-config 注入），endpoint.json 兜底
SID = (os.environ.get("HARNESS_SID") or "").strip()
URL_OVERRIDE = (os.environ.get("HARNESS_BACKEND") or "").strip()
# 会话权限模式（confirm=变更前确认）：超时文案按模式区分——confirm 下
# 未获确认不得引导模型自行执行写操作，否则权限模式形同虚设
PERM = (os.environ.get("HARNESS_PERM") or "auto").strip()

# 单次提问的最长等待（秒）。超过则返回「用户未作答」让模型自行决定，
# 不把整轮回复永久挂死。
WAIT_MAX = 15 * 60
POLL_INTERVAL = 1.0


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(text, is_error=False):
    r = {"content": [{"type": "text", "text": text}]}
    if is_error:
        r["isError"] = True
    return r


def _backend_url():
    """返回后端 HTTP 根地址，读不到则 None。"""
    if URL_OVERRIDE:
        return URL_OVERRIDE
    try:
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            url = (json.load(f) or {}).get("url")
        return url or None
    except Exception:
        return None


def _post(path, payload, timeout=10, _depth=0):
    """POST JSON。**显式跟随 307/308**（v4.0.0-a121）。

    根因（用户实锤「提问未被受理：后端返回 307」）：Claude 子系统已 offload
    到 worker 进程，主进程对 /api/harness/* 回 307 + Location 指向 worker。
    而 `urllib.request.urlopen` **不会为 POST 自动跟随 307**（重定向会改变
    请求方法语义，标准库对 POST 一律抛 HTTPError），于是本函数拿到 307 就
    在 except 分支返回错误——ask_user 全链路失效。

    这里手动跟随一次（307/308 保持原方法与 body，这正是它们的语义），
    最多 3 跳防环。其余状态码维持原处理。
    """
    url = _backend_url()
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     # v3.4.96：93e 进程级 UA 门禁——本子进程默认 UA
                     # (Python-urllib) 被 403，ask_user 全炸（用户实锤
                     # 「提问未被受理：unauthorized」）。带自家标记放行
                     # （字面量与 server._WEBVIEW_UA_MARK 对齐，勿 import
                     # server——会拖起整个 Flask）
                     "User-Agent": "SerialConsoleProWebView/1"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        # 307/308：offload 转发到 worker——保持方法与 body 重放一次
        if e.code in (307, 308) and _depth < 3:
            loc = ""
            try:
                loc = (e.headers.get("Location") or "").strip()
            except Exception:
                loc = ""
            if loc:
                # 用相对路径 + Location 的 path 重拼（Location 是绝对 URL，
                # 直接以其为准）
                try:
                    base = _backend_url() or ""
                    if base and loc.startswith(base):
                        return _post(loc[len(base):] or path, payload,
                                     timeout, _depth + 1)
                    # 跨主机/端口（主进程 → worker）：临时改 override 不可行，
                    # 这里直接构造完整 URL 请求
                    return _post_abs(loc, payload, timeout)
                except Exception:
                    pass
        try:
            return json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return {"ok": False, "err": "后端返回 %s" % e.code}
    except Exception:
        return None


def _post_abs(url, payload, timeout=10):
    """向绝对 URL POST（重定向目标，往往换端口）。"""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "SerialConsoleProWebView/1"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return {"ok": False, "err": "后端返回 %s" % e.code}
    except Exception:
        return None


# 本次待答问题 id（模型一次只问一组；后端按 sid 定位）
_pending = [None]


def _ask(args):
    """发起一次提问并阻塞等待用户作答。返回给模型的文本。"""
    questions = args.get("questions")
    if not isinstance(questions, list) or not questions:
        return _result("questions 必须是非空数组", is_error=True)
    title = str(args.get("title") or "").strip()
    req_id = "q%d-%d" % (os.getpid(), int(time.time() * 1000))
    r = _post("/api/harness/ask/reply", {
        "sid": SID, "req_id": req_id,
        "title": title, "questions": questions}, timeout=15)
    if r is None:
        # 后端不可达（工具没开 / endpoint.json 过期）：明确告知，别让模型猜
        return _result("无法连接前端控制台后端，用户看不到这次提问。"
                       "请改用普通文本把选项写出来让用户回复。", is_error=True)
    if not r.get("ok"):
        return _result("提问未被受理：%s" % (r.get("err") or "未知原因"), is_error=True)

    # 长轮询等作答
    deadline = time.time() + WAIT_MAX
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        rr = _post("/api/harness/ask/poll", {"sid": SID, "req_id": req_id}, timeout=10)
        if not rr or not rr.get("ok"):
            continue
        if rr.get("done"):
            return _result(json.dumps(rr.get("answer") or {}, ensure_ascii=False))
    # 超时文案按权限模式区分：confirm 下绝不能引导模型「自行继续」执行
    # 本该确认的写操作（审计 §一.3）
    if PERM == "confirm":
        return _result("用户长时间未作答，未获得确认。不要执行任何会产生写入/修改/"
                       "删除效果的操作；改为说明需要用户确认什么，等待用户回复。",
                       is_error=False)
    return _result("用户长时间未作答，请自行按最优方案继续，并在回复中说明你的选择。",
                   is_error=False)


_TOOLS = [{
    "name": "ask_user",
    "description": (
        "向用户提问并等待其选择。用户在界面上看到可点击的选项卡片，点击提交后"
        "本工具返回用户的选择。\n"
        "适用场景：需要用户从若干方案中拍板（如「用方案 A 还是 B」）、关键决策"
        "需要确认、信息不足以继续且必须由用户提供时。\n"
        "不要用它问「你要不要我继续」这类无意义确认；也不要明知答案的明知故问。\n"
        "调用本工具后你应当停下等待，返回值里就是用户的选择。"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "卡片标题（可选），如「选择实现方案」",
            },
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "description": "要问的问题，1-4 个",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "完整的问题文本，以问号结尾",
                        },
                        "header": {
                            "type": "string",
                            "description": "极短标签（≤12 字符），作为选项组标题，如「方案」「范围」",
                        },
                        "multiSelect": {
                            "type": "boolean",
                            "description": "是否允许多选，默认 false",
                        },
                        "options": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "description": "可选项，2-4 个",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "选项显示文本，简短（1-5 词）",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "该选项的含义/后果说明，帮助用户判断",
                                    },
                                },
                                "required": ["label"],
                            },
                        },
                    },
                    "required": ["question", "options"],
                },
            },
        },
        "required": ["questions"],
    },
}]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        req_id = req.get("id")
        if req_id is None:
            continue
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "harness-ask", "version": "1.0.0"}}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            if params.get("name") != "ask_user":
                _send({"jsonrpc": "2.0", "id": req_id,
                       "result": _result("未知工具", is_error=True)})
                continue
            try:
                res = _ask(params.get("arguments") or {})
            except Exception as e:
                res = _result("提问失败：%s" % e, is_error=True)
            _send({"jsonrpc": "2.0", "id": req_id, "result": res})
        else:
            _send({"jsonrpc": "2.0", "id": req_id, "result": {}})


if __name__ == "__main__":
    main()
