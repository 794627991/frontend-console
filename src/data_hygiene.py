# -*- coding: utf-8 -*-
"""harness_uploads 附件目录自动清理 + 数据目录存储感知（v3.5.92）。

用户拍板的清理策略：
- 超期删除：附件保留半年（180 天，按 mtime）；
- 容量上限 1GB：超出删最古老的，删到剩余 ≤ 80%（819MB）为止；
- 触发时机：启动即清 + 每 24h 一次 + 上传成功后节流触发（10 分钟一次）。

存储感知（设置→数据目录展示）：
- 用户数据空间（可迁移）= DATA_DIR（日志/笔记/缓存，随迁移走）；
- 工具数据空间（固定）= HOME_DIR（~/.serialconsole_pro：config/附件/
  各子进程状态，不随迁移改址）。
"""
import os
import threading
import time

UPLOADS_MAX_AGE_S = 180 * 24 * 3600      # 半年
UPLOADS_MAX_BYTES = 1 << 30              # 1GB
UPLOADS_TARGET_PCT = 0.8                 # 超限删到剩余 80% 为止


def uploads_dir():
    from src.app_state import HOME_DIR
    return os.path.join(HOME_DIR, "harness_uploads")


def _scan():
    items = []
    try:
        for fn in os.listdir(uploads_dir()):
            p = os.path.join(uploads_dir(), fn)
            try:
                st = os.stat(p)
                if os.path.isfile(p) or st.st_size:
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


def usage_stats():
    """两栏占用 + 附件目录明细（设置页存储感知数据源）。"""
    from src.app_state import DATA_DIR, HOME_DIR
    up = uploads_dir()
    return {
        "user": {"path": DATA_DIR, "bytes": _dir_size(DATA_DIR)},
        "tool": {"path": HOME_DIR, "bytes": _dir_size(HOME_DIR)},
        "uploads": {"path": up, "bytes": _dir_size(up),
                    "max_bytes": UPLOADS_MAX_BYTES,
                    "max_age_days": UPLOADS_MAX_AGE_S // (24 * 3600)},
    }


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
