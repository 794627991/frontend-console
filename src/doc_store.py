# -*- coding: utf-8 -*-
"""文档服务状态：等待前端回传、索引缓存、视图状态（设计文档 6.4 的 6.4.3–6.4.5）。

三条约束落在本文件里：

1. **等待前端回传**（6.4.3）。后端不能直接调页面，只能经 SSE 广播一条
   `ui_action`，再用 threading.Event 等前端 `POST /api/doc/report_*` 回来。
   超时和成功都要把 `_pending` 里的条目清掉——不清理就是内存泄漏，而且
   前端迟到回传会写进一个已经不存在的等待者。

2. **索引缓存**（6.4.4）。前端解析完回传 {outline, units, revision}，按
   规范化路径缓存在内存。最多 16 个文档，按 revision（大小:修改时间）失效。

3. **视图状态**（6.4.5）。全局一份——应用是单窗口的。

【规模上限】回传的 units 文本总量超过 8MiB 时只收大纲，不收分页文本；
之后对这份文档调 read_document / search_document 会返回「文档过大」。
"""

import os
import threading
import time
import uuid

from src.doc_anchor import kind_of_path, EXT_KIND

# ---------- 限制 ----------
WAIT_OPEN = 30.0        # 打开文档：等前端回传大纲
WAIT_SHOW = 15.0        # 定位并高亮
MAX_INDEX_DOCS = 16     # 索引缓存的文档数
MAX_UNITS_BYTES = 8 * 1024 * 1024   # 分页文本总量上限
MAX_FILE_BYTES = 100 * 1024 * 1024  # 单个文件上限（6.4.2 第 5 步）
MAX_OUTLINE_ITEMS = 200
MAX_AT_LEN = 300
MAX_SELECTION_LEN = 2000

_PENDING = {}           # req_id -> {"ev": Event, "res": None}
_PENDING_LOCK = threading.Lock()

_INDEX = {}             # 规范化路径 -> {"revision", "info", "units", "ts", "text_ok"}
_INDEX_LOCK = threading.Lock()

_VIEW = {"path": "", "kind": "", "at": "", "selection": {"text": ""}}
_VIEW_LOCK = threading.Lock()


# ================================================================
# 等待前端回传（6.4.3）
# ================================================================

class DocError(Exception):
    """带错误码的失败（6.4.2 的错误码表）。"""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def new_req_id():
    return uuid.uuid4().hex


def wait_for(action, payload, timeout):
    """推一条 ui_action 给前端，等它回传。

    返回前端回传的 dict；超时返回 {"ok": False, "code": "timeout", ...}。
    **无论成功还是超时都清掉 _pending**——泄漏的条目会让下一次同名请求
    收不到自己的结果（前端回传的 req_id 对不上已超时的条目时就忽略）。
    """
    from src.app_state import _broadcast_to_ai   # 延迟导入：避免循环依赖

    req_id = new_req_id()
    ev = threading.Event()
    slot = {"ev": ev, "res": None}
    with _PENDING_LOCK:
        _PENDING[req_id] = slot
    try:
        # **先铺 payload 再写固定字段**：payload 里带 kind（文档类型 docx/pdf…），
        # 反过来 update 会把信封的 kind="ui_action" 覆盖成 "docx" —— 前端
        # sense.js 按 kind 分发，帧从此被静默丢弃（实测：广播到了浏览器，
        # 但 AI 侧等满 15 秒超时）。信封字段必须最后写，且这几项不接受覆盖。
        d = {}
        d.update(payload or {})
        d["kind"] = "ui_action"
        d["action"] = action
        d["req_id"] = req_id
        _broadcast_to_ai(d)
        if not ev.wait(timeout):
            return {"ok": False, "code": "timeout", "req_id": req_id,
                    "err": "文档面板没有响应。请确认 AI 会话页处于打开状态"}
        res = slot.get("res") or {}
        return res
    finally:
        with _PENDING_LOCK:
            _PENDING.pop(req_id, None)


def deliver(req_id, result):
    """前端回传时调。req_id 对不上（已超时被清理）返回 False。"""
    with _PENDING_LOCK:
        slot = _PENDING.get(req_id)
    if not slot:
        return False
    slot["res"] = result
    slot["ev"].set()
    return True


def pending_count():
    with _PENDING_LOCK:
        return len(_PENDING)


# ================================================================
# 路径校验（6.4.2，五步，任一步失败立即抛出）
# ================================================================

def validate_path(path, base_dir=None):
    """校验并返回规范化后的绝对路径。失败抛 DocError。"""
    from src.app_state import reject_win_devpath

    p = (path or "").strip()
    if not p:
        raise DocError("invalid_path", "路径为空")
    if reject_win_devpath(p):       # ① Windows 保留设备名（CON 等会永久阻塞）
        raise DocError("invalid_path", "路径包含 Windows 保留设备名")
    # ② 相对路径按会话的项目目录补全（MCP 进程的当前目录就是会话目录，
    #    但工具参数里的相对路径要显式补——进程 cwd 不可靠）
    if not os.path.isabs(p):
        base = base_dir or os.getcwd()
        p = os.path.join(base, p)
    p = os.path.normpath(p)
    # ③ 绝对 + 是文件
    if not os.path.isabs(p):
        raise DocError("invalid_path", "路径不是绝对路径：%s" % path)
    if not os.path.isfile(p):
        raise DocError("not_found", "文件不存在：%s" % p)
    # ④ 扩展名白名单
    kind = kind_of_path(p)
    if not kind:
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        raise DocError("unsupported_type", "不支持的文档类型：.%s" % ext)
    # ⑤ 体积上限
    try:
        size = os.path.getsize(p)
    except OSError as e:
        raise DocError("not_found", "无法读取文件：%s" % e)
    if size > MAX_FILE_BYTES:
        raise DocError("too_large", "文件超过 100MB 上限")
    return p, kind


def revision_of(path):
    """`大小:修改时间毫秒`（6.1.8）。取不到返回空串。"""
    try:
        st = os.stat(path)
        return "%d:%d" % (st.st_size, int(round(st.st_mtime * 1000)))
    except OSError:
        return ""


# ================================================================
# 索引缓存（6.4.4）
# ================================================================

def _key(path):
    return os.path.normcase(os.path.abspath(path))


def index_store(path, revision, info, units):
    """存前端回传的解析结果。units 超预算时只收大纲。"""
    units = units or []
    # 估一下分页文本的体量（UTF-8 字节）
    total = 0
    for u in units:
        t = u.get("text") or ""
        total += len(t.encode("utf-8", "replace"))
        if total > MAX_UNITS_BYTES:
            break
    text_ok = total <= MAX_UNITS_BYTES
    if len(units) > MAX_OUTLINE_ITEMS * 40:
        units = units[:MAX_OUTLINE_ITEMS * 40]
    entry = {
        "revision": revision or "",
        "info": info or {},
        "units": units if text_ok else [],
        "ts": time.time(),
        "text_ok": text_ok,
    }
    k = _key(path)
    with _INDEX_LOCK:
        _INDEX[k] = entry
        # 超过上限：淘汰最久没被用的（按 ts）
        if len(_INDEX) > MAX_INDEX_DOCS:
            order = sorted(_INDEX.items(), key=lambda kv: kv[1].get("ts", 0))
            for kk, _ in order[:len(_INDEX) - MAX_INDEX_DOCS]:
                _INDEX.pop(kk, None)
    return entry


def index_get(path, revision=None):
    """取缓存。给了 revision 且与缓存不符时视为失效（顺手清掉）。"""
    k = _key(path)
    with _INDEX_LOCK:
        e = _INDEX.get(k)
        if not e:
            return None
        if revision is not None and e.get("revision") != revision:
            _INDEX.pop(k, None)
            return None
        e["ts"] = time.time()
        return dict(e)


def index_drop(path):
    with _INDEX_LOCK:
        _INDEX.pop(_key(path), None)


def index_count():
    with _INDEX_LOCK:
        return len(_INDEX)


# ================================================================
# 视图状态（6.4.5）
# ================================================================

def view_get():
    with _VIEW_LOCK:
        return dict(_VIEW)


def view_set(path, kind, at, selection):
    with _VIEW_LOCK:
        _VIEW["path"] = path or ""
        _VIEW["kind"] = kind or ""
        _VIEW["at"] = (at or "")[:MAX_AT_LEN]
        sel = (selection or {}).get("text") if isinstance(selection, dict) else ""
        _VIEW["selection"] = {"text": (sel or "")[:MAX_SELECTION_LEN]}


def reset_all():
    """测试用：清空三份状态。"""
    with _PENDING_LOCK:
        _PENDING.clear()
    with _INDEX_LOCK:
        _INDEX.clear()
    with _VIEW_LOCK:
        _VIEW.update({"path": "", "kind": "", "at": "", "selection": {"text": ""}})
