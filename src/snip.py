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

_TMP_BMP = os.path.join(os.environ.get("TEMP", "."), "fc_snip.bmp")   # BMP 免编码
# 抓屏几何伴生文件（--grab 与 BMP 同批落盘）：底图已改 BMP、PNG 产物不复存在，
# 故独立定义路径，不再借废弃的 PNG 底图名拼接，避免误导读者以为还有 PNG 落盘
_TMP_GEO = os.path.join(os.environ.get("TEMP", "."), "fc_snip.bmp.geo.json")
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


# v3.5.149（用户实锤 Snipaste 按 F1 立刻响应）：热键信号走命名事件——主进程
# SetEvent <1ms 直达常驻截图窗进程，替代「spawn --grab 子进程（冷启动+落盘）
# + 0.15s mtime 轮询」的旧链路。事件名带 port：单实例下彻底规避跨实例串扰。
_SNIP_GO_EVENT = "Local\\fc_snip_go_%s"


def _open_event(name):
    """打开/创建命名事件（自动复位）。返回 HANDLE（0=失败转 None）。
    restype/argtypes 必须显式 c_void_p：默认 c_int 在 64 位下截断句柄
    （main.py 剪贴板实锤同款坑——SetEvent 带截断句柄静默失败）。"""
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateEventW.restype = ctypes.c_void_p
        k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_int, ctypes.c_wchar_p]
        # 注意：SetEvent/WaitForMultipleObjects 无 W 后缀变体（不带字符串参数
        # 的 API 不分 ANSI/Wide，kernel32 只导出裸名）——写 SetEventW 会在
        # argtypes 赋值时 AttributeError 'function not found' 被 except 吞掉
        k32.SetEvent.restype = ctypes.c_int
        k32.SetEvent.argtypes = [ctypes.c_void_p]
        k32.WaitForMultipleObjects.restype = ctypes.c_uint
        k32.WaitForMultipleObjects.argtypes = [ctypes.c_uint,
                                               ctypes.POINTER(ctypes.c_void_p),
                                               ctypes.c_int, ctypes.c_uint]
        k32.CloseHandle.restype = ctypes.c_int
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.CreateEventW(None, False, False, name)
        return h or None
    except Exception:
        return None


def set_go_event(port):
    """主进程热键 → 唤醒常驻截图窗（它自己进程内抓屏，免 spawn）。"""
    h = _open_event(_SNIP_GO_EVENT % port)
    if h:
        try:
            ctypes.windll.kernel32.SetEvent(h)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)   # v3.5.151 全审F6a：不再漏


# v3.5.150（用户拍板 Snipaste F3 同款）：贴图信号事件，同 go 事件机制
_SNIP_PIN_EVENT = "Local\\fc_snip_pin_%s"


def set_pin_event(port):
    """主进程 F3 → 唤醒常驻截图窗贴图（读剪贴板/req 直通）。"""
    h = _open_event(_SNIP_PIN_EVENT % port)
    if h:
        try:
            ctypes.windll.kernel32.SetEvent(h)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)   # v3.5.151 全审F6a：不再漏


def _cfg_flag(name, dflt=False):
    """读 config.json 布尔键（主进程用；贴图自动贴开关）。"""
    try:
        from src.app_state import CONFIG_FILE
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return bool(json.load(f).get(name, dflt))
    except Exception:
        return dflt


def read_clipboard_image():
    """读剪贴板图片（v3.5.150 F3 贴图数据源）。优先级：PNG 注册格式（无损带
    alpha，浏览器/新工具多写）→ CF_DIBV5(17) → CF_DIB(8) → CF_HDROP(15) 图片
    文件（资源管理器复制的白送支持）。返回 PIL.Image 或 None。
    全程 restype/argtypes 显式（64 位句柄截断，main.py 剪贴板实锤同款坑）。"""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    s32 = ctypes.windll.shell32
    for fn, restype, argtypes in (
            (k32.GlobalLock, wintypes.LPVOID, [wintypes.HGLOBAL]),
            (k32.GlobalUnlock, None, [wintypes.HGLOBAL]),
            (k32.GlobalSize, ctypes.c_size_t, [wintypes.HGLOBAL]),
            (u32.GetClipboardData, wintypes.HANDLE, [wintypes.UINT]),
            (u32.RegisterClipboardFormatW, wintypes.UINT, [wintypes.LPCWSTR]),
            (u32.IsClipboardFormatAvailable, wintypes.BOOL, [wintypes.UINT]),
            (s32.DragQueryFileW, wintypes.UINT, [wintypes.HANDLE, wintypes.UINT,
                                                 wintypes.LPWSTR, wintypes.UINT])):
        if restype is not None:
            fn.restype = restype
        fn.argtypes = argtypes

    def _hbytes(h):
        if not h:
            return b""
        p = k32.GlobalLock(h)
        try:
            n = k32.GlobalSize(h) or 0
            if not p or not n:
                return b""
            return ctypes.string_at(p, n)
        finally:
            k32.GlobalUnlock(h)

    # OpenClipboard 竞态：别的程序正占着 → 40ms 间隔重试 3 发
    opened = False
    for _ in range(3):
        if u32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.04)
    if not opened:
        return None
    try:
        from io import BytesIO
        import struct
        img = None

        def _dib_to_image(blob):
            """DIB 载荷 → 拼 BITMAPFILEHEADER → PIL（PIL 不收裸 DIB）。"""
            if len(blob) < 40:
                return None
            try:
                bisize = struct.unpack_from("<I", blob, 0)[0]
                bits = struct.unpack_from("<H", blob, 14)[0]
                comp = struct.unpack_from("<I", blob, 16)[0]
                off = 14 + bisize
                # BI_BITFIELDS 掩码紧随头只在经典 BITMAPINFOHEADER(40)——
                # V2/V3/V4/V5 头（52/56/108/124）掩码已含在 bisize 内，再
                # +12 越过像素起点（全审F3 实证 V5 双计解码失败）
                if comp == 3 and bits in (16, 32) and bisize == 40:
                    off += 12
                elif bits <= 8:                   # 调色板（biClrUsed 在 32：
                    nclr = struct.unpack_from("<I", blob, 32)[0] or (1 << bits)
                    off += nclr * 4               # 36 是 biClrImportant——
                                                  # v3.5.152 复核勘误：3.5.151
                                                  # 按误报改 36 读成 Important
                                                  # 反成回归，回到 32）
                fh = b"BM" + struct.pack("<IHHI", 14 + len(blob), 0, 0, off)
                from PIL import Image
                im = Image.open(BytesIO(fh + blob))
                im.load()
                return im
            except Exception:
                return None

        fmt_png = u32.RegisterClipboardFormatW("PNG")
        if fmt_png and u32.IsClipboardFormatAvailable(fmt_png):
            blob = _hbytes(u32.GetClipboardData(fmt_png))
            if blob[:8] == b"\x89PNG\r\n\x1a\n":
                try:
                    from PIL import Image
                    img = Image.open(BytesIO(blob))
                    img.load()
                except Exception:
                    img = None
        for fmt in ((17, 8) if img is None else ()):   # CF_DIBV5 → CF_DIB
            if u32.IsClipboardFormatAvailable(fmt):
                img = _dib_to_image(_hbytes(u32.GetClipboardData(fmt)))
                if img is not None:
                    break
        if img is None and u32.IsClipboardFormatAvailable(15):   # CF_HDROP
            h = u32.GetClipboardData(15)
            if h:
                n = s32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
                for i in range(n):
                    buf = ctypes.create_unicode_buffer(300)
                    if not s32.DragQueryFileW(h, i, buf, 300):
                        continue
                    ext = buf.value.rsplit(".", 1)[-1].lower() \
                        if "." in buf.value else ""
                    if ext in ("png", "jpg", "jpeg", "bmp", "gif", "webp"):
                        try:
                            from PIL import Image
                            img = Image.open(buf.value)
                            img.load()
                            break
                        except Exception:
                            pass
        if img is not None:
            # alpha 全 0 修补：32bpp DIB 的 alpha 常是全零填充 → 全透明/发黑
            #（历史实锤）；真透明图（PNG 剪贴）extrema 不会是 (0,0)
            try:
                if img.mode in ("RGBA", "LA"):
                    if img.getchannel("A").getextrema() == (0, 0):
                        img.putalpha(255)
            except Exception:
                pass
        return img
    except Exception:
        return None
    finally:
        try:
            u32.CloseClipboard()
        except Exception:
            pass


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
def window_main(port, armed=False, pin_pending=False):
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

    def _save_log(msg):
        """保存链路日志（TEMP）：间歇性失败要能事后定位。"""
        try:
            with open(os.path.join(os.environ.get("TEMP", "."),
                                   "fc_snip_save.log"), "a",
                      encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
        except Exception:
            pass

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
                # owner=截图窗（同进程）：不挂 owner 时对话框 z 序在全屏置顶
                # 截图窗之下（用户实锤「弹出来但看不见、卡死只能强关」）；
                # 模态挂 owner 后系统强制对话框显示在 owner 之上。
                owner = None
                try:
                    from System import IntPtr
                    from System.Windows.Forms import Control
                    hwnd = ctypes.windll.user32.FindWindowW(None, "fc-snip")
                    if hwnd:
                        owner = Control.FromHandle(IntPtr(hwnd))
                except Exception:
                    owner = None
                # DialogResult 是 pythonnet 枚举：coreclr 运行时下与 int 的
                # == 比较不可靠（恒 False → 「确认」被当取消，一个都存不下
                # 的实锤位）。str 判为主、int 兜底（转换也可能炸，再包一层）。
                res = dlg.ShowDialog(owner)
                _save_log("ShowDialog 返回: %r" % res)
                _ok = str(res) == "OK"
                if not _ok:
                    try:
                        _ok = int(res) == 1
                    except Exception:
                        pass
                if _ok:
                    result["path"] = dlg.FileName
            except Exception:
                pass

        t = Thread(ThreadStart(_run))
        t.SetApartmentState(ApartmentState.STA)
        t.Start()
        t.Join()
        return result.get("path")

    state = {"armed": armed, "showing": False, "pin_pending": pin_pending}

    def _die():
        """自退唯一出口（v3.5.151 全审F1）：先删 ALIVE 探活标记再退——30s
        周期心跳让死前标记恒新鲜，660s 容忍下直接退=死后 ~10 分钟「假活
        死区」（SetEvent 发进无人等的事件，F1/F3 反复按反复无响应）。删标
        记使死亡即刻可见，主进程下一击即走冷启动重拉。"""
        try:
            os.remove(_TMP_ALIVE)
        except OSError:
            pass
        os._exit(0)

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
            用户定调：保存就是保存）。取消对话框=放弃当次，同样收起。
            全程写 TEMP 日志：间歇失败要能定位（用户实锤「多次一个没存下」）。"""
            try:
                import base64
                raw = base64.b64decode((data_url or "").split(",", 1)[-1])
            except Exception as e:
                raw = b""
                _save_log("decode 失败: %r" % e)
            _save_log("snip_save_as 收图 %d bytes" % len(raw))

            def _ask():
                path = _save_dialog()
                _save_log("对话框结果: %r" % path)
                if path and raw:
                    try:
                        with open(path, "wb") as f:
                            f.write(raw)
                        _save_log("已写入 %s (%d bytes)" % (path, len(raw)))
                    except Exception as e:
                        _save_log("写入失败 %s: %r" % (path, e))
                _hide()
            threading.Thread(target=_ask, daemon=True).start()
            return True

        def snip_cancel(self):
            _hide()
            return True

    # ---- v3.5.150 贴图（pin）子系统：常驻进程 pywebview 多窗，每贴一张
    # 一个独立置顶无边框小窗（Snipaste F3 同款）。随工具存亡：主进程退出
    # kill_snip_windows EnumWindows 收编 + 本进程 Flask 探活自杀兜底。 ----
    _pins = {}          # n -> {"wv": 窗对象, "w": 原图宽, "h": 原图高, "t": 创建时刻}
    _pin_seq = [0]
    _pin_lock = threading.Lock()   # v3.5.151 全审F6c：seq 分配/LRU 原子化
    _MAX_PINS = 8       # 内存护栏：每贴一张≈一个 WebView2 渲染进程（40-80MB）
    _PIN_DIR = os.environ.get("TEMP", ".")
    try:                # 启动清扫上次会话贴图残留（v3.5.151 全审F4）
        for _f in os.listdir(_PIN_DIR):
            if _f.startswith("fc_pin_") and _f.endswith(".png"):
                try:
                    os.remove(os.path.join(_PIN_DIR, _f))
                except OSError:
                    pass
    except OSError:
        pass

    class RECTr(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    class PTxy(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def _pin_hwnd(n):
        return ctypes.windll.user32.FindWindowW(None, "fc-pin-%d" % n)

    def _pin_close(n):
        info = _pins.pop(n, None)
        try:
            if info and info.get("wv"):
                info["wv"].destroy()
        except Exception:
            pass
        try:            # v3.5.151 全审F4：底图同删，%TEMP% 不留贴图尸体
            os.remove(os.path.join(_PIN_DIR, "fc_pin_%d.png" % n))
        except OSError:
            pass

    def _pin_resize(n, nw, nh):
        """改贴图窗尺寸，鼠标点锚定（缩放不漂移）。全程物理像素+SetWindowPos，
        绕开 pywebview 逻辑像素换算（DPI>100% 混淆源）。"""
        u32 = ctypes.windll.user32
        hwnd = _pin_hwnd(n)
        if not hwnd or nw < 80 or nh < 80:
            return
        rc = RECTr()
        if not u32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return
        pt = PTxy()
        u32.GetCursorPos(ctypes.byref(pt))
        k2 = nw / max(1, rc.r - rc.l)
        u32.SetWindowPos(hwnd, -1,                 # -1=TOPMOST 重申置顶
                         int(pt.x - (pt.x - rc.l) * k2),
                         int(pt.y - (pt.y - rc.t) * k2),
                         int(nw), int(nh), 0x0040)

    def _pin_drag(n, dx, dy):
        """按像素拖动。dx/dy 是 CSS px——乘窗口 DPI 比回物理。"""
        u32 = ctypes.windll.user32
        hwnd = _pin_hwnd(n)
        if not hwnd:
            return
        rc = RECTr()
        if not u32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return
        u32.GetDpiForWindow.restype = ctypes.c_uint
        k = (u32.GetDpiForWindow(hwnd) or 96) / 96.0
        u32.SetWindowPos(hwnd, -1,
                         rc.l + int(dx * k), rc.t + int(dy * k),
                         0, 0, 0x0001 | 0x0010 | 0x0040)   # NOSIZE|NOACTIVATE

    def _pin_alpha(n, pct):
        u32 = ctypes.windll.user32
        hwnd = _pin_hwnd(n)
        if not hwnd:
            return
        u32.SetWindowLongW(hwnd, -20,              # GWL_EXSTYLE |= WS_EX_LAYERED
                           u32.GetWindowLongW(hwnd, -20) | 0x00080000)
        u32.SetLayeredWindowAttributes(hwnd, 0,
                                       max(25, min(255, int(255 * pct / 100))), 2)

    def _pin_fit(n, orig_w, orig_h):
        """适应屏幕：光标所在屏工作区 90% 完整显示，居中。"""
        u32 = ctypes.windll.user32
        hwnd = _pin_hwnd(n)
        if not hwnd:
            return
        pt = PTxy()
        u32.GetCursorPos(ctypes.byref(pt))
        hmon = u32.MonitorFromPoint(pt, 2)         # MONITOR_DEFAULTTONEAREST

        class MINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("rcMonitor", RECTr),
                        ("rcWork", RECTr), ("dwFlags", ctypes.c_uint)]
        mi = MINFO()
        mi.cbSize = ctypes.sizeof(MINFO)
        if not u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return
        rc = mi.rcWork
        mw, mh = rc.r - rc.l, rc.b - rc.t
        sc = min(0.9 * mw / max(1, orig_w), 0.9 * mh / max(1, orig_h))
        nw, nh = max(80, int(orig_w * sc)), max(80, int(orig_h * sc))
        u32.SetWindowPos(hwnd, -1, rc.l + (mw - nw) // 2, rc.t + (mh - nh) // 2,
                         nw, nh, 0x0040)

    class PinWin:
        """贴图窗 js_api（pin.html 调）：拖动/缩放/透明度/关闭/适应屏幕。"""

        def __init__(self, n, w, h):
            self.n, self.w, self.h = n, w, h

        def close(self):
            _pin_close(self.n)
            return True

        def drag_by(self, dx, dy):
            try:
                _pin_drag(self.n, float(dx or 0), float(dy or 0))
            except Exception:
                pass
            return True

        def zoom(self, direction):
            """滚轮缩放：原图 2.5x 与虚拟屏 1.25x 双上限，80px 下限。"""
            try:
                cur = _pins.get(self.n) or {}
                hwnd = _pin_hwnd(self.n)
                rc = RECTr()
                if hwnd and ctypes.windll.user32.GetWindowRect(
                        hwnd, ctypes.byref(rc)):
                    cw = rc.r - rc.l
                else:
                    cw = int(cur.get("w") or self.w)
                nw = cw * (1.15 if int(direction or 0) > 0 else 1 / 1.15)
                g = _virt_geo()
                nw = max(80, min(int(nw), int(cur.get("w") or self.w) * 5 // 2,
                                 int(g["w"] * 1.25)))
                nh = max(80, int(nw * self.h / max(1, self.w)))
                _pin_resize(self.n, nw, nh)
            except Exception:
                pass
            return True

        def scale_pct(self, pct):
            """右键菜单预设：相对原图 50/100/200%。"""
            try:
                _pin_resize(self.n,
                            max(80, int(self.w * int(pct) / 100)),
                            max(80, int(self.h * int(pct) / 100)))
            except Exception:
                pass
            return True

        def fit_screen(self):
            try:
                _pin_fit(self.n, self.w, self.h)
            except Exception:
                pass
            return True

        def opacity(self, pct):
            try:
                _pin_alpha(self.n, int(pct or 100))
            except Exception:
                pass
            return True

    def _create_pin(img):
        """贴一张：图落 TEMP/fc_pin_<n>.png（/api/snip/pinimg 服务给页面）
        → 建无边框置顶窗（loaded 后钉物理尺寸+去任务栏+show，snip 窗同款
        手法——create 的 width/height 是逻辑口径，必须重钉）。"""
        try:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        except Exception:
            return
        w, h = img.size
        if not w or not h:
            return
        with _pin_lock:            # F3 连发+自动贴并发：seq 分配原子
            _pin_seq[0] += 1
            n = _pin_seq[0]
        path = os.path.join(_PIN_DIR, "fc_pin_%d.png" % n)
        try:
            img.save(path)
        except Exception:
            return
        g = _virt_geo()
        sc = min(1.0, (g["w"] * 0.9) / max(1, w), (g["h"] * 0.9) / max(1, h))
        pw, ph = max(80, int(w * sc)), max(80, int(h * sc))
        pin = PinWin(n, w, h)
        try:
            wv = webview.create_window(
                "fc-pin-%d" % n,
                "http://127.0.0.1:%s/web/pin.html?id=%d" % (port, n),
                js_api=pin,
                x=min(max(0, g["x"] + g["w"] // 2 - pw // 2), g["x"] + g["w"] - pw),
                y=min(max(0, g["y"] + g["h"] // 2 - ph // 2), g["y"] + g["h"] - ph),
                width=pw, height=ph,
                frameless=True, on_top=True, resizable=False,
                easy_drag=False, shadow=False, hidden=True)
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            return
        _pins[n] = {"wv": wv, "w": w, "h": h, "t": time.time()}
        with _pin_lock:            # LRU 淘汰最旧（选 key 锁内、销毁锁外）
            old = min(_pins, key=lambda k: _pins[k]["t"]) \
                if len(_pins) > _MAX_PINS else None
        if old is not None:
            _pin_close(old)

        def _pin_loaded():
            tries = [0]

            def _do():
                try:
                    time.sleep(0.2)
                    if wv.evaluate_js("window.__FC_PIN__===true") is not True:
                        # v3.5.153：错误页不再一关了之（用户只见「没反应」）
                        # ——重试加载 2 次（WebGUI 冷启竞态实锤形态），仍败才关
                        tries[0] += 1
                        if tries[0] <= 2:
                            try:
                                wv.load_url("http://127.0.0.1:%s/web/pin.html?id=%d"
                                            % (port, n))
                            except Exception:
                                pass
                            return          # load_url 完成会再触发 loaded
                        _pin_close(n)       # 错误页绝不 show
                        return
                    u32 = ctypes.windll.user32
                    hwnd = _pin_hwnd(n)
                    if hwnd:
                        u32.SetWindowLongW(hwnd, -20,
                                           u32.GetWindowLongW(hwnd, -20) | 0x80)
                    try:
                        from System import Func, Type
                        from System.Drawing import Size
                        native = wv.native

                        def _fix():
                            native.ClientSize = Size(pw, ph)
                        native.Invoke(Func[Type](_fix))
                    except Exception:
                        if hwnd:                   # CLR 不可用兜底（会被弹回）
                            u32.SetWindowPos(hwnd, -1, 0, 0, pw, ph, 0x0040)
                    if hwnd:
                        u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                         0x0001 | 0x0002 | 0x0040)
                    wv.show()
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()
        wv.events.loaded += _pin_loaded

    def _handle_pin():
        """贴图入口（pin 事件唤醒）：req 直通（截图自动贴，保 alpha 不走剪贴
        板时序）→ 剪贴板读图（PNG/DIB/文件三源）。"""
        try:
            img = None
            req = os.path.join(os.environ.get("TEMP", "."), "fc_pin_req.json")
            if os.path.isfile(req):
                try:
                    with open(req, encoding="utf-8") as f:
                        m = json.load(f)
                except Exception:
                    m = None
                try:
                    os.remove(req)
                except OSError:
                    pass
                p = (m or {}).get("path") or ""
                if p and os.path.isfile(p):
                    try:
                        from PIL import Image
                        img = Image.open(p)
                        img.load()
                    except Exception:
                        img = None
            if img is None:
                img = read_clipboard_image()
            if img is None:
                return
            _create_pin(img)
        except Exception:
            pass

    if pin_pending:
        state["pin_pending"] = True   # 冷路径：首载 loaded 后贴一次（_on_loaded 消费）

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
                        _die()
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
                # v3.5.150：冷路径贴图（spawn 带 pin 参）→ 首载后贴一次
                if state.get("pin_pending"):
                    state["pin_pending"] = False
                    threading.Thread(target=_handle_pin, daemon=True).start()
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
        """待命哨兵 v3.5.149：命名事件主等（<1ms）+ 150ms 超时兜底（mtime
        轮询/Flask 探活原逻辑全保留）。go 事件 → 进程内抓屏（本进程已 DPI
        aware，免 spawn 子进程免冷启动）→ 几何未变走 evaluate_js 免 reload
        唤醒；几何变了/唤醒失败回落整页 reload（旧路永在）。"""
        last = os.path.getmtime(_TMP_BMP) if os.path.isfile(_TMP_BMP) else 0
        idle_since = time.time()
        last_probe = 0.0
        last_beat = 0.0
        ev_go = _open_event(_SNIP_GO_EVENT % port)
        ev_pin = _open_event(_SNIP_PIN_EVENT % port)
        kinds, hs = [], []
        for ev, kind in ((ev_go, "go"), (ev_pin, "pin")):
            if ev:
                kinds.append(kind)
                hs.append(ev)
        handles = None
        if hs:
            handles = (ctypes.c_void_p * len(hs))(
                *[ctypes.c_void_p(h) for h in hs])
        while True:
            fired = None
            if handles:
                # WAIT_OBJECT_0+i：对应事件触发（0=go / 1=pin）；超时(0x102)
                # 走兜底轮询。原型已在 _open_event 统一声明
                r = ctypes.windll.kernel32.WaitForMultipleObjects(
                    len(hs), handles, False, 150)
                if 0 <= r < len(hs):
                    fired = kinds[r]
            else:
                time.sleep(0.15)
            now = time.time()
            # v3.5.149 心跳周期写：免 reload 后 loaded 不再周期发生，而
            # snip_window_alive 靠 ALIVE 心跳判活（660s 容忍）——停更=主进程
            # 误判窗已死再 spawn=双窗实锤回归，30s 一写必须与免 reload 同笔
            if now - last_beat > 30:
                last_beat = now
                try:
                    with open(_TMP_ALIVE, "w", encoding="utf-8") as f:
                        json.dump({"port": int(port), "t": now}, f)
                except Exception:
                    pass
            if now - last_probe > 2:      # Flask 探活 2s 一次足够
                last_probe = now
                if not _flask_ok():
                    _die()   # 主实例没了：静默退，下一次启动重新拉起
            try:
                m = os.path.getmtime(_TMP_BMP) if os.path.isfile(_TMP_BMP) else 0
            except OSError:
                continue
            if fired == "pin":
                # v3.5.150 贴图：读 req/剪贴板 → 建独立置顶窗（不动截图主窗）
                idle_since = time.time()
                threading.Thread(target=_handle_pin, daemon=True).start()
            elif fired == "go":
                # v3.5.152 全审F6b：收到事件即刷心跳——「ALIVE <10s 新鲜」
                # 的语义自此成立（事件必达=心跳必新；事件未达=心跳陈旧→
                # launch_window 的 _check 兜底 grab 正确放行，不再被
                # 30s 周期心跳的随机龄误拦）
                try:
                    with open(_TMP_ALIVE, "w", encoding="utf-8") as f:
                        json.dump({"port": int(port), "t": time.time()}, f)
                except Exception:
                    pass
                # 主路径：进程内抓屏（60-120ms）+ 免 reload 唤醒
                try:
                    _grab_only()
                except Exception:
                    pass
                last = os.path.getmtime(_TMP_BMP) if os.path.isfile(_TMP_BMP) else last
                g = _virt_geo()
                same = True
                try:
                    same = (win.x == g["x"] and win.y == g["y"]
                            and win.width == g["w"] and win.height == g["h"])
                except Exception:
                    pass
                state["showing"] = True
                idle_since = time.time()
                if same:
                    try:
                        win.evaluate_js("window.__snipArm && __snipArm()")
                        win.show()
                        hwnd = ctypes.windll.user32.FindWindowW(None, "fc-snip")
                        if hwnd:
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception:
                        try:     # 页面假死/WebView2 崩：回落整页 reload
                            win.load_url(_page_url())
                        except Exception:
                            pass
                else:
                    try:         # 几何变了：整页 reload 走 _on_loaded 重钉尺寸
                        win.load_url(_page_url())
                    except Exception:
                        pass
            elif m > last:
                last = m
                state["showing"] = True      # _on_loaded 里 show
                try:
                    win.load_url(_page_url())
                except Exception:
                    pass
                idle_since = time.time()
            elif state["showing"] or _pins:
                idle_since = time.time()   # 贴图挂着=进程有活干，绝不自退
            elif not _pins and time.time() - idle_since > 1800:
                _die()   # 空闲 30 分钟自退（v3.5.153：600→1800——用户节奏
                         # 「放置十几分钟再截」正落 600s 窗外=每次首截都是
                         # 冷启动慢；常驻待命 ~100MB，30 分钟不用才释放）
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
    """主进程启动预热（v3.5.153 提前）：延时拉起常驻截图窗（首载不弹窗），
    第一次热键即 <1s。旧 10s 延迟=启动后立刻按 F1 常驻窗未起走冷启动
    （spawn python+WebView2 冷启 ~2s，用户实锤「首次还是慢」）。"""
    def _go():
        time.sleep(3)           # 避开主窗创建最高峰，2~3s 内常驻窗就位
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


def _spawn_window(port, armed, pin_pending=False):
    """拉起截图窗子进程（带 8s 防抖：热键冷启动与 prewarm 竞态双窗实锤位）。
    armed=True 首载即显（热键路径）；False 预热待命；pin_pending=True 冷路径
    贴图（首载后贴一次）。"""
    if os.path.isfile(_TMP_SPAWN) and \
            time.time() - os.path.getmtime(_TMP_SPAWN) < 8:
        return True, "spawning"
    try:
        with open(_TMP_SPAWN, "w") as f:
            f.write("1")
        subprocess.Popen(_self_exe_mode(
            "--snip-window", port,
            extra=(["armed"] if armed else []) + (["pin"] if pin_pending else [])),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True, "ok"
    except Exception as e:
        return False, str(e)


def kill_snip_windows():
    """主进程退出时收编孤儿窗：fc-snip 主窗 + 全部 fc-pin-* 贴图窗发 WM_CLOSE
    （v3.5.150 EnumWindows 前缀匹配；正常退出路径调，异常崩溃兜底靠子进程
    Flask 探活自杀）。"""
    u32 = ctypes.windll.user32
    targets = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                     ctypes.c_void_p)

    @WNDENUMPROC
    def _cb(hwnd, _lp):
        try:
            buf = ctypes.create_unicode_buffer(64)
            u32.GetWindowTextW(hwnd, buf, 64)
            t = buf.value
            if t == "fc-snip" or t.startswith("fc-pin-"):
                targets.append(hwnd)
        except Exception:
            pass
        return True

    try:
        u32.EnumWindows(_cb, 0)
    except Exception:
        pass
    for hwnd in targets:
        u32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    for _ in range(4):                          # 残留兜底（snip 主窗单实例）
        hwnd = u32.FindWindowW(None, "fc-snip")
        if not hwnd:
            return
        u32.PostMessageW(hwnd, 0x0010, 0, 0)
        time.sleep(0.15)


def launch_window(port):
    """主进程热键路径 v3.5.149：常驻窗活着 → 命名事件唤醒（它进程内抓屏，
    免 spawn 子进程）；死了 → 冷路径 spawn --grab + armed 窗。事件链路失效
    由 1s 核查兜底补旧路。收图逻辑不变。"""
    t0 = time.time()
    if os.path.isfile(_TMP_OUT):
        os.remove(_TMP_OUT)
    if snip_window_alive(port):
        set_go_event(port)

        def _check():
            # v3.5.151 全审F6b：兜底判据从「mtime 未变」改为「ALIVE 心跳不
            # 新鲜」——心跳 <10s 新鲜 = 常驻窗活着且必在等本 port 的事件
            #（SetEvent 必达），只是抓屏慢；补 grab 反而与常驻窗 _grab_only
            # 双写撕裂底图。心跳陈旧 = 窗真死（_die 已删标记，此处读不到），
            # 补旧路落盘供冷启动。
            time.sleep(1.5)
            try:
                with open(_TMP_ALIVE, encoding="utf-8") as f:
                    if time.time() - float(json.load(f).get("t") or 0) < 10:
                        return
            except Exception:
                pass
            m = os.path.getmtime(_TMP_BMP) if os.path.isfile(_TMP_BMP) else 0
            if m <= t0:
                grab()
        threading.Thread(target=_check, daemon=True).start()
    else:
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
                # v3.5.150 自动贴图（config snip_auto_pin，设置页开关）：req
                # 文件直通 uploads 原图（保 alpha，不吃剪贴板时序）+ pin 事件
                if _cfg_flag("snip_auto_pin"):
                    try:
                        with open(os.path.join(os.environ.get("TEMP", "."),
                                               "fc_pin_req.json"),
                                  "w", encoding="utf-8") as f:
                            json.dump({"path": path}, f)
                        set_pin_event(port)
                    except Exception:
                        pass
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


def set_hotkey(hotkey_str, slot="snip"):
    """热更新键位（v3.5.150 多槽）：'f1'/'ctrl+alt+a'/''（空=注销禁用）。
    slot：snip=截图（0xFC1）/ pin=贴图（0xFC3）。返回 (ok, err)。"""
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
    """启动全局热键线程并应用初始键位（热更新走 set_hotkey）。
    slot 见 set_hotkey；旧调用 start_hotkey(hk, cb) 语义不变。"""
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
    if "--grab" in sys.argv:
        _dpi_aware()
        _grab_only()
    elif "--snip-window" in sys.argv:
        i = sys.argv.index("--snip-window")
        port = sys.argv[i + 1] if i + 1 < len(sys.argv) else "80"
        window_main(port, armed="armed" in sys.argv,
                    pin_pending="pin" in sys.argv)
