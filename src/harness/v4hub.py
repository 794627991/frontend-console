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


def _ts_ms(v):
    """transcript 行 ts → epoch ms。ts 是 CLI jsonl 的 ISO-8601 字符串
    （transcript.py:268 直取 o['timestamp']），旧写法 int(x[:13]) 恒抛
    ValueError 回落 0——hydration 行全部无时刻，补放去重的末轮边界失效。
    与 subagent_projection._ts_ms 同款（ISO 优先、数字兜底）。"""
    import datetime
    s = str(v or "").strip()
    if not s:
        return 0
    try:
        return int(datetime.datetime.fromisoformat(
            s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return 0

_lock = threading.Lock()
_build_locks = {}           # sid -> 冷建串行锁（复审G1：并发冷建双喂防）
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
        blk = _build_locks.get(sid)
        if blk is None:
            blk = _build_locks[sid] = threading.Lock()
    if feed is not None and feed.epoch == s.log.epoch:
        return feed
    with blk:                            # 冷建串行（复审G1：并发冷建会双喂
        # 同一事件——先存者补放窗与后存者 live ingest 重叠=行双画）
        with _lock:
            feed = _main_feeds.get(sid)
        if feed is not None and feed.epoch == s.log.epoch:
            return feed                  # 双重检查：等锁期间他人已建好
        feed = F.V4Feed(epoch=s.log.epoch)
        h = s.log.last_seq               # hydration 水位（此刻账本已到的事件）
        _hydrate_main(feed, s)           # 转写全量打底（历史权威）
        if h > 0:
            try:
                feed._replay = True      # 补放期：与 hydration 重叠的行不重画
                for env in s.log.events_after(h):   # 只补水位后在飞事件
                    feed.ingest(env)
                feed._replay = False
            except Exception:
                feed._replay = False
                log.exception("v4 账本尾部补放失败 sid=%s", sid)
        with _lock:
            old = _main_feeds.get(sid)
            if old is None or old.epoch != s.log.epoch:
                _main_feeds[sid] = feed
                feed = _main_feeds[sid]
            else:
                feed = old               # 锁内仍撞（epoch 竞速）：保留先入者
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
            ts = _ts_ms(l.get("ts"))
            if turn_n == 0 and role != "user":
                # 开场非 user 行（sysnote/renew/开场白）归入 t1——先建 t1
                # header。否则该组无 turn_header（实测 a12：189 行挤无头组，
                # 前端把无头组当 running 渲染「工作中 6时2分」假秒表）
                turn_n = 1
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t1", "turn_header", ts, 0, state="success"))
                feed.snap["total"] += 1
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
        # 水位补放的去重键：hydration 已呈现的历史行不得被账本尾部补放重复
        # （rows 按 rowId 幂等，但 hydration 的行 rowId 与账本 delta 不是同一
        # 命名空间——用内容指纹兜底）
        try:
            feed._hydrated = True
            feed._hyd_keys = set(
                (r.get("kind"), (r.get("text") or "")[:200])
                for r in feed.snap["rows"])
            # 补放去重的单向上界：hydration 已呈现行的最大时刻
            feed._hyd_max_at = max(
                [int(r.get("at") or 0) for r in feed.snap["rows"]] or [0])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 子代理 feed
# ---------------------------------------------------------------------------

def v4_sub_feed(sid, agent_key, hydrate_paths=None):
    """子 feed 懒建：首次依序尝试 hydrate_paths（三源候选）全量重建。

    a56（用户实测「回放点开是空的」）：hydrate 颗粒无果（候选全 miss）时
    **不缓存**——空 feed 一旦缓存，此后 paths 修正也永远命中空实例（回放
    永远空白）。下次订阅携修正 paths 重试。"""
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
        if not feed.snap["rows"]:
            return feed          # 颗粒无果：不缓存（下次携修正 paths 重试）
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
