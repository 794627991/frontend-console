# -*- coding: utf-8 -*-
"""首次启动依赖自检 + 缺库安装引导（源码分发场景）。

背景：工程以源码 zip 分发时，对方机器需要 Python + 一组 pip 库。
必需库（Flask/pyserial/pywebview）缺了工具根本起不来；可选库（paramiko/pywinpty）
缺了对应功能不可用。exe 分发不受影响（PyInstaller 已全收）。

流程（main.py 在 import server/webview 之前调用）：
  1. check_deps() 逐库 importlib 探测 → (缺的必需库, 缺的可选库)
  2. 缺库时起一个原生 pywebview 引导窗口（同款深色 UI + 进度动画），
     js_api 把 pip 安装进度实时推给页面
  3. 装完用户点「继续启动」→ 关窗，延迟拉起新进程重新走 main
     （新装的库必须重新 import——同进程补 import 不可靠，重启最干净）

pip 兜底链（每库独立走，任何一级成功即停）：
  离线 wheel（pydeps/，离线包带的）→ 默认源 → 清华镜像
pywebview 自身缺失时：先静默 pip 补装再 execv 重启进引导；彻底失败用
Win32 MessageBox 弹手动安装命令（pythonw 无控制台，print 根本看不见）。

翻车记录（v2.30 修复）：on_loaded 里 win.focus() —— pywebview 6.x 的
Window.focus 是 bool 属性不是方法（snip.py 同款坑），调用即 TypeError，
而事件线程吞异常 + pythonw 日志进 nul → install_all 永远不跑 → 界面恒
「待安装 0%」、pip 一次不执行，只能关窗 execv 重启再卡，死循环。
教训：loaded 处理器里除 install_all 外的任何步骤都必须 try 包住。
"""
import os
import sys
import subprocess
import importlib
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 依赖清单：pip 名 → (import 名, 是否必需, 中文用途说明)
# 顺序即安装顺序（Flask 最先——装完第一件事就是让它能起）
DEPS = [
    ("flask",     ("flask",    True,  "HTTP 后端服务")),
    ("pyserial",  ("serial",   True,  "串口连接")),
    ("pywebview", ("webview",  True,  "桌面窗口（WebView2）")),
    ("paramiko",  ("paramiko", False, "SSH 远程连接")),
    ("pywinpty",  ("winpty",   False, "内嵌 Claude 终端（ConPTY）")),
    # a356 紧急回撤（用户实锤：内网机打不开工具）：pyelftools 曾列入本表——
    # 但本闸门对可选库缺失同样阻断启动（missing=req+opt 全进引导页），
    # 内网无外网 pip 装不上 → 工具永远卡在首启安装页。跳转索引（nav_index）
    # 对缺库本就自动降级（符号层跳过、白名单照常）——预装毫无必要；
    # 需要时随 .fcpk 资源包的 pydeps 离线装。严禁再把非命脉库加进本表
]

# 清华镜像（默认源失败时兜底：无网/超时/被墙设备常见）
_MIRROR_ARGS = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]

_pip_checked = False   # ensurepip 只补一次


def check_deps():
    """逐库探测。返回 (missing_required, missing_optional)——元素是 (pip名, 用途)。"""
    miss_req, miss_opt = [], []
    for pip_name, (mod_name, required, desc) in DEPS:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            (miss_req if required else miss_opt).append((pip_name, desc))
    return miss_req, miss_opt


# ---- pip 安装（带回退链）----

def _subprocess_hidden(cmd, timeout=600):
    """跑子进程但不闪控制台黑框（pythonw 源码分发场景）。"""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _ensure_pip():
    """python -m pip 可用性兜底：极简 Python 无 pip 时 ensurepip 补一次。"""
    global _pip_checked
    if _pip_checked:
        return True
    _pip_checked = True
    try:
        if _subprocess_hidden([sys.executable, "-m", "pip", "--version"], 60).returncode == 0:
            return True
    except Exception:
        return False
    try:
        _subprocess_hidden([sys.executable, "-m", "ensurepip", "--upgrade"], 300)
        return _subprocess_hidden([sys.executable, "-m", "pip", "--version"], 60).returncode == 0
    except Exception:
        return False


def _wheels_dir():
    """离线 wheel 目录：仓库根 pydeps/（源码分发场景手工放置的 wheel）。
    .fcpk 资源包的 pydeps kind 由 res_install 直接交给 pip --find-links，
    不落这个目录。存在且含 wheel 才返回，否则 None。"""
    d = os.path.join(_ROOT, "pydeps")
    try:
        if os.path.isdir(d) and any(
                f.endswith((".whl", ".tar.gz")) for f in os.listdir(d)):
            return d
    except Exception:
        pass
    return None


def _pip_install(pip_name):
    """单库安装，回退链：离线 wheel（若有）→ 默认源 → 清华镜像。
    返回 (ok, 尾行消息)——失败消息给页面日志区展示。"""
    if not _ensure_pip():
        return False, "pip 不可用且 ensurepip 补装失败"
    attempts = []
    wd = _wheels_dir()
    if wd:
        attempts.append(["--no-index", "--find-links", wd])
    attempts.append([])
    attempts.append(list(_MIRROR_ARGS))
    last_msg = ""
    for extra in attempts:
        try:
            r = _subprocess_hidden(
                [sys.executable, "-m", "pip", "install", "--no-input",
                 "--timeout", "30"] + extra + [pip_name])
        except Exception as e:
            last_msg = f"pip 异常: {e}"
            continue
        if r.returncode == 0:
            return True, ""
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        last_msg = tail[-1][:200] if tail else f"pip 返回码 {r.returncode}"
    return False, last_msg


# ---- 启动自检（每机一次）：config 标记 deps_selftest_ok ----
def _selftest_flag_path():
    """标记文件与 config.json 同目录（app_state.HOME_DIR）——源码/打包两态同一路径。"""
    try:
        from src.app_state import HOME_DIR
        return os.path.join(HOME_DIR, "deps_selftest.json")
    except Exception:
        # app_state 依赖 flask 之外的纯标准库，但保险起见给独立回退
        return os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                            "deps_selftest.json")


def selftest_once():
    """启动早期调用（main.py，在 bootstrap_if_needed 之后）：
    探测一轮依赖，全通过 → 写标记，此后启动不再测（用户要求：只一次）。
    有缺失 → 返回缺失清单给调用方弹提醒（每启动都提醒，除非用户用离线包补装）。
    返回 (ok, miss_req, miss_opt, skipped)。"""
    flag = _selftest_flag_path()
    # 标记存在且值 ok → 不再测
    try:
        import json
        with open(flag, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("ok"):
            return True, [], [], True   # skipped：之前测过，直接放行
    except Exception:
        pass
    miss_req, miss_opt = check_deps()
    if not (miss_req or miss_opt):
        try:
            import json
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            with open(flag, "w", encoding="utf-8") as f:
                json.dump({"ok": True, "ts": time.time()}, f)
        except Exception:
            pass
        return True, [], [], False
    return False, miss_req, miss_opt, False


def mark_selftest_ok():
    """离线包补装依赖成功后调用：写标记，后续启动不再弹提醒。"""
    try:
        import json
        flag = _selftest_flag_path()
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        with open(flag, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "ts": time.time()}, f)
    except Exception:
        pass


def _install_page_html(missing, base_url_assets=""):
    """安装引导页（同款深色 UI + 进度条动画）。纯内联，不依赖 web/（它可能还没法服务）。"""
    import html as _h
    items = "".join(
        f'<div class="dep-item" data-dep="{_h.escape(p)}">'
        f'<span class="dep-name">{_h.escape(p)}</span>'
        f'<span class="dep-desc">{_h.escape(d)}</span>'
        f'<span class="dep-status">待安装</span></div>'
        for p, d in missing
    )
    pip_cmd = "pip install " + " ".join(p for p, _ in missing)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>首次启动 · 安装依赖</title>
<style>
  :root {{
    --bg: #0d1524; --bg-card: #182238; --border: #243654; --border-glow: #2a4a7a;
    --fg: #dbe7f5; --fg-bright: #f2f7fd; --muted: #6d7f9d; --accent: #00d4ff;
    --danger: #ff5f6e; --ok: #3ddc97;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--fg);
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    display: flex; align-items: center; justify-content: center; height: 100vh; }}
  .box {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
    width: 460px; max-width: 92vw; padding: 26px 28px; box-shadow: 0 8px 40px rgba(0,0,0,.45); }}
  h1 {{ font-size: 16px; color: var(--fg-bright); display: flex; align-items: center; gap: 8px; }}
  h1 .icon {{ font-size: 20px; }}
  .sub {{ font-size: 12px; color: var(--muted); margin: 6px 0 18px; }}
  .dep-item {{ display: flex; align-items: center; gap: 10px; padding: 8px 10px;
    border: 1px solid transparent; border-radius: 8px; font-size: 12px; margin-bottom: 6px;
    background: rgba(255,255,255,.02); }}
  .dep-item .dep-name {{ font-family: Consolas, monospace; color: var(--accent); font-weight: 600; width: 82px; }}
  .dep-item .dep-desc {{ color: var(--muted); flex: 1; }}
  .dep-item .dep-status {{ font-size: 11px; color: var(--muted); }}
  .dep-item.installing .dep-status {{ color: var(--accent); }}
  .dep-item.installing .dep-status::after {{ content: "…安装中"; }}
  .dep-item.done .dep-status {{ color: var(--ok); }}
  .dep-item.done .dep-status::after {{ content: "✓ 已安装"; }}
  .dep-item.failed .dep-status {{ color: var(--danger); }}
  .dep-item.failed .dep-status::after {{ content: "✗ 失败"; }}
  .progress {{ height: 4px; background: rgba(255,255,255,.06); border-radius: 2px;
    margin: 16px 0 6px; overflow: hidden; }}
  .progress .bar {{ height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), #4da6ff);
    border-radius: 2px; transition: width .3s ease;
    background-size: 200% 100%; animation: shimmer 1.2s linear infinite; }}
  @keyframes shimmer {{ 0% {{ background-position: 0 0; }} 100% {{ background-position: -200% 0; }} }}
  .pct {{ font-size: 11px; color: var(--muted); text-align: right; }}
  .spinner {{ display: inline-block; width: 12px; height: 12px; vertical-align: -2px;
    border: 2px solid rgba(0,212,255,.2); border-top-color: var(--accent);
    border-radius: 50%; animation: spin .8s linear infinite; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .log {{ margin-top: 12px; max-height: 110px; overflow-y: auto; background: rgba(0,0,0,.35);
    border-radius: 6px; padding: 8px 10px; font-family: Consolas, monospace;
    font-size: 10px; line-height: 1.5; color: var(--muted); white-space: pre-wrap; }}
  .log .errline {{ color: var(--danger); }}
  .btn {{ margin-top: 16px; width: 100%; padding: 9px 0; border-radius: 8px; border: none;
    background: var(--accent); color: #04202e; font-size: 13px; font-weight: 600;
    cursor: pointer; opacity: .45; pointer-events: none; transition: opacity .2s; }}
  .btn.ready {{ opacity: 1; pointer-events: auto; }}
  .manual {{ margin-top: 12px; font-size: 11px; color: var(--muted); display: none; }}
  .manual code {{ display: block; margin-top: 4px; padding: 6px 8px; background: rgba(0,0,0,.35);
    border-radius: 6px; font-size: 10px; color: var(--fg); user-select: text;
    font-family: Consolas, monospace; word-break: break-all; }}
</style></head>
<body>
<div class="box">
  <h1>首次启动 · 安装依赖</h1>
  <div class="sub">检测到缺少以下运行库，正在自动安装（约 1~2 分钟，仅需一次）</div>
  <div id="list">{items}</div>
  <div class="progress"><div class="bar" id="bar"></div></div>
  <div class="pct" id="pct">0%</div>
  <div class="log" id="log"></div>
  <button class="btn" id="goBtn" onclick="goOn()">继续启动</button>
  <div class="manual" id="manual">
    自动安装失败（多为网络不通/需要代理）。请手动在命令行执行后，点上方「继续启动」：
    <code>{_h.escape(pip_cmd)}</code>
  </div>
</div>
<script>
  const total = {len(missing)};
  let installed = 0;
  function setDep(pip, cls) {{
    const el = document.querySelector('[data-dep="' + pip + '"]');
    if (el) {{ el.className = 'dep-item ' + cls; }}
  }}
  function bump() {{
    installed++;
    const pct = Math.round(installed / total * 100);
    document.getElementById('bar').style.width = pct + '%';
    document.getElementById('pct').textContent = pct + '%';
    if (installed >= total) {{
      document.getElementById('goBtn').classList.add('ready');
    }}
  }}
  function log(line, isErr) {{
    const el = document.getElementById('log');
    const d = document.createElement('div');
    if (isErr) d.className = 'errline';
    d.textContent = line;
    el.appendChild(d);
    el.scrollTop = el.scrollHeight;
  }}
  window._onProgress = (pip, ok, msg) => {{
    setDep(pip, ok ? 'done' : 'failed');
    if (msg) log(msg, !ok);
    if (!ok) document.getElementById('manual').style.display = 'block';
    bump();
  }};
  function goOn() {{ pywebview.api.finish(); }}
</script>
</body></html>"""


class _BootstrapAPI:
    """pywebview js_api：安装进度回调 + 结束按钮。

    pip 在后台线程跑，每装完一个库 evaluate_js 推一行进度到页面。
    finish() 置 Event，main 等 Event 后 os.execv 重启进程（新装的库
    必须重新 import——execv 不留半初始化状态，最干净）。
    """

    def __init__(self, window_holder, missing):
        self._holder = window_holder      # {win: window}——避免循环引用的容器
        self._missing = missing
        self.done_evt = None              # main 注入

    def _js(self, code):
        """evaluate_js 包装：任何异常吞掉。进度推送绝不能反过来打断安装线程。"""
        w = self._holder.get("win")
        if not w:
            return
        try:
            w.evaluate_js(code)
        except Exception:
            pass

    def _push(self, pip, ok, msg):
        """一个库安装完成：更新该行状态 + 计数进进度条。"""
        self._js(f"_onProgress({pip!r}, {str(ok).lower()}, {msg!r})")

    def _mark(self, pip):
        """一个库开始安装：仅置「…安装中」样式，不计进度（此前误推 done
        会把没装的库标成 ✓ 并虚增进度，页面就永远停在假完成态）。"""
        self._js(f"setDep({pip!r}, 'installing')")

    def install_all(self):
        """逐库 pip install（线程里跑）。必须先装必需库；失败继续装后面的（用户能看到全部结果）。"""
        import threading
        def worker():
            for pip_name, _desc in self._missing:
                self._mark(pip_name)
                ok, msg = _pip_install(pip_name)
                self._push(pip_name, ok, msg)
            if self.done_evt:
                self.done_evt.set()
        threading.Thread(target=worker, daemon=True).start()

    def finish(self):
        """用户点「继续启动」：关窗（webview.start 返回 → main execv 重启）。
        done_evt 仅留作状态探针——main 阻塞在 webview.start()，没人等它。"""
        if self.done_evt:
            self.done_evt.set()
        w = self._holder.get("win")
        if w:
            try:
                w.close()
            except Exception:
                try:
                    w.destroy()
                except Exception:
                    pass
        return True


def run_bootstrap(missing):
    """起安装引导窗口，等用户点继续。返回 True 表示流程应继续（重启进程）。"""
    import webview
    holder = {}
    api = _BootstrapAPI(holder, missing)
    html_str = _install_page_html(missing)
    win = webview.create_window(
        title="首次启动 · 安装依赖",
        html=html_str,
        width=500, height=560,
        resizable=False,
        js_api=api,
    )
    holder["win"] = win

    import threading
    api.done_evt = threading.Event()

    def on_loaded():
        # show/focus 这类窗口操作任何一步失败都不能挡住安装线程
        # （翻车记录见文件头注释——focus 在 pywebview 6 是 bool 属性）。
        # 窗口本身 focus=True 创建时已聚焦，无需额外置前。
        try:
            win.show()
        except Exception:
            pass
        api.install_all()

    win.events.loaded += on_loaded
    # 引导窗不写 private_mode（一次性窗口，无需持久化）
    webview.start()
    # 窗口关闭（用户点继续或直接关窗）→ 主流程继续
    return True


def _message_box(text):
    """pythonw 下唯一可见的原生 UI（无任何第三方依赖，仅 Win32）。"""
    try:
        import ctypes
        # MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        ctypes.windll.user32.MessageBoxW(0, text, "前端控制台 · 依赖安装", 0x50040)
    except Exception:
        pass


def _restart_process():
    """延迟 1.5s 拉起新进程替代 os.execv：execv 的子进程可能抢在父进程
    完全退出前启动，撞上父进程还握着的单实例 mutex → 走「聚焦旧实例」
    分支静默自灭（实测踩过：pythonw 下重启后进程凭空消失）。延迟到爹
    死透了再起，mutex 已释放，干净接管。"""
    code = ("import subprocess,sys,time;time.sleep(1.5);"
            "subprocess.Popen(sys.argv[1:])")
    try:
        subprocess.Popen(
            [sys.executable, "-c", code, sys.executable] + sys.argv,
            cwd=os.getcwd(),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False


def bootstrap_if_needed():
    """main.py 启动早期调用。缺库时引导安装并重启进程；不缺直接返回继续启动。
    返回 True = 应继续启动；False = 已重启/应退出（调用方 return）。
    a356 铁律：只有**必需库**缺失才进引导安装——可选库（paramiko/pywinpty）
    缺失只 print 提示、绝不阻断启动（pyelftools 内网事故的根因就是可选库
    也被算进 missing 拉起引导页，无外网装不上=工具永远打不开）。"""
    miss_req, miss_opt = check_deps()
    if miss_opt:
        print("[deps] 可选库缺失（不阻断，需要时用离线资源包补装）：%s"
              % ", ".join(p for p, _ in miss_opt))
    missing = miss_req
    if not missing:
        return True

    # pywebview 自身缺失时无法弹 GUI：静默 pip 补装 → 重启进正常引导。
    # （旧版只 print + input()——pythonw 下无控制台，用户看到的就是双击后毫无反应）
    try:
        importlib.import_module("webview")
    except ImportError:
        ok, msg = _pip_install("pywebview")
        if ok and _restart_process():
            return False
        pip_cmd = "pip install " + " ".join(p for p, _ in missing)
        text = ("依赖自动安装失败（%s）。请手动在命令行执行后重新启动本工具：\n\n    %s"
                % (msg or "网络不通/需要代理", pip_cmd))
        print("=" * 56)
        print(text)
        print("=" * 56)
        _message_box(text)
        return False

    run_bootstrap(missing)
    # 窗口关闭（用户点继续或直接关窗）后重启进程：新装的库必须重新 import
    # （已加载的模块表里没有它们）。
    if _restart_process():
        return False
    # 重启失败（极少见）——退化为提示重启
    print("依赖安装流程结束，请重新启动本工具。")
    try:
        input("按回车退出…")
    except Exception:
        pass
    return False
