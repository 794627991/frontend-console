# -*- coding: utf-8 -*-
"""无人值守安全重启前端控制台（工具进程 + HikLink bot 通道）。

由 WMI 独立进程运行（与工具进程树解耦，杀工具不影响本脚本）：
  等 45s（等最后一条回复推送完成）→ 精确杀工具主进程 → 分离启动 →
  轮询 hiklink_bot.log 出现「认证成功」（bot 自启=claude 通道就绪）→
  失败自动重试（共 3 次）。全程写 restart_tool_result.txt。

claude 会话连续性：重启后首条消息经 harness meta（claude_harness.json）
--resume 原 session_id，上下文不丢。
"""
import os
import re
import subprocess
import sys
import time

PYW = r"C:\Users\gaoyi13\AppData\Local\Programs\Python\Python314\pythonw.exe"
TOOL_DIR = r"D:\AI\串口控制台Pro"
MAIN_PY = os.path.join(TOOL_DIR, "src", "main.py")
BOT_LOG = r"D:\Frontend Console\hiklink_bot.log"
RESULT = r"C:\Users\gaoyi13\AppData\Local\Temp\restart_tool_result.txt"
DELAY_FIRST = 45      # 触发后先等这么久（最后回复推送出去）
AUTH_TIMEOUT = 90     # 每次启动后等 bot 认证的上限
ATTEMPTS = 3


def note(msg):
    with open(RESULT, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))


def find_tool_pid():
    r"""精确找工具主进程：pythonw.exe 且命令行含 src\main.py。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='pythonw.exe'",
             "get", "CommandLine,ProcessId", "/format:csv"],
            capture_output=True, text=True, timeout=20).stdout
    except Exception as e:
        note("wmic 查询失败: %s" % e)
        return None
    for line in out.splitlines():
        if "main.py" not in line:
            continue
        m = re.search(r"(\d+)\s*$", line)
        if m:
            return int(m.group(1))
    return None


def wait_auth(since, timeout=AUTH_TIMEOUT):
    """bot 日志 since 之后出现「认证成功」即认定 claude 通道就绪。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with open(BOT_LOG, encoding="utf-8", errors="replace") as f:
                f.seek(since)
                if "认证成功" in f.read():
                    return True
        except OSError:
            pass
        time.sleep(3)
    return False


def main():
    note("=== 重启流程启动（等 %ds 让最后回复推送完成）===" % DELAY_FIRST)
    time.sleep(DELAY_FIRST)
    for attempt in range(1, ATTEMPTS + 1):
        pid = find_tool_pid()
        note("第 %d/%d 次：工具 PID=%s" % (attempt, ATTEMPTS, pid))
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True)
            time.sleep(5)
        since = os.path.getsize(BOT_LOG) if os.path.isfile(BOT_LOG) else 0
        try:
            subprocess.Popen(
                [PYW, MAIN_PY], cwd=TOOL_DIR,
                creationflags=subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)
        except Exception as e:
            note("启动失败: %s" % e)
            continue
        note("工具已启动，等待 HikLink bot 认证（≤%ds）…" % AUTH_TIMEOUT)
        if wait_auth(since):
            note("RESULT: OK — 工具已重启，bot 认证成功（claude 通道就绪，"
                 "首条消息将 resume 原会话）")
            return
        note("超时未见认证成功")
    note("RESULT: FAIL — %d 次尝试均未通过，需人工介入" % ATTEMPTS)


if __name__ == "__main__":
    main()
