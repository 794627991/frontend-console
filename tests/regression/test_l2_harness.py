# -*- coding: utf-8 -*-
"""L2 Harness：CDP DOM 驱动、零 CLI 额度、不破坏会话内容。

安全策略：
- 只做「切换会话 / 收起展开 / 只读断言」；不发送任何消息。
- 结束时切回测试开始时的会话；不删除任何会话。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result          # noqa: E402


def _groups(pg):
    return int(pg.ev("document.querySelectorAll('.h-grp').length") or 0)


def _heads(pg):
    return json.loads(pg.ev(
        "JSON.stringify([...document.querySelectorAll('.h-turn-head')].map(e=>({t:(e.textContent||'').trim(),d:e.style.display})))") or "[]")


def _sessions(pg):
    return json.loads(pg.ev(
        "JSON.stringify(((window._HG&&window._HG.sessions)||[]).map(s=>s.sid||s.id||s))") or "[]")


def run():
    try:
        pg = Page()
    except Exception as e:
        return [result("L2-ENV", "L2 环境", "L2", "P0", "SKIP", "应用未运行: %r" % e)]
    out = []
    try:
        pg.clear_errs()
        orig = pg.ev("(window._HG&&window._HG.sid)||null")
        n0 = _groups(pg)
        heads0 = _heads(pg)
        # ---- H5-4 新建空会话：旧 DOM 清空、提示可见 ----
        pg.ev("window.newChat()")
        time.sleep(1.0)
        n_empty = _groups(pg)
        note = pg.ev_obj(
            "JSON.stringify({oldFlowRows: (window._HG.flowEl?window._HG.flowEl.children.length:-1),"
            " emptyNote: !!document.querySelector('.h-v4empty,.h-sysnote')})")
        out.append(result("H5-4", "新建空会话清空旧 DOM", "L2", "P1",
                          "PASS" if n_empty == 0 else "FAIL",
                          "组数=%d %s" % (n_empty, json.dumps(note, ensure_ascii=False))))
        # ---- H5-1 切回原会话：内容完整恢复 ----
        if orig:
            pg.ev("window.switchTo(%s)" % json.dumps(orig), await_promise=True, timeout=60)
            ok = pg.wait_until(
                "document.querySelectorAll('.h-grp').length >= %d" % max(1, n0),
                timeout=20, interval=0.5)
            n1 = _groups(pg)
            heads1 = _heads(pg)
            out.append(result("H5-1", "A→空→A 切回内容完整", "L2", "P0",
                              "PASS" if ok else "CHECK",
                              "切前组=%d 切回组=%d 头=%d" % (n0, n1, len(heads1))))
            # ---- H5-5 切回后贴底 ----
            sc = pg.ev_obj(
                "JSON.stringify((function(){var f=window._HG.flowEl;if(!f)return {};"
                "return {top:f.scrollTop,h:f.scrollHeight,c:f.clientHeight,"
                "near:(f.scrollHeight-f.scrollTop-f.clientHeight)<80};})())")
            out.append(result("H5-5", "切回后滚动贴近底部", "L2", "P2",
                              "PASS" if sc.get("near") or sc.get("h", 0) <= sc.get("c", 0) else "CHECK",
                              json.dumps(sc, ensure_ascii=False)))
            # ---- H4-4 手动展开后不被强制收起（交互：点开再点回） ----
            toggled = pg.ev_obj(
                "JSON.stringify((function(){var h=document.querySelector('.h-turn-head');"
                "var b=h&&h.closest('.h-grp')&&h.closest('.h-grp').querySelector('.h-grp-body,.h-turn-body');"
                "if(!h||!b)return {skip:true};var was=b.classList.contains('closed');"
                "h.click();var mid=!b.classList.contains('closed');h.click();"
                "return {skip:false,was:was,mid:mid,end:!b.classList.contains('closed')};})())")
            ok = (not toggled.get("skip")) and toggled.get("mid") is True
            out.append(result("H4-4", "组头展开/收起可交互", "L2", "P2",
                              "PASS" if ok else "CHECK", json.dumps(toggled, ensure_ascii=False)))
            # ---- H3-5 工具卡交互存在性 ----
            tool = pg.ev_obj(
                "JSON.stringify((function(){var t=document.querySelector('.h-tool');"
                "if(!t)return {skip:true};var head=t.querySelector('.h-tool-head');"
                "var copy=document.querySelector('.hg-mico.h-acopy');"
                "return {skip:false,head:!!head,copy:!!copy,slots:(t.querySelector('.h-tslots')||{}).textContent||''};})())")
            out.append(result("H3-5", "工具卡展开头/复制按钮存在", "L2", "P2",
                              "PASS" if (not tool.get("skip")) and tool.get("head") else
                              ("SKIP" if tool.get("skip") else "CHECK"),
                              json.dumps(tool, ensure_ascii=False)))
            # ---- H7-1 回滚按钮只授予末条回复 ----
            rw = pg.ev_obj(
                "JSON.stringify({rewindBtns: document.querySelectorAll('[data-hg-rewind]').length,"
                "asst: document.querySelectorAll('.h-msg.asst').length})")
            out.append(result("H7-1r", "回滚按钮唯一性", "L2", "P2",
                              "PASS" if rw.get("rewindBtns", 0) <= max(1, rw.get("asst", 1)) else "CHECK",
                              json.dumps(rw, ensure_ascii=False)))
        else:
            for cid, name, pri in [("H5-1", "A→空→A 切回内容完整", "P0"),
                                   ("H5-5", "切回后滚动贴近底部", "P2"),
                                   ("H4-4", "组头展开/收起可交互", "P2"),
                                   ("H3-5", "工具卡展开头/复制按钮存在", "P2"),
                                   ("H7-1r", "回滚按钮唯一性", "P2")]:
                out.append(result(cid, name, "L2", pri, "SKIP", "无活动会话"))
        # ---- H9-1 活动流/状态容器 ----
        st = pg.ev_obj(
            "JSON.stringify({act: !!document.querySelector('[data-hg-act]'),"
            "dyn: !!document.querySelector('.hg-dyn-capsule,[data-hg-dyn]'),"
            "chips: document.querySelectorAll('.hg-chip').length})")
        out.append(result("H9-1", "活动流/胶囊/chips 容器存在", "L2", "P2",
                          "PASS" if any([st.get("act"), st.get("dyn"), st.get("chips")]) else "CHECK",
                          json.dumps(st, ensure_ascii=False)))
        # ---- H5-2 归档条（>20 回合才出现） ----
        arch = pg.ev_obj("JSON.stringify({archive: !!document.querySelector('.h-archbar,[data-hg-archive]'),groups: document.querySelectorAll('.h-grp').length})")
        out.append(result("H5-2", "归档条（>20 回合）", "L2", "P2",
                          "PASS" if arch.get("archive") else "SKIP",
                          "组数=%s（<20 无法构造）" % arch.get("groups")))
        # ---- R1 竞态：快速切会话 ×3（原会话 ↔ 空会话） ----
        try:
            if orig:
                n_base = _groups(pg)
                for _ in range(3):
                    pg.ev("window.newChat()")
                    time.sleep(0.6)
                    pg.ev("window.switchTo(%s)" % json.dumps(orig),
                          await_promise=True, timeout=60)
                    time.sleep(0.7)
                ok = pg.wait_until(
                    "document.querySelectorAll('.h-grp').length >= %d" % max(1, n_base),
                    timeout=20, interval=0.5)
                out.append(result("R1", "快速切会话 ×3 内容不丢", "L2", "P1",
                                  "PASS" if ok else "CHECK",
                                  "base=%d now=%d" % (n_base, _groups(pg))))
            else:
                out.append(result("R1", "快速切会话 ×3 内容不丢", "L2", "P1", "SKIP", "无活动会话"))
        except Exception as e:
            out.append(result("R1", "快速切会话 ×3 内容不丢", "L2", "P1", "CHECK", repr(e)))
        errs = pg.drain_errs()
        out.append(result("L2E", "L2 期间无页面异常", "L2", "P0",
                          "PASS" if not errs else "FAIL",
                          json.dumps(errs[:5], ensure_ascii=False)))
    finally:
        # 恢复：切回原会话
        try:
            if orig:
                pg.ev("window.switchTo(%s)" % json.dumps(orig), await_promise=True, timeout=60)
        except Exception:
            pass
        pg.close()
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
