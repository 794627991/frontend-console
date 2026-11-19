# -*- coding: utf-8 -*-
"""可见态全路径复现：max→minimize→任务栏还原 / max→close→托盘点开。执行后删。"""
import sys
import time

try:
    _m = sys.modules.get("main") or sys.modules.get("__main__")
    w = getattr(_m, "_win", None) if _m else None
    if w is None:
        import webview
        w = webview.windows[0] if webview.windows else None

    from System.Windows.Forms import FormWindowState as FS
    import ctypes

    def st(tag):
        f = w.native
        fm = _m._fc_restore.get("from_max")
        sub = bool(_m._orig_wndproc.get("fn"))
        b = f.Bounds
        return "%s: state=%s from_max=%s subclass=%s visible=%s %dx%d" % (
            tag, f.WindowState, fm, sub, f.Visible, b.Width, b.Height)

    out = []

    # 确保窗口可见
    w.show()
    time.sleep(0.5)

    # ===== 路径A：最大化 → 最小化 → 任务栏点击（SW_RESTORE）=====
    w.maximize()
    time.sleep(0.8)
    out.append(st("A1 after-maximize"))
    w.minimize()
    time.sleep(0.8)
    out.append(st("A2 after-minimize"))
    hwnd = int(w.native.Handle.ToInt64())
    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE = 任务栏点击同款
    time.sleep(1.0)
    out.append(st("A3 after-taskbar-restore"))

    # ===== 路径B：最大化 → 关闭驻托盘 → 托盘点开 =====
    w.maximize()
    time.sleep(0.8)
    out.append(st("B1 after-maximize"))
    import src.tray as T
    T.hide_to_tray(w, lambda: None)
    time.sleep(0.6)
    out.append(st("B2 after-hide"))
    w.show()
    w.restore()
    time.sleep(0.8)
    out.append(st("B3 after-tray-open"))

    # 还原到普通态收尾
    if w.native.WindowState == FS.Maximized:
        w.restore()
        time.sleep(0.4)

    with open(r"C:/Users/79462/AppData/Local/Temp/fc_full_out.txt", "w",
              encoding="utf-8") as f:
        f.write("\n".join(out))
except Exception as e:
    with open(r"C:/Users/79462/AppData/Local/Temp/fc_full_out.txt", "w",
              encoding="utf-8") as f:
        f.write("ERR %r" % e)
