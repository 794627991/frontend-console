# -*- coding: utf-8 -*-
"""子代理冷查询投影（ZCode subagent-session-query.ts 的 Python 版，纯函数零 IO）。

设计定调（用户拍板「全盘抄 ZCode，不要自己造轮子」）：/agents 不再维护增量
状态，每次查询从磁盘持久事实（主会话 jsonl 行 + 子代理转写尾探 + meta.json
父子链接）现算投影。F5/切会话/后端重启的正确性由「唯一真源=磁盘」构造性
保证，而非补丁——历次实锤（bg 假 done/乱序幻影/迁键丢映射/merge 覆写）
所针对的整类问题在无状态投影里不存在。

三层分工（对位 ZCode）：
  collect_main_facts      主 jsonl 行 → 有序事实表（本模块，纯）
  child_outcome_from_tail 子代理转写尾行 → 终局状态（本模块，纯；
                         IO/水位由 subagent_readmodel 负责）
  project                 事实+尾探+活性 → agents/tidMap（本模块，纯，
                         状态判定链=优先级契约，对位 runningStatus/endedStatus）

磁盘事实形态（2026-10-19 实测，CLI 2.1.293）：
  · assistant 行 content[].tool_use：name∈{Agent,Task}（派发）/
    SendMessage（续派）；input 带 description/subagent_type/
    run_in_background/to/message
  · user 行 content[].tool_result：前台=结果文本；后台 ACK=纯文本
    "agentId: xxx (internal ID…)"；SendMessage 回执=JSON resumedAgentId
  · task-notification：type=user 行、message.content 为 XML 字符串、
    origin.kind=="task-notification"——<task-id>(=agentId)/<tool-use-id>/
    <status>completed|stopped|failed|cancelled|…</status>/<summary>
  · 子代理独立转写 projects/<主sid>/subagents/agent-<agentId>.jsonl
    （行同构，顶层 agentId+isSidechain:true）+ agent-<agentId>.meta.json
    （toolUseId 父子链接/requestShape=foreground|background）
"""
import json
import re

# ---- 常量（与 ZCode 同源的契约口径）----

_SUBAGENT_TOOLS = ("Agent", "Task")
# cancel 语义正则（ZCode CANCELLATION_PATTERN 对位）
_RE_CANCEL = re.compile(r"abort|cancel|interrupt|stop(?!e)", re.I)
# 后台 ACK 纯文本 agentId（宽松版——仅对 bg=True 回执使用，见
# _agent_id_from_receipt 的形态锚说明；全审S2）
_RE_ACK_LOOSE = re.compile(r"agentId:\s*([0-9a-zA-Z_-]{8,64})")
# SendMessage 回执 JSON
_RE_RESUMED = re.compile(r"resumedAgentId[\"'\s:]+([0-9a-zA-Z_-]{8,64})")
_RE_AGENT_JSON = re.compile(r"[\"']agentId[\"'\s:]+([0-9a-zA-Z_-]{8,64})")
_RE_ANY_ID = re.compile(r"^[0-9a-zA-Z_-]{8,64}$")
# task-notification XML 字段
_RE_XML = {
    "task_id": re.compile(r"<task-id>([^<]+)</task-id>"),
    "tid": re.compile(r"<tool-use-id>([^<]+)</tool-use-id>"),
    "status": re.compile(r"<status>([^<]+)</status>"),
    "summary": re.compile(r"<summary>([^<]*)</summary>", re.S),
}
# 尾探：STREAM_RECOVERY 类半截行不算终态（ZCode 防御对位）
_RE_STREAM_RECOVERY = re.compile(r"stream.?recovery", re.I)

FRESH_WINDOW_MS = 120 * 1000   # 子代理转写 mtime 新鲜窗（_bg_alive_probe 同阈）


def _ts_ms(v):
    """ISO 时间戳 → epoch ms（与 registry 版同款，前端契约是 ms 数字）。"""
    import datetime
    s = str(v or "").strip()
    if not s:
        return 0
    try:
        s2 = s.replace("Z", "+00:00")
        return int(datetime.datetime.fromisoformat(s2).timestamp() * 1000)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return 0


def _looks_id(s):
    return bool(s) and bool(_RE_ANY_ID.match(str(s)))


def _content_text(c):
    """tool_result content（list[Block]|str）→ 文本。"""
    if isinstance(c, list):
        return "\n".join(str(b.get("text") or "")
                         for b in c if isinstance(b, dict))
    return str(c or "")


# ---- ① 主 jsonl 行 → 有序事实表 ----

def collect_main_facts(lines):
    """行迭代器 → 事实列表（dict，按出现序）。

    五类事实：dispatch / result / notify / send / send_result。
    行门控由 caller 做（子串快筛）；本函数容忍脏行（跳过不炸）。
    跳过：parent_tool_use_id（子代理链内部行）/ isSidechain / isMeta。
    """
    facts = []
    fi = 0
    for line in lines:
        try:
            o = json.loads(line)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        if o.get("parent_tool_use_id") or o.get("isSidechain") or o.get("isMeta"):
            continue
        ts = _ts_ms(o.get("timestamp"))
        typ = o.get("type")
        # task-notification：user 行 + origin.kind（XML content）
        org = o.get("origin") or {}
        if typ == "user" and isinstance(org, dict) and org.get("kind") == "task-notification":
            msg = o.get("message") or {}
            c = msg.get("content") if isinstance(msg, dict) else None
            xml = _content_text(c) if not isinstance(c, str) else c
            if "<task-notification>" not in str(xml):
                continue
            facts.append({
                "kind": "notify",
                "tid": (_RE_XML["tid"].search(xml) or [None, ""])[1].strip()
                if _RE_XML["tid"].search(xml) else "",
                "task_id": (_RE_XML["task_id"].search(xml).group(1).strip()
                            if _RE_XML["task_id"].search(xml) else ""),
                "status": (_RE_XML["status"].search(xml).group(1).strip()
                           if _RE_XML["status"].search(xml) else ""),
                "summary": (_RE_XML["summary"].search(xml).group(1).strip()[:200]
                            if _RE_XML["summary"].search(xml) else ""),
                "ts": ts})
            continue
        if typ not in ("assistant", "user"):
            continue
        msg = o.get("message") or {}
        blocks = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if typ == "assistant" and b.get("type") == "tool_use":
                n = str(b.get("name") or "")
                inp = b.get("input") or {}
                tid = str(b.get("id") or "")
                if n in _SUBAGENT_TOOLS:
                    facts.append({
                        "kind": "dispatch", "tid": tid,
                        "type": str(inp.get("subagent_type")
                                    or inp.get("agent_type") or "Task"),
                        "desc": str(inp.get("description") or "")[:200],
                        "prompt1": str(inp.get("prompt") or "").strip()
                        .split("\n")[0][:60],
                        "bg": bool(inp.get("run_in_background")),
                        "ts": ts})
                elif n == "SendMessage":
                    m1 = str(inp.get("message") or "").strip().split("\n")[0]
                    facts.append({
                        "kind": "send", "tid": tid,
                        "to": str(inp.get("to") or "").strip(),
                        "msg1": m1[:60], "ts": ts})
            elif typ == "user" and b.get("type") == "tool_result":
                txt = _content_text(b.get("content"))
                tid = str(b.get("tool_use_id") or "")
                err = bool(b.get("is_error"))
                facts.append({"kind": "result", "tid": tid,
                              "text": txt, "is_error": err, "ts": ts})
    # 全审S2：send_result 后置分类——回执文本必须 (a)tid 有对应 send 事实
    # (b)resumedAgentId 命中。旧前向判定让「前台回执正文里引用
    # resumedAgentId: xxx」被误判成 SendMessage 回执：前台终态被吞+
    # 幻影条目 running+bg 永跑
    send_tids = {f["tid"] for f in facts if f["kind"] == "send"}
    for f in facts:
        if f["kind"] != "result" or f["tid"] not in send_tids:
            continue
        m = _RE_RESUMED.search(f.get("text") or "")
        if m:
            f["kind"] = "send_result"
            f["resumed"] = m.group(1)
            f["ok"] = not f["is_error"]
            f["text"] = (f.get("text") or "")[:200]
    for i, f in enumerate(facts):
        f["i"] = i   # 全局事实序（行序）——新轮越界判定的基准
    return facts


# ---- ② 子代理转写尾探 → 终局状态（ZCode lastChildOutcome 对位） ----

def child_outcome_from_tail(tail_lines):
    """子代理转写尾行（最后 N 行，caller 截取）→ 终局 dict。

    规则（对位 ZCode）：顶层 result 行优先；最后 assistant 含 tool_use
    =mid_flight（在干活）；仅 text/thinking=终局 success+summary；
    STREAM_RECOVERY 半截行不算终态。返回 {terminal, status, summary,
    endedAt, lastActive}（terminal=False 表示仍在飞/无定论）。
    """
    out = {"terminal": False, "status": "", "summary": "",
           "endedAt": 0, "lastActive": 0, "tokens": 0, "toolN": 0}
    for line in reversed(tail_lines or []):
        # 逆序找最顶层结论：先遇 result 行直接定；否则**最后一条 assistant**
        # （全审S1：ZCode at(-1) 语义——逆序遇第一条 assistant 即定案，不得
        # 越过终局 text 向更早的 tool assistant 探——否则主流尾部形态
        # [tool_asst, user, text_asst] 被误判 mid_flight）
        try:
            o = json.loads(line)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        ts = _ts_ms(o.get("timestamp")) or out["lastActive"]
        if ts:
            out["lastActive"] = max(out["lastActive"], ts)
        typ = o.get("type")
        if typ == "result" and not out["terminal"]:
            sub = str(o.get("subtype") or "")
            err = bool(o.get("is_error"))
            txt = str(o.get("result") or "")[:200]
            if _RE_STREAM_RECOVERY.search(sub) or _RE_STREAM_RECOVERY.search(txt):
                continue   # 恢复中半截行，不算终态
            out["terminal"] = True
            out["status"] = "err" if (err or sub in ("error_max_turns",
                                                     "error_during_execution")) else "done"
            out["summary"] = txt
            out["endedAt"] = ts
            # 全审G3：顶层 result 行带 usage（与主会话 result 同构）——
            # 用量只在此提取（ZCode：在飞的那条还没有账）
            u = o.get("usage") or {}
            try:
                out["tokens"] = int(u.get("total_tokens") or 0) or out["tokens"]
                out["toolN"] = int(u.get("tool_uses") or u.get("num_turns")
                                   or 0) or out["toolN"]
            except Exception:
                pass
            continue
        if typ == "assistant" and not out["terminal"]:
            msg = o.get("message") or {}
            blocks = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(blocks, list):
                continue
            has_tool = any(isinstance(x, dict) and x.get("type") == "tool_use"
                           for x in blocks)
            if has_tool:
                # 最后 assistant 在调工具=在干活（ZCode hasToolRound 防御）
                return out
            # 最后 assistant 纯文本=终局 success——立即定案（不再向更早探）
            txt = "\n".join(str(x.get("text") or "")
                            for x in blocks if isinstance(x, dict))
            out["terminal"] = True
            out["status"] = "done"
            out["summary"] = txt[:200]
            out["endedAt"] = ts
            return out
        # 其他行（user/attachment…）继续逆序
    return out


# ---- ③ 投影（状态判定链=优先级契约） ----

def _agent_id_from_receipt(txt, bg=False):
    """回执文本提 agentId（全审S2 双锚）：
    · bg=True（后台派发的回执=ACK 形态）：任意位置 agentId: 提取——生产
      ACK 实测带 "Task " 前缀（"Task agentId: xxx (internal ID)"），纯
      行首锚会漏；后台回执文本出自 CLI 本体，形态可信
    · bg=False（前台回执）：JSON 形态（strip 后 { 开头且整串 parse 成
      dict）走键提取——前台回执正文里引用 "agentId: xxx" 的散文/协议
      说明不采（S2 探针：前台终态被吞+幻影 running 即此形态）"""
    s = str(txt or "")
    if bg:
        m = _RE_ACK_LOOSE.search(s)
        return m.group(1) if m and _looks_id(m.group(1)) else ""
    st = s.strip()
    if st.startswith("{"):
        # 真实前台回执=首个 JSON 对象后跟结论文本——取 {...} 段 parse，
        # 整串 parse 必失败（实测 '{"agentId":...} 结论 PASS'）
        end = st.find("}")
        segs = [st[:end + 1]] if end > 0 else []
        segs.append(st)
        for seg in segs:
            try:
                j = json.loads(seg)
            except Exception:
                continue
            if isinstance(j, dict):
                v = str(j.get("agentId") or "")
                if _looks_id(v):
                    return v
    return ""


def _status_from_notify(st):
    """notification <status> → done/err/interrupted（未知值保守归 done）。"""
    s = str(st or "").strip().lower()
    if s in ("completed", "success", ""):
        return "done"
    if s in ("failed", "error"):
        return "err"
    if s in ("cancelled", "canceled", "stopped", "interrupted"):
        return "interrupted"
    return "done"


def project(facts, child_states=None, liveness=None, external_links=None,
            external_ids=None):
    """事实表 → {agents:{key→条目}, tidMap, rev}。

    条目字段与旧注册表完全同形（前端零改动契约）：agentId/found/type/
    desc/status/t0/doneAt/rounds/lastActive/tids/bg/tokens/toolN/brief
    （interrupted 且证据不足时另附 lost:true，对位 ZCode lost 终态）。

    参数：
      facts            collect_main_facts 产物（主 jsonl 全量事实，有序）
      child_states     {agentId→child_outcome_from_tail 产物}
      liveness         {proc_alive, busy, now_ms, child_fresh:{agentId→bool}}
      external_links   {tid→agentId}（meta.json toolUseId 父子链接，readmodel 供）
      external_ids     {角色名→agentId}（meta/audit ids，角色名 SendMessage 归链）
    """
    child_states = child_states or {}
    liveness = liveness or {}
    external_links = external_links or {}
    external_ids = external_ids or {}
    proc_alive = bool(liveness.get("proc_alive"))
    busy = bool(liveness.get("busy"))
    now_ms = int(liveness.get("now_ms") or 0)
    fresh = liveness.get("child_fresh") or {}

    # 索引：tid → 事实
    dispatch_by_tid = {}
    result_by_tid = {}
    send_by_tid = {}
    sendres_by_tid = {}
    notifies = []
    for f in facts:
        k = f["kind"]
        if k == "dispatch":
            dispatch_by_tid.setdefault(f["tid"], f)
        elif k == "result":
            result_by_tid.setdefault(f["tid"], f)
        elif k == "send":
            send_by_tid.setdefault(f["tid"], f)
        elif k == "send_result":
            sendres_by_tid.setdefault(f["tid"], f)
        elif k == "notify":
            notifies.append(f)

    # agentId 解析（三源：ACK/JSON 回执（S2 形态锚）→ external_links(meta)）
    def aid_of_dispatch(tid):
        r = result_by_tid.get(tid)
        d = dispatch_by_tid.get(tid)
        if r:
            a = _agent_id_from_receipt(r.get("text") or "",
                                       bg=bool(d and d.get("bg")))
            if a:
                return a
        return external_links.get(tid) or ""

    # 候选构建：dispatch（首轮）+ send_result.resumed（跨会话纯续派）
    ents = {}   # agentId 或 "pending:tid" → 条目
    tid_map = {}

    def _new_ent(aid, etype, desc, t0, bg):
        return {"agentId": aid, "found": bool(aid), "type": etype,
                "desc": str(desc or "")[:200], "status": "running",
                "t0": t0, "doneAt": 0, "rounds": 1,
                "lastActive": t0, "tids": [],
                "tokens": 0, "toolN": 0, "brief": "",
                **({"bg": True} if bg else {})}

    d_order = []
    for tid, d in dispatch_by_tid.items():
        aid = aid_of_dispatch(tid)
        key = aid if aid else "pending:" + tid
        if key in ents:
            ent = ents[key]
            ent["rounds"] += 0   # 同键重放不叠轮（dispatch_by_tid 已去重）
        else:
            ent = _new_ent(aid, d.get("type") or "Task",
                           d.get("desc") or d.get("prompt1"), d.get("ts"),
                           d.get("bg"))
            ents[key] = ent
            d_order.append(key)
        if tid not in ent["tids"]:
            ent["tids"].append(tid)
        ent["lastActive"] = max(ent["lastActive"], d.get("ts") or 0)
        if tid and aid:
            tid_map[tid] = aid

    # 跨会话纯续派（无首轮 dispatch）——该轮已在此计数，send 归链不再叠
    cross_tids = set()
    for tid, sr in sendres_by_tid.items():
        aid = sr.get("resumed") or ""
        if not _looks_id(aid) or aid in ents:
            if aid and aid in ents:
                tid_map[tid] = aid
            continue
        sm = send_by_tid.get(tid) or {}
        ents[aid] = _new_ent(aid, "SendMessage",
                             sm.get("msg1") or "", sr.get("ts"), True)
        tid_map[tid] = aid
        cross_tids.add(tid)

    # SendMessage 归链（每条 send 事实=新轮）
    for tid, sm in send_by_tid.items():
        if tid in cross_tids:
            continue   # 轮已由 send_result 侧计数（跨会话新条目）
        to = sm.get("to") or ""
        aid = ""
        if to in external_ids:
            aid = str(external_ids.get(to) or "")
        if not aid and _looks_id(to) and to in ents:
            aid = to
        if not aid:
            sr = sendres_by_tid.get(tid)
            if sr and _looks_id(sr.get("resumed") or ""):
                aid = sr["resumed"]
        if not aid:
            continue   # 归链失败：等回执 flush（<2s 窗口，readmodel 下轮收敛）
        ent = ents.get(aid)
        if ent is None:
            continue   # 目标不在场（跨会话且无回执）——不铸条目
        ent["rounds"] += 1
        ent["status"] = "running"
        ent["doneAt"] = 0
        ent["lastActive"] = max(ent["lastActive"], sm.get("ts") or 0)
        if tid not in ent["tids"]:
            ent["tids"].append(tid)
        tid_map[tid] = aid
        if sm.get("msg1"):
            ent["desc"] = sm["msg1"][:200]   # 任务名取最新续派轮消息首行

    # 每条目「最后一轮」的事实序：终态证据（notify/result）只认新轮之后的
    # ——旧轮的 result/notification 不得覆写续派新翻的 running（send 归链
    # 在先翻正，此处防被旧证据盖回）。对位 ZCode「终态不可逆，除非出现
    # 更晚的 send 开新轮」的时序面。
    last_round_i = {}
    for key, ent in ents.items():
        li = -1
        for tid in ent["tids"]:
            d = dispatch_by_tid.get(tid)
            if d is not None:
                li = max(li, d.get("i", 0))
            sm = send_by_tid.get(tid)
            if sm is not None:
                li = max(li, sm.get("i", 0))
        last_round_i[key] = li

    # notification 终态（bg 权威；tid 或 task_id 双反查）
    for n in notifies:
        tid_n = n.get("tid") or ""
        aid = tid_map.get(tid_n) or ""
        if not aid and _looks_id(n.get("task_id") or ""):
            aid = n["task_id"]
        ent = ents.get(aid) if aid else None
        if ent is None:
            # 全审G4：ACK 未落盘窗口（dispatch 已 flush、回执没有）——条目
            # 尚在 pending:tid 键。notify 自带 task_id，直接迁键落终态（对位
            # 旧 registry 迁键语义；ACK 一旦落盘后续投影自然同键收敛）
            pend = ents.get("pending:" + tid_n)
            if pend is not None and _looks_id(aid):
                pend["agentId"] = aid
                pend["found"] = True
                ents[aid] = pend
                ents.pop("pending:" + tid_n, None)
                tid_map[tid_n] = aid
                ent = pend
            else:
                continue
        else:
            if n.get("i", 0) < last_round_i.get(aid, -1):
                continue   # 旧轮通知：新轮已开（更晚的 send），不再定终态
        st = _status_from_notify(n.get("status"))
        ent["status"] = st
        ent["doneAt"] = n.get("ts") or 0
        ent["lastActive"] = max(ent["lastActive"], ent["doneAt"])
        if n.get("summary"):
            ent["brief"] = n["summary"]

    # 前台 result 终态 + 子代理尾探终局（逐条目）
    for key, ent in list(ents.items()):
        li = last_round_i.get(key, -1)
        fg_final = None
        for tid in ent["tids"]:
            r = result_by_tid.get(tid)
            if r is None:
                continue
            if r.get("i", 0) < li:
                continue   # 旧轮回执：新轮已开，不定新轮终态
            # bg ACK（dispatch.bg 且文本 agentId: 形态）不是终态——启程确认
            d = dispatch_by_tid.get(tid)
            txt = r.get("text") or ""
            if d and d.get("bg") and _RE_ACK_LOOSE.search(txt) and not r.get("is_error"):
                continue
            if r.get("is_error"):
                fg_final = ("interrupted" if _RE_CANCEL.search(txt) else "err",
                            r.get("ts") or 0, txt[:200])
            else:
                fg_final = ("done", r.get("ts") or 0, txt[:200])
        aid = ent.get("agentId")
        co = child_states.get(aid) if aid else None
        # ---- 状态判定链（优先级契约，ZCode runningStatus/endedStatus 对位）----
        # RUNNING 1：转写新鲜（mtime<120s，CLI 还在写=铁证在跑）——进程死
        # 也不否决（孤儿 CLI 诚实显示在跑）
        if ent["status"] == "running" and aid and fresh.get(aid):
            continue
        # RUNNING 1b：尾探 mid_flight——**仅在进程活时可信**（进程死后转写
        # 永停 mid_flight，历史死代理不得永久 running；影子对账实锤）
        if ent["status"] == "running" and co and not co.get("terminal") \
                and proc_alive:
            ent["lastActive"] = max(ent["lastActive"],
                                    co.get("lastActive") or 0)
            continue
        # RUNNING 2：bg 且无任何终态证据且进程活（宁跑勿完——ACK/未 flush 窗口）
        if ent["status"] == "running" and ent.get("bg") and proc_alive:
            continue
        # RUNNING 3：前台无 result 事实且会话 busy（父 tool part pending/running）
        if ent["status"] == "running" and not ent.get("bg") and fg_final is None \
                and busy and proc_alive:
            continue
        # ENDED 1/2：notification / 前台 result（上面已写 status，此处补 brief）
        if fg_final is not None and ent["status"] in ("running",):
            ent["status"], ent["doneAt"], ent["brief"] = fg_final
            ent["lastActive"] = max(ent["lastActive"], ent["doneAt"])
            continue
        # ENDED 3：子代理尾探终局（最低优先级终态——前台 result/notify 在上）
        if ent["status"] == "running" and co and co.get("terminal"):
            ent["status"] = co.get("status") or "done"
            ent["doneAt"] = co.get("endedAt") or 0
            if co.get("summary"):
                ent["brief"] = co["summary"]
            if co.get("tokens"):
                ent["tokens"] = co["tokens"]   # 全审G3：顶层 result usage
            if co.get("toolN"):
                ent["toolN"] = co["toolN"]
            ent["lastActive"] = max(ent["lastActive"], co.get("lastActive") or 0)
            continue
        # ENDED 4：证据不足——进程死/不新鲜 → interrupted+lost（不装 done）
        if ent["status"] == "running":
            if not proc_alive:
                ent["status"] = "interrupted"
                ent["lost"] = True
                ent["doneAt"] = ent["lastActive"]
            # proc_alive 但既无终态证据也不 fresh 且非 bg 非 busy：
            # 前台无 result 且回合已越界（!busy）——健康 CLI 必写 result，
            # 缺失=中断
            elif not busy and not ent.get("bg"):
                ent["status"] = "interrupted"
                ent["lost"] = True
                ent["doneAt"] = ent["lastActive"]
            # else：保持 running（liveness 不明时不猜）
    return {"agents": ents, "tidMap": tid_map, "rev": len(facts)}
