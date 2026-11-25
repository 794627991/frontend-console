# 内嵌浏览器（路线 A）白盒对抗审计 · 第 6 轮（终判轮）

- 基线：d9c8886 未变；输入材料：`patch-round-5.md`（P1'/D8/收敛结论）
- 方法：P1' 逐路径死端攻击（唤醒/无 URL 唤醒/pend_nav/`_webWake` 异常/`!sleeping` 误伤面/阅读退出）+ **被抑制 show 的后端 `_want` 状态追踪**（`_ctlPush` 定时器、ResizeObserver、`layout._apply` → `_apply_visibility` 链路全量复核）
- 铁律遵守：零代码修改；pytest 隔离 USERPROFILE（复跑 **20 passed**）

---

## 一、P1' 评审（W31 修复：:436 补 `!reader && !sleeping` 守卫）

### 任务点名的死端攻击——四条路径全部通过

1. **休眠 tab 切回的唤醒时序**：`:428-433` 的唤醒块先于守卫行执行——`_webWake(c)` 把 `c._ui.sleeping` 置 false **之后**才评估 `!c._ui.sleeping` → 守卫放行 → `_webCtlVisible(true)` 照发（与 `_webNavigate` 内部 :407 的那次重复，sq 单调无害）。无死端 ✓。
2. **无 URL 唤醒**（`_webNavTop` 返回空——栈空或全 about:blank）：`if (u) _webNavigate(u)` 跳过 → `_webNavigate` 内部的 :407 不执行 → **守卫行本身放行**（sleeping 已被 wake 清掉）→ 控件照常显出 ✓。P1' 的守卫恰好补上了这条基线也依赖的路径，无新增死端。
3. **pend_nav 转入**（控件已入 `_ctl`、CoreWebView2 未就绪）：show 照常生效（`_apply_visibility` 只操作 WinForms `Visible`，与初始化完成与否无关——空白直至初始化完成，与基线一致）✓。
4. **`_webWake` 抛异常时的 UI 状态**：`_webWake` 仅做标志翻转与 querySelector（现实不可抛）；即便抛出，异常发生在守卫行**之前**——基线与 P1' 版本都会跳过其后的 `_webCtlVisible(true)` → UI 停在「wrap 可见 + 休眠浮层 + 无控件」——**与基线完全相同，不更差** ✓。
5. **`!sleeping` 的误伤面**：reader 与 sleeping 互斥（休眠巡检 `c._ui.reader` 跳过）→ 守卫两条件不会同时拦截；`c._ui` 必存在（isWeb 分支的 conn 皆出自 `buildWebPanelTab`）✓。
6. **阅读态退出路径 :514**：`_webReaderToggle(false)` → `_webCtlVisible(true)` 恢复 ✓；经 `_webNavigate` 的 `skipRestore` 路径（:405）先清 `c._ui.reader` 再显——与守卫时序一致 ✓。

### W32【P1·补丁引入】P1' 静默抑制 show 留下陈旧 `_want`——切到阅读态 tab 后，任意 layout 触发把**前一个 tab 的控件**弹到前台盖住阅读视图（比 W31 更糟：显示的是错误 tab 的页面）

- 位置：patch-round-5 P1' diff（`web-panel.js:436` 守卫只做抑制、不补发 show(false)）；受害链路：`web-panel.js:437`（`setTimeout(c._ctlPush, 30)` 无条件）→ `:263-269`（push：A 的 wrap 可见 → 放行 → 发 layout）→ `src/web_tabs.py:418`（`layout._apply` **无条件**调用 `_apply_visibility`——a555 补显机制）→ `web_tabs.py:342-348`（`_want=(B,True)` 的**排他显示分支**：全部控件 `Visible = (tid == B)` + `BringToFront`）。
- 触发路径（纯 GUI，与 W31 同款两步）：网页 tab B 可见（`_want=(B,True)`）→ 切到阅读态 tab A → P1' 守卫抑制 show → `_want` **停在 (B,True)** → 30ms 后 `_ctlPush` 定时器发出 layout → `_apply_visibility` 排他分支 → **B 的控件 Visible=True + BringToFront**，A 的控件被藏 → B 的页面（HWND）盖住 A 的阅读视图。
- 必然性：除 `_ctlPush` 定时器外，A 的 wrap 从 display:none→flex 本身触发其 ResizeObserver → 同一 layout 链路 → **弹出不依赖概率**。且窗口 resize、任何存活控件的 RO 回调都会反复重现。
- 无自愈：overlay-sync 的 show 分支被 `!reader` 挡住且无纠正分支；`_want` 直到阅读退出（:514 → `_want=(A,True)`）或下一次非阅读网页切换才纠正——整个阅读会话期间 B 的控件悬浮在前。
- 与基线对比：基线（无 P1'）切回阅读 tab 时 show(A,True) 会**刷新** `_want=(A,True)` → 后续 layout 排他显示 A——是 W31 的「同 tab 页面盖阅读」；P1' 后变成「**别的 tab** 的页面盖阅读」——严格更糟。
- 特例确认：前一 tab 也是阅读态时无此弹窗（其 `_want=(B,False)` 走只藏分支）——但常见路径（前一 tab 为正常可见网页）必现。
- **修复方向（一行）**：抑制的同时显式补发——`if (!c._ui.reader && !c._ui.sleeping) _webCtlVisible(true); else _webCtlVisible(false);` → `_want=(A,False)` → `_apply_visibility` 走只藏分支（B 保持现有 Visible=False）→ 无弹窗且 `_want` 与实态一致；与阅读入口 `_webReaderToggle(true)` 的 `_webCtlVisible(false)` 语义对齐。
- **验收口径更新**（供手册/黑盒）：P1' 原案下「切回阅读态 tab 应无 show 请求」不成立——修复版应为「切回阅读态 tab 发出 `show(on:false)`（而非 on:true），且其后任意 resize/layout 不产生针对他 tab 的排他显示」。

---

## 二、终判

**本轮非零确凿（W32，P1，补丁引入）。静态白盒终判暂不宣告 DONE。**

- **基线静态收敛维持成立**：W32 是 patch-round-5 P1' 引入的回归，不是新的基线面——R5 对基线的收敛判定（静态域穷尽，最后一块为 W31）不受影响；R1–R5 基线确凿 31 条（W1–W31）+ 黑盒 B1–B19 终态不变。
- **补丁链状态**：patch-round-1..4 评审通过；patch-round-5 仅 P1' 需一行修订（抑制 → 显式 `show(false)`），其余（D8 设计、收敛结论 (a)(b)(c)）采纳。
- **收敛路径**：P1' 按 W32 修订后，该修复的静态面即闭合（守卫 + `_want` 刷新两半齐全）；按终止规则（连续一轮白+黑零确凿 → DONE），R7 对修订版 P1' 做确认轮即可正式宣告「静态双通道收敛」——预计零确凿。
- B10/B16/B17/B18/B19 验收快照不受影响；仅阅读态切回格的断言按上文验收口径更新（on:false 而非无请求）。

---

## 三、已排查未发现问题（防 R7 重复）

1. 唤醒路径时序（wake 先清标志 → 守卫放行；与 :407 重复 show 无害）。
2. 无 URL 唤醒（守卫自行放行，无死端）。
3. pend_nav 转入（Visible 与初始化解耦，基线一致）。
4. `_webWake` 异常场景（与基线逐字节相同，不更差）。
5. `!sleeping` 误伤面（reader×sleeping 互斥；`c._ui` 必存在）。
6. 阅读退出 :514 与 `_webNavigate` skipRestore 路径（reader 先清后显，守卫时序一致）。
7. 前一 tab 亦为阅读态的特例（`_want=(B,False)` 只藏分支，无弹窗——弹窗仅限「前一 tab 正常可见」的常见路径）。
8. 基线测试隔离复跑：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**。
9. 叠装一致性：P1' 与 A8'/A10''/N3/N5 的行段无重叠；W32 修订（else 分支）不与任何在途补丁冲突。
