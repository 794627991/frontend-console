# -*- coding: utf-8 -*-
"""v4 投影 feed：CLI 事件 → 行 delta 归约 + delta log + 订阅帧（拉模式）。

对照 ZCode bootstrap/zcode-protocol-v4/{product-projection,
conversation-topic-publisher}.ts 的 SSE 化移植（v4 线，2026-10-20 重构）：

- V4Feed 每会话一只（主会话 + 每个子代理各一只）。ingest(env) 把信封
  事件归约成封闭五操作 delta，用 v4proto.apply 推进自身快照（投影与
  delta 流逐字节一致是构造保证——服务端快照就是 apply 的产物）。
- 发布采用「共享 delta log + 订阅者游标」而非逐订阅者 push buffer：
  SSE 生成器每 30ms（FLUSH_MS）拉 frames_after(sent_seq)，对区间内 delta
  做 coalesce 打一帧。订阅者落后越出保留窗（floor）→ 拉 None → 发
  snapshot 帧重对齐（服务端单方裁决整窗替换，客户端没有猜结构路径）。
- 挂接顺序（persist-before-publish）：HarnessSession.emit → log.emit
  （store 锁内 seq 落账）→ 本 feed.ingest(env)。前端永远只消费投影。
- epoch：/rewind bump_epoch 时 feed 重建（_reset），旧订阅携旧 epoch
  重连只能拿 snapshot。
- 子代理 feed（V4AgentFeeds）：watcher 扫描 CLI 子代理转写 jsonl 的增量
  行 → feed_jsonl_line 归约入子投影；首次访问（hydrate）从文件全量重建。
  子投影与主投影共用 V4Feed 的行模型与帧协议——子 pane 与主窗口同管线。

行粒度对齐（.hg-unify-plan.md 核对结论）：assistant text/thinking 块级
一行；tool_use 一行、tool_result 终态 upsert；CLI 不开 partial 流式，
文本块一次到达（row.delta 预留流式能力，当前主要消费方是 coalesce 后
的批量 append——协议位留足，CLI 开 partial 即生效）。
"""
import json
import threading

from . import v4proto as P

FLUSH_MS = 30                  # 订阅帧合并窗口（ZCode continuous profile）
LOG_RETAIN = 600               # delta log 保留条数（越窗订阅者转 snapshot）
# a41c 退役：TAIL_ROWS 行数闸删除（与回合窗并存必打架，见 snapshot_wire
# 注释）；wire_snapshot 的 tail 参数保留仅供单测直接调用


def _txt(content):
    """CLI content 块列表 → 纯文本（str 直通；list 拼 text 块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "\n".join(parts)
    return ""


def _input_brief(inp, limit=2000):
    """tool_use input → 展示用摘要 JSON（保序截断）。"""
    try:
        s = json.dumps(inp, ensure_ascii=False)
    except Exception:
        s = str(inp)
    return s[:limit]


def _in_obj(inp, cap=4000):
    """tool_use input → 可渲染对象（浅拷贝，超长字符串值截断防爆）。"""
    if not isinstance(inp, dict):
        return {}
    out = {}
    for k, v in inp.items():
        if isinstance(v, str) and len(v) > cap:
            out[k] = v[:cap] + "…"
        else:
            try:
                json.dumps(v, ensure_ascii=False)
                out[k] = v
            except Exception:
                out[k] = str(v)
    return out


class V4Feed(object):
    """单会话投影 feed（主会话与子代理共用）。线程安全：ingest 与取帧
    并发（ingest 来自 session 线程，取帧来自 SSE 生成器），锁内推进。"""

    def __init__(self, epoch="", hydrate=None):
        self._lock = threading.Lock()
        self._reset(epoch, hydrate)

    def _reset(self, epoch, hydrate=None):
        self.epoch = epoch
        self.snap = P.new_snapshot(epoch)
        self._row_id = 0
        self._log = []                 # [(seq, [delta,...]), ...]
        self._floor_seq = 0            # log 内最老条目的 seq（0=空）
        self._pending_tools = {}       # tool_use id -> rowId（终态配对）
        self._pending_agents = {}      # Task tool_use id -> (sub行, tool行)
        self._exit_marker_row = None   # 最近 exit marker 行（interrupted 合并锚）
        self._turn_rows = {}           # turnId -> turn_header rowId
        self._hydrate = hydrate        # 冷启动重建回调（snapshot 空时调用）
        self._hydrated = False
        self._hyd_keys = set()         # hydration 已呈现行的内容指纹（去重）
        self._hyd_max_at = 0           # hydration 全部行的最大时刻（去重上界）
        self._held = False             # 后台子代理 hold（result 不提前收口）
        self._replay = False           # 水位补放阶段（历史重复行过滤）
        if hydrate:
            hydrate(self)              # 重建路径直接填 snapshot（不发 delta）

    # ------------------------------------------------------------------
    # 行构造（reducer 内部）
    # ------------------------------------------------------------------
    def _row(self, turn, kind, at, at_seq, **fields):
        self._row_id += 1
        row = P.mk_row(self._row_id, turn or "", kind, at, at_seq, **fields)
        return P.d_row_appended(row), self._row_id

    def _upsert(self, row_id, **fields):
        """按 rowId 换整行（保留行原有字段——从当前快照行取）。"""
        for r in self.snap["rows"]:
            if r["rowId"] == row_id:
                nr = dict(r)
                nr.update(fields)
                return P.d_row_upserted(nr), nr
        return None, None

    # ------------------------------------------------------------------
    # ingest：信封事件 → deltas（主会话 reducer）
    # ------------------------------------------------------------------
    def ingest(self, env):
        t = env.get("type")
        # 字段合并视图：V3 事件的业务字段有两种布局——user_echo/renew/peer/
        # queue 族在**信封顶层**（session.py emit {"kind":"user_echo",
        # "text":...}），cli_stream 族在 data 里。只查 data 会全部取空
        # （实测 a17：用户消息行 text 全空=气泡空白根因）。合并：顶层非信封
        # 字段打底，data 覆盖（cli_stream 的 data 无顶层重名，安全）
        data = env.get("data") if isinstance(env.get("data"), dict) else {}
        _top = {k: v for k, v in env.items()
                if k not in ("type", "kind", "seq", "ts", "epoch",
                             "sid", "turn", "data")}
        if _top:
            _m = dict(_top)
            _m.update(data)
            data = _m
        seq = env.get("seq") or 0
        turn = env.get("turn") or ""
        ts = env.get("ts") or 0
        ds = []
        with self._lock:
            if t == "user_echo":
                self._exit_marker_row = None   # 新回合=合并锚失效
                if self._dup_hist("user_input", data.get("text"), ts):
                    return                # 补放与 hydration 重叠：不重画
                hd, _hr = self._ensure_header(turn, ts, seq)
                if hd:
                    ds.append(hd)     # 组头先于用户气泡（顺序即渲染序）
                d, _ = self._row(turn, "user_input", ts, seq,
                                 text=data.get("text") or "",
                                 files=data.get("files") or [],
                                 images=data.get("images") or 0,
                                 cmd=data.get("cmd") or "")
                ds.append(d)
            elif t == "cli_stream":
                ds = self._reduce_cli(data, turn, ts, seq)
            elif t == "turn_started":
                if turn and turn not in self._turn_rows:
                    d, rid = self._row(turn, "turn_header", ts, seq,
                                       state="running",
                                       model=data.get("model") or "",
                                       startedAt=ts)
                    ds.append(d)
                    self._turn_rows[turn] = rid
                ds.append(P.d_state({"busy": True, "curTurn": turn}))
            elif t == "turn_complete":
                rid = self._turn_rows.get(turn)
                if rid is None and turn:
                    hd, rid = self._ensure_header(turn, ts, seq)
                    if hd:
                        ds.append(hd)
                if rid:
                    d, _ = self._upsert(rid, state="success",
                                        endedAt=ts,
                                        activeMs=data.get("duration_ms"))
                    if d:
                        ds.append(d)
                self._held = False
                ds.append(P.d_state({"busy": False}))
            elif t == "turn_hold":
                # 后台子代理在飞：result 已到但回合未完（session 不发
                # turn_complete）——标记后 _reduce_cli 的 result 兜底不收口
                self._held = True
            elif t == "turn_error":
                rid = self._turn_rows.get(turn)
                if rid:
                    d, _ = self._upsert(rid, state="error", endedAt=ts,
                                        err=data.get("brief") or "")
                    if d:
                        ds.append(d)
                ds.append(P.d_state({"busy": False}))
                self._held = False    # 与 turn_complete 对称：hold 不跨回合残留
            elif t == "interrupted":
                d, _ = self._row("", "marker", ts, seq,
                                 mkind="interrupted", text=data.get("text") or "")
                ds.append(d)
                rid = self._turn_rows.get(self.snap["state"].get("curTurn"))
                if rid:
                    d2, _ = self._upsert(rid, state="cancelled", endedAt=ts)
                    if d2:
                        ds.append(d2)
                ds.append(P.d_state({"busy": False}))
            elif t == "subagent_started":
                hd, _hr = self._ensure_header(turn, ts, seq)
                if hd:
                    ds.append(hd)
                agent = data.get("task_id") or data.get("aid") or ""
                _tid = data.get("tid") or ""
                _inp = data.get("input") or {}
                d, rid = self._row(turn, "subagent", ts, seq,
                                   tid=_tid,
                                   agentType=data.get("type") or "Agent",
                                   status="running",
                                   summary=(data.get("desc")
                                            or _inp.get("description") or ""),
                                   childTopic="sub:" + agent if agent else "")
                ds.append(d)
                # Task tool_use 行同时开（结论回写锚点）。tid 必带——前端
                # renderToolUse/renderOneToolResult 全靠它配对 rowById（缺tid
                # =行卡无名/秒表永跑/终态不收口，用户实测致命问题根因）
                td, trid = self._row(turn, "tool_call", ts, seq,
                                     tid=_tid,
                                     tool=data.get("tool") or "Task",
                                     status="running",
                                     input=_input_brief(_inp),
                                     startedAt=ts)
                ds.append(td)
                if _tid:
                    self._pending_agents[_tid] = (rid, trid)
            elif t == "subagent_result":
                tid = data.get("tid") or ""
                pair = self._pending_agents.pop(tid, None)
                ok = bool(data.get("ok"))
                if pair:
                    srid, trid = pair
                    d, _ = self._upsert(srid,
                                        status="success" if ok else "failed",
                                        summary=data.get("brief") or "",
                                        endedAt=ts)
                    if d:
                        ds.append(d)
                    d2, _ = self._upsert(trid,
                                         status="success" if ok else "error",
                                         output=data.get("brief") or "",
                                         endedAt=ts,
                                         dur=data.get("dur"))
                    if d2:
                        ds.append(d2)
            elif t == "peer":
                ds = self._reduce_peer(data, turn, ts, seq)
            elif t == "interrupted":
                # 中断与 exit 连发（杀进程中断=exit 先到 interrupted 后到）合并
                # 为一行：双行会在回放侧触发 turn_interrupted 编排两次建组
                #（store.js grpEnsure）——第二条凭空建空组定稿=「已工作 0 秒」
                # 孤儿组（用户实测）。V3 转写侧本就只补一条中断痕迹行
                text = data.get("text") or data.get("msg") or ""
                rid_ex = self._exit_marker_row
                if rid_ex:
                    d, _ = self._upsert(rid_ex, mkind="interrupted", text=text)
                else:
                    d, _ = self._row("", "marker", ts, seq,
                                     mkind="interrupted", text=text)
                if d:
                    ds.append(d)
            elif t == "sysnote":
                # 系统提示不占位（用户拍板 a39：「系统提示 · 已注入…」气泡
                # 当时只是没改）——skind 标记 task-notification（后台代理完成
                # 通知有摘要信息量，保留），纯注入提示行前端不画
                text = data.get("text") or data.get("msg") or ""
                _sk = ("task-notification"
                       if ("<task-notification" in text or "任务通知" in text)
                       else "")
                d, _ = self._row("", "marker", ts, seq, mkind=t, text=text,
                                 skind=_sk)
                ds.append(d)
            elif t in ("renew", "audit", "exit", "model_switched"):
                text = data.get("text") or data.get("msg") or ""
                d, rid = self._row("", "marker", ts, seq, mkind=t, text=text)
                ds.append(d)
                # 记录最近 exit marker 行（interrupted 合并锚；新 exit 覆盖）
                if t == "exit":
                    self._exit_marker_row = rid
            elif t == "ask":
                # 交互提问进 A 区（V3 形态=挂 dock 的 askRender 面板，非消息行）；
                # 前端 v4view paintState 消费。幂等：askRender 同 req_id 查重。
                ds.append(P.d_state({"ask": {
                    "req_id": data.get("req_id") or "",
                    "title": data.get("title") or "",
                    "questions": data.get("questions") or [],
                }}))
            elif t == "ask_done":
                ds.append(P.d_state({
                    "ask": None,
                    "ask_done": {"req_id": data.get("req_id") or "",
                                 "answer": data.get("answer")},
                }))
            elif t in ("input_admitted", "input_promoted", "input_discarded"):
                # queue 真源在 durable 排队账本；仅当事件携带全量 queue 时才
                # 更新 A 区（否则等路由订阅时冷填）
                if isinstance(data.get("queue"), list):
                    ds.append(P.d_state({"queue": data["queue"]}))
            if not ds:
                return
            P.apply_deltas(self.snap, ds)
            self.snap["seq"] = seq
            self._log.append((seq, ds))
            self._trim()

    def _dup_hist(self, kind, text, at=0):
        # 补放期去重：该行是否已由 hydration 呈现。
        #
        # 单一方向边界（不是 ±5s 绝对值）：hydration 读的是「创建 feed 时刻
        # 已落盘的转写」，其最大行时刻 = _hyd_max_at。同一条事件的 jsonl 行
        # 与账本补放行的时刻同源，必然 at <= _hyd_max_at + 容差；而用户此后
        # 重发同文本的新消息 at 必然更大 → 不会被误杀（round-2 的 ±5s 双向
        # 窗口会误杀「5s 内原样重发」）。
        # 容差 2s：jsonl 的 ts 由 CLI 打、env ts 由 harness emit 时打，同一条
        # 事件两者可差数百毫秒。
        # 已知残留：同文本且在 hydration 末行 2s 内的新消息仍会被当作重复
        # （仅 feed 冷建的那一次补放窗内，窗口极窄）。
        if not self._replay or not self._hyd_keys:
            return False
        if (kind, (text or "")[:200]) not in self._hyd_keys:
            return False
        if at and self._hyd_max_at:
            return at <= self._hyd_max_at + 2000
        return True

    @staticmethod
    def _is_sub_mirror(o):
        """子代理镜像/注入行判据（对齐 sse.js 的既有分层口径）。

        红线：子代理正文/工具绝不允许进主投影。CLI 把子代理事件镜像到主
        会话 stdout（带 parent_tool_use_id），旧 handleEvent 靠这些字段分流
        到子窗格；v4 主 feed 若不过滤，子内容会直接流进主窗口。

        分层（与 sse.js:285/697 与 :30 一致——不做统一加宽，防误杀主链）：
        - assistant/user/result 等业务事件：parent_tool_use_id / isSidechain
        - system 生命周期事件：另加 agent_id（嵌套派发的唯一标记）
        """
        if o.get("parent_tool_use_id") or o.get("isSidechain"):
            return True
        return o.get("type") == "system" and bool(o.get("agent_id"))

    def _ensure_header(self, turn, ts, seq, model=""):
        """组头懒建（turn_started 缺失兜底）：任何带 turn 的行到达时补建，
        否则组头永远不出现（「工作组头不出现」红线的构造性防线）。"""
        if not turn or turn in self._turn_rows:
            return None, None
        d, rid = self._row(turn, "turn_header", ts, seq,
                           state="running", model=model, startedAt=ts)
        self._turn_rows[turn] = rid
        return d, rid

    def _reduce_cli(self, data, turn, ts, seq):
        """CLI stream-json 事件 → deltas。"""
        ds = []
        if self._is_sub_mirror(data):
            return ds                     # 子代理镜像行：不进主投影（红线）
        typ = data.get("type")
        if typ == "assistant":
            m = data.get("message") or {}
            model = m.get("model") or ""
            hd, _hr = self._ensure_header(turn, ts, seq, model)
            if hd:
                ds.append(hd)
            for b in (m.get("content") or []):
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text" and (b.get("text") or "").strip():
                    d, _ = self._row(turn, "assistant_text", ts, seq,
                                     text=b["text"], model=model)
                    ds.append(d)
                elif bt == "thinking" and (b.get("thinking") or "").strip():
                    d, _ = self._row(turn, "reasoning", ts, seq,
                                     text=b["thinking"])
                    ds.append(d)
                elif bt == "tool_use":
                    name = b.get("name") or ""
                    d, rid = self._row(turn, "tool_call", ts, seq,
                                       tool=name, status="running",
                                       input=_in_obj(b.get("input") or {}),
                                       startedAt=ts,
                                       tid=b.get("id") or "")
                    ds.append(d)
                    if b.get("id"):
                        self._pending_tools[b["id"]] = rid
        elif typ == "user":
            m = data.get("message") or {}
            for b in (m.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    rid = self._pending_tools.pop(b.get("tool_use_id"), None)
                    if rid is None:
                        continue
                    err = bool(b.get("is_error"))
                    out = _txt(b.get("content"))[:8000]
                    # a48（用户定调「回答形态要 a42 效果」）：ask_user 的
                    # 回答在后端人类可读化——原始 JSON {"问题":"答案"} →
                    # 「📝 回答：问题 → 答案；…」。数据在后端整合（红线），
                    # 前端 live/回放/体全场景直接吃到成品文本
                    _tn = next((r.get("tool") for r in self.snap["rows"]
                                if r["rowId"] == rid), "")
                    if _tn == "mcp__harness__ask_user" and not err:
                        try:
                            _oj = json.loads(out)
                            if isinstance(_oj, dict):
                                out = "；".join(
                                    "%s → %s" % (k, v)
                                    for k, v in _oj.items()) or out
                        except Exception:
                            pass
                        out = "📝 回答：" + out
                    d, _ = self._upsert(
                        rid, status="error" if err else "success",
                        output=out,
                        endedAt=ts)
                    if d:
                        ds.append(d)
        elif typ == "system":
            # a52：压缩状态事件（{"type":"system","subtype":"status",
            # "status":"compacting"|"requesting"}）进 A 区 state——v4 归一后
            # per-sid 投影天然隔离（V3 全局 _HG.compacting 串台根因消除）；
            # 前端 bridge 消费置 _HG.compacting/compactT0 并驱动压缩线
            if data.get("subtype") == "status":
                _st = data.get("status") or ""
                if _st == "compacting" and not self.snap["state"].get("compacting"):
                    self.snap["state"]["compacting"] = True
                    self.snap["state"]["compactT0"] = ts or int(ts) or 0
                    ds.append(P.d_state({"compacting": True,
                                         "compactT0": ts or 0}))
                elif _st != "compacting" and self.snap["state"].get("compacting"):
                    self.snap["state"]["compacting"] = False
                    ds.append(P.d_state({"compacting": False}))
            m = data.get("message") or {}
            md = m.get("model") or ""
            if md:
                ds.append(P.d_state({"model": md}))
        elif typ == "result":
            # 兜底收口：turn_started/turn_complete 缺失（CLI 自发回合、旧版
            # CLI）时也要有组头终态——否则前端组永远停在「工作中」。hold 期
            # （后台子代理在飞）session 不发 turn_complete，结果帧照常到达，
            # 此时**不**收口（避免组头提前 success 而 busy 仍 True）。
            if getattr(self, "_held", False):
                return ds
            rid = self._turn_rows.get(turn) if turn else None
            if rid:
                d, _ = self._upsert(rid, state="error" if data.get("is_error")
                                    else "success", endedAt=ts,
                                    activeMs=data.get("duration_ms"))
                if d:
                    ds.append(d)
        return ds

    def _reduce_peer(self, data, turn, ts, seq):
        """peer 族（session.py emit {kind:'peer', name, text, to}——name 含
        「识图」=识图会话回传代播）。字段按后端真身取：旧 title/brief 从未
        匹配过（回传正文全丢）；识图发起不在此处——走 cli_stream 的识图
        tool_use（V3 同源：sse.js 双通道工具名分支建卡起表）。"""
        ds = []
        d, _ = self._row("", "peer_notify", ts, seq,
                         name=data.get("name") or "其他会话",
                         text=(data.get("text") or "")[:8000],
                         to=data.get("to") or "")
        ds.append(d)
        return ds

    # ------------------------------------------------------------------
    # 子代理 jsonl 行归约（watcher 增量与 hydrate 共用）
    # ------------------------------------------------------------------
    def feed_jsonl_line(self, obj):
        """CLI 转写 jsonl 单行（dict）→ deltas 入子投影。返回是否消费。"""
        if not isinstance(obj, dict):
            return False
        ds = []
        seq = self.snap["seq"] + 1
        ts = 0
        try:
            import time as _t
            ts = int(_t.time() * 1000)
        except Exception:
            pass
        typ = obj.get("type")
        with self._lock:
            if typ == "result":
                self.snap["state"]["done"] = True
                self.snap["state"]["final"] = (obj.get("result") or "")[:8000]
                self.snap["state"]["err"] = bool(obj.get("is_error"))
                ds.append(P.d_state({"done": True,
                                     "final": self.snap["state"]["final"],
                                     "err": self.snap["state"]["err"]}))
            elif typ in ("assistant", "user"):
                m = obj.get("message") or {}
                content = m.get("content")
                blocks = content if isinstance(content, list) else []
                if typ == "assistant":
                    model = m.get("model") or ""
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt == "text" and (b.get("text") or "").strip():
                            d, _ = self._row("s", "assistant_text", ts, seq,
                                             text=b["text"][:2000], model=model)
                            ds.append(d)
                        elif bt == "thinking" and (b.get("thinking") or "").strip():
                            d, _ = self._row("s", "reasoning", ts, seq,
                                             text=b["thinking"][:2000])
                            ds.append(d)
                        elif bt == "tool_use":
                            if b.get("name") == "SubagentHandback":
                                # 结论单一真源：只进 state.final（不落行流），
                                # 否则子 pane 时间线与结论区会各画一份（红线）
                                rep = ""
                                for v in (b.get("input") or {}).values():
                                    if isinstance(v, str) and len(v) > len(rep):
                                        rep = v
                                if rep.strip():
                                    self.snap["state"]["final"] = rep[:8000]
                                    ds.append(P.d_state({"final": rep[:8000],
                                                         "done": True}))
                                    continue
                            d, rid = self._row("s", "tool_call", ts, seq,
                                               tool=b.get("name") or "",
                                               status="running",
                                               tid=b.get("id") or "")
                            ds.append(d)
                            if b.get("id"):
                                self._pending_tools[b["id"]] = rid
                else:
                    t = _txt(content).strip()
                    if t and not t.startswith("<"):
                        d, _ = self._row("s", "user_input", ts, seq, text=t[:1200])
                        ds.append(d)
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            rid = self._pending_tools.pop(
                                b.get("tool_use_id"), None)
                            if rid is None:
                                continue
                            err = bool(b.get("is_error"))
                            d, _ = self._upsert(
                                rid, status="error" if err else "success",
                                output=_txt(b.get("content"))[:8000],
                                endedAt=ts)
                            if d:
                                ds.append(d)
            if not ds:
                return False
            P.apply_deltas(self.snap, ds)
            self.snap["seq"] = seq
            self._log.append((seq, ds))
            self._trim()
            return True

    def hydrate_jsonl(self, path):
        """从子代理转写文件全量重建（子投影冷启动）。"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        o = json.loads(raw)
                    except Exception:
                        continue
                    self.feed_jsonl_line(o)
            self._hydrated = True
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # 订阅帧（拉模式；SSE 生成器每 FLUSH_MS 调用）
    # ------------------------------------------------------------------
    def _trim(self):
        if len(self._log) > LOG_RETAIN:
            drop = len(self._log) - LOG_RETAIN
            del self._log[:drop]
            self._floor_seq = self._log[0][0] if self._log else 0

    def frames_after(self, after_seq):
        """(after_seq, last] 合并帧。越窗/落后 → None（调用方发 snapshot）。
        epoch 校验由路由层做（base.epoch != feed.epoch → 直接 snapshot）。"""
        with self._lock:
            if after_seq < self._floor_seq:
                return None
            ds = []
            for seq, dl in self._log:
                if seq > after_seq:
                    ds.extend(dl)
            if not ds:
                return None
            return P.coalesce(ds), self.snap["seq"]

    def snapshot_wire(self):
        with self._lock:
            # a41c（用户定调「放大不是办法」）：回合窗是唯一裁剪——行数闸
            # 删除（TAIL_ROWS 退役）。投影「行」有天然上界（一轮=思考段+工具
            # 调用+正文，工具输出截断在字段级非行级），不存在单轮爆行需兜的
            # 场景；行数闸与回合闸并存必打架（a41 实锤 21 回合恰卡 400 行被
            # 二次裁回 10 轮，a41b 放大只是把打架阈值后挪）。21=V3 窗 20 轮+1
            #（多 1 轮做前端 start>0 归档条判定锚）
            return P.wire_snapshot(self.snap, tail_turns=21)

    @property
    def last_seq(self):
        with self._lock:
            return self.snap["seq"]
