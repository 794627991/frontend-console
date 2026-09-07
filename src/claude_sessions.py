# -*- coding: utf-8 -*-
"""Claude Code 会话/技能发现（设计见 docs/CLAUDE_CODE_INTEGRATION.md §3.1）。

数据源是 ~/.claude/projects/<项目目录名>/<session_id>.jsonl 转写文件：
  - cwd 从首条带 cwd 字段的行还原（项目目录名里非 ASCII 全塌成 -，不可靠）
  - 标题/摘要从首条真实用户消息取（排除 caveat/命令/attachment 行）
  - 头 64KB + 尾 128KB 两窗读取，不全文遍历；模块级缓存 mtime+size 双 key，
    5s 轮询未变化的会话成本≈0
大文件（几十 MB）安全：尾窗 seek(-tail, 2) 后按 \\n 对齐再解析。
"""
import os, re, json, time, glob

def _projects_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")

# 模块级缓存：文件路径 → (mtime, size, parsed_dict_or_None)
_sess_cache = {}
_CACHE_MAX = 200   # 缓存条目上限，防长期运行无限膨胀

# 摘要候选行里排除的内容前缀（caveat/斜杠命令回显/系统输出等非真实用户输入）
_SKIP_MSG_RE = re.compile(r"^<(local-command-caveat|local-command-stdout|command-name|command-message|command-args|bash-)")
# 摘要里的 ANSI 转义序列（终端染色的命令回显会带 \x1b[1m 等）
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# 块式 content 里只取文本块
_TEXT_TYPES = ("text",)


def _head_tail(path, head=64 * 1024, tail=128 * 1024):
    """返回 (头窗行列表, 尾窗行列表)。文件小于窗口时整体读。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head_bytes = f.read(head)
        tail_bytes = b""
        if size > head:
            f.seek(max(0, size - tail))
            tail_bytes = f.read()
    def lines(b):
        out = []
        for raw in b.split(b"\n"):
            raw = raw.strip()
            if raw:
                out.append(raw)
        return out
    h = lines(head_bytes)
    t = lines(tail_bytes) if tail_bytes else []
    return h, t


def _first_user_summary(head_lines):
    """从头窗行找首条【主体会话判定级】真实用户消息（typed + human origin），
    返回 (summary, timestamp, is_mainline)。is_mainline=False 表示该 jsonl
    是碎片（后台 sdk 转写 / queue 碎片 / compact 残壳），列表里不显示。

    主体会话判据（实测验证）：user 行 promptSource='typed' 且 origin.kind='human'。
    —— Claude Code 的「后台会话」（agent 后台 run）转写出来 promptSource='sdk'，
    /compact 与 queue-operation 碎片没有 typed 消息。用户看到的正是
    自己 typed 开的对话，与 CLI 自带后台总览（图示 agent 视图）口径一致。"""
    is_mainline = False
    for raw in head_lines:
        try:
            o = json.loads(raw)
        except Exception:
            continue   # 半行（写到一半）跳过
        if o.get("type") != "user":
            continue
        # 块式 content（新版本）取第一个 text 块；字符串 content（老版本）直接用
        msg = o.get("message") or {}
        c = msg.get("content")
        # tool_result（工具回显）不算用户输入
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        text = None
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            for blk in c:
                if isinstance(blk, dict) and blk.get("type") in _TEXT_TYPES and blk.get("text"):
                    text = blk["text"]
                    break
        if not text or _SKIP_MSG_RE.match(text.strip()):
            continue
        if o.get("promptSource") == "typed" and (o.get("origin") or {}).get("kind") == "human":
            is_mainline = True
            # 纯文本化：去 ANSI 转义 + 压缩空白
            text = re.sub(r"\s+", " ", _ANSI_RE.sub("", text)).strip()
            return (text[:80], o.get("timestamp"), True)
        if not is_mainline:
            # 记下第一条真实消息备作标题兜底（非 typed 会话也走到这）
            text_bk = re.sub(r"\s+", " ", _ANSI_RE.sub("", text)).strip()
            if not _first_user_summary._bk:
                _first_user_summary._bk = (text_bk[:80], o.get("timestamp"))
    return (_first_user_summary._bk[0], _first_user_summary._bk[1], is_mainline)
_first_user_summary._bk = (None, None)   # 单文件解析期临时槽（每次解析前重置）


def _title_of(head_lines, fallback_summary):
    """会话显示名：aiTitle/agentName 行优先（Claude 自起的名字，后台总览同款），
    无则用首条消息摘要。"""
    for raw in head_lines:
        try:
            o = json.loads(raw)
        except Exception:
            continue
        if o.get("type") in ("ai-title", "agent-name"):
            t = o.get("aiTitle") or o.get("agentName")
            if t:
                return re.sub(r"\s+", " ", t).strip()[:60]
    return fallback_summary or ""


def _cwd_of(head_lines, fallback_name):
    """cwd 还原：头窗里第一条带 cwd 字段的行；全无则解目录名（C--Users-x → C:\\Users\\x）。"""
    for raw in head_lines:
        try:
            o = json.loads(raw)
        except Exception:
            continue
        cwd = o.get("cwd")
        if cwd:
            return cwd
    # 目录名兜底：C--Users-gaoyi13 → C:\Users\gaoyi13（非 ASCII 信息已丢，尽力还原）
    m = re.match(r"^([A-Za-z])--(.+)$", fallback_name)
    if m:
        return m.group(1) + ":\\" + m.group(2).replace("-", "\\")
    return fallback_name


def _last_user_message(tail_lines):
    """从尾窗行找最后一条真实用户消息（typed/human 的纯文本），作卡片摘要。
    显示会话当前进展——首条消息（"你好"）挂在那没有信息量。尾窗最多 128KB，
    大会话也只覆盖近尾部；全被 tool_result/系统行占据时返回 None（前端回退首条）。"""
    for raw in reversed(tail_lines):
        try:
            o = json.loads(raw)
        except Exception:
            continue
        if o.get("type") != "user":
            continue
        # 后台 agent 转写里 sdk 消息也可能进尾窗——只认 typed+human（与主体判定同口径）
        if o.get("promptSource") != "typed" or (o.get("origin") or {}).get("kind") != "human":
            continue
        msg = o.get("message") or {}
        c = msg.get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        text = None
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            for blk in c:
                if isinstance(blk, dict) and blk.get("type") in _TEXT_TYPES and blk.get("text"):
                    text = blk["text"]
                    break
        if not text or _SKIP_MSG_RE.match(text.strip()):
            continue
        return re.sub(r"\s+", " ", _ANSI_RE.sub("", text)).strip()[:80]
    return None


def _parse_session(path, project_dir_name):
    """解析单个会话 jsonl → dict。碎片（无 typed 主体消息）返回 None 不进列表。"""
    try:
        h, t = _head_tail(path)
    except OSError:
        return None
    if not h:
        return None
    _first_user_summary._bk = (None, None)   # 备作标题兜底的槽位
    summary, first_ts, is_mainline = _first_user_summary(h)
    if not is_mainline:
        return None   # 后台 sdk 转写 / queue 碎片 / compact 残壳——用户没在这个文件里 typed 过
    title = _title_of(h, summary)
    cwd = _cwd_of(h, project_dir_name)
    # 消息数近似：尾窗里 type=user/assistant 的行数（尾窗最多 128KB，几 MB 会话也只数近尾部）
    approx_msgs = 0
    last_ts = None
    for raw in t:
        # 尾窗行用快速前缀探测，避免逐行 json.loads 开销
        if b'"type":"user"' in raw or b'"type":"assistant"' in raw:
            approx_msgs += 1
    # last_ts：尾窗倒数第一行的时间戳（jsonl 按时间追加）
    for raw in reversed(t):
        m = re.search(rb'"timestamp":"([^"]+)"', raw)
        if m:
            last_ts = m.group(1).decode("utf-8", "replace")
            break
    # 摘要：最后一条用户消息（反映会话当前进展——首条"你好"没有信息量）；
    # 尾窗没有 typed 消息时回退首条
    last_summary = _last_user_message(t)
    return {
        "session_id": os.path.splitext(os.path.basename(path))[0],
        "cwd": cwd,
        "project": project_dir_name,
        "title": title,          # aiTitle 优先（后台总览同款会话名），否则首条消息
        "summary": last_summary or summary or "（无文本消息）",
        "first_ts": first_ts or "",
        "last_ts": last_ts or first_ts or "",
        "approx_msgs": approx_msgs,
        "size": os.path.getsize(path),
        "mtime": os.path.getmtime(path),
    }


def list_sessions(limit=50):
    """列出全部会话，按 mtime 新→旧。active 判定：< 60s 视为活跃（外部进程正用）。"""
    pdir = _projects_dir()
    result = []
    now = time.time()
    for proj in glob.glob(os.path.join(pdir, "*", "*.jsonl")):
        name = os.path.basename(os.path.dirname(proj))
        try:
            st = os.stat(proj)
        except OSError:
            continue
        cache_key = proj
        cached = _sess_cache.get(cache_key)
        parsed = None
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            parsed = cached[2]
        if parsed is None:
            parsed = _parse_session(proj, name)
            # 缓存 None 也没意义（文件坏了每次都重试也无妨，但记个空 dict 防反复解析）
            _sess_cache[cache_key] = (st.st_mtime, st.st_size, parsed)
        if not parsed:
            continue
        # active：jsonl 15 分钟内有写入视为活跃。会话 idle（等输入/长任务思考）
        # 时不写文件——60s 窗口把正开着的会话误判成历史（识图会话等图、
        # 工具里打开的会话等输入都会掉下去）。15min 覆盖一轮正常交互+思考；
        # 真关掉的会话最迟 15min 后自然归历史。
        parsed["active"] = (now - st.st_mtime) < 15 * 60
        result.append(parsed)
    result.sort(key=lambda s: -s["mtime"])
    # 缓存收敛
    if len(_sess_cache) > _CACHE_MAX:
        for k in list(_sess_cache)[:len(_sess_cache) - _CACHE_MAX]:
            _sess_cache.pop(k, None)
    # 用户备注优先于 aiTitle：session_id → 备注名（存工具 config.json，不动 claude 的 jsonl——
    # claude 下次起标题会覆盖自己的 ai-title 行，但不会碰我们的备注）
    notes = _load_notes()
    for s in result[:limit]:
        note = notes.get(s["session_id"])
        if note:
            s["note"] = note
            s["title"] = note   # 显示优先级：备注 > aiTitle > 首条消息
    return result[:limit]


def _load_notes():
    """读会话备注表（存 ~/.serialconsole_pro/config.json 的 claude_notes 键）。"""
    try:
        from src.app_state import _load_config
        return dict(_load_config().get("claude_notes") or {})
    except Exception:
        return {}


def set_session_note(session_id, note):
    """写/清一条会话备注。note 空串删除该条。返回更新后的表。"""
    from src.app_state import _load_config, _save_config
    cfg = _load_config()
    notes = dict(cfg.get("claude_notes") or {})
    sid = (session_id or "").strip()
    if not sid:
        return notes
    note = (note or "").strip()
    if note:
        notes[sid] = note
    else:
        notes.pop(sid, None)
    cfg["claude_notes"] = notes
    _save_config(cfg)
    # 备注改了要让列表缓存失效（title 已合进 parsed 缓存）
    global _sess_cache
    _sess_cache.clear()
    return notes


# ---- 技能（第 2 期只读列出；第 3 期再做管理） ----
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)

def list_skills(cwd=None):
    """扫三来源的技能：user（~/.claude/skills）/ project（<cwd>/.claude/skills）/
    plugin（~/.claude/plugins/*/skills）。frontmatter 正则提 name/description。"""
    roots = []
    home = os.path.expanduser("~")
    roots.append(("user", os.path.join(home, ".claude", "skills")))
    if cwd and os.path.isdir(cwd):
        roots.append(("project", os.path.join(cwd, ".claude", "skills")))
    roots.append(("plugin", os.path.join(home, ".claude", "plugins")))
    out = []
    seen = set()
    for source, root in roots:
        if not os.path.isdir(root):
            continue
        if source == "plugin":
            # plugins/<插件>/skills/<技能>/SKILL.md
            for md in glob.glob(os.path.join(root, "*", "skills", "*", "SKILL.md")):
                _add_skill(md, "plugin", out, seen)
        else:
            for md in glob.glob(os.path.join(root, "*", "SKILL.md")):
                _add_skill(md, source, out, seen)
    out.sort(key=lambda s: (s["source"], s["name"]))
    return out

def _add_skill(md_path, source, out, seen):
    key = (source, os.path.basename(os.path.dirname(md_path)))
    if key in seen:
        return
    seen.add(key)
    name = os.path.basename(os.path.dirname(md_path))
    desc = ""
    try:
        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(8192)
        m = _FM_RE.match(head)
        if m:
            fm = m.group(1)
            nm = re.search(r"^name:\s*(.+)$", fm, re.M)
            dm = re.search(r"^description:\s*(.+)$", fm, re.M)
            if nm:
                name = nm.group(1).strip()
            if dm:
                desc = dm.group(1).strip()
    except OSError:
        pass
    out.append({"name": name, "desc": desc, "source": source})
