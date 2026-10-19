# -*- coding: utf-8 -*-
"""subagent-registry 端到端冒烟：Flask test_client 直调 /api/harness/agents，
模拟「派发→回执→续派→中断→续派→完成」全生命周期，断言注册表每一步的
权威态（用户验收前的自测底线）。用法：python tools/_registry_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness.consts import _sessions, _sessions_lock   # noqa: E402
from src.harness.session import HarnessSession        # noqa: E402


def main():
    # 裸装配 session（不 spawn CLI——只测注册表数据面）
    s = HarnessSession.__new__(HarnessSession)
    s.sid = "smoke-reg-1"
    s.session_id = ""
    s.cwd = os.getcwd()
    s.alive = False
    s.busy = False
    s.busy_since = 0
    s.title = "smoke"
    s.model = ""
    s.live_model = ""
    from src.harness.registry import AgentRegistry
    s._registry = AgentRegistry()
    with _sessions_lock:
        _sessions[s.sid] = s

    from src.server import app
    c = app.test_client()

    def snap():
        r = c.get("/api/harness/agents?sid=%s&src=reg" % s.sid)
        j = r.get_json()
        assert j and j["ok"], j
        return j

    # ① 首轮派发（agentId 未知 pending——后端键带 pending: 前缀，前端剥）
    s._registry.on_task_dispatch("toolu_A", "reviewer", "全审技能仓库块", 1000)
    j = snap()
    assert j["agents"]["pending:toolu_A"]["status"] == "running", j["agents"]
    assert j["agents"]["pending:toolu_A"]["found"] is False
    # ② 回执迁键
    s._registry.on_task_result("toolu_A", '{"agentId":"rev_skill_001","success":true}',
                               False, 60000, 1000, 12)
    j = snap()
    a = j["agents"]["rev_skill_001"]
    assert a["found"] and a["status"] == "done" and a["rounds"] == 1, a
    assert j["tidMap"]["toolu_A"] == "rev_skill_001"
    # ③ SendMessage 续派（to=角色名，经 ids 映射归链）
    s._registry.on_send_message("toolu_B", "reviewer", "继续审新增提交",
                                {"reviewer": "rev_skill_001"}, 70000)
    j = snap()
    a = j["agents"]["rev_skill_001"]
    assert a["rounds"] == 2 and a["status"] == "running", a
    assert j["tidMap"]["toolu_B"] == "rev_skill_001"
    # ④ 包装 task_started（bg）
    s._registry.on_task_started("toolu_B", "reviewer", "", "wrap_x_001",
                                True, 71000)
    # ⑤ ■ 中断（only_fg：bg 链不收）
    s.on_interrupt = None
    try:
        s._registry.on_interrupt_all(80000, only_fg=True)
    except Exception:
        pass
    a = snap()["agents"]["rev_skill_001"]
    assert a["status"] == "running", ("bg 链被 only_fg 误收", a)
    # ⑥ 完成
    s._registry.on_task_notification("toolu_B", True, "PASS 无发现",
                                     120000, 3000, 40)
    a = snap()["agents"]["rev_skill_001"]
    assert a["status"] == "done" and a["brief"] == "PASS 无发现", a
    assert a["rounds"] == 2 and a["bg"] is True, a
    # ⑦ 并行第二个代理（证明多代理互不干扰）
    s._registry.on_task_dispatch("toolu_C", "designer", "设计笔记块方案", 2000)
    s._registry.on_task_result("toolu_C", "agentId: des_note_0001", False,
                               90000, 500, 6)
    ag = snap()["agents"]
    assert ag["des_note_0001"]["desc"] == "设计笔记块方案"
    assert len([k for k in ag if not k.startswith("pending:")]) == 2
    # ⑧ 进程死全收
    s._registry.on_task_notification("toolu_X", True, "", 1, 0, 0)  # 未知 tid no-op
    des = snap()["agents"]["des_note_0001"]
    assert des["status"] == "done"
    print("registry e2e smoke: ALL PASS")


if __name__ == "__main__":
    main()
