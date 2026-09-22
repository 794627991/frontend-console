# -*- coding: utf-8 -*-
"""最小自测：任务分级路由重构（v2.49）——引导词生成 + 审计兜底判定。

覆盖验收四条：
1. light 引导词含 L0-L4 五档路由 / dev 同领域续派（SendMessage）/
   四要素上下文包协议 / 审核分级（免审/轻审/全审）/ 上限数字嵌词。
2. 审计兜底两档线判定（audit_verdict：L1 免审区干净、L2 未轻审违规、
   超 L2 属 L3 违规、dev 无 reviewer 违规、已派审不追责）+ 事中闸
   （audit_gate_check：L2 内放行、行/文件任一达线拦）。
3. 指纹热更：分级线改配置 → 引导词变 → _bridge_fp 指纹变；切模型
   （light↔strong）引导词/指纹变；开关关 → 空串。
4. 配置默认值/0 合法档/MultiEdit 行数口径/文件归一键。

隔离：CONFIG_FILE 重定向临时文件（不碰用户真 config.json）；不装 agents
（不触真实 ~/.claude/agents）。直接 `python tests/test_roles_routing.py` 运行。
"""
import json
import os
import sys
import tempfile

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
check("strong 词含决策者", "决策者" in gs)
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

print()
print("=" * 56)
print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
if _FAIL:
    print("失败项：", "、".join(_FAIL))
    sys.exit(1)
print("全部通过")
