# -*- coding: utf-8 -*-
"""第十九轮前端协议审计缺陷回归（a570）：1×P1 + 3×P2。"""
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
    assert j > i
    return js[i:j]


# ---- P1：前端必须接受后端导出的根键 -----------------------------------

def test_frontend_import_accepts_root_keys():
    seg = _seg("const _normK =", "const _mode =")
    assert "_isRootKey" in seg, "根键 \"\"/\".\" 是合法形态（后端 _norm_dirs 接受）"
    assert "if (_isRootKey(k)) return false;" in seg


def test_frontend_import_root_key_exempt_from_mode_conflict():
    seg = _seg("const _nonRoot =", "// 路径列表")
    assert "_nonRoot.length" in seg, \
        "mode=full 时只有非根键才算冲突（根键与 mode 同义）"
    assert "_rv !== _mode" in seg, "根键取值必须等于 mode"


def test_export_import_roundtrip(tmp_path):
    """真跑后端导出 → 前端校验必须接受（P1 的直接断言）。"""
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_api
    from src import nav_index as ni
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "t", "mode": "manual",
                   "arch": "auto", "dirs": {"": "full", "src": "whitelist"},
                   "artifact_roots": [], "exclude_names": []}, f)
    outdir = str(tmp_path / "out")
    os.makedirs(outdir, exist_ok=True)
    from unittest import mock
    import flask
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    with mock.patch.object(nav_api, "_guard", lambda p: True), \
            mock.patch.object(nav_api.os.path, "expanduser",
                              lambda p: outdir if p == "~" else p):
        # （2026-11-23：不再把带 _save_file_dialog 的假 src.main 塞进
        #   sys.modules——后端已不找那个随 P4 删除的 picker。）
        j = app.test_client().post("/api/nav/scope_export",
                                   json={"root": root}).get_json()
    assert j["ok"], j
    body = json.load(open(j["path"], encoding="utf-8"))
    assert "" in body["dirs"]
    # 前端校验必须接受这份文件
    if not NODE:
        pytest.skip("node 不可用")
    js = _js()
    i = js.find('const _dirsIn = cfg.dirs || {};')
    k = js.find("card._scopeCfg = Object.assign", i)
    assert i > 0 and k > i
    code = """
    const cfg = %s;
    const errors = [];
    const showBanner = (m, _ms, isErr) => { if (isErr) errors.push(m); };
    const card = {};
    const _TMP_L = new Set(['tmp', 'temp', 'tmpdir', 'tempdir']);
    (function () {
    %s
    })();
    console.log(JSON.stringify({ok: errors.length === 0, err: errors[0] || ''}));
    """ % (json.dumps(body, ensure_ascii=False), js[i:k])
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout)
    assert got["ok"], "后端导出的配置前端必须能导入：%s" % got.get("err")


@pytest.mark.parametrize("dirs", [{"": "full"}, {".": "full"}])
def test_frontend_import_accepts_manual_root_key(dirs):
    if not NODE:
        pytest.skip("node 不可用")
    js = _js()
    i = js.find('const _dirsIn = cfg.dirs || {};')
    k = js.find("card._scopeCfg = Object.assign", i)
    code = """
    const cfg = %s;
    const errors = [];
    const showBanner = (m, _ms, isErr) => { if (isErr) errors.push(m); };
    const card = {};
    const _TMP_L = new Set(['tmp', 'temp', 'tmpdir', 'tempdir']);
    (function () {
    %s
    })();
    console.log(JSON.stringify({ok: errors.length === 0, err: errors[0] || ''}));
    """ % (json.dumps({"version": 2, "dirs": dirs}, ensure_ascii=False),
           js[i:k])
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["ok"]


# ---- P2-2：根行必须能设状态 -------------------------------------------

def test_root_row_has_state_buttons():
    js = _js()
    assert "mkRow('', rootName, true, 0, false)" in js
    assert "if (rk) r.appendChild(cb);" in js, \
        "根行不许挂仅产物源复选框（artifact_roots 空段会被后端拒）"


# ---- P2-3：继承态 no-op 不许动后代 arts -------------------------------

def test_inherit_noop_does_not_touch_arts():
    seg = _seg("const _noop = (!own && eff === v);", "if (own && dirs[rk] === v)")
    assert "_backInherit()" not in seg, \
        "纯 no-op 点击不许走 _backInherit（会静默清空后代的仅产物源标记）"
    assert "render();" in seg


def test_back_inherit_only_on_own_reset():
    seg = _seg("if (own && dirs[rk] === v) {", "dirs[rk] = v;")
    assert "_backInherit()" in seg, "显式节点点自己当前值 = 回到继承"
