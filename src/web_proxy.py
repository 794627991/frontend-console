# -*- coding: utf-8 -*-
"""Web 服务模块（a544 终局形态精简）。

WebView2 控件架构（src/web_tabs.py）下，代理路由/NAV_JS 注入/h2 端口/
404 兜底全部退役（用户令「没用全删」）。本模块只保留与 iframe/代理无关
的独立功能：
- /api/web/fetch_text：取页转纯文本（阅读模式 / 收藏命名 / 发给 Claude）
- _web_detect_charset / _web_html_to_text：纯函数（tests 直测，a473 起）

a502~a543 的同源代理演进史见 git log（XFO 绕行→会话→路径式→h2），
被控件架构整体取代。
"""

from flask import Blueprint, jsonify, request

bp = Blueprint("web_proxy", __name__)


def _web_detect_charset(headers_ct, raw):
    """a473/审计修：charset 三跳探测（纯函数，tests 直测）。

    ① Content-Type 的 charset=（RFC 9110 允许带引号 charset="GBK"——
    审计实证带引号形态原正则失配回落 utf-8 全页乱码）
    ② body 前 2KB 的 <meta charset=…>（老内网页只写 meta 不写 header）
    ③ 兜底 utf-8"""
    import re as _re
    m = _re.search(r'charset=["\']?([\w-]+)', (headers_ct or "").lower())
    if m:
        return m.group(1)
    head = raw[:2048].decode("ascii", "replace").lower()
    m = _re.search(r'<meta[^>]+charset=["\']?([\w-]+)', head)
    if m:
        return m.group(1)
    return "utf-8"


def _web_html_to_text(html_src):
    """a473/审计修：HTML→纯文本（纯函数）。返回 (title, body)。"""
    import html as _html
    import re as _re
    title = ""
    m = _re.search(r"<title[^>]*>([\s\S]*?)</title>", html_src, _re.I)
    if m:
        title = _html.unescape(_re.sub(r"\s+", " ", m.group(1))).strip()[:120]
    # 审计修（隐藏级）：re.sub 第 4 个位置参数是 count 不是 flags——
    # flags 一律关键字传参（a474 实锤：count=2 时长页面第 3 个 script
    # 起全部漏剥）
    body = _re.sub(r"<(script|style|noscript|title)[^>]*>[\s\S]*?</\1>", " ",
                   html_src, flags=_re.I)
    body = _re.sub(r"<!--[\s\S]*?-->", " ", body)
    body = _re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>|</h[1-6]>", "\n",
                   body, flags=_re.I)
    body = _re.sub(r"<[^>]+>", " ", body)
    body = _html.unescape(body)
    body = _re.sub(r"[ \t\r\f\v]+", " ", body)
    body = _re.sub(r"\n\s*\n\s*", "\n", body)
    body = "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())
    if body.startswith("\ufeff"):
        body = body[1:].lstrip()   # BOM 残留正文首行清理
    return title, body


@bp.route("/api/web/fetch_text", methods=["POST"])
def api_web_fetch_text():
    """a473：取页转纯文本（阅读模式 / 收藏命名 / 「发给 Claude」）。

    轻量 HTML→文本：去 script/style/注释/标签 + 实体解码，不引依赖。
    上限：响应体 5MB、正文 40K 字符。内网 https 自签不校验（本地单用户
    工具语境，与浏览器「继续访问」同权）。"""
    import ssl as _ssl
    import urllib.request
    data = request.get_json(force=True, silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "err": "仅支持 http(s) 链接"}), 400
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            raw = r.read(5 * 1024 * 1024)
            cs = _web_detect_charset(r.headers.get("Content-Type"), raw)
            try:
                text = raw.decode(cs, "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
    except Exception as e:
        return jsonify({"ok": False, "err": "取页失败：%s" % str(e)[:180]})
    title, body = _web_html_to_text(text)
    capped = len(body) > 40000
    return jsonify({"ok": True, "url": url, "title": title,
                    "text": body[:40000], "truncated": capped})


def register(app):
    """挂载（server.py 调用）。"""
    app.register_blueprint(bp)
