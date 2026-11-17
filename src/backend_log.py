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
# a601 对抗审计：字符记账只算文本长度，而每条记录至少占 ~144B（tuple + str
# 头）。实测 1 字符/行的极端场景下，「10MB 记账」的真实 RSS 是 307MB（30×），
# 24 字符典型行是 107MB（10×）。用户要的是「10MB 内存」，所以再加一道条数
# 硬上限，把最坏放大锁在几十 MB 量级。
_MAX_ENTRIES = 200000
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
_excepthooks_installed = False
# 安装类操作的专用锁（与缓冲区 _lock 分开：install 时不持有数据锁，
# 避免任何嵌套/顺序问题）
_install_lock = threading.Lock()

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
_ACCESS_RE = re.compile(r"^\s*(?:\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]{2,}) - - "
                        r"\[[^\]]*\] \"(GET|POST|PUT|"
                        r"DELETE|HEAD|OPTIONS|PATCH) ")

# 敏感信息脱敏（a600/a601 对抗审计）：日志面板会满屏展示、还能一键复制/
# 导出成文件发给同事或贴进工单——明文密码/令牌/密钥带出去是真实的信息外泄。
# 只在命中可疑关键字时才跑正则（绝大多数行不含这些词，热路径近乎零成本）。
# a601：粗筛曾用大小写敏感的 `in`，只列了首字母大写形态，实测 52 个变形里
# 29 个泄露（PASSWORD= / PaSsWoRd= / TOKEN= 全漏）。改为 lower() 一次后
# 用同一份关键字表判断——副本成本 ~1.2µs/行，可接受。
_SECRET_HINTS = ("password", "passwd", "pwd", "token", "secret", "api_key",
                 "apikey", "api-key", "access_key", "access-key",
                 "private_key", "private-key", "authorization",
                 "cookie", "session_id", "bearer", "basic ", "jwt",
                 "密码", "口令", "密钥")
# 值：可选引号包裹 / 非空白；key 两侧允许引号（JSON 形态 "password":"x"）；分隔符含全角
_SECRET_RE = re.compile(
    r"(?i)[\"']?\b(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|cookie|session[_-]?id)[\"']?"
    r"\s*[:=：＝]\s*"
    r"(\"[^\"]*\"|'[^']*'|[^\s,，。；;）)]+)")
_CN_SECRET_RE = re.compile(
    r"(密码|口令|密钥)\s*(?:[:：=＝为是]\s*)?"
    r"(\"[^\"]*\"|'[^']*'|[^\s,，。；;）)）]+)")
# a616（疯狗审计 v3 重炮二）：**空格分隔**形态——`--password hunter2`、
# `password mypass`、`--token abc123`。原实现的分隔符类只有 [:=：＝]，空格
# 形态整行穿透（实测 `--password hunter2 user=admin` 原样入库、原样可导出）。
# 值限定为 ASCII 可见字符且 ≥6 位：中文词（「password 错误」「token 无效」）
# 一律不碰，宁可漏抹也不把正常日志抹成星号。
_SECRET_SPACE_RE = re.compile(
    r"(?i)(?:(?<=[\s\-])|^)(?:--)?"
    r"(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|"
    r"private[_-]?key)[\"']?\s*(?:[:=：＝]\s*)?"
    r"(\"[^\"]{6,}\"|'[^']{6,}'|[A-Za-z0-9._~+/=!@#%^&*$\-]{6,})")
# HTTP 认证头 / 裸令牌：`Bearer xxx` / `Basic xxx` / `token eyJ...`
# bearer/basic 的令牌通常 ≥8 字符；裸 token 要 ≥16 才动手，避免误伤
# 「token 无效」这类正常短语。
_BEARER_RE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+([A-Za-z0-9._~+/=-]{8,})")
_BARE_TOKEN_RE = re.compile(
    r"(?i)\btoken\s+([A-Za-z0-9._~+/=-]{16,})")
# 连接串里的 userinfo 密码：`scheme://user:pass@host`
_URL_PASS_RE = re.compile(r"(://[^:/\s@]+:)([^@\s/]+)(@)")


def _redact(text):
    """把 `password=xxx` / `"token":"x"` / `密码：xxx` / `Bearer x` 抹成 ***。

    性能：超长行先按「将入库」的长度截断再跑正则——原来在截断前对 10MB
    单行跑正则，实测含 token 的巨行要 1.15 秒，把调用线程卡住（违反性能
    铁律）。多行文本按行切分逐行处理，避免 `\\S+` 跨行吃掉 traceback 首行。
    """
    try:
        if not _has_secret_hint(text):
            return text
        if "\n" in text:
            # 逐行脱敏：`\\S+` 对整段跑会把下一行的「Traceback (most recent」
            # 当成密钥值整词抹掉（实测 exception() 的异常类型行消失）。
            return "\n".join(_redact_line(x) for x in text.split("\n"))
        return _redact_line(text)
    except Exception:
        return text


def _redact_line(text):
    if len(text) > _MAX_LINE_CHARS:
        text = text[:_MAX_LINE_CHARS]
    text = _URL_PASS_RE.sub(lambda m: m.group(1) + "***" + m.group(3), text)
    text = _BEARER_RE.sub("***", text)
    text = _BARE_TOKEN_RE.sub("token ***", text)
    text = _SECRET_RE.sub(lambda m: m.group(1) + "=***", text)
    text = _CN_SECRET_RE.sub(lambda m: m.group(1) + "=***", text)
    text = _SECRET_SPACE_RE.sub(lambda m: m.group(1) + " ***", text)
    return text


def _has_secret_hint(text):
    """粗筛：是否可能含敏感关键字（大小写无关）。

    性能（每行都跑）：实测 `lower()+any(in)` 1.52µs/行，与无副本的
    `any(in)` 1.49µs/行几乎相同——`str.lower()` 在 C 层复制极快，不值得
    为省它引入大小写判断的复杂度。这里只做一次副本 + 一次线性扫描。
    另加一条结构判断：连接串 `://user:pass@host` 没有关键字。
    """
    low = text.lower()
    for h in _SECRET_HINTS:
        if h in low:
            return True
    return "://" in low and "@" in low


def _classify(line):
    """行首关键词判级别。热路径——只切前 32 字符，不做全行正则。

    性能要点（用户铁律）：每行都要跑，所以
    - 前缀匹配用 `str.startswith(tuple)` 一次调用（C 层扫完 12 个前缀），
      而不是 Python 循环逐个 startswith（cProfile 里那圈占了 _classify
      一半时间）
    - 行首不是空白时不做 lstrip（绝大多数日志行不以空白开头）
    """
    head = line[:32] if len(line) > 32 else line
    if not head:
        return "info"
    c = head[0]
    hs = head.lstrip() if (c == " " or c == "\t" or c == "\n" or c == "\r") \
        else head
    if hs.startswith(_ERR_PREFIXES):
        return "error"
    if hs.startswith(_WARN_PREFIXES):
        return "warn"
    # 兜底形态：`ValueError: xxx` / `socket.timeout: ...` / `KeyError:'a'`
    # （首词以 Error/Exception 收尾）。a600 对抗审计：原来只判
    # `first.endswith(("Error","Error:"))`，而 `first = hs.split(" ",1)[0]`
    # 遇到无空格形态（`KeyError:'a'`、`ValueError:bad`）会把整串当首词，
    # 于是这类最典型的异常行被判成 info，在「仅错误」过滤下彻底隐形。
    # 现在先按冒号切出 `KeyError` 再看。
    #
    # 性能：这条兜底是**普通信息行**（占绝大多数）唯一会走到的分支，不能
    # 每行都 split+lower。先做一次 C 层扫：首词里既没有 ':' 也不含
    # 'rror'/'xception' 等子串的，必然不是异常，直接返回（一次 `in` 比
    # split+lower+endswith 便宜一个数量级）。
    sp = hs.find(" ")
    word = hs if sp < 0 else hs[:sp]
    if ":" not in word and "rror" not in word and "xception" not in word \
            and "nterrupt" not in word and "ault" not in word \
            and "imeout" not in word and "verflow" not in word:
        return "info"
    first = word.split(":", 1)[0]
    # 小写化再判：`socket.timeout` / `gaiainfo` 这类模块限定名是小写的
    fl = first.lower()
    # a616（疯狗审计 v3 重炮二）：`endswith("fault")` 撞上 **default**
    # （"de"+"fault"）——「default config loaded」这种普通日志被判成 error，
    # 「仅错误」过滤器从此混进噪声，温度计的刻度就歪了。default 是常见
    # 普通词，静态排除它；其余 *Fault（SegmentationFault/PageFault）照常。
    if fl.endswith(("error", "exception", "interrupt",
                    "timeout", "overflow", "fault")) \
            and not fl.endswith("default"):
        return "error"
    return "info"


# 时间戳按秒缓存：热路径每秒可能上千条，strftime 每次 ~1µs 纯浪费。
_ts_cache = ("", 0.0)


def _ts():
    global _ts_cache
    now = time.time()
    cached, at = _ts_cache          # 单次读取（避免两次读之间被别的线程改）
    if now - at < 1.0:
        return cached
    s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    # a601 对抗审计：原来无条件写回。两个线程在秒边界竞争时，慢的那个会用
    # 较旧的 now 覆盖较新的缓存，使时间戳回退并冻结约 1 秒。只允许前进。
    if now >= at:
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
        # a601 对抗审计：按 `\r` 刷新的进度条（pip/curl/串口）截断时原来保留
        # 头部——用户看到的永远是最旧的进度（实测「进度 27328%…」，真正的
        # 当前值被砍掉）。这类行取尾部：最新状态才是有用的。
        if "\r" in text:
            text = "…（已截断）" + text[-_MAX_LINE_CHARS:]
        else:
            text = text[:_MAX_LINE_CHARS] + " …（单行超长已截断）"
    size = len(text) + len(rec[4])
    # a601 对抗审计：size==0 的记录（text 与 tag 都空）不增加记账，`while`
    # 淘汰条件永远为假，会永久驻留（实测容量 0 时 1000 条空记录全留下）。
    if size <= 0:
        return
    entry = (rec[0], rec[1], rec[2], rec[3], rec[4], text, size)
    _buf.append(entry)
    _buf_chars += size
    # 超出容量：从头丢，直到落回上限以内（字符 + 条数双重上限）
    while _buf and (_buf_chars > _MAX_CHARS or len(_buf) > _MAX_ENTRIES):
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
        if (c0 == "1" or c0 == " " or c0 == ":") and _ACCESS_RE.match(t):
            continue
        staged.append((ts, _classify(t), stream, "", _redact(t)))
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
    if (c0 == "1" or c0 == " " or c0 == ":") and _ACCESS_RE.match(text):
        return              # werkzeug 访问日志：噪音（仍透传到原流）
    # 锁外把这条记录算完整（_classify/_ts 是纯函数，无共享状态）
    level = _classify(text)
    ts = _ts()
    text = _redact(text)
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
        ts = _ts()                 # 锁外算（与其他热路径一致）
        text = _redact(text)       # 锁外脱敏（导出/复制会把日志带出机器）
        with _lock:
            _seq += 1
            _append((_seq, ts, lv, "log", str(tag or "")[:40], text, 0))
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
        # 实例锁：_partial 是共享可变状态（sys.stdout 全进程单例，多线程
        # 共用一个 TeeStream）。没有它，多线程的 += / split 会互相覆盖，
        # 造成行缝合、丢行、重复行（实测默认 GIL 下 96 万次写出现 23 次）。
        self._plock = threading.Lock()

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
        #
        # 2.4.4 对抗审计（严重）：缓冲侧的**任何**异常都不能外泄——原来
        # _emit_many 一抛，整条 write 就抛，而 `if self._orig:` 在它后面，
        # 意味着原流一个字都没写。日志模块的 bug 会让程序输出静默消失，
        # 直接违反「log 绝不能影响正常使用」。现在整体 try 住，且保证
        # 原流始终先写（缓冲失败也不影响透传）。
        #
        # a601 对抗审计（严重）：`_partial` 是**实例共享**状态（sys.stdout
        # 全进程单例），而 write/flush 没有任何锁。实测默认 GIL 配置下 96 万
        # 次多线程 print 出 23 行错乱（两个线程的前缀被缝成一行），若残片是
        # werkzeug 访问日志的前半段，还会被 _ACCESS_RE 整行当噪音丢弃（业务
        # 错误行静默消失）。这里用实例锁保护 `_partial` 的读-改-写；
        # 锁只在内存操作段持有，`_orig.write` 留在锁外避免阻塞原流。
        with self._plock:
            try:
                if not _enabled:
                    # 关闭期：不攒残片，也不留旧残片粘到重开后的内容上
                    # （实测旧行为会把关闭期写入的残片和重开后的行缝一起）。
                    parts = None
                    self._partial = ""
                elif "\n" in s:
                    self._partial += s
                    parts = self._partial.split("\n")
                    self._partial = parts.pop()      # 最后一段无换行 = 残片
                else:
                    parts = None
                    self._partial += s
                    # 残片也设上限：某些库持续写不带换行的进度条会无限攒
                    if len(self._partial) > 65536:
                        parts = [self._partial]
                        self._partial = ""
                if parts:
                    _emit_many(parts, self._stream)
            except Exception:
                # 缓冲失败：丢弃残片并继续——绝不能因为记账坏了而吞掉真实输出
                self._partial = ""
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self):
        # 刷流时把残留残片也落进缓冲（否则最后一行没有换行就永远看不见）
        with self._plock:
            try:
                if not _enabled:
                    self._partial = ""
                elif self._partial:
                    _emit(self._partial, self._stream)
                    self._partial = ""
            except Exception:
                self._partial = ""
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

    def reconfigure(self, **kwargs):
        """透传 reconfigure 到原流。

        a600 对抗审计：本工程多个子模块（harness/ask_mcp.py、
        mcp_server.py 等）都会调 `sys.stdout.reconfigure(encoding="utf-8")`。
        接管 stdout 后 sys.stdout 是 _TeeStream，而 io.TextIOBase 没有
        reconfigure —— 这些调用会抛 AttributeError 直接崩掉子进程。
        原流支持就转发，不支持就静默接受（编码已由 self.encoding 兜底）。
        """
        fn = getattr(self._orig, "reconfigure", None)
        if fn is None:
            return None
        try:
            return fn(**kwargs)
        except Exception:
            return None

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

    def __getattr__(self, name):
        """其余属性一律透传到原流。

        a600 对抗审计：接管 stdout 后，`sys.stdout.write_through` /
        `line_buffering` / `name` / `softspace` 这类属性在 _TeeStream 上都
        不存在，第三方代码（进度条库、colorama、pytest capture 等）一碰就
        AttributeError。显式定义的（write/flush/fileno/isatty/encoding/
        errors/buffer/reconfigure）走上面，剩下的都转发给原流。
        """
        orig = self.__dict__.get("_orig")
        if orig is None:
            raise AttributeError(name)
        return getattr(orig, name)


def install(max_chars=None):
    """接管 stdout/stderr（幂等）。main.py 在最早时机调用一次。

    a601 对抗审计：`if _installed: return` 与赋值之间原来没锁，并发调用会
    读到已装好的 TeeStream 再包一层（双层 TeeStream → 每行记两份、缓冲
    容量变相减半）。用专用锁保护整段「检查-赋值-置位」。
    """
    global _installed, _orig_stdout, _orig_stderr, _MAX_CHARS
    with _install_lock:
        # 已被外部替换（pytest capture / colorama / ipykernel 换掉 sys.stdout）
        # 时视为未安装，重新接管——否则日志静默丢失且无法恢复。
        if _installed and (sys.stdout is _orig_stdout and
                           sys.stderr is _orig_stderr):
            return None                    # 真的已装好（流未被替换）
        if _installed:
            # 流被外部换掉：以**当前**流为新的底层重新接管
            # （pytest capture / colorama 等会替换 sys.stdout）
            if not isinstance(sys.stdout, _TeeStream):
                _orig_stdout = sys.stdout
                sys.stdout = _TeeStream(_orig_stdout, "stdout")
            if not isinstance(sys.stderr, _TeeStream):
                _orig_stderr = sys.stderr
                sys.stderr = _TeeStream(_orig_stderr, "stderr")
            return None
        # a601：bool 是 int 子类，`install(max_chars=True)` 曾把容量设成 1，
        # 缓冲永久失效且 capacity_chars 变成 JSON true。显式排除 bool。
        if (max_chars and isinstance(max_chars, int)
                and not isinstance(max_chars, bool) and max_chars > 0):
            _MAX_CHARS = max_chars
        _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeStream(_orig_stdout, "stdout")
        sys.stderr = _TeeStream(_orig_stderr, "stderr")
        _installed = True


def uninstall():
    """还原 stdout/stderr 并复位安装标记（供测试与运行期停用）。

    a601 对抗审计：原来只有 install、没有 uninstall，`_installed=True` 永久
    短路；一旦第三方库替换了 sys.stdout，任何 API 都无法把日志缓冲恢复回来。
    """
    global _installed, _orig_stdout, _orig_stderr
    with _install_lock:
        try:
            if isinstance(sys.stdout, _TeeStream):
                sys.stdout = _orig_stdout if _orig_stdout is not None \
                    else sys.stdout._orig
        except Exception:
            pass
        try:
            if isinstance(sys.stderr, _TeeStream):
                sys.stderr = _orig_stderr if _orig_stderr is not None \
                    else sys.stderr._orig
        except Exception:
            pass
        _orig_stdout = _orig_stderr = None
        _installed = False
    return True


class _LoggingBridge:
    """标准库 logging → 缓冲桥（第三方库日志可见）。"""
    _PREFIX_TAG_RE = re.compile(r"^([\w.\-]+):?\s*")

    def __init__(self):
        try:
            import logging
            self._logging = logging
        except Exception:
            self._logging = None
        self._handler = None      # 2.4.4 对抗审计：记住已装的 handler

    def install(self, level=None):
        """幂等安装。重复调用不再叠 handler。

        a600 对抗审计实测缺陷：原来每次调用都 addHandler 一个新的，调 5 次
        就有 5 个 handler —— 同一条日志被记 5 份，把缓冲填满垃圾。
        a601：并发调用同样会叠（实测 8 线程并发装出 8 个 handler，且泄漏
        的旧 handler 无法再被 uninstall 摘除、逐轮累积）。整段加锁。
        """
        if self._logging is None:
            return False
        with _install_lock:
            try:
                lv = level or self._logging.INFO
                root = self._logging.getLogger()
                # a600 对抗审计：记住的 handler 可能已被外部摘掉（测试/第三方
                # 重置 root），此时不能再以为「已装」——否则日志静默丢失。
                if self._handler is not None and self._handler not in root.handlers:
                    self._handler = None
                if self._handler is None:
                    self._handler = _make_bridge_handler(self._logging)()
                    root.addHandler(self._handler)
                if root.level > lv or root.level == 0:
                    root.setLevel(lv)
                return True
            except Exception:
                return False

    def uninstall(self):
        """摘掉 handler（供测试或运行期停用）。"""
        with _install_lock:
            if self._logging is None or self._handler is None:
                return False
            try:
                self._logging.getLogger().removeHandler(self._handler)
                self._handler = None
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
    """装全局未捕获异常钩子（主线程 + 所有线程）。幂等。

    用户定调「任何报错都往日志缓冲里放」。GUI 版没有控制台，线程里抛的
    异常原来只进 sys.stderr（= 某个没人看的 pipe），本次让它们一律落进
    缓冲。保留原钩子的行为——先记日志再交回去。

    a600 对抗审计实测缺陷：原来不幂等，调 3 次同一次崩溃被记 3 份（每次
    都把上一轮的钩子当 prev 再包一层，形成 N 层链）。现在只装一次。
    """
    global _excepthooks_installed
    if _excepthooks_installed:
        return
    _excepthooks_installed = True
    try:
        prev = getattr(sys, "excepthook", None)

        def _main_hook(t, v, tb):
            _hook_record("主线程", t, v, tb)
            if prev is not None:
                prev(t, v, tb)
        sys.excepthook = _main_hook
    except Exception:
        pass
    try:
        import threading
        prev_thook = getattr(threading, "excepthook", None)

        def _thook(args):
            # a600 对抗审计：原来这里只注释「交回默认」却没真调用，导致
            # 线程未捕获异常的默认 stderr 输出（含 traceback）被静默吞掉。
            # 现在记录后再交给上一个钩子；没有上一个就按默认行为打印。
            try:
                if getattr(args, "exc_value", None) is not None and \
                        args.exc_type is not None:
                    _hook_record("线程 %s" % getattr(args.thread, "name", "?"),
                                 args.exc_type, args.exc_value,
                                 args.exc_traceback)
            except Exception:
                pass
            if prev_thook is not None:
                prev_thook(args)
            else:
                threading.__excepthook__(args)
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


def _safe_tail(start):
    """锁外取 deque 尾部切片；并发修改导致视图失效时重试一次。"""
    try:
        return list(itertools.islice(_buf, max(0, start), None))
    except RuntimeError:
        try:
            return list(itertools.islice(_buf, max(0, start), None))
        except RuntimeError:
            return []


def snapshot(since=0, limit=2000):
    """取日志快照：seq > since 的最后 limit 条。返回 {lines, last_seq, ...}。

    性能（用户铁律「log 绝不能影响流畅性能」）：deque 是 seq 单调递增的，
    所以「seq > since」等价于「从尾部倒着找第一条 seq <= since」，可以先
    在锁外切片再逐条判断，避免全量 10MB 扫描 + 全量 dict 复制（实测
    40000 条时原实现 18.5ms/次，每 2s 一次会顶掉一帧）。

    a600 对抗审计（数据丢失）：原来 `last_seq` 恒等于全局 `_seq`。当
    since>0 且新行数超过 limit 时，尾部倒推只取最近的 limit 条，**中间
    那段被跳过**，而前端看到 last_seq 已是全局最新，于是那一段永久丢失。
    现改为：有截断时 `last_seq` 返回**实际返回的最大 seq**、并置
    `truncated=True`，前端据此继续追赶（下一轮 since 只到已拿到的位置）。
    """
    since = int(since or 0)
    more = False
    head = False
    # a601 对抗审计（性能）：原来 list(_buf) / 倒推全扫 / dropwhile 全扫都在
    # 锁内。10MB 全是 1 字符短行时是 1048 万条，锁内 list(_buf) 131ms、
    # 失效游标倒推 1.28 秒——这期间**所有线程的日志写入都被阻塞**，
    # 直接违反「log 绝不能影响流畅性能」。现在锁内只取 O(1) 的元信息，
    # 切片在锁外做；deque 的 append/popleft 是原子操作，锁外读到的可能
    # 有少量漂移（多/少几行），对日志展示完全可接受。
    with _lock:
        snap_len = len(_buf)
        first_seq = _buf[0][0] if _buf else 0
        meta = (_buf_chars, _dropped, _seq, snap_len)
    # a601 对抗审计 D4：客户端游标落在缓冲起点之前（停顿太久，中间行已被
    # 淘汰）时，倒推找不到 x[0] <= since，会静默返回全部现存行且
    # truncated=False——调用方以为追平，实际中间永久缺一段。如实报告缺口。
    lost = 0
    if since > 0 and _buf and first_seq > since + 1:
        lost = first_seq - since - 1
    if since <= 0:
        # 首屏：取尾部 limit 条
        if limit and snap_len > limit:
            # 首屏截断和「增量还有更多」是两回事：前者说明**更早的**行没
            # 返回（不需要追赶，用户要的本来就是最新），后者说明还有更新的
            # 行没拿完（需要继续追）。混用 truncated 会让前端对着首屏
            # 空转追赶（last_seq 已在末尾，下一轮拿到 0 条）。分成两个字段。
            head = True
            tail = _safe_tail(snap_len - limit)
        else:
            tail = _safe_tail(0)
    else:
        # 增量：从尾部倒推，找到第一条 seq <= since 为止
        tail = []
        try:
            for x in reversed(_buf):
                if x[0] <= since:
                    break
                tail.append(x)
                if limit and len(tail) >= limit:
                    more = True
                    break
        except RuntimeError:
            # 并发修改导致 deque 视图失效：退回全量快照取尾部
            tail = _safe_tail(max(0, snap_len - (limit or snap_len)))
        tail.reverse()
        if more:
            # 超限：改取「最早 limit 条」，前端下一轮 since 自然推进，不丢。
            try:
                tail = list(itertools.islice(
                    itertools.dropwhile(lambda x: x[0] <= since, _buf), limit))
            except RuntimeError:
                pass
    total_chars, dropped, last, n = meta
    if more and tail:
        # 截断时 last_seq 只推进到本次实际返回的最后一条，前端据此续拉
        last = tail[-1][0]
    # dict 转换放到锁外（原来在锁内，持有全局锁做 2000 次 dict() 是最糟的）。
    # 大批量（全量导出/首屏大页）分批让出 GIL：实测 15 万条连续转换会让
    # 并发写线程单次阻塞 31ms；每 5000 条 sleep(0) 一次可把写线程延迟压到
    # 毫秒级（sleep(0) 只让出 CPU 时间片，不引入定时器开销）。
    items = []
    append = items.append
    for i, x in enumerate(tail):
        append({"seq": x[0], "ts": x[1], "level": x[2],
                "src": x[3], "tag": x[4], "text": x[5]})
        if i and i % 5000 == 0:
            time.sleep(0)
    return {"lines": items, "last_seq": last,
            "truncated": more,
            "head_truncated": head,
            "lost": lost,
            "capacity_chars": _MAX_CHARS,
            "used_chars": total_chars,
            "entries": n,
            "dropped": dropped,
            "installed": _installed}


def iter_entries(since=0):
    """流式遍历缓冲条目（供导出用），避免一次性建几十万个 dict。

    a601 对抗审计：`snapshot(limit=0)` 会把全部条目转成 dict 再返回，10MB
    短行缓冲（最多 20 万条 × 272B）仅这一步就多占 ~55MB，条目更多时可达
    2.7GB。导出只需要顺序读，用生成器逐条产出即可。
    注意：锁只在取引用时持有，迭代期间缓冲可能被追加（deque 迭代是安全
    的，append 不会让已有迭代器失效）。
    """
    with _lock:
        start = 0
        if since > 0:
            for i, x in enumerate(_buf):
                if x[0] > since:
                    start = i
                    break
            else:
                start = len(_buf)
    try:
        for i, x in enumerate(_buf):
            if i < start:
                continue
            yield (x[0], x[1], x[2], x[3], x[4], x[5])
    except RuntimeError:
        return


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
