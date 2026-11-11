# -*- coding: utf-8 -*-
"""Win 侧运行时安装原语（供 src/res_install.py 的 .fcpk 资源包安装复用）。

a32x（用户令「旧版离线包（zip）通道彻底退役，不要了」）：本模块原先注册的
五个 HTTP 端点（setup_status/setup_poll/setup_pkg_dir/setup_offline_pack/
setup_install）与前端安装引导窗已全部删除，现在**不注册任何端点、没有 UI**。
依赖安装统一走「设置 → 外部依赖安装」的 .fcpk 资源包，或 res_install 的
在线安装通道。

保留的是被复用的安装原语（那些逻辑经过多轮实机验证，重写只会引入回归）：
- Node/Git 静默安装（MSI 1603 无权限自动退化为免安装 zip）
- claude-code 铺包 + npm shim + PATH（HKCU）
- 工具 pip 依赖离线补装（--no-index --find-links，绝不联网）
- claude --version 硬验证（装上≠能跑）

安全/边界：安装器只写 HKCU PATH（与 file_assoc 同一约束），MSI/EXE
静默参数全部走官方 documented 开关，绝不碰 pythonw（铁律3）。
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

from flask import Blueprint

claude_setup_bp = Blueprint("claude_setup", __name__)

# a32x（对抗审 P1）：旧 UI 的 /api/claude/setup_poll 删除后，_log 原本的唯一
# 读者消失了——27 处排障关键日志（"msiexec 退出码 1603""改用免安装 zip""pip
# 尾部输出"）全进了无人读的缓冲区，等于把排障能力整体删掉。改为：
#   ① 保留环形缓冲（便于异常时 dump）
#   ② 支持注入 sink——res_install 安装时把 say 塞进来，日志直接进资源包
#      安装面板的实时日志流，用户看得见
_log_sink = None
# 内部诊断日志缓冲（a32x：旧 /api/claude/setup_poll 已删——现在只有 _log_sink
# 注入的消费者能看到；无 sink 时仅留 500 条环形缓冲供异常时 dump）
_setup_state = {"log": []}


def _log(msg):
    s = str(msg)
    _setup_state["log"].append({"t": time.time(), "msg": s})
    if len(_setup_state["log"]) > 500:
        del _setup_state["log"][:-500]
    sink = _log_sink
    if sink is not None:
        try:
            sink(s)
        except Exception:
            pass     # sink 坏掉不能影响安装主流程


# ---- 资源探测 ----

# 离线资源搜索位（按优先级）：
# 1. 用户自定义目录（config.json 的 offline_pkg_dir——a32x 起 UI 入口已随
#    旧 zip 通道退役，只保留"高级用户手工改 config.json"这条路）
# 2. 工具同目录 offline_pkg/ —— a326 起资源已统一迁入 offline_assets/，
#    这里仅作历史遗留目录兼容读取（新装机器上没有这个目录）
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
    # 2. 工具同目录 offline_pkg/（a326 起仅历史遗留兼容读取）
    app_dir = _app_dir()
    dirs.append(os.path.join(app_dir, "offline_pkg"))
    dirs.append(os.path.join(app_dir, "dist", "offline_pkg"))
    # a326：源码场景的统一资源目录（仓库 offline_assets/；exe 场景无此目录，
    # isdir 检查自然跳过）
    dirs.append(os.path.join(app_dir, "offline_assets"))
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


# ---- 运行时依赖安装（供 res_install 复用；旧 zip 通道的 UI/端点已退役）----

# 工具自身 pip 依赖（与 deps_bootstrap.DEPS 一致）——资源包的 pydeps kind
# 解包后按 --no-index --find-links 离线补装
_TOOL_DEPS = ["flask", "pyserial", "pywebview", "paramiko", "pywinpty",
              "pyelftools"]

# 官方下载位（在线安装通道：本地资源目录没安装器时才走；版本与 D:\AI\安装环境 对齐）
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
            f"下载失败（{e}）——请检查网络。无网环境请让发布者在资源包内"
            f"附带对应安装器（node 的 .msi 或 node-v*-win-x64.zip / Git-*.exe）"
            f"后重新制作 .fcpk 包") from e
    return dst


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
        # 本地资源目录（在线安装通道优先用）
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


def _npm_install_global(force=False):
    """npm 装 claude-code——免提权设计：
    Windows 上 npm 全局 prefix 若指向 Program Files（nodejs MSI 默认），
    install -g 要管理员写权限（UAC 弹窗）。用 npm_config_prefix 环境变量
    把全局位钉到 %APPDATA%\\npm（用户目录，npm 官方推荐的用户级配置位），
    全程零提权。装完写 PATH + 广播，新起进程直接可见。

    a459（用户实锤：已经装过还每次跑全量 install -g，几百 MB 白下载，还可能
    把可用版本换掉）：已装且非强制时改走 `npm update -g`——只拉版本差异，
    装不上（离线/registry 不通）就保留现有安装并如实说明，绝不因为「更新
    失败」把用户手上能用的 CLI 弄坏。"""
    _, npm = _node_ok()
    if not npm:
        raise RuntimeError("node/npm 不可用——先装 Node")
    appdata = os.environ.get("APPDATA", "")
    npm_dir = os.path.join(appdata, "npm")
    os.makedirs(npm_dir, exist_ok=True)
    env = dict(os.environ)
    env["npm_config_prefix"] = npm_dir
    env["npm_config_cache"] = os.path.join(appdata, "npm-cache")
    pkg = "@anthropic-ai/claude-code"
    # a469（第二轮审计 P2）：判据用**实际** prefix，不再是 env 里那个待写入的
    # 位置。原来硬传 npm_dir（%APPDATA%\npm），_claude_installed 的默认分支
    # 永不执行——用户 CLI 装在 Program Files 或自定 prefix 时一律判未装，每次
    # 全量 install -g，a459 想省的下载一分没省（_npm_prefix 成了死代码）。
    # 只在「实际 prefix 里确实装着」时才跟随它，否则仍装到用户目录：
    # Program Files 的 update 要提权（UAC），免提权是本函数的既定设计。
    if not force:
        real = _npm_prefix()
        if real and os.path.isdir(real) and _claude_installed(real):
            npm_dir = real
            env["npm_config_prefix"] = real
    if not force and _claude_installed(npm_dir):
        _log("已安装 claude-code，改为 npm update -g（只拉版本差异）…")
        r = subprocess.run(["cmd", "/c", npm, "update", "-g", pkg],
                           capture_output=True, text=True, timeout=900, env=env)
        for line in ((r.stdout or "") + (r.stderr or "")).splitlines():
            _log(line)
        if r.returncode != 0:
            # 更新失败不动现有安装：能用比新更重要
            _log("npm update 失败（退出码 %d）——保留现有安装，可改用"
                 "「强制重装」" % r.returncode)
        _ensure_npm_path()
        return
    _log("npm install -g %s（prefix → 用户目录，免提权）…" % pkg)
    r = subprocess.run(["cmd", "/c", npm, "install", "-g", pkg],
                       capture_output=True, text=True, timeout=900, env=env)
    for line in ((r.stdout or "") + (r.stderr or "")).splitlines():
        _log(line)
    if r.returncode != 0:
        raise RuntimeError(f"npm 退出码 {r.returncode}")
    _ensure_npm_path()


def _npm_prefix():
    """npm 实际全局 prefix（`npm prefix -g`），拿不到就退回 %APPDATA%\\npm。

    a464（审计 P2）：原实现把「已装」判据硬编码到 %APPDATA%\\npm——用户 CLI
    装在 nodejs MSI 默认的 Program Files、或改过 prefix 时，此目录下没有包，
    于是一律判未装、又走全量 install，本次改动想省的下载对这类机器无效。
    """
    _, npm = _node_ok()
    if npm:
        try:
            # a469（第二轮审计 P2）：node 走管道输出 UTF-8，而 text=True 用
            # locale(cp936) 解码——用户名含中文或 .npmrc 自定 prefix 含中文时
            # 必然乱码，isdir 恒 False 静默降级回 APPDATA（这次改动的目的之一
            # 就是别钉死 APPDATA）。另补 CREATE_NO_WINDOW：pythonw 无控制台
            # 时这个 cmd 会闪窗。超时抬到 60s（冷启动/杀毒扫描首跑）。
            kw = {}
            _cnw = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if _cnw:
                kw["creationflags"] = _cnw
            r = subprocess.run(["cmd", "/c", npm, "prefix", "-g"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=60, **kw)
            p = (r.stdout or "").strip().splitlines()
            if r.returncode == 0 and p and os.path.isdir(p[-1].strip()):
                return p[-1].strip()
            _log("npm prefix -g 未拿到有效目录（rc=%s out=%r）"
                 % (r.returncode, (r.stdout or "")[:200]))
        except Exception as e:
            _log("npm prefix -g 探测失败: %s" % e)
    return os.path.join(os.environ.get("APPDATA", ""), "npm")


def _claude_installed(npm_dir=None):
    """是否已装**可用**的 claude-code：package.json 与它的 bin 入口都在。

    a464（审计 P2）三处修正：
    - 原判据「两文件任一存在」，install 中断留下 package.json 而入口缺失时
      也判已装（docstring 说用 package.json 精确判，实现与说法相反）。
    - 目录来源改为 npm 实际 prefix（见 _npm_prefix），不再钉死 APPDATA。
    - 入口**从 package.json 的 bin 读**，不要写死 cli.js——实包是
      `{"bin": {"claude": "bin/claude.exe"}}`（带 native exe 的发行形态），
      写死 cli.js 会让所有机器都判成未装、又走全量下载。
    """
    base = os.path.join(npm_dir or _npm_prefix(), "node_modules",
                        "@anthropic-ai", "claude-code")
    pj = os.path.join(base, "package.json")
    if not os.path.isfile(pj):
        return False
    try:
        with open(pj, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False
    # a469（第二轮审计 P2）：json.load 对 []、""、数字都成功，随后 d.get 抛
    # AttributeError 且不在上面的 except 覆盖范围内——install 中断把
    # package.json 写成非对象时，走不到 npm install -g 的覆盖修复路径。
    if not isinstance(d, dict):
        return False
    b = d.get("bin")
    if isinstance(b, str):
        rel = b
    elif isinstance(b, dict):
        rel = b.get("claude") or (next(iter(b.values())) if b else "")
    else:
        rel = ""
    if not rel:
        return False
    return os.path.isfile(os.path.join(base, rel.replace("/", os.sep)))


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
