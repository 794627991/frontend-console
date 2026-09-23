# -*- coding: utf-8 -*-
"""harness 包 —— v3.0 自 src/claude_harness.py 重构拆分。

旧引用入口 src/claude_harness.py 保留为兼容 shim,新代码建议直接
from src.harness.xxx import ...。各模块职责见各自 docstring。
"""
from .consts import (_EVENTS_MAX, _IDLE_KILL_S, _META_FILE, _PROMPTS_KEY, _PROMPTS_LEGACY_KEY, _QUEUE_MAX, _SKILL_ZH_FILE, _SRC_DIR, _UPLOAD_DIR, _UPLOAD_MAX, _sessions, _sessions_lock, log)
from .meta import (_meta, _meta_load, _meta_loaded, _meta_lock, _meta_save, _meta_tombstones, log)
from .models import (_model_label, _models_cache, available_models, log)
from .prompts import (_collect_system_prompt, _prompt_matches_project, _prompts_load, _prompts_save, log)
from .vision import (VISION_DEFAULT_NAME, VISION_DEFAULT_PROMPT, _MM_PROBE_LOCK, _MM_RE, _VISION_KEY, _VISION_TOOLS, _cleanup_peer_reg, _cleanup_stale_vision_peers, _iso_dur_sec, _mm_probe_key, _mm_probe_model, _mm_probe_png_bytes, _mm_probed_load, _model_is_multimodal, _model_vision_mode, _peer_reg_path, _pid_alive, _vision_default_cfg, _vision_load, _vision_lock, _vision_obj, _vision_save, ensure_vision_session, log)
from .bridges import (TOKEN_RULES, _bridge_fp, ask_bridge_text, confirm_bridge_text, log, vision_bridge_text)
from .askmcp import (_ask_mcp_cfg_path, log)
from .audit import (_AUDIT_EDIT_TOOLS, _AUDIT_LOG_MAX, _AUDIT_MSG_PREFIX, _AUDIT_ROLES, _audit_dispatch_role, _audit_hook_settings_path, _audit_iso_now, _audit_lines, _audit_log_append, _audit_log_read, _audit_nlines, log)
from .session import (HarnessSession, _CTX_WINDOW_1M, _CTX_WINDOW_DEFAULT, _session_ctx_used, _session_ctx_window, log)
from .lifecycle import (_ensure_gc, _gc_loop, _gc_started, _get_or_create, _peer_poll_loop, log, stop_vision_session)
from .transcript import (_SKIP_RE, _SUBAGENT_BLK_FULL, _extract_att, _inject_subagent_blocks, _map_subagent_rows, _strip_att, _subagent_rows_for, _subagent_rows_from_jsonl, _subagent_transcript_candidates, _tool_summary, log, re_title, transcript_for)
from .routes import (_jsonl_path_for, _llm_cool_until, _llm_translate_batch, _recover_scan, _rewind_jsonl, _rewind_jsonl_anchor, _rewind_jsonl_ts, _rewind_write, _skill_zh_load, _skill_zh_save, harness_agent_models, harness_ask_answer, harness_ask_poll, harness_ask_reply, harness_audit_gate, harness_bp, harness_connect, harness_ctx, harness_delete, harness_events, harness_file, harness_files, harness_get_prompt, harness_get_vision, harness_interrupt, harness_kill, harness_mcp_list, harness_mm_probe, harness_models, harness_peer_pair_log, harness_peer_result_check, harness_recover, harness_recoverable, harness_rename, harness_rewind, harness_roles_info, harness_send, harness_sessions, harness_set_model, harness_set_prompt, harness_set_roles, harness_set_vision, harness_skill_zh_translate, harness_skills, harness_start_vision, harness_stop_vision, harness_stream, harness_subagent_replay, harness_subagent_tail, harness_transcript, harness_upload, harness_vision_status, log)
