# -*- coding: utf-8 -*-
"""ANSI 处理工具（从 web 版迁移，保持一致）。
纯函数模块，无外部依赖，被 base_conn / ai_routes / _patched_append 调用。
"""
import re

_ANSI_COLOR = {
    0: None, 30: "#6e7681", 31: "#ff7b72", 32: "#56d364", 33: "#e3b341",
    34: "#79c0ff", 35: "#d2a8ff", 36: "#39c5cf", 37: "#c9d1d9",
    90: "#8b949e", 91: "#ffa198", 92: "#7ee787", 93: "#f0e07a",
    94: "#a5d6ff", 95: "#d2a8ff", 96: "#56d4dd", 97: "#f0f6fc",
}
_ANSI_BG = {
    40: "#484f58", 41: "#67060c", 42: "#1a4730", 43: "#6b4600",
    44: "#0d2240", 45: "#4b0092", 46: "#005456", 47: "#57606a",
}
_ANSI_RE = re.compile(r"""
    \x1b\[ [0-?]* [ -/]* [@-~]
  | \x1b\] [^\x07\x1b]* (?:\x07|\x1b\\)
  | \x1b [=>]
  | \x1b[()][0AB0]
  | [\x00-\x08\x0b\x0c\x0e-\x1f]
""", re.VERBOSE)
_CSI_RE = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")

# 全屏刷新命令检测：top/htop 等用这些序列整屏重绘
# v0.3.1：改用 xterm.js 后，终端渲染交给前端 raw 流。后端 screen_mode 仅控制
# 前端"全屏模式"提示条的显示/隐藏，不再抑制 buf 逐行追加——这样 AI 通过
# /api/ai/* 始终能感知串口数据，不会因误进全屏而失明（修复 v0.3.0 感知异常）。
_SCREEN_STRONG_RE = re.compile(rb"\x1b\[\d*2J|\x1b\[\?1049h|\x1b\[H\x1b\[J", re.I)
_SCREEN_ANY_RE = re.compile(rb"\x1b\[[\d;]*[HJKsu]|\x1b\[\?1049[hl]|\x1b\[\d*2J|\x1b\[[\d;]*r", re.I)

_256_PALETTE = None
def _color256(n):
    global _256_PALETTE
    if _256_PALETTE is None:
        std = ["#000000","#aa0000","#00aa00","#aa5500","#0000aa","#aa00aa","#00aaaa","#aaaaaa",
               "#555555","#ff5555","#55ff55","#ffff55","#5555ff","#ff55ff","#55ffff","#ffffff"]
        pal = list(std)
        lv = [0,95,135,175,215,255]
        for r in lv:
            for g in lv:
                for b in lv:
                    pal.append(f"#{r:02x}{g:02x}{b:02x}")
        for k in range(24):
            v = 8 + 10*k
            pal.append(f"#{v:02x}{v:02x}{v:02x}")
        _256_PALETTE = pal
    if 0 <= n < len(_256_PALETTE):
        return _256_PALETTE[n]
    return None

def strip_ansi(text):
    return _ANSI_RE.sub("", text)

def ansi_to_html(text):
    out = []
    i = 0
    spans = []
    cur = {"fg": None, "bg": None, "bold": False, "italic": False, "underline": False}
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    def open_span():
        styles = []
        if cur["bold"]: styles.append("font-weight:700")
        if cur["italic"]: styles.append("font-style:italic")
        if cur["underline"]: styles.append("text-decoration:underline")
        if cur["fg"]: styles.append(f"color:{cur['fg']}")
        if cur["bg"]: styles.append(f"background:{cur['bg']}")
        if styles:
            out.append(f'<span style="{";".join(styles)}">')
            spans.append(True)
        else:
            spans.append(False)
    def close_span():
        if spans:
            if spans.pop():
                out.append("</span>")
    while i < len(text):
        m = _CSI_RE.match(text, i)
        if m:
            params = m.group(1)
            final = m.group(3)
            i = m.end()
            if final != "m":
                continue
            codes = [int(x) if x else 0 for x in params.split(";")]
            j = 0
            changed = False
            while j < len(codes):
                c = codes[j]
                if c == 0:
                    cur = {"fg": None, "bg": None, "bold": False, "italic": False, "underline": False}; changed = True
                elif c == 1: cur["bold"] = True; changed = True
                elif c == 3: cur["italic"] = True; changed = True
                elif c == 4: cur["underline"] = True; changed = True
                elif c == 22: cur["bold"] = False; changed = True
                elif c == 23: cur["italic"] = False; changed = True
                elif c == 24: cur["underline"] = False; changed = True
                elif 30 <= c <= 37 or 90 <= c <= 97: cur["fg"] = _ANSI_COLOR.get(c); changed = True
                elif 40 <= c <= 47: cur["bg"] = _ANSI_BG.get(c); changed = True
                elif c == 38 and j + 2 < len(codes) and codes[j+1] == 5: cur["fg"] = _color256(codes[j+2]); changed = True; j += 2
                elif c == 48 and j + 2 < len(codes) and codes[j+1] == 5: cur["bg"] = _color256(codes[j+2]); changed = True; j += 2
                elif c == 39: cur["fg"] = None; changed = True
                elif c == 49: cur["bg"] = None; changed = True
                j += 1
            if changed:
                close_span(); open_span()
            continue
        ch = text[i]
        if ch == "\x1b":
            i += 1
            if i < len(text): i += 1
            continue
        out.append(esc(ch))
        i += 1
    while spans:
        close_span()
    return "".join(out)

def classify_line(line):
    s = line.strip()
    if not s: return "empty"
    if s.startswith("[") and "]" in s and any(c.isdigit() for c in s[:12]):
        if "error" in s.lower() or "fail" in s.lower() or "panic" in s.lower() or "oops" in s.lower():
            return "kernel_err"
        return "kernel"
    if "U-Boot" in s or s.startswith("=>") or "Hit any key" in s: return "uboot"
    if "boot_debug" in s or "heop" in s.lower():
        if "fail" in s.lower(): return "heop_fail"
        if "succ" in s.lower() or "success" in s.lower() or "OK" in s: return "heop_ok"
        return "heop"
    if s.endswith("#") or s.endswith("# ") or s.endswith("$") or s == "#": return "prompt"
    return "text"
