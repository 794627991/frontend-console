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

from src import server as S  # noqa: E402


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
    assert S._proxy_sanitize_setcookie(sc) == "sessionid=abc123; HttpOnly; Path=/"


def test_sanitize_keeps_attrs_and_appends_path():
    assert S._proxy_sanitize_setcookie("token=x") == "token=x; Path=/"
    assert S._proxy_sanitize_setcookie(
        "a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT") == \
        "a=1; Expires=Wed, 21 Oct 2099 07:28:00 GMT; Path=/"


def test_sanitize_empty():
    assert S._proxy_sanitize_setcookie("") == ""
    assert S._proxy_sanitize_setcookie(None) == ""
    assert S._proxy_sanitize_setcookie("Domain=x.com; Secure") == ""


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
    # 绝对代理 URL（相对 Location 会被部分客户端按 <base> 解析，绝对最稳）
    assert "/api/web/proxy?url=" in r.headers["Location"]
    assert r.headers["Location"].startswith("http://")
    assert "http%3A%2F%2Fsrv%2Fmain" in r.headers["Location"]
    # 302 中间响应的 Set-Cookie 不丢（urllib 自动跟随时会吞掉）
    assert r.headers.getlist("Set-Cookie") == ["sessionid=abc; Path=/"]


def test_302_absolute_location(monkeypatch):
    op = _FakeOpener(_http_error(301, location="http://other/x"))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2Fsrv%2Fa")
    assert r.status_code == 301
    assert "http%3A%2F%2Fother%2Fx" in r.headers["Location"]


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


# ---------- 404 兜底：location.href='/main' 类 JS 跳转 ----------

_REF = ("http://127.0.0.1:49302/api/web/proxy?url="
        "http%3A%2F%2F10.17.97.73%3A8765%2Flogin")

def test_404_fallback_redirects_to_proxy():
    c = S.app.test_client()
    r = c.get("/main", headers={"Referer": _REF,
                                "Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 302
    assert "http%3A%2F%2F10.17.97.73%3A8765%2Fmain" in r.headers["Location"]


def test_404_fallback_keeps_query():
    c = S.app.test_client()
    r = c.get("/main?tab=1&x=2", headers={"Referer": _REF,
                                          "Accept": "text/html"})
    assert "http%3A%2F%2F10.17.97.73%3A8765%2Fmain%3Ftab%3D1%26x%3D2" \
        in r.headers["Location"]


def test_404_ajax_not_redirected():
    c = S.app.test_client()
    r = c.get("/api/whatever", headers={"Referer": _REF,
                                        "Accept": "application/json"})
    assert r.status_code == 404          # fetch 期待原状态码，不动
    # POST 不兜（只兜 GET 导航）；POST 未知路径命中静态 path 路由的
    # method 限制 → 405，同样不是 302 即达标
    r2 = c.post("/main", headers={"Referer": _REF,
                                  "Accept": "text/html"})
    assert r2.status_code != 302


def test_404_without_proxy_referer_untouched():
    c = S.app.test_client()
    assert c.get("/nope").status_code == 404
    assert c.get("/nope", headers={
        "Referer": "http://10.17.97.73:8765/login",
        "Accept": "text/html"}).status_code == 404


def test_404_loop_guard(monkeypatch):
    # 重定向目标必是 /api/web/proxy（有路由），不该再进 404；即使原始站点
    # 自身 404，代理透传状态码（路由命中）不触发兜底——用假 opener 钉住
    op = _FakeOpener(urllib.error.HTTPError(
        "http://10.17.97.73:8765/main", 404, "msg",
        _msg({"Content-Type": "text/html"}), io.BytesIO(b"<html><head></head><body>404</body></html>")))
    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: op)
    c = S.app.test_client()
    r = c.get("/api/web/proxy?url=http%3A%2F%2F10.17.97.73%3A8765%2Fmain")
    assert r.status_code == 404          # 透传，不是 302
