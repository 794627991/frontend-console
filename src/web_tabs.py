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
        self._next_new_target = [None]       # NewWindowRequested → 待开 URL
        self._ensure_env()

    # ---------- 环境（一次） ----------
    def _ensure_env(self):
        """独立用户数据文件夹——pywebview 已锁默认目录，二次打开会抛
        「文件夹已被使用」。目录在 LOCALAPPDATA 下的独立子目录。
        程序集与 loader 路径照抄 pywebview 的 interop 加载方式。"""
        try:
            import os
            import clr
            base = r"C:\Users\gaoyi13\AppData\Local\Programs\Python\Python314\Lib\site-packages\webview\lib"
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
                    _log("ERROR", "env create: %r" % e)
            task.ContinueWith(System.Action[System.Threading.Tasks.Task](_done))
        except Exception as e:
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
        import System

        def _push(js):
            try:
                m = self._main_cvw
                if m:
                    m.ExecuteScriptAsync(js)
            except Exception:
                pass

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
            _push("window.__webTabHist && window.__webTabHist(%s, %s, %s)" % (
                json.dumps(tab_id),
                "true" if cvw.CanGoBack else "false",
                "true" if cvw.CanGoForward else "false"))
        cvw.HistoryChanged += _on_hist

        def _on_new_window(s, a):
            try:
                u = str(a.Uri or "")
                a.set_Handled(True)
                if u:
                    _push("window.__webTabNew && window.__webTabNew(%s)"
                          % json.dumps(u))
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

    def show(self, tab_id, visible):
        """切 tab：显示目标控件，其余隐藏（同一 rect 叠放）。"""
        def _apply():
            try:
                for tid, c in self._ctl.items():
                    c.Visible = (tid == tab_id) and visible
                    if c.Visible:
                        c.BringToFront()
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

        def _apply():
            try:
                import System.Drawing
                r = System.Drawing.Rectangle(*self._rect)
                for c in self._ctl.values():
                    c.Bounds = r
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
            return jsonify(t.show(tid, bool(d.get("on", True))))
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
