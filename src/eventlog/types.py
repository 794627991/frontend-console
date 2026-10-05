# -*- coding: utf-8 -*-
"""事件契约（v3.0 事件溯源改造，方案对照 ZCode session.events.ts）。

单一契约文件集中声明全部事件类型常量与信封构造——协议类型分散后必然
漂移（ZCode 在此文件顶部明说），这是「11 个 kind 字符串散落 emit 调用点」
的终结者。

信封（每条 SSE 事件 JSON 的公共字段，emit 时由 store 统一注入）：
  seq    int    会话内单调递增；分配在 store 锁内（修 v2.x seq 竞态：
               reader 线程/HTTP handler/peer 轮询并发 emit 同号乱序）
  ts     int    epoch 毫秒
  epoch  str    日志代际（logEpoch，对照 transport.ts:84）：日志重写
               （/rewind 截断转写）即更换——旧 seq 空间作废，客户端带旧
               epoch 重连只能拿到 reset（全量重建），不能 resume
  sid    str    harness 会话 id（信封自带，客户端不再依赖连接归属推断）
  turn   str    回合 id（user 发送→result 为一个 turn；CLI 自发回合同界），
               会话级控制事件（peer/audit 等）可空
  type   str    统一事件类型（本文件常量之一）
  kind   str    旧字段保留（= 11 个 legacy kind），前端按它分派不受影响；
               新代码一律用 type

type 与 kind 的关系：控制类事件 type == kind（user_echo/renew/…）；CLI
透传事件 kind=='event' 而 type=='cli_stream'（CLI 原始 NDJSON 在 data 里，
二级类型 data.type 由前端 handleEvent 消化——两层合并收编是后续迁移项，
本期先统一信封，前端零破坏）。
"""
import threading
import time
import uuid


class SessionEventType(object):
    """事件类型常量清单（值统一 snake_case，对照 ZCode SessionEventType）。

    生命周期前缀分组：会话级（无 turn）/ 回合级 / CLI 流 / 交互 / 保留。
    """
    # ---- 回合生命周期（v3.0 新增；前端本期忽略，reducer 已消费）----
    TURN_STARTED = "turn_started"       # send() 占位成功 / CLI 自发回合起跑
    TURN_COMPLETE = "turn_complete"     # result 到达（正常收尾）
    TURN_ERROR = "turn_error"           # busy 中进程死/中断（异常收尾）

    # ---- CLI 透传 ----
    CLI_STREAM = "cli_stream"           # legacy kind=='event'，data=原始 NDJSON

    # ---- 会话级控制（legacy kind 原值收编）----
    USER_ECHO = "user_echo"
    RENEW = "renew"
    INTERRUPTED = "interrupted"
    EXIT = "exit"
    PEER = "peer"
    AUDIT = "audit"
    RAW = "raw"
    MODEL_SWITCHED = "model_switched"

    # ---- 交互式提问 ----
    ASK = "ask"
    ASK_DONE = "ask_done"

    # ---- 子代理镜像（#12：后端从 CLI 杂讯合成干净生命周期，reducer 直用）----
    SUBAGENT_STARTED = "subagent_started"   # Task 派发起跑（tid/type/desc/bg/task_id）
    SUBAGENT_RESULT = "subagent_result"     # task_notification 收尾（ok/brief/tokens/tool_n）

    # ---- durable 输入账本（#10：busy 期排队输入的服务端真源）----
    INPUT_ADMITTED = "input_admitted"       # 入队（id/text/gen）
    INPUT_PROMOTED = "input_promoted"       # 出队真发（id）
    INPUT_DISCARDED = "input_discarded"     # 废弃（id/reason：rewind 换代、用户删除、发送失败）


# kind → type 映射（emit 入口查表；未知 kind 原样透传，前向兼容）
_KIND_TO_TYPE = {
    "event": SessionEventType.CLI_STREAM,
    "user_echo": SessionEventType.USER_ECHO,
    "renew": SessionEventType.RENEW,
    "interrupted": SessionEventType.INTERRUPTED,
    "exit": SessionEventType.EXIT,
    "peer": SessionEventType.PEER,
    "audit": SessionEventType.AUDIT,
    "raw": SessionEventType.RAW,
    "model_switched": SessionEventType.MODEL_SWITCHED,
    "ask": SessionEventType.ASK,
    "ask_done": SessionEventType.ASK_DONE,
    SessionEventType.SUBAGENT_STARTED: SessionEventType.SUBAGENT_STARTED,
    SessionEventType.SUBAGENT_RESULT: SessionEventType.SUBAGENT_RESULT,
    SessionEventType.INPUT_ADMITTED: SessionEventType.INPUT_ADMITTED,
    SessionEventType.INPUT_PROMOTED: SessionEventType.INPUT_PROMOTED,
    SessionEventType.INPUT_DISCARDED: SessionEventType.INPUT_DISCARDED,
    SessionEventType.TURN_STARTED: SessionEventType.TURN_STARTED,
    SessionEventType.TURN_COMPLETE: SessionEventType.TURN_COMPLETE,
    SessionEventType.TURN_ERROR: SessionEventType.TURN_ERROR,
}


def type_for_kind(kind):
    return _KIND_TO_TYPE.get(kind, kind)


# ---------------------------------------------------------------------------
# 瞬态事件类型（对照 ZCode session-event-retention.ts TRANSIENT_SET）。
# 瞬态事件照常分配 seq 进 live 流，但一个 turn 滞后地从内存淘汰——turn
# 结束只标记 sealed，下一个 turn_started 才一次性淘汰（滞后原因：turn 刚
# 结束时消息可能尚未落盘，冷恢复还要靠内存瞬态事件拼文本）。
# 本期项目无逐 chunk delta 事件（CLI 不开 --include-partial-messages），
# 集合暂空；机制完整保留，delta 化后把流式类型填进来即生效。
# ---------------------------------------------------------------------------
TRANSIENT_SESSION_EVENT_TYPES = frozenset()

SEALED_TURN_TRANSIENT_GRACE_MS = 120 * 1000   # 单 turn 子会话兜底宽限


def new_epoch():
    """新日志代际。进程内每次调用唯一；rewind/日志重写时更换。"""
    return uuid.uuid4().hex[:12]


def new_turn_id():
    return uuid.uuid4().hex[:12]


def make_envelope(item, sid, epoch, turn):
    """给裸事件 dict 注入信封公共字段（seq 由 store.append 锁内补）。

    不改调用方传入的 dict——拷贝后写（emit 契约：item 归 store 所有）。
    """
    env = dict(item)
    env.setdefault("ts", int(time.time() * 1000))
    env["sid"] = sid
    env["epoch"] = epoch
    if turn:
        env.setdefault("turn", turn)
    else:
        env.pop("turn", None)
    env["type"] = type_for_kind(env.get("kind"))
    return env


class TurnWindowRetention(object):
    """turn 窗口瞬态事件回收（对照 session-event-retention.ts:55-96）。

    on_append 返回本条事件触发淘汰的 turn_id 列表（下一 turn 开始 →
    淘汰全部已 sealed 的）；collect_expired 由 60s tick 兜底调用，处理
    单 turn 内再无后续 turn 的子会话（宽限 120s）。
    """

    def __init__(self, transient_types=None):
        self._transient = frozenset(transient_types or TRANSIENT_SESSION_EVENT_TYPES)
        self._open_turns = set()
        self._sealed_at = {}          # turn_id -> seal 时刻 ms

    @property
    def transient_types(self):
        return self._transient

    def is_transient(self, ev):
        return ev.get("type") in self._transient

    def on_append(self, ev, now_ms):
        turn = ev.get("turn")
        if not turn:
            return []
        t = ev.get("type")
        if t == SessionEventType.TURN_STARTED:
            evict = [x for x in self._sealed_at if x != turn]
            self._sealed_at.clear()
            self._open_turns.add(turn)
            return evict
        if t in (SessionEventType.TURN_COMPLETE, SessionEventType.TURN_ERROR):
            self._open_turns.discard(turn)
            if turn not in self._sealed_at:
                self._sealed_at[turn] = now_ms
        return []

    def collect_expired(self, now_ms, grace_ms=SEALED_TURN_TRANSIENT_GRACE_MS):
        expired = [t for t, at in self._sealed_at.items()
                   if now_ms - at >= grace_ms]
        for t in expired:
            self._sealed_at.pop(t, None)
            self._open_turns.discard(t)
        return expired


# 全局瞬态回收 tick 的锁（多会话 store 共用一只 policy 各自持有，tick 全局）
RETENTION_TICK_S = 60
_retention_lock = threading.Lock()
