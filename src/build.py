# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：前端控制台 → onedir 应用目录（v2.3.0 起）。
源码整理后入口在 src/main.py，资源（web/、ico/、vendor、spec）在项目根。
产物 = dist/前端控制台/（exe + _internal/ 依赖），发布形态 = zip。"""
import os, re, sys, subprocess, shutil

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
    _sync_electron_version()
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
        # 发布守卫：
        # 1) web 明文目录必须在场（Flask 磁盘 serve 的唯一 UI 源）
        # 2) 已退役依赖反向校验——pywebview/pythonnet/clr_loader 一个都不许
        #    混进来（换壳 P4 后后端零 .NET 依赖，混入说明 spec/import 链回归）
        _need = [os.path.join(app_dir, "_internal", "web", "index.html")]
        for g in _need:
            if not os.path.exists(g):
                raise SystemExit("[发布守卫] 关键内容缺失：%s ——禁止发布，"
                                 "请检查 skip_top/打包配置后重打" % g)
        for _bad in ("webview", "pythonnet", "clr_loader"):
            _p = os.path.join(app_dir, "_internal", _bad)
            if os.path.exists(_p):
                raise SystemExit("[发布守卫] 已退役依赖被打进包：%s ——"
                                 "检查 spec hiddenimports / 遗留 import" % _p)
        print("[发布守卫] web 在场；webview/pythonnet/clr_loader 均未混入")
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
            # 密钥外发问题用户拍板（2026-11-23）：调试包只自用、绝不对外发布，
            # 完整性优先——**必须带全部源码**（含 _fcpk_key.py），不做排除。
            print(f"调试包: src 源码明文外置 {_n} 个 .py → _internal/src/")
            # 2026-11-23 内网实锤「启动巨慢」：frozen 环境不写 __pycache__，
            # 每次启动全量重编几百个明文 .py（内网再叠杀软逐文件实时扫描，
            # 每个明文读都过一遍引擎）。打包时预编译 .pyc 随包——同解释器
            # 3.14 出的缓存 magic 匹配，运行时 SourceFileLoader 直接命中、
            # 跳过编译；改 .py 调试不受影响（mtime 变了自动失效重编）。
            # 对抗审计修订：①pyc 命中率被 zip 的 DOS 时间戳偶数秒取整打掉
            # （奇数秒 mtime 的源解压后 pyc 判 stale）——先把源 mtime 归一
            # 到偶数秒再编译；②compile_dir 返回 bool 而非计数、失败不抛——
            # 必须显式拦包（a635 精神：编译失败禁止出包）
            import compileall
            _int_dir = os.path.join(app_dir, "_internal")
            for _r, _ds, _fs in os.walk(_int_dir):
                _ds[:] = [d for d in _ds if d != "__pycache__"]
                for _f in _fs:
                    if _f.endswith(".py"):
                        _p = os.path.join(_r, _f)
                        _st = os.stat(_p)
                        _even = int(_st.st_mtime) & ~1
                        os.utime(_p, (_even, _even))
            if not compileall.compile_dir(_int_dir, quiet=2, force=True,
                                          workers=4):
                raise SystemExit("[发布守卫] pyc 预编译失败（源码语法错？）"
                                 "——禁止发布")
            _npc = sum(len([f for f in fs if f.endswith(".pyc")])
                       for _, _, fs in os.walk(_int_dir))
            print(f"调试包: 预编译 pyc 完成（{_npc} 个 .pyc）")
            # 2026-11-24 用户令：debug **也出安装包**（与 release 同一
            # electron-builder 流程，唯一区别=后端带源码明文）。原 zip +
            # electron-shell 目录形态退役——安装包的 extraResources 会把
            # 本目录搬进 resources\backend\，派生布局与 release 完全一致，
            # installer.nsh 的数据保障（保留 resources\backend\data）自动
            # 生效，壳的路径约定也不用改。
            # 2026-11-24：退役形态残留清理。原 zip + electron-shell 目录形态
            # 已不再生成，但开发机 dist 里可能留着旧残留——留着有实害：
            # 双击 dist/前端控制台_debug/前端控制台/前端控制台.exe（无参数）时，
            # src/main.py 的调试包直启分支会向上探测到同级的
            # electron-shell/dist/electron.exe，拉起**旧壳**（界面与当前代码
            # 不符）。构建产物自动生成，删之无损。
            _ddir = os.path.join(BASE, "dist", APP_NAME + "_debug")
            for _stale in ("electron-shell", "ico"):
                _sp = os.path.join(_ddir, _stale)
                if os.path.isdir(_sp):
                    # 不用 ignore_errors：删不掉（旧进程占用）必须吭声，
                    # 否则「旧壳被误拉」的实害原样留存却毫无提示。
                    try:
                        shutil.rmtree(_sp)
                        print("已清理退役残留：%s" % _stale)
                    except OSError as _e:
                        print("[警告] 退役残留未清理干净：%s（%s）——"
                              "退出占用它的进程后重打" % (_sp, _e))
            import glob as _glob
            for _z in _glob.glob(os.path.join(BASE, "dist",
                                              APP_NAME + "_debug-v*.zip")):
                try:
                    os.remove(_z)
                    print("已清理退役残留：%s" % os.path.basename(_z))
                except OSError as _e:
                    print("[警告] 旧 zip 未删除：%s（%s）" % (_z, _e))
            _stamp_harness_version(app_dir)
            print("调试包后端就绪（源码明文）：%s" % app_dir)
            print("下一步由 打包_debug.bat 调 electron-builder 出安装包")
            return dist
        _refresh_offline_claude()   # v3.4.95：离线 claude-code 版本有变即刷新
        _refresh_offline_codegraph()   # a360：codegraph 同款（用户令工具内置——工作机无 npm 实锤）
        # a322：offline_pkg 三处分散资源已统一迁入 offline_assets/（MANIFEST
        # 入库、本体 gitignore），旧 _sync_offline_pkg 双目录同步随之退役；
        # 其尾部的 README 随包复制挪到这里
        try:
            shutil.copy2(os.path.join(BASE, "README.md"),
                         os.path.join(BASE, "dist", APP_NAME, "README.md"))
        except OSError:
            pass
        # v4.1（用户拍板）：WebView2 不再随包（换壳 P4 后 Electron 自带
        # Chromium，该项整体退役）；离线资源包 .fcpk 只保留可选集成
        # （node/git/claude/codegraph/onlyoffice/pydeps）。
        # 发布包随之从 318MB 降到约 65MB。
        # v4.1 换壳（Electron 迁移 P1，用户拍板）：资源加密链退役——web/ 由
        # spec datas 明文直带 _internal/web（磁盘 serve：secure_boot 见无
        # .fcenc 自动空转、FC_MEM_WEB 空、Flask 落磁盘读，运行时零改动）。
        # Cython pyd 外置**保留**（防抄=机器码层，与加密解耦的独立开关）。
        # 原 AES-GCM 链（encrypt_pkg → .fcenc → 启动自解密进内存）不再调用；
        # .fcdebug 哨兵照写——selftest 的「明文磁盘 serve」分支语义正好覆盖
        # 本形态（pyd src + 明文 web），省一个第三态
        try:
            from tools.encrypt_pkg import _stage_src_pyd
            _n = _stage_src_pyd(app_dir, BASE)
            print("pyd 外置: %d 个（web 明文直带——资源加密已随换壳退役）" % _n)
        except Exception as e:
            # a635（用户实锤 v2.4.4 死包启动 ModuleNotFoundError: src.version）：
            # 原来是「打印警告照常发布」——Cython 编译失败时 _internal/src/ 一个
            # pyd 都没有，包照发，同事装上必崩。编译是发布必经步骤，
            # 失败即停发，不许产出残缺包。
            raise SystemExit("[发布守卫] Cython 编译失败，禁止发布：%s" % e)
        try:
            open(os.path.join(app_dir, "_internal", ".fcdebug"), "w").close()
        except OSError:
            pass
        # a635：pyd 外置在 encrypt_pkg 里做，这里复核确实落了盘——空 src/
        # 的包启动就 ModuleNotFoundError，绝不能进分发流。
        _src_dir = os.path.join(app_dir, "_internal", "src")
        _npyd = 0
        _has_ver = False
        for _r, _ds, _fs in os.walk(_src_dir):
            for _f in _fs:
                if _f.endswith(".pyd"):
                    _npyd += 1
                    if _f.startswith("version."):
                        _has_ver = True
        if _npyd < 1 or not _has_ver:
            raise SystemExit("[发布守卫] _internal/src/ 缺少 Cython pyd"
                             "（找到 %d 个，version.pyd=%s）——禁止发布"
                             % (_npyd, _has_ver))
        print("[发布守卫] src pyd 校验通过（%d 个）" % _npyd)
        _stamp_harness_version(app_dir)
        _publish(app_dir)
        _build_offline_fcpk()    # v4.1：统一加密离线资源包（.fcpk）
        return dist
    else:
        print("打包失败：未找到 exe")
        return None


def _sync_electron_version():
    """把 src/version.py 的 APP_VERSION 同步进 electron/package.json。

    2026-11-24 用户实锤：安装包叫「调试版-Setup-0.1.0」，而工具版本是
    2.4.4。根因是 electron-builder 的产品版本只认 electron/package.json 的
    `version`（配置文件里**不允许** version 键，schema 无此项），那份是壳的
    占位 0.1.0，与 APP_VERSION 从来没连过——release 包同样中标。
    semver 原样写入；只有不同才改文件，避免每次打包都碰 git 工作区。
    """
    sys.path.insert(0, BASE)
    from src.version import APP_VERSION
    path = os.path.join(BASE, "electron", "package.json")
    lock = os.path.join(BASE, "electron", "package-lock.json")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    # 精确替换顶层 version 字段（electron/package.json 只有一处，见守卫）
    n = raw.count('"version"')
    if n != 1:
        raise SystemExit("[发布守卫] electron/package.json 的 \"version\" 出现"
                         " %d 次（应恰好 1 次），拒绝猜测改哪个" % n)
    new = re.sub(r'("version"\s*:\s*)"[^"]*"', r'\1"%s"' % APP_VERSION, raw,
                 count=1)
    changed = new != raw
    if changed:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    # package-lock 的根版本同步跟走（另两处 "version" 是自身条目与依赖，
    # 只改顶层与 packages[""]——按 JSON 结构改，不做文本替换）
    try:
        import json
        with open(lock, encoding="utf-8") as f:
            lk = json.load(f)
        hit = False
        if lk.get("version") != APP_VERSION:
            lk["version"] = APP_VERSION
            hit = True
        _root = lk.get("packages", {}).get("")
        if _root is not None and _root.get("version") != APP_VERSION:
            _root["version"] = APP_VERSION
            hit = True
        if hit:
            with open(lock, "w", encoding="utf-8", newline="\n") as f:
                json.dump(lk, f, ensure_ascii=False, indent=2)
                f.write("\n")
    except (OSError, ValueError) as e:
        print("[警告] package-lock.json 版本同步跳过：%s" % e)
    print(("壳版本已同步：" if changed else "壳版本已对齐：")
          + "electron/package.json -> %s（源自 src/version.py）" % APP_VERSION)


def _stamp_harness_version(app_dir):
    """把 git 推导的 harness 版本盖进包（用户实锤 exe 显示 a467 旧常量：
    frozen 无 .git 只能手 bump，80 个提交没人记得）。章落 _internal/
    harness_version.txt，_git_harness_version 的 frozen 分支读它——与
    源码 git 推导同源同格式（4.1.0-aNNN-<hash>）。"""
    sys.path.insert(0, BASE)
    try:
        from src.harness import _git_version_sync
    except Exception as e:
        raise SystemExit("[发布守卫] harness 版本盖章导入失败（%r）"
                         "——检查 src/harness 可导入性" % e)
    v = _git_version_sync(BASE)
    if not v:
        print("==============================================")
        print("[严重警告] harness 版本盖章取不到（git 异常/超时？）")
        print("  包内将回退兜底常量——exe 里显示旧版本号的老病会复发！")
        print("==============================================")
        return
    with open(os.path.join(app_dir, "_internal", "harness_version.txt"),
              "w", encoding="utf-8") as f:
        f.write(v + "\n")
    print("harness 版本盖章:", v)


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
    # skip_top 只对应用目录**顶层**生效（旧实现用裸目录名对任意深度匹配，
    # 曾把 _internal/pythonnet/runtime/ 误剔 → 发布死包）。换壳 P4 后
    # pythonnet/webview 已不在包内；runtime/ 仅兼容旧构建残留。
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
    """a360（用户实锤「说好的工具内置呢」）：codegraph 本体从 npm 全局刷到
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

# ---- a201→a407：billion-context 移出默认打包链（用户令：内网装不上，
# 默认包不背 200MB；唯一安装入口=代理面板联网 npm 装——见 src/proxy.py
# 的 /api/proxy/bili_install）。原 _prep_bili_dir 组装器随之退役。 ----


def _offline_sources(kinds=None):
    """收集离线资源清单。返回 [(src_path, arcname, kind, mode, link_from)]。

    kinds=None 收全量；否则只收这些 kind（用户拍板：默认全量，需要时可只打
    某几项，如 --kinds claude 单独出 270MB 的小包给只缺 Claude 的同事）。

    mode 取舍（实测压缩率）：.msi/.zip/.whl 已压缩过（1.01~1.05，再压反而
    变大）→ raw；.exe/.dll 值得压（Git 1.03、claude.exe 0.57）→ 只有明确的
    DLL/EXE 用 deflate。
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
            else:
                continue
            if _take(kind):
                out.append((p, "install/" + name, kind, mode, None))
    if os.path.isdir(src):
        # a407：bili 不再入包（唯一入口=代理面板联网装）
        cg = os.path.join(src, "codegraph")
        if os.path.isdir(cg) and _take("codegraph"):
            # a360：codegraph 平台 bundle（node.exe+lib 自带运行时）整目录
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
        # a309R：OnlyOffice DS 安装包（kind=onlyoffice）——a322 迁入
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
        # D（2026-11-23 用户拍板）：Electron 运行时 zip 入包——内网源码/
        # 调试形态无网也能起壳（正常发布走 Setup.exe 自带）。zip 已压缩
        # → raw；版本须与 electron/package.json 的 devDependency 对齐
        el = os.path.join(src, "electron")
        if os.path.isdir(el) and _take("electron"):
            for f in sorted(os.listdir(el)):
                if f.lower().endswith(".zip"):
                    out.append((os.path.join(el, f), "electron/" + f,
                                "electron", "raw", None))
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
        # 包体沿用也要刷新清单：退役 kind（webview2/dotnet）的旧条目必须在
        # MANIFEST 里消失，不能因为「文件没变」把过期清单一直带在仓库里
        _write_offline_manifest()
        return dst
    total_bytes = sum(os.path.getsize(p) for p, *_ in files)
    print("资源包: 打包 %d 个文件 / %.0f MB（加密 + 压缩，需数分钟）…"
          % (len(files), total_bytes / 1024 / 1024))
    resources = []
    for kind in ("node", "git", "claude", "codegraph",
                 "onlyoffice", "pydeps", "electron"):
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
    """a322（用户需求：资源本体不入 git，清单入 git）：扫描 offline_assets/
    生成 MANIFEST.json——新检出机器按清单的 url/note 恢复资源本体。
    单文件条目记 sha256（安装器类 <100MB）；目录类（claude-code/
    codegraph）记 version+文件数+总大小，不逐文件哈希。
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
    urls = {  # 在线恢复/在线安装同源（a322 批2 在线安装复用）
        "git": "https://github.com/git-for-windows/git/releases/download/"
               "v2.55.0.windows.5/Git-2.55.0.5-64-bit.exe",
        "node": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-x64.msi",
    }
    if os.path.isdir(inst):
        for name in sorted(os.listdir(inst)):
            p = os.path.join(inst, name)
            if not os.path.isfile(p):
                continue
            low = name.lower()
            kind = ("git" if low.startswith("git-") else
                    "node" if low.startswith("node-") else
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
    # D：Electron 运行时 zip（版本读 electron/package.json 对齐声明）
    _ev = ""
    try:
        with open(os.path.join(BASE, "electron", "package.json"),
                  encoding="utf-8") as _f:
            _ev = (json.load(_f).get("devDependencies") or {}).get("electron") or ""
    except Exception:
        pass
    eld = os.path.join(A, "electron")
    if os.path.isdir(eld):
        for f in sorted(os.listdir(eld)):
            p = os.path.join(eld, f)
            if os.path.isfile(p) and f.lower().endswith(".zip"):
                items.append({"kind": "electron", "file": "electron/" + f,
                              "size": os.path.getsize(p), "sha256": _sha256(p),
                              "url": "https://npmmirror.com/mirrors/electron/"
                                     + (f.split("-")[1].lstrip("v")
                                        if "-v" in f else "") + "/" + f,
                              "note": "Electron 运行时（devDependency %s）——"
                                      "源码/调试形态离线起壳；正常发布走 "
                                      "Setup.exe 自带" % _ev})
    # a407：bili 不再入清单（移出默认包）
    for kind, sub in (("claude", "claude-code"),
                      ("codegraph", "codegraph")):
        d = os.path.join(A, sub)
        if not os.path.isdir(d):
            continue
        n, sz = _dirstat(d)
        # a419（用户实锤：codegraph 条目被 manifest 刷新静默丢掉）：a360 只
        # 手工补了条目、没教本扫描器——刷新即丢。codegraph 平台 bundle 的
        # package.json 在 lib/ 下（node.exe+lib 布局），先 lib 后根兜底
        _v = _pkgver(d)
        if kind == "codegraph" and not _v:
            _v = _pkgver(os.path.join(d, "lib"))
        items.append({
            "kind": kind, "dir": sub + "/", "files": n, "size": sz,
            "version": _v,
            "url": ("https://www.npmjs.com/package/@anthropic-ai/claude-code"
                    if kind == "claude" else
                    "https://www.npmjs.com/package/@colbymchenry/codegraph"),
            "note": ("npm 包整树镜像" if kind == "claude" else
                     "发布机 npm i -g @colbymchenry/codegraph 后跑 "
                     "src/build.py _refresh_offline_codegraph 恢复"
                     "（平台 bundle win32-x64：node.exe+lib 自带运行时）"),
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
    # （codegraph 静默丢失实锤），必须大声报出来而不是静默写盘等提交。
    # 有意移出的资源允许从清单消失：bili→代理面板联网装；webview2/dotnet
    # →换壳 P4 后不再是工具依赖（Electron 自带 Chromium，无 pythonnet）
    _RETIRED = {"bili", "webview2", "dotnet"}
    _mf_path = os.path.join(A, "MANIFEST.json")
    try:
        _old = json.load(open(_mf_path, encoding="utf-8"))
        _old_kinds = {it.get("kind") for it in (_old.get("items") or [])}
        _new_kinds = {it.get("kind") for it in items}
        for _k in sorted(_old_kinds - _new_kinds - _RETIRED):
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
      python src/build.py --offline                    打全量（六项）
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
    # 三档预设（换壳 P4：工具本体已自足，资源包只剩可选集成）：
    #   claude = Claude 生态（CLI + Node + Git）；拓展 = OnlyOffice；full 全量。
    #   要调整分组改这里即可（安装端按 kind 装包，与分组无关）。
    presets = {
        "full":   {"label": "",       "kinds": None,
                   "desc": "全量（六项全含）"},
        "claude": {"label": "claude", "kinds": ["claude", "node", "git"],
                   "desc": "claude 包（Claude CLI + Node + Git）"},
        "ext":    {"label": "拓展",    "kinds": ["onlyoffice"],
                   "desc": "额外拓展包（OnlyOffice——Word/Excel/PPT 全功能编辑）"},
    }
    ap = argparse.ArgumentParser(
        prog="build.py --offline",
        description="只打离线资源包（.fcpk），不打包 exe")
    ap.add_argument("--offline", action="store_true", help="离线资源包模式")
    ap.add_argument("--preset", default="",
                    choices=sorted(presets),
                    help="三档预设：full 全量 / claude / ext 额外拓展")
    ap.add_argument("--kinds", default="",
                    help="自定义只打这些资源，逗号分隔：node,git,claude,"
                         "codegraph,onlyoffice,pydeps；--preset 优先")
    ap.add_argument("--manifest", action="store_true",
                    help="只刷新 offline_assets/MANIFEST.json（资源清单入库用）")
    ap.add_argument("--out", default="",
                    help="额外复制一份到该目录（可选）")
    args = ap.parse_args(argv)

    if getattr(args, "manifest", False):
        _write_offline_manifest()
        return 0
        return
    if args.preset and args.preset != "full":
        pr = presets[args.preset]
        kinds = pr["kinds"]
        tag = pr["label"]
        title = pr["desc"]
    elif args.preset == "full":
        kinds, tag, title = None, "", "全量（六项全含）"
    else:
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
        valid = {"node", "git", "claude", "codegraph",
                 "onlyoffice", "pydeps", "electron"}
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
