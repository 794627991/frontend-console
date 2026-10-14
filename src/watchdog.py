# -*- coding: utf-8 -*-
"""v3.5.223 请求看门狗（用户实锤：两串口+SSH+后台claude 并发时后端整体
阻塞 150s——send_raw/tftp/sessions 全挂起，关串口才恢复）。

在途请求 >2s 未完成时，自动把**全部线程栈**转储到
~/.serialconsole_pro/watchdog_dump.log（sys._current_frames——无需
py-spy）。诊断基建：下一次复现直接有栈可读，一次定凶。

用法（server.py app 创建后一行）：
    from src.watchdog import install_watchdog
    install_watchdog(app)
"""
import os
import sys
import threading
import time
import traceback

_REQS = {}
_LOCK = threading.Lock()
_LAST = [0.0]
_DUMP = os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                     "watchdog_dump.log")

try:
    from flask import request
except Exception:      # 独立导入失败（非 Flask 环境）——不安装
    request = None


def _before():
    with _LOCK:
        _REQS[threading.get_ident()] = {
            "path": (request.path or "?")[:60], "t0": time.time()}


def _after(resp):
    with _LOCK:
        _REQS.pop(threading.get_ident(), None)
    return resp


def _dump_stacks(slow):
    frames = sys._current_frames()
    lines = ["", "===== WATCHDOG DUMP %s | slow=%d in-flight=%d =====" % (
        time.strftime("%H:%M:%S"), len(slow), len(_REQS))]
    for pth, dt in sorted(slow, key=lambda x: -x[1])[:6]:
        lines.append("  SLOW %6.1fs %s" % (dt, pth))
    for tid, fr in frames.items():
        lines.append("--- thread %x ---" % tid)
        lines.extend("    " + l for l in traceback.format_stack(fr)[-12:])
    try:
        os.makedirs(os.path.dirname(_DUMP), exist_ok=True)
        with open(_DUMP, "a", encoding="utf-8", errors="replace") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _loop():
    while True:
        time.sleep(2)
        try:
            now = time.time()
            with _LOCK:
                slow = [(r["path"], now - r["t0"])
                        for r in _REQS.values() if now - r["t0"] > 2.0]
            # C组G2：老化剔除——请求线程异常死亡（after 未跑）的条目永驻
            # 会让 slow 恒真 → 无限幻影转储；>600s 的条目直接清
            with _LOCK:
                for k in list(_REQS):
                    if now - _REQS[k]["t0"] > 600:
                        del _REQS[k]
            if not slow:
                continue
            if now - _LAST[0] < 10:      # 10s 频控（持续卡顿防日志爆炸）
                continue
            _LAST[0] = now
            _dump_stacks(slow)
        except Exception:
            pass


def install_watchdog(app):
    if request is None:
        return
    app.before_request(_before)
    app.after_request(_after)
    threading.Thread(target=_loop, daemon=True).start()
