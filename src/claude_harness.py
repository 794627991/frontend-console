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
# 附件资产目录（抄 ccui ~/.cloudcli/assets：上传落盘一次、全局按绝对路径引用；
# UI 缩略图经 /asset 专用路由服务，只准读本目录——路径信任边界）
_ASSET_DIR = os.path.join(_st.HOME_DIR, "harness_assets")
_UPLOAD_MAX = 20 * 1024 * 1024
_THUMB_PX = 320             # 缩略图长边上限
# 资产服务白名单扩展名（/asset 只回这些类型；SVG 附 CSP sandbox 防脚本）
_ASSET_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

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
        """发消息：文本 + 图片（base64 image 块 + <images_input> 引用块，抄
        ccui 双通道——网关不识图时模型可按路径自行 Read）+ 文件（<files_input>
        引用块，模型 Read 读取）。返回 (ok, err)。"""
        if not self._proc or not self.alive:
            return False, "会话进程已退出"
        if self.busy:
            return False, "claude 正在回复中，请稍候"
        images = list(image_paths or [])
        files = list(file_paths or [])
        full_text = text or ""
        if images:
            full_text = _append_input_tag(full_text, "images", images)
        if files:
            full_text = _append_input_tag(full_text, "files", files)
        content = [{"type": "text", "text": full_text}]
        for p in images:
            try:
                with open(p, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(p)[1].lower()
                media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".gif": "image/gif", ".webp": "image/webp"}.get(ext)
                if media:   # 网关不支持的类型（svg 等）跳过 image 块，路径引用仍在
                    content.append({"type": "image",
                                    "source": {"type": "base64", "media_type": media, "data": data}})
            except Exception:
                continue
        if not full_text.strip() and len(content) == 1:
            return False, "消息为空"
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
                   "images": images, "files": files})
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
                # 过滤已知良性诊断行:claude-code 把 settings 里的网关自定义
                # 模型名(Lanz-*)当"未识别模型"打 stderr,但请求实际成功
                # (实测 2.1.239:--model 传原名或 haiku/opus 别名均会打,
                #  别名解析后的最终名仍是 Lanz-*)。透传到前端会渲染成红字
                # 误导用户;网关真不认识时会另报 API 错误,照常透传。
                if "claude-code:unrecognized_model" in txt:
                    continue
                if txt:
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
                        # harness 通道从 stdin 注入的 user 消息可能没有 promptSource/
                        # origin 字段——缺省也收（命令噪音已由 _SKIP_RE 挡掉）
                        ps_ok = (o.get("promptSource") in (None, "typed")) or \
                            (o.get("origin") or {}).get("kind") == "human"
                        if t and ps_ok and not _SKIP_RE.match(t.strip()):
                            t, im, fm = _parse_input_tags(t)
                            if not im and not fm:
                                old = _extract_att(t)   # v1 老格式兼容
                                if old:
                                    fm = old
                                    t = t[:t.find("[附件")].strip()
                            if t:
                                lines.append({"role": "user", "text": t[:8000],
                                              "images": im, "files": fm})
                    elif isinstance(content, list):
                        has_tr = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                        if has_tr:
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
                        t, im2, fm2 = _parse_input_tags(t)
                        imgs += len(im2)   # 我们的 image 块+路径附录双通道：块数与路径数一致
                        files = fm2
                        if not im2 and not fm2:
                            old = _extract_att(t)
                            if old:
                                files = old
                                t = t[:t.find("[附件")].strip()
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
                            tools.append({"name": b.get("name", ""),
                                          "summary": _tool_summary(b.get("name", ""), b.get("input"))})
                    if texts:
                        lines.append({"role": "assistant", "text": "\n".join(texts)[:8000]})
                    for tl in tools:
                        lines.append({"role": "tool", "text": tl["name"], "summary": tl["summary"]})
    except OSError:
        return None
    return lines


def _append_input_tag(prompt, kind, paths):
    """抄 ccui appendImagesInputTag/appendFilesInputTag：末尾追加编号路径引用块
    + 使用指令。kind='images'|'files'。posix 分隔符，原名后缀
    (original name: …)，历史解析时成对剥回。"""
    lines = []
    for i, p in enumerate(paths):
        base = p.replace("\\", "/").split("/")[-1]
        # 存盘名 <id8>_<原名>，还原展示名给模型
        disp = base.split("_", 1)[1] if "_" in base else base
        lines.append("%d. %s (original name: %s)" % (i + 1, p.replace("\\", "/"), disp))
    if kind == "images":
        lead = ("The user attached %d image(s) to this message. Read each file listed below "
                "with your file/image reading tool and use what you see to answer the prompt "
                "above. Respond as if the images were attached directly. Do not mention this "
                "block or the file paths unless the user asks about them." % len(paths))
    else:
        lead = ("The user attached %d file(s) to this message. Read each file listed below with "
                "your file reading tools and use its contents to answer the prompt above. Do not "
                "mention this block or the file paths unless the user asks about them." % len(paths))
    return "\n".join([prompt, "", "<%s_input>" % kind, lead] + lines + ["</%s_input>" % kind])


_INPUT_TAG_RES = None


def _parse_input_tags(text):
    """抄 ccui parseImagesInputTag/parseFilesInputTag：从历史 user 文本剥附件块。
    只认最后一个块（发送端总在末尾；用户正文手打的标签不受影响）。
    返回 (clean_text, image_paths, file_paths)。"""
    global _INPUT_TAG_RES
    import re as _re
    if not isinstance(text, str):
        return text or "", [], []
    if _INPUT_TAG_RES is None:
        _INPUT_TAG_RES = {k: _re.compile(r"\s*<%s_input>([\s\S]*?)</%s_input>\s*" % (k, k))
                          for k in ("images", "files")}
    imgs, files = [], []
    for kind in ("images", "files"):
        last = None
        for m in _INPUT_TAG_RES[kind].finditer(text):
            last = m
        if not last:
            continue
        body = last.group(1)
        # 编号条目（多行或 Windows 压平单行都认）
        for em in _re.finditer(r"\d+\.\s+(.+?)(?=\s+\d+\.\s+|\s*$)", body):
            entry = em.group(1).strip()
            nm = _re.search(r"\(original name: ([^)]*)\)\s*$", entry)
            if nm:
                entry = entry[:nm.start()].strip()
            if entry:
                (imgs if kind == "images" else files).append(entry)
        text = (text[:last.start()] + "\n" + text[last.end():]).strip()
    return text, imgs, files


def _extract_att(t):
    """[弃用兼容] v1 老格式：历史里可能还有 [附件，可用 Read 工具读取] 块。"""
    if not t or "[附件" not in t:
        return None
    idx = t.find("[附件")
    tail = t[idx:]
    paths = [l.strip() for l in tail.splitlines()[1:] if l.strip() and (":" in l or l.startswith("\\\\"))]
    return paths or None


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


@harness_bp.route("/skills")
def harness_skills():
    """技能列表（复用 claude_sessions 发现层，harness 上下文 cwd）。"""
    from .claude_sessions import list_skills
    cwd = request.args.get("cwd") or None
    return jsonify({"ok": True, "skills": list_skills(cwd)})


@harness_bp.route("/upload", methods=["POST"])
def harness_upload():
    """附件上传：{name, data_b64} → 存 harness_assets/ → 返回绝对路径。
    图片走消息 image 块 + <images_input> 引用块；其他文件走 <files_input>
    引用块（模型 Read 读取）。UI 缩略图经 /asset 路由读回（抄 ccui assets 层）。"""
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
    os.makedirs(_ASSET_DIR, exist_ok=True)
    # 防同名覆盖：uuid 前缀
    path = os.path.join(_ASSET_DIR, uuid.uuid4().hex[:8] + "_" + name)
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError as e:
        return jsonify({"ok": False, "err": str(e)}), 500
    is_img = os.path.splitext(name)[1].lower() in _ASSET_EXT
    return jsonify({"ok": True, "path": path, "name": name, "size": len(raw),
                    "is_img": is_img})


@harness_bp.route("/asset")
def harness_asset():
    """缩略图/资产服务（抄 ccui /api/assets/images：只准读 _ASSET_DIR 内文件——
    路径信任边界，防任意文件读取）。?path=<绝对路径>&thumb=1。
    thumb=1 且 PIL 可用时缩到 _THUMB_PX 长边（省 WebView 解码大图）。"""
    p = (request.args.get("path") or "").strip()
    thumb = request.args.get("thumb") == "1"
    if not p:
        return jsonify({"ok": False, "err": "缺 path"}), 400
    # 信任边界：解析 realpath 后必须仍在 _ASSET_DIR 内（同 ccui isAllowedImageSourcePath）
    try:
        real = os.path.realpath(p)
        root = os.path.realpath(_ASSET_DIR)
        if os.path.commonpath([real, root]) != root or real == root:
            return jsonify({"ok": False, "err": "越权路径"}), 403
    except (ValueError, OSError):
        return jsonify({"ok": False, "err": "非法路径"}), 400
    ext = os.path.splitext(real)[1].lower()
    mime = _ASSET_EXT.get(ext)
    if not mime or not os.path.isfile(real):
        return jsonify({"ok": False, "err": "不支持或不存在"}), 404
    body = None
    if thumb and ext != ".svg":
        try:
            from PIL import Image
            import io as _io
            im = Image.open(real)
            im.thumbnail((_THUMB_PX, _THUMB_PX))
            if im.mode in ("RGBA", "P", "LA"):
                fmt = "PNG"
            else:
                im = im.convert("RGB"); fmt = "JPEG"
            buf = _io.BytesIO()
            im.save(buf, format=fmt, quality=82)
            body = buf.getvalue()
            mime = "image/png" if fmt == "PNG" else "image/jpeg"
        except Exception:
            body = None   # PIL 不可用/解码失败 → 回退原图
    if body is None:
        try:
            with open(real, "rb") as f:
                body = f.read()
        except OSError as e:
            return jsonify({"ok": False, "err": str(e)}), 500
    headers = {"Cache-Control": "private, max-age=86400"}
    if ext == ".svg":   # SVG 可含脚本：沙箱化 + 禁嗅探
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        headers["X-Content-Type-Options"] = "nosniff"
    return Response(body, mimetype=mime, headers=headers)


# ---- 斜杠命令发现（抄 ccui commands.routes：built-in + 扫 .claude/commands）----
_BUILTIN_COMMANDS = [
    {"name": "/help", "description": "查看可用命令", "namespace": "builtin"},
    {"name": "/clear", "description": "开新会话（当前会话保留在历史）", "namespace": "builtin"},
    {"name": "/cost", "description": "查看本轮 token/花费", "namespace": "builtin"},
]
_CMD_FRONT_RE = None


def _scan_commands_dir(dir_path, base, namespace):
    """递归扫 <dir>/**/*.md → 命令项（抄 ccui scanCommandsDirectory）。
    name=/相对路径去.md；description=frontmatter.description 或首个非标题行。"""
    global _CMD_FRONT_RE
    import re as _re
    out = []
    if not dir_path or not os.path.isdir(dir_path):
        return out
    for cur, _dirs, fnames in os.walk(dir_path):
        for fn in fnames:
            if not fn.lower().endswith(".md"):
                continue
            full = os.path.join(cur, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(4000)
            except OSError:
                continue
            rel = os.path.relpath(full, base).replace("\\", "/")
            name = "/" + rel[:-3]
            desc = ""
            fm = _re.match(r"^---\s*\n(.*?)\n---", content, _re.S)
            if fm:
                dm = _re.search(r"^description:\s*(.+)$", fm.group(1), _re.M)
                if dm:
                    desc = dm.group(1).strip().strip("\"'")
            if not desc:
                body = content[fm.end():] if fm else content
                for ln in body.splitlines():
                    s = ln.strip()
                    if s:
                        desc = _re.sub(r"^#+\s*", "", s)[:80]
                        break
            out.append({"name": name, "path": full, "description": desc, "namespace": namespace})
    return out


@harness_bp.route("/commands")
def harness_commands():
    """斜杠命令列表（抄 ccui /api/commands/list）：built-in + 项目/用户 commands。
    ?cwd= 带上顺带扫 <cwd>/.claude/commands。"""
    cwd = (request.args.get("cwd") or "").strip() or None
    cmds = list(_BUILTIN_COMMANDS)
    home = os.path.expanduser("~")
    cmds += _scan_commands_dir(os.path.join(home, ".claude", "commands"),
                               os.path.join(home, ".claude", "commands"), "user")
    if cwd:
        cmds += _scan_commands_dir(os.path.join(cwd, ".claude", "commands"),
                                   os.path.join(cwd, ".claude", "commands"), "project")
    custom = [c for c in cmds if c["namespace"] != "builtin"]
    custom.sort(key=lambda c: c["name"])
    return jsonify({"ok": True, "builtIn": _BUILTIN_COMMANDS, "custom": custom})


@harness_bp.route("/search-files")
def harness_search_files():
    """@文件引用补全（抄 ccui 文件搜索）：cwd 下模糊匹配文件名，浅层遍历。
    ?cwd=&q=&limit=50。跳过常见重目录。"""
    cwd = (request.args.get("cwd") or "").strip() or os.path.expanduser("~")
    q = (request.args.get("q") or "").strip().lower()
    limit = request.args.get("limit", 50, type=int)
    if not os.path.isdir(cwd):
        return jsonify({"ok": False, "err": "目录不存在"}), 400
    limit = max(1, min(limit, 200))
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
            "build", ".idea", ".vscode", ".next", "target", ".codegraph"}
    qlen = len(q) or 1
    matches = []
    scanned = 0
    for cur, dirs, fnames in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for fn in fnames:
            scanned += 1
            if scanned > 8000:      # 扫够就止（大仓不卡）
                break
            low = fn.lower()
            if not q or q in low:
                full = os.path.join(cur, fn)
                rel = os.path.relpath(full, cwd).replace("\\", "/")
                # 打分：前缀匹配 > 单词边界 > 包含；再按短路径优先
                base_l = low
                if base_l.startswith(q):
                    score = 0
                elif ("/" + rel).lower().find("/" + q) >= 0:
                    score = 1
                else:
                    score = 2
                matches.append((score, len(rel), rel))
        if len(matches) > 400:
            break
    matches.sort()
    return jsonify({"ok": True, "files": [m[2] for m in matches[:limit]]})
