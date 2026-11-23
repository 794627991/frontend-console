# -*- coding: utf-8 -*-
"""第十七轮后端审计缺陷回归（a570）。

2×P0 + 5×P1 + 4×P2，全部来自子代理实测复现。
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni    # noqa: E402
from src import nav_api            # noqa: E402


def _mk(root, rel_dir="", files=()):
    p = os.path.join(root, *rel_dir.split("/")) if rel_dir else root
    os.makedirs(p, exist_ok=True)
    for fn in files:
        with open(os.path.join(p, fn), "w") as f:
            f.write("int x;\n")
    return p


def _scope(dirs=None, mode="manual", arts=None, excl=None, name="t"):
    return {"version": 2, "name": name, "mode": mode, "arch": "auto",
            "dirs": dirs or {}, "artifact_roots": arts or [],
            "exclude_names": excl or []}


def _files_of(root):
    p = os.path.join(ni.lib_dir(root), "files.txt")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(os.path.relpath(ln, root).replace(os.sep, "/"))
            except ValueError:
                out.append(ln.replace(os.sep, "/"))
    return out


# ---- P0-1：显式 live 节点自身命中 exclude_names -------------------------

def test_explicit_live_dir_matching_exclude_name_still_indexed(tmp_path):
    root = str(tmp_path)
    _mk(root, "src/include", ["a.c", "b.c"])
    _mk(root, "src/other", ["o.c"])
    sc = _scope({"src/include": "full"}, excl=["include"])
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except RuntimeError as e:
        pytest.fail("显式勾选的目录不能被同名排除名剪空：%s" % e)
    got = _files_of(root)
    assert "src/include/a.c" in got, got
    assert "src/include/b.c" in got, got


def test_has_live_desc_includes_self():
    dirs = {"src/include": "full"}
    assert ni._has_live_desc("src/include", dirs) is True, \
        "含自身——否则该目录在 scandir 层就被剪"
    assert ni._has_live_desc("", dirs) is True
    assert ni._has_live_desc("other", dirs) is False


# ---- P0-2：硬规则不被用户排除名解锁 -----------------------------------

def test_hard_skip_not_unlocked_by_user_exclude(tmp_path):
    """硬规则（.git / tmp）不能被用户排除名解锁。

    a570 第十九轮起 `_norm_dirs` 直接拒 tmp 键（死配置），所以这里绕开
    校验、直接构造 state_of，验证 walk 层的硬剪不被 _user_skip 放开。
    """
    root = str(tmp_path)
    _mk(root, ".git/src", ["evil.c"])
    _mk(root, "tmp/src", ["t.c"])
    _mk(root, "app", ["a.c"])
    # 绕开 _norm_dirs（它会直接拒 tmp 键），直接构造 state_of 测 walk 层
    sc = {"mode": "manual",
          "dirs": {".git/src": "full", "tmp/src": "full", "app": "full"}}
    got = list(ni._walk_files(root, state_of=ni._make_state_of(sc),
                              excl_names=[".git", "tmp"],
                              say=lambda _m: None))
    rels = {r for _, r in got}
    assert not any(f.startswith(".git/") for f in rels), rels
    assert not any(f.startswith("tmp/") for f in rels), rels
    assert "app/a.c" in rels, rels


# ---- P1：推荐器 on_prog 校验 run_id -----------------------------------

def test_on_prog_ignores_stale_run_id(tmp_path, monkeypatch):
    """旧任务被守护线程释放后，on_prog 不得改写新任务进度。"""
    from src import nav_api

    def _fake_recommend(r, progress=None, should_cancel=None):
        # 模拟：先让守护线程把槽释放（换 run_id），再继续报进度
        with nav_api._rec_lock:
            nav_api._rec_state["run_id"] = "new-task"
            nav_api._rec_state["cur"] = ""
        progress(50, 100, "OLD#50")
        return {"ok": True, "dirs": {}}

    monkeypatch.setattr(ni, "recommend_scope", _fake_recommend)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    monkeypatch.setattr(nav_api, "_REC_GUARD", 3600.0)
    nav_api._state.update(running=False, importing=False)
    with nav_api._rec_lock:
        nav_api._rec_state.update(running=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    c = app.test_client()
    r = c.post("/api/nav/scope_recommend", json={"root": str(tmp_path)})
    assert r.status_code == 200
    time.sleep(0.2)
    with nav_api._rec_lock:
        assert nav_api._rec_state.get("cur") != "OLD#50", \
            "旧任务的进度不能写进新任务的槽"
        nav_api._rec_state.update(running=False, run_id="", result=None)


def test_slot_release_invalidates_run_id():
    import inspect
    src = inspect.getsource(nav_api.nav_scope_recommend)
    i = src.find("推荐任务超时（扫描卡住）")
    assert i > 0
    seg = src[i:i + 400]
    assert "run_id=uuid.uuid4().hex" in seg, \
        "释放槽必须作废旧凭证，否则旧线程会写成 ok=True+超时错误"


# ---- P1：降级后缀表覆盖全部形态 ---------------------------------------

def test_strip_suffix_covers_all_downgrade_names(tmp_path):
    root = str(tmp_path)
    _mk(root, "kernel", ["a.c"])
    sc = _scope({"kernel": "whitelist"}, name="我的范围（白名单推导为空，自动全量）")
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    # 再建一次：名称不得叠加
    sc2 = _scope({"kernel": "whitelist"},
                 name=json.load(open(os.path.join(root, ni.SCOPE_FILE),
                                     encoding="utf-8")).get("name", "")) \
        if os.path.isfile(os.path.join(root, ni.SCOPE_FILE)) else sc
    try:
        ni.build(root, log=lambda _m: None, scope=sc2)
    except Exception:
        pass
    st = ni.status(root)
    nm = (st.get("scope") or {}).get("name", "")
    assert "白名单推导为空，自动全量）（白名单推导为空" not in nm, nm


# ---- P1：「被调整」判据两边归一 ---------------------------------------

def test_scope_change_detection_normalizes_both_sides(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    _mk(root, "Kernel", ["a.c"])
    req = _scope({"Kernel": "manual" and "full"})
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    monkeypatch.setattr(nav_api, "_backup_scope_if_overwrite", lambda *a, **k: "")
    monkeypatch.setattr(ni, "build",
                        lambda r, **kw: {"ok": True,
                                         "scope": _scope({"kernel": "full"})})
    logs = []
    monkeypatch.setattr(nav_api, "_log", lambda m: logs.append(str(m)))
    nav_api._state.update(running=False, importing=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    app.test_client().post("/api/nav/build", json={"root": root, "scope": req})
    assert not any("被调整" in m for m in logs), \
        "仅大小写差异不是调整：%r" % logs
    nav_api._state.update(running=False, importing=False)


# ---- P1：_collapse_wl 补 full 的顶层来自目录集 -------------------------

def test_collapse_wl_tops_are_dirs_not_files(tmp_path):
    root = str(tmp_path)
    _mk(root, "kernel", ["k.c"])
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write("# t\n")
    _mk(root, "vendor/sub", ["vs.c"])
    sc = _scope({"kernel": "whitelist", "vendor/sub": "off"})
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    # scope 记在库的 meta.json（inline 传入时 build 不落盘工程根）
    meta = json.load(open(os.path.join(ni.lib_dir(root), "meta.json"),
                          encoding="utf-8"))
    dirs = (meta.get("scope") or {}).get("dirs") or {}
    assert "readme.md" not in dirs, "文件名不能当目录键：%r" % dirs
    # a570 第二十轮：不再补顶层 full 键（补出来的键会成为 _live_set 里的
    # 「显式 live 证据」，让 exclude_names/artifact 隔离失效）。根键 ""=full
    # 已完整表达「未显式区全量」，深层 off 与显式节点原样保留。
    assert dirs.get("") == "full", dirs
    assert dirs.get("vendor/sub") == "off", dirs
    assert "vendor" not in dirs, "不该自动补顶层 full 键：%r" % dirs


# ---- P2：artifact 分支也查排除名段 ------------------------------------

def test_artifact_branch_honours_segment_exclude(tmp_path):
    root = str(tmp_path)
    _mk(root, "out/gen/deep", ["keep.c"])
    _mk(root, "out/gen", [])
    with open(os.path.join(root, "out", "gen", "x.o"), "w") as f:
        f.write("x")
    with open(os.path.join(root, "out", "gen", "x.o.cmd"), "w") as f:
        f.write("x")
    sc = _scope({"out": "off", "out/gen/deep": "full"},
                arts=["out"], excl=["gen"])
    got = list(ni._walk_files(
        root, state_of=ni._make_state_of(sc),
        artifact_roots=sc["artifact_roots"], excl_names=sc["exclude_names"],
        say=lambda _m: None))
    rels = {r for _, r in got}
    assert "out/gen/x.o" not in rels, rels
    assert "out/gen/x.o.cmd" not in rels, rels
    assert "out/gen/deep/keep.c" in rels, rels


# ---- P2：force 等待上界不小于取消宽限 --------------------------------

def test_force_deadline_covers_cancel_grace():
    import inspect
    src = inspect.getsource(nav_api.nav_scope_recommend)
    i = src.find("_deadline = time.time() +")
    assert i > 0
    seg = src[i:i + 160]
    assert "_REC_CANCEL_GRACE" in seg, \
        "原 10s 上界 < 30s 取消宽限，硬卡时 force 必然先失败一次"


# ---- P2：指纹对 mode/arch 也 lower -----------------------------------

def test_fingerprint_lowercases_mode_arch():
    a = nav_api._scope_fingerprint({"mode": "MANUAL", "arch": "AUTO",
                                    "dirs": {"A": "FULL"}})
    b = nav_api._scope_fingerprint({"mode": "manual", "arch": "auto",
                                    "dirs": {"a": "full"}})
    assert a == b


# ---- 性能：_under_live 不再是按文件线扫 ------------------------------

def test_under_live_is_prefix_walk():
    import inspect
    src = inspect.getsource(ni._make_state_of)
    i = src.find("def _under_live")
    assert i > 0
    seg = src[i:i + 400]
    assert "rpartition" in seg and "for _k in" not in seg, \
        "每文件线性扫全部 live 键会在大规模下退化 6 倍"
