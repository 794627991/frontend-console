# -*- coding: utf-8 -*-
"""v4 feed 注册中心：主/子 feed 懒建、冷启动重建（账本重放或 transcript
hydration）、session.emit 与 watcher 的挂接桥。

初始化两路（对照 ZCode resume/snapshot 服务端单方裁决）：
- 账本有事件（live 会话/近期）→ store.events_after(0) 逐条 ingest 重放——
  seq 连续，与后续 live 事件无缝（同源同序，无落盘滞后竞态）。
- 账本空（后端重启/旧会话冷开）→ transcript_for lines hydration 重建行
  （历史全终态；此后新事件按账本新序接续，无旧 live 残留）。

子 feed：agentKey 懒建，首次从子代理转写候选路径全量 hydrate；watcher
扫到增量行继续喂（feed_jsonl_line）。子投影与主投影同协议同模型——
子 pane 与主窗口同一条消费管线。

挂接纪律（404 精神）：ingest 只在两处——session.emit（主）与
watcher/sub 路由（子），新增触发点必须经 v4hub，禁止绕过直调 feed。
"""
import threading

from . import v4feed as F
from .consts import _sessions, _sessions_lock, log

_lock = threading.Lock()
_main_feeds = {}            # sid -> V4Feed
_sub_feeds = {}             # (sid, agentKey) -> V4Feed


def v4_main_feed(s):
    """主 feed 懒建（feed 与 session 同生命周期；epoch 跟随账本）。

    初始化（ZCode transcript-hydration 对位）：**transcript hydration 永远
    打底**（CLI 落盘转写是历史权威），账本只补「取水位时刻之后」的在飞事件
    ——重启后账本恢复 seq 水位但事件体不在（实测 v4.0.0-a6 白屏根因：
    `last_seq>0` 误判为完整账本走重放，投影只剩当前 turn）。"""
    sid = s.session_id
    with _lock:
        feed = _main_feeds.get(sid)
    if feed is not None and feed.epoch == s.log.epoch:
        return feed
    feed = F.V4Feed(epoch=s.log.epoch)
    h = s.log.last_seq                   # hydration 水位（此刻账本已到的事件）
    _hydrate_main(feed, s)               # 转写全量打底（历史权威）
    if h > 0:
        try:
            for env in s.log.events_after(h):   # 只补水位后在飞事件（不重复）
                feed.ingest(env)
        except Exception:
            log.exception("v4 账本尾部补放失败 sid=%s", sid)
    with _lock:
        old = _main_feeds.get(sid)
        if old is None or old.epoch != s.log.epoch:
            _main_feeds[sid] = feed
            feed = _main_feeds[sid]
        else:
            feed = old                   # 并发建窗：保留先入者（幂等）
    return feed


def v4_ingest_main(s, env):
    """session.emit 挂接（store 落账之后调用——persist-before-publish）。"""
    try:
        v4_main_feed(s).ingest(env)
    except Exception:
        log.exception("v4 ingest main 失败 sid=%s seq=%s",
                      getattr(s, "session_id", "?"), env.get("seq"))


def v4_drop_main(sid):
    with _lock:
        _main_feeds.pop(sid, None)


def _hydrate_main(feed, s):
    """transcript_for lines → 行（历史全终态；sub_* 段不进主投影——
    子内容走子 pane 是红线）。user 行开新轮。"""
    from .transcript import transcript_for
    try:
        lines = transcript_for(s)
    except Exception:
        log.exception("v4 hydrate main 失败 sid=%s", s.session_id)
        return
    if not lines:
        return
    with feed._lock:
        turn_n = 0
        for l in lines:
            role = l.get("role")
            ts = 0
            try:
                ts = int(str(l.get("ts") or "")[:13] or 0)
            except Exception:
                ts = 0
            if role == "user":
                turn_n += 1
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % turn_n, "turn_header", ts, 0,
                    state="success"))
                feed.snap["total"] += 1
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % turn_n, "user_input", ts, 0,
                    text=l.get("text") or "", files=l.get("files") or [],
                    images=l.get("images") or 0))
                feed.snap["total"] += 1
            elif role == "assistant":
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % max(turn_n, 1), "assistant_text",
                    ts, 0, text=l.get("text") or "", model=l.get("model") or ""))
                feed.snap["total"] += 1
            elif role == "thinking":
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % max(turn_n, 1), "reasoning",
                    ts, 0, text=l.get("text") or ""))
                feed.snap["total"] += 1
            elif role == "tool":
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % max(turn_n, 1), "tool_call", ts, 0,
                    tool=l.get("text") or "", status="success",
                    summary=l.get("summary") or "", input=l.get("input") or "",
                    output=l.get("result") or "", tid=l.get("tid") or ""))
                feed.snap["total"] += 1
            elif role in ("renew", "sysnote", "audit", "exit"):
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "", "marker", ts, 0, mkind=role,
                    text=l.get("text") or ""))
                feed.snap["total"] += 1
            elif role == "peer":
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "", "peer_notify", ts, 0,
                    title=l.get("title") or "协作回传",
                    brief=l.get("brief") or ""))
                feed.snap["total"] += 1
            elif role == "vision_relay":
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % max(turn_n, 1), "vision", ts, 0,
                    prompt=l.get("prompt") or "", src=l.get("src") or "",
                    chan=l.get("chan") or "", tid=l.get("tid") or "",
                    dur=l.get("dur") or 0, status="done"))
                feed.snap["total"] += 1
            # sub_open/sub_text/... 不进主投影（红线：子内容只在子 pane）


# ---------------------------------------------------------------------------
# 子代理 feed
# ---------------------------------------------------------------------------

def v4_sub_feed(sid, agent_key, hydrate_paths=None):
    """子 feed 懒建：首次依序尝试 hydrate_paths（三源候选）全量重建。"""
    key = (sid, agent_key)
    with _lock:
        feed = _sub_feeds.get(key)
        if feed is not None:
            return feed
    feed = F.V4Feed(epoch="sub")
    if hydrate_paths:
        for p in hydrate_paths:
            if p and feed.hydrate_jsonl(p):
                break
    with _lock:
        got = _sub_feeds.setdefault(key, feed)
        return got


def v4_sub_ingest(sid, agent_key, obj):
    """watcher 增量行喂入（缺 feed 时静默——未订阅的子代理不建投影）。"""
    with _lock:
        feed = _sub_feeds.get((sid, agent_key))
    if feed is None:
        return False
    try:
        return feed.feed_jsonl_line(obj)
    except Exception:
        log.exception("v4 sub ingest 失败 %s/%s", sid, agent_key)
        return False


def v4_drop_sub(sid, agent_key=None):
    with _lock:
        if agent_key is None:
            for k in list(_sub_feeds):
                if k[0] == sid:
                    _sub_feeds.pop(k, None)
        else:
            _sub_feeds.pop((sid, agent_key), None)


def v4_drop_session(sid):
    """会话删除/回收时清全部 feed。"""
    v4_drop_main(sid)
    v4_drop_sub(sid)


def v4_session_for(sid):
    with _sessions_lock:
        return _sessions.get(sid)
