# -*- coding: utf-8 -*-
"""启动资源闸门的按钮组常量与引导分支（a647）。

用户实锤：内网同事机器缺 WebView2，打开工具弹出的「缺少运行环境」只有
「中止 / 重试 / 忽略」三个按钮——那是 MB_ABORTRETRYIGNORE(0x2) 的形态，
而代码写的是 `MB_YESNOCANCEL = 0x2`（winuser.h 里它是 0x3）。于是：
  · 界面要的「是 / 否 / 取消」变成「中止 / 重试 / 忽略」；
  · 点哪个都返回 IDABORT/IDRETRY/IDIGNORE，代码只认 IDYES/IDNO，
    全部落进 `return False` → 离线包和在线安装两条路都进不去。
内网没有外网，离线资源包是唯一出路，等于彻底堵死。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import res_ui  # noqa: E402


def test_messagebox_button_constants_match_winuser():
    """winuser.h：按钮组占低 4 位，各组合是占用值不是位标志。"""
    assert res_ui.MB_OK == 0x0
    assert res_ui.MB_OKCANCEL == 0x1
    assert res_ui.MB_ABORTRETRYIGNORE == 0x2
    assert res_ui.MB_YESNOCANCEL == 0x3
    assert res_ui.MB_YESNO == 0x4
    assert res_ui.MB_RETRYCANCEL == 0x5


def test_messagebox_return_ids_match_winuser():
    """返回值 ID* 必须与 winuser.h 一致——判定全靠它们。"""
    assert (res_ui.IDOK, res_ui.IDCANCEL, res_ui.IDABORT, res_ui.IDRETRY,
            res_ui.IDIGNORE, res_ui.IDYES, res_ui.IDNO) == (1, 2, 3, 4, 5, 6, 7)


def test_button_and_icon_flags_do_not_collide():
    """按钮组（低 4 位）与图标（0x10/0x30/0x40）不能重叠——重叠会让
    按钮组被图标位污染，弹出来的是另一套按钮。"""
    groups = [res_ui.MB_OK, res_ui.MB_OKCANCEL, res_ui.MB_ABORTRETRYIGNORE,
              res_ui.MB_YESNOCANCEL, res_ui.MB_YESNO, res_ui.MB_RETRYCANCEL]
    icons = [res_ui.MB_ICONERROR, res_ui.MB_ICONWARNING,
             res_ui.MB_ICONINFORMATION]
    for g in groups:
        assert g & 0xF0 == 0, "按钮组 %#x 与图标位重叠" % g
    for i in icons:
        assert i & 0x0F == 0, "图标 %#x 占用了按钮组位" % i


def test_guide_install_reaches_offline_on_yes(monkeypatch):
    """点「是」必须进离线包引导（内网唯一出路），不能被当取消丢掉。"""
    from src import res_boot
    hit = {}

    def fake_msgbox(text, title="", flags=0):
        # 同时断言按钮组是 YESNOCANCEL 而不是 ABORTRETRYIGNORE
        hit["group"] = flags & 0x0F
        return res_ui.IDYES

    def fake_offline(res):
        hit["offline"] = True
        return True

    monkeypatch.setattr(res_ui, "msgbox", fake_msgbox)
    monkeypatch.setattr(res_boot, "_guide_offline", fake_offline)
    res = {"items": [], "hard_missing": ["webview2"]}
    assert res_boot._guide_install(res) is True
    assert hit["group"] == res_ui.MB_YESNOCANCEL == 0x3, hit
    assert hit.get("offline"), "点「是」必须走离线包引导"


def test_guide_install_reaches_online_on_no(monkeypatch):
    from src import res_boot
    hit = {}
    monkeypatch.setattr(res_ui, "msgbox", lambda *a, **k: res_ui.IDNO)
    monkeypatch.setattr(res_boot, "_guide_online",
                        lambda res: hit.setdefault("online", True) or True)
    res = {"items": [], "hard_missing": ["webview2"]}
    assert res_boot._guide_install(res) is True
    assert hit.get("online")


def test_guide_install_cancel_exits(monkeypatch):
    from src import res_boot
    monkeypatch.setattr(res_ui, "msgbox", lambda *a, **k: res_ui.IDCANCEL)
    res = {"items": [], "hard_missing": ["webview2"]}
    assert res_boot._guide_install(res) is False


def test_guide_install_unknown_return_falls_back_to_offline(monkeypatch):
    """a647 兜底：未知返回值不能直接退出（内网机器没外网，离线包是唯一
    出路）。按钮组常量曾写错成 ABORTRETRYIGNORE，点哪个都返回 3/4/5。"""
    from src import res_boot
    hit = {}
    for rc in (res_ui.IDABORT, res_ui.IDRETRY, res_ui.IDIGNORE):
        hit.clear()
        monkeypatch.setattr(res_ui, "msgbox", lambda *a, _r=rc, **k: _r)
        monkeypatch.setattr(res_boot, "_guide_offline",
                            lambda res: hit.setdefault("offline", True) or True)
        res = {"items": [], "hard_missing": ["webview2"]}
        assert res_boot._guide_install(res) is True, "rc=%r 被当成退出" % rc
        assert hit.get("offline"), "rc=%r 未进入离线引导" % rc
