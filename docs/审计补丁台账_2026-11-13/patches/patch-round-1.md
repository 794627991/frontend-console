# 补丁 · 第 1 轮（提案，未应用）

> ⚠ **R2 白盒对抗评审结论（2026-11-13，见 `rounds/round-2-whitebox.md`）**：A1/A2/A3/A5/A6/A7/A9/A12 核验干净；**A4、A8、A10、A11、D1 五处需修订**（W14–W17、W20），修订 diff 在 `patches/patch-round-2.md`：
> - **A4（W14/P2）**：失败推送在 ContinueWith 池线程直调 `ExecuteScriptAsync`，违反 a549 线程亲和铁律且异常被吞 → `__webTabDead` 永不送达，W13 修复在最需要它的路径上自失效
> - **A8（W15/P3）**：只覆盖 3/6 个 `_webNavigate` 调用点，`:495` 的 1s 唤醒巡检仍走 `_webCur()` 回落 → 跨 tab 恢复 URL（B1 同型残留）
> - **A10（W16/P3）**：scheme 白名单放行了 `file:`（未拍板的行为变更）→ 修订版收窄为 `https?|about` 并显式拦截提示
> - **A11（W17/P3）**：删 `_lock` 后 `import threading` 成孤儿导入（本文件原注「仍被其他处使用」有误，grep 证实唯一使用点就是 `_lock`）
> - **D1（W20/P3）**：pagehide beacon 迟到会 dispose_all 杀掉刷新后重建的 tab 并归零 `_want_seq` → dispose_all 需带页面纪元令牌
>
> **应用 R1 补丁前必须先读 patch-round-2.md 的对应修订**。

> 生成：2026-11-13（R1 收尾）。依据：`rounds/round-1-whitebox.md`（W1–W13）+ `rounds/round-1-blackbox.md`（B1–B6）。
> 性质：**纯提案 md，未修改任何代码文件**。所有行号以基线 d9c8886 为准，应用时以内容锚点定位。
> 分组：**A** = 确定性补丁（可直接评审应用）；**D** = 设计级补丁（方案+骨架，需拍板后出正式 diff）；**C** = 核伪/环境项（不打补丁）。
> 应用顺序建议：A1 → A2 → A3/A4/A5 → 其余 A → 评审 D。

---

## A. 确定性补丁

### A1【P0 / W1】移除 `--disable-web-security`（iframe 时代残留，跨源暴露本机 API）

`src/main.py:1563-1569`。a501 加此开关的唯一理由（内网代理 XFO 挡 iframe 子页）已被 a544 结构性终结：网页 tab 不再是 iframe。该开关经 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 环境变量**同样注入网页 tab 的独立浏览器进程**（`CoreWebView2Environment.CreateAsync` 的 options 为 None 时读该环境变量）→ 任意外站页面可跨源 fetch 本机 `http://127.0.0.1:<port>/api/read_text`（任意文件读）、`/api/history`（终端历史）等 GET API，端口可被扫描发现。主 UI 与网页 tab 均无跨源需求，删除无损。

```diff
--- a/src/main.py
+++ b/src/main.py
@@ -1563,15 +1563,10 @@
     _wv_args = ["--disable-backgrounding-occluded-windows",
                 "--disable-renderer-backgrounding",
                 "--disable-background-timer-throttling",
-                "--disable-features=CalculateNativeWinOcclusion",
-                # a501（用户需求「网页里的链接能在工具内点开并显示」）：
-                # 内网代理注入 X-Frame-Options 导致 iframe 子页导航被拒。
-                # a495–a500 五版请求/响应层方案全部无效（pythonnet COM
-                # 对外部 HTTPS 的 Headers 不可访问）——唯一可靠路径是
-                # 渲染引擎层禁用同源检查。桌面工具 WebView2 沙箱内可控。
-                "--disable-web-security"]
+                "--disable-features=CalculateNativeWinOcclusion"]
+    # R1 审计 W1（P0）：a501 的 --disable-web-security 已随 a544 iframe
+    # 时代退役。该开关经 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 同样注入
+    # 网页 tab 独立浏览器进程 → 任意外站可跨源调用本机 GET API
+    # （/api/read_text 任意文件读、/api/history 终端历史）。主 UI 与
+    # 网页 tab 均无跨源需求，移除。
```

**回归验证点（R2）**：主 UI 外链点击（`__newWindow` 路由 `main.py:806`）、网页 tab 内 target=_blank、Claude 回复链接打开——这三条链路都不依赖该开关（`ExecuteScriptAsync` 不受同源策略约束），但需实测确认。

### A2【P1 / W2】`_safe_load` 回环判定改按 hostname 精确解析

`src/main.py:806-817`。原 `"127.0.0.1" not in _u` 子串判定：`http://127.0.0.1.evil.com` 因子串命中被当作本机 URL 放行 → 主 UI 窗口直接导航到外部页（叠加 A1 修复前的同源禁用，可跨源读本机 API）。

```diff
--- a/src/main.py
+++ b/src/main.py
@@ -803,6 +803,17 @@
             _orig_load = self.load_url
+
+            def _is_loopback(u):
+                # R1 审计 W2：原「"127.0.0.1" not in _u」子串判定可被
+                # http://127.0.0.1.evil.com 绕过（子串命中→误判本机→主 UI
+                # 导航到外部页）。改按 urlsplit().hostname 精确判定。
+                try:
+                    from urllib.parse import urlsplit
+                    return (urlsplit(u).hostname or "").lower() in (
+                        "127.0.0.1", "localhost", "::1")
+                except Exception:
+                    return False
+
             def _safe_load(url, *la, **kw):
                 try:
                     _u = str(url or "")
-                    if _u.startswith(("http://", "https://"))                             and "127.0.0.1" not in _u:
+                    if _u.startswith(("http://", "https://")) and not _is_loopback(_u):
                         sender.CoreWebView2.ExecuteScriptAsync(
```

### A3【P1 / W5】dispose 与 create 在途竞态：登记取消，`_build` 弃建

`src/web_tabs.py`。create 的 REST 响应先于 `_build` 执行（BeginInvoke 异步）；「开→立刻关」时 dispose 查无 ctl 返回 ok，随后 `_build` 照常建出控件 → 无人引用的隐形孤儿（加载完整网页、持会话直到进程退出）。

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ -49,6 +49,7 @@
         self._pending = set()                # a555：create 在途的 tab（双发去重）
         self._pend_nav = {}                  # a555：在途 tab 的后发导航（末次胜）
+        self._cancel = set()                 # R1 审计 W5：create 在途中被 dispose（弃建标记）
         self._env_failed = False             # a555：env 永久失败 → 快速失败
         self._ensure_env()
@@ -136,6 +137,12 @@
 
         def _build():
             try:
+                if tab_id in self._cancel:
+                    # R1 审计 W5：create 在途期间 tab 已被关闭——不建控件、
+                    # 不接线、不导航（原先照建 → 永不 Dispose 的隐形孤儿）
+                    self._cancel.discard(tab_id)
+                    return
                 import Microsoft.Web.WebView2.WinForms as WF
                 import System
                 import System.Drawing
@@ -385,12 +392,21 @@
     def dispose(self, tab_id):
         """关 tab：控件从 Form 移除并 Dispose（渲染进程回收）。"""
         ctl = self._ctl.pop(tab_id, None)
-        if not ctl:
-            return {"ok": True}
-
-        def _rm():
-            try:
-                self._form.Controls.Remove(ctl)
-                ctl.Dispose()
-            except Exception as e:
-                _log("WARN", "dispose: %r" % e)
-        self._ui(_rm)
-        return {"ok": True}
+        if ctl:
+            def _rm():
+                try:
+                    self._form.Controls.Remove(ctl)
+                    ctl.Dispose()
+                except Exception as e:
+                    _log("WARN", "dispose: %r" % e)
+            self._ui(_rm)
+        elif tab_id in self._pending:
+            # R1 审计 W5：create 在途中被关——原路径查无 ctl 直接 ok，
+            # 随后 _build 照常建出控件。登记取消标记 + 清理在途导航。
+            self._cancel.add(tab_id)
+            self._pending.discard(tab_id)
+            self._pend_nav.pop(tab_id, None)
+        return {"ok": True}
```

### A4【P1 / W13】`EnsureCoreWebView2Async` 失败回收死控件 + 前端 `__webTabDead` 提示

`src/web_tabs.py:163-168`：初始化失败原先只记日志——死控件永留 `_ctl`，tab 假活（无重试/无回收/无提示）。后端回收 + 通知前端关 tab。

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ -163,8 +163,31 @@
         def _init_done(t):
             try:
                 t.Result    # 确保异常在此可见
             except Exception as e:
                 _log("ERROR", "EnsureCoreWebView2Async: %r" % e)
-                return
+                # R1 审计 W13：初始化失败原先只记日志——死控件永留 _ctl，
+                # tab 假活（用户看到的是永远加载不出来的空 tab，且无法
+                # 自愈）。回收控件 + 通知前端关 tab。
+                self._ctl.pop(tab_id, None)
+                self._pend_nav.pop(tab_id, None)
+
+                def _rm():
+                    try:
+                        self._form.Controls.Remove(ctl)
+                        ctl.Dispose()
+                    except Exception:
+                        pass
+                self._ui(_rm)
+                m = self._main_cvw
+                if m:
+                    try:
+                        m.ExecuteScriptAsync(
+                            "window.__webTabDead && window.__webTabDead(%s, %s)"
+                            % (json.dumps(tab_id), json.dumps(str(e))))
+                    except Exception:
+                        pass
+                return
 
             def _on_ui():
```

前端（`web/js/web-panel.js`，放在 `window.__newWindow` 定义附近，约 :651）：

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -655,6 +655,17 @@
 window.__newWindow = function (url) {
   try {
     buildWebPanelTab(url, { newTab: true });   // a554：外链开新 tab
   } catch (_) {}
 };
+
+// R1 审计 W13：控件初始化失败（EnsureCoreWebView2Async 异常）——后端
+// 已回收控件，前端关掉假活 tab 并提示（原先 tab 永远空白假活）
+window.__webTabDead = function (tabId, err) {
+  try {
+    const c = Object.values(connections).find(
+      x => x && x.meta && x.meta.kind === 'web' && x._tabId === tabId);
+    if (c) {
+      showBanner('网页 tab 初始化失败：' + (err || '未知'), 4000, true);
+      closeEditorTab(c.portId);
+    }
+  } catch (_) {}
+};
```

### A5【P2 / W6】CoreWebView2 就绪前的 navigate 转 `_pend_nav`（末次胜出）

`src/web_tabs.py:283-294`。控件已入 `_ctl` 但 `EnsureCoreWebView2Async` 未完成的窗口期内，navigate 的 `ctl.CoreWebView2` 为 None → AttributeError 被 `_go` 吞掉 → URL 静默丢失（返回 ok=True，地址栏与实际页面脱节）。

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ -283,13 +283,21 @@
     def navigate(self, tab_id, url):
         ctl = self._ctl.get(tab_id)
         if not ctl:
             return {"ok": False, "err": "no tab"}
 
         def _go():
             try:
-                ctl.CoreWebView2.Navigate(url)
+                if ctl.CoreWebView2 is None:
+                    # R1 审计 W6：EnsureCoreWebView2Async 未完成窗口期，
+                    # 原路径 AttributeError 被吞 → URL 静默丢失（ok=True
+                    # 但页面不动，地址栏与页面脱节）。转入 _pend_nav，
+                    # 就绪后按「末次胜出」导航（与 create 双发同一机制）。
+                    self._pend_nav[tab_id] = url
+                    return
+                ctl.CoreWebView2.Navigate(url)
             except Exception as e:
                 _log("WARN", "navigate: %r" % e)
         self._ui(_go)
         return {"ok": True}
```

> 注：`ctl.CoreWebView2` 属性访问仅在 UI 线程合法（a549 铁律），`_go` 经 `_ui` 已在 UI 线程执行，此处判断安全。A3 若使 `_build` 弃建，本补丁的 `_pend_nav` 残项由 A4/W3 的清理路径兜底。

### A6【P2 / W7】`/api/web/tabs` 入参收口（NaN/字符串/布尔穿透 → 裸 500）

`src/web_tabs.py:442-470`。`int(d.get("sq") or 0)` 对 `"NaN"`/`"abc"` 抛 ValueError → Flask 裸 500 HTML；`layout` 的 x/y/w/h 同理；`bool(d.get("on", True))` 对 `"false"` 判 True（布尔穿透）。

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ -442,31 +442,49 @@
     @bp.route("/api/web/tabs", methods=["POST"])
     def api_web_tabs():
         d = request.get_json(force=True, silent=True) or {}
         act = str(d.get("act") or "")
         tid = str(d.get("tab") or "")
         url = str(d.get("url") or "")
         t = get_tabs()
         if not t:
             return jsonify({"ok": False, "err": "控件管理器未装配"})
+
+        def _num(k, dft=0):
+            # R1 审计 W7：x/y/w/h/sq 原样透传，"abc"/"NaN" → int() 抛
+            # ValueError → 裸 500。收口：非有限数值一律回落默认。
+            try:
+                v = float(d.get(k, dft))
+                if v != v or v in (float("inf"), float("-inf")):
+                    return dft
+                return int(v)
+            except (TypeError, ValueError, OverflowError):
+                return dft
+
         if act == "create":
             return jsonify(t.create(tid, url))
         if act == "nav":
             return jsonify(t.navigate(tid, url))
         if act == "back":
             return jsonify(t.go_back(tid))
         if act == "fwd":
             return jsonify(t.go_forward(tid))
         if act == "reload":
             return jsonify(t.reload(tid))
         if act == "show":
-            # a556：sq 序号透传（前端乱序保护）
-            return jsonify(t.show(tid, bool(d.get("on", True)),
-                                  int(d.get("sq") or 0)))
+            # a556：sq 序号透传（前端乱序保护）。R1 审计 W7：on="false"
+            # 原为真值字符串 → bool("false")=True，布尔穿透修正。
+            _on = d.get("on", True)
+            return jsonify(t.show(
+                tid,
+                _on if isinstance(_on, bool)
+                else str(_on).strip().lower() in ("true", "1", "yes", "on"),
+                _num("sq")))
         if act == "dispose":
             return jsonify(t.dispose(tid))
         if act == "layout":
-            return jsonify(t.layout(d.get("x", 0), d.get("y", 0),
-                                    d.get("w", 0), d.get("h", 0)))
+            return jsonify(t.layout(_num("x"), _num("y"),
+                                    _num("w"), _num("h")))
         return jsonify({"ok": False, "err": "bad act"})
```

### A7【P2 / W9】`_SINGLE_KINDS` 移除 `'web'`（a473 残留 → 多开永不进抽屉）

`web/js/util.js:62`。a554 起网页 tab 支持多开，`'web'` 留在单例兜底集使 `_isFlat('web')` 恒真 → 多开的网页 tab 永不收进抽屉（a452 记录过的 claude 同款事故）。

```diff
--- a/web/js/util.js
+++ b/web/js/util.js
@@ -59,7 +59,10 @@
   // _SINGLE_KINDS = 设计上不会多开的类型（兜底：即便数量判定放宽也不收）
   // a452（审计 P1）：claude **不在**此列——后端 server.py 允许 `claude:{n}`
   // 自增多开（连开多个会话是常态）。把它当单例兜底会让 _isFlat 短路，
   // 多个 claude tab 永不进抽屉，tab 栏被平铺占满压成图标态。
-  const _SINGLE_KINDS = new Set(['harness', 'bitcalc', 'proxy', 'vcs', 'web']);
+  // R1 审计 W9：a554 起网页 tab 支持多开（buildWebPanelTab newTab），
+  // 'web' 留在此集合会让多开的网页 tab 永不进抽屉（claude 同款事故）。
+  const _SINGLE_KINDS = new Set(['harness', 'bitcalc', 'proxy', 'vcs']);
```

### A8【P2 / B1】`_webNavigate` 增加显式目标 tab（跨 tab 串导航）

`web/js/web-panel.js`。`_webNavigate` 内部恒取 `_webCur()`：对非激活 tab 的地址栏回车，导航发生在**激活 tab** 上（黑盒行为+代码双证）。

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -394,8 +394,10 @@
 // 导航（终局：控件 Navigate，无代理无软过渡）
-function _webNavigate(url) {
-  const c = _webCur();
+function _webNavigate(url, c) {
+  // R1 审计 B1：c 可指定目标 tab——非激活 tab 的地址栏回车原先会把
+  // URL 导航到「激活 tab」上（_webCur 恒取激活），本 tab 纹丝不动。
+  c = c || _webCur();
   if (!c || !url) return;
```

调用点修正（3 处）：

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -173,7 +173,7 @@
       // a554 多开：回车=当前 tab 导航；Ctrl+回车=开新网页 tab
       if (e.ctrlKey) buildWebPanelTab(u, { newTab: true });
-      else _webNavigate(u);
+      else _webNavigate(u, conn);
@@ -230,7 +230,7 @@
-    _webNavigate(conn._nav.stack[conn._nav.stack.length - 1]);
+    _webNavigate(conn._nav.stack[conn._nav.stack.length - 1], conn);
@@ -433,7 +433,7 @@
         const u = _webNavTop(c);              // a556：跳过脏 about:blank
-        if (u) _webNavigate(u);
+        if (u) _webNavigate(u, c);
```

> 语义保持：`_webActivePid = c.portId`（导航即激活）不变；`buildWebPanelTab` 顶栏入口（:103）在 `switchTab(pid)` 后导航，`_webCur()` 即目标 tab，无需改。

### A9【P3 / W12】NewWindowRequested 空 URI 降级 about:blank

`src/web_tabs.py:255-270`。`a.set_Handled(True)` 无条件执行后，空 URI 走不进推送也走不进降级导航 → `window.open('')` 毫无反应。

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ -255,8 +255,10 @@
         def _on_new_window(s, a):
             try:
-                u = str(a.Uri or "")
+                # R1 审计 W12：空 URI 原样吞（Handled=True 后既不推送也
+                # 不导航）——window.open('') 语义=空白页，降级 about:blank
+                u = str(a.Uri or "") or "about:blank"
                 a.set_Handled(True)
                 if u and not _push(
```

### A10【P3 / B4】`_webNormUrl` scheme 白名单（javascript:/file: 不再被补 http://）

`web/js/web-panel.js:80-85`。

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -80,9 +80,13 @@
 function _webNormUrl(s) {
   s = String(s || '').trim();
   if (!s) return '';
+  // R1 审计 B4：原仅放行 http(s)://，javascript:/file:/mailto: 一律被
+  // 补 http:// 前缀（产生垃圾导航项）。已知 scheme 原样放行；
+  // localhost:8080 这类「形似 scheme」的主机:端口 仍走补全。
+  if (/^(https?|file|ftp|about|mailto|javascript|data|ws|wss):/i.test(s)) return s;
   if (/^https?:\/\//i.test(s)) return s;
   return 'http://' + s;    // 内网多为 http 裸主机名——缺省补 http
 }
```

> 留给 R2 实测的产品决策点：地址栏 `javascript:` 放行后 WebView2 `Navigate()` 是否执行（文档语义偏向静默无效）。若实测会执行且不希望地址栏成为注入面，把 `javascript|data` 从白名单移除并显式拦截提示即可——一行取舍。

### A11【P3 / W11】死代码清理（a544 退役残留）

四处均为「无任何代码路径触达」的残留，删除无损：

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -20,8 +20,7 @@
-// （挂 conn._nav/_ui）。WEB_PORTID 保留作兼容标记；_webCur() 返回当前
+// （挂 conn._nav/_ui）。_webCur() 返回当前
 // 激活的网页 tab（无激活时回落第一个网页 tab）
-const WEB_PORTID = 'web:panel';            // 兼容标记（外部模块引用判断 kind）
```
（全仓 grep 证实 `WEB_PORTID` 仅剩定义与注释引用，无代码引用。）

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -146,4 +146,3 @@
-        <div class="web-blank-hint" data-web-blank-hint style="display:none;">
-          <span>页面可能被拒绝嵌入（内网代理注入 X-Frame-Options）——试试 <b>☰ 阅读模式</b> 或 <b>↗ 浏览器</b></span>
-        </div>
```
（`web-blank-hint` 创建后无任何代码置其可见——a544 后 iframe XFO 场景结构性消失。配套删 style.css 中 `.web-blank-hint` 规则。）

```diff
--- a/web/js/sidebar-resize.js
+++ b/web/js/sidebar-resize.js
@@ -30,11 +30,6 @@
-  // a524：拖动期间禁用 iframe 指针事件——iframe 会捕获 mousemove（父
-  // 文档收不到），鼠标一移进网页区域（web tab 常驻后主区就是 iframe）
-  // 拖动即断（用户实锤「打开网页后左栏拖动有问题」）。拖完恢复。
-  const iframes = () => document.querySelectorAll('iframe');
   bar.addEventListener('mousedown', e => {
     dragging = true; startX = e.clientX; startW = sb.offsetWidth;
     bar.classList.add('dragging');
     document.body.style.userSelect = 'none';
-    iframes().forEach(f => f.style.pointerEvents = 'none');
     e.preventDefault();
@@ -49,7 +44,6 @@
     dragging = false;
     bar.classList.remove('dragging');
     document.body.style.userSelect = '';
-    iframes().forEach(f => f.style.pointerEvents = '');
```
（a544 后页面无 iframe，`iframes()` 恒空集。⚠ 但见 C-3：WebView2 原生控件是否同样吞 mousemove，需 R2 实测——若实测拖动跨控件区断掉，此处不是删除而是要改成对 `.web-body` 区域的同款处理。）

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ -22,4 +22,3 @@
 _tabs = None            # WebTabs 单例（main._patched_ready 装配）
-_lock = threading.Lock()
```
（`_lock` 定义后全文件零引用；`import threading` 仍被其他处使用，保留。）

### A12【P1 / W4-止血】设置页 CDP 文案对齐现实

`web/js/settings.js:787`。设置页承诺「AI 可用 devtools_* 工具操作浏览器」，但 W4 证实网页 tab 内容 CDP 完全不可达（独立 UDF=独立进程，9222 被主 UI 进程先占）。在 D2 方案落地前，文案先不撒谎：

```diff
--- a/web/js/settings.js
+++ b/web/js/settings.js
@@ -787,3 +787,3 @@
       + (on ? '<b style="color:var(--accent)">已开启</b>' : '已关闭')
       + '<small style="color:var(--muted);font-weight:400;">　' + (on
-        ? (live ? 'AI 可用 devtools_* 工具操作浏览器' : '已保存——重启工具后生效')
+        ? (live ? 'AI 可用 devtools_* 工具操作工具主界面（网页 tab 内容暂不可达，修复中）' : '已保存——重启工具后生效')
```

---

## D. 设计级补丁（方案已定，需拍板后出正式 diff）

### D1【P1 / W3】主 UI 刷新三重错乱：pagehide 回收 + seq 握手 + tab id 页面纪元

三重根因：① 后端 `_want_seq` 进程内只增不减，前端 sq 刷新即归零 → 刷新后一切 show/hide 被丢弃，旧控件可永久盖住 UI；② 前端 tab id 从 `web-1` 重新分配与幸存控件撞名 → `create` 命中 `tab_id in self._ctl` 直接 navigate 旧控件；③ 刷新前所有控件无人 dispose → 全部泄漏。

方案（三层一起上，缺一不可）：

1. **前端 pagehide 统一回收**（`web/js/web-panel.js` 新增，index.html 的 debug-only beacon 不动）：
```js
// R1 审计 W3：页面卸载（刷新/关闭）→ 回收全部网页控件 + 后端会话水位
// 归零。原先 web 控件无任何卸载清理（api_reload_disconnect 只管串口/SSH）
window.addEventListener('pagehide', function () {
  try {
    navigator.sendBeacon('/api/web/tabs',
      JSON.stringify({ act: 'dispose_all' }));
  } catch (_) {}
});
```
2. **后端新增 `dispose_all` act + 会话重置**（`src/web_tabs.py` register 内，`dispose` 分支后）：
```python
if act == "dispose_all":
    r = t.dispose_all()          # 方法已存在（当前无调用方，正好启用）
    t.reset_session()            # 新方法：_want_seq=0; _want=None;
    return jsonify(r)            #          _pend_nav.clear(); _cancel.clear()
```
> 注意与 D3（多客户端）耦合：任一客户端刷新都会 dispose_all 杀掉其他客户端的网页 tab。单客户端形态下这是正解；多客户端支持落地时改为按「会话 id」分组回收。

3. **tab id 加页面纪元前缀**（`web/js/web-panel.js:106-107`）：
```js
const _webPageEpoch = String(Date.now() % 1e8);   // 页面实例纪元：刷新后不与后端幸存控件撞名
const portId = 'web:' + _webPageEpoch + ':' + (++_webSeq);
const ctlId  = 'web-' + _webPageEpoch + '-' + _webSeq;
```
后端把 tab_id 当不透明字符串（现状即如此），无配套改动。

### D2【P1 / W4】CDP 触达网页 tab

根因三连：web tab 环境独立 UDF=独立浏览器进程；两进程都带 `--remote-debugging-port=9222`（同一环境变量注入），主 UI 先启先绑，web tab 进程绑不上静默继续；`devtools_cdp.find_page_target` 只按工具后端 origin 过滤 target。

方案（推荐 a + b 一起）：

- **a. 给 web tab 环境显式独立 CDP 端口**（`src/web_tabs.py:_ensure_env`）：
```python
opts = C.CoreWebView2EnvironmentOptions()
opts.AdditionalBrowserArguments = "--remote-debugging-port=9223"
task = C.CoreWebView2Environment.CreateAsync(None, udf, opts)
```
  显式 options 优先生效并屏蔽环境变量继承（顺带成为 W1 的纵深防御：网页 tab 进程不再吃 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`）。`devtools_cdp` 改为多端口发现：探测 `9222`（主 UI）与 `9223`（网页 tab 池），`find_page_target` 增加「按 tab 匹配」入口——tab_id 与 CDP target 的映射靠 `web_tabs` 维护（tab_id → 当前 URL → `/json/list` 匹配，或给每 tab 注入 `window.__fcTabId` 后经 Runtime.evaluate 认领）。
- **b. 端口占用策略**：9223 被占时 web tab 环境退化为无 CDP（不阻塞浏览器功能），设置页 `web_cdp_live` 探活同步覆盖 9223。

### D3【P2 / W8】多客户端事件扇出

现状：事件推送目标是唯一的 `self._main_cvw`（第一个 UI 文档）；第二客户端零送达，且 seq/Bounds 双端互踩。目标形态：

- 后端维护「UI 会话列表」：每客户端首访 layout/show 时登记（含自增 sid），`_push` 改为遍历扇出；
- 事件改走 SSE（`/api/web/events?sid=`）或每客户端轮询自己的事件队列（现有 SSE 基建在 server.py 已有先例可抄）；
- Bounds 显隐意图按会话隔离（`_want`/`_want_seq` 从单值变 per-sid），控件显示权归「最近操作的会话」；
- D1 的 pagehide 回收改为 `dispose` 自己会话创建的 tab（tab 记录属主 sid）。

工作量集中在 web_tabs.py 状态结构（`_ctl` 值加属主元组），前端只需在 `_webCtl` 调用带 sid。**拍板点**：是否真要支持多 UI 客户端？若产品定调「单实例单 UI」（现状mutex 已保证单实例），则反向收紧：后端检测第二 UI 文档接入时拒绝 web tab 操作并提示——成本几乎为零。

### D4【P2 / B2】发送链路静默失败（位置在审计范围外，给定位）

黑盒实锤：网页 tab「发给 Claude」填入正常，点击发送 → `POST /api/harness/connect` 503 `{"err":"Claude 后端未就绪（worker 未启动）","ok":false}` → **UI 无任何反馈且输入框已被清空**。修复点在 harness 发送路径（`web/js/harness/`，不在本审计 diff 范围内）：非 ok 响应时 `showBanner(err, 4000, true)` + **恢复输入框内容**（失败不许丢用户输入）。本审计只登记，修复建议走 harness 模块自己的修复批次；R2 黑盒会复验该路径。

### D5【P3 / B3】多客户端 `web-session` 互踩

同源 localStorage 共享键 `web-session`，双客户端 last-write-wins：A 保存的导航栈被 B 覆盖，刷新后双方恢复出同一状态。方案：**写权归一**——只有「持有 web 心跳锁」的客户端允许写 web-session（写前 `navigator.locks`（WebView2 Chromium 支持 Web Locks API）或 localStorage 心跳时间戳仲裁），其余客户端只读。若 D3 拍板「单 UI」定调，此问题随之消失（外部浏览器打开 UI 属调试形态）。

### D6【P3 / B6】`/api/*` 404/405 响应形态一致化

错误方法/未知 API 路径返回 Flask HTML 404/405，与全局 JSON 错误口径不一致（AI 与脚本消费方解析困难）。server.py 增加：

```python
@app.errorhandler(404)
@app.errorhandler(405)
def _api_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "err": "%s %s" % (e.code, e.name)}), e.code
    return e
```

---

## C. 核伪 / 环境项 / 存疑（不打补丁）

| 项 | 处置 |
|---|---|
| W10「`list()` 快照非原子」 | **部分核伪**：CPython 下 `list(dict.items())` 是单次 C 调用，GIL 内原子；真正成立的部分是 `_lock` 死定义（A11 清理）与 W5/W6 的逻辑竞态（A3/A5 已补）。R2 复核后可关。 |
| B5 8765 端口冲突 | 环境项：隔离测试实例与真实实例抢 8765。R2 起隔离实例改用自定义端口（`server.py:3599` 硬编码 8765，测试时用环境变量或临时改绑定前探活）。 |
| 白盒存疑区 8 条 | 见 `rounds/round-1-whitebox.md` 文末，R2 逐条复核升级或关闭。 |
| R2 新增实测种子 | ① 侧栏拖动跨 **WebView2 原生控件**区域是否断（a524 同款问题的新表面，A11 删 iframes() 前必须先实测）；② 地址栏 `javascript:` 在 WebView2 Navigate 的真实行为（A10 留的取舍点）；③ A1 移除开关后的三条外链链路回归。 |

## 建议新增测试（`tests/test_web_tabs_logic.py`）

- W5：create 后（_pending 在途）立即 dispose → 断言 `_cancel` 命中、`_build` 不产出控件（可用假 form 收集 BeginInvoke 回调同步执行）。
- W6：`_ctl` 有值但 CoreWebView2 None 时 navigate → 断言 URL 进 `_pend_nav`。
- W7：act=show 传 `sq:"NaN"` / `on:"false"`、layout 传 `"abc"` → 断言 200 JSON（不 500）且语义正确。
- W12：`_on_new_window` 空 URI → 断言以 about:blank 降级（推送参数）。
- W3：dispose_all 后 `_want_seq/_want/_pend_nav` 归零。
- 前端逻辑（若引入 JS 测试）：`_webNormUrl` scheme 白名单表驱动用例；`_webNavigate(url, c)` 定向用例。
