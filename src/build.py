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
        return dist
    else:
        print("打包失败：未找到 exe")
        return None

if __name__ == "__main__":
    build()
