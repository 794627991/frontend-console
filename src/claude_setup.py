# -*- coding: utf-8 -*-
"""Claude CLI 安装引导（联网 / 离线双通道）。

首次打开 Claude 检测不到 CLI 时，前端弹安装引导窗：
- 联网通道：npm install -g @anthropic-ai/claude-code（需要 node/npm）
- 离线通道：制作整合包（Git 安装器 + Node MSI + %APPDATA%\\npm 里的
  claude-code 目录打包成 zip），无网机器上解包静默装。

安全/边界：安装器只写 HKCU PATH（与 file_assoc 同一约束），MSI/EXE
静默参数全部走官方 documented 开关，绝不碰 pythonw（铁律3）。
"""
import glob
import json
import os
import shutil
import subprocess
import threading
import time
import zipfile

from flask import Blueprint, jsonify, request

from .claude_conn import _resolve_claude_exe, ClaudeNotFoundError

claude_setup_bp = Blueprint("claude_setup", __name__)

# 安装任务状态（单例：同一时刻只允许一个安装/打包任务在跑）
_setup_lock = threading.Lock()
_setup_state = {"running": False, "phase": "", "log": [], "done": False, "ok": False,
                "err": "", "ts": 0}


def _log(msg):
    _setup_state["log"].append({"t": time.time(), "msg": str(msg)})
    if len(_setup_state["log"]) > 500:
        del _setup_state["log"][:-500]


# ---- 资源探测 ----

# 离线资源默认搜索位：D:\\AI\\安装环境（用户装机资源目录）+ 工具旁 offline_pkg/
_ENV_DIRS = [r"D:\AI\安装环境"]


def _find_installer(pattern, extra_dirs=None):
    """按 glob 找安装器（Git exe / Node msi）。返回绝对路径或 None。"""
    dirs = list(_ENV_DIRS) + list(extra_dirs or [])
    # 工具所在盘的 \\AI\\安装环境 也试一次（换机器盘符不定）
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(os.path.splitdrive(app_dir)[0] + os.sep,
                             "AI", "安装环境"))
    dirs.append(os.path.join(app_dir, "offline_pkg"))
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, pattern)):
            if os.path.isfile(f):
                return f
    return None


def _claude_pkg_dir():
    """本机 npm 全局包里的 claude-code 目录（打包源）。"""
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None
    p = os.path.join(appdata, "npm", "node_modules", "@anthropic-ai", "claude-code")
    return p if os.path.isdir(p) else None


def _node_ok():
    """node/npm 可用性：返回 (node_path, npm_cmd_path)。"""
    node = shutil.which("node.exe") or shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        # PATH 缺 npm 目录的兜底（claude_conn 同款坑）
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            nb = os.path.join(appdata, "npm")
            for cand in ("npm.cmd", "npm"):
                p = os.path.join(nb, cand)
                if os.path.isfile(p):
                    npm = p
                    break
    return (node, npm)


def _git_ok():
    return shutil.which("git.exe") or shutil.which("git")


@claude_setup_bp.route("/api/claude/setup_status")
def claude_setup_status():
    """检测四件套：claude CLI / node+npm / git / 离线资源（打包源 + 安装器）。"""
    try:
        _resolve_claude_exe()
        claude = True
    except ClaudeNotFoundError:
        claude = False
    node, npm = _node_ok()
    pkg = _claude_pkg_dir()
    size = 0
    if pkg:
        for root, _dirs, files in os.walk(pkg):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return jsonify({
        "ok": True,
        "claude": claude,
        "node": bool(node), "npm": bool(npm),
        "git": bool(_git_ok()),
        "pkg_dir": pkg or "", "pkg_size": size,
        "git_installer": _find_installer("Git-*.exe") or "",
        "node_installer": _find_installer("node-v*.msi") or "",
    })


# ---- 状态轮询 ----

@claude_setup_bp.route("/api/claude/setup_poll")
def claude_setup_poll():
    with _setup_lock:
        return jsonify({"ok": True, **{k: v for k, v in _setup_state.items()}})


# ---- 制作离线整合包 ----

@claude_setup_bp.route("/api/claude/setup_offline_pack", methods=["POST"])
def claude_setup_offline_pack():
    """把 Git 安装器 + Node MSI + claude-code 目录打成 zip。
    body: {out_dir} —— zip 输出目录（前端弹原生目录选择）。
    包结构：claude-offline.zip
      ├ Git-*.exe  ├ node-v*.msi
      └ claude-code/            （npm 包目录原样，含 bin/claude.exe）
    """
    data = request.get_json(force=True, silent=True) or {}
    out_dir = (data.get("out_dir") or "").strip() or os.path.join(
        os.path.expanduser("~"), "Desktop")
    with _setup_lock:
        if _setup_state["running"]:
            return jsonify({"ok": False, "err": "已有任务在运行"}), 409
        _setup_state.update(running=True, phase="打包离线资源", log=[], done=False,
                            ok=False, err="", ts=time.time())
    def work():
        try:
            git_setup = _find_installer("Git-*.exe")
            node_msi = _find_installer("node-v*.msi")
            pkg = _claude_pkg_dir()
            if not pkg:
                raise RuntimeError("本机 npm 全局目录里没有 claude-code 包（无打包源）")
            os.makedirs(out_dir, exist_ok=True)
            zip_path = os.path.join(out_dir, "claude-offline.zip")
            _log(f"输出：{zip_path}")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for src, arc in ((git_setup, "install/Git.exe"), (node_msi, "install/node.msi")):
                    if src:
                        _log(f"加入 {os.path.basename(src)}（{os.path.getsize(src)//1024//1024} MB）")
                        zf.write(src, arc)
                    else:
                        _log(f"跳过：未找到 {'Git 安装器' if arc.endswith('Git.exe') else 'Node MSI'}")
                _log("加入 claude-code 包目录（323MB 级，需几分钟）…")
                n = 0
                for root, _dirs, files in os.walk(pkg):
                    for f in files:
                        fp = os.path.join(root, f)
                        zf.write(fp, os.path.join(
                            "claude-code",
                            os.path.relpath(fp, pkg)))
                        n += 1
                        if n % 200 == 0:
                            _log(f"  claude-code 已打包 {n} 个文件…")
                _log(f"claude-code 打包完成，共 {n} 个文件")
            _setup_state.update(done=True, ok=True, phase="打包完成")
            _log(f"完成：{zip_path}（{os.path.getsize(zip_path)//1024//1024} MB）")
        except Exception as e:
            _setup_state.update(done=True, ok=False, err=str(e), phase="打包失败")
            _log(f"失败：{e}")
        finally:
            _setup_state["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


# ---- 离线安装（从 zip 包或直接用安装器资源） ----

# 官方下载位（联网通道资源目录没安装器时用；版本与 D:\AI\安装环境 对齐）
_NODE_URL = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-x64.msi"
_GIT_URL = ("https://github.com/git-for-windows/git/releases/download/"
            "v2.55.0.4.windows.1/Git-2.55.0.4-64-bit.exe")


def _download(url, dst):
    """流式下载安装器到 dst，按 MB 打日志。"""
    import urllib.request
    _log(f"下载 {url}")
    with urllib.request.urlopen(url, timeout=60) as resp, open(dst, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                _log(f"  已下载 {got // 1024 // 1024}/{total // 1024 // 1024} MB")
    return dst


def _install_node_if_missing(dl_dir):
    """Node 缺则静默装：先找本地 MSI 资源（安装环境目录），没有且能联网
    就下载官方 MSI。两条安装通道共用。"""
    if shutil.which("node.exe") or shutil.which("node"):
        _log("Node 已存在，跳过安装")
        return True
    msi = _find_installer("node-v*.msi")
    if not (msi and os.path.isfile(msi)):
        msi = os.path.join(dl_dir, "node.msi")
        if not os.path.isfile(msi):
            _download(_NODE_URL, msi)
    _install_node_from(msi)
    return bool(shutil.which("node.exe") or shutil.which("node"))


def _install_node_from(msi):
    """msiexec 静默装 Node。"""
    if not (msi and os.path.isfile(msi)):
        _log("警告：无 Node 安装器且本机无 Node——claude.cmd 需要 node.exe")
        return
    _log(f"静默安装 Node：{os.path.basename(msi)}（1-2 分钟）…")
    r = subprocess.run(["msiexec", "/i", msi, "/qn", "/norestart"],
                       capture_output=True, timeout=900)
    _log(f"msiexec 退出码 {r.returncode}")
    _refresh_process_path()   # msiexec 写注册表，本进程环境不自动更新


def _install_git_if_missing(dl_dir):
    """Git 缺则静默装：先找本地安装器，没有且能联网就下载官方 exe。"""
    if _git_ok():
        _log("Git 已存在，跳过安装")
        return True
    exe = _find_installer("Git-*.exe")
    if not (exe and os.path.isfile(exe)):
        exe = os.path.join(dl_dir, "Git.exe")
        if not os.path.isfile(exe):
            _download(_GIT_URL, exe)
    return _install_git_from(exe)


def _install_git_from(exe):
    """Inno Setup 官方静默参数装 Git。"""
    if not (exe and os.path.isfile(exe)):
        _log("警告：无 Git 安装器且本机无 Git")
        return
    _log(f"静默安装 Git：{os.path.basename(exe)}（1-3 分钟）…")
    r = subprocess.run([exe, "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"],
                       capture_output=True, timeout=900)
    _log(f"Git 安装器退出码 {r.returncode}")
    _refresh_process_path()


def _npm_install_global():
    """npm 装 claude-code——免提权设计：
    Windows 上 npm 全局 prefix 若指向 Program Files（nodejs MSI 默认），
    install -g 要管理员写权限（UAC 弹窗）。用 npm_config_prefix 环境变量
    把全局位钉到 %APPDATA%\\npm（用户目录，npm 官方推荐的用户级配置位），
    全程零提权。装完写 PATH + 广播，新起进程直接可见。"""
    _, npm = _node_ok()
    if not npm:
        raise RuntimeError("node/npm 不可用——先装 Node")
    appdata = os.environ.get("APPDATA", "")
    npm_dir = os.path.join(appdata, "npm")
    os.makedirs(npm_dir, exist_ok=True)
    env = dict(os.environ)
    env["npm_config_prefix"] = npm_dir
    env["npm_config_cache"] = os.path.join(appdata, "npm-cache")
    _log("npm install -g @anthropic-ai/claude-code（prefix → 用户目录，免提权）…")
    r = subprocess.run(["cmd", "/c", npm, "install", "-g",
                        "@anthropic-ai/claude-code"],
                       capture_output=True, text=True, timeout=900, env=env)
    for line in ((r.stdout or "") + (r.stderr or "")).splitlines():
        _log(line)
    if r.returncode != 0:
        raise RuntimeError(f"npm 退出码 {r.returncode}")
    _ensure_npm_path()


def _broadcast_path_change():
    """PATH 写注册表后广播 WM_SETTINGCHANGE（新起进程立即可见）。"""
    try:
        import ctypes
        from ctypes import wintypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(wintypes.DWORD()))
    except Exception:
        pass


def _ensure_npm_path():
    """把 %APPDATA%\\npm 写进 HKCU PATH（不存在才写；存在不动——守则4）。"""
    try:
        import winreg
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return
        npm_dir = os.path.join(appdata, "npm")
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment",
                             0, winreg.KEY_READ | winreg.KEY_WRITE)
        try:
            cur = winreg.QueryValueEx(key, "Path")[0]
        except FileNotFoundError:
            cur = ""
        parts = [p for p in cur.split(";") if p.strip()]
        if npm_dir.lower() not in [p.strip().lower() for p in parts]:
            parts.append(npm_dir)
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(parts))
        winreg.CloseKey(key)
        os.environ["PATH"] = os.environ["PATH"] + os.pathsep + npm_dir
        _broadcast_path_change()
    except Exception as e:
        _log(f"PATH 写入警告：{e}")


def _make_npm_shims(pkg_dir):
    """npm shim 生成：claude.cmd / claude.ps1 / claude（照 npm 标准布局写）。"""
    appdata = os.environ.get("APPDATA", "")
    npm_dir = os.path.join(appdata, "npm")
    os.makedirs(npm_dir, exist_ok=True)
    inner = os.path.join(pkg_dir, "bin", "claude.exe")
    if not os.path.isfile(inner):
        raise RuntimeError("包内缺 bin\\claude.exe，包不完整")
    rel = os.path.relpath(inner, npm_dir)
    cmd = f"""@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
IF EXIST "%dp0%\\node.exe" (
  SET "_prog=%dp0%\\node.exe"
) ELSE (
  SET "_prog=node.exe"
)
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%" "{rel}" %*
"""
    with open(os.path.join(npm_dir, "claude.cmd"), "w", encoding="utf-8") as f:
        f.write(cmd)
    ps1 = f"""#!/usr/bin/env pwsh
$basedir = Split-Path $MyInvocation.MyCommand.Definition -Parent
$exe = Join-Path $basedir "{rel.replace(os.sep, '\\')}"
if (Test-Path "$basedir\\node.exe") {{ & "$basedir\\node.exe" $exe $args }}
else {{ & "node.exe" $exe $args }}
exit $LASTEXITCODE
"""
    with open(os.path.join(npm_dir, "claude.ps1"), "w", encoding="utf-8") as f:
        f.write(ps1)
    _log(f"npm shim 已生成：{npm_dir}\\claude.cmd")


@claude_setup_bp.route("/api/claude/setup_install", methods=["POST"])
def claude_setup_install():
    """离线静默安装。body: {mode: 'offline'|'online', zip_path?}
    offline：优先用 zip 包（前端文件选择）；无 zip 则直接用安装环境目录资源。
    online：npm install -g（需要 node/npm 已装）。
    """
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode") or "offline"
    zip_path = (data.get("zip_path") or "").strip()
    with _setup_lock:
        if _setup_state["running"]:
            return jsonify({"ok": False, "err": "已有任务在运行"}), 409
        _setup_state.update(running=True, phase="准备", log=[], done=False,
                            ok=False, err="", ts=time.time())
    def work():
        try:
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                raise RuntimeError("无 APPDATA 环境")
            # 下载/解包临时目录（联网下载安装器、离线解 zip 都在这，完事清理）
            dl_dir = os.path.join(appdata, ".claude_offline_tmp")
            try:
                if mode == "online":
                    _install_node_if_missing(dl_dir)   # npm 依赖 Node——先补齐
                    _install_git_if_missing(dl_dir)
                    _npm_install_global()
                else:
                    # ---- 离线：解 zip（或直用资源目录）→ 静默装 Node/Git → 铺包 ----
                    workdir = dl_dir
                    if zip_path and os.path.isfile(zip_path):
                        if not zipfile.is_zipfile(zip_path):
                            raise RuntimeError("不是有效的 zip 包")
                        _log(f"解包 {zip_path} …")
                        if os.path.isdir(workdir):
                            shutil.rmtree(workdir, ignore_errors=True)
                        os.makedirs(workdir, exist_ok=True)
                        with zipfile.ZipFile(zip_path) as zf:
                            total = sum(1 for _ in zf.namelist())
                            for i, name in enumerate(zf.namelist()):
                                zf.extract(name, workdir)
                                if i % 500 == 0:
                                    _log(f"  已解 {i}/{total} …")
                        git_setup = os.path.join(workdir, "install", "Git.exe")
                        node_msi = os.path.join(workdir, "install", "node.msi")
                        pkg_dir = os.path.join(workdir, "claude-code")
                        if not os.path.isdir(pkg_dir):
                            raise RuntimeError("包内无 claude-code 目录")
                    else:
                        # 无 zip：直接用安装环境目录资源（有啥用啥）
                        git_setup = _find_installer("Git-*.exe")
                        node_msi = _find_installer("node-v*.msi")
                        pkg_dir = _claude_pkg_dir()
                        if not pkg_dir:
                            raise RuntimeError("既没有离线 zip，本机也没有 claude-code 包可铺")

                    # Node / Git：缺才静默装（zip 内资源优先于全局资源目录）
                    if shutil.which("node.exe") or shutil.which("node"):
                        _log("Node 已存在，跳过安装")
                    else:
                        _install_node_from(node_msi if (node_msi and os.path.isfile(node_msi))
                                           else _find_installer("node-v*.msi"))
                    if _git_ok():
                        _log("Git 已存在，跳过安装")
                    else:
                        _install_git_from(git_setup if (git_setup and os.path.isfile(git_setup))
                                          else _find_installer("Git-*.exe"))

                    # 铺 claude-code 包到 %APPDATA%\npm\node_modules（npm 标准位）
                    dst = os.path.join(appdata, "npm", "node_modules", "@anthropic-ai",
                                       "claude-code")
                    if os.path.abspath(pkg_dir) != os.path.abspath(dst):
                        _log(f"复制 claude-code → {dst}（几百 MB，需几分钟）…")
                        if os.path.isdir(dst):
                            _log("  目标已存在，先移除旧版")
                            shutil.rmtree(dst, ignore_errors=True)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copytree(pkg_dir, dst)
                    _make_npm_shims(dst)
                    _ensure_npm_path()
            finally:
                # 清理临时目录（zip 解包 / 联网下载的安装器）
                if os.path.isdir(dl_dir):
                    shutil.rmtree(dl_dir, ignore_errors=True)
                    _log("已清理临时目录")

            # 验证：强制重新解析
            _log("验证 claude CLI …")
            import src.claude_conn as cc
            cc._exe_cache = None
            try:
                exe, _shim = _resolve_claude_exe(force=True)
                _log(f"验证通过：{exe}")
                _setup_state.update(done=True, ok=True, phase="安装完成")
            except ClaudeNotFoundError as e:
                raise RuntimeError(f"装完仍未检测到 claude：{e}")
        except Exception as e:
            _setup_state.update(done=True, ok=False, err=str(e), phase="安装失败")
            _log(f"失败：{e}")
        finally:
            _setup_state["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


def _refresh_process_path():
    """从注册表 Machine+User PATH 重建本进程 PATH（安装器写完注册表用）。"""
    try:
        import winreg
        parts = []
        for hive, sub in ((winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                           (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                k = winreg.OpenKey(hive, sub, 0, winreg.KEY_READ)
                try:
                    v = winreg.QueryValueEx(k, "Path")[0]
                    if v:
                        parts.extend(v.split(";"))
                finally:
                    winreg.CloseKey(k)
            except OSError:
                pass
        if parts:
            os.environ["PATH"] = ";".join(p for p in parts if p.strip()) + \
                os.pathsep + os.environ.get("PATH", "")
            _log("本进程 PATH 已从注册表刷新")
    except Exception as e:
        _log(f"PATH 刷新警告：{e}")
