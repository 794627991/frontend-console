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


# ---------------------------------------------------------------------------
# 性能批（目录缓存 + 空闲退避）：
# - _ls(dir)：目录清单缓存（dir mtime 不变直接复用，免每秒全量 glob 枚举
#   ——枚举会触发 Defender 实时扫描放大，实测单轮 1.33ms×每秒）；新建/
#   删除文件必然改 dir mtime，缓存不会漏新转写
# - 空闲退避：30s 无任何增量数据时扫描间隔 1s→5s（有数据立即回 1s，
#   实时感对位 SSE 不变——活跃代理的转写在持续追加，永远处于快档）
# ---------------------------------------------------------------------------
_ls_cache = {}              # dir -> (mtime_ns, [names])
_sid_proj = {}              # session_id -> (ts, proj_dir) 30s TTL 绑定缓存
_last_data_ts = 0.0         # 最近一次推到增量的时刻（退避档位依据）
BACKOFF_SLOW_S = 5.0        # 空闲档间隔
BACKOFF_AFTER_S = 30.0      # 无数据多久进空闲档


def _ls(dir_path):
    """目录清单（mtime 门控缓存）。目录不存在返回 None。"""
    try:
        st = os.stat(dir_path)
        mtime = st.st_mtime_ns
    except OSError:
        return None
    c = _ls_cache.get(dir_path)
    if c and c[0] == mtime:
        return c[1]
    try:
        names = [e.name for e in os.scandir(dir_path)]
    except OSError:
        return None
    _ls_cache[dir_path] = (mtime, names)
    return names


def _proj_for_session(home, sid):
    """session_id → 所在 projects/<proj> 目录（30s TTL；会话 jsonl 落位后
    基本不再变，原每秒每会话全量 glob 是枚举大头）。"""
    now = time.time()
    c = _sid_proj.get(sid)
    if c and now - c[0] < 30.0:
        return c[1]
    proj_dir = None
    proot = _ls(os.path.join(home, ".claude", "projects"))
    if proot:
        for d in proot:
            cand = os.path.join(home, ".claude", "projects", d, sid + ".jsonl")
            if os.path.isfile(cand):
                proj_dir = os.path.dirname(cand)
                break
    _sid_proj[sid] = (now, proj_dir)
    return proj_dir


def _push_file(s, fp, aid, force=False, reconcile=False):
    """读 fp 自 offset 起的增量整行：喂 v4 子投影 + emit 兼容事件。

    a68（用户实测「子代理过程缺失/结论永不到/永远不结束」根因）：增量
    截尾（MAX_DELTA_BYTES）只作用于**旧前端镜像事件的载荷**——子 feed
    喂入必须全量行。子代理转写里 api-request-blob 单行可达数百 KB，一次
    增量常态超 256KB，旧截尾直接把增量起点跳到文件尾=整段业务行（工具/
    收尾 handback）永久丢失，feed 冻结在中途（state.final 永空、前端
    秒表永跑）。V3 无此问题（回放走 /subagent_replay 全量文件）。

    force=True：绕过新鲜窗（订阅时刻的对账自愈用——冻结 feed 重开 pane
    时全量重推一轮，uuid 去重保证幂等）。
    reconcile=True（a119P，用户实测「打开子代理必卡」）：订阅时刻对账的
    新语义——绕过新鲜窗但**保留 offset 只补间隙**。force 归零=每开一次
    pane 全量重读整份 MB 级转写+逐行解析，是打开卡顿主源；追平时
    （offset==size）零成本跳过，有间隙才读且只读间隙。全量完整性由同
    请求内 v4_sub_feed 的 hydration 兜底（hydrate 整读文件，其命中文件
    的 offset 由 mark_offsets 直推到尾）。
    返回本轮推送字节数（0=无增量；watcher 退避档位的依据）。"""
    now = time.time()
    if not force and not reconcile \
            and now - os.path.getmtime(fp) > FRESH_WINDOW_S:
        return 0
    off = _offsets.get(fp, 0)
    sz = os.path.getsize(fp)
    if force:
        # S2 修复（a116）：force 的语义是「全量重推」——旧实现在 sz<=off
        # 时仍早退，而被救的正是 offset 已到文件尾的两类冻结 feed（旧截尾
        # 时代把 off 跳到 sz；转写长时间打开未追加 sz==off）→ 自愈链恒
        # no-op。归零后由 uuid 去重保证幂等（子 feed）/内容指纹保证幂等。
        off = 0
    if sz <= off:
        return 0
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        f.seek(off)
        txt = f.read()
    # 只推整行（尾半行下轮补）
    if txt and not txt.endswith("\n"):
        cut = txt.rfind("\n")
        if cut < 0:
            return 0
        txt = txt[:cut + 1]
        new_off = off + len(txt.encode("utf-8"))
    else:
        new_off = sz if sz == os.path.getsize(fp) else off + len(txt.encode("utf-8"))
    _offsets[fp] = new_off
    if not txt.strip():
        return 0
    # v4 子投影：feed 不在（pane 先开、转写后到）且 v4 客户端在场（主投影
    # 或子订阅意向——a74：子 pane 先于主窗订阅/主 store 断连窗口期原闸会
    # 误杀）→ 按需全量 hydrate（a65：转写首行出现即建出有内容的 feed，
    # 此后增量续喂；hydrate 已消费全文件，本轮增量跳过防重复，uuid 去重
    # 再兜底）。V3 模式（无主 feed 无意向）行为与旧版完全一致
    try:
        from . import v4hub
        # a83：键统一 harness sid（s.sid）——session_id 被 CLI 首 init 换代
        # 后 watcher 会喂进另一把键下的新 feed，pane 绑的旧 feed 成孤儿
        if not v4hub.v4_sub_has(s.sid, aid) \
                and (v4hub.v4_main_has(s.sid)
                     or v4hub.v4_sub_wanted_has(s.sid, aid)):
            if v4hub.v4_sub_hydrate(s.sid, aid, [fp]):
                return sz - off
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
            v4hub.v4_sub_ingest(s.sid, aid, obj)
    except Exception:
        pass
    # 兼容旧前端（批F 退役）：载荷防爆照旧截尾
    s.emit({"kind": "event", "data": {
        "type": "subagent_delta",
        "agent": aid,
        "offset": new_off,
        "text": txt[:MAX_DELTA_BYTES],
    }})
    return new_off - off


def mark_offsets(paths):
    """a119P（用户实测「打开子代理卡顿」）：hydration 已整读的文件，offset
    直推到文件尾——订阅时刻对账（push_paths_once）与 watcher 后续增量
    都从尾部续，不再全量重读。只标**产出过行的命中文件**（v4_sub_feed 依
    序试候选、首个产出即停，未读候选不标——留给对账首读，内容指纹/uuid
    去重保证幂等）。"""
    for p in paths or []:
        if not p or not os.path.isfile(p):
            continue
        try:
            _offsets[p] = os.path.getsize(p)
        except OSError:
            pass


def push_paths_once(s, aid, paths):
    """a68：订阅时刻的强制对账——对候选路径重推一轮（绕过新鲜窗）。
    冻结 feed（截尾时代丢的尾段/中途打开-pane 缓存的残缺投影）在用户
    重开 pane 时由此自愈；uuid 去重保证与既有行幂等。
    a119P（用户实测「打开子代理必卡」）：force（offset 归零全量重读）
    改 reconcile（保留 offset 只补间隙）——审计类子代理转写 MB 级，每开
    一次 pane 全量重读+逐行解析是打开卡顿主源。追平零成本跳过；冷文件
    也能补齐缺口。全量兜底由同请求内 v4_sub_feed 的 hydration 承担
    （hydrate 整读文件，命中文件的 offset 由 mark_offsets 推到尾）；force
    归零救的「offset 被旧截尾时代跳到尾部」残留在现进程内不可复现
    （a68 后 offset 只在真读完才前进）。"""
    for p in paths or []:
        if not p or not os.path.isfile(p):
            continue
        try:
            _push_file(s, p, aid, reconcile=True)
        except Exception:
            pass


def _watch_loop():
    global _last_data_ts
    last_clean = 0.0
    while True:
        # 空闲退避：近 30s 推到过增量→1s 快档（实时感不变），否则 5s 慢档
        interval = WATCH_INTERVAL_S \
            if time.time() - _last_data_ts < BACKOFF_AFTER_S else BACKOFF_SLOW_S
        time.sleep(interval)
        try:
            now = time.time()
            # 周期清 _offsets/_ls_cache/_sid_proj（终态文件离开新鲜窗后回收内存）
            if now - last_clean > 300:
                last_clean = now
                for p in list(_offsets.keys()):
                    try:
                        if now - os.path.getmtime(p) > FRESH_WINDOW_S:
                            _offsets.pop(p, None)
                    except OSError:
                        _offsets.pop(p, None)
                if len(_ls_cache) > 512:
                    _ls_cache.clear()
                for k in [k for k, v in _sid_proj.items()
                          if now - v[0] > 300]:
                    _sid_proj.pop(k, None)
            home = os.path.expanduser("~")
            # 只扫有活会话的项目目录（会话→proj 绑定 30s TTL 缓存，原每秒
            # 每会话全量 glob projects/*/<sid>.jsonl 是枚举大头）
            proj_dirs = set()
            for s in _iter_sessions():
                sid = getattr(s, "session_id", None)
                if not sid:
                    continue
                pd = _proj_for_session(home, sid)
                if pd:
                    proj_dirs.add(pd)
            for proj in proj_dirs:
                # proj/*/subagents：proj 目录清单走 _ls 缓存（mtime 门控），
                # subagents 子目录存在性用 csid 目录缓存判定（新建子代理
                # 转写目录必改 csid mtime，不会漏）
                proot = _ls(proj)
                if not proot:
                    continue
                for csid in proot:
                    cdir = os.path.join(proj, csid)
                    sub_dir = os.path.join(cdir, "subagents")
                    names = _ls(cdir)
                    if names is None or "subagents" not in names:
                        continue
                    s = _session_for(sub_dir, csid)
                    if s is None:
                        continue
                    files = _ls(sub_dir) or []
                    for fn in files:
                        if not (fn.startswith("agent-") and fn.endswith(".jsonl")):
                            continue
                        try:
                            n = _push_file(s, os.path.join(sub_dir, fn),
                                           fn[len("agent-"):-len(".jsonl")])
                            if n:
                                _last_data_ts = time.time()
                        except Exception:
                            continue
            # 源②（新版 CLI Agent 工具 tasks/<id>.output）——v4 补的覆盖面
            la = os.environ.get("LOCALAPPDATA")
            if la:
                for s in _iter_sessions():
                    sid = getattr(s, "session_id", None)
                    if not sid:
                        continue
                    pd = _proj_for_session(home, sid)
                    if not pd:
                        continue
                    proj_name = os.path.basename(pd)
                    for csid in [x for x in (
                            list(getattr(s, "lineage", None) or []) + [sid]) if x]:
                        tdir = os.path.join(la, "Temp", "claude", proj_name,
                                            csid, "tasks")
                        for fn in (_ls(tdir) or []):
                            if not fn.endswith(".output"):
                                continue
                            try:
                                n = _push_file(s, os.path.join(tdir, fn),
                                               fn[:-len(".output")])
                                if n:
                                    _last_data_ts = time.time()
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
