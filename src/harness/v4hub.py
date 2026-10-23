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
import re
import threading
import time

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
_building = set()           # sid 集合：冷建进行中（严重4 门禁放行判据）
# MAJOR-2/FATAL-4/FATAL-5 修正（a116 三次全审）：冷建窗口内的 live 事件
# **不能直投投影**（会让 live 行先占 rowId、历史 append 到其后=行序倒挂；
# 且 snap["rows"] 被污染会让 _zero 判据失效、账本前半段永久丢）。
# 改为 pending 队列：emit 只做 O(1) append 不阻塞，冷建完成后按 seq 有序
# 并入（_claim_seq 挡住与 _replay_from 补放的重叠）。
_building_pending = {}      # sid -> [env, ...]
_EMPTY_TTL = 30.0           # 零产出临时 feed 复用窗（严重8/MAJOR-4：防循环水化）
_empty_feeds = {}           # sid -> (epoch, at, feed)
_main_feeds = {}            # sid -> V4Feed
_sub_feeds = {}             # (sid, agentKey) -> V4Feed
# a74：子订阅意向表（FIFO 512）——watcher 按需 hydrate 的闸原本只认主 feed
# 在场，子 pane 先于主窗订阅/主 store 断连窗口期=闸死（转写出现也无人建
# feed，孤儿永不愈）。/v4/stream sub 订阅即登记，与主 feed 等价放行
_sub_wanted = []            # [(sid, agentKey), ...]

# F5 修复（a116 需求 1「不允许两套并存」的后端铁证）：主投影订阅意向。
# 旧实现在 **V3 模式**（零 v4 客户端）下每条 emit 都构建/重建完整 v4 投影
# ——实测零订阅者 last_seq>0 时 3 次 emit 触发 3 次全量 hydration。本集合
# 使 ingest 在「无人订阅且 feed 未建」时直接返回：账本是唯一真源，订阅者
# 到来时冷建照常从转写+账本重建，不丢数据。
_main_wanted = set()        # sid 集合（进程级，512 FIFO 上限同 _sub_wanted）


def v4_main_want(sid):
    """主 feed 订阅意向登记（/v4/stream 主 topic 订阅即登记）。"""
    with _lock:
        if sid in _main_wanted:
            return
        if len(_main_wanted) > 512:
            _main_wanted.clear()       # 简单兜底（session 数不可能过百）
        _main_wanted.add(sid)


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
        # 严重8 修正（a116 全审）+ MAJOR-4（a116 二次全审）：
        # 零产出块挡 (a62「空投影不缓存」) 返回的临时 feed 不入册，而 routes
        # 的 S5 对账每 5s 无条件再调本函数 → 空会话每 5s 打一次全量转写扫描
        # （实测 1.5~4.2s/次，持 blk）。TTL 内直接复用上次的临时 feed
        # （仍不入册，a62 语义不变）。TTL=30s、键只按 epoch（MAJOR-4）。
        # MAJOR-9/FATAL-6 修正（a116 三、四次全审）：TTL 到期**不能转正入册**
        # （转正在 hydration 之前 return，该实例此后再也不会跑 hydration →
        # 该会话主窗永久没有历史，刷新也无；实测 HEAD 正常、转正后永久缺）。
        # 正确做法：正常重建，同时把旧临时 feed 的 live 行显式纳入重放范围
        # ——它们本来就来自账本（emit 先落 store 再 ingest），从 0 全量重放
        # 即可原样重建，配合 _replay/_dup_hist 与 hydration 历史去重。
        _e = _empty_feeds.get(sid)
        _prev_empty = None
        if _e is not None and _e[0] == s.log.epoch:
            if time.time() - _e[1] < _EMPTY_TTL:
                return _e[2]
            if _e[2].snap["rows"]:
                _prev_empty = _e[2]      # 有过 live 行：重建后需从 0 重放
                _empty_feeds.pop(sid, None)
        if blk is None:
            blk = _build_locks[sid] = threading.Lock()
    if feed is not None and feed.epoch == s.log.epoch:
        return feed
    with blk:                            # 冷建串行（复审G1：并发冷建会双喂
        # 同一事件——先存者补放窗与后存者 live ingest 重叠=行双画）
        with _lock:
            feed = _main_feeds.get(sid)
            _building.add(sid)           # 严重4：冷建窗口内 emit 不得丢
            _building_pending.setdefault(sid, [])
        try:
            if feed is not None and feed.epoch == s.log.epoch:
                # 早返回：本次没有进行水化，pending 里的事件（若有）转投
                # 已存在的 feed，交由 finally 摘键兜底。
                with _lock:
                    _early = _building_pending.get(sid)
                    _evs = list(_early) if _early else []
                    if _early:
                        del _early[:]
                for _env in sorted(_evs, key=lambda e: e.get("seq") or 0):
                    try:
                        feed.ingest(_env)
                    except Exception:
                        # 全审（a116）：单条失败不能吞掉整批——记异常后继续
                        # 投递余下事件（丢掉一条 vs 丢掉一批，后者更糟）。
                        log.exception("v4 早返回 pending 单条失败 sid=%s seq=%s",
                                      sid, _env.get("seq"))
                return feed              # 双重检查：等锁期间他人已建好
            # F1-R（a116 十一次全审）：起点必须**严格大于**旧实例发过的任何
            # wseq。原公式 `账本 last_seq + LOG_RETAIN` 有洞——wseq 与账本
            # seq 都每事件 +1，「1 delta/事件」时同额偏移抵消，k==m 时
            # 旧 max == 新 base（审计实测丢 E1..E4、重复 E500..E503）。
            # 现由 V4Feed 的**进程级高水位**兜底：wseq_base 只是下界提示，
            # 实际起点取 max(提示, 进程已发放最大值 + 1)，从定义上严格递增。
            # 十六次全审（严重，(c) 降级论证不成立）：持久化小文件**不可
            # 信**（满盘/权限/被清 → 静默失败 → 读回 0 → 旧游标被放行 →
            # 整批消息静默消失，实测 40 条全丢且无快照无重连）。
            # 十七次全审：失效的**真实形态不是「读回 0」而是「陈旧非零」**
            # ——先成功写过几个值、之后写失败 → 盘上是旧值 → 「hwm>0 才
            # 不用兜底」的分支根本不触发 → 陈旧值与真实水位差 ≥3 时首批
            # 新事件拿到 ≤ 旧游标的 wseq，静默吞 13~33 条（实测）。
            # 故**无条件**取 max：`last_seq` 可作值下界（每个 store.append
            # 对应一次 ingest/补放，上一代发过的 wseq 数不超过它）。
            # 代价实测可接受：只让**换代那一次**走整窗快照（换代本就该
            # 重对齐），快照 ack 的 toSeq 进入新空间后，后续重连全部安静
            # 续传（审计实测 resume(100)=False → 快照 502 → resume(502)=True）。
            # 二十二次全审（结构）：正确性主链已改为**实例身份匹配**
            # （feed.incarnation，见 routes 的 base_inc 判据）——换实例必
            # 不匹配必快照。
            # **但数值单调不可删**（二十三次复审）：ack 与 snapshot frame
            # 之间若断线，客户端会处于 (inc=新, seq=旧) 的撕裂态，身份判据
            # 放行；此时只有「起点高于旧游标 / 旧游标已越窗」能把它挡回去。
            # 数值单调是撕裂态的**第二道兜底**，不是「次要属性」。
            _hint = max(int(getattr(s.log, "wseq_hwm", 0) or 0),
                        int(s.log.last_seq or 0))
            feed = F.V4Feed(epoch=s.log.epoch, wseq_base=_hint)
            # 让 feed 每次落账把 wseq 回写账本高水位（跨进程持久化见
            # store.wseq_hwm / session.to_meta 的 "wseq"）
            feed.log_store = s.log
            h = s.log.last_seq           # hydration 起点水位
            _hydrate_main(feed, s)       # 转写全量打底（历史权威）
            # P0-4 修复（a116 新会话首回合事件永久丢失）：
            # 零产出 = CLI 尚未把 jsonl 落盘（新会话首回合的常态），此时**账本
            # 才是唯一真源**，必须从 0 重放全量事件。旧实现只停止缓存并从 h 补放，
            # 而 h 已越过本回合全部事件 → turn_started/user_echo/ask/turn_complete
            # 永久不可恢复（实测 state 空、ask 丢、行只剩三条）。
            # 致命3 修正（a116 全审）：原实现置 `h = 0` 后紧接着的前置门
            # `if h > 0:` 会把整个补放块跳过——events_after(0) 从未被调用，
            # 「零产出→全量重放」是一条死代码（实测零产出 + 账本 3 条事件，
            # feed 仍 rows=0/seqs=[]）。改为独立的 _replay_from() 入口。
            _zero = not feed.snap["rows"] and h > 0
            if _zero:
                log.info("v4 主投影 hydration 零产出(账本全量重放) "
                         "sid=%s seq=%s", sid, h)
            if _zero:
                _replay_from(feed, s, 0, sid)      # 账本全量（唯一真源）
            elif h > 0:
                # FATAL-6 配套：上一次是「有 live 行但零产出」的临时 feed
                # （转写当时还没落盘）时，本轮起手水位虽 > 0，但这段历史
                # 只在账本里、不在转写里 → 必须从 0 全量重放才能取回。
                _lo = 0 if _prev_empty is not None else h
                _replay_from(feed, s, _lo, sid)
            # FATAL-4/FATAL-5 修正（a116 三次全审）：冷建窗口内 emit 收进
            # pending 的事件在此**按 seq 有序并入**——此时 history/补放已
            # 落定，live 行自然排在它们之后（行序正确），且上方的 _zero
            # 判据是在 hydration 与补放之后取的、不被 live 污染。
            # 与 _replay_from 的重叠由 feed._claim_seq 的 seq 判重挡住。
            # 竞态收口：反复取空直到锁内一次性「取走最后一批 + 摘标记 +
            # 摘键」——三者同锁完成，之后 emit 只会走正常路径，不会有事件
            # 落在「列表已清空」与「标记已摘」之间被丢。
            # MAJOR-11（a116 四次全审）：循环**必须有硬上界**——退出条件
            # 是「连续两轮取空」，事件流不停（实测 200 条/秒）则永不成立，
            # blk 被长期占用 → 后续所有 v4_main_feed（新 SSE、S5 对账、
            # 正常 ingest）全部阻塞，SSE 无首帧 → 15s 判死 → 重连死循环。
            # 限制：最多 3 轮、累计 60ms。超限后剩余 pending 由正常 ingest
            # 路径消费（标记摘掉后 emit 直接投 feed，不丢）。
            _deadline = time.time() + 0.06
            _fails = {}                  # MAJOR-13：seq -> 连续失败次数
            for _round in range(3):
                with _lock:
                    _lst = _building_pending.get(sid)
                    _batch = list(_lst) if _lst else []
                    if _lst:
                        del _lst[:]
                    if not _batch and _round >= 1:
                        _building.discard(sid)
                        _building_pending.pop(sid, None)
                        break
                if not _batch:
                    time.sleep(0.02)
                    continue
                for _env in sorted(_batch, key=lambda e: e.get("seq") or 0):
                    try:
                        feed.ingest(_env)
                        _fails.pop(_env.get("seq"), None)
                    except Exception:
                        # MAJOR-12（a116 四次全审）：单条失败不静默丢，回队。
                        # MAJOR-13（五次全审）：回队必须**计次**——同一条
                        # 永远失败时会每轮排在最前、吃光 50ms 预算、挤掉新
                        # 事件。同一 seq 失败 ≥2 次即丢弃并 warning。
                        _sq = _env.get("seq")
                        _fails[_sq] = _fails.get(_sq, 0) + 1
                        if _fails[_sq] >= 2:
                            log.error("v4 冷建 pending 单条连续失败 %d 次，"
                                      "丢弃 sid=%s seq=%s", _fails[_sq],
                                      sid, _sq)
                            continue
                        log.exception("v4 冷建 pending 单条失败（回队）"
                                      " sid=%s seq=%s", sid, _sq)
                        with _lock:
                            _building_pending.setdefault(sid, []).append(_env)
                if time.time() >= _deadline:
                    log.warning("v4 冷建 pending drain 达上界（余 %d 条）"
                                " sid=%s", len(_building_pending.get(sid) or []),
                                sid)
                    break
            try:
                _reconcile_live(feed, s)  # a82：在飞回合状态对账（busy/组头/hold）
            except Exception:
                log.exception("v4 冷建对账失败 sid=%s", sid)
            # S6 修复（a116）：快照冷填 queue——v4 snapshot 不附 s.queue_list()
            # 时，冷开/切回后的待发送队列条为空，直到下一条 queue 事件才恢复
            # （用户切回来看到队列「消失」）。真源在 session._inbox。
            try:
                _q = s.queue_list()
                if _q:
                    feed.snap["state"]["queue"] = _q
            except Exception:
                pass
            with _lock:
                old = _main_feeds.get(sid)
                # a62（用户实测致命「子页开着主窗历史全消失」）：hydration 零
                # 产出且账本有历史（last_seq>0）=定位失败——空投影**不缓存**
                # （否则此后每次重连都发空 snapshot，前端整窗重建抹成空白）。
                # 本次请求仍返回（前端有空快照防御），下次冷建重试 hydration
                if not feed.snap["rows"] and (s.log.last_seq or 0) > 0:
                    log.warning("v4 主投影 hydration 零产出(不缓存) sid=%s "
                                "seq=%s", sid, s.log.last_seq)
                    # 严重8/MAJOR-4：TTL 窗内复用本次结果，避免循环全量水化
                    _empty_feeds[sid] = (s.log.epoch, time.time(), feed)
                    return feed
                if old is None or old.epoch != s.log.epoch:
                    _main_feeds[sid] = feed
                    feed = _main_feeds[sid]
                    _empty_feeds.pop(sid, None)  # 正式入册：清零产出缓存
                else:
                    feed = old           # 锁内仍撞（epoch 竞速）：保留先入者
        finally:
            # 全审（a116）：add/discard 必须成对覆盖所有返回与异常路径——
            # 泄漏会让门禁对该 sid 永久放行，更糟的是该 sid 此后所有 emit
            # 都进 pending 而没人消费（主窗永久冻结、无自愈，只能重启）。
            # MAJOR-11 配套：drain 触及上界时可能仍有残留，摘标记**之前**
            # 必须把残留取走并投递。
            # MAJOR-14 修正（a116 五次全审）：原实现用 `for...else` + 上界
            # `break`，而 break 会**跳过 else**（Python 语义）→ 恰好在这种
            # 极端过载路径上既不摘标记也不摘 pending = 事件黑洞。现改为
            # 无条件 try/finally：循环只为「尽量多投」，清理**永远**执行。
            _fd = time.time() + 0.05
            try:
                for _ in range(4):
                    with _lock:
                        _lst = _building_pending.get(sid)
                        _rest = list(_lst) if _lst else []
                        if _lst:
                            del _lst[:]
                        if not _rest:
                            break
                    for _env in sorted(_rest, key=lambda e: e.get("seq") or 0):
                        try:
                            feed.ingest(_env)
                        except Exception:
                            log.exception("v4 冷建残留 pending 单条失败 "
                                          "sid=%s seq=%s", sid, _env.get("seq"))
                    if time.time() >= _fd:
                        break
            finally:
                with _lock:
                    _left = _building_pending.get(sid)
                    _n = len(_left) if _left else 0
                    _building.discard(sid)
                    _building_pending.pop(sid, None)
                if _n:
                    log.warning("v4 冷建残留 pending 超上界丢弃 %d 条 sid=%s "
                                "（极端过载：新事件由正常 ingest 接管）",
                                _n, sid)
    return feed


def _replay_from(feed, s, lo, sid):
    """账本补放：ingest 严格 > lo 的事件。补放期 _replay=True（与 hydration
    重叠的行不重画）。重复 seq 由 feed 侧的入口判重幂等丢弃。

    严重4 修正（a116 全审）：旧实现取 h 后又把水位抬到水化结束时的
    last_seq（h2），理由是「(h, h2] 由 live 线程消费」。但冷建期间
    `_main_wanted` 尚未登记（routes 先建 feed 后登记），`v4_ingest_main`
    直接 return ——那段事件**两头都没人消费**，实测 hydration 延时 0.4s +
    期间 emit 一条 → feed rows=0/seqs=[]，消息彻底消失。
    现按 lo 原样补放，(lo, h2] 与 live 份重叠由 seq 判重兜住。"""
    try:
        feed._replay = True
        for env in s.log.events_after(lo):
            feed.ingest(env)
        feed._replay = False
    except Exception:
        feed._replay = False
        log.exception("v4 账本补放失败 sid=%s lo=%s", sid, lo)


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
        # 严重7 配套（a116 全审）：对账直接改 snap 不经过 _commit，必须手动
        # bump 帧版本，否则 snapshot/帧文本缓存键（现以 _ver 为准）认为
        # 「没变」，对账结果对后续订阅者不可见。
        with feed._cv:
            feed._ver += 1
            feed._cv.notify_all()


def v4_ingest_main(s, env):
    """session.emit 挂接（store 落账之后调用——persist-before-publish）。"""
    try:
        # F5 门禁：无订阅者且 feed 未建 → 不跑投影（V3 会话零开销）。
        # 账本是唯一真源，订阅者到达时 v4_main_feed 从转写+账本全量重建。
        sid = s.sid
        with _lock:
            # 严重4 修正（a116 全审）：冷建进行中也必须放行——冷建窗口内
            # （hydration 1.5~4.2s）落账的事件若在此丢弃，而补放又按
            # 「已交给 live 线程」的假设跳过了它，则该事件永久消失。
            if (sid not in _main_wanted and sid not in _main_feeds
                    and sid not in _building):
                return
            # MAJOR-2 修正（a116 二次全审）+ FATAL-4/5 收口（三次全审）：
            # 冷建进行中**不投给 feed、也不等 blk**（等 blk 会把
            # session.emit 的 reader 线程拖住 1.5~4.2s；直投会让 live 行
            # 先占 rowId 造成行序倒挂、并让 _zero 判据失效）。改为 O(1)
            # 入 pending 队列，冷建收尾时按 seq 有序并入。
            # S3（a116 十五次全审）：**append 必须在本锁内**。原实现只取
            # 引用、出锁再 append——与收尾的 `pop(sid)`（finally 块）之间
            # 存在窗口：收尾先摘键，随后的 append 落进孤儿 list → 既没进
            # pending 也没走 live 路径 → 事件永久消失且无自愈。
            _pend = _building_pending.get(sid)
            if _pend is not None:
                _pend.append(env)
                return
        _f = v4_main_feed(s)
        # a116 十六次全审（F3-1/F3-2 根修）：wseq 高水位由 `store.wseq_hwm`
        # 的 setter **同步**落独立小文件（见 eventlog/store.py）。这里不再
        # 需要任何异步落盘——`_commit` 无论来自 live 还是冷建补放，都经过
        # 同一个 setter，不存在「某条路径忘了持久化」的缺口。
        _f.ingest(env)      # 重复 seq 由 _claim_seq 判重幂等丢弃
    except Exception:
        log.exception("v4 ingest main 失败 sid=%s seq=%s",
                      getattr(s, "session_id", "?"), env.get("seq"))


def v4_drop_main(sid):
    with _lock:
        _f = _main_feeds.pop(sid, None)
        # P2-8 修复（a116）：订阅意向一并回收，_main_wanted 不再无界。
        # 一般13 修正（a116 全审）：**不 pop _build_locks**——删除瞬间
        # 另一线程可能正持该锁，随后第三个线程 get 到 None 会新建一把，
        # 两把锁并行冷建=双喂。锁对象开销可忽略，保锁更安全。
        _main_wanted.discard(sid)
        _building.discard(sid)
        _building_pending.pop(sid, None)
        _empty_feeds.pop(sid, None)
    # a116 十六次全审：wseq 高水位已在 store 的 setter 里同步落盘，drop 时
    # 无需兜底写（原实现取 `_sessions.get(sid)` 恒 None——routes 先 pop 后
    # drop，是死代码）。


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
    # a118（用户实锤「所有编辑的代码行数又都不对了」）：Edit/MultiEdit 真实
    # 行号注入——_dln_inject 只挂在 V3 /transcript 端点，v4 hydration 直接
    # 调 transcript_for 漏了这一步，281 条 Edit 行 dln 全空=回放行号全错。
    # 懒导入避循环（routes 也 import 本模块）；注入逻辑/缓存与 V3 同源同口径
    try:
        from .routes import _dln_inject
        _dln_inject(lines)
    except Exception:
        pass
    # S4 修复（a116）：hand-back 扫盘必须**在 feed._lock 之外**做。旧实现整个
    # 块（glob 全 projects + 逐行扫 452MB 主转写）持锁执行：112MB 会话实测
    # 扫盘 0.44s + transcript_for 1.12s = 冷建 1.55s 全程持锁，期间所有
    # frames_after/snapshot_wire 阻塞（首帧延迟、订阅者空转）。
    # 现改为：锁外扫出 {aid: 正文}，锁内只做短回填。按 sid 精确路径，不 glob。
    _hb = {}
    try:
        import glob as _g
        # 一般14（a116 全审）：新会话 session_id 为 None（session.py:46），
        # 拼接会 TypeError 被 except 吞掉、每次冷建打一条栈。无 sid 时
        # 无路径可扫，直接跳过（hand-back 回填由 live 事件路径覆盖）。
        if not s.session_id:
            _cands = []
        else:
            _cands = [p for p in _g.glob(os.path.join(
                os.path.expanduser("~"), ".claude", "projects", "*",
                s.session_id + ".jsonl")) if os.path.isfile(p)]
        for _fp in _cands:
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
                    _m = F.HB_AID_RE.search(_t)
                    if _m:
                        _hb[_m.group(1)] = F.hb_report_body(_t)
        if _cands:
            log.debug("v4 hydration 扫 %d 份转写取 hand-back sid=%s",
                      len(_cands), s.session_id)
    except Exception:
        log.exception("v4 hydration hand-back 扫描失败 sid=%s", s.session_id)
        _hb = {}
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
                    images=l.get("images") or []))
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
                # P2-9 修复（a116）：Task/Agent/SendMessage 行在 hydration 时
                # 一律落 success 会让刷新后仍在跑的卡先按「完成」画
                # （dataset.final 会摘掉同步标），冷同步失败/竞速窗口内用户
                # 看到假完成。无终态证据（无 result 文本）时落 running，
                # 由后续 feed 终态帧/冷同步收口。
                _tname = l.get("text") or ""
                _tres = l.get("result") or ""
                _stat = "success"
                # FATAL-2 修正（a116 二次全审）：判据不能只看「result 为空」
                # ——真实后台派发回执**文本非空**（"Async agent launched
                # successfully. (This tool result is internal metadata and
                # not a final result)…"），主转写实测 379 个 Task/Agent/
                # SendMessage 里 result 为空只有 3 个（0.8%），旧判据让 99%
                # 的 ACK 型行在刷新后落 success = 「假完成」（前端
                # dataset.final 摘掉同步标）。与 v4feed 同口径用 is_bg_ack
                # 判文本形态，命中即落 running，等真终态帧/冷同步收口。
                if (_tname in ("Task", "Agent", "SendMessage")
                        and (not str(_tres).strip()
                             or F.is_bg_ack(_tres))):
                    _stat = "running"
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "t%d" % max(turn_n, 1), "tool_call", ts, 0,
                    tool=_tname, status=_stat,
                    summary=l.get("summary") or "", input=l.get("input") or "",
                    output=_tres, tid=l.get("tid") or "",
                    dln=l.get("dln") or None))   # a118：Edit 真实行号透传
                feed.snap["total"] += 1
            elif role in ("renew", "sysnote", "audit", "exit"):
                _tx = l.get("text") or ""
                # a93S（用户定调「这个不显示」）：后台保活探活卡不进投影
                #（与 v4feed live 侧同滤；hydration 从 audit log 并入的回放行
                # 同样不落行）
                if role == "audit" and (_tx.startswith("[保活")
                                        or _tx.startswith("[限流")):
                    continue
                feed._row_id += 1
                feed.snap["rows"].append(F.P.mk_row(
                    feed._row_id, "", "marker", ts, 0, mkind=role,
                    text=_tx))
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
        # 而 Task 行的元数据 output 自带同 aid，hydration 时就地配对回填。
        # S4：扫盘已在锁外完成（_hb），此处仅剩行遍历+字符串替换。
        try:
            if _hb:
                for _r in feed.snap["rows"]:
                    if _r.get("kind") != "tool_call" \
                            or _r.get("tool") not in ("Task", "Agent"):
                        continue
                    _out = str(_r.get("output") or "")
                    if not F.hb_is_meta(_out):
                        continue
                    _m2 = re.search(
                        r'delivered to you as a message from .([0-9a-zA-Z_-]{8,64})',
                        _out)
                    if _m2 and _m2.group(1) in _hb:
                        _r["output"] = "✅ " + _hb[_m2.group(1)][:4000]
        except Exception:
            # 致命1（a116 全审）：原 `except Exception: pass` 让 NameError
            # 级别的缺陷（`re` 未在模块导入）完全静默——a81/a68 的 Task 卡
            # 摘要回填实际 100% 失效却无人察觉。改为记录异常。
            log.exception("v4 hydration hand-back 回填失败 sid=%s",
                          s.session_id)
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
    # F1-R（a116 十一次全审）：子 feed 起点交给 V4Feed 的**类级高水位**
    # 分配（wseq_base=0 → 取 max(0, 进程 hwm+1)）。原实现用毫秒时间戳
    # ×1e6，时钟回拨或同毫秒两次重建时会拿到 ≤ 旧 max 的起点，旧游标
    # 遂可落进新空间（同 epoch "sub" → 永不回退快照）。
    feed = F.V4Feed(epoch="sub")
    _hit = None
    if hydrate_paths:
        for p in hydrate_paths:
            if not p:
                continue
            feed.hydrate_jsonl(p)
            if feed.snap["rows"]:
                _hit = p          # 产出过行的候选：整文件已被消费
                break           # 产出行即权威候选
    if _hit:
        # a119P（用户实测「打开子代理卡顿」）：命中文件已整读——offset 直推
        # 文件尾，订阅时刻对账（push_paths_once）零重读（此前每开一次 pane
        # 都 force 归零全量重读 MB 级转写+逐行解析）。未产出候选不标，
        # 留给对账首读（幂等）
        try:
            from .subagent_watch import mark_offsets
            mark_offsets([_hit])
        except Exception:
            pass
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
