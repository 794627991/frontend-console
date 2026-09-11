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
import os, json, base64, subprocess, threading, time, uuid
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
# 会话
# ---------------------------------------------------------------------------
class HarnessSession:
    """一个 stream-json harness 会话（kind='harness'）。

    元数据（sid/title/model/cwd/session_id）持久化；进程是易耗品——
    闲置被回收、切回自动复活（--resume 续上下文）。port_id 稳定 =
    harness:<sid8>，前端 tab 与后端会话一一对应。
    """

    kind = "harness"

    def __init__(self, sid, cwd=None, model=None, session_id=None, title=""):
        self.sid = sid
        self.port_id = "harness:" + sid[:8]
        self.cwd = cwd or os.path.expanduser("~")
        self.model = model or None
        self.session_id = session_id or None    # claude 侧真实会话 id（复活用）
        self.title = title or ""
        self.hidden = False     # 识图后台会话：不进会话列表（不 sync_meta）
        self.created = int(time.time() * 1000)
        self.last_active = self.created
        # ---- 运行时（进程相关，不持久化）----
        self._proc = None
        self.alive = False
        self.busy = False
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
        # 用户自定义提示词：start() 每次都注入（新会话/复活/闲置回收重建同路径）
        # v2.8：多条目体系——启用的 global 条目 + cwd 匹配的 project 条目拼接
        sys_prompt = _collect_system_prompt(self.cwd)
        if sys_prompt:
            argv += ["--append-system-prompt", sys_prompt]
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
        """只杀进程保元数据与事件缓冲（闲置回收/复活前清理用）。"""
        self.alive = False
        self.busy = False
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

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
                           session_id=m.get("session_id"), title=m.get("title", ""))
        s.created = m.get("created") or s.created
        s.last_active = m.get("last_active") or s.last_active
        _sessions[sid] = s
        return s


def _gc_loop():
    """闲置回收：活进程闲置超阈 kill（元数据/缓冲保留）。60s 一轮，daemon。"""
    while True:
        time.sleep(60)
        try:
            now = int(time.time() * 1000)
            with _sessions_lock:
                objs = list(_sessions.values())
            for s in objs:
                if s.alive and not s.busy and (now - s.last_active) > _IDLE_KILL_S * 1000:
                    s.kill_proc()
        except Exception:
            pass


def _ensure_gc():
    global _gc_started
    if not _gc_started:
        _gc_started = True
        threading.Thread(target=_gc_loop, daemon=True).start()


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
                    texts, tools = [], []
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and b.get("text"):
                            texts.append(b["text"])
                        elif b.get("type") == "tool_use":
                            tools.append({"id": b.get("id", ""), "name": b.get("name", ""),
                                          "summary": _tool_summary(b.get("name", ""), b.get("input")),
                                          "input": b.get("input") or {}})
                    if texts:
                        lines.append({"role": "assistant", "text": "\n".join(texts)[:8000]})
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
