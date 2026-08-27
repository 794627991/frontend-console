#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串口控制台 Pro —— 多串口后端 + AI 接入层
- 每个串口一个 SerialPort 实例：独立线程读、独立环形缓冲、独立日志
- API 按串口 ID（端口名）路由
- AI 接入层：/api/ai/* 系列，AI 可查询任意串口实时数据、发送命令、订阅流
- 完全继承 web 版的 \r/\x08/ANSI 处理逻辑
"""
import os, sys, time, threading, json, glob, re, base64, subprocess, codecs
from collections import deque
from datetime import datetime
from queue import Queue
import itertools

import serial
import serial.tools.list_ports
from flask import Flask, Response, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PyInstaller 打包后资源在 _MEIPASS 临时目录；开发时在源码目录
def _resource_base():
    return getattr(sys, "_MEIPASS", BASE_DIR)
RES_DIR = _resource_base()
# 日志目录：默认用用户数据目录 ~/.serialconsole_pro/logs（与 endpoint.json 同级），
# 保证源码运行和 PyInstaller exe 运行都指向同一稳定位置，不受 exe 临时解压目录
# （_MEIPASS，每次启动不同且关闭即清空）或 exe 所在子目录影响，历史日志可持久读取。
# 可通过环境变量 SERIAL_LOG_DIR 或配置文件覆盖（见 /api/log_dir）。
STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
DEFAULT_LOG_DIR = os.path.join(STATE_DIR, "logs")


def _load_config():
    """读取持久化配置（日志目录等）。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg):
    """保存配置到 ~/.serialconsole_pro/config.json。"""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# 优先级：环境变量 > 配置文件 > 默认值
_cfg = _load_config()
LOG_DIR = os.environ.get("SERIAL_LOG_DIR") or _cfg.get("log_dir") or DEFAULT_LOG_DIR
COMMON_BAUDS = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

# 全局单调递增序列号：作为分页/搜索的稳定游标（避免 ms 时间戳同值）
_SEQ_COUNTER = itertools.count(1)
_SEQ_LOCK = threading.Lock()

def _next_seq():
    with _SEQ_LOCK:
        return next(_SEQ_COUNTER)

# 全屏刷新命令检测：top/htop 等用这些序列整屏重绘
# v0.3.1：改用 xterm.js 后，终端渲染交给前端 raw 流。后端 screen_mode 仅控制
# 前端"全屏模式"提示条的显示/隐藏，不再抑制 buf 逐行追加——这样 AI 通过
# /api/ai/* 始终能感知串口数据，不会因误进全屏而失明（修复 v0.3.0 感知异常）。
_SCREEN_STRONG_RE = re.compile(rb"\x1b\[\d*2J|\x1b\[\?1049h|\x1b\[H\x1b\[J", re.I)
_SCREEN_ANY_RE = re.compile(rb"\x1b\[[\d;]*[HJKsu]|\x1b\[\?1049[hl]|\x1b\[\d*2J|\x1b\[[\d;]*r", re.I)

app = Flask(__name__)

# 把未捕获异常的 traceback 写到日志文件，便于 exe（无控制台）模式下排查 500。
import logging
if not app.logger.handlers:
    _err_log_path = os.path.join(STATE_DIR, "server_errors.log")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        _h = logging.FileHandler(_err_log_path, encoding="utf-8")
        _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        app.logger.addHandler(_h)
        app.logger.setLevel(logging.ERROR)
    except Exception:
        pass

# ============================================================
# ANSI 处理（从 web 版迁移，保持一致）
# ============================================================
_ANSI_COLOR = {
    0: None, 30: "#6e7681", 31: "#ff7b72", 32: "#56d364", 33: "#e3b341",
    34: "#79c0ff", 35: "#d2a8ff", 36: "#39c5cf", 37: "#c9d1d9",
    90: "#8b949e", 91: "#ffa198", 92: "#7ee787", 93: "#f0e07a",
    94: "#a5d6ff", 95: "#d2a8ff", 96: "#56d4dd", 97: "#f0f6fc",
}
_ANSI_BG = {
    40: "#484f58", 41: "#67060c", 42: "#1a4730", 43: "#6b4600",
    44: "#0d2240", 45: "#4b0092", 46: "#005456", 47: "#57606a",
}
_ANSI_RE = re.compile(r"""
    \x1b\[ [0-?]* [ -/]* [@-~]
  | \x1b\] [^\x07\x1b]* (?:\x07|\x1b\\)
  | \x1b [=>]
  | \x1b[()][0AB0]
  | [\x00-\x08\x0b\x0c\x0e-\x1f]
""", re.VERBOSE)
_CSI_RE = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")

_256_PALETTE = None
def _color256(n):
    global _256_PALETTE
    if _256_PALETTE is None:
        std = ["#000000","#aa0000","#00aa00","#aa5500","#0000aa","#aa00aa","#00aaaa","#aaaaaa",
               "#555555","#ff5555","#55ff55","#ffff55","#5555ff","#ff55ff","#55ffff","#ffffff"]
        pal = list(std)
        lv = [0,95,135,175,215,255]
        for r in lv:
            for g in lv:
                for b in lv:
                    pal.append(f"#{r:02x}{g:02x}{b:02x}")
        for k in range(24):
            v = 8 + 10*k
            pal.append(f"#{v:02x}{v:02x}{v:02x}")
        _256_PALETTE = pal
    if 0 <= n < len(_256_PALETTE):
        return _256_PALETTE[n]
    return None

def strip_ansi(text):
    return _ANSI_RE.sub("", text)

def ansi_to_html(text):
    out = []
    i = 0
    spans = []
    cur = {"fg": None, "bg": None, "bold": False, "italic": False, "underline": False}
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    def open_span():
        styles = []
        if cur["bold"]: styles.append("font-weight:700")
        if cur["italic"]: styles.append("font-style:italic")
        if cur["underline"]: styles.append("text-decoration:underline")
        if cur["fg"]: styles.append(f"color:{cur['fg']}")
        if cur["bg"]: styles.append(f"background:{cur['bg']}")
        if styles:
            out.append(f'<span style="{";".join(styles)}">')
            spans.append(True)
        else:
            spans.append(False)
    def close_span():
        if spans:
            if spans.pop():
                out.append("</span>")
    while i < len(text):
        m = _CSI_RE.match(text, i)
        if m:
            params = m.group(1)
            final = m.group(3)
            i = m.end()
            if final != "m":
                continue
            codes = [int(x) if x else 0 for x in params.split(";")]
            j = 0
            changed = False
            while j < len(codes):
                c = codes[j]
                if c == 0:
                    cur = {"fg": None, "bg": None, "bold": False, "italic": False, "underline": False}; changed = True
                elif c == 1: cur["bold"] = True; changed = True
                elif c == 3: cur["italic"] = True; changed = True
                elif c == 4: cur["underline"] = True; changed = True
                elif c == 22: cur["bold"] = False; changed = True
                elif c == 23: cur["italic"] = False; changed = True
                elif c == 24: cur["underline"] = False; changed = True
                elif 30 <= c <= 37 or 90 <= c <= 97: cur["fg"] = _ANSI_COLOR.get(c); changed = True
                elif 40 <= c <= 47: cur["bg"] = _ANSI_BG.get(c); changed = True
                elif c == 38 and j + 2 < len(codes) and codes[j+1] == 5: cur["fg"] = _color256(codes[j+2]); changed = True; j += 2
                elif c == 48 and j + 2 < len(codes) and codes[j+1] == 5: cur["bg"] = _color256(codes[j+2]); changed = True; j += 2
                elif c == 39: cur["fg"] = None; changed = True
                elif c == 49: cur["bg"] = None; changed = True
                j += 1
            if changed:
                close_span(); open_span()
            continue
        ch = text[i]
        if ch == "\x1b":
            i += 1
            if i < len(text): i += 1
            continue
        out.append(esc(ch))
        i += 1
    while spans:
        close_span()
    return "".join(out)

def classify_line(line):
    s = line.strip()
    if not s: return "empty"
    if s.startswith("[") and "]" in s and any(c.isdigit() for c in s[:12]):
        if "error" in s.lower() or "fail" in s.lower() or "panic" in s.lower() or "oops" in s.lower():
            return "kernel_err"
        return "kernel"
    if "U-Boot" in s or s.startswith("=>") or "Hit any key" in s: return "uboot"
    if "boot_debug" in s or "heop" in s.lower():
        if "fail" in s.lower(): return "heop_fail"
        if "succ" in s.lower() or "success" in s.lower() or "OK" in s: return "heop_ok"
        return "heop"
    if s.endswith("#") or s.endswith("# ") or s.endswith("$") or s == "#": return "prompt"
    return "text"


# ============================================================
# 多串口管理
# ============================================================
class SerialPort:
    """单个串口连接：独立读线程、环形缓冲、SSE 客户端、日志。

    v0.3.0：终端渲染改用前端 xterm.js，后端不再做 \r/\n 行切分。
    读线程把原始字节流（UTF-8）按块推给前端 SSE（kind=raw），同时把
    "逻辑行"追加进 buf/日志供历史分页/搜索/分析使用。逻辑行由 \n 切分，
    行内 \r 视为"本行覆盖重写"——取最后一个 \r 之后的内容，避免 v0.2.2
    打印快时 \r 被当成新行追加产生大量空行的 bug。
    """
    def __init__(self, port, baud, port_id):
        self.port = port
        self.baud = baud
        self.port_id = port_id  # 用端口名作 ID
        self.ser = serial.Serial(port, int(baud), timeout=0.2)
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
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        self._start_log()

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
                    self.log_fp.write(f"{ts_ms}\t{tag}\t{raw_line}\n")
                    self.log_fp.flush()
                except Exception:
                    pass

    def _push_raw(self, text, last=False):
        """把一段原始字节流（已 decode 为 str）推给本串口所有 SSE 客户端。"""
        ts_ms = int(time.time() * 1000)
        item = {"kind": "raw", "port": self.port_id, "ts": ts_ms, "data": text, "last": last}
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
        partial = b""   # 尚未遇到 \n 的字节累积（行缓冲）
        while self.alive:
            try:
                with self.lock:
                    s = self.ser
                if s is None:
                    time.sleep(0.1); partial = b""; continue
                with self.lock:
                    n = s.in_waiting or 1
                    chunk = s.read(n)
                if chunk:
                    # ---- 全屏应用检测（仅控制前端 xterm 提示条，不再抑制 buf）----
                    # 检测到 top/htop 等全屏应用时通知前端显示"全屏模式"提示条，
                    # 但 buf/日志照常逐行追加——这样 AI 通过 /api/ai/buffer、
                    # /api/ai/observe、/api/ai/stream 始终能感知串口数据，
                    # 不会因误进全屏而"终端开了却获取不到数据"。
                    # 前端 xterm.js 走 _push_raw 的原始流，全屏渲染不受影响。
                    if not self.screen_mode and _SCREEN_STRONG_RE.search(chunk):
                        self.screen_mode = True
                        self.screen_last = time.time()
                        self._emit_screen_control("enter")
                    if self.screen_mode:
                        if _SCREEN_ANY_RE.search(chunk):
                            self.screen_last = time.time()
                        # 主动退出：块含裸 \n 且无屏幕控制序列 → top 退出、shell 回来
                        if b"\n" in chunk and not _SCREEN_ANY_RE.search(chunk):
                            self.screen_mode = False
                            self._emit_screen_control("exit")
                        elif (time.time() - self.screen_last) > 12:
                            # 长超时兜底退出（> top 默认 5s 刷新间隔）
                            self.screen_mode = False
                            self._emit_screen_control("exit")
                    # ---- 无论是否全屏：推 raw 给前端 xterm + 切分入 buf/日志 ----
                    # 1) 推原始流给前端 xterm（含 \r \n 等控制序列，xterm 自行渲染）
                    self._push_raw(self._raw_dec.decode(chunk))
                    # 2) 行切分入 buf/日志：只在 \n 处断行，\r 视为行内覆盖
                    partial += chunk
                    if len(partial) > 65536:
                        # 超长无换行（如二进制/进度条）：作为一行落盘，避免内存堆积
                        self.append_line(partial.decode("utf-8", errors="replace"))
                        partial = b""
                    while b"\n" in partial:
                        line, partial = partial.split(b"\n", 1)
                        # \r 处理（与 v0.2-legacy 一致）：
                        # 1) 先去掉行尾 \r（\r\n 行尾的 \r，如 "Mem: ...\r"）
                        # 2) 再处理行内 \r：取最后一个 \r 之后的内容（设备用 \r 覆盖重绘本行）
                        # 若直接 rsplit 会把 "Mem: ...\r" 吃成空行（top 等输出全是 内容\r\n）
                        if line.endswith(b"\r"): line = line[:-1]
                        if b"\r" in line: line = line.rsplit(b"\r", 1)[-1]
                        self.append_line(line.decode("utf-8", errors="replace"))
                    # \r 重绘入 buf：partial 中含 \r 但无 \n（命令行重绘，如 "\r# cmd"），
                    # 设备用 \r 回到行首重绘当前命令行，后面不跟 \n（命令还在编辑中）。
                    # 若不入 buf，AI 调 /api/ai/buffer 就看不到命令行——感知异常。
                    # 取最后一个 \r 之后的内容作为当前行入 buf（去掉 ANSI 控制序列后）。
                    # 仅当 \r 不在末尾（后面有内容）时处理；\r 在末尾等下一块数据再判断。
                    while b"\r" in partial:
                        idx = partial.rfind(b"\r")
                        if idx == len(partial) - 1:
                            break  # \r 在末尾，等下一块数据
                        after = partial[idx+1:]
                        if after:
                            self.append_line(after.decode("utf-8", errors="replace"))
                        partial = b""
                    # partial 中剩余的是未结束的行（无 \n），等下次再处理
                else:
                    # 无新字节：全屏长超时兜底退出
                    if self.screen_mode and (time.time() - self.screen_last) > 12:
                        self.screen_mode = False
                        self._emit_screen_control("exit")
                    time.sleep(0.02)
            except serial.SerialException:
                self.append_line(f"[serial-reader] 串口异常，尝试重连...")
                time.sleep(2)
                try:
                    with self.lock:
                        if self.ser:
                            try: self.ser.close()
                            except Exception: pass
                        self.ser = serial.Serial(self.port, self.baud, timeout=0.2)
                    self.append_line(f"[serial-reader] 重连成功")
                except Exception as e:
                    self.append_line(f"[serial-reader] 重连失败: {e}")
                    time.sleep(3)
            except Exception as e:
                self.append_line(f"[serial-reader] 异常: {e}")
                time.sleep(1)

    def send_raw(self, data: bytes):
        with self.lock:
            if self.ser is None: raise RuntimeError("串口未连接")
            self.ser.write(data)

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

    def get_buffer_before(self, before_seq, n=500):
        """取 seq < before_seq 的最近 n 行（时间正序），返回 (lines, has_more)。
        buf 按 seq 单调 append，反向扫描 O(窗口) 级。"""
        res = []
        with self.buf_lock:
            for it in reversed(self.buf):
                if it["seq"] < before_seq:
                    res.append(it)
                    if len(res) >= n:
                        break
        res.reverse()
        # 若取到的行数 < n 且已扫到 buf 头，说明没有更早的历史
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

    def close(self):
        self.alive = False
        time.sleep(0.1)
        with self.lock:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
                self.ser = None
        with self.log_lock:
            if self.log_fp:
                try: self.log_fp.close()
                except Exception: pass


# ---- 全局串口表 ----
_ports = {}            # port_id -> SerialPort
_ports_lock = threading.Lock()

def list_ports():
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({"device": p.device, "description": p.description, "hwid": p.hwid})
    return ports

def close_all_ports():
    with _ports_lock:
        for p in list(_ports.values()):
            p.close()
        _ports.clear()


# ============================================================
# AI 接入层
# ============================================================
# AI 订阅：跨所有串口的全局流，AI 可实时获取所有串口数据
_ai_clients = []       # AI SSE Queue 列表
_ai_clients_lock = threading.Lock()

def _broadcast_to_ai(item):
    """串口有新行时，同时推给所有 AI 订阅者。"""
    with _ai_clients_lock:
        dead = []
        for q in _ai_clients:
            try:
                q.put_nowait(item)
            except Exception:
                dead.append(q)
        for q in dead:
            try: _ai_clients.remove(q)
            except Exception: pass

# hook 到 SerialPort.append_line
_orig_append = SerialPort.append_line
def _patched_append(self, raw_line, local_echo=False):
    _orig_append(self, raw_line, local_echo)
    ts_ms = int(time.time() * 1000)
    clean = strip_ansi(raw_line)
    _broadcast_to_ai({"ts": ts_ms, "text": clean, "port": self.port_id, "tag": classify_line(clean)})
SerialPort.append_line = _patched_append


def start_background():
    """启动后台维护线程。"""
    def _cleanup():
        while True:
            time.sleep(30)
            # 清理超过 7 天的日志
            try:
                cutoff = time.time() - 7*86400
                for f in glob.glob(os.path.join(LOG_DIR, "serial_*.log")):
                    if os.path.getmtime(f) < cutoff:
                        os.remove(f)
            except Exception:
                pass
    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()


# ============================================================
# Flask 路由
# ============================================================
@app.route("/")
def index():
    return send_from_directory(RES_DIR, "index.html")

@app.route("/<path:fn>")
def static_files(fn):
    return send_from_directory(RES_DIR, fn)

@app.route("/api/ports")
def api_ports():
    return jsonify({"ports": list_ports(), "bauds": COMMON_BAUDS})

@app.route("/api/status")
def api_status():
    with _ports_lock:
        info = {}
        for pid, p in _ports.items():
            info[pid] = {
                "port": p.port, "baud": p.baud, "recording": p.recording,
                "log_path": p.log_path, "buf_lines": len(p.buf),
                "clients": len(p.clients), "cmd_history_count": len(p.cmd_history),
            }
    return jsonify({"ports": info, "log_dir": LOG_DIR})

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(force=True)
    port = data.get("port")
    baud = data.get("baud")
    if not port or not baud:
        return jsonify({"ok": False, "err": "need port and baud"}), 400
    port_id = port
    with _ports_lock:
        if port_id in _ports:
            return jsonify({"ok": False, "err": f"{port} 已连接"})
        try:
            p = SerialPort(port, baud, port_id)
            _ports[port_id] = p
        except Exception as e:
            return jsonify({"ok": False, "err": str(e)}), 500
    # 触发提示符
    try:
        p.send_raw(b"\r")
    except Exception:
        pass
    return jsonify({"ok": True, "port_id": port_id, "msg": f"已连接 {port}@{baud}"})

@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.pop(port_id, None)
    if p:
        p.close()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "err": "未找到该串口"}), 404

@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    cmd = data.get("cmd", "")
    newline = data.get("newline", True)
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 500
    try:
        p.send_cmd(cmd, newline)
        echo = cmd + ("\r" if newline else "")
        p.append_line(echo, local_echo=True)
        return jsonify({"ok": True, "sent": cmd})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/send_raw", methods=["POST"])
def api_send_raw():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    byte_list = data.get("bytes", [])
    if not isinstance(byte_list, list):
        return jsonify({"ok": False, "err": "bytes must be list"}), 400
    payload = bytes(int(b) & 0xFF for b in byte_list if isinstance(b, (int, float)))
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 500
    try:
        if payload:
            p.send_raw(payload)
        return jsonify({"ok": True, "sent": len(payload)})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/history")
def api_history():
    port_id = request.args.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"history": []})
    return jsonify({"history": p.get_history()})

@app.route("/api/buffer")
def api_buffer():
    port_id = request.args.get("port_id")
    n = int(request.args.get("n", 500))
    before_seq = request.args.get("before_seq")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"lines": [], "has_more": False})
    if before_seq:
        try:
            bs = int(before_seq)
        except ValueError:
            bs = 0
        lines, has_more = p.get_buffer_before(bs, n)
        return jsonify({"lines": lines, "has_more": has_more})
    return jsonify({"lines": p.get_buffer(n), "has_more": len(p.buf) > n})

@app.route("/api/search")
def api_search():
    """在指定串口的 buf 全量搜索关键字。"""
    port_id = request.args.get("port_id")
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 200))
    before_seq = request.args.get("before_seq")
    bs = int(before_seq) if before_seq else 0
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接", "total": 0, "lines": [], "has_more": False})
    res = p.search_lines(q, limit=limit, before_seq=bs)
    res["ok"] = True
    res["port_id"] = port_id
    # 命中行只回纯文本，省带宽
    res["lines"] = [{"seq": it["seq"], "ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in res["lines"]]
    return jsonify(res)

@app.route("/api/logs")
def api_logs():
    files = []
    if os.path.isdir(LOG_DIR):
        for f in sorted(glob.glob(os.path.join(LOG_DIR, "serial_*.log")), reverse=True):
            files.append({"name": os.path.basename(f), "size": os.path.getsize(f), "mtime": int(os.path.getmtime(f))})
    return jsonify({"logs": files, "dir": LOG_DIR})

@app.route("/api/log_dir", methods=["GET", "POST"])
def api_log_dir():
    """GET 返回当前日志目录；POST 设置新目录（持久化，立即生效，日志库从此读新目录）。"""
    global LOG_DIR
    if request.method == "GET":
        return jsonify({"ok": True, "dir": LOG_DIR, "default": DEFAULT_LOG_DIR})
    data = request.get_json(force=True) or {}
    new_dir = (data.get("dir") or "").strip()
    # 空字符串表示恢复默认目录
    if not new_dir:
        new_dir = DEFAULT_LOG_DIR
    new_dir = os.path.abspath(new_dir)
    try:
        os.makedirs(new_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "err": f"无法创建目录: {e}"}), 400
    if not os.access(new_dir, os.W_OK):
        return jsonify({"ok": False, "err": "目录不可写"}), 400
    LOG_DIR = new_dir
    _save_config({**_load_config(), "log_dir": new_dir})
    return jsonify({"ok": True, "dir": LOG_DIR})


@app.route("/api/log_dir/open", methods=["POST"])
def api_log_dir_open():
    """用系统资源管理器打开日志目录。WebView2 拦截 file:// 协议，必须后端调 explorer。"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        target = (data.get("dir") or LOG_DIR).strip()
        if not target:
            target = LOG_DIR
        os.makedirs(target, exist_ok=True)
        # os.startfile 在 pywebview Flask 线程里可能静默失败，改用 explorer.exe 更可靠
        import subprocess
        subprocess.Popen(["explorer.exe", target], close_fds=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400

@app.route("/api/open_log_file", methods=["POST"])
def api_open_log_file():
    """在资源管理器中打开日志目录并选中指定日志文件（仅 Windows 支持 /select）。"""
    data = request.get_json(force=True)
    name = data.get("name")
    if not name:
        return jsonify({"ok": False, "err": "need name"}), 400
    path = os.path.join(LOG_DIR, name)
    try:
        if not os.path.isfile(path):
            return jsonify({"ok": False, "err": "not found"}), 404
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer.exe", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", LOG_DIR])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/log/<name>")
def api_log_read(name):
    path = os.path.join(LOG_DIR, name)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "err": "not found"}), 404
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return Response(f.read(), mimetype="text/plain")

@app.route("/api/replay/<name>")
def api_replay(name):
    path = os.path.join(LOG_DIR, name)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "err": "not found"}), 404
    lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.startswith("#"): continue
            parts = ln.split("\t", 2)
            if len(parts) == 3:
                lines.append({"ts": int(parts[0]), "tag": parts[1], "text": parts[2], "html": None})
    return jsonify({"lines": lines})

@app.route("/api/new_log", methods=["POST"])
def api_new_log():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 500
    return jsonify({"log_path": p.new_log()})

@app.route("/api/clear_buffer", methods=["POST"])
def api_clear_buffer():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if p:
        p.clear_buffer()
    return jsonify({"ok": True})

@app.route("/api/stream")
def stream():
    port_id = request.args.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 404
    q = p.add_client()
    def gen():
        yield "event: hello\ndata: {}\n\n"
        while True:
            try:
                item = q.get(timeout=15)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except Exception:
                yield ": ping\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================
# AI 专用 API
# ============================================================
@app.route("/api/ai/status")
def ai_status():
    """AI 获取所有串口状态概览。"""
    return api_status()

@app.route("/api/ai/buffer")
def ai_buffer():
    """AI 获取指定串口的缓冲（可指定行数）。"""
    port_id = request.args.get("port_id")
    n = int(request.args.get("n", 200))
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    items = p.get_buffer(n)
    # 给 AI 返回纯文本（去 ANSI/HTML），更省 token
    return jsonify({"ok": True, "port_id": port_id, "lines": [
        {"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items
    ]})

@app.route("/api/ai/recent")
def ai_recent():
    """AI 获取所有已连接串口最近的输出（各取最后 N 行）。"""
    n = int(request.args.get("n", 50))
    result = {}
    with _ports_lock:
        all_ports = list(_ports.items())
    for pid, p in all_ports:
        items = p.get_buffer(n)
        result[pid] = [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items]
    return jsonify({"ok": True, "ports": result})

@app.route("/api/ai/send", methods=["POST"])
def ai_send():
    """AI 向指定串口发送命令。"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    cmd = data.get("cmd", "")
    wait = float(data.get("wait", 1.5))  # 等待回显秒数
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    try:
        before = len(p.buf)
        p.send_cmd(cmd, newline=True)
        # 等待设备回显
        time.sleep(wait)
        after = len(p.buf)
        new_items = p.get_buffer(max(0, after - before))
        return jsonify({"ok": True, "port_id": port_id, "sent": cmd,
                        "response": [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in new_items]})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)})

@app.route("/api/ai/send_raw", methods=["POST"])
def ai_send_raw():
    """AI 发送原始字节。"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    byte_list = data.get("bytes", [])
    payload = bytes(int(b) & 0xFF for b in byte_list if isinstance(b, (int, float)))
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    try:
        if payload:
            p.send_raw(payload)
        return jsonify({"ok": True, "sent": len(payload)})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)})

@app.route("/api/ai/stream")
def ai_stream():
    """AI 订阅所有串口的实时流（跨串口全局 SSE）。"""
    q = Queue(maxsize=10000)
    with _ai_clients_lock:
        _ai_clients.append(q)
    def gen():
        yield "event: hello\ndata: {}\n\n"
        while True:
            try:
                item = q.get(timeout=15)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except Exception:
                yield ": ping\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/ai/ports")
def ai_ports():
    """AI 获取可用串口列表。"""
    return jsonify({"ok": True, "ports": list_ports(), "connected": list(_ports.keys())})

@app.route("/api/ai/observe")
def ai_observe():
    """Claude Code 直连用：一次返回状态 + 各串口最近 N 行，减少往返。
    可选 ?n=50 控制每个串口取多少行。"""
    n = int(request.args.get("n", 50))
    with _ports_lock:
        all_ports = list(_ports.items())
    status = {}
    recent = {}
    for pid, p in all_ports:
        status[pid] = {
            "port": p.port, "baud": p.baud, "recording": p.recording,
            "buf_lines": len(p.buf), "cmd_history_count": len(p.cmd_history),
        }
        items = p.get_buffer(n)
        recent[pid] = [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items]
    return jsonify({"ok": True, "connected": list(_ports.keys()),
                    "status": status, "recent": recent})


# 临时调试：接收前端 xterm buffer 信息
@app.route("/api/debug_xterm", methods=["POST"])
def debug_xterm():
    data = request.get_json(force=True, silent=True) or {}
    with open(r"D:\AI\串口控制台Pro\test_result.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})

if __name__ == "__main__":
    start_background()
    app.run(host="127.0.0.1", port=8765, threaded=True, debug=False, use_reloader=False)
