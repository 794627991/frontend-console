# -*- coding: utf-8 -*-
"""系统托盘（pystray）：关闭最小化到托盘 + 单击唤出 + 右键菜单。

- 单击托盘 → 显示主窗口（default_action）
- 右键托盘 → 原生菜单「显示主窗口 / 退出」（Win32 popup，跟随系统主题；
  工具内弹窗全部走前端暗色模态框，托盘菜单保持系统原生——桌面惯例，
  微信/QQ/VSCode 同款，不违和）
- 懒建：首次隐藏到托盘才创建（不隐藏永不占托盘位）
- 幂等：重复调用复用已有 Icon
"""
import threading

_icon = None          # pystray.Icon 单例
_lock = threading.Lock()


def _make_icon(window, on_quit):
    """建托盘图标。用 app.ico 直接当托盘图标（免 PIL 重绘，ICO 自带多尺寸）。"""
    import pystray
    from PIL import Image
    from src.app_state import RES_DIR
    import os

    ico = os.path.join(RES_DIR, "ico", "app.ico")
    # pystray 只吃 PIL Image；ICO 打开取第一帧
    try:
        img = Image.open(ico)
    except Exception:
        img = Image.new("RGBA", (32, 32), (0, 212, 255, 255))

    def show_main(icon=None, item=None):
        try:
            window.show()
            window.restore()   # 最小化态唤出要先还原
            window.focus()
        except Exception:
            pass

    menu = pystray.Menu(
        pystray.MenuItem("显示主窗口", show_main, default=True),   # default=True → 左键单击直接触发
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda icon=None, item=None: on_quit()),
    )
    return pystray.Icon("SerialConsolePro", img, "前端控制台", menu)


def hide_to_tray(window, on_quit):
    """隐藏主窗口到托盘（首次调用建托盘，之后只 hide）。"""
    global _icon
    with _lock:
        if _icon is None:
            try:
                _icon = _make_icon(window, on_quit)
                _icon.run_detached()   # 后台线程跑消息循环，不阻塞主线程
            except Exception:
                # 托盘建不起来（如服务会话无托盘区）→ 返回 False 让调用方直接退出
                _icon = None
                return False
    try:
        window.hide()
    except Exception:
        pass
    return True


def quit_tray():
    """退出前清托盘图标（进程退出会自动消失，显式停更干净）。"""
    global _icon
    with _lock:
        if _icon is not None:
            try:
                _icon.stop()
            except Exception:
                pass
            _icon = None
