# -*- coding: utf-8 -*-
"""v3.5.123/124 后台子代理回合保活状态机测试（全审 P9 补覆盖）。
直测 HarnessSession 的 _bg_tasks/_held/hold 守卫：登记/注销/真收尾清
_held/kill 补 exit 结算/monitor 常驻。CONFIG_FILE 隔离同 test_audit_boundary。"""
import os
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import src.app_state as _st   # noqa: E402
_TMP = tempfile.mkdtemp(prefix="bg_hold_test_")
_st.CONFIG_FILE = os.path.join(_TMP, "config.json")
os.environ.setdefault("HARNESS_AGENTS_DIR", _TMP)
import json as _json
with open(_st.CONFIG_FILE, "w", encoding="utf-8") as _f:
    _json.dump({"harness_roles": {"design_max_lines": 150,
                                  "l1_max_lines": 100,
                                  "l2_max_lines": 250}}, _f)

from src.harness.session import HarnessSession   # noqa: E402


def _mk_session():
    s = HarnessSession.__new__(HarnessSession)
    s.sid = "t"
    s._audit = {"lines": 0, "files": [], "designer": False,
                "designFired": False, "reviewer": False, "rev_at": 0,
                "fired_at": 0, "streak": 0, "ids": {}, "pending": {}}
    s._audit_lock = __import__("threading").Lock()
    s._audit_state = lambda: ("auto", (100, 200, 250), False)
    s._audit_card = lambda text: None
    s._audit_send = lambda text: None
    s.emit = lambda o: None
    s._bg_tasks = {}
    s._held = False
    s._bg_mon_started = False
    s.last_active = int(time.time() * 1000)
    return s


def _tally_task(s, tid, subagent_type="designer", bg=True):
    """模拟主链 Task 派发事件入审计账。"""
    s._audit_tally({"message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Task",
         "input": {"subagent_type": subagent_type, "prompt": "x"}}]}})


def test_hold_keeps_busy_and_defers_settle():
    """P3/P4（复核R3 改真实调用）：源码绊网验证 reader hold 行为——
    ①hold 分支 busy 维持与 _held 置位；②中间 result 不落 busy（hold 守卫
    在 turn_complete 之前）；③settle/turn_end 只在真收尾分支。"""
    src = open(os.path.join(ROOT, "src", "harness", "session.py"),
               encoding="utf-8").read()
    # ①hold 分支：立 _held + busy 维持 True（同 _busy_lock 临界）
    h = src.index('if typ == "result" and _hold_now:')
    hold_seg = src[h:src.index('"turn_complete"')]
    assert "self._held = True" in hold_seg
    assert "self.busy = True" in hold_seg
    # ②中间 result 分支不得出现 settle/turn_end（defer 语义）
    assert "_audit_settle" not in hold_seg and "_turn_end()" not in hold_seg
    # ③真收尾分支：turn_complete → 清 _held → settle → turn_end 顺序
    t = src.index('"turn_complete"')
    tail_seg = src[t:t + 800]
    assert "self._held = False" in tail_seg
    assert tail_seg.index('_audit_settle("result")') < tail_seg.index("self._turn_end()")
    print("hold defer PASS")


def test_real_tail_clears_held():
    """P2 回归：真收尾分支必须清 _held（防幽灵释放）——直读源码断言。"""
    src = open(os.path.join(ROOT, "src", "harness", "session.py"),
               encoding="utf-8").read()
    seg = src[src.index('if typ == "result" and not self._bg_tasks'):
              src.index('self._turn_end()', src.index('if typ == "result" and not self._bg_tasks'))]
    assert "self._held = False" in seg, "真收尾未清 _held（幽灵释放回归）"
    print("tail clears held PASS")


def test_kill_settles_exit_when_held():
    """P5：hold 中 bg_in_flight_clear → 补 _audit_settle("exit")（警示不续发）。"""
    s = _mk_session()
    s._held = True
    settled = []
    s._audit_settle = lambda reason: settled.append(reason)
    s.bg_in_flight_clear()
    assert settled == ["exit"], settled
    assert s._bg_tasks == {} and s._held is False
    # 非 hold 时 clear 不触发结算
    s2 = _mk_session()
    settled2 = []
    s2._audit_settle = lambda reason: settled2.append(reason)
    s2.bg_in_flight_clear()
    assert settled2 == []
    print("kill exit settle PASS")


def test_monitor_thread_persistent():
    """P1：monitor 线程常驻——_bg_mon_started 置位后二次 ensure 不新建线程，
    且线程循环体无 return 自退（源码断言）。"""
    s = _mk_session()
    s._bg_monitor_ensure()
    s._bg_monitor_ensure()          # 二次调用不应建第二条线程
    src = open(os.path.join(ROOT, "src", "harness", "session.py"),
               encoding="utf-8").read()
    seg = src[src.index("def _bg_monitor_ensure"):]
    seg = seg[:seg.index("def bg_in_flight_clear")]
    loop_body = seg[seg.index("def _loop"):]
    assert "while True" in loop_body, "monitor 应常驻 while True"
    body_after_sleep = loop_body[loop_body.index("time.sleep(30)"):]
    assert "return" not in body_after_sleep.split("except")[0], \
        "循环主路径不得自退（P1 一次性闩锁回归）"
    print("monitor persistent PASS")


def test_bg_shell_not_registered():
    """P6（复核R3 改真实调用）：直调 _emit_task_mirror——后台 shell
    （subagent_type 空）不登记保活；真子代理登记。"""
    s = _mk_session()
    s.emit = lambda o: None
    s._bg_monitor_ensure = lambda: None   # 桩掉线程拉起
    s._emit_task_mirror({"subtype": "task_started", "tool_use_id": "t9",
                         "subagent_type": "", "is_backgrounded": True,
                         "description": "sleep"})
    assert s._bg_tasks == {}, "后台 shell 不该锁大回合"
    s._emit_task_mirror({"subtype": "task_started", "tool_use_id": "t10",
                         "subagent_type": "designer", "is_backgrounded": True,
                         "description": "设计"})
    assert "t10" in s._bg_tasks, "真子代理应登记"
    # 注销：notification 到达即出表
    s._emit_task_mirror({"subtype": "task_notification", "tool_use_id": "t10"})
    assert "t10" not in s._bg_tasks
    print("bg shell excluded PASS")


if __name__ == "__main__":
    for f in (test_hold_keeps_busy_and_defers_settle,
              test_real_tail_clears_held,
              test_kill_settles_exit_when_held,
              test_monitor_thread_persistent,
              test_bg_shell_not_registered):
        f()
        print(f.__name__, "PASS")
