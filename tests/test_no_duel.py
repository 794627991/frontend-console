# -*- coding: utf-8 -*-
"""互踢/反复登录防线单测（a559 铁律 + a561 审计加固）。

覆盖防线组件：
- hiklink_bot._reconnect_wait：认证后短命断线指数退避；第 5 轮起熔断
  递增 300→600→1200→1800s；未认证断线不计踢；健康断线（≥60s）清零
- hiklink_bot._BotSingleFlight：O_EXCL 原子创建；活进程持锁拒绝；
  死 pid 接管；自残留清理；锁路径动态（迁移不分裂）
- lanzi.worker.LanzQuotaWorker._push_relogin：30 分钟滑窗第 3 次重登熔断
"""
import os
import sys
import time

sys.path.insert(0, '.')

from src.lanzi.bot import _BotSingleFlight, _reconnect_wait
from src.lanzi.worker import LanzQuotaWorker


# ---------- _reconnect_wait ----------

def test_reconnect_wait_normal_reset():
    """认证后存活 ≥60s 的正常断线：清零 + 基础 3s。"""
    assert _reconnect_wait(120.0, 3) == (3, 0, False)
    assert _reconnect_wait(3600.0, 9) == (3, 0, False)


def test_reconnect_wait_kick_backoff_progression():
    """认证后短命断线：3→6→12→24 带抖动。"""
    n = 0
    w1, n, t = _reconnect_wait(10.0, n)
    assert not t and 3 <= w1 <= 4 and n == 1
    w2, n, t = _reconnect_wait(10.0, n)
    assert not t and 6 <= w2 <= 9 and n == 2
    w3, n, t = _reconnect_wait(10.0, n)
    assert not t and 12 <= w3 <= 18 and n == 3
    w4, n, t = _reconnect_wait(10.0, n)
    assert not t and 24 <= w4 <= 36 and n == 4


def test_reconnect_wait_circuit_escalates():
    """a561 审计 P1：熔断递增 300→600→1200→1800 封顶（原恒 300，
    两实例僵持互踢永不收敛）。"""
    n = 4
    w, n, t = _reconnect_wait(10.0, n)
    assert t and w == 300 and n == 5
    w, n, t = _reconnect_wait(10.0, n)
    assert t and w == 600 and n == 6
    w, n, t = _reconnect_wait(10.0, n)
    assert t and w == 1200 and n == 7
    for _ in range(5):
        w, n, t = _reconnect_wait(10.0, n)
        assert t and w == 1800


def test_reconnect_wait_unauthed_not_kick():
    """a561 审计 P2：认证前断线（连接级故障）不计踢、不进熔断。"""
    w, n, t = _reconnect_wait(5.0, 0, was_authed=False)
    assert (w, n, t) == (3, 0, False)
    w, n, t = _reconnect_wait(5.0, 9, was_authed=False)
    assert (w, n, t) == (3, 9, False)


def test_reconnect_wait_kick_then_alive_resets():
    """被挤几轮后连上活连接（>60s 断开）→ 清零回 3s。"""
    _, n, _ = _reconnect_wait(5.0, 0)
    _, n, _ = _reconnect_wait(5.0, n)
    w, n, t = _reconnect_wait(300.0, n)
    assert (w, n, t) == (3, 0, False)


# ---------- _BotSingleFlight ----------

def _write_lock(path, pid):
    with open(path, "w", encoding="utf-8") as f:
        f.write("%d,%d" % (pid, int(time.time())))


def test_single_flight_blocks_live_holder(tmp_path, monkeypatch):
    """异 pid 持锁且进程活着 → 拒绝启动（互踢防线本体）。"""
    import src.lanzi.bot as hb
    monkeypatch.setattr(hb, "_pid_alive", lambda pid: True)
    p = str(tmp_path / "bot.lock")
    _write_lock(p, 424242)
    fl = _BotSingleFlight(lambda: p)
    ok, msg = fl.acquire()
    assert not ok and "424242" in msg     # 拒绝并报出占用者 PID
    assert os.path.exists(p)              # 不动别人的锁


def test_single_flight_unknown_liveness_refuses(tmp_path, monkeypatch):
    """a561：pid 查不出（高完整性/权限拒绝）→ 保守拒绝，绝不误接管。"""
    import src.lanzi.bot as hb
    monkeypatch.setattr(hb, "_pid_alive", lambda pid: True)
    p = str(tmp_path / "bot.lock")
    _write_lock(p, 777)
    fl = _BotSingleFlight(lambda: p)
    ok, msg = fl.acquire()
    assert not ok


def test_single_flight_dead_holder_takeover(tmp_path, monkeypatch):
    """持有者 pid 确认不存在 → 原子接管。"""
    import src.lanzi.bot as hb
    monkeypatch.setattr(hb, "_pid_alive", lambda pid: False)
    p = str(tmp_path / "bot.lock")
    _write_lock(p, 999999)
    fl = _BotSingleFlight(lambda: p)
    ok, _ = fl.acquire()
    assert ok
    with open(p, encoding="utf-8") as f:
        assert str(os.getpid()) in f.read()
    fl.release()
    assert not os.path.exists(p)


def test_single_flight_self_residue_reclaimed(tmp_path):
    """自己的残留锁（异常退出没删）→ 清掉重拿。"""
    p = str(tmp_path / "bot.lock")
    _write_lock(p, os.getpid())
    fl = _BotSingleFlight(lambda: p)
    ok, _ = fl.acquire()
    assert ok
    fl.release()


def test_single_flight_path_dynamic(tmp_path):
    """a561：锁路径按 DATA_DIR 动态解析（迁移后不分裂成两把锁）。"""
    state = {"dir": str(tmp_path / "a")}
    fl = _BotSingleFlight(
        lambda: os.path.join(state["dir"], "hiklink_bot.lock"))
    ok, _ = fl.acquire()
    assert ok
    state["dir"] = str(tmp_path / "b")     # 模拟数据目录迁移
    assert fl.path.startswith(str(tmp_path / "b"))
    fl.release()


# ---------- Lanz 重登滑窗 ----------

def test_push_relogin_trips_on_third():
    now = 1000000.0
    stamps, t = LanzQuotaWorker._push_relogin([], now)
    assert not t and len(stamps) == 1
    stamps, t = LanzQuotaWorker._push_relogin(stamps, now + 60)
    assert not t and len(stamps) == 2
    stamps, t = LanzQuotaWorker._push_relogin(stamps, now + 120)
    assert t and stamps == []             # 第 3 次 → 熔断 + 清窗


def test_push_relogin_window_drops_old():
    now = 1000000.0
    stamps = [now]
    stamps, t = LanzQuotaWorker._push_relogin(stamps, now + 1900)
    assert not t and len(stamps) == 1     # 旧戳出窗丢弃，不计第 2 次


def test_push_relogin_long_gaps_never_trip():
    """正常长会话（几小时登一次）永不熔断。"""
    ts = []
    t = False
    for i in range(6):
        ts, t = LanzQuotaWorker._push_relogin(ts, 1000000.0 + i * 7200)
        assert not t


# ---------- a561：跨进程重登标记（进程重启型风暴防线） ----------

def test_marks_roundtrip(tmp_path, monkeypatch):
    """落盘标记读写回环（F5：滑窗跨进程共享）。"""
    import src.lanzi.state as st
    p = str(tmp_path / "marks.json")
    monkeypatch.setattr(st, "MARKS_PATH", p)
    st.save_marks([100.0, 200.0], trip_ts=300.0)
    stamps, trip = st.load_marks()
    assert stamps == [100.0, 200.0] and trip == 300.0
    st.save_marks([], 0.0)
    assert st.load_marks() == ([], 0.0)


def test_marks_missing_file_is_empty(tmp_path, monkeypatch):
    import src.lanzi.state as st
    monkeypatch.setattr(st, "MARKS_PATH", str(tmp_path / "nope.json"))
    assert st.load_marks() == ([], 0.0)
