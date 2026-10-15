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
    dist = os.path.join(app_dir, APP_NAME + ".exe")
    if os.path.exists(dist):
        sz = sum(os.path.getsize(os.path.join(r, f))
                 for r, _, fs in os.walk(app_dir) for f in fs) / 1024 / 1024
        print(f"\n打包成功: {app_dir} ({sz:.1f} MB)")
        # v3.5.248（打包_debug.bat）：HG_NO_ENCRYPT=1 = 调试包——web 源码明文
        # （可直接查看/改），zip 照打（v3.5.248 用户定调「打包压缩还是要的」）
        # 但放 dist 根、不进 releases——升级分发流绝不收录调试包
        if DEBUG:
            print("调试包模式（HG_NO_ENCRYPT=1）：源码明文，zip 输出到 dist 根")
            _publish_debug(app_dir)
            return dist
        _refresh_offline_claude()   # v3.4.95：离线 claude-code 版本有变即刷新
        _sync_offline_pkg()
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
        _publish_offline_pkg()   # v3.4.97：离线资源包同步进 releases（发布页可下载）
        return dist
    else:
        print("打包失败：未找到 exe")
        return None


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
    skip_dirs = {".update", "data"}          # 运行时产物不进发布包
    skip_files = {"update.bat"}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for r, ds, fs in os.walk(app_dir):
            ds[:] = [d for d in ds if d not in skip_dirs]
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
    notes = ""
    notes_path = os.path.join(BASE, "RELEASE_NOTES.md")
    if os.path.exists(notes_path):
        try:
            with open(notes_path, encoding="utf-8") as f:
                notes = f.read().strip()[:500]
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


def _publish_offline_pkg():
    """v3.4.97（用户需求「offline_pkg 同步到 release 形成压缩包，发布页
    同步提供」）：dist/offline_pkg → dist/releases/<应用名>-offline-pkg.zip。
    不带版本号（用户定调：离线包内容是 Git/Node/claude-code/依赖，与工具
    版本无关）。发布中心 _offline_pkg() 单独通道列出——同事端门户即见
    即下。指纹（文件数+大小+mtime 汇总）不变则沿用；指纹未变但旧带版本
    号的包还在（v2.3.3 及之前的名），直接改名收编不重压（几百 MB 级）。
    刻意不写 manifest.json——自动更新器只认主应用包，离线资源绝不能被
    当应用更新推下去。"""
    import zipfile
    src = os.path.join(BASE, "dist", "offline_pkg")
    if not os.path.isdir(src):
        print("offline-pkg: dist/offline_pkg 不存在，跳过")
        return
    rel = os.path.join(BASE, "dist", "releases")
    os.makedirs(rel, exist_ok=True)
    dst = os.path.join(rel, "%s-offline-pkg.zip" % APP_NAME)
    n_files = total = 0
    for r, _, fs in os.walk(src):
        for f in fs:
            try:
                st = os.stat(os.path.join(r, f))
            except OSError:
                continue
            n_files += 1
            total += st.st_size + int(st.st_mtime)
    fp = "%d-%d" % (n_files, total)
    fp_file = os.path.join(rel, "offline-pkg.fingerprint")
    try:
        with open(fp_file, encoding="utf-8") as f:
            old = f.read().strip()
    except OSError:
        old = ""
    if old == fp:
        if os.path.isfile(dst):
            print("offline-pkg: 内容未变，沿用 %s" % os.path.basename(dst))
            return
        # 内容未变只是改了名（v2.3.3 及之前带 -v<ver>）：最新一份旧包直接
        # 改名收编，不重压
        olds = sorted(
            (n for n in os.listdir(rel)
             if n.startswith("%s-offline-pkg-v" % APP_NAME) and n.endswith(".zip")),
            key=lambda n: os.path.getmtime(os.path.join(rel, n)))
        if olds:
            os.replace(os.path.join(rel, olds[-1]), dst)
            print("offline-pkg: 内容未变，旧包改名收编 → %s" % os.path.basename(dst))
            return
    print("offline-pkg: 压缩 dist/offline_pkg → releases（几百 MB 需几分钟）…")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for r, _, fs in os.walk(src):
            for f in fs:
                p = os.path.join(r, f)
                z.write(p, os.path.join("offline_pkg", os.path.relpath(p, src)))
    try:
        with open(fp_file, "w", encoding="utf-8") as f:
            f.write(fp)
    except OSError:
        pass
    print("offline-pkg: 已发布 → %s (%d MB)" % (dst, os.path.getsize(dst) // 1024 // 1024))


def _refresh_offline_claude():
    """v3.4.95（用户需求「打包时 claude 版本也重新更新，如果有变化的话」）：
    本机 npm 全局的 @anthropic-ai/claude-code 与 offline_pkg/claude-code
    比对版本，不同则镜像刷新（根目录源 + dist 镜像两份）——离线安装资源
    不再停留在首次打包时的旧版。找不到本机安装（CI/未装）静默跳过。"""
    import json
    cands = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules",
                     "@anthropic-ai", "claude-code"),
    ]
    try:   # npm 前缀自定义过的机器
        out = subprocess.check_output(["npm", "root", "-g"], text=True,
                                      stderr=subprocess.DEVNULL, timeout=20).strip()
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
    src_v = _ver(src)
    # 版本基准取两处任一现存（根目录源或 dist 镜像——本机常只有 dist 份）
    dst_v = (_ver(os.path.join(BASE, "offline_pkg", "claude-code"))
             or _ver(os.path.join(BASE, "dist", "offline_pkg", "claude-code")))
    if not src_v or src_v == dst_v:
        print(f"offline claude-code: {dst_v or '无'} 与本机一致，无需刷新")
        return
    for dst in (os.path.join(BASE, "offline_pkg", "claude-code"),
                os.path.join(BASE, "dist", "offline_pkg", "claude-code")):
        if not os.path.isdir(os.path.dirname(dst)):
            continue
        print(f"offline claude-code: {dst_v or '无'} → {src_v} 刷新 {dst} …")
        # robocopy /MIR 镜像（几百 MB 级，Windows 自带，比 copytree 快且可续传）
        rc = subprocess.call(["robocopy", src, dst, "/MIR", "/NFL", "/NDL", "/NJH",
                              "/NJS", "/NP"], timeout=1800)
        if rc > 7:   # 0-7 均为成功档
            print(f"⚠ claude-code 刷新失败 (robocopy rc={rc}):", dst)


def _sync_offline_pkg():
    """确保 dist/offline_pkg 与项目根 offline_pkg 同步（随包离线安装资源：
    Git 安装器 / Node MSI / claude-code 包，Claude 离线安装用）。
    v2.3.0 onedir：offline_pkg 旁挂在 dist/ 级（不进应用目录——发布 zip
    只有应用本体几十 MB，离线资源几百 MB 单独按需分发）。"""
    src_pkg = os.path.join(BASE, "offline_pkg")
    dst_pkg = os.path.join(BASE, "dist", "offline_pkg")
    if os.path.isdir(src_pkg) and not os.path.isdir(dst_pkg):
        print("复制 offline_pkg → dist/（Claude 离线安装资源，几百 MB 需几分钟）…")
        shutil.copytree(src_pkg, dst_pkg)
        print("offline_pkg 已同步到 dist/")
    # README 放进应用目录（随 zip 分发，解压即可翻阅）
    src_rd = os.path.join(BASE, "README.md")
    dst_rd = os.path.join(BASE, "dist", APP_NAME, "README.md")
    try:
        shutil.copy2(src_rd, dst_rd)
    except OSError:
        pass

if __name__ == "__main__":
    build()
