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
        # v4.0.4：探针组限定 tools/（本项目私有约定）——根目录同名不算
        for p in ("tools/_probe_gate.py", "tools/_selftest_matrix.py",
                  "tools/_stress_switch.py", "tools/_scan_form_fields.py"):
            self.assertEqual(_audit_lines("Write", _write_inp(p)), 0,
                             "%s 应豁免（tools/ 探针）" % p)

    def test_escape_attempts_still_counted(self):
        """v4.0.4/v4.0.5 逃逸面回归：normpath 消 .. + 目录域约束。"""
        for p in ("tests/../src/harness/session.py",
                  "src/tests/../audit.py",
                  "tests/../../../evil.py",
                  "src/_scan_big.py",          # 前缀无 tools/ 域
                  "web/_probe_x.js",           # 非 tools/ 目录
                  "tools/_probeable.py"):      # 边界：非 _probe_ 前缀
            self.assertGreater(_audit_lines("Write", _write_inp(p)), 0,
                               "%s 属产品代码逃逸，不得豁免" % p)

    def test_exempt_works_outside_repo_root(self):
        """v4.0.5（复审实锤）：豁免不得锚定运行代码所在目录。

        审计代码跑在后端进程里，会话 cwd 可能是 worktree / 用户项目 /
        发布版 exe 内。旧实现以 `_SRC_DIR` 上一级作根 → worktree 与
        任意用户项目的 tests/ 都计 501 行（需求1 失效）。
        """
        for p in ("D:/AI/otherproject/tests/test_a.py",
                  "D:/AI/otherproject/tools/_probe.py",
                  "D:/AI/串口控制台Pro-子代理重构/tests/test_x.py",
                  "pkg/tests/test_x.py",
                  "_selftest_matrix.py",       # 根级探针
                  "tools/_probe.py"):          # 尾下划线可省
            self.assertEqual(_audit_lines("Write", _write_inp(p)), 0,
                             "%s 应豁免（不得因不在仓库根下失去豁免）" % p)

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
        """`start()` 的注入条件不得看形态，也**不得看线值的启动快照**。

        v4.0.2 修掉 `not st[2]`（mid 不注入）；v4.0.4 进一步：注入条件
        不能看 design_limit() 的**启动瞬间**值——会话启动后再改配置、或
        启动时形态被误判成 heavy，钩子就永远缺席。闸开不开由 /audit_gate
        每次调用实时判定。
        """
        code = _code_lines("src/harness/session.py")
        i = next(k for k, l in enumerate(code)
                 if "_st_audit = self._audit_state()" in l)
        seg = "\n".join(code[i:i + 20])
        self.assertIn("_audit_hook_settings_path()", seg, "hook 注入点不见了")
        # 注入条件只应是「审计机制启用」（_audit_state 非 None）——
        # 任何 strong 旗 / design_limit 快照参与分流的写法都算回归
        self.assertNotIn("not _st_audit[2]", seg,
                         "start() 仍按 strong 旗排除 mid（事中闸不生效）")
        self.assertNotIn("design_limit", seg,
                         "start() 仍按启动瞬间的设计线判注入（配置改动不生效）")

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
        # 停止 ≠ 失败（用户语义：自己停的，不该红叉）；也 ≠ success
        # （v4.0.4：success 会被摘要/统计读成「有交付结论」）——用词表里
        # 已有的 cancelled 表达「被主动停」。
        self.assertEqual(after[0]["status"], "cancelled")
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

    def test_stopped_without_brief_still_flips_tool_row(self):
        """v4.0.6（复审实锤）：停止通知通常不带 summary——tool 行也必须翻。

        原门控 `if (_brief and ...)` 让无 summary 的停止通知跳过 tool 行回填，
        Task 工具行永停 running → F5/切回重建后行卡又变绿「完成」。
        """
        f = self._F.V4Feed(epoch="STOP2")
        f.ingest({"type": "turn_started"})
        f.ingest({"type": "cli_stream", "data": {
            "type": "assistant", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "call_x", "name": "Task",
                 "input": {"description": "干活"}}]}}})
        f.ingest({"type": "subagent_started", "tid": "call_x",
                  "agent_type": "reviewer", "desc": "干活", "aid": "aid_x"})
        f.ingest({"type": "subagent_result", "tid": "call_x", "ok": False,
                  "stopped": True, "brief": "", "aid": "aid_x",
                  "task_id": "aid_x"})
        tool = [r for r in f.snap["rows"] if r.get("kind") == "tool_call"
                and r.get("tid") == "call_x"]
        self.assertTrue(tool, "tool 行丢了")
        self.assertEqual(tool[0]["status"], "cancelled",
                         "无 brief 的停止通知未翻 tool 行（重建后画成完成）")
        self.assertIn("已停止", str(tool[0].get("output") or ""))

    def test_empty_tid_stop_flips_authoritative_tool_row(self):
        """v4.0.6（复审实锤）：空 tid 的停止通知也必须翻权威 Task tool 行。

        停止通知不带 tool-use-id → session 反查可能落空（冷启动窗口）→ tid
        为空。原实现 `_flip_tool = (_stopped and tid)` 直接跳过 tool 行，
        SUB 行翻了 cancelled 但 tool 行永停 running → F5/切回又是假运行。
        """
        f = self._F.V4Feed(epoch="STOP3")
        f.ingest({"type": "turn_started"})
        f.ingest({"type": "cli_stream", "data": {
            "type": "assistant", "message": {"model": "m", "content": [
                {"type": "tool_use", "id": "call_y", "name": "Task",
                 "input": {"description": "干活"}}]}}})
        f.ingest({"type": "subagent_started", "tid": "call_y",
                  "agent_type": "reviewer", "desc": "干活", "aid": "aid_y"})
        # 空 tid + 只带 aid（真实停止通知形态）
        f.ingest({"type": "subagent_result", "tid": "", "ok": False,
                  "stopped": True, "brief": "", "aid": "aid_y",
                  "task_id": "aid_y"})
        tool = [r for r in f.snap["rows"] if r.get("kind") == "tool_call"
                and r.get("tid") == "call_y"]
        self.assertTrue(tool, "tool 行丢了")
        self.assertEqual(tool[0]["status"], "cancelled",
                         "空 tid 的停止通知没翻权威 tool 行（重建后假运行）")
        # SUB 行同翻
        subs = [r for r in f.snap["rows"] if r.get("kind") == "subagent"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["status"], "cancelled")
        # pending 残留已清
        self.assertNotIn("call_y", f._pending_agents,
                         "空 tid 路径没清 _pending_agents（跨会话累积）")

    # （test_no_tid_stop_branch_is_reachable 已删——a138 退役 sse.js 后成
    #  空壳；无 tid 停止收口的行为由本类上方的 feed 级测试覆盖）

    def test_cold_sync_keeps_stopped(self):
        """v4.0.6：Sync 不得抹掉本地已停止事实（后端未 flush 时仍报 running）。"""
        src = open(os.path.join(ROOT, "web/js/harness/registry.js"),
                   encoding="utf-8").read()
        # 必须有「本地 stopped 优先保留」的显式分支
        self.assertIn("_lv.stopped", src,
                      "Sync 未保留本地 stopped → 每轮 Sync 抹成运行中/完成")
        self.assertIn("loc.stopped = true", src)

    def test_v4_sub_row_terminal_passes_stopped(self):
        """v4.0.5/v4.0.6：SUB 行终态行卡收口与子窗格收口都要传 stopped。"""
        src = open(os.path.join(ROOT, "web/js/harness/v4bridge.js"),
                   encoding="utf-8").read()
        i = src.index("ars(row.tid, row.status === 'failed'")
        seg = src[i:i + 300]
        self.assertIn("stopped", seg, "SUB 行终态未传 stopped")
        self.assertIn("cancelled", seg, "未识别 cancelled 状态")
        # 子窗格 _subFinish 收口（复审实锤的第二处漏传）
        j = src.index("_ars2(_rowSt.dataset.tid || _tidM")
        seg2 = src[j:j + 400]
        self.assertIn("stopped", seg2,
                      "_subFinish 未传 stopped → 2.5s 后行卡翻回「完成」")


    def test_v4_compaction_ticker(self):
        """a122（用户实锤「压缩不读秒，一直 0s」）：v4 管线必须自建秒表。

        v4bridge 原先只置 compactT0 渲染一次，1s 定时器只有 V3 sse.js 的
        status 分支建 → v4 下秒数恒 0。断言：v4 分支必须起 setInterval，
        且离开压缩态必须 clearInterval（否则定时器泄漏、rAF 永跑）。
        """
        src = open(os.path.join(ROOT, "web/js/harness/v4bridge.js"),
                   encoding="utf-8").read()
        i = src.index("if (typeof patch.compacting === 'boolean'")
        seg = src[i:i + 1400]
        self.assertIn("setInterval", seg,
                      "v4 压缩分支未起 1s 秒表 → 秒数冻在 0")
        self.assertIn("clearInterval", seg,
                      "v4 压缩结束未清定时器 → 泄漏")
        self.assertIn("compactTimer", seg)
        # 清定时器必须置 null：主清点在 relay._hgCompactionEnd（a142 起
        # v4 压缩收口统一走它）；v4bridge 定时器体内另有自清（不在本守卫）
        for rel, anchor in (("web/js/harness/relay.js", "function _hgCompactionEnd()"),):
            s2 = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            j = s2.index(anchor)
            self.assertIn("_HG.compactTimer = null", s2[j:j + 900],
                          rel + " 清定时器未置 null → v4 秒表判定失效")

    def test_run_chains_picks_latest_not_first(self):
        """a122：胶囊假运行——同链幽灵档先被遍历到会占住 cid。

        实测实体：live 残留档（键=tool_use_id、done:false、doneAt:0）与权威
        档（done:true/interrupted）共链，旧实现 `if (seen.has(cid)) continue`
        先到先占 → 胶囊恒「子代理执行中」。判据必须按「最近事件时刻」
        （doneAt||t0）取最大者定运行态。
        """
        src = open(os.path.join(ROOT, "web/js/harness/panel.js"),
                   encoding="utf-8").read()
        i = src.index("function _hgRunChains()")
        seg = src[i:src.index("function _hgPeerLines()")]
        self.assertNotIn("if (seen.has(cid)) continue", seg,
                         "仍是先到先占判据 → 幽灵档可占住 cid")
        # 判据必须含 sendAt：生产续派是就地复活原档（不改 t0，只写 sendAt），
        # 只取 max(doneAt,t0) 会把刚复活的链判成上一轮已结束（审计实锤）
        self.assertIn("a.sendAt", seg,
                      "未计入 sendAt → 续派复活后被误判为已结束")
        self.assertIn("doneAt", seg, "未按最近事件时刻定运行态")
        self.assertIn("best", seg)
        self.assertIn("at === prev.at", seg,
                      "平局未做 done 优先（终态档 doneAt 可为 0）")
        # 前提事实防漂移：复活只写 sendAt，绝不动 t0
        vb = open(os.path.join(ROOT, "web/js/harness/v4bridge.js"),
                  encoding="utf-8").read()
        k = vb.index("_orig.done = false; _orig.doneAt = 0;")
        self.assertIn("_orig.sendAt", vb[k:k + 500],
                      "复活未写 sendAt → 轮次栅栏失效")
        self.assertNotIn("_orig.t0 =", vb[k:k + 500],
                         "复活改了 t0 → 判据前提失效")
        # Sync 侧同口径清理幽灵档（否则目录/计数仍见假运行条目）
        reg = open(os.path.join(ROOT, "web/js/harness/registry.js"),
                   encoding="utf-8").read()
        self.assertIn("b.done && b.k !== k", reg,
                      "Sync 未清理同链幽灵档 → 目录/胶囊仍假运行")
        self.assertIn("a.sendAt", reg, "Sync 清理判据漏 sendAt")

    def test_v4_close_resets_compaction(self):
        """a122（审计）：v4 不连旧流，压缩结束事件丢失时无人收口。

        必须在 v4Close 直接复位三字段——且**不能**调 _hgCompactionEnd
        （它会置 compactResume，压缩未结束就置 = 回原会话误 reopen）。
        """
        src = open(os.path.join(ROOT, "web/js/harness/v4main.js"),
                   encoding="utf-8").read()
        i = src.index("function v4Close()")
        seg = src[i:i + 900]
        self.assertIn("_HG.compacting = false", seg)
        self.assertIn("_HG.compactSid = null", seg)
        self.assertIn("compactTimer = null", seg)
        self.assertNotIn("_hgCompactionEnd()", seg,
                         "误用 _hgCompactionEnd → 置 compactResume 致误 reopen")


if __name__ == "__main__":
    unittest.main(verbosity=2)
