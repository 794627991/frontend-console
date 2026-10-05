# -*- coding: utf-8 -*-
"""SessionEventLog：store + bus + stash 的每会话门面（v3.0）。

HarnessSession 只对接这一个类——三件套的组装细节不外泄（架构治理：
eventlog 模块唯一公开入口，见 architecture-policy.yaml）。
"""
from .store import SessionEventStore
from .bus import SessionBus, sse_frames, SUBSCRIBER_BUFFER, KEEPALIVE_S
from .truncate import ToolOutputStash, truncate_tool_output, PROTOCOL_LIMITS
from .types import SessionEventType


class SessionEventLog(object):
    def __init__(self, sid, retention=2000, epoch=None, start_seq=0):
        self.store = SessionEventStore(sid, retention=retention,
                                       epoch=epoch, start_seq=start_seq)
        self.bus = SessionBus(self.store)
        self.stash = ToolOutputStash()

    # ---- 语义属性（门面直通）----
    @property
    def sid(self):
        return self.store.sid

    @property
    def epoch(self):
        return self.store.epoch

    @property
    def last_seq(self):
        return self.store.last_seq

    @property
    def floor_seq(self):
        return self.store.floor_seq

    @property
    def projection(self):
        return self.store.projection

    def stats(self):
        return self.store.stats()

    # ---- 写入 + 广播（HarnessSession.emit 的全部职责）----
    def emit(self, item, turn=None):
        """协议出口统一截断 → 锁内盖章落 store → 广播。返回已盖章事件。"""
        if item.get("kind") == "event" and isinstance(item.get("data"), dict):
            item = dict(item)
            item["data"] = truncate_tool_output(item["data"], self.stash)
        env = self.store.append(item, turn=turn)
        self.bus.publish(env)
        return env

    # ---- 订阅（stream 路由用）----
    def subscribe(self, base_epoch=None, base_seq=0):
        return self.bus.subscribe(base_epoch=base_epoch, base_seq=base_seq)

    def unsubscribe(self, sub):
        self.bus.unsubscribe(sub)

    def frames(self, sub, mode, replay):
        return sse_frames(self.store, sub, mode, replay)

    # ---- 旧接口兼容（/events 轮询兜底路径沿用）----
    def events_after(self, after_seq=0, limit=None):
        return self.store.events_after(after_seq, limit=limit)

    # ---- 日志重写 / 对象重建 ----
    def bump_epoch(self):
        self.store.bump_epoch()

    def restore(self, epoch, seq):
        self.store.restore(epoch, seq)

    # ---- 截断全文按需拉取 ----
    def full_output(self, ref):
        return self.stash.get(ref)
