# -*- coding: utf-8 -*-
"""事件 → 会话投影的纯函数归约（v3.0，对照 ZCode event-reducer.ts:74-160）。

纪律（AGENTS 同款）：状态唯一所有者——projection 只由事件流归约得到，
live / 重放 / 快照共用同一函数；reducer 内不改输入对象（纯函数，replay
与 live 共用无副作用）；未知事件类型只 bump updated_at（前向兼容：旧
消费端读新事件流不崩）。

本期落地范围：服务端投影（busy/turn 计数/最近错误）作为散落 busy 旗的
「对照真相」供 /events 与测试校验；前端 handleEvent 的 500 行分派迁移
成 reducer handler 是后续迁移项（信封已统一，迁移是搬运不是重构）。
"""
from .types import SessionEventType, type_for_kind


def initial_projection(sid):
    import time
    return {"sid": sid, "status": "idle", "turn": None, "turn_count": 0,
            "last_error": None, "last_seq": 0, "updated_at": int(time.time() * 1000),
            # v3.1（#12/#10）：镜像事件与账本事件的投影——live/重放共用
            "agents": {},            # tid -> {type,desc,bg,done,err,tokens,tool_n}
            "inbox": [],             # 待发输入（durable 账本投影）
            "turn_tools": _empty_tools(),   # 当前回合工具计数（回合摘要行用）
            "tools_total": _empty_tools()}   # 会话累计


_TOOL_READ = ("Read", "NotebookEdit")
_TOOL_SEARCH = ("Grep", "Glob", "WebSearch", "WebFetch", "TodoRead")
_TOOL_EDIT = ("Edit", "MultiEdit", "Write", "NotebookEdit")


def _empty_tools():
    return {"calls": 0, "reads": 0, "searches": 0, "edits": 0, "bash": 0, "agents": 0}


def _tally_tools(bucket, name):
    bucket["calls"] += 1
    if name in _TOOL_READ:
        bucket["reads"] += 1
    if name in _TOOL_SEARCH:
        bucket["searches"] += 1
    if name in _TOOL_EDIT:
        bucket["edits"] += 1
    if name in ("Bash",):
        bucket["bash"] += 1
    if name in ("Task", "Agent"):
        bucket["agents"] += 1


def apply_event(proj, ev):
    """(projection, event) -> 新 projection。纯函数。"""
    import time
    p = dict(proj)
    p["updated_at"] = int(time.time() * 1000)
    if ev.get("seq"):
        p["last_seq"] = max(p.get("last_seq", 0), ev["seq"])
    # type 优先；裸 kind（无信封的存量事件/测试直喂）按映射表归一——
    # 老事件流（无 turn_* 事件的会话重放）也能归约出 running/idle
    t = ev.get("type") or type_for_kind(ev.get("kind"))
    if t == SessionEventType.TURN_STARTED:
        p["turn"] = ev.get("turn")
        p["turn_count"] = p.get("turn_count", 0) + 1
        p["status"] = "running"
        p["last_error"] = None          # 源头清理：新 turn 清旧错误
        p["turn_tools"] = _empty_tools()   # 回合计数随回合开窗
    elif t in (SessionEventType.TURN_COMPLETE, SessionEventType.TURN_ERROR):
        p["turn"] = None
        p["status"] = "idle"
        if t == SessionEventType.TURN_ERROR:
            p["last_error"] = (ev.get("text") or "turn aborted")[:200]
        else:
            # 摘要定格：上一回合的工具构成随事件快照（面板/摘要行重放可用）
            p["last_turn_tools"] = dict(p.get("turn_tools") or _empty_tools())
    elif t == SessionEventType.SUBAGENT_STARTED:
        ag = dict(p.get("agents") or {})
        ag[str(ev.get("tid") or "")] = {
            "type": ev.get("agent_type") or "Task", "desc": ev.get("desc") or "",
            "bg": bool(ev.get("bg")), "task_id": ev.get("task_id") or "",
            # v3.5.315：起跑时刻进投影（信封 ts）——前端刷新/切会话后从
            # proj 真源重建运行中档案时秒表不归零（此前前端只能拿「重建
            # 时刻」近似，长跑代理时长凭空缩水）
            "t0": ev.get("ts") or 0,
            "done": False, "err": False, "tokens": 0, "tool_n": 0}
        p["agents"] = ag
    elif t == SessionEventType.SUBAGENT_RESULT:
        ag = dict(p.get("agents") or {})
        cur = ag.get(str(ev.get("tid") or ""))
        if cur is not None:
            nxt = dict(cur)
            # v4.0.4：被停≠失败——stopped 单独记旗，不置 err（用户主动
            # 停止画红叉是错的；err 只留给真失败）
            _stopped = bool(ev.get("stopped"))
            nxt.update({"done": True,
                        "stopped": _stopped,
                        "err": (not bool(ev.get("ok", True))) and not _stopped,
                        "tokens": ev.get("tokens") or nxt.get("tokens") or 0,
                        "tool_n": ev.get("tool_n") or nxt.get("tool_n") or 0,
                        "brief": (ev.get("brief") or "")[:200]})
            ag[str(ev.get("tid"))] = nxt
            p["agents"] = ag
    elif t == SessionEventType.INPUT_ADMITTED:
        box = list(p.get("inbox") or [])
        box.append({"id": ev.get("id"), "text": ev.get("text") or "",
                    "gen": ev.get("gen") or 0})
        p["inbox"] = box
    elif t == SessionEventType.INPUT_PROMOTED:
        _eid = ev.get("id")
        p["inbox"] = [x for x in (p.get("inbox") or []) if x.get("id") != _eid]
    elif t == SessionEventType.INPUT_DISCARDED:
        _eid = ev.get("id")
        p["inbox"] = [x for x in (p.get("inbox") or []) if x.get("id") != _eid]
    elif t == SessionEventType.USER_ECHO:
        # 老事件流（无 turn_* 事件的存量会话重放）也能归约出 running
        if p["status"] == "idle":
            p["status"] = "running"
    elif t == SessionEventType.CLI_STREAM:
        d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if d.get("type") == "result" and p["status"] == "running":
            p["turn"] = None
            p["status"] = "idle"
        elif d.get("type") == "system" and d.get("subtype") == "api_error":
            p["last_error"] = str(d.get("message") or "api_error")[:200]
        elif d.get("type") == "assistant" and not d.get("parent_tool_use_id"):
            # 主链工具调用计数（回合摘要行「查阅 · N 搜索 · N 文件」的数据源；
            # 子代理内部调用不计——它是子代理自己的过程，不是主回合动作）
            _c = d.get("message", {}).get("content")
            if isinstance(_c, list):
                tt = dict(p.get("turn_tools") or _empty_tools())
                tot = dict(p.get("tools_total") or _empty_tools())
                for b in _c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        _tally_tools(tt, str(b.get("name") or ""))
                        _tally_tools(tot, str(b.get("name") or ""))
                p["turn_tools"] = tt
                p["tools_total"] = tot
    elif t == SessionEventType.INTERRUPTED:
        p["turn"] = None
        p["status"] = "idle"
        p["last_error"] = "interrupted"
    elif t == SessionEventType.EXIT:
        p["turn"] = None
        p["status"] = "idle"
    return p


def reduce_events(sid, events):
    """整段归约（冷重建/测试用）。"""
    p = initial_projection(sid)
    for ev in events:
        p = apply_event(p, ev)
    return p
