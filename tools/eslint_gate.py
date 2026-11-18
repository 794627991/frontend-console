# -*- coding: utf-8 -*-
"""ESLint 基线校验：与已接受的基线比对，只报**新增**的 error。

为什么需要：项目此前零 lint，一次全量扫描会有大量存量告警。如果不管，
要么天天红着看（很快就没人看了），要么一次性大规模改（风险高）。
基线策略是中间路线——把当前状态冻结成基线，后续只要不新增就算通过。

用法：
    python tools/eslint_gate.py            # 校验（新增 error → 退出码 1）
    python tools/eslint_gate.py --update   # 把当前状态刷新为基线
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tests", "js", "eslint-baseline.json")


def _run_lint():
    """跑 eslint，返回 {file: [(line, rule, msg), ...]}（只收 error）。"""
    # Windows 上 npx 是 .cmd，subprocess 不认 shell=False 直调 → 用 node 直跑
    # eslint 入口（node_modules/.bin/eslint 是 shell 脚本，同样不行）。
    entry = os.path.join(ROOT, "tools", "js-tooling", "node_modules",
                         "eslint", "bin", "eslint.js")
    config = os.path.join(ROOT, "tools", "js-tooling", "eslint.config.mjs")
    if not os.path.isfile(entry):
        raise SystemExit("找不到 eslint：先跑 npm install")
    out = subprocess.run(["node", entry, "--config", config,
                          "web/js", "-f", "json"],
                         cwd=ROOT, capture_output=True)
    raw = out.stdout.decode("utf-8", "replace").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    result = {}
    for item in data:
        rel = os.path.relpath(item["filePath"], ROOT).replace(os.sep, "/")
        errs = [(m["line"], m.get("ruleId"), m["message"])
                for m in item["messages"] if m["severity"] == 2]
        if errs:
            result[rel] = errs
    return result


def _load_baseline():
    try:
        with open(BASELINE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    update = "--update" in sys.argv
    current = _run_lint()
    total = sum(len(v) for v in current.values())

    if update:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=1, sort_keys=True)
        print("基线已更新：%d 个 error（%d 个文件）"
              % (total, len(current)))
        return 0

    base = _load_baseline()
    base_keys = {(f, ln, r) for f, errs in base.items() for ln, r, _ in errs}
    new = []
    for fname, errs in current.items():
        for line, rule, msg in errs:
            if (fname, line, rule) not in base_keys:
                new.append((fname, line, rule, msg))

    if not new:
        print("通过：无新增 error（基线 %d 条，当前 %d 条）"
              % (sum(len(v) for v in base.values()), total))
        return 0

    print("新增 %d 个 error（基线未覆盖）：" % len(new))
    for fname, line, rule, msg in new[:50]:
        print("  %s:%d  [%s] %s" % (fname, line, rule, msg[:90]))
    if len(new) > 50:
        print("  ... 还有 %d 条" % (len(new) - 50))
    print("\n确认是有意改动后，跑 python tools/eslint_gate.py --update 刷新基线")
    return 1


if __name__ == "__main__":
    sys.exit(main())
