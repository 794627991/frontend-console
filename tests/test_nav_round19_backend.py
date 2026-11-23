# -*- coding: utf-8 -*-
"""第十九轮后端审计缺陷回归（a570）：3×P1 + 3×P2。"""
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


def _files_of(root):
    p = os.path.join(ni.lib_dir(root), "files.txt")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(os.path.relpath(ln, root).replace(os.sep, "/"))
                except ValueError:
                    out.append(ln.replace(os.sep, "/"))
    return out


# ---- P1-1：根键不能当 live 证据 ---------------------------------------

def test_root_key_not_in_live_set(tmp_path):
    """`_live_set` 若含根键，任意路径都判「在 live 子树内」→ 排除名与
    产物源隔离全部失效。"""
    root = str(tmp_path)
    _mk(root, "app", ["main.c"])
    _mk(root, "vendor", ["drop.c"])
    _mk(root, "vendor/sub", ["keep.c"])
    sc = {"mode": "manual",
          "dirs": {"": "full", "vendor/sub": "full"}}
    got = list(ni._walk_files(root, state_of=ni._make_state_of(sc),
                              excl_names=["vendor"], say=lambda _m: None))
    rels = {r for _, r in got}
    assert "vendor/drop.c" not in rels, "根键让排除名失效：%r" % rels
    assert "vendor/sub/keep.c" in rels, rels


def test_root_key_does_not_disable_artifact_isolation(tmp_path):
    root = str(tmp_path)
    _mk(root, "build/host", ["tool.c"])
    with open(os.path.join(root, "build", "x.o"), "w") as f:
        f.write("x")
    sc = {"mode": "manual", "dirs": {"": "full"}}
    got = list(ni._walk_files(root, state_of=ni._make_state_of(sc),
                              artifact_roots=["build"], say=lambda _m: None))
    rels = {r for _, r in got}
    assert "build/host/tool.c" not in rels, \
        "根键让产物源隔离失效：%r" % rels
    assert "build/x.o" in rels, rels


# ---- P1-2：只要根直下有源码才写根键 -----------------------------------

def test_collapse_wl_root_key_safe_for_excludes(tmp_path):
    """降级后写根键是必需的（表达「未显式区全量」），但必须**不能**让
    exclude_names / artifact_roots 隔离失效——关键是不再补顶层 full 键。"""
    root = str(tmp_path)
    _mk(root, "app", ["main.c"])
    _mk(root, "vendor", ["drop.c"])
    _mk(root, "vendor/sub", ["keep.c"])
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual", "dirs": {}}, f)
    sc = {"version": 2, "name": "t", "mode": "manual", "arch": "auto",
          "dirs": {"vendor/sub": "full"}, "artifact_roots": [],
          "exclude_names": ["vendor"]}
    m1 = ni.build(root, log=lambda _m: None, scope=sc)
    got1 = _files_of(root)
    assert "vendor/drop.c" not in got1, got1
    # 用第一次的实际范围重建（模拟落盘后再读回）
    saved = {k: m1["scope"][k] for k in
             ("version", "name", "mode", "arch", "dirs",
              "artifact_roots", "exclude_names")}
    ni.build(root, log=lambda _m: None, scope=saved)
    got2 = _files_of(root)
    assert "vendor/drop.c" not in got2, \
        "二次建库不许因自动补键让排除名失效：%r" % got2

    dirs = saved["dirs"]
    assert "" in dirs
    # 关键：除显式节点外不许有任何自动补出来的顶层 full 键
    assert set(dirs) <= {"vendor/sub", ""}, dirs


def test_collapse_wl_writes_root_key_for_real_root_source(tmp_path):
    root = str(tmp_path)
    with open(os.path.join(root, "rootfile.c"), "w") as f:
        f.write("int x;\n")
    _mk(root, "src", ["a.c"])
    m = ni.build(root, log=lambda _m: None,
                 scope={"version": 2, "name": "t", "mode": "manual",
                        "arch": "auto", "dirs": {"src": "whitelist"},
                        "artifact_roots": [], "exclude_names": []})
    assert (m.get("scope") or {}).get("dirs", {}).get("") == "full"


# ---- P1-3：full_dirs 里的空键必须命中所有路径 -------------------------

def test_under_any_empty_key_matches_everything():
    assert ni._under_any("rootfile.c", [""]) is True
    assert ni._under_any("app/main.c", ["", "app"]) is True
    assert ni._under_any("x.c", []) is False


def test_root_full_dir_marks_in_build(tmp_path):
    """三态树根行点「全」后，根直下源码的 in_build 必须是 True。"""
    root = str(tmp_path)
    with open(os.path.join(root, "rootfile.c"), "w") as f:
        f.write("int root_sym;\n")
    _mk(root, "app", ["main.c"])
    sc = {"version": 2, "name": "t", "mode": "manual", "arch": "auto",
          "dirs": {"": "full", "app": "whitelist"},
          "artifact_roots": [], "exclude_names": []}
    try:
        ni.build(root, log=lambda _m: None, scope=sc)
    except Exception:
        pass
    mf = json.load(open(os.path.join(ni.lib_dir(root), "manifest.json"),
                        encoding="utf-8"))
    assert "" in (mf.get("full_dirs") or []), mf.get("full_dirs")


# ---- P2：任务占用时不许有任何写操作 -----------------------------------

def test_clear_rejected_when_busy_does_not_delete(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual", "dirs": {"a": "off"}}, f)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    nav_api._state.update(running=True, root="other", importing=False)
    try:
        import flask
        app = flask.Flask(__name__)
        app.register_blueprint(nav_api.nav_bp)
        r = app.test_client().post("/api/nav/build",
                                   json={"root": root, "scope_clear": True})
        assert r.status_code == 409
        assert os.path.isfile(sp), "被拒的清除请求不许删配置"
        assert not os.path.isfile(sp + ".prev.bak")
    finally:
        nav_api._state.update(running=False, root="")


def test_backup_rejected_when_busy(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual",
                   "dirs": {"src": "off"}}, f)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    nav_api._state.update(running=True, root="other", importing=False)
    try:
        import flask
        app = flask.Flask(__name__)
        app.register_blueprint(nav_api.nav_bp)
        r = app.test_client().post("/api/nav/build", json={
            "root": root,
            "scope": {"version": 2, "mode": "full", "dirs": {}}})
        assert r.status_code == 409
        assert not os.path.isfile(sp + ".prev.bak"), \
            "被拒请求不许写备份（否则真正覆盖时告警丢失）"
    finally:
        nav_api._state.update(running=False, root="")


# ---- P2：scope_tree 的 sub 与 tmp 同口径 ------------------------------

def test_scope_tree_sub_ignores_tmp(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    _mk(root, "onlysub/tmp", ["t.c"])
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    j = app.test_client().get("/api/nav/scope_tree?root=" + root).get_json()
    row = [d for d in j["dirs"] if d["name"] == "onlysub"][0]
    assert row["sub"] is False, "唯一子目录是 tmp 时不该显示展开箭头"


# ---- P2：tmp 键被 _norm_dirs 拒绝 ------------------------------------

def test_norm_dirs_drops_tmp_keys():
    """a570 第二十轮：tmp 键**忽略**而不是判整份非法——判非法会让配置变
    `bad:`，build 随即当无配置全量重生成并覆盖写盘（丢用户配置）。"""
    dropped = []
    assert ni._norm_dirs({"tmp": "full"}, dropped) == {}
    assert dropped == ["tmp"]
    dropped2 = []
    assert ni._norm_dirs({"a/temp": "off"}, dropped2) == {}
    assert dropped2 == ["a/temp"]
    assert ni._norm_dirs({"a/b": "off"}) == {"a/b": "off"}
