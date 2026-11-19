#!/usr/bin/env python3
"""
claude_proxy_core.py
====================
Claude Code 重试代理核心（无 curses，Windows/Linux 通吃）。版本随 GUI 定版 V2.2.0。

从 claude_proxy_live.py 摘录的转发核心：透明转发 Claude Code 请求到上游，
对 429/5xx 阶梯退避重试（1.0s→10s 封顶，带抖动），边转发边解析 SSE usage 统计。

与 live.py 的区别：
    - 去掉 curses 仪表盘（Windows 无 curses），纯核心可被 GUI/CLI 复用
    - Stats.snapshot(history_limit=None)：可选只取末尾 N 条历史，避免全量拷贝
    - /__proxy/stats JSON 补全 last_overload_*/events（live.py 漏了）
    - create_server() 工厂默认 host=127.0.0.1（live.py 是 0.0.0.0，桌面机无需 LAN 暴露）

架构：
    Claude Code -> 127.0.0.1:37349 (本代理) -> lanz.hikvision.com:80 -> 内部模型

退避策略（阶梯式，封顶 10s，带 [0.8,1.2] 随机抖动）：
    attempt 1-10   -> 1.0s
    attempt 11-20  -> 3.0s
    attempt 21-30  -> 5.0s
    ...           -> 每档 +2.0s，每档 10 次
    attempt 41+    -> 封顶 10.0s
    429/5xx/网络异常无限重试直到成功或客户端断开（这些都不消耗额度：请求被拒/服务端错误/没拿到响应），
    客户端断开立即停止（不再发请求，省额度）；已拿到上游响应后异常不重试（避免上游重复生成烧额度）。

重试策略可通过 core 同目录 retry_config.json 配置（缺省保持上述默认行为）：
    max_attempts        重试次数上限（429+5xx+网络异常合计），0=无限（默认）
    max_retry_seconds   重试总时长上限（秒，从请求发起起算），0=无限（默认）
    backoff_enabled     阶梯退避开关，False=立即重试不等待（默认 True）
    max_backoff_seconds 单次退避封顶秒数，实际值带 [0.8,1.2] 随机抖动（默认 10.0）
    达上限后熔断：把最后一次上游错误原样回放给客户端（合成 502），不让客户端挂死。

控制接口：
    GET  /__proxy/ping      -> {"status":"ok"}
    GET  /__proxy/stats     -> 计数器/token/模型/运行时长/429事件
    POST /__proxy/shutdown  -> 优雅关闭
"""

import http.client
import http.server
import json
import logging
import os
import random
import select
import socket
import socketserver
import sys
import threading
import time

log = logging.getLogger("claude_proxy_core")

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}
CONTROL_PREFIX = "/__proxy/"

# 可重试状态码分两档：限流(可多试) / 服务端错误(少试)
THROTTLE_STATUSES = {429, 529}          # 限流/过载，值得多试
ERR_STATUSES = {500, 502, 503, 504}     # 服务端错误，重试意义小
RETRY_STATUSES = THROTTLE_STATUSES | ERR_STATUSES

# 重试上限/退避参数移至 retry_config.json（RETRY_CFG），默认 0=无限重试保持现状

# 阶梯退避参数（提高起步与封顶，加抖动错开并发重试）
STEP_SIZE = 10          # 每档 10 次重试
STEP_DELTA = 2.0        # 每档 +2.0s
MIN_WAIT = 1.0          # 起始 1.0s
MAX_WAIT = 10.0         # 封顶 10.0s（默认；可被 retry_config.json 覆盖）
JITTER_RANGE = (0.8, 1.2)   # 随机抖动，错开并发请求的重试节奏
MAX_RETRY_AFTER = 60.0      # 尊重上游 Retry-After 头的上限
STREAM_READ_TIMEOUT = 1.0   # 流式转发时上游 read 超时，超时即探测客户端是否还在
CLIENT_GONE_CONFIRM = 3     # 流式 read 超时时连续探测到客户端断开的次数才认定（防误断）

# ---- 重试策略配置（retry_config.json，可用户编辑）--------------------
# 文件位置：core 模块同目录（源码跑=脚本目录；打包 exe=exe 所在目录）。
# 改完需重启代理生效（模块加载时读一次）。字段缺省/非法时用默认值。
RETRY_CONFIG_DEFAULTS = {
    "max_attempts": 0,          # 重试次数上限（429+5xx+网络异常合计）。0=无限（默认，现状）
    "max_retry_seconds": 0,    # 重试总时长上限（秒，从请求发起起算）。0=无限（默认，现状）
    "backoff_enabled": True,   # 阶梯退避开关。False=不逐次加长，固定按最短间隔
                               # (MIN_WAIT,1s,带抖动)重试，也不理 Retry-After
    "max_backoff_seconds": MAX_WAIT,  # 单次退避封顶秒数。实际值仍带 [0.8,1.2] 随机抖动
}


def load_retry_config():
    """读 retry_config.json。文件不存在/字段缺失/非法 → 用默认值（保持现状行为）。
    v2.27.1：数据目录（DATA_DIR）优先；旧位置（项目根/exe 目录/src/）命中后
    自动迁入数据目录（一次性，os.replace）——配置跟数据目录走（用户定调）。
    返回 dict（内部已做类型与范围校验）。"""
    cfg = dict(RETRY_CONFIG_DEFAULTS)
    data_path = None
    try:
        from src.app_state import DATA_DIR
        data_path = os.path.join(DATA_DIR, "retry_config.json")
    except Exception:
        pass
    paths = []
    if data_path:
        paths.append(data_path)
    # 旧位置兜底（历史版本写在程序侧）：项目根 / exe 目录 / src/
    try:
        from src.app_state import BASE_DIR
        paths.append(os.path.join(BASE_DIR, "retry_config.json"))
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            paths.append(os.path.join(
                os.path.dirname(sys.executable), "retry_config.json"))
        except Exception:
            pass
    paths.append(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "retry_config.json"))
    chosen = next((p for p in paths if os.path.exists(p)), None)
    if chosen:
        try:
            with open(chosen, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                # 只收认识的字段，忽略 _ 开头的注释键
                known = set(RETRY_CONFIG_DEFAULTS)
                cfg.update({k: v for k, v in d.items() if k in known})
            # 命中旧位置 → 一次性迁入数据目录（配置跟数据目录走）
            if data_path and chosen != data_path:
                try:
                    os.replace(chosen, data_path)
                    log.info("retry_config.json 已迁入数据目录 %s", data_path)
                except OSError as e:
                    log.warning("retry_config.json 迁入数据目录失败（不影响使用）: %s", e)
        except (ValueError, OSError) as e:
            log.warning("读取 %s 失败，用默认重试配置: %s", chosen, e)
    # 校验：数值字段非法/负数回默认；布尔强转
    for k in ("max_attempts", "max_retry_seconds", "max_backoff_seconds"):
        try:
            v = float(cfg.get(k, RETRY_CONFIG_DEFAULTS[k]))
            cfg[k] = v if v >= 0 else RETRY_CONFIG_DEFAULTS[k]
        except (TypeError, ValueError):
            cfg[k] = RETRY_CONFIG_DEFAULTS[k]
    cfg["max_attempts"] = int(cfg["max_attempts"])
    cfg["backoff_enabled"] = bool(cfg.get("backoff_enabled",
                                          RETRY_CONFIG_DEFAULTS["backoff_enabled"]))
    return cfg


def retry_config_file():
    """返回 retry_config.json 的写入路径。v2.27.1：归数据目录（DATA_DIR，
    可迁移）——配置属用户数据，跟数据目录走而非跟程序目录（用户定调：
    软件迁移目录后数据类文件应在新数据目录）。旧位置（项目根/exe 目录/src/）
    的存量文件由 load_retry_config 首读时自动迁入数据目录。"""
    try:
        from src.app_state import DATA_DIR
        return os.path.join(DATA_DIR, "retry_config.json")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "retry_config.json")


def reload_retry_config():
    """重读 retry_config.json 并就地更新 RETRY_CFG（GUI 热更新用）。
    backoff_wait/check_retry_cap 每次调用都读 RETRY_CFG，就地 update 后
    正在运行的代理立即生效，无需重启。返回更新后的配置副本。"""
    RETRY_CFG.update(load_retry_config())
    return dict(RETRY_CFG)


RETRY_CFG = load_retry_config()


def backoff_wait(attempt):
    """根据当前重试次数返回应等待秒数（阶梯式，带抖动）。

    基准值：attempt 1-10 -> 1.0, 11-20 -> 3.0, 21-30 -> 5.0, ...
    封顶 RETRY_CFG["max_backoff_seconds"]（默认 10.0）。
    实际返回值乘以 [0.8, 1.2] 的随机抖动，错开并发请求的重试节奏——
    用户配置 0.5s 封顶时实际等待在 0.5 的随机范围内。
    backoff_enabled=False 时不逐次加长、不理 Retry-After，但也不零间隔
    打爆上游：固定按最短间隔 MIN_WAIT(1s，同样带抖动)重试。
    """
    if not RETRY_CFG["backoff_enabled"]:
        return MIN_WAIT * random.uniform(*JITTER_RANGE)
    step = (attempt - 1) // STEP_SIZE          # 0-based 档位
    wait = MIN_WAIT + step * STEP_DELTA
    wait = min(wait, RETRY_CFG["max_backoff_seconds"])
    return wait * random.uniform(*JITTER_RANGE)


def backoff_tier(attempt):
    """返回当前退避档位的描述字符串。"""
    return "%.1fs" % backoff_wait(attempt)


def client_alive(sock):
    """非阻塞探测客户端是否还连着。

    进入重试循环前请求体已读完，客户端正常处于"等响应"状态、不发数据，
    所以 socket 不可读 = 还活着；对端关闭则 socket 变可读且 PEEK 读到 b""。
    跨平台：select 只用于 socket（Windows 限制）、socket.MSG_PEEK 双平台支持。"""
    if sock is None:
        return False
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        if not readable:
            return True
        return sock.recv(1, socket.MSG_PEEK) != b""
    except (BlockingIOError, InterruptedError):
        return True     # 暂时没数据，按还活着处理
    except (OSError, ValueError):
        return False    # socket 已失效


def check_retry_cap(n429, nerr, t0):
    """重试上限判据（读 retry_config.json 配置，默认全 0=无限重试保持现状）。
    返回放弃原因字符串或 None(可继续)。n429+nerr=已重试次数；t0=请求发起时刻。
    次数与时长两个条件独立，任一超限即熔断。"""
    if RETRY_CFG["max_attempts"] > 0 and (n429 + nerr) >= RETRY_CFG["max_attempts"]:
        return "max_attempts"
    if RETRY_CFG["max_retry_seconds"] > 0 and \
            (time.time() - t0) >= RETRY_CFG["max_retry_seconds"]:
        return "max_retry_time"
    return None


def parse_retry_after(resp):
    """取上游 Retry-After 响应头转 float 秒数。解析失败返回 None。

    支持两种格式：纯数字（秒）或 HTTP 日期（按 RFC 7231，取距现在的秒差）。
    """
    val = resp.getheader("Retry-After")
    if not val:
        return None
    val = val.strip()
    # 纯数字秒数
    try:
        return float(val)
    except ValueError:
        pass
    # HTTP 日期格式
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(val)
        if dt is None:
            return None
        delta = dt.timestamp() - time.time()
        return delta if delta > 0 else 0.0
    except (TypeError, ValueError, OSError):
        return None


def short_path(path):
    """缩写请求路径，去掉冗长的 /v3/anthropic/model 前缀。"""
    p = path
    for prefix in ("/v3/anthropic/model", "/v1/anthropic/model"):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    if not p:
        p = "/"
    # 去掉 query string
    if "?" in p:
        p = p.split("?", 1)[0]
    if len(p) > 40:
        p = "..." + p[-37:]
    return p


def parse_request_model(body_bytes):
    """从请求 body 解析 model 字段。解析失败返回 None。"""
    if not body_bytes:
        return None
    try:
        d = json.loads(body_bytes.decode("utf-8"))
        m = d.get("model")
        return m if isinstance(m, str) else None
    except (ValueError, UnicodeDecodeError):
        return None


def parse_request_brief(body_bytes):
    """从请求 body 提取人类可读的请求摘要（"请求了什么"）。
    优先级：最后一条 user 消息里的真实文本 > 最后一次工具调用 > system 提示 > None。
    跳过 tool_result、billing header 等无意义内容。返回截断到 120 字符的纯文本。

    关键：Claude Code agentic 循环里每轮请求都带完整历史，最后一条 user 几乎总是
    tool_result（工具返回，无用户文本）。若回退找最近的有文本 user 消息，会永远
    指向用户最初那条输入 → 整个会话所有请求显示同一条。所以最后一条 user 是
    tool_result 时，改取最后一次 assistant 的 tool_use（正在调什么工具），
    这样每轮请求能区分"在读文件/在编辑/在跑命令"。"""
    if not body_bytes:
        return None
    try:
        d = json.loads(body_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None

    def _is_noise(t):
        """判断文本是否为无意义的元数据/控制标记。"""
        if not t:
            return True
        s = t.strip()
        if not s:
            return True
        # billing header / 元数据
        if s.startswith("x-anthropic-") or s.startswith("anthropic-"):
            return True
        # 纯标识符式（如 "cc_version=..."）
        if s.startswith("cc_") and "=" in s and len(s) < 60:
            return True
        return False

    def _text_of(content):
        """Claude API 的 content 可能是字符串或 [{type:text,text:...},...]。
        只取 type:text 的块，跳过 tool_result/tool_use/image。返回拼接纯文本。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    parts.append(blk.get("text", ""))
            return " ".join(parts)
        return ""

    def _last_tool_use(messages):
        """倒序找最后一条 assistant 消息里的最后一个 tool_use 块。
        返回 "工具名(参数摘要)" 或 None。这是 agentic 循环"当前正在做什么"的标志。"""
        for msg in reversed(messages):
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            # 同一条 assistant 消息可能有多个 tool_use，取最后一个（最近调的）
            for blk in reversed(content):
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    name = blk.get("name", "?")
                    inp = blk.get("input", {})
                    # 提取关键参数摘要：优先 file_path/command/pattern 等有意义字段
                    arg = ""
                    for key in ("file_path", "command", "pattern", "path",
                                "url", "query", "prompt"):
                        v = inp.get(key) if isinstance(inp, dict) else None
                        if v:
                            arg = str(v)
                            break
                    if arg:
                        return "%s: %s" % (name, arg[:80])
                    return name
        return None

    msgs = d.get("messages")
    if isinstance(msgs, list):
        # 1) 只看最后一条 user 消息：若有真实文本就用它。
        #    关键：只看最后一条，不往前遍历。Claude Code agentic 循环里每轮请求
        #    都带完整历史，最后一条 user 几乎总是 tool_result（无文本）。若往前
        #    遍历找有文本的 user，会永远指向用户最初那条 → 整个会话显示同一条。
        last_user_txt = None
        for msg in reversed(msgs):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user_txt = _text_of(msg.get("content")).strip()
                break
        if last_user_txt and last_user_txt.startswith("<transcript>"):
            # CLI 内部请求（会话恢复/压缩时把 transcript 片段发给模型）——
            # 不是用户输入，原始片段只会刷屏且困惑（像重复的旧消息）
            return "⚙ CLI 内部整理（transcript 摘要）"
        if last_user_txt and not _is_noise(last_user_txt):
            return last_user_txt[:120]
        # 2) 最后一条 user 是 tool_result（无文本）→ 取最后一次工具调用，
        #    而非回退到最初的用户输入（那会让整个会话显示同一条）
        tu = _last_tool_use(msgs)
        if tu:
            return "⟳ " + tu[:118]
    # 3) system 提示（跳过 billing header 类噪音）
    sys_c = d.get("system")
    if isinstance(sys_c, str) and sys_c.strip() and not _is_noise(sys_c):
        return "system: " + sys_c.strip()[:112]
    if isinstance(sys_c, list):
        txt = _text_of(sys_c).strip()
        if txt and not _is_noise(txt):
            return "system: " + txt[:112]
    # 4) 有工具定义但无 user 文本（工具调用场景）
    if isinstance(d.get("tools"), list) and d.get("tools"):
        return "(工具调用 %d 个)" % len(d["tools"])
    return None


# ---- 共享状态（代理线程写，GUI/仪表盘线程读）----------------------------
class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self.total_requests = 0
        self.total_overloads = 0       # 命中 429/5xx 的次数
        self.total_retries = 0         # 实际重发次数
        self.total_success = 0         # 成功转发的请求数
        self.start_time = time.time()
        # token 累计
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # 最近一次请求详情
        self.last_model = None
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        self.last_req_brief = None     # (method, path, model, brief)
        self.last_req_ts = None
        # 最近请求历史 (ts, model, in_tok, out_tok, brief, elapsed)
        self.req_history = []
        self.history_max = 100000   # 存全部历史供翻页查看（每条小tuple，10万条约几MB）
        # 429/5xx 事件
        self.last_overload_ts = None
        self.last_overload_status = None
        self.last_overload_path = None
        self.last_overload_attempt = 0
        self.events = []
        self.events_max = 30
        # 当前正在重试的请求数（>0 说明此刻正在重试）
        self.in_flight_retries = 0
        # 失败统计
        self.total_giveups = 0         # 达到重试上限放弃的请求数
        self.total_client_gone = 0     # 因客户端断开而中止的请求数
        self.last_fail = None          # (ts, reason, path, attempt, status)
        # reason ∈ {"max_429", "max_err", "upstream_error", "client_gone"}

    def snapshot(self, history_limit=None):
        """返回状态快照。history_limit=N 时只取 req_history 末尾 N 条（GUI 轮询用，
        避免每秒全量拷贝 10 万条）。events 同理受 history_limit 限制不裁剪（最多 30 条）。"""
        with self._lock:
            history = self.req_history
            if history_limit is not None and len(history) > history_limit:
                history = history[-history_limit:]
            return {
                "total_requests": self.total_requests,
                "total_overloads": self.total_overloads,
                "total_retries": self.total_retries,
                "total_success": self.total_success,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "last_model": self.last_model,
                "last_input_tokens": self.last_input_tokens,
                "last_output_tokens": self.last_output_tokens,
                "last_req_brief": self.last_req_brief,
                "last_req_ts": self.last_req_ts,
                "req_history": list(history),
                "req_history_total": len(self.req_history),
                "uptime_seconds": int(time.time() - self.start_time),
                "last_overload_ts": self.last_overload_ts,
                "last_overload_status": self.last_overload_status,
                "last_overload_path": self.last_overload_path,
                "last_overload_attempt": self.last_overload_attempt,
                "events": list(self.events),
                "in_flight_retries": self.in_flight_retries,
                "total_giveups": self.total_giveups,
                "total_client_gone": self.total_client_gone,
                "last_fail": self.last_fail,
            }

    def req_start(self, method, path, model, brief=None):
        with self._lock:
            self.total_requests += 1
            self.last_req_brief = (method, short_path(path), model, brief)
            self.last_req_ts = time.time()

    def req_success(self, model, in_tok, out_tok, elapsed, brief=None):
        """brief: 本请求的 (method, path, model, desc) 四元组。并发下共享的
        last_req_brief 会被其他请求覆盖（张冠李戴），调用方应传请求级快照；
        None 时回退共享字段（向后兼容）。"""
        with self._lock:
            self.total_success += 1
            if in_tok:
                self.total_input_tokens += in_tok
                self.last_input_tokens = in_tok
            if out_tok:
                self.total_output_tokens += out_tok
                self.last_output_tokens = out_tok
            if model:
                self.last_model = model
            brief = brief if brief is not None else self.last_req_brief
            # 请求描述：优先用 body 摘要(brief[3])，否则回退 method+path
            if brief and brief[3]:
                desc = brief[3]
            elif brief:
                desc = "%s %s" % (brief[0], brief[1])
            else:
                desc = "?"
            self.req_history.append(
                (time.time(), model or (brief[2] if brief else "?"),
                 in_tok or 0, out_tok or 0,
                 desc,
                 elapsed))
            if len(self.req_history) > self.history_max:
                self.req_history = self.req_history[-self.history_max:]

    def req_failed(self, reason, path, attempt, status=None, elapsed=None,
                   in_tok=0, out_tok=0, brief=None):
        """记录一个放弃/中止的请求。reason 见 __init__ 注释。
        已消耗的 token 如实累加（额度确实消耗了）；失败行写入 req_history，
        描述后缀 " ← 失败:原因@attempt"，GUI 历史表直接可见。
        brief: 本请求的 (method, path, model, desc) 四元组，None 回退共享字段。"""
        with self._lock:
            if reason == "client_gone":
                self.total_client_gone += 1
            else:
                self.total_giveups += 1
            if in_tok:
                self.total_input_tokens += in_tok
            if out_tok:
                self.total_output_tokens += out_tok
            self.last_fail = (time.time(), reason, short_path(path), attempt, status)
            brief = brief if brief is not None else self.last_req_brief
            if brief and brief[3]:
                desc = brief[3]
            elif brief:
                desc = "%s %s" % (brief[0], brief[1])
            else:
                desc = "?"
            desc = "%s ← 失败:%s@%d" % (desc, reason, attempt)
            self.req_history.append(
                (time.time(), (brief[2] if brief else "?"),
                 in_tok, out_tok, desc, elapsed or 0.0))
            if len(self.req_history) > self.history_max:
                self.req_history = self.req_history[-self.history_max:]

    def record_overload(self, status, path, attempt):
        with self._lock:
            self.total_overloads += 1
            self.total_retries += 1
            self.last_overload_ts = time.time()
            self.last_overload_status = status
            self.last_overload_path = short_path(path)
            self.last_overload_attempt = attempt
            self.events.append((time.time(), status, short_path(path), attempt))
            if len(self.events) > self.events_max:
                self.events = self.events[-self.events_max:]

    def record_retry_error(self):
        with self._lock:
            self.total_retries += 1

    def inflight_inc(self):
        """标记一个请求进入重试中状态（在途）。每个请求只调一次，
        在 req_success/req_failed 时配对 inflight_dec。"""
        with self._lock:
            self.in_flight_retries += 1

    def inflight_dec(self):
        """标记一个请求结束重试中状态（成功或放弃）。"""
        with self._lock:
            self.in_flight_retries -= 1
            if self.in_flight_retries < 0:
                self.in_flight_retries = 0  # 防御性，不应发生


# ---- SSE 流式解析器 -------------------------------------------------
# 边转发边解析 SSE，从 message_start 提取 model+input_tokens，
# 从 message_delta 提取 output_tokens。不缓存整流，逐 chunk 转发。
class SSEUsageParser:
    def __init__(self):
        self.model = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.stop_reason = None
        self._buf = b""

    def feed(self, chunk):
        """喂入一个 chunk，返回 (model, in_tok, out_tok) 的增量更新或 None。"""
        self._buf += chunk
        result = None
        while b"\n\n" in self._buf:
            block, self._buf = self._buf.split(b"\n\n", 1)
            data_lines = []
            for line in block.split(b"\n"):
                if line.startswith(b"data:"):
                    data_lines.append(line[5:].lstrip())
            if not data_lines:
                continue
            data_str = b"\n".join(data_lines)
            try:
                evt = json.loads(data_str.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            # 防御：SSE data 可能是合法 JSON 但非 dict（如 data: 42 → int）。
            # evt.get 对非 dict 抛 AttributeError，会穿透 _stream_response 的
            # (BrokenPipe, ConnectionReset) except → 跳过 conn.close() → conn
            # 泄漏 + in_flight 永久卡死 + 线程死亡。只认 dict 事件，其余跳过。
            if not isinstance(evt, dict):
                continue
            etype = evt.get("type")
            if etype == "message_start":
                msg = evt.get("message", {})
                if "model" in msg and not self.model:
                    self.model = msg.get("model")
                usage = msg.get("usage", {})
                # Claude API usage：input_tokens 只是"未缓存的新输入"，
                # 缓存的输入在 cache_creation_input_tokens（本次写入缓存）
                # 和 cache_read_input_tokens（命中已有缓存）里。Claude Code
                # 重度依赖 prompt caching，绝大部分输入走 cache_read——只取
                # input_tokens 会少算几十倍。三个字段加总才是真实输入。
                self.input_tokens = (
                    int(usage.get("input_tokens", 0) or 0)
                    + int(usage.get("cache_creation_input_tokens", 0) or 0)
                    + int(usage.get("cache_read_input_tokens", 0) or 0)
                ) or self.input_tokens
                result = (self.model, self.input_tokens, self.output_tokens)
            elif etype == "message_delta":
                # 实测 lanz 上游：message_start 的 usage 只有 input_tokens/
                # output_tokens，cache_creation/cache_read 只出现在 message_delta
                # 的 usage 里（最终值）。带 cache_control 的请求 message_start
                # 的 input_tokens 为 0——不在 delta 里补收 input 侧会全部记 0
                #（实测 64% 请求 in=0）。此处同样三字段加总取最终值。
                usage = evt.get("usage", {})
                in_total = (
                    int(usage.get("input_tokens", 0) or 0)
                    + int(usage.get("cache_creation_input_tokens", 0) or 0)
                    + int(usage.get("cache_read_input_tokens", 0) or 0)
                )
                if in_total:
                    self.input_tokens = in_total
                if "output_tokens" in usage:
                    self.output_tokens = usage.get("output_tokens", self.output_tokens)
                delta = evt.get("delta", {})
                if "stop_reason" in delta:
                    self.stop_reason = delta.get("stop_reason")
                result = (self.model, self.input_tokens, self.output_tokens)
        return result


# ---- 代理处理器 -----------------------------------------------------
class RetryProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 不走默认 stderr 访问日志

    def _handle_control(self):
        if self.path == CONTROL_PREFIX + "ping":
            self._json(200, {"status": "ok"})
        elif self.path == CONTROL_PREFIX + "stats":
            s = self.server.stats.snapshot()
            self._json(200, {
                "status": "ok",
                "upstream": "%s:%d" % (self.server.upstream_host, self.server.upstream_port),
                "listen_port": self.server.server_address[1],
                "total_requests": s["total_requests"],
                "total_overloads": s["total_overloads"],
                "total_retries": s["total_retries"],
                "total_success": s["total_success"],
                "total_input_tokens": s["total_input_tokens"],
                "total_output_tokens": s["total_output_tokens"],
                "last_model": s["last_model"],
                "last_input_tokens": s["last_input_tokens"],
                "last_output_tokens": s["last_output_tokens"],
                "last_req_brief": s["last_req_brief"],
                "req_history": s["req_history"],
                "req_history_total": s["req_history_total"],
                "uptime_seconds": s["uptime_seconds"],
                "last_overload_ts": s["last_overload_ts"],
                "last_overload_status": s["last_overload_status"],
                "last_overload_path": s["last_overload_path"],
                "last_overload_attempt": s["last_overload_attempt"],
                "events": s["events"],
                "in_flight_retries": s["in_flight_retries"],
                "total_giveups": s["total_giveups"],
                "total_client_gone": s["total_client_gone"],
                "last_fail": s["last_fail"],
            })
        elif self.path == CONTROL_PREFIX + "shutdown":
            self._json(200, {"status": "shutting down"})
            self.wfile.flush()
            # 同时设置 stop_event 唤醒主循环
            ev = getattr(self.server, "stop_event", None)
            if ev is not None:
                ev.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json(404, {"error": "unknown control path"})

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self):
        if self.path.startswith(CONTROL_PREFIX):
            self._handle_control()
            return

        stats = self.server.stats
        self._inflight_counted = False  # 本请求是否已计入在途（遇429/5xx时计一次，
                                         # 终结时配对减，保证 in_flight_retries 准确）
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        # 请求侧：解析 model 和请求摘要，记录请求简要
        req_model = parse_request_model(body)
        req_brief = parse_request_brief(body)
        # 本请求的 brief 四元组（与 Stats.last_req_brief 同构），随调用链透传到
        # req_success/req_failed——不再回查共享字段（并发下会被别的请求覆盖，
        # 历史 model/描述张冠李戴，审计 TODO#3）
        req_brief_t = (self.command, short_path(self.path), req_model, req_brief)
        stats.req_start(self.command, self.path, req_model, req_brief)
        t0 = time.time()

        out_headers = {}
        for key in self.headers.keys():
            if key.lower() in HOP_BY_HOP:
                continue
            out_headers[key] = self.headers[key]
        # Host 头是本地代理入口（127.0.0.1:37349）——按域名路由的网关会 404。
        # 重写为上游地址（默认端口不带上，与直连时客户端构造的 Host 一致）。
        _uh = self.server.upstream_host
        if (self.server.upstream_scheme, self.server.upstream_port) not in (("http", 80), ("https", 443)):
            _uh = "%s:%d" % (_uh, self.server.upstream_port)
        out_headers["Host"] = _uh

        path = self.path
        attempt = 0
        n429 = 0      # 限流类(429/529)累计重试次数
        nerr = 0      # 服务端错误(5xx)/网络异常累计重试次数
        last_err = None   # (status, headers, body) 最后一次上游可重试响应，供熔断时回放
        while True:
            # 循环顶部：客户端若已断开，立即放弃，不再发任何请求（省额度）
            if not client_alive(self.connection):
                stats.req_failed("client_gone", path, attempt,
                                 elapsed=time.time() - t0,
                                 brief=req_brief_t)
                log.info("client gone on %s %s (attempt %d) -- abort",
                         self.command, path, attempt)
                self._inflight_done(stats)
                return

            attempt += 1
            wait = backoff_wait(attempt)
            conn = None  # 循环内 try 之前初始化，except 里能安全 close
            got_response = False  # 每次新请求前重置：上一轮 429 的 True 不能带到这轮，
                                  # 否则新连接 request/getresponse 失败会被误判为"响应后
                                  # 异常"不重试→回放 502→Claude Code 双层重试→烧额度
            try:
                conn_cls = (http.client.HTTPSConnection
                            if getattr(self.server, "upstream_scheme", "http") == "https"
                            else http.client.HTTPConnection)
                conn = conn_cls(
                    self.server.upstream_host, self.server.upstream_port, timeout=600)
                conn.request(self.command, path, body=body, headers=out_headers)
                resp = conn.getresponse()
                got_response = True   # 拿到状态码后，本轮后续异常不能再重试（上游可能已生成）

                if resp.status in RETRY_STATUSES:
                    # 读 429/5xx 的 error body。单独 try：若上游在发 error 响应中途
                    # 断开（RST/超时），resp.read() 抛 OSError/HTTPException。此时
                    # 上游只是拒绝/出错，没开始生成 token，重试不烧额度。绝不能让
                    # 这个异常冒泡到外层 except 的 got_response 分支——got_response
                    # 已为 True（getresponse 成功），那会判为"响应后异常"静默 return，
                    # 既不重试也不给客户端任何响应 → 客户端收到空响应 → Claude Code
                    # 以为失败自己重试一层 → 双层重试烧额度（审计 bug #1）。
                    try:
                        err_body = resp.read()
                        err_headers = resp.getheaders()
                    except (http.client.HTTPException, ConnectionError, OSError) as e:
                        log.warning("upstream broke reading %d body on %s %s"
                                    " (attempt %d): %s -- retrying (no tokens spent)",
                                    resp.status, self.command, path, attempt, e)
                        try:
                            conn.close()
                        except Exception:
                            pass
                        stats.record_retry_error()
                        nerr += 1
                        if not self._inflight_counted:
                            stats.inflight_inc()
                            self._inflight_counted = True
                        if not self._sleep_checked(wait):
                            stats.req_failed("client_gone", path, attempt,
                                             elapsed=time.time() - t0,
                                             brief=req_brief_t)
                            self._inflight_done(stats)
                            return
                        continue
                    # 保留这次响应，熔断时原样回放给客户端
                    last_err = (resp.status, err_headers, err_body)
                    conn.close()
                    is_throttle = resp.status in THROTTLE_STATUSES
                    if is_throttle:
                        n429 += 1
                    else:
                        nerr += 1
                    stats.record_overload(resp.status, path, attempt)
                    # 首次进入重试：计入在途（整个重试期间 in_flight_retries 持续 >0，
                    # 直到成功/放弃才减。GUI 每秒刷新都能看到，不再只在 sleep 瞬间闪现）
                    if not self._inflight_counted:
                        stats.inflight_inc()
                        self._inflight_counted = True
                    # 429/5xx 重试直到成功/客户端断开/达上限熔断。
                    # 默认（max_attempts/max_retry_seconds=0）无限重试，保持现状：
                    # 429/5xx 不消耗额度（请求被拒/服务端错误，没生成 token），
                    # 客户端断开由 _sleep_checked 兜底立即停。若熔断回放 429/502 给
                    # Claude Code，会触发 Claude Code 自己又重试一层（双层重试），
                    # 那才烧额度——所以默认不设上限；用户在 retry_config.json 显式
                    # 配置上限后，达限即回放最后一次错误，不让客户端挂死。
                    cap = check_retry_cap(n429, nerr, t0)
                    if cap is not None:
                        self._inflight_done(stats)
                        self._give_up(cap, path, attempt, resp.status, last_err,
                                      t0, brief=req_brief_t)
                        return
                    # Retry-After 头优先于阶梯退避（限流场景上游更清楚节奏）；
                    # backoff_enabled=False 时不等待也不理 Retry-After（立即重试）
                    ra = parse_retry_after(resp)
                    if ra is not None and RETRY_CFG["backoff_enabled"]:
                        wait = min(ra, MAX_RETRY_AFTER)
                    log.warning("%d on %s %s (attempt %d) -- retry in %.1fs",
                                resp.status, self.command, path, attempt, wait)
                    if not self._sleep_checked(wait):
                        # 睡眠期间客户端断开，立即放弃
                        stats.req_failed("client_gone", path, attempt,
                                         elapsed=time.time() - t0,
                                         brief=req_brief_t)
                        self._inflight_done(stats)
                        return
                    continue

                # 成功：流式/非流式透传并解析 usage
                self._stream_response(resp, conn, stats, t0, attempt,
                                      req_model=req_model, req_brief=req_brief)
                self._inflight_done(stats)  # 请求终结（成功/client_gone/upstream_broke）
                return

            except (http.client.HTTPException, ConnectionError, OSError) as e:
                # 循环内 I/O 全打在上游连接 conn 上，这里的 OSError 是上游断开，
                # 不是客户端断开；客户端断开由循环顶部的 client_alive 兜住。
                # 关键防烧额度：若已从上游拿到响应状态码(got_response)，说明上游可能
                # 已开始生成 token。此时重试会让上游重新生成整个响应，重复计费。
                # 日志实证：上游 200 流式响应中途 "cannot read from timed out object"
                # 被重试，attempt 2 又生成一次 → 9 条请求烧 10+ 条额度。
                if got_response:
                    # 已拿到响应状态码。流式响应中途的上游读异常已在 _stream_response
                    # 内部消化（不会冒泡到这里）。能走到这里说明是 getresponse() 后、
                    # _stream_response 调用前/中的异常，响应头可能已发给客户端。
                    # 绝不回放 502——会在已发的响应里塞 502，Claude Code 解析混乱 +
                    # 触发双层重试烧额度。只记失败，静默结束。
                    log.warning("upstream error after response started on %s %s: %s"
                                " -- not retrying/replaying (would double-charge)",
                                self.command, path, e)
                    stats.req_failed("upstream_error", path, attempt,
                                     status=None, elapsed=time.time() - t0, brief=req_brief_t)
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._inflight_done(stats)
                    return
                # 未拿到响应（连接/请求/getresponse 阶段失败）：无限重试，上游没生成
                # token 不烧额度。客户端断开由 _sleep_checked 兜底立即停。
                # 不熔断回放——回放 502 会触发 Claude Code 自己重试一层（双层重试烧额度）。
                # 防止 socket 泄漏：request/getresponse 失败后 conn 可能已建立连接，
                # 不关闭长时间频繁重试会耗尽句柄。
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                stats.record_retry_error()
                nerr += 1
                if not self._inflight_counted:
                    stats.inflight_inc()
                    self._inflight_counted = True
                cap = check_retry_cap(n429, nerr, t0)
                if cap is not None:
                    self._inflight_done(stats)
                    self._give_up(cap, path, attempt, None, last_err, t0,
                                  conn_err=e,
                                  brief=req_brief_t)
                    return
                log.warning("upstream error on %s %s: %s -- retry in %.1fs",
                            self.command, path, e, wait)
                if not self._sleep_checked(wait):
                    stats.req_failed("client_gone", path, attempt,
                                     elapsed=time.time() - t0, brief=req_brief_t)
                    self._inflight_done(stats)
                    return
                continue

    def _inflight_done(self, stats):
        """请求终结（成功/失败）时，若曾计入在途则减回。保证 in_flight_retries 准确。"""
        if self._inflight_counted:
            stats.inflight_dec()
            self._inflight_counted = False

    def _sleep_checked(self, wait):
        """分块睡眠，每 0.5s 探测客户端是否还在。客户端断开返回 False。"""
        deadline = time.time() + wait
        while True:
            now = time.time()
            if now >= deadline:
                return True
            if not client_alive(self.connection):
                return False
            time.sleep(min(0.5, deadline - now))
        return True

    def _give_up(self, reason, path, attempt, status, last_err, t0,
                 conn_err=None, brief=None):
        """重试上限熔断出口：记录失败，把最后一次上游错误原样回放给客户端，
        不让客户端挂死。last_err=(status, headers, body)；全网络异常无响应时
        合成 502 JSON。brief 为本请求的透传值（不回查共享字段）。"""
        elapsed = time.time() - t0
        stats = self.server.stats
        if last_err is not None:
            st, hdrs, bdy = last_err
        else:
            # 纯网络异常，从未拿到上游响应：合成 502
            st = 502
            err_msg = "upstream unreachable after %d attempts" % attempt
            if conn_err is not None:
                err_msg = "%s: %s" % (err_msg, conn_err)
            bdy = json.dumps({
                "type": "error",
                "error": {"type": "upstream_error",
                          "message": err_msg},
            }).encode("utf-8")
            hdrs = [("Content-Type", "application/json"),
                    ("Content-Length", str(len(bdy)))]
        stats.req_failed(reason, path, attempt, status=st, elapsed=elapsed,
                         brief=brief)
        log.warning("give up on %s %s (attempt %d, reason=%s) -- replay %d",
                    self.command, path, attempt, reason, st)
        try:
            self.send_response(st)
            for key, val in hdrs:
                if key.lower() in HOP_BY_HOP:
                    continue
                self.send_header(key, val)
            self.end_headers()
            self.wfile.write(bdy)
        except (BrokenPipeError, ConnectionResetError):
            # 客户端在熔断回放时已断开，无所谓
            pass

    def _stream_response(self, resp, conn, stats, t0, attempt=0,
                         req_model=None, req_brief=None):
        # req_model/req_brief 由 _forward 透传，用于构造请求级 brief
        # （不回查共享的 last_req_brief，避免并发请求张冠李戴）。
        req_brief_t = (self.command, short_path(self.path), req_model, req_brief)
        client_gone = False
        upstream_broke = False  # 上游流式中途断开（非客户端断开）：记失败但不回放
        try:
            self.send_response(resp.status)
            for key, val in resp.getheaders():
                if key.lower() in HOP_BY_HOP:
                    continue
                self.send_header(key, val)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            # 响应头阶段客户端就断了，标记并跳过转发
            client_gone = True

        content_type = (resp.getheader("Content-Type") or "").lower()
        streaming = "text/event-stream" in content_type
        parser = SSEUsageParser() if streaming else None
        nonstream_body = b"" if not streaming else None
        model = None
        in_tok = 0
        out_tok = 0
        if not client_gone:
            try:
                if streaming:
                    # 流式转发完全不主动探测客户端（client_alive 在 Windows 上对
                    # "正在等待响应"的 socket 不可靠，长思考时上游无数据频繁探测
                    # 会误报累积→截断正常 SSE 输出→Claude Code 收不完整响应
                    # 自己重试→多烧额度）。客户端断开只靠 wfile.write 抛
                    # BrokenPipe/ConnectionReset 检测，可靠且不误断。
                    # 关键：read1 不设短 timeout。短 timeout 会让 socket 进入
                    # timed-out 状态，后续 read1 抛 OSError "cannot read from
                    # timed out object"（不是 socket.timeout，catch 不到）→ 冒泡
                    # → 回放 502 → Claude Code 双层重试烧额度。用连接默认的 600s
                    # 长 timeout 阻塞等上游：上游长思考时阻塞等（正确行为），上游
                    # 发数据时继续，客户端断开时下次 wfile.write 抛异常兜底。
                    while True:
                        try:
                            # read1 读到任何可用数据即返回，不等满 n，
                            # 适合 SSE 流式逐块转发
                            chunk = resp.read1(4096)
                        except (socket.timeout, TimeoutError):
                            # 连接级超时（600s 无任何数据）：上游真断了，结束转发
                            log.warning("upstream idle timeout (600s) during stream"
                                        " on %s %s (attempt %d) -- closing",
                                        self.command, self.path, attempt)
                            upstream_broke = True
                            break
                        except (http.client.HTTPException, OSError) as e:
                            # 上游读异常。流式响应中途，已给客户端发了部分 SSE。
                            # 绝不能冒泡到 _forward 的 got_response 分支回放 502——
                            # 那会在 SSE 流里塞 502，Claude Code 解析混乱 + 触发双层
                            # 重试烧额度。静默结束转发（客户端收到不完整 SSE 会
                            # 自己按断流处理，比 502 回放安全）。
                            log.warning("upstream read error during stream on %s %s"
                                        " (attempt %d): %s -- closing stream",
                                        self.command, self.path, attempt, e)
                            upstream_broke = True
                            break
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if parser is not None:
                            r = parser.feed(chunk)
                            if r is not None:
                                model, in_tok, out_tok = r
                else:
                    data = resp.read()
                    self.wfile.write(data)
                    nonstream_body = data
            except (BrokenPipeError, ConnectionResetError):
                # 转发循环中客户端断开：立即跳出，不再继续读上游
                client_gone = True
            except Exception as e:
                # 兜底：转发/解析中任何意外异常（如 SSEUsageParser.feed 对畸形
                # 事件抛出的异常）。绝不冒泡到 _forward 的 got_response 分支——
                # 那会跳过 _inflight_done 导致 in_flight 永久卡死，且可能回放
                # 502 触发双层重试烧额度。按上游中途断开处理：静默结束，
                # 已消耗 token 如实入账，conn 由 finally 关闭防泄漏。
                log.warning("unexpected error during stream on %s %s"
                            " (attempt %d): %s -- closing stream",
                            self.command, self.path, attempt, e)
                upstream_broke = True
        # finally：无论是否 client_gone/upstream_broke/异常都关闭上游连接，
        # 停止上游继续生成 token（省额度）。放 try/finally 确保任何异常路径
        # 都不泄漏 conn（否则句柄耗尽 + in_flight 卡死 + 线程死亡）。
        try:
            conn.close()
        except Exception:
            pass

        if client_gone:
            # 客户端断开：按失败记，已消耗 token 如实入账
            elapsed = time.time() - t0
            stats.req_failed("client_gone", self.path, attempt,
                             status=resp.status, elapsed=elapsed,
                             in_tok=in_tok, out_tok=out_tok, brief=req_brief_t)
            log.info("client gone during stream on %s %s (attempt %d)",
                     self.command, self.path, attempt)
            return

        if upstream_broke:
            # 上游流式中途断开：已给客户端发了部分 SSE，不能回放 502（会塞进 SSE 流
            # 导致 Claude Code 解析混乱 + 双层重试烧额度）。按失败记，已消耗 token
            # 如实入账，静默结束。客户端收到不完整 SSE 会自己按断流处理。
            elapsed = time.time() - t0
            stats.req_failed("upstream_error", self.path, attempt,
                             status=resp.status, elapsed=elapsed,
                             in_tok=in_tok, out_tok=out_tok, brief=req_brief_t)
            log.warning("upstream broke mid-stream on %s %s (attempt %d, %.1fs, "
                        "in=%d out=%d) -- not replaying",
                        self.command, short_path(self.path), attempt, elapsed,
                        in_tok, out_tok)
            return

        # 非流式：从完整 body 解析 usage/model
        if not streaming and nonstream_body:
            try:
                d = json.loads(nonstream_body.decode("utf-8"))
                model = d.get("model") or model
                usage = d.get("usage", {})
                # 同 SSEUsageParser：input_tokens + cache_creation + cache_read
                # 才是真实输入，详见 message_start 分支注释。
                in_tok = (
                    int(usage.get("input_tokens", 0) or 0)
                    + int(usage.get("cache_creation_input_tokens", 0) or 0)
                    + int(usage.get("cache_read_input_tokens", 0) or 0)
                ) or in_tok
                out_tok = usage.get("output_tokens", 0) or out_tok
            except (ValueError, UnicodeDecodeError):
                pass
        elif streaming and parser is not None:
            model = parser.model or model
            in_tok = parser.input_tokens or in_tok
            out_tok = parser.output_tokens or out_tok

        elapsed = time.time() - t0
        stats.req_success(model, in_tok, out_tok, elapsed, brief=req_brief_t)
        log.info("ok %s %s -> %d (attempt %d, %.1fs, in=%d out=%d)",
                 self.command, short_path(self.path), resp.status,
                 attempt, elapsed, in_tok, out_tok)

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_DELETE = _forward
    do_PATCH = _forward
    do_OPTIONS = _forward
    do_HEAD = _forward


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


# ---- 格式化辅助 ----------------------------------------------------
def fmt_uptime(sec):
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    if d:
        return "%dd %dh %dm" % (d, h, m)
    if h:
        return "%dh %dm %ds" % (h, m, s)
    return "%dm %ds" % (m, s)


def fmt_tok(n):
    """token 数格式化：>1000 用 k，>1000000 用 M。"""
    if n >= 1000000:
        return "%.1fM" % (n / 1000000.0)
    if n >= 1000:
        return "%.1fk" % (n / 1000.0)
    return str(n)


# ---- 工厂与启动辅助 ------------------------------------------------
def parse_upstream(s):
    """解析 host:port 字符串为 (host, port)。无端口默认 80。"""
    if ":" in s:
        host, port = s.rsplit(":", 1)
        return host, int(port)
    return s, 80


def create_server(host="127.0.0.1", port=37349, upstream="lanz.hikvision.com:80"):
    """组装一个带好上游/stats/stop_event 的代理 server。

    upstream 传 "host:port" 字符串（http）或 (host, port, scheme) 三元组
    （v2.26：上游随用户配置的直连 base_url 动态推导，支持 https）。
    返回 (server, stats, stop_event)。默认 host=127.0.0.1（桌面机无需 LAN 暴露）。
    调用方拿到后用 server_thread_start() 起线程，stop() 时 stop_event.set() + shutdown。
    """
    if isinstance(upstream, str):
        upstream = (*parse_upstream(upstream), "http")
    upstream_host, upstream_port, upstream_scheme = upstream
    stats = Stats()
    server = ThreadingHTTPServer((host, port), RetryProxyHandler)
    server.upstream_host = upstream_host
    server.upstream_port = upstream_port
    server.upstream_scheme = (upstream_scheme or "http").lower()
    server.stats = stats
    stop_event = threading.Event()
    server.stop_event = stop_event  # 供 /__proxy/shutdown 接口唤醒用
    return server, stats, stop_event


def server_thread_start(server, stop_event=None):
    """起 daemon 线程跑 serve_forever(poll_interval=0.2)，让 shutdown 响应快。
    返回线程对象。"""
    if stop_event is None:
        stop_event = getattr(server, "stop_event", None)
    t = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    t.start()
    return t


def stop_server(server, stop_event=None):
    """优雅停止：stop_event.set() + server.shutdown() + server_close()。
    shutdown() 会阻塞等 serve_forever 返回（~0.2s），不要在 server 线程内调用（会死锁）。"""
    if stop_event is None:
        stop_event = getattr(server, "stop_event", None)
    if stop_event is not None:
        stop_event.set()
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass


# ---- CLI 单跑（无 UI，纯代理 + 日志，便于调试）-----------------------
def main():
    import argparse
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Claude Code 重试代理核心（无仪表盘）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=37349, help="监听端口 (默认 37349)")
    parser.add_argument("--upstream", default="lanz.hikvision.com:80",
                        help="上游 host:port (默认 lanz.hikvision.com:80)")
    args = parser.parse_args()

    server, stats, stop_event = create_server(args.host, args.port, args.upstream)
    upstream_host, upstream_port = server.upstream_host, server.upstream_port
    log.info("Claude retry proxy (core) listening on %s:%d -> %s:%d",
             args.host, args.port, upstream_host, upstream_port)
    log.info("阶梯退避: 1.0s->3.0s->5.0s->...->10.0s(封顶,带抖动), 429/5xx/网络异常无限重试, 客户端断开即停, 已拿到响应后不重试")
    log.info("Point Claude Code at: http://127.0.0.1:%d/v3/anthropic/model", args.port)
    log.info("Ctrl-C 退出")

    server_thread_start(server, stop_event)
    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    stop_server(server, stop_event)
    log.info("bye.")


if __name__ == "__main__":
    main()
