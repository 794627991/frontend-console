# -*- coding: utf-8 -*-
"""v4 协议纯函数黄金夹具测试（Python 端）。

与 web/js/harness/v4proto.js 跑同一份 tests/v4_golden/golden.json——
双端语义一致是「投影+apply 纯函数共用」的可执行替身（ZCode 双端共享
代码，我们用共享夹具）。另含 wire_snapshot 尾窗与 removed 屏障的单测。
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# v4proto 是纯函数模块，直接按文件加载（包 __init__ 牵连 consts/app_state）
_spec = importlib.util.spec_from_file_location(
    "v4proto", os.path.join(ROOT, "src", "harness", "v4proto.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

GOLDEN = os.path.join(ROOT, "tests", "v4_golden", "golden.json")


class TestGoldenApplyCoalesce(unittest.TestCase):
    def _cases(self):
        with open(GOLDEN, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_python_apply_and_coalesce(self):
        for c in self._cases():
            with self.subTest(case=c["name"]):
                snap = copy.deepcopy(c["snapshot0"]) if c.get("snapshot0") \
                    else P.new_snapshot("")
                P.apply_deltas(snap, c["deltas"])
                self.assertEqual(snap, c["expect"], c["name"])
                if c.get("expect_coalesced"):
                    co = P.coalesce(c["deltas"])
                    self.assertEqual(co, c["expect_coalesced"], c["name"])
                    # 语义保持：apply(coalesce(ds)) ≡ apply(ds)
                    snap2 = copy.deepcopy(c["snapshot0"]) if c.get("snapshot0") \
                        else P.new_snapshot("")
                    P.apply_deltas(snap2, co)
                    self.assertEqual(snap2, snap, c["name"] + " equiv")

    def test_js_golden_same_cases(self):
        """JS 端跑同一夹具（node 在场则校验，不在场跳过不误报）。"""
        js = os.path.join(ROOT, "web", "js", "harness", "v4proto.js")
        try:
            r = subprocess.run(
                [sys.executable.replace("python", "node").replace("python3", "node"),
                 js, "--golden", GOLDEN]
                if False else ["node", js, "--golden", GOLDEN],
                capture_output=True, text=True, timeout=30,
                shell=(os.name == "nt"))
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("node 不可用")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("GOLDEN OK", r.stdout + r.stderr)


class TestWireSnapshot(unittest.TestCase):
    def test_tail_window(self):
        snap = P.new_snapshot("e")
        for i in range(1, 11):
            P.apply_delta(snap, P.d_row_appended(
                P.mk_row(i, "t", "marker", i, i, mkind="sysnote", text="x")))
        w = P.wire_snapshot(snap, tail=4)
        self.assertEqual([r["rowId"] for r in w["rows"]], [7, 8, 9, 10])
        self.assertEqual(w["total"], 10)          # total 仍是全量账
        self.assertEqual(w["firstRowId"], 7)

    def test_tail_turns_window(self):
        # a41：按回合裁窗——窗保最后 N+1 个完整回合（user 行数），回合内
        # 行（thinking/tool）不拦腰截断；行数 tail 作绝对上限兜底
        snap = P.new_snapshot("e")
        rid = 0
        for t in range(1, 6):                     # 5 轮，每轮 user+thinking+tool
            for kind, txt in (("user_input", "u%d" % t),
                              ("reasoning", "th"), ("tool_call", "tl")):
                rid += 1
                P.apply_delta(snap, P.d_row_appended(
                    P.mk_row(rid, "t%d" % t, kind, rid, rid, text=txt)))
        w = P.wire_snapshot(snap, tail_turns=2)   # 保最后 2+1=3 个 user 行起
        kinds = [r["kind"] for r in w["rows"]]
        self.assertEqual(kinds.count("user_input"), 3)
        self.assertEqual(kinds[0], "user_input")   # 窗起点=完整回合头
        self.assertEqual(w["turnsTotal"], 5)       # 真源仍是全量
        self.assertEqual(w["firstRowId"], 7)       # 第 3 轮 user 行=rowId 7
        # 行数兜底：tail_turns 裁完后仍超 tail 再按行裁
        w2 = P.wire_snapshot(snap, tail=4, tail_turns=99)
        self.assertEqual(len(w2["rows"]), 4)

    def test_unknown_op_noop(self):
        snap = P.new_snapshot("")
        P.apply_delta(snap, {"op": "row.moved", "rowId": 1})   # 封闭集外
        self.assertEqual(snap["rows"], [])
        self.assertEqual(snap["total"], 0)


if __name__ == "__main__":
    unittest.main()
