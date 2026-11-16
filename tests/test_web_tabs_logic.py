# -*- coding: utf-8 -*-
"""web_tabs.py 逻辑层单测（a555 审计配套）。

不碰真 CLR/WebView2——System 与 WinForms 模块经 sys.modules 桩注入，
FakeForm.BeginInvoke 可同步执行（模拟 UI 线程串行）或排队（模拟 UI 线程
异步，再现 Flask 线程与 UI 线程的乱序窗口）。验证 a555 六项修复的行为：

- create 双发去重（连点回车）+ 在途导航末次胜出
- show 首显哨兵（首份 layout 前不显，防默认 rect 闪位）与 create 在途守卫
- layout 到达后补显被推迟的 show 意图
- dispose 后在途事件不再裸抛（_on_hist 保护）
- NewWindowRequested 主 UI 推送失败 → 降级本 tab 导航（不再静默吞）
- env 永久失败 → create 快速返回（不再白等 5s）
"""
import sys
import time
import types

import pytest

# ---------- CLR 桩 ----------
sys.path.insert(0, '.')


class _ActionProto:
    """System.Action(fn) / System.Action[T](fn) 双形态。"""
    def __init__(self, item=None):
        self.item = item

    def __call__(self, fn):
        return fn

    def __getitem__(self, item):
        return _ActionProto(item)


class _FakeRect:
    def __init__(self, *a):
        self.a = a


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self

    def fire(self, args=None):
        for h in list(self.handlers):
            h(None, args)


class FakeProfile:
    PasswordAutofillEnabled = False
    GeneralAutofillEnabled = False


class FakeCvw:
    def __init__(self):
        self.Profile = FakeProfile()
        self.Source = "about:blank"
        self.DocumentTitle = "t"
        self._can_back = False
        self._can_fwd = False
        self._dead = False
        self.SourceChanged = FakeEvent()
        self.HistoryChanged = FakeEvent()
        self.NewWindowRequested = FakeEvent()
        self.DocumentTitleChanged = FakeEvent()
        self.NavigationStarting = FakeEvent()
        self.NavigationCompleted = FakeEvent()
        self.WebMessageReceived = FakeEvent()   # R9.17：WebMessage 桥
        self.posted = []
        self.navigated = []
        self.scripts = []
        self.injected = []          # a557：
        self._is_suspended = False  # a575：挂起态
        # R9.16/a575 接口补齐：真实 Cvw 有 Settings 与 TrySuspend/Resume/IsSuspended
        self.Settings = types.SimpleNamespace()
        self._suspended = False

    def TrySuspendAsync(self):
        self._is_suspended = True

    def ResumeWebResourceRequests(self):
        self._is_suspended = False

    @property
    def IsSuspended(self):
        return self._is_suspended

    @property
    def CanGoBack(self):
        if self._dead:
            raise RuntimeError("ObjectDisposedException (模拟)")
        return self._can_back

    @property
    def CanGoForward(self):
        if self._dead:
            raise RuntimeError("ObjectDisposedException (模拟)")
        return self._can_fwd

    def Navigate(self, u):
        self.navigated.append(u)

    def AddScriptToExecuteOnDocumentCreatedAsync(self, js):
        self.injected.append(js)

    def TrySuspendAsync(self):
        self._is_suspended = True
    def ResumeWebResourceRequests(self):
        self._is_suspended = False
    @property
    def IsSuspended(self):
        return self._is_suspended

    def PostWebMessageAsJson(self, j):
        self.posted.append(j)

    def ExecuteScriptAsync(self, js):
        self.scripts.append(js)


class _FakeTask:
    Result = None

    def ContinueWith(self, cb):
        cb(self)          # 模拟线程池立即完成
        return self


class FakeCtl:
    n_created = 0

    def __init__(self):
        FakeCtl.n_created += 1
        self.Visible = False
        self._bounds = None
        self.disposed = False
        self.inited = False
        self.cvw = FakeCvw()

    @property
    def CoreWebView2(self):
        return self.cvw if self.inited else None

    @property
    def Bounds(self):
        return self._bounds

    @Bounds.setter
    def Bounds(self, v):
        self._bounds = v

    def BringToFront(self):
        pass

    def Dispose(self):
        self.disposed = True

    def EnsureCoreWebView2Async(self, env):
        self.inited = True
        return _FakeTask()


class FakeControls(list):
    def Add(self, c):
        self.append(c)

    def Remove(self, c):
        if c in self:
            self.remove(c)


class FakeForm:
    """mode='sync'：BeginInvoke 立即执行（UI 线程串行）。
    mode='async'：排队，drain() 手动排干（再现乱序窗口）。"""

    def __init__(self, mode='sync'):
        self.Controls = FakeControls()
        self.mode = mode
        self.q = []

    def BeginInvoke(self, act):
        if self.mode == 'sync':
            act()
        else:
            self.q.append(act)

    def drain(self):
        while self.q:
            self.q.pop(0)()


class FakeArgs:
    def __init__(self, uri):
        self.Uri = uri
        self.handled = False

    def set_Handled(self, v):
        self.handled = v


@pytest.fixture
def stub_clr(monkeypatch):
    """注入 System / System.Drawing / WinForms 桩，退场还原。

    注意 `import a.b.c` 会逐级导入父包——父级也要占位（No module named
    'Microsoft' 的教训）。"""
    stub_sys = types.ModuleType('System')
    stub_sys.Action = _ActionProto()
    # System.Action[System.Threading.Tasks.Task](fn)：下标表达式先求值
    stub_sys.Threading = types.SimpleNamespace(
        Tasks=types.SimpleNamespace(Task=object))
    stub_draw = types.ModuleType('System.Drawing')
    stub_draw.Rectangle = _FakeRect
    stub_sys.Drawing = stub_draw
    wf = types.ModuleType('Microsoft.Web.WebView2.WinForms')
    wf.WebView2 = FakeCtl
    parents = [types.ModuleType(n) for n in
               ('Microsoft', 'Microsoft.Web', 'Microsoft.Web.WebView2')]
    keys = ('System', 'System.Drawing', 'Microsoft', 'Microsoft.Web',
            'Microsoft.Web.WebView2', 'Microsoft.Web.WebView2.WinForms')
    saved = {k: sys.modules.get(k) for k in keys}
    monkeypatch.setitem(sys.modules, 'System', stub_sys)
    monkeypatch.setitem(sys.modules, 'System.Drawing', stub_draw)
    for m in parents:
        monkeypatch.setitem(sys.modules, m.__name__, m)
    monkeypatch.setitem(sys.modules, 'Microsoft.Web.WebView2.WinForms', wf)
    FakeCtl.n_created = 0
    yield
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _mk(mode='sync'):
    from src.web_tabs import WebTabs

    class _T(WebTabs):
        def _ensure_env(self):     # 测试不创建真 WebView2 环境
            pass

    t = _T(FakeForm(mode))
    t._env = object()
    return t


# ---------- 用例 ----------

def test_create_dedup_last_nav_wins(stub_clr):
    """连点回车双发 create：只建一个控件，末次导航胜出。"""
    t = _mk('async')
    assert t.create('t1', 'https://a/') == {'ok': True}
    assert t.create('t1', 'https://b/') == {'ok': True}   # 在途去重
    t._form.drain()
    assert FakeCtl.n_created == 1
    ctl = t._ctl['t1']
    assert ctl.cvw.navigated == ['https://a/', 'https://b/']


def test_show_pending_guard_and_layout_reveal(stub_clr):
    """show 先于 create._build 被处理：不误藏他 tab，layout 到达后补显。"""
    t = _mk('async')
    t.create('t1', 'https://a/')
    assert t.show('t1', True) == {'ok': True}    # 在途守卫：不应排 _apply
    t._form.drain()
    ctl = t._ctl['t1']
    assert ctl.Visible is False                  # 未经 layout 不显
    t.layout(10, 20, 300, 200)
    t._form.drain()
    assert ctl.Visible is True                   # layout 补显
    assert ctl._bounds.a == (10, 20, 300, 200)


def test_first_show_sentinel(stub_clr):
    """首份 layout 前显式 show 也被哨兵拦下，由 layout 补显。"""
    t = _mk('async')
    t.create('t1', 'https://a/')
    t._form.drain()
    t.show('t1', True)
    t._form.drain()
    assert t._ctl['t1'].Visible is False         # 哨兵：无 layout 不显
    t.layout(0, 0, 800, 600)
    t._form.drain()
    assert t._ctl['t1'].Visible is True


def test_show_snapshot_vs_dispose_race(stub_clr):
    """show 的可见性应用循环里并发 dispose 不抛、不死锁（快照迭代）。"""
    t = _mk('sync')
    t.layout(0, 0, 800, 600)                     # 前端时序：create 前必推 layout
    for i in range(3):
        t.create('t%d' % i, 'https://x/%d' % i)
    import threading
    th = threading.Thread(target=lambda: t.dispose('t1'))
    assert t.show('t0', True) == {'ok': True}    # 同步模式下先跑完再 dispose
    th.start()
    th.join()
    assert 't1' not in t._ctl
    assert t._ctl['t0'].Visible is True          # 意图已正确落地


def test_hidden_tab_suspends_pipeline(stub_clr):
    """a575：隐藏网页 tab = TrySuspendAsync（渲染管线真停，后台零产帧）；
    重新显示 = ResumeWebResourceRequests。"""
    t = _mk('sync')
    t.layout(0, 0, 800, 600)
    t.create('a', 'https://a/')
    t.create('b', 'https://b/')
    t.show('a', True)
    pw_b = t._ctl['b'].cvw
    assert pw_b.IsSuspended is True            # 后台 b 被挂起
    pw_a = t._ctl['a'].cvw
    assert pw_a.IsSuspended is False           # 活动 a 不挂起
    t.show('b', True)                        # 切到 b
    assert t._ctl['b'].cvw.IsSuspended is False  # b 恢复
    assert t._ctl['a'].cvw.IsSuspended is True   # a 转后台挂起


def test_hide_all_suspends_everything(stub_clr):
    """a575：全隐（hide_all）= 所有控件挂起。"""
    t = _mk('sync')
    t.layout(0, 0, 800, 600)
    t.create('a', 'https://a/')
    t.show('a', False)
    assert t._ctl['a'].cvw.IsSuspended is True


def test_anti_autosignin_injected(stub_clr):
    """a556：show(false) 只藏目标——后台 tab 休眠不得藏掉活动 tab。"""
    t = _mk('sync')
    t.layout(0, 0, 800, 600)
    t.create('a', 'https://a/')
    t.create('b', 'https://b/')
    assert t.show('a', True) == {'ok': True}      # 排他显示
    assert t._ctl['a'].Visible is True and t._ctl['b'].Visible is False
    t.show('b', False)                            # b 休眠：只藏 b
    assert t._ctl['a'].Visible is True            # 活动的不受影响
    assert t._ctl['b'].Visible is False


def test_show_seq_drops_stale(stub_clr):
    """a556：乱序迟到的旧 show 意图按 seq 丢弃（fetch 到达顺序无保证）。"""
    t = _mk('sync')
    t.layout(0, 0, 800, 600)
    t.create('a', 'https://a/')
    t.show('a', True, sq=5)
    assert t._ctl['a'].Visible is True
    t.show('a', False, sq=3)                      # 迟到的旧隐藏令 → 丢弃
    assert t._ctl['a'].Visible is True
    t.show('a', False, sq=6)                      # 新令 → 生效
    assert t._ctl['a'].Visible is False


def test_disposed_event_no_crash(stub_clr):
    """dispose 后在途 HistoryChanged（属性已死）不再裸穿 CLR 事件分发。"""
    t = _mk('sync')
    t.create('t1', 'https://a/')
    ctl = t._ctl['t1']
    t.dispose('t1')
    ctl.cvw._dead = True
    ctl.cvw.HistoryChanged.fire()                # 不应抛异常
    ctl.cvw.SourceChanged.fire()
    assert ctl.disposed


def test_new_window_push_ok(stub_clr):
    """主 UI 在位：推送 __webTabNew，不降级。"""
    t = _mk('sync')
    t.create('t1', 'https://a/')
    main = FakeCvw()
    t.set_main(main)
    args = FakeArgs('https://new/')
    t._ctl['t1'].cvw.NewWindowRequested.fire(args)
    assert args.handled is True
    assert any('__webTabNew' in s for s in main.scripts)
    assert 'https://new/' not in t._ctl['t1'].cvw.navigated


def test_new_window_fallback_navigates(stub_clr):
    """主 UI 推送失败（未装配/关停期）：降级本 tab 打开，不再静默吞。"""
    t = _mk('sync')
    t.create('t1', 'https://a/')
    # _main_cvw 保持 None（set_main 从未被调）
    args = FakeArgs('https://new/')
    t._ctl['t1'].cvw.NewWindowRequested.fire(args)
    assert args.handled is True
    assert t._ctl['t1'].cvw.navigated[-1] == 'https://new/'


def test_anti_autosignin_injected(stub_clr):
    """a557/a560：防自动签到脚本随控件初始化注入；autofill 恢复开。
    R9.9：第二个注入 = 无 form 登录的原生保存/填充打通脚本（合成 form
    + requestSubmit 喂密码管理器）——共 2 个，顺序固定。"""
    t = _mk('sync')
    t.create('t1', 'https://a/')
    ctl = t._ctl['t1']
    assert len(ctl.cvw.injected) == 1
    assert "input[type=password]" in ctl.cvw.injected[0]
    assert ctl.cvw.Profile.PasswordAutofillEnabled is True
    assert ctl.cvw.Profile.GeneralAutofillEnabled is True


def test_env_failed_fast_return(stub_clr):
    """env 永久失败后 create 快速返回，不再白等 5s。"""
    t = _mk('sync')
    t._env = None
    t._env_failed = True
    t0 = time.time()
    r = t.create('x', 'https://a/')
    assert r['ok'] is False
    assert time.time() - t0 < 0.5


def test_route_chain_complete(stub_clr):
    """R9.12 路由存在性钉测：a567 的死代码清理曾把 show/dispose/dispose_all/
    layout 连同 pw 路由一起误删（整链只剩 suspend），create 返回 bad act →
    控件永不创建 → 网页全黑 + 右键落在主文档（整工具刷新）。本钉测保证
    10 个 act 全部可达且不返回 bad act；未知 act 必须报 bad act（防
    「整链被删只剩兜底」的回归再犯——兜底行在，业务链不在也能红灯）。"""
    import flask
    from src import web_tabs as wt
    t = _mk('sync')
    old_tabs = wt._tabs
    wt._tabs = t
    try:
        app = flask.Flask(__name__)
        wt.register(app)
        client = app.test_client()
        acts = ["create", "nav", "back", "fwd", "reload", "suspend", "show",
                "dispose", "dispose_all", "layout"]
        for act in acts:
            body = {"act": act, "tab": "t1", "url": "https://a/",
                    "on": True, "sq": 1, "all": False,
                    "x": 0, "y": 0, "w": 100, "h": 100, "epoch": ""}
            r = client.post("/api/web/tabs", json=body)
            j = r.get_json()
            assert r.status_code == 200, (act, r.status_code, j)
            assert j.get("err") != "bad act", (act, j)
        # 反向钉：未知 act 必须报 bad act（兜底行必须在）
        r = client.post("/api/web/tabs", json={"act": "__nope__", "tab": "t1"})
        assert r.status_code == 200 and r.get_json().get("err") == "bad act"
    finally:
        wt._tabs = old_tabs
