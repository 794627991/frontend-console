# -*- coding: utf-8 -*-
"""2026-11-23 总审计 a684 节 nav 系修复的回归锚（a684-A2/A4/A5/A6/A7/A8/A9/A10）。

每条都是低危的防御分支与口径类缺陷，单独看都不致命，但同一种「防御代码
自身带病 / 两端口径相反 / 靠巧合成立」的模式反复出现。本文件逐条钉死：

  A2  落盘范围时只把顶层**目录**补成 full（根直下文件名不算目录）
  A4  `_cur_d` 的四处访问全部在 `_dl` 下（AST 守卫 + 旧实现样本自检）
  A5  「预估 N 文件」按当前配置的生效状态算（off 不计，一级子目录能扣则扣）
  A6  前端导入对 tmp 键与后端 `_norm_dirs` 同口径：忽略该键 + 提示，不整单拒
  A7  scope_tree 的 truncated 以「确有目录被截」为准（恰好 800 个不误报）
  A8  推荐器 zoo 先验改词边界匹配（kazoo_lib 不再被整棵判 off）
  A9  「仅清除范围」的轻量 reset 清掉上一次任务的结论
      （复核时另发现：删除失败被 `except OSError: pass` 吞掉仍报已清除）
  A10 全树统一态的 state_of 也暴露两个能力查询（恒 False，契约显式化）

pytest 收集；也可 `python tests/test_nav_audit_20261124.py` 直接跑。
前端两条用例需要 node（没有则 skip）。
"""
import ast
import inspect
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time

import flask
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import nav_api, nav_index as ni   # noqa: E402

NAV_JS = os.path.join(ROOT, "web", "js", "nav.js")
NODE = shutil.which("node")


# ---------------------------------------------------------------- 夹具

def _scope_file(root, dirs=None):
    sp = os.path.join(root, ni.SCOPE_FILE)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "mode": "manual",
                   "dirs": dirs if dirs is not None else {"src": "off"}}, f)
    return sp


@pytest.fixture
def nav_client(monkeypatch):
    monkeypatch.setattr(nav_api, "_guard", lambda p: True)
    app = flask.Flask(__name__)
    app.register_blueprint(nav_api.nav_bp)
    nav_api._state.update(running=False, importing=False)
    yield app.test_client()
    nav_api._state.update(running=False, importing=False, done=False, ok=False,
                          err="", result=None, reason="", cancelled=False)


def _run_js(code):
    if not NODE:
        pytest.skip("node 不可用")
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def _js():
    with open(NAV_JS, encoding="utf-8") as f:
        return f.read()


def _mk_file(*parts):
    d = os.path.join(*parts[:-1])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(*parts), "w", encoding="utf-8") as f:
        f.write("int x;\n")


# ---------------------------------------------------------------- A2

def test_top_dirs_only_counts_directories():
    """rel 是文件相对路径：不含 / 的是根直下文件，不能当成顶层目录。"""
    rels = {"Makefile", "README.md", "src/a.py", "Src/b.py", "docs/x/y.md"}
    assert ni._top_dirs_of(rels) == {"src", "docs"}


def test_top_dirs_matches_what_the_walk_collects(tmp_path):
    """对照真实 walk 的产出：补键集合必须恰好是「有文件的顶层目录」。"""
    root = str(tmp_path)
    _mk_file(root, "Makefile")
    _mk_file(root, "src", "a.py")
    _mk_file(root, "src", "sub", "b.py")
    _mk_file(root, "docs", "deep", "x.md")
    rels = {rel for _abs, rel in ni._walk_files(root)}
    assert "Makefile" in rels                      # 根直下文件确实在产出里
    assert ni._top_dirs_of(rels) == {"src", "docs"}


# ---------------------------------------------------------------- A4

def _unlocked_cur_d(tree):
    """返回 `_cur_d` 未在 `with _dl:` 下被读取的行号。

    嵌套函数是另一个执行上下文，外层的持锁状态不继承。
    """
    bad = []

    def walk(node, locked):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            locked = False
        if (isinstance(node, ast.Name) and node.id == "_cur_d"
                and isinstance(node.ctx, ast.Load) and not locked):
            bad.append(node.lineno)
        if isinstance(node, ast.With):
            held = locked or any(
                isinstance(i.context_expr, ast.Name) and i.context_expr.id == "_dl"
                for i in node.items)
            for i in node.items:
                walk(i, locked)
            for b in node.body:
                walk(b, held)
            return
        for c in ast.iter_child_nodes(node):
            walk(c, locked)

    walk(tree, False)
    return bad


# 修复前的形态（worker 裸写、退出裸删；看门狗那处本来就持锁）
_OLD_WALK_SAMPLE = '''
def _walk_files(root):
    _cur_d = {}
    _dl = threading.Lock()
    def _watchdog_tick():
        with _dl:
            _cur_d.pop(name, None)
    def _worker():
        me = threading.current_thread().name
        try:
            for r, ds, fs in os.walk(sub):
                _cur_d[threading.current_thread().name] = r
        finally:
            try:
                _cur_d.pop(me, None)
            except Exception:
                pass
'''


def test_cur_d_lock_guard_catches_the_unlocked_shape():
    """守卫自检：对旧形态必须报得出（报不出说明守卫本身是坏的）。"""
    bad = _unlocked_cur_d(ast.parse(textwrap.dedent(_OLD_WALK_SAMPLE)))
    assert len(bad) == 2, bad                     # 写 + 退出删；看门狗那处不报


def test_cur_d_access_all_under_dl_lock():
    src = textwrap.dedent(inspect.getsource(ni._walk_files))
    tree = ast.parse(src)
    # 自检：确实在检查 `_walk_files`，且里面有四处访问
    assert any(isinstance(n, ast.Name) and n.id == "_cur_d"
               for n in ast.walk(tree))
    bad = _unlocked_cur_d(tree)
    assert bad == [], "_cur_d 在 _dl 之外被访问：行 %s" % bad


def test_cur_d_walk_finishes_with_no_worker_left(tmp_path):
    """行为面：加锁后 walk 照常收口——文件一个不少，结束后零 worker 残留。"""
    import threading
    for i in range(12):
        d = tmp_path / ("d%02d" % i)
        d.mkdir()
        for j in range(30):
            (d / ("f%02d.c" % j)).write_text("int x;\n", encoding="utf-8")
    rels = {rel for _abs, rel in ni._walk_files(str(tmp_path))}
    assert len(rels) == 12 * 30
    deadline = time.time() + 5
    while time.time() < deadline:
        left = [t.name for t in threading.enumerate()
                if t.name.startswith("nav_walk_")]
        if not left:
            break
        time.sleep(0.05)
    assert left == [], left


# ---------------------------------------------------------------- A5

_NODES = [
    {"rel": "src", "code": 1000,
     "subs": [{"name": "Gen", "code": 300}, {"name": "keep", "code": 400},
              {"name": "__root__", "code": 300}]},
    {"rel": "rootfs", "code": 39000,
     "subs": [{"name": "lib", "code": 20000}, {"name": "app", "code": 19000}]},
    {"rel": "docs", "code": 50, "subs": []},
]


def _fe_estimate(dirs, root_default="whitelist"):
    js = _js()
    i = js.find("    // ---- 状态 ----")
    j = js.find("    const _syncArtBox = () => {", i)
    assert i > 0 and j > i
    code = """
    const cnt = {};
    (function () {
    %s
      recNodes = %s;
      rootDefault = %s;
      Object.assign(dirs, %s);
      _syncCounts();
      console.log(JSON.stringify({est: _estFiles(), txt: cnt.textContent}));
    })();
    """ % (js[i:j], json.dumps(_NODES), json.dumps(root_default), json.dumps(dirs))
    return _run_js(code)


def test_estimate_excludes_off_tops():
    got = _fe_estimate({"rootfs": "off"})
    assert got["est"] == 1050, got                # 旧实现：40050（off 也计入）
    assert "预估 1.1k 文件" in got["txt"]


def test_estimate_all_live_is_the_upper_bound():
    got = _fe_estimate({})
    assert got["est"] == 40050
    assert "4.0W" in got["txt"]


def test_estimate_adds_back_live_sub_under_off_top():
    """off 顶层下用户显式勾选的子目录会下钻（_keep_dir 同向），要加回。"""
    got = _fe_estimate({"rootfs": "off", "rootfs/app": "full"})
    assert got["est"] == 20050, got


def test_estimate_subtracts_off_sub_under_live_top():
    # dirs 键一律 lower（与后端 _norm_dirs 同口径）；节点里的子目录名是磁盘
    # 真实大小写（Gen）——匹配必须不分大小写
    got = _fe_estimate({"src/gen": "off"})
    assert got["est"] == 39750, got               # 旧实现：40050


def test_estimate_zero_when_everything_off():
    got = _fe_estimate({"src": "off", "rootfs": "off", "docs": "off"})
    assert got["est"] == 0
    assert "预估" not in got["txt"]               # 0 不显示「预估 0 文件」


def test_estimate_without_recommend_data():
    js = _js()
    i = js.find("    // ---- 状态 ----")
    j = js.find("    const _syncArtBox = () => {", i)
    code = """
    const cnt = {};
    (function () {
    %s
      _syncCounts();
      console.log(JSON.stringify({est: _estFiles(), txt: cnt.textContent}));
    })();
    """ % js[i:j]
    got = _run_js(code)
    assert got["est"] == 0 and "预估" not in got["txt"]


# ---------------------------------------------------------------- A6

def _fe_import(cfg):
    js = _js()
    i = js.find("        // a570：只认 v2。")
    j = js.find("      }).catch(e => showBanner('读取失败: ' + e, 4000, true));", i)
    assert i > 0 and j > i
    code = """
    const cfg = %s;
    const errors = []; const notes = [];
    const showBanner = (m, _ms, isErr) => { (isErr ? errors : notes).push(m); };
    const card = {};
    const _TMP_L = new Set(['tmp', 'temp', 'tmpdir', 'tempdir']);
    const renderSel = () => {}; const sel = {};
    const _syncSelHead = () => {}; const _headCfg = () => {};
    const _withCounts = (c) => c;
    (function () {
    %s
    })();
    console.log(JSON.stringify({ok: errors.length === 0, err: errors[0] || '',
      notes, dirs: (card._scopeCfg || {}).dirs || null}));
    """ % (json.dumps(cfg, ensure_ascii=False), js[i:j])
    return _run_js(code)


@pytest.mark.parametrize("cfg", [
    {"version": 2, "dirs": {"tmp": "off", "src": "off"}},
    {"version": 2, "mode": "full", "dirs": {"tmp": "off"}},
    {"version": 2, "dirs": {"a/TMP/b": "full", "x": "full"}},
    {"version": 2, "dirs": {"tempdir": "whitelist", "keep": "full"}},
])
def test_frontend_import_drops_tmp_keys_like_backend(tmp_path, cfg):
    got = _fe_import(cfg)
    assert got["ok"] is True, got
    assert ni._norm_scope(cfg, str(tmp_path))[0] is True, "后端口径变了"
    dropped = []
    normed = ni._norm_dirs(cfg["dirs"], dropped)
    assert dropped, "用例本身必须含 tmp 键"
    assert "已忽略 %d 个 tmp 类目录" % len(dropped) in got["notes"][-1], got["notes"]
    assert sorted(got["dirs"].keys()) == sorted(normed.keys())


@pytest.mark.parametrize("cfg", [
    {"version": 2, "dirs": {"../tmp": "off"}},          # 路径校验先于 tmp 剔除
    {"version": 2, "dirs": {"C:/tmp": "off"}},
    {"version": 2, "dirs": {"tmp": "bogus"}},           # 值校验先于 tmp 剔除
    {"version": 2, "dirs": {"tmp": ["off"]}},
])
def test_frontend_import_still_rejects_bad_tmp_keys(tmp_path, cfg):
    got = _fe_import(cfg)
    assert got["ok"] is False, got
    assert ni._norm_scope(cfg, str(tmp_path))[0] is False, "后端口径变了"


def test_frontend_import_without_tmp_has_no_drop_note():
    got = _fe_import({"version": 2, "dirs": {"src": "off"}})
    assert got["ok"] is True and got["dirs"] == {"src": "off"}
    assert "已忽略" not in got["notes"][-1]


def test_legacy_config_with_tmp_key_still_restorable(tmp_path):
    """还原路径不断裂：含 tmp 键的历史落盘文件（a570 P1·第二十轮之前写的、
    或 .prev.bak）后端读得回，原文喂给前端「导入 JSON」也不拒。"""
    root = str(tmp_path / "proj")
    os.makedirs(root)
    legacy = {"version": 2, "mode": "manual", "arch": "auto",
              "dirs": {"src": "off", "tmp": "full"},
              "artifact_roots": [], "exclude_names": []}
    with open(os.path.join(root, ni.SCOPE_FILE), "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    sc, source = ni.load_scope(root)
    assert source == "project" and sc["dirs"] == {"src": "off"}, (sc, source)
    got = _fe_import(legacy)
    assert got["ok"] is True, got                    # 旧前端：整单拒
    assert got["dirs"] == {"src": "off"}


# ---------------------------------------------------------------- A7

def test_scope_tree_truncated_only_when_dirs_actually_cut(tmp_path, nav_client):
    root = str(tmp_path)
    for i in range(800):
        os.mkdir(os.path.join(root, "d%04d" % i))
    j = nav_client.get("/api/nav/scope_tree",
                       query_string={"root": root}).get_json()
    assert j["ok"] and len(j["dirs"]) == 800
    assert j["truncated"] is False, "恰好 800 个一个没截，不该报截断"
    os.mkdir(os.path.join(root, "d_extra"))
    j = nav_client.get("/api/nav/scope_tree",
                       query_string={"root": root}).get_json()
    assert len(j["dirs"]) == 800 and j["truncated"] is True


def test_scope_tree_hard_skipped_dirs_do_not_count_as_truncated(tmp_path, nav_client):
    """被硬规则（tmp/点目录）跳过的不算截断。"""
    root = str(tmp_path)
    for i in range(800):
        os.mkdir(os.path.join(root, "d%04d" % i))
    for extra in ("tmp", "temp", ".git"):
        os.mkdir(os.path.join(root, extra))
    j = nav_client.get("/api/nav/scope_tree",
                       query_string={"root": root}).get_json()
    assert len(j["dirs"]) == 800 and j["truncated"] is False


# ---------------------------------------------------------------- A8

@pytest.mark.parametrize("name", ["zoos", "zoo_tmp", "zmo", "zoo", "my-zoo",
                                  "output_zoo", "ZOO", "zoos2"])
def test_l1_zoo_family_still_off(name):
    assert ni._rule_level1(name) == ("off", "成果物目录")


@pytest.mark.parametrize("name", ["kazoo_lib", "amazon_zookeeper", "bizmo",
                                  "crazoo_src", "tools"])
def test_l1_zoo_word_boundary(name):
    """zoo/zmo 必须是一个完整的词——前缀里带 zoo 的源码目录不再被整棵判 off。"""
    assert ni._rule_level1(name) is None, name


# ---------------------------------------------------------------- A9

def test_clear_only_resets_previous_task_conclusion(tmp_path, nav_client):
    root = str(tmp_path)
    _scope_file(root)
    nav_api._state.update(result={"files": 999, "code_files": 999},
                          reason="stale-reason", cancelled=True,
                          scope_saved=False, percent=87, cur="stale")
    r = nav_client.post("/api/nav/build", json={"root": root, "scope_clear": True})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "cleared": True}
    s = nav_api._state
    assert s["running"] is False and s["done"] is True and s["ok"] is True
    assert s["result"] is None and s["reason"] == "" and s["cancelled"] is False
    assert s["scope_saved"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="用 Win32 共享模式占用文件")
def test_clear_failure_is_reported_not_swallowed(tmp_path, nav_client):
    """文件被占用删不掉：必须如实报失败，不能返回「已清除」。"""
    import ctypes
    from ctypes import wintypes
    root = str(tmp_path)
    sp = _scope_file(root)
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    INVALID = wintypes.HANDLE(-1).value
    # 只允许别人「读」：不带 FILE_SHARE_DELETE → 别人删不掉
    h = k32.CreateFileW(str(sp), 0x80000000, 0x1, None, 3, 0, None)
    assert h not in (None, 0, INVALID), "CreateFileW 失败"
    try:
        with pytest.raises(PermissionError):
            os.remove(str(sp))                    # 自检：占用确实让删除失败
        r = nav_client.post("/api/nav/build",
                            json={"root": root, "scope_clear": True})
    finally:
        k32.CloseHandle(h)
    assert r.status_code == 500
    j = r.get_json()
    assert j["ok"] is False and "删除失败" in j["err"]
    assert os.path.isfile(sp), "删除失败时配置必须原样留着"
    assert os.path.isfile(sp + ".prev.bak"), "备份已做，重试不必再做"
    s = nav_api._state
    assert s["running"] is False and s["done"] is True
    assert s["ok"] is False and s["err"]
    # 占用解除后重试成功
    r2 = nav_client.post("/api/nav/build",
                         json={"root": root, "scope_clear": True})
    assert r2.status_code == 200 and r2.get_json()["cleared"] is True
    assert not os.path.exists(sp)


# ---------------------------------------------------------------- A10

@pytest.mark.parametrize("sc", [
    {"version": 2, "mode": "full", "dirs": {}, "artifact_roots": [],
     "exclude_names": []},
    {"version": 2, "mode": "whitelist", "dirs": {}, "artifact_roots": [],
     "exclude_names": []},
    {"version": 2, "mode": "manual", "dirs": {"kernel": "off",
                                              "kernel/src": "whitelist"},
     "artifact_roots": [], "exclude_names": []},
])
def test_state_of_always_exposes_capability_queries(sc):
    f = ni._make_state_of(sc)
    assert callable(f.has_live_desc) and callable(f.under_live)
    if sc["mode"] == "manual":
        assert f("kernel") == "off"
        assert f.has_live_desc("kernel") is True
        assert f.under_live("kernel/src/a.c") is True
    else:
        assert f("anything/deep") == sc["mode"]
        # 统一态没有「显式节点」概念：两个查询恒 False
        assert f.has_live_desc("anything") is False
        assert f.under_live("anything") is False


def test_uniform_state_walk_still_cuts_user_excluded_whole_subtree(tmp_path):
    """A10 的行为面：统一态 + 用户排除名 = 整棵剪（has_live_desc 恒 False 的语义）。"""
    root = str(tmp_path)
    _mk_file(root, "gen", "keep", "a.c")
    _mk_file(root, "gen", "drop", "a.c")
    _mk_file(root, "src", "a.c")
    sc = {"version": 2, "mode": "full", "dirs": {}, "artifact_roots": [],
          "exclude_names": ["gen"]}
    rels = {rel for _a, rel in ni._walk_files(
        root, excl_names=sc["exclude_names"], state_of=ni._make_state_of(sc))}
    assert rels == {"src/a.c"}, rels


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
