# -*- coding: utf-8 -*-
"""harness.meta —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import threading
import logging
log = logging.getLogger(__name__)
from .consts import _META_FILE


# ---- from claude_harness.py:697 (_meta) ----

# ---------------------------------------------------------------------------
# 会话元数据持久化（重启不丢会话列表——"像微信一样"的根基）
# ---------------------------------------------------------------------------
_meta = {}                  # sid -> meta dict

# ---- from claude_harness.py:702 (_meta_lock) ----
_meta_lock = threading.Lock()

# ---- from claude_harness.py:703 (_meta_loaded) ----
_meta_loaded = False

# ---- from claude_harness.py:704 (_meta_tombstones) ----
_meta_tombstones = set()    # 本进程已删 sid：_meta_save 合并时防从盘面复活

# ---- from claude_harness.py:705 (_meta_load) ----


def _meta_load():
    global _meta, _meta_loaded
    if _meta_loaded:
        return
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _meta = {k: v for k, v in d.items() if isinstance(v, dict) and v.get("sid")}
    except FileNotFoundError:
        _meta = {}                     # 首次启动无表：正常路径
    except Exception:
        # 坏文件（写入撕裂/被截断）不能静默当空表——否则下一次 _meta_save
        # 会用空表全量覆盖，整张会话列表蒸发（2026-09 实测丢过一批）。
        # 先留档 .bad 供人工找回，再当空表起步。
        try:
            os.replace(_META_FILE, _META_FILE + ".bad")
        except OSError:
            pass
        _meta = {}
    _meta_loaded = True

# ---- from claude_harness.py:728 (_meta_save) ----


def _meta_save():
    """原子写（tmp + replace，同 claude_default 模式）。锁内快照防并发撕裂。

    落盘前重读盘面做并集合并：本进程只在首次用表时读一次文件，若期间另
    有进程（多开/重启窗口期）写入过新条目，拿内存快照直接覆盖会把它们抹
    掉。口径：盘面有而内存没有的条目补进来；两边都有以内存为准（本进程
    刚操作过，是最新的）。墓碑排除本进程已删条目，防止合并把刚删的复活。
    """
    with _meta_lock:
        _meta_load()
        try:
            with open(_META_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        if isinstance(d, dict):
            for k, v in d.items():
                if (k not in _meta and k not in _meta_tombstones
                        and isinstance(v, dict) and v.get("sid")):
                    _meta[k] = v
        data = dict(_meta)
    try:
        os.makedirs(os.path.dirname(_META_FILE), exist_ok=True)
        tmp = _META_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _META_FILE)
    except Exception:
        pass
