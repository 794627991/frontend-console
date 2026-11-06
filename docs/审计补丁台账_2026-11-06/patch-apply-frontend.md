# 前端补丁干跑应用终审（patch-apply-frontend）

> 审计对象：doc/patch-log.md 前端 12 件终版 diff，含 patch-review-r3-frontend.md:132-147 的附带 diff
> 基线：HEAD db9f27a（web/、src/ 工作区干净）
> 方法：目标文件复制到 `%TEMP%\patch_apply_fe\`，python 按内容锚点逐字匹配应用，唯一命中才落；不命中就记下逐行诊断，再做意图重建（`+` 行逐字取台账，只把上下文和 `-` 行换成现状原文）。每步跑 node --check / py_compile。叠加顺序做了正序、逆序、单件三种。行为验证在 CDP 9223 新开的独立 target 上做，每项都和基线对照。
> 铁律执行：六个真实源文件的 SHA256 前后一致，`git status web src` 为空。对真实仓库只运行过 `git apply --check`，这个命令只检查、不写文件。

---

## 一、结论先行

**12 件的裁决：APPLY-CLEAN 4 件，APPLY-ISSUES 2 件，DIFF-MISMATCH 6 件。** 台账原文能逐字落地的只有一半。对不上的 6 件按意图重建后全部能落，六个文件的终态语法全过。CDP 行为探针 12/12 符合补丁意图，基线对照也把 S-B1、S-B2、S-B4、S-B5、S-B7、S-B8、S-B9、C-2 这些原缺陷逐个复现了出来。

落码前要先知道五件事：

1. **台账 diff 不能直接 `git apply`。** 有 6 件的上下文行或 `-` 行和现状对不上，具体是省略号 `{ ... }`、尾注释被截断、一行被拆成两行、旧版文案、伪造的函数签名。用 `git log -S` 查过，这些现状文本在 11-05 16:40 到 20:55 之间的提交里就已存在，早于 audit-b（11-06 00:42）和 patch-log（最后修改 11-06 05:27），HEAD 之后也没有新提交。所以这是台账转写失真，不是源码漂移。建议直接用附录的统一 diff 落码。它对真实仓库跑过 `git apply --check`，6 个文件全部通过。
2. **R7-1 和 R4-F1 记的是同一个改动，而且重复执行不会自动跳过。** 先落 R4-F1 再落 R7-1 时，`-` 行（showBanner）还在，所以第二次照样命中，`if (d2.ok) m.backend = v;` 和后面三行注释会被插两遍，`node --check` 照样通过。任务清单把 P-5 写成"R2-3+R3-3+R4-F1+R7-1 补齐的 - 段"，按清单逐段执行就会出这个问题。这段只能执行一次。
3. **P-26 守的四类 tab 本来就不走 closeConnection。** sidebar.js:198/:233 已经把 edit/hex/diff/bindiff 分流给 closeEditorTab。实测侧栏 ✕ 真正落进 closeConnection 的是 office 和 bitcalc，终版的正则拦不到它们。office 的 pdf.js 文档和 worker、OnlyOffice 实例、两个 Observer 只在 _edCloseNow 里释放，所以这条泄漏面补丁没有覆盖。这是存量问题，不是补丁引入的。
4. **P-22 撤掉 Makefile 选项后，localStorage 里已经记成 makefile 的文件重开时下拉显示空白**（selectedIndex=-1，基线显示"Makefile"）。属于边缘回归，影响面小。
5. **R2-4 读 `c.meta.label` 时没有判空。** 只要注册表里出现一个缺 meta 的 conn，整个配色广播就会抛 TypeError 中断，后面的下拉同步和持久化都不执行；基线在同样情况下不抛错。目前全部 13 个写入点都带 meta，所以这只是潜在风险，不过 sidebar.js:188 已经有防这类畸形 conn 的先例。另外实测 .md tab 的 .ed-scroll 被 Monaco 完全盖住，isMd 分支没有任何可见效果。

还有一条文档层面的事实要更正：⬇（U+2B07）的 Emoji_Presentation 属性是 No。V8 的 `\p{Emoji_Presentation}` 对它返回 false；用按钮字体在 canvas 上实测，它渲染成单色，彩色像素为 0。加了 FE0F 的 ⬇️ 才是彩色。所以 R2-6、R3-6 和 r3 报告"⬇ Emoji_Presentation=Yes"的判定不成立，audit-b:187 原来的豁免判定其实是对的。删掉 ⬇ 本身无害，按钮文字自己就能说清楚，可以照落，但台账里那条勘误要反过来改。

---

## 二、终版裁决表

| # | 补丁 | 终版出处 | 目标文件 | 原文应用 | 重建后 | 语法 | CDP 行为 | 裁决 |
|---|---|---|---|---|---|---|---|---|
| 1 | P-5 | P-5 取消分支 + R2-3（CSS）+ R3-3 + R4-F1 | nav.js、style.css | 取消分支和 R3-3 对不上；R2-3、R4-F1 逐字可落 | 可落 | ✓ | 四个出口和 z 序全部 PASS | **DIFF-MISMATCH** |
| 2 | P-11 | P-11 + R2-4 | editor.js | P-11 的 `-` 行尾注释被截断；R2-4 逐字可落 | 可落 | ✓ | 收敛 PASS，另有 3 条注记 | **DIFF-MISMATCH** |
| 3 | P-12 | P-12 | nav.js | 上下文用了省略号，`-` 行缺尾注释 | 可落 | ✓ | 竞态 3 个用例 PASS | **DIFF-MISMATCH** |
| 4 | P-14 | P-14 两段 + R3-4 + R4-F2 | editor.js | P-14 h2 和 R3-4 用 `{ ... }` 省略；P-14 h1 和 R4-F2 逐字可落 | 可落 | ✓ | 6 个场景 PASS | **DIFF-MISMATCH** |
| 5 | P-16 | P-16 | nav.js | onclick 段逐字可落；Enter 分支只有一句"同款" | 推导后可落 | ✓ | 点击、回车、ed=null、取消全部 PASS | **APPLY-ISSUES** |
| 6 | P-21 | R3-5 + update_server 五处 | settings.js、update_server.py | R3-5 逐字可落；update_server 段是规则式伪 diff | 可落（恰好 5 行） | ✓ | 渲染和 emoji 扫描 PASS | **DIFF-MISMATCH** |
| 7 | P-22 | P-22 | editor.js | 逐字可落 | — | ✓ | 撤项 PASS；已记忆的值显示空白 | **APPLY-ISSUES** |
| 8 | P-24 | P-24 | editor.js | 逐字可落 | — | ✓ | Ruby 正常显示 | **APPLY-CLEAN** |
| 9 | P-25 | R3-1，实际以 R7-2 为准 | nav.js | R3-1 缩进多 2 且缺两行注释；R7-2 逐字可落 | — | ✓ | 合成 8 例 + 真函数 3 例 PASS | **APPLY-CLEAN**（按 R7-2 落） |
| 10 | P-26 | R2-2 + R3-2 | sidebar.js | R2-2 是伪签名加 `...原分发逻辑...`；R3-2 逐字可落 | 可落 | ✓ | 转发 PASS；覆盖面错位 | **DIFF-MISMATCH** |
| 11 | R4-F1 | R4-F1（并入 P-5） | nav.js | 逐字可落 | — | ✓ | 第 4 出口 PASS | **APPLY-CLEAN**（R7-1 不得再落） |
| 12 | R2-3 附带 | r3 报告 :133-135、:141-143 | settings.js | 两段逐字可落 | — | ✓ | ⬇ 清零 | **APPLY-CLEAN** |

裁决口径如下。

- **APPLY-CLEAN**：台账原文逐字唯一命中，语法和行为都通过，没有遗留问题。
- **APPLY-ISSUES**：原文能落，语法也通过，但 diff 不完整，或者带来了边缘回归。
- **DIFF-MISMATCH**：原文的上下文行或 `-` 行和现状不逐字一致，没法直接 `git apply`。下文逐行列出对不上的地方，并给出意图重建后的验证结果。

---

## 三、逐件详情

### 1. P-5（C-2+S-B1）—— DIFF-MISMATCH

对不上的行：

| 台账行 | 台账文本 | 现状 | 差异 |
|---|---|---|---|
| log:296 | `? '构建 sqlite 快查索引（大库约 1 分钟，一次性）？'` | nav.js:876 `…一次性；查询 0~4ms/内存 ~50MB）？'` | 台账用的是旧版文案 |
| log:297-298 | 条件行以 `{` 结尾，`-` 行 `_renderState(card, path, j, st); return;` 单独占一行 | nav.js:877 是一整行：`` …立即生效）？`))) { _renderState(card, path, j, st); return; } `` | 现状是同行写法，台账的 `-` 行在源码里不存在 |
| log:1114/1116（R3-3） | 上下文 `} catch (e) { showBanner('切换失败: ' + e, 3000, true);`，另有一行单独的 `      }` | nav.js:884 是一整行：`… 3000, true); }` | 实际需要把一行拆成三行，台账却把它写成了上下文 |

逐字可落的部分：R2-3（style.css:2135，唯一命中）和 R4-F1（nav.js:883 的 showBanner 行，唯一命中）。P-5b 原段（`m.style.cssText = …z-index:200…`）在全仓找不到这一行，它已被 R2-3 取代，不执行。

重建方式：

- 取消分支：把 nav.js:877 拆成"条件行加 `{`、台账 `+` 段 5 行、`}`"。
- R3-3：把 :883-884 换成"showBanner、`if (!d2.ok)` 复位、catch 开头、catch 内复位、`}`"。

两处的 `+` 行都逐字取自台账。闭包变量 `m`（_renderState:843 的 `const m = j.meta || {}`）、`bkSel`、`v` 都能访问到，探针实际执行到了这些代码。

CDP 验证：把副本 nav.js 整体放进独立 target 执行，fetch 和 _ddConfirm 用桩替换，驱动真实的 onchange。

| 出口 | 基线下拉终值 | 终版下拉终值 |
|---|---|---|
| ① 确认时点取消 | sqlite（不回弹，复现 S-B1） | readtags ✓ |
| ② POST 返回 ok:false（:883） | sqlite | readtags ✓ |
| ③ fetch 抛错（:884 catch） | sqlite | readtags ✓ |
| ④ POST 成功后再改档并取消（R4-F1） | memory（显示与实际失步） | sqlite，即已切换成功的新档 ✓ |

z 序验证：调用真实的 _ddConfirm，同时打开索引面板，用 elementFromPoint 取确认框中心点。基线命中 navIdxPanel（z 200 < 9999，复现 C-2）；注入 R2-3 规则后命中 #ddcMsg（z 10001）✓。全仓 z-index 高于 10001 的只有 editor.js:2426 的调试探针（99999）；.ctx-menu 是 10000，index.html 里没有 5 位数的 z-index，所以不会出现层级倒挂。

注记：

- P-5 要靠 R2-3 才能让确认框可见，两者必须同批落。
- 复位表达式 `m.backend || (m.code_files >= 200000 ? …)` 在三处重复出现。R5F-2③ 已经撤回了合并方案，按现状保留。

### 2. P-11（S-B2）—— DIFF-MISMATCH

对不上的行：log:446 的 `-` 行尾注释写的是 `// a377`，而现状 editor.js:1885 是 `// a377：笔记编辑区同主题`。按意图重建（`+` 行逐字）之后，R2-4（log:872-874）逐字唯一命中。

CDP 验证：用真实的 buildEditorTab 建了 .note、.md、.py、.txt 四个 tab，分别调用基线和副本的 `_mdPvSetTheme('sepia', false)`。

| tab | 基线 | 终版 |
|---|---|---|
| .note | md-pv-sepia | md-pv-sepia |
| .md | md-pv-sepia | md-pv-sepia |
| .py | md-pv-sepia（泄漏，复现 S-B2） | 无 ✓ |
| .txt | md-pv-sepia（泄漏） | 无 ✓ |

工具栏下拉同步正常。另有三条注记：

- **缺 meta 时广播中断。** 往注册表里加一个缺 meta 的 conn 后，终版抛出 `TypeError: Cannot read properties of undefined (reading 'label')`，基线不抛。建议改成 `const isMd = !!(c && c.meta && (c.meta.label || '').toLowerCase().endsWith('.md'));`。
- **isMd 分支没有可见效果。** 在 .py 和 .md tab 的 .ed-scroll 上、中、下三个点做 elementFromPoint，命中的都是 monaco，因为 `.ed-holder:has(> .monaco-editor)` 用绝对定位把它整个盖住了；只有笔记 tab 命中 .ed-scroll 本身。所以 .md 挂不挂类在视觉上没有区别。广播之后新开的 .md tab 不挂类，和旧 tab 不一致，但同样看不出来。这一点无害，不必为它改代码。
- `+` 段的注释还写着"收敛到笔记 tab（conn.isNote…）"，加了 R2-4 之后已经不准确，落码时顺手改成"笔记 + .md"。

### 3. P-12（S-B4）—— DIFF-MISMATCH

对不上的行：

- log:477 的上下文 `if (!j.ok || !j.items) { ... return; }` 是省略写法，现状 nav.js:389-394 是一个 6 行的块。
- log:479 的 `-` 行是 `_full = j.items;`，现状 :396 后面还带着尾注释 `// R33-1：全量留底供本地过滤`。

重建方式：把 :395-397 这三行换成台账 `+` 段的 7 行。R33-1 那条尾注释会随之消失，需要保留的话手工补回。

作用域检查：`const q` 声明在 then 回调的块内，不会和 input handler 里的 q 冲突。`_full` 在 :401 用 `let` 声明，异步回调执行时它早已初始化，不存在暂时性死区问题。

CDP 验证：调用副本的 showFileSymbols，用闸门控制首次拉取何时 resolve，先输入过滤词再放行。

| 首拉前输入 | 基线行数 | 终版行数 |
|---|---|---|
| zzzz | 3（被全量覆盖，复现 S-B4） | 0 ✓ |
| al | 3 | 1（alpha）✓ |
| 空 | 3 | 3 ✓（空查询行为不变） |

### 4. P-14 族（S-B7）—— DIFF-MISMATCH

这一族共四个护栏：

- P-14 h1：_edJumpFresh 中 stat 之后。
- R3-4：_edReloadFromDisk 中 j2 之后。
- P-14 h2：monaco 分支内，按 R3-4 的决议保留。
- R4-F2：_edCheckDiskChanged 中 stat 之后。

对不上的行：

- log:535 的上下文是 `if (conn.editor) { ... }`，现状 editor.js:1214 是 `if (conn.editor) { conn.editor.render(content); }`。
- log:1127 的上下文是 `if (!j2.ok) { ... return; }`，现状 :1211 是一条完整的 showBanner 语句。

P-14 h1（:1243）和 R4-F2（:1169）逐字唯一命中。

CDP 验证：把三个函数从副本中抽出、改名后注入，外部依赖全部指向桩。在 fetch 的 await 窗口内删除注册项，并让 monaco/editor 抛出 disposed，以此模拟用户关掉 tab。

| 场景 | 基线 | 终版 |
|---|---|---|
| S1 _edJumpFresh，在 stat 窗口内关 tab | 仍然发出 open，弹 banner「重读失败: monaco disposed」 | 只发 stat，无 banner ✓ |
| S2 _edReloadFromDisk，在 open 窗口内关 tab（monaco） | 弹 banner「重读失败」 | 无 ✓ |
| S2b 同上，笔记（Editor.js） | 弹 banner「重读失败: editor destroyed」 | 无 ✓ |
| S3 _edCheckDiskChanged，在 stat 窗口内关 tab | 弹出"磁盘已改"选择框 1 次 | 0 次 ✓ |
| S4 对照：_edJumpFresh，tab 一直存活 | 重载、setValue('NEW')、banner「已重新加载」 | 相同 ✓ |
| S5 对照：_edCheckDiskChanged，tab 一直存活 | 弹框 1 次 | 相同 ✓ |

注记：P-14 h2 紧跟在 R3-4 之后，两者之间没有 await，所以 h2 永远不会触发，是一道冗余防御。按 R3-4 的决议保留，没有害处。

### 5. P-16（S-B9）—— APPLY-ISSUES

log:571-572 的 row.onclick 段在 nav.js:380 逐字唯一命中。Enter 分支只写了"（Enter 分支同款）"，没有给 diff，按方法论条文 2 应算作未落实。这次照 onclick 的同款变换（`openFileSmart(it.path, 'auto', ` → `_jumpOpen(ed, it.path, `）推导出来，施加在 :419。

CDP 验证：

- 点击和回车两条分支，基线的历史栈都是 `[]`，终版都是 `[from.c:7, 目标:行]`，selectLine 也保留了。
- ed 为 null（面板不是从编辑器打开）时不抛错，只把目标项入栈。
- 打开方式选"取消"（返回 'cancelled'）时不入栈，_jumpOpen 原有的语义保持不变。

建议在台账里补上 Enter 分支的逐字 diff，内容见附录 nav.js 的第 3 个 hunk。

### 6. P-21（S37-11+S-B6）—— DIFF-MISMATCH（update_server 段）

settings.js 部分：

- settings.js:1682（R3-5）逐字唯一命中。
- P-21 原来的 settings 段（裸 `${ICO16.dotOff}`）同样能命中基线，但它和 R3-5 互斥：先落哪一个，另一个就会 NO-MATCH。只落 R3-5。

update_server.py 部分：

- log:673-674 写的是"`1️⃣ → <b>1.</b>`""`⬇ → 删`"这样的规则描述，没有逐行的 `-/+`。
- 按规则重建后，改动恰好落在 :807、:828、:850、:1006、:1025 五行，py_compile 通过。
- `<b>1.</b>` 所在的 .mn-step 不在 .mn-card 里面，`.mn-card b{display:block}` 作用不到它，标题行的行内布局不变。

渲染验证：把副本 :1679-1682 的右值放到独立页里求值。未运行分支出现 dotOff SVG，颜色是 rgb(122,122,149)，即 --muted；运行分支的 dotOn 仍然是 --neon-green；文本里没有 emoji。

emoji 扫描（`\p{Emoji_Presentation}`、FE0F 序列、⬇/⚪）：

- update_server.py 从 5 处降到 0 处。
- settings.js 从 5 处降到 2 处。剩下两处是 :1851 和 :1902 注释里的 🧹，不会渲染，不在本补丁范围内。

### 7. P-22（S-B3）—— APPLY-ISSUES

editor.js:140 逐字唯一命中。终版下拉的 23 个 value 和 monaco.getLanguages() 返回的 91 个 id 对照，全部已注册，死项清零。新增的 HTML 注释写在模板串里，不含反引号和 `${`，node --check 通过。这段注释会进入每个编辑器 tab 的 DOM，但不影响功能。

问题：`hg-ed-lang-override` 里已经记成 makefile 的文件重新打开时，`sel.value='makefile'` 找不到对应选项，selectedIndex=-1，下拉显示空白；基线在这种情况下显示"Makefile"。高亮行为不变，因为 makefile 本来就没有高亮。

建议在同一批里给 editor.js:326 的记忆恢复处加兜底：值不在下拉选项里就按 null 处理，也就是回到"自动"。本机当前的 localStorage 里只有一条 shell 记忆，没有 makefile。

### 8. P-24（S-B5）—— APPLY-CLEAN

editor.js:154-155 逐字唯一命中，monaco 已注册 ruby。把下拉值设为 ruby 时，基线 selectedIndex=-1，显示空白；终版显示"Ruby" ✓。

### 9. P-25（S-B8）—— APPLY-CLEAN（按 R7-2 落）

R3-1 原文（log:1072-1075）的 `-` 段缩进比现状多 2 格，而且漏了 nav.js:633-634 的两行 R33-3 注释，所以对不上。R7-2（log:1672-1686）的 `-` 段 6 行和 nav.js:631-636 逐字吻合，`+` 段的逻辑和 R3-1 相同：`md.value = IIFE(...)` 整体赋值，并使用 `_m[0].length`。按 R7-2 落。

CDP 验证（markdown-it 就是页面实际加载的 CommonMark 实现）：

- **合成 8 个用例**：普通、3 连、4 连、5 连、行内 3 连、空、null、七连混排。终版全部得到"1 个 fence、路径行渲染为 code、标题只出现 1 次"。基线在 4 连和 5 连两个用例里出现 2 个 fence，路径行被吞掉，复现了 S-B8。
- **副本真函数 provideHover**：输入含 4 连反引号时，基线 fence 为 [4,4]，路径丢失；终版 fence 为 [5]，路径还在，标题只出现 1 次 ✓。
- **反例**：R2-1 的 `_m.length` 写法在所有用例里围栏长度都固定为 4，复现了 r2 指出的回归。

注记：R7-2 的 `+` 段删掉了 R3-1 自带的 4 行说明注释，R33-3 的旧注释也一起删了，落地后这段动态围栏没有任何注释。建议补一行"围栏长度 = snippet 内最长反引号串 + 1（CommonMark 闭合栏 ≥ 开栏）"。

### 10. P-26（D-3 附带）—— DIFF-MISMATCH

对不上的行：log:842 写的是 `function closeConnection(portId, ...) {`，现状 sidebar.js:113 是 `function closeConnection(portId) {`；log:851 的 `...原分发逻辑...` 是占位符。按"在函数头之后插入"的方式重建 R2-2 之后，R3-2（log:1096-1104）逐字唯一命中。

全仓 closeConnection 的调用点只有 sidebar.js:235 和 terminal-core.js:76。closeEditorTab 和 _edCloseNow 都不会回调 closeConnection，所以不会出现递归。

CDP 验证：

| 用例 | 基线 closeConnection | 终版 |
|---|---|---|
| edit: 笔记 tab | 发出 POST /api/disconnect（被桩拦截），不走 _edCloseNow | 转发给 closeEditorTab，不发 disconnect ✓ |
| edit: 代码 tab | 同上，monaco.dispose 调用 0 次 | 转发，dispose 调用 1 次 ✓ |

侧栏 ✕ 的实际路由：执行 refreshSidebar 之后点击真实按钮，监视实际调用了哪个函数。

| tab 类型 | 实际调用 | 终版守卫 | 资源释放 |
|---|---|---|---|
| edit（.py） | closeEditorTab | 不经过守卫 | 完整 |
| office（伪造的 conn，挂了 _pdfTask 桩） | closeConnection | 正则不含 office，放行 | _pdfTask.destroy 调用 0 次 ✗ |
| bitcalc（真实 tab） | closeConnection | 放行 | 没有专属资源，只是多发一个 404 的 disconnect |

结论：守卫按设计生效，但它守的四类 tab 本来就被 sidebar.js:198/:233 分流走了。真正走 closeConnection、又漏掉 dispose 的是 office，因为 _dsEditor、_pdfTask、_pdfIO、_outlineRO 只在 _edCloseNow 里释放。建议二选一：

- 在正则里补上 `office|bitcalc|proxy`；
- 或者在 sidebar.js:198 的 isEdit 判断里加入这三类。后者修的才是真实路径。

另外，R2-2 三行头注释里的第三行"（编辑器 _edCloseNow 的完整 dispose）=5 倍泄漏…"是改写后残留的半句，落码时把它和前两行合成一句。

### 11. R4-F1 —— APPLY-CLEAN（R7-1 不得再落）

log:1412-1417 在 nav.js:883 逐字唯一命中，第 4 出口的探针结果 PASS（见第 1 件表格第④行）。

重复应用检测：R4-F1 落地之后，R7-1（log:1658-1663，和 R4-F1 逐字节相同）的 `-` 行仍然唯一命中（:893）。再落一次，`if (d2.ok) m.backend = v;` 就会出现 2 次，而 node --check 照样通过。证据副本是 out\idem\nav.dup_R7-1.js。

### 12. R2-3 附带（settings.js:788/:1661）—— APPLY-CLEAN

r3 报告 :134-135 和 :142-143 两段的 `-` 行，分别和 settings.js:788（10 空格缩进，在模板串内）、:1661（4 空格缩进，单引号字符串）逐字唯一命中。落地后再施加一次是 NO-MATCH，可以安全重复执行。

注意：r3 报告 :132-147 的 ```diff 围栏里夹着说明文字（:136-139、:144-146），整块交给 `git apply` 会失败，只能取出其中两段 hunk。⬇ 的 Emoji_Presentation 判定见第一节末尾的更正。

---

## 四、合并冲突检查

1. **nav.js（P-5、P-12、P-16、P-25，加上 R3-3、R4-F1）**：改动区为 :380、:395-397、:419、:631-636、:876-884，互不重叠。正序和逆序叠加后的终态 SHA256 一致（543d2bcc…），四件分别单独落到基线也都通过。唯一共用的锚点是 :883 的 showBanner 行：R4-F1 在它前面插入，R3-3 在它后面插入，两种顺序结果一致。
2. **editor.js（P-11、P-14、P-22、P-24）**：改动区为 :140、:154-155、:1168-1251、:1884-1885，互不重叠。正逆序终态一致（a9c4492d…），每件都能单独落。P-14 内部 R3-4 和 h2 相邻但不冲突，h2 是冗余护栏（见第 4 件）。
3. **跨文件依赖**：
   - P-5（nav.js）在功能上依赖 R2-3（style.css），必须同批落。
   - P-26 运行时依赖 editor.js 里已有的 closeEditorTab。
   - P-14 的护栏依赖 _edCloseNow 里的 `delete connections[...]`。两条关闭路径都会删除注册项，所以护栏在两条路径上都有效。
4. **重复应用**：把 14 段终版原文对终态副本再施加一次，只有 R4-F1 和 R7-1 会再次命中（重复执行会二次插入），其余 12 段都是 NO-MATCH。
5. **取代关系**：
   - P-5b 原段被 R2-3 取代。
   - P-21 原 settings 段和 R3-5 互斥。
   - R2-1 和 R3-1 被 R7-2 取代。
   - R2-2 原文里的 closeHexTab 行被 R3-2 取代（closeHexTab 在全仓不存在）。
   
   这些被取代的段落码时一律跳过。
6. **行号漂移**：落地后 editor.js 从 :140 往下整体后移 3 行，从 :155 往下再后移 1 行；nav.js 从取消分支往下后移 6 行。台账里"editor.js:1183 之前""nav.js:883/:884"这类行号引用，对已落码的文件不再成立，必须按内容锚点落。

---

## 五、应用顺序与分批建议

**应用顺序**：按文件分组，按内容锚点落。本次正序就是这个顺序，逆序已验证结果相同。

1. web/style.css：R2-3
2. web/js/nav.js：P-5 取消分支 → R3-3 → R4-F1（只落一次）→ P-12 → P-16（onclick 和 Enter）→ P-25（R7-2）
3. web/js/editor.js：P-11 → R2-4 → P-14 h1 → P-14 h2 → R3-4 → R4-F2 → P-22 → P-24
4. web/js/sidebar.js：R2-2（重建的头部）和 R3-2 合成一段
5. web/js/settings.js：R3-5 → r3:788 → r3:1661
6. src/update_server.py：五行规则替换

最省事的办法是直接用附录的统一 diff，一次 `git apply` 落完 6 个文件，已经用 `--check` 验证过可用。

**分批建议**：

| 批次 | 补丁 | 理由 |
|---|---|---|
| 立即 | R2-3 + P-5（含 R3-3，R4-F1 只落一次）、P-12、P-14 族、P-16、P-24、P-25（R7-2）、P-21 全部、R2-3 附带 | 行为探针全部通过，基线缺陷消除，没有回归。P-5 和 R2-3 同批 |
| 谨慎（同批带小修） | P-22（加记忆值兜底）、P-11/R2-4（加 `c.meta` 判空并改注释）、P-26（补 office 覆盖或改侧栏分流，整理注释） | 都能落，也没有即时风险，但各有一处边缘回归、潜在异常或覆盖缺口，建议落码时一起修掉 |
| 暂缓 / 不执行 | R7-1（R4-F1 的重复记载）、P-5b 原段、P-21 原 settings 段、R2-1/R3-1 原文、R2-2 原文中的 closeHexTab 行 | 已被取代或属于重复记载，执行会导致二次插入或找不到锚点 |

---

## 六、方法与可复核产物

所有产物都在 `%TEMP%\patch_apply_fe\`，即 `C:\Users\gaoyi13\AppData\Local\Temp\patch_apply_fe\`。

- **`base\`**：六个目标文件的原样副本，SHA256 和真实文件一致；另有 patch-log 和 r3 报告的副本。
- **`scripts\apply_fe.py`**：应用引擎。先做严格的逐字唯一命中，失败时记录逐行诊断，再做意图重建。支持 fwd、rev、iso 三种模式，每步跑 node --check 或 py_compile，并保留原文件的行尾格式（editor.js 是 LF，其余是 CRLF）。
- **`out\fwd\`、`out\rev\`、`out\iso\`**：逐步副本（`<文件>.<步号>.<补丁>.*`）、终态文件 `final_*`，以及记录每个 hunk 命中行和诊断信息的 `report.json`。
- **`out\frontend_final.patch`**：仓库相对路径的统一 diff，保留 CRLF。`git apply --check` 6/6 通过。去掉 CR 的 `frontend_final.lf.patch` 在本仓库（core.autocrlf=true）下同样通过，退出码都是 0。
- **`out\idem\`**：重复应用的证据文件 nav.dup_R4-F1.js 和 nav.dup_R7-1.js。
- **`scripts\probe_*.mjs` 和 `out\probe_*.json`**：CDP 探针脚本和结果。
- **CDP 隔离措施**：
  - 所有探针都在用 `/json/new` 新开的独立 target 上运行，用完已关闭。
  - 副本函数改名为 `__B_*`、`__P_*` 后注入，不覆盖页面原有函数。
  - 非 GET 请求全部拦截：5 次 POST /api/disconnect 都被桩截获，没有真正发出。放行的只有只读 GET（/api/status、/api/theme）。
  - 用户原来的页面（4C4ADC23…）只做过两次只读 evaluate：开头取一次状态，结尾核对一次。核对结果是页面上没有注入残留，z-index 仍然是 200。

---

## 附录：落码用统一 diff

下面是 `out\frontend_final.patch` 去掉 CR 后的显示版，在本仓库根目录 `git apply --check` 通过。落码后建议核对新增行的行尾格式和所在文件一致：nav/settings/sidebar/style/update_server 是 CRLF，editor.js 是 LF。

`````diff
diff --git a/src/update_server.py b/src/update_server.py
index 59c65c1..bcc5bfb 100644
--- a/src/update_server.py
+++ b/src/update_server.py
@@ -804,7 +804,7 @@ _PORTAL_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
     </div>
     <div class="mn-sec"><b>快速上手 · 三个配置</b></div>
     <div class="mn-step">
-      <div class="mn-step-t">1️⃣ 接入 Claude Code —— 让 AI 在工具里跑起来</div>
+      <div class="mn-step-t"><b>1.</b> 接入 Claude Code —— 让 AI 在工具里跑起来</div>
       <svg class="mn-svg" viewBox="0 0 720 96" xmlns="http://www.w3.org/2000/svg">
         <defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="0">
           <stop offset="0" stop-color="#4f8fff"/><stop offset="1" stop-color="#8957e5"/></linearGradient></defs>
@@ -825,7 +825,7 @@ _PORTAL_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
       <b>提示：</b>工具页左下角有「Claude」状态徽章，绿色=通道就绪。之后每个会话页签就是一个独立 AI，互不干扰。</p>
     </div>
     <div class="mn-step">
-      <div class="mn-step-t">2️⃣ 配置识图 —— 让 AI 看懂你的截图</div>
+      <div class="mn-step-t"><b>2.</b> 配置识图 —— 让 AI 看懂你的截图</div>
       <svg class="mn-svg" viewBox="0 0 720 96" xmlns="http://www.w3.org/2000/svg">
         <rect x="10" y="18" width="170" height="56" rx="10" fill="none" stroke="#4f8fff" stroke-width="1.5"/>
         <rect x="30" y="30" width="44" height="32" rx="4" fill="none" stroke="#4f8fff" stroke-width="1.2"/>
@@ -847,7 +847,7 @@ _PORTAL_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
       <b>用法：</b>把截图拖进会话输入框（或粘贴），AI 直接分析图内内容。</p>
     </div>
     <div class="mn-step">
-      <div class="mn-step-t">3️⃣ 配置三角色 —— AI 分身帮你干活</div>
+      <div class="mn-step-t"><b>3.</b> 配置三角色 —— AI 分身帮你干活</div>
       <svg class="mn-svg" viewBox="0 0 720 110" xmlns="http://www.w3.org/2000/svg">
         <rect x="10" y="10" width="200" height="40" rx="8" fill="none" stroke="#4f8fff" stroke-width="1.5"/>
         <text x="110" y="35" text-anchor="middle" fill="currentColor" font-size="12">主会话（调度+干活）· 模型槽 A</text>
@@ -1003,7 +1003,7 @@ async function load(){
       +(top.sha1?'<span class="sha" title="'+esc(top.sha1)+'">sha1 '+esc(top.sha1.slice(0,12))+'…</span>':'')+'</div>'
       +(top.notes?mdRender(top.notes,'notes')
         :'<div class="notes plain" style="color:var(--muted)">（本版未写更新说明——发布者在项目根 RELEASE_NOTES.md 写好后重新打包，说明会随版本带上）</div>')
-      +'<div class="row"><button class="btn" data-dl="'+top.url+'" data-n="'+esc(top.file)+'">⬇ 下载整包</button>'
+      +'<div class="row"><button class="btn" data-dl="'+top.url+'" data-n="'+esc(top.file)+'">下载整包</button>'
       +'<span data-dlst style="font-size:12px;color:var(--muted)">下载后解压即完成安装</span></div></div>';
     // 离线资源包独立卡片（用户定调「离线包和实际包分开」）：不是应用版本，
     // 不占 hero、不进更新日志；包名不带版本号——内容与工具版本无关
@@ -1022,7 +1022,7 @@ async function load(){
           ? '<br><b style="color:#e8a33d">这是派生/留档包（副本、改名版本或备份），可能不是最新完整包</b>'
           : '')
         +'</div></div>'
-        +'<button class="btn" data-dl="'+esc(j.offline.url)+'" data-n="'+esc(j.offline.file)+'" style="flex-shrink:0">⬇ 下载'+(j.offline.format==='fcpk'?'资源包':'离线包')+'</button></div>';
+        +'<button class="btn" data-dl="'+esc(j.offline.url)+'" data-n="'+esc(j.offline.file)+'" style="flex-shrink:0">下载'+(j.offline.format==='fcpk'?'资源包':'离线包')+'</button></div>';
     }
     const rest=j.items.slice(1);
     if(rest.length){
diff --git a/web/js/editor.js b/web/js/editor.js
index 85e8289..fe62355 100644
--- a/web/js/editor.js
+++ b/web/js/editor.js
@@ -137,7 +137,10 @@ function buildEditorTab(name, content, extPath, fileMtime, draftExt) {
           <option value="python">Python</option>
           <option value="c">C</option>
           <option value="cpp">C++</option>
-          <option value="makefile">Makefile</option>
+          <!-- S-B3（P3）：vendored Monaco 0.52 无 makefile 语言注册（getLanguages
+               91 id 实证）——选项保留即"死项"（选了=无高亮与纯文本不可区分）。
+               长期方案：vendor 补第三方 makefile Monarch 包（与 cpp/shell 补丁
+               同目录登记"升级重拷需重打"）；短期撤项自洽 -->
           <option value="javascript">JavaScript</option>
           <option value="typescript">TypeScript</option>
           <option value="json">JSON</option>
@@ -152,6 +155,7 @@ function buildEditorTab(name, content, extPath, fileMtime, draftExt) {
           <option value="bat">Batch</option>
           <option value="powershell">PowerShell</option>
           <option value="perl">Perl</option>
+          <option value="ruby">Ruby</option>
           <option value="lua">Lua</option>
           <option value="markdown">Markdown</option>
           <option value="ini">INI</option>
@@ -1167,6 +1171,7 @@ async function _edCheckDiskChanged(conn) {
       : '/api/ed/stat?name=' + encodeURIComponent(conn.meta.label);
     const r = await fetch(q);
     const j = await r.json();
+    if (connections[conn.portId] !== conn) return;   // R4-F2：stat 窗口内关 tab
     if (!j.ok) {
       // 文件被外部删除/不可访问：一次性提示（不弹选择——没有可重载的东西）
       if (conn.fileMtime && !conn._fileGoneWarned) {
@@ -1209,10 +1214,12 @@ async function _edReloadFromDisk(conn) {
     const r2 = await fetch(oq);
     const j2 = await r2.json();
     if (!j2.ok) { showBanner('重读失败：' + (j2.err || ''), 4000, true); return; }
+    if (connections[conn.portId] !== conn) return;   // R3-4：open 窗口内关 tab
     let content = j2.text;
     if (conn.isNote) { try { content = JSON.parse(j2.text); } catch(_) { content = { blocks: [] }; } }
     if (conn.editor) { conn.editor.render(content); }
     else if (conn.monaco) {
+      if (connections[conn.portId] !== conn) return;   // disposed 防护
       const pos = conn.monaco.getPosition();
       conn.monaco.setValue(j2.text);
       try { conn.monaco.setPosition(pos); conn.monaco.revealLineInCenter(pos.lineNumber); } catch(_) {}
@@ -1241,6 +1248,7 @@ async function _edJumpFresh(conn) {
     const r = await fetch('/api/ed/stat?path=' + encodeURIComponent(conn.extPath));
     const j = await r.json();
     const changed = !!(j.ok && Math.abs(j.mtime - conn.fileMtime) >= 0.001);
+    if (connections[conn.portId] !== conn) return;   // S-B7：跳转窗口内 tab 已关
     if (!changed) return;
     if (!conn.dirty) { await _edReloadFromDisk(conn); return; }
     if (!conn._jfWarned) {
@@ -1882,7 +1890,14 @@ function _mdPvApplyTheme(pv) {
 window._mdPvSetTheme = (t, persist) => {
   _mdPvTheme = t;
   document.querySelectorAll('.ed-md-preview').forEach(_mdPvApplyTheme);
-  document.querySelectorAll('.ed-scroll').forEach(_mdPvApplyTheme);   // a377：笔记编辑区同主题
+  // S-B2（P3）：.ed-scroll 是所有编辑器形态共有的滚动容器——全量广播把
+  // 预览配色染到代码/文本 tab（且新开 tab 不受影响=tab 间不一致）。
+  // 收敛到笔记 tab（conn.isNote 的 wrap 才有 .ed-scroll 主题消费语义）
+  document.querySelectorAll('.term-area').forEach(w => {
+    const c = connections[w.dataset.portId];
+    const isMd = c && (c.meta.label || '').toLowerCase().endsWith('.md');
+    if (c && (c.isNote || isMd)) { const sc = w.querySelector('.ed-scroll'); if (sc) _mdPvApplyTheme(sc); }
+  });
   // 同步所有工具栏下拉
   document.querySelectorAll('[data-ed-mdtheme]').forEach(sel => { sel.value = t; });
   if (persist !== false) {
diff --git a/web/js/nav.js b/web/js/nav.js
index c07f06e..6e8e11e 100644
--- a/web/js/nav.js
+++ b/web/js/nav.js
@@ -377,7 +377,7 @@
         const ln = _h('span', ':' + (it.line || 1));
         ln.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--muted);flex-shrink:0;';
         row.appendChild(k); row.appendChild(n); row.appendChild(ln);
-        row.onclick = () => { _closeSym(); openFileSmart(it.path, 'auto', { line: Math.max(1, it.line || 1), col: 1, selectLine: true }); };
+        row.onclick = () => { _closeSym(); _jumpOpen(ed, it.path, { line: Math.max(1, it.line || 1), col: 1, selectLine: true }); };
         list.appendChild(row);
         rows.push(row);
       });
@@ -392,8 +392,12 @@
           list.appendChild(d);
           return;
         }
-        all = j.items;
-        _full = j.items;   // R33-1：全量留底供本地过滤
+        // S-B4（P3）：resolve 前用户已输入的过滤词被全量覆盖——渲染统一走
+        // 过滤通道（与 input handler 同口径）
+        _full = j.items;
+        const q = input.value.trim().toLowerCase();
+        all = q ? _full.filter(it => it.name.toLowerCase().includes(q)) : _full;
+        selIdx = 0;
         render();
       }).catch(() => {});
     // R33-1（实锤：每键打后端，110MB 库每发 0.5-2.2s）：首拉已取全量
@@ -416,7 +420,7 @@
         e.preventDefault();
         const it = all[selIdx];
         _closeSym();
-        openFileSmart(it.path, 'auto', { line: Math.max(1, it.line || 1), col: 1, selectLine: true });
+        _jumpOpen(ed, it.path, { line: Math.max(1, it.line || 1), col: 1, selectLine: true });
       }
     });
   }
@@ -628,12 +632,15 @@
         if (!j || !j.candidates || !j.candidates.length) return null;
         const c = j.candidates[0];
         const md = { value: '' };
-        md.value = '**' + word.word + '** `' + (c.kind || 'symbol') + '`' +
-          (c.in_build === true ? ' ✓编译内' : '') + (c.file_local ? ' ·本文件' : '') + '\n\n' +
-          // R33-3（实锤：snippet 内 0 缩进裸 ``` 截断代码块——CommonMark
-          // 闭合栏不得长于开栏）：四反引号围栏，源码内 ``` 无法误闭合
-          '````\n' + (c.snippet || '') + '\n````\n\n' +
-          '`' + c.rel + ' :' + c.line + '`';
+        md.value = ((_s) => {
+          let _max = 3;
+          for (const _m of _s.matchAll(/`+/g)) _max = Math.max(_max, _m[0].length);
+          const _f = '`'.repeat(_max + 1);
+          return '**' + word.word + '** `' + (c.kind || 'symbol') + '`' +
+            (c.in_build === true ? ' ✓编译内' : '') + (c.file_local ? ' ·本文件' : '') + '\n\n' +
+            _f + '\n' + _s + '\n' + _f + '\n\n' +
+            '`' + c.rel + ' :' + c.line + '`';
+        })(String(c.snippet || ''));
         return { range: new monaco.Range(position.lineNumber, word.startColumn,
                                          position.lineNumber, word.endColumn),
                  contents: [{ isTrusted: false }, md] };
@@ -874,14 +881,27 @@
       if (typeof _ddConfirm === 'function' &&
           !(await _ddConfirm('切换查询模式', v === 'sqlite'
             ? '构建 sqlite 快查索引（大库约 1 分钟，一次性；查询 0~4ms/内存 ~50MB）？'
-            : `切到 ${v} 模式（删除 tags.db 立即生效）？`))) { _renderState(card, path, j, st); return; }
+            : `切到 ${v} 模式（删除 tags.db 立即生效）？`))) {
+        // C-2+S-B1：①_renderState 二次调用命中死节点（btns 捕获 div:last-child
+        // 落进 st 内部行）——改直接复位下拉；②弹窗 z=200 被面板 z=9999 遮挡
+        // （见 P-5b 的 CSS 补丁），此处只需复位显示态
+        bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));
+        return;
+      }
       try {
         const r = await fetch('/api/nav/reindex', { method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify({ root: path, backend: v }) });
         const d2 = await r.json();
+        if (d2.ok) m.backend = v;   // R4-F1：第 4 失步出口——前瞻同步显示态。
+                                    // 切档无 poll 轮询（/api/nav/poll 仅建索
+                                    // 引流消费）；任务异步失败由索引面板重开
+                                    // （按 meta 渲染）兜底显示回归
         showBanner(d2.ok ? '查询模式切换中（任务槽执行）' : ('切换失败：' + (d2.err || '')), 3000, !d2.ok);
-      } catch (e) { showBanner('切换失败: ' + e, 3000, true); }
+        if (!d2.ok) bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));   // R3-3：:883 出口
+      } catch (e) { showBanner('切换失败: ' + e, 3000, true);
+        bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));   // R3-3：:884 catch 出口
+      }
     };
     btns.insertBefore(bkSel, btns.lastChild);
     const bDel = _h('button', ICO16.trash + ' 删除索引', true);
diff --git a/web/js/settings.js b/web/js/settings.js
index 1191954..649867d 100644
--- a/web/js/settings.js
+++ b/web/js/settings.js
@@ -785,7 +785,7 @@ async function _stRenderResourcesPane(pane) {
         </label>
         <div class="dd-actions" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
           <button class="btn primary" id="rsGo" disabled><span>${ICO16.wrench}</span> 离线包安装所选</button>
-          <button class="btn ghost" id="rsOnlineGo" disabled title="">⬇ 在线安装所选</button>
+          <button class="btn ghost" id="rsOnlineGo" disabled title="">在线安装所选</button>
           <button class="btn ghost" id="rsCancel" style="display:none;">■ 取消</button>
         </div>
         <div class="dd-sub" id="rsNetInfo" style="display:none;margin-top:6px;">—</div>
@@ -1658,7 +1658,7 @@ async function _stRenderUpdatePane(pane) {
   async function _stDoApply(res) {
     const ok = await _ddConfirm('升级确认', '下载并校验通过后，工具将自动重启完成升级（黑窗一闪属正常）。\n继续？');
     if (!ok) return;
-    res.innerHTML = '<div class="dd-sub">⬇ 下载并校验中…（内网一般几秒，完成后自动重启）</div>';
+    res.innerHTML = '<div class="dd-sub">下载并校验中…（内网一般几秒，完成后自动重启）</div>';
     try {
       const j = await (await fetch('/api/update/apply', {method: 'POST'})).json();
       if (!j.ok) { res.innerHTML = '<span style="color:var(--neon-red,var(--neon-orange));">' + esc(j.err || '升级准备失败') + '</span>'; return; }
@@ -1679,7 +1679,7 @@ async function _stRenderUpdatePane(pane) {
       $p('upSrvInfo').innerHTML = j.running
         ? `<span style="color:var(--neon-green);vertical-align:-2px">${ICO16.dotOn}</span> 运行中 · 已发布 <b>${esc(j.published || '（无版本——先跑打包.bat）')}</b>${ver}<br>` +
           `同事升级地址（发给同事）：<span style="font-family:var(--font-monospace,monospace);user-select:all;">${esc(j.url)}</span>`
-        : `⚪ 未运行 · 分发目录 ${esc(j.dir)}${ver}`;
+        : `<span style="color:var(--muted);vertical-align:-2px">${ICO16.dotOff}</span> 未运行 · 分发目录 ${esc(j.dir)}${ver}`;
     } catch(_) { $p('upSrvInfo').textContent = '状态获取失败'; }
   }
   $p('upSrvToggle').onclick = async () => {
diff --git a/web/js/sidebar.js b/web/js/sidebar.js
index f2c7103..53e984f 100644
--- a/web/js/sidebar.js
+++ b/web/js/sidebar.js
@@ -111,6 +111,14 @@ async function connectTelnet(host, port, quiet) {
 }
 
 function closeConnection(portId) {
+  // D-3（P3）附带防御：直调 closeConnection 绕过编辑器完整 dispose 链
+  // （hex/diff/bindiff 无专属关闭函数——四类统一转发，sidebar.js:198/:233 实证）
+  // （编辑器 _edCloseNow 的完整 dispose）=5 倍泄漏（3.1MB/次 vs 0.58MB）
+  if (/^(edit|hex|diff|bindiff):/.test(portId) &&
+      typeof closeEditorTab === 'function') {
+    closeEditorTab(portId); return;   // 产品路径四类统一走 closeEditorTab
+                                      // （sidebar.js:198/:233 实证）
+  }
   fetch('/api/disconnect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId})});
   const conn = connections[portId];
   if (conn) {
diff --git a/web/style.css b/web/style.css
index b7ed35c..7e5e7a1 100644
--- a/web/style.css
+++ b/web/style.css
@@ -2132,7 +2132,8 @@
 .dd-note { font-size: 11px; color: var(--muted); line-height: 1.6;
   border-top: 1px solid var(--border); padding-top: 10px; }
 /* 确认/进度弹窗叠在数据目录面板之上（modal 默认 z-index 相同，后挂的 DOM 靠后渲染仍被遮） */
-#ddConfirmModal, #ddProgressModal { z-index: 200; }
+#ddConfirmModal, #ddProgressModal { z-index: 10001; }   /* C-2：索引面板 9999 之上
+                                                          ——两条 ID 同提防倒挂（r1 建议保持同层） */
 /* 迁移进度面板：环形动画 */
 .dd-prog .dd-prog-body { padding: 28px 24px; display: flex; flex-direction: column;
   align-items: center; gap: 12px; text-align: center; }
`````
