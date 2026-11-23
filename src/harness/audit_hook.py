# -*- coding: utf-8 -*-
"""light 形态直改轻审线的事中闸（Claude Code PreToolUse hook 进程）。

回合结算审计（_audit_settle）是事后兜底——违规已发生只能补审；本模块补
事中拦截：light（轻主力）形态会话启动时把本进程注册为 PreToolUse hook
（--settings 临时文件的 hooks 键，见 claude_harness.
_audit_hook_settings_path），CLI 在每次 Edit/Write/MultiEdit/NotebookEdit
前调起本进程，它查后端 /api/harness/audit_gate 拿本回合单次直改最大行数
——达线且本回合尚未派过 reviewer 就 exit 2（block，stderr 文案指路送审：派
reviewer 审已完成的改动，审过即开闸），未超/已送审/未启用 exit 0。

铁律：闸是增强不是依赖——后端不在/超时/输入畸形/任何异常一律 exit 0
放行，绝不因闸自身故障阻塞工作（回合结算审计仍在，双层兜底）。

后端地址读锚点 endpoint.json（app_state.HOME_DIR，工具启动时写入，与
ask_mcp.py 同一套服务发现）；HARNESS_BACKEND 环境变量可覆盖
（同 ask_mcp 的 URL_OVERRIDE 先例，测试用）。双形态入口：源码
`python src/main.py --audit-hook` / 打包 `exe --audit-hook`。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

from src import app_state as _st
ENDPOINT_FILE = os.path.join(_st.HOME_DIR, "endpoint.json")

# matcher 已在 settings 侧过滤，这里再核一遍双保险（hook stdin 字段以 CLI
# 实际为准：{session_id, transcript_path, tool_name, tool_input, ...}）
_GATE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _backend_url():
    """后端 HTTP 根地址；env 覆盖优先，endpoint.json 兜底；读不到 None。"""
    u = (os.environ.get("HARNESS_BACKEND") or "").strip()
    if u:
        return u
    try:
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("url") or None
    except Exception:
        return None


def main():
    # stderr 是给模型看的中文提示，防 GBK 控制台炸非 GBK 字符（mcp_server
    # stdout 同款坑）；stdin 是 CLI 喂的 UTF-8 JSON。stdout 保持静默——
    # hook 协议只认 stderr 与退出码，stdout 上的杂音可能被当输出解析。
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        data = json.loads(sys.stdin.read() or "{}") or {}
    except Exception:
        sys.exit(0)                       # 输入畸形：没有可判依据，放行
    # 子代理直改放行（官方 hooks 文档+本机 CLI 实证）：hooks 在 Task 子
    # 代理内同样触发，且 stdin 的 session_id 与主会话相同——子代理标记是
    # agent_id/agent_type 字段。没有这层判定，子代理工具触发本闸时会被
    # 主会话的累计误拦（闸自锁）。当前子代理（designer 只读/reviewer 只审
    # 不改）工具集本无编辑类，此判定是防将来扩展的安全层。
    # 注意：agent_type 仅在会话带 --agent 启动时主链也会携带——当前 start()
    # 的 argv 无 --agent，判 agent_id or agent_type 安全；将来引入 --agent
    # 启动需收紧为仅判 agent_id。
    if data.get("agent_id") or data.get("agent_type"):
        sys.exit(0)
    if str(data.get("tool_name") or "") not in _GATE_TOOLS:
        sys.exit(0)                       # 非直改类工具不归本闸管
    csid = str(data.get("session_id") or "").strip()
    if not csid:
        sys.exit(0)
    url = _backend_url()
    if not url:
        sys.exit(0)                       # 找不到后端：闸失效，放行
    try:
        q = urllib.parse.quote(csid, safe="")
        # v3.4.98：补门禁标记 UA（与 mcp_server/ask_mcp 同款）——
        # 93e 起 /api/* 无标记一律 403，本闸查询静默失败=直改超线不拦
        # （fail-open；8cbe99b 修了三家自家子进程，这里是被漏掉的第四家）
        req = urllib.request.Request(
            url + "/api/harness/audit_gate?session_id=" + q,
            headers={"User-Agent": "SerialConsoleProWebView/1"})
        with urllib.request.urlopen(req, timeout=2) as r:
            resp = json.loads(r.read().decode("utf-8", "replace") or "{}") or {}
        gate = (resp or {}).get("gate") or {}
        if gate.get("block"):
            # exit 2 = block：stderr 文案回给模型，指路送审——派 reviewer
            # 审已完成的改动，审过即开闸（直干是常态，闸只逼送审不逼停工）
            msg = str(gate.get("msg") or "").strip() \
                or "本回合已有单次直改达到轻审线上限，请先派 reviewer 代理审已完成的改动，审过即可继续。"
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
            sys.exit(2)
    except SystemExit:
        raise                              # 上面 exit(2) 直传，别落进下面的兜底
    except Exception:
        pass                               # 查询失败=闸失效：放行（铁律）
    sys.exit(0)


if __name__ == "__main__":
    main()
