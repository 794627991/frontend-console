# -*- coding: utf-8 -*-
"""后端日志环形缓冲（用户需求：不弹 cmd 黑框，点版本号看后端日志）。

用户定调（2.4.4）：
- **不写磁盘**，只驻内存，进程退出即消失
- **容量按内存字节计**：默认 10MB（不是按行数）——行数上限会因单行长短
  差异导致实际占用忽大忽小，按字节才可控
- **本功能是后续指定的调试手段**：任何报错、警告、有用信息都应往这里放。
  为此除接管 stdout/stderr 外，还提供 `log(tag, msg)` / `debug()` /
  `warn()` / `error()` / `exception()` 主动埋点接口（详见文件尾）。

三层收口：
1. 接管 sys.stdout / sys.stderr —— 原有裸 print 零改动即全进缓冲
2. `log()` 系列 —— 新代码/关键路径主动埋点，带模块标签
3. `install_logging_bridge()` —— 把标准库 logging 也桥接进来（第三方库
   如 paramiko / werkzeug / urllib3 的日志一并可见）

为什么以接管流为主：本工程日志几乎全是裸 print（main.py 20+ 处、src/* 大量），
改成 logging 要动几十个文件且容易漏。接管 stdout/stderr 能一次覆盖全部输出。
"""
import collections
import io
import re
import sys
import threading
import time
import traceback

# 容量按「字符数」近似内存占用（Python str 每字符 1~4 字节；中文多为 2 字节
# 的 UCS-2 或 4 字节 UCS-4）。取 1 字符 ≈ 1 字节的保守估计，10MB ≈ 千万字符，
# 实际内存可能略高，但同一量级，远好于「2000 行」这种与内容无关的上限。
_MAX_CHARS = 10 * 1024 * 1024     # 10MB（按字符计量，近似）
_MAX_LINES = 0                    # 0 = 不按行数限制，纯按字节
_MAX_LINE_CHARS = 8000            # 单行钳位：防一条巨型输出吃掉整个缓冲
_buf = collections.deque()
_buf_chars = 0                    # 当前占用的字符数（与 _buf 同步维护）
_lock = threading.Lock()
_seq = 0
_installed = False
_orig_stdout = None
_orig_stderr = None
_dropped = 0                      # 因超容量被丢弃的行数（界面提示用）

# 级别粗判（保持低成本：只做行首关键词匹配，不解析整行）
_ERR_RE = re.compile(r"^\s*(\[错误\]|\[error\]|ERROR\b|Traceback \(most recent|"
                     r"Exception\b|\w*Error\b:|FATAL|CRITICAL)", re.I)
_WARN_RE = re.compile(r"^\s*(\[警告\]|\[warn\]|WARN\b|⚠|DeprecationWarning)", re.I)
# werkzeug 的逐请求访问日志（127.0.0.1 - - "GET /api/xxx" 200 -）——轮询
# 日志面板自己每 2s 就产生一条，会把启动/错误信息淹没。这类噪音不进缓冲
# （仍透传到控制台/磁盘，需要时照样能看）。
_ACCESS_RE = re.compile(r"^\s*\d+\.\d+\.\d+\.\d+ - - \[[^\]]*\] \"(GET|POST|PUT|"
                        r"DELETE|HEAD|OPTIONS|PATCH) ")


def _classify(line):
    if _ERR_RE.search(line):
        return "error"
    if _WARN_RE.search(line):
        return "warn"
    return "info"


def _append(rec):
    """把一条记录塞进环形缓冲，按字符数淘汰最旧。调用方必须持锁。"""
    global _buf_chars, _dropped
    text = rec.get("text") or ""
    if len(text) > _MAX_LINE_CHARS:
        text = text[:_MAX_LINE_CHARS] + " …（单行超长已截断）"
        rec["text"] = text
    rec["len"] = len(text) + len(rec.get("tag") or "")
    _buf.append(rec)
    _buf_chars += rec["len"]
    # 超出容量：从头丢，直到落回 10MB 以内
    while _buf_chars > _MAX_CHARS and _buf:
        old = _buf.popleft()
        _buf_chars -= old.get("len") or 0
        _dropped += 1


def _emit(line, stream):
    """把一行 stdout/stderr 写进缓冲。"""
    global _seq
    if not line:
        return
    text = line.rstrip("\r\n")
    if not text:
        return
    if _ACCESS_RE.match(text):
        return          # werkzeug 访问日志：噪音，不进缓冲（仍透传到原流）
    with _lock:
        _seq += 1
        _append({"seq": _seq, "ts": _ts(), "level": _classify(text),
                 "src": stream, "tag": "", "text": text})


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def log(tag, msg, level="info"):
    """主动埋点（本功能是「指定的调试手段」，关键路径都该写这里）。

    tag：模块/子系统短名（如 "web_tabs" / "shell_conn" / "ssh"），界面按它
         做分组和过滤；msg：任意对象，会 str() 化。
    返回 None；不可抛出——日志本身绝不该让业务失败。
    """
    global _seq
    try:
        text = msg if isinstance(msg, str) else repr(msg)
    except Exception:
        text = "<unprintable>"
    try:
        with _lock:
            _seq += 1
            _append({"seq": _seq, "ts": _ts(),
                     "level": level if level in ("info", "warn", "error")
                     else "info",
                     "src": "log", "tag": str(tag or "")[:40], "text": text})
    except Exception:
        pass


def debug(tag, msg):
    log(tag, msg, "info")


def warn(tag, msg):
    log(tag, msg, "warn")


def error(tag, msg):
    log(tag, msg, "error")


def exception(tag, msg="", _exc=True):
    """记录异常（自动带 traceback）。在 except 块里调用。"""
    try:
        tb = traceback.format_exc() if _exc else ""
    except Exception:
        tb = ""
    log(tag, (str(msg) + ("\n" if msg else "") + tb).rstrip(), "error")


class _TeeStream(io.TextIOBase):
    """写一份到环形缓冲，一份透传给原始流（控制台/日志文件）。"""

    def __init__(self, orig, stream):
        self._orig = orig
        self._stream = stream
        self._partial = ""

    def writable(self):
        return True

    def write(self, s):
        if not isinstance(s, str):
            try:
                s = str(s)
            except Exception:
                return 0
        # 按行切：未换行的残片攒着，凑成整行再入缓冲（避免半行噪音）
        self._partial += s
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            _emit(line, self._stream)
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self):
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

    def fileno(self):
        if self._orig is not None:
            try:
                return self._orig.fileno()
            except Exception:
                pass
        raise OSError("no fileno")

    def isatty(self):
        if self._orig is not None:
            try:
                return self._orig.isatty()
            except Exception:
                pass
        return False

    @property
    def encoding(self):
        return getattr(self._orig, "encoding", "utf-8") or "utf-8"

    @property
    def errors(self):
        return getattr(self._orig, "errors", "replace")

    @property
    def buffer(self):
        """原始字节流。有代码直接写 sys.stdout.buffer（如 UTF-8 强制输出），
        必须透传，否则 AttributeError。"""
        return getattr(self._orig, "buffer", None)


def install(max_chars=None):
    """接管 stdout/stderr（幂等）。main.py 在最早时机调用一次。"""
    global _installed, _orig_stdout, _orig_stderr, _MAX_CHARS
    if _installed:
        return
    if max_chars and isinstance(max_chars, int) and max_chars > 0:
        _MAX_CHARS = max_chars
    _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
    sys.stdout = _TeeStream(_orig_stdout, "stdout")
    sys.stderr = _TeeStream(_orig_stderr, "stderr")
    _installed = True


class _LoggingBridge:
    """标准库 logging → 缓冲桥（第三方库日志可见）。"""
    _PREFIX_TAG_RE = re.compile(r"^([\w.\-]+):?\s*")

    def __init__(self):
        try:
            import logging
            self._logging = logging
        except Exception:
            self._logging = None

    def install(self, level=None):
        if self._logging is None:
            return False
        try:
            lv = level or self._logging.INFO
            root = self._logging.getLogger()
            root.addHandler(_make_bridge_handler(self._logging)())
            if root.level > lv or root.level == 0:
                root.setLevel(lv)
            return True
        except Exception:
            return False


def _make_bridge_handler(logging_mod):
    """构造 logging.Handler 子类（必须真继承 Handler——addHandler 之后
    框架会调 handle()/createLock()/acquire()，鸭子类型不够）。

    运行时构造而非模块级 class，是为了让 logging 不可用时模块仍能导入。
    """
    class _BridgeHandler(logging_mod.Handler):
        def __init__(self):
            super().__init__()

        def _level_of(self, levelno):
            try:
                if levelno >= logging_mod.ERROR:
                    return "error"
                if levelno >= logging_mod.WARNING:
                    return "warn"
            except Exception:
                pass
            return "info"

        def emit(self, record):
            try:
                name = (record.name or "").strip()
                msg = record.getMessage()
                # werkzeug 访问日志已由 _ACCESS_RE 在流层过滤；logging 桥
                # 再挡一道（werkzeug 有时走 logging 而非流）
                if name == "werkzeug" and _ACCESS_RE.match(msg):
                    return
                if record.exc_info:
                    msg += "\n" + "".join(
                        traceback.format_exception(*record.exc_info)).rstrip()
                log(name or "logging", msg, self._level_of(record.levelno))
            except Exception:
                pass
    return _BridgeHandler


_logging_bridge = _LoggingBridge()


def install_logging_bridge(level=None):
    """把标准库 logging 桥接进缓冲（第三方库日志可见）。幂等。"""
    return _logging_bridge.install(level)


def install_excepthooks():
    """装全局未捕获异常钩子（主线程 + 所有线程）。

    用户定调「任何报错都往日志缓冲里放」。GUI 版没有控制台，线程里抛的
    异常原来只进 sys.stderr（= 某个没人看的 pipe），本次让它们一律落进
    缓冲。保留原钩子的行为（若之前有人装过）——先记日志再交回去。
    """
    try:
        prev = getattr(sys, "excepthook", None)
        sys.excepthook = lambda t, v, tb: (
            _hook_record("主线程", t, v, tb),
            prev(t, v, tb) if prev else None)
    except Exception:
        pass
    try:
        import threading

        def _thook(args):
            if getattr(args, "exc_value", None) is not None and \
                    args.exc_type is not None:
                _hook_record("线程 %s" % getattr(args.thread, "name", "?"),
                             args.exc_type, args.exc_value, args.exc_traceback)
            # 交回默认（打印到 stderr，同时也会进缓冲，去重靠 _emit 的同一
            # 逻辑不重复也没关系——这里只保证「一定有一条带 traceback 的」）
        threading.excepthook = _thook
    except Exception:
        pass


def _hook_record(where, et, ev, tb):
    try:
        txt = "未捕获异常（%s）：%s: %s\n%s" % (
            where, getattr(et, "__name__", et), ev,
            "".join(traceback.format_exception(et, ev, tb)).rstrip())
        log("crash", txt, "error")
    except Exception:
        pass


def snapshot(since=0, limit=2000):
    """取日志快照：seq > since 的最后 limit 条。返回 {lines, last_seq, ...}。"""
    with _lock:
        items = [dict(x) for x in _buf if x["seq"] > int(since or 0)]
        total_chars = _buf_chars
        dropped = _dropped
        last = _seq
        n = len(_buf)
    if limit and len(items) > limit:
        items = items[-limit:]
    for it in items:
        it.pop("len", None)          # 内部字段不外泄
    return {"lines": items, "last_seq": last,
            "capacity_chars": _MAX_CHARS,
            "used_chars": total_chars,
            "entries": n,
            "dropped": dropped,
            "installed": _installed}


def clear():
    global _buf_chars, _dropped
    with _lock:
        _buf.clear()
        _buf_chars = 0
        _dropped = 0
    return True


def installed():
    return _installed


def stats():
    with _lock:
        return {"capacity_chars": _MAX_CHARS, "used_chars": _buf_chars,
                "entries": len(_buf), "dropped": _dropped,
                "installed": _installed}
