#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端控制台 v2.2.0 —— 桌面应用入口
- pywebview 渲染前端（系统 WebView2，无需浏览器）
- 内嵌 Flask 后端（多串口管理 + AI 接入层）
- 无控制台黑框：用 pythonw.exe 或 PyInstaller --windowed
- 单实例：二次启动时聚焦已有窗口
"""
import os, sys, threading, json, time
import urllib.request

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

# v2.3.8 argv 诊断落盘（selftest 分支未生效排查；确认后移除）
try:
    with open(os.path.join(os.path.dirname(sys.executable),
                           "argv_debug.txt"), "w", encoding="utf-8") as _f:
        _f.write("argv=%r\nfrozen=%r\nname=%r\n" % (sys.argv, getattr(sys, "frozen", False), __name__))
except OSError:
    pass

# ---- 单实例锁 ----
import ctypes
MUTEX_NAME = "Global\\SerialConsolePro_SingleInstance"
mutex = None

def acquire_single_instance():
    """确保只有一个实例运行。返回 True 表示获锁成功。"""
    global mutex
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    # ERROR_ALREADY_EXISTS = 183
    if ctypes.windll.kernel32.GetLastError() == 183:
        return False
    return True


def resource_path(rel):
    """兼容 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ---- Claude Code 直连入口：endpoint 文件 ----
# 工具启动时把本地 HTTP 服务地址写到固定文件，任何 Claude Code 会话读它即可发现服务。
STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
ENDPOINT_FILE = os.path.join(STATE_DIR, "endpoint.json")

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


def _clean_webview_cache():
    """关闭时清 WebView2 纯缓存（防无限累计——单次打开大文件一条响应就能 37M）。
    只删随时可重建的缓存子树：HTTP Cache / Code Cache / GPU Shader / 组件更新包；
    保留用户状态：Local Storage（灰显偏好 hx_zeroGray 存这里）/ Cookies / IndexedDB。
    删失败静默（下次启动 WebView 自动重建，无数据风险）。"""
    import shutil
    try:
        from src.app_state import DATA_DIR
        eb = os.path.join(DATA_DIR, "webview_cache", "EBWebView")
        if not os.path.isdir(eb):
            return
        # Default 内的纯缓存（不动 Local Storage/Network/Cookies 等小而有用的）
        default = os.path.join(eb, "Default")
        for sub in ("Cache", "Code Cache", "GPUCache", "DawnWebGPUCache", "DawnGraphiteCache"):
            shutil.rmtree(os.path.join(default, sub), ignore_errors=True)
        # EBWebView 顶层的可重建缓存
        for sub in ("GrShaderCache", "ShaderCache", "component_crx_cache", "Subresource Filter"):
            shutil.rmtree(os.path.join(eb, sub), ignore_errors=True)
    except Exception:
        pass


def find_and_focus_existing_window():
    """找到已运行的窗口并置前。pywebview 窗口标题固定。
    不过滤可见性——托盘隐藏的窗口 IsWindowVisible=False，照样枚举到后
    SW_SHOW 唤出（用户：双击快捷方式要打开之前实例，浏览器同款）。"""
    try:
        user32 = ctypes.windll.user32
        # 句柄是 64 位指针，必须显式声明参数/返回类型，否则 ctypes 按 c_int 截断会 OverflowError
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.IsIconic.restype = ctypes.c_bool
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool
        user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.EnumWindows.restype = ctypes.c_bool
        # 前缀匹配而非全名：版本号升级后新进程仍能唤出旧版残留实例
        target = "前端控制台 v"
        found = []
        # 回调签名: BOOL CALLBACK EnumWindowsProc(HWND, LPARAM)，HWND 用 c_void_p 承接 64 位句柄
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, _):
            # 不看可见性：隐藏（托盘）窗口也要找到并唤出
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if target in buf.value:
                    found.append(hwnd)
            return True
        user32.EnumWindows(enum_proc, 0)
        for hwnd in found:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE（最小化）
            else:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW（隐藏态唤出，托盘场景）
            user32.SetForegroundWindow(hwnd)
        return len(found) > 0
    except Exception:
        return False


def _raise_existing_instance():
    """旧实例活着：HTTP 通知它自唤（托盘隐藏态唯一可靠通道），失败再跨进程置前。"""
    try:
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            url = json.load(f).get("url")
        if url:
            req = urllib.request.Request(url + "/api/raise_window",
                                         data=b"", method="POST")
            urllib.request.urlopen(req, timeout=2)
            return
    except Exception:
        pass
    find_and_focus_existing_window()


def _old_instance_alive():
    """检测旧实例是否真的活着：读 endpoint.json 并探活 HTTP 服务。
    返回 True 表示旧实例正常响应；False 表示旧实例已死（mutex 可能是残留）。"""
    try:
        if not os.path.isfile(ENDPOINT_FILE):
            return False
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            ep = json.load(f)
        url = ep.get("url")
        if not url:
            return False
        urllib.request.urlopen(url + "/api/status", timeout=1.5)
        return True
    except Exception:
        return False


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
    # 延迟 import，避免 GUI 模式加载 mcp_server 的依赖
    from src import mcp_server
    mcp_server.main()


def _notify_existing_open_file(path):
    """--open-file 场景已有活实例：聚焦其窗口并 HTTP 通知打开该文件。
    通知走 /api/ai/open_file（旧实例广播 SSE ui_action → 前端 openFileSmart）。
    同时让旧实例窗口最大化（用户需求：双击关联文件=全屏看文件，热路径同权）。
    失败静默（窗口已聚焦，用户可手动拖入）。"""
    if not _old_instance_alive():
        return
    # 不单独调 /api/raise_window：它与 maximize 各起各的 daemon 线程，并发下
    # maximize 先完成、raise 的 restore 后执行会把最大化窗口还原成普通尺寸
    # （用户实锤「双击打开还是窗口的」）。/api/window/maximize 内部已含
    # show+restore+focus，唤出（含托盘隐藏态）+最大化一个线程顺序完成。
    try:
        ep_path = os.path.join(os.path.expanduser("~"), ".serialconsole_pro", "endpoint.json")
        with open(ep_path, "r", encoding="utf-8") as f:
            url = json.load(f).get("url")
        try:
            req = urllib.request.Request(url + "/api/window/maximize", data=b"{}", method="POST")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
        req = urllib.request.Request(
            url + "/api/ai/open_file",
            data=json.dumps({"path": path}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


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


def main():
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
    # --snip-window <port> 模式：独立全屏截图窗子进程（最终形态——窗=物理
    # 屏幕，底图 1:1 不缩进工具窗口；DPI 感知下物理像素直达无虚拟化错位）
    if '--snip-window' in sys.argv:
        from src import snip
        i = sys.argv.index('--snip-window')
        snip.window_main(int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 80,
                         armed='armed' in sys.argv)
        return
    # --mcp 模式：作为 MCP stdio server 运行（集成进 exe，无需单独 python 脚本）。
    # PyInstaller --windowed(console=False) 下 sys.stdin/stdout 可能为 None，
    # 但被 subprocess pipe 启动时 fd 0/1 存在，用 open(fd) 重新包装。
    if '--mcp' in sys.argv:
        _run_mcp_mode()
        return
    # --open-file <path>：文件关联接管后的双击打开入口（file_assoc.py 写的 shell 命令）。
    # 有活实例 → 聚焦其窗口 + HTTP 通知它打开（SSE ui_action 拉起）。
    open_file_path = None
    if '--open-file' in sys.argv:
        i = sys.argv.index('--open-file')
        if i + 1 < len(sys.argv):
            open_file_path = os.path.abspath(sys.argv[i + 1])
    notified_existing = False
    if open_file_path:
        _notify_existing_open_file(open_file_path)
        notified_existing = True
    if not acquire_single_instance():
        # mutex 提示已有实例。先探活旧实例的 HTTP 服务：
        # 若旧实例正常响应，聚焦其窗口后静默退出；
        # 若旧实例已死（进程被强杀但 mutex 残留，或僵尸状态），强制接管——
        # 关闭残留 mutex 句柄，继续启动新实例，避免用户被僵尸实例彻底卡死。
        if _old_instance_alive():
            # 优先 HTTP 通知旧实例自唤（窗口隐藏在托盘时跨进程 ShowWindow
            # 对 pywebview WinForms 宿主不可靠）；失败再跨进程置前兜底。
            # 双击文件场景跳过：上面已通知过（含最大化），这里再 raise 的
            # restore 会把刚做好的最大化还原（用户实锤「双击打开还是窗口的」）。
            if not notified_existing:
                _raise_existing_instance()
            return
        # 旧实例已死，释放残留 mutex 句柄后继续
        global mutex
        if mutex:
            try: ctypes.windll.kernel32.CloseHandle(mutex)
            except Exception: pass
            mutex = None
        # 重新获取一个干净的 mutex
        if not acquire_single_instance():
            # 仍有其他活实例（刚启动的），聚焦后退出
            find_and_focus_existing_window()
            return

    # 延迟导入，避免单实例检查失败时也加载重依赖
    # ---- 首次启动依赖自检（源码分发场景）----
    # 缺 pip 库时弹引导窗自动安装（同款 UI + 进度动画），装完 execv 重启进程。
    # exe 分发时全部库已打进 exe，自检恒通过、零开销（import 探测 <50ms）。
    from src.deps_bootstrap import bootstrap_if_needed, selftest_once
    if not bootstrap_if_needed():
        return
    # 自依赖自检（每机一次）：全通过写标记不再测；有缺失则把清单传给
    # 前端——每次启动都提醒哪些功能不可用，直到用户用离线包补装
    # （exe 分发恒通过，标记写过后零开销）
    _deps_missing = selftest_once()

    # 并行预导入：server 模块（Flask+serial，~600ms）与 webview（~270ms）并行加载，
    # 在主线程 import webview 的同时，子线程预 import server，省 ~270ms 启动时间。
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
    threading.Thread(target=_preload_server, daemon=True).start()

    import webview
    # 优化 WebView2 启动：禁用 file url（我们用 HTTP）省浏览器参数；关默认菜单省 UI 初始化
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = False

    # 等 server 预导入完成（通常 webview 导入完时 server 也差不多好了）
    _server_ready.wait(timeout=10)
    if "err" in _server_mod:
        raise _server_mod["err"]
    if "app" not in _server_mod:
        # 预导入超时（>10s），直接在主线程同步导入兜底，避免 KeyError 卡死启动
        from src.server import app as _app, start_background as _sb
        _server_mod["app"] = _app
        _server_mod["start_background"] = _sb
    app = _server_mod["app"]
    start_background = _server_mod["start_background"]
    # 启动后台线程（日志、清理等）
    start_background()

    # --open-file 热路径：新实例通知旧实例（HTTP）→ 旧实例窗口最大化后打开文件。
    # 注册必须在 app.run 之前——Flask 处理过第一个请求后 setup 方法全部封禁
    # （v2.25 踩坑：注册放 window 创建后被探活请求抢先，启动即 AssertionError）。
    # window 此刻还不存在没关系：处理时运行时取 main._win。
    @app.route("/api/window/maximize", methods=["POST"])
    def _api_window_maximize():
        w = getattr(main, "_win", None)
        if w is not None:
            # WinForms 宿主必须从 GUI 线程操作窗口（_show_main_window 同款）：
            # 路由线程直接调会被静默忽略；且最小化态 maximize 不生效——先 restore
            def _do():
                try:
                    w.show()
                    w.restore()
                    w.maximize()
                    w.focus()
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    # v2.3.12 内置截图全屏路径（第三次恢复，这次配前端视口就绪轮询）：
    # enter=toggle 全屏；exit=toggle 恢复 + maximize 兜底（pywebview 退出
    # 全屏回 Normal 不回之前的最大化态——任务栏消失实锤的根因，显式拉回）。
    @app.route("/api/window/fullscreen", methods=["POST"])
    def _api_window_fullscreen():
        # v3.4.94：补漏 flask request 导入——此前未导入，本路由运行时
        # NameError→500（Cython 静态检查随打包加密实锤）
        from flask import request
        act = (request.get_json(force=True, silent=True) or {}).get("action", "enter")
        w = getattr(main, "_win", None)
        if w is not None:
            def _do():
                try:
                    w.show()
                    w.toggle_fullscreen()
                    if act == "exit":
                        import time as _t
                        _t.sleep(0.15)          # 等全屏退出布局完成再拉最大化
                        w.maximize()
                    w.focus()
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    # v2.3.12 截图全局热键：任意应用前台按键 → 截当时真实屏幕 → 主窗弹前
    # → SSE snip_hotkey → 前端进入截图态。热键键位读 config.json 的
    # snip_hotkey（默认 ctrl+alt+a，空串禁用），注册失败静默（被占用不抢）。
    def _on_snip_hotkey():
        # 最终形态：直接起独立全屏截图窗（DPI 子进程，=物理屏幕 1:1），
        # 主窗不动——工具窗口只是触发器，不参与截图显示
        from src import snip as _snip
        from src.app_state import HOME_DIR
        try:
            with open(os.path.join(HOME_DIR, "endpoint.json"), encoding="utf-8") as f:
                port = int((json.load(f) or {}).get("port") or 0)
        except Exception:
            return
        if port:
            _snip.launch_window(port)

    try:
        from src.app_state import CONFIG_FILE
        with open(CONFIG_FILE, encoding="utf-8") as _f:
            _snip_hk = (json.load(_f).get("snip_hotkey") or "ctrl+alt+a")
    except Exception:
        _snip_hk = "ctrl+alt+a"
    from src import snip as _snip_mod
    _snip_mod.start_hotkey(_snip_hk, _on_snip_hotkey)

    # Flask 用空闲端口，避免冲突
    import socket
    def free_port():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port
    port = free_port()

    flask_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, threaded=True, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()

    # 等待 Flask 就绪（50ms 间隔轮询，Flask 通常 ~600ms 起来，首次命中即返回）
    import urllib.request
    flask_ready = False
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=0.5)
            flask_ready = True
            break
        except Exception:
            time.sleep(0.05)
    if not flask_ready:
        # Flask 5s 未就绪：端口可能被抢占或 app.run 异常退出，不写 endpoint 避免误导 MCP
        print(f"[错误] 后端服务未能在端口 {port} 启动，请检查端口占用后重试。", file=sys.stderr)
        return
    # Flask 已就绪，写 endpoint 供 Claude Code 跨会话发现（写早了 MCP 会探活到未就绪的服务）
    write_endpoint(port)

    # 预热常驻截图窗（延时 10s 拉起，首载 hidden 待命）：第一次热键即 <1s 弹出
    _snip_mod.prewarm(port)
    # 退出时收编孤儿截图窗（它是独立进程不随主进程退；端口下次随机重换，
    # 孤儿窗 reload 旧端口=「无法连接」错误页，用户实锤）。异常崩溃兜底
    # 靠子进程自身 Flask 探活自杀。
    import atexit as _atexit
    _atexit.register(_snip_mod.kill_snip_windows)

    # 单实例唤醒通道：二次启动的进程探活旧实例后调 /api/raise_window 让它自弹。
    # 路由本体在 server.py 注册（Flask 首请求后禁止加路由——之前把 @app.route
    # 放这里，app.run 后探活请求已把 setup 锁死，工具直接打不开，用户实锤）。
    # 这里只注入 show 回调：webview 窗口此刻才存在，闭包捕获。
    def _show_main_window():
        # pywebview WinForms 宿主从自身 GUI 线程操作窗口才稳——包 daemon 线程
        # 里 show/restore/focus，路由线程只负责触发，幂等无副作用。
        def _do():
            try:
                w = webview.windows[0]
                w.show()
                w.restore()
                w.focus()
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()
    from src import server as _srv
    _srv.set_raise_window_callback(_show_main_window)

    # 自依赖自检结果给 server（前端 /api/deps_status 拉取弹提醒）
    try:
        _ok, _mr, _mo, _skipped = _deps_missing
        from src import server as _srv
        if hasattr(_srv, "set_deps_missing"):
            _srv.set_deps_missing(_mr, _mo, _skipped)
    except Exception:
        pass

    # JS API：暴露原生文件选择对话框给前端（拖拽拿不到 File.path 时的 fallback）
    class FileBridge:
        def tray_confirm_hide(self):
            """首次关闭提示框「知道了」后调用：把窗口隐藏到托盘（后端时机控制）。
            在独立线程 hide——pywebview js_api 调用也在 GUI 线程，hide 本身安全。"""
            try:
                webview.windows[0].hide()
            except Exception:
                pass

        def pick_log(self):
            """弹出原生文件选择对话框，返回选中文件的绝对路径或空字符串。"""
            try:
                import webview
                result = webview.windows[0].create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    file_types=('Log Files (*.log;*.txt;*.out)', 'All Files (*.*)'),
                )
                if result:
                    return result[0] if isinstance(result, list) else result
            except Exception as e:
                return ""
            return ""

        def pick_any(self):
            """打开任意文件（编辑器/阅读器智能分发的文件选择）。不限制类型。"""
            try:
                import webview
                result = webview.windows[0].create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    file_types=('All Files (*.*)',),
                )
                if isinstance(result, (list, tuple)):
                    return result[0] if result else ""
                if isinstance(result, str):
                    return result
            except Exception:
                return ""
            return ""

        def pick_two(self):
            """文件对比：弹出原生文件选择对话框，多选两份（A 基准 + B 对比）。
            返回路径列表（前端拿前两个）；取消/选一份返回空列表。"""
            try:
                import webview
                result = webview.windows[0].create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=('All Files (*.*)',),
                )
                if isinstance(result, (list, tuple)):
                    return [p for p in result if p]
                if isinstance(result, str) and result:
                    return [result]
            except Exception:
                return []
            return []

        def pick_dir(self):
            """弹出原生目录选择对话框，返回选中目录的绝对路径或空字符串。
            注意：pywebview 返回的是 tuple（非 list），字符串才是单选时的裸返回——
            三种形态都归一化为 str，前端只拿纯路径。"""
            try:
                import webview
                result = webview.windows[0].create_file_dialog(
                    webview.FOLDER_DIALOG,
                    allow_multiple=False,
                )
                if isinstance(result, (list, tuple)):
                    return result[0] if result else ""
                if isinstance(result, str):
                    return result
            except Exception:
                return ""
            return ""

        def read_clipboard(self):
            """Win32 原生读剪贴板文本。绕开 navigator.clipboard.readText 的
            WebView2 权限弹窗（首次粘贴会弹"允许粘贴吗"），原生读取无弹窗。"""
            try:
                import ctypes
                from ctypes import wintypes
                u32 = ctypes.windll.user32
                k32 = ctypes.windll.kernel32
                CF_UNICODETEXT = 13
                # 64 位下 ctypes 默认 restype 是 32 位 int，句柄会截断成负数/
                # 错值 → GlobalLock 拿 None → 恒空（copy_image_to_clipboard 同款坑，
                # 这里之前漏了显式声明——"剪贴板总是空的"根因）
                u32.GetClipboardData.restype = wintypes.HANDLE
                u32.GetClipboardData.argtypes = [wintypes.UINT]
                if not u32.OpenClipboard(0):
                    return ""
                try:
                    h = u32.GetClipboardData(CF_UNICODETEXT)
                    if not h:
                        return ""
                    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
                    k32.GlobalLock.restype = wintypes.LPVOID
                    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                    ptr = k32.GlobalLock(h)
                    if not ptr:
                        return ""
                    try:
                        return ctypes.wstring_at(ptr)
                    finally:
                        k32.GlobalUnlock(h)
                finally:
                    u32.CloseClipboard()
            except Exception:
                return ""

        def copy_image_to_clipboard(self, path):
            """把图片文件写入系统剪贴板（CF_DIB）。
            供 claude 终端收拖拽图片：claude CLI 输入框不吃文件拖拽、靠剪贴板收图，
            前端拖图到 claude tab 时调这里，再提示用户 Ctrl+V 粘贴。
            Pillow 解码任意格式（png/jpg/webp/…）→ BMP → 去 14B 文件头即 CF_DIB 载荷。"""
            try:
                import ctypes
                from ctypes import wintypes
                from PIL import Image
                import io
                img = Image.open(path)
                # RGBA/调色板一律转 RGBA 再 flatten 到白底 BMP（部分应用不认带 alpha 通道的 DIB）
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1])
                    img = bg
                else:
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="BMP")
                blob = buf.getvalue()
                dib = blob[14:]   # BITMAPFILEHEADER 后 = BITMAPINFO + 像素

                u32 = ctypes.windll.user32
                k32 = ctypes.windll.kernel32
                # 64 位下 ctypes 默认 restype 是 32 位 int，句柄/指针会截断——必须显式声明
                k32.GlobalAlloc.restype = wintypes.HGLOBAL
                k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
                k32.GlobalLock.restype = wintypes.LPVOID
                k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
                k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
                u32.SetClipboardData.restype = wintypes.HANDLE
                u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
                GMEM_MOVEABLE = 0x0002
                CF_DIB = 8
                h = k32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
                if not h:
                    return False
                ptr = k32.GlobalLock(h)
                if not ptr:
                    k32.GlobalFree(h)
                    return False
                try:
                    ctypes.memmove(ptr, dib, len(dib))
                finally:
                    k32.GlobalUnlock(h)
                if not u32.OpenClipboard(0):
                    k32.GlobalFree(h)
                    return False
                try:
                    u32.EmptyClipboard()
                    ok = bool(u32.SetClipboardData(CF_DIB, h))
                    if not ok:
                        k32.GlobalFree(h)
                    return ok
                finally:
                    u32.CloseClipboard()
            except Exception:
                return False

    # pywebview 窗口
    # maximized：--open-file 冷启动直接以最大化开局（原生初始态，不靠回调时机）。
    # 双击关联文件=全屏看文件（用户需求）；普通快捷方式启动维持 1280×820。
    # v3.5.10（用户实锤「标题栏图标还是 Python 图标，风格不统一」）：显式
    # 传窗口图标——源码跑时进程是 python.exe，不传 icon 标题栏/任务栏就
    # 跟 Python 走。打包版 exe 已内嵌同款 ico（build.py --icon），源码/打包
    # 两种形态从此同图标。frozen 下 ico 在 _MEIPASS 资源目录（123 行 base
    # 同款口径），源码在项目根 ico/
    _icon = os.path.join(
        getattr(sys, "_MEIPASS", _ROOT)
        if getattr(sys, "frozen", False) else _ROOT,
        "ico", "app.ico")
    window = webview.create_window(
        title="前端控制台 v%s" % APP_VERSION,
        url=f"http://127.0.0.1:{port}/",
        width=1280,
        height=820,
        min_size=(900, 600),
        maximized=bool(open_file_path),
        text_select=True,
        js_api=FileBridge(),
        icon=_icon if os.path.isfile(_icon) else None,
    )
    main._win = window   # /api/window/maximize 路由用（--open-file 热路径让活实例最大化）

    # 窗口关闭：默认最小化到托盘（config close_to_tray，设置可关）；
    # 托盘「退出」或 close_to_tray=false 才真正退出。
    # closing 事件回调返回 False 即阻止关闭（pywebview Event 语义）。
    # 坑（曾点 ✕ 直接未响应——死锁实锤）：closing 在 GUI 主线程同步执行，
    # 回调里调 window.evaluate_js() 会等 JS 返回，而 JS 求值又需要 GUI 消息循环
    # 处理——消息循环正被 closing 占着 → 死锁。回调里只做判断+返回，
    # 隐藏/建托盘/弹提示全部挪后台线程（window 方法线程安全，内部 marshal）。
    _real_quit = {"flag": False}   # 托盘退出置位后放行下一次 closing
    _prompt_session = {"shown": False}   # 进程内弹过提示（进程生命周期只弹一次）
    # v2.1.0：升级重启要跨模块触发真退出——挂模块级（updater._request_quit 用）
    main._real_quit = _real_quit

    def _do_real_cleanup():
        from src.server import close_all_ports
        close_all_ports()
        clear_endpoint()
        _clean_webview_cache()
        # Claude Proxy 收尾（幂等）：停额度 worker/headroom/重试代理，
        # autoswitched 时回滚 base_url 直连——不回滚 Claude Code 会连不上
        try:
            from src.proxy import proxy_shutdown
            proxy_shutdown()
        except Exception:
            pass   # proxy 模块异常不拖累主工具退出

    def on_closing():
        if _real_quit["flag"]:
            from src.tray import quit_tray
            quit_tray()
            _do_real_cleanup()
            return True   # 放行：真退出
        try:
            from src.app_state import CONFIG_FILE
            import json as _json
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = _json.load(f)
            tray_enabled = cfg.get("close_to_tray", True)
        except Exception:
            tray_enabled = True
        if not tray_enabled:
            _do_real_cleanup()
            return True
        # 关闭到托盘全流程在后台线程做（closing 回调零阻塞）。
        # 弹提示的条件（用户定的节奏）：每次进程活动期间只弹一次——
        #   进程内已弹过（_prompt_session 置位）→ 直接隐藏；
        #   没弹过且 config tray_prompt_shown=false（用户没勾"不再显示"）→ 弹，
        #     用户点「知道了」后置会话标记+隐藏；
        #   勾过"不再显示"→ 永不弹，直接隐藏。
        # 彻底退出后下次启动是全新进程，标记归零——首次关闭又会弹一次。
        import threading
        if not _prompt_session["shown"]:
            try:
                from src.app_state import CONFIG_FILE
                import json as _json
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    _cfg = _json.load(f)
                _prompted = bool(_cfg.get("tray_prompt_shown"))
            except Exception:
                _prompted = False
        else:
            _prompted = True   # 本进程已弹过，本次不再弹
        threading.Thread(target=_hide_async, daemon=True,
                         kwargs={"prompt": not _prompted}).start()
        return False   # 阻止关闭：隐藏时机交给 _hide_async/前端确认

    def _hide_async(prompt):
        import time
        time.sleep(0.05)   # 让 closing 先返回（防重入）
        from src.tray import hide_to_tray
        ok = hide_to_tray(
            window,
            on_quit=lambda: (_real_quit.update(flag=True),
                              _try_destroy(window)),
        )
        if not ok:
            return   # 无托盘环境：closing 已拦但没建起托盘——用户无唤出入口。
                     # 不硬退（数据要保护），下次启动 close_to_tray 建议用户关掉
        if prompt:
            # 首次：窗口留 Visible 弹提示，等前端确认后才隐藏（见 tray_confirm_hide）
            _prompt_session["shown"] = True   # 展示即置位（进程内不再弹）
            try:
                window.evaluate_js("window._trayNotice && window._trayNotice();")
            except Exception:
                pass   # 前端不可达（极端）：直接隐藏兜底，别让窗口关不掉
                try:
                    window.hide()
                except Exception:
                    pass
        else:
            try:
                window.hide()
            except Exception:
                pass

    def _try_destroy(window):
        """托盘「退出」：不 show（show+destroy 会闪窗，用户实锤）。
        直接后台线程清理 + destroy——destroy 对隐藏窗同样走 closing，
        _real_quit 已置位，closing 放行清理链。"""
        def _quit_async():
            import time
            time.sleep(0.05)
            try:
                window.destroy()
            except Exception:
                # 兜底：窗口已死关不掉就硬退（托盘退出必须有出口）
                from src.tray import quit_tray
                quit_tray()
                _do_real_cleanup()
                import os
                os._exit(0)
        import threading
        threading.Thread(target=_quit_async, daemon=True).start()

    window.events.closing += on_closing

    # 窗口加载完成后注册原生拖拽：pywebview 的 WebView2 后端能拿到文件绝对路径
    # （Chromium 标准 File.path 不暴露，但 pywebview 通过 CoreWebView2File.Path 获取，
    #   注入 event.dataTransfer.files[i].pywebviewFullPath）。需用 pywebview DOM API
    #   注册 drop 监听（_dnd_state.num_listeners>0 才捕获路径），回调里 evaluate_js 调前端。
    def on_loaded():
        # 页面加载完成即激活并置前窗口：从托盘/后台/快捷方式启动时窗口可能不在
        # 前台，用户打开工具就是为了敲命令——不等先点一下
        try:
            window.show()
            window.focus()
        except Exception:
            pass
        # --open-file 启动（接管后双击文件、当时无活实例）：窗口就绪后打开该文件
        if open_file_path:
            try:
                window.maximize()   # v2.25：关联打开默认最大化（用户需求：别用默认小窗看文件）
            except Exception:
                pass
            try:
                safe = open_file_path.replace('\\', '/').replace("'", "\\'")
                window.evaluate_js(f"openDroppedFile('{safe}', true);")
            except Exception:
                pass
        def drop_handler(event):
            try:
                files = event.get('dataTransfer', {}).get('files', [])
                for f in files:
                    path = f.get('pywebviewFullPath')
                    if path:
                        # 按类型分发（转义防注入）：文本类后缀 → 编辑器（可编辑写回原路径），
                        # 其余（.log/未知）→ 日志查看器（只读虚拟列表）
                        safe = path.replace('\\', '/').replace("'", "\\'")
                        window.evaluate_js(f"openDroppedFile('{safe}');")
                        break
            except Exception:
                pass
        try:
            window.dom.get_element('body').on('drop', drop_handler)
        except Exception:
            pass

    window.events.loaded += on_loaded

    # debug=False 避免开发工具干扰；生产可开
    # private_mode=False + 固定 storage_path：让 WebView2 复用缓存目录，
    # 避免每次启动新建临时目录导致冷启动（默认 private_mode=True 要 5s+ 初始化）。
    # 缓存也是用户数据：放数据目录（默认 D:\前端控制台\webview_cache），不放 C 盘。
    # 旧版本缓存在 ~/.serialconsole_pro/webview_cache——仅移动目录（同盘 rename O(1)，
    # 跨盘 copy 后删），失败不阻塞（浏览器缓存丢了自动重建）。
    from src.app_state import DATA_DIR, HOME_DIR
    import shutil as _sh
    try:
        new_cache = os.path.join(DATA_DIR, "webview_cache")
        old_cache = os.path.join(HOME_DIR, "webview_cache")
        if os.path.isdir(old_cache) and not os.path.isdir(new_cache):
            os.makedirs(os.path.dirname(new_cache), exist_ok=True)
            try:
                _sh.move(old_cache, new_cache)
            except Exception:
                _sh.copytree(old_cache, new_cache, dirs_exist_ok=True)
                _sh.rmtree(old_cache, ignore_errors=True)
    except Exception:
        pass
    # 启动期按开关拉起升级分发服务（v2.1.0）：发布机 config
    # update_server_enabled=true 时后台起 8765 静态服务（同事升级源）。
    # daemon 线程随主进程走；失败静默（目录没建/端口占用）——设置页
    # 手动开时才把错误亮出来。
    try:
        from src.app_state import CONFIG_FILE
        import json as _json2
        with open(CONFIG_FILE, encoding="utf-8") as _f:
            _cfg = _json2.load(_f)
        if _cfg.get("update_server_enabled"):
            from src import update_server
            update_server.start()
    except Exception:
        pass
    # v3.4.99（用户终裁「93e 的 UA 门禁是严重错误，撤」）：需求本体只有
    # 一条——正常启动没有 F12/右键菜单/F5（这些全挂在 pywebview 的 debug
    # 开关上），而该开关**只认 run_debug.bat**（HARNESS_DEBUG_WEB=1），
    # config 的 webview_debug 不再单独放行。93~98 的浏览器直开门禁（令牌/
    # 挑战/UA 三代）系对需求的误读叠加过度工程，连带 403 过四家内部子进
    # 程，已整体拆除——HTTP 服务恢复仅绑 127.0.0.1 的开放原状。
    from src.server import DEBUG_WEB as _dbg_web
    _wv_debug = _dbg_web
    if _wv_debug:
        os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                              "--remote-debugging-port=9222")
    webview.start(debug=_wv_debug, private_mode=False,
                  storage_path=os.path.join(DATA_DIR, "webview_cache"))


def _selftest():
    """--selftest 打包自检（v2.3.8）：验证解密+全依赖 import 链，写
    dist/selftest_result.txt 后退出——**不碰单实例锁、不起 webview**，
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
    try:
        with open(os.path.join(os.path.dirname(sys.executable), "_selftest_diag.txt"), "w", encoding="utf-8") as _df:
            _df.write("selftest读时 sys.FC_MEM_WEB=%r modules含main=%r\n" % (
                getattr(sys, "FC_MEM_WEB", "MISSING"), "main" in sys.modules))
    except Exception:
        pass
    def _imp(name):
        import importlib
        importlib.import_module(name)
    for mod in ("src.version", "src.app_state", "src.server", "src.serial_conn",
                "src.tftp", "src.tray", "flask", "serial",
                "serial.tools.list_ports", "websocket", "webview",
                "Crypto.Cipher.AES", "Crypto.Cipher.PKCS1_v1_5", "Crypto.PublicKey.RSA", "PIL.Image"):
        _t("import " + mod, lambda n=mod: _imp(n))
    _t("web 内存 serve 抽查", lambda: (
        None if getattr(sys, "FC_MEM_WEB", {}) else (_ for _ in ()).throw(AssertionError("内存字典为空")),
        list(getattr(sys, "FC_MEM_WEB", {}))[:1]))
    header = "selftest %s @ %s\n" % ("PASS" if ok else "FAIL", sys.executable)
    out.write("argv=%r\n" % (sys.argv,))
    _flush(final=header.split(" @ ")[0])
    sys.exit(0 if ok else 1)   # 自检完即退，绝不掉进 main()（否则起主界面永不返回）


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    main()
