# -*- coding: utf-8 -*-
"""安装「提交即回归」git hooks（本地开发机，一次安装）。

    python tools/install_regression_hooks.py           # 安装/更新
    python tools/install_regression_hooks.py --remove  # 卸载

hooks：
- post-commit：跑 L0 静态门禁（秒级，零额度）——失败时醒目提示，绝不阻断提交。
- pre-push ：跑 L0 + 尝试 L1/L2（应用未运行时自动 SKIP），失败阻断推送。

设计约束：
- hook 只调用 tests/regression/run_all.py，不复制检查逻辑（单一真源）。
- 已存在非本工具写入的 hook 内容会被保留（追加到末尾）。
- Windows 下 Git Bash 直接执行；行尾强制 LF。
"""
import os
import stat
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".git", "hooks")

HEADER = "# ---- regression hooks (tools/install_regression_hooks.py) ----"

POST_COMMIT = """#!/bin/sh
{header}
# 提交后静态门禁：秒级、零额度、不阻断（结果写本地日志，不弄脏工作区）
cd "$(git rev-parse --show-toplevel)" 2>/dev/null || exit 0
LOG="$HOME/.serialconsole_pro/regression_last.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
if command -v python >/dev/null 2>&1; then PY=python
elif command -v python3 >/dev/null 2>&1; then PY=python3
else exit 0; fi
if ! "$PY" tests/regression/run_all.py --layers L0 --no-report >"$LOG" 2>&1; then
  echo ""
  echo "⚠ [回归] L0 静态门禁失败（见 $LOG）——请立即修复："
  tail -n 20 "$LOG" 2>/dev/null
  echo ""
fi
""".format(header=HEADER)

PRE_PUSH = """#!/bin/sh
{header}
# 推送前：L0 + 尝试 L1/L2（应用未运行自动 SKIP，不会误伤）
cd "$(git rev-parse --show-toplevel)" 2>/dev/null || exit 0
LOG="$HOME/.serialconsole_pro/regression_last.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
if command -v python >/dev/null 2>&1; then PY=python
elif command -v python3 >/dev/null 2>&1; then PY=python3
else exit 0; fi
echo "[回归] pre-push：L0/L1/L2 …"
if ! "$PY" tests/regression/run_all.py --layers L0,L1,L2 --no-report >"$LOG" 2>&1; then
  echo "✖ [回归] 失败，推送已阻断。详情：$LOG"
  tail -n 30 "$LOG" 2>/dev/null
  echo "（确需跳过：git push --no-verify）"
  exit 1
fi
echo "[回归] 通过"
""".format(header=HEADER)


def _write_hook(name, body):
    os.makedirs(HOOKS, exist_ok=True)
    p = os.path.join(HOOKS, name)
    old = ""
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
            old = f.read()
        if HEADER in old:
            # 替换本工具段落（整文件重写：仅保留非本工具内容）
            idx = old.find(HEADER)
            old = old[:idx].rstrip("\n")
            body = old + "\n" + body if old else body
        else:
            body = old.rstrip("\n") + "\n" + body
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def install():
    for name, body in (("post-commit", POST_COMMIT), ("pre-push", PRE_PUSH)):
        print("已写入", _write_hook(name, body))
    print("完成。post-commit=L0；pre-push=L0/L1/L2；日志 ~/.serialconsole_pro/regression_last.log")


def remove():
    for name in ("post-commit", "pre-push"):
        p = os.path.join(HOOKS, name)
        if not os.path.isfile(p):
            continue
        with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
            s = f.read()
        if HEADER in s:
            if s.strip().startswith("#!"):
                head, _, rest = s.partition("\n")
            else:
                head, rest = "", s
            idx = rest.find(HEADER)
            rest = rest[:idx].rstrip("\n")
            if rest.strip():
                with open(p, "w", encoding="utf-8", newline="\n") as f:
                    f.write((head + "\n" if head else "") + rest + "\n")
            else:
                os.remove(p)
            print("已移除", name, "中的回归段落")
    print("完成")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        install()
