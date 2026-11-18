# -*- coding: utf-8 -*-
"""模块化回归测试公共库：CDP 连接、求值、错误收集、等待、截图。

依赖项目自带 src/devtools_cdp.py（无第三方向依赖）。
前置：前端控制台应用运行中，主 UI CDP 端口 9222。
"""
import base64
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import devtools_cdp as dc          # noqa: E402

PORT = int(os.environ.get("REGRESSION_CDP_PORT", "9222"))
ARTIFACTS = os.path.join(_HERE, "artifacts")


def artifact_dir():
    """本次运行的产物目录（tests/regression/artifacts/<ts>）。"""
    import datetime
    d = os.path.join(ARTIFACTS, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d


class Page(object):
    """一个常驻 CDP 页会话（测试期间复用，减少建连抖动）。"""

    def __init__(self, port=None):
        self.port = port or PORT
        targets = dc.list_targets(self.port)
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            raise RuntimeError("CDP 端口 %d 无 page target（应用未运行？）" % self.port)
        self.target = pages[0]
        self.cs = dc.CdpSession(self.port, self.target["id"], timeout=10)
        self.cs.__enter__()
        self._hook_errors()

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
              f:String(e.filename||''), l:e.lineno||0, ts:Date.now()});
          });
          window.addEventListener('unhandledrejection', function(e){
            window.__regErrs.push({t:'rejection',
              m:String((e.reason && e.reason.message) || e.reason || ''),
              ts:Date.now()});
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

    def close(self):
        try:
            self.cs.__exit__(None, None, None)
        except Exception:
            pass


# ---- 结果容器 ----
def result(cid, name, layer, priority, status, detail=""):
    """status: PASS / FAIL / SKIP / CHECK"""
    return {"id": cid, "name": name, "layer": layer,
            "priority": priority, "status": status, "detail": detail}


def summarize(results):
    from collections import Counter
    c = Counter(r["status"] for r in results)
    return dict(c)
