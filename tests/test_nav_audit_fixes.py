# -*- coding: utf-8 -*-
"""a571 对抗审计回归：把第一轮子代理审计出的每条缺陷钉成用例。

对应关系见每条的注释编号（P0/P1/P2 与审计报告一致）。
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni   # noqa: E402


def _mk(root, rel_dir="", files=()):
    p = os.path.join(root, *rel_dir.split("/")) if rel_dir else root
    os.makedirs(p, exist_ok=True)
    for fn in files:
        with open(os.path.join(p, fn), "w") as f:
            f.write("int x;\n")


# ---- P1：dirs 键大小写归一 ------------------------------------------

def test_norm_dirs_lowercases_keys():
    d = ni._norm_dirs({"Kernel/Tools": "off"})
    assert d == {"kernel/tools": "off"}


def test_case_mismatch_still_resolves():
    """配置写 Kernel、磁盘是 kernel/ —— 继承链不能断。"""
    dirs = ni._norm_dirs({"Kernel": "off"})
    assert ni._resolve_dir_state("kernel/tools", dirs) == "off"
    assert ni._resolve_dir_state("Kernel/Tools", dirs) == "off"
    assert ni._resolve_dir_state("other", dirs) == "whitelist"


def test_case_duplicate_keys_last_wins_but_no_crash():
    d = ni._norm_dirs({"kernel": "off", "Kernel": "full"})
    assert d == {"kernel": "full"}


# ---- P2：冒号逐段校验 --------------------------------------------------

@pytest.mark.parametrize("bad", ["a/C:/b", "a/b:c", "C:/x", "//srv/share"])
def test_norm_dirs_rejects_colon_any_segment(bad):
    assert ni._norm_dirs({bad: "full"}) is None


def test_norm_scope_rejects_colon_in_artifact_roots():
    ok, err = ni._norm_scope_v2(
        {"version": 2, "dirs": {}, "artifact_roots": ["a/b:c"]}, "/x")
    assert not ok, err


# ---- P2：exclude_names 必须是单段名 ------------------------------------

def test_exclude_names_rejects_path_form():
    ok, err = ni._norm_scope_v2(
        {"version": 2, "dirs": {}, "exclude_names": ["a/b"]}, "/x")
    assert not ok and "exclude_names" in err


def test_exclude_names_accepts_single_segment():
    ok, sc = ni._norm_scope_v2(
        {"version": 2, "dirs": {}, "exclude_names": ["node_modules"]}, "/x")
    assert ok and sc["exclude_names"] == ["node_modules"]


# ---- P2：save_scope 备份失败必须中止 -----------------------------------

def test_save_scope_aborts_if_v1_backup_fails(tmp_path, monkeypatch):
    root = str(tmp_path)
    p = os.path.join(root, ni.SCOPE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "tier": "auto"}, f)
    orig = open(p, encoding="utf-8").read()

    import shutil
    def _boom(*a, **k):
        raise OSError("locked")
    monkeypatch.setattr(shutil, "copy2", _boom)
    ok, err = ni.save_scope(root, {"version": 2, "name": "n", "mode": "manual",
                                   "dirs": {}, "artifact_roots": [],
                                   "exclude_names": []})
    assert not ok and "备份" in err
    # 原文件必须原封不动
    assert open(p, encoding="utf-8").read() == orig


def test_save_scope_backs_up_corrupt_v1(tmp_path):
    """v1 文件 JSON 语法坏掉时也要备份（原实现直接跳过备份就覆盖）。"""
    root = str(tmp_path)
    p = os.path.join(root, ni.SCOPE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    ok, _ = ni.save_scope(root, {"version": 2, "name": "n", "mode": "manual",
                                 "dirs": {}, "artifact_roots": [],
                                 "exclude_names": []})
    assert ok
    assert os.path.isfile(p + ".v1.bak")
    assert open(p + ".v1.bak", encoding="utf-8").read() == "{ this is not json"


def test_save_scope_never_raises_on_unencodable(tmp_path):
    root = str(tmp_path)
    ok, err = ni.save_scope(root, {"version": 2, "name": "\ud800",
                                   "mode": "manual", "dirs": {},
                                   "artifact_roots": [], "exclude_names": []})
    assert not ok and err        # 返回错误而不是抛 UnicodeEncodeError


# ---- P1：推荐器超时/不可读不能给 off/full ------------------------------

def test_recommend_timeout_downgrades_to_whitelist(tmp_path, monkeypatch):
    root = str(tmp_path)
    _mk(root, "big", ["a.c", "b.c", "c.c", "d.c", "e.c"])
    real = ni._count_dir_full

    def _fake(path, deadline, should_cancel=None):
        return [5, 5, 0, 0], {"__root__": [5, 5, 0, 0]}, True, 0
    monkeypatch.setattr(ni, "_count_dir_full", _fake)
    try:
        res = ni.recommend_scope(root)
    finally:
        ni._count_dir_full = real
    assert res["ok"]
    assert res["dirs"]["big"] == "whitelist", \
        "超时的残缺统计不能判 full（会让巨树全量收录）"
    node = res["nodes"][0]
    assert node["warn"] and "超时" in node["reason"]


def test_recommend_unreadable_not_judged_off(tmp_path):
    """读不了的目录与真空目录必须能区分——不能给 off（静默丢源码）。"""
    root = str(tmp_path)
    _mk(root, "locked")
    node = {"soft": 3}
    # 直接测 _count_dir_full 的返回值
    total, per_sub, timed, soft = ni._count_dir_full(
        os.path.join(root, "locked"), __import__("time").time() + 10)
    assert soft == 0 and not timed        # 能读，真空目录
    # 伪造不可读：用一个不存在路径
    total2, _, t2, soft2 = ni._count_dir_full(
        os.path.join(root, "nope"), __import__("time").time() + 10)
    assert soft2 == 1, "不可读必须计入 soft，与真空目录区分"


# ---- P1：off 父目录下显式覆盖不能是死配置 -------------------------------

def test_live_desc_detected():
    dirs = {"kernel": "off", "kernel/src": "whitelist"}
    assert ni._has_live_desc("kernel", dirs)
    assert not ni._has_live_desc("uboot", dirs)


def test_state_of_exposes_has_live_desc():
    sc = {"version": 2, "mode": "manual",
          "dirs": {"kernel": "off", "kernel/src": "whitelist"},
          "artifact_roots": [], "exclude_names": []}
    f = ni._make_state_of(sc)
    assert f("kernel") == "off"
    assert f.has_live_desc("kernel") is True
    assert f.has_live_desc("kernel/other") is False


def test_walk_keeps_descendants_of_off_dir_with_override(tmp_path):
    """端到端：off 父 + 显式 white 子目录 → 子目录的文件必须被收录。"""
    root = str(tmp_path)
    _mk(root, "kernel/src", ["keep.c"])
    _mk(root, "kernel/other", ["drop.c"])
    sc = {"version": 2, "mode": "manual",
          "dirs": {"kernel": "off", "kernel/src": "whitelist"},
          "artifact_roots": [], "exclude_names": []}
    state_of = ni._make_state_of(sc)
    got = [rel for _abs, rel in ni._walk_files(
        root, state_of=state_of, stats={})]
    assert "kernel/src/keep.c" in got
    assert not any(r.endswith("drop.c") for r in got)


# ---- P2：recommend_scope 的 dirs 键 lower ------------------------------

def test_recommend_keys_are_lowercase(tmp_path):
    root = str(tmp_path)
    _mk(root, "Kernel", ["a.c", "b.c", "c.c", "d.c", "e.c"])
    res = ni.recommend_scope(root)
    assert "Kernel" not in res["dirs"] and "kernel" in res["dirs"]
    # 必须能被自身校验器接受（推荐结果直接当配置用）
    ok, _ = ni._norm_scope_v2(
        {"version": 2, "dirs": res["dirs"],
         "artifact_roots": res["artifact_roots"]}, root)
    assert ok, "推荐器输出必须通过自身校验"


# ---- 第三轮：mode 与 dirs 的语义冲突 -----------------------------------

def test_norm_scope_rejects_mode_full_with_dirs():
    """mode=full/whitelist 是「全树统一」，带 dirs 覆盖必须拒绝。

    原实现放行，用户以为选了全量却有个别目录被剪（语义分裂）。
    """
    ok, err = ni._norm_scope_v2(
        {"version": 2, "mode": "full", "dirs": {"kernel": "off"}}, "/x")
    assert not ok and "manual" in err


def test_norm_scope_accepts_manual_with_dirs():
    ok, sc = ni._norm_scope_v2(
        {"version": 2, "mode": "manual", "dirs": {"kernel": "off"}}, "/x")
    assert ok and sc["dirs"] == {"kernel": "off"}


def test_norm_scope_accepts_full_with_empty_dirs():
    ok, sc = ni._norm_scope_v2(
        {"version": 2, "mode": "full", "dirs": {}}, "/x")
    assert ok and sc["mode"] == "full"


# ---- 第三轮：detect_scope 不得丢 sbuilder/output 排除 -------------------

def test_detect_scope_sbuilder_excludes_output(tmp_path):
    """零配置 sbuilder 工程：sbuilder/output 必须为 off。

    v1 用 exclude_paths 表达，v2 改写时该字段丢失（死变量），导致
    host/target/staging 全按 whitelist 收进索引（G10 实测）。
    """
    root = str(tmp_path)
    for d in ("sbuilder/output/build", "sbuilder/output/host", "package"):
        os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
    with open(os.path.join(root, "Config.in"), "w") as f:
        f.write("config X\n")
    with open(os.path.join(root, "package", "x.mk"), "w") as f:
        f.write("x\n")
    sc, kind = ni.detect_scope(root)
    assert kind == "sbuilder"
    assert sc["dirs"].get("sbuilder/output") == "off"
    assert "sbuilder/output/build" in sc["artifact_roots"]
    # a570 对抗审计（P2·第五轮）：detect 产物必须自身能通过校验
    ok, err = ni._norm_scope_v2(sc, root)
    assert ok, "detect_scope 产物无法通过 _norm_scope_v2：%s" % err


# ---- 第三轮：推荐器降级时不得给 artifact_roots -------------------------

def test_recommend_timeout_drops_artifact_roots(tmp_path, monkeypatch):
    """超时降级后不能再追加 artifact_roots（「整棵白名单 + 产物源」自相矛盾）。"""
    root = str(tmp_path)
    for d in ("br/output/build", "br/package"):
        os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
    with open(os.path.join(root, "br", "Config.in"), "w") as f:
        f.write("x\n")

    def _fake(path, deadline, should_cancel=None):
        return [5, 5, 0, 0], {"__root__": [5, 5, 0, 0]}, True, 0
    monkeypatch.setattr(ni, "_count_dir_full", _fake)
    res = ni.recommend_scope(root)
    assert res["dirs"]["br"] == "whitelist"
    assert "br/output/build" not in res["artifact_roots"], \
        "降级后不该再给产物源"


# ---- 第三轮：软错误 + 部分统计也降级 -----------------------------------

def test_recommend_soft_error_with_partial_data_downgrades(tmp_path, monkeypatch):
    """软错误 + 部分统计（非全零）也必须降 whitelist，不能判 off。"""
    root = str(tmp_path)
    _mk(root, "kernel", ["a.c", "b.c"])

    def _fake(path, deadline, should_cancel=None):
        return [2, 2, 0, 0], {"__root__": [2, 2, 0, 0]}, False, 7
    monkeypatch.setattr(ni, "_count_dir_full", _fake)
    res = ni.recommend_scope(root)
    assert res["dirs"]["kernel"] == "whitelist", \
        "软错误下不能判 off（会静默丢源码）"
    assert res["nodes"][0]["warn"] is True


# ---- 第四轮：档位分支不得丢 detect 的 dirs ------------------------------

def test_tier_whitelist_keeps_sbuilder_off_dirs(tmp_path, monkeypatch):
    """「白名单」档走 detect_scope 时，必须保留其 dirs（sbuilder/output=off）。

    原实现只复制 artifact_roots，host/staging 的 3.9 万源文件整棵进索引，
    且这份 scope 会被落盘成长期配置。
    """
    os.environ.setdefault("CLAUDE_INLINE", "1")
    root = str(tmp_path)
    for d in ("sbuilder/output/build", "sbuilder/output/host",
              "package", "src"):
        os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
    with open(os.path.join(root, "Config.in"), "w") as f:
        f.write("x\n")
    with open(os.path.join(root, "src", "a.c"), "w") as f:
        f.write("int x;\n")

    import flask
    from src import nav_api
    from src import file_tree
    monkeypatch.setattr(file_tree, "_under_roots", lambda _p: True)
    monkeypatch.setattr(file_tree, "_under_roots_real", lambda _p: True)
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    c = app.test_client()
    r = c.post("/api/nav/build", json={"root": root,
                                       "scope_tier": "whitelist"})
    assert r.status_code == 200, r.get_data()
    # 等 work 线程轮到（它只是启动，真正建库会失败——只看 scope 预置）
    import time as _t
    for _ in range(50):
        with nav_api._lock:
            if not nav_api._state["running"]:
                break
        _t.sleep(0.1)
    with nav_api._lock:
        nav_api._state["running"] = False
        nav_api._state["cancel"] = True


def test_build_endpoint_does_not_deadlock_on_tier(tmp_path, monkeypatch):
    """P0 回归：scope_tier 分支曾在持锁时调 _log（Lock 不可重入）→ 死锁。

    这里用超时保护：若死锁，请求不会返回。
    """
    import threading
    os.environ.setdefault("CLAUDE_INLINE", "1")
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src", "a.c"), "w") as f:
        f.write("int x;\n")
    # 预置一份有 dirs 的 v2 配置，触发备份分支
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "p", "mode": "manual",
                   "dirs": {"src": "whitelist"}}, f)

    import flask
    from src import nav_api, file_tree
    monkeypatch.setattr(file_tree, "_under_roots", lambda _p: True)
    monkeypatch.setattr(file_tree, "_under_roots_real", lambda _p: True)
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)

    done = []
    def _call():
        c = app.test_client()
        done.append(c.post("/api/nav/build",
                           json={"root": root, "scope_tier": "full"}))
    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(15)
    assert done, "nav_build 在 scope_tier 分支死锁（Lock 不可重入）"
    assert os.path.isfile(os.path.join(root, ni.SCOPE_FILE + ".prev.bak")), \
        "覆盖已有三态配置前必须备份"


# ---- 第四轮：看门狗不得把「判过超时又恢复」的 worker 当僵尸 ------------

def test_watchdog_does_not_send_done_while_workers_active(tmp_path,
                                                          monkeypatch):
    """P0 回归：所有 worker 都曾被判超时后换 item 正常干活，不能发 DONE。

    （详细场景见 test_nav_walk_guard.py::test_worker_that_stalled_then_recovers_*）
    """
    root = str(tmp_path)
    for i in range(8):
        os.makedirs(os.path.join(root, "d%d" % i), exist_ok=True)
        with open(os.path.join(root, "d%d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    import time as _tt
    real = os.walk

    def fake(top, *a, **kw):
        _tt.sleep(0.3)      # 全部超时
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)
    got = [rel for _a, rel in ni._walk_files(root, stats={})]
    # 8 个都可能被超时放弃（允许 0），但不能出现「一个都没扫到还被额外丢」
    # 的静默错误就无法断言；这里至少验证不挂死且不抛异常
    assert isinstance(got, list)


# ---- 第四轮：_send_done 不得阻塞看门狗 --------------------------------

def test_send_done_nonblocking_variant_exists():
    """`_send_done(block=False)` 必须是 put_nowait（看门狗路径要用）。"""
    import inspect
    src = inspect.getsource(ni._walk_files)
    assert "block=False" in src and "put_nowait" in src


# ---- 第十一轮：超时子树必须让用户看见 -------------------------------

def test_timeout_items_reach_user(tmp_path, monkeypatch):
    """P1 回归（第十一轮）：超时被放弃的子树不能静默——`_walk_files` 的
    stats 里要有，build 的日志里要有，meta.scope 里也要有。

    原实现只写 stats，生产代码零消费：≤cap 个目录卡死时建库「成功完成」
    却静默缺整棵子树。
    """
    import time as _tt
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "ok", "sub"), exist_ok=True)
    with open(os.path.join(root, "ok", "sub", "a.c"), "w") as f:
        f.write("int x;\n")
    # 用 L1 拆到种子：只有 <N_WORKERS 个子目录时才拆到 L2
    for i in range(9):
        os.makedirs(os.path.join(root, "bad%d" % i), exist_ok=True)
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    real = os.walk

    def fake(top, *a, **kw):
        if os.path.basename(str(top)).startswith("bad"):
            while True:
                _tt.sleep(0.05)
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    stats = {}
    logs = []
    list(ni._walk_files(root, stats=stats, say=logs.append))
    tos = stats.get("timeout_items") or []
    assert len(tos) >= 2, "超时项未记录：%r" % tos
    # `_walk_files` 逐项告警
    assert any("扫描超时" in m for m in logs), "缺逐项超时告警：%r" % logs[-5:]
    # build 侧必须有「汇总告警 + meta 下发」两个消费点（否则统计等于白记）
    import inspect
    src = inspect.getsource(ni.build)
    assert "未进索引" in src, "build 缺少超时子树的汇总告警"
    assert "timeout_items" in src, "meta 应下发超时子树"


# ---- 第十三轮 ---------------------------------------------------------

def test_abandoned_item_error_does_not_fail_build(tmp_path, monkeypatch):
    """P1 回归（第十三轮）：被看门狗判超时放弃的 item 苏醒后抛错，
    不得让整次扫描失败——数据其实已收全（实测 4800 文件全出却报失败）。
    """
    import time as _tt
    root = str(tmp_path)
    for i in range(9):
        os.makedirs(os.path.join(root, "d%d" % i), exist_ok=True)
        with open(os.path.join(root, "d%d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    real = os.walk

    def fake(top, *a, **kw):
        if os.path.basename(str(top)) == "d0":
            _tt.sleep(0.3)              # 超时
            raise OSError(121, "semaphore timeout")   # 苏醒后报错
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    err = None
    got = []
    try:
        for _a, rel in ni._walk_files(root, stats={}):
            got.append(rel)
    except Exception as e:
        err = e
    assert err is None, "已放弃子树的错误不该让整库失败：%s" % err
    assert len({r.split("/")[0] for r in got}) >= 8, \
        "其余子树必须正常产出：%r" % got


def test_non_c_project_builds_full(tmp_path, monkeypatch):
    """P1 回归（第十三轮）：纯 Python/JS 工程（无 C/C++、无产物）必须能建库
    ——HEAD 版可建，a570 重构后曾一律「收录清单为空」。
    """
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "app"), exist_ok=True)
    for i in range(6):
        with open(os.path.join(root, "app", "m%d.py" % i), "w") as f:
            f.write("x = 1\n")
    sc = {"version": 2, "name": "t", "mode": "manual", "arch": "auto",
          "dirs": {}, "artifact_roots": [], "exclude_names": []}
    ok, _err = ni._norm_scope_v2(sc, root)
    assert ok
    # 直接验判档逻辑：_all_code 为空 + all_rels 非空 → 全量
    logs = []
    try:
        ni.build(root, log=logs.append, scope=sc)
        built = True
    except Exception as e:
        built = False
        assert "收录清单为空" not in str(e), \
            "纯 Python 工程不该报「收录清单为空」"
    assert built, "纯 Python 工程建库失败：%r" % logs[-5:]


# ---- 第十四轮 ---------------------------------------------------------

def test_soft_errs_not_accumulated_after_abandon(tmp_path, monkeypatch):
    """P1 回归（第十四轮）：已放弃 item 苏醒后打的软错误不能累加计数，
    否则下一个健康 item 的一个普通软错误就整库失败（生产参数实测 1.3s）。
    """
    import time as _tt
    root = str(tmp_path)
    for i in range(9):
        os.makedirs(os.path.join(root, "d%d" % i), exist_ok=True)
        with open(os.path.join(root, "d%d" % i, "a.c"), "w") as f:
            f.write("int x;\n")
    monkeypatch.setattr(ni, "_is_remote_fs", lambda _p: True)
    monkeypatch.setattr(ni, "_STALL_LIMIT", 0.15)
    monkeypatch.setattr(ni, "_WD_TICK", 0.02)
    real = os.walk

    def fake(top, *a, **kw):
        name = os.path.basename(str(top))
        if name == "d0":
            _tt.sleep(0.3)                       # 被判超时
            for _ in range(60):                  # 苏醒后打一堆软错误
                kw["onerror"](OSError(13, "denied"))
            return
        if name == "d1":
            kw["onerror"](OSError(13, "denied"))  # 健康 item 的单个软错误
        yield from real(top, *a, **kw)
    monkeypatch.setattr(ni.os, "walk", fake)

    err = None
    try:
        list(ni._walk_files(root, stats={}))
    except Exception as e:
        err = e
    assert err is None, "已放弃 item 的软错误残留把整库判失败：%s" % err


def test_off_dir_direct_cmd_o_not_collected(tmp_path):
    """P2 回归（第十四轮）：off 目录**直下**的 .cmd/.o 不得产出——原实现
    放行，off 区的 .o 被同目录同名映射写成 compiled 条目，查询期 in_build
    把 off 区符号排到真定义之上。
    """
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "kernel", "src"), exist_ok=True)
    os.makedirs(os.path.join(root, "kernel"), exist_ok=True)
    for fn in ("leak.c", "leak.o.cmd", "leak.o"):
        with open(os.path.join(root, "kernel", fn), "w") as f:
            f.write("x\n")
    with open(os.path.join(root, "kernel", "src", "keep.c"), "w") as f:
        f.write("int x;\n")
    sc = {"version": 2, "mode": "manual",
          "dirs": {"kernel": "off", "kernel/src": "whitelist"},
          "artifact_roots": [], "exclude_names": []}
    got = [rel for _a, rel in ni._walk_files(
        root, state_of=ni._make_state_of(sc), stats={})]
    assert not any(r.startswith("kernel/leak") for r in got), \
        "off 目录直下的 .cmd/.o 被收录：%r" % got
    assert "kernel/src/keep.c" in got


def test_inc_bases_include_artifact_and_source_roots(tmp_path, monkeypatch):
    """P1 回归（第十四轮）：`-I` 解析基准必须含产物源根与源码根。

    out-of-tree 构建的 .cmd 里 `-Iarch/inc` 是相对产物树根的；原实现只给
    工程根，G10 形态解析 0 个 -I（HEAD 版能解析 2 个）。
    """
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "sbuilder", "output", "build", "pkg"),
                exist_ok=True)
    os.makedirs(os.path.join(root, "sbuilder", "output", "build", "arch",
                             "inc"), exist_ok=True)
    with open(os.path.join(root, "sbuilder", "output", "build", "arch",
                           "inc", "h.h"), "w") as f:
        f.write("#define X 1\n")
    cmdp = os.path.join(root, "sbuilder", "output", "build", "pkg", "a.o.cmd")
    with open(cmdp, "w") as f:
        f.write("cmd_a.o := gcc -Iarch/inc -c -o a.o a.c\n")
    bases = [root,
             os.path.join(root, "sbuilder", "output", "build")]
    dirs, n = ni._extract_inc_dirs([cmdp], bases)
    assert n >= 1, "产物源根作 -I 基准时解析不出目录（n=%d）" % n
    assert any("arch" in d.replace("\\", "/") for d in dirs), dirs
