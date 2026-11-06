# 补丁审计报告 R2 · 前端组（白盒）

> 审计对象：doc/patch-log.md【第 2 轮修订】前端重写/补强项（R2-1 ~ R2-7），另核 r1 前端 PASS with notes 的吸收完整性。
> 审计方法：①源码现状逐行核对（锚点漂移必查——r1 教训：伪 diff 锚点不存在）②node 实证（脚本落系统 TEMP，未入仓库；字面应用语义推演 + 修正形态三/四用例回归）③转发链/时序/作用域白盒推演 ④r1 裁决与 r1 新发现 7 条的吸收核对。
> 本文件只裁决补丁提案，未修改任何工具源码。源码基线核对：web/ 与 HEAD 一致（git status 仅 doc/ 未跟踪），r1 所见行号本轮全部复现，无锚点漂移。

---

## 结论先行

**7 件：PASS 2 · PASS with notes 4 · FAIL 1。**

| 修订项 | 对应补丁 | 裁决 | 一句话 |
|---|---|---|---|
| R2-1 | P-25 重写 | **FAIL** | 锚点行吻合但结构声称与 diff 自相矛盾：字面应用=标题头重复复发（node 实证）+ `_m.length` 恒 1 使动态围栏失效（S-B8 未修复）+ "r1 已实证该结构"引注不实 |
| R2-2 | P-26 重写 | **PASS with notes** | 位置/转发目标/单路径/前缀矩阵全对；但 closeHexTab **不存在**（死代码），"同族专属链存在"注释失实——r1 留的核对点答案是：四类无专属函数，统一 closeEditorTab |
| R2-3 | P-5 补强 | **PASS with notes** | z 同提对迁移进度弹窗的连带影响核实为安全；失败分支复位需覆盖**两个出口**（d2.ok false + catch），_curBk 建议仍未吸收 |
| R2-4 | P-11 补强 | **PASS** | isMd 口径与 buildEditorTab（editor.js:226/295）一致；connections 同步注册复核成立；其他 tab 族无 .ed-scroll 双保险无误伤 |
| R2-5 | P-14 补强 | **PASS with notes** | 方向全对，但"函数头一行"≠ r1 建议位（j2 之后）——_edReloadFromDisk 自身 open 窗口内关 tab 仍裸奔（S-B7 主场景之一残留）；"上移"措辞有撤掉 monaco 分支护栏的风险 |
| R2-6 | P-21 补强 | **PASS with notes** | audit-b:187 勘误方向正确但被推迟且未列入第 3 轮范围清单；r1 的 dotOff 包装 span 对齐缺口**完全未被吸收**（本轮最大漏项） |
| R2-7 | P-22 补强 | **PASS** | monaco-bridge.js:22/:41 逐字核实存在，补记到位；落地时建议把 :41 写进 P-22 注释本体 |

---

## 逐件裁决详情

### R2-1（P-25 重写：hover 动态围栏 IIFE 整体替换版）—— **FAIL**

**① 是否正确解决问题 —— 否（双重失效，node 实证）**

- **锚点现状**：nav.js:631-636 为 `md.value = '**' + word.word + ... + '\n\n' +`（:631-632 标题头两行）+ R33-3 注释（:633-634）+ `'````\n' + (c.snippet || '') + '\n````\n\n' +`（:635）+ `'` + c.rel + ' :' + c.line + '`';`（:636）。R2-1 diff 的两行 `-` 与 ：635-636 **逐字吻合**（锚点本身无漂移）。
- **缺陷 A——结构声称与 diff 自相矛盾，标题头重复复发**。台账括注称"整个模板表达式替换为单个 IIFE 调用——首尾原行一并删除，不再有拼接残段"，但 diff 的 `-` 段只含 ：635-636 两行，**:631-632 标题头两行未被删除**。字面应用结果为：
  ```js
  md.value = '**' + word.word + ... + '\n\n' + ((_s) => { ... return '**' + word.word + ...; })(String(c.snippet || ''));
  ```
  IIFE 返回值自带完整标题头 → node 运行实证：**标题头 `**foo** \`func\` 出现 2 次**，与 r1 对原 P-25 的 FAIL 发现完全同型——静默损坏（node --check 通过）。
- **缺陷 B——`_m.length` 语义回归，动态围栏失效**。R2-1 把原 P-25 正确的 `m[0].length` 改成了 `_m.length`：`matchAll(/`+/g)` 的匹配对象是数组，无捕获组时 `length` **恒为 1**（node 实证：`_m.length=1` vs `_m[0].length=4`）。结果 `_max` 恒为 3、围栏恒 4 反引号——含 4 连反引号行的 snippet（S-B8 主场景）产出 4 长围栏，闭合栏 ≥ 开栏即可闭合，**S-B8 未被修复**。
- **"善意解读"也不成立**：若按"整个赋值语句替换"应用（:631-636 全删），`+` 段缺 `md.value = ` 前缀 → IIFE 返回值被丢弃，`md.value` 恒为 ：630 初始化的空串 → hover 内容空白。
- **不实引注**：括注称"审计员 r1 已用该结构 node 三用例实证"——**失实**。r1 的 node 三用例实证的是**语句前置版（无 IIFE）**；对 IIFE 版 r1 只给了结构要求（"必须让它替换整个赋值语句"），未做运行实证。R2-1 把 r1 的背书错安在这个（未实证且错误的）结构上。

**② 是否引入新问题**：三处——①:631-632 残留拼接（重复标题头）；②`_m.length` 回归（原 P-25 尚且正确）；③台账引注失实会误导第 3 轮复核基线。

**③ 是否遗漏更优方案**：是——r1 已给出且已 node 实证的**语句前置版（无 IIFE）**被放弃。本轮复核重跑修正形态 4 用例（普通 snippet / 4 连反引号行 / 空 snippet / 8 连反引号串）：围栏恒 > 内容最长反引号串（4/5/4/9）、标题头唯一、语句版与正确接线的 IIFE 版（`md.value = ((...)=>{...})(...)` + `_m[0].length`）逐字节等价，ALL PASS。第 3 轮修订建议直接采用语句前置版（provideHover 的 `.then` 回调是函数体，普通语句合法），如坚持 IIFE 则必须：删 ：631-636 全部 + `+` 段以 `md.value = ` 开头 + `_m.length` 改回 `_m[0].length`。

---

### R2-2（P-26 重写：sidebar.js:113 closeConnection 头部防御 + kind 列表）—— **PASS with notes**

**① 是否正确解决问题 —— 是（主体成立）**

- **现状核对（任务指定点①）**：`closeConnection` 真身 **sidebar.js:113** `function closeConnection(portId) {`——**单参数**。diff 上下文行的示意签名 `(portId, ...)` 与实际不符（落地无碍，记一笔）；"函数头部——分发逻辑之前插入"的插入点成立（:114 起）。函数体确无任何 `edit:` 前缀判定/kind 分支（r1 结论复核成立），kind 分发在 sidebar.js:228-238（isLog/isEdit/isHarness/else 四路）。
- **转发目标核实**：`closeEditorTab`（editor.js:1384，顶层 async function，经典脚本全局）存在且被 sidebar.js:233 直接调用（同文件先例）。`_edCloseNow`（editor.js:1427-1520）对四类的完整 dispose 链齐备：editor.destroy(:1436)/monaco.dispose(:1438)/model dispose(:1446-1457)/_docKey/_dvKey/_bdKey/_hxUp 摘除(:1465-1468)/_hxAbort(:1470)/diffEd dispose(:1472-1478)，dirty 确认(:1387-1393)与剩余 tab 激活逻辑(:1498-1518，含 _hgTabBack 回来路)与 closeConnection 的同款段(:144-160)语义等价——**转发后无双执行（return 单路径，任务指定点③成立）**，跳过 `/api/disconnect`（edit 族必 404）与 `refreshGlobalStatus`（产品关闭路径本就不调，editor.js:1519 只 refreshSidebar）均为改善，与 r1 ② 一致。
- **portId 前缀矩阵复核（任务指定点④）**：`edit:`(editor.js:94)/`hex:`(hex-viewer.js:32)/`diff:`(diff-viewer.js:174)/`bindiff:`(hex-diff.js:205)/`log:`(log-viewer.js:117)——与 r1 矩阵逐一吻合。正则 `/^(edit|hex|diff|bindiff):/` 无误伤（`editor:`/`harness:`/`log:` 等均不命中；交替次序与 `:` 锚定已推演）。
- **产品路径零回归**：closeConnection 全仓仅两个调用点——sidebar.js:235（非 isLog/isEdit/isHarness 分支）与 terminal-core.js:76（终端 tab ✕），均不传四类前缀；防御性定位（防外部直调）与 D-3 原文口径一致。

**② 是否引入新问题 —— 一处死代码 + 一处失实注释**

- **`closeHexTab` 不存在**：全仓 grep（web/js 全文件 + html）零命中。该行 `typeof closeHexTab === 'function'` 恒 false = **不可达死代码**。
- **注释依据失实**：`// diff/bindiff 关闭函数名按现文件核（r1 审计员：同族专属链存在）`——r1 从未声称存在独立专属函数；r1 ③ 给出的正是"`connections[portId].meta.kind ∈ {editor,hex,diff,bindiff}` → 统一 closeEditorTab"，并明说"专属清理段在 _edCloseNow 内部(:1468-1478)"。**r1 留的核对点（任务指定点②）答案：hex/diff/bindiff 无专属关闭函数，产品路径四类统一走 closeEditorTab（sidebar.js:198 isEdit 定义 + :233 分发）**。第 3 轮定稿应删 closeHexTab 行与该注释（保留首行 closeEditorTab 转发即可——正则已覆盖四类，单转发路径天然完整）。

**③ 更优方案**：r1 原案（conn.meta.kind 判定）与前缀正则均可；正则连未注册 id 也拦截，无优劣差。新发现：hex-diff.js:180 有瞬态 `bindiff:loading:*` tab（不入 connections、自有 onclick 自毁）也命中正则——转发后 closeEditorTab :1386 `if (!conn) return` 静默返回，安全且比现状（直调会重置 termArea 空态+侧栏）更保守，仅记录。

---

### R2-3（P-5 补强：style.css:2135 z 10001 + nav.js:883 失败分支复位）—— **PASS with notes**

**① z 提升正确性（含 #ddProgressModal 连带影响——任务指定点①）**

- 锚点逐字吻合：web/style.css:2135 `#ddConfirmModal, #ddProgressModal { z-index: 200; }`；全 CSS **单一控制点**（ddConfirm/ddProgress 无其他规则），git 树无漂移。
- **#ddProgressModal 200→10001 连带影响核实为安全**：该弹窗仅 settings.js `_ddProgress()`(:2000-2043) 使用；迁移流（:1781-1800）时序为 `_ddConfirm(迁移确认)`→`prog.show`→**同步** fetch→`prog.hide`→**之后**才 `showBanner`（完成/失败文案）。提升后进度弹窗新盖住 nav 三面板(9999)/ctx-menu(10000) 属"迁移期阻塞交互"的正确语义；banner(300) 全部在 prog.hide() 之后发出，**无遮挡回归**；首启引导流（:2099 _ddConfirm）与迁移进度同流程、同层（10001）无倒挂——r1"两条 ID 同提"的建议落实正确。200~10001 区间无其他需要保持可见的元素。**迁移场景语义成立**。

**② 失败分支复位（任务指定点②对称性）**

- nav.js:883 实锤成立：`showBanner(d2.ok ? ... : '切换失败：...', ...)` 不复位 bkSel，失败后下拉停留新值（S-B1 同型）。
- **但失败有两个出口**——:883（`d2.ok === false`）与 :884（`catch` 网络异常）。R2-3 只说"失败分支"单数，**两出口都补复位才与确认取消分支真正对称**（漏 catch 出口 = 同型失同步残留一半）。落地形态建议：
  ```js
  const d2 = await r.json();
  if (!d2.ok) bkSel.value = _curBk;
  showBanner(...);
  } catch (e) { bkSel.value = _curBk; showBanner(...); }
  ```
- **_curBk 建议仍未吸收**：:869 已算好同值常量 `_curBk = m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')`，r1 更优方案（复位直接写 `bkSel.value = _curBk;`）连续两轮未采纳（小事，但属明确漏项）。

**③ 新问题**：style.css:3124-3125 注释"z-index 95：普通内容之上、通用模态（100）与确认框（200）之下"在改 10001 后陈旧（hg-ctx-card 95 < 10001 层级关系不变，仅注释失真）——落地时顺手更正。

---

### R2-4（P-11 补强：isNote+isMd 过滤）—— **PASS**

**① isMd 判定口径一致性（任务指定点）**

- buildEditorTab 的判定：`_isMd = name ? name.toLowerCase().endsWith('.md') : false`（editor.js:226，大小写不敏感）；mdtheme 下拉显示条件 `（name||'').toLowerCase().endsWith('.md') || isNote`（:295）同款。
- R2-4 用 `c.meta.label.toLowerCase().endsWith('.md')`：注册时点 label===name（:197 `meta: { kind:'editor', label: name || '未命名' }`——草稿 name 为 null 时 label='未命名' 不含 .md 后缀 → isMd=false，与 _isMd=false 一致）→ **口径一致**。改名/另存后 conn.meta.label 动态更新（editor.js:1340/:1353）——label 判定与改名后实态反而更一致（构建期 name 判定已冻结），方向无害。

**② connections 时序（任务指定点）**：`connections[portId] = conn`（editor.js:246）在 buildEditorTab 内**同步**注册、meta.label 先于注册赋值（:197）→ 广播循环中 `c.meta.label` 必可得——r1 结论复核成立。

**③ 无误伤双保险**：`.ed-scroll` 仅存在于 editor wrap（editor.js:110 term-area + :173 ed-scroll 模板）；hex/diff/bindiff/log/terminal-core/proxy-panel/harness 各 wrap grep 零 `.ed-scroll` 命中 → `querySelector` 返回 null 跳过；终端 conn 的 meta.label 即使以 .md 结尾也被"无 .ed-scroll 子元素"挡住。

**④ 补丁链自洽**：R2-4 的 `-` 行与 P-11 原补丁的 `+` 行逐字对齐；`.ed-md-preview` 独立广播（editor.js:1884）不受影响（现状 :1885 锚点逐字吻合，仅注释微差"// a377：笔记编辑区同主题"）。**无新问题、无遗漏方案。**

---

### R2-5（P-14 补强：护栏上移 _edReloadFromDisk + _edCheckDiskChanged stat 窗口）—— **PASS with notes**

**① 锚点与覆盖（任务指定点①）**

- 锚点全部存在：`_edReloadFromDisk` editor.js:1202-1228（函数头 :1202）；`_edCheckDiskChanged` :1160-1198（stat 窗口 ：1168-1169，reload 选项 ：1187-1188）；`_edJumpFresh` :1236-1251（stat 后 ：1243）。
- **函数头护栏对 _edCheckDiskChanged reload 路径的覆盖：成立**。模态 await（:1185）结束后到 `_edReloadFromDisk(conn)` 调用（:1188）之间**无 await 窗口**（同步衔接）——"弹窗期间关 tab"由函数头护栏捕获 ✓。

**② 覆盖缺口（r1 建议位降级）**

- r1 明确建议护栏放 `const j2 = await r2.json()`（:1210）**之后**、任何写点分支之前——覆盖"调用已进入、open fetch 在途时关 tab"窗口（S-B7 原实锤窗口之一）。R2-5 写"函数头一行"：只挡"调用前已关"，**挡不住 open 窗口内关 tab**——此时 ：1214 `conn.editor.render(content)`（已 destroy 实例）/:1217 `conn.monaco.setValue`（已 dispose 实例）抛错 → :1227 catch 误报"重读失败"，**S-B7 在 _edReloadFromDisk 自身 await 窗口的主场景仍通**。
- **"上移"措辞的次生风险**：原 P-14 在 monaco 分支内的护栏（:1215 前）若被"上移"字面执行=撤除。正确落地：函数头 + j2 后**双点**（或按 r1 单点上移到 j2 后替代 monaco 分支位）。
- **_edCheckDiskChanged 的"同款一行"未给插入行号**：应插 :1169（`const j = await r.json();` 解析后）与 ：1183（`conn._dcAsking = true` 置位前）之间——放对位置还可顺带防"死 tab 弹差异弹窗"副作用（_dcAsking/diskWatchAsked 挂在已关 conn 上）。

**③ 双护栏重复检查无害性（任务指定点②）**：_edJumpFresh stat 后检查（P-14 原有，R2-5 明示保留）+ _edReloadFromDisk 头部——两检查点各护各的 await 窗口，重复=早退，**无害成立** ✓。

---

### R2-6（P-21 补强 + audit-b:187 勘误记录）—— **PASS with notes**

- **audit-b:187 现状核实**：该行确为"`**emoji 全量复扫**：web/ 渲染路径彩色 emoji 仅剩 S-B6 一处 ⚪；▶/⬇/■/⠿/⎇/↺/✓/✗/⟳/▾ 均 Emoji_Presentation=No 文本字形（a373 豁免类）✓。`"——⬇（U+2B07）确被归入豁免类，与 Unicode emoji-data（Emoji_Presentation=Yes）及 P-21 的处置矛盾；勘误方向（移入"应清"）正确。
- **P-21 五处锚点现文件仍在位**：src/update_server.py 807/828/850（keycap 1️⃣2️⃣3️⃣）、1006/1025（⬇）；web/js/settings.js:1682（⚪）；icons.js:83（dotOff）——"五处替换不变"落点有效 ✓。
- **缺口一**：audit-b 的实际勘误被推迟（"由巡查任务在下轮核"），且 patch-log 末尾"第 3 轮审计范围"清单**未含此项**——第 3 轮审计者若直接引用 :187 豁免表会漏改 ⬇。建议把"audit-b:187 勘误"显式列入第 3 轮范围，或本轮直接修订该文档行（audit-b 是审计文档非工具源码，修订不违反铁律）。
- **缺口二（本轮最大漏项）**：r1 P-21 ② 的 **dotOff 视觉对齐缺口完全未被吸收**——运行侧 dotOn 带 `<span style="color:var(--neon-green);vertical-align:-2px">` 包装（settings.js:1680），dotOff 裸插 SVG 基线偏上、颜色随文字；r1 建议补同款包装（`color:var(--muted)` + `vertical-align:-2px`）。R2-6 只处理了 audit-b 勘误，此条只字未提。

---

### R2-7（P-22 论证补强：映射面补记）—— **PASS**

- **monaco-bridge.js:22** `'.mak': 'makefile', '.mk': 'makefile', ...` 与 **:41** `if (n === 'makefile' || n === 'readme') return 'makefile';` 逐一逐字核实存在——r1 论证缺口（"改映射指 plaintext"方案本就不完整，文件名强映射仍落 'makefile'）成立，R2-7 补记方向正确。
- "维持仅撤下拉项、映射不动"与 r1 取舍一致 ✓（editor.js:140 makefile 选项仍在位，P-22 落点有效）。
- 小注（不影响裁决）：补记目前是台账级文字；落地时 P-22 的 diff 注释本体应把 :41 一并登记（r1 原话：防止后人只改 :22 得出"修完了"的错误结论）。

---

## 新发现区（r2 独立确认，非 r1 已知项复读）

1. **R2-1 的 `_m.length` 语义回归**（归 R2-1 FAIL 主因之二，单列为方法学条目）：`String.prototype.matchAll` 的匹配对象是数组，无捕获组时 `.length` 恒 1、匹配串长度须取 `m[0].length`。建议后续凡用 matchAll 的补丁一律记 `m[0]`——原 P-25 本来正确，R2-1 重写时引入回归，属"修订引入新缺陷"的典型样本。
2. **hex-diff.js:180 `bindiff:loading:*` 瞬态 tab**：portId 前缀命中 R2-2 正则但该 tab 不入 connections（自有 onclick 自毁、加载完成 `loadTab.remove()`）。补丁后直调 closeConnection('bindiff:loading:…') → closeEditorTab :1386 静默返回（现状直调反而会重置 termArea 空态+重建侧栏）——行为差异微小且非产品路径，仅记录。
3. **closeEditorTab 与 closeConnection 的剩余 tab 逻辑等价**（editor.js:1498-1518 vs sidebar.js:144-160）：两者均实现 v4.1"关活动 tab 优先回 _hgTabBack 来路"语义——R2-2 转发无激活态回归（佐证 R2-2 ①）。
4. **style.css:3124-3125 注释陈旧面**：z 200→10001 后该处"确认框（200）"注释失真（归 R2-3 落地注意项）。
5. **git 基线核对**：web/ 源码与 HEAD 一致（git status 仅 doc/ 未跟踪）——r1 全部行号现状在本轮复现，**无锚点漂移**；本轮唯一全新锚点问题是 R2-1 的结构矛盾而非行号漂移。

---

## 顺带核验：r1 前端 PASS with notes 的 notes 吸收核对

| r1 note | R2 吸收情况 |
|---|---|
| P-5：z 补丁指向改 style.css:2135 | ✓ R2-3 落实 |
| P-5：#ddProgressModal 同提防倒挂 | ✓ R2-3 两条 ID 同提 |
| P-5：影响面论据错误（"modal.show 体系本就在其上"——实测 .modal=100 在其下，ctx-menu 10000 也在其下） | ✗ **未修**（patch-log P-5 正文论述未更正） |
| P-5：复位写 `bkSel.value = _curBk`（:869 已算好） | ✗ 未采纳（R2-3 仍用重复表达式） |
| P-5：sqlite 文案漂移（nav.js:876 实际含"；查询 0~4ms/内存 ~50MB"） | ✗ 未提（应用 diff 时需按实际文本对齐） |
| P-5：验证加"取消后 showBanner 无误报、面板按钮仍可点" | ✗ 未并入 P-5 验证段 |
| P-11：isMd 口径扩大 | ✓ R2-4 落实 |
| P-11：验证加"分栏 .md tab 换主题源码列跟随" | ✗ 未并入 P-11 验证段 |
| P-14：护栏上移 _edReloadFromDisk | △ R2-5 落实但**落点降级**（函数头 ≠ r1 建议位 j2 后，open 窗口残留） |
| P-14：_edCheckDiskChanged stat 窗口列入作用域 | ✓ R2-5 列入（但未给插入行号） |
| P-14：验证加"磁盘改动弹窗选重载期间关 tab"用例 | ✗ 未并入 P-14 验证段 |
| P-16：ed null 优雅降级（结论无风险） | 无行动项（可接受）；可选验证未并入 |
| P-21：dotOff 需同款包装 span（中性色 + vertical-align:-2px） | ✗ **未吸收（本轮最大漏项）** |
| P-21：audit-b:187 勘误 | △ R2-6 记录但推迟，且未列入第 3 轮范围清单 |
| P-21：验证加"运行/未运行两态图标对称"对比截图 | ✗ 未并入 |
| P-22：monaco-bridge.js:41 文件名强映射补记 | ✓ R2-7 落实（台账级；落地时补进 diff 注释本体） |
| r1 新发现 7（引用漂移汇总逐条处理） | ✗ 未吸收——P-25 的"模板数组字面量"描述错误在 R2-1 中延续为"模板表达式"（仍不准确，实为 md.value 字符串拼接）；P-5 文案漂移、P-12 的 R33-1 注释行漂移均未处理 |

**吸收率小结**：7 条 r1 新发现中 5 条实质吸收（1/3/4/5/6 → R2-3/R2-6/R2-3/R2-5/R2-7），第 7 条（漂移汇总）与 P-21 dotOff、P-5 论据更正、_curBk 及四条验证建议未吸收。建议第 3 轮修订时逐条回补（尤其 dotOff 与验证段）。

---

## 附：审计过程记录

- 源码核对范围：web/js/nav.js（600-660 / 812-900）、web/js/sidebar.js（100-240）、web/js/editor.js（94 / 110-115 / 195-320 / 1160-1270 / 1340-1360 / 1384-1520 / 1855-1900）、web/js/monaco-bridge.js（15-60）、web/js/hex-diff.js（175-220）、web/js/icons.js:83、web/js/util.js:20、web/js/log-viewer.js/hex-viewer.js/diff-viewer.js/terminal-core.js（portId 前缀与 .ed-scroll 排查）、web/style.css（2120-2150 / 3120-3130 / z-index 全扫）、web/index.html（脚本加载序 510/513/526）、src/update_server.py（807/828/850/1006/1025）、settings.js（1670-1700 / 1778-1800 / 2000-2103）、doc/audit-b-frontend.md:187。
- node 实证（脚本落系统 TEMP\r2-audit，未入仓库）：①R2-1 diff 字面应用语义——标题头 ×2、4 连反引号行围栏仍 4（`_m.length` 恒 1）；②修正形态（语句前置版与正确接线 IIFE 版，`_m[0].length`）4 用例 ALL PASS（围栏 4/5/4/9 恒 > 内容最长反引号串、标题头唯一、两版逐字节等价）。
- 转发链/时序白盒推演：closeConnection 调用点全仓 sweep（仅 sidebar.js:235、terminal-core.js:76）；closeEditorTab/_edCloseNow dispose 链逐行核对；bindiff:loading 瞬态 tab 生命周期；迁移流 prog.show/hide 与 showBanner 时序；buildEditorTab 注册时序与 label 判定口径。
- git 基线：web/ 与 HEAD 一致（仅 doc/ 未跟踪），r1 行号无漂移。
