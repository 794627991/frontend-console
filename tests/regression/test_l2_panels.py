# -*- coding: utf-8 -*-
"""L2 非 Harness 面板：CDP DOM 驱动、零 CLI 额度。

只做「打开-断言-关闭」型操作；不修改用户数据、不发起网络安装。
无法自动构造的用例以 SKIP 记录（原因 + 手工步骤见用例明细文档）。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page, result          # noqa: E402


def run():
    try:
        pg = Page()
    except Exception as e:
        return [result("L2P-ENV", "L2 面板环境", "L2", "P0", "SKIP", "应用未运行: %r" % e)]
    out = []
    try:
        pg.clear_errs()
        # ---- O1-2 日志弹窗打开/关闭 ----
        pg.ev("document.querySelector('#btnLogs') && document.querySelector('#btnLogs').click()")
        time.sleep(0.6)
        opened = pg.ev("!!document.querySelector('#logsModal.show, #logsModal[style*=block]')")
        listed = pg.ev("(document.querySelector('#logsList')||{}).children.length || 0")
        pg.ev("var c=document.querySelector('#logsClose'); if(c)c.click();"
              "document.querySelector('#logsModal').classList.remove('show')")
        time.sleep(0.3)
        closed = not pg.ev("!!document.querySelector('#logsModal.show')")
        out.append(result("O1-2", "日志弹窗打开/列表/关闭", "L2", "P1",
                          "PASS" if opened and closed else "FAIL",
                          "opened=%s listed=%s closed=%s" % (opened, listed, closed)))
        # ---- O1-1 日志查看器（依赖真实日志条目） ----
        out.append(result("O1-1", "日志查看器渲染/滚动/搜索", "L2", "P2", "SKIP",
                          "需真实日志文件与条目点击，见文档手工步骤"))
        # ---- O1-6 命令库面板默认渲染 ----
        cmd = pg.ev("(document.querySelector('#cmdLibrary')||{}).children.length || 0")
        out.append(result("O1-6", "命令库面板渲染", "L2", "P2",
                          "PASS" if cmd > 0 else "CHECK", "子节点=%s" % cmd))
        # ---- F1-1 文件树根节点渲染 ----
        roots = pg.ev("(document.querySelector('#treeRoots')||{}).children.length || 0")
        out.append(result("F1-1", "文件树根节点渲染", "L2", "P1",
                          "PASS" if roots > 0 else "CHECK", "根节点=%s" % roots))
        # ---- O1-9 窗口控制按钮存在 ----
        wins = pg.ev("document.querySelectorAll('.win-controls button, .win-controls .wc-btn').length")
        out.append(result("O1-9", "窗口控制按钮存在", "L2", "P2",
                          "PASS" if wins > 0 else "CHECK", "按钮=%s" % wins))
        # ---- O1-11 笔记/导航/技能关键挂载 ----
        mounts = pg.ev_obj(
            "JSON.stringify({nnExportMd: typeof window.nnExportMd,"
            " nnBindWikiClick: typeof window.nnBindWikiClick,"
            " NavJump: typeof window.NavJump,"
            " skills: typeof (window.HgSkills||window._hgSkills)})")
        ok = mounts.get("nnExportMd") in ("function", "object")
        out.append(result("O1-11", "笔记/导航挂载可达", "L2", "P2",
                          "PASS" if ok else "CHECK", json.dumps(mounts, ensure_ascii=False)))
        # ---- O1-7 设置面板打开/关闭（不切换主题） ----
        theme_before = pg.ev("document.documentElement.getAttribute('data-theme')||''")
        pg.ev("(function(){try{window.openSettingsPanel&&window.openSettingsPanel();}catch(e){}return 1;})()")
        time.sleep(0.8)
        set_open = pg.ev("!!document.querySelector('#settingsModal.show, #settingsModal[style*=\"block\"]')")
        pg.ev("var sm=document.querySelector('#settingsModal'); if(sm) sm.classList.remove('show');")
        theme_after = pg.ev("document.documentElement.getAttribute('data-theme')||''")
        out.append(result("O1-7", "设置面板打开/关闭（主题不变）", "L2", "P2",
                          "PASS" if set_open and theme_before == theme_after else "CHECK",
                          "open=%s theme=%s→%s" % (set_open, theme_before, theme_after)))
        # ---- O1-5 代理面板（buildProxyTab 单例） ----
        pg.ev("(function(){try{window.buildProxyTab&&window.buildProxyTab();}catch(e){}return 1;})()")
        time.sleep(1.0)
        proxy = json.loads(pg.ev(
            "JSON.stringify(Object.values(connections).filter(c=>c.meta&&c.meta.kind==='proxy')"
            ".map(c=>({pid:c.portId,dom:(c.wrap||document).querySelectorAll('*').length})))") or "[]")
        for c in proxy:
            try:
                pg.ev("window.closeConnection(%s)" % json.dumps(c["pid"]))
            except Exception:
                pass
        out.append(result("O1-5", "代理面板建/渲染/关闭", "L2", "P2",
                          "PASS" if proxy and proxy[0].get("dom", 0) > 50 else
                          ("CHECK" if proxy else "FAIL"),
                          json.dumps(proxy[:1], ensure_ascii=False)))
        # ---- O1-1 日志查看器（点条目→渲染→关闭） ----
        pg.ev("document.querySelector('#btnLogs') && document.querySelector('#btnLogs').click()")
        time.sleep(0.8)
        has_item = pg.ev("document.querySelectorAll('#logsList [data-view]').length")
        lv = None
        if has_item:
            pg.ev("document.querySelector('#logsList [data-view]').click()")
            end = time.time() + 15
            while time.time() < end:
                lv = json.loads(pg.ev(
                    "JSON.stringify(Object.values(connections).filter(c=>c.meta&&c.meta.kind==='log')"
                    ".map(c=>({pid:c.portId,dom:(c.wrap||document).querySelectorAll('*').length})))") or "[]")
                if lv:
                    break
                time.sleep(0.5)
            if lv:
                try:
                    pg.ev("window.closeConnection(%s)" % json.dumps(lv[0]["pid"]))
                except Exception:
                    pass
        out.append(result("O1-1", "日志查看器条目渲染/关闭", "L2", "P2",
                          "PASS" if lv and lv[0].get("dom", 0) > 50 else
                          ("SKIP" if not has_item else "CHECK"),
                          ("条目=%s " % has_item) + (json.dumps(lv[:1], ensure_ascii=False) if lv else "")))
        # ---- R3 竞态：快速开关日志弹窗 ×3 ----
        try:
            for _ in range(3):
                pg.ev("document.querySelector('#btnLogs').click()")
                time.sleep(0.15)
                pg.ev("var m=document.querySelector('#logsModal'); if(m) m.classList.remove('show');")
                time.sleep(0.15)
            r3_errs = pg.drain_errs()
            out.append(result("R3", "快速开关日志弹窗 ×3", "L2", "P2",
                              "PASS" if not r3_errs else "CHECK",
                              json.dumps(r3_errs[:3], ensure_ascii=False)))
        except Exception as e:
            out.append(result("R3", "快速开关日志弹窗 ×3", "L2", "P2", "CHECK", repr(e)))
        # ---- 其余需真实环境的用例：记录 SKIP ----
        skips = [
            ("T1-2", "终端搜索/历史回放", "需终端输出内容"),
            ("T1-3", "截图链路（snip）", "需桌面截图窗口交互"),
            ("F1-2", "文件树新建/重命名/删除", "写操作，需用户指定测试目录"),
            ("F1-4", "拖拽移动", "需真实文件与拖拽模拟"),
            ("N1-1", "网页 tab 打开/切换/控件显隐", "需真实网页导航（网络）"),
            ("N1-2", "关闭网页 tab 控件释放", "需已打开网页 tab"),
            ("N1-3", "网页 tab 休眠/唤醒", "需已打开网页 tab"),
            ("O1-8", "侧栏/标签拖拽", "拖拽模拟会改变用户布局"),
            ("O1-10", "Office/Markdown 预览", "需真实 docx/pdf/md 文件"),
        ]
        for cid, name, why in skips:
            out.append(result(cid, name, "L2", "P2", "SKIP", why))
        errs = pg.drain_errs()
        out.append(result("L2PE", "L2 面板期间无页面异常", "L2", "P0",
                          "PASS" if not errs else "FAIL",
                          json.dumps(errs[:5], ensure_ascii=False)))
    finally:
        pg.close()
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
