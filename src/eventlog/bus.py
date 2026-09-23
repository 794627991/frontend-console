# -*- coding: utf-8 -*-
"""每会话事件总线：订阅者管理 + SSE 生成器协议（v3.0）。

对照 ZCode persistent-protocol.ts / conversation-topic-publisher.ts 的
SSE 化移植：

  subscribe(base={epoch,seq})
    ├─ ack(mode=resume)   base 有效 → 从 store 补 (base.seq, last] delta
    ├─ ack(mode=snapshot) base 无效但事件流可表达 → 客户端清场，重放保留窗
    └─ ack(mode=reset)    epoch 不匹配（/rewind 过）→ 转写重建，连本条一并关

  帧序防丢防重的关键顺序：先注册队列 → 再快照 store 回放 → 再消费队列，
  队列里可能混有快照已含的事件，按 seq 去重（「先落 store 再广播」与
  「队列先行」一起保证无漏）。

  慢订阅者（对照 persistent-protocol send() 的 abandonSession）：队列满
  不再「丢最旧塞最新」（旧策略让客户端拿到有洞的增量流且毫不知情），
  改为清空积压 + 投递 RESET 控制帧 + 关连接——客户端显式重建。积压 500
  条（ZCode 订阅者 buffer 同值）说明消费者已死/挂起，补洞无意义。

  心跳：空闲 5s 发 `event: ka`（命名事件——SSE 注释行前端 JS 不可见，
  看不到就做不了 20s 判死看门狗）。对照 KEEP_ALIVE_INTERVAL=5000 /
  ACK_TIMEOUT=20000。
"""
import json
import threading
from queue import Queue, Empty, Full

SUBSCRIBER_BUFFER = 500          # 每订阅者队列上限（ZCode core.ts:72）
KEEPALIVE_S = 5                   # 心跳间隔
FRAME_FORMAT = "data: %s\n\n"

_RESET_ITEM = {"__control__": "reset"}


class Subscription(object):
    def __init__(self):
        self.queue = Queue(maxsize=SUBSCRIBER_BUFFER)
        self.lock = threading.Lock()
        self.closed = False

    def close(self):
        with self.lock:
            self.closed = True


class SessionBus(object):
    def __init__(self, store):
        self.store = store
        self._subs = []
        self._lock = threading.Lock()

    # ---- 订阅 ----
    def subscribe(self, base_epoch=None, base_seq=0):
        """注册订阅者并判定续传模式。返回 (subscription, mode, replay_list)。

        replay_list 仅为 resume/snapshot 的初始回放段；live 段由调用方从
        subscription.queue 消费（与回放段按 seq 去重）。
        """
        sub = Subscription()
        with self._lock:
            self._subs.append(sub)
        mode = self.store.resume_mode(base_epoch, base_seq)
        if mode == "resume":
            replay = self.store.events_after(base_seq)
        elif mode == "snapshot":
            replay = self.store.snapshot()
        else:
            replay = []
        return sub, mode, replay

    def unsubscribe(self, sub):
        sub.close()
        with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass

    def has_subscribers(self):
        with self._lock:
            return any(not s.closed for s in self._subs)

    # ---- 发布 ----
    def publish(self, env):
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if sub.closed:
                continue
            try:
                sub.queue.put_nowait(env)
            except Full:
                # 慢订阅者：清空积压投 reset（不再丢最旧塞最新——有洞的
                # 增量流比断连更危险，客户端毫不知情地缺事件）
                with sub.lock:
                    try:
                        while True:
                            sub.queue.get_nowait()
                    except Empty:
                        pass
                    sub.closed = True
                    try:
                        sub.queue.put_nowait(_RESET_ITEM)
                    except Exception:
                        pass


def sse_frames(store, sub, mode, replay):
    """SSE 帧生成器：ack → 回放 → live（带去重/心跳/reset）。

    Flask Response(sse_frames(...)) 直接可用。生成器退出（GeneratorExit/
    断连）时由调用方 finally unsubscribe——这里不持有 sub 生命周期。
    """
    ack = {"mode": mode, "epoch": store.epoch, "seq": store.last_seq,
           "floor_seq": store.floor_seq}
    yield "event: ack\ndata: %s\n\n" % json.dumps(ack, ensure_ascii=False)
    if mode == "reset":
        # epoch 不匹配：客户端收 reset 即关流走 transcript 重建
        yield "event: reset\ndata: %s\n\n" % json.dumps(
            {"epoch": store.epoch, "reason": "epoch-mismatch"}, ensure_ascii=False)
        return
    last_sent = 0
    for ev in replay:
        last_sent = ev["seq"]
        yield FRAME_FORMAT % json.dumps(ev, ensure_ascii=False)
    while True:
        try:
            item = sub.queue.get(timeout=KEEPALIVE_S)
        except Empty:
            yield "event: ka\ndata: {}\n\n"
            continue
        if item is _RESET_ITEM or item.get("__control__") == "reset":
            yield "event: reset\ndata: %s\n\n" % json.dumps(
                {"reason": "slow-subscriber"}, ensure_ascii=False)
            return
        # 回放段与 live 段的接缝去重：队列在快照前注册，可能混入已回放事件
        if item.get("seq") and item["seq"] <= last_sent:
            continue
        if item.get("seq"):
            last_sent = item["seq"]
        yield FRAME_FORMAT % json.dumps(item, ensure_ascii=False)
