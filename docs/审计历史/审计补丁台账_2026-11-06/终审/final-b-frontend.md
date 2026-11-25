# 前端对抗式终审（final-b-frontend）

> 对象：e1e2067（=a393，28 补丁全量落盘）中的全部前端改动——web/js/nav.js、web/js/editor.js、web/js/settings.js、web/js/sidebar.js、web/style.css、src/update_server.py（portal 页五行属前端面）。
> 立场：只找问题不修复。只读 + CDP 9223 新开独立 target 做只读行为验证（已用完关闭）。
> 不重复报：R28-R35、28 实锤本体、10 轮补丁审计、干跑发现（doc/patch-apply-frontend.md 第一节的五件事及全部注记——含 P-26 覆盖面错位（office/bitcalc 存量泄漏）、P-22 已记忆值显示空白、R2-4 缺 meta 抛错、isMd 无可见效果、h2 冗余护栏、台账转写失真等）。

---

## 一、结论先行

**新实锤 4 条（P3×1 + P4×3），实证更正 1 条，一致性注记 2 条。** 落盘代码本身：12 件补丁的落码与干跑附录一致（含两处顺手修：c.meta 判空、selectedIndex 回退），四文件 node --check 复验全过，未发现补丁引入的语法、作用域或递归问题。问题集中在两处：**P-5 的 z-index 修复只提了两个 ID，其余 .modal 弹窗在 9999 面板下仍被遮（B-F1，P3）**；**S-B7 族的收口在三处 fetch 窗口之外还有第 4 处同型缺口和两个弹窗挂起盲区（B-F2/B-F4，P4）**。另外 CDP 实测推翻了 S-B7 原实锤的"setValue 抛错"机理（B-F3）——vendored Monaco 双 dispose 后相关 API 全部静默，这不否定 P-14 的价值，但既有审计的机理描述需要留档更正。

| 编号 | 级别 | 一句话 | 位置 |
|---|---|---|---|
| B-F1 | P3 | z 提升只覆盖 ddConfirm/ddProgress，其余 .modal（z100）在 nav 全屏面板（z9999）期间弹出的弹窗仍被遮——磁盘已改三选框是最现实场景 | web/style.css:1890/:2135 ↔ web/js/editor.js:1136、web/js/nav.js:776 |
| B-F2 | P4 | 编码切换重读链 await 窗口无存活护栏——S-B7 族第 4 处同型缺口（实测后果降级为误导 banner） | web/js/editor.js:263-294（encSel.onchange） |
| B-F3 | 更正 | "monaco dispose 后 setValue 抛错"在真实 vendored Monaco 0.52 上不成立（双 dispose 后全静默），S-B7/干跑的异常路径系桩模拟 | 证据见第四节实测 |
| B-F4 | P4 | _edDiskChangedModal 挂起窗口是护栏盲区：弹窗不随关 tab 回收（滞留）；edSave 409 挂起时关 tab 后选"保留内存版"会对已关 tab 强制覆盖写盘 | web/js/editor.js:1136/:1107（409 keep 分支）/:1436（_edCloseNow 清理清单不含该弹窗） |
| B-F5 | 注记 | monacoLangFor 自动路径仍返回未注册的 'makefile'（makefile/readme/.mak/.mk）——实测静默回落 plaintext，无故障，与撤项理由自洽，仅一致性 | web/js/monaco-bridge.js:36-44 |
| B-F6 | P4 | P-26 正则在全部产品 UI 路径上的命中集为空（tab 栏 ✕ 只服务后端 port_id 类连接），补丁零行为变化，纯防御 | web/js/sidebar.js:113-121 ↔ web/js/terminal-core.js:76 |

---

## 二、逐件复核（按任务七项重点）

### ① P-5 四出口复位矩阵 + z-index 10001 —— 出口齐，z 修复覆盖面不全（B-F1）

四出口走查（nav.js:881-905 落盘版）：

| 出口 | 落盘处理 | 判定 |
|---|---|---|
| 确认取消 | `bkSel.value = m.backend \|\| (m.code_files>=200000?'sqlite':'memory'); return;` | ✓ |
| POST 返回 ok:false（原 :883） | `if (!d2.ok) bkSel.value = ...` | ✓ |
| fetch 抛错（原 :884 catch） | catch 内同式复位 | ✓ |
| POST 成功（R4-F1） | `if (d2.ok) m.backend = v;` 前瞻同步 | ✓ |
| （任务异步失败） | 无前端复位——注释明示"由索引面板重开（按 meta 渲染）兜底"，失真窗口=面板不重开期间；m.backend 污染的是本次渲染闭包的 meta 快照，重开面板从后端取真值 | 设计取舍，与干跑口径一致 |

补充两点：复位表达式在三处逐字一致（R5F-2③ 撤回合并，维持现状已知）；`await _ddConfirm(...)` 位于 try 块之外，理论上存在"确认弹窗本身抛异常→不复位"的第 5 出口，但 _ddConfirm（settings.js:2044）的 Promise 只在三个按钮回调里 resolve、永不 reject，该出口不成立。

z 序全仓数值走查：10001 之上仅 editor.js:2442 调试探针（99999，pointer-events:none）；.ctx-menu 10000 在其下——但 ctx-menu 由 tabs/树的 contextmenu 触发，ddConfirm 打开时事件落在 modal 遮罩上到不了那些监听，不存在"看不见的菜单"；banner（300/320）不与确认框同域。ddConfirm/ddProgress 同层 10001，迁移流程是确认先 resolve（remove('show')）再开进度，无同屏竞争。**倒挂不存在；问题在反方向——没被提升的弹窗（B-F1）。**

### ② P-11 md-pv 收敛 —— 判空已落盘，链路成立

落盘版 `const isMd = c && c.meta && (c.meta.label || '').toLowerCase().endsWith('.md');`（干跑修正 4 已带上）。遍历依赖的 `.term-area` 两处构建点都写 `wrap.dataset.portId`（editor.js:110-111、terminal-core.js:74），connections 是 util.js:20 顶层 let，跨脚本可见——收敛广播可达笔记与 .md tab。isMd 分支无可见效果为干跑注记，不重复。

### ③ P-14 三处护栏 —— 位置正确，族收口有两类缺口（B-F2/B-F4）

三处护栏分别落在 _edCheckDiskChanged 的 stat 之后（R4-F2）、_edReloadFromDisk 的 j2 之后（R3-4）与 monaco 分支内（h2，冗余已知）、_edJumpFresh 的 stat 之后。护栏依赖的 `delete connections[...]` 在 _edCloseNow（editor.js:1509）与 closeConnection（sidebar.js:149）两条关闭路径都存在，转发链上同样有效。**但族收口不完整**：

- 第 4 处同型 await 窗口：encSel.onchange（编码切换重读，editor.js:263-294）——`await fetch('/api/ed/open?force=1...')` 之后无存活护栏，直接 `conn.monaco.getPosition()/setValue()`（B-F2）；
- 两个弹窗挂起盲区：_edCheckDiskChanged 轮询弹窗与 edSave 409 弹窗的 `await _edDiskChangedModal(...)` 窗口内关 tab，三处护栏全部管不到（B-F4）。

### ④ P-22 记忆回退 —— 语义正确，无降级风险

落盘在 _edBindLangSel 两处（bound 分支与首绑，editor.js:443/:447）加 `if (sel.value && sel.selectedIndex < 0) sel.value = '';`。核对三点：下拉存在 `<option value="">语言：自动</option>`（:135），回退后显示正常；回退不同步清 conn.langOverride 与 localStorage——bound 分支每次重绑都会再回退，无实害（注记）；记忆恢复链 `_ov → conn.langOverride → monacoCreate(..., 'makefile')` 的下游行为经 CDP 实测（见第四节）：**未注册语言 id 在 createModel/editor.create/setModelLanguage 三条路径全部不抛错、languageId 静默回落 plaintext**，不存在"重开降级 textarea"的风险。

### ⑤ P-25 动态围栏 IIFE —— 语法与语义均正确

`md.value = ((_s) => {...})(String(c.snippet || ''));` 赋值链闭合；四文件 node --check 复验通过。走查：matchAll 的正则带 g 标志（必须，否则抛 TypeError）；`_max` 初值 3 保证空 snippet 也是四栏（与 R33-3 原行为对齐）；`_f = _max + 1` 恒大于 snippet 内任何反引号串，CommonMark 意义上不可被内容闭合；`String(c.snippet || '')` 兜住 null/undefined/非串。无问题。

### ⑥ P-26 关闭转发 —— 链路完整，但命中集为空（B-F6）

核对：四类 portId 生成前缀逐一匹配正则（edit: editor.js:94、hex: hex-viewer.js:32、diff: diff-viewer.js:174、bindiff: hex-diff.js:180/:205）；转发目标 closeEditorTab(portId) 签名一致，内部脏确认→_edCloseNow，尾部自带 switchTab（回"来时的 tab"）+ refreshSidebar，与 closeConnection 原收尾等价；无递归（closeEditorTab/_edCloseNow 不回调 closeConnection）；`typeof closeEditorTab === 'function'` 防住了 editor.js 加载失败序。

**新事实（对已知第 3 件事的补充，不与其重复）**：全仓 closeConnection 调用点共两个——sidebar.js:243（侧栏 ✕ 的 else 分支，四类已被 :241 isEdit 分流，落到这的只剩 office/bitcalc 等正则不含的类型）和 terminal-core.js:76（buildTerminal 建的 tab ✕）。而 buildTerminal 仅服务后端 port_id 类连接（serial/ssh/telnet，sidebar.js:51/:76/:99；claude，claude.js:33——portId 同样来自后端 j.port_id），四类编辑 tab 的 ✕ 由各自 viewer 直连 closeEditorTab（editor.js:100、hex-viewer.js:37、diff-viewer.js:181、hex-diff.js:211）。**即 P-26 正则在全部产品 UI 路径上一次也不会命中：补丁零行为变化，是纯防御桩**；它想守的泄漏面（office/bitcalc，已知存量）依旧不守。定性 P4：不产生错误，但"附带防御"的实际防御价值应为零这一事实未在补丁注释与提交信息中体现（注释写"产品路径四类统一走 closeEditorTab（:198/:233 实证）"——实证的恰是这条路径不存在）。

### ⑦ 补丁间 DOM/事件监听交互 —— 未发现冲突

- P-22 的 HTML 注释进 `<select>`：注释节点在 options 之外合法，sel.options/selectedIndex/value 求值不受影响；
- P-12 首拉后 `selIdx = 0` 与 P-16 Enter 分支取 `all[selIdx]`：过滤通道下口径一致；
- P-25 的 provideHover 每次调用现算 md 对象，无监听注册、无状态残留；
- P-11 的 querySelectorAll 静态快照遍历与 P-26 关 tab 移除 wrap：遍历中对已摘除节点染色，无害；
- P-14×P-26：转发关闭链上 `delete connections` 先于任何后续 await 返回，护栏有效（上节已核）；
- P-5 的 bkSel 为 _renderState 每次新建，旧 select 摘除后 onchange 不可再触发，无重入残留；
- P-21 五行：`.mn-step` 不在 `.mn-card` 内（grep 全部 .mn-card 都在 mn-grid），`.mn-card b{display:block}`（update_server.py:547）作用不到 `<b>N.</b>`，裸 b 规则（.notes/.tip）也不命中，标题保持行内 700，无布局回归；settings.js ⚪→dotOff 的 ICO16 引用同文件已有先例。

---

## 三、新发现详述

### B-F1（P3）z 提升覆盖面不全：9999 面板期间其余 modal 弹窗仍被遮

`.modal` 默认 `z-index:100`（style.css:1890）。P-5/R2-3 只把 #ddConfirmModal/#ddProgressModal 提到 10001，同类的 **edDiskChangedModal（磁盘已改三选，editor.js:1136 `className='modal'`）、edConfirmModal（脏确认/:1411）、edSave 409 复用的同一弹窗**都还是 100。而 nav.js 的全屏面板（索引 :776、符号 :274/:347/:452、引用 :224）内联 z-index:9999、fixed inset:0 拦点击。

现实场景：索引面板开着（活动编辑 tab 的 wrap 并未 display:none，5s 磁盘轮询照跑，editor.js:1257 的可见性判断只看 wrap.display）→ 文件被外部改 → `_edDiskChangedModal` 弹出（z100）→ **被 9999 面板整个盖住，用户不可见不可点**；`conn._dcAsking = true` 抑制重复弹，表现为"面板开着期间磁盘改动永远无提示"，关掉面板才看到滞留的弹窗。不丢数据（内存版保留），但提示链断裂。脏确认（面板开着时 Ctrl+S 触发 409 弹窗）同理更边缘。修复口径本批未定，属 C-2 的同族残留面——只提两个 ID 的选择让"确认/进度在面板之上"这条修复原则没有贯彻到同一层级的其他模态。

### B-F2（P4）S-B7 族第 4 处缺口：编码切换重读链无护栏

editor.js:263-294（encSel.onchange）：`await _edConfirm(...)`（dirty 时）与 `await fetch('/api/ed/open?force=1&...')` 之后，直接 `conn.monaco.getPosition(); conn.monaco.setValue(j.text)`，无 `connections[conn.portId] !== conn` 检查——与三处已修护栏完全同型。fetch 窗口内关 tab 的实际后果（按第四节实测，Monaco disposed 不抛）：setValue 静默无效果，随后 `_edSetBase/_edMarkTab/_edUpdateInfo` 写游离 conn（tab 已 remove，querySelector 在游离节点上正常返回，无抛），最后 **showBanner('已按 X 重新读取')——tab 已关，误导性提示**。无异常、无状态污染，故 P4。一致性缺口本身值得收口（四处同型只修三处）。

### B-F3（实证更正）"monaco dispose 后 setValue 抛错"前提不成立

audit-b:119 对 S-B7 的机理描述是"monaco dispose 后 setValue 抛错 → 误弹「重读失败」banner"；干跑 S1/S2 的基线复现（「重读失败: monaco disposed」）是在注入桩里"让 monaco/editor 抛出 disposed"模拟出来的。CDP 独立 target 加载同版本 vendored Monaco（0.52 min，file:// 直读 vendor/monaco）实测：**editor.dispose() + model.dispose()（_edCloseNow:1447+:1458 同款双 dispose）之后，getPosition/setValue/setPosition/getValue 全部 NO_THROW（getValue 返回 ''，getModel 返回 null），setModelLanguage 对未注册 id 亦不抛**。也就是说真实产品路径上 S-B7 的"异常 banner"半边不存在；P-14 护栏的真实净收益是另半边——防「已重新加载」误导 banner 与对游离 conn 的状态写入（这部分仍真实成立）。结论：护栏该留，机理描述该改；B-F2 的严重度也据此从"同 S-B7"降为 P4。

### B-F4（P4）弹窗挂起窗口盲区：滞留弹窗 + 已关 tab 强制写盘

_edDiskChangedModal 是 Promise 弹窗，两个入口的挂起窗口都没有存活护栏，且 _edCloseNow 的清理清单（:1436-1502）不含它：

1. **轮询入口**（_edCheckDiskChanged）：弹窗挂起时关 tab → 弹窗滞留屏幕（不随 tab 回收），用户点任一按钮才消失。reload 分支进入 _edReloadFromDisk 有护栏、静默正确；**keep 分支无护栏**——对游离 conn 置 dirty、_edMarkTab/_edUpdateInfo（游离节点，无抛），并误弹「已保留内存版并标记改动」（tab 实已关闭）。
2. **409 入口**（edSave，editor.js:1107 附近）：保存撞外部改动弹窗挂起时关 tab（dirty 状态 → 脏确认放行 → tab 关闭）→ 用户回到弹窗点「保留内存版」→ `return edSave(conn, true)`——**对已关闭的 tab 以 _forceOverwrite=true（跳过 CAS）重新 POST /api/ed/save 强制覆盖磁盘**。用户刚刚确认"关闭将丢失"，随后内存中间态却被写盘，语义相悖。需要三步用户操作，极边缘，但它是本族唯一会产生真实写盘副作用的出口，定 P4。

### B-F5（注记）monacoLangFor 自动路径仍产出未注册 id

monaco-bridge.js:36-44：名为 makefile/readme 或后缀 .mak/.mk 的文件，自动判定仍返回 'makefile'——P-22 以"vendored Monaco 0.52 无 makefile 注册（91 id 实证）"为由撤了下拉项，但自动链没动。实测（第四节）未注册 id 三条 API 路径全部静默回落 plaintext：无故障、下拉显示"自动"正确、与"makefile 无高亮=纯文本不可区分"的撤项理由自洽。仅指出补丁边界停在选项表、没触判定表，长期方案（vendor 补 Monarch 包）落地前两端不一致无害。

### 小注（不计数）

- P-5 取消分支注释引用"（见 P-5b 的 CSS 补丁）"——P-5b 原段已被 R2-3 取代且从未落码，注释指向一个不存在的补丁名，读者会空找；
- P-22 回退只改 sel.value 不清 conn.langOverride/localStorage（上节②已述，无实害）；
- 干跑注记过的"P-25 落地后围栏段无注释"在落盘版同样未补（R7-2 的 + 段本来就没有）。

---

## 四、方法与证据

- **走查**：`git show e1e2067` 六文件全 diff；对照 doc/patch-apply-frontend.md 附录逐字节核对（含两处顺手修）；全仓 z-index、closeConnection/buildTerminal/closeEditorTab 调用图、portId 前缀生成点、.modal 家族与 9999 面板的层叠关系、update_server.py 的 b 元素规则命中。
- **语法复验**：nav/editor/sidebar/settings 四文件 `node --check` 全过（2026-11-06 本机 node v24.19.0）。
- **CDP 实测**（9223，`/json/new` 独立 target FCCD25CF79185284756A818CA7B66E68，已 `/json/close` 关闭；全程只读，未触碰用户页面 4C4ADC23）：file:// 加载与产品同版本的 vendored Monaco（vendor/monaco/min/vs，getLanguages 91 id、无 makefile、有 ruby——复核 S-B3/S-B5 前提），三轮实验：
  1. createModel/editor.create/setModelLanguage 对 'makefile' 与 'totally_nosuchlang' 均不抛，languageId 回落 plaintext；
  2. editor.dispose()+model.dispose() 后 getPosition/setValue/setPosition 不抛；
  3. 同上双 dispose 后 getValue 返回 ''、getModel 返回 null（即 B-F3 证据链）。
- **限制**：本机 8867 后端服务当前未运行（旧 target 均为历史页面），部署面（服务器吐出的静态资源与落盘一致性）无法在线验证，以 git 落盘内容为准；P-5 四出口与 P-25 围栏的行为验证沿用干跑既有 CDP 结果（本轮未重复），本轮实测聚焦干跑未覆盖的 Monaco 引擎真实行为。
