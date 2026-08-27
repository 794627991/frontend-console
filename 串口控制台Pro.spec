# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/AI/串口控制台Pro/main.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.'), ('app.ico', '.'), ('vendor', 'vendor')],
    hiddenimports=['paramiko'],  # paramiko 改为延迟导入（_get_paramiko），PyInstaller 静态分析检测不到，需显式声明
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
    name='串口控制台Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:/AI/串口控制台Pro/app.ico'],
)
