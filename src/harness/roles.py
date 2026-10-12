# -*- coding: utf-8 -*-
"""三档形态角色设计——harness 内置定义（v3.5.0）。

角色定义是 harness 的一部分，不是用户手工放的 ~/.claude/agents/*.md：
会话启动时自动把子代理定义安装到 claude 的 agents 目录（幂等：内容有变
才写，配置改了模型会同步重生成）。任何人装了本工具即得，零手工配置。

模型名存 config.json 的 harness_roles 节（light_model / mid_model /
heavy_model / enabled / audit_mode / l1_max_lines / l2_max_files /
l2_max_lines / design_max_lines / designer_model / reviewer_model），换
API 方案改配置即可，不用动代码（v3.5.15 端点映射退役：model_map 键现归
识图专用，见 harness_vision 节）。

形态（roles_mode，v3.5.0 三档精确匹配）：用户在面板直接配「哪个模型是
轻/中/重哪一档」——实跑模型名归一化（剥 [1M] 类窗口后缀 + casefold）
后依次匹配 三档配置值（同值配多档时 轻>中>重），首个命中即该形态：
- light 轻档：轻主力——designer+reviewer 双代理 + 分级线全档
  + 回合结算审计（=旧 light 行为；v3.5.51 事中闸退役，中途不拦截）；
- mid 中档：中主力——直干 + 仅 reviewer 审核兜底（=旧 strong 行为）；
- heavy 重档：最信任档——直干为主但**派发自由**（designer/reviewer/通用
  子代理按需都可派，v3.5.16 用户纠偏「重模型难道不能派代理吗」），免的
  只是强制分级线（回合结算审计全免）；v3.5.12 两档简化：mid 没配
  =没有中档这一层，重档值命中直接 heavy；
- 未匹配：mid 配了兜 mid（安全：多一道审），mid 没配按两档兜 heavy。
main_model / light_keywords（v3.4.95 词表识别）已退役：三档下拉本身即
显式声明，第二真相源只会重蹈「配置漂移压死实跑」的坑。

三形态共同点（v3.5.17 用户定调）：**派发自由**——通用子代理（探查/搜索/
并行任务）三档都按需随时可派；档位差别只在强制项——轻档=设计+审核必须
（分级线全档）、中档=审核必须（审计线）、重档=零强制。子代理只留两个
专职——设计者/审计者各取 designer_model/reviewer_model 槽（空=回退重档
heavy_model→自动识别）：
- designer 设计者：只设计，绝不干活——输出架构/模块划分/关键决策/风险/
  依赖顺序的框架方案；工具全集（除 Task——禁派子代理），用权限核实代码
  现状/跑验证确认可行性，方案有必要时可输出设计文档（*.md）辅助交付；
  light 形态常驻安装
  （派发纪律：主会话必须把已知上下文尽可能带上——目标/背景与约束/已试
  方案/相关文件+行号/验收标准）；
- reviewer 审核者：只读——工具集无编辑类，body 明文强化「不允许修改
  代码/测试用例」；对抗审核 PASS/FAIL，轻审（只审 diff）/全审（取证级）
  两档；light/mid 都安装（mid 的审计兜底就是它）。
- executor/coder/dev 三角色退役：任何形态都不安装、md 退役删除。

安装/退役（install_roles_agents，幂等）：
- light/heavy → designer.md + reviewer.md 双装（heavy 派发自由，
  v3.5.16——昔日「重档定向删两文件」的例外随禁派发语义退役）；mid →
  只 reviewer.md；
- executor.md/coder.md/dev.md 无条件退役清理；
- 开关关闭 → 全部清理。

模型池解析（resolve_role_models → (轻池, 重池)），优先级：
① 显式档位配置 light_model/heavy_model（面板三档下拉；旧键
  executor_model/coder_model 降级——仅对应新键为空时参与）；
② 当前方案模型表自动分类（内置轻量词表，见 _pick_pool_models）；
③ 硬默认 ("glm-5.3-flash", "glm-5.3")。
v3.5.15：model_map 端点映射从三角色判定链退役（用户拍板「换 API 方案
时由我自己重新配轻中重才合理」）——model_map 键归识图专用
（vision_mcp 按端点解析识图模型），换方案请在面板重配档位。

审计（与 claude_harness 共用纯函数，引导词/结算/闸三处同源）：
- audit_limits：两档线现值 (l1, l2f, l2l)——l1 免审线；l2l 轻审线
  （单次直改总行数）；l2f 键保留兼容但 v2.52 起不参与任何判定
  （v3.5.41 用户拍板收紧：改回合内直改累计——单次最大口径被多次小 Edit 切片逃逸，实测 174 行回合零审计）
  0 合法（最严档），缺键/非法回默认；
- audit_verdict(lines, rev, strong)：light——单次超免审线未轻审=
  违规、单次超轻审线属大改须全审未派=违规（已派视作审过，不重复
  追责）；strong 旗（=中档 mid 直干；重档 heavy 上游短路全免）——单次
  超审计线未派 reviewer=违规（直干是常态，
  无轻审义务）；设计档（v2.54）：回合内直改累计 ≥ 设计线（design_limit，
  0=关）未派 designer=违规；designer 派发豁免设计档（不产生直改、
  不算已审）；
- audit_gate_check(used_lines, reviewed, designed)：事中闸（仅 light
  注入 hook）——审计档（达轻审线未派 reviewer）与设计档（达设计线
  未派 designer，v2.54）两档独立判定，任一命中拦下一次并指路；已派
  对应代理即放行对应档（审过开闸：直干是常态，闸只逼送审不逼停工
  ——没有可转派的干活代理，硬拦到底会死锁）；
- clamp_role_limits：l1 ≤ l2l 交叉校验（clamp 档，回显原因）。

实测要点：agent 文件的 model 字段必须写【显式模型 ID】——别名
（opus/haiku）在这条链路上会被无视（子代理跑主链模型）。

版本史（仅此处与 git，不进引导词/body）：
- v2.29-v2.34：三角色（executor/coder/designer→dev + reviewer）双形态、
  回合结算审计、结构禁权、配置面板；
- v2.37：agents 目录函数化+护栏+审计日志（两次误清用户真目录的根治）；
- v2.40：直改事中闸（PreToolUse hook）；
- v2.42-v2.46R：子代理转写/回放/窗格体系（前端）；
- v2.49：任务分级路由 L0-L4（轻主力大部分中小编码回主会话直改）；
- v2.50：strong 主会话直干（砍派发分工）、三槽配置、clamp、SendMessage
  续派计派发标记；
- v2.51（本次，用户拍板重规划）：轻形态也砍轻子代理——主会话（轻模型）
  一个人干所有活，子代理只留 designer（只设计）+ reviewer（只读审核）
  两个重模型；executor/coder/dev 退役清理（含死代码 body）；模型轻重
  判定废「名字含 flash/turbo/light 判轻」改「除 Opus 皆轻」+ 两池显式
  配置（旧键降级兼容）；分级路由 L0-L4 语义收编进新引导词（免审线/
  轻审线保留，派 dev 路径作废）；引导词与 body 全面去版本代号瘦身；
- v2.52 曾定「单次最大不累计」；v3.5.41 用户实锤多次小 Edit 切片逃逸
  （174 行回合零审计）改回合内累计；文案去「Task 工具」名；
- v2.53：三槽直白化「主会话/设计者/审计者」各自模型（designer_model/
  reviewer_model 新键，空=回退重池）；「重」角标移除；
- v2.54（用户拍板）：设计线 design_max_lines（默认 200，0=不强制）——
  回合内直改累计达线未派 designer：回合结束结算追责，强制大改方案先行（v3.5.51 事中闸退役：中途不打断）；
  子代理段内补 text 气泡（轮询+回填双通道）；回传历史/实时分离
  （历史绝不新建段）。
"""
import json
import os
import re
import time

import src.app_state as _st

_ROLES_KEY = "harness_roles"

# v2.37（P0+ 根治 c）：目录必须函数化——模块级常量硬指向真实 HOME，测试
# monkeypatch config 路径清的却是真目录（v2.34 犯过，2026-09-21 00:33 又犯：
# 无参 install_roles_agents() 把用户真目录换成了 strong 套装）。现在测试用
# HARNESS_AGENTS_DIR 环境变量重定向，生产零感知。
def _agents_dir():
    """agents 目录（每次调用解析）。测试环境变量 HARNESS_AGENTS_DIR 重定向
    到隔离目录；未设置时走真实 ~/.claude/agents。"""
    d = (os.environ.get("HARNESS_AGENTS_DIR") or "").strip()
    if d:
        return os.path.abspath(d)
    return os.path.join(os.path.expanduser("~"), ".claude", "agents")


def _agents_dir_audit(action, detail):
    """v2.37（P0+ 根治 b）：安装/卸载动作落一行审计日志——用户目录两次被
    清都无法事后定位肇事者，这行日志让「谁在什么时候动了 agents 目录」
    永远可查。失败静默（日志不可用不拖垮安装）。"""
    try:
        import src.app_state as _st2
        p = os.path.join(_st2.HOME_DIR, "agents_dir_audit.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s | %s | %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), action, detail))
    except Exception:
        pass


def _agents_dir_guard(d):
    """v2.37（P0+ 根治 b）：测试护栏——环境变量重定向生效时，解析目录不得
    等于/位于真实 ~/.claude 下（防测试误配环境变量反而打真目录）。违规直接
    抛错（测试必须响亮失败，静默等于没护）。"""
    if not (os.environ.get("HARNESS_AGENTS_DIR") or "").strip():
        return d
    real = os.path.join(os.path.expanduser("~"), ".claude", "agents")
    nd, nr = os.path.normcase(os.path.normpath(d)), os.path.normcase(os.path.normpath(real))
    if nd == nr or nd.startswith(nr + os.sep):
        raise ValueError("HARNESS_AGENTS_DIR 指向真实 agents 目录（%s）——测试隔离失效" % d)
    return d

# 轻量词表（v3.5.0 职能收缩）：不再参与形态判定（三档精确匹配取代），
# 仅服务 _pick_pool_models 给空档位挑 sane 默认值（首次用户下拉的预填）
_LIGHT_RE = re.compile(r"flash|turbo|mini|haiku|lite|nano|micro|small|instant", re.I)


def _norm_model(m):
    """档位匹配归一化：剥 [1M] 类窗口后缀 + casefold。用户配置值常带
    [1M] 后缀、网关名大小写不一——不归一化会匹配失败全落中档（迁移期
    最大静默坑，方案 R2）。"""
    return str(m or "").split("[")[0].strip().casefold()

_DEFAULTS = {"enabled": False,          # 默认关闭（用户定调：开关开启才生效）
             # v3.5.19R（用户纠偏「三槽只是默认，也可自己随便改」）：三档
             # 显式配置键回归——空=默认联动 API 配置三槽（Haiku/Sonnet/Opus，
             # 见 _tier_env），显式值优先于三槽
             "light_model": "",         # 轻档（空=Haiku 槽值）
             "mid_model": "",           # 中档（空=Sonnet 槽值）
             "heavy_model": "",         # 重档（空=Opus 槽值）
             # light 形态审计（回合结算盘点工具调用记录，零 token）：
             "audit_mode": "auto",      # 兜底档：auto=违规自动续发补审 / warn=仅警示 / off=关
             # 分级线两档（旧 max_free_lines=3 已废；v2.52 只看单次直改
             # 总行数，不计文件数、不做回合累计）：
             "l1_max_lines": 100,       # 免审线：回合内直改累计 ≤ 此行数免审
             "l2_max_files": 3,         # 已退役不参与判定（键保留兼容旧配置）
             "l2_max_lines": 200,       # 轻审线：回合内直改累计 ≤ 此行数；超线属大改须全审
             "design_max_lines": 200}   # 设计线：回合内直改累计 ≥ 此行数须先派 designer 出方案（0=不强制）


def roles_cfg():
    """读角色配置（缺字段兜默认；**未知键原样保留**——旧版遗留的
    executor_model/coder_model 等键由此透传给降级逻辑，不丢）。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        r = d.get(_ROLES_KEY)
        if isinstance(r, dict):
            out = dict(_DEFAULTS)
            out.update(r)
            return out
    except Exception:
        pass
    return dict(_DEFAULTS)


_DESIGNER_BODY = """你是「设计者」——只设计，绝不干活。

职责：
- 框架方案：架构、模块划分、关键决策及理由、依赖顺序、风险与应对
- 需求拆解：把含糊/复杂需求拆成可执行的实现路线（到文件级/步骤级）
- 疑难诊断：bug 根因方向分析、技术选型比较、架构权衡

铁律——你不实施：
- 不交付代码改动：动手实施的是派发方（主会话），不是你
- 你有完整工具（除派发子代理）：用来核实代码现状、跑只读检查与测试
  验证可行性——让方案建立在事实上而非猜测上；方案有必要时输出设计
  文档（*.md）辅助交付
- 产出是方案本身：结论先行 → 架构与模块划分 → 关键决策及理由 →
  实施步骤与依赖顺序 → 风险与验证方法
- 派发方（主会话）按你的方案实施——方案要细到可照做，动手的是它不是你

纪律：
- 禁止派发子代理（Task/Agent）——你是最底层执行单元
- git commit/push 由主会话执行，你没有提交权
- 信息不足时明确列出假设，不要含糊带过
"""

_REVIEWER_BODY = """你是「审计者」——对抗性代码审核员。唯一职责：证明这份改动有问题。

立场：假定代码是错的。你的价值在于找出问题，不在于肯定代码。真找不到
问题时必须说清查过什么、怎么取证的，不许敷衍放行。

审档两形（派发方在任务里声明；未声明按全审）：
- 轻审：只审 diff——逻辑正确性、边界条件、与周边代码一致性三个维度，
  不重建全项目上下文，快速给结论（同样只审不改）。
- 全审：取证级——下方全部维度逐一过。

审查维度（对每处改动逐一过；轻审只取带☆的三项）：
- 需求符合性：对照任务描述逐条核对——漏做、做偏、做多了都算问题
- 逻辑正确性☆：边界条件、空值/越界、错误默认值、分支遗漏
- 健壮性：异常路径、失败处理、资源泄漏、并发/竞态
- 安全性：注入、路径拼接、越权、敏感信息泄露
- 一致性☆：与项目既有风格约定冲突、重复造轮子、破坏既有行为

取证纪律（全审全额执行；轻审可缩至 diff 相关文件的对应段落）：
- 必须 Read 相关文件核对实际代码，不能只信交付报告的自述
- 能跑的验证（命令/测试/编译）要实际跑，跑不了的注明原因
- 只读！不允许修改代码、不允许修改测试用例、不动任何文件——发现问题
  报告，修复归实施方

结论格式（严格二选一）：
PASS —— 仅当穷尽该档维度仍未发现问题；列出已查维度与取证动作
FAIL —— 每个问题一条：文件:行号、问题描述、严重级（致命/严重/一般）、
        修复建议；致命/严重问题未解决前不许改口 PASS

纪律：
- 禁止派发子代理（Task/Agent）
- git commit/push 由主会话执行，你没有提交权
"""


def update_roles_cfg(patch):
    """merge 写角色配置（只动 patch 里出现的键，其余键保留；main_model/
    light_keywords 已退役——POST 白名单不收，未知键由 roles_cfg 透传容忍）。
    返回 (ok, err)。生效路径与开关一致：档位模型（light/mid/heavy——形态
    翻转即换词）/分级线（l1_max_lines 等）出现在引导词里 → 下条消息前的
    指纹热更自动换词重启 + agents 重生成；audit_mode 在回合结算时读盘，
    即时生效。enabled 关闭即清理 agents（残留定义会被 CLI 自动发现）。
    v3.4.54 起走 app_state.cfg_commit（config.json 五写方统一锁+原子事务，
    消除读-改-写窗口互抹与撕裂放大）。"""
    def _mut(d):
        r = d.get(_ROLES_KEY)
        r = r if isinstance(r, dict) else {}
        r.update(patch)
        d[_ROLES_KEY] = r
    ok, err = _st.cfg_commit(_mut)
    if not ok:
        return False, err
    if patch.get("enabled") is False:
        # 关闭即清理角色文件：CLI 自动发现 agents 目录，残留定义会让模型
        # 在开关关闭后仍自发派发（违背「关闭=回到普通」）
        _uninstall_roles_agents()
    return True, None


def _pick_pool_models(models, default):
    """从当前方案模型表按内置轻量词表分类（v3.5.0：仅给空档位挑 sane
    默认值，形态判定不走这里——见 roles_mode 三档精确匹配）：
    含轻量词 → 轻池；其余 → 重池。default 落其所属池优先取；重池回退
    default——用户主模型通常是该方案里最强的；轻池优先取与重池**不同**
    的模型（default 同时被重池占用时让位给更轻的候选），方案只有一个
    模型时两池共用。模型名带 [1M] 类窗口后缀会被剥离（agent 的 model
    字段必须裸 ID）。返回 (light, heavy)；表为空返回 (None, None)。"""
    bare = []
    for m in models or []:
        b = str(m).split("[")[0].strip()
        if b and b not in bare:
            bare.append(b)
    if not bare:
        return None, None
    d = str(default or "").split("[")[0].strip()
    light_pool = [m for m in bare if _LIGHT_RE.search(m)]
    heavy_pool = [m for m in bare if not _LIGHT_RE.search(m)]
    heavy = (d if d in heavy_pool else None) \
        or (heavy_pool[0] if heavy_pool else None) \
        or (d if d in bare else None) or bare[0]
    light = (d if (d in light_pool and d != heavy) else None) \
        or next((m for m in light_pool if m != heavy), None) \
        or (d if d in bare else None) or bare[0]
    return light, heavy


def resolve_role_models(models=None, default=None):
    """按当前 API 方案解析 (轻池模型, 重池模型)。
    优先级：① 显式档位配置 light_model/heavy_model（旧键
    executor_model/coder_model 降级——仅在对应新键为空时参与）；② 当前
    方案模型表自动分类（内置轻量词表，见 _pick_pool_models）；③ 硬默认。
    v3.5.15（用户拍板「换 API 方案时由我自己重新配轻中重才合理」）：
    model_map 端点映射从三角色判定链退役——model_map 键现归识图专用
    （vision_mcp 按端点解析识图模型，识图配置面板读写），三角色档位
    跨方案不自动切换，换方案请在面板重配档位。两池独立回退。"""
    cfg = roles_cfg()
    if models is None:
        try:
            # 惰性导入防循环（claude_harness 也 import 本模块）
            from ..claude_harness import available_models as _am
            d = _am()
            models, default = d.get("models") or [], d.get("default")
        except Exception:
            models, default = [], None
    cl = str(cfg.get("light_model") or cfg.get("executor_model") or "").split("[")[0].strip()   # 剥 [1M]（全审 R1）
    ch = str(cfg.get("heavy_model") or cfg.get("coder_model") or "").split("[")[0].strip()
    auto_l, auto_h = _pick_pool_models(models, default)
    return (cl or auto_l or "glm-5.3-flash",
            ch or auto_h or "glm-5.3")


def resolve_agent_models(models=None, default=None):
    """解析 (designer 模型, reviewer 模型)——v2.53 用户拍板：面板直白配
    「设计者/审计者」各自模型（designer_model/reviewer_model 显式优先），
    缺省回退重池（heavy_model→自动分类→硬默认），即两代理共用重模型的
    历史行为；只配一槽不影响另一槽回退。v3.5.18（全审建议11）：显式槽
    值剥 [1M] 类窗口后缀——agent md 的 model 字段必须裸 ID（自动路径
    _pick_pool_models 早剥，显式路径此前漏剥）。v3.5.19：回退重档取
    resolve_tier_models 的重档（联动 API 配置三槽）。"""
    cfg = roles_cfg()
    _tl, _tm, heavy = resolve_tier_models(models, default)
    cd = str(cfg.get("designer_model") or "").split("[")[0].strip()
    cr = str(cfg.get("reviewer_model") or "").split("[")[0].strip()
    return (cd or heavy, cr or heavy)


def _tier_env():
    """当前生效 API 方案的 anthropic 三槽映射（v3.5.19 用户拍板「三档与
    API 配置联动」）：读 ~/.claude/settings.json env——
    ANTHROPIC_DEFAULT_HAIKU_MODEL → 轻档、…SONNET… → 中档、…OPUS… → 重档。
    用户配 API 方案时已声明过三槽映射，档位跟随它是唯一真相源（独立三档
    配置键 light/mid/heavy_model 退役）。HARNESS_TIER_SETTINGS 环境变量可
    重定向 settings 路径（测试隔离用）。读不到（异常/缺槽）返回对应空串，
    由调用方回退方案表自动分类。"""
    try:
        p = (os.environ.get("HARNESS_TIER_SETTINGS") or "").strip() \
            or os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = (json.load(f).get("env") or {})
        return (str(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") or "").split("[")[0].strip(),
                str(env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or "").split("[")[0].strip(),
                str(env.get("ANTHROPIC_DEFAULT_OPUS_MODEL") or "").split("[")[0].strip())
    except Exception:
        return ("", "", "")


def resolve_tier_models(models=None, default=None):
    """解析三档模型 (轻, 中, 重)——形态判定的数据源（v3.5.19R：显式优先、
    三槽默认）：① 面板显式配置 light/mid/heavy_model；② 未配档位默认联动
    API 配置三槽（Haiku→轻 / Sonnet→中 / Opus→重，_tier_env，换方案自动
    跟随；中档缺省取重档同值）；③ 轻/重仍缺回退方案表自动分类
    （_pick_pool_models）。model_map 端点映射保持退役。"""
    cfg = roles_cfg()
    cl = str(cfg.get("light_model") or "").split("[")[0].strip()
    cm = str(cfg.get("mid_model") or "").split("[")[0].strip()
    ch = str(cfg.get("heavy_model") or "").split("[")[0].strip()
    el, em, eh = _tier_env()
    cl = cl or el
    cm = cm or em or eh     # 中档缺省=重档值（Sonnet 槽在则用槽值）
    ch = ch or eh
    if not cl or not ch:    # 显式+三槽都缺的档 → 方案表自动分类兜底
        _pl, _ph = resolve_role_models(models, default)
        cl = cl or _pl
        cm = cm or _ph
        ch = ch or _ph
    return (cl, cm, ch)


def roles_mode(model=None):
    """主会话形态（v3.5.19 三档联动 API 配置）：
    实跑模型名归一化（_norm_model：剥 [1M] 后缀 + casefold）后依次匹配
    三槽档位值（resolve_tier_models：Haiku→轻 / Sonnet→中 / Opus→重），
    同值多档时 轻>中>重：
    - "light"：轻主力——designer+reviewer 双代理 + 分级线/结算审计；
    - "mid"：中主力——直干 + reviewer 审核兜底（=旧 strong 行为）；
    - "heavy"：最信任档——直干为主+派发自由（designer/reviewer/通用
      子代理按需可派，v3.5.16），免的只是强制分级（结算审计全免）；
    - 未匹配任何槽 / 名字不可得 → mid（安全兜底：漏配的最坏后果是多一道
      审）；内部异常兜 mid。"""
    try:
        model = str(model or "").strip()
        if not model:
            return "mid"
        n = _norm_model(model)
        light, mid, heavy = resolve_tier_models()
        if light and n == _norm_model(light):
            return "light"
        if mid and n == _norm_model(mid):
            return "mid"
        if heavy and n == _norm_model(heavy):
            return "heavy"
        return "mid"   # 未匹配兜中档（安全：多一道审）
    except Exception:
        return "mid"


def _agent_md(name, description, model, body, tools=None):
    """显式声明 tools 清单——实测省略时新版 CLI 给子代理的默认工具集
    **不含文件编辑类**（曾实锤「Edit 不在可调用清单」，被迫用 Bash 脚本
    绕行改文件）。角色按定位显式给全，防默认集变动再翻车。tools 接受
    逗号串（_TOOLS_* 常量）或列表。"""
    t = ("\ntools: %s" % (", ".join(tools) if not isinstance(tools, str)
                          else tools)) if tools else ""
    return ("---\nname: %s\ndescription: %s\nmodel: %s%s\n---\n%s"
            % (name, description, model, t, body))


# 角色工具清单：
# designer 定位「只设计不干活」——工具全集（除 Task：禁派子代理），
# 权限用于核实现状/验证可行性/输出设计文档，不交付代码改动（body 纪律，
# 用户拍板：除审计者只读外全部角色全工具）；SendMessage 保留（向主会话
# 回话链路要用，接收不依赖本表）。
# reviewer 定位「只审不改」——排除 Write/Edit/MultiEdit/NotebookEdit（此
# 只读限制不动）与 Task（禁派子代理，与 designer 同规）；Bash 保留（取证
# 纪律要求能跑的验证实际跑）。
_TOOLS_DESIGN = ("Read, Write, Edit, MultiEdit, NotebookEdit, Bash, Glob, "
                 "Grep, WebFetch, WebSearch, TodoWrite, SendMessage, "
                 "AskUserQuestion")
_TOOLS_REVIEW = ("Read, Bash, Glob, Grep, WebFetch, WebSearch, "
                 "TodoWrite, SendMessage, AskUserQuestion")


# 本工具托管的五个角色文件名（同名自建 agent 会被覆盖/清掉，记录在案）。
# 其中 executor/coder/dev 已退役：任何形态都不安装、无条件清理残留。
_SELF_AGENTS = ("executor.md", "coder.md", "designer.md",
                "dev.md", "reviewer.md")
_RETIRED_AGENTS = ("executor.md", "coder.md", "dev.md")


def _uninstall_roles_agents():
    """删除本工具管理的角色文件（只动 _SELF_AGENTS 自有名，用户其他自建
    代理不碰）。CLI 自动发现 ~/.claude/agents/ 下的代理——关闭开关若不
    清理，模型仍可能自发派发 Task 给角色代理，违背「关闭=回到普通」的
    语义。失败静默。
    v2.37（P0+）：目录函数化+护栏+审计日志（本函数曾两次清掉用户真目录）。"""
    d = _agents_dir_guard(_agents_dir())
    removed = []
    for fn in _SELF_AGENTS:
        try:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                os.remove(p)
                removed.append(fn)
        except Exception:
            pass
    _agents_dir_audit("uninstall(enabled=False)",
                      "dir=%s removed=%s" % (d, ",".join(removed) or "-"))


def install_roles_agents(model=None):
    """按当前形态安装/更新角色子代理定义到 ~/.claude/agents/（幂等：内容
    有变才写）。light/heavy → designer+reviewer 双装（v3.5.16 重档派发
    自由，各取 designer_model/reviewer_model 槽，空=回退重档）；mid → 只
    reviewer（审计兜底代理，designer 共存不清）；executor/coder/dev 无条件
    退役清理。开关关闭 → 全部清理。失败静默（不拖垮会话启动）。"""
    cfg = roles_cfg()
    if not cfg["enabled"]:
        _uninstall_roles_agents()
        return
    d = _agents_dir_guard(_agents_dir())
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return
    mode = roles_mode(model)
    designer_m, reviewer_m = resolve_agent_models()
    # 三形态共用定义（v3.5.18 合并 light/heavy 两分支——逐字重复漂移风险，
    # 全审建议9）：mid 只装 reviewer；light/heavy 双装（v3.5.16 重档派发
    # 自由——昔日「重档定向删两文件」随禁派发语义退役）
    _reviewer_md = _agent_md(
        "reviewer",
        "审计者：改动交付或超审计线时派此代理审——分"
        "两档：轻审（只审 diff）／全审（取证级：需求符合性/逻辑/健"
        "壮性/安全/一致性）。只读不改，PASS/FAIL 二选一。"
        "复审（复核自己 FAIL 过的修复）由主会话 SendMessage 续派本"
        "代理完成——上下文保留逐条验收、免重读文件；新审计目标才新开"
        "本代理。",
        reviewer_m, _REVIEWER_BODY, tools=_TOOLS_REVIEW)
    if mode == "mid":
        # 中主力：主会话直干，只装审计兜底的 reviewer（designer 共存不清）
        wanted = {"reviewer.md": _reviewer_md}
    else:
        # light / heavy：双装（heavy 派发自由，v3.5.16）
        wanted = {
            "designer.md": _agent_md(
                "designer",
                "设计者：只设计，绝不干活——架构/模块划分/关键决"
                "策/风险/依赖顺序的框架方案；不写代码不改文件不跑实现。需"
                "要高水平方案时派此代理，并把已知上下文尽可能带上。",
                designer_m, _DESIGNER_BODY, tools=_TOOLS_DESIGN),
            "reviewer.md": _reviewer_md,
        }
    wrote = []
    for fn in _SELF_AGENTS:
        p = os.path.join(d, fn)
        if fn in _RETIRED_AGENTS:
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    wrote.append("%s(退役,删)" % fn)
            except Exception:
                pass
            continue
        if fn not in wanted:
            # 另一形态的在用文件——共存不清理（v2.37 目录共享原则；v3.5.16
            # heavy 已改双装，昔日的定向删分支随「禁派发」语义退役）
            continue
        try:
            cur = None
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    cur = f.read()
            if cur != wanted[fn]:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(wanted[fn])
                wrote.append(fn)
        except Exception:
            pass
    _agents_dir_audit(
        "install(%s)" % mode,
        "model=%s dir=%s wrote=%s" % (model or "-", d, ",".join(wrote) or "-(已是最新)"))


def ensure_roles_ready(model=None):
    """派发前自愈：Task/SendMessage 派发前调用——幂等重装本形态角色定义
    （install 有变才写，成本可忽略），兜住一切上游删除路径（旧版互清/
    测试误清/人工误删），保证派发瞬间定义必在。返回安装前**缺失**的期望
    文件名清单——非空=发生过自愈，调用方应红卡告警（陈旧内容由 install
    静默修复，审计日志可查）。light/heavy 需要 designer.md+reviewer.md
    （heavy 派发自由，v3.5.16）；mid 只需 reviewer.md（审计兜底代理）。"""
    if not roles_cfg()["enabled"]:
        return []
    d = _agents_dir_guard(_agents_dir())
    _m = roles_mode(model)
    need = ["reviewer.md"] if _m == "mid" else ["designer.md", "reviewer.md"]
    missing = [fn for fn in need if not os.path.isfile(os.path.join(d, fn))]
    install_roles_agents(model)
    if missing:
        _agents_dir_audit("self-heal(派发前自愈)",
                          "model=%s dir=%s healed=%s" % (model or "-", d, ",".join(missing)))
    return missing


def audit_limits(cfg=None):
    """审计两档线现值：(l1_max_lines, l2_max_files, l2_max_lines)。
    引导词 / 回合结算两处共用本函数（事中闸 v3.5.51 退役）——数字同源，不会词里一套
    审计另一套。0 合法（最严档：l1=0 任何直改都须轻审；l2=0 任何直改都
    属大改须全审），缺键/非法回默认。纯函数不落盘（cfg 缺省读盘一次）。
    v2.52 曾定单次最大口径；v3.5.41 改回合内累计。l2_max_files 不再参与任何
    判定（键与返回形状保留兼容旧配置/旧调用方；clamp_role_limits 仅解包
    弃值不消费它）。"""
    c = cfg if cfg is not None else roles_cfg()

    def _int(key, dflt):
        try:
            # 不用 ` or dflt` 兜底——那会把合法的 0 吞成默认
            return max(0, int(c.get(key)))
        except (TypeError, ValueError):
            return dflt
    return (_int("l1_max_lines", 100), _int("l2_max_files", 3),
            _int("l2_max_lines", 200))


def design_limit(cfg=None):
    """设计线现值（v2.54）：回合内直改累计 ≥ 此行数的大改，动手前须先派
    designer 出框架方案——主会话惯性全自己做（用户原话）的事前强制档。
    0=不强制设计（与审计线「0=最严」语义相反：设计强制的是动手前行为，
    0 线会让一切直改都要先出方案，过凶）。缺键/非法回默认 200。
    纯函数不落盘。"""
    c = cfg if cfg is not None else roles_cfg()
    try:
        return max(0, int(c.get("design_max_lines")))
    except (TypeError, ValueError):
        return 200


def audit_verdict(lines, rev, designed=True, cfg=None, strong=False):
    """【v3.5.100 起退役】结算已改用户消息边界制（session._audit_settle 内
    联新口径：lines 跨 AI 回合累计+审后再审），本函数不再被调用——保留仅供
    tests/test_roles_routing.py 锚旧纯函数语义（口径参考，非活代码）。
    原文档：回合结算违规判定（纯函数）：
    入参 lines=本回合直改累计行数（v3.5.41 起 _audit_tally 累计入账）、rev=是否派发过 reviewer、
    designed=是否派发过 designer（v2.52 用户拍板：判定只看单次直改总
    行数——不计文件数、不做回合累计；v2.54 新增设计档强制）。返回违规
    描述列表（空=干净）；描述自带档位与可数依据，供警示卡/补审指令直用。
    判定与引导词同源（audit_limits / design_limit）：
    - light：免审区（lines≤l1）干净；轻审区（l1<lines≤l2l）须 reviewer
      轻审，未派=违规；lines>l2l 属大改——直改须 reviewer 取证级全审，
      未派=违规（已派视作审过，不重复追责——提示性兜底）；设计档
      （v2.54）：lines≥设计线且未派 designer=违规（大改须方案先行；
      dl=0 关闭；事后只能查「派过没有」（v3.5.51 事中闸退役，无前置
      时序强制，漏派由结算兜底）；
    - strong 旗（v3.5.0 起=中档 mid 直干；重档 heavy 在上游 _audit_state
      已短路返回 None 不进本函数）：只守审计线（lines>l2l 且未派
      reviewer=违规；直干是设计常态，无轻审义务，也无 designer 强制
      ——mid 不装 designer）；
    - reviewer 派发豁免审计档；designer 派发豁免设计档——两档独立。
    兜底是提示性的：本函数只判不拦，处置（警示/续发补审）归调用方按
    audit_mode 决定。"""
    l1, _l2f, l2l = audit_limits(cfg)
    viol = []
    if strong:
        if not rev and lines > l2l:
            viol.append(
                "主会话回合内直改累计 %d 行，超过审计线（回合累计 ≤%d 行），"
                "本回合未派 reviewer 审计" % (lines, l2l))
        return viol
    if not rev and lines > l1:
        if lines <= l2l:
            viol.append(
                "主会话回合内直改累计 %d 行，超过免审线（回合累计 ≤%d 行）属"
                "中改，本回合未派 reviewer 轻审（只审 diff）" % (lines, l1))
        else:
            viol.append(
                "主会话回合内直改累计 %d 行，超过轻审线（回合累计 ≤%d 行）属"
                "大改——须 reviewer 取证级全审，本回合未派审" % (lines, l2l))
    dl = design_limit(cfg)
    if dl > 0 and not designed and lines >= dl:
        viol.append(
            "主会话回合内直改累计 %d 行，达到设计线（≥%d 行）属大改，本回合"
            "未先派 designer 出框架方案——大改须方案先行" % (lines, dl))
    return viol


def clamp_role_limits(patch, cfg=None):
    """l1_max_lines ≤ l2_max_lines 交叉校验（clamp 档）。返回
    (new_patch, notes)：new_patch 在 patch 基础上补上被钳的键（原键值
    替换），notes 为 [{"key","from","to","reason"}]（空=无需钳）。
    选 clamp 不选 400：配置面板一次保存三键，用户单调 l2 低于 l1 时 400
    会把整次保存打回（其它合法键也白存），clamp + 回显原因更可用——
    POST /roles 把 notes 原样带回前端提示。
    只向下钳 l1 不动 l2：l2 是审计主线（闸与结算都守它），l1 只是免审区
    上沿，语义上 l1 ≤ l2l 恒成立（免审区是轻审区的子集）。未出现在 patch
    里的键取现值（cfg）参与比较——单独调低 l2 也会把现存 l1 带下来写进
    new_patch。非数字输入不在此处理（端点既有的 400 校验负责）。"""
    c = cfg if cfg is not None else roles_cfg()
    l1_cur, _l2f, l2l_cur = audit_limits(c)
    out = dict(patch)
    notes = []
    try:
        l1 = int(out.get("l1_max_lines", l1_cur))
        l2l = int(out.get("l2_max_lines", l2l_cur))
    except (TypeError, ValueError):
        return out, notes
    if l1 > l2l:
        out["l1_max_lines"] = l2l
        notes.append({
            "key": "l1_max_lines", "from": l1, "to": l2l,
            "reason": ("l1_max_lines 不得超过 l2_max_lines（免审线高于轻审"
                       "线会让免审区吞掉轻审区），已自动收紧至 "
                       "l2_max_lines=%d" % l2l)})
    return out, notes


def audit_gate_check(used_lines, cfg=None, reviewed=False, designed=True,
                     design_fired=False):
    """事中闸判定（纯函数，claude_harness /audit_gate 调用）：
    (block, msg)。v3.5.53（用户定调「设计事中触发一次；审计只事后」）：
    - 设计档：本回合**首次**累计达设计线（design_limit，0=关）且未派
      designer 时拦一次——指路先出方案；design_fired=True（本回合已触发过）
      不再拦（同一事务只咬一口；方案实施中需要核对可随时自由派 designer）；
    - 审计档退役：轻审线中途不再拦——「改一段审一段」把大改切成两半（用户
      实锤），审计统一回合结束结算送审（audit_verdict），允许多次审计直到
      修复完成。
    reviewed/designer 旗保留（派过即放行对应档的旧语义兼容）。口径用 >=
    （达线即触发）。"""
    dl = design_limit(cfg)
    if design_fired:
        return False, None
    if not designed and dl > 0 and used_lines >= dl:
        return True, ("回合内直改累计 %d 行达到设计线（≥%d 行）——请先派 designer "
                      "代理出框架方案（带上全部已知上下文：目标/背景约束/"
                      "已试方案/文件+行号/验收标准），按方案继续实施"
                      "（本回合只提醒这一次，之后自由直改，回合结束统一审计）"
                      % (used_lines, dl))
    return False, None


def roles_bridge_text(model=None):
    """角色引导词（三形态，v3.5.17 派发自由共性+强制项差异）：轻档 →
    轻主力词（直干+设计/审核强制，分级线全档嵌词）；中档 → 中主力词
    （直干+审核强制，审计线嵌词）；重档 → 最信任档词（直干+派发自由、
    零强制，无任何线数字，只保留质量纪律与回合终点纪律）。开关关闭一律
    空串。model 参数参与形态判定并进引导词指纹（切模型/改档位配置自动换
    形态热更）。两档上限（audit_limits）以可数数字嵌进词里，改配置即变词
    （指纹热更），并明示回合结算审计——威慑前置（事前引导词 + 事后审计
    兜底；heavy 豁免）。"""
    if not roles_cfg()["enabled"]:
        return ""
    _mode = roles_mode(model)
    if _mode == "heavy":
        # 重档词（v3.5.16 用户实锤纠偏「重模型难道不能派代理吗」）：撤
        # 「不派任何子代理」——最强模型手脚不该被捆。派发自由（设计/审核/
        # 通用子代理按需判断），免的只是强制审核分级线（_audit_state 全免
        # 不变）；交付纪律保留
        return (
            "【主会话直干（你=最信任档）】\n"
            "本会话用最信任档模型直接干活：编码、执行、调试通常你亲自完成"
            "（能力最强直干最快），但子代理按需自由使用——并行探查、独立"
            "设计（designer）、对抗审核（reviewer）、通用任务代理都可以派，"
            "何时派你自己判断。无审核分级线强制（不会审计你的直改量），质"
            "量由你自己把关。\n"
            "质量纪律：\n"
            "- 动手前先想清楚：需求边界、实现路径、风险点；复杂改动先在回"
            "复里列出方案要点再实施。\n"
            "- 改完自测通过再交；遵守项目既有代码风格与约定。\n"
            "- 回合终点纪律：完成后，最后一条消息必须是给用户的结论汇总"
            "（做了什么、自测结果、用户需要做什么），不得静默结束回合。\n"
        )
    if _mode == "light":
        cfg = roles_cfg()
        l1, _l2f, l2l = audit_limits(cfg)
        # 威慑句按 audit_mode 生成——off 档不宣称「会审计」（空头威胁，
        # 模型被抓过一次空头支票后纪律反而松动）
        if str(cfg.get("audit_mode") or "auto") != "off":
            audit_note = ("harness 会在回合结束时审计你的工具调用记录——按"
                          "回合内直改累计行数判定，不计文件数（多次小改会累"
                          "计，拆小不逃审）；累计超免审线未轻审、超轻审线未"
                          "全审会被自动查出并要求补审")
        else:
            audit_note = "跳过应做的审核（轻审/全审）就答复用户属重大流程违规"
        designer_m, reviewer_m = resolve_agent_models()
        dl = design_limit(cfg)
        # 设计线行按 dl 条件生成（v2.54R：dl=0 引导词不得宣称「≥0 行都要
        # 方案」——词与判定机制同源，否则关闭强制后模型仍被词驱动过度派发）
        if dl > 0:
            design_line = ("· 设计线（强制）：回合内直改累计 ≥%d 行的大改，动手前"
                           "必须先派 designer 出框架方案再实施——不要惯性全"
                           "自己做掉；方案没把握时即使没到线也应先派 "
                           "designer。\n" % dl)
        else:
            design_line = ("· 设计线：未启用（0=不强制）——是否派 designer "
                           "自行判断，方案没把握时建议先派。\n")
        return (
            "【任务分级（你=轻快主力）】\n"
            "本会话是面向用户的轻快主力：日常对话直接答；编码、执行、调试"
            "通常你亲自完成（省 token 且快），通用子代理（探查/搜索/并行任"
            "务等）按需随时可派——派发完全自由；**强制项只有设计与审核**，"
            "分档上限可数，按单次直改总计行数判定（不计文件数、不做回合累"
            "计——只有一次性改超才审计）：\n"
            "· 杂活：问答、查文件、跑命令、环境排查、信息收集 → 你直接"
            "干。\n"
            "· 小改（免审）：回合内直改累计 ≤%d 行的配置/常量/文案/"
            "注释级 → 你直接改，免审。\n"
            "· 中改（轻审）：回合内直改累计 ≤%d 行的真代码改动 → "
            "你直接改，交付前派 reviewer 轻审（只审 diff：逻辑/边界/一致"
            "性）。\n"
            "· 大改（全审）：回合内直改累计超轻审线、多文件重构、架构改动、疑难"
            " bug → "
            "仍由你实施，交付前 reviewer 取证级全审。\n"
            "%s"
            "· 高风险：删数据、发布、外发、碰铁律文件（如 cmdlib.json）"
            "→ 无论谁实施都必须审核，且动手前先向用户显式确认拿到同意。\n"
            "派 designer 的纪律（它只设计不干活：输出架构/模块划分/关键决"
            "策/风险/依赖顺序）：把已知上下文尽"
            "可能带上——①目标（做什么/为什么）②背景与约束 ③已试方案及为"
            "何不行 ④相关文件+行号 ⑤验收标准。上下文给足，方案才可用。\n"
            "派 reviewer 的上下文包四要素：①目标 ②涉及文件+行号 ③已定决"
            "策（禁翻案项）④验收标准。\n"
            "两个专职代理：设计者 designer（%s）只设计、审计者 reviewer"
            "（%s）对抗审核（只审不改，PASS/FAIL 二选一）。\n"
            "流程：中改你改完 → reviewer 轻审；大改 designer 出方案 → 你"
            "实施 → reviewer 全审 → FAIL 自己修再送审，致命/严重问题清零"
            "才收 → 你消化双方结论后汇总答复用户。\n"
            "审计者续派准则（硬性）：新审计目标（新功能/新改动的首轮轻审或"
            "全审）才新开 reviewer——对抗中立性要求新视角；复核自己 FAIL 过"
            "的修复必须 SendMessage 续派原 reviewer（上下文保留、逐条验收、"
            "免重读文件），禁止为复审新开。设计者同理：同一方案的迭代续派，"
            "新方案新开。\n"
            "纪律（%s）：\n"
            "- 不要把该审的改动刻意拆小逃审：单次改动超免审线就必须轻审、"
            "超轻审线就必须全审。\n"
            "- reviewer 判 FAIL 必须回炉重修；两边的报告都要消化后再答，"
            "不要原样转发一大坨。\n"
            "- 回合终点纪律：提交/实施完成后，你的最后一条消息必须是给用户的结论"
            "汇总（做了什么、审核结论、提交号、用户需要做什么）——用户看不到后台"
            "代理的过程，静默结束回合=交付没完成。\n"
            % (l1, l2l, design_line, designer_m, reviewer_m, audit_note)
        )
    # mid 分支：中档模型主会话=干活者，直干为主+派发自由（强制项=审核）；
    # 只保留审计兜底——回合内直改累计超审计线（数字嵌词热更）触发回合
    # 结算审计（audit_verdict strong 分支：超线未派 reviewer=违规）。
    cfg = roles_cfg()
    _l1, _l2f, l2l = audit_limits(cfg)
    if str(cfg.get("audit_mode") or "auto") != "off":
        audit_note = ("harness 会在回合结束时审计你的直改量（按回合内直改"
                      "累计行数，不计文件数）——超过审计线会被自动"
                      "查出并要求派 reviewer 补审后重新汇总；复审复核自己 "
                      "FAIL 过的修复必须 SendMessage 续派原 reviewer（上下文"
                      "保留免重读），新审计目标才新开")
    else:
        audit_note = "大改不派 reviewer 审计就答复用户属重大流程违规"
    return (
        "【主会话直干（你=干活者）】\n"
        "本会话用中档模型直接干活：需求承接、方案、编码、debug、杂活通常由你"
        "亲自完成，通用子代理按需随时可派——派发完全自由；**强制项只有审核**"
        "（审计线见下）。\n"
        "质量纪律：\n"
        "- 动手前先想清楚：需求边界、实现路径、风险点；复杂改动先在回复里"
        "列出方案要点再实施。\n"
        "- 审计兜底（%s）：回合内直改累计超过审计线（回合累计 ≤%d 行）"
        "即触发审计——须派 reviewer 对抗审计（只审不改，PASS/FAIL），FAIL "
        "自己修复后复审再答复用户。\n"
        "- 改完自测通过再交；遵守项目既有代码风格与约定。\n"
        "- 回合终点纪律：完成后，最后一条消息必须是给用户的结论汇总（做了"
        "什么、自测与审核结果、用户需要做什么），不得静默结束回合。\n"
        % (audit_note, l2l)
    )
