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
import logging as _logging
import os
import re as _re
import threading as _threading

_log = _logging.getLogger(__name__)

from .types import (SessionEventType, make_envelope, new_epoch,
                    TurnWindowRetention)
from . import reducer as _reducer

# a116 十六次全审：wseq 高水位独立小文件目录。放 HOME_DIR 下与 meta 同级
# （用户数据目录，重启存活）；不进 meta 是为了同步写——meta 是全量读写，
# 每条事件都同步会让流式 token 变成磁盘风暴。
_WSEQ_DIR = os.path.join(
    os.path.expanduser("~"), ".serialconsole_pro", "v4wseq")

# a116 十六次全审：`_save_wseq` 的句柄/游标是**跨对象**共享的底层资源
# （`_commit` 持 feed._lock，`restore` 持 store._lock——两把不同的锁，
# 会并发进到这里）。lseek+write 是两步操作，并发下会互相穿插导致写错
# 位置，必须串行化。单把全局锁，临界区只有两次 syscall，开销可忽略。
_WSEQ_FD_LOCK = _threading.Lock()


def _safe_name(sid):
    """sid → 安全文件名（只保留字母数字与 -_，其余转下划线）。"""
    return _re.sub(r"[^A-Za-z0-9_-]", "_", str(sid or "anon"))[:80] or "anon"


def drop_wseq_file(sid):
    """会话删除时清掉它的 wseq 高水位文件（否则长期累积孤儿小文件）。
    幂等：文件不存在不算错。"""
    try:
        os.remove(os.path.join(_WSEQ_DIR, "%s.wseq" % _safe_name(sid)))
    except Exception:
        pass

# v3.1（#13）microcompact 阈值：保留窗字节总量超过 COMPACT_BYTES 且新回合
# 已开跑时，把**旧回合**的超大 cli_stream 负载就地折叠（正文/工具输出留
# 头尾各 200 字符）。只影响后来者（断线重连 replay / 慢订阅者回放）——已
# 广播出去的 live 流不受影响；live DOM 渲染兜底在持久真源（转写 jsonl）。
COMPACT_BYTES = 1536 * 1024          # 保留窗字节上限（约 1.5MB）
COMPACT_EVENT_BYTES = 4096           # 单事件超过该值才算「超大」
COMPACT_KEEP = 200                   # 折叠保留的头/尾字符数


def _fold_text(s, keep=COMPACT_KEEP):
    """头尾各留 keep 字符，中间替换为折叠标记。返回 (新文本, 折掉的字节数)。"""
    s = str(s)
    if len(s) <= keep * 2 + 64:
        return s, 0
    marker = "\n…（旧回合输出已折叠 %d 字节，完整内容见消息流/转写）…\n" % len(s.encode("utf-8"))
    return s[:keep] + marker + s[-keep:], len(s.encode("utf-8"))


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
        self._bytes = 0                 # v3.1（#13）：保留窗字节估算（append 累加）
        # v4 投影投递序号的高水位（a116 十四次全审）。v4 客户端的续传游标
        # 是「投递序号 wseq」而不是事件 seq，两者空间独立。重建 feed 时
        # 新起点必须严格大于**上一代发过的任何 wseq**，否则旧游标会合法
        # 落进新空间（静默丢历史 + rowId 撞号）。账本 seq 无法推算该值
        # （wseq 与 seq 的偏移逐代累积），必须持久化。
        self._wseq_hwm = 0
        # a116 十六次全审（F3-1/F3-2 根修）：wseq 高水位**同步**落独立小文件。
        # 为什么不能靠 meta 的异步 sync_meta：
        #   ① 冷建补放走的是 feed.ingest→_commit，不经 v4_ingest_main，
        #      异步路径根本不知道有变更（实测 40 条补放的 wseq 从不落盘）；
        #   ② 异步窗口内崩溃，重启 base = persisted+2 可能 ≤ 客户端游标，
        #      首批新事件拿到已被消费的 wseq → 静默吞消息（实测 lag≥3 丢 1-2 条）。
        # 独立小文件（每 sid 一个，几十字节）同步写，代价远低于全量 meta
        # 读盘+合并+原子写；且删除会话时随 meta 一起清，不会复活幽灵。
        self._wseq_path = os.path.join(_WSEQ_DIR, "%s.wseq" % _safe_name(sid))
        self._wseq_written = 0          # 已落盘值（避免无变更重复写）
        self._wseq_fd = None            # 常开的定长覆盖句柄（见 _save_wseq）
        self._wseq_closed = False       # 会话删除后置位：拒绝重建孤儿文件
        self._load_wseq()
        self.compacted_events = 0       # microcompact 命中计数（stats/测试观测）
        self.projection = _reducer.initial_projection(sid)

    # ---- wseq 高水位持久化（a116 十六次全审）----
    @property
    def wseq_hwm(self):
        return self._wseq_hwm

    @wseq_hwm.setter
    def wseq_hwm(self, v):
        """**同步**落盘：所有写入方（v4feed._commit 的 live 与冷建补放、
        restore、v4hub）一律经过这里，不存在「某条路径忘了持久化」。
        只写增长值（`_save_wseq` 内部比 `_wseq_written`）。"""
        v = int(v or 0)
        self._wseq_hwm = max(self._wseq_hwm, v)
        self._save_wseq(self._wseq_hwm)

    def _load_wseq(self):
        try:
            with open(self._wseq_path, encoding="utf-8") as f:
                self.wseq_hwm = max(self._wseq_hwm,
                                    int((f.read() or "0").strip()))
        except Exception:
            pass
        self._wseq_written = self._wseq_hwm

    def close_wseq(self):
        """释放常开句柄并**永久关停**本对象的 wseq 落盘（会话删除时调）。
        幂等。置 `_wseq_closed` 后，在飞的 `_commit` 迟到调 setter 也不会
        `O_CREAT` 重建孤儿文件（十六次全审，一般级）。"""
        with _WSEQ_FD_LOCK:
            self._wseq_closed = True
            fd, self._wseq_fd = self._wseq_fd, None
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass

    def _read_disk_wseq(self):
        """读盘上当前高水位（供跨对象单调守卫用）。失败返回 0。"""
        try:
            with open(self._wseq_path, encoding="utf-8") as f:
                return int((f.read() or "0").strip() or 0)
        except Exception:
            return 0

    def _save_wseq(self, v):
        """同步落盘。**性能关键**：常开 fd + 定长文本覆盖写（实测 0.01ms，
        而 ``open+write+os.replace`` 是 15ms——流式 token 每秒数十条事件，
        后者会直接拖垮对话）。

        定长编码：20 位零填充整数。高位补零后写入，读侧 ``int()`` 天然吃
        前导零；字符串总是 20 字节，``lseek(0)+write`` 完整覆盖旧值，不会
        出现「新值比旧值短 → 尾部残留旧数字」（如 1000 覆盖 999 变 10009）。

        失败不抛：持久化是正确性增强而非前置条件。但**失败必须留痕**
        （十六次全审：实测静默失败 → 重启后旧游标被放行 → 40 条消息
        全部静默丢失且无任何日志）。调用方另有账本 seq 作第二下界，
        见 v4hub 建 feed 处的 `max(wseq_hwm, last_seq)`。"""
        v = int(v)
        blob = ("%020d" % v).encode("ascii")
        with _WSEQ_FD_LOCK:      # 守卫 + lseek+write 必须整体原子
            # 单调守卫必须在锁内（十六次全审，一般级）。
            # 二十一次全审（一般级）：守卫还必须**读当前盘值**——`_wseq_written`
            # 是每对象私有的，GC 重建窗口内同一 sid 可短暂并存两个 store
            # （旧对象仍被在飞 `_commit` 持有）→ 旧对象的小值会覆盖新对象的
            # 大值（实测 a=100,b=500,a=300 后盘上 300）。
            if not v or v <= self._wseq_written:
                return
            if self._wseq_closed:
                return           # 会话已删除：不再重建孤儿文件
            disk = self._read_disk_wseq()
            if disk and v <= disk:
                self._wseq_written = disk      # 同步本对象视图，避免重复尝试
                return
            try:
                if self._wseq_fd is None:
                    os.makedirs(_WSEQ_DIR, exist_ok=True)
                    self._wseq_fd = os.open(
                        self._wseq_path,
                        os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                        0o644)
                os.lseek(self._wseq_fd, 0, os.SEEK_SET)
                n = os.write(self._wseq_fd, blob)
                if n != len(blob):          # 短写（理论上普通文件不会）
                    raise OSError("short write %r/%r" % (n, len(blob)))
                self._wseq_written = v
            except Exception:
                # 句柄失效（目录被清/权限变/满盘）→ 丢弃，下次重建
                try:
                    if self._wseq_fd is not None:
                        os.close(self._wseq_fd)
                except Exception:
                    pass
                self._wseq_fd = None
                # 首次失败打一次警告（不刷屏）：这条日志是「持久化已不可信，
                # 依赖账本 seq 下界兜底」的唯一现场线索。
                if not getattr(self, "_wseq_warned", False):
                    self._wseq_warned = True
                    try:
                        _log.warning(
                            "v4 wseq 高水位落盘失败 path=%s（后续降级为"
                            "账本 seq 下界兜底，不再重复告警）",
                            self._wseq_path, exc_info=True)
                    except Exception:
                        pass

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
                    "epoch": self.epoch, "evicted": self.evicted_events,
                    "bytes": self._bytes, "compacted": self.compacted_events}

    # ---- 写入 ----
    def append(self, item, turn=None, now_ms=None):
        """信封注入 + 锁内分配 seq + 落缓冲 + 瞬态淘汰 + 投影归约。

        返回盖好章的事件（调用方拿去广播——先落 store 再广播，对照
        v4-bridge.ts:529 的顺序约定）。item 本体不被持有（make_envelope
        已拷贝）。
        """
        import time as _time
        import json as _json
        now_ms = now_ms if now_ms is not None else int(_time.time() * 1000)
        with self._lock:
            self._last_seq += 1
            env = make_envelope(item, self.sid, self.epoch, turn)
            env["seq"] = self._last_seq
            self._events.append(env)
            try:
                self._bytes += len(_json.dumps(env, ensure_ascii=False))
            except Exception:
                self._bytes += 256       # 不可序列化事件的粗估兜底
            if len(self._events) == self.retention:
                # deque 满后再 append 会自动丢最老；这里同步推进 floor
                self._floor_seq = self._events[0]["seq"] - 1
            # v3.1（#13）：新回合开跑 = 旧回合定格，此刻判定是否折叠旧负载
            if env.get("type") == "turn_started":
                self._maybe_compact(env.get("turn"))
            # turn 窗口瞬态淘汰（本期 TRANSIENT 集合为空，机制预埋）
            evict_turns = self.retention_policy.on_append(env, now_ms)
            if evict_turns:
                self._evict_transient(set(evict_turns))
            self.projection = _reducer.apply_event(self.projection, env)
            return env

    # ---- microcompact（#13）----
    def _maybe_compact(self, current_turn):
        """保留窗字节超阈时折叠**旧回合**的超大 cli_stream 负载。

        就地改 deque 内事件（锁内、单线程安全）：正文/工具输出块留头尾
        COMPACT_KEEP 字符，标记 _folded 便于消费端识别。live 已广播流零
        影响——折叠只利好 replay/慢订阅补发与内存占用。
        """
        if self._bytes <= COMPACT_BYTES or not current_turn:
            return
        import json as _json
        for env in self._events:
            if env.get("_folded") or env.get("type") != "cli_stream":
                continue
            if env.get("turn") in (None, current_turn):
                continue
            try:
                if len(_json.dumps(env, ensure_ascii=False)) <= COMPACT_EVENT_BYTES:
                    continue
            except Exception:
                continue
            data = env.get("data")
            if not isinstance(data, dict):
                continue
            msg = data.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            blocks = content if isinstance(content, list) else None
            saved = 0
            if blocks is not None:
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and isinstance(b.get("text"), str):
                        new, drop = _fold_text(b["text"])
                        if drop:
                            b["text"] = new
                            saved += drop
                    elif b.get("type") == "tool_result":
                        c = b.get("content")
                        if isinstance(c, str):
                            new, drop = _fold_text(c)
                            if drop:
                                b["content"] = new
                                saved += drop
                        elif isinstance(c, list):
                            for cb in c:
                                if isinstance(cb, dict) and cb.get("type") == "text" \
                                        and isinstance(cb.get("text"), str):
                                    new, drop = _fold_text(cb["text"])
                                    if drop:
                                        cb["text"] = new
                                        saved += drop
            if isinstance(content, str):
                new, drop = _fold_text(content)
                if drop:
                    msg["content"] = new
                    saved += drop
            if saved > 0:
                env["_folded"] = True
                env["folded_bytes"] = saved
                data["_folded"] = True
                self._bytes = max(0, self._bytes - saved)
                self.compacted_events += 1

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
            self._bytes = 0                 # 缓冲清空，字节估算归零（#13）
            self._floor_seq = self._last_seq
            self.projection = _reducer.initial_projection(self.sid)

    def restore(self, epoch, seq, wseq_hwm=0):
        """会话对象被重建（闲置回收/重启后 _get_or_create）时续号续代。

        meta 有 epoch → 沿用（GC 重建不是日志重写，代际不变，前端快照的
        base 仍可 resume）；无 epoch（升级前旧 meta）→ 新代（前端旧水位
        作废，走 snapshot 重建一次，代价一次性）。
        """
        with self._lock:
            self.epoch = epoch or new_epoch()
            self._last_seq = max(self._last_seq, int(seq or 0))
            self._floor_seq = self._last_seq
            # v4 投递序号高水位跨重启续用（见 __init__ 注释）
            self.wseq_hwm = max(self.wseq_hwm, int(wseq_hwm or 0))
            self._save_wseq(self.wseq_hwm)
