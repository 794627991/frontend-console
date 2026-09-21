# -*- coding: utf-8 -*-
"""Claude harness 界面化会话（微信式多会话版）。

与 claude_conn.py（ConPTY 跑 TUI，xterm 保真）平行的另一条通道：
  claude -p --input-format stream-json --output-format stream-json --verbose
进程常驻，stdin 写 NDJSON user 消息即连续多轮；stdout 逐行 NDJSON 事件
（system/assistant/user/result），后端原样透传给前端 SSE，渲染全在前端。

v2（微信式改造）新增：
- 会话持久化：~/.serialconsole_pro/claude_harness.json 元数据表——
  会话列表跨重启保留；切回会话用 --resume <session_id> 复活上下文。
- 模型选择：connect 时 --model <名>（会话级，改模型=新会话）。
- 图片/文件附件：消息 content 数组带 image base64 块 + 文件路径文本
  （实测：内网网关模型不识图时会收到模型「无法识图」自述——协议透传，
  网关换多模态模型后自动生效）。
- 闲置回收：活进程闲置 15min 自动 kill（元数据保留），切回会话自动复活
  ——铁律1「不用时不得占用任何资源」。会话数不设死上限，靠回收兜底。
- 事件缓冲有上限（_EVENTS_MAX），历史气泡从 ~/.claude 转写重建。

铁律约束：不动 claude_conn/claude_sessions/claude_setup/claude_default；
不落盘工具日志（Claude 自写 ~/.claude/projects 转写）。
"""
import os, json, base64, re, sys, subprocess, threading, time, uuid, hashlib, tempfile
import logging   # v2.3.3：log 此前从未定义（续命失败分支 log.warning 一走就
log = logging.getLogger(__name__)   # NameError 吞掉真实异常——Cython 编译抓出的潜雷）
from queue import Queue, Empty

from flask import Blueprint, request, jsonify, Response, send_from_directory

from . import app_state as _st
from .claude_conn import _resolve_claude_exe, _humanize_claude_error, _trust_workspace
_EVENTS_MAX = 4000          # 每会话事件缓存上限（前端重连回放用）
_QUEUE_MAX = 2000           # SSE 客户端队列上限
_IDLE_KILL_S = 15 * 60      # 活进程闲置回收阈值（秒）
_META_FILE = os.path.join(_st.HOME_DIR, "claude_harness.json")
_UPLOAD_DIR = os.path.join(_st.HOME_DIR, "harness_uploads")
_UPLOAD_MAX = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# 用户自定义提示词（v2.8：多条目体系）
#   harness_prompts = [ {id, scope, project, note, text, enabled} ]
#   scope ∈ {"global","project"}；global 对所有会话生效；project 只对
#   cwd 匹配 project 的会话生效（末段目录名精确匹配，如 "串口控制台Pro"
#   匹配 D:\AI\串口控制台Pro——比全路径匹配好写好认）。
#   start() 时收集 启用的 global 条目 + cwd 匹配的启用 project 条目，
#   按 note 头 / text 体 拼接注入 --append-system-prompt。
# 旧单条 harness_system_prompt（v2.4）自动迁移为一条 global 条目（一次性）。
# ---------------------------------------------------------------------------
_PROMPTS_KEY = "harness_prompts"
_PROMPTS_LEGACY_KEY = "harness_system_prompt"


# ---------------------------------------------------------------------------
# 识图会话配置（v2.14）
#   harness_vision = {enabled, model, prompt, name}
#
#   工具启动 claude 后，后台起一个专用会话（固定模型 + 固定名字）。识图任务
#   由主会话经 Claude Code 原生 peer 机制（SendMessage/ListAgents）转交，结论
#   经同通道回传。不走 MCP、不自造管道。
#
#   实测确认（v2.14 实现依据）：
#   - `claude -p --input-format stream-json` 进程自动注册进 peer 网络
#     （~/.claude/sessions/<pid>.json，带 messagingSocketPath，entrypoint=sdk-cli）
#   - 无输入时静默待命，不烧轮次；收到 peer 消息自动触发一轮，
#     无需 notify_when_idle。
#   - --name 决定寻址名（支持中文），会话存活期稳定；进程退出后注册条目自动清理。
#
#   两个作用域各有一份提示词，都不占用户提示词列表的位置，但起同样作用：
#   - prompt（识图侧）：告诉识图会话它是什么、怎么读图、必须用 SendMessage 回复。
#   - 主会话侧的转交规则由 vision_bridge_text() 生成，注入每个会话。
#   用户可改、可改回默认（reset）；留空=用默认。
# ---------------------------------------------------------------------------
_VISION_KEY = "harness_vision"
VISION_DEFAULT_NAME = "识图会话"

# 识图后台会话对象（单例；列表容器便于闭包内赋值）
_vision_lock = threading.Lock()
_vision_obj = [None]

VISION_DEFAULT_PROMPT = """你是本机专用的识图会话。你没有串口/SSH 设备控制能力，唯一职责是读图并给出结论。

收到其他 Claude 会话（主会话）发来的识图任务时：
- 用 Read 工具直接读图片路径。只读图，不要调用串口、日志、TFTP 一类工具。
- 回答「结论先行」：第一句直接给答案，再给支撑细节。不要复述你看到了什么，除非那是结论的一部分。
- 客观描述优先于推测。看不清、被遮挡、分辨率不足、图里没有该信息，就直说「看不清 / 图中无此信息」，不要猜。
- 提到位置时给可复核的坐标或区域描述（如「左上角状态栏第 2 行」「坐标约 (820, 340)」），方便主会话核对。
- 多张图一起给时，明确标注每张图的结论对应哪个文件，不要把不同图的信息混成一条结论。
- 需要跨图对比（如「这两张图的差异」）时，逐项列出差异点，不要只给笼统印象。
- 回复必须用 SendMessage 工具发回给发件人（把来件的 from 属性作为 to）。只用普通文本输出的话，对方看不到。"""


def _vision_default_cfg():
    # v2.28.1：mm_mcp 名单退役——分类只剩两态（真多模态 inline / 其余全部
    # MCP），非 inline 即 MCP，无需名单。旧 config 里的 mm_mcp 键自然闲置。
    # v2.28.2：model_map 端点模型映射 + mcp_prompt——识图配置（MCP 后端）
    # 多方案适配：lanz 端点配 Lanz 系、bigmodel 端点配 glm 系。
    return {"enabled": False, "model": "", "prompt": VISION_DEFAULT_PROMPT,
            "name": VISION_DEFAULT_NAME, "mm_extra": [], "model_map": {},
            "mcp_prompt": ""}


def _vision_load():
    """读识图会话配置。缺字段兜默认（老 config 升级不炸）。"""
    cfg = _vision_default_cfg()
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        raw = d.get(_VISION_KEY)
        if isinstance(raw, dict):
            cfg["enabled"] = bool(raw.get("enabled", False))
            cfg["model"] = str(raw.get("model") or "").strip()
            cfg["prompt"] = str(raw.get("prompt") or "").strip() or VISION_DEFAULT_PROMPT
            cfg["name"] = str(raw.get("name") or "").strip() or VISION_DEFAULT_NAME
            mm = raw.get("mm_extra")
            if isinstance(mm, list):
                cfg["mm_extra"] = [str(x).strip() for x in mm if str(x).strip()]
            # v2.28.2：端点模型映射（dict 或 "关键字=模型" 行列表均收）+
            # MCP 识图提示词
            mmap_raw = raw.get("model_map")
            mmap = {}
            if isinstance(mmap_raw, dict):
                mmap = {str(k).strip().lower(): str(v).strip()
                        for k, v in mmap_raw.items()
                        if str(k).strip() and str(v).strip()}
            elif isinstance(mmap_raw, list):
                for line in mmap_raw:
                    kv = str(line).split("=", 1)
                    if len(kv) == 2 and kv[0].strip() and kv[1].strip():
                        mmap[kv[0].strip().lower()] = kv[1].strip()
            if mmap:
                cfg["model_map"] = mmap
            mp = str(raw.get("mcp_prompt") or "").strip()
            if mp:
                cfg["mcp_prompt"] = mp
    except Exception:
        pass
    return cfg


# ---------------------------------------------------------------------------
# 多模态模型判定（v2.19）
#   名字启发式 + 识图配置 mm_extra 名单（正则没覆盖到时用户手补）。
#   识图会话自身配置的 model 必然多模态，自动并入。
#   判定影响两处：模型下拉加 👁 标记；start() 时主会话模型已多模态，
#   注入「直接用 Read 读图」引导，不再教它转交识图会话（用户实测：
#   明明切了多模态模型，发图还是被引导去找识图会话，不符合逻辑）。
# ---------------------------------------------------------------------------
_MM_RE = re.compile(
    r"vl|vision|omni|multimodal|gpt-4o|gpt-4\.5|gemini"
    r"|[\d.]v(?:$|[-_.])|^claude"
    # v2.25：独立单字母 V 段（Lanz-Medium-V / Qwen-V 这类「-V」后缀写法）。
    # 旧式只看「数字或点 + v」的 `[\d.]v`，把 V 前面是连字符的漏判成非多模态
    # ——用户实测 Lanz-Medium-V 无 👁，且会话仍被引导去转交识图会话。
    r"|[-_]v(?:$|[-_.])",
    re.I)


def _mm_probe_key(model):
    """探测缓存的签名键：base_url|model。同一模型名在不同配置方案（智谱直连
    vs lanz 网关 vs 本地代理）下多模态能力不同——只按名字缓存会把旧方案的
    结论带到新方案（2026-09-16 实测：glm-5.3-flash[1M] 在旧方案探测通过，
    切方案后主会话仍被注入「自己读图」，实际读不了，图片也不转交识图会话，
    两头落空）。旧格式的裸模型名键自然失配，等价于自动失效重探。
    v2.27.5：模型名归一化小写——CLI 侧会把 [1M] 规范成 [1m]，大小写不一致
    会让签名键/相等比较全部翻车（用户实锤切模型后仍走转交）。"""
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = (json.load(f).get("env") or {})
        base = (env.get("ANTHROPIC_BASE_URL") or "unknown").rstrip("/").lower()
    except Exception:
        base = "unknown"
    return base + "|" + (model or "").strip().lower()


def _model_is_multimodal(name):
    name = (name or "").strip()
    if not name:
        return False
    lname = name.lower()
    # 当前方案下的运行时探测结果最权威（真实链路上验证过能否读图），
    # 优先于名字启发式与 mm_extra 名单——名单可能是别的方案探测时自动加的
    cached = _mm_probed_load().get(_mm_probe_key(name))
    if cached is not None:
        return bool(cached)
    if _MM_RE.search(lname):
        return True
    cfg = _vision_load()
    # v2.27.5：全部比较用小写——CLI 切模型后上报 [1m] 小写，配置里是 [1M]，
    # 严格相等永远 False → 多模态模型被误判走转交（用户实锤）
    if lname == (cfg["model"] or "").strip().lower():
        return True
    for item in cfg["mm_extra"]:
        # v2.25：前缀匹配覆盖窗口后缀变体；v2.27.11 收窄为 item+'['——
        # 激进前缀会把同族别的模型吞掉（名单填 glm-5.3 连 glm-5.3-flash
        # 一起判中，实测踩坑），只覆盖 [1M] 这类上下文窗口后缀
        item = (item or "").strip().lower()
        if lname == item or lname.startswith(item + "["):
            return True
    return False


def _vision_save(cfg):
    """原子写识图配置。v2.25 改 merge 语义：cfg 里的键覆盖 _VISION_KEY 同名键，
    其余键（如 mm_probed 探测缓存）原样保留——旧实现整键替换，调用方没带
    的字段会被静默抹掉。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    cur = d.get(_VISION_KEY)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(cfg)
    d[_VISION_KEY] = cur
    try:
        tmp = _st.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _st.CONFIG_FILE)
        return True, None
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# 多模态运行时探测（v2.25）
#   名字启发式靠猜、名单靠用户记——都不如直接问模型本身：起一次性 headless
#   claude，发一张已知颜色的测试图让它 Read，答对颜色即为多模态。结果按
#   模型名缓存在识图配置的 mm_probed（config.json，不进 ~/.claude/settings），
#   探测一次终身受用；通过者自动并入 mm_extra 名单。
# ---------------------------------------------------------------------------
_MM_PROBE_LOCK = threading.Lock()


def _mm_probe_png_bytes():
    """生成 8x8 纯红 PNG（标准库手搓，无 PIL 依赖）。"""
    import struct, zlib
    w = h = 8
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8bit RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _mm_probe_model(model):
    """探测 model 识图能力。返回 (mode, msg)：mode ∈ 'inline'/'mcp'/None。
    v2.27.12 两段式（用户定调：三态结论靠探测自动得出，不靠人工猜）：
    1) inline——独立进程 Read 红图直接答（模型本身多模态）；
    2) inline 失败 → mcp——同进程改走 Read 拿 CDN 链接 + 调
       mcp__4_5v_mcp__analyze_image（模型自身看不了图但 MCP 通道可识图，
       与本会话实测 glm-5.3 行为一致）；
    3) 都失败 → None（转交识图会话兜底）。"""
    probe_path = os.path.join(_st.STATE_DIR, "mm_probe.png")
    try:
        with open(probe_path, "wb") as f:
            f.write(_mm_probe_png_bytes())
    except Exception as e:
        return None, "写测试图失败：%s" % e
    exe, is_shim = _resolve_claude_exe()
    base = (["cmd.exe", "/c", exe] if is_shim else [exe])

    def _run(prompt, tools):
        argv = base + ["-p", prompt, "--model", model,
                       "--permission-mode", "auto", "--allowedTools", tools]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return ""
        except Exception:
            return ""
        return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", errors="replace")

    def _red(out):
        return bool("红" in out or re.search(r"\bred\b", out or "", re.I))

    # 第 1 段（也是唯一一段，v2.28.1）：直读测真多模态。原第 2 段（测 MCP
    # 工具链）退役——本地 analyze_image 注入所有会话，MCP 通道无需探测；
    # 答不出颜色即非真多模态，分类自动落 mcp（默认通道）。
    out = _run("用 Read 工具读取这张图片：" + probe_path +
               "。它是纯色图，只回答颜色的中文名（例如：红色），不要解释。",
               "Read")
    if _red(out):
        return "inline", "真多模态 ✔（模型直读答出颜色）"
    return "mcp", ("非真多模态——直读未答出颜色，默认走 MCP 通道"
                   "（本地 analyze_image），无需配置（直读片段："
                   + (out or "").strip()[:50] + "）")


def _mm_probed_load():
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = (d.get(_VISION_KEY) or {}).get("mm_probed")
        if isinstance(p, dict):
            return p
    except Exception:
        pass
    return {}
    try:
        tmp = _st.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _st.CONFIG_FILE)
        return True, None
    except Exception as e:
        return False, str(e)


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


def _model_vision_mode(name):
    """v2.28.1：两态分类（用户定调：只保留真多模态，其余全部走 MCP）。
    返回 'inline'（真多模态，内联直读）或 'mcp'（本地 analyze_image 通道）。
    inline 判定 = 名字正则 / 探测缓存（mm_probed）/ mm_extra 名单；
    mm_mcp 第三态名单已退役——非 inline 一律 MCP，无需枚举。"""
    name = (name or "").strip()
    if not name:
        return "mcp"
    if _model_is_multimodal(name):     # 内部顺序：缓存 → 正则 → mm_extra
        return "inline"
    return "mcp"


# v2.28.5：识图工具名双通道——网关内置名（主通道，服务端执行）+ 本地名
# （兜底通道，harness_vision_mcp.py 注册，server 名 vision）。同名会被网关
# 遮蔽（实测 log 零记录、零 tool_use），本地版必须独立名字才可作为真兜底。
# 实时事件流与历史回放解析按两个名字识别识图调用。
_VISION_TOOLS = ("mcp__4_5v_mcp__analyze_image", "mcp__vision__analyze_image")


def _iso_dur_sec(t0, t1):
    """两个 ISO 时间串的差（秒，1 位小数）。解析失败返回 None。"""
    try:
        from datetime import datetime
        a = datetime.fromisoformat(str(t0).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(t1).replace("Z", "+00:00"))
        return round((b - a).total_seconds(), 1)
    except Exception:
        return None


# v2.29.1 三角色设计：角色定义内置于 src/harness_roles.py（随工具分发，
# 会话启动自动安装到 ~/.claude/agents/，别的机器零手工配置）；角色引导词/
# 结构禁权/配置开关都在那个模块里。v2.30.2 双形态：主会话轻快模型 →
# 轻主力模式（designer 代理，无禁权），强模型 → 决策者模式（结构禁权）。
from .harness_roles import (roles_bridge_text, roles_disallow,
                            install_roles_agents)


# v2.3.7 全会话铁律（用户定调「浪费 token 极其可耻」）：注入每个会话。
TOKEN_RULES = (
    "【铁律：珍惜 token】\n"
    "1. 结论即停：工具返回已足以回答就直接用，禁止重复调用确认。\n"
    "2. 单问单调：一次调用覆盖多角度（prompt 里并列），不撒网连发。\n"
    "3. 言简意赅：回复别废话，先结论后要点；代码注释写清不写长。\n"
    "4. 不重读：上下文已有的信息（自己刚写/刚读）不重新 Read。"
)


def _bridge_fp(model):
    """识图引导词指纹（send 前热更检测用）：内容含三态判定结果，代码升级
    / mm_mcp 名单调整 / vision 开关都会改变指纹。未启用时空串（有→无也
    构成变化，同样触发重启换新）。v2.29：三角色引导词并入指纹——角色
    开关/词改动同样触发活会话热更换词。"""
    return hashlib.md5((vision_bridge_text(model) + "\x00"
                        + roles_bridge_text(model)).encode("utf-8")).hexdigest()


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
            "不要转交给其他会话处理。"
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
    # v2.28：转交识图会话分支退役——_model_vision_mode 已无 None 态
    # （全部并入 mcp），本地 analyze_image 是唯一识图通道。防御性返回空串。


def _peer_reg_path():
    return os.path.join(os.path.expanduser("~"), ".claude", "sessions")


def _cleanup_peer_reg(pid=None, session_id=None):
    """清理 claude 的 peer 注册条目（~/.claude/sessions/<pid>.json）。

    为什么需要：kill_proc 是强杀（proc.kill()），claude 来不及自己摘注册，
    残留条目指向死 pid —— 之后 ListAgents 会列出幽灵会话，主会话可能把
    识图任务发给一个不存在的 peer。所以要主动摘。

    匹配规则（v2.15 收紧）：已知 session_id 时只按 session_id 匹配，
    pid 不能再作为独立命中条件 —— 本机 _resolve_claude_exe() 走的是直连
    claude.exe（is_shim=False），proc.pid 就是 claude 自己的 pid，而 pid 会
    被系统复用。旧写法下「新会话恰好拿到刚死会话的 pid」时，新会话关停会把
    那条 *活着* 的注册删掉（_pid_alive 查的是条目自己的 pid，防不住这个），
    导致主会话 --resume 时 peer 身份被摘、或子代理结果送不回来。
    session_id 未知时才退回 pid 匹配（cmd.exe shim 场景），此时本会话注册
    条目本来也带 pid，能对上。
    删前先确认进程真的死了，避免误删尚在运行的会话注册。
    """
    d = _peer_reg_path()
    if not os.path.isdir(d):
        return
    try:
        names = os.listdir(d)
    except OSError:
        return
    for fn in names:
        if not fn.endswith(".json"):
            continue
        p = os.path.join(d, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                o = json.load(f)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        if session_id:
            hit = o.get("sessionId") == session_id
        else:
            hit = bool(pid) and o.get("pid") == pid
        if not hit:
            continue
        # 进程还活着就不动（防误删：pid 可能已被系统复用）
        if _pid_alive(o.get("pid")):
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def _pid_alive(pid):
    """跨平台判活（只读探测，不发信号）。pid 无效返回 False。"""
    if not pid:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _cleanup_stale_vision_peers(name):
    """清理「同名且进程已死」的识图会话孤儿注册。

    刻意只清同名条目，不做全表清理——别的条目属于用户其他 Claude 会话，
    误删会砸掉正在用的会话。同名死条目才是真正会撞车的（新进程起来后
    同名并存，主会话可能把识图任务发给死的那条）。
    """
    if not name:
        return 0
    d = _peer_reg_path()
    if not os.path.isdir(d):
        return 0
    n = 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for fn in names:
        if not fn.endswith(".json"):
            continue
        p = os.path.join(d, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                o = json.load(f)
        except Exception:
            continue
        if not isinstance(o, dict) or o.get("name") != name:
            continue
        if _pid_alive(o.get("pid")):
            continue          # 还活着：可能是用户手动开的同名会话，不动
        try:
            os.remove(p); n += 1
        except OSError:
            pass
    return n


def ensure_vision_session():
    """v2.28：识图会话退役——MCP 通道（mcp__4_5v_mcp__analyze_image）全面接管。

    原职责（养一个多模态后台会话做转交识图）已被本地 analyze_image 取代：
    速度 5.6 倍（一次推理 vs agent 两轮+轮询回传）、无常驻进程、无跨会话
    复杂度。保留函数签名做空操作：调用方（GC/connect 路径）零改动；遗留
    的旧识图会话由 GC 的 kill 分支自然收走，不再新拉。
    """
    return None


def stop_vision_session():
    """关掉识图后台会话（用户关开关/改配置时调）。"""
    with _vision_lock:
        s, _vision_obj[0] = _vision_obj[0], None
    if s is not None:
        try:
            with _sessions_lock:
                _sessions.pop(s.sid, None)
            s.close()
        except Exception:
            pass


def _prompts_load():
    """读 config.json 的 harness_prompts 列表。坏数据防御：过滤缺 id/text
    的条目，字段兜默认值。失败返回 []。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        raw = d.get(_PROMPTS_KEY)
        if not isinstance(raw, list):
            return []
        out = []
        for it in raw:
            if not isinstance(it, dict) or not it.get("id") or not it.get("text"):
                continue
            out.append({
                "id": str(it["id"]),
                "scope": it.get("scope") if it.get("scope") in ("global", "project") else "global",
                "project": str(it.get("project") or "").strip(),
                "note": str(it.get("note") or "").strip(),
                "text": str(it["text"]).strip(),
                "enabled": bool(it.get("enabled", True)),
            })
        return out
    except Exception:
        return []


def _prompts_save(items):
    """原子写 config.json 的 harness_prompts。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    d[_PROMPTS_KEY] = items
    try:
        tmp = _st.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _st.CONFIG_FILE)
        return True, None
    except Exception as e:
        return False, str(e)


def _prompt_matches_project(item, cwd):
    """项目作用域匹配：cwd 末段目录名（normpath 后）== item.project。
    project 为空视作不匹配（防误全局）。大小写不敏感（Windows）。"""
    if item.get("scope") != "project" or not item.get("project") or not cwd:
        return False
    try:
        tail = os.path.basename(os.path.normpath(cwd)) or cwd
        return tail.lower() == str(item["project"]).strip().lower()
    except Exception:
        return False


def _collect_system_prompt(cwd):
    """按 cwd 收集要注入的提示词（start() 用）：
    启用的 global 条目 + cwd 匹配的启用 project 条目，note 做「」小标题。
    返回拼接后的单串（空串=不注入）。"""
    parts = []
    for it in _prompts_load():
        if not it.get("enabled", True):
            continue
        if it.get("scope") == "project" and not _prompt_matches_project(it, cwd):
            continue
        note = it.get("note") or ""
        parts.append(("【%s】" % note if note else "") + it["text"].strip())
    return "\n\n".join(parts)

# ---------------------------------------------------------------------------
# 会话元数据持久化（重启不丢会话列表——"像微信一样"的根基）
# ---------------------------------------------------------------------------
_meta = {}                  # sid -> meta dict
_meta_lock = threading.Lock()
_meta_loaded = False
_meta_tombstones = set()    # 本进程已删 sid：_meta_save 合并时防从盘面复活


def _meta_load():
    global _meta, _meta_loaded
    if _meta_loaded:
        return
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _meta = {k: v for k, v in d.items() if isinstance(v, dict) and v.get("sid")}
    except FileNotFoundError:
        _meta = {}                     # 首次启动无表：正常路径
    except Exception:
        # 坏文件（写入撕裂/被截断）不能静默当空表——否则下一次 _meta_save
        # 会用空表全量覆盖，整张会话列表蒸发（2026-09 实测丢过一批）。
        # 先留档 .bad 供人工找回，再当空表起步。
        try:
            os.replace(_META_FILE, _META_FILE + ".bad")
        except OSError:
            pass
        _meta = {}
    _meta_loaded = True


def _meta_save():
    """原子写（tmp + replace，同 claude_default 模式）。锁内快照防并发撕裂。

    落盘前重读盘面做并集合并：本进程只在首次用表时读一次文件，若期间另
    有进程（多开/重启窗口期）写入过新条目，拿内存快照直接覆盖会把它们抹
    掉。口径：盘面有而内存没有的条目补进来；两边都有以内存为准（本进程
    刚操作过，是最新的）。墓碑排除本进程已删条目，防止合并把刚删的复活。
    """
    with _meta_lock:
        _meta_load()
        try:
            with open(_META_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        if isinstance(d, dict):
            for k, v in d.items():
                if (k not in _meta and k not in _meta_tombstones
                        and isinstance(v, dict) and v.get("sid")):
                    _meta[k] = v
        data = dict(_meta)
    try:
        os.makedirs(os.path.dirname(_META_FILE), exist_ok=True)
        tmp = _META_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _META_FILE)
    except Exception:
        pass


# ---- 可选模型列表（读 ~/.claude/settings.json env 的 LANZ 映射）----
# 按文件 mtime 失效缓存：配置方案切换（/api/claude/profiles/apply 整份
# 写回 settings.json）后必须能立刻看到新模型映射——旧实现进程生命周期内
# 只读一次，用户实测「切了配置方案模型下拉不刷新，重启工具才生效」。
_models_cache = None


def available_models():
    global _models_cache
    path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        mtime = 0
    if _models_cache is not None and _models_cache.get("_mtime") == mtime:
        return _models_cache
    names, default = [], None
    try:
        with open(path, "r", encoding="utf-8") as f:
            env = (json.load(f) or {}).get("env") or {}
        default = env.get("ANTHROPIC_MODEL") or None
        for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                  "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                  "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_FLASH_MODEL"):
            v = env.get(k)
            if v and v not in names:
                names.append(v)
    except Exception:
        pass
    if not default and names:
        default = names[0]   # settings 无显式默认 → 取首个映射（与 CLI 回退语义一致）
    _models_cache = {"models": names, "default": default, "_mtime": mtime}
    return _models_cache


def _model_label(m):
    """Lanz-Auto → lanz · Lanz-Auto（参考 ClaudeDesktop 的徽章文案风格）。"""
    return "lanz · %s" % m if m and m.startswith("Lanz") else (m or "")


# ---------------------------------------------------------------------------
# 交互式提问（v2.17）
#   CLI 在 -p 下没有 AskUserQuestion/ExitPlanMode，所以 ask_user 走自建 MCP。
#   MCP server（src/harness_ask_mcp.py）反过来通过这两个端点找用户要答案，
#   前端渲染可点卡片 → 用户提交 → 唤醒那边阻塞着的工具调用。
# ---------------------------------------------------------------------------
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def _ask_mcp_cfg_path(sid, perm="auto"):
    """写本会话的 --mcp-config 文件（内容极小，每次 start 覆写）。

    perm：会话权限模式（auto/confirm），经 HARNESS_PERM 传给 ask_user MCP。
    路径用正斜杠：cmd.exe shim 会吞反斜杠转义，JSON 里带 \\ 的 Windows 路径
    经 shim 传递后解析失败（实测 --mcp-config 内联 JSON 会被引号处理吃掉）。
    """
    d = os.path.join(_st.HOME_DIR, "harness_ask")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return None
    # 打包（PyInstaller）下 src 不在磁盘上，改用 exe 自己的 --mcp-ask /
    # --mcp-vision 模式
    if getattr(sys, "frozen", False):
        ask_cmd, ask_args = sys.executable, ["--mcp-ask"]
        vis_cmd, vis_args = sys.executable, ["--mcp-vision"]
    else:
        ask_cmd = vis_cmd = (sys.executable or "python")
        ask_args = [os.path.join(_SRC_DIR, "harness_ask_mcp.py").replace("\\", "/")]
        vis_args = [os.path.join(_SRC_DIR, "harness_vision_mcp.py").replace("\\", "/")]
    # v2.28.5：注入两个 server——harness（ask_user）+ vision（本地兜底
    # 识图 analyze_image）。网关内置的 mcp__4_5v_mcp__analyze_image 是主通道
    # （服务端执行，无需本地配置）；本地版用独立名字 mcp__vision__analyze_image
    # 做兜底——同名会被网关遮蔽成影子工具（实测），改名后网关失败时模型
    # 才真正有第二条路可走。随识图开关门控（与引导词开关同步）。
    # PYTHONIOENCODING 防 GBK 控制台下中文工具描述乱码。
    servers = {"harness": {
        "command": ask_cmd,
        "args": ask_args,
        "env": {"HARNESS_SID": sid, "HARNESS_PERM": perm},
    }}
    if _vision_load()["enabled"]:
        servers["vision"] = {
            "command": vis_cmd,
            "args": vis_args,
            "env": {"PYTHONIOENCODING": "utf-8"},
        }
    cfg = {"mcpServers": servers}
    p = os.path.join(d, "%s.json" % sid[:16])
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        return None
    return p.replace("\\", "/")


# ---------------------------------------------------------------------------
# v2.34 light 形态回合结算审计（三角色强制机制的兜底层）。
# 背景：light 形态（主会话=轻快模型）下「代码修改必须走 dev+reviewer」纯靠
# 引导词软约束——失效模式：模型偷懒自己 Edit、把多行改动自判为微调免审、
# dev 交付后跳过 reviewer 直接答用户、分多次小改切片逃逸。strong 形态有
# 结构禁权不管；light 主会话要干杂活不能禁工具。审计=用客观事实（stream-json
# 事件流的工具调用记录）判定，不靠模型自判；纯本地字符串/计数，零 token。
# ---------------------------------------------------------------------------
_AUDIT_EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")   # 直改类工具（主会话调用才计）


def _audit_nlines(s):
    """字符串行数（空串=0）——审计行数口径的基础件。"""
    s = str(s or "")
    return s.count("\n") + 1 if s else 0


def _audit_lines(name, inp):
    """v2.34 审计行数口径（写死于此，判定要可复现）：
    - Edit：max(old_string, new_string) 行数——替换影响按两侧较大跨度计。
      不用行数差：删 30 行补 1 行的「瘦身式大改」差值为负/极小，会逃逸。
    - Write：新文件全文行数（空 content 至少计 1——整文件清空也是变更）；
      覆盖写时旧内容事件流里不可得，按全量新增计。
    - NotebookEdit：new_source（cell 新内容）行数；delete 无内容变更计 0。"""
    try:
        if name == "Edit":
            return max(_audit_nlines(inp.get("old_string")),
                       _audit_nlines(inp.get("new_string")))
        if name == "Write":
            # 空 content 也是实质变更（整文件清空/覆盖写空），至少计 1——
            # 计 0 会让「把文件写空」逃逸审计
            return max(1, _audit_nlines(inp.get("content")))
        if name == "NotebookEdit":
            return _audit_nlines(inp.get("new_source"))
    except Exception:
        pass
    return 0


def _audit_hook_settings_path():
    """写 light 形态会话的 --settings 临时文件（v2.40 直改免审线事中闸注入）。

    内容只有 hooks 键：Edit/Write/MultiEdit/NotebookEdit 的 PreToolUse 指向
    `--audit-hook` 子命令（它查 /audit_gate 决定放行/拦截，见
    harness_audit_hook.py）。双形态命令与 _ask_mcp_cfg_path 同构：源码=
    python main.py，打包=exe 自身（src 不在盘上）。

    返回 settings 路径；任何失败返回 None（注入失败不阻塞会话启动——
    铁律：闸是增强不是依赖，回合结算审计仍在兜底）。"""
    try:
        if getattr(sys, "frozen", False):
            parts = [sys.executable, "--audit-hook"]
        else:
            # 路径正斜杠：cmd shim 会吞反斜杠转义（_ask_mcp_cfg_path 实测坑）
            parts = [sys.executable or "python",
                     os.path.join(_SRC_DIR, "main.py").replace("\\", "/"),
                     "--audit-hook"]
        # 每段双引号：解释器装在 Program Files 等带空格路径时裸拼会断
        cmd = " ".join('"%s"' % p for p in parts)
        cfg = {"hooks": {"PreToolUse": [{
            "matcher": "Edit|Write|MultiEdit|NotebookEdit",
            "hooks": [{"type": "command", "command": cmd}]}]}}
        fd, p = tempfile.mkstemp(suffix=".json", prefix="claude_audit_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        return p
    except Exception:
        return None


# v2.34.1：审计警示卡持久化（~/.serialconsole_pro/harness_audit_log.jsonl，
# 每行 {sid, ts, text}，512K 截半——vision_mcp.log 同款惯例）。背景：warn/
# 降级/中断档的卡只 emit 进事件缓冲，transcript_for 回放（解析 jsonl）没有
# 对应行——刷新/切会话即失；auto 档实时卡与续发消息也是两份不同文本。
# 现统一：卡文本=落盘文本=（auto 档）续发消息文本，同一字符串三处共用；
# [审计] user 行在 transcript_for 里不再单独出（卡由本 log 回放，无双份）。
_AUDIT_LOG_MAX = 512 * 1024

# v2.34.2（复审 R1 收口）：审计续发消息的唯一句式前缀。send_message 的
# 「不画气泡」与 transcript_for 的「跳过不出行」都按它判定，与 _audit_settle
# 拼消息处三处引用同一常量——防文案漂移导致判定失效。刻意比 "[审计]" 长：
# 用户手打的以「[审计]」开头的普通消息（质疑机制时引用前缀等）不能被吞，
# 必须照常画气泡/回放（曾用宽前缀 startswith("[审计]")，用户视角「我发的
# 话凭空没了」）。warn/中断/exit 档的卡文案不走 send_message，不受影响。
_AUDIT_MSG_PREFIX = "[审计] 本回合检测到:"


def _audit_iso_now():
    """UTC ISO（Z 后缀，与 CLI 转写 timestamp 同款格式，可直接字符串比较）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _audit_log_append(sid, text):
    """审计卡落盘（追加一行；超限截半保后半）。失败静默——回放缺卡不致命。"""
    try:
        p = os.path.join(_st.HOME_DIR, "harness_audit_log.jsonl")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"sid": sid, "ts": _audit_iso_now(),
                                "text": str(text or "")[:4000]},
                               ensure_ascii=False) + "\n")
        if os.path.getsize(p) > _AUDIT_LOG_MAX:
            with open(p, "r", encoding="utf-8") as f:
                lns = f.readlines()
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(lns[len(lns) // 2:])
    except Exception:
        pass


def _audit_log_read(sid):
    """读该会话的全部审计卡（转写回放合并用）。返回 role='audit' 行列表。"""
    out = []
    try:
        p = os.path.join(_st.HOME_DIR, "harness_audit_log.jsonl")
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if o.get("sid") == sid and o.get("text"):
                    out.append({"role": "audit", "text": str(o["text"])[:4000],
                                "ts": o.get("ts") or ""})
    except Exception:
        pass
    return out


class HarnessSession:
    """一个 stream-json harness 会话（kind='harness'）。

    元数据（sid/title/model/cwd/session_id）持久化；进程是易耗品——
    闲置被回收、切回自动复活（--resume 续上下文）。port_id 稳定 =
    harness:<sid8>，前端 tab 与后端会话一一对应。
    """

    kind = "harness"

    def __init__(self, sid, cwd=None, model=None, session_id=None, title="", name=None,
                 permission=None, think=None, lineage=None):
        self.sid = sid
        self.port_id = "harness:" + sid[:8]
        self.cwd = cwd or os.path.expanduser("~")
        self.model = model or None
        self.session_id = session_id or None    # claude 侧真实会话 id（复活用）
        # v2.27.18 血统链（用户铁律：续命/重开可以，历史回放不能丢）：
        # 超窗续命等场景换过的新会话 session_id 依序记录。transcript_for
        # 按链把新旧 jsonl 串起来渲染——用户视角回放永远完整。
        self.lineage = list(lineage) if lineage else []
        self.title = title or ""
        self.name = name or None    # --name：peer 网络里别人按它寻址
        # v2.20：权限模式（auto=现状自动执行；confirm=写操作前 ask_user 确认）
        # 与思考等级（None=CLI 自主；low/medium/high/max → MAX_THINKING_TOKENS）。
        # 都随会话持久化，新会话 connect 时指定。
        self.permission = permission if permission in ("auto", "confirm") else "auto"
        self.think = think if think in ("low", "medium", "high", "max") else None
        self.hidden = False         # 识图后台会话：不进用户会话列表（不 sync_meta）
        self.is_vision = False      # 识图会话：start() 时用固定的基础提示词
        self.created = int(time.time() * 1000)
        self.last_active = self.created
        # ---- 运行时（进程相关，不持久化）----
        self._proc = None
        self.alive = False
        self.busy = False
        self.busy_since = None   # 本轮处理计时起点 ms（busy 时有效，供前端恢复计时）
        self.bridge_fp = None    # 注入时的识图引导词指纹（send 前热更检测，见 start()）
        self.renewed_at = 0      # v2.27.15：最近一次超窗续命的事件位点（HikLink 等待基准用）
        # v2.27.21：CLI 实报模型名（assistant 事件 message.model）。引导词/
        # 窗口判定以它为准——settings 默认名（如 glm-5.3-flash[1M]）与实跑名
        # （glm-5.3）会错位，三态分类按 settings 名算会把 MCP 类模型判成
        # inline/转交（用户实锤：切方案后仍转交识图会话，白等 7m44s）
        self.live_model = None
        # v2.27.20：peer 回传扫描态。_tr_sid 记路径归属的 session_id（续命/
        # resume 换代后旧路径作废重找）；_tr_lock 防 reader 线程与回传兜底
        # 轮询线程并发扫同一文件（偏移竞争会重复 emit peer 气泡）
        self._tr_sid = None
        self._tr_lock = threading.Lock()
        # v2.17 交互式提问：MCP 工具调用发起的待答问题
        #   {req_id, title, questions, answer, done, ts}
        self.ask = None
        self.ask_lock = threading.Lock()
        self.events = []
        self.events_lock = threading.Lock()
        # v2.25：识图完成状态持久化（最近 result 时刻 + 结论摘要）。/vision_status
        # 原从事件窗口尾部 12 条里回扫，识图轮次密集时 result/assistant 被新事件
        # 挤出窗口 → last_done 归 0，前端「已返回」冒泡整个漏掉（用户多次反馈）
        self.vision_done = {"ts": 0, "brief": ""}
        # v2.34 light 审计回合累计（运行态，不持久化）：lines=本回合主会话
        # 直改（Edit/Write/NotebookEdit）累计行数；dev/reviewer=本回合 Task
        # 派发标记；streak=连续违规回合数（防自动补审死循环：连续 3 回合
        # 违规后降级为仅警示）。回合结算（result/interrupted/exit）清零。
        self._audit = {"lines": 0, "dev": False, "reviewer": False, "streak": 0}
        # v2.40：light 形态事中闸的 --settings 临时文件路径（kill 时清理；
        # revive 重启由 start() 重建——hooks 是进程启动参数，活进程不热更）
        self._audit_settings_path = None
        self._seq = 0
        self.clients = []
        self.clients_lock = threading.Lock()
        self.last_result = None
        base = os.path.basename(os.path.normpath(self.cwd)) or self.cwd
        self.port = "Claude 对话(%s)" % base
        self.baud = None

    # ---- 元数据同步 ----
    def to_meta(self):
        return {"sid": self.sid, "title": self.title, "model": self.model,
                "cwd": self.cwd, "session_id": self.session_id,
                "lineage": self.lineage, "live_model": self.live_model,
                "name": self.name,
                "permission": self.permission, "think": self.think,
                "created": self.created, "last_active": self.last_active,
                # v2.35.2：事件序号随元数据落盘——会话对象被重建（闲置回收/
                # 重启后 _get_or_create）时续号。否则 _seq 归零重计，新事件
                # 序号全部小于前端快照里的旧 seq，被防重放守卫整批吞掉，
                # 会话看起来活着、事件永远不来（切不活跃会话场景的主害之一）
                "seq": getattr(self, "_seq", 0) or 0}

    def sync_meta(self):
        if getattr(self, "hidden", False):
            return          # 识图后台会话不出现在用户会话列表
        with _meta_lock:
            _meta_load()
            _meta[self.sid] = self.to_meta()
        _meta_save()

    # ---- 进程生命周期 ----
    def start(self):
        # 起进程前自愈：base_url 若指向自家代理但代理没在跑（上次强杀残留），
        # claude 读到死端口会全部请求失败——先恢复直连再 Popen（幂等，直连零开销）
        try:
            from src.proxy import ensure_direct_if_proxy_down
            ensure_direct_if_proxy_down("claude_start")
        except Exception:
            pass
        exe, is_shim = _resolve_claude_exe()
        argv = (["cmd.exe", "/c", exe] if is_shim else [exe])
        argv += ["-p",
                 "--input-format", "stream-json",
                 "--output-format", "stream-json",
                 "--verbose",
                 "--permission-mode", "auto"]
        # v2.17：注册交互式提问 MCP（ask_user）。--permission-mode auto 下任何
        # 未预授权的工具都会被权限系统拦下并自动拒绝（headless 没有提示通道），
        # 所以必须用 --allowedTools 预授权，否则 ask_user 调用直接失败。
        # --mcp-config 是追加式的（实测：内置 codegraph/headroom 等仍在），
        # 不会覆盖用户已有的 MCP。
        if not self.is_vision:
            _cfg = _ask_mcp_cfg_path(self.sid, self.permission)
            if _cfg:
                argv += ["--mcp-config", _cfg]
                # v2.28.5：本地兜底识图工具随开关门控（与 --mcp-config 同步）；
                # 网关主通道名也保留预授权（个别链路网关不拦截时可客户端执行）
                _tools = ["mcp__harness__ask_user"]
                if _vision_load()["enabled"]:
                    _tools += ["mcp__4_5v_mcp__analyze_image",
                               "mcp__vision__analyze_image"]
                argv += ["--allowedTools", ",".join(_tools)]
        # v2.14：识图后台会话用固定基础提示词；普通会话走用户提示词体系 +
        # 识图转交引导（主会话默认不知道有识图同伴，必须显式告知）。
        if self.is_vision:
            sys_prompt = (_vision_load().get("prompt") or "").strip()
            self.bridge_fp = None   # 识图会话自身不参与引导词热更
        else:
            # v2.20：model=None 的会话实际跑 settings 默认模型——多模态判定
            # 必须按实际模型来，否则默认多模态模型也被教去转交识图会话
            # v2.27.21：实报名（live_model）优先——revive 换词重启时按真实
            # 在跑模型注入（settings 名与实报名错位是转交 bug 的真根因）
            eff_model = self._eff_model()
            roles_txt = roles_bridge_text(eff_model)
            if roles_txt:
                # 角色定义随工具分发：起会话前按当前形态安装到
                # ~/.claude/agents/（幂等，强模型→executor/coder，
                # 轻快模型→designer）——别的机器零手工配置
                install_roles_agents(eff_model)
            parts = [_collect_system_prompt(self.cwd),
                     TOKEN_RULES,
                     roles_txt,
                     vision_bridge_text(eff_model),
                     ask_bridge_text()]
            if self.permission == "confirm":
                parts.append(confirm_bridge_text())
            sys_prompt = "\n\n".join(p for p in parts if p)
            # v2.27.13：记注入时的引导词指纹——系统提示是进程启动参数，
            # 活会话不会因代码升级/名单调整换新词（用户实锤：MCP 类模型
            # 揣着旧「转交版」绕识图会话白等 1m20s）。send 前对指纹热更。
            self.bridge_fp = _bridge_fp(eff_model)
            # v2.29 三角色：决策者结构性禁权——干活工具全禁（Bash/Edit/Write/
            # WebFetch/WebSearch/Glob/Grep），逼着它走 Task 派发给 executor/
            # coder；保留 Read 供审核代码用。子代理有自己的工具表不受影响。
            # v2.30.2：仅决策者形态（主会话强模型）挂禁权；轻主力形态主会话
            # 要亲自干杂活，工具不能禁（roles_disallow 返回空串）。留在 else
            # 分支内——eff_model 只在此定义（曾放分支外，识图会话路径直接
            # NameError；现 is_vision 已退役不可达，防御性归位）。
            _roles_ban = roles_disallow(eff_model)
            if _roles_ban:
                argv += ["--disallowedTools", _roles_ban]
            elif self._audit_state() is not None:
                # v2.40 light 形态事中闸：直改免审线硬拦截。与 strong 禁权
                # 互斥共存（strong 全禁了 Edit 根本到不了闸；light 不禁工具
                # ——主会话要干杂活，改用 PreToolUse hook 在直改累计达线时
                # exit 2 拦下。回合结算审计只能事后补审，这里把超线掐灭在
                # 发生前，双层）。_audit_state 非 None=roles 开+light+
                # audit_mode!=off，与结算审计同源判定（audit_mode=off 时
                # 闸与审计同步关）；注入失败照常启动（闸失效不阻塞工作）。
                _p = _audit_hook_settings_path()
                if _p:
                    self._audit_settings_path = _p
                    argv += ["--settings", _p]
        if sys_prompt:
            argv += ["--append-system-prompt", sys_prompt]
        if self.name:
            argv += ["--name", self.name]     # peer 寻址名（识图会话靠它被找到）
        # 复活：claude 侧已有真实 session_id → --resume 续上下文
        if self.session_id:
            argv += ["--resume", self.session_id]
        if self.model:
            argv += ["--model", self.model]
        env = dict(os.environ)
        env.setdefault("TERM", "dumb")
        # v2.20：思考等级 → CLI 的 MAX_THINKING_TOKENS（透传到网关/模型侧
        # 的 thinking budget；不支持时被忽略，无害）
        if self.think:
            env["MAX_THINKING_TOKENS"] = str(
                {"low": 4096, "medium": 10240, "high": 20480, "max": 31999}[self.think])
        _trust_workspace(self.cwd)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            argv, cwd=self.cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
        self.alive = True
        self.busy = False
        # v2.35：本进程实例已见的 init 事件数——第 2 个起是「新回合起跑」
        # （CLI 自发回合：后台任务完成通知/协作回传续跑），据此补置 busy
        self._init_n = 0
        self.last_active = int(time.time() * 1000)
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _audit_settings_cleanup(self):
        """v2.40：删事中闸 --settings 临时文件并清引用（claude 启动时已读
        完；revive 重启会重建新文件）。kill_proc 与 reader loop 自然死亡
        路径（finally 不走 kill_proc）都要调——漏后者的话 revive 的 start()
        覆盖 _audit_settings_path，旧文件每次死亡-复活泄漏一个到 %TEMP%。"""
        _p = getattr(self, "_audit_settings_path", None)
        if _p:
            self._audit_settings_path = None
            try:
                os.remove(_p)
            except Exception:
                pass

    def kill_proc(self, quiet=False):
        """只杀进程保元数据与事件缓冲（闲置回收/复活前清理用）。
        v2.14：强杀会让 claude 来不及清理 peer 注册条目（~/.claude/sessions/
        <pid>.json），残留条目指向死 pid —— 下次 ListAgents 会看到幽灵会话。
        所以杀完主动清理自己那条注册。
        v2.20：quiet=True 吞掉随之而来的 exit 事件——会话内切模型重启进程
        是计划内动作，不该弹「会话进程已结束」吓人。
        v2.25：进程已死透（reader loop 早已收尾）时不设 _suppress_exit——
        标志位无人消费会残留，吞掉下一次真正的意外退出（两次切模型且
        中间进程已自然退出的触发链）。"""
        self.alive = False
        self.busy = False
        self._audit_settings_cleanup()
        if quiet:
            proc_alive = bool(self._proc and self._proc.poll() is None)
            if proc_alive:
                self._suppress_exit = True
        self.ask_cancel()       # v2.17：别让 MCP 侧的提问继续空转等
        proc, self._proc = self._proc, None
        if proc is not None:
            pid = None
            try:
                pid = proc.pid
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            if pid or self.session_id:
                _cleanup_peer_reg(pid, self.session_id)

    def close(self):
        self.kill_proc()
        try:
            if getattr(self, "reader", None) and self.reader.is_alive():
                self.reader.join(timeout=1.0)
        except Exception:
            pass

    def revive_if_dead(self):
        """已死会话复活（有 claude session_id 才能续上下文）。返回能否用。"""
        if self.alive:
            return True
        if not self.session_id:
            return False
        try:
            self.start()
            return True
        except Exception:
            return False

    # ---- 输入 ----
    def _is_remote_bot_session(self):
        """本会话是否 HikLink 小助手专属会话（远程通道，无人在场）。
        判定：hiklink 单例记着的 harness sid 就是本会话（controller 在但
        sid 对不上=GUI 会话，不能静默换会话）。"""
        try:
            from src import hiklink_bot as hb
            ctl = hb._controller
            return bool(ctl and ctl._sid and ctl._sid == self.sid)
        except Exception:
            return False

    def _eff_model(self):
        """v2.27.21：有效模型名——CLI 实报（live_model）优先于会话 model
        优先于 settings 默认。识图三态/上下文窗口判定统一走这里：实报名
        才是真正在跑的模型（settings 名经网关映射后可能完全不同，实测
        flash 名义 inline vs 实跑 glm-5.3 应为 mcp，错位导致错误引导词）。"""
        return self.live_model or self.model or available_models().get("default")

    # ---- v2.34 light 形态回合结算审计 ----
    def _audit_tally(self, o):
        """回合内审计累计：只记主会话调用——子代理事件带 parent_tool_use_id
        一律不算（它们有自己的纪律，主会话的违规才算违规）。纯计数不读
        配置（每事件零盘 IO），判不判定是 _audit_settle 结算时的事。"""
        au = self._audit
        if o.get("parent_tool_use_id"):
            return
        blocks = (o.get("message") or {}).get("content")
        if not isinstance(blocks, list):
            return
        for b in blocks:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            n = str(b.get("name") or "")
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            if n in _AUDIT_EDIT_TOOLS:
                au["lines"] += _audit_lines(n, inp)
            elif n in ("Task", "Agent"):
                st = str(inp.get("subagent_type") or inp.get("agent_type") or "")
                if st == "dev":
                    au["dev"] = True
                elif st == "reviewer":
                    au["reviewer"] = True

    def _audit_state(self):
        """审计现值：(audit_mode, max_free_lines)；不审计返回 None。
        条件=roles 开 + light 形态（strong 有结构禁权不需要）+ audit_mode
        != off。结算时读一次盘——配置改动回合间生效。"""
        try:
            from .harness_roles import roles_cfg, roles_mode
            cfg = roles_cfg()
            mode = str(cfg.get("audit_mode") or "auto")
            if not cfg.get("enabled") or mode == "off":
                return None
            if roles_mode(self._eff_model()) != "light":
                return None
            try:
                # 不用 `or 3` 兜底——那会把合法的 0（最严档：任何直改都
                # 违规）吞成 3。缺键/None → int() 抛 TypeError 落默认 3
                mf = int(cfg.get("max_free_lines"))
            except (TypeError, ValueError):
                mf = 3
            return mode, max(0, mf)
        except Exception:
            return None

    def _audit_settle(self, reason):
        """回合结算审计（result/interrupted/exit 三处调用）。盘点本回合：
        违规两条——① 主会话直改累计行数 > 免审线且无 reviewer 派发；
        ② 有 dev 派发但无 reviewer 派发。兜底按 audit_mode：auto=回合结束
        自动续发一条 [审计] user 消息要求补审（复用 send_message 管线，
        busy/进程/指纹热更检查全继承）；warn=仅聊天流红色警示（前端
        kind='audit' 事件）。防循环：连续 3 个违规回合后降级仅警示；中断/
        进程退出只警示不续发（用户主动停/进程已死，续发无意义，且不计入
        streak）。计数结算后清零（切片逃逸防护：多次小改按回合累计判定）。"""
        au = self._audit
        lines, dev, rev = au["lines"], au["dev"], au["reviewer"]
        au.update({"lines": 0, "dev": False, "reviewer": False})
        st = self._audit_state()
        if st is None:
            au["streak"] = 0
            return
        mode, max_free = st
        viol = []
        if lines > max_free and not rev:
            viol.append("主会话直改累计 %d 行超过免审线 %d 行，且本回合未派 "
                        "reviewer 审核" % (lines, max_free))
        if dev and not rev:
            viol.append("已派 dev 交付但未派 reviewer 对抗审核")
        if not viol:
            au["streak"] = 0
            return
        desc = "；".join(viol)
        if reason == "result":
            au["streak"] += 1
        degraded = au["streak"] >= 3
        if reason == "result" and mode == "auto" and not degraded:
            # 自动补审：卡文本与续发消息同一字符串（v2.34.1 统一——实时/
            # 落盘回放/模型所见三处一致）。续发走后台线程，send_message 与
            # 用户抢发竞争时返回失败——静默记 log，卡已到位，不重试。
            text = (_AUDIT_MSG_PREFIX + "%s。已自动续发补审指令——立即用 "
                    "Task 工具派 reviewer 代理补审上述改动（对抗审核：只审"
                    "不改，给 PASS/FAIL 结论），按结论处理：FAIL 派 dev 修复"
                    "后复审，PASS 才算完成，然后再答复用户。不要辩解，直接"
                    "补审。" % desc)
            self._audit_card(text)
            threading.Thread(target=self._audit_send, args=(text,),
                             daemon=True).start()
            return
        why = {"interrupted": "（回合被中断，仅记录不自动补审）",
               "exit": "（会话进程已退出，仅记录不自动补审）"}.get(reason, "")
        tail = ("已连续 %d 个回合违规，自动补审已降级为仅警示（防循环烧 "
                "token），请人工介入。" % au["streak"]) if degraded else \
               ("审计模式为 %s，仅警示不自动续发——请手动派 reviewer 补审。"
                % mode)
        self._audit_card(_AUDIT_MSG_PREFIX + "%s。%s%s" % (desc, tail, why))

    def _audit_card(self, text):
        """审计警示卡：emit（实时 SSE 红卡）+ 落盘 audit log（回放持久）。
        v2.34.1 前只 emit——warn/降级/中断档的卡不落转写，刷新/切会话即失。"""
        self.emit({"kind": "audit", "text": text[:4000]})
        _audit_log_append(self.sid, text)

    def _audit_send(self, text):
        """审计自动续发：补审指令作为 user 消息发回本会话（模型视角=用户
        要求补审），走正常 send_message 管线。text 以 _AUDIT_MSG_PREFIX
        开头 → send_message 里不画用户气泡（警示事件已由 _audit_settle 先行
        emit）。失败静默（log）——用户抢先发消息/进程退出属正常竞争，不重试
        不阻塞。"""
        try:
            ok, err = self.send_message(text)
            if not ok:
                log.warning("[审计] 补审续发未发出：%s", err)
        except Exception as e:
            log.warning("[审计] 补审续发异常：%s", e)

    def _autorenew_on_overflow(self, text, image_paths, file_paths,
                               used, mwin, eff_model):
        """超窗自动续命（v2.27.15，仅小助手这类远程无人在场会话）。
        旧会话上下文已超当前模型窗口（切 API 方案模型变小所致）——拒发的话
        手机侧永远收不到回复。做法：导出旧对话主干注入新会话首条消息，
        self 改指新 claude session_id（对外 sid 不变，用户无感），
        再把本条消息作为正常轮次发出。返回 True=已续命并已发送。
        失败路径返回 False 走原有拒发提示（别把用户消息吞了）。"""
        if getattr(self, "is_vision", False):
            return False   # 识图配角会话不续命
        try:
            from src.claude_sessions import export_session_transcript
            lines, _cwd = export_session_transcript(self.session_id)
        except Exception:
            return False
        if not lines:
            return False   # 导不出历史（文件没了/空）→ 没有可迁移的东西
        # 历史注入首条消息：远超窗口的完整历史没法塞，按轮次收尾的对话主干
        # 足够新会话延续任务记忆。角色对齐精简格式，长块截断防超窗复发。
        parts = []
        for ln in lines:
            role = {"user": "用户", "assistant": "助手",
                    "tool": "（工具）", "system": "（摘要）"}.get(ln.get("role"), "（其他）")
            parts.append("%s：%s" % (role, (ln.get("text") or "").strip()))
        hist = "\n".join(parts)
        # 旧历史压缩到新窗口的 ~60%（给回复/工具留余量），超长从头截断保最近
        budget = int(mwin * 0.6)
        if len(hist) > budget:
            hist = "……（更早历史已截断）\n" + hist[-budget:]
        old_title = self.title
        # 换新 claude 会话：杀旧进程（元数据保留）、清 session_id 全新 start。
        # 不能走 revive_if_dead——它要求 session_id 非空（--resume 语义），
        # 这里恰恰是开新会话，必须裸 start。
        # v2.27.18：旧 session_id 记入血统链——transcript_for 按链串接历代
        # jsonl，历史回放不丢（用户铁律：重开可以，回放不能丢）。
        self.kill_proc(quiet=True)
        if self.session_id:
            self.lineage = list(getattr(self, "lineage", None) or []) + [self.session_id]
        self.session_id = None
        self.title = None           # 让首条真实消息重新定标题
        try:
            self.start()
        except Exception as e:
            log.warning("超窗续命：新会话启动失败 %s", e)
            return False
        seed = ("[系统] 上一会话上下文已超当前模型窗口，自动重开。以下是此前"
                "对话历史记录，请据此延续原有任务脉络：\n\n%s\n\n[系统] 历史结束。"
                % hist)
        ok, err = HarnessSession.send_message(self, seed)
        if not ok:
            log.warning("超窗续命：历史注入失败 %s", err)
            return False
        # 等注入轮完成再发用户本条（不并发写 stdin）
        deadline = time.time() + 600
        while time.time() < deadline and self.busy:
            time.sleep(1)
        if self.busy:
            return False   # 注入轮 10 分钟没跑完，放弃（消息原样走拒发）
        self.title = old_title or self.title
        self.sync_meta()
        # 续命位点：调用方（HikLink _run_cmd）据此把等待基准挪到用户本条
        # turn——注入轮的 result 不算数，否则推空「没有文本回复」
        self.renewed_at = self._seq
        ok, err = HarnessSession.send_message(self, text or "", image_paths, file_paths)
        if not ok:
            log.warning("超窗续命：重发用户消息失败 %s", err)
            return False   # 用户消息没发出去 → 走拒发提示，别静默吞
        return True

    def send_message(self, text, image_paths=None, file_paths=None):
        """发消息：文本 + 可选图片（base64 块，实测网关透传）+ 文件路径（文本
        附录，任何模型都能用 Read 读）。返回 (ok, err)。"""
        # 上下文超窗拒发（用户定调）：切 API 方案会把模型强制跟着切小窗
        # （快照带模型映射），1M 会话攒超 256K 后发消息必 400 prompt is
        # too long（实测 267112 > 262144）——直接拦在发送前并给出路。
        # 3% 余量：prompt 除历史外还有 system/工具定义等固定开销。
        # /compact 后 _session_ctx_used 撞压缩边界归零，即可继续发。
        try:
            eff_model = self._eff_model()
            if eff_model and self.session_id:
                used, _w, _c = _session_ctx_used(self)
                # v2.27.22：窗口走候选链（配置名后缀优先）——实报裸名无 [1M]
                # 信息，单看它 1M 会话会被判成 256K 误拒（用户实锤）
                mwin = _session_ctx_window(self)
                if used and used >= int(mwin * 0.97):
                    # v2.27.15：小助手自动续命（用户定调：超窗时自动重开会话
                    # 并映射旧链接，手机侧无感）。500K 历史塞不进 256K 窗口，
                    # headless 也无手动 /compact 入口——唯一出路是开新会话：
                    # 导出旧对话主干 → 首条消息注入历史 → 改 session_id 映射，
                    # 用户视角「还是那个小助手」。只有远程通道（HikLink 小
                    # 助手）无人在场才自动续命——GUI 会话有人看着提示即可，
                    # 静默换会话违背「我不同意方案A」的定调。
                    if self._is_remote_bot_session() and \
                            self._autorenew_on_overflow(text, image_paths, file_paths,
                                                        used, mwin, eff_model):
                        return True, None
                    # v2.28.10：/compact 是超窗的解药，守卫必须放行——否则满窗
                    # 时唯一出口被自己锁死（用户实锤：手动压缩发不出去，红条
                    # 就是拒发语）。压缩后 _session_ctx_used 撞压缩边界归零。
                    # v2.28.11：爆死态（单轮巨量注入，如 Read 大图）连 /compact
                    # 都压不动（压缩请求自身超窗）——/rewind 回退是终极逃生门。
                    if not (text or "").lstrip().startswith("/compact"):
                        return False, ("当前上下文已约 %dK tokens，超过模型「%s」"
                                       "的 %dK 窗口——可 /rewind 回退上一回合"
                                       "（强烈推荐，立即恢复），或 /compact 压缩"
                                       "（爆死态可能压不动），或新建会话"
                                       % (round(used / 1024),
                                          eff_model,
                                          round(mwin / 1024)))
        except Exception:
            pass   # 检测自身失败不拦发送（读不到用量时维持原行为）
        # base_url 死代理自愈的第二时机（用户实锤）：start 里的自愈只在起
        # 进程时跑——claude 启动时代理还活着、之后代理被停，进程不死就永远
        # 不走 start，消息全打进死端口。发送前发现 base_url 已恢复直连，
        # 就重启进程换新配置（有 session_id 则复活续上下文，本条照常发）。
        if self.alive and not self.busy:
            try:
                from src.proxy import ensure_direct_if_proxy_down
                if ensure_direct_if_proxy_down("claude_send"):
                    self.kill_proc(quiet=True)
                    if not self.revive_if_dead():
                        return False, "会话进程已退出（base_url 已恢复直连，请重发）"
            except Exception:
                pass
            # v2.27.13：识图引导词过期热更——系统提示是进程启动参数，代码升级
            # / mm_mcp 名单调整后活会话仍揣旧词（用户实锤：MCP 类模型被旧
            # 「转交版」带去绕识图会话白等）。指纹变了就 kill+resume 静默换新
            # （与切模型同款，上下文保留），本条消息照常发。
            if self.alive and self.bridge_fp is not None:
                try:
                    eff_model = self._eff_model()
                    if _bridge_fp(eff_model) != self.bridge_fp:
                        self.kill_proc(quiet=True)
                        if not self.revive_if_dead():
                            return False, "会话进程已退出（识图引导词已更新，请重发）"
                except Exception:
                    pass
            # v2.37（P0+）派发前自愈：Task/SendMessage 派发前确保本形态角色
            # 定义在位（幂等重装，几毫秒）——兜住一切上游删除路径（旧版互清/
            # 测试误清/人工误删）。发生过缺失自愈时红卡告警：此前派发可能
            # 已回落主链轻模型，用户须知情。仅角色开关启用时介入。
            try:
                from .harness_roles import ensure_roles_ready
                _miss = ensure_roles_ready(self._eff_model())
                if _miss:
                    self.emit({"kind": "audit",
                               "text": "检测到角色定义缺失（%s）已自动恢复——"
                                       "此前派发可能回落主链模型，建议重发该任务"
                                       % "、".join(m[:-3] for m in _miss)})
            except Exception:
                pass
        if not self._proc or not self.alive:
            return False, "会话进程已退出"
        self.busy_since = int(time.time() * 1000)   # 处理计时起点（前端切会话回来显示真实已跑时长）
        if self.busy:
            return False, "claude 正在回复中，请稍候"
        # v2.25：先占 busy 再写 stdin——写在后置位时两个并发 /send 都能穿过
        # 检查，两条 NDJSON 行交叠写进管道。失败路径就地下面的 return 处复位。
        self.busy = True
        content = []
        for p in (image_paths or []):
            try:
                with open(p, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(p)[1].lower().lstrip(".") or "png"
                media = "image/" + ("jpeg" if ext in ("jpg", "jpeg") else ext)
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": media, "data": data}})
            except Exception:
                continue
        full_text = text or ""
        att = list(image_paths or []) + list(file_paths or [])
        if att:
            att_lines = "\n".join(att)
            full_text = (full_text + "\n\n" if full_text else "") + \
                "[附件，可用 Read 工具读取]\n" + att_lines
        if not full_text and not content:
            self.busy = False
            return False, "消息为空"
        if not full_text and content:
            full_text = "请查看图片"
        if content:
            content.append({"type": "text", "text": full_text})
        else:
            content = full_text
        try:
            payload = {"type": "user", "message": {"role": "user", "content": content}}
            self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except Exception as e:
            self.busy = False
            return False, "发送失败：%s" % e
        self.last_active = int(time.time() * 1000)
        # v2.34.2（R1）：判定收窄到 _AUDIT_MSG_PREFIX（_audit_settle 续发
        # 消息的唯一句式开头）——不定标题、不画用户气泡（警示已由
        # _audit_settle 的 kind='audit' 事件先行呈现）。用户手打「[审计]…」
        # 开头的普通消息不命中，照常走 user_echo 画气泡。
        _audit_msg = (text or "").lstrip().startswith(_AUDIT_MSG_PREFIX)
        # 首条消息定标题（微信式：会话标题=首句）
        if not self.title and text and not _audit_msg:
            self.title = re_title(text)
            self.sync_meta()
        # v2.27.23：超窗续命的 [系统] 历史注入不推原文——几十万 token 刷满
        # 消息流（用户定调"后台化"）。改推 renew 分割线事件，前端一行带过。
        if _audit_msg:
            pass
        elif (text or "").lstrip().startswith("[系统] 上一会话上下文已超当前模型窗口"):
            rounds = sum(1 for _ln in text.splitlines()
                         if _ln.startswith(("用户：", "助手：")))
            self.emit({"kind": "renew",
                       "text": "上下文超窗，已自动重开会话（%d 轮历史已后台迁移）" % rounds})
        else:
            self.emit({"kind": "user_echo", "text": text or "",
                       "images": list(image_paths or []), "files": list(file_paths or [])})
        return True, None

    def interrupt(self):
        """中断当前回复：kill 进程（claude 中断语义无 stdin 通道，杀进程即停），
        事件缓冲保留，下次发送自动复活续上下文。"""
        if not self.alive or not self.busy:
            return False, "当前没有进行中的回复"
        threading.Thread(target=self._interrupt_async, daemon=True).start()
        return True, None

    def _interrupt_async(self):
        # v2.25：去掉 stdin 空写探活——0 字节写对部分 CLI 会被当作 EOF/空行
        # 事件（审计 §三.10），且探活结果无人消费，紧随的 kill 已覆盖停机语义
        self.kill_proc()
        # v2.34：中断也结算审计——直改半截/审核跳过同样算违规记录（仅警示
        # 不续发：用户主动停，续发违背意图）。须在 emit interrupted 前调，
        # 警示先于「已中断」行出现。
        try:
            self._audit_settle("interrupted")
        except Exception:
            pass
        self.emit({"kind": "interrupted", "text": "已中断回复"})

    # ---- 事件层 ----
    def _check_peer_lines(self):
        """跨会话回传检测（v2.27.4）：CLI 收到 peer 消息只写转写 jsonl，
        不往 stdout 流吐 user 事件（实测事件缓冲里 495 条 system 全是
        thinking_tokens，零 peer 信号）——前端永远看不到回传。这里在回合
        有输出（assistant/result 事件）时增量扫转写尾部，新出现的 peer
        行（origin.kind=peer）先于该事件下发 kind:'peer'，前端渲染📥气泡。
        首次调用只建立偏移基线（跳过历史），之后每次只读新增字节。"""
        try:
            if not self.session_id:
                return
            # v2.27.20：reader 线程与回传兜底轮询线程都会进来——锁住防偏移
            # 竞争重复 emit（两线程同时读同一段增量，peer 气泡画两份）。
            # v2.3.2 审计 P7：换代重置（_tr_sid 比对+三字段清空）也挪进锁内——
            # 原在锁外，线程 B 清空 _tr_off 后，锁内读到一半的线程 A 用
            # f.tell() 把 None 覆写回旧文件偏移，旧偏移对着新文件用（错位/漏行）
            with self._tr_lock:
                # v2.27.20：session_id 变了（超窗续命换代 / resume 分叉）——缓存
                # 的转写路径还指着旧文件，新文件的 peer 行永远扫不到（换代后
                # 回传"凭空消失"的第二个根因）。归属不符即作废重找、重立基线。
                if getattr(self, "_tr_sid", None) != self.session_id:
                    self._tr_sid = self.session_id
                    self._tr_path = None
                    self._tr_off = None
                if not getattr(self, "_tr_path", None):
                    import glob as _g
                    for cand in _g.glob(os.path.join(os.path.expanduser("~"),
                                         ".claude", "projects", "*", self.session_id + ".jsonl")):
                        self._tr_path = cand
                        break
                path = getattr(self, "_tr_path", None)
                if not path:
                    return
                try:
                    size = os.path.getsize(path)
                except OSError:
                    # v2.27.20：转写文件被清理（外部清缓存等）——清缓存下轮
                    # 重找，别每 5s 抛一次被吞的异常空转
                    self._tr_path = None
                    return
                off = getattr(self, "_tr_off", None)
                if off is None:            # 基线：从文件末尾起，历史 peer 不重放
                    self._tr_off = size
                    return
                if size < off:             # 截断/轮转 → 重扫全量
                    off = 0
                if size == off:
                    return
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(off)
                    chunk = f.read()
                    self._tr_off = f.tell()
            for ln in chunk.splitlines():
                ln = ln.strip()
                if not ln or ("Another Claude" not in ln and '"peer"' not in ln):
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if o.get("type") != "user":
                    continue
                t = (o.get("message") or {}).get("content")
                # v2.3.2 两形态（用户实锤「模型收到了前台没显示」）：
                # 独立行=空闲期到达，origin.kind=peer、正文以标记开头（原逻辑）；
                # 内嵌行=busy 期到达被 CLI 排队，回合结束注入进下一轮用户消息
                # （system-reminder 包装，origin 是 human）——此前检测不到，
                # 模型收到了但前端永远无气泡。走到这里的含标记 user/str 统一解析
                # （内嵌型须带 <cross-session-message 标签收窄，防用户手打误报）。
                if not isinstance(t, str) or \
                        "Another Claude session sent a message" not in t:
                    continue
                if (o.get("origin") or {}).get("kind") != "peer" and \
                        "<cross-session-message" not in t:
                    continue
                # v2.3.2 审计 1a 误报收窄：非 peer origin（内嵌型）还须 system-reminder
                # 壳在标记之前——CLI 排队注入的固定形态；用户手贴回传原文/贴原始
                # jsonl 排查问题时通常不带这层壳，不再弹假回传气泡
                _mp = t.find("Another Claude session sent a message")
                if (o.get("origin") or {}).get("kind") != "peer" and _mp > 0:
                    if t.find("<system-reminder") < 0 or \
                            t.find("<system-reminder") > _mp:
                        continue
                nm = re.search(r'from-name="([^"]*)"', t)
                body = re.search(r"<cross-session-message[^>]*>(.*)</cross-session-message>",
                                 t, re.S)
                # v2.27.5：peer 消息会触发自动回合，但没走 harness send()——
                # busy 从未被置起，活动指示条不亮（用户实锤）。这里补置，
                # result 事件照常回落；前端 5s 轮询据此亮指示条+计时。
                # v2.27.19：只在进程活着时置——死会话（回传兜底轮询扫到的）
                # 没有 result 来回落，置了会永远挂「回复中」
                if self.alive:
                    self.busy = True
                    self.busy_since = int(time.time() * 1000)
                self.emit({"kind": "peer",
                           "name": nm.group(1) if nm else "其他会话",
                           "text": ((body.group(1) if body else t).strip())[:8000]})
        except Exception:
            pass

    def _relay_vision_reply(self, o):
        """v2.3.2：识图会话回传代播——它的 assistant 事件流里出现 SendMessage
        tool_use 时，把结论（input.message）直接广播给所有主会话（emit kind='peer'
        附 to=收件人 peer 名）。主会话 busy 时 CLI 运行时注入不留 jsonl 痕迹，
        这是唯一可靠的观测点。前端按转交线收件人名匹配渲染，错发无污染。"""
        try:
            blocks = (o.get("message") or {}).get("content") or []
            if not isinstance(blocks, list):
                return
            for b in blocks:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"
                        and b.get("name") == "SendMessage"):
                    continue
                inp = b.get("input") or {}
                to = str(inp.get("to") or "")
                msg = str(inp.get("message") or "").strip()
                if not msg:
                    continue
                name = getattr(self, "name", None) or "识图会话"
                with _sessions_lock:
                    targets = [s for s in _sessions.values()
                               if not getattr(s, "is_vision", False)]
                for s in targets:
                    s.emit({"kind": "peer", "name": name, "to": to,
                            "text": msg[:8000]})
        except Exception:
            pass

    def _reader_loop(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line_b in proc.stdout:
                if not self.alive:
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self.last_active = int(time.time() * 1000)
                try:
                    o = json.loads(line)
                except Exception:
                    self.emit({"kind": "raw", "text": line})
                    continue
                typ = o.get("type")
                # v2.3.0：thinking_tokens 进度心跳不转发——CLI 思考期间逐条推
                # 「已思考约 N tokens」（每秒 1~3 条），前端零消费（活动指示条
                # 计时是前端自算），但每条都要 SSE 推送+前端 parse+分派再丢弃，
                # 且刷爆 4000 条事件缓冲把有价值的重放事件挤出去（实测单会话
                # 缓冲 495 条全是它）。思考内容（thinking 块）/回复文本（text
                # 块）走完全不同的事件，不受影响。
                if typ == "system" and o.get("subtype") == "thinking_tokens":
                    continue
                if typ == "system" and o.get("session_id") and o.get("subtype") == "init":
                    if o.get("session_id") != self.session_id:
                        self.session_id = o.get("session_id")
                        self.sync_meta()
                    # v2.35（P0-1 根因修复）：CLI 自发回合（后台任务完成通知、
                    # 协作回传续跑等）不经 send()，busy 从未被置起——事件流里
                    # 模型在干活、会话列表却报空闲，前端 5s 自愈轮询据此把运行
                    # 态徽章摘掉（用户实锤「AI 还在执行运行状态没了」），排队泵
                    # 还会提前把队列消息打进正在跑的回合。stream-json 实测
                    # （stdin 保持打开）：每回合起跑都发一条 system/init，首个
                    # init 是进程待机（不能置，否则空转进程永远挂「回复中」），
                    # 第 2 个起即新回合——此刻补置 busy，回合终结的 result 照常
                    # 回落。revive/热更重启的「新进程首 init」不置：该路径随后
                    # 必有 send() 占位，不靠这里。
                    self._init_n = getattr(self, "_init_n", 0) + 1
                    if self._init_n > 1 and self.alive and not self.busy:
                        self.busy = True
                        self.busy_since = int(time.time() * 1000)
                # v2.35（P0-1 兜底）：主链 assistant 事件到达而 busy 仍 False =
                # 一条我们没观察到起点的回合正在跑（init 丢失/旧版 CLI 无续
                # init）——同样补置。子代理事件（带 parent_tool_use_id）不算：
                # 后台子代理跑活时主会话本就空闲、可以收新消息。
                if typ == "assistant" and not o.get("parent_tool_use_id") \
                        and self.alive and not self.busy:
                    self.busy = True
                    self.busy_since = int(time.time() * 1000)
                if typ == "result":
                    self.busy = False
                    self.last_result = o
                    # v2.2.1：回合结束落一次盘——last_active 平时只更新内存，
                    # 重启工具后 meta 停在旧时刻会话排序/时间倒退（回合粒度
                    # 写盘，频次可接受；每行写则太频）
                    try:
                        self.sync_meta()
                    except Exception:
                        pass
                if typ == "assistant":
                    # v2.27.21：记录 CLI 实报模型名——引导词热更/窗口判定
                    # 的第一依据（settings 名会与实跑名错位，见 _eff_model）。
                    # 只记录不打断：若与注入词的三态分类不一致，下一次 send
                    # 前的 bridge_fp 热更自然发现指纹变化并换词重启
                    lm = (o.get("message") or {}).get("model")
                    if lm and lm != self.live_model:
                        self.live_model = lm
                        self.sync_meta()
                    # v2.3.2 第三形态（用户实锤「识图跑完回传没显示」）：目标
                    # 会话 busy 时，CLI 把回传以运行时通知直接注入其当前回合，
                    # **jsonl 零痕迹**——主会话侧扫盘永远无解。改在识图会话侧
                    # 截获：它发出的 SendMessage tool_use（input.to/message 现成）
                    # → 向全部非 vision 会话广播 kind='peer'（带 to 字段），前端
                    # 按转交线上的收件人名对号入座渲染，无污染。
                    if getattr(self, "is_vision", False):
                        self._relay_vision_reply(o)
                    # v2.34：回合内审计累计（纯计数零盘 IO；子代理事件内部
                    # 自行排除，见 _audit_tally）
                    self._audit_tally(o)
                if typ in ("assistant", "result"):
                    self._check_peer_lines()   # 回合有输出 → 先补发新到的 peer 回传
                self.emit({"kind": "event", "data": o})
                # v2.34：result 即回合终点——结算审计（light 形态违规兜底，
                # 事件已 emit，前端先收 result 收尾再收审计警示，顺序自然）
                if typ == "result":
                    try:
                        self._audit_settle("result")
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            was_busy = self.busy    # v2.34：进程死时回合是否仍在进行（下方结算用）
            self.alive = False
            self.busy = False
            # v2.40：自然死亡不走 kill_proc——事中闸 settings 临时文件在这
            # 条路径也要清（否则 revive 覆盖引用后旧文件泄漏，见方法注释）
            self._audit_settings_cleanup()
            # v2.20：计划内重启（会话内切模型）吞掉 exit——只吞一次，
            # 防止标志位残留吞掉真正的意外退出
            if getattr(self, "_suppress_exit", False):
                self._suppress_exit = False
            else:
                # v2.34：回合进行中进程死掉（崩溃/被杀）——结算审计只警示
                # 不续发（进程已死）。was_busy 在 busy 复位前取：kill_proc
                # 会先把 busy 清掉，正常 result 后的进程退出不算「回合中断」。
                if was_busy:
                    try:
                        self._audit_settle("exit")
                    except Exception:
                        pass
                self.emit({"kind": "exit", "text": "会话进程已结束（发送消息将自动恢复）"})

    def _drain_stderr(self):
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                if not self.alive:
                    break
                txt = line.decode("utf-8", errors="replace").strip()
                if not txt:
                    continue
                # v2.13：CLI stderr 良性日志过滤——unrecognized_model 是 CLI
                # 对非内置名（Lanz-*）的提醒，模型实际回退默认照常跑（实测 rc=0
                # 输出正常）；原样 emit 成 raw 事件会在界面显示红字，用户实测
                # 误以为是模型失效。真失效走 API 400（result 事件已有独立提示）。
                if "unrecognized_model" in txt or "claude-code:" in txt and "warning" in txt.lower():
                    continue
                self.emit({"kind": "raw", "text": txt})
        except Exception:
            pass

    # ---- 交互式提问（v2.17）----
    def ask_open(self, req_id, title, questions):
        """登记一个待答问题并广播 harness_ask 事件（前端渲染可点卡片）。

        同一会话同时只允许一个待答问题：模型是串行调用的，若旧的还没答
        又来一个，说明旧的那个已经没意义了（工具调用已被中断等），直接换掉。
        """
        with self.ask_lock:
            self.ask = {"req_id": req_id, "title": title,
                        "questions": questions, "answer": None,
                        "done": False, "ts": int(time.time() * 1000)}
        self.emit({"kind": "ask", "req_id": req_id, "title": title,
                   "questions": questions})
        return True

    def ask_answer(self, req_id, answer):
        """用户提交答案：记下并唤醒长轮询中的 MCP 工具调用。"""
        with self.ask_lock:
            a = self.ask
            if not a or a.get("req_id") != req_id:
                return False
            a["answer"] = answer
            a["done"] = True
        self.emit({"kind": "ask_done", "req_id": req_id, "answer": answer})
        return True

    def ask_poll(self, req_id):
        """MCP 侧长轮询：返回 (found, done, answer)。"""
        with self.ask_lock:
            a = self.ask
            if not a or a.get("req_id") != req_id:
                return False, False, None
            return True, bool(a.get("done")), a.get("answer")

    def ask_cancel(self):
        """会话进程结束/被中断：让还在等的 MCP 调用立刻拿到「用户未作答」，
        不要继续空转轮询。"""
        with self.ask_lock:
            a = self.ask
            if a and not a.get("done"):
                a["answer"] = {"_cancelled": True}
                a["done"] = True
            self.ask = None

    def emit(self, item):
        self._seq += 1
        item = dict(item)
        item["seq"] = self._seq
        item["ts"] = int(time.time() * 1000)
        with self.events_lock:
            self.events.append(item)
            if len(self.events) > _EVENTS_MAX:
                del self.events[:len(self.events) - _EVENTS_MAX]
            # v2.25：识图完成即落字段（见 __init__ vision_done 注释）——窗口
            # 滑动不再影响；brief 此刻回扫必然扫得到（assistant 刚发生）
            # v2.3.2 修真根因：CLI 事件统一包成 kind='event'（result 在 data.type
            # 里），旧判断只认裸 kind=='result'——从事件结构重构起永不匹配，
            # last_done 恒 0、「已返回」toast 从未弹过（用户实锤）。
            _d = item.get("data") if isinstance(item.get("data"), dict) else {}
            _is_result = (item.get("kind") == "result"
                          or (item.get("kind") == "event" and _d.get("type") == "result"))
            if _is_result and getattr(self, "is_vision", False):
                brief = ""
                for e in reversed(self.events):
                    # 同上：assistant 也是 kind='event' 包装（text 块在
                    # data.message.content 里），旧裸 kind 判断同样扫不到
                    txt = e.get("text")
                    if not txt and e.get("kind") == "event":
                        _c = ((e.get("data") or {}).get("message") or {}).get("content")
                        if isinstance(_c, list):
                            txt = "\n".join(b.get("text", "") for b in _c
                                            if isinstance(b, dict) and b.get("type") == "text")
                    if (e.get("kind") == "assistant" or txt) and (txt or "").strip():
                        brief = (txt or "").strip()[:120]
                        break
                self.vision_done = {"ts": item.get("ts") or 0, "brief": brief}
        with self.clients_lock:
            dead = []
            for q in self.clients:
                try:
                    q.put_nowait(item)
                except Exception:
                    try:
                        q.get_nowait()
                        q.put_nowait(item)
                    except Exception:
                        dead.append(q)
            for q in dead:
                try:
                    self.clients.remove(q)
                except Exception:
                    pass

    # ---- SSE ----
    def add_client(self):
        q = Queue(maxsize=_QUEUE_MAX)
        with self.clients_lock:
            self.clients.append(q)
        return q

    def remove_client(self, q):
        with self.clients_lock:
            try:
                self.clients.remove(q)
            except Exception:
                pass

    def get_events_after(self, after_seq=0, limit=500):
        with self.events_lock:
            res = [it for it in self.events if it["seq"] > after_seq]
        return res[-limit:] if limit else res


def re_title(text):
    import re as _re
    t = _re.sub(r"\s+", " ", (text or "").strip())
    return (t[:24] + "…") if len(t) > 24 else t


# ---------------------------------------------------------------------------
# 会话表 + 闲置回收
# ---------------------------------------------------------------------------
_sessions = {}              # sid -> HarnessSession（活/复活中的对象）
_sessions_lock = threading.Lock()
_gc_started = False


def _get_or_create(sid):
    """按 sid 取会话对象（内存没有就从元数据重建——复活路径）。"""
    with _sessions_lock:
        s = _sessions.get(sid)
        if s:
            return s
        _meta_load()
        m = _meta.get(sid)
        if not m:
            return None
        s = HarnessSession(m["sid"], cwd=m.get("cwd"), model=m.get("model"),
                           session_id=m.get("session_id"), title=m.get("title", ""),
                           name=m.get("name"), permission=m.get("permission"),
                           think=m.get("think"), lineage=m.get("lineage"))
        s.created = m.get("created") or s.created
        s.last_active = m.get("last_active") or s.last_active
        s.live_model = m.get("live_model") or None   # v2.27.21：实报模型跨重启保留
        s._seq = int(m.get("seq") or 0)              # v2.35.2：事件序号续号（见 to_meta 注释）
        _sessions[sid] = s
        return s


def _gc_loop():
    """闲置回收：活进程闲置超阈 kill（元数据/缓冲保留）。60s 一轮，daemon。
    v2.14：识图会话不参与回收——它是常驻配角，被回收后主会话发消息会
    突然找不到人（peer 名字消失）；顺带这轮把它救活。"""
    while True:
        time.sleep(60)
        try:
            now = int(time.time() * 1000)
            with _sessions_lock:
                objs = list(_sessions.values())
            for s in objs:
                if getattr(s, "is_vision", False) or getattr(s, "hidden", False):
                    continue
                if s.alive and not s.busy and (now - s.last_active) > _IDLE_KILL_S * 1000:
                    s.kill_proc()
            # v2.28：识图会话退役——GC 不再保活/拉起；升级前实例里的遗留
            # 识图会话（若有）闲置即收
            with _vision_lock:
                v = _vision_obj[0]
            if v and v.alive and not v.busy:
                v.kill_proc()
        except Exception:
            pass


def _ensure_gc():
    global _gc_started
    if not _gc_started:
        _gc_started = True
        threading.Thread(target=_gc_loop, daemon=True).start()
        threading.Thread(target=_peer_poll_loop, daemon=True).start()


def _peer_poll_loop():
    """回传兜底轮询（v2.27.19）：_check_peer_lines 只在进程 stdout 有
    assistant/result 事件时被触发，而 claude -p 进程回完 result 就退出——
    peer 回传到达时进程多半已死，CLI 只把消息排队写进 jsonl
    （attachment.type=queued_command），永远没人扫。用户实测：转交线计时
    13 分钟不落、📥 气泡不出现，回传"凭空消失"。
    这里 5s 一轮扫全部「前端在看」的会话（有 SSE 客户端），即使进程死了
    也照常补扫 jsonl 尾部，peer 行照样 emit。不看的会话不扫——不产生
    事件也就无需实时性，等用户切回来打开 SSE，下一轮自然补上。"""
    while True:
        time.sleep(5)
        try:
            with _sessions_lock:
                objs = list(_sessions.values())
            for s in objs:
                if getattr(s, "is_vision", False) or getattr(s, "hidden", False):
                    continue
                try:
                    with s.clients_lock:
                        watching = bool(s.clients)
                except Exception:
                    watching = False
                if not watching:
                    continue
                # 有事件缓冲序列号，前端重连时用 after_seq 续传不丢
                s._check_peer_lines()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 历史转写重建（切回会话时把历史灌进气泡）
# ---------------------------------------------------------------------------
_SKIP_RE = None


def transcript_for(s):
    """sid → 气泡行数组。claude 侧 session_id 的 jsonl 全量解析：
    user(typed 文本/图片/文件附件) / assistant(文本/工具调用) / tool_result 摘要。
    返回 None 表示转写不存在（新会话还没聊，气泡本来就空）。
    v2.27.18 血统链：会话被续命换过 session_id 时按 lineage 串接历代 jsonl——
    回放永远完整（用户铁律：重开可以，历史回放不能丢）。"""
    global _SKIP_RE
    import re as _re   # v2.27.17：无条件导入——原来只在 _SKIP_RE is None 时
    # 顺带 import，进程预热后再遇跨会话消息行就 UnboundLocalError（实测
    # /api/harness/transcript 500 → 前端对话流空白，历史看着"全没了"）
    if _SKIP_RE is None:
        _SKIP_RE = _re.compile(r"^(<local-command-caveat|<local-command-stdout|<command-name|<command-message|<command-args|<bash-|Another Claude session sent a message|<cross-session-message)")
    # v2.27.18 血统链：历代 session_id 的 jsonl 依序解析（旧→新，当前在尾）。
    # call_by_id 跨代共用：新代开头的 tool_result 仍能挂回旧代行。某代文件
    # 没了（被清理）静默跳过，不丢后代。去重保序防重复解析同一文件。
    ids = [x for x in (list(getattr(s, "lineage", None) or []) + [s.session_id]) if x]
    seen = set()
    ordered = [x for x in ids if not (x in seen or seen.add(x))]
    import glob as _glob
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")

    def _parse_one(path, lines, call_by_id):
        """解析一个 session 的 jsonl，行追加进 lines。返回是否读到文件。"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    if '"type":"user"' not in raw and '"type":"assistant"' not in raw:
                        continue
                    try:
                        o = json.loads(raw)
                    except Exception:
                        continue
                    typ = o.get("type")
                    if o.get("isSynthetic") or o.get("parent_tool_use_id"):
                        continue
                    # v2.3.12：/compact 压缩摘要行（isCompactSummary=true）不进
                    # 用户气泡——用户手动压缩后界面弹出几十行英文摘要（用户实锤
                    # 「不应该在我的消息气泡里」）。折叠成 renew 分割线：摘要已
                    # 并入模型上下文（续命记忆），UI 只留一行标记不渲染原文。
                    if o.get("isCompactSummary"):
                        lines.append({"role": "renew",
                                      "text": "上下文已压缩（/compact 摘要已并入模型记忆）",
                                      "ts": o.get("timestamp") or ""})
                        continue
                    msg = o.get("message") or {}
                    content = msg.get("content")
                    if typ == "user":
                        if isinstance(content, str):
                            t = content
                            # v2.27.3：跨会话消息（识图回传等）不再被 _SKIP_RE 静默吞掉——
                            # 解析出发件人与正文，产 peer 行让前端渲染专属回传气泡
                            # （用户定调：识图全程要有可见反馈，回传内容不能凭空消失）
                            # v2.3.2 审计 P2：补第二形态——busy 期回传被 CLI 排队后
                            # 内嵌注入下一轮用户消息（system-reminder 包装、origin=
                            # human），此前 startswith 口径识别不到，历史重建把它渲染
                            # 成带原始 XML 的普通用户气泡，等待线永不定格。
                            _m_pos = t.find("Another Claude session sent a message")
                            if _m_pos >= 0 and "<cross-session-message" in t:
                                _seg = t[_m_pos:]
                                nm = _re.search(r'from-name="([^"]*)"', _seg)
                                body = _re.search(
                                    r"<cross-session-message[^>]*>(.*)</cross-session-message>",
                                    _seg, _re.S)
                                lines.append({"role": "peer",
                                              "name": (nm.group(1) if nm else "其他会话"),
                                              "text": ((body.group(1) if body else _seg).strip())[:8000],
                                              "ts": o.get("timestamp") or ""})
                                # 内嵌形态：同一条 user 行还含用户真实输入——剔除整个
                                # system-reminder 注入块，剩余文本照常出 user 气泡
                                # （独立形态整行即回传，continue）
                                if _m_pos == 0 and t.strip().startswith("Another Claude session"):
                                    continue
                                t = _re.sub(r"<system-reminder>.*?</system-reminder>",
                                            "", t, flags=_re.S).strip()
                                if not t:
                                    continue
                            # v2.37R6（载入自愈①）：agent-message 通知形态回传
                            # 入回放——此前只在实时流被识别（R2 补的 SSE 分支），
                            # 转写重建不产出 → 载入后对应转交线成假等待残留
                            # （用户实测 4 条 18m+ 秒表狂走）。有完整开闭标签
                            # 才判（与实时口径一致），产 peer 行走前端既有按名
                            # 配对定格
                            _am = _re.search(r"<agent-message[^>]*>[\s\S]*?</agent-message>", t)
                            if _am:
                                _anm = _re.search(r'from-name="([^"]*)"', t) \
                                    or _re.search(r"\bname=\"([^\"]*)\"", t)
                                lines.append({"role": "peer",
                                              "name": (_anm.group(1) if _anm else "协作代理"),
                                              "text": _am.group(0).strip()[:8000],
                                              "ts": o.get("timestamp") or ""})
                                continue
                            # harness 通道从 stdin 注入，promptSource 是 "sdk"（不是 typed）；
                            # 排除标准是"非用户输入"（工具注入 default）——命令噪音由 _SKIP_RE 挡
                            # v2.27.23：超窗续命的 [系统] 历史注入不进气泡流——
                            # 用户定调"后台化，别让我看到"：几十万 token 的历史主干
                            # 刷满整屏。折叠成一行 renew 分割线，记忆在新会话上下文
                            # 里完整保留（注入真实发生），只是 UI 不渲染原文。
                            if t.lstrip().startswith("[系统] 上一会话上下文已超当前模型窗口"):
                                rounds = sum(1 for _ln in t.splitlines()
                                             if _ln.startswith(("用户：", "助手：")))
                                lines.append({"role": "renew",
                                              "text": "上下文超窗，已自动重开会话（%d 轮历史已后台迁移）" % rounds,
                                              "ts": o.get("timestamp") or ""})
                                continue
                            # v2.34.2（R1）：续发消息行按唯一句式前缀跳过
                            # 不出——警示卡由 harness_audit_log 回放（文本与
                            # 续发消息同一字符串，出两份就是双卡）。判定用
                            # _AUDIT_MSG_PREFIX 而非宽 "[审计]"：用户手打以
                            # [审计] 开头的普通消息必须照常出 user 行回放。
                            if t.lstrip().startswith(_AUDIT_MSG_PREFIX):
                                continue
                            ps_ok = (o.get("promptSource") in (None, "typed", "sdk")) or \
                                (o.get("origin") or {}).get("kind") == "human"
                            if t and ps_ok and not _SKIP_RE.match(t.strip()):
                                lines.append({"role": "user", "text": t[:8000],
                                              "ts": o.get("timestamp") or ""})
                        elif isinstance(content, list):
                            # v2.37R6（载入自愈①）：list 内容的 text 块里的
                            # agent-message 回传同样入回放（str 分支同款口径）
                            _am_skip = None
                            for _tb in content:
                                if not (isinstance(_tb, dict)
                                        and _tb.get("type") == "text"):
                                    continue
                                _tx = _tb.get("text") or ""
                                _am = _re.search(r"<agent-message[^>]*>[\s\S]*?</agent-message>", _tx)
                                if _am:
                                    _anm = _re.search(r'from-name="([^"]*)"', _tx) \
                                        or _re.search(r"\bname=\"([^\"]*)\"", _tx)
                                    lines.append({"role": "peer",
                                                  "name": (_anm.group(1) if _anm else "协作代理"),
                                                  "text": _am.group(0).strip()[:8000],
                                                  "ts": o.get("timestamp") or ""})
                                    _am_skip = id(_tb)
                                    break
                            trs = [b for b in content
                                   if isinstance(b, dict) and b.get("type") == "tool_result"]
                            if trs:
                                # 执行结果挂回对应 tool_use 行（前端详情弹层用）
                                for b in trs:
                                    line = call_by_id.get(b.get("tool_use_id"))
                                    # v2.28：识图 MCP 调用——结果落 peer 行（前端
                                    # 📥 回传气泡），对应 vision_relay 分割线定格用时
                                    if isinstance(line, dict) and "_vr" in line:
                                        rc = b.get("content")
                                        if isinstance(rc, list):
                                            rc = chr(10).join(x.get("text", "") for x in rc
                                                              if isinstance(x, dict) and x.get("type") == "text")
                                        vrow = line["_vr"]
                                        vrow["dur"] = _iso_dur_sec(vrow.get("ts"), o.get("timestamp"))
                                        vrow["err"] = bool(b.get("is_error"))
                                        lines.append({"role": "peer", "name": "识图",
                                                      "text": (rc or "（识图失败，无返回内容）")[:8000],
                                                      "ts": o.get("timestamp") or ""})
                                        continue
                                    if line is None or line.get("result") is not None:
                                        continue
                                    rc = b.get("content")
                                    if isinstance(rc, list):
                                        rc = chr(10).join(x.get("text", "") for x in rc
                                                   if isinstance(x, dict) and x.get("type") == "text")
                                    line["result"] = (rc or "")[:8000]
                                    if b.get("is_error"):
                                        line["err"] = True
                                continue
                            texts, imgs, files = [], 0, []
                            for b in content:
                                if not isinstance(b, dict):
                                    continue
                                # R6 复审 E：agent-message 块已产 peer 行，不进 user 气泡
                                if _am_skip is not None and id(b) == _am_skip:
                                    continue
                                if b.get("type") == "text" and b.get("text"):
                                    texts.append(b["text"])
                                elif b.get("type") == "image":
                                    imgs += 1
                            t = " ".join(texts)
                            m_att = _extract_att(t)
                            if m_att:
                                files = m_att
                                t = _strip_att(t)
                            if (t or imgs) and not _SKIP_RE.match((t or "").strip()):
                                lines.append({"role": "user", "text": t[:8000], "images": imgs, "files": files,
                                              "ts": o.get("timestamp") or ""})
                    elif typ == "assistant" and isinstance(content, list):
                        texts, tools, thinks = [], [], []
                        for b in content:
                            if not isinstance(b, dict):
                                continue
                            if b.get("type") == "text" and b.get("text"):
                                texts.append(b["text"])
                            elif b.get("type") == "thinking" and b.get("thinking"):
                                thinks.append(b["thinking"])
                            elif b.get("type") == "tool_use":
                                tools.append({"id": b.get("id", ""), "name": b.get("name", ""),
                                              "summary": _tool_summary(b.get("name", ""), b.get("input")),
                                              "input": b.get("input") or {},
                                              # v2.3.2：行级 ts——前端历史重建给转交等待线
                                              # 提供真实起点（此前缺字段，恒传 0 回退 Date.now，
                                              # 定格「用时」恒 0s——审计 P1）
                                              "ts": o.get("timestamp") or ""})
                        # 思考先出：一轮里 thinking 在工具调用之前，重建后「思考抽屉」才在
                        # 「执行抽屉」上方（与流式渲染同序）
                        if thinks:
                            # v2.3.12 补 ts：此前 thinking/assistant 行不带 ts →
                            # 只读模式轮时长恒 0（「已工作 N 个步骤」出不来时间）、
                            # 思考段时长恒「持续了几秒」无法给精确值（用户实锤）
                            lines.append({"role": "thinking", "text": "\n".join(thinks)[:8000],
                                          "ts": o.get("timestamp") or ""})
                        # 空白/纯换行的 text 块要丢掉：模型每轮都会吐一个 "\n\n" 占位，
                        # 落盘后仍是真值 → 重建时每条渲染成一个空白 AI 气泡（历史会话
                        # 满屏空白圆角条的根因），还把真正的思考/工具行挤出可视区。
                        t = "\n".join(texts).strip()
                        if t:
                            # v2.38 带 model：前端历史重建气泡的模型徽章数据源
                            # （此前不落 → 旧会话气泡只剩头像字母没模型名，用户实锤）
                            lines.append({"role": "assistant", "text": t[:8000],
                                          "ts": o.get("timestamp") or "",
                                          "model": (o.get("message") or {}).get("model") or ""})
                        for tl in tools:
                            if tl["name"] in _VISION_TOOLS:
                                # v2.28：识图 MCP = vision_relay 分割线行（前端 📤
                                # 转交线+秒表），不出普通工具卡；结果由 tool_result
                                # 分支挂回成 peer 行（📥 回传气泡）
                                row = {"role": "vision_relay", "dur": None,
                                       "ts": tl.get("ts") or ""}
                                lines.append(row)
                                if tl["id"]:
                                    call_by_id[tl["id"]] = {"_vr": row}
                                continue
                            row = {"role": "tool", "text": tl["name"], "summary": tl["summary"],
                                   "input": tl["input"], "result": None,
                                   "ts": tl.get("ts") or ""}
                            if tl["id"]:
                                call_by_id[tl["id"]] = row
                            lines.append(row)
        except OSError:
            return False
        return True

    lines = []
    call_by_id = {}           # tool_use_id -> 行 dict（把 tool_result 挂回调用行）
    found_any = False
    for csid in ordered:
        for cand in _glob.glob(os.path.join(proj, "*", csid + ".jsonl")):
            if _parse_one(cand, lines, call_by_id):
                found_any = True
            break
    if not found_any:
        return None
    # v2.34.1：审计警示卡（audit log）按 ts 并入回放——warn/降级/中断档的
    # 卡此前只在实时事件流，jsonl 里没有对应行，刷新即失。卡落在本会话
    # sid 维度（跨血统链全量），按时间戳稳定排序插回各回合 result 之后。
    try:
        arows = _audit_log_read(s.sid)
        if arows:
            from datetime import datetime as _dt, timezone as _tz

            def _tk(ln):
                try:
                    return _dt.fromisoformat(
                        str(ln.get("ts") or "").replace("Z", "+00:00"))
                except Exception:
                    return _dt.min.replace(tzinfo=_tz.utc)
            for ln in lines:
                ln["_k"] = _tk(ln)
            for a in arows:
                a["_k"] = _tk(a)
            lines = lines + arows
            lines.sort(key=lambda x: x["_k"])   # 稳定排序：同刻保持原相对序
            for ln in lines:
                ln.pop("_k", None)
    except Exception:
        pass
    return lines


def _extract_att(t):
    """从 user 文本里剥出 [附件，可用 Read 工具读取] 后的路径列表（v2 发送格式回读）。"""
    if not t or "[附件" not in t:
        return None
    idx = t.find("[附件")
    tail = t[idx:]
    paths = [l.strip() for l in tail.splitlines()[1:] if l.strip() and (":" in l or l.startswith("\\\\"))]
    return paths or None


def _strip_att(t):
    idx = t.find("[附件")
    return (t[:idx] if idx >= 0 else t).strip()


def _tool_summary(name, input):
    i = input or {}
    try:
        if name in ("Read", "Write", "Edit"):
            return i.get("file_path", "")
        if name in ("Bash", "PowerShell"):
            return i.get("command", i.get("cmd", ""))
        if name in ("Grep", "Glob"):
            return i.get("pattern", "")
        if name.startswith("mcp__"):
            for k, v in i.items():
                if isinstance(v, str) and v:
                    return "%s=%s" % (k, v[:60])
        if isinstance(i.get("cmd"), str):
            return i["cmd"]
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Blueprint 路由（/api/harness/*）
# ---------------------------------------------------------------------------
harness_bp = Blueprint("harness", __name__, url_prefix="/api/harness")


@harness_bp.route("/connect", methods=["POST"])
def harness_connect():
    """新建/复活会话。body: {sid?, model?, cwd?}。
    sid 缺省=新会话；带 sid=切回（内存对象复活或从元数据重建）。"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    model = (data.get("model") or "").strip() or None
    cwd = (data.get("cwd") or "").strip() or os.path.expanduser("~")
    if not os.path.isdir(cwd):
        return jsonify({"ok": False, "err": "目录不存在：%s" % cwd}), 400
    _ensure_gc()
    if sid:
        s = _get_or_create(sid)
        if not s:
            return jsonify({"ok": False, "err": "会话不存在"}), 404
        if not s.alive and not s.revive_if_dead():
            return jsonify({"ok": False, "err": "会话已失效（无法恢复上下文）"}), 400
        # v2.28：识图走 MCP 通道（注入所有会话），连接时不再拉识图会话
        return jsonify({"ok": True, "port_id": s.port_id, "sid": s.sid, "kind": "harness",
                        "cwd": s.cwd, "model": s.model, "title": s.title})
    # 新会话
    new_sid = uuid.uuid4().hex
    s = HarnessSession(new_sid, cwd=cwd, model=model,
                       permission=(data.get("permission") or "").strip() or None,
                       think=(data.get("think") or "").strip() or None)
    try:
        s.start()
    except Exception as e:
        return jsonify({"ok": False, "err": _humanize_claude_error(e)}), 500
    s.sync_meta()
    with _sessions_lock:
        _sessions[new_sid] = s
    return jsonify({"ok": True, "port_id": s.port_id, "sid": s.sid, "kind": "harness",
                    "cwd": s.cwd, "model": s.model, "title": s.title})


@harness_bp.route("/ask/reply", methods=["POST"])
def harness_ask_reply():
    """MCP 侧发起提问（src/harness_ask_mcp.py 调）。
    body: {sid, req_id, title, questions}。登记后前端经 SSE 收到 harness_ask
    事件渲染成可点卡片；用户提交走 /ask/answer。"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    req_id = (data.get("req_id") or "").strip()
    s = _get_or_create(sid)
    if not s or not req_id:
        return jsonify({"ok": False, "err": "会话不存在或缺少 req_id"}), 400
    s.ask_open(req_id, (data.get("title") or "").strip(), data.get("questions") or [])
    return jsonify({"ok": True})


@harness_bp.route("/ask/poll", methods=["POST"])
def harness_ask_poll():
    """MCP 侧长轮询等作答。body: {sid, req_id}。"""
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    found, done, answer = s.ask_poll((data.get("req_id") or "").strip())
    return jsonify({"ok": True, "found": found, "done": done, "answer": answer})


@harness_bp.route("/ask/answer", methods=["POST"])
def harness_ask_answer():
    """用户提交答案（前端调）。body: {sid, req_id, answer}。
    answer 形如 {问题原文: "选项label"}；多选用 ", " 连接。"""
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    req_id = (data.get("req_id") or "").strip()
    if not s.ask_answer(req_id, data.get("answer") or {}):
        return jsonify({"ok": False, "err": "该提问已失效（可能已被新提问替换）"}), 409
    return jsonify({"ok": True})


@harness_bp.route("/send", methods=["POST"])
def harness_send():
    """发消息。body: {sid, text, images?, files?}（images/files=upload 返回的绝对路径）。"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    text = (data.get("text") or "").strip()
    images = [p for p in (data.get("images") or []) if isinstance(p, str) and p]
    files = [p for p in (data.get("files") or []) if isinstance(p, str) and p]
    s = _get_or_create(sid)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    if not s.alive and not s.revive_if_dead():
        return jsonify({"ok": False, "err": "会话已失效，请新建会话"}), 400
    ok, err = s.send_message(text, images or None, files or None)
    if not ok:
        return jsonify({"ok": False, "err": err}), 400
    return jsonify({"ok": True})


@harness_bp.route("/interrupt", methods=["POST"])
def harness_interrupt():
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    ok, err = s.interrupt()
    return jsonify({"ok": ok, "err": err}) if not ok else jsonify({"ok": True})


@harness_bp.route("/kill", methods=["POST"])
def harness_kill():
    """手动退出进程（/exit 命令）。会话记录保留，下次发消息自动 --resume。"""
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    if not s.alive:
        return jsonify({"ok": True, "note": "进程已不在运行"})
    s.kill_proc(quiet=False)     # 不吞 exit：让前端收到「进程已结束」事件收尾
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# v2.28.11 会话回退（/rewind）——爆窗/坏回合的逃生门。
# 背景（2026-09-20 实锤）：一次 Read 截图把上下文从 340K 打到 1024K 满窗，
# 此时 /compact 自身也要发全量历史去压缩、请求直接超窗——会话被砖死。
# 回退 = 把转写截断到「最后第 N 个完整回合」（result 行）之后，备份保全量，
# 杀进程，下次发消息 --resume 按截断后的转写续上下文（CLI 原生语义）。
# ---------------------------------------------------------------------------
def _jsonl_path_for(session_id):
    import glob as _glob
    for cand in _glob.glob(os.path.join(os.path.expanduser("~"), ".claude",
                                        "projects", "*", session_id + ".jsonl")):
        return cand
    return None


def _rewind_jsonl(session_id, turns=1):
    """截断转写：保留到最后第 turns 个 result 行（含）。返回 (ok, msg)。"""
    p = _jsonl_path_for(session_id)
    if not p:
        return False, "找不到会话转写文件"
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    idxs = [i for i, L in enumerate(lines)
            if '"type":"result"' in L]
    if not idxs:
        return False, "转写里没有完整回合可回退"
    # 丢弃最后 turns 个完整回合（未完成的尾部行随之丢弃）；最多退到只剩
    # 首回合（全退空转写 resume 语义不明，不做）
    turns = max(1, min(turns, len(idxs) - 1)) if len(idxs) > 1 else 1
    cut = idxs[len(idxs) - 1 - turns]
    keep = lines[:cut + 1]
    if len(keep) == len(lines):
        return False, "转写尾部没有可丢弃的回合"
    return _rewind_write(p, lines, keep, "已回退 %d 个完整回合" % turns)


def _rewind_jsonl_ts(session_id, ts):
    """锚点截断（v2.28.14 消息级回滚）：保留到 ts 所属回合的 result 为止
    ——找第一个 timestamp >= ts 的 result 行，截到它（含）。ts 是该 AI 消息
    事件的 ISO 时间戳（前端从回放行带入 dataset）。"""
    p = _jsonl_path_for(session_id)
    if not p:
        return False, "找不到会话转写文件"
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    cut = None
    for i, L in enumerate(lines):
        if '"type":"result"' not in L:
            continue
        try:
            o = json.loads(L)
        except Exception:
            continue
        if str(o.get("timestamp") or "") >= ts:
            cut = i
            break
    if cut is None:
        return False, "锚点消息之后没有完整回合"
    keep = lines[:cut + 1]
    if len(keep) == len(lines):
        return False, "已在锚点位置，没有可回退的内容"
    return _rewind_write(p, lines, keep, "已回滚到指定消息")


def _rewind_jsonl_anchor(session_id, anchor):
    """文本锚点截断（v2.28.16 消息级回滚主路径）：锚点 = 某条 AI 消息正文的
    前缀（前端从气泡带入，实时/回放两路都有文本）。从尾部找首条匹配的
    assistant 行，截到它之后的第一个 result 行（该回合收尾）——「回滚到
    这条消息所在回合结束」。"""
    p = _jsonl_path_for(session_id)
    if not p:
        return False, "找不到会话转写文件"
    a = (anchor or "").strip()[:60]
    if not a:
        return False, "缺少回滚锚点"
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    hit = None
    for i in range(len(lines) - 1, -1, -1):
        if '"type":"assistant"' not in lines[i]:
            continue
        try:
            o = json.loads(lines[i])
        except Exception:
            continue
        c = (o.get("message") or {}).get("content")
        if isinstance(c, str):
            txt = c
        elif isinstance(c, list):
            txt = "".join(b.get("text", "") for b in c
                          if isinstance(b, dict) and b.get("type") == "text")
        else:
            txt = ""
        if txt.strip().startswith(a):
            hit = i
            break
    if hit is None:
        return False, "锚点消息不在会话记录里"
    cut = None
    for i in range(hit, len(lines)):
        if '"type":"result"' in lines[i]:
            cut = i
            break
    if cut is None:
        return False, "锚点所在回合没有完整收尾"
    keep = lines[:cut + 1]
    if len(keep) == len(lines):
        return False, "锚点之后没有可回退的内容"
    return _rewind_write(p, lines, keep, "已回滚到指定消息")


def _rewind_write(p, lines, keep, brief):
    """备份全量并原子写截断结果。返回 (ok, msg)。"""
    import shutil
    bak = p + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, bak)                     # 全量备份——历史永不丢
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(keep)
    os.replace(tmp, p)
    return True, ("%s（丢弃 %d 行；全量备份 %s）"
                  % (brief, len(lines) - len(keep), os.path.basename(bak)))


@harness_bp.route("/rewind", methods=["POST"])
def harness_rewind():
    """/rewind [n]：回退最近 n 个完整回合（默认 1）。杀进程，下次发消息
    自动 --resume 续上回退后的上下文。爆窗（含 /compact 也压不动的砖死态）
    与「刚才那轮搞砸了」两个场景的统一逃生门。"""
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    if not s.session_id:
        return jsonify({"ok": False, "err": "会话还没有内容可回退"}), 400
    anchor = str(data.get("anchor") or "").strip()
    ts = str(data.get("ts") or "").strip()
    if anchor:
        # v2.28.16 消息级回滚主路径：文本锚点（气泡正文前缀）
        ok, msg = _rewind_jsonl_anchor(s.session_id, anchor)
    elif ts:
        # v2.28.14 时间戳锚点（备用）
        ok, msg = _rewind_jsonl_ts(s.session_id, ts)
    else:
        try:
            turns = int(data.get("turns") or 1)
        except Exception:
            turns = 1
        ok, msg = _rewind_jsonl(s.session_id, turns)
    if not ok:
        return jsonify({"ok": False, "err": msg}), 400
    # 进程必须杀：内存里的历史还是旧的，resume 才会按截断后的转写重建
    s.kill_proc(quiet=True)
    s.last_result = None                     # 用量缓存失效（守卫/窗口判定重算）
    s.emit({"kind": "raw", "text": "⏪ " + msg + "——发送消息即续上回退后的上下文"})
    return jsonify({"ok": True, "msg": msg})


def _session_ctx_used(s):
    """会话已用上下文 tokens（/ctx 与 set_model 窗口预检共用）。
    取值顺序：jsonl 尾部倒扫最新非零 usage（跳过子代理行；撞压缩边界
    归零——/compact 后旧值全部过期）→ last_result.usage 兜底。
    last_result 只贡献窗口（contextWindow）。返回 (used, window, compacted)。"""
    used, window = 0, 0
    lr = getattr(s, "last_result", None) or {}
    try:
        mu = lr.get("modelUsage") or {}
        for k in mu:
            w = (mu[k] or {}).get("contextWindow") or 0
            window = max(window, int(w))
        u = lr.get("usage") or {}
        used = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
            + (u.get("cache_creation_input_tokens") or 0)
    except Exception:
        used = 0
    import glob as _glob
    path = None
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    for cand in _glob.glob(os.path.join(proj, "*", s.session_id + ".jsonl")):
        path = cand
        break
    found = False
    compacted = False
    if path:
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 1048576))     # 尾部 1MB（大行/多附件保险）
                tail = f.read().decode("utf-8", errors="replace")
            for raw in reversed(tail.splitlines()):
                raw = raw.strip()
                if '"isCompactSummary":true' in raw:
                    if not found:
                        compacted = True
                        used = 0
                    break
                if '"type":"assistant"' not in raw or '"usage"' not in raw:
                    continue
                if '"isSidechain":true' in raw:
                    continue
                try:
                    o = json.loads(raw)
                except Exception:
                    continue          # 块首半行被截断，跳过
                uu = (o.get("message") or {}).get("usage") or {}
                v = (uu.get("input_tokens") or 0) + (uu.get("cache_read_input_tokens") or 0) \
                    + (uu.get("cache_creation_input_tokens") or 0)
                if isinstance(v, int) and v > 0:
                    used = v
                    found = True
                    break
        except OSError:
            pass
    return used, window, compacted


# 网关模型上下文窗口（tokens）：模型名带 [1M] 后缀 = 1M 窗口变体，
# 其余默认 256K（实测报错原文 maximum context length 262144）。
_CTX_WINDOW_1M = 1048576
_CTX_WINDOW_DEFAULT = 262144


def _session_ctx_window(s):
    """v2.27.22：会话上下文窗口——候选链解析 [1M] 后缀：会话配置名 →
    settings 默认名 → CLI 实报名。实报名（live_model，网关上报）会被
    剥掉 [1M] 后缀（裸 glm-5.3），单看它会把 1M 会话判成 256K →
    251K 被误判超窗拒发（用户实锤「严重 bug」）。窗口是用户在配置里
    显式选的后缀属性，必须从配置名读；实报名只作最后兜底。"""
    for n in (s.model, available_models().get("default"), s._eff_model()):
        n = (n or "").lower()
        if "[1m]" in n or n.endswith("1m"):
            return _CTX_WINDOW_1M
    return _CTX_WINDOW_DEFAULT


@harness_bp.route("/ctx")
def harness_ctx():
    """上下文用量（v2.20 兜底数据源）。取值逻辑见 _session_ctx_used。"""
    s = _get_or_create((request.args.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    if not s.session_id:
        return jsonify({"ok": True, "used": 0, "window": 0, "sid": s.sid})
    used, window, compacted = _session_ctx_used(s)
    return jsonify({"ok": True, "used": used, "window": window, "sid": s.sid,
                    "compacted": compacted,
                    "model": s.model or available_models().get("default") or ""})


@harness_bp.route("/set_model", methods=["POST"])
def harness_set_model():
    """会话内切模型（v2.20 强需求：不再要求新建会话）。

    claude 进程的 --model 是启动参数，活进程改不了——做法是 quiet 杀掉 +
    --resume 同一 session_id 重启：上下文连续，新模型下次回复即生效。
    引导词随 start() 按新模型重新生成（多模态直读/识图转交口径跟着变）。
    前端收 model_switched 事件渲染分割线。"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    model = (data.get("model") or "").strip() or None
    s = _get_or_create(sid)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    if s.busy:
        return jsonify({"ok": False, "err": "claude 正在回复中，回复结束后再切模型"}), 409
    # 注：不在此拦「超窗切小模型」——切 API 方案时模型是被快照强制带过去的，
    # 拦不住；超窗的兜底在 send_message（发了必 400，直接拒发并提示出路）。
    if model == s.model:
        return jsonify({"ok": True, "model": s.model})
    s.model = model
    s.live_model = None   # v2.27.21：旧实报随模型切换作废，start 按新 model 注入
    if s.alive:
        s.kill_proc(quiet=True)          # 吞 exit：计划内重启不弹「进程已结束」
    if s.session_id:
        s.revive_if_dead()               # 失败无妨：下次 send 前仍会 revive
    s.sync_meta()
    s.emit({"kind": "model_switched", "text": model or "默认模型"})
    return jsonify({"ok": True, "model": s.model})


@harness_bp.route("/stream")
def harness_stream():
    """SSE 事件流。?sid=&after_seq=。连接建立先回放增量（重连不丢）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    after_seq = request.args.get("after_seq", 0, type=int)
    q = s.add_client()
    def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            for it in s.get_events_after(after_seq):
                yield "data: %s\n\n" % json.dumps(it, ensure_ascii=False)
            while True:
                try:
                    item = q.get(timeout=15)
                    yield "data: %s\n\n" % json.dumps(item, ensure_ascii=False)
                except Empty:
                    yield ": ping\n\n"
        finally:
            s.remove_client(q)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@harness_bp.route("/sessions")
def harness_sessions():
    """会话列表（持久化元数据，新→旧）。
    v2.2.1：last_active 取活对象内存值与 meta 的较大者——reader 每行更新
    内存 last_active 但 sync_meta 只在元数据变更时落盘，纯对话（不改标题
    不切模型）时 meta 停在上次落盘时刻，列表时间冻结（用户实锤「一直在
    对话却显示 1 小时前」）。"""
    _meta_load()
    with _sessions_lock:
        live = {sid: (s.alive, s.busy, s.busy_since,
                      getattr(s, "last_active", 0)) for sid, s in _sessions.items()}
    items = []
    for sid, m in _meta.items():
        alive, busy, busy_since, live_la = live.get(sid, (False, False, None, 0))
        if not busy:
            busy_since = None
        last_active = max(m.get("last_active", 0) or 0, live_la or 0)
        items.append({"sid": sid, "title": m.get("title") or "新会话",
                      "model": m.get("model"), "cwd": m.get("cwd", ""),
                      "permission": m.get("permission") or "auto",
                      "think": m.get("think"),
                      "session_id": m.get("session_id"), "has_history": bool(m.get("session_id")),
                      "created": m.get("created", 0), "last_active": last_active,
                      "alive": alive, "busy": busy, "busy_since": busy_since})
    items.sort(key=lambda x: -x["last_active"])
    return jsonify({"ok": True, "sessions": items})


@harness_bp.route("/transcript")
def harness_transcript():
    """切回会话的历史气泡。?sid=。转写不存在返回 lines:[]（新会话空气泡）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    lines = transcript_for(s)
    return jsonify({"ok": True, "lines": lines or [], "alive": s.alive,
                    "busy": s.busy, "busy_since": s.busy_since,
                    "model": s.model, "title": s.title, "seq": s._seq})


@harness_bp.route("/audit_gate")
def harness_audit_gate():
    """v2.40 light 形态直改免审线事中闸查询端点（PreToolUse hook 在每次
    Edit/Write/MultiEdit/NotebookEdit 前来问）。?session_id=<CLI 侧会话 id>。
    返回 {ok, gate}；gate.block=true=本回合主会话直改累计已达免审线，hook
    exit 2 拦下（msg 随行给模型）。

    口径与 _audit_settle 同源：_audit_state 判启用（roles 开+light+
    audit_mode!=off；读一次小配置文件，改配置即时生效），used 取会话
    _audit 的本回合 lines 累计。block 判定用 >=（达到即拦下一次）而非
    结算的 >（超线追责）——事中闸的职责是让超线根本不发生，事后审计
    只兜闸失效的漏网。

    查不到会话（session_id 不在 _sessions：别的实例/已换代）一律放行。
    注意子代理与主会话同 session_id（官方 hooks 文档+本机 CLI 2.1.278
    实证：hook stdin 无独立 id，子代理标记是 agent_id/agent_type 字段）
    ——dev 直改的放行判定在 hook 脚本侧做（agent_id/agent_type 有值即
    exit 0，不发起本查询），拦它等于闸自锁。本接口纯内存读（配置文件
    除外），每次直改都调，无磁盘扫描。"""
    csid = (request.args.get("session_id") or "").strip()
    gate = {"block": False}
    if csid:
        with _sessions_lock:
            s = next((x for x in _sessions.values()
                      if x.session_id == csid), None)
        if s is not None:
            st = s._audit_state()
            if st is not None:
                _, max_free = st
                used = int((s._audit or {}).get("lines") or 0)
                if used >= max_free:
                    gate = {"block": True, "used": used, "max_free": max_free,
                            "msg": ("本回合直改已 %d 行，达到免审线 %d——按轻"
                                    "主力分工请用 Task 工具派 dev 代理实施本"
                                    "改动；确需继续直改可在设置里调整免审线。"
                                    % (used, max_free))}
    return jsonify({"ok": True, "gate": gate})


def _subagent_rows_from_jsonl(path):
    """v2.42（内部共用）：解析子代理转写 jsonl → 回放 rows。返回 None=文件
    不可读（miss，调用方继续试兜底源）；list=解析结果（可为空——文件存在
    但无有效行，如实返回空让前端走「转写存在但无可回放内容」分支）。
    抽出共用的原因：新版 CLI（2.1.267+ Agent 工具）的子代理转写迁移到
    %LOCALAPPDATA%\\Temp\\claude\\<项目转码名>\\<主会话id>\\tasks\\<taskId>.output，
    实测行结构与 projects/<proj>/<agentId>.jsonl 同构（assistant 行
    message.content 含 text/tool_use/thinking 块且带 model 字段，user 行
    tool_result 块同构；多出的 attachment/system 行被 type 过滤跳过，
    thinking 块本就不提取——回放不需要），两源走同一解析避免复制。
    容量护栏沿用 v2.37R3 流式「保头 150 + 滚动尾 50」——O(1) 内存全量
    扫描，无硬帽：尾部恒为真实最后 50 行（最终交付报告不会丢），省略数
    精确。"""
    rows = []
    from collections import deque
    _tail = deque(maxlen=50)
    _total = 0

    def _push(row):
        """rows 满 200 后新行溢出进滚动尾窗（list.pop(200) 对 ≤201 长度是常数代价）。"""
        nonlocal _total
        _total += 1
        rows.append(row)
        if len(rows) > 200:
            _tail.append(rows.pop(200))

    def _txt(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text")
        return ""

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                # v2.37R2/R3（复审2/R3）：全量扫描无硬帽——rows 满 200 后新行
                # 溢出进 _tail 滚动窗（见 _push），尾部恒为真实最后 50 行
                if not raw:
                    continue
                try:
                    o = json.loads(raw)
                except Exception:
                    continue
                typ = o.get("type")
                if typ not in ("assistant", "user"):
                    continue
                m = o.get("message") or {}
                content = m.get("content")
                blocks = content if isinstance(content, list) else []
                if typ == "assistant":
                    model = m.get("model") or ""
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and (b.get("text") or "").strip():
                            _push({"k": "text", "text": b["text"][:2000],
                                   "model": model})
                        elif b.get("type") == "tool_use":
                            inp = b.get("input") or {}
                            hint = (inp.get("command") or inp.get("file_path")
                                    or inp.get("path") or inp.get("pattern")
                                    or inp.get("query") or inp.get("description")
                                    or inp.get("subject") or inp.get("prompt") or "")
                            _push({"k": "tool", "name": b.get("name") or "",
                                   "hint": str(hint)[:120]})
                else:
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            _push({"k": "result",
                                   "text": _txt(b.get("content"))[:200],
                                   "err": bool(b.get("is_error"))})
    except OSError:
        return None
    # v2.37R2/R4：头 150 + 省略标注 + 真实尾 50——rows 恒持前 200，
    # rows[150:]（50 行）与 _tail 拼接后取尾 50 = 真实最后 50 行
    # （终审2：旧式仅拼 _tail 会丢 rows[150:200] 区间，[201,249] 全错）
    if _total > 200:
        rows = (rows[:150]
                + [{"k": "note", "text": "…中间已省略 %d 条（详情见完整转写）…" % (_total - 200)}]
                + (rows[150:] + list(_tail))[-50:])
    return rows


@harness_bp.route("/subagent_replay")
def harness_subagent_replay():
    """v2.38：历史子代理回放数据源。?sid=&agent=<agentId(=task_started 的
    task_id)>。子代理是独立 session，事件不在主会话 jsonl 里（实测主链
    转写零 top-level parent_tool_use_id 行）。按 id 读转写、抽文本/工具调
    用/结果序列供前端回放窗格重建。v2.42 双源：源①（优先）旧版 CLI 落
    projects/<proj>/<agentId>.jsonl（与主会话同目录）；源②（兜底）新版
    CLI（2.1.267+）Agent 工具的子代理转写迁移到 %LOCALAPPDATA%\\Temp\\
    claude\\<项目转码名>\\<主会话id>\\tasks\\<taskId>.output（JSONL=完整
    子代理会话，行结构与①同构——真实样例实测验证）。found=False = 两源
    均未命中（旧会话/已被 CLI 清理/跨会话协作）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    agent = (request.args.get("agent") or "").strip()
    if not agent or not re.match(r"^[0-9a-zA-Z_-]{8,64}$", agent):
        return jsonify({"ok": False, "err": "agent 参数非法"}), 400
    # 主会话 jsonl 定位（与 _check_peer_lines 同源逻辑：按 lineage+当前 id 找）
    import glob as _g
    csids = [x for x in (list(getattr(s, "lineage", None) or [])
                         + [s.session_id]) if x]
    main_dir = None
    for csid in csids:
        for cand in _g.glob(os.path.join(os.path.expanduser("~"), ".claude",
                                         "projects", "*", csid + ".jsonl")):
            main_dir = os.path.dirname(cand)
            break
        if main_dir:
            break
    if not main_dir:
        return jsonify({"ok": True, "found": False, "rows": []})
    rows = None
    # 源①（优先，旧版 CLI）：主会话同目录的子代理独立 jsonl
    sub_path = os.path.join(main_dir, agent + ".jsonl")
    if os.path.isfile(sub_path):
        rows = _subagent_rows_from_jsonl(sub_path)
    # 源②（兜底，新版 CLI 子代理转写迁移）：tasks 目录挂在
    # %LOCALAPPDATA%\\Temp\\claude\\<项目转码名>\\<主会话id>\\tasks\\ 下——
    # 项目转码名即 main_dir 的 basename（projects 与 Temp\\claude 同码，
    # 样例 D--AI------Pro）；lineage 全链逐会话试：续聊链上任一会话启动的
    # task 都能命中（task_id 全局唯一，多目录存在也不歧义）
    if rows is None:
        la = os.environ.get("LOCALAPPDATA")
        if la:
            for csid in csids:
                tpath = os.path.join(la, "Temp", "claude",
                                     os.path.basename(main_dir), csid,
                                     "tasks", agent + ".output")
                if os.path.isfile(tpath):
                    rows = _subagent_rows_from_jsonl(tpath)
                    break
    if rows is None:
        return jsonify({"ok": True, "found": False, "rows": []})
    return jsonify({"ok": True, "found": True, "rows": rows})


@harness_bp.route("/peer_pair_log", methods=["POST"])
def harness_peer_pair_log():
    """v2.37R2（复审6）：协作回传配对结果落审计日志——task_id=SendMessage to
    同源假设的事后取证点（命中与否都记，和 agents_dir_audit 同通道）。
    fire-and-forget，前端不等响应，失败静默。"""
    data = request.get_json(force=True, silent=True) or {}
    try:
        from .harness_roles import _agents_dir_audit
        _agents_dir_audit("peer-pair", "sid=%s task=%s peer=%s paired=%s" % (
            str(data.get("sid") or "")[:20], str(data.get("task") or "-")[:64],
            str(data.get("name") or "-")[:64], bool(data.get("ok"))))
    except Exception:
        pass
    return jsonify({"ok": True})


@harness_bp.route("/peer_result_check")
def harness_peer_result_check():
    """v2.37R6（追溯自愈②）：回合终结时对仍 pending 的转交线做轻量存在性
    检查——peer 名即 agentId/会话 id（SendMessage to 同源），其转写 jsonl
    与主会话同目录；文件尾部含**时间戳 ≥ since** 的 result 行=对端在转交
    之后确有完成回合 → 前端定格「已回传（转写核实补记）」。?sid=&peers=
    &sinces=（两列 csv 按下标对齐，since=线起点 epoch ms；缺省 0=不过滤）。
    R6 复审 A：peer 白名单（无路径分隔符/无 ../无控制符/≤64，中文名放行）；
    B：since 判定防旧回合 result 误定格；C：上限 10 条（前端对超出部分标
    「未核实」）。轻量：每 peer 只读尾部 64KB。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404

    def _ok_name(p):
        # R6 复审 A：路径穿越探测封死——禁分隔符/..、控制符，≤64（中文名放行）
        if not p or len(p) > 64:
            return False
        if any(c in p for c in ("/", "\\", "..", ",")):
            return False
        return not any(ord(c) < 32 for c in p)

    peers = [p.strip() for p in (request.args.get("peers") or "").split(",")
             if _ok_name(p.strip())][:10]
    sinces = [x for x in (request.args.get("sinces") or "").split(",")]
    if not peers:
        return jsonify({"ok": True, "results": {}})
    main_dir = None
    import glob as _g
    for csid in [x for x in (list(getattr(s, "lineage", None) or [])
                             + [s.session_id]) if x]:
        for cand in _g.glob(os.path.join(os.path.expanduser("~"), ".claude",
                                         "projects", "*", csid + ".jsonl")):
            main_dir = os.path.dirname(cand)
            break
        if main_dir:
            break
    results = {}
    for idx, p in enumerate(peers):
        found = False
        try:
            since = int(sinces[idx] or 0)
        except (ValueError, TypeError):
            since = 0
        if main_dir:
            pf = os.path.join(main_dir, p + ".jsonl")
            if os.path.isfile(pf):
                try:
                    size = os.path.getsize(pf)
                    with open(pf, "rb") as f:
                        if size > 65536:
                            f.seek(size - 65536)
                        tail = f.read().decode("utf-8", errors="replace")
                    # R6 复审 B：只认 timestamp ≥ since 的 result 行——对端旧
                    # 回合的 result 不算本次委托的回传
                    for ln in tail.splitlines():
                        if '"type":"result"' not in ln and '"type": "result"' not in ln:
                            continue
                        if since <= 0:
                            found = True
                            break
                        mt = re.search(r'"timestamp":"([^"]+)"', ln)
                        if not mt:
                            found = True   # 行无时间戳：宁可信其有（不掩盖真实回传）
                            break
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(mt.group(1).replace("Z", "+00:00"))
                            if dt.timestamp() * 1000 >= since:
                                found = True
                                break
                        except ValueError:
                            found = True
                            break
                except OSError:
                    found = False
        results[p] = found
    return jsonify({"ok": True, "results": results})


@harness_bp.route("/events")
def harness_events():
    """事件增量（轮询兜底/断线补齐）。?sid=&after_seq="""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    return jsonify({"ok": True, "events": s.get_events_after(request.args.get("after_seq", 0, type=int)),
                    "seq": s._seq, "alive": s.alive, "busy": s.busy,
                    "busy_since": s.busy_since})


@harness_bp.route("/rename", methods=["POST"])
def harness_rename():
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    title = (data.get("title") or "").strip()[:60]
    s = _get_or_create(sid)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    s.title = title or "新会话"
    s.sync_meta()
    return jsonify({"ok": True, "title": s.title})


@harness_bp.route("/delete", methods=["POST"])
def harness_delete():
    """删会话：杀进程 + 删元数据（~/.claude 转写不动）。body: {sid}。"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    with _sessions_lock:
        s = _sessions.pop(sid, None)
    if s:
        s.close()
    with _meta_lock:
        _meta_load()
        _meta.pop(sid, None)
        _meta_tombstones.add(sid)   # 盘面上那条也别让 _meta_save 合并回来
    _meta_save()
    return jsonify({"ok": True})


def _recover_scan():
    """扫描磁盘上没进注册表的会话 jsonl（数据自救：列表的兜底入口）。

    列表唯一来源是 claude_harness.json，它一旦被清（写入撕裂/多开互相
    覆盖）会话就"看不见"了，但转写还在 ~/.claude/projects/ 下。这里把
    注册表里没有的 jsonl 全列出来，标题取文件头首条人工消息，cwd/时间
    取文件内的真实值。只读文件头，几十 MB 的转写也不会卡。

    无用会话直接屏蔽（用户定调：只留真正的会话）：
    - 人工消息为 0 → 识图/跨会话协作的后台从会话，恢复出来只有陌生
      干活记录；
    - 首条人工消息命中测试句式（hi/只回复/从1数到/暗号/探测脚本指令
      等）→ 测代理/测工具留下的垃圾；
    - 人工消息 ≤1 且文件 <100KB → 一句话探测会话，无实质内容。
    """
    import re as _re
    test_re = _re.compile(
        r"^(你好|hi\b|hello|test|测试|ping|1\+1"
        r"|只回复|回复(一个字|两个字|ok\b|hi\b|exactly)|reply with|respond with"
        r"|从\s*1\s*数到|数到\s*\d+"
        r"|记住暗号|记住你不能识图|你是一个?专门识图|你是识图会话"
        r"|call the (mcp )?tool|use the \w+ tool|run the bash command"
        r"|用 (mcp__|read 工具|bash 工具|listagents|sendmessage|ansi)"
        r"|请(用 bash 工具|直接回答|只回复|深入思考|做两件事|做三件事|调用|输出)"
        r"|输出一段)",
        _re.I)
    _meta_load()
    have = {m.get("session_id") for m in _meta.values() if m.get("session_id")}
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    items = []
    if not os.path.isdir(proj):
        return items
    for d in os.listdir(proj):
        dd = os.path.join(proj, d)
        if not os.path.isdir(dd) or d.startswith("."):
            continue          # 排除 .trash-* 之类人工归档目录，只认项目编码目录
        for fn in os.listdir(dd):
            if not fn.endswith(".jsonl"):
                continue
            csid = fn[:-len(".jsonl")]
            if csid in have:
                continue
            fp = os.path.join(dd, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            title, cwd = "", ""
            human = 0
            truncated = False
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f):
                        if i >= 200:
                            truncated = True
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        if not cwd and o.get("cwd"):
                            cwd = o["cwd"]
                        if o.get("type") != "user" or o.get("isSynthetic") or o.get("parent_tool_use_id"):
                            continue
                        c = (o.get("message") or {}).get("content")
                        txt = ""
                        if isinstance(c, str):
                            txt = c
                        elif isinstance(c, list):
                            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                                continue
                            txt = next((b.get("text", "") for b in c
                                        if isinstance(b, dict) and b.get("type") == "text"), "")
                        txt = txt.strip()
                        # 跳过 CLI 命令包装/跨会话消息/识图图片转交——都不是人话标题；
                        # 剩下的才算人工消息。识图/协作从会话一条人工都没有，
                        # 恢复它们只会让用户点开看到一堆陌生干活记录（2026-09-16
                        # 实测误导：把识图会话起名"串口控制台会话"恢复，用户点开
                        # 以为聊天历史全丢）。人工消息为 0 的不列出。
                        if not txt or txt.startswith(("<", "Another Claude", "[Image:")):
                            continue
                        human += 1
                        if not title:
                            title = txt
                        # 不提前 break：human 要数准（屏蔽判定 + 前端「你的消息×N」都靠它）
            except OSError:
                continue
            # 无用会话屏蔽：从会话 / 测试句式 / 一句话探测（规则详见函数头注释）
            if (not human
                    or test_re.match(title or "")
                    or (human <= 1 and st.st_size < 100 * 1024)):
                continue
            items.append({"session_id": csid, "human": human, "human_more": truncated,
                          "title": (title or "").replace("\n", " ").strip()[:60] or "（无标题会话）",
                          "cwd": cwd, "size": st.st_size,
                          "last_active": int(st.st_mtime * 1000)})
    items.sort(key=lambda x: -x["last_active"])
    return items


@harness_bp.route("/recoverable")
def harness_recoverable():
    """列出可恢复的孤儿会话（盘上有转写、注册表没条目）。"""
    try:
        items = _recover_scan()
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True, "items": items})


@harness_bp.route("/recover", methods=["POST"])
def harness_recover():
    """把盘上的孤儿会话找回列表：补注册表条目（不启动进程，发消息才复活）。
    body: {session_id, title?}。cwd 取转写内的真实值——--resume 必须在
    原目录跑才能续上旧上下文。"""
    data = request.get_json(force=True, silent=True) or {}
    csid = (data.get("session_id") or "").strip()
    if (not csid or "/" in csid or "\\" in csid or ".." in csid
            or not all(ch in "0123456789abcdef-" for ch in csid.lower())):
        return jsonify({"ok": False, "err": "非法 session_id"}), 400
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    hit = None
    if os.path.isdir(proj):
        for d in os.listdir(proj):
            p = os.path.join(proj, d, csid + ".jsonl")
            if os.path.isfile(p):
                hit = p
                break
    if not hit:
        return jsonify({"ok": False, "err": "磁盘上没找到该会话记录"}), 404
    cwd = ""
    try:
        with open(hit, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("cwd"):
                    cwd = o["cwd"]
                    break
    except OSError:
        pass
    st = os.stat(hit)
    s = HarnessSession(uuid.uuid4().hex, cwd=cwd or _st.HOME_DIR,
                       session_id=csid,
                       title=(data.get("title") or "").strip()[:60] or "恢复的会话")
    s.created = int(st.st_mtime * 1000)
    s.last_active = s.created
    s.sync_meta()
    return jsonify({"ok": True, "sid": s.sid})


@harness_bp.route("/models")
def harness_models():
    d = available_models()
    # v2.19：附带多模态名单（前端下拉打 👁 标记；判定口径同 start() 注入）
    # v2.28.1：mm_mcp 字段退役——非真多模态一律走 MCP（默认态），无需枚举
    return jsonify({"ok": True, "models": d.get("models", []),
                    "default": d.get("default"),
                    "mm": [m for m in d.get("models", []) if _model_is_multimodal(m)]})


@harness_bp.route("/mcp_list")
def harness_mcp_list():
    """/mcp 命令的数据源。headless(-p) 会话没有 CLI 的交互式 MCP 面板，
    这里代跑 `claude mcp list` 拿真实的 server 清单与连接健康状态，
    原文返给前端按行渲染（CLI 的输出格式随版本变，不硬解析）。"""
    exe, is_shim = _resolve_claude_exe()
    argv = (["cmd.exe", "/c", exe] if is_shim else [exe]) + ["mcp", "list"]
    try:
        r = subprocess.run(
            argv, capture_output=True, timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or b"").decode("utf-8", errors="replace")
        err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        if err:
            out += ("\n" + err)
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "err": "claude mcp list 超时（45s）——可能有 server 健康检查卡住"})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)})
    return jsonify({"ok": True, "output": out.strip()})


@harness_bp.route("/vision_status")
def harness_vision_status():
    """v2.28：识图会话退役——状态 API 只回静态退役形态。前端徽章按
    needed=false + alive=false 显示「多模态直读/关闭」，不再有会话态。
    保留端点是为兼容旧前端轮询（改字段会 JS 报错）。"""
    cfg = _vision_load()
    return jsonify({"ok": True, "enabled": bool(cfg["enabled"]),
                    "name": cfg["name"], "model": cfg["model"],
                    "alive": False, "busy": False, "needed": False,
                    "sid": "", "last_seq": 0, "recent": [], "busy_since": None,
                    "last_done": 0, "last_brief": ""})


@harness_bp.route("/system_prompt", methods=["GET"])
def harness_get_prompt():
    """读用户自定义提示词条目列表（v2.8 多条目；?cwd= 时附带每条 active 计算）。
    旧单条 harness_system_prompt 自动迁移成一条 global 条目（一次性）。"""
    items = _prompts_load()
    if not items:
        # 旧版单条迁移（一次性）：写过 v2.4 单条提示词的机器升级后无缝接续
        try:
            with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            legacy = d.get(_PROMPTS_LEGACY_KEY)
            if isinstance(legacy, str) and legacy.strip():
                items = [{"id": "migrated-legacy", "scope": "global", "project": "",
                          "note": "（v2.4 迁移）", "text": legacy.strip(),
                          "enabled": True}]
                _prompts_save(items)
                d.pop(_PROMPTS_LEGACY_KEY, None)
                tmp = _st.CONFIG_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=1)
                os.replace(tmp, _st.CONFIG_FILE)
        except Exception:
            pass
    cwd = (request.args.get("cwd") or "").strip()
    out = []
    for it in items:
        o = dict(it)
        if cwd:
            o["active"] = bool(it.get("enabled", True)) and (
                it.get("scope") != "project"
                or _prompt_matches_project(it, cwd))
        out.append(o)
    return jsonify({"ok": True, "prompts": out})


@harness_bp.route("/system_prompt", methods=["POST"])
def harness_set_prompt():
    """写用户自定义提示词（v2.8 多条目整表保存）。
    body: {prompts: [{id, scope, project, note, text, enabled}]}。
    整表覆盖（前端管理界面即真相源）；id 缺失的条目自动补 uuid。
    只影响之后启动/复活的会话进程（系统提示词是进程启动参数）。"""
    data = request.get_json(force=True, silent=True) or {}
    raw = data.get("prompts")
    if not isinstance(raw, list):
        return jsonify({"ok": False, "err": "prompts 必须是数组"}), 400
    items = []
    for it in raw:
        if not isinstance(it, dict) or not str(it.get("text") or "").strip():
            continue   # 空文本条目直接丢弃
        items.append({
            "id": str(it.get("id") or ("p-" + uuid.uuid4().hex[:8])),
            "scope": it.get("scope") if it.get("scope") in ("global", "project") else "global",
            "project": str(it.get("project") or "").strip(),
            "note": str(it.get("note") or "").strip(),
            "text": str(it.get("text") or "").strip(),
            "enabled": bool(it.get("enabled", True)),
        })
    ok, err = _prompts_save(items)
    if not ok:
        return jsonify({"ok": False, "err": err or "写入失败"}), 500
    return jsonify({"ok": True, "count": len(items)})


@harness_bp.route("/mm_probe", methods=["POST"])
def harness_mm_probe():
    """运行时探测一个模型的识图能力（v2.28.1 单段式：只测真多模态直读）。
    body: {model}。inline → 并入 mm_extra（👁）并记缓存 True；非 inline →
    记缓存 False，分类自动落 mcp（默认通道，无需名单）。"""
    data = request.get_json(force=True, silent=True) or {}
    model = str(data.get("model") or "").strip()
    if not model:
        return jsonify({"ok": False, "err": "need model"})
    pkey = _mm_probe_key(model)     # v2.27.2：按方案签名缓存，切方案自动重探
    cached = _mm_probed_load().get(pkey)
    if cached is not None:
        mode = "inline" if cached else "mcp"
        label = "真多模态（直读）" if cached else "非真多模态（走 MCP 通道）"
        return jsonify({"ok": True, "model": model, "mode": mode,
                        "cached": True, "msg": "缓存结果（当前方案）：" + label})
    with _MM_PROBE_LOCK:          # 探测要起子进程，同时只跑一个
        mode, msg = _mm_probe_model(model)
    # merge 落盘（不整键替换，别把并发写进来的其他字段冲掉）
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    v = d.get(_VISION_KEY)
    if not isinstance(v, dict):
        v = {}
    p = v.get("mm_probed")
    if not isinstance(p, dict):
        p = {}
    p[pkey] = (mode == "inline")   # 仅 inline 记 True；False = 走 MCP 通道
    v["mm_probed"] = p
    d[_VISION_KEY] = v
    try:
        tmp = _st.CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _st.CONFIG_FILE)
    except Exception:
        pass
    # 名单归位：inline → mm_extra（真多模态 👁 名单）；mcp 无需名单（默认态）
    if mode == "inline":
        cfg = _vision_load()
        lname = model.lower()
        if not any(lname == (x or "").lower() or lname.startswith((x or "").lower() + "[")
                   for x in cfg["mm_extra"]):
            cfg["mm_extra"] = list(cfg["mm_extra"]) + [model]
            _vision_save(cfg)
    return jsonify({"ok": True, "model": model, "mode": mode, "msg": msg})


@harness_bp.route("/vision", methods=["GET"])
def harness_get_vision():
    """读识图配置（v2.28.2：MCP 后端配置——模型/端点映射/提示词）。
    附带 defaults 供前端「恢复默认」按钮用（mcp_prompt 缺省取 MCP 内置）。"""
    from .harness_vision_mcp import MCP_DEFAULT_SYSTEM
    cfg = _vision_load()
    return jsonify({"ok": True, "vision": cfg,
                    "defaults": {"mcp_prompt": MCP_DEFAULT_SYSTEM,
                                 "model_map": {}},
                    "running": False,
                    "models": available_models().get("models", []),
                    "default_model": available_models().get("default")})


@harness_bp.route("/vision", methods=["POST"])
def harness_set_vision():
    """写识图配置。body: {enabled, model, mcp_prompt?, model_map?, mm_extra?}。
    v2.28.2：配置即 MCP 行为——MCP 每次调用时读盘，改完即刻生效，无需
    重启会话。旧键 prompt/name（会话时代）不再写入，存量值自然闲置。"""
    data = request.get_json(force=True, silent=True) or {}
    old = _vision_load()
    cfg = {
        "enabled": bool(data.get("enabled", False)),
        "model": str(data.get("model") or "").strip(),
        "mcp_prompt": str(data.get("mcp_prompt") or "").strip(),
    }
    # v2.25：mm_extra（多模态手补名单）随保存一起落盘——旧实现重建 cfg 时
    # 没带这个字段，_vision_save 整体覆盖后用户配过的名单被静默清空
    mm = data.get("mm_extra")
    if isinstance(mm, list):
        cfg["mm_extra"] = [str(x).strip() for x in mm if str(x).strip()]
    else:
        cfg["mm_extra"] = list(old.get("mm_extra") or [])
    # v2.28.2：端点模型映射——dict 或 "关键字=模型" 行列表均收，未提交保旧值
    mmap_raw = data.get("model_map")
    if isinstance(mmap_raw, dict) or isinstance(mmap_raw, list):
        mmap = {}
        if isinstance(mmap_raw, dict):
            for k, v in mmap_raw.items():
                if str(k).strip() and str(v).strip():
                    mmap[str(k).strip().lower()] = str(v).strip()
        else:
            for line in mmap_raw:
                kv = str(line).split("=", 1)
                if len(kv) == 2 and kv[0].strip() and kv[1].strip():
                    mmap[kv[0].strip().lower()] = kv[1].strip()
        cfg["model_map"] = mmap
    else:
        cfg["model_map"] = dict(old.get("model_map") or {})
    ok, err = _vision_save(cfg)
    if not ok:
        return jsonify({"ok": False, "err": err or "写入失败"}), 500
    return jsonify({"ok": True, "vision": cfg})


@harness_bp.route("/vision/start", methods=["POST"])
def harness_start_vision():
    """v2.28：识图会话退役——手动拉起端点改为返回退役说明（前端重试按钮
    不再拉起后台会话；识图走 MCP 通道，无需预热）。"""
    return jsonify({"ok": False,
                    "err": "识图会话已退役：识图改走 MCP 通道"
                           "（mcp__4_5v_mcp__analyze_image），无需手动拉起"}), 400


@harness_bp.route("/vision/stop", methods=["POST"])
def harness_stop_vision():
    stop_vision_session()
    return jsonify({"ok": True})


@harness_bp.route("/roles")
def harness_roles_info():
    """v2.29.2：三角色设计说明（/roles 命令数据源）。resolved 是按当前
    API 方案解析出的实际模型（换方案自动适配）。v2.30.2 带 mode——按
    settings 默认模型判定的当前形态（strong 决策者 / light 轻主力）。
    v2.34：roles 含 audit_mode/max_free_lines（defaults 兜底）；附
    models/default_model 供配置面板下拉用。"""
    from .harness_roles import (resolve_role_models, roles_cfg,
                                roles_mode)
    ex, co = resolve_role_models()
    try:
        mode = roles_mode(available_models().get("default"))
    except Exception:
        mode = "strong"
    return jsonify({"ok": True, "roles": roles_cfg(), "mode": mode,
                    "resolved": {"executor": ex, "coder": co,
                                 "designer": co},
                    "models": available_models().get("models", []),
                    "default_model": available_models().get("default")})


@harness_bp.route("/agent_models")
def harness_agent_models():
    """v2.35（P1-4）：子代理类型 → 模型名映射。扫 ~/.claude/agents/*.md 的
    frontmatter（name/model 字段，同 harness_roles 的安装格式），供前端在
    Task 起跑时显示子代理用什么模型。读不到 model 的条目不出现在映射里
    （内置代理 Explore/Plan 等没有定义文件——前端标注「主链模型」）。
    实跑模型以子代理 assistant 事件的 message.model 为准（网关映射后可能与
    frontmatter 不同），本接口只管起跑时的预显示。只读、无缓存（目录极小）。"""
    agents = {}
    try:
        import glob as _g
        d = os.path.join(os.path.expanduser("~"), ".claude", "agents")
        for p in _g.glob(os.path.join(d, "*.md")):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(4096)
            except Exception:
                continue
            if not head.lstrip().startswith("---"):
                continue
            parts = head.split("---")
            if len(parts) < 3:
                continue
            fm = parts[1]
            m_name = re.search(r"^name:\s*(.+?)\s*$", fm, re.M)
            m_model = re.search(r"^model:\s*(.+?)\s*$", fm, re.M)
            if not m_model:
                continue
            name = (m_name.group(1) if m_name else "").strip().strip('"\'') \
                or os.path.splitext(os.path.basename(p))[0]
            model = m_model.group(1).strip().strip('"\'')
            if name and model:
                agents[name] = model
    except Exception:
        pass
    return jsonify({"ok": True, "agents": agents})


@harness_bp.route("/roles", methods=["POST"])
def harness_set_roles():
    """v2.29.3 开关；v2.34 扩成整节配置（merge 写盘，只动出现的键）。
    body 可含 {enabled, executor_model, coder_model, model_map,
    audit_mode, max_free_lines}。生效路径与开关一致：模型槽/免审线出现在
    引导词里 → 指纹热更下条消息换词重启 + agents 重生成；audit_mode 在
    回合结算时读盘，即时生效。model_map 行式 "端点关键字=执行者,编程者"
    （编程者可省=与执行者同）或 dict {关键字:{executor,coder}}。"""
    from .harness_roles import update_roles_cfg
    data = request.get_json(force=True, silent=True) or {}
    patch = {}
    if "enabled" in data:
        patch["enabled"] = bool(data.get("enabled"))
    for k in ("executor_model", "coder_model"):
        if k in data:
            patch[k] = str(data.get(k) or "").strip()
    if "audit_mode" in data:
        # v2.34.1：出现但不合法 → 400（与 max_free_lines 口径一致——静默
        # 跳过会让调用方假成功，配置面板显示的与实际生效的不符）
        if data.get("audit_mode") not in ("auto", "warn", "off"):
            return jsonify({"ok": False,
                            "err": "audit_mode 须为 auto/warn/off"}), 400
        patch["audit_mode"] = data.get("audit_mode")
    if "max_free_lines" in data:
        try:
            patch["max_free_lines"] = max(0, min(100000,
                                                 int(data.get("max_free_lines"))))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "err": "免审线须为数字"}), 400
    mmap_raw = data.get("model_map")
    if isinstance(mmap_raw, (dict, list)):
        mmap = {}
        if isinstance(mmap_raw, dict):
            for k, v in mmap_raw.items():
                if not str(k).strip() or not isinstance(v, dict):
                    continue
                ex = str(v.get("executor") or "").strip()
                co = str(v.get("coder") or "").strip()
                if ex and co:
                    mmap[str(k).strip().lower()] = {"executor": ex, "coder": co}
        else:
            for line in mmap_raw:
                kv = str(line).split("=", 1)
                if len(kv) != 2 or not kv[0].strip():
                    continue
                rhs = [x.strip() for x in kv[1].split(",") if x.strip()]
                if not rhs:
                    continue
                mmap[kv[0].strip().lower()] = {
                    "executor": rhs[0],
                    "coder": rhs[1] if len(rhs) > 1 else rhs[0]}
        patch["model_map"] = mmap
    if not patch:
        return jsonify({"ok": False, "err": "没有可写入的配置项"}), 400
    ok, err = update_roles_cfg(patch)
    if not ok:
        return jsonify({"ok": False, "err": err or "写入失败"}), 500
    resp = {"ok": True}
    resp.update(patch)
    return jsonify(resp)


@harness_bp.route("/skills")
def harness_skills():
    """技能列表（复用 claude_sessions 发现层，harness 上下文 cwd）。
    v2.27：附带中文描述缓存（skill_zh_cache.json），前端「技能需要翻译」
    的持久层——静态映射未命中的英文 desc，由 /skill_zh/translate 落缓存。"""
    from .claude_sessions import list_skills
    cwd = request.args.get("cwd") or None
    return jsonify({"ok": True, "skills": list_skills(cwd),
                    "zh": _skill_zh_load()})


# ---- 技能描述汉化（v2.27：新增技能自动翻译，免长期手工维护映射表）----
_SKILL_ZH_FILE = os.path.join(_st.HOME_DIR, "skill_zh_cache.json")


def _skill_zh_load():
    try:
        with open(_SKILL_ZH_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _skill_zh_save(d):
    try:
        tmp = _SKILL_ZH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _SKILL_ZH_FILE)
    except OSError:
        pass


_llm_cool_until = [0.0]     # 翻译失败冷却：网关故障/方案切换窗口期不反复白发请求


def _llm_translate_batch(pairs):
    """用 settings.json 配的模型批量翻译英文技能描述。返回 {原文: 译文}。

    走 anthropic 兼容网关（base_url + /v1/messages），失败静默空表——
    翻译是锦上添花，不该让菜单报错；冷却 2 分钟后前端下次触发再试。
    每次调用都实时重读 settings.json：用户切换配置方案（网关/模型/凭据）
    后自动跟随，无需重启。
    """
    import urllib.request
    env = {}
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            env = (json.load(f).get("env") or {})
    except Exception:
        return {}
    base = (env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    token = env.get("ANTHROPIC_AUTH_TOKEN") or ""
    # settings 里的模型名带 [1M]/[1m] 这类上下文窗口标记（CLI 侧口径），
    # 网关直调不认——实测 400「模型不存在」，剥掉末尾方括号段再发
    model = re.sub(r"\[[^\]]+\]$", "", env.get("ANTHROPIC_MODEL") or "")
    if not base or not token or not model:
        return {}
    body = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(pairs.values()))
    prompt = (
        "把下面的软件技能描述逐条翻译成简洁的简体中文一句话（保留产品名/"
        "专有名词，不超过40字）。严格按「序号. 中文」逐行输出，不要任何"
        "解释或多余内容。\n\n" + body)
    payload = json.dumps({"model": model, "max_tokens": 4000,
                          "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        base + "/v1/messages", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token,
                 "x-api-key": token,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
        text = "".join(b.get("text", "") for b in (d.get("content") or [])
                       if isinstance(b, dict))
        _llm_cool_until[0] = 0.0          # 成功清冷却
    except Exception:
        _llm_cool_until[0] = time.time() + 120   # 失败冷却 2 分钟再试
        return {}
    out = {}
    keys = list(pairs.keys())
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if not m:
            continue
        i = int(m.group(1)) - 1
        if 0 <= i < len(keys):
            out[keys[i]] = m.group(2).strip()[:80]
    return out


@harness_bp.route("/skill_zh/translate", methods=["POST"])
def harness_skill_zh_translate():
    """把未汉化的英文技能描述交给 LLM 翻译并入缓存。body: {items:[{name,desc}]}。
    返回 {ok, map}（本次新增的翻译，含缓存里已有的）。"""
    data = request.get_json(force=True, silent=True) or {}
    items = data.get("items") or []
    cache = _skill_zh_load()
    # 待翻 = 描述非空、不含中文、且缓存没覆盖的原文（构建时已跳过缓存命中）
    todo = []
    for it in items:
        if not isinstance(it, dict):
            continue
        desc = (it.get("desc") or "").strip()
        if not desc or re.search(r"[一-鿿]", desc) or desc in cache:
            continue
        if desc not in todo:
            todo.append(desc)
    if todo and time.time() >= _llm_cool_until[0]:
        translated = _llm_translate_batch({k: k for k in todo})
        for src, zh in translated.items():
            if zh:
                cache[src] = zh
        if translated:
            _skill_zh_save(cache)
    return jsonify({"ok": True, "map": cache})


@harness_bp.route("/files")
def harness_files():
    """@ 文件引用候选列表：浅层扫描会话 cwd（两层深度防大目录卡顿，
    隐藏文件滤除；名字短的排前——输入 a.js 时 a.js 应排在 xxxa.js 前）。"""
    cwd = request.args.get("cwd") or os.path.expanduser("~")
    q = (request.args.get("q") or "").strip().lower()
    if not os.path.isdir(cwd):
        return jsonify({"ok": False, "err": "目录不存在"}), 400
    # Windows 保留设备名（nul/con/prn/aux/com1…）：@ 引用出来无法读取，滤掉
    _win_reserved = {"nul", "con", "prn", "aux"}
    out, seen = [], set()

    def scan(dirp, depth):
        if len(out) >= 60 or depth < 0:
            return
        try:
            with os.scandir(dirp) as it:
                ents = list(it)
        except OSError:
            return
        dirs = []
        for e in ents:
            if len(out) >= 60:
                return
            if e.name.startswith("."):
                continue
            if os.name == "nt" and e.name.lower() in _win_reserved:
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                dirs.append(e)
                continue
            if q and q not in e.name.lower() and q not in e.path.lower():
                continue
            if e.path not in seen:
                seen.add(e.path)
                out.append({"name": e.name, "path": e.path})
        for e in dirs:   # 结果不足时下钻子目录
            if len(out) >= 60:
                return
            scan(e.path, depth - 1)

    scan(cwd, 1)
    out.sort(key=lambda x: len(x["name"]))
    return jsonify({"ok": True, "files": out[:30]})


@harness_bp.route("/upload", methods=["POST"])
def harness_upload():
    """附件上传：{name, data_b64} → 存 harness_uploads/ → 返回绝对路径。
    图片走消息 image 块；其他文件走路径文本（模型 Read 读取）。"""
    data = request.get_json(force=True, silent=True) or {}
    name = os.path.basename((data.get("name") or "file.bin").replace("\\", "/"))[:120]
    b64 = data.get("data_b64") or ""
    if not b64:
        return jsonify({"ok": False, "err": "空文件"}), 400
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return jsonify({"ok": False, "err": "编码无效"}), 400
    if len(raw) > _UPLOAD_MAX:
        return jsonify({"ok": False, "err": "文件过大（>20MB）"}), 400
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    # 防同名覆盖：uuid 前缀
    path = os.path.join(_UPLOAD_DIR, uuid.uuid4().hex[:8] + "_" + name)
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError as e:
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True, "path": path, "name": name, "size": len(raw)})


@harness_bp.route("/file")
def harness_file():
    """附件原件（v2.19）。

    前端 chip 缩略图原先直接拿 upload 返回的**本地绝对路径**当 <img src>——
    http 页面加载不了 file:// 之外的盘符路径，结果是破图占位符叠一行文件名
    （用户看到的「🖼 2.png 2.png」）。改成前端用 /api/harness/file?name=，
    这里只读地回 _UPLOAD_DIR 里的原件。

    防穿越：只取 basename，再校验 realpath 落在 _UPLOAD_DIR 内。
    """
    fn = os.path.basename((request.args.get("name") or "").replace("\\", "/"))
    if not fn:
        return jsonify({"ok": False, "err": "缺少 name"}), 400
    if os.path.realpath(os.path.join(_UPLOAD_DIR, fn)).startswith(
            os.path.realpath(_UPLOAD_DIR) + os.sep):
        return send_from_directory(_UPLOAD_DIR, fn)
    return jsonify({"ok": False, "err": "非法路径"}), 403
