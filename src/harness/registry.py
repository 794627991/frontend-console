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
        """② Task tool_result——提取 agentId 迁移键；完成态落定。"""
        m = _RE_AGENT_JSON.search(str(result_text or "")) \
            or _RE_RES_AGENT.search(str(result_text or ""))
        aid = m.group(1) if m else ""
        with self._lock:
            ent = self._pop_pending(tid)
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
                        "lastActive": ts_ms or 0, "tids": [tid],
                        "tokens": 0, "toolN": 0, "brief": ""}
                if tid not in cur["tids"]:
                    cur["tids"].append(tid)
                self._tid_map[tid] = aid
                cur["status"] = "err" if err else "done"
                cur["doneAt"] = ts_ms or 0
                cur["lastActive"] = ts_ms or 0
                if tokens:
                    cur["tokens"] = tokens
                if tool_n:
                    cur["toolN"] = tool_n
            elif ent is not None:
                # 无 id 可提（CLI 异常形态）——临时条目直接落终态（前端不回放）
                ent["status"] = "err" if err else "done"
                ent["doneAt"] = ts_ms or 0
                self._ag["pending:" + tid] = ent

    def on_send_message(self, tid, to, message_first_line, ids_map, ts_ms):
        """③ SendMessage tool_use——to 归链建轮。归链判定顺序（冒烟实测
        bug 修正：'reviewer' 恰 8 字符合法 id 形态，先判形态会把角色名当
        agentId 建独立条目=归链失败）：
          ① ids_map（Task 回执回填的 角色→agentId 映射）优先
          ② to 本身是注册表现有键（首轮已回填 agentId 的直连续派）
          ③ 都不中=跨会话协作/无效寻址——不建条目（注册表只管本会话派出
            的子代理；to 形如 id 但从未在本会话出现过的场景必然如此——
            本会话续派的前提是首轮完成、agentId 已回填在场）
        """
        to = str(to or "").strip()
        with self._lock:
            aid = str((ids_map or {}).get(to) or "")
            if not aid:
                aid = to if (to and to in self._ag) else ""
            if not aid:
                return
            cur = self._ag.get(aid)
            if cur is None:
                # 竞态兜底：ids_map 命中但条目被重建置换等罕见路径
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
        """④a task_started 系统事件——真子代理（subagent_type 非空）补记：
        tid 归链（task_id 若是真实 agentId 直接迁）；t0/rounds 修正。"""
        if not str(agent_type or "").strip():
            return          # 后台 shell 不入注册表（v3.4.43 定调）
        with self._lock:
            aid = self._tid_map.get(tid) or ""
            if not aid and _looks_id(task_id):
                # 新版 CLI task_id=真实 agentId；SendMessage 包装 task_id 是
                # 异形 id——靠 to 归链在先（③），这里只在链首直派时迁键
                aid = str(task_id)
                self._tid_map[tid] = aid
            if aid:
                cur = self._ag.get(aid)
                if cur is None:
                    cur = self._ag[aid] = {
                        "agentId": aid, "found": True,
                        "type": agent_type or "Task",
                        "desc": str(desc or "")[:200], "status": "running",
                        "t0": ts_ms or 0, "doneAt": 0, "rounds": 1,
                        "lastActive": ts_ms or 0, "tids": [],
                        "bg": bool(bg), "tokens": 0, "toolN": 0, "brief": ""}
                if bg:
                    cur["bg"] = True
                if tid and tid not in cur["tids"]:
                    cur["tids"].append(tid)
                    self._tid_map[tid] = aid
                if not cur["t0"]:
                    cur["t0"] = ts_ms or 0
                if not cur["desc"] and desc:
                    cur["desc"] = str(desc)[:200]
                cur["status"] = "running"
                cur["doneAt"] = 0
                cur["lastActive"] = ts_ms or 0
                return
            # 无链可归（增量乱序早到）——临时条目兜底，result/重建收编
            if "pending:" + tid not in self._ag:
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
                agents[k if k.startswith("pending:") else k] = a
            return {"agents": agents, "tidMap": dict(self._tid_map),
                    "rebuilt": self._rebuilt}

    def mark_rebuilt(self):
        with self._lock:
            self._rebuilt = True

    def replace_all(self, agents, tid_map):
        """扫转写重建后的整体置换（重启恢复路）。"""
        with self._lock:
            self._ag = agents or {}
            self._tid_map = tid_map or {}
            self._rebuilt = True

    # ---- 内部 ----

    def _pop_pending(self, tid):
        """取走临时条目（迁移用）；不删 pending 键（found=False 历史保留）。"""
        ent = self._ag.get("pending:" + tid)
        if ent is not None:
            self._ag["pending:" + tid] = dict(ent)   # 原位留终态副本
            return dict(ent)
        # 已被 task_started 建立的链首（aid 直派形态）——按 tid_map 反查
        aid = self._tid_map.get(tid) or ""
        if aid:
            cur = self._ag.get(aid)
            if cur is not None and tid in (cur.get("tids") or []):
                return dict(cur)
        return None


def rebuild_from_transcript(sub_open_rows, sendmsg_rows):
    """重启/首查的静态重建（纯函数，便于测试）：由 /transcript 已注入的
    sub_open 行（agentId/type/desc/err/done）+ SendMessage 行（resumedAgentId）
    重建注册表。轮数=同 agentId 的段数；t0/doneAt 用行 ts；跨会话纯续派
    （无首轮行）也成条目（SendMessage 行派生）。"""
    reg = AgentRegistry()
    agents = {}
    tid_map = {}
    for r in sub_open_rows or []:
        aid = str(r.get("agent") or "")
        if not _looks_id(aid):
            continue
        ent = agents.get(aid)
        if ent is None:
            ent = agents[aid] = {
                "agentId": aid, "found": True,
                "type": r.get("type") or "Task",
                "desc": str(r.get("desc") or "")[:200],
                "status": "err" if r.get("err") else "done",
                "t0": r.get("ts") or 0, "doneAt": r.get("ts") or 0,
                "rounds": 0, "lastActive": r.get("ts") or 0, "tids": [],
                "tokens": 0, "toolN": 0, "brief": ""}
        ent["rounds"] += 1
        ent["doneAt"] = r.get("ts") or ent["doneAt"]
        ent["lastActive"] = r.get("ts") or ent["lastActive"]
        ent["status"] = "err" if r.get("err") else "done"   # 最后一段的状态
        # 转写侧 tid 不可知（sub_open 行不带 tool_use_id）——tid_map 由
        # 增量钩子补；重启即进程死，live 帧不再来，无碍
    for r in sendmsg_rows or []:
        m = _RE_RES_AGENT.search(str(r.get("result") or ""))
        aid = m.group(1) if m else ""
        if not _looks_id(aid):
            continue
        msg1 = str((r.get("input") or {}).get("message") or "").strip()
        desc = (msg1.split("\n")[0][:60] or "") if msg1 else ""
        ent = agents.get(aid)
        if ent is None:
            ent = agents[aid] = {
                "agentId": aid, "found": True, "type": "SendMessage",
                "desc": desc[:120], "status": "done",
                "t0": r.get("ts") or 0, "doneAt": r.get("ts") or 0,
                "rounds": 0, "lastActive": r.get("ts") or 0, "tids": [],
                "tokens": 0, "toolN": 0, "brief": ""}
        ent["rounds"] += 1
        ent["lastActive"] = r.get("ts") or ent["lastActive"]
        if desc:
            ent["desc"] = desc[:200]   # 最新轮任务名
    reg.replace_all(agents, tid_map)
    return reg
