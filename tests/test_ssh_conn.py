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
    def fake_create(addr, timeout=None):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(socket, "create_connection", fake_create)
    with pytest.raises(ConnectionError) as ei:
        _tcp_probe("10.0.0.1", 22, 3)
    assert "失败" in str(ei.value)


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
    """banner_timeout/timeout/auth_timeout 必须 >= 60s。

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
    assert got.get("banner_timeout", 0) >= 60
    assert got.get("timeout", 0) >= 60
    assert got.get("auth_timeout", 0) >= 60
