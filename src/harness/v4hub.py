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
import json
import os
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
# a74：子订阅意向表（FIFO 512）——watcher 按需 hydrate 的闸原本只认主 feed
# 在场，子 pane 先于主窗订阅/主 store 断连窗口期=闸死（转写出现也无人建
# feed，孤儿永不愈）。/v4/stream sub 订阅即登记，与主 feed 等价放行
_sub_wanted = []            # [(sid, agentKey), ...]


def v4_sub_want(sid, agent_key):
    """子 feed 订阅意向登记（/v4/stream sub 分支调用）。"""
    with _lock:
        key = (sid, agent_key)
        if key in _sub_wanted:
            return
        _sub_wanted.append(key)
        while len(_sub_wanted) > 512:
            _sub_wanted.pop(0)


def v4_sub_wanted_has(sid, agent_key):
    with _lock:
        return (sid, agent_key) in _sub_wanted


def v4_main_feed(s):
    """主 feed 懒建（feed 与 session 同生命周期；epoch 跟随账本）。

    初始化（ZCode transcript-hydration 对位）：**transcript hydration 永远
    打底**（CLI 落盘转写是历史权威），账本只补「取水位时刻之后」的在飞事件
    ——重启后账本恢复 seq 水位但事件体不在（实测 v4.0.0-a6 白屏根因：
    `last_seq>0` 误判为完整账本走重放，投影只剩当前 turn）。

    a83（用户实锤「新会话一直工作中、主窗什么都不显示，后台代理却在跑」）：
    缓存键必须用 **harness sid（s.sid）**，绝不能用 `s.session_id`（claude
    uuid）——新会话首回合 session_id 从 None 被 CLI 首个 system/init 换成
    真 uuid（session.py:1590），键一换 ingest 冷建新 feed 进注册表，用户
    已绑定的旧键 feed 成孤儿（页面的 SSE gen 循环还挂着它：ka 心跳照跳、
    帧永远没有，判死/重连全不触发=主窗永久冻结，刷新才拿到新键 feed 的
    全量快照假愈）。子 feed 键（v4_sub_*）同批换 s.sid。"""
    sid = s.sid
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
        try:
            _reconcile_live(feed, s)     # a82：在飞回合状态对账（busy/组头/hold）
        except Exception:
            log.exception("v4 冷建对账失败 sid=%s", sid)
        with _lock:
            old = _main_feeds.get(sid)
            # a62（用户实测致命「子页开着主窗历史全消失」）：hydration 零产出
            # 且账本有历史（last_seq>0）=定位失败——空投影**不缓存**（否则
            # 此后每次重连都发空 snapshot，前端整窗重建把主窗抹成空白）。
            # 本次请求仍返回（前端有空快照防御），下次冷建重试 hydration
            if not feed.snap["rows"] and (s.log.last_seq or 0) > 0:
                log.warning("v4 主投影 hydration 零产出(不缓存) sid=%s seq=%s",
                            sid, s.log.last_seq)
                return feed
            if old is None or old.epoch != s.log.epoch:
                _main_feeds[sid] = feed
                feed = _main_feeds[sid]
            else:
                feed = old               # 锁内仍撞（epoch 竞速）：保留先入者
    return feed


def _reconcile_live(feed, s):
    """a82（用户实测「新会话一直在工作中、主窗却定稿折叠成『已工作 22 分
    13 秒』」）：冷建后与 session 真源对账，回填在飞回合的投影状态。

    根因：turn_started/turn_hold 是 harness 自产事件，**永不落 CLI 转写**
    ——hydration（转写打底）天然没有它们；账本补放又只回放水位之后
    （events_after 严格 >）。后端重启（账本恢复的水位在事件体之上）/回合一
    进行到一半才首次冷建 feed 时，turn_started 恒在水位之下 → busy/curTurn/
    _turn_rows/_held 永久丢失 → 前端 state.busy 缺省 false，把在飞回合当已
    完结定稿折叠（19 张工具卡全被藏起），而后台子代理实际还在跑（后台代理
    面板可见）。对账：busy 的会话末组头翻回 running、_turn_rows 登记（真
    turn_complete 到达收口既有组头，而非 _ensure_header 凭空建幽灵空组）、
    A 区补 busy/curTurn、_held 抑制迟到 result 兜底——「子代理结束，主窗
    同步结束」的链路由此闭环。"""
    tid = ""
    try:
        tid = (getattr(s, "_turn_id", "") or "").strip()
    except Exception:
        pass
    held = bool(getattr(s, "_held", False))
    busy = bool(getattr(s, "busy", False)) or bool(tid) or held
    if not busy:
        return
    bs = int(getattr(s, "busy_since", 0) or 0)
    with feed._lock:
        rows = feed.snap["rows"]
        # 翻转条件：转写已覆盖当前回合（末行时刻 ≥ 回合起点-2s 容差）。CLI
        # 尚未落盘当前回合时不翻——上一轮的定稿组头不能误伤，当前回合组头
        # 由后续带 turn 的行 _ensure_header 懒建。
        last_at = max([int(r.get("at") or 0) for r in rows] or [0])
        hdr = None
        if rows and (not bs or last_at >= bs - 2000):
            for r in reversed(rows):
                if r.get("kind") == "turn_header":
                    hdr = r
                    break
        if hdr is not None:
            nr = dict(hdr)
            nr["state"] = "running"
            if not nr.get("startedAt"):
                nr["startedAt"] = nr.get("at") or bs
            nr.pop("endedAt", None)
            for i, r in enumerate(rows):
                if r.get("rowId") == nr["rowId"]:
                    rows[i] = nr
                    break
            if tid:
                feed._turn_rows[tid] = nr["rowId"]
        feed.snap["state"]["busy"] = True
        if tid:
            feed.snap["state"]["curTurn"] = tid
        feed._held = held


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
        # a81（用户实锤：重启后历史 Task 卡摘要永远显示「This agent's
        # report was delivered…」投递元数据）：a68 的 hand-back 回填只跑
        # live 事件，hydration 重建的行吃不到——主转写里 hand-back 注入行
        # （origin.kind=peer，transcript_for 不含）带 from aid+报告全文，
        # 而 Task 行的元数据 output 自带同 aid，hydration 时就地配对回填
        try:
            import glob as _g
            import re as _re
            _hb = {}
            for _fp in _g.glob(os.path.join(os.path.expanduser("~"), ".claude",
                                            "projects", "*", s.session_id + ".jsonl")):
                with open(_fp, "r", encoding="utf-8", errors="replace") as f:
                    for _ln in f:
                        if "[Subagent hand-back]" not in _ln:
                            continue
                        try:
                            _o = json.loads(_ln)
                        except Exception:
                            continue
                        _c = (_o.get("message") or {}).get("content")
                        _t = _c if isinstance(_c, str) else \
                            next((str(b.get("text") or "") for b in _c
                                  if isinstance(b, dict)
                                  and "[Subagent hand-back]" in str(b.get("text") or "")), "") \
                            if isinstance(_c, list) else ""
                        if "[Subagent hand-back]" not in _t:
                            continue
                        _m = _re.search(r'from[=\\" ]+([0-9a-zA-Z_-]{8,64})', _t)
                        if _m:
                            _hb[_m.group(1)] = F.hb_report_body(_t)
            if _hb:
                for _r in feed.snap["rows"]:
                    if _r.get("kind") != "tool_call"                             or _r.get("tool") not in ("Task", "Agent"):
                        continue
                    _out = str(_r.get("output") or "")
                    if "delivered to you as a message from" not in _out:
                        continue
                    _m2 = _re.search(
                        r'delivered to you as a message from .([0-9a-zA-Z_-]{8,64})',
                        _out)
                    if _m2 and _m2.group(1) in _hb:
                        _r["output"] = "✅ " + _hb[_m2.group(1)][:4000]
        except Exception:
            pass
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
    永远空白）。下次订阅携修正 paths 重试。
    a62：hydrate 判据从「文件可读」改为「产出行数」——tasks/*.output 等
    候选可读但 feed_jsonl_line 零产出（格式不匹配），旧判据会停止尝试
    后续候选并缓存空实例；逐候选判 rows，空则换下一个。"""
    key = (sid, agent_key)
    with _lock:
        feed = _sub_feeds.get(key)
        if feed is not None:
            return feed
    feed = F.V4Feed(epoch="sub")
    if hydrate_paths:
        for p in hydrate_paths:
            if not p:
                continue
            feed.hydrate_jsonl(p)
            if feed.snap["rows"]:
                break           # 产出行即权威候选
    with _lock:
        if not feed.snap["rows"]:
            return feed          # 全候选零产出：不缓存（下次携修正 paths 重试）
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


def v4_main_has(sid):
    """a65：该会话的 v4 主投影是否已建（watcher 按需 hydrate 的启用闸——
    主 feed 在场=有 v4 客户端订阅过本会话，子投影按需冷建才有意义；V3
    模式恒 False，watcher 行为与旧版完全一致）。"""
    with _lock:
        return _main_feeds.get(sid) is not None


def v4_sub_has(sid, agent_key):
    with _lock:
        return _sub_feeds.get((sid, agent_key)) is not None


def v4_sub_hydrate(sid, agent_key, paths):
    """a65：watcher 按需冷建子 feed——pane 先开而转写后到（刚派发的代理
    CLI 尚未落盘）时，快照恒空；转写首行出现即按候选全量 hydrate 建出
    有内容的 feed 并缓存，此后 watcher 增量正常续喂（调用方须把本轮
    offset 推到文件尾——hydrate 已消费全量，增量跳过防重复）。
    返回是否建出有内容的 feed。"""
    if v4_sub_has(sid, agent_key):
        return True
    v4_sub_feed(sid, agent_key, paths)
    return v4_sub_has(sid, agent_key)


def v4_drop_session(sid):
    """会话删除/回收时清全部 feed。"""
    v4_drop_main(sid)
    v4_drop_sub(sid)


def v4_session_for(sid):
    with _sessions_lock:
        return _sessions.get(sid)
