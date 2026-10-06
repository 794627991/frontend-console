# -*- coding: utf-8 -*-
"""Claude harness 界面化会话（微信式多会话版）。

与 claude_conn.py（ConPTY 跑 TUI，xterm 保真）平行的另一条通道：
  claude -p --input-format stream-json --output-format stream-json --verbose
进程常驻，stdin 写 NDJSON user 消息即连续多轮；stdout 逐行 NDJSON 事件
（system/assistant/user/result），后端原样透传给前端 SSE，渲染全在前端。

v2（微信式改造）新增：
- 会话持久化：~/.serialconsole_pro/claude_harness.json 元数据表——
  会话列表跨重启保留；切回会话用 --resume <session_id> 复活上下文。
- 模型选择：connect 时 --model <名>（会话级，改模型=新会话）。
- 图片/文件附件：消息 content 数组带 image base64 块 + 文件路径文本
  （实测：内网网关模型不识图时会收到模型「无法识图」自述——协议透传，
  网关换多模态模型后自动生效）。
- 闲置回收：活进程闲置 15min 自动 kill（元数据保留），切回会话自动复活
  ——铁律1「不用时不得占用任何资源」。会话数不设死上限，靠回收兜底。
- 事件缓冲有上限（_EVENTS_MAX），历史气泡从 ~/.claude 转写重建。

铁律约束：不动 claude_conn/claude_sessions/claude_setup/claude_default；
不落盘工具日志（Claude 自写 ~/.claude/projects 转写）。

v3.0:本文件已重构为兼容 shim——实现全部拆入 src/harness/ 子包,
此处 re-export 全部旧名,既有引用(server.py 等 5 处)零改动。
"""
from src.harness.consts import (  # noqa: F401
    _EVENTS_MAX,
    _IDLE_KILL_S,
    _META_FILE,
    _PROMPTS_KEY,
    _PROMPTS_LEGACY_KEY,
    _QUEUE_MAX,
    _SKILL_ZH_FILE,
    _SRC_DIR,
    _UPLOAD_DIR,
    _UPLOAD_MAX,
    _sessions,
    _sessions_lock,
    log,
)
from src.harness.meta import (  # noqa: F401
    _meta,
    _meta_load,
    _meta_loaded,
    _meta_lock,
    _meta_save,
    _meta_tombstones,
    log,
)
from src.harness.models import (  # noqa: F401
    _models_cache,
    available_models,
    log,
)
from src.harness.prompts import (  # noqa: F401
    _collect_system_prompt,
    _prompt_matches_project,
    _prompts_load,
    _prompts_save,
    log,
)
from src.harness.vision import (  # noqa: F401
    _MM_PROBE_LOCK,
    _MM_RE,
    _VISION_KEY,
    _VISION_TOOLS,
    _cleanup_peer_reg,
    _iso_dur_sec,
    _mm_probe_key,
    _mm_probe_model,
    _mm_probe_png_bytes,
    _mm_probed_load,
    _model_is_multimodal,
    _model_vision_mode,
    _peer_reg_path,
    _pid_alive,
    _vision_default_cfg,
    _vision_load,
    _vision_save,
    log,
)
from src.harness.bridges import (  # noqa: F401
    TOKEN_RULES,
    _bridge_fp,
    ask_bridge_text,
    confirm_bridge_text,
    log,
    vision_bridge_text,
)
from src.harness.askmcp import (_ask_mcp_cfg_path, log)
from src.harness.audit import (  # noqa: F401
    _AUDIT_EDIT_TOOLS,
    _AUDIT_LOG_MAX,
    _AUDIT_MSG_PREFIX,
    _AUDIT_ROLES,
    _audit_dispatch_role,
    _audit_hook_settings_path,
    _audit_iso_now,
    _audit_lines,
    _audit_log_append,
    _audit_log_read,
    _audit_nlines,
    log,
)
from src.harness.session import (  # noqa: F401
    HarnessSession,
    _CTX_WINDOW_1M,
    _CTX_WINDOW_DEFAULT,
    _session_ctx_used,
    _session_ctx_window,
    log,
)
from src.harness.lifecycle import (  # noqa: F401
    _ensure_gc,
    _gc_loop,
    _gc_started,
    _get_or_create,
    _peer_poll_loop,
    log,
)
from src.harness.transcript import (  # noqa: F401
    _SKIP_RE,
    _SUBAGENT_BLK_FULL,
    _extract_att,
    _inject_subagent_blocks,
    _map_subagent_rows,
    _strip_att,
    _subagent_rows_for,
    _subagent_rows_from_jsonl,
    _subagent_transcript_candidates,
    _tool_summary,
    log,
    re_title,
    transcript_for,
)
from src.harness.routes import (  # noqa: F401
    _jsonl_path_for,
    _llm_cool_until,
    _llm_translate_batch,
    _recover_scan,
    _rewind_jsonl,
    _rewind_jsonl_anchor,
    _rewind_jsonl_ts,
    _rewind_write,
    _skill_zh_load,
    _skill_zh_save,
    harness_agent_models,
    harness_ask_answer,
    harness_ask_poll,
    harness_ask_reply,
    harness_audit_gate,
    harness_bp,
    harness_connect,
    harness_ctx,
    harness_delete,
    harness_events,
    harness_file,
    harness_files,
    harness_get_prompt,
    harness_get_vision,
    harness_interrupt,
    harness_kill,
    harness_mcp_list,
    harness_mm_probe,
    harness_models,
    harness_peer_pair_log,
    harness_peer_result_check,
    harness_recover,
    harness_recoverable,
    harness_rename,
    harness_rewind,
    harness_roles_info,
    harness_send,
    harness_sessions,
    harness_set_model,
    harness_set_prompt,
    harness_set_roles,
    harness_set_vision,
    harness_skill_zh_translate,
    harness_skills,
    harness_stream,
    harness_subagent_replay,
    harness_subagent_tail,
    harness_transcript,
    harness_upload,
    harness_vision_status,
    log,
)
