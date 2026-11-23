# -*- coding: utf-8 -*-
"""UI 禁 emoji 铁律的自动防线（AGENTS.md，用户 2026-11-05 设定）。

铁律原文：前端控制台**渲染到界面的文本**绝对禁止彩色 emoji（⚠❌✅🟢 等）；
边界条款：✓ ✗ ⟳ ▾ 等单色文本字形是工程既有风格，允许；代码注释不受限。

2026-11-23 总审计实锤这道铁律一直在漏：a684 新写的两条告警用了 ⚠，
web-panel.js 的密码管理里还各有一处 ❌ 和 🔑——四处的共同点是没人拦。
本文件把它变成测试：

  1. 前端（web/js、web/*.html、web/css）**非注释位置**不得出现：
       · 铁律点名的四个：⚠ ❌ ✅ 🟢
       · 辅助平面 emoji 区 U+1F000~U+1FAFF 全部（🔑 🔧 📷 …——这些码位在
         Windows 上只有 Segoe UI Emoji 一种呈现，恒彩色，没有单色文本形式）
       · 变体选择符 U+FE0F（显式要求 emoji 呈现）
  2. 后端 `jsonify({...})` 里直接回给界面的文案键（err/info/msg/…）同上
     （日志类 say()/log() 文本是另一回事，不在此列）

**不在守卫内的**：▶ ↔ ⬆ ⏹ ⚙ ✳ ⏎ ↩ ↕ 这类 BMP 符号——它们在工程里早已
大量使用，属「单色文本字形」还是「默认彩色呈现」交用户裁定；裁定前不拿
它们当硬失败，免得守卫一上来把几十处既有按钮标红。

注释里的 emoji 允许（边界条款）。JS 注释识别按行进行、先判字符串再判
`//`：拿不准的情形（多行模板串跨行等）一律按「不是字符串」处理——
守卫宁可漏报，不可误报。
"""
import ast
import glob
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 铁律点名的四个（BMP）
NAMED = {0x26A0, 0x274C, 0x2705, 0x1F7E2}
VS16 = 0xFE0F
UI_TEXT_KEYS = {"err", "error", "info", "msg", "message", "tip", "warn",
                "warning", "label", "title", "text", "detail", "reason"}


def _banned(ch):
    o = ord(ch)
    return (o in NAMED or o == VS16 or 0x1F000 <= o <= 0x1FAFF
            or o == 0x20E3)                       #Combining Enclosing Keycap


def _js_code_hits(src):
    """[(行号, 字符)]：JS 源码里出现在**非注释**位置的禁用字符。"""
    hits = []
    in_block = False
    for no, line in enumerate(src.split("\n"), 1):
        i, n, q, esc = 0, len(line), None, False
        while i < n:
            c = line[i]
            if in_block:
                j = line.find("*/", i)
                if j < 0:
                    break                          # 块注释延续到下一行
                in_block = False
                i = j + 2
                continue
            if q:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == q:
                    q = None
                elif _banned(c):
                    hits.append((no, c))
                i += 1
                continue
            if c in "\"'`":
                q = c
            elif c == "/" and line.startswith("//", i):
                break                             # 行注释：余下不看
            elif c == "/" and line.startswith("/*", i):
                in_block = True
                i += 2
                continue
            elif _banned(c):
                hits.append((no, c))
            i += 1
    return hits


def _frontend_files():
    pats = ["web/js/**/*.js", "web/*.html", "web/css/*.css"]
    out = []
    for pat in pats:
        out.extend(glob.glob(os.path.join(ROOT, pat), recursive=True))
    return sorted(set(out))


def _file_hits(path):
    with io.open(path, encoding="utf-8") as f:
        src = f.read()
    if path.endswith(".js"):
        return _js_code_hits(src)
    # html / css：没有行注释，剥掉块注释后整篇查
    pat = r"<!--.*?-->" if path.endswith(".html") else r"/\*.*?\*/"
    body = re.sub(pat, "", src, flags=re.S)
    return [(body[:k].count("\n") + 1, ch) for k, ch in enumerate(body)
            if _banned(ch)]


def test_no_banned_emoji_in_frontend_ui_text():
    bad = []
    files = _frontend_files()
    assert len(files) > 50, "前端文件枚举异常（%d 个）" % len(files)
    for p in files:
        for no, ch in _file_hits(p):
            bad.append("%s:%d U+%04X" % (os.path.relpath(p, ROOT), no, ord(ch)))
    assert bad == [], ("界面文本出现铁律禁用的 emoji（改用 ICO16 图标或纯文字；"
                       "注释里不受限）：\n  " + "\n  ".join(bad))


def test_no_banned_emoji_in_backend_ui_messages():
    bad = []
    for p in sorted(glob.glob(os.path.join(ROOT, "src", "**", "*.py"), recursive=True)):
        with io.open(p, encoding="utf-8-sig") as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError as e:
                bad.append("%s 解析失败：%s" % (os.path.relpath(p, ROOT), e))
                continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "jsonify"):
                continue
            for a in node.args:
                if not isinstance(a, ast.Dict):
                    continue
                for k, v in zip(a.keys, a.values):
                    if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                            and k.value in UI_TEXT_KEYS
                            and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                        for ch in sorted({c for c in v.value if _banned(c)}):
                            bad.append("%s:%d %s 含 U+%04X" % (
                                os.path.relpath(p, ROOT), v.lineno, k.value, ord(ch)))
    assert bad == [], "回给界面的文案出现铁律禁用的 emoji：\n  " + "\n  ".join(bad)


# ---------------------------------------------------------------- 守卫自检

_JS_SAMPLE = r"""
const ok1 = '✓ 完成：' + n;                 // 单色文本字形：允许
// 注释里随便写：⚠ ❌ ✅ 🟢 🔑 🔧 📷
/* 块注释 ⚠ ❌ 也算注释 */
const bad1 = '⚠ 本次有 ' + n + ' 个子树';
const bad2 = '❌ ' + (j && j.err);
const bad3 = '（再点一次 🔑 重试）';
const bad4 = '✅ 已启用', bad5 = '🟢 在线';
const ok2 = 'http://example.com/' + '✓';    // 字符串里的 // 不是注释
const ok3 = "it's " + '▸';                  // 转义引号后状态不乱
const bad6 = '⚠<VS16>' ;                   // 变体选择符本身也禁
""".replace("<VS16>", chr(0xFE0F))      # 样本里要放真正的 U+FE0F，不是转义序列


def test_guard_catches_banned_and_ignores_comments():
    hits = _js_code_hits(_JS_SAMPLE)
    lines = sorted({no for no, _ch in hits})
    named = sorted({ch for _no, ch in hits})
    # 样本行号：1 空行 / 2 ok1 / 3 行注释 / 4 块注释 / 5~8 bad1~bad5 /
    # 9 ok2 / 10 ok3 / 11 bad6。恰好报 5 行 6 个字符；ok 行与注释行一行都不报
    assert lines == [5, 6, 7, 8, 11], lines
    assert named == sorted(["⚠", "❌", "🔑", "✅", "🟢", chr(0xFE0F)]), named


def test_guard_catches_html_and_css_comments_are_exempt():
    d = os.path.join(ROOT, "tests", "_emoji_guard_tmp")
    html = os.path.join(d, "a.html"); css = os.path.join(d, "b.css")
    os.makedirs(d, exist_ok=True)
    try:
        with io.open(html, "w", encoding="utf-8") as f:
            f.write("<!-- ✅ 🟢 注释 -->\n<div>⚠ 提示</div>\n")
        with io.open(css, "w", encoding="utf-8") as f:
            f.write("/* ❌ */\n.x::after { content: '🔑' }\n")
        assert [no for no, _c in _file_hits(html)] == [2]
        assert [no for no, _c in _file_hits(css)] == [2]
    finally:
        for p in (html, css):
            if os.path.exists(p):
                os.remove(p)
        if os.path.isdir(d):
            os.rmdir(d)


def test_guard_reports_backend_message():
    sample = ("from flask import jsonify\n"
              "def a():\n"
              "    return jsonify({'ok': False, 'err': '密码管理在 🔑 菜单'})\n"
              "def b():\n"
              "    return jsonify({'ok': True, 'err': '正常文案'})\n")
    bad = []
    for node in ast.walk(ast.parse(sample)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "jsonify" and node.args
                and isinstance(node.args[0], ast.Dict)):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if (isinstance(k, ast.Constant) and k.value in UI_TEXT_KEYS
                        and isinstance(v, ast.Constant)
                        and any(_banned(c) for c in v.value)):
                    bad.append(v.lineno)
    assert bad == [3]


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
