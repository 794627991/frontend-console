# -*- coding: utf-8 -*-
"""后端日志环形缓冲（用户需求：不弹 cmd 黑框，点版本号看后端日志）。

设计：
- 只驻内存，不写磁盘（用户明指定）。进程退出即消失。
- 定长环形：默认 2000 条，超出丢最旧——长期运行不会吃内存。
- 同时接管 sys.stdout / sys.stderr：原来的 print 全部进缓冲，黑框里能看到
  的东西在界面上也能看到。原流向（控制台/已重定向的文件）保留一份转发，
  不破坏现有排查习惯。
- 每条带时间戳、级别、来源流（stdout/stderr）。级别按行首关键词粗判
  （[错误]/ERROR/Traceback 等 → error；[警告]/WARN → warn），够界面着色用。

为什么不用 logging 模块：本工程日志几乎全是裸 print（main.py 全仓 20+ 处
print，src/* 也大量如此），改成 logging 要动几十个文件且容易漏。接管
stdout/stderr 是唯一能一次覆盖全部输出的做法。
"""
import collections
import io
import re
import sys
import threading
import time

_MAX_LINES = 2000
_buf = collections.deque(maxlen=_MAX_LINES)
_lock = threading.Lock()
_seq = 0
_installed = False
_orig_stdout = None
_orig_stderr = None

# 级别粗判（保持低成本：只做行首关键词匹配，不解析整行）
_ERR_RE = re.compile(r"^\s*(\[错误\]|\[error\]|ERROR\b|Traceback \(most recent|"
                     r"Exception\b|\w*Error\b:|FATAL)", re.I)
_WARN_RE = re.compile(r"^\s*(\[警告\]|\[warn\]|WARN\b|⚠)", re.I)
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


def _emit(line, stream):
    """把一行写进环形缓冲。"""
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
        _buf.append({
            "seq": _seq,
            "ts": time.strftime("%H:%M:%S", time.localtime()),
            "level": _classify(text),
            "src": stream,
            "text": text[:4000],     # 单行钳位，防一条超大输出吃掉整个缓冲
        })


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


def install(max_lines=None):
    """接管 stdout/stderr（幂等）。main.py 在最早时机调用一次。"""
    global _installed, _orig_stdout, _orig_stderr, _MAX_LINES, _buf
    if _installed:
        return
    if max_lines and isinstance(max_lines, int) and max_lines > 0:
        _MAX_LINES = max_lines
        _buf = collections.deque(_buf, maxlen=_MAX_LINES)
    _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
    sys.stdout = _TeeStream(_orig_stdout, "stdout")
    sys.stderr = _TeeStream(_orig_stderr, "stderr")
    _installed = True


def snapshot(since=0, limit=500):
    """取日志快照：seq > since 的最后 limit 条。返回 {lines, last_seq}。"""
    with _lock:
        items = [dict(x) for x in _buf if x["seq"] > int(since or 0)]
    if limit and len(items) > limit:
        items = items[-limit:]
    return {"lines": items, "last_seq": _seq, "capacity": _MAX_LINES,
            "installed": _installed}


def clear():
    with _lock:
        _buf.clear()
    return True


def installed():
    return _installed
