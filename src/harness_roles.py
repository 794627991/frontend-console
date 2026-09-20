# -*- coding: utf-8 -*-
"""三角色设计——harness 内置定义（v2.29.1）。

角色定义是 harness 的一部分，不是用户手工放的 ~/.claude/agents/*.md：
会话启动时自动把 executor（执行者）/coder（编程者）两个子代理定义安装
到 claude 的 agents 目录（幂等：内容有变才写，配置改了模型会同步重生成）。
任何人装了本工具即得三角色，零手工配置。

模型名存 config.json 的 harness_roles 节（executor_model / coder_model /
enabled），换 API 方案改配置即可，不用动代码。

实测要点：agent 文件的 model 字段必须写【显式模型 ID】——别名
（opus/haiku）在这条链路上会被无视（子代理跑主链模型）。
"""
import json
import os
import re

import src.app_state as _st

_ROLES_KEY = "harness_roles"
ROLE_DISALLOW = "Bash,Edit,Write,WebFetch,WebSearch,Glob,Grep"
_AGENTS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "agents")

# 轻快模型识别（执行者级）：名字带这些词的当 executor
_LIGHT_RE = re.compile(r"flash|turbo|light|mini|fast|air|speed|lite", re.I)

_DEFAULTS = {"enabled": False,          # v2.29.3 默认关闭（用户定调：开关开启才生效）
             "executor_model": "glm-5.3-flash",
             "coder_model": "glm-5.3",
             "model_map": {}}


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


def set_roles_enabled(enabled):
    """写开关（merge 语义：只动 enabled，其余键保留）。返回 (ok, err)。
    改完即生效——角色词在引导词指纹里，下条消息发送前的指纹热更会自动
    kill+resume 换词重启（含/不含结构禁权），已有会话无需重建。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    r = d.get(_ROLES_KEY)
    r = r if isinstance(r, dict) else {}
    r["enabled"] = bool(enabled)
    d[_ROLES_KEY] = r
    try:
        tmp = _st.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _st.CONFIG_FILE)
        return True, None
    except Exception as e:
        return False, str(e)


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


def install_roles_agents():
    """安装/更新 executor、coder 子代理定义到 ~/.claude/agents/（幂等：
    内容有变才写）。模型按当前 API 方案解析（resolve_role_models）——换
    方案后下次起会话自动重生成对应模型的定义。失败静默（只影响本功能，
    不拖垮会话启动）。"""
    cfg = roles_cfg()
    if not cfg["enabled"]:
        return
    ex_model, co_model = resolve_role_models()
    try:
        os.makedirs(_AGENTS_DIR, exist_ok=True)
    except Exception:
        return
    for fn, content in _agent_files(ex_model, co_model).items():
        p = os.path.join(_AGENTS_DIR, fn)
        try:
            cur = None
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    cur = f.read()
            if cur != content:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception:
            pass


def roles_bridge_text(model=None):
    """决策者角色引导。只注入非「执行者级」主会话——主会话模型与执行者
    同级（轻快模型）时它本身就是干活的定位，直接干活不套娃。"""
    if not roles_cfg()["enabled"]:
        return ""
    ex_model, co_model = resolve_role_models()
    if model:
        ml = str(model).lower()
        if ml == ex_model.lower() or _LIGHT_RE.search(ml):
            return ""
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
        "不必派发；子代理结论要消化后再答，不要原样转发一大坨。"
        % (ex_model, co_model)
    )
