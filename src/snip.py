# -*- coding: utf-8 -*-
"""内置截图+标注 v2.3.12 最终形态（用户定调：截图就是截图——独立全屏窗
盖住整个物理屏幕，底图 1:1 原封不动，绝不缩在工具窗口里）。

架构（Snipaste 形态）：
- 触发（📷 按钮/全局热键）→ 主进程 DPI 子进程抓屏（--grab，物理像素）
- 同一子进程形态再开「截图窗子进程」（--snip-window <port>）：DPI 感知下
  建 pywebview 无边框置顶全屏窗（物理像素直达，主进程非 aware 的虚拟化
  错位从根上不存在），WS_EX_TOOLWINDOW 去任务栏图标
- 窗内 vendor js-web-screen-shot（MIT）框选/标注，canvas=视口=屏幕=底图
  → 1:1 原生分辨率（插件自带 dpr 感知导出）
- 完成 → base64 写 TEMP/snip_out.png → 子进程退出；主进程轮询收图 →
  落 harness_uploads + CF_DIB 剪贴板 + SSE snip_done → 前端挂附件
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
_TMP_BMP = os.path.join(os.environ.get("TEMP", "."), "fc_snip.bmp")   # BMP 免编码
_TMP_GEO = _TMP_PNG + ".geo.json"
_TMP_OUT = os.path.join(os.environ.get("TEMP", "."), "fc_snip_out.png")
# 常驻窗生命标记：ALIVE=子进程每次页面加载成功后写（port+时间），主进程
# 探活以此为准——窗口标题探活分不清「哪个主实例的窗」：工具重启后端口随机，
# 上一实例遗留的孤儿窗仍叫 fc-snip，命中它会让它 reload 旧端口 → WebView2
# 弹「无法连接 127.0.0.1」错误页（用户实锤）。SPAWN=spawn 防抖标记（热键
# 与 prewarm 竞态双窗）。
_TMP_ALIVE = os.path.join(os.environ.get("TEMP", "."), "fc_snip_alive.json")
_TMP_SPAWN = os.path.join(os.environ.get("TEMP", "."), "fc_snip_spawn.marker")


# ---------------------------------------------------------------------------
# 子进程公共：DPI 感知（两种模式共用）
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
    """--grab：抓屏 → BMP（PNG 编码 1920x1080 要 ~0.4s，BMP 免压缩 ~0.05s，
    localhost 传输不差这点体积）+ 几何 json。"""
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    img.save(_TMP_BMP)
    with open(_TMP_GEO, "w", encoding="utf-8") as f:
        json.dump(_virt_geo(), f)


# ---------------------------------------------------------------------------
# 子进程：截图窗（--snip-window <port>）
# ---------------------------------------------------------------------------
def window_main(port, armed=False):
    """常驻截图窗子进程：DPI 感知 → 无边框置顶全屏窗（hidden）待命。
    生命周期：主进程热键时抓屏（--grab 落 BMP）→ 本进程 _arm_loop 感知
    BMP mtime 变化 → reload 页面拿新底图 → loaded 钉物理几何 → show；
    完成/取消 → hide 待命（不 destroy：销毁闪屏 + 下次冷启动 2s 双输）。
    armed=True：热键触发的冷启动，主进程已抓好屏，首载后直接 show。
    空闲 10 分钟自退（WebView2 常驻 ~100-150MB，不用时归零）。"""
    _dpi_aware()
    geo = _virt_geo()          # 几何不依赖抓屏文件，立即可用
    if not os.path.isfile(_TMP_BMP):
        _grab_only()           # 预热拉起时先抓一张供首载（旧图即可）
    if os.path.isfile(_TMP_OUT):
        os.remove(_TMP_OUT)

    import webview

    def _save_dialog():
        """另存为对话框（WinForms 必须 STA 线程跑）。默认图片库+时间戳文件名。"""
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import SaveFileDialog
            from System.Threading import Thread, ThreadStart, ApartmentState
        except Exception:
            return None
        result = {}

        def _run():
            try:
                dlg = SaveFileDialog()
                dlg.Filter = "PNG 图片 (*.png)|*.png"
                dlg.FileName = time.strftime("snip_%Y%m%d_%H%M%S.png")
                try:
                    buf = ctypes.create_unicode_buffer(260)
                    # CSIDL_MYPICTURES=0x27：默认打开「图片」目录
                    ctypes.windll.shell32.SHGetFolderPathW(None, 0x27, None, 0, buf)
                    if buf.value:
                        dlg.InitialDirectory = buf.value
                except Exception:
                    pass
                if dlg.ShowDialog() == 1:      # DialogResult.OK
                    result["path"] = dlg.FileName
            except Exception:
                pass

        t = Thread(ThreadStart(_run))
        t.SetApartmentState(ApartmentState.STA)
        t.Start()
        t.Join()
        return result.get("path")

    state = {"armed": armed, "showing": False}

    def _page_url():
        g = _virt_geo()        # reload 时现取：换分辨率/显示器自适应
        return ("http://127.0.0.1:%s/web/screenshot.html?w=%d&h=%d&v=%d"
                % (port, g["w"], g["h"], int(time.time() * 1000)))

    class SnipWin:
        def snip_done(self, data_url):
            """√ 确认：base64 → 落盘 → 隐藏待命。"""
            try:
                import base64
                with open(_TMP_OUT, "wb") as f:
                    f.write(base64.b64decode((data_url or "").split(",", 1)[-1]))
            except Exception:
                pass
            _hide()
            return True

        def snip_save_as(self, data_url):
            """「保存」按钮：另存为对话框存 PNG 文件（区别于 √=附加到对话，
            用户定调：保存就是保存）。取消对话框=放弃当次，同样收起。"""
            try:
                import base64
                raw = base64.b64decode((data_url or "").split(",", 1)[-1])
            except Exception:
                raw = b""

            def _ask():
                path = _save_dialog()
                if path:
                    try:
                        with open(path, "wb") as f:
                            f.write(raw)
                    except Exception:
                        pass
                _hide()
            threading.Thread(target=_ask, daemon=True).start()
            return True

        def snip_cancel(self):
            _hide()
            return True

    def _hide():
        # 即刻 hide（旧版 sleep 0.2 给了插件 destroyDom 黑帧 200ms 展示时间，
        # 黑屏闪烁实锤）；跨进程调用+Invoke 全程 ~20ms，抢在视觉感知前摘窗
        try:
            win.hide()
            state["showing"] = False
        except Exception:
            pass

    # easy_drag=False 必须显式关：pywebview 6.x 默认 True——frameless 窗注入
    # customize.js 监听 window.mousedown，页面任意处按住拖动=拖走整个窗口
    # （用户实锤「框选时窗口能被拖走」，插件的框选拖动拦不住它）。
    # shadow=False 同理：默认 True 会 ExtendFrameIntoClientArea 给无边框窗
    # 补 DWM 玻璃边框——顶部一圈条带观感像「多出一排菜单栏的最大化窗口」
    # （用户实锤），关掉才是 Snipaste 式纯桌面覆盖。
    win = webview.create_window(
        "fc-snip", _page_url(),
        js_api=SnipWin(),
        x=int(geo.get("x", 0)), y=int(geo.get("y", 0)),
        width=int(geo.get("w", 1280)), height=int(geo.get("h", 800)),
        frameless=True, on_top=True, resizable=False, hidden=True,
        easy_drag=False, shadow=False)

    def _on_loaded():
        # 去任务栏图标 + 置顶样式刷新（SWP_FRAMECHANGED 让 EXSTYLE 立即生效）
        def _do():
            try:
                time.sleep(0.25)
                # 页面真伪验证：WebView2 初始化竞态下加载失败
                # （ERR_CONNECTION_REFUSED，与主窗 WebView2 同时冷启实锤）也会
                # 触发 loaded——错误页绝不 show、绝不写心跳。验证失败静默
                # reload 重试 3 次，仍败自退（下次热键重新拉起）。
                try:
                    _ok = win.evaluate_js("window.__FC_SNIP__===true")
                except Exception:
                    _ok = None
                if _ok is not True:
                    state["fails"] = state.get("fails", 0) + 1
                    if state["fails"] > 3:
                        os._exit(0)
                    try:
                        time.sleep(1)          # 给 WebView2 一拍喘息再重试
                        win.load_url(_page_url())
                    except Exception:
                        pass
                    return
                state["fails"] = 0
                u32 = ctypes.windll.user32
                hwnd = u32.FindWindowW(None, "fc-snip")
                if hwnd:
                    GWL_EXSTYLE = -20
                    style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | 0x80)  # WS_EX_TOOLWINDOW
                    GWL_STYLE = -16
                    style2 = u32.GetWindowLongW(hwnd, GWL_STYLE)
                    u32.SetWindowLongW(hwnd, GWL_STYLE,
                                       style2 & ~0x00C40000)  # 去边框样式残留
                # 钉死窗口=虚拟屏幕物理矩形。必须走 WinForms 自己的
                # ClientSize/Location：pywebview 建窗先设 Size 再改 frameless，
                # Form 缓存的 ClientSize 是按带边框样式算的「屏-边框-标题栏」
                # （实测 1920x1080 屏被钳到 1904x1041，raw SetWindowPos 钉完
                # 被 WM_WINDOWPOSCHANGING 弹回）→ 遮罩差 16x39 盖不满屏，
                # 右侧竖条+底部露出真任务栏=「两排任务栏」实锤。Invoke 到
                # GUI 线程设，Form 缓存同步更新。每次 loaded 现取几何：
                # 分辨率/显示器热切换后 reload 自动归位。
                g = _virt_geo()
                gx, gy, gw, gh = g["x"], g["y"], g["w"], g["h"]
                try:
                    from System import Func, Type
                    from System.Drawing import Point, Size
                    native = win.native

                    def _fix():
                        native.ClientSize = Size(gw, gh)
                        native.Location = Point(gx, gy)
                    native.Invoke(Func[Type](_fix))
                except Exception:
                    # CLR 不可用兜底：raw 钉（会被弹回但聊胜于无）
                    if hwnd:
                        u32.SetWindowPos(hwnd, -1, gx, gy, gw, gh, 0x0040)
                if hwnd:
                    # 置顶+样式刷新（NOSIZE|NOMOVE 只刷框架）
                    u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                     0x0001 | 0x0002 | 0x0040)
                # armed=热键冷启动（主进程已抓好屏）或 reload 弹出时才 show；
                # 预热首载（旧底图待命）保持 hidden。
                if state["armed"] or state["showing"]:
                    state["armed"] = False
                    win.show()
                    # pywebview 6.x 的 window.focus 是 bool 属性不是方法（诊断
                    # 实测调用即 TypeError 炸线程），聚焦改走 Win32
                    if hwnd:
                        u32.SetForegroundWindow(hwnd)
                # 页面加载成功=连上本实例 Flask：写生命标记（主进程探活凭据）
                try:
                    with open(_TMP_ALIVE, "w", encoding="utf-8") as f:
                        json.dump({"port": int(port), "t": time.time()}, f)
                except Exception:
                    pass
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    def _flask_ok():
        """探活本实例 Flask：reload 前必须确认——主实例已退出（端口随机重换）
        时 reload 旧端口 = WebView2「无法连接」错误页挂在屏上（用户实锤）。"""
        import urllib.request
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:%s/api/status" % port, timeout=0.8)
            return True
        except Exception:
            return False

    def _arm_loop():
        """待命哨兵：主进程抓屏落 BMP（mtime 更新）→ reload 新底图弹出。
        Flask 连不通（孤儿窗）直接自杀，绝不让错误页见人。"""
        last = os.path.getmtime(_TMP_BMP) if os.path.isfile(_TMP_BMP) else 0
        idle_since = time.time()
        last_probe = 0.0
        while True:
            time.sleep(0.15)
            if time.time() - last_probe > 2:      # Flask 探活 2s 一次足够
                last_probe = time.time()
                if not _flask_ok():
                    os._exit(0)   # 主实例没了：静默退，下一次启动重新拉起
            try:
                m = os.path.getmtime(_TMP_BMP) if os.path.isfile(_TMP_BMP) else 0
            except OSError:
                continue
            if m > last:
                last = m
                state["showing"] = True      # _on_loaded 里 show
                try:
                    win.load_url(_page_url())
                except Exception:
                    pass
                idle_since = time.time()
            elif state["showing"]:
                idle_since = time.time()
            elif time.time() - idle_since > 600:
                os._exit(0)   # 空闲 10 分钟自退：内存归零，下次热键冷启动
    threading.Thread(target=_arm_loop, daemon=True).start()

    win.events.loaded += _on_loaded
    webview.start()          # 子进程消息循环，常驻直到 os._exit


# ---------------------------------------------------------------------------
# 主进程：剪贴板 + 启动器
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


def _self_exe_mode(flag, port=None, extra=()):
    args = [flag] + ([str(port)] if port is not None else []) + list(extra)
    if getattr(sys, "frozen", False):
        return [sys.executable] + args
    return [sys.executable, os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "snip.py")] + args


def grab():
    """主进程：spawn --grab 子进程抓屏（成功判据：产物 mtime 晚于调用时刻）。"""
    import time
    t0 = time.time()
    try:
        subprocess.run(_self_exe_mode("--grab"), timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    return os.path.isfile(_TMP_BMP) and os.path.getmtime(_TMP_BMP) > t0


def prewarm(port):
    """主进程启动预热：延时拉起常驻截图窗（首载不弹窗）。第一次热键即 <1s。"""
    def _go():
        time.sleep(10)          # 避开启动高峰（主窗渲染/依赖自检）
        try:
            if not snip_window_alive(port):
                _spawn_window(port, armed=False)   # 内含 8s 防抖
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True, name="snip-prewarm").start()


def snip_window_alive(port):
    """常驻截图窗探活（凭 ALIVE 标记）：port 匹配本实例 + 660s 内有心跳。
    只按窗口标题探活分不清实例——上一实例遗留的孤儿窗也叫 fc-snip，
    命中它会 reload 旧端口弹「无法连接」错误页（用户实锤）。"""
    try:
        with open(_TMP_ALIVE, "r", encoding="utf-8") as f:
            m = json.load(f)
        return (int(m.get("port") or 0) == int(port)
                and time.time() - float(m.get("t") or 0) < 660)
    except Exception:
        return False


def _spawn_window(port, armed):
    """拉起截图窗子进程（带 8s 防抖：热键冷启动与 prewarm 竞态双窗实锤位）。
    armed=True 首载即显（热键路径）；False 预热待命。"""
    if os.path.isfile(_TMP_SPAWN) and \
            time.time() - os.path.getmtime(_TMP_SPAWN) < 8:
        return True, "spawning"
    try:
        with open(_TMP_SPAWN, "w") as f:
            f.write("1")
        subprocess.Popen(_self_exe_mode(
            "--snip-window", port, extra=(["armed"] if armed else [])),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True, "ok"
    except Exception as e:
        return False, str(e)


def kill_snip_windows():
    """主进程退出时收编孤儿窗：给所有 fc-snip 窗发 WM_CLOSE。正常退出路径
    （✕/托盘退出）调；异常崩溃兜底靠子进程 _arm_loop 的 Flask 探活自杀。"""
    u32 = ctypes.windll.user32
    for _ in range(4):
        hwnd = u32.FindWindowW(None, "fc-snip")
        if not hwnd:
            return
        u32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
        time.sleep(0.15)


def launch_window(port):
    """主进程热键路径：先抓屏 → 常驻窗活着则它感知 BMP 更新自弹（<1s）；
    死了则 armed 冷启动（首载即显）。轮询收图逻辑不变。"""
    if os.path.isfile(_TMP_OUT):
        os.remove(_TMP_OUT)
    grab()                       # 抓屏落 BMP（mtime 更新驱动常驻窗 reload）
    if not snip_window_alive(port):
        ok, info = _spawn_window(port, armed=True)
        if not ok:
            return False, "截图窗启动失败：%s" % info

    def _collect():
        deadline = time.time() + 180
        while time.time() < deadline:
            if os.path.isfile(_TMP_OUT):
                time.sleep(0.1)   # 等写完（子进程先写完再退出，双保险）
                try:
                    with open(_TMP_OUT, "rb") as f:
                        raw = f.read()
                except OSError:
                    continue
                if not raw:
                    continue
                import uuid
                from src.claude_harness import _UPLOAD_DIR
                os.makedirs(_UPLOAD_DIR, exist_ok=True)
                path = os.path.join(_UPLOAD_DIR, "%s_snip.png" % uuid.uuid4().hex[:8])
                with open(path, "wb") as f:
                    f.write(raw)
                copy_png_to_clipboard(path)
                from src.app_state import _broadcast_to_ai
                _broadcast_to_ai({"kind": "ui_action", "action": "snip_done", "path": path})
                return
            time.sleep(0.3)

    threading.Thread(target=_collect, daemon=True).start()
    return True, "ok"


def save_png(data_url):
    """保留接口（HTTP 直存路径）。dataURL → 落 uploads + 复制剪贴板。"""
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


# ---------------------------------------------------------------------------
# 全局热键
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


def set_hotkey(hotkey_str):
    """热更新键位：'f1'/'ctrl+alt+a'/''（空=注销禁用）。返回 (ok, err)。"""
    u32 = ctypes.windll.user32
    s = str(hotkey_str or "").strip().lower()
    if not s:
        with _hk["lock"]:
            _hk["pending"] = None
            _hk["disabled"] = True
        _wake_hk_thread()
        return True, None
    hk = _parse_hotkey(s)
    if not hk:
        return False, "格式无效（示例 f1 / ctrl+alt+a；字母数字键需带修饰键）"
    if not u32.RegisterHotKey(None, 0xFC2, hk[0], hk[1]):
        return False, "热键被其他程序占用"
    u32.UnregisterHotKey(None, 0xFC2)
    with _hk["lock"]:
        _hk["pending"] = hk
        _hk["disabled"] = False
    _wake_hk_thread()
    return True, None


_hk = {"tid": 0, "pending": "UNSET", "disabled": False, "lock": threading.Lock()}
_WM_APP_SNIP = 0x8000 + 1


def _wake_hk_thread():
    if _hk["tid"]:
        ctypes.windll.user32.PostThreadMessageW(_hk["tid"], _WM_APP_SNIP, 0, 0)


def start_hotkey(hotkey_str, on_trigger):
    """启动全局热键线程并应用初始键位（热更新走 set_hotkey）。"""
    _start_hk_thread(on_trigger)
    if str(hotkey_str or "").strip():
        return set_hotkey(hotkey_str)
    return True, None


def _start_hk_thread(on_trigger):
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
        HOTKEY_ID = 0xFC1
        current = None
        msg = wintypes.MSG()
        while True:
            with _hk["lock"]:
                pend = _hk["pending"]
                disabled = _hk["disabled"]
                _hk["pending"] = "UNSET"
            if pend != "UNSET" or disabled:
                if current is not None:
                    u32.UnregisterHotKey(None, HOTKEY_ID)
                    current = None
                if not disabled and pend not in ("UNSET", None) and pend:
                    if u32.RegisterHotKey(None, HOTKEY_ID, pend[0], pend[1]):
                        current = pend
            r = u32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r <= 0:
                break
            if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                try:
                    threading.Thread(target=on_trigger, daemon=True).start()
                except Exception:
                    pass

    threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    if "--grab" in sys.argv:
        _dpi_aware()
        _grab_only()
    elif "--snip-window" in sys.argv:
        i = sys.argv.index("--snip-window")
        port = sys.argv[i + 1] if i + 1 < len(sys.argv) else "80"
        window_main(port, armed="armed" in sys.argv)
