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


# a675（用户定调「非必要不写 IO」）：入口级兜底——模块顶层未捕获异常（如
# a663 漏 import atexit 的 NameError）在 pythonw 下完全无痕，进程直接蒸发。
# 装最小 excepthook：**仅异常时**写 boot_error.log（正常启动零写盘）；
# 下次成功启动由 main() 的提示逻辑读入内存日志并改名 .seen。
def _fatal_hook(et, ev, tb):
    try:
        import time as _t
        import traceback as _tb
        d = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
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


# ---- 无题化窗体 + 自绘窗控（a59x，用户定调参考 zcode 桌面端复刻）----
# 设计照抄 zcode（Electron）Windows 分支：窗控三钮由页面自绘，窗口去原生
# 标题栏但保留缩放边框。Electron frameless 在 Win32 底层正是「WS_THICKFRAME
# 在、WS_CAPTION 摘」的窗——缩放边框/Aero snap/DWM 阴影全保留；拖拽 =
# drag 区命中 HTCAPTION，拖动/双击最大化/贴靠/右键系统菜单全是系统行为。
# WebView2 不认 -webkit-app-region，这里走同构 Win32 路径（SendMessage
# WM_NCLBUTTONDOWN HTCAPTION），交互效果与 zcode 一字不差。

_WS_CAPTION = 0x00C00000
_WS_SYSMENU = 0x00080000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_GWL_STYLE = -16
_GWL_WNDPROC = -4
_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_WM_NCPAINT = 0x0085
# 未文档化 legacy 非客户区绘制消息：激活切换时系统用它们画白色边框——
# NCPAINT 拦不住（Chromium/Electron 自绘 chrome 的经典坑，标准解法=吞掉）
_WM_NCUAHDRAWCAPTION = 0x00AE
_WM_NCUAHDRAWFRAME = 0x00AF
_WM_SYSCOMMAND = 0x0112
_SC_MAXIMIZE = 0xF030
_SC_RESTORE = 0xF120
_HT_CLIENT = 1
# HT* 边缘命中码（winuser.h）：L/R/T/B 及四角组合
_HT_EDGE = {"l": 10, "r": 11, "t": 12, "tl": 13, "tr": 14,
            "b": 15, "bl": 16, "br": 17}

# WndProc 子类化状态（_strip 成功路径设置；回调必须持模块级引用防 GC）。
# 按 hwnd 记录（审计 P2：全局单份 + 幂等守卫在句柄重建场景永久丢子类）
_orig_wndproc = {"fn": None, "hwnd": 0}
# 自管还原 bounds（严重 bug 根修：无题窗 NCCALCSIZE=0 下系统 RestoreBounds
# 不含边框，max↔restore 循环逐次漂移膨胀——实测第一次 restore client 高
# 1622>屏 1540，第二次宽 +18；记录 maximize 前真实 bounds 自管写回）
_fc_restore = {"bounds": None, "pre_min": None, "from_min": False, "from_max": False, "fixing_max": False}
_WNDPROC_CB = None
# 审计 P3：回调每条消息 import ctypes + 重设 argtypes 是千级/秒的纯开销——
# 模块级预声明一次（消息处理高频路径零 import）
_ct_u32 = None
def _wndproc_apis():
    global _ct_u32
    if _ct_u32 is None:
        import ctypes as _ct
        u = _ct.windll.user32
        u.CallWindowProcW.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_uint,
                                      _ct.c_longlong, _ct.c_longlong]
        u.CallWindowProcW.restype = _ct.c_longlong
        u.GetWindowRect.argtypes = [_ct.c_void_p, _ct.POINTER(_tagRECT)]
        u.GetWindowRect.restype = _ct.c_bool
        _ct_u32 = u
    return _ct_u32


def _fc_wndproc(hwnd, msg, wparam, lparam):
    """无题窗的消息过滤器：
    - WM_NCCALCSIZE(wParam=1) 返回 0 → 非客户区清零，客户区占满整窗（黑条
      根除，Electron frameless 同款）。代价：THICKFRAME 的边缘 resize 命中带
      一并被清（用户实测三问题之一「无法调整大小」）——由下方 WM_NCHITTEST
      自管补回（Electron hwnd_message_handler.cc 同款，NCCALCSIZE 全清 +
      NCHITTEST 自算边缘）。
    - WM_NCHITTEST：原过程回 HTCLIENT 且非最大化时，鼠标在窗缘 resize 带
      （SM_CXSIZEFRAME+SM_CXPADDEDBORDER×DPI，约 8px@96dpi）内则返回对应
      HTLEFT/HTTOP/…/HTBOTTOMRIGHT——边缘缩放恢复。
    其余消息原样转发原 WndProc。"""
    if msg == _WM_NCCALCSIZE and wparam:
        return 0
    if msg == _WM_NCPAINT:
        # 激活切换时系统重画非客户区——NCHITTEST 返回 HT* 的边缘带被视作
        # 非客户区，默认绘制涂白（用户实锤「切进程切回来必现白框」）。
        # 跳过系统绘制：带内由 Form.BackColor（主题色）呈现，无缝。
        return 0
    if msg == _WM_SYSCOMMAND:
        sc = wparam & 0xFFF0
        # 审计 P1：原生最大化/还原（Win+方向键/Alt+Space/任务栏）绕过
        # toggle_max 批次——原生 restore 走系统 RestoreBounds 复现漂移
        # （实测首还原高 1622>屏 1540，6 循环 +355px 累积）。
        # 【终局】SC_RESTORE 完全接管：不转发系统（系统的 restore 布局按
        # 「假想有边框」重算 rect=漂移根源），自己 WindowState=Normal +
        # bounds 写回（maximize 前记录 / minimize 前常态跟踪，钳工作区）。
        # 本回调即 GUI 线程，直接操作安全。
        if sc == _SC_MAXIMIZE:
            try:
                f2 = _orig_wndproc.get("win")
                fnat = getattr(f2, "native", None) if f2 is not None else None
                from System.Windows.Forms import FormWindowState as _FS
                if fnat is not None and fnat.WindowState != _FS.Minimized:
                    _fc_restore["bounds"] = fnat.Bounds
            except Exception:
                pass
        elif sc == _SC_RESTORE:
            # 终审 P1-2：不转发、无条件接管——最大化态最小化后还原应回最大化
            # （读 GetWindowPlacement 的 WPF_RESTORETOMAXIMIZED）；rb 兜底=
            # placement.rcNormalPosition（系统记的正确还原矩形）。异常也不落
            # 回转发（系统布局=漂移根源）。
            try:
                f2 = _orig_wndproc.get("win")
                fnat = getattr(f2, "native", None) if f2 is not None else None
                if fnat is not None:
                    import ctypes as _ct
                    from System.Windows.Forms import FormWindowState as _FS
                    from System.Drawing import Rectangle as _Rect
                    from System.Windows.Forms import Screen as _Screen

                    class _WP(ctypes.Structure):
                        _fields_ = [("length", ctypes.c_uint),
                                    ("flags", ctypes.c_uint),
                                    ("showCmd", ctypes.c_uint),
                                    ("ptMin", ctypes.c_long * 2),
                                    ("ptMax", ctypes.c_long * 2),
                                    ("rcNormal", ctypes.c_long * 4)]

                    wp = _WP()
                    wp.length = ctypes.sizeof(_WP)
                    # a635（对抗审计 P1-2）：fnat 已经是 win.native（WinForms
                    # Form），而 _win_hwnd 的契约是「pywebview 窗 → HWND」，
                    # 内部取 win.native —— 再传 Form 进去必然拿到 0（Form 没有
                    # .native）。原来 GetWindowPlacement 恒失败：to_max 恒
                    # False、rcNormal 全 0（兜底还原成 0×0）。直接用 Handle。
                    try:
                        _hwnd_v = int(fnat.Handle.ToInt64())
                    except Exception:
                        _hwnd_v = 0
                    _gp_ok = bool(_hwnd_v) and bool(
                        _ct.windll.user32.GetWindowPlacement(
                            _hwnd_v, ctypes.byref(wp)))
                    to_max = bool(_gp_ok and (wp.flags & 2))   # WPF_RESTORETOMAXIMIZED
                    rb = None
                    if _fc_restore.get("from_max"):
                        # 最大化期间的最小化——还原回最大化（from_max 由
                        # maximized/restored 事件维护）
                        _fc_restore["from_max"] = False
                        fnat.WindowState = _FS.Maximized
                        return 0
                    if fnat.WindowState == _FS.Maximized:
                        rb = _fc_restore["bounds"]
                    else:
                        rb = _fc_restore["pre_min"]
                    if rb is None:
                        # a635：GetWindowPlacement 失败时 rcNormal 全 0，直接
                        # 拿来用会把窗口还原成 0×0（再被下面 clamp 成 200×200）。
                        # 拿不到可信矩形就交回系统默认布局，别硬写垃圾值。
                        _n = wp.rcNormal
                        if _gp_ok and (_n[2] - _n[0]) > 0 and (_n[3] - _n[1]) > 0:
                            rb = _Rect(_n[0], _n[1],
                                       _n[2] - _n[0], _n[3] - _n[1])
                        else:
                            return 0
                    fnat.WindowState = _FS.Maximized if to_max else _FS.Normal
                    if not to_max:
                        wa = _Screen.FromHandle(fnat.Handle).WorkingArea
                        nx = max(wa.Left, min(rb.X, wa.Right - max(rb.Width, 200)))
                        ny = max(wa.Top, min(rb.Y, wa.Bottom - max(rb.Height, 200)))
                        fnat.Bounds = _Rect(nx, ny, min(rb.Width, wa.Width),
                                            min(rb.Height, wa.Height))
                    return 0   # 无条件接管：系统布局=漂移根源，一律不转发
            except Exception:
                return 0   # 接管路径任何异常也不落回系统转发
        # SC_MAXIMIZE / 其它 SC 值继续走转发（最大化 bounds 由
        # MaximizedBounds=workarea 钉住，无漂移）
    if msg == 0x0018 and wparam:   # WM_SHOWWINDOW(TRUE)：还原必发（任务栏
        # 点击/alt-tab/ShowWindow 全走这里——SC 钩不到 ShowWindow 路径）。
        # from_max=「最大化期间被最小化」——还原落地时直接切回 Maximized，
        # 不让系统按「假想有边框」重算 rect（placement.rcNormal 已被
        # MaximizedBounds 动态设置破坏成乱值，实测 (154,1434,974,0)）。
        try:
            if _fc_restore.get("from_max") and not _fc_restore.get("fixing_max"):
                f2 = _orig_wndproc.get("win")
                fnat = getattr(f2, "native", None) if f2 is not None else None
                if fnat is not None:
                    from System.Windows.Forms import FormWindowState as _FS
                    _fc_restore["from_max"] = False
                    _fc_restore["fixing_max"] = True
                    try:
                        fnat.WindowState = _FS.Maximized
                    finally:
                        _fc_restore["fixing_max"] = False
                    return 0
        except Exception:
            pass
    if msg in (_WM_NCUAHDRAWCAPTION, _WM_NCUAHDRAWFRAME):
        # 白框真凶（NCPAINT 拦截无效的用户复现实锤）：未文档化 legacy NC
        # 绘制消息，激活切换必发，画系统色边框盖住主题色带。Electron
        # hwnd_message_handler 同款吞法。
        return 0
    if msg == _WM_NCHITTEST:
        try:
            u = _wndproc_apis()
            r = u.CallWindowProcW(_orig_wndproc["fn"], hwnd, msg, wparam, lparam)
            if r != _HT_CLIENT or not _orig_wndproc.get("win"):
                return r   # 系统已判非客户区（罕见）直接沿用
            # 最大化不可 resize，整窗 HTCLIENT（页面自管交互）
            f = getattr(_orig_wndproc["win"], "native", None)
            from System.Windows.Forms import FormWindowState
            if f is not None and f.WindowState == FormWindowState.Maximized:
                return r
            # 物理屏幕坐标（lparam 打包两 signed short，多屏可为负）
            x = lparam & 0xFFFF
            y = (lparam >> 16) & 0xFFFF
            if x >= 0x8000: x -= 0x10000
            if y >= 0x8000: y -= 0x10000
            rc = _tagRECT()
            if not u.GetWindowRect(hwnd, ctypes.byref(rc)):
                return r
            try:
                dpi = u.GetDpiForWindow(hwnd) or 96
            except Exception:
                dpi = 96
            b = _edge_border_phys_px(_orig_wndproc["win"])   # 与露出带宽一致
            l = x < rc.left + b
            t = y < rc.top + b
            rgt = x >= rc.right - b
            btm = y >= rc.bottom - b
            if l and t:   return _HT_EDGE["tl"]
            if rgt and t: return _HT_EDGE["tr"]
            if l and btm: return _HT_EDGE["bl"]
            if rgt and btm: return _HT_EDGE["br"]
            if l:   return _HT_EDGE["l"]
            if rgt: return _HT_EDGE["r"]
            if t:   return _HT_EDGE["t"]
            if btm: return _HT_EDGE["b"]
            return r
        except Exception:
            try:
                return _wndproc_apis().CallWindowProcW(
                    _orig_wndproc["fn"], hwnd, msg, wparam, lparam)
            except Exception:
                return 0
    try:
        return _wndproc_apis().CallWindowProcW(
            _orig_wndproc["fn"], hwnd, msg, wparam, lparam)
    except Exception:
        return 0


def _subclass_ncclient(win):
    """给主窗挂 _fc_wndproc（GUI 线程内调；按 hwnd 幂等——同 hwnd 已挂跳过，
    换 hwnd（句柄重建）则重挂，旧 proc 随旧窗消亡无需恢复）。"""
    global _WNDPROC_CB
    try:
        import ctypes as _ct
        hwnd = _win_hwnd(win)
        if not hwnd:
            return
        if _orig_wndproc["hwnd"] == hwnd and _WNDPROC_CB is not None:
            return   # 同窗已挂
        _u = _ct.windll.user32
        _u.GetWindowLongPtrW.argtypes = [_ct.c_void_p, _ct.c_int]
        _u.GetWindowLongPtrW.restype = _ct.c_longlong
        _u.SetWindowLongPtrW.argtypes = [_ct.c_void_p, _ct.c_int, _ct.c_longlong]
        _u.SetWindowLongPtrW.restype = _ct.c_longlong
        _orig_wndproc["fn"] = _u.GetWindowLongPtrW(hwnd, _GWL_WNDPROC)
        if not _orig_wndproc["fn"]:
            return   # 审计 P3（存疑项收口）：读到 0 再装子类 = CallWindowProcW(NULL) 吞全部消息
        _orig_wndproc["hwnd"] = hwnd
        _orig_wndproc["win"] = win   # NCHITTEST 判最大化用（GUI 线程读安全）
        _WNDPROC_CB = _ct.WINFUNCTYPE(_ct.c_longlong, _ct.c_void_p, _ct.c_uint,
                                      _ct.c_longlong, _ct.c_longlong)(_fc_wndproc)
        _u.SetWindowLongPtrW(hwnd, _GWL_WNDPROC, _ct.cast(_WNDPROC_CB, _ct.c_void_p).value)
    except Exception:
        _orig_wndproc["fn"] = None   # 失败回原生态：残留黑条但不炸窗


def _main_core_webview(win):
    """取主 UI 的 CoreWebView2（DevTools/刷新需要）。失败返回 None。
    必须从 GUI 线程调用（WinForms 控件跨线程访问会抛）。"""
    try:
        f = getattr(win, "native", None)
        if f is None:
            return None
        for c in f.Controls:
            if getattr(c, "Name", "") == "fc_edge_holder":
                if c.Controls.Count > 0:
                    return c.Controls[0].CoreWebView2
    except Exception:
        pass
    return None


def _win_set_foreground(win):
    """pywebview 6.x 的 window.focus 是 bool 属性不是方法（window.py:134
    self.focus=focus，调用即 TypeError 'bool' object is not callable，托盘
    「显示主窗口」实锤）——置前走 Win32 SetForegroundWindow（最小化先恢复）。"""
    try:
        hwnd = _win_hwnd(win)
        if hwnd:
            import ctypes as _ct
            u = _ct.windll.user32
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, 9)   # SW_RESTORE
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _win_hwnd(win):
    """pywebview 窗 → Win32 HWND（native 即 WinForms Form，见 winforms.py:194）。
    未 shown/已销毁返回 0。"""
    try:
        f = getattr(win, "native", None)
        if f is None:
            return 0
        # pythonnet 的 IntPtr 不支持 int() 直转（实测 TypeError），必须走
        # ToInt64() 方法（pywebview 自身用 ToInt32 同款路径）
        return int(f.Handle.ToInt64())
    except Exception:
        return 0


def _edge_border_phys_px(win):
    """窗缘 resize 命中带宽度（物理 px）= SM_CXSIZEFRAME+SM_CXPADDEDBORDER
    按窗 DPI（GetSystemMetricsForDpi 精确，避免系统 DPI 双重缩放）。
    NCCALCSIZE 清非客户区后此带必须由 WebView2 让位（见 _set_edge_pad）。"""
    try:
        import ctypes as _ct
        hwnd = _win_hwnd(win)
        if not hwnd:
            return 8
        u = _ct.windll.user32
        try:
            dpi = u.GetDpiForWindow(hwnd) or 96
        except Exception:
            dpi = 96
        # 【试金石实验】inset 归零：判定白框与 inset 带的因果关系
        # （命中暂弃；实验完按结论恢复 4px 或重构命中通道）
        return 0
    except Exception:
        return 8


def _invoke_gui(win, fn):
    """GUI 线程封送执行（已在 GUI 线程时 .NET Invoke 同步直执行，无死锁）。"""
    try:
        f = getattr(win, "native", None)
        if f is None:
            return
        from System.Windows.Forms import MethodInvoker
        f.Invoke(MethodInvoker(fn))
    except Exception:
        try:
            fn()
        except Exception:
            pass


# a596/597 教训实锤：pythonnet 的 .NET 对象不能挂 python 属性（setattr
# AttributeError——holder._fc_cur 假挂载实锤），状态存模块级 python 容器
_FC_HOLDER = {"panel": None, "cur": [0], "wv": None}
# a635：上次上报的主题底色（只留内存记账，不落盘——原 theme_color 配置项
# 已无消费方，见 _set_form_bg 注释）
_FC_BG = {"last": ""}


def _set_edge_pad(win, phys_px):
    """WebView2 边缘让位（终版，手动布局）：
    教训链：Form.Padding 对 Dock 子项无效（Form.DisplayRectangle 怪癖）→
    Panel(Dock=Fill)+Padding 仍无效——**Panel 本身也是子控件**，Dock=Fill 照
    样盖满客户区，WM_NCHITTEST 发给 Panel（HTCLIENT），主窗收不到（用户实测
    「染红阶段也不见光标」+ 四边异色框）。启动 3s 内能拽=子窗尚未就位的裸窗
    期。终修：Panel 摘 Dock 手动布局 Location=(b,b) Size=(client-2b)，边缘带
    成为主窗**裸区**（无任何子控件）→ 主窗必收 NCHITTEST → 自管 HT* 命中。
    Form.Resize 持续同步；最大化 inset=0 铺满（MaximizedBounds 已钉 workarea）。
    带内底色=Form.BackColor（页面经 /api/window/bg 上报 --bg-panel 同色，
    与顶栏/侧栏无缝）。"""
    def _do():
        try:
            import clr as _clr
            _clr.AddReference("System.Drawing")
            from System.Drawing import Point, Size
            from System.Windows.Forms import Panel, FormWindowState
            f = getattr(win, "native", None)
            if f is None:
                return
            holder = _FC_HOLDER["panel"]
            wv = _FC_HOLDER["wv"]
            # a635（对抗审计 P0-1）：a630 声称「恢复创建分支」，但查找条件写成
            # `not getattr(c, "Dock", None)` —— .NET 枚举成员 bool() 恒 True
            # （DockStyle.Fill=5 → True），webview 恒找不到 → 这里提前 return
            # → fc_edge_holder 永不创建，白框钩子/Controller 染色/边缘让位
            # 全链死码且静默。改为「名字不是 holder 的那个子控件就是 webview」。
            if wv is None:
                for c in list(f.Controls):
                    if getattr(c, "Name", "") == "fc_edge_holder":
                        holder = c
                    else:
                        wv = wv or c   # pywebview 只加一个子控件（webview）
            if wv is None:
                try:
                    import src.backend_log as _bl
                    _bl.warn("window", "_set_edge_pad：Form 上找不到 webview 子控件"
                             "（Controls=%s），边缘让位/染色链跳过" % (
                                 [getattr(c, "Name", "?") for c in f.Controls],))
                except Exception:
                    pass
                return
            if holder is None:
                holder = Panel()
                holder.Name = "fc_edge_holder"
                f.Controls.Remove(wv)
                holder.Controls.Add(wv)   # wv 已 Dock=Fill——在 Panel 内继续 Fill
                f.Controls.Add(holder)
                _FC_HOLDER["panel"] = holder
                _FC_HOLDER["wv"] = wv

                # 激活切换白框终修：Controller bounds ±1 重提交逼 Chromium 重画
                # 呈现面（zcode attachWindowsWindowRepaint 的 WebView2 等价）；
                # Controller 初始化完成后补染主题色兜底（启动时序缺口）
                import System
                import System.Reflection as _srf
                _BF = _srf.BindingFlags
                def _ctrl():
                    try:
                        fld = wv.GetType().GetField("_coreWebView2Controller",
                              _BF.NonPublic | _BF.Instance)
                        return fld.GetValue(wv) if fld is not None else None
                    except Exception:
                        return None
                def _force_repaint(*_a):
                    try:
                        ctrl = _ctrl()
                        if ctrl is None:
                            return
                        b2 = ctrl.Bounds
                        ctrl.Bounds = System.Drawing.Rectangle(
                            b2.X, b2.Y, b2.Width + 1, b2.Height)
                        ctrl.Bounds = b2
                    except Exception:
                        pass
                def _on_init_done(*_a):
                    try:
                        ctrl = _ctrl()
                        if ctrl is not None:
                            c2 = f.BackColor
                            ctrl.DefaultBackgroundColor = System.Drawing.Color.FromArgb(
                                c2.R, c2.G, c2.B)
                            _force_repaint()
                    except Exception:
                        pass
                def _lay(_s=None, _a=None):
                    try:
                        b = 0 if f.WindowState == FormWindowState.Maximized                             else _FC_HOLDER["cur"][0]
                        w2 = f.ClientSize.Width - 2 * b
                        h2 = f.ClientSize.Height - 2 * b
                        if w2 > 0 and h2 > 0:
                            holder.Location = Point(b, b)
                            holder.Size = Size(w2, h2)
                    except Exception:
                        pass
                try:
                    wv.CoreWebView2InitializationCompleted += _on_init_done
                    f.Activated += _force_repaint
                    f.Resize += _lay
                    _FC_HOLDER["repaint"] = _force_repaint   # 闭包持引用防 GC
                    _FC_HOLDER["init"] = _on_init_done
                    _FC_HOLDER["lay"] = _lay
                except Exception as _e2:
                    try:
                        import src.backend_log as _bl
                        _bl.exception("window", "白框钩子挂载失败（不影响布局主链）：%r" % _e2)
                    except Exception:
                        pass
            _FC_HOLDER["cur"][0] = int(phys_px)
            _FC_HOLDER["lay"]()
        except Exception as _e:
            # 本会话实锤模式：吞点静默失效（edge pad 曾 ImportError 拖拽全失
            # 效无任何日志）——关键路径吞点必须落日志
            try:
                import src.backend_log as _bl
                _bl.exception("window", "_set_edge_pad 失败 phys=%s" % phys_px)
            except Exception:
                pass
    _invoke_gui(win, _do)


def _set_form_bg(win, r, g, b):
    """Form 边缘带底色跟随页面主题（win-controls.js 监听 data-theme 上报）。"""

    def _do():
        try:
            import clr as _clr
            _clr.AddReference("System.Drawing")
            from System.Drawing import Color
            f = getattr(win, "native", None)
            if f is None:
                return
            f.BackColor = Color.FromArgb(int(r), int(g), int(b))
            # a635（对抗审计 P2-3）：这里原来每次主题变化都整份 config 原子写
            # （_load_config + _save_config，含 .bak 滚动），但注释承诺的读取方
            # create_window(background_color=) 已随 A/B 实验停用——全仓零读取
            # 方（grep 只命中这处写）。纯 IO 开销 + 退出路径上的写风险窗口。
            # 保留一行轻量记账（不落盘），供日志面板/排障看上次上报色。
            _FC_BG["last"] = "#%02X%02X%02X" % (int(r), int(g), int(b))
            # WebView2 呈现层白底根修（用户实锤「外圈红中间白」）：包装属性
            # DefaultBackgroundColor 只在 CoreWebView2 创建前有效，运行时设置
            # 被 Controller 忽略——反射取内部 CoreWebView2Controller 直接设
            # Controller.DefaultBackgroundColor（UI 线程，本批次即 GUI 线程）
            try:
                holder = None
                for c in f.Controls:
                    if getattr(c, "Name", "") == "fc_edge_holder":
                        holder = c
                        break
                if holder is not None and holder.Controls.Count > 0:
                    wv = holder.Controls[0]
                    import System.Reflection as _srf
                    _BF = _srf.BindingFlags
                    fld = wv.GetType().GetField("_coreWebView2Controller",
                          _BF.NonPublic | _BF.Instance)
                    ctrl = fld.GetValue(wv) if fld is not None else None
                    if ctrl is None:
                        pr = wv.GetType().GetProperty("CoreWebView2Controller",
                              _BF.NonPublic | _BF.Instance)
                        ctrl = pr.GetValue(wv) if pr is not None else None
                    if ctrl is not None:
                        ctrl.DefaultBackgroundColor = Color.FromArgb(int(r), int(g), int(b))
                    else:
                        wv.DefaultBackgroundColor = Color.FromArgb(int(r), int(g), int(b))
            except Exception:
                pass
            # DWM 窗口边框线染同色：DWMWA_BORDER_COLOR=34（Win11；35 是
            # caption 色——第一版染错了属性，白线残留实锤）
            import ctypes as _ct
            c3 = _ct.c_uint((int(b) << 16) | (int(g) << 8) | int(r))   # 0x00BBGGRR
            for _attr in (34, 35):
                try:
                    _ct.windll.dwmapi.DwmSetWindowAttribute(
                        _win_hwnd(win), _attr, _ct.byref(c3), 4)
                except Exception:
                    pass
        except Exception as _e:
            try:
                import src.backend_log as _bl
                _bl.exception("window", "_set_form_bg 失败（边缘带/白框类回归风险）：%r" % _e)
            except Exception:
                pass
    _invoke_gui(win, _do)


def _pin_maximized_bounds(win):
    """钉最大化 bounds=所在屏工作区（实测实锤：无题窗 WinForms maximize 的
    rect 底部贴到屏幕底而非工作区底——页面底部 55 物理px 被任务栏盖，overhang
    补偿只是遮丑，这个是根修）。MaximizedBounds 设 workarea 后最大化 rect 精确
    等于工作区，overhang 恒 0，CSS 补偿自然空转（机制保留作保险）。GUI 线程调。"""
    try:
        from System.Windows.Forms import Screen
        f = getattr(win, "native", None)
        if f is None:
            return
        f.MaximizedBounds = Screen.FromHandle(f.Handle).WorkingArea
    except Exception:
        pass


def _strip_window_caption(win):
    """摘 WS_CAPTION、保 THICKFRAME/SYSMENU/MinBox/MaxBox。
    必须在 GUI 线程动窗体样式（snip.py:319-328 的 SetWindowPos 被弹回教训），
    本函数任意线程可调：内部 Invoke(MethodInvoker) 封送 GUI 线程同步执行。
    shown/loaded 双挂点幂等重试（shown 偶发不触发/句柄重建场景兜底）。"""
    def _do():
        try:
            import ctypes as _ct
            hwnd = _win_hwnd(win)
            if not hwnd:
                return
            _u = _ct.windll.user32
            # 64 位句柄/返回值必须显式声明，否则按 32 位截断
            # （main.py EnumWindows 同款教训）
            _u.GetWindowLongPtrW.argtypes = [_ct.c_void_p, _ct.c_int]
            _u.GetWindowLongPtrW.restype = _ct.c_longlong
            _u.SetWindowLongPtrW.argtypes = [_ct.c_void_p, _ct.c_int, _ct.c_longlong]
            _u.SetWindowLongPtrW.restype = _ct.c_longlong
            _u.SetWindowPos.argtypes = [_ct.c_void_p, _ct.c_void_p,
                                        _ct.c_int, _ct.c_int, _ct.c_int, _ct.c_int,
                                        _ct.c_uint]
            style = _u.GetWindowLongPtrW(hwnd, _GWL_STYLE)
            if not style:
                return
            style = (int(style) & ~_WS_CAPTION) | _WS_SYSMENU | _WS_THICKFRAME \
                | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX
            _u.SetWindowLongPtrW(hwnd, _GWL_STYLE, style)
            # FRAMECHANGED 让非客户区立即按新样式重算（NOMOVE|NOSIZE|NOZORDER|NOACTIVATE）
            _u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)
            # 非客户区清零（WM_NCCALCSIZE 过滤）：残边在亮色主题露黑条（用户实锤）
            _subclass_ncclient(win)
            # WebView2 边缘让位：Dock=Fill 子窗盖满客户区会吞 WM_NCHITTEST，
            # 主窗自管边缘命中失效（用户实测「无法调整大小」）——Padding 让
            # 子窗缩进 resize 带，露出 Form 区域收 NCHITTEST
            _set_edge_pad(win, _edge_border_phys_px(win))
            # 冷启 maximized（--open-file）路径：pywebview 内部 maximize 不走
            # toggle_max 路由，此处补钉 MaximizedBounds（幂等，非最大化设了
            # 也只在下次 maximize 生效）
            from System.Windows.Forms import FormWindowState as _FS
            f = getattr(win, "native", None)
            if f is not None and f.WindowState == _FS.Maximized:
                _pin_maximized_bounds(win)
        except Exception:
            pass
    try:
        f = getattr(win, "native", None)
        if f is None:
            return
        from System.Windows.Forms import MethodInvoker
        f.Invoke(MethodInvoker(_do))
    except Exception:
        pass


class _tagRECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint),
                ("rcMonitor", _tagRECT), ("rcWork", _tagRECT),
                ("dwFlags", ctypes.c_uint)]


def _maximize_overhang_css_px(win):
    """无题窗（THICKFRAME 在、CAPTION 摘）最大化时窗口矩形越出工作区——
    四边边框被推到屏外，客户区顶部/两侧被裁。实测 window rect vs workarea
    得每侧越界物理 px，÷ DPI 缩放转 CSS px 给页面做 body.is-max 补偿
    （Electron 内部做了这事，我们自理）。非最大化/量不到返回 0。
    纯 user32 调用，任意线程可调（避开 GUI 线程 evaluate_js 死锁坑）。"""
    try:
        import ctypes as _ct
        hwnd = _win_hwnd(win)
        if not hwnd:
            return 0.0
        _u = _ct.windll.user32
        _u.GetWindowRect.argtypes = [_ct.c_void_p, _ct.POINTER(_tagRECT)]
        _u.GetMonitorInfoW.argtypes = [_ct.c_void_p, _ct.POINTER(_MONITORINFO)]
        rc = _tagRECT()
        if not _u.GetWindowRect(hwnd, _ct.byref(rc)):
            return 0.0
        # 最小化守卫（2026-11-18 用户实锤「快速最小化再打开短时间什么都没有」）：
        # 最小化窗口 rect=(-32000,-32000)（Windows 标准坐标），与工作区求差
        # 得 over≈25000 CSS px——页面套上 hg-overhang 四边 25000px padding，
        # 全部内容被推到屏幕外只剩 body 背景。最小化没有「越界补偿」概念，
        # 直接 0（还原后下一次拉取自然回正常值）
        try:
            f2 = getattr(win, "native", None)
            from System.Windows.Forms import FormWindowState as _FS
            if f2 is not None and f2.WindowState == _FS.Minimized:
                return 0.0
        except Exception:
            pass
        mon = _u.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST（审计 P2：1=PRIMARY 副屏补偿错乱）
        if not mon:
            return 0.0
        mi = _MONITORINFO()
        mi.cbSize = _ct.sizeof(_MONITORINFO)
        if not _u.GetMonitorInfoW(mon, _ct.byref(mi)):
            return 0.0
        try:
            dpi = _u.GetDpiForWindow(hwnd) or 96
        except Exception:
            dpi = 96
        scale = float(dpi) / 96.0
        # 对称越界，取上/左其中一个即可（还原态理论为 0，防御性 max(0,…))
        over_top = max(0, mi.rcWork.top - rc.top)
        over_left = max(0, mi.rcWork.left - rc.left)
        over_bottom = max(0, rc.bottom - mi.rcWork.bottom)
        # 四边对称取值（审计 P1：底部不补则页面下缘被任务栏盖 8px）
        return round(max(over_top, over_left, over_bottom) / scale, 1)
    except Exception:
        return 0.0


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


def _patch_pywebview_move():
    """修 pywebview 6.2.1 winforms move() 的 None 实参崩溃（自绘窗控拖拽地基）。

    winforms.py:636-644 的 move() 给 SetWindowPos 传 None 当 hWndInsertAfter/
    cx/cy（指望 ctypes 转 NULL），但无 argtypes 声明时 None 走 int(None)
    → TypeError（用户实锤拖拽静默失效，栈见日志）。自绘标题栏的顶栏拖拽
    （win-controls.js → pywebviewMoveWindow 特例 → 本 move）全靠它。
    本仓库已有摘 pywebview 拦截的先例（_unhook_webview_intercept），同款
    手法：类方法级替换 + 显式 argtypes + fail-safe（patch 不上不挡启动）。"""
    try:
        import ctypes as _ct
        from webview.platforms import winforms as _wf
        def move(self, x, y):
            # 逻辑 px → 物理 px（原实现同式）；SWP_NOSIZE|NOZORDER|SHOWWINDOW
            try:
                u = _ct.windll.user32
                u.SetWindowPos.argtypes = [_ct.c_void_p, _ct.c_void_p,
                                           _ct.c_int, _ct.c_int,
                                           _ct.c_int, _ct.c_int, _ct.c_uint]
                u.SetWindowPos.restype = _ct.c_bool
                scale = getattr(self, "_scale", 1)
                xp = int(x * scale) if scale != 1 else int(x)
                yp = int(y * scale) if scale != 1 else int(y)
                u.SetWindowPos(self.Handle.ToInt64(), None, xp, yp, 0, 0,
                               0x0001 | 0x0004 | 0x0040)
            except Exception:
                pass
        _wf.BrowserView.BrowserForm.move = move
    except Exception:
        pass


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


def _save_file_dialog(default_name):
    """弹原生保存对话框，返回目标绝对路径（取消/失败返回空串）。

    供 /api/backend_log/save 使用（WebView2 里 `<a download>` 被 init.js 的
    全局链接拦截器 preventDefault，且 pywebview 默认 ALLOW_DOWNLOADS=False，
    浏览器下载路径完全走不通）。pywebview 6.x 的 create_file_dialog 可以在
    非 GUI 线程调用（内部 marshal 回 WinForms 线程），失败时抛异常——路由
    拿到空串后退回桌面目录落盘，不会卡死。
    """
    try:
        import webview
        wins = getattr(webview, "windows", None) or []
        if not wins:
            return ""
        result = wins[0].create_file_dialog(
            webview.SAVE_DIALOG, save_filename=default_name,
            file_types=("Text Files (*.txt)", "All Files (*.*)"))
        if isinstance(result, (list, tuple)):
            return result[0] if result else ""
        if isinstance(result, str):
            return result
    except Exception:
        return ""
    return ""


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
        d = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
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
    _boot_mark("===== boot =====")
    # 用户需求（2.4.4）：启动不再弹 cmd 黑框——日志由进程内环形缓冲接管
    # （src/backend_log.py，只驻内存不写盘），界面点标题栏版本号即可查看。
    # 必须在任何 print 之前装（此处之前只有 import，无输出）。子模式
    # （--mcp-ask/--audit-hook 等）是短命子进程且走 stdio 协议，绝不能接管
    # 它们的 stdout/stderr——真实用户看日志只会用主实例。
    if not any(a in sys.argv for a in (
            '--claude-worker', '--mcp-ask', '--mcp-vision', '--audit-hook',
            '--snip-grab', '--snip-window', '--selftest')):
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
        _be = _os.path.join(_os.path.expanduser("~"), ".serialconsole_pro",
                            "boot_error.log")
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
    _boot_mark("依赖自检 开始")
    if not bootstrap_if_needed():
        return
    _boot_mark("依赖自检 完成")
    # 并行预导入：server 模块（Flask+serial）在这里就起子线程加载——与
    # 资源闸门/自检/webview patch 全部并行。实测启动打点：Flask 就绪段
    # 1811ms 中大头是冷态 import src.server，而旧实现把线程建在 import
    # webview 前一刻（只并行了 ~1ms）、随即 wait 等满额 = 白跑。
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
    # v4.1（用户拍板）：硬资源闸门——必须在 `import webview` 之前。
    # WebView2 缺失/过旧、.NET Framework < 4.8.1 时窗口根本建不出来（后者
    # 连 import webview 都抛异常），所以这里用 Win32 原生对话框引导用户装
    # 离线资源包，装完自动重启；用户取消或安装失败则本进程退出。
    try:
        from src.res_boot import preflight_gate
        _boot_mark("资源闸门 开始")
        if not preflight_gate():
            return
        _boot_mark("资源闸门 完成")
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
    _boot_mark("selftest_once 完成")

    import webview
    _boot_mark("import webview 完成")
    # 摘除 pywebview 全 URL 拦截（串口卡顿第一现场，见函数注释）——
    # 必须在 webview.start 之前：拦截器在窗口创建时注册
    _unhook_webview_intercept()
    # 修 move() None 实参崩溃（自绘窗控顶栏拖拽的地基，见函数注释）
    _patch_pywebview_move()
    # 优化 WebView2 启动：禁用 file url（我们用 HTTP）省浏览器参数；关默认菜单省 UI 初始化
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    # 自动弹 DevTools 在桌面工具形态纯打扰（a355 起）——要人工看再 F12
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    # a544 网页 tab 终局形态：网页 tab 是独立的 WebView2 浏览器控件
    #（src/web_tabs.py），主 UI 的 NewWindowRequested 只剩一种来源——
    # 工具 UI 自身的外链（Claude 回复里的 URL 等）→ 前端 __newWindow
    # 在网页 tab 内打开（ca9df59/a484 起的语义，简写保留）。
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    try:
        from webview.platforms.edgechromium import EdgeChrome as _EC

        _orig_ready = _EC.on_webview_ready
        def _patched_ready(self, sender, args):
            _orig_ready(self, sender, args)
            # 外链路由：pywebview 在 OPEN_EXTERNAL=False 档会走
            # self.load_url(url)，包装拦截外部 URL → 前端 __newWindow
            #（ExecuteScriptAsync fire-and-forget——绝不能 evaluate_js
            # 等 UI 线程回调，a484 死锁实锤）
            _orig_load = self.load_url

            def _is_loopback(u):
                # R1 审计 W2（A2）：原「"127.0.0.1" not in _u」子串判定可被
                # http://127.0.0.1.evil.com 绕过（子串命中→误判本机→主 UI
                # 导航到外部页）。改按 urlsplit().hostname 精确判定。
                try:
                    from urllib.parse import urlsplit
                    return (urlsplit(u).hostname or "").lower() in (
                        "127.0.0.1", "localhost", "::1")
                except Exception:
                    return False

            def _safe_load(url, *la, **kw):
                try:
                    _u = str(url or "")
                    if _u.startswith(("http://", "https://")) and not _is_loopback(_u):
                        sender.CoreWebView2.ExecuteScriptAsync(
                            "window.__newWindow && window.__newWindow(%s);"
                            % json.dumps(_u))
                        return
                    # R2 审计 W19（N2）：非 http(s)（file:/data:/about: 等）
                    # 原先直落 _orig_load → 主 UI 内 file: 链接把工具窗口
                    # 整页导航到本地文件。一律吞掉，仅放行 http(s) 回环目标。
                    if not (_u.startswith("http://") or _u.startswith("https://")):
                        return
                except Exception:
                    pass
                return _orig_load(url, *la, **kw)
            self.load_url = _safe_load
            # 右键菜单强制开（a483 用户令；原方法按 debug 开关设）
            try:
                sender.CoreWebView2.Settings.AreDefaultContextMenusEnabled = True
            except Exception:
                pass
            # a624（用户令）：**浏览器级快捷键一律屏蔽**——F5/Ctrl+R 不再
            # 整刷工具，F12/Ctrl+Shift+I 也不再直接开 DevTools。能力改由
            # 后端日志窗口的两个按钮承接（强制刷新 / 打开 DevTools），
            # 这样快捷键不会在敲命令时误触。网页 tab 是独立控件+独立环境，
            # 不受此设置影响（其 F5 仍刷网页）。
            try:
                sender.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = False
            except Exception:
                pass
            # a544：网页 tab 控件管理器装配。失败不阻塞主 UI（网页 tab
            # 打不开但工具其余功能完好），错误进 stderr 可查
            try:
                from src import web_tabs as _wt
                _inst = _wt.install(self.form)
                if _inst:
                    # a550：登记主 UI CoreWebView2——控件事件推送的目标文档
                    # （推到工具 UI 才能调 __webTabNew 等，详见 web_tabs.set_main）
                    _inst.set_main(sender.CoreWebView2)
            except Exception as _e:
                print("[a544] WebTabs install failed: %r" % _e,
                      file=sys.stderr)
        _EC.on_webview_ready = _patched_ready
    except Exception as _patch_err:
        import traceback as _tb
        print("[webview-patch] FAILED: %r" % _patch_err, file=sys.stderr)
        _tb.print_exc()

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
                    _win_set_foreground(w)
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
                    _win_set_foreground(w)
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    # ---- a624：调试能力改由后端日志窗口的两个图标按钮承接 ----
    # 用户令：网页相关快捷键（F5/F12/Ctrl+R）全部屏蔽，能力挪到界面上。
    _ct_json = {"Content-Type": "application/json"}
    @app.route("/api/window/reload", methods=["POST"])
    def _api_window_reload():
        """强制刷新整个工具页面（等同原 F5）。前端 __fcHardReload 里
        先打 reload_disconnect 清场再 location.reload()。"""
        w = getattr(main, "_win", None)
        if w is None:
            return '{"ok": false, "err": "窗口未就绪"}', 503, _ct_json

        def _do():
            # evaluate_js 在 GUI 线程等返回值会死锁（a484 实锤）→ 后台线程
            try:
                w.evaluate_js(
                    "window.__fcHardReload && window.__fcHardReload();")
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()
        return '{"ok": true}', 200, _ct_json

    @app.route("/api/window/devtools", methods=["POST"])
    def _api_window_devtools():
        """打开主 UI DevTools（等同原 F12）。走 CoreWebView2 原生窗口，
        不受 AreBrowserAcceleratorKeysEnabled=False 影响。控件只在 GUI
        线程可操作，故用 _invoke_gui 封送。"""
        w = getattr(main, "_win", None)
        if w is None:
            return '{"ok": false, "err": "窗口未就绪"}', 503, _ct_json
        result = {"ok": False, "err": ""}

        def _do():
            try:
                cvw = _main_core_webview(w)
                if cvw is None:
                    result["err"] = "主界面控件未就绪"
                    return
                cvw.OpenDevToolsWindow()
                result["ok"] = True
            except Exception as e:
                result["err"] = repr(e)

        _invoke_gui(w, _do)
        if result["ok"]:
            return '{"ok": true}', 200, _ct_json
        return ('{"ok": false, "err": %s}'
                % json.dumps(result["err"] or "打开失败"),
                500, _ct_json)

    # ---- a59x 自绘窗控路由（zcode 复刻：页面三钮 + 顶栏拖拽的后端通道）----
    # 命令语义与 zcode desktopCommandHandlers.ts 对齐：MinimizeWindow /
    # ToggleMaximizeWindow（isMaximized 二态切）/ CloseWindow（走托盘语义链）。
    @app.route("/api/window/minimize", methods=["POST"])
    def _api_window_minimize():
        w = getattr(main, "_win", None)
        if w is not None:
            def _do():
                try:
                    w.minimize()
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    @app.route("/api/window/toggle_max", methods=["POST"])
    def _api_window_toggle_max():
        # zcode ToggleMaximizeWindow 同构：isMaximized → unmaximize，否则
        # maximize。**架构铁律（py-spy 死锁实锤）**：一切 .NET Control 成员
        # 调用（WindowState/Bounds/Invoke/Screen）必须打包进单个 GUI 线程
        # 批次——后台线程直调 Control 成员=跨线程未定义行为（SendMessage
        # 同步等 GUI、GUI 等 GIL 进 Python 回调，互等死锁，10 连 toggle 泄
        # 漏 50+ 线程）。后台线程只做 Invoke 投递 + join 收口。
        w = getattr(main, "_win", None)
        out = {"ok": False, "max": False, "overhang": 0}
        if w is not None:
            _done = threading.Event()

            def _do_gui():
                try:
                    import clr as _clr
                    _clr.AddReference("System.Drawing")
                    from System.Drawing import Rectangle as _Rect
                    from System.Windows.Forms import FormWindowState, Screen as _Screen
                    f = getattr(w, "native", None)
                    if f is None:
                        return
                    if f.WindowState == FormWindowState.Maximized:
                        # 自管还原（_fc_restore 注释）：先切 Normal 再写回
                        # maximize 前记录的 bounds（钳到工作区内）
                        f.WindowState = FormWindowState.Normal
                        rb = _fc_restore["bounds"]
                        if rb is not None:
                            try:
                                wa = _Screen.FromHandle(f.Handle).WorkingArea
                                _nx = max(wa.Left, min(rb.X, wa.Right - max(rb.Width, 200)))
                                _ny = max(wa.Top, min(rb.Y, wa.Bottom - max(rb.Height, 200)))
                                f.Bounds = _Rect(_nx, _ny, min(rb.Width, wa.Width),
                                                 min(rb.Height, wa.Height))
                            except Exception:
                                pass
                        _set_edge_pad(w, _edge_border_phys_px(w))   # 还原边缘 resize 带
                        out["max"] = False
                    else:
                        try:
                            if f.WindowState != FormWindowState.Minimized:
                                _fc_restore["bounds"] = f.Bounds   # 记录拖拽后的最新值
                        except Exception:
                            pass
                        _pin_maximized_bounds(w)
                        f.WindowState = FormWindowState.Maximized
                        _set_edge_pad(w, 0)   # 最大化铺满（bounds 已钉 workarea 无越界）
                        out["max"] = True
                    out["ok"] = True
                except Exception:
                    pass
                finally:
                    _done.set()

            try:
                from System.Windows.Forms import MethodInvoker
                f_native = getattr(w, "native", None)
                if f_native is not None:
                    f_native.Invoke(MethodInvoker(_do_gui))
            except Exception:
                pass
            if not _done.is_set():
                out["err"] = "timeout"
        out["overhang"] = _maximize_overhang_css_px(w) if w is not None else 0
        return ('{"ok": %s, "max": %s, "overhang": %s}' % (
                    "true" if out["ok"] else "false",
                    "true" if out["max"] else "false", out["overhang"]),
                200, {"Content-Type": "application/json"})

    @app.route("/api/window/state")
    def _api_window_state():
        # zcode GetDesktopWindowChromeState 同构：页面启动时拉初态
        # （冷启最大化/重启恢复时事件可能早于页面就绪，拉取兜底）。
        # 带 overhang（审计 P1：冷启最大化只回 max 不回补偿值 → is-max 置位
        # 但 --wv-overhang 恒 0，顶/左/右裁 8px 且无后续事件不可自愈）。
        w = getattr(main, "_win", None)
        maxed = False
        try:
            from System.Windows.Forms import FormWindowState
            f = getattr(w, "native", None) if w is not None else None
            if f is not None:
                maxed = f.WindowState == FormWindowState.Maximized
        except Exception:
            pass
        over = _maximize_overhang_css_px(w) if w is not None else 0
        return ('{"ok": true, "max": %s, "overhang": %s}' % (
                    "true" if maxed else "false", over),
                200, {"Content-Type": "application/json"})

    # ---- a59x 边缘 resize（页面热区+自研，inset=0 白框终局方案的配套）----
    # 主窗裸区方案（inset>0+主窗 NCHITTEST）与 WebView2 呈现有固有白框
    # （试金石实验实锤：inset=0 白框消失）——命中改走页面热区：前端四边
    # 热区 mousedown 报方向+鼠标，mousemove 报绝对坐标，后端 GUI 线程按
    # 「起点 bounds+delta」绝对 SetWindowPos（幂等、丢帧无累积误差）。
    _fc_resize = {"active": False, "edge": "", "mx": 0, "my": 0, "bounds": None}

    @app.route("/api/window/resize_begin", methods=["POST"])
    def _api_resize_begin():
        from flask import request
        d = request.get_json(force=True, silent=True) or {}
        edge = str(d.get("edge") or "")
        if edge not in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
            return '{"ok": false}', 200, {"Content-Type": "application/json"}
        w = getattr(main, "_win", None)
        if w is None:
            return '{"ok": false}', 200, {"Content-Type": "application/json"}

        def _do():
            try:
                f = getattr(w, "native", None)
                if f is None:
                    return
                _fc_resize.update(active=True, edge=edge,
                                  mx=int(d.get("x") or 0), my=int(d.get("y") or 0),
                                  bounds=f.Bounds)
            except Exception:
                _fc_resize["active"] = False
        _invoke_gui(w, _do)
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    @app.route("/api/window/resize_move", methods=["POST"])
    def _api_resize_move():
        from flask import request
        d = request.get_json(force=True, silent=True) or {}
        if not _fc_resize["active"]:
            return '{"ok": true}', 200, {"Content-Type": "application/json"}
        w = getattr(main, "_win", None)
        if w is None:
            return '{"ok": true}', 200, {"Content-Type": "application/json"}

        def _do():
            try:
                import clr as _clr
                _clr.AddReference("System.Drawing")
                from System.Drawing import Rectangle as _Rect
                f = getattr(w, "native", None)
                r = _fc_resize["bounds"]
                if f is None or r is None:
                    return
                dx = (int(d.get("x") or 0) - _fc_resize["mx"])
                dy = (int(d.get("y") or 0) - _fc_resize["my"])
                try:
                    scale = (f.DeviceDpi or 96) / 96.0
                except Exception:
                    scale = 1.0
                dx = int(dx * scale)
                dy = int(dy * scale)
                e = _fc_resize["edge"]
                nx, ny, nw, nh = r.X, r.Y, r.Width, r.Height
                if "e" in e: nw = r.Width + dx
                if "s" in e: nh = r.Height + dy
                if "w" in e: nw = r.Width - dx; nx = r.X + dx
                if "n" in e: nh = r.Height - dy; ny = r.Y + dy
                # min_size 钳制（CSS 900×600 → 物理；拖左/上缘时保持对缘不动）
                minw = int(900 * scale)
                minh = int(600 * scale)
                if nw < minw:
                    if "w" in e: nx -= (minw - nw)
                    nw = minw
                if nh < minh:
                    if "n" in e: ny -= (minh - nh)
                    nh = minh
                f.Bounds = _Rect(nx, ny, nw, nh)
            except Exception as _e:
                _fc_resize["err"] = repr(_e)   # 静默吞错的教训：NameError 卡死拖拽
        _invoke_gui(w, _do)
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    @app.route("/api/window/resize_end", methods=["POST"])
    def _api_resize_end():
        _fc_resize["active"] = False
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    @app.route("/api/frontend_log", methods=["POST"])
    def _api_frontend_log():
        # 日志审计盲区#3：前端 JS 异常上报（index.html rec() error 级别，
        # 1s/5 条节流）→ backend_log 'frontend' tag，后端日志面板可见
        from flask import request   # 局部 import（fullscreen 路由 907 行同款教训）
        d = request.get_json(force=True, silent=True) or {}
        text = str(d.get("text") or "")[:1200]
        if text:
            from src import backend_log as _bl
            _bl.error("frontend", text)
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    @app.route("/api/window/bg", methods=["POST"])
    def _api_window_bg():
        # Form 边缘带底色跟随页面主题（win-controls.js 监听 data-theme 上报
        # body backgroundColor；NCCALCSIZE 清非客户区后露出的 Form 区域用页面
        # 同色，视觉无缝，亮暗主题都不露馅）
        from flask import request
        c = str((request.get_json(force=True, silent=True) or {}).get("color") or "")
        m = __import__("re").search(r"rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)", c)
        if m:
            w = getattr(main, "_win", None)
            if w is not None:
                _set_form_bg(w, int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return '{"ok": true}', 200, {"Content-Type": "application/json"}

    @app.route("/api/window/close", methods=["POST"])
    def _api_window_close():
        # a667：✕ 默认是「关闭到托盘」并不退出，不能在此锁定退出原因
        # （否则后续异常退出会被误判为正常 api_close）。真正退出由
        # _do_real_cleanup 的 cleanup / 托盘退出路径记录。
        # 自绘 ✕ 与原生 X 同语义：destroy→Form.Close→closing 拦截链
        # （close_to_tray 默认驻托盘）。_try_destroy 是托盘「退出」同款
        # 通道（后台线程 + 兜底硬退），此处只走 destroy 不置真退标记。
        w = getattr(main, "_win", None)
        if w is not None:
            def _do():
                try:
                    w.destroy()
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

    # a544：h2 代理端口退役（终局形态为 WebView2 控件，代理流量归零）。
    # 证书文件遗留（数据目录 web_h2_cert/key.pem）无害——certutil 已导入
    # 用户受信根的那张自签证书同样无害（只信任 127.0.0.1），不回滚系统。

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
    _boot_mark("Flask 就绪")

    # Claude 子系统 worker：进程隔离（harness/hiklink 重负载移驻独立进程，
    # 见 src/worker_app.py 模块注释）。失败不阻塞主工具（Claude 面板不可用，
    # 串口终端不受影响）；崩溃由 worker 侧 supervisor 自动重启
    # main_port（a117）：主页面真实来源随拉起注入 worker CORS 白名单——
    # 端口动态随机，worker 侧硬编码必拦（用户实锤「重启后全挂/会话空」）
    try:
        from src import worker_app
        _boot_mark("worker 拉起 开始")
        # a668：异步拉起——Popen + READY 握手（实测 1140ms）走后台线程，
        # 主线程立刻继续开窗。握手完成前 harness/hiklink 族由 server.py 的
        # 307 兜底（WORKER_BASE 空时 503，前端 workerbase.js 本来就这么处理）。
        worker_app.manage_start(main_port=port)
        _boot_mark("worker 拉起已派发（后台握手）")
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
                _win_set_foreground(w)
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
        # background_color 已停用（A/B 实验：白框复现与该参数强相关——
        # pywebview 在 CoreWebView2InitializationCompleted 时强制
        # DefaultBackgroundColor=FromArgb(255,bg)，与我们的 Controller
        # 染色竞争；启动白闪改由主题色持久化+首次 bg 上报前 Form 深色兜底）
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
        _exit_reason("cleanup")
        # a582（内网方案·根因2）：网页 tab 的 WebView2 环境必须在后续
        # taskkill /T /F 树杀**之前**优雅关闭——Chromium cookie/密码库是
        # 延迟批量写盘，被强杀则未落盘数据全丢（用户实锤：每次重开工具
        # 所有网页登录态全丢）。内部 sleep ~1.2s 等浏览器进程 flush。
        try:
            from src import web_tabs as _wt
            _wt.shutdown()
        except Exception:
            pass
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
            _audit_exit()
        except Exception:
            pass
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
        _exit_reason("tray_exit")
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

    # ---- a59x 无题化 + 状态回推（zcode DesktopWindowChromeStateChanged 同构）----
    # 单飞信号闸（终审 P3 补回）：evaluate_js 无超时，WebView2 尺寸剧变时
    # EvaluateJavaScriptAsync 可能挂死（py-spy 实锤）——非阻塞抢闸失败即
    # 跳过，卡死线程堆积上限 1，正确性由前端 state 拉取兜底
    _hg_push_gate = threading.Semaphore(1)
    _hg_pending = {"dirty": False}
    _hg_last_state = {"max": None, "over": -1.0}
    def _hg_push_win_state(maxed, force=False):
        """最大化态变化推给页面：切 ▢/❐ 字形 + 最大化越界补偿值。
        pywebview 事件回调在后台线程执行（Event.set 开线程），evaluate_js
        内部 marshal 回 GUI——on_closing 注释里的 GUI 线程死锁坑在此不适用；
        页面未就绪时求值失败静默（冷启最大化场景由 /api/window/state 拉取兜底）。
        闸改「脏标记补推」（2026-11-18 用户实锤：最小化还原时 maximized/
        restored 事件交替，闸忙 skip 漏推 → 窗体 Maximized 但 UI is-max 没置
        位/字形错）——闸忙置 dirty，release 前补推真实态；补推重读真实
        WindowState（minimize→restore 过程 .NET 内部 Normal→Maximized 两次
        切换，事件交替竞态以真实态为准）。"""
        if not _hg_push_gate.acquire(blocking=False):
            _hg_pending["dirty"] = True
            return   # 已有推送卡在 evaluate_js——置脏，release 前补推
        try:
            over = _maximize_overhang_css_px(window)
            # 竞态修正：以真实 WindowState 为准（事件参数可能反映中间态）
            try:
                from System.Windows.Forms import FormWindowState as _FS
                f2 = getattr(window, "native", None)
                if f2 is not None and f2.WindowState == _FS.Maximized:
                    maxed = True
            except Exception:
                pass
            # 审计 P1（snap 保险）：值没变就跳过（拖拽时不逐帧刷 JS）
            if not force and _hg_last_state["max"] == maxed \
                    and abs(_hg_last_state["over"] - over) < 0.5:
                _hg_pending["dirty"] = False
                return
            _hg_last_state["max"] = maxed
            _hg_last_state["over"] = over
            window.evaluate_js(
                "window._hgWinState&&window._hgWinState({max:%s,overhang:%s})"
                % ("true" if maxed else "false", over))
        except Exception:
            pass
        finally:
            # 闸持期内置脏的（并发事件被 skip）——补推一轮真实态，推送永不丢
            if _hg_pending.pop("dirty", False):
                try:
                    from System.Windows.Forms import FormWindowState as _FS2
                    f2 = getattr(window, "native", None)
                    _cur = f2 is not None and f2.WindowState == _FS2.Maximized
                    if _hg_last_state["max"] != _cur:
                        _hg_last_state["max"] = _cur
                        # a635（对抗审计 P2-1）：补推必须带 overhang——不带
                        # 时前端 _apply 收到 undefined 会把 ov 归零、摘掉
                        # hg-overhang 类，恰好在「闸忙、事件交替」这个最需要
                        # 补偿的窗口里造成 8px 闪烁。
                        _over2 = _maximize_overhang_css_px(window)
                        _hg_last_state["over"] = _over2
                        window.evaluate_js(
                            "window._hgWinState&&window._hgWinState({max:%s,overhang:%s})"
                            % ("true" if _cur else "false", _over2))
                except Exception:
                    pass
            _hg_push_gate.release()

    window.events.maximized += lambda: (_fc_restore.__setitem__(
        "from_max", True), _hg_push_win_state(True))
    # a635（对抗审计 P1-5）：a633 把 restored 链里的 _hg_push_win_state(False)
    # 换成了 _hg_restore_bounds_fix，而前者是全代码唯一推 max=false 给页面的
    # 地方——卸载后 UI 的 is-max/❐ 字形只能靠 resize 防抖拉取兜底；Bounds 写
    # 回后尺寸恰好不变时 resize 不触发，页面停在 is-max。这里补回推送
    # （顺序：先清 from_max，再矫正 bounds，最后推状态）。
    window.events.restored += lambda: (
        _fc_restore.__setitem__("from_max", False),
        _hg_restore_bounds_fix(window),
        _hg_push_win_state(False))
    # minimized/restored 自管矫正（用户复现路径实锤：拖边框→任务栏最小化→
    # 还原×N→内容缩块——任务栏还原走 ShowWindow(SW_RESTORE)，不发
    # SYSCOMMAND 钩不到；Windows 对无 CAPTION 窗的 restore 按「假想有边框」
    # 重算 bounds，每循环累积漂移。minimized 时自记 bounds，restored 时
    # 强制写回，绕开系统漂移）
    # pre_min 常态化跟踪（时机修正：minimized 事件时 bounds 已被系统改成
    # -32000 垃圾值（实测 pre_min=(-32000,-32000)→矫正写回 (0,0)）——改为
    # Normal 态的 moved/resized 事件持续刷新，最小化发生时自然是最后一次好值
    window.events.resized += lambda: _hg_track_normal_bounds(window)
    window.events.moved += lambda: _hg_track_normal_bounds(window)

    def _hg_track_normal_bounds(win):
        # a635（对抗审计 P2-2）：pywebview 的 Event.set 在 should_lock=False
        # 时**每个事件开一个 Thread**，拖拽 resize 是 60-120Hz——每帧一个
        # Python 线程 + 一次跨线程 Invoke 同步等待（py-spy 当初抓到的正是
        # 这个形态）。这里做**尾随去抖**：拖拽期间只保留最后一个事件，停止
        # 120ms 后补一次（读的是 GUI 线程里的真实状态，不丢状态）。
        import time as _t
        _now = _t.time()
        if _fc_restore.get("trk_timer"):
            try:
                _fc_restore["trk_timer"].cancel()
            except Exception:
                pass
        def _later():
            _fc_restore["trk_timer"] = None
            _track_now(win)
        try:
            _tm = threading.Timer(0.12, _later)
            _tm.daemon = True
            _fc_restore["trk_timer"] = _tm
            _tm.start()
        except Exception:
            _track_now(win)      # 定时器建不起来：直接读（宁多一次不丢）

    def _track_now(win):
        try:
            from System.Windows.Forms import FormWindowState, MethodInvoker
            f = getattr(win, "native", None)
            if f is None:
                return
            def _save():
                try:
                    from System.Windows.Forms import FormWindowState as _FS
                    if f.WindowState == _FS.Normal:
                        _fc_restore["pre_min"] = f.Bounds
                    elif f.WindowState == _FS.Minimized:
                        _fc_restore["from_min"] = True   # minimized 置位（矫正开关）
                except Exception:
                    pass
            f.Invoke(MethodInvoker(_save))
        except Exception:
            pass

    def _hg_restore_bounds_fix(win):
        try:
            def _fix():
                try:
                    from System.Windows.Forms import FormWindowState, Screen as _Screen
                    f = getattr(win, "native", None)
                    if f is None or f.WindowState != FormWindowState.Normal:
                        return
                    # 终审 P2-4：本矫正只管「来自 minimized 的 restored」
                    # ——un-maximize（toggle_max/SC_RESTORE 接管）不干预（它们的
                    # bounds 自管正确）。RestoreBounds 数据源弃用（压测实锤
                    # 6 循环 +355px：.NET 镜像同样被 NCCALCSIZE 污染）
                    if not _fc_restore.get("from_min"):
                        return
                    _fc_restore["from_min"] = False
                    rb = _fc_restore["pre_min"]
                    if rb is None:
                        return
                    _fc_restore["pre_min"] = None
                    wa = _Screen.FromHandle(f.Handle).WorkingArea
                    nx = max(wa.Left, min(rb.X, wa.Right - max(rb.Width, 200)))
                    ny = max(wa.Top, min(rb.Y, wa.Bottom - max(rb.Height, 200)))
                    f.Bounds = System.Drawing.Rectangle(
                        nx, ny, min(rb.Width, wa.Width), min(rb.Height, wa.Height))
                except Exception:
                    pass
            import System
            from System.Windows.Forms import MethodInvoker
            f = getattr(win, "native", None)
            if f is not None:
                f.Invoke(MethodInvoker(_fix))
        except Exception:
            pass
    # resized/moved 高频推送摘除（py-spy 实锤：每事件一线程，evaluate_js 卡死
    # 堆积）——snap/移动场景改由前端 resize 防抖拉取 /api/window/state
    # shown 后摘 WS_CAPTION（GUI 线程 Invoke 封送）；loaded 再补一刀幂等
    # （shown 偶发不触发/句柄重建场景兜底——strip 幂等无副作用）
    window.events.shown += lambda: _strip_window_caption(window)
    window.events.loaded += lambda: _strip_window_caption(window)

    # 窗口加载完成后注册原生拖拽：pywebview 的 WebView2 后端能拿到文件绝对路径
    # （Chromium 标准 File.path 不暴露，但 pywebview 通过 CoreWebView2File.Path 获取，
    #   注入 event.dataTransfer.files[i].pywebviewFullPath）。需用 pywebview DOM API
    #   注册 drop 监听（_dnd_state.num_listeners>0 才捕获路径），回调里 evaluate_js 调前端。
    def on_loaded():
        _boot_mark("窗口 loaded（页面可见）")
        # 页面加载完成即激活并置前窗口：从托盘/后台/快捷方式启动时窗口可能不在
        # 前台，用户打开工具就是为了敲命令——不等先点一下
        try:
            window.show()
            _win_set_foreground(window)
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
    # v3.4.99 定的「正常启动无 F12/右键/F5」已由 a624 迭代：
    # a624（用户令）：调试能力常开（devtools 是 MCP 网页操作的必需品），
    # 但**浏览器级快捷键全屏蔽**（F5/F12/Ctrl+R/Ctrl+Shift+I），改由后端
    # 日志窗口的两个按钮承接。pywebview 的 debug=True 会连带打开 DevTools
    # 快捷键与右键菜单，所以 webview.start 仍传 False；DevTools 由按钮
    # 显式调用 CoreWebView2.OpenDevToolsWindow() 打开。
    from src.server import DEBUG_CAPS as _dbg_caps
    _wv_debug = False
    # a473（用户令：L3 网页操作必须有）：CDP 端口——AI 经 devtools_* MCP
    # 工具操作浏览器（内网换组件/报错分析）。端口只绑 127.0.0.1（CDP 固有
    # 行为），本机单用户工具可接受。
    # a624：调试能力常开 → 主 UI 的 CDP 端口也常开（MCP 的 devtools_*
    # 依赖它；此前只在 run_debug.bat 下才有，网页操作需求无法满足）。
    _web_cdp_cfg = bool(_dbg_caps)
    if not _web_cdp_cfg:
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
    # R1 审计 W1（P0）：a501 的 --disable-web-security 已随 a544 iframe
    # 时代退役。该开关经 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 同样注入
    # 网页 tab 独立浏览器进程 → 任意外站可跨源调用本机 GET API
    # （/api/read_text 任意文件读、/api/history 终端历史）。主 UI 与
    # 网页 tab 均无跨源需求，移除。
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
    _boot_mark("即将 webview.start（窗口创建）")


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
