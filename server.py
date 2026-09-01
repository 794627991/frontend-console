#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端控制台 Pro —— 多串口/SSH 后端 + AI 接入层
- 每个串口一个 SerialPort 实例：独立线程读、独立环形缓冲、独立日志
- API 按串口 ID（端口名）路由
- AI 接入层：/api/ai/* 系列，AI 可查询任意串口实时数据、发送命令、订阅流
- 完全继承 web 版的 \r/\x08/ANSI 处理逻辑

功能模块拆分到 src/ 包：
- src/app_state.py：共享状态 + 路径常量 + 配置/命令库/seq 工具
- src/ansi_utils.py：ANSI 处理 + 行分类 + 全屏检测正则
- src/base_conn.py：连接基类（环形 buf/SSE/日志/读循环）
- src/serial_conn.py：串口连接（pyserial）+ list_ports
- src/ssh_conn.py：SSH 连接（paramiko 延迟导入）
- src/log_index.py：日志行偏移索引（G 级文件随机访问）
- src/tftp.py：TFTP 服务器 + Blueprint 路由
"""
import os, sys, time, threading, json, glob, re, base64, subprocess
from queue import Queue

from flask import Flask, Response, request, jsonify, send_from_directory

import src.app_state as _st
from src.app_state import (
    BASE_DIR, RES_DIR, STATE_DIR, CONFIG_FILE, LOG_DIR, DEFAULT_LOG_DIR, CMD_LIB_FILE,
    COMMON_BAUDS, _load_config, _save_config, _load_cmd_lib, _save_cmd_lib,
    _next_seq, _ports, _ports_lock, _ai_clients, _ai_clients_lock,
    _open_logs, _open_logs_lock, _mcp_calls, _mcp_calls_lock, _MCP_CALLS_MAX,
    _log_index_cache, _log_index_lock, _get_log_index, _broadcast_to_ai,
)
from src.ansi_utils import (
    strip_ansi, ansi_to_html, classify_line,
    _ANSI_COLOR, _ANSI_BG, _ANSI_RE, _CSI_RE, _color256,
    _SCREEN_STRONG_RE, _SCREEN_ANY_RE,
)
from src.base_conn import BaseConnection
from src.serial_conn import SerialPort, list_ports
from src.ssh_conn import SSHConnection, _get_paramiko
from src.tftp import tftp_bp, _tftp


app = Flask(__name__)

# 把未捕获异常的 traceback 写到日志文件，便于 exe（无控制台）模式下排查 500。
import logging
if not app.logger.handlers:
    _err_log_path = os.path.join(STATE_DIR, "server_errors.log")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        _h = logging.FileHandler(_err_log_path, encoding="utf-8")
        _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        app.logger.addHandler(_h)
        app.logger.setLevel(logging.ERROR)
    except Exception:
        pass

# 注册 TFTP Blueprint（路由 /api/tftp/*）
app.register_blueprint(tftp_bp)

# ---- 全局串口表（_ports/_ports_lock 来自 app_state，此处定义 close_all_ports）----
def close_all_ports():
    with _ports_lock:
        for p in list(_ports.values()):
            p.close()
        _ports.clear()

# hook 到 SerialPort.append_line：AI 全局流挂载点（猴子补丁，import serial_conn 后执行）
# hook 到 SerialPort.append_line
_orig_append = SerialPort.append_line
def _patched_append(self, raw_line, local_echo=False):
    _orig_append(self, raw_line, local_echo)
    ts_ms = int(time.time() * 1000)
    clean = strip_ansi(raw_line)
    _broadcast_to_ai({"ts": ts_ms, "text": clean, "port": self.port_id, "tag": classify_line(clean)})
SerialPort.append_line = _patched_append

def start_background():
    """启动后台维护线程。"""
    def _cleanup():
        while True:
            time.sleep(30)
            # 清理超过 7 天的日志
            try:
                cutoff = time.time() - 7*86400
                for f in glob.glob(os.path.join(LOG_DIR, "serial_*.log")):
                    if os.path.getmtime(f) < cutoff:
                        os.remove(f)
            except Exception:
                pass
    t = threading.Thread(target=_cleanup, daemon=True)
    t.start()

# ============================================================
# Flask 路由
# ============================================================
@app.route("/")
def index():
    return send_from_directory(RES_DIR, "index.html")

@app.route("/<path:fn>")
def static_files(fn):
    return send_from_directory(RES_DIR, fn)

@app.route("/api/ports")
def api_ports():
    return jsonify({"ports": list_ports(), "bauds": COMMON_BAUDS})

@app.route("/api/status")
def api_status():
    with _ports_lock:
        info = {}
        for pid, p in _ports.items():
            info[pid] = {
                "port": p.port, "baud": p.baud, "recording": p.recording,
                "log_path": p.log_path, "buf_lines": len(p.buf),
                "clients": len(p.clients), "cmd_history_count": len(p.cmd_history),
                "kind": getattr(p, "kind", "serial"),
                "host": getattr(p, "host", None), "username": getattr(p, "username", None),
            }
    return jsonify({"ports": info, "log_dir": LOG_DIR})

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(force=True)
    kind = data.get("kind", "serial")
    if kind == "ssh":
        # SSH 连接
        host = (data.get("host") or "").strip()
        port = data.get("port") or 22
        username = (data.get("username") or "").strip()
        password = data.get("password")
        key_path = (data.get("key_path") or "").strip() or None
        if not host or not username:
            return jsonify({"ok": False, "err": "need host and username"}), 400
        if not password and not key_path:
            return jsonify({"ok": False, "err": "need password or key_path"}), 400
        if _get_paramiko() is None:
            return jsonify({"ok": False, "err": "paramiko 未安装，无法 SSH 连接"}), 500
        port_id = f"ssh:{host}:{port}"
        with _ports_lock:
            if port_id in _ports:
                return jsonify({"ok": False, "err": f"{port_id} 已连接"})
            try:
                p = SSHConnection(host, port, username, password=password, key_path=key_path, port_id=port_id)
                _ports[port_id] = p
            except Exception as e:
                return jsonify({"ok": False, "err": str(e)}), 500
        # SSH invoke_shell 自带 shell，不主动 send \r
        return jsonify({"ok": True, "port_id": port_id, "kind": "ssh",
                        "msg": f"已连接 {username}@{host}:{port}"})
    else:
        # 串口连接（默认）
        port = data.get("port")
        baud = data.get("baud")
        if not port or not baud:
            return jsonify({"ok": False, "err": "need port and baud"}), 400
        port_id = port
        with _ports_lock:
            if port_id in _ports:
                return jsonify({"ok": False, "err": f"{port} 已连接"})
            try:
                p = SerialPort(port, baud, port_id)
                _ports[port_id] = p
            except Exception as e:
                return jsonify({"ok": False, "err": str(e)}), 500
        # 触发提示符
        try:
            p.send_raw(b"\r")
        except Exception:
            pass
        return jsonify({"ok": True, "port_id": port_id, "kind": "serial", "msg": f"已连接 {port}@{baud}"})

@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.pop(port_id, None)
    if p:
        p.close()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "err": "未找到该串口"}), 404

@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    cmd = data.get("cmd", "")
    newline = data.get("newline", True)
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 500
    try:
        p.send_cmd(cmd, newline)
        echo = cmd + ("\r" if newline else "")
        p.append_line(echo, local_echo=True)
        return jsonify({"ok": True, "sent": cmd})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/send_raw", methods=["POST"])
def api_send_raw():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    byte_list = data.get("bytes", [])
    if not isinstance(byte_list, list):
        return jsonify({"ok": False, "err": "bytes must be list"}), 400
    payload = bytes(int(b) & 0xFF for b in byte_list if isinstance(b, (int, float)))
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 500
    try:
        if payload:
            p.send_raw(payload)
        return jsonify({"ok": True, "sent": len(payload)})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/history")
def api_history():
    port_id = request.args.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"history": []})
    return jsonify({"history": p.get_history()})

@app.route("/api/buffer")
def api_buffer():
    port_id = request.args.get("port_id")
    n = int(request.args.get("n", 500))
    before_seq = request.args.get("before_seq")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"lines": [], "has_more": False})
    if before_seq:
        try:
            bs = int(before_seq)
        except ValueError:
            bs = 0
        lines, has_more = p.get_buffer_before(bs, n)
        return jsonify({"lines": lines, "has_more": has_more})
    return jsonify({"lines": p.get_buffer(n), "has_more": len(p.buf) > n})

@app.route("/api/search")
def api_search():
    """在指定串口的 buf 全量搜索关键字。"""
    port_id = request.args.get("port_id")
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 200))
    before_seq = request.args.get("before_seq")
    bs = int(before_seq) if before_seq else 0
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接", "total": 0, "lines": [], "has_more": False})
    res = p.search_lines(q, limit=limit, before_seq=bs)
    res["ok"] = True
    res["port_id"] = port_id
    # 命中行只回纯文本，省带宽
    res["lines"] = [{"seq": it["seq"], "ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in res["lines"]]
    return jsonify(res)

@app.route("/api/logs")
def api_logs():
    """日志库文件列表。sort：time_desc（默认，最新在前）/ time_asc / name_asc / name_desc / size_desc。"""
    files = []
    if os.path.isdir(LOG_DIR):
        for f in glob.glob(os.path.join(LOG_DIR, "serial_*.log")):
            files.append({"name": os.path.basename(f), "size": os.path.getsize(f), "mtime": int(os.path.getmtime(f))})
    sort = (request.args.get("sort") or "time_desc").strip()
    if sort == "time_asc":    files.sort(key=lambda x: x["mtime"])
    elif sort == "name_asc":  files.sort(key=lambda x: x["name"])
    elif sort == "name_desc": files.sort(key=lambda x: x["name"], reverse=True)
    elif sort == "size_desc": files.sort(key=lambda x: x["size"], reverse=True)
    else:                     files.sort(key=lambda x: x["mtime"], reverse=True)  # time_desc 默认
    return jsonify({"logs": files, "dir": LOG_DIR})

@app.route("/api/log_dir", methods=["GET", "POST"])
def api_log_dir():
    """GET 返回当前日志目录；POST 设置新目录（持久化，立即生效，日志库从此读新目录）。"""
    global LOG_DIR
    if request.method == "GET":
        return jsonify({"ok": True, "dir": LOG_DIR, "default": DEFAULT_LOG_DIR})
    data = request.get_json(force=True) or {}
    new_dir = (data.get("dir") or "").strip()
    # 空字符串表示恢复默认目录
    if not new_dir:
        new_dir = DEFAULT_LOG_DIR
    new_dir = os.path.abspath(new_dir)
    try:
        os.makedirs(new_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "err": f"无法创建目录: {e}"}), 400
    if not os.access(new_dir, os.W_OK):
        return jsonify({"ok": False, "err": "目录不可写"}), 400
    LOG_DIR = new_dir
    _st.LOG_DIR = new_dir  # 同步 app_state：base_conn._start_log 读模块属性，改目录对新连接立即生效
    _save_config({**_load_config(), "log_dir": new_dir})
    return jsonify({"ok": True, "dir": LOG_DIR})


@app.route("/api/log_dir/open", methods=["POST"])
def api_log_dir_open():
    """用系统资源管理器打开日志目录。WebView2 拦截 file:// 协议，必须后端调 explorer。"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        target = (data.get("dir") or LOG_DIR).strip()
        if not target:
            target = LOG_DIR
        os.makedirs(target, exist_ok=True)
        # os.startfile 在 pywebview Flask 线程里可能静默失败，改用 explorer.exe 更可靠
        import subprocess
        subprocess.Popen(["explorer.exe", target], close_fds=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400

@app.route("/api/open_log_file", methods=["POST"])
def api_open_log_file():
    """在资源管理器中打开日志目录并选中指定日志文件（仅 Windows 支持 /select）。"""
    data = request.get_json(force=True)
    name = data.get("name")
    if not name:
        return jsonify({"ok": False, "err": "need name"}), 400
    path = os.path.join(LOG_DIR, name)
    try:
        if not os.path.isfile(path):
            return jsonify({"ok": False, "err": "not found"}), 404
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer.exe", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", LOG_DIR])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/log/<name>")
def api_log_read(name):
    path = os.path.join(LOG_DIR, name)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "err": "not found"}), 404
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return Response(f.read(), mimetype="text/plain")

@app.route("/api/replay/<name>")
def api_replay(name):
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.startswith("#"): continue
            parts = ln.split("\t", 2)
            if len(parts) == 3 and parts[0].isdigit():
                lines.append({"ts": int(parts[0]), "tag": parts[1], "text": parts[2], "html": None})
    return jsonify({"lines": lines})


# ---- G 级历史翻阅：日志行索引 + 分页 + 搜索 ----
def _resolve_log_path(name_or_path):
    """解析日志路径：支持 LOG_DIR 内文件名，也支持外部绝对路径。
    防路径穿越：LOG_DIR 内文件名不允许含 .. 逃逸。"""
    if os.path.isabs(name_or_path) and os.path.isfile(name_or_path):
        return name_or_path
    # 防穿越：规范化后必须在 LOG_DIR 内
    p = os.path.normpath(os.path.join(LOG_DIR, name_or_path))
    if not os.path.realpath(p).startswith(os.path.realpath(LOG_DIR) + os.sep) and os.path.realpath(p) != os.path.realpath(LOG_DIR):
        return None
    if os.path.isfile(p):
        return p
    return None

@app.route("/api/log_count")
def api_log_count():
    """返回日志总行数。name=日志名或绝对路径。"""
    name = request.args.get("name", "")
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    if not idx._loaded:
        idx.build()
    return jsonify({"ok": True, "total": idx.total, "path": path})

@app.route("/api/log_page")
def api_log_page():
    """按行号分页读取日志。name=日志名或绝对路径，offset=起始行(0-based)，limit=行数。"""
    name = request.args.get("name", "")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 100))
    limit = min(limit, 500)  # 单次上限防大请求
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    lines = idx.get_page(offset, limit)
    return jsonify({"ok": True, "lines": lines, "offset": offset, "total": idx.total})

@app.route("/api/log_search")
def api_log_search():
    """在日志文件搜索关键字。name=日志名或绝对路径，q=关键字，offset=起始行，limit=命中上限。"""
    name = request.args.get("name", "")
    q = request.args.get("q", "")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 200))
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    res = idx.search(q, limit=limit, start_offset=offset)
    return jsonify({"ok": True, **res})

@app.route("/api/log_open_external", methods=["POST"])
def api_log_open_external():
    """打开外部日志文件（任意路径），返回可用的 name 标识供后续 log_count/page/search 用。
    body: {path: 绝对路径}。"""
    data = request.get_json(force=True, silent=True) or {}
    p = (data.get("path") or "").strip()
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    return jsonify({"ok": True, "name": p, "size": os.path.getsize(p)})


@app.route("/api/ai/diff_logs", methods=["POST"])
def ai_diff_logs():
    """对比两份日志，返回差异。BSP 常用于对比"正常启动 vs 异常启动"日志。
    body: {a: 路径1, b: 路径2, mode: "line"|"summary", context: 上下文行数}
    - mode=line：行级 diff（基于 text 内容忽略时间戳），输出增/减/变化块
    - mode=summary：去重摘要，对比两份日志各自唯一行 + 出现次数，按频次差异排序
    context：line 模式下差异块上下文行数（默认 2）"""
    import difflib
    from collections import Counter
    data = request.get_json(force=True, silent=True) or {}
    pa = _resolve_log_path(data.get("a", ""))
    pb = _resolve_log_path(data.get("b", ""))
    if not pa or not pb:
        return jsonify({"ok": False, "err": f"日志路径解析失败: a={data.get('a')} b={data.get('b')}"}), 400
    mode = (data.get("mode") or "summary").strip()
    ctx = int(data.get("context", 2))
    ctx = max(0, min(ctx, 10))

    # 读两份日志的 text 行（忽略 ts，只取 tag+text 用于对比；纯外部日志 tag=text）
    def read_texts(path):
        idx = _get_log_index(path)
        if not idx._loaded:
            idx.build()
        out = []
        with open(path, "rb") as f:
            for i in range(idx.total):
                f.seek(idx.offsets[i])
                line = f.readline().decode("utf-8", errors="replace")
                p = idx._parse_line(line)
                # 对比键：tag+text（忽略 ts，因为两份日志时间戳必然不同）
                out.append((p.get("tag", "text"), p.get("text", "")))
        return out

    try:
        a_lines = read_texts(pa)
        b_lines = read_texts(pb)
    except Exception as e:
        return jsonify({"ok": False, "err": f"读取日志失败: {e}"}), 500

    a_name = os.path.basename(pa)
    b_name = os.path.basename(pb)

    if mode == "line":
        # 行级 diff：用 difflib 对 text 序列做差异比对
        a_texts = [t for _, t in a_lines]
        b_texts = [t for _, t in b_lines]
        sm = difflib.SequenceMatcher(a=a_texts, b=b_texts, autojunk=False)
        blocks = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            # 上下文
            cs = max(0, i1 - ctx)
            ce = min(len(a_texts), i2 + ctx)
            block = {
                "op": op,  # replace / delete / insert
                "a_range": [i1, i2], "b_range": [j1, j2],
                "a_ctx": [{"row": cs + k, "text": a_texts[cs + k]} for k in range(ce - cs) if cs + k < len(a_texts)],
                "b_ctx": [{"row": j1 + k, "text": b_texts[j1 + k]} for k in range(j2 - j1 + ctx) if j1 + k < len(b_texts)],
            }
            # 只保留差异行，上下文单独标
            block["a_lines"] = [{"row": i1 + k, "text": a_texts[i1 + k]} for k in range(i2 - i1)]
            block["b_lines"] = [{"row": j1 + k, "text": b_texts[j1 + k]} for k in range(j2 - j1)]
            blocks.append(block)
        return jsonify({"ok": True, "mode": "line", "a": a_name, "b": b_name,
                        "a_total": len(a_lines), "b_total": len(b_lines),
                        "diff_blocks": blocks, "diff_count": len(blocks)})

    # mode=summary：去重摘要，对比唯一行 + 出现次数
    def count_lines(lines):
        c = Counter()
        for tag, text in lines:
            # 去掉行内可变部分（时间戳已在 text 里就保留，对比时两份日志时间不同但内容同）
            key = text.strip()
            if not key:
                continue
            c[key] += 1
        return c
    a_cnt = count_lines(a_lines)
    b_cnt = count_lines(b_lines)
    all_keys = set(a_cnt) | set(b_cnt)
    only_a = []  # 只在 A 出现
    only_b = []  # 只在 B 出现
    diff_cnt = []  # 两边都有但次数差大
    for k in all_keys:
        ca = a_cnt.get(k, 0)
        cb = b_cnt.get(k, 0)
        if ca and not cb:
            only_a.append({"text": k, "a_count": ca})
        elif cb and not ca:
            only_b.append({"text": k, "b_count": cb})
        elif abs(ca - cb) > 0:
            diff_cnt.append({"text": k, "a_count": ca, "b_count": cb, "delta": cb - ca})
    # 按次数/差异排序
    only_a.sort(key=lambda x: -x["a_count"])
    only_b.sort(key=lambda x: -x["b_count"])
    diff_cnt.sort(key=lambda x: -abs(x["delta"]))
    return jsonify({"ok": True, "mode": "summary", "a": a_name, "b": b_name,
                    "a_total": len(a_lines), "b_total": len(b_lines),
                    "a_unique": len(a_cnt), "b_unique": len(b_cnt),
                    "only_a": only_a[:100], "only_b": only_b[:100],
                    "count_diffs": diff_cnt[:100],
                    "only_a_total": len(only_a), "only_b_total": len(only_b),
                    "count_diffs_total": len(diff_cnt)})

@app.route("/api/new_log", methods=["POST"])
def api_new_log():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 500
    return jsonify({"log_path": p.new_log()})

@app.route("/api/clear_buffer", methods=["POST"])
def api_clear_buffer():
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if p:
        p.clear_buffer()
    return jsonify({"ok": True})

@app.route("/api/stream")
def stream():
    port_id = request.args.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"}), 404
    q = p.add_client()
    def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": ping\n\n"
        finally:
            # 客户端断开时回收队列，避免泄漏（gen 退出 = 连接关闭）
            p.remove_client(q)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================
# AI 专用 API
# ============================================================
@app.route("/api/ai/status")
def ai_status():
    """AI 获取所有串口状态概览。"""
    return api_status()

@app.route("/api/ai/buffer")
def ai_buffer():
    """AI 获取指定串口的缓冲（可指定行数）。"""
    port_id = request.args.get("port_id")
    n = int(request.args.get("n", 200))
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    items = p.get_buffer(n)
    # 给 AI 返回纯文本（去 ANSI/HTML），更省 token
    return jsonify({"ok": True, "port_id": port_id, "lines": [
        {"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items
    ]})

@app.route("/api/ai/recent")
def ai_recent():
    """AI 获取所有已连接串口最近的输出（各取最后 N 行）。"""
    n = int(request.args.get("n", 50))
    result = {}
    with _ports_lock:
        all_ports = list(_ports.items())
    for pid, p in all_ports:
        items = p.get_buffer(n)
        result[pid] = [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items]
    return jsonify({"ok": True, "ports": result})

@app.route("/api/ai/send", methods=["POST"])
def ai_send():
    """AI 向指定串口发送命令。"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    cmd = data.get("cmd", "")
    wait = float(data.get("wait", 1.5))  # 等待回显秒数
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    try:
        # 用 seq 游标取命令后的新输出，避免 len 差在并发下取错（别人命令/设备自报混入）
        with p.buf_lock:
            before_seq = p.buf[-1]["seq"] if p.buf else -1
        p.send_cmd(cmd, newline=True)
        # 等待设备回显
        time.sleep(wait)
        new_items = p.get_buffer_after(before_seq)
        return jsonify({"ok": True, "port_id": port_id, "sent": cmd,
                        "response": [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in new_items]})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)})

@app.route("/api/ai/send_raw", methods=["POST"])
def ai_send_raw():
    """AI 发送原始字节。"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    byte_list = data.get("bytes", [])
    payload = bytes(int(b) & 0xFF for b in byte_list if isinstance(b, (int, float)))
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    try:
        if payload:
            p.send_raw(payload)
        return jsonify({"ok": True, "sent": len(payload)})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)})

@app.route("/api/ai/stream")
def ai_stream():
    """AI 订阅所有串口的实时流（跨串口全局 SSE）。"""
    q = Queue(maxsize=10000)
    with _ai_clients_lock:
        _ai_clients.append(q)
    def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Exception:
                    yield ": ping\n\n"
        finally:
            # 客户端断开时从 _ai_clients 移除队列，避免泄漏（与 stream() 同模式）
            with _ai_clients_lock:
                try:
                    _ai_clients.remove(q)
                except ValueError:
                    pass
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/ai/ports")
def ai_ports():
    """AI 获取可用串口列表。"""
    return jsonify({"ok": True, "ports": list_ports(), "connected": list(_ports.keys())})

@app.route("/api/ai/observe")
def ai_observe():
    """Claude Code 直连用：一次返回状态 + 各串口最近 N 行，减少往返。
    可选 ?n=50 控制每个串口取多少行。"""
    n = int(request.args.get("n", 50))
    with _ports_lock:
        all_ports = list(_ports.items())
    status = {}
    recent = {}
    for pid, p in all_ports:
        status[pid] = {
            "port": p.port, "baud": p.baud, "recording": p.recording,
            "buf_lines": len(p.buf), "cmd_history_count": len(p.cmd_history),
        }
        items = p.get_buffer(n)
        recent[pid] = [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items]
    with _open_logs_lock:
        open_logs = list(_open_logs)
    return jsonify({"ok": True, "connected": list(_ports.keys()),
                    "status": status, "recent": recent, "open_logs": open_logs})


# ---- 前端上报已打开的日志（打开/关闭日志 tab 时同步） ----
@app.route("/api/ai/open_logs", methods=["GET", "POST", "DELETE"])
def ai_open_logs():
    """GET 查询当前已打开日志列表；POST 全量覆盖列表；DELETE 清空。
    前端打开/关闭日志 tab 时 POST 全量同步，让 MCP/AI 能感知用户当前在看哪个日志。"""
    global _open_logs
    if request.method == "GET":
        with _open_logs_lock:
            return jsonify({"ok": True, "logs": list(_open_logs)})
    if request.method == "DELETE":
        with _open_logs_lock:
            _open_logs.clear()  # 原地清空，避免重绑使 app_state 的绑定脱节
        return jsonify({"ok": True})
    # POST: 全量覆盖
    data = request.get_json(force=True, silent=True) or {}
    logs = data.get("logs")
    if not isinstance(logs, list):
        return jsonify({"ok": False, "err": "need logs list"}), 400
    # 规范化：只保留需要的字段
    clean = []
    for l in logs:
        if not isinstance(l, dict):
            continue
        name = str(l.get("name", "")).strip()
        path = str(l.get("path", "")).strip()
        if not name or not path:
            continue
        clean.append({
            "name": name,
            "path": path,
            "port_id": str(l.get("port_id", "")),
            "total": int(l.get("total", 0) or 0),
        })
    with _open_logs_lock:
        _open_logs[:] = clean  # 原地替换，避免重绑使 app_state 的绑定脱节
    return jsonify({"ok": True, "count": len(clean)})


# ---- MCP 状态信息（前端面板展示 + MCP server 上报调用记录） ----
@app.route("/api/ai/mcp_info")
def ai_mcp_info():
    """返回 MCP 相关信息：后端地址、已注册工具列表、最近调用记录。
    工具列表从 mcp_server.py 静态定义读取（硬编码在此保持一致），调用记录由 mcp_server 上报。"""
    tools = [
        {"name": "observe", "desc": "概览所有连接 + 最近输出 + 已打开日志"},
        {"name": "list_ports", "desc": "列出可用串口 + 已连接"},
        {"name": "connect_serial", "desc": "建立串口连接"},
        {"name": "connect_ssh", "desc": "建立 SSH 连接"},
        {"name": "send_command", "desc": "发命令 + 等回显"},
        {"name": "send_raw", "desc": "发原始字节（Ctrl-C 等）"},
        {"name": "get_buffer", "desc": "取连接最近 N 行缓冲"},
        {"name": "list_open_logs", "desc": "列出前端已打开的日志文件"},
        {"name": "read_log", "desc": "读日志文件（分页）"},
        {"name": "search_log", "desc": "日志关键字搜索"},
        {"name": "diff_logs", "desc": "对比两份日志差异（summary/line）"},
        {"name": "disconnect", "desc": "断开连接"},
        {"name": "tftp_status", "desc": "TFTP 服务状态：运行中/目录/文件列表/传输记录"},
        {"name": "tftp_start", "desc": "启动 TFTP 服务（UDP 69），设备可上传/下载文件"},
        {"name": "tftp_stop", "desc": "停止 TFTP 服务"},
        {"name": "tftp_set_dir", "desc": "设置/切换 TFTP 根目录"},
    ]
    with _mcp_calls_lock:
        calls = list(_mcp_calls)
    # 读 endpoint 信息
    ep_info = {}
    try:
        ep_path = os.path.join(STATE_DIR, "endpoint.json")
        if os.path.isfile(ep_path):
            with open(ep_path, "r", encoding="utf-8") as f:
                ep_info = json.load(f)
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "backend_url": ep_info.get("url", ""),
        "endpoint": ep_info,
        "tools": tools,
        "recent_calls": calls,
    })


@app.route("/api/ai/mcp_report", methods=["POST"])
def ai_mcp_report():
    """MCP server 每次工具调用后上报记录，前端状态面板展示最近活动。"""
    data = request.get_json(force=True, silent=True) or {}
    entry = {
        "ts": time.time(),
        "tool": str(data.get("tool", "")),
        "args": str(data.get("args", ""))[:200],
        "ok": bool(data.get("ok", True)),
    }
    global _mcp_calls
    with _mcp_calls_lock:
        _mcp_calls.append(entry)
        if len(_mcp_calls) > _MCP_CALLS_MAX:
            _mcp_calls[:] = _mcp_calls[-_MCP_CALLS_MAX:]  # 原地截断，避免重绑使 app_state 的绑定脱节
    return jsonify({"ok": True})


# 前端性能计时上报（诊断启动慢）
_perf_last = {}
@app.route("/api/ai/perf", methods=["POST", "GET"])
def ai_perf():
    """前端上报页面加载各阶段耗时（ms）。GET 返回最近一次。"""
    global _perf_last
    if request.method == "GET":
        return jsonify({"ok": True, "perf": _perf_last})
    data = request.get_json(force=True, silent=True) or {}
    _perf_last = {**data, "ts": time.time()}
    return jsonify({"ok": True})

# ---- 命令库持久化（跨端口/重启保留） ----
@app.route("/api/cmd_lib")
def cmd_lib_get():
    """读取命令库 [{name, cmd}]。"""
    return jsonify({"ok": True, "lib": _load_cmd_lib()})

@app.route("/api/cmd_lib", methods=["POST"])
def cmd_lib_save():
    """保存整个命令库（前端全量覆盖）。body: {lib: [{name, cmd}]}"""
    data = request.get_json(force=True, silent=True) or {}
    lib = data.get("lib")
    if not isinstance(lib, list):
        return jsonify({"ok": False, "err": "need lib list"}), 400
    # 规范化：只保留 name/cmd 字段，cmd 必填
    clean = [{"name": str(c.get("name", "")).strip(), "cmd": str(c.get("cmd", "")).strip()}
             for c in lib if isinstance(c, dict) and str(c.get("cmd", "")).strip()]
    _save_cmd_lib(clean)
    return jsonify({"ok": True, "lib": clean})


if __name__ == "__main__":
    start_background()
    app.run(host="127.0.0.1", port=8765, threaded=True, debug=False, use_reloader=False)
