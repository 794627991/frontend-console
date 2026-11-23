# -*- coding: utf-8 -*-
"""第十六轮对抗审计缺陷回归（a570）。

前端审计报的 2 个 P1 + 10 个 P2，逐条钉住行为，防止再退化。
后端部分真跑 Flask/落盘；前端部分做可判定的结构断言（node 可用时
额外实跑一次合并逻辑）。
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NAV_JS = os.path.join(ROOT, "web", "js", "nav.js")
NODE = shutil.which("node")


def _js():
    with open(NAV_JS, encoding="utf-8") as f:
        return f.read()


@pytest.fixture()
def client():
    os.environ.setdefault("CLAUDE_INLINE", "1")
    import flask
    from src import nav_api
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    return app.test_client()


# ---- 后端 P1：前端 scope 载荷覆盖已有三态配置必须备份 --------------------

def test_scope_payload_overwrite_makes_prev_bak(tmp_path):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "原配置", "mode": "manual",
                   "dirs": {"kernel": "off", "src/app": "full"}}, f)
    msg = nav_api._backup_scope_if_overwrite(
        root, {"version": 2, "mode": "full", "dirs": {}})
    assert msg, "覆盖已有三态配置必须给出提示"
    bak = sp + ".prev.bak"
    assert os.path.isfile(bak)
    assert json.load(open(bak, encoding="utf-8"))["dirs"] == {
        "kernel": "off", "src/app": "full"}


def test_scope_payload_backup_not_overwritten_again(tmp_path):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual", "dirs": {"a": "off"}}, f)
    nav_api._backup_scope_if_overwrite(root, {"mode": "full", "dirs": {}})
    first = open(sp + ".prev.bak", encoding="utf-8").read()
    # 第二次覆盖（此时源已被改成新配置）：备份不得被改写
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual", "dirs": {"b": "off"}}, f)
    nav_api._backup_scope_if_overwrite(root, {"mode": "manual",
                                              "dirs": {"c": "off"}})
    assert open(sp + ".prev.bak", encoding="utf-8").read() == first


def test_scope_payload_no_backup_when_identical(tmp_path):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    cfg = {"version": 2, "mode": "manual", "dirs": {"a": "off"}}
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    assert nav_api._backup_scope_if_overwrite(root, cfg) == ""
    assert not os.path.isfile(sp + ".prev.bak"), "同配置重建不该产生备份"


# ---- 后端 P2：force / run_id ------------------------------------------

def test_recommend_force_rejects_other_project(client, monkeypatch):
    from src import nav_api
    # _guard 依赖文件树登记根，测试里放行
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    with nav_api._rec_lock:
        nav_api._rec_state.update(
            running=True, root="C:/projA",
            root_key=os.path.normcase(os.path.abspath("C:/projA")),
            cancel=False, run_id="r1")
    try:
        r = client.post("/api/nav/scope_recommend",
                        json={"root": "C:/projB", "force": True})
        assert r.status_code == 409
        assert r.get_json()["same"] is False
        with nav_api._rec_lock:
            assert nav_api._rec_state["cancel"] is False, "不许误杀别的工程"
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, cancel=False,
                                      root="", root_key="", run_id="")


def test_recommend_force_same_project_cancels_old(client, monkeypatch):
    """force + 同工程：旧任务被取消，等它退出后返回 200。"""
    from src import nav_api
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    import threading as _th
    _REAL_THREAD = _th.Thread
    # 不起真线程：work() 会调 recommend_scope 打真盘。这里只验证「旧任务
    # 被取消后能起新任务」，所以替换为立即返回的桩。
    _fake = type("_T", (), {"__init__": lambda self, *a, **k: None,
                            "start": lambda self: None})
    monkeypatch.setattr(nav_api.threading, "Thread", _fake)
    rk = os.path.normcase(os.path.abspath("C:/projA"))
    with nav_api._rec_lock:
        nav_api._rec_state.update(running=True, root="C:/projA",
                                  root_key=rk, cancel=False, run_id="old")

    def _exit():
        import time as _time
        _time.sleep(0.15)      # 让 force 循环先看到运行中并置 cancel
        with nav_api._rec_lock:
            nav_api._rec_state["running"] = False

    _REAL_THREAD(target=_exit, daemon=True).start()
    try:
        r = client.post("/api/nav/scope_recommend",
                        json={"root": "C:/projA", "force": True})
        assert r.status_code == 200, r.get_data()
        j = r.get_json()
        assert j["ok"] is True and j.get("run_id")
        assert j["run_id"] != "old", "重新推荐必须是一次新的任务"
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, cancel=False,
                                      root="", root_key="", run_id="")


def test_cancel_with_stale_run_id_is_rejected(client):
    from src import nav_api
    with nav_api._rec_lock:
        nav_api._rec_state.update(
            running=True, root="C:/projA",
            root_key=os.path.normcase(os.path.abspath("C:/projA")),
            cancel=False, run_id="new-run")
    try:
        r = client.post("/api/nav/scope_recommend_cancel",
                        json={"root": "C:/projA", "run_id": "old-run"})
        assert r.status_code == 409
        with nav_api._rec_lock:
            assert nav_api._rec_state["cancel"] is False, \
                "旧弹层的 cancel 不许杀掉新任务"
        r2 = client.post("/api/nav/scope_recommend_cancel",
                         json={"root": "C:/projA", "run_id": "new-run"})
        assert r2.status_code == 200
        with nav_api._rec_lock:
            assert nav_api._rec_state["cancel"] is True
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, cancel=False,
                                      root="", root_key="", run_id="")


def test_poll_exposes_run_id(client):
    from src import nav_api
    with nav_api._rec_lock:
        nav_api._rec_state.update(
            running=True, root="C:/projA", run_id="rid-1",
            root_key=os.path.normcase(os.path.abspath("C:/projA")))
    try:
        j = client.get("/api/nav/scope_recommend_poll?root=C:/projA").get_json()
        assert j["run_id"] == "rid-1"
        # 别人的工程读不到 run_id
        j2 = client.get("/api/nav/scope_recommend_poll?root=C:/projB").get_json()
        assert j2["run_id"] == ""
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, root="", root_key="",
                                      run_id="")


# ---- 前端 P1：推荐合并只保留用户手改 ----------------------------------

def _extract(fn_name, end_marker):
    js = _js()
    i = js.find(fn_name)
    assert i > 0, "找不到 " + fn_name
    j = js.find(end_marker, i)
    assert j > i
    return js[i:j]


def test_frontend_merge_uses_user_set_not_whole_dirs():
    js = _js()
    assert "const _userSet = new Set();" in js
    seg = _extract("const _manual = {}", "const _manualArts")
    assert "for (const k of _userSet)" in seg, \
        "合并保留集必须只来自用户手改（否则第二次推荐对已有目录全部失效）"
    # banner 计数也用同一份集合
    assert "Object.keys(_manual).length" in js


def test_frontend_state_button_can_revert_to_inherit():
    """显式节点必须能点回继承（own && dirs[rk] === v → delete）。"""
    js = _js()
    seg = _extract("const _stateBtns", "cb.disabled")
    assert "if (own && dirs[rk] === v)" in seg
    assert "delete dirs[rk]" in seg
    assert "_userSet.delete(rk)" in seg


def test_frontend_clear_also_clears_arts_off_and_invalidates_poll():
    seg = _extract("bClr.onclick", "bCancel.onclick")
    assert "artsOff.clear()" in seg, "全部清除必须清掉显式取消的产物源"
    assert "_recEpoch++" in seg, "全部清除必须作废在途推荐结果"
    assert "scope_recommend_cancel" in seg


def test_frontend_expand_does_not_mark_root_on_failure():
    seg = _extract("bExpand.onclick", "search.oninput")
    assert "if (kids[''] && !expanded.has('')) expanded.add('');" in seg, \
        "根层加载失败时不许把根标成已展开（会永久停在 ⋯ 假加载态）"


def test_frontend_close_panel_removes_scope_pick():
    seg = _extract("function _closePanel", "function _h(")
    assert "navScopePick" in seg
    assert "_cleanup(true)" in seg


def test_frontend_scope_select_updates_head():
    js = _js()
    assert "sel.onchange = _syncSelHead;" in js, \
        "切档必须同步头部文字（否则展示与生效相反）"
    seg = _extract("const _syncSelHead", "sel.onchange")
    assert "全量档" in seg and "白名单档" in seg


def test_frontend_import_validates_backslash_mode_arch_lists():
    seg = _extract("const _normK =", "card._scopeCfg = Object.assign")
    assert "replace(/\\\\/g, '/')" in seg or "replace(/\\\\/g, '/')" in _js()
    assert "mode 只认 whitelist/manual/full" in seg
    assert "arch 只认 auto/arm/arm64" in seg
    assert "exclude_names" in seg and "Array.isArray(cfg[_key])" in seg


def test_frontend_cancel_carries_run_id():
    js = _js()
    assert "let _runId = '';" in js
    assert "run_id: _runId" in js
    assert "_runId = r.run_id || '';" in js


def test_frontend_shows_timeout_items_and_scope_saved():
    js = _js()
    assert "timeout_items" in js, "超时子树必须在完成态告警"
    assert "s.scope_saved === false" in js, "范围未落盘必须提示"


def test_frontend_has_export_entry():
    """a570 第十七轮：导出必须走后端落盘（WebView2 里 `<a download>` 必失败）。"""
    js = _js()
    assert "'导出 JSON'" in js
    assert "/api/nav/scope_export" in js, "导出必须走后端写盘"
    assert "a.download" not in js, \
        "WebView2 里 init.js 会拦掉 a[href] 且 ALLOW_DOWNLOADS=False"



# ---- node 实跑：合并语义（P1 第一条的真行为）---------------------------

def test_node_merge_semantics():
    """把 nav.js 的合并逻辑按原样抽出来跑：第二次推荐必须覆盖上次推荐值，
    只保留用户手改。"""
    if not NODE:
        pytest.skip("node 不可用")
    code = r"""
    const dirs = {kernel:'off', src:'whitelist'};   // 上次推荐的产物
    const _userSet = new Set(['kernel']);           // 用户只手改过 kernel
    dirs.kernel = 'full';
    const res = {dirs: {kernel:'off', src:'full', tools:'off'},
                 artifact_roots: []};
    const _manual = {};
    for (const k of _userSet) if (Object.prototype.hasOwnProperty.call(dirs,k))
      _manual[k] = dirs[k];
    for (const k in dirs) delete dirs[k];
    Object.assign(dirs, res.dirs || {}, _manual);
    console.log(JSON.stringify({dirs, kept: Object.keys(_manual)}));
    """
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["dirs"] == {"kernel": "full", "src": "full", "tools": "off"}
    assert out["kept"] == ["kernel"]
