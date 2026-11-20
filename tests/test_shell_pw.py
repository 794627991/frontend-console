# -*- coding: utf-8 -*-
"""壳内密码自动保存 / 选择式填充 —— 接线与安全边界的静态钉子。

用户定调终版（2026-11-20）：点密码框 → 弹出已存账号；登录 → 只问“是否
保存”；存储由工具内部 safeStorage 完成，不要求用户建库/输主密码/管理列表。
本文件钉住最容易在后续补丁里被静默改坏的结构。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _read_gbk(rel):
    with open(os.path.join(ROOT, rel), 'rb') as f:
        return f.read().decode('gbk')


def test_packaging_contains_all_password_files():
    pkg = json.loads(_read('electron/package.json'))
    files = pkg['build']['files']
    for name in ('main.js', 'preload.js', 'guest-preload.js',
                 'passwords.js', 'pw-ipc.js'):
        assert name in files, name
        assert os.path.exists(os.path.join(ROOT, 'electron', name)), name
    assert not any('kdbxweb' in f or 'vault-keepass' in f for f in files)
    bat = _read_gbk('打包壳.bat')
    for name in ('preload.js', 'guest-preload.js', 'passwords.js', 'pw-ipc.js'):
        assert name in bat, name
    assert 'vault-keepass.js' not in bat and 'kdbxweb' not in bat


def test_guest_preload_is_isolated_and_formless_capture():
    src = _read('electron/guest-preload.js')
    assert "require('electron')" in src
    assert 'contextBridge' not in src          # 不向页面暴露任何 API
    assert 'localStorage.' not in src
    assert 'window.top === window' in src      # 顶层帧限定
    assert "protocol === 'http:'" in src
    # 选择式填充：点字段上报候选请求；选中后才 fill；不再页面加载自动回填
    assert 'fc-pw:suggest' in src and 'fc-pw:fill' in src
    assert 'tryFill' not in src
    # autofocus/提交后 JS 回焦不弹：focus 只认点在字段上或 Tab
    assert 'suggestAllowedForFocus' in src
    assert 'lastPointerEl' in src and 'suppressUntil' in src
    # 🔑 菜单直填通道
    assert 'fc-pw:fill-now' in src
    # 无 form 登录（发布中心：单密码框 + 进入按钮、fetch 登录）也要能捕获
    assert 'LOGIN_RE' in src
    assert "addEventListener('click'" in src
    assert "addEventListener('keydown'" in src
    assert 'input[type=submit]' in src
    assert 'fc-pw:guest-get' not in src


def test_main_forces_guest_preload_and_guards_ipc():
    main = _read('electron/main.js')
    assert "GUEST_PRELOAD = path.join(__dirname, 'guest-preload.js')" in main
    assert "on('will-attach-webview'" in main
    assert 'webPreferences.preload = GUEST_PRELOAD' in main
    assert 'webPreferences.nodeIntegration = false' in main
    assert 'webPreferences.contextIsolation = true' in main
    assert 'webPreferences.sandbox = true' in main
    ipc = _read('electron/pw-ipc.js')
    assert "getType() !== 'webview'" in ipc
    assert 'f.parent' in ipc
    assert 'isMainUi' in ipc
    for ch in ('fc-pw:save', 'fc-pw:guest-capture', 'fc-pw:suggest', 'fc-pw:fill'):
        assert ch in ipc, ch
    assert 'vault' not in ipc                  # KeePass/建库卡已撤出用户路径
    main_src = main
    for ch in ('fc-pw:site-list', 'fc-pw:site-reveal', 'fc-pw:site-delete',
               'fc-pw:site-fill'):
        assert ch in main_src, ch


def test_store_uses_safe_storage_only():
    src = _read('electron/passwords.js')
    assert 'safeStorage.encryptString' in src
    assert 'safeStorage.decryptString' in src
    assert 'isEncryptionAvailable' in src
    assert 'writeFileSync(tmp, buf' in src
    assert 'JSON.stringify(cache)' in src
    assert "passwords.bin" in src


def test_ui_auto_flow_no_manager_no_keePass():
    ui = _read('web/js/web-panel.js')
    assert 'data-web="pw"' in ui
    # 🔑 保留：当前站点菜单（填充/显示/删除），不再有全站内置库/建库卡
    assert "pwBtn.style.display = 'none'" not in ui
    assert '_pwSiteMenu' in ui and 'pwSiteList' in ui and 'pwSiteFill' in ui
    assert 'window.fcShell.pwApi' not in ui
    assert '_pwVault' not in ui
    assert 'KeePass' not in ui
    assert 'onPwSuggest' in ui and 'onPwSavePrompt' in ui
    assert 'pw-suggest' in ui and 'pw-save-toast' in ui
    assert '_pwConfirm' in ui          # 删除确认用工具自绘，不用 Windows 原生白框
    pre = _read('electron/preload.js')
    assert 'onPwSuggest' in pre and 'onPwSavePrompt' in pre
    assert 'pwFill:' in pre and 'pwSave:' in pre
    assert 'pwSiteList:' in pre and 'pwSiteFill:' in pre
    assert 'pwVault' not in pre
