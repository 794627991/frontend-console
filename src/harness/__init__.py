# -*- coding: utf-8 -*-
"""harness 包 —— v3.0 自 src/claude_harness.py 重构拆分。

旧引用入口 src/claude_harness.py 兼容 shim 已随 B 激进批退役（a140），
一律 from src.harness.xxx import ...。各模块职责见各自 docstring。
"""
# harness 版本单一源（v3.5.0+ 用户拍板「与工具版本分离」——harness 迭代
# 快于发版，独立演进号）：GET /api/harness/version 下发，前端 index.html
# 静态值仅作首屏兜底。与工具发版版本 src.version.APP_VERSION 互不牵连
#（打包/升级链只看 APP_VERSION）。
#
# a467：常量手工 bump 在 a388 之后 80 个提交里一次都没发生（用户实锤：
# 诊断栏一直 v4.1.0-a405——运行实例更旧）。改为**启动时从 git 提交史自动
# 取最新 v4.1.0-aNNN**（源码运行机器都有 git）；打包版无 .git 回落常量
#（发版打包时以当时 HEAD 为准改一次即可）。进程内缓存——版本反映的是
# **正在运行的代码**，提交后不重启不换号（与「请重启生效」横幅语义一致）。
_HARNESS_FALLBACK = "4.1.0-a467"


def _parse_harness_version(subjects):
    """从提交标题（新→旧）取第一个 v4.1.0-aNNN。纯函数供测试。"""
    import re
    for s in subjects or []:
        m = re.match(r"^v4\.1\.0-a(\d+)", str(s or ""))
        if m:
            return "4.1.0-a" + m.group(1)
    return ""


def _git_harness_version():
    """git 提交史取版本；无 git/无 .git/任何异常返回空（走回落）。"""
    import os
    import subprocess
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):                    # src/harness → 仓库根
        if os.path.isdir(os.path.join(d, ".git")):
            break
        d = os.path.dirname(d)
    else:
        return ""
    try:
        out = subprocess.run(
            ["git", "log", "--format=%s", "-n", "400"],
            cwd=d, capture_output=True, timeout=5).stdout
        return _parse_harness_version(
            out.decode("utf-8", "replace").splitlines())
    except Exception:
        return ""


HARNESS_VERSION = _git_harness_version() or _HARNESS_FALLBACK
from .consts import (_EVENTS_MAX, _IDLE_KILL_S, _META_FILE, _PROMPTS_KEY, _PROMPTS_LEGACY_KEY, _QUEUE_MAX, _SKILL_ZH_FILE, _SRC_DIR, _UPLOAD_DIR, _UPLOAD_MAX, _sessions, _sessions_lock, log)
from .meta import (_meta, _meta_load, _meta_loaded, _meta_lock, _meta_save, _meta_tombstones, log)
from .models import (_models_cache, available_models, log)
from .prompts import (_collect_system_prompt, _prompt_matches_project, _prompts_load, _prompts_save, log)
from .bridges import (TOKEN_RULES, _bridge_fp, ask_bridge_text, confirm_bridge_text, log, vision_bridge_text)
from .askmcp import (_ask_mcp_cfg_path, log)
from .audit import (_AUDIT_EDIT_TOOLS, _AUDIT_LOG_MAX, _AUDIT_MSG_PREFIX, _AUDIT_ROLES, _audit_dispatch_role, _audit_hook_settings_path, _audit_iso_now, _audit_lines, _audit_log_append, _audit_log_read, _audit_nlines, log)
from .session import (HarnessSession, _CTX_WINDOW_1M, _CTX_WINDOW_DEFAULT, _session_ctx_used, _session_ctx_window, log)
from .transcript import (_SKIP_RE, _SUBAGENT_BLK_FULL, _extract_att, _inject_subagent_blocks, _map_subagent_rows, _strip_att, _subagent_rows_for, _subagent_rows_from_jsonl, _subagent_transcript_candidates, _tool_summary, log, re_title, transcript_for)
