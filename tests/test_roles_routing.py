# -*- coding: utf-8 -*-
"""最小自测：角色重规划（v2.51）——双形态主会话直干 + designer/reviewer。

覆盖八块：
1. 引导词：light=直干所有活+分级（免审/轻审/全审线数字嵌词）+designer
   派发纪律（带全上下文五要素）+reviewer 只审不改；strong=直干+reviewer
   审计兜底；两词均无版本代号、无 dev/executor/coder 派发词、无 L 档位
   代号；开关关 → 空串；audit_mode 切换威慑句。
2. 形态判定（v3.5.0 三档精确匹配）：实跑模型归一化命中 轻/中/重 三档
   配置值（同值 重>中>轻）；mid 未配时重档值命中按中档（D2：重档须显式
   opt-in）；未匹配/无名 → mid 兜底；main_model/light_keywords 退役残留
   不参与判定；tier 解析三档齐/缺省。
3. 模型池：v3.5.15 起 model_map 不再参与档位（键归识图 /vision 端点），
   断言「不覆盖」；显式两池 light_model/heavy_model、旧键降级
   （executor_model/coder_model）、方案表自动分类、[1M] 剥离。
4. agent md：light/heavy 双装 designer+reviewer（v3.5.16 重档派发自由）、
   mid 只 reviewer（designer 共存）、退役清理、roundtrip 幂等；
   designer body「只设计绝不干活」、reviewer body 只读强化；tools：
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
# v3.5.19：三档联动 API 配置三槽——mock settings.json 重定向（不碰真机）
_TIER_SETTINGS = os.path.join(_TMP, "settings.json")
os.environ["HARNESS_TIER_SETTINGS"] = _TIER_SETTINGS


def write_tiers(haiku="", sonnet="", opus=""):
    """写三槽映射（模拟 API 配置方案的 env 槽位）。"""
    import json as _j
    with open(_TIER_SETTINGS, "w", encoding="utf-8") as f:
        _j.dump({"env": {
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": haiku,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": sonnet,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": opus}}, f)


import src.harness.roles as hr

LIGHT_MODEL = "glm-5.3-flash"       # 轻档显式值
HEAVY_MODEL = "glm-5.3"             # 重档显式值
MID_MODEL = "glm-4.7"               # 中档显式值（v3.5.0 三档）
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
check("三档显式键在 defaults 且默认空（v3.5.19R：空=三槽默认）",
      d.get("light_model") == "" and d.get("mid_model") == ""
      and d.get("heavy_model") == "")
check("分级线默认 100/3/200", hr.audit_limits() == (100, 3, 200),
      str(hr.audit_limits()))
check("旧键 max_free_lines 已不在 defaults", "max_free_lines" not in d)
write_cfg(enabled=True, executor_model="old-ex", coder_model="old-co",
          legacy_junk=1)
d2 = hr.roles_cfg()
check("roles_cfg 透传未知键/旧键（降级依赖）",
      d2.get("executor_model") == "old-ex" and d2.get("legacy_junk") == 1)
write_cfg(enabled=True)

# ============ 2. 形态判定：三档联动 API 配置三槽（v3.5.19） ============
print("[2] 形态判定（三槽联动：Haiku→轻 / Sonnet→中 / Opus→重）")
M = hr.roles_mode
write_tiers(haiku=LIGHT_MODEL, sonnet=MID_MODEL, opus=HEAVY_MODEL)
check("Haiku 槽值命中 → light", M(LIGHT_MODEL) == "light")
check("槽值带 [1M] 后缀归一化命中", M(LIGHT_MODEL + "[1M]") == "light")
check("Sonnet 槽值命中 → mid", M(MID_MODEL) == "mid")
check("Opus 槽值命中 → heavy（最信任档）", M(HEAVY_MODEL) == "heavy")
check("槽值大小写不敏感", M(HEAVY_MODEL.upper()) == "heavy")
check("未匹配三槽 → mid（安全兜底：多一道审）", M("unknown-model-x") == "mid")
check("无名 → mid", M(None) == "mid" and M("") == "mid")
# 同值多槽：a127 用户拍板改为 重>中>轻
write_tiers(haiku="same-x", sonnet="same-x", opus="same-x")
check("同值多槽优先级 重>中>轻（取重）", M("same-x") == "heavy")
write_tiers(sonnet=HEAVY_MODEL, opus=HEAVY_MODEL)
check("Sonnet==Opus 同值：命中取重档", M(HEAVY_MODEL) == "heavy")
write_tiers(haiku="same-y", sonnet="same-y", opus=HEAVY_MODEL)
check("轻==中 同值（重不同）：命中取中档", M("same-y") == "mid")
# v3.5.19R：显式配置优先于三槽默认（用户纠偏「三槽只是默认，也可随便改」）
write_tiers(haiku=LIGHT_MODEL, sonnet=MID_MODEL, opus=HEAVY_MODEL)
write_cfg(enabled=True, light_model=HEAVY_MODEL, heavy_model=LIGHT_MODEL)
check("显式档位覆盖三槽默认（轻=显式 heavy 值）",
      M(HEAVY_MODEL) == "light" and M(LIGHT_MODEL) == "heavy")
write_cfg(enabled=True, main_model=HEAVY_MODEL, light_keywords="flash")
check("退役键 main_model/light_keywords 残留不参与判定",
      M(LIGHT_MODEL) == "light" and M(MID_MODEL) == "mid")
# tier 解析：空配置=三槽直读（[1M] 剥离）；显式覆盖优先
write_cfg(enabled=True)
write_tiers(haiku="glm-5.3-flash[1M]", sonnet="glm-4.7", opus="glm-5.3[1M]")
_l, _m, _h = hr.resolve_tier_models()
check("tier 解析：空配置=三槽默认（剥 [1M]）",
      (_l, _m, _h) == (LIGHT_MODEL, MID_MODEL, HEAVY_MODEL), str((_l, _m, _h)))
write_cfg(enabled=True, light_model="my-l", mid_model="my-m", heavy_model="my-h")
check("tier 解析：显式三键覆盖三槽",
      hr.resolve_tier_models() == ("my-l", "my-m", "my-h"),
      str(hr.resolve_tier_models()))
write_tiers()   # 全槽缺失 → 回退方案表自动分类
write_cfg(enabled=True)
_l, _m, _h = hr.resolve_tier_models(
    models=["glm-5.3-flash", MID_MODEL, "glm-5.3"], default="glm-5.3")
check("tier 解析：缺槽回退方案表（轻词池/重池，mid=重池兜）",
      _l == "glm-5.3-flash" and _h == "glm-5.3" and _m == "glm-5.3",
      str((_l, _m, _h)))
write_tiers(haiku=LIGHT_MODEL, sonnet=MID_MODEL, opus=HEAVY_MODEL)   # 复原三槽（后续段依赖）

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
check("只配旧轻键：重池走方案表自动分类（非轻词池取首个）",
      li == "old-ex" and hv == "glm-5.3", str((li, hv)))
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
# v3.5.15：model_map 端点映射从三角色判定链退役——旧/新键名两种写法都
# 不再覆盖档位（键归识图专用，POST 解析保留见 [14]）；v3.5.18 撤
# base_url 形参（无消费者），直接调即可
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY,
          model_map={"open.bigmodel.cn": {"executor": "m-ex", "coder": "m-co"}})
check("model_map 不再覆盖三角色档位（v3.5.15 退役·旧键名）",
      hr.resolve_role_models() == (POOL_LIGHT, POOL_HEAVY))
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY,
          model_map={"open.bigmodel.cn": {"light": "m-li", "heavy": "m-hv"}})
check("model_map 不再覆盖三角色档位（v3.5.15 退役·新键名）",
      hr.resolve_role_models() == (POOL_LIGHT, POOL_HEAVY))
write_cfg(enabled=True)
check("方案表为空兜硬默认",
      hr.resolve_role_models(models=[], default=None)
      == ("glm-5.3-flash", "glm-5.3"))

# ============ 4. light 引导词 ============
print("[4] light 引导词（直干+双代理）")
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
g = hr.roles_bridge_text(LIGHT_MODEL)
for kw, label in [
        ("任务分级", "任务分级头"),
        ("派发完全自由", "通用子代理派发自由（v3.5.17）"),
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

# ============ 5. mid 引导词（=旧 strong：直干+审核兜底） ============
print("[5] mid 引导词（直干+审核兜底）")
# v3.5.12 两档简化：HEAVY_MODEL 无 mid 配置=heavy 全免词——mid 词需三档配置
write_cfg(enabled=True, light_model=LIGHT_MODEL, mid_model=MID_MODEL,
          heavy_model=HEAVY_MODEL)
gs = hr.roles_bridge_text(MID_MODEL)
check("mid 词无版本代号", "v2." not in gs)
check("light/mid 词不同", g != gs)
write_cfg(enabled=False)
check("开关关 → 空串", hr.roles_bridge_text(LIGHT_MODEL) == "")
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)

# ============ 5b. heavy 引导词（v3.5.16 纠偏：直干+派发自由） ============
print("[5b] heavy 引导词（直干+派发自由）")
write_cfg(enabled=True, light_model=POOL_LIGHT, mid_model=MID_MODEL,
          heavy_model=POOL_HEAVY)
gh = hr.roles_bridge_text(POOL_HEAVY)
check("heavy 词=最信任档直干", "最信任档" in gh and "亲自完成" in gh)
check("heavy 词派发自由（designer/reviewer 按需可派，v3.5.16）",
      "子代理按需自由使用" in gh and "designer" in gh and "reviewer" in gh)
check("heavy 词无强制分级线数字（审计全免，词与机制同源）",
      all(w not in gh for w in ("审计线", "免审线", "轻审线", "≤")))
check("heavy 词含回合终点纪律（信任档也要交付纪律）",
      "回合终点纪律" in gh and "结论汇总" in gh)
check("mid/heavy 词不同", gh != gs)
check("三形态词互不相同", len({g, gs, gh}) == 3)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)

# ============ 6. 指纹热更 ============
print("[6] 指纹热更")
from src.harness.bridges import _bridge_fp
from src.harness.audit import _audit_lines
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
write_cfg(enabled=True)   # 清显式档位（三槽生效）
write_tiers(haiku=LIGHT_MODEL, sonnet=MID_MODEL, opus="opus-x")
check("改 Opus 槽 → 指纹变（重档值经代理模型嵌词）", _bridge_fp(LIGHT_MODEL) != fp1)
write_tiers(haiku=LIGHT_MODEL, sonnet=MID_MODEL, opus=HEAVY_MODEL)

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
print("[7d] 设计线（v2.54 强制设计档）")
check("达设计线未派 designer → 违规指明方案先行",
      any("设计线" in v and "designer" in v for v in V(200, False, designed=False)),
      str(V(200, False, designed=False)))
check("达设计线已派 designer → 无设计违规",
      not any("设计线" in v for v in V(200, False, designed=True)))
check("未达设计线不触发（150<200）",
      not any("设计线" in v for v in V(150, False, designed=False)))
check("design_max_lines=0 → 不强制设计",
      not any("设计线" in v for v in V(500, False, designed=False,
              cfg={"l1_max_lines": 100, "l2_max_lines": 200,
                   "design_max_lines": 0})))
check("strong 不查设计档（不装 designer）",
      not any("设计线" in v for v in hr.audit_verdict(
          500, False, designed=False, strong=True)))
g_off_dl = (write_cfg(enabled=True, light_model=POOL_LIGHT,
                      heavy_model=POOL_HEAVY, design_max_lines=0),
            hr.roles_bridge_text(LIGHT_MODEL))[1]
check("dl=0 引导词不宣称强制设计",
      "设计线（强制）" not in g_off_dl and "未启用" in g_off_dl)
g_on_dl = (write_cfg(enabled=True, light_model=POOL_LIGHT,
                     heavy_model=POOL_HEAVY, design_max_lines=300),
           hr.roles_bridge_text(LIGHT_MODEL))[1]
check("dl>0 引导词嵌设计线数字",
      "≥300 行" in g_on_dl and "设计线（强制）" in g_on_dl)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
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
# v3.5.12 两档简化：mid 词的审计线热更用三档配置验（HEAVY_MODEL 已是 heavy 全免词）
write_cfg(enabled=True, light_model=POOL_LIGHT, mid_model=MID_MODEL,
          heavy_model=POOL_HEAVY)
fp_s1 = _bridge_fp(MID_MODEL)
write_cfg(enabled=True, light_model=POOL_LIGHT, mid_model=MID_MODEL,
          heavy_model=POOL_HEAVY, l2_max_lines=150)
check("mid 改审计线 → 词变+指纹变（热更）",
      "≤150 行" in hr.roles_bridge_text(MID_MODEL)
      and _bridge_fp(MID_MODEL) != fp_s1)
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)

# ============ 8. 事中闸（审过开闸） ============
print("[8] 事中闸（v3.5.53：仅设计档一次性触发；审计档退役归结算）")
G = hr.audit_gate_check
check("设计线内（100 行）放行", G(100) == (False, None))
check("轻审线无设计线 → 不拦（审计档退役归结算）",
      G(200) == (False, None))
b, m = G(250, designed=False)
check("达设计线 → 拦（>= 口径）", b and "designer" in m, m or "")
b, m = G(350, designed=False)
check("拦下文案指路出方案不提 dev",
      b and "派 dev" not in m and "designer" in m, m or "")
check("已派 designer → 开闸",
      G(350, designed=True) == (False, None))
check("未达线时 designed 不影响放行", G(10, designed=False) == (False, None))
check("免审/小改不拦（旧 3 行微调口径废除沿用）",
      G(3) == (False, None) and G(99) == (False, None))
# v3.5.53：设计档一次性触发（design_fired）+ 审计档退役
check("design_fired=True → 不拦（本回合只咬一口）",
      G(250, design_fired=True) == (False, None))
check("审计档退役：仅超轻审线未达设计线 → 不拦",
      G(250, reviewed=False) == (False, None))
check("审计档退役：已派 reviewer 也不拦（同上）",
      G(300, reviewed=True) == (False, None))
print("[8b] 设计档事中闸（v2.54）")
b, m = G(200, designed=False)
check("达设计线未派 designer → 拦并指路出方案",
      b and "设计线" in m and "designer" in m, m or "")
check("已派 designer → 设计档不触发（v3.5.53 零强制零拦截）",
      G(200, designed=True) == (False, None),
      str(G(200, designed=True)))
b, m2 = G(200, designed=False, reviewed=True)
# v3.5.314 定稿口径（与 v3.5.313 结算同源）：审计链已建立（reviewer 在场）
# → 设计档豁免，回修/审计驱动迭代不再被拦。旧断言「两档独立、reviewer 不
# 豁免设计档」与实现及用户拍板冲突，属测试滞后（HEAD 上即失败）。
check("已派 reviewer → 设计档豁免（v3.5.314 与结算同口径）",
      (not b) and not m2, str((b, m2)))
check("设计线 0 → 设计档不拦（审计档独立仍在）",
      "设计线" not in (G(500, designed=False,
          cfg={"l1_max_lines": 100, "l2_max_lines": 200,
               "design_max_lines": 0})[1] or ""))

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
# v3.5.12 两档简化：HEAVY_MODEL（glm-5.3，mid 未配）= heavy 全删——
# 「只装 reviewer」的 mid 行为用三档配置 + MID_MODEL 验证
write_cfg(enabled=True, light_model=LIGHT_MODEL, mid_model=MID_MODEL,
          heavy_model=HEAVY_MODEL)
hr.install_roles_agents(MID_MODEL)       # mid（v4.0.4：reviewer + designer）
check("mid 清退役三角色",
      not any(os.path.exists(os.path.join(ad, fn)) for fn in
              ("executor.md", "coder.md", "dev.md")))
check("mid 装 reviewer", os.path.isfile(os.path.join(ad, "reviewer.md")))
check("mid 也装 designer（v4.0.4 事中闸指路，否则闸一开就死锁）",
      os.path.isfile(os.path.join(ad, "designer.md")))
with open(os.path.join(ad, "designer.md"), encoding="utf-8") as f:
    dmd_old = f.read()
check("mid 覆盖旧 designer 内容（不再共存保留）",
      dmd_old != "---\nname: designer\n---\nold")
check("mid ensure_roles_ready 不再报告缺失",
      hr.ensure_roles_ready(MID_MODEL) == [])
hr.install_roles_agents(LIGHT_MODEL)     # light
check("light 装 designer+reviewer",
      os.path.isfile(os.path.join(ad, "designer.md"))
      and os.path.isfile(os.path.join(ad, "reviewer.md")))
# v3.5.16 heavy：派发自由——与 light 同款双装（昔日定向删随禁派发语义退役）
write_cfg(enabled=True, light_model=POOL_LIGHT, mid_model=MID_MODEL,
          heavy_model=POOL_HEAVY)
hr.install_roles_agents(POOL_HEAVY)      # heavy（mid 配齐 → heavy 可达）
check("heavy 双装 designer+reviewer（派发自由，v3.5.16）",
      os.path.isfile(os.path.join(ad, "designer.md"))
      and os.path.isfile(os.path.join(ad, "reviewer.md")))
check("heavy ensure_roles_ready 查双文件", hr.ensure_roles_ready(POOL_HEAVY) == [])
hr.install_roles_agents(MID_MODEL)       # mid
check("mid 装 reviewer + designer（v4.0.4）",
      os.path.isfile(os.path.join(ad, "reviewer.md"))
      and os.path.isfile(os.path.join(ad, "designer.md")))
write_cfg(enabled=True, light_model=POOL_LIGHT, heavy_model=POOL_HEAVY)
hr.install_roles_agents(LIGHT_MODEL)     # 复原 light 双装（后续段依赖）
with open(os.path.join(ad, "designer.md"), encoding="utf-8") as f:
    dmd = f.read()
with open(os.path.join(ad, "reviewer.md"), encoding="utf-8") as f:
    rmd = f.read()
check("roundtrip 后 designer 内容已刷新（非手工旧装）",
      dmd != "---\nname: designer\n---\nold")
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
# v3.5.12：HEAVY_MODEL 两档制下=heavy（全删）——「reviewer 兜底在位」用 mid 验
write_cfg(enabled=True, light_model=POOL_LIGHT, mid_model=MID_MODEL,
          heavy_model=POOL_HEAVY)
hr.install_roles_agents(MID_MODEL)
check("mid 往返：designer 存活 + reviewer 在位",
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
from src.harness.audit import _audit_dispatch_role as D
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
from src.harness.session import HarnessSession as _HS
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
    check("POST 档位键落盘（v3.5.19R 显式配置回归）",
          jr.get("ok") and jr.get("light_model") == "e-light"
          and jr.get("heavy_model") == "e-heavy", str(jr))
    check("POST clamp 回显（l1 钳到 200）",
          jr.get("clamped") and jr["clamped"][0]["to"] == 200, str(jr))
    gr = _c.get("/api/harness/roles").get_json()
    rs = gr.get("resolved") or {}
    check("GET resolved 显式档位优先",
          rs.get("light") == "e-light" and rs.get("heavy") == "e-heavy",
          str(rs))
    check("GET roles 含分级线与 audit_mode",
          gr["roles"].get("l1_max_lines") == 200
          and gr["roles"].get("l2_max_lines") == 200
          and gr["roles"].get("audit_mode") == "auto")
    jr2 = _c.post("/api/harness/roles", json={
        "model_map": ["open.bigmodel.cn=mm-li,mm-hv"]}).get_json()
    check("POST model_map 已退役：被忽略不落盘（v3.5.18，识图走 /vision）",
          not jr2.get("model_map")
          and not (hr.roles_cfg().get("model_map") or {}).get("open.bigmodel.cn"),
          str(jr2))
    check("model_map 不再影响三角色档位（v3.5.15 退役）",
          hr.resolve_role_models() != ("mm-li", "mm-hv"))
    jr3 = _c.post("/api/harness/roles", json={"audit_mode": "bogus"})
    check("audit_mode 非法 → 400", jr3.status_code == 400)
    jr4 = _c.post("/api/harness/roles", json={"executor_model": "old-keep"})
    check("旧键仍被接受落盘（兼容）",
          jr4.get_json().get("executor_model") == "old-keep")
    # v2.53：设计者/审计者槽新键端到端（POST 落盘 + resolved 回显）——
    # 白名单漏键会在此现形（面板保存假成功 bug 的回归测试）
    jr5 = _c.post("/api/harness/roles", json={"designer_model": "e-dm",
                                  "reviewer_model": "e-rm",
                                  "design_max_lines": 150})
    jr5 = jr5.get_json(silent=True) or {}
    check("POST 设计者/审计者槽落盘",
          jr5.get("ok") and jr5.get("designer_model") == "e-dm"
          and jr5.get("reviewer_model") == "e-rm", str(jr5))
    # v3.5.0 三档端到端：mid_model 落盘+resolved.mid 回显；退役键被白名单忽略
    jr6 = _c.post("/api/harness/roles", json={"mid_model": "e-mid",
                                  "main_model": "should-ignore",
                                  "light_keywords": "should-ignore"}).get_json()
    gr6 = _c.get("/api/harness/roles").get_json()
    rs6 = gr6.get("resolved") or {}
    check("POST mid_model 落盘 + resolved.mid 回显（显式优先）",
          jr6.get("mid_model") == "e-mid" and rs6.get("mid") == "e-mid",
          str((jr6, rs6)))
    check("退役键 main_model/light_keywords 被白名单忽略不落盘",
          "main_model" not in jr6 and "light_keywords" not in jr6
          and "main_model" not in gr6["roles"]
          and "light_keywords" not in gr6["roles"], str(jr6))

    check("POST 设计线落盘（数字键）",
          jr5.get("design_max_lines") == 150, str(jr5))
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
