# -*- coding: utf-8 -*-
"""a462（第二轮对抗审计）：LanzQuotaWorker 状态机与容错回归。

钉三个真实缺陷，都是「不报错但结果错」的那类——测试靠断言最终状态，
不靠异常：

1. `cur_epoch` 是 (cur_cred_epoch, cred_epoch) 二元组，内层循环却拿
   int 去比 → 恒不等 → 每轮 break，600s 全量刷新退化成 20s。
2. `_fetch_all` 会话过期只 emit 不返回状态 → models 通道仍 2001 时
   内层永不回外层，额度面板永久「会话过期，等待重新登录」。
3. 上游把 `routeStatus` 漂移成 list/str → `rs.get` AttributeError 整批
   负载丢弃，每 20s 报一次同一错误。
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import lanz_quota as L          # noqa: E402
from src import proxy as P              # noqa: E402


# ---- 1. _fetch_all 的返回值语义 ----------------------------------------
def _mk_worker():
    w = P.LanzQuotaWorker.__new__(P.LanzQuotaWorker)
    w._lock = threading.Lock()
    w._cred = ("u", "p")
    w._auto = True
    w._auto_relogin = True
    w._locked = False
    w._login_err = ""
    w._login_failed = False
    w._cred_epoch = 0
    w._cur_cred_epoch = 0
    w._refresh_req = False
    w._stop = threading.Event()
    w._wake = threading.Event()
    w._cur_client = None
    w._events = []
    w._emit = lambda kind, payload: w._events.append((kind, payload))
    return w


class _ClientOK:
    logged_in = True

    def get_dashboard(self):
        return {"overview": {"a": 1}, "modelRank": []}

    def get_budget_overview(self):
        return {"b": 2}


class _ClientDashExpired(_ClientOK):
    def get_dashboard(self):
        raise L.LanzSessionExpired("会话过期（3001）")


def test_fetch_all_ok_returns_true():
    w = _mk_worker()
    assert w._fetch_all(_ClientOK(), w._cred) is True
    assert any(k == "data" for k, _ in w._events)


def test_fetch_all_session_expired_returns_false():
    """缺陷 2：会话过期必须以返回值传递，否则内层永不回外层重登。"""
    w = _mk_worker()
    assert w._fetch_all(_ClientDashExpired(), w._cred) is False
    assert any(k == "fetch_err" for k, _ in w._events)


class _ClientNetErr(_ClientOK):
    def get_dashboard(self):
        raise L.LanzNetworkError("网络异常")


def test_fetch_all_network_error_keeps_session():
    """网络错误 ≠ 会话失效，不能触发重登（内网抖动时重登会撞风控）。"""
    w = _mk_worker()
    assert w._fetch_all(_ClientNetErr(), w._cred) is True


# ---- 2. 内层循环的换代判据 --------------------------------------------
# a469（第二轮审计）：原来这两条在测试体内**复刻**了判据表达式，从未调用
# 源码——把 proxy.py 改回 `cur_epoch != self._cred_epoch` 的 int 比较，测试
# 依旧全绿。改成直调生产函数 `_epoch_changed`。
def test_epoch_tuple_compare_does_not_break_every_round():
    """缺陷 1：cur_epoch 是二元组，拿 int 比恒真 → 每轮 break。

    什么都没变时，内层**不该**被判定为换代。
    """
    w = _mk_worker()
    cur_epoch = (w._cur_cred_epoch, w._cred_epoch)   # (0, 0)
    assert P._epoch_changed(w, w._cred, w._cred, cur_epoch) is False


def test_epoch_detects_submit_same_credentials():
    """同一组账号密码再提交一次（cred 值不变）也必须被判为换代。"""
    w = _mk_worker()
    cur_epoch = (w._cur_cred_epoch, w._cred_epoch)   # (0, 0)
    w._cred_epoch += 1                               # submit_credentials
    assert P._epoch_changed(w, w._cred, w._cred, cur_epoch) is True


def test_epoch_detects_force_relogin():
    """force_relogin 只动 _cur_cred_epoch（cred 值不变）也要判换代。"""
    w = _mk_worker()
    cur_epoch = (w._cur_cred_epoch, w._cred_epoch)
    w._cur_cred_epoch += 1
    assert P._epoch_changed(w, w._cred, w._cred, cur_epoch) is True


def test_epoch_detects_credential_values_changed():
    w = _mk_worker()
    cur_epoch = (w._cur_cred_epoch, w._cred_epoch)
    assert P._epoch_changed(w, ("u", "p"), ("u2", "p2"), cur_epoch) is True


# ---- 3. subscribe: routeStatus 类型漂移 -------------------------------
def _run_get_model_loads(payload):
    """走 get_model_loads 的解析路径，只把 `_fetch_text` 换成固定 JSON。"""
    import json
    c = L.LanzClient("u", "p")
    c._logged_in = True
    c._fetch_text = lambda *a, **kw: json.dumps(payload)
    return c.get_model_loads()


def test_route_status_list_does_not_raise():
    """缺陷 3：routeStatus 漂移成 list 时 rs.get 抛 AttributeError。"""
    out = _run_get_model_loads(
        {"code": 2001, "data": [{"modelName": "m1", "routeStatus": [1, 2]}]})
    assert len(out) == 1
    assert out[0]["name"] == "m1"
    assert out[0]["pct"] is None


def test_route_status_str_does_not_raise():
    out = _run_get_model_loads(
        {"code": 2001, "data": [{"modelName": "m2", "routeStatus": "busy"}]})
    assert out[0]["pct"] is None


def test_route_status_normal_still_parsed():
    out = _run_get_model_loads({"code": 2001, "data": [{
        "modelName": "m3",
        "routeStatus": {"total_active": 5, "effective_max_concurrent": 10},
    }]})
    assert out[0]["pct"] == 50
    assert out[0]["level"] == "normal"


# ---- 4. 锁定判据：不得把「警示语 / 不确定结论」当事实 ------------------
def test_lockout_msg_true_only_on_certain_wording():
    certain = [
        "账号已被 SSO 锁定（登录尝试次数超限）。请等待…",
        "Too many attempts, please contact itsm@hikvision.com",
        "登录失败，被重定向回 SSO 登录页。服务端提示: 您的账号已被锁定",
    ]
    for m in certain:
        assert P._is_lockout_msg(m) is True, m


def test_lockout_msg_false_on_warning_and_uncertain():
    """密码错误文案自带「会锁定」警示语；优先级4 兜底是「可能已锁定」。"""
    uncertain = [
        "用户名或密码错误。 注意：连续错误会锁定 SSO 账号。",
        "会话失效，请求被重定向回 SSO 登录页。可能账号已锁定或凭据失效…",
        "登录失败，被重定向回 SSO 登录页。服务端提示: 验证码错误",
        "",
    ]
    for m in uncertain:
        assert P._is_lockout_msg(m) is False, m
