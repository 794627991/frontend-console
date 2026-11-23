# -*- coding: utf-8 -*-
"""推荐器「被作废的工作线程必须停下」回归锚（2026-11-23 总审计 P0-2）。

此前守护线程强制释放任务槽时只作废 run_id、不置 cancel；被作废的工作线程
只看 cancel 标志 → 要等 recommend_scope 自然结束才停（每 top 上限 300s，
剩十几个 top 就是白扫一小时 CPU / SMB IO），用户立刻点「重新推荐」时新旧
线程还会并发扫同一棵树。

现在：① 守护线程释放槽时同时置 cancel；② 取消判定同时比对本次 run_id——
只补 ① 不够，新任务启动会把 cancel 重置，旧线程下一个检查点又活了。

用真实的守护线程与工作线程跑（把巡检间隔 / 超时阈值调小），不是手工改状态。
"""
import os
import sys
import threading
import time

import flask
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import nav_api, nav_index

PROJ = os.path.join(os.path.abspath(os.sep), "no-such-project")   # 任意绝对路径


@pytest.fixture
def rec(monkeypatch):
    """推荐器槽归零 + 快速守护线程 + 可观察的假扫描函数。"""
    monkeypatch.setattr(nav_api, "_guard", lambda _p: True)
    monkeypatch.setattr(nav_api, "_REC_GUARD", 0.15)      # 0.15s 即判「卡住」
    monkeypatch.setattr(nav_api, "_REC_GUARD_TICK", 0.02)  # 巡检间隔
    nav_api._rec_state.update(running=False, cancel=False, done=False, ok=False,
                              err="", run_id="", result=None)
    seen = []
    exited = threading.Event()

    def fake_recommend(root, progress=None, should_cancel=None, say=None):
        seen.append("start")
        try:
            for _ in range(500):                  # 没人叫停要 10s 才跑完
                if should_cancel and should_cancel():
                    seen.append("cancelled")
                    raise nav_index.Cancelled()
                time.sleep(0.02)
            seen.append("finished")                # 只有白扫到底才会出现
        finally:
            exited.set()
        return {"ok": True, "nodes": []}

    monkeypatch.setattr(nav_index, "recommend_scope", fake_recommend)
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    c = app.test_client()

    def wait_done():
        for _ in range(200):
            s = c.get("/api/nav/scope_recommend_poll",
                      query_string={"root": PROJ}).get_json()
            if s["done"]:
                return s
            time.sleep(0.02)
        raise AssertionError("守护线程没有释放任务槽")

    return {"c": c, "seen": seen, "exited": exited, "wait_done": wait_done}


def test_guard_release_stops_the_abandoned_worker(rec):
    r = rec["c"].post("/api/nav/scope_recommend", json={"root": PROJ}).get_json()
    assert r["ok"] is True
    s = rec["wait_done"]()
    assert "超时" in s["err"]
    # 旧线程在下一个检查点就退出了（不是白扫到自然结束）
    assert rec["exited"].wait(5), "被作废的工作线程没有停下"
    assert rec["seen"] == ["start", "cancelled"]


def test_old_worker_stays_dead_when_user_restarts_immediately(rec):
    """释放槽后用户立刻点「重新推荐」：新任务会把 cancel 重置——旧线程
    靠 run_id 比对仍然退出。"""
    c, seen, exited = rec["c"], rec["seen"], rec["exited"]
    r1 = c.post("/api/nav/scope_recommend", json={"root": PROJ}).get_json()
    rec["wait_done"]()                                   # 守护线程已释放槽
    assert exited.wait(5)
    r2 = c.post("/api/nav/scope_recommend",
                json={"root": PROJ, "force": True}).get_json()
    assert r2["ok"] is True and r2["run_id"] != r1["run_id"]
    assert seen[:2] == ["start", "cancelled"]             # 旧线程已死且没复活
    assert nav_api._rec_state["running"] is True          # 新任务在跑
    # 收尾：取消新任务，别把线程留到进程结束
    c.post("/api/nav/scope_recommend_cancel",
           json={"root": PROJ, "run_id": r2["run_id"]})
    for _ in range(200):
        if seen.count("cancelled") >= 2:
            break
        time.sleep(0.02)
    assert seen.count("cancelled") == 2 and "finished" not in seen


def test_cancel_by_user_still_works(rec):
    """正常取消路径不受 run_id 比对影响。"""
    c, seen, exited = rec["c"], rec["seen"], rec["exited"]
    r = c.post("/api/nav/scope_recommend", json={"root": PROJ}).get_json()
    j = c.post("/api/nav/scope_recommend_cancel",
               json={"root": PROJ, "run_id": r["run_id"]}).get_json()
    assert j["ok"] is True
    assert exited.wait(5)
    assert seen == ["start", "cancelled"]


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
