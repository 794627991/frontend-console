# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：前端控制台 → onedir 应用目录（v2.3.0 起）。
源码整理后入口在 src/main.py，资源（web/、ico/、vendor、spec）在项目根。
产物 = dist/前端控制台/（exe + _internal/ 依赖），发布形态 = zip。"""
import os, sys, subprocess, shutil

# v3.4.96：输出编码兜底——打包.bat 设 PYTHONIOENCODING=gbk，⚠/✓ 等
# 字符在重定向（>file / CI）下 gbk 不可编码直接 UnicodeEncodeError 崩掉
# 尾段（实测崩在 _publish 最后一行 ⚠ 提示；交互式控制台无恙故此前未现）。
# replace：坏字符落 ? 不致命
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根
if BASE not in sys.path:
    sys.path.insert(0, BASE)   # v2.3.1：tools.encrypt_pkg 在项目根下（py src/build.py 时 path[0]=src/）
APP_NAME = "前端控制台"
# v3.5.248（打包_debug.bat）：HG_NO_ENCRYPT=1 = 调试包——独立目录、源码明文、
# 仍打 zip（放 dist 根）；正包流（offline 同步/加密/releases 发布）全跳过
DEBUG = os.environ.get("HG_NO_ENCRYPT") == "1"
MAIN = os.path.join(BASE, "src", "main.py")
ICON = os.path.join(BASE, "ico", "app.ico")

def build():
    # 对抗审 P1-2：密钥必须在 encrypt_pkg（cython 收编 src/*.py）之前就绪
    # ——否则首发包的 exe 里没有密钥模块，用户机读不了同批产出的 .fcpk
    _ensure_fcpk_key()
    if not os.path.exists(ICON):
        print("图标不存在，跳过图标")
        icon_arg = []
    else:
        icon_arg = ["--icon", ICON]

    # 用 spec 文件打包（spec 里配置了 excludes 排除 cryptography 等重依赖以加速启动）
    spec = os.path.join(BASE, APP_NAME + ".spec")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    # v3.5.248：调试包独立目录 dist/前端控制台_debug/——与正包互不覆盖
    if DEBUG:
        cmd += ["--distpath", os.path.join("dist", APP_NAME + "_debug")]
    cmd.append(spec)

    print("打包命令:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=BASE)

    # v2.3.0 onedir：产物是应用目录（exe + _internal），exe 在目录内
    app_dir = os.path.join(BASE, "dist", APP_NAME + ("_debug" if DEBUG else ""))
    # v3.5.248b（用户实锤 debug 打包「未找到 exe」）：PyInstaller onedir 产物
    # 恒在 distpath 下再套一层 name 目录（distpath\name\name.exe）
    # distpath 是 dist/前端控制台_debug，真身在其下 前端控制台/ 内
    if DEBUG:
        app_dir = os.path.join(app_dir, APP_NAME)
    dist = os.path.join(app_dir, APP_NAME + ".exe")
    if os.path.exists(dist):
        # 对抗审计 P0 复发防线（v2.4.0 曾把 pythonnet/runtime 99 个文件剔掉
        # 发出死包）：发布 zip 前强制校验关键目录在场，缺了直接 FAIL 停发
        _guards = [
            os.path.join(app_dir, "_internal", "pythonnet", "runtime"),
            os.path.join(app_dir, "_internal", "webview", "lib"),
            os.path.join(app_dir, "_internal", "web", "index.html"),
        ]
        for g in _guards:
            if not os.path.exists(g):
                raise SystemExit("[发布守卫] 关键内容缺失：%s ——禁止发布，"
                                 "请检查 skip_top/打包配置后重打" % g)
        print("[发布守卫] 关键内容校验通过（pythonnet/webview/web）")
        sz = sum(os.path.getsize(os.path.join(r, f))
                 for r, _, fs in os.walk(app_dir) for f in fs) / 1024 / 1024
        print(f"\n打包成功: {app_dir} ({sz:.1f} MB)")
        # v3.5.248（打包_debug.bat）：HG_NO_ENCRYPT=1 = 调试包——web 源码明文
        # （可直接查看/改），zip 照打（v3.5.248 用户定调「打包压缩还是要的」）
        # 但放 dist 根、不进 releases——升级分发流绝不收录调试包
        if DEBUG:
            # v3.5.267（全审）：debug 哨兵文件——selftest 据此区分 debug 明文
            # 形态与「正包加密失败态」（后者无 .fcenc 也无 .fcdebug，应 FAIL）
            try:
                open(os.path.join(app_dir, "_internal", ".fcdebug"), "w").close()
            except OSError:
                pass
            # v3.5.250（用户实锤 debug 包启动 ModuleNotFoundError: src.version）：
            # spec excludes 'src'——正包的 src 由 encrypt_pkg 编译成原生 pyd
            # 外置 _internal/src/（防反解），debug 跳过加密=没人生成 pyd=src
            # 整包缺失。debug 改为把 src 源树 .py 明文落 _internal/src/
            #（FrozenImporter 排除 src 后自动回落文件系统 import——这正是
            # 「不加密源码」的形态本体）
            _src_root = os.path.join(BASE, "src")
            _dst = os.path.join(app_dir, "_internal", "src")
            _n = 0
            for r, ds, fs in os.walk(_src_root):
                ds[:] = [d for d in ds if d != "__pycache__"]
                for f in fs:
                    if not f.endswith(".py"):
                        continue
                    _sp = os.path.join(r, f)
                    _dp = os.path.join(_dst, os.path.relpath(_sp, _src_root))
                    os.makedirs(os.path.dirname(_dp), exist_ok=True)
                    shutil.copy2(_sp, _dp)
                    _n += 1
            print(f"调试包: src 源码明文外置 {_n} 个 .py → _internal/src/")
            print("调试包模式（HG_NO_ENCRYPT=1）：源码明文，zip 输出到 dist 根")
            _publish_debug(app_dir)
            return dist
        _refresh_offline_claude()   # v3.4.95：离线 claude-code 版本有变即刷新
        _refresh_offline_codegraph()   # a386：codegraph 同款（用户令工具内置——工作机无 npm 实锤）
        # a326：offline_pkg 三处分散资源已统一迁入 offline_assets/（MANIFEST
        # 入库、本体 gitignore），旧 _sync_offline_pkg 双目录同步随之退役；
        # 其尾部的 README 随包复制挪到这里
        try:
            shutil.copy2(os.path.join(BASE, "README.md"),
                         os.path.join(BASE, "dist", APP_NAME, "README.md"))
        except OSError:
            pass
        # v4.1（用户拍板）：不再 _bundle_webview2 随包带运行时——改为打进
        # 统一离线资源包 .fcpk（含 WebView2/dotnet/node/git/claude/pydeps）。
        # 发布包随之从 318MB 降到约 65MB。
        # v2.3.1 发布前资源加密（web 前端源码/blob → AES-256-GCM 密文，
        # exe 启动 src/secure_boot.py 自解密；第三方库不碰）
        try:
            from tools.encrypt_pkg import encrypt_pkg
            n = encrypt_pkg(app_dir)
            if n:
                print(f"资源加密: {n} 个文件（口令混淆内嵌，首启自解密）")
        except Exception as e:
            print("⚠ 资源加密失败（发布 zip 将含明文 web）:", e)
        _publish(app_dir)
        _build_offline_fcpk()    # v4.1：统一加密离线资源包（.fcpk）
        return dist
    else:
        print("打包失败：未找到 exe")
        return None


def _bundle_webview2(app_dir):
    """【v4.1 已退役，保留以便回滚】WebView2 改为打进 .fcpk 资源包，
    发布包不再随带。回滚：skip_dirs 去掉 "runtime" + 主流程恢复调用。

    v2.3.7b（用户铁律×2「无条件随包；保底包不能是下载的——不能假设
    构建机有网络」）：WebView2 Fixed Version 运行时随仓走——a326 起
    本体迁 offline_assets/webview2/（不入 git），MANIFEST.json 入库记录
    版本与获取方式，新检出机器按清单跑 tools/fetch_webview2_fixed.py
    恢复后再打包。

    缺失=资源未恢复 → 打包直接失败（绝不出依赖系统运行时的降级包，
    也绝不在 build 期下载）。版本升级：开发机上人工跑
    tools/fetch_webview2_fixed.py（那是唯一联网点，跑完更新清单提交）。"""
    src = os.path.join(BASE, "offline_assets", "webview2")
    if not os.path.isdir(src):
        raise RuntimeError(
            "WebView2 内置运行时缺失（offline_assets/webview2/ 不在——新"
            "检出仓库无资源本体）。按铁律打包中止：按 offline_assets/"
            "MANIFEST.json 跑 tools/fetch_webview2_fixed.py 恢复后重试"
            "（不在 build 期下载）")
    dst = os.path.join(app_dir, "runtime", "WebView2Fixed")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst)
    n = sum(len(fs) for _, _, fs in os.walk(dst))
    if not os.path.isfile(os.path.join(
            dst, os.listdir(dst)[0], "msedgewebview2.exe")) or n < 100:
        raise RuntimeError("WebView2 内置运行时不完整（%d 文件）——打包中止"
                           % n)
    sz = sum(os.path.getsize(os.path.join(r, f))
             for r, _, fs in os.walk(dst) for f in fs) / 1024 / 1024
    print("webview2 内置: WebView2Fixed → 应用包（%d 文件，%.0f MB，"
          "zip 压缩后约增 1/3）" % (n, sz))


def _publish_debug(app_dir):
    """v3.5.248：调试包压缩——同 _publish 的 zip 口径（顶层壳目录、跳运行时
    产物），但输出 dist 根、不写 manifest、不进 releases：压缩是给用户拿去
    别处调试用的，升级分发服务（检查更新）绝不收录调试包。"""
    import zipfile
    sys.path.insert(0, BASE)
    from src.version import APP_VERSION
    dst = os.path.join(BASE, "dist", "%s_debug-v%s.zip" % (APP_NAME, APP_VERSION))
    skip_dirs = {".update", "data"}          # 运行时产物不进包
    skip_files = {"update.bat"}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for r, ds, fs in os.walk(app_dir):
            ds[:] = [d for d in ds if d not in skip_dirs]
            for f in fs:
                if f in skip_files:
                    continue
                p = os.path.join(r, f)
                z.write(p, os.path.join(APP_NAME + "_debug", os.path.relpath(p, app_dir)))
    print("调试 zip: %s (%.1f MB)" % (dst, os.path.getsize(dst) / 1024 / 1024))


def _publish(app_dir):
    """打包即发布（v2.3.0 zip 形态）：应用目录打成版本化 zip 放 dist/releases/
    + 生成 manifest.json（版本/sha1/大小/日期/说明）。发布机开「升级分发服务」
    （设置页）后同事端「检查更新」即见此版。说明取版本说明文件，没有就留空。
    zip 只含应用本体——data/.update/update.bat 等运行时产物、offline_pkg
    （几百 MB 离线安装资源）都不进包。"""
    import hashlib, datetime, zipfile
    sys.path.insert(0, BASE)
    from src.version import APP_VERSION
    rel = os.path.join(os.path.dirname(app_dir), "releases")
    os.makedirs(rel, exist_ok=True)
    ver_name = "%s-v%s.zip" % (APP_NAME, APP_VERSION)
    dst = os.path.join(rel, ver_name)
    # 压缩应用目录（顶层带「前端控制台/」壳——同事解压即得同名目录，
    # updater 解压后按唯一壳目录定位应用根）
    # v4.1（用户拍板）：runtime/ 不再进发布包——WebView2 移入统一离线资源包
    # （.fcpk），发布包 318MB → 65MB。缺运行时的机器启动时由 res_boot 闸门
    # 引导装包。回滚只需把下面的顶层 runtime 剔除删掉并恢复 _bundle_webview2。
    #
    # 全审 A2 实锤（严重）：早前用 {".update","data","runtime"} 做**裸目录名**
    # 匹配，对任意深度生效，把 _internal/pythonnet/runtime/（Python.Runtime.dll
    # 等 99 个文件）一并剔掉 → 发布包里 pythonnet 条目为 0 → import clr 失败
    # → `import webview` 抛异常，窗口根本建不出来。必须只跳过应用目录**顶层**
    # 的那三个目录。
    skip_top = {".update", "data", "runtime", "offline_runtime"}
    skip_files = {"update.bat"}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for r, ds, fs in os.walk(app_dir):
            if os.path.normpath(r) == os.path.normpath(app_dir):
                ds[:] = [d for d in ds if d not in skip_top]
            for f in fs:
                if f in skip_files:
                    continue
                p = os.path.join(r, f)
                z.write(p, os.path.join(APP_NAME, os.path.relpath(p, app_dir)))
    h = hashlib.sha1()
    with open(dst, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    # 说明唯一来源（用户定调「自动提取不要了，由我找AI手动处理」——流水账
    # 两犯后整条路拆除）：只认打包前写好的 RELEASE_NOTES.md；没写就留空，
    # 发布页该版显示「未写更新说明」。归档 notes-v<ver>.md 供门户更新日志
    # 逐版展示。
    # v4.0.1：截断线 500→4000——新画的发布说明 1305 字，500 会在第一条
    # 主线中间切断（用户实锤发布页说明被拦腰截断）。发布页/更新弹窗两侧
    # 本来就是 max-height+滚动区，放宽上限只是少丢内容，不会撑破版面。
    notes = ""
    notes_path = os.path.join(BASE, "RELEASE_NOTES.md")
    if os.path.exists(notes_path):
        try:
            with open(notes_path, encoding="utf-8") as f:
                notes = f.read().strip()[:4000]
        except OSError:
            pass
    if notes:
        try:
            with open(os.path.join(rel, "notes-v%s.md" % APP_VERSION),
                      "w", encoding="utf-8") as f:
                f.write(notes)
        except OSError:
            pass
    manifest = {
        "version": APP_VERSION,
        "file": ver_name,
        "format": "zip",
        "sha1": h.hexdigest(),
        "size": os.path.getsize(dst),
        "date": datetime.date.today().isoformat(),
        "notes": notes,
    }
    mpath = os.path.join(rel, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        import json
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    from src.update_server import _lan_ip, PORT
    print(f"\n[已发布] v{APP_VERSION} → {dst} ({manifest['size']//1024//1024} MB)")
    print(f"  sha1: {manifest['sha1']}")
    print(f"  同事升级地址: http://{_lan_ip()}:{PORT}/"
          f"（需在设置里开启「升级分发服务」）")
    print(f"  说明文件: RELEASE_NOTES.md（本次 {'已带' if notes else '未写——发布页该版将无更新说明，发布前找AI写好放项目根'}）")
    print("  ⚠ v2.2.x 及更早的 onefile 旧版无法自动升级到 zip 形态——"
          "需把 zip 发给同事手动解压换装一次（2.3.0 起全程自动）")



def _refresh_offline_codegraph():
    """a386（用户实锤「说好的工具内置呢」）：codegraph 本体从 npm 全局刷到
    offline_assets/codegraph/（平台 bundle：node.exe + lib，自带运行时——
    同事机零 npm 依赖）。与 claude-code 同款版本比对 + robocopy 镜像。"""
    import json
    cands = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules",
                     "@colbymchenry", "codegraph", "node_modules",
                     "@colbymchenry", "codegraph-win32-x64"),
    ]
    try:
        # S37-12（P4）：list 形态 CreateProcess 不解析 .cmd 且 npm 无 npm.exe
        # ——Windows 恒 FileNotFoundError，自定义前缀兜底从未生效
        from shutil import which as _sh_which   # P-23 干跑修正：模块不可调用
        _npm = _sh_which("npm") or ""
        out = (subprocess.check_output([_npm, "root", "-g"], text=True,
                                       stderr=subprocess.DEVNULL, timeout=20).strip()
               if _npm else "")
        if out:
            cands.append(os.path.join(out, "@colbymchenry", "codegraph",
                                      "node_modules", "@colbymchenry",
                                      "codegraph-win32-x64"))
    except Exception:
        pass
    src = next((c for c in cands
                if os.path.isfile(os.path.join(c, "node.exe"))
                and os.path.isdir(os.path.join(c, "lib"))), None)
    if not src:
        print("offline codegraph: 未找到本机安装，跳过版本刷新")
        return

    def _ver(d):
        try:
            with open(os.path.join(d, "lib", "package.json"), encoding="utf-8") as f:
                return json.load(f).get("version") or ""
        except Exception:
            try:
                with open(os.path.join(d, "package.json"), encoding="utf-8") as f:
                    return json.load(f).get("version") or ""
            except Exception:
                return ""

    dst = os.path.join(BASE, "offline_assets", "codegraph")
    src_v, dst_v = _ver(src), _ver(dst)
    if not src_v or src_v == dst_v:
        print(f"offline codegraph: {dst_v or '无'} 与本机一致，无需刷新")
        return
    print(f"offline codegraph: {dst_v or '无'} → {src_v} 刷新 …")
    rc = subprocess.call(["robocopy", src, dst, "/MIR", "/NFL", "/NDL", "/NJH",
                          "/NJS", "/NP"], creationflags=0x08000000)
    # R34-3b：robocopy 0-7 成功码；>7（8+，真失败）不能报「刷新完成」
    # ——失败时离线副本处于半镜像态，必须显式报错（claude 段同款判定）
    if rc > 7:
        print(f"offline codegraph: ✗ 刷新失败（robocopy rc={rc}，副本可能不完整）")
    else:
        print(f"offline codegraph: 刷新完成（robocopy rc={rc}）")


def _refresh_offline_claude():
    """v3.4.95（用户需求「打包时 claude 版本也重新更新，如果有变化的话」）：
    本机 npm 全局的 @anthropic-ai/claude-code 与 offline_assets/claude-code
    比对版本，不同则 robocopy /MIR 镜像刷新——离线安装资源不再停留在首次
    打包时的旧版。找不到本机安装（CI/未装）静默跳过。"""
    import json
    cands = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules",
                     "@anthropic-ai", "claude-code"),
    ]
    try:   # npm 前缀自定义过的机器
        # S37-12（P4）：list 形态 CreateProcess 不解析 .cmd 且 npm 无 npm.exe
        # ——Windows 恒 FileNotFoundError，自定义前缀兜底从未生效
        from shutil import which as _sh_which   # P-23 干跑修正：模块不可调用
        _npm = _sh_which("npm") or ""
        out = (subprocess.check_output([_npm, "root", "-g"], text=True,
                                       stderr=subprocess.DEVNULL, timeout=20).strip()
               if _npm else "")
        if out:
            cands.append(os.path.join(out, "@anthropic-ai", "claude-code"))
    except Exception:
        pass
    src = next((c for c in cands if os.path.isfile(os.path.join(c, "package.json"))), None)
    if not src:
        print("offline claude-code: 未找到本机安装，跳过版本刷新")
        return
    def _ver(d):
        try:
            with open(os.path.join(d, "package.json"), encoding="utf-8") as f:
                return json.load(f).get("version") or ""
        except Exception:
            return ""
    dst = os.path.join(BASE, "offline_assets", "claude-code")
    src_v, dst_v = _ver(src), _ver(dst)
    if not src_v or src_v == dst_v:
        print(f"offline claude-code: {dst_v or '无'} 与本机一致，无需刷新")
        return
    print(f"offline claude-code: {dst_v or '无'} → {src_v} 刷新 …")
    # robocopy /MIR 镜像（几百 MB 级，Windows 自带，比 copytree 快且可续传）
    rc = subprocess.call(["robocopy", src, dst, "/MIR", "/NFL", "/NDL", "/NJH",
                          "/NJS", "/NP"], timeout=1800)
    if rc > 7:   # 0-7 均为成功档
        print(f"⚠ claude-code 刷新失败 (robocopy rc={rc})")



# ---------------------------------------------------------------------------
# v4.1：统一离线资源包 .fcpk（用户拍板：WebView2 移出发布包，格式统一+加密）
# ---------------------------------------------------------------------------

# ---- a201：bili 资源组装（打包机联网跑一次，产物进 offline_assets/bili/）----
BILI_NPM_VERSION = "0.1.204"        # 锁定版（0.1.x 高频迭代，不跟 master）
BILI_NODE_VERSION = "22.14.0"       # LTS（≥22 硬要求）

def _prep_bili_dir():
    """组装内置压缩引擎资源：Node 便携运行时 node.exe + billion-context
    完整依赖树。npm install --prefix 产出 node_modules（含全部依赖），
    node.exe 从官方 zip 抽取（win-x64 zip 里 node.exe 自含全部内置模块）。
    幂等：目录已存在且关键文件齐则跳过。"""
    import subprocess, zipfile, urllib.request
    root = os.path.join(BASE, "offline_assets", "bili")
    node_exe = os.path.join(root, "node.exe")
    entry = os.path.join(root, "node_modules", "billion-context",
                         "dist", "index.js")
    if os.path.isfile(node_exe) and os.path.isfile(entry):
        print("[bili] 已组装，跳过（删 %s 可重跑）" % root)
        return
    os.makedirs(root, exist_ok=True)
    if not os.path.isfile(node_exe):
        url = ("https://nodejs.org/dist/v%s/node-v%s-win-x64.zip"
               % (BILI_NODE_VERSION, BILI_NODE_VERSION))
        zpath = os.path.join(BASE, "dist", "node-v%s-win-x64.zip" % BILI_NODE_VERSION)
        if not os.path.isfile(zpath):
            print("[bili] 下载 %s …" % url)
            # 对抗审 a206B P2：半截 zip 永久卡死重跑（存在性检查放行坏档，
            # zipfile 每次抛 BadZipFile）——.part 下载完再原子改名
            urllib.request.urlretrieve(url, zpath + ".part")
            # 对抗审 a206B P3：官方 SHASUMS256.txt 原产地校验（企业 MITM 换
            # 合法 zip 无 CRC 兜底的场景）
            import hashlib
            h = hashlib.sha256(open(zpath + ".part", "rb").read()).hexdigest()
            sums = urllib.request.urlopen(
                "https://nodejs.org/dist/v%s/SHASUMS256.txt" % BILI_NODE_VERSION,
                timeout=30).read().decode()
            expect = next((l.split()[0] for l in sums.splitlines()
                           if l.strip().endswith(
                               "node-v%s-win-x64.zip" % BILI_NODE_VERSION)), "")
            if expect and h.lower() != expect.lower():
                os.remove(zpath + ".part")
                raise SystemExit("[bili] ✗ node.zip 校验失败（shasum 不符，"
                                 "可能传输损坏或被代理替换）——已删除可重试")
            os.replace(zpath + ".part", zpath)
        with zipfile.ZipFile(zpath) as z:
            member = "node-v%s-win-x64/node.exe" % BILI_NODE_VERSION
            with z.open(member) as src, open(node_exe, "wb") as dst:
                import shutil as _sh
                _sh.copyfileobj(src, dst)
        print("[bili] node.exe 就位")
    if not os.path.isfile(entry):
        print("[bili] npm install billion-context@%s …" % BILI_NPM_VERSION)
        # 对抗审 a206B P3：无 npm 机器上裸 CalledProcessError 回溯→人话指引
        try:
            subprocess.run(["npm", "install", "--prefix", root,
                            "billion-context@%s" % BILI_NPM_VERSION],
                           check=True, shell=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise SystemExit("[bili] ✗ npm 安装失败（%s）。打包机需先装 "
                             "Node.js ≥22（自带 npm）再运行 --prep-bili" % e)
        # 对抗审 a206B P2-5：npm 写入的 package.json 是 ^caret 浮动——lock
        # 被删时重跑会静默漂到最新 0.1.x。改写为精确版本钉死
        pj = os.path.join(root, "package.json")
        try:
            import json as _j
            d = _j.load(open(pj, encoding="utf-8"))
            deps = d.get("dependencies") or {}
            if deps.get("billion-context") != BILI_NPM_VERSION:
                deps["billion-context"] = BILI_NPM_VERSION
                _j.dump(d, open(pj, "w", encoding="utf-8"), indent=2)
                print("[bili] package.json 已钉精确版本 %s" % BILI_NPM_VERSION)
        except Exception:
            pass
    print("[bili] 组装完成 → %s" % root)


def _offline_sources(kinds=None):
    """收集离线资源清单。返回 [(src_path, arcname, kind, mode, link_from)]。

    kinds=None 收全量；否则只收这些 kind（用户拍板：默认全量，需要时可只打
    某几项，如 --kinds claude 单独出 270MB 的小包给只缺 Claude 的同事）。

    mode 取舍（实测压缩率）：.msi/.zip/.whl 已压缩过（1.01~1.05，再压反而
    变大）→ raw；.exe/.dll 值得压（Git 1.03 但 exe 本体可变、webview2 的
    msedge.dll 0.61、claude.exe 0.57）→ 只有明确的 DLL/EXE 用 deflate。
    """
    want = set(kinds) if kinds else None

    def _take(k):
        return want is None or k in want

    src = os.path.join(BASE, "offline_assets")
    out = []
    inst = os.path.join(src, "install")
    if os.path.isdir(inst):
        for name in sorted(os.listdir(inst)):
            p = os.path.join(inst, name)
            if not os.path.isfile(p):
                continue
            low = name.lower()
            if low.endswith((".msi", ".zip", ".whl", ".tar.gz")):
                mode = "raw"
            elif low.endswith(".exe"):
                mode = "deflate"
            else:
                continue
            if low.startswith("git-"):
                kind = "git"
            elif low.startswith("node-"):
                kind = "node"
            elif low.startswith("ndp481"):
                kind = "dotnet"
            else:
                continue
            if _take(kind):
                out.append((p, "install/" + name, kind, mode, None))
    if os.path.isdir(src):
        bl = os.path.join(src, "bili")
        if os.path.isdir(bl) and _take("bili"):
            # a201 内置压缩引擎：Node 便携运行时 + billion-context 依赖树
            # （组装见 _prep_bili_dir）。整目录全收（claude-code 同款教训：
            # 挑扩展名会丢 package.json 等命脉文件，装出空壳）。
            # 对抗审 a206B P3：.ts/.map/.mjs 等 ~48MB 高可压文本原走 raw，
            # deflate 后包体省 30MB+
            for r, ds, fs in os.walk(bl):
                ds.sort()
                # 对抗审 a206B P2：junction 下钻防护（os.path.islink 对 Windows
                # junction 返回 False，须查 reparse 属性）——npm workspaces/
                # pnpm 场景会产生 junction，下钻即重复条目+超长路径炸解包
                ds[:] = [d for d in ds
                         if not (os.stat(os.path.join(r, d)).st_file_attributes or 0) & 0x400]
                for f in sorted(fs):
                    p2 = os.path.join(r, f)
                    arc = "bili/" + os.path.relpath(p2, bl).replace("\\", "/")
                    low = f.lower()
                    mode = ("deflate" if low.endswith(
                        (".exe", ".dll", ".node", ".cjs", ".js", ".json",
                         ".ts", ".cts", ".mts", ".mjs", ".map"))
                        else "raw")
                    out.append((p2, arc, "bili", mode, None))
        cg = os.path.join(src, "codegraph")
        if os.path.isdir(cg) and _take("codegraph"):
            # a386：codegraph 平台 bundle（node.exe+lib 自带运行时）整目录
            # 全收（bili/claude 同款教训：挑扩展名装出空壳）
            for r, ds, fs in os.walk(cg):
                ds.sort()
                ds[:] = [d for d in ds
                         if not (os.stat(os.path.join(r, d)).st_file_attributes or 0) & 0x400]
                for f in sorted(fs):
                    p2 = os.path.join(r, f)
                    arc = "codegraph/" + os.path.relpath(p2, cg).replace("\\", "/")
                    low = f.lower()
                    mode = ("deflate" if low.endswith(
                        (".exe", ".dll", ".node", ".cjs", ".js", ".json",
                         ".ts", ".cts", ".mts", ".mjs", ".map"))
                        else "raw")
                    out.append((p2, arc, "codegraph", mode, None))
        cc = os.path.join(src, "claude-code")
        if os.path.isdir(cc) and _take("claude"):
            # 全审 B4 实锤（严重）：早前只收 .exe/.node/.dll，把
            # package.json / cli-wrapper.cjs / install.cjs / LICENSE 等全丢了
            # ——装出来是「只有两个 exe 的空壳」，claude 起不来、版本号也读
            # 不到，还会把用户现有可用安装 rmtree 掉。改为**整目录全收**：
            # 已压缩的二进制用 deflate，其余（json/js/md）用 raw。
            first_exe = None
            for r, ds, fs in os.walk(cc):
                ds.sort()
                for f in sorted(fs):
                    p = os.path.join(r, f)
                    arc = ("claude-code/"
                           + os.path.relpath(p, cc).replace("\\", "/"))
                    low = f.lower()
                    mode = ("deflate" if low.endswith(
                        (".exe", ".dll", ".node", ".cjs", ".js", ".json"))
                        else "raw")
                    link = None
                    if low == "claude.exe":
                        if first_exe is None:
                            first_exe = arc
                        else:
                            link = first_exe
                    out.append((p, arc, "claude", mode, link))
        # a309R：OnlyOffice DS 安装包（kind=onlyoffice）——a326 迁入
        # offline_assets/onlyoffice/。打包机没下载过则包不含
        oo = os.path.join(src, "onlyoffice",
                          "onlyoffice-documentserver.exe")
        if os.path.isfile(oo) and _take("onlyoffice"):
            out.append((oo, "install/onlyoffice-documentserver.exe",
                        "onlyoffice", "raw", None))
        pd = os.path.join(src, "pydeps")
        if os.path.isdir(pd) and _take("pydeps"):
            for f in sorted(os.listdir(pd)):
                p = os.path.join(pd, f)
                if os.path.isfile(p):
                    out.append((p, "pydeps/" + f, "pydeps", "raw", None))
    wv = os.path.join(BASE, "offline_assets", "webview2")
    if os.path.isdir(wv) and _take("webview2"):
        for r, ds, fs in os.walk(wv):
            ds.sort()
            for f in sorted(fs):
                p = os.path.join(r, f)
                arc = "webview2/" + os.path.relpath(p, wv).replace("\\", "/")
                low = f.lower()
                mode = "deflate" if low.endswith((".exe", ".dll")) else "raw"
                out.append((p, arc, "webview2", mode, None))
    return out


def _ensure_fcpk_key():
    """对抗审计修正：仓库不再携带口令——首次 --offline 生成随机密钥到
    gitignored 的 src/_fcpk_key.py，之后复用（旧包可读）。"""
    import secrets
    kp = os.path.join(BASE, "src", "_fcpk_key.py")
    if os.path.isfile(kp):
        return kp
    pw = secrets.token_hex(16)
    with open(kp, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n"
                "# build.py 自动生成（勿提交勿手改）\n"
                "BUILD_KEY = %r\n" % pw)
    print("[fcpk] 已生成资源包密钥 src/_fcpk_key.py（gitignored）")
    return kp


def _password_fingerprint():
    """口令指纹（进资源包指纹——口令换了必须重打，旧包新 exe 读不了）。"""
    import hashlib as _hl
    from src.fcpk import _password
    try:
        return _hl.sha256(_password().encode("utf-8")).hexdigest()[:12]
    except Exception:
        return "nokey"


def _build_offline_fcpk(kinds=None, quiet=False, tag=""):
    """产出 dist/releases/<应用名>-资源包.fcpk（或 -资源包-<tag>.fcpk）。

    kinds=None 打全量；给列表则只打这些。tag 是文件名后缀（preset 传中文
    档名如「基础」，--kinds 传逗号串）。指纹（清单摘要）不变则沿用；
    写完立即全量验签，坏包绝不发布。

    子集包文件名带后缀——否则只打 claude 的小包会覆盖掉 706MB 的
    全量包（用户下次装机拿到的就只剩 claude 了）。
    """
    _ensure_fcpk_key()          # N6：必须在 docstring 之后，否则文档串失效
    import hashlib
    sys.path.insert(0, BASE)
    from src import fcpk
    files = _offline_sources(kinds)
    if not files:
        print("资源包: 无可用资源（offline_assets/ 不在或为空——新检出仓库按"
              " offline_assets/MANIFEST.json 恢复资源本体"
              + ("，或不含 %s" % ",".join(kinds) if kinds else "") + "），跳过")
        return None
    rel = os.path.join(BASE, "dist", "releases")
    os.makedirs(rel, exist_ok=True)
    suffix = ("-" + tag) if tag else ""
    dst = os.path.join(rel, "%s-资源包%s.fcpk" % (APP_NAME, suffix))
    h = hashlib.sha256()
    for p, arc, kind, mode, link in files:
        st = os.stat(p)
        h.update(("%s|%s|%d|%d" % (arc, kind, st.st_size,
                                   int(st.st_mtime))).encode("utf-8"))
    # 密钥变更也要触发重打（对抗审二轮：口令换仓后旧包读不了，指纹却不变
    # → 沿用旧口令包=新 exe 配旧包必失败）
    h.update(_password_fingerprint().encode("utf-8"))
    fp = h.hexdigest()[:16]
    # 指纹文件按产物分开——共用一份会让「刚打完 claude 子集包」把全量包的
    # 指纹覆盖掉，下次全量打包的续用判定就永远失效（白跑几分钟重打 706MB）
    fp_file = os.path.join(rel, "offline-pkg%s.fingerprint" % suffix)
    try:
        with open(fp_file, encoding="utf-8") as f:
            old = f.read().strip()
    except OSError:
        old = ""
    if old == fp and os.path.isfile(dst):
        print("资源包: 内容未变，沿用 %s（%d MB）"
              % (os.path.basename(dst), os.path.getsize(dst) // 1024 // 1024))
        return dst
    total_bytes = sum(os.path.getsize(p) for p, *_ in files)
    print("资源包: 打包 %d 个文件 / %.0f MB（加密 + 压缩，需数分钟）…"
          % (len(files), total_bytes / 1024 / 1024))
    resources = []
    for kind in ("webview2", "dotnet", "node", "git", "claude", "bili",
                 "onlyoffice", "pydeps"):
        n = sum(1 for x in files if x[2] == kind)
        if n:
            resources.append({"kind": kind, "files": n})
    w = fcpk.FcpkWriter(dst, resources=resources)
    try:
        # 进度条：按已写字节/总字节单行刷新（706MB~1.6GB 数分钟，只有首尾
        # 两行输出的黑盒体验被用户实锤）。每 pct 变化节流打印
        done_bytes = 0
        last_pct = -1
        for p, arc, kind, mode, link in files:
            w.add_file(p, arc, kind=kind, mode=mode, link_from=link)
            done_bytes += os.path.getsize(p)
            pct = int(done_bytes * 100 / total_bytes) if total_bytes else 100
            if pct != last_pct:
                print("\r资源包: 写入中 %3d%%  (%d / %d MB)"
                      % (pct, done_bytes // 1048576, total_bytes // 1048576),
                      end="", flush=True)
                last_pct = pct
        print()
        w.close()
    except Exception as e:
        print("资源包: 打包失败 %s" % e)
        # C4（全审）：早前删的是最终产物 dst，而写入用的是 dst+".building"
        # ——中途失败会把上一版可用的 673MB 好包删掉。只清临时文件。
        for _tmp in (dst + ".building", dst + ".tmp2"):
            try:
                os.remove(_tmp)
            except OSError:
                pass
        return None
    print("资源包: 验签 …")
    r = fcpk.FcpkReader(dst)
    r.verify_all()
    r.close()
    try:
        with open(fp_file, "w", encoding="utf-8") as f:
            f.write(fp)
    except OSError:
        pass
    sz = os.path.getsize(dst)
    print("资源包: 已发布 → %s (%d MB)" % (dst, sz // 1024 // 1024))
    _write_offline_manifest()
    return dst


def _write_offline_manifest():
    """a326（用户需求：资源本体不入 git，清单入 git）：扫描 offline_assets/
    生成 MANIFEST.json——新检出机器按清单的 url/note 恢复资源本体。
    单文件条目记 sha256（安装器类 <100MB）；目录类（claude-code/bili/
    webview2）记 version+文件数+总大小，不逐文件哈希（1.2 万文件太慢）。
    """
    import hashlib
    import json
    import time
    A = os.path.join(BASE, "offline_assets")
    if not os.path.isdir(A):
        print("manifest: offline_assets/ 不存在，跳过")
        return None

    def _sha256(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _dirstat(d):
        n = sz = 0
        for r, _, fs in os.walk(d):
            for f in fs:
                try:
                    sz += os.path.getsize(os.path.join(r, f)); n += 1
                except OSError:
                    pass
        return n, sz

    def _pkgver(d):
        try:
            with open(os.path.join(d, "package.json"), encoding="utf-8") as f:
                return json.load(f).get("version") or ""
        except Exception:
            return ""

    items = []
    inst = os.path.join(A, "install")
    urls = {  # 在线恢复/在线安装同源（a326 批2 在线安装复用）
        "git": "https://github.com/git-for-windows/git/releases/download/"
               "v2.55.0.windows.5/Git-2.55.0.5-64-bit.exe",
        "node": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-x64.msi",
        "dotnet": "https://download.visualstudio.microsoft.com/download/pr/"
                  "6a893f45-0810-4b11-9051-3b9ef0d1cf0e/4d6923c759e4cc4d34438f"
                  "2b57f4c06/ndp481-x86-x64-allos-enu.exe",
    }
    if os.path.isdir(inst):
        for name in sorted(os.listdir(inst)):
            p = os.path.join(inst, name)
            if not os.path.isfile(p):
                continue
            low = name.lower()
            kind = ("git" if low.startswith("git-") else
                    "node" if low.startswith("node-") else
                    "dotnet" if low.startswith("ndp481") else
                    "onlyoffice" if "onlyoffice" in low else None)
            if not kind:
                continue
            items.append({"kind": kind, "file": "install/" + name,
                          "size": os.path.getsize(p), "sha256": _sha256(p),
                          "url": urls.get(kind, ""),
                          "note": "官方直链，在线安装同源" if urls.get(kind)
                                  else "官网下载页获取"})
    oo = os.path.join(A, "onlyoffice", "onlyoffice-documentserver.exe")
    if os.path.isfile(oo):
        items.append({"kind": "onlyoffice", "file": "onlyoffice/"
                      "onlyoffice-documentserver.exe",
                      "size": os.path.getsize(oo), "sha256": _sha256(oo),
                      "url": "https://www.onlyoffice.com/download.aspx",
                      "note": "DS 安装器；在线安装用官方 download.aspx 直链"})
    for kind, sub in (("claude", "claude-code"), ("bili", "bili"),
                      ("webview2", "webview2"), ("codegraph", "codegraph")):
        d = os.path.join(A, sub)
        if not os.path.isdir(d):
            continue
        n, sz = _dirstat(d)
        # a419（用户实锤：codegraph 条目被 manifest 刷新静默丢掉）：a386 只
        # 手工补了条目、没教本扫描器——刷新即丢。codegraph 平台 bundle 的
        # package.json 在 lib/ 下（node.exe+lib 布局），先 lib 后根兜底
        _v = _pkgver(d)
        if kind == "codegraph" and not _v:
            _v = _pkgver(os.path.join(d, "lib"))
        items.append({
            "kind": kind, "dir": sub + "/", "files": n, "size": sz,
            "version": (_v if kind in ("claude", "bili", "codegraph") else
                        (sorted(os.listdir(d))[0] if kind == "webview2"
                         and os.listdir(d) else "")),
            "url": ("https://www.npmjs.com/package/@anthropic-ai/claude-code"
                    if kind == "claude" else
                    "https://www.npmjs.com/package/billion-context"
                    if kind == "bili" else
                    "https://www.npmjs.com/package/@colbymchenry/codegraph"
                    if kind == "codegraph" else
                    "tools/fetch_webview2_fixed.py 按版本下载（微软已下架直链）"),
            "note": ("npm 包整树镜像" if kind in ("claude", "bili") else
                     "发布机 npm i -g @colbymchenry/codegraph 后跑 "
                     "src/build.py _refresh_offline_codegraph 恢复"
                     "（平台 bundle win32-x64：node.exe+lib 自带运行时）"
                     if kind == "codegraph" else
                     "Fixed Version 运行时，恢复脚本见 url"),
        })
    pd = os.path.join(A, "pydeps")
    if os.path.isdir(pd):
        wheels = sorted(f for f in os.listdir(pd) if f.endswith(".whl"))
        if wheels:
            n, sz = _dirstat(pd)
            items.append({"kind": "pydeps", "dir": "pydeps/", "files": n,
                          "size": sz, "wheels": wheels,
                          "url": "pip download（requirements 见 wheel 名）",
                          "note": "离线 wheel 池，在线安装走 pip"})
    # a419：丢项告警——新清单比旧清单少的 kind 且本体仍在盘上=扫描器没认出
    # （codegraph 静默丢失实锤），必须大声报出来而不是静默写盘等提交
    _mf_path = os.path.join(A, "MANIFEST.json")
    try:
        _old = json.load(open(_mf_path, encoding="utf-8"))
        _old_kinds = {it.get("kind") for it in (_old.get("items") or [])}
        _new_kinds = {it.get("kind") for it in items}
        for _k in sorted(_old_kinds - _new_kinds):
            print("manifest: ⚠ 旧清单有 %s 条目但本次扫描未产出（本体在盘？"
                  "扫描器不认识该目录）——已保留旧条目防丢" % _k)
            _keep = next(it for it in _old["items"] if it.get("kind") == _k)
            items.append(_keep)
    except Exception:
        pass
    mf = {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": items,
          "note": "资源本体不入 git；本清单入库。新检出机器按各 item 的 "
                  "url/note 恢复 offline_assets/ 后才能打离线包。"}
    path = os.path.join(A, "MANIFEST.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mf, f, ensure_ascii=False, indent=2)
    print("manifest: %d 项已刷新 → %s（记得提交）" % (len(items), path))
    return path


def offline_main(argv):
    """只打离线资源包，不跑 PyInstaller（用户拍板：命令行 + bat 入口）。

    用法：
      python src/build.py --offline                    打全量（八项）
      python src/build.py --offline --preset base      基础资源包
      python src/build.py --offline --preset claude    claude 包
      python src/build.py --offline --preset ext       额外拓展包
      python src/build.py --offline --kinds claude     自定义只打某几项
      python src/build.py --offline --kinds claude,node --out D:\\交付

    为什么单独一个入口：完整打包要跑 PyInstaller（几分钟）+ 资源加密 +
    发布 zip，只想补一个资源包时没必要全跑；而且这东西是给「已经发出去的
    工具」补环境用的，与发布包版本不必同步。
    """
    import argparse
    import glob
    # 四档预设（用户需求：全量 / 基础 / claude / 额外拓展）。分组语义：
    #   基础 = 工具本体运行环境；claude = Claude 生态（CLI + 运行时 + 版本
    #   控制 + bili 内置引擎）；拓展 = OnlyOffice 全功能 Office 编辑。
    #   要调整分组改这里即可（安装端按 kind 装包，与分组无关）。
    presets = {
        "full":   {"label": "",       "kinds": None,
                   "desc": "全量（八项全含）"},
        "base":   {"label": "基础",    "kinds": ["webview2", "dotnet", "pydeps"],
                   "desc": "基础资源包（WebView2 + .NET + Python 依赖——工具本体环境）"},
        "claude": {"label": "claude", "kinds": ["claude", "node", "git", "bili"],
                   "desc": "claude 包（Claude CLI + Node + Git + bili 内置引擎）"},
        "ext":    {"label": "拓展",    "kinds": ["onlyoffice"],
                   "desc": "额外拓展包（OnlyOffice——Word/Excel/PPT 全功能编辑）"},
    }
    ap = argparse.ArgumentParser(
        prog="build.py --offline",
        description="只打离线资源包（.fcpk），不打包 exe")
    ap.add_argument("--offline", action="store_true", help="离线资源包模式")
    ap.add_argument("--preset", default="",
                    choices=sorted(presets),
                    help="四档预设：full 全量 / base 基础 / claude / ext 额外拓展")
    ap.add_argument("--kinds", default="",
                    help="自定义只打这些资源，逗号分隔：webview2,dotnet,node,git,"
                         "bili,claude,onlyoffice,pydeps；--preset 优先")
    ap.add_argument("--prep-bili", action="store_true",
                    help="先组装 bili 资源（node.exe + billion-context 依赖树，需联网）")
    ap.add_argument("--manifest", action="store_true",
                    help="只刷新 offline_assets/MANIFEST.json（资源清单入库用）")
    ap.add_argument("--out", default="",
                    help="额外复制一份到该目录（可选）")
    args = ap.parse_args(argv)

    if getattr(args, "manifest", False):
        _write_offline_manifest()
        return 0
    if getattr(args, "prep_bili", False):
        _prep_bili_dir()
        return
    if args.preset and args.preset != "full":
        pr = presets[args.preset]
        kinds = pr["kinds"]
        tag = pr["label"]
        title = pr["desc"]
    elif args.preset == "full":
        kinds, tag, title = None, "", "全量（八项全含）"
    else:
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
        valid = {"webview2", "dotnet", "node", "git", "claude", "bili",
                 "onlyoffice", "pydeps"}
        bad = [k for k in kinds if k not in valid]
        if bad:
            print("未知资源：%s（可选：%s）" % (",".join(bad), ",".join(sorted(valid))))
            return 2
        tag = "-".join(kinds)
        title = ",".join(kinds) if kinds else "全量"

    print("=" * 46)
    print("  离线资源包（%s）" % title)
    print("=" * 46)
    dst = _build_offline_fcpk(kinds, tag=tag)
    if not dst:
        print("[失败] 资源包未产出")
        return 1
    # 清理同名的历史子集包之外不做任何删除——全量包与子集包可以共存
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        tgt = os.path.join(args.out, os.path.basename(dst))
        shutil.copy2(dst, tgt)
        print("已复制到：%s" % tgt)
    print("\n[成功] %s（%.1f MB）"
          % (dst, os.path.getsize(dst) / 1024 / 1024))
    print("把这个文件发给需要的同事，工具里「设置 → 外部依赖安装」选它即可。")
    return 0


if __name__ == "__main__":
    if "--offline" in sys.argv:
        sys.exit(offline_main(sys.argv[1:]))
    build()
