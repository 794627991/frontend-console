# -*- coding: utf-8 -*-
"""a122 行为级回归：胶囊链判定与 Sync 幽灵档清理。

**为什么不用字符串断言**：v4.0.7 复审实锤「assertIn("setInterval", seg) 只能
防回退，不证行为」。这里直接从源文件抽出真实函数体，交给 node 执行，用
六组场景验证返回值——改判据必然改变返回值，改注释不会误报。

场景来源（用户实锤现场）：
  · 幽灵档 `call_8c9c…` = {done:false, doneAt:0, t0:T}（47h 前 live 残留）
  · 权威档 `a57ea…`     = {done:true, interrupted, doneAt:T+50073, t0:T}
  → 胶囊显示「子代理执行中」，而该代理早已终结。

审计追加的关键场景：**续派是就地复活原档**（v4bridge.js:747-755 只写
sendAt 不动 t0），所以判据漏 sendAt 会把刚复活的链判成上一轮已结束。
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
T = 1792979214851

# 从 panel.js 抽出 _hgRunChains 的真实实现体（到下一个函数为止）
_RUNCHAIN_JS = r"""
const fs = require('fs');
const path = process.argv[1];
const src = fs.readFileSync(path, 'utf8');
const i = src.indexOf('function _hgRunChains()');
const j = src.indexOf('function _hgPeerLines()');
if (i < 0 || j < 0) { console.log('EXTRACT_FAIL'); process.exit(0); }
const body = src.slice(i, j);
const fn = new Function('_HG', body + '; return _hgRunChains;');
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const name in cases) {
  out[name] = fn({ agents: cases[name] })().map(a => a.taskId);
}
console.log(JSON.stringify(out));
"""

_CLEANUP_JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a0 = src.indexOf('// a122（用户实锤「子代理明明结束了');
const a1 = src.indexOf('_HG.agents = agents;', a0);
if (a0 < 0 || a1 < 0) { console.log('EXTRACT_FAIL'); process.exit(0); }
const block = src.slice(a0, a1);
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const name in cases) {
  const agents = cases[name];
  new Function('agents', block)(agents);
  out[name] = Object.keys(agents).sort();
}
console.log(JSON.stringify(out));
"""


def _node_eval(script, file_rel, cases):
    if not NODE:
        raise unittest.SkipTest("node 不可用")
    fd = os.path.join(ROOT, file_rel)
    r = subprocess.run([NODE, "-e", script, fd, json.dumps(cases)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    raw = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    # 先判原文再 json.loads——否则抽取失败时报的是 JSONDecodeError，看不出根因
    assert "EXTRACT_FAIL" not in raw, \
        "源码抽取失败（函数被改名/定位注释动了？）：%s" % file_rel
    return json.loads(raw)


def _ghost():
    return {"taskId": "A", "done": False, "doneAt": 0, "t0": T}


def _auth():
    return {"taskId": "A", "done": True, "interrupted": True,
            "doneAt": T + 50073, "t0": T}


class TestRunChains(unittest.TestCase):
    def test_cases(self):
        cases = {
            # 用户实锤现场：残留 + 权威档 → 不该算运行中
            "live": {"g": _ghost(), "a": _auth()},
            # 审计问题1：续派就地复活（只加 sendAt，t0 不变）
            "renew": {"one": {"taskId": "A", "done": False, "doneAt": 0,
                              "t0": T, "sendAt": T + 100000}},
            "renew_ghost": {
                "live": {"taskId": "A", "done": False, "doneAt": 0,
                         "t0": T, "sendAt": T + 100000},
                "old": {"taskId": "A", "done": True, "doneAt": T + 50000,
                        "t0": T}},
            # 两条都在跑：一条一计
            "two_running": {
                "a": {"taskId": "A", "done": False, "doneAt": 0, "t0": T},
                "b": {"taskId": "A", "done": False, "doneAt": 0, "t0": T + 5000}},
            # 审计问题3：doneAt 均可为 0 → 平局时 done 优先（不算运行中）
            "tie": {"g": _ghost(), "a": {"taskId": "A", "done": True,
                                         "doneAt": 0, "t0": T}},
            "all_done": {"a": {"taskId": "A", "done": True, "doneAt": T}},
        }
        got = _node_eval(_RUNCHAIN_JS, "web/js/harness/panel.js", cases)
        self.assertEqual(got["live"], [], "幽灵档占住 cid → 胶囊假运行")
        self.assertEqual(got["renew"], ["A"], "续派复活被误判为已结束")
        self.assertEqual(got["renew_ghost"], ["A"], "续派复活被残留 done 档压制")
        self.assertEqual(got["two_running"], ["A"], "同链应一计")
        self.assertEqual(got["tie"], [], "平局未做 done 优先")
        self.assertEqual(got["all_done"], [])


class TestSyncCleanup(unittest.TestCase):
    def test_cases(self):
        cases = {
            "live": {"ghost": _ghost(), "auth": _auth()},
            "renew": {"live": {"taskId": "A", "done": False, "doneAt": 0,
                               "t0": T, "sendAt": T + 100000}},
            "renew_ghost": {
                "live": {"taskId": "A", "done": False, "doneAt": 0,
                         "t0": T, "sendAt": T + 100000},
                "old": {"taskId": "A", "done": True, "doneAt": T + 50000,
                        "t0": T}},
            "two_running": {
                "a": {"taskId": "A", "done": False, "doneAt": 0, "t0": T},
                "b": {"taskId": "A", "done": False, "doneAt": 0, "t0": T + 5000}},
            "tie": {"g": _ghost(), "a": {"taskId": "A", "done": True,
                                         "doneAt": 0, "t0": T}},
        }
        got = _node_eval(_CLEANUP_JS, "web/js/harness/registry.js", cases)
        self.assertEqual(got["live"], ["auth"], "幽灵档未被清 → 目录仍假运行")
        # 续派复活：绝不能把在跑的档删掉（审计问题5）
        self.assertEqual(got["renew"], ["live"], "误删刚复活的运行档")
        self.assertEqual(got["renew_ghost"], ["live", "old"],
                         "误删运行档或误删残留档")
        # 两条都真在跑：都不许删
        self.assertEqual(got["two_running"], ["a", "b"], "删掉了真在跑的档")
        self.assertEqual(got["tie"], ["a"], "平局未做 done 优先")


class TestRenewStampCoverage(unittest.TestCase):
    """a122 复审：sendAt 必须覆盖**全部**就地复活点，不只 v4 一条。

    V3 是默认管线（v4main.js 里 v4 默认关）。四处复活点任何一处漏写
    sendAt，同链残留 done 档就会压过刚复活的运行档 —— 真在跑的代理不显示。
    这几处嵌在事件处理闭包里难以单独执行，退而用「复位语句附近必须出现
    sendAt」的形式守护（判据本身的行为已由 TestRunChains 行为级覆盖）。
    """

    def test_all_renew_sites_write_send_at(self):
        sse = open(os.path.join(ROOT, "web/js/harness/sse.js"),
                   encoding="utf-8").read()
        vb = open(os.path.join(ROOT, "web/js/harness/v4bridge.js"),
                  encoding="utf-8").read()
        # 锚定**赋值形态**（不是裸 "sendAt"）：注释里出现「不写 sendAt」
        # 之类的字样不该让断言误通过——复审实锤过这个漏洞。
        import re as _re
        sites = [
            (sse, "_orig3.done = false; _orig3.doneAt = 0;", "_orig3", "sse task_started 归并"),
            (sse, "_m2.done = false; _m2.doneAt = 0;", "_m2", "sse 包装 task_started 归并"),
            (sse, "_orig.done = false; _orig.doneAt = 0;", "_orig", "sse SendMessage 归并"),
            (vb, "_orig.done = false; _orig.doneAt = 0;", "_orig", "v4bridge SendMessage 归并"),
        ]
        for src, anchor, var, label in sites:
            self.assertIn(anchor, src, "%s 定位锚点消失（源码被改写？）" % label)
            k = src.index(anchor)
            seg = src[k:k + 500]
            self.assertTrue(
                _re.search(r"\b%s\.sendAt\s*=\s*Date\.now\(\)" % _re.escape(var), seg),
                "%s 未写 sendAt 赋值 → 复活后被残留 done 档压制" % label)

    def test_sync_fence_and_carry(self):
        """Sync 重建既不能丢 sendAt，也不能采纳上一轮的 done/err。

        栅栏的**逻辑**由 TestRegFence 行为级覆盖；这里只守接线（键归一
        一致、sendAt 带进新档案、pending 分支也接栅栏）。
        """
        reg = open(os.path.join(ROOT, "web/js/harness/registry.js"),
                   encoding="utf-8").read()
        self.assertIn("sendBy", reg, "Sync 未按 agentId 回填 sendAt")
        self.assertIn("_sendAtFor", reg,
                      "栅栏取值未与 sendBy 共用键归一 → pending/裸键条目永不命中")
        self.assertIn("loc.sendAt = _sAt", reg,
                      "Sync 重建未把 sendAt 带到新档案")
        # pending 分支也必须接栅栏（复审问题3：原先直接落键、sendAt 丢失）
        i = reg.index("if (k.indexOf('pending:') === 0)")
        seg = reg[i:i + 1600]
        self.assertIn("_regFence(", seg, "pending 分支未接栅栏")
        self.assertIn("_pSAt", seg, "pending 分支未带 sendAt")


class TestRegFence(unittest.TestCase):
    """a122 三修：Sync 轮次栅栏的三道保险（行为级）。

    从 registry.js 抽出 `_regFence` 真实函数体执行。复审实锤过：只做字符串
    断言时把保险②换成 `const _localNewer = false;` 仍能通过——必须验行为。
    """

    def test_cases(self):
        script = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const i = src.indexOf('function _regFence(');
const j = src.indexOf('function _regCid(', i);
if (i < 0 || j < 0) { console.log('EXTRACT_FAIL'); process.exit(0); }
const fn = new Function(src.slice(i, j) + '; return _regFence;')();
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const n in cases) { const c = cases[n]; out[n] = fn(c[0], c[1], c[2], c[3]); }
console.log(JSON.stringify(out));
"""
        S = T + 100000
        cases = {
            # [status, eAt, sAt, lv]
            # 上一轮 done（早于续派）→ 翻回
            "stale_done": ["done", T + 50000, S, None],
            # 本轮 done（晚于续派）→ 保持终态
            "fresh_done": ["done", S + 1000, S, None],
            # 保险①：interrupted 是启发式，绝不翻回
            "interrupted": ["interrupted", T + 50000, S, None],
            # 无 sendAt（没续派过）→ 不设栅栏
            "no_send": ["done", T + 50000, 0, None],
            # 保险②：本地已有不早于 sendAt 的终态事实 → 不得翻回
            "local_newer": ["done", T + 50000, S,
                            {"done": True, "doneAt": S + 60000}],
            # 保险②：本地终态早于 sendAt（上一轮的）→ 可以翻回
            "local_older": ["done", T + 50000, S,
                            {"done": True, "doneAt": T + 10000}],
            # 保险②：本地终态但**无时间凭证**（doneAt=0，有损重建/histcache）
            # → 保守按「不得翻回」，否则 0>=sAt 恒假让保险② 静默失效
            "local_no_stamp": ["done", T + 50000, S,
                               {"done": True, "doneAt": 0}],
            # 保险②：本地未 done → 不阻止翻回
            "local_running": ["stopped", T + 50000, S,
                              {"done": False, "doneAt": 0}],
        }
        got = _node_eval(script, "web/js/harness/registry.js", cases)
        self.assertTrue(got["stale_done"], "上一轮 done 未翻回 → 续派后链假结束")
        self.assertFalse(got["fresh_done"], "本轮 done 被误翻回 → 永远收不了尾")
        self.assertFalse(got["interrupted"], "启发式被当栅栏依据 → 静默死亡永不落定")
        self.assertFalse(got["no_send"], "无 sendAt 却设栅栏")
        self.assertFalse(got["local_newer"],
                         "推翻 v4.0.6：本地更新的 stopped/done 被抹掉")
        self.assertTrue(got["local_older"], "本地上一轮终态应允许翻回")
        self.assertFalse(got["local_no_stamp"],
                         "doneAt 缺失时保险② 静默失效（0>=sAt 恒假）")
        self.assertTrue(got["local_running"], "本地运行档不该阻止翻回")


class TestRegLiveOf(unittest.TestCase):
    """a122 四修：live 表多键解析。

    live 期档案以 **tid 键**建立（sse/v4bridge 建档），投影键是 agentId；
    首个 Sync 之前 `live[k]` 恒 undefined → v4.0.6（本地 stopped 不得被抹）
    与保险② 同时失效，用户主动停止的档被翻回运行中（复审模拟实锤）。
    """

    def test_cases(self):
        script = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const i = src.indexOf('function _regCid(');
const j = src.indexOf('async function _hgRegSync(', i);
if (i < 0 || j < 0) { console.log('EXTRACT_FAIL'); process.exit(0); }
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const n in cases) {
  const c = cases[n];
  const fn = new Function('_HG', src.slice(i, j) + '; return _regLiveOf;')(
    { tidMap: c.tidMap || {}, aidKey: c.aidKey || {} });
  const got = fn(c.key, c.live);
  // 返回可区分标识（cid + done + 时间戳），否则同链多档无法断言选了哪条
  out[n] = got ? [got.taskId || got.agentId || 'HIT', !!got.done,
                  got.doneAt || 0, got.sendAt || 0].join('|') : null;
}
console.log(JSON.stringify(out));
"""
        # 核心场景：投影键=agentId 'A'，live 档案以 tid 'call_1' 为键
        cases = {
            "by_tidmap": {
                "key": "A", "live": {"call_1": {"taskId": "A", "done": True}},
                "tidMap": {"call_1": "A"}},
            "by_aidkey": {
                "key": "A", "live": {"call_2": {"taskId": "A", "done": True}},
                "aidKey": {"A": "call_2"}},
            "direct": {
                "key": "A", "live": {"A": {"taskId": "A"}}},
            "pending_prefix": {
                "key": "pending:call_3",
                "live": {"call_3": {"taskId": "A"}}, "tidMap": {}},
            "reverse_cid": {
                "key": "A", "live": {"call_9": {"taskId": "A"}},
                "tidMap": {}, "aidKey": {}},
            "miss": {"key": "Z", "live": {"call_1": {"taskId": "A"}}},
            # a122 五修（复审实锤）：aidKey 只记**首次** tid，指向旧残留档；
            # 同链另有新活档。必须选活档，否则保险② 反过来把在跑的链判成
            # 已结束（缺陷的反向回归）。
            "pick_newest": {
                "key": "A",
                "live": {"call_1": {"taskId": "A", "done": True, "doneAt": 0},
                         "call_2": {"taskId": "A", "done": False,
                                    "doneAt": 0, "sendAt": T + 100000}},
                "aidKey": {"A": "call_1"}},
            # 反向：两条都 done，取 doneAt 更晚的
            "pick_latest_done": {
                "key": "A",
                "live": {"call_1": {"taskId": "A", "done": True,
                                    "doneAt": T + 1000},
                         "call_2": {"taskId": "A", "done": True,
                                    "doneAt": T + 9000}},
                "aidKey": {"A": "call_1"}},
        }
        got = _node_eval(script, "web/js/harness/registry.js", cases)
        for k in ("by_tidmap", "by_aidkey", "direct", "pending_prefix",
                  "reverse_cid"):
            self.assertTrue(got[k] and got[k].startswith("A|"),
                            "%s 未定位到档案 → 本地 stopped 被抹 / 保险②失效"
                            % k)
        self.assertIsNone(got["miss"], "无关键误命中别的链")
        # 必须选**活档**（done=false + sendAt），不是 aidKey 指向的旧残留
        self.assertEqual(got["pick_newest"],
                         "A|false|0|%d" % (T + 100000),
                         "选到旧残留 done 档 → 在跑的链被判成已结束")
        self.assertEqual(got["pick_latest_done"], "A|true|%d|0" % (T + 9000),
                         "同链两终态档未取最新")


class TestSyncBlockIntegration(unittest.TestCase):
    """a122 四修·集成：真实 Sync 循环体执行。

    上面 TestRegLiveOf 只验 `_regLiveOf` 本身；复审指出「多键解析写对了
    但调用点仍用 live[k]」这类缝会无声——变异实跑确认过。这里把
    `const _lv = ...` 到 `agents[k] = loc;` 整段抽出来执行，绑定真实函数。
    """

    def test_local_stopped_survives_under_tid_key(self):
        script = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a0 = src.indexOf('function _regFence(');
const a1 = src.indexOf('async function _hgRegSync(', a0);
if (a0 < 0 || a1 < 0) { console.log('EXTRACT_FAIL'); process.exit(0); }
const helpers = src.slice(a0, a1);           // _regFence/_regCid/_regLiveOf

const b0 = src.indexOf('const _lv = _regLiveOf(k, live);');
const b1 = src.indexOf('agents[k] = loc;', b0);
if (b0 < 0 || b1 < 0) { console.log('EXTRACT_FAIL'); process.exit(0); }
const loop = src.slice(b0, b1 + 'agents[k] = loc;'.length);

const c = JSON.parse(process.argv[2]);
const _HG = { tidMap: c.tidMap || {}, aidKey: c.aidKey || {} };
const fn = new Function('_HG', 'k', 'jAg', 'live', 'loc0', 'sendBy',
  '_sendAtFor', 'agents', helpers + `
  const loc = loc0;
  const modelBy = {};
  ${loop}
  return loc;`);
const sendBy = {};
const _sendAtFor = (k2) => sendBy[k2] || 0;
const out = fn(_HG, c.key, c.proj, c.live, c.loc0, sendBy, _sendAtFor, {});
console.log(JSON.stringify(out));
"""
        S = T + 100000
        # 核心缝：live 档案挂 tid 键 'call_1'，投影键是 agentId 'A'
        proj = {"A": {"status": "done", "doneAt": T + 50000}}
        live_tid = {"call_1": {"taskId": "A", "agentId": "A", "done": True,
                              "stopped": True, "doneAt": S + 60000,
                              "sendAt": S}}
        live_self = {"A": {"taskId": "A", "agentId": "A", "done": True,
                           "stopped": True, "doneAt": S + 60000, "sendAt": S}}
        case = {"key": "A", "proj": proj, "live": live_tid, "loc0": {
            "type": "designer", "taskId": "A", "agentId": "A",
            "done": True, "err": False, "stopped": False,
            "interrupted": False, "doneAt": T + 50000}}
        case_send = dict(case)
        case_send["sendBy"] = {"A": S}

        # ① 本地 stopped 在 tid 键下必须保留
        got = _node_eval(script, "web/js/harness/registry.js", case)
        self.assertTrue(got.get("stopped"),
                        "live 挂 tid 键时本地 stopped 被抹（v4.0.6 回归）")

        # ② 保险② 在 tid 键下也必须挡住「上一轮 done」
        script2 = script.replace("const sendBy = {};",
                                 "const sendBy = c.sendBy || {};")
        got2 = _node_eval(script2, "web/js/harness/registry.js", case_send)
        self.assertTrue(got2.get("done") and got2.get("stopped"),
                        "保险② 在 tid 键下失效 → 本地终态被翻回运行中")


if __name__ == "__main__":
    unittest.main(verbosity=2)
