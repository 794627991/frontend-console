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
import os, json, base64, sys, subprocess, threading, time, uuid
from queue import Queue, Empty

from flask import Blueprint, request, jsonify, Response

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
    return {"enabled": False, "model": "", "prompt": VISION_DEFAULT_PROMPT,
            "name": VISION_DEFAULT_NAME}


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
    except Exception:
        pass
    return cfg


def _vision_save(cfg):
    """原子写识图配置（只覆盖 _VISION_KEY，其余字段保留）。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    d[_VISION_KEY] = cfg
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


def vision_bridge_text():
    """生成注入每个主会话的「识图转交」引导段（识图未启用则空串）。

    这是问题2 的核心：主会话默认不知道自己有识图同伴，必须显式告知——
    告知它 peer 名叫什么、什么时候该转交、怎么转交、怎么收回结论。
    """
    cfg = _vision_load()
    if not cfg["enabled"]:
        return ""
    name = cfg["name"]
    return (
        "【识图转交】\n"
        "本机有一个专用识图会话（多模态模型），可通过 Claude Code 原生的 "
        "ListAgents / SendMessage 工具联系，会话名是「%s」（可能带 [ref] 后缀，"
        "照原样引用即可）。\n"
        "你自己不具备看图能力，所以凡是需要「看图」的任务都必须转交给它：\n"
        "- 触发场景：用户发来图片、给出图片路径让你分析、让你看截图/照片/"
        "截图型日志/UI 截图/寄存器截图，或任何需要读取图像内容的问题。\n"
        "- 转交方式：SendMessage 给「%s」，消息里附上图片的绝对路径 + "
        "你想知道的具体问题。一次可以给多张图，要说清每张图各问什么。\n"
        "- 不要加 notify_when_idle（默认行为就会等它回复）。\n"
        "- 收回结论：它的回复会自动送达你，直接转述给用户即可，不要自己"
        "编造图片内容。\n"
        "- 若 ListAgents 里找不到该名字，说明识图会话没起来，如实告诉用户"
        "去「📜 提示词 — 识图会话配置」里检查开关，不要假装看过图。\n"
        "图片本身不需要你读取，读图是它的职责。"
    ) % (name, name)


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
    """取（必要时新建并启动）识图后台会话。返回 HarnessSession 或 None。

    独立 sid，不 sync_meta → 不出现在用户的会话列表里（是后台配角）。
    """
    cfg = _vision_load()
    if not cfg["enabled"]:
        return None
    with _vision_lock:
        s = _vision_obj[0]
        if s is not None and s.alive:
            return s
        if s is not None:
            try:                     # 死进程先清掉，防同名残留
                with _sessions_lock:
                    _sessions.pop(s.sid, None)
                s.close()
            except Exception:
                pass
        try:
            s = HarnessSession(uuid.uuid4().hex, cwd=_st.HOME_DIR,
                               model=cfg["model"] or None,
                               title="识图会话", name=cfg["name"])
            s.hidden = True          # 不 sync_meta：不进用户会话列表
            s.is_vision = True
            _cleanup_stale_vision_peers(cfg["name"])   # 先扫掉同名孤儿，防撞车
            s.start()
        except Exception:
            _vision_obj[0] = None
            return None
        with _sessions_lock:
            _sessions[s.sid] = s
        _vision_obj[0] = s
        return s


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


def _meta_load():
    global _meta, _meta_loaded
    if _meta_loaded:
        return
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _meta = {k: v for k, v in d.items() if isinstance(v, dict) and v.get("sid")}
    except Exception:
        _meta = {}
    _meta_loaded = True


def _meta_save():
    """原子写（tmp + replace，同 claude_default 模式）。锁内快照防并发撕裂。"""
    with _meta_lock:
        _meta_load()
        data = dict(_meta)
    try:
        os.makedirs(os.path.dirname(_META_FILE), exist_ok=True)
        tmp = _META_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _META_FILE)
    except Exception:
        pass


# ---- 可选模型列表（读 ~/.claude/settings.json env 的 LANZ 映射，缓存一次）----
_models_cache = None


def available_models():
    global _models_cache
    if _models_cache is not None:
        return _models_cache
    names, default = [], None
    try:
        with open(os.path.join(os.path.expanduser("~"), ".claude", "settings.json"),
                  "r", encoding="utf-8") as f:
            env = (json.load(f) or {}).get("env") or {}
        default = env.get("ANTHROPIC_MODEL") or None
        for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                  "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                  "ANTHROPIC_DEFAULT_FLASH_MODEL"):
            v = env.get(k)
            if v and v not in names:
                names.append(v)
    except Exception:
        pass
    if not default and names:
        default = names[0]   # settings 无显式默认 → 取首个映射（与 CLI 回退语义一致）
    _models_cache = {"models": names, "default": default}
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


def _ask_mcp_cfg_path(sid):
    """写本会话的 --mcp-config 文件（内容极小，每次 start 覆写）。

    路径用正斜杠：cmd.exe shim 会吞反斜杠转义，JSON 里带 \\ 的 Windows 路径
    经 shim 传递后解析失败（实测 --mcp-config 内联 JSON 会被引号处理吃掉）。
    """
    d = os.path.join(_st.HOME_DIR, "harness_ask")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return None
    # 打包（PyInstaller）下 src 不在磁盘上，改用 exe 自己的 --mcp-ask 模式
    if getattr(sys, "frozen", False):
        cmd, args = sys.executable, ["--mcp-ask"]
    else:
        script = os.path.join(_SRC_DIR, "harness_ask_mcp.py").replace("\\", "/")
        cmd, args = (sys.executable or "python"), [script]
    cfg = {"mcpServers": {"harness": {
        "command": cmd,
        "args": args,
        "env": {"HARNESS_SID": sid},
    }}}
    p = os.path.join(d, "%s.json" % sid[:16])
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        return None
    return p.replace("\\", "/")


class HarnessSession:
    """一个 stream-json harness 会话（kind='harness'）。

    元数据（sid/title/model/cwd/session_id）持久化；进程是易耗品——
    闲置被回收、切回自动复活（--resume 续上下文）。port_id 稳定 =
    harness:<sid8>，前端 tab 与后端会话一一对应。
    """

    kind = "harness"

    def __init__(self, sid, cwd=None, model=None, session_id=None, title="", name=None):
        self.sid = sid
        self.port_id = "harness:" + sid[:8]
        self.cwd = cwd or os.path.expanduser("~")
        self.model = model or None
        self.session_id = session_id or None    # claude 侧真实会话 id（复活用）
        self.title = title or ""
        self.name = name or None    # --name：peer 网络里别人按它寻址
        self.hidden = False         # 识图后台会话：不进用户会话列表（不 sync_meta）
        self.is_vision = False      # 识图会话：start() 时用固定的基础提示词
        self.created = int(time.time() * 1000)
        self.last_active = self.created
        # ---- 运行时（进程相关，不持久化）----
        self._proc = None
        self.alive = False
        self.busy = False
        # v2.17 交互式提问：MCP 工具调用发起的待答问题
        #   {req_id, title, questions, answer, done, ts}
        self.ask = None
        self.ask_lock = threading.Lock()
        self.events = []
        self.events_lock = threading.Lock()
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
                "name": self.name,
                "created": self.created, "last_active": self.last_active}

    def sync_meta(self):
        if getattr(self, "hidden", False):
            return          # 识图后台会话不出现在用户会话列表
        with _meta_lock:
            _meta_load()
            _meta[self.sid] = self.to_meta()
        _meta_save()

    # ---- 进程生命周期 ----
    def start(self):
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
            _cfg = _ask_mcp_cfg_path(self.sid)
            if _cfg:
                argv += ["--mcp-config", _cfg,
                         "--allowedTools", "mcp__harness__ask_user"]
        # v2.14：识图后台会话用固定基础提示词；普通会话走用户提示词体系 +
        # 识图转交引导（主会话默认不知道有识图同伴，必须显式告知）。
        if self.is_vision:
            sys_prompt = (_vision_load().get("prompt") or "").strip()
        else:
            parts = [_collect_system_prompt(self.cwd), vision_bridge_text(),
                     ask_bridge_text()]
            sys_prompt = "\n\n".join(p for p in parts if p)
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
        _trust_workspace(self.cwd)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            argv, cwd=self.cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
        self.alive = True
        self.busy = False
        self.last_active = int(time.time() * 1000)
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def kill_proc(self):
        """只杀进程保元数据与事件缓冲（闲置回收/复活前清理用）。
        v2.14：强杀会让 claude 来不及清理 peer 注册条目（~/.claude/sessions/
        <pid>.json），残留条目指向死 pid —— 下次 ListAgents 会看到幽灵会话。
        所以杀完主动清理自己那条注册。"""
        self.alive = False
        self.busy = False
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
    def send_message(self, text, image_paths=None, file_paths=None):
        """发消息：文本 + 可选图片（base64 块，实测网关透传）+ 文件路径（文本
        附录，任何模型都能用 Read 读）。返回 (ok, err)。"""
        if not self._proc or not self.alive:
            return False, "会话进程已退出"
        if self.busy:
            return False, "claude 正在回复中，请稍候"
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
            return False, "发送失败：%s" % e
        self.busy = True
        self.last_active = int(time.time() * 1000)
        # 首条消息定标题（微信式：会话标题=首句）
        if not self.title and text:
            self.title = re_title(text)
            self.sync_meta()
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
        try:
            self._proc.stdin.write(b"")   # 探活（不阻塞 stdin 写）
        except Exception:
            pass
        self.kill_proc()
        self.emit({"kind": "interrupted", "text": "已中断回复"})

    # ---- 事件层 ----
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
                if typ == "system" and o.get("session_id") and o.get("subtype") == "init":
                    if o.get("session_id") != self.session_id:
                        self.session_id = o.get("session_id")
                        self.sync_meta()
                if typ == "result":
                    self.busy = False
                    self.last_result = o
                self.emit({"kind": "event", "data": o})
        except Exception:
            pass
        finally:
            self.alive = False
            self.busy = False
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
                           name=m.get("name"))
        s.created = m.get("created") or s.created
        s.last_active = m.get("last_active") or s.last_active
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
            ensure_vision_session()      # 没起/挂了就拉起（配置未启用时是空操作）
        except Exception:
            pass


def _ensure_gc():
    global _gc_started
    if not _gc_started:
        _gc_started = True
        threading.Thread(target=_gc_loop, daemon=True).start()


def ensure_vision_bg():
    """工具启动 claude 后自动拉起识图会话（放线程里，不阻塞启动）。
    daemon 线程 + 吞异常：识图起不来不能影响主功能可用。"""
    def _run():
        try:
            ensure_vision_session()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# 历史转写重建（切回会话时把历史灌进气泡）
# ---------------------------------------------------------------------------
_SKIP_RE = None


def transcript_for(s):
    """sid → 气泡行数组。claude 侧 session_id 的 jsonl 全量解析：
    user(typed 文本/图片/文件附件) / assistant(文本/工具调用) / tool_result 摘要。
    返回 None 表示转写不存在（新会话还没聊，气泡本来就空）。"""
    global _SKIP_RE
    if _SKIP_RE is None:
        import re as _re
        _SKIP_RE = _re.compile(r"^<(local-command-caveat|local-command-stdout|command-name|command-message|command-args|bash-)")
    sid = s.session_id
    if not sid:
        return None
    import glob as _glob
    path = None
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    for cand in _glob.glob(os.path.join(proj, "*", sid + ".jsonl")):
        path = cand
        break
    if not path:
        return None
    lines = []
    call_by_id = {}           # tool_use_id -> 行 dict（把 tool_result 挂回调用行）
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
                msg = o.get("message") or {}
                content = msg.get("content")
                if typ == "user":
                    if isinstance(content, str):
                        t = content
                        # harness 通道从 stdin 注入，promptSource 是 "sdk"（不是 typed）；
                        # 排除标准是"非用户输入"（工具注入 default）——命令噪音由 _SKIP_RE 挡
                        ps_ok = (o.get("promptSource") in (None, "typed", "sdk")) or \
                            (o.get("origin") or {}).get("kind") == "human"
                        if t and ps_ok and not _SKIP_RE.match(t.strip()):
                            lines.append({"role": "user", "text": t[:8000]})
                    elif isinstance(content, list):
                        trs = [b for b in content
                               if isinstance(b, dict) and b.get("type") == "tool_result"]
                        if trs:
                            # 执行结果挂回对应 tool_use 行（前端详情弹层用）
                            for b in trs:
                                line = call_by_id.get(b.get("tool_use_id"))
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
                            lines.append({"role": "user", "text": t[:8000], "images": imgs, "files": files})
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
                                          "input": b.get("input") or {}})
                    # 思考先出：一轮里 thinking 在工具调用之前，重建后「思考抽屉」才在
                    # 「执行抽屉」上方（与流式渲染同序）
                    if thinks:
                        lines.append({"role": "thinking", "text": "\n".join(thinks)[:8000]})
                    # 空白/纯换行的 text 块要丢掉：模型每轮都会吐一个 "\n\n" 占位，
                    # 落盘后仍是真值 → 重建时每条渲染成一个空白 AI 气泡（历史会话
                    # 满屏空白圆角条的根因），还把真正的思考/工具行挤出可视区。
                    t = "\n".join(texts).strip()
                    if t:
                        lines.append({"role": "assistant", "text": t[:8000]})
                    for tl in tools:
                        row = {"role": "tool", "text": tl["name"], "summary": tl["summary"],
                               "input": tl["input"], "result": None}
                        if tl["id"]:
                            call_by_id[tl["id"]] = row
                        lines.append(row)
    except OSError:
        return None
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
    ensure_vision_bg()      # v2.14：启动 claude 会话即后台拉起识图会话
    if sid:
        s = _get_or_create(sid)
        if not s:
            return jsonify({"ok": False, "err": "会话不存在"}), 404
        if not s.alive and not s.revive_if_dead():
            return jsonify({"ok": False, "err": "会话已失效（无法恢复上下文）"}), 400
        return jsonify({"ok": True, "port_id": s.port_id, "sid": s.sid, "kind": "harness",
                        "cwd": s.cwd, "model": s.model, "title": s.title})
    # 新会话
    new_sid = uuid.uuid4().hex
    s = HarnessSession(new_sid, cwd=cwd, model=model)
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
    """会话列表（持久化元数据，新→旧）。"""
    _meta_load()
    with _sessions_lock:
        live = {sid: (s.alive, s.busy) for sid, s in _sessions.items()}
    items = []
    for sid, m in _meta.items():
        alive, busy = live.get(sid, (False, False))
        items.append({"sid": sid, "title": m.get("title") or "新会话",
                      "model": m.get("model"), "cwd": m.get("cwd", ""),
                      "session_id": m.get("session_id"), "has_history": bool(m.get("session_id")),
                      "created": m.get("created", 0), "last_active": m.get("last_active", 0),
                      "alive": alive, "busy": busy})
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
                    "busy": s.busy, "model": s.model, "title": s.title, "seq": s._seq})


@harness_bp.route("/events")
def harness_events():
    """事件增量（轮询兜底/断线补齐）。?sid=&after_seq="""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    return jsonify({"ok": True, "events": s.get_events_after(request.args.get("after_seq", 0, type=int)),
                    "seq": s._seq, "alive": s.alive, "busy": s.busy})


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
    _meta_save()
    return jsonify({"ok": True})


@harness_bp.route("/models")
def harness_models():
    return jsonify({"ok": True, **available_models()})


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


@harness_bp.route("/vision", methods=["GET"])
def harness_get_vision():
    """读识图会话配置 + 运行时状态（是否已就绪、实际存活）。
    附带 defaults 供前端「恢复默认」按钮用。"""
    cfg = _vision_load()
    with _vision_lock:
        s = _vision_obj[0]
    return jsonify({"ok": True, "vision": cfg,
                    "defaults": {"prompt": VISION_DEFAULT_PROMPT,
                                 "name": VISION_DEFAULT_NAME},
                    "running": bool(s is not None and s.alive),
                    "models": available_models().get("models", []),
                    "default_model": available_models().get("default")})


@harness_bp.route("/vision", methods=["POST"])
def harness_set_vision():
    """写识图会话配置。body: {enabled, model, prompt, name}。
    改了配置就让旧进程失效（下次 ensure 用新配置重建），
    避免新旧提示词/模型混用。"""
    data = request.get_json(force=True, silent=True) or {}
    old = _vision_load()
    cfg = {
        "enabled": bool(data.get("enabled", False)),
        "model": str(data.get("model") or "").strip(),
        "prompt": str(data.get("prompt") or "").strip() or VISION_DEFAULT_PROMPT,
        "name": str(data.get("name") or "").strip() or VISION_DEFAULT_NAME,
    }
    ok, err = _vision_save(cfg)
    if not ok:
        return jsonify({"ok": False, "err": err or "写入失败"}), 500
    # 配置有实质变化 → 停掉旧进程（下次 ensure 用新配置重建）
    if any(old.get(k) != cfg[k] for k in ("enabled", "model", "prompt", "name")):
        stop_vision_session()
    return jsonify({"ok": True, "vision": cfg})


@harness_bp.route("/vision/start", methods=["POST"])
def harness_start_vision():
    """手动拉起识图会话（工具启动时也会自动拉起；这是给用户手动重试用）。"""
    if not _vision_load()["enabled"]:
        return jsonify({"ok": False, "err": "识图会话未启用"}), 400
    s = ensure_vision_session()
    if s is None:
        return jsonify({"ok": False, "err": "启动失败（检查 claude 可用性与模型名）"}), 500
    return jsonify({"ok": True, "sid": s.sid, "name": s.name, "model": s.model})


@harness_bp.route("/vision/stop", methods=["POST"])
def harness_stop_vision():
    stop_vision_session()
    return jsonify({"ok": True})


@harness_bp.route("/skills")
def harness_skills():
    """技能列表（复用 claude_sessions 发现层，harness 上下文 cwd）。"""
    from .claude_sessions import list_skills
    cwd = request.args.get("cwd") or None
    return jsonify({"ok": True, "skills": list_skills(cwd)})


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
