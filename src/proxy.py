# -*- coding: utf-8 -*-
"""Claude Proxy 合入模块（原 D:/AI/proxy 独立工具，tkinter 版去 GUI 平移）。

链路：Claude Code → 8787(headroom 压缩) → 37349(重试代理) → lanz.hikvision.com

组件（全部从 claude_proxy_gui_headroom.pyw 平移，去 tkinter）：
- BaseUrlManager     读写 ~/.claude/settings*.json 的 ANTHROPIC_BASE_URL（原子写原样保留）
- ProxyController    重试代理生命周期（core.create_server + daemon 线程）
- HeadroomController headroom 压缩层子进程托管（8787）
- LanzQuotaWorker    额度查询后台线程（emit 直写模块缓存，无 root.after）
- proxy_bp           Flask 蓝图：/api/proxy/* 给前端面板
- tray_menu_items()  Proxy 托盘段——并入主工具托盘（用户定：托盘合成一个，
                     不建第二个 Icon）；tooltip 由 1s 线程写主托盘 title

退出三件套（必须完整，生产验证过的保命逻辑）：
- 退出回滚 base_url（autoswitched 标记，只有工具自己改写过才回滚）
- atexit 兜底回滚（Ctrl-C/kill 等 _quit 没走的路径）
- 启动自愈（上次强杀后 base_url 卡代理地址 → 切回直连）
"""
import atexit
import json
import logging
import os
import socket
import subprocess
import threading
import time

from flask import Blueprint, jsonify, request

from src import proxy_core as core
from src import lanz_quota
from src.app_state import BASE_DIR, DATA_DIR

log = logging.getLogger("claude_proxy")

# ---- 常量（GUI:73-233 平移）----
PROXY_URL = "http://127.0.0.1:8787"
DIRECT_URL = "http://lanz.hikvision.com/v3/anthropic/model"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 37349
RETRY_URL = "http://127.0.0.1:%d/v3/anthropic/model" % LISTEN_PORT
UPSTREAM = "lanz.hikvision.com:80"

HEADROOM_PORT = 8787
HEADROOM_UPSTREAM = RETRY_URL
HEADROOM_ENV_EXTRA = {"HEADROOM_RETRY_MAX_ATTEMPTS": "1",
                      "HEADROOM_MODE": "token",
                      "HEADROOM_NO_CCR": "1"}
PIP_PKG_SPEC = "headroom-ai[all]"
HEADROOM_READY_TIMEOUT = 90

HEADROOM_MODES = {
    "full":  {"label": "完整压缩（ML + 结构化）", "env": {}},
    "light": {"label": "轻量压缩（仅结构化，省 ~400MB 内存）",
              "env": {"HEADROOM_DISABLE_KOMPRESS": "1"}},
    "off":   {"label": "关闭压缩（headroom 不启动）", "env": None},
}

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HEADROOM_MODE_PATH = os.path.join(CLAUDE_DIR, "headroom_mode.json")
CLAUDE_SETTINGS_PATHS = (
    os.path.join(CLAUDE_DIR, "settings.local.json"),
    os.path.join(CLAUDE_DIR, "settings.json"),
)
# 凭据/日志随主工具数据目录（不写进 _MEI 临时目录、不散落）
LANZ_CRED_PATH = os.path.join(DATA_DIR, "lanz_credentials.json")

try:
    from PIL import Image, ImageDraw, ImageFont   # 托盘图标绘制（原生 Win32 托盘不吃 PIL，仅保留其他用途）
except Exception:
    pass

HAS_LANZ = True
try:
    from src.lanz_quota import (LanzError, LanzAuthError, LanzSessionExpired,
                                LanzNetworkError, LanzClient, load_credentials,
                                save_credentials)
except Exception:
    HAS_LANZ = False


def _fnum(n):
    """数字缩写（GUI fnum 平移）：12345 → 12.3k"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1e8:
        return "%.0f" % n
    if n >= 1e4:
        return "%.1fW" % (n / 1e4)
    if n >= 1e3:
        return "%.1fk" % (n / 1e3)
    if n == int(n):
        return "%d" % int(n)
    return "%.1f" % n


# ---- BaseUrlManager（GUI:330-396 原样，纯文件操作零 GUI）---------------
class BaseUrlManager:
    """读写 ~/.claude/settings*.json 的 env.ANTHROPIC_BASE_URL。
    只动 ANTHROPIC_BASE_URL 一个字段，其余一概不碰。
    原子写 + 撞锁重试（重试前重读磁盘合并，防 stale 快照覆盖并发改动）。"""

    def read_current_url(self):
        for path in CLAUDE_SETTINGS_PATHS:
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                env = d.get("env")
                url = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
                if url:
                    return url
            except (ValueError, OSError, AttributeError):
                continue
        return None

    def apply(self, target):
        changed, skipped = [], []
        for path in CLAUDE_SETTINGS_PATHS:
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
            except (ValueError, OSError, AttributeError) as e:
                log.warning("读取 %s 失败，跳过: %s", path, e)
                continue
            env = d.get("env")
            old = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
            if old == target:
                skipped.append(os.path.basename(path))
                continue
            d.setdefault("env", {})["ANTHROPIC_BASE_URL"] = target
            tmp = path + ".tmp"
            for attempt in range(3):
                try:
                    if attempt > 0:
                        with open(path, encoding="utf-8") as f:
                            d = json.load(f)
                        d.setdefault("env", {})["ANTHROPIC_BASE_URL"] = target
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(d, f, indent=2, ensure_ascii=False)
                        f.write("\n")
                    os.replace(tmp, path)
                    changed.append("%s: %s -> %s" % (os.path.basename(path), old, target))
                    break
                except OSError:
                    time.sleep(0.2)
        return changed, skipped


# ---- ProxyController（GUI:400-464 平移，本来就纯线程零 tkinter）---------
class ProxyController:
    def __init__(self):
        self.server = None
        self.stats = None
        self.stop_event = None
        self.thread = None
        self._lock = threading.Lock()

    @staticmethod
    def port_in_use(host=LISTEN_HOST, port=LISTEN_PORT):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex((host, port)) == 0
        except OSError:
            return False

    @staticmethod
    def ping_existing(host=LISTEN_HOST, port=LISTEN_PORT):
        try:
            import urllib.request
            r = urllib.request.urlopen(
                "http://%s:%d/__proxy/ping" % (host, port), timeout=1)
            return r.status == 200
        except Exception:
            return False

    @property
    def running(self):
        return self.server is not None and not self.stop_event.is_set()

    def start(self, host=LISTEN_HOST, port=LISTEN_PORT, upstream=UPSTREAM):
        with self._lock:
            if self.running:
                return
            if self.port_in_use(host, port):
                raise RuntimeError("端口 %d 已被占用" % port)
            self.server, self.stats, self.stop_event = core.create_server(
                host, port, upstream)
            self.thread = core.server_thread_start(self.server, self.stop_event)
            log.info("代理已启动 %s:%d -> %s", host, port, upstream)

    def stop(self):
        with self._lock:
            if not self.running:
                self.server = None
                return
            srv, ev = self.server, self.stop_event
            self.server = None
            self.stop_event = None
        t = threading.Thread(target=core.stop_server, args=(srv, ev), daemon=True)
        t.start()
        log.info("代理已停止")

    def snapshot(self):
        if self.stats is None:
            return None
        return self.stats.snapshot(history_limit=500)


# ---- 压缩模式持久化（GUI:468-529 原样）--------------------------------
def load_headroom_mode():
    try:
        with open(HEADROOM_MODE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        mode = d.get("mode")
        if mode in HEADROOM_MODES:
            return mode
    except (ValueError, OSError):
        pass
    return None


def load_ccr():
    try:
        with open(HEADROOM_MODE_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("ccr"))
    except (ValueError, OSError):
        return False


def _write_mode_file(updates):
    d = {}
    try:
        with open(HEADROOM_MODE_PATH, encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict):
            d.update(old)
    except (ValueError, OSError):
        pass
    d.update(updates)
    with open(HEADROOM_MODE_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def save_headroom_mode(mode, remember=True):
    try:
        if remember and mode in HEADROOM_MODES:
            _write_mode_file({"mode": mode})
        else:
            try:
                os.remove(HEADROOM_MODE_PATH)
            except OSError:
                pass
    except OSError as e:
        log.warning("保存压缩模式失败: %s", e)


def save_ccr(enabled):
    try:
        _write_mode_file({"ccr": bool(enabled)})
    except OSError as e:
        log.warning("保存 CCR 开关失败: %s", e)


# ---- headroom.exe 定位（GUI:86-172 平移）------------------------------
def _detect_headroom_exe():
    if getattr(__import__("sys"), "frozen", False):
        roots = []
        home = os.path.expanduser("~")
        _PY = os.path.join(home, "AppData", "Local", "Programs", "Python")
        if os.path.isdir(_PY):
            roots.append(_PY)
        for pf in (r"C:\Program Files\Python39", r"C:\Program Files\Python310",
                   r"C:\Program Files\Python311", r"C:\Program Files\Python312",
                   r"C:\Program Files\Python313", r"C:\Program Files\Python314"):
            if os.path.isdir(pf):
                roots.append(pf)
        for root in roots:
            subs = []
            for ver in sorted(os.listdir(root), reverse=True):
                d = os.path.join(root, ver)
                if os.path.isdir(d) and not ver.startswith("_"):
                    subs.append(d)
            if os.path.exists(os.path.join(root, "python.exe")):
                subs.append(root)
            for d in subs:
                cand = os.path.join(d, "Scripts", "headroom.exe")
                if os.path.isfile(cand):
                    return cand
        import shutil
        p = shutil.which("headroom")
        return p
    # 源码运行：从当前解释器同目录 Scripts 推导；找不到再 which 兜底
    import sys
    cand = os.path.join(os.path.dirname(sys.executable),
                        "Scripts", "headroom.exe")
    if os.path.isfile(cand):
        return cand
    import shutil
    return shutil.which("headroom")


HEADROOM_EXE = _detect_headroom_exe()


# ---- HeadroomController（GUI:533-660 平移）----------------------------
class HeadroomController:
    def __init__(self):
        self.proc = None
        self._err_file = None
        self._out_file = None
        self._lock = threading.Lock()

    @staticmethod
    def port_in_use(port=HEADROOM_PORT):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False

    @staticmethod
    def ping_existing(port=HEADROOM_PORT):
        import urllib.request, urllib.error
        for path in ("/livez", "/healthz", "/stats"):
            try:
                r = urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (port, path), timeout=1)
                if 200 <= r.status < 300:
                    return True
            except urllib.error.HTTPError as e:
                if 500 <= e.code < 600:
                    return True
                continue
            except Exception:
                continue
        return False

    @property
    def running(self):
        if self.proc is not None:
            return self.proc.poll() is None
        return self.ping_existing()

    def proc_snapshot(self):
        with self._lock:
            return self.proc

    def start(self, mode="full", ccr=None):
        with self._lock:
            if self.running:
                if self.proc is None:
                    log.info("headroom: 8787 已有实例在跑，复用（不接管）")
                return
            if self.port_in_use():
                raise RuntimeError("端口 %d 已被其他程序占用（非 headroom）"
                                   % HEADROOM_PORT)
            if not os.path.exists(HEADROOM_EXE):
                raise RuntimeError("未找到 headroom.exe（%s）\n"
                                   "pip install %s 后重试" % (HEADROOM_EXE, PIP_PKG_SPEC))
            env = dict(os.environ)
            env["ANTHROPIC_TARGET_API_URL"] = HEADROOM_UPSTREAM
            env.update(HEADROOM_ENV_EXTRA)
            if ccr:
                env.pop("HEADROOM_NO_CCR", None)
            mode_env = HEADROOM_MODES.get(mode, {}).get("env") or {}
            env.update(mode_env)
            creationflags = 0x08000000 if os.name == "nt" else 0
            err_path = os.path.join(DATA_DIR, "headroom_stderr.log")
            out_path = os.path.join(DATA_DIR, "headroom_stdout.log")
            os.makedirs(DATA_DIR, exist_ok=True)
            self._err_file = open(err_path, "w", encoding="utf-8", errors="replace")
            self._out_file = open(out_path, "w", encoding="utf-8", errors="replace")
            self.proc = subprocess.Popen(
                [HEADROOM_EXE, "proxy", "--port", str(HEADROOM_PORT)],
                env=env, creationflags=creationflags,
                stdout=self._out_file, stderr=self._err_file)
            log.info("headroom 已拉起 pid=%s 模式=%s 上游=%s",
                     self.proc.pid, mode, HEADROOM_UPSTREAM)

    def startup_error(self):
        """读 stderr 尾部（启动失败诊断，前端展示）。"""
        try:
            with open(os.path.join(DATA_DIR, "headroom_stderr.log"),
                      encoding="utf-8", errors="replace") as f:
                return "\n".join(f.read().splitlines()[-12:])
        except OSError:
            return ""

    def stats(self):
        """拉 headroom /stats 拿压缩统计（GUI:677-690 平移）。
        返回 dict 或 None（不在线/超时），字段随 headroom 版本差异由调用方 .get 兜底。"""
        if not self.running:
            return None
        try:
            import urllib.request
            r = urllib.request.urlopen(
                "http://127.0.0.1:%d/stats" % HEADROOM_PORT, timeout=2)
            return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def stop(self):
        with self._lock:
            if self.proc is None:
                return
            proc, self.proc = self.proc, None
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for f in (self._err_file, self._out_file):
            try:
                if f:
                    f.close()
            except Exception:
                pass
        self._err_file = self._out_file = None
        log.info("headroom 子进程已停止")


# ---- LanzQuotaWorker（GUI:3371-3544 平移；emit → 直写模块缓存）--------
class LanzQuotaWorker:
    """额度查询 daemon 线程。emit(kind,payload) 直写模块级缓存
    _quota_state（前端轮询 /api/proxy/status 读走），无 tkinter。"""

    REFRESH_INTERVAL = 600
    LOGIN_RETRY_WAIT = 60

    def __init__(self, emit):
        self._emit = emit
        self._cred = None
        self._auto = True
        self._login_failed = False
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def submit_credentials(self, user, pwd):
        with self._lock:
            self._cred = (user, pwd)
        self._wake.set()

    def clear_credentials(self):
        with self._lock:
            self._cred = None
            self._login_failed = False
        self._wake.set()

    def refresh_now(self):
        with self._lock:
            if self._cred is None:
                return False
        self._wake.set()
        return True

    def force_relogin(self):
        """强制重登：丢旧 client（连旧 session cookie 一起），下轮循环换新
        client 全新登录。多天不用后 session 过期且 _ensure_login 的单次
        重试救不回来时用（用户实测场景）。代理链路零触碰——只动额度查询。"""
        with self._lock:
            if self._cred is None:
                return False
            self._login_failed = False
        self._cur_cred_epoch = (getattr(self, "_cur_cred_epoch", 0) + 1)
        self._wake.set()
        return True

    def set_auto(self, on):
        """自动刷新开关（GUI checkbox 同款）。"""
        with self._lock:
            self._auto = bool(on)
        if on:
            self._wake.set()   # 开启时唤醒，避免卡在 wait(None)

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _run(self):
        client = None
        cur_cred = object()
        cur_epoch = 0
        while not self._stop.is_set():
            try:
                with self._lock:
                    cred, auto = self._cred, self._auto
                if cred is None:
                    self._wake.wait(5)
                    self._wake.clear()
                    continue
                epoch = getattr(self, "_cur_cred_epoch", 0)
                if cred != cur_cred or epoch != cur_epoch:
                    # 换凭据或 force_relogin（epoch++）：换新 client 丢旧 session
                    client = lanz_quota.LanzClient(*cred)
                    cur_cred = cred
                    cur_epoch = epoch
                if not self._ensure_login(client, cred):
                    self._wake.wait(self.LOGIN_RETRY_WAIT)
                    self._wake.clear()
                    continue
                self._fetch_all(client, cred)
                self._wake.clear()
                if self._stop.is_set():
                    break
                self._wake.wait(self.REFRESH_INTERVAL if auto else None)
            except Exception:
                log.exception("LanzQuotaWorker _run 循环异常，继续运行")

    def _cred_changed(self, cred):
        with self._lock:
            return self._cred != cred

    def _ensure_login(self, client, cred):
        if client.logged_in:
            return True
        self._emit("login_start", None)
        try:
            client.login()
            if self._cred_changed(cred):
                return False
            with self._lock:
                self._login_failed = False
            self._emit("login_ok", cred[0])
            return True
        except lanz_quota.LanzAuthError as e:
            with self._lock:
                self._login_failed = True
            if not self._cred_changed(cred):
                self._emit("login_err", str(e))
            return False
        except lanz_quota.LanzNetworkError as e:
            with self._lock:
                self._login_failed = True
            if not self._cred_changed(cred):
                self._emit("login_err", "网络错误（需内网/VPN）: %s" % e)
            return False
        except lanz_quota.LanzError as e:
            with self._lock:
                self._login_failed = True
            if not self._cred_changed(cred):
                self._emit("login_err", "登录失败: %s" % e)
            return False

    def _fetch_all(self, client, cred=None):
        for attempt in (1, 2):
            try:
                dash = client.get_dashboard()
                budget = None
                try:
                    budget = client.get_budget_overview()
                except lanz_quota.LanzError:
                    pass
                if cred is not None and self._cred_changed(cred):
                    return
                self._emit("data", {"dashboard": dash, "budget": budget,
                                    "ts": time.time()})
                return
            except lanz_quota.LanzSessionExpired:
                if attempt == 1:
                    try:
                        client.login(force=True)
                        continue
                    except lanz_quota.LanzError as e:
                        if cred is None or not self._cred_changed(cred):
                            self._emit("fetch_err", "会话过期且重新登录失败: %s" % e)
                        return
                if cred is None or not self._cred_changed(cred):
                    self._emit("fetch_err", "会话过期")
                return
            except lanz_quota.LanzNetworkError as e:
                if cred is None or not self._cred_changed(cred):
                    self._emit("fetch_err", "网络错误: %s" % e)
                return
            except lanz_quota.LanzError as e:
                if cred is None or not self._cred_changed(cred):
                    self._emit("fetch_err", "查询失败: %s" % e)
                return


# ==== 模块级单例与状态（仿 tftp.py `_tftp` 模式）========================
_bmgr = BaseUrlManager()
_ctl = ProxyController()
_hr = HeadroomController()
_quota_state = {}       # {"kind":..., "payload":..., "ts":...} 最新一次 emit（msg 提示用）
_quota_login = None     # 登录态独立槽 {"state": online/logging/error/fetch_err, "user":...}
                         # （与 _quota_state 分槽：data 事件不再覆盖登录态——
                         # 用户实锤合槽后前端永远显示「登录中」）
_quota_ov = {}           # dashboard.overview 缓存（托盘菜单/tooltip 用）
_quota_rank = []         # dashboard.modelRank 缓存（模型用量排名表）
_quota_ts = None         # 上次 data 时间戳（前端显示"上次刷新 Ns 前"）
_quota_lock = threading.Lock()
_quota = None            # LanzQuotaWorker（HAS_LANZ 且凭据存在时才建）
_cred_cache = None       # 凭据磁盘缓存（save/clear 时刷新；status 1s 轮询
                         # 不再每秒 load_credentials 读盘+JSON 解析）
_cred_cached = False     # 缓存是否已初始化（None=无凭据 也是合法值）

_autoswitched = False    # 工具自动改过 base_url → 退出时回滚直连
_hr_switching = False
_headroom_mode = None    # 当前压缩模式（init 时从记忆文件读）
_ccr = False
_tray_tip_thread = None
_tip_stop = threading.Event()
_shutdown_done = False
_hr_stats_cache = None        # headroom /stats 最近一次结果（5s 缓存线程写，
                              # status 1s 轮询只读——/stats 拉取 2s 超时不能同步做）
_hr_stats_ts = 0.0


def _hr_stats_loop():
    """headroom 压缩统计缓存线程：headroom 模式在（非 off）就 5s 拉 /stats
    （GUI _refresh_headroom 平移，但这里是后台循环天然防堆积，不会像 GUI 每秒探测）。
    条件不绑 _ctl.running：headroom 可独立于自家重试代理在线（端口 37349 被
    外部实例占、或 headroom 复用外部实例）——绑死则 stats 永远 null，
    面板卡「stats 拉取中/失败」（用户实锤）。_hr.stats() 内部自判 running。"""
    global _hr_stats_cache, _hr_stats_ts
    while not _tip_stop.is_set():
        try:
            if _headroom_mode != "off":
                _hr_stats_cache = _hr.stats()
                _hr_stats_ts = time.time()
            else:
                _hr_stats_cache = None
        except Exception:
            pass
        _tip_stop.wait(5)


def _ensure_hr_stats_thread():
    t = threading.Thread(target=_hr_stats_loop, daemon=True)
    t.start()
    return t


def _quota_emit(kind, payload):
    """LanzQuotaWorker emit 回调：直写模块缓存（前端轮询 status 读走，
    托盘菜单动态行读 _quota_ov）。GUI 版是 root.after 派发 tkinter，这里无 GUI。

    登录状态与最新事件分槽存（用户实锤过合槽 bug：data 事件覆盖 login_ok
    后前端永远显示「登录中」）——_quota_login 独立记登录态，只被
    login_ok/login_err/fetch_err/断开 翻转；_quota_state 只给 msg 类提示。"""
    global _quota_ov, _quota_rank, _quota_ts, _quota_login
    with _quota_lock:
        _quota_state["kind"] = kind
        _quota_state["payload"] = payload
        _quota_state["ts"] = time.time()
        if kind == "login_start":
            _quota_login = {"state": "logging", "user": _quota_login and _quota_login.get("user")}
        elif kind == "login_ok":
            _quota_login = {"state": "online", "user": payload}
        elif kind == "login_err":
            _quota_login = {"state": "error", "user": None,
                            "msg": str(payload or "登录失败")}
        elif kind == "fetch_err":
            # 查询失败可能意味着会话失效——「在线」是误导（GUI 同款降级）
            _quota_login = {"state": "fetch_err", "user": _quota_login.get("user") if _quota_login else None,
                            "msg": str(payload or "查询失败")}
        elif kind == "data" and isinstance(payload, dict):
            dash = payload.get("dashboard") or {}
            ov = dash.get("overview") or {}
            if ov:
                _quota_ov = ov
            # 模型用量排名（GUI modelRank 表：模型/tokens/费用/积分/请求数）
            rank = dash.get("modelRank") or []
            if rank:
                _quota_rank = rank
            _quota_ts = payload.get("ts")
            # data 到了说明登录成功：兜底恢复（GUI _render_quota_data 同款，
            # 防 login_ok 事件被面板未打开时错过导致卡「登录中」）
            if not _quota_login or _quota_login.get("state") != "online":
                user = None
                try:
                    cred = _get_credentials()
                    user = (cred or {}).get("username")
                except Exception:
                    pass
                _quota_login = {"state": "online", "user": user}


def _get_credentials():
    """凭据读缓存：首次读盘，之后走内存；save/clear 时 _invalidate_cred_cache
    刷新。status 路由 1s 被前端轮询，不能每次读盘。"""
    global _cred_cache, _cred_cached
    if not _cred_cached:
        _cred_cache = lanz_quota.load_credentials(LANZ_CRED_PATH) if HAS_LANZ else None
        _cred_cached = True
    return _cred_cache


def _invalidate_cred_cache(cred):
    """save/clear 后直接写新值（免得下轮 status 又读一次盘）。"""
    global _cred_cache, _cred_cached
    _cred_cache = cred
    _cred_cached = True


def _ensure_quota_worker():
    """有凭据才建 worker（懒建，daemon 线程自动开跑）。"""
    global _quota
    if not HAS_LANZ or _quota is not None:
        return
    cred = _get_credentials()
    if cred:
        _quota = LanzQuotaWorker(_quota_emit)
        _quota.submit_credentials(cred["username"], cred["password"])
    else:
        # 无凭据也建 worker（等 POST /credentials 唤醒），但只建一次
        _quota = LanzQuotaWorker(_quota_emit)


# ---- 启停/模式核心操作（GUI _on_toggle/_set_mode/_apply_hr_mode 平移）--
def _wait_headroom_ready(timeout=HEADROOM_READY_TIMEOUT):
    """等 headroom /livez 就绪（GUI:2622-2641 原样）。Popen 返回≠可服务。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = _hr.proc_snapshot()
        if proc is not None and proc.poll() is not None:
            raise RuntimeError("headroom 子进程启动即退出 (code=%s)\n%s"
                               % (proc.returncode, _hr.startup_error()))
        if _hr.ping_existing():
            log.info("headroom 已就绪 :%d", HEADROOM_PORT)
            return
        time.sleep(0.5)
    raise RuntimeError("headroom %ds 内未就绪\n%s" % (timeout, _hr.startup_error()))


def _proxy_mode_url():
    """代理模式目标 base_url：off→37349 直连重试代理；压缩在跑→8787（GUI:2694）。"""
    if _headroom_mode == "off" or not _hr.ping_existing():
        return RETRY_URL
    return PROXY_URL


def start_proxy():
    """启动重试代理 + headroom（按模式）+ 切 base_url（GUI _on_toggle 平移）。
    headroom 冷启动慢 → 后台线程等就绪再补切 8787，期间先切 37349 会话不中断。
    返回 (ok, msg)。"""
    global _autoswitched, _hr_switching
    if _ctl.running:
        return True, "已在运行"
    if _ctl.port_in_use():
        if _ctl.ping_existing():
            return False, "already_running"   # 外部自家实例在跑（前端降级展示，复用不杀）
        return False, "端口 %d 被其他程序占用，无法启动" % LISTEN_PORT
    try:
        _ctl.start()
    except RuntimeError as e:
        return False, str(e)
    _hr_switching = True

    def _worker():
        global _hr_switching
        try:
            # 先切 37349 直连（不等 headroom，会话立即可用）
            target = RETRY_URL
            cur = _bmgr.read_current_url()
            if cur != target:
                _bmgr.apply(target)
                _autoswitched = True
            if _headroom_mode != "off":
                try:
                    _hr.start(_headroom_mode, ccr=_ccr)
                    _wait_headroom_ready()
                    if _bmgr.read_current_url() != PROXY_URL:
                        _bmgr.apply(PROXY_URL)
                        _autoswitched = True
                except Exception as e:   # 失败不回滚重试代理，无压缩继续跑
                    log.warning("headroom 启动失败，继续无压缩运行: %s", e)
        finally:
            _hr_switching = False
    threading.Thread(target=_worker, daemon=True).start()
    _ensure_tray()
    return True, "启动中（headroom 冷启动可达 10-30s）"


def stop_proxy():
    """停止代理（GUI stop_proxy 平移）：headroom + 重试代理一起停，
    base_url 还指着自家代理（37349/8787）就一律切回直连——含手动
    「切换为代理模式」的路径（用户实锤：点停止的同时应切直连，
    之前只在 _autoswitched 时回滚，手动切过代理模式的会停在死端口）。
    幂等。"""
    global _autoswitched
    _hr.stop()
    _ctl.stop()
    try:
        cur = _bmgr.read_current_url()
        if _autoswitched or cur in (PROXY_URL, RETRY_URL):
            _bmgr.apply(DIRECT_URL)
            log.info("代理停止，base_url 已切回直连（原: %s）", cur)
    except Exception as e:
        log.warning("代理停止后切直连失败: %s", e)
    _autoswitched = False
    return True, "已停止（base_url 已切回直连）"


def set_mode(mode):
    """手动切 base_url（GUI _set_mode 平移）：changed 非空才算用户接管，
    autoswitched=False 退出不回滚。返回 (ok, changed)。"""
    global _autoswitched
    if mode not in ("proxy", "direct"):
        return False, ["未知模式"]
    target = _proxy_mode_url() if mode == "proxy" else DIRECT_URL
    changed, skipped = _bmgr.apply(target)
    if changed:
        _autoswitched = False
    log.info("手动切换 base_url -> %s: %s", target, changed)
    return True, changed


def apply_hr_mode(mode, ccr=None):
    """运行时切压缩模式（GUI _apply_hr_mode/_done 平移）。
    off：停 headroom 同步切 37349；full/light：停旧拉新，后台线程等就绪切 8787，
    失败回退 off 并同步记忆文件。"""
    global _headroom_mode, _hr_switching, _ccr, _autoswitched
    if ccr is not None:
        _ccr = bool(ccr)
        save_ccr(_ccr)
    if mode not in HEADROOM_MODES:
        return False, "未知压缩模式"
    # 原版行为（用户实锤顺序）：headroom 的上游是重试代理，代理没跑时
    # 拉 headroom 无意义 → 只记模式，下次启动代理时自动拉起（托盘路径）。
    # off（关闭压缩）永远立即生效。面板弹窗另有 running 门槛防误点。
    if mode != "off" and not _ctl.running:
        _headroom_mode = mode
        save_headroom_mode(mode, remember=True)
        log.info("压缩模式 -> %s（代理未运行，下次启动生效）", mode)
        return True, "已记住，下次启动代理时生效"
    if _hr_switching:
        return False, "压缩模式切换进行中，请稍候"
    _hr_switching = True

    def _worker():
        global _headroom_mode, _hr_switching, _autoswitched
        try:
            _headroom_mode = mode
            save_headroom_mode(mode, remember=True)
            _hr.stop()
            if mode == "off":
                # 代理在跑才把 base_url 指回 37349；没在跑时只改记忆
                # ——否则 base_url 指向空端口，Claude Code 直接连不上
                if _ctl.running:
                    _bmgr.apply(RETRY_URL)
                    _autoswitched = True
                log.info("压缩模式切换 -> off（headroom 已停%s）",
                         "，直连重试代理" if _ctl.running else "，代理未跑不动 base_url")
                return
            try:
                _hr.start(mode, ccr=_ccr)
                _wait_headroom_ready()
                _bmgr.apply(PROXY_URL)
                _autoswitched = True
                log.info("压缩模式切换 -> %s（base_url -> 8787）", mode)
            except Exception as e:
                # 失败回退 off：记忆与实际运行状态一致（不能让"记住的模式"
                # 与实际脱节，重启后又试图拉起拉不起来的模式）
                _headroom_mode = "off"
                save_headroom_mode("off", remember=True)
                log.warning("切换到 %s 失败，回退直连: %s", mode, e)
                _bmgr.apply(RETRY_URL)
                _autoswitched = True
        finally:
            _hr_switching = False
    threading.Thread(target=_worker, daemon=True).start()
    return True, "切换中"


# ---- 托盘（并入主工具托盘 tray.py，用户定：合成一个，不建第二个 Icon）--
# pystray 的 MenuItem text/checked 传函数 → 每次打开菜单重新求值，
# 因此主托盘构造时一次性并入 Proxy 子菜单，所有动态项（额度行/启停
# 字样/压缩 radio/CCR）零重建成本，未启动时自动显示对应占位。


def _quota_tip_suffix():
    """tooltip 额度前缀（GUI:3343-3368 原样）：未登录/无数据返回空串。"""
    with _quota_lock:
        ov = dict(_quota_ov)
    if not ov:
        return ""
    ext_u = ov.get("externalDailyUsed", 0) or 0
    ext_l = ov.get("externalDailyLimit", 0) or 0
    int_u = ov.get("internalDailyUsed", 0) or 0
    int_l = ov.get("internalDailyLimit", 0) or 0
    qline = "今日 外%s/%s 内%s/%s 请求%s" % (
        _fnum(ext_u), _fnum(ext_l), _fnum(int_u), _fnum(int_l),
        _fnum(ov.get("dailyRequestCount", 0) or 0))
    parts = []
    if ov.get("hasBudget"):
        parts.append("余%.0f" % (ov.get("remainCredit", 0) or 0))
    tot = ov.get("totalCredits", 0) or 0
    r = ov.get("usageRate", 0) or 0
    if r:
        parts.append("耗%.0f(%d%%)" % (tot, round(r * 100)))
    else:
        parts.append("耗%.0f" % tot)
    qline += " " + " ".join(parts)
    return qline


def _tray_quota_items():
    """托盘菜单顶部额度动态行（GUI:2350-2390 平移）。text 传函数 →
    每次右键打开菜单重新求值最新缓存，cb=None 纯展示零网络。
    返回原生菜单描述树（tray.py 原生 Win32 托盘格式）。"""
    def _dyn(fn):
        return ("item", fn, None, {"enabled": False})

    def _sum():
        ov = _quota_ov if HAS_LANZ else None
        if not ov:
            return "额度: 未登录/暂无数据"
        return "今日 外 %s/%s  内 %s/%s" % (
            _fnum(ov.get("externalDailyUsed", 0) or 0),
            _fnum(ov.get("externalDailyLimit", 0) or 0),
            _fnum(ov.get("internalDailyUsed", 0) or 0),
            _fnum(ov.get("internalDailyLimit", 0) or 0))

    def _mk_model(name, ku, kl):
        def _text():
            ov = _quota_ov if HAS_LANZ else None
            if not ov:
                return "%s: -" % name
            u = ov.get(ku, 0) or 0
            l = ov.get(kl, 0) or 0
            remain = max(l - u, 0)
            pct = int(u / l * 100) if l else 0
            return "%s 已用%s 余%s %d%%" % (name, _fnum(u), _fnum(remain), pct)
        return _text

    return [
        _dyn(_sum),
        _dyn(_mk_model("Lanz-Auto", "internalAutoDailyUsed", "internalAutoDailyLimit")),
        _dyn(_mk_model("Lanz-Flash", "internalFlashDailyUsed", "internalFlashDailyLimit")),
        _dyn(_mk_model("Lanz-Medium", "internalMediumDailyUsed", "internalMediumDailyLimit")),
    ]


def tray_menu_items():
    """主托盘右键菜单的 Proxy 段（tray.py 原生 Win32 托盘调用并入）。
    返回原生菜单描述树（("item", text, cb, opts) / ("sep",)），text/checked
    可传函数 → 打开菜单时求值最新状态；未启动时启停行自动降级。
    与 pystray.MenuItem(fn) 签名兼容：函数项被调时收一个 None 参数。"""
    has_headroom = os.path.exists(HEADROOM_EXE)

    def _hr_items():
        # 未启动重试代理时压缩项置灰（headroom 需要 37349 做上游）；
        # 关闭压缩永远可点——用于启动前把记忆里的模式改成 off
        en = has_headroom   # 对齐原工具：装了 headroom 即可选，代理未跑=只记模式下次启动生效
        return [
            ("item", "完整压缩", lambda: apply_hr_mode("full"),
             {"radio": True, "checked": lambda: _headroom_mode == "full",
              "enabled": en}),
            ("item", "轻量压缩", lambda: apply_hr_mode("light"),
             {"radio": True, "checked": lambda: _headroom_mode == "light",
              "enabled": en}),
            ("item", "关闭压缩", lambda: apply_hr_mode("off"),
             {"radio": True, "checked": lambda: _headroom_mode == "off"}),
        ]

    def _toggle_text():
        return "■ 停止 Claude 代理" if _ctl.running else "▶ 启动 Claude 代理"

    def _header_text():
        return ("Claude Proxy [%s]" % _api_status_text()) if _ctl.running \
            else "Claude Proxy（未启动）"

    return [
        ("sep",),
        # Claude Proxy 段头（只读，代理状态随打开刷新）
        ("item", _header_text, None, {"enabled": False}),
        *_tray_quota_items(),
        ("item", _toggle_text,
         lambda: stop_proxy() if _ctl.running else start_proxy(), {}),
        ("item", "切换为代理模式", lambda: set_mode("proxy"), {}),
        ("item", "切换为直连模式", lambda: set_mode("direct"), {}),
        ("item", "压缩模式", None, {"submenu": _hr_items()}),
        ("item", "CCR 流压缩（激进·/compact 可能卡死）",
         lambda: apply_hr_mode(_headroom_mode, ccr=not _ccr),
         {"checked": lambda: _ccr, "enabled": has_headroom and _ctl.running}),
    ]


def _api_status_text():
    """托盘段头状态字（GUI _refresh 四态平移）。"""
    snap = _ctl.snapshot()
    if snap is None:
        return "STOPPED"
    now = time.time()
    retrying = snap["in_flight_retries"] > 0
    recent_overload = (snap["last_overload_ts"] is not None and
                       now - snap["last_overload_ts"] < 2.0)
    last_fail = snap.get("last_fail")
    recent_fail = (last_fail is not None and now - last_fail[0] < 5.0)
    if recent_fail:
        return "FAILED"
    if retrying or recent_overload:
        return "RETRY"
    return "HEALTHY"


def _tray_tip_loop():
    """tooltip 刷新 daemon 线程（GUI:3319-3341 平移）。
    Windows szTip 限 128 字符，额度在前确保完整显示。
    节流 5s 且值不变不写——高频 NIM_MODIFY 会与 Explorer 悬停 tooltip
    查询竞争。代理未启动时线程退出（不占常驻资源），start 时重开。"""
    import src.tray as tray_mod
    last_tip = None
    while not _tip_stop.is_set():
        if not tray_mod.alive():
            time.sleep(2)   # 主托盘还没建（用户没最小化过）：低频等待
            last_tip = None
            continue
        try:
            snap = _ctl.snapshot()
            qs = _quota_tip_suffix()
            if snap is None:
                tip = qs if qs else "前端控制台"
                tip += "\nClaude Proxy 未启动"
            else:
                now = time.time()
                retrying = snap["in_flight_retries"] > 0
                recent_overload = (snap["last_overload_ts"] is not None and
                                   now - snap["last_overload_ts"] < 2.0)
                last_fail = snap.get("last_fail")
                recent_fail = (last_fail is not None and now - last_fail[0] < 5.0)
                if recent_fail:
                    st = "FAILED"
                elif retrying or recent_overload:
                    st = "RETRY"
                else:
                    st = "HEALTHY"
                tip = qs if qs else "Claude Proxy [%s]" % st
                tip += "\n429/5xx %s 重试 %s 失败 %s" % (
                    _fnum(snap["total_overloads"]),
                    _fnum(snap["total_retries"]),
                    _fnum(snap.get("total_giveups", 0) + snap.get("total_client_gone", 0)))
                tip += "\n免费 %s 收费 %s 运行 %s" % (
                    _fnum(snap.get("free_requests", 0)),
                    _fnum(snap.get("fee_requests", 0)),
                    core.fmt_uptime(snap["uptime_seconds"]))
            if tip != last_tip:
                tray_mod.set_tip(tip)
                last_tip = tip
        except Exception:
            pass
        time.sleep(5)


def _ensure_tray():
    """启动代理时开 tooltip 刷新线程（主托盘由 tray.py 管理，这里只写 title）。"""
    global _tray_tip_thread
    if _tray_tip_thread is not None and _tray_tip_thread.is_alive():
        return
    _tip_stop.clear()
    _tray_tip_thread = threading.Thread(target=_tray_tip_loop, daemon=True)
    _tray_tip_thread.start()
    log.info("proxy tooltip 刷新线程已启动")


def _quota_model_rows(ov):
    """三模型明细行（GUI _model_tile 数据平移，前端渲染用）。"""
    rows = []
    for name, ku, kl in (
        ("Lanz-Auto", "internalAutoDailyUsed", "internalAutoDailyLimit"),
        ("Lanz-Flash", "internalFlashDailyUsed", "internalFlashDailyLimit"),
        ("Lanz-Medium", "internalMediumDailyUsed", "internalMediumDailyLimit")):
        u = ov.get(ku, 0) or 0
        l = ov.get(kl, 0) or 0
        rows.append({"name": name, "used": u, "limit": l,
                     "remain": max(l - u, 0),
                     "pct": int(u / l * 100) if l else 0})
    return rows


# ---- 模块生命周期 -------------------------------------------------------
def proxy_module_init():
    """server.py start_background 时调（不自动启动代理——按需启动）：
    读记忆的压缩模式/CCR；启动自愈；建额度 worker。"""
    global _headroom_mode, _ccr
    m = load_headroom_mode()
    _headroom_mode = m if m else "light"   # 无记忆默认 light（省内存版）
    _ccr = load_ccr()
    # ---- 启动自愈（GUI:2489-2507 平移）----
    # 上次被任务管理器杀/崩溃，_quit 没执行 → base_url 卡代理地址，
    # Claude Code 连不上。发现指向代理但代理没在跑，先切回直连。
    try:
        cur = _bmgr.read_current_url()
        if cur in (PROXY_URL, RETRY_URL) and not (
                _ctl.ping_existing() or _hr.ping_existing()):
            changed, _ = _bmgr.apply(DIRECT_URL)
            log.info("启动自愈: base_url 指向代理但未运行，已切回直连: %s", changed)
    except Exception as e:
        log.warning("启动自愈检查失败: %s", e)
    # 额度 worker（有凭据自动登录；无凭据建了等 POST 唤醒）
    _ensure_quota_worker()
    # headroom /stats 缓存线程（代理运行时 5s 拉，status 只读缓存）
    _ensure_hr_stats_thread()
    # atexit 兜底回滚（Ctrl-C/强杀等 proxy_shutdown 没走的路径）
    atexit.register(_atexit_rollback)


def _atexit_rollback():
    """atexit 兜底：进程退出时若 base_url 还指着自家代理 → 回直连。"""
    try:
        cur = _bmgr.read_current_url()
        if cur in (PROXY_URL, RETRY_URL):
            if not (_ctl.ping_existing() or _hr.ping_existing()):
                _bmgr.apply(DIRECT_URL)
                log.info("atexit 兜底: 已切回直连")
    except Exception:
        pass


def proxy_shutdown(force_rollback=False):
    """真退出链（main.py _do_real_cleanup 调，幂等）：
    停额度 worker → 停 tooltip 线程 → headroom → 重试代理 → base_url 回滚。
    （托盘是主工具 tray.py 的，quit_tray 由 main.py 退出链自己管。）"""
    global _shutdown_done, _autoswitched
    if _shutdown_done:
        return
    _shutdown_done = True
    _tip_stop.set()
    try:
        if _quota is not None:
            _quota.stop()
    except Exception:
        pass
    try:
        _hr.stop()
        # 同步停 server（阻塞 ~0.2s 确保端口释放）
        srv = _ctl.server
        ev = _ctl.stop_event
        if srv is not None and ev is not None and not ev.is_set():
            _ctl.server = None
            _ctl.stop_event = None
            core.stop_server(srv, ev)
        if force_rollback or _autoswitched:
            _bmgr.apply(DIRECT_URL)
            _autoswitched = False
            log.info("退出时已切回直连 (force=%s)" % force_rollback)
    except Exception as e:
        log.error("proxy 退出收尾出错: %s", e)


# ---- Flask 蓝图 ---------------------------------------------------------
proxy_bp = Blueprint("proxy", __name__)


@proxy_bp.route("/api/proxy/status")
def _api_status():
    snap = _ctl.snapshot()
    now = time.time()
    st = "STOPPED"
    if snap is not None:
        retrying = snap["in_flight_retries"] > 0
        recent_overload = (snap["last_overload_ts"] is not None and
                           now - snap["last_overload_ts"] < 2.0)
        last_fail = snap.get("last_fail")
        recent_fail = (last_fail is not None and now - last_fail[0] < 5.0)
        if recent_fail:
            st = "FAILED"
        elif retrying or recent_overload:
            st = "RETRY"
        else:
            st = "HEALTHY"
    with _quota_lock:
        qkind = _quota_state.get("kind")
        qpayload = _quota_state.get("payload")
        qlogin = dict(_quota_login) if _quota_login else None
        ov = dict(_quota_ov)
        rank = list(_quota_rank)
        qts = _quota_ts
    cred = _get_credentials()
    data = {
        "ok": True,
        "running": snap is not None,
        "already_running": (snap is None and _ctl.port_in_use()
                            and _ctl.ping_existing()),
        "port_busy": (snap is None and _ctl.port_in_use()
                      and not _ctl.ping_existing()),
        "status": st,
        "snapshot": snap,
        "base_url": _bmgr.read_current_url(),
        "hr_mode": _headroom_mode,
        "hr_running": _hr.running if _headroom_mode != "off" else False,
        "hr_switching": _hr_switching,
        "ccr": _ccr,
        "headroom_exe": os.path.exists(HEADROOM_EXE),
        "hr_stats": _hr_stats_cache,
        "quota_kind": qkind,
        "quota_payload": qpayload,
        "quota_login": qlogin,
        "quota_user": (qlogin or {}).get("user") if qlogin else None,
        "quota_auto": _quota._auto if _quota is not None else True,
        "has_credentials": cred is not None,
        "quota_username": (cred or {}).get("username"),
        "quota_ts": qts,
    }
    if ov:
        data["quota_overview"] = ov
        data["quota_models"] = _quota_model_rows(ov)
    if rank:
        data["quota_rank"] = rank
    return jsonify(data)


@proxy_bp.route("/api/proxy/start", methods=["POST"])
def _api_start():
    ok, msg = start_proxy()
    return jsonify({"ok": ok, "msg": msg,
                    "already_running": msg == "already_running"})


@proxy_bp.route("/api/proxy/stop", methods=["POST"])
def _api_stop():
    ok, msg = stop_proxy()
    return jsonify({"ok": ok, "msg": msg})


@proxy_bp.route("/api/proxy/mode", methods=["POST"])
def _api_mode():
    j = request.get_json(silent=True) or {}
    ok, changed = set_mode(j.get("mode", ""))
    return jsonify({"ok": ok, "changed": changed})


@proxy_bp.route("/api/proxy/compression", methods=["POST"])
def _api_compression():
    j = request.get_json(silent=True) or {}
    # ccr 缺省 None=不改（apply_hr_mode 内部判），配置弹窗一次带 {mode, ccr} 同改
    ok, msg = apply_hr_mode(j.get("mode", ""), ccr=j.get("ccr"))
    return jsonify({"ok": ok, "msg": msg})


@proxy_bp.route("/api/proxy/ccr", methods=["POST"])
def _api_ccr():
    j = request.get_json(silent=True) or {}
    ok, msg = apply_hr_mode(_headroom_mode, ccr=bool(j.get("on")))
    return jsonify({"ok": ok, "msg": msg})


@proxy_bp.route("/api/proxy/quota", methods=["POST"])
def _api_quota_refresh():
    if not HAS_LANZ or _quota is None:
        return jsonify({"ok": False, "msg": "额度模块不可用（缺 pycryptodome）"})
    j = request.get_json(silent=True) or {}
    if "auto" in j:
        # 自动刷新开关（GUI checkbox 平移）：{auto: bool}
        _quota.set_auto(bool(j.get("auto")))
        return jsonify({"ok": True, "msg": "自动刷新已开启（10min）" if j.get("auto")
                        else "自动刷新已关闭"})
    if j.get("force"):
        # 强制重登：丢旧 session 换新 client 全新登录（多天不用后登录失效的自救）。
        # 只动额度查询，重试代理/headroom 链路零触碰。
        if not _quota.force_relogin():
            return jsonify({"ok": False, "msg": "未配置凭据"})
        return jsonify({"ok": True, "msg": "已触发强制重登（丢弃旧会话，重新登录）"})
    if not _quota.refresh_now():
        return jsonify({"ok": False, "msg": "未配置凭据"})
    return jsonify({"ok": True, "msg": "已触发刷新"})


@proxy_bp.route("/api/proxy/credentials", methods=["POST"])
def _api_credentials():
    j = request.get_json(silent=True) or {}
    action = j.get("action", "save")
    if not HAS_LANZ or _quota is None:
        return jsonify({"ok": False, "msg": "额度模块不可用（缺 pycryptodome）"})
    if action == "clear":
        global _quota_login, _quota_ov, _quota_rank, _quota_ts
        lanz_quota.delete_credentials(LANZ_CRED_PATH)
        _invalidate_cred_cache(None)   # 同步缓存，下轮 status 不再读盘
        _quota.clear_credentials()
        with _quota_lock:
            _quota_login = None
            _quota_ov = {}
            _quota_rank = []
            _quota_ts = None
        return jsonify({"ok": True, "msg": "已断开登录"})
    user = (j.get("username") or "").strip()
    pwd = j.get("password") or ""
    if not user or not pwd:
        return jsonify({"ok": False, "msg": "用户名/密码不能为空"})
    lanz_quota.save_credentials(LANZ_CRED_PATH, user, pwd)
    _invalidate_cred_cache({"username": user, "password": pwd})
    _quota.submit_credentials(user, pwd)
    return jsonify({"ok": True, "msg": "已保存，开始登录"})
