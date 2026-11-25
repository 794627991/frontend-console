# -*- coding: utf-8 -*-
"""渲染路径测绘（3.1）：只打点、不改产品代码。

通过 CDP 在运行中的应用里包装渲染入口（window 属性赋值会被 v4bridge 的
`_g` / 跨模块裸引用实时解析到），跑一段真实会话，统计每类行实际调用的
渲染原语、次数与耗时。产出 docs/render-path-audit.md（数据表）。

⚠ 消耗 1-2 条 Claude CLI 额度；用户要求时手动执行：
    python tests/regression/render_audit.py
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cdp_lib import Page          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(_HERE))
OUT = os.path.join(ROOT, "tests", "regression", "artifacts", "渲染路径测绘.md")

INJECT = r"""
(function () {
  if (window.__auditWrapped) return 'already';
  window.__auditWrapped = 1;
  window.__auditStats = {};
  function wrap(name) {
    var orig = window[name];
    if (typeof orig !== 'function') return;
    window[name] = function () {
      var t0 = performance.now();
      var ok = false;
      try {
        var r = orig.apply(this, arguments);
        ok = true;
        return r;
      } finally {
        var d = performance.now() - t0;
        var st = window.__auditStats[name] ||
          (window.__auditStats[name] = { calls: 0, ms: 0, max: 0, err: 0 });
        st.calls++; st.ms += d; if (d > st.max) st.max = d;
        if (!ok) st.err++;
      }
    };
  }
  ['_hgRowAdd', 'renderToolUse', 'renderOneToolResult', 'renderHistLine',
   'renderAsst', 'appendThinking', 'startThinking', 'endThinking',
   '_histRender', 'renderUser'].forEach(wrap);
  return 'wrapped';
})()
"""


def _stats(pg):
    return json.loads(pg.ev("JSON.stringify(window.__auditStats || {})") or "{}")


def main():
    pg = Page()
    orig = None
    try:
        orig = pg.ev("(window._HG&&window._HG.sid)||null")
        print('注入:', pg.ev(INJECT))
        pg.ev("window.newChat()")
        time.sleep(0.8)
        # 一条含思考/工具/正文的消息，覆盖主要渲染路径
        pg.ev("(async()=>{var el=window._hgInput;"
              "el.value='用 Bash 执行 echo hi，然后简短回复 done';"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "await window.send();return 1;})()",
              await_promise=True, timeout=90)
        end = time.time() + 150
        while time.time() < end:
            time.sleep(2)
            if not pg.ev("!!(window._HG&&window._HG.busy)"):
                time.sleep(1.5)
                break
        st = _stats(pg)
        dom = pg.ev_obj(
            "JSON.stringify({grps:document.querySelectorAll('.h-grp').length,"
            "asst:document.querySelectorAll('.h-msg.asst').length,"
            "tools:document.querySelectorAll('.h-tool').length,"
            "think:document.querySelectorAll('.h-drawer.think').length,"
            "nodes:document.querySelectorAll('[data-hg-flow] *').length})")
        lines = ["# 渲染路径测绘（真实会话）", "",
                 "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"), "",
                 "## DOM 规模", "", "| 项 | 数量 |", "|---|---|"]
        for k, v in dom.items():
            lines.append("| %s | %s |" % (k, v))
        lines += ["", "## 渲染原语调用统计", "",
                  "| 原语 | 调用次数 | 总耗时 ms | 单次最大 ms | 异常 |",
                  "|---|---|---|---|---|"]
        for name, s in sorted(st.items(), key=lambda x: -x[1]["calls"]):
            lines.append("| %s | %d | %.1f | %.2f | %d |" %
                         (name, s["calls"], s["ms"], s["max"], s.get("err", 0)))
        total_calls = sum(s["calls"] for s in st.values())
        total_ms = sum(s["ms"] for s in st.values())
        lines += ["", "**合计**: %d 次调用 / %.1f ms" % (total_calls, total_ms), "",
                  "## 读法", "",
                  "- 调用次数与 DOM 规模的比值 = 每个渲染原语的生产率；",
                  "- 单次最大耗时 > 50ms 的原语 = 长任务候选（与流式卡顿相关）；",
                  "- `_hgRowAdd`/`renderHistLine` 的次数高 = 历史账本管线占比高；",
                  "- 本表是「是否值得合并渲染层」的决策依据：没有数据不重写。"]
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("写入:", OUT)
        print(json.dumps(st, ensure_ascii=False, indent=1)[:1500])
    finally:
        try:
            if orig:
                pg.ev("window.switchTo(%s)" % json.dumps(orig),
                      await_promise=True, timeout=60)
        except Exception:
            pass
        pg.close()


if __name__ == "__main__":
    main()
