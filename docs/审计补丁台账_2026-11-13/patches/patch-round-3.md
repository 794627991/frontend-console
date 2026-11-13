# 补丁 · 第 3 轮（提案，未应用）

> 生成：2026-11-13（R3 收尾）。依据：`rounds/round-3-whitebox.md`（W21–W27）+ `rounds/round-3-blackbox.md`（B10–B15，台账沿用黑盒编号）。
> 性质：**纯提案 md，未修改任何代码文件**。行号以基线 d9c8886 为准；基于 patch-round-1/2 已应用（含修订链 A4→A4'→A4''）的前提。
> 本轮要点：**N3（W22/P1）是当前最重的基线新面**；W21 再次证明补丁本身需要被对抗（A4' 换机制重演自失效）。

---

## 一、确定性补丁

### N3（修 W22/P1）——侧栏 ✕ 与抽屉「全部关闭」接管 web 关闭链

`web/js/sidebar.js:113-119` 的 `closeConnection` 转发正则只认 `^(edit|hex|diff|bindiff):`，web 落通用清理：**无 dispose REST、无 `_ctlResize.disconnect()`、无 resize 监听移除、无 `_webActivePid` 清理** → ① 后端控件永不 Dispose（W5 级隐形孤儿）；② 幽灵 resize 监听对已删 wrap 读出全零 rect → 发 `layout(0,0,0,0)` → **所有存活网页控件被缩到 50×50**，且按陈旧 `_want` 重排显隐。两条产品可达路径：侧栏行 ✕（sidebar.js:250 `else closeConnection(pid)`）与抽屉「全部关闭」（util.js:243 批量循环 web 不在 `isEd` 列表）。

```diff
--- a/web/js/sidebar.js
+++ b/web/js/sidebar.js
@@ -113,13 +113,16 @@
 function closeConnection(portId) {
   // D-3（P3）附带防御：直调 closeConnection 绕过编辑器完整 dispose 链
   // （hex/diff/bindiff 无专属关闭函数——四类统一转发，sidebar.js:198/:233 实证）
   // （编辑器 _edCloseNow 的完整 dispose）=5 倍泄漏（3.1MB/次 vs 0.58MB）
-  if (/^(edit|hex|diff|bindiff):/.test(portId) &&
+  // R3 审计 W22（P1）：web 必须同样转发——web-panel 的 closeEditorTab
+  // 包装负责 dispose REST + resize/layout 监听清理 + _webActivePid 清理；
+  // 落本函数通用清理 = 控件永不 Dispose + 幽灵监听发 layout(0,0,0,0)
+  // 把全部存活网页控件缩成 50×50（侧栏 ✕ 与抽屉批量关闭两条路径可达）
+  if (/^(edit|hex|diff|bindiff|web):/.test(portId) &&
       typeof closeEditorTab === 'function') {
     closeEditorTab(portId); return;   // 产品路径四类统一走 closeEditorTab
                                       // （sidebar.js:198/:233 实证）
   }
```

```diff
--- a/web/js/util.js
+++ b/web/js/util.js
@@ -235,6 +235,12 @@       # 抽屉「全部关闭」批量循环（util.js:229-246）
         if (kind === 'harness') {
           if (typeof _harnessClose === 'function') _harnessClose(pid);
           return;
         }
+        if (kind === 'web') {
+          // R3 审计 W22：必须走 closeEditorTab 包装（dispose REST + 监听
+          // 清理），落 closeConnection 通用清理即 W22 全套后果
+          if (typeof closeEditorTab === 'function') closeEditorTab(pid);
+          return;
+        }
         const isEd = kind === 'editor' || kind === 'hex' || kind === 'diff' ||
```

### A4''（修 W21/P2）——except 变量先固化为普通局部，再进闭包

R2 版 A4' 的 `_rm` 闭包引用 `except ... as e` 的 `e`：CPython 块尾隐式 `del e` 清空 cell → BeginInvoke 延迟执行 `str(e)` 抛 NameError 被吞 → `__webTabDead` 永不送达（**运行时实测复现**，换机制重演 W14 自失效）。

```diff
--- a/src/web_tabs.py（替换 A4' 中 _init_done 失败分支）
@@
         def _init_done(t):
             try:
                 t.Result    # 确保异常在此可见
             except Exception as e:
                 _log("ERROR", "EnsureCoreWebView2Async: %r" % e)
+                # R3 审计 W21：except 变量在块尾被 CPython 隐式 del——闭包
+                # 延迟执行时 str(e) 抛 NameError 被吞（实测复现）。先固化
+                # 为普通局部变量再进 _rm 闭包。
+                err = str(e)
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
                     # R2 审计 W14：通知前端必须在 UI 线程发（a549 铁律）
                     m = self._main_cvw
                     if m:
                         try:
                             m.ExecuteScriptAsync(
                                 "window.__webTabDead && window.__webTabDead(%s, %s)"
-                                % (json.dumps(tab_id), json.dumps(str(e))))
+                                % (json.dumps(tab_id), json.dumps(err)))
                         except Exception:
                             pass
                 self._ui(_rm)
                 return
```

### A10''（修 W23/P3）——顶栏地址栏对非法协议同样给可见反馈

A10' 的拦截反馈只加在面板地址栏；顶栏（`web-panel.js:676`）把 `file:`/`javascript:` 静默当「空输入」→ 误开一个会话恢复空 tab 且零反馈。

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -674,9 +674,13 @@
   if (bar) bar.addEventListener('keydown', (e) => {
     if (e.key !== 'Enter' || e.isComposing) return;
     e.preventDefault();
     const u = _webNormUrl(bar.value);
-    if (!u) { buildWebPanelTab(); bar.blur(); return; }   // 空=开网页 tab（有会话则恢复）
+    if (!u) {
+      // R3 审计 W23：非空输入被 _webNormUrl 拦成 ''（file:/javascript: 等）
+      // = 非法协议，给可见反馈；真空输入才走「开网页 tab（恢复会话）」
+      if (bar.value.trim()) { showBanner('该协议不允许在内嵌浏览器打开', 2500, true); return; }
+      buildWebPanelTab(); bar.blur(); return;
+    }
```

### A8''（修 W26/P3）——`_webSyncUI` 遗留 3 个无参调用点

A8' 参数化了 `_webSyncUI(c)` 但 `:611/:615`（`_webAct` star 分支）与 `:732`（收藏夹菜单删除收藏）仍无参回落激活——B7 场景下点的那颗 ★ 状态不变；`:732` 真实用户可达（删除收藏后后台 tab 的 ★ 保持高亮脏态）。

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -611,3 +611,3 @@       # _webAct star 分支（收藏成功后）
-          _webSyncUI();
+          _webSyncUI(c);
@@ -615,3 +615,3 @@       # _webAct star 分支（取消收藏后）
-    _webSyncUI();
+    _webSyncUI(c);
@@ -732,3 +732,10 @@      # 收藏夹菜单删除收藏分支
       _webFavsSave(favs2);
       list.remove();
       _webFavMenu(anchor);
-      _webSyncUI();
+      // R3 审计 W26：删除的收藏可能正被任意后台网页 tab 持有——逐个
+      // 同步星标态（web tab 数量少，全量同步成本可忽略）
+      for (const pid in connections) {
+        const cw = connections[pid];
+        if (cw && cw.meta && cw.meta.kind === 'web') _webSyncUI(cw);
+      }
       return;
```

### N4（修 B12/P3）——fetch_text 失败文案统一，不外露内部异常

`web_proxy.py:93-94` 的 `str(e)[:180]` 直出内部异常原文（B12 实测：非 ASCII 主机 → latin-1 编码异常全文）。

```diff
--- a/src/web_proxy.py
+++ b/src/web_proxy.py
@@ -93,8 +93,15 @@
-    except Exception as e:
-        return jsonify({"ok": False, "err": "取页失败：%s" % str(e)[:180]})
+    except Exception as e:
+        # R3 审计 B12：内部异常原文不外露（非 ASCII 主机的 latin-1 编码
+        # 异常等直出到响应体）——常见失败给可读文案，其余只给类型名
+        _kind = type(e).__name__
+        _hint = {
+            "UnicodeEncodeError": "不支持该主机名/地址编码",
+            "URLError": "无法连接目标（域名不存在或网络不可达）",
+            "TimeoutError": "取页超时",
+            "ValueError": "未知 URL 形态",
+        }.get(_kind)
+        return jsonify({"ok": False, "err": "取页失败：" + (_hint or _kind)})
```

### N5（修 B13/P3）——`_webFavs` 校验 + 自愈

`web/js/web-panel.js:63-65`：localStorage 存入非数组（旧版本/手工改写/损坏）→ `favs.map`/`splice` 抛错 → 收藏菜单打不开、星标 toggle 静默无效，**刷新重启均不自愈**。web-session 同文件就有容错口径，此处对齐。

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -63,5 +63,13 @@
-function _webFavs() {
-  try { return JSON.parse(localStorage.getItem('web-favs') || '[]'); } catch (_) { return []; }
-}
+function _webFavs() {
+  // R3 审计 B13：非数组/元素缺 url 的畸形历史值原先原样返回 → 上层
+  // .map/.splice 抛错，收藏功能整体静默失效且永不自愈。校验 + 回写自愈。
+  try {
+    const v = JSON.parse(localStorage.getItem('web-favs') || '[]');
+    if (!Array.isArray(v)) { _webFavsSave([]); return []; }
+    const ok = v.filter(x => x && typeof x === 'object' && typeof x.url === 'string');
+    if (ok.length !== v.length) _webFavsSave(ok);
+    return ok;
+  } catch (_) { try { _webFavsSave([]); } catch (_e) {} return []; }
+}
```

### N1'（修 W25/P3，B11 佐证）——fetch_text 阻断自动重定向，逐跳重分类 SSL ctx

N1 按入口 host 一次性分类，ctx 随 urllib 自动重定向**继承**：私网自签 302 跳公网 = CERT_NONE 套在公网连接上（B11 实测 301/302/307/308 全贯通）。改为手动逐跳：每跳按新 host 重建 ctx，非 http(s) 跳转拒绝，6 跳封顶。

```diff
--- a/src/web_proxy.py
+++ b/src/web_proxy.py
@@ -70,6 +70,12 @@
     import ssl as _ssl
     import urllib.request
+    class _NoRedirect(urllib.request.HTTPRedirectHandler):
+        """R3 审计 W25：阻断自动重定向——逐跳按目标 host 重建 SSL ctx
+        （私网/公网逐跳重分类，防「私网 ctx 经重定向套在公网连接上」）。"""
+        def redirect_request(self, req, fp, code, msg, headers, newurl):
+            return None
+
     data = request.get_json(force=True, silent=True) or {}
     url = str(data.get("url") or "").strip()
@@ -82,17 +88,45 @@
     try:
-        ctx = _ssl.create_default_context()
-        if _web_is_private_host(_web_url_host(url)):
-            ctx.check_hostname = False
-            ctx.verify_mode = _ssl.CERT_NONE
-        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
+        # R3 审计 W25：手动逐跳跟随（≤6 跳），每跳重建 opener+ctx
+        from urllib.parse import urljoin as _urljoin
+        cur = url
+        resp = None
+        for _hop in range(6):
+            ctx = _ssl.create_default_context()
+            if _web_is_private_host(_web_url_host(cur)):
+                ctx.check_hostname = False
+                ctx.verify_mode = _ssl.CERT_NONE
+            _opener = urllib.request.build_opener(
+                urllib.request.HTTPSHandler(context=ctx), _NoRedirect)
+            _req = urllib.request.Request(cur, headers={
+                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
+                               "AppleWebKit/537.36 (KHTML, like Gecko) "
+                               "Chrome/124.0 Safari/537.36"),
+                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
+            })
+            try:
+                resp = _opener.open(_req, timeout=15)
+            except urllib.request.HTTPError as he:
+                if he.status in (301, 302, 303, 307, 308) and he.headers.get("Location"):
+                    _nxt = _urljoin(cur, he.headers["Location"])
+                    if not _nxt.startswith(("http://", "https://")):
+                        return jsonify({"ok": False,
+                                        "err": "取页失败：重定向到不支持的协议"}), 400
+                    cur = _nxt
+                    continue
+                raise
+            break
+        else:
+            return jsonify({"ok": False, "err": "取页失败：重定向次数过多"})
+        with resp as r:
             raw = r.read(5 * 1024 * 1024)
             cs = _web_detect_charset(r.headers.get("Content-Type"), raw)
             try:
                 text = raw.decode(cs, "replace")
             except LookupError:
                 text = raw.decode("utf-8", "replace")
```

> 配套记录：TOCTOU 双方向（私网分类后 hosts 改指公网）在 R3 评审核验中补记为观察项；`::ffff:` v4-mapped 形态边缘记录。

---

## 二、设计修订

### D1''（修 W24/P2 + B14 佐证）——dispose_all 覆盖在途 create；_epochs 清理补全；epoch 加随机后缀

- **W24 空洞**：D1' 的 `dispose_all(epoch)` 只遍历 `_ctl`，`_pending` 在途 create（含首开最长 5s env 等待窗）不可见 → 刷新落在窗口内孤儿照建，且旧纪元标记使后续 dispose_all **永久跳过**（纪元隔离反而关死了 A3 的回收路径）。修订：`dispose_all(epoch)` 对 `_ctl ∪ _pending` 并集处置——`_ctl` 命中走 dispose；`_pending` 命中走 A3 cancel 路径（登记 `_cancel` + 清 `_pend_nav` + 清 `_epochs`）。
- **`_epochs` 清理补全**：A3 的 cancel 路径与 A4'' 的失败回收路径同步 `self._epochs.pop(tab_id, None)`（D1' 只写了 dispose 一处）。
- **B14 佐证采纳**：多客户端 tab id 撞名（A 刷新后 `web-1` = B 的 `web-1`）实测造成浮层联动跨客户端串隐——D1'-3 的纪元前缀 id 正是解药；epoch 建议追加随机后缀（`Date.now()%1e8 + '-' + Math.random().toString(36).slice(2,6)`）杜绝同毫秒碰撞。
- 跨客户端 `show(on:false)` 串隐的完整解法仍在 **D3**（会话隔离或单 UI 收紧），纪元前缀只解撞名不解广播语义。

### W27（测试质量）——建议清单（不改测试文件，仅登记）

1. `_FakeTask.ContinueWith` 改「延迟派发续延」复现池线程异步序（抹平 a549/W14/W21 族的结构性盲区——A4'' 的回归断言必须经 BeginInvoke 通道 + 消息非空双钉）。
2. `test_show_snapshot_vs_dispose_race` 更名或真并发化（当前 sync 模式零交错）。
3. 新增：W22 双路径关闭（侧栏 ✕ / 抽屉批量 → 断言 dispose REST 已发 + 无幽灵 layout）、W24（dispose_all 在 create 在途时命中 `_pending`）、N4/N5 表驱动、A6 REST 层（Flask test client + 桩装配）。

---

## 三、记录（不打补丁）

| 项 | 处置 |
|---|---|
| B10（P2） | A8' 验收基线：12 格全矩阵坐实变体族——补丁应用后的回归断言集 |
| B11（P2） | N1' 佐证：跨协议重定向全贯通 + 自签 https 被接受（CERT_NONE 实锤）；头反射干净、gzip 炸弹不成立、40K 边界精确、并发 20/20 通过 |
| B15（P3） | W9/A7 黑盒再证（12 个 web tab 全平铺无抽屉）——A7 落地即解 |
| B14（P2） | 归 D1''/D3（见上） |
| W22 附带 | `POST /api/disconnect {port_id:"web:…"}` 必败噪音请求——N3 转发后自然消失 |
| A8' 判定表 | 白盒 R3 全量对账**通过**（17 调用表达式逐一归位，无第 8 处漏网） |

## 四、桌面端验证清单（v2，承接 round-3-whitebox §四 的 10 项）

10 项清单在 `round-3-whitebox.md` §四（D2 参数合并语义、9223 触达、javascript: Navigate、A1 三链回归、dispose_all 真实回收、N2 内部 load、mailto/ws: 行为、W22 修复回归、a551 叠放、休眠真机），每项带步骤与预期，此处不重复。补 2 项：
11. N3 回归：侧栏 ✕ 关网页 tab / 抽屉「全部关闭」→ 后端日志见 dispose、resize 后其余控件布局正常（不再 50×50）。
12. N5 回归：localStorage 写入 `"just-a-string"` → 收藏菜单可开、存储被自愈回 `[]`。

## 五、建议新增测试（增量）

15. W22：双路径关闭 → 断言 dispose REST 发出 + 无 `layout(0,0,0,0)` 幽灵请求（可拦 fetch 层）。
16. W24：`dispose_all(epoch)` 在 `_pending` 在途时 → 断言 cancel 命中、`_build` 零产出、`_epochs` 无残项。
17. A4''：失败分支断言推送**经 BeginInvoke 通道**且 `err` 非空（双钉 W14/W21）。
18. N1'：重定向逐跳 ctx 重分类（私网→公网 302 后公网段必须验证；非 http(s) Location 拒绝；6 跳封顶）。
19. N4/N5：表驱动（B12 的 latin-1 形态；web-favs 非数组/缺 url/混合畸形）。
