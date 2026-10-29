# -*- coding: utf-8 -*-
"""启动资源闸门（v4.1，用户拍板）。

背景（用户需求）：WebView2 运行时从发布包里挪进离线资源包——发布包
318MB → 65MB。代价是「干净机器上必须先装资源包才能用」，所以启动前
必须先检测，缺了引导用户装包。

硬拦（不满足直接拦在窗口创建前，因为根本建不出窗口）：
- WebView2 运行时：系统 Evergreen ≥109 就算满足（用户拍板）；否则要
  offline_runtime 里解包出来的 Fixed Version
- .NET Framework 4.8+（Release ≥ 528372）：pywebview 的 WebView2 后端
  走 pythonnet，.NET 缺/过低时 `import webview` 本身就抛异常——它比
  WebView2 更早崩，所以同属硬拦（用户拍板纳入）

软提示（启动后再提示，不锁死工具——串口等核心功能与它们无关）：
- Node.js / npm、Git、Claude Code CLI、工具自身 pydeps

界面约束（关键）：WebView2 缺失时 pywebview 建不了任何窗口，tkinter
又没打进发布包，所以引导只能用 Win32 原生：MessageBoxW 提问 +
GetOpenFileNameW 选包 + IProgressDialog 进度条。三条 API 本项目已有
先例（deps_bootstrap 的 MessageBoxW、tray.py 的 Win32 窗口、
main.py:926 的 64 位句柄显式声明——新写的 ctypes 封装必须照抄那个教训：
**指针参数不显式声明 argtypes 在 64 位下会静默截断**）。

纯探测逻辑（probe_*）不碰 UI，可单测；UI 只在 preflight_gate 里用。
"""
import json
import os
import shutil
import struct
import subprocess
import sys

from src import app_state as _st

# 最低可接受版本（用户拍板：系统 Evergreen ≥109 就算满足；:has() /
# content-visibility 全覆盖的最低线，与 main._WV2_MIN 同口径）
WV2_MIN = (109, 0, 1518, 0)
NETFX_MIN_RELEASE = 528372      # .NET Framework 4.8 / 4.8.1 的已知可用下限
_WV2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# 统一资源清单（唯一真源：后端探测、前端呈现、离线包表三者同口径）
MANIFEST = [
    {"kind": "webview2", "name": "WebView2 运行时", "hard": True,
     "fix": "离线资源包内解出（无需管理员）"},
    # C3（全审）：阈值取 528372（.NET 4.8）而不是 533320（4.8.1）——4.8 已足够
    # 跑 pythonnet，且 Win10 21H2+ 自带 4.8 可免装。名称随之写 4.8+，不叫
    # 「4.8.1」以免与阈值口径打架。
    {"kind": "dotnet", "name": ".NET Framework 4.8+", "hard": True,
     "fix": "离线资源包内安装器（需管理员，装完可能要重启）"},
    {"kind": "node", "name": "Node.js / npm", "hard": False,
     "fix": "离线资源包内静默安装"},
    {"kind": "git", "name": "Git", "hard": False,
     "fix": "离线资源包内静默安装"},
    {"kind": "claude", "name": "Claude Code CLI", "hard": False,
     "fix": "离线资源包内复制安装"},
    {"kind": "pydeps", "name": "工具 Python 依赖", "hard": False,
     "fix": "离线资源包内 wheel 补装"},
]


def app_dir():
    """工具根目录（frozen=exe 所在目录；源码=项目根）。
    与 claude_setup._app_dir 同口径，但本模块必须在 server 未起来时也能用，
    所以不 import 那个模块（避免拉进 flask 依赖链）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------- 探测

def _fixed_ver(fixed_dir):
    """从 Fixed Version 运行时目录名抽版本：
    Microsoft.WebView2.FixedVersionRuntime.133.0.3065.92.x64 → 133.0.3065.92"""
    import re
    name = os.path.basename(fixed_dir.rstrip("\\/"))
    m = re.search(r"FixedVersionRuntime[.\-_](\d+(?:\.\d+)+)", name)
    if m:
        return m.group(1)
    m = re.search(r"(\d+(?:\.\d+){2,})", name)
    return m.group(1) if m else name


def probe_webview2():
    """→ (state, ver, detail)。state ∈ ok / missing / outdated。
    先看系统 Evergreen，再看资源包解出的 Fixed Version。"""
    pv = _wv2_system_version()
    if pv and _ver_tuple(pv) >= WV2_MIN:
        return "ok", pv, "系统 Evergreen"
    fixed = wv2_fixed_dir()
    if fixed:
        # C5（全审）：早前取 dirname(fixed) 的 basename，得到的是上层目录名
        # `webview2`（前端显示「WebView2 运行时 webview2」）。fixed 本身就是
        # 版本目录 Microsoft.WebView2.FixedVersionRuntime.<ver>.x64，从它抽版本。
        v = _fixed_ver(fixed)
        return "ok", v, "离线包运行时"
    if pv:
        return "outdated", pv, "系统版本过低（需 ≥%s）" % ".".join(map(str, WV2_MIN))
    return "missing", "", "系统未安装，资源包也未解出"


def _wv2_system_version():
    """注册表探测系统 Evergreen WebView2（HKLM/HKCU × 32/64 视图全扫）。"""
    try:
        import winreg
    except ImportError:
        return ""
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for wow in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(
                        root,
                        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\\" + _WV2_GUID,
                        0, winreg.KEY_READ | wow) as k:
                    return str(winreg.QueryValueEx(k, "pv")[0] or "")
            except OSError:
                continue
    return ""


def _ver_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split(".") if x.isdigit())
    except Exception:
        return ()


def wv2_fixed_dir():
    """找「可用的 WebView2 运行时目录」（含 msedgewebview2.exe 的那层）。

    探测顺序（重要——新包解出的要优先于旧的随包 runtime，否则升级早期
    两处并存时会用旧版）：
      1. <app>/offline_runtime/webview2/**      v4.1 资源包解出的
      2. <app>/runtime/WebView2Fixed/**          v2.3.7~v2.4.0 随包的
      3. 上一级目录下的同名两处（onedir 形态兜底）
    """
    import glob as _gl
    base = app_dir()
    roots = [os.path.join(base, "offline_runtime", "webview2"),
             os.path.join(base, "runtime", "WebView2Fixed"),
             os.path.join(base, "runtime"),
             os.path.join(os.path.dirname(base), "offline_runtime", "webview2"),
             os.path.join(os.path.dirname(base), "runtime", "WebView2Fixed")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for depth in range(1, 6):       # offline_runtime/webview2/<ver>/x.exe = 3 层
            hit = sorted(_gl.glob(os.path.join(
                root, *(["*"] * depth), "msedgewebview2.exe")))
            if hit:
                return os.path.dirname(hit[0])
    return ""


def probe_dotnet():
    """→ (state, ver, detail)。查 .NET Framework v4 Full 的 Release 值。"""
    try:
        import winreg
    except ImportError:
        return "unknown", "", "非 Windows，跳过"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(
                    root,
                    r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as k:
                rel = int(winreg.QueryValueEx(k, "Release")[0])
                if rel >= NETFX_MIN_RELEASE:
                    # 4.8 = 528040 / 4.8.1 = 533320 及以上（阈值 528372 见上）
                    ver = "4.8.1" if rel >= 533320 else "4.8"
                    return "ok", ver, "Release %d" % rel
                return "outdated", str(rel), "Release %d < %d" % (
                    rel, NETFX_MIN_RELEASE)
        except OSError:
            continue
    return "missing", "", "未安装 .NET Framework 4.8+"


def _which(name):
    return shutil.which(name) or ""


def probe_node():
    node = _which("node.exe") or _which("node")
    npm = _which("npm.cmd") or _which("npm")
    if node and npm:
        return "ok", _run_ver([node, "--version"]), ""
    return "missing", "", "" if not node else "缺 npm"


def probe_git():
    g = _which("git.exe") or _which("git")
    if g:
        return "ok", _run_ver([g, "--version"]), ""
    return "missing", "", ""


def probe_claude():
    try:
        from .claude_conn import _resolve_claude_exe, ClaudeNotFoundError
        exe, _shim = _resolve_claude_exe()
        return "ok", _run_ver([exe, "--version"]), ""
    except Exception:
        return "missing", "", ""


def probe_pydeps():
    """工具自身 pip 依赖：只测发布包里也可能缺的那几个（exe 分发恒 ok）。"""
    need = [("paramiko", "SSH"), ("winpty", "内嵌终端")]
    miss = []
    for mod, _desc in need:
        try:
            __import__(mod)
        except ImportError:
            miss.append(mod)
    if miss:
        return "missing", "", "缺 " + "/".join(miss)
    return "ok", "", ""


_PROBES = {"webview2": probe_webview2, "dotnet": probe_dotnet,
           "node": probe_node, "git": probe_git, "claude": probe_claude,
           "pydeps": probe_pydeps}


def _run_ver(argv, timeout=8):
    """跑一次 --version 取版本串。超时/失败返回空（探测失败≠缺失）。"""
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip().splitlines()
        if not out:
            return ""
        # "git version 2.55.0" → 2.55.0；"v24.19.0" → 24.19.0
        import re
        m = re.search(r"\d+\.\d+(?:\.\d+)?", out[0])
        return m.group(0) if m else out[0][:40]
    except Exception:
        return ""


def probe_all(use_cache=True):
    """统一检测入口。返回
        {"ok": bool, "items": [...], "hard_missing": [...], "soft_missing": [...]}
    每项：{kind, name, hard, ok, state, ver, detail, fix}
    """
    state_file = _state_file()
    cache = _read_state() if use_cache else {}
    cached = (cache.get("last_probe") or {}) if use_cache else {}
    items, hard_miss, soft_miss = [], [], []
    for m in MANIFEST:
        k = m["kind"]
        c = cached.get(k)
        if c and time_ok(c.get("ts")):
            st, ver, detail = c["state"], c.get("ver", ""), c.get("detail", "")
        else:
            try:
                st, ver, detail = _PROBES[k]()
            except Exception as e:
                st, ver, detail = "unknown", "", str(e)[:80]
            cached[k] = {"state": st, "ver": ver, "detail": detail,
                         "ts": _now()}
        ok = st == "ok"
        items.append({"kind": k, "name": m["name"], "hard": m["hard"],
                      "ok": ok, "state": st, "ver": ver, "detail": detail,
                      "fix": m["fix"]})
        if not ok:
            (hard_miss if m["hard"] else soft_miss).append(k)
    if use_cache:
        _write_state({"last_probe": cached})
    return {"ok": not hard_miss, "items": items,
            "hard_missing": hard_miss, "soft_missing": soft_miss}


_PROBE_TTL = 60     # 探测结果缓存 60s——前端轮询不重复起子进程


def time_ok(ts):
    import datetime
    try:
        t = datetime.datetime.fromisoformat(ts)
        return (datetime.datetime.now() - t).total_seconds() < _PROBE_TTL
    except Exception:
        return False


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _state_file():
    return os.path.join(app_dir(), "offline_runtime", ".fcpk.json")


def _read_state():
    try:
        with open(_state_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_state(d):
    """合并写（只覆盖给定键，别把已装清单抹掉）。"""
    cur = _read_state()
    cur.update(d or {})
    p = _state_file()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        pass


# --------------------------------------------------------------------- 闸门

def preflight_gate(force=False):
    """启动硬闸门。返回 True=放行，False=用户取消/安装失败应退出。

    必须在 `import webview` 之前调用（.NET 缺失时那一步就崩）。
    已在 app_dir 落过 .fcpk.json 且探测通过 → 零开销直接放行。

    force=True 走「测试模式」：环境变量 FC_FORCE_MISSING 可强制把指定
    kind 判成缺失（本机 WebView2/.NET 都齐全时，用它验证引导链路）。
    """
    res = probe_all(use_cache=False)
    forced = [x.strip() for x in
              (os.environ.get("FC_FORCE_MISSING") or "").split(",") if x.strip()]
    if forced:
        for it in res["items"]:
            if it["kind"] in forced:
                it.update(ok=False, state="missing",
                          detail="[测试模式强制]")
        res["hard_missing"] = [i["kind"] for i in res["items"]
                               if i["hard"] and not i["ok"]]
    if not res["hard_missing"]:
        return True
    return _guide_install(res)


def _guide_install(res):
    """缺硬性资源 → 原生引导：说明 → 选包 → 进度 → 重启。"""
    from src import res_ui

    names = "、".join(it["name"] for it in res["items"]
                     if it["kind"] in res["hard_missing"])
    txt = ("缺少运行环境：%s\n\n"
           "工具无法启动。请准备好离线资源包（.fcpk 文件），点「确定」选择它，"
           "工具会自动安装后重启。\n\n"
           "点「取消」退出。" % names)
    if res_ui.msgbox(txt, "前端控制台 · 缺少运行环境",
                     res_ui.MB_OKCANCEL | res_ui.MB_ICONWARNING
                     | res_ui.MB_SETFOREGROUND | res_ui.MB_TOPMOST) != res_ui.IDOK:
        return False

    path = res_ui.pick_fcpk()
    if not path:
        # 对话框不可用/取消 → 兜底自动找
        path = res_ui.autofind_fcpk()
        if not path:
            res_ui.msgbox("没有选择资源包，工具无法启动。\n\n请把 .fcpk 资源包"
                          "放在工具目录或桌面后重新打开工具。",
                          "前端控制台", res_ui.MB_OK | res_ui.MB_ICONERROR)
            return False
        if res_ui.msgbox("未手动选择，已自动使用：\n%s\n\n继续安装？" % path,
                         "前端控制台", res_ui.MB_YESNO | res_ui.MB_ICONWARNING
                         ) != res_ui.IDYES:
            return False

    from src import fcpk
    if not fcpk.is_fcpk(path):
        res_ui.msgbox("选中的不是资源包（%s）。\n\n请选择 .fcpk 文件。"
                      % os.path.basename(path),
                      "前端控制台", res_ui.MB_OK | res_ui.MB_ICONERROR)
        return False
    info = fcpk.inspect(path)
    if not info.get("ok"):
        res_ui.msgbox("资源包有问题：%s" % (info.get("err") or "无法读取"),
                      "前端控制台", res_ui.MB_OK | res_ui.MB_ICONERROR)
        return False

    ok = _run_install_with_ui(path)
    if not ok:
        return False
    res_ui.msgbox("运行环境安装完成，正在重新启动工具…", "前端控制台",
                  res_ui.MB_OK | res_ui.MB_ICONINFORMATION)
    _restart_self()
    return False        # 本进程退出


def _run_install_with_ui(path):
    """解包安装 + 进度条。返回 bool。失败弹窗给日志路径。"""
    import threading
    from src import res_ui, res_install

    from src.res_boot import MANIFEST
    need = [m["kind"] for m in MANIFEST if m["hard"]]
    log_lines = []
    state = {"done": False, "ok": False, "err": ""}

    def log(msg):
        log_lines.append(str(msg))

    cancel = {"req": False}

    def work():
        pg = None
        try:
            pg = res_ui.progress("前端控制台 · 正在安装运行环境")

            def prog(done, total, label):
                if pg:
                    pg.set_progress(done, total or 1)
                    if label:
                        pg.set_line("正在安装：" + os.path.basename(label), 1)

            # 全审 C1：早前「取消」按钮完全没接线——用户点了取消安装照跑，
            # 装完还自动重启。这里把 IProgressDialog.HasUserCancelled 接到
            # install_from 的 should_cancel 上，每个 kind / 解包块之间检查。
            def should_cancel():
                if pg and pg.cancelled():
                    cancel["req"] = True
                return cancel["req"]

            res = res_install.install_from(path, kinds=need, log=log,
                                           progress=prog,
                                           should_cancel=should_cancel)
            errs = res.get("errors") or {}
            state["ok"] = not errs
            state["err"] = "; ".join("%s: %s" % kv for kv in errs.items())
            state["res"] = res
        except res_install.InstallCancelled:
            state["ok"] = False
            state["cancelled"] = True
            state["err"] = "已取消安装"
            log("用户取消安装")
        except Exception as e:
            state["ok"] = False
            state["err"] = str(e)[:400]
            log("失败：%s" % e)
        finally:
            if pg:
                pg.stop()
            state["done"] = True

    th = threading.Thread(target=work, daemon=False)
    th.start()
    while th.is_alive():
        th.join(0.3)
    # 写日志备查（失败时告诉用户路径）
    log_path = os.path.join(os.environ.get("TEMP", "."), "fcpk_install.log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
    except OSError:
        pass
    if state.get("cancelled"):
        res_ui.msgbox("已取消安装。\n\n工具缺少必需运行环境，无法启动。\n"
                      "双击工具后重新选择资源包即可继续。",
                      "前端控制台", res_ui.MB_OK | res_ui.MB_ICONWARNING)
    elif not state["ok"]:
        res_ui.msgbox("安装未完全成功：\n%s\n\n详细日志：%s\n\n"
                      "可重启工具后再次选择资源包重试。"
                      % (state["err"] or "未知错误", log_path),
                      "前端控制台", res_ui.MB_OK | res_ui.MB_ICONERROR)
    return bool(state["ok"])


def _restart_self():
    """拉起新进程后本进程退出。

    全审 C2 实锤：早前用 `[sys.executable, "-c", code, exe, ...]` 想让
    「子进程先睡 1.5s 再拉起」——但 frozen 下 sys.executable 是 exe 本身，
    `-c` 只是普通命令行参数，exe 收到会当未知参数忽略并**立刻**启动，
    睡 1.5s 的助手脚本从不执行。实际靠父进程 CloseHandle(mutex) 后 0.2s
    退出与子进程竞速，多数能赢但无保证。

    改成：写一个 .bat 延迟拉起（cmd 的 timeout 可靠），然后释放 mutex 退出。
    """
    import subprocess
    import tempfile
    import time
    rel_args = sys.argv[1:]
    try:
        bat = os.path.join(tempfile.gettempdir(),
                           "fcpk_restart_%d.bat" % os.getpid())
        lines = ["@echo off",
                 "timeout /t 2 /nobreak >nul",
                 'start "" "%s"%s' % (
                     sys.executable,
                     "".join(' "%s"' % a for a in rel_args)),
                 'del "%~f0"']
        with open(bat, "w", encoding="mbcs", errors="replace") as f:
            f.write("\r\n".join(lines) + "\r\n")
        subprocess.Popen([bat], shell=True,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    try:
        import src.main as _m
        mut = getattr(_m, "mutex", None)
        if mut:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(mut)
    except Exception:
        pass
    time.sleep(0.2)
    os._exit(0)


def soft_report():
    """软资源缺失时的状态缓存（前端启动后 GET /api/resources/status 读）。
    不做任何 UI——前端负责呈现常驻红条。"""
    try:
        return probe_all(use_cache=True)
    except Exception:
        return {"ok": True, "items": [], "hard_missing": [], "soft_missing": []}
