# -*- coding: utf-8 -*-
"""远程会话检测回归（a468：无GPU加速模式的一次性建议依据）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import server as S  # noqa: E402


def _with_env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    for k in ("SESSIONNAME", "CLIENTNAME"):
        os.environ.pop(k, None)
    os.environ.update(kv)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_rdp_session_detected():
    for _ in _with_env(SESSIONNAME="RDP-Tcp#3"):
        assert S._is_remote_session() is True


def test_ica_session_detected():
    for _ in _with_env(SESSIONNAME="ICA-CITRIX-01"):
        assert S._is_remote_session() is True


def test_console_not_detected():
    for _ in _with_env(SESSIONNAME="Console", CLIENTNAME="whatever"):
        assert S._is_remote_session() is False


def test_clientname_only_detected():
    # RDP 下被剥了 SESSIONNAME 的派生进程：CLIENTNAME 在且非 Console
    for _ in _with_env(CLIENTNAME="MY-PC"):
        assert S._is_remote_session() is True


def test_bare_console_not_detected():
    for _ in _with_env(SESSIONNAME=""):
        assert S._is_remote_session() is False
