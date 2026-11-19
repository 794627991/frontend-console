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


_IMPORT_RE = re.compile(
    r"""\bimport\s+(?:[^;'"]*?\s+from\s+)?['"]([^'"]+)['"]"""
    r"""|\bexport\s+[^;'"]*?\s+from\s+['"]([^'"]+)['"]"""
    r"""|\bimport\(\s*['"]([^'"]+)['"]\s*\)""")


def _scan_esm_imports(entry_files, on_disk):
    """从模块入口沿 import/export-from/动态 import 找出所有被引用的 js。

    只处理**相对路径**（./ ../）——裸模块名（'globals' 之类）不是本项目
    文件，跳过。返回相对 web/ 的路径集合，只保留磁盘上真实存在的。"""
    web_root = os.path.join(ROOT, "web")
    seen = set()
    queue = [os.path.join(web_root, p) for p in entry_files]
    while queue:
        cur = queue.pop()
        try:
            with open(cur, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            continue
        base = os.path.dirname(cur)
        for m in _IMPORT_RE.finditer(src):
            spec = m.group(1) or m.group(2) or m.group(3)
            if not spec:
                continue
            if not (spec.startswith("./") or spec.startswith("../")):
                continue
            tgt = os.path.normpath(os.path.join(base, spec))
            rel = os.path.relpath(tgt, web_root).replace(os.sep, "/")
            if rel in seen or rel in on_disk and rel in seen:
                continue
            if rel not in on_disk:
                continue          # 目标不是本仓的 js（不应发生，防御）
            seen.add(rel)
            queue.append(tgt)
    return seen


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
    # ESM 子模块：type="module" 的入口可以 import 同级/子目录的 js，这些
    # 文件不会出现在 index.html 的 <script src> 里，但确实是活的。不把它们
    # 计入已加载会全部误报成孤儿（a673 Lanzi 专栏拆分后实测 4 个）。
    esm_reached = _scan_esm_imports(loaded, on_disk)
    loaded_effective = list(loaded) + sorted(esm_reached - set(loaded))
    orphans = sorted(on_disk - set(loaded_effective))
    with open(os.path.join(OUT, "orphans.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(orphans) + "\n")
    # a673：ESM 子模块也是按 ESM 解析的，eslint 的 sourceType 必须覆盖它们
    # （js_collect_globals 同理：内部声明不进全局清单）
    modules = sorted(set(modules) | esm_reached)
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
