# -*- coding: utf-8 -*-
"""a606：SSH 建连超时策略（MobaXterm 能连、工具连不上）。"""
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ssh_conn  # noqa: E402
from src.ssh_conn import _tcp_probe  # noqa: E402


def test_tcp_probe_reports_timeout_as_connection_error(monkeypatch):
    """不可达主机要在 TCP 阶段快速失败（不能拖满 banner 的 60s）。"""
    def fake_create(addr, timeout=None):
        raise socket.timeout("timed out")

    monkeypatch.setattr(socket, "create_connection", fake_create)
    with pytest.raises(ConnectionError) as ei:
        _tcp_probe("10.0.0.1", 22, 3)
    assert "超时" in str(ei.value)


def test_tcp_probe_reports_refused(monkeypatch):
    """端口拒绝要给出「端口未开放」，不是笼统的 TCP 失败（a608 文案分流）。"""
    def fake_create(addr, timeout=None):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(socket, "create_connection", fake_create)
    with pytest.raises(ConnectionError) as ei:
        _tcp_probe("10.0.0.1", 22, 3)
    assert "端口未开放" in str(ei.value)


def test_tcp_probe_reports_dns_failure(monkeypatch):
    """DNS 解析失败要明确说「无法解析主机」（原来被兜底文案吃掉）。"""
    def fake_create(addr, timeout=None):
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(socket, "create_connection", fake_create)
    with pytest.raises(ConnectionError) as ei:
        _tcp_probe("no-such-host.invalid", 22, 3)
    assert "无法解析主机" in str(ei.value)


def test_tcp_probe_ok_and_closes(monkeypatch):
    closed = []

    class FakeSock:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(socket, "create_connection",
                        lambda a, timeout=None: FakeSock())
    _tcp_probe("10.0.0.1", 22, 3)
    assert closed == [True]


def test_ssh_connect_allows_slow_banner(monkeypatch):
    """banner_timeout/timeout/auth_timeout 必须 >= 120s。

    嵌入式 dropbear 实测要 15~20 秒才发 banner（10.20.115.193 实测 20.2s），
    原来 10s 正好把这类设备挡在外面，报 "No existing session"。
    """
    got = {}

    class FakeClient:
        def set_missing_host_key_policy(self, p):
            pass

        def connect(self, **kw):
            got.update(kw)

        def invoke_shell(self, **kw):
            raise RuntimeError("stop here")

    class FakePK:
        SSHClient = FakeClient

        @staticmethod
        def AutoAddPolicy():
            return object()

    monkeypatch.setattr(ssh_conn, "_get_paramiko", lambda: FakePK)
    monkeypatch.setattr(ssh_conn, "_tcp_probe", lambda *a, **k: None)

    # 绕过 __init__ 的连接启动（BaseConnection 会在构造时开线程），
    # 只验证 _io_open 拼出来的 kwargs。
    c = ssh_conn.SSHConnection.__new__(ssh_conn.SSHConnection)
    c.host, c.ssh_port, c.username = "1.2.3.4", 22, "admin"
    c.password, c.key_path, c.port_id = "x", None, None
    c._keepalive_stop = None
    c._client = c._channel = c._io_handle = c._keepalive = None
    with pytest.raises(RuntimeError):
        c._io_open()
    assert got.get("banner_timeout", 0) >= 120
    assert got.get("timeout", 0) >= 120
    assert got.get("auth_timeout", 0) >= 120


# ---- a608：逐次令牌取消（审计修订）----------------------------------
def test_cancel_uses_conn_token():
    """取消按 conn_token 打标记，不再按 port_id（避免误杀同目标其它实例）。"""
    from src import server as S
    tok = "ct-test-1"
    try:
        j = S.app.test_client().post(
            "/api/connect/cancel", json={"conn_token": tok}).get_json()
        assert j["ok"] is True
        assert S._was_cancelled(tok) is True
    finally:
        S._clear_cancelled(tok)
    assert S._was_cancelled(tok) is False


def test_connect_cancel_requires_token():
    from src import server as S
    r = S.app.test_client().post("/api/connect/cancel", json={})
    assert r.status_code == 400


def test_cancelled_connect_closes_session(monkeypatch):
    """取消后连接才成功 —— 必须立刻关掉，不能给设备留残会话。"""
    from src import server as S
    created = []

    class FakeConn:
        def __init__(self, *a, **k):
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

    tok = "ct-test-2"
    monkeypatch.setattr(S, "SSHConnection", FakeConn)
    monkeypatch.setattr(S, "_get_paramiko", lambda: object())
    monkeypatch.setattr(S, "_ssh_disc_patch", lambda: None)
    S._mark_cancelled(tok)
    try:
        r = S.app.test_client().post("/api/connect", json={
            "kind": "ssh", "host": "9.9.9.9", "port": 22,
            "username": "u", "password": "p", "conn_token": tok})
        assert r.status_code == 499
        assert created and created[0].closed is True
        assert S._was_cancelled(tok) is False     # 标记已消费
    finally:
        S._clear_cancelled(tok)


def test_cancel_mark_cleared_even_when_connect_fails(monkeypatch):
    """审计缺陷 1（P0）：取消 + 连接失败，标记必须被清，否则下次连接受累。"""
    from src import server as S
    tok = "ct-fail"

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("auth fail")

    monkeypatch.setattr(S, "SSHConnection", Boom)
    monkeypatch.setattr(S, "_get_paramiko", lambda: object())
    monkeypatch.setattr(S, "_ssh_disc_patch", lambda: None)
    S._mark_cancelled(tok)
    try:
        r = S.app.test_client().post("/api/connect", json={
            "kind": "ssh", "host": "7.7.7.7", "port": 22,
            "username": "u", "password": "p", "conn_token": tok})
        assert r.status_code == 500
        assert S._was_cancelled(tok) is False
    finally:
        S._clear_cancelled(tok)


def test_cancel_does_not_kill_other_sessions():
    """审计缺陷 2（P0）：取消某次连接不能关掉同目标已建立的其它会话。

    审计指出原版是**假测试**：它只断言「会话没被关」，而 a607 的取消路由
    只读 port_id，收到 conn_token 直接 400 返回，根本没走到关闭分支——
    所以缺陷代码上这条也绿。现在补上「路由必须正常接受本次请求」的断言：
    a607 会返回 400，本用例即 FAIL；a608 返回 200 才继续验证不误杀。
    """
    from src import server as S

    class FakeConn:
        def __init__(self, *a, **k):
            self.closed = False

        def close(self):
            self.closed = True

    pid = "ssh:7.7.7.7:22"
    p = FakeConn()
    with S._ports_lock:
        S._ports[pid] = p
    try:
        r = S.app.test_client().post("/api/connect/cancel",
                                     json={"conn_token": "ct-other"})
        assert r.status_code == 200, "取消接口必须按 conn_token 受理"
        assert r.get_json()["ok"] is True
        # 已建立的会话不受影响
        assert p.closed is False
        with S._ports_lock:
            assert pid in S._ports
    finally:
        with S._ports_lock:
            S._ports.pop(pid, None)


def test_late_cancel_closes_registered_session():
    """a616（疯狗审计 v3 重炮三）：迟到取消必须真的关掉会话。

    a610 的时序：连接线程在 _ports_lock 里检查标记（未命中）→ 注册
    _ports[pid]=p → finally _clear_cancelled(token)。取消恰好落在注册之后、
    清理之前时，标记被写入又被连接线程自己擦掉，会话照样存活——前端早已
    abort，设备上留一条没人用的会话。
    修法：注册时同锁登记 token→port_id，cancel 路由按映射直接摘掉关闭。
    本用例模拟「注册已完成、连接线程还没走到 finally」的状态。
    """
    from src import server as S

    class FakeConn:
        def __init__(self, *a, **k):
            self.closed = False

        def close(self):
            self.closed = True

    pid = "ssh:8.8.8.8:22"
    tok = "ct-late"
    p = FakeConn()
    with S._ports_lock:
        S._ports[pid] = p
        S._bind_token_port(tok, pid)
    try:
        r = S.app.test_client().post("/api/connect/cancel",
                                     json={"conn_token": tok})
        assert r.status_code == 200
        assert p.closed is True, "迟到取消必须关闭已注册会话"
        with S._ports_lock:
            assert pid not in S._ports, "已关闭的会话必须从 _ports 摘掉"
        # 映射保留到连接线程 finally 自清；此处手工清，保证用例独立
    finally:
        with S._ports_lock:
            S._ports.pop(pid, None)
        S._unbind_token_port(tok)
        S._clear_cancelled(tok)
