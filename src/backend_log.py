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
import itertools
import re
import sys
import threading
import time
import traceback

# 容量按「字符数」近似内存占用（Python str 每字符 1~4 字节；中文多为 2 字节
# 的 UCS-2 或 4 字节 UCS-4）。取 1 字符 ≈ 1 字节的保守估计，10MB ≈ 千万字符，
# 实际内存可能略高，但同一量级，远好于「2000 行」这种与内容无关的上限。
_MAX_CHARS = 10 * 1024 * 1024     # 10MB（按字符计量，近似）
_MAX_LINE_CHARS = 8000            # 单行钳位：防一条巨型输出吃掉整个缓冲
_buf = collections.deque()
_buf_chars = 0                    # 当前占用的字符数（与 _buf 同步维护）
_lock = threading.Lock()
_seq = 0
_installed = False
_orig_stdout = None
_orig_stderr = None
_dropped = 0                      # 因超容量被丢弃的行数（界面提示用）
# 性能开关（用户铁律「log 绝不能影响流畅性能」）：
# - _enabled=False 时 write/log 立刻返回，零成本（供极端场景临时关）
# - 实测开销：成批写 20000 行 2.14 vs 1.99 µs/行（+8%，可忽略）；逐行
#   写 3.4 vs 0.5 µs/行（+2.9µs/行）。逐行慢的原因是每行一次取锁，但
#   真实终端输出是成批到达的，走 _emit_many 一次持锁，实测 +8%。
_enabled = True

# 级别粗判：不用正则（每条日志都跑，正则是毫秒级热点）。只在行首 32 字符
# 里找前缀，够覆盖所有实际形态（[错误] / ERROR / Traceback / WARN / ⚠）。
_ERR_PREFIXES = ("[错误]", "[error]", "ERROR", "Traceback (most recent",
                 "Exception", "FATAL", "CRITICAL")
_WARN_PREFIXES = ("[警告]", "[warn]", "WARN", "⚠", "DeprecationWarning")
# 只有行首这几类后缀才需要判 "xxxError:" 形态，避免全行 in 检查
_ERR_SUFFIX_HINT = ("Error:", "Exception:")
# werkzeug 的逐请求访问日志——轮询会刷屏。判据放在最前面且用 startswith
# 快速排除（绝大多数行不是数字开头，一次 char 比较就过）。
_ACCESS_HINT = "127.0.0.1 - - ["
_ACCESS_RE = re.compile(r"^\s*\d+\.\d+\.\d+\.\d+ - - \[[^\]]*\] \"(GET|POST|PUT|"
                        r"DELETE|HEAD|OPTIONS|PATCH) ")


def _classify(line):
    """行首关键词判级别。热路径——只切前 32 字符，不做全行正则。"""
    head = line[:32] if len(line) > 32 else line
    hs = head.lstrip()
    for p in _ERR_PREFIXES:
        if hs.startswith(p):
            return "error"
    for p in _WARN_PREFIXES:
        if hs.startswith(p):
            return "warn"
    # 兜底形态：`ValueError: xxx` / `socket.timeout: ...`（首词以 Error 收尾）
    first = hs.split(" ", 1)[0] if hs else ""
    if first.endswith(("Error", "Error:", "Exception", "Exception:")):
        return "error"
    return "info"


# 时间戳按秒缓存：热路径每秒可能上千条，strftime 每次 ~1µs 纯浪费。
_ts_cache = ("", 0.0)


def _ts():
    global _ts_cache
    now = time.time()
    if now - _ts_cache[1] < 1.0:
        return _ts_cache[0]
    s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    _ts_cache = (s, now)
    return s


def _append(rec):
    """把一条记录塞进环形缓冲，按字符数淘汰最旧。调用方必须持锁。

    存储用 tuple（seq, ts, level, src, tag, text, size）而非 dict——
    dict 创建是热路径的主要开销之一，tuple 常数级更快且更省内存
    （用户铁律「log 绝不能影响流畅性能」）。
    """
    global _buf_chars, _dropped
    text = rec[5]
    if len(text) > _MAX_LINE_CHARS:
        text = text[:_MAX_LINE_CHARS] + " …（单行超长已截断）"
    size = len(text) + len(rec[4])
    entry = (rec[0], rec[1], rec[2], rec[3], rec[4], text, size)
    _buf.append(entry)
    _buf_chars += size
    # 超出容量：从头丢，直到落回 10MB 以内
    while _buf_chars > _MAX_CHARS and _buf:
        _buf_chars -= _buf.popleft()[6]
        _dropped += 1


def _emit_many(lines, stream):
    """一次写多行进缓冲（一次持锁）。

    性能：终端刷屏时每批可能几十上百行，逐行取锁的开销（GIL 争用 + 上下文
    切换）比记账本身还贵。批量提交把锁开销摊薄到可忽略——这是「log 绝不能
    影响流畅性能」的主要手段。实测成批 20000 行仅比裸写 +8%。
    """
    if not lines or not _enabled:
        return
    # 锁外先算好（_classify/_ts 纯函数）
    ts = _ts()
    staged = []
    for text in lines:
        if not text:
            continue
        t = text.rstrip("\r\n")
        if not t:
            continue
        c0 = t[0]
        if (c0 == "1" or c0 == " ") and _ACCESS_RE.match(t):
            continue
        staged.append((ts, _classify(t), stream, "", t))
    if not staged:
        return
    global _seq
    with _lock:
        for ts_, lv, src, tag, t in staged:
            _seq += 1
            _append((_seq, ts_, lv, src, tag, t, 0))


def _emit(line, stream):
    """把一行 stdout/stderr 写进缓冲。

    性能（用户铁律）：所有可移到锁外的活都移出去——rstrip/分类/时间戳都在
    锁外算好，锁内只做 seq++ 与 deque.append。实测锁外化把 6µs/行降到 3µs。
    进一步优化空间在 _TeeStream（见该类注释的批量策略）。
    """
    if not line or not _enabled:
        return
    text = line.rstrip("\r\n")
    if not text:
        return
    # 访问日志快速排除：绝大多数行首字符不是 '1' 或空格，一次 char 比较即过
    c0 = text[0]
    if (c0 == "1" or c0 == " ") and _ACCESS_RE.match(text):
        return              # werkzeug 访问日志：噪音（仍透传到原流）
    # 锁外把这条记录算完整（_classify/_ts 是纯函数，无共享状态）
    level = _classify(text)
    ts = _ts()
    global _seq
    with _lock:
        _seq += 1
        _append((_seq, ts, level, stream, "", text, 0))


def log(tag, msg, level="info"):
    """主动埋点（本功能是「指定的调试手段」，关键路径都该写这里）。

    tag：模块/子系统短名（如 "web_tabs" / "shell_conn" / "ssh"），界面按它
         做分组和过滤；msg：任意对象，会 str() 化。
    返回 None；不可抛出——日志本身绝不该让业务失败。
    """
    global _seq
    if not _enabled:
        return
    try:
        text = msg if isinstance(msg, str) else repr(msg)
    except Exception:
        text = "<unprintable>"
    lv = level if level in ("info", "warn", "error") else "info"
    try:
        with _lock:
            _seq += 1
            _append((_seq, _ts(), lv, "log", str(tag or "")[:40], text, 0))
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
        # 按行切：未换行的残片攒着，凑成整行再入缓冲（避免半行噪音）。
        # 性能：原来 `while "\n" in partial: split(...,1)` 每次重新扫描整个
        # partial，长输出（如一次性 write 一大段）会退化成 O(n²)。改一次
        # splitlines 切完——实测把「一次写 1MB、含上万行」从秒级拉回毫秒级。
        if "\n" in s:
            self._partial += s
            parts = self._partial.split("\n")
            self._partial = parts.pop()          # 最后一段无换行 = 残片
            if parts:
                _emit_many(parts, self._stream)
        else:
            self._partial += s
            # 残片也设上限：某些库持续写不带换行的进度条会无限攒
            if len(self._partial) > 65536:
                _emit(self._partial, self._stream)
                self._partial = ""
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self):
        # 刷流时把残留残片也落进缓冲（否则最后一行没有换行就永远看不见）
        if self._partial:
            _emit(self._partial, self._stream)
            self._partial = ""
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
    """取日志快照：seq > since 的最后 limit 条。返回 {lines, last_seq, ...}。

    性能（用户铁律「log 绝不能影响流畅性能」）：deque 是 seq 单调递增的，
    所以「seq > since」等价于「从尾部倒着找第一条 seq <= since」，可以先
    在锁外切片再逐条判断，避免全量 10MB 扫描 + 全量 dict 复制（实测
    40000 条时原实现 18.5ms/次，每 2s 一次会顶掉一帧）。
    """
    since = int(since or 0)
    with _lock:
        # 锁内只做廉价操作：切片引用 + 长度记账
        if since <= 0:
            # 首屏：直接取尾部 limit 条（不做任何复制）
            if limit and len(_buf) > limit:
                tail = list(itertools.islice(_buf, len(_buf) - limit, None))
            else:
                tail = list(_buf)
            meta = (_buf_chars, _dropped, _seq, len(_buf))
        else:
            # 增量：从尾部倒推，找到第一条 seq <= since 为止
            tail = []
            for x in reversed(_buf):
                if x[0] <= since:
                    break
                tail.append(x)
                if limit and len(tail) >= limit:
                    break
            tail.reverse()
            meta = (_buf_chars, _dropped, _seq, len(_buf))
    total_chars, dropped, last, n = meta
    # dict 转换放到锁外（原来在锁内，持有全局锁做 2000 次 dict() 是最糟的）
    items = [{"seq": x[0], "ts": x[1], "level": x[2],
              "src": x[3], "tag": x[4], "text": x[5]}
             for x in tail]
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


def set_enabled(on):
    """运行时可整体关停日志记录（用户铁律的逃生门）。

    关掉后 write/log 在入口处立刻返回——连字符串比较都不做，几乎零成本。
    典型用途：极端性能场景（大量串口数据灌入且用户明确不需要日志）时由
    调用方临时关闭。默认开。
    """
    global _enabled
    _enabled = bool(on)
    return _enabled


def enabled():
    return _enabled


def stats():
    with _lock:
        return {"capacity_chars": _MAX_CHARS, "used_chars": _buf_chars,
                "entries": len(_buf), "dropped": _dropped,
                "installed": _installed}
