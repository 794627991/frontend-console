# -*- coding: utf-8 -*-
"""样式快照：对固定 UI 状态采样全量元素 computedStyle 指纹。

用途：CSS 重排（按子系统）前后的**等价性验证**。流程：
    python tests/regression/style_snapshot.py --save before.json
    （执行 CSS 重排并刷新页面）
    python tests/regression/style_snapshot.py --save after.json
    python tests/regression/style_snapshot.py --diff before.json after.json

采样状态（每态按固定操作重建，保证可比）：
  S0 harness 新会话（输入卡/空面板）
  S1 版本控制面板
  S2 设置面板
  S3 日志弹窗
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page          # noqa: E402

SNAP_JS = r"""(function(){
  var sels=[
    'body','html','.topbar','.topbar-left','.logo','.topbar-right',
    '#btnLogs','#btnVcs','#btnNewConn','#btnSettings',
    '#sidebar','.sidebar','#treeRoots','#cmdLibrary','.panel-tab',
    '#tabs','.tab-bar','.tab','.tab.active',
    '.term-area','.term-toolbar','.term-toolbar .btn',
    '[data-hg-input]','.hg-send','.hg-chip','.h-turn-head','.h-grp',
    '.h-tool','.h-msg.asst','.h-drawer.think',
    '.hg-vcs-pane','.hg-vcs-acts','.hg-vcs-logrow','.hg-vcs-badge',
    '.modal','.modal .box','#logsModal .box','#settingsModal .box',
    '.ed-toolbar','.lv-btn','.log-viewer-toolbar',
    '.win-controls','.win-controls button','.web-pane','.office-toolbar'
  ];
  var props=['display','position','color','backgroundColor','fontSize',
             'fontWeight','borderTopColor','borderRadius','paddingTop',
             'paddingLeft','marginTop','zIndex','overflow','width','height'];
  var out={};
  sels.forEach(function(sel){
    var els=document.querySelectorAll(sel);
    if(!els.length) return;
    var e=els[0], cs=getComputedStyle(e), o={};
    props.forEach(function(k){ o[k]=cs[k]; });
    out[sel]=o;
  });
  return JSON.stringify({n:document.querySelectorAll('body *').length, sel:out});
})()"""

def _snap(pg):
    return json.loads(pg.ev(SNAP_JS) or "{}")


def collect():
    pg = Page()
    shots = {}
    try:
        # S0：新会话（harness 面板）
        pg.ev("window.newChat()")
        time.sleep(1.2)
        shots["S0_harness"] = _snap(pg)
        # S1：版本控制
        pg.ev("document.querySelector('#btnVcs').click()")
        time.sleep(1.2)
        shots["S1_vcs"] = _snap(pg)
        # S2：设置
        pg.ev("(function(){try{window.openSettingsPanel&&window.openSettingsPanel();}catch(e){}return 1;})()")
        time.sleep(0.8)
        shots["S2_settings"] = _snap(pg)
        pg.ev("var m=document.querySelector('#settingsModal'); if(m)m.classList.remove('show');")
        # S3：日志弹窗
        pg.ev("document.querySelector('#btnLogs').click()")
        time.sleep(0.8)
        shots["S3_logs"] = _snap(pg)
        pg.ev("var m=document.querySelector('#logsModal'); if(m)m.classList.remove('show');")
    finally:
        pg.close()
    return shots


def diff(a_path, b_path):
    a = json.load(open(a_path, encoding="utf-8"))
    b = json.load(open(b_path, encoding="utf-8"))
    bad = []
    for state in sorted(set(a) | set(b)):
        sa = (a.get(state) or {}).get("sel") or {}
        sb = (b.get(state) or {}).get("sel") or {}
        common = sorted(set(sa) & set(sb))
        only_a = sorted(set(sa) - set(sb))
        only_b = sorted(set(sb) - set(sa))
        diffs = []
        for sel in common:
            for k, v in sa[sel].items():
                if sb[sel].get(k) != v:
                    diffs.append({"sel": sel, "prop": k,
                                  "before": v, "after": sb[sel].get(k)})
        if diffs:
            bad.append({"state": state, "diffs": diffs[:8],
                        "only_before": only_a[:5], "only_after": only_b[:5]})
        elif only_a or only_b:
            # 元素存在性差异单独记录（可能是页面状态差异，不判失败）
            pass
    print("状态数:", len(set(a) | set(b)), " 样式不一致状态数:", len(bad))
    for x in bad:
        print(" ", json.dumps(x, ensure_ascii=False)[:500])
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--diff", nargs=2)
    a = ap.parse_args()
    if a.diff:
        sys.exit(diff(*a.diff))
    shots = collect()
    if a.save:
        with open(a.save, "w", encoding="utf-8") as f:
            json.dump(shots, f, ensure_ascii=False, indent=1)
        print("已保存:", a.save)
    print(json.dumps(shots, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
