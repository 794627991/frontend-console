# -*- coding: utf-8 -*-
"""SSO 锁定状态匿名探测（a559，用户令：不登录查是否解锁）。

原理：匿名 GET lanz dashboard → 302 到 sso CAS 登录页。a446 实锤锁定
期间登录页本体就带 "Too many attempts" 文案——不提交任何凭据，零登录
尝试，不会重置锁定计时。

用法：python -m src.sso_status

注意：判定依赖「锁定文案出现在匿名可达的登录页上」。若贵司 SSO 只在
提交凭据后才显示锁定（匿名页恒无横幅），本探测无法区分锁定/解锁——
探测结果会如实说明，绝不猜。
"""
import json
import ssl
import urllib.request

DASHBOARD = "https://lanz.hikvision.com/resource/dashboard"
# a561 审计 F11：词表照抄 proxy._is_lockout_msg 的确定式结论——裸「锁定」
# 「尝试次数」会撞登录页静态警示语（"多次尝试将锁定账号"），页面改版即误报
LOCK_HINTS = ("too many attempts", "account is locked", "has been locked",
              "已被sso锁定", "已被 sso 锁定", "已被锁定", "尝试次数超限")


def probe(timeout=10):
    """返回 dict：locked=True/False/None（None=无法匿名判定）+ 依据。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(DASHBOARD, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36")})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        raw = r.read(500 * 1024)
        final_url = r.geturl()
    text = raw.decode("utf-8", "replace")
    low = text.lower()
    on_login_page = "sso.hikvision.com" in final_url
    # F11：只在登录页上判词，避免跟到错误页时正文误命中
    hits = [h for h in LOCK_HINTS if h in low] if on_login_page else []
    if hits:
        return {"locked": True, "evidence": hits, "url": final_url,
                "hint": "登录页带锁定文案——仍在锁定期"}
    if on_login_page:
        return {"locked": False, "evidence": [], "url": final_url,
                "hint": "已到登录页且无锁定文案——匿名视角未见锁定"
                        "（若 SSO 只对提交凭据者显示锁定，此判定不可靠）"}
    return {"locked": None, "evidence": [], "url": final_url,
            "hint": "未跳转到登录页（%s）——无法匿名判定" % final_url}


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"locked": None, "error": str(e)[:200]},
                         ensure_ascii=False, indent=2))
