# -*- coding: utf-8 -*-
"""换壳 P4 退役依赖防线（2026-11-22）。

目标：工具本体零外部依赖——后端不得再 import pywebview/pythonnet/clr，
资源清单不得再有硬项，旧密码管理面不得复活。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BANNED_TOP = {"webview", "pythonnet", "clr", "clr_loader", "pystray"}
BANNED_SRC = {"tray", "tray_menu", "res_ui"}


def _iter_py():
    for r, _ds, fs in os.walk(os.path.join(ROOT, "src")):
        for f in fs:
            if f.endswith(".py"):
                yield os.path.join(r, f)


def test_no_retired_imports():
    bad = []
    for p in _iter_py():
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            try:
                tree = ast.parse(f.read().lstrip("\ufeff"), p)
            except SyntaxError as e:
                bad.append("%s: SyntaxError %s" % (p, e))
                continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
                for m in mods:
                    top = m.split(".")[0]
                    if top in BANNED_TOP:
                        bad.append("%s:%d import %s" % (p, node.lineno, m))
                    for r in BANNED_SRC:
                        if m == "src." + r or m.startswith("src." + r + "."):
                            bad.append("%s:%d import %s" % (p, node.lineno, m))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] in BANNED_TOP:
                    bad.append("%s:%d from %s" % (p, node.lineno, mod))
                for r in BANNED_SRC:
                    if mod == "src." + r or mod.startswith("src." + r + "."):
                        bad.append("%s:%d from %s" % (p, node.lineno, mod))
                    if mod == "src" and any(a.name == r for a in node.names):
                        bad.append("%s:%d from src import %s"
                                   % (p, node.lineno, r))
    assert not bad, "退役依赖被重新引入：\n" + "\n".join(bad)


def test_manifest_has_no_hard_resources():
    from src import res_boot
    assert res_boot._HARD == ()
    assert not [m for m in res_boot.MANIFEST if m.get("hard")]
    kinds = {m["kind"] for m in res_boot.MANIFEST}
    assert "webview2" not in kinds and "dotnet" not in kinds


def test_shell_log_no_disk_write_except_dump():
    """用户令 2026-11-23：调试日志非必要不写盘，全走内存日志系统
    （诊断面板 tag=shell）。electron/main.js 里 appendFileSync 全文件
    只允许出现一次——即 _logDump（致命路径崩溃转储）内部那处。"""
    import io as _io
    src = _io.open(os.path.join(ROOT, "electron", "main.js"),
                   encoding="utf-8").read()
    n = src.count("appendFileSync")
    assert n == 1, (
        "electron/main.js 出现 %d 处 appendFileSync（应仅 _logDump 内 1 处）"
        "——调试日志禁止逐条写盘" % n)
    i = src.index("appendFileSync")
    assert "function _logDump" in src[:i], "唯一的 appendFileSync 必须在 _logDump 内"


def test_deps_bootstrap_does_not_require_pywebview():
    from src.deps_bootstrap import DEPS
    assert "pywebview" not in {p for p, _ in DEPS}


def test_no_retired_pip_names_in_dep_lists():
    """对抗审 B：AST import 扫描扫不到依赖表字符串——退役包名不得出现在
    任何 pip 依赖清单里（装了=白下/离线包失败）。"""
    from src import claude_setup, deps_bootstrap
    retired = {"pywebview", "pythonnet", "clr_loader", "pystray"}
    lists = {
        "deps_bootstrap.DEPS": [p for p, _ in deps_bootstrap.DEPS],
        "claude_setup._TOOL_DEPS": claude_setup._TOOL_DEPS,
        "claude_setup._TOOL_DEPS_ONLINE": claude_setup._TOOL_DEPS_ONLINE,
    }
    for name, lst in lists.items():
        hit = retired & set(lst)
        assert not hit, "%s 含退役依赖：%s" % (name, sorted(hit))


def test_shell_log_returns_processed_count():
    """对抗审（2026-11-23）：壳按响应里的 n 推进游标——后端必须如实回
    实际处理数，且批次上限 20（壳发送批也对齐 20）。丢日志=丢证据。"""
    import src.server as S
    c = S.app.test_client()
    r = c.post("/api/shell_log",
               json={"lines": ["L%d" % i for i in range(50)]})
    j = r.get_json()
    assert j and j.get("ok") is True
    assert j.get("n") == 20, "超批必须只算处理过的 20 行，got %r" % j.get("n")
    # 正常小批全收
    r2 = c.post("/api/shell_log", json={"lines": ["a", "b"]})
    assert r2.get_json().get("n") == 2


def test_shell_flush_single_flight_and_batch():
    """壳侧 flush：批大小与后端对齐 20；失败单定时器重试；按 n 推进。"""
    import io as _io
    import re as _re
    src = _io.open(os.path.join(ROOT, "electron", "main.js"),
                   encoding="utf-8").read()
    assert "_LOG_BATCH = 20" in src, "壳发送批必须与后端 lines[:20] 对齐"
    assert "_logInFlight" in src, "必须单飞防请求风暴"
    assert "j.n" in src, "游标必须按后端实际处理数 n 推进"
    assert _re.search(r"setTimeout\(\(\) => \{ _logRetryT = null; _logFlush\(\); \}, 3000\)",
                      src), "失败必须有 3s 单定时器重试"


def test_web_tabs_only_keeps_inject_route():
    from flask import Flask
    from src import web_tabs
    app = Flask(__name__)
    web_tabs.register(app)
    c = app.test_client()
    j = c.get("/api/web/tabs/inject").get_json()
    assert j["ok"] is True and "pointerdown" in j["js"]
    # 旧密码管理面已迁 Electron：明确拒绝而不是静默成功
    j2 = c.post("/api/web/tabs", json={"act": "pw_list"}).get_json()
    assert j2["ok"] is False
    # 旧控件命令返回空成功（兼容缓存页）
    j3 = c.post("/api/web/tabs", json={"act": "create"}).get_json()
    assert j3["ok"] is True
