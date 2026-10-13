# 扫描 web/ 全部 JS+HTML 中无 name 且无 id 的表单标签（跨行标签块完整解析）
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG_RE = re.compile(r"<(input|select|textarea)\b[^>]*>", re.S | re.I)
ATTR_RE = re.compile(r"""\b(name|id)\s*=\s*(""" + r'"[^"]*"|\'[^\']*\'|[^\s>]+)')

hits = {}
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "web")):
    if "node_modules" in dirpath or "vendor" in dirpath:
        continue
    for fn in files:
        if not fn.endswith((".js", ".html")):
            continue
        p = os.path.join(dirpath, fn)
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        rel = os.path.relpath(p, ROOT)
        for m in TAG_RE.finditer(text):
            tag = m.group(0)
            if ATTR_RE.search(tag):
                continue
            line = text[:m.start()].count("\n") + 1
            hits.setdefault(rel, []).append((line, tag[:110].replace("\n", " ⏎ ")))

total = 0
for f in sorted(hits):
    for line, tag in hits[f]:
        total += 1
        print("%s:%d: %s" % (f, line, tag))
print("---- total: %d ----" % total)
