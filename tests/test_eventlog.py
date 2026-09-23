# -*- coding: utf-8 -*-
"""最小自测：事件溯源层 eventlog（v3.0，方案对照 ZCode 事件溯源架构）。

覆盖七块：
1. 信封：kind→type 映射、公共字段（seq/ts/epoch/sid/turn）注入、kind 保留
   （前端按它分派不受影响）、未知 kind 前向透传。
2. seq 并发安全：8 线程 × 200 条并发 emit——严格递增、无重复、缓冲有序
   （v2.x seq 在锁外分配的竞态回归防线）。
3. 断点续传三态：resume（base 落在 [floor, last]）/ snapshot（base 无效
   或缺失）/ reset（epoch 不匹配）；保留窗滑出推进 floor_seq；计数器
   只增不减（淘汰/换代不回拨）。
4. SSE 帧协议：ack 帧形状、resume 回放段、接缝去重（订阅后并发 publish
   不丢不重）、慢订阅者溢出 → reset 控制帧、ka 心跳在空闲时发出。
5. 工具输出截断：超 64KB 头尾各 32KB + 中间标记 + truncated 元数据；
   多字节安全（切点落 UTF-8 字符中间不炸）；小输出零拷贝直通；
   stash LRU 逐出后全文 404 语义（get None）。
6. 投影归约：turn_started/complete/error 推 status、turn 计数、last_error
   源头清理；未知类型只 bump 不崩（前向兼容）；对同一事件段 reduce_events
   与增量 apply 结果一致（live/replay 共用同一归约）。
7. 换代与重建：bump_epoch（rewind）后旧 epoch 只能 reset、seq 续不回拨；
   restore（GC 重建）同代续号可 resume、旧 meta 无 epoch 换新代。

直接 `py tests/test_eventlog.py` 运行。纯内存测试，不碰 ~/.serialconsole_pro。
"""
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.eventlog import (SessionEventLog, SessionEventType, reduce_events,
                          PROTOCOL_LIMITS)
from src.eventlog.bus import SUBSCRIBER_BUFFER, KEEPALIVE_S

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def main():
    print("== 1. 信封 ==")
    log = SessionEventLog("s1", retention=100)
    e1 = log.emit({"kind": "user_echo", "text": "hi"})
    e2 = log.emit({"kind": "event", "data": {"type": "assistant"}})
    e3 = log.emit({"kind": "raw", "text": "x"}, turn="t9")
    check("seq 从 1 严格递增", e1["seq"] == 1 and e2["seq"] == 2 and e3["seq"] == 3)
    check("信封公共字段齐备",
          all(e1.get(k) for k in ("seq", "ts", "epoch", "sid", "type")))
    check("sid/epoch 注入", e1["sid"] == "s1" and e1["epoch"] == log.epoch)
    check("kind 保留（前端兼容）", e1["kind"] == "user_echo")
    check("CLI 透射 type=cli_stream", e2["type"] == SessionEventType.CLI_STREAM)
    check("控制事件 type==kind", e1["type"] == "user_echo")
    check("turn 字段随行", e3.get("turn") == "t9" and "turn" not in e1)
    e4 = log.emit({"kind": "future_unknown_kind"})
    check("未知 kind 前向透传", e4["type"] == "future_unknown_kind")

    print("== 2. seq 并发安全 ==")
    cc = SessionEventLog("cc", retention=5000)
    def worker(n):
        for i in range(200):
            cc.emit({"kind": "raw", "text": "w%d-%d" % (n, i)})
    ths = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    seqs = [e["seq"] for e in cc.events_after(0)]
    check("并发 1600 条无重复", len(seqs) == 1600 and len(set(seqs)) == 1600,
          "len=%d uniq=%d" % (len(seqs), len(set(seqs))))
    check("并发后缓冲仍有序", seqs == sorted(seqs))

    print("== 3. 断点续传三态 ==")
    sm = SessionEventLog("sm", retention=10)
    for i in range(15):
        sm.emit({"kind": "raw", "text": "e%d" % i})
    check("保留窗滑出推进 floor", sm.floor_seq == 5 and sm.last_seq == 15,
          "floor=%s last=%s" % (sm.floor_seq, sm.last_seq))
    check("base 在窗内 → resume",
          sm.store.resume_mode(sm.epoch, 10) == "resume")
    check("base 落窗外 → snapshot",
          sm.store.resume_mode(sm.epoch, 2) == "snapshot")
    check("base 越过 last → snapshot",
          sm.store.resume_mode(sm.epoch, 99) == "snapshot")
    check("base 缺省（无 epoch）→ snapshot", sm.store.resume_mode(None, 10) == "snapshot")
    check("epoch 不匹配 → reset", sm.store.resume_mode("bogus", 10) == "reset")
    check("淘汰后计数器不回拨（floor 前的 seq 不再复用）",
          sm.emit({"kind": "raw", "text": "n"})["seq"] == 16)

    print("== 4. SSE 帧协议 ==")
    fp = SessionEventLog("fp")
    for i in range(3):
        fp.emit({"kind": "raw", "text": "f%d" % i})
    sub, mode, replay = fp.subscribe(base_epoch=fp.epoch, base_seq=1)
    check("subscribe 判 resume 且回放 (1,3]", mode == "resume"
          and [e["seq"] for e in replay] == [2, 3])
    # 接缝去重：订阅后（快照前）新事件进队列，帧生成器按 seq 跳过重发
    fp.bus.publish(fp.store.append({"kind": "raw", "text": "live"},
                                   turn=None))
    gen = fp.frames(sub, mode, replay)
    f_ack = next(gen)
    check("首帧 event: ack 且 mode 正确",
          f_ack.startswith("event: ack") and '"resume"' in f_ack, f_ack[:60])
    body = [next(gen) for _ in range(3)]
    import re as _re
    seqs_got = [_re.search(r'"seq": (\d+)', b).group(1) for b in body]
    check("回放+live 帧序无重复", seqs_got == ["2", "3", "4"], repr(seqs_got))
    check("空闲心跳 event: ka", next(gen).startswith("event: ka"))
    check("ka 间隔对照 ZCode 5s", KEEPALIVE_S == 5)
    check("订阅者 buffer 对照 ZCode 500", SUBSCRIBER_BUFFER == 500)
    # 慢订阅者：灌满 buffer → 清积压投 reset
    for i in range(SUBSCRIBER_BUFFER + 50):
        fp.bus.publish({"kind": "raw", "text": "flood", "seq": 1000 + i})
    got = sub.queue.get(timeout=1)
    check("溢出投递 reset 控制帧", got.get("__control__") == "reset", repr(got)[:60])
    sub2, mode2, replay2 = fp.subscribe(base_epoch="bogus", base_seq=0)
    g2 = fp.frames(sub2, mode2, replay2)
    check("reset 模式 ack 后即 reset 帧并断流",
          next(g2).startswith("event: ack") and next(g2).startswith("event: reset"))
    try:
        next(g2)
        ended = False
    except StopIteration:
        ended = True
    check("reset 模式生成器终止", ended)

    print("== 5. 工具输出截断 ==")
    tr = SessionEventLog("tr")
    head_b = PROTOCOL_LIMITS["tool_output_head_bytes"]
    tail_b = PROTOCOL_LIMITS["tool_output_tail_bytes"]
    big = "x" * (head_b + tail_b + 4096)
    cli_ev = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": big}]}}
    env = tr.emit({"kind": "event", "data": cli_ev})
    blk = env["data"]["message"]["content"][0]
    check("超限截断 + total_bytes 元数据",
          blk["_truncated"]["total_bytes"] == len(big))
    check("截断结果 ≤ head+tail+标记",
          len(blk["content"].encode("utf-8")) <= head_b + tail_b + 16)
    check("中间标记 \\n…\\n", "\n…\n" in blk["content"])
    check("ref 可取回全文", tr.full_output(blk["_truncated"]["ref"]) == big)
    # 多字节安全：中文串跨切点
    mb = "汉" * 40000            # 120000 字节 > 64KB，切点必落多字节字符中间
    ev2 = tr.emit({"kind": "event", "data": {"type": "user", "message": {
        "content": [{"type": "tool_result", "content": mb}]}}})
    b2 = ev2["data"]["message"]["content"][0]
    check("多字节切点不炸（两侧 ignore 解码）", b2["content"].startswith("汉")
          and b2["content"].endswith("汉") and "\n…\n" in b2["content"])
    # 小输出零拷贝
    small = {"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "ok"}]}}
    check("小输出原对象直通（零拷贝）",
          tr.emit({"kind": "event", "data": small})["data"] is small)
    # stash LRU：灌 32+ 条，最早被逐出
    first_ref = None
    for i in range(PROTOCOL_LIMITS["stash_max_entries"] + 1):
        t = "L%d-%s" % (i, "y" * 100) + "z" * (head_b + tail_b)
        e = tr.emit({"kind": "event", "data": {"type": "user", "message": {
            "content": [{"type": "tool_result", "content": t}]}}})
        r = e["data"]["message"]["content"][0]["_truncated"]["ref"]
        if i == 0:
            first_ref = r
    check("stash LRU 逐出（最早 ref 取不回）", tr.full_output(first_ref) is None)

    print("== 6. 投影归约 ==")
    evs = [
        {"kind": "turn_started", "turn": "t1", "seq": 1},
        {"kind": "user_echo", "turn": "t1", "seq": 2},
        {"kind": "event", "turn": "t1", "seq": 3,
         "data": {"type": "assistant", "message": {"content": []}}},
        {"kind": "turn_complete", "turn": "t1", "seq": 4},
        {"kind": "turn_started", "turn": "t2", "seq": 5},
        {"kind": "turn_error", "turn": "t2", "text": "进程崩溃", "seq": 6},
        {"kind": "future_x", "seq": 7},
    ]
    from src.eventlog import initial_projection
    p = initial_projection("pj")
    for e in evs:
        p = __import__("src.eventlog", fromlist=["apply_event"]).apply_event(p, e)
    check("turn 计数=2 且终态 idle", p["turn_count"] == 2 and p["status"] == "idle")
    check("turn_error 落 last_error", p["last_error"] == "进程崩溃")
    check("未知类型不崩且推进 last_seq", p["last_seq"] == 7)
    p2 = reduce_events("pj", evs)
    check("整段归约与逐条一致（live/replay 共用）",
          p2["turn_count"] == p["turn_count"] and p2["status"] == p["status"]
          and p2["last_seq"] == p["last_seq"])
    # 新 turn 清旧错误（ZCode 源头清理语义）
    p3 = __import__("src.eventlog", fromlist=["apply_event"]).apply_event(
        p, {"kind": "turn_started", "turn": "t3", "seq": 8})
    check("新 turn 清旧 last_error", p3["last_error"] is None
          and p3["status"] == "running")
    # 集成：store.append 内嵌归约（增量真源）
    it = SessionEventLog("it")
    it.emit({"kind": "turn_started"}, turn="t1")
    it.emit({"kind": "user_echo", "text": "q"}, turn="t1")
    check("store 增量投影=running 且 turn 在场",
          it.projection["status"] == "running" and it.projection["turn"])

    print("== 7. 换代与重建 ==")
    rw = SessionEventLog("rw")
    for i in range(5):
        rw.emit({"kind": "raw", "text": "r%d" % i})
    old_epoch = rw.epoch
    rw.bump_epoch()
    check("bump 后旧 epoch → reset",
          rw.store.resume_mode(old_epoch, 3) == "reset")
    check("bump 后同代 base 也只能 snapshot（缓冲已清）",
          rw.store.resume_mode(rw.epoch, 3) == "snapshot")
    nxt = rw.emit({"kind": "raw", "text": "after"})
    check("换代后 seq 续不回拨", nxt["seq"] == 6 and nxt["epoch"] == rw.epoch)
    gc1 = SessionEventLog("gc")
    eg = gc1.emit({"kind": "raw", "text": "x"})
    gc2 = SessionEventLog("gc")
    gc2.restore(gc1.epoch, eg["seq"])
    check("GC 重建同代续号 → resume",
          gc2.store.resume_mode(gc1.epoch, eg["seq"]) == "resume")
    gc3 = SessionEventLog("gc3")
    gc3.restore(None, 42)
    gc4 = SessionEventLog("gc3")
    gc4.restore(None, 42)
    check("旧 meta 无 epoch → 各自换新代（前端水位作废走 snapshot）",
          gc3.epoch != gc4.epoch)

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：")
        for n in _FAIL:
            print("  -", n)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
