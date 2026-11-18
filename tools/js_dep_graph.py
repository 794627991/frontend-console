# -*- coding: utf-8 -*-
"""前端文件依赖图：谁定义了哪些全局名、谁引用了谁（模块化分期的选料地图）。

背景（模块化一期）：75 个经典 script 靠共享全局互调，加载顺序即依赖。
转 ESM 必须自底向上（叶片先行）——本工具把「底」和「叶」变成可计算的：

  defines        该文件声明/挂载的全部全局名（含 window.xxx = 挂载）
  references     该文件正文里出现的**其它文件**定义的名字
  referenced_by  引用了本文件名字的其它文件（反向边）
  top_level_exec 顶层立即执行段（启发式：IIFE 调用 / 顶层 DOM 布线 /
                 顶层直调——这些代码在解析期就跑，模块化时机分析的关键）
  is_module      index.html 是否以 type="module" 加载（modules.txt）

启发式声明（不装 AST）：引用判定 = 标识符全词匹配（名字出现在文件里即算，
分不清「函数体内晚调用」与「顶层立即调用」——后者靠 top_level_exec 与
人工 grep 收口）。所以本图用于圈定候选，不用于机械放行。

用法：python tools/js_dep_graph.py   →  tests/js/dep-graph.json + 叶片摘要
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from js_collect_globals import DECL_RE, WIN_RE, EXTERNAL_GLOBALS  # noqa: E402
from js_script_manifest import parse_script_tags  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "js", "dep-graph.json")

IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")

# 顶层立即执行段的启发式信号（行首无缩进才算顶层）
_TOP_EXEC_RES = (
    re.compile(r"^\((?:async\s+)?function\b"),          # IIFE 起手
    re.compile(r"^\}\)\(\)\s*;?\s*$"),                  # IIFE 收尾（证明确实调了）
    re.compile(r"^(?:document|window|navigator|localStorage|location|"
               r"addEventListener|setInterval|setTimeout|requestAnimationFrame"
               r"|requestIdleCallback|history)\b"),
    re.compile(r"^\$\("),
    re.compile(r"^[A-Za-z_$][\w$]*\("),                 # 顶层直调 foo(...)
    re.compile(r"^[A-Za-z_$][\w$]*\.(?:onclick|onchange|oninput|onkeydown|"
               r"onload|onerror|addEventListener|appendChild|remove|focus|"
               r"querySelector|getBoundingClientRect)\b"),
)


def _defines_and_exec(path):
    """返回 (定义名集合, 顶层执行证据行列表≤3)。"""
    names = set()
    exec_lines = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if len(exec_lines) < 3 and any(r.match(line) for r in _TOP_EXEC_RES):
                    exec_lines.append(line.strip()[:100])
                m = DECL_RE.match(line)
                if m:
                    names.add(m.group("fn") or m.group("vn"))
                    continue
                m = WIN_RE.match(line)
                if m:
                    names.add(m.group(1))
    except OSError:
        pass
    return names, exec_lines


def _idents(path):
    """文件里出现过的全部标识符（去重集合）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return set(IDENT_RE.findall(f.read()))
    except OSError:
        return set()


def main():
    with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
        html = f.read()

    order = []           # [(rel, is_module)] 按加载序
    for src, is_module in parse_script_tags(html):
        src = src.split("?")[0]
        if src.startswith("web/"):
            rel = os.path.relpath(src, "web").replace(os.sep, "/")
            if rel.endswith(".js"):
                order.append((rel, is_module))

    files = {}
    define_map = {}      # name -> set(rel)
    for idx, (rel, is_module) in enumerate(order):
        p = os.path.join(ROOT, "web", rel.replace("/", os.sep))
        defs, exec_lines = _defines_and_exec(p)
        files[rel] = {
            "load_index": idx,
            "is_module": is_module,
            "defines": sorted(defs),
            "top_level_exec": exec_lines,
            "idents": _idents(p),
        }
        for n in defs:
            define_map.setdefault(n, set()).add(rel)

    for rel, info in files.items():
        own = set(info["defines"])
        foreign = set()
        for n in info["idents"]:
            owners = define_map.get(n)
            if not owners or n in EXTERNAL_GLOBALS or len(owners) != 1:
                continue     # 多处定义的名字归属不明（init/_post 之类），不入边
            owner = next(iter(owners))
            if owner != rel and n not in own:
                foreign.add((owner, n))
        info["references"] = sorted(
            {"%s:%s" % (o, n) for o, n in foreign})

    for rel, info in files.items():
        rb = {}
        for other, oinfo in files.items():
            if other == rel:
                continue
            hit = sorted(n for (o, n) in
                         {(x.split(":", 1)[0], x.split(":", 1)[1])
                          for x in oinfo["references"]}
                         if o == rel)
            if hit:
                rb[other] = hit
        info["referenced_by"] = rb

    # 序列化：references 拆回 {file: [names]} 更好读
    for info in files.values():
        refs = {}
        for pair in info.pop("references"):
            o, n = pair.split(":", 1)
            refs.setdefault(o, []).append(n)
        info["references"] = {k: sorted(v) for k, v in refs.items()}
        info.pop("idents")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_note": "tools/js_dep_graph.py 生成，提交入库；"
                                      "引用判定为标识符全词启发式（见模块头注释）",
                   "files": files}, f, ensure_ascii=False, indent=1, sort_keys=True)

    # 叶片摘要：无人引用（referenced_by 空）的文件 = 最安全的 ESM 候选
    leaves = [rel for rel, info in files.items()
              if not info["referenced_by"] and not info["is_module"]]
    print("图已写入 %s：%d 文件，其中零反向引用（叶片）%d 个："
          % (os.path.relpath(OUT, ROOT), len(files), len(leaves)))
    for rel in leaves:
        info = files[rel]
        tag = " [顶层执行]" if info["top_level_exec"] else ""
        print("  %s%s" % (rel, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
