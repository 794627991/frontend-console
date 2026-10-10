# -*- coding: utf-8 -*-
"""harness.vision —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import re
import subprocess
import threading
import logging
log = logging.getLogger(__name__)
from .. import app_state as _st
from ..claude_conn import _resolve_claude_exe


# ---- from claude_harness.py:52 (_VISION_KEY) ----


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





# ---- from claude_harness.py:91 (_vision_default_cfg) ----


def _vision_default_cfg():
    # v2.28.1：mm_mcp 名单退役——分类只剩两态（真多模态 inline / 其余全部
    # MCP），非 inline 即 MCP，无需名单。旧 config 里的 mm_mcp 键自然闲置。
    # v2.28.2：model_map 端点模型映射 + mcp_prompt——识图配置（MCP 后端）
    # 多方案适配：lanz 端点配 Lanz 系、bigmodel 端点配 glm 系。
    return {"enabled": False, "model": "", "prompt": "", "name": "",
            "mm_extra": [], "model_map": {}, "mcp_prompt": "",
            "base_url": "", "api_key": ""}

# ---- from claude_harness.py:101 (_vision_load) ----


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
            mm = raw.get("mm_extra")
            if isinstance(mm, list):
                cfg["mm_extra"] = [str(x).strip() for x in mm if str(x).strip()]
            # v3.5.31：mm_user 人工判定表（{模型名: bool}）——判定链最高优先级
            mu = raw.get("mm_user")
            if isinstance(mu, dict):
                cfg["mm_user"] = {str(k).strip().lower(): bool(v)
                                  for k, v in mu.items() if str(k).strip()}
            mp = str(raw.get("mcp_prompt") or "").strip()
            if mp:
                cfg["mcp_prompt"] = mp
            # v3.5.86：识图专用端点/密钥（内网/自建网关）——留空走
            # settings.json 同源→智谱直连兜底（vision_mcp._endpoints 链）
            cfg["base_url"] = str(raw.get("base_url") or "").strip()
            cfg["api_key"] = str(raw.get("api_key") or "").strip()
    except Exception:
        pass
    return cfg

# ---- from claude_harness.py:139 (_MM_RE) ----


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

# ---- from claude_harness.py:157 (_mm_probe_key) ----


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

# ---- from claude_harness.py:175 (_model_is_multimodal) ----


def _model_is_multimodal(name):
    name = (name or "").strip()
    if not name:
        return False
    lname = name.lower()
    cfg = _vision_load()
    # v3.5.31（用户定调「防止抽风，用户判断永远优先于缓存」）：mm_user 人工
    # 判定表最高优先级——探测缓存/名字正则/名单全部让位。探测是 headless
    # 一次性进程，环境抖动会把多模态模型误判 false（glm-5.3 实锤）；用户
    # 眼见为实的结论不该被机器缓存覆盖。表结构 {模型名小写: bool}，面板写入
    for item, val in (cfg.get("mm_user") or {}).items():
        it = (item or "").strip().lower()
        if it and (lname == it or lname.startswith(it + "[")):
            return bool(val)
    # v3.5.91（用户实锤内网机 Lanz-Medium-V 显示 MCP）：**用户显式配置全面
    # 提到探测缓存之前**——识图配置的「识图模型」与「多模态名单」都是用户
    # 亲手选/填的，延续 v3.5.31「用户判断永远优先于缓存」的定调。旧顺序
    # （缓存→正则→名单）里，一次环境坏掉的探测（如旧版端点落智谱连接拒绝）
    # 会缓存 False 且永久压制名单——名单填了 Lanz-Medium-V 照样显示 MCP
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
    # 用户显式配置之后才是运行时探测缓存（真实链路上验证过能否读图）与
    # 名字正则——名字启发式的正反两面都不该盖过用户配置
    cached = _mm_probed_load().get(_mm_probe_key(name))
    if cached is not None:
        return bool(cached)
    if _MM_RE.search(lname):
        return True
    return False

# ---- from claude_harness.py:202 (_vision_save) ----


def _vision_save(cfg):
    """原子写识图配置。v2.25 改 merge 语义：cfg 里的键覆盖 _VISION_KEY 同名键，
    其余键（如 mm_probed 探测缓存）原样保留——旧实现整键替换，调用方没带
    的字段会被静默抹掉。v3.4.54 起走 app_state.cfg_commit（统一锁+原子事务）。"""
    def _mut(d):
        cur = d.get(_VISION_KEY)
        if not isinstance(cur, dict):
            cur = {}
        cur.update(cfg)
        d[_VISION_KEY] = cur
    return _st.cfg_commit(_mut)

# ---- from claude_harness.py:228 (_MM_PROBE_LOCK) ----


# ---------------------------------------------------------------------------
# 多模态运行时探测（v2.25）
#   名字启发式靠猜、名单靠用户记——都不如直接问模型本身：起一次性 headless
#   claude，发一张已知颜色的测试图让它 Read，答对颜色即为多模态。结果按
#   模型名缓存在识图配置的 mm_probed（config.json，不进 ~/.claude/settings），
#   探测一次终身受用；通过者自动并入 mm_extra 名单。
# ---------------------------------------------------------------------------
_MM_PROBE_LOCK = threading.Lock()

# ---- from claude_harness.py:238 (_mm_probe_png_bytes) ----


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

# ---- from claude_harness.py:251 (_mm_probe_model) ----


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

# ---- from claude_harness.py:296 (_mm_probed_load) ----


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

# ---- from claude_harness.py:356 (_model_vision_mode) ----


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

# ---- from claude_harness.py:369 (_VISION_TOOLS) ----


# v2.28.5：识图工具名双通道——网关内置名（主通道，服务端执行）+ 本地名
# （兜底通道，harness_vision_mcp.py 注册，server 名 vision）。同名会被网关
# 遮蔽（实测 log 零记录、零 tool_use），本地版必须独立名字才可作为真兜底。
# 实时事件流与历史回放解析按两个名字识别识图调用。
_VISION_TOOLS = ("mcp__4_5v_mcp__analyze_image", "mcp__vision__analyze_image")

# ---- from claude_harness.py:376 (_iso_dur_sec) ----


def _iso_dur_sec(t0, t1):
    """两个 ISO 时间串的差（秒，1 位小数）。解析失败返回 None。"""
    try:
        from datetime import datetime
        a = datetime.fromisoformat(str(t0).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(t1).replace("Z", "+00:00"))
        return round((b - a).total_seconds(), 1)
    except Exception:
        return None

# ---- from claude_harness.py:477 (_peer_reg_path) ----
    # v2.28：转交识图会话分支退役——_model_vision_mode 已无 None 态
    # （全部并入 mcp），本地 analyze_image 是唯一识图通道。防御性返回空串。


def _peer_reg_path():
    return os.path.join(os.path.expanduser("~"), ".claude", "sessions")

# ---- from claude_harness.py:483 (_cleanup_peer_reg) ----


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

# ---- from claude_harness.py:533 (_pid_alive) ----


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


