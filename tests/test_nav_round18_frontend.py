# -*- coding: utf-8 -*-
"""第十八轮前端审计缺陷回归（a570）：6 条 P2。"""
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


def test_run_recommend_catch_checks_epoch():
    """旧请求的 reject 迟到不能改写新推荐的状态栏/按钮。"""
    seg = _seg("const _runRecommend", "let _pollErr")
    i = seg.find("} catch (e) {")
    assert i > 0
    tail = seg[i:]
    assert "_myEpoch !== _recEpoch" in tail,         "catch 分支必须比对 epoch，否则旧请求失败会解禁「建库」按钮"


def test_409_takeover_skips_dead_runs():
    js = _js()
    assert "const _deadRuns = new Set();" in js
    seg = _seg("const _runRecommend", "let _pollErr")
    assert "_deadRuns.has(r.run_id)" in seg,         "已作废的 run_id 不能接管（双击选择目录会被自己的取消打成「已取消」）"
    # 三处 cancel 都要登记
    assert js.count("_deadRuns.add(") >= 3


def test_backend_409_exposes_run_id():
    import inspect
    from src import nav_api
    src = inspect.getsource(nav_api.nav_scope_recommend)
    i = src.find('"busy": True')
    assert i > 0
    seg = src[max(0, i - 200):i + 400]
    assert '"run_id": _rec_state.get("run_id")' in seg


def test_back_inherit_clears_descendant_arts():
    seg = _seg("const _backInherit", "_noop =")
    assert "a.indexOf(pfx) === 0" in seg,         "父目录回继承后，后代的仅产物源标记也要清（与 set 分支对称）"


def test_import_rejects_non_string_dir_state():
    seg = _seg("const _badV =", "if (_badV !== undefined)")
    assert "typeof _dirsIn[k] !== 'string'" in seg,         "dirs 值是数组/数字时 String() 会放行，建库才 400"


def test_export_warns_when_unsaved_selection():
    seg = _seg("bExp.onclick", "row.appendChild(bExp)")
    assert "尚未建库" in seg, "导出读的是磁盘配置，必须提示与面板选择无关"


def test_export_picker_falls_back_to_main_module():
    import inspect
    from src import nav_api
    src = inspect.getsource(nav_api.nav_scope_export)
    assert '"__main__"' in src,         "发布包排除 src/main.py，frozen 下入口是 __main__，只查 src.main 会永不弹框"
    assert "from src import main as _m" not in src
