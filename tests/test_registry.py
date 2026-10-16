# -*- coding: utf-8 -*-
"""subagent-registry 注册表单测（全审 F1/F2/F4/F5 回归网）。

直跑式（与 test_bg_hold 同风格）：python tests/test_registry.py
覆盖：ids 生产方向（agentId→角色，session._registry_feed 反转后归链）、
pending 迁键删除（鬼影绝迹）、未派发 tid 的 result 不铸幻影、
SendMessage 回执不落终态（resumedAgentId 归链兜底）、wrapper task_started
不建 found 条目、中断语义、重建 merge/ts 契约。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness.registry import (AgentRegistry, rebuild_from_transcript,  # noqa: E402
                                  _ts_ms)

_PASS = 0


def ok(name, cond, detail=""):
    global _PASS
    assert cond, "FAIL: %s %s" % (name, detail)
    _PASS += 1
    print("  PASS %s" % name)


def test_ids_direction_f1():
    """F1：生产 ids 表方向（agentId→角色）经反转后归链双向形态。"""
    r = AgentRegistry()
    r.on_task_dispatch("tA", "reviewer", "全审A", 1000)
    r.on_task_result("tA", '{"agentId":"rev_00000001","success":true}', False, 2000, 0, 0)
    # 生产方向快照（session._registry_feed 反转前的形态）
    prod_ids = {"rev_00000001": "reviewer"}
    flipped = {}
    for aid, role in prod_ids.items():
        flipped[role] = aid
    # ① to=角色名（反转表命中）
    r.on_send_message("tB", "reviewer", "继续审", flipped, 3000)
    a = r.snapshot()["agents"]["rev_00000001"]
    ok("F1-角色名续派归链", a["rounds"] == 2 and a["status"] == "running", a)
    ok("F1-tidMap", r.snapshot()["tidMap"].get("tB") == "rev_00000001")
    # ② to=agentId 直连（to 在现有键）
    r.on_task_notification("tB", True, "done", 4000, 0, 0)
    r.on_send_message("tC", "rev_00000001", "第三轮", flipped, 5000)
    a = r.snapshot()["agents"]["rev_00000001"]
    ok("F1-agentId直连归链", a["rounds"] == 3 and a["status"] == "running", a)
    ok("F1-无角色名幻影", "reviewer" not in r.snapshot()["agents"])


def test_pending_cleanup_f2():
    """F2：迁键删 pending（鬼影绝迹）。"""
    r = AgentRegistry()
    r.on_task_dispatch("tT", "Task", "前台任务", 1000)
    r.on_task_result("tT", "agentId: exp_00000002", False, 60000, 0, 0)
    j = r.snapshot()["agents"]
    ok("F2-迁键删pending", "pending:tT" not in j, list(j.keys()))
    ok("F2-终态落真键", j["exp_00000002"]["status"] == "done")
    # task_started 迁键路径同款
    r2 = AgentRegistry()
    r2.on_task_dispatch("tU", "Explore", "探查", 100)
    r2.on_task_started("tU", "Explore", "", "exp_00000003", True, 200)
    j2 = r2.snapshot()["agents"]
    ok("F2-started迁键删pending", "pending:tU" not in j2 and
       j2["exp_00000003"]["desc"] == "探查", j2)


def test_no_phantom_f4():
    """F4：未派发 tid 的 tool_result 不铸幻影；SendMessage 回执不落终态。"""
    r = AgentRegistry()
    r.on_task_result("bash_tid_1", "cannot find agentId foobar12345 in config",
                     False, 1000, 0, 0)
    ok("F4-Bash散文不铸幻影", "foobar12345" not in r.snapshot()["agents"])
    # SendMessage 回执：送达确认≠完成
    r.on_task_dispatch("tD", "reviewer", "审X", 1000)
    r.on_task_result("tD", '{"agentId":"rev_00000004","success":true}', False, 2000, 0, 0)
    r.on_send_message("tE", "rev_00000004", "续派", {}, 3000)
    r.on_task_result("tE", '{"resumedAgentId":"rev_00000004","success":true}',
                     False, 3500, 0, 0)
    a = r.snapshot()["agents"]["rev_00000004"]
    ok("F4-SM回执不落终态", a["status"] == "running", a)
    # 归链失败的 SM（跨会话）回执 resumedAgentId → 轻条目（转写同源事实）
    r.on_send_message("tF", "outer_agent_99", "跨会话", {}, 4000)
    r.on_task_result("tF", '{"resumedAgentId":"outer_agent_99","success":true}',
                     False, 4500, 0, 0)
    a2 = r.snapshot()["agents"].get("outer_agent_99")
    ok("F4-跨会话回执兜底建轮", a2 and a2["rounds"] == 1 and
       a2["status"] == "running", a2)


def test_wrapper_no_phantom_f5():
    """F5：无 pending 无链的 task_started 不建 **found=True** 条目（wrapper
    幻影=目录第二个子代理——绝迹）。孤立 task_started 允许 pending 乱序
    兜底（found:false 前端不进目录不回放，tool_use 帧到达后收编/迁键）。"""
    r = AgentRegistry()
    r.on_task_started("wrap_tid_1", "reviewer", "", "wrap_id_9999", True, 1000)
    j = r.snapshot()["agents"]
    ok("F5-wrapper不建found条目", "wrap_id_9999" not in j
       and not any(v.get("found") for v in j.values()), j)
    # SM 包装形态（send 帧在先）：task_started 不建 pending（sm_tids 拦）
    r2 = AgentRegistry()
    r2.on_task_dispatch("tP", "reviewer", "首轮", 100)
    r2.on_task_result("tP", "agentId: rev_00000009", False, 200, 0, 0)
    r2.on_send_message("tQ", "rev_00000009", "续", {}, 300)
    r2.on_task_started("tQ", "reviewer", "", "wrap_id_8888", True, 400)
    j2 = r2.snapshot()["agents"]
    ok("F5-SM包装无pending鬼影", "pending:tQ" not in j2
       and j2["rev_00000009"]["rounds"] == 2, j2)
    # 有 pending 的直派 task_started 迁键 ✓（F2 已测）


def test_interrupt_semantics():
    """中断语义：only_fg 不收 bg；进程死全收。"""
    r = AgentRegistry()
    r.on_task_dispatch("tG", "reviewer", "bg审", 1000)
    r.on_task_result("tG", "agentId: rev_00000005", False, 2000, 0, 0)
    r.on_send_message("tH", "rev_00000005", "续", {}, 3000)
    r.on_task_started("tH", "reviewer", "", "w1", True, 3100)   # bg=True
    r.on_interrupt_all(4000, only_fg=True)
    ok("中断-bg不收", r.snapshot()["agents"]["rev_00000005"]["status"] == "running")
    r.on_interrupt_all(5000, only_fg=False)
    ok("中断-进程死全收",
       r.snapshot()["agents"]["rev_00000005"]["status"] == "interrupted")


def test_rebuild_merge_f7():
    """重建：ts ISO→ms 契约 + merge 保增量。"""
    ok("F7-ts解析", _ts_ms("2026-10-17T08:30:00Z") > 1700000000000)
    ok("F7-ts数字透传", _ts_ms(1729000000000) == 1729000000000)
    ok("F7-ts空兜0", _ts_ms("") == 0)
    reg = rebuild_from_transcript(
        [{"agent": "rev_00000006", "type": "reviewer", "desc": "全审",
          "err": False, "ts": "2026-10-17T08:00:00Z"}],
        [{"result": "resumedAgentId: rev_00000006 ok",
          "input": {"message": "第二轮继续"}, "ts": "2026-10-17T09:00:00Z"}])
    a = reg.snapshot()["agents"]["rev_00000006"]
    ok("F7-轮数", a["rounds"] == 2, a)
    ok("F7-ms契约", isinstance(a["t0"], int) and a["t0"] > 0)
    ok("F7-最新任务名", a["desc"] == "第二轮继续", a)
    # merge 保增量：活注册表 crash 时在跑（回执未达=running 链）→ 进程死
    # 落 interrupted——重建的转写 done/err（若有段行）或整条缺失都不得覆写
    live = AgentRegistry()
    live.on_task_dispatch("tI", "reviewer", "crash时在跑", 1000)
    live.on_task_started("tI", "reviewer", "", "rev_00000006", True, 1500)
    live.on_interrupt_all(9999999999999, only_fg=False)   # 进程死（未来时刻=恒新）
    reg2 = rebuild_from_transcript(
        [{"agent": "rev_00000006", "type": "reviewer", "desc": "全审",
          "err": False, "ts": "2026-10-17T08:00:00Z"}], [])
    live.merge_rebuilt(reg2.snapshot()["agents"], reg2.snapshot()["tidMap"])
    a2 = live.snapshot()["agents"]["rev_00000006"]
    ok("F7-merge保增量interrupted", a2["status"] == "interrupted", a2)


def test_feed_flip_via_session():
    """端到端：session._registry_feed 的 ids 反转（F1 生产路径）。"""
    from src.harness.session import HarnessSession
    s = HarnessSession.__new__(HarnessSession)
    s._audit = {"ids": {"rev_00000007": "reviewer"}}
    s._audit_lock = __import__("threading").Lock()
    from src.harness.registry import AgentRegistry
    s._registry = AgentRegistry()
    # Task 派发+回执（同帧序列走 _registry_feed/_registry_result 形态）
    s._registry_feed({"message": {"content": [
        {"type": "tool_use", "id": "tJ", "name": "Task",
         "input": {"subagent_type": "reviewer", "description": "审Y"}}]}})
    s._registry_result({"message": {"content": [
        {"type": "tool_result", "tool_use_id": "tJ",
         "content": '{"agentId":"rev_00000007","success":true}'}]}})
    # 角色名续派（生产 ids=agentId→角色，feed 内反转）
    s._registry_feed({"message": {"content": [
        {"type": "tool_use", "id": "tK", "name": "SendMessage",
         "input": {"to": "reviewer", "message": "继续审\n细节"}}]}})
    a = s._registry.snapshot()["agents"].get("rev_00000007")
    ok("端到端-角色名归链(session反转)", a and a["rounds"] == 2
       and a["status"] == "running" and a["desc"] == "继续审", a)


def test_full_lifecycle_mainline():
    """复审F2回归网：主生命周期序列（dispatch→task_started→result→
    notification，新 CLI task_id=真实 agentId 形态）——迁键路径丢
    tidMap 的回归恰在此序列（task_started 先迁键、result/notification
    按 tid 反查），每个断言锁死一层。"""
    r = AgentRegistry()
    r.on_task_dispatch("toolu_M", "reviewer", "主序列审", 1000)
    r.on_task_started("toolu_M", "reviewer", "主序列审", "rev_main_0001",
                      True, 1100)
    j1 = r.snapshot()
    ok("主序列-started迁键", "rev_main_0001" in j1["agents"]
       and "pending:toolu_M" not in j1["agents"], list(j1["agents"].keys()))
    ok("主序列-started的tidMap（迁键不丢映射）",
       j1["tidMap"].get("toolu_M") == "rev_main_0001", j1["tidMap"])
    r.on_task_result("toolu_M", '{"agentId":"rev_main_0001","success":true}',
                     False, 60000, 1500, 15)
    r.on_task_notification("toolu_M", True, "PASS 主序列", 61000, 1600, 16)
    j2 = r.snapshot()
    a = j2["agents"]["rev_main_0001"]
    ok("主序列-终态done", a["status"] == "done" and a["doneAt"] == 61000, a)
    ok("主序列-brief/用量", a["brief"] == "PASS 主序列"
       and a["tokens"] == 1600 and a["toolN"] == 16, a)
    ok("主序列-result后tidMap仍在", j2["tidMap"].get("toolu_M") == "rev_main_0001")
    # bg 形态同序列
    r.on_task_dispatch("toolu_N", "Explore", "bg探查", 100)
    r.on_task_started("toolu_N", "Explore", "bg探查", "exp_main_0002",
                      True, 200)
    r.on_task_notification("toolu_N", True, "bg完成", 50000, 100, 5)
    a2 = r.snapshot()["agents"]["exp_main_0002"]
    ok("主序列-bg通知终态", a2["status"] == "done" and a2["brief"] == "bg完成", a2)
    # 旧 CLI wrapper 键孤儿清扫（F5 残留②）
    r2 = AgentRegistry()
    r2.on_task_dispatch("toolu_W", "reviewer", "旧CLI形态", 100)
    r2.on_task_started("toolu_W", "reviewer", "旧CLI形态", "wrap_key_99",
                       False, 200)
    r2.on_task_result("toolu_W", "agentId: rev_true_0003", False, 900, 0, 0)
    j3 = r2.snapshot()
    ok("主序列-wrapper孤儿清扫", "wrap_key_99" not in j3["agents"]
       and j3["agents"]["rev_true_0003"]["status"] == "done", list(j3["agents"].keys()))


if __name__ == "__main__":
    test_ids_direction_f1()
    test_pending_cleanup_f2()
    test_no_phantom_f4()
    test_wrapper_no_phantom_f5()
    test_interrupt_semantics()
    test_rebuild_merge_f7()
    test_feed_flip_via_session()
    test_full_lifecycle_mainline()
    print("========================================================")
    print("registry tests: %d PASS" % _PASS)
