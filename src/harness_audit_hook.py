# -*- coding: utf-8 -*-
"""light 形态直改免审线的事中闸（Claude Code PreToolUse hook 进程）。

v2.34 的回合结算审计（_audit_settle）是事后兜底——违规已发生只能补审；
本模块补事中硬拦截：light（轻主力）形态会话启动时把本进程注册为
PreToolUse hook（--settings 临时文件的 hooks 键，见 claude_harness.
_audit_hook_settings_path），CLI 在每次 Edit/Write/MultiEdit/NotebookEdit
前调起本进程，它查后端 /api/harness/audit_gate 拿本回合直改累计——达到
免审线就 exit 2（block，stderr 文案引导模型改派 dev），未超/未启用 exit 0。

铁律：闸是增强不是依赖——后端不在/超时/输入畸形/任何异常一律 exit 0
放行，绝不因闸自身故障阻塞工作（回合结算审计仍在，双层兜底）。

后端地址读 ~/.serialconsole_pro/endpoint.json（工具启动时写入，与
harness_ask_mcp.py 同一套服务发现）；HARNESS_BACKEND 环境变量可覆盖
（同 ask_mcp 的 URL_OVERRIDE 先例，测试用）。双形态入口：源码
`python src/main.py --audit-hook` / 打包 `exe --audit-hook`。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
ENDPOINT_FILE = os.path.join(STATE_DIR, "endpoint.json")

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
    # 子代理直改放行（官方 hooks 文档+本机 CLI 2.1.278 实证）：hooks 在
    # Task 子代理内同样触发，且 stdin 的 session_id 与主会话相同——子代理
    # 标记是 agent_id/agent_type 字段。没有这层判定，主会话达线被拦后按
    # 提示派 dev，dev 的 Edit 带同一 session_id 仍超线被拦死（闸自锁，
    # 把自己指出的逃生门堵死）。dev 本来就是被派来干活的，放行。
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
        with urllib.request.urlopen(
                url + "/api/harness/audit_gate?session_id=" + q,
                timeout=2) as r:
            resp = json.loads(r.read().decode("utf-8", "replace") or "{}") or {}
        gate = (resp or {}).get("gate") or {}
        if gate.get("block"):
            # exit 2 = block：stderr 文案回给模型，指路派 dev——这正是轻主力
            # 分工的本意（主会话超线直改该转派发，而非继续手改）
            msg = str(gate.get("msg") or "").strip() \
                or "本回合直改已达免审线，请用 Task 工具派 dev 代理实施本改动。"
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
