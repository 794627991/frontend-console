# 补丁 · 第 5 轮（提案，未应用）

> 生成：2026-11-13（R5 收敛判定轮收尾）。依据：`rounds/round-5-whitebox.md`（W31）+ `rounds/round-5-blackbox.md`（零确凿·黑盒收敛）。
> 本轮状态：白盒确凿序列 13→7→7→3→**1**（静态域正式收敛）；黑盒**零确凿**。R5 非零（W31 一条），按终止规则派 R6 终判轮。

---

## 一、确定性补丁

### P1'（修 W31/P2）——switchTab 包装器补阅读态守卫（一行）

`web-panel.js:436`：switchTab 包装器对网页目标无条件 `_webCtlVisible(true)`——切回**阅读态**网页 tab 时 HWND 原生控件盖住阅读视图，UI 态与实态相反且无自愈路径（纯 GUI 可达：开阅读 → 切 B → 切回 A）。对照 `:376` 浮层联动守卫 `!c._ui.reader && !c._ui.sleeping`——不对称即证明。

```diff
--- a/web/js/web-panel.js
+++ b/web/js/web-panel.js
@@ -435,3 +435,7 @@
       // 目标 tab 控件显示 + 布局对齐；其余网页 tab 控件隐藏
-      _webCtlVisible(true);
+      // R5 审计 W31：与 :376 浮层联动守卫对齐——阅读态不显原生控件
+      //（HWND 会盖住阅读视图且无自愈）。休眠态防御性同守：唤醒路径
+      // 经 _webNavigate 内部的 _webCtlVisible(true) 照常显出，无死端。
+      if (!c._ui.reader && !c._ui.sleeping) _webCtlVisible(true);
```

**无死端核验**（白盒 R5 + 主控复核）：
- 休眠 tab 切回：`:428-433` 先 `_webWake(c)` + `_webNavigate(u)`，后者内部 `_webCtlVisible(true)`（:407）照常显出控件；
- 阅读态切回：控件保持隐藏，阅读视图（DOM）正常显示；退出阅读走 `_webReaderToggle` 内部的 `_webCtlVisible(true)`（:514）恢复——两条恢复路径均在。

---

## 二、收敛结论（白盒 R5 正式宣告，主控采纳）

- **(a) 双通道已穷尽面**：web_tabs.py 全部、web-panel.js 全部、双轨历史（归属+内容+第三形态——reload 不加历史项、SPA pushState 走同 host 覆盖，无第三形态）、fetch_text 全对抗面、web-favs/web-session、CDP 链、启动/装配链、四份补丁与叠装、测试质量。
- **(b) 移交桌面验证手册**：14 项（round-4-whitebox §五 定稿）+ W31 修复回归 + B17 的「50×50」桌面后果存疑项。
- **(c) D 栈实现后必审清单**：D1''（`_epochs` 清理齐全性/reset 门控/beacon 时序）、D2（参数合并语义/9223 降级/target 映射）、D3（握手窗口期/扇出注入面/per-sid 隔离）、D8（B10 矩阵回归/a556 保持；三个坑位观察：标志消费对重定向脆弱→建议期望 URL 对账、Navigate 后 GoBack 剔除的提交时序、既有语义保持清单）、D5/D7、A 系全量回归（20+21 类用例）。

## 三、黑盒 R5 终证记录（验收快照定稿）

- 幽灵累积终证：旁路（侧栏 ✕）激活态关闭**线性累积**幽灵（实测 4 个同帧 `layout(0,0,0,0)`）；pill ✕ 正路零幽灵且 dispose 正常——N3 回归口径 4 条断言定格。
- 验收快照 5 张表（报告「验收快照（d9c8886 基线）」节）：B7 12 格矩阵 / B16 请求序列 / B17 幽灵语义 / B18 七格 / B19 各格。
- 兜底新面全干净：8KB URL、30 跳重定向环（0.13s 优雅失败）、5MB web-session（自愈剔除冗余）。
- 四轮回归终扫 12 项抽查零漂移。
- N4' 评审核验干净（分支序正确、HTTPError 优先命中）；D8 三个坑位观察已并入 (c)。

## 四、R6 终判口径

R6 = 判定轮：白盒评审 P1' + 静态复判；黑盒 W31 基线定格（切回阅读态 tab 时 `show(on:true)` 请求应发出 = 基线；P1' 应用后应消失）+ 回归抽查。**R6 双通道零确凿 → DONE**（连续一轮白+黑零确凿）。
