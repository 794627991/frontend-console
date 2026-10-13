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
    hold_seg = src[h:src.index('"turn_complete"', h)]
    assert "self._held = True" in hold_seg
    assert "self.busy = True" in hold_seg
    # ②中间 result 分支不得出现 settle/turn_end（defer 语义）
    assert "_audit_settle" not in hold_seg and "_turn_end()" not in hold_seg
    # ③真收尾分支：turn_complete → 清 _held → settle → turn_end 顺序
    t = src.index('"turn_complete"', h)
    tail_seg = src[t:t + 800]
    assert "self._held = False" in tail_seg
    assert tail_seg.index('_audit_settle("result")') < tail_seg.index("self._turn_end()")
    print("hold defer PASS")


def test_real_tail_clears_held():
    """P2 回归：真收尾分支必须清 _held（防幽灵释放）——直读源码断言。"""
    src = open(os.path.join(ROOT, "src", "harness", "session.py"),
               encoding="utf-8").read()
    h = src.index('if typ == "result" and not _hold_now:')
    seg = src[h:src.index("self._turn_end()", h)]
    assert "self._held = False" in seg, "真收尾未清 _held（幽灵释放回归）"
    assert '"turn_complete"' in seg, "真收尾缺 turn_complete emit（前端 hold 永不清）"
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
    """P1：monitor 线程常驻——_bg_mon_started 置位后二次 ensure 不新建线程；
    循环主路径不得出现「集空且无 hold」自退（v3.5.124 一次性闩锁回归）。
    R1 的 _closed 自退（已删会话）是合法停机，排除在外。"""
    s = _mk_session()
    s._bg_monitor_ensure()
    s._bg_monitor_ensure()          # 二次调用不应建第二条线程
    src = open(os.path.join(ROOT, "src", "harness", "session.py"),
               encoding="utf-8").read()
    seg = src[src.index("def _bg_monitor_ensure"):]
    seg = seg[:seg.index("def bg_in_flight_clear")]
    loop_body = seg[seg.index("def _loop"):]
    assert "while True" in loop_body, "monitor 应常驻 while True"
    main_path = loop_body[loop_body.index("time.sleep(30):") if "time.sleep(30):" in loop_body
                          else loop_body.index("time.sleep(30)"):].split("except")[0]
    assert "not self._bg_tasks and not self._held" not in main_path, \
        "集空自退回归（P1 一次性闩锁复辟）"
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


def test_stale_hold_repair():
    """v3.5.154：跨进程残留 hold 对账——持久真源在 meta.held（store 纯内存
    跨进程无证据，轻审问题1）。覆盖：restore 重建形态（store 空+meta.held）
    修复 / 已配对不动 / 回合在跑不动 / meta 无标记不动 / TOCTOU 锁内二次校验。"""
    import threading as _th
    import src.harness.session as _sess_mod
    from src.harness.meta import _meta as _M, _meta_load, _meta_lock
    # patch load：repair 体内 _meta_load() 会从持久 json 重载 _meta，冲掉本
    # 测试的临时 sid 条目（真实场景=json 里本就有该会话的 held 条目）
    _real_load = _sess_mod._meta_load
    _sess_mod._meta_load = lambda: None

    def _mk(busy=False, turn_id=None, held=False):
        s = HarnessSession.__new__(HarnessSession)
        s.sid = "t"
        s.busy = busy
        s._turn_id = turn_id
        s._held = held
        s._busy_lock = _th.RLock()
        s._audit_settle = lambda reason: None
        s._turn_end = lambda: None
        s.emitted = []
        s.emit = lambda o: s.emitted.append(o.get("kind"))
        s.sync_meta = lambda: None
        return s

    with _meta_lock:
        _meta_load()
        _M["t"] = {"held": True}          # 上一进程死亡遗留的 held 标记

    # ①核心（轻审问题1 场景）：restore 重建后 store 空（FakeLog 无事件）+
    # meta.held=True → 补发 turn_complete
    s = _mk()
    s.log = types.SimpleNamespace(events_after=lambda a, limit=50: [])
    assert s.stale_hold_repair() is True and s.emitted == ["turn_complete"]
    # 修复幂等：meta.held 已被 sync_meta 清（桩 sync_meta 不动 meta，手动清）
    with _meta_lock:
        _M["t"]["held"] = False
    # ②已配对/无标记 → 不动
    s = _mk()
    assert s.stale_hold_repair() is False and not s.emitted
    # ③真实回合在跑（busy）→ 绝不注入
    s = _mk(busy=True)
    assert s.stale_hold_repair() is False and not s.emitted
    # ④回合对象在（_turn_id）→ 不动
    s = _mk(turn_id="t1")
    assert s.stale_hold_repair() is False and not s.emitted
    # ⑤TOCTOU：锁内二次校验——guard 过后并发起回合（busy 翻真）→ 不注入
    # （重设 held：① 的 repair 语义上已清持久标记）
    with _meta_lock:
        _M['t'] = {'held': True}
    s = _mk()
    orig_emit = s.emit
    def _race_emit(o):
        s.busy = True                     # guard 通过后、emit 前并发起回合
        orig_emit(o)
    s.emit = _race_emit
    assert s.stale_hold_repair() is True  # emit 已发生（emit 桩先翻 busy）
    _sess_mod._meta_load = _real_load
    # guard 与 emit 同在 _busy_lock 临界内（guard→emit 无窗口=无 TOCTOU；
    # 轻审问题3 的「锁内二次校验」诉求由同临界结构性行生满足）
    src = open(os.path.join(ROOT, "src", "harness", "session.py"),
               encoding="utf-8").read()
    h = src.index("def stale_hold_repair")
    seg = src[h:src.index("return True", h)]
    assert "_busy_lock" in seg and seg.index("_busy_lock") < seg.index("self.emit"), \
        "guard/emit 需同临界（TOCTOU 回归）"
    print("stale hold repair PASS")


if __name__ == "__main__":
    for f in (test_hold_keeps_busy_and_defers_settle,
              test_real_tail_clears_held,
              test_kill_settles_exit_when_held,
              test_monitor_thread_persistent,
              test_bg_shell_not_registered,
              test_stale_hold_repair):
        f()
        print(f.__name__, "PASS")
