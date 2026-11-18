# -*- coding: utf-8 -*-
"""比对 index.html 实际加载的脚本与磁盘上的文件。

用途：ESLint 配置需要知道「哪些 js 是页面里真在跑的」，否则要么漏扫
（动态加载的）要么误报（根本没用到的）。本脚本输出两份清单：
  tests/js/loaded.txt     index.html 按顺序引用的脚本（相对 web/）
  tests/js/orphans.txt    磁盘上有但没被 index 引用的（疑似死文件）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "js")


def main():
    html_path = os.path.join(ROOT, "web", "index.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    refs = re.findall(r'<script[^>]*src="([^"]+\.js)[^"]*"', html)
    loaded = []
    for r in refs:
        r = r.split("?")[0]
        if r.startswith("web/"):
            loaded.append(os.path.relpath(r, "web").replace(os.sep, "/"))

    on_disk = set()
    for root, _dirs, files in os.walk(os.path.join(ROOT, "web", "js")):
        for fn in files:
            if fn.endswith(".js"):
                p = os.path.relpath(os.path.join(root, fn),
                                    os.path.join(ROOT, "web"))
                on_disk.add(p.replace(os.sep, "/"))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "loaded.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(loaded) + "\n")
    orphans = sorted(on_disk - set(loaded))
    with open(os.path.join(OUT, "orphans.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(orphans) + "\n")

    print("index.html 引用 %d 个脚本；磁盘 %d 个 js；未被引用 %d 个"
          % (len(loaded), len(on_disk), len(orphans)))
    if orphans:
        print("未被 index.html 引用的（可能是动态加载，需人工确认）：")
        for o in orphans:
            print("  " + o)
    return 0


if __name__ == "__main__":
    sys.exit(main())
