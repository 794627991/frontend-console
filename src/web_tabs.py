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
_lock = threading.Lock()


def get_tabs():
    return _tabs


def _log(level, msg):
    try:
        print("[web-tabs][%s] %s" % (level, msg))
    except Exception:
        pass


class WebTabs:
    """WebView2 控件池：tab_id → 控件。布局 rect 由前端上报（DIP）。"""

    def __init__(self, form):
        self._form = form                    # pywebview 的 WinForms Form
        self._main_cvw = None                # 工具主 UI 的 CoreWebView2（事件推送目标）
        self._ctl = {}                       # tab_id(str) → WebView2 控件
        self._env = None                     # 共享 CoreWebView2Environment
        self._rect = (0, 0, 800, 600)        # 最近一次布局（物理像素）
        self._layout_seen = False            # a555：首份 rect 到达前不显控件
        self._want = None                    # a555：(tab_id, visible) 最近显隐意图
        self._want_seq = 0                   # a556：show 命令序号（乱序丢弃）
        self._pending = set()                # a555：create 在途的 tab（双发去重）
        self._pend_nav = {}                  # a555：在途 tab 的后发导航（末次胜）
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
            task = C.CoreWebView2Environment.CreateAsync(None, udf, None)
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
    def create(self, tab_id, url):
        """开 tab：创建控件 → 初始化 → 导航。初始化是异步链（env →
        EnsureCoreWebView2Async → CoreWebView2 就绪 → Navigate），全程
        ContinueWith 不阻塞 UI 线程。"""
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

        def _build():
            try:
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
                return

            def _on_ui():
                try:
                    cvw = ctl.CoreWebView2
                    # a552：密码自动填充（登录态便利，用户令）——开启后
                    # Chromium 密码管理器弹「保存密码」气泡，下次打开同站
                    # 自动填充账号密码（密码存 UDF 的 Login Data，持久）
                    try:
                        cvw.Profile.PasswordAutofillEnabled = True
                        cvw.Profile.GeneralAutofillEnabled = True
                    except Exception as e:
                        _log("WARN", "autofill: %r" % e)
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
                u = str(a.Uri or "")
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
        if visible:
            for tid, c in list(self._ctl.items()):
                c.Visible = (tid == tab_id)
                if c.Visible:
                    c.BringToFront()
        else:
            c = self._ctl.get(tab_id)
            if c:
                c.Visible = False

    def show(self, tab_id, visible, sq=0):
        """切 tab：显示目标控件（排他），或只藏目标。

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
        self._want = (tab_id, bool(visible))
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
        if not ctl:
            return {"ok": True}

        def _rm():
            try:
                self._form.Controls.Remove(ctl)
                ctl.Dispose()
            except Exception as e:
                _log("WARN", "dispose: %r" % e)
        self._ui(_rm)
        return {"ok": True}

    def dispose_all(self):
        for tid in list(self._ctl.keys()):
            self.dispose(tid)

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
        if act == "create":
            return jsonify(t.create(tid, url))
        if act == "nav":
            return jsonify(t.navigate(tid, url))
        if act == "back":
            return jsonify(t.go_back(tid))
        if act == "fwd":
            return jsonify(t.go_forward(tid))
        if act == "reload":
            return jsonify(t.reload(tid))
        if act == "show":
            # a556：sq 序号透传（前端乱序保护）
            return jsonify(t.show(tid, bool(d.get("on", True)),
                                  int(d.get("sq") or 0)))
        if act == "dispose":
            return jsonify(t.dispose(tid))
        if act == "layout":
            return jsonify(t.layout(d.get("x", 0), d.get("y", 0),
                                    d.get("w", 0), d.get("h", 0)))
        return jsonify({"ok": False, "err": "bad act"})

    app.register_blueprint(bp)


def install(form):
    """main._patched_ready 装配入口。"""
    global _tabs
    try:
        _tabs = WebTabs(form)
        _log("INFO", "WebTabs installed")
        return _tabs
    except Exception as e:
        _log("ERROR", "install: %r" % e)
        return None
