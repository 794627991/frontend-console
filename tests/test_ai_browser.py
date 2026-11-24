# -*- coding: utf-8 -*-
"""AI 浏览器单测（2026-11-24 用户需求：AI 用 CDP 操作网页时，页面显示在 AI 会话
右侧分屏，用户看着 AI 操作）。

钉住的行为：
1. 总开关关闭 / 视图未就绪：中文报错；未就绪时推 ui_action: ai_browser_open
2. 壳登记（attach）与迟到的旧视图通知（detach 的 stale 判定）；只认网页视图
3. 导航白名单与等待夹限；点击 / 输入 / 按键发出的**真实 CDP 输入事件**序列；
   元素定位；窗口不可见时快速报清楚原因
4. wait / eval / dom / screenshot；console / network 环形缓冲；监听线程
5. MCP 进程侧：browser_* 转后端（失败文案不自相矛盾）；devtools_* 默认目标
   =AI 浏览器，target=app 才走工具自身界面（用户拍板）
6. devtools_cdp：eval_on / wait_event（含 socket 超时恢复）/ collect(stop) /
   send 的等待上限
7. 三端契约：分区名、IPC 通道、SSE 帧、路由——没有编译器帮忙，只能靠测试钉住

全程不连真实 CDP：CdpSession / find_cdp / list_targets / time 全部打桩。
对抗审计（2026-11-24）后补强：原先有恒真断言和「名字说测了其实没测」的用例，
逐条改成能真正失败的；三个判官指出的问题各配一条回归。
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, '.')

import flask
import pytest

import src.ai_browser as ab
import src.devtools_cdp as cdp
import src.mcp_server as mcp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class FakeTime:
    """替身 time：sleep 不真等，但让时钟走过同样秒数（deadline 逻辑照常）；
    其余属性转给真实 time。slept 累计睡掉的总时长——「上限封顶」类断言靠它。"""

    def __init__(self):
        self._now = 1000.0
        self.slept = 0.0

    def time(self):
        return self._now

    def sleep(self, s):
        s = max(0.0, float(s))
        self._now += s
        self.slept += s

    def __getattr__(self, k):
        return getattr(time, k)


class _WsMod:
    WebSocketTimeoutException = type("WebSocketTimeoutException", (Exception,), {})


class FakeWs:
    """CdpSession.send / wait_event / collect 的底层桩：按脚本吐帧。
    timeouts 记录每一次 settimeout 的值（验证「超时有没有恢复 / 是否真的生效」）。
    clock 给了的话，抛超时前让时钟走过本次 socket 超时（贴近真实阻塞）；
    帧写成 (秒数, 内容) 表示「阻塞这么多秒后才收到这一帧」。"""

    def __init__(self, frames=(), exc=None, clock=None):
        self.frames = list(frames)
        self.exc = exc
        self.clock = clock
        self.timeouts = []
        self.sent = []

    def settimeout(self, t):
        self.timeouts.append(t)

    def send(self, s):
        self.sent.append(s)

    def recv(self):
        if self.exc:
            raise self.exc
        if self.frames:
            f = self.frames.pop(0)
            if isinstance(f, tuple):
                if self.clock:
                    self.clock.sleep(f[0])
                return f[1]
            if isinstance(f, Exception):
                if self.clock:
                    self.clock.sleep(self.timeouts[-1] if self.timeouts else 0)
                raise f
            return f
        if self.clock:
            self.clock.sleep(self.timeouts[-1] if self.timeouts else 0)
        raise _WsMod.WebSocketTimeoutException()

    def close(self):
        pass


class _NS:
    pass


@pytest.fixture
def env(monkeypatch):
    """干净状态 + 桩 CDP + 收集广播 + Flask test client。"""
    with ab._lock:
        ab._state.update(target_id=None, wc_id=None, ts=0.0, gen=0)
    ab._hist_clear()
    ab._listen_gen[1] = -1
    monkeypatch.setattr(ab, "_broadcast_to_ai", lambda item: None)   # 防漏：用例自己装收集器
    e = _NS()
    e.sent = []            # (时刻, _broadcast_to_ai 收到的帧)
    e.calls = []           # CdpSession.send 的 (method, params, 时刻)
    e.wait_timeouts = []   # CdpSession.wait_event 收到的 timeout
    e.replies = {}         # method → result / 异常 / callable(params)
    e.targets = [{"id": "T1", "type": "webview"}]       # /json/list 桩
    e.load_ok = [True]     # wait_event("Page.loadEventFired") 是否等到
    e.clock = FakeTime()
    monkeypatch.setattr(ab, "time", e.clock)
    monkeypatch.setattr(ab, "_broadcast_to_ai", lambda item: e.sent.append((e.clock.time(), item)))
    monkeypatch.setattr(ab, "_listener_start", lambda: None)       # 不起真线程
    monkeypatch.setattr(ab, "_wait_listen", lambda timeout=3.0: True)   # 同上：不等监听就绪
    e.config = {"ai_browser_enabled": True}
    monkeypatch.setattr(ab._st, "_load_config", lambda: dict(e.config))

    class FakeSession:
        def __init__(self, port, tid):
            self.tid = tid

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send(self, method, params=None, timeout=10):
            e.calls.append((method, dict(params or {}), e.clock.time()))
            r = e.replies.get(method)
            if r is None:
                return {}
            if isinstance(r, Exception):
                raise r
            return r(params) if callable(r) else r

        def wait_event(self, names, timeout=20):
            e.wait_timeouts.append(timeout)
            return {"method": "Page.loadEventFired", "params": {}} if e.load_ok[0] else None

        def collect(self, seconds, on_event, stop=None):
            return "done"

    monkeypatch.setattr(ab._cdp, "CdpSession", FakeSession)
    monkeypatch.setattr(ab._cdp, "find_cdp", lambda timeout=1.0: 9222)
    monkeypatch.setattr(ab._cdp, "list_targets", lambda port, timeout=3.0: list(e.targets))
    app = flask.Flask("aibr_test")
    app.register_blueprint(ab.ai_browser_bp)
    app.config["TESTING"] = True
    c = app.test_client()
    e.post = lambda p, body=None: c.post(p, json=body or {}).get_json()
    e.get = lambda p: c.get(p).get_json()
    # 壳登记时带的三个字段（partition 是后端核对「确实是 AI 浏览器分区」的依据）
    e.attach = lambda: e.post("/api/ai_browser/attach",
                              {"wc_id": 7, "target_id": "T1", "partition": "persist:fc-ai-browser"})
    e.ops = lambda: [i for _t, i in e.sent if i.get("action") == "ai_browser_op"]
    e.op_times = lambda op: [t for t, i in e.sent
                             if i.get("action") == "ai_browser_op" and i.get("op") == op]
    return e


def _js(e, mapping):
    """Runtime.evaluate 桩：按表达式回值（没登记的表达式回 None）。"""
    e.replies["Runtime.evaluate"] = lambda p: {
        "result": {"value": mapping.get(p["expression"])}} if p["expression"] in mapping \
        else {"result": {"value": None}}


def _elem(x, y, label, ok=True, count=1, in_view=True):
    return json.dumps({"ok": ok, "count": count, "x": x, "y": y,
                       "inView": in_view, "label": label})


_ELEM = lambda sel, idx=0: ab._ELEM_JS % (json.dumps(sel), idx)   # noqa: E731
_PROBE = lambda sel: "!!document.querySelector(%s)" % json.dumps(sel)   # noqa: E731
_HIST_JS = lambda can, how: ab._HIST_JS % (can, how)   # noqa: E731


def _method(env, name):
    return [p for m, p, _t in env.calls if m == name]


def _sent_methods(env):
    return [m for m, _p, _t in env.calls]


# ---------- 1. 开关 / 就绪 ----------

def test_disabled_reports_without_opening(env, monkeypatch):
    env.config["ai_browser_enabled"] = False
    r = env.post("/api/ai_browser/navigate", {"url": "https://example.com"})
    assert r["ok"] is False
    assert "关闭" in r["err"] and "target=app" in r["err"]     # 指路：要操作工具界面得显式声明
    assert env.sent == [] and env.calls == []                  # 关闭时既不推展开也不连 CDP
    for path in ("click", "type", "press", "screenshot", "eval", "console", "reload"):
        assert env.post("/api/ai_browser/" + path, {})["ok"] is False


def test_not_ready_opens_then_times_out(env, monkeypatch):
    monkeypatch.setattr(ab, "ATTACH_TIMEOUT", 0.3)
    r = env.post("/api/ai_browser/navigate", {"url": "https://example.com"})
    assert r["ok"] is False and "没有及时就绪" in r["err"]
    assert [i["action"] for _t, i in env.sent] == ["ai_browser_open"]
    assert env.calls == []                                     # 没就绪不发任何 CDP 命令


def test_not_ready_succeeds_once_shell_registers(env, monkeypatch):
    # 前端展开后壳来登记：等待循环应当放行（登记在 0.2s 后到达）
    def _late(*a, **k):
        env.clock.sleep(0.2)
        assert env.attach()["ok"]
        return 0
    monkeypatch.setattr(ab, "_ui", lambda action, **kw: _late())
    assert env.post("/api/ai_browser/navigate", {"url": "https://example.com"})["ok"]


def test_cdp_port_down_fails_fast(env, monkeypatch):
    def _boom(timeout=1.0):
        raise cdp.CdpUnavailable()
    monkeypatch.setattr(ab._cdp, "find_cdp", _boom)
    monkeypatch.setattr(ab, "ATTACH_TIMEOUT", 5.0)
    t0 = env.clock.time()
    r = env.post("/api/ai_browser/navigate", {"url": "https://example.com"})
    assert r["ok"] is False and "9222" in r["err"]
    assert env.clock.time() - t0 < 0.01 and env.sent == []     # 端口不通：不空等、不推展开


# ---------- 2. 登记 ----------

def test_attach_detach_and_stale_notice(env):
    assert env.get("/api/ai_browser/state")["attached"] is False
    assert env.post("/api/ai_browser/attach", {"wc_id": 7})["ok"] is False      # 缺 target_id
    assert env.attach()["ok"] is True
    st = env.get("/api/ai_browser/state")
    assert st == {"ok": True, "enabled": True, "attached": True}
    assert env.post("/api/ai_browser/detach", {"wc_id": 6})["stale"] is True    # 旧视图的迟到通知
    assert env.get("/api/ai_browser/state")["attached"] is True
    env.post("/api/ai_browser/detach", {"wc_id": 7})
    assert env.get("/api/ai_browser/state")["attached"] is False


def test_attach_only_accepts_ai_browser_partition(env):
    # 对抗复审：用户自己开的网页 tab 也是 type=webview——只看类型拦不住。
    # 壳按分区名认视图，登记时带上分区名，后端按同一个名字再核一遍
    body = {"wc_id": 1, "target_id": "T1"}
    for bad in ({}, {"partition": ""}, {"partition": "persist:webtabs"},
                {"partition": "persist:fc-ai-browser "}, {"partition": None}):
        r = env.post("/api/ai_browser/attach", dict(body, **bad))
        assert r["ok"] is False and "partition" in r["err"], (bad, r)
    assert env.get("/api/ai_browser/state")["attached"] is False
    assert env.post("/api/ai_browser/attach", dict(body, partition="persist:fc-ai-browser"))["ok"] is True


def test_attach_only_accepts_existing_webview_targets(env, monkeypatch):
    # 对抗审计：任意非空 target_id 都能登记——把工具自己的主页面登记进来，
    # devtools_* 的默认目标就又变回工具界面（拍板②被绕过）
    env.targets = [{"id": "PAGE", "type": "page"}, {"id": "SW", "type": "service_worker"}]
    part = {"wc_id": 1, "partition": "persist:fc-ai-browser"}
    r = env.post("/api/ai_browser/attach", dict(part, target_id="PAGE"))
    assert r["ok"] is False and "网页视图" in r["err"]
    assert env.post("/api/ai_browser/attach", dict(part, target_id="SW"))["ok"] is False
    assert env.get("/api/ai_browser/state")["attached"] is False

    def _boom(timeout=1.0):
        raise cdp.CdpUnavailable()
    monkeypatch.setattr(ab._cdp, "find_cdp", _boom)
    r = env.post("/api/ai_browser/attach", dict(part, target_id="T1"))
    assert r["ok"] is False and "CDP 端口连不上" in r["err"]
    assert env.get("/api/ai_browser/state")["attached"] is False


def test_operation_queue_is_bounded(env, monkeypatch):
    # 对抗复审：两个 AI 并发时，后一个在操作锁上排队的时间不算在 MCP 的 HTTP
    # 超时里——等太久会变成「调用方先放弃报失败、后端拿到锁后照做」。
    # 等锁有上限，超了快速失败让 AI 稍后重试
    monkeypatch.setattr(ab, "_OP_QUEUE_WAIT", 0.05)
    env.replies["Runtime.evaluate"] = lambda p: {"result": {"value": "T"}}
    env.attach()
    assert env.post("/api/ai_browser/eval", {"expression": "1"})["ok"] is True   # 正常不排队
    assert ab._op_lock.acquire(timeout=1)                                     # 模拟另一个操作正占着锁
    try:
        r = env.post("/api/ai_browser/eval", {"expression": "1"})
    finally:
        ab._op_lock.release()
    assert r["ok"] is False and "还没结束" in r["err"] and "稍后重试" in r["err"], r
    # 锁一定被还回来了（没泄漏）：之后照常可用
    assert env.post("/api/ai_browser/eval", {"expression": "1"})["ok"] is True


def test_dead_target_triggers_reopen(env, monkeypatch):
    assert env.attach()["ok"] is True
    env.targets = []                                          # 壳重启 / guest 销毁
    monkeypatch.setattr(ab, "ATTACH_TIMEOUT", 0.2)
    r = env.post("/api/ai_browser/navigate", {"url": "https://example.com"})
    assert r["ok"] is False
    assert "ai_browser_open" in [i["action"] for _t, i in env.sent]


# ---------- 3. 导航 ----------

def test_navigate_ok_and_whitelist(env):
    env.attach()
    env.replies["Page.navigate"] = {"frameId": "F"}
    _js(env, {"location.href": "https://example.com/", "document.title || ''": "Example"})
    r = env.post("/api/ai_browser/navigate", {"url": "https://example.com"})
    assert r["ok"] and r["url"] == "https://example.com/" and r["title"] == "Example"
    assert r["loaded"] is True and r["text"] == "已打开：https://example.com/  «Example»"
    assert env.ops() == [{"kind": "ui_action", "action": "ai_browser_op",
                          "op": "navigate", "text": "https://example.com"}]
    for bad in ("file:///C:/Windows/win.ini", "javascript:alert(1)", "ftp://x/y",
                "data:text/html,hi", "about:blank#x"):
        r = env.post("/api/ai_browser/navigate", {"url": bad})
        assert r["ok"] is False and "只接受" in r["err"], bad
    assert env.ops()[-1]["text"] == "https://example.com"   # 非法网址不推指示帧
    assert env.post("/api/ai_browser/navigate", {"url": "about:blank"})["ok"] is True


def test_navigate_error_and_slow_load(env):
    env.attach()
    env.replies["Page.navigate"] = {"frameId": "F", "errorText": "net::ERR_NAME_NOT_RESOLVED"}
    r = env.post("/api/ai_browser/navigate", {"url": "https://nope.invalid"})
    assert r["ok"] is False and "ERR_NAME_NOT_RESOLVED" in r["err"]
    env.replies["Page.navigate"] = {"frameId": "F"}
    env.load_ok[0] = False                                     # 没等到 load：不算失败
    r = env.post("/api/ai_browser/navigate", {"url": "https://slow.example"})
    assert r["ok"] is True and r["loaded"] is False and "20 秒内没等到加载完成" in r["text"]


def test_navigate_wait_is_clamped(env):
    # 对抗审计：AI 把秒当毫秒传（30000）且页面迟迟不 load，会一直占着操作锁和
    # 整个 MCP 进程（单线程——串口工具也跟着不响应）。夹到 1–60 秒
    env.attach()
    env.replies["Page.navigate"] = {"frameId": "F"}
    _js(env, {"location.href": "https://x/", "document.title || ''": ""})
    for given, want in ((30000, 60.0), (0.1, 1.0), (-5, 1.0), ("abc", 20.0), (None, 20.0), (7, 7.0)):
        env.wait_timeouts.clear()
        env.load_ok[0] = False
        r = env.post("/api/ai_browser/navigate", {"url": "https://x", "timeout": given})
        assert r["ok"] is True and env.wait_timeouts == [want], (given, env.wait_timeouts)
    env.load_ok[0] = False
    r = env.post("/api/ai_browser/navigate", {"url": "https://x", "timeout": 30000})
    assert "60 秒内没等到加载完成" in r["text"]               # 文案说的是夹限后的数


# ---------- 4. 点击 / 输入 / 按键：真实输入事件序列 ----------

def test_click_selector_moves_then_clicks(env):
    env.attach()
    _js(env, {_ELEM("#btn"): _elem(120, 65, "button「搜索」")})
    r = env.post("/api/ai_browser/click", {"selector": "#btn"})
    assert r["ok"] and r["label"] == "button「搜索」" and r["text"] == "已点击 button「搜索」"
    assert r["in_view"] is True
    mouse = _method(env, "Input.dispatchMouseEvent")
    assert [(p["type"], p["button"]) for p in mouse] == [
        ("mouseMoved", "none"), ("mousePressed", "left"), ("mouseReleased", "left")]
    assert all(p["x"] == 120 and p["y"] == 65 for p in mouse)
    assert mouse[1]["clickCount"] == 1
    # 指示帧先于鼠标事件、且间隔 ≥0.3s：前端先把光标移过去（看得见「移过去、再点」）
    t_op = env.op_times("click")[0]
    t_mouse = [t for m, _p, t in env.calls if m == "Input.dispatchMouseEvent"][0]
    assert t_mouse - t_op >= 0.3 - 1e-6
    assert env.ops()[-1] == {"kind": "ui_action", "action": "ai_browser_op",
                             "op": "click", "x": 120, "y": 65, "label": "button「搜索」"}


def test_click_warns_when_center_outside_viewport(env):
    env.attach()
    _js(env, {_ELEM("#big"): _elem(5, 4000, "div「超高」", in_view=False)})
    r = env.post("/api/ai_browser/click", {"selector": "#big"})
    assert r["ok"] is True and r["in_view"] is False
    assert "不在网页可视区内" in r["text"] and "可能没点中" in r["text"]
    assert len(_method(env, "Input.dispatchMouseEvent")) == 3      # 照点，但把风险说清楚


def test_element_lookup_scrolls_instantly_and_judges_the_center(env):
    # 页面若设了 scroll-behavior:smooth，默认滚动是动画，紧接着取到的是滚动前坐标
    assert "scrollIntoView({block:'center', inline:'center', behavior: 'instant'})" in ab._ELEM_JS
    # 对抗复审：提示说的是「中心不在可视区内」，判定就必须看中心点——原先判的是整个
    # 元素四条边都在视口内，比视口高的大元素（中心明明可点）会被误报
    assert re.search(r"inView: cx >= 0 && cy >= 0 && cx <= innerWidth && cy <= innerHeight",
                     ab._ELEM_JS), "inView 必须判中心点"
    assert "r.bottom <= innerHeight" not in ab._ELEM_JS and "r.right <= innerWidth" not in ab._ELEM_JS
    # 字面量只能证明「写成了这样」；这里用 Node 真执行这段脚本，喂三个元素验证判定
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node：判定逻辑的执行验证跳过（字面量断言已覆盖）")
    body = (ab._ELEM_JS.replace("document.querySelectorAll(%s)", "document.querySelectorAll(SEL)")
            .replace("els[%d]", "els[IDX]"))
    # _ELEM_JS 是一个立即执行的函数；去掉结尾的调用括号，留函数本身反复调
    assert body.rstrip().endswith("})()")
    js = (
        "var SEL = '#x', IDX = 0;\n"
        "var innerWidth = 1000, innerHeight = 800;\n"
        "var document = { querySelectorAll: function () { return els; } };\n"
        "function rect(l, t, r, b) { return { left: l, top: t, width: r - l, height: b - t }; }\n"
        "function el(r) { return {\n"
        "  tagName: 'DIV',\n"
        "  scrollIntoView: function () {}, getBoundingClientRect: function () { return r; },\n"
        "  getAttribute: function () { return ''; }, innerText: '', textContent: '', value: '', id: '' }; }\n"
        "var els = [el(rect(100, 100, 300, 200)),      // 完全在视口内\n"
        "           el(rect(100, -500, 300, 3500)),    // 比视口高：中心 (200,1500) 在视口外\n"
        "           el(rect(100, -200, 300, 1000))];   // 比视口高：但中心 (200,400) 在视口内\n"
        "var probe = " + body.rstrip()[:-2] + ";\n"
        "var out = [];\n"
        "for (var i = 0; i < 3; i++) { IDX = i; out.push(JSON.parse(probe())); }\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8",
                       input="", timeout=20)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # 第三个：元素本身没有完整落在视口内（bottom 1000 > 800），但中心可点——不许误报
    assert [o["inView"] for o in out] == [True, False, True], out
    assert (out[1]["x"], out[1]["y"]) == (200.0, 1500.0)            # 坐标确实取的是元素中心


def test_click_by_coords_and_right_button(env):
    env.attach()
    r = env.post("/api/ai_browser/click", {"x": 10, "y": 20.5, "button": "RIGHT"})
    assert r["ok"] and r["label"] == "(10, 20.5)" and r["in_view"] is None
    assert _method(env, "Input.dispatchMouseEvent")[1]["button"] == "right"


def test_click_selector_miss_and_bad_args(env):
    env.attach()
    _js(env, {_ELEM("#nope"): _elem(0, 0, "", ok=False, count=0)})
    r = env.post("/api/ai_browser/click", {"selector": "#nope"})
    assert r["ok"] is False and "没找到元素 #nope" in r["err"]
    assert _method(env, "Input.dispatchMouseEvent") == []     # 找不到元素绝不乱点
    assert env.ops() == []
    r = env.post("/api/ai_browser/click", {})
    assert r["ok"] is False and "需要 selector" in r["err"]
    r = env.post("/api/ai_browser/click", {"selector": "#a", "index": "x"})
    assert r["ok"] is False and "参数错误" in r["err"]


def test_type_into_selector_clears_then_types(env):
    env.attach()
    _js(env, {_ELEM("#inp"): _elem(50, 30, "input「q」")})
    r = env.post("/api/ai_browser/type", {"selector": "#inp", "text": "hi"})
    assert r["ok"] and r["text"] == "已向 input「q」 输入：hi"
    keys = [(p["type"], p["key"], p.get("text"), p["modifiers"])
            for p in _method(env, "Input.dispatchKeyEvent")]
    assert keys == [("rawKeyDown", "a", None, 2), ("keyUp", "a", None, 2),      # Ctrl+A
                    ("rawKeyDown", "Delete", None, 0), ("keyUp", "Delete", None, 0),
                    ("keyDown", "h", "h", 0), ("keyUp", "h", None, 0),
                    ("keyDown", "i", "i", 0), ("keyUp", "i", None, 0)]
    assert len(_method(env, "Input.dispatchMouseEvent")) == 3    # 先点进去聚焦
    assert [o["op"] for o in env.ops()] == ["click", "type"]


def test_type_selector_miss_is_an_error(env):
    # 对抗审计：显式给了 selector 却没找到，原先悄悄改成输给当前焦点元素
    # （click 同场景是拒绝的）
    env.attach()
    _js(env, {_ELEM("#nope"): _elem(0, 0, "", ok=False, count=0)})
    r = env.post("/api/ai_browser/type", {"selector": "#nope", "text": "x"})
    assert r["ok"] is False and "没找到元素 #nope" in r["err"]
    assert not [m for m in _sent_methods(env) if m.startswith("Input.")]


def test_type_without_selector_keeps_content_and_can_press_enter(env):
    env.attach()
    r = env.post("/api/ai_browser/type", {"text": "ok", "enter": True})
    assert r["ok"] and "（回车确认）" in r["text"]
    keys = [(p["type"], p["key"], p["modifiers"]) for p in _method(env, "Input.dispatchKeyEvent")]
    assert keys == [("keyDown", "o", 0), ("keyUp", "o", 0), ("keyDown", "k", 0),
                    ("keyUp", "k", 0), ("rawKeyDown", "Enter", 0), ("keyUp", "Enter", 0)]
    assert _method(env, "Input.dispatchMouseEvent") == []        # 没给 selector：不点、不清空
    # 逐字路径也带物理键 code（与 _key 同口径；对抗复审指出原先不一致）
    assert [p["code"] for p in _method(env, "Input.dispatchKeyEvent")] == [
        "KeyO", "KeyO", "KeyK", "KeyK", "Enter", "Enter"]
    env.post("/api/ai_browser/type", {"text": "a5,"})
    assert [p["code"] for p in _method(env, "Input.dispatchKeyEvent")[-6:]] == [
        "KeyA", "KeyA", "Digit5", "Digit5", "Comma", "Comma"]


def test_type_unicode_or_long_uses_insert_text(env):
    env.attach()
    env.post("/api/ai_browser/type", {"text": "中文"})
    env.post("/api/ai_browser/type", {"text": "x" * 200})
    assert [p for p in _method(env, "Input.insertText")] == [
        {"text": "中文"}, {"text": "x" * 200}]
    assert _method(env, "Input.dispatchKeyEvent") == []
    assert env.post("/api/ai_browser/type", {"text": ""})["ok"] is False


def test_type_newline_becomes_enter(env):
    env.attach()
    env.post("/api/ai_browser/type", {"text": "a\nb"})
    keys = [(p["type"], p["key"]) for p in _method(env, "Input.dispatchKeyEvent")]
    assert ("rawKeyDown", "Enter") in keys and keys.count(("keyDown", "a")) == 1


def test_type_newline_becomes_enter_on_insert_text_path_too(env):
    # 对抗审计：非 ASCII / 长文本走 Input.insertText，\n 被当文本塞进去——
    # 工具描述承诺的「\n 表示回车」只在逐字路径兑现了
    env.attach()
    env.post("/api/ai_browser/type", {"text": "第一行\n\n第三行"})
    seq = [(m, p) for m, p, _t in env.calls
           if m == "Input.insertText" or (m == "Input.dispatchKeyEvent" and p["type"] != "keyUp")]
    assert seq == [("Input.insertText", {"text": "第一行"}),
                   ("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "Enter",
                                               "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                                               "modifiers": 0, "code": "Enter"}),
                   ("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "Enter",
                                               "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                                               "modifiers": 0, "code": "Enter"}),
                   ("Input.insertText", {"text": "第三行"})]


def test_press_key_combos(env):
    env.attach()
    env.post("/api/ai_browser/press", {"key": "Control+a"})
    env.post("/api/ai_browser/press", {"key": "Shift+Tab"})
    env.post("/api/ai_browser/press", {"key": "x"})
    env.post("/api/ai_browser/press", {"key": " "})
    k = [p for p in _method(env, "Input.dispatchKeyEvent") if p["type"] != "keyUp"]
    assert k[0] == {"type": "rawKeyDown", "key": "a", "code": "KeyA",
                    "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65, "modifiers": 2}
    assert k[1]["modifiers"] == 8 and k[1]["key"] == "Tab" and "text" not in k[1]
    assert k[2] == {"type": "keyDown", "key": "x", "code": "KeyX", "text": "x",
                    "unmodifiedText": "x", "windowsVirtualKeyCode": 88,
                    "nativeVirtualKeyCode": 88, "modifiers": 0}
    assert k[3]["key"] == " " and k[3]["text"] == " " and k[3]["code"] == "Space"
    for bad, word in (({"key": "nope"}, "不认识的按键"), ({"key": "Foo+a"}, "不认识的修饰键"),
                      ({"key": ""}, "不能为空"), ({"key": "  "}, "不能为空"), ({"key": "+"}, "不能为空")):
        r = env.post("/api/ai_browser/press", bad)
        assert r["ok"] is False and word in r["err"], bad


def test_press_modifier_bits_follow_cdp_spec(env):
    # CDP Input.dispatchKeyEvent 的 modifiers：Alt=1、Ctrl=2、Meta/Command=4、Shift=8。
    # 对抗审计实锤：此前 Alt 误写成 4（那是 Meta）——Alt 快捷键全成了 Meta 快捷键
    env.attach()
    for combo, mods in (("Alt+ArrowLeft", 1), ("alt+F4", 1), ("Control+a", 2), ("Ctrl+a", 2),
                        ("Meta+a", 4), ("Cmd+a", 4), ("Command+a", 4), ("Win+a", 4),
                        ("Shift+Tab", 8), ("Control+Shift+a", 10), ("Alt+Shift+a", 9),
                        ("Ctrl+Alt+Delete", 3), ("Ctrl+Alt+Shift+a", 11)):
        before = len(_method(env, "Input.dispatchKeyEvent"))
        assert env.post("/api/ai_browser/press", {"key": combo})["ok"] is True, combo
        got = [p for p in _method(env, "Input.dispatchKeyEvent")[before:] if p["type"] != "keyUp"]
        assert [p["modifiers"] for p in got] == [mods], (combo, got)
    assert ab._MODS["alt"] == 1 and ab._MODS["shift"] == 8


def test_press_shift_printable_types_shifted_character(env):
    # rawKeyDown 加 Shift 不产生文本：仅 Shift + 可打印字符要带 text（大写 / 上档符号）
    env.attach()
    for combo, key, text, code in (("Shift+a", "A", "A", "KeyA"), ("Shift+1", "!", "!", "Digit1"),
                                   ("Shift+,", "<", "<", "Comma"), ("Shift+Tab", "Tab", None, None)):
        before = len(_method(env, "Input.dispatchKeyEvent"))
        env.post("/api/ai_browser/press", {"key": combo})
        got = [p for p in _method(env, "Input.dispatchKeyEvent")[before:] if p["type"] != "keyUp"]
        assert len(got) == 1 and got[0]["key"] == key and got[0]["modifiers"] == 8, combo
        assert got[0].get("text") == text, (combo, got[0])
        if code:
            assert got[0]["code"] == code


def test_press_function_keys_and_odd_characters(env):
    env.attach()
    for name, vk in (("F1", 112), ("f5", 116), ("F12", 123)):
        before = len(_method(env, "Input.dispatchKeyEvent"))
        assert env.post("/api/ai_browser/press", {"key": name})["ok"] is True
        got = _method(env, "Input.dispatchKeyEvent")[before:]
        assert got[0]["windowsVirtualKeyCode"] == vk and got[0]["code"] == name.upper()
    # 大写后会变长的字符（ß → SS）：不能让 ord() 炸成「未知错误」
    before = len(_method(env, "Input.dispatchKeyEvent"))
    for name in ("ß", "Space", "space"):
        r = env.post("/api/ai_browser/press", {"key": name})
        assert r["ok"] is True, (name, r)
    got = _method(env, "Input.dispatchKeyEvent")[before:]      # 每个按键两个事件：down、up
    # ß：虚拟键码取不到就不给；code 也不能硬拼成 "KeySS"（对抗复审指出）
    assert got[0]["windowsVirtualKeyCode"] == 0 and "code" not in got[0] and got[0]["text"] == "ß"
    assert got[2]["code"] == "Space" and got[4]["code"] == "Space"      # "Space" 与 "space" 都认
    assert got[4]["key"] == " "


def test_press_key_code_for_digits_and_punctuation(env):
    env.attach()
    for combo, code, text in (("5", "Digit5", "5"), ("Shift+5", "Digit5", "%"),
                              (",", "Comma", ","), ("Shift+,", "Comma", "<"),
                              ("?", "Slash", "?"), ("-", "Minus", "-")):
        before = len(_method(env, "Input.dispatchKeyEvent"))
        assert env.post("/api/ai_browser/press", {"key": combo})["ok"] is True, combo
        got = _method(env, "Input.dispatchKeyEvent")[before:]
        assert [p["code"] for p in got] == [code, code] and got[0].get("text") == text, (combo, got)


def test_history_and_reload_run_inside_the_page(env):
    # 回归保护（端到端实锤）：不能用 CDP Page 域的导航命令——guest 的框架挂在宿主
    # 页面的框架树上，Page.reload 会把宿主页面（整个前端控制台界面）一起重载
    env.attach()
    _js(env, {_HIST_JS("Back", "back"): True, _HIST_JS("Forward", "Forward"): False,
              "location.reload()": None})
    assert env.post("/api/ai_browser/back")["text"] == "已后退"
    assert env.post("/api/ai_browser/forward")["text"] == "没有更靠后的页面"
    r = env.post("/api/ai_browser/reload", {})
    assert r["loaded"] is True and r["text"] == "已重新加载"
    sent = _sent_methods(env)
    for banned in ("Page.reload", "Page.navigateToHistoryEntry", "Page.getNavigationHistory"):
        assert banned not in sent, banned
    # 后退真走了才推指示帧（状态条：正在后退…）；没得退就不推
    assert [o["text"] for o in env.ops()] == ["后退", "重新加载"]
    # 页面立刻开始重载、location.reload() 的回包没等到：不算失败
    env.replies["Runtime.evaluate"] = lambda p: (_ for _ in ()).throw(
        cdp.CdpError("WS 读取失败: 页面可能已关闭"))
    env.load_ok[0] = False
    r = env.post("/api/ai_browser/reload", {})
    assert r["ok"] is True and r["loaded"] is False and "没等到加载完成" in r["text"]


def test_hidden_window_fails_fast_for_input_and_screenshot(env):
    # 端到端实锤：工具窗口被完全遮挡 / 最小化时，输入事件与截图会挂到超时——
    # 先挡住并说清原因，不让 AI 干等 10~20 秒再拿到一句「页面无响应」
    env.attach()
    _js(env, {"document.visibilityState": "hidden"})
    for path, body in (("click", {"selector": "#btn"}), ("click", {"x": 1, "y": 2}),
                       ("type", {"text": "a"}), ("press", {"key": "Enter"}),
                       ("screenshot", {})):
        r = env.post("/api/ai_browser/" + path, body)
        assert r["ok"] is False and "不可见" in r["err"], (path, r)
    assert not [m for m in _sent_methods(env)
                if m.startswith("Input.") or m == "Page.captureScreenshot"]
    # 读页面内容的操作不受影响
    _js(env, {"document.visibilityState": "hidden", "document.title": "T"})
    assert env.post("/api/ai_browser/eval", {"expression": "document.title"})["text"] == "T"
    # 窗口可见时照常；可见性检查不改变别的报错
    _js(env, {"document.visibilityState": "visible", _ELEM("#nope"): _elem(0, 0, "", ok=False, count=0)})
    assert "没找到元素" in env.post("/api/ai_browser/click", {"selector": "#nope"})["err"]


# ---------- 5. wait / eval / dom / screenshot ----------

def test_wait_fixed_ms_is_capped(env):
    env.attach()
    r = env.post("/api/ai_browser/wait", {"ms": 500})
    assert r["found"] is True and r["text"] == "已等待 500 ms"
    assert abs(env.clock.slept - 0.5) < 1e-6
    env.clock.slept = 0.0
    env.post("/api/ai_browser/wait", {"ms": 999999})          # 上限 10 秒
    assert abs(env.clock.slept - 10.0) < 1e-6
    assert _method(env, "Runtime.evaluate") == []             # 固定等待不查页面
    assert env.post("/api/ai_browser/wait", {})["ok"] is False


def test_wait_selector_hit_and_timeout(env):
    env.attach()
    _js(env, {_PROBE("#x"): True})
    r = env.post("/api/ai_browser/wait", {"selector": "#x"})
    assert r["found"] is True and "元素已出现" in r["text"]
    _js(env, {})
    t0 = env.clock.time()
    r = env.post("/api/ai_browser/wait", {"selector": "#y", "timeout": 3})
    assert r["ok"] is True and r["found"] is False and "3 秒内没等到" in r["text"]
    assert 3 <= env.clock.time() - t0 < 4


def test_eval_dom_screenshot(env, monkeypatch, tmp_path):
    env.attach()
    monkeypatch.setattr(ab._st, "DATA_DIR", str(tmp_path))    # 项目约定：数据目录只认 DATA_DIR
    _js(env, {"1+1": 2, "location.pathname": "/", "document.title": "T",
              "document.readyState": "complete",
              ab._DOM_JS % (json.dumps("div"), 20): json.dumps({
                  "url": "/", "title": "T", "ready": "complete", "count": 0, "items": []})})
    assert env.post("/api/ai_browser/eval", {"expression": "1+1"})["text"] == "2"
    assert "缺少必填参数" in env.post("/api/ai_browser/eval", {})["err"]
    r = env.post("/api/ai_browser/dom", {"selector": "div"})
    assert r["ok"] and r["text"].startswith("页面: T / [complete]\n命中 0 个")
    assert "缺少必填参数" in env.post("/api/ai_browser/dom", {})["err"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    env.replies["Page.captureScreenshot"] = {"data": base64.b64encode(png).decode()}
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] and os.path.isfile(r["path"]) and r["path"].startswith(str(tmp_path))
    assert r["path"].startswith(os.path.join(str(tmp_path), "ai_browser")) and "已保存" in r["text"]
    with open(r["path"], "rb") as f:
        assert f.read() == png
    env.replies["Page.getLayoutMetrics"] = {"cssContentSize": {"width": 1200.5, "height": 3000}}
    env.post("/api/ai_browser/screenshot", {"full": True})
    shot = _method(env, "Page.captureScreenshot")[-1]
    assert shot["clip"]["width"] == 1200.5 and shot["captureBeyondViewport"] is True
    env.replies["Page.captureScreenshot"] = {"data": ""}
    assert "截图没有拿到数据" in env.post("/api/ai_browser/screenshot", {})["err"]


def test_screenshot_dir_follows_data_dir(env, monkeypatch, tmp_path):
    # 用户把数据目录迁走后，截图必须跟着走（不是钉死在工具目录）
    env.attach()
    moved = tmp_path / "别处" / "数据"
    monkeypatch.setattr(ab._st, "DATA_DIR", str(moved))
    env.replies["Page.captureScreenshot"] = {"data": base64.b64encode(b"\x89PNG" + b"0" * 30).decode()}
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] and os.path.dirname(r["path"]) == os.path.join(str(moved), "ai_browser")


def test_expression_error_is_reported(env):
    env.attach()
    env.replies["Runtime.evaluate"] = {"result": {}, "exceptionDetails": {
        "exception": {"description": "ReferenceError: foo is not defined"}}}
    r = env.post("/api/ai_browser/eval", {"expression": "foo()"})
    assert r["ok"] is False and "表达式异常: ReferenceError" in r["err"]


def test_every_operation_emits_an_indicator_frame(env):
    # 拍板③（操作可视化）+ 用户主动重开的入口：用户关掉分屏 tab 后，AI 的任何
    # 一步操作都会让「AI 浏览器」tab 重新出现——只有导航/点击才推帧的话，
    # AI 接着只读页面（eval / 截图 / console）时用户就没有入口把视图调回来
    env.attach()
    _js(env, {_HIST_JS("Back", "back"): True, "location.reload()": None,
              "document.title || ''": "", "location.href": "https://x/",
              ab._DOM_JS % (json.dumps("a"), 20): json.dumps({
                  "url": "/", "title": "", "ready": "complete", "count": 0, "items": []})})
    env.replies["Page.navigate"] = {"frameId": "F"}
    env.replies["Page.captureScreenshot"] = {"data": base64.b64encode(b"\x89PNG" + b"0" * 30).decode()}
    start = len(env.sent)
    for path, body in (("navigate", {"url": "https://x/"}), ("eval", {"expression": "1"}),
                       ("dom", {"selector": "a"}), ("wait", {"selector": "a"}),
                       ("screenshot", {}), ("console", {}), ("network", {}),
                       ("back", {}), ("forward", {}), ("reload", {}),
                       ("press", {"key": "Enter"}), ("type", {"text": "t"}),
                       ("click", {"x": 1, "y": 2})):
        assert env.post("/api/ai_browser/" + path, body)["ok"] is True, path
    got = [i.get("op") for _t, i in env.sent[start:] if i.get("action") == "ai_browser_op"]
    for op in ("navigate", "eval", "dom", "wait", "screenshot", "console", "network",
               "press", "type", "click"):
        assert op in got, op
    assert got.count("navigate") == 3                    # 导航 + 后退 + 重载
    by_op = {o["op"]: o for o in env.ops()}
    assert by_op["eval"]["text"] == "1" and by_op["dom"]["text"] == "a" and by_op["wait"]["text"] == "a"
    assert by_op["screenshot"]["text"] == "" and by_op["console"]["text"] == ""
    # 指示帧带的是给状态条用的短文案，不是整段脚本
    env.post("/api/ai_browser/eval", {"expression": "第一行();\n第二行();"})
    assert env.ops()[-1]["text"] == "第一行();"


# ---------- 6. console / network 缓冲 ----------

def _feed_console_and_net(env):
    now = env.clock.time()
    ab._on_evt({"method": "Runtime.consoleAPICalled", "params": {"type": "log", "args": [
        {"value": "hello"}, {"type": "string", "value": "world"},
        {"type": "object", "description": "Object"}]}})
    ab._on_evt({"method": "Runtime.consoleAPICalled", "params": {
        "type": "warning", "args": [{"value": 42}]}})
    ab._on_evt({"method": "Runtime.exceptionThrown", "params": {"exceptionDetails": {
        "exception": {"description": "TypeError: boom"}}}})
    ab._on_evt({"method": "Log.entryAdded", "params": {"entry": {
        "level": "error", "text": "Failed to load resource"}}})
    ab._on_evt({"method": "Network.requestWillBeSent", "params": {"requestId": "r1", "type": "Document", "request": {
        "url": "https://x/page", "method": "GET"}}})
    ab._on_evt({"method": "Network.responseReceived", "params": {"requestId": "r1", "response": {"status": 200}}})
    ab._on_evt({"method": "Network.loadingFinished", "params": {"requestId": "r1", "encodedDataLength": 4096}})
    ab._on_evt({"method": "Network.requestWillBeSent", "params": {"requestId": "r2", "type": "XHR", "request": {
        "url": "https://x/api/missing", "method": "POST"}}})
    ab._on_evt({"method": "Network.responseReceived", "params": {"requestId": "r2", "response": {"status": 404}}})
    ab._on_evt({"method": "Network.loadingFinished", "params": {"requestId": "r2", "encodedDataLength": 12}})
    ab._on_evt({"method": "Network.requestWillBeSent", "params": {"requestId": "r3", "type": "Script", "request": {
        "url": "https://x/api/down.js", "method": "GET"}}})
    ab._on_evt({"method": "Network.loadingFailed", "params": {"requestId": "r3", "errorText": "net::ERR_TIMED_OUT"}})
    ab._on_evt({"method": "Network.requestWillBeSent", "params": {"requestId": "r4", "type": "Fetch", "request": {
        "url": "https://x/api/stream", "method": "GET"}}})
    ab._on_evt({"method": "Page.frameNavigated", "params": {}})      # 无关事件：忽略
    return now


def test_console_history(env):
    env.attach()
    _feed_console_and_net(env)
    r = env.post("/api/ai_browser/console", {"tail": 50})
    lines = r["text"].split("\n")
    assert lines[0] == "统计: error 2, warn 1（缓冲起点=视图最近一次连接）"
    assert lines[1].endswith("[log] hello world Object")
    assert any(l.endswith("[warn] 42") for l in lines)
    assert any(l.endswith("[error] TypeError: boom") for l in lines)
    assert any(l.endswith("[error] Failed to load resource") for l in lines)
    r = env.post("/api/ai_browser/console", {"level": "error"})
    assert "TypeError: boom" in r["text"] and "hello world" not in r["text"]
    r = env.post("/api/ai_browser/console", {"level": "warn"})
    assert "[warn] 42" in r["text"] and "hello world" not in r["text"]
    r = env.post("/api/ai_browser/console", {"tail": 1})
    assert "（已省略最早 3 条，显示最新 1 条）" in r["text"]


def _live_session(listener_gets_it):
    """实时窗口用的假会话：窗口内来一条 error 事件。listener_gets_it 为真时，
    常驻监听线程那条会话也收到同一条（CDP 语义：两条会话各收一份事件）。"""
    class LiveSession:
        def __init__(self, port, tid):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send(self, method, params=None, timeout=10):
            return {}

        def collect(self, seconds, on_event, stop=None):
            msg = {"method": "Runtime.consoleAPICalled", "params": {
                "type": "error", "args": [{"value": "once"}]}}
            if listener_gets_it:
                ab._on_evt(msg)
            on_event(msg)
            return "done"
    return LiveSession


def _once_in_history():
    with ab._hist_lock:
        return sum(1 for it in ab._console_buf if it["text"] == "once"), len(ab._console_buf)


def test_console_live_window_writes_history_only_when_listener_is_not_covering(env, monkeypatch):
    # 对抗审计 + 复审：常驻监听线程与实时窗口的临时会话各收一份同一条事件。
    #   监听已接上 → 临时会话不写历史（再写统计就翻倍）
    #   监听没接上（退避重连中）→ 临时会话是唯一的来源，必须写（否则这条就丢了）
    # 情况一：监听线程已接上当前视图
    monkeypatch.setattr(ab._cdp, "CdpSession", _live_session(True))
    env.attach()
    with ab._lock:
        ab._listen_mark(ab._state["gen"])
    _feed_console_and_net(env)
    r = env.post("/api/ai_browser/console", {"live_seconds": 1})
    assert "统计: error 2, warn 1" in r["text"]        # 历史那 4 条的统计，没被实时窗口改写
    assert "实时窗口 1s 收到 1 条" in r["text"] and "[error] once" in r["text"]
    assert _once_in_history() == (1, 5)                # 只有监听线程写的那一份
    # 情况二：监听线程没接上——临时会话写历史
    monkeypatch.setattr(ab._cdp, "CdpSession", _live_session(False))
    with ab._listen_cv:
        ab._listen_gen[1] = -1
    r = env.post("/api/ai_browser/console", {"live_seconds": 1})
    assert "实时窗口 1s 收到 1 条" in r["text"]
    assert _once_in_history() == (2, 6)                # 这一份来自临时会话
    # 再读一次历史：那一条还在（没丢）
    r = env.post("/api/ai_browser/console", {"tail": 50})
    assert r["text"].count("[error] once") == 2 and "统计: error 4, warn 1" in r["text"]


def test_console_tail_and_overflow(env):
    env.attach()
    for i in range(ab._LISTEN_MAX + 25):
        ab._on_evt({"method": "Runtime.consoleAPICalled", "params": {
            "type": "log", "args": [{"value": "m%d" % i}]}})
    assert len(ab._console_buf) == ab._LISTEN_MAX              # 环形：只留最新
    assert env.post("/api/ai_browser/console", {"tail": 100000})["text"].count("[log] m") == 200


def test_network_window(env):
    env.attach()
    now = _feed_console_and_net(env)
    r = env.post("/api/ai_browser/network", {"seconds": 10})
    lines = r["text"].split("\n")
    assert lines[0] == "最近 10s，共 4 请求 | 失败 1 | 4xx/5xx 1"
    assert lines[1] == "  !! FAIL:net::ERR_TIMED_OUT https://x/api/down.js"   # 失败的排最前
    assert lines[2] == "  !! 404 https://x/api/missing"
    assert "200 GET https://x/page Document 4k" in lines
    assert "[stream] GET https://x/api/stream Fetch " in r["text"]
    # 时间窗口：只留最近 5 秒（把前两条拨到 8 秒前）
    with ab._hist_lock:
        for rid in ("r1", "r2"):
            ab._net_buf[rid]["t"] = now - 8
    r = env.post("/api/ai_browser/network", {"seconds": 5})
    assert "共 2 请求 | 失败 1 | 4xx/5xx 0" in r["text"] and "/page" not in r["text"]
    r = env.post("/api/ai_browser/network", {"seconds": 10, "filter": "api"})
    assert "共 3 请求" in r["text"] and "/page" not in r["text"]


def test_attach_new_view_clears_history(env):
    part = {"partition": "persist:fc-ai-browser"}
    env.attach()
    _feed_console_and_net(env)
    assert len(ab._console_buf) == 4
    env.post("/api/ai_browser/attach", dict(part, wc_id=7, target_id="T1"))      # 同一视图：不清
    assert len(ab._console_buf) == 4
    env.targets.append({"id": "T2", "type": "webview"})
    env.post("/api/ai_browser/attach", dict(part, wc_id=9, target_id="T2"))      # 换了视图：清
    assert len(ab._console_buf) == 0 and len(ab._net_buf) == 0


def test_console_item_ignores_other_events():
    assert ab._console_item({"method": "Page.loadEventFired"}) is None
    assert ab._console_item({"method": "Log.entryAdded", "params": {"entry": {
        "level": "warning", "text": "w"}}})["lv"] == "warn"


def test_wait_listen_tracks_view_generation():
    # 不用 env 夹具：它为了不起真线程把 _wait_listen 桩掉了，这里要测真的。
    # _wait_listen 用的是真实的 Condition 定时等待：只给 0.05s，别拖慢测试
    try:
        with ab._lock:
            ab._state.update(target_id="T9", gen=7)
        ab._listen_gen[1] = -1
        assert ab._wait_listen(0.05) is False           # 监听线程还没接上这个视图
        ab._listen_mark(7)
        assert ab._wait_listen(0.05) is True
        with ab._lock:
            ab._state.update(target_id="T10", gen=8)    # 换了视图：旧的「已接上」不算数
        assert ab._wait_listen(0.05) is False
        ab._listen_mark(8)
        assert ab._wait_listen(0.05) is True
        with ab._lock:
            ab._state.update(target_id=None)            # 没有登记：不等
        assert ab._wait_listen(0.05) is False
    finally:
        # 用完复位，别把全局状态漏给别的用例
        with ab._lock:
            ab._state.update(target_id=None, gen=0)
        ab._listen_gen[1] = -1


def test_listener_tick_round(monkeypatch):
    """监听线程的一轮：连上 → 订阅三个域 → 标记「已接上」→ 登记换掉就收手；
    连接断了要把「已接上」撤掉（下次导航前等重新接上）。"""
    marked, sent, stop_seen = [], [], []

    class S:
        def __init__(self, port, tid):
            assert (port, tid) == (9222, "TL")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send(self, method, params=None, timeout=10):
            sent.append(method)
            return {}

        def collect(self, seconds, on_event, stop=None):
            stop_seen.append(stop is not None and stop())
            ab._listen_mark(3)                # 真的标记「已接上」——下面要验证它会被撤掉
            marked.append(ab._listen_gen[1])
            return "stopped"
    monkeypatch.setattr(ab._cdp, "CdpSession", S)
    monkeypatch.setattr(ab._cdp, "find_cdp", lambda timeout=1.0: 9222)
    try:
        with ab._lock:
            ab._state.update(target_id="TL", gen=3)
        ab._listen_gen[1] = -1
        assert ab._listener_tick() is True            # 视图仍是登记中的：需要再来一轮
        assert sent == ["Runtime.enable", "Log.enable", "Network.enable"]
        assert stop_seen == [False] and marked == [3]  # 连上时确实标记过（否则下面那条是恒真）
        assert ab._listen_gen[1] == -1                # 这一轮连接结束：「已接上」被撤掉
        # 没有登记时什么都不做
        with ab._lock:
            ab._state.update(target_id=None)
        sent.clear()
        assert ab._listener_tick() is False and sent == []
    finally:
        with ab._lock:
            ab._state.update(target_id=None, gen=0)
        ab._listen_gen[1] = -1


def test_listener_tick_reconnects_with_backoff(monkeypatch):
    # 登记还在但连不上（壳没了却没收到 detach）：这一轮连不上，但登记还在——下一轮再来
    class Boom:
        def __init__(self, *a):
            raise ConnectionError("连不上")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(ab._cdp, "CdpSession", Boom)
    monkeypatch.setattr(ab._cdp, "find_cdp", lambda timeout=1.0: 9222)
    try:
        with ab._lock:
            ab._state.update(target_id="TL", gen=1)
        ab._listen_mark(1)
        assert ab._listener_tick() is True            # 连不上，但登记还在：下一轮再来
        assert ab._listen_gen[1] == -1                # 「已接上」不能留着骗 navigate
    finally:
        with ab._lock:
            ab._state.update(target_id=None, gen=0)


def test_listener_loop_backoff_sequence_and_wakes_up(monkeypatch):
    # 监听线程主循环（对抗复审）：连不上时按 0.5 → 1 → 2 → 4 → 5 退避；退避等待必须
    # 能被 attach / detach 打断——第一版用 time.sleep，叫不醒，新视图最多晚 5 秒
    # 才被接上，超过 _wait_listen 的等待，首次导航的网络事件会漏
    class StopLoop(Exception):
        pass

    def run(wait_results, tick_results):
        waits, calls = [], []

        def fake_tick():
            calls.append(1)
            return next(ticks)                       # True = 这个视图仍是登记中的
        monkeypatch.setattr(ab, "_listener_tick", fake_tick)

        def fake_wait(timeout=None):
            if timeout is None:                      # 没有登记时等 attach：直接当被叫醒
                return True
            waits.append(timeout)
            r = next(wait_results)
            if r == "stop":
                raise StopLoop()
            return r                                # True = 退避途中被 attach / detach 叫醒
        monkeypatch.setattr(ab._wake, "wait", fake_wait)
        ticks = iter(tick_results)
        with ab._lock:
            ab._state.update(target_id="TL", gen=1)
        with pytest.raises(StopLoop):
            ab._listener_loop()
        return waits, calls
    try:
        # 一直连不上、没人打断：0.5 → 1 → 2 → 4 → 5（封顶，之后一直是 5）
        waits, calls = run(iter([False] * 5 + ["stop"]), [True] * 10)
        assert waits == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0] and len(calls) == 6
        # 退避途中 attach 来了：退避归零，下一轮从 0.5 重新起
        waits, calls = run(iter([False, False, True, False, False, "stop"]), [True] * 10)
        assert waits == [0.5, 1.0, 2.0, 0.5, 1.0, 2.0] and len(calls) == 6
        # 监听说「不再是登记中的」（登记换掉了）：不退避，立刻去接新的
        waits, calls = run(iter(["stop"]), [False, True, True, True])
        assert waits == [0.5] and len(calls) == 2
    finally:
        with ab._lock:
            ab._state.update(target_id=None, gen=0)
        ab._listen_gen[1] = -1


def test_next_backoff_is_capped():
    seq = [0.5]
    for _ in range(6):
        seq.append(ab._next_backoff(seq[-1]))
    assert seq == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0, 5.0]


# ---------- 7. MCP 进程侧 ----------

def test_mcp_browser_tools_delegate_to_backend(monkeypatch):
    posted = []
    monkeypatch.setattr(mcp, "_post", lambda url, path, body, timeout=30: posted.append(
        (path, body, timeout)) or {"ok": True, "text": "T:" + path.rsplit("/", 1)[-1]})
    u = "http://backend"
    assert mcp.tool_browser_navigate(u, {"url": "https://x", "timeout": 3}) == "T:navigate"
    assert posted[-1][1] == {"url": "https://x", "timeout": 3.0}
    assert posted[-1][2] == 100                        # HTTP 超时 = 等待上限 + 60，下限 100
    assert mcp.tool_browser_wait(u, {"selector": "#a", "timeout": 25}) == "T:wait"
    assert posted[-1][2] == 100
    # 对抗复审：AI 把秒当毫秒传——后端自己会夹，但 MCP 的 HTTP 超时按它算，也必须夹
    mcp.tool_browser_navigate(u, {"url": "https://x", "timeout": 30000})
    assert posted[-1][1] == {"url": "https://x", "timeout": 60.0} and posted[-1][2] == 120
    mcp.tool_browser_navigate(u, {"url": "https://x", "timeout": "abc"})   # 非数字：不传，后端用缺省
    assert posted[-1][1] == {"url": "https://x"} and posted[-1][2] == 100
    mcp.tool_browser_click(u, {"x": 0, "y": 5.5, "button": "right", "selector": None})
    assert posted[-1][1] == {"x": 0, "y": 5.5, "button": "right"}   # None 不传；0 照传
    mcp.tool_browser_click(u, {})
    assert posted[-1][1] == {}
    mcp.tool_browser_type(u, {"text": "hi", "enter": True})
    assert posted[-1][1] == {"text": "hi", "enter": True}
    mcp.tool_browser_console(u, {"live_seconds": 5, "level": "error"})
    assert posted[-1][2] == 105 and posted[-1][1] == {"live_seconds": 5, "level": "error"}
    assert mcp.tool_browser_screenshot(u, {"full": True}).startswith("T:screenshot\n用 Read")
    assert mcp.tool_browser_eval(u, {"expression": "1", "max_len": 9}) == "OK T:eval"
    mcp.tool_browser_network(u, {"seconds": 3})
    assert posted[-1][1] == {"seconds": 3}
    mcp.tool_browser_reload(u, {})
    assert posted[-1][1] == {} and posted[-1][0] == "/api/ai_browser/reload"
    assert mcp.tool_browser_back(u, {}) == "T:back"
    assert mcp.tool_browser_forward(u, {}) == "T:forward"
    mcp.tool_browser_press(u, {"key": "Control+a"})
    assert posted[-1][1] == {"key": "Control+a"} and posted[-1][2] == 100
    mcp.tool_browser_dom(u, {"selector": "a", "limit": 3})
    assert posted[-1][1] == {"selector": "a", "limit": 3}
    # 13 个工具各打各的路由（click 上面故意调了两次，所以按集合比）
    assert set(p for p, _b, _t in posted) == set(
        "/api/ai_browser/" + r for r in ("navigate", "click", "type", "press", "wait",
                                         "screenshot", "eval", "dom", "console", "network",
                                         "back", "forward", "reload"))


def test_mcp_http_timeout_leaves_headroom_over_backend_worst_case(monkeypatch):
    # MCP 的 HTTP 超时必须盖过后端最坏耗时，否则两个 AI 并发时后一个会在 MCP 层
    # 报「后端通信失败」，而后端其实把操作做完了。后端最坏 = 等操作锁
    # _OP_QUEUE_WAIT + 等视图就绪 ATTACH_TIMEOUT + 等监听 3s + Page.navigate 15s
    # + 等加载 T。原先取 T+30，恰好相等零余量
    posted = []
    monkeypatch.setattr(mcp, "_post", lambda url, path, body, timeout=30:
                        posted.append(timeout) or {"ok": True, "text": "T"})
    worst = ab._OP_QUEUE_WAIT + ab.ATTACH_TIMEOUT + 3.0 + 15.0
    mcp.tool_browser_navigate("http://b", {"url": "https://x", "timeout": 30000})   # T = 60
    assert posted[-1] == 120 and posted[-1] > worst + 60.0
    mcp.tool_browser_wait("http://b", {"selector": "#a", "timeout": 999})            # MCP 夹到 60
    assert posted[-1] == 120 and posted[-1] > worst + 30.0                           # 后端自己再夹到 30
    mcp.tool_browser_screenshot("http://b", {})                                    # 后端截图上限 20s
    assert posted[-1] == 100 and posted[-1] > worst + 20.0


def test_mcp_failure_text_is_consistent(monkeypatch):
    # 对抗审计：失败文案自相矛盾——eval 类回「OK 失败：…」，截图类回
    # 「失败：…\n用 Read 工具查看（图像）」
    monkeypatch.setattr(mcp, "_post", lambda *a, **k: {"ok": False, "err": "视图没有及时就绪"})
    u = "http://b"
    for name, text in (("eval", mcp.tool_browser_eval(u, {"expression": "1"})),
                       ("screenshot", mcp.tool_browser_screenshot(u, {})),
                       ("click", mcp.tool_browser_click(u, {"selector": "#a"})),
                       ("navigate", mcp.tool_browser_navigate(u, {"url": "https://x"})),
                       ("dom", mcp.tool_browser_dom(u, {"selector": "a"})),
                       ("console", mcp.tool_browser_console(u, {})),
                       ("network", mcp.tool_browser_network(u, {}))):
        assert text == "失败：视图没有及时就绪", (name, text)
    monkeypatch.setattr(mcp, "_post", lambda *a, **k: {"ok": False})
    assert mcp.tool_browser_press(u, {"key": "Enter"}) == "失败：后端没有说明原因"
    # 后端回了无法识别的内容（不是 JSON 对象）：也要说人话，不能落成「未知错误」
    for junk in ([1, 2], "oops", None):
        monkeypatch.setattr(mcp, "_post", lambda *a, _j=junk, **k: _j)
        assert mcp.tool_browser_press(u, {"key": "Enter"}) == "失败：后端返回了无法识别的内容（不是 JSON 对象）"


def test_mcp_devtools_default_target_is_ai_browser(monkeypatch):
    app_evals, br = [], []
    monkeypatch.setattr(mcp, "_aibr", lambda url, path, body=None, timeout=None, http_timeout=None:
                        br.append((path, body)) or "BR")
    monkeypatch.setattr(mcp.devtools_cdp, "evaluate",
                        lambda expr, max_len=4000: app_evals.append(expr) or "APP")
    u = "http://backend"
    # 缺省 = AI 浏览器（用户拍板：不再默认操作工具自身界面）
    assert mcp.tool_devtools_eval(u, {"expression": "document.title"}) == "OK BR"
    assert mcp.tool_devtools_dom(u, {"selector": "div", "limit": 3}) == "BR"
    assert br[-1] == ("dom", {"selector": "div", "limit": 3})
    assert mcp.tool_devtools_console(u, {"tail": 5, "live_seconds": 2}) == "BR"
    assert mcp.tool_devtools_network(u, {"seconds": 4.7, "filter": "api"}) == "BR"
    assert br[-1] == ("network", {"seconds": 4, "filter": "api"})
    assert mcp.tool_devtools_screenshot(u, {}).startswith("BR\n用 Read")
    assert app_evals == []
    n_br = len(br)
    # 显式 target=app 才走工具自身界面（原链路原样保留）
    assert mcp.tool_devtools_eval(u, {"expression": "document.title", "target": "APP"}) == "OK APP"
    assert mcp.tool_devtools_dom(u, {"selector": "div", "target": "app"}) == "APP"
    # app 链原样保留：eval 一次、dom 一次（dom 走 evaluate 发它的查询脚本）
    assert app_evals[0] == "document.title"
    assert len(app_evals) == 2 and app_evals[1].startswith("(function(){var els=")
    assert len(br) == n_br                              # target=app 不碰 AI 浏览器


def test_mcp_devtools_bad_target_is_plain_text():
    r = mcp.tool_devtools_eval("http://b", {"expression": "1", "target": "tool"})
    assert r.startswith("失败：") and "target 只能是" in r
    assert mcp.tool_devtools_eval("http://b", {}).startswith("失败：缺少必填参数")


def test_mcp_tool_table():
    names = [t["name"] for t in mcp._TOOLS]
    assert len(names) == len(set(names))
    assert sum(n.startswith("browser_") for n in names) == 13
    for t in mcp._TOOLS:
        if t["name"].startswith("devtools_"):
            assert t["inputSchema"]["properties"]["target"]["default"] == "browser"
        if t["name"].startswith("browser_"):
            assert hasattr(mcp, "tool_" + t["name"])          # 每个工具都有实现
    nav = next(t for t in mcp._TOOLS if t["name"] == "browser_navigate")
    assert (nav["inputSchema"]["properties"]["timeout"]["minimum"],
            nav["inputSchema"]["properties"]["timeout"]["maximum"]) == (1, 60)   # 与后端夹限一致
    assert nav["inputSchema"]["required"] == ["url"]
    wait = next(t for t in mcp._TOOLS if t["name"] == "browser_wait")
    assert (wait["inputSchema"]["properties"]["timeout"]["minimum"],
            wait["inputSchema"]["properties"]["timeout"]["maximum"]) == (1, 30)
    # 工具描述不能把人往「操作工具界面」上引：要操作得显式写 target=app
    for t in mcp._TOOLS:
        if t["name"].startswith("devtools_"):
            assert "默认" in t["description"] and 'target="app"' in t["description"], t["name"]
    # 只读的才允许断连重试；有副作用的（点击/输入/导航/eval）不在列
    assert {"browser_screenshot", "browser_dom", "browser_console", "browser_network"} \
        <= mcp._RETRY_SAFE_TOOLS
    assert not {"browser_click", "browser_type", "browser_press", "browser_navigate",
                "browser_eval", "browser_wait", "browser_reload", "browser_back",
                "browser_forward"} & mcp._RETRY_SAFE_TOOLS
    assert "devtools_eval" not in mcp._RETRY_SAFE_TOOLS      # 既有口径不动


# ---------- 8. devtools_cdp ----------

def test_eval_on_value_shapes(monkeypatch):
    class Cs:
        def __init__(self, res):
            self.res, self.sent = res, []

        def send(self, method, params=None, timeout=10):
            self.sent.append((method, params, timeout))
            return self.res
    assert cdp.eval_on(Cs({"result": {"value": 3}}), "1+2") == "3"
    assert cdp.eval_on(Cs({"result": {"value": "raw"}}), "s") == "raw"
    assert cdp.eval_on(Cs({"result": {"subtype": "unserializable",
                                      "description": "NaN"}}), "NaN") == "NaN"
    assert cdp.eval_on(Cs({"result": {"value": None}}), "v") == "null"
    cs = Cs({"result": {"value": "x" * 50}})
    assert cdp.eval_on(cs, "v", timeout=7, max_len=10).startswith("xxxxxxxxxx\n…（已截断，全长 50")
    assert cs.sent[0][0] == "Runtime.evaluate" and cs.sent[0][2] == 7
    with pytest.raises(cdp.CdpError, match="表达式异常: ReferenceError: nope"):
        cdp.eval_on(Cs({"result": {}, "exceptionDetails": {
            "exception": {"description": "ReferenceError: nope"}}}), "nope")


def _bare_session(ws):
    cs = cdp.CdpSession.__new__(cdp.CdpSession)       # 不走 __init__：不碰 websocket 库
    cs._ws_mod, cs._ws, cs._mid, cs._collector, cs._timeout = _WsMod, ws, 0, None, 3.0
    return cs


def test_wait_event_returns_matching_event():
    ws = FakeWs(['garbage', '{"id":1,"result":{}}', '{"method":"Page.frameNavigated"}',
                 '{"method":"Page.loadEventFired","params":{"timestamp":1}}'])
    got = []
    cs = _bare_session(ws)
    cs._collector = got.append
    ev = cs.wait_event("Page.loadEventFired", timeout=1)
    assert ev["method"] == "Page.loadEventFired"
    assert [m["method"] for m in got] == ["Page.frameNavigated"]   # 途中的事件喂 collector
    assert cs.wait_event(["X", "Page.loadEventFired"], timeout=0.05) is None   # 超时 → None


def test_wait_event_restores_socket_timeout(monkeypatch):
    # 对抗审计实锤（真实 websocket-client 下测得残留 0.47s / 0.30s）：等事件期间
    # 用 0.5s 短超时轮询，返回时不恢复——同一会话随后的命令只要回包稍慢就被
    # 截断成「WS 读取失败」。navigate 之后还要读网址和标题，正是这种命令
    clock = FakeTime()
    monkeypatch.setattr(cdp, "time", clock)
    ws = FakeWs([], clock=clock)                       # 一直超时 → 等到上限返回 None
    cs = _bare_session(ws)
    assert cs.wait_event("Page.loadEventFired", timeout=2) is None
    assert all(0 < t <= 0.5 for t in ws.timeouts[:-1])     # 等待期间是短超时轮询
    assert ws.timeouts[-1] == cs._timeout == 3.0           # 返回时恢复建连超时
    ws2 = FakeWs(['{"method":"Page.loadEventFired"}'])
    cs2 = _bare_session(ws2)
    assert cs2.wait_event("Page.loadEventFired", timeout=5)["method"] == "Page.loadEventFired"
    assert ws2.timeouts[-1] == 3.0                        # 命中返回的路径也恢复
    ws3 = FakeWs([], exc=ConnectionError("gone"))
    with pytest.raises(cdp.CdpError, match="WS 读取失败"):
        _bare_session(ws3).wait_event("X", timeout=1)
    assert ws3.timeouts[-1] == 3.0                        # 异常退出的路径也恢复


def test_send_waits_the_full_timeout_not_the_connect_timeout(monkeypatch):
    # 建连超时（_timeout=3s）只该管握手：留在 socket 上会让 send(timeout=15/20)
    # 名存实亡——截图、导航这类慢命令 3 秒就被判「WS 读取失败」
    clock = FakeTime()
    monkeypatch.setattr(cdp, "time", clock)
    ws = FakeWs([], clock=clock)                       # 页面一直不回包
    cs = _bare_session(ws)
    t0 = clock.time()
    with pytest.raises(cdp.CdpError) as ei:
        cs.send("Page.captureScreenshot", timeout=7)
    assert "超时 7s" in str(ei.value) and "WS 读取失败" not in str(ei.value)
    assert clock.time() - t0 >= 7 - 1e-6               # 等满了 7 秒，没被 3 秒截断
    assert max(ws.timeouts) > cs._timeout
    # 页面在第 5 秒才回包（超过建连超时 3s）：照样收到
    ws2 = FakeWs([(5.0, '{"id":1,"result":{"v":7}}')], clock=clock)
    cs2 = _bare_session(ws2)
    assert cs2.send("Page.navigate", timeout=10) == {"v": 7}
    # 真断连（没到上限就抛非超时异常）：报「WS 读取失败」而不是「超时」
    with pytest.raises(cdp.CdpError, match="WS 读取失败"):
        _bare_session(FakeWs([], exc=ConnectionError("reset"))).send("X", timeout=10)


def test_collect_stop_and_closed(monkeypatch):
    seen = []
    assert _bare_session(FakeWs()).collect(5, seen.append, stop=lambda: True) == "stopped"
    assert seen == []
    r = _bare_session(FakeWs(exc=ConnectionError("gone"))).collect(5, seen.append)
    assert r == "closed" and seen[-1]["method"] == "_cdp_disconnected"   # 断连可感知
    # 断连必须如实报「closed」：报成「done」会让监听线程在同一条死连接上空转
    assert r != "done"


def test_evaluate_fallback_unpacks_two_values(monkeypatch):
    # 回落分支原先按三个值解包 find_webtab_target()（只返回两个）——真走到即 ValueError
    monkeypatch.setattr(cdp, "find_cdp", lambda timeout=1.0: 9222)
    monkeypatch.setattr(cdp, "ENDPOINT_FILE", os.devnull)
    monkeypatch.setattr(cdp, "find_page_target",
                        lambda port, origin: (_ for _ in ()).throw(cdp.TargetNotFound("x")))
    monkeypatch.setattr(cdp, "find_webtab_target", lambda timeout=3.0: (9222, {"id": "W1"}))

    class Cs:
        def __init__(self, port, tid):
            assert (port, tid) == (9222, "W1")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send(self, method, params=None, timeout=10):
            return {"result": {"value": "ok"}}
    monkeypatch.setattr(cdp, "CdpSession", Cs)
    assert cdp.evaluate("1") == "ok"


def test_cdp_port_resolution(monkeypatch):
    # 抽成纯函数来测（对抗复审：别在测试里 reload 真模块——reload 后 CdpError 等异常类
    # 是新类，ai_browser / mcp_server 用 from-import 持有的还是旧类，之后真实会话
    # 抛的异常会穿过 except 落成「未知错误」）。FC_CDP_PORT 仅供隔离验证改指别的
    # 端口；配错了（非整数 / 超出端口范围）不能让后端导入期崩，也不能连到一个怪端口
    for raw, want in (("9333", 9333), ("18766", 18766), ("abc", 9222), ("0", 9222),
                      ("", 9222), (None, 9222), (" 18766 ", 18766), ("-5", 9222), ("99999", 9222)):
        assert cdp._resolve_debug_port(raw) == want, raw
    # 模块常量确实由它算：同一份环境变量，重算一遍应与常量一致（不 reload）
    assert cdp._DEBUG_PORT == cdp._resolve_debug_port(os.environ.get("FC_CDP_PORT"))
    monkeypatch.setenv("FC_CDP_PORT", "9333")
    assert cdp._resolve_debug_port(os.environ["FC_CDP_PORT"]) == 9333


# ---------- 9. 三端契约 ----------

def _function_body(src, header):
    """取出顶层函数体（从函数头到第一个顶格的右花括号）。"""
    a = src.find(header)
    assert a >= 0, header
    b = src.find("\n}\n", a)
    assert b > a, header
    return src[a:b + 2]


def test_cross_component_contract_literals():
    """三端必须对齐的字面量：分区名 / IPC 通道 / SSE 帧 / 路由 / 伪 tab 名。
    没有编译器帮忙，只能靠测试钉住（对抗审计：此前「三处对齐」只是口头约定，
    后端的 PARTITION 常量在它自己的文件里零引用）。"""
    py = _read("src", "ai_browser.py")
    sh = _read("electron", "main.js")
    pre = _read("electron", "preload.js")
    fe = _read("web", "js", "harness", "ai-browser.js")
    sense = _read("web", "js", "sense.js")
    mcp_py = _read("src", "mcp_server.py")
    part = "persist:fc-ai-browser"
    # 分区名：前端建 webview 用；壳凭它认视图（will-attach）并登记时上报；
    # 后端 attach 时核对；壳认领 guest 时比对其 session
    assert 'PARTITION = "%s"' % part in py and "!= PARTITION" in py
    assert sh.count("const AIBR_PARTITION = '%s';" % part) == 1
    assert fe.count("const AIBR_PARTITION = '%s';" % part) == 1
    assert fe.count("setAttribute('partition', AIBR_PARTITION)") == 1
    assert re.search(r"aibrPost\('/api/ai_browser/attach',\s*\{[^}]*partition: AIBR_PARTITION", sh), \
        "壳登记时必须带上分区名"
    assert "eSession.fromPartition(AIBR_PARTITION)" in sh
    # IPC 通道：preload 侧 invoke / on 的名字 == 壳侧 handle / send 的名字
    assert "invoke('fc:aibr-attach'" in pre and "ipcMain.handle('fc:aibr-attach'" in sh
    assert "on('fc:aibr-open-url'" in pre and "send('fc:aibr-open-url'" in sh
    assert "send('fc:webtab-open'" in sh                 # 既有通道仍在（别的 webview 用）
    # 壳：挂载即登记——认领判据不依赖两个事件的先后（首选分区判据，aibrPending 兜底）
    assert "params.partition === AIBR_PARTITION" in sh
    did_attach = _function_body(sh, "win.webContents.on('did-attach-webview', ")
    assert "byPartition === true" in did_attach and "byPartition === null && aibrPending" in did_attach
    assert "aibrRegister(gwc)" in did_attach
    # AI 浏览器视图不挂密码填充 preload：这个删除必须在「分区名命中」的分支里
    assert re.search(r"if \(aibrPending\) \{\s*delete webPreferences\.preload;", sh), \
        "delete preload 必须在 aibrPending 为真的分支内（否则会摘掉用户网页 tab 的 preload）"
    assert re.search(r"\} else \{\s*webPreferences\.preload = GUEST_PRELOAD;", sh)
    # attach 只认登记过的视图；登记失败不报成功
    assert "!aibrIds.has(n)" in sh
    assert "if (!r || r.ok !== true)" in sh and "r.ok === false) return" not in sh
    # SSE：后端推的 action，sense.js 都接；sense.js 接到的都转给 AI_BR
    for act in ("ai_browser_open", "ai_browser_op"):
        assert '_ui("%s"' % act in py or act in py
        assert "item.action === '%s'" % act in sense
    assert "window.AI_BR.open()" in sense and "window.AI_BR.op(item)" in sense
    # SSE op 取值：后端推的每一种 op，前端都有文案分支（不能推了没人画）
    ops_py = set(re.findall(r'_ui\("ai_browser_op", op="([a-z]+)"', py))
    ops_fe = set(re.findall(r"d\.op === '([a-z]+)'", fe))
    assert ops_py == ops_fe and len(ops_py) >= 10
    # 导航类指示帧的三个固定词：后端原样推，前端原样认
    for w in ("重新加载", "后退", "前进"):
        assert '_ui("ai_browser_op", op="navigate", text="%s")' % w in py, w
        assert w in fe, w
    # 壳 POST 的路由，后端都得有
    for route in ("/api/ai_browser/attach", "/api/ai_browser/detach"):
        assert route in sh and '@ai_browser_bp.route("%s"' % route in py, route
    # MCP 调的 13 条路由，后端都得有
    routes_py = set(re.findall(r'@ai_browser_bp.route\("/api/ai_browser/([a-z]+)"', py))
    routes_mcp = set(re.findall(r'_aibr\(url, "([a-z]+)"', mcp_py))
    assert routes_mcp <= routes_py and len(routes_mcp) == 13
    # 前端伪 tab 名 == 分屏模块的常量
    assert "const AIBR_TID = '__aibr__';" in fe and "type: '__aibr__'" in fe
    sub = _read("web", "js", "harness", "subpane.js")
    assert "const _SUB_AIBR = '__aibr__';" in sub and "window._SUB_AIBR = _SUB_AIBR;" in sub
    # 分屏的上限计数 / 逐出 / 残留清理 / 恢复认领 / 贴底滚动 都豁免它
    # （逐出那行原先只钉了它的子串，恒真——这里每条都带各自独有的上下文）
    for guard in ("_sub.order.filter(x => x !== _SUB_DIR && x !== _SUB_DYN && x !== _SUB_AIBR).length > 6",
                  "const old = _sub.order.find(x => x !== _SUB_DIR && x !== _SUB_DYN && x !== _SUB_AIBR)",
                  "&& t !== _SUB_AIBR && _sub.tabs[t])",
                  "t === _SUB_DYN || t === _SUB_AIBR) return false;",
                  "tid !== _SUB_DYN && tid !== _SUB_AIBR) _subScroll(tid);",
                  "t === _SUB_AIBR ? ((typeof ICO16"):
        assert guard in sub, guard
    # 总开关的键名：后端读写、设置页——同一个
    assert '"ai_browser_enabled"' in _read("src", "server.py") and "ai_browser_enabled" in py
    assert "ai_browser_enabled" in _read("web", "js", "settings.js")
    # MCP 的等待上限夹限 == 后端的夹限（两头各自夹，数字必须一致）
    assert "min(_AIBR_WAIT_MAX, max(1.0, v))" in mcp_py and "min(60.0, max(1.0, wait_s))" in py


def test_frontend_module_guards_from_audit():
    fe = _read("web", "js", "harness", "ai-browser.js")
    css = _read("web", "style", "harness.css")
    # AI 自动展开不是用户动作：不能把会话记成「想让分屏开着」（a638）
    assert re.search(r"_subShow\(\s*AIBR_TID\s*,\s*false\s*\)", fe), "AI 自动展开必须传 userIntent=false"
    assert re.search(r"_subShow\(\s*AIBR_TID\s*,\s*true", fe) is None, "AI 自动展开不许冒充用户动作"
    # 指示帧到达时舞台不在：先展开（展开请求可能丢在 SSE 断线期间）
    op_body = _function_body(fe, "function op(d) {")
    assert re.search(r"if \(!_S\.stage\) open\(\);", op_body)
    # 取网页视图标识只能等 dom-ready（更早会抛错）：attach 只由 dom-ready / open 触发
    assert re.search(r"wv\.addEventListener\('dom-ready', \(\) => \{", fe)
    assert "addEventListener('did-attach'" not in fe       # 不在更早的事件里取标识
    assert fe.count("getWebContentsId()") == 1
    url_line = [ln for ln in fe.split("\n") if ".getURL()" in ln]
    assert len(url_line) == 1 and "try {" in url_line[0]        # getURL 在 try 里调
    # 拖分隔条期间舞台不吃鼠标；转后台态让网页失焦
    assert "closest('[data-hg-subres]')" in fe and "classList.add('hg-aibr-drag')" in fe
    assert ".hg-aibr-stage.hg-aibr-drag { pointer-events: none; }" in css
    sync_body = _function_body(fe, "function _sync() {")
    assert "_S.wv.blur()" in sync_body
    # 后台态是近乎透明而不是隐藏（display:none 时截图挂死）
    assert ".hg-aibr-stage.hg-aibr-bg { left: 0; top: 0; width: 1280px; height: 800px;" in css
    assert "opacity: .001; pointer-events: none; }" in css
    # 对抗复审 N1：舞台回收后重建时，尺寸观察器要重新挂上——做成幂等的「保证在盯
    # 占位框」，建舞台 / 面板已存在 / 面板新建三条路径都调
    assert "function _observeSlot() {" in fe and "_S.ro.observe(_S.slot);" in fe
    assert len(re.findall(r"^\s*_observeSlot\(\)", fe, re.M)) == 3
    teardown = _function_body(fe, "function _teardownStage(")
    assert "_S.ro.disconnect()" in teardown and "_S.ro = null;" in teardown
    # 对抗复审 N2：回收计时只在三处重置（转前台 / 转后台 / AI 的每一步操作）。
    # _sync 的触发源包括全应用任意一次界面过渡——在 _sync 末尾无条件续命，等于
    # 应用在用就永远不回收
    assert len(re.findall(r"_touchReap\(\);", fe)) == 3
    assert sync_body.count("_touchReap();") == 2
    assert not sync_body.rstrip().endswith("_touchReap();\n}"), "_sync 末尾不许无条件续命"
    assert "_touchReap();" in op_body
    # 面板被整个移除时 ResizeObserver 不报告：另盯分屏 body 的子节点增删
    assert "new MutationObserver(_queueSync)" in fe and "observe(body, { childList: true })" in fe
    # 对抗复审 N3：网页渲染进程崩溃——自动重载一次；页面加载成功后标志复位；
    # 再打开时若仍处于崩溃态，先拆掉重建（节点还在但已是死的，不会自己换）
    assert re.search(r"addEventListener\('render-process-gone'", fe) and "wv.reload()" in fe
    dom_ready = fe[fe.index("wv.addEventListener('dom-ready'"):][:200]
    assert "_S.crashed = false;" in dom_ready, "dom-ready 必须复位崩溃标志"
    open_body = _function_body(fe, "function open() {")
    assert "if (_S.stage && _S.crashed) _teardownStage();" in open_body
