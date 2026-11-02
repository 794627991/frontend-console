# -*- coding: utf-8 -*-
"""文件树内容搜索（a209批3）：vendor rg.exe 封装 + SSE 流式输出。

对标 VSCode（其文件搜索同为 ripgrep）。链路：前端 POST /api/tree/search
（返回 text/event-stream）→ 本模块起 rg 子进程 --json 流式读行 → 逐事件
推给前端（file/match/summary）。取消：客户端断开（SSE 生成器 GeneratorExit）
→ 进程 terminate。

函数定义模式（mode=function）：per-语言函数定义正则 OR 组合（NAME 处
替换用户输入，字面转义防注入）。

安全：scope 必须 _under_roots（登记根白名单，同 /api/tree/list）。
性能：rg 子进程独立于 Flask 主进程（流畅度第一守则）；命中限额熔断。
"""
import os
import re
import json
import subprocess
import threading

from flask import Blueprint, request, Response, jsonify

from src.file_tree import _under_roots

tree_search_bp = Blueprint("tree_search", __name__)

RG_EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "vendor", "rg.exe")
MAX_HITS = 1000          # 命中熔断（防巨仓刷爆前端）
MAX_FILES = 200          # 文件数上限（同因）
FILE_SIZE_CAP = "4M"     # 单文件参与上限（rg --max-filesize）

# 函数定义模式（NAME=用户输入字面量；多语言 OR 组合——覆盖嵌入式常用域）
_FUNC_PATTERNS = [
    r"^\s*(?:static\s+|inline\s+|extern\s+)*[\w\*\s]+\bNAME\s*\(",   # C/C++ 定义/声明
    r"^\s*def\s+NAME\s*\(",                                          # Python
    r"\bfunction\s+NAME\s*\(",                                       # JS/TS
    r"^\s*(?:function\s+)?NAME\s*\(\s*\)\s*\{",                      # shell/awk
    r"^\s*NAME\s*:\s*function\s*\(",                                 # JS 对象方法
]


def _func_regex(name):
    lit = re.escape(name)
    return "|".join(p.replace("NAME", lit) for p in _FUNC_PATTERNS)


@tree_search_bp.route("/api/tree/search", methods=["POST"])
def tree_search():
    """SSE 流式内容搜索。body: {q, scope?, case?, regex?, mode?(text|function), maxResults?}"""
    data = request.get_json(force=True, silent=True) or {}
    q = str(data.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "err": "关键词为空"}), 400
    scope = _under_roots(str(data.get("scope") or ""))
    if not scope:
        return jsonify({"ok": False, "err": "搜索范围不在已登记根内"}), 400
    smart_case = not bool(data.get("case"))       # 默认 smart-case（全小写=忽略大小写）
    use_regex = bool(data.get("regex")) or str(data.get("mode")) == "function"
    max_hits = min(int(data.get("maxResults") or MAX_HITS), 5000)

    if str(data.get("mode")) == "function":
        pattern = _func_regex(q)
    else:
        pattern = q if use_regex else re.escape(q)

    return Response(_stream(scope, pattern, use_regex, smart_case, max_hits),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _stream(scope, pattern, use_regex, smart_case, max_hits):
    """起 rg 流式读 --json 行 → SSE。生成器被关闭（客户端断开）时 terminate。"""
    if not os.path.isfile(RG_EXE):
        yield _sse({"type": "error", "err": "未找到 vendor/rg.exe（搜索不可用）"})
        return
    cmd = [RG_EXE, "--json", "--no-messages", "--max-filesize", FILE_SIZE_CAP,
           "--max-count", "50"]
    if not use_regex:
        cmd.append("--fixed-strings")
    else:
        cmd.append("--engine")  # auto：回退到 rust 引擎不支持回溯的特性
        cmd.append("auto")
    if not smart_case:
        cmd.append("--case-sensitive")
    cmd += ["-e", pattern, scope]
    creationflags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             creationflags=creationflags, env=dict(os.environ, RG_UTF8="1"))
    try:
        hits = files = 0
        truncated = False
        cur_file = None
        for raw in iter(proc.stdout.readline, b""):
            if hits >= max_hits or files > MAX_FILES:
                truncated = True
                break
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            t = ev.get("type")
            if t == "begin":
                cur_file = (ev.get("data") or {}).get("path", {}).get("text", "")
                if cur_file:
                    files += 1
                    yield _sse({"type": "file", "path": cur_file})
            elif t == "match":
                d = ev.get("data") or {}
                line_no = d.get("line_number")
                txt = (d.get("lines") or {}).get("text", "")
                txt = txt.rstrip("\r\n")
                # 截窗（长行防 SSE 帧爆炸）
                if len(txt) > 240:
                    st = max(0, min(120, len(txt) - 120))
                    txt = ("…" if st > 0 else "") + txt[st:st + 240]
                else:
                    st = 0
                # 命中列（首个 submatch 起点换算列）
                col = 1
                subs = d.get("submatches") or []
                if subs:
                    col = (subs[0].get("start") or 0) + 1
                hits += 1
                yield _sse({"type": "match", "path": cur_file, "line": line_no,
                            "col": col, "text": txt})
            elif t == "done":
                break
        yield _sse({"type": "summary", "hits": hits, "files": files,
                    "truncated": truncated})
    except GeneratorExit:
        return   # 客户端断开：finally terminate
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
