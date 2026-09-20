# -*- coding: utf-8 -*-
"""内置截图+标注（v2.3.12）：vendor js-web-screen-shot（MIT，ikaia/js-screen-shot）
**主窗内嵌形态**（用户定调：不额外弹窗、直接就能截——插件本为嵌入页面设计，
主窗内全屏遮罩盖住 UI 即截图态，独立 pywebview 窗的尺寸/坐标/任务栏坑全免）。

链路：
- 📷 按钮 → POST /api/snip/grab：DPI 子进程 ImageGrab 抓屏 → TEMP/fc_snip.png
- 主窗前端 new screenShotPlugin({source:'image', imageSrc:'/api/snip/img'})
  → 主窗内遮罩框选/标注 → 确认 → POST /api/snip/save(base64)
- 后端落 harness_uploads + CF_DIB 复制剪贴板 → 返回 path → 前端直接挂附件
"""
import os
import io
import json
import ctypes
import subprocess
import sys

_TMP_PNG = os.path.join(os.environ.get("TEMP", "."), "fc_snip.png")
_TMP_GEO = _TMP_PNG + ".geo.json"


# ---------------------------------------------------------------------------
# 子进程：DPI 无损抓屏（主进程与 exe 各有入口调 grab_main）
# ---------------------------------------------------------------------------
def grab_main():
    """`--grab` 子进程入口：DPI 感知 → 全屏截图 → PNG + 几何 json → 退出。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)   # 虚拟桌面整幅（物理像素）
    img.save(_TMP_PNG)
    u32 = ctypes.windll.user32
    geo = {"x": u32.GetSystemMetrics(76), "y": u32.GetSystemMetrics(77),   # SM_X/YVIRTUALSCREEN
           "w": u32.GetSystemMetrics(78), "h": u32.GetSystemMetrics(79)}  # SM_CX/CYVIRTUALSCREEN
    with open(_TMP_GEO, "w", encoding="utf-8") as f:
        json.dump(geo, f)


def grab():
    """主进程入口：子进程抓屏（dev=python 源码 / 打包=exe 自身 --snip-grab）。
    成功判据：产物存在且 mtime 晚于调用时刻（防吃到上一次的旧图）。"""
    import time
    t0 = time.time()
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--snip-grab"]
    else:
        cmd = [sys.executable, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "snip.py"), "--grab"]
    try:
        subprocess.run(cmd, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    return os.path.isfile(_TMP_PNG) and os.path.getmtime(_TMP_PNG) > t0


# ---------------------------------------------------------------------------
# 剪贴板：PNG 文件 → CF_DIB（与 main.py copy_image_to_clipboard 同工艺）
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
        h = k32.GlobalAlloc(0x0002, len(dib))   # GMEM_MOVEABLE
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
            ok = bool(u32.SetClipboardData(8, h))   # CF_DIB
            if not ok:
                k32.GlobalFree(h)
            return ok
        finally:
            u32.CloseClipboard()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 全局热键（v2.3.12）：任意应用前台按热键 → 截当前真实屏幕 → 工具弹前进入
# 截图态（Snipaste 核心体验；按钮入口截到的是工具最大化时盖住一切的自己）
# ---------------------------------------------------------------------------
_MODS = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}


def _parse_hotkey(s):
    """'ctrl+alt+a' → (mods, vk)。键位支持 a-z/0-9/f1-f12；非法返回 None。"""
    parts = [p.strip().lower() for p in str(s or "").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, ""
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        else:
            key = p
    if not key or not mods:
        return None
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x70 + int(key[1:]) - 1
    else:
        return None
    return mods, vk


def start_hotkey(hotkey_str, on_trigger):
    """注册全局热键（daemon 消息循环线程）。失败静默返回 False。
    hotkey_str 形如 'ctrl+alt+a'（config.json 的 snip_hotkey，空/非法=不注册）。"""
    hk = _parse_hotkey(hotkey_str)
    if not hk:
        return False

    def _loop():
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        mods, vk = hk
        HOTKEY_ID = 0xFC1
        if not u32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
            return   # 被其他程序占用（Snipaste 等同款热键）——不抢，静默
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:   # WM_HOTKEY
                try:
                    threading.Thread(target=on_trigger, daemon=True).start()
                except Exception:
                    pass

    import threading
    threading.Thread(target=_loop, daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# 出口：base64 → uploads + 剪贴板
# ---------------------------------------------------------------------------
def save_png(data_url):
    """dataURL → 落 harness_uploads + 复制剪贴板。返回 (ok, path/err)。"""
    try:
        import base64
        raw = base64.b64decode((data_url or "").split(",", 1)[-1])
    except Exception:
        return False, "图像数据无效"
    if not raw:
        return False, "图像数据为空"
    try:
        import uuid
        from src.claude_harness import _UPLOAD_DIR
        os.makedirs(_UPLOAD_DIR, exist_ok=True)
        path = os.path.join(_UPLOAD_DIR, "%s_snip.png" % uuid.uuid4().hex[:8])
        with open(path, "wb") as f:
            f.write(raw)
    except Exception as e:
        return False, "保存失败：%s" % e
    copy_png_to_clipboard(path)
    return True, path


if __name__ == "__main__" and "--grab" in sys.argv:
    grab_main()
