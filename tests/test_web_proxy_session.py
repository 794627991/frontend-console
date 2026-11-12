# -*- coding: utf-8 -*-
"""a505 代理会话三件套回归：Cookie 转发 / Set-Cookie 透传 / 302 透传 / 404 兜底。

背景实锤：内网系统（10.17.97.73:8765）登录 POST 200 成功（a504 拦截 fetch
已通）但无法跳转、也无报错——三处断层：
①请求侧不转发浏览器 Cookie → 服务器看到的全是未登录请求；
②Set-Cookie 不透传（且带 Domain/Secure 属性浏览器要拒收）→ session 丢失；
③JS 跳转 location.href='/main' 在代理域 404（location 赋值拦不住）。
"""
import email.message
import io
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import server as S      # noqa: E402  (app)
from src import web_proxy as W  # noqa: E402


def _msg(hdrs):
    m = email.message.Message()
    for k, v in hdrs.items():
        m[k] = v
    return m


class _FakeResp:
    def __init__(self, raw=b"", hdrs=None, url="http://srv/"):
        self._raw = raw
        self.headers = _msg(hdrs or {})
        self._url = url

    def read(self, n=-1):
        return self._raw

    def geturl(self):
        return self._url


class _FakeOpener:
    """替身 opener：捕获代理发出的请求；result 是响应或待抛异常。"""

    def __init__(self, result):
        self.result = result
        self.last_req = None

    def open(self, req, timeout=None):
        self.last_req = req
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# ---------- 纯函数：Set-Cookie 清洗 ----------

def test_sanitize_strips_domain_secure_samesite_path():
    sc = ("sessionid=abc123; Domain=10.17.97.73; Path=/api; Secure; "
          "HttpOnly; SameSite=None")
    assert W._proxy_sanitize_setcookie(sc) == "sessionid=abc123; HttpOnly; Path=/"


def test_sanitize_keeps_attrs_and_appends_path():
    assert W._proxy_sanitize_setcookie("token=x") == "token=x; Path=/"
    assert W._proxy_sanitize_setcookie(
        "a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT") == \
        "a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT; Path=/"


def test_sanitize_empty():
    assert W._proxy_sanitize_setcookie("") == ""
    assert W._proxy_sanitize_setcookie(None) == ""
    assert W._proxy_sanitize_setcookie("Domain=x.com; Secure") == ""


# ---------- 请求侧：Cookie 转发 ----------

def test_browser_cookie_forwarded(monkeypatch):
    op = _FakeOpener(_FakeResp(
        b"<html><head></head><body>ok</body></html>", {}, "http://srv/"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    # werkzeug test client 会拦走 headers 里的 Cookie（也不透传
    # environ_overrides 的 HTTP_COOKIE），set_cookie 才等价于浏览器行为
    c.set_cookie("sessionid", "abc123")
    c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2F")
    assert "sessionid=abc123" in (op.last_req.headers.get("Cookie") or "")


def test_no_cookie_header_when_browser_sent_none(monkeypatch):
    op = _FakeOpener(_FakeResp(
        b"<html><head></head><body>ok</body></html>", {}, "http://srv/"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2F")
    assert "Cookie" not in op.last_req.headers


# ---------- 响应侧：Set-Cookie 透传 ----------

def test_setcookie_passthrough_on_html(monkeypatch):
    op = _FakeOpener(_FakeResp(
        b"<html><head></head><body>ok</body></html>",
        {"Set-Cookie": "sessionid=abc; Domain=srv; Path=/api; Secure"},
        "http://srv/"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2F")
    scs = r.headers.getlist("Set-Cookie")
    assert scs == ["sessionid=abc; Path=/"]


def test_setcookie_multiple(monkeypatch):
    op = _FakeOpener(_FakeResp(
        b"<html><head></head><body>ok</body></html>",
        {"Set-Cookie": "a=1; Path=/x, b=2"}, "http://srv/"))
    # email.Message 逗号拆多条：直接放两个头更真实
    m = _msg({})
    m["Set-Cookie"] = "a=1; Domain=srv"
    m["Set-Cookie"] = "b=2; Secure"
    op.result.headers = m
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2F")
    assert sorted(r.headers.getlist("Set-Cookie")) == ["a=1; Path=/", "b=2; Path=/"]


# ---------- 30x：不跟随 + Location 代理化 ----------

def _http_error(code, location=None, setcookie=None):
    hdrs = {}
    if location:
        hdrs["Location"] = location
    if setcookie:
        hdrs["Set-Cookie"] = setcookie
    e = urllib.error.HTTPError(
        "http://srv/login", code, "msg", _msg(hdrs), io.BytesIO(b""))
    return e


def test_302_passthrough_location_proxied(monkeypatch):
    op = _FakeOpener(_http_error(
        302, location="/main", setcookie="sessionid=abc; Domain=srv"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2Flogin")
    assert r.status_code == 302
    # a506：绝对路径式代理 URL（dirname 语义对 publicPath 类运行时正确）
    assert "/api/web/proxy/http/srv/main" in r.headers["Location"]
    assert r.headers["Location"].startswith("http://")
    # 302 中间响应的 Set-Cookie 不丢（urllib 自动跟随时会吞掉）
    assert r.headers.getlist("Set-Cookie") == ["sessionid=abc; Path=/"]


def test_302_absolute_location(monkeypatch):
    op = _FakeOpener(_http_error(301, location="http://other/x"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2Fa")
    assert r.status_code == 301
    assert "/api/web/proxy/http/other/x" in r.headers["Location"]


def test_302_without_location_falls_to_error_path(monkeypatch):
    # 无 Location 的 30x：无跳转可代理化，走错误码透传
    op = _FakeOpener(_http_error(302))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2Flogin")
    assert r.status_code == 302


def test_401_body_and_setcookie_passthrough(monkeypatch):
    e = urllib.error.HTTPError(
        "http://srv/api/login", 401, "msg",
        _msg({"Content-Type": "application/json",
              "Set-Cookie": "reset=1"}), io.BytesIO(b'{"err":"bad"}'))
    op = _FakeOpener(e)
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.post("/api/web/proxy?url=http%3A%2F%2Fsrv%2Fapi%2Flogin",
               data='{"p":"x"}', content_type="application/json")
    assert r.status_code == 401
    assert r.data == b'{"err":"bad"}'
    assert r.headers.getlist("Set-Cookie") == ["reset=1; Path=/"]


def test_post_body_and_ct_forwarded(monkeypatch):
    op = _FakeOpener(_FakeResp(
        b'{"ok":1}', {"Content-Type": "application/json"}, "http://srv/api/login"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.post("/api/web/proxy?url=http%3A%2F%2Fsrv%2Fapi%2Flogin",
               data='{"user":"u","pass":"p"}', content_type="application/json")
    assert r.status_code == 200
    assert op.last_req.data == b'{"user":"u","pass":"p"}'
    assert "application/json" in (op.last_req.headers.get("Content-type") or "")


# ---------- 404 兜底（a508 客户端还原页：sessionStorage.__px_orig）----------

_REF = "http://localhost/api/web/proxy/https/10.17.97.73:8765/login"

def test_404_fallback_returns_recovery_page():
    """a508：兜底改为 404+还原页（JS 读 sessionStorage 拼回代理路径）——
    replaceState 伪装后 Referer 不含代理前缀，服务端无从还原。"""
    c = S.app.test_client()
    r = c.get("/main", headers={"Referer": _REF,
                                "Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 404                       # 语义仍是 404
    assert b"__px_orig" in r.data                     # 还原脚本在
    assert b"Redirecting" in r.data


def test_404_ajax_untouched():
    c = S.app.test_client()
    r = c.get("/api/whatever", headers={"Referer": _REF,
                                        "Accept": "application/json"})
    assert r.status_code == 404          # fetch 期待原状态码，不动
    assert b"__px_orig" not in r.data    # 无还原脚本
    # POST 不兜（只兜 GET 导航）；POST 未知路径命中静态 path 路由的
    # method 限制 → 405
    r2 = c.post("/main", headers={"Referer": _REF,
                                  "Accept": "text/html"})
    assert r2.status_code == 405


def test_404_without_same_origin_referer_untouched():
    c = S.app.test_client()
    r = c.get("/nope")
    assert r.status_code == 404 and b"__px_orig" not in r.data
    # 外域 referer 不同源，不兜
    r2 = c.get("/nope", headers={
        "Referer": "http://10.17.97.73:8765/login",
        "Accept": "text/html"})
    assert r2.status_code == 404 and b"__px_orig" not in r2.data


def test_404_loop_guard(monkeypatch):
    # 原始站点自身 404 由代理路由透传（路由命中），不进兜底——用假 opener 钉住
    op = _FakeOpener(urllib.error.HTTPError(
        "http://10.17.97.73:8765/main", 404, "msg",
        _msg({"Content-Type": "text/html"}), io.BytesIO(b"<html><head></head><body>404</body></html>")))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2F10.17.97.73%3A8765%2Fmain")
    assert r.status_code == 404 and b"__px_orig" not in r.data


# ---------- a506：路径式代理 ----------

def test_url_rewrite_path_style():
    """重写函数产路径式（publicPath 的 dirname 语义正确）。"""
    fn = W._proxy_url_rewrite("https://github.com/zai-org/ZCode",
                              "http://127.0.0.1:49302/api/web/proxy")
    assert fn("https://github.githubassets.com/assets/app.js") == \
        "http://127.0.0.1:49302/api/web/proxy/https/github.githubassets.com/assets/app.js"
    # 相对路径基于页面 URL 解析
    assert fn("/assets/core-1.js") == \
        "http://127.0.0.1:49302/api/web/proxy/https/github.com/assets/core-1.js"
    # query 附加、fragment 丢弃（相对路径按 urljoin 目录语义：base 末段
    # ZCode 无尾斜杠视作文件名，a.js 替换它）
    assert fn("a.js?v=3#x") == \
        "http://127.0.0.1:49302/api/web/proxy/https/github.com/zai-org/a.js?v=3"
    # 非 http(s) / 空值原样返回
    assert fn("javascript:0") == "javascript:0"
    assert fn("#top") == "#top"
    assert fn("data:image/gif;base64,x") == "data:image/gif;base64,x"


def test_path_route_serves_and_forwards(monkeypatch):
    """/proxy/https/host/path 路由取页 + cookie 转发 + Set-Cookie 透传。"""
    op = _FakeOpener(_FakeResp(
        b"<html><head></head><body>ok</body></html>",
        {"Set-Cookie": "s=1; Domain=x; Secure"}, "http://srv:8765/a/b"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    c.set_cookie("s", "1")
    r = c.get("/api/web/proxy/http/srv:8765/a/b?q=1")
    assert r.status_code == 200
    assert b"ok" in r.data
    # 还原出的原始 URL（含 query）+ cookie 转发
    assert op.last_req.full_url == "http://srv:8765/a/b?q=1"
    assert "s=1" in (op.last_req.headers.get("Cookie") or "")
    assert r.headers.getlist("Set-Cookie") == ["s=1; Path=/"]


def test_path_route_webpack_chunk_semantics(monkeypatch):
    """核心场景：publicPath=代理 dirname → chunk 相对路径落回代理路由。"""
    op = _FakeOpener(_FakeResp(
        b"console.log(1)", {"Content-Type": "application/javascript"},
        "https://github.githubassets.com/assets/wp-runtime-abc.js"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy/https/github.githubassets.com/assets/wp-runtime-abc.js")
    assert r.status_code == 200
    assert op.last_req.full_url == \
        "https://github.githubassets.com/assets/wp-runtime-abc.js"


def test_404_fallback_any_same_origin_referer(monkeypatch):
    """a508：兜底条件放宽为同源 referer（replaceState 伪装后 referer 只剩
    origin，代理前缀在 pathname 里已不可见）——还原基址交给页面 JS。"""
    c = S.app.test_client()
    r = c.get("/apps", headers={"Referer": "http://localhost/",
                                "Accept": "text/html"})
    assert r.status_code == 404 and b"__px_orig" in r.data


def test_path_route_bad_url():
    c = S.app.test_client()
    # scheme 由 <any(http,https)> 约束，非法值走 404（兜底无 referer 不拦）
    assert c.get("/api/web/proxy/ftp/srv/x").status_code == 404


def test_importmap_urls_rewritten(monkeypatch):
    """a506：importmap JSON 里的 URL 必须代理化——裸模块名 import 走浏览器
    模块加载器（无属性/无 fetch hook），不重写则内网直接断 module graph
    （GitHub hydration 永不接管、commit 列永久骨架的根因）。"""
    _im = ('<script type="importmap">'
           '{"imports":{"react":"https://cdn.x.com/a.js",'
           '"react-dom/client":"https://cdn.x.com/b.js?ver=1"}'
           ',"scopes":{"/app/":{"x":"https://other.y.com/c.js"}}}'
           '</script>')
    op = _FakeOpener(_FakeResp(
        ("<html><head>" + _im + "</head><body>ok</body></html>").encode(),
        {"Content-Type": "text/html"}, "https://github.com/zai-org/ZCode"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy/https/github.com/zai-org/ZCode")
    assert r.status_code == 200
    _h = r.data.decode()
    # _fn 产绝对代理 URL（request.host 在 test client 下是 localhost）
    assert '"http://localhost/api/web/proxy/https/cdn.x.com/a.js"' in _h
    assert "http://localhost/api/web/proxy/https/cdn.x.com/b.js?ver=1" in _h
    assert "http://localhost/api/web/proxy/https/other.y.com/c.js" in _h
    assert '"https://cdn.x.com/a.js"' not in _h       # 原始 URL 不残留


def test_no_store_on_proxy_responses(monkeypatch):
    """a510：代理响应禁缓存（WebView2 缓存旧代理产物 → 升级后
    ERR_CACHE_READ_FAILURE / 执行过期注入逻辑）。"""
    op = _FakeOpener(_FakeResp(
        b"<html><head></head><body>ok</body></html>",
        {"Content-Type": "text/html"}, "http://srv/"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy/https/srv/")
    assert "no-store" in r.headers.get("Cache-Control", "")
