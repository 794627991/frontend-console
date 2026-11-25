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
import ast
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
import src.downloads as dl
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
    with dl._lock:
        dl._records.clear()
    # 下载类用例读写的数据目录：沙箱里专属的子目录。不直接用全局 DATA_DIR 的当前值
    # ——同批别的测试会在导入期把它改走且不恢复（test_vcs_git_ops 就是这样，实测
    # 跑在它后面时下载目录落到了沙箱外，被下面 _dl_wipe 的自证拦下）。
    # 没有隔离开关就直接失败：宁可整份全红，也不让任何一个用例碰真实的数据目录
    iso = os.environ.get("FC_STATE_DIR")
    assert iso, "测试自隔离未生效（FC_STATE_DIR 为空）——拒绝运行"
    monkeypatch.setattr(ab._st, "DATA_DIR", os.path.join(iso, "dl_test"))
    monkeypatch.setattr(ab, "_broadcast_to_ai", lambda item: None)   # 防漏：用例自己装收集器
    monkeypatch.setattr(dl, "_broadcast_to_ai", lambda item: None)   # 下载中心的 SSE 帧同理
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
    # 下载中心（src/downloads.py）与 AI 浏览器共用同一套桩：假时钟（否则「等下载结束」
    # 的用例会真等满 60 秒）与同一个帧收集器
    monkeypatch.setattr(dl, "time", e.clock)
    monkeypatch.setattr(dl, "_broadcast_to_ai", lambda item: e.sent.append((e.clock.time(), item)))
    monkeypatch.setattr(ab, "_listener_start", lambda: None)       # 不起真线程
    monkeypatch.setattr(ab, "_wait_listen", lambda timeout=3.0: True)   # 同上：不等监听就绪
    e.config = {"ai_browser_enabled": True}
    monkeypatch.setattr(ab._st, "_load_config", lambda: dict(e.config))
    # 配置的保存也走内存：下载目录配置（config 的 download_dir）的用例读写闭环，
    # 不碰磁盘上的 config.json
    monkeypatch.setattr(ab._st, "_save_config",
                        lambda cfg: (e.config.clear(), e.config.update(cfg)))

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
    app.register_blueprint(dl.downloads_bp)       # 下载中心（2026-11-24 用户令起独立成模块）
    app.config["TESTING"] = True
    c = app.test_client()
    e.post = lambda p, body=None: c.post(p, json=body or {}).get_json()
    e.status = lambda p, body=None: c.post(p, json=body or {}).status_code
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


def test_hidden_window_self_wakes_then_still_operates(env):
    # 2026-11-25 用户令「仿照 zcode：AI 浏览器要能后台 / 最小化 / 失焦下继续控制」。
    # 旧行为是 hidden 直接拒绝并报错——那等于把「后台可用」判了死刑。现在改为：
    # 先尝试唤醒（焦点模拟 + 生命周期 active + 强制视口），**仍不拒绝**，
    # 照常下发输入/截图，只在返回文案里如实提示风险。
    env.attach()
    png = b"\x89PNG" + b"0" * 30
    env.replies["Page.captureScreenshot"] = {"data": base64.b64encode(png).decode()}
    env.replies["Page.getLayoutMetrics"] = {"cssLayoutViewport":
                                            {"clientWidth": 1024, "clientHeight": 768}}
    _js(env, {"document.visibilityState": "hidden",
              _ELEM("#btn"): _elem(10, 20, "按钮")})
    for path, body in (("click", {"selector": "#btn"}), ("click", {"x": 1, "y": 2}),
                       ("type", {"text": "a"}), ("press", {"key": "Enter"}),
                       ("screenshot", {})):
        r = env.post("/api/ai_browser/" + path, body)
        assert r["ok"] is True, (path, r)
        assert "当前不可见（hidden）" in r["text"], (path, r)
    # 唤醒手段真的发了：焦点模拟 + 生命周期激活 + 强制视口。
    # 5 次操作各唤醒一次——**不可见时截图不重复跑**（每跑一遍最坏多 30s，
    # 会烧穿 MCP 的 100s HTTP 超时），所以正好是 5 次，不是 6 次。
    sent = _sent_methods(env)
    assert "Emulation.setFocusEmulationEnabled" in sent
    assert "Page.setWebLifecycleState" in sent
    assert [p["width"] for p in _method(env, "Emulation.setVisibleSize")] == [1024] * 5
    # 输入照常下发（hidden 不再是拦路虎）
    assert len(_method(env, "Input.dispatchMouseEvent")) >= 3
    assert [p for p in _method(env, "Input.dispatchKeyEvent") if p["type"] != "keyUp"]
    # 读页面内容的操作不受影响
    _js(env, {"document.visibilityState": "hidden", "document.title": "T"})
    assert env.post("/api/ai_browser/eval", {"expression": "document.title"})["text"] == "T"
    # 窗口可见时：不发任何唤醒命令、文案干净；也不改变别的报错
    env.calls.clear()
    _js(env, {"document.visibilityState": "visible",
              _ELEM("#nope"): _elem(0, 0, "", ok=False, count=0)})
    r = env.post("/api/ai_browser/press", {"key": "Tab"})
    assert r["text"] == "已按键 Tab", r
    sent = _sent_methods(env)
    for wake in ("Emulation.setFocusEmulationEnabled", "Page.setWebLifecycleState",
                 "Emulation.setVisibleSize"):
        assert wake not in sent, wake
    assert "没找到元素" in env.post("/api/ai_browser/click", {"selector": "#nope"})["err"]


def test_screenshot_falls_back_when_first_capture_fails(env):
    # 可见页面第一段截图失败（偶发超时）：退到「强制视口 → 再截」，成功就不碰离屏
    env.attach()
    png = b"\x89PNG" + b"0" * 30
    state = {"n": 0}

    def _shot(p):
        state["n"] += 1
        if state["n"] == 1:
            raise cdp.CdpError("页面无响应（Page.captureScreenshot 超时 20s）")
        return {"data": base64.b64encode(png).decode()}

    env.replies["Page.captureScreenshot"] = _shot
    env.replies["Page.getLayoutMetrics"] = {"cssLayoutViewport":
                                            {"clientWidth": 800, "clientHeight": 600}}
    _js(env, {"document.visibilityState": "visible"})
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] is True and r["text"].startswith("已保存"), r
    shots = _method(env, "Page.captureScreenshot")
    assert len(shots) == 2 and shots[1].get("fromSurface") is None, shots
    assert [p["width"] for p in _method(env, "Emulation.setDeviceMetricsOverride")] == [800]
    assert _method(env, "Emulation.clearDeviceMetricsOverride") == [{}]


def test_screenshot_when_hidden_always_reissues_the_wake_chain(env):
    # 受控实验实锤（真实最小化 + WebView guest）：
    #   · 未唤醒的 hidden 页 captureScreenshot 会挂到超时
    #   · 焦点模拟 + setWebLifecycleState('active') 之后普通截图 66~86ms 出图
    #   · fromSurface:false 反而挂死（只能最后兜底）
    #   · **焦点模拟是粘性的**：做过一次页面就永远自报 visible，所以截图不能
    #     按 visibilityState 早退——必须每次强制重发唤醒链
    env.attach()
    png = b"\x89PNG" + b"0" * 30
    shots = []

    def _shot(p):
        shots.append(dict(p))
        if len(shots) == 1:
            raise cdp.CdpError("页面无响应（Page.captureScreenshot 超时 3s）")
        return {"data": base64.b64encode(png).decode()}

    env.replies["Page.captureScreenshot"] = _shot
    env.replies["Page.getLayoutMetrics"] = {"cssLayoutViewport":
                                            {"clientWidth": 760, "clientHeight": 520}}
    _js(env, {"document.visibilityState": "hidden"})
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] is True and r["text"].startswith("已保存"), r
    sent = _sent_methods(env)
    assert "Emulation.setFocusEmulationEnabled" in sent
    assert "Page.setWebLifecycleState" in sent
    assert [p["width"] for p in _method(env, "Emulation.setDeviceMetricsOverride")] == [760]
    assert _method(env, "Emulation.clearDeviceMetricsOverride") == [{}]
    # 第二段是普通真帧（不是离屏）；离屏只在它也不成时才用
    assert len(shots) == 2 and shots[1].get("fromSurface") is None, shots
    # 全失败要报清每一步
    env.calls.clear()
    env.replies["Page.captureScreenshot"] = cdp.CdpError("就是不给帧")
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] is False and "截图失败" in r["err"] and "就是不给帧" in r["err"], r
    assert len(_method(env, "Page.captureScreenshot")) == 3      # 原始 / 强制视口 / 离屏


def test_screenshot_visible_page_uses_the_real_frame_without_metrics(env):
    # 窗口可见时：真帧 66~86ms，不该强加 DeviceMetricsOverride（会改变页面视口，
    # 让后续布局/坐标与用户所见不一致）
    env.attach()
    png = b"\x89PNG" + b"0" * 30
    env.replies["Page.captureScreenshot"] = {"data": base64.b64encode(png).decode()}
    _js(env, {"document.visibilityState": "visible"})
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] is True, r
    assert len(_method(env, "Page.captureScreenshot")) == 1
    assert _method(env, "Emulation.setDeviceMetricsOverride") == []


def test_wake_turns_page_visible_but_screenshot_still_reissues_wake_chain(env):
    # 端到端实锤的坑：焦点模拟是**粘性**的——做过一次页面就永远自报 visible，
    # 合成器却可能仍是 hidden。若按「现在 visible 了」早退，就会漏掉生命周期
    # 激活这一步，截图随即挂满超时。所以截图每次都强制重发唤醒链。
    env.attach()
    png = b"\x89PNG" + b"0" * 30
    vis = {"v": "hidden"}

    def _eval(p):
        expr = p.get("expression") or ""
        if expr == "document.visibilityState":
            return {"result": {"value": vis["v"]}}
        if expr == "document.readyState":
            return {"result": {"value": "complete"}}
        return {"result": {"value": ""}}

    env.replies["Runtime.evaluate"] = _eval
    env.replies["Emulation.setFocusEmulationEnabled"] = lambda p: (
        vis.update(v="visible"), {})[1]        # 焦点模拟让页面改口说 visible
    env.replies["Page.captureScreenshot"] = {"data": base64.b64encode(png).decode()}
    env.replies["Page.getLayoutMetrics"] = {"cssLayoutViewport":
                                            {"clientWidth": 900, "clientHeight": 700}}
    r = env.post("/api/ai_browser/screenshot", {})
    assert r["ok"] is True, r
    sent = _sent_methods(env)
    assert "Page.setWebLifecycleState" in sent, sent
    assert "Emulation.setFocusEmulationEnabled" in sent
    # 关键：第一次之后页面已经自报 visible。第二次截图**仍须**强制重发唤醒链
    # ——否则粘性焦点模拟会让它跳过生命周期激活，截图又挂满超时。
    env.calls.clear()
    assert vis["v"] == "visible"
    r2 = env.post("/api/ai_browser/screenshot", {})
    assert r2["ok"] is True, r2
    sent2 = _sent_methods(env)
    assert "Page.setWebLifecycleState" in sent2, sent2
    assert "Emulation.setFocusEmulationEnabled" in sent2, sent2


def test_unreadable_visibility_still_wakes_and_says_so(env):
    # 缺陷回归（对抗审计指出）：eval 抛异常（页面导航中/忙/超时）→ 原实现静默
    # 早退：一条唤醒命令都不发、提示为空，给 AI「一切正常」的假象。页面正忙恰是
    # 最需要唤醒的时刻。现在必须：照跑唤醒链，并如实说「这次没读到状态」。
    env.attach()
    env.replies["Runtime.evaluate"] = cdp.CdpError("页面无响应（Runtime.evaluate 超时 10s）")
    env.replies["Page.getLayoutMetrics"] = {"cssLayoutViewport":
                                            {"clientWidth": 800, "clientHeight": 600}}
    r = env.post("/api/ai_browser/press", {"key": "Tab"})
    assert r["ok"] is True, r
    sent = _sent_methods(env)
    assert "Emulation.setFocusEmulationEnabled" in sent, "读不到状态也要唤醒"
    assert "Page.setWebLifecycleState" in sent
    assert "没读到页面可见性" in r["text"], r
    # 但不能谎称「窗口不可见」——那是没测准的事
    assert "当前不可见" not in r["text"], r


def test_click_when_clearly_visible_does_not_wake(env):
    # 可见时一条唤醒命令都不该发（省 CDP 往返，也不碰页面）
    env.attach()
    _js(env, {"document.visibilityState": "visible",
              _ELEM("#btn"): _elem(10, 20, "按钮")})
    r = env.post("/api/ai_browser/click", {"selector": "#btn"})
    assert r["ok"] is True and r["text"] == "已点击 按钮", r
    sent = _sent_methods(env)
    for m in ("Emulation.setFocusEmulationEnabled", "Page.setWebLifecycleState",
              "Emulation.setVisibleSize"):
        assert m not in sent, (m, sent)


def test_wake_failures_are_reported_not_swallowed(env):
    # 唤醒命令失守时要能在返回文案里看见（原先全被 except: pass 吞掉，
    # 端到端排查时完全分不清「唤醒了但没用」和「唤醒命令根本没发出去」）
    env.attach()
    env.replies["Emulation.setFocusEmulationEnabled"] = cdp.CdpError("不支持该方法")
    _js(env, {"document.visibilityState": "hidden"})
    r = env.post("/api/ai_browser/press", {"key": "Tab"})
    assert r["ok"] is True, r
    assert "唤醒命令失败" in r["text"] and "focusEmu" in r["text"], r


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
    # 下载记录打的是下载中心（src/downloads.py），不在 /api/ai_browser/* 之下
    assert mcp.tool_browser_downloads(u, {"wait": 30}) == "T:list"
    assert posted[-1][0] == "/api/downloads/list"
    assert posted[-1][1] == {"wait": 30.0} and posted[-1][2] == 100
    # 13 个工具各打各的 AI 浏览器路由（click 上面故意调了两次，所以按集合比）
    assert set(p for p, _b, _t in posted if p.startswith("/api/ai_browser/")) == set(
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
    assert sum(n.startswith("browser_") for n in names) == 14
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
    assert {"browser_screenshot", "browser_dom", "browser_console", "browser_network",
            "browser_downloads"} <= mcp._RETRY_SAFE_TOOLS
    # browser_downloads 的 wait 可为 0（不等于「用缺省」）；上限与后端夹限一致
    dl = next(t for t in mcp._TOOLS if t["name"] == "browser_downloads")
    wprop = dl["inputSchema"]["properties"]["wait"]
    assert (wprop["minimum"], wprop["maximum"], wprop["default"]) == (0, 60, 0)
    assert "download" in dl["description"] and "不要凭页面文案" in dl["description"]
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


def test_shell_keeps_guest_alive_in_background():
    """后台可用（2026-11-25 用户令：仿照 zcode，AI 浏览器要能后台 / 最小化 / 失焦
    下继续操作）。三条壳侧配置：
      1. Chromium 的两个 backgrounding 开关
      2. CalculateNativeWinOcclusion 关掉——Windows 上「被别的窗口盖住」= 判隐藏
      3. **只给 AI 浏览器视图**设 webPreferences.backgroundThrottling = false
    受控实验的取舍（见 AGENTS.md）：全局 disable-background-timer-throttling
    **故意不开**——它会把主界面 2s/5s/10s/30s 的轮询在最小化时全速跑起来；
    而只关 guest 这一条就足以让定时器正常运行，还能保持 visibilityState=visible。
    """
    sh = _read("electron", "main.js")
    body = sh[sh.index("app.commandLine.appendSwitch('remote-debugging-port'"):
              sh.index("// Chromium 日志只留 FATAL")]
    for sw in ("'disable-backgrounding-occluded-windows'",
               "'disable-renderer-backgrounding'"):
        assert "appendSwitch(%s)" % sw in body, sw
    assert "appendSwitch('disable-features', 'CalculateNativeWinOcclusion')" in body
    # 全局定时器节流开关**不该**出现（会连带节流主界面，白烧 CPU）
    assert "'disable-background-timer-throttling'" not in body, \
        "全局节流开关会连带主界面轮询全速跑；只给 guest 关节流即可（受控实验）"
    attach = _function_body(sh, "win.webContents.on('will-attach-webview', ")
    assert "if (aibrPending) webPreferences.backgroundThrottling = false;" in attach, \
        "只给 AI 浏览器视图关节流——普通网页标签页全关等于全都白烧 CPU"


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
    # 壳 POST 的 AI 浏览器路由，后端都得有
    for route in ("/api/ai_browser/attach", "/api/ai_browser/detach"):
        assert route in sh and '@ai_browser_bp.route("%s"' % route in py, route
    # MCP 调的 13 条 AI 浏览器路由，后端都得有
    routes_py = set(re.findall(r'@ai_browser_bp.route\("/api/ai_browser/([a-z]+)"', py))
    routes_mcp = set(re.findall(r'_aibr\(url, "([a-z]+)"', mcp_py))
    assert routes_mcp <= routes_py and len(routes_mcp) == 13
    # ---- 下载中心（2026-11-24 用户令）：独立成 src/downloads.py，AI 浏览器与普通
    # 网页标签页的下载共用。下面这些字面量把各端钉在一起 ----
    dls = _read("src", "downloads.py")
    assert set(re.findall(r'@downloads_bp.route\("/api/downloads/([a-z]+)"', dls)) == {
        "report", "list", "config", "forget", "open"}
    assert "app.register_blueprint(downloads_bp)" in _read("src", "server.py")
    # AI 浏览器模块不再有下载路由，只订阅下载中心（状态条显示）；状态条只认 AI 浏览器
    # 来源的下载——普通网页的下载若推 ai_browser_op，会把分屏给展开
    assert "/api/ai_browser/download" not in py and "_downloads.subscribe(_dl_status)" in py
    status = py[py.index("def _dl_status(rec, event):"):]
    assert 'rec.get("source") != "ai_browser" or event == "updated"' in status
    assert "else if (d.op === 'download') msg = text;" in fe
    # 壳：两个分区的 session 都挂 will-download——AI 浏览器与网页标签页（分区名与
    # web-panel.js 建标签页用的一致）。只挂前者 = 普通网页下载照旧弹保存框、没提示
    setup = _function_body(sh, "function dlSetup() {")
    assert "Object.keys(DL_SOURCES)" in setup
    assert "eSession.fromPartition(part).on('will-download'" in setup
    assert "DL_SOURCES[AIBR_PARTITION] = 'ai_browser';" in sh
    assert "DL_SOURCES['persist:webtabs'] = 'webtab';" in sh
    assert _read("web", "js", "web-panel.js").count("setAttribute('partition', 'persist:webtabs')") == 1
    take = _function_body(sh, "function dlTakeOver(item, source) {")
    assert re.search(r"if \(!dlDir\) return;", take), "下载中心没给出可用目录必须不接管"
    assert "item.setSavePath(target)" in take                  # 设了保存路径 = 不弹保存框
    assert "const target = aibrDlPath(dlDir, name);" in take    # 只存进下载中心给的目录
    assert "aibrPost('/api/downloads/report'," in take and "id, source, filename:" in take
    assert "dlItems.set(id, item);" in take and "dlItems.delete(id);" in take
    # 进度帧不许按事件带的 state 字符串过滤：实测是 'progressing' 而非文档的 'in_progress'
    #（按后者写会把进度全吃掉，2026-11-24 实跑踩到）；「还没结束」以 dlItems 为准
    assert "state !== 'in_progress'" not in take and "if (!dlItems.has(id)) return;" in take
    # 目录只认下载中心 GET /api/downloads/config，且只有后端明确说「可用」才接管；
    # 登记响应不再带目录；后端地址一有就取一次；用户改了配置，界面让壳立刻重取
    fetch_body = _function_body(sh, "function dlFetchDir() {")
    assert "fetch(endpointUrl + '/api/downloads/config')" in fetch_body
    assert "j.usable === true" in fetch_body
    assert "download_dir" not in _function_body(sh, "async function aibrAttach(wcId) {")
    assert re.search(r"endpointUrl = url;\n\s*//[^\n]*\n\s*dlFetchDir\(\);", sh), "后端地址有了要先取下载目录"
    refresh_h = re.search(r"ipcMain\.on\('fc:dl-refresh', \(e\) => \{(.*?)\n\}\);", sh, re.S).group(1)
    assert "e.sender === win.webContents) dlFetchDir();" in refresh_h     # 只认主界面
    # 取消：只认主界面发来的，只对进行中的下载
    cancel_h = re.search(r"ipcMain\.handle\('fc:dl-cancel', \(e, id\) => \{(.*?)\n\}\);", sh, re.S).group(1)
    assert "e.sender !== win.webContents" in cancel_h and "dlItems.get(String(id))" in cancel_h
    assert "it.cancel()" in cancel_h
    assert "invoke('fc:dl-cancel'" in pre and "send('fc:dl-refresh'" in pre   # preload 与壳同名
    # 同名不覆盖：目录里已有的、另一个进行中的下载占着的路径都要跳过
    dl_path = _function_body(sh, "function aibrDlPath(dir, name) {")
    assert "fs.existsSync(p)" in dl_path and "aibrDlReserved.has(p)" in dl_path
    assert "base + ' (' + n + ')' + ext" in dl_path
    # 后端：「完成」要自己核实文件在下载目录里才给路径
    assert 'size, why = _verified(d.get("path"))' in dls
    # 两头的等待夹限数字必须一致；这条下限是 0（与 navigate/wait 的 1 不同）
    assert "min(_AIBR_WAIT_MAX, max(0.0, wait_s))" in mcp_py
    assert "min(WAIT_MAX, max(0.0, wait_s))" in dls
    assert "_AIBR_WAIT_MAX = 60.0" in mcp_py and "WAIT_MAX = 60.0" in dls
    # MCP 的下载记录打的是下载中心
    assert '_post(url, "/api/downloads/list", {"wait": wait_s}' in mcp_py
    # SSE：下载中心每个阶段都推 kind="download"；sense.js 转给下载面板且不进感知流
    assert '_broadcast_to_ai(dict(rec, kind="download", event=event))' in dls
    assert re.search(r"if \(item\.kind === 'download' && window\.DL\) \{\s*window\.DL\.onEvent\(item\);", sense)
    # 下载面板（web/js/downloads.js）：入口在**网页标签页工具栏** + 浮层。
    # 它只「看」和打开 / 取消 / 移除记录——删文件只能在设置的「可清理项」里
    dljs = _read("web", "js", "downloads.js")
    html = _read("web", "index.html")
    # 2026-11-25 用户令：入口移进网页工具栏（密码钥匙右边），顶栏钮已删
    assert 'window.DL = { onEvent, refresh, toggleFrom };' in dljs
    assert "document.getElementById('btnDownloads')" not in dljs, "顶栏入口已退役"
    assert html.count('id="btnDownloads"') == 0, "顶栏下载钮必须已删除"
    webtab = _read("web", "js", "web-panel.js")
    assert 'data-web="dl"' in webtab, "下载入口必须在网页标签页工具栏"
    # 位置校验：dl 紧跟在 pw（密码钥匙）之后、read（阅读）之前
    assert re.search(r'data-web="pw".*?data-web="dl".*?data-web="read"',
                     webtab, re.S), "下载钮必须在密码钥匙右边、阅读左边"
    assert '<script type="module" src="web/js/downloads.js' in html
    for call in ("post('/api/downloads/list'", "post('/api/downloads/open'",
                 "post('/api/downloads/forget'", "window.fcShell.dlCancel(id)"):
        assert call in dljs, call
    assert "/api/data_dir/clean" not in dljs and "mode: 'all'" not in dljs, "面板不许删文件"
    # 2026-11-25 用户实锤「下载时没有弹出下载进度」：started 就自动弹面板
    assert "item.event === 'started'" in dljs, "下载开始必须自动弹面板"
    assert "item.event === 'done'" in dljs and "!_autoOpened" in dljs
    css = _read("web", "style", "base.css")
    assert '[data-web="dl"] { position: relative; }' in css
    assert ".dl-panel {" in css and ".dl-badge {" in css
    assert "#btnDownloads {" not in css, "顶栏钮的样式必须一起删"
    # 下载目录的配置（用户令：默认跟随数据目录，可手动指定）：设置页有入口，
    # 保存后让壳立刻重取
    settings = _read("web", "js", "settings.js")
    assert "fetch('/api/downloads/config'" in settings and "window.fcShell.dlRefresh()" in settings
    assert "if (window.DL) window.DL.refresh();" in settings      # 开着的面板头部目录跟着换
    assert 'id="ddDlPath"' in settings and 'id="ddDlApply"' in settings
    # 下载的删除入口（2026-11-24 用户令）：统一在 设置→数据目录→「可清理项」里，
    # 且只在那里。后端把下载列进可清理目标；前端确认条对它不显示「按策略清理」
    # （工具不替用户判断），按天数按钮的文案跟着目标走；不再有单独的「只显示」行
    settings = _read("web", "js", "settings.js")

    def _object(src, head):
        a = src.index(head)
        return src[a:src.index("};", a)]
    assert "row('AI 浏览器下载'" not in settings
    assert "Object.entries(j.targets || {}).map(([k, u]) =>" in settings
    assert "downloads: '工具不会自动删除下载的文件" in _object(settings, "const POLICY = {")
    assert "const NO_POLICY = { logs: true, downloads: true };" in settings
    assert "pending === 'logs' ? '删除旧日志' : '删除旧文件'" in settings
    # 下载走回收站；警告与成功提示按实际位置如实切换（本地硬盘能找回 / 网络位置、U 盘不能）
    assert "const _danger = (k) => k === 'downloads'" in settings
    assert "删除的文件会移入回收站，可以找回" in settings
    assert "不进回收站，删除后无法恢复" in settings
    assert "项移入回收站（" in settings and "downloads: '全部清空" not in settings
    hygiene = _read("src", "data_hygiene.py")
    assert '_CLEANABLE = ("uploads", "logs", "idx", "ask", "nav", "downloads")' in hygiene
    assert "if dl_default:" in hygiene and '"trash": _dl_recyclable(dl_dir),' in hygiene
    # 用户手动指定的目录：不进可清理项，清理入口也不认（那里面可能有用户自己的文件）
    clean_fn = hygiene[hygiene.index("def manual_clean("):hygiene.index("def cleanup_throttled(")]
    assert "if not st.download_dir_is_default():\n            return 0, 0" in clean_fn
    assert '"download_dir": {"path": dl_dir, "custom": not dl_default,' in hygiene
    assert "手动指定（工具不提供清理，要删请自己去文件夹）" in settings
    assert "from src.file_tree import _recycle_to_trash" in hygiene
    assert "DOWNLOAD_AGE_OPTIONS = LOG_AGE_OPTIONS" in hygiene
    assert '"downloads": DOWNLOAD_AGE_OPTIONS}.get(target)' in _read("src", "server.py")
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


# ---------- 12. 下载（2026-11-24 用户令：不弹保存框，自动存到 数据目录\download）----------

def _real(p):
    return os.path.normcase(os.path.realpath(p))


def _dl_wipe():
    """清空下载目录里的文件。动手前先自证它在沙箱里——FC_STATE_DIR 没设（不是
    pytest 身份）时这里直接失败，绝不拿真实的数据目录练手。"""
    d = ab._st.download_dir(create=True)
    assert _real(d).startswith(_real(os.environ["FC_STATE_DIR"]) + os.sep), \
        "下载目录不在沙箱里，拒绝清理"
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)               # 用例自己造的子文件夹
        else:
            os.remove(p)
    return d


def _dl_write(name, data=b"0123456789"):
    """模拟「壳把文件写进了下载目录」。"""
    p = os.path.join(ab._st.download_dir(create=True), name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _dl_report(env, did, **kw):
    # 默认按「AI 浏览器里的下载」上报（状态条的断言依赖来源）；普通网页标签页的用例自己传
    kw.setdefault("source", "ai_browser")
    kw.setdefault("filename", did + ".bin")
    return env.post("/api/downloads/report", dict(kw, id=did))


def _dl_rows(env, **kw):
    return env.post("/api/downloads/list", kw)["downloads"]


def _dl_row(env, did, **kw):
    return {r["id"]: r for r in _dl_rows(env, **kw)}[did]


def test_download_dir_follows_data_dir(env, monkeypatch):
    # 隔离自证（AGENTS.md 铁律）：目录由**被测进程自己**报出来看——必须在
    # FC_STATE_DIR 里、不在仓库里。下载目录默认跟数据目录走（用户令），而数据目录
    # 在隔离态落沙箱——放数据目录下天然隔离（放工具目录下则不然：APP_DIR 不认隔离开关）
    iso = os.environ.get("FC_STATE_DIR")
    assert iso, "pytest 身份下测试自隔离必须生效，否则这个用例会碰真实数据目录"
    orig = ab._st.DATA_DIR
    probe = os.path.join(iso, "dlprobe")
    monkeypatch.setattr(ab._st, "DATA_DIR", probe)              # 仍在沙箱里
    want = os.path.join(probe, "download")
    assert ab._st.download_dir() == want and ab._st.download_dir_is_default()
    assert not os.path.isdir(probe), "不带 create：只算路径，不建目录"
    assert ab._st.download_dir(create=True) == want and os.path.isdir(want)
    # 目录建不了 → None：调用方据此不接管下载，而不是落到别处
    blocker = os.path.join(iso, "dlblocker")
    with open(blocker, "w") as f:          # 同名位置是个文件，makedirs 必失败
        f.write("x")
    monkeypatch.setattr(ab._st, "DATA_DIR", blocker)
    assert ab._st.download_dir(create=True) is None
    assert ab._st.download_dir() == os.path.join(blocker, "download")   # 只算路径时不报错
    monkeypatch.setattr(ab._st, "DATA_DIR", "")
    assert ab._st.download_dir(create=True) is None and ab._st.download_dir() is None
    # 回到沙箱里的真实数据目录。逐项改回而不用 monkeypatch.undo()：测试函数与夹具
    # 拿的是同一个 monkeypatch，undo 会把夹具装的全部桩一起撤掉——登记请求就会
    # 去连真实的 CDP 调试口
    monkeypatch.setattr(ab._st, "DATA_DIR", orig)
    d = ab._st.download_dir()
    assert _real(d).startswith(_real(iso) + os.sep), "下载目录不在沙箱里"
    assert not _real(d).startswith(_real(ab._st.BASE_DIR) + os.sep), "下载目录不许落在仓库里"
    assert _real(os.path.dirname(d)) == _real(ab._st.DATA_DIR) and os.path.basename(d) == "download"


def test_attach_does_not_hand_out_download_dir(env):
    # 下载目录不再随登记结果交给壳（2026-11-24 用户令：普通网页标签页的下载也走同一
    # 套，与登记无关）——壳统一向下载中心 GET /api/downloads/config 取
    assert env.attach() == {"ok": True}


def test_dir_config_reports_default_and_unusable_dir(env, monkeypatch, tmp_path):
    # 壳据这个接口决定接不接管下载：usable=false（目录建不出来）就不接管、退回弹保存框
    r = env.get("/api/downloads/config")
    assert r == {"ok": True, "dir": ab._st.download_dir(), "custom": False,
                 "default_dir": ab._st.download_dir(), "usable": True, "reason": None}
    bad = str(tmp_path / "nope")            # 同名位置是个文件：目录建不出来
    with open(bad, "w") as f:
        f.write("x")
    assert env.post("/api/downloads/config", {"dir": bad})["ok"] is False   # 配置阶段就拒绝
    # 目录「后来」失效（配置时是好的，之后那个位置被换成了文件）：如实报不可用
    env.config["download_dir"] = os.path.join(bad, "sub")
    r = env.get("/api/downloads/config")
    assert (r["ok"], r["usable"], r["custom"]) == (True, False, True)
    assert "保存框" in r["reason"]
    env.config.pop("download_dir")


def test_download_lifecycle_is_recorded_and_shown_on_the_status_bar(env):
    env.attach()
    _dl_wipe()
    assert _dl_report(env, "dl_a", event="started", filename="资源包.fcpk",
                      total=1827874558, url="https://x.example/y")["ok"]
    rec = _dl_rows(env)
    assert len(rec) == 1
    assert (rec[0]["id"], rec[0]["filename"], rec[0]["state"]) == ("dl_a", "资源包.fcpk", "in_progress")
    assert (rec[0]["total"], rec[0]["received"], rec[0]["path"], rec[0]["error"]) == (1827874558, 0, None, None)
    assert "url" not in rec[0]                                   # 来源地址不外露
    frames = env.ops()
    assert [(f["op"], f["text"]) for f in frames] == [("download", "开始下载：资源包.fcpk")]
    # 进度：只更新记录，不推状态条（否则大文件把状态条刷成流水）
    env.sent.clear()
    _dl_report(env, "dl_a", event="updated", received=900, total=1800)
    assert env.ops() == [] and _dl_row(env, "dl_a")["received"] == 900
    assert _dl_row(env, "dl_a")["total"] == 1800
    # 完成：文件确实在下载目录里 → 记完成，大小以磁盘为准
    p = _dl_write("资源包.fcpk")
    _dl_report(env, "dl_a", event="done", state="completed", received=999, path=p)
    rec = _dl_row(env, "dl_a")
    assert (rec["state"], rec["path"], rec["received"]) == ("completed", p, 10)
    assert env.ops()[-1]["text"] == "下载完成：资源包.fcpk（10 B）→ 已存到下载目录"
    # 取消 / 失败
    env.sent.clear()
    _dl_report(env, "dl_b", event="started", filename="b.zip")
    _dl_report(env, "dl_b", event="done", state="cancelled")
    assert env.ops()[-1]["text"] == "下载已取消：b.zip"
    _dl_report(env, "dl_c", event="started", filename="c.bin")
    _dl_report(env, "dl_c", event="done", state="interrupted", received=5)
    rec = _dl_row(env, "dl_c")
    assert (rec["state"], rec["error"], rec["path"]) == ("interrupted", "下载被中断", None)
    assert env.ops()[-1]["text"] == "下载失败：c.bin（下载被中断）"
    assert _dl_row(env, "dl_b")["path"] is None
    # 重复的 started（同一 id）：更新而不是再登记一条
    _dl_report(env, "dl_a", event="started", total=7)
    assert len(_dl_rows(env)) == 3 and _dl_row(env, "dl_a")["total"] == 7


def test_download_completed_is_verified_on_disk(env, tmp_path):
    # 对抗点：「完成」不能只信上报——AI 会照着路径去读文件。路径必须是下载目录里
    # 真实存在的文件，否则按失败处理，且不给路径
    env.attach()
    _dl_wipe()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"abc")
    bad = [(str(outside), "文件不在下载目录里"),
           (os.path.join(ab._st.download_dir(), "nope.bin"), "文件不在磁盘上"),
           (ab._st.download_dir(), "文件不在下载目录里"),          # 目录本身
           ("", "文件不在下载目录里"), (None, "文件不在下载目录里"),
           (str(tmp_path), "文件不在下载目录里")]
    for i, (path, why) in enumerate(bad):
        did = "dl_v%d" % i
        _dl_report(env, did, event="started")
        _dl_report(env, did, event="done", state="completed", received=3, path=path)
        rec = _dl_row(env, did)
        assert (rec["state"], rec["error"], rec["path"]) == ("interrupted", why, None), (path, rec)
        assert env.ops()[-1]["text"].startswith("下载失败：")
    # 真在目录里：大小写 / 斜杠写法不同也算数（Windows 路径不区分这些）
    p = _dl_write("ok.bin", b"abcd")
    for i, variant in enumerate((p.upper(), p.replace("\\", "/"))):
        did = "dl_ok%d" % i
        _dl_report(env, did, event="started")
        _dl_report(env, did, event="done", state="completed", received=1, path=variant)
        rec = _dl_row(env, did)
        assert (rec["state"], rec["received"]) == ("completed", 4), (variant, rec)
        assert _real(rec["path"]) == _real(p)                   # 给 AI 的是壳报的原样路径
    # 声称的路径里夹带 ..：按规范化后的真实位置判——在目录里才算
    sneaky = os.path.join(ab._st.download_dir(), "..", "download", "ok.bin")
    _dl_report(env, "dl_dotdot", event="started")
    _dl_report(env, "dl_dotdot", event="done", state="completed", path=sneaky)
    assert _dl_row(env, "dl_dotdot")["state"] == "completed"


def test_download_report_validation(env):
    env.attach()
    assert env.post("/api/downloads/report", {"event": "started"})["ok"] is False   # 缺 id
    assert _dl_report(env, "!!!", event="started")["ok"] is False                      # 清洗后为空
    assert "event" in _dl_report(env, "dl_x", event="boom")["err"]
    assert env.post("/api/downloads/report", [1, 2])["ok"] is False                 # 不是对象
    # 后端重启过、壳还在报旧下载：没有起点记录——如实回 unknown，不凭空登记
    unknown = {"ok": True, "unknown": True}
    assert _dl_report(env, "dl_ghost", event="updated", received=1) == unknown
    assert _dl_report(env, "dl_ghost", event="done", state="completed") == unknown
    assert _dl_rows(env) == [] and env.ops() == []
    # 结束状态不认识：按失败处理并说明
    _dl_report(env, "dl_s", event="started", filename="s.bin")
    _dl_report(env, "dl_s", event="done", state="finished")
    rec = _dl_row(env, "dl_s")
    assert rec["state"] == "interrupted" and "未知的结束状态：finished" in rec["error"]
    # 字节数 / 文件名 / id 里的垃圾入参
    _dl_report(env, "dl../..\\z", event="started", filename="a\u0000b\n.bin" + "长" * 400,
               total="abc", received=-5)
    rec = _dl_row(env, "dlz")
    assert rec["total"] == 0 and rec["received"] == 0
    assert len(rec["filename"]) == 255
    for ch in ("\u0000", "\n", "\r"):
        assert ch not in rec["filename"]
    _dl_report(env, "dlz", event="updated", received=float("nan"), total=float("inf"))
    _dl_report(env, "dlz", event="done", state="cancelled", received="12")
    rec = _dl_row(env, "dlz")
    assert rec["received"] == 12 and rec["total"] == 0
    assert _dl_report(env, "dl_empty", event="started", filename="  \x07 ")["ok"]
    assert _dl_row(env, "dl_empty")["filename"] == "download"


def test_download_records_are_capped(env):
    env.attach()
    done = {"state": "completed", "received": 1, "total": 1, "path": "p", "error": None,
            "ts": 0, "source": "webtab"}
    with dl._lock:
        dl._records.clear()
        for i in range(60):
            dl._records["dl_%03d" % i] = dict(done, id="dl_%03d" % i, filename="f%d" % i)
    _dl_report(env, "dl_new", event="started", filename="new.bin")
    ids = [r["id"] for r in _dl_rows(env)]
    assert len(ids) == dl._RECORD_MAX == 50
    # 61 → 50 要淘汰 11 条：dl_000 … dl_010
    assert ids[-1] == "dl_new" and "dl_010" not in ids and "dl_011" in ids   # 淘汰最早已结束的
    with dl._lock:
        dl._records.clear()
        for i in range(50):
            dl._records["p_%03d" % i] = dict(done, id="p_%03d" % i, filename="p%d" % i,
                                               state="in_progress", path=None)
    _dl_report(env, "p_new", event="started")
    ids = [r["id"] for r in _dl_rows(env)]
    assert len(ids) == 50 and ids[-1] == "p_new"
    assert "p_000" not in ids and "p_001" in ids           # 全在进行中：只能挤掉最旧的


def test_download_done_invalidates_usage_cache(env, monkeypatch):
    from src import data_hygiene as dh
    calls = []
    monkeypatch.setattr(dh, "invalidate_usage_cache", lambda: calls.append(1))
    env.attach()
    _dl_report(env, "dl_c", event="started", filename="c.bin")
    _dl_report(env, "dl_c", event="updated", received=1)
    assert calls == []                               # 开始 / 进度不重扫：设置页下次打开自然重扫
    _dl_report(env, "dl_c", event="done", state="cancelled")
    assert calls == [1]                              # 结束后：设置页的存储占用要跟上


def test_fmt_bytes():
    f = dl._fmt_bytes
    got = [f(v) for v in (0, 1, 1023, 1024, 1536, 1048576, 1827874558, None, "abc", -5,
                          float("nan"), float("inf"))]
    assert got == ["0 B", "1 B", "1023 B", "1.00 KB", "1.50 KB", "1.00 MB", "1.70 GB",
                   "0 B", "0 B", "0 B", "0 B", "0 B"]


def test_downloads_query_text_is_latest_first(env):
    env.attach()
    _dl_wipe()
    ddir = ab._st.download_dir()
    r = env.post("/api/downloads/list", {})
    assert (r["ok"], r["dir"], r["downloads"]) == (True, ddir, [])
    assert r["text"] == "还没有下载记录。下载不弹保存窗口，文件自动存到：" + ddir
    p1 = _dl_write("one.bin")
    _dl_report(env, "dl_1", event="started", filename="one.bin")
    _dl_report(env, "dl_1", event="done", state="completed", path=p1)
    _dl_report(env, "dl_2", event="started", filename="two.bin", total=2000)
    _dl_report(env, "dl_2", event="updated", received=1000, total=2000)
    _dl_report(env, "dl_3", event="started", filename="three.bin")
    _dl_report(env, "dl_3", event="done", state="cancelled")
    _dl_report(env, "dl_4", event="started", filename="four.bin", total=4000)
    _dl_report(env, "dl_4", event="done", state="interrupted")
    assert env.post("/api/downloads/list", {})["text"].split("\n") == [
        "下载目录：" + ddir,
        "[失败] four.bin（下载被中断）",
        "[已取消] three.bin",
        "[进行中] two.bin  已收 1000 B（50%）",
        "[完成] one.bin  10 B  → " + p1,
    ]


def test_downloads_wait_blocks_until_finished_or_times_out(env, monkeypatch):
    env.attach()
    assert env.post("/api/downloads/list", {"wait": 30})["ok"]   # 没有进行中的：不等
    assert env.clock.slept == 0
    _dl_wipe()
    _dl_report(env, "dl_w", event="started", filename="w.bin")
    for wait in ({}, {"wait": "abc"}, {"wait": float("nan")}, {"wait": -3}):
        env.post("/api/downloads/list", wait)                    # 缺省 / 垃圾值 = 0：不等
    assert env.clock.slept == 0
    # 等到了：轮询期间下载结束（sleep 的副作用模拟壳报完成）
    plain_sleep = env.clock.sleep

    def _sleep_then_finish(s):
        plain_sleep(s)
        _dl_report(env, "dl_w", event="done", state="completed", path=_dl_write("w.bin"))
    monkeypatch.setattr(env.clock, "sleep", _sleep_then_finish)
    r = env.post("/api/downloads/list", {"wait": 10})
    assert 0 < env.clock.slept <= 10 and r["downloads"][-1]["state"] == "completed"
    # 等不到：夹到上限 60 秒后如实返回「还在进行中」
    monkeypatch.setattr(env.clock, "sleep", plain_sleep)
    _dl_report(env, "dl_w2", event="started", filename="w2.bin")
    env.clock.slept = 0
    r = env.post("/api/downloads/list", {"wait": 999})
    assert abs(env.clock.slept - 60.0) < 1e-6
    assert r["downloads"][-1]["state"] == "in_progress"
    env.clock.slept = 0
    env.post("/api/downloads/list", {"wait": 0.5})
    assert abs(env.clock.slept - 0.6) < 1e-6      # 0.2 秒一步：第三步越过 0.5


def _fake_trash(monkeypatch, where):
    """回收站替身：真调系统回收站会往用户的回收站里塞测试文件。替身把文件挪进一个
    临时目录并记下调用——要验证的是「走的是回收站这条路、失败就不删」。
    返回 (记录到的调用, 切换失败的开关)。"""
    from src import data_hygiene as dh
    where.mkdir(parents=True, exist_ok=True)
    calls, switch = [], [False]

    def recycle(p):
        calls.append(os.path.basename(p))
        if switch[0]:
            return False                          # 模拟回收站不可用 / 操作失败
        shutil.move(p, str(where / os.path.basename(p)))
        return True
    monkeypatch.setattr(dh, "_dl_recycle", recycle)
    return calls, switch


def test_downloads_are_deleted_only_from_the_settings_cleanup(env, tmp_path, monkeypatch):
    # 2026-11-24 用户令：下载的删除入口统一在 设置→数据目录→「可清理项」，且**只在
    # 这里**删。与串口日志同款：按策略不删、后台不删、AI 不删；只认用户的手动点击。
    # 删法是移入回收站（下载的是用户的文件，删错能找回）
    from src import data_hygiene as dh
    trash = tmp_path / "trash"
    calls, fail = _fake_trash(monkeypatch, trash)
    ddir = _dl_wipe()
    old = _dl_write("old.bin", b"o" * 1000)
    new = _dl_write("new.bin", b"n" * 300)
    going = os.path.join(ddir, "going.bin.crdownload")       # 进行中的下载
    with open(going, "wb") as f:
        f.write(b"g" * 5000)
    sub = os.path.join(ddir, "我的资料")                       # 用户自己建的子文件夹
    os.mkdir(sub)
    keep = os.path.join(sub, "keep.txt")
    with open(keep, "wb") as f:
        f.write(b"k" * 200)
    forty_days_ago = time.time() - 40 * 86400
    os.utime(old, (forty_days_ago, forty_days_ago))

    # 占用：口径 = 能删的（与清理共用 _download_files）——不含进行中的下载与子文件夹
    data = dh.usage_stats(force=True)
    t = data["targets"]["downloads"]
    assert "downloads" not in data                              # 旧的「只显示」独立行已撤
    assert (t["path"], t["bytes"], t["name"]) == (ddir, 1300, "下载文件")
    assert t["age_options"] == [7, 30, 90] and t["by_age"] == {"7": 1000, "30": 1000, "90": 0}
    assert t["trash"] is True and dh._dl_recyclable(ddir)      # 测试目录在本地硬盘上：删除可进回收站
    assert list(data["targets"])[0] == "downloads"              # 排在可清理项第一位
    assert "downloads" in dh._CLEANABLE

    # 按策略：不删任何东西（工具不替用户判断）
    assert dh.manual_clean("downloads", "policy") == (0, 0)
    assert os.path.isfile(old) and os.path.isfile(new) and calls == []
    # 按天数：只删超过 N 天的；天数只认白名单，否则抛错——不「假成功 0 项」
    assert dh.manual_clean("downloads", "older", days=30) == (1, 1000)
    assert calls == ["old.bin"]                                 # 走的是回收站这条路
    assert not os.path.exists(old) and (trash / "old.bin").read_bytes() == b"o" * 1000
    assert os.path.isfile(new)
    for bad in (0, 1, 31, "30", None):
        with pytest.raises(ValueError):
            dh.manual_clean("downloads", "older", days=bad)
    assert os.path.isfile(new) and len(calls) == 1              # 被拒的请求没删东西
    # 回收站不可用 / 操作失败：不删，也不计入成绩——绝不退回永久删除
    fail[0] = True
    assert dh.manual_clean("downloads", "all") == (0, 0)
    assert os.path.isfile(new) and os.path.isfile(keep) and os.path.isfile(going)
    fail[0] = False
    # 全部清空：只删下载目录第一层的普通文件；进行中的下载、子文件夹、目录本身都留着
    assert dh.manual_clean("downloads", "all") == (1, 300)
    assert sorted(os.listdir(ddir)) == ["going.bin.crdownload", "我的资料"]
    assert os.path.getsize(going) == 5000 and os.path.isfile(keep)
    assert sorted(p.name for p in trash.iterdir()) == ["new.bin", "old.bin"]
    # 目标名字写错一律拒绝：不删东西，也不报成功
    assert dh.manual_clean("download", "all") == (0, 0)
    assert dh.manual_clean("download_dir", "all") == (0, 0)
    assert os.path.isfile(keep) and os.path.isfile(going)
    # 清理之后占用缓存已失效：下一次统计是重扫的
    assert dh._usage_cache["ts"] == 0.0 and dh._dir_total_cache["ts"] == 0.0


def test_dl_recyclable_tells_the_truth_about_the_location(monkeypatch):
    # 只有本地固定硬盘才有回收站；网络位置 / U 盘上删了就是删了——界面据此如实警告
    import ctypes
    if not hasattr(ctypes, "windll"):
        pytest.skip("非 Windows：盘类型判断只在 Windows 上有意义")
    k32 = ctypes.windll.kernel32
    from src import data_hygiene as dh
    rec = dh._dl_recyclable
    assert rec(None) is False and rec("") is False
    assert rec(r"\\nas\share\download") is False               # UNC 路径
    monkeypatch.setattr(k32, "GetDriveTypeW", lambda root: 3)
    assert rec(r"D:\x\download") is True                       # DRIVE_FIXED
    for kind in (0, 1, 2, 4, 5, 6):                            # 未知 / 无根目录 / 可移动 / 网络 / 光盘 / RAM 盘
        monkeypatch.setattr(k32, "GetDriveTypeW", lambda root, k=kind: k)
        assert rec(r"D:\x\download") is False, kind

    def boom(root):
        raise OSError("判不出来")
    monkeypatch.setattr(k32, "GetDriveTypeW", boom)
    assert rec(r"D:\x\download") is False                      # 判不出来按「不能」说，不夸大


def test_dl_recycle_never_falls_back_to_permanent_delete(monkeypatch):
    # 真实的回收站调用沿用文件树删除的实现；这里只钉「失败就不删、不退回 os.remove」
    import types
    from src import data_hygiene as dh
    for answer, want in (((False, "系统回收站操作失败"), False), ((True, ""), True),
                         (OSError("boom"), False)):
        def _trash(p, a=answer):
            if isinstance(a, Exception):
                raise a
            return a
        monkeypatch.setitem(sys.modules, "src.file_tree",
                            types.SimpleNamespace(_recycle_to_trash=_trash))
        assert dh._dl_recycle(r"D:\ nowhere\a.bin") is want


def test_clean_route_accepts_downloads_only_with_whitelisted_days(env, tmp_path, monkeypatch):
    # 接口层同样只认 downloads + 7/30/90；别的目标仍不支持按天数
    import src.server as S
    _fake_trash(monkeypatch, tmp_path / "trash")              # 不往用户的回收站里放测试文件
    _dl_wipe()                                               # 别的用例留下的文件不算在这条里
    a = _dl_write("a.bin", b"a" * 10)
    c = S.app.test_client()

    def post(body):
        rv = c.post("/api/data_dir/clean", json=body)
        return rv.status_code, rv.get_json()

    assert post({"target": "downloads", "mode": "older", "days": 0})[0] == 400     # 0 天=绕过确认的全清
    assert post({"target": "downloads", "mode": "older", "days": "abc"})[0] == 400
    assert post({"target": "downloads", "mode": "older"})[0] == 400
    assert post({"target": "idx", "mode": "older", "days": 7})[0] == 400
    assert post({"target": "download", "mode": "all"})[0] == 400                    # 名字写错
    assert post({"target": "downloads", "mode": "wipe"})[0] == 400
    assert os.path.isfile(a)                                                         # 被拒的请求都没删东西
    assert post({"target": "downloads", "mode": "policy"}) == (200, {"ok": True, "removed": 0, "freed": 0})
    assert os.path.isfile(a)
    code, body = post({"target": "downloads", "mode": "older", "days": 7})
    assert code == 200 and body["ok"] is True and body["removed"] == 0               # 刚下载的，不够 7 天
    assert os.path.isfile(a)
    assert post({"target": "downloads", "mode": "all"}) == (200, {"ok": True, "removed": 1, "freed": 10})
    assert not os.path.exists(a)


_DL_DELETERS = {"os.remove", "os.unlink", "_try_rm", "shutil.rmtree",
                "remove", "unlink", "rmtree",
                # 「移入回收站」也是删除——守卫必须认得它
                "_dl_recycle", "_recycle_to_trash", "SHFileOperationW"}


def _calls_in(node):
    """函数体内所有被调用的函数名（点路径名 + 裸名）。"""
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f, parts = n.func, []
            while isinstance(f, ast.Attribute):
                parts.append(f.attr)
                f = f.value
            if isinstance(f, ast.Name):
                parts.append(f.id)
            if parts:
                names.add(".".join(reversed(parts)))
                names.add(parts[0])
    return names


def _branch_calls(fn_node, target_name):
    """manual_clean 里 `if/elif target == "<target_name>":` 那个分支（含嵌套）调用的函数名。"""
    for n in ast.walk(fn_node):
        if not isinstance(n, ast.If) or not isinstance(n.test, ast.Compare):
            continue
        left, ops, right = n.test.left, n.test.ops, n.test.comparators
        if (isinstance(left, ast.Name) and left.id == "target" and len(ops) == 1
                and isinstance(ops[0], ast.Eq) and len(right) == 1
                and isinstance(right[0], ast.Constant) and right[0].value == target_name):
            return _calls_in(n)
    return None


def test_no_code_deletes_downloads_outside_manual_clean():
    """静态守卫（2026-11-24 用户令：下载**只在**设置→数据目录→可清理项里删）：
    除 data_hygiene.manual_clean 外，src 下任何函数都不得「涉及下载目录且调用删除」。
    「涉及」取宽——调了 download_dir / _download_files，或函数里的字符串提到
    download：宁可多拦，新增一条删除路径时必须先过这一关。
    （照搬串口日志「后台永不删除」的守卫写法。）"""
    offenders = []
    for r, _ds, fs in os.walk(os.path.join(ROOT, "src")):
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(r, f)
            with open(p, encoding="utf-8-sig", errors="replace") as fh:
                try:
                    tree = ast.parse(fh.read(), p)
                except SyntaxError:
                    continue
            mod = os.path.splitext(os.path.basename(p))[0]
            for n in ast.walk(tree):
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                strings = [s.value for s in ast.walk(n)
                           if isinstance(s, ast.Constant) and isinstance(s.value, str)]
                touches = bool(_calls_in(n) & {"download_dir", "_download_files"}) \
                    or any("download" in s for s in strings)
                if not touches or not (_calls_in(n) & _DL_DELETERS):
                    continue
                if (mod, n.name) == ("data_hygiene", "manual_clean"):
                    continue
                offenders.append("%s:%d %s()" % (os.path.relpath(p, ROOT), n.lineno, n.name))
    assert not offenders, "这些函数会删下载的文件，却不在唯一的手动清理入口里：\n" + "\n".join(offenders)
    # 守卫自检：白名单里那个函数确实是「涉及下载且会删」的——否则上面的扫描是空转
    hygiene = ast.parse(_read("src", "data_hygiene.py"))
    mc = next(n for n in hygiene.body if isinstance(n, ast.FunctionDef) and n.name == "manual_clean")
    assert _calls_in(mc) & {"_download_files", "_try_rm"} == {"_download_files", "_try_rm"}
    # 下载那个分支只能走回收站（_dl_recycle），不许用直接删除（_try_rm）：下载的是
    # 用户的文件，删错要能找回；回收站失败就不删，不退回永久删除
    dl_branch = _branch_calls(mc, "downloads")
    assert dl_branch is not None and "_dl_recycle" in dl_branch and not (dl_branch & {"_try_rm", "os.remove"}), \
        sorted(dl_branch or [])
    assert _branch_calls(mc, "logs") & {"_try_rm"}            # 自检：取分支的函数确实取到了东西


def test_mcp_downloads_wait_is_clamped_and_zero_is_sent(monkeypatch):
    posted = []
    monkeypatch.setattr(mcp, "_post", lambda url, path, body, timeout=30: posted.append(
        (body, timeout)) or {"ok": True, "text": "T"})
    u = "http://backend"
    for arg, want, http in ((None, 0.0, 100), (0, 0.0, 100), ("12", 12.0, 100), (5, 5.0, 100),
                            (60, 60.0, 120), (999, 60.0, 120), (30000, 60.0, 120),
                            ("abc", 0.0, 100), (float("nan"), 0.0, 100), (-3, 0.0, 100)):
        mcp.tool_browser_downloads(u, {} if arg is None else {"wait": arg})
        assert posted[-1] == ({"wait": want}, http), (arg, posted[-1])


def test_shell_download_helpers_run_in_node():
    """壳的两个纯函数用 Node 真执行（字面量只能证明「写成了这样」）：文件名清洗与
    同名不覆盖。函数体从磁盘上的 electron/main.js 原样取出，不手抄。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node：壳的下载辅助函数的执行验证跳过（字面量断言已覆盖）")
    sh = _read("electron", "main.js")
    cases = ["资源包.fcpk", "..\\..\\evil.exe", 'a/b:c*d?e"f<g>h|i', "...", "  ", "", None,
             "file.  ", ".gitignore", "CON.txt", "nul", "com1.bin", "console.txt",
             "x" * 300 + ".bin", "a\u0000b\u001f.bin"]
    js = "\n".join([
        "const path = require('path');",
        "var existing = " + json.dumps([r"D:\dl\a.bin", r"D:\dl\a (1).bin"]) + ";",
        "var reserved = " + json.dumps([r"D:\dl\a (2).bin"]) + ";",
        "const fs = { existsSync: function (p) { return existing.indexOf(p) >= 0; } };",
        "const aibrDlReserved = new Set(reserved);",
        "const AIBR_WIN_RESERVED = "
        + re.search(r"const AIBR_WIN_RESERVED = (.*?);\n", sh).group(1) + ";",
        _function_body(sh, "function aibrSafeName(name) {"),
        _function_body(sh, "function aibrDlPath(dir, name) {"),
        "var names = " + json.dumps(cases) + ".map(function (c) { return aibrSafeName(c); });",
        "var dir = " + json.dumps(r"D:\dl") + ";",
        "var paths = ['a.bin', 'README', 'b.bin'].map(function (n) {",
        "  return path.basename(aibrDlPath(dir, n)); });",
        "process.stdout.write(JSON.stringify({ names: names, paths: paths }));",
    ])
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8",
                       input="", timeout=20)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # 清洗：去路径分隔符与非法字符、去尾随的点/空格、空名兜底、避开保留设备名；
    # 以点开头的正常文件名（.gitignore）保留——只挡 "." / ".."
    assert out["names"] == ["资源包.fcpk", ".._.._evil.exe", "a_b_c_d_e_f_g_h_i", "download",
                            "download", "download", "download", "file", ".gitignore", "_CON.txt",
                            "_nul", "_com1.bin", "console.txt", "x" * 180, "a_b_.bin"], out["names"]
    for name in out["names"]:
        assert name not in (".", "..") and "/" not in name and "\\" not in name
    # 同名不覆盖：已有的 a.bin、a (1).bin 与另一个进行中下载占着的 a (2).bin 都跳过
    assert out["paths"] == ["a (3).bin", "README", "b.bin"], out["paths"]


# ---------- 13. 下载中心：目录配置 / 打开 / 来源（2026-11-24 用户令）----------

def test_custom_download_dir_redirects_downloads_and_is_never_cleaned(env, monkeypatch, tmp_path):
    # 用户令：下载目录默认跟随数据目录，可手动另行指定。手动指定的目录工具只往里
    # 存、不提供清理——那里面可能有用户自己的文件
    from src import data_hygiene as dh
    _dl_wipe()
    custom = os.path.join(os.environ["FC_STATE_DIR"], "my-downloads")     # 仍在沙箱里
    r = env.post("/api/downloads/config", {"dir": custom})
    assert (r["ok"], r["custom"], r["usable"]) == (True, True, True) and _real(r["dir"]) == _real(custom)
    assert os.path.isdir(custom) and env.config["download_dir"] == custom
    assert _real(env.get("/api/downloads/config")["dir"]) == _real(custom)    # 壳看到的就是它
    # 新下载落到这里
    _dl_report(env, "dl_c1", event="started")
    p = os.path.join(custom, "c1.bin")
    with open(p, "wb") as f:
        f.write(b"c" * 77)
    _dl_report(env, "dl_c1", event="done", state="completed", path=p)
    assert _dl_row(env, "dl_c1")["state"] == "completed"
    assert _real(_dl_row(env, "dl_c1")["path"]) == _real(p)
    assert _real(env.post("/api/downloads/list", {})["dir"]) == _real(custom)
    # 落在旧默认目录里的文件不再算「下载」：声称完成也不给路径
    old_default = ab._st.download_default_dir()
    os.makedirs(old_default, exist_ok=True)
    old_file = os.path.join(old_default, "old.bin")
    with open(old_file, "wb") as f:
        f.write(b"o")
    _dl_report(env, "dl_o", event="started")
    _dl_report(env, "dl_o", event="done", state="completed", path=old_file)
    assert _dl_row(env, "dl_o")["state"] == "interrupted"
    # 可清理项里没有它；清理入口的三个挡位也都不认
    calls, _fail = _fake_trash(monkeypatch, tmp_path / "trash")
    data = dh.usage_stats(force=True)
    assert "downloads" not in data["targets"]
    assert data["download_dir"]["custom"] is True and _real(data["download_dir"]["path"]) == _real(custom)
    assert data["download_dir"]["bytes"] == 77
    for mode, days in (("all", None), ("policy", None), ("older", 7)):
        assert dh.manual_clean("downloads", mode, days=days) == (0, 0)
    assert calls == [] and os.path.isfile(p) and os.path.isfile(old_file)
    # 恢复默认：空串 = 跟随数据目录；清理入口随之回来
    r = env.post("/api/downloads/config", {"dir": ""})
    assert (r["ok"], r["custom"]) == (True, False) and env.config["download_dir"] == ""
    assert _real(r["dir"]) == _real(old_default) and ab._st.download_dir_is_default()
    assert "downloads" in dh.usage_stats(force=True)["targets"]


def test_custom_download_dir_is_validated(env, tmp_path):
    # 校验不过就回绝，且不动现有配置——危险的位置一个都不许当场建目录
    assert "download_dir" not in env.config
    for bad, why in (("downloads", "完整路径"), ("~\\downloads", "完整路径"),
                     ("relative\\path", "完整路径"),
                     (ab._st.DATA_DIR, "数据目录本身"), (ab._st.APP_DIR, "工具目录本身"),
                     (ab._st.HOME_DIR, "锚点目录本身"),
                     (os.path.expanduser("~"), "用户主目录本身"),
                     (os.environ.get("SystemRoot") or r"C:\Windows", "系统目录")):
        r = env.post("/api/downloads/config", {"dir": bad})
        assert r["ok"] is False and why in r["err"], (bad, r)
        assert "download_dir" not in env.config, bad
    assert "磁盘根" in env.post("/api/downloads/config", {"dir": os.path.abspath(os.sep)})["err"]
    a_file = tmp_path / "afile"
    a_file.write_text("x")
    r = env.post("/api/downloads/config", {"dir": str(a_file)})
    assert r["ok"] is False and "用不了" in r["err"] and a_file.read_text() == "x"
    assert env.status("/api/downloads/config", [1]) == 400             # 不是对象
    assert env.post("/api/downloads/config", {})["custom"] is False    # 没给 dir = 恢复默认
    # 通过的：绝对路径、建得出来、写得进——探针文件用完即删
    want = tmp_path / "新目录" / "下载"
    r = env.post("/api/downloads/config", {"dir": str(want)})
    assert r["ok"] is True and want.is_dir() and os.listdir(want) == []


def test_open_only_touches_the_download_dir(env, monkeypatch):
    ddir = _dl_wipe()
    a = _dl_write("a.bin")
    sub = os.path.join(ddir, "sub")
    os.mkdir(sub)
    deep = os.path.join(sub, "deep.bin")
    with open(deep, "wb") as f:
        f.write(b"d")
    calls = []
    monkeypatch.setattr(dl.os, "startfile", lambda p: calls.append(("startfile", p)))
    monkeypatch.setattr(dl.subprocess, "Popen", lambda cmd, **kw: calls.append(("popen", cmd)))
    # 目录本身 / 文件 / 在资源管理器里定位文件
    assert env.post("/api/downloads/open", {"path": ddir})["ok"] is True
    assert env.post("/api/downloads/open", {"path": a})["ok"] is True
    assert env.post("/api/downloads/open", {"path": a, "reveal": True})["ok"] is True
    assert [c[0] for c in calls] == ["popen", "startfile", "popen"]
    assert calls[1][1] == _real(a)
    assert "/select," in calls[2][1] and calls[2][1].endswith('"')   # /select, 与路径之间没有空格
    # 越界 / 下一层 / 不存在的：一律拒绝，什么也不打开
    n = len(calls)
    for path, code, why in ((os.path.join(ddir, "..", "x.bin"), 403, "下载目录里"),
                            (deep, 403, "下载目录里"), (ab._st.DATA_DIR, 403, "下载目录里"),
                            (os.path.join(ddir, "nope.bin"), 404, "不在磁盘上"),
                            ("", 400, "缺少路径"), (None, 400, "缺少路径")):
        rv = env.post("/api/downloads/open", {"path": path})
        assert rv["ok"] is False and why in rv["err"], (path, rv)
        assert env.status("/api/downloads/open", {"path": path}) == code
    assert len(calls) == n


def test_forget_only_removes_finished_records_and_never_files(env):
    keep = _dl_write("keep.bin")
    _dl_report(env, "dl_f1", event="started")
    _dl_report(env, "dl_f2", event="started")
    _dl_report(env, "dl_f2", event="done", state="cancelled")
    assert env.post("/api/downloads/forget", {"id": "dl_f2"})["ok"] is True
    assert [r["id"] for r in _dl_rows(env)] == ["dl_f1"]
    assert env.post("/api/downloads/forget", {"id": "dl_f1"})["ok"] is True
    assert [r["id"] for r in _dl_rows(env)] == ["dl_f1"]            # 进行中的不许移除
    assert env.post("/api/downloads/forget", {"all": True})["ok"] is True
    assert [r["id"] for r in _dl_rows(env)] == ["dl_f1"]
    assert os.path.isfile(keep)                                      # 只动记录，不动文件


def test_webtab_downloads_show_in_the_panel_but_never_on_the_ai_status_bar(env):
    # 普通网页标签页的下载（source=webtab）：进下载面板（SSE kind=download，每个阶段
    # 都推），不进 AI 浏览器的状态条——那条帧的开头会 open()，等于把分屏给展开
    _dl_wipe()
    _dl_report(env, "dl_w", event="started", source="webtab", filename="w.bin")
    _dl_report(env, "dl_w", event="updated", source="webtab", received=5, total=10)
    _dl_report(env, "dl_w", event="done", source="webtab", state="completed", path=_dl_write("w.bin"))
    frames = [i for _t, i in env.sent if i.get("kind") == "download"]
    assert [(f["event"], f["state"], f["source"]) for f in frames] == [
        ("started", "in_progress", "webtab"), ("updated", "in_progress", "webtab"),
        ("done", "completed", "webtab")]
    assert all(f["id"] == "dl_w" and f["filename"] == "w.bin" for f in frames)
    assert env.ops() == []                               # 一帧 ai_browser_op 都没有
    assert _dl_row(env, "dl_w")["source"] == "webtab"
    # AI 浏览器里的下载：开始与结束进状态条，进度帧不进（只给面板）
    env.sent.clear()
    _dl_report(env, "dl_a", event="started")
    _dl_report(env, "dl_a", event="updated", received=1)
    _dl_report(env, "dl_a", event="done", state="cancelled")
    assert [i["text"] for i in env.ops()] == ["开始下载：dl_a.bin", "下载已取消：dl_a.bin"]
    assert [i["event"] for _t, i in env.sent if i.get("kind") == "download"] == ["started", "updated", "done"]
    # 订阅者抛异常不连累登记
    def boom(rec, ev):
        raise RuntimeError("boom")
    dl.subscribe(boom)
    try:
        assert _dl_report(env, "dl_b", event="started")["ok"] is True
        assert _dl_row(env, "dl_b")["state"] == "in_progress"
    finally:
        dl._hooks.remove(boom)
    # 不认识的来源按普通网页处理（绝不算成 AI 浏览器）
    env.sent.clear()
    _dl_report(env, "dl_x", event="started", source="whatever")
    assert _dl_row(env, "dl_x")["source"] == "webtab" and env.ops() == []


def test_shell_takeover_reports_progress_whatever_the_event_state_word_is():
    """壳的下载接管（dlTakeOver）用 Node 真执行——函数体从磁盘上的 electron/main.js 原样取出。
    2026-11-24 实跑踩到的 bug：Electron 的 updated 事件带的 state 是 'progressing'，不是
    文档写的 'in_progress'；按后者过滤会把所有进度帧吃掉，面板上的进度条从头到尾是 0，
    直到结束才跳满（此前的单测是直接往接口灌进度，绕过了壳这段，所以一直没发现）。
    只有真执行、并且用 Electron 实测的那个词去触发，才钉得住这类 bug。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("没有 node：壳的下载接管的执行验证跳过（字面量断言已覆盖）")
    sh = _read("electron", "main.js")
    js = "\n".join([
        "const path = require('path');",
        "let dlDir = 'D:\\\\dl', dlSeq = 0, now = 100000;",
        "const dlItems = new Map(), aibrDlReserved = new Set(), posted = [], fetches = [0];",
        "const fs = { existsSync: function () { return false; } };",
        "const log = function (m) {};",
        "const DL_UPDATE_MS = " + re.search(r"const DL_UPDATE_MS = (\d+);", sh).group(1) + ";",
        "const AIBR_WIN_RESERVED = "
        + re.search(r"const AIBR_WIN_RESERVED = (.*?);\n", sh).group(1) + ";",
        "const aibrPost = function (p, body) { posted.push(JSON.parse(JSON.stringify(body)));",
        "  return Promise.resolve({ ok: true }); };",
        "const dlFetchDir = function () { fetches[0]++; return Promise.resolve(dlDir); };",
        "Date.now = function () { return now; };",
        _function_body(sh, "function aibrSafeName(name) {"),
        _function_body(sh, "function aibrDlPath(dir, name) {"),
        _function_body(sh, "function dlTakeOver(item, source) {"),
        # 假的 DownloadItem：事件按 Electron 45 实测的参数触发（updated 的 state 是 'progressing'）
        "function mkItem(name, total) {",
        "  var h = {}, received = 0;",
        "  return {",
        "    savePath: null,",
        "    setSavePath: function (p) { this.savePath = p; },",
        "    getFilename: function () { return name; },",
        "    getTotalBytes: function () { return total; },",
        "    getReceivedBytes: function () { return received; },",
        "    getURL: function () { return 'https://example.com/' + name; },",
        "    on: function (ev, fn) { (h[ev] = h[ev] || []).push(fn); },",
        "    receive: function (n) { received += n; h.updated.forEach(function (f) { f({}, 'progressing'); }); },",
        "    finish: function (st) { h.done.forEach(function (f) { f({}, st); }); }",
        "  };",
        "}",
        "var out = {};",
        # ① 下载中心没给出可用目录：不接管、不上报（退回 Electron 默认的弹保存框）
        "dlDir = null; var it0 = mkItem('a.bin', 10); dlTakeOver(it0, 'webtab');",
        "out.noDir = { savePath: it0.savePath, posted: posted.length };",
        # ② 正常接管：开始 → 进度 → 完成
        "dlDir = 'D:\\\\dl'; var it = mkItem('video.mp4', 1000); dlTakeOver(it, 'webtab');",
        "it.receive(300);                       // 第 1 块：立刻上报",
        "var afterFirst = posted.length;",
        "it.receive(100);                       // 距上次上报不足节流窗口：不上报",
        "out.throttled = posted.length - afterFirst;",
        "now += DL_UPDATE_MS; it.receive(100);  // 过了窗口：上报",
        "out.progress = posted.filter(function (p) { return p.event === 'updated'; })",
        "  .map(function (p) { return p.received; });",
        "var beforeDone = posted.length;",
        "it.finish('completed');",
        "it.receive(50);                        // 结束之后又来的进度：不认",
        "out.afterDone = posted.slice(beforeDone).map(function (p) { return p.event + ':' + p.state; });",
        "out.savePath = path.basename(it.savePath);",
        "out.stillRunning = dlItems.has(it0.savePath === null ? '' : posted[posted.length - 1].id);",
        "out.fetches = fetches[0];",
        "var starts = posted.filter(function (p) { return p.event === 'started'; });",
        "var dones = posted.filter(function (p) { return p.event === 'done'; });",
        "out.started = starts[0];",
        "out.done = dones[0];",
        # ③ 取消：done 的 state 原样上报；来源标记跟着分区走
        "var it2 = mkItem('b.bin', 50); dlTakeOver(it2, 'ai_browser'); it2.receive(20); it2.finish('cancelled');",
        "out.cancelled = posted.filter(function (p) { return p.event === 'done'; })[1].state;",
        "out.sources = posted.filter(function (p) { return p.event === 'started'; })",
        "  .map(function (p) { return p.source; });",
        "process.stdout.write(JSON.stringify(out));",
    ])
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8",
                       input="", timeout=20)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["noDir"] == {"savePath": None, "posted": 0}
    assert out["progress"] == [300, 500] and out["throttled"] == 0, out   # 进度帧按 'progressing' 也上报；节流生效
    assert out["afterDone"] == ["done:completed"] and out["stillRunning"] is False
    assert out["savePath"] == "video.mp4" and out["fetches"] >= 1         # 结束后顺手重取目录
    assert out["started"]["total"] == 1000 and out["started"]["filename"] == "video.mp4"
    assert out["done"]["path"].endswith("video.mp4")
    assert (out["done"]["received"], out["done"]["total"], out["done"]["state"]) == (500, 1000, "completed")
    assert out["cancelled"] == "cancelled" and out["sources"] == ["webtab", "ai_browser"]
