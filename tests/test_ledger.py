# -*- coding: utf-8 -*-
"""v3.1 durable 输入账本 + 子代理镜像 + 分支世代集成测试（纯内存，隔离 meta）。

覆盖：
1. queue_admit/queue_list/queue_discard/queue_to_head 账本操作 + 事件流
   （input_admitted/discarded/promoted）+ 投影（inbox）三态一致；
2. to_meta 落盘口径（inbox/gen 随元数据持久，GC 重建路径由 lifecycle 恢复）；
3. bump_generation（#14 /rewind 换代）：旧代条目全作废 + 事件显式通知；
4. 回合终结自动泵（#10）：_turn_end → 800ms 后真发；无进程会话发送失败
   → 条目作废（input_discarded reason=发送失败），不静默吞；
5. _emit_task_mirror（#12）：CLI task_started/task_notification → 干净镜像
   事件 + reducer agents 投影。

直接 `py tests/test_ledger.py` 运行。meta 读写全部打补丁为内存字典——
绝不触碰 ~/.serialconsole_pro 真实用户数据。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.harness.session as S

# 隔离：sync_meta 只写内存字典，_meta_load 空操作（会话注册/标题路径不读真实盘）
S._meta_load = lambda: None
S._meta_save = lambda: None
S._meta = {}

from src.harness.session import HarnessSession  # noqa: E402

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def kinds(s):
    return [e.get("kind") for e in s.log.store.snapshot()]


def main():
    s = HarnessSession("test-ledger", cwd=ROOT)
    print("== 1. 账本基础（admit/list/discard/to_head + 事件 + 投影）==")
    q1 = s.queue_admit("任务A")
    q2 = s.queue_admit("任务B")
    q3 = s.queue_admit("任务C")
    check("admit ×3 → queue_list 3 条",
          [e["text"] for e in s.queue_list()] == ["任务A", "任务B", "任务C"])
    ks = kinds(s)
    check("事件流 input_admitted ×3",
          ks.count("input_admitted") == 3)
    check("投影 inbox 3 条（id 对齐）",
          sorted(x["id"] for x in s.log.store.projection["inbox"])
          == sorted([q1, q2, q3]))
    check("queue_discard 精确摘除", s.queue_discard(q2, "user") is True
          and [e["text"] for e in s.queue_list()] == ["任务A", "任务C"])
    check("discard 不存在条目返回 False", s.queue_discard("nope") is False)
    check("queue_to_head 提队首", s.queue_to_head(q3) is True
          and [e["text"] for e in s.queue_list()] == ["任务C", "任务A"])

    print("== 2. to_meta 落盘口径（inbox/gen 持久）==")
    m = s.to_meta()
    check("meta 带 inbox 2 条 + gen",
          len(m.get("inbox") or []) == 2 and m.get("gen") == 0)

    print("== 3. 分支世代（#14 /rewind 换代作废旧代）==")
    n_stale = s.bump_generation(reason="rewind")
    check("换代作废 2 条旧代条目", n_stale == 2 and s.queue_list() == [])
    check("作废事件带 reason=rewind",
          any(e.get("kind") == "input_discarded" and e.get("reason") == "rewind"
              for e in s.log.store.snapshot()))
    check("世代号自增", s._gen == 1)
    q4 = s.queue_admit("新代任务")
    check("新代条目正常存活", [e["text"] for e in s.queue_list()] == ["新代任务"])

    print("== 4. 回合终结自动泵（#10）==")
    s._turn_start()
    before = len(s.log.store.snapshot())
    s._turn_end()
    time.sleep(1.6)          # 泵延迟 800ms + 余量
    ks = kinds(s)
    check("回合终结事件已落（turn_started/complete）",
          "turn_started" in ks and "turn_complete" in ks)
    check("泵出队真发（input_promoted）", "input_promoted" in ks)
    # v3.4.54：泵发送失败改回插保命（原「作废+input_discarded」语义废除
    # ——竞态下曾把排队消息吞掉）。无进程会话 send 必失败：断言条目回插
    # 队首、无作废事件
    check("无进程会话发送失败 → 条目回插保命",
          not any(e.get("kind") == "input_discarded"
                  and str(e.get("reason") or "").startswith("发送失败")
                  for e in s.log.store.snapshot())
          and [e["text"] for e in s.queue_list()] == ["新代任务"])
    check("队列不清空（消息保命可见）", len(s.queue_list()) >= 1)

    print("== 5. 子代理镜像（#12）==")
    s._emit_task_mirror({"subtype": "task_started", "tool_use_id": "tu9",
                         "subagent_type": "reviewer", "description": "审计拆分",
                         "is_backgrounded": False, "task_id": "ag9"})
    s._emit_task_mirror({"subtype": "task_notification", "tool_use_id": "tu9",
                         "status": "completed", "summary": "PASS",
                         "usage": {"total_tokens": 4200, "tool_uses": 3},
                         "task_id": "ag9"})
    snap = s.log.store.snapshot()
    st = [e for e in snap if e.get("kind") == "subagent_started"]
    sr = [e for e in snap if e.get("kind") == "subagent_result"]
    check("镜像事件成对落流",
          len(st) == 1 and len(sr) == 1 and st[0]["agent_type"] == "reviewer")
    a = s.log.store.projection["agents"].get("tu9")
    check("镜像驱动 agents 投影收尾",
          a and a["done"] is True and a["err"] is False
          and a["tokens"] == 4200 and a["tool_n"] == 3)

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：")
        for n in _FAIL:
            print("  -", n)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
