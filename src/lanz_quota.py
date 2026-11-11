#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lanz_quota.py
=============
海康 Lanz 平台（lanz.hikvision.com）API 额度查询客户端。

为 claude_proxy_gui.pyw 提供：登录 Lanz 平台、查询 API 使用情况与额度。
纯客户端模块，不 import tkinter，可被 GUI 复用也可独立 CLI 调试。

认证机制（已逆向验证）：
    1. CAS 单点登录（sso.hikvision.com）
       GET /resource/dashboard → 302 到 sso 登录页 → 提取 lt/execution/salt
       → RSA(PKCS1v15) 加密 (salt+明文密码) → POST 表单 → 拿 session cookie
    2. API 请求带 Swms-Request-Token 头
       AES-CBC-PKCS7 加密 "SWMS_<uuid4>_<毫秒时间戳>" → base64
       （服务端只校验头存在且可解密，不校验内容，每次随机生成即可）

额度 API（base /v1/ai-resource，成功 code=2001，未授权 code=3001）：
    /dashboard        总览（今日已用/上限、总积分、剩余、模型排名、趋势）
    /budget/overview  部门预算卡片
    /records          使用记录明细（分页）
    /creditPricing    模型积分定价
    /budget/isAdmin   是否管理员

网络层用标准库 urllib（不引入 requests），绕过系统代理（公司代理环境会挂），
禁用 SSL 证书校验（内网证书 Missing Authority Key Identifier）。
加密用 pycryptodome（RSA + AES 一个库搞定）。
"""

import base64
import http.cookiejar
import json
import logging
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

log = logging.getLogger("claude_proxy_lanz")

# ---- 常量 ------------------------------------------------------------
LANZ_DASHBOARD = "https://lanz.hikvision.com/resource/dashboard"
API_BASE = "https://lanz.hikvision.com/v1/ai-resource"
SSO_HOME = "https://sso.hikvision.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REQUEST_TIMEOUT = 15

# CAS 登录页 RSA 公钥（PKCS#8 DER，base64），从 sso.hikvision.com/js/rsa_public_key.js 提取。
# 1024 位，固定不变（页面写死）。
RSA_PUB_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCqc90wxTr7Biug8nciEMrSygRg"
    "Yvo31+shw+gxp0LqVbVCeGklV/Mwx7HXeGbbK9HHHAORE6lDgIb7tgCPZHygA2v"
    "JtBhlhIy2IgHDpsp8Hv0UjwCML8/6KvChE3YChPffs6UUUgwJOQiDWOe/i2dCT4"
    "J2p/AR1kFcd2UFEGaW1QIDAQAB"
)
# Swms-Request-Token 的 AES-CBC 密钥/IV（从 app.js 模块 9685 提取，写死）。
AES_KEY = b"139074101@SR&LYJ"   # 16 字节
AES_IV = b"N6s87ssQyWB9ZRFK"    # 16 字节


# ---- 异常 ------------------------------------------------------------
class LanzError(Exception):
    """Lanz 客户端基类异常。"""


class LanzAuthError(LanzError):
    """登录失败（用户名/密码错、登录页结构变化）。"""


class LanzSessionExpired(LanzError):
    """API 返回 code=3001，会话过期需重新登录。"""


class LanzNetworkError(LanzError):
    """网络异常（超时/DNS/SSL/连接失败）。"""


# ---- 加密（pycryptodome）--------------------------------------------
_RSA_KEY = None
_AES_CIPHER_LOCK = threading.Lock()  # pycryptodome 的 cipher 对象非线程安全，串行用


def _rsa_key():
    """惰性加载并缓存 RSA 公钥。RSA.import_key 原生吃 PKCS#8 DER。"""
    global _RSA_KEY
    if _RSA_KEY is None:
        from Crypto.PublicKey import RSA
        _RSA_KEY = RSA.import_key(base64.b64decode(RSA_PUB_B64))
    return _RSA_KEY


def encrypt_password(plain, salt):
    """CAS 登录密码加密：RSA(PKCS1v15)(salt + 明文) → base64。

    页面逻辑：salt（每次登录页随机）+ 明文密码拼接后 RSA 加密。
    """
    from Crypto.Cipher import PKCS1_v1_5
    msg = (salt + plain).encode("utf-8")
    cipher = PKCS1_v1_5.new(_rsa_key())
    enc = cipher.encrypt(msg)
    return base64.b64encode(enc).decode("ascii")


def make_swms_token():
    """生成 Swms-Request-Token 请求头值。

    AES-CBC-PKCS7 加密 "SWMS_<uuid4>_<毫秒时间戳>" → base64。
    服务端只校验头存在且可解密，不校验内容，每次随机生成即可。
    """
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    raw = ("SWMS_%s_%d" % (uuid.uuid4(), int(time.time() * 1000))).encode("ascii")
    with _AES_CIPHER_LOCK:
        ct = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(raw, AES.block_size))
    return base64.b64encode(ct).decode("ascii")


# ---- 登录页字段提取 --------------------------------------------------
def _extract_field(html, name=None, id_attr=None):
    """从登录页 HTML 提取 <input> 隐藏字段值。容忍 name/value 属性顺序。

    用 (?<![-\\w]) 排除 data-value/data-name 等 data-*/aria-* 属性
    （否则 <input name="lt" value="real" data-value="x"> 会取到 data-value）。
    返回 value 字符串或 None。"""
    key = ('name="%s"' % name) if name else ('id="%s"' % id_attr)
    # name 在 value 前 / value 在 name 前 两种顺序都试；value 前加 lookbehind
    # 排除 -或字母数字前缀（data-value 的 value 前是 '-'）
    for pat in (r'<input[^>]*\b' + key + r'[^>]*(?<![-\w])value="([^"]*)"',
                r'<input[^>]*(?<![-\w])value="([^"]*)"[^>]*\b' + key):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def _classify_nonjson(raw):
    """识别非 JSON 响应正文的类型，返回可读根因字符串；无法识别返回 None。

    用于 _request 解析失败时把 "char 0" 这种无信息报错转成具体原因：
    账号锁定 / 凭据错误 / 会话失效重定向回登录页 / WAF 拦截 / 空响应。
    """
    if not raw or not raw.strip():
        return "响应为空（服务端未返回内容，可能网关超时或 WAF 拦截）"
    s = raw[:600]
    low = s.lower()
    # SSO 登录页特征：HikLink Single Sign-On / sso.hikvision.com / <form ...login>
    is_login_page = ("single sign-on" in low or "sso.hikvision.com" in low
                     or ("<form" in low and "login" in low))
    if is_login_page:
        # 登录页里可能嵌着具体错误文案（<div id="msg">）
        m = re.search(r'<div id="msg">([^<]*)</div>', raw, re.I)
        msg = m.group(1).strip() if m else ""
        # 转义实体还原
        for ent, ch in (("&ldquo;", "“"), ("&rdquo;", "”"),
                        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
            msg = msg.replace(ent, ch)
        msg_low = msg.lower()
        # 优先级1：账号锁定 / 尝试次数超限
        # a446（用户实锤）：SSO 锁定期的实际文案是 "Too many attempts,
        # please contact itsm@..."，原关键词表只有 locked/error limit，
        # 命中不了就一路降级成「会话失效」——误导用户以为是自己的会话
        # 掉了，实际是账号被风控锁了、必须等或联系 ITSM。
        if ("too many attempts" in msg_low or "locked" in msg_low
                or "error limit" in msg_low
                or "too many" in msg_low and "attempt" in msg_low):
            return ("账号已被 SSO 锁定（登录尝试次数超限）。请等待锁定自动解除"
                    "（约 8~30 分钟），或联系 itsm@hikvision.com 解锁；"
                    "解锁前任何登录尝试都会重新计时。"
                    + (" 服务端提示: %s" % msg if msg else ""))
        # 优先级2：凭据错误（"Wrong username or password"）
        if "wrong" in msg_low or "password" in msg_low or "invalid" in msg_low:
            return ("用户名或密码错误。" + (" 服务端提示: %s" % msg if msg else "")
                    + " 注意：连续错误会锁定 SSO 账号。")
        # 优先级3：登录页带其他提示
        if msg:
            return "登录失败，被重定向回 SSO 登录页。服务端提示: %s" % msg
        # 优先级4：登录页但无 msg（会话失效被重定向，非主动登录失败）
        return ("会话失效，请求被重定向回 SSO 登录页。"
                "可能账号已锁定或凭据失效，请稍后重试或检查 SSO 账号状态。")
    # gzip/压缩残留：magic bytes 0x1f 0x8b，或大量不可打印字符
    if raw[:1] == "\x1f" or sum(1 for c in raw[:64] if ord(c) < 9 or 14 <= ord(c) < 32) > 32:
        return ("响应疑似压缩/二进制正文（未按 Accept-Encoding:identity 返回）。"
                "body前64字节: %r" % raw[:64])
    # HTML 但非登录页（WAF 拦截页、错误页等）
    if low.startswith("<!doctype") or low.startswith("<html") or "<title>" in low:
        m = re.search(r"<title>(.*?)</title>", s, re.I | re.S)
        title = m.group(1).strip() if m else ""
        return ("响应为 HTML 而非 JSON（可能 WAF 拦截或网关错误页）。"
                + (" 标题: %s" % title if title else "")
                + " body前200: %r" % raw[:200].replace("\n", " "))
    return None


# ---- LanzClient ------------------------------------------------------
class LanzClient:
    """海康 Lanz 平台 API 客户端。

    用法：
        c = LanzClient("user", "pass")
        c.login()              # CAS 登录，拿 session cookie
        ov = c.get_dashboard() # 查额度总览
        # ... API 返 3001 会话过期时调 c.login(force=True) 重登
    """

    def __init__(self, username, password, timeout=REQUEST_TIMEOUT):
        self.username = username
        self.password = password
        self._timeout = timeout
        self._jar = None           # http.cookiejar.CookieJar
        self._opener = None        # urllib opener（带 cookie 处理）
        self._logged_in = False
        self._lock = threading.Lock()  # 串行化登录/重登录

    @property
    def logged_in(self):
        return self._logged_in

    def _make_opener(self):
        """构造带 cookie 处理、绕过系统代理、禁用 SSL 校验的 opener。"""
        self._jar = http.cookiejar.CookieJar()
        ctx = ssl._create_unverified_context()  # 内网证书 Missing AKI
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.ProxyHandler({}),       # 绕过系统代理（公司代理会挂）
            urllib.request.HTTPSHandler(context=ctx))
        # Accept-Encoding: identity 明确要求服务端不压缩。否则部分网关/WAF 会
        # 返回 gzip 正文，urllib 不自动解压 → json.loads 收到二进制乱码 →
        # "响应非 JSON: expecting value: line 1 column 1 (char 0)"（gzip magic \x1f
        # 不是有效 JSON 起始字符，报错位置恰为 char 0）。
        self._opener.addheaders = [
            ("User-Agent", UA), ("Accept-Encoding", "identity")]

    def _fetch_text(self, url, data=None, extra_headers=None):
        """用 opener 发请求，返回响应文本。网络异常转 LanzNetworkError。

        HTTPError 读响应体前几百字节拼进消息（SSO 锁号/风控常在 401/403/500
        响应体里写明原因，丢弃会让 GUI 误报"网络错误"导致用户反复重试）。
        """
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            resp = self._opener.open(req, timeout=self._timeout)
            return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            # 读响应体前 500 字节做诊断（SSO 锁号/凭据错常在 body 里写中文提示）
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            msg = "HTTP %d: %s" % (e.code, url)
            if body:
                msg += " | body: %s" % body.replace("\n", " ")[:200]
            raise LanzNetworkError(msg)
        except urllib.error.URLError as e:
            raise LanzNetworkError("URL错误: %s" % e.reason)
        except (ssl.SSLError, OSError) as e:
            raise LanzNetworkError("网络异常: %s" % e)

    def login(self, force=False):
        """CAS 两步登录。幂等：已登录且非 force 直接返回。

        成功 → self._logged_in=True；失败抛 LanzAuthError / LanzNetworkError。
        用 /dashboard API 返回 code==2001 作为登录成功最终判据
        （不依赖 302 跳转 URL 细节，更可靠）。
        """
        with self._lock:
            if self._logged_in and not force:
                return
            self._logged_in = False
            self._make_opener()
            try:
                # 1) GET dashboard → opener 自动跟随 302 到 sso 登录页
                html = self._fetch_text(LANZ_DASHBOARD)
                lt = _extract_field(html, name="lt")
                exe = _extract_field(html, name="execution")
                salt = _extract_field(html, id_attr="salt")
                m = re.search(r'<form[^>]*\baction="([^"]+)"', html, re.I)
                action = m.group(1) if m else None
                if not (lt and exe and salt and action):
                    raise LanzAuthError(
                        "登录页结构变化：缺少 lt/execution/salt/action 字段")
                # 2) POST 表单
                form = urllib.parse.urlencode({
                    "username": self.username,
                    "password": encrypt_password(self.password, salt),
                    "localDate": "",
                    "lt": lt,
                    "execution": exe,
                    "_eventId": "submit",
                    "ver": "2.0",
                    "loginForm": "qrLoginForm",
                    "fingerprint": "",
                }).encode("utf-8")
                action_url = action if action.startswith("http") else SSO_HOME + action
                # action 来自服务器 HTML，禁用 SSL 校验下可被 MITM 篡改指向攻击者
                # 主机。只允许相对路径或 sso.hikvision.com，否则凭据（RSA 加密的
                # 密码）会被 POST 到攻击者服务器。
                try:
                    parsed = urllib.parse.urlparse(action_url)
                    if parsed.scheme not in ("http", "https"):
                        raise LanzAuthError("登录页 action 非法（非 http(s)）: %s" % action)
                    if parsed.netloc and parsed.netloc != urllib.parse.urlparse(SSO_HOME).netloc:
                        raise LanzAuthError("登录页 action 指向非 SSO 主机: %s" % parsed.netloc)
                except LanzAuthError:
                    raise
                except Exception as e:
                    raise LanzAuthError("登录页 action 解析失败: %s" % e)
                self._fetch_text(
                    action_url, data=form,
                    extra_headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": SSO_HOME,
                        "Referer": action_url,  # 登录表单的 action URL
                    })
                # 3) 最终验证：dashboard API 返回 2001
                #    （POST 后 opener 已跟随 302 回 dashboard，cookie 已就位）
                self._request("/dashboard", _login_check=True)
                self._logged_in = True
                log.info("Lanz 登录成功: %s", self.username)
            except LanzError:
                raise
            except Exception as e:
                # 未知异常归为登录失败，带上下文便于定位
                raise LanzAuthError("登录失败: %s" % e)

    def _swms_headers(self):
        """API 请求头：Swms-Request-Token + Referer。"""
        return {
            "Swms-Request-Token": make_swms_token(),
            "Referer": LANZ_DASHBOARD,
        }

    def _request(self, path, _login_check=False):
        """GET API_BASE+path，解 JSON，返回 data 字段。

        code==2001 → 返回 data
        code==3001 → LanzSessionExpired（_login_check 时为 LanzAuthError），
                     并清 _logged_in 使 login() 不带 force 也能重登
        code!=2001 → LanzError
        响应非 dict → LanzError（服务端/WAF 返 null/[]/裸串时 d.get 会崩）
        网络异常   → LanzNetworkError
        """
        url = API_BASE + path
        try:
            raw = self._fetch_text(url, extra_headers=self._swms_headers())
            d = json.loads(raw)
        except LanzError:
            raise
        except (ValueError, json.JSONDecodeError) as e:
            # 登录校验时拿不到 JSON = POST 后没跳到 dashboard（停在登录页），
            # 即凭据无效；否则是真异常（API 返了非 JSON 正文）。
            # 先识别响应正文类型，给出可读根因，而非光秃秃的 "char 0"。
            hint = _classify_nonjson(raw)
            if _login_check:
                # 登录后仍拿到登录页 = 凭据无效或账号被锁
                raise LanzAuthError(hint or "用户名或密码错误（登录后未授权）")
            # 非 login_check：会话失效被网关重定向回登录页，或 WAF/网关拦截
            raise LanzError(hint or ("响应非 JSON: %s | body前200: %r"
                                     % (e, raw[:200].replace("\n", " ")
                                        if raw else "")))
        if not isinstance(d, dict):
            raise LanzError("响应结构异常（非 JSON 对象）: %r" % type(d).__name__)
        code = d.get("code")
        if code == 2001:
            return d.get("data")
        if code == 3001:
            self._logged_in = False  # 清标志，login() 不带 force 也能重登
            if _login_check:
                # 登录后立即 3001 = 凭据无效或会话没建立
                raise LanzAuthError("用户名或密码错误（登录后未授权）")
            raise LanzSessionExpired("会话过期（3001）")
        raise LanzError("API 返回错误 code=%s msg=%s" % (code, d.get("msg", "")))

    # ---- 业务方法（薄封装）----
    def get_dashboard(self):
        """额度总览。返回 overview + trend + modelRank + modelTrend。"""
        return self._request("/dashboard")

    def get_budget_overview(self):
        """部门预算卡片。非管理员可能无权，调用方应捕获 LanzError。"""
        return self._request("/budget/overview")

    def get_records(self, page=1, size=20):
        """使用记录明细（分页）。page>=1，1<=size<=100。"""
        try:
            page = int(page)
            size = int(size)
        except (TypeError, ValueError):
            raise LanzError("get_records 参数需为整数: page=%r size=%r" % (page, size))
        if page < 1 or not (1 <= size <= 100):
            raise LanzError("get_records 参数越界: page=%d size=%d" % (page, size))
        return self._request("/records?page=%d&size=%d" % (page, size))

    def get_credit_pricing(self):
        """模型积分定价。"""
        return self._request("/creditPricing")

    def is_admin(self):
        """是否管理员。"""
        return self._request("/budget/isAdmin")

    def get_model_loads(self):
        """模型实时负载（a442 用户需求：代理悬浮卡与面板显示模型负载）。

        数据源与 API 密钥申请页同源：GET /v1/openai/models（不在
        /v1/ai-resource 前缀下，故走完整 URL）。每项 routeStatus 提供
        total_active / effective_max_concurrent，负载百分比按前端口径
        min(100, floor(active/max*100)) 计算；缺字段返回 None。

        返回 [{"name","type","ctx","tags","available","active","max","pct","level"}]
        level: jam(>85) / busy(>70) / normal(>=40) / idle(else)
        无权限或接口异常时抛 LanzError，由调用方降级。
        """
        url = "https://lanz.hikvision.com/v1/openai/models"
        raw = self._fetch_text(url, extra_headers=self._swms_headers())
        try:
            d = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as e:
            raise LanzError("模型负载响应非 JSON: %s" % e)
        if not isinstance(d, dict):
            raise LanzError("模型负载响应结构异常: %r" % type(d).__name__)
        code = d.get("code")
        if code == 3001:
            self._logged_in = False
            raise LanzSessionExpired("会话过期（3001）")
        if code != 2001:
            raise LanzError("模型负载接口返回 code=%s msg=%s"
                            % (code, d.get("msg", "")))
        out = []
        for m in (d.get("data") or []):
            if not isinstance(m, dict):
                continue
            # a452（审计）：`or {}` 只兜 None/空值，上游把 routeStatus 漂移成
            # list/str 时 rs.get 直接 AttributeError，整批负载被丢且每 20s
            # 报一次（a452 给 modelTags 修的就是同一类，这里漏了）。
            rs = m.get("routeStatus")
            if not isinstance(rs, dict):
                rs = {}
            active = rs.get("total_active")
            mx = rs.get("effective_max_concurrent")
            # a452（审计 P2）：原判据 isinstance(..., int) 放行 bool（True 被
            # 当成 1），且未校验 active >= 0——上游口径漂移返回 -1 时算出负
            # pct，前端 width:-N% 与「--」判定全部失配。用 type() is int 精确
            # 排除 bool，并要求非负。
            def _cnt(v):
                return v if type(v) is int and v >= 0 else None
            active, mx = _cnt(active), _cnt(mx)
            pct = None
            if active is not None and mx:
                pct = min(100, int(active * 100 // mx))
            if pct is None:
                level = None
            elif pct > 85:
                level = "jam"
            elif pct > 70:
                level = "busy"
            elif pct >= 40:
                level = "normal"
            else:
                level = "idle"
            # a452（审计 P2）：modelTags 原假定是 str，服务端返回 list/数字时
            # `.split` 抛 AttributeError，被上层当「负载查询异常」整批丢弃并
            # 每 20s 报一次。容忍 str（分号分隔）/list/tuple/None。
            _tags = m.get("modelTags")
            if isinstance(_tags, str):
                _tags = [t for t in _tags.split(";") if t]
            elif isinstance(_tags, (list, tuple)):
                _tags = [str(t) for t in _tags if t]
            else:
                _tags = []
            out.append({
                "name": m.get("modelName") or "",
                "type": m.get("type") or "",
                "ctx": m.get("contextSize") or "",
                "tags": _tags,
                "available": rs.get("available"),
                "active": active,
                "max": mx,
                "pct": pct,
                "level": level,
            })
        return out


# ---- 凭据读写 --------------------------------------------------------
def load_credentials(path):
    """读取凭据文件。返回 {"username":..., "password":...} 或 None。

    文件缺失/JSON 损坏返回 None 并 log，不抛（启动时不该因凭据问题崩）。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            log.warning("凭据文件非 JSON 对象，忽略: %r", type(d).__name__)
            return None
        user = d.get("username")
        pwd = d.get("password")
        if user and pwd:
            return {"username": user, "password": pwd}
    except (ValueError, OSError) as e:
        log.warning("读取凭据文件失败，忽略: %s", e)
    return None


def save_credentials(path, username, password):
    """保存凭据到文件。原子写（唯一 tmp + os.replace），utf-8。

    格式 {"version":1, "username":..., "password":...}（明文）。
    用 tempfile.mkstemp 生成唯一 tmp 名（固定名在并发写时会交错产出坏 JSON），
    失败时 finally 清理孤儿 tmp。
    """
    import tempfile
    d = {"version": 1, "username": username, "password": password}
    fd = None
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None  # 已交给 with，勿重复 close
            json.dump(d, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
        tmp = None  # 已 replace，无需清理
        log.info("凭据已保存: %s", path)
    except OSError as e:
        log.error("保存凭据失败: %s", e)
        raise
    finally:
        if fd is not None:
            try: os.close(fd)
            except OSError: pass
        if tmp is not None:
            try: os.remove(tmp)
            except OSError: pass


def delete_credentials(path):
    """删除凭据文件（断开时调）。不存在则静默。"""
    try:
        if os.path.exists(path):
            os.remove(path)
            log.info("凭据已删除: %s", path)
    except OSError as e:
        log.warning("删除凭据失败: %s", e)


# ---- CLI 单跑（无 UI，便于调试）-------------------------------------
def main():
    import argparse
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    parser = argparse.ArgumentParser(description="海康 Lanz 平台额度查询客户端")
    parser.add_argument("username", help="用户名")
    parser.add_argument("password", help="密码")
    args = parser.parse_args()

    c = LanzClient(args.username, args.password)
    print("登录中...")
    c.login()
    print("登录成功\n")

    print("=== dashboard overview ===")
    dash = c.get_dashboard()
    ov = dash.get("overview", {})
    print("今日外部: %s/%s" % (ov.get("externalDailyUsed"), ov.get("externalDailyLimit")))
    print("今日内部: %s/%s" % (ov.get("internalDailyUsed"), ov.get("internalDailyLimit")))
    print("今日请求: %s" % ov.get("dailyRequestCount"))
    print("总消耗积分: %s" % ov.get("totalCredits"))
    print("剩余积分: %s" % ov.get("remainCredit"))
    print("预算积分: %s (hasBudget=%s)" % (ov.get("budgetCredit"), ov.get("hasBudget")))
    print("\n=== modelRank ===")
    for m in dash.get("modelRank", []):
        print("  %-20s tokens=%-12s 积分=%-10s 请求数=%s" % (
            m.get("finalModel"), m.get("tokens"), m.get("credits"),
            m.get("requestCount")))

    print("\n=== creditPricing ===")
    try:
        for m in c.get_credit_pricing():
            print("  %-20s %s 积分/百万token" % (m.get("modelName"), m.get("pricePerMillion")))
    except LanzError as e:
        print("  (无权: %s)" % e)


if __name__ == "__main__":
    main()
