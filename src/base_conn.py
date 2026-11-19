# -*- coding: utf-8 -*-
"""连接基类：串口/SSH 共用的通用层。
IO 层（打开/读/写/关闭/重连）由子类实现 _io_* 方法。通用层负责：
环形 buf、SSE 客户端、日志落盘、行切分入 buf、全屏检测、AI 感知挂载点。
v0.3.0：终端渲染走前端 xterm.js，后端推 raw 字节流 + 切逻辑行入 buf/日志。
"""
import os, re, time, threading
from collections import deque
from datetime import datetime
from queue import Queue

from . import app_state as _st
from .app_state import _next_seq
from .ansi_utils import strip_ansi, classify_line, _SCREEN_STRONG_RE, _SCREEN_ANY_RE


# ---- a672：日志定时兜底落盘 ----------------------------------------------
# 为什么不是每个连接起一个线程：连接数少（串口/SSH 通常个位数），但线程
# 每个都要一份栈+调度；模块级单例巡检所有活连接，开销恒定。
# 为什么 FLUSH_IDLE=3s：用户定调「超过 3s 没冲满 64K 就写」。实测单次
# flush 到内核 0.006ms（p95 0.007ms，不 fsync），3s 一次对 CPU/磁盘完全
# 无感；同时把「日志看不到最新几分钟」压到最多 3 秒。
FLUSH_IDLE = 3.0
_FLUSH_CHECK = 1.0        # 巡检间隔（1s 轮一次，命中条件才真 flush）
_flusher_started = False
_flusher_lock = threading.Lock()
_live_conns = []          # 弱引用不了（连接无 __weakref__ 顾虑），直接持引用
_live_conns_lock = threading.Lock()


def register_conn(conn):
    """登记活跃连接（供定时 flush 巡检）。重复登记幂等。"""
    with _live_conns_lock:
        if conn not in _live_conns:
            _live_conns.append(conn)


def unregister_conn(conn):
    with _live_conns_lock:
        try:
            _live_conns.remove(conn)
        except ValueError:
            pass


def _unique_log_path(path):
    """原子占用一个不存在的日志文件名（a673，审计 P1 修）。

    原实现先 `os.path.exists` 再 `open(..., "w")`——检查和创建之间有竞态，
    且 999 个候选全撞后 path 仍是原值，照样截断覆盖。既然注释宣称「绝不
    覆盖」，代码就必须真的有这个保证：
      · O_CREAT|O_EXCL 是原子「创建或失败」，两个进程/线程抢同一名字只有
        一个拿到；
      · 拿不到就换 `<base>_1.log`、`_2.log`……由调用方接着试；
      · 极端情况（同一秒被占用上千次）退到 pid+纳秒后缀，仍不会覆盖。
    """
    base, ext = os.path.splitext(path)
    for cand in [path] + ["%s_%d%s" % (base, i, ext) for i in range(1, 1000)]:
        try:
            fd = os.open(cand, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        except OSError:
            break              # 目录不可写等：交给调用方的 open() 报真错
        else:
            os.close(fd)
            return cand
    # 病态兜底：纳秒级唯一名，绝不复用已存在的文件
    return "%s_%d_%d%s" % (base, os.getpid(), time.time_ns(), ext)


def _flusher_loop():
    """模块级巡检线程：只对「有未落盘数据且已静默 > FLUSH_IDLE 秒」的连接
    flush。风暴期块满自动落盘，这里缓冲区是空的或刚写过，代价为零。"""
    global _flusher_started
    while True:
        try:
            time.sleep(_FLUSH_CHECK)
            with _live_conns_lock:
                conns = list(_live_conns)
            now = time.time()
            for c in conns:
                if not getattr(c, "recording", False):
                    continue
                fp = getattr(c, "log_fp", None)
                if not fp or fp.closed:
                    continue
                at = getattr(c, "_log_dirty_at", 0)
                # a673（审计 P2）：这一读故意在锁外。脏读的后果只有「这轮
                # 少 flush 或多 flush 一次」——下一轮把 `晚/早一轮` 抹平，
                # 而 flush 本身幂等。若把读挪进 log_lock，巡检就要持有每个
                # 连接的锁做判断，反而和写入路径抢锁。写侧置位在锁内，读侧
                # 锁外只看单调时间戳，不会读到撕裂值（GIL 下 float 赋值原子）。
                if not at or now - at < FLUSH_IDLE:
                    continue
                with c.log_lock:
                    try:
                        fp.flush()
                        c._log_dirty_at = 0     # 已落盘，等下次写入再置
                    except Exception:
                        pass
        except Exception:
            pass


def _ensure_flusher():
    """懒启动巡检线程（首次开日志时才起，纯 claude 会话不占线程）。"""
    global _flusher_started
    if _flusher_started:
        return
    with _flusher_lock:
        if _flusher_started:
            return
        _flusher_started = True
    threading.Thread(target=_flusher_loop, daemon=True,
                     name="log-flusher").start()


class BaseConnection:
    kind = "serial"  # 子类覆盖

    def __init__(self, port_id):
        self.port_id = port_id
        self.port = port_id
        self.baud = None
        self.lock = threading.Lock()
        self.buf = deque(maxlen=200000)
        self.buf_lock = threading.Lock()
        self.clients = []          # SSE Queue 列表
        self.clients_lock = threading.Lock()
        self.cmd_history = deque(maxlen=200)
        self.recording = True
        self.log_fp = None
        self.log_lock = threading.Lock()
        self.log_path = None
        self.alive = True
        # 全屏应用（top/htop）期间：buf 不追加逐行，但 raw 流照推
        self.screen_mode = False
        self.screen_last = 0.0
        # v2.2.1 智能流式解码缓冲：疑似跨 chunk 的不完整 UTF-8 尾部（见
        # _smart_decode——替代原 codecs replace 增量解码器，二进制流不再
        # 把 ASCII 卷进替换字符）
        self._dec_buf = b""
        # IO 句柄（子类在 _io_open 中设置）
        self._io_handle = None
        # 重连节奏控制：首次异常报原因，失败退避 3s 起指数翻倍至 60s；
        # _reconn_kick 被外部（按 R）置位可中断等待立即重试
        self._reconn_first = True
        self._reconn_backoff = 3
        self._reconn_kick = threading.Event()
        self._reconn_lock = threading.Lock()
        self._reconn_inflight = False

    # ---- IO 层：子类实现 ----
    # （_smart_decode 为模块级函数，见文件尾）
    def _io_open(self):
        """打开连接，设置 self._io_handle。子类实现。"""
        raise NotImplementedError
    def _io_read_chunk(self):
        """读一块字节，返回 bytes（无数据返回 b''）。子类实现。"""
        raise NotImplementedError
    def _io_write(self, data: bytes):
        """写字节。子类实现。"""
        raise NotImplementedError
    def _io_close(self):
        """关闭连接。子类实现。"""
        raise NotImplementedError
    def _io_reconnect(self):
        """重连。子类实现。返回 True 表示成功。"""
        raise NotImplementedError

    def _start_log(self):
        log_dir = _st.LOG_DIR  # 模块属性访问：跟随 api_log_dir 运行时改目录（立即生效）
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", self.port_id)
        path = os.path.join(log_dir, f"serial_{safe}_{ts}.log")
        # a672：同一秒内连续 new_log（或同端口名并发重连）会撞名——原来
        # open(..., "w") 直接把正在用的旧日志**截断覆盖**，等于静默丢日志
        #（用户实锤「日志缺失」的一个隐蔽来源）。撞名就加序号，绝不覆盖。
        # a673（审计 P1）：原实现 999 次全撞后 path 保持原值 → open("w")
        # 照样截断，注释比代码强硬。改为用 O_EXCL 原子占位：谁先创建谁用，
        # 撞了换下一个名字，永不可能落到「覆盖已有文件」的分支。
        self.log_path = _unique_log_path(path)
        # 原子占位（O_EXCL）已建出空文件；下面用 "w" 打开它——占位保证这个
        # 名字属于本连接，不存在他人的内容可被截断。
        # v3.5.162：buffering 1(行缓冲)→64KB 块缓冲——行缓冲+append_line 的
        # 显式 flush 让每行日志刷盘两次，SSH 输出风暴（QR 码/大量行，实锤）
        # 时每秒数千次刷盘打满磁盘 IO，多连接场景整机卡顿分钟级。块缓冲后
        # 系统调用降 ~千倍；代价：进程异常退出丢尾部 <64KB 日志（可接受，
        # 崩溃排查另有 traceback 渠道），正常关闭/停止记录不受影响
        #
        # a672（用户实锤「同事 SSH 没断，日志缺失最新几分钟」）：64KB 块
        # 缓冲在**低频**日志下永远攒不满——实测一行典型设备日志约 68 字节，
        # 要 952 行才落一次盘；几秒一行的设备跑几分钟只有几 KB，全躺在
        # Python 用户态缓冲里，磁盘上一个字都没有。这跟「日志实时性」是
        # 两回事：读线程一直在实时收，只是不落盘。
        # 修：保留 64KB 缓冲（风暴防护不动），另加**定时兜底 flush**——
        # 每秒巡检，超过 FLUSH_IDLE 秒没有新数据落盘就 flush 一次。实测
        # flush 到内核（不 fsync）单次 0.006ms / p95 0.007ms，比写一行日志
        # 本身还便宜；风暴期块满自然落盘，定时器到点时缓冲区是空的，
        # 代价为零。低频场景最多滞后 FLUSH_IDLE 秒。
        self.log_fp = open(self.log_path, "w", encoding="utf-8", buffering=65536)
        self.log_fp.write(f"# 串口日志 {self.port_id} 开始 {datetime.now().isoformat()}\n")
        self._log_dirty_at = time.time()   # 上次写入数据（未落盘）的时刻
        _ensure_flusher()

    def append_line(self, raw_line, local_echo=False):
        """把一行逻辑文本追加进 buf/日志。raw_line 为含 ANSI 的原始行文本。

        注意：终端 SSE 走 raw 流（_push_raw），不经过这里；AI 全局流由
        下方的 _patched_append hook 转发，这里只管 buf + 日志。
        """
        ts_ms = int(time.time() * 1000)
        clean = strip_ansi(raw_line)
        tag = "input" if local_echo else classify_line(clean)
        item = {"seq": _next_seq(), "ts": ts_ms, "text": clean, "tag": tag, "port": self.port_id}
        with self.buf_lock:
            self.buf.append(item)
        if self.recording and self.log_fp:
            with self.log_lock:
                try:
                    # 写 clean（已去 ANSI）而非 raw_line，否则日志回看会带 \x1b[...m 转义码
                    # v3.5.162：去显式 flush（块缓冲批量落盘；风暴期每行两次刷盘
                    # 是多连接整机卡顿的主凶）
                    self.log_fp.write(f"{ts_ms}\t{tag}\t{clean}\n")
                    # a672：只记时间戳，不 flush——由模块级巡检线程按 FLUSH_IDLE
                    # 兜底落盘（见 _flusher_loop）
                    self._log_dirty_at = time.time()
                except Exception:
                    pass

    def _push_raw(self, text, last=False):
        """把一段原始字节流（已 decode 为 str）推给本连接所有 SSE 客户端。
        队列满时丢弃最旧条目腾位（而非移除客户端——客户端仍在消费，只是瞬时积压）。"""
        ts_ms = int(time.time() * 1000)
        item = {"kind": "raw", "port": self.port_id, "ts": ts_ms, "data": text, "last": last}
        with self.clients_lock:
            for q in self.clients:
                try:
                    q.put_nowait(item)
                except Exception:
                    # 队列满：丢最旧一条腾位再塞，保客户端在线不断流
                    try:
                        q.get_nowait()
                        q.put_nowait(item)
                    except Exception:
                        pass

    def _emit_screen_control(self, state):
        """推全屏模式控制事件（enter/exit）。"""
        ts_ms = int(time.time() * 1000)
        item = {"kind": "screenctl", "port": self.port_id, "ts": ts_ms, "state": state}
        with self.clients_lock:
            dead = []
            for q in self.clients:
                try:
                    q.put_nowait(item)
                except Exception:
                    dead.append(q)
            for q in dead:
                try:
                    self.clients.remove(q)
                except Exception:
                    pass

    def _emit_conn_state(self, state, detail=""):
        """推连接状态事件给前端（断连 overlay / 重连提示）。
        state: "down"（断连，overlay 盖终端）/ "retrying"（自动重连中）/
        "up"（重连成功，撤 overlay）。detail 为人类可读原因。"""
        ts_ms = int(time.time() * 1000)
        item = {"kind": "connstate", "port": self.port_id, "ts": ts_ms,
                "state": state, "detail": detail}
        with self.clients_lock:
            for q in self.clients:
                try:
                    q.put_nowait(item)
                except Exception:
                    try:
                        q.get_nowait()
                        q.put_nowait(item)
                    except Exception:
                        pass

    def reconnect_now(self):
        """外部触发立即重连（前端按 R）：置 kick 事件中断当前退避等待，
        并在独立线程跑一次重连——不阻塞 API 调用方。手动断开(alive=False)时无效。
        返回 True 表示已触发（alive 且允许重连）。"""
        if not self.alive:
            return False
        # 子类无重连语义（claude_conn 返回 False）时也允许试——统一走 _io_reconnect
        self._reconn_kick.set()
        threading.Thread(target=self._reconnect_once, daemon=True).start()
        return True

    def _reconnect_once(self):
        """立即重连一次（不占用 reader 的退避节奏）：与 reader 的重连互斥靠
        _reconn_inflight 标志——两路并发重连会交叉 close/open 同一通道，必炸。
        reader 侧进入 _io_reconnect 前同样检查该标志（见 _reader_loop）。"""
        with self._reconn_lock:
            if self._reconn_inflight:
                return
            self._reconn_inflight = True
        try:
            try:
                if self._io_reconnect():
                    self._reconn_first = True
                    self._reconn_backoff = 3
                    self._emit_conn_state("up", "重连成功")
                else:
                    self._emit_conn_state("retrying", "重连失败，将继续自动重试")
            except Exception as re:
                self._emit_conn_state("retrying", f"重连失败: {re}")
        finally:
            self._reconn_inflight = False

    def _reader_reconnect(self):
        """reader 循环的重连入口：与手动 R 的 _reconnect_once 互斥。
        手动重连进行中时跳过本轮（手动路径已 emit 状态，不重复）。"""
        with self._reconn_lock:
            if self._reconn_inflight:
                return None   # 手动重连在跑：本轮跳过
            self._reconn_inflight = True
        try:
            try:
                return self._io_reconnect()
            finally:
                self._reconn_inflight = False
        except Exception:
            self._reconn_inflight = False
            raise

    def _reader_loop(self):
        """通用读循环：取字节 → 全屏检测 → 解码 → 推 raw → 切行入 buf/日志。
        IO 层由 _io_read_chunk 提供；异常由 _io_reconnect 处理。
        v2.2.1：解码改走 _smart_decode（ASCII 永不被吞、非法高位字节输出
        '.'），行缓冲随之为字符级——cat 二进制分区（如 /dev/part/env 的
        GBK 内容）不再整屏 � 且 ASCII 全可见（用户实锤）。"""
        partial = ""   # 尚未遇到 \n 的字符累积（行缓冲，已解码）
        while self.alive:
            try:
                chunk = self._io_read_chunk()
                if chunk:
                    # ---- 全屏应用检测（仅控制前端 xterm 提示条，不再抑制 buf）----
                    if not self.screen_mode and _SCREEN_STRONG_RE.search(chunk):
                        self.screen_mode = True
                        self.screen_last = time.time()
                        self._emit_screen_control("enter")
                    if self.screen_mode:
                        if _SCREEN_ANY_RE.search(chunk):
                            self.screen_last = time.time()
                        if b"\n" in chunk and not _SCREEN_ANY_RE.search(chunk):
                            self.screen_mode = False
                            self._emit_screen_control("exit")
                        elif (time.time() - self.screen_last) > 12:
                            self.screen_mode = False
                            self._emit_screen_control("exit")
                    # ---- 解码一次，raw 流与行缓冲共用（同源一致）----
                    text, self._dec_buf = _smart_decode(self._dec_buf, chunk)
                    self._push_raw(text)
                    partial += text
                    if len(partial) > 65536:
                        self.append_line(partial)
                        partial = ""
                    while "\n" in partial:
                        line, partial = partial.split("\n", 1)
                        if line.endswith("\r"): line = line[:-1]
                        if "\r" in line: line = line.rsplit("\r", 1)[-1]
                        self.append_line(line)
                    while "\r" in partial:
                        idx = partial.rfind("\r")
                        if idx == len(partial) - 1:
                            break
                        # \r 前的内容（进度条覆盖的旧行）也保留，\r 后的是新内容
                        before = partial[:idx]
                        after = partial[idx+1:]
                        if before:
                            self.append_line(before)
                        if after:
                            self.append_line(after)
                        partial = ""
                else:
                    if self.screen_mode and (time.time() - self.screen_last) > 12:
                        self.screen_mode = False
                        self._emit_screen_control("exit")
                    # 空转 sleep 50ms：数据到达最坏延迟 50ms（低于人感知阈值 ~100ms），
                    # 空闲唤醒频率 ~20 次/秒，兼顾交互响应与 CPU 占用（之前 0.2s 阻塞读太迟钝）
                    time.sleep(0.05)
            except Exception as e:
                # IO 异常：持续重连直至成功或手动断开（仅 alive 时）。
                # 首次异常报原因 + 推「断连」状态给前端盖 overlay；后续重试只报节奏。
                # 按 R 置 _reconn_kick 可随时中断退避等待立即重试。
                if not self.alive:
                    break
                if self._reconn_first:
                    self._reconn_first = False
                    self.append_line(f"[reader] 连接异常: {e}，开始自动重连...")
                    self._emit_conn_state("down", str(e))
                    # 2.4.4：断连原因进调试日志（排障第一现场）
                    try:
                        from src import backend_log
                        backend_log.warn("conn", "%s 连接异常：%s: %s" % (
                            self.port_id, e.__class__.__name__, e))
                    except Exception:
                        pass
                # 可中断等待（kick 置位立即醒）
                self._reconn_kick.wait(2)
                self._reconn_kick.clear()
                if not self.alive:
                    break
                try:
                    ok = self._reader_reconnect()
                    if ok is None:
                        # 手动 R 的重连正在跑：短等它出结果（它成功会 emit up）
                        self._reconn_kick.wait(1)
                        self._reconn_kick.clear()
                    elif ok:
                        self._reconn_first = True  # 重连成功：下次异常重新报原因
                        self._reconn_backoff = 3
                        self.append_line(f"[reader] 重连成功")
                        self._emit_conn_state("up", "重连成功")
                    else:
                        # 子类 _io_reconnect 内部已做指数退避等待；失败后稍歇再进入下一轮，
                        # 现在读层句柄为 None 会抛 EOFError 驱回这里，重试不再中断
                        self.append_line(f"[reader] 重连失败，{self._reconn_backoff}s 后重试...")
                        self._emit_conn_state("retrying", f"重连失败，{self._reconn_backoff}s 后自动重试（按 R 立即重连）")
                        self._reconn_kick.wait(self._reconn_backoff)
                        self._reconn_kick.clear()
                        self._reconn_backoff = min(self._reconn_backoff * 2, 60)
                except Exception as re:
                    self.append_line(f"[reader] 重连失败: {re}，{self._reconn_backoff}s 后重试...")
                    self._emit_conn_state("retrying", f"重连失败: {re}（按 R 立即重连）")
                    self._reconn_kick.wait(self._reconn_backoff)
                    self._reconn_kick.clear()
                    self._reconn_backoff = min(self._reconn_backoff * 2, 60)

    def send_raw(self, data: bytes):
        self._io_write(data)

    def send_cmd(self, cmd, newline=True):
        with self.buf_lock:
            if cmd.strip():
                self.cmd_history.append(cmd)
        payload = cmd.encode("utf-8")
        if newline: payload += b"\r\n"
        self.send_raw(payload)

    def add_client(self):
        q = Queue(maxsize=10000)
        with self.clients_lock:
            self.clients.append(q)
        return q

    def remove_client(self, q):
        with self.clients_lock:
            try: self.clients.remove(q)
            except Exception: pass

    def get_buffer(self, n=500):
        with self.buf_lock:
            return list(self.buf)[-n:]

    def get_buffer_after(self, after_seq, n=500):
        """取 seq > after_seq 的所有行（时间正序），用于取某次命令后的新输出。"""
        with self.buf_lock:
            return [it for it in self.buf if it["seq"] > after_seq]

    def get_buffer_before(self, before_seq, n=500):
        """取 seq < before_seq 的最近 n 行（时间正序），返回 (lines, has_more)。"""
        res = []
        with self.buf_lock:
            for it in reversed(self.buf):
                if it["seq"] < before_seq:
                    res.append(it)
                    if len(res) >= n:
                        break
        res.reverse()
        has_more = len(res) == n
        return res, has_more

    def search_lines(self, q, limit=200, before_seq=0):
        """在 buf 全量搜索关键字，返回命中行 + 总数。大小写不敏感。"""
        if not q:
            return {"total": 0, "lines": [], "has_more": False}
        pat = re.compile(re.escape(q), re.IGNORECASE)
        res = []
        total = 0
        with self.buf_lock:
            for it in self.buf:
                if it["seq"] < before_seq:
                    continue
                if pat.search(it["text"]):
                    total += 1
                    if len(res) < limit:
                        res.append(it)
        has_more = total > limit
        return {"total": total, "lines": res, "has_more": has_more}

    def get_history(self):
        with self.buf_lock:
            return list(self.cmd_history)

    def clear_buffer(self):
        with self.buf_lock:
            self.buf.clear()

    def new_log(self):
        with self.log_lock:
            if self.log_fp:
                try:
                    self.log_fp.flush()   # a672：切文件前先落盘，别丢尾巴
                    self.log_fp.close()
                except Exception: pass
        self._start_log()
        return self.log_path

    def start(self):
        """打开 IO + 启动读线程 + 开始日志。子类 __init__ 后调用。
        _start_log 失败（如 LOG_DIR 指向的网络盘掉线）降级为无日志继续跑——
        异常逃逸会留下半构造对象（已开句柄+读线程）无人 close，COM 口占死。"""
        self._io_open()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        try:
            self._start_log()
        except Exception:
            self.log_fp = None
        register_conn(self)   # a672：供定时 flush 巡检

    def close(self):
        self.alive = False
        # 2.4.4：连接生命周期进调试日志（点版本号查看）——断连时刻/端口是
        # 排障最常问的两个信息，此前只散在各自模块的 print 里。
        try:
            from src import backend_log
            backend_log.log("conn", "关闭连接 %s（kind=%s）"
                            % (self.port_id, getattr(self, "kind", "?")), "info")
        except Exception:
            pass
        # 唤醒滞留在退避等待的 reader（kick.wait 立即返回，alive=False 让它退出）
        self._reconn_kick.set()
        time.sleep(0.1)
        try:
            self._io_close()
        except Exception: pass
        # join 读线程，避免它在已关的句柄上继续读并触发隐式重连
        try:
            if hasattr(self, "reader") and self.reader.is_alive():
                self.reader.join(timeout=1.0)
        except Exception: pass
        with self.log_lock:
            if self.log_fp:
                try:
                    # a672：关闭必 flush——64KB 缓冲里可能压着最后几 KB，
                    # 直接 close 会丢（用户实锤「日志缺最新内容」的同族问题）
                    self.log_fp.flush()
                    self.log_fp.close()
                except Exception: pass
                self.log_fp = None
        unregister_conn(self)   # a672：移出定时 flush 巡检表


# ---------------------------------------------------------------------------
# v2.2.1 智能流式解码：UTF-8 优先、逐字节兜底（用户定调「能显示的 ASCII 全显示」）
# 替代 codecs utf-8 errors=replace 增量解码：后者遇 GBK 等非 UTF-8 流整屏
# U+FFFD，且 0xC2+ 起始字节会把后续 ASCII 卷进替换序列吞掉。规则：
# - ASCII（含 \r\n\t/ESC 等控制字符）逐字节透传——xterm/日志链原有行为不变
# - 合法 UTF-8 多字节序列（中文等）整段解码原样输出
# - 非法/孤立高位字节输出 '.'（可见占位，hexdump 观感）；尾部疑似跨 chunk
#   的不完整序列留缓冲下轮续（上限 8 字节，防乱码流死攒）
# ---------------------------------------------------------------------------
def _smart_decode(buf, chunk):
    """buf=上轮遗留尾部字节，chunk=本轮新字节。返回 (text, rest)。"""
    data = buf + chunk
    out = []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b < 0x80:
            out.append(chr(b))
            i += 1
            continue
        ln = 2 if b <= 0xDF else 3 if b <= 0xEF else 4 if b <= 0xF7 else 0
        if ln == 0:
            out.append(".")     # 0x80-0xBF 孤立续字节 / 0xF8+ 非法起始
            i += 1
            continue
        if i + ln > n:
            rest = data[i:]
            if len(rest) > 8:   # 攒超 8B 仍不完整=乱码流，可见化清空
                out.append("." * len(rest))
                return "".join(out), b""
            return "".join(out), rest
        try:
            out.append(data[i:i + ln].decode("utf-8"))
            i += ln
        except UnicodeDecodeError:   # overlong/非法序列（0xC0 0xC1 0xF5-0xF7 等）
            out.append(".")
            i += 1
    return "".join(out), b""
