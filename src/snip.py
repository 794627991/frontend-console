# -*- coding: utf-8 -*-
"""内置截图+标注（v2.3.12）：以 github.com/likaia/js-screen-shot（MIT）的
交互方案为蓝本自己实现——框选/八向调整/矩形/椭圆/箭头/画笔/马赛克/文字/
撤销，宿主为 pywebview 无边框置顶全屏窗（web/screenshot.html）。

架构（蓝本口径，代码自研）：
- 抓屏：独立子进程开 DPI 感知后 ImageGrab 全屏 → 物理像素 PNG + 虚拟桌面
  几何 json（主进程不动 DPI 设置，避免主窗缩放回归）。dev 用
  `python src/snip.py --grab <png>`；打包后 exe --snip-grab <png>。
- 标注器：纯前端 Canvas（标注对象数组全量重放，撤销=pop）。
- 出口：js_api snip_done(dataURL) → 落 harness_uploads + CF_DIB 复制剪贴板
  → SSE ui_action(snip_done) → 前端自动挂 Claude 对话附件。
"""
import os
import io
import json
import time
import ctypes
import threading
import subprocess
import sys

# 子进程入口（--grab）时项目根不在 sys.path——同 main.py 的 _ROOT 注入
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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


def _spawn_grab():
    """在子进程里抓屏（dev=python 源码 / 打包=exe 自身 --snip-grab）。"""
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
    return os.path.isfile(_TMP_PNG)


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
# 截图窗生命周期（单例）
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_win = None          # 当前截图窗（pywebview Window）


class SnipBridge:
    """截图窗 js_api：标注完成/取消的回传通道。"""

    def snip_done(self, data_url, act):
        """标注完成。data_url=canvas dataURL；act: attach(挂附件)/copy(仅复制)。"""
        threading.Thread(target=_finish, args=(data_url, act), daemon=True).start()
        return True

    def snip_cancel(self):
        _close_win()
        return True


def _close_win():
    global _win
    w, _win = _win, None
    if w is not None:
        try:
            w.destroy()
        except Exception:
            pass


def _finish(data_url, act):
    """落盘 + 剪贴板 + 广播挂附件（截图窗已可关）。"""
    _close_win()
    try:
        import base64
        import uuid
        raw = base64.b64decode(data_url.split(",", 1)[-1])
        from src.claude_harness import _UPLOAD_DIR
        os.makedirs(_UPLOAD_DIR, exist_ok=True)
        path = os.path.join(_UPLOAD_DIR, "%s_snip.png" % uuid.uuid4().hex[:8])
        with open(path, "wb") as f:
            f.write(raw)
    except Exception:
        return
    copy_png_to_clipboard(path)
    if act == "attach":
        from src.app_state import _broadcast_to_ai
        _broadcast_to_ai({"kind": "ui_action", "action": "snip_done", "path": path})


def start_snip():
    """入口：抓屏 → 开截图标注窗。返回 (ok, info)。"""
    global _win
    with _lock:
        if _win is not None:
            return False, "截图窗已打开（先完成或按 Esc 关闭）"
        if not _spawn_grab():
            return False, "抓屏失败（子进程未产出截图）"
        geo = {}
        try:
            with open(_TMP_GEO, "r", encoding="utf-8") as f:
                geo = json.load(f)
        except Exception:
            geo = {"x": 0, "y": 0, "w": 1280, "h": 800}
        # Flask 端口从 endpoint.json 取（write_endpoint 已写，MCP 同源机制）
        port = ""
        try:
            ep = os.path.join(os.path.expanduser("~"), ".serialconsole_pro", "endpoint.json")
            with open(ep, "r", encoding="utf-8") as f:
                port = str((json.load(f) or {}).get("port") or "")
        except Exception:
            pass
        if not port:
            return False, "后端端口未知（endpoint.json 缺失）"
        try:
            import webview
            url = "http://127.0.0.1:%s/web/screenshot.html" % port
            _win = webview.create_window(
                "截图", url, js_api=SnipBridge(),
                x=int(geo.get("x", 0)), y=int(geo.get("y", 0)),
                width=int(geo.get("w", 1280)), height=int(geo.get("h", 800)),
                frameless=True, on_top=True, resizable=False,
            )
        except Exception as e:
            _win = None
            return False, "截图窗创建失败：%s" % e
    return True, "ok"


if __name__ == "__main__" and "--grab" in sys.argv:
    grab_main()
