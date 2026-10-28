# -*- coding: utf-8 -*-
"""a116 二十三次全审：/v4/stream 的**身份匹配**判据守护测试。

二十二次全审把正确性主链从「wseq 数值严格单调」改成「feed 实例身份
（incarnation）匹配」——`routes.py` 里 `base_inc == feed.incarnation`
是**唯一承重判据**。复审实测：这条判据当时零覆盖，变异掉它全套测试
仍然全绿（86 项）。本文件补上守护。

三条断言，对应三种必须区分的情形：
  1. inc 相同 + epoch 相同 + seq 在窗内 → resume（这是唯一允许续传的形态）
  2. **inc 不同**（同 epoch、同 seq）→ snapshot（承重判据本身）
  3. **inc 缺失**（老客户端/垫片丢失）→ snapshot（不能因缺失而放行）
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 与 test_route_smoke 同理：offload 形态下主进程没有 harness 路由
# （请求落到 worker 落点 → 503），必须在 import src.server 之前置位。
os.environ.setdefault("CLAUDE_INLINE", "1")

# 与 test_v4feed 同理：wseq/BOOT 落盘必须重定向，绝不能写真 HOME
_TMP = tempfile.mkdtemp(prefix="wseq_inc_")
import src.eventlog.store as _S
from src.harness import v4feed as _F
_S._WSEQ_DIR = _TMP
_F.V4Feed._boot_path = staticmethod(lambda: os.path.join(_TMP, "BOOT"))
_F.V4Feed._boot = None

from src.server import app
from src.harness import routes as _R

def _mkfeed():
    _F.V4Feed._hwm.clear()
    _F.V4Feed._hwm_floor = 0
    f = _F.V4Feed(epoch="E1", wseq_base=0)
    from src.harness import v4proto as P
    for i in range(5):
        f._commit("t%d" % i, [P.d_state({"n": i})])
    return f


class _Stub(object):
    session_id = "incstub"

    def __init__(self):
        self.log = type("L", (), {"epoch": "E1", "last_seq": 5,
                                  "wseq_hwm": 0})()


def _first_ack(qs):
    """打一次 /v4/stream，取**第一帧 ack**（不消费后续无限流）。"""
    c = app.test_client()
    r = c.get("/api/harness/v4/stream?" + qs)
    if r.status_code != 200:
        return None
    buf = b""
    try:
        for chunk in r.response:
            buf += chunk if isinstance(chunk, bytes) else chunk.encode()
            if b"\n\n" in buf:
                break
    finally:
        r.close()
    txt = buf.decode("utf-8", "replace")
    for block in txt.split("\n\n"):
        if block.startswith("event:ack"):
            for line in block.splitlines():
                if line.startswith("data: "):
                    import json
                    return json.loads(line[6:])
    return None


class TestStreamIncarnation(unittest.TestCase):
    def setUp(self):
        self.feed = _mkfeed()
        self.stub = _Stub()
        self._o_get = _R._get_or_create
        _R._get_or_create = lambda sid: self.stub
        from src.harness import v4hub
        self._o_feed = v4hub.v4_main_feed
        v4hub.v4_main_feed = lambda s, acquire=False: self.feed
        self._poked = False
        self._o_mark = getattr(v4hub, "mark_main_wanted", None)
        if self._o_mark:
            v4hub.mark_main_wanted = lambda s: None

    def tearDown(self):
        _R._get_or_create = self._o_get
        from src.harness import v4hub
        v4hub.v4_main_feed = self._o_feed
        if getattr(self, "_o_mark", None):
            v4hub.mark_main_wanted = self._o_mark

    def _qs(self, inc, seq=None):
        seq = self.feed.snap["seq"] if seq is None else seq
        return ("sid=incstub&topic=main&epoch=%s&seq=%d&inc=%s"
                % (self.feed.epoch, seq, inc))

    def test_matching_inc_resumes(self):
        """承重判据的正例：身份对得上才允许续传（否则本设计会退化成
        每次连接都整窗快照，虽然不丢数据但可感知地变慢）。"""
        a = _first_ack(self._qs(self.feed.incarnation))
        self.assertIsNotNone(a)
        self.assertEqual(a["mode"], "resume", "同实例续传被误拒")
        self.assertEqual(a["inc"], self.feed.incarnation, "ack 未回带身份")

    def test_different_inc_forces_snapshot(self):
        """**核心守护**：同 epoch、同 seq、inc 不同 → 必须快照。
        变异掉 `base_inc == feed.incarnation` 这一条，此用例必挂。"""
        a = _first_ack(self._qs("9" * 16))
        self.assertIsNotNone(a)
        self.assertEqual(a["mode"], "snapshot",
                         "inc 不匹配仍放行 → 旧游标会落进新实例空间（丢消息）")

    def test_missing_inc_forces_snapshot(self):
        """老客户端不传 inc（或垫片丢失）→ 一律快照，不能因「没带」而放行。"""
        a = _first_ack("sid=incstub&topic=main&epoch=%s&seq=%d"
                       % (self.feed.epoch, self.feed.snap["seq"]))
        self.assertIsNotNone(a)
        self.assertEqual(a["mode"], "snapshot",
                         "缺 inc 被当成匹配 → 老客户端可撞号")

    def test_ack_always_carries_inc(self):
        """ack 必须回带 inc（前端续传的全部依据）。"""
        for inc in (self.feed.incarnation, ""):
            a = _first_ack(self._qs(inc) if inc else
                           "sid=incstub&topic=main&epoch=%s&seq=%d"
                           % (self.feed.epoch, self.feed.snap["seq"]))
            self.assertEqual(a.get("inc"), self.feed.incarnation,
                             "ack 缺 inc，前端下次无法续传")



class TestAtomicPair(unittest.TestCase):
    """二十三次全审（严重，撕裂态）：ack 与 snapshot frame 必须**同批**
    写出。分两次 yield 会落进两个 TCP chunk，客户端在中间断线就得到
    (inc=新实例, seq=旧游标) —— 下次重连身份判据放行 → 旧投影吃新实例
    增量 → 花屏且永不回退快照（复现原始 P0）。"""

    def setUp(self):
        self.feed = _mkfeed()
        self.stub = _Stub()
        self._o_get = _R._get_or_create
        _R._get_or_create = lambda sid: self.stub
        from src.harness import v4hub
        self._o_feed = v4hub.v4_main_feed
        v4hub.v4_main_feed = lambda s, acquire=False: self.feed
        self._poked = False
        self._o_mark = getattr(v4hub, "mark_main_wanted", None)
        if self._o_mark:
            v4hub.mark_main_wanted = lambda s: None

    def tearDown(self):
        _R._get_or_create = self._o_get
        from src.harness import v4hub
        v4hub.v4_main_feed = self._o_feed
        if getattr(self, "_o_mark", None):
            v4hub.mark_main_wanted = self._o_mark

    def test_ack_and_snapshot_in_same_chunk(self):
        """首帧必须是**一个** chunk 里同时含 ack 与 frame（顺序 ack 在前）。"""
        c = app.test_client()
        r = c.get("/api/harness/v4/stream?sid=incstub&topic=main")
        self.assertEqual(r.status_code, 200)
        chunks = []
        try:
            for chunk in r.response:
                chunks.append(chunk if isinstance(chunk, bytes)
                              else chunk.encode())
                if len(chunks) >= 2:
                    break
        finally:
            r.close()
        first = chunks[0].decode("utf-8", "replace")
        self.assertIn("event:ack", first, "ack 不在首 chunk")
        self.assertIn('"mode": "snapshot"', first, "ack 模式异常")
        self.assertIn("event:frame", first,
                      "**撕裂态回归**：ack 与 frame 分属两个 chunk，"
                      "客户端可能在两者之间断线")
        self.assertLess(first.index("event:ack"), first.index("event:frame"),
                        "ack 必须在前")

    def test_ack_carries_same_inc_as_frame_seq(self):
        """ack 的 inc 与 seq 必须与同批 frame 的 toSeq 一致（配对原子）。"""
        c = app.test_client()
        r = c.get("/api/harness/v4/stream?sid=incstub&topic=main")
        buf = b""
        try:
            for chunk in r.response:
                buf += chunk if isinstance(chunk, bytes) else chunk.encode()
                if b"event:frame" in buf:
                    break
        finally:
            r.close()
        import json
        txt = buf.decode("utf-8", "replace")
        ack = frame = None
        for block in txt.split("\n\n"):
            for line in block.splitlines():
                if not line.startswith("data: "):
                    continue
                o = json.loads(line[6:])
                if block.startswith("event:ack"):
                    ack = o
                elif block.startswith("event:frame"):
                    frame = o
        self.assertIsNotNone(ack)
        self.assertIsNotNone(frame)
        self.assertEqual(ack["inc"], self.feed.incarnation)
        self.assertEqual(ack["seq"], frame["toSeq"],
                         "ack.seq 与 frame.toSeq 不一致 → 配对未原子")



    def test_snapshot_then_deltas_converges(self):
        """**收敛性**（二十四次全审严重回归的守护）：起始 snapshot 之后
        落一条事件，必须收到 deltas —— 而不是再来一个 snapshot。

        回归形态：`_snap_pair` 把 `_snap_text` 的 sent 解包成函数局部，
        `_gen` 的 sent 永久停在 0 → poll(0) 恒 None → 每次循环都判「越窗」
        → 每条消息一次整窗重渲（实测 22 条事件 22 次 snapshot、deltas=0）。
        """
        from src.harness import v4proto as P
        import threading
        c = app.test_client()
        r = c.get("/api/harness/v4/stream?sid=incstub&topic=main")
        buf = ""
        snaps = deltas = 0
        deadline = __import__("time").time() + 8.0
        # 回归态（sent 恒 0）下循环会**无限**重发快照，永不退出——
        # 必须有硬截止，否则测试挂死而不是失败。
        try:
            for chunk in r.response:
                buf += chunk.decode("utf-8", "replace") if isinstance(
                    chunk, bytes) else chunk
                # 收到首快照后再落一条事件，然后继续读到出现增量
                if snaps == 1 and deltas == 0 and not self._poked:
                    self._poked = True
                    self.feed._commit("late", [P.d_state({"n": 99})])
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    if block.startswith("event:frame") and '"snapshot"' in block:
                        snaps += 1
                    elif block.startswith("event:frame") and '"deltas"' in block:
                        deltas += 1
                if deltas or __import__("time").time() > deadline:
                    break
        finally:
            r.close()
        self.assertEqual(snaps, 1, "重复整窗快照：sent 游标未推进")
        self.assertGreater(deltas, 0, "增量路径失效：每个事件都在整窗重发")


if __name__ == "__main__":
    unittest.main(verbosity=2)
