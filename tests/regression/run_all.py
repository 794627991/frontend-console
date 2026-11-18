# -*- coding: utf-8 -*-
"""模块化回归测试统一入口。

    python tests/regression/run_all.py                       # L0-L2
    python tests/regression/run_all.py --layers L0,L1,L2     # 指定层
    python tests/regression/run_all.py --layers L3 --groups H1,H3,H4   # 真实 CLI（耗额度）

结果自动追加到 docs/modularization-regression/测试报告.md。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
REPORT = os.path.join(ROOT, "docs", "modularization-regression", "测试报告.md")
sys.path.insert(0, _HERE)


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "?"


def _hg_ver():
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=2) as r:
            targets = json.load(r)
        # 版本从页面取
        from cdp_lib import Page
        pg = Page()
        try:
            return pg.ev("window._HG_VER || ''")
        finally:
            pg.close()
    except Exception:
        return ""


def _run_layer(layer, groups):
    if layer == "L0":
        import test_l0_static
        return test_l0_static.run()
    if layer == "L1":
        import test_l1_boot
        return test_l1_boot.run()
    if layer == "L2":
        import test_l2_harness
        import test_l2_panels
        import test_l2_files
        import test_l2_vcs
        import test_l2_extra
        return (test_l2_harness.run() + test_l2_panels.run()
                + test_l2_files.run() + test_l2_vcs.run()
                + test_l2_extra.run())
    if layer == "L3":
        import test_l3_harness
        return test_l3_harness.run(groups)
    return []


def _append_report(rows_by_layer, meta):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    lines = []
    lines.append("\n---\n")
    lines.append("## 执行记录 %s\n" % meta["time"])
    lines.append("- HEAD: `%s`  _HG_VER: `%s`  层: %s%s\n" % (
        meta["head"], meta["ver"], ",".join(meta["layers"]),
        ("  组: " + ",".join(meta["groups"])) if meta["groups"] else ""))
    total = {"PASS": 0, "FAIL": 0, "SKIP": 0, "CHECK": 0}
    for layer, rows in rows_by_layer.items():
        lines.append("\n### %s\n" % layer)
        lines.append("| ID | 用例 | 结果 | 详情 |")
        lines.append("|---|---|---|---|")
        for r in rows:
            total[r["status"]] = total.get(r["status"], 0) + 1
            detail = str(r.get("detail", "")).replace("|", "\\|")[:220]
            lines.append("| %s | %s | **%s** | %s |" %
                         (r["id"], r["name"], r["status"], detail))
    lines.append("\n**合计**: PASS=%d FAIL=%d SKIP=%d CHECK=%d\n" % (
        total.get("PASS", 0), total.get("FAIL", 0),
        total.get("SKIP", 0), total.get("CHECK", 0)))
    with open(REPORT, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layers", default="L0,L1,L2")
    ap.add_argument("--groups", default="")
    ap.add_argument("--smoke", action="store_true",
                    help="真机冒烟（= L3 SMOKE 组，1 条消息；仅用户主动发起）")
    ap.add_argument("--no-report", action="store_true")
    a = ap.parse_args()
    layers = [x.strip().upper() for x in a.layers.split(",") if x.strip()]
    groups = [x.strip().upper() for x in a.groups.split(",") if x.strip()] or None
    if a.smoke:
        # 冒烟只在用户显式发起时执行（不挂 git hook，避免日常提交烧额度）
        layers = ["L3"]
        groups = ["SMOKE"]
    rows_by_layer = {}
    for layer in layers:
        print("\n===== %s =====" % layer)
        try:
            rows = _run_layer(layer, groups)
        except Exception as e:
            from cdp_lib import result
            rows = [result(layer + "-ERR", layer + " 执行异常", layer, "P0", "FAIL", repr(e))]
        rows_by_layer[layer] = rows
        for r in rows:
            print("  %-6s %-4s %-36s %s" %
                  (r["id"], r["status"], r["name"], str(r.get("detail", ""))[:150]))
    meta = {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "head": _git_head(), "ver": _hg_ver(),
            "layers": layers, "groups": groups or []}
    total = {"PASS": 0, "FAIL": 0, "SKIP": 0, "CHECK": 0}
    for rows in rows_by_layer.values():
        for r in rows:
            total[r["status"]] = total.get(r["status"], 0) + 1
    print("\n===== 合计 PASS=%d FAIL=%d SKIP=%d CHECK=%d =====" %
          (total.get("PASS", 0), total.get("FAIL", 0),
           total.get("SKIP", 0), total.get("CHECK", 0)))
    if not a.no_report:
        _append_report(rows_by_layer, meta)
        print("报告已追加: %s" % REPORT)


if __name__ == "__main__":
    main()
