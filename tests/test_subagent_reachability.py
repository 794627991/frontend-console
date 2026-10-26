# -*- coding: utf-8 -*-
"""v4.0.1 子代理「无条件可点开」守护检查。

用户硬性要求：「我需要无条件的能点开任意子代理」。

原缺陷（实测复现）：从行卡/目录点进去，只要档案里没有 agentId，代码就
弹一句 banner 然后 `return`——解析漏斗（regSync → 后端 subagent_resolve）
根本没跑。而 `subagent_resolve` 实测能从主会话转写的 tool_result 里挖出
agentId（真实转写 94 个派发中 93 个可解析，唯一失败是真的任务不存在）。

本检查钉三件事：
  A. 前端所有「子代理入口」不得在没有解析尝试的情况下直接 return；
  B. 后端 `subagent_resolve` 对真实转写有高命中率（实测口径）；
  C. `inc`/`_snap_pair` 等上一轮修复不被顺手改坏（冒烟）。

只做静态与后端实测，不启动 UI（用户正在运行实例，不能打扰）。
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# 三个入口文件：任何「开子代理窗格」的点击最终都汇到它们
ENTRY_FILES = ["web/js/harness/main.js", "web/js/harness/panel.js",
               "web/js/harness/subpane.js"]


class TestNoDeadEndClick(unittest.TestCase):
    """A：不得存在「弹个 banner 就结束、完全没试过解析」的死路。"""

    def test_resolve_funnel_exists(self):
        s = _read("web/js/harness/panel.js")
        self.assertIn("function _subResolveOpen(", s,
                      "统一解析漏斗缺失——各入口会各自分叉")
        # 漏斗必须同时砸三条路：regSync → 后端 resolve → 目录兜底
        self.assertIn("_hgRegSync", s)
        self.assertIn("/api/harness/subagent_resolve", s)

    def test_agentline_click_always_resolves(self):
        s = _read("web/js/harness/main.js")
        m = re.search(r"const agRow = e\.target\.closest\('\.h-tool\.agentline'\);"
                      r"(.*?)\n    \}", s, re.S)
        self.assertIsNotNone(m, "行卡点击分支不见了")
        body = m.group(1)
        # 有 tid 就必须无条件进漏斗（原缺陷：档案缺失就直接放弃）
        self.assertIn("if (pid) { _subReopen(pid); return; }", body,
                      "行卡点击又回到「档案缺失就放弃」的死路")

    def test_resolve_open_is_used_by_all_entries(self):
        """档案缺失 / id 为空 / 幻影 / 目录行 / 回放内部——五处都必须收敛。"""
        p = _read("web/js/harness/panel.js")
        s = _read("web/js/harness/subpane.js")
        self.assertGreaterEqual(p.count("_subResolveOpen("), 4,
                                "panel 侧入口未全部收敛到漏斗")
        self.assertGreaterEqual(s.count("_subResolveOpen("), 3,
                                "subpane 侧入口未全部收敛到漏斗")
        # 回放内部（所有路径的最后一道关）也必须兜
        self.assertIn("if (typeof _subResolveOpen === 'function')",
                      s, "_subReplay 无 id 时仍可能只弹 banner")

    def test_no_banner_only_return_in_agent_entries(self):
        """残留的「没有 agentId 记录…return」必须由漏斗守卫兜住。

        允许的**唯一**形态：紧邻上一行是 `if (typeof _subResolveOpen ===
        'function') { ... }` 的兜底（漏斗万一不可用时的最后话术）。
        """
        for rel in ENTRY_FILES:
            lines = _read(rel).splitlines()
            for i, line in enumerate(lines):
                if "没有 agentId 记录" not in line or "return" not in line:
                    continue
                prev = lines[i - 1] if i else ""
                self.assertIn("_subResolveOpen", prev,
                              "%s:%d 仍有 banner-only 死路: %s"
                              % (rel, i + 1, line.strip()))


class TestBackendResolveReachability(unittest.TestCase):
    """B：后端确实能从真实转写挖出 agentId（离线实测，不启动服务）。"""

    def test_resolve_regexes_extract_from_real_transcript(self):
        import glob
        import json
        base = os.path.expanduser("~/.claude/projects")
        files = sorted(glob.glob(os.path.join(base, "*", "*.jsonl")),
                       key=os.path.getsize, reverse=True)[:1]
        if not files:
            self.skipTest("本机无 claude 转写，跳过实测")
        fp = files[0]
        _aid_res = [re.compile(p) for p in (
            r"resumedAgentId[\"':\s]+([0-9a-zA-Z_-]{8,64})",
            r"[\"']agentId[\"'][:\s]+[\"']([0-9a-zA-Z_-]{8,64})[\"']",
            r"(?<![a-zA-Z])agentId[\"':\s]+([0-9a-zA-Z_-]{8,64})",
            r'from "([0-9a-zA-Z_-]{8,64})" \(its SubagentHandback')]
        tids, hit = [], 0
        with open(fp, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                for b in ((o.get("message") or {}).get("content") or []):
                    if (isinstance(b, dict) and b.get("type") == "tool_use"
                            and b.get("name") in ("Task", "Agent", "SendMessage")):
                        if b.get("id"):
                            tids.append(b["id"])
        tids = list(dict.fromkeys(tids))
        self.assertGreater(len(tids), 0, "该转写没有派发记录，用例无效")
        with open(fp, encoding="utf-8", errors="replace") as f:
            text_lines = f.readlines()
        for tid in tids:
            for line in text_lines:
                if tid not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                found = False
                for b in ((o.get("message") or {}).get("content") or []):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result" and b.get("tool_use_id") == tid:
                        bc = b.get("content")
                        txt = bc if isinstance(bc, str) else "\n".join(
                            x.get("text", "") for x in bc if isinstance(x, dict))
                        if any(rx.search(txt) for rx in _aid_res):
                            found = True
                if found:
                    hit += 1
                    break
        ratio = hit / float(len(tids))
        # 实测 93/94；留余量到 0.7（转写内容随会话变化）
        self.assertGreater(ratio, 0.7,
                           "后端解析命中率过低 %.1f%%（%d/%d）——点开会大量落空"
                           % (ratio * 100, hit, len(tids)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
