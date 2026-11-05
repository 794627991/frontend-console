# -*- coding: utf-8 -*-
"""CPU 优先提升（用户需求：工具抢占更多 CPU 获得更强性能）。

两件事（都可独立开关）：
1. 进程优先级：本工具 python 主进程 + 全部 WebView2 子进程（renderer/GPU）
   提到 AboveNormal/High——CPU 满载争抢时分到更多时间片（编译/虚拟机
   并行时界面不被挤压）。Realtime 绝不提供（会饿死系统进程）。
2. 电源计划：切 Windows 高性能计划（消除省电降频的间歇慢）——改的是
   系统全局，退出/关闭时还原原计划。

实现：PowerShell 一次调用全提（不引入 psutil 依赖）；webview 子进程组
随工具启动固定，但崩溃重启会出新进程——低频重刷兜底。配置存
config.json 的 boost 键，启动时若开启则应用。
"""
import os
import subprocess
import threading
import time

# 档位白名单（PowerShell PriorityClass 名）
_LEVELS = ("above_normal", "high")
_PS_NAME = {"above_normal": "AboveNormal", "high": "High", "normal": "Normal"}
# Windows 内置电源计划 GUID（高性能/平衡）——机器可能删过高性能（返回码非 0
# 即跳过并在日志说明）
_SCHEME_HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_SCHEME_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"

_refresh_timer = None
_prev_scheme = None     # 切换前记住的原计划（还原用）


def _ps(script, timeout=30):
    """跑 PowerShell（隐藏窗口；失败静默——提升是尽力而为不是命脉）"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, str(e)


def _apply_priority(level):
    ps_level = _PS_NAME.get(level, "AboveNormal")
    # 主进程（自身）+ 全部 webview2 子进程一次提
    ok1, _ = _ps("$p = Get-Process -Id %d -ErrorAction SilentlyContinue; "
                 "if ($p) { $p.PriorityClass = '%s' }" % (os.getpid(), ps_level))
    ok2, out2 = _ps("Get-Process msedgewebview2 -ErrorAction SilentlyContinue | "
                    "ForEach-Object { try { $_.PriorityClass = '%s' } catch {} }; "
                    "(Get-Process msedgewebview2 -ErrorAction SilentlyContinue).Count" % ps_level)
    n = (out2 or "").strip().splitlines()[-1] if ok2 else "?"
    return ok1 and ok2, n


def _apply_power(on):
    global _prev_scheme
    if on:
        # 记住当前计划（只记一次）。R24-5：还原成功后清空 _prev_scheme
        # ——下次开启重记（否则二次开启不重记当前，退出还原覆盖用户
        # 中途手动切换的计划）
        if _prev_scheme is None:
            ok, out = _ps("(powercfg /getactivescheme) -replace '.*GUID: ([0-9a-f-]+).*','$1'")
            g = (out or "").strip().splitlines()
            _prev_scheme = g[-1] if g and len(g[-1]) == 36 else _SCHEME_BALANCED
        ok, _ = _ps("powercfg /setactive %s" % _SCHEME_HIGH)
        return ok
    # 还原
    target = _prev_scheme or _SCHEME_BALANCED
    ok, _ = _ps("powercfg /setactive %s" % target)
    if ok:
        _prev_scheme = None   # R24-5：还原即忘——下轮开启重记真实现值
    return ok


def _log(msg):
    print("[boost] " + msg)


# R24-2（实锤：重刷循环无代际检查）：快速开关/切档时旧循环体的 Timer
# cancel 已无效（已触发）→ 复活/双循环互踩。代际计数：apply 自增捕获，
# 循环体醒来发现代际不符即自灭（不再起新 timer）。
_gen = 0
_boost_lock = threading.Lock()


def apply(level="above_normal", power_plan=False, quiet=False):
    """应用提升设置。level ∈ above_normal|high|normal(=全还原)"""
    global _refresh_timer, _gen
    with _boost_lock:
        _gen += 1
        my_gen = _gen
        stop()
        if level in _LEVELS:
            ok, n = _apply_priority(level)
            if not quiet:
                _log("优先级 %s → python+webview2×%s %s"
                     % (level, n, "✓" if ok else "✗"))
            if power_plan:
                okp = _apply_power(True)
                if not quiet:
                    _log("电源计划 → 高性能 %s" % ("✓" if okp else "✗（本机无此计划）"))
            # 低频重刷：webview2 子进程崩溃重启后新进程回到 Normal——60s 兜底
            _refresh_timer = threading.Timer(60.0, _refresh_loop,
                                             args=(my_gen, level, power_plan))
            _refresh_timer.daemon = True
            _refresh_timer.start()
        elif level == "normal":
            _apply_priority("normal")
            # R24-1（高，实锤：关档勾选复选框真切电源计划）：normal 分支
            # 只还原"工具自己切过的"（_prev_scheme 非 None）——power_plan
            # 参数此处无意义（关档下勾选只是记状态，不生效不切）
            if _prev_scheme is not None:
                _apply_power(False)
            if not quiet:
                _log("已还原 Normal/原电源计划")


def _refresh_loop(my_gen, level, power_plan):
    global _refresh_timer
    if my_gen != _gen:
        return   # 旧代际自灭：不再刷也不再起新 timer
    # R25-1（实锤：loop 的优先级刷在锁外，与 apply 关档并发无互斥——
    # 打桩定向复现旧档尾刷落在 Normal 之后残留）：双查+刷优先全部入锁，
    # 与 apply 串行化
    with _boost_lock:
        if my_gen != _gen:
            return
        _apply_priority(level)   # 静默重刷（新 webview2 进程补提）
        # R24-2 补刀：_apply_priority 期间（秒级 PowerShell）可能已有新
        # apply 进来（代际已变）——起下一拍前**再查一次**，否则旧循环复活
        if my_gen != _gen:
            return
        _refresh_timer = threading.Timer(60.0, _refresh_loop,
                                         args=(my_gen, level, power_plan))
        _refresh_timer.daemon = True
        _refresh_timer.start()


def stop():
    """停掉重刷循环（退出/切换时）"""
    global _refresh_timer
    if _refresh_timer:
        _refresh_timer.cancel()
        _refresh_timer = None


def restore_and_exit():
    """进程退出钩子：还原电源计划（优先级随进程消亡自动回收，无需还原）"""
    stop()
    if _prev_scheme is not None:
        _apply_power(False)


def boot_from_config():
    """启动时按 config 应用（main.py 调用）"""
    try:
        from src.app_state import _load_config
        b = _load_config().get("boost") or {}
        lv = str(b.get("level") or "normal")
        pp = bool(b.get("power_plan"))
        if lv in _LEVELS or pp:
            apply(lv, pp, quiet=True)
            _log("启动应用：level=%s power=%s" % (lv, pp))
    except Exception:
        pass
