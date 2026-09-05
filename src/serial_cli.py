#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串口控制台 Pro —— Claude Code 直连桥
作用：让 Claude Code 会话（或任何命令行）一键发现正在运行的工具后端，
      并通过它的 HTTP API 实时查看/发送串口数据。

用法：
  python src/serial_cli.py                  # 概览：服务地址 + 各串口状态 + 最近输出
  python src/serial_cli.py status           # 仅状态
  python src/serial_cli.py ports            # 可用串口 + 已连接
  python src/serial_cli.py buf COM10 50     # 看指定串口最近 50 行
  python src/serial_cli.py recent 80        # 所有串口各取最近 80 行
  python src/serial_cli.py send COM10 "cat /proc/cpuinfo"   # 发命令（自动加回车）
  python src/serial_cli.py raw  COM10 3     # 发原始字节（如 Ctrl-C=3）
  python src/serial_cli.py watch            # 实时跟随输出（轮询，Ctrl-C 退出）

服务发现：读 ~/.serialconsole_pro/endpoint.json（工具启动时写入）。
工具没开时提示用户启动桌面上的「前端控制台.exe」。
"""
import os, sys, json, time, urllib.request, urllib.error, urllib.parse, subprocess

STATE_DIR = os.path.join(os.path.expanduser("~"), ".serialconsole_pro")
ENDPOINT_FILE = os.path.join(STATE_DIR, "endpoint.json")

# 工具 exe 的几个候选位置：dist、桌面
EXE_CANDIDATES = [
    r"D:\AI\串口控制台Pro\dist\前端控制台.exe",
    os.path.join(os.path.expanduser("~"), "Desktop", "前端控制台.exe"),
]
# 自动启动用 run.bat（源码运行，cd 到项目根后 pythonw src/main.py）
RUN_BAT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.bat")

def find_endpoint():
    """返回 (url, info) 或 (None, None)。"""
    if not os.path.isfile(ENDPOINT_FILE):
        return None, None
    try:
        with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
            info = json.load(f)
        url = info.get("url")
        if not url:
            return None, None
        # 验证服务还活着（进程可能已退出但文件未清理）
        try:
            urllib.request.urlopen(url + "/api/status", timeout=1.0)
        except Exception:
            return None, None
        return url, info
    except Exception:
        return None, None

def find_exe():
    """找到工具 exe 的实际路径。"""
    for p in EXE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None

def ensure_running(auto_start=True, timeout=25):
    """确保工具后端在运行。返回 url 或 None。
    auto_start=True 时，若工具未运行则自动启动并等就绪。
    v0.3 测试版优先用 run.bat 启动源码版（而非主目录 exe），避免连错实例。"""
    url, _ = find_endpoint()
    if url:
        return url
    if not auto_start:
        return None
    # 优先用本目录 run.bat 启动 v0.3 源码版
    start_cmd = None
    start_cwd = None
    if os.path.isfile(RUN_BAT):
        start_cmd = ["cmd", "/c", RUN_BAT]
        start_cwd = os.path.dirname(RUN_BAT)
    else:
        exe = find_exe()
        if not exe:
            return None
        start_cmd = [exe]
        start_cwd = os.path.dirname(exe)
    print(f"【前端控制台 v1.0.0 未运行】正在启动: {start_cmd}", file=sys.stderr)
    try:
        # 用 Popen 启动 GUI 进程，不阻塞
        subprocess.Popen(
            start_cmd,
            cwd=start_cwd,
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as e:
        print(f"启动失败: {e}", file=sys.stderr)
        return None
    # 轮询等 endpoint 出现 + 服务就绪
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.5)
        url, _ = find_endpoint()
        if url:
            print(f"【工具已就绪】{url}", file=sys.stderr)
            return url
    print("【超时】工具启动后未在规定时间内就绪，可能需要手动检查。", file=sys.stderr)
    return None

def api_get(url, path):
    try:
        with urllib.request.urlopen(url + path, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "err": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "err": str(e)}

def api_post(url, path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "err": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "err": str(e)}

def need_running():
    print("【前端控制台 v1.0.0 未运行】")
    print("请先双击桌面上的「前端控制台.exe」启动工具，再运行本命令。")
    sys.exit(1)

def cmd_overview(url):
    j = api_get(url, "/api/ai/observe?n=30")
    if not j.get("ok"):
        print("获取失败:", j.get("err")); return
    connected = j.get("connected", [])
    print(f"服务: {url}")
    print(f"已连接串口: {len(connected)} 个")
    if not connected:
        print("  （无连接。在工具里点「新建连接」添加串口。）")
        return
    status = j.get("status", {})
    recent = j.get("recent", {})
    for pid in connected:
        s = status.get(pid, {})
        lines = recent.get(pid, [])
        print(f"\n─ {pid} @ {s.get('baud')} | 缓冲 {s.get('buf_lines')} 行 | 历史 {s.get('cmd_history_count')} 条")
        if lines:
            print(f"  最近 {len(lines)} 行:")
            for l in lines[-12:]:
                tag = l.get("tag", "")
                mark = {"kernel_err": "‼", "kernel": "K", "uboot": "U",
                        "heop_fail": "‼", "heop_ok": "✓", "prompt": ">"}.get(tag, " ")
                print(f"  {mark} {l.get('text','')}")
        else:
            print("  （暂无输出）")

def cmd_status(url):
    j = api_get(url, "/api/status")
    ports = j.get("ports", {})
    print(f"已连接 {len(ports)} 个串口:")
    for pid, p in ports.items():
        print(f"  {pid} @ {p.get('baud')} | 缓冲 {p.get('buf_lines')} 行 | "
              f"录制 {'中' if p.get('recording') else '停'} | 历史 {p.get('cmd_history_count')} 条")

def cmd_ports(url):
    j = api_get(url, "/api/ai/ports")
    print("可用串口:")
    for p in j.get("ports", []):
        print(f"  {p['device']} — {p['description']}")
    conn = j.get("connected", [])
    print(f"已连接: {', '.join(conn) if conn else '（无）'}")

def cmd_buf(url, port, n):
    j = api_get(url, f"/api/ai/buffer?port_id={urllib.parse.quote(port)}&n={n}")
    if not j.get("ok"):
        print(f"失败: {j.get('err')}"); return
    lines = j.get("lines", [])
    print(f"{port} 最近 {len(lines)} 行:")
    for l in lines:
        print(f"  {l.get('text','')}")

def cmd_recent(url, n):
    j = api_get(url, f"/api/ai/recent?n={n}")
    if not j.get("ok"):
        print(f"失败: {j.get('err')}"); return
    for pid, lines in j.get("ports", {}).items():
        print(f"\n─ {pid} (最近 {len(lines)} 行)")
        for l in lines:
            print(f"  {l.get('text','')}")

def cmd_send(url, port, cmd):
    j = api_post(url, "/api/ai/send", {"port_id": port, "cmd": cmd, "wait": 2})
    if not j.get("ok"):
        print(f"发送失败: {j.get('err')}"); return
    print(f"已向 {port} 发送: {j.get('sent')}")
    resp = j.get("response", [])
    if resp:
        print(f"设备返回 {len(resp)} 行:")
        for l in resp:
            print(f"  {l.get('text','')}")
    else:
        print("（设备无返回）")

def cmd_raw(url, port, *bytes_str):
    try:
        bs = [int(b) & 0xFF for b in bytes_str]
    except ValueError:
        print("字节必须是 0-255 整数"); return
    j = api_post(url, "/api/ai/send_raw", {"port_id": port, "bytes": bs})
    if not j.get("ok"):
        print(f"发送失败: {j.get('err')}"); return
    print(f"已向 {port} 发送 {j.get('sent')} 字节: {bs}")

def cmd_watch(url):
    """轮询各串口缓冲，只打印新增行。靠每行 ts 去重。"""
    seen = {}  # port -> last ts
    print(f"实时跟随 {url} 的串口输出（Ctrl-C 退出）…")
    # 先用当前缓冲初始化 seen，避免一上来刷屏
    init = api_get(url, "/api/ai/observe?n=500")
    for pid, lines in init.get("recent", {}).items():
        if lines:
            seen[pid] = lines[-1].get("ts", 0)
    try:
        while True:
            j = api_get(url, "/api/ai/observe?n=200")
            for pid, lines in j.get("recent", {}).items():
                last = seen.get(pid, 0)
                fresh = [l for l in lines if l.get("ts", 0) > last]
                if fresh:
                    seen[pid] = fresh[-1].get("ts", last)
                    for l in fresh:
                        print(f"[{pid}] {l.get('text','')}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n已停止跟随。")

def main():
    args = sys.argv[1:]
    # --no-start: 只查询，不自动启动工具（用于"工具是否在跑"的纯检测）
    if args and args[0] == "--no-start":
        args = args[1:]
        url, _ = find_endpoint()
        if url is None:
            need_running()
    else:
        # 默认：工具没开就自动启动 exe 并等就绪
        url = ensure_running(auto_start=True)
        if url is None:
            need_running()
    if not args or args[0] in ("overview", "obs", "o", ""):
        cmd_overview(url)
    elif args[0] == "status":
        cmd_status(url)
    elif args[0] == "ports":
        cmd_ports(url)
    elif args[0] == "buf" and len(args) >= 2:
        cmd_buf(url, args[1], int(args[2]) if len(args) > 2 else 50)
    elif args[0] == "recent":
        cmd_recent(url, int(args[1]) if len(args) > 1 else 50)
    elif args[0] == "send" and len(args) >= 3:
        cmd_send(url, args[1], " ".join(args[2:]))
    elif args[0] == "raw" and len(args) >= 3:
        cmd_raw(url, args[1], *args[2:])
    elif args[0] == "watch":
        cmd_watch(url)
    elif args[0] == "start":
        # 显式启动工具（即使已在运行也只聚焦，不报错）
        url = ensure_running(auto_start=True)
        if url:
            print(f"工具已就绪: {url}")
        else:
            need_running()
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
