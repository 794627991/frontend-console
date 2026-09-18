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
            ('README.md', '.'),
            # HikLink 机器人登录/注册的 marshal 字节码资产（hiklink_bot._his()
            # 按 __file__ 同目录读）——漏打包时同事的 exe 一登录注册就
            # FileNotFoundError，机器人永不启动（2026-09-16 实锤）
            ('src/_hiklink_his.blob', 'src')],
    hiddenimports=[
        # ---- v2.3.4 关键修正：excludes 'src' 后 src.* 不在模块图里，原先经
        # src.* 传递引入的第三方库会整批从打包图消失 → 冻结环境 import flask/
        # serial 失败 → 依赖自检误报缺库卡死（用户实锤「首次启动·安装依赖」）。
        # 这里显式列全部运行时第三方。
        'flask', 'serial', 'serial.tools', 'serial.tools.list_ports',
        'websocket',                      # websocket-client（HikLink 机器人 WS；
                                          # hiklink_bot try/except 静默吞缺失，
                                          # 表现=机器人永不运行，用户实锤）
        'webview',                       # pywebview（WebView2 桌面窗口）
        'paramiko', 'cryptography', 'nacl',   # SSH 链
        'winpty',                        # 内嵌 Claude 终端（ConPTY）
        'Crypto', 'Crypto.Cipher', 'Crypto.PublicKey', 'Crypto.Util.Padding',
        'Crypto.Util.number',            # pycryptodome（代理 CAS + 资源解密）
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
        'numpy',                         # proxy_usage 用量统计
        'yaml',                          # 配置解析
        'pystray', 'pystray._win32',     # 托盘历史兼容（现原生 Win32，保留无害）
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除不需要的重依赖：pdfminer/bcrypt/setuptools 是无关间接依赖。
    # 注意：paramiko/cryptography/ssl 已移出 excludes——SSH 集成需要 paramiko，
    # paramiko 依赖 cryptography + ssl。虽增 ~17MB，但 SSH 功能必需。
    # v2.3.1 excludes 'src'：自有模块一律不进 exe 内嵌 PYZ（反解包工具
    # pyinstxtractor+decompyle 可还原 pyc 源码，用户要求 exe 也不可反解）。
    # 自有 pyc 由 tools/encrypt_pkg.py 编译后以 AES 密文外置 _internal/src/，
    # exe 启动时 main.py 顶部内联自举解密后再 import——运行时 FrozenImporter
    # 找不到 src.* 自动回落文件系统加载解密后的平铺 pyc。
    excludes=[
        'pdfminer', 'setuptools',
        'pkg_resources',
        'src',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
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

# v2.3.0 onedir 模式（用户定调，治 exe 卡慢根因）：onefile 每次启动解压
# 52MB 到 %TEMP%、静态资源全从 TEMP 读，慢机+杀软扫描下启动/首开文件
# 卡顿数秒（同事机实锤）。onedir 依赖落盘在 exe 旁 _internal/，启动免解压、
# 资源原地读。分发/升级形态随之变为 zip（build.py 打包即发布 zip，
# updater 解压替换整个应用目录并保全 data/）。
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='前端控制台',
)
