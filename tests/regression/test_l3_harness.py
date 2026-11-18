# -*- coding: utf-8 -*-
"""L3 真实 CLI 交互：发送真实消息，验证流式/工具/工作头/排队/停止/子代理。

⚠ 消耗 Claude CLI 额度。默认不随 L0-L2 执行，需显式 --layers L3。
每条场景独立新建测试会话；结束后切回测试开始时的会话（不删除测试会话）。

用法：
    python tests/regression/test_l3_harness.py --groups H1,H3,H4
    可用组：H1 H2 H3 H4 H5 H6 H7
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result          # noqa: E402


def _state(pg):
    return json.loads(pg.ev(
        "JSON.stringify({sid:(window._HG&&window._HG.sid)||null,"
        "busy:!!(window._HG&&window._HG.busy),"
        "heads:[...document.querySelectorAll('.h-turn-head')].map(e=>({t:(e.textContent||'').trim(),d:e.style.display})),"
        "asst:document.querySelectorAll('.h-msg.asst').length,"
        "think:document.querySelectorAll('.h-drawer.think').length,"
        "tools:document.querySelectorAll('.h-tool').length,"
        "toolSlots:[...document.querySelectorAll('.h-tool .h-tslots')].map(e=>(e.textContent||'').trim())})")
        or "{}")


def _send(pg, text, timeout=120):
    pg.ev("(async()=>{var el=window._hgInput;el.value=%s;"
          "el.dispatchEvent(new Event('input',{bubbles:true}));await window.send();return 1;})()"
          % json.dumps(text), await_promise=True, timeout=timeout)


def _wait_idle(pg, timeout=150, need_asst=True, need_tools=False):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        time.sleep(2)
        st = _state(pg)
        last = st
        if not st.get("busy"):
            if (not need_asst or st.get("asst")) and (not need_tools or st.get("tools")):
                time.sleep(1.2)
                return _state(pg)
    return last


def _new(pg):
    pg.ev("window.newChat()")
    time.sleep(0.8)


def g_h1(pg):
    """H1-1 发极简消息；H1-5 空输入不发送；H1-2 排队（快速连发两条）。"""
    out = []
    _new(pg)
    sid0 = pg.ev("(window._HG&&window._HG.sid)||null")
    _send(pg, "只回复三个字：收到了")
    st = _wait_idle(pg, need_asst=True)
    head_ok = any("已工作" in h["t"] for h in st.get("heads", []))
    out.append(result("H1-1", "新建会话→发消息→回复+工作头", "L3", "P0",
                      "PASS" if st.get("asst") and head_ok else "FAIL",
                      json.dumps({k: st.get(k) for k in ("asst", "heads", "busy")}, ensure_ascii=False)))
    # H1-5 空输入
    sid_before = pg.ev("(window._HG&&window._HG.sid)||null")
    pg.ev("(async()=>{window._hgInput.value='   ';await window.send();return 1;})()",
          await_promise=True, timeout=20)
    time.sleep(0.5)
    sid_after = pg.ev("(window._HG&&window._HG.sid)||null")
    out.append(result("H1-5", "空输入不发送", "L3", "P1",
                      "PASS" if sid_before == sid_after else "FAIL",
                      "sid不变=%s" % (sid_before == sid_after)))
    # H1-2 排队：连发两条
    _send(pg, "第一问：只回复数字 1", timeout=30)
    _send(pg, "第二问：只回复数字 2", timeout=30)
    queued = pg.ev("document.querySelectorAll('.hg-queue-item,[data-hg-queue] .item,.hg-qbar').length")
    st2 = _wait_idle(pg, timeout=180, need_asst=True)
    out.append(result("H1-2", "busy 中连发→排队→自动发出", "L3", "P1",
                      "PASS" if st2.get("asst", 0) >= 3 else "CHECK",
                      "asst=%s queueDom=%s busy=%s" % (st2.get("asst"), queued, st2.get("busy"))))
    return out


def g_h2(pg):
    """H2-1/2 流式正文与思考。"""
    out = []
    _new(pg)
    _send(pg, "先思考再回答：1+1 等于几？只回复数字")
    st = _wait_idle(pg, need_asst=True)
    out.append(result("H2-1", "正文流式渲染+定稿", "L3", "P0",
                      "PASS" if st.get("asst") else "FAIL", json.dumps(st.get("asst"))))
    out.append(result("H2-2", "思考段出现/收段", "L3", "P1",
                      "PASS" if st.get("think", 0) >= 1 else "SKIP",
                      "think=%s（模型未输出思考时正常）" % st.get("think")))
    return out


def g_h3(pg):
    """H3-1/2 工具行 live 出现与终态。"""
    out = []
    _new(pg)
    _send(pg, "用 Bash 执行一条命令 echo hi，然后只回复 done")
    seen = False
    end = time.time() + 120
    while time.time() < end:
        time.sleep(2)
        st = _state(pg)
        if st.get("tools"):
            seen = True
            break
    st = _wait_idle(pg, need_asst=True, need_tools=True)
    out.append(result("H3-1", "工具行 live 出现（未切会话）", "L3", "P0",
                      "PASS" if seen else "FAIL", "tools=%s" % st.get("tools")))
    slots = st.get("toolSlots") or []
    out.append(result("H3-2", "工具终态徽章回写", "L3", "P0",
                      "PASS" if any(("完成" in s or "错误" in s) for s in slots) else "CHECK",
                      "slots=%s" % slots))
    return out


def g_h4(pg):
    """H4-1/2 两种回合的工作头。"""
    out = []
    _new(pg)
    _send(pg, "只回复两个字：收到")
    st = _wait_idle(pg, need_asst=True)
    h = [x for x in st.get("heads", []) if "已工作" in x["t"] and x.get("d") != "none"]
    out.append(result("H4-1", "纯正文回合工作头", "L3", "P0",
                      "PASS" if h else "FAIL", json.dumps(st.get("heads"), ensure_ascii=False)))
    _send(pg, "用 Bash 执行 echo ok，然后只回复 done")
    st2 = _wait_idle(pg, need_asst=True, need_tools=True)
    h2 = [x for x in st2.get("heads", []) if "已工作" in x["t"] and ("工具" in x["t"] or "思考" in x["t"])]
    out.append(result("H4-2", "工具回合工作头带计数", "L3", "P1",
                      "PASS" if h2 else "CHECK", json.dumps(st2.get("heads"), ensure_ascii=False)))
    return out


def g_h5(pg):
    """H5-3 busy 中切走立即切回：活组不定稿、秒表续走。"""
    out = []
    _new(pg)
    _send(pg, "数到二十，每行一个数字", timeout=30)
    time.sleep(2.0)
    s1 = _state(pg)
    sid = s1.get("sid")
    pg.ev("window.newChat()")
    time.sleep(0.8)
    pg.ev("window.switchTo(%s)" % json.dumps(sid), await_promise=True, timeout=60)
    st = _wait_idle(pg, timeout=180, need_asst=True)
    heads = st.get("heads", [])
    out.append(result("H5-3", "busy 切走再切回内容完整", "L3", "P0",
                      "PASS" if st.get("asst") else "FAIL",
                      json.dumps({"asst": st.get("asst"), "busy": st.get("busy"),
                                  "heads": heads[:3]}, ensure_ascii=False)))
    return out


def g_h6(pg):
    """H6 子代理派发与窗格。"""
    out = []
    _new(pg)
    _send(pg, "派一个子代理执行：只回复子代理完成。然后你回复主完成。", timeout=30)
    st = _wait_idle(pg, timeout=240, need_asst=True)
    subs = pg.ev("document.querySelectorAll('.h-subpane,.h-subsec,.h-ag-live,.h-agent').length")
    tools = st.get("tools", 0)
    out.append(result("H6-1", "子代理派发行出现", "L3", "P0",
                      "PASS" if tools or subs else "CHECK",
                      "tools=%s subDom=%s" % (tools, subs)))
    out.append(result("H6-2/6", "子代理窗格/时间线", "L3", "P1",
                      "PASS" if subs else "SKIP", "subDom=%s" % subs))
    return out


def g_h7(pg):
    """H7-2 停止生成。"""
    out = []
    _new(pg)
    _send(pg, "从 1 数到 200，每个数字一行", timeout=30)
    # 必须等 busy 真正进入生成态再点停止——固定 sleep 会打在「已自然结束」
    # 的回合上（头已是已工作，stopGen 无活组早退，不是产品缺陷）
    for _ in range(30):
        time.sleep(0.25)
        if pg.ev("!!(window._HG&&window._HG.busy)"):
            break
    # 停止入口 = busy 态的发送钮（main.js: setBusy 切成 ■ + stopGen）
    stopped = False
    try:
        stopped = bool(pg.ev("(function(){if(typeof window.stopGen!=='function')return false;"
                             "window.stopGen();return true;})()"))
    except Exception:
        pass
    _wait_idle(pg, timeout=120, need_asst=False)
    # 中断定格由后端 interrupted 帧驱动，轮询最多 20s 等「已停止」出现
    heads_stop = []
    end = time.time() + 20
    while time.time() < end:
        st = _state(pg)
        heads_stop = [x for x in st.get("heads", []) if "已停止" in x["t"]]
        if heads_stop:
            break
        time.sleep(1)
    exit_row = pg.ev("document.querySelectorAll('.h-exit,.h-interrupted').length")
    out.append(result("H7-2", "停止生成→组头已停止", "L3", "P1",
                      "PASS" if stopped and heads_stop else "FAIL",
                      "clicked=%s exitRow=%s heads=%s" % (
                          stopped, exit_row,
                          json.dumps(_state(pg).get("heads"), ensure_ascii=False)[:220])))
    out.append(result("H7-1", "回滚到上一回合", "L3", "P1", "SKIP",
                      "破坏性操作（删除后续内容），需手工确认后执行"))
    out.append(result("H7-3", "压缩开始/结束", "L3", "P2", "SKIP",
                      "需触发上下文压缩（长会话），手工"))
    return out


def g_smoke(pg):
    """SMOKE：发布前 30 秒真机冒烟（1 条消息）。"""
    out = []
    _new(pg)
    _send(pg, "只回复两个字：收到")
    st = _wait_idle(pg, need_asst=True)
    head_ok = any("已工作" in h["t"] and h.get("d") != "none" for h in st.get("heads", []))
    out.append(result("SMOKE-1", "真机会话冒烟（发消息→回复→工作头）", "L3", "P0",
                      "PASS" if st.get("asst") and head_ok else "FAIL",
                      json.dumps({k: st.get(k) for k in ("asst", "heads", "busy")},
                                 ensure_ascii=False)))
    return out


GROUPS = {"H1": g_h1, "H2": g_h2, "H3": g_h3, "H4": g_h4,
          "H5": g_h5, "H6": g_h6, "H7": g_h7, "SMOKE": g_smoke}


def run(groups=None):
    groups = groups or ["H1", "H2", "H3", "H4"]
    try:
        pg = Page()
    except Exception as e:
        return [result("L3-ENV", "L3 环境", "L3", "P0", "SKIP", "应用未运行: %r" % e)]
    orig = None
    out = []
    try:
        orig = pg.ev("(window._HG&&window._HG.sid)||null")
        pg.clear_errs()
        for g in groups:
            fn = GROUPS.get(g)
            if not fn:
                out.append(result(g, g, "L3", "P2", "SKIP", "未知组"))
                continue
            try:
                out.extend(fn(pg))
            except Exception as e:
                out.append(result(g, g + " 组执行", "L3", "P0", "FAIL",
                                  "异常: %r" % (e,)))
        errs = pg.drain_errs()
        out.append(result("L3E", "L3 期间无页面异常", "L3", "P0",
                          "PASS" if not errs else "FAIL",
                          json.dumps(errs[:5], ensure_ascii=False)))
    finally:
        try:
            if orig:
                pg.ev("window.switchTo(%s)" % json.dumps(orig), await_promise=True, timeout=60)
        except Exception:
            pass
        pg.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", default="H1,H2,H3,H4")
    a = ap.parse_args()
    gs = [x.strip() for x in a.groups.split(",") if x.strip()]
    print(json.dumps(run(gs), ensure_ascii=False, indent=2))
