# -*- coding: utf-8 -*-
"""v4feed/v4hub 单测：主 reducer 事件序列、子 jsonl 喂入、hydration、
订阅帧（resume/snapshot 裁决）。纯内存，不依赖真实 session/CLI。"""
import importlib.util
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS_DIR = os.path.join(ROOT, "src", "harness")

# 构造 harness 包上下文（v4feed/v4hub 用相对 import；不经过 __init__
# 避免牵连 consts/app_state）
_pkg = types.ModuleType("harness")
_pkg.__path__ = [HARNESS_DIR]
sys.modules.setdefault("harness", _pkg)


def _load(fullname, fname):
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(HARNESS_DIR, fname))
    m = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = m
    spec.loader.exec_module(m)
    return m


P = _load("harness.v4proto", "v4proto.py")
F = _load("harness.v4feed", "v4feed.py")


def _env(seq, typ, turn="t1", data=None, ts=1000):
    return {"seq": seq, "ts": ts, "epoch": "e1", "sid": "s1",
            "turn": turn, "type": typ, "kind": typ, "data": data or {}}


class TestMainReducer(unittest.TestCase):
    def _feed(self):
        return F.V4Feed(epoch="e1")

    def test_full_turn_lifecycle(self):
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "user_echo", data={"text": "你好"}))
        f.ingest(_env(3, "cli_stream", data={"type": "assistant", "message": {
            "model": "m1", "content": [
                {"type": "thinking", "thinking": "想一想"},
                {"type": "text", "text": "答复正文"},
                {"type": "tool_use", "id": "tu1", "name": "Bash",
                 "input": {"command": "ls"}},
            ]}}))
        f.ingest(_env(4, "cli_stream", data={"type": "user", "message": {
            "content": [{"type": "tool_result", "tool_use_id": "tu1",
                         "content": "file1\nfile2"}]}}))
        f.ingest(_env(5, "turn_complete", data={"duration_ms": 1200}))
        rows = f.snap["rows"]
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds, ["turn_header", "user_input", "reasoning",
                                 "assistant_text", "tool_call"])
        self.assertEqual(rows[0]["state"], "success")
        self.assertEqual(rows[0]["activeMs"], 1200)
        self.assertEqual(rows[2]["text"], "想一想")
        self.assertEqual(rows[4]["tool"], "Bash")
        self.assertEqual(rows[4]["status"], "success")
        self.assertEqual(rows[4]["output"], "file1\nfile2")
        self.assertTrue(f.snap["state"]["busy"] is False)
        self.assertEqual(f.snap["seq"], 5)

    def test_subagent_rows(self):
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "user_echo", data={"text": "去探查"}))
        f.ingest(_env(3, "subagent_started",
                      data={"tid": "tu9", "task_id": "agent_x",
                            "type": "Explore", "desc": "探查注册表"}))
        f.ingest(_env(4, "subagent_result",
                      data={"tid": "tu9", "ok": True, "brief": "结论ABC"}))
        rows = f.snap["rows"]
        sub = [r for r in rows if r["kind"] == "subagent"]
        tool = [r for r in rows if r["kind"] == "tool_call"]
        self.assertEqual(len(sub), 1)
        self.assertEqual(sub[0]["status"], "success")
        self.assertEqual(sub[0]["childTopic"], "sub:agent_x")
        self.assertEqual(sub[0]["summary"], "结论ABC")
        self.assertEqual(tool[0]["status"], "success")
        self.assertEqual(tool[0]["output"], "结论ABC")   # 结论=工具行终态

    def test_frames_resume_and_snapshot(self):
        f = self._feed()
        for i in range(1, 6):
            f.ingest(_env(i, "user_echo", data={"text": "m%d" % i}))
        fr = f.frames_after(3)
        self.assertIsNotNone(fr)
        deltas, to = fr
        self.assertEqual(to, 5)
        # 只含 seq>3 的两条 append
        self.assertEqual(len(deltas), 2)
        # 越窗（floor）→ None → 调用方发 snapshot
        f._log = []
        f._floor_seq = 4
        self.assertIsNone(f.frames_after(3))

    def test_marker_and_peer(self):
        f = self._feed()
        f.ingest(_env(1, "renew", turn="", data={"text": "已续命"}))
        f.ingest(_env(2, "peer", turn="", data={"title": "协作A",
                                                "brief": "回传完成"}))
        f.ingest(_env(3, "peer", turn="", data={"vision": {
            "prompt": "看图", "src": "http://x/1.png", "tid": "v1",
            "chan": "vision"}}))
        rows = f.snap["rows"]
        self.assertEqual(rows[0]["kind"], "marker")
        self.assertEqual(rows[0]["mkind"], "renew")
        self.assertEqual(rows[1]["kind"], "peer_notify")
        self.assertEqual(rows[2]["kind"], "vision")
        self.assertEqual(rows[2]["status"], "pending")


class TestSubFeed(unittest.TestCase):
    def test_jsonl_lines(self):
        f = F.V4Feed(epoch="sub")
        self.assertTrue(f.feed_jsonl_line({"type": "user", "message": {
            "content": "探查一下注册表"}}))
        self.assertTrue(f.feed_jsonl_line({"type": "assistant", "message": {
            "model": "m", "content": [
                {"type": "thinking", "thinking": "思路"},
                {"type": "tool_use", "id": "t1", "name": "Grep",
                 "input": {"pattern": "x"}},
            ]}}))
        self.assertTrue(f.feed_jsonl_line({"type": "user", "message": {
            "content": [{"type": "tool_result", "tool_use_id": "t1",
                         "content": "hit"}]}}))
        self.assertTrue(f.feed_jsonl_line({"type": "result",
                                           "result": "最终报告"}))
        rows = f.snap["rows"]
        self.assertEqual([r["kind"] for r in rows],
                         ["user_input", "reasoning", "tool_call"])
        self.assertEqual(rows[2]["status"], "success")
        self.assertEqual(f.snap["state"]["done"], True)
        self.assertEqual(f.snap["state"]["final"], "最终报告")

    def test_handback_report_as_text(self):
        f = F.V4Feed(epoch="sub")
        f.feed_jsonl_line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback",
             "input": {"report": "交付的结论文本"}}]}})
        rows = f.snap["rows"]
        self.assertEqual(rows[0]["kind"], "assistant_text")
        self.assertEqual(rows[0]["text"], "交付的结论文本")


if __name__ == "__main__":
    unittest.main()
