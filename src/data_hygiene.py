# -*- coding: utf-8 -*-
"""harness_uploads 附件目录自动清理 + 数据目录存储感知（v3.5.92）。

用户拍板的清理策略：
- 超期删除：附件保留半年（180 天，按 mtime）；
- 容量上限 1GB：超出删最古老的，删到剩余 ≤ 80%（819MB）为止；
- 触发时机：启动即清 + 每 24h 一次 + 上传成功后节流触发（10 分钟一次）。

存储感知（设置→数据目录展示）：
- 用户数据空间（可迁移）= DATA_DIR（日志/笔记/缓存，随迁移走）；
- 工具数据空间 = STATE_DIR（数据目录：附件/
  各子进程状态，不随迁移改址）。
"""
import os
import threading
import time

UPLOADS_MAX_AGE_S = 180 * 24 * 3600      # 半年
UPLOADS_MAX_BYTES = 1 << 30              # 1GB
UPLOADS_TARGET_PCT = 0.8                 # 超限删到剩余 80% 为止


def uploads_dir():
    # v3.5.94（轻审R1-1）：复用 harness/consts._UPLOAD_DIR 单一源——此前两处
    # 独立拼 STATE_DIR/harness_uploads，任一侧改址即清理与上传目标分家
    from src.harness.consts import _UPLOAD_DIR
    return _UPLOAD_DIR


def _scan():
    items = []
    try:
        for fn in os.listdir(uploads_dir()):
            p = os.path.join(uploads_dir(), fn)
            try:
                if not os.path.isfile(p):
                    continue   # 轻审R1-2：只收文件（旧 or st_size 写法在 POSIX 下会把目录计入）
                st = os.stat(p)
                items.append((st.st_mtime, st.st_size, p))
            except OSError:
                pass
    except OSError:
        pass
    return items


def cleanup_uploads():
    """执行一轮清理。返回 (删除文件数, 释放字节)。"""
    items = _scan()
    now = time.time()
    removed = 0
    freed = 0
    keep = []
    for mt, sz, p in items:
        if now - mt > UPLOADS_MAX_AGE_S:
            try:
                os.remove(p)
                removed += 1
                freed += sz
            except OSError:
                keep.append((mt, sz, p))
        else:
            keep.append((mt, sz, p))
    total = sum(sz for _, sz, _ in keep)
    if total > UPLOADS_MAX_BYTES:
        keep.sort(key=lambda x: x[0])    # 最老在前
        target = int(UPLOADS_MAX_BYTES * UPLOADS_TARGET_PCT)
        for mt, sz, p in keep:
            if total <= target:
                break
            try:
                os.remove(p)
                removed += 1
                freed += sz
                total -= sz
            except OSError:
                pass
    return removed, freed


def _dir_size(root):
    """目录总字节（深度遍历，坏项跳过；防呆：root 不存在返回 0）。"""
    total = 0
    real = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        # 不越界（junction/symlink 指回自身或祖先会造成死循环）
        dirnames[:] = [d for d in dirnames
                       if os.path.realpath(os.path.join(dirpath, d))
                       .startswith(real + os.sep)]
        for fn in filenames:
            try:
                total += os.stat(os.path.join(dirpath, fn)).st_size
            except OSError:
                pass
    return total


_usage_cache = {"ts": 0.0, "data": None}


def usage_stats(force=False):
    """两栏占用 + 附件目录明细 + 可清理目标清单（设置页存储感知数据源）。
    v3.5.94（轻审R1-5）：60s TTL 缓存——DATA_DIR 含 G 级日志，反复进出设置页
    不该反复全量深扫；manual_clean 后 force 重扫。"""
    import time as _t
    now = _t.time()
    if not force and _usage_cache["data"] and now - _usage_cache["ts"] < 60:
        return _usage_cache["data"]
    from src import app_state as st
    up = uploads_dir()
    log_dir = getattr(st, "LOG_DIR", st.DEFAULT_LOG_DIR)
    idx_dirs = [os.path.join(st.DATA_DIR, "logs", "idx"),
                os.path.join(getattr(st, "BASE_DIR", st.DATA_DIR), "idx")]
    ask = os.path.join(st.STATE_DIR, "harness_ask")
    # 2026-11-23（用户令）：原「cache」目标（数据目录 webview_cache\EBWebView，
    # 旧 WebView2 窗口体的缓存）已整体移除——Electron 壳不读不写它，旧目录已清除。
    targets = {
        "uploads": {"path": up, "bytes": _dir_size(up), "name": "会话附件"},
        "logs": {"path": log_dir, "bytes": _dir_size(os.path.join(log_dir))
                 - sum(_dir_size(os.path.join(log_dir, d)) for d in ("idx",) if os.path.isdir(os.path.join(log_dir, d))),
                 "name": "串口日志"},
        "idx": {"path": idx_dirs[0], "bytes": sum(_dir_size(d) for d in idx_dirs),
                "name": "日志索引（可重建，含 legacy 目录）"},
        "ask": {"path": ask, "bytes": _dir_size(ask), "name": "提问状态"},
        # a333：代码跳转索引（ctags tags + 白名单 + ELF 符号表——可重建的
        # 衍生数据，手动建/删走文件树右键，存储感知可见可清）
        "nav": {"path": os.path.join(st.DATA_DIR, "nav"),
                "bytes": _dir_size(os.path.join(st.DATA_DIR, "nav")),
                "name": "代码跳转索引（各工程符号库）"},
    }
    data = {
        "user": {"path": st.DATA_DIR, "bytes": _dir_size(st.DATA_DIR)},
        # 2026-11-23 退役改造：原「工具数据空间(固定 HOME_DIR)」口径已合——
        # 全部用户数据(含附件/子进程状态)都在数据目录(user 行)；固定不迁的
        # 只剩锚点(endpoint/指针/崩溃取证，KB 级；config 已搬进数据目录)
        "anchor": {"path": st.HOME_DIR, "bytes": _dir_size(st.HOME_DIR)},
        "uploads": {"path": up, "bytes": targets["uploads"]["bytes"],
                    "max_bytes": UPLOADS_MAX_BYTES,
                    "max_age_days": UPLOADS_MAX_AGE_S // (24 * 3600)},
        "targets": targets,
    }
    _usage_cache["ts"] = now
    _usage_cache["data"] = data
    return data


# ---- 手动清理（v3.5.93：用户拍板「手动清理+可选范围」）--------------------
# 目标只含**衍生数据**（附件/日志/索引/缓存/提问状态）——笔记、命令库、
# 配置等用户数据永远不出现在这里

_CLEANABLE = ("uploads", "logs", "idx", "ask", "nav")


def _files_in(root, suffix=None):
    """root 下文件清单 [(mtime, size, path)]。与 _dir_size 同款 reparse point
    剪枝（轻审R2-1 严重）：Windows 下 os.walk 默认下钻 junction（mklink /J
    无需管理员），不剪枝则 manual_clean 会删到目标目录之外——uploads 里被
    塞一个 junction 即可波及任意目录。"""
    out = []
    real = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames
                       if os.path.realpath(os.path.join(dirpath, d))
                       .startswith(real + os.sep)]
        for fn in filenames:
            if suffix and not fn.endswith(suffix):
                continue
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p, follow_symlinks=False)
                out.append((st.st_mtime, st.st_size, p))
            except OSError:
                pass
    return out


def _try_rm(p):
    try:
        os.remove(p)
        return True
    except OSError:
        return False


def manual_clean(target, mode):
    """手动清理入口。target ∈ uploads|logs|idx|ask|nav；mode ∈ policy|all。
    返回 (removed, freed)。policy=按各自保留策略；all=清空该类。
    （2026-11-23 用户令：原 cache 目标——旧 WebView2 缓存——已随旧窗口体退役，
    连同 _CACHE_SUBS 清单一并移除；Electron 壳的缓存在它自己的 userData 里。）"""
    from src import app_state as st
    removed = 0
    freed = 0
    if target not in _CLEANABLE or mode not in ("policy", "all"):
        return 0, 0
    _usage_cache["ts"] = 0.0   # 清理后占用缓存失效（下次 usage 强制重扫）

    if target == "uploads":
        if mode == "policy":
            removed, freed = cleanup_uploads()
        else:
            for _mt, sz, p in _files_in(uploads_dir()):
                if _try_rm(p):
                    removed += 1
                    freed += sz

    elif target == "logs":
        log_dir = getattr(st, "LOG_DIR", st.DEFAULT_LOG_DIR)
        cutoff = time.time() - 7 * 86400
        for mt, sz, p in _files_in(log_dir, suffix=".log"):
            if mode == "policy" and os.path.basename(p).startswith("serial_") \
                    and mt >= cutoff:
                continue   # policy：保留 7 天内的串口日志
            if mode == "policy" and not os.path.basename(p).startswith("serial_"):
                continue   # policy：只动 serial_* 日志，别的文件不碰
            if _try_rm(p):
                removed += 1
                freed += sz

    elif target == "idx":
        # 轻审R2-2 严重：cleanup_stale_idx(3) 内部只清 legacy BASE_DIR/idx，
        # LogIndex 实际写 DATA_DIR/logs/idx——policy 此前对现行目录空转。
        # 改为自实现按 atime/mtime 双目录清理（口径与前端声明一致）
        dirs = [os.path.join(st.DATA_DIR, "logs", "idx"),
                os.path.join(getattr(st, "BASE_DIR", st.DATA_DIR), "idx")]
        cutoff = time.time() - 3 * 86400
        for d in dirs:
            for _mt, sz, p in _files_in(d, suffix=".idx"):
                if mode == "policy":
                    try:
                        s2 = os.stat(p)
                        if max(s2.st_atime, s2.st_mtime) >= cutoff:
                            continue   # policy：3 天内用过的保留
                    except OSError:
                        continue
                if _try_rm(p):
                    removed += 1
                    freed += sz

    elif target == "ask":
        ask = os.path.join(st.STATE_DIR, "harness_ask")
        items = _files_in(ask)
        if mode == "policy":
            items.sort(key=lambda x: x[0], reverse=True)   # 新在前
            items = items[500:]                            # 保留最近 500 个
        for _mt, sz, p in items:
            if _try_rm(p):
                removed += 1
                freed += sz

    elif target == "nav":
        # a333：代码跳转索引——全部可重建（重跑右键建索引即恢复）。
        # policy 与 all 等价（整库删除，没有"部分保留"语义）；清后让查询
        # 缓存失效，跳转自动回到 no-index 态
        import shutil as _sh2
        from src import nav_index as _ni
        root = os.path.join(st.DATA_DIR, "nav")
        if os.path.isdir(root):
            before = _dir_size(root)
            for name in os.listdir(root):
                _sh2.rmtree(os.path.join(root, name), ignore_errors=True)
            freed += max(0, before - (_dir_size(root) if os.path.exists(root) else 0))
            removed += 1
        try:
            _ni._invalidate_cache()
        except Exception:
            pass

    return removed, freed


_last_ts = [0.0]


def cleanup_throttled():
    """上传路由成功后调（10 分钟节流，异步不阻塞响应）。"""
    now = time.time()
    if now - _last_ts[0] < 600:
        return
    _last_ts[0] = now

    def _run():
        try:
            cleanup_uploads()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def start():
    """启动即清一轮，此后每 24h 一轮（守护线程，不挡启动）。"""

    def _loop():
        while True:
            try:
                cleanup_uploads()
            except Exception:
                pass
            time.sleep(24 * 3600)
    threading.Thread(target=_loop, daemon=True).start()
