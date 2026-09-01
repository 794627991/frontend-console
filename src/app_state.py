# -*- coding: utf-8 -*-
"""应用共享状态与配置工具。
集中管理跨模块共享的全局状态（连接表/AI 订阅/日志索引/MCP 调用记录/序列号）
及路径常量、配置/命令库读写、序列号生成。各功能模块从此 import。
"""
import os, sys, json, threading, itertools

# ---- 路径常量 ----
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

# ---- 配置 ----
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

# ---- 命令库持久化 ----
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

# ---- 全局单调递增序列号 ----
# 作为分页/搜索的稳定游标（避免 ms 时间戳同值）
_SEQ_COUNTER = itertools.count(1)
_SEQ_LOCK = threading.Lock()

def _next_seq():
    with _SEQ_LOCK:
        return next(_SEQ_COUNTER)

# ---- 连接表（port_id -> SerialPort/SSHConnection）----
_ports = {}
_ports_lock = threading.Lock()

# ---- AI 接入层状态 ----
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

# ---- 日志索引缓存 ----
from .log_index import LogIndex
_log_index_cache = {}  # path -> LogIndex
_log_index_lock = threading.Lock()

def _get_log_index(path):
    """获取/缓存日志索引。每次调用都触发 build()——内部按 _built_size
    判断文件是否追加，未变则 O(1) 返回，追加则增量续扫。"""
    with _log_index_lock:
        if path not in _log_index_cache:
            _log_index_cache[path] = LogIndex(path)
        idx = _log_index_cache[path]
        idx.build()
        return idx

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
