# -*- coding: utf-8 -*-
"""前端 JS 工具链的自检（a644）。

这套工具链是新增的：ESLint 静态检查 + node 单元测试 + 全局名清单生成。
本测保证「工具本身没坏」，而不是去测前端业务逻辑（那在 tests/js/*.test.mjs）。

钉住：
1. globals 收集器能覆盖 IIFE 内的缩进声明（曾因只认行首漏掉 hgModal 等，
   导致 800+ 条假 no-undef）
2. index.html 与实际 js 文件一致（无孤儿脚本、无引用不存在的文件）
3. eslint 配置能真的拦住未定义引用（用临时注入验证门禁）
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, '.')

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_MODULES = os.path.join(ROOT, "tools", "js-tooling", "node_modules")
HAS_NODE_TOOLING = os.path.isdir(NODE_MODULES) and bool(
    shutil.which("node"))


def test_globals_collector_handles_indented_declarations():
    """IIFE 里的缩进声明也要收——否则跨文件调用全被误报未定义。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "jc", os.path.join(ROOT, "tools", "js_collect_globals.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    names = mod.scan(os.path.join(ROOT, "web", "js", "harness", "modal.js"))
    assert "hgModal" in names, "IIFE 内缩进两格的 hgModal 未被收集"
    # async 前缀也要认
    harness_sessions = mod.scan(
        os.path.join(ROOT, "web", "js", "harness", "sessions.js"))
    assert "refreshSessions" in harness_sessions
    assert "switchTo" in harness_sessions


def test_globals_file_covers_known_cross_file_calls():
    """生成好的 app-globals.json 必须包含真实存在的跨文件函数名。"""
    p = os.path.join(ROOT, "tests", "js", "app-globals.json")
    assert os.path.isfile(p), "先跑 python tools/js_collect_globals.py"
    with open(p, encoding="utf-8") as f:
        names = set(json.load(f))
    for must in ("closeEditorTab", "openFileSmart", "apiPost",
                 "hgModal", "refreshSessions"):
        assert must in names, "%s 不在全局清单里（no-undef 会误报）" % must


def test_no_orphan_scripts():
    """index.html 引用的脚本必须都存在，磁盘上的 js 也必须都被引用。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "jm", os.path.join(ROOT, "tools", "js_script_manifest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    loaded = os.path.join(ROOT, "tests", "js", "loaded.txt")
    orphans = os.path.join(ROOT, "tests", "js", "orphans.txt")
    assert mod.main() == 0
    with open(loaded, encoding="utf-8") as f:
        names = [x for x in f.read().split("\n") if x]
    assert names, "index.html 没引用任何脚本？"
    for n in names:
        assert os.path.isfile(os.path.join(ROOT, "web", n)), \
            "index.html 引用了不存在的 %s" % n
    with open(orphans, encoding="utf-8") as f:
        assert [x for x in f.read().split("\n") if x] == [], \
            "磁盘上有 js 没被 index.html 引用（确认是否死文件）"


@pytest.mark.skipif(not HAS_NODE_TOOLING,
                    reason="未跑 npm install（node_modules 不存在）")
def test_eslint_gate_blocks_undefined_reference():
    """门禁必须真的能拦住新增的未定义引用（不是空跑）。"""
    target = os.path.join(ROOT, "web", "js", "util.js")
    backup = target + ".gatetest"
    shutil.copy2(target, backup)
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write("\nfunction _gateProbe(){ return _definitelyNotDefined(1); }\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "eslint_gate.py")],
            cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode == 1, "门禁没拦住新增的 no-undef"
        assert "_definitelyNotDefined" in proc.stdout
    finally:
        shutil.move(backup, target)


@pytest.mark.skipif(not HAS_NODE_TOOLING,
                    reason="未跑 npm install（node_modules 不存在）")
def test_eslint_clean_against_baseline():
    """当前代码相对基线无新增 error。"""
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "eslint_gate.py")],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(not HAS_NODE_TOOLING,
                    reason="未跑 npm install（node_modules 不存在）")
def test_node_unit_tests_pass():
    """node 单元测试（纯函数）必须全绿。"""
    files = [
        "tests/js/log-viewer-scroll.test.mjs",
        # 2026-11-26 Step 2：docview 的纯函数层
        "tests/js/docview-anchor.test.mjs",
        "tests/js/docview-docx-parse.test.mjs",
        "tests/js/docview-linkify.test.mjs",
    ]
    proc = subprocess.run(
        ["node", "--test"] + files,
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
