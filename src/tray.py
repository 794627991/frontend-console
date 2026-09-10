# -*- coding: utf-8 -*-
"""系统托盘（pystray）：关闭最小化到托盘 + 单击唤出 + 右键菜单。

- 单击托盘 → 显示主窗口（default_action）
- 右键托盘 → 原生菜单「显示主窗口 / Claude Proxy 段 / 退出」（Win32 popup，
  跟随系统主题；工具内弹窗全部走前端暗色模态框，托盘菜单保持系统原生——
  桌面惯例，微信/QQ/VSCode 同款，不违和）
- 懒建：首次隐藏到托盘才创建（不隐藏永不占托盘位）
- 幂等：重复调用复用已有 Icon
- 自愈：watchdog 每 30s 验活——icon 消失/消息循环死（explorer 重启、
  pystray 内部异常）自动重建。用户实锤过「托盘直接没了」，窗口隐藏后
  再无唤出入口，宁可重建也不能丢（铁律①）
"""
import threading

_icon = None          # pystray.Icon 单例
_lock = threading.Lock()
_window = None        # hide_to_tray 留存窗口引用（watchdog 重建用）
_on_quit = None       # 同上，重建时传回退出回调
_watchdog = None


def get_icon():
    """当前托盘 Icon（proxy 模块 tooltip 刷新线程读用；未建返回 None）。"""
    return _icon


def _make_icon(window, on_quit):
    """建托盘图标。用 app.ico 直接当托盘图标（免 PIL 重绘，ICO 自带多尺寸）。
    菜单尾部并入 Claude Proxy 段（proxy.tray_menu_items()：额度行/启停/
    模式/压缩/CCR，text 全传函数动态求值——启动代理前后无需重建菜单）。"""
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

    proxy_items = []
    try:
        from src import proxy as _proxy
        proxy_items = _proxy.tray_menu_items()
    except Exception:
        pass   # proxy 模块异常不拖累主托盘（拼积木：各段独立可用）

    menu = pystray.Menu(
        pystray.MenuItem("显示主窗口", show_main, default=True),   # default=True → 左键单击直接触发
        pystray.Menu.SEPARATOR,
        *proxy_items,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda icon=None, item=None: on_quit()),
    )
    return pystray.Icon("SerialConsolePro", img, "前端控制台", menu)


def _rebuild():
    """重建托盘 Icon（watchdog 验活失败时调）。窗口/退出回调用留存的引用。"""
    global _icon
    with _lock:
        try:
            if _icon is not None:
                try:
                    _icon.stop()
                except Exception:
                    pass
            _icon = _make_icon(_window, _on_quit)
            _icon.run_detached()
        except Exception:
            _icon = None   # 重建也失败（无托盘环境等），下轮 watchdog 再试


def _watchdog_loop():
    """30s 验活：icon 的消息循环线程死了或 visible 被外部清掉 → 重建。"""
    import time
    while True:
        time.sleep(30)
        with _lock:
            icon = _icon
        if icon is None:
            continue   # 从未建过（还没隐藏过），不抢建
        try:
            alive = icon.visible
        except Exception:
            alive = False
        if not alive:
            _rebuild()


def hide_to_tray(window, on_quit):
    """隐藏主窗口到托盘（首次调用建托盘，之后只 hide）。"""
    global _icon, _window, _on_quit, _watchdog
    with _lock:
        _window, _on_quit = window, on_quit   # watchdog 重建要用
        if _icon is None:
            try:
                _icon = _make_icon(window, on_quit)
                _icon.run_detached()   # 后台线程跑消息循环，不阻塞主线程
            except Exception:
                # 托盘建不起来（如服务会话无托盘区）→ 返回 False 让调用方直接退出
                _icon = None
                return False
        if _watchdog is None:
            _watchdog = threading.Thread(target=_watchdog_loop, daemon=True)
            _watchdog.start()
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
