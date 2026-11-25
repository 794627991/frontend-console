# 补丁审计报告 R1 · 前端组（白盒）

> 审计对象：doc/patch-log.md 中 10 件前端类补丁提案（P-5 / P-11 / P-12 / P-14 / P-16 / P-21 / P-22 / P-24 / P-25 / P-26）。
> 审计方法：①源码现状逐行核对（行号/内容漂移点名）②JS 语法与语义推演（node --check + node 运行实证，脚本落系统 TEMP，未入仓库）③活体只读核验（CDP 9223 新开独立 target，读 CSSOM/computed 后即关，全程零写操作）④交互面排查（弹层/主题/关闭链/事件监听）⑤更优方案与验证可操作性检查。
> 本文件只裁决补丁提案，未修改任何工具源码。

---

## 结论先行

**10 件：PASS 2 · PASS with notes 6 · FAIL 2。**

| 补丁 | 实锤 | 裁决 | 一句话 |
|---|---|---|---|
| P-5 | C-2+S-B1 | **PASS with notes** | 取消回弹 JS 侧正确；z 补丁的 diff 锚点不存在（真身是 style.css:2135 的 ID 规则，非内联样式），需改指向 |
| P-11 | S-B2 | **PASS with notes** | isNote 收敛正确；漏了 .md（非笔记）源码列的主题同步——补丁自己制造新的"tab 间不一致"变体 |
| P-12 | S-B4 | **PASS** | 统一过滤通道根治竞态，闭包/TDZ 核实无险 |
| P-14 | S-B7 | **PASS with notes** | 护栏先例与行号全对；建议护栏上移到 `_edReloadFromDisk` 函数头（现只护 monaco 分支，笔记路径仍裸奔） |
| P-16 | S-B9 | **PASS with notes** | 与工作区符号先例同构；ed null 已核实优雅降级，风险不存在 |
| P-21 | S37-11+S-B6 | **PASS with notes** | 五处行号逐字命中、ICO16.dotOff 存在；漏了 dotOn 同款对齐包装 span，且与 audit-b emoji 豁免表自相矛盾 |
| P-22 | S-B3 | **PASS with notes** | 撤项+保持映射的取舍正确；论证需补 monaco-bridge.js:41 文件名强映射（否则"改映射"方案本就不完整） |
| P-24 | S-B5 | **PASS** | vendor basic-languages 静态证实 ruby 已注册，一行选项零风险 |
| P-25 | S-B8 | **FAIL** | 算法对、diff 接线错：字面应用产生逗号表达式损坏（node 实证标题头重复两遍），且 IIFE 根本不必存在 |
| P-26 | D-3 | **FAIL** | 方向对、锚点与文件全错：closeConnection 在 sidebar.js:113 且**没有** edit:* 分支可改；需按 kind ∈ {editor,hex,diff,bindiff} 重写防御头 |

---

## 逐件裁决详情

### P-5（C-2+S-B1：档位确认弹窗 z 提升 + 取消回弹）—— PASS with notes

**① 是否正确解决问题 —— 是（两侧均实证成立）**

- **S-B1 取消回弹（JS 侧）**：机制核实成立。`_renderState`（web/js/nav.js:817）首行 `const btns = card.querySelector('div:last-child')`（:818）按文档序取第一个匹配；取消路径二次调用时 `st` 已含 ok1/信息行等子节点（:845-860），**st 内部最后一行 div** 先于 `btns`（card 第 4 子）命中 → 随后 `st.innerHTML = ''`（:844）把捕获节点打成死节点，`btns.insertBefore(...)` 全部落空，下拉停留试选值。补丁改 `bkSel.value` 复位绕开死路径，正确。
- **闭包可得性（任务指定核对点）**：`bkSel`（nav.js:866）、`m = j.meta || {}`（:843）、`bkSel.onchange`（:872）同处 `_renderState` 函数作用域；`m.code_files` 在 ：849 已有用法。补丁行 `bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));` 语法合法、语义与 ：869 的 `_curBk` 完全等价。
- **C-2 z 遮挡（任务指定核对点：_ddConfirm 实际定义位置与 z 现状）**：
  - `_ddConfirm` 定义在 **web/js/settings.js:2044**（非 patch-log 含糊所称"util.js 或 nav.js 内联"），弹层创建方式是 `m.className = 'modal'`（settings.js:2048）+ 复用单例 `#ddConfirmModal`，**没有任何内联 z-index**。
  - z=200 的真身是 **web/style.css:2135** 的 ID 规则：`#ddConfirmModal, #ddProgressModal { z-index: 200; }`（上面 ：2134 注释说明当初就是为了压过同 z 的数据目录面板）。patch-log P-5b 的 diff（`- m.style.cssText = '...z-index:200...'`）**指向不存在的代码**，照抄落不了地。
  - 活体只读核验（CDP 9223 新开独立 target，读 CSSOM + computed 后即关）：`.modal` 计算值 **100**；CSSOM 命中 `["#ddConfirmModal, #ddProgressModal","200"]`；`.ctx-menu` **10000**；现存 fixed 高层元素 banner=300 / connModal=100 / logsModal=100 / ctxMenu=10000。与静态分析完全一致。
  - 遮挡链成立：确认弹窗 200 < navIdxPanel 9999（nav.js:768 内联）/ navSymPanel 9999（:347）/ navCandsPanel 9999（:448）→ 确认弹窗被索引面板整层盖住，C-2 属实。
  - z=10001 落位安全：高于 9999 三面板、高于 ctx-menu 10000 与全部 .modal(100)，低于唯一 99999 tooltip。确认弹窗置顶本就是正确语义，无倒挂场景。

**② 是否引入新问题**

- **P-5b 必须改指向**：落地应改 style.css:2135。且该规则**同时管 ddProgressModal**（数据目录迁移进度条）——需明示只提 `#ddConfirmModal`（拆两条规则）还是同提 10001。建议同提：首启引导（settings.js:2099 的 _ddConfirm）与迁移进度同流程，只提一个会出现"确认 10001 / 进度 200"的层级倒挂。
- **影响面评估文字错误**：patch-log 称"其他模态（modal.show 体系）本就在其上"——实测 .modal 体系 z=100 在其**下**，ctx-menu 10000 也在其下。结论（语义安全）不变，但论据要改。
- **现状引用漂移**：patch-log 引 sqlite 文案为"…一次性）？"，实际 nav.js:876 是"…一次性；查询 0~4ms/内存 ~50MB）？"——应用 diff 时须按实际文本对齐。

**③ 更优方案**

- 复位直接写 `bkSel.value = _curBk;`（:869 已算好的同值常量，删掉重复表达式）。
- 顺手面：nav.js:883 切换失败（`d2.ok === false`）时 bkSel 同样停留新值——与 S-B1 取消回弹同型的失同步，建议同补一行复位（详见新发现区 3）。

**验证可操作性**：真机三步可行；建议增加"取消后 showBanner 无误报、面板按钮仍可点"断言（验证死节点路径确实被绕开）。

---

### P-11（S-B2：md-pv 收敛 isNote）—— PASS with notes

**① 是否正确解决问题 —— 是**

- S-B2 机制核实：`.ed-scroll` 是**所有**编辑器形态公共模板的滚动容器（editor.js:173，注释/大纲/holder 同层），基础规则 `.ed-scroll { ... background: var(--note-bg); ... }`（style.css:479）+ `.ed-scroll.md-pv-*` 主题类改 `--note-bg`（style.css:5229-5230 等）→ a377 全量广播（editor.js:1885）把预览配色染到代码/文本 tab。现状引用与 ：1884-1885 吻合（仅注释文字微差）。
- 补丁三要素核实：①wrap 是 `.term-area` 且带 `dataset.portId`（editor.js:110-111）✓；②`connections[portId] = conn` 在 buildEditorTab 内**同步**注册（:246，补丁声称的"打开动画中 meta 已注册"成立，connections 时序风险排除）✓；③`c.isNote` 属性存在（conn 字段 ：205）✓。`connections` 为 util.js:20 全局 `let`，editor.js 已有 12+ 处引用，作用域无险。
- 终端 wrap 同名 `.term-area`（terminal-core.js:81）：无 `.ed-scroll` 子元素且 conn.isNote 为 undefined → 双保险跳过 ✓。

**② 是否引入新问题 —— 一处遗漏面**

- **.md（非笔记）tab 的源码列被误伤**：现行为下 `.md` tab 的 `.ed-scroll`（分栏"源码"列）也吃主题类；且 mdtheme 下拉对 `.md` 同样显示（editor.js:295 `(name||'').endsWith('.md') || isNote`），a377 注释（:294）明说"`.ed-scroll` 消费同一批 --note-* 变量"。补丁 isNote-only 后：新开 .md tab 的源码列不再挂类、已挂类的旧 tab 在换主题时**冻结为陈旧类**——正是 S-B2 要消灭的"tab 间不一致"的新变体。S-B2 实锤自身口径（"非 **md/note** 的代码/文本 tab"）也表明 .md 应保留。
- 修正建议（一行）：
  ```js
  if (c && (c.isNote || (c.meta.label || '').toLowerCase().endsWith('.md'))) { ... }
  ```
- `.ed-md-preview` 走上一行独立广播（:1884）不受影响 ✓（patch-log 已自证）。

**③ 更优方案**：按上式扩大过滤口径即可；改 CSS 作用域（笔记 wrap 挂专用类）改动面大，不值。**验证**：补丁原三步之外加"分栏 .md tab 换主题源码列跟随"一步。

---

### P-12（S-B4：fsym 首拉竞态，渲染统一走过滤通道）—— PASS

**① 是否正确解决问题 —— 是**

- 竞态机制核实：showFileSymbols 首拉（nav.js:387-398）resolve 后无条件 `all = j.items; _full = j.items; render()` 覆盖 input 处理器（:402-410，160ms 去抖后对 `_full` 过滤）先行产生的过滤结果；输入先于 resolve 时全量顶掉空列表。与 S-B4 实锤吻合（现状引用仅差一行 R33-1 注释）。
- 补丁统一渲染通道：resolve 时按当前 `input.value` 过滤后再 render，q='' 行为退化为全量（等价）。`selIdx = 0` 与 input 处理器（:406）口径一致。
- **闭包/TDZ 核实（重点）**：`_full` 的 `let` 声明在 ：401，位于 fetch 调用（:387）**之后**——then 回调是微任务，showFileSymbols 同步体（含 ：401 初始化）必然先执行完，无暂时性死区；`input`/`selIdx` 同作用域。语法合法。

**② 是否引入新问题**：无。`_full` 是每次面板实例的局部量，无跨面板泄漏；catch 静默路径不变。

**③ 更优方案**：与工作区符号面板 ：300 同款"resolve 时比对当前输入"守卫亦可，但统一过滤通道更彻底（顺带把 selIdx 语义拉齐）。补丁选择无遗漏。小注：`!j.ok` 分支（:389-394）在用户已输入过滤词时仍会以"无符号"占位覆盖列表——既有行为、不在 S-B4 范围，仅记录。

**验证可操作性**：CDP 限速复现步骤可直接沿用 audit-b 的 T4/T4R 方法（input 'zzzz' → resolve 后应为空列表）。

---

### P-14（S-B7：_edJumpFresh/_edReloadFromDisk 存活护栏）—— PASS with notes

**① 是否正确解决问题 —— 是**

- S-B7 机制核实：`_edJumpFresh`（editor.js:1236-1251）await stat 窗口、`_edReloadFromDisk`（:1202-1228）await open 窗口内关 tab → `closeEditorTab → _edCloseNow` 已 `conn.monaco.dispose()`（:1438）→ 对 disposed editor `setValue` 抛错 → 外层 catch 误报"重读失败"（:1227）。`delete connections[conn.portId]`（:1496）保证 `connections[conn.portId] !== conn` 守卫判别有效。
- 同款护栏先例确凿：jump 链 editor.js:2291 `connections[conn.portId] === conn`（补丁论证属实）。
- **行号核对**：本批唯一零漂移补丁——:1236-1251 / :1202-1228 与实际完全吻合；现状引用行（:1243 changed、:1215-1217 monaco 写点）逐字吻合。
- 语法/作用域：`connections` 全局可用；插入点在 `changed` 计算后、分支前，语法合法。

**② 是否引入新问题 —— 无回归，但有覆盖缺口**

- 护栏只插 **monaco 分支**：`conn.editor`（笔记 Editor.js 实例）与 `conn.ta`（降级 textarea）路径未护——笔记 tab 关闭后 `conn.editor.render(content)` 落在 destroy 过的实例上（:1436 已 destroy），大概率抛错进同一个 catch 误报"重读失败"；成功路径也会在关 tab 后误报"已重新加载"（:1226）。`_edJumpFresh` 因 extPath 前置条件（:1238）本就只服务外部文件，**笔记的 reload 走的是 _edCheckDiskChanged → 选择重载（:1187-1188）这条无护栏的调用链**。
- 修正建议：护栏上移到 `_edReloadFromDisk` 的 `const j2 = await r2.json()`（:1210）之后、任何写点分支之前，一护全部分支；`_edJumpFresh` 内的插入保留（stat 窗口同样需要）。单点上移比双点插入覆盖面更全且更少重复。

**③ 更优方案**：见上。相邻面提醒：`_edCheckDiskChanged` 自身的 stat fetch（:1168）窗口同样裸奔（diskWatchTimer 5s 轮询触发，概率低但同型）——不在 S-B7 范围，记入新发现区 4。

**验证可操作性**："跳转窗口内快速关 tab"可行；建议加"磁盘改动弹窗选重载期间关 tab"用例（覆盖笔记路径）。

---

### P-16（S-B9：fsym 跳转入导航历史，走 _jumpOpen）—— PASS with notes

**① 是否正确解决问题 —— 是**

- S-B9 机制核实：row.onclick（nav.js:380）与 Enter 分支（:415-420，patch-log 写 ：416-421 为 ±1 漂移）走裸 `openFileSmart`，不入 NAV_HIST；工作区符号面板 :323 走 `_jumpOpen` 先例确凿——行为不一致成立，对齐即修。
- **ed 为 null 的行为（任务指定核对点）**：入口两路均非 null——键位路 :712 `if (ed && matchKey(...))` 显式守卫；addAction 命令路（:587-601）`run: function (edt) { fn(edt); }` 由 Monaco 传入编辑器实例。理论上 null 时 `_jumpOpen → _navPos(null)` 的 try/catch 返回 null（nav.js:59-67）→ `navPush(null)` 被 `if (!pos || !_navPathOk(pos.path))` 安全跳过（:75-76），目标位置仍入栈，跳转本身不受影响——优雅降级，与 :323 先例同款暴露面，无新增风险。
- opts 形状 `{ line, col: 1, selectLine: true }` 与 ：488 先例逐字同款（openFileSmart 支持面已证）；`_closeSym()` 先行保持；a375R/a380R 的取消不污染历史语义由 `_jumpOpen` 内部（:174-176）自带。

**② 是否引入新问题**：无。`_jumpSeq` 并发保护、'cancelled' 排除均为既有机制；面板 DOM 先移除，commit 闭包不引用面板节点。

**③ 更优方案**：无（与工作区符号行为对齐就是目标本身）。**验证**：fsym 跳转后 Alt+← 回原位置可行；可加"打开方式弹窗取消后历史无幽灵项"复验（a375R 回归面）。

---

### P-21（S37-11+S-B6：emoji 残留三处）—— PASS with notes

**① 是否正确解决问题 —— 是（行号全部精确命中）**

- **settings.js:1682**：`: `⚪ 未运行 · 分发目录 ${esc(j.dir)}${ver}`;` 逐字命中 ✓；`ICO16.dotOff` 存在（icons.js:83，`<circle cx="8" cy="8" r="4"/>` 描边空圈，经 _icoWrap 产出 stroke=currentColor 的 16px SVG），与运行侧 dotOn（实心，:83 附近）对称 ✓。
- **src/update_server.py**：keycap 1️⃣/2️⃣/3️⃣ 在 **807/828/850**、⬇ 在 **1006/1025**——五处行号逐一精确命中（patch-log 位置行全对）。`1️⃣` → `<b>1.</b>` 语义等价；⬇ 删除后按钮文字"下载整包/下载资源包/下载离线包"自足 ✓。

**② 是否引入新问题**

- **dotOff 视觉对齐缺口**：运行侧 dotOn 带 `<span style="color:var(--neon-green);vertical-align:-2px">` 包装（settings.js:1680），补丁对 dotOff 是裸插——SVG 基线偏上、颜色随文字。建议补同款包装（中性色如 `color:var(--muted)` + `vertical-align:-2px`），与运行侧真正对称。
- **文档自相矛盾（必有一错）**：audit-b-frontend.md:187 的 emoji 全量复扫把 ⬇ 归入"Emoji_Presentation=No 文本字形（a373 豁免类）"，而 P-21 按"彩色 emoji"处理 ⬇。Unicode emoji-data 中 U+2B07 的 Emoji_Presentation=Yes（Windows Segoe UI Emoji 下彩色渲染）——**P-21 方向正确，audit-b :187 的分类行需要修订**，否则后续轮次会拿它当豁免依据（详见新发现区 2）。

**③ 更优方案**：无。**验证**：分发页/设置页视觉复扫可行，建议加"运行/未运行两态图标对称"对比截图。

---

### P-22（S-B3：ed-lang 撤 Makefile 死选项）—— PASS with notes

**① 是否正确解决问题 —— 是**

- S-B3 机制静态佐证：`vendor/monaco/min/vs/basic-languages/` 共 80 目录，**无 makefile**（ruby/perl/lua 等在列）——与 audit-b 真机 getLanguages 91 id 实证互洽。editor.js:140 `<option value="makefile">Makefile</option>` 命中属实。
- **映射保持不动的取舍（任务指定核对点）——正确，且论证需补一处**：补丁建议保持 monaco-bridge.js:22 的 `.mak/.mk→makefile` 映射，正确（现状该语言 ID 无 grammar → 视觉等同 plaintext，零功能损失；未来 vendor 补 grammar 自动升级）。但"改映射指 plaintext"方案本就不完整——**monaco-bridge.js:41 还有文件名强映射** `if (n === 'makefile' || n === 'readme') return 'makefile';`，即使改了 :22，名为 makefile/readme 的文件仍落 'makefile' ID。补丁论证里"撤项后 Makefile 文件走 plaintext"欠精确（是"视觉等同 plaintext"，语言 ID 未必是 plaintext），注释里应把 :41 一并登记，防止后人只改 :22 得出"修完了"的错误结论。

**② 是否引入新问题**：无。纯 UI 删项；`_edBindLangSel` 按当前 lang id 回显时若遇 'makefile' 会落空选中"语言：自动"——实际无害（自动档行为不变）。

**③ 更优方案**：即补丁已选的"保持映射、仅撤下拉项" ✓。**验证**：下拉无 Makefile、.mk 打开仍无高亮——可行。

---

### P-24（S-B5：下拉补 Ruby 选项）—— PASS

**① 是否正确解决问题 —— 是**

- S-B5 机制核实：detectLangByShebang 返回 'ruby'（monaco-bridge.js:56），下拉选项表（editor.js:134-159）无 ruby——显示与实际错位成立。vendor basic-languages **含 ruby 目录**（静态佐证"ruby 已注册真机实证"），`value="ruby"` 与 shebang 返回值同一 ID，monacoLangFor override 直通（monaco-bridge.js:39）。
- diff 上下文 `<option value="perl">Perl</option>` / `<option value="lua">Lua</option>` 与 editor.js:154-155 逐字吻合；位置描述"editor.js:124-167"是选项表外围范围，可接受。

**② 是否引入新问题**：无（一行选项，幂等绑定已有 dataset.bound 防重）。**③ 更优方案**：无。**验证**：无后缀 ruby 脚本下拉显示 Ruby——可行。

---

### P-25（S-B8：hover 动态围栏 IIFE）—— **FAIL**

**① 算法本身正确**：围栏 = max(3, snippet 内最长反引号串) + 1，满足 CommonMark 闭合栏规则（闭合须≥开栏、开栏≥3），对内容内任意长度反引号串不可闭合。`matchAll(/`+/g)` 用法正确（有 /g）；`word`/`c` 在 provideHover 的 then 回调作用域内可得。node 实证：含 4 连反引号行的 snippet 产出 5 反引号围栏，正确。

**② diff 字面应用产生损坏输出（node 运行实证）——FAIL 主因**

- diff 只删除了中间的围栏行（nav.js:635），但 IIFE 返回的是**整段内容**（含标题头与路径行），且以 `})(),` 结尾；未删除的首行（:631-632）拼在其前、未删除的尾行（:636）跟在其后。由于 `=` 优先级高于 `,`，实际语义是：
  ```js
  md.value = 头部串 + IIFE(整段内容), 尾行串;   // 逗号表达式：尾行串是死表达式
  ```
- node 实测输出：**标题头 `**foo** \`func\`` 重复两遍**（首行拼一次 + IIFE 内部再一次），`\`a.c :12\`` 由 IIFE 附带出现一次而外层尾行串被丢弃；`node --check` **通过**（语法合法）——补丁自我声称"需 node --check 核语法"恰好挡不住这类静默语义损坏。
- 另：位置描述"模板数组字面量内"不符——实为 `md.value = '字符串拼接'`（nav.js:631-636），不在任何模板串/数组字面量内。现状引用（:633-636 四反引号围栏行）本身与源码吻合。

**③ 修正方向（更优方案：根本不需要 IIFE）**

provideHover 的 `.then(j => { ... })` 回调是函数体，**普通语句合法**——把围栏计算提到 `md.value` 赋值之前即可，表达式零结构变化、零接线风险：

```js
const _s = String(c.snippet || '');
let _max = 3;
for (const _m of _s.matchAll(/`+/g)) _max = Math.max(_max, _m[0].length);
const _f = '`'.repeat(_max + 1);
md.value = '**' + word.word + '** `' + (c.kind || 'symbol') + '`' +
  (c.in_build === true ? ' ✓编译内' : '') + (c.file_local ? ' ·本文件' : '') + '\n\n' +
  _f + '\n' + _s + '\n' + _f + '\n\n' +
  '`' + c.rel + ' :' + c.line + '`';
```

（node 已按此版实证：普通/4 反引号/空 snippet 三用例全部正确。）若坚持 IIFE，则必须让它替换**整个赋值语句**（以 `;` 结尾、同时删除首尾两行）——但语句前置版显然更简单。**验证**：沿用原"fixture snippet 含四连反引号行"，并新增"标题头只出现一次"断言。

---

### P-26（D-3：closeConnection edit:* 转发 closeEditorTab）—— **FAIL**

**① 问题定位属实，但锚点与文件归属全错（FAIL 主因）**

- patch-log 写"位置：web/js/terminal-core.js:76（closeConnection 分发）"——**实际** terminal-core.js:76 是 `buildTerminal` 里终端 tab ✕ 的 onclick（调 closeConnection，portId 为串口/SSH/Telnet/Claude，永不为 edit:*），不是任何分发点。
- `closeConnection` 的真身是 **web/js/sidebar.js:113-163**：一段通用拆除路径（POST /api/disconnect + sse/term/_webgl dispose + 各类 timer 清理 + tab/wrap 移除 + connections 删除 + 剩余 tab 切换）。**全文没有任何 `edit:` 前缀判定、没有任何 `kind === 'editor'` 分支**——patch-log 的伪 diff `- if (kind === 'editor') { ... 现有关闭逻辑 ... }` 在源码中**不存在可落的锚点**（`kind` 变量在该作用域也无定义）。真正的 kind 分发在两处：侧栏关闭按钮 sidebar.js:231-235（isEdit → closeEditorTab）、switchTab 的 editor 分支（terminal-core.js:526/552）——patch-log 把两处拓扑搞混了。
- 泄漏事实本身与 D-3 附带观察一致（3.1MB/次 vs 0.58MB/次，直调绕过 `_edCloseNow` 的 monaco/model/diffEd/document 监听器 dispose 链）；D-3 原文也明说"当前按 kind 分发没踩到，外部脚本/扩展若直调会放大 5 倍"——**这是防御性补丁，防的是非产品路径**，patch-log 应写明这一点（现文读起来像在修一条真实存在的关闭路径）。

**② 等价性核对（任务指定核对点）**：转发即替代、return 保证单路径，无双执行。转发后相对现 closeConnection 对 edit:* 的行为差异：
- **跳过** `POST /api/disconnect`——对 edit:* 本就是 sidebar.js:229-230 注释认定的"必 404"垃圾请求，跳过是改善；
- **跳过** `refreshGlobalStatus()`——产品路径 closeEditorTab/_edCloseNow 本就不调它（editor.js:1494-1519 只调 refreshSidebar），一致性无损；
- **获得** dirty 确认弹窗 + 完整 dispose 链——正是防御目的。
方向完全成立，问题只在落地形态。

**③ 修正方向**

```js
function closeConnection(portId) {                    // sidebar.js:113
  // D-3：编辑族 tab 直调兜底——统一转产品关闭链（dirty 确认 + dispose）
  const _c = connections[portId];
  if (_c && _c.meta && ['editor', 'hex', 'diff', 'bindiff'].indexOf(_c.meta.kind) >= 0
      && typeof closeEditorTab === 'function') { closeEditorTab(portId); return; }
  fetch('/api/disconnect', ...);                      // 原逻辑不动
  ...
```

仅守 `'edit:'` 前缀**不够**：hex/diff/bindiff 的 portId 前缀分别是 `'hex:'`（hex-viewer.js:32）/`'diff:'`（diff-viewer.js:174）/`'bindiff:'`（hex-diff.js:205），侧栏对这四类同样走 closeEditorTab（sidebar.js:198 isEdit 定义 + :233 分发）——防御面必须与 isEdit 同口径，否则 hex/diff 直调仍绕过 dispose 链。`_edCloseNow` 对 hex/diff/bindiff 的清理段已存在（editor.js:1468-1478 的 _hxUp/_hxAbort/diffEd），转发目标安全。"治本挂行动项（heap snapshot 出 P-26b）"的定位正确：主泄漏 0.58MB/10 次确非本行能治。**验证**：原"50 次开/关 GC 后堆增量"方案可行，需加一条"直调 closeConnection('edit:…') 现在走确认弹窗 + dispose"的行为断言。

---

## 新发现区（审计过程中确认、不属于原 10 件范围的事实与建议）

1. **全站确认/进度弹窗层级的单一控制点**：`#ddConfirmModal, #ddProgressModal { z-index: 200; }`（web/style.css:2135）——P-5b 的真正落点。活体核验（CDP 9223 独立 target 只读）：`.modal` 计算值 100、`.ctx-menu` 10000、CSSOM 命中 ddConfirm 规则 200。修改时建议两条 ID 同提或显式拆分（首启引导确认与迁移进度同流程，防层级倒挂）。
2. **audit-b-frontend.md:187 的 emoji 豁免表与 P-21 矛盾**：该行把 ⬇（U+2B07）归入"Emoji_Presentation=No 豁免类"，与 S-B6 对 ⚪（U+26AA）同型判定的结论冲突；按 Unicode emoji-data，U+2B07 的 Emoji_Presentation=Yes。P-21 处理方向正确，audit-b 该行应修订，防止后续轮次引用豁免表漏改 ⬇。
3. **nav.js:883 切换失败分支的 bkSel 失同步**：reindex 请求返回 ok:false 或网络异常时，下拉停留新值而后端未切换——与 S-B1 取消回弹同型（S-B1 只锤了取消侧）。P-5 落地时建议顺手复位，或单独记账。
4. **_edCheckDiskChanged 的 stat 窗口无存活护栏**（editor.js:1160-1179）：与 S-B7 同型的 await 窗口（5s 轮询触发，概率低），S-B7/P-14 落地后它是同族最后一块裸奔面。
5. **monaco-bridge.js:41 文件名强映射**（`makefile`/`readme` → 'makefile'）：P-22 的论证精度缺口（见 P-22 裁决）；同时也是"vendored Monaco 补 makefile grammar 后无需任何前端改动即自动生效"的关键受益点，值得写进长期方案注释。
6. **portId 前缀矩阵**（P-26 防御面口径依据）：`edit:`（editor.js:94）、`hex:`（hex-viewer.js:32）、`diff:`（diff-viewer.js:174）、`bindiff:`（hex-diff.js:205）、`log:`（log-viewer.js:117）、其余 terminal/proxy/harness 各有前缀；侧栏 isEdit 口径 = editor/hex/diff/bindiff 四类。
7. **patch-log 引用漂移汇总**（均不影响裁决方向，应用 diff 时按实际文本对齐）：P-5 的 sqlite 文案（nav.js:876 多"查询 0~4ms/内存 ~50MB"）；P-12 现状少一行 R33-1 注释（nav.js:396）；P-16 Enter 分支 ±1 行号（实际 ：415-420）；P-25 位置描述"模板数组字面量"与实况（md.value 字符串拼接）不符。

---

## 附：审计过程记录

- 源码核对范围：web/js/nav.js（872-885 / 380-421 / 59-76 / 162-182 / 585-603 / 621-642 / 342-428 / 760-790）、web/js/editor.js（115-160 / 160-320 / 1160-1270 / 1384-1520 / 1855-1910 / 2355-2390）、web/js/settings.js（1670-1700 / 2040-2103）、web/js/sidebar.js（113-238）、web/js/terminal-core.js（66-124 / 526-553）、web/js/monaco-bridge.js（全文）、web/js/icons.js（1-90）、web/js/util.js:20/1040、web/style.css（479 / 1889-1896 / 2134-2135 / 5229-5239）、vendor/monaco/min/vs/basic-languages 目录清单、src/update_server.py（800-860 / 1000-1030）。
- node 实证（脚本落系统 TEMP，未入仓库）：P-25 补丁字面应用结果——`node --check` 通过但运行输出标题头重复两遍（FAIL 证据）；语句前置修正版三用例（普通/4 反引号行/空 snippet）全部正确。
- 活体只读核验：CDP 9223 `/json/new`（PUT）开独立 target 加载应用页 → Runtime.evaluate 只读 CSSOM/computed → `/json/close` 关闭，全程未触碰用户现有窗口、零 DOM 写操作。
