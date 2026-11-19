# -*- coding: utf-8 -*-
"""Lanzi 专栏 HTTP 端点（a672）。

全部挂在 /api/lanzi/* 下，与代理的 /api/proxy/* 彻底分开——旧路径
/api/proxy/quota|credentials 已移除（用户定调：不保留转发）。

端点清单：
    GET  /api/lanzi/status          登录态 + 额度概览 + 三模型 + 排名 + 负载
    POST /api/lanzi/login           保存凭据并开始登录 body{username,password}
    POST /api/lanzi/logout          断开登录（机器人不受影响）
    POST /api/lanzi/refresh         立即刷新额度
    POST /api/lanzi/relogin         强制重登（丢弃旧会话）
    POST /api/lanzi/auto            body{auto:bool}      自动刷新开关
    POST /api/lanzi/auto_relogin    body{auto_relogin:bool} 自动重登开关
    GET  /api/lanzi/sso_probe       SSO 锁定匿名探测
    GET  /api/lanzi/bot_status      机器人运行态
    POST /api/lanzi/bot_activate    激活/停用机器人 body{stop:bool}
    POST /api/lanzi/bot_credentials 手填机器人凭据 body{app_id,app_secret}
"""
import logging

from flask import Blueprint, jsonify, request

from src.lanzi import api

log = logging.getLogger("claude_proxy")

lanzi_bp = Blueprint("lanzi", __name__)


@lanzi_bp.route("/api/lanzi/status")
def _status():
    try:
        return jsonify({"ok": True, **api.status_payload()})
    except Exception as e:
        log.exception("lanzi status 失败")
        return jsonify({"ok": False, "msg": str(e)})


@lanzi_bp.route("/api/lanzi/login", methods=["POST"])
def _login():
    j = request.get_json(silent=True) or {}
    user = (j.get("username") or "").strip()
    pwd = j.get("password") or ""
    if not user or not pwd:
        return jsonify({"ok": False, "msg": "用户名/密码不能为空"})
    ok, msg = api.save_credentials(user, pwd)
    if not ok:
        return jsonify({"ok": False, "msg": msg})
    # 机器人：账号登录后按实际结果如实回报（此前无条件回「机器人已激活」）
    bot_msg = ""
    try:
        from src.lanzi import bot
        _ok, _bm = bot.ensure_started()
        if _ok:
            bot_msg = _bm
        else:
            # 「机器人未启用」语义要保留（冒号而非括号，避免双层括号）
            bot_msg = "机器人未启用：" + (_bm or "无凭据")
    except Exception as e:
        log.warning("登录后激活机器人异常: %s", e)
    return jsonify({"ok": True,
                    "msg": "已保存，开始登录" + ("；" + bot_msg if bot_msg else "")})


@lanzi_bp.route("/api/lanzi/logout", methods=["POST"])
def _logout():
    try:
        manual = api.clear_credentials()
    except Exception as e:
        log.exception("lanzi logout 失败")
        return jsonify({"ok": False, "msg": str(e)})
    return jsonify({"ok": True,
                    "msg": "已断开登录（机器人不受影响）" if manual else "已断开登录"})


@lanzi_bp.route("/api/lanzi/refresh", methods=["POST"])
def _refresh():
    ok, msg = api.refresh_now()
    return jsonify({"ok": ok, "msg": msg})


@lanzi_bp.route("/api/lanzi/relogin", methods=["POST"])
def _relogin():
    ok, msg = api.force_relogin()
    return jsonify({"ok": ok, "msg": msg})


@lanzi_bp.route("/api/lanzi/auto", methods=["POST"])
def _auto():
    j = request.get_json(silent=True) or {}
    ok, msg = api.set_auto(bool(j.get("auto")))
    return jsonify({"ok": ok, "msg": msg})


@lanzi_bp.route("/api/lanzi/auto_relogin", methods=["POST"])
def _auto_relogin():
    j = request.get_json(silent=True) or {}
    ok, msg = api.set_auto_relogin(bool(j.get("auto_relogin")))
    return jsonify({"ok": ok, "msg": msg})


@lanzi_bp.route("/api/lanzi/sso_probe")
def _sso_probe():
    """匿名探测 SSO 是否锁定（不提交任何凭据，不会重置锁定计时）。"""
    try:
        from src.lanzi import sso
        return jsonify({"ok": True, **sso.probe()})
    except Exception as e:
        return jsonify({"ok": False, "locked": None, "error": str(e)[:200]})


@lanzi_bp.route("/api/lanzi/bot_status")
def _bot_status():
    try:
        from src.lanzi import bot
        return jsonify({"ok": True, **bot.status_snapshot()})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@lanzi_bp.route("/api/lanzi/bot_activate", methods=["POST"])
def _bot_activate():
    try:
        from src.lanzi import bot
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})
    j = request.get_json(silent=True) or {}
    if j.get("stop"):
        ok, msg = bot.ensure_stopped()
    else:
        ok, msg = bot.ensure_started()
    return jsonify({"ok": ok, "msg": msg})


@lanzi_bp.route("/api/lanzi/bot_credentials", methods=["POST"])
def _bot_credentials():
    """保存/清除手填机器人凭据（App ID + App Secret）。

    显式要求两个键都在场：把「取不到参数」当清除的话，本机任意网页一个
    text/plain 简单请求就能清空凭据并停掉机器人。
    """
    try:
        from src.lanzi import bot
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})
    j = request.get_json(silent=True)
    if not isinstance(j, dict) or "app_id" not in j or "app_secret" not in j:
        return jsonify({"ok": False, "msg": "请求体必须含 app_id 与 app_secret"}), 400
    ok, msg = bot.set_manual_credentials(j.get("app_id"), j.get("app_secret"))
    return jsonify({"ok": ok, "msg": msg})
