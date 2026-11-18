# -*- coding: utf-8 -*-
"""CSS 按子系统重排（用户定调「一步到位」）。

输入：web/style.css（单一真源）
输出：web/style/base.css / harness.css / editor.css / terminal.css /
      vcs.css / office.css / web.css / misc.css + index.html 多 link

算法：
  1. 顶层块解析（跟踪字符串与注释，@media/@keyframes 整体为一块）。
  2. 以顶层注释块为「段」边界；段标题关键词决定初判，段内选择器前缀
     投票可推翻（规则数 ≥3 且投票一致性 ≥70%）。
  3. 段内规则保持原始顺序；子系统文件顺序 = base → harness → editor →
     terminal → vcs → office → web → misc。
  4. 输出冲突报告：同一选择器出现在多个子系统（提示人工复核）。

注意：重排会改变跨子系统层叠顺序——必须用
tests/regression/style_snapshot.py 做前后 computedStyle 指纹对比。

用法：
    python tools/split_css_subsystems.py --dry-run   # 只出报告
    python tools/split_css_subsystems.py             # 写文件 + 改 index.html
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "web", "style.css")
OUTDIR = os.path.join(ROOT, "web", "style")
INDEX = os.path.join(ROOT, "web", "index.html")

ORDER = ["base", "harness", "editor", "terminal", "vcs", "office", "web", "misc"]

# 段标题关键词（按优先级；强特征在前）
TITLE_KW = [
    ("vcs", ["vcs", "版本控制", "版本面板", "提交历史", "分支", "stash", "标签管理"]),
    ("office", ["office", "docx", "pdf 查看", "xlsx", "pptx", "onlyoffice"]),
    ("web", ["网页 tab", "网页tab", "web-tab", "网页加载", "地址栏", "收藏星标"]),
    ("editor", ["编辑器", "editor", "monaco", "markdown", "md 预览", "md预览",
                "大纲", "图片上传", "md 分屏", "md分屏"]),
    ("terminal", ["终端", "terminal", "xterm", "串口", "serial", "ssh", "tftp"]),
    ("harness", ["harness", "claude", "agent", "会话", "工具行", "工具卡",
                 "工作头", "输入卡", "排队", "识图", "子智能体", "子代理", "技能",
                 "审计", "三角色", "回合", "抽屉", "折叠组", "消息", "排空"]),
    ("base", ["主题", "换肤", "变量", "布局", "重置", "顶栏", "侧栏", "按钮",
              "模态", "弹窗", "全局", "字体", "滚动条", "tab 栏", "标签栏",
              "窗口", "标题栏", "设置", "通用", "空态", "基础"]),
]

PREF = [
    ("vcs", [".hg-vcs", "#hgvcs", "hg-vcs"]),
    ("harness", [".hg-", ".h-", ".claude-", ".skill", ".h-ag"]),
    ("editor", [".ed-", ".monaco", ".md-", ".editor", ".cm-", ".log-viewer"]),
    ("terminal", [".xterm", ".term-", ".terminal"]),
    ("office", [".office-", ".xlsx-", ".docx-", ".pdf-", ".ov-"]),
    ("web", [".web-"]),
    ("misc", [".lv-", ".hx-", ".diff-", ".df-", ".dv-", "#replay", ".replay-",
              ".nn-"]),
    ("base", ["body", "html", ":root", "*", ".topbar", ".sidebar", ".tab",
              ".modal", ".btn", ".panel", ".pane", ".tree", ".port-", ".conn-",
              ".win-controls", ".recent-", ".notice", ".toast", ".empty"]),
]


def parse_blocks(src):
    """顶层块：[(start,end,text)]。"""
    n = len(src)
    i = 0
    depth = 0
    start = 0
    instr = None
    bl = []
    BS = chr(92)
    while i < n:
        c = src[i]
        if instr:
            if c == BS:
                i += 2
                continue
            if c == instr:
                instr = None
            i += 1
            continue
        if c in ('"', "'"):
            instr = c
            i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = (j + 2) if j >= 0 else n
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                bl.append((start, i + 1, src[start:i + 1]))
                start = i + 1
        elif c == ';' and depth == 0:
            seg = src[start:i + 1]
            if seg.strip():
                bl.append((start, i + 1, seg))
            start = i + 1
        i += 1
    if src[start:].strip():
        bl.append((start, n, src[start:]))
    return bl


def selector_of(text):
    s = text.split('{', 1)[0]
    s = re.sub(r'^\s*/\*[\s\S]*?\*/\s*', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def vote(sel):
    s = sel.strip().lower()
    for sub, prefixes in PREF:
        for p in prefixes:
            if s.startswith(p):
                return sub
    return None


def title_class(title):
    t = title.lower()
    for sub, kws in TITLE_KW:
        if any(k in t for k in kws):
            return sub
    return None


def block_title(txt):
    m = re.match(r'\s*/\*([\s\S]*?)\*/', txt)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''


def classify_block(txt):
    """选择器前缀优先；无前缀时用前导注释标题；再兜底 base。"""
    sel = selector_of(txt)
    sub = vote(sel)
    if sub:
        return sub
    return title_class(block_title(txt)) or "base"


def build(src, dry):
    blocks = parse_blocks(src)
    buckets = defaultdict(list)
    seg_report = []
    for st, en, txt in blocks:
        sel = selector_of(txt)
        sub = classify_block(txt)
        buckets[sub].append((st, txt))
        seg_report.append({"title": block_title(txt)[:60], "n": 1,
                           "sub": sub, "sels": [sel[:80]]})
    # 冲突：同一选择器出现在多个子系统
    sel_subs = defaultdict(set)
    for sub, items in buckets.items():
        for _st, txt in items:
            sel_subs[selector_of(txt)].add(sub)
    conflicts = {s: sorted(v) for s, v in sel_subs.items() if len(v) > 1}

    report = {
        "blocks": len(seg_report),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "conflicts": {k: v for k, v in list(conflicts.items())[:30]},
        "conflict_count": len(conflicts),
        "sample": sorted(seg_report, key=lambda x: -x["n"])[:20],
        "unclassified_misc": [x for x in seg_report if x["sub"] == "misc"][:10],
    }
    if dry:
        print(json.dumps(report, ensure_ascii=False, indent=1)[:6000])
        return

    os.makedirs(OUTDIR, exist_ok=True)
    for sub in ORDER:
        items = buckets.get(sub) or []
        body = "".join(txt for _st, txt in items)
        with open(os.path.join(OUTDIR, sub + ".css"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("/* a654 子系统分卷：%s（由 tools/split_css_subsystems.py "
                    "从 style.css 重排；段内顺序不变） */\n" % sub)
            f.write(body)
    # index.html：替换 style part link 块
    html = open(INDEX, encoding="utf-8").read()
    pat = re.compile(r'(<link rel="stylesheet" href="web/style\.part\d+\.css\?v=__HG_VER__">\n?)+')
    links = "\n".join(
        '<link rel="stylesheet" href="web/style/%s.css?v=__HG_VER__">' % s
        for s in ORDER)
    html2, n = pat.subn(links + "\n", html, count=1)
    if n == 0:
        # 兼容仍引用单文件 style.css 的情况
        pat2 = re.compile(r'<link rel="stylesheet" href="web/style\.css\?v=__HG_VER__">')
        html2, n = pat2.subn(links + "\n", html, count=1)
    if n == 0:
        raise SystemExit("index.html 未找到 style 引用")
    open(INDEX, "w", encoding="utf-8").write(html2)
    print("已写出 8 个子系统文件 + index.html 已切换")
    print(json.dumps(report, ensure_ascii=False, indent=1)[:2000])


if __name__ == "__main__":
    if not os.path.isfile(SRC):
        raise SystemExit("web/style.css 已删除（a659）；需要重排请先从 git 历史恢复单一源，回滚命令见测试计划 9.5")
    src = open(SRC, encoding="utf-8").read()
    build(src, "--dry-run" in sys.argv)
