# -*- coding: utf-8 -*-
"""pytest 全局隔离（a452，第二轮对抗审计 P1）。

**必须在任何测试模块导入之前**设 CLAUDE_INLINE=1：

`src/server.py` 在**模块导入期**就把
`CLAUDE_OFFLOAD = os.environ.get("CLAUDE_INLINE") != "1"` 固化成常量。
pytest 按文件名序收集，`test_route_smoke.py` 先于 `test_v4_inc.py` 导入，
一旦它先把 `src.server` 拉进来，offload 就被钉死为 True（harness 蓝图不
注册、只剩 `/<path:sub>` 落点）。之后 `test_v4_inc.py` 里再
`os.environ.setdefault("CLAUDE_INLINE","1")` 已经晚了——模块级常量不会重读，
`/api/harness/v4/stream` 返回 503，7 条用例全挂（而单跑该文件却全过）。

conftest.py 由 pytest 在收集测试模块**之前**导入，是唯一可靠的注入点。
"""
import os

os.environ.setdefault("CLAUDE_INLINE", "1")
