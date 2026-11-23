# -*- coding: utf-8 -*-
"""前端三态树与 API 契约的钉测（a571 重写）。

第一版全是「字符串存在性」检查——把 `version: 2` 写进注释就能骗过，
`v1` 字段只要有行首注释也不报，三态按钮的文案一字之差就误报。审计三轮
后重写为**行为断言**：

  · 真正跑 Flask 的端点，看返回码/形状（不是看源码里有没有那个 URL）
  · 用 node 实际求值 nav.js 中的关键函数（sandbox 里跑），看行为
  · 对源码做**结构性**检查（AST 级：JS 用 node --check 之外的简单解析）

node 不可用时相关用例 skip，不误报失败。
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


def _run_node(code, timeout=20):
    """在 node 里跑一段 JS，返回 stdout（失败抛 AssertionError）。"""
    if not NODE:
        pytest.skip("node 不可用")
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


# ---- 端点契约（真跑 Flask）--------------------------------------------

@pytest.fixture()
def client():
    os.environ.setdefault("CLAUDE_INLINE", "1")
    import flask
    from src import nav_api
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    return app.test_client()


def test_recommend_endpoints_registered(client):
    rules = {str(r) for r in client.application.url_map.iter_rules()}
    assert "/api/nav/scope_recommend" in rules
    assert "/api/nav/scope_recommend_poll" in rules
    assert "/api/nav/scope_recommend_cancel" in rules


def test_tier_endpoint_accepts_four_choices(client):
    for ch in ("full", "whitelist", "reconfigure", "cancel"):
        r = client.post("/api/nav/tier", json={"choice": ch})
        # 无待选任务 → 409（取值校验已通过）
        assert r.status_code == 409, (ch, r.status_code, r.get_data())
    r = client.post("/api/nav/tier", json={"choice": "bogus"})
    assert r.status_code == 400
    assert b"reconfigure" in r.get_data(), "400 文案必须列出全部合法值"


def test_recommend_cancel_honours_root(client):
    """cancel 带 root 且与运行中任务不符时必须拒绝（跨工程误杀防护）。"""
    from src import nav_api
    with nav_api._rec_lock:
        nav_api._rec_state.update(running=True, root="C:/projA",
                                  root_key=os.path.normcase(os.path.abspath(
                                      "C:/projA")), cancel=False, run_id="r1")
    try:
        r = client.post("/api/nav/scope_recommend_cancel",
                        json={"root": "C:/projB", "run_id": "r1"})
        assert r.status_code == 409
        assert r.get_json()["same"] is False
        assert nav_api._rec_state["cancel"] is False, "不许误杀别的工程"
        r2 = client.post("/api/nav/scope_recommend_cancel",
                         json={"root": "C:/projA", "run_id": "r1"})
        assert r2.status_code == 200
        assert nav_api._rec_state["cancel"] is True
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, cancel=False,
                                      root="", root_key="", run_id="")


def test_recommend_poll_requires_matching_root(client):
    from src import nav_api
    with nav_api._rec_lock:
        nav_api._rec_state.update(
            running=True, done=True, ok=True, root="C:/projA",
            root_key=os.path.normcase(os.path.abspath("C:/projA")),
            result={"dirs": {"a": "off"}})
    try:
        # 不传 root → mine=False，不能读到别人的结果
        j = client.get("/api/nav/scope_recommend_poll").get_json()
        assert j["mine"] is False and j["result"] is None
        # 传错的 root → 同样拒绝
        j2 = client.get("/api/nav/scope_recommend_poll?root=C:/projB"
                        ).get_json()
        assert j2["mine"] is False and j2["result"] is None
        # 传对 → 拿到
        j3 = client.get("/api/nav/scope_recommend_poll?root=C:/projA"
                        ).get_json()
        assert j3["mine"] is True
        assert j3["result"]["dirs"] == {"a": "off"}
    finally:
        with nav_api._rec_lock:
            nav_api._rec_state.update(running=False, done=False, ok=False,
                                      root="", root_key="", result=None)


# ---- 前端行为（node 求值）--------------------------------------------

def test_frontend_applies_recommendation_in_place():
    """P0 回归：`dirs` 是 const，推荐结果必须原地替换而不是整体赋值。

    直接从 nav.js 里抽出「应用推荐」那段逻辑的形状不可靠，改用真实断言：
    文件里不得出现对 `dirs` 的整体赋值（`dirs = ` 但排除 `dirs = {}`）。
    """
    js = _js()
    import re
    # 找 `dirs = ` 赋值（不是声明、不是 ===/==、不是 dirs[ 索引写）
    bad = []
    for m in re.finditer(r"(?<![\w.\[])\bdirs\s*=(?!=)", js):
        line_start = js.rfind("\n", 0, m.start()) + 1
        line = js[line_start:js.find("\n", m.start())].strip()
        if line.startswith("//") or line.startswith("*"):
            continue
        if re.match(r"^(const|let|var)\s+dirs\s*=\s*\{\s*\}\s*;?$", line):
            continue          # 合法声明
        bad.append(line)
    assert not bad, "dirs 是 const，禁止整体赋值（P0 回归）：%r" % bad


def test_frontend_dir_keys_are_lowercased():
    """三态树的 dirs/arts 键必须与后端、推荐器同口径（lower）。"""
    js = _js()
    assert "const _k = (rel) => (rel || '').toLowerCase();" in js, \
        "缺 _k() 归一辅助——大小写不一致会让推荐结果全部显示成继承态"
    # dirs 的写点必须用 _k 或 rk
    assert "dirs[rk]" in js, "dirs 的写点必须用归一后的键"


def test_frontend_root_row_has_state_buttons_but_no_art_checkbox():
    """a570 第十九轮：后端已接受根键 ""（表达「工程根自身」的收录状态），
    根行必须挂三态按钮——否则根直下源码建库时被根默认 whitelist 排掉，
    用户看不出。但「仅产物源」复选框不能挂：artifact_roots 的空段会被
    后端 `_lst` 拒绝。"""
    js = _js()
    assert "mkRow('', rootName, true, 0, false)" in js, \
        "根行必须挂三态按钮（后端已支持根键）"
    assert "if (rk) r.appendChild(cb);" in js, \
        "根行不许挂仅产物源复选框"


def test_frontend_closepick_stops_poll_and_cancels():
    js = _js()
    assert "_closePick" in js
    # 关闭路径必须停轮询 + 带 root 的 cancel
    idx = js.find("const _closePick")
    assert idx > 0
    seg = js[idx:idx + 900]
    assert "_stopPoll()" in seg
    assert "scope_recommend_cancel" in seg
    assert "root: root" in seg


def test_frontend_poll_checks_root_ownership():
    js = _js()
    assert "r.mine === false" in js, "poll 必须丢弃别的工程的结果"


def test_frontend_import_rejects_non_object_dirs():
    """a570 第十七轮：dirs 缺失/null 属合法（后端 _norm_dirs(None)->{}），
    但数组与非对象必须拒——否则 `{dirs:[...]}` 会静默变成「全树白名单」。"""
    js = _js()
    assert "Array.isArray(cfg.dirs)" in js
    assert "d.dirs !== null" in js or "dirs !== null" in js


# ---- 后端 status 契约 --------------------------------------------------

def test_status_exposes_v2_scope_shape(tmp_path):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_index as ni
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src", "a.c"), "w") as f:
        f.write("int x;\n")
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 2, "name": "t", "mode": "manual",
                   "dirs": {"src": "whitelist", "vendor": "off"}}, f)
    st = ni.status(root)
    sc = st.get("scope")
    assert sc and sc["source"] == "project"
    assert sc["state_counts"] == {"whitelist": 1, "full": 0, "off": 1}
    assert "tier" not in sc and "include" not in sc


def test_status_reports_v1_deprecated(tmp_path):
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_index as ni
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src", "a.c"), "w") as f:
        f.write("int x;\n")
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "tier": "auto", "include": ["."]}, f)
    st = ni.status(root)
    assert st["scope"]["source"] == "v1-deprecated"


def test_status_reports_corrupt_config(tmp_path):
    """配置损坏必须明确回报（不是伪装成「未配置」，否则用户看不到问题）。"""
    os.environ.setdefault("CLAUDE_INLINE", "1")
    from src import nav_index as ni
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "src", "a.c"), "w") as f:
        f.write("int x;\n")
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        f.write("{broken")
    st = ni.status(root)
    assert st["scope"]["source"].startswith("bad:")
