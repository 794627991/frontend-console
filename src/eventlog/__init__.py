# -*- coding: utf-8 -*-
"""eventlog —— 会话事件溯源层（v3.0，方案对照 ZCode 事件溯源架构）。

模块唯一公开入口（architecture-policy.yaml 声明）：外部只允许
`from src.eventlog import ...`，不得深 import 子模块。

公开内容：
  SessionEventLog    每会话门面（HarnessSession 对接点）
  SessionEventType   事件类型常量清单（契约单一源）
  reduce_events      事件段 → 投影（冷重建/测试）
  PROTOCOL_LIMITS    协议参数（截断/stash 上限）
"""
from .types import (SessionEventType, TRANSIENT_SESSION_EVENT_TYPES,
                    new_epoch, new_turn_id, type_for_kind)
from .store import SessionEventStore
from .truncate import ToolOutputStash, truncate_tool_output, PROTOCOL_LIMITS
from .reducer import initial_projection, apply_event, reduce_events
from .log import SessionEventLog

__all__ = [
    "SessionEventType", "TRANSIENT_SESSION_EVENT_TYPES",
    "new_epoch", "new_turn_id", "type_for_kind",
    "SessionEventStore",
    "ToolOutputStash", "truncate_tool_output", "PROTOCOL_LIMITS",
    "initial_projection", "apply_event", "reduce_events",
    "SessionEventLog",
]
