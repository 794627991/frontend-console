# -*- coding: utf-8 -*-
"""应用共享状态与配置工具。
集中管理跨模块共享的全局状态（连接表/AI 订阅/日志索引/MCP 调用记录/序列号）
及路径常量、配置/命令库读写、序列号生成。各功能模块从此 import。
"""
import os, sys, json, threading, itertools

# ---- 路径常量 ----
# app_state 在 src/ 下，上溯两层到项目根（server/main 等也从 src/ 以 src.* 引用本模块）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _resource_base():
    return getattr(sys, "_MEIPASS", BASE_DIR)
RES_DIR = _resource_base()

# ---- home 锚点（用户口径：只有这两样放 home）----
# endpoint.json：MCP 服务发现锚点，路径必须固定（serial_cli/mcp_server 硬编码读它）
# config.json：配置本体（含 data_dir），也需稳定位置——数据目录本身由它决定，不能随数据目录搬
HOME_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
CONFIG_FILE = os.path.join(HOME_DIR, "config.json")

def _default_data_dir():
    """数据目录（日志/笔记/缓存）默认值（用户口径修正：数据跟工具目录走）。
    默认 = 工具所在目录\\data（源码运行=项目根\\data，exe=exe 旁\\data）——
    备份工具目录即备份全部数据。仅当工具目录不可写时才退 C 盘用户目录。
    实际生效值可被 config.json 的 data_dir 覆盖（设置界面可改+迁移）。"""
    cand = os.path.join(BASE_DIR, "data")
    try:
        os.makedirs(cand, exist_ok=True)
        if os.access(cand, os.W_OK):
            return cand
    except Exception:
        pass
    return os.path.join(HOME_DIR, "data")   # 兜底（工具目录只读等罕见场景）

def _load_home_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_HOME_CFG = _load_home_config()
# 数据目录：config 的 data_dir > 默认值（config 里旧的 log_dir 是单独日志目录，继续生效）
DATA_DIR = _HOME_CFG.get("data_dir") or _default_data_dir()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = os.path.join(HOME_DIR, "data")
STATE_DIR = DATA_DIR   # 兼容旧代码引用：STATE_DIR 语义=数据目录（endpoint 写入仍用 HOME_DIR）

# 日志目录：config 旧 log_dir（老用户自定义过）> 数据目录/logs
DEFAULT_LOG_DIR = os.path.join(DATA_DIR, "logs")
# 命令库持久化（跨端口/重启保留）——数据目录内（备份数据目录即备份全部用户数据）。
# 旧版本在 BASE_DIR/cmdlib.json：启动自动归位到数据目录（不覆盖，删旧位置）。
CMD_LIB_FILE = os.path.join(DATA_DIR, "cmdlib.json")

def _migrate_legacy_user_data():
    """旧位置用户数据自动归位到数据目录（防「找不到了」，不阻塞启动）：
    - BASE_DIR/cmdlib.json → DATA_DIR/cmdlib.json
    - BASE_DIR/serial_logs/ → DATA_DIR/serial_logs/（旧版本日志目录，
      归位后同步把 config.log_dir 指到新位置——绝不丢日志库读取路径）
    归位原则：新位置已有同名不覆盖；复制成功才删旧位置文件。"""
    import shutil
    try:
        # cmdlib.json
        legacy_cmd = os.path.join(BASE_DIR, "cmdlib.json")
        if os.path.isfile(legacy_cmd) and os.path.normpath(legacy_cmd) != os.path.normpath(CMD_LIB_FILE):
            if not os.path.exists(CMD_LIB_FILE):
                shutil.copy2(legacy_cmd, CMD_LIB_FILE)
            if os.path.exists(CMD_LIB_FILE):
                os.remove(legacy_cmd)
        # serial_logs/（旧日志目录）：复制全部 → 更新 config.log_dir → 删旧目录
        legacy_logs = os.path.join(BASE_DIR, "serial_logs")
        dst_logs = os.path.join(DATA_DIR, "serial_logs")
        if os.path.isdir(legacy_logs) and os.path.normpath(legacy_logs) != os.path.normpath(dst_logs):
            os.makedirs(dst_logs, exist_ok=True)
            moved = 0
            for fn in os.listdir(legacy_logs):
                s, d = os.path.join(legacy_logs, fn), os.path.join(dst_logs, fn)
                if os.path.exists(d):
                    continue
                try:
                    shutil.copy2(s, d)
                    moved += 1
                except Exception:
                    pass
            if moved:
                # config.log_dir 指旧位置（或未配置）→ 指到新位置；用户自定义指向别处的不动
                cfg = _load_config()
                old_ld = cfg.get("log_dir") or ""
                if not old_ld or os.path.abspath(old_ld) == os.path.abspath(legacy_logs):
                    cfg["log_dir"] = dst_logs
                    _save_config(cfg)
                shutil.rmtree(legacy_logs, ignore_errors=True)
                # 模块级 LOG_DIR 已在 import 时定值，同步运行时
                global LOG_DIR
                if os.environ.get("SERIAL_LOG_DIR"):
                    pass   # 环境变量优先级最高，不动
                elif not old_ld or os.path.abspath(old_ld) == os.path.abspath(LOG_DIR):
                    LOG_DIR = dst_logs
    except Exception:
        pass

_migrate_legacy_user_data()

# ---- 配置 ----
def _load_config():
    """读取持久化配置（home 锚点 config.json：数据目录/日志目录/主题/最近记录）。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_config(cfg):
    """保存配置到 home 锚点 config.json（~/.serialconsole_pro/，不随数据目录迁移）。"""
    try:
        os.makedirs(HOME_DIR, exist_ok=True)
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
    """保存命令库到工具目录 cmdlib.json。（用户铁律：外部不得改命令库，仅工具 UI 写）"""
    try:
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
