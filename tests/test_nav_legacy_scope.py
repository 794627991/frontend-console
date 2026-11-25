# -*- coding: utf-8 -*-
"""2026-11-25 审查 a697（内网补丁合入外网）时的实测缺陷与回归钉测。

a697 自述「只做语法检查，功能验证由内网实机进行」。外网这边实测到并修掉的：

  1. 没有 `confirmed` 键的旧配置一律被当成「从未经确认」而弃用——a697 之前存下的
     配置**都没有这个键**，用户在三态树上配好、面板存下的也一样。实测：用户手写的
     `src:off / libs:full` 被日志说成「工具自动生成」，建库后磁盘上的配置被推荐结果
     覆盖成全不勾并标上 confirmed:true。现在按名字分：只有工具自动写的那几种才算未确认。
  2. 全新小工程（每个顶层目录的代码文件都不到 5 个、没有编译产物）首次建库报
     「收录清单为空」；a697 之前按源码全量兜底、照常收录。现在推荐器在全不勾时
     把「仅仅因为代码少」的有代码目录改推荐为全量。
  3. 直调 build()（ask_scope=None）没有人作答，日志却写「推荐器（用户已确认）」，
     落盘 confirmed:true。现在只有真的问过用户才算已确认（与 detect 分支口径一致）。
  4. 三个 walk-guard 测试钉的是被 a697 有意删掉的旧契约——已在
     tests/test_nav_walk_guard.py 里改写；本文件不重复。
"""
import json
import os
import sys
import time

import flask
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import nav_api, nav_index as ni    # noqa: E402


# 没带 confirmed 键的用户配置——a697 之前面板存下来的都是这个样子
LEGACY_USER = {"version": 2, "name": "用户精细范围", "mode": "manual",
               "dirs": {"src": "off", "temp": "off", "libs": "full"}}


def _mk(root, rel_dir, files):
    p = os.path.join(root, *rel_dir.split("/"))
    os.makedirs(p, exist_ok=True)
    for fn in files:
        with open(os.path.join(p, fn), "w") as f:
            f.write("int %s;\n" % fn[0])


def _scope_path(root):
    return os.path.join(root, ni.SCOPE_FILE)


def _write_scope(root, cfg):
    with open(_scope_path(root), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return _scope_path(root)


def _read_scope(root):
    with open(_scope_path(root), encoding="utf-8") as f:
        return json.load(f)


def _files_of(root):
    p = os.path.join(ni.lib_dir(root), "files.txt")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(os.path.relpath(ln, root).replace(os.sep, "/"))
    return out


def _tiny_project(root):
    """没有编译产物、每个顶层目录的代码文件都不到 5 个的小工程。"""
    _mk(root, "src", ["a.c", "b.c"])
    _mk(root, "libs", ["l.c"])


# ---- 1. 旧配置：用户的照旧生效，工具自动写的仍然重新推荐 ----------------

def test_legacy_user_scope_without_confirmed_is_honored(tmp_path):
    root = str(tmp_path)
    _tiny_project(root)
    sp = _write_scope(root, LEGACY_USER)
    with open(sp, encoding="utf-8") as f:
        before = f.read()

    sc, src = ni.load_scope(root)
    assert src == "project"
    assert sc["confirmed"] is True, "用户存下的旧配置不该被当成「从未经确认」"
    st = ni.status(root)
    assert st["scope"]["name"] == "用户精细范围"
    assert st["scope"]["confirmed"] is True, "面板与建库的口径必须一致"

    log = []
    ni.build(root, log=log.append)
    files = _files_of(root)
    assert "libs/l.c" in files, files
    assert not any(f.startswith("src/") for f in files), "用户的 off 必须仍然生效"
    with open(sp, encoding="utf-8") as f:
        assert f.read() == before, "用用户自己的配置建库，不该改写它"
    assert not any("推荐" in x for x in log), "有用户配置就不该跑推荐器"


def test_legacy_auto_scope_without_confirmed_is_still_unconfirmed(tmp_path):
    """内网 G10 那种残缺骨架（名字是工具自动写的）意图不变：照样重新推荐 + 确认。"""
    root = str(tmp_path)
    _mk(root, "app", ["a%d.c" % i for i in range(6)])
    _write_scope(root, {"version": 2, "name": "sbuilder 方案（自动检测）",
                        "mode": "manual",
                        "dirs": {"sbuilder": "off", "sbuilder/output": "off"}})
    sc, src = ni.load_scope(root)
    assert src == "project" and sc["confirmed"] is False

    asked = []
    log = []
    res = ni.build(root, log=log.append,
                   ask_scope=lambda rec: asked.append(rec) or "accept")
    assert len(asked) == 1
    # 弹窗文案要据实：工程根有一份工具自动生成、未经确认的配置，不是「尚无配置」
    assert asked[0].get("had_auto_cfg") is True
    assert any("从未经确认" in x for x in log), log
    assert res["scope"]["confirmed"] is True
    disk = _read_scope(root)
    assert disk["confirmed"] is True
    # 名字后缀是落盘时既有的自动改写（白名单推导为空 → 自动全量），这里只认前缀
    assert disk["name"].startswith("推荐配置"), disk["name"]


@pytest.mark.parametrize("value,confirmed", [
    (True, True), (False, False), ("false", False), ("true", False), (1, False),
])
def test_explicit_confirmed_key_wins(tmp_path, value, confirmed):
    root = str(tmp_path)
    _tiny_project(root)
    cfg = dict(LEGACY_USER, confirmed=value)
    _write_scope(root, cfg)
    sc, _src = ni.load_scope(root)
    assert sc["confirmed"] is confirmed, "显式写了 confirmed 就以它为准（只认布尔 True）"


@pytest.mark.parametrize("name,confirmed", [
    ("sbuilder 方案（自动检测）", False),
    ("源码树内产物（自动检测）", False),
    ("源码树内产物（自动检测）（自动降级为全量）", False),
    ("自动（隐式范围）", False),
    ("未命名范围", True),
    ("", True),
    ("我的范围", True),
    ("自动检测", True),          # 只是名字像，不是工具写的那几种
])
def test_only_tool_written_names_count_as_unconfirmed(tmp_path, name, confirmed):
    root = str(tmp_path)
    _tiny_project(root)
    _write_scope(root, dict(LEGACY_USER, name=name))
    sc, _src = ni.load_scope(root)
    assert sc["confirmed"] is confirmed, name


def test_api_build_with_legacy_user_scope_does_not_ask(tmp_path, monkeypatch):
    """界面路径：有用户存下的旧配置时不弹确认窗、不跑推荐器。"""
    root = str(tmp_path)
    _tiny_project(root)
    _write_scope(root, LEGACY_USER)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    nav_api._state.update(running=False, importing=False)
    calls = []
    orig = ni.recommend_scope
    monkeypatch.setattr(ni, "recommend_scope",
                        lambda *a, **k: calls.append(1) or orig(*a, **k))
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    try:
        r = app.test_client().post("/api/nav/build", json={"root": root})
        assert r.status_code == 200 and r.get_json().get("ok") is True, r.get_data()
        deadline = time.time() + 90
        while time.time() < deadline and not nav_api._state["done"]:
            time.sleep(0.05)
        s = nav_api._state
        assert s["done"] and s["ok"], s.get("err")
        assert calls == [], "用户存下的旧配置不该被弃用去跑推荐器"
        assert s["ask_scope"] is None and s["ask_tier"] is None
        assert "libs/l.c" in _files_of(root), _files_of(root)
    finally:
        nav_api._state.update(running=False, importing=False, done=False, ok=False,
                              err="", result=None, reason="", cancelled=False)


# ---- 2. 小工程首次建库：推荐全不勾时不能是空索引 ------------------------

def test_all_off_recommendation_promotes_tiny_code_dirs_to_full(tmp_path):
    root = str(tmp_path)
    _tiny_project(root)
    rec = ni.recommend_scope(root)
    assert rec["ok"], rec
    assert rec["dirs"] == {"src": "full", "libs": "full"}, rec["dirs"]
    assert all(n["warn"] for n in rec["nodes"]), "改推荐过的目录要带告警，提醒用户确认"
    assert all("按全量收录" in n["reason"] for n in rec["nodes"])


def test_tiny_project_first_build_indexes_sources(tmp_path):
    """a697 之后这里是 RuntimeError: 收录清单为空；a697 之前 3 个文件照收。"""
    root = str(tmp_path)
    _tiny_project(root)
    log = []
    ni.build(root, log=log.append)
    assert {"libs/l.c", "src/a.c", "src/b.c"} <= set(_files_of(root)), _files_of(root)
    assert any("改推荐为全量" in x for x in log), log


def test_all_off_fallback_leaves_name_rule_dirs_alone(tmp_path):
    """只动「仅仅因为代码少」被判不勾的目录；按名字判的（比如 release）不动。"""
    root = str(tmp_path)
    _mk(root, "src", ["a.c"])
    _mk(root, "release", ["r.c"])
    rec = ni.recommend_scope(root)
    assert rec["dirs"] == {"src": "full", "release": "off"}, rec["dirs"]


def test_all_off_fallback_not_triggered_when_something_is_indexable(tmp_path):
    root = str(tmp_path)
    _mk(root, "app", ["a%d.c" % i for i in range(6)])     # 有代码、无产物 → 全量
    _mk(root, "tools", ["t.c"])                           # 代码极少 → 不勾
    rec = ni.recommend_scope(root)
    assert rec["dirs"] == {"app": "full", "tools": "off"}, rec["dirs"]


# ---- 3. 「用户已确认」只在实际问过时才成立 ------------------------------

def _six_file_project(root):
    _mk(root, "app", ["a%d.c" % i for i in range(6)])


def test_direct_build_does_not_claim_user_confirmation(tmp_path):
    root = str(tmp_path)
    _six_file_project(root)
    log = []
    res = ni.build(root, log=log.append)          # ask_scope=None：没有人作答
    assert not any("用户已确认" in x for x in log), log
    assert any("推荐器（未经确认" in x for x in log), log
    assert res["scope"]["confirmed"] is False
    assert _read_scope(root)["confirmed"] is False, \
        "没人确认过就落盘 confirmed:true，之后的建库会永久跳过推荐与确认"


def test_accepted_recommendation_is_confirmed(tmp_path):
    root = str(tmp_path)
    _six_file_project(root)
    log = []
    res = ni.build(root, log=log.append, ask_scope=lambda rec: "accept")
    assert any("推荐器（用户已确认）" in x for x in log), log
    assert res["scope"]["confirmed"] is True
    assert _read_scope(root)["confirmed"] is True


def test_failing_confirmation_callback_is_not_user_confirmation(tmp_path):
    root = str(tmp_path)
    _six_file_project(root)
    def boom(_rec):
        raise RuntimeError("确认通道断了")
    res = ni.build(root, log=lambda _m: None, ask_scope=boom)
    assert res["scope"]["confirmed"] is False
    assert _read_scope(root)["confirmed"] is False


def test_cancelled_recommendation_builds_nothing(tmp_path):
    root = str(tmp_path)
    _six_file_project(root)
    log = []
    with pytest.raises(ni.Cancelled):
        ni.build(root, log=log.append, ask_scope=lambda rec: "cancel")
    assert not os.path.exists(_scope_path(root))


# ---- 前端：确认弹窗的文案据实 ------------------------------------------

def test_scope_dialog_text_is_truthful_about_existing_config():
    js = open(os.path.join(ROOT, "web", "js", "nav.js"), encoding="utf-8").read()
    assert "rec && rec.had_auto_cfg" in js
    assert "工程根已有一份工具自动生成、从未经确认的收录范围" in js
    assert "该工程尚无收录范围配置" in js        # 真的没有配置时仍是这句
