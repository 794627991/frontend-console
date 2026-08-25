# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/AI/串口控制台Pro/main.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.'), ('app.ico', '.'), ('vendor', 'vendor')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除不需要的重依赖：pywebview 的 ssl extra 拉入 cryptography（17MB），
    # 但本应用用本地 HTTP 无需 SSL；paramiko/pdfminer/bcrypt/setuptools 也是无关间接依赖。
    # ssl/libcrypto/libssl 6MB+ 也排除：urllib 只访问 http://127.0.0.1 不需要 https。
    excludes=[
        'cryptography', 'bcrypt', 'paramiko', 'pdfminer', 'setuptools',
        'pkg_resources', 'ssl', '_ssl',
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
