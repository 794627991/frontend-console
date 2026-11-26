# -*- coding: utf-8 -*-
"""doc_anchor 的规则单测。

与 tests/js/docview-anchor.test.mjs **用同一组用例**（AC-3.10：Python 版和
JS 版跑同一批输入，结果必须相同）。改任何一边都要同步改另一边。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.doc_anchor import (  # noqa: E402
    parse_locator, format_locator, parse_anchor, split_anchor, kind_of_path,
    column_name, parse_cell, format_cell, format_sheet, parse_xlsx,
    HINTS, KIND_DOCX, KIND_PDF, KIND_PPTX, KIND_XLSX,
)


def test_docx_locators():
    assert parse_locator("docx", "p:14") == {"kind": "docx", "paragraph": 14}
    assert parse_locator("docx", "p:3-9") == {"kind": "docx", "paragraphs": {"from": 3, "to": 9}}
    assert parse_locator("docx", "t:2") == {"kind": "docx", "table": 2}
    assert parse_locator("docx", "t:2/r3c1") == {"kind": "docx", "table": 2, "cell": {"row": 3, "col": 1}}
    # 大小写与空白容忍
    assert parse_locator("docx", "  P : 7 ") == {"kind": "docx", "paragraph": 7}


def test_docx_rejects():
    for bad in ["", "p:", "p:0", "p:9-3", "p:abc", "t:2/r3", "t:0", "x:3",
                "p:1-", "p:1000001"]:
        assert parse_locator("docx", bad) is None, "应拒绝 %r" % bad


def test_pdf_locators():
    assert parse_locator("pdf", "page:5") == {"kind": "pdf", "page": 5}
    assert parse_locator("pdf", "page:2-4") == {"kind": "pdf", "pages": {"from": 2, "to": 4}}
    assert parse_locator("pdf", "page:0") is None
    assert parse_locator("pdf", "p:5") is None


def test_pptx_locators():
    assert parse_locator("pptx", "slide:3") == {"kind": "pptx", "slide": 3}
    assert parse_locator("pptx", "slide:2-4") == {"kind": "pptx", "slides": {"from": 2, "to": 4}}
    assert parse_locator("pptx", "slide:3/shape:7") == {"kind": "pptx", "slide": 3, "shape": 7}
    # 形状只能落在单张上
    assert parse_locator("pptx", "slide:2-4/shape:7") is None


def test_xlsx_locators():
    assert parse_locator("xlsx", "Revenue") == {"kind": "xlsx", "sheet": "Revenue"}
    assert parse_locator("xlsx", "Revenue!B2") == {
        "kind": "xlsx", "sheet": "Revenue",
        "range": {"from": {"row": 2, "col": 2}, "to": {"row": 2, "col": 2}}}
    assert parse_locator("xlsx", "Revenue!B2:F9") == {
        "kind": "xlsx", "sheet": "Revenue",
        "range": {"from": {"row": 2, "col": 2}, "to": {"row": 9, "col": 6}}}
    # 反向范围归一成左上到右下
    assert parse_locator("xlsx", "Revenue!F9:B2")["range"] == {
        "from": {"row": 2, "col": 2}, "to": {"row": 9, "col": 6}}
    # 表名带空格要单引号；内部单引号写两个
    assert parse_locator("xlsx", "'Q3 data'!A1")["sheet"] == "Q3 data"
    assert parse_locator("xlsx", "'It''s'!A1")["sheet"] == "It's"
    # 绝对引用
    assert parse_locator("xlsx", "S!$B$2")["range"]["from"] == {"row": 2, "col": 2}
    # 引号没闭合 / 列超限
    assert parse_locator("xlsx", "'Q3 data!A1") is None
    assert parse_locator("xlsx", "S!XFE1") is None


def test_format_locator():
    assert format_locator({"kind": "docx", "paragraphs": {"from": 3, "to": 9}}) == "p:3-9"
    assert format_locator({"kind": "pdf", "pages": {"from": 2, "to": 4}}) == "page:2-4"
    assert format_locator({"kind": "pptx", "slides": {"from": 2, "to": 4}}) == "slide:2-4"
    assert format_locator({"kind": "pptx", "slide": 3, "shape": 7}) == "slide:3/shape:7"
    assert format_locator({"kind": "docx", "table": 2, "cell": {"row": 3, "col": 1}}) == "t:2/r3c1"
    assert format_locator({"kind": "xlsx", "sheet": "Q3 data"}) == "'Q3 data'"
    assert format_locator({"kind": "xlsx", "sheet": "S",
                           "range": {"from": {"row": 2, "col": 2}, "to": {"row": 9, "col": 6}}}) == "S!B2:F9"
    assert format_locator({"kind": "xlsx", "sheet": "S",
                           "range": {"from": {"row": 2, "col": 2}, "to": {"row": 2, "col": 2}}}) == "S!B2"


def test_roundtrip():
    cases = [("docx", "p:14"), ("docx", "p:3-9"), ("docx", "t:2"), ("docx", "t:2/r3c1"),
             ("pdf", "page:5"), ("pdf", "page:2-4"),
             ("pptx", "slide:3"), ("pptx", "slide:2-4"), ("pptx", "slide:3/shape:7"),
             ("xlsx", "Revenue"), ("xlsx", "Revenue!B2"), ("xlsx", "Revenue!B2:F9"),
             ("xlsx", "'Q3 data'!A1")]
    for k, raw in cases:
        assert format_locator(parse_locator(k, raw)) == raw, "往返失败：%s|%s" % (k, raw)


def test_columns():
    assert column_name(1) == "A"
    assert column_name(26) == "Z"
    assert column_name(27) == "AA"
    assert column_name(16384) == "XFD"
    assert parse_cell("AA10") == {"row": 10, "col": 27}
    assert format_cell({"row": 10, "col": 27}) == "AA10"
    assert format_sheet("Revenue") == "Revenue"
    assert format_sheet("Q3 data") == "'Q3 data'"
    assert format_sheet("It's") == "'It''s'"


def test_split_anchor():
    assert split_anchor("D:\\docs\\报告.docx#p:3") == ("D:\\docs\\报告.docx", "p:3")
    assert split_anchor("/a/b.pdf") == ("/a/b.pdf", "")
    # .bak 不在扩展名表里，不能被当成切点
    assert split_anchor("D:\\a\\my.docx.bak") == ("D:\\a\\my.docx.bak", "")
    assert split_anchor("D:\\a\\x.PPTX#slide:2") == ("D:\\a\\x.PPTX", "slide:2")


def test_parse_anchor():
    kind, path, at, loc = parse_anchor("D:\\docs\\报告.docx#p:3-9")
    assert kind == "docx"
    assert path == "D:\\docs\\报告.docx"
    assert loc == {"kind": "docx", "paragraphs": {"from": 3, "to": 9}}
    # 锚点写错：loc 为 None，但路径与 kind 仍给出
    kind2, path2, at2, loc2 = parse_anchor("a.pdf#page:0")
    assert kind2 == "pdf"
    assert loc2 is None


def test_kind_of_path():
    assert kind_of_path("a/b.docx") == "docx"
    assert kind_of_path("a/b.DOCX") == "docx"
    assert kind_of_path("a/b.docx#p:3") == "docx"
    assert kind_of_path("a/b.png") == "image"
    assert kind_of_path("a/b.txt") is None
    assert kind_of_path("a/b") is None
    assert kind_of_path("a/b.docx:12") == "docx"


def test_hints_present():
    for k in (KIND_DOCX, KIND_PDF, KIND_PPTX, KIND_XLSX):
        assert HINTS[k]
