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

    def test_sub_mirror_filtered_from_main(self):
        """红线：子代理镜像事件绝不进主投影。判据分层对齐 sse.js：
        业务事件看 parent_tool_use_id/isSidechain；system 另加 agent_id。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "assistant", "parent_tool_use_id": "tu1",
            "message": {"content": [{"type": "text", "text": "子代理正文"}]}}))
        f.ingest(_env(3, "cli_stream", data={
            "type": "assistant", "isSidechain": True,
            "message": {"content": [{"type": "text", "text": "侧链正文"}]}}))
        f.ingest(_env(4, "cli_stream", data={
            "type": "system", "agent_id": "agent_x",
            "subtype": "task_started", "message": {}}))
        f.ingest(_env(5, "cli_stream", data={
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "主会话正文"}]}}))
        texts = [r.get("text") for r in f.snap["rows"]
                 if r["kind"] == "assistant_text"]
        self.assertEqual(texts, ["主会话正文"])
        # 主链 assistant 带 agent_id 不过滤（sse.js 同口径，防误杀主窗正文）
        f.ingest(_env(6, "cli_stream", data={
            "type": "assistant", "agent_id": "agent_y",
            "message": {"content": [{"type": "text", "text": "主链二"}]}}))
        texts = [r.get("text") for r in f.snap["rows"]
                 if r["kind"] == "assistant_text"]
        self.assertEqual(texts, ["主会话正文", "主链二"])

    def test_result_fallback_closes_header(self):
        """turn_complete 缺失（CLI 自发回合）时 result 帧兜底收口组头。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "result", "duration_ms": 900, "is_error": False}))
        hdr = f.snap["rows"][0]
        self.assertEqual(hdr["kind"], "turn_header")
        self.assertEqual(hdr["state"], "success")
        self.assertEqual(hdr["activeMs"], 900)

    def test_held_result_does_not_close(self):
        """hold 期（后台子代理在飞）result 帧不提前收口组头。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "turn_hold", data={"n": 1}))
        f.ingest(_env(3, "cli_stream", data={"type": "result"}))
        self.assertEqual(f.snap["rows"][0]["state"], "running")
        f.ingest(_env(4, "turn_complete"))
        self.assertEqual(f.snap["rows"][0]["state"], "success")
        # 收口后 hold 标记清除，后续回合 result 时间戳正常兜底
        f.ingest(_env(5, "turn_started"))
        f.ingest(_env(6, "cli_stream", data={"type": "result"}))
        self.assertEqual(f.snap["rows"][-1]["state"], "success")

    def test_header_lazy_created(self):
        """turn_started 缺失时，任何带 turn 的行到达都要补建组头——
        「工作组头不出现」红线的构造性防线。"""
        f = self._feed()
        f.ingest(_env(1, "user_echo", data={"text": "你好"}))
        kinds = [r["kind"] for r in f.snap["rows"]]
        self.assertEqual(kinds, ["turn_header", "user_input"])
        self.assertEqual(f.snap["rows"][0]["state"], "running")
        # 第二条用户消息同轮不重复建头
        f.ingest(_env(2, "user_echo", data={"text": "再来"}))
        self.assertEqual([r["kind"] for r in f.snap["rows"]].count("turn_header"), 1)

    def test_replay_dedup_against_hydration(self):
        """水位补放期与 hydration 重叠的用户行不重复渲染。"""
        f = self._feed()
        f.snap["rows"].append({"rowId": 1, "turnId": "t0",
                               "kind": "user_input", "text": "历史一条"})
        f.snap["total"] = 1
        f._hyd_keys = {("user_input", "历史一条")}
        f._replay = True
        f.ingest(_env(1, "user_echo", data={"text": "历史一条"}))
        self.assertEqual(len([r for r in f.snap["rows"]
                              if r["kind"] == "user_input"]), 1)
        # 补放期结束：真实新消息照常画
        f._replay = False
        f.ingest(_env(2, "user_echo", data={"text": "历史一条"}))
        self.assertEqual(len([r for r in f.snap["rows"]
                              if r["kind"] == "user_input"]), 2)

    def test_replay_dedup末轮边界(self):
        # 单调上界：只有 at <= hydration 最大时刻 + 2s 的同文本才去重；
        # 显著更晚的同文本（用户真实重发）必须照常成行。
        # 已知窄窗：2s 内原样重发仍会被当作补放重复（仅 feed 冷建那一次）。
        f = self._feed()
        f._hyd_keys = {("user_input", "复述这句话")}
        f._hyd_max_at = 1_000_000
        f._replay = True
        # 同一时刻附近（补放重叠真实重复）→ 去重，不重画
        f.ingest(_env(1, "user_echo", ts=1_000_500,
                      data={"text": "复述这句话"}))
        self.assertEqual(len([r for r in f.snap["rows"]
                              if r["kind"] == "user_input"]), 0)
        # 显著更晚（> 容差，真实新消息）→ 照常画
        f.ingest(_env(2, "user_echo", ts=1_060_000,
                      data={"text": "复述这句话"}))
        self.assertEqual(len([r for r in f.snap["rows"]
                              if r["kind"] == "user_input"]), 1)

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

    def test_handback_report_goes_to_final_only(self):
        """结论单一真源：SubagentHandback 只进 state.final，不落行流
        （否则子 pane 时间线与结论区各画一份）。"""
        f = F.V4Feed(epoch="sub")
        f.feed_jsonl_line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback",
             "input": {"report": "交付的结论文本"}}]}})
        self.assertEqual(len(f.snap["rows"]), 0)
        self.assertEqual(f.snap["state"]["final"], "交付的结论文本")
        self.assertTrue(f.snap["state"]["done"])


if __name__ == "__main__":
    unittest.main()
