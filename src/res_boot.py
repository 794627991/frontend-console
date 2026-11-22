# -*- coding: utf-8 -*-
"""离线资源探测（v4.1 / Electron 换壳 P4）。

安装包自足：Python 运行时随 PyInstaller、Chromium 随 Electron——不再有
WebView2/.NET 启动硬闸，也没有「建不出窗口」的引导链。本模块只服务可选
外部集成的状态探测与离线包清单：Node/npm、Git、Claude Code CLI、
OnlyOffice、pydeps、codegraph，以及 bili 存量探测。前端设置页「外部依赖
安装」与 /api/resources/status 读这里。

纯探测逻辑不碰 UI，可单测。
"""
import json
import os
import shutil
import struct
import subprocess
import sys

from src import app_state as _st

# 统一资源清单（唯一真源：后端探测、前端呈现、离线包表三者同口径）
MANIFEST = [
    {"kind": "node", "name": "Node.js / npm", "hard": False,
     "fix": "离线资源包内静默安装"},
    {"kind": "git", "name": "Git", "hard": False,
     "fix": "离线资源包内静默安装"},
    {"kind": "claude", "name": "Claude Code CLI", "hard": False,
     "fix": "离线资源包内复制安装"},
    {"kind": "pydeps", "name": "工具 Python 依赖", "hard": False,
     "fix": "在线安装（pip）或离线资源包内 wheel 补装"},
    # a309R：OnlyOffice DS（word/excel/ppt 全功能编辑，可选）——探测 80 口
    {"kind": "onlyoffice", "name": "OnlyOffice 全功能编辑", "hard": False,
     "fix": "离线资源包内静默安装（约 10 分钟，弹 UAC 确认）"},
    # a407（用户令）：billion-context 移出安装库（内网装不上是常态）——
    # 唯一入口=代理面板联网下载（proxy.py /api/proxy/bili_install）。
    # bili_ok() 探测保留：旧包已装机器/系统 npm 全局两种存量继续可用
    # S37-6（P3）：a360 铺了安装器但没进面板清单——外部依赖页无此项，
    # 错误文案"设置→外部依赖安装"成死路
    {"kind": "codegraph", "name": "Claude 代码图引擎（codegraph）",
     "hard": False,
     "fix": "安装离线资源包（或设置→外部依赖安装单装）"},
    # D（2026-11-23 用户拍板）：源码/调试形态离线起壳；正常发布 Setup 自带
    {"kind": "electron", "name": "Electron 运行时（源码形态）",
     "hard": False,
     "fix": "安装离线资源包（解到 offline_runtime/electron，run.bat 免 npm 直起）"},
]


def app_dir():
    """工具根目录（frozen=exe 所在目录；源码=项目根）。
    与 claude_setup._app_dir 同口径，但本模块必须在 server 未起来时也能用，
    所以不 import 那个模块（避免拉进 flask 依赖链）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------- 探测

def _which(name):
    return shutil.which(name) or ""


def probe_node():
    node = _which("node.exe") or _which("node")
    npm = _which("npm.cmd") or _which("npm")
    if node and npm:
        return "ok", _run_ver([node, "--version"]), ""
    return "missing", "", "" if not node else "缺 npm"


def probe_git():
    g = _which("git.exe") or _which("git")
    if g:
        return "ok", _run_ver([g, "--version"]), ""
    return "missing", "", ""


def probe_claude():
    try:
        from .claude_conn import _resolve_claude_exe, ClaudeNotFoundError
        exe, _shim = _resolve_claude_exe()
        # a452（审计 P1）：能解析到路径 ≠ 能跑。npm update 中途失败会把包写成
        # 半成品（入口被删/替换中），此时 _resolve 仍能命中缓存里的旧路径，
        # 装完照报成功、CLI 实际不可用。要求 --version 真有输出才算 ok。
        # a452（第二轮审计 P2）：超时/起不来 ≠ 缺安装。杀毒首扫新 exe、慢盘
        # 上 --version 常超 8s，原来一律判 missing，刚装好的 CLI 被报安装
        # 失败（install 侧据此抛 InstallError）。超时给 30s 并判 unknown。
        try:
            ver = _run_ver([exe, "--version"], timeout=30, strict=True)
        except _VerUnknown as e:
            return "unknown", "", "claude 存在但 --version 探测超时/起不来: %s" % e
        if not (ver or "").strip():
            return "missing", "", "claude 可执行文件存在但无法运行（可能安装不完整）"
        return "ok", ver, ""
    except Exception:
        return "missing", "", ""


def probe_onlyoffice():
    """OnlyOffice DS 探测：80 口 healthcheck（服务在装好的机器常驻）。
    a309R：DS 是 Windows 服务，装了即监听 80——比查目录/注册表可靠。
    性能（启动闸门实测 4041ms 的元凶）：urllib 对 "localhost" 先试 ::1
    再试 127.0.0.1，每个地址族各吃满 2s 超时——未装 DS 的机器白等 4s。
    先 socket 直连 127.0.0.1:80 快速判端口（未监听=立即 ECONNREFUSED），
    端口通了才发 HTTP。"""
    import socket
    try:
        _s = socket.create_connection(("127.0.0.1", 80), timeout=0.6)
        _s.close()
    except Exception:
        return "missing", "", ""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1/healthcheck", timeout=2) as r:
            if r.status == 200:
                return "ok", "Document Server", ""
    except Exception:
        pass
    return "missing", "", ""


def probe_pydeps():
    """工具自身 pip 依赖：只测发布包里也可能缺的那几个（exe 分发恒 ok）。
    a595 增 pycryptodome（Crypto）——fcpk 资源包解密真依赖，缺了资源包
    功能 503；早前不测导致状态恒绿、在线装 pydeps 也不补它。"""
    need = [("paramiko", "SSH"), ("winpty", "内嵌终端"),
            ("Crypto", "资源包功能")]
    miss = []
    for mod, _desc in need:
        try:
            __import__(mod)
        except ImportError:
            miss.append(mod)
    if miss:
        return "missing", "", "缺 " + "/".join(miss)
    return "ok", "", ""


def bili_ok(base=None):
    """billion-context 内置运行时是否完整（a336R 第7轮 P1-4：三处判据统一）。

    base 是 `offline_runtime` 目录（marker `.biliok` 就在它下面，树在
    `bili/`）。res_install / res_boot.probe_bili / proxy._detect_bili_cmd
    原先各写一份，任何一处改判据都会分裂成「面板说装好了、代理说没装」。
    本模块只依赖标准库，两侧都已 import 它，放这里零新增依赖。
    """
    if base is None:
        base = os.path.join(app_dir(), "offline_runtime")
    cur = os.path.join(base, "bili")
    return (os.path.isfile(os.path.join(base, ".biliok"))
            and os.path.isfile(os.path.join(cur, "node.exe"))
            and os.path.isfile(os.path.join(cur, "node_modules",
                                            "billion-context", "dist",
                                            "index.js")))


def probe_bili():
    """billion-context 引擎探测（a335R；a336R 判据并入 bili_ok）。"""
    if bili_ok():
        return "ok", "", ""
    return "missing", "", ""


def probe_electron():
    """Electron 运行时：源码形态两种落位任一命中即 ok——
    ① offline_runtime/electron/electron.exe（资源包装出）
    ② electron/node_modules/electron/dist/electron.exe（npm install 装出）。
    正常发布（Setup.exe）自带，恒不需要本项。"""
    for p in (
        os.path.join(app_dir(), "offline_runtime", "electron", "electron.exe"),
        os.path.join(app_dir(), "electron", "node_modules", "electron",
                     "dist", "electron.exe"),
    ):
        if os.path.isfile(p):
            return "ok", "", ""
    return "missing", "", "源码形态离线起壳需要（发布版 Setup 不需要）"


_PROBES = {"electron": probe_electron,
           "node": probe_node, "git": probe_git, "claude": probe_claude,
           "onlyoffice": probe_onlyoffice,
           "pydeps": probe_pydeps, "bili": probe_bili}

def _probe_codegraph():
    from src import nav_codegraph as _ncg
    if _ncg.available():
        _v = ""
        try:
            # 版本路径抄 res_install._ver 惯例：dirname(exe)/lib/package.json
            # （无 ".."——R2-9 实证三种 bundle 形态全 404）
            import json as _j
            _exe = _ncg._cg_exe() or ""
            with open(os.path.join(os.path.dirname(_exe),
                "lib", "package.json"), encoding="utf-8") as _f:
                _v = _j.load(_f).get("version", "") or ""
        except Exception:
            _v = ""
        return ("ok", _v, ("codegraph " + _v) if _v else "codegraph 已安装")
    return ("missing", "", "")
    # 契约：missing 态 detail/ver 留空——fix 指引文案由 MANIFEST.fix 渲染
    # （settings.js:867 非 ok 态 detail||fix 即命中）

_PROBES["codegraph"] = _probe_codegraph   # S37-6：三元组 (state, fix, detail)


def _run_ver(argv, timeout=8, strict=False):
    """跑一次 --version 取版本串。超时/失败返回空（探测失败≠缺失）。

    strict=True 时，超时/进程起不来抛 _VerUnknown（「没跑出结论」），
    而「跑通了但没输出」仍返回 ""（那是确定异常）。install 侧靠这个区分
    避免把慢机上的好安装误报成失败。
    """
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip().splitlines()
        if not out:
            return ""
        # "git version 2.55.0" → 2.55.0；"v24.19.0" → 24.19.0
        import re
        m = re.search(r"\d+\.\d+(?:\.\d+)?", out[0])
        return m.group(0) if m else out[0][:40]
    except Exception as e:
        if strict:
            raise _VerUnknown("%s: %s" % (type(e).__name__, e))
        return ""


class _VerUnknown(Exception):
    """--version 探测**没跑出结论**（超时/进程起不来），区别于「跑通了但没输出」。

    a452（第二轮审计 P2）：_run_ver 的 docstring 写明「超时/失败返回空
    （探测失败≠缺失）」，但 install 侧把空一律当 missing——企业杀毒首扫新
    解压的 claude.exe、慢盘上 --version 超过 8s 时，刚装好的 CLI 会被报
    「npm 装完但 claude 不可用」。三态区分由此补上。
    """


def probe_all(use_cache=True, kinds=None):
    """统一检测入口。返回
        {"ok": bool, "items": [...], "hard_missing": [...], "soft_missing": [...]}
    每项：{kind, name, hard, ok, state, ver, detail, fix}

    kinds：只探指定子集（None=全部）。全部为软项探测（含 HTTP/子进程，
    onlyoffice 实测 4s）——只在设置页/状态轮询里用，不进启动关键路径。
    """
    state_file = _state_file()
    cache = _read_state() if use_cache else {}
    cached = (cache.get("last_probe") or {}) if use_cache else {}
    items, hard_miss, soft_miss = [], [], []
    for m in MANIFEST:
        k = m["kind"]
        if kinds is not None and k not in kinds:
            continue
        c = cached.get(k)
        if c and time_ok(c.get("ts")):
            st, ver, detail = c["state"], c.get("ver", ""), c.get("detail", "")
        else:
            try:
                st, ver, detail = _PROBES[k]()
            except Exception as e:
                st, ver, detail = "unknown", "", str(e)[:80]
            cached[k] = {"state": st, "ver": ver, "detail": detail,
                         "ts": _now()}
        ok = st == "ok"
        items.append({"kind": k, "name": m["name"], "hard": m["hard"],
                      "ok": ok, "state": st, "ver": ver, "detail": detail,
                      "fix": m["fix"]})
        # a455（第三轮审计 P2）：unknown=探测没跑出结论，不是缺失。原来把它
        # 也塞进 hard/soft_missing，导致顶层 ok 变 false——慢机上「装了但
        # --version 超时」会让整包自检报不通过。
        if not ok and st != "unknown":
            (hard_miss if m["hard"] else soft_miss).append(k)
    if use_cache:
        _write_state({"last_probe": cached})
    return {"ok": not hard_miss, "items": items,
            "hard_missing": hard_miss, "soft_missing": soft_miss}


_PROBE_TTL = 60     # 探测结果缓存 60s——前端轮询不重复起子进程


def time_ok(ts):
    import datetime
    try:
        t = datetime.datetime.fromisoformat(ts)
        return (datetime.datetime.now() - t).total_seconds() < _PROBE_TTL
    except Exception:
        return False


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


_HARD = ()   # 换壳 P4：启动硬闸门已退役（Electron 自带 Chromium）
_state_lock = __import__("threading").Lock()


def _state_file():
    return os.path.join(app_dir(), "offline_runtime", ".fcpk.json")


def _read_state():
    try:
        with open(_state_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _pop_state(key):
    """锁内单键删除（对抗审二轮 P3-3：read-pop-write 快照回写会覆盖并发写）。"""
    with _state_lock:
        cur = _read_state()
        cur.pop(key, None)
        p = _state_file()
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except OSError:
            pass


def _write_state(d):
    """合并写（只覆盖给定键，别把已装清单抹掉）。锁内读改写——并发
    /status 轮询与安装收尾曾互相覆盖（对抗审 P2）。"""
    with _state_lock:
        cur = _read_state()
        cur.update(d or {})
        p = _state_file()
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except OSError:
            pass


def soft_report():
    """软资源缺失时的状态缓存（前端启动后 GET /api/resources/status 读）。
    不做任何 UI——前端负责呈现常驻红条。"""
    try:
        return probe_all(use_cache=True)
    except Exception:
        return {"ok": True, "items": [], "hard_missing": [], "soft_missing": []}
