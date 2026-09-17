# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：前端控制台 → onedir 应用目录（v2.3.0 起）。
源码整理后入口在 src/main.py，资源（web/、ico/、vendor、spec）在项目根。
产物 = dist/前端控制台/（exe + _internal/ 依赖），发布形态 = zip。"""
import os, sys, subprocess, shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根
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
        _sync_offline_pkg()
        _publish(app_dir)
        return dist
    else:
        print("打包失败：未找到 exe")
        return None


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
    notes = ""
    notes_path = os.path.join(BASE, "RELEASE_NOTES.md")
    if os.path.exists(notes_path):
        try:
            with open(notes_path, encoding="utf-8") as f:
                notes = f.read().strip()[:500]
            # v2.2.1：说明随版本归档——门户历史版本也能显示各自的更新说明
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
    print(f"  说明文件: RELEASE_NOTES.md（本次 {'已带' if notes else '未写，发布前补上更友好'}）")
    print("  ⚠ v2.2.x 及更早的 onefile 旧版无法自动升级到 zip 形态——"
          "需把 zip 发给同事手动解压换装一次（2.3.0 起全程自动）")


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
