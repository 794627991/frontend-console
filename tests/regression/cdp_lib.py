# -*- coding: utf-8 -*-
"""模块化回归测试公共库：CDP 连接、求值、错误收集、等待、截图。

依赖项目自带 src/devtools_cdp.py（无第三方向依赖）。
前置：前端控制台应用运行中，主 UI CDP 端口 9222。
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import shutil
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import devtools_cdp as dc          # noqa: E402

PORT = int(os.environ.get("REGRESSION_CDP_PORT", "9222"))
MODE = os.environ.get("REGRESSION_CDP_MODE", "headless")   # headless|real
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def _find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _app_url():
    """用户窗口的地址（headless 用同一后端）。

    顺序：9222 页面 target → ~/.serialconsole_pro/endpoint.json → 环境变量。
    绝不硬编码端口（应用每次启动随机端口）。
    """
    try:
        for t in dc.list_targets(PORT):
            if t.get("type") == "page" and t.get("url", "").startswith("http"):
                return t["url"]
    except Exception:
        pass
    try:
        ep = os.path.join(os.path.expanduser("~"), ".serialconsole_pro",
                          "endpoint.json")
        with open(ep, encoding="utf-8") as f:
            u = (json.load(f) or {}).get("url") or ""
        if u.startswith("http"):
            return u
    except Exception:
        pass
    return os.environ.get("REGRESSION_APP_URL", "")
ARTIFACTS = os.path.join(_HERE, "artifacts")


def artifact_dir():
    """本次运行的产物目录（tests/regression/artifacts/<ts>）。"""
    import datetime
    d = os.path.join(ARTIFACTS, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d


class Page(object):
    """一个常驻 CDP 页会话（测试期间复用，减少建连抖动）。"""

    def __init__(self, port=None, mode=None):
        """mode: headless（默认，独立 Chrome，不碰用户窗口）| real（9222）。"""
        self._proc = None
        self._profile = None
        m = mode or MODE
        if m == "real":
            self.port = port or PORT
            targets = dc.list_targets(self.port)
            pages = [t for t in targets if t.get("type") == "page"]
            if not pages:
                raise RuntimeError("CDP 端口 %d 无 page target（应用未运行？）" % self.port)
            self.target = pages[0]
        else:
            self._start_headless()
        self.cs = dc.CdpSession(self.port, self.target["id"], timeout=10)
        self.cs.__enter__()
        self._hook_errors()

    def _start_headless(self):
        chrome = _find_chrome()
        if not chrome:
            raise RuntimeError("未找到 Chrome/Edge，无法 headless")
        url = _app_url()
        if not url:
            raise RuntimeError("无法解析应用地址（9222/endpoint.json/REGRESSION_APP_URL 均不可用）")
        # 测试模式标记：页面据此禁用 pagehide 断开真实连接、禁用 recent 落盘
        url += ("&" if "?" in url else "?") + "regression=1"
        self.port = _free_port()
        self._profile = tempfile.mkdtemp(prefix="reg-hl-")
        try:
            self._proc = subprocess.Popen(
                [chrome, "--headless=new", "--remote-debugging-port=%d" % self.port,
                 "--user-data-dir=%s" % self._profile, "--disable-gpu",
                 "--no-first-run", "--no-default-browser-check", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            end = time.time() + 30
            while time.time() < end:
                try:
                    pages = [t for t in dc.list_targets(self.port)
                             if t.get("type") == "page"]
                    if pages:
                        self.target = pages[0]
                        break
                except Exception:
                    pass
                time.sleep(0.3)
            else:
                raise RuntimeError("headless CDP 连接失败")
        except Exception:
            self._cleanup_proc()
            raise
        # 等待页面就绪（后端页面有 _HG_VER）
        end = time.time() + 25
        while time.time() < end:
            try:
                cs = dc.CdpSession(self.port, self.target["id"], timeout=5)
                cs.__enter__()
                try:
                    r = cs.send("Runtime.evaluate", {
                        "expression": "document.readyState==='complete' && !!window._HG_VER",
                        "returnByValue": True}, timeout=5)
                    if (r.get("result") or {}).get("value"):
                        cs.__exit__(None, None, None)
                        return
                finally:
                    try:
                        cs.__exit__(None, None, None)
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("headless 页面未就绪（%s）" % url)

    # ---- 求值 ----
    def ev(self, expr, timeout=30.0, await_promise=False):
        r = self.cs.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": await_promise}, timeout=timeout)
        res = r.get("result") or {}
        if res.get("subtype") == "error":
            raise RuntimeError("页面求值异常: %s" % (res.get("description") or res))
        return res.get("value")

    def ev_obj(self, expr, timeout=30.0, await_promise=False):
        v = self.ev(expr, timeout, await_promise)
        return json.loads(v) if isinstance(v, str) else v

    def wait_until(self, expr, timeout=15.0, interval=0.3, timeout_msg=None):
        """轮询布尔 JS 表达式直至为 true；超时返回 False。"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.ev(expr, timeout=10):
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    # ---- 错误收集 ----
    def _hook_errors(self):
        self.ev(r"""(function(){
          if (window.__regHooked) return 'already';
          window.__regHooked = 1; window.__regErrs = [];
          window.addEventListener('error', function(e){
            window.__regErrs.push({t:'error', m:String(e.message||''),
              f:String(e.filename||''), l:e.lineno||0,
              stack:String((e.error&&e.error.stack)||'').slice(0,1200), ts:Date.now()});
          });
          window.addEventListener('unhandledrejection', function(e){
            window.__regErrs.push({t:'rejection',
              m:String((e.reason && e.reason.message) || e.reason || ''),
              stack:String((e.reason&&e.reason.stack)||'').slice(0,1200), ts:Date.now()});
          });
          return 'hooked';
        })()""")

    def drain_errs(self):
        try:
            errs = self.ev_obj("JSON.stringify(window.__regErrs || [])")
            self.ev("window.__regErrs = []")
            return errs
        except Exception:
            return []

    def clear_errs(self):
        try:
            self.ev("window.__regErrs = []")
        except Exception:
            pass

    # ---- 截图 ----
    def shot(self, out_dir, name):
        try:
            os.makedirs(out_dir, exist_ok=True)
            r = self.cs.send("Page.captureScreenshot", {"format": "png"}, timeout=20)
            p = os.path.join(out_dir, name + ".png")
            with open(p, "wb") as f:
                f.write(base64.b64decode(r["data"]))
            return p
        except Exception as e:
            return "截图失败: %r" % (e,)

    def _cleanup_proc(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._profile:
            try:
                shutil.rmtree(self._profile, ignore_errors=True)
            except Exception:
                pass
            self._profile = None

    def close(self):
        try:
            self.cs.__exit__(None, None, None)
        except Exception:
            pass
        self._cleanup_proc()


# ---- 已知噪声过滤（第三方库/测试自身快速操作的固有报错）----
NOISE_PATTERNS = (
    "AbstractContextKeyService has been disposed",   # Monaco dispose 竞态（D3）
)


def filter_known_noise(errs):
    """返回 (真实异常, 已知噪声)。

    噪声白名单必须精确：导入脚本中止仅在「monaco worker + failed to load」
    组合下放行（R2 快速开关 test 场景）；其余 worker 错误（含 D4 回归）
    必须 FAIL。
    """
    kept, noise = [], []
    for e in errs or []:
        sig = str(e.get("m") or "") + str(e.get("stack") or "")
        known = any(p in sig for p in NOISE_PATTERNS) or (
            "importScripts" in sig and "vendor/monaco" in sig
            and "failed to load" in sig)
        (noise if known else kept).append(e)
    return kept, noise


# ---- 结果容器 ----
def result(cid, name, layer, priority, status, detail=""):
    """status: PASS / FAIL / SKIP / CHECK"""
    return {"id": cid, "name": name, "layer": layer,
            "priority": priority, "status": status, "detail": detail}


def summarize(results):
    from collections import Counter
    c = Counter(r["status"] for r in results)
    return dict(c)
