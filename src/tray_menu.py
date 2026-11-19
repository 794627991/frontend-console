# -*- coding: utf-8 -*-
"""托盘右键菜单——完全自绘弹层（用户定调：ZCode 同款观感）。

不再用 HMENU/TrackPopupMenu：系统菜单的暗色、圆角、行高、hover 全部
不可控（a679 owner-draw 要 CBT 钩子拍 #32768 + WM_ENTERIDLE 补边框，
实测观感/交互都不可靠）。这里用 WS_POPUP 无边框窗口 + GDI 双缓冲自绘：
圆角深色卡片、分组线、hover 高亮、勾选/圆点/子菜单箭头全自己画；
点击、失焦关闭、Esc、键盘导航、滚轮也全自己处理。

已知行为差异（有意保留，不修）：
- 光标移出整条菜单链不会自动关闭（系统菜单有移动容忍超时）——点外部/
  失焦才关；子菜单会留在屏幕上等用户处理。
- 「打开设置」先归还焦点再激活主窗，视觉上焦点跳两跳（功能正确）。

调用约束：只在托盘线程调用（窗口创建与消息循环必须同线程）。
菜单数据与 tray.py provider 同构：
  [("sep",),
   ("item", text, callback, {"checked":, "radio":, "enabled":,
                             "default":, "submenu": [...]})]
text/checked/enabled 可传函数，打开菜单时求值。
"""
import ctypes
import ctypes.wintypes as wt
import os

WM_DESTROY = 0x0002
WM_KILLFOCUS = 0x0008
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_ACTIVATE = 0x0006
WM_MOUSEACTIVATE = 0x0021
WM_KEYDOWN = 0x0100
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEWHEEL = 0x020A
WM_MOUSELEAVE = 0x02A3
TME_LEAVE = 0x00000002
WA_INACTIVE = 0
MA_ACTIVATE = 1
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
VK_RETURN, VK_ESCAPE = 0x0D, 0x1B

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOW = 5
SRCCOPY = 0x00CC0020
DT_LEFT, DT_VCENTER, DT_SINGLELINE, DT_NOPREFIX = 0x0, 0x4, 0x20, 0x800
DT_END_ELLIPSIS = 0x8000
PS_SOLID, NULL_PEN, NULL_BRUSH = 0, 8, 5
IDC_ARROW = 32512
MONITOR_DEFAULTTONEAREST = 2

# 视觉（对齐 ZCode 深色卡片：近黑底、大行高、分组留白）
_BG = (0x1E, 0x1E, 0x1E)
_BORDER = (0x38, 0x38, 0x38)
_FG = (0xE4, 0xE4, 0xE4)
_FG_B = (0xF5, 0xF5, 0xF5)
_FG_DIM = (0x86, 0x86, 0x86)
_HOVER = (0x2E, 0x2E, 0x2E)
_LINE = (0x3B, 0x3B, 0x3B)
_CHECK = (0xDD, 0xDD, 0xDD)

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_g32 = ctypes.windll.gdi32
# 独立 user32 句柄：main.py 也设置全局 windll.user32.GetMonitorInfoW.argtypes
# （它自己的 POINTER(_MONITORINFO)），ctypes 函数对象是进程共享的，两边互相
# 覆盖会报 "expected LP__MONITORINFO instead of pointer"。这里单开句柄，
# 函数对象独立、argtypes 互不影响。
_u32m = ctypes.WinDLL("user32")

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT,
                             ctypes.c_void_p, ctypes.c_void_p)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", ctypes.c_void_p), ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL),
                ("rcPaint", wt.RECT), ("fRestore", wt.BOOL),
                ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


class _TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD),
                ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]


# ---- Win32 签名（argtypes 成对铁律：64 位句柄按 int 推断会截断）----
_u32.RegisterClassExW.argtypes = (ctypes.c_void_p,)
_u32.RegisterClassExW.restype = wt.ATOM
_u32.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wt.HWND, ctypes.c_void_p,
                                 wt.HINSTANCE, ctypes.c_void_p)
_u32.CreateWindowExW.restype = wt.HWND
_u32.DestroyWindow.argtypes = (wt.HWND,)
_u32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
_u32.SetForegroundWindow.argtypes = (wt.HWND,)
_u32.SetFocus.argtypes = (wt.HWND,)
_u32.GetForegroundWindow.restype = wt.HWND
_u32.GetCursorPos.argtypes = (ctypes.c_void_p,)
_u32.GetMessageW.argtypes = (ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT)
_u32.GetMessageW.restype = ctypes.c_int
_u32.TranslateMessage.argtypes = (ctypes.c_void_p,)
_u32.DispatchMessageW.argtypes = (ctypes.c_void_p,)
_u32.DispatchMessageW.restype = ctypes.c_longlong
_u32.PostQuitMessage.argtypes = (ctypes.c_int,)
_u32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, ctypes.c_void_p,
                                ctypes.c_void_p)
_u32.DefWindowProcW.restype = ctypes.c_longlong
_u32.InvalidateRect.argtypes = (wt.HWND, ctypes.c_void_p, wt.BOOL)
_u32.BeginPaint.argtypes = (wt.HWND, ctypes.c_void_p)
_u32.BeginPaint.restype = wt.HDC
_u32.EndPaint.argtypes = (wt.HWND, ctypes.c_void_p)
_u32.DrawTextW.argtypes = (wt.HDC, wt.LPCWSTR, ctypes.c_int,
                           ctypes.c_void_p, wt.UINT)
_u32.DrawTextW.restype = ctypes.c_int
_u32.FillRect.argtypes = (wt.HDC, ctypes.c_void_p, wt.HBRUSH)
_u32.FillRect.restype = ctypes.c_int
_u32.GetDpiForWindow.argtypes = (wt.HWND,)
_u32.GetDpiForWindow.restype = wt.UINT
_u32.GetSystemMetrics.argtypes = (ctypes.c_int,)
_u32.GetSystemMetrics.restype = ctypes.c_int
_u32.TrackMouseEvent.argtypes = (ctypes.c_void_p,)
_u32.TrackMouseEvent.restype = wt.BOOL
try:
    _shcore = ctypes.WinDLL("shcore")
    _shcore.GetDpiForMonitor.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                         ctypes.POINTER(wt.UINT),
                                         ctypes.POINTER(wt.UINT))
    _shcore.GetDpiForMonitor.restype = ctypes.c_long
except Exception:
    _shcore = None
_u32.LoadCursorW.argtypes = (wt.HINSTANCE, wt.LPCWSTR)
_u32.LoadCursorW.restype = wt.HANDLE
_g32.CreateRoundRectRgn.argtypes = (ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int)
_g32.CreateRoundRectRgn.restype = ctypes.c_void_p
_u32.SetWindowRgn.argtypes = (wt.HWND, ctypes.c_void_p, wt.BOOL)
_u32m.MonitorFromPoint.argtypes = (wt.POINT, wt.DWORD)
_u32m.MonitorFromPoint.restype = ctypes.c_void_p
_u32m.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_MONITORINFO))
_u32m.GetMonitorInfoW.restype = wt.BOOL
_g32.CreateSolidBrush.argtypes = (wt.COLORREF,)
_g32.CreateSolidBrush.restype = ctypes.c_void_p
_g32.CreatePen.argtypes = (ctypes.c_int, ctypes.c_int, wt.COLORREF)
_g32.CreatePen.restype = ctypes.c_void_p
_g32.CreateFontW.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wt.DWORD, wt.DWORD,
                             wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                             wt.DWORD, wt.DWORD, wt.LPCWSTR)
_g32.CreateFontW.restype = ctypes.c_void_p
_g32.SelectObject.argtypes = (wt.HDC, ctypes.c_void_p)
_g32.SelectObject.restype = ctypes.c_void_p
_g32.DeleteObject.argtypes = (ctypes.c_void_p,)
_g32.DeleteObject.restype = wt.BOOL
_g32.GetStockObject.argtypes = (ctypes.c_int,)
_g32.GetStockObject.restype = ctypes.c_void_p
_g32.MoveToEx.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int,
                          ctypes.c_void_p)
_g32.MoveToEx.restype = wt.BOOL
_g32.LineTo.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int)
_g32.LineTo.restype = wt.BOOL
_g32.Ellipse.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_int)
_g32.Ellipse.restype = wt.BOOL
_g32.Polygon.argtypes = (wt.HDC, ctypes.POINTER(wt.POINT), ctypes.c_int)
_g32.Polygon.restype = wt.BOOL
_g32.SetBkMode.argtypes = (wt.HDC, ctypes.c_int)
_g32.SetTextColor.argtypes = (wt.HDC, wt.COLORREF)
_g32.CreateCompatibleDC.argtypes = (wt.HDC,)
_g32.CreateCompatibleDC.restype = wt.HDC
_g32.CreateCompatibleBitmap.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int)
_g32.CreateCompatibleBitmap.restype = wt.HANDLE
_g32.DeleteDC.argtypes = (wt.HDC,)
_g32.BitBlt.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                        ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int,
                        wt.DWORD)
_g32.RoundRect.argtypes = (wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_int)
_g32.GetTextExtentPoint32W.argtypes = (wt.HDC, wt.LPCWSTR, ctypes.c_int,
                                       ctypes.c_void_p)
_g32.GetTextExtentPoint32W.restype = wt.BOOL
_k32.GetModuleHandleW.argtypes = (wt.LPCWSTR,)
_k32.GetModuleHandleW.restype = wt.HINSTANCE


def _rgb(rgb):
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


def _log(fmt, *a):
    try:
        import logging
        logging.getLogger("serialconsole.tray").info(fmt, *a)
    except Exception:
        pass


def _val(v, *args):
    if callable(v):
        try:
            return v(*args)
        except Exception:
            return None
    return v


# ---- 进程级 GDI 资源（按 DPI 缓存，托盘线程单线程使用）----
_GFX = {}
_CLASS_ATOM = None
_WNDPROC_REF = None
_MENUS = {}          # hwnd -> _Menu（当前打开的所有层）
_PREV_FG = None      # 菜单打开前的前台窗口（关闭时归还）
_PENDING = None      # 选中项回调（菜单链全部关闭后由 show_menu 返回）
_CLOSING = False


def _gfx(scale):
    key = round(scale, 3)
    g = _GFX.get(key)
    if g:
        return g
    h = -int(10.0 * 96 * scale / 72)     # 10pt，负值=按字符高
    face = "Microsoft YaHei UI"
    g = {
        "font": _g32.CreateFontW(h, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face),
        "font_b": _g32.CreateFontW(h, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0,
                                   face),
        "brush": {}, "pen": {},
    }
    _GFX[key] = g
    return g


def _trim_gfx():
    """只保留最近 3 个 DPI 档（显示器热插拔不会无限累积 GDI 对象）。
    仅在菜单链全部关闭后调用，正在显示的档不会被释放。"""
    if len(_GFX) <= 3:
        return
    for k in list(_GFX)[:-3]:
        g = _GFX.pop(k, None)
        if not g:
            continue
        handles = [g.get("font"), g.get("font_b")]
        handles += list(g.get("brush", {}).values())
        handles += list(g.get("pen", {}).values())
        for h in handles:
            if h:
                try:
                    _g32.DeleteObject(h)
                except Exception:
                    pass


def _brush(g, rgb):
    b = g["brush"].get(rgb)
    if not b:
        b = g["brush"][rgb] = _g32.CreateSolidBrush(_rgb(rgb))
    return b


def _pen(g, rgb, width=1):
    key = (rgb, width)
    p = g["pen"].get(key)
    if not p:
        p = g["pen"][key] = _g32.CreatePen(PS_SOLID, int(width), _rgb(rgb))
    return p


def _text_w(dc, font, text):
    old = _g32.SelectObject(dc, font)
    size = wt.SIZE()
    # 长度必须显式给（GetTextExtentPoint32W 不支持 -1，会 ERROR_INVALID_PARAMETER
    # 返回 0 → 菜单宽度退化成最小值，长文本全被省略号截断）
    _g32.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(size))
    _g32.SelectObject(dc, old)
    return int(size.cx)


def _build_rows(items):
    """provider 描述树 → 绘制行模型；函数值在此刻求值。"""
    rows = []
    for it in items or []:
        if isinstance(it, tuple) and it and it[0] == "sep":
            rows.append({"sep": True})
            continue
        if not (isinstance(it, tuple) and len(it) >= 3):
            continue
        text, cb = it[1], it[2]
        opts = it[3] if len(it) > 3 and isinstance(it[3], dict) else {}
        row = {
            "text": str(_val(text) or ""),
            "cb": cb,
            "enabled": bool(_val(opts.get("enabled", True))),
            "checked": bool(_val(opts.get("checked"))),
            "radio": bool(opts.get("radio")),
            "default": bool(opts.get("default")),
        }
        sub = opts.get("submenu")
        if sub:
            row["sub"] = _build_rows(sub)
        rows.append(row)
    # 首尾/连续分隔符合并（provider 段失败时可能出现空段）
    clean = []
    for r in rows:
        if r.get("sep") and (not clean or clean[-1].get("sep")):
            continue
        clean.append(r)
    while clean and clean[-1].get("sep"):
        clean.pop()
    return clean


def _dpi_scale(hwnd):
    try:
        dpi = _u32.GetDpiForWindow(hwnd) or 96
    except Exception:
        dpi = 96
    return dpi / 96.0


def _screen_scale(pt, owner_hwnd):
    """光标所在显示器的 DPI。多屏不同缩放时不能拿托盘隐藏窗（主屏）
    的 DPI，否则副屏菜单字体缩水一圈；失败落回 owner 的 DPI。"""
    if _shcore is not None:
        try:
            mon = _u32m.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            dx, dy = wt.UINT(), wt.UINT()
            if mon and _shcore.GetDpiForMonitor(
                    mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 \
                    and dx.value:
                return dx.value / 96.0
        except Exception:
            pass
    return _dpi_scale(owner_hwnd)


def _ensure_class():
    global _CLASS_ATOM, _WNDPROC_REF
    if _CLASS_ATOM:
        return _CLASS_ATOM
    wc = _WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
    _WNDPROC_REF = WNDPROC(_menu_wndproc)
    wc.lpfnWndProc = _WNDPROC_REF
    wc.hInstance = _k32.GetModuleHandleW(None)
    wc.hCursor = _u32.LoadCursorW(None, ctypes.c_wchar_p(IDC_ARROW))
    wc.lpszClassName = "SerialConsoleProMenu%d" % os.getpid()
    _CLASS_ATOM = _u32.RegisterClassExW(ctypes.byref(wc))
    return _CLASS_ATOM


class _Menu(object):
    def __init__(self, rows, scale, parent=None, parent_index=-1):
        self.rows = rows
        self.scale = scale
        self.parent = parent
        self.parent_index = parent_index
        self.child = None
        self._track = False      # WM_MOUSELEAVE 是否已 arm
        self.hwnd = None
        self.x = self.y = 0
        self.w = self.h = 0
        self.content_h = 0
        self.scroll = 0
        self.hover = -1
        self.g = _gfx(scale)
        s = scale
        self.row_h = int(30 * s)
        self.sep_h = int(10 * s)
        self.pad_y = int(5 * s)
        self.pad_x = int(14 * s)
        self.check_w = int(17 * s)
        self.radius = int(9 * s)
        self._measure()

    # ---- 测量 ----
    def _measure(self):
        s = self.scale
        g = self.g
        dc = _g32.CreateCompatibleDC(None)
        try:
            # 勾选区只在菜单确实含勾选/单选项时预留；否则文字与分隔线对齐
            need_check = any((not r.get("sep")) and
                             (r.get("checked") or r.get("radio"))
                             for r in self.rows)
            self.check_w = int(17 * s) if need_check else 0
            maxw = 0
            for r in self.rows:
                if r.get("sep"):
                    continue
                tw = _text_w(dc, g["font_b"] if r.get("default")
                             else g["font"], r["text"])
                right = self.pad_x + (int(15 * s) if r.get("sub") else 0)
                # +4px 余量：GetTextExtent 与实际绘制留白口径略差，防末字截断
                maxw = max(maxw, self.pad_x + self.check_w + tw + right
                           + int(6 * s))
        finally:
            _g32.DeleteDC(dc)
        self.w = max(int(184 * s), maxw)
        # top 是内容坐标（不含上下 padding）；绘制/命中/子菜单位置
        # 各加一次 pad_y，避免双重偏移（子菜单曾整体下错位 10px）
        y = 0
        for r in self.rows:
            r["top"] = y
            r["h"] = self.sep_h if r.get("sep") else self.row_h
            y += r["h"]
        self.content_h = y + self.pad_y * 2

    def _row_at(self, cy):
        """内容坐标 → 行下标（越界/分隔/禁用返回 -1）。"""
        cy = cy - self.pad_y + self.scroll
        for i, r in enumerate(self.rows):
            if r.get("sep") or not r.get("enabled", True):
                continue
            if r["top"] <= cy < r["top"] + r["h"]:
                return i
        return -1

    def _first_item(self):
        for i, r in enumerate(self.rows):
            if not r.get("sep") and r.get("enabled", True):
                return i
        return -1

    def _step(self, idx, d):
        n = len(self.rows)
        i = idx
        for _ in range(n + 1):
            i = (i + d) % n
            if not self.rows[i].get("sep") and self.rows[i].get("enabled", True):
                return i
        return idx

    # ---- 显示 ----
    def _work_area(self):
        try:
            pt = wt.POINT(self.x, self.y)
            hmon = _u32m.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if hmon and _u32m.GetMonitorInfoW(hmon, ctypes.pointer(mi)):
                return mi.rcWork
        except Exception:
            _log("取工作区失败（回主屏边界）: %s", repr(_exc()))
        # 兜底：主屏物理边界（菜单仍可用，副屏时只是不感知任务栏）
        return wt.RECT(0, 0, _u32.GetSystemMetrics(0), _u32.GetSystemMetrics(1))

    def show_at(self, x, y, right_align=True, bottom_align=True):
        """在屏幕坐标 (x,y) 打开。托盘菜单右/上对齐光标（原 TrackPopupMenu
        习惯），子菜单左侧对齐父项右侧。"""
        s = self.scale
        self.x, self.y = x, y
        work = self._work_area()
        max_h = max(self.row_h * 3, work.bottom - work.top - int(16 * s))
        if self.content_h > max_h:
            self.h = max_h
        else:
            self.h = self.content_h
        px = x - self.w if right_align else x
        py = y - self.h if bottom_align else y
        if px < work.left + 4:
            px = x if right_align else x
        if px + self.w > work.right - 4:
            px = work.right - 4 - self.w
        if py < work.top + 4:
            py = y if bottom_align else y
        if py + self.h > work.bottom - 4:
            py = work.bottom - 4 - self.h
        if px < work.left + 4:
            px = work.left + 4
        if py < work.top + 4:
            py = work.top + 4
        self.x, self.y = px, py
        atom = _ensure_class()
        hinst = _k32.GetModuleHandleW(None)
        self.hwnd = _u32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
            ctypes.c_wchar_p(atom), None, WS_POPUP,
            int(px), int(py), int(self.w), int(self.h),
            self.parent.hwnd if self.parent else None,
            None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError()
        _MENUS[self.hwnd] = self
        try:
            rgn = _g32.CreateRoundRectRgn(0, 0, int(self.w) + 1,
                                          int(self.h) + 1,
                                          self.radius * 2, self.radius * 2)
            if rgn:
                _u32.SetWindowRgn(self.hwnd, rgn, True)
        except Exception:
            pass
        _u32.ShowWindow(self.hwnd, SW_SHOW)
        _u32.SetForegroundWindow(self.hwnd)
        _u32.SetFocus(self.hwnd)

    # ---- 交互 ----
    def _on_move(self, cy):
        if not self._track:
            tm = _TRACKMOUSEEVENT()
            tm.cbSize = ctypes.sizeof(_TRACKMOUSEEVENT)
            tm.dwFlags = TME_LEAVE
            tm.hwndTrack = self.hwnd
            try:
                _u32.TrackMouseEvent(ctypes.byref(tm))
                self._track = True
            except Exception:
                pass
        idx = self._row_at(cy)
        if idx != self.hover:
            self.hover = idx
            _u32.InvalidateRect(self.hwnd, None, False)
        if self.child and idx != self.child.parent_index:
            self._close_child()

    def _on_click(self, cy):
        idx = self._row_at(cy)
        if idx < 0:
            # 禁用行/分隔线/空白：纹丝不动（系统菜单同款）；外部点击由失活关闭
            return
        row = self.rows[idx]
        if row.get("sub"):
            if self.child and self.child.parent_index == idx:
                self._close_child()
            else:
                self._open_sub(idx)
            return
        _choose(row)

    def _open_sub(self, idx):
        self._close_child()
        row = self.rows[idx]
        child = _Menu(row["sub"], self.scale, parent=self, parent_index=idx)
        s = self.scale
        px = self.x + self.w - int(2 * s)
        py = self.y + self.pad_y + row["top"] - self.scroll
        work = self._work_area()
        if px + child.w > work.right - 4:
            px = self.x - child.w + int(2 * s)
        child.show_at(px, py, right_align=False, bottom_align=False)
        self.child = child
        _u32.InvalidateRect(self.hwnd, None, False)

    def _close_child(self):
        if self.child:
            c = self.child
            self.child = None
            try:
                _u32.DestroyWindow(c.hwnd)
            except Exception:
                pass

    def _on_key(self, vk):
        if vk == VK_ESCAPE:
            if self.parent is not None:
                p = self.parent
                p._close_child()
                _u32.SetForegroundWindow(p.hwnd)
                _u32.SetFocus(p.hwnd)
            else:
                _close_all()
            return
        if vk == VK_LEFT:
            if self.parent is not None:
                p = self.parent
                p._close_child()
                _u32.SetForegroundWindow(p.hwnd)
                _u32.SetFocus(p.hwnd)
            return
        if vk in (VK_DOWN, VK_UP):
            idx = self._first_item() if self.hover < 0 else \
                self._step(self.hover, 1 if vk == VK_DOWN else -1)
            self.hover = idx
            self._ensure_visible(idx)
            _u32.InvalidateRect(self.hwnd, None, False)
            return
        if vk == VK_RIGHT:
            idx = self.hover
            if 0 <= idx < len(self.rows) and self.rows[idx].get("sub"):
                self._open_sub(idx)
            return
        if vk == VK_RETURN and 0 <= self.hover < len(self.rows):
            row = self.rows[self.hover]
            if row.get("sub"):
                self._open_sub(self.hover)
            elif row.get("enabled", True):
                _choose(row)

    def _ensure_visible(self, idx):
        if not (0 <= idx < len(self.rows)):
            return
        r = self.rows[idx]
        top = self.pad_y + r["top"] - self.scroll
        bottom = top + r["h"]
        if top < self.pad_y:
            self.scroll = max(0, r["top"] - self.pad_y)
        elif bottom > self.h - self.pad_y:
            self.scroll = min(self.content_h - self.h,
                              r["top"] + r["h"] + self.pad_y - self.h)
        self.scroll = max(0, min(self.scroll, self.content_h - self.h))

    def _wheel(self, delta):
        if self.content_h <= self.h:
            return
        self.scroll = max(0, min(self.content_h - self.h,
                                 self.scroll - int(delta / 120.0
                                                   * self.row_h * 2)))
        # 与 WM_MOUSELEAVE 同口径：子菜单开着时父项高亮是其从属指示，
        # 滚动父菜单不能把它灭掉（同一个保护的两个入口）。
        if self.child is None:
            self.hover = -1
        _u32.InvalidateRect(self.hwnd, None, False)

    # ---- 绘制 ----
    def paint(self):
        ps = _PAINTSTRUCT()
        hdc = _u32.BeginPaint(self.hwnd, ctypes.byref(ps))
        mem = None
        bmp = None
        old = None
        try:
            mem = _g32.CreateCompatibleDC(hdc)
            bmp = _g32.CreateCompatibleBitmap(hdc, self.w, self.h)
            old = _g32.SelectObject(mem, bmp)
            self._draw(mem)
            _g32.BitBlt(hdc, 0, 0, self.w, self.h, mem, 0, 0, SRCCOPY)
        finally:
            if mem:
                if old:
                    _g32.SelectObject(mem, old)
                if bmp:
                    _g32.DeleteObject(bmp)
                _g32.DeleteDC(mem)
            _u32.EndPaint(self.hwnd, ctypes.byref(ps))

    def _draw(self, dc):
        s = self.scale
        g = self.g
        w, h = self.w, self.h
        # 底：圆角卡片 + 1px 边框
        bg, pen = _brush(g, _BG), _pen(g, _BORDER, 1)
        _g32.SelectObject(dc, bg)
        _g32.SelectObject(dc, pen)
        _g32.RoundRect(dc, 0, 0, w, h, self.radius * 2, self.radius * 2)
        _g32.SetBkMode(dc, 1)
        np = _g32.GetStockObject(NULL_PEN)
        for idx, r in enumerate(self.rows):
            y = self.pad_y + r["top"] - self.scroll
            if y > h or y + r["h"] < 0:
                continue
            if r.get("sep"):
                if 0 <= y + r["h"] // 2 < h:
                    ly = y + r["h"] // 2
                    ln = wt.RECT(self.pad_x + self.check_w, ly,
                                 w - self.pad_x, ly + 1)
                    _u32.FillRect(dc, ctypes.byref(ln), _brush(g, _LINE))
                continue
            enabled = r.get("enabled", True)
            if idx == self.hover and enabled:
                _g32.SelectObject(dc, _brush(g, _HOVER))
                _g32.SelectObject(dc, np)
                _g32.RoundRect(dc, int(5 * s), y + int(2 * s),
                               w - int(5 * s), y + self.row_h - int(2 * s),
                               int(6 * s) * 2, int(6 * s) * 2)
                _g32.SelectObject(dc, bg)
                _g32.SelectObject(dc, pen)
            fnt = g["font_b"] if r.get("default") else g["font"]
            _g32.SelectObject(dc, fnt)
            if not enabled:
                fg = _FG_DIM
            elif idx == self.hover:
                fg = _FG_B
            else:
                fg = _FG
            _g32.SetTextColor(dc, _rgb(fg))
            rt = wt.RECT(self.pad_x + self.check_w, y,
                         w - self.pad_x - (int(15 * s) if r.get("sub") else 0),
                         y + self.row_h)
            _u32.DrawTextW(dc, r["text"], -1, ctypes.byref(rt),
                           DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX
                           | DT_END_ELLIPSIS)
            cy = y + self.row_h // 2
            cx = self.pad_x + int(8 * s)
            if r.get("checked") and enabled:
                if r.get("radio"):
                    _g32.SelectObject(dc, _brush(g, _CHECK))
                    _g32.SelectObject(dc, np)
                    rr = max(3, int(3.5 * s))
                    _g32.Ellipse(dc, cx - rr, cy - rr, cx + rr, cy + rr)
                else:
                    ck = _pen(g, _CHECK, max(1, int(2 * s)))
                    _g32.SelectObject(dc, ck)
                    _g32.MoveToEx(dc, cx - int(5 * s), cy, None)
                    _g32.LineTo(dc, cx - int(1 * s), cy + int(4 * s))
                    _g32.LineTo(dc, cx + int(5 * s), cy - int(4 * s))
            if r.get("sub"):
                ax = w - self.pad_x - int(5 * s)
                pts = (wt.POINT * 3)(
                    (ax, cy - int(4 * s)), (ax, cy + int(4 * s)),
                    (ax + int(5 * s), cy))
                _g32.SelectObject(dc, _brush(g, fg))
                _g32.SelectObject(dc, np)
                _g32.Polygon(dc, pts, 3)


def _choose(row):
    global _PENDING
    _PENDING = row.get("cb")
    _close_all()


def _close_all(restore_focus=True):
    """关闭整条菜单链。restore_focus=True 时归还打开前的前台窗口
    （自绘窗口抢过 SetForegroundWindow，不归还会让用户原窗口一直灰着）。
    失活/外部点击路径传 False——前台已经给了用户点的窗口，不能再抢。"""
    global _CLOSING, _PREV_FG
    if _CLOSING:
        return
    _CLOSING = True
    try:
        # 顺序关键：先归还再销毁。销毁前台窗口的瞬间系统会把前台转给
        # z 序下一个窗口，本进程可能从此丧失前台权限——之后再
        # SetForegroundWindow 会被前台锁静默拒绝（返回 FALSE）。
        if restore_focus and _PREV_FG:
            try:
                if _u32.IsWindow(_PREV_FG) and \
                        not _u32.SetForegroundWindow(_PREV_FG):
                    _log("归还前台失败（前台锁），焦点可能漂移")
            except Exception:
                pass
        for m in list(_MENUS.values()):
            try:
                _u32.DestroyWindow(m.hwnd)
            except Exception:
                pass
        _MENUS.clear()
    finally:
        _CLOSING = False
    _PREV_FG = None
    _trim_gfx()


def _menu_wndproc(hwnd, msg, wparam, lparam):
    m = _MENUS.get(hwnd)
    try:
        # WNDPROC 形参是 c_void_p：ctypes 可能给 None/int，统一成 int
        wparam = int(wparam or 0)
        lparam = int(lparam or 0)
        if not m:
            return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_PAINT:
            m.paint()
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return MA_ACTIVATE
        if msg == WM_MOUSEMOVE:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            m._on_move(y)
            return 0
        if msg == WM_LBUTTONUP:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            m._on_click(y)
            return 0
        if msg == WM_MOUSELEAVE:
            m._track = False
            # 光标从父菜单移进子菜单也会触发父窗 MOUSELEAVE——此时子菜单
            # 开着，父项要保持高亮指示从属关系（系统菜单/ZCode 同款）。
            if m.child is None and m.hover != -1:
                m.hover = -1
                _u32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_MOUSEWHEEL:
            delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
            m._wheel(delta)
            return 0
        if msg == WM_KEYDOWN:
            m._on_key(wparam & 0xFFFF)
            return 0
        if msg == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE and not _CLOSING:
                fg = _u32.GetForegroundWindow()
                if fg not in _MENUS:
                    _close_all(restore_focus=False)
            return 0
        if msg == WM_DESTROY:
            _MENUS.pop(hwnd, None)
            return 0
        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)
    except Exception:
        _log("菜单窗口异常 msg=%s: %s", msg, repr(_exc()))
        try:
            return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            return 0


def _exc():
    import sys
    return sys.exc_info()[1]


def close_all():
    """外部（再次右键/退出）关掉当前菜单链。"""
    _close_all(restore_focus=False)


def show_menu(owner_hwnd, items):
    """模态显示菜单，返回被点击项的回调（未选择返回 None）。

    只允许在托盘线程调用；内部消息循环会消费本线程消息（含 WM_QUIT，
    收到后重投递并返回）。"""
    global _PENDING, _PREV_FG
    keep_prev = _PREV_FG
    if _MENUS:
        _close_all(restore_focus=False)
    rows = _build_rows(items)
    if not rows:
        return None
    pt = wt.POINT()
    _u32.GetCursorPos(ctypes.byref(pt))
    scale = _screen_scale(pt, owner_hwnd)
    root = _Menu(rows, scale)
    # 重入（菜单已开时再右键）：沿用旧菜单打开前记录的前台；旧菜单销毁
    # 过程中前台已漂移，不能再拿 GetForegroundWindow 当“原前台”。
    _PREV_FG = keep_prev if keep_prev else _u32.GetForegroundWindow()
    try:
        root.show_at(pt.x, pt.y)
    except Exception:
        _log("菜单显示失败（上抛由 tray 兜底）: %s", repr(_exc()))
        _close_all(restore_focus=False)
        raise
    _PENDING = None
    msg = wt.MSG()
    while _MENUS:
        r = _u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if r == 0:
            _close_all(restore_focus=False)   # 应用退出，无需归还前台
            _u32.PostQuitMessage(msg.wParam)
            break
        if r == -1:
            _log("菜单消息循环错误")
            _close_all(restore_focus=False)
            break
        _u32.TranslateMessage(ctypes.byref(msg))
        _u32.DispatchMessageW(ctypes.byref(msg))
    # 取出即清空：托盘右键重入（菜单已开时再右键）会产生嵌套 show_menu，
    # 内层选中的回调不能在外层返回时被 _fire 第二次。
    cb, _PENDING = _PENDING, None
    return cb
