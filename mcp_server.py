#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端控制台 Pro —— MCP Server (stdio 传输)

让 Claude Code（或任何 MCP 客户端）原生集成终端控制台 Pro 的能力：
  - 查看串口/SSH 连接状态与输出
  - 发命令、发原始字节（Ctrl-C 等）
  - 读取/搜索日志文件（含拖放进工具的任意路径日志）

服务发现：读 ~/.serialconsole_pro/endpoint.json 找到工具后端 HTTP 地址。
工具没开时自动拉起（复用 serial_cli.py 的启动逻辑）。

Claude Code 配置（~/.claude.json 或项目 .mcp.json）:
{
  "mcpServers": {
    "serial-console-pro": {
      "command": "python",
      "args": ["D:\\AI\\串口控制台Pro\\mcp_server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import subprocess

# ---- 服务发现（与 serial_cli.py 共用 endpoint.json） ----
STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
ENDPOINT_FILE = os.path.join(STATE_DIR, "endpoint.json")

# 工具没开时自动拉起的候选入口
_EXE_CANDIDATES = [
    r"D:\AI\串口控制台Pro\dist\串口控制台Pro.exe",
    os.path.join(os.path.expanduser("~"), "Desktop", "串口控制台Pro.exe"),
]
_RUN_BAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.bat")
_MAIN_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")


def _find_endpoint():
    """返回 (url, info) 或 (None, None)。不探活，只读文件。"""
    if not os.path.isfile(ENDPOINT_FILE):
        return None, None
    try:
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            info = json.load(f)
        url = info.get("url")
        return (url, info) if url else (None, None)
    except Exception:
        return None, None


def _alive(url, timeout=1.0):
    """探活后端 /api/status。"""
    try:
        urllib.request.urlopen(url + "/api/status", timeout=timeout)
        return True
    except Exception:
        return False


def _ensure_backend():
    """确保工具后端在跑。没开则拉起，最多等 25s。返回 (url, info) 或 (None, None)。"""
    url, info = _find_endpoint()
    if url and _alive(url):
        return url, info
    # 拉起工具（优先 run.bat 源码运行，其次 exe）
    launched = False
    for exe in _EXE_CANDIDATES:
        if os.path.isfile(exe):
            try:
                subprocess.Popen([exe], cwd=os.path.dirname(exe),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                launched = True
                break
            except Exception:
                pass
    if not launched and os.path.isfile(_RUN_BAT):
        try:
            subprocess.Popen([_RUN_BAT], cwd=os.path.dirname(_RUN_BAT),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            launched = True
        except Exception:
            pass
    if not launched and os.path.isfile(_MAIN_PY):
        try:
            subprocess.Popen([sys.executable, _MAIN_PY], cwd=os.path.dirname(_MAIN_PY),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            launched = True
        except Exception:
            pass
    if not launched:
        return None, None
    # 轮询等就绪
    for _ in range(50):
        time.sleep(0.5)
        url, info = _find_endpoint()
        if url and _alive(url):
            return url, info
    return None, None


# ---- HTTP 调用封装 ----
def _get(url, path, params=None, timeout=30):
    q = ""
    if params:
        q = "?" + urllib.parse.urlencode(params)
    req = urllib.request.urlopen(url + path + q, timeout=timeout)
    return json.loads(req.read().decode("utf-8"))


def _post(url, path, body, timeout=30):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fmt_lines(items, max_text=200):
    """把后端返回的行列表格式化成易读文本。"""
    out = []
    for it in items:
        ts = it.get("ts")
        tstr = ""
        if ts:
            import datetime
            tstr = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S") + "." + str(ts % 1000).zfill(3)
        tag = it.get("tag") or ""
        text = (it.get("text") or "").rstrip()
        if len(text) > max_text:
            text = text[:max_text] + "…"
        prefix = f"[{tstr}]" if tstr else ""
        if tag:
            prefix += f"[{tag}]"
        out.append(f"{prefix} {text}" if prefix else text)
    return "\n".join(out)


# ---- MCP 工具实现 ----
def tool_observe(url, n=50):
    """概览：所有连接状态 + 各连接最近 N 行输出。"""
    j = _get(url, "/api/ai/observe", {"n": n})
    if not j.get("ok"):
        return f"后端错误: {j.get('err', '未知')}"
    connected = j.get("connected", [])
    if not connected:
        return "当前无活动连接。用 list_ports 查看可用串口，connect_serial 建立连接。"
    lines = [f"已连接 {len(connected)} 个: {', '.join(connected)}", ""]
    for pid, status in (j.get("status") or {}).items():
        lines.append(f"=== {pid} ===")
        lines.append(f"  端口/主机: {status.get('port', status.get('host', ''))}  波特率: {status.get('baud', '')}")
        lines.append(f"  缓冲行数: {status.get('buf_lines', 0)}  命令历史: {status.get('cmd_history_count', 0)}")
        recent = (j.get("recent") or {}).get(pid, [])
        if recent:
            lines.append("  最近输出:")
            for l in _fmt_lines(recent).split("\n"):
                lines.append("    " + l)
        lines.append("")
    return "\n".join(lines)


def tool_list_ports(url):
    """列出可用串口 + 已连接的连接。"""
    j = _get(url, "/api/ai/ports")
    ports = j.get("ports", [])
    connected = j.get("connected", [])
    out = []
    if connected:
        out.append(f"已连接: {', '.join(connected)}")
    else:
        out.append("已连接: 无")
    out.append("")
    out.append("可用串口:")
    if not ports:
        out.append("  （无可用串口）")
    else:
        for p in ports:
            out.append(f"  {p.get('device', '?')} — {p.get('description', '')}")
    return "\n".join(out)


def tool_connect_serial(url, port, baud=115200):
    """建立串口连接。"""
    j = _post(url, "/api/connect", {"kind": "serial", "port": port, "baud": baud})
    if j.get("ok"):
        return f"已连接 {port}@{baud}（port_id={j.get('port_id', port)}）"
    return f"连接失败: {j.get('err', '未知错误')}"


def tool_connect_ssh(url, host, username, password=None, key_path=None, port=22):
    """建立 SSH 连接。"""
    body = {"kind": "ssh", "host": host, "port": port, "username": username}
    if password:
        body["password"] = password
    if key_path:
        body["key_path"] = key_path
    j = _post(url, "/api/connect", body)
    if j.get("ok"):
        return f"已连接 {username}@{host}:{port}（port_id={j.get('port_id')}）"
    return f"SSH 连接失败: {j.get('err', '未知错误')}"


def tool_send_command(url, port_id, cmd, wait=2.0):
    """向连接发送命令（自动加回车），等待回显秒数后返回新输出。"""
    j = _post(url, "/api/ai/send", {"port_id": port_id, "cmd": cmd, "wait": wait})
    if not j.get("ok"):
        return f"发送失败: {j.get('err', '串口未连接？')}"
    resp = j.get("response", [])
    if not resp:
        return f"已发送: {cmd}\n（{wait}s 内无新输出）"
    return f"已发送: {cmd}\n回显:\n" + _fmt_lines(resp)


def tool_send_raw(url, port_id, bytes_list):
    """发送原始字节（如 [3]=Ctrl-C, [4]=Ctrl-D）。"""
    j = _post(url, "/api/ai/send_raw", {"port_id": port_id, "bytes": bytes_list})
    if j.get("ok"):
        return f"已发送 {j.get('sent', len(bytes_list))} 字节"
    return f"发送失败: {j.get('err', '未知')}"


def tool_get_buffer(url, port_id, n=200):
    """获取指定连接最近 N 行缓冲。"""
    j = _get(url, "/api/ai/buffer", {"port_id": port_id, "n": n})
    if not j.get("ok"):
        return f"获取失败: {j.get('err', '未知')}"
    lines = j.get("lines", [])
    if not lines:
        return f"{port_id} 缓冲为空"
    return f"=== {port_id} 最近 {len(lines)} 行 ===\n" + _fmt_lines(lines)


def tool_read_log(url, path, offset=0, limit=200):
    """读取日志文件（支持绝对路径或日志目录内文件名）。
    先返回总行数，再返回指定页的行。"""
    jc = _get(url, "/api/log_count", {"name": path})
    if not jc.get("ok"):
        return f"无法读取日志: {jc.get('err', '文件不存在或无权限')}"
    total = jc.get("total", 0)
    jp = _get(url, "/api/log_page", {"name": path, "offset": offset, "limit": limit})
    if not jp.get("ok"):
        return f"日志共 {total} 行，但分页读取失败: {jp.get('err', '')}"
    lines = jp.get("lines", [])
    body = _fmt_lines(lines)
    return f"日志: {path}\n共 {total} 行，显示 {offset}-{offset + len(lines) - 1}:\n{body}"


def tool_search_log(url, path, query, limit=500):
    """在日志中搜索关键字，返回命中行（行号 + 内容）。"""
    j = _get(url, "/api/log_search", {"name": path, "q": query, "limit": limit})
    if not j.get("ok"):
        return f"搜索失败: {j.get('err', '未知')}"
    lines = j.get("lines", [])
    if not lines:
        return f"日志 {path} 中未找到「{query}」"
    out = [f"命中 {len(lines)} 处（{path}）:"]
    for l in lines:
        row = l.get("row", "?")
        tag = l.get("tag") or ""
        text = (l.get("text") or "").rstrip()
        if len(text) > 200:
            text = text[:200] + "…"
        out.append(f"  L{row}[{tag}] {text}")
    return "\n".join(out)


def tool_disconnect(url, port_id):
    """断开连接。"""
    j = _post(url, "/api/disconnect", {"port_id": port_id})
    if j.get("ok"):
        return f"已断开 {port_id}"
    return f"断开失败: {j.get('err', '未知')}"


# ---- MCP stdio 协议 ----
# 用最小化 JSON-RPC 实现，避免依赖 mcp SDK（纯标准库即可被 Claude Code 调用）。
# MCP 协议: https://spec.modelcontextprotocol.io/
_TOOLS = [
    {
        "name": "observe",
        "description": "概览终端控制台 Pro：列出所有已连接的串口/SSH，并返回每个连接的最近输出。这是最常用的入口，先调它了解当前状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 50, "description": "每个连接取最近 N 行输出"},
            },
        },
    },
    {
        "name": "list_ports",
        "description": "列出系统可用串口 + 当前已连接的连接。建连接前先调它看有哪些串口。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "connect_serial",
        "description": "建立串口连接。需要端口号（如 COM1）和波特率。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "string", "description": "串口设备名，如 COM1、COM10"},
                "baud": {"type": "integer", "default": 115200, "description": "波特率"},
            },
            "required": ["port"],
        },
    },
    {
        "name": "connect_ssh",
        "description": "建立 SSH 连接。需主机、用户名，密码或密钥路径二选一。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "SSH 主机 IP"},
                "username": {"type": "string", "description": "用户名"},
                "password": {"type": "string", "description": "密码（与 key_path 二选一）"},
                "key_path": {"type": "string", "description": "密钥文件绝对路径（与 password 二选一）"},
                "port": {"type": "integer", "default": 22, "description": "SSH 端口"},
            },
            "required": ["host", "username"],
        },
    },
    {
        "name": "send_command",
        "description": "向已连接的串口/SSH 发送命令（自动加回车），等待回显后返回新输出。最常用的操作命令。注意 BusyBox 设备命令尾部不要带裸数字。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_id": {"type": "string", "description": "连接 ID（COM1 或 ssh:host:22，从 observe 获取）"},
                "cmd": {"type": "string", "description": "要发送的命令"},
                "wait": {"type": "number", "default": 2.0, "description": "等待回显秒数"},
            },
            "required": ["port_id", "cmd"],
        },
    },
    {
        "name": "send_raw",
        "description": "发送原始字节。常用于发 Ctrl-C（[3]）中断卡死进程、Ctrl-D（[4]）结束输入。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_id": {"type": "string", "description": "连接 ID"},
                "bytes": {"type": "array", "items": {"type": "integer"}, "description": "字节列表，如 [3] 表示 Ctrl-C"},
            },
            "required": ["port_id", "bytes"],
        },
    },
    {
        "name": "get_buffer",
        "description": "获取指定连接最近 N 行缓冲输出。需要看更多历史输出时用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_id": {"type": "string", "description": "连接 ID"},
                "n": {"type": "integer", "default": 200, "description": "取最近 N 行"},
            },
            "required": ["port_id"],
        },
    },
    {
        "name": "read_log",
        "description": "读取日志文件。支持绝对路径（用户拖进工具的任意日志）或日志目录内文件名。先返回总行数再返回指定页。用于查看用户打开的日志文件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "日志文件绝对路径或日志目录内文件名"},
                "offset": {"type": "integer", "default": 0, "description": "起始行（0-based）"},
                "limit": {"type": "integer", "default": 200, "description": "读取行数"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_log",
        "description": "在日志文件中搜索关键字，返回所有命中行（行号+内容）。用于在用户打开的日志中定位 error/warning 等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "日志文件绝对路径或文件名"},
                "query": {"type": "string", "description": "搜索关键字"},
                "limit": {"type": "integer", "default": 500, "description": "最多返回命中数"},
            },
            "required": ["path", "query"],
        },
    },
    {
        "name": "disconnect",
        "description": "断开指定连接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_id": {"type": "string", "description": "连接 ID"},
            },
            "required": ["port_id"],
        },
    },
]


def _dispatch(url, name, args):
    """分发工具调用。返回字符串结果。"""
    if name == "observe":
        return tool_observe(url, args.get("n", 50))
    if name == "list_ports":
        return tool_list_ports(url)
    if name == "connect_serial":
        return tool_connect_serial(url, args["port"], args.get("baud", 115200))
    if name == "connect_ssh":
        return tool_connect_ssh(url, args["host"], args["username"],
                                args.get("password"), args.get("key_path"), args.get("port", 22))
    if name == "send_command":
        return tool_send_command(url, args["port_id"], args["cmd"], args.get("wait", 2.0))
    if name == "send_raw":
        return tool_send_raw(url, args["port_id"], args["bytes"])
    if name == "get_buffer":
        return tool_get_buffer(url, args["port_id"], args.get("n", 200))
    if name == "read_log":
        return tool_read_log(url, args["path"], args.get("offset", 0), args.get("limit", 200))
    if name == "search_log":
        return tool_search_log(url, args["path"], args["query"], args.get("limit", 500))
    if name == "disconnect":
        return tool_disconnect(url, args["port_id"])
    return f"未知工具: {name}"


def _send(msg):
    """写一条 JSON-RPC 消息到 stdout（以换行分隔）。"""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(text):
    """把工具返回的文本包成 MCP content result。"""
    return {"content": [{"type": "text", "text": str(text)}]}


def main():
    """MCP stdio 主循环。处理 initialize / tools/list / tools/call。"""
    # 懒发现后端：第一次工具调用时才 ensure，避免 MCP 启动就阻塞
    _url_cache = [None]

    def get_url():
        if _url_cache[0] and _alive(_url_cache[0], timeout=0.8):
            return _url_cache[0]
        url, _ = _ensure_backend()
        _url_cache[0] = url
        return url

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params") or {}

        # 通知（无 id）不回响应
        if req_id is None:
            continue

        if method == "initialize":
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "serial-console-pro", "version": "0.4.0"},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                url = get_url()
                if not url:
                    _send({"jsonrpc": "2.0", "id": req_id,
                           "result": _result("终端控制台 Pro 未运行，且自动拉起失败。请手动启动工具后重试。")})
                    continue
                result = _dispatch(url, name, args)
                _send({"jsonrpc": "2.0", "id": req_id, "result": _result(result)})
            except urllib.error.URLError as e:
                _send({"jsonrpc": "2.0", "id": req_id,
                       "result": _result(f"后端通信失败: {e}（工具可能已关闭，重试会自动拉起）")})
                _url_cache[0] = None  # 失效缓存，下次重新发现
            except Exception as e:
                _send({"jsonrpc": "2.0", "id": req_id,
                       "result": {"content": [{"type": "text", "text": f"工具执行异常: {e}"}], "isError": True}})
        else:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
