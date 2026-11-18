# -*- coding: utf-8 -*-
"""L2 版本控制面板（vcs-panel / vcs-git-ops，a650 新功能）。

只读安全策略：仅打开面板/历史/分支/Stash/标签对话框并断言渲染，**绝不点击
任何写操作按钮**（创建/删除/切换/应用/丢弃）。测试结束关闭所有弹窗。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result          # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE)).replace(os.sep, "/")


def _vcs_conn(pg):
    return json.loads(pg.ev(
        "JSON.stringify(Object.values(connections)"
        ".filter(c=>c.meta&&c.meta.kind==='vcs').map(c=>({pid:c.portId})))") or "[]")


def _dlg_open(pg):
    return pg.ev("!!document.querySelector('.hg-vcs-rdlg')")


def _dlg_body_nodes(pg):
    return pg.ev("(function(){var b=document.querySelector('.hg-vcs-rdlg .hg-vcs-rdlg-body');"
                 "return b?b.querySelectorAll('*').length:0;})()")


def _close_dlg(pg):
    pg.ev("(function(){var x=document.querySelector('.hg-vcs-rdlg [name=\"dlg_close\"]');"
          "if(x)x.click();return 1;})()")
    time.sleep(0.3)


def run():
    try:
        pg = Page()
    except Exception as e:
        return [result("VCS-ENV", "VCS 环境", "L2", "P0", "SKIP", "应用未运行: %r" % e)]
    out = []
    try:
        pg.clear_errs()
        # ---- VCS-1 打开面板（单例） ----
        pg.ev("document.querySelector('#btnVcs').click()")
        time.sleep(1.0)
        c1 = _vcs_conn(pg)
        conns_before = len(json.loads(pg.ev(
            "JSON.stringify(Object.keys(connections))") or "[]"))
        pg.ev("document.querySelector('#btnVcs').click()")
        time.sleep(0.5)
        conns_after = len(json.loads(pg.ev(
            "JSON.stringify(Object.keys(connections))") or "[]"))
        pane = pg.ev("document.querySelectorAll('[data-vcs-root] *').length")
        out.append(result("VCS-1", "面板打开/单例/骨架渲染", "L2", "P0",
                          "PASS" if c1 and conns_before == conns_after and pane > 0 else "FAIL",
                          "conn=%s paneNodes=%s 单例=%s" % (bool(c1), pane, conns_before == conns_after)))
        # ---- VCS-2 工程状态（若无 root 则显式设置项目根） ----
        info = pg.ev_obj(
            "JSON.stringify({root:(window.VCS&&VCS.root)||'',"
            "vcs:(window.VCS&&VCS.data&&VCS.data.vcs)||'',"
            "branch:(window.VCS&&VCS.data&&VCS.data.branch)||'',"
            "files:((window.VCS&&VCS.data&&VCS.data.files)||[]).length})")
        if not info.get("root"):
            try:
                pg.ev("(function(){window.VCS.root=%s;"
                      "if(typeof _vcsActivate==='function')_vcsActivate(true);return 1;})()"
                      % json.dumps(PROJECT_ROOT))
                pg.wait_until("!!(window.VCS&&VCS.data)", timeout=12, interval=0.5)
                info = pg.ev_obj(
                    "JSON.stringify({root:(window.VCS&&VCS.root)||'',"
                    "vcs:(window.VCS&&VCS.data&&VCS.data.vcs)||'',"
                    "branch:(window.VCS&&VCS.data&&VCS.data.branch)||'',"
                    "files:((window.VCS&&VCS.data&&VCS.data.files)||[]).length})")
            except Exception:
                pass
        # 状态区渲染（有 root 时才可能非空）
        state_dom = pg.ev("document.querySelectorAll('[data-vcs-root] .hg-vcs-item,"
                          "[data-vcs-root] .hg-vcs-file, [data-vcs-root] .hg-vcs-sec,"
                          "[data-vcs-root] .hg-vcs-acts button').length")
        ok = bool(info.get("root")) and state_dom > 0
        out.append(result("VCS-2", "工程状态/改动列表渲染", "L2", "P1",
                          "PASS" if ok else "CHECK",
                          "root=%s vcs=%s branch=%s files=%s dom=%s" % (
                              (info.get("root") or "")[-30:], info.get("vcs"),
                              info.get("branch"), info.get("files"), state_dom)))
        # 状态自愈：全量运行时前面的测试可能让面板/工程状态未激活——
        # 等 data 就绪，必要时重新激活一次再继续。
        pg.wait_until("!!(window.VCS&&VCS.data&&VCS.data.vcs)", timeout=10, interval=0.5)
        if not pg.ev("!!(window.VCS&&VCS.data&&VCS.data.vcs)"):
            pg.ev("(function(){try{if(typeof _vcsActivate==='function')_vcsActivate(true);"
                  "else if(typeof _vcsReload==='function')_vcsReload();}catch(e){}return 1;})()")
            pg.wait_until("!!(window.VCS&&VCS.data&&VCS.data.vcs)", timeout=15, interval=0.5)

        # ---- VCS-10 主缓存刷新 + 图形模式不污染 VCS.log ----
        # 审计修正：图形按钮只存在于 _vcsHistOpen 创建的弹窗内——旧实现
        # 在弹窗未开时点击（空转）再比较同一份未变化缓存，属自证 PASS。
        try:
            pg.ev("(function(){if(typeof _vcsHistOpen==='function')_vcsHistOpen();return 1;})()")
            graph_ok = pg.wait_until(
                "!!document.querySelector('[data-vcs-graph]')", timeout=10, interval=0.4)
            pg.wait_until(
                "(function(){return ((window.VCS&&VCS.log)||[]).length>0;})()",
                timeout=15, interval=0.5)
            base = pg.ev_obj(
                "JSON.stringify({first:((window.VCS.log||[])[0]||{}).rev||'',"
                "deco:((window.VCS.log||[])[0]||{}).deco||'',"
                "len:((window.VCS.log||[]).length)})")
            if not graph_ok:
                out.append(result("VCS-10", "图形模式不污染主缓存（首行/装饰）", "L2", "P0",
                                  "FAIL", "历史弹窗/图形按钮不可用（未真正执行切换）"))
            else:
                pg.ev("(function(){document.querySelector('[data-vcs-graph]').click();return 1;})()")
                time.sleep(2.0)
                on = bool(pg.ev("!!document.querySelector('[data-vcs-graph].on')"))
                pg.ev("(function(){var b=document.querySelector('[data-vcs-graph]');"
                      "if(b&&b.classList.contains('on'))b.click();return 1;})()")
                time.sleep(2.0)
                after = pg.ev_obj(
                    "JSON.stringify({first:((window.VCS.log||[])[0]||{}).rev||'',"
                    "deco:((window.VCS.log||[])[0]||{}).deco||'',"
                    "len:((window.VCS.log||[]).length)})")
                ok = (on and base.get("first") and after.get("first") == base.get("first")
                      and after.get("deco") and after.get("len", 0) >= 1)
                out.append(result("VCS-10", "图形模式不污染主缓存（首行/装饰）", "L2", "P0",
                                  "PASS" if ok else "FAIL",
                                  "on=%s base=%s after=%s" % (
                                      on, json.dumps(base, ensure_ascii=False),
                                      json.dumps(after, ensure_ascii=False))))
            pg.ev("(function(){var b=document.querySelector('[data-vcs-hclose]');"
                  "if(b)b.click();return 1;})()")
            time.sleep(0.5)
        except Exception as e:
            out.append(result("VCS-10", "图形模式不污染主缓存（首行/装饰）", "L2", "P0", "CHECK", repr(e)))
            try:
                pg.ev("(function(){var b=document.querySelector('[data-vcs-hclose]');"
                      "if(b)b.click();return 1;})()")
            except Exception:
                pass

        # ---- VCS-3 提交历史弹窗（列表/搜索/图形/详情） ----
        if not pg.ev("!!(window.VCS&&VCS.data&&VCS.data.vcs)"):
            pg.ev("(function(){try{if(typeof _vcsActivate==='function')_vcsActivate(true);"
                  "else if(typeof _vcsReload==='function')_vcsReload();}catch(e){}return 1;})()")
            pg.wait_until("!!(window.VCS&&VCS.data&&VCS.data.vcs)", timeout=15, interval=0.5)
        pg.ev("(function(){if(typeof _vcsHistOpen==='function')_vcsHistOpen();return 1;})()")
        time.sleep(1.0)
        hist = None
        for _ in range(10):
            hist = pg.ev_obj(
                "JSON.stringify({open:!!document.querySelector('[data-vcs-hlist]'),"
                "rows:document.querySelectorAll('[data-vcs-hlist] > *').length,"
                "search:!!document.querySelector('[data-vcs-hq=\"text\"]'),"
                "graph:!!document.querySelector('[data-vcs-graph]'),"
                "deco:document.querySelectorAll('.hg-vcs-decoic, .hg-vcs-deco').length,"
                "detail:!!document.querySelector('[data-vcs-hdetail]')})")
            if hist and hist.get("rows"):
                break
            time.sleep(0.8)
        out.append(result("VCS-3", "提交历史弹窗（列表/搜索/图形/HEAD 装饰/详情）", "L2", "P1",
                          "PASS" if hist and hist.get("open") and hist.get("rows")
                          and hist.get("deco", 0) > 0 else
                          ("CHECK" if hist and hist.get("open") else "FAIL"),
                          json.dumps(hist, ensure_ascii=False)))
        # ---- VCS-3a 图形模式（--graph） ----
        try:
            pg.ev("(function(){document.querySelector('[data-vcs-graph]').click();return 1;})()")
            time.sleep(2.0)
            g = pg.ev_obj(
                "JSON.stringify({on:!!document.querySelector('[data-vcs-graph].on'),"
                "rows:document.querySelectorAll('[data-vcs-hlist] > *').length,"
                "graphCells:document.querySelectorAll('.hg-vcs-graph').length})")
            pg.ev("(function(){var b=document.querySelector('[data-vcs-graph]');"
                  "if(b&&b.classList.contains('on'))b.click();return 1;})()")
            time.sleep(1.2)
            out.append(result("VCS-3a", "图形视图（分叉/合并）", "L2", "P2",
                              "PASS" if g.get("on") and g.get("graphCells", 0) > 0 else "CHECK",
                              json.dumps(g, ensure_ascii=False)))
        except Exception as e:
            out.append(result("VCS-3a", "图形视图（分叉/合并）", "L2", "P2", "CHECK", repr(e)))
        # ---- VCS-3b 关键字筛选 ----
        try:
            first_before = pg.ev(
                "(function(){var r=document.querySelector('[data-vcs-hlist] .hg-vcs-logrev');"
                "return r?r.textContent.trim():'';})()")
            kw = pg.ev(
                "(function(){var m=((window.VCS&&VCS.log&&VCS.log[0]&&VCS.log[0].msg)||'');"
                "var x=String(m).match(/[A-Za-z0-9_]{4,}/);return x?x[0]:'';})()")
            if not kw:
                out.append(result("VCS-3b", "关键字筛选提交", "L2", "P2", "SKIP",
                                  "当前 HEAD 提交消息无可提取关键词"))
                raise RuntimeError("skip-filter")
            pg.ev("(function(){var i=document.querySelector('[data-vcs-hq=\"text\"]');"
                  "i.value=%s;i.dispatchEvent(new Event('input',{bubbles:true}));return 1;})()"
                  % json.dumps(kw))
            q = None
            for _ in range(8):
                time.sleep(0.8)
                q = pg.ev_obj(
                    "JSON.stringify({rows:document.querySelectorAll('[data-vcs-hlist] .hg-vcs-hlrow').length,"
                    "first:(function(){var r=document.querySelector('[data-vcs-hlist] .hg-vcs-logrev');"
                    "return r?r.textContent.trim():'';})(),"
                    "clear:!!document.querySelector('[data-vcs-hclear]')})")
                if q.get("rows") and q.get("first"):
                    break
            pg.ev("(function(){var i=document.querySelector('[data-vcs-hq=\"text\"]');"
                  "i.value='';i.dispatchEvent(new Event('input',{bubbles:true}));return 1;})()")
            time.sleep(1.5)
            hit = bool(q) and q.get("rows", 0) >= 1 and bool(q.get("first"))
            out.append(result("VCS-3b", "关键字筛选提交", "L2", "P2",
                              "PASS" if hit else "CHECK",
                              json.dumps(q, ensure_ascii=False) + " before=" + str(first_before)))
        except RuntimeError:
            pass   # SKIP 已在 try 内登记
        except Exception as e:
            out.append(result("VCS-3b", "关键字筛选提交", "L2", "P2", "CHECK", repr(e)))
        # ---- VCS-3c 点提交行 → 详情 ----
        try:
            rows = pg.ev("document.querySelectorAll('[data-vcs-hlist] > *').length")
            if rows:
                pg.ev("(function(){var r=document.querySelector('[data-vcs-hlist] > *');"
                      "r.click();return 1;})()")
                time.sleep(2.0)
                d = None
                for _ in range(8):
                    time.sleep(0.8)
                    d = pg.ev_obj(
                        "JSON.stringify({nodes:(function(){var e=document.querySelector('[data-vcs-hdetail]');"
                        "return e?e.querySelectorAll('*').length:0;})(),"
                        "files:document.querySelectorAll('[data-vcs-hdetail] .hg-vcs-cfrow').length,"
                        "meta:!!document.querySelector('[data-vcs-hdetail] .hg-vcs-hmeta')})")
                    if d.get("files"):
                        break
                out.append(result("VCS-3c", "点提交行→详情渲染", "L2", "P2",
                                  "PASS" if d and d.get("files", 0) > 0 else "CHECK",
                                  json.dumps(d, ensure_ascii=False)))
            else:
                out.append(result("VCS-3c", "点提交行→详情渲染", "L2", "P2", "SKIP", "无提交行"))
        except Exception as e:
            out.append(result("VCS-3c", "点提交行→详情渲染", "L2", "P2", "CHECK", repr(e)))
        # ---- VCS-3d 下一页 ----
        try:
            rev0 = pg.ev(
                "(function(){var r=document.querySelector('[data-vcs-hlist] .hg-vcs-logrev');"
                "return r?r.textContent.trim():'';})()")
            pg.ev("(function(){var b=document.querySelector('[data-vcs-hnext]');"
                  "if(b&&!b.disabled)b.click();return 1;})()")
            time.sleep(2.0)
            rev1 = pg.ev(
                "(function(){var r=document.querySelector('[data-vcs-hlist] .hg-vcs-logrev');"
                "return r?r.textContent.trim():'';})()")
            out.append(result("VCS-3d", "历史翻页（下一页）", "L2", "P2",
                              "PASS" if rev0 and rev1 and rev0 != rev1 else "CHECK",
                              "rev %s → %s" % (rev0, rev1)))
        except Exception as e:
            out.append(result("VCS-3d", "历史翻页（下一页）", "L2", "P2", "CHECK", repr(e)))
        pg.ev("(function(){var b=document.querySelector('[data-vcs-hclose]');"
              "if(b)b.click();return 1;})()")
        time.sleep(0.4)
        hist_closed = not pg.ev("!!document.querySelector('[data-vcs-hlist]')")
        out.append(result("VCS-3e", "历史弹窗关闭", "L2", "P1",
                          "PASS" if hist_closed else "FAIL", "closed=%s" % hist_closed))
        # ---- VCS-9 内嵌最近提交 + 点行展开文件清单 ----
        try:
            inline = pg.ev("document.querySelectorAll('[data-vcs-root] .hg-vcs-logrow').length")
            exp = None
            if inline:
                pg.ev("(function(){var r=document.querySelector('[data-vcs-root] .hg-vcs-logrow');"
                      "r.click();return 1;})()")
                time.sleep(1.8)
                exp = pg.ev_obj(
                    "JSON.stringify({rows:document.querySelectorAll('[data-vcs-root] .hg-vcs-logrow').length,"
                    "files:(function(){var e=document.querySelector('[data-vcsfiles]');"
                    "return e?e.querySelectorAll('*').length:0;})()})")
            out.append(result("VCS-9", "内嵌最近提交/点行展开文件", "L2", "P2",
                              "PASS" if inline and exp and exp.get("files", 0) > 0 else
                              ("SKIP" if not inline else "CHECK"),
                              "rows=%s %s" % (inline, json.dumps(exp, ensure_ascii=False) if exp else "")))
        except Exception as e:
            out.append(result("VCS-9", "内嵌最近提交/点行展开文件", "L2", "P2", "CHECK", repr(e)))
        # ---- VCS-4/5/6 分支 / Stash / 标签对话框（只读打开+渲染+关闭） ----
        for cid, fn, name in [("VCS-4", "_vcsBranchDialog", "分支对话框"),
                              ("VCS-5", "_vcsStashDialog", "Stash 对话框"),
                              ("VCS-6", "_vcsTagsDialog", "标签对话框")]:
            try:
                pg.ev("(function(){if(typeof %s==='function')%s();return 1;})()" % (fn, fn))
                time.sleep(1.2)
                opened = _dlg_open(pg)
                nodes = _dlg_body_nodes(pg)
                _close_dlg(pg)
                closed = not _dlg_open(pg)
                out.append(result(cid, name + "（打开/渲染/关闭）", "L2", "P1",
                                  "PASS" if opened and nodes > 0 and closed else
                                  ("CHECK" if opened else "FAIL"),
                                  "open=%s nodes=%s closed=%s" % (opened, nodes, closed)))
            except Exception as e:
                out.append(result(cid, name, "L2", "P1", "CHECK", repr(e)))
        # ---- VCS-7 竞态：快速开关历史弹窗 ×3 ----
        try:
            for _ in range(3):
                pg.ev("(function(){if(typeof _vcsHistOpen==='function')_vcsHistOpen();return 1;})()")
                time.sleep(0.25)
                pg.ev("(function(){if(typeof _vcsHistClose==='function')_vcsHistClose();return 1;})()")
                time.sleep(0.25)
            residual = pg.ev("document.querySelectorAll('[data-vcs-hlist]').length")
            out.append(result("VCS-7", "快速开关历史弹窗 ×3 无残留", "L2", "P2",
                              "PASS" if residual == 0 else "FAIL", "残留=%s" % residual))
        except Exception as e:
            out.append(result("VCS-7", "快速开关历史弹窗 ×3 无残留", "L2", "P2", "CHECK", repr(e)))
        # ---- VCS-8 安全：无写操作痕迹 ----
        safe = pg.ev_obj(
            "JSON.stringify({busy:!!(window.VCS&&VCS.busy), out:String((window.VCS&&VCS.out)||'')})")
        out.append(result("VCS-8", "只读测试无写操作痕迹", "L2", "P0",
                          "PASS" if not safe.get("busy") else "CHECK",
                          json.dumps(safe, ensure_ascii=False)[:160]))
        errs = pg.drain_errs()
        out.append(result("VCS-E", "VCS 测试期间无页面异常", "L2", "P0",
                          "PASS" if not errs else "FAIL",
                          json.dumps(errs[:5], ensure_ascii=False)))
    finally:
        # 清理：关闭弹窗（面板保留——用户原本可能就开着，不主动关 tab）
        try:
            pg.ev("(function(){var d=document.querySelector('.hg-vcs-rdlg [name=\"dlg_close\"]');"
                  "if(d)d.click();if(typeof _vcsHistClose==='function')_vcsHistClose();return 1;})()")
        except Exception:
            pass
        pg.close()
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
