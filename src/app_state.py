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

# ---- home 锚点（用户定调：只有这两样放 home，data_dir 只管数据）----
# endpoint.json：MCP 服务发现锚点，路径必须固定（main/mcp_server/
#   harness_ask_mcp 各自本地定义 STATE_DIR=HOME_DIR 读写它，不随数据目录走）
# config.json：配置本体（含 data_dir），也需稳定位置——数据目录本身由它决定，
#   不能随数据目录搬。用户指定的 data_dir 只是现有数据所在，不含这两样。
HOME_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
CONFIG_FILE = os.path.join(HOME_DIR, "config.json")

def _default_data_dir():
    """数据目录（日志/笔记/缓存）默认值。用户定调（v2.2.2）：
    - 未指定路径 → 统一在工具目录下建英文名文件夹 data（源码=项目根\\data，
      exe=exe 旁\\data），所有数据都进这里，备份工具目录即备份全部数据
    - 不允许临时目录——工具目录不可写时不偷偷落到别处（凭据会散落两处，
      同事机实锤踩坑），保持指向工具目录并记录告警：登录等写盘操作会
      显式报错，引导用户把工具挪到可写目录
    - 实际生效值可被 config.json 的 data_dir 覆盖（设置界面可改+迁移），
      迁移后以迁移的为准"""
    cand = os.path.join(BASE_DIR, "data")
    try:
        os.makedirs(cand, exist_ok=True)
        # 真实写测试替代 os.access——W_OK 在受控目录/网络盘上会误报可写
        probe = os.path.join(cand, ".wprobe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except Exception as e:
        import logging
        logging.getLogger("app_state").error(
            "数据目录不可写：%s（%s）——请把工具移到可写目录后重启，"
            "登录/凭据等写盘操作将失败", cand, e)
    return cand

def _load_home_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_HOME_CFG = _load_home_config()
# 数据目录：config 的 data_dir > 默认值（config 里旧的 log_dir 是单独日志目录，继续生效）
# v2.2.2 用户定调：迁移/指定过的 data_dir 以它为准；默认=工具目录\data。
# makedirs 失败不换临时目录（同 _default_data_dir 口径），保持指向并让
# 写盘操作显式报错
DATA_DIR = _HOME_CFG.get("data_dir") or _default_data_dir()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    import logging
    logging.getLogger("app_state").error(
        "数据目录创建失败：%s（%s）——请检查路径权限", DATA_DIR, e)
# ⚠ 命名陷阱：本处 STATE_DIR=数据目录（mm_probe/迁移逻辑用）；而 main/
# mcp_server/harness_ask_mcp 各自本地定义的 STATE_DIR=HOME_DIR
# （endpoint.json 锚点）。同名不同义，互不相干——endpoint/config 永远固定
# HOME_DIR，不随 data_dir 迁移（用户定调：指定目录只是数据所在）
STATE_DIR = DATA_DIR

# 日志目录：config 旧 log_dir（老用户自定义过）> 数据目录/logs
DEFAULT_LOG_DIR = os.path.join(DATA_DIR, "logs")
# 命令库持久化（跨端口/重启保留）——数据目录内（备份数据目录即备份全部用户数据）。
# 旧版本在 BASE_DIR/cmdlib.json：启动自动归位到数据目录（不覆盖，删旧位置）。
CMD_LIB_FILE = os.path.join(DATA_DIR, "cmdlib.json")

def _migrate_legacy_user_data():
    """旧位置用户数据自动归位到数据目录（防「找不到了」，不阻塞启动）：
    - BASE_DIR/cmdlib.json → DATA_DIR/cmdlib.json
    - 旧日志（BASE_DIR/serial_logs/ 及其历史形态 ~/.serialconsole_pro/logs、
      旧数据目录 logs）→ 一律并入 DATA_DIR/logs（目录合一：只留一个 logs），
      并清掉 config.log_dir 让其走默认——日志库从此只认 data/logs。
    归位原则：新位置已有同名不覆盖；复制成功才删旧文件。"""
    import shutil
    try:
        # cmdlib.json
        legacy_cmd = os.path.join(BASE_DIR, "cmdlib.json")
        if os.path.isfile(legacy_cmd) and os.path.normpath(legacy_cmd) != os.path.normpath(CMD_LIB_FILE):
            if not os.path.exists(CMD_LIB_FILE):
                shutil.copy2(legacy_cmd, CMD_LIB_FILE)
            if os.path.exists(CMD_LIB_FILE):
                os.remove(legacy_cmd)
        # 旧日志目录合并入 data/logs
        final_logs = os.path.join(DATA_DIR, "logs")
        os.makedirs(final_logs, exist_ok=True)
        legacy_log_dirs = [
            os.path.join(BASE_DIR, "serial_logs"),                    # 旧版本工具目录
            os.path.join(BASE_DIR, "data", "serial_logs"),            # 上一版归位目标
            os.path.join(DATA_DIR, "serial_logs"),
        ]
        merged = 0
        for legacy in legacy_log_dirs:
            if not os.path.isdir(legacy) or os.path.normpath(legacy) == os.path.normpath(final_logs):
                continue
            # 递归复制（旧目录里可能有用户手工归档的子目录，顶层 copy2 会
            # IsADirectoryError 且被吞掉，随后 rmtree 连子目录一起删=数据丢失）
            merged_this = 0
            unmerged = []
            for root, dirs, files in os.walk(legacy):
                rel = os.path.relpath(root, legacy)
                droot = final_logs if rel == "." else os.path.join(final_logs, rel)
                os.makedirs(droot, exist_ok=True)
                for fn in files:
                    s, d = os.path.join(root, fn), os.path.join(droot, fn)
                    if os.path.exists(d):
                        continue
                    try:
                        shutil.copy2(s, d)
                        merged_this += 1
                    except Exception:
                        unmerged.append(fn)
                for dn in dirs:
                    if not os.path.isdir(os.path.join(droot, dn)):
                        unmerged.append(dn + os.sep)
            merged += merged_this
            # rmtree 前核对：本目录全部条目已复制成功才删旧目录，否则保留（宁可留旧目录）
            if merged_this and not unmerged:
                shutil.rmtree(legacy, ignore_errors=True)
        # config.log_dir 指旧位置的 → 清掉走默认（data/logs）；指外部自定义的不动
        cfg = _load_config()
        old_ld = cfg.get("log_dir") or ""
        if old_ld and os.path.abspath(old_ld) != os.path.abspath(final_logs):
            # 指向的不是最终目录：若在已知旧位置集合内则清除（走默认合一）；
            # 指向完全外部目录的保留（用户特意自定义）
            known_old = {os.path.abspath(p) for p in legacy_log_dirs if os.path.isdir(p)}
            if os.path.abspath(old_ld) in known_old or os.path.abspath(old_ld).endswith("serial_logs"):
                cfg.pop("log_dir", None)
                _save_config(cfg)
                global LOG_DIR
                if not os.environ.get("SERIAL_LOG_DIR"):
                    LOG_DIR = final_logs
    except Exception:
        pass

_migrate_legacy_user_data()

# ---- 配置 ----
# v3.4.54：config.json 五方共写（roles/vision/prompts/routes×2/app_state/
# tftp）互不加锁、_save_config 还是裸 "w" 直写——撕裂一旦发生，各读方
# except 返回 {} 会让下一次任一保存把全量配置静默清零。收敛为：模块级
# _CONFIG_LOCK 串行化全部落盘 + 原子写（tmp+replace，唯一 tmp 名）+ 坏读
# .bad 隔离（对齐 harness meta.py 惯例）。
_CONFIG_LOCK = threading.Lock()

def cfg_read():
    """读 config.json。FileNotFoundError → {}；损坏（JSONDecodeError/
    OSError）→ 先改名 .bad 留档供人工找回，再当 {} 起步——坏内容绝不
    再经保存路径放大成全量清空。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        try:
            os.replace(CONFIG_FILE, CONFIG_FILE + ".bad")
        except OSError:
            pass
        return {}

def cfg_commit(mutator):
    """原子读-改-写 config.json（锁内整事务）。mutator(d) 就地修改 d。
    返回 (ok, err)。读方语义：锁外热路径读不加锁（GIL 下瞬时陈旧可容忍），
    关键在坏文件已被 cfg_read 隔离、写方全部串行。"""
    import time as _time
    with _CONFIG_LOCK:
        d = cfg_read()
        if not isinstance(d, dict):
            d = {}
        try:
            r = mutator(d)
            if isinstance(r, dict):
                d = r
            os.makedirs(HOME_DIR, exist_ok=True)
            tmp = "%s.tmp.%d.%d" % (CONFIG_FILE, os.getpid(), threading.get_ident())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            try:
                os.replace(tmp, CONFIG_FILE)
            except PermissionError:
                _time.sleep(0.08)   # 目标被读句柄/杀软短暂持有：重试一次
                os.replace(tmp, CONFIG_FILE)
            return True, None
        except Exception as e:
            return False, str(e)

def _load_config():
    """读取持久化配置（home 锚点 config.json：数据目录/日志目录/主题/最近记录）。"""
    return cfg_read()

def _save_config(cfg):
    """保存配置到 home 锚点 config.json。整量替换语义（历史 22 调用点不
    改）；v3.4.54 起锁内原子写（此前裸 "w" 直写是撕裂的头号来源）。"""
    def _whole(d):
        d.clear()
        d.update(cfg)
    cfg_commit(_whole)

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


# ---- Windows 保留设备名防线（a239 第5轮B1：CON/COM1 等设备名传给 open() 会
# 永久阻塞 worker 线程——flask threaded 下 30 并发即泄漏 30 线程不可回收）----
_WIN_RESERVED = ({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                 | {"COM%d" % i for i in range(1, 10)}
                 | {"LPT%d" % i for i in range(1, 10)})


def reject_win_devpath(path):
    """路径含 NUL 或 basename 命中 Windows 保留设备名 → True（调用方 400 拒）。
    CON.txt 这类「带扩展名的设备名」同样会打开设备，按去扩展名判定。"""
    try:
        s = str(path)
    except Exception:
        return True
    if not s or "\x00" in s:
        return True
    base = os.path.basename(s.rstrip(chr(92) + "/"))   # \ 与 /（避免源码转义歧义）
    stem = base.split(".")[0].rstrip(". ") if "." in base else base.rstrip(". ")
    return stem.upper() in _WIN_RESERVED
