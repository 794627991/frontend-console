# -*- coding: utf-8 -*-
"""双形态角色设计——harness 内置定义（v2.51）。

角色定义是 harness 的一部分，不是用户手工放的 ~/.claude/agents/*.md：
会话启动时自动把子代理定义安装到 claude 的 agents 目录（幂等：内容有变
才写，配置改了模型会同步重生成）。任何人装了本工具即得，零手工配置。

模型名存 config.json 的 harness_roles 节（light_model / heavy_model /
main_model / enabled / model_map / audit_mode / l1_max_lines /
l2_max_files / l2_max_lines），换 API 方案改配置即可，不用动代码。

形态（roles_mode）：① main_model 显式配置优先（按配置名识别）；② 实跑
模型名自动识别——默认映射「除 Opus 皆轻」：名字含 opus（不分大小写）→
strong 重模型直干，其余 → light 轻主力；名字不可得兜 strong（不装角色、
直干，与旧版空名行为一致）。

双形态共同点：主会话直干所有活（编码/执行/调试都是自己干），不派干活
子代理；超线由回合结算审计兜底（auto=自动续发派 reviewer 补审 / warn=
仅警示 / off=关）。子代理只留两个，都取重模型（heavy_model）：
- designer 设计者：只设计，绝不干活——输出架构/模块划分/关键决策/风险/
  依赖顺序的框架方案；工具全集（除 Task——禁派子代理），用权限核实代码
  现状/跑验证确认可行性，方案有必要时可输出设计文档（*.md）辅助交付；
  light 形态常驻安装
  （派发纪律：主会话必须把已知上下文尽可能带上——目标/背景与约束/已试
  方案/相关文件+行号/验收标准）；
- reviewer 审核者：只读——工具集无编辑类，body 明文强化「不允许修改
  代码/测试用例」；对抗审核 PASS/FAIL，轻审（只审 diff）/全审（取证级）
  两档；两形态都安装（strong 的审计兜底就是它）。
- executor/coder/dev 三角色退役：任何形态都不安装、md 退役删除、body
  定义已清理（历史上 coder/designer 从未接线的死代码一并消除）。

安装/退役（install_roles_agents，幂等）：
- light → designer.md + reviewer.md；strong → 只 reviewer.md；
- executor.md/coder.md/dev.md 无条件退役清理（残留会被 CLI 自动发现、
  诱导主会话向已不存在的分工派发）；
- designer.md 是 light 在用文件，strong 共存不清理（v2.37 目录共享原则：
  agents 目录全局共享，只确保本形态所需文件在位且最新，绝不动其他形态
  的在用文件）；
- 五个文件名均为本工具托管名：同名自建 agent 会被覆盖/清掉（记录在案，
  不另做识别）；开关关闭 → 全部清理（违背「关闭=回到普通」的残留定义
  会被 CLI 自动发现）。

模型池解析（resolve_role_models → (轻池, 重池)），优先级：
① model_map 端点映射（配置显式指定，关键字匹配 base_url；行式
  "端点=轻,重" 与 dict 形态兼容——executor 键按轻池、coder 键按重池
  解释，沿用旧格式不迁移）；
② 显式池配置 light_model/heavy_model（面板两池下拉，用户显式指定的
  优先于默认映射）；
③ 当前方案模型表自动分类：名字含 opus → 重池，其余 → 轻池（default
  落哪池优先取哪池；无 opus 时重池回退 default——主模型通常是方案里
  最强的）；
④ 硬默认 ("glm-5.3-flash", "glm-5.3")。
旧键降级（读取侧兼容，不迁移写盘）：executor_model → 轻池、coder_model
→ 重池，仅在对应新键为空时参与，新键优先。

审计（与 claude_harness 共用纯函数，引导词/结算/闸三处同源）：
- audit_limits：两档线现值 (l1, l2f, l2l)——l1 免审线；l2f/l2l 轻审线
  （文件数/回合累计行数）。0 合法（最严档），缺键/非法回默认；
- audit_verdict(lines, files, rev, strong)：light——超免审线未轻审=
  违规、超轻审线属大改须全审未派=违规（已派视作审过，不重复追责）；
  strong——超审计线未派 reviewer=违规（直干是常态，无轻审义务）；
  designer 派发不计入判定（设计不产生直改、不触发审计线、也不算
  「已审」）；
- audit_gate_check(used_lines, used_files, reviewed)：事中闸（仅 light
  注入 hook）——直改达线且本回合尚未派过 reviewer 时拦下一次并指路
  送审；已派 reviewer 即放行（审过开闸：直干是常态，闸只逼送审不逼
  停工——没有可转派的干活代理，硬拦到底会死锁）；
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
  轻审线保留，派 dev 路径作废）；引导词与 body 全面去版本代号瘦身。
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

# 重模型识别（默认映射「除 Opus 皆轻」）：名字含 opus（不分大小写）→ 重；
# 其余（flash/turbo/glm/lanz 等一切非 opus 名）→ 轻。旧的「名字含
# flash/turbo/light 判轻」写死规则已废（用户重规划拍板）。
_HEAVY_RE = re.compile(r"opus", re.I)

_DEFAULTS = {"enabled": False,          # 默认关闭（用户定调：开关开启才生效）
             "light_model": "",         # 轻池（主会话直干用；空=按方案自动识别）
             "heavy_model": "",         # 重池（designer/reviewer 用；空=自动识别）
             # 主会话模型槽——显式声明主会话用什么模型，形态判定据此名
             # 识别；空串=按实跑模型名自动识别
             "main_model": "",
             "model_map": {},
             # light 形态审计（回合结算盘点工具调用记录，零 token）：
             "audit_mode": "auto",      # 兜底档：auto=违规自动续发补审 / warn=仅警示 / off=关
             # 分级线两档（旧 max_free_lines=3 已废，三键取代）：
             "l1_max_lines": 100,       # 免审线：单文件且回合累计 ≤ 此行数免审
             "l2_max_files": 3,         # 轻审线：≤ 此文件数（且行数不超线）直改+轻审
             "l2_max_lines": 200}       # 轻审线：回合累计 ≤ 此行数；超任一即大改须全审


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


_DESIGNER_BODY = """你是「设计者」——只设计，绝不干活（重模型）。

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

_REVIEWER_BODY = """你是「审核」——对抗性代码审核员（重模型）。唯一职责：证明这份改动有问题。

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
    """merge 写角色配置（只动 patch 里出现的键，其余键保留）。返回
    (ok, err)。生效路径与开关一致：模型池（含 main_model 主会话槽——形态
    翻转即换词）/分级线（l1_max_lines 等）出现在引导词里 → 下条消息前的
    指纹热更自动换词重启 + agents 重生成；audit_mode 在回合结算时读盘，
    即时生效。enabled 关闭即清理 agents（残留定义会被 CLI 自动发现）。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    r = d.get(_ROLES_KEY)
    r = r if isinstance(r, dict) else {}
    r.update(patch)
    d[_ROLES_KEY] = r
    try:
        tmp = _st.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _st.CONFIG_FILE)
    except Exception as e:
        return False, str(e)
    if patch.get("enabled") is False:
        # 关闭即清理角色文件：CLI 自动发现 agents 目录，残留定义会让模型
        # 在开关关闭后仍自发派发（违背「关闭=回到普通」）
        _uninstall_roles_agents()
    return True, None


def set_roles_enabled(enabled):
    """写开关（转调 update_roles_cfg 的 merge 语义：只动 enabled，其余键
    保留）。改完即生效——角色词在引导词指纹里，下条消息发送前的指纹热更
    会自动 kill+resume 换词重启，已有会话无需重建。"""
    return update_roles_cfg({"enabled": bool(enabled)})


def _current_base_url():
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = (json.load(f).get("env") or {})
        return (env.get("ANTHROPIC_BASE_URL") or "").strip()
    except Exception:
        return ""


def _pick_pool_models(models, default):
    """从当前方案模型表按「除 Opus 皆轻」分类：名字含 opus → 重池；其余 →
    轻池。default 是 opus 落重池、非 opus 落轻池（优先取）；无显式 opus
    时重池回退 default——用户主模型通常是该方案里最强的；轻池优先取与
    重池**不同**的模型（default 同时被重池占用时让位给更轻的候选），
    方案只有一个模型时两池共用。模型名带 [1M] 类窗口后缀会被剥离（agent
    的 model 字段必须裸 ID）。返回 (light, heavy)；表为空返回
    (None, None)。"""
    bare = []
    for m in models or []:
        b = str(m).split("[")[0].strip()
        if b and b not in bare:
            bare.append(b)
    if not bare:
        return None, None
    d = str(default or "").split("[")[0].strip()
    heavy_pool = [m for m in bare if _HEAVY_RE.search(m)]
    light_pool = [m for m in bare if not _HEAVY_RE.search(m)]
    heavy = (d if d in heavy_pool else None) \
        or (heavy_pool[0] if heavy_pool else None) \
        or (d if d in bare else None) or bare[0]
    light = (d if (d in light_pool and d != heavy) else None) \
        or next((m for m in light_pool if m != heavy), None) \
        or (d if d in bare else None) or bare[0]
    return light, heavy


def resolve_role_models(base_url=None, models=None, default=None):
    """按当前 API 方案解析 (轻池模型, 重池模型)——换方案自动适配。
    优先级：① model_map 端点映射（配置显式指定，关键字匹配 base_url；
    executor 键按轻池、coder 键按重池解释，沿用旧格式）；② 显式池配置
    light_model/heavy_model（旧键 executor_model/coder_model 降级——仅在
    对应新键为空时参与，新键优先）；③ 当前方案模型表自动分类（名字含
    opus→重池，其余→轻池）；④ 硬默认。两池独立回退（只配一池不影响
    另一池自动识别）。"""
    cfg = roles_cfg()
    url = (base_url if base_url is not None else _current_base_url()).lower()
    if url:
        for key, m in (cfg.get("model_map") or {}).items():
            k = str(key).strip().lower()
            if k and k in url and isinstance(m, dict):
                li = str(m.get("light") or m.get("executor") or "").strip()
                hv = str(m.get("heavy") or m.get("coder") or "").strip()
                if li and hv:
                    return li, hv
    if models is None:
        try:
            # 惰性导入防循环（claude_harness 也 import 本模块）
            from .claude_harness import available_models as _am
            d = _am()
            models, default = d.get("models") or [], d.get("default")
        except Exception:
            models, default = [], None
    cl = str(cfg.get("light_model") or cfg.get("executor_model") or "").strip()
    ch = str(cfg.get("heavy_model") or cfg.get("coder_model") or "").strip()
    auto_l, auto_h = _pick_pool_models(models, default)
    return (cl or auto_l or "glm-5.3-flash",
            ch or auto_h or "glm-5.3")


def roles_mode(model=None):
    """主会话形态：① harness_roles.main_model 显式配置优先——按配置名过
    「除 Opus 皆轻」识别（用户声明主会话模型是什么，实测名/settings 名
    错位时兜正形态）；② 未配置回落实跑模型名识别：名字含 opus（不分
    大小写）→ strong 重模型直干；其余（flash/turbo/glm 等一切非 opus）
    → light 轻主力（直干所有活 + designer/reviewer 双重模型代理）；名字
    不可得兜 strong（不装角色、直干——与旧版空名行为一致）。"""
    try:
        m = str(roles_cfg().get("main_model") or "").strip()
    except Exception:
        m = ""
    if m:
        model = m
    if model and not _HEAVY_RE.search(str(model)):
        return "light"
    return "strong"


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
# 只读限制不动）；Bash 保留（取证纪律要求能跑的验证实际跑）。
_TOOLS_DESIGN = ("Read, Write, Edit, MultiEdit, NotebookEdit, Bash, Glob, "
                 "Grep, WebFetch, WebSearch, TodoWrite, SendMessage, "
                 "AskUserQuestion")
_TOOLS_REVIEW = ("Read, Bash, Glob, Grep, WebFetch, WebSearch, Task, "
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
    有变才写）。light → designer+reviewer（都取重模型池）；strong → 只
    reviewer（审计兜底代理）；executor/coder/dev 无条件退役清理。开关
    关闭 → 全部清理。失败静默（不拖垮会话启动）。

    目录共享原则（v2.37）：agents 目录是全局共享的（CLI 按文件名发现，
    与本工具会话无关）——只确保本形态所需文件存在且内容最新，绝不动
    其他形态的在用文件（designer.md 是 light 在用文件，strong 共存不
    清理；roundtrip 回 light 时内容有变才重写）。"""
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
    _light_m, heavy_m = resolve_role_models()
    if mode == "light":
        wanted = {
            "designer.md": _agent_md(
                "designer",
                "设计者（重模型）：只设计，绝不干活——架构/模块划分/关键决"
                "策/风险/依赖顺序的框架方案；不写代码不改文件不跑实现。需"
                "要高水平方案时派此代理，并把已知上下文尽可能带上。",
                heavy_m, _DESIGNER_BODY, tools=_TOOLS_DESIGN),
            "reviewer.md": _agent_md(
                "reviewer",
                "对抗审核（重模型）：改动交付或超审计线时派此代理审——分"
                "两档：轻审（只审 diff）／全审（取证级：需求符合性/逻辑/健"
                "壮性/安全/一致性）。只读不改，PASS/FAIL 二选一。",
                heavy_m, _REVIEWER_BODY, tools=_TOOLS_REVIEW),
        }
    else:
        # strong：主会话直干，只装审计兜底的 reviewer（designer 共存不清）
        wanted = {
            "reviewer.md": _agent_md(
                "reviewer",
                "对抗审核（重模型）：改动交付或超审计线时派此代理审——分"
                "两档：轻审（只审 diff）／全审（取证级：需求符合性/逻辑/健"
                "壮性/安全/一致性）。只读不改，PASS/FAIL 二选一。",
                heavy_m, _REVIEWER_BODY, tools=_TOOLS_REVIEW),
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
            # 另一形态的在用文件——共存不清理（v2.37 根因修复点）
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
    静默修复，审计日志可查）。light 需要 designer.md+reviewer.md；strong
    只需 reviewer.md（审计兜底代理）。"""
    if not roles_cfg()["enabled"]:
        return []
    d = _agents_dir_guard(_agents_dir())
    need = (["designer.md", "reviewer.md"]
            if roles_mode(model) == "light" else ["reviewer.md"])
    missing = [fn for fn in need if not os.path.isfile(os.path.join(d, fn))]
    install_roles_agents(model)
    if missing:
        _agents_dir_audit("self-heal(派发前自愈)",
                          "model=%s dir=%s healed=%s" % (model or "-", d, ",".join(missing)))
    return missing


def audit_limits(cfg=None):
    """审计两档线现值：(l1_max_lines, l2_max_files, l2_max_lines)。
    引导词 / 回合结算 / 事中闸三处共用本函数——数字同源，不会词里一套
    审计另一套。0 合法（最严档：l1=0 任何直改都须轻审；l2=0 任何直改都
    属大改须全审），缺键/非法回默认。纯函数不落盘（cfg 缺省读盘一次）。"""
    c = cfg if cfg is not None else roles_cfg()

    def _int(key, dflt):
        try:
            # 不用 ` or dflt` 兜底——那会把合法的 0 吞成默认
            return max(0, int(c.get(key)))
        except (TypeError, ValueError):
            return dflt
    return (_int("l1_max_lines", 100), _int("l2_max_files", 3),
            _int("l2_max_lines", 200))


def audit_verdict(lines, files, rev, cfg=None, strong=False):
    """回合结算违规判定（纯函数，claude_harness._audit_settle 调用）：
    入参为本回合累计——lines=直改行数、files=直改涉及文件数、rev=是否
    派发过 reviewer。返回违规描述列表（空=干净）；描述自带档位与可数
    依据，供警示卡/补审指令直用。判定与引导词同源（audit_limits）：
    - light：免审区（单文件且 lines≤l1）干净；轻审区（files≤l2f 且
      lines≤l2l）须 reviewer 轻审，未派=违规；超轻审线属大改——直改须
      reviewer 取证级全审，未派=违规（已派视作审过，不重复追责——
      提示性兜底）；
    - strong：只守审计线（超 l2 任一且未派 reviewer=违规；直干是设计
      常态，无轻审义务）；
    - designer 派发不计入判定：设计不产生直改、不触发审计线、也不算
      「已审」。
    兜底是提示性的：本函数只判不拦，处置（警示/续发补审）归调用方按
    audit_mode 决定。"""
    l1, l2f, l2l = audit_limits(cfg)
    viol = []
    if strong:
        if not rev and (files > l2f or lines > l2l):
            viol.append(
                "主会话直改 %d 行/%d 个文件，超过审计线（≤%d 个文件、回合"
                "累计 ≤%d 行），本回合未派 reviewer 审计" % (lines, files, l2f, l2l))
        return viol
    if not rev and (files > 1 or lines > l1):
        if files <= l2f and lines <= l2l:
            viol.append(
                "主会话直改 %d 行/%d 个文件，超过免审线（单文件 ≤%d 行）属"
                "中改，本回合未派 reviewer 轻审（只审 diff）"
                % (lines, files, l1))
        else:
            viol.append(
                "主会话直改 %d 行/%d 个文件，超过轻审线（≤%d 个文件、回合"
                "累计 ≤%d 行）属大改——须 reviewer 取证级全审，本回合未派审"
                % (lines, files, l2f, l2l))
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


def audit_gate_check(used_lines, used_files, cfg=None, reviewed=False):
    """事中闸判定（纯函数，claude_harness /audit_gate 调用）：
    (block, msg)。主会话直改累计**达到**轻审线上限（行或文件任一达线）
    且本回合尚未派过 reviewer → 拦下一次直改并指路送审；已派 reviewer
    即放行（审过开闸——直干是常态，闸只逼送审不逼停工：没有可转派的
    干活代理，硬拦到底会把唯一干活者锁死）。口径用 >=（达线即拦下一次），
    与结算的超线追责（>，audit_verdict）互补：事中闸让「超线且全程未
    送审」尽量不发生，事后审计只兜闸失效的漏网。免审/轻审区内的直改
    一律放行。"""
    _l1, l2f, l2l = audit_limits(cfg)   # 闸只守轻审线上限，l1 不参与
    if reviewed:
        return False, None
    if used_lines >= l2l or used_files >= l2f:
        return True, ("本回合直改已 %d 行/%d 个文件，达到轻审线上限（≤%d "
                      "个文件、累计 ≤%d 行）——请先用 Task 工具派 reviewer "
                      "代理审已完成的改动（对抗审核：只审不改，PASS/FAIL），"
                      "审过即可继续直改；需要方案支持可派 designer（带上全部"
                      "已知上下文）。确需放宽可在三角色配置里调整分级线。"
                      % (used_lines, used_files, l2f, l2l))
    return False, None


def roles_bridge_text(model=None):
    """角色引导词（双形态）：轻模型 → 轻主力词（主会话直干所有活 +
    designer/reviewer 双重模型代理 + 分级线嵌词）；重模型 → 直干词
    （干活者 + reviewer 审计兜底，审计线嵌词）。开关关闭一律空串。
    model 参数参与形态判定并进引导词指纹（切模型/改 main_model 配置
    自动换形态热更）。两档上限（audit_limits）以可数数字嵌进词里，
    改配置即变词（指纹热更），并明示回合结算审计——威慑前置（事前
    引导词 + 事后审计兜底）。"""
    if not roles_cfg()["enabled"]:
        return ""
    if roles_mode(model) == "light":
        cfg = roles_cfg()
        l1, l2f, l2l = audit_limits(cfg)
        # 威慑句按 audit_mode 生成——off 档不宣称「会审计」（空头威胁，
        # 模型被抓过一次空头支票后纪律反而松动）
        if str(cfg.get("audit_mode") or "auto") != "off":
            audit_note = ("harness 会在回合结束时审计你的工具调用记录——直改"
                          "行数/文件数按回合累计，切片拆小也会累计超线；超免"
                          "审线未轻审、超轻审线未全审会被自动查出并要求"
                          "补审")
        else:
            audit_note = "跳过应做的审核（轻审/全审）就答复用户属重大流程违规"
        heavy_model = resolve_role_models()[1]
        return (
            "【任务分级（你=轻快主力，直干所有活）】\n"
            "本会话是面向用户的轻快主力：日常对话直接答；编码、执行、调试"
            "全部由你亲自完成，不派干活子代理（省 token 且快）。分档上限"
            "可数，按本回合累计：\n"
            "· 杂活：问答、查文件、跑命令、环境排查、信息收集 → 你直接"
            "干。\n"
            "· 小改（免审）：单文件且本回合累计 ≤%d 行的配置/常量/文案/"
            "注释级 → 你直接改，免审。\n"
            "· 中改（轻审）：≤%d 个文件且本回合累计 ≤%d 行的真代码改动 → "
            "你直接改，交付前派 reviewer 轻审（只审 diff：逻辑/边界/一致"
            "性）。\n"
            "· 大改（全审）：超以上上限、多文件重构、架构改动、疑难 bug → "
            "仍由你实施，交付前 reviewer 取证级全审；方案没把握先派 "
            "designer 出框架方案。\n"
            "· 高风险：删数据、发布、外发、碰铁律文件（如 cmdlib.json）"
            "→ 无论谁实施都必须审核，且动手前先向用户显式确认拿到同意。\n"
            "派 designer 的纪律（它只设计不干活：输出架构/模块划分/关键决"
            "策/风险/依赖顺序）：把已知上下文尽"
            "可能带上——①目标（做什么/为什么）②背景与约束 ③已试方案及为"
            "何不行 ④相关文件+行号 ⑤验收标准。上下文给足，方案才可用。\n"
            "派 reviewer 的上下文包四要素：①目标 ②涉及文件+行号 ③已定决"
            "策（禁翻案项）④验收标准。\n"
            "两个重模型代理：designer（%s）设计、reviewer（%s）对抗审核"
            "（只审不改，PASS/FAIL 二选一）。\n"
            "流程：中改你改完 → reviewer 轻审；大改 designer 出方案 → 你"
            "实施 → reviewer 全审 → FAIL 自己修再送审，致命/严重问题清零"
            "才收 → 你消化双方结论后汇总答复用户。\n"
            "纪律（%s）：\n"
            "- 不要自行把改动判小逃审：超免审线就必须轻审、超轻审线就必须"
            "全审。\n"
            "- reviewer 判 FAIL 必须回炉重修；两边的报告都要消化后再答，"
            "不要原样转发一大坨。\n"
            "- 回合终点纪律：提交/实施完成后，你的最后一条消息必须是给用户的结论"
            "汇总（做了什么、审核结论、提交号、用户需要做什么）——用户看不到后台"
            "代理的过程，静默结束回合=交付没完成。\n"
            % (l1, l2f, l2l, heavy_model, heavy_model, audit_note)
        )
    # strong 分支：重模型主会话=干活者，自己干所有活，不派干活子代理；
    # 只保留审计兜底——回合累计直改超审计线（数字嵌词热更）触发回合
    # 结算审计（audit_verdict strong 分支：超线未派 reviewer=违规）。
    cfg = roles_cfg()
    _l1, l2f, l2l = audit_limits(cfg)
    if str(cfg.get("audit_mode") or "auto") != "off":
        audit_note = ("harness 会在回合结束时审计你的直改量（行数/文件数按"
                      "回合累计，切片拆小也会累计）——超过审计线会被自动查出"
                      "并要求派 reviewer 补审后重新汇总")
    else:
        audit_note = "大改不派 reviewer 审计就答复用户属重大流程违规"
    return (
        "【主会话直干（你=干活者）】\n"
        "本会话用重模型直接干活：需求承接、方案、编码、debug、杂活全部由你"
        "亲自完成——不派子代理干活（嵌套派发浪费且失控）；审计兜底要求的 "
        "reviewer 补审除外。\n"
        "质量纪律：\n"
        "- 动手前先想清楚：需求边界、实现路径、风险点；复杂改动先在回复里"
        "列出方案要点再实施。\n"
        "- 审计兜底（%s）：回合累计直改超过审计线（≤%d 个文件、累计 ≤%d 行）"
        "即触发审计——须派 reviewer 对抗审计（只审不改，PASS/FAIL），FAIL "
        "自己修复后复审再答复用户。\n"
        "- 改完自测通过再交；遵守项目既有代码风格与约定。\n"
        "- 回合终点纪律：完成后，最后一条消息必须是给用户的结论汇总（做了"
        "什么、自测与审核结果、用户需要做什么），不得静默结束回合。\n"
        % (audit_note, l2f, l2l)
    )
