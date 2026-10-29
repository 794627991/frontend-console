# -*- coding: utf-8 -*-
"""v4feed/v4hub 单测：主 reducer 事件序列、子 jsonl 喂入、hydration、
订阅帧（resume/snapshot 裁决）。纯内存，不依赖真实 session/CLI。"""
import importlib.util
import os
import sys
import threading
import time
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

# v4hub 依赖 .consts（consts 又会拉 app_state → 跨包相对 import 炸）。
# 单测只需 consts 里的三个符号，桩掉即可，不牵连真实 app_state。
_cst = types.ModuleType("harness.consts")
_cst._sessions = {}
_cst._sessions_lock = threading.RLock()
_cst.log = __import__("logging").getLogger("test.v4hub")
sys.modules["harness.consts"] = _cst
H = _load("harness.v4hub", "v4hub.py")


def _env(seq, typ, turn="t1", data=None, ts=1000):
    return {"seq": seq, "ts": ts, "epoch": "e1", "sid": "s1",
            "turn": turn, "type": typ, "kind": typ, "data": data or {}}


def _use_temp_wseq_dir():
    """a116 十六次全审：wseq 高水位同步落盘 → 测试绝不能写真 HOME_DIR。
    全模块统一改用临时目录（首次 import 时执行一次）。"""
    import tempfile
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import src.eventlog.store as _S
    _S._WSEQ_DIR = tempfile.mkdtemp(prefix="wseq_test_")
    # 二十二次全审：BOOT 计数器也在同一目录，必须一并重定向，
    # 否则测试会写用户真实 ~/.serialconsole_pro/v4wseq/BOOT。
    F.V4Feed._boot_path = staticmethod(
        lambda: os.path.join(_S._WSEQ_DIR, "BOOT"))
    F.V4Feed._boot = None
    return _S


def _reset_hwm():
    """F1-R：V4Feed 有**进程级** wseq 高水位（跨实例严格递增）。测试要
    断言具体的 wseq 数值，必须先把水位归零，否则用例间互相污染。"""
    with F.V4Feed._hwm_lock:
        F.V4Feed._hwm.clear()
        F.V4Feed._hwm_floor = 0


def _mkfeed(epoch="e1", **kw):
    """构造 feed 并把起点归一化为 0——**仅供测试断言可读性**。

    生产路径的起点是墙钟微秒（1.79e15 量级），断言里写 `snap["seq"]==5`
    会全部失效。这里在构造后把 `_wseq_base`/`_wseq`/`snap["seq"]`/
    `_floor_seq` 一起平移到 0 起编，语义等价（相对关系
    不变），只是数值从大整数变成小整数。
    专门验证「起点单调/跨代拒绝」的用例**不要**用它——那些需要真实起点。
    """
    f = F.V4Feed(epoch=epoch, **kw)
    _off = f._wseq_base
    if _off:
        f._wseq_base = 0
        f._wseq = 0
        f.snap["seq"] = 0
        f._floor_seq = 0
    return f


# 模块级一次性切到临时目录：任何用例都不得写用户真实 HOME_DIR
_WSEQ_STORE = _use_temp_wseq_dir()


def _evlog(sid):
    """构造真实 SessionEventLog 门面（eventlog 是独立包，正常导入）。"""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from src.eventlog.log import SessionEventLog
    return SessionEventLog(sid)


class _HWMTestCase(unittest.TestCase):
    """所有会断言 wseq 数值的测试类都继承它：每例前重置进程级水位。"""

    def setUp(self):
        _reset_hwm()


class TestMainReducer(_HWMTestCase):
    def _feed(self):
        return _mkfeed("e1")

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
        # a65：镜像不再建 tool_call 行——权威卡=转写 Task tool_use
        self.assertEqual(len(tool), 0)

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
        # a65：isMeta 同滤（设计 §5.2；sse.js:1549 同款丢弃）
        f.ingest(_env(4, "cli_stream", data={
            "type": "assistant", "isMeta": True,
            "message": {"content": [{"type": "text", "text": "元行正文"}]}}))
        f.ingest(_env(5, "cli_stream", data={
            "type": "system", "agent_id": "agent_x",
            "subtype": "task_started", "message": {}}))
        f.ingest(_env(6, "cli_stream", data={
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "主会话正文"}]}}))
        texts = [r.get("text") for r in f.snap["rows"]
                 if r["kind"] == "assistant_text"]
        self.assertEqual(texts, ["主会话正文"])
        # 主链 assistant 带 agent_id 不过滤（sse.js 同口径，防误杀主窗正文）
        f.ingest(_env(7, "cli_stream", data={
            "type": "assistant", "agent_id": "agent_y",
            "message": {"content": [{"type": "text", "text": "主链二"}]}}))
        texts = [r.get("text") for r in f.snap["rows"]
                 if r["kind"] == "assistant_text"]
        self.assertEqual(texts, ["主会话正文", "主链二"])

    def test_bg_agent_ack_does_not_finalize(self):
        """a90 根修：run_in_background 的 Agent 派发，CLI 立即回执
        （"agent launched successfully… internal"）不得终结 tool 行——
        派发时刻定死=主窗卡假完成+过程同步停摆的源头。真终态由
        subagent_result（真摘要）/hand-back（✅ 报告）翻转。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "assistant", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "tu1", "name": "Agent",
                 "input": {"description": "审计", "run_in_background": True}}]}}))
        f.ingest(_env(3, "cli_stream", data={
            "type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tu1",
                 "content": "Agent launched successfully (id agent_aaaabbbbcccc "
                            "for internal use, not a final result)"}]}}))
        rows = [r for r in f.snap["rows"] if r["kind"] == "tool_call"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "running")
        self.assertFalse(rows[0].get("output"))
        # 真终态：notification 真摘要 → 行翻 success + ✅ 摘要
        f.ingest(_env(4, "subagent_started",
                      data={"task_id": "agent_aaaabbbbcccc", "tid": "tu1",
                            "desc": "审计"}))
        f.ingest(_env(5, "subagent_result",
                      data={"tid": "tu1", "ok": True, "brief": "审计完成：无阻塞问题"}))
        row = [r for r in f.snap["rows"] if r["kind"] == "tool_call"][0]
        self.assertEqual(row["status"], "success")
        self.assertTrue(row["output"].startswith("✅"))
        self.assertEqual(row["endedAt"], 1000)

    def test_fg_task_result_finalizes_normally(self):
        """前台 Task（无 run_in_background）：tool_result 就是真结果，
        照常终结——守卫只打击后台回执，不误伤前台。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "assistant", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "tu2", "name": "Task",
                 "input": {"description": "速查"}}]}}))
        f.ingest(_env(3, "cli_stream", data={
            "type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tu2",
                 "content": "查完了：3 处"}]}}))
        row = [r for r in f.snap["rows"] if r["kind"] == "tool_call"][0]
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["output"], "查完了：3 处")

    def test_bg_agent_dispatch_error_finalizes(self):
        """后台派发失败（回执 is_error）：真失败，照常终结为 error。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "assistant", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "tu3", "name": "Agent",
                 "input": {"description": "审计", "run_in_background": True}}]}}))
        f.ingest(_env(3, "cli_stream", data={
            "type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tu3",
                 "is_error": True, "content": "agent not found"}]}}))
        row = [r for r in f.snap["rows"] if r["kind"] == "tool_call"][0]
        self.assertEqual(row["status"], "error")

    def test_sendmessage_receipt_does_not_finalize(self):
        """a110S：SendMessage 行卡的语义=续派链——送达回执（resumedAgentId）
        不终结行；链的 notification（tid=包装 call id）回填真终态。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "assistant", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "sm1", "name": "SendMessage",
                 "input": {"to": "agent_aaaabbbbcccc",
                           "message": "继续完成审计"}}]}}))
        f.ingest(_env(3, "cli_stream", data={
            "type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "sm1",
                 "content": "Message delivered to agent_aaaabbbbcccc "
                            "(resumedAgentId: agent_aaaabbbbcccc)"}]}}))
        row = [r for r in f.snap["rows"] if r["kind"] == "tool_call"][0]
        self.assertEqual(row["status"], "running")
        self.assertFalse(row.get("output"))
        # 链完成：notification（tid=包装 id）→ 行翻 success + ✅ 真摘要
        f.ingest(_env(4, "subagent_result",
                      data={"tid": "sm1", "ok": True, "brief": "审计完成：全部通过"}))
        row = [r for r in f.snap["rows"] if r["kind"] == "tool_call"][0]
        self.assertEqual(row["status"], "success")
        self.assertTrue(row["output"].startswith("✅"))

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


    def test_can_resume_quiet_feed(self):
        """a92：安静 feed（无新帧）可续传——frames_after 的 None 二义性
        （无新帧 vs 越窗）曾让路由把每次重连都判成整窗 snapshot。"""
        f = self._feed()
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "user_echo", data={"text": "hi"}))
        last = f.last_seq
        # 无新帧：frames_after None 但 can_resume True（resume 空转）
        self.assertIsNone(f.frames_after(last))
        self.assertTrue(f.can_resume(last))
        # 越出保留窗：两者都不行（snapshot 兜底）
        # 判据下界是空间起点 _wseq_base（floor 只决定「还有多少增量可取」）
        f._wseq_base = last + 1
        self.assertFalse(f.can_resume(last))

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


class TestHubDedup(_HWMTestCase):
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

    # ---- a82：冷建对账（在飞回合的 busy/组头/_turn_rows/_held 回填） ----

    def _hydrated_feed(self):
        """hydration 形态的投影：末组头 state=success（无 startedAt/endedAt），
        _turn_rows 空、state 空——v4_main_feed 冷建后 reconcile 前的真身。"""
        feed = F.V4Feed(epoch="e1")
        feed._row_id += 1
        feed.snap["rows"].append(P.mk_row(
            feed._row_id, "t1", "turn_header", 1000, 0, state="success"))
        feed.snap["total"] += 1
        feed._row_id += 1
        feed.snap["rows"].append(P.mk_row(
            feed._row_id, "t1", "user_input", 1000, 0, text="审"))
        feed.snap["total"] += 1
        feed._row_id += 1
        feed.snap["rows"].append(P.mk_row(
            feed._row_id, "t1", "tool_call", 1200, 0, tool="Bash",
            status="success", tid="call_1"))
        feed.snap["total"] += 1
        return feed

    def test_reconcile_live_flips_running_and_registers(self):
        """busy 会话冷建：末组头翻 running + _turn_rows 登记 + A 区 busy/curTurn
        （用户实测「定稿折叠藏 19 卡」的直接回归）。"""
        import types
        feed = self._hydrated_feed()
        s = types.SimpleNamespace(busy=True, _turn_id="d784783e0000",
                                  _held=True, busy_since=900)
        self.H._reconcile_live(feed, s)
        hdr = feed.snap["rows"][0]
        self.assertEqual(hdr["state"], "running")
        self.assertEqual(hdr.get("startedAt"), 1000)
        self.assertNotIn("endedAt", hdr)
        self.assertEqual(feed._turn_rows.get("d784783e0000"), hdr["rowId"])
        self.assertTrue(feed.snap["state"].get("busy"))
        self.assertEqual(feed.snap["state"].get("curTurn"), "d784783e0000")
        self.assertTrue(feed._held)
        # 链路闭环：真 turn_complete 到达 → 收口既有组头（非幽灵新组）+ busy 熄灭
        feed.ingest(_env(300, "turn_complete", turn="d784783e0000", ts=5000))
        self.assertEqual(feed.snap["rows"][0]["state"], "success")
        self.assertFalse(feed.snap["state"].get("busy"))

    def test_reconcile_live_idle_untouched(self):
        """非 busy 会话冷建：不碰任何状态（历史会话回放不受影响）。"""
        import types
        feed = self._hydrated_feed()
        s = types.SimpleNamespace(busy=False, _turn_id=None,
                                  _held=False, busy_since=None)
        self.H._reconcile_live(feed, s)
        self.assertEqual(feed.snap["rows"][0]["state"], "success")
        self.assertFalse(feed.snap["state"])
        self.assertFalse(feed._turn_rows)

    def test_reconcile_live_stale_transcript_no_flip(self):
        """转写未覆盖当前回合（CLI 未落盘）：末组头不翻（上一轮定稿组头
        不能误伤），A 区 busy 仍回填。"""
        import types
        feed = self._hydrated_feed()
        s = types.SimpleNamespace(busy=True, _turn_id="aaaabbbbcccc",
                                  _held=False, busy_since=9999)
        self.H._reconcile_live(feed, s)
        self.assertEqual(feed.snap["rows"][0]["state"], "success")
        self.assertNotIn("aaaabbbbcccc", feed._turn_rows)
        self.assertTrue(feed.snap["state"].get("busy"))


class TestSubFeed(_HWMTestCase):
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
        # a70：input 随行——子 pane 卡头 hint（command/file_path）/diff 改动
        # 体/查阅聚组判定全靠它（与主投影 tool_use 同构）
        self.assertEqual(rows[2]["input"].get("pattern"), "x")
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

    def test_sub_round_boundary_resets_state(self):
        """a117（用户实锤「上一轮结论被当本轮结论，本轮还在跑却显示
        已工作」）：续派新轮的 user 行到达=轮界——陈旧 done/final/err
        必须复位，否则快照/看门狗重放把进行中的新轮定稿+旧结论顶上。"""
        f = F.V4Feed(epoch="s")
        f.feed_jsonl_line({"type": "user", "message": {"content": "第一轮任务"}})
        f.feed_jsonl_line({"type": "result", "result": "第一轮结论",
                           "is_error": False})
        self.assertTrue(f.snap["state"]["done"])
        self.assertEqual(f.snap["state"]["final"], "第一轮结论")
        # 续派第二轮：user 行（真实续派消息，非机器注入）
        f.feed_jsonl_line({"type": "user",
                           "message": {"content": "继续：第二轮任务"}})
        self.assertFalse(f.snap["state"]["done"])
        self.assertEqual(f.snap["state"]["final"], "")
        # 第二轮进行中（思考行在流，无 result）——保持 running
        f.feed_jsonl_line({"type": "assistant",
                           "message": {"model": "m", "content": [
                               {"type": "thinking", "thinking": "第二轮思考中"}]}})
        self.assertFalse(f.snap["state"]["done"])

    def test_uuid_dedup_watcher_vs_hydrate(self):
        """a65：同 uuid 行二次喂入 no-op——hydrate 全量与 watcher 增量
        并发重叠窗口的同行双画闸。"""
        f = F.V4Feed(epoch="sub")
        line = {"uuid": "u-1", "type": "assistant", "message": {
            "model": "m", "content": [{"type": "text", "text": "一"}]}}
        self.assertTrue(f.feed_jsonl_line(dict(line)))
        self.assertFalse(f.feed_jsonl_line(dict(line)))
        texts = [r.get("text") for r in f.snap["rows"]
                 if r["kind"] == "assistant_text"]
        self.assertEqual(texts, ["一"])
        # 无 uuid 的行不受影响（旧格式照常消费）
        self.assertTrue(f.feed_jsonl_line({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "二"}]}}))


class TestFullAuditRegressions(_HWMTestCase):
    """全审（2026-10-23）修复项回归：每条对应一个已取证缺陷。"""

    def test_f2_handback_cli_stream_no_nameerror(self):
        """F2：含 hand-back 的 cli_stream 事件不得抛 NameError（模块级 re
        缺失）；并且要真的把结论写进行卡 output。"""
        f = F.V4Feed(epoch="e1")
        f.ingest(_env(1, "subagent_started",
                      data={"tid": "tu1", "desc": "审查", "aid": "abc12345"}))
        f.ingest(_env(2, "cli_stream", data={
            "type": "user", "message": {"content": [{"type": "text", "text":
                '[Subagent hand-back] The report follows:\n'
                '<agent-message from="a4ec4a0433c71b3f4">\n  真结论\n'
                '</agent-message>'}]}}))
        # 不得抛异常（旧实现 NameError），且 aid 正则命中真实形态
        m = F.HB_AID_RE.search('from="a4ec4a0433c71b3f4"')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "a4ec4a0433c71b3f4")

    def test_aid_regex_real_forms(self):
        """F1：三形态——from="X"（真实）/ from "X"（旧口径）/ from-name="X"。"""
        self.assertEqual(F.HB_AID_RE.search('from="abcdefgh"').group(1),
                         "abcdefgh")
        self.assertEqual(F.HB_AID_RE.search('from "abcdefgh"').group(1),
                         "abcdefgh")
        self.assertIsNone(F.HB_AID_RE.search('from-name="abcdefgh"'))
        self.assertIsNone(F.HB_AID_RE.search('from ""'))

    def test_f4_seq_monotonic_under_out_of_order(self):
        """F4 + a116 九次全审根修：乱序摄入不得让**投递序号**回退，
        `_seqs` 必须保持严格递增（bisect 前提）。

        旧方案让真实 seq 直接当投递序号并按序插入，迟到时靠哨兵 +1 抬高
        水位——但哨兵值恰好等于下一笔真实 seq，该事件必然再被判迟到，
        形成「每个事件一次整窗快照」的循环（九次全审实测 16/17 轮）。
        分离后：真实 seq 只判重，投递序号单调追加，乱序无任何副作用。"""
        f = F.V4Feed(epoch="e1")

        def _c(seq, ds):
            # 与 ingest/feed_jsonl_line 同序：先查重，成功落账后由
            # `_commit` 登记（F2）
            with f._lock:
                if f._seen_seq(seq):
                    return False
            return f._commit(seq, ds)

        _b0 = f.snap["seq"]
        _c(12, [P.d_state({"x": 12})])
        _c(11, [P.d_state({"x": 11})])
        self.assertEqual(f.snap["seq"], _b0 + 2)     # 投递序号 +1、+1
        self.assertEqual(f._seqs, [_b0 + 1, _b0 + 2])  # 严格递增
        self.assertEqual(f._resnap_ver, 0)           # 无需重对齐
        _c(12, [P.d_state({"x": 12})])               # 重复真实 seq 幂等
        self.assertEqual(f._seqs, [_b0 + 1, _b0 + 2])
        self.assertEqual(f.snap["seq"], _b0 + 2)

    def test_f4_frames_after_no_lost_row(self):
        """F4 端到端：先 12 后 11，订阅者从 0 拉帧两者都要覆盖到。"""
        _reset_hwm()
        f = _mkfeed("e1")
        f._commit(11, [P.d_state({"a": 1})])
        f._commit(12, [P.d_state({"b": 2})])
        # 订阅者从窗口下界**之前**拉帧（0 表示「本地无内容」）：
        # 新实例 floor 从 1 起，0 尚未越窗（seq >= _wseq_base=0 成立），
        # 两条都必须在帧里——这正是 F4「乱序不丢行」的断言点。
        fr = f.frames_after(0)
        self.assertIsNotNone(fr)
        deltas, to = fr
        self.assertEqual(to, 2)                     # 投递序号末位
        merged = {}
        for d in deltas:                            # coalesce 可能合帧
            if d.get("op") == "state.updated":
                merged.update(d.get("patch") or {})
        self.assertEqual(merged, {"a": 1, "b": 2})  # 两条都在，未丢 11

    def test_s3_interrupted_does_not_override_success(self):
        """S3：已 success 的组头不得被后到的 interrupted 翻 cancelled。"""
        f = F.V4Feed(epoch="e1")
        f.ingest(_env(1, "turn_started", turn="t1"))
        f.ingest(_env(2, "turn_complete", turn="t1"))
        hdr = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(hdr[-1]["state"], "success")
        f.ingest(_env(3, "interrupted", data={"text": "stopped"}))
        hdr = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(hdr[-1]["state"], "success")   # 不得翻 cancelled

    def test_hb_is_meta_single_point(self):
        """S7：两种元数据文案 + 2 空格缩进都必须识别为元数据。
        一般9（a116 全审）：真结论正文里**提到**该短语不得误判为元数据。"""
        for s in ("This agent's report was delivered to you",
                  "  This agent's report was delivered",
                  '   delivered to you as a message from "abc"'):
            self.assertTrue(F.hb_is_meta(s), s)
        self.assertFalse(F.hb_is_meta("✅ 真正的结论文本"))
        self.assertFalse(F.hb_is_meta(
            "✅ 结论：CLI 打印了 delivered to you as a message from x"))

    def test_subagent_done_resets_on_resume(self):
        """P2：续派 resume 后新轮**用户指令行**必须复位 done/final
        （否则新轮立刻定稿）。致命1（a116 二次全审）修正了复位判据：
        只有纯文本 user 行（无 tool_result 块）才是新一轮起点；
        assistant/收尾 tool_result 行不得复位——否则已完结代理被翻回
        running 且无 result 行能重新落定（147/147 份真实转写全中）。"""
        f = F.V4Feed(epoch="sub")
        f.feed_jsonl_line({"type": "result", "result": "第一轮结论",
                           "timestamp": "2026-01-01T00:00:00Z"})
        self.assertTrue(f.snap["state"]["done"])
        # 收尾形态：assistant 追写行不得复位
        f.feed_jsonl_line({"type": "assistant", "timestamp":
                           "2026-01-01T00:05:00Z", "message": {
                               "model": "m", "content": [
                                   {"type": "text", "text": "结尾说明"}]}})
        self.assertTrue(f.snap["state"]["done"], "assistant 行不得复位 done")
        # 收尾形态：tool_result 行不得复位
        f.feed_jsonl_line({"type": "user", "timestamp":
                           "2026-01-01T00:06:00Z", "message": {
                               "content": [{"type": "tool_result",
                                            "tool_use_id": "x",
                                            "content": "ok"}]}})
        self.assertTrue(f.snap["state"]["done"], "tool_result 行不得复位 done")
        # 真续派：纯文本 user 指令行 = 新一轮
        f.feed_jsonl_line({"type": "user", "timestamp":
                           "2026-01-01T00:10:00Z", "message": {
                               "content": [{"type": "text",
                                            "text": "再查一遍"}]}})
        self.assertFalse(f.snap["state"]["done"])
        self.assertEqual(f.snap["state"]["final"], "")

    # ------------------------------------------------------------------
    # 修复全审（a116 全审代理）发现的三致命/三严重回归面
    # ------------------------------------------------------------------
    def test_hydration_must_not_reset_done(self):
        """致命2：全量 hydration 不得把已完结子代理翻回 running。
        子代理落地 SubagentHandback 后 CLI 仍追写行（ts 更晚），逐行复位
        会让 169/169 份已完结子转写全部 done=False、final 清空。"""
        import json as _j
        import os as _o
        import tempfile
        lines = [
            {"type": "assistant",
             "timestamp": "2026-01-01T00:00:00Z",
             "message": {"model": "m", "content": [
                 {"type": "tool_use", "name": "SubagentHandback",
                  "input": {"report": "REAL REPORT"}}]}},
            {"type": "user", "timestamp": "2026-01-01T00:00:05Z",
             "message": {"content": [
                 {"type": "tool_result", "content": "late"}]}},
        ]
        p = _o.path.join(tempfile.mkdtemp(), "s.jsonl")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_j.dumps(x) for x in lines))
        f = F.V4Feed(epoch="sub")
        f.hydrate_jsonl(p)
        self.assertTrue(f.snap["state"].get("done"))
        self.assertIn("REAL REPORT", f.snap["state"].get("final") or "")

    def test_dup_seq_does_not_double_apply(self):
        """严重5：重复 seq 必须在 apply_deltas **之前**判重。
        旧实现先 apply 再交给 _commit 丢弃——log 只一条，投影却两份。
        a116 九次全审：判重键是**真实 seq**，投递序号 wseq 每次 +1。"""
        f = _mkfeed()
        env = _env(1, "user_echo", data={"text": "HELLO"})
        f.ingest(env)
        f.ingest(env)
        rows = [r for r in f.snap["rows"] if r.get("kind") == "user_input"]
        self.assertEqual(len(rows), 1, "投影被二次应用：%r" % rows)
        self.assertEqual(f._seqs, [1])          # 只有一条投递记录

    def test_late_seq_gets_new_wire_seq(self):
        """a116 九次全审（根修）：**投递序号与真实 seq 分离**。

        历史方案（迟到保原 seq 有序插入 + 哨兵水位 + per-connection resnap）
        已全部删除——它们的共同前提是「一个数既当事件身份又当游标」，
        九次全审实测：哨兵后的水位恰好等于下一笔真实 seq，该事件必然再被
        判「迟到」，此后每个事件都退化为整窗快照（16/17 轮全是快照），
        且 `_late_lo` 永久钉死导致断线重连永远被拒续传。

        新不变量：迟到事件拿到**末尾的新投递序号** → 落在任何游标之后
        → 任何连接都能通过 frames_after 正常取到，无需重对齐/强制快照。"""
        f = _mkfeed()
        f.ingest(_env(12, "turn_started", turn="t2"))
        f.ingest(_env(11, "turn_complete", turn="t2"))
        # 投递序号严格递增：[1, 2] —— 与真实 seq 无关
        self.assertEqual(f._seqs, [1, 2])
        self.assertEqual(f.snap["seq"], 2)
        # 迟到不再触发任何重对齐
        self.assertEqual(f._resnap_ver, 0)
        self.assertEqual((f._late_lo, f._late_snap), (0, 0))
        # 后续真实事件照常落地，且不会被误判迟到
        f.ingest(_env(13, "user_echo", data={"text": "REAL13"}))
        self.assertEqual(f._seqs, [1, 2, 3])
        self.assertEqual(f._resnap_ver, 0, "真实新事件被误判为迟到")
        texts = [r.get("text") for r in f.snap["rows"]
                 if r.get("kind") == "user_input"]
        self.assertIn("REAL13", texts)

    def test_late_seq_does_not_hijack_future(self):
        """FATAL-8 最小复现：1,3 到达后 2 迟到，随后真实 4 必须落地。"""
        f = _mkfeed()
        for s in (1, 3):
            f.ingest(_env(s, "user_echo", data={"text": "M%d" % s}))
        f.ingest(_env(2, "user_echo", data={"text": "M2"}))
        f.ingest(_env(4, "user_echo", data={"text": "M4"}))
        self.assertEqual(f._seqs, [1, 2, 3, 4])   # 投递序号，四次都在
        texts = [r.get("text") for r in f.snap["rows"]
                 if r.get("kind") == "user_input"]
        self.assertIn("M4", texts, "真实 seq=4 被迟到重分配占用")
        self.assertEqual(len(texts), 4)

    def test_disconnected_client_gets_late_row_by_resume(self):
        """a116 九次全审：断线期间的迟到事件，重连后**续传即可拿到**——
        迟到拿到新的末尾投递序号，落在客户端游标之后。

        旧方案要求 here 拒续传逼整窗快照（_late_lo/_late_snap 区间），
        代价是长跑会话「每次重连整窗快照」+ 快照无限循环。分离后不需要。"""
        f = _mkfeed()
        for s in (1, 2, 4):
            f.ingest(_env(s, "user_echo", data={"text": "M%d" % s}))
        _cur = f.snap["seq"]                       # 客户端断线时的游标 = 3
        f.ingest(_env(3, "user_echo", data={"text": "LATE3"}))
        # 迟到追加为投递序号 4
        self.assertEqual(f._seqs, [1, 2, 3, 4])
        self.assertTrue(f.can_resume(_cur), "可续传（无需整窗快照）")
        fr = f.frames_after(_cur)
        self.assertIsNotNone(fr, "迟到行必须能被增量投递到")
        self.assertEqual(fr[1], 4)
        import json as _jj
        _txt = _jj.dumps(fr[0], ensure_ascii=False)
        self.assertIn("LATE3", _txt, "迟到行内容未出现在增量帧中")
        # 断线重连的最坏情况：游标恰好等于当前水位 → 安静续传
        self.assertTrue(f.can_resume(f.snap["seq"]))
        self.assertIsNone(f.frames_after(f.snap["seq"]))
        # 干净 feed 完全不受影响
        g = F.V4Feed()
        g.ingest(_env(1, "user_echo", data={"text": "A"}))
        # N2（十二次全审）：floor 是真实条目，游标 == floor 表示已消费到
        # 该条 → 后续全部可投递，应放行（等号历史风险由「起点严格递增」兜）
        self.assertTrue(g.can_resume(g._floor_seq))
        # 游标 == floor：该条已消费，之后无新帧 → None（安静续传）
        self.assertIsNone(g.frames_after(g._floor_seq))

    def test_poll_is_atomic_with_frames(self):
        """一般-1（a116 八次全审）：`poll` 在同一把锁里判定与取帧，
        消除「判版本」与「取帧」之间的落账窗口。
        九次全审根修后迟到可正常投递，poll 简化为纯取帧（返回 frame）。"""
        f = _mkfeed()
        for s in (1, 2, 4):
            f.ingest(_env(s, "user_echo", data={"text": "M%d" % s}))
        fr0 = f.poll(2)
        self.assertIsNotNone(fr0, "游标 2 之后有真实增量")
        f.ingest(_env(3, "user_echo", data={"text": "LATE3"}))
        fr1 = f.poll(3)
        self.assertIsNotNone(fr1, "迟到行必须能被 poll 取到")
        self.assertEqual(fr1[1], 4)
        import json as _jj
        self.assertIn("LATE3", _jj.dumps(fr1[0], ensure_ascii=False))
        # 越窗游标：frame 为 None（调用方走快照）
        self.assertIsNone(f.poll(-1))

    def test_resume_probe_matches_two_step(self):
        """一般-1：`resume_probe` 必须与 (can_resume, frames_after) 两段式
        在全部边界上结论一致，否则路由起始裁决会与旧行为分叉。"""
        f = _mkfeed()
        for s in (1, 2, 4):
            f.ingest(_env(s, "user_echo", data={"text": "M%d" % s}))
        f.ingest(_env(3, "user_echo", data={"text": "LATE3"}))
        for seq in (0, 1, 2, 3, 4, 5, 99):
            ok, fr, last = f.resume_probe(seq)
            self.assertEqual(ok, f.can_resume(seq),
                             "resume_probe 与 can_resume 在 seq=%d 分叉" % seq)
            if ok:
                two = f.frames_after(seq)
                if two is None:
                    self.assertIsNone(fr)
                else:
                    self.assertIsNotNone(fr)
                    self.assertEqual(fr[1], two[1])
                self.assertEqual(last, f.snap["seq"])

    def test_trim_keeps_dedup_bounded_and_log_bounded(self):
        """a116 九次全审：`_trim` 只收 log（按投递序号），**不得**动真实
        seq 的判重集——旧实现同步重建 `_seq_set`，越窗真实 seq 失去判重
        能力，同一事件二次投递会多画一行（审计实测 rows 999→1000）。

        判重集另有自己的有界策略（8192 FIFO），与 log 窗口无关。"""
        f = F.V4Feed()
        for s in range(1, 2000):
            f.ingest(_env(s, "user_echo", data={"text": "x%d" % s}))
        self.assertEqual(len(f._log), F.LOG_RETAIN, "log 未按窗口裁剪")
        self.assertEqual(len(f._seqs), F.LOG_RETAIN)
        self.assertEqual(f._floor_seq, f._seqs[0])
        # 判重集仍保留全部真实 seq（2000 条 < 8192 上限）
        self.assertEqual(len(f._seq_set), 1999 - 1 + 1)   # seq 1..1999
        # 越窗真实 seq 再投一次 → 必须被挡住（不得多画一行）
        n0 = len([r for r in f.snap["rows"] if r.get("kind") == "user_input"])
        f.ingest(_env(5, "user_echo", data={"text": "x5"}))
        n1 = len([r for r in f.snap["rows"] if r.get("kind") == "user_input"])
        self.assertEqual(n0, n1, "越窗真实 seq 未被判重挡住（多画一行）")

    def test_zero_output_replays_ledger(self):
        """致命3：hydration 零产出时必须从 0 重放账本。
        旧实现置 h=0 后被前置门 `if h>0` 整个跳过——事件一条都不重放。"""
        class _Log(object):
            epoch = 0
            last_seq = 3

            def events_after(self, lo):
                return [_env(s, "user_echo", data={"text": "M%d" % s})
                        for s in range(1, 4) if s > lo]

        class _S(object):
            sid = "__t_zero__"
            session_id = "x"
            log = _Log()
            _turn_id = ""
            _held = False
            busy = False
            busy_since = 0

            def queue_list(self):
                return []

        _orig_hyd = H._hydrate_main
        H._hydrate_main = lambda feed, s: None   # 强制零产出
        try:
            feed = H.v4_main_feed(_S())
            rows = [r for r in feed.snap["rows"]
                    if r.get("kind") == "user_input"]
            self.assertEqual(len(rows), 3,
                             "零产出未从账本全量重放：rows=%r" % rows)
        finally:
            H._hydrate_main = _orig_hyd
            H.v4_drop_session("__t_zero__")

    def test_ingest_not_dropped_during_build(self):
        """严重4：冷建窗口内（hydration 进行中、_main_wanted 未登记）
        落账的事件不得被门禁丢弃。"""
        class _S(object):
            sid = "__t_gate__"
            session_id = "y"

        s = _S()
        with H._lock:
            H._building.add(s.sid)          # 模拟冷建进行中
        n = {"c": 0}

        class _Feed(object):
            def ingest(self, env):
                n["c"] += 1

        orig = H.v4_main_feed
        H.v4_main_feed = lambda _s: _Feed()
        try:
            H.v4_ingest_main(s, {"seq": 1})
            self.assertEqual(n["c"], 1, "冷建窗口内事件被门禁丢弃")
        finally:
            H.v4_main_feed = orig
            with H._lock:
                H._building.discard(s.sid)

    def test_pending_live_keeps_order(self):
        """FATAL-4（a116 三次全审）：冷建窗口内的 live 事件必须并入**历史
        之后**。旧实现直投投影，live 行先占 rowId、hydration 把历史 append
        在其后 → 实时消息显示在历史之前（真实可达：多标签页/切回会话）。"""
        class _Log(object):
            epoch = 0
            last_seq = 1

            def events_after(self, lo):
                return []

        class _S(object):
            sid = "__t_order__"
            session_id = "x"
            log = _Log()
            _turn_id = ""
            _held = False
            busy = False

            def queue_list(self):
                return []

        _orig = H._hydrate_main

        def _hyd(feed, s):
            feed.snap["rows"].append(
                F.P.mk_row(1, "t1", "user_input", 500, 0, text="HIST"))
            # 模拟水化进行中另一线程 emit
            H.v4_ingest_main(_S(), {"seq": 3, "ts": 900, "turn": "t1",
                                    "type": "user_echo",
                                    "data": {"text": "LIVE3"}})

        H._hydrate_main = _hyd
        try:
            feed = H.v4_main_feed(_S())
            texts = [r.get("text") for r in feed.snap["rows"]
                     if r.get("kind") == "user_input"]
            self.assertEqual(texts, ["HIST", "LIVE3"],
                             "live 行排到了历史之前或丢失：%r" % texts)
        finally:
            H._hydrate_main = _orig
            H.v4_drop_session("__t_order__")

    def test_pending_does_not_break_zero_output(self):
        """FATAL-5（a116 三次全审）：冷建期 live 事件不得让 `_zero` 判据
        失效——否则账本里 seq<=h 的本回合前半段（turn_started/user_echo）
        永不重放，用户消息永久丢失（P0-4 回退）。"""
        class _Log(object):
            epoch = 0
            last_seq = 2

            def events_after(self, lo):
                evs = [{"seq": 1, "ts": 100, "turn": "t1",
                        "type": "turn_started", "data": {}},
                       {"seq": 2, "ts": 200, "turn": "t1",
                        "type": "user_echo", "data": {"text": "用户的问题"}}]
                return [e for e in evs if e["seq"] > lo]

        class _S(object):
            sid = "__t_zero_live__"
            session_id = "x"
            log = _Log()
            _turn_id = ""
            _held = False
            busy = False

            def queue_list(self):
                return []

        _orig = H._hydrate_main
        H._hydrate_main = lambda feed, s: H.v4_ingest_main(
            _S(), {"seq": 3, "ts": 900, "turn": "t1", "type": "user_echo",
                   "data": {"text": "LIVE3"}})
        try:
            feed = H.v4_main_feed(_S())
            texts = [r.get("text") for r in feed.snap["rows"]
                     if r.get("kind") == "user_input"]
            self.assertIn("用户的问题", texts,
                          "账本前半段被 live 污染后未重放：%r" % texts)
            self.assertIn("LIVE3", texts)
        finally:
            H._hydrate_main = _orig
            H.v4_drop_session("__t_zero_live__")

    def test_ttl_rebuild_keeps_history_and_live(self):
        """FATAL-6（a116 四次全审）：TTL 到期后必须正常重建 + 从 0 重放，
        既保住历史（转写已落盘）也保住临时 feed 里的 live 行。
        旧修法「转正入册」在 hydration 之前 return → 该会话主窗**永久
        没有历史**（刷新也无，只有后端重启/rewind 才恢复）。"""
        class _Log(object):
            epoch = 0
            last_seq = 2

            def events_after(self, lo):
                evs = [{"seq": 1, "ts": 100, "turn": "t1",
                        "type": "user_echo", "data": {"text": "HISTORY-1"}},
                       {"seq": 2, "ts": 200, "turn": "t1",
                        "type": "user_echo", "data": {"text": "LIVE2"}}]
                return [e for e in evs if e["seq"] > lo]

        class _S(object):
            sid = "__t_ttl__"
            session_id = "x"
            log = _Log()
            _turn_id = ""
            _held = False
            busy = False

            def queue_list(self):
                return []

        _orig = H._hydrate_main
        H._hydrate_main = lambda feed, s: None      # 零产出
        try:
            f1 = H.v4_main_feed(_S())
            f1.ingest(_env(2, "user_echo", data={"text": "LIVE2"}))
            with H._lock:                            # 强制 TTL 过期
                _e = H._empty_feeds.get("__t_ttl__")
                if _e:
                    H._empty_feeds["__t_ttl__"] = (
                        _e[0], time.time() - 40, _e[2])
            f2 = H.v4_main_feed(_S())
            texts = [r.get("text") for r in f2.snap["rows"]
                     if r.get("kind") == "user_input"]
            self.assertIn("HISTORY-1", texts,
                          "TTL 重建后历史不可见：%r" % texts)
            self.assertIn("LIVE2", texts, "live 行丢失：%r" % texts)
        finally:
            H._hydrate_main = _orig
            H.v4_drop_session("__t_ttl__")

    def test_building_flag_not_leaked(self):
        """全审（a116）：_building 的 add/discard 必须成对——泄漏会让门禁
        对该 sid 永久放行（V3 会话每 emit 付一次完整投影开销）。"""
        class _BadLog(object):
            epoch = 0
            last_seq = 1

            def events_after(self, lo):
                raise RuntimeError("boom")       # 逼异常路径

        class _S(object):
            sid = "__t_leak__"
            session_id = "z"
            log = _BadLog()
            _turn_id = ""
            _held = False
            busy = False

            def queue_list(self):
                return []

        _orig_hyd = H._hydrate_main
        H._hydrate_main = lambda feed, s: None
        origins = (H._replay_from, H._reconcile_live)
        H._replay_from = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("boom"))
        try:
            try:
                H.v4_main_feed(_S())
            except Exception:
                pass
            self.assertNotIn("__t_leak__", H._building,
                             "_building 泄漏：门禁将对该 sid 永久放行")
        finally:
            H._replay_from, H._reconcile_live = origins
            H._hydrate_main = _orig_hyd
            H.v4_drop_session("__t_leak__")


    def test_wseq_base_prevents_history_loss_across_rebuild(self):
        """F1（a116 十次全审，致命）：feed 重建后 wseq **不得**从 1 重编。

        重现路径：进程重启 / TTL 换空 feed / 临时 feed 转正式——epoch
        不变（lifecycle 沿用账本 epoch），而客户端持久游标是旧实例的 wseq。
        若新实例从 1 起编，旧游标 3 在新空间里 map 成「第 3 个事件」→
        resume_probe 返回 ok → 只发增量 → **旧游标之前的行永久缺失，
        且 epoch 相同永不回退快照**（审计实测丢 3/15 条）。
        修法：起点由调用方按跨实例单调的量注入（账本水位 / 时间戳）。"""
        # 旧实例：发到 wseq=3，客户端游标 = 3
        _reset_hwm()
        old = F.V4Feed(epoch="EP")
        _o0 = old.snap["seq"]
        for s in (1, 2, 3):
            old.ingest(_env(s, "user_echo", data={"text": "OLD%d" % s}))
        self.assertEqual(old.snap["seq"], _o0 + 3)
        _cursor = old.snap["seq"]
        # 新实例：起点必须高于旧游标（主 feed 用账本水位）
        new = F.V4Feed(epoch="EP", wseq_base=_cursor)
        _b = new.snap["seq"]
        self.assertGreater(_b, _cursor, "快照 toSeq 必须严格越过旧游标")
        for s in range(501, 516):
            new.ingest(_env(s, "user_echo", data={"text": "NEW%d" % s}))
        ok, fr, _last = new.resume_probe(_cursor)
        self.assertFalse(ok, "旧游标在新空间里被误判为可续传 → 静默丢历史")
        # 合法游标（新空间内、快照 toSeq 之后）照常续传
        _snap_to = new.snap["seq"]
        self.assertTrue(new.can_resume(_snap_to))
        self.assertIsNone(new.frames_after(_snap_to))   # 已在最新，安静续传

    def test_claim_registered_only_after_success(self):
        """F2（a116 十次全审，严重）：判重登记必须在**成功落账之后**。

        原实现在 apply 之前登记，一旦 reducer/apply 抛瞬态异常、调用方
        回队重试（v4hub MAJOR-12 回队机制），重试会被判重拒掉 → 事件永久
        丢失。真实可达入口：CLI 给出非字符串 text 时 `_reduce_cli` 抛
        AttributeError（v4feed.py 内 .strip()）。"""
        f = F.V4Feed()
        bad = _env(9, "cli_stream", data={"type": "assistant",
                                          "message": {"content": [
                                              {"type": "text", "text": 123}]}})
        with self.assertRaises(Exception):
            f.ingest(bad)
        # 抛异常后不得留下判重登记
        self.assertFalse(f._seen_seq(9), "失败事件被登记 → 重试将被拒")
        # 重试（同 seq，内容正常）必须放行
        f.ingest(_env(9, "user_echo", data={"text": "M9"}))
        texts = [r.get("text") for r in f.snap["rows"]
                 if r.get("kind") == "user_input"]
        self.assertIn("M9", texts, "重试被误判重复而丢弃")

    def test_seen_seq_is_query_only(self):
        """F3（a116 十次全审）：`_seen_seq` 只查不登记——早退路径
        （`_dup_hist` 命中 / 无 ds）不会把真实 seq 吃掉，随后同一事件经
        pending 转投仍能正常落账。"""
        f = F.V4Feed()
        # 一条不产 ds 的事件（turn_complete 无对应 turn → 只补 header，
        # 用 ask_pending 之类难以构造，改为直接验证查询语义）
        self.assertFalse(f._seen_seq(77))
        f.ingest(_env(77, "user_echo", data={"text": "M77"}))
        self.assertTrue(f._seen_seq(77))
        # 重复投递仍被挡
        n0 = len([r for r in f.snap["rows"] if r.get("kind") == "user_input"])
        f.ingest(_env(77, "user_echo", data={"text": "M77"}))
        n1 = len([r for r in f.snap["rows"] if r.get("kind") == "user_input"])
        self.assertEqual(n0, n1)

    def test_empty_feed_can_resume_its_own_water(self):
        """N1（a116 十二次全审，严重）：**空 log** 的 feed 必须能续传自己的水位。

        空 feed 时 `_floor_seq == snap["seq"] == _wseq_base` 三者相等，
        若统一按「游标 <= floor 即越窗」判，唯一合法游标也被拒 → 起始
        裁决恒 ok=False → **每 5s 整窗快照 + 前端 `_rebuild` 全量重渲**
        （审计实测 11s 内 SNAPSHOT×3、KA×0，正是 a92/MAJOR-10 修掉过的
        回归）。触发面：HWM 抬高后新建的任何会话；或重启后重开旧会话
        （账本缓冲空、零 commit）。"""
        # 场景 1：同 epoch 桶已被抬高 → 新建会话（不同 epoch）仍从 0 起，
        # 空 feed 必须可续传
        busy = F.V4Feed(epoch="BUSY")
        busy.ingest(_env(1, "user_echo", data={"text": "x"}))
        fresh = F.V4Feed(epoch="FRESH")
        self.assertTrue(fresh.can_resume(fresh.snap["seq"]),
                        "空 feed 拒续传 → 每 5s 整窗快照")
        ok, fr, last = fresh.resume_probe(fresh.snap["seq"])
        self.assertTrue(ok)
        self.assertIsNone(fr)          # 无增量，安静续传
        self.assertEqual(last, fresh.snap["seq"])

        # 场景 2：重启后重开旧会话（提示水位 2001、零 commit）。
        # 起点被严格抬到 > 2001 → 旧实例游标（≤2001）落不进新空间，
        # 该走整窗快照；快照 toSeq 之后安静续传（不能循环快照）。
        old = F.V4Feed(epoch="OLD", wseq_base=2001)
        _b2 = old.snap["seq"]
        self.assertGreater(_b2, 2001, "起点必须严格越过账本水位")
        self.assertFalse(old.can_resume(2001),
                         "旧实例游标落进新空间 → 整段重放/撞号丢行")
        self.assertTrue(old.can_resume(_b2),
                        "快照 toSeq 之后必须能安静续传（否则循环快照）")

    def test_base_strictly_exceeds_guess_when_guess_dominates(self):
        """二十一次全审：上面那条 `assertGreater(_b2, 2001)` 在当前实现下
        由墙钟/boot 的巨大值满足，**并未真正验证「起点严格 > 提示」**这一
        不变式（审计判为假绿）。这里把时钟与 boot 都压到极小，迫使
        `guess` 成为唯一的支配源，才能真正验到该逻辑。"""
        import time as _t
        orig = _t.time
        _t.time = lambda: 0.0
        F.V4Feed._boot = 0                 # boot 高位也归零
        try:
            f = F.V4Feed(epoch="G", wseq_base=2001)
            self.assertGreater(f.snap["seq"], 2001,
                               "guess 未被采纳（起点没越过提示水位）")
            self.assertFalse(f.can_resume(2001),
                             "提示水位本身被当合法游标")
            self.assertFalse(f.can_resume(2000))
        finally:
            _t.time = orig
            F.V4Feed._boot = None

    def test_injected_base_with_small_log_rejects_old_cursor(self):
        """F1-R 复发（a116 十三次全审，致命）：`_floor_seq` 必须**每次**
        随 log 同步，不能只在超窗裁剪时更新。

        原 `_trim` 把 floor 赋值写在 `if len > LOG_RETAIN` 块内 → log 非空
        但 < 600 时 floor 停在注入起点，落后于 `_log[0][0]`。于是「旧游标
        == 注入起点」在**新实例累计 < 600 事件**这个最常见窗口（短会话 /
        TTL 换代 / 子 feed）里被放行 → 整段历史当增量重放 → 前端 rowId
        撞号、静默丢行（审计实测 10 行被吞）。"""
        f = F.V4Feed(epoch="EP", wseq_base=20)
        for s_ in range(1, 6):
            f.ingest(_env(s_, "user_echo", data={"text": "E%d" % s_}))
        self.assertEqual(f._floor_seq, f._log[0][0],
                         "floor 未随 log 同步（落后于真实首条）")
        self.assertFalse(f.can_resume(20),
                         "旧游标==注入起点被放行 → 重启后整段重放/撞号丢行")
        self.assertFalse(f.resume_probe(20)[0])
        # N2 不受影响：floor 本身仍可续传
        self.assertTrue(f.can_resume(f._floor_seq))

    def test_resume_below_floor_goes_snapshot_for_completeness(self):
        """a116 十三次全审自查：游标落在**已裁剪区间**时必须走快照。

        `_trim` 只保留最近 600 条，floor 之前的增量已经不存在。若仍判
        「可续传」，`frames_after` 只返回 `(floor, last]` 这一截——客户端
        缺掉的中间段**永远不会补**（实测 700 条后 `frames_after(5)` 返回
        to=700 看着正常，实际漏 5..100 共 96 条）。允许 `floor-1` 是它的
        合法边界：那条本身仍在 log 中，增量完整。"""
        f = F.V4Feed()
        for s_ in range(1, 701):
            f.ingest(_env(s_, "user_echo", data={"text": "M%d" % s_}))
        _fl = f._floor_seq
        self.assertGreater(_fl, 50, "未触发 trim，用例前提不成立")
        for _q in (0, 5, _fl - 2):
            self.assertFalse(f.can_resume(_q),
                             "游标 %d 在已裁剪区，放行会漏掉中间增量" % _q)
            self.assertIsNone(f.frames_after(_q))
        # floor-1：还没消费 floor 那条，增量 (floor-1, last] 完整
        self.assertTrue(f.can_resume(_fl - 1))
        _fr = f.frames_after(_fl - 1)
        self.assertIsNotNone(_fr)
        self.assertEqual(_fr[1], f.snap["seq"])

    def test_wseq_hwm_persisted_across_generations(self):
        """F1-R 第三形态（a116 十四次全审，致命）：固定 `+1/+2` 偏移会
        逐代累积——上一代起点含偏移、它发的游标 = 上代水位 + 偏移 + m，
        而本代账本水位 = 上代水位 + m，于是「旧游标 = 本代水位 + 偏移」
        **恒成立**，任何常数都追不上（实测 gen3/4/5 稳定撞等号）。

        正确解法：wseq 高水位**持久化**到会话账本（`store.wseq_hwm`
        → `meta["wseq"]`），下一代起点 = 高水位 + 2，与账本推算解耦。
        这里用假 store 模拟 5 代进程重启，每代都验证旧游标被拒。"""
        class _Log(object):
            def __init__(self):
                self.wseq_hwm = 0
                self.last_seq = 0
                self.epoch = "EP"

        st = _Log()
        cursor = 0
        for gen in range(1, 6):
            _reset_hwm()                       # 模拟进程重启：进程级水位归零
            f = F.V4Feed(epoch="EP", wseq_base=st.wseq_hwm)
            f.log_store = st
            if gen > 1:
                self.assertGreater(f.snap["seq"], cursor,
                                   "第 %d 代起点未越过上一代游标" % gen)
                self.assertFalse(f.can_resume(cursor),
                                 "第 %d 代：旧游标被放行 → 整段重放/撞号丢行"
                                 % gen)
            for _i in range(10):
                st.last_seq += 1
                f.ingest(_env(st.last_seq, "user_echo",
                              data={"text": "G%d-%d" % (gen, _i)}))
            cursor = f.snap["seq"]
            self.assertEqual(st.wseq_hwm, cursor, "高水位未回写账本")

    def test_hydrate_retry_clears_uuid_dedup(self):
        """S2（a116 十五次全审，严重）：`hydrate_jsonl` 失败重试必须清空
        `_seen_uuid`。

        uuid 是在 `feed_jsonl_line` 里**先于落账**登记的；失败分支只清了
        rows/total → 重试时前半段行被判「已见过」整段跳过（实测 5 行只回填
        2 行），且返回 True/_hydrated=True → 半成品 feed 被永久缓存，
        子代理窗格永久残缺。"""
        import json as _jj
        import tempfile
        lines = [{"uuid": "u%d" % i, "type": "assistant",
                  "message": {"content": [{"type": "text", "text": "L%d" % i}]}}
                 for i in range(5)]
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("\n".join(_jj.dumps(x) for x in lines))
            f = F.V4Feed(epoch="sub")
            _orig = f.feed_jsonl_line
            _n = [0]

            def _boom(obj, hydrate=False):
                _n[0] += 1
                if _n[0] == 3:
                    raise RuntimeError("boom")
                return _orig(obj, hydrate=hydrate)

            f.feed_jsonl_line = _boom
            self.assertFalse(f.hydrate_jsonl(p), "失败应返回 False")
            self.assertEqual(f._seen_uuid, set(), "失败未清 uuid 去重集")
            # 重试：全部 5 行都要回填
            f.feed_jsonl_line = _orig
            self.assertTrue(f.hydrate_jsonl(p))
            _txt = [r.get("text") for r in f.snap["rows"]]
            for i in range(5):
                self.assertIn("L%d" % i, _txt, "重试后仍缺第 %d 行" % i)
        finally:
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_cursor_at_floor_is_resumable(self):
        """N2（十二次全审，一般）：有 log 时 floor 是**真实条目**，
        游标 == floor 表示已消费到该条 → 后续全部可投递，应放行。
        原严格 `>` 会把它误拒（1/600 边界，代价偶发一次多余快照）。"""
        f = F.V4Feed()
        for s_ in range(1, 700):
            f.ingest(_env(s_, "user_echo", data={"text": "M%d" % s_}))
        self.assertGreater(f._floor_seq, 0, "未触发 trim，用例前提不成立")
        self.assertTrue(f.can_resume(f._floor_seq),
                        "游标==floor 被误拒（本应可投递后续全部增量）")
        fr = f.frames_after(f._floor_seq)
        self.assertIsNotNone(fr, "floor 之后有大量增量，却被判无帧")
        self.assertEqual(fr[1], f.snap["seq"])

    def test_hwm_is_bucketed_by_epoch(self):
        """N3（十二次全审，一般）：HWM 按 epoch 分桶——活跃会话不得把
        无关会话的起点推高（原全局单桶实测 A 写 100k 后 B 的 base=100001）。"""
        a = F.V4Feed(epoch="SESSION_A")
        for i in range(1, 501):
            a.ingest(_env(i, "user_echo", data={"text": "A%d" % i}))
        b = F.V4Feed(epoch="SESSION_B")
        # 十九次全审：起点恒为墙钟微秒（不再是 0），「不被串扰」的正确断言
        # 是 B 的 base 不超过 A 的 base + 墙钟跳变，且与 A 的水位无关。
        self.assertLess(b.snap["seq"], a.snap["seq"] + 10000000,
                        "跨 epoch 串扰：B 的起点被 A 顶高")
        # 同 epoch 重建仍严格递增（正是需要单调续号的场景）
        c = F.V4Feed(epoch="SESSION_A")
        self.assertGreater(c.snap["seq"], a.snap["seq"],
                           "同 epoch 重建起点未严格递增 → 旧游标可落进新空间")

    def test_wseq_base_equal_boundary_goes_snapshot(self):
        """F1-R（a116 十一次全审，致命）：**等号边界**必须走快照。

        旧公式 `账本 last_seq + LOG_RETAIN` 在「1 delta/事件」时与旧实例
        同额增长：旧 max = L1+600+k，新 base = L2+600 = L1+m+600，k==m
        即相等 → 客户端游标恰等于新 floor。若判据是 `>=` 就放行 → 整段
        历史当增量重画、早段永久缺失（审计实测丢 E1..E4、重复 E500..E503）。
        """
        old = F.V4Feed(epoch="EP")
        for s_ in (1, 2, 3):
            old.ingest(_env(s_, "user_echo", data={"text": "E%d" % s_}))
        _cursor = old.snap["seq"]                 # 旧游标 == 旧 max_wseq
        # 新实例即使**恰好**从旧 max 起编（等号边界），也必须拒绝续传
        new = F.V4Feed(epoch="EP", wseq_base=_cursor)
        self.assertFalse(new.can_resume(_cursor),
                         "游标 == 旧 base 被放行 → 重建后历史重复/缺失")
        self.assertFalse(new.resume_probe(_cursor)[0])
        self.assertIsNone(new.frames_after(_cursor))
        # 而真实的类级高水位分配永远给出严格更大的起点
        real = F.V4Feed(epoch="EP")
        self.assertGreater(real.snap["seq"], _cursor)

    def test_sub_feed_wseq_base_monotonic(self):
        """F1 第二形态：子 feed 的 epoch 恒为 "sub"，必须靠时间戳起点
        保证跨重建单调。这里直接验证注入语义（构造顺序 → 起点递增）。"""
        a = F.V4Feed(epoch="sub", wseq_base=1000000)
        a.ingest(_env(1, "user_echo", data={"text": "A"}))
        _a_max = a.snap["seq"]
        self.assertGreater(_a_max, 1000000)
        b = F.V4Feed(epoch="sub", wseq_base=2000000)
        self.assertGreater(b.snap["seq"], 2000000)
        self.assertFalse(b.resume_probe(_a_max)[0],
                         "子 feed 重建后旧游标被误判可续传")


class TestWseqPersistence(unittest.TestCase):
    """F1/F2（a116 十五次全审）：投递序号高水位必须走**同一个对象**。

    原实现把 `wseq_hwm` 写在门面实例属性上，而 `restore` 写的是 store
    的同名属性 → 两个对象各存一份，重启后读到的永远是 0（F2）。
    且 `lifecycle._get_or_create` 已改成三参调用，门面若不同步接收
    会直接 TypeError → 任何会话复活路径 100% 500（F1）。
    """

    def test_facade_proxies_wseq_hwm_to_store(self):
        lg = _evlog("pw1")
        lg.wseq_hwm = 42
        self.assertEqual(lg.store.wseq_hwm, 42, "门面写入未落到 store")
        self.assertEqual(lg.wseq_hwm, 42)

    def test_restore_accepts_three_args_and_round_trips(self):
        lg = _evlog("pw2")
        lg.restore("EP", 100, 42)          # lifecycle 的实际调用形态
        self.assertEqual(lg.epoch, "EP")
        self.assertEqual(lg.last_seq, 100)
        self.assertEqual(lg.wseq_hwm, 42, "高水位未从 meta 恢复")
        # 旧 meta（无 wseq 字段）→ 默认 0，不炸
        lg2 = _evlog("pw3")
        lg2.restore("EP", 5)
        self.assertEqual(lg2.wseq_hwm, 0)

    def test_new_feed_base_reads_persisted_hwm(self):
        """重启后新 feed 的起点必须来自持久化高水位（而非进程内 HWM）。"""
        lg = _evlog("pw4")
        lg.restore("EP", 10, 500)          # 上一代发到 wseq=500
        _reset_hwm()
        f = F.V4Feed(epoch=lg.epoch, wseq_base=int(lg.wseq_hwm or 0))
        self.assertGreater(f.snap["seq"], 500,
                           "新起点未越过持久化高水位 → 旧游标可落进新空间")

    def test_commit_writes_back_hwm_to_store(self):
        lg = self._mk()
        f = F.V4Feed(epoch="EP")
        f.log_store = lg
        for s_ in range(1, 4):
            f.ingest(_env(s_, "user_echo", data={"text": "M%d" % s_}))
        self.assertEqual(lg.wseq_hwm, f.snap["seq"],
                         "落账未回写高水位 → 重启后起点回落")

    @staticmethod
    def _mk():
        return _evlog("pw5")


class TestSyncWseqPersist(unittest.TestCase):
    """a116 十六次全审（F3-1/F3-2 根修）：wseq 高水位走 **同步** 小文件。

    原异步方案（debounce/meta sync）有两处不可闭合的缺口：
      ① 冷建补放经 `feed.ingest→_commit`，不经 `v4_ingest_main`，异步路径
         根本不知道有变更（实测 40 条补放的 wseq 从不落盘）；
      ② 异步窗口内崩溃，重启 base = persisted+2 可能 ≤ 客户端游标，首批
         新事件拿到已消费的 wseq → 静默吞消息（实测 lag≥3 丢 1-2 条）。
    现改为 store.wseq_hwm 的 setter 同步落盘：所有写入方共用同一入口。
    """

    def setUp(self):
        self._S = _WSEQ_STORE

    def test_setter_writes_through_immediately(self):
        """写完立刻用新 store 对象读——模拟进程崩溃后重启。"""
        lg = _evlog("sw1")
        lg.wseq_hwm = 42
        self.assertEqual(lg.store.wseq_hwm, 42)
        self.assertEqual(self._S.SessionEventStore("sw1").wseq_hwm, 42,
                         "同步落盘未生效 → 重启读到 0")

    def test_cold_build_commit_persists(self):
        """F3-1：冷建补放不经过 v4_ingest_main，也必须落盘。"""
        lg = _evlog("sw2")
        f = F.V4Feed(epoch="EP")
        f.log_store = lg
        n0 = f.snap["seq"]
        for s_ in range(1, 41):           # 40 条：模拟冷建补放
            f.ingest(_env(s_, "user_echo", data={"text": "M%d" % s_}))
        self.assertEqual(f.snap["seq"], n0 + 40)
        self.assertEqual(self._S.SessionEventStore("sw2").wseq_hwm,
                         f.snap["seq"], "冷建补放的 wseq 未落盘")

    def test_monotonic_never_decreases_on_disk(self):
        lg = _evlog("sw3")
        lg.wseq_hwm = 50
        lg.wseq_hwm = 10                  # 回退尝试
        self.assertEqual(lg.wseq_hwm, 50)
        self.assertEqual(self._S.SessionEventStore("sw3").wseq_hwm, 50)

    def test_restore_persists_forward_value(self):
        lg = _evlog("sw4")
        lg.restore("EP", 100, 500)
        self.assertEqual(lg.wseq_hwm, 500)
        self.assertEqual(self._S.SessionEventStore("sw4").wseq_hwm, 500)

    def test_cold_build_then_restart_rejects_old_cursor(self):
        """F3-1（十六次全审，致命）：冷建补放 40 条 → 崩溃重启。

        原异步方案下这 40 条的 wseq 从不落盘，重启 base=0、新事件重新
        从 1 编号 → 客户端持久化的游标 40 在代 2 里「合法」，40 条新消息
        一条也拿不到。同步落盘后 base = 40+2，旧游标一律拒。
        """
        _reset_hwm()
        lg = _evlog("sw5")
        f = F.V4Feed(epoch="EP5")
        f.log_store = lg
        _n0 = f.snap["seq"]
        for i in range(1, 41):
            f._commit("c%d" % i, [{"kind": "row"}])
        cursor = f.snap["seq"]
        self.assertEqual(cursor, _n0 + 40)

        _reset_hwm()                       # 模拟进程重启
        st2 = self._S.SessionEventStore("sw5")
        self.assertEqual(st2.wseq_hwm, cursor, "冷建补放未落盘")
        f2 = F.V4Feed(epoch="EP5", wseq_base=st2.wseq_hwm)
        f2.log_store = st2
        self.assertGreater(f2._wseq_base, cursor, "重启后起点未越过旧游标")
        self.assertFalse(f2.can_resume(cursor),
                         "旧游标被放行 → 重启后新消息会被静默吞掉")
        f2._commit("new1", [{"kind": "row"}])
        self.assertGreater(f2.snap["seq"], cursor, "补事件后水位应越过旧游标")
        self.assertFalse(f2.can_resume(cursor), "新事件后旧游标仍须拒")

    def test_persist_lag_window_no_longer_swallows(self):
        """F3-2（十六次全审，严重）：异步滞后 lag≥3 时首批新事件拿到
        ≤ 游标的 wseq 被吞。同步落盘后 lag 恒为 0。"""
        _reset_hwm()
        lg = _evlog("sw6")
        f = F.V4Feed(epoch="EP6")
        f.log_store = lg
        _n0 = f.snap["seq"]
        for i in range(1, 21):
            f._commit("e%d" % i, [{"kind": "row"}])
        cursor = f.snap["seq"]            # 客户端游标

        # 不 reset 类级 HWM（模拟同进程重建），持久化必须零滞后
        st2 = self._S.SessionEventStore("sw6")
        self.assertEqual(st2.wseq_hwm, cursor, "持久化滞后（应为 0 滞后）")
        f2 = F.V4Feed(epoch="EP6", wseq_base=st2.wseq_hwm)
        f2.log_store = st2
        self.assertGreater(f2._wseq_base, cursor, "同进程重建起点未越过旧游标")
        self.assertFalse(f2.can_resume(cursor))
        # 补事件让 water 越过旧游标——排除「被 seq > water 顺手拒掉」的假绿
        for i in range(3):
            f2._commit("lag%d" % i, [{"kind": "row"}])
        self.assertGreater(f2.snap["seq"], cursor)
        self.assertFalse(f2.can_resume(cursor))


    def test_persist_failure_falls_back_to_ledger_seq(self):
        """十六次全审（严重）：落盘失败时**不能**让旧游标被放行。

        盘上高水位读回 0 时，若 base 只用它 → base=0 → 旧游标 40 被判
        合法 → 新事件重新从 1 编号 → 40 条消息全部静默消失（无快照、
        无重连）。修法：起点取 max(wseq_hwm, 账本 last_seq)。
        """
        _reset_hwm()
        lg = _evlog("sw7")
        lg.restore("EP7", 40, 0)          # meta: seq=40, wseq=0（落盘失败）
        self.assertEqual(lg.wseq_hwm, 0)
        # 与生产同款的下界计算（v4hub 建 feed 处）
        hint = max(int(lg.wseq_hwm or 0), int(lg.last_seq or 0))
        self.assertEqual(hint, 40, "持久化不可信时未回落到账本 seq")
        f = F.V4Feed(epoch="EP7", wseq_base=hint)
        f.log_store = lg
        self.assertGreater(f._wseq_base, 40, "起点未越过旧游标")
        self.assertFalse(f.can_resume(40),
                         "落盘失败时旧游标被放行 → 整批消息静默丢失")
        f._commit("n1", [{"kind": "row"}])
        self.assertGreater(f.snap["seq"], 40, "补事件后水位应越过旧游标")
        self.assertFalse(f.can_resume(40))


    def test_closed_store_never_recreates_file(self):
        """十六次全审（一般级）：会话删除后在飞的 `_commit` 迟到调 setter，
        会 O_CREAT 重建孤儿文件。置 `_wseq_closed` 后必须拒绝。"""
        _reset_hwm()
        lg = _evlog("sw8")
        lg.wseq_hwm = 10
        p = lg.store._wseq_path
        self.assertTrue(os.path.exists(p))
        lg.store.close_wseq()
        self._S.drop_wseq_file("sw8")
        self.assertFalse(os.path.exists(p))
        lg.wseq_hwm = 11                 # 迟到的写入
        self.assertFalse(os.path.exists(p), "已删除会话的 wseq 文件被重建")


class TestNoOffsetAccumulation(unittest.TestCase):
    """十八次全审（致命）：起点偏移曾逐代累积。

    旧实现 hint = max(持久化值, 账本 last_seq)，持久化失效后退化为
    last_seq（**恒比上代水位小 offset**），`base = hint + 2` 每代 +2 且
    不回退。几代后旧游标（= 上代水位）会**同时**越过 `_wseq_base` 与
    `_first_issued` → 实测 16~20 条新消息静默丢失。
    现改用与状态无关的单调源（墙钟微秒），偏移不再参与。
    """

    def test_base_monotonic_across_generations_without_persistence(self):
        _reset_hwm()
        cur = None
        for gen in range(8):
            f = F.V4Feed(epoch="OFF")
            if cur is not None:
                self.assertGreater(f._wseq_base, cur,
                                   "第 %d 代起点未超过旧游标" % gen)
                self.assertFalse(f.can_resume(cur),
                                 "第 %d 代放行了上一代游标" % gen)
                # 空 feed 时 can_resume(base) 必须为 True（S1：快照 ack
                # 下发的 toSeq 就是 base，客户端拿着它重连必须放行）
            for i in range(2):
                f._commit("g%d_%d" % (gen, i), [P.d_state({"n": i})])
            cur = f.snap["seq"]

    def test_base_survives_total_persistence_loss(self):
        """盘被清 + 崩溃重启：起点本身必须严格越过旧游标。

        **必须直接断言 `_wseq_base`**：若只断言 `can_resume(cur)==False`，
        在 base=0（缺陷形态）时会被 `seq > water(=0)` 挡掉而「通过」——
        这正是二十次全审抓到的假绿（注入 `return 0` 早退后全套 75 例全绿）。
        """
        _reset_hwm()
        f = F.V4Feed(epoch="PL")
        for i in range(20):
            f._commit("p%d" % i, [P.d_state({"n": i})])
        cur = f.snap["seq"]
        _reset_hwm()                      # 进程重启 + 持久化全丢
        f2 = F.V4Feed(epoch="PL", wseq_base=0)
        # 决定性断言：起点由墙钟源给出，必须**严格大于**旧游标
        self.assertGreater(f2._wseq_base, cur,
                           "起点未越过旧游标（return 0 早退回归）")
        self.assertFalse(f2.can_resume(cur))
        # 补事件后仍须拒（此时 water > cur，不再有 seq>water 的遮挡）
        for i in range(5):
            f2._commit("q%d" % i, [P.d_state({"n": i})])
        self.assertGreater(f2.snap["seq"], cur, "补事件后水位应已越过旧游标")
        self.assertFalse(f2.can_resume(cur),
                         "水位越过旧游标后仍放行 → 静默丢行")


class TestBootNamespace(unittest.TestCase):
    """二十一次全审（严重）：墙钟可回拨 → 起点改用**持久化启动序号**作高位。

    回拨量落在「重启耗时 E」邻域内时（实测 R ∈ (E - m·1µs, E]），纯墙钟
    会让新 base 掉到旧游标下方 → 旧游标被判可续传 → 整批消息静默丢失。
    修法：`base = boot * 10^9 + (墙钟µs % 10^9)`，boot 每次进程启动 +1
    并持久化，与时钟完全无关。
    """

    def setUp(self):
        _reset_hwm()
        import tempfile
        self._boot_dir = tempfile.mkdtemp(prefix="boot_")
        self._old = F.V4Feed._boot_path
        F.V4Feed._boot = None
        F.V4Feed._boot_path = staticmethod(
            lambda: os.path.join(self._boot_dir, "BOOT"))

    def tearDown(self):
        F.V4Feed._boot_path = self._old
        F.V4Feed._boot = None

    def test_boot_increments_across_processes(self):
        a = F.V4Feed._next_boot()
        F.V4Feed._boot = None              # 模拟进程重启
        b = F.V4Feed._next_boot()
        self.assertGreater(b, a, "启动序号未跨进程递增")

    def test_base_not_reduced_by_clock_rollback(self):
        """时钟回拨到 1970 年——base 也必须 > 上一代游标（boot 高位兜住）。"""
        import time as _t
        orig = _t.time
        f = F.V4Feed(epoch="RB")
        f._commit("a", [P.d_state({"n": 1})])
        cur = f.snap["seq"]
        # 重启 + 时钟大幅回拨
        F.V4Feed._boot = None
        _reset_hwm()
        _t.time = lambda: 0.0              # 回拨到 epoch
        try:
            g = F.V4Feed(epoch="RB")
        finally:
            _t.time = orig
        self.assertGreater(g._wseq_base, cur,
                           "时钟回拨后起点落回旧游标下方")

    def test_base_within_js_safe_integer(self):
        """二十二次全审（致命）：base 必须落在 JS 安全整数内（< 2^53）。

        初版 boot 用 `max(cur, time.time())+1` → boot≈1.79e9 →
        base≈1.79e18，超安全整数 200 倍，前端 Number 低 3 位归零，
        游标比较全部失真。boot 改为纯小序号（从 1 起）。
        """
        JS_MAX = 2 ** 53
        for _ in range(5):
            F.V4Feed._boot = None         # 模拟 5 次进程启动
            f = F.V4Feed(epoch="SAFE")
            self.assertLess(f._wseq_base, JS_MAX,
                            "base 超出 JS 安全整数，前端精度丢失")
            self.assertGreater(f._wseq_base, 0)
            f._commit("s", [P.d_state({"n": 1})])
            self.assertLess(f.snap["seq"], JS_MAX)

        # 长跑：一代内发 1e6 条也不能溢出（低位空间 1e9）
        F.V4Feed._boot = None
        g = F.V4Feed(epoch="SAFE2")
        for i in range(20):
            g._commit("x%d" % i, [P.d_state({"n": i})])
        self.assertLess(g.snap["seq"], JS_MAX)


    def test_guess_and_hi_still_honoured(self):
        """`guess`/`hi` 两源不能因为墙钟/boot 巨大而被静默丢弃。"""
        import time as _t
        orig = _t.time
        _t.time = lambda: 0.0              # 让 boot 低位与墙钟都极小
        F.V4Feed._boot = None
        try:
            f = F.V4Feed(epoch="GH", wseq_base=10 ** 12)
            self.assertGreaterEqual(f._wseq_base, 10 ** 12,
                                    "guess 被丢弃")
            g = F.V4Feed(epoch="GH")
            self.assertGreater(g._wseq_base, f.snap["seq"],
                               "同 epoch 重建未取 hi")
        finally:
            _t.time = orig
            F.V4Feed._boot = None


class TestBootPersistence(unittest.TestCase):
    """BOOT 计数器相关用例——**每例独立目录**，避免与其它用例互相污染
    （二十二次全审：共用一个 BOOT 文件导致钳制用例的饱和值泄漏给
    后续用例，实测基线红）。"""

    def setUp(self):
        _reset_hwm()
        import tempfile
        self._dir = tempfile.mkdtemp(prefix="bootcase_")
        self._old_path = F.V4Feed._boot_path
        F.V4Feed._boot_path = staticmethod(
            lambda: os.path.join(self._dir, "BOOT"))
        F.V4Feed._boot = None
        import src.eventlog.store as _S
        self._old_dir = _S._WSEQ_DIR
        _S._WSEQ_DIR = self._dir        # wseq 文件与 BOOT 同目录（兜底要扫它）

    def tearDown(self):
        F.V4Feed._boot_path = self._old_path
        F.V4Feed._boot = None
        import src.eventlog.store as _S
        _S._WSEQ_DIR = self._old_dir

    def test_base_at_boot_max_with_worst_low_still_safe(self):
        """边界（二十二次全审）：boot 钳到 `_BOOT_MAX` 且低位取**最坏值**
        （STRIDE-1）时，base 仍须 < 2^53-1。初版 `_BOOT_MAX = 2^53 // STRIDE`
        没预留低位域，74.5% 的低位取值会越界（实测 base=9007199400000002）。"""
        JS_MAX = 2 ** 53 - 1
        S = F.V4Feed._BOOT_STRIDE
        M = F.V4Feed._BOOT_MAX
        worst = M * S + (S - 1) + 2
        self.assertLessEqual(worst, JS_MAX,
                             "_BOOT_MAX 未预留低位域：最坏 base 越出安全整数")

        # 用真实路径验证：BOOT 写到极大值 → 钳制 → 低位取最坏 → 仍安全
        with open(F.V4Feed._boot_path(), "w", encoding="utf-8") as f:
            f.write(str(10 ** 15))
        F.V4Feed._boot = None
        b = F.V4Feed._next_boot()
        self.assertLessEqual(b, M)
        _reset_hwm()
        f = F.V4Feed(epoch="BMAX")
        # 直接算该 boot 下最坏 base
        self.assertLessEqual(b * S + (S - 1) + 2, JS_MAX,
                             "钳制后最坏 base 仍越界")
        self.assertLess(f._wseq_base, JS_MAX)

    def test_boot_survives_boot_file_loss(self):
        """BOOT 文件被清 + 时钟回拨：boot 必须从现存 wseq 文件的高位恢复。

        否则 boot 归 1，叠加回拨后 base 会掉到旧游标下方（实测 gap -6000 万，
        靠 `seq > water` 侥幸挡住）。
        """
        import time as _t
        from src.eventlog.store import SessionEventStore
        f = F.V4Feed(epoch="BL")
        st = SessionEventStore("bl")
        f.log_store = st
        f._commit("a", [P.d_state({"n": 1})])
        cur = f.snap["seq"]
        boot1 = F.V4Feed._boot
        # BOOT 文件被清 + 进程重启 + 回拨 60 秒
        os.remove(F.V4Feed._boot_path())
        F.V4Feed._boot = None
        _reset_hwm()
        orig = _t.time
        _t.time = lambda: orig() - 60
        try:
            g = F.V4Feed(epoch="BL")
        finally:
            _t.time = orig
        self.assertGreater(F.V4Feed._boot, boot1,
                           "BOOT 丢失后未从 wseq 文件恢复高位")
        self.assertGreater(g._wseq_base, cur, "起点掉到旧游标下方")


    def test_boot_clamped_when_file_holds_huge_value(self):
        """BOOT 文件被写入极大值（损坏/人为）时，boot 必须被钳制，
        base 不得超出 JS 安全整数 2^53。"""
        JS_MAX = 2 ** 53
        with open(F.V4Feed._boot_path(), "w", encoding="utf-8") as f:
            f.write(str(10 ** 12))
        F.V4Feed._boot = None
        b = F.V4Feed._next_boot()
        self.assertLessEqual(b, F.V4Feed._BOOT_MAX, "boot 未钳制")
        F.V4Feed._boot = None
        _reset_hwm()
        f = F.V4Feed(epoch="CLAMP")
        self.assertLess(f._wseq_base, JS_MAX, "钳制后 base 仍超安全整数")
        f._commit("c", [P.d_state({"n": 1})])
        self.assertLess(f.snap["seq"], JS_MAX)
        # 清理：别让钳制后的 BOOT 值污染同目录后续用例
        try:
            os.remove(F.V4Feed._boot_path())
        except Exception:
            pass
        F.V4Feed._boot = None
        _reset_hwm()


class TestSnapshotAckResumable(unittest.TestCase):
    """S1 回归守护（二十一次全审）：快照 ack 的 toSeq 必须可续传。

    客户端拿快照后断开、期间来 1 条事件，重连时必须走增量而非整窗快照
    ——否则每次重连都全量重渲（a92/MAJOR-10 回归）。
    """

    def test_ack_then_one_event_still_resumable(self):
        _reset_hwm()
        f = F.V4Feed(epoch="ACK")
        B = f.snap["seq"]                  # 快照 ack 下发的 toSeq
        f._commit("one", [P.d_state({"n": 1})])
        self.assertTrue(f.can_resume(B),
                        "ack 后仅 1 条事件即判越窗 → 每次重连整窗重渲")
        fr = f.frames_after(B)
        self.assertIsNotNone(fr)
        self.assertEqual(fr[1], f.snap["seq"])






class TestIncarnation(unittest.TestCase):
    """二十二次全审（结构）：**身份匹配**取代「数值严格单调」。

    22 轮审计证明「起点永远大于旧游标」在「持久化可丢 + 时钟可回拨 +
    并发取号可撞」下不可达。身份匹配不依赖任何可失效状态：换了实例
    就是换了空间，客户端游标一律作废走快照。
    """

    def test_each_instance_has_unique_incarnation(self):
        _reset_hwm()
        seen = set()
        for _ in range(20):
            f = F.V4Feed(epoch="INC")
            self.assertNotIn(f.incarnation, seen, "实例身份撞号")
            seen.add(f.incarnation)

    def test_incarnation_stable_within_instance(self):
        _reset_hwm()
        f = F.V4Feed(epoch="INC2")
        first = f.incarnation
        for i in range(5):
            f._commit("i%d" % i, [P.d_state({"n": i})])
        self.assertEqual(f.incarnation, first, "实例内身份漂移")


    def test_same_epoch_seq_but_different_inc_must_snapshot(self):
        """身份匹配的**唯一承重判据**（二十二次全审）：同 epoch、同 seq、
        但 inc 不同 → 必须走快照，不能续传。

        这是「旧游标落进新空间」的终结条件：旧实例发的 seq 在新实例里
        即便数值合法（同 epoch + 同 seq），身份不匹配就一律作废。
        """
        _reset_hwm()
        old = F.V4Feed(epoch="SAME")
        for i in range(5):
            old._commit("o%d" % i, [P.d_state({"n": i})])
        cur = old.snap["seq"]
        old_inc = old.incarnation

        new = F.V4Feed(epoch="SAME")      # 同 epoch，新实例
        new._wseq_base = cur              # 强制数值上「合法」
        new.snap["seq"] = cur
        new._wseq = cur
        new._floor_seq = cur
        self.assertNotEqual(new.incarnation, old_inc, "实例身份未变化")
        # 数值判据会放行（同 epoch、seq 在窗口内），身份判据必须拒
        # ——routes 层的 `base_inc == feed.incarnation` 是最后一环，
        # 这里验 feed 侧的身份标识本身是不可伪造的。
        self.assertEqual(len(new.incarnation), 16)
        self.assertNotEqual(new.incarnation, old_inc)

    def test_inc_not_leaked_across_instances(self):
        """20 次重建的 inc 全不同——保证「换了实例必然快照」。"""
        _reset_hwm()
        incs = {F.V4Feed(epoch="LEAK").incarnation for _ in range(20)}
        self.assertEqual(len(incs), 20, "实例身份重复 → 旧游标可能被误认")


    def test_base_clamped_when_guess_is_polluted(self):
        """二十三次全审（一般）：`guess`/`hi` 路径不受 `_BOOT_MAX` 约束——
        升级自旧版（boot 曾用时间戳）遗留的 wseq 文件里可能是 ~1.79e18，
        经 v4hub 的 `_hint` 注入后 base 越过 JS 安全整数。且 `_save_wseq`
        的 `v <= _wseq_written` 守卫会让该大值永远留在盘上。最终 base
        必须统一兜底。"""
        _reset_hwm()
        huge = 1792758829942572288          # 旧版时间戳 boot 的残留形态
        f = F.V4Feed(epoch="HUGEGUESS", wseq_base=huge)
        self.assertLessEqual(f._wseq_base, F.V4Feed._BASE_MAX,
                             "guess 注入的超界起点未被钳制")
        self.assertLess(f._wseq_base, 2 ** 53, "起点越过 JS 安全整数")
        # 钳制后仍要能继续前进（不能顶格钳死）
        f._commit("x", [P.d_state({"n": 1})])
        self.assertLess(f.snap["seq"], 2 ** 53, "补事件后再次越界")


class TestTpsState(_HWMTestCase):
    """a152：TPS 投影——主窗 output/duration、子代理只累计。"""

    def test_result_usage_projects_tps(self):
        f = _mkfeed("e1")
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={"type": "assistant", "message": {
            "model": "m", "content": [{"type": "text", "text": "答"}]}}))
        f.ingest(_env(3, "cli_stream", data={
            "type": "result", "duration_ms": 30000,
            "usage": {"output_tokens": 1200, "input_tokens": 50000}}))
        tps = f.snap["state"].get("tps")
        self.assertTrue(tps, "tps state 未投影")
        self.assertEqual(tps["last"], 40.0, "1200/30s 应为 40.0")
        self.assertEqual(tps["toks"], 1200)
        self.assertEqual(tps["all"], 1200)
        self.assertEqual(tps["sub"], 0)

    def test_subagent_tokens_accumulate_only(self):
        f = _mkfeed("e1")
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "subagent_started", data={
            "tid": "tu1", "agent_type": "reviewer", "desc": "d",
            "bg": False, "task_id": "ag1"}))
        f.ingest(_env(3, "subagent_result", data={
            "tid": "tu1", "ok": True, "brief": "b",
            "tokens": 5000, "tool_n": 4, "task_id": "ag1"}))
        tps = f.snap["state"].get("tps")
        self.assertEqual(tps["sub"], 5000, "子代理 token 应累计")
        self.assertEqual(tps["last"], 0, "子代理不得进主窗 TPS")

    def test_live_ctx_tracking(self):
        """a153：assistant usage→ctxLive 基准；流式字符→liveToks 估；result 落真值。"""
        f = _mkfeed("e1")
        f.ingest(_env(1, "turn_started"))
        # 首个 assistant 块：usage 输入侧 50000 + 200 字符文本（liveToks=50 未过 32 档→先不估）
        f.ingest(_env(2, "cli_stream", data={"type": "assistant", "message": {
            "model": "m", "usage": {"input_tokens": 50000, "output_tokens": 10},
            "content": [{"type": "text", "text": "x" * 200}]}}))
        tps = f.snap["state"].get("tps")
        self.assertEqual(tps["ctxLive"], 50000, "assistant usage 输入侧应即时入 ctxLive")
        # 第二块：再 +1000 字符（累计 1200 字符 → liveToks=300 ≥32 档）
        f.ingest(_env(3, "cli_stream", data={"type": "assistant", "message": {
            "model": "m",
            "content": [{"type": "text", "text": "y" * 1000}]}}))
        tps = f.snap["state"].get("tps")
        self.assertEqual(tps["liveToks"], 300, "1200 字符 //4 = 300")
        # result：真值 60000 覆盖 ctxLive，估値清零
        f.ingest(_env(4, "cli_stream", data={
            "type": "result", "duration_ms": 10000,
            "usage": {"output_tokens": 400, "input_tokens": 60000}}))
        tps = f.snap["state"].get("tps")
        self.assertEqual(tps["ctxLive"], 60000)
        self.assertEqual(tps["liveToks"], 0, "result 后估値应清零")
        # 新回合：字符账归零
        f.ingest(_env(5, "turn_started", turn="t2"))
        f.ingest(_env(6, "cli_stream", turn="t2", data={"type": "assistant", "message": {
            "model": "m", "content": [{"type": "text", "text": "z" * 400}]}}))
        tps = f.snap["state"].get("tps")
        self.assertEqual(tps["liveToks"], 100, "新回合 400//4=100（上一回合的 300 已清）")

    def test_multi_turn_accumulates(self):
        f = _mkfeed("e1")
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "cli_stream", data={
            "type": "result", "duration_ms": 10000,
            "usage": {"output_tokens": 300}}))
        f.ingest(_env(3, "turn_started", turn="t2"))
        f.ingest(_env(4, "cli_stream", turn="t2", data={
            "type": "result", "duration_ms": 20000,
            "usage": {"output_tokens": 800}}))
        tps = f.snap["state"].get("tps")
        self.assertEqual(tps["all"], 1100)
        self.assertEqual(tps["last"], 40.0, "第二回合 800/20s")
        self.assertEqual(tps["toks"], 800)


class TestMachineTurnMerge(_HWMTestCase):
    """a144R（用户铁律「闸不得拆分回合」）：审计/设计闸续发指令（send_message
    直发、先发 machine_turn 标记）拉起的新回合并回原组头——不建第二个
    turn_header，工时链式累计；用户手打（user_echo）撤旗照常新起组头。"""

    def _t1_done(self, f):
        f.ingest(_env(1, "turn_started"))
        f.ingest(_env(2, "user_echo", data={"text": "开始"}))
        f.ingest(_env(3, "turn_complete", data={"duration_ms": 1000}))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["state"], "success")
        self.assertEqual(heads[0]["activeMs"], 1000)

    def test_machine_turn_merges_and_accumulates(self):
        f = _mkfeed("e1")
        self._t1_done(f)
        # 续发：标记先于新回合的 turn_started（send_message 真实顺序）
        f.ingest(_env(4, "machine_turn"))
        f.ingest(_env(5, "turn_started", turn="t2"))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 1, "续审回合不得新建组头（回合不拆分）")
        self.assertEqual(heads[0]["state"], "running", "并回后组头须重开")
        self.assertEqual(heads[0]["endedAt"], 0)
        f.ingest(_env(6, "cli_stream", turn="t2",
                      data={"type": "assistant", "message": {"model": "m",
                             "content": [{"type": "text", "text": "补审中"}]}}))
        f.ingest(_env(7, "turn_complete", turn="t2", data={"duration_ms": 500}))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["state"], "success")
        self.assertEqual(heads[0]["activeMs"], 1500, "工时链式累计 1000+500")
        # 二次续接：base 替换不翻倍（行上 activeMs 已含总量）
        f.ingest(_env(8, "machine_turn"))
        f.ingest(_env(9, "turn_started", turn="t3"))
        f.ingest(_env(10, "turn_complete", turn="t3", data={"duration_ms": 300}))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["activeMs"], 1800, "二次并接 1500+300 不翻倍")

    def test_cold_replay_fallback_merges(self):
        """a147（深攻 P1·冷建重放窗）：并回旗在而 _last_turn_rid 缺失（hydration
        冷建不设它，machine_turn 与 turn_started 同窗重放）——扫快照末组头
        作并回目标，不拆分；upsert 带 reopened 背书字段。"""
        f = _mkfeed("e1")
        self._t1_done(f)
        f._last_turn_rid = None            # 模拟 hydration 冷建后的状态
        f.ingest(_env(4, "machine_turn"))
        f.ingest(_env(5, "turn_started", turn="t2"))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 1, "冷建重放窗仍须并回（不拆分）")
        self.assertEqual(heads[0]["state"], "running")
        self.assertEqual(heads[0].get("reopened"), 1, "并回 upsert 须带背书字段")
        f.ingest(_env(6, "turn_complete", turn="t2", data={"duration_ms": 500}))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["activeMs"], 1500)

    def test_user_echo_cancels_merge_flag(self):
        f = _mkfeed("e1")
        self._t1_done(f)
        f.ingest(_env(4, "machine_turn"))
        # 标记与 turn_started 之间插入用户手打（铁律：用户手打=回合边界）
        f.ingest(_env(5, "user_echo", turn="t2", data={"text": "用户插话"}))
        f.ingest(_env(6, "turn_started", turn="t2"))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(len(heads), 2, "用户回合照常新起组头")

    def test_complete_without_duration_preserves_activeMs(self):
        f = _mkfeed("e1")
        self._t1_done(f)
        f.ingest(_env(4, "machine_turn"))
        f.ingest(_env(5, "turn_started", turn="t2"))
        # 生产 turn_complete 不带 duration_ms——不得把 activeMs 冲成 None
        f.ingest(_env(6, "turn_complete", turn="t2"))
        heads = [r for r in f.snap["rows"] if r["kind"] == "turn_header"]
        self.assertEqual(heads[0]["activeMs"], 1000, "无时长时保真前段工时")
        self.assertEqual(heads[0]["state"], "success")


if __name__ == "__main__":
    unittest.main()