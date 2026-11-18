# -*- coding: utf-8 -*-
"""比对 index.html 实际加载的脚本与磁盘上的文件。

用途：ESLint 配置需要知道「哪些 js 是页面里真在跑的」，否则要么漏扫
（动态加载的）要么误报（根本没用到的）。本脚本输出三份清单：
  tests/js/loaded.txt     index.html 按顺序引用的脚本（相对 web/）
  tests/js/orphans.txt    磁盘上有但没被 index 引用的（疑似死文件）
  tests/js/modules.txt    带 type="module" 的引用（相对 web/）——模块化
                          一期的单一真源：js_collect_globals（模块内部名
                          不进全局清单）与 eslint 配置（sourceType 切换）
                          都读它，避免三处各写一份解析。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "js")


def parse_script_tags(html):
    """返回 [(src, is_module)]，按文档顺序。src 为 index.html 原始引用
    （含 ?v= 查询串），is_module 由标签是否带 type="module" 判定。"""
    tags = re.findall(r"<script\b[^>]*>", html)
    out = []
    for tag in tags:
        m = re.search(r'src="([^"]+)"', tag)
        if not m:
            continue
        out.append((m.group(1), 'type="module"' in tag))
    return out


def main():
    html_path = os.path.join(ROOT, "web", "index.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    loaded = []
    modules = []
    for src, is_module in parse_script_tags(html):
        src = src.split("?")[0]
        if not src.startswith("web/"):
            continue
        rel = os.path.relpath(src, "web").replace(os.sep, "/")
        loaded.append(rel)
        if is_module:
            modules.append(rel)

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
    with open(os.path.join(OUT, "modules.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(modules) + "\n")

    print("index.html 引用 %d 个脚本（module %d）；磁盘 %d 个 js；未引用 %d 个"
          % (len(loaded), len(modules), len(on_disk), len(orphans)))
    if orphans:
        print("未被 index.html 引用的（可能是动态加载，需人工确认）：")
        for o in orphans:
            print("  " + o)
    return 0


if __name__ == "__main__":
    sys.exit(main())
