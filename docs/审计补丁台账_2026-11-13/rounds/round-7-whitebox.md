# 内嵌浏览器（路线 A）白盒对抗审计 · 第 7 轮（修订定稿 + 确认轮）

- 基线：d9c8886 未变；输入材料：`patch-round-6.md`（W32 分析与「全隐」候选方案）
- 方法：候选方案五点定向攻击（哨兵表达/_layout_seen×_pending 交互/退出恢复/a556 保护/W32 全时序）+ 修订版 P1'' 全量对抗自证（20 项推演）+ 第二形态穷举（`_want=(X,True)` 全部写入点清点）
- 铁律遵守：零代码修改；pytest 隔离 USERPROFILE（复跑 **20 passed**）

---

## 一、候选方案攻击与完善（任务点①—⑤）

### ① 「`__all__` 哨兵 vs 其他表达」——哨兵方案成立，四处加固

- **碰撞面**：前端 tab id 恒为 `web:<epoch>:<n>` / `web-<epoch>-<n>` 形态，永不等于 `__all__`；REST 直调 `tab="__all__"+all=false` → `_ctl.get` 落空 → 无操作；`tab="__all__"+all=true` 即本意图。无碰撞 ✓。
- **替代方案否决理由**：`_want=(None,False)` 语义歧义（None 与「无意图」的 `_want=None` 仅差一个元组壳，`if not self._want` 判空逻辑易混）；独立 `_want_all` 布尔字段 = 显示意图双源，`_apply_visibility`/reset/快照全要加分支——状态面更大。**哨兵进既有二元组是最小态** ✓。
- **四处加固**：(a) 哨兵提为模块常量 `_HIDE_ALL = "__all__"`（show 写入与 `_apply_visibility` 判定两处共用，防手抄不一致）；(b) 参数命名 `hide_all`（避免遮蔽内建 `all`）；(c) hide_all=True 时**忽略 visible 参数**（语义单源，防 `all:true+on:true` 组合歧义）；(d) REST 的 `all` 字段按 A6 同款布尔穿透解析（`"false"` 字符串不得判真）。

### ② 全隐分支 × `_layout_seen`/`_pending` —— 无交互缺陷

- **首份 layout 前**：`show._apply` 的 `_layout_seen` 门照常拦截 → `_want=(HIDE_ALL,False)` 记账不应用；控件此刻本就 `Visible=False`（`_build` 创建默认）→ 语义一致；layout 到达后 `layout._apply` 补应用全隐——**不会弹默认 rect**（a555 哨兵流程原样兼容）✓。
- **`_pending`（create 在途）**：全隐分支只遍历 `_ctl`——在途控件不在册、建成即默认不可见 ✓；`show` 的在途守卫 `if visible and …` 在 hide_all（visible 恒 False 语义）下不触发 → `_apply` 正常排队 ✓。
- **`show(A,True)` 补显流与全隐的先后**：`_want` 单槽后写者胜 + sq 门控——全隐(sq=n) 与补显 show(sq>n) 乱序时 sq 正确裁决 ✓。

### ③ 退出阅读态 :514 的排他显示恢复 —— 复核通过，且顺带清理

`_webCtlVisible(true)` → `_want=(A,True)` → 排他分支：A `Visible=True+BringToFront`、**其余全部 `Visible=False`**——从全隐态恢复时该分支同时把任何存活可见控件一并压下，恢复即清理 ✓；`_layout_seen=False` 场景走 a555 记账-补显流 ✓；`skipRestore` 路径（`_webNavigate` :405 先清 reader 再 :407 显）与守卫时序一致 ✓。

### ④ a556 target-only 回归保护 —— 成立

`_webSleep` 的 `show(bg,false)` 不带 `all` 字段 → 后端 `hide_all` 缺省 False → target-only 原样 ✓；`_webCtlVisible` 其余全部调用点（:375/:377/:407/:445/:514/:522）均不传 all → 行为零变化 ✓；既有用例 `test_show_hide_one_semantics`（a556 语义钉）与 `test_show_seq_drops_stale` 不受签名影响 ✓。全隐的唯一发出点 = P1'' 守卫的 else 分支（切回阅读态/唤醒失败防御态）。

### ⑤ W32 场景全时序推演（修订版）—— 无第二形态，见第三节表

---

## 二、修订版 P1'' 完整 diff（定稿）

> 锚点：patch-round-1..5 全应用后的形态（REST show 分支为 A6 版）。若在未应用 A6 的 d9c8886 裸基线直接合入，REST 段锚点为 `bool(d.get("on", True))` / `int(d.get("sq") or 0)` 行，其余 hunk 不变。P1'' 整体**取代** P1'（patch-round-5 的 :436 守卫行由本 diff 的 web-panel.js 第 2 块替换）。

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

---

## 三、W32 场景全时序推演（修订版 P1''）

| 步骤 | 动作 | `_want` | 后端控件态 | 判定 |
|---|---|---|---|---|
| 0 | B 可见（用户在 B） | `(B,True)` | B 可见+前置 | 基线 |
| 1 | 切到阅读态 A | `(HIDE_ALL,False)` | 全部 Visible=False | **W32 根因消除**（P1' 版此处停留 `(B,True)`） |
| 2 | +30ms `_ctlPush` → layout | `(HIDE_ALL,False)` | 全隐（幂等） | 无弹出 ✓ |
| 3 | resize / RO / 任意后续 layout | 同上 | 全隐（幂等） | 无弹出 ✓（W32 的必然弹出链已断） |
| 4 | 浮层开 → sync `show(A,false)`（target-only） | `(A,False)` | 只藏 A（本就隐藏） | hide-only 分支永不清他控件 → 无弹窗形态 ✓ |
| 5 | 浮层关 → sync show 分支被 `!reader` 抑制 | `(A,False)` | 不变 | 全隐实质保持 ✓ |
| 6 | 隐藏 tab D 休眠 `show(D,false)` | `(D,False)` | 只藏 D | a556 语义原样 ✓ |
| 7 | 退出阅读（:514） | `(A,True)` | A 可见+前置、余全藏 | 排他恢复即清理 ✓ |
| 8 | 切回普通网页 tab C | `(C,True)` | C 可见、A/B 藏 | 基线 ✓ |
| 9 | A(reader) → B(reader) | `(HIDE_ALL,False)` | 全隐（幂等） | 连续阅读态切换无残留 ✓ |
| 10 | 唤醒路径（sleeping→wake→`_webNavigate`:407） | `(A,True)` | A 显 | 守卫首分支放行，无死端 ✓ |

**第二形态穷举**（`_want=(X,True)` 全部写入点清点）：`:377` overlay-sync（`!reader && !sleeping` 守卫）、`:407 _webNavigate`（:405 先清 reader）、`:514` 阅读退出（用户意图）、`:436` 守卫首分支（P1'' 守卫）——阅读态存续期间不存在任何 stale-(X,True) 写入路径；`_want=(HIDE_ALL,False)` 的消费（全隐分支）幂等且不设 Visible=True。**确认无第二形态**。

---

## 四、确认判定

**零确凿。修订版 P1'' 定稿，R7 收敛成立。**

- 主控对 R6 一行修的否决**正确**：`show(A,false)` target-only 在多 tab 场景漏藏 B（基线里 B 的隐藏正是靠 `show(A,true)` 的排他分支执行）——全隐哨兵是完整修复。
- 修订版经 20 项对抗推演（第一节①—⑤ + 第三节时序表 + 第二形态穷举）零缺陷；20 个既有用例零破坏（`show` 加参带默认值、a556 钉测原样通过）。
- 按终止规则：**R7 双通道零确凿 → DONE，静态双通道审计正式收敛**。终态 = 基线确凿 W1–W31 + 黑盒 B1–B19 + 补丁链 patch-round-1..6（P1'' 取代 P1'）+ 本轮 P1'' 定稿。
- 移交项不变：桌面验证手册（round-4 §五 14 项，其中「阅读态切回」格验收口径 = 应发 `show(on:false)` **全隐请求**而非 on:true——patch-round-6 §记录已更新）；D 栈实现评审清单（round-5 §三(c)，P1'' 的 `_HIDE_ALL`/`hide_all` 并入 D1'' 批次同审）。

## 五、建议新增测试（增量，承接 21 类）

22. `show(t,False,hide_all=True)` → 全部控件 `Visible=False`；随后 `show(A,True)` → 排他恢复。
23. hide_all 于首份 layout 前 → 记账不应用；layout 到达 → 应用全隐（无默认 rect 弹出）。
24. hide_all 的 sq 门控（迟到的全隐被丢弃）。
25. a556 回归补断言：休眠 `show(bg,false)` 请求体**不含** `all` 字段（防将来误改）。
26. 前端（若引入 JS 测试）：切回阅读态 tab → 捕获 `show(on:false, all:true)`；切回普通 tab → `show(on:true)` 无 all。

## 六、已排查未发现问题（防 R8 重复）

1. 哨兵碰撞面（前端 id 形态/REST 直调两向）；None/独立布尔字段的替代方案否决依据。
2. `_layout_seen` 前的全隐记账-补显流；`_pending` 在途控件与全隐遍历的解耦。
3. 退出阅读 :514 排他恢复兼清理；`skipRestore` 路径时序。
4. a556 target-only 回归（休眠路径无 all 字段、既有两用例零改动通过）。
5. W32 十步全时序 + `_want=(X,True)` 四写入点穷举——无第二形态。
6. `hide_all`+`on:true` 组合歧义（visible 忽略语义）；REST `all` 布尔穿透；`_ctlPush` 在 on=false 时不发（RO/resize 兜底）。
7. 浮层 sync 的 target-only show 在全隐态下的 `_want` 漂移（(HIDE_ALL)→(A,False)）——后果等价（hide-only 分支永不清他控件）、无弹窗形态。
8. `show` 签名加参对既有 20 用例与 REST 直调方的向后兼容。
9. 基线测试隔离复跑：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**；工作树 clean（HEAD d9c8886）。
