# -*- coding: utf-8 -*-
"""子代理冷查询读模型（IO 层，对位 ZCode subagent-observation.ts）。

每会话一只（get_model 注册表）：主会话 jsonl 按字节水位增量吸收成事实表，
子代理转写三源候选尾探（mtime 门控），meta.json 一次性读父子链接——
全部喂 subagent_projection.project 现算投影。真源=磁盘：F5/切会话/后端
重启的正确性由数据源决定而非内存（designer 方案，用户拍板「全盘抄
ZCode」）。

性能口径（方案第五节）：稳态 refresh = N 次 stat + 未变文件零读盘 +
增量尾读；首查全扫一次（55MB≈0.23s 实证同款子串门控）。fact 表
append-only 随会话生灭（内存），不入盘。
"""
import glob
import io
import json
import os
import threading
import time

from .subagent_projection import (collect_main_facts, child_outcome_from_tail,
                                  project, _RE_ACK_AGENT, _RE_AGENT_JSON,
                                  _looks_id, FRESH_WINDOW_MS)

_TAIL_BYTES = 65536        # 子代理转写尾探窗口（覆盖几十行足够）
_FACT_GATE = ('"tool_use"', '"tool_result"', 'task-notification')


def _line_chunks(path, offset):
    """从 offset 起读增量完整行（最后换行边界；半行留下次）。

    返回 (lines, new_offset)；文件缩水/不存在 → (None, 0)=caller 重扫。"""
    try:
        st = os.stat(path)
    except OSError:
        return None, 0
    size = st.st_size
    if size < offset:
        return None, 0
    if size == offset:
        return [], offset
    with open(path, "rb") as f:
        f.seek(offset)
        buf = f.read(size - offset)
    cut = buf.rfind(b"\n")
    if cut < 0:
        return [], offset        # 半行：等下一批
    lines = buf[:cut].decode("utf-8", errors="replace").split("\n")
    return [ln for ln in lines if ln.strip()], offset + cut + 1


class SubagentReadModel(object):

    def __init__(self, sid, projects_root=None):
        self._sid = sid
        self._projects_root = projects_root or os.path.join(
            os.path.expanduser("~"), ".claude", "projects")
        self._lock = threading.Lock()
        self._main_wm = {}       # path → offset（缩水重扫由 _line_chunks 报）
        self._facts = []
        self._meta_links = {}    # tid → agentId（meta.json toolUseId）
        self._meta_dir_sig = None
        self._child = {}         # agentId → {path, mtime, size, outcome}
        self._proj = None        # 缓存投影
        self._sig = None         # 全文件 stat 签名（未变直接回缓存）

    # ---- 主 jsonl 定位（lineage 全链，旧→新） ----

    def _main_paths(self, s):
        ids = [x for x in (list(getattr(s, "lineage", None) or [])
                           + [s.session_id]) if x]
        seen, ordered = set(), []
        for i in ids:
            if i not in seen:
                seen.add(i)
                ordered.append(i)
        out = []
        for i in ordered:
            hits = glob.glob(os.path.join(self._projects_root, "*", i + ".jsonl"))
            out.extend(hits)
        return out, ordered

    # ---- meta.json 父子链接（subagents 目录，签名门控重扫） ----

    def _meta_scan(self, s, main_dir):
        if not main_dir:
            return
        ids = [x for x in (list(getattr(s, "lineage", None) or [])
                           + [s.session_id]) if x]
        sig_parts = []
        for i in ids:
            d = os.path.join(main_dir, i, "subagents")
            try:
                sig_parts.append((d, os.stat(d).st_mtime_ns))
            except OSError:
                pass
        sig = tuple(sig_parts)
        if sig == self._meta_dir_sig:
            return
        links = {}
        for d, _ in sig:
            for p in glob.glob(os.path.join(d, "agent-*.meta.json")):
                try:
                    m = json.loads(io.open(p, encoding="utf-8",
                                           errors="replace").read())
                except Exception:
                    continue
                tid = str(m.get("toolUseId") or "")
                aid = os.path.basename(p)[len("agent-"):-len(".meta.json")]
                if tid and _looks_id(aid):
                    links[tid] = aid
        self._meta_links = links
        self._meta_dir_sig = sig

    # ---- 子代理转写三源候选（与 transcript.py 同序） ----

    def _child_candidates(self, main_dir, csids, aid):
        out = []
        if main_dir:
            out.append(os.path.join(main_dir, aid + ".jsonl"))
        la = os.environ.get("LOCALAPPDATA")
        if la and main_dir:
            for c in csids:
                out.append(os.path.join(la, "Temp", "claude",
                                        os.path.basename(main_dir), c,
                                        "tasks", aid + ".output"))
        if main_dir:
            for c in csids:
                out.append(os.path.join(main_dir, c, "subagents",
                                        "agent-" + aid + ".jsonl"))
        return out

    # ---- refresh（HTTP 线程独占；reader 不碰） ----

    def refresh(self, s, force=False):
        with self._lock:
            paths, csids = self._main_paths(s)
            main_dir = os.path.dirname(paths[-1]) if paths else None
            # ① 主文件增量吸收
            sig_parts = []
            changed = force
            for p in paths:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                sig_parts.append((p, st.st_size, st.st_mtime_ns))
                off = self._main_wm.get(p, 0)
                if st.st_size == off and p in self._main_wm:
                    continue
                lines, new_off = _line_chunks(p, off)
                if lines is None:     # 缩水/换文件：全量重扫
                    lines, new_off = _line_chunks(p, 0)
                    if lines is None:
                        continue
                if lines:
                    gated = [ln for ln in lines
                             if any(g in ln for g in _FACT_GATE)]
                    if gated:
                        base = len(self._facts)
                        new = collect_main_facts(gated)
                        for k, f in enumerate(new):
                            f["i"] = base + k   # 全局事实序（跨增量批单调）
                        self._facts.extend(new)
                self._main_wm[p] = new_off
                changed = True
            # ② meta 链接（签名门控）
            self._meta_scan(s, main_dir)
            # ③ 候选 agentId：dispatch 回执提取 + meta 链接值
            aids = set()
            for f in self._facts:
                if f["kind"] == "result":
                    m = _RE_AGENT_JSON.search(f.get("text") or "") \
                        or _RE_ACK_AGENT.search(f.get("text") or "")
                    if m and _looks_id(m.group(1)):
                        aids.add(m.group(1))
                elif f["kind"] == "send_result":
                    if _looks_id(f.get("resumed") or ""):
                        aids.add(f["resumed"])
            aids.update(self._meta_links.values())
            # ④ 子代理尾探（mtime/size 门控 + child_fresh）
            now_ms = int(time.time() * 1000)
            child_states, child_fresh = {}, {}
            for aid in aids:
                cur = self._child.get(aid)
                pick = None
                for cand in self._child_candidates(main_dir, csids, aid):
                    try:
                        st = os.stat(cand)
                    except OSError:
                        continue
                    if st.st_size <= 0:
                        continue   # 0 字节占位（v3.2.6 教训）
                    pick = (cand, st.st_size, st.st_mtime_ns)
                    break
                if pick is None:
                    # 转写不存在（历史被清理/未 flush）——保留旧 outcome
                    if cur and cur.get("outcome"):
                        child_states[aid] = cur["outcome"]
                    continue
                path, size, mtime = pick
                sig_parts.append((path, size, mtime))
                if now_ms - int(mtime // 1_000_000) < FRESH_WINDOW_MS:
                    child_fresh[aid] = True   # st_mtime_ns（纳秒）→ms
                if cur and cur.get("path") == path and cur.get("size") == size:
                    if cur.get("outcome"):
                        child_states[aid] = cur["outcome"]
                    continue
                try:
                    with open(path, "rb") as f:
                        if size > _TAIL_BYTES:
                            f.seek(size - _TAIL_BYTES)
                        tail = f.read().decode("utf-8", errors="replace")
                except OSError:
                    continue
                outcome = child_outcome_from_tail(tail.split("\n"))
                self._child[aid] = {"path": path, "size": size,
                                    "outcome": outcome}
                child_states[aid] = outcome
                changed = True
            sig = tuple(sig_parts)
            if not changed and self._proj is not None and sig == self._sig:
                return self._proj
            self._sig = sig
            # ⑤ liveness + 角色名映射（session 活内存；死会话退化为空）
            proc_alive = False
            try:
                p = getattr(s, "_proc", None)
                proc_alive = bool(p is not None and p.poll() is None)
            except Exception:
                pass
            ext_ids = {}
            try:
                with s._audit_lock:
                    for _aid, _role in (s._audit.get("ids") or {}).items():
                        ext_ids[str(_role)] = str(_aid)
            except Exception:
                pass
            proj = project(self._facts, child_states=child_states,
                           liveness={"proc_alive": proc_alive,
                                     "busy": bool(getattr(s, "busy", False)),
                                     "now_ms": now_ms,
                                     "child_fresh": child_fresh},
                           external_links=self._meta_links,
                           external_ids=ext_ids)
            self._proj = proj
            return proj

    def tid_to_aid(self, tid):
        with self._lock:
            return (self._proj or {}).get("tidMap", {}).get(str(tid or "")) or ""


_models = {}
_models_lock = threading.Lock()


def get_model(sid, projects_root=None):
    with _models_lock:
        m = _models.get(sid)
        if m is None:
            m = _models[sid] = SubagentReadModel(sid,
                                                 projects_root=projects_root)
        return m
