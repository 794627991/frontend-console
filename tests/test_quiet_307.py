# -*- coding: utf-8 -*-
"""主进程访问日志降噪（2026-11-24 设计书）：只吞 307 + 轮询族访问行。

验收口径：
  · lanzi/proxy/harness 轮询族 307 不记；
  · 同路径的 404/500/503 照记（错误必须可见）；
  · 其他路径的 307、非 307 一律不吞。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.server import QuietAccessHandler, _is_quiet_307


def test_lanzi_prefix_307_filtered():
    for p in ("/api/lanzi/status", "/api/lanzi/bot_status",
              "/api/lanzi/status?x=1"):
        assert _is_quiet_307(307, p) is True


def test_other_polling_307_filtered():
    for p in ("/api/proxy/status", "/api/proxy/events",
              "/api/harness/version"):
        assert _is_quiet_307(307, p) is True


def test_errors_and_other_paths_kept():
    # 同路径的错误必须照记（设计书验收硬要求）
    assert _is_quiet_307(500, "/api/lanzi/status") is False
    assert _is_quiet_307(404, "/api/lanzi/status") is False
    assert _is_quiet_307(503, "/api/lanzi/bot_status") is False
    # 路径边界：/api/lanzi 本身不属于 /api/lanzi/ 族
    assert _is_quiet_307(307, "/api/lanzi") is False
    # 其他路径的 307 照记；非 307 一律不吞
    assert _is_quiet_307(307, "/api/other") is False
    assert _is_quiet_307(200, "/api/proxy/status") is False


def test_handler_gates_only_matching_307():
    """handler 层：命中不产生日志（不走父类），未命中照常走父类。"""
    calls = []

    class _Fake(QuietAccessHandler):
        def __init__(self, path):
            # 略过父类 __init__（不建 socket）；补齐 log_request 依赖的字段
            self.path = path
            self.command = "GET"
            self.request_version = "HTTP/1.1"
            self.requestline = "GET %s HTTP/1.1" % path

        def log(self, *a, **k):       # 父类 log_request 最终落到 self.log
            calls.append(a)

    _Fake("/api/lanzi/status").log_request(307, "-")
    assert calls == [], "307+轮询族必须静默"
    _Fake("/api/lanzi/status").log_request(500, "-")
    assert len(calls) == 1, "500 必须照记"
    _Fake("/api/other").log_request(307, "-")
    assert len(calls) == 2, "其他路径的 307 必须照记"
