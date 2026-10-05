# -*- coding: utf-8 -*-
"""harness.transcript —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import re
import logging
log = logging.getLogger(__name__)
from .audit import _AUDIT_MSG_PREFIX, _audit_log_read
from .vision import _VISION_TOOLS, _iso_dur_sec


# ---- from claude_harness.py:2128 (re_title) ----


def re_title(text):
    import re as _re
    t = _re.sub(r"\s+", " ", (text or "").strip())
    return (t[:24] + "…") if len(t) > 24 else t

# ---- from claude_harness.py:2227 (_SKIP_RE) ----


# ---------------------------------------------------------------------------
# 历史转写重建（切回会话时把历史灌进气泡）
# ---------------------------------------------------------------------------
_SKIP_RE = None
# v3.2.12（用户定调「这些不要出现在聊天框」）：中断/续跑机器标记行——纯 CLI
# 协议噪音，非用户输入，历史重建整行丢弃（成对出现：user 标记 + assistant
# "No response requested."）
_NOISE_RE = re.compile(
    r"^(\[Request interrupted by user( for tool use)?\]"
    r"|Continue from where you left off\.)", re.I)
# 自动续命摘要（英文 CLI 形态）——折叠成 renew 分割线（同 /compact 口径）
_CONT_RE = re.compile(r"^This session is being continued from a previous conversation", re.I)
# 用户贴图的路径占位回显——提取成 files 图片（前端出缩略图），文本不再裸显
_IMG_ECHO_RE = re.compile(r"\[Image: source: ([^\]]+?)\]")

# ---- from claude_harness.py:2233 (transcript_for) ----


def _sysnote_of(t, ts):
    """v3.3.2（回合连续性）：机器注入（task-notification/system-reminder）→
    sysnote 弱化行（前端渲染单行 dim，不渲染用户气泡、不分割回合）。
    完整开闭标签对才判（宽容半个标签=保留 user 行现状，v2.37R2 同哲学）；
    附件在场不判（真人粘贴带图不误伤——调用方守卫）。返回 None=非机器注入。"""
    s = (t or "").strip()
    if s.startswith("<task-notification") and s.endswith("</task-notification>"):
        return {"role": "sysnote", "kind": "task-notification", "text": s[:8000],
                "ts": ts or ""}
    if s.startswith("<system-reminder") and s.endswith("</system-reminder>"):
        return {"role": "sysnote", "kind": "system-reminder", "text": s[:8000],
                "ts": ts or ""}
    return None


def transcript_for(s):
    """sid → 气泡行数组。claude 侧 session_id 的 jsonl 全量解析：
    user(typed 文本/图片/文件附件) / assistant(文本/工具调用) / tool_result 摘要。
    返回 None 表示转写不存在（新会话还没聊，气泡本来就空）。
    v2.27.18 血统链：会话被续命换过 session_id 时按 lineage 串接历代 jsonl——
    回放永远完整（用户铁律：重开可以，历史回放不能丢）。"""
    global _SKIP_RE
    import re as _re   # v2.27.17：无条件导入——原来只在 _SKIP_RE is None 时
    # 顺带 import，进程预热后再遇跨会话消息行就 UnboundLocalError（实测
    # /api/harness/transcript 500 → 前端对话流空白，历史看着"全没了"）
    if _SKIP_RE is None:
        _SKIP_RE = _re.compile(r"^(<local-command-caveat|<local-command-stdout|<command-name|<command-message|<command-args|<bash-|Another Claude session sent a message|<cross-session-message)")
    # v2.27.18 血统链：历代 session_id 的 jsonl 依序解析（旧→新，当前在尾）。
    # call_by_id 跨代共用：新代开头的 tool_result 仍能挂回旧代行。某代文件
    # 没了（被清理）静默跳过，不丢后代。去重保序防重复解析同一文件。
    ids = [x for x in (list(getattr(s, "lineage", None) or []) + [s.session_id]) if x]
    seen = set()
    ordered = [x for x in ids if not (x in seen or seen.add(x))]
    import glob as _glob
    proj = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    _last_u = None   # v3.2.13：最近发出的 user 行 (files, imgs)——孪生回显判据用

    def _parse_one(path, lines, call_by_id):
        """解析一个 session 的 jsonl，行追加进 lines。返回是否读到文件。"""
        nonlocal _last_u
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    if '"type":"user"' not in raw and '"type":"assistant"' not in raw:
                        continue
                    try:
                        o = json.loads(raw)
                    except Exception:
                        continue
                    typ = o.get("type")
                    if o.get("isSynthetic") or o.get("parent_tool_use_id"):
                        continue
                    # v2.3.12：/compact 压缩摘要行（isCompactSummary=true）不进
                    # 用户气泡——用户手动压缩后界面弹出几十行英文摘要（用户实锤
                    # 「不应该在我的消息气泡里」）。折叠成 renew 分割线：摘要已
                    # 并入模型上下文（续命记忆），UI 只留一行标记不渲染原文。
                    if o.get("isCompactSummary"):
                        lines.append({"role": "renew",
                                      "text": "上下文已压缩（/compact 摘要已并入模型记忆）",
                                      "ts": o.get("timestamp") or ""})
                        continue
                    msg = o.get("message") or {}
                    content = msg.get("content")
                    if typ == "user":
                        if isinstance(content, str):
                            t = content
                            # v2.27.3：跨会话消息（识图回传等）不再被 _SKIP_RE 静默吞掉——
                            # 解析出发件人与正文，产 peer 行让前端渲染专属回传气泡
                            # （用户定调：识图全程要有可见反馈，回传内容不能凭空消失）
                            # v2.3.2 审计 P2：补第二形态——busy 期回传被 CLI 排队后
                            # 内嵌注入下一轮用户消息（system-reminder 包装、origin=
                            # human），此前 startswith 口径识别不到，历史重建把它渲染
                            # 成带原始 XML 的普通用户气泡，等待线永不定格。
                            _m_pos = t.find("Another Claude session sent a message")
                            if _m_pos >= 0 and "<cross-session-message" in t:
                                _seg = t[_m_pos:]
                                nm = _re.search(r'from-name="([^"]*)"', _seg)
                                body = _re.search(
                                    r"<cross-session-message[^>]*>(.*)</cross-session-message>",
                                    _seg, _re.S)
                                lines.append({"role": "peer",
                                              "name": (nm.group(1) if nm else "其他会话"),
                                              "text": ((body.group(1) if body else _seg).strip())[:8000],
                                              "ts": o.get("timestamp") or ""})
                                # 内嵌形态：同一条 user 行还含用户真实输入——剔除整个
                                # system-reminder 注入块，剩余文本照常出 user 气泡
                                # （独立形态整行即回传，continue）
                                if _m_pos == 0 and t.strip().startswith("Another Claude session"):
                                    continue
                                t = _re.sub(r"<system-reminder>.*?</system-reminder>",
                                            "", t, flags=_re.S).strip()
                                if not t:
                                    continue
                            # v2.37R6（载入自愈①）：agent-message 通知形态回传
                            # 入回放——此前只在实时流被识别（R2 补的 SSE 分支），
                            # 转写重建不产出 → 载入后对应转交线成假等待残留
                            # （用户实测 4 条 18m+ 秒表狂走）。有完整开闭标签
                            # 才判（与实时口径一致），产 peer 行走前端既有按名
                            # 配对定格
                            _am = _re.search(r"<agent-message[^>]*>[\s\S]*?</agent-message>", t)
                            if _am:
                                _anm = _re.search(r'from-name="([^"]*)"', t) \
                                    or _re.search(r"\bname=\"([^\"]*)\"", t)
                                lines.append({"role": "peer",
                                              "name": (_anm.group(1) if _anm else "协作代理"),
                                              "text": _am.group(0).strip()[:8000],
                                              "ts": o.get("timestamp") or ""})
                                continue
                            # harness 通道从 stdin 注入，promptSource 是 "sdk"（不是 typed）；
                            # 排除标准是"非用户输入"（工具注入 default）——命令噪音由 _SKIP_RE 挡
                            # v2.27.23：超窗续命的 [系统] 历史注入不进气泡流——
                            # 用户定调"后台化，别让我看到"：几十万 token 的历史主干
                            # 刷满整屏。折叠成一行 renew 分割线，记忆在新会话上下文
                            # 里完整保留（注入真实发生），只是 UI 不渲染原文。
                            if t.lstrip().startswith("[系统] 上一会话上下文已超当前模型窗口"):
                                rounds = sum(1 for _ln in t.splitlines()
                                             if _ln.startswith(("用户：", "助手：")))
                                lines.append({"role": "renew",
                                              "text": "上下文超窗，已自动重开会话（%d 轮历史已后台迁移）" % rounds,
                                              "ts": o.get("timestamp") or ""})
                                continue
                            # v2.34.2（R1）：续发消息行按唯一句式前缀跳过
                            # 不出——警示卡由 harness_audit_log 回放（文本与
                            # 续发消息同一字符串，出两份就是双卡）。判定用
                            # _AUDIT_MSG_PREFIX 而非宽 "[审计]"：用户手打以
                            # [审计] 开头的普通消息必须照常出 user 行回放。
                            if t.lstrip().startswith(_AUDIT_MSG_PREFIX):
                                continue
                            # v3.3.2：机器注入弱化行（独立成对才判）——历史重建
                            # 不再把它渲染成完整用户气泡+切割回合（live 侧
                            # handleEvent 同口径 renderSysNote）
                            _sn = _sysnote_of(t, o.get("timestamp"))
                            if _sn:
                                lines.append(_sn)
                                continue
                            ps_ok = (o.get("promptSource") in (None, "typed", "sdk")) or \
                                (o.get("origin") or {}).get("kind") == "human"
                            if t and ps_ok and not _SKIP_RE.match(t.strip()):
                                lines.append({"role": "user", "text": t[:8000],
                                              "ts": o.get("timestamp") or ""})
                        elif isinstance(content, list):
                            # v2.37R6（载入自愈①）：list 内容的 text 块里的
                            # agent-message 回传同样入回放（str 分支同款口径）
                            _am_skip = None
                            for _tb in content:
                                if not (isinstance(_tb, dict)
                                        and _tb.get("type") == "text"):
                                    continue
                                _tx = _tb.get("text") or ""
                                _am = _re.search(r"<agent-message[^>]*>[\s\S]*?</agent-message>", _tx)
                                if _am:
                                    _anm = _re.search(r'from-name="([^"]*)"', _tx) \
                                        or _re.search(r"\bname=\"([^\"]*)\"", _tx)
                                    lines.append({"role": "peer",
                                                  "name": (_anm.group(1) if _anm else "协作代理"),
                                                  "text": _am.group(0).strip()[:8000],
                                                  "ts": o.get("timestamp") or ""})
                                    _am_skip = id(_tb)
                                    break
                            trs = [b for b in content
                                   if isinstance(b, dict) and b.get("type") == "tool_result"]
                            if trs:
                                # 执行结果挂回对应 tool_use 行（前端详情弹层用）
                                for b in trs:
                                    line = call_by_id.get(b.get("tool_use_id"))
                                    # v2.28：识图 MCP 调用——结果落 peer 行（前端
                                    # 📥 回传气泡），对应 vision_relay 分割线定格用时
                                    if isinstance(line, dict) and "_vr" in line:
                                        rc = b.get("content")
                                        if isinstance(rc, list):
                                            rc = chr(10).join(x.get("text", "") for x in rc
                                                              if isinstance(x, dict) and x.get("type") == "text")
                                        vrow = line["_vr"]
                                        vrow["dur"] = _iso_dur_sec(vrow.get("ts"), o.get("timestamp"))
                                        vrow["err"] = bool(b.get("is_error"))
                                        lines.append({"role": "peer", "name": "识图",
                                                      "text": (rc or "（识图失败，无返回内容）")[:8000],
                                                      "ts": o.get("timestamp") or ""})
                                        continue
                                    # v3.2.21（用户实锤「为啥不能回放」缺口①）：
                                    # 同 tool_use_id 重试（先报错后成功）——成功
                                    # 结果覆盖报错结果（agentId 在成功结果里，
                                    # 保先到的错会把回放 id 一起丢掉）
                                    if line is None:
                                        continue
                                    if (line.get("result") is not None
                                            and not (line.get("err") and not b.get("is_error"))):
                                        continue
                                    rc = b.get("content")
                                    if isinstance(rc, list):
                                        rc = chr(10).join(x.get("text", "") for x in rc
                                                   if isinstance(x, dict) and x.get("type") == "text")
                                    line["result"] = (rc or "")[:8000]
                                    if b.get("is_error"):
                                        line["err"] = True
                                    else:
                                        line.pop("err", None)
                                continue
                            texts, imgs, files = [], 0, []
                            for b in content:
                                if not isinstance(b, dict):
                                    continue
                                # R6 复审 E：agent-message 块已产 peer 行，不进 user 气泡
                                if _am_skip is not None and id(b) == _am_skip:
                                    continue
                                if b.get("type") == "text" and b.get("text"):
                                    texts.append(b["text"])
                                elif b.get("type") == "image":
                                    imgs += 1
                            t = " ".join(texts)
                            m_att = _extract_att(t)
                            if m_att:
                                files = m_att
                                t = _strip_att(t)
                            # v3.2.16（用户最后定调，复原收敛）：贴图占位回显
                            # ——CLI 对每次贴图落两条 user 行（base64 块+上传附
                            # 件渲染真图缩略 + "[Image: source: …]" 纯回显行）。
                            # 回显标记一律剥掉、路径绝不并入 files（上传副本的
                            # chips 恒可点开预览，Temp 路径并进只会出死链）；
                            # 剥完空壳（无文字无他附件）整行丢弃——消息列内
                            # 永远不出现图片链接行。v3.2.14 的 hash→原名改写
                            # 撤销（依赖新路由，未重启后端时点图全裂）
                            _ims = _IMG_ECHO_RE.findall(t)
                            if _ims:
                                t = _IMG_ECHO_RE.sub("", t).strip()
                                if not t and not m_att:
                                    continue
                            # v3.2.12：中断/续跑机器标记行整行丢弃
                            if _NOISE_RE.match((t or "").strip()):
                                continue
                            # v3.2.12：自动续命摘要折叠 renew 线
                            if _CONT_RE.match((t or "").strip()):
                                lines.append({"role": "renew",
                                              "text": "会话自动续命（上下文摘要已并入模型记忆）",
                                              "ts": o.get("timestamp") or ""})
                                continue
                            # v3.3.2：机器注入弱化行（纯文本+完整标签对才判；
                            # 带附件=真人粘贴，不误伤）
                            if not imgs and not files:
                                _sn = _sysnote_of(t or "", o.get("timestamp"))
                                if _sn:
                                    lines.append(_sn)
                                    continue
                            if (t or imgs or files) and not _SKIP_RE.match((t or "").strip()):
                                # v3.2.13：发送侧孪生回显——base64 行紧随的
                                # marker-only 行（无文字无图、files 是上一条的
                                # 子集）是同一附件的重复回显，整条丢弃（用户
                                # 定调「不要给我渲染出来」）；纯文件附件无
                                # base64 孪生，不满足 images>0 判据不会误伤
                                if (not t and not imgs and files and _last_u
                                        and _last_u[1] > 0
                                        and set(files) <= set(_last_u[0] or [])):
                                    continue
                                lines.append({"role": "user", "text": t[:8000], "images": imgs, "files": files,
                                              "ts": o.get("timestamp") or ""})
                                _last_u = (files, imgs)
                    elif typ == "assistant" and isinstance(content, list):
                        texts, tools, thinks = [], [], []
                        for b in content:
                            if not isinstance(b, dict):
                                continue
                            if b.get("type") == "text" and b.get("text"):
                                texts.append(b["text"])
                            elif b.get("type") == "thinking" and b.get("thinking"):
                                thinks.append(b["thinking"])
                            elif b.get("type") == "tool_use":
                                tools.append({"id": b.get("id", ""), "name": b.get("name", ""),
                                              "summary": _tool_summary(b.get("name", ""), b.get("input")),
                                              "input": b.get("input") or {},
                                              # v2.3.2：行级 ts——前端历史重建给转交等待线
                                              # 提供真实起点（此前缺字段，恒传 0 回退 Date.now，
                                              # 定格「用时」恒 0s——审计 P1）
                                              "ts": o.get("timestamp") or ""})
                        # 思考先出：一轮里 thinking 在工具调用之前，重建后「思考抽屉」才在
                        # 「执行抽屉」上方（与流式渲染同序）
                        if thinks:
                            # v2.3.12 补 ts：此前 thinking/assistant 行不带 ts →
                            # 只读模式轮时长恒 0（「已工作 N 个步骤」出不来时间）、
                            # 思考段时长恒「持续了几秒」无法给精确值（用户实锤）
                            lines.append({"role": "thinking", "text": "\n".join(thinks)[:8000],
                                          "ts": o.get("timestamp") or ""})
                        # 空白/纯换行的 text 块要丢掉：模型每轮都会吐一个 "\n\n" 占位，
                        # 落盘后仍是真值 → 重建时每条渲染成一个空白 AI 气泡（历史会话
                        # 满屏空白圆角条的根因），还把真正的思考/工具行挤出可视区。
                        t = "\n".join(texts).strip()
                        # v3.2.12（用户定调「中断的消息不要显示」）：中断回显
                        # "No response requested." 是 CLI 协议噪音非模型输出，
                        # 从文本里剥除；同轮若还有思考/工具（中断前的工作）保留
                        t = t.replace("No response requested.", "").strip()
                        if t:
                            # v2.38 带 model：前端历史重建气泡的模型徽章数据源
                            # （此前不落 → 旧会话气泡只剩头像字母没模型名，用户实锤）
                            lines.append({"role": "assistant", "text": t[:8000],
                                          "ts": o.get("timestamp") or "",
                                          "model": (o.get("message") or {}).get("model") or ""})
                        for tl in tools:
                            if tl["name"] in _VISION_TOOLS:
                                # v2.28：识图 MCP = vision_relay 分割线行（前端 📤
                                # 转交线+秒表），不出普通工具卡；结果由 tool_result
                                # 分支挂回成 peer 行（📥 回传气泡）
                                row = {"role": "vision_relay", "dur": None,
                                       "ts": tl.get("ts") or ""}
                                lines.append(row)
                                if tl["id"]:
                                    call_by_id[tl["id"]] = {"_vr": row}
                                continue
                            row = {"role": "tool", "text": tl["name"], "summary": tl["summary"],
                                   "input": tl["input"], "result": None,
                                   "tid": tl["id"] or "",
                                   "ts": tl.get("ts") or ""}
                            if tl["id"]:
                                call_by_id[tl["id"]] = row
                            lines.append(row)
        except OSError:
            return False
        return True

    lines = []
    call_by_id = {}           # tool_use_id -> 行 dict（把 tool_result 挂回调用行）
    found_any = False
    main_dir = None           # v2.43：主会话 jsonl 所在项目目录（子代理转写定位用，与回放接口同源）
    for csid in ordered:
        for cand in _glob.glob(os.path.join(proj, "*", csid + ".jsonl")):
            if main_dir is None:
                main_dir = os.path.dirname(cand)
            if _parse_one(cand, lines, call_by_id):
                found_any = True
            break
    if not found_any:
        return None
    # v2.34.1：审计警示卡（audit log）按 ts 并入回放——warn/降级/中断档的
    # 卡此前只在实时事件流，jsonl 里没有对应行，刷新即失。卡落在本会话
    # sid 维度（跨血统链全量），按时间戳稳定排序插回各回合 result 之后。
    try:
        arows = _audit_log_read(s.sid)
        if arows:
            from datetime import datetime as _dt, timezone as _tz

            def _tk(ln):
                try:
                    return _dt.fromisoformat(
                        str(ln.get("ts") or "").replace("Z", "+00:00"))
                except Exception:
                    return _dt.min.replace(tzinfo=_tz.utc)
            for ln in lines:
                ln["_k"] = _tk(ln)
            for a in arows:
                a["_k"] = _tk(a)
            lines = lines + arows
            lines.sort(key=lambda x: x["_k"])   # 稳定排序：同刻保持原相对序
            for ln in lines:
                ln.pop("_k", None)
    except Exception:
        pass
    # v3.2.21（用户实锤「为啥不能回放」缺口②）：agentId 兜底——Task/Agent
    # 行结果缺 id（报错重试/空结果/超长截断）时，从 subagents/*.meta.json
    # 反查：文件名即 agentId，toolUseId 精确对齐（tid），desc+agentType 兜
    # 底。回放窗格/目录/agentline 回绑全靠这个 id——缺它=「无 agentId 无法
    # 回放」。meta 目录直扫（每会话个位数文件，无缓存避免运行中新增漏查）
    try:
        _aid_re = re.compile(r"(?<![a-zA-Z])agentId[:\"'\s]+[0-9A-Za-z_-]{8,64}", re.I)
        _aidm = {}
        if main_dir:
            for csid in ordered:
                _sd = os.path.join(main_dir, csid, "subagents")
                if not os.path.isdir(_sd):
                    continue
                for fn in os.listdir(_sd):
                    if not (fn.startswith("agent-") and fn.endswith(".meta.json")):
                        continue
                    try:
                        with open(os.path.join(_sd, fn), "r", encoding="utf-8",
                                  errors="replace") as _mf:
                            _mj = json.load(_mf)
                    except Exception:
                        continue
                    _aid = fn[len("agent-"):-len(".meta.json")]
                    if _mj.get("toolUseId"):
                        _aidm[("t", _mj["toolUseId"])] = _aid
                    _aidm.setdefault(("d", str(_mj.get("agentType") or ""),
                                      str(_mj.get("description") or "")), _aid)
        for ln in lines:
            if (not _aidm or ln.get("role") != "tool"
                    or ln.get("text") not in ("Task", "Agent")):
                continue
            if _aid_re.search(str(ln.get("result") or "")):
                continue
            _inp = ln.get("input") or {}
            _aid = (_aidm.get(("t", ln.get("tid")))
                    or _aidm.get(("d", str(_inp.get("subagent_type")
                                            or _inp.get("agent_type") or ""),
                                  str(_inp.get("description") or ""))))
            if _aid:
                _rc = str(ln.get("result") or "")
                if len(_rc) < 7000:
                    ln["result"] = (_rc + "\nagentId: " + _aid).strip()
                else:   # 超长结果——id 前置，绝不因截断再丢
                    ln["result"] = ("agentId: " + _aid + "\n" + _rc)[:8000]
    except Exception:
        pass
    # v2.43：子代理会话主 flow 化——Agent/Task 派发行后注入子代理过程段行
    # （sub_open + sub_text/sub_think/sub_tool/sub_result/sub_note 序列，前端
    # 聚段渲染）。数据源与回放接口同源（_subagent_rows_for 双源），容量护栏
    # 见 _inject_subagent_blocks 头注释。异常吞掉——注入失败退化为原有形态
    # （Agent 卡+result），绝不影响主链回放。
    try:
        lines = _inject_subagent_blocks(lines, ordered, main_dir)
    except Exception:
        pass
    return lines

# ---- from claude_harness.py:2525 (_extract_att) ----


def _extract_att(t):
    """从 user 文本里剥出 [附件，可用 Read 工具读取] 后的路径列表（v2 发送格式回读）。"""
    if not t or "[附件" not in t:
        return None
    idx = t.find("[附件")
    tail = t[idx:]
    paths = [l.strip() for l in tail.splitlines()[1:] if l.strip() and (":" in l or l.startswith("\\\\"))]
    return paths or None

# ---- from claude_harness.py:2535 (_strip_att) ----


def _strip_att(t):
    idx = t.find("[附件")
    return (t[:idx] if idx >= 0 else t).strip()

# ---- from claude_harness.py:2540 (_tool_summary) ----


def _tool_summary(name, input):
    i = input or {}
    try:
        if name in ("Read", "Write", "Edit"):
            return i.get("file_path", "")
        if name in ("Bash", "PowerShell"):
            return i.get("command", i.get("cmd", ""))
        if name in ("Grep", "Glob"):
            return i.get("pattern", "")
        if name.startswith("mcp__"):
            for k, v in i.items():
                if isinstance(v, str) and v:
                    return "%s=%s" % (k, v[:60])
        if isinstance(i.get("cmd"), str):
            return i["cmd"]
        return ""
    except Exception:
        return ""

# ---- from claude_harness.py:3078 (_subagent_rows_from_jsonl) ----


# v3.2.6R4：子代理回放工具行的写盘命令判定（前端 _HG_EXP_WRITE_RE 的完整
# Python 复刻——四分支：写动词 / git 写子命令 / -delete / 重定向 / 解释器
# -c|-e；re.I 对齐 JS /i）。两侧需同步维护；保守方向：宁可错杀（断组直挂）
# 绝不把写命令聚进「查阅」组
_SUBAGENT_CMD_WRITE_RE = re.compile(
    r"\b(sed\s+-i|tee|mv|cp|rm|mkdir|touch|chmod|del|erase|out-file|move-item"
    r"|copy-item|remove-item|set-content|add-content|clear-content|new-item"
    r"|rename-item)\b"
    r"|(^|[;&]\s*)git\s+(add|commit|rm|mv|checkout|switch|restore|reset|clean"
    r"|revert|cherry-pick|merge|rebase)\b"
    r"|\s-delete\b"
    r"|(^|\s|;|&|\|)\s*(?:&?>|2?>|>{1,2})\s*\S"
    r"|\b(python|py|node|perl|ruby|awk)\s+(-c|-e)\b",
    re.I)


def _subagent_rows_from_jsonl(path):
    """v2.42（内部共用）：解析子代理转写 jsonl → 回放 rows。返回 None=文件
    不可读（miss，调用方继续试兜底源）；list=解析结果（可为空——文件存在
    但无有效行，如实返回空让前端走「转写存在但无可回放内容」分支）。
    抽出共用的原因：新版 CLI（2.1.267+ Agent 工具）的子代理转写迁移到
    %LOCALAPPDATA%\\Temp\\claude\\<项目转码名>\\<主会话id>\\tasks\\<taskId>.output，
    实测行结构与 projects/<proj>/<agentId>.jsonl 同构（assistant 行
    message.content 含 text/tool_use/thinking 块且带 model 字段，user 行
    tool_result 块同构；多出的 attachment/system 行被 type 过滤跳过，
    thinking 块本就不提取——回放不需要），两源走同一解析避免复制。
    容量护栏沿用 v2.37R3 流式「保头 150 + 滚动尾 50」——O(1) 内存全量
    扫描，无硬帽：尾部恒为真实最后 50 行（最终交付报告不会丢），省略数
    精确。"""
    rows = []
    from collections import deque
    _tail = deque(maxlen=50)
    _total = 0

    def _push(row):
        """rows 满 200 后新行溢出进滚动尾窗（list.pop(200) 对 ≤201 长度是常数代价）。"""
        nonlocal _total
        _total += 1
        rows.append(row)
        if len(rows) > 200:
            _tail.append(rows.pop(200))

    def _txt(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text")
        return ""

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                # v2.37R2/R3（复审2/R3）：全量扫描无硬帽——rows 满 200 后新行
                # 溢出进 _tail 滚动窗（见 _push），尾部恒为真实最后 50 行
                if not raw:
                    continue
                try:
                    o = json.loads(raw)
                except Exception:
                    continue
                typ = o.get("type")
                if typ not in ("assistant", "user"):
                    continue
                m = o.get("message") or {}
                content = m.get("content")
                blocks = content if isinstance(content, list) else []
                if typ == "assistant":
                    model = m.get("model") or ""
                    # v3.2.6（ZCode 子智能体模式）：行级 ts——窗格时间线用首末行
                    # ts 算「已工作」总时长、邻行 ts 差算思考段「持续了 N 秒」
                    _ts = o.get("timestamp") or ""
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and (b.get("text") or "").strip():
                            _push({"k": "text", "text": b["text"][:2000],
                                   "model": model, "ts": _ts})
                        elif b.get("type") == "thinking" and (b.get("thinking") or "").strip():
                            # v2.43：thinking 入 rows——子代理会话主 flow 化要
                            # 「有思考」（用户原话）；回放窗格同渲染（hg-sub-think
                            # 折叠行）。旧行为只 text/tool_use，think 块被丢弃。
                            _push({"k": "think", "text": b["thinking"][:2000],
                                   "model": model, "ts": _ts})
                        elif b.get("type") == "tool_use":
                            inp = b.get("input") or {}
                            # v3.3.1（用户实锤「没看到方案输出」）：handback 交付形态
                            # 的子代理——最终报告不是 text 块而是 SubagentHandback
                            # 工具的 input（CLI 转写里根本没有那段正文）。原样出
                            # tool 行 hint 恒空=报告在回放/主流段注入两路永不可见。
                            # 报告行按 text 出（k='text'），取 input 里最长的字符串
                            # 字段（防 schema 漂移）；截 8000（tail 窗保证末行不丢）
                            if b.get("name") == "SubagentHandback":
                                _rep = ""
                                for _v in inp.values():
                                    if isinstance(_v, str) and len(_v) > len(_rep):
                                        _rep = _v
                                if _rep.strip():
                                    _push({"k": "text", "text": _rep[:8000],
                                           "model": model, "ts": _ts})
                                    continue
                            hint = (inp.get("command") or inp.get("file_path")
                                    or inp.get("path") or inp.get("pattern")
                                    or inp.get("query") or inp.get("description")
                                    or inp.get("subject") or inp.get("prompt")
                                    or inp.get("message") or "")
                            # v3.2.6R3/R4（审计残留）：Bash/PowerShell 的写盘
                            # 标记按**全量命令**判定（写动词/重定向常在尾部，
                            # hint 的 120 字截断会漏检→前端伪 input 把写命令
                            # 误聚进查阅组）。完整复刻前端 _HG_EXP_WRITE_RE
                            # 四分支（写动词/git 写子命令/-delete/重定向/解释
                            # 器 -c|-e；/i 对齐 re.I）——保守方向：绝不把写
                            # 命令聚组，两端正则需同步维护
                            _row = {"k": "tool", "name": b.get("name") or "",
                                    "hint": str(hint)[:120], "ts": _ts}
                            # v3.2.25（用户实锤「历史回放看不到改动」）：
                            # Edit/Write 的输入体随行（old/new/content 各截
                            # 3000）——窗格回放据此画 diff/写入内容，不再只
                            # 有「成功」一行
                            if b.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                                _row["in"] = {
                                    _k: (_v[:3000] if isinstance(_v, str) else _v)
                                    for _k, _v in inp.items()
                                    if _k in ("file_path", "old_string", "new_string",
                                              "content", "edits", "new_source")}
                            if b.get("name") in ("Bash", "PowerShell"):
                                _cmd = str(inp.get("command")
                                           or inp.get("cmd") or "")
                                if _SUBAGENT_CMD_WRITE_RE.search(_cmd):
                                    _row["w"] = 1
                            _push(_row)
                else:
                    # v3.2.21（用户定调「有来有回」）：子代理侧 user 行（首次
                    # 派发提示 / SendMessage 追加消息）——入线程作来向消息，
                    # 与 think/tool/text 交替成完整对话流；tool_result 载体行
                    # 的 _txt 为空自然跳过；CLI 协议噪音（system-reminder/
                    # command 包裹）不是人来向，同样跳过
                    _ut = _txt(content).strip()
                    if (_ut and not _ut.startswith("<")
                            and not (_SKIP_RE and _SKIP_RE.match(_ut))):
                        _push({"k": "user", "text": _ut[:1200],
                               "ts": o.get("timestamp") or ""})
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            _push({"k": "result",
                                   "text": _txt(b.get("content"))[:200],
                                   "err": bool(b.get("is_error")),
                                   "ts": o.get("timestamp") or ""})
    except OSError:
        return None
    # v2.37R2/R4：头 150 + 省略标注 + 真实尾 50——rows 恒持前 200，
    # rows[150:]（50 行）与 _tail 拼接后取尾 50 = 真实最后 50 行
    # （终审2：旧式仅拼 _tail 会丢 rows[150:200] 区间，[201,249] 全错）
    if _total > 200:
        rows = (rows[:150]
                + [{"k": "note", "text": "…中间已省略 %d 条（详情见完整转写）…" % (_total - 200)}]
                + (rows[150:] + list(_tail))[-50:])
    return rows

# ---- from claude_harness.py:3170 (_subagent_transcript_candidates) ----


def _subagent_transcript_candidates(main_dir, csids, agent):
    """v2.43（内部共用）：agentId → 子代理转写候选路径（按优先级序）。
    ① projects 主会话同目录 <agent>.jsonl（旧版 CLI）；② 新版 CLI（2.1.267+）
    tasks 目录 %LOCALAPPDATA%\\Temp\\claude\\<项目转码名>\\<主会话id>\\tasks\\
    <agent>.output——项目转码名即 main_dir 的 basename，lineage 全链逐会话试
    （task_id 全局唯一，多目录存在也不歧义）；③ v2.46R（P3）：第三形态
    projects/<主会话id>/subagents/agent-<agentId>.jsonl——真实实证（8faf 会话
    9/21）：该形态下 tasks 目录不存在、projects 同名 jsonl 也不存在，只有
    subagents 目录在（SendMessage 续派会话的现行 CLI 落盘形态），缺此源则
    双源全 miss=历史/回放/实时思考全断。回放接口、transcript_for 段注入与
    subagent_tail 轮询共用本查找。"""
    out = []
    if main_dir:
        out.append(os.path.join(main_dir, agent + ".jsonl"))
    la = os.environ.get("LOCALAPPDATA")
    if la and main_dir:
        for csid in csids or []:
            out.append(os.path.join(la, "Temp", "claude",
                                    os.path.basename(main_dir), csid,
                                    "tasks", agent + ".output"))
    if main_dir:
        for csid in csids or []:
            out.append(os.path.join(main_dir, csid, "subagents",
                                    "agent-" + agent + ".jsonl"))
    return out

# ---- from claude_harness.py:3197 (_subagent_rows_for) ----


def _subagent_rows_for(main_dir, csids, agent):
    """v2.43（内部共用）：候选路径依序解析（isfile 才读；读失败 None 时试
    下一候选），返回首个可读结果；None=两源均未命中。
    v3.2.6：现行 CLI（Task 工具）会先落一个 **0 字节**的 Temp tasks
    <taskId>.output 占位、真实转写随后才写 projects/<主会话id>/subagents/
    agent-<id>.jsonl——旧「rows is not None 即返回」会在占位文件上解析出
    [] 短路，永远到不了第三形态（实测复现：回放恒「转写存在但无可回放
    内容」）。改为：空解析继续试下一候选，全空才如实回空表（前端给中性
    文案，不进 noreplay 锁死集）。"""
    first_empty = None
    for p in _subagent_transcript_candidates(main_dir, csids, agent):
        if os.path.isfile(p):
            rows = _subagent_rows_from_jsonl(p)
            if rows is None:
                continue        # 读失败——试下一候选
            if rows:
                return rows
            if first_empty is None:
                first_empty = rows
    return first_empty

# ---- from claude_harness.py:3208 (_SUBAGENT_BLK_FULL) ----


# v2.43：transcript_for 注入全量过程行的段数上限——更早的段只出 stub 段头
# （点击段头走回放窗格看全程）。3 = 每次切会话至多 3 次转写读+解析的
# 性能护栏（数百 KB 级 JSONL，实测每段数十 ms；无子代理会话零开销）。
_SUBAGENT_BLK_FULL = 3

# ---- from claude_harness.py:3214 (_inject_subagent_blocks) ----


def _inject_subagent_blocks(lines, csids, main_dir):
    """v2.43：transcript_for 尾段——Agent/Task 派发行后插入子代理过程行，
    前端聚成主 flow 里的子代理段（与实时路径同构）。行型：
    sub_open（段头数据：agent/type/desc/model/err[/stub]）/ sub_text /
    sub_think / sub_tool（result 就近挂回）/ sub_result（孤儿结果）/ sub_note。
    容量护栏：每段沿用回放「头150+尾50」窗口（_subagent_rows_from_jsonl）；
    仅最近 _SUBAGENT_BLK_FULL 个段拉全量，更早段 stub=True 只出段头。
    无转写（旧会话/未完成回合/已被清理/空转写）不出段——退化为原有形态
    （Agent 卡+result），不报错（老会话兼容铁律）。"""
    if not main_dir:
        return lines
    ag_rows = [i for i, ln in enumerate(lines)
               if isinstance(ln, dict) and ln.get("role") == "tool"
               and ln.get("text") in ("Task", "Agent")]
    # v2.46R（P1）：不做「无 Agent 行即早退」——纯续派会话（重启后第一步就
    # SendMessage 续派，全程无 Task/Agent 工具行）也要走下面的 resumedAgentId
    # 补段循环；循环自然空转，由末尾 `if not parsed` 兜底
    parsed = []
    for i in ag_rows:
        # v2.46R（P7）：宽容形态——裸文本 `agentId: x` 与 JSON `"agentId":"x"`
        # 都命中（另一设备实测 JSON 形态全漏=重开看不到 agent 历史的主因之
        # 一）；(?<![a-zA-Z]) 防误吞 resumedAgentId 尾段（那是续派循环的职责）
        m = re.search(r"(?<![a-zA-Z])agentId[\"\':\s]+([0-9a-zA-Z_-]{8,64})",
                      str((lines[i] or {}).get("result") or ""))
        if m:
            parsed.append((i, m.group(1)))
    # v2.46：SendMessage 续派补段——今天的子代理多为 SendMessage 续派（真实
    # 转写实证：55 个派发/续派 result 里 Agent 37 个带裸 agentId: 文本、
    # SendMessage 17 个全是 JSON 形态只带 resumedAgentId，旧正则全漏）。跨会话
    # 续派的代理在本会话没有 Agent 派发行 → 永远不出段（重启后 agent 历史
    # 「消失」的一路根因）。从 SendMessage 行 result 提取 resumedAgentId，
    # 首次出现且尚未建段的 agentId 在该行后注入段（同代理与 Agent 派发行
    # 去重；JSON/裸文本两种形态都匹配）。
    _seen = set(aid for _, aid in parsed)
    for i, ln in enumerate(lines):
        if not (isinstance(ln, dict) and ln.get("role") == "tool"
                and ln.get("text") == "SendMessage"):
            continue
        m = re.search(r"resumedAgentId[\"\':\s]+([0-9a-zA-Z_-]{8,64})",
                      str(ln.get("result") or ""))
        aid = m.group(1) if m else ""
        if not aid or aid in _seen:
            continue
        _seen.add(aid)
        parsed.append((i, aid))
    parsed.sort(key=lambda p: p[0])
    if not parsed:
        return lines
    full = set(aid for _, aid in parsed[-_SUBAGENT_BLK_FULL:])
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        hit = next((p for p in parsed if p[0] == i), None)
        if not hit:
            continue
        _, aid = hit
        inp = ln.get("input") or {}
        # v2.46：SendMessage 行无 description/subagent_type——desc 回退收件人+
        # 消息头（段头悬浮说明有内容可看），type 维持 Task（.output 转写里才有
        # 真实角色，rows 首个 model 行同源补模型）
        _desc = inp.get("description")
        if not _desc and ln.get("text") == "SendMessage":
            _msg = str(inp.get("message") or "").strip()
            _desc = "续派" + ((" → " + _msg[:60]) if _msg else "")
        head = {"role": "sub_open", "agent": aid,
                "type": inp.get("subagent_type") or inp.get("agent_type") or "Task",
                "desc": str(_desc or "")[:200],
                "model": "", "err": bool(ln.get("err"))}
        if aid not in full:
            head["stub"] = True
            out.append(head)
            continue
        rows = _subagent_rows_for(main_dir, csids, aid)
        if not rows:
            continue           # 无转写/空转写：不出段（老会话兼容退化）
        head["model"] = next((r.get("model") for r in rows
                              if r.get("k") == "text" and r.get("model")), "")
        blk = _map_subagent_rows(aid, rows)
        if not blk:
            continue
        out.append(head)
        out.extend(blk)
    return out

# ---- from claude_harness.py:3299 (_map_subagent_rows) ----


def _map_subagent_rows(agent, rows):
    """v2.43（内部共用）：回放 rows → 主 flow 段行序列。tool_result 就近
    挂回 sub_tool 行（FIFO 配对——转写无 tool_use_id，CLI 流序下 result 恒
    跟在其 tool_use 之后，并行多工具按到达序回填；孤儿结果独立 sub_result
    行）。sub_tool 行带 summary/input/result/err——前端懒抽屉 _histToolBodyHtml
    直接可用。"""
    out, pend = [], []
    for r in rows:
        k = r.get("k")
        if k == "text":
            out.append({"role": "sub_text", "agent": agent,
                        "text": r.get("text") or "",
                        "model": r.get("model") or ""})
        elif k == "note":
            out.append({"role": "sub_note", "agent": agent,
                        "text": r.get("text") or ""})
        elif k == "tool":
            row = {"role": "sub_tool", "agent": agent, "text": r.get("name") or "",
                   "summary": r.get("hint") or "", "input": {}, "result": None,
                   "ts": ""}
            if r.get("err"):
                row["err"] = True
            out.append(row)
            pend.append(row)
        elif k == "think":
            out.append({"role": "sub_think", "agent": agent,
                        "text": r.get("text") or ""})
        elif k == "result":
            if pend:
                t = pend.pop(0)
                t["result"] = r.get("text") or ""
                if r.get("err"):
                    t["err"] = True
            else:
                out.append({"role": "sub_result", "agent": agent,
                            "text": r.get("text") or "",
                            "err": bool(r.get("err"))})
    return out
