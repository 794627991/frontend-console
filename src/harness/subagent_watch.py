# -*- coding: utf-8 -*-
"""subagent_watch —— 子代理转写 watcher（v3.5.405 建；v4 归一重构批B 升级）。

v4 职责（ZCode ingestDetachedLiveSession 对位）：扫「新鲜子代理转写」的
增量行 → 逐行解析喂 v4 子投影（v4hub.v4_sub_ingest）→ 子 pane 的
/v4/stream sub:<agent> 订阅者收到 delta 帧（子代理实时刷新红线的数据面）。
旧 emit `subagent_delta` 事件保留（旧前端兼容；批F 旧管线退役时一并下线）。

扫描覆盖两源（三源候选的③+②；源①旧版 CLI 罕见，由子 feed hydrate 兜底）：
- 源③ projects/<proj>/<csid>/subagents/agent-<id>.jsonl（SendMessage 续派）
- 源② %LOCALAPPDATA%\\Temp\\claude\\<projName>/<csid>/tasks/<id>.output
  （新版 CLI 2.1.267+ Agent 工具）——v4 前此源增量无人喂（P0-3 缺口）

设计要点：
- 只 watch 新鲜转写（mtime 120s 内）——终态文件零开销；
- 每文件记 offset（内存），只推整行（尾半行下轮补）；
- 会话按文件所属目录反查 lineage；找不到会话=不属于活会话，跳过；
- watcher 全局单线程 daemon，随 lifecycle 启动（_gc_loop 同款挂法），
  任何单轮异常静默（watcher 永不死）。
"""
import glob
import json
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


def _push_file(s, fp, aid, force=False):
    """读 fp 自 offset 起的增量整行：喂 v4 子投影 + emit 兼容事件。

    a68（用户实测「子代理过程缺失/结论永不到/永远不结束」根因）：增量
    截尾（MAX_DELTA_BYTES）只作用于**旧前端镜像事件的载荷**——子 feed
    喂入必须全量行。子代理转写里 api-request-blob 单行可达数百 KB，一次
    增量常态超 256KB，旧截尾直接把增量起点跳到文件尾=整段业务行（工具/
    收尾 handback）永久丢失，feed 冻结在中途（state.final 永空、前端
    秒表永跑）。V3 无此问题（回放走 /subagent_replay 全量文件）。

    force=True：绕过新鲜窗（订阅时刻的对账自愈用——冻结 feed 重开 pane
    时全量重推一轮，uuid 去重保证幂等）。"""
    now = time.time()
    if not force and now - os.path.getmtime(fp) > FRESH_WINDOW_S:
        return
    off = _offsets.get(fp, 0)
    sz = os.path.getsize(fp)
    if sz <= off:
        return
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        f.seek(off)
        txt = f.read()
    # 只推整行（尾半行下轮补）
    if txt and not txt.endswith("\n"):
        cut = txt.rfind("\n")
        if cut < 0:
            return
        txt = txt[:cut + 1]
        new_off = off + len(txt.encode("utf-8"))
    else:
        new_off = sz if sz == os.path.getsize(fp) else off + len(txt.encode("utf-8"))
    _offsets[fp] = new_off
    if not txt.strip():
        return
    # v4 子投影：feed 不在（pane 先开、转写后到）且 v4 客户端在场（主投影
    # 或子订阅意向——a74：子 pane 先于主窗订阅/主 store 断连窗口期原闸会
    # 误杀）→ 按需全量 hydrate（a65：转写首行出现即建出有内容的 feed，
    # 此后增量续喂；hydrate 已消费全文件，本轮增量跳过防重复，uuid 去重
    # 再兜底）。V3 模式（无主 feed 无意向）行为与旧版完全一致
    try:
        from . import v4hub
        if not v4hub.v4_sub_has(s.session_id, aid) \
                and (v4hub.v4_main_has(s.session_id)
                     or v4hub.v4_sub_wanted_has(s.session_id, aid)):
            if v4hub.v4_sub_hydrate(s.session_id, aid, [fp]):
                return
    except Exception:
        pass
    # v4 子投影：逐行解析喂入（子 pane 订阅者由此收 delta 帧）——
    # a68：全量行不截尾（截尾=业务行永久丢失，见函数头注释）
    try:
        from . import v4hub
        for raw in txt.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            v4hub.v4_sub_ingest(s.session_id, aid, obj)
    except Exception:
        pass
    # 兼容旧前端（批F 退役）：载荷防爆照旧截尾
    s.emit({"kind": "event", "data": {
        "type": "subagent_delta",
        "agent": aid,
        "offset": new_off,
        "text": txt[:MAX_DELTA_BYTES],
    }})


def push_paths_once(s, aid, paths):
    """a68：订阅时刻的强制对账——对候选路径全量重推一轮（绕过新鲜窗）。
    冻结 feed（截尾时代丢的尾段/中途打开-pane 缓存的残缺投影）在用户
    重开 pane 时由此自愈；uuid 去重保证与既有行幂等。"""
    for p in paths or []:
        if not p or not os.path.isfile(p):
            continue
        try:
            _push_file(s, p, aid, force=True)
        except Exception:
            pass


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
                            _push_file(s, fp,
                                       os.path.basename(fp)[len("agent-"):-len(".jsonl")])
                        except Exception:
                            continue
            # 源②（新版 CLI Agent 工具 tasks/<id>.output）——v4 补的覆盖面
            la = os.environ.get("LOCALAPPDATA")
            if la:
                for s in _iter_sessions():
                    sid = getattr(s, "session_id", None)
                    if not sid:
                        continue
                    proj_name = None
                    for cand in glob.glob(os.path.join(
                            home, ".claude", "projects", "*", sid + ".jsonl")):
                        proj_name = os.path.basename(os.path.dirname(cand))
                        break
                    if not proj_name:
                        continue
                    for csid in [x for x in (
                            list(getattr(s, "lineage", None) or []) + [sid]) if x]:
                        for fp in glob.glob(os.path.join(
                                la, "Temp", "claude", proj_name, csid,
                                "tasks", "*.output")):
                            try:
                                _push_file(s, fp,
                                           os.path.basename(fp)[:-len(".output")])
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
