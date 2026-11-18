# -*- coding: utf-8 -*-
"""冷启动探针：静态服务 repo 根 + headless Chrome CDP，验证 module 加载/顶层执行。

不依赖运行中的应用、不耗 CLI 额度。模板占位符在内存中替换（不改仓库文件）。
"""
import http.server
import json
import os
import socket
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
REPL = [("__HG_VER__", "reg"), ("__HG_WBASE__", ""),
        ("__HG_WFAMFLAG__", ""), ("__HG_DBGF__", "0")]


def _free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _make_handler(port):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=ROOT, **kw)

        def log_message(self, *a):
            pass

        def _json(self, body=b'{"ok": false}'):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/"):
                return self._json()
            if self.path.split("?")[0] in ("/", ""):
                with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
                    data = f.read()
                for k, v in REPL:
                    data = data.replace(k, v)
                b = data.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            return super().do_GET()

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
            except Exception:
                pass
            return self._json()

    return H


def probe(timeout_s=10.0):
    """返回 {ok, exceptions, module_errors, mounts, chrome}。"""
    chrome = _find_chrome()
    if not chrome:
        return {"ok": False, "skip": "未找到 Chrome/Edge", "exceptions": [], "module_errors": []}
    port = _free_port()
    cdp_port = _free_port()
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), _make_handler(port))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="reg-profile-")
    proc = None
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--remote-debugging-port=%d" % cdp_port,
         "--user-data-dir=%s" % profile, "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        import websocket
        ws_url = None
        for _ in range(80):
            try:
                lst = json.load(urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/list" % cdp_port, timeout=1))
                pages = [t for t in lst if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not ws_url:
            return {"ok": False, "skip": "CDP 连接失败", "exceptions": [], "module_errors": []}
        ws = websocket.create_connection(ws_url, timeout=5)
        mid = [0]

        def send(method, params=None, timeout=30):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
            end = time.time() + timeout
            ws.settimeout(0.4)
            while time.time() < end:
                try:
                    msg = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    raise
                if msg.get("id") == mid[0]:
                    return msg.get("result", {})
            raise TimeoutError(method)

        events = []
        send("Runtime.enable")
        send("Log.enable")
        send("Page.enable")
        send("Page.navigate", {"url": "http://127.0.0.1:%d/" % port})
        end = time.time() + timeout_s
        ws.settimeout(0.4)
        while time.time() < end:
            try:
                msg = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
            if "method" in msg:
                events.append(msg)
        exceptions, module_errors = [], []
        for ev in events:
            m = ev["method"]; p = ev.get("params", {})
            if m == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                exceptions.append({
                    "text": d.get("text", ""),
                    "desc": ((d.get("exception") or {}).get("description") or "")[:300],
                    "url": d.get("url", "")})
            elif m == "Log.entryAdded":
                e = p.get("entry", {})
                txt = e.get("text", "") or ""
                if "module" in txt.lower() and ("fail" in txt.lower() or "error" in txt.lower()):
                    module_errors.append(txt[:200])
        ev = send("Runtime.evaluate", {
            "expression": "JSON.stringify({ver:window._HG_VER||'',"
                          "v4b:typeof window.V4Bridge,rowAdd:typeof window._hgRowAdd,"
                          "dispatch:typeof window._hgDispatch,grpFinalize:typeof window.grpFinalize,swHead:String(window.switchTab).slice(0,120)})",
            "returnByValue": True})
        mounts = json.loads((ev.get("result") or {}).get("value") or "{}")
        return {"ok": not exceptions and not module_errors,
                "exceptions": exceptions, "module_errors": module_errors,
                "mounts": mounts, "chrome": chrome}
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            srv.shutdown()
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
