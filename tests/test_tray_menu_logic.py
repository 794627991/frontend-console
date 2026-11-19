# -*- coding: utf-8 -*-
"""托盘自绘菜单纯逻辑单测（不创建窗口、不弹菜单）。

覆盖审计点：_build_rows 归一化 / 键盘导航状态机 / 几何命中 /
文本量宽回归（GetTextExtentPoint32W 长度参数曾传 -1 全盘失败）/
焦点归还在销毁之前 / 子菜单打开时父项高亮保留 / 重入沿用首个原前台。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import tray_menu as tm          # noqa: E402


def _menu(items, scale=1.0):
    return tm._Menu(tm._build_rows(items), scale)


def test_build_rows_merges_seps():
    rows = tm._build_rows([("sep",), ("sep",), ("item", "A", None, {}),
                           ("sep",), ("item", "B", None, {}), ("sep",)])
    assert [r.get("text") for r in rows if not r.get("sep")] == ["A", "B"]
    assert sum(1 for r in rows if r.get("sep")) == 1


def test_build_rows_callable_and_submenu():
    rows = tm._build_rows([
        ("item", lambda: "动态", lambda: "cb",
         {"checked": lambda: True,
          "submenu": [("item", "子", None, {})]}),
    ])
    assert rows[0]["text"] == "动态"
    assert rows[0]["checked"] is True
    assert rows[0]["sub"][0]["text"] == "子"


def test_build_rows_skips_malformed():
    rows = tm._build_rows([("bad",), None, ("item", "ok", None, {})])
    assert [r["text"] for r in rows if not r.get("sep")] == ["ok"]


def test_step_skips_sep_and_disabled():
    m = _menu([("item", "A", None, {}),
               ("sep",),
               ("item", "D", None, {"enabled": False}),
               ("item", "B", None, {})])
    assert m._first_item() == 0
    assert m._step(0, 1) == 3          # 跳过 sep + 禁用
    assert m._step(3, 1) == 0          # 循环
    assert m._step(3, -1) == 0


def test_row_at_geometry_and_disabled():
    m = _menu([("item", "A", None, {}), ("sep",),
               ("item", "B", None, {}),
               ("item", "D", None, {"enabled": False})])

    def y_of(i):
        r = m.rows[i]
        return m.pad_y + r["top"] + r["h"] // 2

    assert m._row_at(y_of(0)) == 0
    assert m._row_at(y_of(1)) == -1      # 分隔线
    assert m._row_at(y_of(2)) == 2
    assert m._row_at(y_of(3)) == -1      # 禁用
    assert m._row_at(0) == -1            # 顶部 padding


def test_text_width_positive():
    dc = tm._g32.CreateCompatibleDC(None)
    try:
        w = tm._text_w(dc, tm._gfx(1.0)["font"], "关于 v2.4.4")
        assert w > 0
    finally:
        tm._g32.DeleteDC(dc)


def test_ensure_visible_keeps_scroll_in_bounds():
    items = [("item", "项%d" % i, None, {}) for i in range(40)]
    m = _menu(items)
    m.h = 200        # 模拟视口
    m._ensure_visible(0)
    assert m.scroll == 0
    m._ensure_visible(39)
    assert 0 <= m.scroll <= m.content_h - m.h
    m._ensure_visible(20)
    assert 0 <= m.scroll <= m.content_h - m.h


def test_close_all_restores_focus_before_destroy(monkeypatch):
    """焦点归还必须发生在 DestroyWindow 之前——销毁前台窗后本进程可能
    失去前台权限，再 SetForegroundWindow 会被前台锁静默拒绝。"""
    calls = []
    dummy = 0x1234
    monkeypatch.setattr(tm, "_MENUS",
                        {dummy: types.SimpleNamespace(hwnd=dummy)})
    monkeypatch.setattr(tm, "_PREV_FG", 0x5678)
    monkeypatch.setattr(tm._u32, "IsWindow", lambda h: True)
    monkeypatch.setattr(tm._u32, "SetForegroundWindow",
                        lambda h: calls.append(("fg", h)) or 1)
    monkeypatch.setattr(tm._u32, "DestroyWindow",
                        lambda h: calls.append(("destroy", h)) or 1)
    tm._close_all(restore_focus=True)
    assert [c[0] for c in calls] == ["fg", "destroy"]
    assert tm._PREV_FG is None


def test_hover_kept_when_child_open_on_leave():
    """光标从父菜单移进子菜单会触发父窗 MOUSELEAVE：父项高亮是从属指示，
    子菜单开着时必须保留；子菜单关掉后再移出才清。"""
    m = _menu([("item", "父", None,
                {"submenu": [("item", "子", None, {})]})])
    m.hwnd = 0x2222
    m.hover = 0
    m.child = types.SimpleNamespace(parent_index=0)
    tm._MENUS[m.hwnd] = m
    try:
        tm._menu_wndproc(m.hwnd, tm.WM_MOUSELEAVE, 0, 0)
        assert m.hover == 0
        m.child = None
        tm._menu_wndproc(m.hwnd, tm.WM_MOUSELEAVE, 0, 0)
        assert m.hover == -1
    finally:
        tm._MENUS.pop(m.hwnd, None)


def test_wheel_keeps_hover_when_child_open():
    """滚轮路径与 MOUSELEAVE 同口径：子菜单开着时滚动父菜单不能灭父项高亮。"""
    m = _menu([("item", "项%d" % i, None, {}) for i in range(20)])
    m.h = 100
    m.hover = 0
    m.child = types.SimpleNamespace(parent_index=0)
    m._wheel(-120)
    assert m.hover == 0
    m.child = None
    m.hover = 3
    m._wheel(-120)
    assert m.hover == -1


def test_reentry_keeps_first_prev_fg(monkeypatch):
    """菜单已开时再次右键（重入）：旧菜单销毁会让前台漂移，必须沿用第一次
    记录的原前台，不能把漂移后的窗口当成归还目标。"""
    class FakeMenu(object):
        def __init__(self, rows, scale):
            pass

        def show_at(self, x, y):
            pass

    monkeypatch.setattr(tm, "_Menu", FakeMenu)
    monkeypatch.setattr(tm._u32, "DestroyWindow", lambda h: 1)
    monkeypatch.setattr(tm, "_MENUS",
                        {0x3333: types.SimpleNamespace(hwnd=0x3333)})
    monkeypatch.setattr(tm, "_PREV_FG", 0x7777)
    try:
        cb = tm.show_menu(0, [("item", "A", None, {})])
        assert cb is None
        assert tm._PREV_FG == 0x7777
    finally:
        tm._MENUS.clear()
        tm._PREV_FG = None
