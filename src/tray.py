# -*- coding: utf-8 -*-
"""系统托盘——原生 Win32 自建（ctypes 直调 Shell_NotifyIcon），无 pystray。

历史教训（用户实锤两轮）：pystray 的 ctypes 消息循环在本进程
（pywebview/WinForms 混宿主）里会静默死——窗口销毁但 _visible 标志残留，
watchdog 重建的新 Icon 又立刻死，2 分钟攒出 9 具幽灵图标（鼠标一划过
Explorer 清尸体）。不再修它，整个换掉：
- 专用线程跑 GetMessage 消息循环，全程自己写，死活有日志有栈
- 退出/线程死 finally 必 NIM_DELETE——不留尸体图标
- WM_TASKBARCREATED（explorer 重启）→ 重新 NIM_ADD 自愈
- 菜单每次右键时动态重建 HMENU（原生 Notepad++ 同款），text/checked
  传函数即每次打开求值，零重建成本
- tooltip set_tip() 线程安全（PostMessage 到托盘线程执行 NIM_MODIFY）

接口（与旧 pystray 版兼容）：
- hide_to_tray(window, on_quit)：首次调用建托盘（懒建），之后只 hide
- quit_tray()：退出清理（NIM_DELETE + 销毁窗口 + 退出消息循环）
- set_tip(text)：更新悬浮 tooltip（节流由调用方做，值不变可不调）
- alive()：托盘线程是否活着（watchdog 用）
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading

_tray = None          # _NativeTray 单例
_lock = threading.Lock()
_window = None        # hide_to_tray 留存窗口引用
_on_quit = None       # 重建用退出回调
_watchdog = None

WM_APP_ = 0x8000
WM_TRAY_CALLBACK = WM_APP_ + 1     # Shell_NotifyIcon 回调消息号
WM_TRAY_SETTITLE = WM_APP_ + 2     # set_tip 投递给托盘线程
WM_TRAY_STOP = WM_APP_ + 3         # quit_tray 请求退出
# 64 位下 WNDPROC 必须自定（wintypes 无 WNDPROC）：LRESULT 是 8 字节
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT,
                             ctypes.c_void_p, ctypes.c_void_p)
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000
WM_DESTROY = 0x0002
# NIM 常量：微软 SDK 头文件 0/1/2（NIM_ADD=0）——pystray 同值。
# 初版误写 1/2/3 错位（NIM_MODIFY 当 ADD），所有 ADD 全变 MODIFY → E_FAIL，
# 调试两小时才在 pystray win32.py 对出真值。教训：ctypes 常量必须核对 SDK 头。
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
TPM_RIGHTALIGN, TPM_BOTTOMALIGN, TPM_RETURNCMD = 8, 0x20, 0x0100
MFS_DISABLED, MFS_CHECKED, MFS_DEFAULT = 3, 8, 0x1000
MFT_SEPARATOR, MFT_RADIOCHECK = 0x800, 0x200
MIIM_FTYPE, MIIM_STRING, MIIM_STATE, MIIM_ID, MIIM_SUBMENU = 0x100, 0x40, 1, 2, 4
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
WS_POPUP = 0x80000000


class _NOTIFYICONDATAW(ctypes.Structure):
    """照抄 pystray 的定义（GUID 结构 + union 匿名展开）——自建平铺版
    在本机稳定 NIM_ADD E_FAIL，同字段同 offset 仍失败，不深究内核实现，
    以实测能过的为准。"""
    class _VOT(ctypes.Union):
        _fields_ = [("uTimeout", wt.UINT), ("uVersion", wt.UINT)]
    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.ULONG), ("Data2", wt.WORD),
                    ("Data3", wt.WORD), ("Data4", wt.BYTE * 8)]
    _fields_ = [
        ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
        ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256), ("version_or_timeout", _VOT),
        ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
        ("guidItem", _GUID), ("hBalloonIcon", wt.HICON),
    ]
    _anonymous_ = ["version_or_timeout"]


class _MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT),
        ("fState", wt.UINT), ("wID", wt.UINT), ("hSubMenu", wt.HMENU),
        ("hbmpChecked", wt.HANDLE), ("hbmpUnchecked", wt.HANDLE),
        ("dwItemData", ctypes.c_void_p), ("dwTypeData", wt.LPWSTR),
        ("cch", wt.UINT), ("hbmpItem", wt.HANDLE),
    ]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", ctypes.c_void_p), ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_shell32 = ctypes.windll.shell32

# 显式 argtypes：ctypes 默认按 int 推断，64 位下 HANDLE 类负值句柄
# 直接 OverflowError（CreateWindowExW 的 hInstance 实测炸过）
_u32.RegisterClassExW.argtypes = (ctypes.c_void_p,)
_u32.RegisterClassExW.restype = wt.ATOM
_u32.UnregisterClassW.argtypes = (wt.ATOM, wt.HINSTANCE)
_u32.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wt.HWND, ctypes.c_void_p,
                                 wt.HINSTANCE, ctypes.c_void_p)
_u32.CreateWindowExW.restype = wt.HWND
_u32.LoadImageW.argtypes = (wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                            ctypes.c_int, wt.UINT)
_u32.LoadImageW.restype = wt.HANDLE
_u32.GetMessageW.argtypes = (ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT)
_u32.GetMessageW.restype = ctypes.c_int
_u32.IsWindow.argtypes = (wt.HWND,)
_u32.IsWindow.restype = wt.BOOL
_u32.DestroyWindow.argtypes = (wt.HWND,)
_u32.SetForegroundWindow.argtypes = (wt.HWND,)
_u32.PostMessageW.argtypes = (wt.HWND, wt.UINT, ctypes.c_void_p, ctypes.c_void_p)
_u32.PostMessageW.restype = wt.BOOL
_u32.PostQuitMessage.argtypes = (ctypes.c_int,)
_u32.GetCursorPos.argtypes = (ctypes.c_void_p,)
_u32.TrackPopupMenuEx.argtypes = (wt.HMENU, wt.UINT, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, ctypes.c_void_p)
_u32.TrackPopupMenuEx.restype = ctypes.c_int
_u32.CreatePopupMenu.argtypes = ()
_u32.CreatePopupMenu.restype = wt.HMENU
_u32.DestroyMenu.argtypes = (wt.HMENU,)
_u32.InsertMenuItemW.argtypes = (wt.HMENU, wt.UINT, wt.BOOL, ctypes.c_void_p)
_u32.RegisterWindowMessageW.argtypes = (wt.LPCWSTR,)
_u32.RegisterWindowMessageW.restype = wt.UINT
_u32.ChangeWindowMessageFilterEx.argtypes = (wt.HWND, wt.UINT, wt.DWORD,
                                             ctypes.c_void_p)
_u32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, ctypes.c_void_p,
                                ctypes.c_void_p)
_u32.DefWindowProcW.restype = ctypes.c_longlong
_shell32.Shell_NotifyIconW.argtypes = (wt.DWORD, ctypes.c_void_p)
_shell32.Shell_NotifyIconW.restype = wt.BOOL


def _log(fmt, *a):
    """托盘自身日志（复用主工具 logging，够定位线程死因）。"""
    try:
        import logging
        logging.getLogger("serialconsole.tray").info(fmt, *a)
    except Exception:
        pass


def _val(v, *args):
    """text/checked/enabled 可传函数（打开菜单时求值）——统一求值。"""
    if callable(v):
        try:
            return v(*args)
        except Exception:
            return None
    return v


class _NativeTray:
    """一个原生托盘：窗口+图标+消息循环线程+动态菜单。

    menu_provider() → 菜单描述树（每次右键重新取，动态 text 求值）：
      [("sep",)
       ("item", text, callback, {"checked":, "radio":, "enabled":,
                                 "default":, "submenu": [...]})]
    on_default()：左键单击回调（显示主窗口）
    """

    def __init__(self, ico_path, title, menu_provider, on_default, on_quit):
        self._ico_path = ico_path
        self._title = title
        self._menu_provider = menu_provider
        self._on_default = on_default
        self._on_quit = on_quit
        self._hwnd = None
        self._thread = None
        self._stopping = False
        self._hicon = None
        self._class_atom = None
        self._wndproc_ref = None       # 防 GC：WNDPROC 必须持有引用
        self._wm_taskbar = 0           # RegisterWindowMessage("TaskbarCreated")

    # ---- 生命周期 ----
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="tray-win32")
        self._thread.start()

    def alive(self):
        t = self._thread
        if t is None or not t.is_alive():
            return False
        return bool(self._hwnd) and bool(_u32.IsWindow(self._hwnd))

    def set_tip(self, text):
        """更新 tooltip。线程安全：PostMessage 让托盘线程执行 NIM_MODIFY
        （Shell_NotifyIcon 文档不保证跨线程安全，落回消息线程最稳）。"""
        if not self.alive() or not text:
            return
        # LPARAM 传 unicode buffer 地址；队列期间防 GC——挂模块级池
        # （托盘线程消费后清池，池超上限丢最旧，量级 tip 文本可忽略）。
        buf = ctypes.create_unicode_buffer(text[:127])
        if len(_tip_pool) > 64:
            del _tip_pool[:32]
        _tip_pool.append(buf)
        _u32.PostMessageW(self._hwnd, WM_TRAY_SETTITLE, 0,
                          ctypes.addressof(buf))

    # ---- 内部：托盘线程 ----
    def _run(self):
        """托盘线程主体：注册类 → 建窗 → NIM_ADD → 消息循环 → finally 清理。
        一切异常都落日志——线程死因下次有据可查（pystray 的教训）。"""
        pid = os.getpid()
        try:
            self._wm_taskbar = _u32.RegisterWindowMessageW("TaskbarCreated")
            wc = _WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
            self._wndproc_ref = WNDPROC(self._wndproc)
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = _k32.GetModuleHandleW(None)
            wc.lpszClassName = "SerialConsoleProTray%d" % pid
            self._class_atom = _u32.RegisterClassExW(ctypes.byref(wc))
            if not self._class_atom:
                raise ctypes.WinError()
            # 类名参数：官方允许传 atom（MAKEINTATOM），ctypes 下
            # c_wchar_p(atom) 是等价表达（LPCWSTR argtypes 要求）
            self._hwnd = _u32.CreateWindowExW(
                0, ctypes.c_wchar_p(self._class_atom), None, WS_POPUP,
                0, 0, 0, 0, None, None, wc.hInstance, None)
            if not self._hwnd:
                raise ctypes.WinError()
            _u32.ChangeWindowMessageFilterEx(self._hwnd, self._wm_taskbar, 1, None)
            self._hicon = _u32.LoadImageW(
                None, os.path.abspath(self._ico_path), IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE)
            self._shell_add()
            _log("托盘线程启动 hwnd=%s", self._hwnd)
        except Exception:
            _log("托盘启动失败: %s", repr(_exc()))
            self._cleanup_window()
            return
        # 消息循环（GetMessage 0=WM_QUIT 退出；-1=错误也退）
        msg = wt.MSG()
        lpmsg = ctypes.byref(msg)
        try:
            while True:
                r = _u32.GetMessageW(lpmsg, None, 0, 0)
                if r in (0, -1):
                    _log("消息循环退出 code=%s（0=正常退出 -1=错误）", r)
                    break
                _u32.TranslateMessage(lpmsg)
                _u32.DispatchMessageW(lpmsg)
        except Exception:
            _log("消息循环异常: %s", repr(_exc()))
        finally:
            self._cleanup_window()

    def _cleanup_window(self):
        """finally 必清：NIM_DELETE（不留尸体图标）→ 销毁窗 → 反注册类。"""
        try:
            self._shell_delete()
        except Exception:
            pass
        if self._hwnd:
            try:
                _u32.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
        if self._class_atom:
            try:
                _u32.UnregisterClassW(self._class_atom,
                                      _k32.GetModuleHandleW(None))
            except Exception:
                pass
            self._class_atom = None

    def _shell_add(self):
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY_CALLBACK
        nid.hIcon = self._hicon
        nid.szTip = self._title[:127]
        if not _shell32.Shell_NotifyIconW(NIM_ADD,
                                                      ctypes.byref(nid)):
            _log("NIM_ADD 失败 err=%s", _k32.GetLastError())

    def _shell_delete(self):
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        _shell32.Shell_NotifyIconW(NIM_DELETE,
                                                ctypes.byref(nid))

    def _shell_settip(self, lparam):
        """托盘线程内：LPARAM 是 unicode buffer 地址，拷进 szTip 后 NIM_MODIFY。"""
        try:
            text = ctypes.wstring_at(lparam)
        except Exception:
            return 0
        # 消费完清池（防 GC 保护池无界增长——池上限 64 由 set_tip 控制）
        _tip_pool.clear()
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_TIP
        nid.szTip = text[:127]
        _shell32.Shell_NotifyIconW(NIM_MODIFY,
                                                ctypes.byref(nid))
        return 0

    # ---- WndProc ----
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == self._wm_taskbar:
                # explorer 重启 → 图标列表被清空，重新 ADD 自愈
                self._shell_add()
                return 0
            if msg == WM_TRAY_CALLBACK:
                low = lparam & 0xFFFF
                if low == WM_LBUTTONUP:
                    self._fire(self._on_default)
                elif low == WM_RBUTTONUP:
                    self._popup_menu()
                return 0
            if msg == WM_TRAY_SETTITLE:
                self._shell_settip(lparam)
                return 0
            if msg == WM_TRAY_STOP:
                _u32.PostQuitMessage(0)
                return 0
            if msg == WM_DESTROY:
                _u32.PostQuitMessage(0)
                return 0
            return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            _log("WndProc 异常 msg=%s: %s", msg, repr(_exc()))
            return 0

    def _fire(self, fn):
        """菜单/单击回调在托盘线程执行，包 daemon 线程防卡消息循环。"""
        if fn is None:
            return

        def _safe():
            try:
                fn()
            except Exception:
                _log("托盘回调异常: %s", repr(_exc()))
        threading.Thread(target=_safe, daemon=True).start()

    # ---- 右键菜单 ----
    def _popup_menu(self):
        """右键：动态重建 HMENU（每次打开求值 text/checked/enabled）→
        TrackPopupMenuEx → 按 ID 回调。原生 Notepad++ 同款做法。"""
        descs = []
        try:
            descs = self._menu_provider()
        except Exception:
            _log("菜单构建异常: %s", repr(_exc()))
            return
        hmenu = _u32.CreatePopupMenu()
        if not hmenu:
            return
        callbacks = {}   # id → fn

        # text/checked/submenu 里的函数项在打开菜单时求值（args 传 None
        # 即 pystray MenuItem(fn, ...) 同签名兼容）
        def _add(parent, items):
            for it in items:
                if isinstance(it, tuple) and it and it[0] == "sep":
                    mii = _MENUITEMINFOW()
                    mii.cbSize = ctypes.sizeof(_MENUITEMINFOW)
                    mii.fMask = MIIM_FTYPE
                    mii.fType = MFT_SEPARATOR
                    _u32.InsertMenuItemW(parent, 0xFFFF, True,
                                         ctypes.byref(mii))
                    continue
                _, text, cb, opts = it
                mid = len(callbacks) + 1
                callbacks[mid] = cb
                mii = _MENUITEMINFOW()
                mii.cbSize = ctypes.sizeof(_MENUITEMINFOW)
                mii.fMask = (MIIM_FTYPE | MIIM_STRING | MIIM_STATE |
                             MIIM_ID | MIIM_SUBMENU)
                mii.wID = mid
                mii.dwTypeData = str(_val(text) or "")
                mii.fType = MFT_RADIOCHECK if opts.get("radio") else 0
                state = 0
                if not opts.get("enabled", True):
                    state |= MFS_DISABLED
                if opts.get("checked"):
                    state |= MFS_CHECKED
                if opts.get("default"):
                    state |= MFS_DEFAULT
                mii.fState = state
                sub = opts.get("submenu")
                if sub:
                    mii.hSubMenu = _u32.CreatePopupMenu()
                    _add(mii.hSubMenu, sub)
                _u32.InsertMenuItemW(parent, 0xFFFF, True, ctypes.byref(mii))

        try:
            _add(hmenu, descs)
            # TrackPopupMenu 前必须 SetForegroundWindow（微软文档），
            # 弹完 PostMessage(WM_NULL) 让菜单正确消失
            _u32.SetForegroundWindow(self._hwnd)
            pt = wt.POINT()
            _u32.GetCursorPos(ctypes.byref(pt))
            cmd = _u32.TrackPopupMenuEx(
                hmenu, TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                pt.x, pt.y, self._hwnd, None)
            _u32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
            if cmd and cmd in callbacks:
                self._fire(callbacks[cmd])
        finally:
            _u32.DestroyMenu(hmenu)

    def stop(self):
        """请求退出：PostMessage 让托盘线程走 finally 清理路径。"""
        if self._hwnd and _u32.IsWindow(self._hwnd):
            _u32.PostMessageW(self._hwnd, WM_TRAY_STOP, 0, 0)


# set_tip 跨线程传 unicode buffer：保持强引用直到托盘线程消费完
# （PostMessage 队列期间防 GC；泄漏量级：每条 tip 一个 buffer，
# 托盘线程消费后清池——见 _shell_settip 后清空。简单起见：池有上限，
# 消费时清空，未消费的堆积到上限后丢弃最旧）。
_tip_pool = []


def _exc():
    import sys
    return sys.exc_info()[1]


def _make_menu_provider(window, on_quit):
    """菜单描述树构建器：显示主窗口 / Proxy 段（动态） / 退出。"""
    def provider():
        # a672：先给安全初值——下面 Proxy 段的 try 若在 import 阶段失败，
        # Lanzi 段会读到未定义名而整段静默消失（外层 except 吞掉）
        _base = ""
        _offload = False
        items = [
            ("item", "显示主窗口",
             lambda: (window.show(), window.restore(),
                      _win_set_foreground(window)),
             {"default": True}),
            ("sep",),
        ]
        try:
            from src import proxy as _proxy
            # 进程隔离（proxy 二期）：proxy 数据面在 worker——菜单段走 HTTP
            # 桥（状态/操作经 /api/proxy/* 往返）；worker 未就绪跳过该段
            from src import server as _srv
            _base = getattr(_srv, "WORKER_BASE", "")
            # MAJOR-5 修正（a116 二次全审）：inline 排障形态（CLAUDE_INLINE=1
            # 或 CLAUDE_OFFLOAD=False）下 manage_start 直接 return、
            # WORKER_BASE 恒空，但 proxy_bp 就注册在**主进程**（server.py），
            # 本地 tray_menu_items() 完全可用。原实现只判 _base，让该形态
            # 的代理菜单整段消失（功能回归）。
            _offload = bool(getattr(_srv, "CLAUDE_OFFLOAD", False))
            if _base:
                items.extend(_proxy.tray_menu_items_remote(_base))
            elif not _offload:
                items.extend(_proxy.tray_menu_items())
            else:
                # P2-9 修复（a116）：offload 形态下 worker 未就绪时**不得**
                # 回落到本地 proxy 菜单——其回调（start_proxy/set_mode）会在
                # 主进程真实执行（绑端口、改 base_url），隔离被绕过且两个
                # 进程可能同时持有代理状态。只放一行灰字提示。
                items.append(("item", "（Claude 后端未就绪）", lambda: None,
                              {"enabled": False}))
        except Exception:
            _log("Proxy 菜单段构建失败: %s", repr(_exc()))

        # a672：Lanzi 段（额度概览 + 立即刷新）——数据面在 worker 时经 HTTP
        # 桥读 /api/lanzi/status；inline 形态直接读本地 lanzi 状态槽
        try:
            from src.lanzi import menu as _lm
            items.extend(_lm.menu_items(_base, _offload))
        except Exception:
            _log("Lanzi 菜单段构建失败: %s", repr(_exc()))
        items.append(("sep",))
        items.append(("item", "退出", on_quit, {}))
        return items
    return provider


def get_icon():
    """兼容旧接口名：返回托盘单例（proxy tooltip 线程判空用）。
    新代码请用 set_tip()。"""
    return _tray


def set_tip(text):
    """更新托盘 tooltip（proxy 模块 tooltip 线程调用）。"""
    t = _tray
    if t is not None:
        t.set_tip(text)


def alive():
    """托盘是否健康（watchdog 用）。"""
    return _tray is not None and _tray.alive()


def _win_set_foreground(window):
    """pywebview 6.x 的 window.focus 是 bool 属性不是方法（调用即
    TypeError 'bool' object is not callable，托盘「显示主窗口」实锤）——
    置前走 Win32 SetForegroundWindow（最小化先恢复）。"""
    try:
        hwnd = int(window.native.Handle.ToInt64())
        import ctypes as _ct
        u = _ct.windll.user32
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _tray_show(window):
    """（用户定调「记忆窗格大小」）：托盘点开保留隐藏前的窗口态——
    最大化关闭→回最大化；窗口化关闭→回窗口化。restore() 只在最小化态
    兜底（对 Maximized 隐藏态调用会把最大化降成普通尺寸）。"""
    try:
        window.show()
        try:
            from System.Windows.Forms import FormWindowState
            if window.native.WindowState == FormWindowState.Minimized:
                window.restore()
        except Exception:
            pass
        _win_set_foreground(window)
    except Exception:
        pass


def ensure_tray(window, on_quit):
    """（用户需求「桌面已经启动后就创建任务栏图标」）：启动即建托盘
    （不隐藏窗口）。幂等——已建只更新回调归属；watchdog 同步拉起。"""
    global _tray, _window, _on_quit, _watchdog
    with _lock:
        _window, _on_quit = window, on_quit
        if _tray is None:
            from src.app_state import RES_DIR
            ico = os.path.join(RES_DIR, "ico", "app.ico")
            _tray = _NativeTray(
                ico, "前端控制台", _make_menu_provider(window, on_quit),
                on_default=lambda: _tray_show(window),
                on_quit=on_quit)
            _tray.start()
        if _watchdog is None:
            _watchdog = threading.Thread(target=_watchdog_loop, daemon=True)
            _watchdog.start()


def hide_to_tray(window, on_quit):
    """隐藏主窗口到托盘（首次调用建原生托盘，之后只 hide）。"""
    ensure_tray(window, on_quit)
    try:
        window.hide()
    except Exception:
        pass
    return True


def _watchdog_loop():
    """30s 验活：托盘线程死/窗口毁 → 停残骸重建（原生实现有日志有栈，
    正常不该死；此为兜底——用户实锤过两轮，宁可多一层保险）。"""
    import time
    global _tray   # R9.7：声明必须在任何使用之前——Python 3.14 把「先使用
    # 后声明 global」升级为硬 SyntaxError（a535 的函数中段声明在 3.14 编译
    # 即失败，托盘隐藏线程因此死亡）。提前到函数顶部覆盖全部使用点。
    while True:
        time.sleep(30)
        with _lock:
            tray = _tray
        if tray is None:
            continue
        if not tray.alive():
            _log("watchdog：托盘线程死亡，重建")
            with _lock:
                try:
                    tray.stop()
                except Exception:
                    pass
                if _window is not None:
                    from src.app_state import RES_DIR
                    ico = os.path.join(RES_DIR, "ico", "app.ico")
                    _tray = _NativeTray(
                        ico, "前端控制台",
                        _make_menu_provider(_window, _on_quit),
                        on_default=lambda w=_window: _tray_show(w),
                        on_quit=_on_quit)
                    _tray.start()
                else:
                    _tray = None


def quit_tray():
    """退出前清托盘（NIM_DELETE 由托盘线程 finally 保证）。"""
    global _tray
    with _lock:
        t = _tray
        _tray = None
    if t is not None:
        try:
            t.stop()
            if t._thread is not None:
                t._thread.join(timeout=2)
        except Exception:
            pass
