# -*- coding: utf-8 -*-
"""互踢/反复登录防线单测（a559 铁律：在线不重登、不互踢）。

覆盖三个防线组件：
- hiklink_bot._reconnect_wait：短命断线指数退避 + 连续 5 轮熔断 + 正常
  断线清零（11-12 风暴的驱动是「连接成功即重置 backoff=3」→ 3s 一轮）
- hiklink_bot._BotSingleFlight：本机单飞锁（活进程持锁拒绝 / 死锁接管 /
  过期接管）
- proxy.LanzQuotaWorker._push_relogin：30 分钟滑窗第 3 次重登熔断
"""
import os
import sys
import time

sys.path.insert(0, '.')

from src.hiklink_bot import _BotSingleFlight, _reconnect_wait
from src.proxy import LanzQuotaWorker


# ---------- _reconnect_wait ----------

def test_reconnect_wait_normal_reset():
    """存活 ≥60s 的正常断线：清零 + 基础 3s。"""
    assert _reconnect_wait(120.0, 3) == (3, 0, False)
    assert _reconnect_wait(3600.0, 9) == (3, 0, False)


def test_reconnect_wait_kick_backoff_progression():
    """短命断线（被挤）：3→6→12→24 带抖动，第 5 轮熔断 300s。"""
    n = 0
    w1, n, t = _reconnect_wait(10.0, n)
    assert not t and 3 <= w1 <= 4 and n == 1
    w2, n, t = _reconnect_wait(10.0, n)
    assert not t and 6 <= w2 <= 9 and n == 2
    w3, n, t = _reconnect_wait(10.0, n)
    assert not t and 12 <= w3 <= 18 and n == 3
    w4, n, t = _reconnect_wait(10.0, n)
    assert not t and 24 <= w4 <= 36 and n == 4
    w5, n, t = _reconnect_wait(10.0, n)
    assert t and w5 == 300 and n == 5
    w6, n, t = _reconnect_wait(10.0, n)
    assert t and w6 == 300          # 熔断后恒 300s 一探，不再加码


def test_reconnect_wait_kick_then_alive_resets():
    """被挤几轮后连上活连接（>60s 断开）→ 清零回 3s。"""
    _, n, _ = _reconnect_wait(5.0, 0)
    _, n, _ = _reconnect_wait(5.0, n)
    w, n, t = _reconnect_wait(300.0, n)
    assert (w, n, t) == (3, 0, False)


# ---------- _BotSingleFlight ----------

def _fresh_lock(path, pid, age=0.0):
    with open(path, "w", encoding="utf-8") as f:
        f.write("%d,%d" % (pid, int(time.time())))
    if age:
        os.utime(path, (time.time() - age,) * 2)


def test_single_flight_blocks_live_holder(tmp_path, monkeypatch):
    """异 pid 持锁且进程活着 → 拒绝启动（互踢防线本体）。"""
    import src.hiklink_bot as hb
    monkeypatch.setattr(hb, "_pid_alive", lambda pid: True)
    p = str(tmp_path / "bot.lock")
    _fresh_lock(p, 424242, age=0)         # 另一活进程持有
    fl = _BotSingleFlight(p)
    ok, msg = fl.acquire()
    assert not ok and "424242" in msg     # 拒绝并报出占用者 PID
    assert os.path.exists(p)              # 不动别人的锁


def test_single_flight_dead_holder_takeover(tmp_path, monkeypatch):
    import src.hiklink_bot as hb
    p = str(tmp_path / "bot.lock")
    _fresh_lock(p, 999999, age=0)         # 活锁龄但 pid 不存在
    fl = _BotSingleFlight(p)
    ok, msg = fl.acquire()
    assert ok                              # 死 pid → 接管
    fl.release()
    assert not os.path.exists(p)


def test_single_flight_stale_mtime_takeover(tmp_path):
    p = str(tmp_path / "bot.lock")
    _fresh_lock(p, 424242, age=300)       # 5 分钟没刷新 = 僵死/断电残留
    fl = _BotSingleFlight(p)
    ok, _ = fl.acquire()
    assert ok
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
