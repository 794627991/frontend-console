# ZCode v3.18 摘要组移植探索与回退备档（v4.1.1，未入库）

> 会话 sess_c88f8f16（2026-11-16/17）。成果已按用户要求**整体回退**；本文与
> `patches/fc-v4.1.1-harness-summary-group.patch` 是唯一存档——重放 patch 即恢复全部实现。
> 本文记录：ZCode 侧解剖 → fc 移植设计 → 上线后叠行事故的根因链 → 免 F5 交付问题 →
> 桩页验证法 → 回退记录。四条教训见 §8。

## 1. 目标

harness 聊天流参考 ZCode 桌面端 v3.18 的「抽屉收缩」效果：两段 AI 正文之间的
**全部工具调用 + 思考过程**折叠成一个统计胶囊（收起只显一行
「已查阅 2 项，已执行 1 命令」，点击展开逐条回看）。此前 fc 的形态是思考段与
工具行平铺时间线，长回合（实测 36 工具）占据大量竖向空间。

前置：本地 ZCode 开源仓库已同步到 v3.18.2（`fec97590`，含 3.18 抽屉效果；
v3.14.3 时代副本无此功能，用户指认 3.18 才出）。

## 2. ZCode 侧解剖（对照源码）

实现就两个文件，职责切干净：

**① 纯函数层 `packages/ui/src/v4/conversationAssistantWorkItems.ts`**
- `groupConsecutiveAssistantSummaries`：遍历回合内行，**思考（reasoning）行 +
  可归类工具**连续出现即捆进同组；**正文、Agent/Subagent 卡、workflow 工具、
  未归类工具、pendingApproval 工具是断组边界**（注释原文：「正文、Workflow、
  Subagent 与未归类工具是边界；不重新拼接真实工具关系」）。
- `getAssistantSummaryToolCategory`：按工具 family 归类——
  `file-read/search/web-fetch/explore` → explore；`shell/node-repl/CUA` → run；
  `file-write` → change；`ListSessions` 族 → session（统计并入 run）。
  family 由 `lib/toolIdentity.ts` 的正则表判定。
- `formatAssistantSummaryStatistics`：按类别计数拼文案，i18n 键
  `chat.summaryGroup.*`（zh-CN：「查阅 {count} 项」「已查阅 {count} 项」
  「执行 {count} 命令」「已执行 {count} 命令」「修改 {count} 文件」），
  change 类按**文件路径词法去重**计数（`summaryFilePath` 归一斜杠/盘符），
  分隔符「，」；全组无工具时兜底「思考」。**只计工具调用数，不计返回目标数**。
- `getAssistantSummaryIconItem`：代表图标优先级 CUA=0 > node-repl=1 > change=2
  > run=3 > 其余=4，缺省 BrainIcon。

**② 组件层 `packages/ui/src/ToolCallBlocks/ToolSummaryRow.tsx` 的
`ConsecutiveSummaryGroup`**
- `useState(false)` 默认收起、状态不持久化；**组内 <2 条直接渲染原行不包壳**。
- `groupRunning = boundary.taskRunning && boundary.tailRowId === lastRowId`：
  只有「整轮尾组 + 任务运行中」算运行态——组后出现任何边界行立即定格。
- 运行态收起行显示**当前活动条目的滚播**（`QueuedSummaryContent`：300ms 翻转 +
  500ms 保持，积压 >2 条跳最新）；工具间隙显示统计文案 + `animated-gradient-text`
  扫光；计数随流式投影实时重算。
- 展开区：max-h 约 16 行可滚（`useBottomFollowingScroll` 跟底 + 上下渐隐 mask）、
  统一左导线（`before:border-l`）、**每条直接复用原工具 renderer**（不复制文案
  与状态规则——注释原文：「分组只持有展开状态；完整摘要继续由原始行 renderer
  提供」）。
- 轮头「已工作 N 分 N 秒」来自 `turnHeader.activeMs`（`lib/workDuration.ts`，
  最多两段单位）。packages/web（分享落地页）经 workspace 依赖复用同一套纯函数
  与组件，无第二份实现——分组逻辑刻意做成纯函数以被 web-share 闭包复用。

## 3. fc 移植设计（v4.1.1）

fc 已有 v3.2 的「查阅聚组」（`.h-tl-grp`，只聚只读工具）与回合级「已工作 X ›」
自动闭合；v4.1.1 把聚组升级为 ZCode 式统一摘要组。数据通路确认：
live（`renderToolUse`）/回放（`renderHistTool`）/孤儿结果/识图卡全走
`_tlPlace` 单一咽喉，v4 桥（v4bridge）与 SSE 双轨都汇入——改一处全覆盖。

| 文件 | 改动 |
| --- | --- |
| tools.js | 新增 `_hgSumCategory`（分类，复用既有 `_hgIsExplore` 作 explore 全集）/`_hgSumStatsTxt`/`_hgSumIcon`/`_hgSumPaint`（尾组+busy=活字，否则定格）/`_tlSumCreate`/`_tlSumFlush`（单成员解包+已前缀+自动收）；`_tlPlace` 重写（组员入组、其余断组） |
| hist.js | `startThinking` 思考段入组体（跨思考累积沿用 v3.2.13 定调）；思考滚播行同步组头活字；收段让位 |
| groups.js | 断组点接线（grpFinalize/renderUser/renderAsst/drawerAppend） |
| relay.js | sysnote/raw/exit/renew/audit 行断组（三处 `_tlSumFlush`） |
| main.js | 组头点击委托 |
| base.js/histcache.js/subpane.js | 注释指向更新；subpane（子代理窗格）保持旧聚组不动 |

移植拍板三条：① 主链桶汇总「· N 搜索 · M 文件」退役为 ZCode 同款「已查阅 N 项」
（窗格不动）；② **单成员组解包**（对照 ZCode items<2 不包壳——孤思考段/孤工具
行回时间线，不留空壳胶囊）；③ **执行/修改类绝不折叠重复调用**（每次运行都是真
动作，对照 ZCode「统计工具调用」口径），只有查阅类沿用 v3.2.13 同目标去重。

## 4. 事故：大胶囊叠行残影（用户实锤「多点了几下，就这样了」）

上线后真实大回合（36 工具，胶囊 21+1 项）展开滚动出现**叠行/半行**——同一条
Grep 行在两个纵向位置各画半截。截图指纹：**叠行的全是长 pattern 折行行
（真实高度≠28px），短行（Read 短路径/Bash/思考段头）全干净**。

根因链（桩页探针实锤，非猜测）：

1. a120Q 性能机制给 `.hg-flow .h-tl .h-tool` 挂了行级
   `content-visibility: auto; contain-intrinsic-size: auto 28px`——视口外行按
   28px 占位参与布局；
2. 胶囊体 `.h-tl-grp-body` 是 42vh 内滚容器（a270 老规则）——行在**内滚**里
   滚进滚出时「28px 占位 ↔ 真实高度」反复物化，探针实测单行 **30↔56px 振荡**；
3. `.hg-flow { contain: layout }` 祖先的合成层失效缺口 → 旧帧不重绘 →
   **旧帧残影叠印**在新布局位置上。

旧「查阅聚组」同样内滚+CV 但只有 3-5 行轻内容未暴露；新胶囊 21+ 行一滚动即炸。
「多点几下」= 反复开合+滚动反复穿越物化边界。

修复（v4.1.1R）：开启的胶囊子树豁免行级 CV
（`.h-tl-grp.open > .h-tl-grp-body .h-tool { content-visibility: visible }`，
成员体是懒壳空体，物化代价≈行头 30px/条，36 行胶囊毫秒级）；
组开合批量懒填只保工具行（思考段体是几十 KB markdown，随组开合全量渲染/丢弃
是纯抖动源——思考段保持自身段头点击单独懒填）。

## 5. 免 F5 交付问题（R2，CSS 修复第一次「没修好」的真因）

CSS 修复后用户复测仍叠行。定位：`server.py` `__HG_DBGF__` 注释原文——
**「正式版无 F5 能力」**。JS 走注入通道（PEP 768 remote_exec 链路）送达活页，
CSS 改动没有通道，活页样式表永远是旧的。截图指纹复现即是铁证：若新 CSS 已
生效，占位振荡物理上不可能存在。

R2 修法：豁免**下沉 JS 层**——`_tlPlace` 摆行时
`row.style.contentVisibility = 'visible'`（行内联恒赢样式表，与 CSS 规则互为
冗余双保险）+ tools.js 尾部**注入扫尾**（`querySelectorAll('.h-tl-grp-body
.h-tool')` 就地补内联——正在开着的坏胶囊下一次注入触发时原地自愈，无需刷新；
冷启动 flow 为空零开销）。

## 6. 验证方法：桩页法（可复用）

免后端复现回放/实况两态：拷 `harness/{base,tools,groups,hist,relay}.js` +
`icons.js` + `style.css` 到临时目录，合成转写（role 行）走真实 `renderHistLine`，
配最小桩：`esc/renderMd/mdBubble/plainBubble`、`_hgDispatch`（对照 store.js
真实 handler 语义）、`_hgToolBadges/_toolInputBodyHtml`（真身在 reducer.js/
主应用侧）、`_HG.histAll`（懒填走本地账）。探针三项：
①行高数组滚动前后对比（振荡检测）；②`getComputedStyle().contentVisibility`
（豁免生效）；③剥内联→跑扫尾→恢复（注入自愈路径）。

结论数据：修复前滚动三轮行高 30↔34 振荡；修复后**完全恒定**；
`inlineOK/compOK/healedBySweep` 全 true；42vh 内滚与左导线正常。

## 7. 回退记录（2026-11-17，用户令「patch 备存后全部回退」）

- harness 8 文件：逐 hunk 核对 20 个 hunk 全属本会话后 `git checkout` 整体回退。
- style.css 混合区：按 `v4.1.1` 标记过滤只摘本会话 hunk（当时 style.css diff
  共 7 hunk，其余 6 个属 a595 批/并行会话——`--fs-*` 字号变量与五片侧栏/
  窗体相关改动，原样未动）。
- 回退后验证：`git apply --check` 对回退树**通过**（patch 可随时重放）；
  `v4.1.1`/`_tlSumFlush`/`_hgSum` 全仓零残留；`node --check` 过。

## 8. 经验教训

1. **内滚容器里禁放 CV 占位行**——`content-visibility:auto` 的占位估高在
   内滚里反复物化=布局振荡，叠 `contain:layout` 祖先=旧帧残影。同类需求应
   豁免子树 CV 或不做内滚。
2. **CSS 改动必须 JS 层随行交付**——本应用正式版页面无 F5，注入通道只到 JS；
   纯 CSS 修复对活页等于没修。关键视觉不变量（如 CV 豁免）应内联落行。
3. **style.css 是并行会话热区**——本会话期间被外部改两次（行号漂移 29→43 行），
   编辑前必须重新 grep 定位；出 patch 用标记过滤 hunk 体时注意 git 文件头
   （diff/index/---/+++）只随**首个 hunk**出现，过滤掉首 hunk 会连头一起丢。
4. **桩页法是 harness 渲染改动的标准验证**——免后端、可合成任意回合形态、
   探针可断言 DOM/CSSOM 事实，比「刷新肉眼看」强一个量级。

## 9. 完整 patch（重放：仓库根 `git apply <patch>`）

```diff
# fc v4.1.1 harness 统一摘要组（ZCode v3.18 ConsecutiveSummaryGroup 移植）
# 会话: sess_c88f8f16 (2026-11-16/17)  状态: 已按用户要求整体回退，本 patch 备存
# 内容: 8 个 harness JS 文件全量 diff + style.css 中仅含 v4.1.1 标记的本会话 hunk
#       （a595 资源批/并行会话的改动不在本 patch 内）
# 重放: git apply D:/AI_PROJECT/patches/fc-v4.1.1-harness-summary-group.patch （仓库根执行）
# 根因备忘: 胶囊体 42vh 内滚 × a120Q 行级 content-visibility:auto 28px 占位 = 振荡残影;
#          正式版页面无 F5, CSS 改动到不了活页 (JS 注入通道先行)
diff --git a/web/js/harness/base.js b/web/js/harness/base.js
index 0c1f98a7..d6b2ae46 100644
--- a/web/js/harness/base.js
+++ b/web/js/harness/base.js
@@ -241,7 +241,7 @@ const _HG = {
                         // busy 保持工作中（中间 result 不落 busy），turn_complete 清
   holdRes: null,        // v3.5.130：hold 期中间 result 帧存档（真收尾 turn_complete
                         // 补收尾序列用：冻结工时/中断标记/ctx 环数据）
-  histBuilding: false,  // v3.2.13：原子渲染（游离缓冲）进行中——isConnected 判据的缓冲期豁免（grpEnsure/_tlPlace/_tlExpFlush）
+  histBuilding: false,  // v3.2.13：原子渲染（游离缓冲）进行中——isConnected 判据的缓冲期豁免（grpEnsure/_tlPlace/_tlSumFlush）
   activity: null,       // 活动指示 {start, verbTimer, tickTimer}
   actStart: 0,
   echoFast: null,       // 已退役（纯 ZCode 式无乐观渲染）——字段保留防旧快照读取炸
diff --git a/web/js/harness/groups.js b/web/js/harness/groups.js
index 30af146f..b7d7db2a 100644
--- a/web/js/harness/groups.js
+++ b/web/js/harness/groups.js
@@ -369,10 +369,10 @@
     phRemove(g);
     opt = opt || {};
     // v3.2R1(P0 审计)：回放态判据（opt.hist 或重建期 openState 在场）前置——
-    // _tlExpFlush 与工时分级共用；尾组定稿发生在 _histRender 的 finally 之后
+    // _tlSumFlush 与工时分级共用；尾组定稿发生在 _histRender 的 finally 之后
     // （openState 已清空），必须靠 hist:true 显式传递才不丢回放语义
     const _hist = opt.hist === true || !!_HG.openState;
-    _tlExpFlush(_hist);                   // v3.2：定稿先冲查阅聚组（头部定格汇总+自动收）
+    _tlSumFlush(_hist);                   // v3.2→v4.1.1：定稿先冲摘要组（单成员解包+「已…」统计+自动收）
     if (g.headTimer) {
       clearInterval(g.headTimer);
       // v3.2R1(P2)：同步从 turnTicks 摘除——只清 interval 不摘 id，数组随
@@ -607,6 +607,9 @@
   }
   function drawerAppend(el, kind) {
     const g = grpEnsure(true);
+    // v4.1.1：非思考行落组线=断组边界（后台任务卡/旧快照回落行）——对照 ZCode
+    // 未归类工具断组口径；think 分支不 flush（旧结构思考抽屉，组语义不变）
+    if (kind !== 'think') _tlSumFlush(!!_HG.openState);
     if (kind === 'think') g.think.body.appendChild(el);
     else if (g.tl) g.tl.appendChild(el);            // v3.2：工具行进内联时间线
     else if (g.exec) g.exec.body.appendChild(el);   // 旧快照组：回落旧执行抽屉
@@ -757,9 +760,9 @@
     // ——超出的从 DOM 移除（转写仍完整，只读模式拉全量可看）。每次新回合
     // 边界（用户发消息）时裁剪一次
     _trimOldTurns();
-    _tlExpFlush(!!_HG.openState);   // v3.2.13：回合边界定稿上回合查阅组——思考不再
-                                    // 断组后，开放组的头部定格必须由用户行兜底
-                                    // （头部定格为桶汇总 + 回放态自动收起）
+    _tlSumFlush(!!_HG.openState);   // v3.2.13→v4.1.1：回合边界定稿上回合摘要组——
+                                    // 思考不再断组后，开放组的定格必须由用户行兜底
+                                    // （单成员解包+已前缀统计+回放态自动收起）
     _HG.asstText = false;                     // 本轮 AI 尚未输出文本（占位/组头判据）
     const d = document.createElement('div');
     d.className = 'h-msg user';
@@ -828,7 +831,7 @@
     // v2.43：子代理文本不再走本函数——改入子代理段（_subText），主 flow 的
     // 灰色 sub 行与 isSub/subId 参数一并退役（归属标识上移到段头）。
     if (!text || !String(text).trim()) return;
-    _tlExpFlush(!!_HG.openState);        // v3.2：正文打断查阅聚组（回放态必收）
+    _tlSumFlush(!!_HG.openState);        // v3.2→v4.1.1：正文打断摘要组（ZCode 正文=断组边界；回放态必收）
     // v3.2.3（用户实测定调）：**一回合一组，不再按正文切组**。v2.18.1 的切组
     // （正文后再出思考/工具就定稿开新组）把一条用户消息拆成 N 条「已工作」
     // 行分段计时（用户实锤 4 连头：「应该全部整合在一起，统一在一起计时」）
diff --git a/web/js/harness/hist.js b/web/js/harness/hist.js
index a9612fbd..cb97a838 100644
--- a/web/js/harness/hist.js
+++ b/web/js/harness/hist.js
@@ -123,7 +123,7 @@
         && (l.files || []).length > 0;
       if (!String(l.text || '').trim() && _tmpEcho) {
         // 回显行不画，但组管线边界语义保留（上一组定稿照走）
-        endThinking(); closeRun(); _tlExpFlush(!!_HG.openState);
+        endThinking(); closeRun(); _tlSumFlush(!!_HG.openState);
         _HG.asstText = false;
       } else {
         const _fall = (l.files || []).concat(l.images || []);   // 407：兼容 live 入账行的 images 字段（双保险）
@@ -386,9 +386,18 @@
       // v2.21：段尾右下角收起钮——长思考读到尾顺手收，不用滚回顶部点头
       `<i class="h-think-seg-fold" title="收起本段">收起 ⌃</i>`;
     if (_toTl) {
-      g.tl.appendChild(seg);
-    if (!hist) seg.classList.add('hg-enter');   // 动画批C：live 思考段淡入                 // v3.2.4：时间线行——与工具行同序
+      // v4.1.1：思考段入摘要组（ZCode reasoning 行=ConsecutiveSummaryGroup
+      // 组员；跨思考累积沿用 v3.2.13 定调）——有开放组直接入体，无则开新组
+      //（纯思考回合定稿时单成员解包回裸行，不留空壳胶囊）
+      if (!g.exp || (!g.exp.el.isConnected && !_HG.histBuilding)) g.exp = _tlSumCreate(g);
+      const _sb = g.exp.el.querySelector('.h-tl-grp-body');
+      if (_sb) _sb.appendChild(seg); else g.tl.appendChild(seg);
+      if (!hist) seg.classList.add('hg-enter');   // 动画批C：live 思考段淡入
       g.tl.style.display = '';
+      // 组头活字（ZCode 运行态收起行显示活动条目对位）；滚播行到达时由
+      // _hgThinkShowLine 同步覆盖；回放态 paint 直接落定稿统计
+      g.exp.liveTxt = '思考中…';
+      _hgSumPaint(g.exp);
     } else {
       g.think.body.appendChild(seg);
     }
@@ -457,6 +466,13 @@
     sp.textContent = line;
     prev.appendChild(sp);
     requestAnimationFrame(() => { prev.scrollLeft = prev.scrollWidth; });   // 流水推尾
+    // v4.1.1：段在摘要组内——滚播行同步组头活字（ZCode QueuedSummaryContent
+    // 收起行滚播对位：组收起时思考流仍在胶囊头逐行可见）
+    const _tq = _HG.think;
+    if (_tq && _tq.grp && _tq.grp.exp && _tq.grp.exp.el && _tq.grp.exp.el.contains(seg)) {
+      _tq.grp.exp.liveTxt = String(line).slice(0, 60);
+      _hgSumPaint(_tq.grp.exp);
+    }
   }
   function _hgThinkPlay(seg, ls) {
     const q = _HG.thinkQ;
@@ -514,6 +530,11 @@
   function endThinking(hist) {
     const t = _HG.think;
     if (!t) return;
+    // v4.1.1：段在摘要组内——活字让位（工具/正文间隙=组头统计+脉动）
+    if (t.grp && t.grp.exp && t.grp.exp.el && t.grp.exp.el.contains(t.seg)) {
+      t.grp.exp.liveTxt = null;
+      _hgSumPaint(t.grp.exp);
+    }
     _HG.think = null;
     const seg = t.seg;
     // 思考流③（ZCode 完成态）：摘要视口清空——:empty 隐藏后时长回贴
diff --git a/web/js/harness/histcache.js b/web/js/harness/histcache.js
index 0df94335..369fb232 100644
--- a/web/js/harness/histcache.js
+++ b/web/js/harness/histcache.js
@@ -134,7 +134,7 @@
     // isConnected 快路径恒 false → 每行都重认回新 wrapper → g.exp 丢失 →
     // 每个 explore 工具各开一个单子行查阅组（碎片墙）。histBuilding 让
     // 连接性判据在缓冲期视缓冲内元素为「在场」（grpEnsure/_tlPlace/
-    // _tlExpFlush 三处同判）
+    // _tlSumFlush 三处同判）
     _HG.histBuilding = true;
     // v3.5.196：不再预清 flow——buf 渲染期旧 DOM 保留在屏（消除白屏），
     // replaceChildren 原子换入即整替（预清与换入语义重复且制造空窗）
diff --git a/web/js/harness/main.js b/web/js/harness/main.js
index 4f7165a2..442e0c17 100644
--- a/web/js/harness/main.js
+++ b/web/js/harness/main.js
@@ -596,6 +596,10 @@ function buildClaudeHarnessTab(opts = {}) {
         const opening = !grpEl.classList.contains('open');
         grpEl.classList.toggle('open');
         grpEl.dataset.userToggled = '1';
+        // v4.1.1R（用户实锤「多点几下叠行+卡」）：批量懒填只保工具行——思考段
+        // 体是整段 markdown（几分钟的长思考≈几十 KB），随组开合全量渲染/丢弃
+        // 是纯抖动源；思考段保持自身段头点击单独懒填（既有 .h-think-seg-head
+        // 分支），开组只填工具行体（a262 原语义）
         if (opening) grpEl.querySelectorAll('.h-tool').forEach(_histLazyFill);
         else grpEl.querySelectorAll('.h-tool').forEach(_histLazyDrop);
       }
diff --git a/web/js/harness/relay.js b/web/js/harness/relay.js
index f7e92185..5c7a3d34 100644
--- a/web/js/harness/relay.js
+++ b/web/js/harness/relay.js
@@ -29,7 +29,7 @@
       //（摘要只在 title），同组第二条会被 24 字前缀锚整行吞掉（含全文 title）
       if (fp && g.root.dataset.lastSys === fp && !d.classList.contains('h-sysnote')) return false;
       g.root.dataset.lastSys = fp;
-      _tlExpFlush(!!_HG.openState);
+      _tlSumFlush(!!_HG.openState);
       // v3.4.80（复核 P1）：空组的 tl 是内联 display:none（grpFromDom 对
       // children=0 落的）——append 后不翻转则行困在里面，点开折叠体依旧
       // 空壳（头「已停止」但看不见中断行）
@@ -80,7 +80,7 @@
     // 即将被 replaceChildren 丢弃的旧 DOM，append 进去等于丢失。只认已连接。
     const g = (_HG.grp && _HG.grp.root && _HG.grp.root.isConnected) ? _HG.grp : null;
     if (g && g.tl) {
-      _tlExpFlush(!!_HG.openState);
+      _tlSumFlush(!!_HG.openState);
       // 同上：空组/纯思考组的 tl 是内联 display:none——直接 append 会困在
       // 不可见容器里（旧 addRow 恒可见）。同 _sysRowIntoGroup 的翻显处理。
       if (g.tl.style.display === 'none') g.tl.style.display = '';
@@ -109,7 +109,7 @@
     const g = (_HG.grp && _HG.grp.root
                && (_HG.grp.root.isConnected || _HG.histBuilding)) ? _HG.grp : null;
     if (g && g.tl) {
-      _tlExpFlush(!!_HG.openState);
+      _tlSumFlush(!!_HG.openState);
       g.tl.appendChild(d);
     } else {
       // a147（深攻 P2）：组外窗口（机器续接的 finalize→reopen 间隙）曾落
diff --git a/web/js/harness/subpane.js b/web/js/harness/subpane.js
index 4b0c39bc..70a3d8fe 100644
--- a/web/js/harness/subpane.js
+++ b/web/js/harness/subpane.js
@@ -652,7 +652,7 @@
       t.tl.appendChild(row);
     }
   }
-  // 查阅组断组：头部定格桶汇总；未被动过则收起（主链 _tlExpFlush 同语义）
+  // 查阅组断组：头部定格桶汇总；未被动过则收起（主链 _tlSumFlush 同语义，v4.1.1）
   function _subTlExpBreak(t) {
     const e = t && t.exp;
     if (!e) { if (t) t.exp = null; return; }
diff --git a/web/js/harness/tools.js b/web/js/harness/tools.js
index c2d8dd53..63706609 100644
--- a/web/js/harness/tools.js
+++ b/web/js/harness/tools.js
@@ -355,6 +355,13 @@
     if (n === 'WebFetch') return '抓取 ' + String((input || {}).url || '').slice(0, 30);
     if (_HG_EXP_MCP_RE.test(n))
       return '探索 ' + String((input || {}).query || (input || {}).prompt || '').slice(0, 30);
+    // v4.1.1：修改类活字（统一摘要组组员扩展——窗格旧聚组不含写类，分支不达无碍）
+    if (n === 'Edit' || n === 'MultiEdit')
+      return '编辑 ' + String((input || {}).file_path || '').split(/[\\/]/).pop();
+    if (n === 'Write')
+      return '写入 ' + String((input || {}).file_path || '').split(/[\\/]/).pop();
+    if (n === 'NotebookEdit')
+      return '编辑 ' + String((input || {}).notebook_path || (input || {}).file_path || '').split(/[\\/]/).pop();
     if (n === 'Bash' || n === 'PowerShell')
       return String((input || {}).command || '').trim().slice(0, 40);
     return '';
@@ -373,68 +380,157 @@
     if (n === 'Bash' || n === 'PowerShell') return 'C:' + String(i.command || i.cmd || '');
     return '';
   }
-  function _tlExpFlush(histMode) {
+  // ==================== v4.1.1：ZCode v3.18 统一摘要组（ConsecutiveSummaryGroup 移植）====
+  // 两段 AI 正文之间的连续 思考段 + 查阅/执行/修改 工具折叠成一个胶囊抽屉，
+  // 收起只显一行统计「已查阅 2 项，已执行 1 命令」。对照 zcode 仓库
+  // packages/ui/src/v4/conversationAssistantWorkItems.ts 的
+  // groupConsecutiveAssistantSummaries + formatAssistantSummaryStatistics，
+  // 渲染壳对照 ToolCallBlocks/ToolSummaryRow.tsx ConsecutiveSummaryGroup。
+  // 组员归类（对照 getAssistantSummaryToolCategory）：
+  //   explore=Read/Glob/Grep/WebSearch/WebFetch/TodoRead/LS+codegraph_explore
+  //           +只读 bash（沿用 v3.2 _hgIsExplore 全集）
+  //   run    =Bash/PowerShell 非只读（shell 族）
+  //   change =Edit/Write/MultiEdit/NotebookEdit（file-write 族）
+  // 断组边界（对照「正文、Workflow、Subagent 与未归类工具是边界」）：
+  //   assistant 正文、提问卡、子代理卡、识图卡、TodoWrite、Skill/计划/任务族、
+  //   后台任务卡、sysnote/raw/exit/renew/audit 行、未归类 MCP 工具。
+  // 思考段是组员不打断（07-hist startThinking 直接入组体，跨思考累积沿用
+  // v3.2.13 定调）。v3.2 的「🔍 查阅」桶汇总在主链退役——窗格（14-subpane）
+  // 保持旧聚组不动，_hgExpBucket/_hgExpSumTxt 仍为其服务。
+  function _hgSumCategory(name, input) {
+    const n = name || '';
+    if (_hgIsExplore(n, input)) return 'explore';
+    if (['Edit', 'Write', 'MultiEdit', 'NotebookEdit'].includes(n)) return 'change';
+    if (n === 'Bash' || n === 'PowerShell') return 'run';
+    return null;   // 未归类＝断组（对照 getAssistantSummaryToolCategory → null）
+  }
+  // 组头统计文案（对照 formatAssistantSummaryStatistics：只计工具调用不计
+  // 返回目标数；change 按文件路径去重；全组无工具落「思考」兜底）
+  function _hgSumStatsTxt(e, completed) {
+    const parts = [];
+    if (e.cat.explore) parts.push((completed ? '已查阅 ' : '查阅 ') + e.cat.explore + ' 项');
+    if (e.cat.run) parts.push((completed ? '已执行 ' : '执行 ') + e.cat.run + ' 命令');
+    if (e.filesN) parts.push('修改 ' + e.filesN + ' 文件');
+    if (e.unresolved) parts.push('修改 ' + e.unresolved + ' 次（路径未知）');
+    return parts.join('，') || '思考';
+  }
+  // 代表图标（对照 getAssistantSummaryIconItem 优先级 change>run>explore，缺省脑）
+  function _hgSumIcon(e) {
+    const _w = s => '<span style="vertical-align:-2.5px">' + s + '</span>';
+    if (e.filesN || e.unresolved) return _w(ICO16.pencil);
+    if (e.cat.run) return _w(ICO16.terminal);
+    if (e.cat.explore) return _w(ICO16.search);
+    return _w(ICO16.brain);
+  }
+  // 组头绘制：回合在跑且本组是时间线末位=运行态（活动条目活字/间隙统计+脉动）；
+  // 否则定稿态统计（已前缀）。对照 ConsecutiveSummaryGroup 的 groupRunning
+  //（boundary.taskRunning && tailRowId===lastRowId）——组后出现任何边界行
+  // （正文/未归类卡）即不再是末位，当场定格「已…」统计
+  function _hgSumPaint(e) {
+    if (!e || !e.el) return;
+    const nameEl = e.el.querySelector('.h-tl-grp-name');
+    if (nameEl) nameEl.innerHTML = _hgSumIcon(e);
+    const sumEl = e.el.querySelector('.h-tl-grp-sum');
+    if (!sumEl) return;
+    const running = !!_HG.busy && !e.el.nextElementSibling;
+    if (!running) {
+      sumEl.textContent = _hgSumStatsTxt(e, true);
+      sumEl.classList.remove('hg-sum-gap');
+      return;
+    }
+    if (e.liveTxt) { sumEl.textContent = e.liveTxt; sumEl.classList.remove('hg-sum-gap'); }
+    else { sumEl.textContent = _hgSumStatsTxt(e, false); sumEl.classList.add('hg-sum-gap'); }
+  }
+  function _tlSumCreate(g) {
+    const grpEl = document.createElement('div');
+    grpEl.className = 'h-tl-grp';   // v3.2.19（用户定调「执行过程中默认不展开」）沿用：生而收起
+    grpEl.innerHTML =
+      `<button class="h-tl-grp-head"><span class="h-chev">▸</span>` +
+      `<span class="h-tl-grp-name"></span>` +
+      `<span class="h-tl-grp-sum"></span></button>` +
+      `<div class="h-tl-grp-body"></div>`;
+    // v3.4.90 同款：空组 tl 是内联 display:none——首成员入列必须翻显
+    if (g.tl.style.display === 'none') g.tl.style.display = '';
+    g.tl.appendChild(grpEl);
+    return { el: grpEl, n: 0, cat: { explore: 0, run: 0 },
+             files: {}, filesN: 0, unresolved: 0, keys: {}, liveTxt: null };
+  }
+  // 定稿（断组/回合边界调用）：单成员组解包（对照 ZCode items.length<2 不包壳
+  // 直接渲染原行——孤思考段/孤工具行回时间线）+ 头部定格「已…」统计 +
+  // 未被动过则自动收起。v3.2.1 判据沿用（回放必收/live 底部跟读判据）
+  function _tlSumFlush(histMode) {
     const g = _HG.grp;
     if (!g || !g.exp) return;
     const e = g.exp;
     g.exp = null;
-    // 定稿：头部定格为桶汇总（去掉运行态活字），未被动过则自动收起
     // v3.2.13：histBuilding——原子渲染期组在游离缓冲内 isConnected 恒
     // false，原早退会让定稿头部永远停在运行态活字；缓冲期内照常定格
     if (!e.el.isConnected && !_HG.histBuilding) return;
+    const body = e.el.querySelector('.h-tl-grp-body');
+    if (body && body.children.length === 1) {
+      const only = body.firstElementChild;
+      if (only && e.el.parentNode) e.el.parentNode.insertBefore(only, e.el);
+      // 组头错误冒泡标记（renderOneToolResult 落在组头 sum 位）随行归还
+      const fm = e.el.querySelector('.h-tl-grp-head .h-tool-failmark');
+      if (fm && only) only.appendChild(fm);
+      e.el.remove();
+      return;
+    }
     const sumEl = e.el.querySelector('.h-tl-grp-sum');
-    if (sumEl) sumEl.textContent = _hgExpSumTxt(e.sum);
+    if (sumEl) { sumEl.textContent = _hgSumStatsTxt(e, true); sumEl.classList.remove('hg-sum-gap'); }
     // v3.2.1（用户实测问题2）：回放定稿必收——重建期 scrollTop 在顶，
-    // isNearBottom() 恒 false → 查阅组在回滚/切回后永远开着；histMode 由
+    // isNearBottom() 恒 false → 摘要组在回滚/切回后永远开着；histMode 由
     // 调用方传（grpFinalize 用 _hist 事实分级——尾组定稿发生在 openState
     // 清空之后，只看 openState 会丢回放语义）；live 保持 v2.12 底部跟读判据
     if (e.el.dataset.userToggled !== '1' && (histMode || isNearBottom())) e.el.classList.remove('open');
   }
   function _hgExpSumTxt(sum) {
+    // v4.1.1：主链桶汇总已并入统一摘要组（_hgSumStatsTxt）——本函数仅剩
+    // 窗格（14-subpane）旧聚组一个消费方，保留防断
     const parts = [];
     if (sum.search) parts.push(sum.search + ' 搜索');
     if (sum.list) parts.push(sum.list + ' 列表');
     if (sum.file) parts.push(sum.file + ' 文件');
     return '· ' + (parts.join(' · ') || '0 项');
   }
-  // 时间线落位：explore 类 → 当前查阅组（无则建）；其余 → 先断组再挂时间线。
-  // renderToolUse 与 renderHistTool（回放）同走本函数——live/回放聚组一致
+  // 时间线落位：组员类（explore/run/change）→ 当前摘要组（无则建）；其余 →
+  // 先断组再挂时间线。renderToolUse 与 renderHistTool（回放）同走本函数——
+  // live/回放聚组一致
   function _tlPlace(row, name, input) {
     const g = grpEnsure(true);
     // v3.5.190（同 07-hist）：工具行不让位——气泡保留到正文到达
-    if (!g.tl) { _tlExpFlush(!!_HG.openState); drawerAppend(row, 'exec'); return; }   // 旧快照组：回落旧抽屉
-    if (_hgIsExplore(name, input)) {
-      if (!g.exp || (!g.exp.el.isConnected && !_HG.histBuilding)) {   // v3.2.13：缓冲期视缓冲内组为在场（grpEnsure 同判）
-        const grpEl = document.createElement('div');
-        grpEl.className = 'h-tl-grp';   // v3.2.19（用户定调「执行过程中默认不展开」）：生而收起——运行态活字照上组头，点击展开
-        grpEl.innerHTML =
-          `<button class="h-tl-grp-head"><span class="h-chev">▸</span>` +
-          `<span class="h-tl-grp-name"><span style="vertical-align:-2.5px">${ICO16.search}</span> 查阅</span>` +
-          `<span class="h-tl-grp-sum"></span></button>` +
-          `<div class="h-tl-grp-body"></div>`;
-        g.tl.appendChild(grpEl);
-        // v3.2.1（用户实测问题2）：撤位置键开合恢复——_hgPathKey 按 DOM 位置
-        // 索引链编键，跨 DOM 代际（v3.1 抽屉↔v3.2 时间线、回滚截断、扩段窗移）
-        // 同键指向不同行，旧记录误开新行还误标 userToggled（用户实锤「终端默
-        // 认全部不收起」）。查阅组与终端卡统一默认收起，点击开合只在当前
-        // DOM 生命周期内有效（用户定调：必须默认都是收起状态）
-        g.exp = { el: grpEl, sum: { search: 0, list: 0, file: 0 }, keys: {} };
-      }
-      // v3.2.13：同目标重复子行折叠为一条（两次读同文件/同 pattern 搜索）——
-      // 不重复入 DOM、组头计数不重复计
-      const _ek = _hgExpKey(name, input);
-      if (_ek && g.exp.keys[_ek]) return;
-      if (_ek) g.exp.keys[_ek] = 1;
-      const body = g.exp.el.querySelector('.h-tl-grp-body');
+    if (!g.tl) { _tlSumFlush(!!_HG.openState); drawerAppend(row, 'exec'); return; }   // 旧快照组：回落旧抽屉
+    const cat = _hgSumCategory(name, input);
+    if (cat) {
+      if (!g.exp || (!g.exp.el.isConnected && !_HG.histBuilding)) g.exp = _tlSumCreate(g);   // v3.2.13：缓冲期视缓冲内组为在场（grpEnsure 同判）
+      const e = g.exp;
+      // v3.2.13：同目标重复子行折叠为一条——仅查阅类沿用（两次读同文件/
+      // 同 pattern 搜索）；执行/修改每次调用都是真动作绝不折叠（对照 ZCode
+      // 「统计工具调用，同一会话的多次操作也分别计数」口径）
+      const _ek = cat === 'explore' ? _hgExpKey(name, input) : '';
+      if (_ek && e.keys[_ek]) return;
+      if (_ek) e.keys[_ek] = 1;
+      const body = e.el.querySelector('.h-tl-grp-body');
       if (body) body.appendChild(row);
-      g.exp.sum[_hgExpBucket(name, input)]++;
-      const sumEl = g.exp.el.querySelector('.h-tl-grp-sum');
-      if (sumEl) {
-        const live = _hgExpLiveTxt(name, input);
-        sumEl.textContent = live ? '· ' + live : _hgExpSumTxt(g.exp.sum);
+      // v4.1.1R2：行级 CV 豁免随行内联——正式版页面无 F5（server.py __HG_DBGF__
+      // 注释），CSS 层豁免（style.css .h-tl-grp.open 规则）经注入通道到不了
+      // 活页，内滚振荡残影在 CSS 就位前也必须死。行内联恒赢样式表，与 CSS
+      // 规则互为冗余双保险
+      row.style.contentVisibility = 'visible';
+      e.n++;
+      if (cat === 'explore') e.cat.explore++;
+      else if (cat === 'run') e.cat.run++;
+      else {
+        // change 按文件路径去重计数（对照 ZCode changedPaths 词法去重：
+        // 路径别名/重复编辑同文件不虚增「修改 N 文件」）
+        const fp = String((input || {}).file_path || (input || {}).notebook_path || '');
+        if (fp) { if (!e.files[fp]) { e.files[fp] = 1; e.filesN++; } }
+        else e.unresolved++;
       }
+      e.liveTxt = _hgExpLiveTxt(name, input);
+      _hgSumPaint(e);
     } else {
-      _tlExpFlush(!!_HG.openState);   // v3.2.1：回放态断组必收
+      _tlSumFlush(!!_HG.openState);   // v3.2.1：回放态断组必收
       // v3.4.90（用户实锤「识图过程没显示」）：空组的 tl 是内联 display:none
       //（grpFromDom 对 children=0 落的）——首行入列必须翻显，否则识图卡/
       // 工具行困在隐藏容器（_sysRowIntoGroup v3.4.80 同修法的上游收口）
@@ -925,6 +1021,15 @@
           `<span class="h-tool-failmark">${st === 'denied' ? '已拒绝' : '执行失败'}</span>`);
       }
     }
+    // v4.1.1：组员收口——活字让位（工具间隙=组头统计+脉动；仅当前开放组，
+    // 已定稿旧组只翻行内徽章不重画组头）
+    {
+      const _cap = row.closest('.h-tl-grp');
+      if (_cap && _HG.grp && _HG.grp.exp && _HG.grp.exp.el === _cap) {
+        _HG.grp.exp.liveTxt = null;
+        _hgSumPaint(_HG.grp.exp);
+      }
+    }
     // 结果折叠体（成功默认藏，错误永远显）
     const hideOk = cfg.result === 'hide' || cfg.kind === 'bash' || cfg.kind === 'diff';
     if (cfg.kind === 'diff' && st === 'completed') _hgDiffLineFix(row);   // v3.4.62：成功改盘才定位（轻审P2：失败 Edit 文件未写，误配出假行号）
@@ -1065,3 +1170,12 @@ function _taskFinish(tid, state, summary) {
   }
   _subDirPaint && _HG.active === '__dir__' && _subDirPaint();
 }
+// ==================== v4.1.1R2：注入扫尾（免 F5 活页的就地治疗）====================
+// 注入通道送达本文件时，活页里可能已有旧代码摆放的胶囊成员行（仍带 a120Q
+// 行级 CV 28px 占位=内滚振荡残影源，用户实锤「点了几下叠行」）——就地补
+// 内联豁免，正在开着的坏胶囊下一次重排即自愈，无需刷新。页面冷启动时
+// flow 为空，本扫尾零开销
+try {
+  document.querySelectorAll('.h-tl-grp-body .h-tool')
+    .forEach(el => { el.style.contentVisibility = 'visible'; });
+} catch (_) {}
diff --git a/web/style.css b/web/style.css
index 304a9844..10785d86 100644
--- a/web/style.css
+++ b/web/style.css
@@ -4762,16 +4869,28 @@ html {
   font-size: var(--fs-sm); color: var(--muted); text-align: left; border-radius: 5px; }
 .h-tl-grp-head:hover { color: var(--fg); }
 .h-tl-grp-head .h-chev { font-size: 10px; display: inline-block;
-  transition: transform .15s; color: var(--muted); }
-.h-tl-grp.open > .h-tl-grp-head .h-chev { transform: rotate(90deg); }
-.h-tl-grp-name { color: var(--muted); font-weight: 500; }
+  transition: transform .15s, opacity .15s; color: var(--muted);
+  opacity: 0; }   /* v4.1.1:ZCode v3.18 同款——收起态 chevron 悬浮显现 */
+.h-tl-grp-head:hover .h-chev { opacity: 1; }
+.h-tl-grp.open > .h-tl-grp-head .h-chev { transform: rotate(90deg); opacity: 1; }
+.h-tl-grp-name { color: var(--muted); font-weight: 500;
+  display: inline-flex; align-items: center; }   /* v4.1.1:代表图标槽（修改>执行>查阅，缺省脑） */
 .h-tl-grp-sum { color: var(--muted); opacity: .8; font-size: var(--fs-xs); }
+/* v4.1.1:运行间隙（组在跑但无活动条目）统计脉动——ZCode animated-gradient-text 对位 */
+.h-tl-grp-sum.hg-sum-gap { animation: hg-think-blink 1.6s ease-in-out infinite; }
 /* 展开的子行树：左竖线 + 缩进（ZCode explore ml-2 border-l pl-3.5 同款） */
 .h-tl-grp-body { display: none; margin: 1px 0 2px 21px; padding-left: 11px;  /* v3.1h:随头 13px 同步右移 */
   border-left: 1px solid color-mix(in srgb, var(--border) 90%, transparent);
   flex-direction: column; gap: 3px; }
 .h-tl-grp.open > .h-tl-grp-body { display: flex;
   max-height: 42vh; overflow-y: auto; }   /* a270：查阅组子树同限 42vh 内滚 */
+/* v4.1.1R（用户实锤「多点了几下叠行/半行」）：胶囊体是内滚容器——a120Q 的
+   行级 content-visibility:auto（28px 占位估高）在内滚里滚进滚出反复物化，
+   行高振荡（探针实测 30↔56px/行）叠加 .hg-flow 的 contain:layout 合成层
+   失效缺口=旧帧残影（同一条 Grep 行在两个位置各画半截）。开启的胶囊子树
+   豁免行级 CV：成员体是懒壳（空体）物化代价≈行头 30px/条，36 行胶囊一次
+   布局毫秒级，换内滚稳定性；关闭态 body display:none 无渲染不受影响 */
+.h-tl-grp.open > .h-tl-grp-body .h-tool { content-visibility: visible; }
 
 /* ---- a262（用户实锤：收起行左色条 34/25/28 三长不齐，连宽也不齐 2/2/3px）
   三类收起行统一为定长 30px × 2px、垂直居中的左色条（::before 定位条，
```
