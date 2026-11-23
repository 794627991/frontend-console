# -*- coding: utf-8 -*-
"""第十六轮后端对抗审计缺陷回归（a570）。

覆盖 2 个 P0 + 4 个 P1 + 5 个 P2，全部来自子代理实测复现的场景。
"""
import json
import os
import sys

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
    """files.txt 里是绝对路径；归一成 posix rel 供断言。"""
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


# ---- P0-2：显式 dirs 下白名单区推导为零时不许硬失败 --------------------

def test_explicit_whitelist_empty_units_falls_back_to_full(tmp_path):
    """推荐器给的 {kernel: whitelist} + 零产物 → 原先「收录清单为空」。"""
    root = str(tmp_path)
    for i in range(10):
        _mk(root, "kernel", ["f%d.c" % i])
    _mk(root, "vendor", ["v.c"])
    sc = _scope({"kernel": "whitelist", "vendor": "off"})
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except RuntimeError as e:
        pytest.fail("必须降级而不是硬失败：%s" % e)
    got = _files_of(root)
    assert any(f.startswith("kernel/") for f in got), got
    assert not any(f.startswith("vendor/") for f in got), "显式 off 区必须仍被剪"


def test_explicit_off_only_python_project_succeeds(tmp_path):
    """纯 Python 工程 + 用户只勾了一个「不」→ 原先硬失败。"""
    root = str(tmp_path)
    _mk(root, "app", ["a.py", "b.py"])
    _mk(root, "vendor", ["v.py"])
    sc = _scope({"vendor": "off"})
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except RuntimeError as e:
        pytest.fail("非 C/C++ + 显式 off 区必须能建库：%s" % e)
    got = _files_of(root)
    assert any(f.startswith("app/") for f in got), got
    assert not any(f.startswith("vendor/") for f in got), got


def test_explicit_mixed_full_area_survives(tmp_path):
    """mixed 档（tools: full）在 kernel 白名单区为零时不能被一起降级掉。"""
    root = str(tmp_path)
    _mk(root, "kernel/lib", ["a.c"])
    _mk(root, "tools", ["t.c"])
    sc = _scope({"kernel": "whitelist", "tools": "full"})
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    mf = json.load(open(os.path.join(ni.lib_dir(root), "manifest.json"),
                        encoding="utf-8"))
    assert "tools" in (mf.get("full_dirs") or []), mf.get("full_dirs")


# ---- P0-1：nav_api 必须落盘 build 实际用过的范围 ------------------------

def test_api_saves_effective_scope_not_requested(tmp_path, monkeypatch):
    root = str(tmp_path)
    _mk(root, "kernel", ["a.c"])
    req = _scope({"kernel": "whitelist", "vendor": "off"})
    # 真实 build 会降级；这里直接给出「降级后的」返回，验证落盘取值来源
    eff = _scope({"kernel": "full", "vendor": "off"},
                 name="t（白名单推导为空，自动全量）")
    eff["mode"] = "manual"

    def _fake_build(r, **kw):
        return {"ok": True, "scope": eff}

    monkeypatch.setattr(ni, "build", _fake_build)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    monkeypatch.setattr(nav_api, "_backup_scope_if_overwrite",
                        lambda *a, **k: "")
    # 别起真线程：直接交换 Thread 为同步执行器
    class _Sync:
        def __init__(self, target=None, daemon=None):
            self._t = target

        def start(self):
            self._t()

    monkeypatch.setattr(nav_api.threading, "Thread", _Sync)
    nav_api._state.update(running=False, importing=False)
    rv = nav_api.nav_build.__wrapped__() if hasattr(
        nav_api.nav_build, "__wrapped__") else None
    # 用 Flask 测试客户端走真实端点
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    c = app.test_client()
    r = c.post("/api/nav/build", json={"root": root, "scope": req})
    assert r.status_code == 200, r.get_data()
    saved = json.load(open(os.path.join(root, ni.SCOPE_FILE), encoding="utf-8"))
    assert saved["dirs"].get("kernel") == "full", \
        "落盘必须是 build 实际用的范围，否则下次建库静默收窄"
    nav_api._state.update(running=False, importing=False)


# ---- P1：exclude_names 不该压过显式后代 --------------------------------

def test_user_exclude_does_not_kill_explicit_descendant(tmp_path):
    root = str(tmp_path)
    _mk(root, "vendor/mylib/src", ["keep.c"])
    _mk(root, "vendor/mylib", ["drop.c"])
    sc = _scope({"vendor/mylib/src": "full"}, excl=["vendor"])
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    got = _files_of(root)
    assert "vendor/mylib/src/keep.c" in got, \
        "用户显式勾了 full 的子树不能被 exclude_names 剪掉：%r" % got
    assert "vendor/mylib/drop.c" not in got, got


def test_hard_skip_dirs_still_pruned_with_explicit_child(tmp_path):
    """_SKIP_DIRS（.git 等）不受影响——只有用户 exclude_names 让路。"""
    root = str(tmp_path)
    _mk(root, ".git/src", ["x.c"])
    sc = _scope({".git/src": "full"})
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    assert not any(".git" in f for f in _files_of(root))


# ---- P1：分片阶段取消 / 不可读根 ---------------------------------------

def test_prepare_phase_honours_cancel(tmp_path):
    root = str(tmp_path)
    for i in range(8):
        _mk(root, "d%d" % i, ["a.c"])
    with pytest.raises(ni.Cancelled):
        list(ni._walk_files(root, should_cancel=lambda: True,
                            say=lambda _m: None))


def test_unreadable_base_is_soft_skipped(tmp_path, monkeypatch):
    """收录根 scandir 抛 PermissionError → 软跳过而不是整库 RuntimeError。"""
    root = str(tmp_path)
    _mk(root, "good", ["a.c"])
    _mk(root, "bad", ["b.c"])
    real_scandir = os.scandir

    def _scandir(d):
        if os.fspath(d).rstrip("\\/").lower().endswith("bad"):
            raise PermissionError(13, "denied")
        return real_scandir(d)

    monkeypatch.setattr(ni.os, "scandir", _scandir)
    got = list(ni._walk_files(root, subs=["bad"], say=lambda _m: None,
                              state_of=lambda _r: "full"))
    assert got == [], "不可读根必须软跳过（零文件）而不是抛错"


# ---- P1：推荐器跳过 tmp 与逐目录取消 -----------------------------------

def test_recommend_skips_tmp_like_walk(tmp_path):
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])
    _mk(root, "tmp", ["b.c"])
    r = ni.recommend_scope(root, say=lambda _m: None)
    assert r["ok"]
    assert "tmp" not in r["dirs"], \
        "推荐器必须与 walk 同口径跳过 tmp（否则确认后零文件）"


def test_recommend_cancel_checked_each_top(tmp_path):
    root = str(tmp_path)
    for i in range(3):
        _mk(root, "d%d" % i, ["a.c"])
    with pytest.raises(ni.Cancelled):
        ni.recommend_scope(root, should_cancel=lambda: True,
                           say=lambda _m: None)


# ---- P2：已放弃 item 的软错误不计 soft_skipped -------------------------

def test_discarded_item_soft_errors_not_counted(tmp_path):
    """形态检查：soft_skipped 的累加必须在 _discarded 判定之内。"""
    import inspect
    src = inspect.getsource(ni._walk_files)
    i = src.find('if not _discarded:\n                                _soft_errs[0] += 1')
    if i < 0:
        # 缩进不同也能匹配：找 _on_err 内的 _soft_errs 累加点
        i = src.find("_soft_errs[0] += 1")
        assert i > 0
    seg = src[i:i + 500]
    assert 'stats["soft_skipped"]' in seg, \
        "soft_skipped 必须与 _soft_errs 同处 not _discarded 分支内（否则假告警）"


# ---- P2：walk 正常结束即摘超时登记（长尾假告警）-----------------------

def test_walk_completion_unregisters_item():
    import inspect
    src = inspect.getsource(ni._walk_files)
    i = src.find("for r, ds, fs in os.walk(sub, onerror=_on_err):")
    assert i > 0
    seg = src[i:i + 6000]
    assert "_sub_start.pop(me, None)" in seg, \
        "walk 正常结束必须摘掉超时登记，否则慢收尾被记成「未进索引」"


# ---- P2：artifact 区里显式 white/full 不被 _only_art 吃掉 ---------------

def test_explicit_state_inside_artifact_root_still_indexed(tmp_path):
    root = str(tmp_path)
    _mk(root, "out/pkg", ["real.c"])
    _mk(root, "out/other", ["gen.c"])
    sc = _scope({"out": "off", "out/pkg": "whitelist"},
                arts=["out"])
    # whitelist 需要产物才有结果，这里只验证 _only_art 不再吞掉显式区
    got = list(ni._walk_files(
        root, state_of=ni._make_state_of(sc), artifact_roots=sc["artifact_roots"],
        say=lambda _m: None))
    rels = {r for _, r in got}
    assert "out/pkg/real.c" in rels, rels
    assert "out/other/gen.c" not in rels, rels


# ---- P2：scope_clear 的磁盘 I/O 不在 _lock 内 --------------------------

def test_scope_clear_io_outside_lock():
    import inspect
    src = inspect.getsource(nav_api.nav_build)
    i = src.find('d.get("scope_clear")')
    assert i > 0
    # 该分支之前最近的 with _lock: 之后必须已闭合（即不在锁内）
    after = src[i:i + 600]
    assert "with _lock:" not in after.split("with _lock:")[0] or True
    # 更直接的判据：删除语句不在任何 with _lock 的缩进块里
    lines = src[i:].splitlines()
    rm_idx = next(j for j, ln in enumerate(lines) if "os.remove(_sp)" in ln)
    indent = len(lines[rm_idx]) - len(lines[rm_idx].lstrip())
    for ln in reversed(lines[:rm_idx]):
        if not ln.strip():
            continue
        li = len(ln) - len(ln.lstrip())
        if li < indent:
            assert not ln.strip().startswith("with _lock:"), \
                "scope_clear 的 isfile/remove 不许在 _lock 内做（SMB 往返阻塞全局）"
            break


# ---- P2：落盘补 full 的键必须 lower -----------------------------------

def test_save_full_dirs_uses_lower_keys(tmp_path):
    import inspect
    src = inspect.getsource(ni.build)
    i = src.find('_sp.get("mode") == "full"')
    assert i > 0
    seg = src[i:i + 1200]
    assert ".lower()" in seg, "补 full 的键必须 lower 归一，否则与 dirs 键撞车"
