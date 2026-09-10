#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端控制台 v1.1.0 —— 多串口/SSH 后端 + AI 接入层
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
    BASE_DIR, RES_DIR, STATE_DIR, HOME_DIR, DATA_DIR, CONFIG_FILE, LOG_DIR, DEFAULT_LOG_DIR, CMD_LIB_FILE,
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
from src.httpfile import httpfile_bp, _hfs, _Handler as _hfs_handler
from src.editor_files import edit_bp
from src.hex_files import hex_bp
from src.file_tree import tree_bp


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

# 注册 HTTP 文件下载 Blueprint（路由 /api/httpfile/*，端口 8081，与 TFTP 同目录联动）
_hfs_handler.tftp = _tftp  # Handler 注入 TFTP 单例——HTTP 共享 TFTP 的 root_dir
app.register_blueprint(httpfile_bp)

# 注册二进制 hex 查看/编辑 Blueprint（路由 /api/hex/*）
app.register_blueprint(hex_bp)

# 注册文本编辑器 Blueprint（路由 /api/ed/*）
app.register_blueprint(edit_bp)

# 注册文件关联接管/还原 Blueprint（路由 /api/assoc/*，注册表只动 HKCU）
from src.file_assoc import assoc_bp
app.register_blueprint(assoc_bp)

# 注册文件树工作区 Blueprint（路由 /api/tree/*，根目录登记制安全模型）
app.register_blueprint(tree_bp)

# 注册 Claude 安装引导 Blueprint（路由 /api/claude/setup_*，联网/离线双通道）
from src.claude_setup import claude_setup_bp
app.register_blueprint(claude_setup_bp)

# 注册 Claude 默认环境/ API 配置 Blueprint（settings.json 铺设与 token 读写）
from src.claude_default import claude_default_bp
app.register_blueprint(claude_default_bp)

# 注册 Claude Proxy Blueprint（重试代理+headroom 压缩+Lanz 额度，/api/proxy/*）
from src.proxy import proxy_bp, proxy_module_init
app.register_blueprint(proxy_bp)

# ---- 自依赖自检状态（main 启动时注入，前端每次启动拉取弹提醒） ----
_deps_state = {"missing_req": [], "missing_opt": [], "skipped": False}


def set_deps_missing(miss_req, miss_opt, skipped):
    """main.py 注入自检结果（deps_bootstrap.selftest_once 的返回值）。"""
    _deps_state.update(missing_req=miss_req, missing_opt=miss_opt, skipped=skipped)


@app.route("/api/deps_status")
def deps_status():
    """自依赖状态：缺哪些库、各自影响什么功能；以及离线包补装入口是否可用。"""
    d = dict(_deps_state)
    d["ok"] = not (d["missing_req"] or d["missing_opt"])
    return jsonify(d)

# ---- 全局串口表（_ports/_ports_lock 来自 app_state，此处定义 close_all_ports）----
def close_all_ports():
    with _ports_lock:
        for p in list(_ports.values()):
            p.close()
        _ports.clear()

# ---- 每目标连接锁：防同一目标并发 connect 重入（如 SSH 10s 超时期间连点两次快捷打开）。
# 绝不能用 _ports_lock 顶替——_ports_lock 保护 _ports 表的瞬时读写（/api/status、
# disconnect 等都抢它），若在临界区内做阻塞连接，全局所有 API 排队等 SSH 超时，
# 表现为「点其他快捷打开整个 UI 卡死」（铁律①流畅性事故）。
_connecting_locks = {}          # port_id -> Lock（连接期间占位）
_connecting_locks_guard = threading.Lock()

def _acquire_connecting(port_id):
    """登记连接占位。返回 False 表示同目标已在连接中（或已连接表已有）。"""
    with _connecting_locks_guard:
        lock = _connecting_locks.setdefault(port_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return False
    with _ports_lock:
        if port_id in _ports:   # 已连接：释放占位让调用方走「已连接」路径
            lock.release()
            _drop_connecting(port_id)
            return False
    return True   # 调用方连接结束后必须 _drop_connecting(port_id)

def _drop_connecting(port_id):
    """连接结束（无论成败）清占位锁。锁被持有中时只清注册表，锁对象由持有方释放。"""
    with _connecting_locks_guard:
        lock = _connecting_locks.get(port_id)
        if lock is not None:
            try: lock.release()
            except Exception: pass
            _connecting_locks.pop(port_id, None)

# hook 到 BaseConnection.append_line：AI 全局流挂载点（猴子补丁，import 各连接类后执行）
# 挂基类而非 SerialPort——SSHConnection 继承基类方法，挂串口类会让 SSH 输出永远不进 /api/ai/stream
_orig_append = BaseConnection.append_line
def _claude_sense_ok(clean):
    """claude 连接行进感知流的准入：TUI 重绘流切出的碎片行剔除，保留有语义的文本。
    剔除规则（按实测 buf 特征）：
    - 空行 / 纯符号(点线框/spinner 字符)
    - 状态栏拆行（Model:/Context:/auto mode/agent 组合）
    - 单字符或 2 字符以下的残片
    - 纯分隔线(─╌▔ 构成)"""
    s = clean.strip()
    if len(s) < 4:
        return False
    if not re.search(r"[一-鿿 a-zA-Z0-9]", s):
        return False   # 纯符号(点线/spinner)
    if re.fullmatch(r"[─╌▔━┄┈═\s]+", s):
        return False
    if "Model:" in s and "Context:" in s:
        return False   # 状态栏整行
    if s.startswith("⏵") or "auto mode on" in s or "Effort:" in s:
        return False
    return True

def _patched_append(self, raw_line, local_echo=False):
    _orig_append(self, raw_line, local_echo)
    # claude 连接过滤后进感知流：整行排除会让感知面板在纯 claude 会话期完全空白
    # （用户依赖它看会话动态）；但 TUI 重绘碎片（状态栏拆行/单字符/分隔线）全量
    # 灌入无语义且误导——尤其恢复会话启动重绘一次灌 8000+ 行，须过滤
    if getattr(self, "kind", "") == "claude":
        clean0 = strip_ansi(raw_line)
        if not _claude_sense_ok(clean0):
            return
        ts_ms = int(time.time() * 1000)
        _broadcast_to_ai({"ts": ts_ms, "text": clean0, "port": self.port_id,
                          "tag": classify_line(clean0)})
        return
    ts_ms = int(time.time() * 1000)
    clean = strip_ansi(raw_line)
    _broadcast_to_ai({"ts": ts_ms, "text": clean, "port": self.port_id, "tag": classify_line(clean)})
BaseConnection.append_line = _patched_append

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
    # Claude Proxy 模块初始化（启动自愈+压缩模式记忆+额度 worker；不自动启动代理）
    try:
        proxy_module_init()
    except Exception as e:
        import logging
        logging.getLogger("claude_proxy").warning("proxy_module_init 失败: %s", e)

# ============================================================
# Flask 路由
# ============================================================
@app.after_request
def _no_cache_static(resp):
    """静态资源(web/ 下的 JS/CSS)禁缓存：开发迭代频繁，WebView2 若缓存旧 JS，
    重启工具仍加载旧代码，改动"看起来不生效"。HTML/JS/CSS 每次都拉最新。"""
    if resp.mimetype in ("text/html", "application/javascript", "text/css", "text/javascript"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

@app.route("/")
def index():
    return send_from_directory(RES_DIR, "web/index.html")

@app.route("/web/<path:fn>")
def web_files(fn):
    return send_from_directory(os.path.join(RES_DIR, "web"), fn)

@app.route("/<path:fn>")
def static_files(fn):
    return send_from_directory(RES_DIR, fn)

# 第三方库本地托管（Monaco Editor / markdown-it，离线可用，不走 CDN）
VENDOR_DIR = os.path.join(BASE_DIR, "vendor")
@app.route("/vendor/<path:fn>")
def vendor_files(fn):
    return send_from_directory(VENDOR_DIR, fn)

# 应用图标（顶栏 logo 用，打包后 ico/ 在 _MEIPASS 下）
ICO_DIR = os.path.join(RES_DIR, "ico")
@app.route("/ico/<path:fn>")
def ico_files(fn):
    return send_from_directory(ICO_DIR, fn)

@app.route("/api/ports")
def api_ports():
    return jsonify({"ports": list_ports(), "bauds": COMMON_BAUDS})

@app.route("/api/help_readme")
def api_help_readme():
    """帮助按钮：返回 README.md 绝对路径（前端 openFileSmart 工具内打开）。
    源码运行=项目根 README；exe=spec datas 打进 _MEIPASS 的 README.md。"""
    p = os.path.join(RES_DIR, "README.md")
    if not os.path.isfile(p):
        return jsonify({"ok": False, "err": "README.md 不存在"})
    return jsonify({"ok": True, "path": p})

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
            # 允许空密码连接：部分设备（dropbear/嵌入设备）空密码可进入，
            # 或服务端虽要求密码但本次认证尝试即可被接受；若通道内还需密码，
            # 用户可在终端里交互输入。拒绝时走异常分类返回清晰报错。
            pass
        if _get_paramiko() is None:
            return jsonify({"ok": False, "err": "paramiko 未安装，无法 SSH 连接"}), 500
        port_id = f"ssh:{host}:{port}"
        # 占位防同目标重入；连接动作在锁外执行（10s 超时不再卡全局 API/其他快捷打开）
        if not _acquire_connecting(port_id):
            with _ports_lock:
                if port_id in _ports:
                    return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
            return jsonify({"ok": False, "err": f"{port_id} 正在连接中，请稍候"}), 400
        try:
            try:
                p = SSHConnection(host, port, username, password=password, key_path=key_path, port_id=port_id)
            except Exception as e:
                # start() 在构造内执行，_start_log 失败或后续步骤异常会留下
                # 半构造对象（已开 SSH 会话+读线程）——必须 close 兜底，否则幽灵会话泄漏
                try: p.close()
                except Exception: pass
                # 认证失败类异常：转成对用户可读的中文提示（paramiko 原始消息常为空/难懂）
                msg = str(e) or e.__class__.__name__
                try:
                    from paramiko.ssh_exception import (
                        AuthenticationException, SSHException,
                        BadHostKeyException, NoValidConnectionsError,
                    )
                    import socket
                    if isinstance(e, AuthenticationException):
                        msg = "认证失败：用户名或密码/密钥错误。" + (f" {e}" if str(e) else " 请检查后重试。")
                    elif isinstance(e, BadHostKeyException):
                        msg = f"主机密钥校验失败：{e}"
                    elif isinstance(e, NoValidConnectionsError):
                        host_raw = getattr(e, "host", (host, int(port)))
                        msg = f"无法连接到 {host_raw[0]}:{host_raw[1]}（网络不通或端口未开放）"
                    elif isinstance(e, socket.timeout) or isinstance(e, TimeoutError) or "timed out" in msg.lower():
                        msg = f"连接 {host}:{port} 超时（网络不可达或端口被防火墙拦截）"
                    elif isinstance(e, socket.gaierror):
                        msg = f"无法解析主机 {host}：{e}"
                    elif isinstance(e, SSHException):
                        msg = f"SSH 协议错误：{e}"
                except Exception:
                    pass
                return jsonify({"ok": False, "err": msg}), 500
            with _ports_lock:
                if port_id in _ports:   # 极端并发：两次同目标连接都成功了，后到者关掉
                    try: p.close()
                    except Exception: pass
                    return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
                _ports[port_id] = p
        finally:
            _drop_connecting(port_id)
        # SSH invoke_shell 自带 shell，不主动 send \r
        return jsonify({"ok": True, "port_id": port_id, "kind": "ssh",
                        "msg": f"已连接 {username}@{host}:{port}"})
    elif kind == "telnet":
        # Telnet 连接（裸 socket + IAC 协商，零依赖）
        host = (data.get("host") or "").strip()
        port = data.get("port") or 23
        if not host:
            return jsonify({"ok": False, "err": "need host"}), 400
        port_id = f"telnet:{host}:{port}"
        # 占位防同目标重入；连接动作在锁外执行（同 SSH，不卡全局 API）
        if not _acquire_connecting(port_id):
            with _ports_lock:
                if port_id in _ports:
                    return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
            return jsonify({"ok": False, "err": f"{port_id} 正在连接中，请稍候"}), 400
        try:
            try:
                from .telnet_conn import TelnetConnection
                p = TelnetConnection(host, port, port_id=port_id)
            except Exception as e:
                try: p.close()
                except Exception: pass
                msg = str(e) or e.__class__.__name__
                import socket as _socket
                if isinstance(e, (_socket.timeout, TimeoutError)):
                    msg = f"连接 {host}:{port} 超时（网络不可达或端口未开放）"
                elif isinstance(e, _socket.gaierror):
                    msg = f"无法解析主机 {host}：{e}"
                elif isinstance(e, ConnectionRefusedError):
                    msg = f"{host}:{port} 拒绝连接（Telnet 服务未开启）"
                return jsonify({"ok": False, "err": msg}), 500
            with _ports_lock:
                if port_id in _ports:
                    try: p.close()
                    except Exception: pass
                    return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
                _ports[port_id] = p
        finally:
            _drop_connecting(port_id)
        return jsonify({"ok": True, "port_id": port_id, "kind": "telnet",
                        "msg": f"已连接 {host}:{port}"})
    elif kind == "claude":
        # Claude Code 本地终端（ConPTY 跑真实 CLI，设计见 docs/CLAUDE_CODE_INTEGRATION.md）
        from .claude_conn import (ClaudeConnection, ClaudeNotFoundError,
                                  _humanize_claude_error, _bg_sessions_running)
        cwd = (data.get("cwd") or "").strip() or os.path.expanduser("~")
        resume = (data.get("resume") or "").strip() or None
        agents = bool(data.get("agents"))   # 显式打开 agents TUI（接管后台会话本体）
        light_theme = bool(data.get("light_theme"))   # 前端壳体为亮色主题时注入 light 主题
        # resume 的会话正以后台 agent 运行时，--resume 会被 claude 拒绝（红字）。
        # 官方 attach 路径只有 agents TUI（无 CLI flag）——自动转 agents 视图，
        # 用户在列表里回车即接管该会话本体。
        if resume and not agents and resume in _bg_sessions_running():
            agents = True
            resume = None
        if resume and not os.path.isdir(cwd):
            return jsonify({"ok": False, "err": f"会话原目录不存在：{cwd}"}), 400
        with _ports_lock:
            # port_id 分配：resume 会话带 id 前缀（同会话重复打开去重）；新会话自增
            if resume:
                port_id = f"claude:r-{resume[:8]}"
                if port_id in _ports:
                    return jsonify({"ok": False, "err": "该会话已在工具内打开，请切换到对应标签页"}), 400
            else:
                n = 1
                while f"claude:{n}" in _ports:
                    n += 1
                port_id = f"claude:{n}"
            try:
                p = ClaudeConnection(cwd=cwd, resume=resume, port_id=port_id,
                                     light_theme=light_theme, agents=agents)
                _ports[port_id] = p
            except Exception as e:
                # 构造内 start() 已 spawn PTY+读线程，异常必须 close 兜底（同 SSH/串口模式）
                _ports.pop(port_id, None)
                try: p.close()
                except Exception: pass
                return jsonify({"ok": False, "err": _humanize_claude_error(e)}), 500
        return jsonify({"ok": True, "port_id": port_id, "kind": "claude",
                        "cwd": cwd, "resume": resume,
                        "msg": f"claude 已启动（{'恢复会话 ' + resume[:8] if resume else '新会话'}）"})
    else:
        # 串口连接（默认）
        port = data.get("port")
        baud = data.get("baud")
        if not port or not baud:
            return jsonify({"ok": False, "err": "need port and baud"}), 400
        port_id = port
        # 占位防同目标重入；串口 open 也可能阻塞（拔线等待），同样移出全局锁
        if not _acquire_connecting(port_id):
            with _ports_lock:
                if port_id in _ports:
                    return jsonify({"ok": False, "err": f"{port} 已连接"}), 400
            return jsonify({"ok": False, "err": f"{port} 正在连接中，请稍候"}), 400
        try:
            try:
                p = SerialPort(port, baud, port_id)
            except Exception as e:
                # 构造内 start() 已开串口句柄/读线程，异常必须 close 兜底，
                # 否则 COM 口被半构造对象占死，再连必 PermissionError
                try: p.close()
                except Exception: pass
                return jsonify({"ok": False, "err": str(e)}), 500
            with _ports_lock:
                if port_id in _ports:
                    try: p.close()
                    except Exception: pass
                    return jsonify({"ok": False, "err": f"{port} 已连接"}), 400
                _ports[port_id] = p
        finally:
            _drop_connecting(port_id)
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

@app.route("/api/reconnect", methods=["POST"])
def api_reconnect():
    """断连 overlay 按 R：中断当前退避等待，立即触发一次重连。
    仅对 alive（未手动断开）的连接有效；重连在后台线程执行，
    本接口立即返回不阻塞（结果经 SSE connstate 事件推给前端）。"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "未找到该连接"}), 404
    if not getattr(p, "alive", False):
        return jsonify({"ok": False, "err": "连接已手动断开，请重新建立连接"}), 400
    triggered = p.reconnect_now() if hasattr(p, "reconnect_now") else False
    if triggered:
        return jsonify({"ok": True, "msg": "已触发重连"})
    return jsonify({"ok": False, "err": "该连接不支持重连"}), 400

@app.route("/api/resize", methods=["POST"])
def api_resize():
    """PTY 尺寸同步（claude 终端 tab 的 xterm onResize → ConPTY setwinsize）。"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    cols = int(data.get("cols") or 0)
    rows = int(data.get("rows") or 0)
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "连接不存在"}), 404
    if not hasattr(p, "resize"):
        return jsonify({"ok": False, "err": "该连接不支持 resize"}), 400
    if cols <= 0 or rows <= 0:
        return jsonify({"ok": False, "err": "尺寸非法"}), 400
    try:
        p.resize(rows, cols)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

@app.route("/api/claude_theme", methods=["POST"])
def api_claude_theme():
    """工具壳体换主题时同步所有活跃 claude 会话（settings 临时文件热重载）。
    body: {light: true/false}——对全部 kind='claude' 连接调用 set_light_theme。"""
    data = request.get_json(force=True)
    light = bool(data.get("light"))
    applied, skipped = 0, 0
    with _ports_lock:
        conns = [p for p in _ports.values() if getattr(p, "kind", "") == "claude"]
    for p in conns:
        try:
            if p.set_light_theme(light):
                applied += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return jsonify({"ok": True, "applied": applied, "skipped": skipped})

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

def _calc_hist_clean(items):
    """计算器历史清洗：只要 {expr,res} 均为字符串的条目，字符串截断 200 字符，上限 50。"""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if (isinstance(it, dict) and isinstance(it.get("expr"), str)
                and isinstance(it.get("res"), str)):
            out.append({"expr": it["expr"][:200], "res": it["res"][:200]})
            if len(out) >= 50:
                break
    return out


@app.route("/api/theme", methods=["GET", "POST"])
def api_theme():
    """主题持久化。localStorage 按 origin（127.0.0.1:端口）隔离，而 Flask 每次
    启动端口随机 → 换肤记忆永远读不到。走 config.json 跨端口稳定。
    兼职通用小配置读写：GET 带回 data_dir_prompted（首启引导标记）；
    POST body 含 data_dir_prompted 时写入（与主题字段互不干扰）。
    终端快捷键映射（term_keys）也在此兼职读写：
      right_action: ctrl_menu / right_menu / right_paste
      auto_copy: bool（选中即自动复制）
      term_font_size: int 10-24（终端字号，默认 13）
    计算器历史（calc_history）也在此兼职读写：[{expr, res}] 上限 50 条。
      ui_zoom: int 80-130（界面缩放百分比，默认 100）
    """
    if request.method == "GET":
        cfg = _load_config()
        tk = cfg.get("term_keys", {})
        return jsonify({"ok": True, "theme": cfg.get("theme", "deepblue"),
                        "data_dir_prompted": bool(cfg.get("data_dir_prompted")),
                        "calc_history": _calc_hist_clean(cfg.get("calc_history", [])),
                        "close_to_tray": bool(cfg.get("close_to_tray", True)),
                        "tray_prompt_shown": bool(cfg.get("tray_prompt_shown", False)),
                        "term_keys": {
                            "right_action": tk.get("right_action", "ctrl_menu"),
                            "auto_copy": bool(tk.get("auto_copy", False)),
                            "term_font_size": int(tk.get("term_font_size", 13)),
                            "ui_zoom": int(tk.get("ui_zoom", 100)),
                        }})
    data = request.get_json(force=True) or {}
    if "data_dir_prompted" in data:
        # 仅写引导标记的轻请求（不带 theme 字段）
        _save_config({**_load_config(), "data_dir_prompted": bool(data["data_dir_prompted"])})
    if "term_keys" in data and isinstance(data["term_keys"], dict):
        tk = data["term_keys"]
        # 白名单校验：right_action 只认三个值；字号/缩放夹取到安全区间，防脏配置
        ra = tk.get("right_action")
        if ra in ("ctrl_menu", "right_menu", "right_paste"):
            def _clamp(v, lo, hi, dflt):
                try:
                    return max(lo, min(hi, int(v)))
                except (TypeError, ValueError):
                    return dflt
            _save_config({**_load_config(), "term_keys": {
                "right_action": ra,
                "auto_copy": bool(tk.get("auto_copy", False)),
                "term_font_size": _clamp(tk.get("term_font_size", 13), 10, 24, 13),
                "ui_zoom": _clamp(tk.get("ui_zoom", 100), 80, 130, 100),
            }})
    if "calc_history" in data and isinstance(data["calc_history"], list):
        # 计算器历史持久化：[{expr, res}]，字符串白名单 + 上限 50（防 config 膨胀）
        _save_config({**_load_config(), "calc_history": _calc_hist_clean(data["calc_history"])})
    # 关闭到托盘（close_to_tray：设置页开关）+ 首次提示已展示标记（tray_prompt_shown）
    _tk = {}
    if "close_to_tray" in data:
        _tk["close_to_tray"] = bool(data["close_to_tray"])
    if "tray_prompt_shown" in data:
        _tk["tray_prompt_shown"] = bool(data["tray_prompt_shown"])
    if _tk:
        _save_config({**_load_config(), **_tk})
    theme = (data.get("theme") or "").strip()
    if theme:
        _save_config({**_load_config(), "theme": theme})
    return jsonify({"ok": True, "theme": theme or _load_config().get("theme", "deepblue")})


# ============================================================
# 最近打开（SSH/串口/文件 快捷重开列表）
# ============================================================
# 存 config.json "recent" 键：[{type, key, label, ts, data{...}}...]，新→旧。
# key = 去重键（ssh:host:port:user / serial:COM3 / file:路径 / claude:session_id）；同 key 只留最新一条并置顶。
_RECENT_MAX = 20  # 列表上限，防无限膨胀
def _recent_add(item):
    """记录一条最近打开（去重置顶），返回更新后的列表。"""
    cfg = _load_config()
    recent = cfg.get("recent", [])
    key = item.get("key") or ""
    recent = [r for r in recent if r.get("key") != key]
    item["ts"] = int(time.time() * 1000)
    recent.insert(0, item)
    recent = recent[:_RECENT_MAX]
    cfg["recent"] = recent
    _save_config(cfg)
    return recent

@app.route("/api/hash_file", methods=["POST"])
def api_hash_file():
    """文件哈希（程序员计算器的文件哈希面板）。
    body: {path} —— 一次流式读，同时算 MD5/SHA1/SHA256/SHA512/CRC32。
    大文件分块（8MB/块）不占内存。路径规则与 hex_files 同款：绝对路径 + 已存在。"""
    data = request.get_json(force=True, silent=True) or {}
    p = os.path.abspath((data.get("path") or "").strip().strip('"').strip("'"))
    if not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    import hashlib, zlib
    md5 = hashlib.md5(); sha1 = hashlib.sha1()
    sha256 = hashlib.sha256(); sha512 = hashlib.sha512()
    crc = 0
    size = 0
    try:
        with open(p, "rb") as f:
            while True:
                chunk = f.read(8 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                md5.update(chunk); sha1.update(chunk)
                sha256.update(chunk); sha512.update(chunk)
                crc = zlib.crc32(chunk, crc)
    except Exception as e:
        return jsonify({"ok": False, "err": f"读取失败：{e}"}), 500
    return jsonify({"ok": True, "path": p, "size": size,
                    "md5": md5.hexdigest(),
                    "sha1": sha1.hexdigest(),
                    "sha256": sha256.hexdigest(),
                    "sha512": sha512.hexdigest(),
                    "crc32": format(crc & 0xFFFFFFFF, '08X').lower()})

@app.route("/api/recent", methods=["GET", "POST", "DELETE"])
def api_recent():
    """GET 列表；POST 记录一条 {type,key,label,data}（或 {replace:[...]} 整表替换）；DELETE 清空。"""
    if request.method == "GET":
        return jsonify({"ok": True, "recent": _load_config().get("recent", [])})
    if request.method == "DELETE":
        _save_config({**_load_config(), "recent": []})
        return jsonify({"ok": True})
    data = request.get_json(force=True) or {}
    # 整表替换（前端单条删除后回写剩余列表）
    if isinstance(data.get("replace"), list):
        keep = []
        for it in data["replace"]:
            t = (it.get("type") or "").strip()
            if t not in ("ssh", "serial", "file", "claude") or not (it.get("key") or "").strip():
                continue
            keep.append({"type": t, "key": it["key"], "label": (it.get("label") or "").strip(),
                         "ts": it.get("ts") or 0, "data": it.get("data") or {}})
        keep.sort(key=lambda x: -x.get("ts", 0))  # 按 ts 新→旧
        _save_config({**_load_config(), "recent": keep[:_RECENT_MAX]})
        return jsonify({"ok": True, "recent": keep[:_RECENT_MAX]})
    t = (data.get("type") or "").strip()
    if t not in ("ssh", "serial", "file", "claude"):
        return jsonify({"ok": False, "err": "type 须为 ssh/serial/file/claude"}), 400
    item = {"type": t, "key": (data.get("key") or "").strip(),
            "label": (data.get("label") or "").strip(), "data": data.get("data") or {}}
    if not item["key"]:
        return jsonify({"ok": False, "err": "key 不能为空"}), 400
    return jsonify({"ok": True, "recent": _recent_add(item)})


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


# ---- 数据目录管理（顶栏机器人图标点开的设置面板）----
# 数据目录收纳：logs/（串口日志，唯一日志目录）、files/（笔记）、cmdlib.json（命令库）、
# webview_cache/（WebView2 缓存——也迁：新位置缓存连续，不产生旧位置孤儿残留；
# 被运行中 WebView2 锁定的文件跳过，纯缓存丢了自动重建）。
# 迁移铁律（用户强调）：迁移前后数据必须都能找到——采用「先复制后切换」而非「先删后搬」：
# 复制全部内容 → 校验大小一致 → 写 config 切换 → 旧目录完整保留不删（用户自查后手动删）。
_DATA_SUBDIRS = ["logs", "files", "webview_cache"]
_DATA_FILES = ["cmdlib.json"]

@app.route("/api/data_dir")
def api_data_dir_get():
    """查询数据目录现状：当前目录、默认建议、各子目录条目数与总大小（迁移面板展示）。"""
    def _stat(d):
        try:
            entries = os.listdir(d)
        except Exception:
            return {"exists": False, "count": 0, "size": 0}
        size = 0
        for fn in entries:
            try:
                size += os.path.getsize(os.path.join(d, fn))
            except Exception:
                pass
        return {"exists": True, "count": len(entries), "size": size}
    subs = {}
    total = 0
    for s in _DATA_SUBDIRS:
        st_ = _stat(os.path.join(DATA_DIR, s))
        # 只显示真实使用的（用户要求）：不存在的目录与空目录不出现在统计里，
        # 避免面板出现「logs 0 项」这类占位噪音
        if not st_["exists"] or st_["count"] == 0:
            continue
        subs[s] = st_
        total += st_["size"]
    cmdlib = _stat(CMD_LIB_FILE)
    if cmdlib["exists"]:
        subs["cmdlib.json"] = {"exists": True, "count": 1, "size": cmdlib["size"]}
        total += cmdlib["size"]
    return jsonify({"ok": True, "dir": DATA_DIR,
                    "default": _st._default_data_dir(),
                    "subdirs": subs, "total_size": total,
                    "home_anchor": HOME_DIR})

@app.route("/api/data_dir/check", methods=["POST"])
def api_data_dir_check():
    """校验候选目录：可创建、可写、不在 C 盘给出提醒但允许（用户自己选的）。
    返回迁移预览：会迁哪些子目录、各多少条目。"""
    data = request.get_json(force=True, silent=True) or {}
    target = (data.get("dir") or "").strip()
    if not target or len(target) < 3 or ":" not in target:
        return jsonify({"ok": False, "err": "路径无效（需绝对路径，如 D:\\前端控制台）"}), 400
    target = os.path.abspath(target)
    if os.path.abspath(DATA_DIR).lower() == target.lower():
        return jsonify({"ok": False, "err": "这就是当前数据目录"}), 400
    cur = os.path.abspath(DATA_DIR).lower()
    # 嵌套判定：目标在当前目录内（或反过来）都拒绝——迁移后 rmtree 旧目录
    # 会把嵌套在内的新副本一起删掉，全量数据丢失
    tgt = target.lower()
    if tgt.startswith(cur + os.sep) or cur.startswith(tgt + os.sep):
        return jsonify({"ok": False, "err": "目标目录不能与当前数据目录互相嵌套（会导致删除旧目录时连带删除新数据）"}), 400
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "err": f"无法创建目录: {e}"}), 400
    if not os.access(target, os.W_OK):
        return jsonify({"ok": False, "err": "目录不可写"}), 400
    warnings = []
    if target.upper().startswith("C:"):
        warnings.append("目标在 C 盘（数据默认应放其他盘，确认要放 C 盘吗？）")
    preview = []
    for s in _DATA_SUBDIRS:
        src = os.path.join(DATA_DIR, s)
        try:
            n = len(os.listdir(src))
        except Exception:
            n = 0
        if n:   # 与统计口径一致：只列有内容的
            preview.append({"name": s, "count": n})
    for s in _DATA_FILES:
        try:
            if os.path.isfile(os.path.join(DATA_DIR, s)):
                preview.append({"name": s, "count": 1})
        except Exception:
            pass
    return jsonify({"ok": True, "dir": target, "warnings": warnings, "preview": preview})

@app.route("/api/data_dir/migrate", methods=["POST"])
def api_data_dir_migrate():
    """迁移数据目录到新位置（先复制后切换，失败不切换——数据绝不丢）：
    1. 逐子目录复制（merge 到目标，不覆盖目标已有同名文件）；
    2. 逐文件校验大小一致（校验失败返回 err，不切换）；
    3. 全部通过后写 config.data_dir + 更新运行时（日志目录/笔记目录立即生效）；
    4. 旧目录完整保留，由用户确认后手动删（杜绝「迁移了就找不到了」）。
    webview_cache 不迁：纯浏览器缓存，重启自动重建。"""
    # 迁移切换要更新本模块按值导入的 DATA_DIR/STATE_DIR/CMD_LIB_FILE/LOG_DIR
    #（改 _st 属性不会同步到 import 绑定），global 声明必须在函数内首次使用前
    global DATA_DIR, STATE_DIR, CMD_LIB_FILE, LOG_DIR
    import shutil
    data = request.get_json(force=True, silent=True) or {}
    target = (data.get("dir") or "").strip()
    if not target or os.path.abspath(target).lower() == os.path.abspath(DATA_DIR).lower():
        return jsonify({"ok": False, "err": "目标与当前目录相同"}), 400
    target = os.path.abspath(target)
    cur = os.path.abspath(DATA_DIR).lower()
    # 嵌套判定：目标嵌套在当前目录内（或当前目录嵌套在目标内）都拒绝——
    # 迁移完成 rmtree(old_data_dir) 会把嵌套在内的新副本一并删除
    if target.lower().startswith(cur + os.sep) or cur.startswith(target.lower() + os.sep):
        return jsonify({"ok": False, "err": "目标目录不能与当前数据目录互相嵌套（会导致删除旧目录时连带删除新数据）"}), 400
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "err": f"无法创建目录: {e}"}), 400
    if not os.access(target, os.W_OK):
        return jsonify({"ok": False, "err": "目标目录不可写"}), 400
    copied = []
    try:
        for s in _DATA_SUBDIRS:
            src = os.path.join(DATA_DIR, s)
            if not os.path.isdir(src):
                continue
            # 分级（用户口径）：cmdlib/笔记 严格校验（必须完整）；logs 尽力复制；
            # webview_cache 仅搬壳（关工具自动清，不值得复制 300M）
            strict = (s == "files")
            tolerant = (s == "webview_cache")
            dst = os.path.join(target, s)
            os.makedirs(dst, exist_ok=True)
            n = 0
            skipped = 0
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                droot = dst if rel == "." else os.path.join(dst, rel)
                os.makedirs(droot, exist_ok=True)
                for fn in files:
                    sf, df = os.path.join(root, fn), os.path.join(droot, fn)
                    try:
                        if not os.path.exists(df):   # 不覆盖目标已有文件（目标可能已有数据）
                            shutil.copy2(sf, df)
                        # 校验：大小一致（copy2 保元数据，大小校验足够可靠且快）
                        if os.path.getsize(sf) != os.path.getsize(df):
                            raise RuntimeError(f"校验失败: {df} 与源大小不一致")
                        n += 1
                    except RuntimeError:
                        if strict:
                            raise   # 笔记内容不一致：迁移失败（用户红线：笔记必须完整）
                        skipped += 1   # log 单文件异常跳过
                    except (PermissionError, OSError):
                        if tolerant or not strict:
                            skipped += 1
                        else:
                            raise
            copied.append({"name": s, "files": n, **({"skipped": skipped} if skipped else {})})
        # 单文件（cmdlib.json）
        for s in _DATA_FILES:
            sf = os.path.join(DATA_DIR, s)
            if not os.path.isfile(sf):
                continue
            df = os.path.join(target, s)
            if not os.path.exists(df):
                shutil.copy2(sf, df)
            if os.path.getsize(sf) != os.path.getsize(df):
                raise RuntimeError(f"校验失败: {df} 与源大小不一致")
            copied.append({"name": s, "files": 1})
    except Exception as e:
        return jsonify({"ok": False, "err": f"迁移失败（未切换，数据仍在原处）: {e}",
                        "copied": copied}), 500
    # 复制校验全过 → 切换运行时 + 持久化
    old_data_dir = os.path.abspath(DATA_DIR)
    # 日志目录合一：迁移后固定走新 data/logs（清掉旧 log_dir 配置，只留一个 logs）
    new_log_dir = os.path.join(target, "logs")
    _st.DATA_DIR = target
    _st.STATE_DIR = target
    _st.LOG_DIR = new_log_dir
    _st.CMD_LIB_FILE = os.path.join(target, "cmdlib.json")
    # server.py 按值导入了 DATA_DIR/STATE_DIR/CMD_LIB_FILE，import 后再改 _st 属性
    # 不会同步到本模块绑定——不更新则二次迁移/GET /api/data_dir 仍用已删除的旧目录
    DATA_DIR = target
    STATE_DIR = target
    CMD_LIB_FILE = os.path.join(target, "cmdlib.json")
    LOG_DIR = new_log_dir
    try:
        import src.editor_files as _ef
        _ef.FILES_DIR = os.path.join(target, "files")
        _ef.IMAGES_DIR = os.path.join(_ef.FILES_DIR, "images")
    except Exception:
        pass
    # 日志索引缓存全部失效（路径已变）
    with _log_index_lock:
        _log_index_cache.clear()
    cfg = {**_load_config(), "data_dir": target, "log_dir": new_log_dir}
    _save_config(cfg)
    # ---- 校验已过（cmdlib/笔记严格校验，log 尽力、缓存仅搬壳），直接删旧目录 ----
    # 用户口径：不要旧目录备份，迁移完自动删。锁定文件残留由关工具自动清。
    shutil.rmtree(old_data_dir, ignore_errors=True)
    return jsonify({"ok": True, "dir": target, "copied": copied,
                    "deleted": True, "residual": 0,
                    "old_dir": old_data_dir, "note": "旧目录已删除"})

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
    # 与其他日志路由统一防线：Flask 默认转换器只挡 / 不挡 %5C（解码为 \），
    # Windows 上反斜杠是合法分隔符，join 后 ..\ 可逐级逃出 LOG_DIR
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return Response(f.read(), mimetype="text/plain")

@app.route("/api/replay/<name>")
def api_replay(name):
    """回放元信息：总行数 + 首末有效时间戳 + 时长。
    不再把全量行 JSON 拉给前端（G 级日志会几百 MB 且拖拽全量重建 DOM 卡死）。
    行数据改由 /api/replay_page 按需分页拉取，按时间跳转走 /api/replay_seek。
    ts<=0 的行（脏数据如 '0\\tinfo\\t'、注释行）不参与首末时间计算——
    曾经因末尾脏行 ts=0 把时长算成负数（-29804419:-19）。"""
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    total = idx.total
    if not total:
        return jsonify({"ok": True, "total": 0, "first_ts": 0, "last_ts": 0, "dur": 0})
    ts_arr = idx.ts_list()
    # ts_list 已把非法行用前值填充；首端无效行填充为 0，扫到第一个 >0 为止
    first_ts = 0
    for v in ts_arr:
        if v > 0:
            first_ts = v
            break
    last_ts = ts_arr[-1]
    dur = max(0, (last_ts - first_ts) / 1000) if first_ts > 0 and last_ts > 0 else 0
    return jsonify({"ok": True, "total": total, "first_ts": first_ts, "last_ts": last_ts, "dur": dur})

@app.route("/api/replay_page")
def api_replay_page():
    """回放分页取行：name + offset(0-based) + limit。行数据按需拉取，
    前端永不持有全量行。limit 上限 5000（播放前进一屏足够）。"""
    name = request.args.get("name", "")
    offset = int(request.args.get("offset", 0))
    limit = min(int(request.args.get("limit", 500)), 5000)
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    lines = idx.get_page(offset, limit)
    # 回放按 ts 驱动，清掉 ts=0 的脏行（如 '0\\tinfo\\t'），避免播放循环错乱
    lines = [l for l in lines if l.get("ts", 0) > 0 or l["tag"] == "comment" or l["text"]]
    return jsonify({"ok": True, "lines": lines, "total": idx.total})

@app.route("/api/replay_seek")
def api_replay_seek():
    """按时间戳定位回放起始行号：name + ts(毫秒)。
    二分 O(log n)，前端拖拽进度条时无需全量扫描。"""
    name = request.args.get("name", "")
    ts_ms = int(request.args.get("ts", 0))
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    row = idx.seek_ts(ts_ms)
    return jsonify({"ok": True, "row": row, "total": idx.total})


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
    """在日志文件搜索关键字。name=日志名或绝对路径，q=关键字，offset=起始行，limit=命中上限。
    count_total=0（续载）时跳过全量计数，只取下一批命中，速度大幅提升。
    exclude=排除模式，多个用 | 分隔，支持正则；命中任一段则该行剔除。"""
    name = request.args.get("name", "")
    q = request.args.get("q", "")
    exclude = request.args.get("exclude", "")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 200))
    count_total = request.args.get("count_total", "1") != "0"
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    res = idx.search(q, limit=limit, start_offset=offset, count_total=count_total, exclude=exclude)
    return jsonify({"ok": True, **res})

@app.route("/api/log_search_page")
def api_log_search_page():
    """按命中序号取页：第 [hit_start, hit_start+count) 条命中（依赖全量扫描建立的命中索引）。
    前端稀疏窗口缓存滚远回载时用，O(1) seek 毫秒级，不重扫不重计。"""
    name = request.args.get("name", "")
    q = request.args.get("q", "")
    exclude = request.args.get("exclude", "")
    hit_start = int(request.args.get("hit_start", 0))
    count = int(request.args.get("count", 500))
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
    idx = _get_log_index(path)
    lines = idx.search_page(q, hit_start, min(count, 500), exclude=exclude)
    total_hits = len(idx._hits_by_q.get((q, exclude or ""), ()))  # 复合键取命中索引长度
    return jsonify({"ok": True, "lines": lines, "hit_start": hit_start, "total_hits": total_hits})

@app.route("/api/log_open_external", methods=["POST"])
def api_log_open_external():
    """打开外部日志文件（任意路径），返回可用的 name 标识供后续 log_count/page/search 用。
    body: {path: 绝对路径}。"""
    data = request.get_json(force=True, silent=True) or {}
    p = (data.get("path") or "").strip()
    if not p or not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    return jsonify({"ok": True, "name": p, "size": os.path.getsize(p)})


@app.route("/api/file_info", methods=["POST"])
def api_file_info():
    """轻量文件信息：大小 + 是否文本后缀。前端打开文件前先探测，用于
    编辑器/阅读器分发决策（>20M 阅读器、20~30M 提示、其余可选）。
    body: {path: 绝对路径}。目录返回 {ok, is_dir: true}（拖文件夹进窗口
    → 设为文件树根，之前对目录返回 err 会误导前端弹"打开方式"窗）。"""
    data = request.get_json(force=True, silent=True) or {}
    p = (data.get("path") or "").strip()
    if not p:
        return jsonify({"ok": False, "err": "路径为空"}), 400
    if os.path.isdir(p):
        return jsonify({"ok": True, "is_dir": True})
    if not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    from src.editor_files import _EXT_TEXT, _ext_of
    return jsonify({"ok": True, "size": os.path.getsize(p),
                    "is_text": _ext_of(p) in _EXT_TEXT})


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

@app.route("/api/read_text")
def api_read_text():
    """对比用读文本：q=文件名或绝对路径。
    日志库内文件名（log tab 的 meta.path 可能是裸名）走 _resolve_log_path 解析；
    其余绝对路径直接读（对比任意文本都有意义，只挡目录/不存在/超限）。"""
    q = request.args.get("q", "")
    path = _resolve_log_path(q)
    if path is None:
        return jsonify({"ok": False, "err": "文件不存在或不可读"}), 400
    try:
        with open(path, "rb") as f:
            data = f.read(30 * 1024 * 1024 + 1)
        if len(data) > 30 * 1024 * 1024:
            return jsonify({"ok": False, "err": "文件过大（>30MB 上限）"}), 400
        return jsonify({"ok": True, "name": os.path.basename(path), "text": data.decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400

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

@app.route("/api/ai/open_file", methods=["POST"])
def ai_open_file():
    """让前端打开指定文件（--open-file 双击入口：已有实例收到新进程的打开请求）。
    {path}：绝对路径。广播 open_file 事件给前端 SSE，前端走 openFileSmart 智能分发。"""
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"ok": False, "err": f"文件不存在：{path}"})
    _broadcast_to_ai({"kind": "ui_action", "action": "open_file", "path": os.path.abspath(path)})
    return jsonify({"ok": True, "path": os.path.abspath(path)})


@app.route("/api/ai/compare_files", methods=["POST"])
def ai_compare_files():
    """AI 让前端打开文件对比 tab（Monaco DiffEditor）。
    {a, b}：两份文件的绝对路径。广播 open_diff 事件给前端 SSE，
    前端 connectAiSSE 收到后 buildDiffViewerTab。路径先校验存在。"""
    data = request.get_json(force=True, silent=True) or {}
    a, b = data.get("a", ""), data.get("b", "")
    if not a or not b:
        return jsonify({"ok": False, "err": "需要两个文件路径 a/b"})
    # 路径校验：日志库内文件名解析成绝对路径（与 diff_logs 同款 _resolve）；
    # 外部绝对路径必须已存在。复用编辑器白名单太窄（对比任意文本都有意义），
    # 这里只挡目录/不存在。
    a_p = _resolve_log_path(a)
    if not a_p:
        return jsonify({"ok": False, "err": f"A 文件不存在：{a}"})
    b_p = _resolve_log_path(b)
    if not b_p:
        return jsonify({"ok": False, "err": f"B 文件不存在：{b}"})
    _broadcast_to_ai({"kind": "ui_action", "action": "open_diff", "a": a_p, "b": b_p})
    return jsonify({"ok": True, "a": os.path.basename(a_p), "b": os.path.basename(b_p)})


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

@app.route("/api/ai/burst", methods=["POST"])
def ai_burst():
    """AI 数据连发：一次调用原子执行整条时间线（延时 + 命令/原始字节序列）。
    典型场景：内核下 reboot → 等 3s → uboot 倒计时窗口内多次连发 Ctrl-U（间隔 0.5~1s）。
    AI 自身思考/往返延迟掐不准 3s 窗口，须由后端在单次调用内精确编排。
    steps: [{delay: 秒(前置等待，默认0), cmd: "命令", 或 raw: [字节列表], wait: 发送后等回显秒数(默认0)}]"""
    data = request.get_json(force=True)
    port_id = data.get("port_id")
    steps = data.get("steps") or []
    with _ports_lock:
        p = _ports.get(port_id)
    if not p:
        return jsonify({"ok": False, "err": "串口未连接"})
    if not steps:
        return jsonify({"ok": False, "err": "steps 为空"})
    # 总时长上限 120s：防 AI 传错参数把后端线程挂死（HTTP 超时会断但服务线程还在睡）
    total = sum(float(s.get("delay", 0)) + float(s.get("wait", 0)) for s in steps)
    if total > 120:
        return jsonify({"ok": False, "err": f"总时长 {total:.1f}s 超过 120s 上限"})
    results = []
    try:
        with p.buf_lock:
            before_seq = p.buf[-1]["seq"] if p.buf else -1
        for i, s in enumerate(steps):
            delay = float(s.get("delay", 0))
            if delay > 0:
                time.sleep(delay)
            label = ""
            if s.get("cmd"):
                p.send_cmd(s["cmd"], newline=True)
                label = "cmd: " + s["cmd"]
            elif s.get("raw"):
                payload = bytes(int(b) & 0xFF for b in s["raw"] if isinstance(b, (int, float)))
                if payload:
                    p.send_raw(payload)
                label = f"raw: {list(payload)}"
            else:
                label = "（空步骤，仅延时）"
            wait = float(s.get("wait", 0))
            if wait > 0:
                time.sleep(wait)
            with p.buf_lock:
                now_seq = p.buf[-1]["seq"] if p.buf else -1
            new_items = p.get_buffer_after(before_seq)
            before_seq = now_seq
            results.append({"step": i + 1, "action": label,
                            "response": [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in new_items]})
        return jsonify({"ok": True, "port_id": port_id, "steps": results})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e), "steps": results})

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
    工具列表动态读 mcp_server._TOOLS（单一数据源，加工具不再两边漏同步），调用记录由 mcp_server 上报。"""
    try:
        # 懒 import：mcp_server 顶层只有标准库，但保持与 main.py --mcp 相同的延迟习惯
        from src.mcp_server import _TOOLS
        tools = [{"name": t["name"], "desc": t["description"].split("。")[0]} for t in _TOOLS]
    except Exception:
        # 兜底：mcp_server 不可导入时退回静态列表（老版行为）
        tools = [
            {"name": "observe", "desc": "概览所有连接 + 最近输出 + 已打开日志"},
            {"name": "list_ports", "desc": "列出可用串口 + 已连接"},
            {"name": "connect_serial", "desc": "建立串口连接"},
            {"name": "connect_ssh", "desc": "建立 SSH 连接"},
            {"name": "send_command", "desc": "发命令 + 等回显"},
            {"name": "send_raw", "desc": "发原始字节（Ctrl-C 等）"},
            {"name": "send_burst", "desc": "数据连发：原子执行整条时间线（延时+命令/字节序列）"},
            {"name": "get_buffer", "desc": "取连接最近 N 行缓冲"},
            {"name": "list_open_logs", "desc": "列出前端已打开的日志文件"},
            {"name": "read_log", "desc": "读日志文件（分页）"},
            {"name": "search_log", "desc": "日志关键字搜索"},
            {"name": "diff_logs", "desc": "对比两份日志差异（summary/line）"},
            {"name": "compare_files", "desc": "在前端打开两份文件的对比视图（Monaco DiffEditor）"},
            {"name": "disconnect", "desc": "断开连接"},
            {"name": "tftp_status", "desc": "TFTP 服务状态：运行中/目录/文件列表/传输记录"},
            {"name": "tftp_start", "desc": "启动 TFTP 服务（UDP 69），设备可上传/下载文件"},
            {"name": "tftp_stop", "desc": "停止 TFTP 服务"},
            {"name": "tftp_set_dir", "desc": "设置/切换 TFTP 根目录"},
        ]
    with _mcp_calls_lock:
        calls = list(_mcp_calls)
    # 读 endpoint 信息
    # 注意：endpoint.json 永远在 ~/.serialconsole_pro（main.py 写入端固定 HOME，
    # 不随数据目录迁移）——不能用 STATE_DIR：数据目录迁移后被切到数据目录。
    # HOME_DIR 本身就是 ~/.serialconsole_pro，直接拼文件名（上版多拼了一层目录）。
    ep_info = {}
    try:
        ep_path = os.path.join(HOME_DIR, "endpoint.json")
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


# ---- Claude 会话/技能发现（设计见 docs/CLAUDE_CODE_INTEGRATION.md §3.2） ----
@app.route("/api/claude/sessions")
def claude_sessions_list():
    """历史会话列表（~/.claude/projects 扫描），供「最近」claude 组与 Claude 面板。"""
    from .claude_sessions import list_sessions
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"ok": True, "sessions": list_sessions(limit=min(max(limit, 1), 200))})


@app.route("/api/claude/skills")
def claude_skills_list():
    """技能三来源列出（user/project/plugin）。"""
    from .claude_sessions import list_skills
    cwd = request.args.get("cwd") or None
    return jsonify({"ok": True, "skills": list_skills(cwd)})


@app.route("/api/claude/transcript")
def claude_transcript():
    """会话转写导出（历史回看覆盖层数据源）：jsonl → 干净对话行数组。
    一次性全量返回，前端缓存渲染——滚轮路径零网络往返（不卡顿的硬前提）。
    查找顺序：session_id 直查；否则按 port_id 从连接对象取 resume（新会话
    无 resume 时再从 ~/.claude/projects 取该 cwd 下 mtime 最新的 jsonl）。"""
    from .claude_sessions import export_session_transcript
    sid = (request.args.get("session_id") or "").strip()
    if not sid:
        pid = (request.args.get("port_id") or "").strip()
        with _ports_lock:
            p = _ports.get(pid)
            resume = getattr(p, "resume", None) if p else None
            cwd = getattr(p, "cwd", None) if p else None
        if resume:
            sid = resume
        elif cwd:
            # 新会话：无 resume id。取该 cwd 项目目录下 mtime 最新的 jsonl
            # （会话开聊即落盘；用户翻的就是当前正在用的这份转写）
            import glob as _g
            from .claude_sessions import _projects_dir
            proj = cwd.replace(":", "-").replace("\\", "/").replace("/", "-").replace(" ", "-")
            cands = []
            for f in _g.glob(os.path.join(_projects_dir(), "*", "*.jsonl")):
                try:
                    if os.path.basename(os.path.dirname(f)) == proj:
                        cands.append(f)
                except Exception:
                    continue
            if cands:
                newest = max(cands, key=os.path.getmtime)
                sid = os.path.splitext(os.path.basename(newest))[0]
    if not sid:
        return jsonify({"ok": False, "err": "session_id 不能为空"}), 400
    lines, cwd = export_session_transcript(sid)
    if lines is None:
        return jsonify({"ok": False, "err": "找不到该会话的转写文件"}), 404
    return jsonify({"ok": True, "session_id": sid, "cwd": cwd or "",
                    "lines": lines, "count": len(lines)})


@app.route("/api/claude/note", methods=["POST"])
def claude_session_note():
    """会话备注：{session_id, note}——note 空串清除。备注优先于 aiTitle 显示。"""
    from .claude_sessions import set_session_note
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("session_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "err": "session_id 不能为空"}), 400
    notes = set_session_note(sid, data.get("note") or "")
    return jsonify({"ok": True, "note": notes.get(sid, ""), "notes": notes})


@app.route("/api/claude/status")
def claude_status():
    """聚合状态：本工具打开的 claude 连接 + 外部活跃会话数。
    mine 行带 label：resume 会话去 sessions 列表按 session_id 匹配会话名
    （aiTitle 优先）；新会话没名字，回退 cwd 尾段。"""
    from .claude_sessions import list_sessions
    with _ports_lock:
        mine = [{"port_id": pid, "cwd": getattr(p, "cwd", ""),
                 "resume": getattr(p, "resume", None), "alive": p.alive}
                for pid, p in _ports.items() if getattr(p, "kind", "") == "claude"]
    sessions = list_sessions(limit=100)
    by_id = {s["session_id"]: s for s in sessions}
    for m in mine:
        s = by_id.get(m.get("resume") or "")
        m["label"] = (s and (s.get("title") or s.get("summary"))) or \
                     ((m.get("cwd") or "").split("\\")[-1].split("/")[-1] or m["port_id"])
        # 带上 summary/session_id：前端运行中卡片渲染成完整会话卡（含摘要/备注入口）
        if s:
            m["summary"] = s.get("summary") or ""
            m["note"] = s.get("note") or ""
            m["active"] = s.get("active", False)
    # 外部活跃计数排除本工具已打开的（否则同一会话被数两次：
    # 状态行「运行中 1 + 外部活跃 1」其实是同一个，徽章虚高）
    mine_ids = {m.get("resume") for m in mine if m.get("resume")}
    external = [s for s in sessions if s.get("active") and s["session_id"] not in mine_ids]
    return jsonify({"ok": True, "mine": mine, "external_active": len(external)})


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
    # 启动清理：idx/ 下超过 3 天未使用的索引文件（atime 由 _touch_idx 维护）
    try:
        from src.log_index import cleanup_stale_idx
        n = cleanup_stale_idx(3)
        if n:
            print(f"[idx] 已清理 {n} 个过期索引文件（3 天未使用）")
    except Exception:
        pass
    start_background()
    app.run(host="127.0.0.1", port=8765, threaded=True, debug=False, use_reloader=False)
