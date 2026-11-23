# -*- coding: utf-8 -*-
"""串口日志「后台永不删除」回归锚（2026-11-23 用户令）。

事故：server.py start_background 里有个 v0.x 起就存在的 _cleanup 守护线程，
每 30 秒删 LOG_DIR 下修改时间超过 7 天的 serial_*.log，无开关。a687 把手动
「按策略清理」改成不删、界面写明「不会自动删除」，却漏了这条后台链路。

用户令：串口日志**后台绝不能删**，只有用户在设置里手动点击才允许删
（挡位：超过 7 / 30 / 90 天，或全部清空）。本文件锁住：

  1. 静态：src 下不存在「既提到 serial_ 又会删文件」的函数——除手动清理
     入口与两处「复制校验通过后才删源」的旧目录合并逻辑
  2. 行为：older 挡位只删超过 N 天的 serial_*.log；all 只删 serial_*；
     policy 什么都不删；天数不在白名单直接抛错（不假成功）
  3. 占用统计与可删范围同口径，并给出各挡位可释放的字节数
  4. 接口：older 的天数只认 7/30/90；按天数只支持串口日志

（后台线程「真的不再删」的运行态验证不在 pytest 里做——要等 30 秒线程
周期，见会话里的隔离运行态验证。）
"""
import ast
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import src.app_state as st
import src.data_hygiene as dh
import src.server as S

DAY = 86400
_NOW = time.time()

# 允许「提到 serial_ 且会删文件」的函数（模块名, 函数名）：
#   manual_clean                      —— 唯一的手动清理入口（本文件的行为用例盯着）
#   _merge_log_dir / _migrate_legacy  —— 旧日志目录**全部复制校验成功后**才删
#   _user_data                          源目录；是搬家不是清理，不按时间丢文件
_ALLOWED = {("data_hygiene", "manual_clean"),
            ("app_state", "_merge_log_dir"),
            ("app_state", "_migrate_legacy_user_data")}
_DELETERS = {"os.remove", "os.unlink", "_try_rm", "shutil.rmtree",
             "remove", "unlink", "rmtree"}


def _calls_named(node):
    """函数体内所有被调用函数的「点路径名」与「裸名」。"""
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            parts = []
            while isinstance(f, ast.Attribute):
                parts.append(f.attr)
                f = f.value
            if isinstance(f, ast.Name):
                parts.append(f.id)
            if parts:
                names.add(".".join(reversed(parts)))
                names.add(parts[0])       # 裸名（如 _try_rm(...)）
    return names


def _strings(node):
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_no_background_code_deletes_serial_logs():
    """静态守卫：除白名单外，任何函数不得「提到 serial_ 且调用删除」。"""
    offenders = []
    src_dir = os.path.join(ROOT, "src")
    for r, _ds, fs in os.walk(src_dir):
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(r, f)
            with open(p, encoding="utf-8-sig", errors="replace") as fh:
                try:
                    tree = ast.parse(fh.read(), p)
                except SyntaxError:
                    continue
            mod = os.path.splitext(os.path.basename(p))[0]
            for n in ast.walk(tree):
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not any("serial_" in s for s in _strings(n)):
                    continue
                if not (_calls_named(n) & _DELETERS):
                    continue
                if (mod, n.name) in _ALLOWED:
                    continue
                offenders.append("%s:%d %s()" % (os.path.relpath(p, ROOT),
                                                 n.lineno, n.name))
    assert not offenders, "这些函数会删串口日志，且不在手动清理/搬家白名单里：\n" \
        + "\n".join(offenders)


@pytest.fixture
def logs(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    d.mkdir()
    monkeypatch.setattr(st, "LOG_DIR", str(d))
    monkeypatch.setattr(st, "DATA_DIR", str(tmp_path))
    dh._usage_cache.update(ts=0.0, data=None)
    dh._dir_total_cache.update(ts=0.0)
    return d


def _mk(d, name, age_days, size=10):
    p = d / name
    p.write_bytes(b"x" * size)
    t = _NOW - age_days * DAY
    os.utime(str(p), (t, t))
    return p


def test_older_deletes_only_old_serial_logs(logs):
    old = _mk(logs, "serial_a.log", 8)
    new = _mk(logs, "serial_b.log", 1)
    foreign = _mk(logs, "other.log", 400)          # 非工具自产：任何挡位都不碰
    removed, freed = dh.manual_clean("logs", "older", days=7)
    assert (removed, freed) == (1, 10)
    assert not old.exists() and new.exists() and foreign.exists()


@pytest.mark.parametrize("days", [30, 90])
def test_older_respects_the_chosen_tier(logs, days):
    p = _mk(logs, "serial_a.log", 8)                # 8 天前的：30/90 天挡位不动它
    assert dh.manual_clean("logs", "older", days=days) == (0, 0)
    assert p.exists()
    _mk(logs, "serial_b.log", days + 5)
    assert dh.manual_clean("logs", "older", days=days) == (1, 10)
    assert p.exists()


def test_older_rejects_days_outside_whitelist(logs):
    p = _mk(logs, "serial_a.log", 400)
    for bad in (0, 1, 365, None):
        with pytest.raises(ValueError):
            dh.manual_clean("logs", "older", days=bad)
    assert p.exists()                                # 拒绝的同时什么都没删


def test_policy_deletes_nothing_and_all_only_serial(logs):
    a = _mk(logs, "serial_a.log", 400)
    b = _mk(logs, "serial_b.log", 0)
    foreign = _mk(logs, "other.log", 400)
    assert dh.manual_clean("logs", "policy") == (0, 0)
    assert a.exists() and b.exists()
    assert dh.manual_clean("logs", "all") == (2, 20)
    assert not a.exists() and not b.exists()
    assert foreign.exists()


def test_older_is_only_for_serial_logs(logs):
    _mk(logs, "serial_a.log", 400)
    assert dh.manual_clean("idx", "older", days=7) == (0, 0)
    assert (logs / "serial_a.log").exists()


def test_usage_counts_only_cleanable_serial_logs(logs, monkeypatch):
    monkeypatch.setattr(st, "BASE_DIR", str(logs.parent))
    monkeypatch.setattr(dh, "uploads_dir", lambda: str(logs / "no_uploads"))
    _mk(logs, "serial_old.log", 400, size=100)
    _mk(logs, "serial_new.log", 1, size=50)
    _mk(logs, "foreign.log", 400, size=1000)        # 不计入「可清理」
    (logs / "idx").mkdir()
    _mk(logs / "idx", "x.idx", 400, size=7)
    data = dh.usage_stats(force=True)
    t = data["targets"]["logs"]
    assert t["bytes"] == 150                        # 统计口径 = 能删的
    assert t["age_options"] == [7, 30, 90]
    assert t["by_age"] == {"7": 100, "30": 100, "90": 100}


def test_route_accepts_only_whitelisted_days(logs):
    _mk(logs, "serial_a.log", 400)
    c = S.app.test_client()

    def post(body):
        rv = c.post("/api/data_dir/clean", json=body)
        return rv.status_code, rv.get_json()

    assert post({"target": "logs", "mode": "older", "days": 0})[0] == 400     # 0 天=绕过确认的全清
    assert post({"target": "logs", "mode": "older", "days": "abc"})[0] == 400
    assert post({"target": "logs", "mode": "older"})[0] == 400
    assert post({"target": "idx", "mode": "older", "days": 7})[0] == 400
    assert (logs / "serial_a.log").exists()          # 以上被拒的请求都没删东西
    code, body = post({"target": "logs", "mode": "older", "days": 90})
    assert code == 200 and body["ok"] is True and body["removed"] == 1
    assert not (logs / "serial_a.log").exists()


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
