# -*- coding: utf-8 -*-
"""连接基类：串口/SSH 共用的通用层。
IO 层（打开/读/写/关闭/重连）由子类实现 _io_* 方法。通用层负责：
环形 buf、SSE 客户端、日志落盘、行切分入 buf、全屏检测、AI 感知挂载点。
v0.3.0：终端渲染走前端 xterm.js，后端推 raw 字节流 + 切逻辑行入 buf/日志。
"""
import os, re, time, threading, codecs
from collections import deque
from datetime import datetime
from queue import Queue

from .app_state import LOG_DIR, _next_seq
from .ansi_utils import strip_ansi, classify_line, _SCREEN_STRONG_RE, _SCREEN_ANY_RE

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
        # UTF-8 增量解码器：跨 chunk 的多字节字符（中文等）不会被拆成 �
        self._raw_dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
        # IO 句柄（子类在 _io_open 中设置）
        self._io_handle = None

    # ---- IO 层：子类实现 ----
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
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", self.port_id)
        self.log_path = os.path.join(LOG_DIR, f"serial_{safe}_{ts}.log")
        self.log_fp = open(self.log_path, "w", encoding="utf-8", buffering=1)
        self.log_fp.write(f"# 串口日志 {self.port_id} 开始 {datetime.now().isoformat()}\n")

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
                    self.log_fp.write(f"{ts_ms}\t{tag}\t{clean}\n")
                    self.log_fp.flush()
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

    def _reader_loop(self):
        """通用读循环：取字节 → 全屏检测 → 推 raw → 切行入 buf/日志。
        IO 层由 _io_read_chunk 提供；异常由 _io_reconnect 处理。"""
        partial = b""   # 尚未遇到 \n 的字节累积（行缓冲）
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
                    # ---- 推 raw 给前端 xterm + 切分入 buf/日志 ----
                    self._push_raw(self._raw_dec.decode(chunk))
                    partial += chunk
                    if len(partial) > 65536:
                        self.append_line(partial.decode("utf-8", errors="replace"))
                        partial = b""
                    while b"\n" in partial:
                        line, partial = partial.split(b"\n", 1)
                        if line.endswith(b"\r"): line = line[:-1]
                        if b"\r" in line: line = line.rsplit(b"\r", 1)[-1]
                        self.append_line(line.decode("utf-8", errors="replace"))
                    while b"\r" in partial:
                        idx = partial.rfind(b"\r")
                        if idx == len(partial) - 1:
                            break
                        # \r 前的内容（进度条覆盖的旧行）也保留，\r 后的是新内容
                        before = partial[:idx]
                        after = partial[idx+1:]
                        if before:
                            self.append_line(before.decode("utf-8", errors="replace"))
                        if after:
                            self.append_line(after.decode("utf-8", errors="replace"))
                        partial = b""
                else:
                    if self.screen_mode and (time.time() - self.screen_last) > 12:
                        self.screen_mode = False
                        self._emit_screen_control("exit")
                    # 空转 sleep 50ms：数据到达最坏延迟 50ms（低于人感知阈值 ~100ms），
                    # 空闲唤醒频率 ~20 次/秒，兼顾交互响应与 CPU 占用（之前 0.2s 阻塞读太迟钝）
                    time.sleep(0.05)
            except Exception as e:
                # IO 异常：尝试重连（仅 alive 时）
                if not self.alive:
                    break
                self.append_line(f"[reader] 连接异常: {e}，尝试重连...")
                time.sleep(2)
                if not self.alive:
                    break
                try:
                    if self._io_reconnect():
                        self.append_line(f"[reader] 重连成功")
                    else:
                        self.append_line(f"[reader] 重连失败")
                        time.sleep(3)
                except Exception as re:
                    self.append_line(f"[reader] 重连失败: {re}")
                    time.sleep(3)

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
                try: self.log_fp.close()
                except Exception: pass
        self._start_log()
        return self.log_path

    def start(self):
        """打开 IO + 启动读线程 + 开始日志。子类 __init__ 后调用。"""
        self._io_open()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        self._start_log()

    def close(self):
        self.alive = False
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
                try: self.log_fp.close()
                except Exception: pass
