# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：前端控制台 → 单 exe，无黑框。
源码整理后入口在 src/main.py，资源（web/、ico/、vendor、spec）在项目根。"""
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

    dist = os.path.join(BASE, "dist", APP_NAME + ".exe")
    if os.path.exists(dist):
        sz = os.path.getsize(dist) / 1024 / 1024
        print(f"\n打包成功: {dist} ({sz:.1f} MB)")
        _sync_offline_pkg(dist)
        _publish(dist)
        return dist
    else:
        print("打包失败：未找到 exe")
        return None


def _publish(dist_exe):
    """打包即发布（v2.1.0）：版本化拷贝到 dist/releases/ + 生成 manifest.json
    （版本/sha1/大小/日期/说明）。发布机开「升级分发服务」（设置页）后同事
    端「检查更新」即见此版。说明取版本说明文件，没有就留空。"""
    import hashlib, datetime
    sys.path.insert(0, BASE)
    from src.version import APP_VERSION
    rel = os.path.join(os.path.dirname(dist_exe), "releases")
    os.makedirs(rel, exist_ok=True)
    ver_name = "%s-v%s.exe" % (APP_NAME, APP_VERSION)
    dst = os.path.join(rel, ver_name)
    shutil.copy2(dist_exe, dst)
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
    print(f"\n[已发布] v{APP_VERSION} → {rel}")
    print(f"  sha1: {manifest['sha1']}")
    print(f"  同事升级地址: http://{_lan_ip()}:{PORT}/"
          f"（需在设置里开启「升级分发服务」）")
    print(f"  说明文件: RELEASE_NOTES.md（本次 {'已带' if notes else '未写，发布前补上更友好'}）")


def _sync_offline_pkg(dist_exe):
    """确保 dist/offline_pkg 与项目根 offline_pkg 同步（随包离线安装资源：
    Git 安装器 / Node MSI / claude-code 包，Claude 离线安装用）。
    PyInstaller 只产单 exe，offline_pkg 是旁挂目录——根目录有而 dist 没有
    就复制过去（根目录没有则不动 dist 已有的）。"""
    src_pkg = os.path.join(BASE, "offline_pkg")
    dst_pkg = os.path.join(os.path.dirname(dist_exe), "offline_pkg")
    if os.path.isdir(src_pkg) and not os.path.isdir(dst_pkg):
        print("复制 offline_pkg → dist/（Claude 离线安装资源，几百 MB 需几分钟）…")
        shutil.copytree(src_pkg, dst_pkg)
        print("offline_pkg 已同步到 dist/")
    # README 也放一份到 dist：帮助按钮在 exe 里读的是 _MEIPASS 内嵌副本（spec datas），
    # 但旁挂分发目录里放一份让人工翻阅/网盘下载者不打开 exe 也能看到说明书。
    src_rd = os.path.join(BASE, "README.md")
    dst_rd = os.path.join(os.path.dirname(dist_exe), "README.md")
    try:
        shutil.copy2(src_rd, dst_rd)
        print("README.md 已同步到 dist/")
    except OSError as e:
        print("README 同步失败（不影响 exe）:", e)

if __name__ == "__main__":
    build()
