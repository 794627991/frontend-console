# -*- coding: utf-8 -*-
"""复现用户路径：最大化 → 关闭驻托盘 → 托盘点开 → 看WindowState。执行后删。"""
import sys
import time

try:
    _m = sys.modules.get("main") or sys.modules.get("__main__")
    w = getattr(_m, "_win", None) if _m else None
    if w is None:
        import webview
        w = webview.windows[0] if webview.windows else None

    from System.Windows.Forms import FormWindowState as FS

    def st(tag):
        f = w.native
        # from_max 状态
        fm = None
        try:
            fm = _m._fc_restore.get("from_max")
        except Exception:
            pass
        b = f.Bounds
        return "%s: state=%s from_max=%s bounds=%dx%d visible=%s" % (
            tag, f.WindowState, fm, b.Width, b.Height, f.Visible)

    out = []

    # 1) 最大化
    w.maximize()
    time.sleep(0.6)
    out.append(st("after-maximize"))

    # 2) 关闭驻托盘（同 on_closing 的 _hide_async 链）
    import src.tray as T
    T.hide_to_tray(w, lambda: None)
    time.sleep(0.6)
    out.append(st("after-hide_to_tray"))

    # 3) 托盘点开（同 on_default：show + restore + foreground）
    w.show()
    w.restore()
    time.sleep(0.8)
    out.append(st("after-tray-open"))

    with open(r"C:/Users/79462/AppData/Local/Temp/fc_tray_out.txt", "w",
              encoding="utf-8") as f:
        f.write("\n".join(out))
except Exception as e:
    with open(r"C:/Users/79462/AppData/Local/Temp/fc_tray_out.txt", "w",
              encoding="utf-8") as f:
        f.write("ERR %r" % e)
