# -*- coding: utf-8 -*-
"""a473 网页取页纯函数回归（charset 三跳探测 + HTML→文本）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import web_proxy as W  # noqa: E402


def test_charset_quoted_header():
    """审计实锤：RFC 9110 合法的 charset="GBK" 原正则失配 → 全页乱码。"""
    assert W._web_detect_charset('text/html; charset="GBK"', b"") == "gbk"
    assert W._web_detect_charset("text/html; charset='gb18030'", b"") == "gb18030"


def test_charset_plain_header():
    assert W._web_detect_charset("text/html; charset=utf-8", b"") == "utf-8"
    assert W._web_detect_charset("application/json", b"") == "utf-8"


def test_charset_meta_fallback():
    """老内网页只写 meta 不写 header——body 前 2KB 兜底。"""
    raw = '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gbk">'.encode("ascii")
    assert W._web_detect_charset("text/html", raw) == "gbk"
    raw2 = b'<html><head><meta charset="gb2312"><title>x</title></head>'
    assert W._web_detect_charset("", raw2) == "gb2312"


def test_charset_default():
    assert W._web_detect_charset("", b"<html><body>plain") == "utf-8"
    assert W._web_detect_charset(None, b"") == "utf-8"


def test_html_to_text_basic():
    title, body = W._web_html_to_text(
        "<html><head><title>构建 &amp; 测试</title><style>.x{}</style>"
        "<script>var a=1;</script></head>"
        "<body><p>第一段</p><div>第二段</div><!-- 注释 -->"
        "<br>第三行 &lt;tag&gt;</body></html>")
    assert title == "构建 & 测试"
    assert "第一段" in body and "第二段" in body and "第三行 <tag>" in body
    assert ".x{}" not in body and "var a" not in body and "注释" not in body
    assert body.splitlines() == ["第一段", "第二段", "第三行 <tag>"]


def test_html_to_text_title_entities_and_len():
    t, _ = W._web_html_to_text("<title>" + "长" * 300 + "</title><body>x</body>")
    assert len(t) == 120   # title 截断 120


def test_multi_script_full_strip():
    """a474 审计 B 轮补钉：re.sub 位置参数 count=2 的回归（第 3 个 script
    块起曾漏剥）。"""
    t, b = W._web_html_to_text(
        "<script>1</script><script>2</script><script>LEAK3</script>"
        "<style>s3</style><p>ok</p><script>LEAK4</script>")
    assert "LEAK3" not in b and "LEAK4" not in b and "s3" not in b and "ok" in b


def test_bom_stripped():
    t, b = W._web_html_to_text("<body>\ufeff正文</body>")
    assert b == "正文"


def test_invalid_charset_falls_back():
    """无效编码名（charset=unicode 老页面）不整页失败——由路由 try 兜，
    这里钉探测函数的返回形态（名字原样返回，由调用方 try LookupError）。"""
    raw = b'<meta charset="unicode">x'
    cs = W._web_detect_charset("", raw)
    assert isinstance(cs, str) and len(cs) > 0
    try:
        raw.decode(cs, "replace")
        ok = True
    except LookupError:
        ok = False
    assert ok is False   # 确认路由的 try 分支是必要路径


def test_bom_stripped_with_leading_space():
    """a477 lstrip 形态钉住（审计 O2）：BOM 后跟标签占位空格的正文首行。"""
    t, b = W._web_html_to_text("<body>\ufeff <p>正文</p></body>")
    assert b == "正文", repr(b)
    t2, b2 = W._web_html_to_text("<body>\ufeff\n<p>换行形态</p></body>")
    assert b2 == "换行形态", repr(b2)
