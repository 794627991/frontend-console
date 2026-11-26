# -*- coding: utf-8 -*-
"""文档锚点语法的 Python 版（与 web/js/docview/anchor.js 同语义）。

为什么后端也要一份：`read_document` 分页、`search_document` 定位都要在
**不等前端**的情况下算锚点，MCP 工具进程里没有浏览器。两份实现必须行为
一致——AC-3.10 用同一组用例同时跑 JS 版和 Python 版，改一边必须改另一边。

语法（设计文档 4.1，译自 ZCode 的 OR/src/domain/anchor.ts）：

    docx   p:14   p:3-9      t:2   t:2/r3c1
    pptx   slide:3   slide:2-4   slide:3/shape:7
    pdf    page:5   page:2-4
    xlsx   Revenue   Revenue!B2   Revenue!B2:F9   'Q3 data'!A1

下标**从 1 起**（不是 0）。上界取 Excel 的极限：行 1048576、列 16384。
锚点文本长度上限 300。
"""

import re

KIND_DOCX = "docx"
KIND_PPTX = "pptx"
KIND_PDF = "pdf"
KIND_XLSX = "xlsx"
KIND_IMAGE = "image"

MAX_ANCHOR_LEN = 300
MAX_ROW = 1048576
MAX_COL = 16384
MAX_INDEX = 1000000

HINTS = {
    KIND_DOCX: "Word 文档的锚点写法：p:14（第 14 段）、p:3-9（第 3 到 9 段）、"
                "t:2（第 2 个表格）、t:2/r3c1（第 2 个表格第 3 行第 1 列）",
    KIND_PPTX: "演示文稿的锚点写法：slide:3（第 3 张）、slide:2-4（第 2 到 4 张）、"
               "slide:3/shape:7（第 3 张的第 7 个形状）",
    KIND_PDF: "PDF 的锚点写法：page:5（第 5 页）、page:2-4（第 2 到 4 页）",
    KIND_XLSX: "工作表的锚点写法：Revenue（整张）、Revenue!B2（单元格）、"
               "Revenue!B2:F9（区域）、'Q3 data'!A1（表名含空格时加单引号）",
    KIND_IMAGE: "图片没有锚点",
}

# 扩展名 → kind（大小写不敏感）。图片六种按 A10。
EXT_KIND = {
    "docx": KIND_DOCX, "doc": KIND_DOCX,
    "pdf": KIND_PDF,
    "xlsx": KIND_XLSX, "xls": KIND_XLSX, "csv": KIND_XLSX,
    "pptx": KIND_PPTX, "ppt": KIND_PPTX,
    "png": KIND_IMAGE, "jpg": KIND_IMAGE, "jpeg": KIND_IMAGE,
    "gif": KIND_IMAGE, "webp": KIND_IMAGE, "bmp": KIND_IMAGE,
    "ico": KIND_IMAGE, "svg": KIND_IMAGE,
}

DOC_EXTS = tuple(EXT_KIND)


def _norm(s):
    """与 text.js 的 normalize 同语义：所有空白压成单空格、去首尾。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def kind_of_path(path):
    """路径 → kind，认不出返回 None。剥锚点与行号后缀后再取扩展名。"""
    p = str(path or "")
    bare = re.sub(r"[#?].*$", "", p)
    bare = re.sub(r":\d+(:\d+)?$", "", bare)
    m = re.search(r"\.([A-Za-z0-9]+)$", bare)
    if not m:
        return None
    return EXT_KIND.get(m.group(1).lower())


# ---------- Excel 列号 ↔ 字母 ----------

def column_name(col):
    n = int(col or 0)
    if n < 1:
        return ""
    s = ""
    while n > 0:
        r = (n - 1) % 26
        s = chr(65 + r) + s
        n = (n - 1) // 26
    return s


def _column_index(name):
    s = str(name or "").upper()
    if not re.fullmatch(r"[A-Z]{1,3}", s):
        return 0
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n


def parse_cell(text):
    """解析 "B2"（允许 $）。返回 {row, col} 或 None。"""
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d{1,7})", str(text or "").strip())
    if not m:
        return None
    col = _column_index(m.group(1))
    row = int(m.group(2))
    if col < 1 or col > MAX_COL:
        return None
    if row < 1 or row > MAX_ROW:
        return None
    return {"row": row, "col": col}


def format_cell(cell):
    if not cell:
        return ""
    c = int(cell.get("col") or 0)
    r = int(cell.get("row") or 0)
    if c < 1 or r < 1:
        return ""
    return column_name(c) + str(r)


def format_sheet(name):
    """表名不是普通标识符时按 Excel 方式加单引号（内部单引号写两个）。"""
    s = "" if name is None else str(name)
    if not s:
        return ""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", s):
        return s
    return "'" + s.replace("'", "''") + "'"


def _parse_sheet_name(raw):
    s = str(raw or "").strip()
    if not s:
        return ""
    if not s.startswith("'"):
        return s
    out, i = [], 1
    n = len(s)
    while i < n:
        if s[i] == "'":
            if i + 1 < n and s[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            i += 1
            break
        out.append(s[i])
        i += 1
    else:
        return ""   # 引号没闭合
    return "".join(out)


def parse_xlsx(text):
    s = str(text or "").strip()
    if not s:
        return None
    bang = s.rfind("!")
    if bang < 0:
        sheet_raw, range_raw = s, ""
    else:
        sheet_raw, range_raw = s[:bang], s[bang + 1:].strip()
    sheet = _parse_sheet_name(sheet_raw)
    if not sheet:
        return None
    if not range_raw:
        return {"kind": KIND_XLSX, "sheet": sheet}
    parts = range_raw.split(":")
    if len(parts) > 2:
        return None
    a = parse_cell(parts[0])
    if not a:
        return None
    if len(parts) == 1:
        return {"kind": KIND_XLSX, "sheet": sheet, "range": {"from": a, "to": a}}
    b = parse_cell(parts[1])
    if not b:
        return None
    # 归一：左上 → 右下
    frm = {"row": min(a["row"], b["row"]), "col": min(a["col"], b["col"])}
    to = {"row": max(a["row"], b["row"]), "col": max(a["col"], b["col"])}
    return {"kind": KIND_XLSX, "sheet": sheet, "range": {"from": frm, "to": to}}


def _num_of(s):
    if not re.fullmatch(r"\d{1,7}", str(s or "")):
        return 0
    n = int(s)
    return n if 1 <= n <= MAX_INDEX else 0


def _range_of(raw):
    m = re.fullmatch(r"(\d{1,7})(?:\s*-\s*(\d{1,7}))?", str(raw or "").strip())
    if not m:
        return None
    frm = _num_of(m.group(1))
    if not frm:
        return None
    to = frm if m.group(2) is None else _num_of(m.group(2))
    if not to:
        return None
    if to < frm:
        return None
    return {"from": frm, "to": to}


def parse_locator(kind, raw):
    """解析锚点文本。返回 Locator dict 或 None。"""
    s = _norm(raw)
    if not s or len(s) > MAX_ANCHOR_LEN:
        return None

    if kind == KIND_XLSX:
        return parse_xlsx(s)

    if kind == KIND_DOCX:
        m = re.fullmatch(r"p\s*:\s*(\d{1,7}(?:\s*-\s*\d{1,7})?)", s, re.I)
        if m:
            r = _range_of(m.group(1))
            if not r:
                return None
            if r["from"] == r["to"]:
                return {"kind": kind, "paragraph": r["from"]}
            return {"kind": kind, "paragraphs": r}
        m = re.fullmatch(r"t\s*:\s*(\d{1,7})(?:\s*/\s*r(\d{1,7})c(\d{1,7}))?", s, re.I)
        if m:
            t = _num_of(m.group(1))
            if not t:
                return None
            if m.group(2) is None:
                return {"kind": kind, "table": t}
            row, col = _num_of(m.group(2)), _num_of(m.group(3))
            if not row or not col:
                return None
            return {"kind": kind, "table": t, "cell": {"row": row, "col": col}}
        return None

    if kind == KIND_PPTX:
        m = re.fullmatch(r"slide\s*:\s*(\d{1,7}(?:\s*-\s*\d{1,7})?)(?:\s*/\s*shape\s*:\s*(\d{1,7}))?", s, re.I)
        if not m:
            return None
        r = _range_of(m.group(1))
        if not r:
            return None
        if m.group(2) is not None:
            shape = _num_of(m.group(2))
            if not shape:
                return None
            if r["from"] != r["to"]:
                return None
            return {"kind": kind, "slide": r["from"], "shape": shape}
        if r["from"] == r["to"]:
            return {"kind": kind, "slide": r["from"]}
        return {"kind": kind, "slides": r}

    if kind == KIND_PDF:
        m = re.fullmatch(r"page\s*:\s*(\d{1,7}(?:\s*-\s*\d{1,7})?)", s, re.I)
        if not m:
            return None
        r = _range_of(m.group(1))
        if not r:
            return None
        if r["from"] == r["to"]:
            return {"kind": kind, "page": r["from"]}
        return {"kind": kind, "pages": r}

    return None


def format_locator(loc):
    """规范化输出。范围省略第二个前缀：`p:3-9`。解析失败返回空串。"""
    if not loc or not loc.get("kind"):
        return ""
    k = loc["kind"]
    if k == KIND_XLSX:
        sheet = format_sheet(loc.get("sheet"))
        if not sheet:
            return ""
        rng = loc.get("range")
        if not rng:
            return sheet
        a, b = rng.get("from"), rng.get("to")
        if not a:
            return sheet
        fa = format_cell(a)
        if not b or (b["row"] == a["row"] and b["col"] == a["col"]):
            return sheet + "!" + fa
        return sheet + "!" + fa + ":" + format_cell(b)
    if k == KIND_DOCX:
        if loc.get("paragraph"):
            return "p:%d" % loc["paragraph"]
        if loc.get("paragraphs"):
            return "p:%d-%d" % (loc["paragraphs"]["from"], loc["paragraphs"]["to"])
        if loc.get("table"):
            cell = loc.get("cell")
            if not cell:
                return "t:%d" % loc["table"]
            return "t:%d/r%dc%d" % (loc["table"], cell["row"], cell["col"])
        return ""
    if k == KIND_PPTX:
        if loc.get("slide"):
            shape = loc.get("shape")
            return "slide:%d%s" % (loc["slide"], ("/shape:%d" % shape) if shape else "")
        if loc.get("slides"):
            return "slide:%d-%d" % (loc["slides"]["from"], loc["slides"]["to"])
        return ""
    if k == KIND_PDF:
        if loc.get("page"):
            return "page:%d" % loc["page"]
        if loc.get("pages"):
            return "page:%d-%d" % (loc["pages"]["from"], loc["pages"]["to"])
        return ""
    return ""


def split_anchor(anchor):
    """从「路径#锚点」切出路径。

    路径在**第一个受支持扩展名**加 # 或行尾处结束（anchor.ts:170-179）——
    所以 `D:\\a\\b.docx#p:3` 的路径是 `D:\\a\\b.docx`，而 `my.docx.bak`
    里的 .docx 不会被误切（.bak 后面既不是 # 也不是行尾）。
    """
    s = "" if anchor is None else str(anchor)
    ext = "(?:docx|doc|pdf|xlsx|xls|csv|pptx|ppt|png|jpe?g|gif|webp|bmp|ico|svg)"
    m = re.search(r"\." + ext + r"(?=#|$)", s, re.I)
    if not m:
        i = s.find("#")
        if i < 0:
            return s, ""
        return s[:i], s[i + 1:]
    last = m.end()
    if last < len(s) and s[last] == "#":
        return s[:last], s[last + 1:]
    return s, ""


def format_anchor(path, loc):
    a = format_locator(loc)
    return ("%s#%s" % (path, a)) if a else str(path)


def parse_anchor(anchor):
    """解析「路径#锚点」为 (kind, path, at, loc)。loc 为 None 表示锚点写错或无锚点。"""
    path, at = split_anchor(anchor)
    kind = kind_of_path(path)
    loc = None
    if at and kind and len(at) <= MAX_ANCHOR_LEN:
        loc = parse_locator(kind, at)
    return kind, path, at, loc
