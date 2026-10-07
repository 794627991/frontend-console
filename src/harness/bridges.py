# -*- coding: utf-8 -*-
"""harness.bridges —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import hashlib
import logging
log = logging.getLogger(__name__)
from .vision import _model_vision_mode, _vision_load


# ---- from claude_harness.py:316 (ask_bridge_text) ----


def ask_bridge_text():
    """生成注入每个会话的「交互式提问」引导段。

    v2.17：CLI 在 -p 下没有 AskUserQuestion/ExitPlanMode（模型想调也没这个
    工具），所以「给选项让用户点选」靠我们自建的 MCP 工具 ask_user 实现。
    模型默认不知道它有这个工具，必须显式告诉它——和识图转交同一个理由。
    """
    return (
        "【交互式提问】\n"
        "你需要用户在若干方案中拍板、或关键决策需要确认时，用 ask_user 工具"
        "（一个 MCP 工具，全名 mcp__harness__ask_user）向用户提问，而不是把"
        "选项写成纯文本让他回复。用户在界面上会看到可点击的选项卡片，点选并"
        "提交后，ask_user 的返回值就是用户的选择。\n"
        "- 什么时候用：方案取舍（「用 A 还是 B」）、实现路径分叉、需要用户补充"
        "偏好或约束、动手前需要授权的高风险操作。\n"
        "- 什么时候不用：纯知识问答、你自己能查证的事实、无意义的「要不要继续」"
        "式确认。\n"
        "- 一个问题的可选项 2-4 个，每个选项配一句说明（用户看说明做判断）。\n"
        "- 调用后你会停在那里等，不要在同一轮里又自己把方案做了。"
    )

# ---- from claude_harness.py:338 (confirm_bridge_text) ----


def confirm_bridge_text():
    """「变更前确认」权限模式的引导段（v2.20）。

    headless -p 下没有原生确认通道，实现落在提示层：要求模型在写操作前
    用 ask_user（v2.17 的 MCP 卡片）征得同意——和 ZCode 同款「变更前确认」。
    """
    return (
        "【变更前确认】\n"
        "本会话开启了「变更前确认」权限模式：凡是要产生写入/修改/删除效果的"
        "操作——Edit/Write/MultiEdit/NotebookEdit、新建或覆盖文件、Bash/"
        "PowerShell 中会改变文件或系统状态的命令——执行前必须先用 ask_user"
        "工具（mcp__harness__ask_user）向用户简述将要做的变更（改哪个文件、"
        "执行什么命令）并征得同意，用户确认后才动手。只读操作（Read/Grep/"
        "Glob/WebSearch/查看类命令）不需要确认。\n"
        "用户拒绝或取消时不要绕过：改用只读方式继续，或说明无法继续的原因。"
    )

# ---- from claude_harness.py:387 (TOKEN_RULES) ----


# 角色设计：角色定义内置于 src/harness_roles.py（随工具分发，会话启动
# 自动安装到 ~/.claude/agents/，别的机器零手工配置）；角色引导词/配置
# 开关都在那个模块里。双形态（v2.51 重规划）：两形态主会话都直干所有
# 活，不派干活子代理；子代理只留 designer（只设计）+ reviewer（只读
# 审核）两个代理——light 装两个、strong 只装 reviewer 作审计
# 兜底（旧决策者结构禁权/roles_disallow 已废除）。
from .roles import (roles_bridge_text, install_roles_agents,
                            audit_verdict, audit_gate_check)


# v2.3.7 全会话铁律（用户定调「浪费 token 极其可耻」）：注入每个会话。
TOKEN_RULES = (
    "【铁律：珍惜 token】\n"
    "1. 结论即停：工具返回已足以回答就直接用，禁止重复调用确认。\n"
    "2. 单问单调：一次调用覆盖多角度（prompt 里并列），不撒网连发。\n"
    "3. 言简意赅：回复别废话，先结论后要点；代码注释写清不写长。\n"
    "4. 不重读：上下文已有的信息（自己刚写/刚读）不重新 Read。"
)

# ---- from claude_harness.py:407 (_bridge_fp) ----


def _bridge_fp(model):
    """识图引导词指纹（send 前热更检测用）：内容含三态判定结果，代码升级
    / mm_mcp 名单调整 / vision 开关都会改变指纹。未启用时空串（有→无也
    构成变化，同样触发重启换新）。v2.29：三角色引导词并入指纹——角色
    开关/词改动同样触发活会话热更换词。"""
    return hashlib.md5((vision_bridge_text(model) + "\x00"
                        + roles_bridge_text(model)).encode("utf-8")).hexdigest()

# ---- from claude_harness.py:416 (vision_bridge_text) ----


def vision_bridge_text(model=None):
    """生成注入每个主会话的识图引导段（识图未启用则空串）。

    这是问题2 的核心：主会话默认不知道自己有识图同伴，必须显式告知——
    告知它 peer 名叫什么、什么时候该转交、怎么转交、怎么收回结论。
    v2.19：主会话模型本身多模态（_model_is_multimodal）→ 反过来注入
    「直接用 Read 读图」，不再转交——通用转交引导会把能看图的会话
    也带去麻烦识图会话（用户实测吐槽）。
    v2.28：两态——inline 直读 / 其余全部走 MCP 通道（本地 analyze_image
    全面接管，识图会话与转交引导退役）。
    """
    cfg = _vision_load()
    if not cfg["enabled"]:
        return ""
    mode = _model_vision_mode(model) if model else None
    if mode == "inline":
        return (
            "【识图说明】\n"
            "本会话使用的模型具备多模态能力：用户发来的图片、截图、照片，"
            "直接用 Read 工具读取图片路径并分析，自己给出结论，"
            "不要转交给其他会话处理。\n"
            "【铁律（实测读错图事故）：只 Read 用户消息里内联出现的图片路径，"
            "禁止主动 Read 自己生成的裁剪/缩放图片文件来「看图」——该路径的"
            "回显链路会产出未编码的畸形 CDN URL 并可能回退到缓存旧图，导致"
            "你看到的图与磁盘上的不是同一张（已实测多起读图错位）。确需自查"
            "生成的图片时，改用 MCP 兜底工具传本地绝对路径分析，或让用户确认。"
        )
    # v2.28：非 inline（含并入的原 None 态）一律走 MCP 通道
    return (
        "【识图说明（MCP 通道）】\n"
            "本会话模型自身看不了图片，但可以调识图 MCP 完成看图，不要转交"
            "其他会话：\n"
            "1. 用户消息里的图片附件自带 CDN 图片链接"
            "（https://maas-log-prod...png?...），直接取用。"
            "没有链接、只有本地路径时【禁止用 Read 读图片取链接——直接走"
            "第 3 步 (b) 兜底工具传本地路径】。实测教训：MCP 模式会话对图片"
            "文件 Read 一次，上下文立涨 +680K tokens 直接爆窗。"
            "链接现取现用、原样完整（200+ 字符一个都不能少——抄坏/截断长链接"
            "是识图失败头号成因）；历史消息里的旧链接签名已过期（约 1 小时"
            "有效期），禁止复用。\n"
            "2. 主通道：调用 mcp__4_5v_mcp__analyze_image 工具，imageSource="
            "该链接，prompt=你想从图里知道的问题（要求结论先行、给坐标"
            "参考）。\n"
            "3. 【兜底阶梯】主通道报错（1210/400/超时）时：直接调 "
            "mcp__vision__analyze_image（本地兜底工具），imageSource 传图片"
            "的本地绝对路径（附件消息里就有，该工具直接读盘、不依赖链接、"
            "不占本会话上下文）——最多试一次；仍失败 → 如实告诉用户「识图"
            "服务暂时不可用」并附最后的错误信息，不要编造图片内容，也不要"
            "反复重试。【绝禁止用 SendMessage/ListAgents 转交「识图会话」"
            "或任何其他会话看图——识图会话已退役不存在，转交出去的图"
            "永远等不到回传，等于扔进黑洞】\n"
            "【铁律：CDN 链接必须原样带完整 query 签名（?UCloudPublicKey=…"
            "&Expires=…&Signature=… 一个参数都不能少、不能截断、不能自己"
            "清洗、不能复制时改动任何字符】——去掉签名、改动一字（如 "
            "TOKEN 错成 T_TOKEN）、截断或链接过期，都会被 CDN 拒绝（400/401），"
            "拿到非图片内容报 1210「图片输入格式/解析错误」，看起来像服务"
            "故障，实际是链接问题（实测踩坑）。\n"
            "【铁律：单图单问、结论即停——一次 analyze_image 返回已足以回答"
            "问题就直接用它，禁止对同一张图再发第二次调用「确认」；多角度"
            "需求并进同一次 prompt。多余调用浪费额度还放大手滑概率（实测"
            "4 连发/2 连发被用户两次质问）。注意：兜底阶梯里的重试不算违例，"
            "那是失败后的自救】\n"
            "多张图逐张处理。兜底阶梯走完仍失败时按第 3 步 (c) 收场。"
        )
