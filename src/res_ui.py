# -*- coding: utf-8 -*-
"""启动资源闸门 —— Win32 原生引导 UI（v4.1）。

为什么全是 Win32 原生：WebView2 缺失时 pywebview 建不出任何窗口，
tkinter 又没打进发布包（spec 未收集，项目也从未用过）。所以只能在
MessageBoxW / GetOpenFileNameW / IProgressDialog 三条原生 API 上做。

64 位指针铁律（main.py:926 踩过）：用 ctypes 传含指针的结构体时**必须**
显式声明 argtypes/restype，否则默认按 C int 传递、指针上半截被截断，
表现为「结构体字段全是垃圾 / 拿回来的路径是空」。本模块所有 Win32
入口函数都成对声明 argtypes + restype。
"""
import ctypes
import os
import sys
from ctypes import wintypes

# ---- 常量 ----
MB_OK = 0x0
MB_OKCANCEL = 0x1
MB_YESNO = 0x4
MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
IDOK = 1
IDCANCEL = 2
IDYES = 6
IDNO = 7

MAX_PATH_ = 260
OFN_FILEMUSTEXIST = 0x00001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_NOCHANGEDIR = 0x00000008
OFN_EXPLORER = 0x00080000


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", ctypes.c_void_p),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


_user32 = ctypes.windll.user32
_comdlg32 = ctypes.windll.comdlg32

# 显式签名（64 位指针铁律）
_user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                wintypes.LPCWSTR, wintypes.UINT]
_user32.MessageBoxW.restype = ctypes.c_int
_comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
_comdlg32.GetOpenFileNameW.restype = wintypes.BOOL


def msgbox(text, title="前端控制台", flags=MB_OK | MB_ICONWARNING
           | MB_SETFOREGROUND | MB_TOPMOST):
    """原生消息框。失败静默返回 0（绝不因 UI 失败阻断安装逻辑）。"""
    try:
        return _user32.MessageBoxW(None, text, title, flags)
    except Exception:
        return 0


def pick_fcpk(initial_dir=None):
    """原生「打开文件」对话框，选 .fcpk。取消返回 ""。"""
    buf = ctypes.create_unicode_buffer(MAX_PATH_ * 4)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    # 过滤器用 \0 分隔，整体再以 \0\0 结尾
    ofn.lpstrFilter = ("前端控制台资源包 (*.fcpk)\0*.fcpk\0"
                       "所有文件 (*.*)\0*.*\0\0")
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = len(buf)
    ofn.lpstrTitle = "选择离线资源包（.fcpk）"
    ofn.lpstrDefExt = "fcpk"
    if initial_dir and os.path.isdir(initial_dir):
        ofn.lpstrInitialDir = initial_dir
    ofn.Flags = (OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
                 | OFN_NOCHANGEDIR | OFN_EXPLORER)
    if not _comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return ""
    return buf.value or ""


def autofind_fcpk():
    """文件对话框不可用时的兜底：在常见位置按名找 *.fcpk（取最新一个）。"""
    import glob
    cands = []
    base = _app_dir()
    for d in (base, os.path.dirname(base),
              os.path.join(os.path.expanduser("~"), "Desktop"),
              os.path.join(os.path.expanduser("~"), "Downloads")):
        if d and os.path.isdir(d):
            cands.extend(glob.glob(os.path.join(d, "*.fcpk")))
    if not cands:
        return ""
    cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0]


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ 进度条

# IProgressDialog 的 IID/CLSID
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(s):
    import uuid
    u = uuid.UUID(s)
    g = _GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    for i in range(8):
        g.Data4[i] = u.bytes[8 + i]
    return g


_CLSID_PROGRESS = "{F8383852-FCD3-11D1-A6B9-006097DF5BD4}"
_IID_PROGRESS = "{EBBC7C04-315E-11D2-B62F-006097DF5BD4}"
PROGDLG_NORMAL = 0x0
PROGDLG_MODAL = 0x1


class _Progress:
    """IProgressDialog 封装。用 vtable 直接调用（不引入 comtypes）。

    槽位：3=StartProgressDialog 4=StopProgressDialog 5=SetTitle
          7=HasUserCancelled 9=SetProgress64 10=SetLine
    注意：COM 对象必须在本线程创建与使用（STA），且只在主线程外的一个
    固定线程里用——因此本类不做跨线程保护，调用方负责。
    """

    def __init__(self):
        self._p = ctypes.c_void_p()
        self._ok = False
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(_GUID), ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
            ole32.CoInitializeEx(None, 2)          # COINIT_APARTMENTTHREADED
            clsid, iid = _guid(_CLSID_PROGRESS), _guid(_IID_PROGRESS)
            hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                        ctypes.byref(iid),
                                        ctypes.byref(self._p))
            self._ok = bool(self._p.value) and (hr & 0xFFFFFFFF) == 0
        except Exception:
            self._ok = False

    def _call(self, slot, restype, *argtypes):
        vt = ctypes.cast(self._p,
                         ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vt[slot])
        return fn

    def start(self, title, line=""):
        if not self._ok:
            return False
        try:
            f = self._call(3, ctypes.c_long, wintypes.HWND, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.LPCWSTR, ctypes.c_void_p,
                           wintypes.DWORD)
            return (f(self._p, None, None, PROGDLG_NORMAL, None, None, 0)
                    & 0xFFFFFFFF) == 0
        except Exception:
            return False

    def set_title(self, t):
        if not self._ok:
            return
        try:
            self._call(5, ctypes.c_long, wintypes.LPCWSTR)(self._p, t)
        except Exception:
            pass

    def set_line(self, t, keep=0):
        if not self._ok:
            return
        try:
            self._call(10, ctypes.c_long, wintypes.LPCWSTR, wintypes.BOOL,
                       ctypes.c_void_p)(self._p, t, keep, None)
        except Exception:
            pass

    def set_progress(self, done, total):
        if not self._ok:
            return
        try:
            self._call(9, ctypes.c_long, ctypes.c_ulonglong,
                       ctypes.c_ulonglong)(self._p, int(done), int(total))
        except Exception:
            pass

    def cancelled(self):
        if not self._ok:
            return False
        try:
            return bool(self._call(7, wintypes.BOOL)(self._p))
        except Exception:
            return False

    def stop(self):
        if not self._ok:
            return
        try:
            self._call(4, ctypes.c_long)(self._p)
        except Exception:
            pass
        self._ok = False


def progress(title):
    """拿一个进度对象；创建失败返回 None（调用方退化为纯日志 + MessageBox）。"""
    p = _Progress()
    return p if (p._ok and p.start(title)) else None
