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
        # v2.35.2：事件序号续号；v3.0 连代际一起续——GC 重建不是日志重写，
        # epoch 不变，前端旧 base 仍可 resume；无 epoch 的旧 meta（升级前
        # 落盘）→ restore 内部换新代，前端旧水位作废走一次 snapshot 重建
        s.log.restore(m.get("epoch"), m.get("seq"))
        # v3.1（#10/#14）：durable 输入账本跨 GC/重启恢复——挂起条目在新对象
        # 里续命，回合终结泵自然接手；世代号一并续（rewind 作废判定不因重建
        # 失忆）。条目结构向后兼容（无 id 的旧数据丢弃）
        s._inbox = [dict(e) for e in (m.get("inbox") or []) if isinstance(e, dict)]
        s._gen = int(m.get("gen") or 0)
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
                    # v3.0 收编后 s.clients/clients_lock 已随 SSE 改造退役——
                    # 旧引用 AttributeError 被下面 except 吞成 watching=False，
                    # 轮询兜底整体死路（peer 回传静默丢失）。改问 bus 订阅者
                    watching = s.log.bus.has_subscribers()
                except Exception:
                    watching = False
                if not watching:
                    continue
                # 有事件缓冲序列号，前端重连时用 after_seq 续传不丢
                s._check_peer_lines()
        except Exception:
            pass
