# -*- coding: utf-8 -*-
"""Electron 壳启动亲和令牌契约（两侧必须同时改）。

2026-11-20 实锤：壳侧把就绪判据从 boot_ms 改成 endpoint.boot_token，但
backend write_endpoint 没回写 → 壳永远等不到匹配 token，60s 超时，工具
打不开。本测试钉住两侧契约，任何单侧补丁/回退都会红。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_boot_token_written_by_backend_and_checked_by_shell():
    py = _read('src/main.py')
    js = _read('electron/main.js')
    # 后端：从 env 原样回写 endpoint
    assert '"boot_token": os.environ.get("FC_BOOT_TOKEN") or ""' in py
    # 壳：注入 env + 只认匹配 token 的 endpoint
    assert 'FC_BOOT_TOKEN: BOOT_TOKEN' in js
    assert 'ep.boot_token === BOOT_TOKEN' in js
    # 不允许再退回只靠 boot_ms 的判据（避免旧单侧补丁复活）
    assert 'boot_ms >= spawnMs' not in js
