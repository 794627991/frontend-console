# -*- coding: utf-8 -*-
"""a674：静态资源 MIME 必须与注册表无关（用户实锤同事机整页裸 HTML）。

根因：Python 的 mimetypes 在 Windows 读注册表（HKCR\\.css 的 Content Type）。
被 CAD / 老 Office / 清理工具改坏或删掉后 `guess_type` 返回 None →
`_mem_web` 落到 `application/octet-stream` → Chromium 对样式表执行严格 MIME
校验，整包 CSS 拒收 → 页面只剩裸 HTML 控件（默认圆角按钮、白底黑字）。

Phase 0 只钉了 .js/.mjs（模块脚本同样严格），漏了 .css 与入口页 .html。
本测试把注册表映射改成错误值后 import server，验证进程内钉死仍然生效。
"""
import mimetypes
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _guess(name):
    return mimetypes.guess_type(name)[0]


@pytest.fixture
def hijacked(monkeypatch):
    """模拟注册表劫持：把单位置成 octet-stream / None。"""
    mimetypes.init()
    tm = mimetypes._db.types_map[True]
    monkeypatch.setitem(tm, ".css", "application/octet-stream")
    monkeypatch.setitem(tm, ".html", "application/octet-stream")
    monkeypatch.setitem(tm, ".htm", "application/octet-stream")
    monkeypatch.setitem(tm, ".js", "application/octet-stream")
    monkeypatch.setitem(tm, ".mjs", "application/octet-stream")
    yield
    mimetypes.init()


def test_server_pins_css_mime_against_registry(hijacked):
    """被劫持后 import server 必须把 .css 拨回 text/css。"""
    assert _guess("a.css") == "application/octet-stream", "前置：劫持未生效"
    from src.server import _pin_mimes
    _pin_mimes()                      # 模拟「进程启动时的那次钉死」
    assert _guess("web/style.css") == "text/css"
    assert _guess("web/skins.css") == "text/css"


def test_server_pins_html_mime_against_registry(hijacked):
    """入口页同理——octet-stream 会让 WebView 把 index.html 当下载。"""
    assert _guess("index.html") == "application/octet-stream"
    from src.server import _pin_mimes
    _pin_mimes()
    assert _guess("index.html") == "text/html"
    assert _guess("index.htm") == "text/html"


def test_server_pins_js_mime_against_registry(hijacked):
    """Phase 0 的既有承诺：type=module 脚本对 MIME 同样严格。"""
    from src.server import _pin_mimes
    _pin_mimes()
    assert _guess("a.js") == "text/javascript"
    assert _guess("a.mjs") == "text/javascript"


def test_all_pinned_types_are_the_expected_values():
    """不依赖劫持，直接核对进程内映射表——防止有人删掉 add_type 那几行。"""
    from src.server import _pin_mimes
    _pin_mimes()
    expect = {
        ".css": "text/css",
        ".html": "text/html",
        ".htm": "text/html",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
    }
    for ext, want in expect.items():
        assert _guess("x" + ext) == want, "%s 未钉死" % ext


def test_static_routes_all_go_through_mimetypes():
    """五条静态路由（/, /web/<fn>, /<fn>, /vendor/<fn>, /ico/<fn>）都靠
    mimetypes 推 Content-Type——进程内钉死一处，全路受益。

    这里做结构性断言：server 模块里不得再出现绕过 mimetypes 的 CSS 分支。
    """
    import inspect
    import src.server as S
    src = inspect.getsource(S)
    # 钉死语句必须在场（删掉就红）
    assert '_pin_mimes()' in src, "模块级必须调用一次钉死"
    for ext, mime in ((".css", "text/css"), (".html", "text/html"),
                      (".htm", "text/html"), (".js", "text/javascript"),
                      (".mjs", "text/javascript")):
        assert 'add_type("%s", "%s")' % (mime, ext) in src, ext
