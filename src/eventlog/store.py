# -*- coding: utf-8 -*-
"""每会话事件存储（v3.0，方案对照 ZCode in-memory-session-event-store.ts）。

三件事：
1. seq 唯一来源——分配在锁内（修 v2.x 竞态：reader 线程/HTTP handler/
   peer 轮询并发 emit 时 `self._seq += 1` 在锁外，同号与乱序都会让前端
   防重放守卫吞事件）；
2. append-only 保留窗——deque(maxlen=retention)，逐出即推进 floor_seq
   （断点续传的有效 base 下界，对照 conversation-topic-publisher.ts:522）；
3. 纯函数投影——append 时顺手过 reducer，live/重放/快照共用同一归约
   （对照 event-reducer.ts：状态唯一所有者，业务侧不再散落 busy 旗）。

计数器只增不减：瞬态淘汰/窗口逐出都不回拨 last_seq——否则下次分配出
重复 seq，前端守卫整批吞事件（v2.35.2 事故的机制化防线）。
"""
from collections import deque

from .types import (SessionEventType, make_envelope, new_epoch,
                    TurnWindowRetention)
from . import reducer as _reducer


class SessionEventStore(object):
    """单会话 append-only 事件日志（内存态；持久真源仍是 CLI 转写 jsonl）。"""

    def __init__(self, sid, retention=2000, epoch=None, start_seq=0):
        self.sid = sid
        self.retention = int(retention)
        self._lock = __import__("threading").Lock()
        self._events = deque(maxlen=self.retention)
        self._last_seq = int(start_seq)
        self._floor_seq = self._last_seq      # 保留窗内最老 seq-1 语义：base >= floor 才可续传
        self.epoch = epoch or new_epoch()
        self.retention_policy = TurnWindowRetention()
        self.evicted_events = 0
        self.projection = _reducer.initial_projection(sid)

    # ---- 基本 view ----
    @property
    def last_seq(self):
        return self._last_seq

    @property
    def floor_seq(self):
        return self._floor_seq

    def stats(self):
        with self._lock:
            return {"sid": self.sid, "events": len(self._events),
                    "last_seq": self._last_seq, "floor_seq": self._floor_seq,
                    "epoch": self.epoch, "evicted": self.evicted_events}

    # ---- 写入 ----
    def append(self, item, turn=None, now_ms=None):
        """信封注入 + 锁内分配 seq + 落缓冲 + 瞬态淘汰 + 投影归约。

        返回盖好章的事件（调用方拿去广播——先落 store 再广播，对照
        v4-bridge.ts:529 的顺序约定）。item 本体不被持有（make_envelope
        已拷贝）。
        """
        import time as _time
        now_ms = now_ms if now_ms is not None else int(_time.time() * 1000)
        with self._lock:
            self._last_seq += 1
            env = make_envelope(item, self.sid, self.epoch, turn)
            env["seq"] = self._last_seq
            self._events.append(env)
            if len(self._events) == self.retention:
                # deque 满后再 append 会自动丢最老；这里同步推进 floor
                self._floor_seq = self._events[0]["seq"] - 1
            # turn 窗口瞬态淘汰（本期 TRANSIENT 集合为空，机制预埋）
            evict_turns = self.retention_policy.on_append(env, now_ms)
            if evict_turns:
                self._evict_transient(set(evict_turns))
            self.projection = _reducer.apply_event(self.projection, env)
            return env

    def _evict_transient(self, turn_ids):
        if not self.retention_policy.transient_types:
            return
        keep = deque(maxlen=self.retention)
        for ev in self._events:
            if self.retention_policy.is_transient(ev) and ev.get("turn") in turn_ids:
                self.evicted_events += 1
                continue
            keep.append(ev)
        self._events = keep

    def prune_transient(self, now_ms, grace_ms=None):
        """60s tick 兜底：单 turn 内再无后续 turn 的子会话按宽限淘汰。"""
        expired = self.retention_policy.collect_expired(
            now_ms, grace_ms) if hasattr(self.retention_policy, "collect_expired") else []
        if expired:
            with self._lock:
                self._evict_transient(set(expired))

    # ---- 读取 ----
    def events_after(self, after_seq, limit=None):
        with self._lock:
            res = [e for e in self._events if e["seq"] > after_seq]
        return res[-limit:] if limit else res

    def snapshot(self):
        with self._lock:
            return list(self._events)

    # ---- 断点续传判定（对照 conversation-topic-publisher.ts:743-788）----
    def resume_mode(self, base_epoch, base_seq):
        """三态：resume（补 delta）/ snapshot（清场重放保留窗）/ reset（转写重建）。

        - base 未带（epoch 为空）→ snapshot：客户端没有可声明的一致水位
        - epoch 不匹配 → reset：日志已被重写（/rewind），事件流无法表达真源，
          客户端必须走 transcript 重建
        - base_seq 落在保留窗内 [floor, last] → resume
        - base_seq 越过 last（不可能的一致态）→ snapshot 兜底
        """
        if base_epoch and base_epoch != self.epoch:
            return "reset"
        if not base_epoch:
            return "snapshot"
        if self._floor_seq <= base_seq <= self._last_seq:
            return "resume"
        return "snapshot"

    # ---- 日志重写 ----
    def bump_epoch(self, epoch=None):
        """/rewind 截断转写后调用：换代 + 清缓冲。seq 计数继续（计数器只增
        不减）；floor 推到 last——旧 seq 空间即刻作废，任何旧 base 都只能
        reset。"""
        with self._lock:
            self.epoch = epoch or new_epoch()
            self._events.clear()
            self._floor_seq = self._last_seq
            self.projection = _reducer.initial_projection(self.sid)

    def restore(self, epoch, seq):
        """会话对象被重建（闲置回收/重启后 _get_or_create）时续号续代。

        meta 有 epoch → 沿用（GC 重建不是日志重写，代际不变，前端快照的
        base 仍可 resume）；无 epoch（升级前旧 meta）→ 新代（前端旧水位
        作废，走 snapshot 重建一次，代价一次性）。
        """
        with self._lock:
            self.epoch = epoch or new_epoch()
            self._last_seq = max(self._last_seq, int(seq or 0))
            self._floor_seq = self._last_seq
