# -*- coding: utf-8 -*-
"""a543 PoC v2：CDP Fetch 删 Referer + Log.entryAdded 检测 XFO 拒绝。

判定：25s 内 Log 流出现 "Refused to display ... X-Frame-Options" = 剥失败；
不出现（且 iframe 导航发生）= 内网代理未注入 XFO = 成功。
"""
import json
import sys
import threading
import time

sys.path.insert(0, ".")

import webview

_cvw_holder = {}
_LOG = []
_CONTINUED = [0]
_FRAMES = [0]


def _patch():
    from webview.platforms.edgechromium import EdgeChrome as _EC
    _orig_ready = _EC.on_webview_ready

    def _patched_ready(self, sender, args):
        _orig_ready(self, sender, args)
        try:
            cvw = sender.CoreWebView2
            _cvw_holder["cvw"] = cvw
            # ① Fetch：Request 阶段删 Referer
            import os as _os
            if not _os.environ.get("POC_NO_FETCH"):
                # Response 阶段拦截：拿到响应后剥 XFO/CSP frame 头再放行
                cvw.CallDevToolsProtocolMethodAsync(
                    "Fetch.enable",
                    json.dumps({"patterns": [{"urlPattern": "*",
                                              "requestStage": "Response"}]}))
                print("[poc] RESPONSE 模式：剥 XFO 响应头")
            else:
                print("[poc] BASELINE 模式：只监听不拦截")
            recv = cvw.GetDevToolsProtocolEventReceiver("Fetch.requestPaused")

            def _on_paused(_s, a):
                _LOG.append("[paused-event] fired")
                try:
                    ev = json.loads(a.ParameterObjectAsJson)
                    _LOG.append("[paused-keys] %s" % sorted(ev.keys())[:8])
                    rid = ev.get("requestId")
                    rhdrs = ev.get("responseHeaders", []) or []
                    has_xfo = any(
                        h.get("name", "").lower() in
                        ("x-frame-options", "content-security-policy")
                        for h in rhdrs)
                    if not has_xfo:
                        _CONTINUED[0] += 1
                        cvw.CallDevToolsProtocolMethodAsync(
                            "Fetch.continueRequest",
                            json.dumps({"requestId": rid}))
                        return
                    # 剥 XFO / 含 frame-ancestors 的 CSP → 需要响应体 fulfill
                    _LOG.append("[poc-strip] %s" % ev.get("response", {})
                                .get("url", "")[:80])
                    t1 = cvw.CallDevToolsProtocolMethodAsync(
                        "Fetch.getResponseBody",
                        json.dumps({"requestId": rid}))
                    def _fulfill(tt):
                        try:
                            body = json.loads(tt.Result)
                            nh = [h for h in rhdrs
                                  if h.get("name", "").lower()
                                  not in ("x-frame-options",
                                          "content-security-policy")]
                            cvw.CallDevToolsProtocolMethodAsync(
                                "Fetch.fulfillRequest", json.dumps({
                                    "requestId": rid,
                                    "responseCode": ev.get("responseCode", 200),
                                    "responseHeaders": nh,
                                    "body": body.get("body", ""),
                                    "base64": body.get("base64", False)}))
                        except Exception as e:
                            _LOG.append("[poc-fulfill-err] %r" % e)
                            try:
                                cvw.CallDevToolsProtocolMethodAsync(
                                    "Fetch.continueRequest",
                                    json.dumps({"requestId": rid}))
                            except Exception:
                                pass
                    import System
                    tt = t1.ContinueWith(System.Action[System.Threading.Tasks.Task](_fulfill))
                except Exception as e:
                    _LOG.append("[poc-paused-err] %r" % e)

            recv.DevToolsProtocolEventReceived += _on_paused
            # ② Log：浏览器内部错误（XFO 拒绝走这里）
            cvw.CallDevToolsProtocolMethodAsync("Log.enable", "{}")
            cvw.CallDevToolsProtocolMethodAsync("Page.enable", "{}")
            cvw.CallDevToolsProtocolMethodAsync("Network.enable", "{}")
            nr = cvw.GetDevToolsProtocolEventReceiver("Network.requestWillBeSent")
            def _on_net(_s, a):
                try:
                    ev = json.loads(a.ParameterObjectAsJson)
                    _LOG.append("[net] %s %s" % (
                        ev.get("request", {}).get("method"),
                        ev.get("request", {}).get("url", "")[:100]))
                except Exception:
                    pass
            nr.DevToolsProtocolEventReceived += _on_net
            logr = cvw.GetDevToolsProtocolEventReceiver("Log.entryAdded")

            def _on_log(_s, a):
                try:
                    ev = json.loads(a.ParameterObjectAsJson)
                    ent = ev.get("entry", {})
                    _LOG.append("[%s] %s" % (ent.get("level"),
                                             ent.get("text", "")[:160]))
                except Exception:
                    pass

            logr.DevToolsProtocolEventReceived += _on_log
            # ③ frame 导航计数（证明 iframe 真的在加载）
            fr = cvw.GetDevToolsProtocolEventReceiver("Page.frameNavigated")

            def _on_frame(_s, a):
                _FRAMES[0] += 1

            fr.DevToolsProtocolEventReceived += _on_frame
            print("[poc] armed: Fetch + Log + Page")
        except Exception as e:
            print("[poc] ready err: %r" % e)

    _EC.on_webview_ready = _patched_ready


_html = """<!doctype html><meta charset='utf-8'>
<body style="margin:0">
<div id="st">loading...</div>
<iframe id="f" style="width:100vw;height:95vh;border:0"
  src="https://github.com/zai-org/ZCode"
  onload="document.getElementById('st').textContent='IFRAME_ONLOAD'"
  onerror="document.getElementById('st').textContent='IFRAME_ONERROR'"></iframe>
</body>"""


def main():
    _patch()
    w = webview.create_window("POC",
                              "http://127.0.0.1:18888/poc.html",
                              width=1200, height=800)

    def _report():
        time.sleep(25)
        xfo = [l for l in _LOG if "X-Frame" in l or "Refused to display" in l]
        print("[poc] continueRequest 次数: %d" % _CONTINUED[0])
        print("[poc] frameNavigated 次数: %d" % _FRAMES[0])
        print("[poc] XFO 拒绝条数: %d" % len(xfo))
        for l in xfo[:5]:
            print("  XFO>", l)
        errs = [l for l in _LOG if "err" in l.lower()][:5]
        for l in errs:
            print("  ERR>", l)
        nets = [l for l in _LOG if l.startswith("[net]")]
        print("[poc] 网络请求数: %d" % len(nets))
        for l in nets[:8]:
            print("  ", l)
        # onload 状态经 pywebview evaluate_js 读（UI 线程）
        try:
            st = w.evaluate_js("document.getElementById('st') && document.getElementById('st').textContent")
            print("[poc] iframe 状态:", st)
        except Exception as e:
            print("[poc] js read err:", e)
        print("[poc] 判定:", "失败（仍被拒）" if xfo else
              ("成功（无 XFO 拒绝）" if len(nets) > 1 else "无导航发生"))
        try:
            w.destroy()
        except Exception:
            pass

    threading.Thread(target=_report, daemon=True).start()
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
