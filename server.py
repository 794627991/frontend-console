#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端控制台 Pro —— 多串口/SSH 后端 + AI 接入层
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

# SSH 集成（可选依赖：延迟导入——纯串口场景不加载 paramiko，省 ~300ms 启动时间）
# 用到 SSH 时才 import，避免启动时阻塞。paramiko 为 None 表示未安装。
_paramiko = None  # 懒加载缓存
def _get_paramiko():
    """延迟导入 paramiko，首次 SSH 连接时才加载。"""
    global _paramiko
    if _paramiko is not None:
        return _paramiko if _paramiko is not False else None
    try:
        import paramiko as _pk
        _paramiko = _pk
        return _pk
    except ImportError:
        _paramiko = False  # 标记未安装，避免重复尝试
        return None

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
CMD_LIB_FILE = os.path.join(STATE_DIR, "cmdlib.json")  # 命令库持久化（跨端口/重启保留）


def _load_cmd_lib():
    """读取持久化命令库 [{name, cmd}]。"""
    try:
        with open(CMD_LIB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧格式：字符串数组 → [{name:'', cmd:旧值}]
        return [c if isinstance(c, dict) else {"name": "", "cmd": c} for c in data]
    except Exception:
        return []


def _save_cmd_lib(lib):
    """保存命令库到 ~/.serialconsole_pro/cmdlib.json。"""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(CMD_LIB_FILE, "w", encoding="utf-8") as f:
            json.dump(lib, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---- 日志行偏移索引（G 级文件随机访问） ----
# 日志格式：工具自记录 ts\ttag\traw_line\n；外部日志：任意文本行。
# 索引记录每行起始字节偏移，支持 O(1) seek 到第 N 行。索引缓存到 .idx 文件。
_log_index_cache = {}  # path -> LogIndex
_log_index_lock = threading.Lock()

class LogIndex:
    """日志文件行偏移索引。首次扫描全文件记录每行偏移，缓存到 .idx。
    支持工具格式（ts\ttag\ttext）和外部纯文本日志。
    文件追加后按 size 变化增量续扫，避免重扫 G 级文件。"""
    def __init__(self, path):
        self.path = path
        self.idx_path = path + ".idx"
        self.offsets = []  # 每行起始字节偏移
        self.total = 0
        self._loaded = False
        self._built_size = -1  # 建索引时的文件大小，用于检测追加失效

    def _parse_line(self, raw):
        """解析一行，返回 {ts, tag, text}。兼容工具格式和外部纯文本。"""
        raw = raw.rstrip("\n").rstrip("\r")
        if raw.startswith("#"):
            return {"ts": 0, "tag": "comment", "text": raw}
        parts = raw.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit():
            # 工具格式：ts\ttag\ttext
            try:
                return {"ts": int(parts[0]), "tag": parts[1], "text": parts[2]}
            except Exception:
                pass
        # 外部纯文本：整行作为 text
        return {"ts": 0, "tag": "text", "text": raw}

    def build(self):
        """扫描日志文件建索引。首次 O(n)，结果缓存到 .idx 文件。
        已加载且文件未追加时直接返回；文件追加时增量续扫。"""
        cur_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        # 已加载且文件大小未变 → 直接返回
        if self._loaded and self._built_size == cur_size:
            return
        # 已加载但文件追加 → 增量续扫追加部分
        if self._loaded and self._built_size >= 0 and cur_size > self._built_size:
            self._append_scan(cur_size)
            return
        # 首次：尝试加载 .idx 缓存
        if not self._loaded:
            try:
                if os.path.isfile(self.idx_path) and os.path.getmtime(self.idx_path) >= os.path.getmtime(self.path):
                    with open(self.idx_path, "rb") as f:
                        data = f.read()
                    if len(data) >= 8:
                        import struct
                        cached_total = struct.unpack(">Q", data[:8])[0]
                        count = (len(data) - 8) // 8
                        # 校验：缓存的总行数与偏移数一致才采用
                        if count == cached_total:
                            self.total = cached_total
                            self.offsets = list(struct.unpack(">" + "Q" * count, data[8:8 + count * 8]))
                            self.offsets.append(cur_size)  # 追加 EOF 偏移占位
                            self._loaded = True
                            # .idx 未存文件大小，用最后一行起点作 _built_size 近似值。
                            # cur_size 必 >= 最后一行起点（该行有内容）；文件被截断时
                            # cur_size < 最后一行起点（或 ==0 且缓存非空）→ 缓存失效全重扫。
                            last_row_start = self.offsets[-2] if len(self.offsets) >= 2 else 0
                            if cur_size < last_row_start or (cur_size == 0 and cached_total > 0):
                                # 文件被截断到更小或清空，缓存失效 → 全重扫
                                self._loaded = False
                                self.offsets = []
                                self.total = 0
                            else:
                                self._built_size = last_row_start
                                if cur_size > self._built_size:
                                    self._append_scan(cur_size)
                            return
            except Exception:
                pass
        # 全文件扫描
        self.offsets = [0]
        with open(self.path, "rb") as f:
            f.seek(0)
            while True:
                line = f.readline()
                if not line:
                    break
                self.offsets.append(f.tell())
        # 末尾可能有空行偏移，去掉
        while len(self.offsets) > 1 and self.offsets[-1] == self.offsets[-2]:
            self.offsets.pop()
        self.total = len(self.offsets) - 1 if self.offsets else 0
        if self.offsets and self.offsets[-1] == 0:
            self.total = 0
        self._built_size = cur_size
        self._save_cache()

    def _append_scan(self, cur_size):
        """增量续扫：从上次索引末尾继续扫描追加部分。
        offsets 结构：[行0起点, 行1起点, ..., 行N-1起点, EOF]。
        pop 掉旧 EOF，从最后一行起点重读到新末尾（兼容最后一行未以 \\n 结尾）。"""
        try:
            with open(self.path, "rb") as f:
                if self.offsets:
                    self.offsets.pop()  # 弹掉旧 EOF
                if not self.offsets:
                    self.offsets = [0]  # 空文件起点
                f.seek(self.offsets[-1])  # 从最后一行起点重读
                while True:
                    line = f.readline()
                    if not line:
                        break
                    self.offsets.append(f.tell())
                while len(self.offsets) > 1 and self.offsets[-1] == self.offsets[-2]:
                    self.offsets.pop()
                self.total = len(self.offsets) - 1 if self.offsets else 0
                if self.offsets and self.offsets[-1] == 0:
                    self.total = 0
                # 截断守卫：若扫描期间文件被截断，最后一个偏移可能超文件大小，
                # 导致后续 get_page seek 到 EOF 外。检测到则丢弃缓存全重扫。
                if self.offsets and self.offsets[-1] > cur_size:
                    raise ValueError("offsets past EOF, file truncated during scan")
            self._built_size = cur_size
            self._save_cache()
        except Exception:
            # 续扫异常（截断等）→ 标记未加载，下次 build 全重扫
            self._loaded = False
            self.offsets = []
            self.total = 0

    def _save_cache(self):
        """保存索引到 .idx 文件。"""
        try:
            import struct
            with open(self.idx_path, "wb") as f:
                f.write(struct.pack(">Q", self.total))
                if self.offsets and self.total > 0:
                    f.write(struct.pack(">" + "Q" * self.total, *self.offsets[:self.total]))
        except Exception:
            pass

    def get_page(self, offset, limit):
        """读取第 offset 行起的 limit 行（0-based）。返回 [{ts,tag,text}, ...]。"""
        if not self._loaded:
            self.build()
        if offset < 0 or offset >= self.total:
            return []
        end = min(offset + limit, self.total)
        res = []
        with open(self.path, "rb") as f:
            for i in range(offset, end):
                f.seek(self.offsets[i])
                line = f.readline()
                res.append(self._parse_line(line.decode("utf-8", errors="replace")))
        return res

    def search(self, q, limit=200, start_offset=0):
        """从 start_offset 行起搜索 q（大小写不敏感），返回命中行 + 游标。"""
        if not self._loaded:
            self.build()
        if not q:
            return {"total": 0, "lines": [], "next_offset": -1, "has_more": False}
        pat = re.compile(re.escape(q), re.IGNORECASE)
        res = []
        total = 0
        next_offset = -1
        with open(self.path, "rb") as f:
            for i in range(start_offset, self.total):
                f.seek(self.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                parsed = self._parse_line(line)
                if pat.search(parsed["text"]):
                    total += 1
                    if len(res) < limit:
                        parsed["row"] = i
                        res.append(parsed)
                    else:
                        # 已满 limit，记录续搜游标，但继续统计 total 以给前端准确计数
                        if next_offset < 0:
                            next_offset = i
        has_more = next_offset >= 0
        return {"total": total, "lines": res, "next_offset": next_offset, "has_more": has_more}


def _get_log_index(path):
    """获取/缓存日志索引。每次调用都触发 build()——内部按 _built_size
    判断文件是否追加，未变则 O(1) 返回，追加则增量续扫。"""
    with _log_index_lock:
        if path not in _log_index_cache:
            _log_index_cache[path] = LogIndex(path)
        idx = _log_index_cache[path]
        idx.build()
        return idx


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
class BaseConnection:
    """连接基类：串口/SSH 共用的通用层。
    IO 层（打开/读/写/关闭/重连）由子类实现 _io_* 方法。通用层负责：
    环形 buf、SSE 客户端、日志落盘、行切分入 buf、全屏检测、AI 感知挂载点。
    v0.3.0：终端渲染走前端 xterm.js，后端推 raw 字节流 + 切逻辑行入 buf/日志。
    """
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
                    time.sleep(0.02)
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


class SerialPort(BaseConnection):
    """物理串口连接。IO 层用 pyserial。"""
    kind = "serial"

    def __init__(self, port, baud, port_id):
        super().__init__(port_id)
        self.port = port
        self.baud = baud
        self.ser = None
        self.start()

    def _io_open(self):
        self.ser = serial.Serial(self.port, int(self.baud), timeout=0.2)
        self._io_handle = self.ser

    def _io_read_chunk(self):
        with self.lock:
            s = self.ser
        if s is None:
            time.sleep(0.1)
            return b""
        with self.lock:
            n = s.in_waiting or 1
            chunk = s.read(n)
        return chunk or b""

    def _io_write(self, data: bytes):
        with self.lock:
            if self.ser is None: raise RuntimeError("串口未连接")
            self.ser.write(data)

    def _io_close(self):
        with self.lock:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
                self.ser = None

    def _io_reconnect(self):
        with self.lock:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2)
        return True


class SSHConnection(BaseConnection):
    """SSH 连接。IO 层用 paramiko interactive shell。
    对前端透明：raw 流推 xterm，xterm 输入转发 channel.sendall。
    含 keepalive + 断线指数退避重连。"""
    kind = "ssh"

    def __init__(self, host, port, username, password=None, key_path=None, port_id=None):
        super().__init__(port_id or f"ssh:{host}:{port}")
        self.host = host
        self.ssh_port = int(port) if port else 22
        self.username = username
        self.password = password
        self.key_path = key_path
        # 兼容 api_status 的 p.port/p.baud 字段
        self.port = f"{username}@{host}"
        self.baud = None
        self._client = None
        self._channel = None
        self._keepalive = None
        self._reconnect_attempts = 0
        self.start()

    def _io_open(self):
        paramiko = _get_paramiko()
        if paramiko is None:
            raise RuntimeError("paramiko 未安装，无法建立 SSH 连接")
        # 停掉旧 keepalive 线程（重连场景），避免多个线程并发 send_ignore
        self._keepalive_stop = True
        if getattr(self, "_keepalive", None) and self._keepalive.is_alive():
            try: self._keepalive.join(timeout=1.0)
            except Exception: pass
        self._keepalive_stop = False
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(hostname=self.host, port=self.ssh_port, username=self.username,
                       timeout=10, allow_agent=False, look_for_keys=False)
        if self.key_path:
            kwargs["key_filename"] = self.key_path
        else:
            kwargs["password"] = self.password
        client.connect(**kwargs)
        self._client = client
        # 交互式 shell（PTY），匹配嵌入式设备 dropbear/uboot-over-ssh 场景
        chan = client.invoke_shell()
        self._channel = chan
        self._io_handle = chan
        # keepalive 线程
        self._keepalive = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive.start()

    def _io_read_chunk(self):
        if self._channel is None:
            time.sleep(0.1)
            return b""
        # recv 阻塞至有数据或 timeout；用 select 避免 100% CPU
        import select
        r, _, _ = select.select([self._channel], [], [], 0.2)
        if r:
            data = self._channel.recv(4096)
            if not data:
                # EOF：对端关闭
                raise EOFError("SSH channel EOF")
            return data
        return b""

    def _io_write(self, data: bytes):
        if self._channel is None: raise RuntimeError("SSH 未连接")
        self._channel.sendall(data)

    def _io_close(self):
        with self.lock:
            if self._channel:
                try: self._channel.close()
                except Exception: pass
                self._channel = None
            if self._client:
                try: self._client.close()
                except Exception: pass
                self._client = None

    def _io_reconnect(self):
        """指数退避重连：1s/2s/4s... 上限 60s。手动 disconnect（alive=False）不重连。"""
        self._reconnect_attempts += 1
        delay = min(60, 2 ** (self._reconnect_attempts - 1))
        time.sleep(delay)
        try:
            self._io_close()
            self._io_open()
            self._reconnect_attempts = 0
            return True
        except Exception:
            return False

    def _keepalive_loop(self):
        """每 30s 发 keepalive，防 NAT/防火墙断连。"""
        while self.alive and self._client is not None and not getattr(self, "_keepalive_stop", False):
            try:
                time.sleep(30)
                if not self.alive or self._client is None or getattr(self, "_keepalive_stop", False):
                    break
                # paramiko 2.10+ 用 send_okay，兼容旧版用 global_request
                t = self._client.get_transport() if self._client else None
                if t is not None:
                    try:
                        t.send_ignore()
                    except Exception:
                        try: t.global_request("keepalive@openssh.com", wait=False)
                        except Exception: pass
            except Exception:
                break


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

# 前端已打开的日志文件列表（前端上报，供 MCP/AI 查询"用户当前在看哪个日志"）
# 每项: {"name": 显示名, "path": 绝对路径或日志目录内文件名, "port_id": 前端 tab id, "total": 行数}
_open_logs = []
_open_logs_lock = threading.Lock()

# MCP 最近调用记录（mcp_server.py 通过 /api/ai/mcp_report 上报，前端状态面板展示）
# 每项: {"ts": 时间戳, "tool": 工具名, "args摘要": 参数摘要, "ok": 是否成功}
_mcp_calls = []
_mcp_calls_lock = threading.Lock()
_MCP_CALLS_MAX = 50

def _broadcast_to_ai(item):
    """串口有新行时，同时推给所有 AI 订阅者。
    队列满时丢最旧腾位，不移除客户端（避免误杀仍在消费的订阅者）。"""
    with _ai_clients_lock:
        for q in _ai_clients:
            try:
                q.put_nowait(item)
            except Exception:
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                except Exception:
                    pass

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
                "kind": getattr(p, "kind", "serial"),
                "host": getattr(p, "host", None), "username": getattr(p, "username", None),
            }
    return jsonify({"ports": info, "log_dir": LOG_DIR})

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(force=True)
    kind = data.get("kind", "serial")
    if kind == "ssh":
        # SSH 连接
        host = (data.get("host") or "").strip()
        port = data.get("port") or 22
        username = (data.get("username") or "").strip()
        password = data.get("password")
        key_path = (data.get("key_path") or "").strip() or None
        if not host or not username:
            return jsonify({"ok": False, "err": "need host and username"}), 400
        if not password and not key_path:
            return jsonify({"ok": False, "err": "need password or key_path"}), 400
        if _get_paramiko() is None:
            return jsonify({"ok": False, "err": "paramiko 未安装，无法 SSH 连接"}), 500
        port_id = f"ssh:{host}:{port}"
        with _ports_lock:
            if port_id in _ports:
                return jsonify({"ok": False, "err": f"{port_id} 已连接"})
            try:
                p = SSHConnection(host, port, username, password=password, key_path=key_path, port_id=port_id)
                _ports[port_id] = p
            except Exception as e:
                return jsonify({"ok": False, "err": str(e)}), 500
        # SSH invoke_shell 自带 shell，不主动 send \r
        return jsonify({"ok": True, "port_id": port_id, "kind": "ssh",
                        "msg": f"已连接 {username}@{host}:{port}"})
    else:
        # 串口连接（默认）
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
        return jsonify({"ok": True, "port_id": port_id, "kind": "serial", "msg": f"已连接 {port}@{baud}"})

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
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.startswith("#"): continue
            parts = ln.split("\t", 2)
            if len(parts) == 3 and parts[0].isdigit():
                lines.append({"ts": int(parts[0]), "tag": parts[1], "text": parts[2], "html": None})
    return jsonify({"lines": lines})


# ---- G 级历史翻阅：日志行索引 + 分页 + 搜索 ----
def _resolve_log_path(name_or_path):
    """解析日志路径：支持 LOG_DIR 内文件名，也支持外部绝对路径。
    防路径穿越：LOG_DIR 内文件名不允许含 .. 逃逸。"""
    if os.path.isabs(name_or_path) and os.path.isfile(name_or_path):
        return name_or_path
    # 防穿越：规范化后必须在 LOG_DIR 内
    p = os.path.normpath(os.path.join(LOG_DIR, name_or_path))
    if not os.path.realpath(p).startswith(os.path.realpath(LOG_DIR) + os.sep) and os.path.realpath(p) != os.path.realpath(LOG_DIR):
        return None
    if os.path.isfile(p):
        return p
    return None

@app.route("/api/log_count")
def api_log_count():
    """返回日志总行数。name=日志名或绝对路径。"""
    name = request.args.get("name", "")
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    if not idx._loaded:
        idx.build()
    return jsonify({"ok": True, "total": idx.total, "path": path})

@app.route("/api/log_page")
def api_log_page():
    """按行号分页读取日志。name=日志名或绝对路径，offset=起始行(0-based)，limit=行数。"""
    name = request.args.get("name", "")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 100))
    limit = min(limit, 500)  # 单次上限防大请求
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    lines = idx.get_page(offset, limit)
    return jsonify({"ok": True, "lines": lines, "offset": offset, "total": idx.total})

@app.route("/api/log_search")
def api_log_search():
    """在日志文件搜索关键字。name=日志名或绝对路径，q=关键字，offset=起始行，limit=命中上限。"""
    name = request.args.get("name", "")
    q = request.args.get("q", "")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 200))
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    res = idx.search(q, limit=limit, start_offset=offset)
    return jsonify({"ok": True, **res})

@app.route("/api/log_open_external", methods=["POST"])
def api_log_open_external():
    """打开外部日志文件（任意路径），返回可用的 name 标识供后续 log_count/page/search 用。
    body: {path: 绝对路径}。"""
    data = request.get_json(force=True, silent=True) or {}
    p = (data.get("path") or "").strip()
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    return jsonify({"ok": True, "name": p, "size": os.path.getsize(p)})


@app.route("/api/ai/diff_logs", methods=["POST"])
def ai_diff_logs():
    """对比两份日志，返回差异。BSP 常用于对比"正常启动 vs 异常启动"日志。
    body: {a: 路径1, b: 路径2, mode: "line"|"summary", context: 上下文行数}
    - mode=line：行级 diff（基于 text 内容忽略时间戳），输出增/减/变化块
    - mode=summary：去重摘要，对比两份日志各自唯一行 + 出现次数，按频次差异排序
    context：line 模式下差异块上下文行数（默认 2）"""
    import difflib
    from collections import Counter
    data = request.get_json(force=True, silent=True) or {}
    pa = _resolve_log_path(data.get("a", ""))
    pb = _resolve_log_path(data.get("b", ""))
    if not pa or not pb:
        return jsonify({"ok": False, "err": f"日志路径解析失败: a={data.get('a')} b={data.get('b')}"}), 400
    mode = (data.get("mode") or "summary").strip()
    ctx = int(data.get("context", 2))
    ctx = max(0, min(ctx, 10))

    # 读两份日志的 text 行（忽略 ts，只取 tag+text 用于对比；纯外部日志 tag=text）
    def read_texts(path):
        idx = _get_log_index(path)
        if not idx._loaded:
            idx.build()
        out = []
        with open(path, "rb") as f:
            for i in range(idx.total):
                f.seek(idx.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                p = idx._parse_line(line)
                # 对比键：tag+text（忽略 ts，因为两份日志时间戳必然不同）
                out.append((p.get("tag", "text"), p.get("text", "")))
        return out

    try:
        a_lines = read_texts(pa)
        b_lines = read_texts(pb)
    except Exception as e:
        return jsonify({"ok": False, "err": f"读取日志失败: {e}"}), 500

    a_name = os.path.basename(pa)
    b_name = os.path.basename(pb)

    if mode == "line":
        # 行级 diff：用 difflib 对 text 序列做差异比对
        a_texts = [t for _, t in a_lines]
        b_texts = [t for _, t in b_lines]
        sm = difflib.SequenceMatcher(a=a_texts, b=b_texts, autojunk=False)
        blocks = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            # 上下文
            cs = max(0, i1 - ctx)
            ce = min(len(a_texts), i2 + ctx)
            block = {
                "op": op,  # replace / delete / insert
                "a_range": [i1, i2], "b_range": [j1, j2],
                "a_ctx": [{"row": cs + k, "text": a_texts[cs + k]} for k in range(ce - cs) if cs + k < len(a_texts)],
                "b_ctx": [{"row": j1 + k, "text": b_texts[j1 + k]} for k in range(j2 - j1 + ctx) if j1 + k < len(b_texts)],
            }
            # 只保留差异行，上下文单独标
            block["a_lines"] = [{"row": i1 + k, "text": a_texts[i1 + k]} for k in range(i2 - i1)]
            block["b_lines"] = [{"row": j1 + k, "text": b_texts[j1 + k]} for k in range(j2 - j1)]
            blocks.append(block)
        return jsonify({"ok": True, "mode": "line", "a": a_name, "b": b_name,
                        "a_total": len(a_lines), "b_total": len(b_lines),
                        "diff_blocks": blocks, "diff_count": len(blocks)})

    # mode=summary：去重摘要，对比唯一行 + 出现次数
    def count_lines(lines):
        c = Counter()
        for tag, text in lines:
            # 去掉行内可变部分（时间戳已在 text 里就保留，对比时两份日志时间不同但内容同）
            key = text.strip()
            if not key:
                continue
            c[key] += 1
        return c
    a_cnt = count_lines(a_lines)
    b_cnt = count_lines(b_lines)
    all_keys = set(a_cnt) | set(b_cnt)
    only_a = []  # 只在 A 出现
    only_b = []  # 只在 B 出现
    diff_cnt = []  # 两边都有但次数差大
    for k in all_keys:
        ca = a_cnt.get(k, 0)
        cb = b_cnt.get(k, 0)
        if ca and not cb:
            only_a.append({"text": k, "a_count": ca})
        elif cb and not ca:
            only_b.append({"text": k, "b_count": cb})
        elif abs(ca - cb) > 0:
            diff_cnt.append({"text": k, "a_count": ca, "b_count": cb, "delta": cb - ca})
    # 按次数/差异排序
    only_a.sort(key=lambda x: -x["a_count"])
    only_b.sort(key=lambda x: -x["b_count"])
    diff_cnt.sort(key=lambda x: -abs(x["delta"]))
    return jsonify({"ok": True, "mode": "summary", "a": a_name, "b": b_name,
                    "a_total": len(a_lines), "b_total": len(b_lines),
                    "a_unique": len(a_cnt), "b_unique": len(b_cnt),
                    "only_a": only_a[:100], "only_b": only_b[:100],
                    "count_diffs": diff_cnt[:100],
                    "only_a_total": len(only_a), "only_b_total": len(only_b),
                    "count_diffs_total": len(diff_cnt)})

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
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": ping\n\n"
        finally:
            # 客户端断开时回收队列，避免泄漏（gen 退出 = 连接关闭）
            p.remove_client(q)
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
        # 用 seq 游标取命令后的新输出，避免 len 差在并发下取错（别人命令/设备自报混入）
        with p.buf_lock:
            before_seq = p.buf[-1]["seq"] if p.buf else -1
        p.send_cmd(cmd, newline=True)
        # 等待设备回显
        time.sleep(wait)
        new_items = p.get_buffer_after(before_seq)
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
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": ping\n\n"
        finally:
            # 客户端断开时从 _ai_clients 移除队列，避免泄漏（与 stream() 同模式）
            with _ai_clients_lock:
                try:
                    _ai_clients.remove(q)
                except ValueError:
                    pass
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
    with _open_logs_lock:
        open_logs = list(_open_logs)
    return jsonify({"ok": True, "connected": list(_ports.keys()),
                    "status": status, "recent": recent, "open_logs": open_logs})


# ---- 前端上报已打开的日志（打开/关闭日志 tab 时同步） ----
@app.route("/api/ai/open_logs", methods=["GET", "POST", "DELETE"])
def ai_open_logs():
    """GET 查询当前已打开日志列表；POST 全量覆盖列表；DELETE 清空。
    前端打开/关闭日志 tab 时 POST 全量同步，让 MCP/AI 能感知用户当前在看哪个日志。"""
    global _open_logs
    if request.method == "GET":
        with _open_logs_lock:
            return jsonify({"ok": True, "logs": list(_open_logs)})
    if request.method == "DELETE":
        with _open_logs_lock:
            _open_logs = []
        return jsonify({"ok": True})
    # POST: 全量覆盖
    data = request.get_json(force=True, silent=True) or {}
    logs = data.get("logs")
    if not isinstance(logs, list):
        return jsonify({"ok": False, "err": "need logs list"}), 400
    # 规范化：只保留需要的字段
    clean = []
    for l in logs:
        if not isinstance(l, dict):
            continue
        name = str(l.get("name", "")).strip()
        path = str(l.get("path", "")).strip()
        if not name or not path:
            continue
        clean.append({
            "name": name,
            "path": path,
            "port_id": str(l.get("port_id", "")),
            "total": int(l.get("total", 0) or 0),
        })
    with _open_logs_lock:
        _open_logs = clean
    return jsonify({"ok": True, "count": len(clean)})


# ---- MCP 状态信息（前端面板展示 + MCP server 上报调用记录） ----
@app.route("/api/ai/mcp_info")
def ai_mcp_info():
    """返回 MCP 相关信息：后端地址、已注册工具列表、最近调用记录。
    工具列表从 mcp_server.py 静态定义读取（硬编码在此保持一致），调用记录由 mcp_server 上报。"""
    tools = [
        {"name": "observe", "desc": "概览所有连接 + 最近输出 + 已打开日志"},
        {"name": "list_ports", "desc": "列出可用串口 + 已连接"},
        {"name": "connect_serial", "desc": "建立串口连接"},
        {"name": "connect_ssh", "desc": "建立 SSH 连接"},
        {"name": "send_command", "desc": "发命令 + 等回显"},
        {"name": "send_raw", "desc": "发原始字节（Ctrl-C 等）"},
        {"name": "get_buffer", "desc": "取连接最近 N 行缓冲"},
        {"name": "list_open_logs", "desc": "列出前端已打开的日志文件"},
        {"name": "read_log", "desc": "读日志文件（分页）"},
        {"name": "search_log", "desc": "日志关键字搜索"},
        {"name": "diff_logs", "desc": "对比两份日志差异（summary/line）"},
        {"name": "disconnect", "desc": "断开连接"},
    ]
    with _mcp_calls_lock:
        calls = list(_mcp_calls)
    # 读 endpoint 信息
    ep_info = {}
    try:
        ep_path = os.path.join(STATE_DIR, "endpoint.json")
        if os.path.isfile(ep_path):
            with open(ep_path, "r", encoding="utf-8") as f:
                ep_info = json.load(f)
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "backend_url": ep_info.get("url", ""),
        "endpoint": ep_info,
        "tools": tools,
        "recent_calls": calls,
    })


@app.route("/api/ai/mcp_report", methods=["POST"])
def ai_mcp_report():
    """MCP server 每次工具调用后上报记录，前端状态面板展示最近活动。"""
    data = request.get_json(force=True, silent=True) or {}
    entry = {
        "ts": time.time(),
        "tool": str(data.get("tool", "")),
        "args": str(data.get("args", ""))[:200],
        "ok": bool(data.get("ok", True)),
    }
    with _mcp_calls_lock:
        _mcp_calls.append(entry)
        if len(_mcp_calls) > _MCP_CALLS_MAX:
            _mcp_calls = _mcp_calls[-_MCP_CALLS_MAX:]
    return jsonify({"ok": True})


# 前端性能计时上报（诊断启动慢）
_perf_last = {}
@app.route("/api/ai/perf", methods=["POST", "GET"])
def ai_perf():
    """前端上报页面加载各阶段耗时（ms）。GET 返回最近一次。"""
    global _perf_last
    if request.method == "GET":
        return jsonify({"ok": True, "perf": _perf_last})
    data = request.get_json(force=True, silent=True) or {}
    _perf_last = {**data, "ts": time.time()}
    return jsonify({"ok": True})

# ---- 命令库持久化（跨端口/重启保留） ----
@app.route("/api/cmd_lib")
def cmd_lib_get():
    """读取命令库 [{name, cmd}]。"""
    return jsonify({"ok": True, "lib": _load_cmd_lib()})

@app.route("/api/cmd_lib", methods=["POST"])
def cmd_lib_save():
    """保存整个命令库（前端全量覆盖）。body: {lib: [{name, cmd}]}"""
    data = request.get_json(force=True, silent=True) or {}
    lib = data.get("lib")
    if not isinstance(lib, list):
        return jsonify({"ok": False, "err": "need lib list"}), 400
    # 规范化：只保留 name/cmd 字段，cmd 必填
    clean = [{"name": str(c.get("name", "")).strip(), "cmd": str(c.get("cmd", "")).strip()}
             for c in lib if isinstance(c, dict) and str(c.get("cmd", "")).strip()]
    _save_cmd_lib(clean)
    return jsonify({"ok": True, "lib": clean})


if __name__ == "__main__":
    start_background()
    app.run(host="127.0.0.1", port=8765, threaded=True, debug=False, use_reloader=False)
