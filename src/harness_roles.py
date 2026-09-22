# -*- coding: utf-8 -*-
"""三角色设计——harness 内置定义（v2.50）。

角色定义是 harness 的一部分，不是用户手工放的 ~/.claude/agents/*.md：
会话启动时自动把子代理定义安装到 claude 的 agents 目录（幂等：内容有变
才写，配置改了模型会同步重生成）。任何人装了本工具即得，零手工配置。

模型名存 config.json 的 harness_roles 节（executor_model / coder_model /
main_model / enabled / model_map；v2.34 增 audit_mode；v2.49 增
l1_max_lines / l2_max_files / l2_max_lines——任务分级路由的两档可数线），
换 API 方案改配置即可，不用动代码。

v2.49（2026-09-22）任务分级路由重构（用户拍板，不翻案）：轻主力形态从
「按角色二分」改为按任务复杂度五档路由——
- L0 杂活（问答/查文件/跑命令/信息收集）主会话直接干，不派发；
- L1 小改：单文件 ≤l1_max_lines 行的配置/常量/文案/注释级 → 主会话直改
  免审（原 max_free_lines=3 的「微调免审」档放大成可用的 L1）；
- L2 中改：≤l2_max_files 文件且回合累计 ≤l2_max_lines 行真代码 → 主会话
  直改 + 派 reviewer 轻审（只审 diff：逻辑/边界/一致性）；
- L3 攻坚：超 L2 上限/多文件重构/架构/疑难 bug → 派 dev 全权攻坚 +
  reviewer 取证级全审（原标准流程）；
- L4 高风险：删数据/发布/外发/碰铁律文件 → 无论谁实施必审 + 用户显式确认。
dev 同领域（同项目/模块）优先 SendMessage 续派复用会话（不冷启动）；派
dev/reviewer 固定四要素上下文包（目标/文件+行号/已定决策/验收标准）。
旧键 max_free_lines 废弃（三键取代）；审计判定抽纯函数 audit_limits /
audit_verdict / audit_gate_check，claude_harness 的回合结算与事中闸共用
同一口径（引导词 / 结算 / 闸三处数字同源）。

实测要点：agent 文件的 model 字段必须写【显式模型 ID】——别名
（opus/haiku）在这条链路上会被无视（子代理跑主链模型）。

v2.50（2026-09-22）二次大改（六项，用户五需求 + 上轮遗留）：
① 子代理禁派子代理：_TOOLS_FULL 去掉 Task——嵌套派发浪费且失控。
  SendMessage 保留：续派回报链路要用——主会话经 SendMessage 续派子代理
  会话（接收不依赖子代理自己的工具表），子代理向主会话回话也走它；
② 子代理禁 git 提交：executor/coder/dev body 加铁律条「改动一律留在
  工作区，commit/push 由主会话执行」。不做 hook 拦截——git 走 Bash 工具，
  工具级无法只拦 commit 不拦其它命令（拦整个 Bash 掐死一切命令执行；
  PreToolUse 按命令文本匹配误伤 git status/log 等合法用法），body 纪律
  条 + 说明即可；
③ 三槽全可配：配置面板/POST /roles 增第三槽 main_model（主会话模型）。
  形态判定（light/strong）改为显式配置优先——配置了 main_model 就按
  配置名过轻快词识别（实测名/settings 名错位时兜正形态），未配置回落
  实跑模型名自动识别（v2.49 原行为）；
④ strong 砍三角色分工流程（本次核心）：重模型主会话不再有
  executor/coder 派发分工——自己干所有活（编码/杂活），引导词重写为
  「你=干活者，直接改，超线会被审计」（无派发路由词、无免审线词）；
  只保留审计兜底：回合累计直改超审计线（沿用 l2_max_files/
  l2_max_lines）触发既有 auto/warn 结算审计（audit_verdict 增 strong
  形态分支：超线未自查=违规，补救=自查复核而非派 reviewer——strong
  不装任何角色文件，旧装 executor/coder 一次性迁移清理）。light 形态
  L0-L4 路由与引导词原样不动；
⑤ 工具限制收窄到审计角色：ROLE_DISALLOW/roles_disallow（strong 主会话
  结构禁权）废除——strong 主会话现在是干活者，干活角色全工具（除①的
  Task）；reviewer 只读限制原样保留（_TOOLS_REVIEW 不动）；
⑥ 上轮 reviewer 遗留：P2——POST /roles 增 l1_max_lines ≤ l2_max_lines
  交叉校验（clamp_role_limits 纯函数，超线 clamp 到 l2 并回显原因；
  选 clamp 不选 400——面板一次存三键，400 会把整次保存打回）；P1——
  SendMessage 续派计派发标记（claude_harness._audit_dispatch_role：按
  input.to 名字/带[ref]/agentId 映射三形态识别，agentId 映射由 Task
  结果回填；「worker [ref]」无名形态与跨进程 agentId 仍匹配不到，缺口
  记录在 _audit_dispatch_role docstring）。
"""
import json
import os
import re
import time

import src.app_state as _st

_ROLES_KEY = "harness_roles"
# v2.50 ⑤：ROLE_DISALLOW（"Bash,Edit,Write,WebFetch,WebSearch,Glob,Grep"）
# 与 roles_disallow() 已废除——它只作用于 strong 主会话（结构禁权逼派发），
# v2.50 起 strong 主会话=干活者要亲自干活，禁权失去意义；reviewer 的只读
# 限制走 _TOOLS_REVIEW（agent 级），与此常量无关，原样保留。

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

# 轻快模型识别（执行者级）：名字带这些词的当 executor
_LIGHT_RE = re.compile(r"flash|turbo|light|mini|fast|air|speed|lite", re.I)

_DEFAULTS = {"enabled": False,          # v2.29.3 默认关闭（用户定调：开关开启才生效）
             "executor_model": "glm-5.3-flash",
             "coder_model": "glm-5.3",
             # v2.50 ③：主会话模型槽——显式声明主会话用什么模型，形态判定
             # （light/strong）据此名过轻快词识别；空串=按实跑模型名自动识别
             "main_model": "",
             "model_map": {},
             # v2.34 light 形态审计（回合结算盘点工具调用记录，零 token）：
             "audit_mode": "auto",      # 兜底档：auto=违规自动续发补审 / warn=仅警示 / off=关
             # v2.49 任务分级路由两档可数线（旧 max_free_lines=3 废弃，三键取代）：
             "l1_max_lines": 100,       # L1 免审线：单文件且回合累计 ≤ 此行数免审
             "l2_max_files": 3,         # L2 轻审线：≤ 此文件数（且行数不超线）直改+轻审
             "l2_max_lines": 200}       # L2 轻审线：回合累计 ≤ 此行数；超任一即 L3 派 dev


def roles_cfg():
    """读角色配置（缺字段兜默认）。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        r = d.get(_ROLES_KEY)
        if isinstance(r, dict):
            return {**_DEFAULTS,
                    **{k: r.get(k, v) for k, v in _DEFAULTS.items()}}
    except Exception:
        pass
    return dict(_DEFAULTS)


_EXECUTOR_BODY = """你是「执行者」——三角色设计里的干活担当（轻快模型，快而省）。

职责（超出范围的请求不要自行扩大，如实回报给派发者）：
- 信息收集：查文件、搜代码、读日志、检索资料
- 环境与数据排查：复现现象、收集证据、整理事实
- debug：按派发者给的线索实际跑命令、定位问题、汇报根因
- 派发者明确指定的照做类小修改

工作方式：
- 结论先行：返回第一句就是答案/结果，再给证据（文件:行号、命令输出摘要）
- 只报告事实与执行结果，不做方案决策
- 线索不足就列出你的理解请派发者确认，不瞎猜着干

铁律（v2.50）：改动一律留在工作区——git commit/push 由主会话执行，你没有
提交权（不要跑 git commit / git push；git 经 Bash 执行，工具级拦不住，靠
本条纪律）。
"""

_CODER_BODY = """你是「编程者」——三角色设计里的攻坚担当（高级模型）。

职责：
- 复杂功能实现、架构设计与改动、疑难 bug 修复
- 产出必须可运行：改完自测通过再交
- 遵守项目既有代码风格与约定

工作方式：
- 交付时返回：改动摘要（文件+要点）、关键决策及理由、自测结果
- 不改需求边界；发现需求矛盾停下来向派发者说明，不自行拍板

铁律（v2.50）：改动一律留在工作区——git commit/push 由主会话执行，你没有
提交权（不要跑 git commit / git push；git 经 Bash 执行，工具级拦不住，靠
本条纪律）。
"""

_DESIGNER_BODY = """你是「设计者」——轻主力形态里的设计担当（高级模型）。

职责（只做分析与设计，不动手改代码）：
- 需求承接：把含糊/复杂的需求拆解清楚，补齐边界与异常场景
- 方案设计：给出可执行的实现方案——改哪些文件、步骤顺序、风险点
- 疑难诊断：bug 根因分析、架构权衡、技术选型比较

工作方式：
- 产出结构化：结论先行 → 方案（步骤化、到文件级）→ 风险与验证方法
- 你不改代码：实施由派发方（轻快主力会话）执行，方案要细到它能照做
- 信息不足时明确列出假设，不要含糊带过
"""

# v2.30.4：designer 并入 coder 成 dev——设计/实施一个上下文打通，消灭
# 无状态子代理之间的方案交接损耗（用户定调；designer.md 保留仅为兼容
# 历史会话的引用，新装不再写它）。
_DEV_BODY = """你是「开发」——轻主力形态的攻坚担当（高级模型），设计与实施一个上下文打通。

职责：
- 方案思考：动手前先想清楚——需求边界、实现路径、风险点；复杂改动先在
  回复里列出方案要点再实施
- 编码：功能实现、多文件改动、架构调整
- debug：疑难 bug 定位与修复——复现→假设→验证→修复的完整循环自己走完
- 自测：交付前必须验证可运行（跑相关命令/测试），并自查一遍改动

工作方式：
- 交付时返回：改动摘要（文件+要点）、关键决策及理由、自测结果
- 实施中发现方案有硬伤：就地调整并在交付说明里讲清，不硬掰原方案
- 不改需求边界；发现需求矛盾停下来向派发者说明，不自行拍板
- 遵守项目既有代码风格与约定
- 续派协作（v2.49）：同领域（同项目/同模块）的后续任务会经 SendMessage
  续派到本会话——跨任务记住读过的代码与已定决策，不重复冷启动重读；
  收到续派先对照上文判断是延续还是换了领域，新领域任务如实说明并建议
  派发方另开新会话

铁律（v2.50）：改动一律留在工作区——git commit/push 由主会话执行，你没有
提交权（不要跑 git commit / git push；git 经 Bash 执行，工具级拦不住，靠
本条纪律）。
"""

_REVIEWER_BODY = """你是「审核」——对抗性代码审核员（高级模型）。唯一职责：证明这份改动有问题。

立场：假定代码是错的。你的价值在于找出问题，不在于肯定代码。真找不到
问题时必须说清查过什么、怎么取证的，不许敷衍放行。

审档两形（v2.49，派发方在任务里声明；未声明按全审）：
- 轻审（L2 中改）：只审 diff——逻辑正确性、边界条件、与周边代码一致性
  三个维度，不重建全项目上下文，快速给结论（同样只审不改）。
- 全审（L3 攻坚）：取证级——下方全部维度逐一过。

审查维度（对每处改动逐一过；轻审只取带☆的三项）：
- 需求符合性：对照任务描述逐条核对——漏做、做偏、做多了都算问题
- 逻辑正确性☆：边界条件、空值/越界、错误默认值、分支遗漏
- 健壮性：异常路径、失败处理、资源泄漏、并发/竞态
- 安全性：注入、路径拼接、越权、敏感信息泄露
- 一致性☆：与项目既有风格约定冲突、重复造轮子、破坏既有行为

取证纪律（全审全额执行；轻审可缩至 diff 相关文件的对应段落）：
- 必须 Read 相关文件核对实际代码，不能只信交付报告的自述
- 能跑的验证（命令/测试/编译）要实际跑，跑不了的注明原因
- 只审不改：发现问题报告，不动手修（修复归 dev 或主会话自查）

结论格式（严格二选一）：
PASS —— 仅当穷尽该档维度仍未发现问题；列出已查维度与取证动作
FAIL —— 每个问题一条：文件:行号、问题描述、严重级（致命/严重/一般）、
        修复建议；致命/严重问题未解决前不许改口 PASS
"""


def update_roles_cfg(patch):
    """v2.34：merge 写角色配置（只动 patch 里出现的键，其余键保留）。返回
    (ok, err)。生效路径与开关一致：模型槽（v2.50 起含 main_model 主会话
    槽——形态翻转即换词）/分级线（l1_max_lines 等，v2.49 取代
    max_free_lines）出现在引导词里 → 下条消息前的指纹热更自动换词
    重启 + agents 重生成；audit_mode 在回合结算时读盘，即时生效。enabled
    关闭即清理 agents（残留定义会被 CLI 自动发现）。"""
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
        # 在开关关闭后仍自发派发 executor/coder（违背「关闭=回到普通」）
        _uninstall_roles_agents()
    return True, None


def set_roles_enabled(enabled):
    """写开关（v2.34 起转调 update_roles_cfg 的 merge 语义：只动 enabled，
    其余键保留）。改完即生效——角色词在引导词指纹里，下条消息发送前的
    指纹热更会自动 kill+resume 换词重启（含/不含结构禁权），已有会话
    无需重建。"""
    return update_roles_cfg({"enabled": bool(enabled)})


def _current_base_url():
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = (json.load(f).get("env") or {})
        return (env.get("ANTHROPIC_BASE_URL") or "").strip()
    except Exception:
        return ""


def _pick_role_models(models, default):
    """从当前方案模型表自动分类：轻快模型（flash/turbo/light 类）→执行者；
    其余取默认优先（无默认取首个非轻快）→编程者。模型名带 [1M] 类窗口
    后缀会被剥离（agent 的 model 字段必须裸 ID）。返回 (ex, co)，识别
    不出返回 (None, None)。"""
    bare = []
    for m in models or []:
        b = str(m).split("[")[0].strip()
        if b and b not in bare:
            bare.append(b)
    if not bare:
        return None, None
    d = str(default or "").split("[")[0].strip()
    ex = next((m for m in bare if _LIGHT_RE.search(m)), None)
    rest = [m for m in bare if m != ex]
    co = d if d in rest else (rest[0] if rest else None)
    if not ex:
        ex = co       # 方案里没有轻快模型：执行者与编程者同级
    if not co:
        co = ex       # 方案只有一个模型：两角色共用
    return ex, co


def resolve_role_models(base_url=None, models=None, default=None):
    """按当前 API 方案解析 (executor_model, coder_model)——换方案自动适配。
    三级：① model_map 端点映射（配置显式指定，含关键字匹配 base_url）；
    ② 当前方案模型表自动识别（settings 的模型映射，轻快→执行者/其余→
    编程者）；③ executor_model/coder_model 配置兜底。"""
    cfg = roles_cfg()
    url = (base_url if base_url is not None else _current_base_url()).lower()
    if url:
        for key, m in (cfg.get("model_map") or {}).items():
            k = str(key).strip().lower()
            if k and k in url and isinstance(m, dict):
                ex = str(m.get("executor") or "").strip()
                co = str(m.get("coder") or "").strip()
                if ex and co:
                    return ex, co
    if models is None:
        try:
            # 惰性导入防循环（claude_harness 也 import 本模块）
            from .claude_harness import available_models as _am
            d = _am()
            models, default = d.get("models") or [], d.get("default")
        except Exception:
            models, default = [], None
    ex, co = _pick_role_models(models, default)
    if ex and co:
        return ex, co
    return cfg["executor_model"], cfg["coder_model"]


def roles_mode(model=None):
    """主会话形态（v2.30.2 双形态；v2.50 判定源改造）：① harness_roles.
    main_model 显式配置优先——按配置名过轻快词识别（用户声明主会话模型
    是什么，实测名/settings 名错位时兜正形态）；② 未配置回落实跑模型名
    自动识别。带轻快词（flash/turbo/…）→ "light" 轻主力——L0-L4 任务
    分级路由（v2.49，原样）；其余 → "strong" 重模型直干（v2.50：主会话
    自己干所有活不派发，超审计线由回合结算审计兜底）。"""
    try:
        m = str(roles_cfg().get("main_model") or "").strip()
    except Exception:
        m = ""
    if m:
        model = m
    if model and _LIGHT_RE.search(str(model).lower()):
        return "light"
    return "strong"


def _agent_md(name, description, model, body, tools=None):
    """v2.46：显式声明 tools 清单——实测省略时新版 CLI（2.1.278）给子代理
    的默认工具集**不含文件编辑类**（dev 实锤「Edit 不在可调用清单」，被迫
    用 Bash 脚本绕行改文件）。角色按定位显式给全，防默认集变动再翻车。
    tools 接受逗号串（_TOOLS_* 常量）或列表。"""
    t = ("\ntools: %s" % (", ".join(tools) if not isinstance(tools, str)
                          else tools)) if tools else ""
    return ("---\nname: %s\ndescription: %s\nmodel: %s%s\n---\n%s"
            % (name, description, model, t, body))


# 角色工具清单：干活角色（dev/coder/executor）全集（含编辑——改代码是
# 它们的核心职责）。v2.50 ①：去掉 Task——子代理禁派子代理（嵌套派发
# 浪费且失控）；SendMessage 保留——续派回报链路要用（主会话经它续派本
# 会话，接收不依赖本表；子代理向主会话回话也走它）。
# reviewer 定位「只审不改」——排除 Write/Edit/MultiEdit/NotebookEdit
# （v2.50 ⑤：此只读限制原样保留，Task 也在 reviewer 清单里保留不动）。
_TOOLS_FULL = ("Read, Write, Edit, MultiEdit, NotebookEdit, Bash, Glob, "
               "Grep, WebFetch, WebSearch, TodoWrite, SendMessage, "
               "AskUserQuestion")
_TOOLS_REVIEW = ("Read, Bash, Glob, Grep, WebFetch, WebSearch, Task, "
                 "TodoWrite, SendMessage, AskUserQuestion")


# v2.50 ④：_agent_files（executor/coder 两个 agent 文件的生成器）已删——
# strong 砍分工后两形态都不再装这两个代理（executor/coder 正文 body 保留
# 在上方仅供历史版本已装文件的对照，不再生成）。


_SELF_AGENTS = ("executor.md", "coder.md", "designer.md",
                "dev.md", "reviewer.md")   # 本工具管理的角色文件（designer 已并
                                           # 入 dev；executor/coder 随 strong 分工
                                           # 一起于 v2.50 退役——都保留在清单里
                                           # 只为清理旧装）


def _uninstall_roles_agents():
    """删除本工具管理的角色文件（只动 _SELF_AGENTS 自有名，用户自建
    代理不碰）。CLI 自动发现 ~/.claude/agents/ 下的代理——关闭开关若不
    清理，模型仍可能自发派发 Task 给 executor/coder，违背「关闭=回到
    普通」的语义。失败静默。
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
    有变才写）。light → dev+reviewer（v2.30.4：designer 并入 dev 一个上下
    文打通，新增 reviewer 对抗审核）；strong → 不装任何角色（v2.50 ④：
    重模型主会话自己干所有活，砍派发分工）。开关关闭 → 全部清理（残留的
    agent 定义会被 CLI 自动发现，模型在关闭后仍可能自发派发）。失败静默
    （不拖垮会话启动）。

    v2.37（P0+ 根治 a）【多形态并存与目录共享】：agents 目录是**全局共享**
    的（CLI 按文件名发现，与本工具会话无关）——**只确保本形态所需文件存在
    且内容最新，绝不动其他形态的在用文件**（dev/reviewer）。v2.50 起
    executor/coder 两形态都不再使用（strong 砍分工、light 本就不装）——与
    designer.md 同款一次性迁移清理（残留会被 CLI 发现、诱导已无分工设计的
    strong 主会话自发派发）。"""
    cfg = roles_cfg()
    if not cfg["enabled"]:
        _uninstall_roles_agents()
        return
    d = _agents_dir_guard(_agents_dir())
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return
    # 废弃名：一次性迁移清理（与形态无关）——designer 并入 dev（v2.30.4）；
    # executor/coder 随 strong 分工一起退役（v2.50 ④，无任何形态在用）
    _obsolete = ("designer.md", "executor.md", "coder.md")
    if roles_mode(model) == "light":
        _ex_model, co_model = resolve_role_models()
        # 轻主力形态：dev 设计+编码+debug 打通、reviewer 对抗审核——都配
        # 强模型（coder 槽）；杂活由主会话自己干，executor 不装（主会话即是）。
        wanted = {
            "dev.md": _agent_md(
                "dev",
                "开发（高级模型）：编码/debug/方案思考一个上下文打通——功能"
                "实现、多文件改动、bug 修复都派此代理，自测通过再交。",
                co_model, _DEV_BODY, tools=_TOOLS_FULL),
            "reviewer.md": _agent_md(
                "reviewer",
                "对抗审核（高级模型）：改动交付后派此代理审——分两档：L2 中"
                "改轻审（只审 diff）／L3 攻坚全审（取证级，需求符合性/逻辑/"
                "健壮性/安全/一致性）。只审不改，PASS/FAIL 二选一。",
                co_model, _REVIEWER_BODY, tools=_TOOLS_REVIEW),
        }
    else:
        wanted = {}     # v2.50 ④：strong 主会话直干，不装角色
    wrote = []
    for fn in _SELF_AGENTS:
        p = os.path.join(d, fn)
        if fn in _obsolete:
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    wrote.append("%s(已退役,删)" % fn)
            except Exception:
                pass
            continue
        if fn not in wanted:
            # 另一形态的在用文件——共存不清理（v2.37 P0+ 根因修复点）
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
        "install(%s)" % ("light" if roles_mode(model) == "light" else "strong"),
        "model=%s dir=%s wrote=%s" % (model or "-", d, ",".join(wrote) or "-(已是最新)"))


def ensure_roles_ready(model=None):
    """v2.37（P0+）派发前自愈：Task/SendMessage 派发前调用——幂等重装本形态
    角色定义（install 有变才写，成本可忽略），兜住一切上游删除路径（旧版
    互清/测试误清/人工误删），保证派发瞬间定义必在。返回安装前**缺失**的
    期望文件名清单——非空=发生过自愈，调用方应红卡告警（陈旧内容由 install
    静默修复，审计日志可查）。v2.50 ④：strong 形态无角色定义可自愈——
    空转返回 []（退役文件的清理由 install 的一次性迁移做）。"""
    if not roles_cfg()["enabled"]:
        return []
    if roles_mode(model) != "light":
        return []
    d = _agents_dir_guard(_agents_dir())
    need = ["dev.md", "reviewer.md"]
    missing = [fn for fn in need if not os.path.isfile(os.path.join(d, fn))]
    install_roles_agents(model)
    if missing:
        _agents_dir_audit("self-heal(派发前自愈)",
                          "model=%s dir=%s healed=%s" % (model or "-", d, ",".join(missing)))
    return missing


def audit_limits(cfg=None):
    """v2.49 审计两档线现值：(l1_max_lines, l2_max_files, l2_max_lines)。
    引导词 / 回合结算 / 事中闸三处共用本函数——数字同源，不会词里一套
    审计另一套。0 合法（最严档：l1=0 任何直改都须轻审；l2=0 任何直改都
    属 L3 须派 dev），缺键/非法回默认。纯函数不落盘（cfg 缺省读盘一次）。"""
    c = cfg if cfg is not None else roles_cfg()

    def _int(key, dflt):
        try:
            # 不用 ` or dflt` 兜底——那会把合法的 0 吞成默认
            return max(0, int(c.get(key)))
        except (TypeError, ValueError):
            return dflt
    return (_int("l1_max_lines", 100), _int("l2_max_files", 3),
            _int("l2_max_lines", 200))


def audit_verdict(lines, files, dev, rev, cfg=None, strong=False):
    """v2.49 回合结算违规判定（纯函数，claude_harness._audit_settle 调用）：
    入参为本回合累计——lines=直改行数、files=直改涉及文件数、dev/rev=是否
    派发过 dev/reviewer。返回违规描述列表（空=干净）；描述自带档位与可数
    依据，供警示卡/补审指令直用。判定与引导词同源（audit_limits）：
    - L1 免审区（单文件且 lines≤l1）→ 无需审；
    - L2 轻审区（files≤l2f 且 lines≤l2l）→ 须 reviewer 轻审，未派=违规；
    - 超 L2 → 属 L3 攻坚（应派 dev 实施+reviewer 全审），主会话直改且
      未派审=违规（已派 reviewer 视作审过，不重复追责——提示性兜底）；
    - dev 已派但无 reviewer → 违规（v2.34 原规则保留）。
    v2.50 ④：strong=True 走 strong 形态分支——主会话直干是设计常态，只守
    L2 审计线（超线须自查复核，无 reviewer 轻审义务、dev 派发不追责）。
    兜底是提示性的：本函数只判不拦，处置（警示/续发补审）归调用方按
    audit_mode 决定。"""
    l1, l2f, l2l = audit_limits(cfg)
    viol = []
    if strong:
        if not rev and (files > l2f or lines > l2l):
            viol.append(
                "主会话直改 %d 行/%d 个文件，超过审计线（≤%d 个文件、回合"
                "累计 ≤%d 行），本回合未自查复核" % (lines, files, l2f, l2l))
        return viol
    if not rev and (files > 1 or lines > l1):
        if files <= l2f and lines <= l2l:
            viol.append(
                "主会话直改 %d 行/%d 个文件，超过免审线（单文件 ≤%d 行）属 "
                "L2 中改，本回合未派 reviewer 轻审（只审 diff）"
                % (lines, files, l1))
        else:
            viol.append(
                "主会话直改 %d 行/%d 个文件，超过轻审线（≤%d 个文件、回合"
                "累计 ≤%d 行）属 L3 攻坚——应派 dev 实施+reviewer 取证级全审，"
                "却由主会话直改且未派审" % (lines, files, l2f, l2l))
    if dev and not rev:
        viol.append("已派 dev 交付但未派 reviewer 对抗审核")
    return viol


def clamp_role_limits(patch, cfg=None):
    """v2.50（P2）l1_max_lines ≤ l2_max_lines 交叉校验（clamp 档）。
    返回 (new_patch, notes)：new_patch 在 patch 基础上补上被钳的键（原键
    值替换），notes 为 [{"key","from","to","reason"}]（空=无需钳）。
    选 clamp 不选 400：配置面板一次保存三键，用户单调 l2 低于 l1 时 400
    会把整次保存打回（其它合法键也白存），clamp + 回显原因更可用——
    POST /roles 把 notes 原样带回前端提示。
    只向下钳 l1 不动 l2：l2 是审计主线（闸与结算都守它），l1 只是免审区
    上沿，语义上 l1 ≤ l2l 恒成立（L1 区是 L2 区的子集）。未出现在 patch
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
                       "线会让 L1 免审区吞掉 L2 轻审区），已自动收紧至 "
                       "l2_max_lines=%d" % l2l)})
    return out, notes


def audit_gate_check(used_lines, used_files, cfg=None):
    """v2.49 事中闸判定（纯函数，claude_harness /audit_gate 调用）：
    (block, msg)。主会话直改累计**达到**轻审线上限（行或文件任一达线）→
    拦下一次直改并指路派 dev——继续手改就属 L3 攻坚，该转派发。口径用
    >=（达线即拦下一次），与结算的「超线追责」（>，audit_verdict）互补：
    事中闸让超线根本不发生，事后审计只兜闸失效的漏网。L1/L2 内的直改
    （新路由的主体）一律放行——闸只守 L2 上限，不再掐 3 行微调。"""
    _l1, l2f, l2l = audit_limits(cfg)   # 闸只守 L2 上限，l1 不参与
    if used_lines >= l2l or used_files >= l2f:
        return True, ("本回合直改已 %d 行/%d 个文件，达到轻审线上限（≤%d "
                      "个文件、累计 ≤%d 行）——再继续手改属 L3 攻坚，请用 "
                      "Task 工具派 dev 代理实施；已完成的 L2 改动交付前记得"
                      "派 reviewer 轻审。确需放宽可在三角色配置里调整分级线。"
                      % (used_lines, used_files, l2f, l2l))
    return False, None


def roles_bridge_text(model=None):
    """角色引导词（v2.30.2 双形态）：轻快模型 → 轻主力词；重模型 →
    v2.50 起为「主会话直干」词（干活者+审计兜底，砍掉决策者/派发分工与
    结构禁权）。开关关闭一律空串。model 参数参与形态判定并进引导词指纹
    （切模型/改 main_model 配置自动换形态热更）。v2.49：light 词为任务
    分级路由（L0-L4，用户拍板）——大部分中小编码回到持有上下文的主会话
    直改，dev 只接 L3 攻坚且同领域续派复用会话；两档上限（audit_limits）
    以可数数字嵌进词里，改配置即变词（指纹热更），并明示回合结算审计——
    威慑前置（事前引导词 + 事后审计兜底，用户定调）。v2.50：strong 词
    同样嵌审计线数字（改配置即热更），但无派发路由词、无免审线词。"""
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
                          "审线未轻审、超轻审线未走 dev 会被自动查出并要求"
                          "补审")
        else:
            audit_note = "跳过应做的审核（轻审/全审）就答复用户属重大流程违规"
        dev_model = resolve_role_models()[1]
        return (
            "【任务分级路由（你=轻快主力）】\n"
            "本会话是面向用户的轻快主力：日常对话直接答；任务按复杂度分级"
            "路由——大部分中小编码由持有上下文的你直接做，不派发（省 token "
            "且快）。分档上限可数，按本回合累计：\n"
            "· L0 杂活：问答、查文件、跑命令、环境排查、信息收集 → 你直接"
            "干，不派发。\n"
            "· L1 小改（免审）：单文件且本回合累计 ≤%d 行的配置/常量/文案/"
            "注释级改动 → 你直接改，不需审核。\n"
            "· L2 中改（轻审）：≤%d 个文件且本回合累计 ≤%d 行的真代码改动 "
            "→ 你直接改，交付前派 reviewer 轻审（只审 diff：逻辑/边界/一致"
            "性，不重建全项目上下文）。\n"
            "· L3 攻坚（全审）：超 L2 上限、多文件重构、架构改动、疑难 bug、"
            "需大量试错跑测试 → 用 Task 派 dev 全权攻坚，交付后 reviewer 取"
            "证级全审。\n"
            "· L4 高风险：删数据、发布、外发、碰铁律文件（如 cmdlib.json）"
            "→ 无论谁实施（你或 dev）都必须审核，且动手前先向用户显式确认"
            "拿到同意。\n"
            "dev 续派策略：同领域（同项目/同模块）的后续任务优先用 "
            "SendMessage 续派同一 dev 会话——它记得读过的代码与已定决策，不"
            "冷启动；换了任务领域才用 Task 新开。\n"
            "派 dev/reviewer 的上下文包固定四要素：①目标（做什么/为什么）"
            "②涉及文件+行号 ③已定决策（禁翻案项）④验收标准。\n"
            "两个强模型代理：dev（%s）攻坚、reviewer（%s）对抗审核（只审不"
            "改，PASS/FAIL 二选一）。\n"
            "流程：L2 你改完 → reviewer 轻审 → FAIL 自己修再送审；L3 dev "
            "实现 → reviewer 全审 → FAIL 回 dev 修 → 复审，致命/严重问题"
            "清零才收 → 你消化双方结论后汇总答复用户。\n"
            "纪律（%s）：\n"
            "- 不要自行把改动判小逃审：超 L1 就必须轻审、超 L2 就必须走 "
            "dev。\n"
            "- reviewer 判 FAIL 必须回炉重修；两边的报告都要消化后再答，"
            "不要原样转发一大坨。\n"
            "- 回合终点纪律：提交/实施完成后，你的最后一条消息必须是给用户的结论"
            "汇总（做了什么、审核结论、提交号、用户需要做什么）——用户看不到后台"
            "代理的过程，静默结束回合=交付没完成。\n"
            % (l1, l2f, l2l, dev_model, dev_model, audit_note)
        )
    # v2.50 ④：strong 分支重写——重模型主会话=干活者，砍掉 v2.29 以来的
    # 决策者/executor/coder 派发分工（嵌套派发浪费且失控）。只保留审计
    # 兜底：回合累计直改超审计线（audit_limits 的 L2 档，数字嵌词热更）
    # 触发回合结算审计（audit_verdict strong 分支：超线未自查=违规）。
    # 无派发路由词、无免审线词（设计常态就是直接改）。
    cfg = roles_cfg()
    _l1, l2f, l2l = audit_limits(cfg)
    if str(cfg.get("audit_mode") or "auto") != "off":
        audit_note = ("harness 会在回合结束时审计你的直改量（行数/文件数按"
                      "回合累计，切片拆小也会累计）——超过审计线会被自动查出"
                      "并要求自查复核后重新汇总")
    else:
        audit_note = "大改不做自查复核就答复用户属重大流程违规"
    return (
        "【主会话直干（你=干活者）】\n"
        "本会话用重模型直接干活：需求承接、方案、编码、debug、杂活全部由你"
        "亲自完成——不要用工具起子代理干活，也不要把活转给别的会话（嵌套"
        "派发浪费且失控）。\n"
        "质量纪律：\n"
        "- 动手前先想清楚：需求边界、实现路径、风险点；复杂改动先在回复里"
        "列出方案要点再实施。\n"
        "- 审计兜底（%s）：回合累计直改超过审计线（≤%d 个文件、累计 ≤%d 行）"
        "即触发审计——须自查复核：逐文件核对逻辑/边界/一致性，能跑的验证"
        "（命令/测试/编译）实际跑，再给用户汇总自查结论。\n"
        "- 改完自测通过再交；遵守项目既有代码风格与约定。\n"
        "- 回合终点纪律：完成后，最后一条消息必须是给用户的结论汇总（做了"
        "什么、自测与自查结果、用户需要做什么），不得静默结束回合。\n"
        % (audit_note, l2f, l2l)
    )
