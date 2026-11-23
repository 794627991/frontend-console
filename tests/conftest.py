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
# a561 审计 F13：残留环境不得让 pytest 变成"真应用实例"起 bot/
# 自动登录（hiklink._autostart / proxy_module_init 都认这个标志）
os.environ.pop("FC_APP_BOOT", None)

# 测试身份血缘标记（第七轮 R7-1 高危）：必须在这里设，且必须先于任何
# 测试模块导入 app_state。
# conftest.py 由 pytest 在**收集阶段**导入——早于测试模块；而
# PYTEST_CURRENT_TEST 只在每条用例执行期间存在，收集阶段没有它，
# app_state 的自隔离靠它认不出 pytest，于是「跑 pytest」会读写用户真实的
# 数据目录、并把指针写进真实的 %APPDATA%。app_state 侧也加了按 argv[0]
# 认 pytest 入口的判定，这里是第二道（不依赖 app_state 那条判定对不对）。
os.environ.setdefault("FC_TEST_CHILD", "1")
