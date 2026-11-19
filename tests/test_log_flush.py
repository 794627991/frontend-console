# -*- coding: utf-8 -*-
"""a672：日志定时兜底落盘（用户实锤「SSH 没断，日志缺失最新几分钟」）。

根因：v3.5.162 为了防 SSH 输出风暴把日志文件改成 64KB 块缓冲，但**低频**
日志永远攒不满——一行约 68 字节，要 952 行才落一次盘；几秒一行的设备跑
几分钟只有几 KB，全躺在 Python 用户态缓冲里，磁盘上一个字都没有。读线程
一直是实时的，只是不落盘。

修：保留 64KB 缓冲（风暴防护不动），另加模块级巡检线程——超过 FLUSH_IDLE
秒没有新数据落盘就 flush 一次；关闭/切日志时必 flush。
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.app_state as _st  # noqa: E402
from src import base_conn as B  # noqa: E402


class _Fake(B.BaseConnection):
    """不碰真实 IO 的连接：读线程空转。"""
    kind = "fake"

    def _io_open(self):
        pass

    def _io_read_chunk(self):
        time.sleep(0.05)
        return b""

    def _io_write(self, d):
        pass

    def _io_close(self):
        pass

    def _io_reconnect(self):
        return False


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(_st, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(B, "_live_conns", [])
    c = _Fake("t")
    c._start_log()
    B.register_conn(c)
    yield c
    try:
        c.close()
    except Exception:
        pass


def _disk(p):
    return os.path.getsize(p) if os.path.exists(p) else 0


def test_low_rate_log_lands_within_flush_idle(conn, monkeypatch):
    """低频写入（攒不满 64KB）必须在 FLUSH_IDLE 后落盘——用户实锤场景。"""
    monkeypatch.setattr(B, "_FLUSH_CHECK", 0.1)
    monkeypatch.setattr(B, "FLUSH_IDLE", 0.3)
    for i in range(3):
        conn.append_line("device output %d" % i)
    assert _disk(conn.log_path) == 0, "块缓冲下不该立即落盘"

    deadline = time.time() + 3.0
    while time.time() < deadline and _disk(conn.log_path) == 0:
        time.sleep(0.05)
    assert _disk(conn.log_path) > 0, "超过 FLUSH_IDLE 仍未落盘"
    assert "device output 2" in open(conn.log_path, encoding="utf-8").read()


def test_high_rate_does_not_flush_per_line(conn):
    """风暴防护不能退化：短时间内大量写入，flush 次数必须远小于行数。

    这是 v3.5.162 块缓冲存在的唯一理由（每行两次刷盘会打满磁盘 IO）。
    """
    n = [0]
    orig = conn.log_fp.flush

    def counting():
        n[0] += 1
        return orig()

    conn.log_fp.flush = counting
    lines = 20000
    for i in range(lines):
        conn.append_line("fast line %d" % i)
    conn.log_fp.flush()          # 收尾一次
    assert n[0] < 20, "flush 次数 %d 远超阈值（应按块满/定时落盘）" % n[0]


def test_close_flushes_tail(conn):
    """close 必须 flush——64KB 里压着的尾巴不能丢。"""
    conn.append_line("last line before close")
    path = conn.log_path
    conn.close()
    assert "last line before close" in open(path, encoding="utf-8").read()


def test_new_log_flushes_old_file(conn):
    """切到新日志文件前必须 flush 旧文件。"""
    conn.append_line("tail of old file")
    old = conn.log_path
    conn.new_log()
    assert "tail of old file" in open(old, encoding="utf-8").read()
    assert conn.log_path != old


def test_close_unregisters(conn):
    """关闭后必须移出巡检表，否则巡检会去 flush 已关闭的文件。"""
    assert conn in B._live_conns
    conn.close()
    assert conn not in B._live_conns


def test_flush_idle_is_reasonable():
    """3 秒是用户拍的板：实测 flush 到内核 0.006ms，3s 一次代价可忽略。

    这条钉住常量语义——有人想改成 0.1s（每行都刷）或 60s（回到丢日志）
    都得先看这条测试的注释。
    """
    assert B.FLUSH_IDLE == 3.0
    assert B._FLUSH_CHECK <= B.FLUSH_IDLE


# ---- a673（审计 P1/P2）：撞名绝不覆盖 + 锁外脏读语义 ----------------------
def test_unique_log_path_never_overwrites(tmp_path):
    """撞名循环的兜底悖论：原实现 999 次全撞后 path 仍是原值 → open("w")
    截断已有文件。现改 O_EXCL 原子占位，任何情况下都拿到一个新名字。"""
    base = str(tmp_path / "serial_x_20260101_000000.log")
    a = B._unique_log_path(base)
    b = B._unique_log_path(base)
    assert a != b, "第二次必须换名"
    assert os.path.basename(b) == "serial_x_20260101_000000_1.log"
    with open(a, "w", encoding="utf-8") as f:
        f.write("PRECIOUS")
    c = B._unique_log_path(base)
    assert c not in (a, b)
    assert open(a, encoding="utf-8").read() == "PRECIOUS", "已有文件被截断"


def test_unique_log_path_exhaustion_falls_back(tmp_path, monkeypatch):
    """序号 1..999 全被占用时，必须退到纳秒唯一名，绝不回到原路径覆盖。

    直接让 os.open 永远抛 FileExistsError（模拟病态占满），O(1) 验证兜底。
    """
    def always_exists(p, flags, mode=0o777):
        raise FileExistsError(p)

    monkeypatch.setattr(os, "open", always_exists)
    base = str(tmp_path / "serial_x_20260101_000000.log")
    p = B._unique_log_path(base)
    assert p != base, "耗尽后不许返回原路径（那会截断已有文件）"
    assert str(os.getpid()) in os.path.basename(p)


def test_same_second_new_log_does_not_truncate(conn):
    """同秒双开必须产生 _1 后缀且旧文件内容完好（真实行为变更）。"""
    conn.append_line("PRECIOUS-OLD")
    old = conn.log_path
    conn.log_fp.flush()
    assert "PRECIOUS-OLD" in open(old, encoding="utf-8").read()

    conn.new_log()                    # 同一秒内再开
    assert conn.log_path != old
    assert "_1.log" in conn.log_path
    assert "PRECIOUS-OLD" in open(old, encoding="utf-8").read(), "旧日志被截断"


def test_flusher_tolerates_racy_dirty_read(conn, monkeypatch):
    """_log_dirty_at 故意在锁外读：读到的值只影响本轮是否 flush，不影响正确性。
    这里把时间戳设成「刚刚写过」，巡检必须跳过（不打扰热路径）。"""
    conn.append_line("hot")
    conn._log_dirty_at = time.time()      # 刚写过，未超 3s
    monkeypatch.setattr(B, "_FLUSH_CHECK", 0.05)
    time.sleep(0.3)
    # 缓冲里还是那行，但巡检不该因为「刚写过」就 flush
    assert conn._log_dirty_at > 0, "脏时间戳应保持，等超时才落盘"
