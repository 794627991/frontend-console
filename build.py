# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：串口控制台 Pro → 单 exe，无黑框。"""
import os, sys, subprocess, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "串口控制台Pro"
MAIN = os.path.join(BASE, "main.py")
ICON = os.path.join(BASE, "app.ico")

def build():
    if not os.path.exists(ICON):
        print("图标不存在，跳过图标")
        icon_arg = []
    else:
        icon_arg = ["--icon", ICON]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",          # 无控制台黑框
        "--onefile",           # 单文件
        "--name", APP_NAME,
        "--add-data", f"index.html{os.pathsep}.",
        "--add-data", f"app.ico{os.pathsep}.",
    ] + icon_arg + [MAIN]

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
