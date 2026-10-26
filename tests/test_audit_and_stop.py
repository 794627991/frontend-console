# -*- coding: utf-8 -*-
"""v4.0.2/v4.0.3 用户报告的三个问题守护测试。

## 问题1：测试用途脚本不该计入审计行数
用户原话：「所有测试用途的脚本不应该计算的」。原 `_audit_lines` 只豁免
纯文档后缀（.md/.txt…），`tests/test_v4_inc.py` 写 500 行照样计 500 行
——设计线/审计线被测试代码白白推高。

## 问题2：事中闸不生效（只事后咬）
用户原话：「正常设计拦截必须是中途拦截，而不是事后拦截，事中闸还是未
生效」。根因=口径不一致：
  · `session.start()` 注入 hook 的条件是 `not st[2]`（只 light）
  · `_audit_settle()` 的设计档判定**不看 strong**（mid 照样事后咬）

## 问题3：停止子代理后胶囊仍显示运行
用户原话：「子代理已经停了，但是胶囊中还显示子代理运行」。根因=停止
通知 `<status>stopped</status>` **不带 tool-use-id**（只有 `<task-id>`
=agentId），`_emit_task_mirror` 在 `if not tid: return` 处直接丢弃 →
投影里的 SUB 行永远 running → 胶囊假运行。
"""
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.harness.audit import _audit_lines, _audit_is_test_path


def _code_lines(rel):
    """读文件但**剔掉注释行**——断言必须针对真实代码。

    教训：我第一版直接对源码整段做字符串断言，结果自己写的注释里
    引用了旧写法（"原 not st[2] 把 …"），测试立刻误报 FAIL。
    """
    out = []
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        for line in f:
            st = line.strip()
            if st.startswith("#") or st.startswith("//"):
                continue
            # 行内注释也剔（只留代码部分，粗略但足够）
            for mark in ("  # ", "  // "):
                k = line.find(mark)
                if k > 0:
                    line = line[:k]
            out.append(line.rstrip("\n"))
    return out


def _write_inp(path, n=500):
    return {"file_path": path, "new_string": "x" * n}


class TestTestScriptsExempt(unittest.TestCase):
    """问题1：测试用途路径不计行数。"""

    def test_tests_dir_exempt(self):
        for p in ("tests/test_v4_inc.py", "tests/fixtures/a.json",
                  "tests\\win\\path.py", "e2e/flow.js"):
            self.assertEqual(_audit_lines("Write", _write_inp(p)), 0,
                             "%s 应豁免（tests 目录）" % p)

    def test_probe_prefix_exempt(self):
        for p in ("tools/_probe_gate.py", "_selftest_matrix.py",
                  "tools/_stress_switch.py"):
            self.assertEqual(_audit_lines("Write", _write_inp(p)), 0,
                             "%s 应豁免（探针前缀）" % p)

    def test_test_suffix_exempt(self):
        for p in ("src/foo_test.py", "web/x.test.js", "src/y.spec.ts"):
            self.assertEqual(_audit_lines("Write", _write_inp(p)), 0,
                             "%s 应豁免（测试后缀）" % p)

    def test_product_code_still_counted(self):
        """**防矫枉过正**：产品代码必须照常计入，否则等于取消审计线。"""
        for p in ("src/harness/audit.py", "web/js/harness/main.js",
                  "src/proxy.py", "specs/foo.py"):   # specs/ 不是 tests/
            self.assertGreater(_audit_lines("Write", _write_inp(p)), 0,
                               "%s 是产品代码，不得豁免" % p)

    def test_unknown_path_not_exempt(self):
        """取不到路径时保守计入（不敢豁免未知目标）。"""
        self.assertGreater(_audit_lines("Write", {"new_string": "x" * 500}), 0)
        self.assertFalse(_audit_is_test_path(""))

    def test_edit_in_tests_exempt(self):
        inp = {"file_path": "tests/test_x.py", "old_string": "a" * 900,
               "new_string": "b" * 900}
        self.assertEqual(_audit_lines("Edit", inp), 0)


class TestGateConsistentWithSettle(unittest.TestCase):
    """问题2：事中闸与回合结算必须同一口径。"""

    def test_hook_injected_regardless_of_strong(self):
        """`start()` 的注入条件不得再看 strong 旗。

        原缺陷：`if _st_audit is not None and not _st_audit[2]` —— mid 形态
        (strong=True) 不注入 hook，但结算照样按设计线判违规 = 只事后咬。
        """
        code = _code_lines("src/harness/session.py")
        i = next(k for k, l in enumerate(code)
                 if "_st_audit = self._audit_state()" in l)
        seg = "\n".join(code[i:i + 20])
        self.assertIn("_audit_hook_settings_path()", seg, "hook 注入点不见了")
        # 主判据必须是设计线（形态无关）；`not _st_audit[2]` 只允许出现在
        # design_limit 读取失败的 except 兜底里，不能是主路径。
        self.assertIn("design_limit", seg, "主判据不是设计线（形态仍在分流）")
        main = seg.split("except Exception:")[0]
        self.assertNotIn("not _st_audit[2]", main,
                         "start() 主路径仍按 strong 旗排除 mid（事中闸不生效）")

    def test_gate_endpoint_not_gated_by_strong(self):
        """`/audit_gate` 也不得把 mid 挡在闸外。"""
        code = _code_lines("src/harness/routes.py")
        i = next(k for k, l in enumerate(code)
                 if "def harness_audit_gate" in l)
        seg = "\n".join(code[i:i + 30])
        self.assertNotIn("not st[2]", seg,
                         "/audit_gate 仍按 strong 旗排除（闸与结算口径不一致）")

    def test_gate_fires_at_design_line(self):
        """达线即拦（>=），未达不拦。"""
        from src.harness.roles import audit_gate_check, design_limit
        dl = design_limit()
        self.assertGreater(dl, 0, "本机设计线为 0，用例无意义")
        self.assertFalse(audit_gate_check(dl - 1, designed=False)[0])
        self.assertTrue(audit_gate_check(dl, designed=False)[0])
        # 已派 designer / 已审计 / 本回合已触发过 → 不拦
        self.assertFalse(audit_gate_check(dl, designed=True)[0])
        self.assertFalse(audit_gate_check(dl, designed=False, reviewed=True)[0])
        self.assertFalse(audit_gate_check(
            dl, designed=False, design_fired=True)[0])


class TestStoppedSubagentCloses(unittest.TestCase):
    """问题3：停止子代理必须把投影行翻终态，胶囊不再假运行。"""

    def setUp(self):
        import src.eventlog.store as _S
        from src.harness import v4feed as F
        self._F = F
        self._tmp = tempfile.mkdtemp(prefix="wseq_stop_")
        self._oS = _S._WSEQ_DIR
        self._oB = F.V4Feed._boot_path
        self._oBoot = F.V4Feed._boot
        _S._WSEQ_DIR = self._tmp
        F.V4Feed._boot_path = staticmethod(
            lambda: os.path.join(self._tmp, "BOOT"))
        F.V4Feed._boot = None
        F.V4Feed._hwm.clear()
        F.V4Feed._hwm_floor = 0

    def tearDown(self):
        import src.eventlog.store as _S
        _S._WSEQ_DIR = self._oS
        self._F.V4Feed._boot_path = self._oB
        self._F.V4Feed._boot = self._oBoot

    def _subs(self, f):
        return [r for r in f.snap["rows"] if r.get("kind") == "subagent"]

    def test_stopped_notification_closes_sub_row(self):
        """停止通知（无 tool-use-id，只带 aid）→ SUB 行必须离开 running。"""
        f = self._F.V4Feed(epoch="STOP1")
        f.ingest({"type": "subagent_started", "tid": "call_abc",
                  "agent_type": "reviewer", "desc": "审计任务",
                  "aid": "a17324c0725555d99"})
        before = self._subs(f)
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["status"], "running")
        # 停止：tid 是 agentId（session 侧反查失败时的兜底形态）
        f.ingest({"type": "subagent_result", "tid": "a17324c0725555d99",
                  "ok": False, "stopped": True, "brief": "",
                  "task_id": "a17324c0725555d99",
                  "aid": "a17324c0725555d99"})
        after = self._subs(f)
        self.assertEqual(len(after), 1, "不得新建第二行")
        self.assertNotEqual(after[0]["status"], "running",
                            "**胶囊假运行回归**：SUB 行仍是 running")
        # 停止 ≠ 失败（用户语义：自己停的，不该红叉）
        self.assertEqual(after[0]["status"], "success")
        self.assertTrue(after[0].get("stopped"), "缺 stopped 标记")
        # 空 brief 不得抹掉已有标题
        self.assertEqual(after[0]["summary"], "审计任务",
                         "brief 空时覆盖了 summary（行卡标题被抹）")

    def test_mirror_keeps_task_notification_without_tid(self):
        """session 侧不得丢弃缺 tool-use-id 的 task_notification。"""
        src = open(os.path.join(ROOT, "src/harness/session.py"),
                   encoding="utf-8").read()
        i = src.index('tid = str(o.get("tool_use_id") or "")')
        seg = src[i:i + 700]
        self.assertNotIn("if not tid:\n            return",
                         seg,
                         "缺 tid 仍直接丢弃 → 停止通知进不了投影")
        self.assertIn("task_notification", seg)
        self.assertIn("aid_to_tid", seg)

    def test_aid_to_tid_reverse_lookup(self):
        """agentId → tid 反查可用（停止通知的 key 桥）。"""
        from src.harness.subagent_readmodel import SubagentReadModel
        m = SubagentReadModel("probe", projects_root=tempfile.mkdtemp())
        m._proj = {"tidMap": {"call_1": "aidA", "call_2": "aidB"},
                   "agents": {"aidB": {"tids": ["call_2"]}}}
        self.assertEqual(m.aid_to_tid("aidA"), "call_1")
        self.assertEqual(m.aid_to_tid("aidB"), "call_2")
        self.assertEqual(m.aid_to_tid("none"), "")
        self.assertEqual(m.aid_to_tid(""), "")

    def test_frontend_badge_has_stopped(self):
        """前端徽章必须有「已停止」态（不是红叉也不是绿勾）。"""
        src = open(os.path.join(ROOT, "web/js/harness/tools.js"),
                   encoding="utf-8").read()
        self.assertIn("stopped:", src, "statusBadge 缺 stopped 映射")
        self.assertIn("已停止", src)

    def test_frontend_terminal_frame_uses_single_lookup(self):
        """终态帧收口不得只直查 agents[tid]（Sync 后键是 agentId）。"""
        src = open(os.path.join(ROOT, "web/js/harness/v4bridge.js"),
                   encoding="utf-8").read()
        i = src.index("var a = (typeof _hgAg === 'function'")
        seg = src[i:i + 800]
        self.assertIn("childTopic", seg, "缺 agentId 直配兜底")


if __name__ == "__main__":
    unittest.main(verbosity=2)
