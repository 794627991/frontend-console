# -*- coding: utf-8 -*-
"""内置截图+标注（Electron 壳形态）。

架构（Snipaste 形态，2026-11-22 换壳 P4）：
- 触发（📷 按钮/全局热键）→ 主进程 spawn DPI 子进程抓屏（--snip-grab，
  物理像素落 BMP）→ SSE 广播 snip_open → Electron 壳建无边框置顶覆盖窗
- 覆层页面 web/screenshot.html + vendor js-web-screen-shot（MIT）框选/标注，
  canvas=视口=底图裁剪区，1:1 原生分辨率（插件自带 dpr 感知导出）
- 完成/另存/取消 → 页面经 preload 桥 IPC 回壳 → 壳 POST /api/snip/save
  （落 harness_uploads + CF_DIB 剪贴板）→ SSE snip_done → 前端挂附件

与旧 pywebview 形态的区别：截图窗不再是 Python 子进程，也不再需要
WebView2/.NET/pythonnet——覆层由 Electron BrowserWindow 承载。
"""
import os
import io
import json
import time
import ctypes
import threading
import subprocess
import sys

# 子进程入口（--snip-grab）时项目根不在 sys.path——同 main.py 的 _ROOT 注入
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_TMP_BMP = os.path.join(os.environ.get("TEMP", "."), "fc_snip.bmp")   # BMP 免编码
# 抓屏几何伴生文件（--snip-grab 与 BMP 同批落盘）：Electron 侧按物理坐标
# 裁剪自己的显示器区域（多显示器/混合 DPI 必需）
_TMP_GEO = os.path.join(os.environ.get("TEMP", "."), "fc_snip.bmp.geo.json")


# ---------------------------------------------------------------------------
# 子进程：DPI 感知抓屏
# ---------------------------------------------------------------------------
def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _virt_geo():
    """虚拟桌面物理矩形（调用方须已 DPI 感知）。"""
    u32 = ctypes.windll.user32
    return {"x": u32.GetSystemMetrics(76), "y": u32.GetSystemMetrics(77),
            "w": u32.GetSystemMetrics(78), "h": u32.GetSystemMetrics(79)}


def _grab_only():
    """抓屏 → BMP（PNG 编码 1920x1080 要 ~0.4s，BMP 免压缩 ~0.05s，
    localhost 传输不差这点体积）+ 物理几何 json。"""
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    img.save(_TMP_BMP)
    with open(_TMP_GEO, "w", encoding="utf-8") as f:
        json.dump(_virt_geo(), f)


def _self_exe_mode(flag="--snip-grab"):
    """抓屏子进程命令：frozen=本体 exe；源码=main.py（由 main 分发到
    --snip-grab 分支）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, flag]
    return [sys.executable, os.path.join(_ROOT, "src", "main.py"), flag]


def grab():
    """主进程：spawn --snip-grab 子进程抓屏（成功判据：产物 mtime 晚于调用时刻）。"""
    t0 = time.time()
    try:
        subprocess.run(_self_exe_mode("--snip-grab"), timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    return os.path.isfile(_TMP_BMP) and os.path.getmtime(_TMP_BMP) > t0


def read_geo():
    """读抓屏子进程落盘的虚拟桌面物理矩形（失败返回 {}）。"""
    try:
        with open(_TMP_GEO, "r", encoding="utf-8") as f:
            d = json.load(f)
        if all(k in d for k in ("x", "y", "w", "h")) and d["w"] > 0 and d["h"] > 0:
            return d
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# QQ/微信同款 hover 窗口识别（/api/snip/hittest 的数据面）
# ---------------------------------------------------------------------------
def window_at_point(x, y, skip_hwnds=()):
    """物理坐标 (x,y) 处用户视角的目标窗口可见矩形；无命中返回 None。

    不能用 WindowFromPoint——截图覆盖窗自己在最顶层盖满全屏，一问必命中
    自己。QQ/微信同款做法：EnumWindows 按 z 序自顶向下，跳过排除句柄/
    不可见/cloaked（挂起的 UWP、其他虚拟桌面）/全透明层/鼠标穿透层，
    取第一个矩形包含该点的顶层窗口。边界用 DWMWA_EXTENDED_FRAME_BOUNDS
    （可见边界，剥掉 Win10 不可见 resize 边框与投影）——这是 QQ 框窗口
    「像素级贴边」的秘密；GetWindowRect 会大一圈。

    前提：调用进程必须 per-monitor DPI aware，否则坐标全部虚拟化错位
    （main.py headless 启动时已设）。skip_hwnds 传覆盖窗自身句柄。
    """
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    dwm = ctypes.windll.dwmapi
    skip = {int(h) for h in skip_hwnds if str(h).strip().isdigit()}
    order = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lp):
        order.append(hwnd)
        return True

    if not u32.EnumWindows(_cb, 0):
        return None
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020       # 鼠标穿透层：用户看到的是它下面的窗
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    DWMWA_CLOAKED = 14
    for hwnd in order:
        if hwnd in skip or not u32.IsWindowVisible(hwnd):
            continue
        cloaked = wintypes.DWORD()
        if dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                     ctypes.byref(cloaked), 4) == 0 \
                and cloaked.value:
            continue
        ex = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TRANSPARENT:
            continue
        if ex & WS_EX_LAYERED:
            alpha = wintypes.BYTE()
            lflags = wintypes.BYTE()
            if u32.GetLayeredWindowAttributes(
                    hwnd, None, ctypes.byref(alpha),
                    ctypes.byref(lflags)) and alpha.value == 0:
                continue                 # 全透明覆盖层
        r = wintypes.RECT()
        got = False
        if dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                     ctypes.byref(r), 16) == 0:
            got = True                   # 阴影窗口/无 DWM 边界时回落 GetWindowRect
        if not got or r.right <= r.left or r.bottom <= r.top:
            if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
                continue
        w, h = int(r.right - r.left), int(r.bottom - r.top)
        if w <= 0 or h <= 0:
            continue
        if not (r.left <= x < r.right and r.top <= y < r.bottom):
            continue
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW"):
            return None                  # 桌面本体不认——点空白交给全屏点击
        return {"x": int(r.left), "y": int(r.top), "w": w, "h": h}
    return None


# ---------------------------------------------------------------------------
# 主进程：剪贴板 + 触发
# ---------------------------------------------------------------------------
def copy_png_to_clipboard(png_path):
    try:
        from PIL import Image
        img = Image.open(png_path)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        dib = buf.getvalue()[14:]   # 去 BITMAPFILEHEADER = CF_DIB 载荷

        from ctypes import wintypes
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        for fn, restype, argtypes in (
                (k32.GlobalAlloc, wintypes.HGLOBAL, [wintypes.UINT, ctypes.c_size_t]),
                (k32.GlobalLock, wintypes.LPVOID, [wintypes.HGLOBAL]),
                (k32.GlobalUnlock, None, [wintypes.HGLOBAL]),
                (k32.GlobalFree, None, [wintypes.HGLOBAL]),
                (u32.SetClipboardData, wintypes.HANDLE, [wintypes.UINT, wintypes.HANDLE])):
            if restype is not None:
                fn.restype = restype
            fn.argtypes = argtypes
        h = k32.GlobalAlloc(0x0002, len(dib))
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
            ok = bool(u32.SetClipboardData(8, h))
            if not ok:
                k32.GlobalFree(h)
            return ok
        finally:
            u32.CloseClipboard()
    except Exception:
        return False


def save_png(data_url):
    """dataURL → 落 uploads + 复制剪贴板。返回 (ok, path|err)。"""
    try:
        import base64
        raw = base64.b64decode((data_url or "").split(",", 1)[-1])
    except Exception:
        return False, "图像数据无效"
    if not raw:
        return False, "图像数据为空"
    try:
        import uuid
        from src.harness.consts import _UPLOAD_DIR
        os.makedirs(_UPLOAD_DIR, exist_ok=True)
        path = os.path.join(_UPLOAD_DIR, "%s_snip.png" % uuid.uuid4().hex[:8])
        with open(path, "wb") as f:
            f.write(raw)
    except Exception as e:
        return False, "保存失败：%s" % e
    copy_png_to_clipboard(path)
    return True, path


_launch_lock = threading.Lock()


def launch_window(port):
    """热键/📷 按钮统一入口：抓屏 → SSE 通知 Electron 壳开覆盖窗。

    port 参数保留（调用方签名不变），壳从 endpoint 自取服务地址。
    返回 (ok, info)：失败时 info 给前端/托盘弹提示。
    """
    # 防连击：抓屏串行化（Electron 侧另有同窗去重）
    if not _launch_lock.acquire(blocking=False):
        return True, "spawning"
    try:
        if not grab():
            return False, "抓屏失败（--snip-grab 子进程未产出底图）"
        try:
            from src.app_state import _broadcast_to_ai
            _broadcast_to_ai({"kind": "ui_action", "action": "snip_open",
                              "geo": read_geo()})
        except Exception as e:
            return False, "通知 Electron 壳失败：%s" % e
        return True, "ok"
    finally:
        _launch_lock.release()


# ---------------------------------------------------------------------------
# 全局热键（ctypes RegisterHotKey，无任何 .NET 依赖）
# ---------------------------------------------------------------------------
_MODS = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}


def _parse_hotkey(s):
    """'ctrl+alt+a' / 'f1' → (mods, vk)。f1-f12 允许无修饰单键；
    字母/数字单键必须带修饰（裸键全局吞输入）。非法返回 None。"""
    parts = [p.strip().lower() for p in str(s or "").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, ""
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        else:
            key = p
    if not key:
        return None
    is_fn = key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12
    if len(key) == 1 and key.isalnum():
        if not mods:
            return None
        vk = ord(key.upper())
    elif is_fn:
        vk = 0x70 + int(key[1:]) - 1
    else:
        return None
    return mods, vk


def set_hotkey(hotkey_str, slot="snip"):
    """热更新键位：'f1'/'ctrl+alt+a'/''（空=注销禁用）。
    slot：snip=截图（0xFC1）。返回 (ok, err)。"""
    u32 = ctypes.windll.user32
    s = str(hotkey_str or "").strip().lower()
    if not s:
        with _hk["lock"]:
            st = _hk["slots"].setdefault(slot, {})
            st["pending"] = None
            st["disabled"] = True
        _wake_hk_thread()
        return True, None
    hk = _parse_hotkey(s)
    if not hk:
        return False, "格式无效（示例 f1 / ctrl+alt+a；字母数字键需带修饰键）"
    if not u32.RegisterHotKey(None, 0xFC2, hk[0], hk[1]):
        return False, "热键被其他程序占用"
    u32.UnregisterHotKey(None, 0xFC2)
    with _hk["lock"]:
        st = _hk["slots"].setdefault(slot, {})
        st["pending"] = hk
        st["disabled"] = False
    _wake_hk_thread()
    return True, None


_hk = {"tid": 0, "lock": threading.Lock(), "slots": {}}
_HK_SLOT_ID = {"snip": 0xFC1, "pin": 0xFC3}
_WM_APP_SNIP = 0x8000 + 1


def _wake_hk_thread():
    if _hk["tid"]:
        ctypes.windll.user32.PostThreadMessageW(_hk["tid"], _WM_APP_SNIP, 0, 0)


def start_hotkey(hotkey_str, on_trigger, slot="snip"):
    """启动全局热键线程并应用初始键位（热更新走 set_hotkey）。"""
    with _hk["lock"]:
        st = _hk["slots"].setdefault(slot, {})
        st["on_trigger"] = on_trigger
    _start_hk_thread()
    if str(hotkey_str or "").strip():
        return set_hotkey(hotkey_str, slot=slot)
    return True, None


def _start_hk_thread(on_trigger=None):
    if _hk.get("started"):
        return
    _hk["started"] = True

    def _loop():
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        # GetCurrentThreadId 在 kernel32（user32 没有——写错库线程即崩，
        # 热键从未注册成功的历史实锤）
        k32 = ctypes.windll.kernel32
        k32.GetCurrentThreadId.restype = wintypes.DWORD
        _hk["tid"] = k32.GetCurrentThreadId()
        current = {}                     # slot -> (mods, vk) 现注册值
        msg = wintypes.MSG()
        while True:
            jobs = []
            with _hk["lock"]:
                for slot, st in _hk["slots"].items():
                    p = st.get("pending", "UNSET")
                    if p != "UNSET" or st.get("disabled"):
                        st["pending"] = "UNSET"
                        jobs.append((slot, p, bool(st.get("disabled"))))
            for slot, pend, disabled in jobs:
                hid = _HK_SLOT_ID[slot]
                if slot in current:
                    u32.UnregisterHotKey(None, hid)
                    current.pop(slot, None)
                if not disabled and pend not in ("UNSET", None) and pend:
                    if u32.RegisterHotKey(None, hid, pend[0], pend[1]):
                        current[slot] = pend
            r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            if msg.message == 0x0312:
                for slot, hid in _HK_SLOT_ID.items():
                    if msg.wParam == hid:
                        st = _hk["slots"].get(slot) or {}
                        cb = st.get("on_trigger")
                        if cb:
                            try:
                                threading.Thread(target=cb, daemon=True).start()
                            except Exception:
                                pass

    threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    if "--snip-grab" in sys.argv or "--grab" in sys.argv:
        _dpi_aware()
        _grab_only()
