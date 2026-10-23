# -*- coding: utf-8 -*-
"""冷查询投影单测（test_registry.py 的场景知识换芯迁移 + 磁盘形态集成）。

直跑：python tests/test_projection.py
覆盖（历史实锤场景全保留，API 从钩子调用改为事实表+project）：
bg ACK 不落终态/notify 权威终态/前台 result 终态/cancel 正则→interrupted/
lost 映射（证据不足不装 done）/SendMessage 轮次归链+desc 更新/跨会话纯
续派/wrapper 幻影缺席（无 dispatch 的 task_id 永不成条目）/pending 窗口/
尾探 mid_flight vs 终局/集合进 collect_main_facts 的磁盘形态集成。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness.subagent_projection import (  # noqa: E402
    collect_main_facts, child_outcome_from_tail, project, _ts_ms)

_PASS = 0


def ok(name, cond, detail=""):
    global _PASS
    assert cond, "FAIL: %s %s" % (name, detail)
    _PASS += 1
    print("  PASS %s" % name)


# ---- 造行工具（2026-10-19 实测磁盘形态）----

def asst(tid, name, inp, ts="2026-10-19T08:00:00Z"):
    return json.dumps({"type": "assistant", "timestamp": ts,
                       "message": {"content": [
                           {"type": "tool_use", "id": tid, "name": name,
                            "input": inp}]}}, ensure_ascii=False)


def res(tid, text, err=False, ts="2026-10-19T08:01:00Z"):
    return json.dumps({"type": "user", "timestamp": ts,
                       "message": {"content": [
                           {"type": "tool_result", "tool_use_id": tid,
                            "content": text, "is_error": err}]}},
                      ensure_ascii=False)


def notify_xml(tid, task_id, status, summary="", ts="2026-10-19T08:05:00Z"):
    xml = ("<task-notification><task-id>%s</task-id><tool-use-id>%s</tool-use-id>"
           "<status>%s</status><summary>%s</summary></task-notification>"
           % (task_id, tid, status, summary))
    return json.dumps({"type": "user", "timestamp": ts,
                       "origin": {"kind": "task-notification"},
                       "message": {"content": xml}}, ensure_ascii=False)


LV = {"proc_alive": True, "busy": True, "now_ms": 1792374000000,
      "child_fresh": {}}


def test_bg_ack_not_final():
    """A1 根因：后台 ACK（启程确认）不落终态；notify 才是权威终态。"""
    lines = [
        asst("t1", "Task", {"subagent_type": "Explore",
                             "description": "后台探查", "run_in_background": True}),
        res("t1", "Task agentId: exp_bg_0001 (internal ID) started in background"),
    ]
    facts = collect_main_facts(lines)
    p = project(facts, liveness=LV)
    a = p["agents"]["exp_bg_0001"]
    ok("bg回执不落终态", a["status"] == "running" and a["doneAt"] == 0, a)
    ok("bg标记", a.get("bg") is True and a["desc"] == "后台探查", a)
    ok("tidMap", p["tidMap"].get("t1") == "exp_bg_0001", p["tidMap"])
    # notify 到达落终态+brief
    facts2 = collect_main_facts(lines + [
        notify_xml("t1", "exp_bg_0001", "completed", "bg真完成")])
    a2 = project(facts2, liveness=LV)["agents"]["exp_bg_0001"]
    ok("notify权威终态", a2["status"] == "done" and a2["brief"] == "bg真完成", a2)
    # 全审G3补齐：notify(ENDED1)路径同样消费 child usage（常规完成路径）
    a2u = project(facts2, liveness=LV, child_states={"exp_bg_0001": {
        "terminal": True, "status": "done", "summary": "bg真完成",
        "endedAt": 90000, "lastActive": 90000,
        "tokens": 999, "toolN": 3}})["agents"]["exp_bg_0001"]
    ok("G3补齐-notify路径usage", a2u["tokens"] == 999 and a2u["toolN"] == 3, a2u)


def test_fg_result_final():
    """前台 Task：result=真终态（done/err）；cancel 正则→interrupted。"""
    lines = [
        asst("t2", "Task", {"subagent_type": "reviewer", "description": "前台审"}),
        res("t2", '{"agentId":"rev_fg_0001"} 结论 PASS'),
    ]
    a = project(collect_main_facts(lines), liveness=LV)["agents"]["rev_fg_0001"]
    ok("前台回执终态", a["status"] == "done" and a["brief"].find("PASS") >= 0, a)
    lines_e = [
        asst("t3", "Task", {"subagent_type": "reviewer", "description": "前台败"}),
        res("t3", '{"agentId":"rev_fg_0002"} aborted by user', err=True),
    ]
    a2 = project(collect_main_facts(lines_e), liveness=LV)["agents"]["rev_fg_0002"]
    ok("cancel正则interrupted", a2["status"] == "interrupted", a2)
    lines_e2 = [
        asst("t4", "Task", {"subagent_type": "reviewer", "description": "前台败2"}),
        res("t4", '{"agentId":"rev_fg_0003"} TypeError: bad', err=True),
    ]
    a3 = project(collect_main_facts(lines_e2), liveness=LV)["agents"]["rev_fg_0003"]
    ok("非cancel错误err", a3["status"] == "err", a3)


def test_send_rounds_and_name():
    """SendMessage 归链：轮数/翻 running/任务名保持原派发名。

    a93S（用户定调「sendmessage 这种名就不应该存在，就应该是原封不动的
    子代理代理名」）：续派**不改名**——desc 保持首轮派发任务名，消息首行
    只在原档无名时兜底（曾覆写成超长消息首行，顶爆胶囊/目录/卡片）。
    """
    lines = [
        asst("t5", "Task", {"subagent_type": "reviewer", "description": "首轮审"}),
        res("t5", '{"agentId":"rev_sm_0001"} PASS'),
        asst("t6", "SendMessage", {"to": "rev_sm_0001",
                                   "message": "继续审第二轮\n细节"}),
        res("t6", '{"success":true,"resumedAgentId":"rev_sm_0001"}'),
    ]
    p = project(collect_main_facts(lines), liveness=LV)
    a = p["agents"]["rev_sm_0001"]
    ok("续派归链建轮", a["rounds"] == 2 and a["status"] == "running", a)
    ok("任务名保持原派发名", a["desc"] == "首轮审", a)
    ok("sm回执非终态", a["doneAt"] == 0, a)
    # 角色名归链（external_ids）
    lines_r = [
        asst("t7", "SendMessage", {"to": "reviewer", "message": "第三轮"}),
    ]
    p2 = project(collect_main_facts(lines), liveness=LV)  # 先建条目
    p3 = project(collect_main_facts(lines + lines_r), liveness=LV,
                 external_ids={"reviewer": "rev_sm_0001"})
    a3 = p3["agents"]["rev_sm_0001"]
    ok("角色名归链", a3["rounds"] == 3 and a3["desc"] == "首轮审", a3)


def test_notify_status_map():
    """notification status 词表：failed→err / stopped→interrupted / 未知→done。"""
    base = [
        asst("t8", "Task", {"subagent_type": "Explore", "description": "词表",
                            "run_in_background": True}),
        res("t8", "agentId: exp_map_0001 started"),
    ]
    f = collect_main_facts(base)
    for st, want in (("failed", "err"), ("stopped", "interrupted"),
                     ("cancelled", "interrupted"), ("weird_value", "done")):
        a = project(collect_main_facts(base + [notify_xml(
            "t8", "exp_map_0001", st)]), liveness=LV)["agents"]["exp_map_0001"]
        ok("notify词表-%s" % st, a["status"] == want, (st, a))


def test_lost_and_interrupted():
    """证据不足不装 done：进程死→interrupted+lost；前台无 result 且回合越界
    →interrupted+lost（健康 CLI 必写 result，缺失=中断）。"""
    lines = [
        asst("t9", "Task", {"subagent_type": "Explore", "description": "孤儿bg",
                            "run_in_background": True}),
        res("t9", "agentId: exp_lost_001 started"),
    ]
    a = project(collect_main_facts(lines),
                liveness=dict(LV, proc_alive=False))["agents"]["exp_lost_001"]
    ok("进程死interrupted+lost", a["status"] == "interrupted"
       and a.get("lost") is True, a)
    lines2 = [
        asst("t10", "Task", {"subagent_type": "Explore", "description": "前台丢"}),
    ]
    a2 = project(collect_main_facts(lines2),
                 liveness=dict(LV, busy=False))["agents"].get("pending:t10")
    ok("前台缺result越界interrupted", a2 and a2["status"] == "interrupted"
       and a2.get("lost") is True, a2)
    # 同场景进程活+busy → 保持 running（**派发在途**：无任何回执——用户
    # 实锤「活着 12 个」修复后仅剩此形态允许 busy 中 running）
    a3 = project(collect_main_facts(lines2), liveness=LV)["agents"]["pending:t10"]
    ok("busy中派发在途保持running", a3["status"] == "running", a3)


def test_stale_midflight_not_running():
    """用户实锤「活着 12 个」回归网（2026-10-19）：转写尾 [tool_use,
    tool_result]（完成但无终局行——常见落盘形态）+ 转写停更 = 残影，
    进程活/busy 都不得判 running。"""
    # 形态①：ACK 回执（dispatch 未带 bg 但文本自证后台）+ 尾探 mid_flight
    # 停更 → interrupted+lost
    lines = [
        asst("tV", "Task", {"subagent_type": "Explore", "description": "残影"}),
        res("tV", "Async agent launched successfully. (This tool result is "
                  "interim — the agent is still running)"),
    ]
    stale_co = {"terminal": False, "status": "", "summary": "",
                "endedAt": 0, "lastActive": 1}   # lastActive 距今极远=停更
    a = project(collect_main_facts(lines), liveness=LV,
                child_states={"resid_0001": stale_co},
                external_links={"tV": "resid_0001"})["agents"].get("resid_0001")
    ok("残影-ACK回执+尾停更=interrupted",
       a and a["status"] == "interrupted" and a.get("lost") is True, a)
    # 形态②：bg=True + 转写停更（周五 reviewer 形态）→ interrupted
    lines2 = [
        asst("tW", "Task", {"subagent_type": "reviewer", "description": "旧bg",
                            "run_in_background": True}),
        res("tW", "Task agentId: resid_0002 started in background"),
    ]
    a2 = project(collect_main_facts(lines2), liveness=LV,
                 child_states={"resid_0002": stale_co},
                 external_links={"tW": "resid_0002"})["agents"].get("resid_0002")
    ok("残影-bg+转写停更=interrupted",
       a2 and a2["status"] == "interrupted", a2)
    # 形态③：send 续派轮回执已到（send_result）+ 尾停更 → interrupted
    lines3 = [
        asst("tX", "Task", {"subagent_type": "reviewer", "description": "首轮"}),
        res("tX", '{"agentId":"resid_0003"} PASS'),
        asst("tY", "SendMessage", {"to": "resid_0003", "message": "第二轮"}),
        res("tY", '{"resumedAgentId":"resid_0003"}'),
    ]
    a3 = project(collect_main_facts(lines3), liveness=LV,
                 child_states={"resid_0003": stale_co},
                 external_links={"tX": "resid_0003"})["agents"].get("resid_0003")
    ok("残影-续派轮回执+尾停更=interrupted",
       a3 and a3["status"] == "interrupted" and a3["rounds"] == 2, a3)
    # 反向护栏：尾探新鲜（lastActive=now）的 mid_flight 仍 running（真在跑）
    fresh_co = dict(stale_co, lastActive=1792396800000)
    LVf = dict(LV, now_ms=1792396800000 + 30000)
    a4 = project(collect_main_facts(lines), liveness=LVf,
                 child_states={"resid_0004": fresh_co},
                 external_links={"tV": "resid_0004"})["agents"].get("resid_0004")
    ok("护栏-尾探新鲜mid_flight仍running",
       a4 and a4["status"] == "running", a4)


def test_child_tail_outcome():
    """尾探：mid_flight（最后 assistant 带 tool_use）vs 终局 text。"""
    mid = [
        json.dumps({"type": "assistant", "timestamp": "2026-10-19T08:00:01Z",
                    "message": {"content": [
                        {"type": "text", "text": "我先看看"},
                        {"type": "tool_use", "id": "x1", "name": "Read",
                         "input": {}}]}}),
    ]
    co = child_outcome_from_tail(mid)
    ok("尾探mid_flight", not co["terminal"], co)
    done_tail = [
        json.dumps({"type": "user", "timestamp": "2026-10-19T08:00:02Z",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "x1",
                         "content": "ok"}]}}),
        json.dumps({"type": "assistant", "timestamp": "2026-10-19T08:00:03Z",
                    "message": {"content": [
                        {"type": "text", "text": "探查完成结论"}]}}),
    ]
    co2 = child_outcome_from_tail(done_tail)
    ok("尾探终局", co2["terminal"] and co2["status"] == "done"
       and co2["summary"] == "探查完成结论", co2)
    # 顶层 result 行优先
    resl = done_tail + [json.dumps(
        {"type": "result", "timestamp": "2026-10-19T08:00:04Z",
         "is_error": True, "result": "max turns exceeded"})]
    co3 = child_outcome_from_tail(resl)
    ok("顶层result优先", co3["terminal"] and co3["status"] == "err", co3)
    # 全审S1：主流尾部形态 [tool_asst, user, text_asst]（无顶层 result 行）
    # ——最后一条 assistant 是纯文本=终局 done，不得被更早的 tool assistant
    # 误翻 mid_flight
    main_stream = [
        json.dumps({"type": "assistant", "timestamp": "2026-10-19T08:00:01Z",
                    "message": {"content": [
                        {"type": "tool_use", "id": "y1", "name": "Grep",
                         "input": {}}]}}),
        json.dumps({"type": "user", "timestamp": "2026-10-19T08:00:02Z",
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "y1",
                         "content": "hit"}]}}),
        json.dumps({"type": "assistant", "timestamp": "2026-10-19T08:00:03Z",
                    "message": {"content": [
                        {"type": "text", "text": "探查结论在此"}]}}),
    ]
    co4 = child_outcome_from_tail(main_stream)
    ok("S1-终局text不被早tool翻mid_flight",
       co4["terminal"] and co4["status"] == "done"
       and co4["summary"] == "探查结论在此", co4)
    # 全审G3：顶层 result 行 usage 提取
    resu = main_stream + [json.dumps(
        {"type": "result", "timestamp": "2026-10-19T08:00:05Z",
         "usage": {"total_tokens": 4321, "tool_uses": 17}})]
    co5 = child_outcome_from_tail(resu)
    ok("G3-result行usage", co5["tokens"] == 4321 and co5["toolN"] == 17, co5)


def test_s2_receipt_anchors():
    """全审S2：前台回执正文引用「resumedAgentId: xxx」不得误判成
    SendMessage 回执（前台终态被吞+幻影 running+bg 永跑）；ACK 行首锚
    （散文裸 agentId: 不采）。"""
    lines = [
        asst("tS", "Task", {"subagent_type": "general-purpose",
                            "description": "协议文档"}),
        res("tS", "协议字段说明: resumedAgentId: fake_id_99 与 agentId: "
                  "bare_99xx 语义不同。实测结论：完成。"),
    ]
    p = project(collect_main_facts(lines), liveness=LV)
    a = p["agents"]["pending:tS"]
    ok("S2-前台终态不被吞", a["status"] == "done", a)
    ok("S2-无幻影条目", "fake_id_99" not in p["agents"]
       and "bare_99xx" not in p["agents"], list(p["agents"]))
    # 真·后台 ACK（行首）照常提取
    lines2 = [
        asst("tS2", "Task", {"subagent_type": "Explore",
                             "description": "锚验证",
                             "run_in_background": True}),
        res("tS2", "\nagentId: anchor_ok_001 (internal ID)"),
    ]
    a2 = project(collect_main_facts(lines2), liveness=LV)["agents"]
    ok("S2-行首ACK照常提取", a2.get("anchor_ok_001", {}).get("bg") is True, a2)


def test_g4_notify_before_ack():
    """全审G4：ACK 未落盘窗口（dispatch 已 flush 回执没有）——notify 自带
    task_id 直接迁键落终态（对位旧 registry 迁键语义）。"""
    lines = [
        asst("tG", "Task", {"subagent_type": "Explore",
                            "description": "窗口", "run_in_background": True}),
        notify_xml("tG", "exp_g4_0001", "completed", "窗口期完成"),
    ]
    p = project(collect_main_facts(lines), liveness=LV)
    a = p["agents"].get("exp_g4_0001")
    ok("G4-notify先于ACK迁键落终态",
       a and a["status"] == "done" and a["found"] is True
       and p["tidMap"].get("tG") == "exp_g4_0001", (a, p["tidMap"]))
    ok("G4-pending键已迁走", "pending:tG" not in p["agents"], list(p["agents"]))


def test_fresh_and_bg_liveness():
    """RUNNING 1/2：转写新鲜=在跑铁证；bg+进程活=宁跑勿完。"""
    lines = [
        asst("t11", "Task", {"subagent_type": "Explore", "description": "新鲜",
                             "run_in_background": True}),
        res("t11", "agentId: exp_fr_0001 started"),
    ]
    f = collect_main_facts(lines)
    a = project(f, liveness=dict(LV, child_fresh={"exp_fr_0001": True},
                                 proc_alive=False))["agents"]["exp_fr_0001"]
    ok("转写新鲜优先于进程死", a["status"] == "running", a)
    a2 = project(f, liveness=LV)["agents"]["exp_fr_0001"]
    ok("bg进程活宁跑勿完", a2["status"] == "running", a2)
    # 影子对账实锤：进程死后 mid_flight 尾态不可信（历史死代理永停
    # mid_flight——不新鲜+进程死 → interrupted，不得永久 running）
    a3 = project(f, liveness=dict(LV, proc_alive=False),
                 child_states={"exp_fr_0001": {"terminal": False,
                                                "status": "", "summary": "",
                                                "endedAt": 0, "lastActive": 1}}
                 )["agents"]["exp_fr_0001"]
    ok("进程死mid_flight不永跑", a3["status"] == "interrupted", a3)


def test_wrapper_phantom_absent():
    """wrapper 幻影缺席：无 dispatch 事实的 task_id 永不成条目
    （增量法的 F5 病根在无状态投影里构造性消失）。"""
    lines = [notify_xml("unknown_tid_99", "wrap_id_9999", "completed", "x")]
    p = project(collect_main_facts(lines), liveness=LV)
    ok("notify无链不铸条目", "wrap_id_9999" not in p["agents"], list(p["agents"]))
    # 后台 Bash 的 notification（task_id 短 id 非 agentId 形态）同样零条目
    lines2 = [notify_xml("bash_tid_1", "b2gbrm3y6", "completed", "monitor")]
    p2 = project(collect_main_facts(lines2), liveness=LV)
    ok("bash通知零条目", not p2["agents"], p2["agents"])


def test_pending_window_and_links():
    """pending 窗口（dispatch 已 flush、ACK 未 flush）+ meta.json 外链。"""
    lines = [asst("t12", "Task", {"subagent_type": "Explore",
                                  "description": "窗口期"})]
    p = project(collect_main_facts(lines), liveness=LV)
    a = p["agents"]["pending:t12"]
    ok("pending窗口条目", a["status"] == "running" and a["found"] is False, a)
    # external_links（meta.json toolUseId）供 agentId
    p2 = project(collect_main_facts(lines), liveness=LV,
                 external_links={"t12": "exp_meta_001"})
    ok("meta外链迁键", p2["agents"]["exp_meta_001"]["found"] is True, p2)


def test_cross_session_resume():
    """跨会话纯续派：send_result 的 resumedAgentId 独立建条目。"""
    lines = [
        asst("t13", "SendMessage", {"to": "outer_agent_99",
                                    "message": "跨会话继续"}),
        res("t13", '{"resumedAgentId":"outer_agent_99","success":true}'),
    ]
    p = project(collect_main_facts(lines), liveness=LV)
    a = p["agents"].get("outer_agent_99")
    ok("跨会话续派条目", a and a["rounds"] == 1
       and a["status"] == "running" and a["desc"] == "跨会话继续", a)


def test_ts_and_skip_rules():
    """_ts_ms 契约 + 行跳过规则（子代理链内部行/isMeta 不产事实）。"""
    ok("ts解析", _ts_ms("2026-10-19T08:30:00Z") > 1700000000000)
    ok("ts数字透传", _ts_ms(1729000000000) == 1729000000000)
    lines = [
        json.dumps({"type": "assistant", "timestamp": "2026-10-19T08:00:00Z",
                    "parent_tool_use_id": "pp1",
                    "message": {"content": [
                        {"type": "tool_use", "id": "inner1", "name": "Task",
                         "input": {"description": "子代理内部派发"}}]}}),
        json.dumps({"type": "assistant", "isMeta": True,
                    "timestamp": "2026-10-19T08:00:00Z",
                    "message": {"content": [
                        {"type": "tool_use", "id": "meta1", "name": "Task",
                         "input": {"description": "meta行"}}]}}),
        asst("t14", "Bash", {"command": "ls"}, ts="2026-10-19T08:00:05Z"),
    ]
    ok("内部行零事实", collect_main_facts(lines) == [])


def test_t0_watch_continuity():
    """A1 秒表连续：t0 恒为 dispatch 事实 ts（epoch ms），F5 前后同源同值。"""
    lines = [
        asst("t15", "Task", {"subagent_type": "Explore", "description": "秒表",
                             "run_in_background": True},
             ts="2026-10-19T09:15:23.456Z"),
        res("t15", "agentId: exp_t0_0001 started",
            ts="2026-10-19T09:15:24.1Z"),
    ]
    p1 = project(collect_main_facts(lines), liveness=LV)
    p2 = project(collect_main_facts(lines), liveness=dict(
        LV, now_ms=1792375000000))   # 模拟 F5 后重拉
    a1, a2 = p1["agents"]["exp_t0_0001"], p2["agents"]["exp_t0_0001"]
    ok("t0同源连续", a1["t0"] == a2["t0"] and a1["t0"] > 0, (a1["t0"], a2["t0"]))
    ok("两次投影一致", a1["status"] == a2["status"] == "running")


if __name__ == "__main__":
    test_bg_ack_not_final()
    test_fg_result_final()
    test_send_rounds_and_name()
    test_notify_status_map()
    test_lost_and_interrupted()
    test_stale_midflight_not_running()
    test_child_tail_outcome()
    test_s2_receipt_anchors()
    test_g4_notify_before_ack()
    test_fresh_and_bg_liveness()
    test_wrapper_phantom_absent()
    test_pending_window_and_links()
    test_cross_session_resume()
    test_ts_and_skip_rules()
    test_t0_watch_continuity()
    print("========================================================")
    print("projection tests: %d PASS" % _PASS)
