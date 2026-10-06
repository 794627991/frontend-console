# -*- coding: utf-8 -*-
"""harness.consts —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import os
import threading
import logging
log = logging.getLogger(__name__)
from .. import app_state as _st


# ---- from claude_harness.py:32 (_EVENTS_MAX) ----
_EVENTS_MAX = 4000          # 每会话事件缓存上限（前端重连回放用）

# ---- from claude_harness.py:33 (_QUEUE_MAX) ----
_QUEUE_MAX = 2000           # SSE 客户端队列上限

# ---- from claude_harness.py:34 (_IDLE_KILL_S) ----
_IDLE_KILL_S = 15 * 60      # 活进程闲置回收阈值（秒）

# ---- from claude_harness.py:35 (_META_FILE) ----
_META_FILE = os.path.join(_st.HOME_DIR, "claude_harness.json")

# ---- from claude_harness.py:36 (_UPLOAD_DIR) ----
_UPLOAD_DIR = os.path.join(_st.HOME_DIR, "harness_uploads")

# ---- from claude_harness.py:37 (_UPLOAD_MAX) ----
_UPLOAD_MAX = 20 * 1024 * 1024

# ---- from claude_harness.py:38 (_PROMPTS_KEY) ----


# ---------------------------------------------------------------------------
# 用户自定义提示词（v2.8：多条目体系）
#   harness_prompts = [ {id, scope, project, note, text, enabled} ]
#   scope ∈ {"global","project"}；global 对所有会话生效；project 只对
#   cwd 匹配 project 的会话生效（末段目录名精确匹配，如 "串口控制台Pro"
#   匹配 D:\AI\串口控制台Pro——比全路径匹配好写好认）。
#   start() 时收集 启用的 global 条目 + cwd 匹配的启用 project 条目，
#   按 note 头 / text 体 拼接注入 --append-system-prompt。
# 旧单条 harness_system_prompt（v2.4）自动迁移为一条 global 条目（一次性）。
# ---------------------------------------------------------------------------
_PROMPTS_KEY = "harness_prompts"

# ---- from claude_harness.py:51 (_PROMPTS_LEGACY_KEY) ----
_PROMPTS_LEGACY_KEY = "harness_system_prompt"

# ---- from claude_harness.py:799 (_SRC_DIR) ----


# ---------------------------------------------------------------------------
# 交互式提问（v2.17）
#   CLI 在 -p 下没有 AskUserQuestion/ExitPlanMode，所以 ask_user 走自建 MCP。
#   MCP server（src/harness/ask_mcp.py）反过来通过这两个端点找用户要答案，
#   前端渲染可点卡片 → 用户提交 → 唤醒那边阻塞着的工具调用。
# ---------------------------------------------------------------------------
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # v3.0: 子包内取两级回到 src/

# ---- from claude_harness.py:2134 (_sessions) ----


# ---------------------------------------------------------------------------
# 会话表 + 闲置回收
# ---------------------------------------------------------------------------
_sessions = {}              # sid -> HarnessSession（活/复活中的对象）

# ---- from claude_harness.py:2140 (_sessions_lock) ----
_sessions_lock = threading.Lock()

# ---- from claude_harness.py:4129 (_SKILL_ZH_FILE) ----


# ---- 技能描述汉化（v2.27：新增技能自动翻译，免长期手工维护映射表）----
_SKILL_ZH_FILE = os.path.join(_st.HOME_DIR, "skill_zh_cache.json")
