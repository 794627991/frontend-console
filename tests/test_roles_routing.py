# -*- coding: utf-8 -*-
"""最小自测：角色重规划（v2.51）——双形态主会话直干 + designer/reviewer。

覆盖八块：
1. 引导词：light=直干所有活+分级（免审/轻审/全审线数字嵌词）+designer
   派发纪律（带全上下文五要素）+reviewer 只审不改；strong=直干+reviewer
   审计兜底；两词均无版本代号、无 dev/executor/coder 派发词、无 L 档位
   代号；开关关 → 空串；audit_mode 切换威慑句。
2. 形态判定：默认「除 Opus 皆轻」（含 opus→strong、glm/flash 等其余→
   light、无名→strong）；main_model 显式配置优先；配置往返。
3. 模型池：model_map 端点映射（executor/coder 旧键与 light/heavy 新键
   两读法）、显式两池 light_model/heavy_model、旧键降级
   （executor_model/coder_model）、方案表自动分类（opus→重池）、行式
   映射解析（Flask test client）。
4. agent md：light 装 designer+reviewer、strong 只 reviewer、designer 在
   strong 下共存不删；executor/coder/dev 退役清理；strong↔light 往返
   幂等；designer body「只设计绝不干活」、reviewer body 只读强化；tools：
   designer 全集除 Task、reviewer 原样（含 Task 无编辑）；两
   body 与两 md 无版本代号；ensure_roles_ready 分形态清单。
5. 审计判定：audit_verdict（免审区干净/超免审未轻审/超轻审属大改须全审
   /已派不追责/strong 超审计线未派审/designer 派发不计；v2.52 只看单次
   直改行数——文件数与回合累计退役）；0 合法最严档。
6. 事中闸：audit_gate_check 达线拦（单次行数、>= 口径）+ 指路送审
   （不提 dev）+ 已派 reviewer 开闸 + 线内放行。
7. 指纹热更：改分级线/切形态 → 引导词与 _bridge_fp 变；口径基础件
   （MultiEdit 求和）；clamp 五态。
8. 派发识别：_audit_dispatch_role（designer/reviewer 三形态；dev 已退役
   不计）+ _audit_tally/_audit_tally_result 集成（记旗/pending/映射回填/
   子代理事件不计）+ POST /roles 端到端（两池落盘 + clamp 回显 + GET
   resolved）。

隔离：CONFIG_FILE 重定向临时文件（不碰用户真 config.json）；
HARNESS_AGENTS_DIR 重定向临时目录（不触真实 ~/.claude/agents）。直接
`py tests/test_roles_routing.py` 运行。
"""
import json
import os
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

LIGHT_MODEL = "glm-5.3-flash"       # 非 opus → light
HEAVY_MODEL = "claude-opus-4-5"     # 含 opus → strong
# 池内显式值（写进配置让 resolve 走确定路径，不受真机 settings 影响）
POOL_LIGHT = "glm-5.3-flash"
POOL_HEAVY = "glm-5.3"

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
check("两池新键默认空（自动识别）",
      d.get("light_model") == "" and d.get("heavy_model") == "")
check("分级线默认 100/3/200", hr.audit_limits() == (100, 3, 200),
      str(hr.audit_limits()))
check("旧键 max_free_lines 已不在 defaults", "max_free_lines" not in d)
write_cfg(enabled=True, executor_model="old-ex", coder_model="old-co",
          legacy_junk=1)
d2 = hr.roles_cfg()
check("roles_cfg 透传未知键/旧键（降级依赖）",
      d2.get("executor_model") == "old-ex" and d2.get("legacy_junk") == 1)
write_cfg(enabled=True)

# ============ 2. 形态判定：除 Opus 皆轻 ============
print("[2] 形态判定（废轻快词规则）")
M = hr.roles_mode
check("glm-5.3-flash → light（非 opus 皆轻）", M(LIGHT_MODEL) == "light")
check("glm-5.3 → light（旧规则会判 strong，新规则轻）", M("glm-5.3") == "light")
check("Lanz-Max → light（非 opus）", M("Lanz-Max") == "light")
check("claude-opus-4-5 → strong", M(HEAVY_MODEL) == "strong")
check("OPUS 大写不分大小写 → strong", M("GLM-Opus-Pro") == "strong")
check("无名 → strong（兜底直干）", M(None) == "strong" and M("") == "strong")
check("旧轻快词不再单独判轻之外的角色（turbo 非 opus=轻）",
      M("gpt-4-turbo") == "light")
write_cfg(enabled=True, main_model=HEAVY_MODEL)
check("main_model 显式优先：实跑 flash 判 strong", M(LIGHT_MODEL) == "strong")
write_cfg(enabled=True, main_model=LIGHT_MODEL)
check("main_model=flash：实跑 opus 判 light", M(HEAVY_MODEL) == "light")
hr.update_roles_cfg({"main_model": ""})
check("清空回落名字自动识别",
      M(LIGHT_MODEL) == "light" and M(HEAVY_MODEL) == "strong")

# ============ 3. 模型池解析 ============
print("[3] 模型池（轻/重两池）")
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
check("显式两池优先", hr.resolve_role_models() == (POOL_LIGHT, POOL_HEAVY),
      str(hr.resolve_role_models()))
write_cfg(enabled=True, executor_model="old-ex", coder_model="old-co")
check("旧键降级：executor→轻池 coder→重池",
      hr.resolve_role_models() == ("old-ex", "old-co"))
write_cfg(enabled=True, executor_model="old-ex", coder_model="old-co",
          light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
check("新旧键并存新键优先", hr.resolve_role_models() == (POOL_LIGHT, POOL_HEAVY))
write_cfg(enabled=True, executor_model="old-ex")
li, hv = hr.resolve_role_models(
    models=["glm-5.3", "claude-opus-4-5"], default=None)
check("只配旧轻键：重池走方案表自动分类",
      li == "old-ex" and hv == "claude-opus-4-5", str((li, hv)))
write_cfg(enabled=True)
li, hv = hr.resolve_role_models(
    models=["glm-5.3-flash", "claude-opus-4-5"], default="glm-5.3-flash")
check("方案表自动分类：opus→重池 其余→轻池",
      li == "glm-5.3-flash" and hv == "claude-opus-4-5")
li, hv = hr.resolve_role_models(models=["glm-5.3-flash", "glm-5.3"],
                                default="glm-5.3")
check("方案表无 opus：重池回退 default（用户主模型最强）",
      li == "glm-5.3-flash" and hv == "glm-5.3")

# ---- v2.53 设计者/审计者独立槽（resolve_agent_models）----
print("[3b] 设计者/审计者模型解析")
write_cfg(enabled=True, heavy_model=POOL_HEAVY)
check("两槽全空 → 共用重池（历史行为）",
      hr.resolve_agent_models() == (POOL_HEAVY, POOL_HEAVY))
write_cfg(enabled=True, heavy_model=POOL_HEAVY,
          designer_model="dm-x", reviewer_model="rm-x")
check("显式两槽优先（各走各的）",
      hr.resolve_agent_models() == ("dm-x", "rm-x"))
write_cfg(enabled=True, heavy_model=POOL_HEAVY, designer_model="dm-x")
check("只配设计者 → 审计者回退重池（互不牵连）",
      hr.resolve_agent_models() == ("dm-x", POOL_HEAVY))
# [1M] 用例走「池配置空→方案表自动分类」路径——不预写池配置（write_cfg
# 是全量重写，上一用例的池配置不会残留）
write_cfg(enabled=True)
li, hv = hr.resolve_role_models(
    models=["Opus-X[1M]", "flash-a"], default="Opus-X[1M]")
check("[1M] 窗口后缀剥离", li == "flash-a" and hv == "Opus-X")
write_cfg(enabled=True, model_map={
    "open.bigmodel.cn": {"executor": "m-ex", "coder": "m-co"}})
check("model_map 旧键名（executor/coder）照收",
      hr.resolve_role_models(base_url="https://open.bigmodel.cn/v1")
      == ("m-ex", "m-co"))
write_cfg(enabled=True, model_map={
    "open.bigmodel.cn": {"light": "m-li", "heavy": "m-hv"}})
check("model_map 新键名（light/heavy）亦可",
      hr.resolve_role_models(base_url="https://open.bigmodel.cn/v1")
      == ("m-li", "m-hv"))
write_cfg(enabled=True)
check("方案表为空兜硬默认",
      hr.resolve_role_models(models=[], default=None)
      == ("glm-5.3-flash", "glm-5.3"))

# ============ 4. light 引导词 ============
print("[4] light 引导词（直干+双代理）")
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
g = hr.roles_bridge_text(LIGHT_MODEL)
for kw, label in [
        ("直干所有活", "主会话直干"),
        ("免审", "免审字样"), ("轻审", "轻审字样"), ("全审", "全审字样"),
        ("designer", "设计者代理"), ("reviewer", "审核者代理"),
        ("只设计不干活", "designer 只设计"),
        ("已试方案", "派发纪律带已试方案"),
        ("验收标准", "上下文含验收标准"),
        ("文件+行号", "上下文含文件行号"),
        ("cmdlib.json", "高风险铁律文件"),
        ("PASS/FAIL", "审核结论二选一"),
        ("≤100 行", "免审线数字嵌词"),
        ("≤200 行", "轻审线行数嵌词"),
        ("单次直改", "单次口径嵌词"),
        (POOL_HEAVY, "重池模型名嵌词"),
        ("回合终点纪律", "终点纪律保留"),
        ("审计", "审计威慑保留")]:
    check(label, kw in g, "缺「%s」" % kw)
check("无版本代号", "v2." not in g and "v2．" not in g)
check("无旧角色/档位词",
      all(w not in g for w in ("派 dev", "派 executor", "派 coder",
                               "L0", "L1", "L2", "L3", "L4", "决策者")),
      "")
g_off = (write_cfg(enabled=True, light_model=POOL_LIGHT,
                   heavy_model=POOL_HEAVY, audit_mode="off"),
         hr.roles_bridge_text(LIGHT_MODEL))[1]
check("audit_mode=off 威慑句切换",
      "重大流程违规" in g_off and "会审计" not in g_off)

# ============ 5. strong 引导词 ============
print("[5] strong 引导词（直干+审核兜底）")
gs = hr.roles_bridge_text(HEAVY_MODEL)
check("strong 词=干活者直干", "干活者" in gs and "亲自完成" in gs)
check("strong 词无派活分工词",
      all(w not in gs for w in ("决策者", "executor", "coder", "路由", "dev")))
check("strong 词无免审/档位词",
      all(w not in gs for w in ("免审", "L1", "L2", "L3", "L4")))
check("strong 词无 designer（不用设计代理）", "designer" not in gs)
check("strong 词含 reviewer 审计兜底与线数字",
      "审计线" in gs and "reviewer" in gs and "单次直改" in gs
      and "≤200 行" in gs)
check("strong 词无版本代号", "v2." not in gs)
check("light/strong 词不同", g != gs)
write_cfg(enabled=False)
check("开关关 → 空串", hr.roles_bridge_text(LIGHT_MODEL) == "")
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)

# ============ 6. 指纹热更 ============
print("[6] 指纹热更")
from src.claude_harness import _bridge_fp, _audit_lines
fp1 = _bridge_fp(LIGHT_MODEL)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY,
          l2_max_lines=150)
g2 = hr.roles_bridge_text(LIGHT_MODEL)
fp2 = _bridge_fp(LIGHT_MODEL)
check("改分级线 → 引导词变", g2 != g and "≤150 行" in g2)
check("改分级线 → 指纹变（热更触发）", fp1 != fp2)
check("切模型 → 指纹变（换形态）", _bridge_fp(HEAVY_MODEL) != fp2)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
check("复原配置 → 指纹复原", _bridge_fp(LIGHT_MODEL) == fp1)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model="opus-x")
check("改重池 → 指纹变（池名嵌词）", _bridge_fp(LIGHT_MODEL) != fp1)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)

# ============ 7. 审计判定（audit_verdict） ============
print("[7] audit_verdict")
V = hr.audit_verdict
check("免审区（50 行）干净", V(50, False) == [])
check("免审线边界（100 行）干净", V(100, False) == [])
v = V(150, False)
check("超免审未轻审 → 违规指明轻审", len(v) == 1 and "轻审" in v[0], str(v))
check("超免审已轻审 → 干净", V(150, True) == [])
v = V(250, False)
check("超轻审线 → 大改须全审（不提 dev）",
      len(v) == 1 and "全审" in v[0] and "dev" not in v[0], str(v))
check("多文件小行数 → 不追责（文件数口径退役）", V(50, False) == [])
check("超线但已派审 → 不追责（提示性兜底）", V(250, True) == [])
check("designer 派发不豁免（不算已审）",
      len(V(250, False, cfg={"l1_max_lines": 100, "l2_max_lines": 200})) == 1)
print("[7b] 0 合法最严档")
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY,
          l1_max_lines=0, l2_max_lines=0)
v01 = V(1, False)
check("全 0 线：1 行直改即属大改须全审", len(v01) == 1 and "全审" in v01[0])
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
print("[7c] strong 分支")
VS = hr.audit_verdict
vs = VS(250, False, strong=True)
check("strong 超线未派审 → 违规指明审计线与 reviewer",
      len(vs) == 1 and "审计线" in vs[0] and "reviewer" in vs[0], str(vs))
check("strong 线内干净（直干是常态）",
      VS(150, False, strong=True) == [] and VS(100, False, strong=True) == [])
check("strong 已派 reviewer 视作审过", VS(250, True, strong=True) == [])
fp_s1 = _bridge_fp(HEAVY_MODEL)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY,
          l2_max_lines=150)
check("strong 改审计线 → 词变+指纹变（热更）",
      "≤150 行" in hr.roles_bridge_text(HEAVY_MODEL)
      and _bridge_fp(HEAVY_MODEL) != fp_s1)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)

# ============ 8. 事中闸（审过开闸） ============
print("[8] audit_gate_check")
G = hr.audit_gate_check
check("轻审线内（150 行）放行", G(150) == (False, None))
check("轻审线内（100 行）放行", G(100) == (False, None))
b, m = G(200)
check("行数达线 → 拦（>= 口径）", b and "reviewer" in m, m or "")
b, m = G(250)
check("拦下文案指路送审不提 dev",
      b and "派 dev" not in m and "designer" in m, m or "")
check("已派 reviewer → 开闸（直干不停工）",
      G(250, reviewed=True) == (False, None))
check("未达线时 reviewed 不影响放行", G(10, reviewed=False) == (False, None))
check("免审/小改不拦（旧 3 行微调口径废除沿用）",
      G(3) == (False, None) and G(99) == (False, None))

# ============ 9. 口径基础件 ============
print("[9] 口径基础件")
n = _audit_lines("MultiEdit", {"edits": [
    {"old_string": "a\nb\nc", "new_string": "x"},
    {"old_string": "y", "new_string": "p\nq"}]})
check("MultiEdit 按块求和 max(old,new)", n == 5, str(n))
check("Edit 口径 max(old,new)=3",
      _audit_lines("Edit", {"old_string": "a\nb\nc", "new_string": "x"}) == 3)

# ============ 10. 配置往返（update_roles_cfg merge） ============
print("[10] 配置往返")
ok, err = hr.update_roles_cfg({"l1_max_lines": 5, "l2_max_files": 1,
                               "l2_max_lines": 9})
check("merge 写盘 ok", ok, str(err))
check("写后线值生效", hr.audit_limits() == (5, 1, 9), str(hr.audit_limits()))
check("线值进引导词", "≤5 行" in hr.roles_bridge_text(LIGHT_MODEL))
ok, err = hr.update_roles_cfg({"light_model": "p-light", "heavy_model": "p-hv"})
check("两池配置往返", hr.roles_cfg().get("light_model") == "p-light"
      and hr.roles_cfg().get("heavy_model") == "p-hv")
ok, err = hr.update_roles_cfg({"main_model": LIGHT_MODEL})
check("main_model 往返 merge 保留",
      hr.roles_cfg().get("main_model") == LIGHT_MODEL
      and hr.roles_cfg().get("light_model") == "p-light")
hr.update_roles_cfg({"main_model": ""})
hr.update_roles_cfg({"l1_max_lines": 100, "l2_max_files": 3, "l2_max_lines": 200,
                     "light_model": POOL_LIGHT, "heavy_model": POOL_HEAVY})

# ============ 11. clamp：l1_max_lines ≤ l2_max_lines ============
print("[11] clamp")
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

# ============ 12. agent md：安装/退役/幂等 ============
print("[12] agent md（临时目录安装）")


def _tools_line(md):
    m = __import__("re").search(r"^tools: (.+)$", md, __import__("re").M)
    return m.group(1).strip() if m else ""


ad = hr._agents_dir()
for fn in ("executor.md", "coder.md", "designer.md", "dev.md", "reviewer.md"):
    p = os.path.join(ad, fn)
    if os.path.exists(p):
        os.remove(p)
# 预置旧版五角色套装 → 验证退役清理 + designer 存活
for fn in ("executor.md", "coder.md", "designer.md", "dev.md", "reviewer.md"):
    with open(os.path.join(ad, fn), "w", encoding="utf-8") as f:
        f.write("---\nname: %s\n---\nold" % fn[:-3])
hr.install_roles_agents(HEAVY_MODEL)     # strong
check("strong 清退役三角色",
      not any(os.path.exists(os.path.join(ad, fn)) for fn in
              ("executor.md", "coder.md", "dev.md")))
check("strong 只装 reviewer", os.path.isfile(os.path.join(ad, "reviewer.md")))
check("strong 下 designer.md 共存不删（light 在用文件）",
      os.path.isfile(os.path.join(ad, "designer.md")))
with open(os.path.join(ad, "designer.md"), encoding="utf-8") as f:
    dmd_old = f.read()
check("strong 不动 designer 内容（仍是旧装）", dmd_old == "---\nname: designer\n---\nold")
check("strong ensure_roles_ready 只查 reviewer",
      hr.ensure_roles_ready(HEAVY_MODEL) == [])
hr.install_roles_agents(LIGHT_MODEL)     # light
check("light 装 designer+reviewer",
      os.path.isfile(os.path.join(ad, "designer.md"))
      and os.path.isfile(os.path.join(ad, "reviewer.md")))
with open(os.path.join(ad, "designer.md"), encoding="utf-8") as f:
    dmd = f.read()
with open(os.path.join(ad, "reviewer.md"), encoding="utf-8") as f:
    rmd = f.read()
check("roundtrip 后 designer 内容已刷新（非旧装）", dmd != dmd_old)
check("designer md 取重池模型（槽空回退）",
      "model: %s" % POOL_HEAVY in dmd and "name: designer" in dmd)
check("reviewer md 取重池模型（槽空回退）", "model: %s" % POOL_HEAVY in rmd)
# v2.53：设计者/审计者显式槽 → 各自 md 取各自模型
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY,
          designer_model="dm-inst", reviewer_model="rm-inst")
hr.install_roles_agents(LIGHT_MODEL)
with open(os.path.join(ad, "designer.md"), encoding="utf-8") as f:
    dmd2 = f.read()
with open(os.path.join(ad, "reviewer.md"), encoding="utf-8") as f:
    rmd2 = f.read()
check("designer md 取设计者槽模型", "model: dm-inst" in dmd2, dmd2[:80])
check("reviewer md 取审计者槽模型", "model: rm-inst" in rmd2, rmd2[:80])
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
tl = _tools_line(dmd).split(", ")
check("designer tools 全集（有 Write/Edit/Bash）且无 Task（禁派子代理）",
      all(t in tl for t in ("Read", "Write", "Edit", "MultiEdit",
                            "NotebookEdit", "Bash", "Glob", "Grep",
                            "SendMessage"))
      and "Task" not in tl)
rtl = _tools_line(rmd).split(", ")
check("reviewer tools 无 Task（禁派子代理）且保留 Bash/SendMessage",
      "Task" not in rtl and "Bash" in rtl and "SendMessage" in rtl)
check("reviewer tools 只读（无编辑类）",
      not any(t in rtl for t in ("Edit", "Write", "MultiEdit", "NotebookEdit")))
check("designer body「只设计绝不干活」",
      "只设计" in hr._DESIGNER_BODY and "绝不干活" in hr._DESIGNER_BODY)
check("designer body 含禁派子代理与 git 纪律",
      "禁止派发子代理" in hr._DESIGNER_BODY
      and "git commit/push" in hr._DESIGNER_BODY)
check("reviewer body 只读强化（不允许修改代码/测试用例）",
      "不允许修改代码" in hr._REVIEWER_BODY and "测试用例" in hr._REVIEWER_BODY)
check("reviewer body 含禁派子代理与 git 纪律",
      "禁止派发子代理" in hr._REVIEWER_BODY
      and "git commit/push" in hr._REVIEWER_BODY)
check("两 body 无版本代号",
      "v2." not in hr._DESIGNER_BODY and "v2." not in hr._REVIEWER_BODY)
check("两 md 无版本代号",
      "v2." not in dmd and "v2." not in rmd)
check("死代码 body 已清理（三轻角色常量删除）",
      not hasattr(hr, "_EXECUTOR_BODY") and not hasattr(hr, "_CODER_BODY")
      and not hasattr(hr, "_DEV_BODY") and not hasattr(hr, "_TOOLS_FULL"))
os.remove(os.path.join(ad, "reviewer.md"))
os.remove(os.path.join(ad, "designer.md"))
check("light ensure_roles_ready 自愈两文件",
      sorted(hr.ensure_roles_ready(LIGHT_MODEL)) == ["designer.md", "reviewer.md"]
      and os.path.isfile(os.path.join(ad, "designer.md"))
      and os.path.isfile(os.path.join(ad, "reviewer.md")))
again = hr.ensure_roles_ready(LIGHT_MODEL)
check("自愈幂等（在位时空表）", again == [])
hr.install_roles_agents(LIGHT_MODEL)
before = {fn: open(os.path.join(ad, fn), "rb").read()
          for fn in ("designer.md", "reviewer.md")}
hr.install_roles_agents(LIGHT_MODEL)
check("light 重复安装幂等（内容不变不写）",
      {fn: open(os.path.join(ad, fn), "rb").read()
       for fn in ("designer.md", "reviewer.md")} == before)
hr.install_roles_agents(HEAVY_MODEL)
check("strong 往返：designer 存活 + reviewer 在位",
      os.path.isfile(os.path.join(ad, "designer.md"))
      and os.path.isfile(os.path.join(ad, "reviewer.md")))
hr.update_roles_cfg({"enabled": False})
check("开关关 → 五文件全清",
      not any(os.path.exists(os.path.join(ad, fn)) for fn in
              ("executor.md", "coder.md", "designer.md", "dev.md",
               "reviewer.md")))
hr.update_roles_cfg({"enabled": True})

# ============ 13. 派发/续派识别 ============
print("[13] 派发/续派识别")
from src.claude_harness import _audit_dispatch_role as D
check("Task 按名计 designer", D("Task", {"subagent_type": "designer"}) == "designer")
check("Agent 按名计 reviewer", D("Agent", {"subagent_type": "reviewer"}) == "reviewer")
check("Task dev 已退役不计", D("Task", {"subagent_type": "dev"}) is None)
check("Task 其他代理不计", D("Task", {"subagent_type": "Explore"}) is None)
check("SendMessage 裸名续派计 designer",
      D("SendMessage", {"to": "designer"}) == "designer")
check("SendMessage 带 [ref] 计 reviewer",
      D("SendMessage", {"to": "reviewer [3fa9c1]"}) == "reviewer")
check("SendMessage 裸 agentId 查映射",
      D("SendMessage", {"to": "a1b2c3d4-9f0e"}, {"a1b2c3d4-9f0e": "designer"}) == "designer")
check("worker 无名形态 → None（缺口如实，见 docstring）",
      D("SendMessage", {"to": "worker [3fa9c1]"}) is None)
check("发 main 不计", D("SendMessage", {"to": "main"}) is None)
check("无关工具不计", D("Edit", {"file_path": "x"}) is None)

# _audit_tally 集成：SendMessage 续派 + Task 记 pending + result 回填映射
from src.claude_harness import HarnessSession as _HS
_fake = types.SimpleNamespace(_audit={"lines": 0, "files": [],
                                      "designer": False, "reviewer": False,
                                      "streak": 0, "ids": {}, "pending": {}})


def _ev(blocks, parent=None):
    o = {"message": {"content": blocks}}
    if parent:
        o["parent_tool_use_id"] = parent
    return o


_HS._audit_tally(_fake, _ev([
    {"type": "tool_use", "id": "tu1", "name": "Task",
     "input": {"subagent_type": "designer", "prompt": "x"}}]))
check("tally：Task designer 记旗+pending", _fake._audit["designer"]
      and "tu1" in _fake._audit["pending"])
_HS._audit_tally(_fake, _ev([
    {"type": "tool_use", "id": "tu2", "name": "SendMessage",
     "input": {"to": "reviewer [abc]", "message": "审"}}]))
check("tally：SendMessage 名字续派计 reviewer 旗", _fake._audit["reviewer"])
_HS._audit_tally_result(_fake, _ev([
    {"type": "tool_result", "tool_use_id": "tu1",
     "content": [{"type": "text",
                  "text": '{"agentId": "a11b22c33-d44e", "ok": true}'}]}]))
check("result 回填 agentId→designer 映射",
      _fake._audit["ids"].get("a11b22c33-d44e") == "designer"
      and not _fake._audit["pending"])
_HS._audit_tally(_fake, _ev([
    {"type": "tool_use", "id": "tu3", "name": "SendMessage",
     "input": {"to": "a11b22c33-d44e", "message": "再续"}}]))
check("tally：裸 agentId 续派经映射再计 designer 旗", _fake._audit["designer"])
_sub = _ev([{"type": "tool_use", "id": "tu9", "name": "Task",
             "input": {"subagent_type": "reviewer"}}], parent="p1")
_fake._audit["reviewer"] = False      # 复位后再验：子代理事件不得重置旗
_HS._audit_tally(_fake, _sub)
check("子代理事件（parent_tool_use_id）不计", not _fake._audit["reviewer"])

# ============ 14. POST/GET /roles 端到端（Flask test client） ============
print("[14] /roles 端点")
try:
    from flask import Flask
    import src.claude_harness as _ch
    _app = Flask(__name__)
    _app.register_blueprint(_ch.harness_bp)
    _c = _app.test_client()
    _r0 = _c.post("/api/harness/roles", json={"light_model": "e-light",
                                  "heavy_model": "e-heavy",
                                  "l1_max_lines": 300,
                                  "l2_max_lines": 200})
    jr = _r0.get_json(silent=True)
    if jr is None:
        print("    [debug] status=%s body=%r" % (_r0.status_code,
                                                 _r0.data[:300]))
    check("POST 两池落盘", jr.get("ok") and jr.get("light_model") == "e-light"
          and jr.get("heavy_model") == "e-heavy", str(jr))
    check("POST clamp 回显（l1 钳到 200）",
          jr.get("clamped") and jr["clamped"][0]["to"] == 200, str(jr))
    gr = _c.get("/api/harness/roles").get_json()
    rs = gr.get("resolved") or {}
    check("GET resolved 出两池", rs.get("light") == "e-light"
          and rs.get("heavy") == "e-heavy", str(rs))
    check("GET roles 含分级线与 audit_mode",
          gr["roles"].get("l1_max_lines") == 200
          and gr["roles"].get("l2_max_lines") == 200
          and gr["roles"].get("audit_mode") == "auto")
    jr2 = _c.post("/api/harness/roles", json={
        "model_map": ["open.bigmodel.cn=mm-li,mm-hv"]}).get_json()
    check("POST 行式 model_map 解析",
          jr2.get("model_map", {}).get("open.bigmodel.cn")
          == {"executor": "mm-li", "coder": "mm-hv"}, str(jr2))
    check("model_map 端点命中覆盖显式池",
          hr.resolve_role_models(base_url="https://open.bigmodel.cn/x")
          == ("mm-li", "mm-hv"))
    jr3 = _c.post("/api/harness/roles", json={"audit_mode": "bogus"})
    check("audit_mode 非法 → 400", jr3.status_code == 400)
    jr4 = _c.post("/api/harness/roles", json={"executor_model": "old-keep"})
    check("旧键仍被接受落盘（兼容）",
          jr4.get_json().get("executor_model") == "old-keep")
    # v2.53：设计者/审计者槽新键端到端（POST 落盘 + resolved 回显）——
    # 白名单漏键会在此现形（面板保存假成功 bug 的回归测试）
    jr5 = _c.post("/api/harness/roles", json={"designer_model": "e-dm",
                                              "reviewer_model": "e-rm"})
    jr5 = jr5.get_json(silent=True) or {}
    check("POST 设计者/审计者槽落盘",
          jr5.get("ok") and jr5.get("designer_model") == "e-dm"
          and jr5.get("reviewer_model") == "e-rm", str(jr5))
    gr2 = _c.get("/api/harness/roles").get_json()
    rs2 = gr2.get("resolved") or {}
    check("GET resolved 回显设计者/审计者模型",
          rs2.get("designer") == "e-dm" and rs2.get("reviewer") == "e-rm",
          str(rs2))
except ImportError as e:
    check("Flask 不可用，跳过端点段（%s）" % e, True)

print()
print("=" * 56)
print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
if _FAIL:
    print("失败项：", "、".join(_FAIL))
    sys.exit(1)
print("全部通过")
