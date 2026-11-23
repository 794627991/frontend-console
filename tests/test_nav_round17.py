# -*- coding: utf-8 -*-
"""第十七轮对抗审计缺陷回归（a570）。

前端 2×P1 + 10×P2，后端 3 条协议问题。
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


def _seg(start, end):
    js = _js()
    i = js.find(start)
    assert i > 0, "找不到 " + start
    j = js.find(end, i)
    assert j > i, "找不到结束标记 " + end
    return js[i:j]


@pytest.fixture()
def client():
    os.environ.setdefault("CLAUDE_INLINE", "1")
    import flask
    from src import nav_api
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    return app.test_client()


# ---- P1：导出走后端落盘 ------------------------------------------------

def test_export_goes_through_backend(tmp_path, monkeypatch):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "原配置", "mode": "manual",
                   "arch": "auto",
                   "dirs": {"src": "whitelist", "vendor": "off"},
                   "artifact_roots": ["out/build"] * 1,
                   "exclude_names": ["node_modules"]}, f)
    # 落盘目录换成 tmp（避免写桌面）
    outdir = str(tmp_path / "out")
    os.makedirs(outdir, exist_ok=True)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    real_expand = os.path.expanduser

    def _expanduser(p):
        return outdir if p == "~" else real_expand(p)

    monkeypatch.setattr(nav_api.os.path, "expanduser", _expanduser)
    # （2026-11-23：此前往 sys.modules["src.main"] 挂 pywebview 的
    #   _save_file_dialog 桩——该函数已随 P4 删除，后端不再找它；而且那是
    #   setdefault、用例结束不恢复，会把假模块永久留在 sys.modules 里。）
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    c = app.test_client()
    r = c.post("/api/nav/scope_export", json={"root": root})
    assert r.status_code == 200, r.get_data()
    j = r.get_json()
    assert j["ok"] and j["path"]
    assert os.path.isfile(j["path"]), "必须真的落盘"
    body = json.load(open(j["path"], encoding="utf-8"))
    assert body["dirs"] == {"src": "whitelist", "vendor": "off"}, \
        "导出必须是真实配置，不是 status 摘要（后者无 dirs）"
    assert body["exclude_names"] == ["node_modules"]
    assert body["artifact_roots"] == ["out/build"]
    assert body["arch"] == "auto"


def test_export_without_scope_is_error(tmp_path, monkeypatch):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_api
    root = str(tmp_path)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    j = app.test_client().post("/api/nav/scope_export",
                               json={"root": root}).get_json()
    assert j["ok"] is False


def test_frontend_export_not_using_a_download():
    js = _js()
    assert "/api/nav/scope_export" in js
    assert "a.download" not in js, \
        "WebView2 里 init.js 拦 a[href] 且 ALLOW_DOWNLOADS=False，下载必失败"


# ---- P2：timeout_items 渲染 --------------------------------------------

def test_frontend_timeout_items_renders_rel():
    js = _js()
    i = js.find("timeout_items")
    assert i > 0
    seg = js[i:i + 700]
    assert ".map(x =>" in seg and "x.rel" in seg, \
        "timeout_items 元素是 {rel, elapsed}，直接 join 会渲染 [object Object]"


# ---- P2：关闭弹层后轮询不得复活 ---------------------------------------

def test_close_pick_increments_epoch():
    seg = _seg("const _closePick", "ov._cleanup")
    assert "_recEpoch++" in seg, \
        "关闭后启动 POST 返回会重新拉起轮询，用户再没有取消入口"


def test_run_recommend_cancels_when_epoch_stale():
    seg = _seg("const _runRecommend", "let _pollErr")
    assert "r.run_id" in seg and "scope_recommend_cancel" in seg, \
        "作废时必须把已启动的后端任务取消掉"


def test_poll_checks_epoch_after_await():
    js = _js()
    i = js.find("const r = await fetch('/api/nav/scope_recommend_poll")
    assert i > 0
    seg = js[i:i + 400]
    assert "_myEpoch !== _recEpoch" in seg, \
        "await 期间被清除的响应必须丢弃（只查 await 之前不够）"


# ---- P2：空 run_id 不许取消 -------------------------------------------

def test_cancel_without_run_id_rejected(client):
    from src import nav_api
    with nav_api._rec_lock:
        nav_api._rec_state.update(
            running=True, root="C:/projA", run_id="r2", cancel=False,
            root_key=os.path.normcase(os.path.abspath("C:/projA")))
    try:
        r = client.post("/api/nav/scope_recommend_cancel",
                        json={"root": "C:/projA"})
        assert r.status_code == 400
        with nav_api._rec_lock:
            assert nav_api._rec_state["cancel"] is False, \
                "空 run_id（旧弹层启动前关闭）不许误杀新任务"
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, cancel=False, root="",
                                      root_key="", run_id="")


# ---- P2：回继承时清 arts ----------------------------------------------

def test_back_inherit_clears_arts():
    seg = _seg("const _backInherit", "_noop =")
    assert "arts.delete(rk)" in seg
    assert "_userArts.delete(rk)" in seg
    assert "artsOff.delete(rk)" in seg


# ---- P2：产物源区分用户手勾与推荐产物 ---------------------------------

def test_manual_arts_only_from_user():
    js = _js()
    assert "const _userArts = new Set();" in js
    seg = _seg("const _manualArts = new Set();", "for (const k in dirs) delete")
    assert "_userArts.has(a)" in seg, \
        "上次推荐的 artifact_roots 不能当「用户手改」永久保留"


# ---- P2：清除范围后头部与载荷一致 -------------------------------------

def test_clear_scope_resets_head():
    js = _js()
    assert "let _scCleared = false;" in js
    seg = _seg("if (_scCleared)", "if (sc && sc.source === 'project')")
    assert "未配置（已清除已存范围）" in seg


def test_render_sel_keeps_value():
    seg = _seg("const renderSel = () => {", "renderSel();")
    assert "const _cur = sel.value || 'follow';" in seg
    assert "sel.value = " in seg, \
        "innerHTML 重置后必须显式回填 sel.value"


# ---- P2：导入校验与后端等价 -------------------------------------------

def _fe_check(cfg):
    """在 node 里跑 nav.js 的导入校验逻辑（抽出来求值）。"""
    if not NODE:
        pytest.skip("node 不可用")
    js = _js()
    i = js.find("        // a570：只认 v2。")
    assert i > 0
    j = js.find("card._scopeCfg = Object.assign", i)
    assert j > i
    body = js[i:j]
    code = r"""
    const cfg = %s;
    const errors = [];
    const showBanner = (m, _ms, isErr) => { if (isErr) errors.push(m); };
    const card = {};
    const _TMP_L = new Set(['tmp', 'temp', 'tmpdir', 'tempdir']);
    (function () {
    %s
    })();
    console.log(JSON.stringify({ok: errors.length === 0, err: errors[0] || ''}));
    """ % (json.dumps(cfg, ensure_ascii=False), body)
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _be_check(tmp_path, cfg):
    from src import nav_index as ni
    ok, _ = ni._norm_scope(cfg, str(tmp_path))
    return ok


@pytest.mark.parametrize("cfg,expect", [
    # 前端原先误拒、后端放行的
    ({"version": 2, "dirs": None}, True),
    ({"version": 2}, True),
    ({"version": 2, "mode": " Manual ", "dirs": {}}, True),
    ({"version": 2, "arch": " arm64 ", "dirs": {}}, True),
    ({"version": 2, "dirs": {"a": " Off "}}, True),
    ({"version": 2, "dirs": {"a": "FULL"}}, True),
    ({"version": 2, "artifact_roots": ["."]}, True),
    ({"version": 2, "exclude_names": ["."]}, True),
    # 两边都该拒
    ({"version": 2, "dirs": {"  ": "off"}}, False),
    ({"version": 2, "dirs": {" / ": "full"}}, False),
    ({"version": 2, "dirs": {"/abs": "off"}}, False),
    ({"version": 2, "dirs": {"a/../b": "off"}}, False),
    ({"version": 2, "dirs": {"C:/x": "off"}}, False),
    # tmp 类键：后端 `_norm_dirs` 忽略该键不判整份非法（a570 P1·第二十轮）；
    # 前端原先整单拒——2026-11-23 总审计 a684-A6 改为同口径
    ({"version": 2, "dirs": {"tmp": "off", "src": "off"}}, True),
    ({"version": 2, "mode": "full", "dirs": {"tmp": "off"}}, True),
    ({"version": 2, "dirs": {"../tmp": "off"}}, False),       # 路径校验先于 tmp
    ({"version": 2, "dirs": {"tmp": "bogus"}}, False),        # 值校验先于 tmp
    ({"version": 1, "dirs": {}}, False),
    ({"version": 2, "mode": "bogus", "dirs": {}}, False),
    ({"version": 2, "mode": "full", "dirs": {"a": "off"}}, False),
])
def test_import_check_matches_backend(tmp_path, cfg, expect):
    fe = _fe_check(cfg)
    be = _be_check(tmp_path, cfg)
    assert be is expect, "后端口径变了：%r -> %r" % (cfg, be)
    assert fe["ok"] is expect, "前端判决与后端不一致：%r -> %r" % (cfg, fe)


# ---- 后端：备份判据覆盖全部语义字段 -----------------------------------

def test_backup_fingerprint_covers_all_fields(tmp_path):
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    base = {"version": 2, "mode": "manual", "arch": "auto",
            "dirs": {"src": "off"}, "artifact_roots": ["out"],
            "exclude_names": ["nm"]}
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(base, f)
    # 只改 artifact_roots —— 必须备份
    assert nav_api._backup_scope_if_overwrite(
        root, dict(base, artifact_roots=[])), "artifact_roots 被清空必须备份"
    # 同配置不备份（新建一份）
    root2 = str(tmp_path / "b")
    os.makedirs(root2)
    with open(os.path.join(root2, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump(base, f)
    assert nav_api._backup_scope_if_overwrite(root2, dict(base)) == ""


# ---- 后端：409 之前不写备份 -------------------------------------------

def test_build_409_does_not_write_backup(tmp_path, monkeypatch):
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual",
                   "dirs": {"src": "off"}}, f)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    nav_api._state.update(running=True, root="other", importing=False)
    try:
        import flask
        app = flask.Flask(__name__)
        app.register_blueprint(nav_api.nav_bp)
        c = app.test_client()
        r = c.post("/api/nav/build", json={
            "root": root,
            "scope": {"version": 2, "mode": "full", "dirs": {}}})
        assert r.status_code == 409
        assert not os.path.isfile(os.path.join(root, ni.SCOPE_FILE) + ".prev.bak"), \
            "被拒的请求不许写备份（否则真正覆盖时备份告警永久丢失）"
    finally:
        nav_api._state.update(running=False, root="")


# ---- 后端：scope_clear 也留备份 ---------------------------------------

def test_scope_clear_writes_backup(tmp_path, monkeypatch):
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual",
                   "dirs": {"src": "off"}}, f)
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    nav_api._state.update(running=False, importing=False)
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    r = app.test_client().post("/api/nav/build",
                               json={"root": root, "scope_clear": True})
    assert r.status_code == 200
    assert not os.path.isfile(sp)
    bak = sp + ".prev.bak"
    assert os.path.isfile(bak), "清除前必须备份（红字按钮不该是不可恢复操作）"
    assert json.load(open(bak, encoding="utf-8"))["dirs"] == {"src": "off"}
