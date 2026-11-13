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
    "(function(){var g=0;"
    "addEventListener('pointerdown',function(){g=Date.now()},true);"
    "addEventListener('keydown',function(){g=Date.now()},true);"
    "addEventListener('submit',function(e){try{"
    "var f=e.target;if(!f||!f.querySelector)return;"
    "if(!f.querySelector('input[type=password]'))return;"
    "if(Date.now()-g>3000){e.preventDefault();}"
    "}catch(_){}},true);})();")

# a557：SSO 页面命中日志——控制台直接可见「谁在频繁打 SSO」（诊断锁号）
_SSO_HOSTS = ("sso.hikvision.com", "moa.hikvision.com")


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
                    "--disable-features=CalculateNativeWinOcclusion")
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
        self._ui(_build)
        return {"ok": True}

    def _wire(self, tab_id, ctl, url):
        """初始化 CoreWebView2 → 事件接线 → 首次导航。

        a548 修：ContinueWith 回调在线程池线程跑，CoreWebView2 属性
        只能 UI 线程访问（InvalidOperationException 实锤）——完成动作
        整体再 BeginInvoke 回 UI 线程。"""
        import System

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
                    try:
                        cvw.Profile.PasswordAutofillEnabled = \
                            WEB_TAB_PASSWORD_AUTOFILL
                        cvw.Profile.GeneralAutofillEnabled = True
                    except Exception as e:
                        _log("WARN", "autofill: %r" % e)
                    # a557：防自动签到脚本——先注册后首航，覆盖首个文档
                    try:
                        cvw.AddScriptToExecuteOnDocumentCreatedAsync(
                            _ANTI_AUTOSIGNIN_JS)
                    except Exception as e:
                        _log("WARN", "anti-autosignin: %r" % e)
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
        if tab_id == _HIDE_ALL:
            # R6 审计 W32：全隐分支——阅读态/守卫态下任何网页控件都不得
            # 可见；幂等（重复 layout 重复全隐无害），不动 BringToFront
            # （恢复排他显示时由 show(X,True) 统一前置）
            for c in list(self._ctl.values()):
                c.Visible = False
            return
        if visible:
            for tid, c in list(self._ctl.items()):
                c.Visible = (tid == tab_id)
                if c.Visible:
                    c.BringToFront()
        else:
            c = self._ctl.get(tab_id)
            if c:
                c.Visible = False

    def show(self, tab_id, visible, sq=0, hide_all=False):
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
        if sq:
            if sq <= self._want_seq:
                return {"ok": True}       # 乱序迟到的旧令
            self._want_seq = sq
        # R6 审计 W32：hide_all=True =「全隐」意图——哨兵写入 _want，
        # layout 补显期与后续任何 layout 均不再按陈旧排他意图弹出
        # 不相关控件。hide_all 时 visible 参数忽略；sq 门控照常生效。
        self._want = (_HIDE_ALL, False) if hide_all else (tab_id, bool(visible))
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
        if n or epoch is None:
            self.reset_session()
        return {"ok": True, "recycled": n}

    def reset_session(self):
        """R4 审计 D1（W3）：页面会话重置——seq 水位/显隐意图/在途导航
        全部归零，刷新后的新页面从干净状态开始（旧 beacon 迟到不回踩）。"""
        self._want_seq = 0
        self._want = None
        self._pend_nav.clear()
        self._cancel.clear()

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
                else str(_all).strip().lower() in ("true", "1", "yes", "on")))
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
