# -*- coding: utf-8 -*-
"""subagent_watch —— 子代理转写 watcher（v3.5.405 单订阅模型批A）。

ZCode subscribe 对位：窗格数据由**服务端推送**（snapshot+delta），前端不轮询。
我们的子代理内容在磁盘转写（CLI 落盘、无进程内事件），本模块用全局 watcher
线程检测「新鲜转写的增量」→ 经既有 SSE 事件流（session.emit→bus→SSE）推
`subagent_delta` 事件给前端——前端的 2s tail 轮询降级为兜底。

设计要点（对位 ZCode 机制4/5）：
- 只 watch 新鲜转写（mtime 120s 内）——终态文件零开销；
- 每文件记 offset（内存），读尾增量原文推送——解析/过滤留在前端既有
  _subDeltaFeed（已验证的行解析逻辑，不在后端重写一遍）；
- 会话按文件所属目录反查（projects/<proj>/<csid>/subagents/ 的 csid 与
  lineage 匹配）；找不到会话=文件不属于任何活会话，跳过；
- watcher 全局单线程 daemon，随 lifecycle 启动（_gc_loop 同款挂法）。
"""
import glob
import os
import threading
import time
import logging

log = logging.getLogger(__name__)

WATCH_INTERVAL_S = 1.0     # 检测间隔（实时感对位 SSE）
FRESH_WINDOW_S = 120.0     # 只看 mtime 新鲜的转写（终态零开销）
MAX_DELTA_BYTES = 262144   # 单文件单轮推送上限（256KB 防爆）

_started = False
_offsets = {}              # abs path -> 已推字节 offset


def _iter_sessions():
    from .consts import _sessions, _sessions_lock
    with _sessions_lock:
        return list(_sessions.values())


def _session_for(cs_dir, csid):
    """subagents 目录的 csid → 所属会话（lineage 含 csid 即命中）。"""
    for s in _iter_sessions():
        ids = list(getattr(s, "lineage", None) or []) + [getattr(s, "session_id", None)]
        if csid and csid in [x for x in ids if x]:
            return s
    return None


def _watch_loop():
    last_clean = 0.0
    while True:
        time.sleep(WATCH_INTERVAL_S)
        try:
            now = time.time()
            # 周期清 _offsets（终态文件离开新鲜窗后回收内存）
            if now - last_clean > 300:
                last_clean = now
                for p in list(_offsets.keys()):
                    try:
                        if now - os.path.getmtime(p) > FRESH_WINDOW_S:
                            _offsets.pop(p, None)
                    except OSError:
                        _offsets.pop(p, None)
            home = os.path.expanduser("~")
            # 只扫有活会话的项目目录（每会话的 projects/<proj> 候选）
            proj_dirs = set()
            for s in _iter_sessions():
                sid = getattr(s, "session_id", None)
                if not sid:
                    continue
                for cand in glob.glob(os.path.join(
                        home, ".claude", "projects", "*", sid + ".jsonl")):
                    proj_dirs.add(os.path.dirname(cand))
            for proj in proj_dirs:
                for sub_dir in glob.glob(os.path.join(proj, "*", "subagents")):
                    csid = os.path.basename(os.path.dirname(sub_dir))
                    s = _session_for(sub_dir, csid)
                    if s is None:
                        continue
                    for fp in glob.glob(os.path.join(sub_dir, "agent-*.jsonl")):
                        try:
                            if now - os.path.getmtime(fp) > FRESH_WINDOW_S:
                                continue
                            off = _offsets.get(fp, 0)
                            sz = os.path.getsize(fp)
                            if sz <= off:
                                continue
                            if sz - off > MAX_DELTA_BYTES:
                                off = sz - MAX_DELTA_BYTES   # 爆量截尾（不推史前）
                            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(off)
                                txt = f.read()
                            # 只推整行（对齐 tail 接口的行边界语义；尾半行下轮补）
                            if txt and not txt.endswith("\n"):
                                cut = txt.rfind("\n")
                                if cut < 0:
                                    continue
                                txt = txt[:cut + 1]
                                new_off = off + len(txt.encode("utf-8"))
                            else:
                                new_off = sz if sz == os.path.getsize(fp) else off + len(txt.encode("utf-8"))
                            _offsets[fp] = new_off
                            if not txt.strip():
                                continue
                            aid = os.path.basename(fp)[len("agent-"):-len(".jsonl")]
                            s.emit({"kind": "event", "data": {
                                "type": "subagent_delta",
                                "agent": aid,
                                "offset": new_off,
                                "text": txt[:MAX_DELTA_BYTES],
                            }})
                        except Exception:
                            continue
        except Exception:
            pass   # watcher 永不死（任何单轮异常静默，下轮重来）


def ensure_started():
    """lifecycle 启动时调用一次（_gc_loop 同款挂法）。"""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_watch_loop, daemon=True).start()
