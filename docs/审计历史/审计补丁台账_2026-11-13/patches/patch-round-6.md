# 补丁 · 第 6 轮（提案，未应用——P1' 修订待 R7 白盒定稿）

> 生成：2026-11-13（R6 收尾）。依据：`rounds/round-6-whitebox.md`（W32）。
> 状态：**W32（P1）为 P1' 补丁引入的回归**，非新基线面——R5 的基线静态收敛判定**维持成立**（基线确凿终态 W1–W31 + B1–B19 不变）；patch-round-1..4 维持通过，patch-round-5 仅 P1' 需修订。

---

## W32（P1，补丁引入）

P1' 的守卫（`if (!c._ui.reader && !c._ui.sleeping) _webCtlVisible(true);`）静默抑制 show 后留下**陈旧 `_want=(B,True)`**（B=前一个激活网页 tab）。切到阅读态 tab 后，`_ctlPush` 定时器（30ms）/ResizeObserver/任意 resize 触发 `layout._apply` → `_apply_visibility` 排他分支按陈旧意图把 **B 的控件 Visible=True+BringToFront** → 错误 tab 的页面盖住 A 的阅读视图。**必然发生**（非概率性），直到阅读退出才自愈——比 W31 的同 tab 遮盖严格更糟。

## 修复分析与候选方案（**R7 白盒定稿：P1''，整体取代 P1'**）

- 白盒 R6 建议一行修：抑制分支补显式 `_webCtlVisible(false)` 刷新 `_want`。
- ⚠ **主控对抗推演：该一行修在多网页 tab 场景仍不完整**——`show(A,false)` 只藏目标（a556 语义「visible=False 只藏目标」），B 的控件失去唯一由排他显示分支执行隐藏的机会（切换 B→A 的基线排他隐藏正是靠 `show(A,true)`）→ **B 的 HWND 盖住 A 的阅读视图**（跨 tab 形态）。
- **R7 白盒对候选「全隐语义」完成五点定向攻击后定稿**（哨兵无碰撞面、`_layout_seen` 记账-补显流无缺陷、`:514` 排他恢复兼清理、a556 target-only 原样、W32 十步全时序无第二形态；20 个既有用例零破坏）。**不变式**：任意时刻可见的 web 控件 ≤1 且必须是「激活且非阅读非休眠」的 tab；进入阅读态 tab = 全隐；退出阅读/切普通 web tab = 排他显示。

### P1'' 定稿 diff · 后端 `src/web_tabs.py`

```diff
--- a/src/web_tabs.py
+++ b/src/web_tabs.py
@@ 模块常量区（_lock 删除后、WebTabs 类定义前）
+_HIDE_ALL = "__all__"    # R6 审计 W32：全隐哨兵（切回阅读态 tab）——前端 tab id
+                         # 恒为 web:<epoch>:<n> 形态，永不与该哨兵碰撞
@@ WebTabs.show
-    def show(self, tab_id, visible, sq=0):
+    def show(self, tab_id, visible, sq=0, hide_all=False):
         if sq:
             if sq <= self._want_seq:
                 return {"ok": True}       # 乱序迟到的旧令
             self._want_seq = sq
-        self._want = (tab_id, bool(visible))
+        # R6 审计 W32：hide_all=True =「全隐」意图——哨兵写入 _want，
+        # layout 补显期与后续任何 layout 均不再按陈旧排他意图弹出
+        # 不相关控件（W32 的错 tab 盖阅读视图根因）。hide_all 时
+        # visible 参数忽略；sq 门控照常生效。
+        self._want = (_HIDE_ALL, False) if hide_all else (tab_id, bool(visible))
         if visible and tab_id not in self._ctl and tab_id in self._pending:
             # a555：create 在途（show 先于 _build 被处理）——此刻应用会把
             # 其他已显示 tab 藏掉又无新控件可显。意图已记 _want，控件建好
             # 后由 layout._apply 补显
             return {"ok": True}
@@ WebTabs._apply_visibility
         if not self._want:
             return
         tab_id, visible = self._want
+        if tab_id == _HIDE_ALL:
+            # R6 审计 W32：全隐分支——阅读态/守卫态下任何网页控件都不得
+            # 可见；幂等（重复 layout 重复全隐无害），不动 BringToFront
+            # （恢复排他显示时由 show(X,True) 统一前置）
+            for c in list(self._ctl.values()):
+                c.Visible = False
+            return
         if visible:
             for tid, c in list(self._ctl.items()):
                 c.Visible = (tid == tab_id)
@@ register：api_web_tabs 的 show 分支（A6 应用形态）
         if act == "show":
             _on = d.get("on", True)
+            _all = d.get("all", False)
             return jsonify(t.show(
                 tid,
                 _on if isinstance(_on, bool)
                 else str(_on).strip().lower() in ("true", "1", "yes", "on"),
-                _num("sq")))
+                _num("sq"),
+                _all if isinstance(_all, bool)
+                else str(_all).strip().lower() in ("true", "1", "yes", "on")))
```

> 裸基线（未应用 A6 的 d9c8886）合入时，REST 段锚点为 `bool(d.get("on", True))` / `int(d.get("sq") or 0)` 行，其余 hunk 不变。

### P1'' 定稿 diff · 前端 `web/js/web-panel.js`

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ _webCtlVisible（:279）
-function _webCtlVisible(on) {
+function _webCtlVisible(on, all) {
   const c = _webCur();
   if (!c || !c._tabId) return;
   // a556：带序号——……（原注释保留）
-  _webCtl(c, { act: 'show', on: !!on, sq: ++_webCtlSeq });
+  const d = { act: 'show', on: !!on, sq: ++_webCtlSeq };
+  if (all) d.all = true;   // R6 审计 W32：全隐语义（后端 _want=(HIDE_ALL,False)）
+  _webCtl(c, d);
   if (on && c._ctlPush) setTimeout(c._ctlPush, 30);   // 显示后重对齐
 }
@@ switchTab 包装器（:436，整体替换 P1' 的守卫行）
-      // R5 审计 W31：与 :376 浮层联动守卫对齐——阅读态不显原生控件
-      //（HWND 会盖住阅读视图且无自愈）。休眠态防御性同守：唤醒路径
-      // 经 _webNavigate 内部的 _webCtlVisible(true) 照常显出，无死端。
-      if (!c._ui.reader && !c._ui.sleeping) _webCtlVisible(true);
+      // R5 审计 W31 + R6 审计 W32 修订：阅读态切回 = 全隐（显式刷新
+      // _want，防陈旧排他意图经 layout 补显弹出他 tab 控件——W32 根因）；
+      // 唤醒失败防御态同理保持全隐（UI 停在休眠浮层，与基线同态）。
+      // 非阅读非休眠 = 排他显示（基线语义）。
+      if (!c._ui.reader && !c._ui.sleeping) _webCtlVisible(true);
+      else _webCtlVisible(false, true);
       if (c._ctlPush) setTimeout(c._ctlPush, 30);
```

> W32 十步全时序推演与 `_want=(X,True)` 四写入点穷举（确认无第二形态）见 `rounds/round-7-whitebox.md` §三。

## 记录

- R6 白盒其余结论：P1' 四条死端路径全部通过（唤醒清标志、无 URL 唤醒放行、pend_nav 解耦、`_webWake` 异常时不比基线差）；`!sleeping` 无误伤面（reader×sleeping 互斥）；阅读退出 `:514` 恢复条件正确。
- **验收口径更新（R7 黑盒）**：切回阅读态 tab 的 show 请求预期 = 基线 `show(on:true)`（W31 缺陷）→ 修订版应发**全隐请求**；桌面验证手册对应格同步更新。
- 终止规则推进：R7 = 修订定稿 + 确认轮；R7 双通道零确凿 → DONE。
