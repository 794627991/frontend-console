# -*- coding: utf-8 -*-
"""分析 ESLint JSON 输出：按规则/文件聚合，并抽样本给人眼看。

用法：
    npx eslint web/js -f json > tests/js/eslint-raw.json
    python tools/eslint_report.py
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "tests", "js", "eslint-raw.json")


def main():
    if not os.path.isfile(RAW):
        print("先跑：npx eslint web/js -f json > tests/js/eslint-raw.json")
        return 1
    with open(RAW, encoding="utf-8") as f:
        data = json.load(f)

    rules = collections.Counter()
    files_err = collections.Counter()
    samples = collections.defaultdict(list)
    for item in data:
        fname = os.path.basename(item["filePath"])
        for m in item["messages"]:
            rid = m.get("ruleId") or "(parse)"
            sev = m["severity"]
            rules[(rid, sev)] += 1
            if sev == 2:
                files_err[fname] += 1
                if len(samples[rid]) < 12:
                    samples[rid].append(
                        "%s:%d  %s" % (fname, m["line"], m["message"][:100]))

    print("=== 按规则 ===")
    for (rid, sev), n in rules.most_common():
        print("%s  %-34s %d" % ("ERR " if sev == 2 else "warn", rid, n))

    print("\n=== error 最多的文件 ===")
    for fname, n in files_err.most_common(15):
        print("%5d  %s" % (n, fname))

    print("\n=== 各规则样本（最多 12 条）===")
    for rid in sorted(samples):
        print("\n-- %s (%d+) --" % (rid, len(samples[rid])))
        for s in samples[rid]:
            print("   " + s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
