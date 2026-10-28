# -*- coding: utf-8 -*-
"""内存批回归测试（用户定调「子代理可无条件点开 ≠ feed 永久驻留」）：

① V4Feed 订阅者计数：/v4/stream 首尾配对语义（acquire/release/下限）
② v4_reap_idle：无订阅者 + 宽限外闲置才收；订阅者在场/活跃 feed 免收；
   busy 会话主 feed 免收；回收后重开路径（冷建）可达
③ watcher subagent_delta 门禁：无 V3 订阅者不 emit（账本零残留）、
   有订阅者照发、bus 查询异常保守照发
④ facts 截断：长 tool_result 截 2000，回执/续派提取不受影响
"""
import importlib.util
import logging
import os
import sys
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS_DIR = os.path.join(ROOT, "src", "harness")

# 与 test_v4feed.py 同款：stub harness 包上下文，绕开 consts→app_state 链
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


_cst = types.ModuleType("harness.consts")
_cst._sessions = {}
_cst._sessions_lock = threading.RLock()
_cst.log = logging.getLogger("test.mem_reap")
sys.modules["harness.consts"] = _cst

P = _load("harness.v4proto", "v4proto.py")
F = _load("harness.v4feed", "v4feed.py")
H = _load("harness.v4hub", "v4hub.py")
W = _load("harness.subagent_watch", "subagent_watch.py")
SP = _load("harness.subagent_projection", "subagent_projection.py")


def _use_temp_wseq_dir():
    import tempfile
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import src.eventlog.store as _S
    _S._WSEQ_DIR = tempfile.mkdtemp(prefix="wseq_test_")
    F.V4Feed._boot_path = staticmethod(
        lambda: os.path.join(_S._WSEQ_DIR, "BOOT"))


_use_temp_wseq_dir()


def _sub_line(i):
    """产出一行能进子投影的 assistant 文本行（带 uuid/timestamp）。"""
    import json
    import uuid
    return json.dumps({
        "type": "assistant", "uuid": str(uuid.uuid4()),
        "timestamp": "2026-10-26T09:00:%02dZ" % (i % 60),
        "message": {"model": "m", "content": [
            {"type": "text", "text": "行 %d" % i}]}})


class TestSubCounter(unittest.TestCase):
    """订阅者计数：配对增减 + 下限保护 + 计数在场阻止回收。"""

    def test_acquire_release_pair(self):
        fd = F.V4Feed(epoch="sub")
        self.assertEqual(fd.subs_n(), 0)
        fd.sub_acquire()
        fd.sub_acquire()
        self.assertEqual(fd.subs_n(), 2)
        fd.sub_release()
        self.assertEqual(fd.subs_n(), 1)
        fd.sub_release()
        self.assertEqual(fd.subs_n(), 0)
        fd.sub_release()                  # 防御性下限：不得为负
        self.assertEqual(fd.subs_n(), 0)

    def test_commit_bumps_last_ingest_at(self):
        fd = F.V4Feed(epoch="sub")
        fd.last_ingest_at -= 3600
        fd.ingest({"type": "sysnote", "seq": 1, "ts": 1, "turn": "",
                   "data": {"text": "x"}})
        self.assertGreater(time.time() - fd.last_ingest_at, -5)
        self.assertLess(time.time() - fd.last_ingest_at, 5)


class _HubTestCase(unittest.TestCase):
    def setUp(self):
        H._sub_feeds.clear()
        H._main_feeds.clear()
        H._main_wanted.clear()
        H._empty_feeds.clear()
        _cst._sessions.clear()

    def tearDown(self):
        self.setUp()


class TestReapIdle(_HubTestCase):

    def _mk_sub_feed(self, key, age, subs=0, rows=True):
        fd = F.V4Feed(epoch="sub")
        if rows:
            fd.feed_jsonl_line({
                "type": "assistant", "uuid": "u-%r" % (key,),
                "timestamp": "2026-10-26T09:00:00Z",
                "message": {"content": [{"type": "text", "text": "x"}]}})
        fd.last_ingest_at = time.time() - age
        for _ in range(subs):
            fd.sub_acquire()
        H._sub_feeds[key] = fd
        return fd

    def test_stale_unsubscribed_sub_feed_reaped(self):
        """无订阅者 + 宽限外 → 回收（用户红线：重开仍可达=冷建）。"""
        fd = self._mk_sub_feed(("s1", "ag1"), age=H._SUB_FEED_GRACE_S + 60)
        H.v4_reap_idle()
        self.assertNotIn(("s1", "ag1"), H._sub_feeds)
        # 重开路径：v4_sub_feed 无缓存时按 paths 冷建（零产出不缓存语义同旧）
        fd2 = H.v4_sub_feed("s1", "ag1", None)
        self.assertNotIn(("s1", "ag1"), H._sub_feeds)

    def test_subscribed_sub_feed_kept(self):
        """pane 在场（订阅者计数>0）→ 永不回收。"""
        self._mk_sub_feed(("s1", "ag1"), age=H._SUB_FEED_GRACE_S + 60, subs=1)
        H.v4_reap_idle()
        self.assertIn(("s1", "ag1"), H._sub_feeds)

    def test_active_sub_feed_kept(self):
        """运行中代理（watcher 持续喂入，last_ingest_at 新鲜）→ 免收。"""
        self._mk_sub_feed(("s1", "ag1"), age=0)
        H.v4_reap_idle()
        self.assertIn(("s1", "ag1"), H._sub_feeds)

    def test_main_feed_busy_session_kept(self):
        """busy 会话的主 feed 免收（收了也会被 emit 立刻重建=抖动）。"""
        class S(object):
            sid = "sm"
            busy = True
        _cst._sessions["sm"] = S()
        fd = F.V4Feed(epoch="e1")
        fd.last_ingest_at = time.time() - (H._MAIN_FEED_GRACE_S + 60)
        H._main_feeds["sm"] = fd
        H._main_wanted.add("sm")
        H.v4_reap_idle()
        self.assertIn("sm", H._main_feeds)

    def test_idle_main_feed_reaped_wanted_kept(self):
        """闲置主 feed 回收，**保留** _main_wanted（对抗审 B-P1）。

        harness 自产镜像事件（subagent_started/result 等）永不落 CLI 转写
        ——门禁若随回收关闭，无人观看期迟到的这类事件进不了任何 feed，其
        seq 又在重开冷建的水位之下（events_after 严格 >），投影永久缺失。
        保留门禁 → 下一条 emit 经 v4_ingest_main 触发冷建并就地 ingest。"""
        class S(object):
            sid = "sm"
            busy = False
        _cst._sessions["sm"] = S()
        fd = F.V4Feed(epoch="e1")
        fd.last_ingest_at = time.time() - (H._MAIN_FEED_GRACE_S + 60)
        H._main_feeds["sm"] = fd
        H._main_wanted.add("sm")
        H.v4_reap_idle()
        self.assertNotIn("sm", H._main_feeds)
        self.assertIn("sm", H._main_wanted)

    def test_sub_reap_discards_sub_wanted(self):
        """子 feed 回收对称清 _sub_wanted（对抗审 A/B：防无人观看的
        「续派写一行→watcher 全量重析 MB 级转写→再回收」IO 循环）。"""
        H._sub_wanted.append(("s1", "ag9"))
        self._mk_sub_feed(("s1", "ag9"), age=H._SUB_FEED_GRACE_S + 60)
        H.v4_reap_idle()
        self.assertNotIn(("s1", "ag9"), H._sub_feeds)
        self.assertNotIn(("s1", "ag9"), H._sub_wanted)

    def test_stale_empty_feeds_swept(self):
        """_empty_feeds 零产出临时 feed 超宽限同收（跨会话累积闭环）。"""
        fd = F.V4Feed(epoch="e1")
        H._empty_feeds["se"] = ("e1", time.time() - (H._MAIN_FEED_GRACE_S + 60), fd)
        H.v4_reap_idle()
        self.assertNotIn("se", H._empty_feeds)
        # TTL 窗内的不收（复用语义不变）
        fd2 = F.V4Feed(epoch="e1")
        H._empty_feeds["se2"] = ("e1", time.time() - 5.0, fd2)
        H.v4_reap_idle()
        self.assertIn("se2", H._empty_feeds)

    def test_sub_feed_acquire_atomic(self):
        """acquire=True：在册/零产出临时/竞速胜者三口都锁内计数（A-P1）。"""
        fd = self._mk_sub_feed(("s1", "agA"), age=0)
        self.assertEqual(fd.subs_n(), 0)
        got = H.v4_sub_feed("s1", "agA", None, acquire=True)
        self.assertIs(got, fd)
        self.assertEqual(fd.subs_n(), 1)
        got.sub_release()
        self.assertEqual(fd.subs_n(), 0)
        # 零产出临时（不入册）同样配对
        tmp = H.v4_sub_feed("s1", "agMISSING", None, acquire=True)
        self.assertNotIn(("s1", "agMISSING"), H._sub_feeds)
        self.assertEqual(tmp.subs_n(), 1)
        tmp.sub_release()

    def test_recheck_does_not_leak_count(self):
        """v4.0.6（自查实锤）：换 feed 对账里「不采纳同实例」必须退还。

        `/v4/stream` 每 5s 对账一次，用 acquire=True 重新取 feed。若
        `_f2 is _f`（在册同实例）时不 release，每 5s 净 +1 → subs_n 单调
        虚高 → 该 feed 永不被 v4_reap_idle 回收（内存优化对子 feed 失效）。
        这里模拟该对账循环若干轮，断言计数不增长。
        """
        fd = self._mk_sub_feed(("s1", "agB"), age=0)
        fd.sub_acquire()                       # 连接本身的计数
        for _ in range(5):                     # 模拟 5 轮 5s 对账
            got = H.v4_sub_feed("s1", "agB", None, acquire=True)
            self.assertIs(got, fd)
            if got is fd:                      # routes.py 的对账语义
                got.sub_release()
        self.assertEqual(fd.subs_n(), 1,
                         "对账轮次泄漏计数 → 该 feed 永不回收")
        # 同一缺陷的**源头**断言：routes.py 的不采纳分支必须覆盖
        # `_f2 is _f`（只写 `is not _f` 就是本缺陷）。上面只验证语义，
        # 只有这条能防源码回退。
        src = open(os.path.join(ROOT, "src/harness/routes.py"),
                   encoding="utf-8").read()
        i = src.index('if _f2 is not _f and _f2.snap.get("rows"):')
        seg = src[i:i + 900]
        self.assertIn("_f2 is _f or not _f2.snap.get", seg,
                      "不采纳分支漏了「同实例退还」→ 每 5s 对账净 +1")

    def test_head_request_does_not_leak_count(self):
        """v4.0.7（自查实证）：HEAD / 未消费响应不得获取订阅计数。

        实测（Flask 测试客户端）：在 handler 里 acquire 时，`HEAD /v4/stream`
        后 subs_n=1 且永不回落（生成器未启动，finally 不执行）；GET+close
        才回 0。计数必须放在生成器首行。
        """
        src = open(os.path.join(ROOT, "src/harness/routes.py"),
                   encoding="utf-8").read()
        # handler 的取 feed 不得带 acquire=True（否则 HEAD 请求泄漏）
        self.assertIn("v4_sub_feed(s.sid, agent, paths, acquire=False)", src,
                      "handler 仍在取计数 → HEAD 请求泄漏")
        self.assertIn("v4_main_feed(s, acquire=False)", src,
                      "主 feed 仍在 handler 取计数 → HEAD 请求泄漏")
        i = src.index("def harness_v4_stream(")
        i = src.index("def gen():", i)          # v4 那个（不是 V3 的）
        seg = src[i:i + 1600]
        self.assertIn("acquire=True", seg,
                      "生成器首行没有取计数 → 与 finally 不配对")
        # acquire 必须在 try 之前、finally 里有 release
        self.assertLess(seg.index("acquire=True"), seg.index("try:"))
        self.assertIn("sub_release()", seg)


class _Bus(object):
    def __init__(self, has):
        self._has = has

    def has_subscribers(self):
        if self._has is Exception:
            raise Exception("bus boom")
        return self._has


class _Log(object):
    def __init__(self, bus):
        self.bus = bus
        self.emitted = []

    def emit(self, item):
        self.emitted.append(item)
        return item


class _Sess(object):
    def __init__(self, log):
        self.log = log
        self.sid = "sw"

    def emit(self, item):
        return self.log.emit(item)


class TestWatchEmitGate(unittest.TestCase):
    """subagent_delta 账本门禁：无 V3 消费者不进账本（370MB 级常驻根除）。"""

    def test_no_subscribers_no_emit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "agent-ag1.jsonl")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(_sub_line(0) + "\n")
            W._offsets.pop(fp, None)
            log = _Log(_Bus(False))
            n = W._push_file(_Sess(log), fp, "ag1", reconcile=True)
            self.assertGreater(n, 0)   # 增量照常消费（v4 子投影喂入不受影响）
            self.assertEqual(log.emitted, [])   # 但不进账本（零消费者）

    def test_with_subscribers_emits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "agent-ag1.jsonl")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(_sub_line(0) + "\n")
            W._offsets.pop(fp, None)
            log = _Log(_Bus(True))
            n = W._push_file(_Sess(log), fp, "ag1", reconcile=True)
            self.assertGreater(n, 0)
            self.assertEqual(len(log.emitted), 1)
            self.assertEqual(log.emitted[0]["data"]["type"], "subagent_delta")

    def test_bus_error_fallback_emits(self):
        """has_subscribers 抛错 → 保守照发（宁可多吃不可断流）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "agent-ag1.jsonl")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(_sub_line(0) + "\n")
            W._offsets.pop(fp, None)
            log = _Log(_Bus(Exception))
            n = W._push_file(_Sess(log), fp, "ag1", reconcile=True)
            self.assertGreater(n, 0)
            self.assertEqual(len(log.emitted), 1)


class TestFactsTruncation(unittest.TestCase):

    def test_long_result_text_truncated(self):
        lines = ['{"type":"assistant","uuid":"a1","timestamp":"2026-10-26T09:00:00Z",'
                 '"message":{"content":[{"type":"tool_use","name":"Bash",'
                 '"id":"tu1","input":{"command":"ls"}}]}}',
                 '{"type":"user","uuid":"u1","timestamp":"2026-10-26T09:00:01Z",'
                 '"message":{"content":[{"type":"tool_result",'
                 '"tool_use_id":"tu1","content":"%s"}]}}' % ("x" * 90000)]
        facts = SP.collect_main_facts(lines)
        res = [f for f in facts if f["kind"] == "result"]
        self.assertEqual(len(res), 1)
        self.assertEqual(len(res[0]["text"]), 2000)

    def test_receipt_extraction_within_prefix(self):
        """截断不得伤回执提取：ACK（bg）与前台 JSON 回执都在头部。"""
        lines = ['{"type":"assistant","uuid":"a1","timestamp":"2026-10-26T09:00:00Z",'
                 '"message":{"content":[{"type":"tool_use","name":"Task",'
                 '"id":"tu1","input":{"run_in_background":true}}]}}',
                 '{"type":"user","uuid":"u1","timestamp":"2026-10-26T09:00:01Z",'
                 '"message":{"content":[{"type":"tool_result","tool_use_id":"tu1",'
                 '"content":"Task agentId: ab12cd34ef56 (internal ID) %s"}]}}'
                 % ("y" * 5000)]
        facts = SP.collect_main_facts(lines)
        d = next(f for f in facts if f["kind"] == "dispatch")
        r = next(f for f in facts if f["kind"] == "result")
        self.assertEqual(SP._agent_id_from_receipt(r["text"], bg=d["bg"]),
                         "ab12cd34ef56")

    def test_send_reclassify_after_truncation(self):
        """续派回执（resumedAgentId）在截断窗内仍被后置分类命中。"""
        lines = ['{"type":"assistant","uuid":"a1","timestamp":"2026-10-26T09:00:00Z",'
                 '"message":{"content":[{"type":"tool_use","name":"SendMessage",'
                 '"id":"tu2","input":{"to":"ag9","message":"hi"}}]}}',
                 '{"type":"user","uuid":"u2","timestamp":"2026-10-26T09:00:01Z",'
                 '"message":{"content":[{"type":"tool_result","tool_use_id":"tu2",'
                 '"content":"{\\"resumedAgentId\\": \\"zz99aa88bb77\\"} %s"}]}}'
                 % ("z" * 3000)]
        facts = SP.collect_main_facts(lines)
        sr = [f for f in facts if f["kind"] == "send_result"]
        self.assertEqual(len(sr), 1)
        self.assertEqual(sr[0]["resumed"], "zz99aa88bb77")


if __name__ == "__main__":
    unittest.main()
