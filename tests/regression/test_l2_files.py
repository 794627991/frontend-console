# -*- coding: utf-8 -*-
"""L2 文件/终端链路：编辑器(Monaco)、Hex、Diff、终端 shell、树内搜索。

使用 tests/regression/fixtures/ 下的样本文件（不触碰用户文件）。
终端用例会创建一个 cmd 进程，测完立即关闭。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result, filter_known_noise          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_HERE))
FIX = os.path.join(ROOT, "tests", "regression", "fixtures").replace(os.sep, "/")


def _conns(pg):
    return json.loads(pg.ev(
        "JSON.stringify(Object.values(connections).map(c=>({"
        "pid:c.portId,kind:(c.meta&&c.meta.kind)||'',label:(c.meta&&c.meta.label)||'',"
        "monaco:!!c.monaco})))") or "[]")


def _wait_conn(pg, pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        for c in _conns(pg):
            if pred(c):
                return c
        time.sleep(0.4)
    return None


def _close(pg, pid):
    try:
        pg.ev("window.closeConnection && window.closeConnection(%s)" % json.dumps(pid))
    except Exception:
        pass
    time.sleep(0.6)


def run():
    try:
        pg = Page()
    except Exception as e:
        return [result("L2F-ENV", "L2 文件环境", "L2", "P0", "SKIP", "应用未运行: %r" % e)]
    out = []
    try:
        pg.clear_errs()
        n_before = len(_conns(pg))
        # ---- E1-1 打开 txt → Monaco 懒加载 ----
        pg.ev("(async()=>{await window.openFileSmart(%s, 'auto');return 1;})()" % json.dumps(FIX + "/sample.txt"),
              await_promise=True, timeout=60)
        c = _wait_conn(pg, lambda x: "sample.txt" in x["label"])
        monaco_ok = False
        if c:
            monaco_ok = pg.wait_until(
                "Object.values(connections).some(c=>c.meta&&c.meta.label==='sample.txt'&&!!c.monaco)",
                timeout=15, interval=0.5)
        tab_txt = pg.ev("(document.querySelector('#tabs')||{}).textContent||''")
        out.append(result("E1-1", "Monaco 懒加载打开 txt", "L2", "P1",
                          "PASS" if c and monaco_ok else ("CHECK" if c else "FAIL"),
                          "conn=%s monaco=%s tab=%s" % (bool(c), monaco_ok, "sample.txt" in tab_txt)))
        # ---- E1-2 同路径去重 ----
        before = len(_conns(pg))
        pg.ev("(async()=>{await window.openFileSmart(%s, 'auto');return 1;})()" % json.dumps(FIX + "/sample.txt"),
              await_promise=True, timeout=60)
        time.sleep(0.8)
        after = len(_conns(pg))
        out.append(result("E1-2", "同路径编辑器去重", "L2", "P2",
                          "PASS" if after == before else "FAIL",
                          "before=%d after=%d" % (before, after)))
        # ---- E1-3 关闭编辑器 tab（走 closeEditorTab 包装） ----
        c = _wait_conn(pg, lambda x: "sample.txt" in x["label"])
        closed = False
        if c:
            pg.ev("window.closeEditorTab && window.closeEditorTab(%s)" % json.dumps(c["pid"]))
            time.sleep(0.8)
            closed = not any("sample.txt" in x["label"] for x in _conns(pg))
        out.append(result("E1-3", "关闭编辑器 tab", "L2", "P1",
                          "PASS" if closed else "FAIL", "closed=%s" % closed))
        # ---- E1-4 Markdown 打开/关闭 ----
        pg.ev("(async()=>{await window.openFileSmart(%s, 'auto');return 1;})()" % json.dumps(FIX + "/sample.md"),
              await_promise=True, timeout=60)
        c = _wait_conn(pg, lambda x: "sample.md" in x["label"])
        if c:
            pg.wait_until(
                "Object.values(connections).some(c=>c.meta&&c.meta.label==='sample.md'&&!!c.monaco)",
                timeout=15, interval=0.5)
            time.sleep(0.5)
            _close(pg, c["pid"])
        out.append(result("E1-4", "Markdown 文件打开/关闭", "L2", "P2",
                          "PASS" if c else "FAIL", "conn=%s" % bool(c)))
        # ---- O1-3 Hex 打开 ----
        pg.ev("(async()=>{await window.buildHexViewerTab(%s, 'sample.hex');return 1;})()"
              % json.dumps(FIX + "/sample.hex"), await_promise=True, timeout=60)
        c = _wait_conn(pg, lambda x: x["kind"] == "hex", timeout=20)
        hx = pg.ev("document.querySelectorAll('.hx-row,.hx-grid,.hx-body,[class*=hx-]').length") if c else 0
        if c:
            _close(pg, c["pid"])
        out.append(result("O1-3", "Hex 查看器打开（intelHexParse）", "L2", "P2",
                          "PASS" if c else "FAIL", "conn=%s hxDom=%s" % (bool(c), hx)))
        # ---- O1-4 文本 Diff（forceText 跳过模式选择弹窗） ----
        pg.ev("(async()=>{await window.buildDiffViewerTab(%s, %s, true);return 1;})()"
              % (json.dumps(FIX + "/diff_a.txt"), json.dumps(FIX + "/diff_b.txt")),
              await_promise=True, timeout=90)
        c = _wait_conn(pg, lambda x: x["kind"] == "diff", timeout=25)
        diff_dom = pg.ev("(function(){var h=document.querySelector('.diff-holder');return h?h.querySelectorAll('div').length:0;})()") if c else 0
        if c:
            _close(pg, c["pid"])
        out.append(result("O1-4", "文本 Diff 打开/差异渲染", "L2", "P2",
                          "PASS" if c and diff_dom else ("CHECK" if c else "FAIL"),
                          "conn=%s diffDom=%s" % (bool(c), diff_dom)))
        # ---- T1-1 终端：UI 流程建 shell 终端→断言→关闭 ----
        pg.ev("document.querySelector('#btnNewConn').click()")
        time.sleep(0.6)
        pg.ev("document.querySelector('.conn-type-btn[data-type=\"shell\"]').click()")
        time.sleep(0.3)
        pg.ev("var s=document.querySelector('#connShellKind'); if(s){s.value='cmd';}")
        pg.ev("document.querySelector('#connConfirm').click()")
        c = _wait_conn(pg, lambda x: x["kind"] == "shell", timeout=25)
        xterm = pg.ev("document.querySelectorAll('.xterm').length") if c else 0
        if c:
            _close(pg, c["pid"])
        out.append(result("T1-1", "终端 shell 建/渲染/关闭", "L2", "P1",
                          "PASS" if c and xterm else ("CHECK" if c else "FAIL"),
                          "conn=%s xterm=%s" % (bool(c), xterm)))
        # ---- F1-3 树内搜索（对 fixtures 目录） ----
        try:
            pg.ev("(function(){try{window.tsSearchIn(%s);}catch(e){}return 1;})()" % json.dumps(FIX))
            time.sleep(2.0)
            ts = pg.ev("document.querySelectorAll('.ts-res,.ts-hit,.ts-group,[class*=ts-]').length")
            out.append(result("F1-3", "树内搜索调用/结果容器", "L2", "P2",
                              "PASS" if ts else "CHECK", "tsDom=%s" % ts))
            pg.ev("try{window.tsSearchIn('')}catch(e){}")
        except Exception as e:
            out.append(result("F1-3", "树内搜索调用/结果容器", "L2", "P2", "CHECK", repr(e)))
        # ---- 未构造项 SKIP ----
        for cid, name, why in [
                ("F1-2", "树新建/重命名/删除", "写操作需用户指定目录；fixtures 目录不在树根"),
                ("F1-4", "拖拽移动", "拖拽模拟会改变布局"),
                ("O1-10", "Office 预览", "需真实 docx/pdf")]:
            out.append(result(cid, name, "L2", "P2", "SKIP", why))
        # ---- R2 竞态：快速开关编辑器 tab ×3 ----
        try:
            for _ in range(3):
                pg.ev("(async()=>{await window.openFileSmart(%s,'auto');return 1;})()"
                      % json.dumps(FIX + "/sample.txt"), await_promise=True, timeout=60)
                pg.ev("(function(){var c=Object.values(connections).find(c=>c.meta&&c.meta.label==='sample.txt');"
                      "if(c) window.closeEditorTab(c.portId);return 1;})()")
                time.sleep(0.4)
            left = [c for c in _conns(pg) if c["label"] == "sample.txt"]
            out.append(result("R2", "快速开关编辑器 tab ×3 无残留", "L2", "P2",
                              "PASS" if not left else "FAIL",
                              "left=%s" % left))
        except Exception as e:
            out.append(result("R2", "快速开关编辑器 tab ×3 无残留", "L2", "P2", "CHECK", repr(e)))
        errs, noise = filter_known_noise(pg.drain_errs())
        out.append(result("L2FE", "L2 文件链路无页面异常", "L2", "P0",
                          "PASS" if not errs else "FAIL",
                          json.dumps(errs[:5], ensure_ascii=False)
                          + (" [已知噪声 %d 条]" % len(noise) if noise else "")))
        # 清理：关闭本测试新建但未关掉的连接
        for c in _conns(pg)[n_before:]:
            _close(pg, c["pid"])
    finally:
        pg.close()
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
