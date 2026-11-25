# -*- coding: utf-8 -*-
"""harness.askmcp —— v3.0 重构自 src/claude_harness.py(机械切割,见 tools/_split_gen.py)"""
import json
import os
import sys
import logging
log = logging.getLogger(__name__)
from .. import app_state as _st
from .consts import _SRC_DIR
from .vision import _vision_load


# ---- from claude_harness.py:808 (_ask_mcp_cfg_path) ----


def _ask_mcp_cfg_path(sid, perm="auto", include_vision=True):
    """写本会话的 --mcp-config 文件（内容极小，每次 start 覆写）。

    perm：会话权限模式（auto/confirm），经 HARNESS_PERM 传给 ask_user MCP。
    include_vision：vision server（本地兜底识图 analyze_image）是否注入——
    v3.5.36（用户拍板「多模态模型 MCP 直接不启用」）：主会话模型判定为
    多模态（inline 直读）时传 False，analyze_image 工具从工具列表彻底消失
    （比不预授权更干净——模型连尝试入口都没有）；非多模态默认 True。
    路径用正斜杠：cmd.exe shim 会吞反斜杠转义，JSON 里带 \\ 的 Windows 路径
    经 shim 传递后解析失败（实测 --mcp-config 内联 JSON 会被引号处理吃掉）。
    """
    d = os.path.join(_st.STATE_DIR, "harness_ask")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return None
    # 打包（PyInstaller）下 src 不在磁盘上，改用 exe 自己的 --mcp-ask /
    # --mcp-vision 模式
    if getattr(sys, "frozen", False):
        ask_cmd, ask_args = sys.executable, ["--mcp-ask"]
        vis_cmd, vis_args = sys.executable, ["--mcp-vision"]
        _pyroot = ""
    else:
        ask_cmd = vis_cmd = (sys.executable or "python")
        ask_args = [os.path.join(_SRC_DIR, "harness", "ask_mcp.py").replace("\\", "/")]
        vis_args = [os.path.join(_SRC_DIR, "harness", "vision_mcp.py").replace("\\", "/")]
        # 2026-11-25 用户实锤「ask_user 一直好使，必须严查」：
        # 这两个 server 脚本开头就 `from src import app_state`，而它们由
        # claude 以 **会话工程目录** 为 cwd 拉起（session.py 的 cwd=self.cwd），
        # 脚本模式下 sys.path[0] 又只含脚本自己的目录（src/harness/）——
        # 工具根不在搜索路径上，import 直接 ModuleNotFoundError，进程秒退。
        # MCP 起不来时 claude 只表现为「少一个工具」、不报错，于是静默失效
        # （实测：本会话 --mcp-config 传了、白名单也给了，但 claude 的子进程
        # 里根本没有 ask_mcp 的 python——它启动即崩）。
        # 修法：显式把工具根塞进子进程的 PYTHONPATH，不再赌 cwd。
        _pyroot = os.path.dirname(_SRC_DIR).replace("\\", "/")
    # v2.28.5：注入两个 server——harness（ask_user）+ vision（本地兜底
    # 识图 analyze_image）。网关内置的 mcp__4_5v_mcp__analyze_image 是主通道
    # （服务端执行，无需本地配置）；本地版用独立名字 mcp__vision__analyze_image
    # 做兜底——同名会被网关遮蔽成影子工具（实测），改名后网关失败时模型
    # 才真正有第二条路可走。随识图开关门控（与引导词开关同步）。
    # PYTHONIOENCODING 防 GBK 控制台下中文工具描述乱码。
    servers = {"harness": {
        "command": ask_cmd,
        "args": ask_args,
        "env": dict({"HARNESS_SID": sid, "HARNESS_PERM": perm},
                    **({"PYTHONPATH": _pyroot} if _pyroot else {})),
    }}
    if include_vision and _vision_load()["enabled"]:
        servers["vision"] = {
            "command": vis_cmd,
            "args": vis_args,
            "env": dict({"PYTHONIOENCODING": "utf-8"},
                        **({"PYTHONPATH": _pyroot} if _pyroot else {})),
        }
    cfg = {"mcpServers": servers}
    p = os.path.join(d, "%s.json" % sid[:16])
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except Exception:
        return None
    return p.replace("\\", "/")
