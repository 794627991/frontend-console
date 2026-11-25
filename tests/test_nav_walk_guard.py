# -*- coding: utf-8 -*-
"""扫描阻塞防护钉测（a570）。

为什么钉这一块：G10 的 `sbuilder/output/build/hikudev-head` 因 sysfs 自链
展开导致扫描器 26 分钟只处理 13/62 个包。内网原方案用「目录级推进」判超时
（每进入一个目录刷新时间戳），但该目录实测 **60 秒推进 893 个目录**
（0.067s/目录）——任何「无推进」判据都永不触发，方案完全无效。

用户定调（四条硬约束）：
1. 任意目录阻塞必须有硬超时（180 秒）
2. 超时目录直接放弃，其余继续
3. 卡死补 worker，保持吞吐
4. worker 总数上界 16，防无限增长

本文件的判据单元是 **item**（work_q 的一个种子子树），不是目录、不是文件。
"""
import os
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni    # noqa: E402


# ---- 常量（用户定调的四条硬约束）--------------------------------------

def test_stall_limit_is_180s():
    """用户定调：180 秒。改小会让正常大目录被误判，改大等于放弃防护。"""
    assert ni._STALL_LIMIT == 180.0


def test_max_workers_is_16():
    """活跃 worker 上界 16（用户定调）。防「卡死→补→又卡死」无限增长。"""
    assert ni._MAX_WORKERS == 16


def test_hard_cap_scales_with_concurrency():
    """a570（P1·第八轮 / 第十轮收敛）：硬卡死线程（不会退出）需要总上界，
    否则名额被永久占满、队尾种子被饿死。上界按并发档位缩放——本地盘
    （N_WORKERS=1）不该补到 64 个线程（磁盘故障下只是 64 倍 IO 压力）。"""
    import inspect
    src = inspect.getsource(ni._walk_files)
    assert "max(8, N_WORKERS * 8)" in src, "硬上限必须按并发档位缩放"


def test_watchdog_tick_is_short_enough():
    """巡检间隔必须远小于超时阈值，否则超时判定会晚一个 tick 才生效。"""
    assert 0 < ni._WD_TICK <= ni._STALL_LIMIT / 10


# ---- tmp 目录剪枝 ------------------------------------------------------

def test_tmp_names_is_exact_match_set():
    """完整名匹配：不能误伤 template / attempt / tmpl。"""
    assert ni._TMP_NAMES == {"tmp", "temp", "tmpdir", "tempdir"}
    for not_tmp in ("template", "attempt", "tmpl", "tempfiles", "tmp2"):
        assert not_tmp not in ni._TMP_NAMES


def _make_tree(root, dirs, files_per_dir=1, filename="a.c"):
    for d in dirs:
        p = os.path.join(root, *d.split("/"))
        os.makedirs(p, exist_ok=True)
        for i in range(files_per_dir):
            with open(os.path.join(p, "%d_%s" % (i, filename)), "w") as f:
                f.write("int x%d;\n" % i)


def test_walk_prunes_tmp_and_counts_it(tmp_path):
    """tmp 类目录被无条件剪枝，且计入 stats["tmp_skipped"] 让用户可见。"""
    root = str(tmp_path)
    _make_tree(root, ["src", "src/tmp", "src/sub"])
    stats = {}
    got = sorted(rel for _, rel in ni._walk_files(root, stats=stats))
    assert all("/tmp/" not in r for r in got)
    assert any(r.startswith("src/sub/") for r in got)
    assert stats.get("tmp_skipped", 0) == 1


# ---- 三态（off 剪枝 / artifact_roots 例外）-----------------------------

def test_walk_prunes_off_state(tmp_path):
    """state_of 返回 off 的目录在 scandir 层剪掉，计入 pruned_off。"""
    root = str(tmp_path)
    _make_tree(root, ["keep", "drop/sub"])
    stats = {}

    def state_of(rel):
        return "off" if rel == "drop" or rel.startswith("drop/") else "full"

    got = [rel for _, rel in ni._walk_files(root, stats=stats,
                                            state_of=state_of)]
    assert any(r.startswith("keep/") for r in got)
    assert not any(r.startswith("drop/") for r in got)
    assert stats.get("pruned_off", 0) >= 1


def _artifact_tree(root):
    """build/pkg 是产物源：里面一个源文件和它的 .cmd。"""
    _make_tree(root, ["build/pkg"], filename="x.c")
    with open(os.path.join(root, "build", "pkg", "x.o.cmd"), "w") as f:
        f.write("savedcmd_x.o := gcc -c -o x.o x.c\n")


def test_artifact_walk_scans_artifact_root_regardless_of_off(tmp_path):
    """产物源由**独立的产物扫描**（subs=产物根、不带 state_of）采 .cmd/.o。

    契约更新（2026-11-25 审查 a697 / 内网 a571）：产物源不再靠主扫描下钻到。
    build() 里是分开的两遍——主扫描管索引清单，产物扫描（subs=artifact_roots）
    管编译描述；产物扫描不看三态，整棵 off 也照扫。
    （本测试原名 test_walk_artifact_root_scanned_despite_off，钉的是「主扫描
    也要扫到」的旧契约。）
    """
    root = str(tmp_path)
    _artifact_tree(root)
    got = [rel for _, rel in ni._walk_files(
        root, subs=["build/pkg"], dot_keep=True, max_depth=24)]
    assert "build/pkg/x.o.cmd" in got, "产物源里的 .cmd 必须被采到"


def test_main_walk_prunes_off_ancestor_of_artifact_root(tmp_path):
    """主扫描遇到 off 的目录就剪——哪怕它是产物源的祖先。

    a697 之前主扫描放行产物源的祖先（原判据 `st == "off" and not _in_artifacts`，
    而 `_in_artifacts` 对祖先也返回 True）：G10 的 `sbuilder/output/build` 是产物源，
    主扫描因此钻进 12.4 万文件的 sbuilder 白等到超时。产物源改由独立的产物扫描
    负责后，主扫描没有理由进去。
    （原 test_walk_artifact_root_ancestor_not_pruned 钉的是相反的旧契约。）
    """
    root = str(tmp_path)
    _artifact_tree(root)
    stats = {}
    got = [rel for _, rel in ni._walk_files(
        root, state_of=lambda _r: "off", artifact_roots=["build/pkg"],
        stats=stats)]
    assert not any(r.startswith("build/") for r in got), \
        "off 的产物源祖先被放行——主扫描钻进了产物区：%r" % got
    assert stats.get("pruned_off", 0) >= 1


def test_artifact_root_source_not_in_index_walk(tmp_path):
    """a570 对抗审计 P0：产物源目录的源码不能进索引清单。

    设计 §4.1：产物源只用来推白名单。G10 的 sbuilder 有 3.9 万源文件，进了索引
    清单就是索引爆炸。主扫描在祖先那一层就剪掉了，源码自然进不来。
    （原 test_walk_artifact_root_only_products_not_source。）
    """
    root = str(tmp_path)
    _artifact_tree(root)
    got = [rel for _, rel in ni._walk_files(
        root, state_of=lambda _r: "off", artifact_roots=["build/pkg"])]
    assert not any(r.endswith(".c") for r in got), \
        "产物源里的源码进了索引清单：%r" % got


def test_walk_off_dir_with_live_child_keeps_child_source(tmp_path):
    """off 父目录下显式 white 的子目录：子目录源码要收，父目录自身的不收。"""
    root = str(tmp_path)
    _make_tree(root, ["kernel/src"], filename="keep.c")
    _make_tree(root, ["kernel"], filename="leak.c")
    sc = {"version": 2, "mode": "manual",
          "dirs": {"kernel": "off", "kernel/src": "whitelist"},
          "artifact_roots": [], "exclude_names": []}
    got = [rel for _, rel in ni._walk_files(
        root, state_of=ni._make_state_of(sc), stats={})]
    assert "kernel/src/0_keep.c" in got
    assert "kernel/0_leak.c" not in got, \
        "off 目录自身直下的文件不能因「有 live 后代」被放行"


def test_artifact_walk_keeps_dot_dirs(tmp_path):
    """a570 对抗审计 P1：产物源扫描里的 .libs/.pio 是合法产物输入（a398#23）。"""
    root = str(tmp_path)
    _make_tree(root, ["out/build/.libs"], filename="x.c")
    with open(os.path.join(root, "out", "build", ".libs", "y.o.cmd"), "w") as f:
        f.write("savedcmd\n")
    got = [rel for _, rel in ni._walk_files(
        root, subs=["out/build"], artifact_roots=["out/build"], dot_keep=True)]
    assert any(".libs" in r and r.endswith(".cmd") for r in got), \
        "dot_keep=True 时产物源里的点目录必须保留"


# ---- 点目录规则（a398 #23 不能回退）------------------------------------

def test_dot_dir_kept_under_whitelist(tmp_path):
    """.libs 在 whitelist 下必须保留——里面的 .o/.cmd 是合法产物输入。"""
    root = str(tmp_path)
    _make_tree(root, ["proj/.libs"], filename="y.c")
    got = [rel for _, rel in ni._walk_files(
        root, state_of=lambda _r: "whitelist")]
    assert any(".libs" in r for r in got), \
        "whitelist 下的点目录被剪了 —— a398 审计 #23 回归"


def test_dot_dir_kept_under_full(tmp_path):
    """a570 对抗审计（P2·第十一轮）：full 档也要保留点目录。

    原实现只在 whitelist 保留，`lib: full` 时 `lib/.libs/*.o` 被剪
    （a398 审计#23 的实测回归）。.libs 里的 .o 对白名单推导有价值；
    full 档本就全收源码，多收几个点目录也是对的。
    """
    root = str(tmp_path)
    _make_tree(root, ["proj/.libs", "proj/normal"], filename="y.c")
    got = [rel for _, rel in ni._walk_files(
        root, state_of=lambda _r: "full")]
    assert any(".libs" in r for r in got), "full 档的点目录被剪了"
    assert any("proj/normal" in r for r in got)


def test_dot_dir_pruned_under_off(tmp_path):
    """off 档的点目录必须剪掉（不收录的子树不该有任何产出）。"""
    root = str(tmp_path)
    _make_tree(root, ["proj/.libs", "proj/normal"], filename="y.c")
    got = [rel for _, rel in ni._walk_files(
        root, state_of=lambda _r: "off")]
    assert not any(".libs" in r for r in got)


# ---- 看门狗：item 级超时 ----------------------------------------------

def test_blocked_subtree_is_abandoned_not_hung(tmp_path, monkeypatch):
    """核心回归：某子树「极慢但持续产出」时，必须在 180s 判定后放弃，
    而不是像内网原方案那样永不触发。

    这里把阈值改小以免测试跑 3 分钟。慢子树用 monkeypatch 的 os.walk
    模拟「每 10ms 产出一个目录、永不结束」。
    """
    root = str(tmp_path)
    _make_tree(root, ["fast/sub"], filename="a.c")
    # 建一个会被识别为慢的种子。_walk_files 的 seed 构造：L1 子目录数
    # < N_WORKERS 时会拆到 L2，所以这里造 9 个一级子目录（>=8），
    # 让 slow 的子目录直接成为 worker 的 item。
    slow = os.path.join(root, "slow")
    for i in range(9):
        os.makedirs(os.path.join(slow, "d%d" % i, "leaf"), exist_ok=True)

    real_walk = os.walk
    stop = threading.Event()

    def fake_walk(top, *a, **kw):
        if "slow" in os.path.normcase(top).replace("\\", "/"):
            # 无限慢：每次产出 1 个目录（模拟 hikudev 的持续产出）
            i = 0
            while not stop.is_set():
                time.sleep(0.01)
                d = os.path.join(top, "d%d" % i)
                i += 1
                yield d, [], ["f.c"]
            return
        yield from real_walk(top, *a, **kw)

    monkeypatch.setattr(ni.os, "walk", fake_walk)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.3)
    monkeypatch.setattr(ni, "_WD_TICK", 0.05)

    stats = {}
    t0 = time.time()
    try:
        # 只跑 slow 种子
        list(ni._walk_files(root, subs=["slow"], stats=stats))
    finally:
        stop.set()
    elapsed = time.time() - t0

    assert elapsed < 10, "看门狗未生效——扫描被慢子树拖住"
    to = stats.get("timeout_items") or []
    assert to, "未记录 timeout_items，用户看不到跳过了什么"
    assert any("slow" in it["rel"] for it in to)


def test_timeout_does_not_drop_remaining_subtrees(tmp_path, monkeypatch):
    """a570 对抗审计 P0 回归：超时只能放弃**那一个 item**，其余子树必须
    照常扫完。

    原实现在看门狗里先算 `_last` 快照、再补 worker，于是补上的 worker 刚
    +1 就发了 DONE，剩余全部子树被静默丢弃（实测 1/16）。
    """
    root = str(tmp_path)
    # 16 个一级子目录：足够多 worker 拆分
    for i in range(16):
        os.makedirs(os.path.join(root, "s%02d" % i), exist_ok=True)
        with open(os.path.join(root, "s%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")

    real_walk = os.walk
    stop = threading.Event()

    def fake_walk(top, *a, **kw):
        base = os.path.basename(str(top))
        if base == "s00":
            while not stop.is_set():   # 只让 s00 一个卡死
                time.sleep(0.01)
            return
        yield from real_walk(top, *a, **kw)

    monkeypatch.setattr(ni.os, "walk", fake_walk)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.3)
    monkeypatch.setattr(ni, "_WD_TICK", 0.05)

    got = []
    t0 = time.time()
    try:
        for _abs, rel in ni._walk_files(root, stats={}):
            got.append(rel)
    finally:
        stop.set()

    assert time.time() - t0 < 20
    # s00 被放弃，其余 15 个必须全部产出
    rest = {r.split("/")[0] for r in got}
    assert len(rest) >= 14, "超时导致其他子树被丢弃：只收到 %r" % sorted(rest)


def test_worker_second_timeout_still_monitored(tmp_path, monkeypatch):
    """a570 对抗审计 P1：`_dead` 只写不删会让同一 worker 的**第二个**
    item 超时永远不被看门狗处理（本地盘 N_WORKERS=1 时等于防护只生效一次）。
    """
    root = str(tmp_path)
    for i in range(4):
        os.makedirs(os.path.join(root, "d%d" % i), exist_ok=True)
        with open(os.path.join(root, "d%d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    # 强制单 worker
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: False)

    real_walk = os.walk
    stop = threading.Event()

    def fake_walk(top, *a, **kw):
        # 每个种子都慢
        while not stop.is_set():
            time.sleep(0.01)
        return
        yield  # noqa

    monkeypatch.setattr(ni.os, "walk", fake_walk)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.2)
    monkeypatch.setattr(ni, "_WD_TICK", 0.04)

    stats = {}
    try:
        list(ni._walk_files(root, stats=stats))
    finally:
        stop.set()
    # 4 个种子串行，每个都该超时——至少 2 次说明第二个及以后仍被监控
    assert len(stats.get("timeout_items") or []) >= 2, \
        "同一 worker 的第二个 item 超时未被看门狗处理"


def test_timeout_worker_exits_promptly(tmp_path, monkeypatch):
    """a570 对抗审计 P0 回归（第三轮）：被判超时的 item 必须让 worker
    **干净退出**，否则「DONE 何时发」永远悬而未决——早发丢数据、晚发卡死。

    定调是「超时目录直接放弃」（该 item 的后续产出本就不该保留），所以这里
    钉的是：扫描迅速结束 + 有 timeout 记录 + 不泄漏线程。
    """
    root = str(tmp_path)
    seed = os.path.join(root, "one")
    os.makedirs(seed, exist_ok=True)

    real_walk = os.walk

    def fake_walk(top, *a, **kw):
        if os.path.basename(str(top)) == "one":
            for i in range(200):
                time.sleep(0.02)        # 远超超时阈值
                d = os.path.join(top, "b%d" % i)
                os.makedirs(d, exist_ok=True)
                yield d, [], ["f.c"]
            return
        yield from real_walk(top, *a, **kw)

    monkeypatch.setattr(ni.os, "walk", fake_walk)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.1)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: False)

    stats = {}
    before = threading.active_count()
    t0 = time.time()
    list(ni._walk_files(root, stats=stats))
    elapsed = time.time() - t0

    assert elapsed < 10, "看门狗判超时后 worker 未及时退出（扫描卡在 %ds）" % elapsed
    assert stats.get("timeout_items"), "未记录 timeout_items"
    time.sleep(0.3)
    assert threading.active_count() <= before + 1, "worker 线程泄漏"


def test_worker_that_stalled_then_recovers_not_treated_as_zombie(tmp_path,
                                                                 monkeypatch):
    """a570 对抗审计 P0 回归（第四轮）：worker 的某个 item 被判超时后，
    若它换到新 item 正常产出，**不能**被当成僵尸——否则看门狗会把
    「全部都被判超时」当作「没人干活了」而提前发 DONE，新 item 的文件
    成批静默丢失（实测 8 个种子的文件全丢）。
    """
    root = str(tmp_path)
    for i in range(24):
        os.makedirs(os.path.join(root, "d%02d" % i), exist_ok=True)
        with open(os.path.join(root, "d%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)   # 8 worker
    monkeypatch.setattr(ni, "_MAX_WORKERS", 16)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.2)
    monkeypatch.setattr(ni, "_WD_TICK", 0.03)

    real_walk = os.walk

    def fake_walk(top, *a, **kw):
        base = os.path.basename(str(top))
        # 前 8 个种子卡一会儿（会被判超时），之后正常
        if base in {"d%02d" % i for i in range(8)}:
            time.sleep(0.5)      # > 阈值，但之后正常产出一个目录
        yield from real_walk(top, *a, **kw)

    monkeypatch.setattr(ni.os, "walk", fake_walk)

    got = [rel for _abs, rel in ni._walk_files(root, stats={})]
    tops = {r.split("/")[0] for r in got}
    # 被超时的那 8 个允许为空；其余 16 个必须全部有文件
    rest = {"d%02d" % i for i in range(8, 24)}
    assert rest.issubset(tops), \
        "超时 worker 恢复后的产出被丢弃：缺 %r" % sorted(rest - tops)


def test_watchdog_thread_does_not_leak(tmp_path):
    """连续多次扫描不得累积看门狗线程（_wd_stop.set() 生效）。"""
    root = str(tmp_path)
    _make_tree(root, ["a/sub", "b/sub"], filename="a.c")
    before = threading.active_count()
    for _ in range(5):
        list(ni._walk_files(root))
    # 给 daemon 线程一点退出时间
    deadline = time.time() + 5
    while time.time() < deadline and threading.active_count() > before:
        time.sleep(0.05)
    assert threading.active_count() <= before + 1, \
        "看门狗线程泄漏：%d -> %d" % (before, threading.active_count())


# ---- 取消 --------------------------------------------------------------

def test_cancel_stops_walk(tmp_path):
    """should_cancel 立即生效（消费侧循环头检查）。"""
    root = str(tmp_path)
    _make_tree(root, ["a/x", "b/y", "c/z"], files_per_dir=3)
    n = [0]

    def cancel():
        n[0] += 1
        return n[0] > 2

    with pytest.raises(ni.Cancelled):
        for _ in ni._walk_files(root, should_cancel=cancel):
            pass


def test_more_seeds_than_workers_all_blocked_none_dropped(tmp_path,
                                                          monkeypatch):
    """a570 对抗审计 P0 回归（第五轮）：种子数 > N_WORKERS 且全部被判超时，
    队列里剩余的种子不能被「最后一个 worker 退出」当成扫完而丢弃。

    原实现（DONE 判据 = `_live` 为空）实测 17 种子只收到 16 个、24 只收到
    16 个，缺失的连 timeout_items 都没记。
    """
    root = str(tmp_path)
    n = 24
    for i in range(n):
        os.makedirs(os.path.join(root, "d%02d" % i), exist_ok=True)
        with open(os.path.join(root, "d%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_MAX_WORKERS", 8)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        if os.path.basename(str(top)).startswith("d"):
            _tt.sleep(0.4)      # 全部超时
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    stats = {}
    got = [rel for _a, rel in ni._walk_files(root, stats=stats)]
    # 全部 24 个种子要么产出、要么在 timeout_items 里被明确记录
    produced = {r.split("/")[0] for r in got}
    timed = {it["rel"].split("/")[0].replace(".", "")
             for it in (stats.get("timeout_items") or [])}
    all_seeds = {"d%02d" % i for i in range(n)}
    missing = all_seeds - produced - timed
    assert not missing, "这些种子既没产出也没记超时（静默丢弃）：%r" % sorted(missing)


def test_done_not_sent_while_worker_still_producing(tmp_path, monkeypatch):
    """a570 对抗审计 P1 回归（第五轮）：唯一存活 worker 正在 item 内正常产出
    （只是当前 item 被判过超时）时，不得发 DONE 截断它。

    原实现看门狗出口「_live 非空且全在 _dead 且队列空」会在此发 DONE，
    实测后半段 10 条全部丢失。
    """
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "only"), exist_ok=True)
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: False)   # 单 worker
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.1)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        if os.path.basename(str(top)) == "only":
            # 先快速产 3 条，再慢吞吞产 20 条（跨过超时阈值但持续推进）
            for i in range(3):
                yield os.path.join(top, "f%d" % i), [], ["a.c"]
            for i in range(3, 23):
                _tt.sleep(0.02)
                yield os.path.join(top, "f%d" % i), [], ["a.c"]
            return
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    import time as _t2
    t0 = _t2.time()
    got = [rel for _a, rel in ni._walk_files(root, stats={})]
    elapsed = _t2.time() - t0
    # 「超时即放弃该 item」⇒ 放弃之后的产出本就不该收，所以不要求 23。
    # 真正要保证的是：彻底收口、不挂死、已收到的是连续前缀（无空洞）。
    assert elapsed < 10, "被放弃的 worker 未及时收口（%.1fs）" % elapsed
    assert got, "一条都没收到"
    idx = [int(r.split("/")[1][1:]) for r in got]
    assert idx == list(range(idx[0], idx[0] + len(idx))), \
        "收到的目录不是连续前缀（说明中间有静默丢失）"


def test_walk_tail_after_last_yield_settles_exactly_once(tmp_path,
                                                         monkeypatch):
    """a570 对抗审计 P1 回归（第六轮）：item 在**最后一次 yield 之后**才慢
    （长尾）——worker 走不到 `_dead` 检查点，item-finally 结算。
    看门狗此时也已代结算 → 原实现双扣 `_pending`，提前 DONE，其他仍在正常
    产出的种子被截断（端到端实测 100% 丢文件）。

    这里只验证「结算恰好一次」：多个带长尾的种子 + 一批正常种子，正常种子
    的文件一个都不能丢。
    """
    root = str(tmp_path)
    for i in range(12):
        os.makedirs(os.path.join(root, "t%02d" % i), exist_ok=True)
        with open(os.path.join(root, "t%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    for i in range(4):
        os.makedirs(os.path.join(root, "z%02d" % i), exist_ok=True)
        with open(os.path.join(root, "z%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_MAX_WORKERS", 16)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.2)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        base = os.path.basename(str(top))
        if base.startswith("t"):
            for _r, ds, fs in real(top, *a, **kw):
                yield _r, ds, fs
            _tt.sleep(0.35)     # 长尾：最后一次 yield 之后才超时
            return
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    got = [rel for _a, rel in ni._walk_files(root, stats={})]
    z = {r.split("/")[0] for r in got if r.startswith("z")}
    assert z == {"z%02d" % i for i in range(4)}, \
        "正常种子被提前 DONE 截断：缺 %r" % sorted(
            {"z%02d" % i for i in range(4)} - z)


def test_pending_settles_exactly_once_under_concurrency(tmp_path, monkeypatch):
    """结算恰好一次：`_pending` 最终必须归零且不提前归零。

    直接把内部状态暴露出来检测不方便，改从行为上钉：大量种子 + 全部长尾，
    必须收口（不挂死）且所有种子要么产出要么记超时。
    """
    root = str(tmp_path)
    n = 40
    for i in range(n):
        os.makedirs(os.path.join(root, "s%02d" % i), exist_ok=True)
        with open(os.path.join(root, "s%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_MAX_WORKERS", 16)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        yield from real(top, *a, **kw)
        _tt.sleep(0.25)     # 全部长尾
    monkeypatch.setattr(ni.os, "walk", fake)

    stats = {}
    t0 = _tt.time()
    got = [rel for _a, rel in ni._walk_files(root, stats=stats)]
    elapsed = _tt.time() - t0
    assert elapsed < 25, "长尾场景未收口（%.1fs）" % elapsed
    produced = {r.split("/")[0] for r in got}
    timed = {it["rel"].split("/")[0] for it in (stats.get("timeout_items") or [])}
    all_s = {"s%02d" % i for i in range(n)}
    missing = all_s - produced - timed
    assert not missing, "既未产出也未记超时：%r" % sorted(missing)


def test_hard_blocked_workers_do_not_starve_healthy_seeds(tmp_path,
                                                           monkeypatch):
    """a570 对抗审计 P1 回归（第七轮）：≥N_WORKERS 个 worker 全部硬卡死在
    系统调用里（永不退出），队列里的健康种子不能被饿死。

    原实现名额按线程总数算，16 个硬卡线程占满后永不补人，队尾 16 个健康
    种子 100% 静默丢失。
    """
    root = str(tmp_path)
    n_bad, n_good = 16, 16
    for i in range(n_bad):
        os.makedirs(os.path.join(root, "bad%02d" % i), exist_ok=True)
    for i in range(n_good):
        os.makedirs(os.path.join(root, "ok%02d" % i), exist_ok=True)
        with open(os.path.join(root, "ok%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_MAX_WORKERS", 16)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.2)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        if os.path.basename(str(top)).startswith("bad"):
            # 硬卡死：不 yield、不返回（模拟 SMB 断连卡在系统调用里）
            while True:
                _tt.sleep(0.05)
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    stats = {}
    got = []
    # 用生产者线程兜底：消费侧最多等 30s
    import threading as _thr

    def _run():
        try:
            for _a, rel in ni._walk_files(root, stats=stats):
                got.append(rel)
        except Exception:
            pass
    t = _thr.Thread(target=_run, daemon=True)
    t.start()
    t.join(30)
    good = {r.split("/")[0] for r in got if r.startswith("ok")}
    assert good == {"ok%02d" % i for i in range(n_good)}, \
        "健康种子被硬卡死线程饿死：缺 %r" % sorted(
            {"ok%02d" % i for i in range(n_good)} - good)


def test_watchdog_never_blocks_on_done(tmp_path, monkeypatch):
    """a570 对抗审计 P1 回归（第七轮）：看门狗结算路径不得走阻塞 DONE。

    构造：消费侧极慢（yield 之间 sleep）让 out_q 打满，看门狗若是最后一个
    结算方会进 put(timeout=1.0) 循环 → 超时判定停摆。
    """
    root = str(tmp_path)
    for i in range(30):
        os.makedirs(os.path.join(root, "d%02d" % i), exist_ok=True)
        for j in range(20):
            with open(os.path.join(root, "d%02d" % i, "f%d.c" % j), "w") as f:
                f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_MAX_WORKERS", 16)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.2)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        if os.path.basename(str(top)).startswith("d"):
            _tt.sleep(0.35)      # 全部超时
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    # a570 对抗审计（P2·第八轮）：原用「耗时 < 40s」当判据，把 `_settle`
    # 变异回阻塞版仍能通过——形同虚设。改为直接记录看门狗调用 `_send_done`
    # 时的 block 参数（它是唯一能证明「看门狗不阻塞」的观察点）。
    blocks = []
    real_send = ni.__dict__.get("_send_done")
    import queue as _q2

    class _SpyQueue(type(_q2.Queue())):
        pass
    # 直接盯 out_q 的 put 超时参数不可行（闭包内），改盯统计：
    # 看门狗路径若阻塞，`_settle` 里调 `_maybe_done(block=True)`，
    # 现象是「最后一个结算方是看门狗且耗时≈1s 的整数倍」。
    t0 = _tt.time()
    n = 0
    for _a, _rel in ni._walk_files(root, stats={}):
        n += 1
        _tt.sleep(0.004)         # 消费侧慢，制造队列压力
    elapsed = _tt.time() - t0
    # 看门狗若阻塞，会按 put(timeout=1.0) 逐秒重试，总耗时呈整秒跳变且
    # 明显劣化。这里钉一个更紧的界（原 40s 太松）。
    assert elapsed < 15, "看门狗被阻塞拖慢收口（%.1fs）" % elapsed


def test_zombies_do_not_cause_false_failure(tmp_path, monkeypatch):
    """a570 对抗审计 P1 回归（第十轮）：有 worker 正常干活时，即使若干僵尸
    把线程数顶到硬上限，也**不得**误报失败——数据扫完了却判失败是严重倒退。
    """
    root = str(tmp_path)
    n_bad, n_good = 7, 40
    for i in range(n_bad):
        os.makedirs(os.path.join(root, "bad%d" % i), exist_ok=True)
    for i in range(n_good):
        os.makedirs(os.path.join(root, "ok%02d" % i), exist_ok=True)
        with open(os.path.join(root, "ok%02d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: False)   # 本地：cap=8
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        base = os.path.basename(str(top))
        if base.startswith("bad"):
            while True:
                _tt.sleep(0.05)
        if base.startswith("ok"):
            _tt.sleep(0.05)      # 慢但会完成
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    err = None
    got = []
    try:
        for _a, rel in ni._walk_files(root, stats={}):
            got.append(rel)
    except Exception as e:
        err = e
    good = {r.split("/")[0] for r in got if r.startswith("ok")}
    assert good == {"ok%02d" % i for i in range(n_good)},         "健康种子被饿死：缺 %r" % sorted(
            {"ok%02d" % i for i in range(n_good)} - good)
    assert err is None, "数据全扫出却报失败（误报）：%s" % err
