# -*- coding: utf-8 -*-
"""SessionEventLog：store + stash 的每会话门面（v3.0；bus 随旧 SSE 链退役）。

HarnessSession 只对接这一个类——组装细节不外泄（架构治理：
eventlog 模块唯一公开入口，见 architecture-policy.yaml）。
"""
from .store import SessionEventStore
from .truncate import ToolOutputStash, truncate_tool_output, PROTOCOL_LIMITS
from .types import SessionEventType


class SessionEventLog(object):
    def __init__(self, sid, retention=2000, epoch=None, start_seq=0):
        self.store = SessionEventStore(sid, retention=retention,
                                       epoch=epoch, start_seq=start_seq)
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

    # ---- 写入（HarnessSession.emit 的全部职责）----
    def emit(self, item, turn=None):
        """协议出口统一截断 → 锁内盖章落 store。返回已盖章事件。"""
        if item.get("kind") == "event" and isinstance(item.get("data"), dict):
            item = dict(item)
            item["data"] = truncate_tool_output(item["data"], self.stash)
        env = self.store.append(item, turn=turn)
        return env

    # ---- 旧接口兼容（hiklink 轮询 / v4hub hydration 补放沿用）----
    def events_after(self, after_seq=0, limit=None):
        return self.store.events_after(after_seq, limit=limit)

    # ---- 日志重写 / 对象重建 ----
    def bump_epoch(self):
        self.store.bump_epoch()

    def restore(self, epoch, seq, wseq_hwm=0):
        """对象重建（GC/重启）时续号续代。`wseq_hwm` 是 v4 投递序号高水位
        （a116 十四次全审）：必须一并直通 store，否则 `_claim_base` 读不到
        真实高水位、重启后起点回落 → 旧客户端游标落进新空间丢历史。"""
        self.store.restore(epoch, seq, wseq_hwm)

    # ---- v4 投递序号高水位（a116 十四次全审）----
    # 必须**代理到 store**：写入方（v4feed._commit）与读取方（v4hub 建 feed、
    # session.to_meta）都拿的是本门面对象。原实现在门面上挂实例属性，
    # 而 restore 写的是 store 的同名属性 → 两个对象各存一份，重启永远读 0。
    @property
    def wseq_hwm(self):
        return getattr(self.store, "wseq_hwm", 0)

    @wseq_hwm.setter
    def wseq_hwm(self, v):
        self.store.wseq_hwm = int(v or 0)

    # ---- 截断全文按需拉取 ----
    def full_output(self, ref):
        return self.stash.get(ref)
