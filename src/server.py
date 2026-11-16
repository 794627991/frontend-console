#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端控制台 v2.2.0 —— 多串口/SSH 后端 + AI 接入层
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
import os, sys, time, threading, json, glob, re, base64, subprocess, collections
from queue import Queue

from flask import Flask, Response, request, jsonify, send_from_directory, g, redirect
import threading as _threading
# a346/R21-6：/api/theme 的 nav_keys 段 read-modify-write 并发锁
_nav_keys_lock = _threading.Lock()

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
from src.tree_search import tree_search_bp


app = Flask(__name__)
# v3.5.223 请求看门狗：在途请求 >2s 自动转储全部线程栈（复现 SSH 卡死类
# 后端阻塞的取证基建，dump 落 ~/.serialconsole_pro/watchdog_dump.log）
try:
    from src.watchdog import install_watchdog
    install_watchdog(app)
except Exception:
    pass


# v3.4.12（用户实锤「重启+Ctrl+F5 仍旧样式」）：调试模式——HARNESS_DEBUG_WEB=1
# 时前端资源直读源码目录 web/（本文件旁），彻底绕过 RES_DIR/_mem_web/一切副本；
# run_debug.bat 一键启动（先清旧进程残尸，控制台可见伺服模式打印）
DEBUG_WEB = os.environ.get("HARNESS_DEBUG_WEB") == "1"
# （v4 归一管线 a137 起唯一基准：HARNESS_V4 / __HG_V4__ 注入与 v4=0 回退
#  通道已随批G 全量退役，前端 v4main 不再有开关）
# Claude 子系统进程隔离（v4.0.0 串口卡顿根治，用户定调「Claude 随便占，
# 串口不能卡」）：harness/hiklink 重负载移驻 src/worker_app.py 独立进程，
# 本进程只留串口终端与轻量路由。CLAUDE_INLINE=1 回落旧单进程形态（排障）。
# WORKER_BASE 由 main.py 拉起 worker 后回填（""=未就绪），index 注入 +
# /api/harness、/api/hiklink 的 307 兜底重定向都在请求时读它。
CLAUDE_OFFLOAD = os.environ.get("CLAUDE_INLINE") != "1"
WORKER_BASE = ""
# a558（SSO 锁号实锤）：真应用实例判定——main.py 入口（含打包 exe，frozen）
# 或 worker 进程（worker_app 以 __main__ 运行时自设）。测试/临时实例
#（python -c 起 server、pytest、python -m src.server）不带此标记 →
# 不自启 HikLink 机器人、不自动登录 Lanz：每个临时实例原先都会带来一次
# SSO 登录 + 与常驻实例互踢（11-12 日志实锤：230 次实例自启、479 次 WS
# 认证、43+ 次 Lanz 真实登录 → SSO 风控锁号）
if (os.path.basename(sys.argv[0] or "") == "main.py"
        or getattr(sys, "frozen", False)
        or os.environ.get("FC_APP_BOOT") == "1"):
    os.environ["FC_APP_BOOT"] = "1"
_SRC_WEB = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         os.pardir, "web"))
if DEBUG_WEB:
    print("[debug-web] 前端直读源码目录: %s" % _SRC_WEB)
    print("[debug-web] RES_DIR(常规模式来源): %s" % RES_DIR)

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

# 注册笔记库索引 Blueprint（路由 /api/notes/*——搜索/双链/标签/导出，只读扫描 files/）
from src.notes_index import notes_bp
app.register_blueprint(notes_bp)

# 注册文件关联接管/还原 Blueprint（路由 /api/assoc/*，注册表只动 HKCU）
from src.file_assoc import assoc_bp
app.register_blueprint(assoc_bp)

# 注册文件树工作区 Blueprint（路由 /api/tree/*，根目录登记制安全模型）
app.register_blueprint(tree_bp)
app.register_blueprint(tree_search_bp)

# 注册版本控制 Blueprint（路由 /api/vcs/*，git/svn 查看+常用写；沿文件树登记根安全模型）
from src.vcs import vcs_bp
app.register_blueprint(vcs_bp)

# 注册 Claude 安装引导 Blueprint：a32x 起该蓝图已无任何端点（旧 zip 安装
# 通道彻底退役，用户令「这个通道彻底退役，不要了」）——保留注册仅为兼容，
# 实际依赖安装走下方 res_bp（.fcpk 资源包）。
from src.claude_setup import claude_setup_bp
app.register_blueprint(claude_setup_bp)

# v4.1（用户拍板）：离线资源状态/安装（统一 .fcpk 资源包的软提示与一键装）
from src.res_api import res_bp
app.register_blueprint(res_bp)

# a333：代码跳转索引（ctags + 编译白名单 + ELF 符号表；手动建库）
from src.nav_api import nav_bp
app.register_blueprint(nav_bp)

# ——以下三个 Claude 系蓝图随 proxy 二期（用户拍板）移驻 worker 进程：
#   usage_bp（/api/usage/*，monkeypatch proxy_core 采集——数据面在哪统计
#   就必须在哪）、claude_default_bp（/api/claude/api_config|profiles|…，
#   其 re-point 队列与 proxy 同进程才通）、proxy_bp（/api/proxy/*，面板
#   与数据面同体）。CLAUDE_INLINE=1 恢复原位注册。
if not CLAUDE_OFFLOAD:
    # 注册代理用量统计积木（路由 /api/usage/*）
    from src.proxy_usage import usage_bp
    app.register_blueprint(usage_bp)

    # 注册 Claude 默认环境/ API 配置 Blueprint（settings.json 铺设与 token 读写）
    from src.claude_default import claude_default_bp
    app.register_blueprint(claude_default_bp)

    # 注册 Claude Proxy Blueprint（重试代理+headroom 压缩+Lanz 额度，/api/proxy/*）
    from src.proxy import proxy_bp, proxy_module_init as _proxy_module_init
    app.register_blueprint(proxy_bp)
else:
    _proxy_module_init = None   # start_background 用（offload 时不在本进程初始化）

# HikLink 机器人积木（独立端口 8766 独立 app；POST /hiklink/robot，宿主零侵入）
# （进程隔离时不在本进程导入——导入链会拖进 claude_harness 全家；worker 侧承载）

# 注册 Claude Harness Blueprint（stream-json 界面化会话，/api/harness/*）
# 与 claude 终端（ConPTY TUI）平行的另一条通道，互不影响（铁律4）
# ——进程隔离（CLAUDE_OFFLOAD，v4.0.0 串口卡顿根治）：harness 与 HikLink
# 机器人移驻 worker 独立进程（src/worker_app.py），本进程只挂 307 兜底
# 重定向（见文件尾 claude_worker_relay）+ 前端 workerbase.js 直连；
# CLAUDE_INLINE=1 时恢复原位注册（排障通道）
if CLAUDE_OFFLOAD:
    _hiklink_bot = None   # /api/hiklink/* 路由不注册（worker 承载）
else:
    from src import hiklink_bot as _hiklink_bot
    from src.harness.routes import harness_bp
    app.register_blueprint(harness_bp)

# R3 审计 B6（D6，用户拍板）：/api/* 的 404/405 全局 JSON 化——错误方法/
# 未知 API 路径原先返回 Werkzeug HTML（AI 与脚本消费方解析困难），与全局
# JSON 错误口径不一致。非 /api/ 路径维持默认 HTML。必须在首请求前注册。
@app.errorhandler(404)
@app.errorhandler(405)
def _api_not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "err": "%s %s" % (e.code, e.name)}), e.code
    return e

# ---- 单实例唤醒通道 ----
# 二次启动的进程探活旧实例后 POST /api/raise_window，旧实例自弹主窗口
# （pywebview WinForms 宿主从自身线程 show 才稳，跨进程 SetForegroundWindow
# 兜底在 main.py）。路由必须在这里注册——Flask 首请求后禁止加路由。
_raise_window_cb = None


def set_raise_window_callback(cb):
    """main.py 注入 show 回调（webview 窗口建好后调，闭包捕获窗口）。"""
    global _raise_window_cb
    _raise_window_cb = cb


@app.route("/api/raise_window", methods=["POST"])
def raise_window():
    """让本实例弹主窗口（新进程探活后调用）。回调未注入（启动早期）返回 ok=False。"""
    cb = _raise_window_cb
    if cb:
        threading.Thread(target=cb, daemon=True).start()
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 503


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
            return False
    return True   # 调用方连接结束后必须 _drop_connecting(port_id)

def _drop_connecting(port_id):
    """连接结束（无论成败）释放占位锁。
    注册表条目永不 pop：锁对象按 port_id 复用——若此处 pop，另一线程
    setdefault 拿到的可能是「即将被 pop 的旧锁」，pop 后第三个线程建新锁，
    同一 port 两路并发 connect（锁失效竞态）。数量以连接目标为界，常驻无害。"""
    with _connecting_locks_guard:
        lock = _connecting_locks.get(port_id)
    if lock is not None:
        try: lock.release()
        except Exception: pass

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
    # v3.5.92：附件目录自动清理（半年过期 + 1GB 上限删至 80%；挂在这里=
    # main.py 导入启动与 server.py 直跑两条路径都覆盖）
    try:
        from src.data_hygiene import start as _dh_start
        _dh_start()
    except Exception:
        pass

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
    # ——进程隔离时随 proxy 移驻 worker（worker_app.main 调），本进程跳过
    if _proxy_module_init is not None:
        try:
            _proxy_module_init()
        except Exception as e:
            import logging
            logging.getLogger("claude_proxy").warning("proxy_module_init 失败: %s", e)
    # v2.2.2：机器人重启自恢复——登录凭据持久在 session 文件，重启后状态
    # 接口照报「已登录」，但 ensure_started 只在登录那一刻被调，bot 不会跟
    # 着复活（同事机实锤：登录成功机器人注册出来，重启工具后「未运行」且
    # 平台侧永远离线）。有凭据就后台拉起，幂等且失败只记日志不弹窗。
    # （进程隔离时 bot 在 worker——自恢复随迁 worker_app.main，本进程不起）
    # a558：再加 FC_APP_BOOT 门——测试/临时实例导入 server（CLAUDE_INLINE=1
    # 场景常见）不得拉起 bot，与常驻实例互踢（SSO 锁号防线）
    if not CLAUDE_OFFLOAD and os.environ.get("FC_APP_BOOT") == "1":
        def _bot_restore():
            time.sleep(8)   # 让端口/网络就绪，避开启动高峰
            try:
                from src import hiklink_bot as hb
                # 机器人只认凭证登录（SSO 自动注册已退役）：没凭证就别调
                # ensure_started，否则每次开机刷一行「启动自恢复失败」
                if hb.is_manual_mode():
                    ok, msg = hb.ensure_started()
                    import logging
                    logging.getLogger("hiklink_bot").info(
                        "启动自恢复机器人: %s (%s)", "成功" if ok else "失败", msg)
            except Exception as e:
                import logging
                logging.getLogger("hiklink_bot").warning(
                    "启动自恢复机器人异常: %s", e)
        threading.Thread(target=_bot_restore, daemon=True,
                         name="hiklink-bot-restore").start()

# ============================================================
# Flask 路由
# ============================================================
# a239（第5轮B2-P1A）：全站 Origin/Host 校验——主进程此前对任何来源的
# POST 都照单全收（get_json(force=True) 使 text/plain 跨源"简单请求"也能
# 解析 JSON）：远程网页可 CSRF 驱动 skills/install（往 ~/.claude/skills 落
# SKILL.md=持久提示注入）、tftp/set_dir 重瞄准（claude_setup 执行任意 zip
# 安装器这一面已随 a32x 退役）；DNS-rebinding（Host 无校验）还放开读面。对照 worker 进程 a116
# 已修同款，主进程漏网至今。
# 规则：
# - Host 必须 127.0.0.1[:port] / localhost[:port] / [::1]（拦 rebinding）
# - 写方法（POST/PUT/DELETE/PATCH）带 Origin 头时，必须 http(s)://127.0.0.1
#   或 localhost 任意端口（WebView2 内同源 fetch / snip 独立窗 / worker / MCP
#   的 urllib 请求无 Origin 或同源，均放行）
_LOCAL_HOST_RE = re.compile(
    r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", re.I)
# 复审 F5：不放宽为任意 loopback 端口——本机恶意页面（http://127.0.0.1:9999）
# 依旧全拦（对齐 worker a116 同款标准）。动态端口号启动时已知，见 _guard
_LOCAL_ORIGIN_RE = re.compile(
    r"^https?://(127\.0\.0\.1|localhost|\[::1\])/?$", re.I)


@app.before_request
def _guard_local_origin():
    try:
        host = (request.host or "").strip()
        if not _LOCAL_HOST_RE.match(host):
            return jsonify({"ok": False, "err": "forbidden host"}), 403
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = (request.headers.get("Origin") or "").strip()
            if origin:
                # 主页面同源（host 已过上面白名单，是本机随机端口的真身）；
                # 其余 loopback 端口（本机其他 Web 页面）一律拒——对齐 worker a116
                _own = "http://" + host
                if origin.rstrip("/") != _own and not _LOCAL_ORIGIN_RE.match(origin):
                    return jsonify({"ok": False, "err": "forbidden origin"}), 403
            # a239（第5轮B1）：顶层真值非对象的 JSON（"x"/123/true/[...]）此前
            # 在 12 个端点打穿 500 HTML——`(get_json(silent=True) or {})` 防不住
            # truthy 非 dict。此处一处收口：能解析且非 dict 一律 400。
            # multipart/form 上传跳过——get_json 会消费 stream 破坏文件解析
            _ct = (request.content_type or "")
            if "multipart" not in _ct and "form-" not in _ct:
                j = request.get_json(force=True, silent=True)
                if j is not None and not isinstance(j, dict):
                    return jsonify({"ok": False, "err": "请求体必须是 JSON 对象"}), 400
    except Exception:
        return jsonify({"ok": False, "err": "bad request"}), 400
    return None


@app.after_request
def _no_cache_static(resp):
    """静态资源(web/ 下的 JS/CSS)禁缓存：开发迭代频繁，WebView2 若缓存旧 JS，
    重启工具仍加载旧代码，改动"看起来不生效"。HTML/JS/CSS 每次都拉最新。
    """
    if resp.mimetype in ("text/html", "application/javascript",
                         "text/css", "text/javascript"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

def _mem_web(rel):
    """v2.3.6：加密门户的自解密 web 资源（main.FC_MEM_WEB，main 自举时解密
    进内存）优先——磁盘只有密文，内存 serve 明文给浏览器（不落盘）。
    dev 模式 dict 空，自动回落 send_from_directory 明文。任何异常回落磁盘
    （import 桥接失败也不能白屏——用户实锤：frozen 下 from src import
    secure_boot 抛 ImportError → / 路由 500）。返回 Response 或 None。"""
    try:
        # v2.3.6：字典挂 sys（frozen 下入口脚本模块名是 main 非 src.main，
        # import src.main 必失败——用户实锤白屏）
        data = getattr(sys, "FC_MEM_WEB", {}).get(rel.replace("\\", "/"))
    except Exception:
        return None
    if data is None:
        return None
    import mimetypes
    mt = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    resp = Response(data, mimetype=mt)
    if mt in ("text/html", "text/css", "application/javascript", "text/javascript"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/")
def index():
    """入口页（v3.5.1+ 版本注入）：index.html 源里的 __HG_VER__ 占位符在此
    统一替换为 HARNESS_VERSION（单一源 src/harness/__init__.py，全链唯一
    版本修改点）——boot 脚本与静态资源缓存参数三路（DEBUG/内存/磁盘）
    一致注入。"""
    try:
        from src.harness import HARNESS_VERSION as _HV
    except Exception:
        _HV = "0"
    def _inject(data):
        # __HG_WBASE__：Claude worker 基址（进程隔离；空串=未分离/未就绪，
        # workerbase.js 见空串即全透明零开销）。占位符与变量名 __HG_WORKER__
        # 刻意不同名——同名会被 replace 连变量名一起吃掉；请求时读 WORKER_BASE，
        # worker 重启换端口后刷新页面即得新值
        # __HG_WFAMFLAG__：worker 能力标记（注入 'proxy'=worker 已承载
        # proxy/usage/claude_default 族）。dev 模式前端文件从磁盘直读、后端
        # 进程可能还是旧代码——新 workerbase 若把 proxy 族改写到旧 worker
        # （只带 harness）就是全 404（用户实锤「API配置全不显示/代理一直
        # 检测中」）。旧后端不认此占位符→字面量残留→workerbase 只改写
        # harness/hiklink，与旧后端实际承载精确对齐。占位符与变量名
        # __HG_WFAM__ 刻意不同名——同名 replace 会连变量名一起吃掉
        # （__HG_V4FLAG__ 同款坑，a99F 实测再踩一次）
        # __HG_DBGF__：debug 页标志（DEBUG_WEB=1 注入 '1'，正式版空串）——
        # 前端只在 debug 版注册 pagehide 断连钩子（正式版无 F5 能力无此需求，
        # 用户定调：刷新清连接是调试机专属行为）。占位符与变量名 __HG_DBG__
        # 刻意不同名——同名 replace 连变量名一起吃（__HG_V4FLAG__ 同款坑）
        if isinstance(data, bytes):
            data = data.replace(b"__HG_VER__", _HV.encode("utf-8"))
            data = data.replace(b"__HG_WBASE__", WORKER_BASE.encode("utf-8"))
            data = data.replace(b"__HG_WFAMFLAG__", b"proxy" if CLAUDE_OFFLOAD else b"")
            # 带引号注入（前端 __HG_DBGF__==='1' 字符串严格比较——裸 1 会
            # 1==='1' 恒 false，钩子永不注册=刷新清场整个死链，用户实锤）
            return data.replace(b"__HG_DBGF__", b"'1'" if DEBUG_WEB else b"''")
        data = data.replace("__HG_VER__", _HV)
        data = data.replace("__HG_WBASE__", WORKER_BASE)
        data = data.replace("__HG_WFAMFLAG__", "proxy" if CLAUDE_OFFLOAD else "")
        return data.replace("__HG_DBGF__", "'1'" if DEBUG_WEB else "''")
    if DEBUG_WEB:
        with open(os.path.join(_SRC_WEB, "index.html"), "rb") as f:
            return Response(_inject(f.read()), mimetype="text/html")
    try:
        r = _mem_web("web/index.html")
    except Exception:
        r = None
    if r is not None:
        # v3.5.80：入口页强制 no-cache——旧实现透传打包资源的 Cache-Control
        #（空/带 max-age），WebView2 持久缓存会端出旧 index.html → 引用旧
        # ?v= 脚本地址 = 整套旧前端（版本徽章走 API 是新的，页面却是旧引擎，
        # 用户实锤「v3.5.78 拖拽修复没生效」的真因）。no-cache 仅要求每次
        # 校验（304 语义），内容几 KB 零成本；子资源照旧吃 ?v= 长缓存
        return Response(_inject(r.get_data()), mimetype="text/html",
                        headers={"Cache-Control": "no-cache"})
    with open(os.path.join(RES_DIR, "web", "index.html"), "rb") as f:
        return Response(_inject(f.read()), mimetype="text/html")

@app.route("/web/<path:fn>")
def web_files(fn):
    if DEBUG_WEB:
        # 调试模式禁缓存（?v= 依赖 HARNESS_VERSION 手动 bump,源码热改期间
        # URL 恒定 → WebView 命中旧缓存 → 「改了没效果」连环坑的总根,用户
        # 实锤多轮）。no-store 保证每次直读源码目录最新文件
        resp = send_from_directory(_SRC_WEB, fn)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    try:
        r = _mem_web("web/" + fn)
    except Exception:
        r = None
    if r is not None:
        return r
    return send_from_directory(os.path.join(RES_DIR, "web"), fn)

@app.route("/<path:fn>")
def static_files(fn):
    if DEBUG_WEB and os.path.isfile(os.path.join(_SRC_WEB, fn)):
        return send_from_directory(_SRC_WEB, fn)
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

@app.route("/favicon.ico")
def favicon():
    """v3.5.81：浏览器每页必请求 favicon——此前 404 刷控制台（用户实锤
    DevTools 红错之一），回应用图标"""
    return send_from_directory(ICO_DIR, "app.ico")

@app.route("/api/ports")
def api_ports():
    return jsonify({"ports": list_ports(), "bauds": COMMON_BAUDS})

_office_convert_cache = {}   # 源路径 mtime → 转换后路径（同文件不重复转）

def _office_convert_legacy(path, ext):
    """a281：.doc/.ppt 旧格式 → .docx/.pptx（Word/PowerPoint COM 自动转换）。
    转换结果缓存在 %TEMP%/office_conv/（按源文件 mtime 失效）。
    需要 Office 已安装；未安装返回 None 由调用方提示。"""
    import subprocess, tempfile
    key = os.path.abspath(path).lower() + ":" + str(os.path.getmtime(path))
    if key in _office_convert_cache:
        cached = _office_convert_cache[key]
        if os.path.isfile(cached):
            return cached
    conv_dir = os.path.join(tempfile.gettempdir(), "office_conv")
    os.makedirs(conv_dir, exist_ok=True)
    # a309R2 M2（审查实锤：同名不同目录缓存碰撞——打开 A 显示 B 的 PDF）：
    # 文件名加全路径哈希前缀，碰撞面消除
    import hashlib as _hl
    _tag = _hl.md5(os.path.abspath(path).lower().encode("utf-8")).hexdigest()[:10]
    dst = os.path.join(conv_dir, _tag + "_" + os.path.splitext(os.path.basename(path))[0] + ext + "x")
    if os.path.isfile(dst):
        _office_convert_cache[key] = dst
        return dst
    app_name = "Word.Application" if ext == "doc" else "PowerPoint.Application"
    fmt = 16 if ext == "doc" else 24   # 16=wdFormatXMLDocument, 24=ppSaveAsOpenXMLPresentation
    _p = path.replace("'", "''")   # H2：PS 单引号转义（RCE 防注入）
    _d = dst.replace("'", "''")
    ps_script = (
        f"$app = New-Object -ComObject {app_name}; "
        f"$app.Visible = $false; "
        f"$doc = $app.Documents.Open('{_p}'); "
        f"$doc.SaveAs([ref]'{_d}', [ref]{fmt}); "
        f"$doc.Close(); $app.Quit()"
    ) if ext == "doc" else (
        f"$app = New-Object -ComObject {app_name}; "
        f"$app.Visible = $false; "
        f"$pres = $app.Presentations.Open('{_p}'); "
        f"$pres.SaveAs('{_d}', {fmt}); "
        f"$pres.Close(); $app.Quit()"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=30, creationflags=0x08000000)
        if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
            _office_convert_cache[key] = dst
            return dst
    except Exception:
        pass
    return None

_office_pdf_cache = {}

@app.route("/api/office/write", methods=["POST"])
def api_office_write():
    """a290 全功能：Office 编辑保存写回。body=原始文件字节，path=绝对路径。
    白名单扩展名 + 设备名校验（与 read 同源），备份 .bak 一次。"""
    from src.app_state import reject_win_devpath
    q = request.args.get("path", "") or request.args.get("q", "")
    if reject_win_devpath(q):
        return jsonify({"ok": False, "err": "路径包含 Windows 保留设备名"}), 400
    if not os.path.isabs(q) or not os.path.isfile(q):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    _ext = os.path.splitext(q)[1].lower().lstrip(".")
    if _ext not in ("xlsx", "xls", "csv", "docx"):
        return jsonify({"ok": False, "err": f"不支持写回的类型: .{_ext}"}), 400
    data = request.get_data()
    if not data or len(data) > 100 * 1024 * 1024:
        return jsonify({"ok": False, "err": "内容为空或过大"}), 400
    try:
        bak = q + ".bak"
        if not os.path.isfile(bak):
            import shutil
            shutil.copy2(q, bak)   # 首次保存前备份一次（防编辑事故）
        with open(q, "wb") as f:
            f.write(data)
        return jsonify({"ok": True, "size": len(data)})
    except Exception as e:
        return jsonify({"ok": False, "err": f"写回失败: {e}"}), 400

def _office_topdf(path):
    """a290 全功能 Office：Word/PowerPoint COM 导出 PDF（保真查看的唯一靠谱链）——
    PPT 纯前端渲染库不成熟（用户实锤全打不开），转 PDF 后走前端 PDF Pro 引擎
    （虚拟化/搜索/缩放/翻页全都有）。缓存按 mtime 失效，同 _office_convert。"""
    import subprocess, tempfile
    key = os.path.abspath(path).lower() + ":pdf:" + str(os.path.getmtime(path))
    if key in _office_pdf_cache:
        cached = _office_pdf_cache[key]
        if os.path.isfile(cached):
            return cached
    conv_dir = os.path.join(tempfile.gettempdir(), "office_conv")
    os.makedirs(conv_dir, exist_ok=True)
    import hashlib as _hl   # M2 同款：路径哈希前缀防同名碰撞
    _tag = _hl.md5(os.path.abspath(path).lower().encode("utf-8")).hexdigest()[:10]
    dst = os.path.join(conv_dir, _tag + "_" + os.path.splitext(os.path.basename(path))[0] + ".pdf")
    is_word = os.path.splitext(path)[1].lower().lstrip(".") in ("doc", "docx")
    app_name = "Word.Application" if is_word else "PowerPoint.Application"
    fmt = 17 if is_word else 32   # wdFormatPDF / ppSaveAsPDF
    _p = path.replace("'", "''")   # H2：PS 单引号转义（RCE 防注入）
    _d = dst.replace("'", "''")
    if is_word:
        ps = (f"$app = New-Object -ComObject {app_name}; $app.Visible = $false; "
              f"$doc = $app.Documents.Open('{_p}'); $doc.SaveAs([ref]'{_d}', [ref]{fmt}); "
              f"$doc.Close(); $app.Quit()")
    else:
        ps = (f"$app = New-Object -ComObject {app_name}; $app.Visible = $false; "
              f"$pres = $app.Presentations.Open('{_p}', $true, $false, $false); "
              f"$pres.SaveAs('{_d}', {fmt}); $pres.Close(); $app.Quit()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60, creationflags=0x08000000)
        if r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
            _office_pdf_cache[key] = dst
            return dst
    except Exception:
        pass
    return None

# ================= a290 全功能：OnlyOffice Document Server 集成 =================
# 用户令"允许大依赖，要全功能编辑"——docx/xlsx/pptx 的真·全功能编辑（Office 级
# 保真、协同格式兼容）只有 OnlyOffice DS 可达。本机安装桌面版 DS（免费）后自动
# 探测启用；未装则前端按钮给安装指引（现有预览/编辑链照常可用）。

_DS_CANDIDATES = ["http://localhost:80", "http://localhost:8080", "http://127.0.0.1:80", "http://localhost:8888"]

def _ds_probe():
    """探测本机 Document Server（/healthcheck，1s 超时）。返回可用基址或 None。"""
    import urllib.request
    for base in _DS_CANDIDATES:
        try:
            req = urllib.request.Request(base + "/healthcheck", method="GET")
            with urllib.request.urlopen(req, timeout=1) as r:
                if r.status == 200:
                    return base
        except Exception:
            continue
    return None

def _ds_jwt_secret():
    """尝试读 DS local.json 的 JWT secret（v7.2+ 默认开 JWT；读不到返回 None
    ——前端配置将不带签名，需用户在 DS 配置关校验或复制 secret 到 config）。"""
    import json as _json
    for pth in (
        "C:/Program Files/ONLYOFFICE/DocumentServer/config/local.json",
        "C:/Program Files (x86)/ONLYOFFICE/DocumentServer/config/local.json",
    ):
        try:
            # utf-8-sig：PowerShell Set-Content -Encoding UTF8 写 BOM——
            # utf-8 裸读抛 JSONDecodeError → secret 永远读不到 → 误报 jwt_hint（实锤）
            with open(pth, "r", encoding="utf-8-sig") as f:
                cfg = _json.load(f)
            return (cfg.get("services", {}).get("CoAuthoring", {})
                      .get("secret", {}).get("inbox", {}).get("string")
                    or cfg.get("services", {}).get("CoAuthoring", {})
                      .get("secret", {}).get("session", {}).get("string"))
        except Exception:
            continue
    return None

def _jwt_hs256(payload, secret):
    """自包含 HS256 JWT（无第三方依赖；DS 校验用）。"""
    import base64, hashlib, hmac as _hmac, json as _json, time
    def b64u(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    header = b64u(_json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64u(_json.dumps({**payload, "iat": int(time.time())}).encode())
    sig = b64u(_hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"

@app.route("/api/office/ds/config")
def api_office_ds_config():
    """生成 OnlyOffice 编辑器配置（探测 DS → 文档配置 + JWT）。"""
    from src.app_state import reject_win_devpath
    q = request.args.get("path", "") or request.args.get("q", "")
    if reject_win_devpath(q) or not os.path.isabs(q) or not os.path.isfile(q):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    base = _ds_probe()
    if not base:
        return jsonify({"ok": False, "err": "未检测到 OnlyOffice Document Server",
                        "install_hint": "安装免费桌面版后重启工具：https://www.onlyoffice.com/zh/download-docs.aspx#docs-community （选 Document Server for Windows）"})
    ext = os.path.splitext(q)[1].lower().lstrip(".")
    doc_type = {"docx": "word", "doc": "word", "xlsx": "cell", "xls": "cell",
                "pptx": "slide", "ppt": "slide", "csv": "cell"}.get(ext)
    if not doc_type:
        return jsonify({"ok": False, "err": f"OnlyOffice 不支持 .{ext}"}), 400
    host = request.host_url.rstrip("/")
    # a298：key 必须是安全短串（字母数字-_)。旧 key=完整路径:mtime:size——含中文/
    # 盘符/冒号，DS 把 key 用作 doc 服务路由 shardkey，特殊字符直接 400（用户
    # 实锤全打不开：ws/polling 全 400）。改 md5(路径+mtime+size) 哈希
    import hashlib
    key = hashlib.md5(f"{os.path.abspath(q).lower()}:{os.path.getmtime(q)}:{os.path.getsize(q)}".encode("utf-8")).hexdigest()[:20]
    cfg = {
        "documentType": doc_type,
        "document": {
            "fileType": ext,
            "key": key,
            "title": os.path.basename(q),
            "url": host + "/api/office/read?path=" + _quote_url(q),
            "permissions": {"edit": True, "download": True, "print": True},
        },
        "editorConfig": {
            "lang": "zh-CN",
            "mode": "edit",
            "callbackUrl": host + "/api/office/ds/callback?path=" + _quote_url(q),
            "user": {"id": "local", "name": "本机"},
        },
        "type": "desktop",
    }
    secret = _ds_jwt_secret()
    if secret:
        cfg["token"] = _jwt_hs256(cfg, secret)
        return jsonify({"ok": True, "dsUrl": base, "config": cfg, "jwt": True})
    return jsonify({"ok": True, "dsUrl": base, "config": cfg, "jwt": False,
                    "jwt_hint": "未读到 DS 的 JWT secret——若打开报错(token)，在 DS 的 local.json 里关掉 JWT 校验（services.CoAuthoring.token.enable.browser/inbox/outbox=false）后重启 DS"})

def _quote_url(u):
    from urllib.parse import quote
    return quote(u)

@app.route("/api/office/ds/callback", methods=["POST"])
def api_office_ds_callback():
    """OnlyOffice 保存回调：status=2(编辑完成)/6(强制保存) 时从 DS 的 url 拉新文件写回。"""
    from src.app_state import reject_win_devpath
    import urllib.request, shutil
    from urllib.parse import urlparse
    q = request.args.get("path", "") or request.args.get("q", "")
    if reject_win_devpath(q) or not os.path.isfile(q):
        return jsonify({"error": 1}), 400
    # M1（a309R3 第2轮实锤）：本端点无鉴权可被任意本地页面 POST——
    # ① 扩展名白名单（与 read/write 对齐），此前 canary.txt 任意文件可被覆写；
    # ② url 必须 http(s)：urlretrieve 收 file:// 即任意本地文件读取→覆写目标
    _ext = os.path.splitext(q)[1].lower().lstrip(".")
    if _ext not in ("docx", "doc", "xlsx", "xls", "csv", "pptx", "ppt"):
        return jsonify({"error": 1}), 400
    try:
        j = request.get_json(force=True) or {}
        if j.get("status") in (2, 6) and j.get("url"):
            u = j["url"]
            pu = urlparse(u)
            if pu.scheme not in ("http", "https") or not pu.netloc:
                return jsonify({"error": 1}), 400
            tmp = q + ".dsdown"
            urllib.request.urlretrieve(u, tmp)
            if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                bak = q + ".bak"
                if not os.path.isfile(bak):
                    shutil.copy2(q, bak)
                os.replace(tmp, q)
        return jsonify({"error": 0})
    except Exception:
        return jsonify({"error": 1})

@app.route("/api/office/read")
def api_office_read():
    """a280：Office 查看器读文件（docx/pdf/xlsx）。q=绝对路径。
    白名单扩展名 + 已登记根内 + 设备名/目录校验。返回原始字节。"""
    from src.app_state import reject_win_devpath
    q = request.args.get("path", "") or request.args.get("q", "")
    if reject_win_devpath(q):
        return jsonify({"ok": False, "err": "路径包含 Windows 保留设备名"}), 400
    if not os.path.isabs(q) or not os.path.isfile(q):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    _ext = os.path.splitext(q)[1].lower().lstrip(".")
    # a290 全功能：?aspdf=1 → COM 导出 PDF（pptx/ppt/docx/doc）——PPT 打开的
    # 唯一保真链，docx 也可走（打印/严格版式场景）
    if request.args.get("aspdf") and _ext in ("pptx", "ppt", "docx", "doc"):
        pdf = _office_topdf(q)
        if not pdf:
            return jsonify({"ok": False, "err": "PDF 导出失败（需要安装 Office；PowerPoint/Word 会后台启动转换）"}), 400
        with open(pdf, "rb") as f:
            return f.read(), 200, {"Content-Type": "application/pdf"}
    # a281：.doc/.ppt 旧格式支持——服务端 Word COM 自动转 .docx 后交给前端渲染
    if _ext in ("doc", "ppt"):
        try:
            converted = _office_convert_legacy(q, _ext)
            if converted:
                with open(converted, "rb") as f:
                    return f.read(), 200, {"Content-Type": "application/octet-stream"}
            return jsonify({"ok": False, "err": f"转换失败（需要安装 Word/PowerPoint 或手动另存为 .{_ext}x）"}), 400
        except Exception as e:
            return jsonify({"ok": False, "err": f"旧格式转换失败: {e}"}), 400
    if _ext not in ("docx", "pdf", "xlsx", "xls", "csv", "pptx"):
        return jsonify({"ok": False, "err": f"不支持的文件类型: .{_ext}"}), 400
    try:
        size = os.path.getsize(q)
        if size > 100 * 1024 * 1024:
            return jsonify({"ok": False, "err": "文件过大（>100MB 上限）"}), 400
        with open(q, "rb") as f:
            return f.read(), 200, {"Content-Type": "application/octet-stream"}
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500

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

# v3.5.5：paramiko 服务端 disconnect 抓手——Transport 收到 MSG_DISCONNECT
# 时只写日志不存异常对象（且 paramiko.transport 日志级别默认 INFO 不外达），
# 认证异常分类需要它还原服务端真实拒绝原因（Max connections limit 等）。
# monkeypatch _parse_disconnect 截获 (code, desc) 存模块级 deque（最近 8 条，
# 带时间戳），分类时取 3s 内最新——并发连接误配窗口极小且同类错误指向一致
_SSH_DISC_RECENT = collections.deque(maxlen=8)
_SSH_DISC_PATCHED = False
def _ssh_disc_patch():
    global _SSH_DISC_PATCHED
    if _SSH_DISC_PATCHED:
        return
    try:
        from paramiko.transport import Transport
        _orig = Transport._parse_disconnect
        def _patched(self, m):
            try:
                code = m.get_int()
                desc = m.get_text()
                _SSH_DISC_RECENT.append((time.time(), int(code), str(desc)))
            except Exception:
                pass
            return _orig(self, m)
        Transport._parse_disconnect = _patched
        _SSH_DISC_PATCHED = True
    except Exception:
        pass
def _ssh_last_disconnect(max_age=3.0):
    now = time.time()
    best = None
    for ts, code, desc in _SSH_DISC_RECENT:
        if now - ts <= max_age:
            best = "Disconnect (code %d): %s" % (code, desc)   # deque 时间序，取最新
    return best


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
        _ssh_disc_patch()   # v3.5.5：装 disconnect 截获 patch（幂等）
        port_id = f"ssh:{host}:{port}"
        # v3.5.315（同事需求「ssh 我想双开，有的时候想看两个界面」）：SSH 允许
        # 同主机多开——每个连接是独立 paramiko channel=独立 shell 界面；同目标
        # 已连接/连接中时自动追加实例序号（ssh:host:port#2/#3…），首连保持无
        # 后缀（向后兼容：旧记录/快捷重开的 port_id 不变）。串口不适用（物理
        # 口独占）。序号分配持 _ports_lock 防双开竞态；_connecting_locks 条目
        # 永不 pop，故用锁持有态（locked）判「连接中」而非键存在（避免关掉
        # 后序号跳涨）。
        with _ports_lock:
            _base, _n = port_id, 1
            def _ssh_busy(pid):
                if pid in _ports:
                    return True
                lk = _connecting_locks.get(pid)
                return bool(lk and lk.locked())
            while _ssh_busy(port_id):
                _n += 1
                port_id = f"{_base}#{_n}"
        # 占位防同目标重入；连接动作在锁外执行（10s 超时不再卡全局 API/其他快捷打开）
        if not _acquire_connecting(port_id):
            with _ports_lock:
                if port_id in _ports:
                    return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
            return jsonify({"ok": False, "err": f"{port_id} 正在连接中，请稍候"}), 400
        try:
            p = None   # 预置：构造在 __init__ 内抛异常（DNS 解析失败等）时 p 未绑定，
                       # 下方 except 里裸 p.close() 会 NameError 被吞——半构造对象无人回收
            try:
                p = SSHConnection(host, port, username, password=password, key_path=key_path, port_id=port_id)
            except Exception as e:
                # start() 在构造内执行，_start_log 失败或后续步骤异常会留下
                # 半构造对象（已开 SSH 会话+读线程）——必须 close 兜底，否则幽灵会话泄漏
                if p is not None:
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
                        # v3.5.5（用户实锤「实际是 Max connections 误报密码错」）：
                        # paramiko 固定文案 "Authentication failed: transport shut
                        # down or saw EOF" = 服务端在认证阶段主动 disconnect
                        # （连接数达上限/主机拒绝等），并非密码错——真密码错的
                        # 文案没有该后缀。定性看文案，定量（服务端原始 reason）
                        # 从 paramiko 日志抓最近一条 Disconnect 行
                        if "transport shut down or saw EOF" in str(e):
                            _d = _ssh_last_disconnect()
                            if _d and "max connection" in _d.lower():
                                msg = ("设备拒绝连接：连接数已达上限（Max connections "
                                       "limit）——请关闭该设备的其他 SSH 会话后重试")
                            elif _d:
                                msg = f"设备在认证阶段主动断开连接：{_d}"
                            else:
                                msg = ("设备在认证阶段主动断开连接（常见原因：连接数"
                                       "达上限/主机拒绝该客户端）——并非用户名或密码错误")
                        else:
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
            # a267：close 移出 _ports_lock（同串口分支）
            _dup = None
            with _ports_lock:
                if port_id in _ports:   # 极端并发：两次同目标连接都成功了，后到者关掉
                    _dup = p
                else:
                    _ports[port_id] = p
            if _dup is not None:
                try: _dup.close()
                except Exception: pass
                return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
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
            p = None   # 预置防 NameError（同 SSH 分支）
            try:
                from .telnet_conn import TelnetConnection
                p = TelnetConnection(host, port, port_id=port_id)
            except Exception as e:
                if p is not None:
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
    elif kind == "shell":
        # a581（用户需求）：本地终端——起来就是可敲命令的 shell 窗口。
        # 引擎见 src/shell_conn.py（ConPTY，与 ClaudeConnection 同源）。
        from .shell_conn import ShellConnection, SHELLS
        shell = (data.get("shell") or "cmd").strip().lower()
        # 白名单必须校验：shell 名直接进 argv[0]，任意值等于任意可执行注入
        if shell not in SHELLS:
            return jsonify({"ok": False,
                            "err": "不支持的 shell：%s" % shell}), 400
        cwd = (data.get("cwd") or "").strip()
        if cwd and not os.path.isdir(cwd):
            return jsonify({"ok": False, "err": "目录不存在：%s" % cwd}), 400
        # 多开：同一 shell 每次新建一个序号实例（与 claude:{n} 同构）
        with _ports_lock:
            n = 1
            while "shell:%s:%d" % (shell, n) in _ports:
                n += 1
            port_id = "shell:%s:%d" % (shell, n)
        # ConPTY spawn 在杀软实时扫描下可达秒级 → 构造移出 _ports_lock
        # （同 SSH/串口/claude 分支），占位锁防同目标重入
        if not _acquire_connecting(port_id):
            return jsonify({"ok": False, "err": "该终端正在打开中，请稍候"}), 400
        try:
            p = None
            try:
                p = ShellConnection(shell=shell, cwd=cwd or None, port_id=port_id)
            except ValueError as e:
                return jsonify({"ok": False, "err": str(e)}), 400
            except Exception as e:
                if p is not None:
                    try: p.close()
                    except Exception: pass
                return jsonify({"ok": False, "err": str(e) or e.__class__.__name__}), 500
            with _ports_lock:
                if port_id in _ports:      # 极端并发：后到者关掉自己
                    try: p.close()
                    except Exception: pass
                    return jsonify({"ok": False, "err": f"{port_id} 已连接"}), 400
                _ports[port_id] = p
        finally:
            _drop_connecting(port_id)
        return jsonify({"ok": True, "port_id": port_id, "kind": "shell",
                        "shell": shell, "cwd": p.cwd,
                        "msg": "已打开终端（%s）" % p.shell_name})
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
        # a239（第5轮A3-P3-8）：ConPTY spawn 在杀软实时扫描下可达秒级，构造
        # 移出全局 _ports_lock（SSH/串口/telnet 已同款移出——锁内 spawn 期间
        # /api/status、/api/send、全部 _ports 读写排队，正是 210 行注释的事故
        # 形态）。占位防同目标重入，锁内复查登记
        if not _acquire_connecting(port_id):
            return jsonify({"ok": False, "err": "该会话正在打开中，请稍候"}), 400
        try:
            with _ports_lock:
                if port_id in _ports:
                    return jsonify({"ok": False, "err": "该会话已在工具内打开"}), 400
            p = None   # 预置防 NameError（同 SSH 分支）
            try:
                p = ClaudeConnection(cwd=cwd, resume=resume, port_id=port_id,
                                     light_theme=light_theme, agents=agents)
                # a267：close 移出 _ports_lock（同串口分支——锁内关卡全局 API）
                _dup = None
                with _ports_lock:
                    if port_id in _ports:   # 双检：占位期间被并发抢先（理论上占位已挡）
                        _dup = p
                    else:
                        _ports[port_id] = p
                if _dup is not None:
                    try: _dup.close()
                    except Exception: pass
                    return jsonify({"ok": False, "err": "该会话已在工具内打开"}), 400
            except Exception as e:
                # 构造内 start() 已 spawn PTY+读线程，异常必须 close 兜底（同 SSH/串口模式）
                _ports.pop(port_id, None)
                if p is not None:
                    try: p.close()
                    except Exception: pass
                return jsonify({"ok": False, "err": _humanize_claude_error(e)}), 500
        finally:
            _drop_connecting(port_id)
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
            p = None   # 预置防 NameError（同 SSH 分支）
            try:
                p = SerialPort(port, baud, port_id)
            except Exception as e:
                # 构造内 start() 已开串口句柄/读线程，异常必须 close 兜底，
                # 否则 COM 口被半构造对象占死，再连必 PermissionError
                if p is not None:
                    try: p.close()
                    except Exception: pass
                return jsonify({"ok": False, "err": str(e)}), 500
            # a267（用户 devtools 追踪实锤 wait=109s）：p.close() 关劣化 COM 口
            # 可卡驱动级百秒——绝不能在 _ports_lock 内关（全局 API 全堵）。
            # 先锁内查重，命中则锁外关闭
            _dup = None
            with _ports_lock:
                if port_id in _ports:
                    _dup = p
                else:
                    _ports[port_id] = p
            if _dup is not None:
                try: _dup.close()
                except Exception: pass
                return jsonify({"ok": False, "err": f"{port} 已连接"}), 400
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


@app.route("/api/reload_disconnect", methods=["POST"])
def api_reload_disconnect():
    """debug 页刷新清场（用户定调）：正式发布版禁用前端刷新（无 F5），
    只有调试机（HARNESS_DEBUG_WEB=1）能刷新——刷新瞬间页面来不及发
    disconnect，串口/SSH 句柄滞留后端进程占口（CDP 强刷实测 COM10 被
    自身后端占用）。pagehide sendBeacon 打到这里，全部连接即刻回收；
    正式版即使手工 POST 也 404（双门：前端不注册钩子 + 后端 DEBUG_WEB）
    """
    if not DEBUG_WEB:
        return jsonify({"ok": False, "err": "仅调试模式"}), 404
    close_all_ports()
    return jsonify({"ok": True})

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


def _q_int(key, default=0, lo=None, hi=None):
    """query 整数安全转换（a238 P3：原裸 int() 对非数字参数抛 ValueError →
    Flask HTML 500）。非法值回落 default，再按 lo/hi 钳制。"""
    try:
        v = int(request.args.get(key, default))
    except (TypeError, ValueError):
        v = default
    if lo is not None: v = max(lo, v)
    if hi is not None: v = min(hi, v)
    return v

@app.route("/api/buffer")
def api_buffer():
    port_id = request.args.get("port_id")
    n = _q_int("n", 500, lo=1)
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
    limit = _q_int("limit", 200, lo=1)
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

def _web_favs_clean(items):
    """网页收藏清洗（R-命名统一批次）：url/title 字符串白名单 + 截断
    （url≤2048 / title≤200）+ 上限 100，与前端 _webFavsSave 同口径。
    RC2（红队）：url 加 scheme 白名单——原仅查长度，file:// 收藏全链
    存活（服务端往返→种子回填→一次点击内嵌浏览器打开本地文件）。
    RC3（红队）：ts 非数值不再裸 int() 500。"""
    out = []
    if not isinstance(items, list):
        return out
    for it in items[:200]:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "").strip()
        # RC2：scheme 白名单（与前端 _webNormUrl 放行集一致）
        if not url or len(url) > 2048:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        try:
            ts = int(it.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0   # RC3：畸形 ts 落 0，不再 500
        entry = {"url": url,
                 "title": str(it.get("title") or "").strip()[:200],
                 "ts": ts}
        note = str(it.get("note") or "").strip()[:100]
        if note:
            entry["note"] = note
        out.append(entry)
    return out[:100]


def _safe_cfg_int(v, lo, hi, default=0):
    """a565 审计：config 脏值安全取整（GET /api/theme 不因手工编辑的
    config.json 抛 TypeError/ValueError 而 500 连坐全前端初始化）。"""
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, n))


def _web_session_clean(d):
    """网页导航栈会话清洗（a565，同 _web_favs_clean 口径）：
    {stack: [http(s) url ≤2048 ×≤50], idx: 钳到栈内}；非法输入回空栈。"""
    out = {"stack": [], "idx": -1}
    if not isinstance(d, dict):
        return out
    stack = [str(u) for u in (d.get("stack") or [])
             if isinstance(u, str) and u.startswith(("http://", "https://"))
             and len(u) <= 2048 and u != "about:blank"][:50]
    out["stack"] = stack
    if stack:
        try:
            idx = int(d.get("idx") or 0)
        except (TypeError, ValueError, OverflowError):   # a565 审计：Infinity→OverflowError 500
            idx = 0
        out["idx"] = max(0, min(idx, len(stack) - 1))
    return out


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


def _cdp_alive():
    """a473/审计修：本进程 CDP 端口是否在听（设置卡活态显示用，0.5s 探活）。"""
    try:
        import urllib.request as _u
        with _u.urlopen("http://127.0.0.1:9222/json/version", timeout=0.5) as r:
            return r.status == 200
    except Exception:
        return False


def _is_remote_session():
    """a468：当前是否跑在远程桌面会话里（RDP/ICA/Citrix）。

    无 GPU 加速场景的一次性建议依据（前端据此提示开 nogpu_mode，不自动
    开——用户在外网真机也用同一份配置，自动开会在切回真机时残留降级）。
    SESSIONNAME：Console=本机控制台 / RDP-Tcp#N=远程桌面 / ICA-*=Citrix。
    任何异常按本机会话处理（宁可漏提示不误报）。"""
    try:
        sn = (os.environ.get("SESSIONNAME") or "").strip().upper()
        if sn.startswith("RDP") or sn.startswith("ICA"):
            return True
        # CLIENTNAME：RDP 会话里是客户端机器名，控制台会话无此变量
        if os.environ.get("CLIENTNAME") and sn != "CONSOLE":
            return True
    except Exception:
        pass
    return False


# a565 审计：theme 字段级并发丢更新防线——_save_config({_load_config()}) 的
# load 在锁外，Flask threaded 下两个并发 POST 以后提交者快照覆盖先提交者字段。
# 各字段读改写整段进锁（nav_keys 同款思路，兑现其注释宣称的保护范围）
_theme_fields_lock = threading.Lock()


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
                        "style": cfg.get("style", "default"),
                        "sidebar_w": int(cfg.get("sidebar_w") or 0),
                        "data_dir_prompted": bool(cfg.get("data_dir_prompted")),
                        "calc_history": _calc_hist_clean(cfg.get("calc_history", [])),
                        # R-命名统一：网页收藏服务端持久化——localStorage 按
                        # origin（含随机端口）隔离，跨启动必丢；走 config.json
                        "web_favs": _web_favs_clean(cfg.get("web_favs", [])),
                        # a563：TFTP 面板高度同款根因同款修——localStorage
                        # 跨启动（端口必变）必丢 = 面板恒回 CSS 50%
                        #（用户实锤"修了很多次未真正修复"的根源）。
                        # a565 审计：GET 侧 try（脏 config 不再连坐 500）
                        "tftp_pane_h": _safe_cfg_int(cfg.get("tftp_pane_h"), 0, 4000),
                        # a564：折叠态（只剩标题栏）跨启动记忆
                        "tftp_pane_collapsed": bool(cfg.get("tftp_pane_collapsed")),
                        # a565：网页导航栈会话（a475 会话恢复）同款根因同款修
                        # ——localStorage 跨启动（端口必变）必丢，恢复从未生效
                        "web_session": _web_session_clean(cfg.get("web_session")),
                        "close_to_tray": bool(cfg.get("close_to_tray", True)),
                        "tray_prompt_shown": bool(cfg.get("tray_prompt_shown", False)),
                        "claude_ui_mode": cfg.get("claude_ui_mode", "harness"),
                        "custom_theme": cfg.get("custom_theme", {}),
                        "term_keys": {
                            "right_action": tk.get("right_action", "ctrl_menu"),
                            "auto_copy": bool(tk.get("auto_copy", False)),
                            "term_font_size": int(tk.get("term_font_size", 13)),
                            "ui_zoom": int(tk.get("ui_zoom", 100)),
                        },
                        "snip_hotkey": cfg.get("snip_hotkey", "ctrl+alt+a"),
                        # v3.5.310 可配置搜索快捷键（页面内 keydown，非系统热键）
                        "doc_search_hotkey": cfg.get("doc_search_hotkey", "ctrl+f"),
                        "notes_search_hotkey": cfg.get("notes_search_hotkey", "ctrl+alt+f"),
                        "perf_mode": bool(cfg.get("perf_mode", False)),
                        # a468：无 GPU 加速模式（虚机/远程桌面——动画降帧档）
                        "nogpu_mode": bool(cfg.get("nogpu_mode", False)),
                        # a468：远程会话检测（RDP/ICA）——前端据此一次性建议开启
                        "remote_session": _is_remote_session(),
                        # a473：L3 网页操作——CDP 端口常开（AI 经 devtools_* MCP
                        # 操作浏览器）；重启生效（WebView2 启动参数期决定）。
                        # web_cdp_live 由服务端探活（审计修：前端 fetch
                        # 127.0.0.1:9222 被 CORS 拒——/json/version 无 ACAO
                        # 头，跨源必败，live 态成了死码）
                        "web_cdp": bool(cfg.get("web_cdp", False)),
                        "web_cdp_live": _cdp_alive(),
                        "md_preview_theme": cfg.get("md_preview_theme", "auto"),
                        # a346: 代码跳转快捷键（nav.js 消费；形如 'f12'/'ctrl+t'）
                        # a336：加 back/fwd（导航历史后退/前进）
                        "nav_keys": cfg.get("nav_keys", {"def": "f12",
                                                         "ref": "shift+f12",
                                                         "sym": "ctrl+t", "fsym": "ctrl+shift+o",
                                                         "back": "alt+arrowleft",
                                                         "fwd": "alt+arrowright"}),
                        # a286: Tab 栏模式——flat=Chrome 平铺收缩 / drawer=分组抽屉
                        "tab_mode": cfg.get("tab_mode", "flat"),
                        # a357：CPU 优先提升（perf_boost）——level: normal/above_normal/high
                        "boost": {"level": (cfg.get("boost") or {}).get("level", "normal"),
                                  "power_plan": bool((cfg.get("boost") or {}).get("power_plan"))}})
    data = request.get_json(force=True) or {}
    if "perf_mode" in data:
        _save_config({**_load_config(), "perf_mode": bool(data["perf_mode"])})
    # a468：无 GPU 加速模式——与 perf_mode（全禁大锤）分档共存
    if "nogpu_mode" in data:
        _save_config({**_load_config(), "nogpu_mode": bool(data["nogpu_mode"])})
    # a473：L3 网页操作——CDP 端口开关（重启生效；main.py 启动期读配置）
    if "web_cdp" in data:
        _save_config({**_load_config(), "web_cdp": bool(data["web_cdp"])})
    if "tab_mode" in data:
        # 白名单：只认 flat/drawer，防脏配置
        if str(data["tab_mode"]).strip() in ("flat", "drawer"):
            _save_config({**_load_config(), "tab_mode": str(data["tab_mode"]).strip()})
    if "md_preview_theme" in data:
        v = str(data["md_preview_theme"]).strip()
        if v in ("auto", "dark", "light", "paper", "github", "dracula",
                 "solarized", "nord", "sepia", "mint"):
            _save_config({**_load_config(), "md_preview_theme": v})
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
        with _theme_fields_lock:
            _save_config({**_load_config(), "calc_history": _calc_hist_clean(data["calc_history"])})
    if "web_favs" in data and isinstance(data["web_favs"], list):
        # 网页收藏持久化：清洗口径同上（url 白名单 + 100 条上限，防 config 膨胀）
        with _theme_fields_lock:
            _save_config({**_load_config(), "web_favs": _web_favs_clean(data["web_favs"])})
    if "tftp_pane_h" in data:
        # a563：TFTP 面板高度持久化（int + 60..4000 钳制，防 config 膨胀）
        try:
            _h = int(data["tftp_pane_h"])
        except (TypeError, ValueError):
            _h = 0
        with _theme_fields_lock:
            _save_config({**_load_config(),
                          "tftp_pane_h": max(0, min(4000, _h))})
    if "tftp_pane_collapsed" in data:
        # a564：折叠态持久化（bool 白名单）
        with _theme_fields_lock:
            _save_config({**_load_config(),
                          "tftp_pane_collapsed": bool(data["tftp_pane_collapsed"])})
    if "web_session" in data:
        # a565：网页导航栈会话持久化（dict 白名单清洗，防 config 膨胀）
        with _theme_fields_lock:
            _save_config({**_load_config(),
                          "web_session": _web_session_clean(data["web_session"])})
    # 关闭到托盘（close_to_tray：设置页开关）+ 首次提示已展示标记（tray_prompt_shown）
    _tk = {}
    if "close_to_tray" in data:
        _tk["close_to_tray"] = bool(data["close_to_tray"])
    if "tray_prompt_shown" in data:
        _tk["tray_prompt_shown"] = bool(data["tray_prompt_shown"])
    if "claude_ui_mode" in data:
        # 顶栏 Claude 按钮分派：harness=界面化聊天 tab / cli=内嵌终端（默认 harness）
        m = str(data["claude_ui_mode"]).strip()
        if m in ("harness", "cli"):
            _tk["claude_ui_mode"] = m
        else:
            return jsonify({"ok": False, "err": "claude_ui_mode 只认 harness/cli"}), 400
    if _tk:
        _save_config({**_load_config(), **_tk})
    # 截图全局热键（v2.3.12 设置页配置项）：值形如 'f1'/'ctrl+alt+a'/''（禁用）。
    # 先热替换注册（同步探测占用给前端即时反馈），成功才落 config。
    if "snip_hotkey" in data:
        import src.snip as _snip
        val = str(data["snip_hotkey"] or "").strip().lower()
        ok, err = _snip.set_hotkey(val)
        if not ok:
            return jsonify({"ok": False, "err": err}), 400
        _save_config({**_load_config(), "snip_hotkey": val})
    # v3.5.310 可配置搜索快捷键：仅落 config（页面内 keydown 消费，前端
    # 热更新 window._HK），无系统级注册。白名单校验（复审 F4）：空串=禁用，
    # 否则 1-4 段小写字母数字以 + 相连——防直连 POST 塞 "win+f" 类脏值
    # （hkMatch 忽略未知修饰键，脏值会退化成裸键触发）
    _HK_RE = re.compile(r"^(|[a-z0-9]+(\+[a-z0-9]+){0,3})$")
    _hk_updates = {}
    for _hk_field in ("doc_search_hotkey", "notes_search_hotkey"):
        if _hk_field in data:
            _v = str(data[_hk_field] or "").strip().lower()
            if not _HK_RE.match(_v):
                return jsonify({"ok": False, "err": _hk_field + " 格式非法（形如 ctrl+f）"}), 400
            _hk_updates[_hk_field] = _v
    if _hk_updates:
        _save_config({**_load_config(), **_hk_updates})
    # a346：代码跳转快捷键（def=转定义 ref=查引用 sym=工作区符号
    # a336：back/fwd=导航历史后退/前进）——与搜索热键同法：仅落 config
    # （nav.js 页面内 keydown 消费+热应用）。
    # R21-3：主键白名单收紧（单字母/数字/f1-f12——录制框旧正则只锚首字符
    # 时 enter 等被落库，改键后该键无法输入）。
    # a336：方向键也合法（VSCode 的导航历史就是 Alt+←/→ 一类），但必须带
    # 修饰——裸方向键是编辑器/终端基础操作，落库会让整机输入瘫痪。
    # R21-6：写入加锁防并发丢更新
    if "nav_keys" in data and isinstance(data["nav_keys"], dict):
        import re as _re2
        nk = data["nav_keys"]
        _NK_KINDS = ("def", "ref", "sym", "fsym", "back", "fwd")   # S37-5：fsym 改键此前永不落盘
        _nk_out = {}
        for _nk_k in _NK_KINDS:
            _v = str(nk.get(_nk_k) or "").strip().lower()
            # a375R（审计 P3-2）：缺项要单独说「不能为空」，否则会落到主键
            # 校验处报「只支持字母/数字/F1-F12」，把调用方引向错误方向
            if not _v:
                return jsonify({"ok": False,
                                "err": "nav_keys.%s 不能为空" % _nk_k}), 400
            if not _HK_RE.match(_v):
                return jsonify({"ok": False,
                                "err": "nav_keys.%s 格式非法（形如 ctrl+t）" % _nk_k}), 400
            _segs = _v.split("+")
            _main = _segs[-1]
            if _re2.fullmatch(r"arrow(left|right|up|down)", _main):
                # a375R（审计 P2-7）：方向键只允许配给导航历史两项——配给
                # def/ref/sym 等于把「按词移动光标」抢成跳转（P1-1 同型）。
                if _nk_k not in ("back", "fwd"):
                    return jsonify({"ok": False,
                                    "err": "nav_keys.%s 方向键只可用于后退/前进"
                                           % _nk_k}), 400
                if len(_segs) < 2:
                    return jsonify({"ok": False,
                                    "err": "nav_keys.%s 方向键需搭配 Ctrl/Alt/Shift"
                                           % _nk_k}), 400
            elif not _re2.fullmatch(r"f([1-9]|1[0-2])|[a-z0-9]", _main):
                return jsonify({"ok": False,
                                "err": "nav_keys.%s 主键只支持 字母/数字/F1-F12/方向键"
                                       % _nk_k}), 400
            _nk_out[_nk_k] = _v
        if len(set(_nk_out.values())) != len(_NK_KINDS) or "" in _nk_out.values():
            return jsonify({"ok": False, "err": "跳转快捷键不能为空且互不冲突"}), 400
        with _nav_keys_lock:
            _save_config({**_load_config(), "nav_keys": _nk_out})
    # a357：CPU 优先提升——白名单档位 + 即时应用（含电源计划还原语义）
    if "boost" in data and isinstance(data["boost"], dict):
        from src import perf_boost as _pb
        lv = str(data["boost"].get("level") or "normal")
        if lv not in ("normal", "above_normal", "high"):
            return jsonify({"ok": False, "err": "boost.level 只认 normal/above_normal/high"}), 400
        pp = bool(data["boost"].get("power_plan"))
        _pb.apply(lv, pp)
        # R24-4（R21-6 同型：load→save 无锁丢更新）——并入 nav_keys 写锁
        #（同保护 /api/theme 的字段级并发写）
        with _nav_keys_lock:
            _save_config({**_load_config(), "boost": {"level": lv, "power_plan": pp}})
    if "custom_theme" in data and isinstance(data["custom_theme"], dict):
        # v2.25 自定义主题调色：键白名单 + 值格式校验（#rgb/#rrgggb、light 布尔），
        # 防 config 被塞脏数据（与 term_keys 白名单同思路）
        _CT_KEYS = {"bg-deep", "bg", "bg-panel", "bg-card", "bg-input", "border",
                    "fg", "fg-bright", "muted", "accent", "accent-2",
                    "term-bg", "term-fg"}
        ct = {}
        for k, v in data["custom_theme"].items():
            if k == "light":
                ct["light"] = bool(v)
            elif k in _CT_KEYS and isinstance(v, str) and \
                    re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", v or ""):
                ct[k] = v.lower()
        _save_config({**_load_config(), "custom_theme": ct})
    theme = (data.get("theme") or "").strip()
    if theme:
        _save_config({**_load_config(), "theme": theme})
    # 风格维度（v4.1 桥接层 skins.css/skin.js）：与 theme 正交，字符集
    # 白名单防脏配置（合法 id 由前端 STYLES 表约束，后端不枚举——后续
    # 批次追加风格不用改这里）
    style = (data.get("style") or "").strip()
    if style and re.fullmatch(r"[a-z0-9-]{1,24}", style):
        _save_config({**_load_config(), "style": style})
    # a219：侧栏宽度记忆（180~1920 钳制防脏值）
    if "sidebar_w" in data:
        try:
            _w = int(data["sidebar_w"])
            if 180 <= _w <= 1920:
                _save_config({**_load_config(), "sidebar_w": _w})
        except (TypeError, ValueError):
            pass
    return jsonify({"ok": True, "theme": theme or _load_config().get("theme", "deepblue")})


# ============================================================
# 最近打开（SSH/串口/文件 快捷重开列表）
# ============================================================
# 存 config.json "recent" 键：[{type, key, label, ts, data{...}}...]，新→旧。
# key = 去重键（ssh:host:port:user / serial:COM3 / file:路径 / claude:session_id）；同 key 只留最新一条并置顶。
_RECENT_MAX = 20  # 列表上限，防无限膨胀
def _recent_add(item):
    """记录一条最近打开（去重置顶），返回更新后的列表。
    a430（用户令）：固定项（pin）无条件保存——重开同 key 保持固定；
    _RECENT_MAX 上限只裁未固定项，固定项永不淘汰。"""
    cfg = _load_config()
    recent = cfg.get("recent", [])
    key = item.get("key") or ""
    old = next((r for r in recent if r.get("key") == key), None)
    if old and old.get("pin"):
        item["pin"] = True          # 固定项重开：保持固定
    recent = [r for r in recent if r.get("key") != key]
    item["ts"] = int(time.time() * 1000)
    recent.insert(0, item)
    unpinned = [r for r in recent if not r.get("pin")]
    if len(unpinned) > _RECENT_MAX:
        _drop = {id(r) for r in unpinned[_RECENT_MAX:]}
        recent = [r for r in recent if id(r) not in _drop]
    cfg["recent"] = recent
    _save_config(cfg)
    return recent

@app.route("/api/hash_file", methods=["POST"])
def api_hash_file():
    """文件哈希（程序员计算器的文件哈希面板）。
    body: {path} —— 一次流式读，同时算 MD5/SHA1/SHA256/SHA512/CRC32。
    大文件分块（8MB/块）不占内存。路径规则与 hex_files 同款：绝对路径 + 已存在。"""
    data = request.get_json(force=True, silent=True) or {}
    from src.app_state import reject_win_devpath
    if reject_win_devpath(data.get("path")):   # a239：CON 等设备名 open/getsize 永久阻塞
        return jsonify({"ok": False, "err": "路径包含 Windows 保留设备名"}), 400
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
    # a430：固定/取消固定（按 key 定位，翻转 pin 并即时落盘——无条件保存）
    if data.get("pin_toggle"):
        _key = str(data["pin_toggle"]).strip()
        cfg = _load_config()
        recent = cfg.get("recent", [])
        tgt = next((r for r in recent if r.get("key") == _key), None)
        if not tgt:
            return jsonify({"ok": False, "err": "条目不存在"}), 404
        if tgt.get("pin"):
            tgt.pop("pin", None)
        else:
            tgt["pin"] = True
            recent.remove(tgt)
            recent.insert(0, tgt)   # 新固定的排置顶区最前
        _save_config({**cfg, "recent": recent})
        return jsonify({"ok": True, "recent": recent})
    # 整表替换（前端单条删除后回写剩余列表）
    if isinstance(data.get("replace"), list):
        keep = []
        for it in data["replace"]:
            t = (it.get("type") or "").strip()
            if t not in ("ssh", "serial", "file", "claude", "telnet", "shell") or not (it.get("key") or "").strip():
                continue
            _e = {"type": t, "key": it["key"], "label": (it.get("label") or "").strip(),
                  "ts": it.get("ts") or 0, "data": it.get("data") or {}}
            if it.get("pin"):        # a430：回写保固定标记
                _e["pin"] = True
            keep.append(_e)
        keep.sort(key=lambda x: -x.get("ts", 0))  # 按 ts 新→旧
        # a430：固定项无条件保存——上限只裁未固定，固定项恒排置顶区
        #（原 [:_RECENT_MAX] 会把旧 ts 的固定项整条裁掉，实测 ⑥ 实锤）
        _pinned = [x for x in keep if x.get("pin")]
        _unpinned = [x for x in keep if not x.get("pin")][:_RECENT_MAX]
        keep = _pinned + _unpinned
        _save_config({**_load_config(), "recent": keep})
        return jsonify({"ok": True, "recent": keep})
    t = (data.get("type") or "").strip()
    # a581：补 shell（本地终端）与 telnet——设计核实实测两者原来都被 400 拒，
    # 即「最近打开」对它们从未生效（telnet 是既有缺陷，顺带修）。
    if t not in ("ssh", "serial", "file", "claude", "telnet", "shell"):
        return jsonify({"ok": False,
                        "err": "type 须为 ssh/serial/file/claude/telnet/shell"}), 400
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
        d = data.get("dir")
        target = (str(d).strip() if isinstance(d, str) and d.strip() else LOG_DIR)
        # a238 P2：去掉 makedirs——「打开目录」不该有创建目录的写副作用
        # （原实现可在任意路径凭空建目录树）；目录不存在就 404
        if not os.path.isdir(target):
            return jsonify({"ok": False, "err": "目录不存在"}), 404
        # os.startfile 在 pywebview Flask 线程里可能静默失败，改用 explorer.exe 更可靠
        import subprocess
        subprocess.Popen(["explorer.exe", target], close_fds=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400


@app.route("/api/open_url", methods=["POST"])
def api_open_url():
    """系统默认浏览器打开外部链接（v2.27.22）。WebView 内点链接若就地导航，
    整个工具被错误页替换（用户实锤：markdown linkify 把裸词 proxy.py 补成
    http://proxy.py，点击后 ERR_NAME_NOT_RESOLVED 占满窗口、无返回入口）。
    前端拦截一切 <a> 点击走这里，WebView 永不离开应用页面。只放行 http(s)。"""
    data = request.get_json(force=True, silent=True) or {}
    url = str(data.get("url") or "").strip()   # a238 P3：非字符串（数字/数组）原会 .strip() 崩 500
    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify({"ok": False, "err": "仅支持 http(s) 链接"}), 400
    try:
        import webbrowser
        webbrowser.open(url)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 400


# ---- a507：Web 代理拆分至 src/web_proxy.py（解耦：server.py 不再承载
# 网页 tab 逻辑；蓝图路由路径不变，404 兜底需 app 级注册故走 register）----
from src.web_proxy import register as _web_proxy_register
_web_proxy_register(app)
# a544：网页 tab 的 WebView2 控件命令通道（终局形态：真浏览器控件，
# 非 iframe）。装配在 main._patched_ready（需 UI 线程的 Form）。
from src import web_tabs as _wt
_wt.register(app)


# ---- 升级功能（v2.1.0）：客户端检查/应用 + 发布端分发服务控制 ----
@app.route("/api/update/state")
def api_update_state():
    """当前版本 + 升级服务器地址（设置页显示与预填）。
    frozen=True = 打包版（同事机）——前端据此隐藏「升级分发服务」区块
    （发布机专用，用户定调：发布版不能有这部分 UI）。"""
    from src.updater import _cfg_url
    from src.version import APP_VERSION
    return jsonify({"ok": True, "current": APP_VERSION,
                    "url": _cfg_url() or "",
                    "frozen": bool(getattr(sys, "frozen", False))})


@app.route("/api/update/url", methods=["POST"])
def api_update_url():
    data = request.get_json(force=True, silent=True) or {}
    u = str(data.get("url") or "").strip()   # a238 P3：同 open_url 的非字符串防崩
    if u and not u.startswith("http://") and not u.startswith("https://"):
        return jsonify({"ok": False, "err": "地址需以 http(s):// 开头"}), 400
    from src.updater import _cfg_url
    return jsonify({"ok": True, "url": _cfg_url(u)})


@app.route("/api/update/check", methods=["POST"])
def api_update_check():
    from src.updater import check_update
    return jsonify(check_update())


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    """下载+校验+写替换脚本（耗时几秒到几十秒——内网直连，同步等待可接受；
    进度条是后话，先把闭环跑通）。"""
    from src.updater import apply_update
    ok, err = apply_update()
    return jsonify({"ok": ok, "err": err})


@app.route("/api/update/run", methods=["POST"])
def api_update_run():
    from src.updater import run_update
    ok, err = run_update()
    return jsonify({"ok": ok, "err": err})


@app.route("/api/update_server/status")
def api_update_server_status():
    from src import update_server
    return jsonify({"ok": True, **update_server.status()})


@app.route("/api/update_server/password", methods=["POST"])
def api_update_server_password():
    """门户登录密码（发布者用；空=恢复默认 888888）。"""
    data = request.get_json(force=True, silent=True) or {}
    pwd = str(data.get("password") or "").strip()
    if len(pwd) > 32:
        return jsonify({"ok": False, "err": "密码过长（≤32 字符）"}), 400
    from src.update_server import _set_portal_password
    _set_portal_password(pwd)
    return jsonify({"ok": True})


@app.route("/api/update_server/toggle", methods=["POST"])
def api_update_server_toggle():
    """开/关发布端分发服务（发布机自己用；开关持久化 config）。
    v2.2.1 热同步（用户定调）：每次开关都停旧实例并强制 reload
    version/updater/update_server 模块链——发布者改了门户/升级器代码后
    无需重启工具，关-开一次即生效。导入/重载全程包 try：新代码有语法错
    时把异常亮给前端（而不是 500），改好再开。"""
    from src.app_state import _load_config, _save_config
    data = request.get_json(force=True, silent=True) or {}
    enable = bool(data.get("enabled"))
    import importlib, sys
    try:
        us_old = sys.modules.get("src.update_server")
        if us_old is not None:
            us_old.stop()               # 先停旧实例（同步收尾，端口干净）
            us_old._server = None       # 半途炸时兜底：状态至少是「已停」
        # 依赖方先重载（version → updater → update_server）；未导入过的
        # 首次导入也走同一路径（坏代码在 import 阶段就能报出来）
        for mod in ("src.pkgname", "src.version", "src.updater",
                    "src.update_server"):
            m = sys.modules.get(mod)
            if m is not None:
                importlib.reload(m)
            else:
                importlib.import_module(mod)
    except Exception as e:
        return jsonify({"ok": False,
                        "err": "热加载失败（新代码有语法错误？修复后再开）：%s" % e})
    from src import update_server as us2   # reload 就地刷新，重取引用
    if enable:
        ok, msg = us2.start()
        if not ok:
            return jsonify({"ok": False, "err": msg})
    cfg = _load_config()
    cfg["update_server_enabled"] = enable
    _save_config(cfg)
    return jsonify({"ok": True, **us2.status()})


# ---- 数据目录管理（顶栏机器人图标点开的设置面板）----
# 数据目录收纳：logs/（串口日志，唯一日志目录）、files/（笔记）、根级 *.json
# （cmdlib.json/retry_config.json 等关键配置——v2.27.1 起自动全量纳入：凡是
# 落在数据目录根的 .json 都是关键配置，迁移时严格校验，新增文件不用改这里）、
# webview_cache/（WebView2 缓存——也迁：新位置缓存连续，不产生旧位置孤儿残留；
# 被运行中 WebView2 锁定的文件跳过，纯缓存丢了自动重建）。
# 迁移铁律（用户强调）：迁移前后数据必须都能找到——采用「先复制后切换」而非「先删后搬」：
# 复制全部内容 → 校验大小一致 → 写 config 切换 → 旧目录完整保留不删（用户自查后手动删）。
_DATA_SUBDIRS = ["logs", "files", "webview_cache",
                # v3.5.320（用户需求）：技能数据随数据空间迁移/统计
                "skill_zh", "skill_cache", "skill_exports"]

def _data_root_json_files():
    """数据目录根级 *.json 清单（关键配置，迁移时严格校验逐个比对大小）。"""
    try:
        return [fn for fn in os.listdir(DATA_DIR)
                if fn.lower().endswith(".json")
                and os.path.isfile(os.path.join(DATA_DIR, fn))]
    except Exception:
        return []

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
    # 根级其他关键配置（retry_config.json 等）一并统计（cmdlib 已列不重复）
    for fn in _data_root_json_files():
        if fn == "cmdlib.json":
            continue
        try:
            sz = os.path.getsize(os.path.join(DATA_DIR, fn))
        except OSError:
            continue
        subs[fn] = {"exists": True, "count": 1, "size": sz}
        total += sz
    return jsonify({"ok": True, "dir": DATA_DIR,
                    "default": _st._default_data_dir(),
                    "subdirs": subs, "total_size": total,
                    "home_anchor": HOME_DIR})

@app.route("/api/data_dir/clean", methods=["POST"])
def api_data_dir_clean():
    """手动清理（v3.5.93 设置→数据目录→存储占用）。body: {target, mode}。
    target ∈ uploads|logs|idx|cache|ask；mode ∈ policy|all。目标只含衍生
    数据（附件/日志/索引/缓存/提问状态），笔记/命令库/配置不可触达。
    v3.5.95（轻审R2-5）：非对象 body 显式 400；非法 target/mode 返回
    ok:false——不再「假成功 0 项」。"""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "err": "参数必须是 JSON 对象"}), 400
    target = str(data.get("target") or "").strip()
    mode = str(data.get("mode") or "").strip()
    from src.data_hygiene import _CLEANABLE, manual_clean
    if target not in _CLEANABLE or mode not in ("policy", "all"):
        return jsonify({"ok": False, "err": "非法 target/mode"}), 400
    removed, freed = manual_clean(target, mode)
    return jsonify({"ok": True, "removed": removed, "freed": freed})


@app.route("/api/data_dir/usage")
def api_data_dir_usage():
    """存储感知（v3.5.92 设置→数据目录）：用户数据空间（可迁移 DATA_DIR）/
    工具数据空间（固定 HOME_DIR）/ 附件目录占用与清理策略。目录大的话
    首扫可能秒级，前端按需拉（进设置页才调）。"""
    try:
        from src.data_hygiene import usage_stats
        return jsonify({"ok": True, **usage_stats()})
    except Exception as e:
        return jsonify({"ok": False, "err": str(e)}), 500


# ---- 数据目录迁移/校验的公共防线（a238 第5轮A1：P0-1/P1-1/P1-5）----
# 迁移家族曾用「字符串前缀比对」判嵌套——abspath 不解析 reparse point，
# 目标是当前数据目录的 junction 别名时判定被穿透：复制阶段 dst 解析回源
# 自身、校验恒过，切换后 rmtree 把唯一数据本体删光（全量灭失）。另外
# UNC 目标一次 POST 即把全部凭据/笔记外传 SMB 再删本地原件
_migrate_lock = threading.Lock()   # a238 P1-2：迁移互斥（并发二次迁移删新副本）


def _migrate_target_err(target):
    """迁移目标预检。返回 None=通过，否则错误文案。"""
    if not isinstance(target, str) or not target.strip():
        return "路径无效"
    target = target.strip()
    # UNC / 设备命名空间（\\\\、\\?\\、\\.\\）一律拒：网络路径的删除不经
    # 回收站、凭据会被整体外传（对齐 fileops 家族「UNC 拒」）
    if target.startswith("\\\\") or target.startswith("//"):
        return "不支持网络路径（UNC）作为数据目录"
    drive = os.path.splitdrive(target)[0]
    if drive.startswith("\\\\"):
        return "不支持网络路径（UNC）作为数据目录"
    return None


def _paths_nested(a, b):
    """嵌套判定（realpath 双侧解析）：a/b 任一互为祖先即 True。"""
    try:
        ra, rb = os.path.realpath(a).lower(), os.path.realpath(b).lower()
    except Exception:
        ra, rb = os.path.abspath(a).lower(), os.path.abspath(b).lower()
    return ra.startswith(rb + os.sep) or rb.startswith(ra + os.sep)


@app.route("/api/data_dir/check", methods=["POST"])
def api_data_dir_check():
    """校验候选目录：可创建、可写、不在 C 盘给出提醒但允许（用户自己选的）。
    返回迁移预览：会迁哪些子目录、各多少条目。"""
    data = request.get_json(force=True, silent=True) or {}
    target = (data.get("dir") or "").strip()
    err = _migrate_target_err(target)
    if err:
        return jsonify({"ok": False, "err": err}), 400
    if len(target) < 3 or ":" not in target:
        return jsonify({"ok": False, "err": "路径无效（需绝对路径，如 D:\\前端控制台）"}), 400
    # \\?\C:\... 设备前缀绕 C 盘提醒——剥掉前缀按真实盘符判
    _naked = target[4:] if target.startswith("\\\\?\\") else target
    target = os.path.abspath(target)
    if os.path.realpath(DATA_DIR).lower() == os.path.realpath(target).lower():
        return jsonify({"ok": False, "err": "这就是当前数据目录"}), 400
    # 嵌套判定（a238：realpath 双侧——junction 别名穿透字符串比对是 P0 灭失链第一环）
    if _paths_nested(DATA_DIR, target):
        return jsonify({"ok": False, "err": "目标目录不能与当前数据目录互相嵌套（会导致删除旧目录时连带删除新数据）"}), 400
    # 目标已是 reparse 别名（junction/symlink）：复制会解析回源自身、校验恒过
    try:
        # a245 P2（a238复审）：normcase 双侧——realpath 返回盘上真实大小写，
        # normpath 保留用户输入大小写，直比会把 D:\Data 误判成链接（同 tftp 修法）
        if os.path.exists(target) and \
                os.path.normcase(os.path.realpath(target)) != os.path.normcase(os.path.normpath(target)):
            return jsonify({"ok": False, "err": "目标路径是链接/联接（junction），请填真实目录"}), 400
    except Exception:
        pass
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "err": f"无法创建目录: {e}"}), 400
    if not os.access(target, os.W_OK):
        return jsonify({"ok": False, "err": "目录不可写"}), 400
    warnings = []
    if _naked.upper().startswith("C:"):
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
    for s in _data_root_json_files():
        preview.append({"name": s, "count": 1})
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
    err = _migrate_target_err(target)
    if err:
        return jsonify({"ok": False, "err": err}), 400
    # a238 P1-2：迁移互斥（Flask threaded=True 下 GB 级复制分钟级窗口内，
    # 第二个并发迁移会在中途读到已切换的全局 DATA_DIR，把 A 刚建好的新副本
    # 当旧目录 rmtree）。non-blocking：迁移中直接 409
    if not _migrate_lock.acquire(blocking=False):
        return jsonify({"ok": False, "err": "已有迁移在进行中，请等待完成"}), 409
    try:
        return _do_data_dir_migrate(target)
    finally:
        _migrate_lock.release()


def _mig_copy_atomic(sf, df):
    """a248（a245复审F1）：迁移拷贝 tmp+os.replace 原子化——copy2 直写目标，
    中途失败（磁盘满/杀软锁）留半截文件：首轮好副本被毁 + 下次重试
    exists(df) 跳拷 + 大小校验恒败 = 该目标目录永久迁移死锁。"""
    import shutil
    tmp = "%s.migtmp.%d.%d" % (df, os.getpid(), time.time_ns() % 10**9)
    try:
        shutil.copy2(sf, tmp)
        os.replace(tmp, df)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _do_data_dir_migrate(target):
    """迁移本体（调用方已持 _migrate_lock）。"""
    global DATA_DIR, STATE_DIR, CMD_LIB_FILE, LOG_DIR
    import shutil
    # a238 P1-2：源/旧目录在入口快照一次——中途全局被切（防御纵深）不再影响本次
    src_data_dir = os.path.abspath(DATA_DIR)
    old_data_dir = src_data_dir
    if os.path.realpath(target).lower() == os.path.realpath(src_data_dir).lower():
        return jsonify({"ok": False, "err": "目标与当前目录相同"}), 400
    target = os.path.abspath(target)
    # a238 P0-1：嵌套判定 realpath 双侧（junction 别名穿透字符串比对 → rmtree 灭失）
    if _paths_nested(src_data_dir, target):
        return jsonify({"ok": False, "err": "目标目录不能与当前数据目录互相嵌套（会导致删除旧目录时连带删除新数据）"}), 400
    # 目标已是 reparse 别名：复制会解析回源自身、校验恒过（a238 P0-1 第二环）
    try:
        # a245 P2（a238复审）：normcase 双侧比对，防大小写假阳性误拒真实目录
        if os.path.exists(target) and \
                os.path.normcase(os.path.realpath(target)) != os.path.normcase(os.path.normpath(target)):
            return jsonify({"ok": False, "err": "目标路径是链接/联接（junction），请填真实目录"}), 400
    except Exception:
        pass
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "err": f"无法创建目录: {e}"}), 400
    if not os.access(target, os.W_OK):
        return jsonify({"ok": False, "err": "目标目录不可写"}), 400
    copied = []
    # a245 P1（a238 复审残留）：迁移窗口起点——复制期间源目录的新写入靠它判定
    t0 = time.time()
    # a250（a247/a248复审F-3）：pass1 判定为"目标预放"的文件集 + 冲突另存失败数
    conflicted = set()
    conflict_errs = 0
    try:
        for s in _DATA_SUBDIRS:
            src = os.path.join(src_data_dir, s)
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
            conflicts = 0   # a248 F2：目标预放旧版被源当前版保真另存的条数
            # a238 P1-5：walk 剪 reparse point（junction 环挂死/外部树整拷——
            # data_hygiene._files_in 同款剪枝）
            _src_real = os.path.realpath(src)
            for root, dirs, files in os.walk(src, onerror=lambda e: None):
                dirs[:] = [d for d in dirs
                           if os.path.realpath(os.path.join(root, d))
                           .startswith(_src_real + os.sep)]
                rel = os.path.relpath(root, src)
                droot = dst if rel == "." else os.path.join(dst, rel)
                os.makedirs(droot, exist_ok=True)
                for fn in files:
                    sf, df = os.path.join(root, fn), os.path.join(droot, fn)
                    try:
                        if not os.path.exists(df):   # 不覆盖目标已有文件（目标可能已有数据）
                            _mig_copy_atomic(sf, df)
                        # 校验：大小一致（copy2 保元数据，大小校验足够可靠且快）
                        if os.path.getsize(sf) != os.path.getsize(df):
                            if strict:
                                raise RuntimeError(f"校验失败: {df} 与源大小不一致")
                            # a248（a245复审F2）：目标预放同名旧文件且与源不一致——
                            # 原先静默 skipped，rmtree 后源的当前版被删、目标旧版
                            # 胜出=数据倒退。改为冲突保真：源当前版另存
                            # .migrate-conflict，两边都不丢。
                            # a252（复审F5）：另存失败必须中止——计数后照删旧目录
                            # =该文件当前版全盘无副本（保真承诺在失败路径失效）
                            try:
                                _mig_copy_atomic(sf, df + ".migrate-conflict")
                            except (PermissionError, OSError) as ce:
                                raise RuntimeError(
                                    f"冲突保真另存失败（未切换未删除，数据仍在原处）: {df} {ce}")
                            skipped += 1
                            conflicts += 1
                            conflicted.add(os.path.relpath(sf, src_data_dir))
                            continue
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
            copied.append({"name": s, "files": n,
                           **({"skipped": skipped} if skipped else {}),
                           **({"conflicts": conflicts} if conflicts else {})})
        # 根级关键配置（cmdlib.json/retry_config.json 及一切 *.json）：
        # 严格校验逐个迁——大小不一致直接判迁移失败，不切换
        for s in _data_root_json_files():
            sf = os.path.join(src_data_dir, s)
            if not os.path.isfile(sf):
                continue
            df = os.path.join(target, s)
            if not os.path.exists(df):
                _mig_copy_atomic(sf, df)
            if os.path.getsize(sf) != os.path.getsize(df):
                raise RuntimeError(f"校验失败: {df} 与源大小不一致")
            copied.append({"name": s, "files": 1})
    except Exception as e:
        return jsonify({"ok": False, "err": f"迁移失败（未切换，数据仍在原处）: {e}",
                        "copied": copied}), 500
    # a244 P1（a238 复审残留）：复制与 rmtree 之间存在分钟级窗口（GB 级数据），
    # 窗口内新写入源目录的文件（保存笔记/追加日志/改 cmdlib）——首轮 walk 已走过
    # 的位置不会重拷，rmtree 却照删 = 新写入被静默删除。rmtree 前二次增量补拷：
    # ctime/mtime 任一 >= t0 的文件覆盖重拷（copy2 保 mtime，首轮已拷的旧文件
    # 不会误判）。固定点收敛最多 3 轮（持续追加的活跃日志容忍尾差）；files/ 与
    # 根级 json 仍严格校验；webview_cache 跳过（缓存可再生，删了不算丢数据）。
    late_total = 0
    try:
        for _catch_round in range(3):
            late = 0
            for s in _DATA_SUBDIRS:
                if s == "webview_cache":
                    continue
                src = os.path.join(src_data_dir, s)
                if not os.path.isdir(src):
                    continue
                dst = os.path.join(target, s)
                strict = (s == "files")
                _src_real = os.path.realpath(src)
                for root, dirs, files in os.walk(src, onerror=lambda e: None):
                    dirs[:] = [d for d in dirs
                               if os.path.realpath(os.path.join(root, d))
                               .startswith(_src_real + os.sep)]
                    rel = os.path.relpath(root, src)
                    droot = dst if rel == "." else os.path.join(dst, rel)
                    os.makedirs(droot, exist_ok=True)
                    for fn in files:
                        sf, df = os.path.join(root, fn), os.path.join(droot, fn)
                        try:
                            st = os.stat(sf)
                        except OSError:
                            continue   # 窗口内又被删：源里已无，随 rmtree 走
                        if max(st.st_ctime, st.st_mtime) < t0:
                            continue   # 窗口前已有：首轮已处理
                        try:
                            # 已补拷到最新（copy2 保 mtime）：本轮无变化，跳过——
                            # 否则窗口内文件 mtime 恒>=t0，固定点永不收敛
                            if os.path.exists(df) and os.path.getsize(df) == st.st_size \
                                    and os.path.getmtime(df) == st.st_mtime:
                                continue
                        except OSError:
                            pass
                        try:
                            # a250（F-3闭环）：df 若是 pass1 判定的目标预放版且窗口内
                            # 源又有新写入——直接覆盖=预放版无副本被毁（与冲突保真
                            # 自相矛盾）。先保真预放版再覆盖
                            if os.path.relpath(sf, src_data_dir) in conflicted and os.path.exists(df):
                                # a252（复审F5）：首轮已保真的 -pre 不再覆盖——
                                # 活跃文件第 2 轮再进此分支时把原件顶掉=保真失效
                                _pre = df + ".migrate-conflict-pre"
                                if not os.path.exists(_pre):
                                    try:
                                        _mig_copy_atomic(df, _pre)
                                    except (PermissionError, OSError):
                                        conflict_errs += 1
                            _mig_copy_atomic(sf, df)   # 窗口内新写入：源是最新意图，原子覆盖
                            late += 1
                            if os.path.getsize(sf) != os.path.getsize(df):
                                raise RuntimeError(f"校验失败: {df} 与源大小不一致")
                        except RuntimeError:
                            if strict:
                                raise
                        except (PermissionError, OSError):
                            if strict:
                                raise
            for s in _data_root_json_files():
                sf = os.path.join(src_data_dir, s)
                if not os.path.isfile(sf):
                    continue
                try:
                    st = os.stat(sf)
                except OSError:
                    continue
                if max(st.st_ctime, st.st_mtime) < t0:
                    continue
                df = os.path.join(target, s)
                try:
                    if os.path.exists(df) and os.path.getsize(df) == st.st_size \
                            and os.path.getmtime(df) == st.st_mtime:
                        continue
                except OSError:
                    pass
                _mig_copy_atomic(sf, df)
                late += 1
                if os.path.getsize(sf) != os.path.getsize(df):
                    raise RuntimeError(f"校验失败: {df} 与源大小不一致")
            late_total += late
            if not late:
                break
    except Exception as e:
        return jsonify({"ok": False, "err": f"迁移失败（未切换，数据仍在原处）: 增量补拷 {e}",
                        "copied": copied}), 500
    # rmtree 前终检（a238 P0-1 第三环防御纵深）：旧/新目录 realpath 必须互不
    # 相同、互不嵌套——任何一环被绕过都在这里挡住「删除唯一数据本体」
    if os.path.realpath(old_data_dir).lower() == os.path.realpath(target).lower() \
            or _paths_nested(old_data_dir, target):
        return jsonify({"ok": False, "err": "安全校验未通过（新旧目录解析后重合），已取消删除旧目录",
                        "dir": target, "copied": copied, "deleted": False,
                        "old_dir": old_data_dir}), 500
    # 复制校验全过 → 切换运行时 + 持久化
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
    # a238 P1-4：其余按值缓存 DATA_DIR 的模块一并 patch（skills_repo/proxy/
    # hiklink_bot/proxy_usage——此前迁移后写回复活的旧目录，数据精神分裂）
    try:
        import src.skills_repo as _sr
        _sr.DATA_DIR = target
        _sr._CACHE_DIR = os.path.join(target, "skill_cache")
        _sr._ZH_DIR = os.path.join(target, "skill_zh")
        _sr._EXPORT_DIR = os.path.join(target, "skill_exports")
    except Exception:
        pass
    try:
        import src.proxy as _px
        _px.DATA_DIR = target
        _px.LANZ_CRED_PATH = os.path.join(target, "lanz_credentials.json")
        _px.PROXY_STATE_PATH = os.path.join(target, "proxy_state.json")
    except Exception:
        pass
    try:
        import src.hiklink_bot as _hk
        _hk.DATA_DIR = target
        _hk.SESSION_PATH = os.path.join(target, "hiklink_session.json")
    except Exception:
        pass
    try:
        import src.proxy_usage as _pu
        _pu.DATA_DIR = target
        _pu.USAGE_PATH = os.path.join(target, "proxy_usage.json")
    except Exception:
        pass
    # 日志索引缓存全部失效（路径已变）
    with _log_index_lock:
        _log_index_cache.clear()
    cfg = {**_load_config(), "data_dir": target, "log_dir": new_log_dir}
    _save_config(cfg)
    # ---- 校验已过（cmdlib/笔记严格校验，log 尽力、缓存仅搬壳），直接删旧目录 ----
    # 用户口径：不要旧目录备份，迁移完自动删。注意（a245复审F5）：被打开句柄
    # 锁定的文件（活跃日志）rmtree 删不掉会残留在旧目录，直到写端重开——
    # ignore_errors 不中断，残留无害但不会自动清理
    shutil.rmtree(old_data_dir, ignore_errors=True)
    return jsonify({"ok": True, "dir": target, "copied": copied,
                    "deleted": True, "residual": 0, "late_copies": late_total,
                    **({"conflict_errs": conflict_errs} if conflict_errs else {}),
                    "old_dir": old_data_dir, "note": "旧目录已删除"})

@app.route("/api/open_log_file", methods=["POST"])
def api_open_log_file():
    """在资源管理器中打开日志目录并选中指定日志文件（仅 Windows 支持 /select）。"""
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    if not name or not isinstance(name, str):
        return jsonify({"ok": False, "err": "need name"}), 400
    # a238 P3（第5轮A1）：日志家族统一防线——此前裸 os.path.join(LOG_DIR, name)，
    # ../ 或绝对分量可对任意路径做存在性探测 + explorer /select 弹窗骚扰
    path = _resolve_log_path(name)
    if not path:
        return jsonify({"ok": False, "err": "not found"}), 404
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
    # a238 P3-4：整读加 30MB 上限（原 G 级外部日志单请求内存爆点；/api/read_text
    # 有限额而此处漏）——超限只取前 30MB 并打截断标记
    _cap = 30 * 1024 * 1024
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read(_cap + 1)
    if len(text) > _cap:
        text = text[:_cap] + "\n\n……（超过 30MB 上限，已截断——请用日志查看器分页打开）"
    return Response(text, mimetype="text/plain")

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
    offset = _q_int("offset", 0, lo=0)
    limit = _q_int("limit", 500, lo=1, hi=5000)
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
    ts_ms = _q_int("ts", 0, lo=0)
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
    offset = _q_int("offset", 0, lo=0)
    limit = _q_int("limit", 100, lo=1)
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
    offset = _q_int("offset", 0, lo=0)
    limit = _q_int("limit", 200, lo=1)
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
    hit_start = _q_int("hit_start", 0, lo=0)
    count = _q_int("count", 500, lo=1)
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
    from src.app_state import reject_win_devpath
    if reject_win_devpath(data.get("path")):   # a239：CON 等设备名 open/getsize 永久阻塞
        return jsonify({"ok": False, "err": "路径包含 Windows 保留设备名"}), 400
    p = (data.get("path") or "").strip()
    if not p:
        return jsonify({"ok": False, "err": "路径为空"}), 400
    if os.path.isdir(p):
        return jsonify({"ok": True, "is_dir": True})
    if not os.path.isfile(p):
        return jsonify({"ok": False, "err": "文件不存在"}), 400
    from src.editor_files import _EXT_TEXT, _ext_of, _text_kind
    # a357R：把内容分级透给前端——'text' 直接进编辑器；'mixed' 弹打开方式
    # 对话框让用户自己选（用户定调：至少能选，不能强制只给一种）；'binary'
    # 默认十六进制，但对话框仍给阅读器/编辑器选项（除 _EXT_BIN 结构文件）。
    _kind = _text_kind(p)
    _is_text = _kind == "text" or (_kind == "mixed" and _ext_of(p) in _EXT_TEXT)
    return jsonify({"ok": True, "size": os.path.getsize(p),
                    "is_text": _is_text, "kind": _kind})


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
    其余绝对路径直接读（对比任意文本都有意义，只挡目录/不存在/超限）。
    a261（用户实锤 run.bat 被误判二进制）：中文 bat 常为 GBK——旧实现 utf-8
    replace 强解出 >5% 替换符→前端误判二进制。改为：NUL 字节判二进制
    （前 64KB），文本走 utf-8 严格→gb18030 严格→replace 三级探测，GBK
    文件正确还原中文；bin 标志显式回传，前端不再猜。"""
    q = request.args.get("q", "")
    from src.app_state import reject_win_devpath
    if reject_win_devpath(q):   # a239：设备名防线（黑盒 CON 实测挂死线程）
        return jsonify({"ok": False, "err": "路径包含 Windows 保留设备名"}), 400
    path = _resolve_log_path(q)
    if path is None:
        return jsonify({"ok": False, "err": "文件不存在或不可读"}), 400
    try:
        with open(path, "rb") as f:
            data = f.read(30 * 1024 * 1024 + 1)
        if len(data) > 30 * 1024 * 1024:
            return jsonify({"ok": False, "err": "文件过大（>30MB 上限）"}), 400
        if b"\x00" in data[:65536]:
            return jsonify({"ok": False, "err": "二进制文件", "bin": True}), 400
        enc_used = "utf-8"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("gb18030")
                enc_used = "gb18030"
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="replace")
        return jsonify({"ok": True, "name": os.path.basename(path),
                        "text": text, "enc": enc_used})
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
    n = _q_int("n", 200, lo=1)
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
    n = _q_int("n", 50, lo=1)
    result = {}
    with _ports_lock:
        all_ports = list(_ports.items())
    for pid, p in all_ports:
        items = p.get_buffer(n)
        result[pid] = [{"ts": it["ts"], "tag": it["tag"], "text": it["text"]} for it in items]
    return jsonify({"ok": True, "ports": result})

@app.route("/api/snip/img")
def snip_img():
    """内置截图底图（v2.3.12）：TEMP 一次性文件，DPI 子进程抓屏产出（BMP
    免编码）。抓屏与截图窗冷启动并行，这里等文件就绪（最多 3s）。
    no-store：每次截图都是新图，绝不能吃缓存。"""
    import src.snip as _snip
    import time as _t
    for _ in range(15):
        if os.path.isfile(_snip._TMP_BMP):
            break
        _t.sleep(0.2)
    if os.path.isfile(_snip._TMP_BMP):
        with open(_snip._TMP_BMP, "rb") as f:
            data = f.read()
        return data, 200, {"Content-Type": "image/bmp",
                           "Cache-Control": "no-store, max-age=0"}
    return "no image", 404


@app.route("/api/snip/grab", methods=["POST"])
def snip_grab():
    """抓屏（v2.3.12）：DPI 子进程全屏截图落 TEMP（/api/snip/img 的数据源，
    独立截图窗页面加载用）。"""
    import src.snip as _snip
    return jsonify({"ok": bool(_snip.grab())})


@app.route("/api/snip/start", methods=["POST"])
def snip_start():
    """起独立全屏截图窗（v2.3.12 最终形态）：DPI 子进程建无边框置顶全屏窗
    （=物理屏幕，底图 1:1），标注完成收图落 uploads+剪贴板+SEE snip_done。
    端口取自请求 Host（截图窗页面回连本服务）。"""
    import src.snip as _snip
    try:
        port = int((request.host or "").rsplit(":", 1)[-1])
    except Exception:
        port = 80
    ok, info = _snip.launch_window(port)
    return jsonify({"ok": ok, "info": info})


@app.route("/api/snip/save", methods=["POST"])
def snip_save():
    """标注完成（v2.3.12）：{data_url} → 落 harness_uploads + 复制剪贴板，
    返回 path 供前端直接挂对话附件（同页调用，不走 SSE 广播）。"""
    import src.snip as _snip
    data = request.get_json(force=True, silent=True) or {}
    ok, r = _snip.save_png(data.get("data_url") or "")
    return jsonify({"ok": ok, "path": r if ok else None, "err": None if ok else r})


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
    n = _q_int("n", 50, lo=1)
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


# ---- 技能仓库（skills.sh 网页适配 + 安装/离线包/汉化，见 src/skills_repo.py）----

import re as _sk_re
_SK_NAME_RE = _sk_re.compile(r"[A-Za-z0-9_.\-]{1,120}\Z")   # 防御纵深（全审建议7）


def _sk_parts(d):
    """owner/repo/skill 三元组校验（白名单外的直接拒绝）。"""
    vals = tuple(str(d.get(k) or "") for k in ("owner", "repo", "skill"))
    if not all(_SK_NAME_RE.match(v) for v in vals):
        return None
    return vals


@app.route("/api/skills/registry")
def skills_registry():
    """榜单卡片（tab=top/trending/hot；q 内存过滤搜索）。
    顺手后台补齐英文 description（首屏卡片即时出，描述几秒后渐进可见）。"""
    from .skills_repo import registry, _desc_backfill
    rows = registry(request.args.get("tab", "top"),
                    request.args.get("q", ""))
    if rows is None:
        return jsonify({"ok": False, "err": "skills.sh 不可达（检查外网）"}), 502
    miss = [r["key"] for r in rows[:40] if not r.get("desc")]
    if miss:
        threading.Thread(target=_desc_backfill, args=(miss,), daemon=True).start()
    return jsonify({"ok": True, "rows": rows})


@app.route("/api/skills/detail")
def skills_detail():
    """技能详情（raw 原文 + 汉化缓存命中）。"""
    from .skills_repo import detail
    p = _sk_parts(request.args)
    if not p:
        return jsonify({"ok": False, "err": "非法 owner/repo/skill"}), 400
    return jsonify({"ok": True, "detail": detail(*p)})


@app.route("/api/skills/installed")
def skills_installed():
    """本地已安装（user 级目录名身份 + disabled + sha + origin）。"""
    from .skills_repo import installed
    return jsonify({"ok": True, "skills": installed(request.args.get("cwd") or None)})


@app.route("/api/skills/install", methods=["POST"])
def skills_install():
    """安装技能到 ~/.claude/skills/。"""
    from .skills_repo import install
    d = request.get_json(force=True, silent=True) or {}
    p = _sk_parts(d)
    if not p:
        return jsonify({"ok": False, "err": "非法 owner/repo/skill"}), 400
    try:
        r = install(*p, scope=str(d.get("scope") or "user"))
    except Exception as e:   # 落盘意外（盘满/权限）不炸 500，如实回错
        return jsonify({"ok": False, "err": str(e)[:150]}), 500
    return jsonify(r), (200 if r.get("ok") else 502)


@app.route("/api/skills/uninstall", methods=["POST"])
def skills_uninstall():
    """卸载 user 级技能。"""
    from .skills_repo import uninstall
    d = request.get_json(force=True, silent=True) or {}
    return jsonify(uninstall(str(d.get("skill") or "")))


@app.route("/api/skills/disable", methods=["POST"])
def skills_disable():
    """禁用/启用（目录改名 .disabled）。body: {skill, off}"""
    from .skills_repo import disable
    d = request.get_json(force=True, silent=True) or {}
    return jsonify(disable(str(d.get("skill") or ""), bool(d.get("off"))))


@app.route("/api/skills/check_updates", methods=["POST"])
def skills_check_updates():
    """更新检测：本工具装的 user 级技能逐个比对上游 SKILL.md sha。"""
    from .skills_repo import check_updates
    return jsonify({"ok": True, "updates": check_updates()})


@app.route("/api/skills/local_detail")
def skills_local_detail():
    """本地已安装技能详情（读本地 SKILL.md，不出网）。"""
    from .skills_repo import local_detail
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "err": "name 为空"}), 400
    r = local_detail(name)
    return jsonify({"ok": not r.get("err"), **r}), (200 if not r.get("err") else 404)


@app.route("/api/skills/pack/export", methods=["POST"])
def skills_pack_export():
    """勾选技能导出离线包 zip（返回文件路径）。"""
    from .skills_repo import export_pack
    d = request.get_json(force=True, silent=True) or {}
    names = [str(n) for n in (d.get("names") or []) if str(n).strip()]
    if not names:
        return jsonify({"ok": False, "err": "未选择技能"}), 400
    ok, r = export_pack(names)
    return jsonify({"ok": ok, **({"path": r} if ok else {"err": r})})


@app.route("/api/skills/pack/inspect", methods=["POST"])
def skills_pack_inspect():
    """导入第一步：上传 zip → 暂存 + 清单预览 + 冲突检测。"""
    from .skills_repo import pack_inspect
    r, err = pack_inspect(request.files.get("file"))
    if err:
        return jsonify({"ok": False, "err": err}), 400
    return jsonify({"ok": True, **r})


@app.route("/api/skills/pack/apply", methods=["POST"])
def skills_pack_apply():
    """导入第二步：按 token 从暂存包落盘。body: {token, names, overwrite}"""
    from .skills_repo import pack_apply
    d = request.get_json(force=True, silent=True) or {}
    return jsonify(pack_apply(str(d.get("token") or ""),
                              [str(n) for n in (d.get("names") or [])],
                              bool(d.get("overwrite"))))


@app.route("/api/skills/translate", methods=["POST"])
def skills_translate():
    """汉化：kind=meta 批量元数据 / kind=body 单篇正文 / kind=search 中文搜索词
    →英文关键词（缓存优先，轻主力模型）。"""
    from .skills_repo import (translate_meta, translate_body, _raw_skill_md,
                              _llm, _zh_key, _zh_load, _zh_save, light_model)
    d = request.get_json(force=True, silent=True) or {}
    kind = d.get("kind")
    if kind == "search":
        q = str(d.get("q") or "").strip()[:60]
        if not q:
            return jsonify({"ok": False, "err": "q 为空"}), 400
        key = _zh_key("search:", q)
        hit = _zh_load(key)
        if hit:
            return jsonify({"ok": True, "en": hit.get("en")})
        text, err = _llm("你是搜索词翻译引擎。把中文搜索词译成 1-3 个英文关键词"
                         "（小写、空格分隔），用于在英文技能库里搜索。只输出英文关键词。",
                         q, max_tokens=64)
        en = (text or "").strip().lower().split("\n")[0].strip() if not err else ""
        if not en:
            return jsonify({"ok": False, "err": err or "翻译失败"}), 502
        _zh_save(key, {"en": en[:80], "ts": int(time.time())})
        return jsonify({"ok": True, "en": en[:80]})
    if kind == "meta":
        items = [{"key": str(i.get("key") or ""), "name": str(i.get("name") or ""),
                  "desc": str(i.get("desc") or "")}
                 for i in (d.get("items") or []) if isinstance(i, dict) and i.get("key")]
        if not items or len(items) > 40:
            return jsonify({"ok": False, "err": "items 为空或超限"}), 400
        return jsonify({"ok": True, "map": translate_meta(items)})
    if kind == "body":
        # v3.5.310：本地已安装技能（body: {local: name}）——读本地 SKILL.md，
        # 不出网；缓存键与远端同构（内容 hash），skills.sh 装的技能两路共享译文
        local_name = str(d.get("local") or "").strip()
        if local_name:
            from .skills_repo import local_detail as _ld
            md = (_ld(local_name) or {}).get("md")
            if not md:
                return jsonify({"ok": False, "err": "本地 SKILL.md 读取失败"}), 404
        else:
            p = _sk_parts(d)
            if not p:
                return jsonify({"ok": False, "err": "非法 owner/repo/skill"}), 400
            md = _raw_skill_md(*p)   # 直取原文（不走 detail——不烧 contents 限额，全审建议3）
        if not md:
            return jsonify({"ok": False, "err": "SKILL.md 拉取失败"}), 502
        hit = _zh_load(_zh_key("body:", md))
        if hit:
            return jsonify({"ok": True, "body_zh": hit.get("body_zh"), "cached": True})
        r, err = translate_body(md)
        if err:
            return jsonify({"ok": False, "err": err}), 502
        return jsonify({"ok": True, **r})
    return jsonify({"ok": False, "err": "kind 必须是 meta/body"}), 400


@app.route("/api/skills/status")
def skills_status():
    """状态条：轻主力模型名 + 数据源可达性。"""
    from .skills_repo import status
    return jsonify({"ok": True, **status()})


# ---- Claude 实时版本（v2.27：Claude 按钮 hover 显示当前 CLI 版本）----
_claude_ver_cache = {"ver": None, "at": 0.0}

@app.route("/api/claude/version")
def claude_version():
    """真跑 `claude --version` 取当前 CLI 版本。缓存 60s——版本不会秒变，
    但升级/换渠道后最多一分钟内 hover 即见新版本（实时性够且不狂拉子进程）。"""
    import time as _t
    from .claude_conn import _resolve_claude_exe
    if _t.time() - _claude_ver_cache["at"] > 60 or not _claude_ver_cache["ver"]:
        exe, is_shim = _resolve_claude_exe()
        argv = (["cmd.exe", "/c", exe] if is_shim else [exe]) + ["--version"]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = (r.stdout or r.stderr or "").decode("utf-8", errors="replace").strip()
            _claude_ver_cache["ver"] = out.splitlines()[0] if out else ""
            _claude_ver_cache["at"] = _t.time()
        except Exception:
            pass
    return jsonify({"ok": bool(_claude_ver_cache["ver"]),
                    "version": _claude_ver_cache["ver"] or ""})


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


# ---- HikLink 机器人：统一登录状态聚合 + 激活门控（机器人与登录绑定） ----
# （进程隔离时随 bot 移驻 worker；本进程由 claude_worker_relay 307 兜底）
if not CLAUDE_OFFLOAD:
    @app.route("/api/hiklink/status")
    def hiklink_status():
        """统一登录 UI 轮询：登录名 + 机器人运行态。"""
        try:
            return jsonify({"ok": True, **_hiklink_bot.status_snapshot()})
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})

    @app.route("/api/hiklink/activate", methods=["POST"])
    def hiklink_activate():
        """激活/停用机器人（幂等）。未登录（无统一凭据）时激活会被拒绝。"""
        j = request.get_json(silent=True) or {}
        if j.get("stop"):
            ok, msg = _hiklink_bot.ensure_stopped()
        else:
            ok, msg = _hiklink_bot.ensure_started()
        return jsonify({"ok": ok, "msg": msg})

    @app.route("/api/hiklink/credentials", methods=["POST"])
    def hiklink_credentials():
        """保存/清除手填机器人凭据（App ID + App Secret）。本路由与 worker
        侧同款——inline 排障形态（CLAUDE_INLINE=1）下没有 307 兜底，缺它就
        只有 status/activate 可用、保存直连 404。"""
        j = request.get_json(silent=True)
        if not isinstance(j, dict) or "app_id" not in j or "app_secret" not in j:
            return jsonify({"ok": False,
                            "msg": "请求体必须含 app_id 与 app_secret"}), 400
        ok, msg = _hiklink_bot.set_manual_credentials(
            j.get("app_id"), j.get("app_secret"))
        return jsonify({"ok": ok, "msg": msg})


else:
    # ---- Claude worker 兜底重定向（307 保方法保 body）----
    # 前端已由 workerbase.js 直连 worker，这里只兜本机子进程（audit-hook /
    # ask-mcp 等沿用主端口地址的调用方）。worker 未就绪返回 503。
    _CW_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    # claude_default 蓝图随 proxy 二期移驻 worker——它与 claude_setup 共享
    # /api/claude/ 前缀但分属两进程，不能整前缀转：精确枚举其端点+profiles
    # 一族子前缀（workerbase.js 的 PRE 同清单，两处必须同步改）
    _CW_CLAUDE_PATHS = ["/api/claude/api_config", "/api/claude/models_probe",
                        "/api/claude/settings_open", "/api/claude/provision"]

    @app.route("/api/harness", methods=_CW_METHODS)
    @app.route("/api/harness/<path:sub>", methods=_CW_METHODS)
    @app.route("/api/hiklink", methods=_CW_METHODS)
    @app.route("/api/hiklink/<path:sub>", methods=_CW_METHODS)
    @app.route("/api/proxy", methods=_CW_METHODS)
    @app.route("/api/proxy/<path:sub>", methods=_CW_METHODS)
    @app.route("/api/usage", methods=_CW_METHODS)
    @app.route("/api/usage/<path:sub>", methods=_CW_METHODS)
    @app.route("/api/claude/profiles", methods=_CW_METHODS)
    @app.route("/api/claude/profiles/<path:sub>", methods=_CW_METHODS)
    def claude_worker_relay(sub=""):
        if not WORKER_BASE:
            return jsonify({"ok": False, "err": "Claude 后端未就绪（worker 未启动）"}), 503
        tgt = WORKER_BASE + request.path
        if request.query_string:
            tgt += "?" + request.query_string.decode("latin-1")
        return redirect(tgt, code=307)

    # claude_default 的四个精确端点（与上面函数体同款,独立函数避免 Flask
    # 同 endpoint 多装饰器拼错）
    def _claude_default_relay():
        if not WORKER_BASE:
            return jsonify({"ok": False, "err": "Claude 后端未就绪（worker 未启动）"}), 503
        tgt = WORKER_BASE + request.path
        if request.query_string:
            tgt += "?" + request.query_string.decode("latin-1")
        return redirect(tgt, code=307)

    for _p in _CW_CLAUDE_PATHS:
        app.add_url_rule(_p, "claude_relay_" + _p.replace("/", "_"),
                         _claude_default_relay, methods=_CW_METHODS)

    @app.route("/api/worker_endpoint")
    def worker_endpoint():
        """前端/诊断用：worker 是否分离、基址是什么（workerbase.js 的对账口）。"""
        return jsonify({"ok": True, "offload": True, "base": WORKER_BASE})


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
