# -*- coding: utf-8 -*-
"""网页 tab 控制器（a544 终局形态）——WebView2 多控件内嵌真浏览器。

架构（用户拍板「最终形态」）：每个网页 tab = 一个完整的 WebView2 浏览器
控件实例（与 Edge 标签页同级），不再是 iframe + 代理。XFO/CSP/
document.domain/防盗链等 iframe 时代的一切限制结构性消失。

职责：
- 控件生命周期：create（tab 开）/ dispose（tab 关），全部 WinForms 控件
  操作经 BeginInvoke 走 UI 线程（Flask 线程直操作会崩）
- 导航/历史：navigate/goBack/goForward/reload（原生历史栈）
- NewWindowRequested → 通知前端开新 tab（每控件一个处理器）
- SourceChanged/HistoryChanged → ExecuteScriptAsync 推给前端
  （地址栏/按钮态跟随，与 a484 的 ExecuteScriptAsync 先例同款
  fire-and-forget——绝不能 evaluate_js 等 UI 线程）
- 布局：前端上报 web-pane 的 getBoundingClientRect（DIP），转物理像素
  设 Bounds；切 tab = 显示/隐藏控件
"""
import json
import threading

_tabs = None            # WebTabs 单例（main._patched_ready 装配）
_HIDE_ALL = "__all__"    # R6 审计 W32：全隐哨兵（切回阅读态 tab）——前端 tab id
                         # 恒为 web[:<epoch>]:<n> 形态（D1 未合时无 epoch 段），
                         # 永不与该哨兵碰撞

# a552 密码自动填充（用户强需求）。a557 曾因 SSO 锁号疑云默认关；a558 已
# 实证锁号真凶是临时测试实例的自动登录/互踢（与浏览器自动填充无关），
# a560 恢复开。配套 _ANTI_AUTOSIGNIN_JS 兜底：密码表单 submit 无近 3s
# 用户手势即拦截——Chromium「自动签到」若走 submit 事件则被拦；若内核
# 绕过事件直提则不设防（已知边界，实测未见由它引发的登录计数）。
WEB_TAB_PASSWORD_AUTOFILL = True

# a557：防自动签到脚本——密码表单 submit 若无近 3s 用户手势（pointerdown/
# keydown）则拦截。浏览器 auto sign-in 无手势必被拦；用户真实点击/回车
# 天然带手势不受影响。注入每个控件的所有后续文档（含跨域页，浏览器级）。
_ANTI_AUTOSIGNIN_JS = (
    "// a582（内网方案·根因3）：原 var g=0 使 Date.now()-0 恒>3000 →"
    "// 所有提交（含 cookie 自动登录）全被拦 = 登录态记忆失效。"
    "// 语义=最近 3 秒内无手势才拦（自动签到防护不变）"
    "(function(){var g=Date.now();"
    "addEventListener('pointerdown',function(){g=Date.now()},true);"
    "addEventListener('keydown',function(){g=Date.now()},true);"
    "addEventListener('submit',function(e){try{"
    "var f=e.target;if(!f||!f.querySelector)return;"
    "if(!f.querySelector('input[type=password]'))return;"
    "if(Date.now()-g>3000){e.preventDefault();}"
    "}catch(_){}},true);})();")

# a557：SSO 页面命中日志——控制台直接可见「谁在频繁打 SSO」（诊断锁号）
_SSO_HOSTS = ("sso.hikvision.com", "moa.hikvision.com")


# ---------- 原生密码库管理器（a583，用户令：🔑 显示/删改已存密码） ----------
def _pwdb_path():
    import os
    return os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "fc_webview_tabs", "EBWebView", "Default", "Login Data")


def _pwdb_copy():
    """运行中的库被 Chromium 锁定——复制到临时文件读（共享读实测可行）。"""
    import os, shutil, tempfile
    src = _pwdb_path()
    if not os.path.exists(src):
        return None
    dst = os.path.join(tempfile.mkdtemp(), "LD.db")
    try:
        shutil.copyfile(src, dst)
        return dst
    except Exception:
        return None


def _pw_v10_key():
    """v10 密钥：Local State os_crypt.encrypted_key（DPAPI 前缀 → 32B AES）。
    实测本机 WebView2 未启用 App-Bound（经典 v10，同用户可解）。"""
    import os, json, base64, ctypes
    from ctypes import wintypes

    class _B(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]
    ls = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                      "fc_webview_tabs", "EBWebView", "Local State")
    try:
        ek = json.load(open(ls, encoding="utf-8"))["os_crypt"]["encrypted_key"]
        raw = base64.b64decode(ek)
        if raw[:5] != b"DPAPI":
            return None      # app-bound v20 形态（本机实测不是）
        cin = _B(len(raw) - 5,
                 ctypes.cast(ctypes.create_string_buffer(raw[5:]),
                             ctypes.POINTER(ctypes.c_char)))
        cout = _B()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(cin), None, None, None, None, 1,
                ctypes.byref(cout)):
            return None
        out = ctypes.string_at(cout.pbData, cout.cbData)
        ctypes.windll.kernel32.LocalFree(cout.pbData)
        return out
    except Exception:
        return None


def _pw_decrypt(blob):
    """三层：DPAPI 前缀（最老）/ v10·v11（AES-GCM）/ v20（app-bound，
    本机 WebView2 实测不启用——留降级提示）。返回 (ok, text)。"""
    import ctypes
    from ctypes import wintypes
    if not blob:
        return False, ""
    if blob[:5] == b"DPAPI":
        class _B(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]
        cin = _B(len(blob) - 5,
                 ctypes.cast(ctypes.create_string_buffer(blob[5:]),
                             ctypes.POINTER(ctypes.c_char)))
        cout = _B()
        if ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(cin), None, None, None, None, 1,
                ctypes.byref(cout)):
            out = ctypes.string_at(cout.pbData, cout.cbData)
            ctypes.windll.kernel32.LocalFree(cout.pbData)
            return True, out.decode("utf-8", "replace")
        return False, "DPAPI 解密失败"
    if blob[:3] in (b"v10", b"v11"):
        key = _pw_v10_key()
        if not key:
            return False, "v10 密钥不可用"
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            pt = AESGCM(key).decrypt(blob[3:15], blob[15:], None)
            return True, pt.decode("utf-8", "replace")
        except ImportError:
            return False, "缺 cryptography 库"
        except Exception as e:
            return False, "AES-GCM: %r" % e
    return False, "app-bound v20 密文（暂不支持明文显示）"


def _pw_entries():
    """读全部条目：[{origin, user}]（不携带密文/明文出后端边界）。"""
    import sqlite3
    db = _pwdb_copy()
    if not db:
        return []
    try:
        con = sqlite3.connect(db)
        rows = con.execute(
            "SELECT origin_url, username_value FROM logins "
            "ORDER BY origin_url").fetchall()
        con.close()
        return [{"origin": r[0], "user": r[1] or ""} for r in rows if r[0]]
    finally:
        # RA3（红队）：库副本含全部用户名/足迹——不留 %TEMP%
        import os as _os
        try:
            _os.remove(db)
        except Exception:
            pass


def _pw_pending_file():
    import os
    from src.app_state import DATA_DIR
    return os.path.join(DATA_DIR, "pw_pending_del.json")


_pw_del_lock = threading.Lock()


def _pw_del_defer(origin, user):
    """运行中库被锁（Chromium 常驻）→ 挂 pending，退出流程（浏览器已停）
    统一执行。立即尝试写入，成功则当场生效。
    RA4：user=None 删全部（兼容），否则按 origin+user 精确。
    RA5：挂起文件读-改-写全程持锁 + 临时文件原子替换。"""
    import json, os, sqlite3, tempfile
    con = None
    try:
        con = sqlite3.connect(_pwdb_path(), timeout=0.3)
        if user is None:
            con.execute("DELETE FROM logins WHERE origin_url=?", (origin,))
        else:
            con.execute("DELETE FROM logins WHERE origin_url=? AND "
                        "username_value=?", (origin, user))
        con.commit()
        return True     # 库恰好空闲（无网页 tab）——立即生效
    except Exception:
        pass
    finally:
        # RA18（红队复验）：连接必须关闭——滞留句柄锁真实库（实测
        # PermissionError 需 GC 才释放）
        try:
            if con is not None:
                con.close()
        except Exception:
            pass
    with _pw_del_lock:
        try:
            p = _pw_pending_file()
            lst = []
            if os.path.exists(p):
                try:
                    lst = json.load(open(p, encoding="utf-8")) or []
                except Exception:
                    # RA6（红队）：损坏的挂起文件不再静默吞——清空重建并告警
                    lst = []
                    _log("WARN", "pw_pending_del.json 损坏，已重建")
            item = [origin, user]
            if item not in lst:
                lst.append(item)
            # RA5：原子写（临时文件 + os.replace），防截断丢全部记录
            tmp = p + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(lst, f, ensure_ascii=False)
                os.replace(tmp, p)   # RC9：原子替换（失败残留 .tmp 由 except 清）
            except Exception:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                raise
            return False    # 已挂起，退出后生效
        except Exception as e:
            _log("WARN", "pw_del_defer: %r" % e)
            return False


def _pw_del_flush():
    """退出流程调用（浏览器进程已停、库解锁）：执行挂起的删除。
    RA15（红队复验）：验证删除确实生效才删挂起文件——库缺失/0 字节假库/
    语句失败时保留挂起文件（下次退出重试），绝不假成功。损坏文件重建时
    WARN（RA16 同源）。"""
    import json, os, sqlite3
    p = _pw_pending_file()
    if not os.path.exists(p):
        return
    try:
        lst = json.load(open(p, encoding="utf-8")) or []
    except Exception as e:
        _log("WARN", "pw_del_flush 挂起文件损坏，已放弃: %r" % e)
        return
    if not lst:
        try:
            os.remove(p)   # 空挂起（历史遗留）清理
        except Exception:
            pass
        return
    dbp = _pwdb_path()
    if not os.path.exists(dbp) or os.path.getsize(dbp) == 0:
        # RA15：库缺失/0字节（上次异常退出造出的假库）——保留挂起，不造假
        _log("WARN", "pw_del_flush: 密码库缺失或空——挂起保留待下次退出重试")
        return
    try:
        con = sqlite3.connect(dbp)
        cur = con.cursor()
        for it in lst:
            if isinstance(it, list) and len(it) == 2:
                o, u = it   # RA4：二元组 [origin, user] 精确删；旧格式字符串按全 origin（兼容）
            else:
                o, u = it, None
            try:
                if u is None or u == "":
                    # RW8（终审）：空串 user 与 NULL 行等价（登录页无用户名
                    # 时 Chromium 存 NULL）——两者都删，否则复核永真滞留
                    cur.execute("DELETE FROM logins WHERE origin_url=? AND "
                                "(username_value IS NULL OR username_value='')",
                                (o,))
                else:
                    cur.execute("DELETE FROM logins WHERE origin_url=? AND "
                                "username_value=?", (o, u))
            except Exception:
                pass
        con.commit()
        con.close()
        # RA15/RW4（终审）：删后复核——复核自身失败（锁库）也保留挂起，
        # 绝不 os.remove 假成功；上次版本复核 except 吞掉后照删=假成功
        # 实测（14.65s 锁等待、pending 消失、行未删）。
        remain = -1   # -1=复核未完成（保留挂起，下次重试）
        try:
            con2 = sqlite3.connect(dbp, timeout=0.3)
            remain = 0
            for it in lst:
                o, u = (it if isinstance(it, list) and len(it) == 2 else (it, None))
                if u is None or u == "":
                    row = con2.execute(
                        "SELECT 1 FROM logins WHERE origin_url=? AND "
                        "(username_value IS NULL OR username_value='')",
                        (o,)).fetchone()
                else:
                    row = con2.execute(
                        "SELECT 1 FROM logins WHERE origin_url=? AND "
                        "username_value=?", (o, u)).fetchone()
                if row:
                    remain += 1
            con2.close()
        except Exception:
            remain = -1
        if remain > 0:
            _log("WARN", "pw_del_flush: %d 条未删净——挂起保留" % remain)
            return
        if remain == -1:
            _log("WARN", "pw_del_flush: 复核失败——挂起保留待重试")
            return
        os.remove(p)
        _log("INFO", "pw_del_flush: %d 条已删" % len(lst))
    except Exception as e:
        _log("WARN", "pw_del_flush: %r" % e)


# RA12（红队复验真修）：密码管理器鉴权 token——启动期随机生成，进程
# 生命周期不变。UI 经 server.py 暴露的 pw_token 取得（同源），本机其他
# 进程无法预知（原 Origin 自指校验 Host/Origin 均可伪造=打穿）。
import secrets as _secrets
PW_TOKEN = _secrets.token_urlsafe(24)


def get_tabs():
    return _tabs


def _log(level, msg):
    try:
        print("[web-tabs][%s] %s" % (level, msg))
    except Exception:
        pass


class WebTabs:
    """WebView2 控件池：tab_id → 控件。布局 rect 由前端上报（DIP）。"""

    def __init__(self, form, cdp=False):
        self._form = form                    # pywebview 的 WinForms Form
        self._cdp = bool(cdp)                # R4 审计 D2：CDP/DevTools 门控
        #（=debug 或配置键 web_cdp，与 main.py 主进程同一口径——a473 原设计
        #「默认关，开启需重启生效」；v3.4.99 终裁正常启动无 F12/右键/F5）
        self._main_cvw = None                # 工具主 UI 的 CoreWebView2（事件推送目标）
        self._ctl = {}                       # tab_id(str) → WebView2 控件
        self._env = None                     # 共享 CoreWebView2Environment
        self._rect = (0, 0, 800, 600)        # 最近一次布局（物理像素）
        self._layout_seen = False            # a555：首份 rect 到达前不显控件
        self._want = None                    # a555：(tab_id, visible) 最近显隐意图
        self._want_seq = 0                   # a556：show 命令序号（乱序丢弃）
        self._pending = set()                # a555：create 在途的 tab（双发去重）
        self._pend_nav = {}                  # a555：在途 tab 的后发导航（末次胜出）
        self._cancel = set()                 # R1 审计 W5：create 在途中被 dispose（弃建标记）
        self._epochs = {}                    # R4 审计 D1（W3）：tab → 页面纪元（dispose_all 按纪元回收）
        self._env_failed = False             # a555：env 永久失败 → 快速失败
        self._closing = False                # RB6：退出落盘中（create 拒绝）
        self._ensure_env()

    # ---------- 环境（一次） ----------
    def _ensure_env(self):
        """独立用户数据文件夹——pywebview 已锁默认目录，二次打开会抛
        「文件夹已被使用」。目录在 LOCALAPPDATA 下的独立子目录。
        程序集与 loader 路径照抄 pywebview 的 interop 加载方式。"""
        try:
            import os
            import clr
            # a555 审计修：原硬编码开发机 site-packages 绝对路径——打包后
            # 无效。改从 pywebview 自身定位（它已加载过 WebView2 程序集，
            # 其 lib 目录即程序集所在；找不到则退回 webview 包内 lib）
            base = None
            try:
                from webview.util import interop_dll_path
                base = os.path.dirname(interop_dll_path(
                    "Microsoft.Web.WebView2.Core.dll"))
            except Exception:
                pass
            if not base:
                import webview
                base = os.path.join(os.path.dirname(webview.__file__), "lib")
            if base not in sys_path():
                sys_path_append(base)
            os.environ["Path"] = os.environ.get("Path", "") + ";" + base
            clr.AddReference("Microsoft.Web.WebView2.Core")
            clr.AddReference("Microsoft.Web.WebView2.WinForms")
            import Microsoft.Web.WebView2.Core as C
            udf = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                               "fc_webview_tabs")
            # R4 审计 D2（W4）：显式 options——①独立 CDP 端口 9223（AI 经
            # devtools_cdp 多端口发现触达网页 tab，9222 归主 UI）——**仅
            # debug 或 web_cdp 配置开启时附带**（a473 原门控：默认关）；
            # ②自带主进程同款性能四旗。9223 被占时浏览器进程无 CDP 但
            # 功能不受损（与 9222 先占同款降级）。
            opts = C.CoreWebView2EnvironmentOptions()
            args = ("--disable-backgrounding-occluded-windows "
                    "--disable-renderer-backgrounding "
                    "--disable-background-timer-throttling "
                    "--disable-features=CalculateNativeWinOcclusion,"
                    # a582（内网方案·根因4）：关密码泄露检测——内网访问
                    # 不到泄露库端点，同步等超时=点「保存」卡顿。落库不受影响
                    "AutofillServerCommunication")
            if self._cdp:
                args += " --remote-debugging-port=9223"
            opts.AdditionalBrowserArguments = args
            # R9 审计 W37：主进程在 debug/web_cdp 模式导出的
            # WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 必含 9222——文档任一
            # 语义（覆盖 options / 追加后同名开关 last-wins）都会压掉
            # 9223。临时摘除该环境变量 → CreateAsync（loader 在此读 env）
            # → 还原。主 UI 环境早已建完，还原无副作用；网页 tab 进程
            # 参数就此完全确定化（W1 纵深成立）。
            _env_key = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
            _saved_env = os.environ.pop(_env_key, None)
            try:
                task = C.CoreWebView2Environment.CreateAsync(None, udf, opts)
            finally:
                if _saved_env is not None:
                    os.environ[_env_key] = _saved_env
            import System

            def _done(t):
                try:
                    self._env = t.Result
                    _log("INFO", "environment ready: %s" % udf)
                except Exception as e:
                    self._env_failed = True   # a555：别让后续 create 白等 5s
                    _log("ERROR", "env create: %r" % e)
            task.ContinueWith(System.Action[System.Threading.Tasks.Task](_done))
        except Exception as e:
            self._env_failed = True
            _log("ERROR", "_ensure_env: %r" % e)

    # ---------- UI 线程工具 ----------
    def _ui(self, fn):
        """Flask 线程 → UI 线程（BeginInvoke fire-and-forget）。"""
        try:
            import System
            self._form.BeginInvoke(
                System.Action(fn))
        except Exception as e:
            _log("WARN", "ui invoke: %r" % e)

    # ---------- tab 生命周期 ----------
    def create(self, tab_id, url, epoch=""):
        """开 tab：创建控件 → 初始化 → 导航。初始化是异步链（env →
        EnsureCoreWebView2Async → CoreWebView2 就绪 → Navigate），全程
        ContinueWith 不阻塞 UI 线程。epoch=页面纪元（R4 审计 D1：刷新后
        pagehide dispose_all(epoch) 按纪元回收，不误杀新纪元控件）。"""
        if self._env_failed:
            # a555：env 已判死——快速失败，别进下面的重试白等 5s
            return {"ok": False, "err": "WebView2 环境初始化失败"}
        if self._env is None and self._closing:
            # RB6（红队）：退出落盘期间（_env 已置空）create 快速失败——
            # 原路径 50×100ms 重试钉死 Flask 线程 ~5s
            return {"ok": False, "err": "正在退出"}
        if not self._env:
            # env 竞态（启动初期）：100ms 重试 ×50
            import time
            for _ in range(50):
                if self._env:
                    break
                time.sleep(0.1)
        if not self._env:
            return {"ok": False, "err": "WebView2 环境未就绪"}
        if tab_id in self._ctl:
            self.navigate(tab_id, url)
            return {"ok": True}
        if tab_id in self._pending:
            # a555 审计修：双击回车连发两个 create——原先两者都过 in _ctl
            # 检查（_build 未跑、dict 未写）→ 建两个控件，先者成永不 Dispose
            # 的孤儿。去重 + 记下后发导航（控件就绪后末次胜出）
            self._pend_nav[tab_id] = url
            return {"ok": True}
        self._pending.add(tab_id)
        self._epochs[tab_id] = epoch

        def _build():
            try:
                if tab_id in self._cancel:
                    # R1 审计 W5：create 在途期间 tab 已被关闭——不建控件、
                    # 不接线、不导航（原先照建 → 永不 Dispose 的隐形孤儿）
                    self._cancel.discard(tab_id)
                    return
                import Microsoft.Web.WebView2.WinForms as WF
                import System
                import System.Drawing
                ctl = WF.WebView2()
                ctl.Visible = False           # 布局就绪前不显示
                x, y, w, h = self._rect
                ctl.Bounds = System.Drawing.Rectangle(x, y, w, h)
                self._form.Controls.Add(ctl)
                self._ctl[tab_id] = ctl
                self._wire(tab_id, ctl, url)
            except Exception as e:
                _log("ERROR", "create: %r" % e)
            finally:
                self._pending.discard(tab_id)
                # RB7-1（红队复验·P2）：被 cancel 的 tab 纪元随弃——否则
                # dispose_all「快照→_cancel.add」窗口内完成的 _build 会让
                # 纪元被 pop 后标记滞留 → 同纪元 beacon 永不回收
                #（强制 100/100 复现）。
                if tab_id in self._cancel:
                    self._epochs.pop(tab_id, None)
        self._ui(_build)   # RB7-1 修复回归：上一次替换误删了本行（_build
                           # 从未被投递 → 全部测试 KeyError 't1'）
        return {"ok": True}

    def _wire(self, tab_id, ctl, url):
        """初始化 CoreWebView2 → 事件接线 → 首次导航。

        a548 修：ContinueWith 回调在线程池线程跑，CoreWebView2 属性
        只能 UI 线程访问（InvalidOperationException 实锤）——完成动作
        整体再 BeginInvoke 回 UI 线程。"""
        import System
        _log("INFO", "_wire called for %s" % tab_id)   # R9.17：注入链可见化

        def _init_done(t):
            try:
                t.Result    # 确保异常在此可见
            except Exception as e:
                _log("ERROR", "EnsureCoreWebView2Async: %r" % e)
                # R3 审计 W21：except 变量在块尾被 CPython 隐式 del——闭包
                # 延迟执行时 str(e) 抛 NameError 被吞（实测复现）。先固化
                # 为普通局部变量再进 _rm 闭包。
                err = str(e)
                # R1 审计 W13：初始化失败原先只记日志——死控件永留 _ctl，
                # tab 假活（无重试/无回收/无提示）。回收控件 + 通知前端关 tab。
                self._ctl.pop(tab_id, None)
                self._pend_nav.pop(tab_id, None)
                self._epochs.pop(tab_id, None)

                def _rm():
                    try:
                        self._form.Controls.Remove(ctl)
                        ctl.Dispose()
                    except Exception:
                        pass
                    # R2 审计 W14：通知前端必须在 UI 线程发（a549 铁律）。
                    m = self._main_cvw
                    if m:
                        try:
                            m.ExecuteScriptAsync(
                                "window.__webTabDead && window.__webTabDead(%s, %s)"
                                % (json.dumps(tab_id), json.dumps(err)))
                        except Exception:
                            pass
                self._ui(_rm)
                return

            def _on_ui():
                try:
                    cvw = ctl.CoreWebView2
                    # a552 开密码自动填充（登录态便利）→ a557 默认关：
                    # Chromium 自动签到会把会话过期变成自动提交的登录尝试
                    # （多 tab × 新开/唤醒/刷新 = 频繁登录 → SSO 锁号，
                    # 用户实锤）。改 WEB_TAB_PASSWORD_AUTOFILL 开回。
                    # a582（内网方案合入·根因1）：.NET CoreWebView2Profile 真实
                    # 属性是 IsPasswordAutosaveEnabled / IsGeneralAutofillEnabled
                    # ——原 PasswordAutofillEnabled/GeneralAutofillEnabled 两个名
                    # 都不存在，赋值 AttributeError 被吞 → 密码保存从未开启
                    # （Login Data 表 0 行实证）。独立 try + 回读日志。
                    def _set_autofill(tag):
                        for _attr, _val in (
                            ("IsPasswordAutosaveEnabled",
                             WEB_TAB_PASSWORD_AUTOFILL),
                            ("IsGeneralAutofillEnabled", True),
                        ):
                            try:
                                setattr(cvw.Profile, _attr, _val)
                            except Exception as e:
                                _log("WARN", "autofill(%s).%s=%r: %r"
                                     % (tag, _attr, _val, e))
                        try:
                            _log("INFO", "autofill(%s) now: pwd=%r form=%r"
                                 % (tag, cvw.Profile.IsPasswordAutosaveEnabled,
                                    cvw.Profile.IsGeneralAutofillEnabled))
                        except Exception:
                            pass
                    _set_autofill(tab_id)
                    # a557：防自动签到脚本——先注册后首航，覆盖首个文档。
                    # R9.17：两条注入各自独立 try（一条失败不再连坐另一条），
                    # 且成败都写日志（此前静默——注入失败无从得知，用户实锤
                    # 「网页文档里 MISSING」）。另在 NavigationStarting 事件
                    # 重注入兜底（AddScript 对 about:blank 等特殊文档可能
                    # 不执行的边界）。
                    try:
                        cvw.AddScriptToExecuteOnDocumentCreatedAsync(
                            _ANTI_AUTOSIGNIN_JS)
                    except Exception as e:
                        _log("WARN", "anti-autosignin inject: %r" % e)
                    # R4 审计 D2：网页 tab 的 DevTools（右键「检查」/F12）与
                    # CDP 同门控——debug 或 web_cdp 开启才可用（v3.4.99 终裁
                    # 「正常启动无 F12」对网页 tab 同样成立）
                    try:
                        cvw.Settings.AreDevToolsEnabled = self._cdp
                    except Exception as e:
                        _log("WARN", "devtools: %r" % e)
                    self._wire_events(tab_id, ctl, cvw)
                    cvw.Navigate(url or "about:blank")
                    # a555：create 在途期间后发的导航（末次胜出）
                    u2 = self._pend_nav.pop(tab_id, None)
                    if u2 and u2 != url:
                        cvw.Navigate(u2)
                except Exception as e:
                    _log("ERROR", "init: %r" % e)
            self._ui(_on_ui)
        try:
            task = ctl.EnsureCoreWebView2Async(self._env)
            task.ContinueWith(
                System.Action[System.Threading.Tasks.Task](_init_done))
        except Exception as e:
            _log("ERROR", "_wire: %r" % e)

    def set_main(self, cvw):
        """a550：登记工具主 UI 的 CoreWebView2——事件推送目标。

        a544 的致命错：_push 用控件自己的 ExecuteScriptAsync——那是往
        控件加载的外部页面（csdn/juejin）执行 JS，__webTabNew 定义在
        工具主 UI 文档里，推送全部静默失败：NewWindowRequested 被
        Handled=True 吞掉后无后续 → 点文章（target=_blank）全无反应
        =「主界面能开子界面打不开」；地址栏/历史按钮也永不更新。"""
        self._main_cvw = cvw

    def _wire_events(self, tab_id, ctl, cvw):
        """地址栏推送 + 历史/新窗口。经主 UI ExecuteScriptAsync
        fire-and-forget（a550：推到工具文档而非网页文档）。"""

        def _push(js):
            """a555：返回成败——NewWindowRequested 推送失败时需降级。"""
            try:
                m = self._main_cvw
                if m:
                    m.ExecuteScriptAsync(js)
                    return True
            except Exception:
                pass
            return False

        def _on_src(s, a):
            try:
                u = str(cvw.Source or "")
                # a557：SSO 页面命中可见化——锁号诊断时在控制台数频次
                if u and any(h in u for h in _SSO_HOSTS):
                    _log("SSO", "login-page hit tab=%s %s" % (tab_id, u))
                _push("window.__webTabUrl && window.__webTabUrl(%s, %s)"
                      % (json.dumps(tab_id), json.dumps(u)))
            except Exception:
                pass
        cvw.SourceChanged += _on_src

        # a553：导航开始/完成 → 前端加载指示（刷新转圈+地址栏呼吸）
        def _on_nav_start(s, a):
            _push("window.__webTabLoad && window.__webTabLoad(%s, true)"
                  % json.dumps(tab_id))
        cvw.NavigationStarting += _on_nav_start

        def _on_nav_done(s, a):
            _push("window.__webTabLoad && window.__webTabLoad(%s, false)"
                  % json.dumps(tab_id))
        cvw.NavigationCompleted += _on_nav_done

        def _on_hist(s, a):
            # a555 审计修：原先 CanGoBack/CanGoForward 在 _push 实参处求值、
            # 整体无 try——dispose 后在途事件抛 ObjectDisposedException 直穿
            # CLR 事件分发 → WinForms ThreadException。六个处理器唯一裸奔者
            try:
                _push("window.__webTabHist && window.__webTabHist(%s, %s, %s)" % (
                    json.dumps(tab_id),
                    "true" if cvw.CanGoBack else "false",
                    "true" if cvw.CanGoForward else "false"))
            except Exception:
                pass
        cvw.HistoryChanged += _on_hist

        def _on_new_window(s, a):
            try:
                # R1 审计 W12：空 URI 原样吞（Handled=True 后既不推送也
                # 不导航）——window.open('') 语义=空白页，降级 about:blank
                u = str(a.Uri or "") or "about:blank"
                a.set_Handled(True)
                if u and not _push(
                        "window.__webTabNew && window.__webTabNew(%s)"
                        % json.dumps(u)):
                    # a555 审计修：主 UI 推送失败（关停期/未装配）时降级本
                    # tab 打开——原先静默吞掉，用户点 _blank 毫无反应
                    try:
                        cvw.Navigate(u)
                    except Exception:
                        pass
            except Exception:
                pass
        cvw.NewWindowRequested += _on_new_window

        # 标题 → 前端 tab label
        def _on_title(s, a):
            try:
                title = str(cvw.DocumentTitle or "")[:30]
                _push("window.__webTabTitle && window.__webTabTitle(%s, %s)"
                      % (json.dumps(tab_id), json.dumps(title)))
            except Exception:
                pass
        cvw.DocumentTitleChanged += _on_title

    # ---------- 命令（REST 进） ----------
    def navigate(self, tab_id, url):
        ctl = self._ctl.get(tab_id)
        if not ctl:
            return {"ok": False, "err": "no tab"}

        def _go():
            try:
                if ctl.CoreWebView2 is None:
                    # R1 审计 W6：EnsureCoreWebView2Async 未完成窗口期，
                    # 原路径 AttributeError 被吞 → URL 静默丢失（ok=True
                    # 但页面不动，地址栏与页面脱节）。转入 _pend_nav，
                    # 就绪后按「末次胜出」导航（与 create 双发同一机制）。
                    self._pend_nav[tab_id] = url
                    return
                ctl.CoreWebView2.Navigate(url)
            except Exception as e:
                _log("WARN", "navigate: %r" % e)
        self._ui(_go)
        return {"ok": True}

    def go_back(self, tab_id):
        ctl = self._ctl.get(tab_id)
        if ctl:
            def _do():
                try:
                    if ctl.CoreWebView2 and ctl.CoreWebView2.CanGoBack:
                        ctl.CoreWebView2.GoBack()
                except Exception as e:
                    _log("WARN", "back: %r" % e)
            self._ui(_do)
        return {"ok": True}

    def go_forward(self, tab_id):
        ctl = self._ctl.get(tab_id)
        if ctl:
            def _do():
                try:
                    if ctl.CoreWebView2 and ctl.CoreWebView2.CanGoForward:
                        ctl.CoreWebView2.GoForward()
                except Exception as e:
                    _log("WARN", "fwd: %r" % e)
            self._ui(_do)
        return {"ok": True}

    def reload(self, tab_id):
        ctl = self._ctl.get(tab_id)
        if ctl:
            def _do():
                try:
                    if ctl.CoreWebView2:
                        ctl.CoreWebView2.Reload()
                except Exception as e:
                    _log("WARN", "reload: %r" % e)
            self._ui(_do)
        return {"ok": True}

    def suspend(self, tab_id):
        """R-外泄根治·静止帧：趁控件还可见抓一帧 PNG → 隐藏 → 帧推给前端
        做占位背景（用户接受「静止」，不接受白屏——控件一藏露出 .web-body
        底色）。抓帧失败/无 CoreWebView2 → 降级直接隐藏（前端保持暗色虚化
        底）。UI 线程起手（a549 铁律）；流读取在完成回调（池线程读
        MemoryStream 非 CoreWebView2 成员，不违铁律），推送经 _ui 归 UI。"""
        ctl = self._ctl.get(tab_id)
        if not ctl:
            return {"ok": False, "err": "no tab"}

        def _do():
            diag = []
            try:
                import Microsoft.Web.WebView2.Core as C
                import System
                # R9.3 加固：System.IO 在部分 pythonnet 版本需显式引用
                try:
                    import System.IO  # noqa: F401
                except Exception:
                    try:
                        import clr
                        clr.AddReference("System.IO")
                    except Exception as e2:
                        diag.append("import-io:%r" % e2)
                cvw = ctl.CoreWebView2
                if cvw is None:
                    diag.append("no-cvw")
                    ctl.Visible = False
                    self._diag(tab_id, diag)
                    return
                ms = System.IO.MemoryStream()
                # R9.5：CoreWebView2CaptureFormat 在 pythonnet 下偶发「属性
                # 返回裸 int 而非枚举实例」（用户实锤两连：先是 AttributeError，
                # 修后 .PNG 返回 1 → CapturePreviewAsync(int) TypeError）。
                # 解析目标=必须拿到真枚举实例：①属性+isinstance 校验；
                # ②从 CapturePreviewAsync 方法签名的参数类型反射（参数的
                # ParameterType 就是枚举 Type，比翻程序集可靠）；③裸 int
                # 兜底（pythonnet 多数版本隐式转，失败即诊断可见）。
                fmt = None
                try:
                    _f = C.CoreWebView2CaptureFormat.PNG
                    import System as _S
                    if isinstance(_f, _S.Enum):
                        fmt = _f
                    else:
                        diag.append("fmt-notenum:%r" % (type(_f),))
                except Exception as e:
                    diag.append("fmt-attr:%r" % e)
                if fmt is None:
                    try:
                        mi = cvw.GetType().GetMethod("CapturePreviewAsync")
                        et = mi.GetParameters()[0].ParameterType
                        fmt = System.Enum.ToObject(et, 1)
                        diag.append("fmt-method")
                    except Exception as e2:
                        diag.append("fmt-refl:%r" % e2)
                        fmt = 1
                task = cvw.CapturePreviewAsync(fmt, ms)
            except Exception as e:
                _log("WARN", "suspend: %r" % e)
                self._diag(tab_id, ["cap:%r" % e])
                try:
                    ctl.Visible = False
                except Exception:
                    pass
                return

            def _done(t):
                data = b""
                try:
                    data = bytes(ms.ToArray())
                except Exception as e:
                    diag.append("read:%r" % e)
                if not data:
                    diag.append("empty-frame")

                def _after():
                    # RB5（红队）：抓帧窗口（100-300ms）内用户可能已切回本
                    # tab——迟到回调按当前意图判定，无条件 False 会把新
                    # show 藏掉（100/100 复现）。意图指向本 tab 可见→保持
                    # 可见（帧照推，被活页盖住无碍）。
                    try:
                        w = self._want
                        if w is not None and w[0] == tab_id and w[1]:
                            ctl.Visible = True
                        else:
                            ctl.Visible = False
                    except Exception:
                        pass
                    m = self._main_cvw
                    if m:
                        try:
                            if data:
                                import base64
                                b64 = base64.b64encode(data).decode("ascii")
                                if len(b64) <= 4 * 1024 * 1024:
                                    m.ExecuteScriptAsync(
                                        "window.__webTabShot && window.__webTabShot(%s, %s)"
                                        % (json.dumps(tab_id),
                                           json.dumps("data:image/png;base64," + b64)))
                                    return
                                diag.append("b64-big:%d" % len(b64))
                        except Exception as e:
                            diag.append("push:%r" % e)
                        # 诊断直推前端 console——断点一眼可见（用户可开 DevTools）
                        if diag:
                            try:
                                m.ExecuteScriptAsync(
                                    "console.warn(%s)"
                                    % json.dumps('[web-tabs] suspend: '
                                                 + ";".join(diag)))
                            except Exception:
                                pass
                self._ui(_after)

            try:
                task.ContinueWith(
                    System.Action[System.Threading.Tasks.Task](_done))
            except Exception as e:
                _log("WARN", "suspend cont: %r" % e)
                self._diag(tab_id, ["cont:%r" % e])
                try:
                    ctl.Visible = False
                except Exception:
                    pass
        self._ui(_do)
        return {"ok": True}

    def _diag(self, tab_id, diag):
        """suspend 失败诊断直推前端 console（pythonw 下 stdout 丢失）。"""
        if not diag:
            return
        _log("WARN", "suspend %s: %s" % (tab_id, ";".join(diag)))
        m = self._main_cvw

        def _push():
            try:
                m.ExecuteScriptAsync(
                    "console.warn(%s)"
                    % json.dumps('[web-tabs] suspend: ' + ";".join(diag)))
            except Exception:
                pass
        if m:
            self._ui(_push)

    def _apply_visibility(self):
        """按最近显隐意图应用（UI 线程内跑）。

        a555 审计修：list 快照——dispose 在 Flask 线程同步 pop _ctl，迭代
        活视图遇并发变更抛 RuntimeError 中断循环（切 tab 半途而废）。
        a556 语义变更：visible=True 排他显示（其余全藏）；visible=False
        **只藏目标**——原先 hide-all 会让后台 tab 休眠时把用户正看的
        活动 tab 一起藏掉（用户实锤）。"""
        if not self._want:
            return
        tab_id, visible = self._want
        # a575（用户实锤：网页后台仍卡爆、一关立刻好）：Visible=False 只是
        # 视觉隐藏，Chromium 渲染管线照常全速——主 UI 性能四旗（禁后台
        # 节流/遮挡判定）同样注入网页 tab 浏览器进程，剥夺了它一切后台
        # 减速权利；页面自身动画/定时器逐帧软件光栅+合成，账单由主 UI
        # GPU 进程照付（实测隐藏态 GPU 进程持续 ~15%）。修法=WebView2
        # 官方挂起：TrySuspend 真停渲染管线（毫秒级 Resume），比导航
        # about:blank 干净（保留页面/历史/滚动位置）。只在 UI 线程跑。

        def _pw(c):
            """取控件的 CoreWebView2（未初始化完成时 None）。"""
            try:
                return c.CoreWebView2
            except Exception:
                return None

        def _suspend_ctl(c):
            pw = _pw(c)
            if not pw:
                return
            try:
                pw.TrySuspendAsync()
            except Exception as e:
                _log("WARN", "TrySuspend: %r" % e)

        def _resume_ctl(c):
            pw = _pw(c)
            if not pw:
                return
            try:
                if pw.IsSuspended:
                    pw.ResumeWebResourceRequests()
            except Exception as e:
                _log("WARN", "resume: %r" % e)

        if tab_id == _HIDE_ALL:
            # R6 审计 W32：全隐分支——阅读态/守卫态下任何网页控件都不得
            # 可见；幂等（重复 layout 重复全隐无害），不动 BringToFront
            # （恢复排他显示时由 show(X,True) 统一前置）
            for c in list(self._ctl.values()):
                c.Visible = False
                _suspend_ctl(c)     # a575：全隐=全部挂起（无人观看）
            return
        if visible:
            for tid, c in list(self._ctl.items()):
                c.Visible = (tid == tab_id)
                if c.Visible:
                    _resume_ctl(c)   # a575：先恢复管线再显示（毫秒级）
                    c.BringToFront()
                else:
                    _suspend_ctl(c)  # a575：后台 tab 挂起（停产帧）
        else:
            c = self._ctl.get(tab_id)
            if c:
                c.Visible = False
                _suspend_ctl(c)
    def show(self, tab_id, visible, sq=0, hide_all=False, epoch=None):
        """切 tab：显示目标控件（排他），或只藏目标。hide_all=True=全隐
        （R6 审计 W32：_want 记哨兵，防陈旧排他意图经 layout 弹出他 tab）。

        a555 审计修：首份 layout 到达前不显控件——默认 rect (0,0,800,600)
        是占位值，WebView2 原生窗口又在 DOM 之上，layout/show 两个独立
        fetch 无顺序保证，乱序时控件会闪一帧盖住工具 UI 左上角。意图记入
        _want，由到达的 layout._apply 补显。
        a556：sq 序号（前端 _webCtlSeq 单调递增）——show 是独立 fetch，
        浏览器多连接下到达顺序无保证；乱序迟到的旧意图直接丢弃，否则
        「切走时隐藏」被「休眠前显示」后到覆盖 → 控件压在其他 tab 上
        （用户实锤「网页没进抽屉」）。"""
        # RB4（红队·P1）：纪元标签——新页面（新 epoch）到达即重置 seq 水位。
        # 修刷新三变体：beacon 丢失/recycle=0 跳过 reset/旧页迟到 sq 抬水位
        # → 新页 show 被丢 20-74s 死 UI。误重置由前端 2s 重发（R9.14 恒发）
        # 自愈（≤2s）。epoch=None（无标签）保持旧行为，兼容。
        if epoch is not None and epoch != getattr(self, "_want_epoch", None):
            # RB7-2（红队复验）：旧纪元迟到指令不得污染新纪元——换纪元时
            # 重置水位但**丢弃本次意图**（旧页的 show 是过时指令；新纪元
            # 自己的 show 马上会到）。误丢弃由前端恒发自愈（≤2s）。
            stale = True
            self._want_epoch = epoch
            self._want_seq = 0
            self._want = None
        else:
            stale = False
        if sq:
            if sq <= self._want_seq:
                return {"ok": True}       # 乱序迟到的旧令
            self._want_seq = sq
        # R6 审计 W32：hide_all=True =「全隐」意图——哨兵写入 _want，
        # layout 补显期与后续任何 layout 均不再按陈旧排他意图弹出
        # 不相关控件。hide_all 时 visible 参数忽略；sq 门控照常生效。
        self._want = (_HIDE_ALL, False) if hide_all else (tab_id, bool(visible))
        if stale:
            return {"ok": True, "stale-epoch-dropped": True}
        if visible and tab_id not in self._ctl and tab_id in self._pending:
            # a555：create 在途（show 先于 _build 被处理）——此刻应用会把
            # 其他已显示 tab 藏掉又无新控件可显。意图已记 _want，控件建好
            # 后由 layout._apply 补显
            return {"ok": True}

        def _apply():
            if not self._layout_seen:
                return          # 等 layout 到达后补显
            try:
                self._apply_visibility()
            except Exception as e:
                _log("WARN", "show: %r" % e)
        self._ui(_apply)
        return {"ok": True}

    def dispose(self, tab_id):
        """关 tab：控件从 Form 移除并 Dispose（渲染进程回收）。"""
        ctl = self._ctl.pop(tab_id, None)
        self._epochs.pop(tab_id, None)
        if ctl:
            def _rm():
                try:
                    self._form.Controls.Remove(ctl)
                    ctl.Dispose()
                except Exception as e:
                    _log("WARN", "dispose: %r" % e)
            self._ui(_rm)
        elif tab_id in self._pending:
            # R1 审计 W5：create 在途中被关——原路径查无 ctl 直接 ok，
            # 随后 _build 照常建出控件。登记取消标记 + 清理在途导航。
            self._cancel.add(tab_id)
            self._pending.discard(tab_id)
            self._pend_nav.pop(tab_id, None)
        return {"ok": True}

    def dispose_all(self, epoch=None):
        """R4 审计 D1（W3/W24）：UI 页面卸载回收——按纪元回收 _ctl 与
        _pending（在途 create 走 W5 取消路径）。epoch 不匹配的控件（其他
        UI 会话/其他纪元）不动；epoch=None=全部回收（panic 语义，兼容
        无纪元的旧调用）。R9 审计 W40：仅当本纪元确有回收（或 panic）
        才归零会话水位——零命中（迟到的他人纪元 beacon 漏网时）不得把
        现存 UI 的 seq/显隐意图打掉。"""
        n = 0
        # RB7-1（终审真修）：双扫——第一扫与 _pending 取消之间可能有
        # _build 完成（EnsureCoreWebView2Async 就绪链在 UI 线程交错），
        # 二扫收尾漏网控件
        for tid in list(self._ctl.keys()):
            if epoch is None or self._epochs.get(tid) == epoch:
                self.dispose(tid)
                n += 1
        for tid in [t for t in list(self._pending)
                    if epoch is None or self._epochs.get(t) == epoch]:
            self._cancel.add(tid)
            self._pending.discard(tid)
            self._pend_nav.pop(tid, None)
            self._epochs.pop(tid, None)
            n += 1
        # RB7-1：二扫——第一扫后到此刻之间完成的 _build（控件已入 _ctl）
        for tid in list(self._ctl.keys()):
            if epoch is None or self._epochs.get(tid) == epoch:
                self.dispose(tid)
                n += 1
        if n or epoch is None:
            self.reset_session()
        return {"ok": True, "recycled": n}

    # ---------- 退出前落盘（a582 内网方案·根因2） ----------
    def flush_on_exit(self, grace_ms=1200):
        """给 WebView2 有序关闭的机会，让 Chromium 把 cookie/密码库写盘。
        步骤：① UI 线程逐个 Dispose 控件 ② 环境引用置空 ③ sleep 等浏览器
        进程自行 flush 退出。全程 fail-safe（单控件异常不连坐；无
        Dispatcher 降级直执行）；由 shutdown() 在非 UI 线程调用。"""
        import time as _t
        try:
            ctls = list(self._ctl.values())
            self._ctl.clear()
            self._epochs.clear()

            def _close_all():
                for c in ctls:
                    try:
                        _cvw = getattr(c, "CoreWebView2", None)
                        if _cvw is not None:
                            try:
                                _cvw.Stop()
                            except Exception:
                                pass
                        self._form.Controls.Remove(c)
                    except Exception:
                        pass
                    try:
                        c.Dispose()
                    except Exception:
                        pass
            try:
                import System
                self._form.BeginInvoke(System.Action(_close_all))
            except Exception:
                _close_all()   # 无 UI Dispatcher 时降级直执行
            self._closing = True   # RB6：退出中——后续 create 快速失败
            self._env = None
            _t.sleep(max(0.0, grace_ms / 1000.0))
            _log("INFO", "flush_on_exit done (grace=%dms, ctls=%d)"
                 % (grace_ms, len(ctls)))
            # a583：浏览器进程已停 → Login Data 解锁，执行挂起的密码删除
            try:
                _pw_del_flush()
            except Exception:
                pass
        except Exception as e:
            _log("WARN", "flush_on_exit: %r" % e)

    def reset_session(self):
        """R4 审计 D1（W3）：页面会话重置——seq 水位/显隐意图/在途导航
        全部归零，刷新后的新页面从干净状态开始（旧 beacon 迟到不回踩）。"""
        self._want_seq = 0
        self._want = None
        self._want_epoch = None   # RB4：会话重置连纪元一起
        self._pend_nav.clear()
        # RB2（红队·P1）：_cancel 不能在此清——dispose_all 的 pending 分支
        # 先写 _cancel 再调本函数，清掉=在途 _build 复活为永不 Dispose 的
        # 隐形孤儿（300/300 确定性复现）。_cancel 由 _build 消费自清。

    # ---------- 布局（前端上报） ----------
    def layout(self, x, y, w, h):
        """rect 物理像素（前端 DIP × devicePixelRatio）。"""
        self._rect = (int(x), int(y), int(max(w, 50)), int(max(h, 50)))
        self._layout_seen = True

        def _apply():
            try:
                import System.Drawing
                r = System.Drawing.Rectangle(*self._rect)
                # a555：list 快照防 dispose 竞态（同 _apply_visibility）
                for c in list(self._ctl.values()):
                    c.Bounds = r
                # a555：补显被首显哨兵推迟/在途 create 错过的 show 意图
                self._apply_visibility()
            except Exception as e:
                _log("WARN", "layout: %r" % e)
        self._ui(_apply)
        return {"ok": True}


# ---------- sys.path 辅助（clr 加载 WebView2 程序集用） ----------
def sys_path():
    import sys
    return sys.path


def sys_path_append(p):
    import sys
    if p not in sys.path:
        sys.path.append(p)


def _detect_cdp():
    """R4 审计 D2：CDP/DevTools 门控探测——与 main.py 主进程同一口径
    （debug 开启，或配置键 web_cdp 开启）。install 在 main.py :853 附近
    被调用，早于 :1559 的 _wv_debug 赋值，故此处自行探测而非收参。"""
    try:
        from src.server import DEBUG_WEB
        if DEBUG_WEB:
            return True
    except Exception:
        pass
    try:
        import json as _json
        from src.app_state import CONFIG_FILE
        with open(CONFIG_FILE, encoding="utf-8") as _f:
            return bool((_json.load(_f) or {}).get("web_cdp"))
    except Exception:
        return False


# ---------- REST 蓝图 ----------
def register(app):
    from flask import Blueprint, jsonify, request
    bp = Blueprint("web_tabs", __name__)

    @bp.route("/api/web/tabs", methods=["POST"])
    def api_web_tabs():
        d = request.get_json(force=True, silent=True) or {}
        act = str(d.get("act") or "")
        tid = str(d.get("tab") or "")
        url = str(d.get("url") or "")
        t = get_tabs()
        if not t:
            return jsonify({"ok": False, "err": "控件管理器未装配"})

        def _num(k, dft=0):
            # R1 审计 W7：x/y/w/h/sq 原样透传，"abc"/"NaN" → int() 抛
            # ValueError → 裸 500。收口：非有限数值一律回落默认。
            try:
                v = float(d.get(k, dft))
                if v != v or v in (float("inf"), float("-inf")):
                    return dft
                return int(v)
            except (TypeError, ValueError, OverflowError):
                return dft

        if act == "create":
            # R4 审计 D1：epoch=页面纪元透传（pagehide dispose_all 按纪元回收）
            return jsonify(t.create(tid, url, str(d.get("epoch") or "")))
        if act == "nav":
            return jsonify(t.navigate(tid, url))
        if act == "back":
            return jsonify(t.go_back(tid))
        if act == "fwd":
            return jsonify(t.go_forward(tid))
        if act == "reload":
            return jsonify(t.reload(tid))
        def _pw_guard():
            # RA12（红队复验真修）：双因子——①X-FC-Token == 模块级 PW_TOKEN
            # （启动期随机，本机其他进程不可预知；UI 经 /api/status 同源取得）
            # ②Origin 与本次 host 同源（浏览器跨站面）。二者全过才放行。
            from flask import request as _rq
            tok = (_rq.headers.get("X-FC-Token") or "")
            if tok != PW_TOKEN:
                return jsonify({"ok": False, "err": "forbidden"}), 403
            org = (_rq.headers.get("Origin") or "").strip().rstrip("/")
            if org != ("http://" + (_rq.host or "")):
                return jsonify({"ok": False, "err": "forbidden"}), 403
            return None

        if act == "pw_list":
            _g = _pw_guard()
            if _g is not None:
                return _g
            # a583 密码管理器：已存站点列表（不含明文）
            return jsonify({"ok": True, "items": _pw_entries()})
        if act == "pw_reveal":
            _g = _pw_guard()
            if _g is not None:
                return _g
            # 单条明文（loopback+origin 守卫内；按 origin+user 定位）
            import sqlite3
            _o = str(d.get("origin") or "")
            _u = str(d.get("user") or "")
            db = _pwdb_copy()
            if not db:
                return jsonify({"ok": False, "err": "密码库不可读"})
            # RA7（红队）：畸形库时 execute 抛出须关连接+删副本+500→400
            import os as _os
            con = None
            try:
                con = sqlite3.connect(db)
                row = con.execute(
                    "SELECT password_value FROM logins WHERE origin_url=? "
                    "AND username_value=? ORDER BY date_created DESC "
                    "LIMIT 1", (_o, _u)).fetchone()   # RA8：多条取最新
            except Exception as e:
                return jsonify({"ok": False, "err": "库读取失败：%r" % e})
            finally:
                # RA17（红队复验）：连接关闭+副本即删入 finally（异常路径也清）
                try:
                    if con is not None:
                        con.close()
                except Exception:
                    pass
                try:
                    _os.remove(db)
                except Exception:
                    pass
            if not row:
                return jsonify({"ok": False, "err": "not-found"})
            ok, text = _pw_decrypt(row[0])
            return jsonify({"ok": ok, "pw": text if ok else "",
                            "err": "" if ok else text})
        if act == "pw_del":
            _g = _pw_guard()
            if _g is not None:
                return _g
            _o = str(d.get("origin") or "")
            # RA4（红队）：按 origin+user 精确删——原全 origin 删除会把同站
            # 多账号一次清光；空 user 显式标记（None=全部，UI 不再使用）
            _u = d.get("user", None)
            if not _o:
                return jsonify({"ok": False, "err": "bad origin"}), 400
            now = _pw_del_defer(_o, _u)
            return jsonify({"ok": True, "immediate": now})
        if act == "suspend":
            # R-外泄根治·静止帧：抓帧→隐藏→回推（前端 reconcile 调用）
            return jsonify(t.suspend(tid))
        if act == "show":
            # a556：sq 序号透传（前端乱序保护）。R1 审计 W7：on/all 布尔
            # 穿透修正。R6 审计 W32：all=true=全隐（_want 记哨兵）。
            _on = d.get("on", True)
            _all = d.get("all", False)
            return jsonify(t.show(
                tid,
                _on if isinstance(_on, bool)
                else str(_on).strip().lower() in ("true", "1", "yes", "on"),
                _num("sq"),
                _all if isinstance(_all, bool)
                else str(_all).strip().lower() in ("true", "1", "yes", "on"),
                str(d.get("epoch") or "") or None))
        if act == "dispose":
            return jsonify(t.dispose(tid))
        if act == "dispose_all":
            # R4 审计 D1（W3）：页面卸载（pagehide beacon）按纪元回收——
            # 只动本纪元控件，刷新后重建的新纪元 tab 不被迟到的 beacon 误杀
            return jsonify(t.dispose_all(str(d.get("epoch") or "") or None))
        if act == "layout":
            return jsonify(t.layout(_num("x"), _num("y"),
                                    _num("w"), _num("h")))

        return jsonify({"ok": False, "err": "bad act"})

    app.register_blueprint(bp)


def shutdown(grace_ms=1200):
    # RA11（红队）：即使 _tabs 未装配（env 失败），挂起删除也须执行
    """a582：退出前优雅关闭 WebView2（main._do_real_cleanup 在 taskkill
    树杀之前调用）。fail-safe：任何异常吞掉，绝不阻塞退出主流程。"""
    global _tabs
    # RB8（红队复验）：重入保护 + 单次 grace——多次退出调用点（main 3 处）
    # 不再各睡一个 grace（实测 3 次=600ms×3）
    if getattr(_tabs, "_closing", False) and _tabs is not None:
        _pw_del_flush()
        return
    try:
        # RA14（红队复验）：挂起删除无论有无控件都执行
        if _tabs is not None:
            _tabs.flush_on_exit(grace_ms)
        _pw_del_flush()   # RA11/RA14
        _tabs = None      # RB8：装配引用清空（flush 已完成，重复调用走
                          # _closing 短路 + 无控件分支，幂等）
    except Exception as e:
        _log("WARN", "shutdown: %r" % e)


def install(form):
    """main._patched_ready 装配入口。CDP/DevTools 门控自行探测
    （=debug 或 web_cdp 配置，见 _detect_cdp）。"""
    global _tabs
    try:
        _tabs = WebTabs(form, cdp=_detect_cdp())
        _log("INFO", "WebTabs installed (cdp=%s)" % _tabs._cdp)
        return _tabs
    except Exception as e:
        _log("ERROR", "install: %r" % e)
        return None
