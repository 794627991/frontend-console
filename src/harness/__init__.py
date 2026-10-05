# -*- coding: utf-8 -*-
"""harness 包 —— v3.0 自 src/claude_harness.py 重构拆分。

旧引用入口 src/claude_harness.py 保留为兼容 shim,新代码建议直接
from src.harness.xxx import ...。各模块职责见各自 docstring。
"""
from .consts import (_EVENTS_MAX, _IDLE_KILL_S, _META_FILE, _PROMPTS_KEY, _PROMPTS_LEGACY_KEY, _QUEUE_MAX, _SKILL_ZH_FILE, _SRC_DIR, _UPLOAD_DIR, _UPLOAD_MAX, _sessions, _sessions_lock, log)
from .meta import (_meta, _meta_load, _meta_loaded, _meta_lock, _meta_save, _meta_tombstones, log)
from .models import (_model_label, _models_cache, available_models, log)
from .prompts import (_collect_system_prompt, _prompt_matches_project, _prompts_load, _prompts_save, log)
from .bridges import (TOKEN_RULES, _bridge_fp, ask_bridge_text, confirm_bridge_text, log, vision_bridge_text)
from .askmcp import (_ask_mcp_cfg_path, log)
from .audit import (_AUDIT_EDIT_TOOLS, _AUDIT_LOG_MAX, _AUDIT_MSG_PREFIX, _AUDIT_ROLES, _audit_dispatch_role, _audit_hook_settings_path, _audit_iso_now, _audit_lines, _audit_log_append, _audit_log_read, _audit_nlines, log)
from .session import (HarnessSession, _CTX_WINDOW_1M, _CTX_WINDOW_DEFAULT, _session_ctx_used, _session_ctx_window, log)
from .transcript import (_SKIP_RE, _SUBAGENT_BLK_FULL, _extract_att, _inject_subagent_blocks, _map_subagent_rows, _strip_att, _subagent_rows_for, _subagent_rows_from_jsonl, _subagent_transcript_candidates, _tool_summary, log, re_title, transcript_for)
