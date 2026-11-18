# -*- coding: utf-8 -*-
"""Claude Proxy 合入模块（原 D:/AI/proxy 独立工具，tkinter 版去 GUI 平移）。

链路：Claude Code → 18788(billion-context 压缩，/bili/ URL 前缀代理) → 37349(重试代理) → lanz.hikvision.com
（a201 前：8787 headroom 压缩，已退役——用户拍板"headroom 实际根本不用了，直接顶掉"）

组件（全部从 claude_proxy_gui_headroom.pyw 平移，去 tkinter）：
- BaseUrlManager     读写 ~/.claude/settings*.json 的 ANTHROPIC_BASE_URL（原子写原样保留）
- ProxyController    重试代理生命周期（core.create_server + daemon 线程）
- BiliController billion-context 压缩层子进程托管（18788；a201 前为 headroom 8787）
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
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request, Response

from src import proxy_core as core
from src import lanz_quota
from src.app_state import BASE_DIR, DATA_DIR

log = logging.getLogger("claude_proxy")


def _notify_mirror(name):
    """a602：数据目录下的凭据/状态小文件落盘后通知 home 镜像（触发式）。"""
    try:
        import src.app_state as _st
        _st.notify_user_file_written(name)
    except Exception:
        pass


def _replace_retry(src, dst):
    """os.replace 带短重试（a602）：备份镜像读文件时 Windows 会短暂占用，
    不能让备份把正常写盘打挂。"""
    try:
        import src.app_state as _st
        _st.replace_retry(src, dst)
    except Exception:
        os.replace(src, dst)

# ---- 常量（GUI:73-233 平移）----
# v2.26 去写死：直连地址/转发上游不再是常量——真源是用户 API 配置的 BASE_URL
# （settings.json env.ANTHROPIC_BASE_URL 的非代理值）。切代理前记忆并持久化到
# proxy_state.json，停止/退出/启动自愈恢复记忆值；代理入口 = 本地端口 + 直连
# 地址的路径（转发路径原样透传，只换 host:port，两边天然对齐）。
# DEFAULT_DIRECT_URL 仅在记忆与当前值都拿不到时兜底。
# v4.0.0-a201：压缩层换代——headroom（headroom-ai，8787）退役，换
# billion-context（bili，模型驱动分层压缩，https://github.com/ranxianglei/
# billion-context，MIT+署名条款：产品须可见标注）。链路不变思路：
# Claude Code → bili(18788，/bili/ URL 前缀代理) → 37349(重试代理) → lanz。
# base_url = PROXY_URL（bili 入口+/bili/+retry 绝对 URL——bili 是 URL 前缀
# 模式，上游编在地址里，不经环境变量）
def _bili_url():
    """bili 入口 base_url：/bili/ 前缀 + 重试代理【完整地址含网关路径】。
    对抗审 a206A P0 实锤（echo 探针实证）：bili 对 /bili/<upstream> 之后
    的路径逐字透传不补前缀——原常量裸写 37349 丢了 /v3/anthropic/model，
    CC 请求会打到 lanz 的 HTML 页（API 全量不可用）。且上游随方案切换可
    变，必须函数化（_retry_url 运行时求值），不能是模块级常量"""
    return "http://127.0.0.1:%d/bili/%s" % (BILI_PORT, _retry_url())
DEFAULT_DIRECT_URL = "http://lanz.hikvision.com/v3/anthropic/model"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 37349

BILI_PORT = 18788
# 外联铁闸（内网部署）：bili 默认每 3 分钟查 npm 自动更新 + advisory 轮询
# （命中缺陷版本会强制安装）——环境变量注入硬关，只跑锁定安装版
BILI_ENV_LOCKDOWN = {"ACP_AUTO_UPDATE": "0", "BILI_ADVISORY_CHECK": "0",
                      "BILI_RELEASE_NOTES_CHECK": "0"}   # 第三轮询器（对抗审 a206A 补）
BILI_READY_TIMEOUT = 90

# 模式：on/off 两档（headroom 的 full/light 档随其退役——bili 阈值体系
# 用默认值：50K 增长软提醒 / 75% 强制压缩 / 95% 紧急截断工具输出）
BILI_MODES = {
    "on":  {"label": "开启压缩（billion-context 分层压缩）", "env": {}},
    "off": {"label": "关闭压缩（bili 不启动）", "env": None},
}
# headroom 时代旧模式文件的迁移映射（full/light→on；旧文件读到即迁移）
_BILI_MODE_FROM_HR = {"full": "on", "light": "on", "off": "off"}

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
BILI_MODE_PATH = os.path.join(CLAUDE_DIR, "bili_mode.json")
_HR_MODE_PATH_LEGACY = os.path.join(CLAUDE_DIR, "headroom_mode.json")
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
        # a238 P2-1（第5轮A3）：apply 全程持 switch_lock（RLock，re_point 重入
        # 安全）——「读文件→改字段→整份 os.replace」与 claude_profiles_apply 的
        # 整份写回交错时，基于旧内容合并的 JSON 会把新方案的 token/模型映射
        # 静默顶回旧值（六处调用点单独加锁不如这一处收口）
        with _switch_lock:
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
                    # 对抗审 a206A P2：base_url 已就位仍要校正 DISABLE_AUTO_
                    # COMPACT（外部工具/手改 settings 丢键时自愈）——原样 continue
                    # 会把缺键永远留在那
                    if isinstance(env, dict):
                        want = "/bili/" in target
                        has = env.get("DISABLE_AUTO_COMPACT") == "1"
                        if want != has:
                            if want:
                                env["DISABLE_AUTO_COMPACT"] = "1"
                            else:
                                env.pop("DISABLE_AUTO_COMPACT", None)
                            tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
                            try:
                                with open(tmp, "w", encoding="utf-8") as f:
                                    json.dump(d, f, indent=2, ensure_ascii=False)
                                    f.write(chr(10))
                                os.replace(tmp, path)
                            except OSError:
                                pass
                    skipped.append(os.path.basename(path))
                    continue
                d.setdefault("env", {})["ANTHROPIC_BASE_URL"] = target
                # bili 独占压缩联动（a201）：base_url 指向 bili（/bili/ 前缀）时写
                # DISABLE_AUTO_COMPACT=1 关掉 Claude Code 自带自动压缩（bili 分层
                # 压缩接管，两者叠加会互相打断前缀缓存）；切走（off/直连/回滚）
                # 自动移除——所有切换路径（start/stop/mode/自愈）都过 apply，单点收口
                if "/bili/" in target:
                    d["env"]["DISABLE_AUTO_COMPACT"] = "1"
                else:
                    d["env"].pop("DISABLE_AUTO_COMPACT", None)
                # P1-7（a116）：tmp 名进程+线程唯一——跨进程并发写同一配置
                # 文件时共用 path+".tmp" 会互相覆盖成半截 JSON
                tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
                for attempt in range(3):
                    try:
                        if attempt > 0:
                            with open(path, encoding="utf-8") as f:
                                d = json.load(f)
                            d.setdefault("env", {})["ANTHROPIC_BASE_URL"] = target
                            if "/bili/" in target:
                                d["env"]["DISABLE_AUTO_COMPACT"] = "1"
                            else:
                                d["env"].pop("DISABLE_AUTO_COMPACT", None)
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(d, f, indent=2, ensure_ascii=False)
                            f.write("\n")
                        os.replace(tmp, path)
                        changed.append("%s: %s -> %s" % (os.path.basename(path), old, target))
                        break
                    except OSError:
                        time.sleep(0.2)
        return changed, skipped


# ---- 直连地址：记忆 / 求值（v2.26 去写死核心）---------------------------
PROXY_STATE_PATH = os.path.join(DATA_DIR, "proxy_state.json")
# 对抗审 a206A P2：8787 保留识别（headroom 时代残留的 base_url 需被
# 自愈/回滚清理，且防 _direct_url 把死 8787 当直连真源毒化记忆）——
# 只作前缀识别，不再监听
_OWN_PROXY_PREFIXES = ("http://127.0.0.1:37349", "http://127.0.0.1:18788",
                       "http://127.0.0.1:8787")


def _is_own_proxy_url(url):
    """base_url 是否指向自家代理入口（37349 重试代理 / 18788 bili）。"""
    return bool(url) and str(url).startswith(_OWN_PROXY_PREFIXES)


_saved_direct = None    # proxy_state.json 的进程内镜像（None=未读过盘）


def _load_saved_direct():
    global _saved_direct
    if _saved_direct is None:
        try:
            with open(PROXY_STATE_PATH, encoding="utf-8") as f:
                u = (json.load(f) or {}).get("direct_url") or None
            if _is_own_proxy_url(u):
                u = None   # 脏数据防御：记忆里存了代理入口会让自愈写回代理地址
            _saved_direct = u
        except (ValueError, OSError):
            _saved_direct = None
    return _saved_direct


def _remember_direct(url):
    """切代理前记忆直连地址（持久化——异常退出后重启仍能恢复真值）。"""
    global _saved_direct
    if not url or _is_own_proxy_url(url):
        return
    _saved_direct = url
    try:
        # 原子写（tmp+replace）：与并发读/方案切换链路同跑时不留半截文件
        tmp = "%s.%d.%d.tmp" % (PROXY_STATE_PATH, os.getpid(),
                                 threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"direct_url": url}, f, ensure_ascii=False, indent=2)
        _replace_retry(tmp, PROXY_STATE_PATH)
        _notify_mirror("proxy_state.json")
    except OSError as e:
        log.warning("记忆直连地址失败: %s", e)


def _profile_direct_url():
    """active 配置方案快照里的 base_url（claude_profiles.json，settings 整份
    快照制）。base_url 卡在代理地址且无 proxy_state 记忆时（旧版切的代理）
    的可靠真源——方案快照是用户显式保存的直连配置，比 DEFAULT 兜底可信。"""
    try:
        p = os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                         "claude_profiles.json")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        name = d.get("active") or ""
        for prof in d.get("profiles") or []:
            if prof.get("name") == name:
                env = (prof.get("settings") or {}).get("env") or {}
                if isinstance(env, dict):
                    return env.get("ANTHROPIC_BASE_URL") or None
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _direct_url():
    """应恢复/展示的直连 base_url，优先级从新到旧：
    ① settings 当前非代理值（最新——覆盖「代理运行中用户改了 BASE_URL」）
    ② proxy_state.json 记忆（切代理前落盘）
    ③ active 配置方案快照的 base_url（①② 都断时的真源，旧版残留场景）
    ④ DEFAULT 兜底（连方案都没有——首次使用）"""
    cur = _bmgr.read_current_url()
    if cur and not _is_own_proxy_url(cur):
        return cur
    u = _load_saved_direct()
    if u:
        return u
    u = _profile_direct_url()
    if u and not _is_own_proxy_url(u):
        return u
    return DEFAULT_DIRECT_URL


def _retry_url():
    """重试代理入口 base_url：本地端口 + 直连地址的路径。
    转发路径原样透传（proxy_core 只换 host:port），因此入口带上同样路径，
    Claude Code 拼出的请求落到上游正好等价于直连时的请求。"""
    return "http://127.0.0.1:%d%s" % (LISTEN_PORT, urlsplit(_direct_url()).path or "/")


def _upstream_of(url):
    """从直连 url 解析转发上游 (host, port, scheme)。"""
    sp = urlsplit(url)
    scheme = (sp.scheme or "http").lower()
    port = sp.port or (443 if scheme == "https" else 80)
    return sp.hostname or urlsplit(DEFAULT_DIRECT_URL).hostname, port, scheme


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
        # 三件套判活：stop() 会整套清空，半残状态只可能来自旧版本/异常路径，
        # 任一缺失都按未启动算（此前 stop_event=None 时这里直接 AttributeError）
        return (self.server is not None and self.stop_event is not None
                and not self.stop_event.is_set())

    def start(self, host=LISTEN_HOST, port=LISTEN_PORT, upstream=None):
        with self._lock:
            if self.running:
                return
            if self.port_in_use(host, port):
                raise RuntimeError("端口 %d 已被占用" % port)
            try:
                server, stats, stop_event = core.create_server(
                    host, port, upstream or _upstream_of(_direct_url()))
            except OSError as e:
                # 绑定失败（被占用/Win 保留端口段/权限）——包装成可读消息，
                # 之前裸 OSError 冒到 Flask 变 500，前端只看得到「请求失败」
                raise RuntimeError(
                    "端口 %d 无法绑定（被占用或被系统保留）: %s" % (port, e))
            self.server, self.stats, self.stop_event = server, stats, stop_event
            self.thread = core.server_thread_start(self.server, self.stop_event)
            log.info("代理已启动 %s:%d -> %s:%s (%s)", host, port,
                     server.upstream_host, server.upstream_port,
                     server.upstream_scheme)

    def stop(self):
        with self._lock:
            srv, ev = self.server, self.stop_event
            # 三件套一起清（此前漏了 stats：停止后 snapshot() 仍拿旧快照，
            # 面板假 HEALTHY/假运行，状态机与 start_proxy 的判定对不上）
            self.server = None
            self.stats = None
            self.stop_event = None
        if srv is None or ev is None:
            return
        t = threading.Thread(target=core.stop_server, args=(srv, ev), daemon=True)
        t.start()
        log.info("代理已停止")

    def snapshot(self):
        if self.stats is None:
            return None
        return self.stats.snapshot(history_limit=500)


# ---- 压缩模式持久化（GUI:468-529 原样）--------------------------------
def load_bili_mode():
    try:
        with open(BILI_MODE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        mode = d.get("mode")
        if mode in BILI_MODES:
            return mode
    except (ValueError, OSError):
        pass
    # headroom 旧模式文件迁移（full/light→on）：读到即落盘新文件（对抗审
    # a206A：原注释称"转存"实际从不落盘——旧文件被清理后迁移来源消失）
    try:
        with open(_HR_MODE_PATH_LEGACY, encoding="utf-8") as f:
            old_mode = (json.load(f) or {}).get("mode")
        if old_mode in _BILI_MODE_FROM_HR:
            new_mode = _BILI_MODE_FROM_HR[old_mode]
            try:
                _write_mode_file({"mode": new_mode})
            except OSError:
                pass
            return new_mode
    except (ValueError, OSError):
        pass
    return None


def load_ccr():
    try:
        with open(BILI_MODE_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("ccr"))
    except (ValueError, OSError):
        return False


def _write_mode_file(updates):
    d = {}
    try:
        with open(BILI_MODE_PATH, encoding="utf-8") as f:
            old = json.load(f)
        if isinstance(old, dict):
            d.update(old)
    except (ValueError, OSError):
        pass
    d.update(updates)
    with open(BILI_MODE_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def save_bili_mode(mode, remember=True):
    try:
        if remember and mode in BILI_MODES:
            _write_mode_file({"mode": mode})
        else:
            try:
                os.remove(BILI_MODE_PATH)
            except OSError:
                pass
    except OSError as e:
        log.warning("保存压缩模式失败: %s", e)


def save_ccr(enabled):
    try:
        _write_mode_file({"ccr": bool(enabled)})
    except OSError as e:
        log.warning("保存 CCR 状态失败: %s", e)


def load_proxy_autostart():
    """a251（用户需求：开启后保存开启状态）：上次代理在跑（记忆 autostart）
    → 本次工具启动自动拉起。与压缩模式同居 BILI_MODE_PATH 一个文件。"""
    try:
        with open(BILI_MODE_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("autostart"))
    except (ValueError, OSError):
        return False


def set_proxy_autostart(on):
    try:
        _write_mode_file({"autostart": bool(on)})
    except OSError as e:
        log.warning("保存代理自启状态失败: %s", e)


# ---- bili 定位（a201 内置方案：offline_runtime/bili 优先，系统兜底）----
# 内置（.fcpk 资源包 kind=bili 释放）：node.exe 便携运行时 + node_modules/
# billion-context 完整依赖树——内网零外联零安装。系统兜底（开发机）：
# PATH node ≥22 + npm 全局包。BILI_NODE/BILI_ENTRY 是启动二元组（路径或
# None），BILI_ERR 为不可用原因（前端展示装机指引）。
# 对抗审 a205R 实锤：释放落点权威是 res_boot.app_dir()（与 res_install.
# runtime_root/res_boot.wv2_fixed_dir 同源）——原写 DATA_DIR/../ 在 frozen
# 布局下错位，内置检测永远落空。延迟 import 防循环（res_boot 仅标准库）
def _bili_runtime_dir():
    from src.res_boot import app_dir
    return os.path.join(app_dir(), "offline_runtime", "bili")
BILI_RUNTIME = _bili_runtime_dir()

def _detect_bili_cmd():
    import shutil, subprocess
    # 1. 内置运行时（.biliok 标记 + 关键文件齐全才算数——半装不认）
    # a336R（第7轮 P1-4）：判据抽到 res_boot.bili_ok，三处共用一份
    from src.res_boot import bili_ok
    node_exe = os.path.join(BILI_RUNTIME, "node.exe")
    entry = os.path.join(BILI_RUNTIME, "node_modules", "billion-context",
                         "dist", "index.js")
    if bili_ok():
        return node_exe, entry, None
    # 2. 系统 node ≥22 + npm 全局 billion-context（开发机兜底）
    try:
        exe = shutil.which("node")
        if exe:
            out = subprocess.run([exe, "--version"], capture_output=True,
                                 text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                 ).stdout.strip().lstrip("v")
            major = int(out.split(".")[0]) if out.split(".")[0].isdigit() else 0
            if major >= 22:
                try:
                    prefix = subprocess.run(["npm", "prefix", "-g"],
                                             capture_output=True, text=True,
                                             timeout=15,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                             ).stdout.strip().splitlines()[-1]
                    g_entry = os.path.join(prefix, "node_modules",
                                           "billion-context", "dist", "index.js")
                    if os.path.isfile(g_entry):
                        return exe, g_entry, None
                    why = "npm 全局未装 billion-context"
                except Exception:
                    why = "npm 检测失败"
            else:
                why = "node %s 过旧（需 ≥22）" % out
        else:
            why = "未找到 node"
    except Exception as e:
        why = "node 检测失败: %s" % e
    return None, None, (
        "billion-context 不可用（%s）。内置方案：用 .fcpk 资源包安装"
        "（含 Node 运行时+依赖全量，内网零外联）；或自装 Node ≥22 后 "
        "npm install -g billion-context" % why)

BILI_NODE, BILI_ENTRY, BILI_ERR = _detect_bili_cmd()


def bili_reprobe():
    """重探 bili 可用性（res_install 装完资源包即调——模块级三元组是一次性
    赋值，不重探则装完仍显示"未安装"需重启工具，对抗审 a206B P2）"""
    global BILI_NODE, BILI_ENTRY, BILI_ERR
    BILI_NODE, BILI_ENTRY, BILI_ERR = _detect_bili_cmd()
    return bool(BILI_NODE and BILI_ENTRY)


# ---- a407：billion-context 唯一安装入口——代理面板联网下载 ----
# 移出默认资源包/安装库后的替代链路：npm 全局装（机器需 Node ≥22 + npm，
# 资源库有 node 安装器；内网无外联时装不上属预期，入口如实报错）。
# 检测链 _detect_bili_cmd ② 天然认 npm 全局装，装完 bili_reprobe 即生效
BILI_NPM_VERSION = "0.1.204"   # 锁定版（0.1.x 高频迭代，不跟 master；随 build.py 迁入）
_bili_inst = {"running": False, "done": False, "ok": False, "err": "", "log": []}


def _bili_install_run():
    import shutil
    import subprocess as _sp
    st = _bili_inst
    try:
        exe = shutil.which("node")
        npm = shutil.which("npm")
        if not (exe and npm):
            st["err"] = "未找到 node/npm——先装 Node.js ≥22（设置→外部依赖安装有安装器），再回来一键装"
            st["log"].append(st["err"])
            return
        out = _sp.run([exe, "--version"], capture_output=True, text=True,
                      timeout=15,
                      creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                      ).stdout.strip().lstrip("v")
        major = int(out.split(".")[0]) if out.split(".")[0].isdigit() else 0
        if major < 22:
            st["err"] = "node %s 过旧（需 ≥22）——资源库 node 安装器升级后重试" % out
            st["log"].append(st["err"])
            return
        pkg = "billion-context@%s" % BILI_NPM_VERSION
        st["log"].append("npm install -g %s …（需联网，约 1-3 分钟）" % pkg)
        r = _sp.run([npm, "install", "-g", pkg], capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=900, creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        tail = ((r.stdout or "") + (r.stderr or "")).strip()
        if tail:
            st["log"].extend(tail.splitlines()[-30:])
        if r.returncode == 0:
            st["ok"] = True
            if bili_reprobe():
                st["log"].append("✓ 安装完成且引擎可用——切「开启压缩」即可启用")
            else:
                st["log"].append("✓ 安装完成（引擎检测待刷新，重启工具后可用）")
        else:
            st["err"] = "npm 安装失败（rc=%d）——检查网络/registry 可达性" % r.returncode
    except Exception as e:
        st["err"] = str(e)[:300]
    finally:
        st["running"] = False
        st["done"] = True


# ---- BiliController（GUI:533-660 平移）----------------------------
class BiliController:
    def __init__(self):
        self.proc = None
        self._err_file = None
        self._out_file = None
        self._lock = threading.Lock()

    @staticmethod
    def port_in_use(port=BILI_PORT):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False

    @staticmethod
    def ping_existing(port=BILI_PORT):
        import urllib.request, urllib.error
        for path in ("/__bili/health", "/__bili/stats"):
            try:
                r = urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (port, path), timeout=1)
                if 200 <= r.status < 300:
                    return True
            except urllib.error.HTTPError as e:
                # 对抗审 a206A P1：headroom 时代 5xx≈活着但坏了；bili 的
                # /__bili/health 启动期正是返 503（starting）——5xx=True 会把
                # 未就绪判成就绪，就绪门形同虚设。bili 语义只认 2xx
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

    def start(self, mode="on"):
        with self._lock:
            if self.running:
                if self.proc is None:
                    log.info("bili: %d 已有实例在跑，复用（不接管）", BILI_PORT)
                return
            if self.port_in_use():
                raise RuntimeError("端口 %d 已被其他程序占用（非 billion-context）"
                                   % BILI_PORT)
            if not BILI_NODE or not BILI_ENTRY:
                raise RuntimeError(BILI_ERR or "未找到 billion-context")
            env = dict(os.environ)
            env.update(BILI_ENV_LOCKDOWN)   # 关 npm 自动更新 + advisory 轮询（内网铁闸）
            creationflags = 0x08000000 if os.name == "nt" else 0
            err_path = os.path.join(DATA_DIR, "bili_stderr.log")
            out_path = os.path.join(DATA_DIR, "bili_stdout.log")
            os.makedirs(DATA_DIR, exist_ok=True)
            self._err_file = open(err_path, "w", encoding="utf-8", errors="replace")
            self._out_file = open(out_path, "w", encoding="utf-8", errors="replace")
            # bili 是 URL 前缀代理：上游编在 base_url 的 /bili/<upstream> 里
            # （PROXY_URL），不经环境变量；--host 显式钉回环
            self.proc = subprocess.Popen(
                [BILI_NODE, BILI_ENTRY, "--host", "127.0.0.1", "--port", str(BILI_PORT)],
                env=env, creationflags=creationflags,
                stdout=self._out_file, stderr=self._err_file)
            log.info("bili 已拉起 pid=%s 模式=%s（上游经 PROXY_URL 前缀）",
                     self.proc.pid, mode)

    def startup_error(self):
        """读 stderr 尾部（启动失败诊断，前端展示）。"""
        try:
            with open(os.path.join(DATA_DIR, "bili_stderr.log"),
                      encoding="utf-8", errors="replace") as f:
                return "\n".join(f.read().splitlines()[-12:])
        except OSError:
            return ""

    def stats(self):
        """拉 bili /__bili/stats 拿压缩统计。
        返回 dict 或 None（不在线/超时），字段随 headroom 版本差异由调用方 .get 兜底。"""
        if not self.running:
            return None
        try:
            import urllib.request
            r = urllib.request.urlopen(
                "http://127.0.0.1:%d/__bili/stats" % BILI_PORT, timeout=2)
            d = json.loads(r.read().decode("utf-8"))
            # 对抗审 a205R+a206A：压缩节省（tokensSaved）不在 /stats——在
            # /__bili/sessions（含历史会话）里。a206A 统一口径：reqs/saved
            # 同源取 /sessions（历史+活），命中率从 /stats 活会话的
            # cached/input 总和算全局比——不再混两个口径在一条统计里
            try:
                r2 = urllib.request.urlopen(
                    "http://127.0.0.1:%d/__bili/sessions" % BILI_PORT, timeout=2)
                j2 = json.loads(r2.read().decode("utf-8"))
                items = j2.get("sessions") if isinstance(j2, dict) else j2
                if isinstance(items, list):
                    d["totals"] = {"tokensSaved": sum(
                        int(x.get("tokensSaved") or 0) for x in items
                        if isinstance(x, dict)),
                        "requests": sum(int(x.get("requests") or 0)
                                        for x in items if isinstance(x, dict))}
            except Exception:
                pass
            try:
                cin = sum(int(x.get("inputTokens") or 0) for x in d.get("sessions") or [])
                cch = sum(int(x.get("cachedTokens") or 0) for x in d.get("sessions") or [])
                if cin > 0:
                    d.setdefault("totals", {})["cacheHitPct"] = round(cch * 100 / cin)
            except Exception:
                pass
            return d
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
        log.info("bili 子进程已停止")


# ---- LanzQuotaWorker（GUI:3371-3544 平移；emit → 直写模块缓存）--------
# a459（审计遗留）：裸 "locked" 会命中 "unlocked"——SSO 解锁成功的提示若拼进
# 异常文案，会被误判成锁定而停登（与 a452 修掉的「警示语误判」同族）。
# locked 的判定挪到 _is_lockout_msg 里先剥 unlocked 再测。
_LOCKOUT_KEYS = ("too many attempts", "error limit")


def _is_lockout_msg(msg):
    """a454/a456：登录失败文案是否是「SSO 账号被锁」而非普通会话失效。

    锁定后每再试一次都会重置 SSO 的锁定计时（用户实锤：1 小时仍未解开，
    因为 600s 一次的退避重登一直在续期）。所以必须在文案层识别出来，
    一旦命中就停登，等用户手动触发。

    a452（审计 P0：判据闭合成环）：原实现里的「锁定」二字是子串匹配，而
    `lanz_quota._classify_nonjson` 的**密码错误**文案自带警示语「注意：
    连续错误会锁定 SSO 账号」——警示语被当成锁定事实，用户密码输错一次
    就永久停登，改对密码也不自愈。所以不能匹配裸「锁定」，必须匹配
    _classify_nonjson **优先级1 那条确定结论**的特征词。

    同理「会话失效 + 重定向」（优先级4）本身是「可能锁定也可能凭据失效」
    的不确定结论，不该当确定锁定处理：它只作为**一次性的**停登理由（避免
    反复撞锁），且 refresh_now / force_relogin / 换凭据都能立刻解除。
    """
    m = str(msg or "").lower()
    # 英文：锁定页/接口返回的原始错误（lanz_quota 会拼进各异常文案）
    if any(k in m for k in _LOCKOUT_KEYS):
        return True
    # a459：先剥 unlocked 再测 locked，防止「账号已解锁」被当锁定停登
    if "locked" in m.replace("unlocked", ""):
        return True
    if "too many" in m and "attempt" in m:
        return True
    # 中文：只认 _classify_nonjson 优先级1 的确定结论。不要匹配裸「锁定」——
    # 密码错误文案里的「会锁定 SSO 账号」是警示语，不是事实。
    if "已被 sso 锁定" in m:
        return True
    # a452（审计）：优先级3 —— 服务端登录页 `<div id="msg">` 若给出中文提示
    # （如「您的账号已被锁定」），_classify_nonjson 不命中英文关键词就落到
    # 「登录失败…服务端提示: …」。必须认带「已」的确定措辞，仍不得恢复裸
    # 「锁定」。注意不能匹配「账号已锁定」——优先级4 兜底文案「可能账号
    # 已锁定或凭据失效」含该子串，那是**不确定**结论，误判成确定锁定就是
    # 上一轮刚修掉的 P0（假锁定卡死一整夜）。
    if "已被锁定" in m:
        return True
    return "尝试次数超限" in m or "次数超限" in m


def _cfg_get_quota_auto():
    """「自动刷新(10min)」：定时拉额度。config.json 的 proxy_quota_auto，
    默认 True。注意这里**只管刷新额度**，不管登录失败后要不要重登——
    自动重登是独立开关 proxy_quota_auto_relogin（a448 用户令：不许混为一谈）。"""
    try:
        from src.app_state import cfg_read
        v = (cfg_read() or {}).get("proxy_quota_auto")
        return True if v is None else bool(v)
    except Exception:
        return True


def _epoch_changed(w, cred, cred_now, cur_epoch):
    """内层负载循环的「换代」判据：凭据变了、或两个 epoch 计数任一变了。

    a452（审计）：`cur_epoch` 是 `(cur_cred_epoch, cred_epoch)` **二元组**，
    原来这里写成 `getattr(self, "_cur_cred_epoch", 0) != cur_epoch`——int 与
    tuple 恒不等 → 内层每轮必 break，600s 的全量刷新被退化成 20s 一次。
    抽成独立函数是为了让测试**直接调真实判据**，而不是在测试里复刻表达式。
    """
    return (cred_now != cred
            or cur_epoch[0] != getattr(w, "_cur_cred_epoch", 0)
            or cur_epoch[1] != w._cred_epoch)


def _cfg_get_auto_relogin():
    """a448：自动重登独立开关。config.json 的 proxy_quota_auto_relogin，
    默认 True（用户令：默认开启，可手动关闭）。"""
    try:
        from src.app_state import cfg_read
        v = (cfg_read() or {}).get("proxy_quota_auto_relogin")
        return True if v is None else bool(v)
    except Exception:
        return True


def _cfg_set_auto_relogin(on):
    try:
        from src.app_state import cfg_commit
        ok, _err = cfg_commit(
            lambda d: d.__setitem__("proxy_quota_auto_relogin", bool(on)))
        return ok
    except Exception:
        return False


def _cfg_set_quota_auto(on):
    try:
        from src.app_state import cfg_commit
        ok, _err = cfg_commit(lambda d: d.__setitem__("proxy_quota_auto", bool(on)))
        return ok
    except Exception:
        return False


class LanzQuotaWorker:
    """额度查询 daemon 线程。emit(kind,payload) 直写模块级缓存
    _quota_state（前端轮询 /api/proxy/status 读走），无 tkinter。"""

    REFRESH_INTERVAL = 600
    LOGIN_RETRY_WAIT = 60

    def __init__(self, emit):
        self._emit = emit
        self._cred = None
        self._auto = _cfg_get_quota_auto()   # 自动刷新(10min)：拉额度
        self._auto_relogin = _cfg_get_auto_relogin()   # a448：自动重登（独立）
        self._login_failed = False
        self._login_err = ""
        self._locked = False                 # a454：SSO 锁定 → 停登等手动
        self._cred_epoch = 0                 # a452：凭据提交计数（同值重提也能唤醒）
        self._refresh_req = False            # a452：手动刷新请求（唤醒后必须拉一次全量）
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def submit_credentials(self, user, pwd):
        with self._lock:
            self._cred = (user, pwd)
            # a452（审计 P2）：只比较凭据值时，用户把**同一组**账号密码再提交
            # 一次无法跳出锁定停登循环（元组相等），界面一直停在锁定态。用
            # epoch 给「提交动作」本身发信号。
            self._cred_epoch += 1
            # a452（审计 P1）：换账号/改密码要清掉上一个账号的锁定态，
            # 否则账号 A 被锁的 _locked/_login_err 会传给账号 B。
            self._locked = False
            self._login_err = ""
        self._wake.set()

    def clear_credentials(self):
        with self._lock:
            self._cred = None
            self._login_failed = False
            self._locked = False      # a452：登出必须清锁定态
            self._login_err = ""
            self._cred_epoch += 1
        self._wake.set()

    def refresh_now(self):
        """手动刷新。a454：同时解除锁定停登——用户手动点了就是要再试一次，
        这是解锁后唯一的主动出口（自动重登已被锁定拦住）。
        a452（审计 P1：点刷新对额度无效）：原实现只 _wake.set()，而内层循环
        醒来先判 `now - last_full >= 600` 未到期就跳过，手动刷新等于没刷。
        加一次性标志，内层消费后必拉一次全量。"""
        with self._lock:
            if self._cred is None:
                return False
            self._locked = False
            self._refresh_req = True
        self._wake.set()
        return True

    def force_relogin(self):
        """强制重登：丢旧 client（连旧 session cookie 一起），下轮循环换新
        client 全新登录。多天不用后 session 过期且 _ensure_login 的单次
        重试救不回来时用（用户实测场景）。代理链路零触碰——只动额度查询。
        a454：同样解除锁定停登（这是用户说的「我登一次就好了」的出口）。"""
        with self._lock:
            if self._cred is None:
                return False
            self._login_failed = False
            self._locked = False
        self._cur_cred_epoch = (getattr(self, "_cur_cred_epoch", 0) + 1)
        self._wake.set()
        return True

    def set_auto(self, on):
        """自动刷新开关：只管「每 10 分钟拉额度」。a454 落 config.json，
        否则控制台一重启就又开回来（用户实锤：关了也没用）。
        a448：**不再**在这里解除锁定——刷新与重登是两件事，锁定停登只由
        set_auto_relogin(True)/手动刷新/强制重登解除。"""
        with self._lock:
            self._auto = bool(on)
        _cfg_set_quota_auto(bool(on))
        if on:
            self._wake.set()   # 开启时唤醒，避免卡在 wait(None)

    def set_auto_relogin(self, on):
        """a448：自动重登独立开关（用户令：不许复用「自动刷新」开关）。
        开启＝登录失败时按退避自动重登；关闭＝只等用户手动刷新/强制重登。
        默认开启（config.json 缺省即 True）。"""
        with self._lock:
            self._auto_relogin = bool(on)
            if on:
                self._locked = False   # 重新允许自动重登＝解除停登
        _cfg_set_auto_relogin(bool(on))
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    @staticmethod
    def _push_relogin(stamps, ts, window=1800, limit=3):
        """a559：重登滑窗维护（纯函数，tests 直测）。

        返回 (new_stamps, tripped)。窗口内第 limit 次重登 → tripped
        （会话被另一处登录反复互踢——每次重登都是真实 SSO 登录，
        次数失控即锁号，视同锁定停登）。"""
        new = [t for t in stamps if ts - t < window] + [ts]
        return ([], True) if len(new) >= limit else (new, False)

    def _locked_wait(self, cred, epoch_of_cred):
        """a454/a559/a561：锁定/熔断停登等待。

        手动解锁（清 _locked）/换凭据/换代唤醒；熔断带冷却时间戳的，
        冷却到期（30 分钟）自动恢复——进程重启型风暴的跨进程熔断不能
        只靠手动。"""
        while not self._stop.is_set():
            with self._lock:
                if not self._locked or self._cred != cred:
                    return
                if self._cred_epoch != epoch_of_cred:
                    return
                trip = getattr(self, "_trip_ts", 0.0)
            if trip and time.time() - trip >= 1800:
                with self._lock:
                    self._locked = False
                    self._trip_ts = 0.0
                _save_marks([], 0.0)
                log.info("SSO 熔断冷却到期，自动恢复")
                return
            self._wake.wait(5)
            self._wake.clear()

    def _run(self):
        client = None
        cur_cred = object()
        cur_epoch = 0
        epoch_of_cred = 0
        fail_n = 0
        cur_done = 0.0          # a559：最近一次已见的登录成功时刻
        # a559：30 分钟滑窗内的重登成功时刻（被踢熔断）；
        # a561 F5：初值改从盘上跨进程标记恢复，熔断冷却期内直接停登
        login_ok_ts, trip_ts = _load_marks()
        self._trip_ts = trip_ts
        if trip_ts and time.time() - trip_ts < 1800:
            with self._lock:
                self._locked = True
                self._login_err = (
                    "SSO 登录过频熔断冷却中（至 %s）——近期有登录风暴或"
                    "进程重启循环；冷却到期自动恢复，或手动刷新提前解锁"
                    % time.strftime("%H:%M", time.localtime(trip_ts + 1800)))
            self._emit("login_locked", self._login_err)
            # epoch_of_cred=0（初始值）：等冷却到期/手动解锁/凭据提交
            self._locked_wait(None, 0)
        while not self._stop.is_set():
            try:
                with self._lock:
                    cred, auto = self._cred, self._auto
                    auto_relogin = self._auto_relogin
                if cred is None:
                    self._wake.wait(5)
                    self._wake.clear()
                    continue
                # a452：凭据「提交动作」也算换代信号——用户把同一组账号密码
                # 再提交一次时 cred 元组相等，只比值得不到任何变化，会卡在
                # 锁定停登循环里出不来。把 _cred_epoch 并入 epoch。
                with self._lock:
                    epoch = (getattr(self, "_cur_cred_epoch", 0),
                             self._cred_epoch)
                if cred != cur_cred or epoch != cur_epoch:
                    # 换凭据或 force_relogin（epoch++）：换新 client 丢旧 session
                    client = lanz_quota.LanzClient(*cred)
                    cur_cred = cred
                    cur_epoch = epoch
                    # a452（审计实锤：cur_epoch 是元组，下面却拿 int 比，
                    # 恒不等 → 内层每轮必 break，600s 全量刷新退化成 20s）。
                    # 复用同一份快照，不要二次读共享字段。
                    epoch_of_cred = epoch[1]
                    fail_n = 0
                    # a561 审计 F4：换账号不背旧账号的滑窗/熔断
                    login_ok_ts = []
                    self._trip_ts = 0.0
                    _save_marks([], 0.0)
                if not self._ensure_login(client, cred):
                    self._clear_loads("登录失败，模型负载暂不可用")
                    with self._lock:
                        locked = self._locked
                        locked_err = self._login_err
                    if locked:
                        # a454（用户实锤：1 小时都没解锁）：锁定期间**不再
                        # 自动重登**。每次尝试都会重置 SSO 的锁定计时，600s
                        # 一次的退避重登等于让锁定永久续期。停在这里，只等
                        # 用户手动刷新/强制重登（它们会清 _locked）或换凭据。
                        self._emit("login_locked", locked_err)
                        self._locked_wait(cred, epoch_of_cred)
                        continue
                    # a446：SSO 连续失败会锁号（实测 "Too many attempts"）。
                    # 固定 60s 重试等于持续敲锁定账号，改指数退避 60→120→
                    # 300→600s 封顶；成功一次即归零。
                    fail_n += 1
                    wait = min(self.LOGIN_RETRY_WAIT * (2 ** min(fail_n - 1, 4)), 600)
                    # a448：是否自动重登看**独立开关** _auto_relogin，
                    # 与「自动刷新(拉额度)」解耦（用户令：不许混为一谈）
                    if not auto_relogin:
                        self._wake.wait(None)
                    else:
                        self._wake.wait(wait)
                    self._wake.clear()
                    continue
                fail_n = 0
                # a559 铁律（用户令：在线就不许反复登录）：新登录成功时刻
                # 变化才计数——30 分钟内第 3 次「重新登录成功」= 会话被
                # 另一处登录反复互踢（每次都是真实 SSO 登录，次数失控即
                # 锁号）。视同锁定停登，等用户确认单一登录处后手动刷新。
                done_ts = getattr(self, "_login_done_ts", 0.0)
                if done_ts != cur_done:
                    prev_done = cur_done
                    cur_done = done_ts
                    # a561 审计 F2：仅「距上次登录 <15 分钟」的重登计为被踢
                    # 嫌疑——自然过期型重登（会话存活长）不计数，服务端会话
                    # TTL ≥15 分钟时永不误熔断
                    if prev_done and done_ts - prev_done < 900:
                        login_ok_ts, tripped = self._push_relogin(login_ok_ts,
                                                                  done_ts)
                        _save_marks(login_ok_ts, 0.0)
                        if tripped:
                            self._trip_ts = time.time()
                            _save_marks([], self._trip_ts)   # F5：落盘跨进程
                            with self._lock:
                                self._locked = True
                                self._login_err = (
                                    "检测到 SSO 会话被反复踢（30 分钟内第 3 次"
                                    "重登成功——另一台机器/实例在用同一账号？）。"
                                    "已停止自动重登（30 分钟后自动恢复，或手动"
                                    "点刷新提前解锁；若服务端会话有效期本就短，"
                                    "也会触发本保护）")
                            login_ok_ts = []
                            self._emit("login_locked", self._login_err)
                            self._locked_wait(cred, epoch_of_cred)
                            continue
                # a446（严重回归修复）：负载查询必须复用**这一个** client。
                # 原先 _get_model_loads 自己 new LanzClient 并每 20s 登录一次，
                # 同一 SSO 账号两个会话互相踢——worker 刚登录就被踢回 SSO
                # 登录页，表现为「一直登录失败」，还会触发风控锁号。
                # a446（严重回归修复）：负载查询必须复用**这一个** client。
                # 原先 _get_model_loads 自己 new LanzClient 并每 20s 登录一次，
                # 同一 SSO 账号两个会话互相踢——worker 刚登录就被踢回 SSO
                # 登录页，表现为「一直登录失败」，还会触发风控锁号。
                # a446：负载 20s 级变化，额度 600s 级。切三段等待，负载每
                # LOAD_TTL 走一次 _fetch_loads（同一 client，零新登录）。
                self._cur_client = client
                last_full = 0.0
                while not self._stop.is_set():
                    now = time.time()
                    # a452（审计 P1：点刷新对额度无效）：手动刷新请求必须
                    # 立即拉一次全量，不能被下面 600s 的到期判定吃掉。
                    with self._lock:
                        force_full = self._refresh_req
                        self._refresh_req = False
                    if force_full or now - last_full >= (self.REFRESH_INTERVAL if auto else 1e9):
                        last_full = time.time()
                        if not self._fetch_all(client, cred):
                            break        # a452：会话过期 → 回外层走 _ensure_login
                    if not self._fetch_loads(client):
                        break            # 会话失效 → 回外层按 60s 退避重登
                    self._wake.clear()
                    if self._stop.is_set():
                        break
                    # 自动刷新关掉时：只等 wake（手动刷新），负载也不自动拉
                    self._wake.wait(LOAD_TTL if auto else None)
                    with self._lock:
                        cred_now, auto_now = self._cred, self._auto
                    # a452：cur_epoch 是 (cur_cred_epoch, cred_epoch) 二元组，
                    # 必须逐项比。原来 `int != tuple` 恒真，内层每轮都 break。
                    if _epoch_changed(self, cred, cred_now, cur_epoch):
                        break            # 凭据/重登变了 → 回外层重建 client
                    auto = auto_now
            except Exception:
                log.exception("LanzQuotaWorker _run 循环异常，继续运行")

    def _fetch_loads(self, client):
        """拉模型负载（a446）：复用 worker 的 client，绝不另建会话。

        返回 True=继续；False=会话失效——**不在负载通道里自己重登**。账号
        一旦被 SSO 风控锁定，20s 一次的重登会持续加重锁定，交给外层
        _ensure_login 按 60s 退避重登。
        """
        try:
            loads = client.get_model_loads()
        except lanz_quota.LanzSessionExpired:
            self._set_loads_err("会话过期，等待重新登录")
            return False
        except lanz_quota.LanzError as e:
            self._set_loads_err("负载查询失败: %s" % e)
            return True
        except Exception as e:
            log.warning("模型负载查询异常: %s", e)
            self._set_loads_err("负载查询异常: %s" % e)
            return True
        global _quota_loads, _quota_loads_ts, _quota_loads_err
        with _quota_loads_lock:
            _quota_loads = loads
            _quota_loads_ts = time.time()
            _quota_loads_err = ""
        return True

    def _set_loads_err(self, msg):
        global _quota_loads_err
        with _quota_loads_lock:
            _quota_loads_err = msg

    def _clear_loads(self, msg):
        global _quota_loads, _quota_loads_ts, _quota_loads_err
        with _quota_loads_lock:
            _quota_loads = []
            _quota_loads_ts = 0.0
            _quota_loads_err = msg

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
                self._login_err = ""
                self._locked = False      # a454：登录成功即解除锁定停登
                self._login_done_ts = time.time()   # a559：新登录时刻（被踢熔断判据）
            self._emit("login_ok", cred[0])
            return True
        except lanz_quota.LanzAuthError as e:
            msg = str(e)
            with self._lock:
                # a452（审计）：旧账号的 login() 在途时用户提交了新账号，
                # 这里若照写 _locked/_login_err，会把旧账号的锁定态喂给新
                # 账号（界面闪一次误导性的「账号已被 SSO 锁定」）。持锁区
                # 内只能直接比字段——_cred_changed 会重新 acquire 死锁。
                if self._cred == cred:
                    self._login_failed = True
                    self._login_err = msg
                    # a454（用户实锤：1 小时不解锁——锁定期间每 600s 仍自动
                    # 登一次，每次尝试都把 SSO 锁定计时重置，等于永久续期）。
                    # 识别到锁定文案就**停登**，不再定时重试，等用户手动点
                    # 刷新/重登。
                    if _is_lockout_msg(msg):
                        self._locked = True
            if not self._cred_changed(cred):
                self._emit("login_err", msg)
            return False
        except lanz_quota.LanzNetworkError as e:
            # a452（审计 P1）：锁定文案不只从 LanzAuthError 出来——_fetch_text
            # 在 HTTP 401/403/500 时把响应体拼进 LanzNetworkError，锁定页的
            # "Too many attempts" 会走这条。只认 LanzAuthError 就漏判，外层
            # 按 60→600s 退避持续重登，把 SSO 锁定反复续期。
            msg = "网络错误（需内网/VPN）: %s" % e
            with self._lock:
                self._login_failed = True
                if _is_lockout_msg(msg):
                    self._locked = True
                    self._login_err = msg
            if not self._cred_changed(cred):
                self._emit("login_err", msg)
            return False
        except lanz_quota.LanzError as e:
            # a452：同理，_request 在 code!=2001/3001 时抛的通用 LanzError
            # 也可能带锁定文案（"API 返回错误 code=… msg=Too many attempts"）。
            msg = "登录失败: %s" % e
            with self._lock:
                self._login_failed = True
                if _is_lockout_msg(msg):
                    self._locked = True
                    self._login_err = msg
            if not self._cred_changed(cred):
                self._emit("login_err", msg)
            return False

    def _fetch_all(self, client, cred=None):
        """拉额度全量。返回 True=继续，False=会话已过期，调用方须回外层重登。

        a452：原 `for attempt in (1, 2)` 的重试只服务于「会话过期 → force
        重登 → 再取一次」这一条（唯一 continue 的路径，已删）。现在会话
        过期直接返回 False，循环只跑一轮。

        a452（审计）：原来这里只 emit 不返回状态，内层靠紧随的
        _fetch_loads 也报 3001 才 break。若 dashboard 走 /v1/ai-resource 已
        过期、而 models 走 /v1/openai/models 仍 2001（两条网关路径），内层
        永不回外层 → 额度面板永久「会话过期，等待重新登录」直到手动重登。
        会话过期必须以返回值显式传递。
        """
        try:
            dash = client.get_dashboard()
            budget = None
            try:
                budget = client.get_budget_overview()
            except lanz_quota.LanzError:
                pass
            if cred is not None and self._cred_changed(cred):
                return True
            self._emit("data", {"dashboard": dash, "budget": budget,
                                "ts": time.time()})
            return True
        except lanz_quota.LanzSessionExpired:
            # a452（审计 P1）：这里原有 `client.login(force=True)` 私有重登，
            # 绕过了 _ensure_login 的锁定识别、_auto_relogin 开关和锁定停登
            # ——自动重登关着照样重登、账号已锁照样再敲一次把锁定计时续期。
            # 刷新路径不允许自带重登：如实报会话过期，交给外层 _run 统一
            # 走 _ensure_login（那里才认锁定与开关）。
            if cred is None or not self._cred_changed(cred):
                self._emit("fetch_err", "会话过期，等待重新登录")
            return False
        except lanz_quota.LanzNetworkError as e:
            if cred is None or not self._cred_changed(cred):
                self._emit("fetch_err", "网络错误: %s" % e)
            return True
        except lanz_quota.LanzError as e:
            if cred is None or not self._cred_changed(cred):
                self._emit("fetch_err", "查询失败: %s" % e)
            return True


# ==== 模块级单例与状态（仿 tftp.py `_tftp` 模式）========================
_bmgr = BaseUrlManager()
_ctl = ProxyController()
_bili = BiliController()
_quota_state = {}       # {"kind":..., "payload":..., "ts":...} 最新一次 emit（msg 提示用）
_quota_login = None     # 登录态独立槽 {"state": online/logging/error/fetch_err, "user":...}
                         # （与 _quota_state 分槽：data 事件不再覆盖登录态——
                         # 用户实锤合槽后前端永远显示「登录中」）
_quota_ov = {}           # dashboard.overview 缓存（托盘菜单/tooltip 用）
_quota_rank = []         # dashboard.modelRank 缓存（模型用量排名表）
# a442（用户需求）：模型实时负载。与额度同源（LanzClient.get_model_loads），
# 但负载变化快——额度 600s 一刷太慢，单独 20s TTL 按需刷新（status 轮询驱动，
# 面板/悬浮卡不看就不拉；刷新频率由 worker 内层循环的 LOAD_TTL 决定。
_quota_loads = []
_quota_loads_ts = 0.0
_quota_loads_err = ""
_quota_loads_lock = threading.Lock()
_quota_ts = None         # 上次 data 时间戳（前端显示"上次刷新 Ns 前"）
_quota_lock = threading.Lock()
_quota = None            # LanzQuotaWorker（HAS_LANZ 且凭据存在时才建）

# a561 审计 F5：跨进程重登标记——进程重启型登录风暴（11-12 实锤形态：
# worker 崩溃→重启→每次进程重建 quota worker 都立即真实登录一次）的滑窗
# 在内存里，每个新进程从零计数拦不住。落盘共享 + 熔断冷却期内新进程
# 也不自动登录，重启循环的登录率被压到每冷却期一次
_MARKS_PATH = os.path.join(DATA_DIR, "lanz_login_marks.json")
_MARKS_LOCK = threading.Lock()


def _load_marks():
    """读跨进程重登标记：([stamps], trip_ts)。任何异常→空标记（不拦登录）。"""
    try:
        with open(_MARKS_PATH, encoding="utf-8") as f:
            j = json.load(f)
        stamps = [t for t in j.get("stamps", [])
                  if isinstance(t, (int, float))]
        return stamps, float(j.get("trip_ts") or 0.0)
    except Exception:
        return [], 0.0


def _save_marks(stamps, trip_ts=0.0):
    tmp = None
    try:
        d = os.path.dirname(_MARKS_PATH)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        # a602：原子写（裸 "w" 直写期间镜像线程会读到半截 JSON）
        tmp = "%s.%d.%d.tmp" % (_MARKS_PATH, os.getpid(),
                                threading.get_ident())
        with _MARKS_LOCK, open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stamps": list(stamps[-4:]), "trip_ts": trip_ts}, f)
        _replace_retry(tmp, _MARKS_PATH)
        tmp = None
        _notify_mirror("lanz_login_marks.json")
    except Exception:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass

_cred_cache = None       # 凭据磁盘缓存（save/clear 时刷新；status 1s 轮询
                         # 不再每秒 load_credentials 读盘+JSON 解析）
_cred_cached = False     # 缓存是否已初始化（None=无凭据 也是合法值）

_autoswitched = False    # 工具自动改过 base_url → 退出时回滚直连
_bili_switching = False
_bili_switch_guard = threading.Lock()   # a238 P3-2：切换标志 check+set 原子化
_bili_last_err = ""      # a203：最近一次压缩模式切换失败原因（前端展示，成功则清空）
_bili_mode = None    # 当前压缩模式（init 时从记忆文件读）
_ccr = False
_tray_tip_thread = None
_tip_stop = threading.Event()
_shutdown_done = False
_liveness_cache = {"ts": 0.0, "already": False, "busy": False}   # a239 A3-P3-9: 端口判活 2s 缓存（status 轮询防 ping 堆积）
_bili_stats_cache = None        # headroom /stats 最近一次结果（5s 缓存线程写，
                              # status 1s 轮询只读——/stats 拉取 2s 超时不能同步做）
_bili_stats_ts = 0.0


def _bili_stats_loop():
    """统计轮询（5s）+ a230 压缩链自愈：bili 中途死掉（崩溃/被杀）时
    base_url 仍指 18788 空端口——正在跑的会话全断且无人救（用户实锤
    「开启后请求 0、会话无响应」）。每拍检测：/bili/ 链 + bili 不通
    → 自动回滚直连（复用 ensure_direct_if_proxy_down 的既有自愈）。"""
    """headroom 压缩统计缓存线程：headroom 模式在（非 off）就 5s 拉 /stats
    （GUI _refresh_headroom 平移，但这里是后台循环天然防堆积，不会像 GUI 每秒探测）。
    条件不绑 _ctl.running：headroom 可独立于自家重试代理在线（端口 37349 被
    外部实例占、或 headroom 复用外部实例）——绑死则 stats 永远 null，
    面板卡「stats 拉取中/失败」（用户实锤）。_bili.stats() 内部自判 running。"""
    global _bili_stats_cache, _bili_stats_ts
    while not _tip_stop.is_set():
        try:
            if _bili_mode != "off":
                _bili_stats_cache = _bili.stats()
                _bili_stats_ts = time.time()
                # a230 自愈：统计拉取失败=不可达——若 base_url 在 bili 链上
                # 即回直连（首拍失败容忍，连续两拍才动——避免启动窗口误切）
                if _bili_stats_cache is None:
                    _bili_down = getattr(_bili_stats_loop, "_down", 0) + 1
                    _bili_stats_loop._down = _bili_down
                    if _bili_down >= 2:
                        try:
                            ensure_direct_if_proxy_down()
                        except Exception:
                            pass
                else:
                    _bili_stats_loop._down = 0
            else:
                _bili_stats_cache = None
                _bili_stats_loop._down = 0
        except Exception:
            pass
        _tip_stop.wait(5)


def _ensure_bili_stats_thread():
    t = threading.Thread(target=_bili_stats_loop, daemon=True)
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
        elif kind == "login_locked":
            # a454：SSO 锁定 → 已停登（不再自动重试，避免续期锁定）
            _quota_login = {"state": "locked", "user": None,
                            "msg": str(payload or "账号已被 SSO 锁定，已停止自动登录"),
                            "auto_paused": True}
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
        try:
            _cred_cache = lanz_quota.load_credentials(LANZ_CRED_PATH) if HAS_LANZ else None
        except Exception:
            _cred_cache = None   # 凭据文件损坏/编码异常不拖死 status 轮询
        _cred_cached = True
    return _cred_cache


def _invalidate_cred_cache(cred):
    """save/clear 后直接写新值（免得下轮 status 又读一次盘）。"""
    global _cred_cache, _cred_cached
    _cred_cache = cred
    _cred_cached = True
    # a442：凭据变了，模型负载也失效（换号后负载/权限都不同）
    global _quota_loads, _quota_loads_ts, _quota_loads_err
    with _quota_loads_lock:
        _quota_loads = []
        _quota_loads_ts = 0.0
        _quota_loads_err = ""


LOAD_TTL = 20.0   # 模型负载缓存时长（秒）：status 1s 轮询，20s 内复用


def _is_lanz_api():
    """当前真正请求的 API 是否走 lanz 网关（a442 用户定调）。

    判据是「上游是谁」而非「是否直连」：本机重试代理恒启动，代理模式的
    base_url 是 127.0.0.1:37349/v3/xxx，其上游由 _direct_url 决定——只要
    上游主机是 lanz.hikvision.com 就算用 lanzi API，负载照样显示。
    """
    try:
        if _ctl.running and _ctl.server is not None:
            host = _ctl.server.upstream_host
        else:
            host = _upstream_of(_direct_url())[0]
        return "lanz.hikvision.com" in (host or "").lower()
    except Exception:
        return False


def _get_model_loads():
    """模型实时负载（a442）。返回 (列表, 错误串)。

    a446（严重回归修复）：**只读缓存，绝不自己登录**。
    原实现在这里 new LanzClient 并 login()，与 LanzQuotaWorker 的会话同时
    存在于同一个 SSO 账号下——两个会话互相踢，worker 刚登好就被踢回 SSO
    登录页（用户实锤「一直登录失败」，还触发风控）。现在负载统一由 worker
    在它自己的 client 上顺带拉（_fetch_loads），这里只取缓存。
    """
    with _quota_loads_lock:
        return list(_quota_loads), _quota_loads_err


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


# ---- 启停/模式核心操作（GUI _on_toggle/_set_mode/_apply_bili_mode 平移）--
def _wait_bili_ready(timeout=BILI_READY_TIMEOUT):
    """等 bili /__bili/health 就绪。Popen 返回≠可服务。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = _bili.proc_snapshot()
        if proc is not None and proc.poll() is not None:
            raise RuntimeError("bili 子进程启动即退出 (code=%s)\n%s"
                               % (proc.returncode, _bili.startup_error()))
        if _bili.ping_existing():
            log.info("bili 已就绪 :%d", BILI_PORT)
            return
        time.sleep(0.5)
    raise RuntimeError("bili %ds 内未就绪\n%s" % (timeout, _bili.startup_error()))


def _proxy_mode_url():
    """代理模式目标 base_url：off→37349 直连重试代理；压缩在跑→bili 入口。"""
    if _bili_mode == "off" or not _bili.ping_existing():
        return _retry_url()
    return _bili_url()


def start_proxy(bili_mode=None):
    """启动重试代理 + headroom（按模式）+ 切 base_url（GUI _on_toggle 平移）。
    bili_mode=None 用当前记忆模式；显式传 "off" 可本次跳过 headroom（省内存）。
    headroom 冷启动慢 → 后台线程等就绪再补切 8787，期间先切 37349 会话不中断。
    返回 (ok, msg)。"""
    global _autoswitched, _bili_switching
    mode = _bili_mode if bili_mode is None else bili_mode
    # a238 P3-2：check+set 原子化（模块锁）——原先两步无锁，压缩切换 90s 窗口
    # 内并发的 start/第二次 compression 请求双双穿过；start 也不检查标志，
    # 会 ping 到正在被 stop 的垂死实例记「复用」随即翻车
    with _bili_switch_guard:
        if _bili_switching:
            return False, "压缩层切换进行中，请稍候"
        if _ctl.running:
            return True, "已在运行"
        if _ctl.port_in_use():
            if _ctl.ping_existing():
                return False, "already_running"   # 外部自家实例在跑（前端降级展示，复用不杀）
            return False, "端口 %d 被其他程序占用，无法启动" % LISTEN_PORT
        try:
            _ctl.start()
        except Exception as e:   # 绑定失败等——给面板可读消息，别让 Flask 吞成 500
            return False, str(e)
        # a251：代理跑起来了 → 记自启（下次工具启动自动拉起；stop 清除）
        set_proxy_autostart(True)
        _bili_switching = True
        # a250 P3（a247/a248复审）：epoch 在主线程 spawn 前捕获——若在线程首条
        # 语句捕获，guard 释放到线程启动的亚毫秒窗内 stop 已 bump，worker 反而
        # 拿到"新值"自认有效
        _ep0 = _repoint_seq

    def _worker():
        global _bili_switching, _autoswitched, _bili_mode, _bili_last_err
        _ep = _ep0
        try:
            # 先记忆当前直连地址（非代理值才记——恢复的真源），再切 37349
            # 直连重试代理（不等 headroom，会话立即可用）
            cur = _bmgr.read_current_url()
            _remember_direct(cur)
            if _is_own_proxy_url(cur) and not _load_saved_direct():
                # base_url 卡在代理地址且无记忆（旧版切的代理）——从配置
                # 方案快照找回真源并落盘，此后恢复不再依赖方案文件
                _remember_direct(_direct_url())
            target = _retry_url()
            # a250 P3：检查+apply 同锁原子化（_switch_lock 与 _bmgr.apply 内部
            # 同把 RLock 可重入；stop/手动接管的 apply 也在锁内 → 全序正确，
            # 杜绝检查后 apply 前 bump 穿透的 TOCTOU）
            with _switch_lock:
                if _ep != _repoint_seq:
                    log.info("启动中途 base_url 已被停止/接管/切方案，放弃重试代理切换")
                    return
                if cur != target:
                    _bmgr.apply(target)
                    _autoswitched = True
            if mode != "off":
                try:
                    _bili.start(mode)
                    _wait_bili_ready()
                    # a250 P3：作废不再杀 bili——epoch 同为切方案所 bump，杀掉会让
                    # 压缩静默失效到下次重启；实例保留（面板状态一致），仅不拉回入口
                    with _switch_lock:
                        if _ep != _repoint_seq:
                            log.info("bili 就绪但 base_url 已被停止/接管/切方案，不切回代理入口（bili 实例保留）")
                            return
                        if _bmgr.read_current_url() != _bili_url():
                            _bmgr.apply(_bili_url())
                            _autoswitched = True
                except Exception as e:
                    # a238 P3-3：对齐 apply_bili_mode 的回退面——原只 log，节点
                    # 滞留（idle node 常驻）且 mode 仍记 on（第 91s 起来也永不
                    # 补切链路，压缩静默失效白占内存）
                    # a251（用户需求：如果能用就保存开启状态）：运行态回退 off
                    # + 留证，但**不再抹记忆文件**——瞬时失败不该永久丢用户偏好，
                    # 下次启动按记忆再试
                    _bili_mode = "off"
                    log.warning("bili 启动失败，本次回退无压缩（记忆保留）: %s", e)
                    try:
                        _bili.stop()
                        _bili_last_err = str(e)[:200]
                    except Exception:
                        pass
        finally:
            _bili_switching = False
            _proxy_notify()   # 状态可能变化（就绪/失败），广播给前端
    threading.Thread(target=_worker, daemon=True).start()
    _ensure_tray()
    _proxy_notify()
    return True, "启动中（bili 冷启动需就绪探测，期间先走 37349 不断会话）"


def ensure_proxy_for_claude():
    """开启 Claude 联动：重试代理没跑就后台拉起——本次不带 headroom（省内存），
    只起 37349 重试代理（价值：用量统计 + 429/5xx 重试）。30s 内没就绪则
    停掉并把 base_url 切回直连，绝不卡死会话。幂等，后台线程执行。"""
    def _worker():
        try:
            if _ctl.running or _ctl.ping_existing():
                return   # 已在跑（含外部自家实例）：直接复用
            ok, msg = start_proxy(bili_mode="off")
            if not ok:
                # 端口被占等失败：确保 base_url 没卡在自家代理端口上
                try:
                    cur = _bmgr.read_current_url()
                    if _is_own_proxy_url(cur):
                        _bmgr.apply(_direct_url())
                except Exception:
                    pass
                log.warning("Claude 联动拉代理失败: %s", msg)
                return
            end = time.time() + 30
            while time.time() < end:
                if _ctl.running and _ctl.ping_existing():
                    log.info("Claude 联动：重试代理已就绪（%d，无 headroom）",
                             LISTEN_PORT)
                    return
                time.sleep(1)
            log.warning("Claude 联动：代理 30s 未就绪，停用并切回直连")
            stop_proxy(remember=False)   # a251：内部回退，不清自启偏好
        finally:
            _proxy_notify()   # 无论结果如何，广播一次让前端同步
    threading.Thread(target=_worker, daemon=True).start()


def stop_proxy(remember=True):
    """停止代理（GUI stop_proxy 平移）：headroom + 重试代理一起停，
    base_url 还指着自家代理（37349/8787）就一律切回直连——含手动
    「切换为代理模式」的路径（用户实锤：点停止的同时应切直连，
    之前只在 _autoswitched 时回滚，手动切过代理模式的会停在死端口）。
    幂等。a251：remember=True（用户动作）才清自启记忆；内部自动停
    （Claude 联动 30s 超时等）传 False——失败回退不抹用户偏好。"""
    global _autoswitched
    if remember:
        set_proxy_autostart(False)
    _bump_repoint_epoch()   # 代理都停了：排队中的方案联动不得再动 base_url
    _bili.stop()
    _ctl.stop()
    try:
        cur = _bmgr.read_current_url()
        if _autoswitched or _is_own_proxy_url(cur):
            _bmgr.apply(_direct_url())
            log.info("代理停止，base_url 已切回直连（原: %s）", cur)
    except Exception as e:
        log.warning("代理停止后切直连失败: %s", e)
    _autoswitched = False
    _proxy_notify()
    return True, "已停止（base_url 已切回直连）"


def set_mode(mode):
    """手动切 base_url（GUI _set_mode 平移）：changed 非空才算用户接管，
    autoswitched=False 退出不回滚。返回 (ok, changed)。"""
    global _autoswitched
    if mode not in ("proxy", "direct"):
        return False, ["未知模式"]
    _bump_repoint_epoch()   # 用户手动接管 base_url：排队中的方案联动作废
    if mode == "proxy":
        # 切代理前必记忆原值——用户只点「切换为代理模式」不点启动的路径
        # 也要覆盖，否则强杀后自愈拿不到记忆，只能恢复默认兜底
        _remember_direct(_bmgr.read_current_url())
    target = _proxy_mode_url() if mode == "proxy" else _direct_url()
    changed, skipped = _bmgr.apply(target)
    if changed:
        _autoswitched = False
    log.info("手动切换 base_url -> %s: %s", target, changed)
    return True, changed


def saved_direct_url():
    """记忆中的直连地址（公开读取口——方案切换净化旧方案快照用）。"""
    return _load_saved_direct()


def current_base_url():
    """settings 当前 ANTHROPIC_BASE_URL（公开读取口——方案切换要在写回
    settings 前捕获「之前是否代理模式」，写完再读就只剩新方案的直连值）。"""
    return _bmgr.read_current_url()


def proxy_intent_active():
    """「链路应处于代理模式」判定（方案切换捕获 was_proxy 用，v2.27.2）：
    base_url 指自家入口，或自动代理模式（_autoswitched）且重试代理在跑。
    后者覆盖连点切方案的中间态——第一刀已把 base_url 写成新方案直连值，
    但用户从未退出代理模式，最后一刀必须把 base_url 拉回代理入口。
    手动「切直连」（set_mode → _autoswitched=False）与停代理后恒 False，
    不会把用户硬拉回代理。"""
    cur = _bmgr.read_current_url()
    if _is_own_proxy_url(cur):
        return True
    return bool(_autoswitched and _ctl.running)


_repoint_seq = 0
_switch_lock = threading.RLock()   # 方案切换全临界区互斥锁（见 switch_lock）


def switch_lock():
    """方案切换临界区锁（claude_default.claude_profiles_apply 持它包住
    「读 settings-净化-写回-写 profiles」整段；后台 re_point worker 与
    headroom 重拉收尾也拿它——杜绝整份写回与字段级改写交错，否则后写的
    字段级 base_url 改动会把新方案 token/模型映射整份顶回旧方案）。"""
    return _switch_lock


def _bump_repoint_epoch():
    """作废所有排队中的后台重指。手动切模式/停代理/自愈回直连后调——
    这些动作之后，排队 worker 再把 base_url 拉回代理入口就是破坏
    （代理已停时更是指向死端口）。"""
    global _repoint_seq
    _repoint_seq += 1


# ---- 方案切换 in-flight 保护（用户定调：后台没稳定前禁止再切方案）----
# 快速连点切方案时多个 worker 竞态，曾出现「新 token + 旧上游」错配终态
# （lanz token 打智谱网关 → Claude 卡死）。保护：apply 前查 in-flight，
# 未稳定一律 409 拒绝；worker 全部收尾（含 headroom 重拉）才放行。
_switch_busy = {"n": 0, "ts": 0.0}
_switch_busy_lock = threading.Lock()


def profile_switch_in_flight(timeout=60.0):
    """方案切换是否仍在后台进行（claude_default.apply 与前端按钮共用）。
    超时强制放行——worker 异常挂死时不能把用户永久锁在外面（epoch 机制
    仍保证最终一致）。"""
    with _switch_busy_lock:
        if _switch_busy["n"] <= 0:
            return False
        if time.time() - _switch_busy["ts"] > timeout:
            _switch_busy["n"] = 0
            return False
        return True


def _switch_busy_inc():
    with _switch_busy_lock:
        _switch_busy["n"] += 1
        _switch_busy["ts"] = time.time()


def _switch_busy_dec():
    with _switch_busy_lock:
        _switch_busy["n"] = max(0, _switch_busy["n"] - 1)


def queue_re_point(new_direct_url, was_proxy=None):
    """把 re_point_upstream 排到后台线程执行（claude_profiles_apply 在
    switch_lock 临界区内调）。秒级同步活全后台，HTTP 接口体感立即。
    epoch：worker 拿到锁后若发现已排入更新的方案（或被手动切模式作废）
    直接退出——最终状态永远等于「最后一次动作」。"""
    global _repoint_seq
    if not new_direct_url or _is_own_proxy_url(new_direct_url):
        return
    _repoint_seq += 1
    myseq = _repoint_seq

    def _worker():
        _switch_busy_inc()
        try:
            with _switch_lock:
                if myseq != _repoint_seq:
                    return   # 排队期间有更新动作：以最后一次为准，本次作废
                try:
                    re_point_upstream(new_direct_url, was_proxy=was_proxy,
                                      _epoch=myseq)
                except Exception as e:
                    log.warning("切方案后台重指代理失败: %s", e)
        finally:
            _switch_busy_dec()

    threading.Thread(target=_worker, daemon=True).start()


def re_point_upstream(new_direct_url, was_proxy=None, notify=True, _epoch=None):
    """API方案切换后重指代理上游（用户定：立即跟随，不等下次启停代理）。
    先记忆新直连地址（此后停止/退出恢复的真源），再热改重试代理上游属性
    （零停机，不 stop/start server）。base_url 此前指代理入口（=代理在链路上）则继续指代理入口
    只是换了真身；本在直连模式则不动 base_url，只换代理上游。headroom 在
    跑且新网关路径不同：其上游 env 是启动时烘死的，必须重拉——借
    apply_bili_mode 整套（停旧拉新+等就绪+切 8787），期间 base_url 先指
    37349 会话不中断。代理没在跑：只记忆，不动 base_url。返回 (ok, msg)。
    was_proxy：调用方（profiles/apply）在整份写回 settings **之前**判得的
    「base_url 是否指代理入口」——传入则优先，不传才现读（调用时 settings
    已被新方案覆盖，现读必为 False，是 v2.27 首修时的实锤时序坑）。"""
    if not new_direct_url or _is_own_proxy_url(new_direct_url):
        return False, "无效的直连地址"
    if was_proxy is None:
        was_proxy = _is_own_proxy_url(_bmgr.read_current_url())
    prev = _load_saved_direct() or _direct_url()
    old_path = urlsplit(prev).path or "/"   # 记忆此刻还是旧网关（settings
    _remember_direct(new_direct_url)          # 已被切方案写成新值，不能作旧源）
    if not _ctl.running:
        if _ctl.ping_existing():
            # 外部自家实例在跑（不归本进程管）：上游热切不了，base_url 停在
            # 代理入口只会打旧上游——退直连自保
            if was_proxy:
                _bmgr.apply(new_direct_url)
            log.warning("方案切换：37349 为外部实例，上游无法热切，已退直连")
            return False, "外部代理实例无法热切，已切直连"
        return False, "代理未运行（已记忆新直连地址）"
    # 热改上游属性而非停/起重试代理：handler 每请求读 server.upstream_*，
    # 原子换引用即可——零停机、持锁仅纳秒（早期版本 stop+start 同步停
    # server ~0.3s 且全程持 switch_lock，连点切方案时请求在锁上排队，
    # 用户实锤「卡死」）。三属性顺序赋值（scheme→host→port），GIL 下单条
    # 原子；纳秒级中间态最多让个别在途请求连错一次，网络异常重试兜底。
    h, p, s = _upstream_of(new_direct_url)
    with _ctl._lock:
        srv = _ctl.server
        if srv is not None:
            srv.upstream_scheme = s
            srv.upstream_host = h
            srv.upstream_port = p
    if srv is None:
        return False, "代理未运行（已记忆新直连地址）"
    log.info("方案切换：代理上游热切 -> %s:%d (%s)", h, p, s)
    global _autoswitched
    if not was_proxy:
        # 用户本就在直连模式：settings 里已是新网关直连，只换代理上游
        # （统计/重试跟对网关），不把用户拉回代理模式
        log.info("方案切换：代理上游 -> %s（base_url 保持直连）", new_direct_url)
        if notify:
            _proxy_notify()
        return True, "代理上游已跟随切换（base_url 保持直连）"
    new_path = urlsplit(new_direct_url).path or "/"
    # 对抗审 a206A：headroom 时代上游烘死在 env 里需重拉——bili 是 URL
    # 前缀模式，上游每请求从 /bili/<upstream> 解码，_bili_url() 已随新方
    # 案求值，重切 base_url 即完成切换，零停机零重拉（旧重拉分支只制造
    # 5s+ 停机窗口，已拆）
    if (_bili.ping_existing() and _bili_mode != "off" and new_path != old_path):
        _bmgr.apply(_bili_url())
        _autoswitched = True
        msg = "代理上游已切换（压缩链路零停机跟随）"
    else:
        target = _proxy_mode_url()
        _bmgr.apply(target)
        _autoswitched = True
        msg = "代理上游已跟随切换"
    log.info("方案切换：代理上游 -> %s，base_url -> 代理入口", new_direct_url)
    if notify:
        _proxy_notify()
    return True, msg


def apply_bili_mode(mode, ccr=None):
    """运行时切压缩模式（GUI _apply_bili_mode/_done 平移）。
    off：停 headroom 同步切 37349；full/light：停旧拉新，后台线程等就绪切 8787，
    失败回退 off 并同步记忆文件。"""
    global _bili_mode, _bili_switching, _ccr, _autoswitched
    if ccr is not None:
        _ccr = bool(ccr)
        save_ccr(_ccr)
    if mode not in BILI_MODES:
        return False, "未知压缩模式"
    # 原版行为（用户实锤顺序）：headroom 的上游是重试代理，代理没跑时
    # 拉 headroom 无意义 → 只记模式，下次启动代理时自动拉起（托盘路径）。
    # off（关闭压缩）永远立即生效。面板弹窗另有 running 门槛防误点。
    if mode != "off" and not _ctl.running:
        _bili_mode = mode
        save_bili_mode(mode, remember=True)
        log.info("压缩模式 -> %s（代理未运行，下次启动生效）", mode)
        return True, "已记住，下次启动代理时生效"
    # a238 P3-2：check+set 进锁（与 start_proxy 同一把 guard，交叉并发全挡）
    with _bili_switch_guard:
        if _bili_switching:
            return False, "压缩模式切换进行中，请稍候"
        _bili_switching = True

    def _worker():
        global _bili_mode, _bili_switching, _autoswitched, _bili_last_err
        try:
            _bili_mode = mode
            save_bili_mode(mode, remember=True)
            _bili.stop()
            if mode == "off":
                # 代理在跑才把 base_url 指回 37349；没在跑时只改记忆
                # ——否则 base_url 指向空端口，Claude Code 直接连不上
                if _ctl.running:
                    _bmgr.apply(_retry_url())
                    _autoswitched = True
                log.info("压缩模式切换 -> off（bili 已停%s）",
                         "，直连重试代理" if _ctl.running else "，代理未跑不动 base_url")
                return
            try:
                # a203：这里原写 _bili.start(mode, ccr=_ccr)——BiliController.start
                # 的签名是 start(self, mode="on")，没有 ccr（ccr 是 headroom 时代的
                # 特性，a206A 已退役）。多传一个关键字参数直接 TypeError，被
                # 下面 except 接住后静默回退 off —— 表现为「点开启压缩完全没
                # 反应」：接口返 ok「切换中」、bili_mode 永远是 off、base_url
                # 不动。runtime 切换与启动路径（:1011）保持一致。
                _bili.start(mode)
                _wait_bili_ready()
                _bmgr.apply(_bili_url())
                _autoswitched = True
                _bili_last_err = ""      # a203：成功即清空上次失败原因
                log.info("压缩模式切换 -> %s（base_url -> 8787）", mode)
            except Exception as e:
                # 失败回退 off（运行态）：a251 起不再把 off 写进记忆文件——
                # 记忆=用户偏好，实际拉不起来时运行态回退+留证，下次再试
                _bili_mode = "off"
                log.warning("切换到 %s 失败，本次回退直连（记忆保留）: %s", mode, e)
                # a203：回退必须留证据。原样只有一行 log.warning —— 前端拿到
                # ok「切换中」后再查状态只看到 off，用户完全不知道为什么
                # （a201/202 的 ccr TypeError 就这样藏了两天）。这次改成把
                # 原因同时塞进状态字段，前端弹窗直接显示。
                try:
                    _bili_last_err = "%s 切换失败：%s" % (mode, e)
                    if _bili.startup_error():
                        _bili_last_err += "\n" + _bili.startup_error()
                except Exception:
                    pass
                _bmgr.apply(_retry_url())
                _autoswitched = True
        finally:
            _bili_switching = False
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
    has_bili = bool(BILI_NODE and BILI_ENTRY)

    def _hr_items():
        # 未启动重试代理时压缩项置灰（bili 的上游是 37349）；
        # 关闭压缩永远可点——用于启动前把记忆里的模式改成 off
        en = has_bili   # 装了 billion-context 即可选，代理未跑=只记模式下次启动生效
        return [
            ("item", "开启压缩", lambda: apply_bili_mode("on"),
             {"radio": True, "checked": lambda: _bili_mode == "on",
              "enabled": en}),
            ("item", "关闭压缩", lambda: apply_bili_mode("off"),
             {"radio": True, "checked": lambda: _bili_mode == "off"}),
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
        # 对抗审 a206A：CCR 菜单退役——BiliController.start 的 ccr 形参
        # 零引用（a201 换代时功能随 headroom env 摘除），开关卖的是空操作
    ]


def tray_menu_items_remote(base):
    """进程隔离形态的托盘 Proxy 段（proxy 数据面在 worker、托盘在主进程）：
    与 tray_menu_items 同构的菜单树，状态/操作全部经 worker 的
    /api/proxy/* HTTP 往返。status 取一次缓存 ~2s（一次右键打开菜单时
    多个 text/checked 求值共享同一次拉取，不风暴）；操作 fire-and-forget。"""
    import urllib.request

    cache = {"ts": 0.0, "data": None}

    def _st():
        now = time.time()
        if cache["data"] is None or now - cache["ts"] > 2.0:
            try:
                req = urllib.request.urlopen(base + "/api/proxy/status",
                                             timeout=1.5)
                cache["data"] = json.loads(req.read().decode("utf-8", "replace"))
            except Exception:
                if cache["data"] is None:
                    cache["data"] = {}
            cache["ts"] = now
        return cache["data"] or {}

    def _post(path, body=None):
        try:
            req = urllib.request.Request(
                base + path, data=json.dumps(body or {}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass   # 托盘操作失败静默：面板是完整入口，菜单只是快捷方式

    def _header_text():
        d = _st()
        return ("Claude Proxy [%s]" % d.get("status")) if d.get("running") \
            else "Claude Proxy（未启动）"

    def _quota_row():
        d = _st()
        ov = d.get("quota_overview")
        u = d.get("quota_user")
        if not ov:
            return "额度: %s" % ("已登录 " + u if u else "未登录/暂无数据")
        return "今日 外 %s/%s  内 %s/%s" % (
            _fnum(ov.get("externalDailyUsed") or 0),
            _fnum(ov.get("externalDailyLimit") or 0),
            _fnum(ov.get("internalDailyUsed") or 0),
            _fnum(ov.get("internalDailyLimit") or 0))

    def _toggle_text():
        return "■ 停止 Claude 代理" if _st().get("running") \
            else "▶ 启动 Claude 代理"

    def _hr_items():
        # 装了 billion-context 即可选（代理未跑=只记模式下次启动生效）
        en = bool(_st().get("bili_ready"))
        return [
            ("item", "开启压缩",
             lambda: _post("/api/proxy/compression", {"mode": "on"}),
             {"radio": True, "checked": lambda: _st().get("bili_mode") == "on",
              "enabled": en}),
            ("item", "关闭压缩",
             lambda: _post("/api/proxy/compression", {"mode": "off"}),
             {"radio": True, "checked": lambda: _st().get("bili_mode") == "off",
              "enabled": True}),
        ]

    return [
        ("sep",),
        ("item", _header_text, None, {"enabled": False}),
        ("item", _quota_row, None, {"enabled": False}),
        ("item", "额度立即刷新", lambda: _post("/api/proxy/quota", {}), {}),
        ("item", _toggle_text,
         lambda: _post("/api/proxy/stop" if _st().get("running")
                       else "/api/proxy/start"), {}),
        ("item", "切换为代理模式",
         lambda: _post("/api/proxy/mode", {"mode": "proxy"}), {}),
        ("item", "切换为直连模式",
         lambda: _post("/api/proxy/mode", {"mode": "direct"}), {}),
        ("item", "压缩模式", None, {"submenu": _hr_items()}),
        # 对抗审 a206A：CCR 菜单退役（同 tray_menu_items 注）
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
    """启动代理时开 tooltip 刷新线程（主托盘由 tray.py 管理，这里只写 title）。
    worker 形态跳过：worker 进程没有托盘（tray 在主进程），tooltip 线程
    在 worker 里只会空转（set_tip 无接收方）。"""
    global _tray_tip_thread
    if os.environ.get("CLAUDE_WORKER") == "1":
        return
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
def ensure_direct_if_proxy_down(origin="startup"):
    """base_url 指向自家代理但对应入口没在跑 → 立即恢复直连。

    工具启动自愈与 claude 会话启动前（claude_harness HarnessSession.start）
    共用：强杀后 base_url 卡在自家代理端口，用户不点「启动代理」
    直接开 Claude 会话时，claude 进程读到的就是死端口——起进程前先修好。
    按 base_url 实际指向验活（bili 入口按 /bili/ 特征判）。幂等；直连
    base_url 时零开销直接返回。
    """
    try:
        cur = _bmgr.read_current_url()
        if not _is_own_proxy_url(cur):
            return False
        # 对抗审 a206A P1：原 ":8787" 子串对新 URL（18788）永不命中——bili 崩
        # 溃后自愈实际去 ping 37349，CC 永久连死端口。URL 特征判 "/bili/"
        alive = _bili.ping_existing() if "/bili/" in cur else _ctl.ping_existing()
        if alive:
            return False
        # 确认接管（此时才作废排队任务——此检查每次会话启动前都跑，
        # 无条件作废会误杀刚排队的方案联动 worker）
        _bump_repoint_epoch()
        changed, _ = _bmgr.apply(_direct_url())
        log.info("自愈(%s): base_url 指向未运行的代理，已恢复直连: %s", origin, changed)
        return True
    except Exception as e:
        log.warning("自愈(%s)检查失败: %s", origin, e)
        return False


def proxy_module_init():
    """server.py start_background 时调（不自动启动代理——按需启动）：
    读记忆的压缩模式/CCR；启动自愈；建额度 worker。"""
    global _bili_mode, _ccr
    # 对抗审 a206A P0 实锤：a201 机械替换时删了赋值行没换新——load 结果
    # 成死存储，_bili_mode 恒 None：记忆 off 被静默反转、CCR 开关失灵、
    # 面板恒显"—"（活动实例 bili_mode:null 实证）。默认 on（用户拍板直接上）
    _bili_mode = load_bili_mode() or "on"
    _ccr = load_ccr()
    # v2.26：启动自愈已移除（用户定）——自愈只发生在「启动 claude 会话前」
    # （HarnessSession.start → ensure_direct_if_proxy_down），且以代理实际
    # ping 不通为前提；工具启动不代劳，避免误判用户刻意的 base_url 状态。
    # a558（SSO 锁号实锤）：额度 worker 自动登录与代理自启只发生在真应用
    # 实例（FC_APP_BOOT）。测试/临时实例（python -c 起 server、pytest
    # 导入）原先每次都自动登 Lanz——11-12 一天 43+ 次真实 SSO 登录触发
    # 风控锁号。无凭据唤醒路径不受影响（首次 POST /credentials 才建）
    if os.environ.get("FC_APP_BOOT") == "1":
        # 额度 worker（有凭据自动登录；无凭据建了等 POST 唤醒）
        _ensure_quota_worker()
        # headroom /stats 缓存线程（代理运行时 5s 拉，status 只读缓存）
        _ensure_bili_stats_thread()
    # a251（用户需求：开启后保存开启状态）：上次代理在跑（记忆 autostart）
    # → 后台自动拉起（延迟避开启动高峰；失败只记日志，不阻塞不弹窗）。
    # 压缩模式按记忆文件自动带上（瞬时失败不再抹记忆，见 start/apply 的
    # 失败回退——记忆的是用户偏好，实际拉不起来时运行态回退 off+留证）
    if os.environ.get("FC_APP_BOOT") == "1" and load_proxy_autostart():
        def _auto_restore():
            time.sleep(6)
            try:
                ok, msg = start_proxy()
                log.info("代理自启恢复: %s (%s)", "成功" if ok else "失败", msg)
            except Exception as e:
                log.warning("代理自启恢复异常: %s", e)
        threading.Thread(target=_auto_restore, daemon=True).start()
    # atexit 兜底回滚（Ctrl-C/强杀等 proxy_shutdown 没走的路径）
    atexit.register(_atexit_rollback)


def _atexit_rollback():
    """atexit 兜底：进程退出时若 base_url 还指着自家代理 → 回直连。"""
    try:
        cur = _bmgr.read_current_url()
        if _is_own_proxy_url(cur):
            if not (_ctl.ping_existing() or _bili.ping_existing()):
                _bmgr.apply(_direct_url())
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
    # 对抗审 a206A P2：回滚先行——原顺序先停 bili（proc.wait 可达 5s）再回
    # base_url，退出窗口内 CC 请求打死端口。先切直连（毫秒级）再停进程
    try:
        if force_rollback or _autoswitched:
            _bmgr.apply(_direct_url())
            _autoswitched = False
    except Exception:
        pass
    try:
        _bili.stop()
        # 同步停 server（阻塞 ~0.2s 确保端口释放）
        srv = _ctl.server
        ev = _ctl.stop_event
        if srv is not None and ev is not None and not ev.is_set():
            _ctl.server = None
            _ctl.stop_event = None
            core.stop_server(srv, ev)
        if force_rollback or _autoswitched:
            _bmgr.apply(_direct_url())
            _autoswitched = False
            log.info("退出时已切回直连 (force=%s)" % force_rollback)
    except Exception as e:
        log.error("proxy 退出收尾出错: %s", e)


# ---- Flask 蓝图 ---------------------------------------------------------
proxy_bp = Blueprint("proxy", __name__)


@proxy_bp.route("/api/proxy/ensure", methods=["POST"])
def _api_proxy_ensure():
    """开启 Claude 联动：确保重试代理在跑（无则后台拉起，无 headroom，
    30s 未就绪自动回退直连）。fire-and-forget，立即返回。"""
    try:
        ensure_proxy_for_claude()
    except Exception as e:
        log.warning("ensure 代理失败: %s", e)
    return jsonify({"ok": True, "msg": "已确保代理（后台）"})


# ---- 代理状态事件推送（SSE）：状态变化点广播信号，前端收到后拉一次
# /api/proxy/status 同步显示——取代前端轮询（用户定：事件通知不轮询） ----
_proxy_sse_clients = []          # queue.Queue 列表（每个 SSE 连接一个）
_proxy_sse_lock = threading.Lock()


def _proxy_notify():
    """向所有 SSE 客户端广播「状态变了」信号（轻量信号，状态本体前端自拉）。"""
    with _proxy_sse_lock:
        clients = list(_proxy_sse_clients)
    for q in clients:
        try:
            q.put_nowait({"type": "proxy_state"})
        except Exception:
            pass


@proxy_bp.route("/api/proxy/events")
def _api_proxy_events():
    """SSE：代理状态变化通知流。连接即挂起，15s 心跳注释行防中间层断链。"""
    from queue import Queue, Empty
    q = Queue()
    with _proxy_sse_lock:
        _proxy_sse_clients.append(q)

    def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Empty:
                    yield ": ping\n\n"
        finally:
            with _proxy_sse_lock:
                try:
                    _proxy_sse_clients.remove(q)
                except ValueError:
                    pass

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@proxy_bp.route("/api/proxy/status")
def _api_status():
    # 状态接口是面板命脉（前端 1s 轮询）——任何异常都不能 500：500 会让
    # 前端 _poll 整轮静默跳过，面板冻结在初始 STOPPED（用户实锤：代理实际
    # 在跑、settings.json 都切过去了，面板却毫无变化）。降级返回错误字段。
    try:
        return jsonify(_status_payload())
    except Exception as e:
        log.exception("status 组装失败")
        return jsonify({"ok": False, "status_err": str(e),
                        "status": "ERR", "running": _ctl.running})


def _status_payload():
    snap = _ctl.snapshot() if _ctl.running else None   # 判活与 start_proxy 同源
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
    # a239（第5轮A3-P3-9）：判活结果 2s 缓存——18788/37349 被「accept 不响应」
    # 的本机进程占住时，ping 两连发 1s 超时会让 3s 轮询的 status 请求持续
    # 堆积；数据面已有 5s stats 缓存同款思路
    _now = time.time()
    if _liveness_cache["ts"] < _now - 2:
        _ar = (not _ctl.running and _ctl.port_in_use() and _ctl.ping_existing())
        _liveness_cache.update(ts=_now, already=_ar, busy=(not _ctl.running and _ctl.port_in_use() and not _ar))
    data = {
        "ok": True,
        "running": _ctl.running,
        "already_running": _liveness_cache["already"],
        "port_busy": _liveness_cache["busy"],
        "status": st,
        "snapshot": snap,
        "base_url": _bmgr.read_current_url(),
        "direct_url": _direct_url(),
        # 链路显示「真正的上游」（用户实锤批注：不能写死）——代理在跑时以
        # server 实际转发目标为准（启动后上游烘死在 server 里，与 _direct_url
        # 推导值脱节时显示真实值）；没跑时才用推导值。
        "upstream": ("%s:%d" % (_ctl.server.upstream_host,
                                _ctl.server.upstream_port)
                     if _ctl.running and _ctl.server is not None
                     else "%s:%d" % _upstream_of(_direct_url())[:2]),
        "bili_mode": _bili_mode,
        "bili_running": _bili.running if _bili_mode != "off" else False,
        "bili_switching": _bili_switching,
        "bili_last_err": _bili_last_err,   # a203：切换失败原因（前端弹窗展示）
        "ccr": _ccr,
        # v2.27.20：重试策略当前值（面板「重试配置」按钮文案用——原独立
        # 工具有此配置入口，合入面板时漏了，用户实锤「配置接口没了」）
        "retry_cfg": dict(core.RETRY_CFG),
        # v2.2.2：同事机无 headroom 时 _detect 返回 None，exists(None) 抛
        # TypeError 炸掉整个 status（面板「状态获取失败」）——先判 None
        "bili_ready": bool(BILI_NODE and BILI_ENTRY),
        # a407：联网安装进度（唯一入口=代理面板；running/log 驱动前端按钮态）
        "bili_install": {"running": _bili_inst["running"],
                         "done": _bili_inst["done"],
                         "ok": _bili_inst["ok"],
                         "err": _bili_inst["err"],
                         "log": _bili_inst["log"][-12:]},
        "bili_stats": _bili_stats_cache,
        "quota_kind": qkind,
        "quota_payload": qpayload,
        "quota_login": qlogin,
        "quota_user": (qlogin or {}).get("user") if qlogin else None,
        "quota_auto": _quota._auto if _quota is not None else True,
        # a448：自动重登是独立开关（与「自动刷新」互不替代）
        "quota_auto_relogin": (_quota._auto_relogin
                               if _quota is not None else True),
        "has_credentials": cred is not None,
        "quota_username": (cred or {}).get("username"),
        # a448（用户实锤：密码框永远是占位符，看不到已保存的密码）：
        # 凭据本来就明文存本地 lanz_credentials.json，界面却没回填——用户
        # 每次都要重打。只在有凭据时回传，前端仅填空框、保持 type=password。
        "quota_password": (cred or {}).get("password"),
        "quota_ts": qts,
    }
    if ov:
        data["quota_overview"] = ov
        try:
            data["quota_models"] = _quota_model_rows(ov)
        except Exception:
            pass   # 额度明细格式异常不拖死整个 status
    if rank:
        data["quota_rank"] = rank
    # a442（用户需求）：模型负载。只在「API 是 lanz」且已存凭据时给——不是
    # lanz 网关（如智谱）时这份数据无意义，前端据此决定是否显示负载列。
    # 不依赖 quota_login 状态：负载查询自己登录（20s 缓存兜住频率），
    # worker 没跑过时也能出数（首次开面板即见）。
    # a456：默认先给 False 再尝试置 True——异常分支（_is_lanz_api 抛错等）
    # 被外层 except 吞掉时字段仍在，前端不会因此退回「加载中」死等。
    data["model_loads_supported"] = False
    try:
        # a453（第二轮审计 P2）：同时下发「本上游是否支持负载」。原来只有
        # 有数据/有错误时才带字段，非 lanz 网关（智谱等）两者都缺——前端无法
        # 区分「不支持」与「还没到」，悬浮卡会永久停在「负载加载中…」。
        if _is_lanz_api() and _get_credentials():
            data["model_loads_supported"] = True
            loads, lerr = _get_model_loads()
            if loads or lerr:
                data["model_loads"] = loads
                data["model_loads_err"] = lerr
                data["model_loads_ts"] = _quota_loads_ts
    except Exception:
        pass   # 负载异常不拖死 status（面板命脉）
    return data




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
    # ccr 缺省 None=不改（apply_bili_mode 内部判），配置弹窗一次带 {mode, ccr} 同改
    ok, msg = apply_bili_mode(j.get("mode", ""), ccr=j.get("ccr"))
    return jsonify({"ok": ok, "msg": msg})


@proxy_bp.route("/api/proxy/bili_install", methods=["POST"])
def _api_bili_install():
    """a407：billion-context 唯一安装入口——联网 npm 全局装（异步，进度走
    /api/proxy/status 的 bili_install 字段）。已在跑/已装幂等处理"""
    if BILI_NODE and BILI_ENTRY:
        return jsonify({"ok": True, "msg": "已安装，无需重复"})
    if _bili_inst["running"]:
        return jsonify({"ok": True, "msg": "安装进行中"})
    _bili_inst.update(running=True, done=False, ok=False, err="", log=[])
    import threading as _th
    _th.Thread(target=_bili_install_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "安装已启动（联网下载）"})


@proxy_bp.route("/api/proxy/retry", methods=["GET", "POST"])
def _api_retry():
    """重试策略配置（原独立工具「重试配置」弹窗的能力回归）。
    GET 读当前值；POST 校验后写 retry_config.json + 热更 RETRY_CFG——
    core 的 backoff_wait/check_retry_cap 每次调用都读 RETRY_CFG，
    正在运行的代理立即生效，无需重启。字段缺省=不改该字段。"""
    if request.method == "GET":
        return jsonify({"ok": True, "cfg": dict(core.RETRY_CFG),
                        "file": core.retry_config_file()})
    j = request.get_json(silent=True) or {}
    cfg = dict(core.RETRY_CFG)
    try:
        if "max_attempts" in j:
            v = int(j["max_attempts"])
            if v < 0:
                raise ValueError("上限次数不能为负")
            cfg["max_attempts"] = v
        if "max_retry_seconds" in j:
            v = float(j["max_retry_seconds"])
            if v < 0:
                raise ValueError("最大时长不能为负")
            cfg["max_retry_seconds"] = v
        if "max_backoff_seconds" in j:
            v = float(j["max_backoff_seconds"])
            if not (0.1 <= v <= 3600):
                raise ValueError("退避封顶需在 0.1~3600 秒")
            cfg["max_backoff_seconds"] = v
        if "backoff_enabled" in j:
            cfg["backoff_enabled"] = bool(j["backoff_enabled"])
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "msg": "参数非法：%s" % e})
    try:
        path = core.retry_config_file()
        # a623R（审计 #12）：tmp 提前置 None——原来 makedirs 抛 OSError 时
        # tmp 还没赋值，except 里 os.remove(tmp) 二次 UnboundLocalError，
        # 真错误被 500 笼统掩盖（_save_marks 同文件里是现成的正确写法）
        tmp = None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # a602：原子写（裸 "w" 直写期间镜像线程会读到半截 JSON）
        tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _replace_retry(tmp, path)
        _notify_mirror(os.path.basename(path))
    except OSError as e:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return jsonify({"ok": False, "msg": "写入失败：%s" % e})
    core.RETRY_CFG.update(cfg)   # 热更（与 reload 等价，少一次盘读）
    log.info("重试策略已更新: %s", cfg)
    return jsonify({"ok": True, "cfg": dict(core.RETRY_CFG), "file": path})


@proxy_bp.route("/api/proxy/ccr", methods=["POST"])
def _api_ccr():
    j = request.get_json(silent=True) or {}
    ok, msg = apply_bili_mode(_bili_mode, ccr=bool(j.get("on")))
    return jsonify({"ok": ok, "msg": msg})


@proxy_bp.route("/api/proxy/quota", methods=["POST"])
def _api_quota_refresh():
    if not HAS_LANZ or _quota is None:
        return jsonify({"ok": False, "msg": "额度模块不可用（缺 pycryptodome）"})
    j = request.get_json(silent=True) or {}
    if "auto" in j:
        # 自动刷新开关（GUI checkbox 平移）：{auto: bool}
        # a448：只管「每 10 分钟拉额度」，与自动重登解耦
        _quota.set_auto(bool(j.get("auto")))
        return jsonify({"ok": True, "msg": "自动刷新已开启（10min）" if j.get("auto")
                        else "自动刷新已关闭"})
    if "auto_relogin" in j:
        # a448（用户令）：自动重登独立开关，与「自动刷新」互不影响
        on = bool(j.get("auto_relogin"))
        _quota.set_auto_relogin(on)
        return jsonify({"ok": True,
                        "msg": "自动重登已开启（登录失败时按退避重试）" if on
                        else "自动重登已关闭（登录失败后等你手动强制重登）"})
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
        manual = False
        try:   # 登出只清 SSO 账号字段：机器人已是独立的凭证形态，与账号
               # 解耦——登出不停它、不删 app_secret（用户拍板）
            from src import hiklink_bot
            manual = hiklink_bot.is_manual_mode()
            hiklink_bot.clear_account()
        except Exception:
            pass
        return jsonify({"ok": True, "msg": "已断开登录（机器人不受影响）"
                        if manual else "已断开登录"})
    user = (j.get("username") or "").strip()
    pwd = j.get("password") or ""
    if not user or not pwd:
        return jsonify({"ok": False, "msg": "用户名/密码不能为空"})
    # v2.2.2：写盘失败显式报错——旧版静默 500 + 前端乐观渲染「已登录」，
    # 实际凭据没落盘，重启就要重登（同事机实锤）。绝不能继续激活机器人。
    try:
        lanz_quota.save_credentials(LANZ_CRED_PATH, user, pwd)
    except Exception as e:
        log.exception("凭据写入失败")
        return jsonify({"ok": False,
                        "msg": "凭据写入失败：%s（数据目录不可写？检查工具"
                               "所在目录权限，或把 exe 拷到普通目录运行）" % e})
    _invalidate_cred_cache({"username": user, "password": pwd})
    _quota.submit_credentials(user, pwd)
    bot_msg = ""
    try:   # 机器人已收敛为凭证登录单形态：账号登录不再激活机器人，
        # 只按实际结果如实回报（此前无条件回「机器人已激活」）
        from src import hiklink_bot
        _ok, _bm = hiklink_bot.ensure_started()
        if _ok:
            bot_msg = _bm
        else:
            # 「机器人未启用」语义要保留（冒号而非括号，避免双层括号），
            # 否则用户会误以为机器人已随登录启用
            bot_msg = "机器人未启用：" + (_bm or "无凭据")
    except Exception as e:
        log.warning("登录后激活机器人异常: %s", e)
    return jsonify({"ok": True,
                    "msg": "已保存，开始登录" + ("；" + bot_msg if bot_msg else "")})
