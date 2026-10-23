# -*- coding: utf-8 -*-
"""Claude 子系统 worker 进程（进程隔离，用户定调「Claude 随便占，串口不能卡」）。

背景（v4.0.0 串口卡顿排查实锤，2026-10-22）：harness v4 feed 每 SSE 连接
30ms 一轮的 frames_after 投影、子代理 watcher 的周期 glob 扫描、会话事件
ingest，全部与串口终端同进程抢 GIL；叠加 pywebview 对 '*' 注册的
WebResourceRequested 拦截（页面每个请求都要过 WinForms UI 线程的 Python
回调），Claude 一跑多会话/代理转发，串口敲键回显实测冻结 10~20s（trace：
响应头批量憋 8.8s/20.1s 后同一毫秒放行；串口日志：回显整批迟到 16~43s）。

本进程承载全部 Claude 系重负载——同进程内随便烧，烧不到主进程的串口：
- harness 蓝图（会话 / v4 feed / 子代理 watcher，from src.claude_harness）
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
import sys
import threading
import time

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
                log.warning("stdin EOF（父进程已退出），worker 自杀")
                os._exit(0)
    except Exception:
        pass   # 读失败不自杀：误杀比晚杀伤害大


def _parent_watchdog(pid):
    while True:
        time.sleep(3)
        try:
            if not _parent_alive(pid):
                log.warning("父进程 %s 已退出，worker 自杀", pid)
                os._exit(0)
        except Exception:
            pass   # 探活自身异常不自杀：stdin 亲缘带兜底


# ---------------------------------------------------------------------------
# worker Flask 应用
# ---------------------------------------------------------------------------
def build_app():
    from flask import Flask, jsonify, request

    from src.claude_harness import harness_bp
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
    # 主进程）；claude_setup（安装引导）留主进程，其内部调 claude_default
    # 函数属罕见路径，跨进程写竞态用户已接受
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

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "pid": os.getpid()})

    @app.route("/worker_shutdown", methods=["POST"])
    def worker_shutdown():
        """父进程退出链调用（manage_stop）：优雅收尾后自杀——先停 Claude
        proxy（停额度 worker/headroom/重试代理+base_url 回滚直连，否则
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

    # ---- CORS：只放行主进程页面来源（同源 127.0.0.1:8765） ----
    # 安全修复（a116 全审 P0）：原实现全站 `Access-Control-Allow-Origin: *`
    # ——浏览器里任一网页脚本都能跨源读 /api/claude/api_config（明文 token）、
    # 任意路径读 /api/harness/file、跨源驱动 /api/proxy/start|stop 与
    # /api/harness/send。worker 端口可扫描，改动前主进程无 CORS 头。
    # 现只回显白名单 Origin（主进程端口 + 本 worker 自身端口）；无 Origin
    # （同源导航/服务端调用）不设头，浏览器按同源处理。
    _MAIN_ORIGIN = "http://127.0.0.1:8765"

    @app.after_request
    def _cors(resp):
        origin = (request.headers.get("Origin") or "").strip()
        allow = ""
        # MAJOR-6 修正（a116 二次全审）：不能放行任意本机端口——本机任一
        # 网页（http://127.0.0.1:9999 之类）即可跨域读 /api/claude/api_config
        # （明文 token）并驱动 /api/proxy/start|stop。只白名单主进程页面
        # 来源与本 worker 自身端口（非 loopback 域名一律不放行）。
        if origin and (origin == _MAIN_ORIGIN or origin == _base):
            allow = origin
        if allow:
            resp.headers["Access-Control-Allow-Origin"] = allow
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
        d = hb._load_session_file()
        if d.get("uid") and d.get("password"):
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
    # Claude Proxy 模块初始化（额度 worker/headroom stats；不自动启动代理）
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
_last_port = 0            # 最近一次实际端口（respawn 期望值跟随 fallback）
_hung = 0                 # 连续 health 探活失败计数（挂死检测）
_lock = threading.Lock()


def _spawn_cmd(prefer_port):
    env = dict(os.environ)
    env["CLAUDE_WORKER_PORT"] = str(prefer_port)
    env["CLAUDE_WORKER_PARENT_PID"] = str(os.getpid())
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


def manage_start(prefer_port=0):
    """主进程开窗前调用：拉起 worker 并进入监护。失败不抛（终端优先）。"""
    global _proc, _last_port
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
                # proxy_shutdown（停额度/headroom/重试代理 + **base_url 回滚
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
