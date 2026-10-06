# -*- coding: utf-8 -*-
"""harness.models —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import logging
log = logging.getLogger(__name__)


# ---- from claude_harness.py:759 (_models_cache) ----


# ---- 可选模型列表（读 ~/.claude/settings.json env 的 LANZ 映射）----
# 按文件 mtime 失效缓存：配置方案切换（/api/claude/profiles/apply 整份
# 写回 settings.json）后必须能立刻看到新模型映射——旧实现进程生命周期内
# 只读一次，用户实测「切了配置方案模型下拉不刷新，重启工具才生效」。
_models_cache = None

# ---- from claude_harness.py:766 (available_models) ----


def available_models():
    global _models_cache
    path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        mtime = 0
    if _models_cache is not None and _models_cache.get("_mtime") == mtime:
        return _models_cache
    names, default = [], None
    try:
        with open(path, "r", encoding="utf-8") as f:
            env = (json.load(f) or {}).get("env") or {}
        default = env.get("ANTHROPIC_MODEL") or None
        for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                  "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                  "ANTHROPIC_DEFAULT_FABLE_MODEL", "ANTHROPIC_DEFAULT_FLASH_MODEL"):
            v = env.get(k)
            if v and v not in names:
                names.append(v)
    except Exception:
        pass
    if not default and names:
        default = names[0]   # settings 无显式默认 → 取首个映射（与 CLI 回退语义一致）
    _models_cache = {"models": names, "default": default, "_mtime": mtime}
    return _models_cache
