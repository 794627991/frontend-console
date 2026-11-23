#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端控制台 —— Electron 壳的 headless 后端入口
- Flask 后端（多串口管理 + AI 接入层），窗口/托盘/WebView 全归 Electron 壳
- PyInstaller --windowed 由壳 spawn，带 --headless 启动
- 单实例：壳 requestSingleInstanceLock 负责；本进程不抢锁
"""
import os, sys, threading, json, time
import urllib.request


# a675（用户定调「非必要不写 IO」）：入口级兜底——模块顶层未捕获异常（如
# a663 漏 import atexit 的 NameError）在 pythonw 下完全无痕，进程直接蒸发。
# 装最小 excepthook：**仅异常时**写 boot_error.log（正常启动零写盘）；
# 下次成功启动由 main() 的提示逻辑读入内存日志并改名 .seen。
def _fatal_hook(et, ev, tb):
    try:
        import time as _t
        import traceback as _tb
        # 锚点公式与 app_state._anchor_dir 同步（此刻可能尚在解密前，不可 import src）
        d = os.path.join(os.environ.get("FC_STATE_DIR")
                         or os.path.join(os.environ.get("APPDATA")
                                         or os.path.expanduser("~"),
                                         "frontend-console-shell", "backend"))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "boot_error.log")
        try:
            if os.path.exists(p) and os.path.getsize(p) > 64 * 1024:
                os.replace(p, p + ".1")
        except Exception:
            pass
        with open(p, "a", encoding="utf-8", errors="replace") as f:
            f.write("[%s] 顶层未捕获异常: %s" % (
                _t.strftime("%Y-%m-%d %H:%M:%S"), repr(ev)))
            f.write(chr(10) + "".join(_tb.format_exception(et, ev, tb)) + chr(10))
    except Exception:
        pass
    try:
        sys.__excepthook__(et, ev, tb)
    except Exception:
        pass


try:
    sys.excepthook = _fatal_hook
except Exception:
    pass

# a242（用户实锤「运行中自己重启」取证）：faulthandler 全程挂载——native 层
# 崩溃（C 扩展/第三方 DLL/ctypes）无 Python traceback 直接蒸发进程，此后任何
# 致命信号都会把全线程栈写到 crash_dump.log，现场不再丢失
try:
    import faulthandler as _fh
    # 锚点公式与 app_state._anchor_dir 同步（解密前不可 import src；
    # 2026-11-23 起 crash_dump.log 落锚点，与 endpoint 同在锚点）
    _CRASH_LOG = os.path.join(
        os.environ.get("FC_STATE_DIR")
        or os.path.join(os.environ.get("APPDATA")
                        or os.path.expanduser("~"),
                        "frontend-console-shell", "backend"),
        "crash_dump.log")
    os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
    _fh.enable(file=open(_CRASH_LOG, "a", encoding="utf-8", errors="replace"),
               all_threads=True)
except Exception:
    pass

# 所有源码都在 src/ 下，import src.* 需要项目根在 sys.path（python src/main.py 时根不在 path）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# v2.1.0：版本单一源（窗口标题/单实例匹配/升级比对统一从这取）
# v2.3.1 自举解密（内联，不依赖 src.*——此刻 src 还是密文）：frozen 包内
# 自有 pyc/web 资产为 AES-GCM 密文（spec excludes src + tools/encrypt_pkg），
# 这里解密还原后下方 import src.* 才能命中文件系统。dev 模式零动作。
# 混淆常量与 src/secure_boot.py 必须同步（两处，改口令一起改）。
def _fc_decrypt():
    """v2.3.7 修复致命缺陷：web 密文 .enc 永久保留（此前解密后删除 →
    下次启动无密可解 → 永远白屏，用户抓到）。改为目录扫描式：
    - _internal/web/**/*.enc → 每次启动解密进内存（.enc 保留，密文无害）
    - _internal/src/*.enc（blob 等落盘型）→ 解密落盘并删 .enc（一次性）
    幂等：.enc 在就解，不在就跳过。"""
    if not getattr(sys, "frozen", False):
        return {}
    import os as _os, hashlib as _hl, glob as _gl
    root = _os.path.join(_os.path.dirname(sys.executable), "_internal")
    # v2.3.8 诊断：解密各阶段落盘（exe 条数 0 排查用，确认后移除）
    try:
        with open(_os.path.join(root, "_fc_debug.txt"), "w", encoding="utf-8") as _f:
            _f.write("root=%r\nweb_dir=%r\nmf=%r\nmf存在=%r\n" % (
                root, _os.path.join(root, "web"),
                _os.path.join(root, ".fcenc"),
                _os.path.isfile(_os.path.join(root, ".fcenc"))))
    except Exception as _e:
        try:
            with open(_os.path.join(root, "_fc_debug.txt"), "w", encoding="utf-8") as _f:
                _f.write("诊断自身失败: %r" % _e)
        except Exception:
            pass
    try:
        from Crypto.Cipher import AES
        _KX, _KM = 0x5A, [0x6D, 0x6E, 0x6A, 0x6E, 0x6B, 0x6A]
        _SX, _SM = 0x3C, [0x1C, 0x1D, 0x19, 0x1D, 0x58, 0x59, 0x5D, 0x59,
                          0x0D, 0x0C, 0x08, 0x0C, 0x49, 0x48, 0x4C, 0x48]
        key = _hl.pbkdf2_hmac(
            "sha256", "".join(chr(b ^ _KX) for b in _KM).encode(),
            bytes(b ^ _SX for b in _SM), 120000)
        mem_web = {}
        web_dir = _os.path.join(root, "web")
        _enc_hits = _gl.glob(_os.path.join(web_dir, "**", "*.enc"), recursive=True)
        try:
            with open(_os.path.join(root, "_fc_debug.txt"), "a", encoding="utf-8") as _f:
                _f.write("glob命中=%d\n" % len(_enc_hits))
        except Exception:
            pass
        for enc in _enc_hits:
            with open(enc, "rb") as f:
                blob = f.read()
            if blob[:5] != b"FCEN\x01":
                continue   # 坏文件跳过不炸启动
            pt = AES.new(key, AES.MODE_GCM, nonce=blob[5:17]).decrypt_and_verify(
                blob[33:], blob[17:33])
            rel = _os.path.relpath(enc, root)[:-4].replace("\\", "/")
            mem_web[rel] = pt    # .enc 保留——下次启动还要用
        # blob 等落盘型（src/*.enc）：解密覆盖落盘，.enc 同样永久保留
        # （用户定调：永远不删——幂等覆盖，下次启动重复解密无害）
        for enc in _gl.glob(_os.path.join(root, "src", "*.enc")):
            plain = enc[:-4]
            with open(enc, "rb") as f:
                blob = f.read()
            if blob[:5] != b"FCEN\x01":
                continue
            pt = AES.new(key, AES.MODE_GCM, nonce=blob[5:17]).decrypt_and_verify(
                blob[33:], blob[17:33])
            with open(plain, "wb") as f:
                f.write(pt)
    except Exception as e:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "程序资源校验失败，无法启动：\n%s" % e, "前端控制台", 0x10)
        sys.exit(1)
    # v2.3.8 致命修复：此前版本丢失了 return——函数隐式返回 None →
    # 前端资源全 404 白屏（用户实锤）。glob 解密循环已填 mem_web，必须返回。
    return mem_web

# v2.3.6：web 明文挂 sys（server.py 的 / 与 /web/* 路由优先从这 serve，
# 磁盘永远密文）。挂 sys 而非模块属性——frozen 下入口脚本模块名是 main
# 不是 src.main，server 里 import src.main 必 ImportError（实测白屏）
sys.FC_MEM_WEB = _fc_decrypt()
from src.version import APP_VERSION

import ctypes


def resource_path(rel):
    """兼容 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ---- Claude Code 直连入口：endpoint 文件 ----
# 工具启动时把本地 HTTP 服务地址写到固定文件，任何 Claude Code 会话读它即可发现服务。
# 2026-11-23 退役改造：锚点=%APPDATA%\frontend-console-shell\backend（与壳
# userData 同一家，见 app_state._anchor_dir）——不再写 ~/.serialconsole_pro
from src import app_state as _st_anchor
STATE_DIR = _st_anchor.HOME_DIR

# ---- a663 退出原因审计已合并进 backend_log（单一真源，避免两套审计）----
def _exit_reason(why):
    try:
        from src import backend_log as _bl
        _bl.set_exit_reason(why)
    except Exception:
        pass


def _audit_exit():
    try:
        from src import backend_log as _bl
        _bl.audit_exit()
    except Exception:
        pass


# Electron 壳（换壳迁移）与测试实例可用 FC_ENDPOINT_FILE 指到别处——默认
# 路径与历史行为完全一致；覆盖只影响本进程写哪，读侧（server.py 探活查询）
# 仍走默认路径，不误报
ENDPOINT_FILE = os.environ.get("FC_ENDPOINT_FILE") or os.path.join(
    STATE_DIR, "endpoint.json")

def write_endpoint(port):
    """把本地 HTTP 服务地址写到固定文件，供 Claude Code 跨会话发现。"""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        from datetime import datetime
        ep = {
            "url": f"http://127.0.0.1:{port}",
            "port": port,
            "pid": os.getpid(),
            "started_at": datetime.now().isoformat(),
            # epoch 毫秒：Electron 壳的就绪判据（跨语言精确比较，ISO 串
            # 免时区解析歧义）。旧读方（Claude 发现/server 探活）忽略未知键
            "boot_ms": int(time.time() * 1000),
            # Electron 壳启动亲和令牌：壳 spawn 时注入 FC_BOOT_TOKEN，
            # 这里原样回写——壳只认与自己 token 匹配的 endpoint，杜绝
            # 认到旧形态/陈旧后端（boot_ms 时间窗在时钟回拨时会误判）
            "boot_token": os.environ.get("FC_BOOT_TOKEN") or "",
            # 后端的工具目录\data（config 的家）。壳读 config（close_to_tray）
            # 直接用它——两边永远同址，不必各自从 __dirname 推（嵌套形调试包
            # 里壳与后端不在同一层，各推各的会错位；第八轮审计 R8-6）。
            "tool_data_dir": _st_anchor.TOOL_DATA_DIR,
        }
        with open(ENDPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(ep, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def clear_endpoint():
    """工具关闭时清理 endpoint 文件。"""
    try:
        if os.path.isfile(ENDPOINT_FILE):
            os.remove(ENDPOINT_FILE)
    except Exception:
        pass


def _run_mcp_mode():
    """MCP stdio 模式：把 mcp_server.py 的逻辑作为子模块运行。
    PyInstaller --windowed 下 sys.stdin/stdout 可能为 None，用 fd 重新包装。"""
    # windowed exe 的 sys.stdin/stdout 可能是 None，但 fd 0/1 存在（subprocess pipe）
    if sys.stdin is None:
        try: sys.stdin = open(0, 'r', encoding='utf-8')
        except Exception: pass
    if sys.stdout is None:
        try: sys.stdout = open(1, 'w', encoding='utf-8')
        except Exception: pass
    # 延迟 import，避免主路径加载 mcp_server 的依赖
    from src import mcp_server
    mcp_server.main()


def _run_mcp_ask_mode():
    """交互式提问 MCP stdio 模式（v2.17）。
    打包（PyInstaller --windowed）后 src/harness/ask_mcp.py 不在磁盘上，harness
    会话的 --mcp-config 会改指 `exe --mcp-ask`，就是这里。与 --mcp 同样的
    fd 重包装：windowed 下 sys.stdin/stdout 可能是 None。"""
    if sys.stdin is None:
        try: sys.stdin = open(0, 'r', encoding='utf-8')
        except Exception: pass
    if sys.stdout is None:
        try: sys.stdout = open(1, 'w', encoding='utf-8')
        except Exception: pass
    from src.harness import ask_mcp as harness_ask_mcp
    harness_ask_mcp.main()


def _run_mcp_vision_mode():
    """识图 MCP stdio 模式（v2.28）。
    打包后 src/harness/vision_mcp.py 不在磁盘上，harness 会话 --mcp-config 里的
    4_5v_mcp server 指向 `exe --mcp-vision`，就是这里。fd 重包装同 --mcp-ask。"""
    if sys.stdin is None:
        try: sys.stdin = open(0, 'r', encoding='utf-8')
        except Exception: pass
    if sys.stdout is None:
        try: sys.stdout = open(1, 'w', encoding='utf-8')
        except Exception: pass
    from src.harness import vision_mcp as harness_vision_mcp
    harness_vision_mcp.main()


def _run_audit_hook_mode():
    """light 形态直改轻审线的事中闸 hook 模式。
    PreToolUse hook：CLI 在每次 Edit/Write/MultiEdit/NotebookEdit 前调起本
    进程，查后端 /api/harness/audit_gate——本回合直改达轻审线上限且尚未派过
    reviewer 则 exit 2 拦下（stderr 指路送审，审过即开闸），否则/任何异常
    exit 0 放行（闸失效不阻塞）。
    打包后走 `exe --audit-hook`（与 --mcp-ask 同模式：src 不在盘上）；windowed
    下 stdin/stderr 可能为 None，fd 重包装同款。逻辑在 harness.audit_hook。"""
    if sys.stdin is None:
        try: sys.stdin = open(0, 'r', encoding='utf-8')
        except Exception: pass
    if sys.stderr is None:
        try: sys.stderr = open(2, 'w', encoding='utf-8')
        except Exception: pass
    from src.harness import audit_hook as harness_audit_hook
    harness_audit_hook.main()


def _run_claude_worker_mode():
    """--claude-worker 模式：Claude 子系统独立进程（v4.0.0 串口卡顿根治）。

    harness 会话/v4 feed/子代理 watcher/HikLink 机器人在此进程承载，
    与主进程（串口终端）分 GIL 域——Claude 后端随便烧，串口零影响
    （用户铁律：流畅第一）。拉起/监护/退出回收在 src.worker_app 的
    manage_* 侧；本模式必须在单实例锁之前返回（worker 是主实例派生的
    常驻子进程，不抢 mutex）。stdout 承载 WORKER_READY 就绪协议，
    windowed 打包下 fd 可能为 None，重包装同 --mcp-ask。"""
    if sys.stdout is None:
        try: sys.stdout = open(1, 'w', encoding='utf-8')
        except Exception: pass
    from src import worker_app
    worker_app.main()


def _setup_job_object():
    """Windows Job Object（JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE）：主进程
    退出（含强杀/Crash）时内核自动 TERMINATE 全部子进程。零孤儿，rg.exe/
    ctags.exe/codegraph 不再残留。启动最早调（所有后续 Popen 自动入 Job）"""
    global _job_handle
    try:
        import ctypes
        import ctypes.wintypes as _wt

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class _BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]

        class _EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC_LIMIT),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.windll.kernel32
        # a382-4（实测实锤）：ctypes 默认 restype=c_int 在 64 位下截断
        # 句柄（CreateJobObjectW 返回的 HANDLE 也会截）——全部显式声明
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        hJob = kernel32.CreateJobObjectW(None, None)
        if not hJob:
            return
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        # JobObjectExtendedLimitInformation = 9
        if not kernel32.SetInformationJobObject(
                hJob, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return
        # a382-4（实测实锤）：GetCurrentProcess 返回伪句柄（-1），经 ctypes
        # 默认 restype=c_int 在 64 位下截断 → AssignProcessToJobObject 报
        # ERROR_INVALID_HANDLE(6)。改 OpenProcess 拿真句柄
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        hProcess = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, os.getpid())
        if not hProcess:
            return
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        if not kernel32.AssignProcessToJobObject(hJob, hProcess):
            kernel32.CloseHandle(hProcess)
            return
        kernel32.CloseHandle(hProcess)   # 自身句柄即关（已入 Job，关系保持）
        _job_handle = hJob   # 全局保命：不关句柄（关了 Job 散了子进程就不杀了）
    except Exception:
        pass   # 非 Windows / 权限不足——不阻断启动，走 _kill_child_processes 兜底


def _kill_child_processes():
    """显式杀全部子进程（_do_real_cleanup 调）。a382 教训（用户内网实锤
    进程残留+rg.exe 占用）：防 Job Object 设置失败/子进程逃逸——taskkill
    /T /F 树杀保留为 **Job 不可用时的兜底**。a681（退出 6s 实测优化）：
    Job 在（_job_handle 非 None=启动时 Assign 成功）时直接返回——
    os._exit 后 KILL_ON_JOB_CLOSE 由内核收编全树（毫秒级，省 taskkill
    spawn+树遍历 ~1s，实测退出链尾段 1.24s 的大头）。本项目 Popen 均未
    用 CREATE_BREAKAWAY，子进程不可能逃出 Job。"""
    if _job_handle:
        return
    try:
        import subprocess
        # taskkill /T 树杀：主进程全部子进程+孙进程
        subprocess.run(
            ["taskkill", "/PID", str(os.getpid()), "/T", "/F"],
            capture_output=True, timeout=5,
            creationflags=0x08000000)
    except Exception:
        pass


# ---- 启动阶段计时（诊断）——用户定调「保留留待后续再用，只是不写磁盘」----
# 打点只进 backend_log 的**内存**环形缓冲（界面点版本号可视），另存模块级
# 列表供后续调试直接读取；全程零磁盘 IO。异常全静默（诊断不影响启动）。
_BOOT_T0 = time.perf_counter()
_BOOT_MARKS = []          # [(ms, label), ...] 本进程启动打点
_BOOT_ERRORS = []         # 启动链异常现场（日志/钩子安装失败等，供诊断）
_BOOT_FLUSHED = 0         # 已补进 backend_log 的条数（install 前的先缓存）


def _boot_flush():
    """把 install 前缓存的打点补进内存日志；未 install 则不动（下次再补）。"""
    global _BOOT_FLUSHED
    try:
        from src import backend_log
        if not backend_log.installed():
            return
        while _BOOT_FLUSHED < len(_BOOT_MARKS):
            _ms, _label = _BOOT_MARKS[_BOOT_FLUSHED]
            backend_log.log("boot", "+%6.0fms  %s" % (_ms, _label))
            _BOOT_FLUSHED += 1
    except Exception:
        pass


def _write_boot_error(exc):
    """安装链完全失败时的最后现场：异常才写的小文件（IO 可忽略）。

    pythonw 下 stderr 无控制台、_BOOT_ERRORS 仅进程内——完全失败时用户
    没有任何可见通道。这里按退出审计同款折中：仅异常写 <64KB 小文件，
    下次成功启动时提示进内存日志。
    """
    try:
        import os
        import time as _t
        import traceback as _tb
        # 锚点公式与 app_state._anchor_dir 同步；boot_error.log 新家=锚点
        d = os.path.join(os.environ.get("FC_STATE_DIR")
                         or os.path.join(os.environ.get("APPDATA")
                                         or os.path.expanduser("~"),
                                         "frontend-console-shell", "backend"))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "boot_error.log")
        try:
            if os.path.exists(p) and os.path.getsize(p) > 64 * 1024:
                os.replace(p, p + ".1")
        except Exception:
            pass
        with open(p, "a", encoding="utf-8", errors="replace") as f:
            f.write("[%s] 安装链失败: %s" % (_t.strftime("%Y-%m-%d %H:%M:%S"),
                                             repr(exc)))
            f.write(chr(10) + _tb.format_exc() + chr(10))
        return p
    except Exception:
        return ""


def _boot_mark(label):
    try:
        _BOOT_MARKS.append(((time.perf_counter() - _BOOT_T0) * 1000, label))
        _boot_flush()
    except Exception:
        pass


def main():
    # 2026-11-23 用户令：调试包免启动器——双击 前端控制台.exe 直启。exe 探测
    # 调试包布局（同层 electron-shell\dist\electron.exe）即拉起自带壳后退出，
    # 壳再以 --headless 把本 exe 拉回当后端（FC_BACKEND_EXE 契约，见
    # electron/main.js resolveBackend），最终进程树与 run.bat/Setup 形态一致。
    # 必须放 main() 最顶上：exe 跳板形态越早起壳越快（其后端日志装载等
    # 一概不需要），也天然先于 _setup_job_object()——Job 是
    # KILL_ON_JOB_CLOSE，本进程一退内核会杀光全部子进程，壳必须生在 Job 外。
    # 仅零参数触发（sys.argv[1:] 为空）——selftest/--mcp 等工具模式一律
    # 带参，不会被劫持，新增模式天然免疫。
    # 内网实锤（2026-11-23）：窗口子系统 exe 的 stderr 双击时不可见，布局
    # 不对会「零反应静默死」——致命路径一律 MessageBox + debug_launch.log
    # 留证。壳根两种落位都认（zip 扁平整/dist 树嵌套形，实锤翻车点）：
    #   扁平：<exe目录>\electron-shell     （zip 解压形态 = 内网实机形态）
    #   嵌套：<exe目录>\..\electron-shell  （dist 树形态 = 开发机形态）
    def _dbg_log(msg):
        try:
            # 对抗审计修正:落锚点(与 boot_error 同家)——数据目录可能被用户
            # 配置挪走/不可写(内网解到受保护位置正是调试包场景),锚点恒在
            from src import app_state as _st
            _d = _st.HOME_DIR
            os.makedirs(_d, exist_ok=True)
            with open(os.path.join(_d, "debug_launch.log"), "a",
                      encoding="utf-8") as _f:
                _f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        except Exception:
            pass

    def _dbg_msgbox(msg):
        # 仅 exe（frozen）弹窗；源码形态走 stderr，别打断测试/CI
        if not getattr(sys, "frozen", False):
            return
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, msg, "前端控制台（调试包）", 0x30)   # MB_ICONWARNING
        except Exception:
            pass

    if getattr(sys, "frozen", False) and not sys.argv[1:]:
        _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        _dbg_root = ""
        for _base in (_exe_dir, os.path.dirname(_exe_dir)):
            if os.path.isfile(os.path.join(_base, "electron-shell", "dist",
                                           "electron.exe")):
                _dbg_root = _base
                break
        if _dbg_root:
            _shell_exe = os.path.join(_dbg_root, "electron-shell", "dist",
                                      "electron.exe")
            print("[调试包] 拉起自带 Electron 壳…")
            os.environ["FC_BACKEND_EXE"] = os.path.abspath(sys.executable)
            import subprocess
            try:
                subprocess.Popen(
                    [_shell_exe, os.path.join(_dbg_root, "electron-shell")],
                    cwd=_dbg_root)
            except Exception as _e:
                _dbg_log("壳拉起失败 %s: %r" % (_shell_exe, _e))
                _dbg_msgbox("Electron 壳拉起失败：%r\n%s" % (_e, _shell_exe))
                sys.exit(2)
            _dbg_log("壳已拉起: %s" % _shell_exe)
            return
        _dbg_log("未找到壳（布局不对/整包未拷全？）: %s" % os.path.join(
            _exe_dir, "electron-shell", "dist", "electron.exe"))

    _boot_mark("===== boot =====")
    # 用户需求（2.4.4）：启动不再弹 cmd 黑框——日志由进程内环形缓冲接管
    # （src/backend_log.py，只驻内存不写盘），界面点标题栏版本号即可查看。
    # 必须在任何 print 之前装（此处之前只有 import，无输出）。子模式
    # （--mcp-ask/--audit-hook 等）是短命子进程且走 stdio 协议，绝不能接管
    # 它们的 stdout/stderr——真实用户看日志只会用主实例。
    if not any(a in sys.argv for a in (
            '--claude-worker', '--mcp-ask', '--mcp-vision', '--audit-hook',
            '--snip-grab', '--selftest')):
        try:
            from src import backend_log
            backend_log.install()
            # 用户定调「任何报错/警告/有用信息都往这里放，后续就是指定的
            # 调试手段」——三道收口全开：流接管 + logging 桥 + 未捕获异常钩子
            backend_log.install_logging_bridge()
            backend_log.install_excepthooks()
            # 用户令（2.4.4）：「启动时必须带上版本号」——日志本身要带版本，
            # 导出的日志才有追溯价值（否则拿到一份日志不知道是哪个版本出的）。
            # 第一条就写版本，且做成醒目的横幅，导出后一眼能看到。
            from src.version import APP_VERSION as _av
            backend_log.log("main", "=" * 60, "info")
            backend_log.log("main", "前端控制台 v%s 启动" % _av, "info")
            backend_log.log("main", "=" * 60, "info")
            backend_log.log("main", "后端日志缓冲已启用（10MB 内存，不写盘）")
            # a626（用户令）：harness 会话的 [harness] boot 系统消息条撤除
            # （现行代码已无注入——旧会话显示的是 a587 时代落盘的历史），
            # 等价信息由 log 系统启动时同步打印（版本 + harness 形态；
            # worker 端口由 worker 就绪消息自报，经 logging 桥可见）
            _harness_mode = "inline" if os.environ.get("CLAUDE_INLINE") else "v4 worker"
            # 终审 P2-5：主进程不 import harness（隔离设计——import 拖全家
            # +_git_harness_version 起子进程最多 5s）——harness 版本读 config
            # 缓存（worker 进程启动时写入，见 worker_app）
            _hv = ""
            try:
                from src.app_state import _load_config as _lc2
                _hv = " · harness v%s" % (_lc2().get("harness_version") or "?")
            except Exception:
                pass
            backend_log.log("main", "[harness] boot 工具 v%s%s [%s]（worker 端口见后续就绪日志）"
                            % (APP_VERSION, _hv, _harness_mode))
        except Exception as _e:
            # a672（用户实锤「启动横幅凭空消失」）：原静默 pass 把安装链内
            # 任何异常（如 a663 的 UnboundLocalError）全吞掉——横幅与退出
            # 审计一起无声失效。改为留现场：stderr + 模块级记录；仍不阻塞启动。
            _berr_path = _write_boot_error(_e)
            try:
                import traceback as _tb
                sys.stderr.write("[警告] 日志/异常钩子安装失败: " + repr(_e)
                                 + ("（详见 %s）" % _berr_path if _berr_path else "")
                                 + chr(10))
                _tb.print_exc(file=sys.stderr)
                sys.stderr.flush()
            except Exception:
                pass
            try:
                _BOOT_ERRORS.append(repr(_e))
            except Exception:
                pass
            # 日志面板可见性：backend_log 若已可用（部分失败场景），把异常
            # 写进内存日志（[boot] 行）；完全装不上时只能 stderr。
            try:
                from src import backend_log as _bl
                if _bl.installed():
                    _bl.error("boot", "日志/异常钩子安装失败: " + repr(_e))
            except Exception:
                pass
    _boot_mark("backend_log 就绪")
    # 上次启动若安装链彻底失败（写了 boot_error.log），本次成功时提示一行
    # 进内存日志并改名为 .seen（保留证据、不重复提示）。
    try:
        import os as _os
        # boot_error.log 只在锚点（见 _fatal_hook/_write_boot_error）；
        # 旧目录一概不看（用户令 2026-11-23：不考虑其他位置）
        try:
            from src import app_state as _st_be
            _be = _os.path.join(_st_be.HOME_DIR, "boot_error.log")
        except Exception:
            _be = ""
        if _os.path.exists(_be):
            try:
                from src import backend_log as _bl3
                if _bl3.installed():
                    _bl3.warn("boot", "上次启动日志初始化失败，详见 " + _be)
            except Exception:
                pass
            try:
                _os.replace(_be, _be + ".seen")
            except Exception:
                pass
    except Exception:
        pass
    #（调试包直启分支已前置到 main() 顶部——exe 跳板形态越早起壳越快，
    #  且必须先于 _setup_job_object()；此处不再重复）
    # 用户实锤（内网）：程序退出后主进程残留+rg.exe 占用——Job Object 绑杀
    # 全部子进程（rg/ctags/codegraph/worker 等）：主进程一退（含强杀），
    # Windows 内核自动 TERMINATE 全部子进程，零孤儿
    _setup_job_object()
    # --claude-worker 模式：Claude 子系统 worker（见 _run_claude_worker_mode；
    # 必须先于单实例锁——主实例派生的子进程不抢 mutex）
    if '--claude-worker' in sys.argv:
        _run_claude_worker_mode()
        return
    # --no-claude-worker：回落旧单进程形态（排障通道）。必须在 server 预
    # 导入线程之前置位——server.py 在 import 时读 CLAUDE_INLINE 定形态
    if '--no-claude-worker' in sys.argv:
        os.environ["CLAUDE_INLINE"] = "1"
    # --mcp-ask 模式：交互式提问 MCP server（harness 的 --mcp-config 指过来）
    if '--mcp-ask' in sys.argv:
        _run_mcp_ask_mode()
        return
    # --mcp-vision 模式：识图 MCP server（4_5v_mcp，analyze_image）
    if '--mcp-vision' in sys.argv:
        _run_mcp_vision_mode()
        return
    # --audit-hook 模式：light 形态直改轻审线 PreToolUse 事中闸（见
    # harness.audit_hook）。必须在单实例锁之前返回——hook 是主实例派生
    # 的短命子进程（每次直改类工具调用起一个），不该去抢主实例的 mutex。
    if '--audit-hook' in sys.argv:
        _run_audit_hook_mode()
        return
    # --snip-grab 模式：截图子进程（v2.3.12 内置截图）。独立进程开 DPI 感知后
    # ImageGrab 全屏——主进程不动 DPI 设置（动了主窗尺寸回归），详见 src/snip.py
    if '--snip-grab' in sys.argv:
        from src import snip
        snip._dpi_aware()
        snip._grab_only()
        return
    # --mcp 模式：作为 MCP stdio server 运行（集成进 exe，无需单独 python 脚本）。
    # PyInstaller --windowed(console=False) 下 sys.stdin/stdout 可能为 None，
    # 但被 subprocess pipe 启动时 fd 0/1 存在，用 open(fd) 重新包装。
    if '--mcp' in sys.argv:
        _run_mcp_mode()
        return
    # P4（2026-11-22，用户拍板）：Electron 壳是唯一入口——单实例锁 /
    # 文件关联 / 窗口语义全部归壳（requestSingleInstanceLock）。调试包 exe
    # 零参数直启已在上方 _setup_job_object() 前自动拉壳；走到这里的只剩
    # 源码直启 / 正包后端裸跑 / 调试包壳缺失——报指引退出，不起无 UI 后端。
    _headless = "--headless" in sys.argv
    if not _headless:
        _msg = ("本版本只支持 Electron 壳启动：请运行 run.bat（源码目录）或"
                "安装后的「前端控制台」快捷方式；调试包直接双击 前端控制台.exe"
                "——若见此框，说明 electron-shell 壳目录缺失：请确保 "
                "前端控制台_debug 目录完整（electron-shell\\ 与 ico\\ 在 exe "
                "同级或其上一级均可），也不要在压缩包里直接双击。")
        print("[错误] " + _msg, file=sys.stderr)
        _dbg_log("直启指引退出（无 --headless）")
        _dbg_msgbox(_msg)
        sys.exit(2)   # 非零退出码：脚本/CI 排障据此区分「形态错误」

    # 延迟导入，避免单实例检查失败时也加载重依赖
    # ---- 首次启动依赖自检（源码分发场景）----
    # 缺 pip 库时弹引导窗自动安装（同款 UI + 进度动画），装完 execv 重启进程。
    # exe 分发时全部库已打进 exe，自检恒通过、零开销（import 探测 <50ms）。
    from src.deps_bootstrap import bootstrap_if_needed, selftest_once
    _boot_mark("依赖自检 开始")
    if not bootstrap_if_needed():
        return
    _boot_mark("依赖自检 完成")
    # 并行预导入：server 模块（Flask+serial）在这里就起子线程加载。实测
    # 启动打点：Flask 就绪段 1811ms 中大头是冷态 import src.server。
    # 依赖自检已通过 → import 不会因缺库失败（缺库会在 bootstrap 阶段
    # 装完并 execv 重启，轮不到这里）。
    _server_ready = threading.Event()
    _server_mod = {}

    def _preload_server():
        try:
            from src.server import app, start_background
            _server_mod["app"] = app
            _server_mod["start_background"] = start_background
        except Exception as e:
            _server_mod["err"] = e
        finally:
            _server_ready.set()

    threading.Thread(target=_preload_server, daemon=True,
                     name="server-preload").start()
    # ---- --headless：Electron 壳形态（换壳迁移 P0）----
    # 壳负责单实例锁/窗口/树杀；本进程只起服务链（Flask/SSE/串口/SSH/终端/
    # harness worker）。2026-11-22 P4 起旧 pywebview 窗体链已整体删除——
    # 本文件不再 import webview/pythonnet，也不碰 WebView2/.NET。
    if _headless:
        # QQ/微信同款窗口识别（/api/snip/hittest）需要物理坐标——Win32
        # 坐标 API 在非 DPI 感知进程里全部虚拟化，125% 缩放下与覆盖窗的
        # 物理底图错位。headless 后端**没有任何窗口**，进程级 DPI 感知零
        # 副作用。注意：旧 pywebview 形态主进程有窗、不能设（会改窗体尺
        # 寸——历史回归点，勿再踩）；本形态无窗链路才安全。
        try:
            from src import snip as _snip_dpi
            _snip_dpi._dpi_aware()
        except Exception:
            pass
        _deps_missing = selftest_once()
        _boot_mark("selftest_once 完成")
        _server_ready.wait(timeout=10)
        if "err" in _server_mod:
            raise _server_mod["err"]
        if "app" not in _server_mod:
            # 预导入超时兜底
            from src.server import app as _app, start_background as _sb
            _server_mod["app"] = _app
            _server_mod["start_background"] = _sb
        app = _server_mod["app"]
        start_background = _server_mod["start_background"]
        start_background()
        # 壳形态旗标（index 注入 __HG_HEADLESS__='1'，win-controls.js 据此
        # 停掉窗控路由族调用——headless 无这些路由，只剩 404/405 日志噪音）
        from src import server as _srv_headless
        _srv_headless.HEADLESS_FORM = True

        # 壳「真退出」通道（P2：托盘退出 / ✕ 直退路径）：优雅清理后自灭。
        # 秒回 200、清理在后台线程跑（壳有界等 4s 后树杀兜底）——只做后端
        # 侧资源收口（窗口/托盘归壳，不在此列）
        @app.route("/api/quit", methods=["POST"])
        def _api_shell_quit():
            def _quit_chain():
                _exit_reason("shell_quit")
                try:
                    from src.server import close_all_ports
                    close_all_ports()
                except Exception:
                    pass
                clear_endpoint()
                try:
                    from src import worker_app
                    worker_app.manage_stop()
                except Exception:
                    pass
                os._exit(0)   # Job Object 内核级收割余下子进程
            threading.Thread(target=_quit_chain, daemon=True,
                             name="shell-quit").start()
            return '{"ok": true}', 200, {"Content-Type": "application/json"}
        # 空闲端口起 Flask（同款探活节奏）。窗口控制路由族（/api/window/*
        # 等）不注册——那是壳 IPC 的领地（P2），main._win 恒 None。
        import socket
        _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _s.bind(("127.0.0.1", 0))
        port = _s.getsockname()[1]
        _s.close()
        threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, threaded=True,
                                   debug=False, use_reloader=False),
            daemon=True).start()
        import urllib.request
        _ready = False
        for _ in range(100):
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/status" % port, timeout=0.5)
                _ready = True
                break
            except Exception:
                time.sleep(0.05)
        if not _ready:
            print("[错误] headless 后端未能在端口 %d 就绪（端口占用/Flask "
                  "异常），进程退出" % port, file=sys.stderr)
            return
        write_endpoint(port)
        _boot_mark("Flask 就绪")
        # harness 链：worker 进程隔离照常（失败不阻塞，307/503 兜底不变）
        try:
            from src import worker_app
            _boot_mark("worker 拉起 开始")
            worker_app.manage_start(main_port=port)
            _boot_mark("worker 拉起已派发（后台握手）")
        except Exception as _we:
            print("[警告] Claude worker 拉起失败: %s" % _we, file=sys.stderr)
        # 全局截图热键：ctypes RegisterHotKey，不依赖窗口；触发起独立 DPI
        # 抓屏子进程（Job Object 收编，壳树杀覆盖）。port 直接闭包更稳。
        try:
            from src.app_state import CONFIG_FILE
            with open(CONFIG_FILE, encoding="utf-8-sig") as _f:
                _snip_hk = (json.load(_f).get("snip_hotkey") or "ctrl+alt+a")
        except Exception:
            _snip_hk = "ctrl+alt+a"

        def _on_snip_hotkey_hd():
            from src import snip as _snip_h
            _snip_h.launch_window(port)
        try:
            from src import snip as _snip_hm
            _snip_hm.start_hotkey(_snip_hk, _on_snip_hotkey_hd)
        except Exception:
            pass   # 热键被占用等：静默（📷 按钮仍可用）
        # 自依赖自检结果给前端（/api/deps_status 弹提醒）
        try:
            _ok, _mr, _mo, _skipped = _deps_missing
            from src import server as _srv
            if hasattr(_srv, "set_deps_missing"):
                _srv.set_deps_missing(_mr, _mo, _skipped)
        except Exception:
            pass
        # 升级分发服务（config 开着才起，发布机形态）
        try:
            import json as _json2
            from src.app_state import CONFIG_FILE
            with open(CONFIG_FILE, encoding="utf-8-sig") as _f:
                if (_json2.load(_f) or {}).get("update_server_enabled"):
                    from src import update_server
                    update_server.start()
        except Exception:
            pass
        try:
            from src import backend_log as _bl
            _bl.log("main", "[headless] 服务就绪 port=%d pid=%d（Electron "
                    "壳形态，无窗口；退出由壳树杀 + Job Object 内核兜底）"
                    % (port, os.getpid()), "info")
        except Exception:
            pass
        # 壳孤儿兜底：壳被强杀（崩溃/taskkill /F）时 will-quit 不会跑，
        # 树杀丢失 → 后端变孤儿常驻。轮询壳进程句柄，壳亡即硬退（Job
        # Object 内核级收割 worker 等全部子进程；worker 侧本就有同款
        # 父进程探活自杀，此处对齐）。--headless 只被壳拉起，跟随壳退出
        # 即正确语义。
        # 盯 FC_SHELL_PID（壳 spawn 时注入）：中间隔 launcher shim
        #（如 WindowsApps 商店 python 别名——壳 spawn 的是 shim，真后端
        # 是孙进程）时 os.getppid() 指向 shim，壳死了 shim 不死、探活失效
        #（实测实锤）。env 缺失再回落直接父进程
        _ppid = int(os.environ.get("FC_SHELL_PID") or 0) or os.getppid()
        def _parent_watch():
            import ctypes as _ct
            _k32 = _ct.windll.kernel32
            while True:
                # PROCESS_QUERY_LIMITED_INFORMATION；父已亡 → NULL → 退
                _h = _k32.OpenProcess(0x1000, 0, _ppid)
                if not _h:
                    _exit_reason("shell_gone")
                    os._exit(0)
                _k32.CloseHandle(_h)
                time.sleep(2.0)
        threading.Thread(target=_parent_watch, daemon=True,
                         name="parent-watch").start()
        # 主线程挂起（等价旧 webview.start 的常驻语义）。daemon 线程随进程走；
        # 壳退出 → taskkill /T 树杀本进程 → Job Object 自动终结全部子进程
        #（worker 等，内核级，强杀也覆盖）
        threading.Event().wait()
        return


def _selftest():
    """--selftest 打包自检（v2.3.8）：验证解密+全依赖 import 链，写
    dist/selftest_result.txt 后退出——**不碰单实例锁、不起任何窗口**，
    开发版运行时也能测发布包。打包.bat 末尾自动调用，异常在打包期暴露，
    不再让用户当端到端测试员。"""
    import io, traceback
    out = io.StringIO()
    ok = True
    res_path = os.path.join(os.path.dirname(sys.executable), "selftest_result.txt")
    def _flush(final=None):
        try:
            with open(res_path, "w", encoding="utf-8") as f:
                f.write("selftest %s\n" % (final or ("RUN" if ok else "PART")) +
                        "argv=%r\n" % (sys.argv,) + out.getvalue())
        except OSError:
            pass
    def _t(label, fn):
        nonlocal ok
        try:
            fn()
            print(f"  ✓ {label}", file=out)
        except Exception as e:
            ok = False
            print(f"  ✗ {label}: {type(e).__name__}: {str(e)[:160]}", file=out)
            print(traceback.format_exc()[-400:], file=out)
        _flush()
    print("FC_MEM_WEB 条数: %d" % len(getattr(sys, "FC_MEM_WEB", {}) or {}), file=out)
    def _imp(name):
        import importlib
        importlib.import_module(name)
    for mod in ("src.version", "src.app_state", "src.server", "src.serial_conn",
                "src.tftp", "flask", "serial",
                "serial.tools.list_ports", "websocket",
                "Crypto.Cipher.AES", "Crypto.Cipher.PKCS1_v1_5",
                "Crypto.PublicKey.RSA", "PIL.Image"):
        _t("import " + mod, lambda n=mod: _imp(n))
    # v3.5.250b：debug 包（打包_debug.bat，HG_NO_ENCRYPT=1）无 .fcenc 清单=
    # web 明文磁盘 serve（[debug-web] 直读 _internal/web），FC_MEM_WEB 恒空
    # 是预期——改抽查磁盘 web 存在性；加密包维持内存 serve 抽查
    # v3.5.267（全审）：三态判据（.fcdebug 哨兵区分 debug 与「正包加密失败
    # 态」——后者两无应 FAIL，此前会误走明文分支放过发布链自检）
    _fc_int = os.path.join(os.path.dirname(sys.executable), "_internal")
    if os.path.isfile(os.path.join(_fc_int, ".fcenc")):
        _t("web 内存 serve 抽查", lambda: (
            None if getattr(sys, "FC_MEM_WEB", {}) else (_ for _ in ()).throw(AssertionError("内存字典为空")),
            list(getattr(sys, "FC_MEM_WEB", {}))[:1]))
    elif os.path.isfile(os.path.join(_fc_int, ".fcdebug")):
        _t("web 明文磁盘 serve 抽查(debug)", lambda: (
            None if os.path.isfile(os.path.join(_fc_int, "web", "index.html"))
            else (_ for _ in ()).throw(AssertionError("_internal/web/index.html 缺失")),
            "plain"))
    else:
        # v3.5.268（复核严重项）：_t 两参签名——标记收回 lambda 元组（对齐
        # debug 分支 "plain" 模式；旧三参写法在目标态 TypeError 崩 selftest）
        _t("资源加密在场", lambda: (
            (_ for _ in ()).throw(AssertionError(
                "非 debug 包但无 .fcenc 加密清单——资源加密失败？（web 处于明文发布态）")),
            "no-fcenc"))
    header = "selftest %s @ %s\n" % ("PASS" if ok else "FAIL", sys.executable)
    out.write("argv=%r\n" % (sys.argv,))
    _flush(final=header.split(" @ ")[0])
    sys.exit(0 if ok else 1)   # 自检完即退，绝不掉进 main()（否则起主界面永不返回）


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    main()
