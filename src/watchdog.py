# -*- coding: utf-8 -*-
"""v3.5.223 请求看门狗（用户实锤：两串口+SSH+后台claude 并发时后端整体
阻塞 150s——send_raw/tftp/sessions 全挂起，关串口才恢复）。

在途请求 >5s 未完成时，自动把**全部线程栈**转储到
~/.serialconsole_pro/watchdog_dump.log（sys._current_frames——无需
py-spy）。

v3.5.289（用户需求「不仅记录，还要能打断阻塞」）：同一请求持续超
15s 时向其线程注入 WatchdogInterrupt 异常——**纯 Python 阻塞**（死锁/
死循环/锁竞争）在下次字节码边界抛出，请求立即 500 返回（前端收到
错误而非干等）；**C 级系统调用阻塞**（subprocess 等待/socket recv，
GIL 已释放）注入不生效——那类由各端点自身超时兜底（如 vcs 的
20s/90s 超时即 kill 子进程）。每请求只注入一次，防异常循环。

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
            "path": (request.path or "?")[:60], "t0": time.time(),
            "interrupted": False}


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
        # v3.5.288（卡死报告 §6.3）：滚动上限——超 10MB 截半（单文件无限
        # 追加一天 3.6MB，长跑机器失控）
        if os.path.exists(_DUMP) and os.path.getsize(_DUMP) > 10 * 1024 * 1024:
            with open(_DUMP, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read()[5 * 1024 * 1024:]
            with open(_DUMP + ".tmp", "w", encoding="utf-8", errors="replace") as f:
                f.write(tail)
            os.replace(_DUMP + ".tmp", _DUMP)
        with open(_DUMP, "a", encoding="utf-8", errors="replace") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


class WatchdogInterrupt(Exception):
    """v3.5.289：看门狗注入的长阻塞打断异常（>15s 的请求线程）。"""


def _interrupt(tid, path, dt):
    """向阻塞请求线程注入异步异常。返回是否已注入（幂等：_REQS 打标）。"""
    import ctypes
    r = _REQS.get(tid)
    if not r or r.get("interrupted"):
        return False
    r["interrupted"] = True
    # 目标线程下次执行 Python 字节码时抛出；卡在 C 调用里则挂起至其返回
    ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(tid), ctypes.py_object(WatchdogInterrupt))
    try:
        with open(_DUMP, "a", encoding="utf-8", errors="replace") as f:
            f.write("WATCHDOG INTERRUPT %.1fs %s (tid=%x)\n" % (dt, path, tid))
    except Exception:
        pass
    return True


def _loop():
    while True:
        time.sleep(2)
        try:
            now = time.time()
            with _LOCK:
                slow = [(r["path"], now - r["t0"])
                        for r in _REQS.values() if now - r["t0"] > 5.0]   # v3.5.288: 2s被常态慢请求误报(全天320次转储),5s只抓真卡顿
            # C组G2：老化剔除——请求线程异常死亡（after 未跑）的条目永驻
            # 会让 slow 恒真 → 无限幻影转储；>600s 的条目直接清
            with _LOCK:
                for k in list(_REQS):
                    if now - _REQS[k]["t0"] > 600:
                        del _REQS[k]
            if not slow:
                continue
            # v3.5.289：>15s 的在途请求注入打断（每请求一次；纯 Python 阻塞
            # 立抛，C 级阻塞不生效由端点超时兜底）
            for tid2, dt2 in slow:
                if dt2 > 15.0:
                    try:
                        _interrupt(tid2, *_REQS[tid2]["path"] and (_REQS[tid2]["path"], dt2))
                    except Exception:
                        pass
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
