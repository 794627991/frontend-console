# 补丁 · 第 2 轮（提案，未应用）

> 生成：2026-11-13（R2 收尾）。依据：`rounds/round-2-whitebox.md`（W14–W20）+ `rounds/round-2-blackbox.md`（R2-B1/B2/B3，台账编号 **B7/B8/B9**）。
> 性质：**纯提案 md，未修改任何代码文件**。所有行号以基线 d9c8886 为准；第一节的修订基于 patch-round-1 已应用的前提。
> 结论摘要：R1 补丁 **8 条干净**（A1/A2/A3/A5/A6/A7/A9/A12），**5 条需修订**（下述 A4'/A8'/A10'/A11'/D1'）；新增修复 2 条（N1/N2）、新增设计拍板项 2 条（D7/D4'）。

---

## 一、R1 补丁修订（应用时替换 patch-round-1 对应节）

### A4'（修订 A4，修 W14/P2）——失败推送并入 `_rm`，经 `_ui` 走 UI 线程

R1 版把 `__webTabDead` 推送写在 ContinueWith **池线程回调**里：违反 a549 线程亲和铁律，`InvalidOperationException` 被 `except` 吞掉 → 前端永不收到通知，W13 修复在最需要它的失败路径上自失效。修法：推送体并入 `_rm`（本就经 `_ui` 在 UI 线程执行）。

```diff
--- a/src/web_tabs.py（替换 patch-round-1 A4 的后端块）
@@
         def _init_done(t):
             try:
                 t.Result    # 确保异常在此可见
             except Exception as e:
                 _log("ERROR", "EnsureCoreWebView2Async: %r" % e)
                 # R1 审计 W13：初始化失败原先只记日志——死控件永留 _ctl，
                 # tab 假活（无重试/无回收/无提示）。回收控件 + 通知前端关 tab。
                 self._ctl.pop(tab_id, None)
                 self._pend_nav.pop(tab_id, None)
 
                 def _rm():
                     try:
                         self._form.Controls.Remove(ctl)
                         ctl.Dispose()
                     except Exception:
                         pass
+                    # R2 审计 W14：通知前端必须在 UI 线程发（a549 铁律）。
+                    # R1 版在池线程直调 ExecuteScriptAsync——异常被吞，
+                    # __webTabDead 永不送达。并入 _rm（经 _ui 通道）。
+                    m = self._main_cvw
+                    if m:
+                        try:
+                            m.ExecuteScriptAsync(
+                                "window.__webTabDead && window.__webTabDead(%s, %s)"
+                                % (json.dumps(tab_id), json.dumps(str(e))))
+                        except Exception:
+                            pass
                 self._ui(_rm)
                 return
```

前端 `window.__webTabDead`（patch-round-1 A4 的前端块）经 W14 评审核验安全（同步 find + `_edCloseNow` 同步清理，无重入问题），**维持不变**。

### A8'（修订 A8，修 W15/P3 + B7/P2）——`_webCur()` 变体族全量参数化

B7（R2-B1）黑盒三连坐实：`_webAct`（:576）全按钮族作用于**激活 tab**——对非激活 tab 点 ★ 收藏进激活 tab 的 URL、☰ 阅读模式开在激活面板、「发给 Claude」填激活 tab 的内容。W15 白盒补刀：A8 只改 3/6 个 `_webNavigate` 调用点，`:495` 唤醒巡检仍回落 `_webCur()`。

本修订不止补调用点，而是把「所属 tab」语义贯通整条按钮/状态链。grep 全量核对后涉及 4 个函数 + 6 个调用点：

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -575,7 +575,10 @@
 function _webAct(act, wrap) {
-  const c = _webCur();
+  // R2 审计 B7：按钮属于哪个 wrap 就操作哪个 tab——原取 _webCur()，
+  // 对非激活 tab 点 ★/☰/发给Claude/后退/前进/刷新 全落在激活 tab 上
+  //（黑盒行为级三连坐实）。wrap.dataset.portId 即按钮所属 tab。
+  const c = connections[(wrap && wrap.dataset.portId) || ''] || _webCur();
   if (!c) return;
@@ -501,7 +504,8 @@
-function _webReaderToggle(on, skipRestore) {
-  const c = _webCur();
+function _webReaderToggle(on, skipRestore, c) {
+  c = c || _webCur();        // R2 审计 B7：可指定所属 tab（同型变体）
   if (!c) return;
@@ -553,7 +557,8 @@
-function _webApplyZoom(z, host) {
+function _webApplyZoom(z, host, c) {
   // a555 审计修：原 connections[WEB_PORTID] 恒 null——缩放全链路死代码
-  const c = _webCur();
+  c = c || _webCur();        // R2 审计 B7：可指定所属 tab（同型变体）
   if (!c) return;
@@ -564,7 +569,8 @@
-function _webSyncUI() {
-  const c = _webCur();
+function _webSyncUI(c) {
+  c = c || _webCur();        // R2 审计 B7：可指定所属 tab（同型变体）
   if (!c) return;
```

调用点补齐（全部 6 处，grep 全量核对）：

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -206,3 +206,3 @@       # Ctrl+滚轮缩放（wheel 事件就发生在本 wrap 上）
-    _webApplyZoom(z, host);
+    _webApplyZoom(z, host, c2);
@@ -214,3 +214,3 @@       # Ctrl+0 复位
-      _webApplyZoom(1, host);
+      _webApplyZoom(1, host, cz);
@@ -405,3 +405,3 @@       # _webNavigate 内退出阅读态
-  if (c._ui.reader) _webReaderToggle(false, true);
+  if (c._ui.reader) _webReaderToggle(false, true, c);
@@ -411,4 +411,4 @@       # _webNavigate 内缩放+按钮态（A8 已有 c 参数）
-  _webApplyZoom(_webZoomFor(url), _webHostOf(url));
-  _webSyncUI();
+  _webApplyZoom(_webZoomFor(url), _webHostOf(url), c);
+  _webSyncUI(c);
@@ -495,3 +495,3 @@       # 1s 唤醒巡检（W15：原回落 _webCur() 恢复进错误 tab）
-      if (url) _webNavigate(url);
+      if (url) _webNavigate(url, c);
@@ -582,3 +582,3 @@       # _webAct reload 分支
-    if (c._ui.reader) _webReaderToggle(true);    // 阅读态重载=重取正文
+    if (c._ui.reader) _webReaderToggle(true, false, c);    // 阅读态重载=重取正文
@@ -586,3 +586,3 @@       # _webAct read 分支
-  if (act === 'read') { _webReaderToggle(!c._ui.reader); return; }
+  if (act === 'read') { _webReaderToggle(!c._ui.reader, false, c); return; }
```

同时更正 patch-round-1 A8 的文档：其自述「调用点修正（3 处）」实为 6 处调用点中遗漏 `:495`（W17②）。

**其余 `_webCur()` 调用点判定表**（grep 全量 20 处，逐一处置）：

| 行号 | 所在函数 | 判定 |
|---|---|---|
| :46 `_webSessionSave` | 只存激活 tab 的 nav | 归 D5（共享单栈模型），不属本变体族 |
| :99 `buildWebPanelTab` | 紧随 `switchTab(pid)` | 正确（`_webCur()` 恒等于目标） |
| :201/:211 Ctrl+滚轮/Ctrl+0 | **修订**（上 diff） | 变体：事件在本 wrap 上却读激活 tab |
| :280 `_webCtlVisible` | 显隐**当前屏幕上**的控件 | 正确（激活语义即本意） |
| :365/:373 浮层联动 | 藏激活控件 | 正确（a551 语义） |
| :395 `_webNavigate` | A8 已参数化 | 已修 |
| :422 `switchTab` prev | 记录切换前 tab | 正确 |
| :495 1s 唤醒巡检 | **修订**（上 diff） | 变体（W15） |
| :502/:553/:564 三函数定义 | **修订**（上 diff） | 变体 |
| :576 `_webAct` | **修订**（上 diff） | 变体（B7 主证） |
| :689/:694/:698 侧栏入口/最近 | 全局入口渲染 | 正确（激活语义） |

### A10'（修订 A10，修 W16/P3）——白名单收窄，`file:` 显式拦截

R1 版白名单放行 `file:` → 地址栏可把内嵌浏览器变成本地文件/UNC 共享查看器（未拍板的行为变更）。收窄 + 显式拦截提示：

```diff
--- a/web/js/web-panel.js（替换 patch-round-1 A10）
@@ -80,9 +80,14 @@
 function _webNormUrl(s) {
   s = String(s || '').trim();
   if (!s) return '';
+  // R2 审计 W16：scheme 白名单收窄为 http(s)/about。file:/javascript:
+  // /data: 等显式拦截（R1 版放行 file: = 内嵌浏览器成为本地文件/UNC
+  // 查看器；javascript: 在 WebView2 Navigate 的行为未实测，先拦）。
+  if (/^(file|javascript|data|vbscript):/i.test(s)) return '';
   if (/^(https?|about|mailto|ftp|ws|wss):/i.test(s)) return s;
   return 'http://' + s;    // 内网多为 http 裸主机名——缺省补 http
 }
```

配套：地址栏回车处给拦截一个可见反馈（`:171` 的 `if (!u) return;` 只有无输入才静默）：

```diff
@@ -171,3 +171,6 @@
       const u = _webNormUrl(urlInput.value);
-      if (!u) return;
+      if (!u) {
+        if (urlInput.value.trim()) showBanner('该协议不允许在内嵌浏览器打开', 2500, true);
+        return;
+      }
```

### A11'（修订 A11，修 W17/P3）——补删孤儿 `import threading`

R1 版 A11 注「`import threading` 仍被其他处使用」**失实**（grep 全文件：唯一使用点就是被删的 `_lock`）。补删：

```diff
--- a/src/web_tabs.py（在 patch-round-1 A11 基础上追加）
@@ -19,3 +19,2 @@
 import json
-import threading
```

### D1'（修订 D1，修 W20/P3）——`dispose_all` 加页面纪元令牌

W20：pagehide beacon 与新页面首批 create 存在乱序窗口——迟到 beacon 会 dispose_all 杀掉刚重建的 tab 并归零 `_want_seq`。与 D1-3 的纪元前缀天然配套：

- 前端所有 `_webCtl` 调用与 pagehide beacon 统一带 `epoch: _webPageEpoch`；
- 后端 `create(tid, url, epoch)` 记录 `self._epochs[tab_id] = epoch`；
- `dispose_all(epoch)` **只回收 `_epochs[tab_id] == epoch` 的控件**，并仅当 `epoch` 不小于已见最大纪元时才 `reset_session()`（防旧纪元 beacon 把新页面的 seq 水位打回去）；
- `_epochs` 随 dispose 清理；无 epoch 字段的旧调用按「无主」处理（dispose_all 不碰）。

> D1 其余设计（pagehide 回收、seq 握手、纪元前缀）经 W14 评审核验成立：sendBeacon 字符串体 Content-Type=`text/plain;charset=UTF-8`，`get_json(force=True)` 可解析（黑盒 fetch 对照实测 200 vs 400）；纪元前缀 `web:<epoch>:<n>` 与 `sortKeyFn` 的 `startsWith('web:')` 兼容。

---

## 二、新增修复

### N1（修 W18/P3，B8 佐证）——fetch_text 证书校验改「默认验证，私网回落」

`src/web_proxy.py:82-85` 现状对所有 https 一律 `CERT_NONE`（docstring 只主张内网自签）——公网取页可被中间人投喂阅读正文/「发给 Claude」注入文本（提示注入通道）。B8 实测进一步证实该端点是**无内网限制的本机+局域网全读原语**（读出真实实例 8765 发布中心页含「默认密码 888888」提示、56278 状态接口、302→内网被跟随）。

```diff
--- a/src/web_proxy.py
@@ -82,10 +82,32 @@
     try:
-        ctx = _ssl.create_default_context()
-        ctx.check_hostname = False
-        ctx.verify_mode = _ssl.CERT_NONE
+        # R2 审计 W18：不再对所有 https 关闭校验（原实现超出 docstring
+        # 自述的「内网自签」范围——公网站点全程可被中间人投喂正文）。
+        # 默认走系统验证；仅当目标解析为私网/回环/链路本地地址时回落
+        # 不校验（内网自签场景，维持 docstring 语义）。
+        ctx = _ssl.create_default_context()
+        if _web_is_private_host(_web_url_host(url)):
+            ctx.check_hostname = False
+            ctx.verify_mode = _ssl.CERT_NONE
         with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
```

配套两个模块级 helper（放 `web_proxy.py` 顶部函数区）：

```python
def _web_url_host(u):
    try:
        from urllib.parse import urlsplit
        return (urlsplit(u).hostname or "")
    except Exception:
        return ""

def _web_is_private_host(host):
    """目标全部解析地址均为私网/回环/链路本地时 True（解析失败按公网
    处理——安全侧）。R2 审计 W18 配套。"""
    try:
        import ipaddress as _ip, socket as _socket
        infos = _socket.getaddrinfo(host, None)
        if not infos:
            return False
        for info in infos:
            ip = _ip.ip_address(info[4][0])
            if not (ip.is_private or ip.is_loopback or ip.is_link_local):
                return False
        return True
    except Exception:
        return False
```

> 已知取舍（R3 复核点）：getaddrinfo 增加一次 DNS 查询开销（fetch_text 本就是网络 IO，可接受）；解析与连接之间存在 TOCTOU 窗口（公网目标被本机 hosts 指到私网再反解的场景收益有限、风险低）；解析失败按公网（验证）处理是安全侧。

### N2（修 W19/P3）——`_safe_load` 非 http(s) scheme 一律拦截

`src/main.py:810-816`：`_safe_load` 只对 http(s) 走外链路由，**其余 scheme 无条件 `return _orig_load(url)`** → 工具 UI 内 `file:` 链接（Claude 回复渲染、日志/笔记内容）可把主窗口整页导航到本地文件。A2 只修了 http(s) 分支内部判定。初装时序已核验安全（initial load 在包装安装前，不被截胡——R2 报告五.12）。

```diff
--- a/src/main.py（基于 patch-round-1 A2 修订版叠加）
@@
             def _safe_load(url, *la, **kw):
                 try:
                     _u = str(url or "")
                     if _u.startswith(("http://", "https://")) and not _is_loopback(_u):
                         sender.CoreWebView2.ExecuteScriptAsync(
                             "window.__newWindow && window.__newWindow(%s);"
                             % json.dumps(_u))
                         return
+                    # R2 审计 W19：非 http(s)（file:/data:/about: 等）原先
+                    # 直落 _orig_load → 主 UI 内 file: 链接把工具窗口整页
+                    # 导航到本地文件。一律吞掉，仅放行 http(s) 回环目标。
+                    if not (_u.startswith("http://") or _u.startswith("https://")):
+                        return
                 except Exception:
                     pass
                 return _orig_load(url, *la, **kw)
```

---

## 三、新增设计拍板项

### D7（B8）——fetch_text 的内网全读语义

B8 实测：该端点可读**同机任意端口**的 HTTP 服务（含工具自身 API JSON、真实实例 8765 发布中心页）与**局域网**服务，302 跳内网被跟随。这是「内网工具」的设计内能力，但与 N1 合并后仍是完整的本机侦察原语。拍板项：
- a. 维持现状（本地单用户工具，调用方=工具自身 UI，N1 已堵住公网 MITM 注入）——**推荐**，成本零；
- b. 加设置开关（默认仅公网+显式白名单内网）；
- c. 响应里加「内网取页」标记，发给 Claude 时在正文头注明来源为内网（降低提示注入的可信度）。

### D4'（修正 R1-D4，依据 B9）——发送失败的真实缺陷是「输入不恢复」

B9 完整链路存档修正了 R1-B2 的「无任何反馈」：红色横幅**其实有**（`.notify.err` 约 3.5s），真正缺陷是 `send()` **先清空输入**、`ok:false` 路径不恢复 → 用户文本永久丢失。修复点不变（harness 发送路径，`POST /api/harness/connect` 503 `{"err":"Claude 后端未就绪（worker 未启动）","ok":false}`），修法改为：**非 ok 响应时恢复输入框原文**（横幅已有，无需补）。仍属 harness 模块范围（本审计 diff 之外），登记待修。

---

## 四、核伪 / 记录（不打补丁）

| 项 | 结论 |
|---|---|
| W10「list() 非原子」 | **核伪关闭**：C 层论证 + 20 万次并发压测零 RuntimeError（round-2-whitebox §二.9） |
| R1-B1/B3/B4/B6 回归 | 黑盒 R2 全部复现确认；B3 细化为「共享单栈模型：后写者追加、A 刷新后恢复出 B 的页面」 |
| B5 8765 端口 | 环境项关闭：根因=`server.py:3599` 独立入口硬编码 8765；隔离实例已改用临时区副本改端口（18765）方案 |
| D1 预演 | 链路可通（见 D1' 评注）；无头实例在 act 分发前被「控件管理器未装配」短路——`dispose_all` 落地验证需桌面端 |
| R1 存疑区 9 条 | 1 升级（W18）、1 核伪（W10）、7 关闭（理由见 round-2-whitebox §二） |
| fetch_text SSRF 其余面 | 起始 file:// 拒、**重定向到 file:// 实测被 urllib 拒**、URL 控制字符发送层拒、5MB/40K 截断有效、15s 超时——均实测通过 |

## 五、建议新增测试（增量，承接 round-2-whitebox §四 的 9 类）

10. A4'：失败分支断言 `__webTabDead` 脚本**经 BeginInvoke 队列**发出（钉住 W14，防回退到池线程直调）。
11. A8'：`_webAct`/`_webReaderToggle`/`_webApplyZoom`/`_webSyncUI` 的「非激活 tab 定向」用例（若引入 JS 测试设施）；`:495` 巡检定向。
12. A10'：`_webNormUrl` 表驱动补 file:/javascript:/data: → '' 用例。
13. N1：`_web_is_private_host` 表驱动（RFC1918/回环/公网/解析失败/多记录混合）——需把 helper 放模块级（本补丁已如此）。
14. N2：`_safe_load` 对 file:/data: 的拦截断言（helper 提级后可测）。
