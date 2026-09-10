# -*- coding: utf-8 -*-
"""系统托盘（pystray）：关闭最小化到托盘 + 单击唤出 + 右键菜单。

- 单击托盘 → 显示主窗口（default_action）
- 右键托盘 → 原生菜单「显示主窗口 / Claude Proxy 段 / 退出」（Win32 popup，
  跟随系统主题；工具内弹窗全部走前端暗色模态框，托盘菜单保持系统原生——
  桌面惯例，微信/QQ/VSCode 同款，不违和）
- 懒建：首次隐藏到托盘才创建（不隐藏永不占托盘位）
- 幂等：重复调用复用已有 Icon
- 自愈：watchdog 每 15s 真实验活——pystray 的 mainloop 退出时 finally
  只 NIM_DELETE 不清 _visible 标志，死图标 visible 仍读 True（用户实锤：
  残影留在托盘，鼠标一划过即消失，旧 watchdog 被骗过永不重建）。故验活
  不信 visible，改验消息循环线程活着 + 宿主窗口 IsWindow 双信号；
  pystray 内部异常同时落日志（DATA_DIR/tray_pystray.log）供下次定位真凶。
"""
import threading

_icon = None          # pystray.Icon 单例
_lock = threading.Lock()
_window = None        # hide_to_tray 留存窗口引用（watchdog 重建用）
_on_quit = None       # 同上，重建时传回退出回调
_watchdog = None


def _setup_pystray_log():
    """pystray 用 logging.getLogger('pystray') 报内部异常（mainloop 崩溃
    只写日志不抛出）。挂一个 FileHandler 捕获真凶——线程死因下次有据可查。"""
    try:
        import logging
        from src.app_state import DATA_DIR
        import os
        lg = logging.getLogger("pystray")
        if any(isinstance(h, logging.FileHandler) for h in lg.handlers):
            return
        lg.setLevel(logging.DEBUG)
        h = logging.FileHandler(os.path.join(DATA_DIR, "tray_pystray.log"),
                                encoding="utf-8")
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(h)
    except Exception:
        pass   # 日志挂不上不拖累托盘


def get_icon():
    """当前托盘 Icon（proxy 模块 tooltip 刷新线程读用；未建返回 None）。"""
    return _icon


def _icon_alive(icon):
    """真实验活：消息循环线程活着 + 宿主窗口仍存在。
    icon.visible 不可信——pystray mainloop 退出（崩溃/explorer 重启窗口被毁）
    后 _visible 标志不清，残影图标照样读 True。线程未起（_thread 无）时
    属刚建瞬间的幼体，退回 visible 判断。"""
    try:
        t = getattr(icon, "_thread", None)
        if t is not None and not t.is_alive():
            return False          # 消息循环线程已死
        hwnd = getattr(icon, "_hwnd", None)
        if hwnd:
            import ctypes
            if not ctypes.windll.user32.IsWindow(hwnd):
                return False      # 宿主窗口已被销毁（残影实锤态）
        return bool(icon.visible)  # 窗口活着但被外部清了 visible：也该重建
    except Exception:
        return False


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
                    _icon.stop()   # 残骸上 stop：向死 hwnd post 失败无害
                except Exception:
                    pass
            _setup_pystray_log()
            _icon = _make_icon(_window, _on_quit)
            _icon.run_detached()
        except Exception:
            _icon = None   # 重建也失败（无托盘环境等），下轮 watchdog 再试


def _watchdog_loop():
    """15s 真实验活：消息循环线程死 / 宿主窗口被毁 / visible 被清 → 重建。
    残影图标（线程已死、窗口已毁）在托盘里存活到鼠标划过才消失——旧逻辑
    验 visible 永远 True，用户实锤「一指托盘图标就没了」。"""
    import time
    while True:
        time.sleep(15)
        with _lock:
            icon = _icon
        if icon is None:
            continue   # 从未建过（还没隐藏过），不抢建
        if not _icon_alive(icon):
            _rebuild()


def hide_to_tray(window, on_quit):
    """隐藏主窗口到托盘（首次调用建托盘，之后只 hide）。"""
    global _icon, _window, _on_quit, _watchdog
    with _lock:
        _window, _on_quit = window, on_quit   # watchdog 重建要用
        if _icon is None:
            try:
                _setup_pystray_log()
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
