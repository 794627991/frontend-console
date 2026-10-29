# -*- coding: utf-8 -*-
"""最小自测：事件溯源层 eventlog（v3.0，方案对照 ZCode 事件溯源架构）。

覆盖七块：
1. 信封：kind→type 映射、公共字段（seq/ts/epoch/sid/turn）注入、kind 保留
   （前端按它分派不受影响）、未知 kind 前向透传。
2. seq 并发安全：8 线程 × 200 条并发 emit——严格递增、无重复、缓冲有序
   （v2.x seq 在锁外分配的竞态回归防线）。
3. 保留窗：滑出推进 floor_seq；计数器只增不减（淘汰/换代不回拨）。
   （§3 resume 三态与 §4 SSE 帧协议已随批G 退役——bus//stream 删除，
   v4 客户端由 /v4/stream 的 ack 三态 + epoch 对账承担同职责）
5. 工具输出截断：超 64KB 头尾各 32KB + 中间标记 + truncated 元数据；
   多字节安全（切点落 UTF-8 字符中间不炸）；小输出零拷贝直通；
   stash LRU 逐出后全文 404 语义（get None）。
   （§6 投影归约已随批G 退役——reducer.py 整文件删除）
7. 换代与重建：bump_epoch（rewind）后 seq 续不回拨、缓冲清空；
   restore（GC 重建）同代续号、旧 meta 无 epoch 换新代。

直接 `py tests/test_eventlog.py` 运行。纯内存测试，不碰 ~/.serialconsole_pro。
"""
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.eventlog import (SessionEventLog, SessionEventType, PROTOCOL_LIMITS)

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
    check("淘汰后计数器不回拨（floor 前的 seq 不再复用）",
          sm.emit({"kind": "raw", "text": "n"})["seq"] == 16)

    # （§4 SSE 帧协议已随批G 退役——bus//stream 旧链删除）

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

    # （§6 投影归约已随批G 退役——reducer.py 整文件删除）

    print("== 7. 换代与重建 ==")
    rw = SessionEventLog("rw")
    for i in range(5):
        rw.emit({"kind": "raw", "text": "r%d" % i})
    old_epoch = rw.epoch
    rw.bump_epoch()
    nxt = rw.emit({"kind": "raw", "text": "after"})
    check("换代后 seq 续不回拨", nxt["seq"] == 6 and nxt["epoch"] == rw.epoch)
    gc1 = SessionEventLog("gc")
    eg = gc1.emit({"kind": "raw", "text": "x"})
    gc2 = SessionEventLog("gc")
    gc2.restore(gc1.epoch, eg["seq"])
    check("GC 重建同代续号", gc2.epoch == gc1.epoch and gc2.last_seq == eg["seq"])
    gc3 = SessionEventLog("gc3")
    gc3.restore(None, 42)
    gc4 = SessionEventLog("gc3")
    gc4.restore(None, 42)
    check("旧 meta 无 epoch → 各自换新代（前端水位作废走 snapshot）",
          gc3.epoch != gc4.epoch)

    # （§8 投影断言已随批G 退役——reducer/projection 删除；镜像事件
    #  行为级覆盖在 test_ledger §5 与 test_v4feed）

    print("== 9. microcompact（旧回合超大负载折叠）==")
    from src.eventlog.store import COMPACT_BYTES, _fold_text
    big = "x" * 12000
    log9 = SessionEventLog("s9", retention=100)
    log9.emit({"kind": "turn_started"}, turn="t9a")
    # 真实流里 cli 事件都带回合 id（session.emit 统一注入），折叠按回合归属判定
    log9.emit({"kind": "event", "data": {"type": "assistant", "message": {"content": [
        {"type": "text", "text": big}]}}}, turn="t9a")
    log9.emit({"kind": "turn_complete"}, turn="t9a")
    folded, dropped = _fold_text(big)
    check("_fold_text 头尾保留 + 标记",
          folded.startswith("x" * 200) and folded.endswith("x" * 200)
          and dropped > 8000 and "已折叠" in folded)
    small, zero = _fold_text("short")
    check("小文本零折叠直通", small == "short" and zero == 0)
    # 保留窗字节未超阈 → 不折叠
    log9.emit({"kind": "turn_started"})
    envs = [e for e in log9.store.snapshot() if e.get("type") == "cli_stream"]
    check("未超阈值不折叠", all(not e.get("_folded") for e in envs))
    # 直接压 store 层验证：把阈值临时调小触发折叠路径
    import src.eventlog.store as _st
    orig = _st.COMPACT_BYTES
    try:
        _st.COMPACT_BYTES = 1024
        st = log9.store
        st._bytes = orig and (st._bytes + 10 * 1024 * 1024)   # 强制超阈
        st._maybe_compact("nonexistent-turn")
        envs2 = [e for e in st.snapshot() if e.get("type") == "cli_stream"]
        hit = [e for e in envs2 if e.get("_folded")]
        check("超阈值旧回合大事件被折叠（含 _folded 标记）",
              len(hit) == 1 and hit[0]["data"]["message"]["content"][0]["text"].startswith("x" * 200))
        check("stats 暴露 compacted 计数", st.stats()["compacted"] >= 1)
        # 新回合（当前 turn）与已折叠事件不重复处理
        st._maybe_compact("nonexistent-turn")
        check("二次 compact 幂等", st.stats()["compacted"] == len(hit))
    finally:
        _st.COMPACT_BYTES = orig

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：")
        for n in _FAIL:
            print("  -", n)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
