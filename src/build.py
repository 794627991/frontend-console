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
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", spec]

    print("打包命令:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=BASE)

    # v2.3.0 onedir：产物是应用目录（exe + _internal），exe 在目录内
    app_dir = os.path.join(BASE, "dist", APP_NAME)
    dist = os.path.join(app_dir, APP_NAME + ".exe")
    if os.path.exists(dist):
        sz = sum(os.path.getsize(os.path.join(r, f))
                 for r, _, fs in os.walk(app_dir) for f in fs) / 1024 / 1024
        print(f"\n打包成功: {app_dir} ({sz:.1f} MB)")
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


def _git_head():
    """当前 HEAD 短 hash。git 不可用返回 None。"""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=BASE, capture_output=True, text=True,
                             timeout=10, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _git_notes_since_last_publish(rel):
    """从 git 抽取更新说明：上次发布位点（releases/publish_head.txt）到当前
    HEAD 的提交标题，一行一条（去 hash、去 Co-Authored 尾巴）。没有位点
    （首次发布）取最近 20 条。抽取失败返回空串（回退到无说明）。"""
    import subprocess as sp
    head = _git_head()
    if not head:
        return ""
    marker = os.path.join(rel, "publish_head.txt")
    old = ""
    try:
        with open(marker, encoding="utf-8") as f:
            old = f.read().strip()
    except OSError:
        pass
    rng = "%s..HEAD" % old if old else "-20"
    try:
        out = sp.run(["git", "log", "--oneline", "--no-color", rng],
                     cwd=BASE, capture_output=True, text=True, timeout=15,
                     encoding="utf-8", errors="replace")
        if out.returncode != 0:
            return ""
        lines = []
        for ln in out.stdout.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            # 「abc1234 修 xxx：yyy」→ 取 hash 后的标题
            parts = ln.split(" ", 1)
            subject = parts[1].strip() if len(parts) == 2 else ln
            lines.append("· " + subject[:80])
        return "\n".join(lines[:30])[:1000]   # 上限：30 条/1000 字符
    except Exception:
        return ""


def _record_publish_head(rel):
    """记录本次发布对应的 git HEAD（下次发布抽取增量的位点）。"""
    head = _git_head()
    if not head:
        return
    try:
        with open(os.path.join(rel, "publish_head.txt"), "w", encoding="utf-8") as f:
            f.write(head)
    except OSError:
        pass


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
    # 说明三级来源（v2.3.1）：人工 RELEASE_NOTES.md 优先；没有则自动从 git
    # 抽取「上次发布以来」的提交标题（用户定调：更新内容体现到网页上，
    # 不想每次手写说明）；git 也不可用则留空。归档 notes-v<ver>.md 供门户
    # 更新日志逐版展示。
    notes = ""
    notes_path = os.path.join(BASE, "RELEASE_NOTES.md")
    if os.path.exists(notes_path):
        try:
            with open(notes_path, encoding="utf-8") as f:
                notes = f.read().strip()[:500]
        except OSError:
            pass
    if not notes:
        notes = _git_notes_since_last_publish(rel)
    if notes:
        try:
            with open(os.path.join(rel, "notes-v%s.md" % APP_VERSION),
                      "w", encoding="utf-8") as f:
                f.write(notes)
        except OSError:
            pass
    _record_publish_head(rel)
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
    print(f"  说明文件: RELEASE_NOTES.md（本次 {'已带' if notes else '未写，发布前补上更友好'}）")
    print("  ⚠ v2.2.x 及更早的 onefile 旧版无法自动升级到 zip 形态——"
          "需把 zip 发给同事手动解压换装一次（2.3.0 起全程自动）")


def _publish_offline_pkg():
    """v3.4.97（用户需求「offline_pkg 同步到 release 形成压缩包，发布页
    同步提供」）：dist/offline_pkg → dist/releases/<应用名>-offline-pkg-
    v<ver>.zip。发布页 _versions() 自动列出带 -v 的 zip——同事端门户即见
    即下。指纹（文件数+大小+mtime 汇总）不变且包在则跳过重压（几百 MB
    级）。刻意不写 manifest.json——自动更新器只认主应用包，离线资源绝
    不能被当应用更新推下去。"""
    import zipfile
    src = os.path.join(BASE, "dist", "offline_pkg")
    if not os.path.isdir(src):
        print("offline-pkg: dist/offline_pkg 不存在，跳过")
        return
    from src.version import APP_VERSION
    rel = os.path.join(BASE, "dist", "releases")
    os.makedirs(rel, exist_ok=True)
    dst = os.path.join(rel, "%s-offline-pkg-v%s.zip" % (APP_NAME, APP_VERSION))
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
    if old == fp and os.path.isfile(dst):
        print("offline-pkg: 内容未变，沿用 %s" % os.path.basename(dst))
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
