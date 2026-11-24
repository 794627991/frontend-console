# -*- coding: utf-8 -*-
r"""AI 浏览器（Flask Blueprint 路由 /api/ai_browser/*）——AI 用 CDP 操作网页时，
页面显示在 harness 会话右侧分屏里，用户看着 AI 操作。

背景（2026-11-24 用户需求）：此前 AI 用 CDP 的唯一入口是 mcp_server 的
devtools_* 五件套，而它们一律先找「工具自己的主页面」——AI 实际操作的是
前端控制台界面本身，用户看不到「AI 在控制网页」。本模块给 AI 一个**可见
的、内嵌的受控浏览器**（参考 ZCode 的 Browser Use：内嵌 <webview> + 右侧
分屏；用户拍板四项：会话右侧分屏 / devtools_* 默认目标改为 AI 浏览器、
显式 target=app 才操作工具界面 / 光标+点击涟漪+状态条 / 自动展开且收起后
仍可后台运行和截图）。

链路：
  1. AI 调 browser_*（或 devtools_* 默认目标）→ MCP 进程 HTTP 打到本模块；
  2. 视图未就绪 → _broadcast_to_ai(ui_action: ai_browser_open) 让前端展开
     分屏、建 <webview>（partition=persist:fc-ai-browser）；
  3. 前端 dom-ready 后经壳 IPC 交出 webContentsId；壳用
     webContents.debugger 取该 guest 的 CDP targetId，POST /attach 登记。
     **精确映射**：9222 的 /json/list 里多个 webview 只凭「取第一个」有
     歧义（find_webtab_target 的老问题）；映射法实测一一对应；
  4. 本模块按 targetId 直连（复用 devtools_cdp.CdpSession：无状态用完即弃）
     发 Page.navigate / Input.dispatch* / Runtime.evaluate /
     Page.captureScreenshot——鼠标键盘全是真实事件，页面上看得见；
  5. 每次操作再推一条 ui_action: ai_browser_op，前端画光标/涟漪/状态条。

实测约束（Electron 45.4.1，隔离实验）：
  - 取 guest 的 webContentsId 必须等 dom-ready（did-attach 里取会抛错）；
  - 面板 display:none 时 Page.captureScreenshot 挂死不返回——前端收起用
    「近乎透明」的后台态（opacity .001，ZCode 同款手法），不隐藏；
  - targetId 在同一 guest 的多次导航间不变；guest 销毁重建才换；
  - 页面刚加载完的瞬间发鼠标事件偶发迟迟不 ack——点击前先让前端把光标
    移过去（顺带成了「看得见移过去再点」的效果），再发事件；
  - **别用 CDP Page 域的导航类命令**（Page.reload / Page.navigateToHistoryEntry）：
    guest 的框架挂在宿主页面的框架树上，端到端实测 Page.reload 把宿主页面
    （整个前端控制台界面）一起重载。后退/前进/重载一律在网页内部用
    history.back()/forward()/location.reload()。
"""
import base64
import functools
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict, deque

from flask import Blueprint, jsonify, request

from src import app_state as _st
from src import devtools_cdp as _cdp
from src import downloads as _downloads      # 下载中心（AI 浏览器与网页标签页共用）
from src.app_state import _broadcast_to_ai
from src.devtools_cdp import CdpError, DevtoolsError

log = logging.getLogger(__name__)

ai_browser_bp = Blueprint("ai_browser", __name__)

# 前端 <webview partition>、壳 will-attach-webview 的判据、本模块——三处对齐
PARTITION = "persist:fc-ai-browser"
ATTACH_TIMEOUT = 12.0        # 等前端展开 + 建视图 + 壳上报的最长时间（秒）
_LISTEN_MAX = 200            # console / network 环形缓冲上限
_SLOW_LOAD = 20.0            # navigate 等 loadEventFired 的上限（秒）

_lock = threading.RLock()
_state = {"target_id": None, "wc_id": None, "ts": 0.0, "gen": 0}    # None = 视图未就绪
_op_lock = threading.Lock()   # 操作串行化：输入事件交错会互抢焦点


class AiBrowserError(Exception):
    """message 即给 AI 看的中文文案。"""


def _enabled():
    """总开关（config.json ai_browser_enabled，缺省开；设置面板可关）。"""
    try:
        return bool(_st._load_config().get("ai_browser_enabled", True))
    except Exception:
        return True


def _ui(action, **kw):
    """推一条 ui_action 给前端（/api/ai/stream，sense.js 分发）。"""
    d = {"kind": "ui_action", "action": action}
    d.update(kw)
    try:
        _broadcast_to_ai(d)
    except Exception:
        pass


def _target_alive(tid, port=None):
    """登记的 targetId 是否还在壳的 target 列表里（壳重启/guest 崩溃会过期）。"""
    try:
        port = port or _cdp.find_cdp()
        return any(t.get("id") == tid for t in _cdp.list_targets(port))
    except DevtoolsError:
        return False


def _ensure_target(timeout=None):
    """返回就绪的 targetId；未就绪则让前端展开并等壳上报。抛 AiBrowserError。"""
    timeout = ATTACH_TIMEOUT if timeout is None else timeout
    if not _enabled():
        raise AiBrowserError("AI 浏览器已在设置里关闭（要操作工具自身界面请传 target=app）")
    try:
        port = _cdp.find_cdp()
    except DevtoolsError as e:
        # CDP 端口本身不通：等前端也没用，直接报（否则每次操作都空等满超时）
        raise AiBrowserError(str(e))
    with _lock:
        tid = _state["target_id"]
    if tid and _target_alive(tid, port):
        return tid
    with _lock:
        _state["target_id"] = None
    _ui("ai_browser_open")
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _lock:
            tid = _state["target_id"]
        if tid:
            _wait_listen()     # 等监听线程接上这个视图（没接上就导航，早期事件会漏）
            return tid
        time.sleep(0.15)
    raise AiBrowserError("AI 浏览器视图没有及时就绪（等了 %ds）——工具窗口可能"
                         "没开着 harness 页；稍后重试" % int(timeout))


_OP_QUEUE_WAIT = 20.0      # 等前一个操作让出锁的上限（秒）；超了快速失败，不让调用方干等


def _op(fn):
    """操作端点统一包装：解析 JSON → 排队（有上限）→ 开关/就绪检查 → 串行 →
    异常转 {ok:False}。"""
    @functools.wraps(fn)
    def wrap(*a, **kw):
        d = request.get_json(force=True, silent=True)
        if not isinstance(d, dict):
            d = {}
        # 等锁有上限：调用方（MCP 进程）的 HTTP 超时是有限的，等太久会变成
        # 「调用方先放弃报失败、后端这边拿到锁后照做」。宁可快速失败让 AI 稍后重试
        if not _op_lock.acquire(timeout=_OP_QUEUE_WAIT):
            return jsonify({"ok": False,
                            "err": "前一个浏览器操作还没结束（已等 %d 秒）——稍后重试"
                                   % int(_OP_QUEUE_WAIT)})
        try:
            try:
                tid = _ensure_target()
                with _cdp.CdpSession(_cdp.find_cdp(), tid) as cs:
                    r = fn(cs, d)
                return jsonify(dict({"ok": True}, **(r or {})))
            except (AiBrowserError, DevtoolsError) as e:
                return jsonify({"ok": False, "err": str(e)})
            except ValueError as e:
                return jsonify({"ok": False, "err": "参数错误：%s" % e})
            except Exception as e:
                log.warning("ai_browser %s 失败: %r", fn.__name__, e)
                return jsonify({"ok": False, "err": "AI 浏览器操作失败：%r" % e})
        finally:
            _op_lock.release()
    return wrap


# ---- CDP 输入（真实鼠标键盘事件）----

_VIS_ERR = ("前端控制台窗口当前不可见（最小化，或被其他窗口完全遮挡）——网页此时"
            "不响应鼠标 / 键盘，也截不了图。请让工具窗口保持可见后再试"
            "（读页面内容的 eval / dom / console / network 不受影响）")


def _check_visible(cs):
    """窗口不可见时 Chromium 不派发输入事件、不出帧：鼠标 / 键盘 / 截图都会
    挂到超时（端到端实锤：窗口被遮挡时点击等满 10 秒才报「页面无响应」）。
    先问一句，hidden 就立刻把原因说清楚。"""
    if str(_cdp.eval_on(cs, "document.visibilityState", max_len=20)).strip().lower() == "hidden":
        raise AiBrowserError(_VIS_ERR)

_KEYS = {
    "enter": ("Enter", 13), "tab": ("Tab", 9), "escape": ("Escape", 27),
    "esc": ("Escape", 27), "backspace": ("Backspace", 8), "delete": ("Delete", 46),
    "del": ("Delete", 46), "arrowup": ("ArrowUp", 38), "arrowdown": ("ArrowDown", 40),
    "arrowleft": ("ArrowLeft", 37), "arrowright": ("ArrowRight", 39),
    "home": ("Home", 36), "end": ("End", 35), "pageup": ("PageUp", 33),
    "pagedown": ("PageDown", 34), "space": (" ", 32),
}
for _i in range(1, 13):                 # F1–F12
    _KEYS["f%d" % _i] = ("F%d" % _i, 111 + _i)
# CDP Input.dispatchKeyEvent 的 modifiers 位（协议定义）：Alt=1、Ctrl=2、
# Meta/Command=4、Shift=8。对抗审计实锤：此前 Alt 误写成 4（那是 Meta）
_MODS = {"alt": 1, "ctrl": 2, "control": 2, "shift": 8,
         "meta": 4, "cmd": 4, "command": 4, "win": 4, "super": 4}
# Shift + 可打印字符必须带 text 才输得进去（rawKeyDown 加 Shift 不产生文本）：
# 主键盘的上档符号
_SHIFTED = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&",
            "8": "*", "9": "(", "0": ")", "`": "~", "-": "_", "=": "+", "[": "{",
            "]": "}", "\\": "|", ";": ":", "'": '"', ",": "<", ".": ">", "/": "?"}
# 数字 / 标点 / 空格的 KeyboardEvent.code（字母是 Key<X>，命名键与键名同名）
_KEY_CODES = {" ": "Space", ",": "Comma", ".": "Period", "/": "Slash", ";": "Semicolon",
              "'": "Quote", "[": "BracketLeft", "]": "BracketRight", "\\": "Backslash",
              "-": "Minus", "=": "Equal", "`": "Backquote"}
# 上档字符 → 物理键（? 的物理键是 /，< 是 ,，% 是 5）：KeyboardEvent.code 永远按物理键算
_UNSHIFTED = {v: k for k, v in _SHIFTED.items()}


def _key_code(ch):
    """可打印字符的 KeyboardEvent.code（按没按修饰键时的物理键算）；取不到给
    None。个别字母大写后会变长（ß → SS），拼不出 Key<X>，就别硬拼。"""
    if len(ch) != 1:
        return None
    if ch.isalpha():
        return ("Key" + ch.upper()) if len(ch.upper()) == 1 else None
    if ch.isdigit():
        return "Digit" + ch
    return _KEY_CODES.get(_UNSHIFTED.get(ch, ch))


def _mouse(cs, x, y, button="left"):
    for t, extra in (("mouseMoved", {"button": "none"}),
                     ("mousePressed", {"button": button, "clickCount": 1}),
                     ("mouseReleased", {"button": button, "clickCount": 1})):
        cs.send("Input.dispatchMouseEvent",
                dict({"type": t, "x": float(x), "y": float(y)}, **extra))


def _key(cs, combo):
    """按键组合（"Enter" / "Control+a" / "Shift+Tab"）。"""
    raw = str(combo)
    if raw == " ":                    # 单个空格 = 空格键（下面的过滤会把它当空丢掉）
        parts = [" "]
    else:
        parts = [p.strip() for p in raw.split("+") if p.strip()]
        if not parts:
            raise AiBrowserError("按键名不能为空")
    mods = 0
    for m in parts[:-1]:
        v = _MODS.get(m.lower())
        if v is None:
            raise AiBrowserError("不认识的修饰键：%s（可用 Ctrl / Shift / Alt）" % m)
        mods |= v
    main = parts[-1]
    named = main.lower() in _KEYS
    if named:
        key, vk = _KEYS[main.lower()]
    elif len(main) == 1:
        key = main
        # 个别字符大写后会变长（ß → SS），ord() 会炸：取不到虚拟键码就按 0
        vk = ord(main.upper()) if len(main.upper()) == 1 else 0
    else:
        raise AiBrowserError("不认识的按键：%s（如 Enter / Tab / Escape / ArrowDown / F5 / Ctrl+a）" % main)
    base = {"key": key, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
            "modifiers": mods}
    # code 按「没按修饰键时的物理键」算，所以要在改 key 之前定下来
    if key == " ":
        base["code"] = "Space"
    elif named:
        base["code"] = key             # 其余命名键 code 同名（Enter / Tab / F5 / ArrowUp…）
    else:
        code = _key_code(key)
        if code:
            base["code"] = code
    text = None
    if len(key) == 1:                  # 可打印字符：带 text 才会输入
        if not mods:
            text = key
        elif mods == 8:                # 仅 Shift：输上档字符（大写字母 / 上档符号）
            text = key.upper() if key.isalpha() else _SHIFTED.get(key, key)
    if text is not None:
        if mods == 8:
            base["key"] = text         # DOM 的 key 值随修饰键变：Shift+a 的 key 是 "A"
        cs.send("Input.dispatchKeyEvent",
                dict(base, type="keyDown", text=text, unmodifiedText=key))
    else:
        cs.send("Input.dispatchKeyEvent", dict(base, type="rawKeyDown"))
    cs.send("Input.dispatchKeyEvent", dict(base, type="keyUp"))


def _insert_text(cs, text, cps=45):
    """整段文本走 Input.insertText（非 ASCII / 长文本）。换行处改按键：
    insertText 会把 \\n 当文本塞进去、不会回车——工具描述承诺的是「\\n 表示
    回车」，不能只有逐字路径兑现（对抗审计实锤）"""
    for i, seg in enumerate(text.split("\n")):
        if i:
            _key(cs, "Enter")
            time.sleep(1.0 / cps)
        if seg:
            cs.send("Input.insertText", {"text": seg})


def _type_text(cs, text, cps=45):
    """逐字键入——页面上看得见输入过程。非 ASCII 整段或超 120 字符改
    Input.insertText（逐字 keyDown 对中文等不可靠；长了也太慢）。"""
    if not text:
        return
    if len(text) > 120 or any(ord(c) > 127 for c in text):
        _insert_text(cs, text, cps)
        return
    for ch in text:
        if ch == "\n":
            _key(cs, "Enter")
        elif ch == "\t":
            _key(cs, "Tab")
        else:
            up = ch.upper()
            vk = ({"windowsVirtualKeyCode": ord(up)}
                  if ch.isalpha() and len(up) == 1 else {})   # ß.upper() 变长，ord 会炸
            code = {"code": _key_code(ch)} if _key_code(ch) else {}   # 与 _key 同口径
            cs.send("Input.dispatchKeyEvent", dict(
                {"type": "keyDown", "key": ch, "text": ch, "unmodifiedText": ch,
                 "modifiers": 0}, **vk, **code))
            cs.send("Input.dispatchKeyEvent", dict(
                {"type": "keyUp", "key": ch, "modifiers": 0}, **vk, **code))
        time.sleep(1.0 / cps)


# 元素定位：scrollIntoView 后取中心点 + 人话标签（「搜索」按钮之类，给状态条用）。
# behavior:'instant' 是必须的：页面若设了 scroll-behavior:smooth，默认滚动是动画，
# 紧接着取到的是滚动前的坐标（对抗审计指出）
_ELEM_JS = r"""(function(){
var els = document.querySelectorAll(%s); var e = els[%d];
if (!e) return JSON.stringify({ok:false, count: els.length});
e.scrollIntoView({block:'center', inline:'center', behavior: 'instant'});
var r = e.getBoundingClientRect();
var cx = r.left + r.width/2, cy = r.top + r.height/2;
var txt = (e.getAttribute('aria-label') || e.getAttribute('placeholder') ||
  e.getAttribute('title') || (e.innerText || e.textContent || '') || e.value ||
  e.getAttribute('name') || e.id || '').replace(/\s+/g, ' ').trim().slice(0, 40);
return JSON.stringify({ok:true, x:cx, y:cy,
  inView: cx >= 0 && cy >= 0 && cx <= innerWidth && cy <= innerHeight,
  label: e.tagName.toLowerCase() + (txt ? '「' + txt + '」' : '')});
})()"""


def _locate(cs, d, need=True):
    """解析目标：selector（+index）或坐标 x/y。返回 (x, y, label, 中心是否在
    网页可视区内) 或 None（坐标点击时第三项之后的可见性不判，给 None）。"""
    sel = d.get("selector")
    if sel:
        idx = int(d.get("index") or 0)
        info = json.loads(_cdp.eval_on(
            cs, _ELEM_JS % (json.dumps(str(sel)), idx)))
        if not info.get("ok"):
            if not need:
                return None
            raise AiBrowserError("页面上没找到元素 %s（匹配 %s 个，index=%d）"
                                 % (sel, info.get("count", 0), idx))
        return (float(info["x"]), float(info["y"]),
                info.get("label") or str(sel), bool(info.get("inView")))
    try:
        x, y = float(d.get("x")), float(d.get("y"))
    except (TypeError, ValueError):
        if not need:
            return None
        raise AiBrowserError("需要 selector（CSS 选择器）或 x、y 坐标")
    return x, y, "(%s, %s)" % (d.get("x"), d.get("y")), None


# ---- 操作端点 ----

@ai_browser_bp.route("/api/ai_browser/navigate", methods=["POST"])
@_op
def _navigate(cs, d):
    url = str(d.get("url") or "").strip()
    if url != "about:blank" and not re.match(r"^https?://", url, re.I):
        raise AiBrowserError("只接受 http/https 网址（或 about:blank）：%s" % url[:120])
    _ui("ai_browser_op", op="navigate", text=url)
    cs.send("Page.enable")
    res = cs.send("Page.navigate", {"url": url}, timeout=15)
    if res.get("errorText"):
        raise AiBrowserError("打不开 %s：%s" % (url[:100], res["errorText"]))
    # 等加载的上限夹到 1–60 秒：AI 把秒当毫秒传（30000）且页面迟迟不 load 时，
    # 会一直占着操作锁和整个 MCP 进程（单线程——串口工具也跟着不响应）
    try:
        wait_s = float(d.get("timeout") or _SLOW_LOAD)
    except (TypeError, ValueError):
        wait_s = _SLOW_LOAD
    wait_s = min(60.0, max(1.0, wait_s))
    loaded = cs.wait_event("Page.loadEventFired", timeout=wait_s) is not None
    href = _cdp.eval_on(cs, "location.href", max_len=300)
    title = _cdp.eval_on(cs, "document.title || ''", max_len=200)
    return {"url": href, "title": title, "loaded": loaded,
            "text": "已打开：%s%s%s" % (
                href, ("  «%s»" % title) if title else "",
                "" if loaded else "\n（%d 秒内没等到加载完成——页面可能还在加载，"
                "可用 browser_wait 等元素出现）" % int(wait_s))}


@ai_browser_bp.route("/api/ai_browser/click", methods=["POST"])
@_op
def _click(cs, d):
    _check_visible(cs)
    x, y, label, in_view = _locate(cs, d)
    button = "right" if str(d.get("button") or "left").lower() == "right" else "left"
    _ui("ai_browser_op", op="click", x=x, y=y, label=label)
    time.sleep(0.3)       # 让前端先把光标移过去——「看得见移过去、再点」
    _mouse(cs, x, y, button)
    note = ("" if in_view is not False else
            "\n（注意：该元素的中心不在网页可视区内，这一下可能没点中——可先用 "
            "browser_eval 把它滚进可视区，或改用坐标点击）")
    return {"x": x, "y": y, "label": label, "in_view": in_view,
            "text": "已点击 %s%s" % (label, note)}


@ai_browser_bp.route("/api/ai_browser/type", methods=["POST"])
@_op
def _type(cs, d):
    text = str(d.get("text") or "")
    if not text:
        raise AiBrowserError("text 不能为空")
    _check_visible(cs)
    label = "当前焦点元素"
    # 显式给了 selector：没找到就报错（与 click 一致），不悄悄改成输给当前焦点元素
    loc = _locate(cs, d, need=bool(d.get("selector")))
    if loc:
        x, y, label, _iv = loc
        _ui("ai_browser_op", op="click", x=x, y=y, label=label)
        time.sleep(0.25)
        _mouse(cs, x, y)
        if d.get("clear", True):
            _key(cs, "Control+a")
            _key(cs, "Delete")
    _ui("ai_browser_op", op="type", text=text[:80], label=label)
    _type_text(cs, text)
    enter = bool(d.get("enter"))
    if enter:
        _key(cs, "Enter")
    return {"label": label,
            "text": "已向 %s 输入%s：%s" % (label, "（回车确认）" if enter else "",
                                          text[:80])}


@ai_browser_bp.route("/api/ai_browser/press", methods=["POST"])
@_op
def _press(cs, d):
    # 不能先 strip：单个空格就是空格键（纯空白的报错交给 _key 判）
    combo = str(d.get("key") or "")
    _check_visible(cs)
    _ui("ai_browser_op", op="press", text=combo)
    _key(cs, combo)
    return {"text": "已按键 %s" % combo}


@ai_browser_bp.route("/api/ai_browser/eval", methods=["POST"])
@_op
def _eval_api(cs, d):
    expr = str(d.get("expression") or "")
    if not expr:
        raise AiBrowserError("缺少必填参数 expression")
    max_len = max(500, min(20000, int(d.get("max_len") or 4000)))
    _ui("ai_browser_op", op="eval", text=expr.lstrip().split("\n")[0][:60])
    out = _cdp.eval_on(cs, expr, max_len=max_len)
    return {"text": out}


_DOM_JS = r"""(function(){
var els = document.querySelectorAll(%s); var items = [];
for (var i = 0; i < Math.min(els.length, %d); i++) {
  var e = els[i], r = e.getBoundingClientRect();
  items.push({tag: e.tagName, id: e.id || '', cls: String(e.className || '').slice(0, 100),
    text: (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 150),
    w: Math.round(r.width), h: Math.round(r.height), vis: r.width > 0 && r.height > 0});
}
return JSON.stringify({url: location.pathname, title: document.title,
  ready: document.readyState, count: els.length, items: items});
})()"""


@ai_browser_bp.route("/api/ai_browser/dom", methods=["POST"])
@_op
def _dom(cs, d):
    sel = str(d.get("selector") or "")
    if not sel:
        raise AiBrowserError("缺少必填参数 selector")
    limit = max(1, min(50, int(d.get("limit") or 20)))
    _ui("ai_browser_op", op="dom", text=sel[:60])
    out = _cdp.eval_on(cs, _DOM_JS % (json.dumps(sel), limit), max_len=20000)
    try:
        j = json.loads(out)
    except Exception:
        return {"text": out}
    lines = ["页面: %s %s [%s]" % (j.get("title", ""), j.get("url", ""), j.get("ready", "")),
             "命中 %s 个" % j.get("count", 0)]
    for it in j.get("items", []):
        sz = (" [%sx%s]" % (it.get("w"), it.get("h"))) if it.get("vis") else " [隐藏]"
        lines.append("<%s id=%s class=%s> %s%s" % (
            it.get("tag"), it.get("id") or "-", (it.get("cls") or "-")[:40],
            (it.get("text") or "")[:80], sz))
    if j.get("count", 0) > len(j.get("items", [])):
        lines.append("（仅列前 %d 个）" % len(j.get("items", [])))
    return {"text": "\n".join(lines)}


@ai_browser_bp.route("/api/ai_browser/screenshot", methods=["POST"])
@_op
def _screenshot(cs, d):
    _check_visible(cs)       # hidden 时 Page.captureScreenshot 挂死不返回——先挡
    _ui("ai_browser_op", op="screenshot", text="（整页）" if d.get("full") else "")
    cs.send("Page.enable")
    params = {"format": "png"}
    if d.get("full"):       # 整页：按内容尺寸裁剪（视口之外也截进来）
        m = cs.send("Page.getLayoutMetrics")
        c = m.get("cssContentSize") or m.get("contentSize") or {}
        w, h = float(c.get("width") or 0), float(c.get("height") or 0)
        if w > 0 and h > 0:
            params["clip"] = {"x": 0, "y": 0, "width": min(w, 16384),
                              "height": min(h, 16384), "scale": 1}
            params["captureBeyondViewport"] = True
    res = cs.send("Page.captureScreenshot", params, timeout=20)
    data = base64.b64decode(res.get("data", ""))
    if not data:
        raise AiBrowserError("截图没有拿到数据")
    folder = os.path.join(_st.DATA_DIR, "ai_browser")   # 项目约定：数据目录只认 st.DATA_DIR
    os.makedirs(folder, exist_ok=True)
    fp = os.path.join(folder, time.strftime("shot_%Y%m%d_%H%M%S")
                      + "_%03d.png" % (int(time.time() * 1000) % 1000))
    with open(fp, "wb") as f:
        f.write(data)
    return {"path": fp, "text": "已保存: %s (%.1f KB)" % (fp, len(data) / 1024)}


_HIST_JS = r"""(function(){
var nav = window.navigation;
if (nav && !nav.canGo%s) return false;
history.%s();
return true;
})()"""


def _history_move(cs, delta):
    """在网页内部走历史（后退 / 前进）。返回是否真的走了。
    不用 CDP Page 域的导航命令（navigateToHistoryEntry / reload）：guest 的框架
    挂在宿主页面的框架树上，端到端实测 Page.reload 把宿主页面（整个前端控制台
    界面）一起重载了。壳的 guest 右键菜单同样是网页内 history.back()/forward()
    （electron/main.js web-contents-created 段注释：guest 内 Navigation API
    判态 + history 实测可靠）。"""
    how, can = ("back", "Back") if delta < 0 else ("forward", "Forward")
    return str(_cdp.eval_on(cs, _HIST_JS % (can, how))).strip() == "true"


@ai_browser_bp.route("/api/ai_browser/back", methods=["POST"])
@_op
def _back(cs, d):
    if _history_move(cs, -1):           # 真走了才推指示帧（状态条：正在后退…）
        _ui("ai_browser_op", op="navigate", text="后退")
        return {"text": "已后退"}
    return {"text": "没有更早的页面"}


@ai_browser_bp.route("/api/ai_browser/forward", methods=["POST"])
@_op
def _forward(cs, d):
    if _history_move(cs, 1):
        _ui("ai_browser_op", op="navigate", text="前进")
        return {"text": "已前进"}
    return {"text": "没有更靠后的页面"}


@ai_browser_bp.route("/api/ai_browser/reload", methods=["POST"])
@_op
def _reload(cs, d):
    _ui("ai_browser_op", op="navigate", text="重新加载")
    cs.send("Page.enable")
    try:
        _cdp.eval_on(cs, "location.reload()")     # 同 _history_move：不用 Page.reload
    except CdpError:
        pass        # 页面立刻开始重载、这条的回包没等到——正常
    loaded = cs.wait_event("Page.loadEventFired", timeout=_SLOW_LOAD) is not None
    return {"loaded": loaded, "text": "已重新加载" + ("" if loaded else "（没等到加载完成）")}


@ai_browser_bp.route("/api/ai_browser/wait", methods=["POST"])
@_op
def _wait(cs, d):
    ms = d.get("ms")
    if ms is not None:     # 固定等待
        sec = min(10.0, max(0.0, float(ms) / 1000.0))
        _ui("ai_browser_op", op="wait", text="%d ms" % int(sec * 1000))
        time.sleep(sec)
        return {"found": True, "text": "已等待 %d ms" % int(sec * 1000)}
    sel = d.get("selector")
    if not sel:
        raise AiBrowserError("wait 需要 selector（等元素出现）或 ms（固定等待，毫秒，≤10000）")
    _ui("ai_browser_op", op="wait", text=str(sel)[:60])
    timeout = min(30.0, max(1.0, float(d.get("timeout") or 15)))
    probe = "!!document.querySelector(%s)" % json.dumps(str(sel))
    deadline = time.time() + timeout
    while True:
        if str(_cdp.eval_on(cs, probe)).strip() == "true":
            return {"found": True, "text": "元素已出现：%s" % sel}
        if time.time() >= deadline:
            break
        time.sleep(0.2)
    return {"found": False,
            "text": "%d 秒内没等到元素出现：%s" % (int(timeout), sel)}


# ---- console / network：监听线程 + 环形缓冲 ----
# 视图里加载的是外部网页，没有工具主页面的 window.__consoleBuf——历史只能
# 自己收：后台线程挂一条常驻 CDP 会话订阅 Runtime/Log/Network 事件入缓冲，
# 工具来读缓冲（操作仍走各自的临时会话，两条连接互不影响）。

_hist_lock = threading.RLock()
_console_buf = deque(maxlen=_LISTEN_MAX)
_net_buf = OrderedDict()            # requestId → 行（插入序，超上限删最旧）
_wake = threading.Event()
_thr = None
_thr_lock = threading.Lock()
# 监听线程是否已接上当前登记的视图：[当前视图代次, 已接上的代次]（-1 = 没接上）。
# 视图每次换登记代次 +1；没接上就导航的话，新页面早期的 console / 网络事件会漏
_listen_cv = threading.Condition()
_listen_gen = [0, -1]


def _hist_clear():
    with _hist_lock:
        _console_buf.clear()
        _net_buf.clear()


def _listen_mark(gen):
    with _listen_cv:
        _listen_gen[1] = gen
        _listen_cv.notify_all()


def _wait_listen(timeout=3.0):
    """等监听线程接上当前登记的视图（接不上也放行，只是早期事件会漏）。"""
    with _lock:
        tid, gen = _state["target_id"], _state["gen"]
    if not tid:
        return False
    with _listen_cv:
        return _listen_cv.wait_for(lambda: _listen_gen[1] == gen, timeout)


def _listener_kick():
    _wake.set()


def _listener_start():
    """登记变化后调用：确保监听线程在跑（幂等）。"""
    global _thr
    _wake.set()
    with _thr_lock:
        if _thr is None or not _thr.is_alive():
            _thr = threading.Thread(target=_listener_loop,
                                    name="ai-browser-cdp", daemon=True)
            _thr.start()


def _next_backoff(cur):
    """监听线程重连退避：0.5s 起每次翻倍，5s 封顶。"""
    return min(5.0, cur * 2)


def _listener_loop():
    """监听线程主循环。退避等待必须是「可被打断」的：登记一变（新视图 attach /
    detach）就要立刻去接新的，不能还睡在退避里——否则新视图最多晚 5 秒才被接上，
    超过 _wait_listen 的等待，首次导航的网络事件会漏（对抗复审实锤：第一版用
    time.sleep，叫不醒）。"""
    backoff = 0.5
    while True:
        with _lock:
            cur = _state["target_id"]
        if not cur:
            _wake.wait()              # 没有登记：等 attach 来叫
            _wake.clear()
            backoff = 0.5
            continue
        if _listener_tick():          # 连接断了 / 连不上，但这个视图仍是登记中的
            if _wake.wait(backoff):   # 退避重连；attach / detach 来了立刻醒
                _wake.clear()
                backoff = 0.5
            else:
                backoff = _next_backoff(backoff)
        else:
            backoff = 0.5             # 登记换掉了：立刻去接新的，不等


def _listener_tick():
    """连上当前登记的视图收事件，直到登记换掉或连接断开。
    返回真 = 这个视图仍是登记中的（需要再来一轮）。"""
    with _lock:
        tid = _state["target_id"]
        gen = _state["gen"]
    if not tid:
        return False
    try:
        with _cdp.CdpSession(_cdp.find_cdp(), tid) as cs:
            cs.send("Runtime.enable")
            cs.send("Log.enable")
            cs.send("Network.enable")
            _listen_mark(gen)        # 接上了：此后新导航的早期事件不会漏
            while cs.collect(60.0, _on_evt, stop=lambda: (
                    _state["target_id"], _state["gen"]) != (tid, gen)) == "done":
                pass
    except Exception as e:
        log.debug("ai_browser 监听线程：连接断开或失败（%r），稍后重连", e)
    with _listen_cv:                 # 这条连接断了：下次导航前要等重新接上
        if _listen_gen[1] == gen:
            _listen_gen[1] = -1
    with _lock:
        return _state["target_id"] == tid


def _arg_text(a):
    if not isinstance(a, dict):
        return ""
    if a.get("value") is not None:
        return str(a["value"])
    return str(a.get("description") or a.get("type") or "")


def _console_item(msg):
    """console / 未捕获异常 / 浏览器日志事件 → 缓冲条目；不是这类返回 None。"""
    m = msg.get("method", "")
    pm = msg.get("params", {}) or {}
    if m == "Runtime.consoleAPICalled":
        lv = pm.get("type", "log")
        return {"t": time.time(), "lv": "warn" if lv == "warning" else lv,
                "text": " ".join(_arg_text(a) for a in pm.get("args", []))}
    if m == "Runtime.exceptionThrown":
        det = pm.get("exceptionDetails", {}) or {}
        return {"t": time.time(), "lv": "error", "text": (
            (det.get("exception") or {}).get("description")
            or det.get("text") or "未捕获异常")}
    if m == "Log.entryAdded":
        en = pm.get("entry", {}) or {}
        lv = "warn" if en.get("level") == "warning" else (en.get("level") or "info")
        return {"t": time.time(), "lv": lv, "text": en.get("text") or ""}
    return None


def _on_evt(msg):
    it = _console_item(msg)
    if it is not None:
        with _hist_lock:
            _console_buf.append(it)
        return
    m = msg.get("method", "")
    pm = msg.get("params", {}) or {}
    rid = pm.get("requestId", "")
    with _hist_lock:
        if m == "Network.requestWillBeSent":
            req = pm.get("request") or {}
            _net_buf[rid] = {"t": time.time(), "url": req.get("url", ""),
                             "method": req.get("method", ""),
                             "type": pm.get("type", ""), "status": None,
                             "size": None, "done": False}
            while len(_net_buf) > _LISTEN_MAX:
                _net_buf.popitem(last=False)
            return
        r = _net_buf.get(rid)
    if r is None:
        return
    if m == "Network.responseReceived":
        r["status"] = (pm.get("response") or {}).get("status")
        r["type"] = pm.get("type") or r["type"]
    elif m == "Network.loadingFinished":
        r["done"] = True
        r["size"] = pm.get("encodedDataLength")
    elif m == "Network.loadingFailed":
        r["done"] = True
        r["status"] = "FAIL:" + str(pm.get("errorText", "err"))


def _console_text(items, tail, level):
    shown, n_err, n_warn = [], 0, 0
    for it in items:
        lv = it.get("lv", "log")
        if lv == "error":
            n_err += 1
        elif lv == "warn":
            n_warn += 1
        if level == "error" and lv != "error":
            continue
        if level == "warn" and lv not in ("warn", "error"):
            continue
        shown.append(it)
    lines = ["统计: error %d, warn %d（缓冲起点=视图最近一次连接）" % (n_err, n_warn)]
    drop = len(shown) - tail
    if drop > 0:
        lines.append("（已省略最早 %d 条，显示最新 %d 条）" % (drop, tail))
    for it in shown[-tail:]:
        lines.append("[%s][%s] %s" % (
            time.strftime("%H:%M:%S", time.localtime(it.get("t") or 0)),
            it.get("lv"), (it.get("text") or "")[:300]))
    return lines


@ai_browser_bp.route("/api/ai_browser/console", methods=["POST"])
@_op
def _console(cs, d):
    tail = max(1, min(200, int(d.get("tail") or 50)))
    level = d.get("level") or "all"
    live = max(0.0, min(30.0, float(d.get("live_seconds") or 0)))
    _ui("ai_browser_op", op="console", text="")
    with _hist_lock:
        items = list(_console_buf)
    lines = _console_text(items, tail, level)
    if live > 0:
        got = []

        def _on(msg):
            if msg.get("method") == "_cdp_disconnected":
                got.append({"t": time.time(), "lv": "error", "text": "〔窗口期内页面断连〕"})
                return
            it = _console_item(msg)
            if it is None:
                return
            got.append(it)
            # 写不写历史，看常驻监听线程此刻接没接上这个视图：接上了，它已经收了
            # 同一条（两条 CDP 会话各收一份事件），再写统计就翻倍；没接上（退避
            # 重连中），这条临时会话就是唯一的来源，不写就丢了（对抗复审实锤）
            with _lock:
                gen = _state["gen"]
            with _listen_cv:
                covered = _listen_gen[1] == gen
            if not covered:
                with _hist_lock:
                    _console_buf.append(it)

        cs.send("Runtime.enable")
        cs.send("Log.enable")
        cs.collect(live, _on)
        lines.append("—— 实时窗口 %ds 收到 %d 条 ——" % (int(live), len(got)))
        lines.extend(_console_text(got, 30, level)[1:])    # [1:]：统计行只留头部那条
    return {"text": "\n".join(lines[:235])}


def _network_text(rows, seconds):
    fail = [r for r in rows if str(r.get("status", "")).startswith("FAIL")]
    bad = [r for r in rows if isinstance(r.get("status"), int) and r["status"] >= 400]
    lines = ["最近 %ds，共 %d 请求 | 失败 %d | 4xx/5xx %d" % (
        int(seconds), len(rows), len(fail), len(bad))]
    fb = fail + bad
    for r in fb[:15]:
        lines.append("  !! %s %s" % (r.get("status"), r["url"][:120]))
    if len(fb) > 15:
        lines.append("  （另有 %d 条失败/异常略）" % (len(fb) - 15))
    fb_ids = {id(r) for r in fb}
    body = [r for r in rows if id(r) not in fb_ids][-40:]
    for r in body:
        st = r.get("status")
        if not r.get("done"):
            st = "[stream]"
        elif not st:
            st = "?"
        sz = ("%dk" % (r["size"] // 1024)) if r.get("size") else ""
        lines.append("%s %s %s %s %s" % (st, r.get("method", ""), r["url"][:120],
                                         r.get("type", ""), sz))
    more = len(rows) - len(fb) - len(body)
    if more > 0:
        lines.append("（另有 %d 条更早的略）" % more)
    return lines


@ai_browser_bp.route("/api/ai_browser/network", methods=["POST"])
@_op
def _network(cs, d):
    seconds = max(1, min(300, int(d.get("seconds") or 10)))
    flt = str(d.get("filter") or "")
    _ui("ai_browser_op", op="network", text=flt[:60])
    since = time.time() - seconds
    with _hist_lock:
        rows = [r for r in _net_buf.values()
                if r["t"] >= since and (not flt or flt in r["url"])]
    return {"text": "\n".join(_network_text(rows, seconds))}


# ---- 登记 / 状态（壳与前端调用）----

@ai_browser_bp.route("/api/ai_browser/attach", methods=["POST"])
def _attach():
    """壳调用：{wc_id, target_id, partition}——主进程对该 guest 取到的 CDP targetId。"""
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        d = {}
    tid = str(d.get("target_id") or "").strip()
    if not tid:
        return jsonify({"ok": False, "err": "缺少 target_id"})
    # 分区名必须是 AI 浏览器的：用户自己开的网页 tab 也是 type=webview，只看类型
    # 拦不住。壳凭分区名认视图，这里按同一个名字再核一遍（三处对齐的第三处）
    if str(d.get("partition") or "") != PARTITION:
        return jsonify({"ok": False, "err": "partition 不是 AI 浏览器的分区"})
    # 还得是壳里现存的网页视图（type=webview）：防把工具自己的主页面 target 登记
    # 进来——那样 devtools_* 的默认目标就又变回工具界面，用户拍板的「必须显式
    # target=app 才能操作工具界面」被绕过
    try:
        port = _cdp.find_cdp()
        if not any(t.get("id") == tid and t.get("type") == "webview"
                   for t in _cdp.list_targets(port)):
            return jsonify({"ok": False,
                            "err": "target_id 不是现存的网页视图（type=webview）"})
    except DevtoolsError as e:
        return jsonify({"ok": False, "err": "CDP 端口连不上：%s" % e})
    with _lock:
        changed = _state["target_id"] != tid
        _state.update(target_id=tid, wc_id=d.get("wc_id"), ts=time.time())
        _state["gen"] = _state["gen"] + 1 if changed else _state["gen"]
    if changed:
        _hist_clear()       # 换了视图：旧视图的 console/网络历史不再对应
    _listener_start()
    # 下载目录不在这里交给壳：普通网页标签页的下载也走同一套（2026-11-24 用户令），
    # 壳统一向下载中心（src/downloads.py）取，与登记无关
    return jsonify({"ok": True})


@ai_browser_bp.route("/api/ai_browser/detach", methods=["POST"])
def _detach():
    """视图销毁时调用（页面卸载 / guest destroyed）。wc_id 不符 = 迟到的旧
    视图通知，不动新登记。"""
    d = request.get_json(force=True, silent=True)
    if not isinstance(d, dict):
        d = {}
    with _lock:
        wc = d.get("wc_id")
        if (wc is not None and _state.get("wc_id") is not None
                and str(wc) != str(_state["wc_id"])):
            return jsonify({"ok": True, "stale": True})
        _state.update(target_id=None, wc_id=None, ts=0.0)
    _listener_kick()
    return jsonify({"ok": True})


@ai_browser_bp.route("/api/ai_browser/state", methods=["GET"])
def _state_api():
    with _lock:
        on = bool(_state["target_id"])
    return jsonify({"ok": True, "enabled": _enabled(), "attached": on})


# ---- 下载的状态条显示 ----
# 下载登记已独立成模块 src/downloads.py（2026-11-24 用户令：AI 浏览器与普通网页
# 标签页共用的下载中心）。这里只保留一件事：AI 浏览器里的下载要在它的状态条上
# 显示出来（用户看着 AI 操作时能看见「在下载 / 存好了」）。
def _dl_status(rec, event):
    if rec.get("source") != "ai_browser" or event == "updated":
        return      # 普通网页标签页的下载不进 AI 浏览器的状态条；进度帧只给下载面板
    name = rec["filename"]
    if rec["state"] == "completed":
        text = "下载完成：%s（%s）→ 已存到下载目录" % (name, _downloads._fmt_bytes(rec["received"]))
    elif rec["state"] == "cancelled":
        text = "下载已取消：" + name
    elif rec["state"] == "interrupted":
        text = "下载失败：%s（%s）" % (name, rec["error"] or "原因未知")
    else:
        text = "开始下载：" + name
    _ui("ai_browser_op", op="download", text=text)


_downloads.subscribe(_dl_status)
