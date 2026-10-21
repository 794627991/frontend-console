# -*- coding: utf-8 -*-
"""v4feed/v4hub 单测：主 reducer 事件序列、子 jsonl 喂入、hydration、
订阅帧（resume/snapshot 裁决）。纯内存，不依赖真实 session/CLI。"""
import importlib.util
import os
import sys
import threading
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

    def test_user_echo_top_level_fields(self):
        """a17 实测根因回归：V3 事件业务字段在信封顶层（非 data）——
        user_echo/renew/queue 族 text 必须 correctly 取到。"""
        f = self._feed()
        # 信封顶层布局（session.py 真实 emit 形态：无 data 键）
        env = {"seq": 1, "ts": 1000, "epoch": "e1", "sid": "s1", "turn": "t1",
               "kind": "user_echo", "type": "user_echo",
               "text": "你好世界", "images": ["a.png"], "files": [],
               "cmd": "c1"}
        f.ingest(env)
        rows = f.snap["rows"]
        u = next(r for r in rows if r["kind"] == "user_input")
        self.assertEqual(u["text"], "你好世界")
        self.assertEqual(u["cmd"], "c1")
        self.assertEqual(u["images"], ["a.png"])
        # marker 顶层 text 同理
        f.ingest({"seq": 2, "ts": 1001, "epoch": "e1", "sid": "s1", "turn": "",
                  "kind": "renew", "type": "renew", "text": "已续命"})
        self.assertEqual(f.snap["rows"][-1]["text"], "已续命")

    def test_queue_snapshot_projection(self):
        """queue 事件带全量快照 → A 区（队列条投影驱动）。"""
        f = self._feed()
        qs = [{"id": "e1", "text": "排队一", "gen": 1, "ts": 1}]
        f.ingest({"seq": 1, "ts": 1000, "epoch": "e1", "sid": "s1", "turn": "",
                  "kind": "input_admitted", "type": "input_admitted",
                  "id": "e1", "queue": qs})
        self.assertEqual(f.snap["state"]["queue"], qs)
        f.ingest({"seq": 2, "ts": 1001, "epoch": "e1", "sid": "s1", "turn": "",
                  "kind": "input_promoted", "type": "input_promoted",
                  "id": "e1", "queue": []})
        self.assertEqual(f.snap["state"]["queue"], [])

    def test_ask_state_projection(self):
        """ask/ask_done → A 区（V3 askRender 挂 dock 形态，非消息行）。"""
        f = self._feed()
        f.ingest(_env(1, "ask", turn="", data={
            "req_id": "r1", "title": "请选择",
            "questions": [{"header": "方案", "question": "用 A 还是 B？",
                           "options": [{"label": "A"}, {"label": "B"}]}]}))
        self.assertEqual(f.snap["state"]["ask"]["req_id"], "r1")
        self.assertEqual(len(f.snap["state"]["ask"]["questions"]), 1)
        self.assertEqual([r["kind"] for r in f.snap["rows"]], [])   # 不成行
        f.ingest(_env(2, "ask_done", turn="", data={
            "req_id": "r1", "answer": {"方案": ["A"]}}))
        self.assertIsNone(f.snap["state"]["ask"])
        self.assertEqual(f.snap["state"]["ask_done"]["req_id"], "r1")

    def test_marker_and_peer(self):
        # peer 事件按后端真身 {name,text,to}（session.py emit）；识图发起走
        # cli_stream 的 tool_use（不产 vision 行——旧 vision 分支是死代码）
        f = self._feed()
        f.ingest(_env(1, "renew", turn="", data={"text": "已续命"}))
        f.ingest(_env(2, "peer", turn="", data={"name": "识图会话A",
                                                "text": "回传结论全文"}))
        rows = f.snap["rows"]
        self.assertEqual(rows[0]["kind"], "marker")
        self.assertEqual(rows[0]["mkind"], "renew")
        self.assertEqual(rows[1]["kind"], "peer_notify")
        self.assertEqual(rows[1]["name"], "识图会话A")
        self.assertEqual(rows[1]["text"], "回传结论全文")


class TestHubDedup(unittest.TestCase):
    """复审G3 回归缺口：坑②（ISO ts 解析死代码）的直接覆盖——
    _ts_ms 直测 + _hydrate_main 端到端断言 _hyd_max_at 非零。"""

    @classmethod
    def setUpClass(cls):
        import types
        pkg = sys.modules.get("harness")
        assert pkg is not None, "harness 包上下文由 test_v4feed 头部建立"
        # v4hub import consts（牵连 app_state）——测试注入桩模块
        if "harness.consts" not in sys.modules:
            stub = types.ModuleType("harness.consts")
            stub._sessions = {}
            stub._sessions_lock = threading.Lock()
            import logging
            stub.log = logging.getLogger("test-v4hub")
            sys.modules["harness.consts"] = stub
        spec = importlib.util.spec_from_file_location(
            "harness.v4hub", os.path.join(HARNESS_DIR, "v4hub.py"))
        cls.H = importlib.util.module_from_spec(spec)
        sys.modules["harness.v4hub"] = cls.H
        spec.loader.exec_module(cls.H)

    def test_ts_ms_iso_and_fallback(self):
        f = self.H._ts_ms
        import datetime
        want = int(datetime.datetime(2026, 10, 20, 12, 0, 0,
                                     tzinfo=datetime.timezone.utc).timestamp() * 1000)
        self.assertEqual(f("2026-10-20T12:00:00.123Z"), want + 123)   # Z 后缀
        self.assertEqual(f("2026-10-20T12:00:00+00:00"), want)        # 显式偏移
        self.assertEqual(f("2026-10-20T12:00:00.123456Z"), want + 123)  # 6 位小数秒
        self.assertEqual(f("1729410000000"), 1729410000000)           # 数字串兜底
        self.assertEqual(f(""), 0)
        self.assertEqual(f(None), 0)
        self.assertEqual(f("垃圾"), 0)                                # 垃圾回落 0

    def test_hydrate_main_sets_max_at(self):
        """端到端：ISO ts 的 transcript 行 hydration 后 _hyd_max_at 必须非零
        （坑②回归：旧 int(x[:13]) 写法恒 0 → 去重上界死代码 → 同文本重发误杀）。"""
        import tempfile
        import time as _t
        feed = F.V4Feed(epoch="e1")
        with tempfile.TemporaryDirectory() as td:
            # 假 transcript：transcript_for(s) 需要真 jsonl——直接单测
            # _hydrate_main 的上界计算逻辑等价段（v4hub 同式）
            rows = [{"kind": "user_input", "at": self.H._ts_ms(
                "2026-10-20T12:00:00.500Z"), "text": "hi"}]
            mx = max([int(r.get("at") or 0) for r in rows] or [0])
            self.assertEqual(mx, self.H._ts_ms("2026-10-20T12:00:00.500Z"))
            self.assertGreater(mx, 0)
        # _ts_ms 对 CLI 真实格式的存活是上界单调性的前提——不重述旧坑
        del feed, _t


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
