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
    if not _under_roots(os.path.realpath(scope)):   # a234: junction 逃逸拒
        return jsonify({"ok": False, "err": "搜索范围包含指向根外的链接"}), 400
    smart_case = not bool(data.get("case"))       # 默认 smart-case（全小写=忽略大小写）
    use_regex = bool(data.get("regex")) or str(data.get("mode")) == "function"
    max_hits = min(int(data.get("maxResults") or MAX_HITS), 5000)

    if str(data.get("mode")) == "function":
        pattern = _func_regex(q)
    else:
        # a213 审计 P1：非正则模式追加 --fixed-strings——原再 re.escape 是
        # 双重转义，'open(file)'/'config.json' 等含元字符查询恒 0 命中
        pattern = q

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
    # a239 B4 + 复审F1/F3：--crlf 让 $ 锚定命中 CRLF 文件（Windows 主流形态），
    # 但它同时禁用正则里的字面 \r（rg rc=2 硬错被 --no-messages 静默=零命中）。
    # 折衷：仅文本模式（非正则）传 --crlf——正则模式用户自己写 \r?$ 最准。
    # 复审F1：注释吞参事故——--max-filesize 回归（a235 资源边界不能拆）
    cmd = [RG_EXE, "--json", "--no-messages",
           "--max-filesize", FILE_SIZE_CAP,
           "--max-count", "50",
           # a218：默认排除依赖/版本库目录（裸目录无 .gitignore 时也排除，
           # 与 VSCode 搜索默认行为对齐）
           "-g", "!node_modules", "-g", "!.git", "-g", "!vendor"]
    if not use_regex:
        cmd.append("--fixed-strings")
        cmd.append("--crlf")
    else:
        cmd.append("--engine")  # auto：回退到 rust 引擎不支持回溯的特性
        cmd.append("auto")
    if not smart_case:
        cmd.append("--case-sensitive")
    cmd += ["-e", pattern, scope]
    creationflags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             creationflags=creationflags)
    # a213 审计 P2：原直接 iter(readline)——rg 静默期阻塞 readline，客户端
    # 断开的 GeneratorExit 无 yield 点可投递，取消停不掉直到自然 EOF。读移
    # 后台线程推 queue，主生成器 0.5s 超时轮询——断开即刻可达 terminate
    import queue as _q
    _q1 = _q.Queue()
    def _reader():
        try:
            for raw in iter(proc.stdout.readline, b""):
                _q1.put(raw)
        finally:
            _q1.put(None)
    threading.Thread(target=_reader, daemon=True).start()
    try:
        hits = files = 0
        truncated = False
        cur_file = None
        _idle = 0
        while True:
            try:
                raw = _q1.get(timeout=0.5)
            except _q.Empty:
                _idle += 1
                if _idle % 4 == 0:   # a218：每 ~2s 扫描进度心跳（冷 IO 期不再死等）
                    yield _sse({"type": "progress", "files": files, "hits": hits})
                continue
            _idle = 0
            if raw is None:
                break
            if hits >= max_hits or files >= MAX_FILES:
                truncated = True
                proc.terminate()   # a233 审计 P1: 熔断即杀——原 wait() 无限挂到 rg 自然结束（实测 64s）且 close() 失效
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
                # a213 审计 P2：非 UTF-8 文件 rg 输出 lines.bytes（base64）
                # 而无 text——原取 text 恒空串（前端只见行号的空命中行）。
                # bytes 回退解码：utf-8 失败试 GB18030（域内中文文件主形态）
                txt = (d.get("lines") or {}).get("text", "")
                if not txt:
                    import base64 as _b64, binascii
                    b64 = (d.get("lines") or {}).get("bytes", "")
                    if b64:
                        try:
                            txt = _b64.b64decode(b64).decode("utf-8")
                        except binascii.Error:
                            txt = ""   # a233 P3: base64 损坏（非 Unicode 错）曾逃出生成器断流
                        except UnicodeDecodeError:
                            try:
                                txt = _b64.b64decode(b64).decode("gb18030", "replace")
                            except Exception:
                                txt = ""
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
        rc = proc.wait()
        if rc == 2:
            yield _sse({"type": "error", "err": "正则表达式无效"})
            return
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
