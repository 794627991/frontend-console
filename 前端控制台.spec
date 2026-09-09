# -*- mode: python ; coding: utf-8 -*-


import os, sysconfig
# pywinpty 的 ConPTY 兄弟 exe（winpty-agent.exe / OpenConsole.exe）：运行时 winpty.dll
# 要把它们落盘到临时目录起 agent 进程，PyInstaller 不收集——必须显式 binaries。
# 按当前解释器的 site-packages 定位（打包者环境与使用者环境无关）。
_winpty_dir = os.path.join(sysconfig.get_paths()['purelib'], 'winpty')
_winpty_bins = [
    (os.path.join(_winpty_dir, f), 'winpty')
    for f in ('winpty-agent.exe', 'OpenConsole.exe')
    if os.path.isfile(os.path.join(_winpty_dir, f))
]

a = Analysis(
    ['D:/AI/串口控制台Pro/src/main.py'],
    pathex=[],
    binaries=_winpty_bins,
    datas=[('web', 'web'), ('ico', 'ico'), ('vendor', 'vendor'),
            ('README.md', '.')],
    hiddenimports=['paramiko',
        'src', 'src.main', 'src.server', 'src.mcp_server', 'src.app_state', 'src.ansi_utils', 'src.base_conn',
        'src.serial_conn', 'src.ssh_conn', 'src.log_index', 'src.tftp',
        'src.httpfile', 'src.editor_files', 'src.hex_files',
        # Claude 集成（第 1/2 期）：claude_conn 是延迟导入（_get_pty 内 import winpty），
        # 静态分析扫不到；claude_sessions 被 server 顶格 import 但保险起见也列上。
        # winpty 的包名与 pip 名不同（pip install pywinpty → import winpty）。
        'src.claude_conn', 'src.claude_sessions', 'winpty',
        'src.telnet_conn'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除不需要的重依赖：pdfminer/bcrypt/setuptools 是无关间接依赖。
    # 注意：paramiko/cryptography/ssl 已移出 excludes——SSH 集成需要 paramiko，
    # paramiko 依赖 cryptography + ssl。虽增 ~17MB，但 SSH 功能必需。
    excludes=[
        'pdfminer', 'setuptools',
        'pkg_resources',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='前端控制台',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 本机无 UPX 二进制，upx=True 实际不生效；关掉避免装了 UPX 的环境把
    # cryptography 的 _rust.pyd 压坏（paramiko/SSH 启动失败的已知先例）。
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:/AI/串口控制台Pro/ico/app.ico'],
)
