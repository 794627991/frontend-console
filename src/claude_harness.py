# -*- coding: utf-8 -*-
"""Claude harness 界面化会话（第 4 期）：spawn claude CLI 的 stream-json 长驻会话。

与 claude_conn.py（ConPTY 跑 TUI，xterm 保真）平行的另一条通道：
  claude -p --input-format stream-json --output-format stream-json --verbose
进程常驻，stdin 写 NDJSON user 消息即连续多轮；stdout 逐行 NDJSON 事件
（system/assistant/user/result），后端原样透传给前端 SSE，渲染全在前端
（分层照 sugyan/claude-code-webui：后端薄透传、前端厚渲染）。

铁律约束：
- 不动 claude_conn/claude_sessions/claude_setup/claude_default（铁律4 零回归）
- 不落盘日志（Claude 自写 ~/.claude/projects 转写，与 claude_conn 同策略）
- 事件缓存有上限（_EVENTS_MAX），翻页加载防内存膨胀（铁律1）
- UI 全部由前端负责，本模块不弹任何东西
"""
import os, json, subprocess, threading, time
from queue import Queue, Empty

from .claude_conn import ClaudeNotFoundError, _resolve_claude_exe, _humanize_claude_error

_EVENTS_MAX = 4000          # 每会话事件缓存上限（前端重连回放用）
_QUEUE_MAX = 2000           # SSE 客户端队列上限（同 base_conn._push_raw 策略）


class ClaudeHarnessSession:
    """一个 stream-json harness 会话。kind='harness'。

    生命周期：__init__ 后端不自动 start，由路由层 start() 后入表；
    结束：close()（杀进程 + 停线程），不重连（会话退出是语义事件）。
    """

    kind = "harness"

    def __init__(self, cwd=None, resume=None, model=None, port_id="harness:1"):
        self.port_id = port_id
        self.cwd = cwd or os.path.expanduser("~")
        self.resume = resume or None
        self.model = model or None
        self._proc = None
        self.alive = False
        self.session_id = None      # system/init 事件里拿到的真实会话 id
        self.last_result = None     # 最近一次 result 事件（cost/turns）
        self.busy = False            # 正在等 claude 回复（result 事件后回 False）
        # 事件回放缓存：前端断线重连 / 历史回看按 seq 增量拉
        self.events = []
        self.events_lock = threading.Lock()
        self._seq = 0
        # SSE 客户端队列
        self.clients = []
        self.clients_lock = threading.Lock()
        # 兼容 api_status/refreshSidebar 读的字段
        base = os.path.basename(os.path.normpath(self.cwd)) or self.cwd
        self.port = f"Claude Harness({base})"
        self.baud = None

    # ---- 启动/关闭 ----
    def start(self):
        exe, is_shim = _resolve_claude_exe()
        if is_shim:
            # .CMD 不能直接 CreateProcess：经 cmd.exe /c 中转（同 claude_conn 模式）
            argv = ["cmd.exe", "/c", exe]
        else:
            argv = [exe]
        argv += ["-p",
                 "--input-format", "stream-json",
                 "--output-format", "stream-json",
                 "--verbose",
                 "--permission-mode", "auto"]
        if self.resume:
            argv += ["--resume", self.resume]
        if self.model:
            argv += ["--model", self.model]
        env = dict(os.environ)
        env.setdefault("TERM", "dumb")   # 无 TUI，不注入颜色；claude 对 headless 自动切
        # CREATE_NO_WINDOW：工具是 GUI 进程，不闪黑窗（同 claude_conn wmic 模式）
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            argv, cwd=self.cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
        self.alive = True
        self.busy = False
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        self._stderr_drain = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_drain.start()

    def close(self):
        self.alive = False
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
        try:
            if self.reader and self.reader.is_alive():
                self.reader.join(timeout=1.0)
        except Exception:
            pass

    # ---- 输入 ----
    def send_message(self, text):
        """往 stdin 写一条 user 消息（NDJSON）。busy 时拒绝排队以外的并发。"""
        if not self._proc or not self.alive:
            return False, "会话进程已退出"
        if self.busy:
            return False, "claude 正在回复中，请稍候"
        try:
            payload = {"type": "user",
                       "message": {"role": "user", "content": text}}
            self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except Exception as e:
            return False, f"发送失败：{e}"
        self.busy = True
        # 本地回显（--replay-user-messages 未开：自己记自己发的内容）
        self.emit({"kind": "user_echo", "text": text})
        return True, None

    def interrupt(self):
        """中断当前回合。无 --permission-prompt-tool 通道时退化为杀进程重启会话。
        v1 先不做（前端按钮预留，返回提示）。"""
        return False, "暂不支持中断当前回复（后续版本提供）"

    # ---- 事件层 ----
    def _reader_loop(self):
        """逐行读 stdout NDJSON → 原样入缓存 + 推 SSE。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        dec_buf = ""
        try:
            for line_b in proc.stdout:
                if not self.alive:
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    # 非 JSON 行（claude 偶发 stderr 混入/日志）：转成 raw 事件保底
                    self.emit({"kind": "raw", "text": line})
                    continue
                typ = o.get("type")
                # 会话 id：system/init 的 session_id 字段
                if typ == "system" and o.get("session_id") and not self.session_id:
                    self.session_id = o.get("session_id")
                if typ == "result":
                    self.busy = False
                    self.last_result = o
                # parent_tool_use_id 非空 = 子代理消息，默认也透传（前端可按需折叠）
                self.emit({"kind": "event", "data": o})
        except Exception:
            pass
        finally:
            self.alive = False
            self.busy = False
            self.emit({"kind": "exit", "text": "会话进程已退出"})

    def _drain_stderr(self):
        """stderr 单独排空防管道堵塞（claude 升级提示等杂音走这里）。"""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                if not self.alive:
                    break
                txt = line.decode("utf-8", errors="replace").strip()
                if txt:
                    self.emit({"kind": "raw", "text": txt})
        except Exception:
            pass

    def emit(self, item):
        """事件入缓存（带 seq）+ 推给所有 SSE 客户端。"""
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
                    # 队列满：丢最旧腾位（同 base_conn._push_raw 策略）
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

    # ---- SSE 客户端管理（同 BaseConnection 接口语义）----
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
        """seq > after_seq 的事件（前端重连增量回放）。"""
        with self.events_lock:
            res = [it for it in self.events if it["seq"] > after_seq]
        return res[-limit:] if limit else res


# ============================================================
# Blueprint 路由（/api/harness/*）
# ============================================================
from flask import Blueprint, request, jsonify, Response

harness_bp = Blueprint("harness", __name__, url_prefix="/api/harness")

# 会话表：port_id -> ClaudeHarnessSession（独立于 server._ports——不动现有连接体系）
_harness = {}
_harness_lock = threading.Lock()


def _alloc_port_id(resume=None):
    """分配 port_id：resume 会话带 id 前缀去重；新会话自增（同 claude 分支模式）。"""
    if resume:
        return f"harness:r-{resume[:8]}"
    n = 1
    while f"harness:{n}" in _harness:
        n += 1
    return f"harness:{n}"


@harness_bp.route("/connect", methods=["POST"])
def harness_connect():
    """启动 harness 会话。body: {cwd, resume?, model?}。"""
    from .claude_conn import _trust_workspace
    data = request.get_json(force=True, silent=True) or {}
    cwd = (data.get("cwd") or "").strip() or os.path.expanduser("~")
    resume = (data.get("resume") or "").strip() or None
    model = (data.get("model") or "").strip() or None
    if not os.path.isdir(cwd):
        return jsonify({"ok": False, "err": f"目录不存在：{cwd}"}), 400
    with _harness_lock:
        port_id = _alloc_port_id(resume)
        if port_id in _harness:
            return jsonify({"ok": False, "err": "该会话已在工具内打开，请切换到对应标签页"}), 400
        s = None
        try:
            _trust_workspace(cwd)
            s = ClaudeHarnessSession(cwd=cwd, resume=resume, model=model, port_id=port_id)
            s.start()
            _harness[port_id] = s
        except Exception as e:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            return jsonify({"ok": False, "err": _humanize_claude_error(e)}), 500
    return jsonify({"ok": True, "port_id": port_id, "kind": "harness",
                    "cwd": cwd, "resume": resume,
                    "msg": f"harness 会话已启动（{'恢复 ' + resume[:8] if resume else '新会话'}）"})


@harness_bp.route("/send", methods=["POST"])
def harness_send():
    """发消息。body: {port_id, text}。"""
    data = request.get_json(force=True, silent=True) or {}
    port_id = data.get("port_id") or ""
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "err": "消息不能为空"}), 400
    with _harness_lock:
        s = _harness.get(port_id)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    if not s.alive:
        return jsonify({"ok": False, "err": "会话进程已退出，请重新打开"}), 400
    ok, err = s.send_message(text)
    if not ok:
        return jsonify({"ok": False, "err": err}), 400
    return jsonify({"ok": True})


@harness_bp.route("/stream")
def harness_stream():
    """SSE 事件流。?port_id=。连接建立时先回放 after_seq 之后的事件（断线重连不丢）。"""
    port_id = request.args.get("port_id") or ""
    after_seq = request.args.get("after_seq", 0, type=int)
    with _harness_lock:
        s = _harness.get(port_id)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    q = s.add_client()
    def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            # 先回放缓存（重连增量）
            for it in s.get_events_after(after_seq):
                yield f"data: {json.dumps(it, ensure_ascii=False)}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Empty:
                    yield ": ping\n\n"
        finally:
            s.remove_client(q)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@harness_bp.route("/events")
def harness_events():
    """事件缓存快照（一次性拉取，前端首次渲染/刷新用）。?port_id=&after_seq=&limit="""
    port_id = request.args.get("port_id") or ""
    after_seq = request.args.get("after_seq", 0, type=int)
    limit = request.args.get("limit", 500, type=int)
    with _harness_lock:
        s = _harness.get(port_id)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    return jsonify({"ok": True, "events": s.get_events_after(after_seq, limit),
                    "seq": s._seq, "alive": s.alive, "busy": s.busy,
                    "session_id": s.session_id})


@harness_bp.route("/disconnect", methods=["POST"])
def harness_disconnect():
    """关闭会话。body: {port_id}。"""
    data = request.get_json(force=True, silent=True) or {}
    port_id = data.get("port_id") or ""
    with _harness_lock:
        s = _harness.pop(port_id, None)
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    s.close()
    return jsonify({"ok": True})


@harness_bp.route("/list")
def harness_list():
    """本工具打开的 harness 会话列表（设置页/面板展示用）。"""
    with _harness_lock:
        items = [{"port_id": pid, "cwd": s.cwd, "resume": s.resume,
                  "alive": s.alive, "busy": s.busy, "session_id": s.session_id}
                 for pid, s in _harness.items()]
    return jsonify({"ok": True, "sessions": items})
