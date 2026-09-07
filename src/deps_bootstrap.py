# -*- coding: utf-8 -*-
"""首次启动依赖自检 + 缺库安装引导（源码分发场景）。

背景：工程以源码 zip 分发时，对方机器需要 Python + 一组 pip 库。
必需库（Flask/pyserial/pywebview）缺了工具根本起不来；可选库（paramiko/pywinpty）
缺了对应功能不可用。exe 分发不受影响（PyInstaller 已全收）。

流程（main.py 在 import server/webview 之前调用）：
  1. check_deps() 逐库 importlib 探测 → (缺的必需库, 缺的可选库)
  2. 缺库时起一个原生 pywebview 引导窗口（同款深色 UI + 进度动画），
     js_api 把 pip 安装进度实时推给页面
  3. 装完用户点「继续启动」→ 窗口关闭，main 正常往下走
     （需要重启进程让新装的库可 import——直接 os.execv 重启自己最干净）

pip 网络失败兜底：页面展示手动安装命令，用户装完再继续。
"""
import os
import sys
import subprocess
import importlib

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
]


def check_deps():
    """逐库探测。返回 (missing_required, missing_optional)——元素是 (pip名, 用途)。"""
    miss_req, miss_opt = [], []
    for pip_name, (mod_name, required, desc) in DEPS:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            (miss_req if required else miss_opt).append((pip_name, desc))
    return miss_req, miss_opt


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
  <h1><span class="icon">📦</span>首次启动 · 安装依赖</h1>
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

    def _push(self, pip, ok, msg):
        import html as _h
        w = self._holder.get("win")
        if not w:
            return
        try:
            w.evaluate_js(f"_onProgress({_h.escape(pip) and pip!r}, {str(ok).lower()}, {msg!r})")
        except Exception:
            pass

    def install_all(self):
        """逐库 pip install（线程里跑）。必须先装必需库；失败继续装后面的（用户能看到全部结果）。"""
        import threading
        import html as _h
        def worker():
            for pip_name, _desc in self._missing:
                self._push(pip_name, True, "")   # 占位先清空
                try:
                    # --no-input：绝不交互挂起；pip 自带超时与重试
                    r = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--no-input", pip_name],
                        capture_output=True, text=True, timeout=600,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    ok = r.returncode == 0
                    tail = (r.stderr or r.stdout or "").strip().splitlines()
                    msg = tail[-1][:200] if tail else ""
                    self._push(pip_name, ok, msg)
                except Exception as e:
                    self._push(pip_name, False, f"pip 异常: {e}")
            if self.done_evt:
                self.done_evt.set()
        threading.Thread(target=worker, daemon=True).start()

    def finish(self):
        """用户点「继续启动」：置完成事件（无论装没装成功——让主流程自己再探测）。"""
        if self.done_evt:
            self.done_evt.set()
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
        win.show()
        win.focus()
        api.install_all()

    win.events.loaded += on_loaded
    # 引导窗不写 private_mode（一次性窗口，无需持久化）
    webview.start()
    # 窗口关闭（用户点继续或直接关窗）→ 主流程继续
    return True


def bootstrap_if_needed():
    """main.py 启动早期调用。缺库时引导安装并重启进程；不缺直接返回继续启动。
    返回 True = 应继续启动；False = 已重启/应退出（调用方 return）。"""
    miss_req, miss_opt = check_deps()
    missing = miss_req + miss_opt
    if not missing:
        return True

    # pywebview 自身缺失时无法弹窗——退化为控制台提示（源码分发者至少有终端）
    try:
        importlib.import_module("webview")
    except ImportError:
        pip_cmd = "pip install " + " ".join(p for p, _ in missing)
        print("=" * 56)
        print("检测到缺少运行库，请在当前 Python 环境执行：")
        print("  " + pip_cmd)
        print("装完后重新启动本工具。")
        print("=" * 56)
        try:
            input("按回车退出…")
        except Exception:
            pass
        return False

    run_bootstrap(missing)
    # 窗口关闭后重启进程：新装的库必须重新 import（已加载的模块表里没有它们）。
    # os.execv 原位重启，不额外产生父子进程层级。
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
        return False
    except Exception:
        # execv 失败（极少见）——退化为提示重启
        print("依赖安装流程结束，请重新启动本工具。")
        try:
            input("按回车退出…")
        except Exception:
            pass
        return False
