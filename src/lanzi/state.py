# -*- coding: utf-8 -*-
"""Lanzi 专栏共享状态（a672）。

原来这些槽散在 proxy.py 里（配额 worker / 凭据缓存 / 负载缓存 / 登录标记），
与代理转发完全无关，只是当年合并在同一个文件。现在集中到这里：

    _ST["state"]     worker 最近一次 emit {"kind","payload","ts"}
    _ST["login"]     登录态独立槽（data 事件不覆盖登录态——合槽后前端永远
                     显示「登录中」，这是用户实锤过的 bug）
    _ST["ov"]        dashboard.overview 缓存（托盘/悬浮卡用）
    _ST["rank"]      模型用量排名
    _ST["loads"]     模型实时负载（20s TTL，额度 600s 一刷太慢）

上游判定（用户定调）：认**上游 host**，不认 base_url。代理会改 base_url，
但请求真正打到的上游不会变。见 is_lanz_upstream()。
"""
import json
import os
import threading
import time
from urllib.parse import urlsplit

from src.app_state import DATA_DIR

LANZ_HOST_MARK = "lanz.hikvision.com"
CRED_PATH = os.path.join(DATA_DIR, "lanz_credentials.json")
MARKS_PATH = os.path.join(DATA_DIR, "lanz_login_marks.json")

_loads_lock = threading.Lock()
_quota_lock = threading.Lock()

_ST = {
    "state": {},        # {"kind","payload","ts"}
    "login": None,      # {"state":"online|logging|error|locked|fetch_err","user","msg"}
    "ov": {},           # dashboard.overview
    "rank": [],         # dashboard.modelRank
    "ts": None,         # 上次 data 时间戳（秒）
    "loads": [],        # 模型负载
    "loads_ts": 0.0,
    "loads_err": "",
}

_cred_cache = None
_cred_cached = False


# ---- 凭据缓存（status 1s 轮询，不能每次读盘）--------------------------
def get_credentials():
    global _cred_cache, _cred_cached
    if not _cred_cached:
        try:
            from src.lanzi.quota import load_credentials
            _cred_cache = load_credentials(CRED_PATH)
        except Exception:
            _cred_cache = None   # 文件损坏/编码异常不拖死轮询
        _cred_cached = True
    return _cred_cache


def set_credentials_cache(cred):
    """save/clear 后直接写新值，并让模型负载失效（换号后负载/权限都不同）。"""
    global _cred_cache, _cred_cached
    _cred_cache = cred
    _cred_cached = True
    clear_loads("")


# ---- 模型负载缓存 ----------------------------------------------------
def set_loads(loads):
    global _ST
    with _loads_lock:
        _ST["loads"] = loads
        _ST["loads_ts"] = time.time()
        _ST["loads_err"] = ""


def set_loads_err(msg):
    with _loads_lock:
        _ST["loads_err"] = msg


def clear_loads(msg):
    with _loads_lock:
        _ST["loads"] = []
        _ST["loads_ts"] = 0.0
        _ST["loads_err"] = msg


def get_loads():
    with _loads_lock:
        return list(_ST["loads"]), _ST["loads_err"], _ST["loads_ts"]


def snapshot():
    """一次性取全部额度状态（避免多次加锁与竞态）。"""
    with _quota_lock:
        return {
            "kind": _ST["state"].get("kind"),
            "payload": _ST["state"].get("payload"),
            "login": dict(_ST["login"]) if _ST["login"] else None,
            "ov": dict(_ST["ov"]),
            "rank": list(_ST["rank"]),
            "ts": _ST["ts"],
        }


def lock():
    return _quota_lock


def store():
    return _ST


# ---- 跨进程重登标记 --------------------------------------------------
_marks_lock = threading.Lock()


def load_marks():
    """读跨进程重登标记：([stamps], trip_ts)。任何异常→空标记（不拦登录）。"""
    try:
        with open(MARKS_PATH, encoding="utf-8") as f:
            j = json.load(f)
        stamps = [t for t in j.get("stamps", []) if isinstance(t, (int, float))]
        return stamps, float(j.get("trip_ts") or 0.0)
    except Exception:
        return [], 0.0


def save_marks(stamps, trip_ts=0.0):
    from src.lanzi.quota import _notify_mirror, _replace_retry
    tmp = None
    try:
        d = os.path.dirname(MARKS_PATH)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        # 原子写（裸 "w" 直写期间镜像线程会读到半截 JSON）
        tmp = "%s.%d.%d.tmp" % (MARKS_PATH, os.getpid(), threading.get_ident())
        with _marks_lock, open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stamps": list(stamps[-4:]), "trip_ts": trip_ts}, f)
        _replace_retry(tmp, MARKS_PATH)
        tmp = None
        _notify_mirror(os.path.basename(MARKS_PATH))
    except Exception:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


# ---- 上游判定（认 host，不认 base_url）-------------------------------
def host_of_url(url):
    """从 url 解析 host（失败返回空串）。"""
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def is_lanz_host(host):
    return LANZ_HOST_MARK in (host or "").lower()


def current_upstream_host():
    """当前**真正被请求打到**的上游 host。

    判定分两支，关键是先确认流量确实还走自家代理：

      1. 代理在跑 **且** 当前 base_url 仍指向自家代理入口 → 用 server 上
         烘死的 upstream_host（运行时真值；代理会改 base_url，但上游不变）
      2. 其余情况 → 从 base_url 本身推导（用户在设置页把 base_url 改成
         第三方网关时，流量已绕过本机代理，桥上的 upstream_host 是过期值）

    a672 审计实锤：原实现只看 ctl.running 就无条件信 server.upstream_host。
    `/api/claude/api_config` 改 base_url 时并不重指上游，于是「代理在跑 →
    用户把 base_url 改成智谱」会误判为 lanz_active=true。
    """
    try:
        from src import proxy as _px
    except Exception:
        return ""
    try:
        cur = _px._bmgr.read_current_url()
    except Exception:
        cur = ""
    own_proxy = False
    try:
        own_proxy = _px._is_own_proxy_url(cur)
    except Exception:
        pass
    if own_proxy:
        # 流量走自家代理入口：代理在跑读桥上真值，没跑读它将要转发的直连目标
        try:
            ctl = _px._ctl
            if ctl.running and ctl.server is not None:
                return (ctl.server.upstream_host or "").lower()
        except Exception:
            pass
        try:
            return _px._upstream_of(_px._direct_url())[0] or ""
        except Exception:
            return ""
    # base_url 已不指向自家代理（用户改成第三方网关）：流量绕过本机代理，
    # 以 base_url 本身的上游为准
    h = host_of_url(cur)
    if h:
        return h
    try:
        return _px._upstream_of(_px._direct_url())[0] or ""
    except Exception:
        return ""


def is_lanz_upstream():
    """「当前是否在用 lanzi API」的唯一判据。

    用户定调：不是认 API 名，而是认上游——代理会改 base_url，上游不会。
    """
    return is_lanz_host(current_upstream_host())
