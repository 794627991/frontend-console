# -*- coding: utf-8 -*-
"""子代理注册表（refactor/subagent-registry 阶段1）。

设计定调（用户通牒「彻底重构，必须完全符合要求」）：以**真实 agentId 为主键**
的会话级权威清单。此前前端 10+ 处 ad-hoc 归一（_subTid 三向反查/peerSent/
subTidRes/链式 done 判定……）是历次「续派两个子代理/假完成/名字不对」实锤的
共同温床——三套 id（tool_use_id / CLI 包装 task_id / 真实 agentId）的归一
收敛到本模块一处，前端全部视图从注册表派生。

数据流：
  reader 线程 4 个钩子增量维护（session.py 调用）
    ① Task/Agent tool_use → 建临时条目（键=派发 tid，agentId 未知）
    ② Task tool_result → 提取 agentId → 条目迁移到 agentId 键（此后稳定）
    ③ SendMessage tool_use → to 归链（agentId 直连/角色名经 ids 映射）建轮
    ④ task_started/task_notification → 状态/t0/rounds/tid 补记
  GET /api/harness/agents?sid= → 下发注册表 + tidMap（SSE live 帧映射用）
  进程重启（内存灭/CLI 子代理同死）→ 首查扫主会话转写静态重建

纯内存（与 _bg_tasks/proj 同生命周期），线程安全由 session 侧 _registry_lock
保证（reader 线程写 / HTTP 线程读）。
"""
import re
import threading

# agentId/工具回执提取（与 routes.py /subagent_resolve、transcript.py
# _inject_subagent_blocks 同源正则——三处共用一套事实口径）
_RE_AGENT_ID = re.compile(r"[0-9a-zA-Z_-]{8,64}")
_RE_RES_AGENT = re.compile(r"resumedAgentId[\"'\s:]+([0-9a-zA-Z_-]{8,64})")
_RE_AGENT_JSON = re.compile(r"agentId[\"'\s:]+([0-9a-zA-Z_-]{8,64})")


def _looks_id(s):
    return bool(s) and bool(_RE_AGENT_ID.fullmatch(str(s)))


class AgentRegistry(object):
    """每会话一只（HarnessSession 持有）。键=agentId（首轮迁移后稳定）；
    迁移前以派发 tid 临时为键（found=False 标记，前端可显示但不可回放）。"""

    def __init__(self):
        self._ag = {}        # agentId(或临时 tid) -> 条目 dict
        self._tid_map = {}   # tid/tool_use_id -> agentId（live 帧归一表）
        self._sm_tids = set()   # SendMessage tool_use tid（回执≠完成，见 on_task_result）
        self._lock = threading.Lock()
        self._rebuilt = False   # 重启后扫转写重建已执行（一次）

    # ---- 增量钩子（reader 线程）----

    def on_task_dispatch(self, tid, agent_type, desc, ts_ms):
        """① Task/Agent tool_use 到达——建临时条目（agentId 待 result 回填）。"""
        with self._lock:
            if tid in self._tid_map:      # 已归链（异常重放）幂等
                return
            self._ag["pending:" + tid] = {
                "agentId": "", "found": False, "type": agent_type or "Task",
                "desc": str(desc or "")[:200], "status": "running",
                "t0": ts_ms or 0, "doneAt": 0, "rounds": 1,
                "lastActive": ts_ms or 0, "tids": [tid],
                "tokens": 0, "toolN": 0, "brief": "",
            }

    def on_task_result(self, tid, result_text, err, ts_ms, tokens, tool_n):
        """② tool_result 回执。F4 修复（全审）：**只在 tid 已有 pending 或
        tidMap 命中时动作**——旧码无正则命中即凭空建 found=True 条目（Bash
        结果散文 "cannot find agentId foobar…" 也能铸幻影代理）。两类 tid：
        · Task 派发 tid：提 agentId 迁键 + 落终态；迁键成功**删除 pending
          键**（F2：旧码留的副本永不落终态=永 running 鬼影，前端 sparse
          覆写 live 富档）
        · SendMessage tid（_sm_tids 在场）：回执=送达确认**不是完成**——
          仅做 resumedAgentId 归链兜底（on_send_message 归链失败时此时
          才真正接链），绝不翻终态
        """
        tid = str(tid or "")
        m = _RE_AGENT_JSON.search(str(result_text or "")) \
            or _RE_RES_AGENT.search(str(result_text or ""))
        aid = m.group(1) if m else ""
        with self._lock:
            if tid in self._sm_tids:
                # SendMessage 回执：resumedAgentId 归链兜底（不落终态）
                self._sm_tids.discard(tid)
                known = self._tid_map.get(tid)
                if (not known) and aid and (aid in self._ag):
                    self._on_send_link(tid, aid, None, ts_ms)
                elif (not known) and aid and _looks_id(aid) and (aid not in self._ag):
                    # 跨会话纯续派（本会话无首轮）——轻条目（转写侧同源事实）
                    self._ag[aid] = {
                        "agentId": aid, "found": True, "type": "SendMessage",
                        "desc": "", "status": "running",
                        "t0": ts_ms or 0, "doneAt": 0, "rounds": 1,
                        "lastActive": ts_ms or 0, "tids": [tid],
                        "tokens": 0, "toolN": 0, "brief": ""}
                    self._tid_map[tid] = aid
                return
            has_pend = ("pending:" + tid) in self._ag
            known = self._tid_map.get(tid)
            if not has_pend and not known:
                return          # F4：未派发过的 tid（Bash 等）一律不动作
            ent = None
            if has_pend:
                ent = dict(self._ag.get("pending:" + tid) or {})
            elif known:
                cur0 = self._ag.get(known)
                if cur0 is not None and tid in (cur0.get("tids") or []):
                    ent = dict(cur0)
            if aid:
                cur = self._ag.get(aid)
                if cur is None and ent is not None:
                    ent["agentId"] = aid
                    ent["found"] = True
                    self._ag[aid] = ent
                    cur = ent
                elif cur is None:
                    cur = self._ag[aid] = {
                        "agentId": aid, "found": True, "type": "Task",
                        "desc": "", "status": "running",
                        "t0": ts_ms or 0, "doneAt": 0, "rounds": 1,
                        "lastActive": ts_ms or 0, "tids": [],
                        "tokens": 0, "toolN": 0, "brief": ""}
                if tid not in cur["tids"]:
                    cur["tids"].append(tid)
                self._tid_map[tid] = aid
                # 复审F5残留②：旧 CLI 形态 task_started 曾把 wrapper task_id
                # 采纳为键（has_pend 门卫内的合法路径）——回执提取出真实
                # agentId 迁真键后，wrapper 键条目若只挂本 tid 则为孤儿
                #（永 running），一并清扫
                if known and known != aid:
                    old = self._ag.get(known)
                    if old is not None and old.get("tids") == [tid]:
                        self._ag.pop(known, None)
                cur["status"] = "err" if err else "done"
                cur["doneAt"] = ts_ms or 0
                cur["lastActive"] = ts_ms or 0
                if tokens:
                    cur["tokens"] = tokens
                if tool_n:
                    cur["toolN"] = tool_n
                # F2：迁键成功——pending 临时键删除（终态已落真键，副本
                # 留守=永 running 鬼影）
                self._ag.pop("pending:" + tid, None)
            elif ent is not None:
                # 无 id 可提（CLI 异常形态）——临时条目直接落终态（前端不回放）
                ent["status"] = "err" if err else "done"
                ent["doneAt"] = ts_ms or 0
                self._ag["pending:" + tid] = ent

    def on_send_message(self, tid, to, message_first_line, ids_map, ts_ms):
        """③ SendMessage tool_use——to 归链建轮。归链判定顺序（F1 修复后
        ids_map=session 反转的角色→agentId）：
          ① ids_map 命中优先
          ② to 本身是注册表现有键（to=agentId 直连续派——本工具自动补审
            指令的形态）
          ③ 都不中：tid 记入 _sm_tids——回执的 resumedAgentId 是归链
            第二机会（跨会话纯续派此刻才接链），不在此建条目
        """
        to = str(to or "").strip()
        tid = str(tid or "")
        with self._lock:
            if tid:
                self._sm_tids.add(tid)
                if len(self._sm_tids) > 256:
                    self._sm_tids.pop()   # frozenset 不可——用 set 的 pop（任意序，老 tid 大概率已完成）
            aid = str((ids_map or {}).get(to) or "")
            if not aid:
                aid = to if (to and to in self._ag) else ""
            if not aid:
                return
            self._on_send_link(tid, aid, message_first_line, ts_ms)

    def _on_send_link(self, tid, aid, message_first_line, ts_ms):
        """锁内归链建轮（on_send_message 与回执兜底共用）。"""
        cur = self._ag.get(aid)
        if cur is None:
            cur = self._ag[aid] = {
                "agentId": aid, "found": True, "type": "SendMessage",
                "desc": "", "status": "running",
                "t0": ts_ms or 0, "doneAt": 0, "rounds": 0,
                "lastActive": ts_ms or 0, "tids": [],
                "tokens": 0, "toolN": 0, "brief": ""}
        cur["rounds"] += 1
        cur["status"] = "running"
        cur["doneAt"] = 0
        cur["lastActive"] = ts_ms or 0
        if tid:
            cur["tids"].append(tid)
            self._tid_map[tid] = aid
        if message_first_line:
            # 任务名取最新续派轮的消息首行（用户要求胶囊显示任务名；
            # 首轮 desc 为空时也是兜底名源）
            cur["desc"] = str(message_first_line)[:200]

    def on_task_started(self, tid, agent_type, desc, task_id, bg, ts_ms):
        """④a task_started 系统事件——真子代理（subagent_type 非空）补记。
        F5 修复（全审）：task_id 真伪不可辨（CLI 包装 id 恰合 id 正则，
        10-sse.js:89 实证）——**只在 tid 已有 pending（Task 直派形态）或
        tidMap 命中（SendMessage 归链在先）时**才用 task_id 迁键/补记；
        无链不建任何 found 条目（wrapper 幻影绝迹——旧码给归链失败的
        包装 task_started 铸 found=True 第二条目=目录第二个「子代理」）。"""
        if not str(agent_type or "").strip():
            return          # 后台 shell 不入注册表（v3.4.43 定调）
        tid = str(tid or "")
        with self._lock:
            aid = self._tid_map.get(tid) or ""
            has_pend = ("pending:" + tid) in self._ag
            if not aid and has_pend and _looks_id(task_id):
                # 新版 CLI 首轮直派：task_id=真实 agentId（pending 在场=
                # Task tool_use 先到，链首身份可信）
                aid = str(task_id)
            if aid:
                cur = self._ag.get(aid)
                pend = self._ag.get("pending:" + tid) if has_pend else None
                if cur is None and not has_pend:
                    return   # 无 pending 且非已归链——不凭 task_id 建条目（F5）
                if cur is None:
                    # pending 迁键：沿用 pending 的 desc/t0（派发时刻比
                    # task_started 更早更准），补 agentId/found
                    base = dict(pend) if pend else {
                        "agentId": "", "found": False,
                        "type": agent_type or "Task",
                        "desc": str(desc or "")[:200],
                        "t0": ts_ms or 0, "doneAt": 0, "rounds": 1,
                        "lastActive": ts_ms or 0, "tids": [],
                        "tokens": 0, "toolN": 0, "brief": ""}
                    base["agentId"] = aid
                    base["found"] = True
                    cur = self._ag[aid] = base
                    # F2：迁键成功删 pending（副本留守=永 running 鬼影）
                    self._ag.pop("pending:" + tid, None)
                if bg:
                    cur["bg"] = True
                if tid and tid not in cur["tids"]:
                    cur["tids"].append(tid)
                # 复审F2回归修复：tidMap 赋值必须无条件——迁键沿用的 pending
                # 副本 tids 已含 tid，旧「not-in-tids 才赋值」守卫把映射整个
                # 跳过 → 终态信号（result/notification 按 tid 反查）全丢
                # → 首轮 Task 永卡 running（复审完整序列实证）
                if tid:
                    self._tid_map[tid] = aid
                if not cur["t0"]:
                    cur["t0"] = ts_ms or 0
                if not cur["desc"] and desc:
                    cur["desc"] = str(desc)[:200]
                cur["status"] = "running"
                cur["doneAt"] = 0
                cur["lastActive"] = ts_ms or 0
                return
            # 无链可归（增量乱序早到）——临时条目兜底，result/重建收编。
            # F5 补：SendMessage 包装 tid（_sm_tids 在场）不建 pending——
            # 其归链由 on_send_message/回执 resumedAgentId 负责，pending
            # 只属于「Task 直派 tool_use 帧乱序滞后」的形态
            if tid not in self._sm_tids and "pending:" + tid not in self._ag:
                self._ag["pending:" + tid] = {
                    "agentId": "", "found": False,
                    "type": agent_type or "Task",
                    "desc": str(desc or "")[:200], "status": "running",
                    "t0": ts_ms or 0, "doneAt": 0, "rounds": 1,
                    "lastActive": ts_ms or 0, "tids": [tid],
                    "tokens": 0, "toolN": 0, "brief": ""}

    def on_task_notification(self, tid, ok, brief, ts_ms, tokens, tool_n):
        """④b task_notification——完成信号（链上 tid 反查 agentId 落定）。"""
        with self._lock:
            aid = self._tid_map.get(tid) or ""
            if not aid:
                return
            cur = self._ag.get(aid)
            if cur is None:
                return
            cur["status"] = "done" if ok else "err"
            cur["doneAt"] = ts_ms or 0
            cur["lastActive"] = ts_ms or 0
            cur["brief"] = str(brief or "")[:200]
            if tokens:
                cur["tokens"] = tokens
            if tool_n:
                cur["toolN"] = tool_n

    def on_interrupt_all(self, ts_ms, only_fg=False):
        """■ 中断（only_fg=True：前台子代理同停，bg 跨回合存活不误收）/
        进程死（only_fg=False：子代理同进程必死，全部 running 落
        interrupted）。续派轮的恢复由下一次 SendMessage/重建翻正。"""
        with self._lock:
            for ent in self._ag.values():
                if ent["status"] == "running" and not (only_fg and ent.get("bg")):
                    ent["status"] = "interrupted"
                    ent["doneAt"] = ts_ms or 0
                    # lastActive 同步（merge_rebuilt 新者胜的比较键——中断时刻
                    # 恒新于转写静态事实，增量不被重建覆写）
                    ent["lastActive"] = max(ent.get("lastActive") or 0, ts_ms or 0)

    # ---- 读侧（HTTP 线程）----

    def aid_of(self, tid):
        """tid → agentId 单查（emit 附 aid 用——锁内一次 dict 读，不拷贝）。"""
        with self._lock:
            return self._tid_map.get(str(tid or "")) or ""

    def snapshot(self):
        with self._lock:
            agents = {}
            for k, v in self._ag.items():
                a = dict(v)
                a["tids"] = list(v.get("tids") or [])
                agents[k] = a        # pending: 前缀原样下发（前端按前缀识别）
            return {"agents": agents, "tidMap": dict(self._tid_map),
                    "rebuilt": self._rebuilt}

    def mark_rebuilt(self):
        with self._lock:
            self._rebuilt = True

    def merge_rebuilt(self, agents, tid_map):
        """扫转写重建后的**合并**（F7 修复：旧 replace_all 整体置换会吞掉
        增量——进程死路径 bg_in_flight_clear 刚落的 interrupted 增量被转写
        done/err 覆写、crash 时在跑（无 sub_open 行）的代理整条抹掉、tidMap
        清空断前端桥）。策略：逐条按 lastActive 新者胜（增量=进程死时刻恒
        新）；tidMap 保留既有并入重建产物。"""
        with self._lock:
            for aid, ent in (agents or {}).items():
                cur = self._ag.get(aid)
                if cur is None or (ent.get("lastActive") or 0) >= (cur.get("lastActive") or 0):
                    e = dict(ent)
                    e["tids"] = list(ent.get("tids") or [])
                    # tids 并集（增量与转写各知一半）
                    if cur is not None:
                        for t in (cur.get("tids") or []):
                            if t not in e["tids"]:
                                e["tids"].append(t)
                    self._ag[aid] = e
            for t, a in (tid_map or {}).items():
                self._tid_map.setdefault(t, a)
            self._rebuilt = True


def _ts_ms(v):
    """行 ts（ISO 字符串）→ epoch ms（F7：前端契约是 ms 数字——字符串直传
    会让 Date.now()-t=NaN、目录当天闸恒 false=重建条目不可见）。解析失败 0。"""
    import datetime
    s = str(v or "").strip()
    if not s:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s2)
        return int(dt.timestamp() * 1000)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return 0


def rebuild_from_transcript(sub_open_rows, sendmsg_rows):
    """重启/首查的静态重建（纯函数，便于测试）：由 /transcript 已注入的
    sub_open 行（agentId/type/desc/err/ts）+ SendMessage 行（resumedAgentId）
    重建注册表。轮数=同 agentId 的段数；t0/doneAt 用行 ts（ISO→ms）；
    跨会话纯续派（无首轮行）也成条目（SendMessage 行派生）。"""
    reg = AgentRegistry()
    agents = {}
    tid_map = {}
    for r in sub_open_rows or []:
        aid = str(r.get("agent") or "")
        if not _looks_id(aid):
            continue
        t = _ts_ms(r.get("ts"))
        ent = agents.get(aid)
        if ent is None:
            ent = agents[aid] = {
                "agentId": aid, "found": True,
                "type": r.get("type") or "Task",
                "desc": str(r.get("desc") or "")[:200],
                "status": "err" if r.get("err") else "done",
                "t0": t, "doneAt": t,
                "rounds": 0, "lastActive": t, "tids": [],
                "tokens": 0, "toolN": 0, "brief": ""}
        ent["rounds"] += 1
        if t:
            ent["doneAt"] = t
            ent["lastActive"] = t
            if not ent["t0"]:
                ent["t0"] = t
        ent["status"] = "err" if r.get("err") else "done"   # 最后一段的状态
        # 转写侧 tid 不可知（sub_open 行不带 tool_use_id）——tid_map 由
        # 增量钩子补；重启即进程死，live 帧不再来，无碍
    for r in sendmsg_rows or []:
        m = _RE_RES_AGENT.search(str(r.get("result") or ""))
        aid = m.group(1) if m else ""
        if not _looks_id(aid):
            continue
        t = _ts_ms(r.get("ts"))
        msg1 = str((r.get("input") or {}).get("message") or "").strip()
        desc = (msg1.split("\n")[0][:60] or "") if msg1 else ""
        ent = agents.get(aid)
        if ent is None:
            ent = agents[aid] = {
                "agentId": aid, "found": True, "type": "SendMessage",
                "desc": desc[:120], "status": "done",
                "t0": t, "doneAt": t,
                "rounds": 0, "lastActive": t, "tids": [],
                "tokens": 0, "toolN": 0, "brief": ""}
        ent["rounds"] += 1
        if t:
            ent["lastActive"] = t
        if desc:
            ent["desc"] = desc[:200]   # 最新轮任务名
    reg.merge_rebuilt(agents, tid_map)
    return reg
