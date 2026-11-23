# -*- coding: utf-8 -*-
"""第十八轮后端审计缺陷回归（a570）：3×P1 + 4×P2。"""
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


def _scope(dirs=None, mode="manual", arts=None, excl=None, name="t", arch="auto"):
    return {"version": 2, "name": name, "mode": mode, "arch": arch,
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
            if ln:
                try:
                    out.append(os.path.relpath(ln, root).replace(os.sep, "/"))
                except ValueError:
                    out.append(ln.replace(os.sep, "/"))
    return out


# ---- P1-1：artifact 区不能因「继承的根默认」被当成显式 live -----------

def test_artifact_area_not_opened_by_inherited_default(tmp_path):
    root = str(tmp_path)
    _mk(root, "rootfs", ["r.c"])
    _mk(root, "sbuilder/output/build", ["tool.c"])
    _mk(root, "sbuilder/output/build/src", ["a.c"])
    with open(os.path.join(root, "sbuilder", "output", "build", "x.o"), "w") as f:
        f.write("x")
    sc = _scope({"rootfs": "off"}, arts=["sbuilder/output/build"])
    got = list(ni._walk_files(
        root, state_of=ni._make_state_of(sc),
        artifact_roots=sc["artifact_roots"], say=lambda _m: None))
    rels = {r for _, r in got}
    assert "sbuilder/output/build/src/a.c" not in rels, \
        "产物源区源码必须只收 .cmd/.o：%r" % sorted(rels)
    assert "sbuilder/output/build/x.o" in rels, rels


def test_artifact_area_still_opens_for_explicit_live(tmp_path):
    root = str(tmp_path)
    _mk(root, "out/pkg", ["real.c"])
    _mk(root, "out/other", ["gen.c"])
    sc = _scope({"out": "off", "out/pkg": "full"}, arts=["out"])
    got = list(ni._walk_files(
        root, state_of=ni._make_state_of(sc),
        artifact_roots=sc["artifact_roots"], say=lambda _m: None))
    rels = {r for _, r in got}
    assert "out/pkg/real.c" in rels, rels
    assert "out/other/gen.c" not in rels, rels


# ---- P1-2：scope_tier 覆盖也走完整指纹备份 ----------------------------

def test_tier_overwrite_backs_up_artifact_only_config(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "detect 产物", "mode": "whitelist",
                   "arch": "auto", "dirs": {},
                   "artifact_roots": ["sbuilder/output/build"],
                   "exclude_names": ["noise"]}, f)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    monkeypatch.setattr(ni, "build", lambda r, **kw: {"ok": True})
    nav_api._state.update(running=False, importing=False)
    logs = []
    monkeypatch.setattr(nav_api, "_log", lambda m: logs.append(str(m)))
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    r = app.test_client().post("/api/nav/build",
                               json={"root": root, "scope_tier": "full"})
    assert r.status_code == 200, r.get_data()
    bak = sp + ".prev.bak"
    assert os.path.isfile(bak), \
        "含 artifact_roots/exclude_names 的有效配置也必须备份"
    assert json.load(open(bak, encoding="utf-8"))["exclude_names"] == ["noise"]
    assert any(".prev.bak" in m for m in logs), logs
    nav_api._state.update(running=False, importing=False)


# ---- P1-3：根直下源码在第二次建库不能丢 ------------------------------

def test_root_files_survive_collapse_and_rebuild(tmp_path):
    root = str(tmp_path)
    with open(os.path.join(root, "rootfile.c"), "w") as f:
        f.write("int x;\n")
    _mk(root, "src", ["a.c"])
    sc = _scope({"src": "whitelist"})
    m1 = ni.build(root, log=lambda _m: None, scope=sc)
    assert "rootfile.c" in _files_of(root), _files_of(root)
    # 第一次降级后的实际范围（含根键 ""）就是「落盘后再读回」的内容。
    # meta.scope 还带 source/timeout_items 等展示字段，回传前按 API 口径挑。
    saved = {k: m1["scope"][k] for k in
             ("version", "name", "mode", "arch", "dirs",
              "artifact_roots", "exclude_names")}
    with open(os.path.join(root, "src", "a.cmd"), "w") as f:
        f.write("-I.")
    with open(os.path.join(root, "src", "a.o"), "w") as f:
        f.write("x")
    ni.build(root, log=lambda _m: None, scope=saved)
    got = _files_of(root)
    assert "rootfile.c" in got, "根直下源码第二次建库丢失：%r" % got


def test_collapse_wl_writes_root_key(tmp_path):
    root = str(tmp_path)
    with open(os.path.join(root, "rootfile.c"), "w") as f:
        f.write("int x;\n")
    _mk(root, "src", ["a.c"])
    meta = ni.build(root, log=lambda _m: None,
                    scope=_scope({"src": "whitelist"}))
    dirs = (meta.get("scope") or {}).get("dirs") or {}
    assert dirs.get("") == "full", "必须用根键表达根自身：%r" % dirs


# ---- P2：面板不展示 tmp（与 walk 硬剪同口径）-------------------------

def test_scope_tree_hides_tmp(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])
    _mk(root, "tmp", ["t.c"])
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    j = app.test_client().get("/api/nav/scope_tree?root=" + root).get_json()
    names = [d["name"] for d in j["dirs"]]
    assert "tmp" not in names, "面板展示 tmp 但 walk 硬剪 → 用户点了没用：%r" % names
    assert "src" in names


# ---- P2：O_EXCL 不覆盖用户已确认的保存框路径 -------------------------

def test_export_respects_picked_overwrite(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual", "dirs": {"a": "off"}}, f)
    mine = os.path.join(str(tmp_path), "mine.json")
    with open(mine, "w", encoding="utf-8") as f:
        f.write("OLD CONTENT")
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)

    import sys as _sys
    import types
    mod = _sys.modules.get("src.main")
    if mod is None:
        mod = types.ModuleType("src.main")
        monkeypatch.setitem(_sys.modules, "src.main", mod)
    # 真实 src.main 可能已被其他用例导入——直接给它挂 picker，避免落到桌面
    monkeypatch.setattr(mod, "_save_file_dialog", lambda _fn: mine,
                        raising=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    j = app.test_client().post("/api/nav/scope_export",
                               json={"root": root}).get_json()
    assert j["ok"], j
    assert j["path"] == mine, "用户确认覆盖的文件不能被改名成 -1"
    assert "OLD CONTENT" not in open(mine, encoding="utf-8").read()
    assert not os.path.isfile(os.path.join(str(tmp_path), "mine-1.json"))


# ---- P2：arch 随 meta 落地 -------------------------------------------

def test_arch_persists_through_api(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])

    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    monkeypatch.setattr(nav_api, "_backup_scope_if_overwrite", lambda *a, **k: "")
    nav_api._state.update(running=False, importing=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    r = app.test_client().post("/api/nav/build", json={
        "root": root, "scope": _scope({"src": "whitelist"}, arch="arm64")})
    assert r.status_code == 200
    # 建库是异步任务：等它落盘
    for _ in range(60):
        time.sleep(0.2)
        with nav_api._lock:
            if nav_api._state["done"]:
                break
    saved = json.load(open(os.path.join(root, ni.SCOPE_FILE), encoding="utf-8"))
    assert saved["arch"] == "arm64", "inline scope 的 arch 不许被静默改写"
    nav_api._state.update(running=False, importing=False)
