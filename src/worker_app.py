# -*- coding: utf-8 -*-
"""Claude 子系统 worker 进程（进程隔离，用户定调「Claude 随便占，串口不能卡」）。

背景（v4.0.0 串口卡顿排查实锤，2026-10-22）：harness v4 feed 每 SSE 连接
30ms 一轮的 frames_after 投影、子代理 watcher 的周期 glob 扫描、会话事件
ingest，全部与串口终端同进程抢 GIL；叠加 pywebview 对 '*' 注册的
WebResourceRequested 拦截（页面每个请求都要过 WinForms UI 线程的 Python
回调），Claude 一跑多会话/代理转发，串口敲键回显实测冻结 10~20s（trace：
响应头批量憋 8.8s/20.1s 后同一毫秒放行；串口日志：回显整批迟到 16~43s）。

本进程承载全部 Claude 系重负载——同进程内随便烧，烧不到主进程的串口：
- harness 蓝图（会话 / v4 feed / 子代理 watcher，from src.harness.routes）
- HikLink 机器人（bot 依赖 harness 会话，随迁 /api/hiklink/* 状态/激活
  路由 + 重启自恢复；8766 webhook app 跟 bot 走）

主进程侧配合（src/server.py + src/main.py）：
- CLAUDE_INLINE=1 可回落旧单进程形态（排障通道），默认分离；
- 主进程不注册上述路由，留 307 兜底重定向（audit-hook 等本机子进程沿
  用原地址无感跟随）；
- 前端 web/js/workerbase.js 按 __HG_WORKER__ 基址把 /api/harness、
  /api/hiklink 的 fetch/EventSource 直连本进程（绕开主进程转发开销）。

生命周期（防孤儿三保险）：
- 父进程 atexit/退出链 terminate + 关 stdin；
- 本进程每 3s 用 OpenProcess 探活父 PID，父亡（含被强杀）即 os._exit；
- 端口优先复用上次值（前端 SSE 自动重连不换地址），占用则回退随机端口
  并在 WORKER_READY 里上报实际端口。

就绪协议：stdout 首行 `WORKER_READY {"port": N}`，父进程解析后回填
server.WORKER_BASE 并写 data_dir/claude_worker.json。
"""
import ctypes
import json
import logging
import os
import re
import sys
import threading
import time

# a558：worker 以进程入口运行（python -m src.worker_app）时标记合法 bot
# 宿主/代理承载；被测试导入（build_app，见 test_route_smoke）时不标记——
# 测试实例不得自启 bot/自动登录（SSO 锁号防线）。冻结形态走 main.py
# --claude-worker，其顶部已先设 FC_APP_BOOT
if __name__ == "__main__":
    os.environ.setdefault("FC_APP_BOOT", "1")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

log = logging.getLogger("claude_worker")

# ---------------------------------------------------------------------------
# 父进程探活：父亡即自杀（防孤儿占端口/占内存——「只要不泄露」的兜底层）
# 双保险：①stdin 亲缘带（_stdin_bond，父进程握管道写端，父亡即 EOF，无
# PID 复用误判）②父 PID 周期探活（OpenProcess，兜 stdin 不可用的形态）
# ---------------------------------------------------------------------------
_STILL_ACTIVE = 259
_KERNEL32 = ctypes.windll.kernel32
# 对抗审修：显式原型——HANDLE 是 64 位，默认 c_int restype 会截断句柄
# （CloseHandle 拿到残句柄=关错对象的风险）
_KERNEL32.OpenProcess.restype = ctypes.c_void_p
_KERNEL32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
_KERNEL32.GetExitCodeProcess.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
_KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]


def _parent_alive(pid):
    """Windows 下探活指定 PID（PROCESS_QUERY_LIMITED_INFORMATION 足够）。"""
    if not pid or pid <= 0:
        return True   # 没约定父 PID：不自杀（手动调试场景）
    h = _KERNEL32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if not _KERNEL32.GetExitCodeProcess(h, ctypes.byref(code)):
            return True   # 查不动：保守活着，交给 stdin 亲缘带兜底
        return code.value == _STILL_ACTIVE
    finally:
        _KERNEL32.CloseHandle(h)


def _suicide_with_rollback(reason):
    """父亡自杀前尽力回滚 base_url（a238 P2-3 第5轮A3）。
    worker 里活着 bili(18788)+重试代理(37349)——主进程被强杀后 os._exit 跳过
    一切清理，settings.json 的 ANTHROPIC_BASE_URL 仍指向死端口，外部终端跑
    claude 全部打死端口且无人提示。回滚是毫秒级文件写，失败也不挡自杀。"""
    try:
        from src.proxy import proxy_shutdown
        proxy_shutdown(force_rollback=True)
    except Exception:
        pass
    log.warning("%s，worker 自杀", reason)
    os._exit(0)


def _stdin_bond():
    """父进程亲缘带：stdin 管道写端在父进程手里，父亡（含被强杀）写端
    关闭 → 读到 EOF → 自杀。与 PID 探活互补：PID 复用骗不过 EOF。手动
    控制台跑时 stdin 是终端——读到行不退，EOF 才退（不误杀调试场景）。

    仅在被 manage_start 派生（CLAUDE_WORKER_PARENT_PID 在场=确有父进程
    持管）时由 main 启用；脱离终端/后台重定向（stdin=/dev/null 立即 EOF）
    的独立运行形态不启用——那种场景没有可失联的父，PID 探活（pid=0 不
    自杀）本就不约束。"""
    try:
        st = sys.stdin
        if st is None:
            try:
                st = open(0, "r", encoding="utf-8")
            except Exception:
                return   # 无 stdin 可依的异常形态：仅剩 PID 探活兜底
        while True:
            if not st.read(1):
                _suicide_with_rollback("stdin EOF（父进程已退出）")
    except Exception:
        pass   # 读失败不自杀：误杀比晚杀伤害大


def _parent_watchdog(pid):
    while True:
        time.sleep(3)
        try:
            if not _parent_alive(pid):
                _suicide_with_rollback("父进程 %d 已退出" % pid)
        except Exception:
            pass   # 探活自身异常不自杀：stdin 亲缘带兜底


# ---------------------------------------------------------------------------
# worker Flask 应用
# ---------------------------------------------------------------------------
def build_app():
    from flask import Flask, jsonify, request

    from src.harness.routes import harness_bp
    from src import hiklink_bot
    from src.proxy import proxy_bp
    from src.proxy_usage import usage_bp
    from src.claude_default import claude_default_bp

    app = Flask(__name__)
    app.register_blueprint(harness_bp)
    # 二期（用户拍板「proxy 搬 worker 做掉，配置不常动」）：Claude proxy
    # 数据面+面板 API+用量统计+默认环境/凭据配置蓝图随迁——claude 流量的
    # json 解析/转发烧 worker 的 GIL，主进程只剩串口终端与轻量路由。
    # claude_default 的 re-point 队列与 proxy 同进程反而更顺（原来跨在
    # 主进程）；claude_setup 的模块级安装原语被 res_install 复用，但无端点
    # 无状态，留在哪个进程都无所谓（a32x 起旧 zip 安装引导通道已退役）
    app.register_blueprint(proxy_bp)
    app.register_blueprint(usage_bp)
    app.register_blueprint(claude_default_bp)

    # ---- HikLink 机器人路由（自 server.py 随迁，语义不变） ----
    @app.route("/api/hiklink/status")
    def hiklink_status():
        """统一登录 UI 轮询：登录名 + 机器人运行态。"""
        try:
            return jsonify({"ok": True, **hiklink_bot.status_snapshot()})
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})

    @app.route("/api/hiklink/activate", methods=["POST"])
    def hiklink_activate():
        """激活/停用机器人（幂等）。未登录（无统一凭据）时激活会被拒绝。"""
        j = request.get_json(silent=True) or {}
        if j.get("stop"):
            ok, msg = hiklink_bot.ensure_stopped()
        else:
            ok, msg = hiklink_bot.ensure_started()
        return jsonify({"ok": ok, "msg": msg})

    @app.route("/api/hiklink/credentials", methods=["POST"])
    def hiklink_credentials():
        """保存/清除手填机器人凭据（App ID + App Secret）。
        body: {app_id, app_secret}；两者皆空 = 清除。保存即重连生效。
        显式要求两个键都在场：把「取不到参数」当清除的话，本机任意网页
        一个 text/plain 简单请求就能清空凭据并停掉机器人。Host/Origin
        由全站 _guard_host 收口。"""
        j = request.get_json(silent=True)
        if not isinstance(j, dict) or "app_id" not in j or "app_secret" not in j:
            return jsonify({"ok": False, "msg": "请求体必须含 app_id 与 app_secret"}), 400
        ok, msg = hiklink_bot.set_manual_credentials(
            j.get("app_id"), j.get("app_secret"))
        return jsonify({"ok": ok, "msg": msg})

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "pid": os.getpid()})

    @app.route("/worker_shutdown", methods=["POST"])
    def worker_shutdown():
        """父进程退出链调用（manage_stop）：优雅收尾后自杀——先停 Claude
        proxy（停额度 worker/bili 压缩/重试代理+base_url 回滚直连，否则
        claude CLI 会连着一个死端口），再逐会话 kill_proc（杀 claude 进程
        + 清 peer 注册，防幽灵会话/孤儿 CLI）、停机器人，半秒后 os._exit。
        硬 terminate 是兜底不是首选（硬杀路径 base_url 不回滚，靠会话侧
        ensure_direct_if_proxy_down 下次启动自愈）。"""
        try:
            from src.proxy import proxy_shutdown
            proxy_shutdown()
        except Exception:
            pass
        try:
            from src.harness.consts import _sessions, _sessions_lock
            with _sessions_lock:
                snaps = list(_sessions.values())
            for s in snaps:
                try:
                    s.kill_proc()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            hiklink_bot.ensure_stopped()
        except Exception:
            pass
        threading.Timer(0.5, os._exit, (0,)).start()
        return jsonify({"ok": True})

    # ---- CORS：只放行主进程页面来源（父进程注入的真实端口）+ 本 worker 自身 ----
    # 安全修复（a116 全审 P0）：原实现全站 `Access-Control-Allow-Origin: *`
    # ——浏览器里任一网页脚本都能跨源读 /api/claude/api_config（明文 token）、
    # 任意路径读 /api/harness/file、跨源驱动 /api/proxy/start|stop 与
    # /api/harness/send。worker 端口可扫描，改动前主进程无 CORS 头。
    # a117（用户实锤「重启后 Claude 面板全挂、会话列表空」）：a116 的白名单
    # **双死**——① _MAIN_ORIGIN 硬编码 8765，而主进程端口每次启动动态随机
    #（实测 63382/61580 各不相同）恒不命中；② _base 在 worker 进程内从未
    # 初始化（只有父进程侧 manage_start 会设它，worker 侧恒空串）恒不命中。
    # 白名单两条全死=零放行=合法主页面也被全拦（sessions 拉不到=「会话
    # 没了」假象，数据无损）。修：主来源改吃父进程注入的
    # CLAUDE_WORKER_MAIN_ORIGIN（manage_start 在主进程 write_endpoint(port)
    # 之后调用，真实端口在手）；worker 侧 main() 绑定后回填全局 _base。
    # 维持 MAJOR-6 安全判定：**不**放宽为「任意 loopback 端口」——本机
    # 恶意网页（http://127.0.0.1:9999 之类）依旧全拦，白名单精确到
    # 主页面来源 + worker 自身两个；无 Origin（同源/服务端调用）不设头
    _MAIN_ORIGIN = (os.environ.get("CLAUDE_WORKER_MAIN_ORIGIN") or "").strip()

    # 允许的来源集合（before_request 与 CORS 共用，两处必须一致——只松一边
    # 等于没修）。主机名等价变体（127.0.0.1/localhost/[::1]）放行、**端口
    # 精确不变**：既不误杀 localhost 打开的页面，也不放开本机任意网页。
    from urllib.parse import urlsplit as _urlsplit

    def _origin_variants(origin):
        o = (origin or "").strip().rstrip("/")
        if not o:
            return set()
        try:
            sp = _urlsplit(o)
        except Exception:
            return {o}
        if not sp.hostname:
            return {o}
        port = (":%d" % sp.port) if sp.port else ""
        out = {o}
        for h in ("127.0.0.1", "localhost", "[::1]"):
            out.add("%s://%s%s" % (sp.scheme, h, port))
        return out

    def _origin_allowed(origin):
        o = (origin or "").strip().rstrip("/")
        if not o:
            return False
        for src in (_MAIN_ORIGIN, _base):
            if src and o in _origin_variants(src):
                return True
        return False

    @app.before_request
    def _guard_host():
        """全站 Host 收口（对齐主进程 server.py 的 _guard_local_origin）。

        此前只有 /api/hiklink/credentials 自己校验，其余端点在 worker 形态下
        没有防线：/api/hiklink/status 现在回传明文 App Secret，DNS rebinding
        （evil.com 重绑到 127.0.0.1:worker端口）后同源 GET 即可读出密钥。

        写操作另校 Origin，**只放行精确来源**：主页面来源、worker 自身、
        以及它们的主机名等价变体（127.0.0.1 ↔ localhost ↔ [::1]，端口不变）。
        绝不放开「任意 loopback 端口」——那会让本机任意网页（127.0.0.1:9999）
        跨源驱动 harness/send、改 api_config（a116 既定安全判定）。
        """
        host = (request.host or "").strip()
        if not _LOCAL_HOST_RE.match(host):
            return jsonify({"ok": False, "msg": "forbidden host"}), 403
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = (request.headers.get("Origin") or "").strip().rstrip("/")
            if origin and not _origin_allowed(origin):
                return jsonify({"ok": False, "msg": "forbidden origin"}), 403
        return None

    @app.after_request
    def _cors(resp):
        # 与 _guard_host 共用同一套放行集合：只松 before_request 不松 CORS
        # 等于没修——localhost 打开的页面在预检阶段就拿不到 ACAO
        origin = (request.headers.get("Origin") or "").strip()
        if origin and _origin_allowed(origin.rstrip("/")):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = \
                "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    return app


def _bot_restore():
    """机器人重启自恢复（自 server.py start_background 随迁，逻辑同款）。"""
    time.sleep(8)   # 让端口/网络就绪，避开启动高峰
    try:
        from src import hiklink_bot as hb
        # 机器人只认凭证登录（SSO 自动注册已退役）：没有 app_id/app_secret
        # 就不要去调 ensure_started，否则每次开机刷一行「启动自恢复失败」
        if hb.is_manual_mode():
            ok, msg = hb.ensure_started()
            log.info("启动自恢复机器人: %s (%s)", "成功" if ok else "失败", msg)
    except Exception as e:
        log.warning("启动自恢复机器人异常: %s", e)


def main():
    # 日志落 data_dir（worker 无控制台；stdout 只走就绪协议，防污染解析）
    from src.app_state import DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        filename=os.path.join(DATA_DIR, "claude_worker.log"),
        filemode="a", encoding="utf-8")
    # werkzeug 访问日志降噪（SSE 心跳每 15s 一条，量大无信息）
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app = build_app()
    # worker 身份标记：proxy 的托盘 tooltip 线程等主进程专属集成据此跳过
    os.environ["CLAUDE_WORKER"] = "1"
    # Claude Proxy 模块初始化（额度 worker/bili stats；不自动启动代理）
    try:
        from src.proxy import proxy_module_init
        proxy_module_init()
    except Exception as e:
        log.warning("proxy_module_init 失败: %s", e)
    threading.Thread(target=_bot_restore, daemon=True,
                     name="hiklink-bot-restore").start()
    # 子代理 watcher 预热（不预热也能被会话 lifecycle 懒拉起，这里只是
    # 让 worker 一活就具备 sub feed 服务能力）
    try:
        from src.harness.subagent_watch import ensure_started as _sw
        _sw()
    except Exception:
        pass

    from werkzeug.serving import make_server
    prefer = int(os.environ.get("CLAUDE_WORKER_PORT") or 0)
    port = prefer
    for _try in range(2):
        try:
            srv = make_server("127.0.0.1", port, app, threaded=True)
            break
        except OSError:
            if _try == 0 and prefer:
                port = 0   # 期望端口被占（上次 worker 还没死透）→ 随机
                continue
            raise
    actual = srv.server_port
    # a117：worker 侧回填自身来源（_cors 白名单第二条此前恒空串——模块级
    # _base 只有父进程侧 manage_start 会设，worker 进程内从未初始化）
    global _base
    _base = "http://127.0.0.1:%d" % actual

    parent_pid = int(os.environ.get("CLAUDE_WORKER_PARENT_PID") or 0)
    if parent_pid > 0:
        # 有父（manage_start 派生）：stdin 亲缘带上岗（父亡即 EOF 即自杀）
        threading.Thread(target=_stdin_bond, daemon=True,
                         name="stdin-bond").start()
    threading.Thread(target=_parent_watchdog, args=(parent_pid,),
                     daemon=True, name="parent-watchdog").start()

    sys.stdout.write("WORKER_READY %s\n" % json.dumps(
        {"port": actual, "pid": os.getpid()}))
    sys.stdout.flush()
    log.info("worker 就绪 port=%s pid=%s prefer=%s", actual, os.getpid(), prefer)
    srv.serve_forever()


# ---------------------------------------------------------------------------
# 父进程侧管理（dev/打包 两形态拉起、就绪握手、崩溃/挂死重启、退出回收）
# ---------------------------------------------------------------------------
_proc = None
_stop = threading.Event()
_base = ""
# 与主进程 server.py 的 _LOCAL_HOST_RE 同款：全站 Host 收口用（见 _guard_host）
# 注：**不要**再引入「任意 loopback 端口」的 Origin 正则——那会放开本机任意
# 网页对 worker 的跨源写面（a116 既定安全判定）。来源白名单见 _origin_allowed
_LOCAL_HOST_RE = re.compile(
    r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", re.I)
_MAIN_PORT = 0            # a117：主进程服务端口（CORS 白名单注入用；manage_start 传入）
_last_port = 0            # 最近一次实际端口（respawn 期望值跟随 fallback）
_hung = 0                 # 连续 health 探活失败计数（挂死检测）
_lock = threading.Lock()


def _spawn_cmd(prefer_port):
    env = dict(os.environ)
    env["CLAUDE_WORKER_PORT"] = str(prefer_port)
    env["CLAUDE_WORKER_PARENT_PID"] = str(os.getpid())
    # a117：主页面真实来源随拉起注入（主进程端口动态随机，硬编码必死）
    if _MAIN_PORT:
        env["CLAUDE_WORKER_MAIN_ORIGIN"] = "http://127.0.0.1:%d" % _MAIN_PORT
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--claude-worker"]
        cwd = None
    else:
        cmd = [sys.executable, "-u", "-m", "src.worker_app"]
        cwd = _ROOT
    return cmd, env, cwd


def _write_endpoint(port, pid):
    try:
        from src.app_state import DATA_DIR
        with open(os.path.join(DATA_DIR, "claude_worker.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"pid": pid or 0, "port": port}, f)
    except Exception:
        pass


def _apply_base(port, pid):
    global _base
    _base = "http://127.0.0.1:%d" % port
    try:
        from src import server as _srv
        _srv.WORKER_BASE = _base   # index 注入 + 307 兜底重定向用
    except Exception:
        pass
    _write_endpoint(port, pid)


def _spawn_once(prefer_port, ready_timeout=25):
    """拉起一个 worker 实例并等 WORKER_READY。返回 (proc, port) 或抛异常。"""
    import subprocess
    cmd, env, cwd = _spawn_cmd(prefer_port)
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=env, cwd=cwd,
                         creationflags=flags)
    # readline 在无输出时会无限阻塞——放后台线程读，主线程限时 join，
    # 超时（worker 卡死/静默）杀进程按失败处理，不拖启动
    got = {}

    def _wait_ready():
        while True:
            line = p.stdout.readline()
            if not line:
                got["eof"] = True
                return
            s = line.decode("utf-8", "replace").strip()
            if s.startswith("WORKER_READY"):
                try:
                    got["port"] = json.loads(s[len("WORKER_READY"):]).get("port")
                except Exception:
                    pass
                return

    th = threading.Thread(target=_wait_ready, daemon=True)
    th.start()
    th.join(ready_timeout)
    if "port" not in got:
        try:
            p.kill()
        except Exception:
            pass
        raise RuntimeError("worker 就绪握手超时（%ss）" % ready_timeout)
    port = got["port"]
    # 常驻排空线程：不排空 stdout 管道写满会卡死 worker（泄漏面）
    def _drain():
        try:
            for ln in p.stdout:
                logging.getLogger("claude_worker.stdout").info(
                    ln.decode("utf-8", "replace").rstrip())
        except Exception:
            pass
    threading.Thread(target=_drain, daemon=True).start()
    return p, port


def _health_ok():
    """worker /health 探活（挂死检测：GIL 死锁但进程活着时 poll() 恒活）。"""
    b = _base
    if not b:
        return True
    try:
        import urllib.request
        urllib.request.urlopen(b + "/health", timeout=2).read()
        return True
    except Exception:
        return False


def _supervisor(prefer_port):
    """监护：进程死(poll)/挂死(health 连败)→指数退避重启。

    对抗审修（锁纪律）：spawn 全程在锁外（握手最长 25s，持锁会堵死
    manage_stop/退出链——实测风险：关工具卡半分钟）；spawn 完成后锁内
    复查 _stop，已停则就地处决新子进程（不留「停止后又复活」的孤儿）。
    期望端口跟随最近实际端口（fallback 换过口后续 respawn 不再死磕旧口）。"""
    global _proc, _last_port, _hung
    backoff = 2.0
    tick = 0
    while not _stop.is_set():
        _stop.wait(5)
        if _stop.is_set():
            return
        tick += 1
        with _lock:
            p = _proc
        if p is not None and p.poll() is None:
            restart = False
            # P1-5 修复（a116）：计数清零必须在「本次确实做了 health 检查
            # 且成功」时发生。原 `if tick%3==0 and not health: ++ else: =0`
            # ——两次检查之间必有两个非 %3 的 tick 走 else 清零，计数永远
            # 到不了 2（逐 tick 模拟 60 次恒失败反证：触发点为空集），
            # worker GIL 挂死（进程活着 poll 恒 None）时永不重启。
            if tick % 3 == 0:
                if not _health_ok():
                    _hung += 1
                    logging.getLogger("claude_worker").warning(
                        "worker health 探活失败 %d/2", _hung)
                    if _hung >= 2:
                        try:
                            p.kill()
                        except Exception:
                            pass
                        restart = True
                else:
                    _hung = 0
            if not restart:
                backoff = 2.0
                continue
            _hung = 0
        # 进程死(poll)或挂死(health 两连败)→ 退避等待后锁外重启
        _stop.wait(backoff)
        if _stop.is_set():
            return
        try:
            p2, port = _spawn_once(_last_port or prefer_port)
            with _lock:
                if _stop.is_set():
                    try:
                        p2.kill()
                    except Exception:
                        pass
                    return
                _proc = p2
            _apply_base(port, p2.pid)
            _last_port = port
            backoff = min(backoff * 2, 30.0)
            logging.getLogger("claude_worker").warning(
                "worker 已重启 port=%s pid=%s", port, p2.pid)
        except Exception as e:
            logging.getLogger("claude_worker").warning("worker 重启失败: %s", e)
            # a238 P3-4：失败同样增长退避——原仅成功路径翻倍，失败时 backoff
            # 恒 2s → 每 ~7s 一次真实进程生灭循环（Popen+25s 等待）常驻 churn
            backoff = min(backoff * 2, 30.0)


def manage_start(prefer_port=0, main_port=0):
    """主进程开窗前调用：拉起 worker 并进入监护。失败不抛（终端优先）。
    main_port（a117）：主进程服务端口——worker CORS 白名单的注入源（主页面
    来源动态随机，硬编码必拦；调用点在 write_endpoint(port) 之后端口在手）。"""
    global _proc, _last_port, _MAIN_PORT
    if main_port:
        _MAIN_PORT = main_port
    if os.environ.get("CLAUDE_INLINE") == "1":
        return
    try:
        import socket
        if not prefer_port:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            prefer_port = s.getsockname()[1]
            s.close()
        _proc, port = _spawn_once(prefer_port)
        _last_port = port
        _apply_base(port, _proc.pid)
        threading.Thread(target=_supervisor, args=(prefer_port,), daemon=True,
                         name="claude-worker-supervisor").start()
        import atexit
        atexit.register(manage_stop)
    except Exception as e:
        logging.getLogger("claude_worker").warning(
            "worker 拉起失败（Claude 面板将不可用，串口不受影响）: %s", e)


def manage_stop():
    _stop.set()
    global _proc
    with _lock:
        p = _proc
        _proc = None
    base = _base
    if p is not None and p.poll() is None:
        # 先优雅（/worker_shutdown：杀会话进程+清 peer 注册+停 bot），
        # 2s 不退再硬杀 terminate
        try:
            if base:
                import urllib.request
                # P1-2 修复（a116）：原用无 body 的 urlopen（=GET）打
                # POST-only 的 /worker_shutdown → 405，优雅收尾整段不执行：
                # proxy_shutdown（停额度/bili/重试代理 + **base_url 回滚
                # 直连**）、逐会话 kill_proc、hiklink_bot 全被跳过，紧接着
                # stdin 关闭让 worker 0.05s 内 os._exit → base_url 长期指向
                # 已死端口，下次开 Claude Code 直接连不上；claude CLI 成孤儿。
                _req = urllib.request.Request(
                    base + "/worker_shutdown", data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST")
                urllib.request.urlopen(_req, timeout=3).read()
                p.wait(timeout=4)
        except Exception:
            pass
        if p.poll() is None:
            try:
                p.stdin.close()
            except Exception:
                pass
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    try:
        from src import server as _srv
        _srv.WORKER_BASE = ""
    except Exception:
        pass
    try:
        from src.app_state import DATA_DIR
        ep = os.path.join(DATA_DIR, "claude_worker.json")
        if os.path.exists(ep):
            os.remove(ep)   # 过期档案不清会误导排查（pid 已死/端口已换）
    except Exception:
        pass


if __name__ == "__main__":
    main()
