#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端控制台 v1.1.0 —— 桌面应用入口
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
    """找到已运行的窗口并置前。pywebview 窗口标题固定。"""
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
        target = "前端控制台 v1.1.0"
        found = []
        # 回调签名: BOOL CALLBACK EnumWindowsProc(HWND, LPARAM)，HWND 用 c_void_p 承接 64 位句柄
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, _):
            if user32.IsWindowVisible(hwnd):
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
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return len(found) > 0
    except Exception:
        return False


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
    失败静默（窗口已聚焦，用户可手动拖入）。"""
    if not _old_instance_alive():
        return
    find_and_focus_existing_window()
    try:
        ep_path = os.path.join(os.path.expanduser("~"), ".serialconsole_pro", "endpoint.json")
        with open(ep_path, "r", encoding="utf-8") as f:
            url = json.load(f).get("url")
        req = urllib.request.Request(
            url + "/api/ai/open_file",
            data=json.dumps({"path": path}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def main():
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
    if open_file_path:
        _notify_existing_open_file(open_file_path)
    if not acquire_single_instance():
        # mutex 提示已有实例。先探活旧实例的 HTTP 服务：
        # 若旧实例正常响应，聚焦其窗口后静默退出；
        # 若旧实例已死（进程被强杀但 mutex 残留，或僵尸状态），强制接管——
        # 关闭残留 mutex 句柄，继续启动新实例，避免用户被僵尸实例彻底卡死。
        if _old_instance_alive():
            find_and_focus_existing_window()
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
    window = webview.create_window(
        title="前端控制台 v1.1.0",
        url=f"http://127.0.0.1:{port}/",
        width=1280,
        height=820,
        min_size=(900, 600),
        text_select=True,
        js_api=FileBridge(),
    )

    # 窗口关闭：默认最小化到托盘（config close_to_tray，设置可关）；
    # 托盘「退出」或 close_to_tray=false 才真正退出。
    # closing 事件回调返回 False 即阻止关闭（pywebview Event 语义）。
    # 坑（曾点 ✕ 直接未响应——死锁实锤）：closing 在 GUI 主线程同步执行，
    # 回调里调 window.evaluate_js() 会等 JS 返回，而 JS 求值又需要 GUI 消息循环
    # 处理——消息循环正被 closing 占着 → 死锁。回调里只做判断+返回，
    # 隐藏/建托盘/弹提示全部挪后台线程（window 方法线程安全，内部 marshal）。
    _real_quit = {"flag": False}   # 托盘退出置位后放行下一次 closing
    _prompt_session = {"shown": False}   # 进程内弹过提示（进程生命周期只弹一次）

    def _do_real_cleanup():
        from src.server import close_all_ports
        close_all_ports()
        clear_endpoint()
        _clean_webview_cache()

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
    webview.start(debug=False, private_mode=False,
                  storage_path=os.path.join(DATA_DIR, "webview_cache"))


if __name__ == "__main__":
    main()
