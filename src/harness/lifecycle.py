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
        s.scheme = m.get("scheme") or None           # v3.5.98：方案名跨 GC/重启保留
        # v2.35.2：事件序号续号；v3.0 连代际一起续——GC 重建不是日志重写，
        # epoch 不变，前端旧 base 仍可 resume；无 epoch 的旧 meta（升级前
        # 落盘）→ restore 内部换新代，前端旧水位作废走一次 snapshot 重建
        s.log.restore(m.get("epoch"), m.get("seq"), m.get("wseq"))
        # v3.1（#10/#14）：durable 输入账本跨 GC/重启恢复——挂起条目在新对象
        # 里续命，回合终结泵自然接手；世代号一并续（rewind 作废判定不因重建
        # 失忆）。条目结构向后兼容（无 id 的旧数据丢弃）
        s._inbox = [dict(e) for e in (m.get("inbox") or []) if isinstance(e, dict)]
        s._gen = int(m.get("gen") or 0)
        _sessions[sid] = s
        # v3.5.158：monitor 常驻线程随重建拉起——v3.5.154 把孤儿 hold 对账
        # 挂在 _bg_monitor 巡检里，但 ensure 的唯一调用点在 bg 登记路径
        # （重启后的孤儿会话在新进程里没跑过带后台任务的回合=无线程=30s
        # 自行对账声称落空）。重建即拉起，孤儿 30s 内自动解锁成真。
        try:
            s._bg_monitor_ensure()
        except Exception:
            pass
        return s

# ---- from claude_harness.py:2164 (_gc_loop) ----


def _gc_loop():
    """闲置回收：活进程闲置超阈 kill（元数据/缓冲保留）。60s 一轮，daemon。
    v2.14：识图会话不参与回收——它是常驻配角，被回收后主会话发消息会
    突然找不到人（peer 名字消失）；顺带这轮把它救活。
    内存批（用户定调「可点开 ≠ 永久驻留」）：闲置会话的三份重缓冲在此
    延迟回收——① v4 投影 feed（v4hub.v4_reap_idle，无订阅者 + 宽限无
    落账才收，重开走既有冷建链）② readmodel 事实表（真源=磁盘，下次
    /agents 冷重建——冷查询设计本义，跨会话不再累积全文）。"""
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
            # ① v4 feed 闲置回收（订阅者在场/活跃 feed 恒受保护）
            try:
                from . import v4hub
                v4hub.v4_reap_idle()
            except Exception:
                pass
            # ② readmodel：进程已死或不活、且不再 busy 的会话回收，另加
            # 新鲜度护栏（对抗审 B-P2：用户停留查看已结束会话的目录时，
            # /agents 轮询还在打 model——刚刷过的（<10 分钟）不收，防
            # 「每 60s 丢一次缓存→下轮轮询全量重扫 55MB」的循环；
            # 真闲置的模型无人刷，照收不误）
            try:
                from .subagent_readmodel import _models, _models_lock
                _now_s = time.time()
                with _models_lock:
                    for s in objs:
                        if getattr(s, "is_vision", False) \
                                or getattr(s, "hidden", False):
                            continue
                        if s.busy or s.alive:
                            continue
                        _sid = getattr(s, "sid", None)
                        _m = _models.get(_sid)
                        if _m is not None and _now_s - getattr(
                                _m, "_last_refresh_at", 0.0) < 600.0:
                            continue
                        _models.pop(_sid, None)
            except Exception:
                pass
        except Exception:
            pass

# ---- from claude_harness.py:2189 (_ensure_gc) ----


def _ensure_gc():
    global _gc_started
    if not _gc_started:
        _gc_started = True
        threading.Thread(target=_gc_loop, daemon=True).start()
        try:
            from .subagent_watch import ensure_started as _sub_watch_start
            _sub_watch_start()   # 405 批A：子代理转写 watcher（delta 推送，ZCode subscribe 对位）
        except Exception:
            pass

# （_peer_poll_loop 回传兜底轮询已随批G 退役：v4 下无旧 SSE 订阅者，循环
#  恒空转；peer 回传由 session reader 路径 _check_peer_lines 覆盖）
