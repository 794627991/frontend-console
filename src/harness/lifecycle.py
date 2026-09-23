# -*- coding: utf-8 -*-
"""harness.lifecycle —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import threading
import time
import logging
log = logging.getLogger(__name__)
from .consts import _IDLE_KILL_S, _sessions, _sessions_lock
from .meta import _meta, _meta_load
from .session import HarnessSession


# ---- from claude_harness.py:2141 (_gc_started) ----
_gc_started = False

# ---- from claude_harness.py:2142 (_get_or_create) ----


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

# ---- from claude_harness.py:2164 (_gc_loop) ----


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
        except Exception:
            pass

# ---- from claude_harness.py:2189 (_ensure_gc) ----


def _ensure_gc():
    global _gc_started
    if not _gc_started:
        _gc_started = True
        threading.Thread(target=_gc_loop, daemon=True).start()
        threading.Thread(target=_peer_poll_loop, daemon=True).start()

# ---- from claude_harness.py:2197 (_peer_poll_loop) ----


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
