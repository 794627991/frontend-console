# -*- coding: utf-8 -*-
"""三角色设计——harness 内置定义（v2.29.1）。

角色定义是 harness 的一部分，不是用户手工放的 ~/.claude/agents/*.md：
会话启动时自动把 executor（执行者）/coder（编程者）两个子代理定义安装
到 claude 的 agents 目录（幂等：内容有变才写，配置改了模型会同步重生成）。
任何人装了本工具即得三角色，零手工配置。

模型名存 config.json 的 harness_roles 节（executor_model / coder_model /
enabled / model_map；v2.34 增 audit_mode / max_free_lines——light 形态
回合结算审计的兜底档与直改免审线），换 API 方案改配置即可，不用动代码。

实测要点：agent 文件的 model 字段必须写【显式模型 ID】——别名
（opus/haiku）在这条链路上会被无视（子代理跑主链模型）。
"""
import json
import os
import re
import time

import src.app_state as _st

_ROLES_KEY = "harness_roles"
ROLE_DISALLOW = "Bash,Edit,Write,WebFetch,WebSearch,Glob,Grep"

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
             "model_map": {},
             # v2.34 light 形态审计（回合结算盘点工具调用记录，零 token）：
             "audit_mode": "auto",      # 兜底档：auto=违规自动续发补审 / warn=仅警示 / off=关
             "max_free_lines": 3}       # 直改免审线：主会话单回合累计 Edit/Write 行数上限


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
"""

_CODER_BODY = """你是「编程者」——三角色设计里的攻坚担当（高级模型）。

职责：
- 复杂功能实现、架构设计与改动、疑难 bug 修复
- 产出必须可运行：改完自测通过再交
- 遵守项目既有代码风格与约定

工作方式：
- 交付时返回：改动摘要（文件+要点）、关键决策及理由、自测结果
- 不改需求边界；发现需求矛盾停下来向派发者说明，不自行拍板
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
"""

_REVIEWER_BODY = """你是「审核」——对抗性代码审核员（高级模型）。唯一职责：证明这份改动有问题。

立场：假定代码是错的。你的价值在于找出问题，不在于肯定代码。真找不到
问题时必须说清查过什么、怎么取证的，不许敷衍放行。

审查维度（对每处改动逐一过）：
- 需求符合性：对照任务描述逐条核对——漏做、做偏、做多了都算问题
- 逻辑正确性：边界条件、空值/越界、错误默认值、分支遗漏
- 健壮性：异常路径、失败处理、资源泄漏、并发/竞态
- 安全性：注入、路径拼接、越权、敏感信息泄露
- 一致性：与项目既有风格约定冲突、重复造轮子、破坏既有行为

取证纪律：
- 必须 Read 相关文件核对实际代码，不能只信交付报告的自述
- 能跑的验证（命令/测试/编译）要实际跑，跑不了的注明原因
- 只审不改：发现问题报告，不动手修（修复归 dev）

结论格式（严格二选一）：
PASS —— 仅当穷尽上述维度仍未发现问题；列出已查维度与取证动作
FAIL —— 每个问题一条：文件:行号、问题描述、严重级（致命/严重/一般）、
        修复建议；致命/严重问题未解决前不许改口 PASS
"""


def update_roles_cfg(patch):
    """v2.34：merge 写角色配置（只动 patch 里出现的键，其余键保留）。返回
    (ok, err)。生效路径与开关一致：模型槽/免审线出现在引导词里 → 下条消息
    前的指纹热更自动换词重启 + agents 重生成；audit_mode 在回合结算时读盘，
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
    """主会话形态（v2.30.2 双形态）：模型名带轻快词（flash/turbo/…）→
    "light"——轻主力模式：主会话自己干杂活+日常对话，强模型挂 designer
    代理承接需求分析/方案设计；其余 → "strong"——决策者模式：主会话只
    派发审核，executor/coder 干活（结构禁权）。"""
    if model and _LIGHT_RE.search(str(model).lower()):
        return "light"
    return "strong"


def _agent_md(name, description, model, body):
    return ("---\nname: %s\ndescription: %s\nmodel: %s\n---\n%s"
            % (name, description, model, body))


def _agent_files(ex_model, co_model):
    return {
        "executor.md": _agent_md(
            "executor",
            "执行者：信息收集、搜代码查日志、环境排查、跑命令、debug 定位、"
            "机械杂活。决策者派发的执行类任务一律用此代理。",
            ex_model, _EXECUTOR_BODY),
        "coder.md": _agent_md(
            "coder",
            "编程者（高级模型）：编码攻坚——复杂功能实现、架构改动、疑难 "
            "bug 修复。高难度开发任务用此代理。",
            co_model, _CODER_BODY),
    }


_SELF_AGENTS = ("executor.md", "coder.md", "designer.md",
                "dev.md", "reviewer.md")   # 本工具管理的角色文件（designer 已并
                                           # 入 dev，保留在清单里只为清理旧装）


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
    有变才写）。strong → executor+coder；light → dev+reviewer（v2.30.4：
    designer 并入 dev 一个上下文打通，新增 reviewer 对抗审核——用户定调
    「设计实施分离的交接损耗大于收益，但对抗审核很关键」）。开关关闭 →
    全部清理（残留的 agent 定义会被 CLI 自动发现，模型在关闭后仍可能
    自发派发）。失败静默（不拖垮会话启动）。

    v2.37（P0+ 根治 a）【多形态并存与目录共享】：agents 目录是**全局共享**
    的（CLI 按文件名发现，与本工具会话无关），而强/轻模型会话在用户环境
    常并存——旧实现「按本会话形态互斥清理」会删掉并存会话正需要的另一套
    角色文件（实测：任一会话启动/热更后，另一形态会话派发找不到
    subagent_type 定义 → CLI 回落通用代理跑主链轻模型，强模型分级整个
    落空）。新语义：**只确保本形态所需文件存在且内容最新，绝不动其他形态
    的文件**（executor/coder/dev/reviewer 四名不冲突，允许共存）；唯一例外
    是废弃名 designer.md（一次性迁移清理，v2.30.4 并入 dev）。"""
    cfg = roles_cfg()
    if not cfg["enabled"]:
        _uninstall_roles_agents()
        return
    d = _agents_dir_guard(_agents_dir())
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return
    if roles_mode(model) == "light":
        ex_model, co_model = resolve_role_models()
        # 轻主力形态：dev 设计+编码+debug 打通、reviewer 对抗审核——都配
        # 强模型（coder 槽）；杂活由主会话自己干，executor 不装（主会话即是）。
        wanted = {
            "dev.md": _agent_md(
                "dev",
                "开发（高级模型）：编码/debug/方案思考一个上下文打通——功能"
                "实现、多文件改动、bug 修复都派此代理，自测通过再交。",
                co_model, _DEV_BODY),
            "reviewer.md": _agent_md(
                "reviewer",
                "对抗审核（高级模型）：开发交付后必须派此代理审改动——专门"
                "挑毛病（需求符合性/逻辑/健壮性/安全/一致性），只审不改，"
                "PASS/FAIL 二选一。",
                co_model, _REVIEWER_BODY),
        }
    else:
        ex_model, co_model = resolve_role_models()
        wanted = _agent_files(ex_model, co_model)
    wrote = []
    for fn in _SELF_AGENTS:
        p = os.path.join(d, fn)
        if fn == "designer.md":
            # 废弃名：一次性迁移清理（并入 dev），与形态无关
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    wrote.append("designer.md(已废弃,删)")
            except Exception:
                pass
            continue
        if fn not in wanted:
            # 另一形态的文件——共存不清理（v2.37 P0+ 根因修复点）
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
    静默修复，审计日志可查）。"""
    if not roles_cfg()["enabled"]:
        return []
    d = _agents_dir_guard(_agents_dir())
    need = ["dev.md", "reviewer.md"] if roles_mode(model) == "light" \
        else ["executor.md", "coder.md"]
    missing = [fn for fn in need if not os.path.isfile(os.path.join(d, fn))]
    install_roles_agents(model)
    if missing:
        _agents_dir_audit("self-heal(派发前自愈)",
                          "model=%s dir=%s healed=%s" % (model or "-", d, ",".join(missing)))
    return missing


def roles_disallow(model=None):
    """结构禁权表：仅决策者形态（strong）返回禁权清单——逼主会话派发；
    轻主力形态（light）返回空串——轻模型要亲自干杂活，工具不能禁。"""
    if not roles_cfg()["enabled"]:
        return ""
    return ROLE_DISALLOW if roles_mode(model) == "strong" else ""


def roles_bridge_text(model=None):
    """角色引导词（v2.30.2 双形态）：主会话强模型 → 决策者词（只派发审核，
    配结构禁权）；轻快模型 → 轻主力词（杂活/日常对话自己干，设计类思考派
    designer 强模型代理，无禁权）。开关关闭一律空串。model 参数参与形态
    判定并进引导词指纹（切模型自动换形态热更）。v2.34：light 词的免审判据
    从「一行级微调」改为可数规则（≤max_free_lines 行），并明示回合结算
    审计——威慑前置（事前引导词 + 事后审计兜底，用户定调）。"""
    if not roles_cfg()["enabled"]:
        return ""
    if roles_mode(model) == "light":
        cfg = roles_cfg()
        try:
            # 不用 `or 3` 兜底——0 是合法免审线（最严档：任何直改都违规）
            max_free = max(0, int(cfg.get("max_free_lines")))
        except (TypeError, ValueError):
            max_free = 3
        # 威慑句按 audit_mode 生成——off 档不宣称「会审计」（空头威胁，
        # 模型被抓过一次空头支票后纪律反而松动）
        if str(cfg.get("audit_mode") or "auto") != "off":
            audit_note = ("harness 会在回合结束时审计你的工具调用记录——直改"
                          "行数按回合累计，切片拆小也会累计超线；超线或跳审"
                          "会被自动查出并要求补审")
        else:
            audit_note = "dev 交付后不审核就答复用户属重大流程违规"
        dev_model = resolve_role_models()[1]
        return (
            "【轻主力分工（你=轻快主力）】\n"
            "本会话是日常对话与执行的轻快主力：问答闲聊直接答；查文件、跑"
            "命令、环境排查、信息收集这类跑腿杂活直接干——这些都不要派发。\n"
            "攻坚必须走两个强模型代理（都用 Task 工具）：\n"
            "1. dev 代理（%s）：编码/debug/方案思考一个上下文打通——功能"
            "实现、多文件改动、bug 修复一律派它，不要自己写。\n"
            "2. reviewer 代理（%s）：对抗审核——dev 交付后必须派它审改动，"
            "它专门挑毛病（只审不改，给 PASS/FAIL 结论）。\n"
            "标准流程：dev 实现 → reviewer 对抗审核 → 判 FAIL 就回 dev 修"
            "→ 复审，致命/严重问题清零才收 → 你消化双方结论后汇总答复用户。\n"
            "纪律（免审线是可数规则；%s）：\n"
            "- 允许你直接改且免审的唯一情形：只动一个文件、本回合累计不超过 "
            "%d 行（配置值/常量/文案/注释级微调）。\n"
            "- 其余任何代码修改一律派 dev——不要自行把改动判成「微调」就"
            "自己上手。\n"
            "- dev 交付后必须派 reviewer 审核再答复用户，无例外。\n"
            "- reviewer 判 FAIL 必须回炉重修；两边的报告都要消化后再答，"
            "不要原样转发一大坨。\n"
            "- 回合终点纪律：提交/实施完成后，你的最后一条消息必须是给用户的结论"
            "汇总（做了什么、审核结论、提交号、用户需要做什么）——用户看不到后台"
            "代理的过程，静默结束回合=交付没完成。\n"
            % (dev_model, dev_model, audit_note, max_free)
        )
    ex_model, co_model = resolve_role_models()
    return (
        "【三角色分工（你=决策者）】\n"
        "本会话你是「决策者」：面向用户的唯一对接人，只做四件事——\n"
        "1. 承接：理解用户需求，含糊就用 ask_user 澄清，然后拆解成子任务。\n"
        "2. 派发（Task 工具）：\n"
        "   - 信息收集/查日志/环境排查/跑命令/debug 定位/机械杂活 → "
        "executor 代理（%s，快省）\n"
        "   - 编码攻坚（功能实现/架构改动/疑难修复）→ coder 代理（%s）\n"
        "3. 审核：coder 的产出必须亲自 Read 看它交付报告里列出的改动文件、"
        "把关质量，不过关打回重做并写明问题。\n"
        "4. 汇总：结论先行答复用户，附关键证据。\n"
        "纪律：你不下场干活——查文件/数数/收集信息/搜索这类事都算活，一律派 "
        "executor（实测你会拿 Glob/Grep 自己数数偷懒，这些已结构性禁止）。"
        "你只保留 Read：用于审核 coder 交付报告里列出的改动文件；审核也可"
        "再派 executor 取证（如查引用、跑验证命令）。纯知识问答直接回答"
        "不必派发；子代理结论要消化后再答，不要原样转发一大坨。\n"
        "回合终点纪律：提交/实施完成后，最后一条消息必须是给用户的结论汇总"
        "（做了什么、审核结论、提交号、用户需要做什么），不得静默结束回合。"
        % (ex_model, co_model)
    )
