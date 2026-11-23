# -*- coding: utf-8 -*-
"""harness.prompts —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import logging
log = logging.getLogger(__name__)
from .. import app_state as _st
from .consts import _PROMPTS_KEY


# ---- from claude_harness.py:624 (_prompts_load) ----


def _prompts_load():
    """读 config.json 的 harness_prompts 列表。坏数据防御：过滤缺 id/text
    的条目，字段兜默认值。失败返回 []。"""
    try:
        with open(_st.CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        raw = d.get(_PROMPTS_KEY)
        if not isinstance(raw, list):
            return []
        out = []
        for it in raw:
            if not isinstance(it, dict) or not it.get("id") or not it.get("text"):
                continue
            out.append({
                "id": str(it["id"]),
                "scope": it.get("scope") if it.get("scope") in ("global", "project") else "global",
                "project": str(it.get("project") or "").strip(),
                "note": str(it.get("note") or "").strip(),
                "text": str(it["text"]).strip(),
                "enabled": bool(it.get("enabled", True)),
            })
        return out
    except Exception:
        return []

# ---- from claude_harness.py:650 (_prompts_save) ----


def _prompts_save(items):
    """原子写 config.json 的 harness_prompts。
    v3.4.54 起走 app_state.cfg_commit（统一锁+原子事务）。"""
    def _mut(d):
        d[_PROMPTS_KEY] = items
    return _st.cfg_commit(_mut)

# ---- from claude_harness.py:670 (_prompt_matches_project) ----


def _prompt_matches_project(item, cwd):
    """项目作用域匹配：cwd 末段目录名（normpath 后）== item.project。
    project 为空视作不匹配（防误全局）。大小写不敏感（Windows）。"""
    if item.get("scope") != "project" or not item.get("project") or not cwd:
        return False
    try:
        tail = os.path.basename(os.path.normpath(cwd)) or cwd
        return tail.lower() == str(item["project"]).strip().lower()
    except Exception:
        return False

# ---- from claude_harness.py:682 (_collect_system_prompt) ----


def _collect_system_prompt(cwd):
    """按 cwd 收集要注入的提示词（start() 用）：
    启用的 global 条目 + cwd 匹配的启用 project 条目，note 做「」小标题。
    返回拼接后的单串（空串=不注入）。"""
    parts = []
    for it in _prompts_load():
        if not it.get("enabled", True):
            continue
        if it.get("scope") == "project" and not _prompt_matches_project(it, cwd):
            continue
        note = it.get("note") or ""
        parts.append(("【%s】" % note if note else "") + it["text"].strip())
    return "\n\n".join(parts)
