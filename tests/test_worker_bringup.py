# -*- coding: utf-8 -*-
"""a668 回归锚：worker 异步拉起的模块级状态必须真的落到位。

事故（用户日志实锤）：manage_start 改成后台线程后，内嵌的 _bring_up
里裸写 `_proc = p` 少了 `global`——赋值只创建局部变量，模块级 _proc 恒
None。supervisor 第一轮（5s 后）读到 None 判「进程死了」，又拉起第二个
worker：13344 与 19792 同时活着，端口/代理/机器人状态全部分裂。

这里不真的拉起子进程：把 _spawn_once/_apply_base/_supervisor 全部换成
假实现，验证 manage_start 返回后模块级 _proc/_last_port/_base 是否正确，
以及「握手期间收到停止请求」时新进程被就位处决。

直接 `py tests/test_worker_bringup.py` 运行（与仓库既有测试同风格）。
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import worker_app as W

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS  %s" % name)
    else:
        _FAIL.append(name)
        print("  FAIL  %s  %s" % (name, detail))


class _FakeProc(object):
    def __init__(self):
        self.killed = False
        self.pid = 4242

    def poll(self):
        return None

    def kill(self):
        self.killed = True


def _patch(proc, port=51000):
    """把拉起链换成假实现，记录 supervisor 是否被启动。"""
    state = {"spawn": 0, "sup": 0}

    def _fake_spawn(prefer_port, ready_timeout=25):
        state["spawn"] += 1
        return proc, port

    def _fake_apply(port_, pid):
        W._base = "http://127.0.0.1:%d" % port_

    def _fake_sup(prefer_port):
        state["sup"] += 1

    W._spawn_once = _fake_spawn
    W._apply_base = _fake_apply
    W._supervisor = _fake_sup
    return state


def main():
    orig = (W._spawn_once, W._apply_base, W._supervisor,
            W._proc, W._last_port, W._base)
    os.environ.pop("CLAUDE_INLINE", None)
    try:
        print("== 1. 异步拉起后模块级状态到位（事故回归）==")
        W._proc = None
        W._last_port = 0
        W._base = ""
        W._stop.clear()
        p1 = _FakeProc()
        st = _patch(p1, 51001)
        W.manage_start(main_port=53000)
        # 后台线程：等握手完成事件
        ok = W._initial_done.wait(5)
        check("握手完成事件置位", ok)
        check("模块级 _proc 已写入（不是 None）", W._proc is p1,
              "实际 %r —— 这正是 2026-11-19 双 worker 事故的根因" % (W._proc,))
        check("_last_port 已写入", W._last_port == 51001, str(W._last_port))
        check("_base 已回填", W._base == "http://127.0.0.1:51001", W._base)
        check("supervisor 只起一个", st["sup"] == 1, str(st))
        check("只拉起一个 worker", st["spawn"] == 1, str(st))

        print("== 2. b 进程未被误杀（supervisor 看到的是活进程）==")
        check("假进程未被 kill", not p1.killed)

        print("== 3. 握手期间收到停止请求 → 就地处决，不留孤儿 ==")
        W._proc = None
        W._last_port = 0
        W._stop.clear()
        p2 = _FakeProc()

        def _slow_spawn(prefer_port, ready_timeout=25):
            # 模拟真实握手窗口：先让 manage_stop 有机会置位 _stop
            W._stop.set()
            return p2, 51002

        st2 = _patch(p2, 51002)
        W._spawn_once = _slow_spawn
        W.manage_start(main_port=53000)
        W._initial_done.wait(5)
        check("停止时新进程被 kill", p2.killed)
        check("停止时模块级 _proc 保持 None", W._proc is None, repr(W._proc))
        check("停止时不启动 supervisor", st2["sup"] == 0, str(st2))
    finally:
        W._stop.clear()
        (W._spawn_once, W._apply_base, W._supervisor,
         W._proc, W._last_port, W._base) = orig

    print("=" * 56)
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    for x in _FAIL:
        print("  -", x)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
