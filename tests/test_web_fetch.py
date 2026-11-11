# -*- coding: utf-8 -*-
"""a473 网页取页纯函数回归（charset 三跳探测 + HTML→文本）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import server as S  # noqa: E402


def test_charset_quoted_header():
    """审计实锤：RFC 9110 合法的 charset="GBK" 原正则失配 → 全页乱码。"""
    assert S._web_detect_charset('text/html; charset="GBK"', b"") == "gbk"
    assert S._web_detect_charset("text/html; charset='gb18030'", b"") == "gb18030"


def test_charset_plain_header():
    assert S._web_detect_charset("text/html; charset=utf-8", b"") == "utf-8"
    assert S._web_detect_charset("application/json", b"") == "utf-8"


def test_charset_meta_fallback():
    """老内网页只写 meta 不写 header——body 前 2KB 兜底。"""
    raw = '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gbk">'.encode("ascii")
    assert S._web_detect_charset("text/html", raw) == "gbk"
    raw2 = b'<html><head><meta charset="gb2312"><title>x</title></head>'
    assert S._web_detect_charset("", raw2) == "gb2312"


def test_charset_default():
    assert S._web_detect_charset("", b"<html><body>plain") == "utf-8"
    assert S._web_detect_charset(None, b"") == "utf-8"


def test_html_to_text_basic():
    title, body = S._web_html_to_text(
        "<html><head><title>构建 &amp; 测试</title><style>.x{}</style>"
        "<script>var a=1;</script></head>"
        "<body><p>第一段</p><div>第二段</div><!-- 注释 -->"
        "<br>第三行 &lt;tag&gt;</body></html>")
    assert title == "构建 & 测试"
    assert "第一段" in body and "第二段" in body and "第三行 <tag>" in body
    assert ".x{}" not in body and "var a" not in body and "注释" not in body
    assert body.splitlines() == ["第一段", "第二段", "第三行 <tag>"]


def test_html_to_text_title_entities_and_len():
    t, _ = S._web_html_to_text("<title>" + "长" * 300 + "</title><body>x</body>")
    assert len(t) == 120   # title 截断 120
