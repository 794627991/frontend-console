# -*- coding: utf-8 -*-
"""a624：调试能力常开 + 快捷键屏蔽 的语义钉子。

用户需求：run_debug.bat 退役（调试能力=常开），但**所有浏览器级快捷键
（F5/F12/Ctrl+R）必须屏蔽**，能力改由后端日志窗口的两个图标按钮承接。

本测钉住三点：
1. DEBUG_CAPS 常开；DEBUG_WEB（源码直读）仍只认环境变量且要求 web/ 存在
2. 主 UI 快捷键屏蔽已平移到 Electron 主窗 before-input-event（P4）
3. 日志窗有两个纯图标按钮，且整刷/DevTools 的入口都在
"""
import os
import re
import sys

sys.path.insert(0, '.')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_debug_caps_always_on():
    """调试能力常开；源码直读不可用（打包版）时必须降级到资源包。"""
    import src.server as s
    assert s.DEBUG_CAPS is True
    # 源码跑：web/ 存在 → 直读
    assert s.DEBUG_WEB is (os.path.isdir(os.path.join(ROOT, "web"))
                           and os.environ.get("HARNESS_DEBUG_WEB") == "1")


def test_packaged_falls_back_when_only_encrypted_assets(monkeypatch, tmp_path):
    """打包版 `<app>/_internal/web/` 里只有 *.enc 没有明文 index.html →
    必须判为「无源码树」，否则直读会 404 白屏。这里用真实行为验证。"""
    import src.server as s
    # 造一个只有加密资源的假 web 目录
    fake = tmp_path / "_internal"
    wd = fake / "web"
    wd.mkdir(parents=True)
    (wd / "index.html.enc").write_bytes(b"xxx")
    (wd / "style.css.enc").write_bytes(b"xxx")
    monkeypatch.setattr(s, "__file__", str(fake / "src" / "server.py"))
    assert s._has_src_web() is False
    # 有明文 index.html + js/ 才算源码树
    (wd / "index.html").write_text("<html></html>", encoding="utf-8")
    (wd / "js").mkdir()
    assert s._has_src_web() is True


def test_real_repo_has_src_web():
    """当前仓库确有明文前端树（源码跑时直读才成立）。"""
    import src.server as s
    assert s._has_src_web() is True


def test_accelerator_keys_disabled_main_ui_only():
    """主 UI 必须屏蔽浏览器级快捷键；网页 tab **不能**关（那里 F5/Ctrl+F
    是浏览器本职行为，关掉等于网页刷不了）。

    P4 换壳后落点从 pywebview 的 AreBrowserAcceleratorKeysEnabled 改为
    Electron 主窗 before-input-event；webview guest 不受主窗 handler 影响。
    """
    shell = _read("electron/main.js")
    assert shell.count("before-input-event") == 1
    seg = shell.split("before-input-event", 1)[1][:700]
    assert "'f5'" in seg and "'f12'" in seg
    assert "input.control" in seg and "e.preventDefault()" in seg


def test_backend_log_has_two_icon_buttons():
    """日志窗头部有两个纯图标按钮（无文字），悬浮有说明。"""
    js = _read("web/js/backend-log.js")
    assert 'data-bl="reload"' in js
    assert 'data-bl="devtools"' in js
    assert "ICO16.refresh" in js
    assert "ICO16.devtools" in js
    assert 'title="强制刷新（原 F5）"' in js
    assert 'title="打开开发者工具（原 F12）"' in js
    # 按钮体内不得有文字（自闭合空标签）
    assert re.search(r'data-bl="reload" title="[^"]*"></button>', js)


def test_devtools_icon_exists():
    """图标库里有 devtools 图标，风格与其他图标一致（16x16 画布）。"""
    ico = _read("web/js/icons.js")
    m = re.search(r"\n  devtools: '(.+)'", ico)
    assert m, "icons.js 缺 devtools 图标"
    d = m.group(1)
    assert "viewBox" not in d          # 由 _icoWrap 统一包
    assert "fill=" not in d            # 不能自带填充，随 currentColor


def test_hard_reload_defined_and_cleans_up():
    """整刷函数先清场再 reload（否则串口/SSH 句柄滞留后端）。"""
    html = _read("web/index.html")
    assert "window.__fcHardReload = function" in html
    seg = html.split("window.__fcHardReload = function", 1)[1][:400]
    assert "reload_disconnect" in seg
    assert "location.reload()" in seg


def test_window_controls_owned_by_shell():
    """P4：窗口控制不出现在后端（/api/window/* 已随旧窗体链删除），
    全部走 Electron IPC（fc:win-ctl / fc:win-state-*）。"""
    main = _read("src/main.py")
    assert '@app.route("/api/window/' not in main
    shell = _read("electron/main.js")
    assert "fc:win-ctl" in shell and "fc:win-state-get" in shell
    assert "fc:win-state" in shell


def test_run_debug_bat_retired():
    """run_debug.bat 已退役（调试能力已常开）；HARNESS_DEBUG_WEB 环境变量
    本身保留（源码直读仍用它）。"""
    assert not os.path.exists(os.path.join(ROOT, "run_debug.bat"))
    assert "HARNESS_DEBUG_WEB" in _read("src/server.py")


def test_debug_packaging_kept():
    """打包_debug.bat 必须保留——它是独立的「源码明文调试包」，与运行期的
    run_debug.bat 是两回事，不能一起退役。"""
    assert os.path.exists(os.path.join(ROOT, "打包_debug.bat"))
    build = _read("src/build.py")
    assert 'HG_NO_ENCRYPT' in build
    assert '_publish_debug' in build
