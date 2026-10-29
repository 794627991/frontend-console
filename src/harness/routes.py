# -*- coding: utf-8 -*-
"""harness.routes —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import base64
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from flask import Blueprint, Response, jsonify, request, send_file, send_from_directory
import logging
log = logging.getLogger(__name__)
from .. import app_state as _st
from ..claude_conn import _humanize_claude_error, _resolve_claude_exe
from .lifecycle import _ensure_gc, _get_or_create
from .roles import audit_gate_check
# v3.4.94：补漏 _PROMPTS_KEY——1165 行旧版提示词迁移用到但未导入
#（Cython 静态检查实锤→资源加密失败；运行时该路径 NameError 被 except
#  吞掉=v2.4 旧机的单条提示词一直迁移不上去）
from .consts import _PROMPTS_KEY, _PROMPTS_LEGACY_KEY, _SKILL_ZH_FILE, _UPLOAD_DIR, _UPLOAD_MAX, _sessions, _sessions_lock
from .meta import _meta, _meta_load, _meta_lock, _meta_save, _meta_tombstones
from .models import available_models
from .prompts import _prompt_matches_project, _prompts_load, _prompts_save
from .session import HarnessSession, _session_ctx_used
from .transcript import _subagent_rows_for, _subagent_transcript_candidates, transcript_for
from .vision import _MM_PROBE_LOCK, _VISION_KEY, _mm_probe_key, _mm_probe_model, _mm_probed_load, _model_is_multimodal, _vision_load, _vision_save


# ---- from claude_harness.py:2560 (harness_bp) ----


# ---------------------------------------------------------------------------
# Blueprint 路由（/api/harness/*）
# ---------------------------------------------------------------------------
harness_bp = Blueprint("harness", "src.claude_harness", url_prefix="/api/harness")  # v3.0: import_name 写死原值

# ---- from claude_harness.py:2566 (harness_connect) ----


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
                        "cwd": s.cwd, "model": s.model, "title": s.title,
                        "scheme": s.scheme or ""})
    # 新会话
    new_sid = uuid.uuid4().hex
    s = HarnessSession(new_sid, cwd=cwd, model=model,
                       permission=(data.get("permission") or "").strip() or None,
                       think=(data.get("think") or "").strip() or None)
    # v3.5.98：新会话打上当前 API 方案名（跨方案发消息拦截的档案依据）
    try:
        from src.claude_default import active_scheme_name
        s.scheme = active_scheme_name() or None
    except Exception:
        pass
    try:
        s.start()
    except Exception as e:
        return jsonify({"ok": False, "err": _humanize_claude_error(e)}), 500
    s.sync_meta()
    with _sessions_lock:
        _sessions[new_sid] = s
    return jsonify({"ok": True, "port_id": s.port_id, "sid": s.sid, "kind": "harness",
                    "cwd": s.cwd, "model": s.model, "title": s.title})

# ---- from claude_harness.py:2602 (harness_ask_reply) ----


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

# ---- from claude_harness.py:2617 (harness_ask_poll) ----


@harness_bp.route("/ask/poll", methods=["POST"])
def harness_ask_poll():
    """MCP 侧长轮询等作答。body: {sid, req_id}。

    v3.4.61：req_id 为空 = 前端快照分支——返回当前待答问题全量
    （req_id/title/questions/done/answer），供前端冷开恢复面板。MCP 侧
    恒传 req_id，既有响应字段不变（additive）。
    """
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    req_id = (data.get("req_id") or "").strip()
    if not req_id:
        found, snap = s.ask_snapshot()
        if not found:
            return jsonify({"ok": True, "found": False})
        return jsonify({"ok": True, "found": True, "req_id": snap["req_id"],
                        "title": snap["title"], "questions": snap["questions"],
                        "done": snap["done"], "answer": snap["answer"]})
    found, done, answer = s.ask_poll(req_id)
    return jsonify({"ok": True, "found": found, "done": done, "answer": answer})

# ---- from claude_harness.py:2628 (harness_ask_answer) ----


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

# ---- from claude_harness.py:2642 (harness_send) ----


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
    ok, err = s.send_message(text, images or None, files or None,
                             cmd=data.get("cmd") or None)
    if not ok:
        return jsonify({"ok": False, "err": err}), 400
    return jsonify({"ok": True})

# ---- from claude_harness.py:2661 (harness_interrupt) ----


@harness_bp.route("/interrupt", methods=["POST"])
def harness_interrupt():
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    ok, err = s.interrupt()
    return jsonify({"ok": ok, "err": err}) if not ok else jsonify({"ok": True})

# ---- from claude_harness.py:2671 (harness_kill) ----


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

# ---- from claude_harness.py:2684 (_jsonl_path_for) ----


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

# ---- from claude_harness.py:2699 (_rewind_jsonl) ----


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

# ---- from claude_harness.py:2720 (_rewind_jsonl_ts) ----


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

# ---- from claude_harness.py:2748 (_rewind_jsonl_anchor) ----


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

# ---- from claude_harness.py:2795 (_rewind_write) ----


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

# ---- from claude_harness.py:2808 (harness_rewind) ----


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
    # 进程必须先杀：截断时 CLI 仍在写同一 jsonl 会丢快照后的新行，且
    # Windows 下 CLI 恰持句柄时 os.replace 抛 PermissionError → 路由裸奔
    # 出 500 HTML（违反全路由 JSON 错误形态）。先杀，截断失败也返回 400
    s.kill_proc(quiet=True)
    s.last_result = None                     # 用量缓存失效（守卫/窗口判定重算）
    try:
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
    except Exception as e:
        ok, msg = False, "转写重写失败：%s" % e
    if not ok:
        return jsonify({"ok": False, "err": msg}), 400
    # v3.0：日志重写即换代（ZCode logEpoch 语义）——转写被截断，事件流的
    # 旧 seq 空间即刻作废；换代后再 emit 提示行（落在新时代里）。客户端
    # 持旧 epoch 重连 → ack(mode=reset) → transcript 重建。
    s.log.bump_epoch()
    # v3.1（#14）：分支世代 +1——旧代排队输入作废（回退后的世界线里失去
    # 意义），input_discarded 事件显式通知前端清队列
    try:
        s.bump_generation(reason="rewind")
    except Exception:
        pass
    s.sync_meta()
    s.emit({"kind": "raw", "text": "⏪ " + msg + "——发送消息即续上回退后的上下文"})
    return jsonify({"ok": True, "msg": msg, "epoch": s.log.epoch})

# ---- v3.1（#10）：durable 输入账本路由 ----


@harness_bp.route("/queue", methods=["GET", "POST"])
def harness_queue():
    """排队输入的服务端真源。GET 列表（切会话/重连初始化队列用）；POST
    入队（busy 期前端替 send 调它——排队语义从「前端本地数组」升级为
    「跨设备/跨重启可见的服务端账本」，回合终结由后端自动泵真发）。"""
    if request.method == "GET":
        s = _get_or_create((request.args.get("sid") or "").strip())
        if not s:
            return jsonify({"ok": False, "err": "会话不存在"}), 404
        return jsonify({"ok": True, "queue": s.queue_list(),
                        "gen": s._gen, "busy": s.busy})
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    text = str(data.get("text") or "")
    if not text.strip() and not (data.get("images") or data.get("files")):
        return jsonify({"ok": False, "err": "消息为空"}), 400
    # v3.1：客户端预生成 id 直接采用（SSE 事件与 POST 响应赛跑的防双画锚点，
    # 合法性在 queue_admit 内校验）
    qid = s.queue_admit(text, data.get("images"), data.get("files"),
                        eid=str(data.get("id") or "").strip() or None)
    return jsonify({"ok": True, "id": qid, "gen": s._gen})


@harness_bp.route("/queue_act", methods=["POST"])
def harness_queue_act():
    """队列条目操作：now=提到队首并中断当前回合（回合终结泵自然先发它）；
    del=作废（编辑回收走 del——前端把文本放回输入框后调它）。"""
    data = request.get_json(force=True, silent=True) or {}
    s = _get_or_create((data.get("sid") or "").strip())
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    eid = str(data.get("id") or "").strip()
    act = str(data.get("act") or "").strip()
    # v3.5.106（用户实锤「拖拽排序后仍按时间序发出」）：id 必填检查只对
    # now/del 生效——order 按 ids 整体重排、天然无单个 id，之前被此检查
    # 400 拦死，排序上报从未生效（前端 catch 不看响应码，静默吞）。
    if act != "order" and not eid:
        return jsonify({"ok": False, "err": "缺少条目 id"}), 400
    if act == "now":
        if not s.queue_to_head(eid):
            return jsonify({"ok": False, "err": "条目不存在"}), 404
        if s.busy:
            s.interrupt()          # 异步：kill → 回合终结 → 800ms 后泵发队首
        else:
            try:
                s._queue_pump()
            except Exception:
                pass
        return jsonify({"ok": True})
    if act == "del":
        return jsonify({"ok": s.queue_discard(eid, reason="user")})
    if act == "order":
        # v3.1：前端拖拽排序上报——按 ids 重排账本；未列出的条目（并发新
        # 入队）按原顺序追加尾部，不丢。v3.4.54：整段入 _inbox_lock（HTTP
        # 线程与泵/入队线程并发重排会互相丢条目）。
        # v3.5.109（designer F2/D）：重排+去重+落盘下沉 session.queue_order
        # （路由薄化、测试可直连）；响应带落账后的权威 id 序——前端按它
        # 重建本地缓存，「写响应即对账」，收窄排序后 UI 弹回旧序的窗口。
        return jsonify({"ok": True, "queue": s.queue_order(data.get("ids"))})
    return jsonify({"ok": False, "err": "未知操作"}), 400

# ---- from claude_harness.py:2920 (harness_ctx) ----


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

# ---- from claude_harness.py:2934 (harness_set_model) ----


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
    # v3.5.285（用户铁令「切模型必须确保提示词换对，不再出此类问题」）：
    # 切换即把新模型的识图口径显性写进对话流（进转写=进上下文）——盖掉
    # 历史里旧模型时代的 analyze_image 调用惯性（resume 保留的历史会让
    # 新模型模仿旧工具调用，实测连环触发不存在的工具）
    try:
        from .vision import _model_vision_mode_dual
        _mm = _model_vision_mode_dual(model, model)
        _way = ("多模态直读：看图一律用 Read 工具直读图片路径；当前工具列表"
                "中没有 analyze_image 类识图工具，历史里出现过的此类调用属于"
                "旧模型时代，禁止模仿"
                if _mm == "inline" else
                "MCP 识图通道：看图必须调用 mcp__vision__analyze_image（传"
                "图片路径/链接）；对话历史里出现过的 Read 直读图片记录属于"
                "旧多模态模型时代——你无法通过 Read 获得图片内容（只会拿到"
                "无意义的二进制/编码文本），禁止模仿，看图一律走识图工具")
        # v3.5.286：真注入标记——emit 只进前端事件流（模型看不到），首条
        # 消息前置声明才进 CLI jsonl 上下文；两路并存（前端即时可见+模型
        # 首条消息起知情）
        s._model_switch_note = _way
        s.emit({"kind": "sysnote",
                "text": "[模型切换] 已切换到 %s。识图方式：%s。"
                        % (model or "默认模型", _way)})
    except Exception:
        pass
    s.emit({"kind": "model_switched", "text": model or "默认模型"})
    return jsonify({"ok": True, "model": s.model})

# ---- from claude_harness.py:2965 (harness_stream) ----


@harness_bp.route("/stream")
def harness_stream():
    """SSE 事件流（v3.0 subscribe(base) 协议）。?sid=&epoch=&after_seq=。

    连接先发 event:ack 三态判定（对照 ZCode transport.ts subscribeParams）：
      resume   base={epoch,seq} 有效 → 回放 (seq, last] 增量
      snapshot base 无效/缺失 → 客户端清场后重放保留窗
      reset    epoch 不匹配（/rewind 换代）→ 客户端走 transcript 重建
    帧序防丢防重：先注册订阅队列→快照回放→live 段按 seq 去重（bus 实现）。
    空闲 5s 发 event:ka 心跳（前端 20s 无帧判死重连）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    # v3.5.154：跨进程残留 hold 对账（重连订阅必经；幂等）——同 transcript
    try:
        s.stale_hold_repair()
    except Exception:
        pass
    base_epoch = (request.args.get("epoch") or "").strip()
    base_seq = request.args.get("after_seq", 0, type=int)
    sub, mode, replay = s.log.subscribe(base_epoch=base_epoch, base_seq=base_seq)
    def gen():
        try:
            for frame in s.log.frames(sub, mode, replay):
                yield frame
        finally:
            s.log.unsubscribe(sub)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- v4 投影流（2026-10-20 归一重构批B；REBUILD-PLAN-ZCODE.md） ----


@harness_bp.route("/v4/stream")
def harness_v4_stream():
    """v4 投影 SSE（ZCode 归一管线）。?sid=&topic=main|sub:<agentKey>&epoch=&seq=。

    帧协议（前端 v4store 唯一消费源）：
      event:ack    {mode:resume|snapshot, epoch, seq}
      event:frame  data:{kind:"snapshot", fromSeq:0, toSeq, snapshot:{...}}
                   data:{kind:"deltas", fromSeq, toSeq, deltas:[封闭五操作]}
    服务端单方裁决续传或整窗：epoch 失配 / 落后越出保留窗 → snapshot。
    deltas 帧为 30ms 合并窗（coalesce）产物；空闲 5s 心跳 event:ka。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    # a74：watcher 启动闸补挂——_ensure_gc 原本只在 /connect（v4 流程可不经
    # connect=子代理转写 watcher 永不启动，按需 hydrate 整链缺席）
    _ensure_gc()
    topic = (request.args.get("topic") or "main").strip()
    from . import v4hub
    if topic.startswith("sub:"):
        agent = topic[4:]
        if not re.match(r"^[0-9a-zA-Z_:.]{4,128}$", agent):
            return jsonify({"ok": False, "err": "topic 非法"}), 400
        import glob as _g
        csids = [x for x in (list(getattr(s, "lineage", None) or [])
                             + [s.session_id]) if x]
        main_dir = None
        for csid in csids:
            for cand in _g.glob(os.path.join(os.path.expanduser("~"),
                                             ".claude", "projects", "*",
                                             csid + ".jsonl")):
                main_dir = os.path.dirname(cand)
                break
            if main_dir:
                break
        from .transcript import _subagent_transcript_candidates
        paths = _subagent_transcript_candidates(main_dir, csids, agent) \
            if main_dir else []
        # a62：兜底改为「候选里没有真 subagents 转写就补」——旧判据
        # `if not paths` 被 tasks/*.output 等可读但不产出的候选挡住（a60
        # 实测：paths 非空但 hydrate 零行=回放仍空）。真转写两层深：
        # projects/<项目>/<csid>/subagents/agent-<id>.jsonl
        _has_real = any(("subagents" in p) and p.endswith(".jsonl")
                        for p in paths)
        if not _has_real:
            for pat in (os.path.join("subagents", "agent-" + agent + ".jsonl"),
                        os.path.join("*", "subagents", "agent-" + agent + ".jsonl")):
                hit = _g.glob(os.path.join(os.path.expanduser("~"),
                                           ".claude", "projects", "*", pat))
                if hit:
                    paths = [hit[0]] + [p for p in paths
                                        if "subagents" not in p]
                    break
        # a74：子订阅意向登记——watcher 按需 hydrate 的闸与主 feed 等价
        # a83：feed 注册键统一 harness sid（s.sid）——session_id 会被 CLI
        # 首 init 从 None 换成 uuid（键漂移=订阅绑孤儿 feed，见 v4hub 文档）
        try:
            v4hub.v4_sub_want(s.sid, agent)
        except Exception:
            pass
        # 内存批（对抗审 A-P1）：acquire=True——取引用与订阅计数在 hub 锁内
        # 原子完成，杜绝「handler 拿到引用→reap 恰好收走→gen 绑孤儿」竞窗。
        # 本连接的 release 统一在 gen 的 finally（cell["feed"] 当前值）
        # v4.0.7（自查实证）：此处**不**取订阅计数——HEAD 请求/生成器
        # 未被消费的响应，Flask 根本不会启动生成器，finally 永不执行 →
        # 计数永久 +1（实测 HEAD 后 n=1、GET+close 后 n=0）。计数改在
        # gen() 首行获取，与 finally 同函数配对。
        feed = v4hub.v4_sub_feed(s.sid, agent, paths, acquire=False)
        # a68（用户实测「重开 pane 还是残缺/结论永不到」）：订阅时刻强制
        # 对账一轮——冻结 feed（增量截尾时代丢的尾段）由此自愈，uuid 去重
        # 幂等；订阅者随后的 deltas 帧自然拿到补回的行与 state.final
        try:
            from .subagent_watch import push_paths_once
            push_paths_once(s, agent, paths)
        except Exception:
            pass
    else:
        # 严重4 修正（a116 全审）：登记必须在建 feed **之前**。旧顺序
        # （先 v4_main_feed 再 v4_main_want）让 hydration 的 1.5~4.2s
        # 窗口内落账的事件被 ingest 门禁判「无订阅者」丢弃——实测
        # hydration 延时 0.4s 期间 emit 一条，消息行彻底消失。
        try:
            v4hub.v4_main_want(s.sid)    # F5：主订阅意向（ingest 门禁放行）
        except Exception:
            pass
        # 内存批（对抗审 A-P1）：同 sub 分支——锁内原子取引用+计数
        feed = v4hub.v4_main_feed(s, acquire=False)
    base_epoch = (request.args.get("epoch") or "").strip()
    base_seq = request.args.get("seq", 0, type=int)
    # 二十二次全审（结构）：feed **实例身份**。客户端游标只在「同一实例」
    # 内有效——换了实例（重建/TTL/重启/GC 复活）一律作废走快照。
    # 这样「旧游标落进新序号空间」在定义上不可能，不依赖任何可失效状态
    # （持久化文件/时钟/并发取号）。
    base_inc = (request.args.get("inc") or "").strip()

    def _deltas_text(f, frm, to, deltas):
        """deltas 帧文本（性能批：同 (from,to) 多订阅者共享一次序列化）。
        P2-2 修复 + 严重7 修正（a116 全审）：键加 **_ver**——feed 每次
        _commit 必 bump 版本，是「内容已变」的充分判据。原键只到
        (frm,to,len(deltas))，内容变但条数不变即命中旧文本（实测缓存
        {busy:true} vs 实际 {model:NEWER,busy:true} 键同为 (10,12,1)，
        第二订阅者永久缺 model）。"""
        _sig = (frm, to, f.frame_version(), len(deltas))
        c = f._frm_cache
        if c and c[0] == _sig:
            return c[1]
        t = "event:frame\ndata: %s\n\n" % json.dumps(
            {"kind": "deltas", "fromSeq": frm, "toSeq": to, "deltas": deltas},
            ensure_ascii=False)
        f._frm_cache = (_sig, t)
        return t

    def _ack_text(f, mode, to):
        """ack 帧文本。a116 二十三次全审：**循环内换 feed 也必须回 ack**。
        身份匹配（inc）落地后，前端只认 ack 送来的 inc；循环内三处换
        feed（越窗补快照/孤儿替换/epoch 换代）原来只发 frame 不换 inc，
        前端就拿着旧实例的 inc 配新实例的 seq —— 之后每次重连都被判
        「身份不匹配」→ 永久退化成一断线就整窗快照。"""
        return "event:ack\ndata: %s\n\n" % json.dumps(
            {"mode": mode, "epoch": f.epoch, "seq": to, "inc": f.incarnation},
            ensure_ascii=False)

    def _snap_pair(f):
        """snapshot 的 ack 与 frame **必须同批写出**（二十三次全审严重，
        撕裂态）。两者分两次 yield 会落进两个 TCP chunk（实测 99/208
        字节）；客户端若在中间断线，状态成 (inc=新实例, seq=旧游标)，
        下次重连身份判据放行 → 旧投影 + 新实例增量 → 花屏且不回退快照。
        返回 (ack_text, frame_text)。"""
        t, sent = _snap_text(f)
        # **必须把 sent 一并返回**（二十四次全审严重回归）：`sent` 是
        # `_gen()` 的循环游标，只在这里解包成局部变量会让外层永久停在 0
        # → poll(0) 恒 None → 每次循环都走「越窗补快照」分支 → **每条消息
        # 一次整窗重渲**（实测 22 条事件 22 次 snapshot、deltas=0）。
        return _ack_text(f, "snapshot", sent), t, sent

    def _snap_text(f):
        """snapshot 帧文本（性能批：seq 不变复用上次序列化）。返回 (text, seq)。
        P2-1 修复 + 严重7 修正（a116 全审）：键用 **_ver**。原键
        (seq, len(rows), busy, curTurn, ask) 在「迟到 seq 做 row upsert」时
        完全不变（行数/seq/state 全同）→ 下发快照仍是旧态（实测服务端
        tool 行已 success/DONE_OUTPUT，两态签名一致，客户端拿 running）。
        _ver 在每次 _commit 与 _reconcile_live 后递增，覆盖全部内容变更。
        a119P（用户实测「打开子代理卡顿」）：子 topic 快照加行数尾窗
        tail=220（与前端时间线上限 _subTlCap 同值）——大子会话（审计代理
        几千行）21 回合窗仍全量下发＝序列化/传输/解析/渲染全链白干，前端
        渲染完又裁回 220。total 仍为全量行数，前端据此出示省略条。缓存键
        per-feed（f._snap_txt），feed 非 main 即 sub，两种形态不会串键"""
        seq = f.snap.get("seq", 0)
        _sig = (seq, f.frame_version())
        c = f._snap_txt
        if c and c[0] == _sig:
            return c[1], seq
        # a122（用户拍板「必须全有，性能优化参考主窗口」）：子 topic 撤掉
        # a119P 的行数尾窗（tail=220 裁掉了多轮代理首轮 user 行=轮次锚点，
        # 用户实测「重开窗格续派消息正常、首条派发消息不见」）。改回与主窗
        # 完全同款：**回合窗**（tail_turns=21）——轮内永不切，锚点天然完整，
        # 大子会话的渲染开销由前端既有的 content-visibility（a114，子窗格
        # 轮组同享）+ 懒体（data-hg-lazy）承担，与主窗同一成本模型。
        if topic.startswith("sub:"):
            w = f.snapshot_wire(tail_turns=21)
        else:
            w = f.snapshot_wire()
        seq = w["seq"]
        t = "event:frame\ndata: %s\n\n" % json.dumps(
            {"kind": "snapshot", "fromSeq": 0, "toSeq": seq, "snapshot": w},
            ensure_ascii=False)
        f._snap_txt = (_sig, t)
        return t, seq

    # a74：子 feed 可替换（订阅时转写未生成=零行不缓存，客户端绑在孤儿
    # feed 上；watcher 按需 hydrate 建出正式 feed 后客户端收不到任何行，
    # 只能等偶然重连——实测窗格空到代理跑完才追平）。循环内 5s 对账点
    # 重取注册表，换了就整窗快照重对齐。
    # 内存批：cell 提升到 gen/_gen 两层闭包共享。订阅计数**在 gen() 内**
    # （见下），handler 只拿引用——HEAD/未消费响应不启动生成器也就不计数。
    cell = {"feed": feed,
            "agent": topic[4:] if topic.startswith("sub:") else None,
            "recheck": time.time()}

    def gen():
        # N5 修复（a116）：生成器全程无 try/finally——客户端断开/异常时
        # 无清理钩子。MINOR-3（a116 二次全审）：原 finally 是 `pass`，与
        # 注释「兜底清理」名实不符。但不能在此撤销订阅意向：同一会话可能
        # 还有其它连接（多标签页/子页），_main_wanted 是会话级不是连接级，
        # 撤了会让仍在场的连接退回「无订阅」。
        # v4.0.7（自查实证）：计数必须在这里取——handler 里取的话，
        # HEAD 请求/未被消费的流响应根本不会启动生成器，finally 永不执行，
        # 计数永久 +1（实测 HEAD 后 n=1、GET+close 后 n=0）。
        # acquire=True 在本函数首行**原子重取**当前 feed：防「handler 取
        # 引用 → reap 恰好收走 → 绑到已回收实例」的竞窗，且与 finally
        # 的 cell["feed"] 严格 1:1（_gen 内换 feed 时做配对迁移）。
        cell["feed"] = (v4hub.v4_sub_feed(s.sid, cell["agent"], None,
                                          acquire=True)
                        if cell["agent"] is not None
                        else v4hub.v4_main_feed(s, acquire=True))
        try:
            for _chunk in _gen():
                yield _chunk
        finally:
            cell["feed"].sub_release()

    def _gen():
        sent = 0
        mode = "snapshot"
        # 二十二次全审：**身份匹配优先**。inc 不匹配（含老客户端不传）
        # 一律走整窗快照——这是本设计的正确性基石，不能放宽。
        if (base_inc and base_inc == feed.incarnation
                and base_epoch and base_epoch == feed.epoch and base_seq > 0):
            # a92（用户实锤「同步中刚一显示又被运行中+秒表刷掉」）：安静 feed
            # （无新帧）曾因 frames_after 的 None 二义性被误判为不可续传→整窗
            # snapshot→前端全量重渲抹掉 ephemeral 状态（live 文本/同步中）。
            # 水位在窗内即 resume（无新帧就只 ack 空转），越窗才 snapshot
            # 一般-1（a116 八次全审）：改用 resume_probe 原子裁决
            # （can_resume + frames_after 同一锁内完成）
            _ok, _fr, _last = feed.resume_probe(base_seq)
            if _ok:
                if _fr is not None:
                    deltas, to = _fr
                else:
                    deltas, to = [], _last
                mode, sent = "resume", to
                yield _ack_text(feed, mode, to)
                if deltas:
                    yield _deltas_text(feed, base_seq, to, deltas)
        if mode == "snapshot":
            # 二十三次全审（严重，撕裂态）：ack 与 frame 必须同批写出
            _a, _t, sent = _snap_pair(feed)
            yield _a + _t
        idle = 0.0
        while True:
            _f = cell["feed"]
            # 性能批（事件驱动订阅）：阻塞等新帧落账（feed._commit 广播），
            # 无新帧只睡到对账/keepalive 最近到点——空闲期零唤醒（原
            # sleep(0.03) 每连接每秒醒 33 次，只为问一句「有新帧吗」）
            _t_ka = 5.0 - idle
            if cell["agent"] is not None:
                _t_ka = min(_t_ka, 5.0 - (time.time() - cell["recheck"]))
            _tmo = max(0.02, _t_ka)
            _v = _f.frame_version()
            _v2 = _f.wait_frames(_v, _tmo)
            if _v2 != _v:
                # 30ms 合并窗（FLUSH_MS 语义保留）：同突发的连续落账并成一帧
                _f.wait_frames(_v2, 0.03)
            # P0-3 修复（a116，a98 性能批引入的丢帧窗口）：原实现只在
            # `_v2 != _v` 时才取帧。而 yield 写 socket 挂起期间落账的事件
            # 会把 _ver 提前 bump，下一轮读到的基线已包含它 → 判「无变化」
            # → 走 ka 路径不调 frames_after → **该帧永久滞留**（实测 200ms
            # 写耗时 + 10ms 事件间隔 = 40 帧里 16 帧滞留；丢 turn_complete
            # 则组头永停「工作中」）。修法：无论是否超时都按既有 sent 游标
            # 取一次帧——真无新帧时 frames_after 返回 None，零成本。
            _got = False
            # a116 九次全审根修：迟到事件拿到**新的末尾投递序号**，天然
            # 落在任何游标之后 → 常规 frames_after 增量路径必然取到，
            # 不再需要「重对齐/强制整窗快照」。原 resnap 分支（读
            # `_resnap_ver` 与取帧两步、per-connection rsnap 记账）已随
            # feed 侧 late 机制一并删除——poll 保留原子取帧语义。
            try:
                _fr = _f.poll(sent)
            except Exception:
                _fr = None
                log.exception("v4 stream 取帧失败 sid=%s", s.session_id)
            if _fr is not None:
                deltas, to = _fr
                frm_from = sent
                sent = to
                if deltas:
                    yield _deltas_text(_f, frm_from, to, deltas)
                    _got = True
            elif not _f.can_resume(sent):
                # F4（a116 十次全审）：慢消费/长时间断线后游标越出保留窗
                # → poll 恒 None、can_resume 恒 False。原实现无此分支，
                # ka 心跳每 5s 刷新客户端 _lastFrameAt → 前端判死永不触发
                # → **该连接永久停更**（实测 1200 笔后 poll(1)=None）。
                # 越窗唯一的自愈手段是整窗快照（toSeq 推进到当前水位）。
                try:
                    _a, _t, sent = _snap_pair(_f)
                    yield _a + _t
                    _got = True
                except Exception:
                    log.exception("v4 stream 越窗补快照失败 sid=%s",
                                  s.session_id)
            if _got:
                idle = 0.0
                continue
            # 超时路径：a74 孤儿 feed 对账（每 5s 一次，仅 sub topic）——
            # 注册表里的正式 feed（watcher hydrate/他端订阅建出）替换孤儿时
            # 整窗重发
            if cell["agent"] is not None:
                try:
                    _now = time.time()
                    if _now - cell["recheck"] >= 5.0:
                        cell["recheck"] = _now
                        # 内存批：acquire=True 锁内原子取引用+计数；不采纳
                        # （同实例/零产出临时）时立即退还，防计数虚高
                        _f2 = v4hub.v4_sub_feed(s.sid, cell["agent"], None,
                                                acquire=True)
                        if _f2 is not _f and _f2.snap.get("rows"):
                            _f.sub_release()
                            cell["feed"] = _f2
                            _a, _t, sent = _snap_pair(_f2)
                            yield _a + _t
                            idle = 0.0
                            continue
                        # v4.0.6（自查实锤）：acquire=True 已给 **_f2 计数 +1**，
                        # 凡「不采纳」都要退还。原实现只覆盖 `_f2 is not _f`，
                        # 漏了 `_f2 is _f`（在册同实例：每 5s 对账再加 1 永不
                        # 退还）→ subs_n 单调虚高 → 该 feed 永不回收（内存
                        # 优化对子 feed 整体失效）。
                        if _f2 is _f or not _f2.snap.get("rows"):
                            _f2.sub_release()
                except Exception:
                    pass
            else:
                # S5 修复（a116）：main topic 的 epoch 对账。原实现只对 sub
                # topic 每 5s 重取注册表，main 把 feed 锁进闭包——/rewind
                # bump_epoch 后新 feed 进注册表，页面仍绑旧 epoch feed：新事件
                # 永远到不了（实测「点回滚后主窗不回滚、新消息也不再出现」，
                # 只能手动刷新）。每 5s 比对 epoch，换代即整窗快照重对齐。
                try:
                    _now = time.time()
                    if _now - cell["recheck"] >= 5.0:
                        cell["recheck"] = _now
                        # 内存批：acquire=True 锁内原子取引用+计数
                        _f2 = v4hub.v4_main_feed(s, acquire=True)
                        # FATAL-3 修正（a116 二次全审）：判据取**对象身份**
                        # 换代，不能只比 epoch。零产出临时 feed 与随后建出的
                        # 正式 feed 的 epoch 同值（都是 s.log.epoch），只比
                        # epoch 则永不切换 → 已订阅客户端永久绑在空 feed 上
                        # （实测 client rows=0、can_resume=False、
                        # frames_after=None，收不到任何 HIST/新行，只能刷新）。
                        # /rewind 换代同样由身份变化覆盖。
                        if _f2 is not _f:
                            _f.sub_release()
                            cell["feed"] = _f2
                            _a, _t, sent = _snap_pair(_f2)
                            yield _a + _t
                            idle = 0.0
                            continue
                        _f2.sub_release()   # 同实例：本连接已持计数，退还刚取
                except Exception:
                    pass
            idle = min(idle + _tmo, 5.0)
            if idle >= 5.0:
                idle = 0.0
                yield "event:ka\ndata: {}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---- from claude_harness.py:2990 (harness_sessions) ----


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
                      "alive": alive, "busy": busy, "busy_since": busy_since,
                      "scheme": m.get("scheme") or ""})   # v3.5.98：会话方案名（前端标注）
    items.sort(key=lambda x: -x["last_active"])
    _cur_scheme = ""
    try:
        from src.claude_default import active_scheme_name
        _cur_scheme = active_scheme_name()
    except Exception:
        pass
    return jsonify({"ok": True, "sessions": items, "scheme": _cur_scheme})

# ---- from claude_harness.py:3018 (harness_transcript) ----


@harness_bp.route("/transcript")
def harness_transcript():
    """切回会话的历史气泡。?sid=。转写不存在返回 lines:[]（新会话空气泡）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    # v3.5.154：跨进程残留 hold 对账（切回会话必经）——上一进程 emit 的
    # turn_hold 在进程死亡后残留事件流，前端重放即永久挂死；后端无回合
    # 在跑时补发 turn_complete 解锁（详见 session.stale_hold_repair）
    try:
        s.stale_hold_repair()
    except Exception:
        pass
    # 399-N1：水位在**读文件之前**捕获（transcript_for 解析大会话可达百毫秒，
    # 期间 emit 的事件行先于读窗不入 lines、又 ≤ 应答 seq——旧水位把它们判为
    # 「已含」跳过=从账与 DOM 双丢）。lines_seq=读窗前快照：_sq > lines_seq 的
    # live 行前端一律保尾拼接（宁毫秒级重复 assistant/thinking，不丢消息）
    _seq0 = s._seq
    lines = transcript_for(s)
    _dln_inject(lines)   # v3.5.336：Edit/MultiEdit 行注入真实行号（ZCode 式权威下发）
    return jsonify({"ok": True, "lines": lines or [], "alive": s.alive,
                    "busy": s.busy, "busy_since": s.busy_since,
                    "model": s.model, "title": s.title, "seq": s._seq,
                    "lines_seq": _seq0, "epoch": s.log.epoch})


# ---- v3.5.336：Edit 真实行号转写级注入（ZCode 架构对齐 ----
# 用户实锤「反反复复修不好，重开会话行号还是不对」：前端事后回填
# （v3.4.62/329/331/333）在任何重建路径上都要重新接线，竞态修不胜修。
# ZCode 的做法是权威事实一次产生：编辑结果落盘时算好 hunk 行号、随
# 转写行结构化下发（fileDiff hunks 自带 oldStart/newStart），前端零回填。
# 此处对齐：transcript 响应前对 Edit/MultiEdit 行定位（当前文件定位
# new_string——与既有 diff_lines 同逻辑同口径），写 l.dln。所有重建
# 路径（快照/重渲/刷新/重开）读转写即得，前端零逻辑零竞态。
_DLN_CACHE = {}


def _dln_inject(lines):
    try:
        for l in lines:
            if not isinstance(l, dict) or l.get("role") != "tool":
                continue
            nm = str(l.get("text") or "")
            if nm not in ("Edit", "MultiEdit"):
                continue
            inp = l.get("input") or {}
            fp = str(inp.get("file_path") or "")
            if not fp or not os.path.isfile(fp):
                continue
            news = ([str(e.get("new_string") or "")
                     for e in (inp.get("edits") or []) if isinstance(e, dict)]
                    if nm == "MultiEdit" else [str(inp.get("new_string") or "")])
            if not any(news):
                continue
            key = fp + "\x01" + str(news[0])[:120]
            hit = _DLN_CACHE.get(key)
            if hit is None:
                hit = _dln_locate(fp, news)
                _DLN_CACHE[key] = hit
            l["dln"] = hit
    except Exception:
        pass


def _dln_locate(fp, news):
    """当前文件定位各 new_string 起始行（歧义/未命中给 None，不造假）。"""
    try:
        if os.path.getsize(fp) > 8 * 1024 * 1024:
            return [None] * len(news)
        with open(fp, "r", encoding="utf-8", errors="replace") as f:
            fl = f.read().split("\n")
    except OSError:
        return [None] * len(news)
    out, cur = [], 0
    for s in news:
        pat = str(s or "").split("\n")
        if not pat or (len(pat) == 1 and pat[0] == ""):
            out.append(None)
            continue
        hit = None
        for i in range(cur, max(cur, len(fl) - len(pat) + 1)):
            if fl[i] == pat[0] and fl[i:i + len(pat)] == pat:
                hit = i
                break
        if hit is None:
            out.append(None)
            continue
        amb = any(i != hit and fl[i] == pat[0] and fl[i:i + len(pat)] == pat
                  for i in range(len(fl) - len(pat) + 1))
        out.append(None if amb else hit + 1)
        cur = hit + len(pat)
    return out


# v3.4.62（用户需求「代码编辑看不到真实改动行号」）：Edit/MultiEdit diff
# 真实行号定位。POST {sid?, path, news:[new_string,...]}。前端在
# tool_result（文件已写盘）后调用——读改后文件按序（游标递增，MultiEdit
# 后续编辑在更后位置）定位各 new_string 的起始行（1-based，首行+整段
# 连续匹配防同文本误配），返回 {ok, lines:[行号|null,...]}。找不到
# （该处后续又被改/文件移动）返回 null，前端保持相对行号不造假。
# 只回行号不回文件内容（本地 127.0.0.1 单用户环境，与 /transcript 同
# 信任域）；8MB/文本限定档，超大或二进制直接拒。
@harness_bp.route("/diff_lines", methods=["POST"])
def harness_diff_lines():
    j = request.get_json(silent=True) or {}
    path = str(j.get("path") or "")
    news = j.get("news")
    if not path or not isinstance(news, list) or not news:
        return jsonify({"ok": False, "err": "参数缺失"}), 400
    if not os.path.isfile(path):
        return jsonify({"ok": False, "err": "文件不存在"}), 404
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return jsonify({"ok": False, "err": "文件过大"}), 413
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            fl = f.read().split("\n")
    except OSError as e:
        return jsonify({"ok": False, "err": "读取失败: %s" % e}), 500
    lines = []
    cur = 0
    for s in news:
        pat = str(s or "").split("\n")
        if not pat or (len(pat) == 1 and pat[0] == ""):
            lines.append(None)
            continue
        hit = None
        for i in range(cur, max(cur, len(fl) - len(pat) + 1)):
            if fl[i] == pat[0] and fl[i:i + len(pat)] == pat:
                hit = i
                break
        if hit is None:
            lines.append(None)
            continue
        # 轻审P3：全文重复命中二义（改动块与他处既有块同文）——首 match 可能
        # 命中旧块而非真改动位，回填出「假真实行号」。全文同 pat 完整匹配数
        # >1 时按「歧义不造假」弃定位
        _amb = False
        for i in range(0, len(fl) - len(pat) + 1):
            if i != hit and fl[i] == pat[0] and fl[i:i + len(pat)] == pat:
                _amb = True
                break
        if _amb:
            lines.append(None)
            continue
        lines.append(hit + 1)
        cur = hit + len(pat)   # 游标推进：MultiEdit 同文件多处编辑按序不回扫
    return jsonify({"ok": True, "lines": lines})


# ---- from claude_harness.py:3030 (harness_audit_gate) ----


@harness_bp.route("/audit_gate")
def harness_audit_gate():
    """设计档事中一次性提醒端点（v3.5.53 重构）。?session_id=<CLI 侧会话 id>。
    返回 {ok, gate}；gate.block=true=本回合首次累计达设计线且未派 designer
    （msg 指路出方案，designFired 置位后本回合不再咬）。审计档（轻审线中途
    拦截）已退役归回合结束结算。

    口径与 _audit_settle 同源：_audit_state 判启用（roles 开+
    audit_mode!=off；闸仅 light——strong 直改是设计常态，_audit_state
    第三位 strong 旗在此分流；读一次小配置文件，改配置即时生效），
    used/designFired 取会话 _audit 的回合内直改累计与设计档一次性触发标志，
    判定走 harness_roles.audit_gate_check。

    查不到会话（session_id 不在 _sessions：别的实例/已换代）一律放行。
    注意子代理与主会话同 session_id（官方 hooks 文档+本机 CLI 实证：hook
    stdin 无独立 id，子代理标记是 agent_id/agent_type 字段）——子代理的
    放行判定在 hook 脚本侧做（agent_id/agent_type 有值即 exit 0，不发起
    本查询），拦它等于闸自锁。本接口纯内存读（配置文件除外），每次直改
    都调，无磁盘扫描。"""
    csid = (request.args.get("session_id") or "").strip()
    gate = {"block": False}
    if csid:
        with _sessions_lock:
            s = next((x for x in _sessions.values()
                      if x.session_id == csid), None)
        if s is not None:
            st = s._audit_state()
            # v4.0.2（用户实锤「事中闸还是未生效」）：原 `not st[2]` 把
            # strong(mid) 形态挡在闸外，而结算 `_audit_settle` 的设计档
            # 不看 strong —— 口径不一致导致 mid 只事后咬。改为与结算同口径：
            # 闸只看设计线是否启用，形态不再参与。
            if st is not None:
                au = s._audit or {}
                used_l = int(au.get("lines") or 0)
                fired = bool(au.get("designFired"))
                block, msg = audit_gate_check(
                    used_l, reviewed=bool(au.get("reviewer")),
                    designed=bool(au.get("designer")),
                    design_fired=fired)
                if block:
                    # v3.5.53：设计档一次性——命中即置 fired（本回合不再咬；
                    # 结算时清零，新回合重新可触发一次）
                    au["designFired"] = True
                    gate = {"block": True, "used": used_l, "msg": msg}
    return jsonify({"ok": True, "gate": gate})

# ---- from claude_harness.py:3339 (harness_subagent_replay) ----


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
    # v2.43：双源查找抽共用 _subagent_rows_for（transcript_for 的子代理段
    # 注入同源复用；语义不变：①projects 同目录优先 ②新版 CLI tasks 目录按
    # lineage 全链兜底，读失败继续试下一候选）
    # v3.5.154：脏转写防御兜底——进程死亡可致转写异型行（实测裸 bool 行
    # 使 _subagent_rows_from_jsonl 抛 AttributeError=整接口 500），任何异常
    # 都降级为 found:False（前端走中性「无可回放」分支），绝不 500
    try:
        rows = _subagent_rows_for(main_dir, csids, agent)
    except Exception as _e:
        log.warning("subagent_replay parse fail: %r", _e)
        return jsonify({"ok": True, "found": False, "rows": []})
    if rows is None:
        return jsonify({"ok": True, "found": False, "rows": []})
    # 批3b（实测修复「重铺后中途行重复插入乱序」）：响应附转写字节尾——前端
    # 铺底成功即写 tail 账本，消除「无账本 offset=0 全量重喂」通道（~900KB
    # ×2s 逐行重喂 + 长文折叠行查重锚打孙级失明 = 中途行 append 到时间线尾
    # 冒充结论的温床；批1「铺底后轮询续流」缺这环衔接）
    _sz = 0
    try:
        for _c in _subagent_transcript_candidates(main_dir, csids, agent):
            # 0 字节的 tasks .output 占位不算（现行 CLI 先落占位再写真转写，
            # 与 _subagent_rows_for 的「空解析继续试下一候选」同语义——
            # 实测：占位先命中 break 后 _sz=0，账本不落=全量重喂通道复活）
            if _c and os.path.isfile(_c) and os.path.getsize(_c) > 0:
                _sz = os.path.getsize(_c)
                break
    except Exception:
        _sz = 0
    return jsonify({"ok": True, "found": True, "rows": rows, "size": _sz})


# ---- v3.5.158：SendMessage/胶囊点击 → 无条件直达子代理（解析接口） ----

_SUBAGENT_RESOLVE_CACHE = {}          # (sid, tid) → dict（FIFO 128）
_SUBAGENT_RESOLVE_KEYS = []
_AGENTID_RE = re.compile(r"^[0-9a-zA-Z_-]{8,64}$")


def _resolve_cache_put(key, val):
    """进程内结果记忆（FIFO 128）：同 tid 二次点击零成本。"""
    if key in _SUBAGENT_RESOLVE_CACHE:
        return
    _SUBAGENT_RESOLVE_CACHE[key] = val
    _SUBAGENT_RESOLVE_KEYS.append(key)
    while len(_SUBAGENT_RESOLVE_KEYS) > 128:
        _SUBAGENT_RESOLVE_CACHE.pop(_SUBAGENT_RESOLVE_KEYS.pop(0), None)


@harness_bp.route("/subagent_resolve")
def harness_subagent_resolve():
    """v3.5.158（用户硬性要求「任何情况下点开胶囊/SendMessage 必达原子代理」）：
    tid（tool_use_id | task_id | agentId）→ 解析出真实 agentId。
    处理序：①O(1) 快判（tid 本身有转写=agent；tasks/<tid>.output 存在=后台
    命令任务）②扫主会话转写 jsonl（血统链，子串门控命中行才 json.loads，
    55MB 实测 0.23s）提 SendMessage 的 to/result 双侧 agentId。全 miss →
    kind:notfound。任何异常降级 notfound（对齐「绝不 500」口径）。进程内
    FIFO 128 缓存，同 tid 二次点击零成本。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    tid = (request.args.get("tid") or "").strip()
    if not tid or not re.match(r"^[0-9a-zA-Z_-]{8,64}$", tid):
        return jsonify({"ok": False, "err": "tid 参数非法"}), 400
    key = (s.sid, tid)
    hit = _SUBAGENT_RESOLVE_CACHE.get(key)
    if hit is not None:
        return jsonify({"ok": True, **hit})
    res = {"kind": "notfound"}
    try:
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
        # ①O(1) 快判（序敏感：先 agent 后 task——同 tid 既有真实子代理转写
        #   又有 tasks/<tid>.output 时（CLI 启动即建 0 字节占位文件），占位
        #   文件不得抢走真实转写的身份）：
        #   projects jsonl / subagents jsonl 两形态转写存在 = agentId
        if main_dir:
            for p in _subagent_transcript_candidates(main_dir, csids, tid):
                if ".output" in os.path.basename(p):
                    continue        # tasks output 不算子代理转写证据
                if os.path.isfile(p):
                    res = {"kind": "agent", "agentId": tid}
                    break
        # ②tasks/<tid>.output 存在 = 后台命令任务（Bash run_in_background）
        if res["kind"] == "notfound":
            la = os.environ.get("LOCALAPPDATA")
            if la and main_dir:
                for csid in csids or []:
                    if os.path.isfile(os.path.join(
                            la, "Temp", "claude", os.path.basename(main_dir),
                            csid, "tasks", tid + ".output")):
                        res = {"kind": "task", "taskId": tid}
                        break
        # ③扫主会话转写：tool_use 侧（SendMessage.to / Task 描述）+
        #   tool_result 侧（resumedAgentId / agentId 多形态）
        if res["kind"] == "notfound" and main_dir:
            files = []
            for csid in csids:
                fp = os.path.join(main_dir, csid + ".jsonl")
                if os.path.isfile(fp):
                    files.append(fp)
            _id_re = re.compile(r"^[0-9a-zA-Z_-]{8,64}$")
            _aid_res = [re.compile(p) for p in (
                r"resumedAgentId[\"':\s]+([0-9a-zA-Z_-]{8,64})",
                r"[\"']agentId[\"'][:\s]+[\"']([0-9a-zA-Z_-]{8,64})[\"']",
                r"(?<![a-zA-Z])agentId[\"':\s]+([0-9a-zA-Z_-]{8,64})",
                r'from "([0-9a-zA-Z_-]{8,64})" \(its SubagentHandback')]
            agent_id = to_name = None
            t_type = t_desc = ""
            for fp in files:
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        for raw in f:
                            if tid not in raw:
                                continue        # 子串门控：命中行才 json.loads
                            try:
                                o = json.loads(raw)
                            except Exception:
                                continue
                            if not isinstance(o, dict):
                                continue
                            m = o.get("message") or {}
                            content = m.get("content")
                            blocks = content if isinstance(content, list) else []
                            for b in blocks:
                                if not isinstance(b, dict):
                                    continue
                                if b.get("type") == "tool_use" and b.get("id") == tid:
                                    inp = b.get("input") or {}
                                    to = str(inp.get("to") or "")
                                    if _id_re.match(to):
                                        agent_id = to
                                    elif to:
                                        to_name = to
                                    if (b.get("name") or "") in ("Task", "Agent"):
                                        t_type = inp.get("subagent_type") or inp.get("agent_type") or "Task"
                                        t_desc = str(inp.get("description") or "")[:120]
                                elif b.get("type") == "tool_result" and b.get("tool_use_id") == tid:
                                    txt = ""
                                    bc = b.get("content")
                                    if isinstance(bc, str):
                                        txt = bc
                                    elif isinstance(bc, list):
                                        txt = "\n".join(
                                            x.get("text", "") for x in bc
                                            if isinstance(x, dict))
                                    for rx in _aid_res:
                                        mm = rx.search(txt)
                                        if mm:
                                            agent_id = mm.group(1)
                                            break
                            if agent_id:
                                break
                except Exception:
                    continue
                if agent_id:
                    break
            # v3.5.160 全审F5：第三正则可能从 tool_result 散文（如报错文案）
            # 误吞伪 agentId——命中后必须先验转写候选真实存在才置信 agent，
            # 否则降 toName/notfound（「转写或在别处」由前端横幅承接）
            if agent_id and _id_re.match(agent_id):
                tr = False
                for p in _subagent_transcript_candidates(main_dir, csids, agent_id):
                    if os.path.isfile(p):
                        tr = True
                        break
                if tr:
                    res = {"kind": "agent", "agentId": agent_id, "transcript": True}
                    if t_type:
                        res["type"] = t_type
                    if t_desc:
                        res["desc"] = t_desc
                elif to_name:
                    res = {"kind": "toName", "toName": to_name}
            elif to_name:
                res = {"kind": "toName", "toName": to_name}
    except Exception as _e:
        log.warning("subagent_resolve fail: %r", _e)
        res = {"kind": "notfound"}
    # v3.5.160 全审F1：只缓存终态（agent/task）——toName/notfound 是瞬态
    # （send→result 落盘窗口/转写未刷盘），缓存会把包装 tid 的跳转钉死到
    # 进程重启，违反「任何情况必达」
    if res.get("kind") in ("agent", "task"):
        _resolve_cache_put(key, res)
    return jsonify({"ok": True, **res})

# ---- from claude_harness.py:3379 (harness_subagent_tail) ----


@harness_bp.route("/subagent_tail")
def harness_subagent_tail():
    """v2.46：子代理转写增量尾读——运行中段实时思考的数据源。
    ?sid=&agent=<agentId>&offset=<n> → {ok, found, text, offset}。
    背景：CLI stream-json 不转发子代理（sidechain）thinking 块（v2.44 实证
    112 事件 0 块 vs 转写落盘 146 块），而 tasks\\<id>.output 实时落盘含全部
    思考。前端对运行中段 2s 轮询本接口：从 offset 读到文件尾，只消费到最后
    一个行边界（半行留待下次——JSONL 行边界切不会截断 UTF-8 多字节序列），
    返回新增完整行的原文与消费后的新 offset。found=False = 转写不存在
    （协作包装/旧会话/尚未落盘）——前端静默跳过下轮再试。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    agent = (request.args.get("agent") or "").strip()
    if not agent or not re.match(r"^[0-9a-zA-Z_-]{8,64}$", agent):
        return jsonify({"ok": False, "err": "agent 参数非法"}), 400
    try:
        offset = max(0, int(request.args.get("offset") or 0))
    except (TypeError, ValueError):
        # v2.46R（P6）：非数字与「非法 400」口径一致——静默回 0 会重读全文件
        # 把已消费的思考块再吐一遍（前端 offset 账目被破坏）
        return jsonify({"ok": False, "err": "offset 参数非法"}), 400
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
        return jsonify({"ok": True, "found": False, "text": "", "offset": offset})
    # 候选路径依序试（与回放/段注入同源）；跳过 0 字节文件——现行 CLI 会
    # 预建空的 tasks\<id>.output（v2.52 实证恒 0 字节不写），isfile 命中
    # 即返回会把有数据的 subagents jsonl（第三源）永久堵死：运行中轮询
    # 与完成回填都只能看到空转写=思考全程断供。size 读取在 try 内（含
    # 0 字节判定）——isfile 通过后文件被删的竞态也不裸抛
    for p in _subagent_transcript_candidates(main_dir, csids, agent):
        if not os.path.isfile(p):
            continue
        try:
            size = os.path.getsize(p)
            if size <= 0:
                continue
            if size <= offset:
                # 无新增（半行也暂不吐）——offset 原样返回
                return jsonify({"ok": True, "found": True, "text": "", "offset": offset})
            with open(p, "rb") as f:
                f.seek(offset)
                chunk = f.read()
            # 只消费到最后一个行边界（含换行字节）；无完整行（还在写半行）不消费
            cut = chunk.rfind(b"\n")
            if cut < 0:
                return jsonify({"ok": True, "found": True, "text": "", "offset": offset})
            consumed = chunk[:cut + 1]
            return jsonify({"ok": True, "found": True,
                            "text": consumed.decode("utf-8", errors="replace"),
                            "offset": offset + cut + 1})
        except OSError:
            continue
        except Exception as _e:
            # v3.5.154：单候选任何异常（脏转写/句柄竞态）都试下一候选，绝不 500
            log.warning("subagent_tail candidate fail: %r", _e)
            continue
    return jsonify({"ok": True, "found": False, "text": "", "offset": offset})

# ---- from claude_harness.py:3445 (harness_peer_pair_log) ----


@harness_bp.route("/peer_pair_log", methods=["POST"])
def harness_peer_pair_log():
    """v2.37R2（复审6）：协作回传配对结果落审计日志——task_id=SendMessage to
    同源假设的事后取证点（命中与否都记，和 agents_dir_audit 同通道）。
    fire-and-forget，前端不等响应，失败静默。"""
    data = request.get_json(force=True, silent=True) or {}
    try:
        from .roles import _agents_dir_audit
        _agents_dir_audit("peer-pair", "sid=%s task=%s peer=%s paired=%s" % (
            str(data.get("sid") or "")[:20], str(data.get("task") or "-")[:64],
            str(data.get("name") or "-")[:64], bool(data.get("ok"))))
    except Exception:
        pass
    return jsonify({"ok": True})

# ---- from claude_harness.py:3461 (harness_peer_result_check) ----


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
            # sinces 与 peers 按下标对齐；白名单过滤后仍按下标取——越界/非法
            # 一律回退 0（不过滤），不让对齐残缺炸掉整批核实
            since = int(sinces[idx]) if idx < len(sinces) else 0
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

# ---- from claude_harness.py:3541 (harness_events) ----


@harness_bp.route("/events")
def harness_events():
    """事件增量（轮询兜底/断线补齐）。?sid=&after_seq=&epoch=

    v3.0：响应带 epoch——轮询方发现 epoch 与自己水位不符即走 reset 重建
    （与 SSE ack(mode=reset) 同语义，轮询路径不再只有 seq 单字段）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    req_epoch = (request.args.get("epoch") or "").strip()
    mode = s.log.store.resume_mode(req_epoch or None,
                                   request.args.get("after_seq", 0, type=int)) \
        if req_epoch else "snapshot"
    return jsonify({"ok": True, "events": s.get_events_after(request.args.get("after_seq", 0, type=int)),
                    "seq": s._seq, "epoch": s.log.epoch, "mode": mode,
                    "alive": s.alive, "busy": s.busy,
                    "busy_since": s.busy_since,
                    # v3.1：投影随增量下发——前端 reducer 种子（切会话/重连后
                    # 进程面板不必从零重放就能对齐服务端真相）
                    "proj": s.log.store.projection,
                    "queue": s.queue_list()})


@harness_bp.route("/agents")
def harness_agents():
    """子代理冷查询投影（ZCode 式，唯一真源=磁盘）。

    ?sid= → {ok, agents:{agentId(或pending:tid)→条目}, tidMap, rev}
    条目：{agentId, found, type, desc(任务名), status(running/done/err/
    interrupted[+lost]), t0, doneAt, rounds(续派轮数), lastActive, tids[],
    bg, tokens, toolN, brief}。前端胶囊/目录/动态/分页全部从它派生。
    每次查询从主会话 jsonl（水位增量吸收）+子代理转写尾探+meta.json
    现算——F5/切会话/后端重启的正确性由数据源构造性保证（历次
    「续派两个子代理/假完成/名字不对/bg假done」实锤的整类根治）。"""
    s = _get_or_create(request.args.get("sid") or "")
    if not s:
        return jsonify({"ok": False, "err": "会话不存在"}), 404
    try:
        from .subagent_readmodel import get_model
        proj = get_model(request.args.get("sid") or "").refresh(s)
        return jsonify({"ok": True, "agents": proj["agents"],
                        "tidMap": proj["tidMap"], "rev": proj["rev"]})
    except Exception as _e:
        log.warning("cold agents fail %r", _e)
        return jsonify({"ok": False, "err": "cold:%r" % _e}), 500

# ---- from claude_harness.py:3552 (harness_rename) ----


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

# ---- from claude_harness.py:3565 (harness_delete) ----


@harness_bp.route("/delete", methods=["POST"])
def harness_delete():
    """删会话：杀进程 + 删元数据（~/.claude 转写不动）。body: {sid}。"""
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("sid") or "").strip()
    with _sessions_lock:
        s = _sessions.pop(sid, None)
    # 全审G2：readmodel（含全量事实表）随会话删除同步回收——否则滞留后端
    # 进程生命周期，长期运行累积泄漏；v4 投影 feed 同步回收（批B）
    try:
        from .subagent_readmodel import _models, _models_lock
        with _models_lock:
            _models.pop(sid, None)
    except Exception:
        pass
    try:
        from . import v4hub
        v4hub.v4_drop_session(sid)
    except Exception:
        pass
    if s:
        s.close()
    with _meta_lock:
        _meta_load()
        _meta.pop(sid, None)
        _meta_tombstones.add(sid)   # 盘面上那条也别让 _meta_save 合并回来
    _meta_save()
    # a116 十六次全审：会话删除 → wseq 高水位小文件一并清（否则每删一个
    # 会话就在 ~/.serialconsole_pro/v4wseq 留一个几十字节的孤儿，长期累积）
    try:
        from ..eventlog.store import drop_wseq_file
        # 先关常开句柄再删文件（Windows 下打开的文件删不掉）
        try:
            if s is not None:
                s.log.store.close_wseq()
        except Exception:
            pass
        drop_wseq_file(sid)
    except Exception:
        pass
    return jsonify({"ok": True})

# ---- from claude_harness.py:3582 (_recover_scan) ----


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

# ---- from claude_harness.py:3685 (harness_recoverable) ----


@harness_bp.route("/recoverable")
def harness_recoverable():
    """列出可恢复的孤儿会话（盘上有转写、注册表没条目）。"""
    try:
        items = _recover_scan()
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500
    return jsonify({"ok": True, "items": items})

# ---- from claude_harness.py:3695 (harness_recover) ----


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

# ---- from claude_harness.py:3741 (harness_models) ----


@harness_bp.route("/models")
def harness_models():
    d = available_models()
    # v2.19：附带多模态名单（前端下拉打 👁 标记；判定口径同 start() 注入）
    # v2.28.1：mm_mcp 字段退役——非真多模态一律走 MCP（默认态），无需枚举
    return jsonify({"ok": True, "models": d.get("models", []),
                    "default": d.get("default"),
                    "mm": [m for m in d.get("models", []) if _model_is_multimodal(m)]})

# ---- from claude_harness.py:3751 (harness_mcp_list) ----


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

# ---- from claude_harness.py:3773 (harness_vision_status) ----


@harness_bp.route("/vision_status")
def harness_vision_status():
    """v2.28：识图会话退役——状态 API 只回静态退役形态。前端徽章按
    needed=false + alive=false 显示「多模态直读/关闭」，不再有会话态。
    保留端点是为兼容旧前端轮询（改字段会 JS 报错）。
    v3.5.37（用户实锤「徽章显示 MCP 还开着」误导）：带 ?sid= 时附当前会话
    模型的识图形态 mode（inline=多模态直读无 MCP 工具 / mcp=MCP 通道挂载）
    ——v3.5.36 起 MCP 挂载按模型形态门控，徽章该反映的是会话真相。"""
    cfg = _vision_load()
    mode = ""
    sid = (request.args.get("sid") or "").strip()
    if sid:
        m = ""
        with _sessions_lock:
            s = _sessions.get(sid)
        if s:
            try:
                from .vision import _model_vision_mode_dual
                m = s._eff_model() or ""   # v3.5.128（全审P2）：恢复守卫语义——内存查到才不读盘
                mode = _model_vision_mode_dual(m, s.model)
            except Exception:
                m = ""
                mode = ""
        # v3.5.45（用户实锤「重启了还是显示 MCP，过一会才变」）：重启后后端
        # _sessions 内存为空（会话 lazy 建），?sid= 查不到 → mode 空 → 前端
        # 回退通用「已启用（MCP）」，等会话被别的调用 lazy 建后才纠正。
        # 回退读落盘 meta（claude_harness.json 的 live_model/model）——重启
        # 丢失的只是内存，档位事实在盘上
        if not m:
            try:
                meta = json.load(open(os.path.join(
                    os.path.expanduser("~"), ".serialconsole_pro",
                    "claude_harness.json"), encoding="utf-8"))
                mm = meta.get(sid) or {}
                m = (mm.get("live_model") or "").strip()
                mc = (mm.get("model") or "").strip()
                if m or mc:
                    from .vision import _model_vision_mode_dual
                    mode = _model_vision_mode_dual(m, mc)
            except Exception:
                pass
    return jsonify({"ok": True, "enabled": bool(cfg["enabled"]),
                    "name": cfg["name"], "model": cfg["model"],
                    "mode": mode,
                    "alive": False, "busy": False, "needed": False,
                    "sid": "", "last_seq": 0, "recent": [], "busy_since": None,
                    "last_done": 0, "last_brief": ""})

# ---- from claude_harness.py:3786 (harness_get_prompt) ----


@harness_bp.route("/system_prompt", methods=["GET"])
def harness_get_prompt():
    """读用户自定义提示词条目列表（v2.8 多条目；?cwd= 时附带每条 active 计算）。
    旧单条 harness_system_prompt 自动迁移成一条 global 条目（一次性）。"""
    items = _prompts_load()
    if not items:
        # 旧版单条迁移（一次性）：写过 v2.4 单条提示词的机器升级后无缝接续。
        # v3.4.54：先前是 _prompts_save 再整写一遍（自身双写竞态），合并为
        # 一次 cfg_commit 事务
        try:
            def _migrate(d):
                legacy = d.get(_PROMPTS_LEGACY_KEY)
                if not (isinstance(legacy, str) and legacy.strip()):
                    return
                d[_PROMPTS_KEY] = [{"id": "migrated-legacy", "scope": "global",
                                    "project": "", "note": "（v2.4 迁移）",
                                    "text": legacy.strip(), "enabled": True}]
                d.pop(_PROMPTS_LEGACY_KEY, None)
            _st.cfg_commit(_migrate)
            items = _prompts_load()
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

# ---- from claude_harness.py:3821 (harness_set_prompt) ----


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

# ---- from claude_harness.py:3849 (harness_mm_probe) ----


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
    # merge 落盘（不整键替换，别把并发写进来的其他字段冲掉）。
    # v3.4.54：改走 cfg_commit 原子事务（五写方统一锁）
    def _probe_cache(d):
        v = d.get(_VISION_KEY)
        if not isinstance(v, dict):
            v = {}
        p = v.get("mm_probed")
        if not isinstance(p, dict):
            p = {}
        p[pkey] = (mode == "inline")   # 仅 inline 记 True；False = 走 MCP 通道
        v["mm_probed"] = p
        d[_VISION_KEY] = v
    _st.cfg_commit(_probe_cache)
    # 名单归位：inline → mm_extra（真多模态 👁 名单）；mcp 无需名单（默认态）
    if mode == "inline":
        cfg = _vision_load()
        lname = model.lower()
        if not any(lname == (x or "").lower() or lname.startswith((x or "").lower() + "[")
                   for x in cfg["mm_extra"]):
            cfg["mm_extra"] = list(cfg["mm_extra"]) + [model]
            _vision_save(cfg)
    return jsonify({"ok": True, "model": model, "mode": mode, "msg": msg})

# ---- from claude_harness.py:3902 (harness_get_vision) ----


@harness_bp.route("/vision", methods=["GET"])
def harness_get_vision():
    """读识图配置（v2.28.2：MCP 后端配置——模型/提示词）。
    附带 defaults 供前端「恢复默认」按钮用（mcp_prompt 缺省取 MCP 内置）。
    v3.5.19：model_map 端点映射退役（用户拍板「完全由用户选择多模态模型
    配置」）——识图模型就是面板主选择框那一个。"""
    from .vision_mcp import MCP_DEFAULT_SYSTEM
    cfg = _vision_load()
    return jsonify({"ok": True, "vision": cfg,
                    "defaults": {"mcp_prompt": MCP_DEFAULT_SYSTEM},
                    "running": False,
                    "models": available_models().get("models", []),
                    "default_model": available_models().get("default")})

# ---- from claude_harness.py:3916 (harness_set_vision) ----


@harness_bp.route("/vision", methods=["POST"])
def harness_set_vision():
    """写识图配置。body: {enabled, model, mcp_prompt?, mm_extra?}。
    v2.28.2：配置即 MCP 行为——MCP 每次调用时读盘，改完即刻生效，无需
    重启会话。旧键 prompt/name（会话时代）不再写入，存量值自然闲置。
    v3.5.19：model_map 端点映射退役——不再收不再存，存量值自然闲置。"""
    data = request.get_json(force=True, silent=True) or {}
    # v3.5.102：空 body 防御（用户实锤「识图配置自己关闭」——冒烟测试对
    # 本路由发空探测请求，enabled 落默认 False 写进真实 config 并被 v3.5.101
    # 的快照同步放大进方案快照，用户开启的配置被探测打回关闭态）。对齐
    # /roles 的「没有可写入的配置项」口径：body 里一个有效键都没有 → 400
    # 拒写，任何探测/误调用都不再落默认值。
    if not any(k in data for k in ("enabled", "model", "mcp_prompt",
                                   "base_url", "api_key",
                                   "mm_extra", "mm_user")):
        return jsonify({"ok": False, "err": "没有可写入的配置项"}), 400
    old = _vision_load()
    cfg = {
        "enabled": bool(data.get("enabled", False)),
        "model": str(data.get("model") or "").strip(),
        "mcp_prompt": str(data.get("mcp_prompt") or "").strip(),
        # v3.5.86：识图专用端点/密钥（内网/自建网关——用户实锤内网 lanzi
        # 机器落不到 settings.json，主端点恒为智谱兜底=连接拒绝）
        "base_url": str(data.get("base_url") or "").strip(),
        "api_key": str(data.get("api_key") or "").strip(),
    }
    # v2.25：mm_extra（多模态手补名单）随保存一起落盘——旧实现重建 cfg 时
    # 没带这个字段，_vision_save 整体覆盖后用户配过的名单被静默清空
    mm = data.get("mm_extra")
    if isinstance(mm, list):
        cfg["mm_extra"] = [str(x).strip() for x in mm if str(x).strip()]
    else:
        cfg["mm_extra"] = list(old.get("mm_extra") or [])
    # v3.5.31：mm_user（用户人工判定表 {模型名: bool}）——最高优先级压过
    # 探测缓存/正则/名单（用户实锤「探测抽风把多模态判 false，眼见为实优先」）。
    # 未提交保旧值；提交则整表替换（面板是全量表编辑）
    mu = data.get("mm_user")
    if isinstance(mu, dict):
        cfg["mm_user"] = {str(k).strip().lower(): bool(v)
                          for k, v in mu.items() if str(k).strip()}
    else:
        cfg["mm_user"] = dict(old.get("mm_user") or {})
    ok, err = _vision_save(cfg)
    if not ok:
        return jsonify({"ok": False, "err": err or "写入失败"}), 500
    # v3.5.101：同步激活方案快照的识图用户配置子集（对称 harness_set_roles
    # 的 roles 同步——面板保存只写 config，快照不跟的话来回切方案时 apply
    # 用旧值写回，改动被打回）。失败不阻断保存——sync_err 带回前端告警。
    try:
        from ..claude_default import sync_active_profile_vision
        _vn = sync_active_profile_vision()
        if _vn:
            cfg["synced"] = _vn
    except Exception as _e:
        cfg["sync_err"] = "方案快照同步失败：%s——切方案可能还原本次修改" % _e
    return jsonify({"ok": True, "vision": cfg})



# ---- from claude_harness.py:3972 (harness_roles_info) ----


@harness_bp.route("/version")
def harness_version():
    """harness 版本下发（v3.5.0+ 与工具版本分离）：单一源 src.harness.
    HARNESS_VERSION；同时带工具发版版本（APP_VERSION）供前端一并显示，
    两条版本线互不牵连。"""
    from . import HARNESS_VERSION
    try:
        from src.version import APP_VERSION
    except Exception:
        APP_VERSION = ""
    return jsonify({"ok": True, "harness": HARNESS_VERSION,
                    "app": APP_VERSION})


@harness_bp.route("/roles")
def harness_roles_info():
    """角色设计说明（/roles 命令数据源）。resolved 是按当前 API 方案解析
    出的实际模型（换方案自动适配）：light/mid/heavy=三档（v3.5.0 三档
    形态判定源；mid 缺省=重档同值但形态判定按中档跑），designer/reviewer=
    设计者/审计者各自实际用的模型（显式优先，缺省回退重档）。
    mode——当前形态（v3.5.0 三档精确匹配：实跑模型名归一化后命中哪档
    即哪形态；light 轻主力直干+双代理 / mid 中主力直干+审核兜底 / heavy
    最信任档直干+派发自由零强制；未匹配兜 mid）。roles 为配置全量（含遗留键透传）；
    附 models/default_model 供配置面板下拉用。"""
    from .roles import (resolve_tier_models, resolve_agent_models,
                                roles_cfg, roles_mode)
    li, mi, hv = resolve_tier_models()
    dmr, rmr = resolve_agent_models()
    # v3.5.3（用户实锤「用 glm-5.3 显示轻主力」）：mode 判定对象错位——旧
    # 取方案默认模型，会话实跑与 default 不同时显示与行为分裂（引导词/
    # agents 安装走实跑是对的）。带 sid 且会话在跑：按 _eff_model（CLI
    # 实报名优先）判定；无 sid/找不到会话回退方案默认
    _eff = None
    _sid = str(request.args.get("sid") or "").strip()
    if _sid:
        from .consts import _sessions
        s = _sessions.get(_sid)
        if s:
            try:
                _eff = s._eff_model()
            except Exception:
                _eff = None
    try:
        mode = roles_mode(_eff or available_models().get("default"))
    except Exception:
        mode = "mid"
    return jsonify({"ok": True, "roles": roles_cfg(), "mode": mode,
                    "resolved": {"light": li, "mid": mi, "heavy": hv,
                                 "designer": dmr, "reviewer": rmr},
                    "models": available_models().get("models", []),
                    "default_model": available_models().get("default")})

# ---- from claude_harness.py:3997 (harness_agent_models) ----


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

# ---- from claude_harness.py:4035 (harness_set_roles) ----


@harness_bp.route("/roles", methods=["POST"])
def harness_set_roles():
    """开关 + 整节配置（merge 写盘，只动出现的键）。body 可含 {enabled,
    designer_model, reviewer_model, light_model, mid_model, heavy_model,
    audit_mode, l1_max_lines, l2_max_files,
    l2_max_lines, design_max_lines}
    （v3.5.0 三档化：mid_model 新键；main_model/light_keywords 已退役，
    旧前端再 POST 这两键会被白名单静默忽略不落盘；v3.5.18 model_map
    亦退役——识图端点映射走独立 /vision 端点写 harness_vision 节）
    （v2.53 设计者/审计者槽新键；旧键 executor_model/coder_model 仍被
    接受落盘——读取侧按池降级兼容）。生效路径与
    开关一致：模型池/分级线出现在引导词里 → 指纹热更下条消息换词重启
    + agents 重生成；audit_mode 在回合结算时读盘，即时生效。写盘前过
    clamp_role_limits 交叉校验 l1_max_lines ≤ l2_max_lines（超线 clamp
    到 l2，不 400——回显在响应 clamped 键）。"""
    from .roles import update_roles_cfg, clamp_role_limits, roles_cfg
    data = request.get_json(force=True, silent=True) or {}
    patch = {}
    if "enabled" in data:
        patch["enabled"] = bool(data.get("enabled"))
    for k in ("designer_model", "reviewer_model", "light_model",
              "mid_model", "heavy_model",
              "executor_model", "coder_model"):
        if k in data:
            patch[k] = str(data.get(k) or "").strip()
    if "audit_mode" in data:
        # v2.34.1：出现但不合法 → 400（与分级线口径一致——静默
        # 跳过会让调用方假成功，配置面板显示的与实际生效的不符）
        if data.get("audit_mode") not in ("auto", "warn", "off"):
            return jsonify({"ok": False,
                            "err": "audit_mode 须为 auto/warn/off"}), 400
        patch["audit_mode"] = data.get("audit_mode")
    # v2.49 分级线三键（取代 max_free_lines）：0 合法（最严档），非法 → 400
    # v2.54 增 design_max_lines（设计线，0=不强制设计，语义与其余线相反）
    for _k, _hi in (("l1_max_lines", 100000), ("l2_max_files", 1000),
                    ("l2_max_lines", 100000), ("design_max_lines", 100000)):
        if _k in data:
            try:
                patch[_k] = max(0, min(_hi, int(data.get(_k))))
            except (TypeError, ValueError):
                return jsonify({"ok": False,
                                "err": "%s 须为数字" % _k}), 400
    # v3.5.18（全审建议）：model_map 解析删除——三角色判定已退役该键
    # （v3.5.15），识图配置走独立 /vision 端点写 harness_vision 节，本
    # 端点收 model_map 只会写进无人读的 harness_roles.model_map（死键）
    if not patch:
        return jsonify({"ok": False, "err": "没有可写入的配置项"}), 400
    # l1 ≤ l2l 交叉校验（clamp 档）——只对本次涉及的键生效，
    # 未涉及的键取盘上现值参与比较（单独调低 l2 也会把现存 l1 带下来）。
    # 放在 update_roles_cfg 之前钳 patch，响应回显的就是实际写盘值（配置
    # 面板显示的与实际生效的必须一致——v2.34 就防的坑）。
    patch, clamped = clamp_role_limits(patch, roles_cfg())
    ok, err = update_roles_cfg(patch)
    if not ok:
        return jsonify({"ok": False, "err": err or "写入失败"}), 500
    resp = {"ok": True}
    resp.update(patch)
    if clamped:
        resp["clamped"] = clamped
    # v3.5.99：同步激活方案快照的 harness_roles 节——面板改三角色只写
    # config.json，快照不跟的话来回切 API 方案时 apply 用旧节写回，改动
    # 被打回（与设置页「保存配置」同病同修）。失败不阻断保存——sync_err
    # 带回前端告警。
    try:
        from ..claude_default import sync_active_profile_roles
        _rn = sync_active_profile_roles()
        if _rn:
            resp["synced"] = _rn
    except Exception as _e:
        resp["sync_err"] = "方案快照同步失败：%s——切方案可能还原本次修改" % _e
    return jsonify(resp)

# ---- from claude_harness.py:4118 (harness_skills) ----


@harness_bp.route("/skills")
def harness_skills():
    """技能列表（复用 claude_sessions 发现层，harness 上下文 cwd）。
    v2.27：附带中文描述缓存（skill_zh_cache.json），前端「技能需要翻译」
    的持久层——静态映射未命中的英文 desc，由 /skill_zh/translate 落缓存。"""
    from ..claude_sessions import list_skills
    cwd = request.args.get("cwd") or None
    return jsonify({"ok": True, "skills": list_skills(cwd),
                    "zh": _skill_zh_load()})

# ---- from claude_harness.py:4133 (_skill_zh_load) ----


def _skill_zh_load():
    try:
        with open(_SKILL_ZH_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

# ---- from claude_harness.py:4142 (_skill_zh_save) ----


def _skill_zh_save(d):
    try:
        tmp = _SKILL_ZH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _SKILL_ZH_FILE)
    except OSError:
        pass

# ---- from claude_harness.py:4152 (_llm_cool_until) ----


_llm_cool_until = [0.0]     # 翻译失败冷却：网关故障/方案切换窗口期不反复白发请求

# ---- from claude_harness.py:4155 (_llm_translate_batch) ----


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
                 "anthropic-version": "2023-06-01",
                 # v4.0.1：内网 lanz 网关按 UA 白名单放行 Anthropic 协议
                 # （仅 claude-cli/*，Python-urllib 默认 UA 一律 403）
                 "User-Agent": "claude-cli/2.0.0 (external, cli)"})
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

# ---- from claude_harness.py:4212 (harness_skill_zh_translate) ----


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

# ---- from claude_harness.py:4239 (harness_files) ----


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

# ---- from claude_harness.py:4289 (harness_upload) ----


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
    # v3.5.92：附件落盘成功后节流触发目录清理（半年过期 + 1GB 上限，见
    # src/data_hygiene.py；10 分钟节流 + 异步，不阻塞上传响应）
    try:
        from src.data_hygiene import cleanup_throttled
        cleanup_throttled()
    except Exception:
        pass
    return jsonify({"ok": True, "path": path, "name": name, "size": len(raw)})

# ---- from claude_harness.py:4315 (harness_file) ----


@harness_bp.route("/file")
def harness_file():
    """附件原件（v2.19）。

    前端 chip 缩略图原先直接拿 upload 返回的**本地绝对路径**当 <img src>——
    http 页面加载不了 file:// 之外的盘符路径，结果是破图占位符叠一行文件名
    （用户看到的「🖼 2.png 2.png」）。改成前端用 /api/harness/file?name=，
    这里只读地回 _UPLOAD_DIR 里的原件。

    防穿越：只取 basename，再校验 realpath 落在 _UPLOAD_DIR 内。
    v3.2.14：补 path= 分支——贴图并名后附件路径指向 CLI 的 Temp images
    原件（原名 1.png；上传副本是 hash 名），按整路径回源。白名单两处：
    _UPLOAD_DIR 任意文件 + %TEMP%/claude/**/images/ 下的图片原件
    （realpath 包含校验 + 父目录名必须是 images + 图片扩展名）。
    """
    p = request.args.get("path")
    if p:
        rp = os.path.realpath(p)
        up_root = os.path.realpath(_UPLOAD_DIR) + os.sep
        if rp.startswith(up_root):
            return send_from_directory(_UPLOAD_DIR, os.path.basename(rp))
        tmp_root = os.path.realpath(os.path.join(tempfile.gettempdir(), "claude")) + os.sep
        _img_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        if (rp.startswith(tmp_root) and os.path.basename(os.path.dirname(rp)) == "images"
                and rp.lower().endswith(_img_ext) and os.path.isfile(rp)):
            return send_file(rp)
        # v3.5.136（用户实锤「拖拽进来的图片无法点击预览」）：拖拽文件来自
        # 任意盘（桌面/工程目录），不落在上面两处白名单——补第三条：图片
        # 扩展名 + 文件存在的任意路径直接回源。本机单用户工具，/api/read_text
        # 已有任意绝对路径读文本的先例（敏感面更大），图片白名单扩展名限死
        # 不放行脚本/文档，实质风险不新增
        # v3.5.256（用户需求）：图片扩展名但文件已不在 → 明确 404「不存在/
        # 已删除」（原落 403 非法路径=文案误导），前端 Lightbox 据此显示提醒
        if rp.lower().endswith(_img_ext):
            if os.path.isfile(rp):
                return send_file(rp)
            return jsonify({"ok": False, "err": "文件不存在或已删除：%s" % p}), 404
        return jsonify({"ok": False, "err": "非法路径"}), 403
    fn = os.path.basename((request.args.get("name") or "").replace("\\", "/"))
    if not fn:
        return jsonify({"ok": False, "err": "缺少 name"}), 400
    if os.path.realpath(os.path.join(_UPLOAD_DIR, fn)).startswith(
            os.path.realpath(_UPLOAD_DIR) + os.sep):
        return send_from_directory(_UPLOAD_DIR, fn)
    return jsonify({"ok": False, "err": "非法路径"}), 403
