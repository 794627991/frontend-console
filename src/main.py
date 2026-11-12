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

# a242（用户实锤「运行中自己重启」取证）：faulthandler 全程挂载——native 层
# 崩溃（C 扩展/WebView2/ctypes）无 Python traceback 直接蒸发进程，此后任何
# 致命信号都会把全线程栈写到 crash_dump.log，现场不再丢失
try:
    import faulthandler as _fh
    _CRASH_LOG = os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
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


def _unhook_webview_intercept():
    """摘除 pywebview 的全 URL WebResourceRequested 拦截（v4.0.0 串口卡顿第一现场）。

    pywebview 6.x 对 '*' 注册 AddWebResourceRequestedFilter(All)：页面每个
    HTTP 请求（含敲键的 /api/send_raw、终端 SSE）都被 WebView2 拦下、编排到
    WinForms UI 线程跑 Python 回调，还逐条枚举 header 转 dict。UI 线程一忙，
    所有请求集体冻结、松手集体放行——用户 trace 实锤：按键 fetch 8ms 发出、
    响应头批量憋 8.8s/20.1s 后同一毫秒放行；串口日志：回显整批迟到 16~43s。
    本工具从不用 request_sent/response_received 事件（全库零订阅），拔掉
    零损失。三重摘除：方法体置空（兜底）+ 注销过滤器（WebView2 不再拦截）
    + 解绑事件（响应回执不再逐条 marshal 上 UI 线程）。
    全程 fail-safe：pywebview 版本差异（类名 EdgeChromium/EdgeChrome 皆有）
    或摘不动时静默放弃，绝不挡启动。"""
    try:
        from webview.platforms import edgechromium as _ec
    except Exception:
        return   # 非 Edge 后端平台：无此拦截器
    try:
        _cls = None
        for _name in ("EdgeChromium", "EdgeChrome"):
            _c = getattr(_ec, _name, None)
            if _c is not None and hasattr(_c, "on_web_resource_request"):
                _cls = _c
                break
        if _cls is None:
            return
        def _noop(self, sender, args):
            return
        _cls.on_web_resource_request = _noop
        _cls.on_web_resource_response = _noop
        _orig_ready = _cls.on_webview_ready
        def _ready_no_intercept(self, sender, args):
            _orig_ready(self, sender, args)
            # P1-3 修复（a116）：`CoreWebView2WebResourceContext` 在装机的
            # pywebview 上不在 webview.platforms.winforms（该类属
            # edgechromium / Microsoft.Web.WebView2.Core），旧 import 抛
            # ImportError 被下方 except 吞掉 → RemoveWebResourceRequestedFilter
            # 与事件解绑都没执行，'*' 过滤器仍注册，页面每请求照样编到
            # WinForms UI 线程（a93 宣称的「串口请求直连」不成立）。
            # 按可用性逐级取符号，并改用枚举的 All 值兜底。
            _ctx_all = None
            for _imp in (
                    lambda: __import__(
                        "webview.platforms.edgechromium", fromlist=["x"]
                    ).CoreWebView2WebResourceContext,
                    lambda: __import__(
                        "Microsoft.Web.WebView2.Core",
                        fromlist=["x"]).CoreWebView2WebResourceContext,
                    lambda: __import__(
                        "webview.platforms.winforms", fromlist=["x"]
                    ).CoreWebView2WebResourceContext):
                try:
                    _ctx_all = _imp().All
                    break
                except Exception:
                    continue
            cwv = sender.CoreWebView2
            # MINOR-5 修正（a116 二次全审）：兜底值原为 0x7FFFFFFF，但
            # CoreWebView2WebResourceContext.All 的实测值是 **0**，用
            # 0x7FFFFFFF 永远匹配不上 → 静默退化为「不摘除」。兜底改 0。
            cwv.RemoveWebResourceRequestedFilter(
                "*", _ctx_all if _ctx_all is not None else 0)
            cwv.WebResourceRequested -= self.on_web_resource_request
            cwv.WebResourceResponseReceived -= self.on_web_resource_response
        _cls.on_webview_ready = _ready_no_intercept
    except Exception:
        import traceback
        traceback.print_exc()   # 摘除失败必须可见（串口请求仍会过 UI 线程）


# ---- WebView2 运行时启动闸（v2.3.7a 用户需求「任何机器都能兼容，宁可包体大」） ----
# 背景：工具用系统 WebView2（pywebview，不内置浏览器内核），离线/久未更新
# 机器上运行时缺失或过旧 → 前端（较新 CSS/JS）半渲染半崩——用户实测同事
# 机界面裁剪破损。方案：随包带 Fixed Version 运行时（runtime/WebView2Fixed/，
# 微软签名校验过的官方构件），启动时注册表探测系统 Evergreen 版本：
#   系统 ≥ 最低线 → 用系统（保持 Evergreen 自动更新语义）
#   缺失/过旧     → 切内置 Fixed Version（零安装零管理员，环境变量
#                   WEBVIEW2_BROWSER_EXECUTABLE_FOLDER，WebView2 官方加载序）
#   都没有        → 打印明确指引（此时窗口必然建不起来）
_WV2_MIN = (109, 0, 1518, 0)   # ES2022/:has/content-visibility 全覆盖的最低线
_WV2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"   # EdgeUpdate Clients 的 WebView2 Runtime


def _wv2_system_version():
    """注册表探测系统 Evergreen WebView2 运行时版本（pv），无则空串。
    HKLM/HKCU × 32/64 位视图全扫——运行时可能装在任一组合位。"""
    try:
        import winreg
    except ImportError:
        return ""
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for wow in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(
                        root,
                        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\\" + _WV2_GUID,
                        0, winreg.KEY_READ | wow) as k:
                    pv, _t = winreg.QueryValueEx(k, "pv")
                    return str(pv or "")
            except OSError:
                continue
    return ""


def _wv2_ver_tuple(pv):
    try:
        return tuple(int(x) for x in str(pv).split(".") if x.isdigit())
    except Exception:
        return ()


def _wv2_fixed_dir():
    """内置/解包出的 Fixed Version 运行时目录（含 msedgewebview2.exe 那层）。

    v4.1（用户拍板）：运行时改由离线资源包解到 <app>/offline_runtime/webview2/，
    探测顺序必须先查它再查老的 runtime/——升级早期两处并存时否则会用旧版。
    深度 1..5（offline_runtime/webview2/<ver>/…/msedgewebview2.exe）。
    """
    from src.res_boot import wv2_fixed_dir as _find
    return _find()


def _ensure_webview2():
    """webview.start 之前调用（WebView2 环境变量只在创建期读取）。"""
    if os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"):
        print("[webview2] 环境变量已指定运行时，尊重不覆盖")
        return
    pv = _wv2_system_version()
    vt = _wv2_ver_tuple(pv) if pv else ()
    if vt and vt >= _WV2_MIN:
        print("[webview2] 系统 Evergreen %s ≥ %s，用系统运行时"
              % (pv, ".".join(map(str, _WV2_MIN))))
        return
    fixed = _wv2_fixed_dir()
    if fixed:
        os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = fixed
        print("[webview2] 系统%s → 切内置 Fixed Version：%s"
              % ("缺失" if not vt else "过旧(%s)" % pv, fixed))
        return
    if vt:
        print("[webview2] ⚠ 系统 %s 低于 %s 且无内置运行时——继续用系统，"
              "新版前端可能渲染异常" % (pv, ".".join(map(str, _WV2_MIN))))
    else:
        # v4.1：运行时改由离线资源包解到 offline_runtime/webview2/。
        # 闸门（res_boot.preflight_gate）正常已拦住此路；走到这里是旁路
        # 启动（--no-claude-worker 等）或闸门异常放行——弹原生提示并继续，
        # 窗口大概率建不出来，至少给用户看得懂的原因。
        print("[webview2] ⚠ 系统无 WebView2 运行时且离线资源包未安装"
              "（offline_runtime/webview2/）——窗口将无法创建；"
              "请用工具目录下的 .fcpk 资源包安装")
        try:
            from src.res_ui import msgbox, MB_OK, MB_ICONERROR
            msgbox("系统缺少 WebView2 运行时，且未安装离线资源包。\n\n"
                   "请重新启动工具，按提示选择 .fcpk 资源包安装。",
                   "前端控制台", MB_OK | MB_ICONERROR)
        except Exception:
            pass


# ---- 用户实锤（内网）：退出后主进程残留+rg.exe 占用 ----
# 根因：①子进程（rg/ctags/codegraph）无退出杀链——主进程挂住不退时它们
# 也不退；②主进程本身缺 os._exit 兜底——非 daemon 线程/清理挂起时进程
# 滞留任务管理器。两层根治：Job Object 内核级绑杀 + os._exit(0) 硬退。
_job_handle = None


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
    """显式杀全部子进程（_do_real_cleanup 调——Job Object 是内核兜底，
    这里是退出链的即时清，防 Job Object 设置失败/子进程逃逸）"""
    try:
        import subprocess
        # taskkill /T 树杀：主进程全部子进程+孙进程
        subprocess.run(
            ["taskkill", "/PID", str(os.getpid()), "/T", "/F"],
            capture_output=True, timeout=5,
            creationflags=0x08000000)
    except Exception:
        pass


def main():
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
    # v4.1（用户拍板）：硬资源闸门——必须在 `import webview` 之前。
    # WebView2 缺失/过旧、.NET Framework < 4.8.1 时窗口根本建不出来（后者
    # 连 import webview 都抛异常），所以这里用 Win32 原生对话框引导用户装
    # 离线资源包，装完自动重启；用户取消或安装失败则本进程退出。
    try:
        from src.res_boot import preflight_gate
        if not preflight_gate():
            return
    except Exception as _e:
        # 全审 B3：早前这里是「吞异常放行」，最坏链路是用户选了半截包 →
        # 抛异常 → 放行 → 走到「窗口建不出来」的莫名状态。改为：先自己
        # 复查一遍 WebView2 是否真的可用——能用才放行（闸门故障不该锁死
        # 老机器），不能用就明确告诉用户原因再退出。
        import traceback
        traceback.print_exc()
        try:
            from src.res_boot import probe_webview2, probe_dotnet
            st_wv = probe_webview2()[0]
            st_net = probe_dotnet()[0]
        except Exception:
            st_wv = st_net = "unknown"
        if st_wv == "ok" and st_net in ("ok", "unknown"):
            print("[res_boot] 闸门异常但运行环境可用，继续启动")
        else:
            try:
                from src.res_ui import msgbox, MB_OK, MB_ICONERROR
                msgbox("启动前检查运行环境时出错，且当前环境不满足要求。\n\n"
                       "错误：%r\nWebView2：%s / .NET：%s\n\n"
                       "请重新双击工具，按提示选择 .fcpk 资源包安装。"
                       % (_e, st_wv, st_net),
                       "前端控制台", MB_OK | MB_ICONERROR)
            except Exception:
                pass
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
    # 摘除 pywebview 全 URL 拦截（串口卡顿第一现场，见函数注释）——
    # 必须在 webview.start 之前：拦截器在窗口创建时注册
    _unhook_webview_intercept()
    # 优化 WebView2 启动：禁用 file url（我们用 HTTP）省浏览器参数；关默认菜单省 UI 初始化
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    # a484（用户实锤：网页 tab 内点链接被系统浏览器抢走）：pywebview 对
    # NewWindowRequested 的默认处理是 webbrowser.open（系统浏览器）——
    # 网页 tab 里点 target=_blank 链接全被 Edge 抢走。但它的另一档
    #（OPEN_EXTERNAL_LINKS_IN_BROWSER=False → load_url）会把**主 WebView2
    # 整窗导航走**（工具 UI 被替换，a238 老事故形态）——两档都不能用。
    # 改为 monkey-patch edgechromium 的 on_new_window_request：Handled=True
    # 不开系统窗口，也不动主窗口导航，而是 evaluate_js 把 URL 交给前端
    # __newWindow(url) → web-panel 在网页 tab 内导航（工具内打开）。
    # debug 端口照开（CDP/9222 诊断链需要），但不自动弹 DevTools 窗口
    #（a355：要人工看再 F12/右键检查——自动弹在桌面工具形态纯打扰）
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    # a484（用户实锤：网页 tab 内点链接被 Edge 抢走）：pywebview 对
    # NewWindowRequested 只有两档——webbrowser.open（系统浏览器，现状）或
    # load_url（主窗被导航走=工具 UI 被替换，a238 事故形态），都不能用。
    # 在 start 之前替换 edgechromium 的**类方法**（webview_ready 订阅的是
    # bound method，类方法替换对已完成与未完成的订阅都生效）：Handled=True
    # 不开系统窗口、不动主窗导航，evaluate_js 把 URL 交给前端
    # window.__newWindow → web-panel 在网页 tab 内导航（工具内打开）。
    # URL 经 json 编码防注入；非 http(s)（mailto/下载直链等）按原路放行
    # 系统处理（Handled 不置位则 WebView2 默认弹系统浏览器，语义正确）。
    try:
        from webview.platforms.edgechromium import EdgeChrome as _EC
        def _on_new_window(self, sender, args):
            # 审计实锤（卡死根因）：本处理器跑在 UI 线程，pywebview 的
            # evaluate_js 内部 Semaphore.acquire 等 UI 线程回调——事件未
            # 返回即死锁。改用 ExecuteScriptAsync fire-and-forget：发起即
            # 返回、不等待结果，前端 __newWindow 自行消化 URL。
            # a487（复审）：①sender 即 CoreWebView2（NewWindowRequested
            # 定义在它上面）——直接用，不再绕 self.webview.CoreWebView2；
            # ②原版 `from System import Func, Object, String` 是死导入且
            # 若 System 命名空间加载失败会让已 Handled 的链接静默吞掉
            # （不开窗也不导航）——删掉。
            try:
                _u = str(args.get_Uri() or "")
                if _u.startswith(("http://", "https://")):
                    args.set_Handled(True)
                    sender.ExecuteScriptAsync(
                        "window.__newWindow && window.__newWindow(%s);"
                        % json.dumps(_u))
            except Exception:
                pass  # 异常时 Handled 可能已置——链接吞掉比开系统浏览器安全
        _EC.on_new_window_request = _on_new_window

        # a489（用户实锤：右键三修仍不生效）：弃 on_loaded 里的 _find_core
        # 递归搜索（对象树结构在 pywebview 版本间不保证）。改为包装
        # on_webview_ready——原方法自己就在操作 sender.CoreWebView2.Settings，
        # 跑完后紧跟一行覆盖 AreDefaultContextMenusEnabled=True，必然生效。
        # 非 debug 时 pywebview 设 False，我们紧跟改 True；debug 时本来就
        # 是 True，覆盖为同值无副作用。前端 web-panel.js 捕获阶段把
        # .web-body 以外的区域 preventDefault，各界面右键行为不变。
        _orig_ready = _EC.on_webview_ready
        def _patched_ready(self, sender, args):
            _orig_ready(self, sender, args)
            try:
                sender.CoreWebView2.Settings.AreDefaultContextMenusEnabled = True
            except Exception:
                pass
        _EC.on_webview_ready = _patched_ready
    except Exception:
        pass  # 平台非 edgechromium（非 Windows）无此模块——跳过

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

    # Claude 子系统 worker：进程隔离（harness/hiklink 重负载移驻独立进程，
    # 见 src/worker_app.py 模块注释）。失败不阻塞主工具（Claude 面板不可用，
    # 串口终端不受影响）；崩溃由 worker 侧 supervisor 自动重启
    # main_port（a117）：主页面真实来源随拉起注入 worker CORS 白名单——
    # 端口动态随机，worker 侧硬编码必拦（用户实锤「重启后全挂/会话空」）
    try:
        from src import worker_app
        worker_app.manage_start(main_port=port)
    except Exception as _we:
        print(f"[警告] Claude worker 拉起失败: {_we}", file=sys.stderr)

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
    # 撤 c0bc5d2 的 icon= 传参（打不开工具的元凶，用户实锤）：pywebview 6.2.1
    # 的 create_window 没有 icon 形参，传了直接 TypeError 进程即死。源码跑时
    # 标题栏/任务栏跟 python.exe 图标走是 pywebview 的能力边界，打包版 exe
    # 内嵌工具 ico 不受影响——除非换 pywebview 或走 Win32 WM_SETICON，否则
    # 此处不能再碰。
    window = webview.create_window(
        title="前端控制台 v%s" % APP_VERSION,
        url=f"http://127.0.0.1:{port}/",
        width=1280,
        height=820,
        min_size=(900, 600),
        maximized=bool(open_file_path),
        text_select=True,
        js_api=FileBridge(),
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
        # Claude worker 回收（幂等）：terminate + 关 stdin；worker 侧另有
        # 父进程探活自杀兜底（主进程被强杀也不留孤儿）
        try:
            from src import worker_app
            worker_app.manage_stop()
        except Exception:
            pass
        # Claude Proxy 收尾（幂等）：停额度 worker/bili 压缩/重试代理，
        # autoswitched 时回滚 base_url 直连——不回滚 Claude Code 会连不上
        # （进程隔离时 proxy 在 worker：manage_stop→/worker_shutdown 已内联
        # proxy_shutdown，主进程模块副本无服务可停，不再调）
        if os.environ.get("CLAUDE_INLINE") == "1":
            try:
                from src.proxy import proxy_shutdown
                proxy_shutdown()
            except Exception:
                pass   # proxy 模块异常不拖累主工具退出
        # CPU 优先还原（a335 的 perf_boost 在 atexit 里有还原，但主进程
        # 挂住时 atexit 不走——这里显式再触发一次）
        try:
            from src.perf_boost import restore_and_exit as _pb_restore
            _pb_restore()
        except Exception:
            pass
        # a382-3：os._exit 跳 atexit——补调三个注册在 atexit 里的清理
        try:
            from src import snip as _snip_kill
            _snip_kill.kill_snip_windows()
        except Exception:
            pass
        try:
            from src.hex_diff import _diff_pool_shutdown
            _diff_pool_shutdown()
        except Exception:
            pass
        try:
            from src import proxy_usage as _pu
            if hasattr(_pu, '_recorder') and _pu._recorder:
                _pu._recorder.flush()
        except Exception:
            pass
        # 用户实锤（内网）终修：全部优雅清理完成后，最后一步杀子进程+硬退
        # ——taskkill /T /F 树杀含自身（进程被 TerminateProcess），所以
        # 必须放在全部清理之**后**（a382-2：原位置在 worker/proxy/perf
        # 之前=自杀后余下清理全被剥夺）。Job Object 是内核级兜底（主进程
        # 任何方式退出都杀子进程），taskkill 是即时清
        try:
            _kill_child_processes()
        except Exception:
            pass
        os._exit(0)

    def _dirty_quit_check(window):
        """真退出前的未保存检查（a239 第5轮A2-P2-5）：dirty tab > 0 时同步
        MessageBox 确认——此前托盘退出对全部脏 tab 静默清零。
        ⚠ 只能在**后台线程**调用：evaluate_js 内部 Invoke 封送回 UI 线程，
        在 closing 回调（UI 线程）里同步调 = 自锁死锁（a242 用户实锤
        「运行中自己重启」的定位：窗口挂死被杀 → MCP 拉起新实例）。
        返回 True=继续退出，False=取消。"""
        dirty = []
        try:
            import json as _json2
            r = window.evaluate_js(
                "JSON.stringify(Object.values(connections)"
                ".filter(c=>c&&c.dirty).map(c=>String((c.meta||{}).label||c.portId)))")
            dirty = _json2.loads(r or "[]")
        except Exception:
            dirty = []   # 探测失败不拦退出（保可用优先）
        if not dirty:
            return True
        try:
            import ctypes
            names = "、".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
            # MB_OKCANCEL | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
            rc = ctypes.windll.user32.MessageBoxW(
                0, "还有 %d 个未保存的文件（%s）。\n\n确定退出将丢弃这些修改。" % (len(dirty), names),
                "前端控制台 · 未保存确认", 0x50041)
            return rc == 1   # IDOK
        except Exception:
            return True

    def _quit_with_check(window):
        """托盘「退出」回调（_hide_async 后台线程执行——evaluate_js 安全）：
        先脏检查，用户确认才置退出标记+销毁窗口。"""
        if not _dirty_quit_check(window):
            return   # 取消：不动标记，窗口保持托盘隐藏态可唤出
        _real_quit.update(flag=True)
        _try_destroy(window)

    def on_closing():
        if _real_quit["flag"]:
            # a242：脏检查已前移到 _quit_with_check（后台线程）——closing 的
            # UI 线程不再做任何 JS 探测（死锁源）。取消退出时这里也不再有
            # JS 调用，直接阻止销毁
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
            # a242（用户实锤「运行中自己重启」定位）：closing 回调跑在 UI 线程，
            # evaluate_js 内部 Invoke 回 UI 线程 = 自锁（窗口挂死被杀 → MCP 拉起
            # 新实例 = 观感「自己重启」）。直退路径不再做 JS 探测（保可用），
            # 脏检查只在托盘退出的后台线程做（_quit_with_check）
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
            on_quit=lambda: _quit_with_check(window),
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
        # a483/a489：右键设置已移至启动段的 on_webview_ready 包装
        #（与 NewWindowRequested patch 同一 try 块，webview.start 之前
        # 安装）——on_loaded 时机太晚且对象树遍历不可靠。
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
                paths = [f.get('pywebviewFullPath') for f in files
                         if f.get('pywebviewFullPath')]
                if not paths:
                    return
                # v3.5.76：计时探针（py 侧收到时刻）+ 多文件全量透传（json 数组
                # 防注入）——旧码 break 只取第一个。前端 openDroppedFiles 分发
                # （harness tab 全收；其余 tab 首文件）
                window.evaluate_js("window.__dragProbe && window.__dragProbe('py-drop');")
                window.evaluate_js('openDroppedFiles(' + json.dumps(paths) + ');')
            except Exception:
                pass
        try:
            _keys_pre = window.evaluate_js(
                "Object.keys((window.pywebview&&window.pywebview._eventHandlers)||{}).join('|')") or ''
            _body_el = window.dom.get_element('body')
            _body_el.on('drop', drop_handler)
            # v3.5.85：拖放快通道（v3.5.84 的阻断版升级为摘除版）。84 用
            # stopImmediatePropagation 截胡，把应用自己的拖放 UI（「松开添加
            # 为对话附件」遮罩的隐藏逻辑）一并拦死=屏障永驻（用户实锤）。
            # 本版不阻断任何事件：①diff 出 .on('drop') 刚注册的 body 监听并
            # removeEventListener 摘除（pywebview 的重序列化路径——DragEvent
            # 整体序列化，domJSON 连 document 子树全属性=整页序列化，大会话
            # 11s 的根因；Python 侧 num_listeners 计数保留，C# FilesDropped
            # 照收路径）②window 捕获快通道照发：additional objects 直送 +
            # 轻量 JSON 事件（仅文件名，nodeId=Element._node_id 权威键）分
            # 发 drop_handler。应用全部拖放 UI/监听正常运行
            _nid = ''
            try:
                _nid = _body_el._node_id or ''
            except Exception:
                _nid = ''
            if _nid:
                window.evaluate_js(
                    "if (!window.__hgFastDrop) { window.__hgFastDrop = 1;"
                    "var _pre = '" + _keys_pre + "'.split('|');"
                    "try { Object.keys(pywebview._eventHandlers || {}).forEach(function(k){"
                    "if (_pre.indexOf(k) < 0)"
                    " try { document.body.removeEventListener('drop', pywebview._eventHandlers[k]); } catch(_){}"
                    "}); } catch(_){}"
                    "window.addEventListener('drop', function(e){"
                    "if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;"
                    "var fs = [];"
                    "for (var i = 0; i < e.dataTransfer.files.length; i++)"
                    " fs.push({name: e.dataTransfer.files[i].name});"
                    "try { chrome.webview.postMessageWithAdditionalObjects('FilesDropped', e.dataTransfer.files); } catch(_){}"
                    "try { chrome.webview.postMessage(['pywebviewEventHandler',"
                    " JSON.stringify({event:{type:'drop', dataTransfer:{files: fs}}, nodeId: '" + _nid + "'}),"
                    " 'eventHandler']); } catch(_){}"
                    "e.preventDefault();"
                    "}, true); }")
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
    # a473（用户令：L3 网页操作必须有）：CDP 端口解除 debug 限定——配置键
    # web_cdp 开启时正常启动也带 --remote-debugging-port（AI 经 devtools_*
    # MCP 工具操作浏览器：内网换组件/报错分析）。端口只绑 127.0.0.1（CDP
    # 固有行为），本机单用户工具可接受；默认关，开启需重启生效。
    # 审计修：**端口与 debug 两布尔分离**——webview.start(debug=) 只认
    # _dbg_web（v3.4.99 用户终裁「正常启动无 F12/右键/F5」，pywebview 的
    # debug=True 会整体打开 DevTools 与右键菜单，不能被 web_cdp 波及）
    _web_cdp_cfg = False
    if not _wv_debug:
        try:
            import json as _json
            from src.app_state import CONFIG_FILE
            with open(CONFIG_FILE, encoding="utf-8") as _f:
                _web_cdp_cfg = bool((_json.load(_f) or {}).get("web_cdp"))
        except Exception:
            _web_cdp_cfg = False
    # 滚动条系列终局复盘：启动参数禁 overlay 特性（f3adc75 超集）已退役——
    # 与 CSS scrollbar-color（踢掉 Fluent 绘制的正解）叠加会把滚动条打成
    # 1~2px 畸形（两机制打架，用户实锤）；单独用它也没能稳定送达命令行
    # （同步时序/loader 行为漂移两轮不稳）。debug 调试端口恢复历史原状
    # a355 全局掉帧实锤治理：用户环境实测页面 rAF 被节流到 7~13fps
    #（135ms/帧；敲字符都卡），DevTools attach 时立刻恢复——WebView2/
    # Chromium 对"非前台/被遮挡窗口"的渲染节流在桌面工具场景是纯伤害
    #（工具窗口常驻但焦点在别处是正常使用形态）。禁三连 + Windows 原生
    # 遮挡判定（CalculateNativeWinOcclusion 误判是 WebView2 已知坑）：
    # 无论窗口前台后台，渲染/定时器一律全速
    _wv_args = ["--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                "--disable-features=CalculateNativeWinOcclusion"]
    if _wv_debug or _web_cdp_cfg:
        _wv_args.append("--remote-debugging-port=9222")
    _prev = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    # R24-3（实锤：同名值型开关被覆盖）：整串子串判断会追加出两个
    # --disable-features → Chromium last-wins → 外部值静默失效。按
    # 开关键去重（外部优先），disable-features 取两边值并集
    _have_keys = {tok.split("=", 1)[0] for tok in _prev.split() if tok.startswith("--")}
    _adds = []
    for a in _wv_args:
        k = a.split("=", 1)[0]
        if k == "--disable-features":
            ext_val = next((tok.split("=", 1)[1] for tok in _prev.split()
                            if tok.startswith("--disable-features=")), "")
            vals = [v for v in (ext_val.split(",") if ext_val else []) + [a.split("=", 1)[1]]
                    if v]
            if ext_val:
                _adds.append("--disable-features=" + ",".join(vals))
                _have_keys.discard(k)   # 外部那份被并集替换：不重复保留
                continue
        if k in _have_keys:
            continue                   # 外部已设同名开关——尊重不覆盖
        _adds.append(a)
        _have_keys.add(k)
    _merged = " ".join([_prev] + _adds).strip()
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = _merged
    _ensure_webview2()   # v2.3.7a：运行时闸——必须在 webview.start 前（创建期读环境变量）
    # a357：CPU 优先提升（config 开着则应用；退出还原电源计划）
    try:
        import atexit
        from src import perf_boost as _pb
        _pb.boot_from_config()
        atexit.register(_pb.restore_and_exit)
    except Exception:
        pass
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
