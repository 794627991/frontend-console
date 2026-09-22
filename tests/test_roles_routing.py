# -*- coding: utf-8 -*-
"""最小自测：任务分级路由（v2.49）+ 三角色二次大改（v2.50）。

v2.49 覆盖四条：
1. light 引导词含 L0-L4 五档路由 / dev 同领域续派（SendMessage）/
   四要素上下文包协议 / 审核分级（免审/轻审/全审）/ 上限数字嵌词。
2. 审计兜底两档线判定（audit_verdict：L1 免审区干净、L2 未轻审违规、
   超 L2 属 L3 违规、dev 无 reviewer 违规、已派审不追责）+ 事中闸
   （audit_gate_check：L2 内放行、行/文件任一达线拦）。
3. 指纹热更：分级线改配置 → 引导词变 → _bridge_fp 指纹变；切模型
   （light↔strong）引导词/指纹变；开关关 → 空串。
4. 配置默认值/0 合法档/MultiEdit 行数口径/文件归一键。

v2.50 六项新增断言：
① 子代理 tools 无 Task（SendMessage 保留）、reviewer 工具集原样；
② 干活角色 body 含 git 禁提交条、reviewer body 无；
③ main_model 主会话槽：显式配置优先定形态、未配置回落名字识别、配置往返；
④ strong 引导词=干活者+审计兜底（无决策者/免审/档位词）+ 审计线数字嵌词
   + 指纹热更；audit_verdict strong 分支（超线未自查违规/线内干净/dev 不
   追责）；
⑤ P2 clamp_role_limits：l1>l2l 钳到 l2l、只调低 l2 带下现存 l1、相等不钳；
⑥ P1 派发/续派识别 _audit_dispatch_role（Task 名/SendMessage 裸名/带
   [ref]/agentId 映射/缺口形态 None）+ _audit_tally SendMessage 计旗 +
   strong 安装不装角色/退役文件清理/ensure_roles_ready 空。

隔离：CONFIG_FILE 重定向临时文件（不碰用户真 config.json）；HARNESS_AGENTS_DIR
重定向临时目录（不触真实 ~/.claude/agents）。直接 `py tests/test_roles_routing.py`
运行。
"""
import json
import os
import re
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 隔离配置（必须在 import src.* 前改 app_state.CONFIG_FILE）----
import src.app_state as _st
_TMP = tempfile.mkdtemp(prefix="roles_routing_test_")
_st.CONFIG_FILE = os.path.join(_TMP, "config.json")
os.environ.setdefault("HARNESS_AGENTS_DIR", _TMP)   # 双保险：装 agents 也进临时目录

import src.harness_roles as hr

LIGHT_MODEL = "glm-5.3-flash"
STRONG_MODEL = "glm-5.3"

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def write_cfg(**patch):
    with open(_st.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"harness_roles": patch}, f, ensure_ascii=False)


# ============ 1. 默认值与配置键 ============
print("[1] 配置默认值")
write_cfg(enabled=True)
d = hr.roles_cfg()
check("新三键默认 100/3/200", hr.audit_limits() == (100, 3, 200),
      str(hr.audit_limits()))
check("旧键 max_free_lines 已不在 defaults", "max_free_lines" not in d)

# ============ 2. light 引导词内容 ============
print("[2] light 引导词（L0-L4 分级路由）")
g = hr.roles_bridge_text(LIGHT_MODEL)
for kw, label in [
        ("L0", "L0 档"), ("L1", "L1 档"), ("L2", "L2 档"), ("L3", "L3 档"),
        ("L4", "L4 档"),
        ("免审", "免审字样"), ("轻审", "轻审字样"), ("全审", "全审字样"),
        ("SendMessage", "dev 续派策略"),
        ("四要素", "上下文包协议"),
        ("①目标", "四要素之目标"), ("②涉及文件+行号", "四要素之文件行号"),
        ("③已定决策", "四要素之决策"), ("④验收标准", "四要素之验收"),
        ("cmdlib.json", "L4 铁律文件"),
        ("≤100 行", "L1 行数嵌词"), ("≤3 个文件", "L2 文件数嵌词"),
        ("≤200 行", "L2 行数嵌词"),
        ("只审 diff", "轻审=只审 diff"),
        ("glm-5.3", "dev 模型名嵌词"),
        ("回合终点纪律", "终点纪律保留"),
        ("审计", "审计威慑保留")]:
    check(label, kw in g, "缺「%s」" % kw)

g_off = (write_cfg(enabled=True, audit_mode="off"), hr.roles_bridge_text(LIGHT_MODEL))[1]
check("audit_mode=off 威慑句切换", "重大流程违规" in g_off and "会审计" not in g_off)

# ============ 3. 形态切换与开关 ============
print("[3] 形态切换")
gs = hr.roles_bridge_text(STRONG_MODEL)
# v2.50 ④：strong=主会话直干（干活者+审计兜底），决策者/派发分工已砍
check("strong 词=干活者直干", "干活者" in gs and "亲自完成" in gs)
check("strong 词无派发分工词",
      all(w not in gs for w in ("决策者", "executor", "coder", "路由")))
check("strong 词无免审/档位词",
      all(w not in gs for w in ("免审", "L1", "L2", "L3", "L4")))
check("strong 词含审计兜底与线数字",
      "审计线" in gs and "自查" in gs and "≤3 个文件" in gs and "≤200 行" in gs)
check("light/strong 词不同", g != gs)
write_cfg(enabled=False)
check("开关关 → 空串", hr.roles_bridge_text(LIGHT_MODEL) == "")
write_cfg(enabled=True)

# ============ 4. 指纹热更 ============
print("[4] 指纹热更")
from src.claude_harness import _bridge_fp, _audit_lines, _audit_file_key
fp1 = _bridge_fp(LIGHT_MODEL)
write_cfg(enabled=True, l2_max_lines=150)
g2 = hr.roles_bridge_text(LIGHT_MODEL)
fp2 = _bridge_fp(LIGHT_MODEL)
check("改分级线 → 引导词变", g2 != g and "≤150 行" in g2)
check("改分级线 → 指纹变（热更触发）", fp1 != fp2)
check("切模型 → 指纹变（换形态）", _bridge_fp(STRONG_MODEL) != fp2)
write_cfg(enabled=True)
check("复原配置 → 指纹复原", _bridge_fp(LIGHT_MODEL) == fp1)

# ============ 5. 审计兜底判定（两档线） ============
print("[5] audit_verdict 两档线")
V = hr.audit_verdict
check("L1 区（50 行/1 文件）免审干净", V(50, 1, False, False) == [])
check("L1 区（100 行/1 文件）边界干净", V(100, 1, False, False) == [])
v = V(150, 1, False, False)
check("L2 区未轻审 → 违规且指明轻审", len(v) == 1 and "轻审" in v[0], str(v))
check("L2 区已轻审 → 干净", V(150, 1, False, True) == [])
check("2 文件小行数（超单文件规则）→ 须轻审",
      len(V(50, 2, False, False)) == 1 and "轻审" in V(50, 2, False, False)[0])
v = V(250, 2, False, False)
check("行数超 L2 → L3 违规（指派 dev）",
      len(v) == 1 and "L3" in v[0] and "dev" in v[0], str(v))
v = V(150, 4, False, False)
check("文件数超 L2 → L3 违规", len(v) == 1 and "L3" in v[0], str(v))
check("超 L2 但已派审 → 不追责（提示性兜底）", V(250, 2, False, True) == [])
check("dev 无 reviewer → 违规（原规则保留）",
      len(V(0, 0, True, False)) == 1 and "reviewer" in V(0, 0, True, False)[0])
check("dev+reviewer → 干净", V(0, 0, True, True) == [])
check("L1 区免审与 dev 派发并存且已审 → 干净", V(5, 1, True, True) == [])

print("[5b] 0 合法最严档")
write_cfg(enabled=True, l1_max_lines=0, l2_max_files=0, l2_max_lines=0)
check("全 0 线：1 行直改即属 L3 违规", len(V(1, 1, False, False)) == 1
      and "L3" in V(1, 1, False, False)[0])
write_cfg(enabled=True)

# ============ 6. 事中闸 ============
print("[6] audit_gate_check")
G = hr.audit_gate_check
check("L2 内（150 行/1 文件）放行", G(150, 1) == (False, None))
check("L2 内（100 行/2 文件）放行", G(100, 2) == (False, None))
b, m = G(200, 1)
check("行数达 L2 线 → 拦（>=口径）", b and "dev" in m, m or "")
b, m = G(100, 3)
check("文件数达 L2 线 → 拦", b and "dev" in m, m or "")
check("闸只守 L2 上限（旧 3 行微调不再拦）", G(3, 1) == (False, None)
      and G(10, 1) == (False, None) and G(99, 1) == (False, None))

# ============ 7. 行数/文件口径 ============
print("[7] 口径基础件")
n = _audit_lines("MultiEdit", {"edits": [
    {"old_string": "a\nb\nc", "new_string": "x"},
    {"old_string": "y", "new_string": "p\nq"}]})
check("MultiEdit 按块求和 max(old,new)", n == 5, str(n))
check("Edit 口径 max(old,new)=3",
      _audit_lines("Edit", {"old_string": "a\nb\nc", "new_string": "x"}) == 3)
k1 = _audit_file_key({"file_path": r"D:\AI\Proj\src\A.py"})
k2 = _audit_file_key({"file_path": "d:/ai/proj/src/a.py"})
check("文件归一（大小写/斜杠同文件同键）", k1 == k2 and k1 != "")
check("畸形输入不计文件", _audit_file_key({}) == "")

# ============ 8. 配置往返（update_roles_cfg merge） ============
print("[8] 配置往返")
ok, err = hr.update_roles_cfg({"l1_max_lines": 5, "l2_max_files": 1,
                               "l2_max_lines": 9})
check("merge 写盘 ok", ok, str(err))
check("写后线值生效", hr.audit_limits() == (5, 1, 9), str(hr.audit_limits()))
check("线值进引导词", "≤5 行" in hr.roles_bridge_text(LIGHT_MODEL))
check("收紧后判定跟着变", V(5, 1, False, False) == []
      and len(V(6, 1, False, False)) == 1)

# ============ 9. 主会话模型槽（v2.50 ③） ============
print("[9] 主会话模型槽")
check("main_model 默认空（回落自动识别）", hr.roles_cfg().get("main_model") == "")
write_cfg(enabled=True, main_model=STRONG_MODEL)
check("显式配置优先：实跑 flash 判 strong", hr.roles_mode(LIGHT_MODEL) == "strong")
check("形态随配置翻转 → 引导词同 strong",
      hr.roles_bridge_text(LIGHT_MODEL) == hr.roles_bridge_text(STRONG_MODEL))
write_cfg(enabled=True, main_model=LIGHT_MODEL)
check("配置 flash → 实跑 strong 判 light", hr.roles_mode(STRONG_MODEL) == "light")
ok, err = hr.update_roles_cfg({"main_model": ""})
check("清空回落名字自动识别", hr.roles_mode(LIGHT_MODEL) == "light"
      and hr.roles_mode(STRONG_MODEL) == "strong")
ok, err = hr.update_roles_cfg({"main_model": "glm-5.3-flash"})
check("配置往返 merge 保留", hr.roles_cfg().get("main_model") == "glm-5.3-flash")
hr.update_roles_cfg({"main_model": ""})

# ============ 10. strong 审计分支与指纹热更（v2.50 ④） ============
print("[10] strong 审计")
VS = hr.audit_verdict
check("strong 超线未自查 → 违规指明审计线",
      len(VS(250, 2, False, False, strong=True)) == 1
      and "审计线" in VS(250, 2, False, False, strong=True)[0]
      and "自查" in VS(250, 2, False, False, strong=True)[0])
check("strong 线内干净（直干是常态）",
      VS(150, 1, False, False, strong=True) == []
      and VS(100, 3, False, False, strong=True) == [])
check("strong 文件数超线也违规",
      len(VS(100, 4, False, False, strong=True)) == 1)
check("strong dev 派发不追责（无审派义务）",
      VS(50, 1, True, False, strong=True) == [])
check("strong 已派 reviewer 视作审过", VS(250, 2, False, True, strong=True) == [])
fp_s1 = _bridge_fp(STRONG_MODEL)
write_cfg(enabled=True, l2_max_lines=150)
check("strong 改审计线 → 词变+指纹变（热更）",
      "≤150 行" in hr.roles_bridge_text(STRONG_MODEL)
      and _bridge_fp(STRONG_MODEL) != fp_s1)
write_cfg(enabled=True)

# ============ 11. agent md：Task 移除 / git 禁提交 / reviewer 原样（v2.50 ①②） ============
print("[11] agent md（临时目录安装）")


def _tools_line(md):
    m = re.search(r"^tools: (.+)$", md, re.M)
    return m.group(1).strip() if m else ""


ad = hr._agents_dir()
for fn in ("executor.md", "coder.md", "designer.md", "dev.md", "reviewer.md"):
    p = os.path.join(ad, fn)
    if os.path.exists(p):
        os.remove(p)
# 预置 v2.49 旧版 strong 套装 → 验证一次性退役清理
for fn in ("executor.md", "coder.md", "designer.md"):
    with open(os.path.join(ad, fn), "w", encoding="utf-8") as f:
        f.write("---\nname: %s\n---\nold" % fn[:-3])
hr.install_roles_agents(STRONG_MODEL)
check("strong 不装任何角色（含退役清理）",
      not any(os.path.exists(os.path.join(ad, fn)) for fn in
              ("executor.md", "coder.md", "designer.md", "dev.md", "reviewer.md")))
check("strong ensure_roles_ready 空（无定义可自愈）",
      hr.ensure_roles_ready(STRONG_MODEL) == [])
hr.install_roles_agents(LIGHT_MODEL)
check("light 装 dev+reviewer", os.path.exists(os.path.join(ad, "dev.md"))
      and os.path.exists(os.path.join(ad, "reviewer.md")))
with open(os.path.join(ad, "dev.md"), encoding="utf-8") as f:
    dev_md = f.read()
with open(os.path.join(ad, "reviewer.md"), encoding="utf-8") as f:
    rev_md = f.read()
tl = _tools_line(dev_md).split(", ")
check("dev tools 无 Task（子代理禁派子代理）", "Task" not in tl)
check("dev tools 保留 SendMessage（续派回报链路）", "SendMessage" in tl)
check("dev tools 干活全集（含编辑类）",
      all(t in tl for t in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash")))
rtl = _tools_line(rev_md).split(", ")
check("reviewer tools 原样（Task 保留）", "Task" in rtl)
check("reviewer tools 只读（无编辑类）",
      not any(t in rtl for t in ("Edit", "Write", "MultiEdit", "NotebookEdit")))
check("dev body 含 git 禁提交铁律",
      "git commit" in hr._DEV_BODY and "留在工作区" in hr._DEV_BODY)
check("executor/coder body 含 git 禁提交铁律",
      "git commit" in hr._EXECUTOR_BODY and "git commit" in hr._CODER_BODY)
check("reviewer body 无 git 条（原样）", "git commit" not in hr._REVIEWER_BODY)

# ============ 12. P2 clamp：l1_max_lines ≤ l2_max_lines（v2.50 ⑥） ============
print("[12] P2 clamp")
C = hr.clamp_role_limits
p, n = C({"l1_max_lines": 300, "l2_max_lines": 200})
check("l1>l2l → clamp 到 l2l 并给原因",
      p["l1_max_lines"] == 200 and len(n) == 1 and n[0]["to"] == 200
      and "reason" in n[0])
p, n = C({"l2_max_lines": 50}, cfg={"l1_max_lines": 100, "l2_max_lines": 200})
check("只调低 l2 → 现存 l1 跟着钳（补进 patch）",
      p.get("l1_max_lines") == 50 and p["l2_max_lines"] == 50)
p, n = C({"l1_max_lines": 200, "l2_max_lines": 200})
check("相等合法不钳", not n and p["l1_max_lines"] == 200)
p, n = C({"l1_max_lines": 50})
check("l1<l2l 不钳", not n and p["l1_max_lines"] == 50)
p, n = C({"enabled": True})
check("不含线键的 patch 不动", p == {"enabled": True} and not n)

# ============ 13. P1 派发/续派识别（v2.50 ⑥） ============
print("[13] P1 派发/续派识别")
from src.claude_harness import _audit_dispatch_role as D
check("Task 按名计 dev", D("Task", {"subagent_type": "dev"}) == "dev")
check("Agent 按名计 reviewer", D("Agent", {"subagent_type": "reviewer"}) == "reviewer")
check("Task 其他代理不计", D("Task", {"subagent_type": "Explore"}) is None)
check("SendMessage 裸名续派计 dev", D("SendMessage", {"to": "dev"}) == "dev")
check("SendMessage 带 [ref] 计 reviewer",
      D("SendMessage", {"to": "reviewer [3fa9c1]"}) == "reviewer")
check("SendMessage 裸 agentId 查映射",
      D("SendMessage", {"to": "a1b2c3d4-9f0e"}, {"a1b2c3d4-9f0e": "dev"}) == "dev")
check("worker 无名形态 → None（缺口如实，见 docstring）",
      D("SendMessage", {"to": "worker [3fa9c1]"}) is None)
check("发 main 不计", D("SendMessage", {"to": "main"}) is None)
check("无关工具不计", D("Edit", {"file_path": "x"}) is None)

# _audit_tally 集成：SendMessage 续派 + Task 记 pending + result 回填映射
from src.claude_harness import HarnessSession as _HS
_fake = types.SimpleNamespace(_audit={"lines": 0, "files": [], "dev": False,
                                      "reviewer": False, "streak": 0,
                                      "ids": {}, "pending": {}})


def _ev(blocks, parent=None):
    o = {"message": {"content": blocks}}
    if parent:
        o["parent_tool_use_id"] = parent
    return o


_HS._audit_tally(_fake, _ev([
    {"type": "tool_use", "id": "tu1", "name": "Task",
     "input": {"subagent_type": "dev", "prompt": "x"}}]))
check("tally：Task dev 记旗+pending", _fake._audit["dev"]
      and "tu1" in _fake._audit["pending"])
_HS._audit_tally(_fake, _ev([
    {"type": "tool_use", "id": "tu2", "name": "SendMessage",
     "input": {"to": "dev [abc]", "message": "续"}}]))
check("tally：SendMessage 名字续派计旗（不再失明）", _fake._audit["dev"])
_HS._audit_tally_result(_fake, _ev([
    {"type": "tool_result", "tool_use_id": "tu1",
     "content": [{"type": "text",
                  "text": '{"agentId": "a11b22c33-d44e", "ok": true}'}]}]))
check("result 回填 agentId→dev 映射",
      _fake._audit["ids"].get("a11b22c33-d44e") == "dev"
      and not _fake._audit["pending"])
_HS._audit_tally(_fake, _ev([
    {"type": "tool_use", "id": "tu3", "name": "SendMessage",
     "input": {"to": "a11b22c33-d44e", "message": "再续"}}]))
check("tally：裸 agentId 续派经映射计旗", _fake._audit["dev"])
_sub = _ev([{"type": "tool_use", "id": "tu9", "name": "Task",
             "input": {"subagent_type": "reviewer"}}], parent="p1")
_HS._audit_tally(_fake, _sub)
check("子代理事件（parent_tool_use_id）不计", not _fake._audit["reviewer"])

print()
print("=" * 56)
print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
if _FAIL:
    print("失败项：", "、".join(_FAIL))
    sys.exit(1)
print("全部通过")
