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
    global _meta_loaded
    if _meta_loaded:
        return
    # v3.2.2（实测实锤）：装载必须**原地更新** _meta——拆分后 routes/lifecycle/
    # session 都 `from .meta import _meta` 拿的是 import 时刻的 dict 对象引用，
    # 旧写法 `_meta = {...}` 是模块级重绑定，先 import 后 load 的启动序会让
    # 全部别名停在初始空 dict 上（本机实测：某次重启 /api/harness/sessions
    # 恒返空表而盘面 3 条俱在）。clear+update 所有别名同享一份真值
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            _meta.clear()
            _meta.update({k: v for k, v in d.items() if isinstance(v, dict) and v.get("sid")})
    except FileNotFoundError:
        pass                            # 首次启动无表：保持空 dict（原地，勿重绑定）
    except Exception:
        # 坏文件（写入撕裂/被截断）不能静默当空表——否则下一次 _meta_save
        # 会用空表全量覆盖，整张会话列表蒸发（2026-09 实测丢过一批）。
        # 先留档 .bad 供人工找回，再当空表起步。
        try:
            os.replace(_META_FILE, _META_FILE + ".bad")
        except OSError:
            pass
        _meta.clear()
    _meta_loaded = True

# ---- from claude_harness.py:728 (_meta_save) ----


def _meta_save():
    """原子写（tmp + replace，同 claude_default 模式）。锁覆盖整个落盘流程。

    落盘前重读盘面做并集合并：本进程只在首次用表时读一次文件，若期间另
    有进程（多开/重启窗口期）写入过新条目，拿内存快照直接覆盖会把它们抹
    掉。口径：盘面有而内存没有的条目补进来；两边都有以内存为准（本进程
    刚操作过，是最新的）。墓碑排除本进程已删条目，防止合并把刚删的复活。

    v3.4.54：tmp 写盘从锁外移入——固定 tmp 名在锁外时，双线程并发保存互
    踩 tmp（Windows 下另一线程持句柄会使本线程 replace 抛 PermissionError
    被静默吞掉=丢保存无感知）。tmp 名带 pid/tid 唯一化（跨进程多开也不
    撞），replace 失败重试一次，仍失败 log.warning，绝不静默。
    """
    import time
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
            tmp = "%s.tmp.%d.%d" % (_META_FILE, os.getpid(), threading.get_ident())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            try:
                os.replace(tmp, _META_FILE)
            except PermissionError:
                time.sleep(0.08)     # 目标被读句柄/杀软短暂持有：重试一次
                os.replace(tmp, _META_FILE)
        except Exception as e:
            log.warning("meta 落盘失败（该次保存丢失）：%s", e)
