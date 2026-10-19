# -*- coding: utf-8 -*-
"""harness 包 —— v3.0 自 src/claude_harness.py 重构拆分。

旧引用入口 src/claude_harness.py 保留为兼容 shim,新代码建议直接
from src.harness.xxx import ...。各模块职责见各自 docstring。
"""
# harness 版本单一源（v3.5.0+ 用户拍板「与工具版本分离」——harness 迭代
# 快于发版，独立演进号）：bump 只改这一处；GET /api/harness/version 下发，
# 前端 index.html 静态值仅作首屏兜底。与工具发版版本 src.version.APP_VERSION
# 互不牵连（打包/升级链只看 APP_VERSION）。
<<<<<<< HEAD
HARNESS_VERSION = "3.5.338"
=======
HARNESS_VERSION = "3.5.336"
>>>>>>> 8a13bae (v3.5.336 Edit行号ZCode架构对齐(用户令「完全参考ZCode,反反复复修不好」——彻底弃前端事后回填路线): ZCode做法=权威事实一次产生:编辑结果落盘时算好hunk行号(oldStart/newStart)随转写行结构化下发,前端零回填零竞态;对齐实施=①后端transcript响应前对Edit/MultiEdit行注入l.dln(_dln_locate当前文件定位new_string,歧义/miss给None不造假,进程缓存_DLN_CACHE防重复IO) ②前端diffHtml加ln0参数(行号计数器初值=ln0-1,Edit原位替换两侧同偏移) ③_histToolBodyHtml把l.dln直传v.dln(Edit单处进diff行号,MultiEdit保chip语义);所有重建路径(快照/重渲/刷新/重开)读转写即得真实行号;实测:真实编辑用例注入259=文件实际259一致,唯一行302精确,重复行'  }'×17歧义None保守;live路保留331回填作结果到达前过渡)
from .consts import (_EVENTS_MAX, _IDLE_KILL_S, _META_FILE, _PROMPTS_KEY, _PROMPTS_LEGACY_KEY, _QUEUE_MAX, _SKILL_ZH_FILE, _SRC_DIR, _UPLOAD_DIR, _UPLOAD_MAX, _sessions, _sessions_lock, log)
from .meta import (_meta, _meta_load, _meta_loaded, _meta_lock, _meta_save, _meta_tombstones, log)
from .models import (_models_cache, available_models, log)
from .prompts import (_collect_system_prompt, _prompt_matches_project, _prompts_load, _prompts_save, log)
from .bridges import (TOKEN_RULES, _bridge_fp, ask_bridge_text, confirm_bridge_text, log, vision_bridge_text)
from .askmcp import (_ask_mcp_cfg_path, log)
from .audit import (_AUDIT_EDIT_TOOLS, _AUDIT_LOG_MAX, _AUDIT_MSG_PREFIX, _AUDIT_ROLES, _audit_dispatch_role, _audit_hook_settings_path, _audit_iso_now, _audit_lines, _audit_log_append, _audit_log_read, _audit_nlines, log)
from .session import (HarnessSession, _CTX_WINDOW_1M, _CTX_WINDOW_DEFAULT, _session_ctx_used, _session_ctx_window, log)
from .transcript import (_SKIP_RE, _SUBAGENT_BLK_FULL, _extract_att, _inject_subagent_blocks, _map_subagent_rows, _strip_att, _subagent_rows_for, _subagent_rows_from_jsonl, _subagent_transcript_candidates, _tool_summary, log, re_title, transcript_for)
