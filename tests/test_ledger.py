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

    # == 4.5 order 重排 + 落盘断言（v3.5.109 designer P1——order 被 400 拦死
    # 3 年未暴露的根因是路由级零语义覆盖；本段直连 session.queue_order +
    # meta 记录器钉住「重排生效且落盘」）==
    print("== 4.5 order 重排（v3.5.109 designer P1）==")
    saves = {"n": 0}
    _real_meta_save = S._meta_save
    S._meta_save = lambda: saves.__setitem__("n", saves["n"] + 1)
    try:
        while s.queue_list():   # 清场：第 4 节泵用例残留的「新代任务」
            s.queue_discard(s.queue_list()[0]["id"], "test")
        s.queue_admit("甲"); s.queue_admit("乙"); s.queue_admit("丙")
        ids3 = [e["id"] for e in s.queue_list()]          # [甲, 乙, 丙]
        out = s.queue_order([ids3[2], ids3[0], ids3[1]])  # 丙,甲,乙
        check("order 重排生效", [e["text"] for e in s.queue_list()]
              == ["丙", "甲", "乙"])
        check("order 返回权威 id 序", out == [e["id"] for e in s.queue_list()])
        check("order 落盘（meta inbox 序=内存序）",
              [x["id"] for x in (S._meta.get("test-ledger") or {}).get("inbox") or []]
              == out and saves["n"] > 0)
        n0 = saves["n"]
        out2 = s.queue_order([ids3[2], "ghost-id", ids3[1]])   # 含不存在 id
        check("order ghost id 忽略不炸、其余保序",
              [e["text"] for e in s.queue_list()] == ["丙", "乙", "甲"]
              and "ghost-id" not in out2)
        out3 = s.queue_order([ids3[1], ids3[1], ids3[0]])      # 重复 id
        check("order 重复 id 首现生效不复制",
              len(s.queue_list()) == 3
              and [e["text"] for e in s.queue_list()] == ["乙", "甲", "丙"])
        out4 = s.queue_order([ids3[2]])                        # 只列一条
        rest = [e["text"] for e in s.queue_list()]
        # 未列出（甲、乙）按**当前账本序**（上一轮结果 [乙,甲,丙] 去丙）追加尾
        check("order 未列出条目按当前账本相对序追加尾",
              rest == ["丙", "乙", "甲"], str(rest))
        s.queue_order(ids3)                                    # 还原时间序
        # to_head 落盘口径：队首不动不落、移动落
        head_id = s.queue_list()[0]["id"]
        n1 = saves["n"]
        check("to_head 已在队首不动不落 meta",
              s.queue_to_head(head_id) is True and saves["n"] == n1)
        s.queue_admit("丁")
        n2 = saves["n"]
        check("to_head 提队首落 meta",
              s.queue_to_head(s.queue_list()[-1]["id"]) is True
              and saves["n"] == n2 + 1)
    finally:
        S._meta_save = _real_meta_save

    # == 4.6 order→泵端到端（designer P1：_PUMP_DELAY 注入秒级驱动，
    # 断言泵取重排后队首）==
    print("== 4.6 order→泵端到端（_PUMP_DELAY 注入）==")
    s._PUMP_DELAY = 0.05
    sent = []
    _real_send = s.send_message
    s.send_message = lambda text, imgs=None, fls=None: (
        sent.append(text), (True, None))[1]
    try:
        while s.queue_list():   # 清场
            s.queue_discard(s.queue_list()[0]["id"], "test")
        # 第 4 节泵失败重试挂的 3s timer 仍在链上——不清标记则 _arm CAS
        # 让位，本节 0.05s 的新链永远挂不上（首跑实锤 sent=[] 的根因）
        s._pump_timer = None
        s.queue_admit("E1"); s.queue_admit("E2"); s.queue_admit("E3")
        idsE = [e["id"] for e in s.queue_list()]
        s.queue_order([idsE[2], idsE[0], idsE[1]])            # E3,E1,E2
        s._turn_start()
        s._turn_end()
        time.sleep(0.4)                                       # 0.05 泵延迟 ×8 余量
        ks = kinds(s)
        prom = [e for e in s.log.store.snapshot()
                if e.get("kind") == "input_promoted"]
        check("泵按重排后队首真发（E3 先发）",
              sent[:1] == ["E3"] and len(prom) >= 1
              and prom[-1].get("id") == idsE[2],
              "sent=%r promN=%d busy=%s" % (sent, len(prom), s.busy))
        check("泵单发出队后剩余保序",
              [e["text"] for e in s.queue_list()] == ["E1", "E2"],
              str([e["text"] for e in s.queue_list()]))
    finally:
        s.send_message = _real_send
        s._pump_timer = None          # 防第 4 节旧 timer 迟到空转/误发
        s._PUMP_DELAY = 0.8           # v3.5.110（补审低2）：还原，防后续节静默快泵
        while s.queue_list():         # 清场给第 5 节
            s.queue_discard(s.queue_list()[0]["id"], "test")

    # == 4.7 识图文案防回退（v3.5.109 designer P3，锚 v3.5.107 泛化口径）：
    # 具体 mcp__ 工具名只允许作例举且必须带「并非所有环境」类限定；泛化
    # 判断措辞（识图类工具/按工具描述）必须在场——写死回潮时这里变红。
    # v3.5.110（补审一般1）封闭：猴补 _vision_load/_model_vision_mode——
    # vision_bridge_text 内部走 _vision_load() 读真实用户 config（本机
    # enabled=True 过、默认环境必红）+ mm_user 判态漂移，不封闭则结果随
    # 机器配置漂移，违背本文件「不碰真实用户数据」铁律
    print("== 4.7 识图文案防回退（designer P3）==")
    import src.harness.bridges as _B
    _r_vl, _r_vm = _B._vision_load, _B._model_vision_mode
    _B._vision_load = lambda: {"enabled": True, "model": "glm-5.3",
                               "mcp_prompt": "", "mm_extra": [], "mm_user": {}}
    _B._model_vision_mode = lambda m: "mcp"
    try:
        _t = _B.vision_bridge_text("glm-5.3")
        check("bridge 兜底泛化措辞在场（识图类工具+限定语）",
              "识图类工具" in _t and "并非所有环境都有" in _t)
        from src.harness.vision_mcp import _TOOLS as _VT
        _d = (_VT[0].get("description") or "") if _VT else ""
        check("本地识图工具 description 泛化措辞在场",
              "识图类工具" in _d and "部分网关内建" in _d)
    finally:
        _B._vision_load, _B._model_vision_mode = _r_vl, _r_vm

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
