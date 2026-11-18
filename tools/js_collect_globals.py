# -*- coding: utf-8 -*-
"""收集前端所有顶层声明，生成 ESLint 的 globals 清单。

为什么需要：web/index.html 用 100 个传统 <script> 标签按顺序加载（零
ES module），每个文件的顶层 `function foo(){}` / `const BAR` 都自动成为
window 上的全局。跨文件互相调用就靠这个共享命名空间。

ESLint 的 no-undef 如果不认识这些名字，会把每一处跨文件调用都报成
「未定义」，噪音淹没真问题。所以先把所有顶层声明喂给它。

局限（重要）：ESLint 无法校验**加载顺序**——A 里声明的函数，只有 A 在
B 之前加载，B 才能用。这类顺序错误本条清单拦不住，需要靠生成
loaded.txt 的实际顺序 + 人工判断。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "web", "js")
OUT = os.path.join(ROOT, "tests", "js", "app-globals.json")

# a644：不能只匹配行首无缩进的声明。大量模块写在 IIFE 里：
#     (function () {
#       function hgModal(...) {...}        <- 缩进两格，但外面是函数作用域
#       ...
#     })();
# 这些名字并不会成为 window 属性，但**同项目其它文件确实在调它们**
# （harness 系列之间就是这么互调的，靠脚本共享作用域被调用）。ESLint 的
# no-undef 若不认识它们，会把每一处真实调用报成「未定义」，噪音淹没真问题。
# 所以收集器放宽到「任意缩进层级的 function/const/let/var/class 声明」，
# 代价是会多收一些真的函数局部变量（无害：只会让 no-undef 少报，不会漏
# 掉真实拼写错误——真拼错的名字依然不在清单里）。
DECL_RE = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?function\s*\*?\s*(?P<fn>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var|class)\s+(?P<vn>[A-Za-z_$][\w$]*)"
    r")")

# window.xxx = ... 显式挂载
WIN_RE = re.compile(r"^\s*window\.([A-Za-z_$][\w$]*)\s*=")

# 第三方库运行时注入的全局名（vendor/ 下的 UMD 包），源码不在本项目里，
# ESLint 静态看不到，必须显式声明。清单来源：web/index.html 的 vendor 引用
# + 各 .js 里的实际用法（grep 核对过）。
EXTERNAL_GLOBALS = {
    # pywebview 注入的 JS 桥
    "pywebview",
    # harness v4 运行时组装对象
    "V4Main",
    # xterm 及其 addon（terminal-core.js）
    "Terminal", "FitAddon", "SearchAddon", "WebLinksAddon", "WebglAddon",
    # highlight.js
    "hljs",
    # Monaco Editor
    "monaco",
    # EditorJS 及插件（editor.js）
    "EditorJS", "Header", "EditorjsList", "Checklist", "Table", "ImageTool",
    "CodeTool", "Delimiter", "Marker", "InlineCode", "Quote",
    # 文档预览（office-viewer.js）
    "DocsAPI", "pdfjsLib", "docx", "JSZip", "XLSX",
    # intel hex 解析（hex-viewer.js）
    "intelHexParse",
    # markdown-it
    "markdownit",
    # 误报的 node 环境残留
    "process", "module", "require", "exports", "__dirname", "__filename",
}

# 有意的函数解包（monkey-patch）：`const _orig = fn; fn = function(){}`
# 形式是刻意做的行为包装，不是手误。按文件+名字精确豁免，不做全局放宽。
FUNC_PATCH_ALLOW = {
    ("web/js/log-viewer.js", "showDragOverlay"),
}


def scan(path):
    names = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = DECL_RE.match(line)
                if m:
                    names.add(m.group("fn") or m.group("vn"))
                    continue
                m = WIN_RE.match(line)
                if m:
                    names.add(m.group(1))
    except OSError:
        pass
    return names


def main():
    all_names = set(EXTERNAL_GLOBALS)
    count = 0
    for root, _dirs, files in os.walk(JS_DIR):
        for fn in files:
            if fn.endswith(".js"):
                all_names |= scan(os.path.join(root, fn))
                count += 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    import json
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(sorted(all_names), f, ensure_ascii=False, indent=1)
    print("扫描 %d 个文件，收集 %d 个全局名 → %s"
          % (count, len(all_names), os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
