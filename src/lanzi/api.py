# -*- coding: utf-8 -*-
"""Lanzi 对外门面（a672）。

proxy.py / server.py / tray.py 只从这里取东西，不直接碰内部模块。这样
内部怎么拆都不影响外部调用方。

职责：
  - emit 回调（worker → state 槽）
  - worker 单例懒建
  - status 组装（额度概览/三模型明细/排名/负载 + 登录态）
  - 操作：登录/登出/刷新/强制重登/自动刷新/自动重登
  - 模型负载查询（只读缓存，绝不自己登录）
"""
import logging
import threading
import time

from src.lanzi import config, state
from src.lanzi import quota

log = logging.getLogger("claude_proxy")

HAS_LANZ = True
try:
    from src.lanzi.quota import (LanzError, LanzAuthError, LanzSessionExpired,
                                 LanzNetworkError, LanzClient)
except Exception:   # pragma: no cover - 缺 pycryptodome 的环境
    HAS_LANZ = False

# worker 单例（按进程）
_quota = None
_quota_lock = threading.Lock()


# ---- emit：worker 事件 → 共享状态槽 --------------------------------
def _emit(kind, payload):
    """登录状态与最新事件分槽存（用户实锤过合槽 bug：data 事件覆盖
    login_ok 后前端永远显示「登录中」）——login 独立记登录态，只被
    login_ok/login_err/fetch_err/断开 翻转；state 只给 msg 类提示。"""
    st = state.store()
    with state.lock():
        st["state"]["kind"] = kind
        st["state"]["payload"] = payload
        st["state"]["ts"] = time.time()
        login = st["login"]
        if kind == "login_start":
            st["login"] = {"state": "logging",
                           "user": login and login.get("user")}
        elif kind == "login_ok":
            st["login"] = {"state": "online", "user": payload}
        elif kind == "login_err":
            st["login"] = {"state": "error", "user": None,
                           "msg": str(payload or "登录失败")}
        elif kind == "login_locked":
            # a454：SSO 锁定 → 已停登（不再自动重试，避免续期锁定）
            st["login"] = {"state": "locked", "user": None,
                           "msg": str(payload or "账号已被 SSO 锁定，已停止自动登录"),
                           "auto_paused": True}
        elif kind == "fetch_err":
            # 查询失败可能意味着会话失效——「在线」是误导
            st["login"] = {"state": "fetch_err",
                           "user": login.get("user") if login else None,
                           "msg": str(payload or "查询失败")}
        elif kind == "data" and isinstance(payload, dict):
            dash = payload.get("dashboard") or {}
            ov = dash.get("overview") or {}
            if ov:
                st["ov"] = ov
            rank = dash.get("modelRank") or []
            if rank:
                st["rank"] = rank
            st["ts"] = payload.get("ts")
            # data 到了说明登录成功：兜底恢复（防 login_ok 事件被面板未
            # 打开时错过导致卡「登录中」）
            if not login or login.get("state") != "online":
                user = None
                try:
                    cred = get_credentials()
                    user = (cred or {}).get("username")
                except Exception:
                    pass
                st["login"] = {"state": "online", "user": user}


# ---- worker 单例 ----------------------------------------------------
def ensure_worker():
    """有凭据才建 worker（懒建，daemon 线程自动开跑）。"""
    global _quota
    if not HAS_LANZ or _quota is not None:
        return _quota
    with _quota_lock:
        if _quota is not None:
            return _quota
        from src.lanzi.worker import LanzQuotaWorker
        w = LanzQuotaWorker(_emit)
        cred = get_credentials()
        if cred:
            w.submit_credentials(cred["username"], cred["password"])
        _quota = w
    return _quota


def worker():
    return _quota


# ---- 凭据 -----------------------------------------------------------
def get_credentials():
    return state.get_credentials()


def save_credentials(user, pwd):
    """写盘并唤醒 worker。返回 (ok, msg)。"""
    w = ensure_worker()
    if not HAS_LANZ or w is None:
        return False, "额度模块不可用（缺 pycryptodome）"
    try:
        quota.save_credentials(state.CRED_PATH, user, pwd)
    except Exception as e:
        log.exception("凭据写入失败")
        return False, ("凭据写入失败：%s（数据目录不可写？检查工具所在目录"
                       "权限，或把 exe 拷到普通目录运行）" % e)
    state.set_credentials_cache({"username": user, "password": pwd})
    w.submit_credentials(user, pwd)
    return True, ""


def clear_credentials():
    """登出：清本地凭据 + 停额度刷新，机器人不受影响。"""
    st = state.store()
    w = ensure_worker()
    quota.delete_credentials(state.CRED_PATH)
    state.set_credentials_cache(None)
    if w is not None:
        w.clear_credentials()
    with state.lock():
        st["login"] = None
        st["ov"] = {}
        st["rank"] = []
        st["ts"] = None
    manual = False
    try:
        from src.lanzi import bot
        manual = bot.is_manual_mode()
        bot.clear_account()
    except Exception:
        pass
    return manual


def refresh_now():
    w = ensure_worker()
    if w is None or not w.refresh_now():
        return False, "未配置凭据"
    return True, "已触发刷新"


def force_relogin():
    w = ensure_worker()
    if w is None or not w.force_relogin():
        return False, "未配置凭据"
    return True, "已触发强制重登（丢弃旧会话，重新登录）"


def set_auto(on):
    w = ensure_worker()
    if w is None:
        return False, "额度模块不可用（缺 pycryptodome）"
    w.set_auto(bool(on))
    return True, ("自动刷新已开启（10min）" if on else "自动刷新已关闭")


def set_auto_relogin(on):
    w = ensure_worker()
    if w is None:
        return False, "额度模块不可用（缺 pycryptodome）"
    w.set_auto_relogin(bool(on))
    return True, ("自动重登已开启（登录失败时按退避重试）" if on
                  else "自动重登已关闭（登录失败后等你手动强制重登）")


def shutdown():
    global _quota
    w = _quota
    _quota = None
    if w is not None:
        try:
            w.stop()
        except Exception:
            pass


# ---- 模型负载 -------------------------------------------------------
# LOAD_TTL 属 worker 内层循环（src/lanzi/worker.py），不在此处。


def get_model_loads():
    """模型实时负载。返回 (列表, 错误串)。

    a446（严重回归修复）：**只读缓存，绝不自己登录**。原实现会 new
    LanzClient 并 login()，与 worker 的会话同时存在于同一 SSO 账号下——
    两个会话互相踢，worker 刚登好就被踢回登录页（用户实锤「一直登录失败」）。
    现在负载统一由 worker 在它自己的 client 上顺带拉。
    """
    loads, err, _ts = state.get_loads()
    return loads, err


# ---- status 组装 ----------------------------------------------------
def status_payload():
    """额度相关字段（proxy status 与 /api/lanzi/status 共用）。"""
    snap = state.snapshot()
    cred = get_credentials()
    w = _quota
    data = {
        "quota_kind": snap["kind"],
        "quota_payload": snap["payload"],
        "quota_login": snap["login"],
        "quota_user": (snap["login"] or {}).get("user") if snap["login"] else None,
        "quota_auto": w._auto if w is not None else True,
        "quota_auto_relogin": w._auto_relogin if w is not None else True,
        "has_credentials": cred is not None,
        "quota_username": (cred or {}).get("username"),
        # 凭据本就明文存本地，界面却没回填——用户每次都要重打
        "quota_password": (cred or {}).get("password"),
        "quota_ts": snap["ts"],
    }
    if snap["ov"]:
        data["quota_overview"] = snap["ov"]
        try:
            data["quota_models"] = model_rows(snap["ov"])
        except Exception:
            pass   # 额度明细格式异常不拖死整个 status
    if snap["rank"]:
        data["quota_rank"] = snap["rank"]

    # 模型负载：只在「上游是 lanz」且已存凭据时给——不是 lanz 网关（智谱等）
    # 时这份数据无意义。默认先给 False 再尝试置 True：异常分支被吞时字段
    # 仍在，前端不会退回「加载中」死等。
    data["model_loads_supported"] = False
    data["lanz_active"] = False
    try:
        data["lanz_active"] = state.is_lanz_upstream()
        if data["lanz_active"] and cred:
            data["model_loads_supported"] = True
            loads, lerr = get_model_loads()
            if loads or lerr:
                _l, _e, ts = state.get_loads()
                data["model_loads"] = loads
                data["model_loads_err"] = lerr
                data["model_loads_ts"] = ts
    except Exception:
        pass   # 负载异常不拖死 status（面板命脉）
    data["upstream_host"] = state.current_upstream_host()
    return data


def model_rows(ov):
    """三模型明细行（GUI _model_tile 数据平移，前端渲染用）。"""
    rows = []
    for name, ku, kl in (
        ("Lanz-Auto", "internalAutoDailyUsed", "internalAutoDailyLimit"),
        ("Lanz-Flash", "internalFlashDailyUsed", "internalFlashDailyLimit"),
        ("Lanz-Medium", "internalMediumDailyUsed", "internalMediumDailyLimit")):
        u = ov.get(ku, 0) or 0
        l = ov.get(kl, 0) or 0
        rows.append({"name": name, "used": u, "limit": l,
                     "remain": max(l - u, 0),
                     "pct": int(u / l * 100) if l else 0})
    return rows


# ---- 托盘/悬浮卡用的极简读取 ----------------------------------------
def overview():
    return dict(state.store()["ov"])


def fnum(n):
    """数字缩写：12345 → 12.3k（与 proxy._fnum 同口径，勿改格式）。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1e8:
        return "%.0f" % n
    if n >= 1e4:
        return "%.1fW" % (n / 1e4)
    if n >= 1e3:
        return "%.1fk" % (n / 1e3)
    if n == int(n):
        return "%d" % int(n)
    return "%.1f" % n


def tip_suffix():
    """tooltip 额度前缀：未登录/无数据返回空串。"""
    ov = overview()
    if not ov:
        return ""
    qline = "今日 外%s/%s 内%s/%s 请求%s" % (
        fnum(ov.get("externalDailyUsed", 0) or 0),
        fnum(ov.get("externalDailyLimit", 0) or 0),
        fnum(ov.get("internalDailyUsed", 0) or 0),
        fnum(ov.get("internalDailyLimit", 0) or 0),
        fnum(ov.get("dailyRequestCount", 0) or 0))
    parts = []
    if ov.get("hasBudget"):
        parts.append("余%.0f" % (ov.get("remainCredit", 0) or 0))
    tot = ov.get("totalCredits", 0) or 0
    r = ov.get("usageRate", 0) or 0
    if r:
        parts.append("耗%.0f(%d%%)" % (tot, round(r * 100)))
    else:
        parts.append("耗%.0f" % tot)
    return qline + " " + " ".join(parts)


def tray_quota_rows():
    """托盘菜单里的额度动态行文本（纯字符串，调用时求值最新缓存）。"""
    ov = overview()
    if not ov:
        return ["额度: 未登录/暂无数据"]
    rows = ["今日 外 %s/%s  内 %s/%s" % (
        fnum(ov.get("externalDailyUsed", 0) or 0),
        fnum(ov.get("externalDailyLimit", 0) or 0),
        fnum(ov.get("internalDailyUsed", 0) or 0),
        fnum(ov.get("internalDailyLimit", 0) or 0))]
    for name, ku, kl in (
            ("Lanz-Auto", "internalAutoDailyUsed", "internalAutoDailyLimit"),
            ("Lanz-Flash", "internalFlashDailyUsed", "internalFlashDailyLimit"),
            ("Lanz-Medium", "internalMediumDailyUsed", "internalMediumDailyLimit")):
        u = ov.get(ku, 0) or 0
        l = ov.get(kl, 0) or 0
        remain = max(l - u, 0)
        pct = int(u / l * 100) if l else 0
        rows.append("%s 已用%s 余%s %d%%" % (name, fnum(u), fnum(remain), pct))
    return rows
