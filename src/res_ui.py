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


def _search_dirs():
    """自动找包的候选目录（a343R 第14轮 P1-3：抽出来供测试打桩）。

    原实现把四个目录内联在 autofind_fcpk 里，测试只能桩 _app_dir，
    仍会读真实 `~/Desktop`、`~/Downloads` —— 发布者桌面放着资源包是
    本项目的正常工作流，于是「判据固化」的测试在同事机上必假红。
    """
    base = _app_dir()
    return (base, os.path.dirname(base),
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.path.expanduser("~"), "Downloads"))


def autofind_fcpk():
    """文件对话框不可用时的兜底：在常见位置按名找 *.fcpk。

    a325R（第2轮对抗审 P1）：原实现取 mtime 最新的任意 *.fcpk——同目录放着
    `前端控制台-资源包.fcpk`（全量）与 `前端控制台-资源包-拓展.fcpk`（子集，
    通常最后打、mtime 更新）时，会自动选中子集包 → 缺 WebView2/.NET 的新机器
    装完仍缺 → 闸门再拦 → 死循环。优先主包（`-资源包.fcpk`），子集包（
    `-资源包-*.fcpk`）只在没有主包时才用。"""
    import glob
    # a339R（第10轮 P3-2）：导入提到循环外一次性做——原实现写在双层 for 内，
    # 一个坏 pyd 会让「所有目录都不可用」且只表现为"你把包放错地方了"。
    # a341R（第12轮）：改用 pkg_rank 排序——原实现只分 main/sub 两档、同档按
    # mtime 取胜，于是 `资源包-副本副本`（新）会顶掉真主包、备份包同理。
    try:
        from src.pkgname import pkg_rank as _rk, APP_NAME as _AN
    except Exception:
        return ""
    cands = []
    for d in _search_dirs():
        if d and os.path.isdir(d):
            for p in glob.glob(os.path.join(d, "*.fcpk")):
                # a334R（第5轮 P2-1）：名字判定必须用 basename——原实现拿
                # 完整路径做 `"资源包" in p`，工具解压在含"资源包"的目录里时，
                # 同目录别家的 other-tool.fcpk 也会被选中。
                _bn = os.path.basename(p).lower()
                # a341R：闸门也要前缀过滤，否则同目录别家的资源包会被选走。
                # a342R（第13轮 P2-1）：但**不**过滤备份——闸门的目标是
                # "找到能用的包"，唯一一份包叫 `-备份` 时必须还能装。
                # a343R（第14轮 P2-5）：目录也可能叫 *.fcpk（解压残留/
                # OneDrive 占位），必须验 isfile，否则闸门选中目录后
                # fcpk.is_fcpk 打不开
                if not os.path.isfile(p):
                    continue
                _r = _rk(_bn, require_prefix=_AN)
                if _r < 0:
                    continue
                cands.append((_r, p))
    if not cands:
        return ""
    # 先按 rank 降序、再按 mtime 降序（rank 高者不受 mtime 影响）
    # a342R（第13轮 P2-2）：getmtime 必须容错——Desktop/Downloads 常被 OneDrive
    # 重定向或杀软隔离，glob 与 stat 之间文件消失会让整条闸门兜底路径抛异常，
    # 用户看到的是"复查运行环境"而不是"包找不到"。
    def _mt(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    def _sz(p):
        # a348R（第19轮）：同档决胜用大小而非 mtime——副本/备份与原件字节
        # 相同，按 mtime 会被它们顶掉（第7~18轮反复复发的同一类事故）
        try:
            return os.path.getsize(p)
        except OSError:
            return 0
    cands = [c for c in cands if os.path.exists(c[1])]
    if not cands:
        return ""
    cands.sort(key=lambda t: (t[0], _sz(t[1]), _mt(t[1])), reverse=True)
    return cands[0][1]


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
            # 对抗审实锤：title 形参从未传入（恒 None）→ 对话框无标题
            return (f(self._p, None, None, PROGDLG_NORMAL, None,
                      (title or None), 0)
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
            # 对抗审实锤（每次调用都访问违例被吞）：SetLine 签名是
            # (DWORD iLine, LPCWSTR pwzText, BOOL fCompactPath,
            #  VARIANT_BOOL* PathRes)——早前漏传首参 iLine，文本被当行号
            # 解引用 → 0x1 读违例，「当前文件」从未显示过
            self._call(10, ctypes.c_long, wintypes.DWORD, wintypes.LPCWSTR,
                       wintypes.BOOL, ctypes.c_void_p)(
                self._p, 1, t, keep, None)
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

    def release(self):
        """IUnknown::Release + CoUninitialize（对抗审 P3：COM 生命周期收尾）。"""
        if not self._ok:
            return
        try:
            self._call(2, ctypes.c_ulong)(self._p)
        except Exception:
            pass
        self._p = ctypes.c_void_p()
        self._ok = False
        try:
            ctypes.windll.ole32.CoUninitialize()
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
