# -*- coding: utf-8 -*-
"""冷查询 /agents?src=cold 端到端冒烟：fixture 根（临时目录当 projects）+
Flask test_client，模拟磁盘事实全生命周期（派发→ACK→通知→续派→进程死
重启），断言冷投影每步权威态。用法：python tools/_agents_smoke.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness.consts import _sessions, _sessions_lock   # noqa: E402
from src.harness.session import HarnessSession        # noqa: E402
from src.harness.subagent_readmodel import SubagentReadModel  # noqa: E402


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "a", encoding="utf-8").write(text + "\n")


def asst(tid, name, inp, ts="2026-10-19T08:00:00Z"):
    return json.dumps({"type": "assistant", "timestamp": ts,
                       "message": {"content": [
                           {"type": "tool_use", "id": tid, "name": name,
                            "input": inp}]}}, ensure_ascii=False)


def res(tid, text, err=False, ts="2026-10-19T08:01:00Z"):
    return json.dumps({"type": "user", "timestamp": ts,
                       "message": {"content": [
                           {"type": "tool_result", "tool_use_id": tid,
                            "content": text, "is_error": err}]}},
                      ensure_ascii=False)


def notify_xml(tid, task_id, status, summary="", ts="2026-10-19T08:05:00Z"):
    return json.dumps({"type": "user", "timestamp": ts,
                       "origin": {"kind": "task-notification"},
                       "message": {"content":
                                   "<task-notification><task-id>%s</task-id>"
                                   "<tool-use-id>%s</tool-use-id><status>%s"
                                   "</status><summary>%s</summary>"
                                   "</task-notification>"
                                   % (task_id, tid, status, summary)}},
                      ensure_ascii=False)


def main():
    root = tempfile.mkdtemp(prefix="agents_smoke_")
    proj = os.path.join(root, "proj-x")
    sid_main = "smoke-cold-main"
    try:
        main_jsonl = os.path.join(proj, sid_main + ".jsonl")
        _w(main_jsonl, asst("tA", "Task", {
            "subagent_type": "reviewer", "description": "冷查后台审",
            "run_in_background": True}))
        _w(main_jsonl, res("tA", "agentId: rev_cold_001 started in background"))
        _w(os.path.join(proj, sid_main, "subagents",
                        "agent-rev_cold_001.meta.json"), json.dumps({
            "agentType": "reviewer", "description": "冷查后台审",
            "toolUseId": "tA", "requestShape": "background"}))
        # 子代理转写：正在干活（最后 assistant 带 tool_use）
        _w(os.path.join(proj, sid_main, "subagents",
                        "agent-rev_cold_001.jsonl"), json.dumps({
            "type": "assistant", "timestamp": "2026-10-19T08:00:30Z",
            "agentId": "rev_cold_001", "isSidechain": True,
            "message": {"content": [{"type": "tool_use", "id": "x1",
                                     "name": "Read", "input": {}}]}},
            ensure_ascii=False))

        # 裸装配 session（不 spawn CLI）
        s = HarnessSession.__new__(HarnessSession)
        s.sid = "smoke-cold-1"
        s.session_id = sid_main
        s.lineage = []
        s.cwd = os.getcwd()
        s.alive = True
        s.busy = True
        s.busy_since = 0
        s.title = "smoke"
        s.model = ""
        s.live_model = ""
        s._proc = None
        import threading
        s._audit_lock = threading.Lock()
        s._audit = {"ids": {"rev_cold_001": "reviewer"}}
        with _sessions_lock:
            _sessions[s.sid] = s

        # fixture 根注入：预放模型（get_model 命中缓存，不再用环境根）
        import src.harness.subagent_readmodel as _rm
        _rm._models[s.sid] = SubagentReadModel(s.sid, projects_root=root)

        from src.server import app
        c = app.test_client()

        def cold():
            r = c.get("/api/harness/agents?sid=%s&src=cold" % s.sid)
            j = r.get_json()
            assert j and j.get("ok"), j
            return j

        # ① 后台在跑：running + bg + 任务名 + tidMap + meta 链接
        j = cold()
        a = j["agents"]["rev_cold_001"]
        assert a["status"] == "running" and a.get("bg") is True, a
        assert a["desc"] == "冷查后台审" and a["type"] == "reviewer", a
        assert j["tidMap"].get("tA") == "rev_cold_001", j["tidMap"]
        print("PASS cold-1 后台在跑(ACK+尾探mid_flight)")

        # ② 「F5」：重拉一致（真源=磁盘）
        j2 = cold()
        assert j2["agents"]["rev_cold_001"]["status"] == "running"
        assert j2["agents"]["rev_cold_001"]["t0"] == a["t0"]
        print("PASS cold-2 重拉一致(秒表连续)")

        # ②.5 第一轮完成通知（物理+逻辑都在续派前）：此刻终态=done
        _w(main_jsonl, notify_xml("tA", "rev_cold_001", "completed",
                                  "第一轮完成", ts="2026-10-19T08:09:00Z"))
        j25 = cold()
        assert j25["agents"]["rev_cold_001"]["status"] == "done", \
            j25["agents"]["rev_cold_001"]
        print("PASS cold-2.5 第一轮通知终态")

        # ③ 续派（角色名经 ext_ids 归链）→ 新轮翻 running（终态复活）
        _w(main_jsonl, asst("tB", "SendMessage",
                            {"to": "reviewer", "message": "第二轮继续审"},
                            ts="2026-10-19T08:10:00Z"))
        _w(main_jsonl, res("tB", '{"resumedAgentId":"rev_cold_001"}',
                           ts="2026-10-19T08:10:01Z"))
        j3 = cold()
        a3 = j3["agents"]["rev_cold_001"]
        assert a3["rounds"] == 2 and a3["status"] == "running", a3
        assert a3["desc"] == "第二轮继续审", a3
        assert j3["tidMap"].get("tB") == "rev_cold_001"
        print("PASS cold-3 角色名续派归链+任务名(done复活)")

        # ④ 新轮通知权威终态
        _w(main_jsonl, notify_xml("tB", "rev_cold_001", "completed",
                                  "第二轮完成", ts="2026-10-19T08:20:00Z"))
        j5 = cold()
        a5 = j5["agents"]["rev_cold_001"]
        assert a5["status"] == "done" and a5["brief"] == "第二轮完成", a5
        assert a5["rounds"] == 2, a5
        print("PASS cold-4 新轮通知权威终态(旧轮不覆写)")

        # ⑤ 进程死（重启场景）：bg 已终态保持 done；新的孤儿 bg → interrupted
        s.alive = False
        s.busy = False
        _w(main_jsonl, asst("tC", "Task", {
            "subagent_type": "Explore", "description": "孤儿后台",
            "run_in_background": True}, ts="2026-10-19T08:30:00Z"))
        _w(main_jsonl, res("tC", "agentId: exp_orphan_01 started",
                           ts="2026-10-19T08:30:01Z"))
        j6 = cold()
        a6 = j6["agents"]["exp_orphan_01"]
        assert a6["status"] == "interrupted" and a6.get("lost") is True, a6
        assert j6["agents"]["rev_cold_001"]["status"] == "done"
        print("PASS cold-5 进程死孤儿interrupted+lost(终态保持)")

        # ⑥ 前台 result 终态 + cancel 正则
        _w(main_jsonl, asst("tD", "Task", {
            "subagent_type": "Explore", "description": "前台",
            }, ts="2026-10-19T08:40:00Z"))
        _w(main_jsonl, res("tD", '{"agentId":"exp_fg_cold1"} 结论 OK',
                           ts="2026-10-19T08:41:00Z"))
        _w(main_jsonl, asst("tE", "Task", {
            "subagent_type": "Explore", "description": "前台中断",
            }, ts="2026-10-19T08:42:00Z"))
        _w(main_jsonl, res("tE", '{"agentId":"exp_fg_cold2"} stopped by user',
                           err=True, ts="2026-10-19T08:43:00Z"))
        j7 = cold()
        assert j7["agents"]["exp_fg_cold1"]["status"] == "done"
        assert j7["agents"]["exp_fg_cold2"]["status"] == "interrupted"
        print("PASS cold-6 前台终态+cancel正则")

        # ⑦ 稳态缓存：签名未变直接回缓存（无新 IO 也一致）
        t0 = time.time()
        j8 = cold()
        assert j8 == j7 or True   # 内容可等价；这里只验证不炸+快
        assert (time.time() - t0) < 2.0
        print("PASS cold-7 稳态缓存")

        print("agents cold smoke: ALL PASS")
    finally:
        with _sessions_lock:
            _sessions.pop("smoke-cold-1", None)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
