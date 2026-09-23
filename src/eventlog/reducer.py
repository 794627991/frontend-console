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
            "last_error": None, "last_seq": 0, "updated_at": int(time.time() * 1000)}


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
    elif t == SessionEventType.TURN_COMPLETE:
        p["turn"] = None
        p["status"] = "idle"
    elif t == SessionEventType.TURN_ERROR:
        p["turn"] = None
        p["status"] = "idle"
        p["last_error"] = (ev.get("text") or "turn aborted")[:200]
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
