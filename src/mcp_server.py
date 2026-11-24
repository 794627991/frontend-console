#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端控制台（版本见 src/version.py）—— MCP Server (stdio 传输)

让 Claude Code（或任何 MCP 客户端）原生集成前端控制台的能力：
  - 查看串口/SSH 连接状态与输出
  - 发命令、发原始字节（Ctrl-C 等）
  - 读取/搜索日志文件（含拖放进工具的任意路径日志）

服务发现：读锚点 endpoint.json（app_state.HOME_DIR，位于 %APPDATA%
下 frontend-console-shell/backend/）找到工具后端 HTTP 地址。
工具没开时自动拉起（复用 serial_cli.py 的启动逻辑）。

Claude Code 配置（~/.claude.json 或项目 .mcp.json）:
{
  "mcpServers": {
    "serial-console-pro": {
      "command": "python",
      "args": ["D:\\AI\\串口控制台Pro\\src\\mcp_server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}

exe 分发（其他用户无需装 Python；exe 内置 MCP server，--mcp 即 stdio 模式）:
{
  "mcpServers": {
    "serial-console-pro": {
      "command": "C:\\path\\to\\前端控制台.exe",
      "args": ["--mcp"]
    }
  }
}
"""
import os
import sys
# v2.3.4 版本单一源：所有用户可见版本串从 src/version.py 取（用户定调
# 「全部指向一个软件版本」）。独立跑本文件（python src/mcp_server.py）时
# sys.path[0]=src/ 找不到包——先补项目根再 import，双失败兜底 "2.3"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from src.version import APP_VERSION
except Exception:
    APP_VERSION = "2.3"
import json
import time
import urllib.request
try:                   # v3.5.187 DevTools 五件套（CDP 直连，懒加载 websocket）
    from src import devtools_cdp
    from src.devtools_cdp import DevtoolsError
except Exception:      # 独立跑（python src/mcp_server.py）兜底 src 在 path
    try:
        import devtools_cdp
        from devtools_cdp import DevtoolsError
    except Exception:
        devtools_cdp = None
        class DevtoolsError(Exception):
            pass
import urllib.error
import urllib.parse
import subprocess

# ---- 服务发现（endpoint.json，工具启动时写入；serial_cli.py 已删） ----
from src import app_state as _st
# 2026-11-23 退役改造：锚点=%APPDATA%\frontend-console-shell\backend
#（app_state._anchor_dir），endpoint 服务发现与 config 同家
ENDPOINT_FILE = os.path.join(_st.HOME_DIR, "endpoint.json")

# 工具没开时自动拉起的候选入口
# PyInstaller frozen（--mcp 模式）下 sys.executable 就是 exe 自己，放最前；
# 源码运行时依次找 src/main.py（始终最新）、开发机 dist exe。
_EXE_CANDIDATES = []
if getattr(sys, "frozen", False):
    _EXE_CANDIDATES.append(sys.executable)               # exe 分发：拉起自己（GUI 模式）
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SRC_DIR)
_EXE_CANDIDATES += [
    os.path.join(_SRC_DIR, "main.py"),                                  # 源码优先
    os.path.join(_ROOT_DIR, "dist", "前端控制台.exe"),                 # 开发机 dist 后备
    os.path.join(os.path.expanduser("~"), "Desktop", "前端控制台.exe"),
]
_RUN_BAT = os.path.join(_ROOT_DIR, "run.bat")


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


_launch_cool_until = [0.0]   # a238 P3-6：拉起失败后的冷却截止（模型对失败
#                             的典型反应是连续重试——每次 Popen+25s 等待的 churn
#                             由冷却压制，60s 内直接快速失败）


def _ensure_backend():
    """确保工具后端在跑。没开则拉起，最多等 25s。返回 (url, info) 或 (None, None)。"""
    url, info = _find_endpoint()
    if url and _alive(url):
        return url, info
    if time.time() < _launch_cool_until[0]:
        return None, None   # 冷却期：上轮拉起刚失败，不再 Popen
    # 拉起工具：优先源码 main.py（始终最新），其次 exe（可能旧版本）
    launched = False
    for candidate in _EXE_CANDIDATES:
        if not os.path.isfile(candidate):
            continue
        try:
            if candidate.endswith(".py"):
                # 源码：用 pythonw 无黑框运行
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                exe_to_run = pyw if os.path.isfile(pyw) else sys.executable
                subprocess.Popen([exe_to_run, candidate], cwd=os.path.dirname(candidate),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                subprocess.Popen([candidate], cwd=os.path.dirname(candidate),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            launched = True
            break
        except Exception:
            continue
    if not launched and os.path.isfile(_RUN_BAT):
        try:
            subprocess.Popen([_RUN_BAT], cwd=os.path.dirname(_RUN_BAT),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            launched = True
        except Exception:
            pass
    if not launched:
        _launch_cool_until[0] = time.time() + 60
        return None, None
    # 轮询等就绪
    for _ in range(50):
        time.sleep(0.5)
        url, info = _find_endpoint()
        if url and _alive(url):
            return url, info
    _launch_cool_until[0] = time.time() + 60   # 25s 未就绪：失败冷却
    return None, None


# ---- HTTP 调用封装 ----
# v3.4.96：93e 进程级 UA 门禁——裸 urllib 默认 UA 会被后端 403（探活走豁免的
# /api/status 能通、真调用全炸）。统一带自家标记（字面量与 server.
# _WEBVIEW_UA_MARK 对齐，勿 import server——MCP server 必须轻载快起）
_SELF_UA = {"User-Agent": "SerialConsoleProWebView/1"}


def _get(url, path, params=None, timeout=30):
    q = ""
    if params:
        q = "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url + path + q, headers=dict(_SELF_UA))
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))


def _post(url, path, body, timeout=30):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json", **_SELF_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _args_summary(args, max_len=120):
    """把工具参数压缩成短摘要，供 MCP 状态面板展示。
    password/key_path 等敏感参数脱敏——SSH 参数 JSON 通常不足 120 字符截断上限，
    明文密码会完整保留在状态面板常驻展示，同屏旁观/截屏即泄露。"""
    try:
        safe = {k: ("***" if k in ("password", "key_path") else v) for k, v in (args or {}).items()}
        s = json.dumps(safe, ensure_ascii=False)
    except Exception:
        s = str(args)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


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
    """概览：所有连接状态 + 各连接最近 N 行输出 + 前端已打开的日志。"""
    j = _get(url, "/api/ai/observe", {"n": n})
    if not j.get("ok"):
        return f"后端错误: {j.get('err', '未知')}"
    connected = j.get("connected", [])
    open_logs = j.get("open_logs", [])
    lines = []
    if connected:
        lines.append(f"已连接 {len(connected)} 个: {', '.join(connected)}")
    else:
        lines.append("已连接: 无（用 list_ports 查看可用串口，connect_serial 建立连接）")
    lines.append("")
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
    if open_logs:
        lines.append(f"前端已打开日志 {len(open_logs)} 个:")
        for l in open_logs:
            total = l.get("total", 0)
            lines.append(f"  📜 {l.get('name', '?')} ({total} 行) — {l.get('path', '')}")
        lines.append("用 read_log/search_log 分析（path 传文件名或绝对路径）")
    else:
        lines.append("前端未打开日志（用户拖放日志到工具或从日志库点击后此处会显示）")
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
    # HTTP 超时须 > 后端 sleep(wait) + 余量，否则 wait 较大时 HTTP 先超时
    j = _post(url, "/api/ai/send", {"port_id": port_id, "cmd": cmd, "wait": wait},
              timeout=max(30, wait + 10))
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


def tool_send_burst(url, port_id, steps):
    """数据连发：一次调用在后端原子执行整条时间线（延时 + 命令/原始字节序列），
    返回每步的新输出。用于 AI 自身思考延迟掐不准时间窗口的场景。
    典型：内核下 reboot 后 uboot 只有 3s 倒计时，需停到 uboot 下——
    steps=[{cmd:"reboot",wait:1},{delay:3,raw:[21],wait:0.5},...{delay:0.5,raw:[21]}]。
    每步 delay 是发送前的等待秒数，wait 是发送后收输出的秒数；cmd 与 raw 二选一。"""
    total = sum(float(s.get("delay", 0)) + float(s.get("wait", 0)) for s in steps)
    j = _post(url, "/api/ai/burst", {"port_id": port_id, "steps": steps},
              timeout=max(60, total + 30))
    if not j.get("ok"):
        # 部分执行也会带已完成的 steps，一并展示
        done = j.get("steps") or []
        head = f"连发失败: {j.get('err', '未知')}"
        if done:
            head += f"（前 {len(done)} 步已执行）"
            return head + "\n" + _fmt_burst_steps(done)
        return head
    return _fmt_burst_steps(j.get("steps") or [])


def _fmt_burst_steps(results):
    """把 burst 返回的步骤结果格式化成易读文本。"""
    out = []
    for r in results:
        out.append(f"--- 第 {r.get('step')} 步: {r.get('action')} ---")
        resp = r.get("response") or []
        if resp:
            for l in _fmt_lines(resp).split("\n"):
                out.append("  " + l)
        else:
            out.append("  （无新输出）")
    return "\n".join(out)


def tool_get_buffer(url, port_id, n=200):
    """获取指定连接最近 N 行缓冲。"""
    j = _get(url, "/api/ai/buffer", {"port_id": port_id, "n": n})
    if not j.get("ok"):
        return f"获取失败: {j.get('err', '未知')}"
    lines = j.get("lines", [])
    if not lines:
        return f"{port_id} 缓冲为空"
    return f"=== {port_id} 最近 {len(lines)} 行 ===\n" + _fmt_lines(lines)


def tool_list_open_logs(url):
    """列出前端（桌面 app）当前已打开的日志文件。
    用户在工具里拖放或从日志库点击打开的日志会出现在这里，让 AI 知道用户当前在看哪个日志。"""
    j = _get(url, "/api/ai/open_logs")
    if not j.get("ok"):
        return f"查询失败: {j.get('err', '未知')}"
    logs = j.get("logs", [])
    if not logs:
        return "前端当前未打开任何日志。（用户拖放日志到工具，或从日志库点击打开后，此处会列出）"
    out = [f"前端已打开 {len(logs)} 个日志:"]
    for l in logs:
        total = l.get("total", 0)
        out.append(f"  📜 {l.get('name', '?')}  ({total} 行)")
        out.append(f"      path: {l.get('path', '')}")
    out.append("用 read_log(path=...) 读取，search_log(path=..., query=...) 搜索。path 可传文件名或绝对路径。")
    return "\n".join(out)


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
    if not lines:
        return f"日志: {path}\n共 {total} 行，offset={offset} 处无内容（超出范围或空文件）。"
    body = _fmt_lines(lines)
    return f"日志: {path}\n共 {total} 行，显示 {offset}-{offset + len(lines) - 1}:\n{body}"


def tool_search_log(url, path, query, limit=500, offset=0):
    """在日志中搜索关键字，返回命中行（行号 + 内容）。
    offset=上次返回的 next_offset 续搜游标（行偏移，非命中序号），
    从该行继续向后扫；首搜传 0（省略）。"""
    j = _get(url, "/api/log_search", {"name": path, "q": query, "limit": limit,
                                      "offset": offset, "count_total": "0" if offset else "1"})
    if not j.get("ok"):
        return f"搜索失败: {j.get('err', '未知')}"
    lines = j.get("lines", [])
    total = j.get("total", 0)
    next_offset = j.get("next_offset", -1)
    has_more = j.get("has_more", False)
    if not lines and not total:
        return f"日志 {path} 中未找到「{query}」"
    out = [f"命中 {total} 处（{path}），显示 {len(lines)} 行:"]
    if has_more and next_offset >= 0:
        out.append(f"（还有更多，用 offset={next_offset} 续搜）")
    for l in lines:
        row = l.get("row", "?")
        tag = l.get("tag") or ""
        text = (l.get("text") or "").rstrip()
        if len(text) > 200:
            text = text[:200] + "…"
        out.append(f"  L{row}[{tag}] {text}")
    return "\n".join(out)


def tool_compare_files(url, a, b):
    """让前端打开文件对比 tab（Monaco DiffEditor 双栏 diff）。任意两份文本文件均可。"""
    j = _post(url, "/api/ai/compare_files", {"a": a, "b": b})
    if not j.get("ok"):
        return f"打开对比失败: {j.get('err', '未知')}"
    return f"已在前端打开对比 tab：A={j.get('a')} ↔ B={j.get('b')}（如未弹出，请确认工具窗口已打开）"


def tool_diff_logs(url, a, b, mode="summary", context=2):
    """对比两份日志差异。BSP 常用于对比"正常启动 vs 异常启动"日志。
    mode=summary（默认）：去重摘要，列出只在某份出现的行 + 出现次数差异，按频次排序。适合找异常日志多了什么报错。
    mode=line：行级 diff，输出增/减/变化块（带上下文）。适合看启动流程哪里分叉。"""
    j = _post(url, "/api/ai/diff_logs", {"a": a, "b": b, "mode": mode, "context": context})
    if not j.get("ok"):
        return f"对比失败: {j.get('err', '未知')}"
    a_name = j.get("a", a)
    b_name = j.get("b", b)
    a_total = j.get("a_total", 0)
    b_total = j.get("b_total", 0)
    header = f"对比: A={a_name}({a_total}行) vs B={b_name}({b_total}行)  模式={j.get('mode')}"
    if mode == "line":
        blocks = j.get("diff_blocks", [])
        if not blocks:
            return f"{header}\n两份日志内容一致（忽略时间戳后无差异）。"
        out = [header, f"共 {j.get('diff_count', 0)} 处差异块:", ""]
        for blk in blocks:
            op = blk.get("op", "?")
            ar = blk.get("a_range", [])
            br = blk.get("b_range", [])
            out.append(f"--- [{op}] A行{ar[0]}-{ar[1]} / B行{br[0]}-{br[1]} ---")
            for l in blk.get("a_lines", []):
                out.append(f"  - A L{l.get('row')}: {l.get('text', '')[:200]}")
            for l in blk.get("b_lines", []):
                out.append(f"  + B L{l.get('row')}: {l.get('text', '')[:200]}")
            out.append("")
        return "\n".join(out)
    # summary 模式
    only_a = j.get("only_a", [])
    only_b = j.get("only_b", [])
    diff_cnt = j.get("count_diffs", [])
    out = [header, f"A唯一行 {j.get('a_unique', 0)} / B唯一行 {j.get('b_unique', 0)}", ""]
    if only_a:
        out.append(f"■ 只在 A 出现的行（{j.get('only_a_total', 0)} 类，显示前 {len(only_a)}）:")
        for l in only_a:
            out.append(f"  ×{l.get('a_count', 0)}  {l.get('text', '')[:200]}")
        out.append("")
    if only_b:
        out.append(f"■ 只在 B 出现的行（{j.get('only_b_total', 0)} 类，显示前 {len(only_b)}）:")
        for l in only_b:
            out.append(f"  ×{l.get('b_count', 0)}  {l.get('text', '')[:200]}")
        out.append("")
    if diff_cnt:
        out.append(f"■ 两边都有但次数差异（{j.get('count_diffs_total', 0)} 类，显示前 {len(diff_cnt)}）:")
        for l in diff_cnt:
            out.append(f"  A×{l.get('a_count', 0)} → B×{l.get('b_count', 0)} (Δ{l.get('delta', 0):+d})  {l.get('text', '')[:200]}")
    if not only_a and not only_b and not diff_cnt:
        out.append("两份日志内容一致（去重后无差异）。")
    return "\n".join(out)


def tool_disconnect(url, port_id):
    """断开连接。"""
    j = _post(url, "/api/disconnect", {"port_id": port_id})
    if j.get("ok"):
        return f"已断开 {port_id}"
    return f"断开失败: {j.get('err', '未知')}"


# ---- TFTP（设备与 PC 互传文件）----
def _fmt_size(n):
    if n is None:
        return "?"
    if n >= 1048576:
        return f"{n/1048576:.1f}MB"
    if n >= 1024:
        return f"{n/1024:.1f}KB"
    return f"{n}B"

def tool_tftp_status(url):
    """TFTP 服务状态：运行中/目录/目录文件列表/最近传输记录。"""
    j = _get(url, "/api/tftp/status")
    if not j.get("ok"):
        return f"查询失败: {j.get('err', '未知')}"
    out = []
    out.append(f"TFTP: {'🟢 运行中' if j.get('running') else '🔴 已停止'}")
    out.append(f"目录: {j.get('root_dir', '?')}")
    files = j.get("files") or []
    if files:
        out.append(f"目录内 {len(files)} 个文件（设备可下载）:")
        for f in files[:20]:
            out.append(f"  📄 {f.get('name')}  {_fmt_size(f.get('size'))}")
    transfers = j.get("transfers") or []
    if transfers:
        out.append(f"最近传输 {len(transfers)} 次:")
        for t in transfers[:10]:
            kind = "设备下载(get)" if t.get("kind") == "get" else "设备上传(put)"
            status = t.get("status", "?")
            size = _fmt_size(t.get("bytes")) + (f"/{_fmt_size(t.get('total'))}" if t.get("total") else "")
            line = f"  [{status}] {kind} {t.get('filename')} {size} from {t.get('peer', '?')}"
            if t.get("err"):
                line += f"  err={t['err']}"
            out.append(line)
    else:
        out.append("暂无传输记录")
    out.append("设备端用法示例: tftp -g -r 文件名 <PC的IP>  (下载) / tftp -p -l 文件名 <PC的IP>  (上传)")
    return "\n".join(out)

def tool_tftp_start(url, root_dir=None):
    """启动 TFTP 服务（UDP 69）。设备端即可上传/下载文件。"""
    body = {"root_dir": root_dir} if root_dir else {}
    j = _post(url, "/api/tftp/start", body)
    if not j.get("ok"):
        return f"启动失败: {j.get('msg', j.get('err', '未知'))}（UDP 69 端口可能被占用，或需管理员权限）"
    return f"{j.get('msg', 'TFTP 已启动')}\n目录: {j.get('root_dir', '')}\n设备端: tftp -g -r <文件> <本机IP> 下载 / tftp -p -l <文件> <本机IP> 上传"

def tool_tftp_stop(url):
    """停止 TFTP 服务。"""
    j = _post(url, "/api/tftp/stop", {})
    if j.get("ok"):
        return j.get("msg", "已停止")
    return f"停止失败: {j.get('err', '未知')}"

def tool_tftp_set_dir(url, root_dir):
    """设置/切换 TFTP 根目录（设备上传的文件落在这里，设备下载的文件从这里读）。"""
    j = _post(url, "/api/tftp/set_dir", {"root_dir": root_dir})
    if not j.get("ok"):
        return f"设置失败: {j.get('err', j.get('msg', '未知'))}"
    files = j.get("files") or []
    extra = f"，目录内 {len(files)} 个文件" if files else ""
    return f"TFTP 目录已切换: {j.get('msg', root_dir)}{extra}"


# ---- MCP stdio 协议 ----
# 用最小化 JSON-RPC 实现，避免依赖 mcp SDK（纯标准库即可被 Claude Code 调用）。
# MCP 协议: https://spec.modelcontextprotocol.io/
# ---- DevTools（CDP 直连 WebView2，v3.5.187 designer 方案）----
# a624：CDP 端口常开（调试能力常开），devtools_* 工具随时可用。
# 无状态用完即弃：每次调用现查 target→新建 WS→执行→close，页面刷新自愈。


def _dt_wrap(fn):
    """统一错误包装：DevtoolsError 族 → 中文三段式文案（类别/详情/建议）。"""
    def wrap(url, args):
        if devtools_cdp is None:
            return "失败：devtools_cdp 模块未加载（导入失败）——检查安装完整性"
        try:
            return fn(url, args)
        except DevtoolsError as e:
            return "失败：%s" % e
        except ValueError as e:
            return "失败：%s" % e      # 参数不合法（如 target 取值）：文案直接给 AI 看
        except Exception as e:
            return "失败：未知错误 %r" % e
    return wrap


# ---- AI 浏览器（2026-11-24 用户需求：AI 用 CDP 操作网页时，页面显示在会话
# 右侧分屏，用户看着 AI 操作）。实现在后端 src/ai_browser.py（推前端展开视图、
# 等壳上报 CDP targetId、发真实鼠标键盘事件）；本进程只转 HTTP 并取回文本。
# 用户拍板：devtools_* 的**默认目标也改为 AI 浏览器**——要操作工具自身界面
# 必须显式 target="app"（此前默认就是工具界面，AI「直接控制工具」看不见）。


def _dt_target(args):
    """devtools_* 的作用目标：browser（缺省，AI 浏览器视图）/ app（工具自身界面）。"""
    t = str(args.get("target") or "browser").strip().lower()
    if t not in ("browser", "app"):
        raise ValueError("target 只能是 browser（AI 浏览器，缺省）或 app（工具自身界面）")
    return t


class _AibrFail(ValueError):
    """后端 AI 浏览器端点回了 ok=false（或回了无法识别的内容）。message 是给 AI 的中文原因。"""


_AIBR_WAIT_MAX = 60.0          # 等待上限（秒），与后端 navigate 的夹限一致
_AIBR_HTTP_SLACK = 60.0        # HTTP 超时 = 等待上限 + 这么多（下限见 _aibr）


def _clamp_wait(timeout):
    """把调用方给的等待上限（秒）夹到 1–60；没给 / 非数字 / nan 给 None（后端用缺省）。
    AI 把秒当毫秒传（30000）时不能原样往下传：后端自己会夹，但 MCP 这边的
    HTTP 超时是按它算的，不夹就会等十个小时（对抗复审实锤）。"""
    if timeout is None:
        return None
    try:
        v = float(timeout)
    except (TypeError, ValueError):
        return None
    if v != v:                   # nan
        return None
    return min(_AIBR_WAIT_MAX, max(1.0, v))


def _aibr(url, path, body=None, timeout=None, http_timeout=None):
    """调后端 AI 浏览器端点，取回已格式化的文本；失败抛 _AibrFail，由工具函数
    外面的 @_dt_wrap 统一转成「失败：…」。不能在这里拼好字符串就返回：调用方
    还会往上加「OK 」「用 Read 查看」之类，失败时就成了「OK 失败：…」
    （对抗审计实锤）。timeout：透传给后端的等待上限（秒，先夹限）；HTTP 超时
    按它留余量——后端最坏要等操作锁 20s + 视图就绪 12s + 监听接上 3s +
    Page.navigate 15s + 等加载 timeout，所以取 timeout + 60、下限 100。"""
    b = dict(body or {})
    wait = _clamp_wait(timeout)
    if wait is not None:
        b["timeout"] = wait
    j = _post(url, "/api/ai_browser/" + path, b,
              timeout=http_timeout or max(100.0, (wait or 0) + _AIBR_HTTP_SLACK))
    if not isinstance(j, dict):
        raise _AibrFail("后端返回了无法识别的内容（不是 JSON 对象）")
    if not j.get("ok"):
        raise _AibrFail(j.get("err") or "后端没有说明原因")
    return j.get("text") or "OK"


def _pick(args, *keys):
    """从工具参数里挑出显式给了的字段（None 不传，让后端用缺省）。"""
    return {k: args[k] for k in keys if args.get(k) is not None}


_SHOT_HINT = "\n用 Read 工具查看（图像）。截图含页面真实内容，转述时注意敏感信息。"


@_dt_wrap
def tool_browser_navigate(url, args):
    return _aibr(url, "navigate", {"url": args.get("url")}, timeout=args.get("timeout"))


@_dt_wrap
def tool_browser_click(url, args):
    return _aibr(url, "click", _pick(args, "selector", "index", "x", "y", "button"))


@_dt_wrap
def tool_browser_type(url, args):
    return _aibr(url, "type", dict({"text": args.get("text")},
                                   **_pick(args, "selector", "clear", "enter")))


@_dt_wrap
def tool_browser_press(url, args):
    return _aibr(url, "press", {"key": args.get("key")})


@_dt_wrap
def tool_browser_wait(url, args):
    return _aibr(url, "wait", _pick(args, "selector", "ms", "timeout"),
                 timeout=args.get("timeout"))


@_dt_wrap
def tool_browser_screenshot(url, args):
    return _aibr(url, "screenshot", {"full": bool(args.get("full"))}) + _SHOT_HINT


@_dt_wrap
def tool_browser_eval(url, args):
    return "OK " + _aibr(url, "eval", {"expression": args.get("expression"),
                                       "max_len": args.get("max_len")})


@_dt_wrap
def tool_browser_dom(url, args):
    return _aibr(url, "dom", _pick(args, "selector", "limit"))


@_dt_wrap
def tool_browser_console(url, args):
    live = float(args.get("live_seconds") or 0)
    return _aibr(url, "console", _pick(args, "tail", "level", "live_seconds"),
                 http_timeout=100 + live)


@_dt_wrap
def tool_browser_network(url, args):
    return _aibr(url, "network", _pick(args, "seconds", "filter"))


@_dt_wrap
def tool_browser_downloads(url, args):
    # 2026-11-24 用户令：下载不弹保存窗口，文件自动存进下载目录（默认 数据目录\
    # download，用户可在设置里改）。打的是下载中心 src/downloads.py（普通网页
    # 标签页的下载也登记在那里）。wait 可以是 0：不走 _aibr 的 timeout 通道
    #（那条夹限下限是 1 秒，还会把它塞进请求体），直接放进请求体
    try:
        wait_s = float(args.get("wait") or 0)
    except (TypeError, ValueError):
        wait_s = 0.0
    if wait_s != wait_s:                  # nan
        wait_s = 0.0
    wait_s = min(_AIBR_WAIT_MAX, max(0.0, wait_s))
    j = _post(url, "/api/downloads/list", {"wait": wait_s},
              timeout=max(100.0, wait_s + _AIBR_HTTP_SLACK))
    if not isinstance(j, dict):
        raise _AibrFail("后端返回了无法识别的内容（不是 JSON 对象）")
    if not j.get("ok"):
        raise _AibrFail(j.get("err") or "后端没有说明原因")
    return j.get("text") or "OK"


@_dt_wrap
def tool_browser_back(url, args):
    return _aibr(url, "back")


@_dt_wrap
def tool_browser_forward(url, args):
    return _aibr(url, "forward")


@_dt_wrap
def tool_browser_reload(url, args):
    return _aibr(url, "reload")


@_dt_wrap
def tool_devtools_eval(url, args):
    expr = str(args.get("expression") or "")
    if not expr:
        return "失败：缺少必填参数 'expression'"
    max_len = max(500, min(20000, int(args.get("max_len") or 4000)))
    if _dt_target(args) == "browser":
        return "OK " + _aibr(url, "eval", {"expression": expr, "max_len": max_len})
    return "OK " + devtools_cdp.evaluate(expr, max_len=max_len)


@_dt_wrap
def tool_devtools_dom(url, args):
    sel = str(args.get("selector") or "")
    if not sel:
        return "失败：缺少必填参数 'selector'"
    limit = max(1, min(50, int(args.get("limit") or 20)))
    if _dt_target(args) == "browser":
        return _aibr(url, "dom", {"selector": sel, "limit": limit})
    js = (
        "(function(){var els=document.querySelectorAll(%s);"
        "var items=[];for(var i=0;i<Math.min(els.length,%d);i++){"
        "var e=els[i],r=e.getBoundingClientRect();"
        "items.push({tag:e.tagName,id:e.id||'',cls:String(e.className||'').slice(0,100),"
        "text:(e.textContent||'').replace(/\\s+/g,' ').trim().slice(0,150),"
        "w:Math.round(r.width),h:Math.round(r.height),"
        "vis:r.width>0&&r.height>0});}"
        "return JSON.stringify({url:location.pathname,title:document.title,"
        "ready:document.readyState,count:els.length,items:items});})()"
        % (json.dumps(sel), limit))
    out = devtools_cdp.evaluate(js, max_len=20000)
    try:
        d = json.loads(out)
    except Exception:
        return out
    lines = ["页面: %s %s [%s]" % (d.get("title", ""), d.get("url", ""), d.get("ready", "")),
             "命中 %s 个" % d.get("count", 0)]
    for it in d.get("items", []):
        if it.get("vis"):
            sz = " [%sx%s]" % (it.get("w"), it.get("h"))
        else:
            sz = " [隐藏]"
        lines.append("<%s id=%s class=%s> %s%s" % (
            it.get("tag"), it.get("id") or "-", (it.get("cls") or "-")[:40],
            (it.get("text") or "")[:80], sz))
    if d.get("count", 0) > len(d.get("items", [])):
        lines.append("（仅列前 %d 个）" % len(d.get("items", [])))
    return "\n".join(lines)


@_dt_wrap
def tool_devtools_console(url, args):
    tail = max(1, min(200, int(args.get("tail") or 50)))
    level = args.get("level") or "all"
    live = max(0, min(30, float(args.get("live_seconds") or 0)))
    if _dt_target(args) == "browser":
        return _aibr(url, "console", _pick(args, "tail", "level", "live_seconds"),
                     http_timeout=45 + live)
    port, tid, _o = devtools_cdp.page_target_origin_probe()
    lines = []
    with devtools_cdp.CdpSession(port, tid) as cs:
        # 缓冲（hook 随页面启动累计；旧前端无缓冲→降级提示）
        # v3.5.187r1 全审S1：条目按旧→新 append，保留最新端（诊断价值最高），
        # 超限显式标注省略数；统计行前置永不丢
        probe = cs.send("Runtime.evaluate", {"expression":
            "window.__consoleBuf ? JSON.stringify(window.__consoleBuf) : 'undefined'"})
        raw = (probe.get("result") or {}).get("value")
        n_err = n_warn = 0
        if raw == "undefined" or raw is None:
            lines.append("（前端无 console 缓冲——旧版本页面，仅实时模式可用）")
            lines.append("统计: error 0, warn 0（无缓冲可统计）")
        else:
            try:
                items = json.loads(raw)
            except Exception:
                items = []
            shown = []
            for it in items:
                lv = it.get("lv")
                if level == "error" and lv != "error":
                    continue
                if level == "warn" and lv not in ("warn", "error"):
                    continue
                if lv == "error":
                    n_err += 1
                elif lv == "warn":
                    n_warn += 1
                shown.append(it)
            drop = len(shown) - tail
            lines.append("统计: error %d, warn %d（缓冲起点=页面最近一次加载）" % (n_err, n_warn))
            if drop > 0:
                lines.append("（已省略最早 %d 条，显示最新 %d 条）" % (drop, tail))
            for it in shown[-tail:]:
                t = time.strftime("%H:%M:%S", time.localtime((it.get("t") or 0) / 1000))
                lines.append("[%s][%s] %s" % (t, it.get("lv"), (it.get("text") or "")[:300]))
        # 实时窗口（可选）
        if live > 0:
            cs.send("Runtime.enable")
            cs.send("Log.enable")
            live_events = []

            def _on(msg):
                m = msg.get("method", "")
                pm = msg.get("params", {})
                if m == "_cdp_disconnected":
                    # r2 全审G2：断连可感知——页面已死不再谎报「无新输出」
                    live_events.append("〔窗口期内页面断连——以上仅为断连前输出〕")
                elif m == "Runtime.consoleAPICalled":
                    txt = " ".join(str(a.get("value", a.get("description", "")))
                                   for a in pm.get("args", []))
                    live_events.append("[%s] %s" % (pm.get("type", "log"), txt[:300]))
                elif m == "Log.entryAdded":
                    en = pm.get("entry", {})
                    live_events.append("[%s] %s" % (en.get("level", "info"),
                                                    (en.get("text") or "")[:300]))
            cs.collect(live, _on)
            if live_events:
                lines.append("—— 实时窗口 %ds 收到 %d 条 ——" % (int(live), len(live_events)))
                lines.extend(live_events[-30:])
            else:
                lines.append("—— 实时窗口 %ds 无新输出 ——" % int(live))
    return "\n".join(lines[:235])   # v3.5.187r1 S1：硬顶提至 220 只防失控


@_dt_wrap
def tool_devtools_screenshot(url, args):
    import base64
    if _dt_target(args) == "browser":
        return _aibr(url, "screenshot", {}) + _SHOT_HINT
    port, tid, _o = devtools_cdp.page_target_origin_probe()
    with devtools_cdp.CdpSession(port, tid) as cs:
        cs.send("Page.enable")
        res = cs.send("Page.captureScreenshot", {"format": "png"}, timeout=15)
    data = base64.b64decode(res.get("data", ""))
    d = os.path.join(_st.STATE_DIR, "devtools")
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, time.strftime("shot_%Y%m%d_%H%M%S")
                      + "_%03d.png" % (int(time.time() * 1000) % 1000))
    with open(fp, "wb") as f:
        f.write(data)
    return ("已保存: %s (%.1f KB)\n用 Read 工具查看（图像）。"
            "注意：截图含用户真实数据，转述时注意敏感信息。" % (fp, len(data) / 1024))


@_dt_wrap
def tool_devtools_network(url, args):
    seconds = max(1, min(30, float(args.get("seconds") or 5)))
    flt = str(args.get("filter") or "")
    if _dt_target(args) == "browser":
        return _aibr(url, "network", {"seconds": int(seconds), "filter": flt})
    port, tid, _o = devtools_cdp.page_target_origin_probe()
    reqs = {}          # requestId → 聚合 dict
    order = []
    with devtools_cdp.CdpSession(port, tid) as cs:
        cs.send("Network.enable")

        def _on(msg):
            m = msg.get("method", "")
            pm = msg.get("params", {})
            rid = pm.get("requestId", "")
            if m == "Network.requestWillBeSent":
                r = pm.get("request", {})
                reqs[rid] = {"url": r.get("url", ""), "method": r.get("method", ""),
                             "type": pm.get("type", ""), "status": None,
                             "size": None, "done": False}
                order.append(rid)
            elif m == "Network.responseReceived" and rid in reqs:
                resp = pm.get("response", {})
                reqs[rid]["status"] = resp.get("status")
                reqs[rid]["type"] = pm.get("type", "") or reqs[rid]["type"]
            elif m == "Network.loadingFinished" and rid in reqs:
                reqs[rid]["size"] = pm.get("encodedDataLength")
                reqs[rid]["done"] = True
            elif m == "Network.loadingFailed" and rid in reqs:
                reqs[rid]["done"] = True
                reqs[rid]["status"] = "FAIL:" + pm.get("errorText", "err")
            elif m == "_cdp_disconnected":
                reqs["__disconnected__"] = True   # r2 G2：断连可感知
        cs.collect(seconds, _on)
    rows = []
    seen = set()
    for rid in order:
        if rid in seen:
            continue
        seen.add(rid)
        r = reqs[rid]
        u = r["url"]
        if flt and flt not in u:
            continue
        rows.append((rid, r, u))
    def _is_fail(r):
        return str(r.get("status", "")).startswith("FAIL")
    def _is_bad(r):
        return isinstance(r.get("status"), int) and r["status"] >= 400
    fail = [(k, r, u) for k, r, u in rows if _is_fail(r)]
    bad = [(k, r, u) for k, r, u in rows if _is_bad(r)]
    _disc = reqs.pop("__disconnected__", False)
    lines = ["窗口 %ds，共 %d 请求 | 失败 %d | 4xx/5xx %d%s" % (
        int(seconds), len(rows), len(fail), len(bad),
        "（窗口期内页面断连，仅含断连前事件）" if _disc else "")]
    _fb = fail + bad
    for _k, r, u in _fb[:15]:
        lines.append("  !! %s %s" % (r.get("status"), u[:120]))
    if len(_fb) > 15:
        lines.append("  （另有 %d 条失败/异常略）" % (len(_fb) - 15))
    bad_keys = {k for k, _r, _u in fail + bad}
    body = [(k, r, u) for k, r, u in rows if k not in bad_keys][-40:]
    for _k, r, u in body:
        st = r.get("status")
        if not r.get("done"):
            st = "[stream]"
        elif not st:
            st = "?"
        sz = ("%dk" % (r["size"] // 1024)) if r.get("size") else ""
        lines.append("%s %s %s %s %s" % (st, r["method"], u[:120], r.get("type", ""), sz))
    if len(body) < len([1 for k, r, u in rows if k not in bad_keys]):
        lines.append("（更早的 %d 条略）" % (len(rows) - len(bad_keys) - len(body)))
    return "\n".join(lines)


_TOOLS = [
    {
        "name": "observe",
        "description": f"概览前端控制台 v{APP_VERSION}：列出所有已连接的串口/SSH，并返回每个连接的最近输出。这是最常用的入口，先调它了解当前状态。重要：本工具与桌面 app 共享同一后端——app 里已连的串口/SSH 会直接出现在这里，port_id 形如 COM1 或 ssh:host:22，可直接用于 send_command/get_buffer，无需也不应再次 connect。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "default": 50, "description": "每个连接取最近 N 行输出"},
            },
        },
    },
    {
        "name": "list_ports",
        "description": "列出系统可用串口 + 当前已连接的连接。本工具与桌面 app 共享后端，已连接列表即 app 里正在用的串口/SSH。要操作已有连接请直接用 observe 拿 port_id，不要重复 connect。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "connect_serial",
        "description": "建立串口连接。需要端口号（如 COM1）和波特率。注意：本工具与桌面 app 共享同一后端，若 app 已连该串口，此处会因端口占用而失败——此时应改用 observe 复用已有连接的 port_id，而非重复 connect。仅在确实需要新建连接时调用。",
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
        "description": "建立 SSH 连接。需主机、用户名，密码或密钥路径二选一。注意：本工具与桌面 app 共享同一后端，若 app 已连该主机，此处会失败——此时应改用 observe 复用已有连接的 port_id（形如 ssh:host:22），而非重复 connect。仅在确实需要新建连接时调用。",
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
                "port_id": {"type": "string", "description": "连接 ID，从 observe 获取（COM1 或 ssh:host:22）。本工具与桌面 app 共享后端，app 里已连的连接直接可用，无需再 connect。"},
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
        "name": "send_burst",
        "description": "数据连发：一次调用在后端原子执行整条时间线（每步可前置延时 + 发命令或原始字节 + 收输出），返回每步新输出。用于时间敏感、AI 思考延迟掐不准窗口的场景。典型用法：内核下重启进 uboot 只有 3s 倒计时，需停到 uboot——steps=[{'cmd':'reboot','wait':1},{'delay':3,'raw':[21],'wait':0.5},{'delay':0.5,'raw':[21]},{'delay':0.5,'raw':[21],'wait':1}]（21=Ctrl-U）。每步字段：delay=发送前等待秒数（默认0），cmd=命令字符串（与 raw 二选一），raw=字节列表，wait=发送后收输出的秒数（默认0）。总时长上限 120s。比多次 send_command 省往返且时间精确。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port_id": {"type": "string", "description": "连接 ID，从 observe 获取"},
                "steps": {
                    "type": "array",
                    "description": "时间线步骤，按序执行",
                    "items": {
                        "type": "object",
                        "properties": {
                            "delay": {"type": "number", "default": 0, "description": "本步骤发送前的等待秒数"},
                            "cmd": {"type": "string", "description": "要发送的命令（自动加回车，与 raw 二选一）"},
                            "raw": {"type": "array", "items": {"type": "integer"}, "description": "原始字节列表如 [21]=Ctrl-U（与 cmd 二选一）"},
                            "wait": {"type": "number", "default": 0, "description": "发送后收集新输出的秒数"},
                        },
                    },
                },
            },
            "required": ["port_id", "steps"],
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
        "name": "list_open_logs",
        "description": "列出前端（桌面 app）当前已打开的日志文件。用户在工具里拖放或从日志库点击打开的日志会出现在这里。分析日志前先调它，拿到 path 再用 read_log/search_log。observe 也会附带此列表。",
        "inputSchema": {"type": "object", "properties": {}},
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
                "offset": {"type": "integer", "default": 0, "description": "续搜游标（上次结果返回的 next_offset 行偏移），首搜省略"},
            },
            "required": ["path", "query"],
        },
    },
    {
        "name": "compare_files",
        "description": "在前端工具中打开两份文件的对比视图（Monaco DiffEditor 双栏 diff，VSCode 同款）。适合用户想直观查看两份日志/配置/源码差异的场景。注意：这是打开界面给用户看，若只要文本形式的 diff 结果（AI 自己分析）用 diff_logs。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "文件 A（基准，左侧）的文件名或绝对路径"},
                "b": {"type": "string", "description": "文件 B（对比，右侧）的文件名或绝对路径"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "diff_logs",
        "description": "对比两份日志差异。BSP 常用于对比'正常启动 vs 异常启动'日志，找异常日志多了什么报错。mode=summary（默认）去重摘要：列出只在某份出现的行 + 出现次数差异，按频次排序，适合找异常多出的报错；mode=line 行级 diff：输出增/减/变化块带上下文，适合看启动流程哪里分叉。a/b 支持文件名或绝对路径。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "日志 A（基准，如正常启动日志）的文件名或绝对路径"},
                "b": {"type": "string", "description": "日志 B（对比，如异常启动日志）的文件名或绝对路径"},
                "mode": {"type": "string", "enum": ["summary", "line"], "default": "summary", "description": "summary=去重摘要按频次差异排序；line=行级 diff 带上下文"},
                "context": {"type": "integer", "default": 2, "description": "line 模式下差异块上下文行数（0-10）"},
            },
            "required": ["a", "b"],
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
    {
        "name": "tftp_status",
        "description": "查询 TFTP 服务状态：运行中/根目录/目录内文件列表/最近传输记录（设备上传下载历史）。BSP 调试常用 TFTP 给设备传固件/配置文件。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tftp_start",
        "description": "启动 TFTP 服务（UDP 69 端口）。启动后设备端可用 tftp 命令上传/下载文件：tftp -g -r <文件名> <PC的IP>（设备下载），tftp -p -l <文件名> <PC的IP>（设备上传）。注意：Windows 防火墙首次可能弹窗，需允许。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_dir": {"type": "string", "description": "TFTP 根目录（可选，不传用当前设置）"},
            },
        },
    },
    {
        "name": "tftp_stop",
        "description": "停止 TFTP 服务。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tftp_set_dir",
        "description": "设置/切换 TFTP 根目录。设备上传的文件落在这里，设备下载的文件从这里读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_dir": {"type": "string", "description": "目录绝对路径"},
            },
            "required": ["root_dir"],
        },
    },
    {
        "name": "devtools_eval",
        "description": "DevTools：执行任意 JS 表达式（支持 await/Promise），返回 JSON 化结果。**默认在 AI 浏览器里执行**（AI 会话右侧分屏里那个可见的网页，用户能看着操作）。要操作前端控制台自己的界面须显式传 target=\"app\"——app 目标可改变工具页面状态与发起真实操作（含发串口命令），慎用；页面刷新即复位。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "JS 表达式（支持 await）"},
                "max_len": {"type": "integer", "default": 4000, "description": "返回截断上限字符"},
                "target": {"type": "string", "enum": ["browser", "app"], "default": "browser",
                           "description": "作用目标：browser=AI 浏览器（缺省）；app=前端控制台自身界面"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "devtools_dom",
        "description": "DevTools：按 CSS 选择器查询页面元素（标签/id/class/文本/尺寸/可见性），附页面标题与 readyState。默认查 AI 浏览器里的网页；target=\"app\" 查前端控制台自身界面。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS 选择器"},
                "limit": {"type": "integer", "default": 20, "description": "最多列出元素数（≤50）"},
                "target": {"type": "string", "enum": ["browser", "app"], "default": "browser",
                           "description": "作用目标：browser=AI 浏览器（缺省）；app=前端控制台自身界面"},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "devtools_console",
        "description": "DevTools：读页面 console 历史（含未捕获异常，环形 200 条）。可加 live_seconds 实时订阅窗口。默认读 AI 浏览器里的网页；target=\"app\" 读前端控制台自身界面。报错定位首选。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tail": {"type": "integer", "default": 50, "description": "取最近 N 条"},
                "level": {"type": "string", "enum": ["all", "error", "warn"], "default": "all"},
                "live_seconds": {"type": "number", "default": 0, "description": ">0 时追加实时订阅窗口（秒，≤30）"},
                "target": {"type": "string", "enum": ["browser", "app"], "default": "browser",
                           "description": "作用目标：browser=AI 浏览器（缺省）；app=前端控制台自身界面"},
            },
        },
    },
    {
        "name": "devtools_screenshot",
        "description": "DevTools：截取页面当前画面，保存 PNG 到用户数据目录并返回绝对路径（用 Read 查看）。默认截 AI 浏览器里的网页；target=\"app\" 截前端控制台自身界面。截图含真实内容，注意敏感信息。",
        "inputSchema": {"type": "object", "properties": {
            "target": {"type": "string", "enum": ["browser", "app"], "default": "browser",
                       "description": "作用目标：browser=AI 浏览器（缺省）；app=前端控制台自身界面"},
        }},
    },
    {
        "name": "devtools_network",
        "description": "DevTools：汇总页面网络请求（状态/方法/URL/类型/大小；失败与 4xx/5xx 全列，其余按序最多 40 行，不返回 body）。默认返回 AI 浏览器网页**最近 N 秒已捕获**的请求（立即返回：先触发动作再调）；target=\"app\" 订阅前端控制台自身界面 N 秒窗口（阻塞）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "default": 5, "description": "监听窗口秒数（1-30）"},
                "filter": {"type": "string", "description": "URL 子串过滤（可选）"},
            "target": {"type": "string", "enum": ["browser", "app"], "default": "browser",
                       "description": "作用目标：browser=AI 浏览器（缺省）；app=前端控制台自身界面"},
            },
        },
    },
    # ---- AI 浏览器（2026-11-24）：可见的受控网页，显示在 AI 会话右侧分屏 ----
    {
        "name": "browser_navigate",
        "description": "AI 浏览器：打开网址。页面显示在前端控制台 AI 会话右侧的分屏里（用户能看着你操作），第一次调用会自动展开。等加载完成后返回最终网址与标题。",
        "inputSchema": {"type": "object", "properties": {
            "url": {"type": "string", "description": "http/https 网址"},
            "timeout": {"type": "number", "default": 20, "minimum": 1, "maximum": 60,
                        "description": "等加载完成的秒数上限（1–60；超时不报错，照常返回）"},
        }, "required": ["url"]},
    },
    {
        "name": "browser_click",
        "description": "AI 浏览器：点击元素。给 CSS 选择器（自动滚动到可见处、取中心点）或 x/y 坐标。真实鼠标事件——用户能在分屏里看到光标移过去并点击。",
        "inputSchema": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "CSS 选择器（与 x/y 二选一）"},
            "index": {"type": "integer", "default": 0, "description": "选择器匹配到多个时点第几个（从 0 起）"},
            "x": {"type": "number", "description": "视口内 x 坐标（CSS 像素）"},
            "y": {"type": "number", "description": "视口内 y 坐标（CSS 像素）"},
            "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
        }},
    },
    {
        "name": "browser_type",
        "description": "AI 浏览器：输入文本。给 selector 就先点进去聚焦（默认先清空原内容）；不给就输入到当前焦点元素。逐字键入，用户能看到输入过程。",
        "inputSchema": {"type": "object", "properties": {
            "text": {"type": "string", "description": "要输入的文本（\\n 表示回车）"},
            "selector": {"type": "string", "description": "输入框的 CSS 选择器（可选）"},
            "clear": {"type": "boolean", "default": True, "description": "输入前是否清空原内容（仅给了 selector 时生效）"},
            "enter": {"type": "boolean", "default": False, "description": "输完是否按回车"},
        }, "required": ["text"]},
    },
    {
        "name": "browser_press",
        "description": "AI 浏览器：按键。如 Enter、Tab、Escape、ArrowDown、Control+a、Shift+Tab。",
        "inputSchema": {"type": "object", "properties": {
            "key": {"type": "string", "description": "按键或组合键，修饰键在前、加号连接"},
        }, "required": ["key"]},
    },
    {
        "name": "browser_wait",
        "description": "AI 浏览器：等待。等某元素出现（selector），或固定等若干毫秒（ms）。页面异步加载后用。",
        "inputSchema": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "等它出现的 CSS 选择器"},
            "ms": {"type": "integer", "description": "固定等待的毫秒数（上限 10000）"},
            "timeout": {"type": "number", "default": 15, "minimum": 1, "maximum": 30,
                        "description": "等元素出现的秒数上限（1–30）"},
        }},
    },
    {
        "name": "browser_screenshot",
        "description": "AI 浏览器：截图。保存 PNG 到用户数据目录 ai_browser/ 并返回绝对路径（用 Read 查看）。full=true 截整个页面。截图含页面真实内容，注意敏感信息。",
        "inputSchema": {"type": "object", "properties": {
            "full": {"type": "boolean", "default": False, "description": "是否截整个页面（含视口外）"},
        }},
    },
    {
        "name": "browser_eval",
        "description": "AI 浏览器：在当前网页里执行任意 JS 表达式（支持 await/Promise），返回 JSON 化结果。读页面状态、取数据用；点击和输入优先用 browser_click / browser_type（有可见操作）。",
        "inputSchema": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "JS 表达式（支持 await）"},
            "max_len": {"type": "integer", "default": 4000, "description": "返回截断上限字符"},
        }, "required": ["expression"]},
    },
    {
        "name": "browser_dom",
        "description": "AI 浏览器：按 CSS 选择器列出网页元素（标签/id/class/文本/尺寸/可见性），附页面标题。定位元素用。",
        "inputSchema": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "CSS 选择器"},
            "limit": {"type": "integer", "default": 20, "description": "最多列出元素数（上限 50）"},
        }, "required": ["selector"]},
    },
    {
        "name": "browser_console",
        "description": "AI 浏览器：读网页 console 历史（含未捕获异常，环形 200 条）。可加 live_seconds 追加实时订阅窗口。报错定位首选。",
        "inputSchema": {"type": "object", "properties": {
            "tail": {"type": "integer", "default": 50, "description": "取最近 N 条"},
            "level": {"type": "string", "enum": ["all", "error", "warn"], "default": "all"},
            "live_seconds": {"type": "number", "default": 0, "description": ">0 时追加实时订阅窗口（秒，上限 30）"},
        }},
    },
    {
        "name": "browser_network",
        "description": "AI 浏览器：汇总网页最近 N 秒内的网络请求（状态/方法/URL/类型/大小；失败与 4xx/5xx 全列，不返回 body）。立即返回——先触发动作再调它。",
        "inputSchema": {"type": "object", "properties": {
            "seconds": {"type": "integer", "default": 10, "description": "回看最近多少秒（上限 300）"},
            "filter": {"type": "string", "description": "URL 子串过滤（可选）"},
        }},
    },
    {
        "name": "browser_downloads",
        "description": "AI 浏览器：查看下载记录（状态 / 大小 / 真实保存路径）。在 AI 浏览器里点下载不会弹保存窗口：文件自动存进下载目录（默认 数据目录\\download，用户可在设置里改）。触发下载后用它拿结果——不要凭页面文案推断文件存到了哪。",
        "inputSchema": {"type": "object", "properties": {
            "wait": {"type": "number", "default": 0, "minimum": 0, "maximum": 60,
                     "description": "有下载正在进行时最多等它多少秒（上限 60）"},
        }},
    },
    {
        "name": "browser_back",
        "description": "AI 浏览器：后退一页。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_forward",
        "description": "AI 浏览器：前进一页。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_reload",
        "description": "AI 浏览器：重新加载当前页。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


_RETRY_SAFE_TOOLS = {
    # a238 P3-5：URLError 重试白名单——只读/幂等工具。connect_*/send_*/
    # tftp_*/disconnect 均有副作用，重试会二次执行（burst 双发/重复握手）
    # a245 P2（a238复审）：devtools_eval 移出——它执行任意 JS（点击/提交/
    # 改 DOM），断连重试=副作用二次执行，与其余 devtools_* 只读族不同类
    "observe", "list_ports", "get_buffer", "read_log", "search_log",
    "list_open_logs", "compare_files", "diff_logs", "tftp_status",
    "devtools_console", "devtools_dom",
    "devtools_network", "devtools_screenshot",
    # 2026-11-24 AI 浏览器只读族（eval/click/type/导航类有副作用，不进）
    "browser_screenshot", "browser_dom",
    "browser_console", "browser_network", "browser_downloads",
}


def _dispatch(url, name, args):
    """分发工具调用。返回字符串结果。"""
    # 缺必填参数时给出明确提示，而非抛 KeyError（AI 偶尔会漏参数）
    def need(key):
        v = args.get(key)
        if v is None:
            raise ValueError(f"缺少必填参数 '{key}'")
        return v
    if name == "observe":
        return tool_observe(url, args.get("n", 50))
    if name == "list_ports":
        return tool_list_ports(url)
    if name == "connect_serial":
        return tool_connect_serial(url, need("port"), args.get("baud", 115200))
    if name == "connect_ssh":
        return tool_connect_ssh(url, need("host"), need("username"),
                                args.get("password"), args.get("key_path"), args.get("port", 22))
    if name == "send_command":
        return tool_send_command(url, need("port_id"), need("cmd"), args.get("wait", 2.0))
    if name == "send_raw":
        return tool_send_raw(url, need("port_id"), need("bytes"))
    if name == "send_burst":
        return tool_send_burst(url, need("port_id"), need("steps"))
    if name == "get_buffer":
        return tool_get_buffer(url, need("port_id"), args.get("n", 200))
    if name == "list_open_logs":
        return tool_list_open_logs(url)
    if name == "read_log":
        return tool_read_log(url, need("path"), args.get("offset", 0), args.get("limit", 200))
    if name == "search_log":
        return tool_search_log(url, need("path"), need("query"), args.get("limit", 500), args.get("offset", 0))
    if name == "compare_files":
        return tool_compare_files(url, need("a"), need("b"))
    if name == "diff_logs":
        return tool_diff_logs(url, need("a"), need("b"), args.get("mode", "summary"), args.get("context", 2))
    if name == "disconnect":
        return tool_disconnect(url, need("port_id"))
    if name == "tftp_status":
        return tool_tftp_status(url)
    if name == "tftp_start":
        return tool_tftp_start(url, args.get("root_dir"))
    if name == "tftp_stop":
        return tool_tftp_stop(url)
    if name == "tftp_set_dir":
        return tool_tftp_set_dir(url, need("root_dir"))
    if name == "devtools_eval":
        return tool_devtools_eval(url, args)
    if name == "devtools_dom":
        return tool_devtools_dom(url, args)
    if name == "devtools_console":
        return tool_devtools_console(url, args)
    if name == "devtools_screenshot":
        return tool_devtools_screenshot(url, args)
    if name == "devtools_network":
        return tool_devtools_network(url, args)
    # AI 浏览器（2026-11-24）
    if name == "browser_navigate":
        return tool_browser_navigate(url, args)
    if name == "browser_click":
        return tool_browser_click(url, args)
    if name == "browser_type":
        return tool_browser_type(url, args)
    if name == "browser_press":
        return tool_browser_press(url, args)
    if name == "browser_wait":
        return tool_browser_wait(url, args)
    if name == "browser_screenshot":
        return tool_browser_screenshot(url, args)
    if name == "browser_eval":
        return tool_browser_eval(url, args)
    if name == "browser_dom":
        return tool_browser_dom(url, args)
    if name == "browser_console":
        return tool_browser_console(url, args)
    if name == "browser_network":
        return tool_browser_network(url, args)
    if name == "browser_downloads":
        return tool_browser_downloads(url, args)
    if name == "browser_back":
        return tool_browser_back(url, args)
    if name == "browser_forward":
        return tool_browser_forward(url, args)
    if name == "browser_reload":
        return tool_browser_reload(url, args)
    return f"未知工具: {name}"


def _send(msg):
    """写一条 JSON-RPC 消息到 stdout（以换行分隔）。"""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(text):
    """把工具返回的文本包成 MCP content result。"""
    return {"content": [{"type": "text", "text": str(text)}]}


class _BackendError(Exception):
    """后端明确返回 4xx/5xx（HTTPError）：错误信息直接作为工具结果，不触发瞬断重试。"""


def _httperr_msg(e):
    """从 HTTPError 响应体提取 err 字段（server.py 已做中文错误分类）。"""
    try:
        body = e.read().decode("utf-8", errors="replace")
        try:
            j = json.loads(body)
            return j.get("err") or body
        except Exception:
            return body
    except Exception:
        return str(e)


def main():
    """MCP stdio 主循环。处理 initialize / tools/list / tools/call。"""
    # Windows 默认 stdout 为系统 ANSI/GBK 编码，json.dumps(ensure_ascii=False) 遇到
    # © 等非 GBK 字符会抛 UnicodeEncodeError，导致工具返回值丢失。统一重配为 utf-8。
    # stdin 同理必须重配：Claude Code 按 MCP stdio 规范写 UTF-8 JSON，stdin 保持
    # GBK 会把中文/emoji 参数解码成乱码+孤立代理字符（\udcad），下游编码必炸。
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
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
                    "serverInfo": {"name": "serial-console-pro", "version": APP_VERSION},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOLS}})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            ok = True
            url = None  # 预初始化，防止 get_url() 抛异常时下方上报引用未定义变量
            try:
                url = get_url()
                if not url:
                    _send({"jsonrpc": "2.0", "id": req_id,
                           "result": _result(f"前端控制台 v{APP_VERSION} 未运行，且自动拉起失败。请手动启动工具后重试。")})
                    continue
                try:
                    result = _dispatch(url, name, args)
                except urllib.error.HTTPError as e:
                    # 后端明确返回 4xx/5xx（密码错/文件不存在/重复 disconnect 等）：
                    # 错误信息直接作为工具结果——server.py 已做中文错误分类。
                    # HTTPError 是 URLError 子类，不能落入下方「瞬断重试」分支：
                    # 重试会把 connect_ssh 这类非幂等调用重复一次完整握手，
                    # 且最终误报「工具可能已关闭」误导 AI 去拉起桌面 app。
                    raise _BackendError(_httperr_msg(e)) from None
                except urllib.error.URLError:
                    # 后端可能刚重启/瞬断（连接拒绝/超时等，非 HTTP 状态错误）：失效缓存，重新发现后端并重试一次
                    # a238 P3-5（第5轮A3）：仅重试只读工具——URLError 也覆盖
                    # 「请求已达、响应丢失」形态，connect_ssh/send_burst 这类
                    # 非幂等调用重试=串口时间线二次发送/重复握手
                    if name not in _RETRY_SAFE_TOOLS:
                        raise
                    _url_cache[0] = None
                    url = get_url()
                    if not url:
                        raise
                    try:
                        result = _dispatch(url, name, args)
                    except urllib.error.HTTPError as e:
                        raise _BackendError(_httperr_msg(e)) from None
                _send({"jsonrpc": "2.0", "id": req_id, "result": _result(result)})
            except _BackendError as e:
                ok = False
                _send({"jsonrpc": "2.0", "id": req_id, "result": _result(f"后端返回错误: {e}")})
            except urllib.error.URLError as e:
                ok = False
                _send({"jsonrpc": "2.0", "id": req_id,
                       "result": _result(f"后端通信失败: {e}（工具可能已关闭，重试会自动拉起）")})
                _url_cache[0] = None  # 失效缓存，下次重新发现
            except Exception as e:
                ok = False
                _send({"jsonrpc": "2.0", "id": req_id,
                       "result": {"content": [{"type": "text", "text": f"工具执行异常: {e}"}], "isError": True}})
            # 上报调用记录给后端（前端 MCP 状态面板展示），失败不阻塞
            if url:
                try:
                    _post(url, "/api/ai/mcp_report", {"tool": name, "args": _args_summary(args), "ok": ok})
                except Exception:
                    pass
        else:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
