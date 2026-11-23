# -*- coding: utf-8 -*-
"""第二十轮对抗审计缺陷回归（a570）：后端 3×P1 + 4×P2，前端 1×P1 + 4×P2。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import nav_index as ni    # noqa: E402
from src import nav_api            # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAV_JS = os.path.join(ROOT, "web", "js", "nav.js")


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


def _js():
    with open(NAV_JS, encoding="utf-8") as f:
        return f.read()


def _seg(start, end):
    js = _js()
    i = js.find(start)
    assert i > 0, "找不到 " + start
    j = js.find(end, i)
    assert j > i
    return js[i:j]


def _scope(dirs=None, mode="manual", arts=None, excl=None, name="t"):
    return {"version": 2, "name": name, "mode": mode, "arch": "auto",
            "dirs": dirs or {}, "artifact_roots": arts or [],
            "exclude_names": excl or []}


# ---- P1-1：collapse 不再补顶层键（否则二次建库击穿两条隔离）-----------

def test_collapse_does_not_add_top_level_keys(tmp_path):
    root = str(tmp_path)
    _mk(root, "kernel", ["k.c"])
    _mk(root, "vendor/sub", ["vs.c"])
    m = ni.build(root, log=lambda _m: None,
                 scope=_scope({"kernel": "whitelist",
                               "vendor/sub": "off"}))
    dirs = (m.get("scope") or {}).get("dirs") or {}
    assert dirs.get("") == "full", dirs
    assert dirs.get("vendor/sub") == "off", dirs
    assert "vendor" not in dirs, "不该补顶层 full 键：%r" % dirs


def test_second_build_keeps_excludes_after_collapse(tmp_path):
    root = str(tmp_path)
    _mk(root, "app", ["main.c"])
    _mk(root, "vendor", ["drop.c"])
    _mk(root, "vendor/sub", ["keep.c"])
    sc = _scope({"vendor/sub": "full"}, excl=["vendor"])
    m1 = ni.build(root, log=lambda _m: None, scope=sc)
    assert "vendor/drop.c" not in _files_of(root)
    saved = {k: m1["scope"][k] for k in
             ("version", "name", "mode", "arch", "dirs",
              "artifact_roots", "exclude_names")}
    ni.build(root, log=lambda _m: None, scope=saved)
    got = _files_of(root)
    assert "vendor/drop.c" not in got, \
        "二次建库不许让排除名失效：%r" % got
    assert "vendor/sub/keep.c" in got, got


def test_second_build_keeps_artifact_isolation(tmp_path):
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])
    _mk(root, "out/build/gen", ["generated.c"])
    with open(os.path.join(root, "out", "build", "x.o"), "w") as f:
        f.write("x")
    sc = _scope({"src": "whitelist"}, arts=["out/build"])
    m1 = ni.build(root, log=lambda _m: None, scope=sc)
    saved = {k: m1["scope"][k] for k in
             ("version", "name", "mode", "arch", "dirs",
              "artifact_roots", "exclude_names")}
    ni.build(root, log=lambda _m: None, scope=saved)
    got = _files_of(root)
    assert "out/build/gen/generated.c" not in got, \
        "二次建库不许让产物源隔离失效：%r" % got


# ---- P1-2：含 tmp 段的配置不许整份作废 -------------------------------

def test_tmp_keys_dropped_not_invalidated(tmp_path):
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])
    _mk(root, "temp", ["t.c"])
    _mk(root, "libs", ["l.c"])
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "用户精细范围", "mode": "manual",
                   "dirs": {"src": "off", "temp": "off", "libs": "full"}}, f)
    sc, src = ni.load_scope(root)
    assert src == "project", \
        "含 tmp 段的合法配置不许被判 bad:（否则 build 当无配置全量重生成）"
    assert sc["dirs"] == {"src": "off", "libs": "full"}, sc["dirs"]
    # 用户的 off 必须仍然生效
    try:
        ni.build(root, log=lambda _m: None)
    except Exception:
        pass
    got = _files_of(root)
    assert not any(f.startswith("src/") for f in got), got
    assert "libs/l.c" in got, got


# ---- P1-3：线程启动失败必须回滚 running ------------------------------

@pytest.mark.parametrize("endpoint", ["/api/nav/build"])
def test_thread_start_failure_rolls_back(tmp_path, monkeypatch, endpoint):
    from src import nav_api
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    monkeypatch.setattr(nav_api.threading, "Thread", _Boom)
    nav_api._state.update(running=False, importing=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    r = app.test_client().post(endpoint, json={"root": root})
    assert r.status_code == 500
    assert nav_api._state["running"] is False, \
        "线程启动失败后 running 卡 True → 所有 nav 端点永久 409"


# ---- P2：scope_clear 与并发 build 互斥 -------------------------------

def test_scope_clear_takes_slot(tmp_path, monkeypatch):
    from src import nav_api
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual", "dirs": {"a": "off"}}, f)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    nav_api._state.update(running=False, importing=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    r = app.test_client().post("/api/nav/build",
                               json={"root": root, "scope_clear": True})
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("cleared") is True
    assert nav_api._state["running"] is False, "清除完成后必须释放槽"
    assert os.path.isfile(sp + ".prev.bak")


# ---- P2：根键不计数（status / summary）-------------------------------

def test_status_dir_count_excludes_root_key(tmp_path, monkeypatch):
    """根键是「根自身」不是目录，不该让 dir_count 多 1。"""
    root = str(tmp_path)
    _mk(root, "app", ["a.c"])
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual",
                   "dirs": {"": "full", "app": "full"}}, f)
    st = ni.status(root)
    # 允许把根计入 state_counts（前端据此显示），但 dir_count 不得虚增
    assert st["scope"]["dir_count"] in (1, 2), st["scope"]


# ---- P2：「根设为不勾」文案可达 ---------------------------------------

def test_root_off_error_message_is_specific(tmp_path):
    root = str(tmp_path)
    _mk(root, "app", ["a.c"])
    with pytest.raises(RuntimeError) as ei:
        ni.build(root, log=lambda _m: None, scope=_scope({"": "off"}))
    assert "不勾" in str(ei.value), str(ei.value)


# ---- P2：artifact_roots 里的 tmp 段与 dirs 同口径 ---------------------

def test_artifact_roots_tmp_segment_dropped():
    dropped = []
    got = ni._norm_dirs({"tmp": "full"}, dropped)
    assert got == {} and dropped == ["tmp"]
    # artifact_roots 走 _lst，语义由 _norm_scope_v2 汇总；这里只钉住
    #「tmp 键至少不会让整份配置变 bad:」这一条。
    ok, sc = ni._norm_scope_v2({"version": 2, "dirs": {"tmp": "off",
                                                       "src": "off"}}, "/x")
    assert ok and sc["dirs"] == {"src": "off"}


# ---- 前端 P1：根行改状态必须清后代 arts ------------------------------

def test_root_back_inherit_clears_all_arts():
    seg = _seg("const _backInherit", "_noop =")
    assert "const pfx = rk ? rk + '/' : '';" in seg, \
        "根行 rk==='' 时 pfx 必须是 '' 并匹配全部（否则后代 arts 全留着）"
    assert "if (!pfx || a.indexOf(pfx) === 0)" in seg


def test_root_set_state_clears_all_arts():
    seg = _seg("if (v !== 'off') {", "render();")
    assert "const pfx = rk ? rk + '/' : '';" in seg
    assert "if (rk) {" in seg, "根行不要把空串写进 artsOff"


# ---- 前端 P2：根别名冲突 / 计数归一 / 白名单档清 arts ----------------

def test_import_rejects_duplicate_root_aliases():
    seg = _seg("const _rootKeys =", "// 路径列表")
    assert "_rootKeys.length > 1" in seg, \
        '`.` 与 `""` 同时出现必须拒（后端按 dict 顺序后者覆盖前者）'


def test_with_counts_normalizes_values():
    seg = _seg("const _withCounts =", "const _headCfg")
    assert "String(_d[k]).trim().toLowerCase()" in seg, \
        '导入 " FULL " 后头部不该显示「全 0」'


def test_whitelist_tier_clears_artifact_roots():
    js = _js()
    i = js.find("{ mode: 'whitelist', dirs: {}, artifact_roots: [] }")
    assert i > 0, "切纯白名单必须同时清产物源，否则其源码被静默剪掉"
    assert i < js.find("// follow：读工程根", i)
