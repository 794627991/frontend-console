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
import sys
import threading
import time
import zipfile

from flask import Blueprint, jsonify, request

from .claude_conn import _resolve_claude_exe, ClaudeNotFoundError

claude_setup_bp = Blueprint("claude_setup", __name__)

# 安装任务状态（单例：同一时刻只允许一个安装/打包任务在跑）
_setup_lock = threading.Lock()
_setup_state = {"running": False, "phase": "", "log": [], "done": False, "ok": False,
                "err": "", "ts": 0, "need_api": False}


def _log(msg):
    _setup_state["log"].append({"t": time.time(), "msg": str(msg)})
    if len(_setup_state["log"]) > 500:
        del _setup_state["log"][:-500]


# ---- 资源探测 ----

# 离线资源搜索位（按优先级）：
# 1. 用户自定义目录（config.json offline_pkg_dir——设置界面/安装窗手动选）
# 2. 工具同目录 offline_pkg/（随包分发的离线安装资源，dist 打包时带上）
# 不再写死 D:\AI\安装环境（用户定：那只是本机的资源目录，别的机器没有）。


def _app_dir():
    """工具根目录。v3.5.27（用户实锤「发布版离线升级 claude 不可用」）：
    旧实现用 __file__ 上溯——打包（frozen）下 __file__ 在 _internal/src/，
    推出的根是 _internal/，而 _sync_offline_pkg 把 offline_pkg 放 exe 同级
    （_internal 的上一级）→ 发布版永远搜不到离线资源，离线升级失效。
    改 frozen 感知：exe 场景取 sys.executable 所在目录（exe 同级正是
    offline_pkg 落点）；源码场景维持 src/ 上溯。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _offline_pkg_dirs():
    """离线资源搜索目录列表（按优先级）。"""
    dirs = []
    # 1. 用户自定义（config.json offline_pkg_dir）
    try:
        from .app_state import _load_config
        custom = (_load_config().get("offline_pkg_dir") or "").strip()
        if custom and os.path.isdir(custom):
            dirs.append(custom)
    except Exception:
        pass
    # 2. 工具同目录 offline_pkg/（随包资源——无 config 也有）
    app_dir = _app_dir()
    dirs.append(os.path.join(app_dir, "offline_pkg"))
    dirs.append(os.path.join(app_dir, "dist", "offline_pkg"))
    # 去重保序
    seen, out = set(), []
    for d in dirs:
        dl = d.lower()
        if dl not in seen:
            seen.add(dl)
            out.append(d)
    return out


def _find_installer(pattern, extra_dirs=None):
    """按 glob 找安装器（Git exe / Node msi）。返回绝对路径或 None。"""
    dirs = list(_offline_pkg_dirs()) + list(extra_dirs or [])
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, pattern)):
            if os.path.isfile(f):
                return f
    return None


def _pkg_version(pkg_dir):
    """包源 claude-code 版本（package.json）。升级提示对比用；读不到空串。"""
    if not pkg_dir:
        return ""
    try:
        with open(os.path.join(pkg_dir, "package.json"), encoding="utf-8") as f:
            return json.load(f).get("version") or ""
    except Exception:
        return ""


def _claude_pkg_dir():
    """claude-code 包目录（离线直装的包源）。
    优先随包/自定义离线资源目录里的 claude-code（无网机器没有 npm 包），
    其次本机 npm 全局包。"""
    for d in _offline_pkg_dirs():
        p = os.path.join(d, "claude-code")
        if os.path.isdir(os.path.join(p, "bin")):
            return p
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        p = os.path.join(appdata, "npm", "node_modules", "@anthropic-ai", "claude-code")
        if os.path.isdir(p):
            return p
    return None


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
    # 用户自定义离线包目录（config）
    try:
        from .app_state import _load_config
        custom_dir = (_load_config().get("offline_pkg_dir") or "").strip()
    except Exception:
        custom_dir = ""
    # v3.5.29：当前 claude 版本（读本机 npm 包 package.json，零进程开销）——
    # 安装面板「已安装（当前 vX.Y.Z）」显示用，升级前后对比一眼可见
    cur_ver = ""
    try:
        appdata = os.environ.get("APPDATA", "")
        pj = os.path.join(appdata, "npm", "node_modules", "@anthropic-ai",
                          "claude-code", "package.json")
        if os.path.isfile(pj):
            with open(pj, encoding="utf-8") as f:
                cur_ver = json.load(f).get("version") or ""
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "claude": claude,
        "version": cur_ver,
        "node": bool(node), "npm": bool(npm),
        "git": bool(_git_ok()),
        "pkg_dir": pkg or "", "pkg_size": size,
        "pkg_version": _pkg_version(pkg),
        "git_installer": _find_installer("Git-*.exe") or "",
        "node_installer": _find_installer("node-v*.msi") or "",
        "offline_pkg_dir": custom_dir,
    })


@claude_setup_bp.route("/api/claude/setup_pkg_dir", methods=["POST"])
def claude_setup_pkg_dir():
    """设置/查看离线安装包搜索目录。body: {dir?} —— dir 为空串=清除自定义（回随包默认）。
    存 config.json offline_pkg_dir。目录形式不限制（zip 由「制作离线包」按钮产出，
    这里管的是解包后的资源目录/安装器目录）。"""
    data = request.get_json(force=True, silent=True) or {}
    from .app_state import _load_config, _save_config
    cfg = _load_config()
    if "dir" in data:
        d = (data.get("dir") or "").strip()
        if d and not os.path.isdir(d):
            return jsonify({"ok": False, "err": f"目录不存在：{d}"}), 400
        if d:
            cfg["offline_pkg_dir"] = d
        else:
            cfg.pop("offline_pkg_dir", None)
        _save_config(cfg)
    return jsonify({"ok": True, "offline_pkg_dir": cfg.get("offline_pkg_dir", "")})


# ---- 状态轮询 ----

@claude_setup_bp.route("/api/claude/setup_poll")
def claude_setup_poll():
    with _setup_lock:
        return jsonify({"ok": True, **{k: v for k, v in _setup_state.items()}})


# ---- 制作离线整合包 ----

# 工具自身 pip 依赖（与 deps_bootstrap.DEPS 一致）——打进离线包 pydeps/，
# 无网机器 pip install --no-index --find-links 离线装
_TOOL_DEPS = ["flask", "pyserial", "pywebview", "paramiko", "pywinpty"]


def _pack_pydeps(zf):
    """把工具自身 pip 依赖打成 wheel 收进 zip（pydeps/）。
    pip download 拉全套（含传递依赖），几 MB 级。失败不致命——
    工具依赖只是离线包的可选增强（exe 分发根本不需要）。"""
    import tempfile
    import subprocess
    import sys as _sys
    d = tempfile.mkdtemp(prefix="pydeps_")
    try:
        _log("收集工具依赖 wheel（pip download，约 10MB）…")
        r = subprocess.run(
            [_sys.executable, "-m", "pip", "download", "--no-input",
             "-d", d] + _TOOL_DEPS,
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            _log("依赖 wheel 收集失败（离线包继续制作，只是不含工具依赖）：" +
                 (r.stderr or "").strip()[:200])
            return
        n = 0
        for f in os.listdir(d):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                zf.write(fp, os.path.join("pydeps", f))
                n += 1
        _log(f"工具依赖已收 {n} 个包")
    finally:
        shutil.rmtree(d, ignore_errors=True)


@claude_setup_bp.route("/api/claude/setup_offline_pack", methods=["POST"])
def claude_setup_offline_pack():
    """把 Git 安装器 + Node MSI + claude-code 目录 + 工具 py 依赖打成 zip。
    body: {out_dir} —— zip 输出目录（前端弹原生目录选择）。
    包结构：claude-offline.zip
      ├ install/Git.exe  ├ install/node.msi
      ├ claude-code/            （npm 包目录原样，含 bin/claude.exe）
      └ pydeps/                （工具自身 pip 依赖 wheel，无网机器补装用）
    """
    data = request.get_json(force=True, silent=True) or {}
    out_dir = (data.get("out_dir") or "").strip() or os.path.join(
        os.path.expanduser("~"), "Desktop")
    with _setup_lock:
        if _setup_state["running"]:
            return jsonify({"ok": False, "err": "已有任务在运行"}), 409
        _setup_state.update(running=True, phase="打包离线资源", log=[], done=False,
                            ok=False, err="", ts=time.time(), need_api=False)
    def work():
        try:
            git_setup = _find_installer("Git-*.exe")
            node_msi = _find_installer("node-v*.msi")
            pkg = _claude_pkg_dir()
            if not pkg:
                raise RuntimeError("没有 claude-code 包（无打包源——本机 npm 或离线资源目录都没有）")
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
                _pack_pydeps(zf)
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
# 免安装 zip（MSI 提权失败 1603 的兜底，零权限解压即用）
_NODE_ZIP_URL = "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip"
# Git for Windows 实测可用地址（tag 命名规则：v主.次.修订.windows.N，资产名 Git-主.次.修订.N）
# 之前写的 v2.55.0.4.windows.1 不存在 → 404。改地址前务必 curl 实测 200。
_GIT_URL = ("https://github.com/git-for-windows/git/releases/download/"
            "v2.55.0.windows.5/Git-2.55.0.5-64-bit.exe")


def _download(url, dst):
    """流式下载安装器到 dst，按 MB 打日志。失败给人话（小白定位问题）。"""
    import urllib.request
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    _log(f"下载 {url}")
    try:
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
    except Exception as e:
        # 下载一半的残片清掉，避免下次误当完整安装器
        try:
            if os.path.isfile(dst):
                os.remove(dst)
        except OSError:
            pass
        raise RuntimeError(
            f"下载失败（{e}）——请检查网络；"
            f"无网环境请改用「📂 离线包安装」（选 claude-offline.zip）") from e
    return dst


def _preflight_urls():
    """联网安装预检：所有要下载的 URL 先 HEAD 探一遍（小白用户——别等
    下载到一半才发现 404）。返回 (ok, 消息)。已有本机资源的项跳过对应 URL。"""
    import urllib.request
    checks = []
    if not (shutil.which("node.exe") or shutil.which("node")):
        checks.append(("Node.js MSI", _NODE_URL))
        checks.append(("Node.js 免安装包", _NODE_ZIP_URL))
    if not _git_ok():
        checks.append(("Git", _GIT_URL))
    if not checks:
        _log("Node/Git 本机已有，无需下载")
        return True, ""
    _log(f"预检下载地址（{len(checks)} 项）…")
    for name, url in checks:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    return False, f"{name} 下载地址失效（HTTP {resp.status}）"
            _log(f"  ✓ {name} 地址正常")
        except Exception as e:
            return False, f"{name} 无法访问（{e}）——请检查网络后重试"
    return True, ""


def _install_node_if_missing(dl_dir):
    """Node 缺则静默装：先本地资源，再下载。MSI 提权装失败（1603 等）自动
    兜底 zip 免安装版——解压即用零提权，小白机器（无管理员）必走通。"""
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


def _install_node_zip(zip_path):
    """zip 免安装版兜底：解压到 %APPDATA%\\nodejs + 写用户 PATH。
    零提权零 msiexec——MSI 1603（无管理员）后的可靠退路。"""
    import zipfile
    dst_root = os.path.join(os.environ.get("APPDATA", ""), "nodejs")
    os.makedirs(dst_root, exist_ok=True)
    _log(f"解压 Node 免安装版 → {dst_root} …")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dst_root)
    # zip 内层是 node-v24.19.0-win-x64/，node.exe 在其中
    inner = [d for d in os.listdir(dst_root)
             if os.path.isdir(os.path.join(dst_root, d))]
    node_dir = os.path.join(dst_root, inner[0]) if inner else dst_root
    # 写用户级 PATH（注册表，免提权）
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_SET_VALUE) as k:
        cur = ""
        try:
            cur = winreg.QueryValueEx(k, "Path")[0]
        except OSError:
            pass
        if node_dir.lower() not in cur.lower():
            winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ,
                              (cur + ";" if cur else "") + node_dir)
    _log(f"Node PATH 已写入用户注册表：{node_dir}")
    _refresh_process_path()
    # 进程内立刻补上，不用等新开终端
    os.environ["PATH"] = node_dir + os.pathsep + os.environ.get("PATH", "")


def _install_node_from(msi):
    """msiexec 静默装 Node；退出码 1603（无管理员权限）等失败自动转 zip 免安装版。
    zip 来源优先级：离线包内 install/node-win-x64.zip > 本地资源目录 > 官方下载。"""
    if not (msi and os.path.isfile(msi)):
        _log("警告：无 Node 安装器且本机无 Node——claude.cmd 需要 node.exe")
        return
    _log(f"静默安装 Node：{os.path.basename(msi)}（1-2 分钟）…")
    r = subprocess.run(["msiexec", "/i", msi, "/qn", "/norestart"],
                       capture_output=True, timeout=900)
    _log(f"msiexec 退出码 {r.returncode}")
    _refresh_process_path()   # msiexec 写注册表，本进程环境不自动更新
    if r.returncode != 0 or not (shutil.which("node.exe") or shutil.which("node")):
        # 1603=通用安装失败（绝大多数是无管理员权限，per-machine MSI 必需）
        # ——改走 zip 免安装版：解压 %APPDATA%\nodejs + 用户 PATH，零提权
        _log("MSI 安装失败（多为无管理员权限），改用免安装 zip 版（零提权）…")
        cand = []
        # 离线包解压目录的 zip（与 msi 同目录；双布局+版本名通配——a124
        # 发布中心包的 zip 是 node-v24…-win-x64.zip 与 msi 同层）
        cand.append(os.path.join(os.path.dirname(msi), "node-win-x64.zip"))
        cand.append(os.path.join(os.path.dirname(msi), "node-v24.19.0-win-x64.zip"))
        try:
            import glob as _g
            _z = sorted(_g.glob(os.path.join(
                os.path.dirname(msi), "node-v*-win-x64.zip")))
            if _z:
                cand.append(_z[-1])
        except Exception:
            pass
        # 本地资源目录（联网通道）
        lz = _find_installer("node-v*-win-x64.zip")
        if lz:
            cand.append(lz)
        zpath = next((c for c in cand if c and os.path.isfile(c)), None)
        if not zpath:
            # 离线包没带 zip 也无本地资源 → 下载（离线机器会失败，报错说明白）
            zpath = os.path.join(os.path.dirname(msi), "node-win-x64.zip")
            _download(_NODE_ZIP_URL, zpath)
        _install_node_zip(zpath)


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


def _install_pydeps(pydeps_dir):
    """工具自身 pip 依赖离线补装（包内 pydeps/ 的 wheel）。
    --no-index --find-links：绝不联网，缺哪个装哪个（已装会被 pip 判 satisfied）。
    目录不存在/为空：静默跳过（老包没带）。"""
    import sys as _sys
    if not (pydeps_dir and os.path.isdir(pydeps_dir) and
            any(f.endswith((".whl", ".tar.gz")) for f in os.listdir(pydeps_dir))):
        return
    _log("补装工具自身依赖（离线 wheel，不联网）…")
    r = subprocess.run(
        [_sys.executable, "-m", "pip", "install", "--no-index",
         "--find-links", pydeps_dir, "--no-input"] + _TOOL_DEPS,
        capture_output=True, text=True, timeout=600,
        creationflags=subprocess.CREATE_NO_WINDOW)
    ok = r.returncode == 0
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for line in tail[-5:]:
        _log("  " + line)
    _log("工具依赖补装" + ("完成" if ok else "失败（不影响 claude 安装）"))
    if ok:
        # 补装成功：写自检通过标记——后续启动不再测/不再弹提醒（用户要求）
        try:
            from .deps_bootstrap import mark_selftest_ok
            mark_selftest_ok()
            _log("自检标记已写（后续启动不再检测依赖）")
        except Exception:
            pass
    # 新装的库当前进程 import 不到——不打断安装流程，工具重启后自然生效


def _verify_claude_runs(exe):
    """硬验证：真跑一次 claude --version 子进程（能执行才叫装好——
    比"文件存在"强一档，路径解析成功但二进制跑不起来也能当场暴露）。"""
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        ver = (r.stdout or r.stderr or "").strip().splitlines()
        if r.returncode == 0:
            _log(f"claude --version 通过：{ver[0] if ver else 'ok'}")
            return True
        raise RuntimeError(f"claude --version 退出码 {r.returncode}：" +
                           (ver[0] if ver else "无输出"))
    except subprocess.TimeoutExpired:
        raise RuntimeError("claude --version 60 秒无响应")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"claude --version 执行失败：{e}")


@claude_setup_bp.route("/api/claude/setup_install", methods=["POST"])
def claude_setup_install():
    """离线静默安装。body: {mode: 'offline'|'online', zip_path?}
    offline：优先用 zip 包（前端文件选择）；无 zip 则用离线资源目录（工具同目录 offline_pkg 或用户指定）。
    online：npm install -g（需要 node/npm 已装）。
    """
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode") or "offline"
    zip_path = (data.get("zip_path") or "").strip()
    with _setup_lock:
        if _setup_state["running"]:
            return jsonify({"ok": False, "err": "已有任务在运行"}), 409
        _setup_state.update(running=True, phase="准备", log=[], done=False,
                            ok=False, err="", ts=time.time(), need_api=False)
    def work():
        try:
            appdata = os.environ.get("APPDATA", "")
            if not appdata:
                raise RuntimeError("无 APPDATA 环境")
            # 下载/解包临时目录（联网下载安装器、离线解 zip 都在这，完事清理）
            dl_dir = os.path.join(appdata, ".claude_offline_tmp")
            try:
                if mode == "online":
                    # 预检：下载地址先 HEAD 探活（小白体验——别下载到一半 404）
                    ok, msg = _preflight_urls()
                    if not ok:
                        raise RuntimeError(f"预检失败：{msg}")
                    _install_node_if_missing(dl_dir)   # npm 依赖 Node——先补齐
                    # Node 装完必须真有 node 可用（MSI 1603 无提权已走 zip 兜底，
                    # 再没有就是彻底失败——中止，不带病继续）
                    if not (shutil.which("node.exe") or shutil.which("node")):
                        raise RuntimeError("Node 安装失败——请截图日志反馈，"
                                           "或改用「📂 离线包安装」")
                    _install_git_if_missing(dl_dir)
                    _npm_install_global()
                else:
                    # ---- 离线：只认 zip 压缩包（用户选包，工具自行解压临时目录） ----
                    # 不再支持裸目录资源——zip 是唯一形式（用户定），确保包完整可分发
                    if not (zip_path and os.path.isfile(zip_path)):
                        raise RuntimeError("离线安装必须选择离线包（claude-offline.zip）——"
                                           "请点「📂 选择离线包」")
                    if not zipfile.is_zipfile(zip_path):
                        raise RuntimeError("不是有效的 zip 包")
                    workdir = dl_dir
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
                    # a124（用户实锤「同事电脑离线包安装报 claude code
                    # 文件夹不存在」）：包布局双形态兼容。
                    # · 正典（「制作离线包」按钮产出 claude-offline.zip）：
                    #   根下 install/Git.exe、install/node.msi、claude-code/、
                    #   pydeps/
                    # · 发布中心通道（build._publish_offline_pkg 的
                    #   前端控制台-offline-pkg.zip）：全部套在 offline_pkg/
                    #   前缀下，且安装器带版本名（Git-2.55…exe /
                    #   node-v24…msi / node-v24…zip）。
                    # 旧实现只认正典路径——同事拿发布中心的包安装，解压后
                    # 找 <workdir>/claude-code 必落空 →「包内无 claude-code
                    # 目录」。两种布局、两种命名都认。
                    def _pkg_path(*segs):
                        for _base in (workdir,
                                      os.path.join(workdir, "offline_pkg")):
                            _p = os.path.join(_base, *segs)
                            if os.path.exists(_p):
                                return _p
                        return None

                    def _pkg_glob(pattern):
                        import glob as _g
                        for _base in (workdir,
                                      os.path.join(workdir, "offline_pkg")):
                            _hit = sorted(_g.glob(os.path.join(_base, pattern)))
                            if _hit:
                                return _hit[-1]
                        return None

                    pkg_dir = _pkg_path("claude-code")
                    if not (pkg_dir and os.path.isdir(os.path.join(pkg_dir, "bin"))):
                        raise RuntimeError(
                            "包内无 claude-code 目录（支持：claude-offline.zip / "
                            "前端控制台-offline-pkg.zip 两种布局）")
                    git_setup = (_pkg_path("install", "Git.exe")
                                 or _pkg_glob("Git-*.exe"))
                    node_msi = (_pkg_path("install", "node.msi")
                                or _pkg_glob("node-v*.msi"))

                    # Node / Git：缺才静默装（包内资源）。node.msi 提权失败自动
                    # 转包内 zip 免安装版（离线机器同样可能无管理员）
                    if shutil.which("node.exe") or shutil.which("node"):
                        _log("Node 已存在，跳过安装")
                    else:
                        _install_node_from(node_msi)
                    if not (shutil.which("node.exe") or shutil.which("node")):
                        raise RuntimeError("Node 安装失败（MSI 无权限且包内无 zip）——"
                                           "请换有管理员的机器或反馈日志")
                    if _git_ok():
                        _log("Git 已存在，跳过安装")
                    else:
                        _install_git_from(git_setup)

                    # 工具 py 依赖补装（包内 pydeps/ 有 wheel 才装——zip 是
                    # 无网机器补依赖的唯一来源；--no-index 绝不联网）
                    _install_pydeps(_pkg_path("pydeps"))   # a124：双布局

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

            # 验证：解析 + 硬验证（真跑一次 --version）
            _log("验证 claude CLI …")
            import src.claude_conn as cc
            cc._exe_cache = None
            try:
                exe, _shim = _resolve_claude_exe(force=True)
                _log(f"解析通过：{exe}")
                _verify_claude_runs(exe)   # 文件在 ≠ 能跑——真执行才算装好
                # 首次安装完成 → 铺设默认 settings/statusline（仅此刻铺，
                # 日常使用绝不自动碰 ~/.claude——用户要求）。provision 缺啥补啥，
                # 用户已有配置不动。
                from src.claude_default import provision_defaults
                _ok, notes = provision_defaults()
                for n in notes:
                    _log(n)
                # 还需要填 API token（首装必填）——标记给前端弹配置窗
                from src.claude_default import _read_settings
                env = _read_settings().get("env", {}) or {}
                _setup_state.update(done=True, ok=True, phase="安装完成",
                                    need_api=not env.get("ANTHROPIC_AUTH_TOKEN"))
                if not env.get("ANTHROPIC_AUTH_TOKEN"):
                    _log("下一步：请在弹出的 API 配置界面填入 API Token")
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
