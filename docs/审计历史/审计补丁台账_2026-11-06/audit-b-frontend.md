# 第 36 轮对抗式代码审查报告 · 前端组（8251c58..HEAD，33 提交全量前端改动）

- 审计对象：`git diff 8251c58..HEAD -- web/ vendor/monaco/`（36 文件 +1873/-314；9a88c13=a372 至 db9f27a/a385R），HEAD=db9f27a
- 环境事实：开发服务器 http://127.0.0.1:8867 未重启（后端 a392）；前端验证走 CDP 9223 **独立新 target** `?r=<时间戳>` 共 7 个脚本（rb36_verify*.py，已删）；根库为共享数据区，全程**只读**（终态 backend=sqlite、458,264 符号、四接口正常）；真 ~/.claude.json 未读写；git 零触碰（工作区 clean）；localStorage 键零污染（`_mdPvSetTheme(t,false)` 不落库、`hg-ed-lang-override` 未触碰）；测试 DOM（md-pv 类/面板/mock）已全部还原清理；CDP target 已关闭。

---

## 一、结论（先行）

**实锤 9 件：P3×4 + P4×5。** 未发现 P1/P2 级问题：本轮范围（a372~a385R）此前七轮对抗审（R30~R35）的已知实锤闭环在其复验面没有回归；新实锤集中在三类主题——**①a390 档位下拉与 a377 预览配色这两个"新 UI 面"的边界缺陷（S-B1/S-B2/S-B6），②a376 语言下拉/高亮链的选项表与真实 Monaco 语言注册表不对齐（S-B3/S-B5），③R33-1 本地过滤改造与 a372 跳转补链各自留下的时序竞态（S-B4/S-B7）**。

| # | 分级 | 主题 | 位置 |
|---|---|---|---|
| S-B1 | **P3** | a390 档位下拉「确认取消」两连坏：下拉**不回弹**（残留试选值与实际后端不一致）+ `_renderState` 重渲染按钮写进**脱离 DOM 的死节点** | web/js/nav.js:877 ↔ :818 |
| S-B2 | **P3** | a377 `_mdPvSetTheme` 把预览配色类挂到**所有编辑器形态**的 `.ed-scroll`——非 md/note 的代码/文本编辑 tab 背景被预览配色染色，且新开 tab 不受影响（tab 间不一致） | web/js/editor.js:1885 + web/style.css:5229+ |
| S-B3 | **P3** | ed-lang 下拉 **Makefile 是死选项**——vendored Monaco 无 makefile 语言（真机 getLanguages 91 个 id 实证），选了=无高亮且与「纯文本」不可区分 | web/js/editor.js:140 + web/js/monaco-bridge.js:22 |
| S-B4 | **P3** | fsym 面板首拉期间输入的过滤词被**全量结果覆盖**（R33-1 本地过滤的时序竞态：input 先对空 `_full` 过滤，resolve 后无条件全量 render）——真机限速复现：input='zzzz' 最终显示 3 行全量 | web/js/nav.js:396-408 ↔ :401/:410-419 |
| S-B5 | **P4** | shebang 探测可返回 `ruby`，但下拉无 ruby 选项——**下拉显示「语言：自动」而实际按 ruby 高亮**（真机双证） | web/js/monaco-bridge.js:56 ↔ web/js/editor.js:124-167 |
| S-B6 | **P4** | 分发服务「未运行」分支残留 `⚪`（U+26AA，Emoji_Presentation=Yes，彩色 emoji 渲染）——a373 铁律残留（🟢 侧已换 dotOn SVG，⚪ 侧漏改） | web/js/settings.js:1682 |
| S-B7 | **P4** | `_edJumpFresh → _edReloadFromDisk` 无 tab 存活护栏——跳转 await 窗口内关 tab → monaco dispose 后 `setValue` 抛错 → **误弹「重读失败」banner**；成功路径则在关 tab 后弹「已重新加载」 | web/js/editor.js:1236-1251 ↔ :1202-1228 |
| S-B8 | **P4** | hover 四反引号围栏残留：snippet 内 **≥4 连反引号行仍可闭合**（CommonMark 闭合栏只需 ≥ 开栏长度，R33-3 修法只挡 3 反引号） | web/js/nav.js:633-636 |
| S-B9 | **P4** | fsym 面板点击/回车跳转走裸 `openFileSmart` **不入导航历史**——同为符号跳转，工作区符号（Ctrl+T）走 `_jumpOpen` 入栈，行为不一致（VSCode 中文件内符号跳转计入历史） | web/js/nav.js:380、:416-421 |

**总评**：本轮大改（导航历史栈、Ctrl+Shift+O、Hover、语言下拉、档位下拉、md-pv 并列、vendor 双补丁）主链路真机全部可用；缺陷面集中在**新 UI 的"取消/复位/回写"分支**与**"选项表 vs 实际注册表"的对齐**，无数据丢失/无 XSS/无内存泄漏。

---

## 二、实锤详情（逐件）

### S-B1（P3）：档位下拉「确认取消」——下拉不回弹 + 重渲染写死节点【真机复现】

**位置**：
- 取消分支：`web/js/nav.js:877` `!(await _ddConfirm(...))) { _renderState(card, path, j, st); return; }`（a390 新增的取消重渲染调用）
- 断裂点：`web/js/nav.js:818` `const btns = card.querySelector('div:last-child');`

**证据（三证齐）**：
1. **代码直读**：`_renderState` 在函数**最顶部**捕获 `btns = card.querySelector('div:last-child')`。首次渲染时 `st` 只有 textContent（'探测中…'，无元素子节点），`div:last-child` 命中按钮行 `btns`（card 的最后一个 div 子节点）✓。但**取消重渲染是第二次调用**——此刻 `st` 已含首轮渲染写入的信息行 div（ok1/info/warn），`querySelector('div:last-child')` 按 DFS 文档序命中的是 **st 内部的最后一个信息行 div**（它自己是其父的 last-child，且在 btns 之前）。随后 indexed 分支 `st.innerHTML=''` 把该 div 从 DOM 摘除 → `btns` 变成**脱离 DOM 的死节点引用** → `btns.insertBefore(bkSel/bDel/bRe, btns.lastChild)` 三连全部写进死节点，**可见按钮行原样保留旧下拉/按钮**。
2. **真机复现（CDP，mock `_ddConfirm=async()=>false` + `window.NavJump.ui('D:/AI/前端控制台')`）**：
   - 取消前：select.value=`sqlite`（与后端 meta.backend=sqlite 一致，a392 已下发 backend 字段）；
   - 设 select.value='readtags' + dispatch change → 取消；
   - 取消后：**select.value 仍为 `readtags`**（不回弹）、面板内 select 数=1（无重复）、st 文本零变化、按钮行=[下拉, 删除索引, 重建, 关闭] 原样——重渲染**整体失效**。
3. **推理链**：意图是"取消 → 重渲染复位下拉"，实际=重渲染产物进 detached 节点被丢弃 + 旧下拉保留用户试选值。每次取消还会向死节点堆一套按钮（内存垃圾，不累积可见 UI）。

**影响面**：①下拉显示态与实际后端不符（用户看到"已选 readtags"而实际仍是 sqlite）——这是**决策型 UI 的状态错位**，下一次误信显示直接点确认会把档位切到不想要的档；②取消=无反馈（相比"回弹"少了明确否定感）。

**最小修法**：`_renderState` 的 btns 捕获改 `card.querySelector(':scope > div:last-child')`（只认直接子层，排除 st 内部）；取消分支不必整渲染，一行 `bkSel.value = (m.backend || ...) || _curBk` 复位即可（m 在闭包内可得）。

---

### S-B2（P3）：md-pv 预览配色类泄漏到全编辑器形态的 `.ed-scroll`【真机复现】

**位置**：
- 污染源：`web/js/editor.js:1885` `document.querySelectorAll('.ed-scroll').forEach(_mdPvApplyTheme);`（a377 注释"笔记编辑区同主题"）
- 放大器：`web/style.css:5229+`——`.ed-md-preview.md-pv-*, .ed-scroll.md-pv-*` 12 组选择器（a377 把 `.ed-scroll.md-pv-*` 加进了全部配色档）；`web/style.css:479` `.ed-scroll { background: var(--note-bg); padding: 12px 0; }`
- 结构事实：`.ed-scroll` 是**每个编辑器 tab 模板都有的滚动容器**（editor.js:173 `<div class="ed-scroll"><div class="ed-holder"></div></div>`），不是笔记专属。

**证据**：
1. 代码直读：`_mdPvSetTheme(t)` 无形态过滤，遍历**全部** `.ed-scroll` 挂 `md-pv-<id>` 类——代码编辑 tab（.py/.txt/.bat）、文本 tab 全部命中；a377 只给 isNote tab 做了打开即应用（editor.js:313），但全局 setTheme 是**跨形态广播**。
2. **真机复现**（CDP，打开 `run.bat` 代码编辑 tab）：污染前 computed background=`rgb(221,216,224)`（主题默认 --note-bg）；`window._mdPvSetTheme('sepia', false)` 后：**classList 变为 `ed-scroll md-pv-sepia`、computed background=`rgb(244,236,216)`**（亮色纸底出现在暗色 UI 的代码编辑 tab 上下边带）。
3. 一致性破坏：广播只影响**当时已打开**的 tab——污染后新开的 .py tab 无类（恢复默认底色），同一窗口里新旧 tab 底色不一致；且持久化主题（当前=dracula）下每次用户在设置页/工具栏改一次预览配色，全部编辑器 tab 周边底色跟随变色（ Monaco 本体自绘背景不受影响，视觉表现为编辑区上下 12px 色带与 Monaco 底色割裂）。

**影响面**：分形态显隐矩阵越界——「MD 预览配色」在用户心智里只作用于预览/笔记，实际波及代码/文本编辑形态。无功能损伤（变量只被 .ed-scroll 自身 background 消费）。

**最小修法**：①`_mdPvSetTheme` 的第二行遍历加形态守卫（只处理 isNote tab 的 sc，或新增专用锚类 `.ed-scroll.note-pv` 仅笔记 tab 挂，选择器随之收紧）；②或 CSS 侧把 `.ed-scroll.md-pv-*` 收窄为 `.note-tab .ed-scroll.md-pv-*`。

---

### S-B3（P3）：ed-lang 下拉 Makefile 死选项——选项表与 vendored Monaco 语言注册表不对齐【真机实证】

**位置**：`web/js/editor.js:140`（`<option value="makefile">Makefile</option>`，a376 新增 24 项下拉）↔ `web/js/monaco-bridge.js:22`（`'.mak': 'makefile', '.mk': 'makefile'`，存量映射）↔ `vendor/monaco/min/vs/editor/editor.main.js`（makefile 出现次数 **0**）。

**证据**：
1. **真机（CDP）**：`monaco.languages.getLanguages()` 返回 91 个 id，逐一对照下拉 24 个 value——**仅 `makefile` 不在**；其余 22 个高亮语言 + plaintext 全部在场（shell/python/c/cpp/javascript/typescript/json/yaml/xml/html/css/sql/java/rust/go/bat/powershell/perl/lua/markdown/ini 逐个确认 `id:"…"` 已注册；`c` 亦在场）。
2. 行为链：选 Makefile → `_edBindLangSel.onchange` → `monacoLangFor(label,'makefile')` 原样返回 'makefile' → `setModelLanguage(model,'makefile')` → monaco 无该语言注册 → **无 tokenizer、零高亮**，与「纯文本」视觉完全相同——用户无从分辨"选了但没效果"还是"文件本来就没语法"。
3. 存量同源：`monacoLangFor('makefile')`/`.mk`/`.mak` 映射早于本批提交（MONACO_LANG 一直指向不存在的语言，makefile 从未真正高亮过）——a376 把这个坏 id **暴露成了用户可选的显式选项**，把静默缺陷变成了交互面上的死项。

**最小修法**：短期——下拉删去 Makefile 项（或 value 改 `plaintext` 并把标签写成「Makefile（纯文本）」，至少自洽）；长期——vendor 补 makefile Monarch 包（monaco 官方无此语言，需第三方 grammar），与 cpp/shell 本地补丁同目录登记「升级重拷需重打」注释。

---

### S-B4（P3）：fsym 面板首拉期间输入的过滤词被全量覆盖【真机限速复现】

**位置**：`web/js/nav.js` showFileSymbols——fetch 链 ：396-408（resolve 后无条件 `all = j.items; _full = j.items; render();`）↔ input 过滤器 ：410-419（`all = q ? _full.filter(...) : _full; render()`）↔ `_full` 声明 ：401。

**证据**：
1. 代码直读：面板打开即发 `/api/nav/symbols?scope=file&file=<path>&q=`；用户在 resolve 前输入 → 160ms 防抖触发过滤器 → `_full` 还是 `[]` → `all=[]` → 列表清空；fetch resolve 后 then 回调**不检查 input 当前值**，直接 `all=j.items; render()` → **全量列表覆盖过滤结果**，输入框里残留的过滤词与列表完全无关，直到下一次按键才重新生效。
2. **真机复现**（CDP，`Network.emulateNetworkConditions latency=1500`，models.py，库内 3 符号）：
   - 基线（不限速）：开面板渲染 3 行 ✓（log / _models_cache / available_models）；
   - 限速 + 开面板 0.25s 后输入 'zzzz'：pending 态 rows=0（对空 _full 过滤）；
   - resolve 后：**input 仍为 'zzzz'，列表显示 3 行全量**——过滤词被丢弃，实证竞态成立。
3. 触发面：R33 实测大库冷态首拉 0.5-2.2s（a384 后端倒排+a391/392 后热态收窄至 25ms 级，但**服务器忙/冷缓存/慢盘时窗口仍在**）——恰是用户"打开就打字"的高频操作序。

**最小修法**（一行）：then 回调的渲染统一走过滤通道——`const q = input.value.trim().toLowerCase(); all = q ? j.items.filter(it => it.name.toLowerCase().includes(q)) : j.items; _full = j.items; selIdx = 0; render();`

---

### S-B5（P4）：shebang ruby 探测结果在下拉无对应选项——显示「自动」实际 ruby 高亮【真机双证】

**位置**：`web/js/monaco-bridge.js:56`（`if (/\bruby\b/.test(first)) return 'ruby';`）↔ `web/js/editor.js:124-167`（ed-lang 24 选项**无 ruby**）。

**证据**：真机（CDP）：`detectLangByShebang('#!/usr/bin/ruby\nputs 1')` → **'ruby'**；`monaco.languages.getLanguages()` 含 ruby（vendored basic-languages 有 ruby 目录）→ conn.langOverride='ruby' → monacoCreate 按 ruby 建 model，**高亮生效**；但 `_edBindLangSel` 的 `sel.value = conn.langOverride` 赋给无匹配 option 的 select → 值回落 ''（首项「语言：自动」）——**UI 显示自动、实际 ruby**。javascript（node）分支无此问题（下拉有 javascript）。

**影响面**：无后缀 ruby 脚本（`#!/usr/bin/env ruby`）——小众但存在；显示错位会让用户误以为语言决策没生效而手动重选（重选后持久化的是下拉里有的值，行为反而变对）。

**最小修法**：`detectLangByShebang` 收敛到下拉已有的语言集合（删 ruby 分支，或下拉补 `<option value="ruby">Ruby</option>`——monaco 侧已就绪，一行）。

---

### S-B6（P4）：分发服务「未运行」分支残留 `⚪` 彩色 emoji——a373 铁律残留

**位置**：`web/js/settings.js:1682` `` : `⚪ 未运行 · 分发目录 ${esc(j.dir)}${ver}` ``（`_stRenderUpdatePane` 的 upSrvInfo）。

**证据**：a373（0506e57）铁律清零把同函数的**运行中分支** 🟢 换成了 `ICO16.dotOn` SVG（本轮 diff 可见），**未运行分支的 ⚪（U+26AA WHITE CIRCLE）漏改**。U+26AA 属 Emoji_Presentation=Yes——WebView2/Chromium 默认彩色 emoji 渲染（与 ✓✗⟳▾ 等单色文本字形不同类）。a373 提交信息的豁免清单（✓✗⟳▾）不含 ⚪；本轮全 web/ JS 扫描仅此一处彩色 emoji 残留（其余命中 ▶/⬇/■ 均 Emoji_Presentation=No 文本字形，属既有豁免类）。

**最小修法**：换 `ICO16.dotOff`（icons.js:83 在场）+ neutral 色 span，与运行中分支的 dotOn 写法对称——一行。

---

### S-B7（P4）：跳转补链 `_edJumpFresh` 无 tab 存活护栏——关 tab 后误弹「重读失败」/「已重新加载」

**位置**：`web/js/editor.js:1236-1251`（`_edJumpFresh`：await stat → await `_edReloadFromDisk`，无 `connections[conn.portId] === conn` 检查）↔ :1202-1228（`_edReloadFromDisk`：`conn.monaco.setValue` 无 dispose 防护，catch 里 showBanner('重读失败: '+e)）。

**证据**：
1. 时序链：`openFileSmart` 去重分支 `switchTab` 后 `await _edJumpFresh(_c)`（两次网络往返：/api/ed/stat + 命中改动再 /api/ed/open）→ 之后 `jump()`。窗口内用户关闭该 tab：`_edCloseNow`（editor.js:1427）先 `conn.monaco.dispose()` 再 dispose model（:1436-1456）——而 `_edReloadFromDisk` 的 await 已在途，恢复执行后对 **disposed editor/model 调 setValue** → monaco 抛 "Model is disposed" → 被 `_edReloadFromDisk` 的 catch 捕获 → **对一个已不存在的 tab 弹红色「重读失败: Error: Model is disposed…」banner**。若 setValue 恰在 dispose 前完成，则关 tab 后还弹「已重新加载 ××」成功 banner。`jump()` 自身有存活护栏（editor.js:2291 `connections[conn.portId] === conn`），但补链前半段没有。
2. 附带：双击引用等快速两次跳转 → 两个 `_edJumpFresh` 并发 → 双 stat + 双 reload + 双 banner（幂等但嘈杂）。
3. 窗口=两次本地 fetch（正常数 ms~数十 ms；后端忙/大文件 stat 慢时放宽）。对比同族先例：`_edCheckDiskChanged` 有 `wrap.style.display==='none'` 跳过、`_edCloseNow` 专清 diskWatchTimer——本函数是链条里唯一没接存活护栏的新增异步点。

**最小修法**：`_edJumpFresh` 在 stat resolve 后、reload 前加一行 `if (connections[conn.portId] !== conn) return;`；`_edReloadFromDisk` 的各写点（setValue/banner）前同样判活（与 jump 同款检查）。

---

### S-B8（P4）：hover 四反引号围栏对 ≥4 连反引号 snippet 仍可被闭合（R33-3 修法边界残留）

**位置**：`web/js/nav.js:633-636` `'````\n' + (c.snippet || '') + '\n````\n\n'`（R33-3 四反引号围栏）。

**证据**：CommonMark 闭合栏规则是"**不短于**开栏长度的连续反引号行"——四反引号开栏挡住了 3 反引号（R33-3 实锤场景已闭环），但 snippet 含**恰好 ≥4 个连续反引号的行**（如 JS 模板串里嵌四反引号、markdown 语法示例代码）时仍会提前闭合代码块，路径行字面化（R33-3 的原始症状在更窄输入上重现）。触发面比原实锤更窄（源码中 4 连反引号罕见），无安全面（isTrusted:false，面板内渲染）。

**最小修法**：动态围栏——计算 snippet 内最长反引号串 n，围栏用 n+1 个（`'`'`.repeat(n+1)`），一处三行；或文档化接受该残留。

---

### S-B9（P4）：fsym 面板跳转不入导航历史——与工作区符号跳转行为不一致

**位置**：`web/js/nav.js:380`（row.onclick）与 ：416-421（Enter 分支）——均裸调 `openFileSmart(it.path, …, { selectLine: true })`；对照组 ：323（工作区符号面板 go）走 `_jumpOpen(ed, it.path, …)` 入栈。

**证据**：代码直读。同为"符号跳转"类动作（a360R 注释自述只在「转到定义、引用点击、工作区符号点击」压栈），Ctrl+Shift+O 的跳转（含跨行、常到文件另一端）被排除在 Alt+←/→ 历史之外——用户从文件头跳到文件尾的函数后再按 Alt+← 回不去。VSCode 的 workbench.action.navigateBack 同样记录文件内符号跳转。

**最小修法**：两处改 `_jumpOpen(ed, it.path, { line: …, col: 1, selectLine: true })`（ed 在闭包内可得）——一行×2。

---

## 三、存疑区（非实锤，供下轮跟踪/复核）

1. **nav.js keydown 的 fsym 分支缺 `return`**（:712-714）：`showFileSymbols(ed)` 执行后**继续**落入 back/fwd 判定块。默认键位无交集；设置页冲突检测（6 键互斥）挡住了用户把 fsym 与 back/fwd 配成同键——两道防线都绕开时才会双触发（如后端 nav_keys 被手改成 fsym=alt+arrowleft）。防御缺口，非现实触发。
2. **`navJumpTo`/`_navStep` 死分支**：openFileSmart 是 async 恒返回 Promise → navJumpTo 的 `return true` 兜底分支与 `_navStep` 的 `r === false` 同步 continue 分支永不可达（真实失败全部走 `.then(ok=false)` 路径，语义等价）。死代码非缺陷。
3. **`matchKey` 把 metaKey 计入 ctrl**（:531 `hasCtrl = !!(e.ctrlKey || e.metaKey)`）：Windows 单_modifier 环境无实感；若未来 macOS 版且用户配 Meta 系键会出现 Ctrl 与 Meta 互相误触。
4. **editor 去重 `_normPath` 全串小写**（editor.js:81）：大小写**敏感**的 UNC 共享（Linux Samba 默认）上 `\\srv\share\A.txt` 与 `\\srv\share\a.txt` 若真共存会被去重合并。Windows 语义取舍（a374 已论证 NTFS 无此形态），跨平台共享目录场景理论残留。
5. **`hg-ed-lang-override` 无上限增长**（editor.js:435-446）：按路径累积、永不修剪——条目极小，十万次手选才到 MB 级，观察即可。
6. **`_hoverCache` >120 全量 clear**（nav.js:600）：非 LRU，热词缓存可能被一次大扫除全丢——悬停低频，影响可忽略。
7. **proxy-panel.js:636 `⚠ ` → `' '`**：删 emoji 时留了一个前导空格（`"> 未检测到…"`），纯空白瑕疵。
8. **bit-calc.js:706 `'计算失败：' + (j.err || '')`**：err 为空时尾冒号悬空（原写法兜底文案 '计算失败' 反而完整）。
9. **`_edJumpFresh` 每次跳转固定一次 stat 往返**：去重跳转低频+本地 stat 廉价（注释已自证），不加缓存是正确取舍；仅提示大文件在极慢后端下 F12 体感或增 10-50ms。
10. **`_tvScrollToPath` 侧栏隐藏期 120ms 轮询 2s**：有界（a375R 已加兜底），仅指出频繁切 tab 时可能并发多个 tick 链——apply() 幂等，无害。

---

## 四、通过清单（打了什么、没炸什么——核对后无问题项）

- **vendor cpp.js 三规则**（a387）：捕获组与 token 数组严格对齐——struct 规则 3 组 3 token（`["keyword","","entity.name.type"]`）、#define 规则 2 组 2 token（`["keyword.directive","entity.name.function"]`）、函数前瞻规则用 cases 对象（无数组错位）；插入位置均在通用 ident 规则**之前**（生效前提）；keyword 优先不误伤 `if(`/`while(`；无捕获组挂 token 数组的历史坑未复发；tokenPostfix ".cpp" 与主题前缀匹配兼容（真机 R35 已验色值，本轮无改动回归）。
- **vendor shell.js 转义规则**（a376）：`dblStringBody` 头部插入 `[/\\[\\"$`]/,"string"]`——`\"`/`\$`/`` \` ``/`\\` 整体吞入字符串态，不再提前 `@popall`；未破坏单引号 body 与 parameters/heredoc 态；正则转义正确（char class 含反斜杠自匹配）。
- **fcpk-plus/fcpk-plus-dark 两态主题**（a387）：`_monacoDefinePlusThemes` 在 monacoInit 的 require 回调内注册一次（`_monacoReady` 单例保证）；`inherit:true` + `colors:{}` 完整继承基底；亮侧色值 795E26/267F99、暗侧 DCDCAA/4EC9B0 与 VSCode Light+/Dark+ 对齐；全库仅一处 `setTheme` 调用点，无残留 'vs'/'vs-dark' 硬编码；custom 分支随 `_customData.light` 正确分流。
- **stickyScroll/bracketPairColorization/guides opts**（a383）：monacoCreate 选项表三项齐带，与 vendored 0.52 能力匹配；未破坏 20MB 大文件降级链（largeFileSize 分支在先）。
- **`monacoLangFor(name, override)`**：override 直通无校验——配未知 id（如手改 localStorage）时 monaco 静默按纯文本渲染，不抛异常不炸 tab（安全侧）。`detectLangByShebang` 仅在 `monacoLangFor(label)==='plaintext'` 时启用，有后缀文件零行为变化；`split('\n',1)` 无全量扫描开销；bash/zsh/ksh/ash/dash/sh/python/perl/node/ruby/lua 匹配序正确（shell 先于 python，`#!/usr/bin/env python3` 命中 python）。
- **语言记忆读写**（a376+R31-1）：读写同键 `_edNormPath`（反斜杠→正斜杠+小写），跨形态重开命中；JSON.parse 双层 `|| {}` 兜底 null/'[]'/坏 JSON；整个读写包 try/catch（localStorage 禁用态安全）；「自动」=delete 记忆 ✓。
- **ed-lang 24 项 vs 注册表**：除 S-B3 的 makefile 外，22 个高亮语言逐一在 vendored basic-languages/editor.main.js 确认注册（T1 真机 91 id 对照）；`_edBindLangSel` 幂等（dataset.bound）、绑定在 monacoCreate 成功之后（降级 textarea 路径不显示下拉）✓。
- **buildEditorTab 去重归一**（a374）：`_normPath` 两侧同函数同口径；`extPath||c.extPath` 前置守卫排除双空比较；label 大小写不敏感 + extPath 归一相等才劫持，同名不同路径 `continue` 新开 tab（a238 语义保持）；空串 vs null 的形态差被守卫吸收 ✓。
- **`_edJumpFresh` mtime 口径**：/api/ed/open 与 /api/ed/stat 均产 `os.path.getmtime`/`st.st_mtime`（秒浮点，editor_files.py:310/:332），epsilon 0.001 与后端保存 CAS（:428）同源——无单位错配、无误触发 reload。
- **openFileSmart 返回值链**（a375R/a380R/a382R/a375R）：true/false/'cancelled' 三态在 `_jumpOpen`（显式排除 'cancelled'）与 `_navStep`（cancelled 回退游标 + 幂等 prevCur 守卫）两端全处理；Office 分支后置到存在性闸门之后；noFallback 早于降级分支（「类型」文案不再误判二进制）；失败路径统一 return false ✓。
- **导航历史栈**：双端入栈（from+target）、同位置去重、`splice(cur+1)` 浏览器语义、MAX 200 封顶、`_jumpSeq` 乱序丢弃、预算化递归（a377R）✓；Alt+←/→ 接管矩阵（monaco 接管/xterm 放行/plain input 放行/其余接管）与注释一致 ✓。
- **Ctrl+Shift+O 面板本体**（除 S-B4/S-B9）：面板生命周期监听随 DOM 移除一起回收、`_symTimer` 关面板即清、Esc 停止冒泡、ArrowUp/Down 边界 clamp、selIdx 过滤后复位 ✓；键盘真键链（focus→capture keydown→面板开→fetch 发出）真机走通。
- **Hover 主链**（除 S-B8）：词级缓存 60s、容量 120 封顶、fetch catch→null（悬停永不抛）、`/^[A-Za-z]:/` 盘符守卫、range 用 word 边界 ✓；`_h` 的 html=true 白名单面——全部调用点为 ICO16 常量+静态文案，无后端数据进 innerHTML。
- **键位体系**（a360R/a383/R33-4）：NAV_KEYS 6 键、applyKeys 全键热应用、keyLabel 方向键箭头、录制白名单（字母/数字/F1-F12 + 方向键必须带修饰 + 方向键仅限 back/fwd）、冲突检测 `Set.size !== vals.length` 随键数自适应、恢复默认 `_ORDER` 全键 + saveNow 落库全键 banner ✓；录制 15s 超时经 `let onKey=null` 复位守卫，正常录完不误弹「超时」✓；a378R save/reset 同列流式对齐 + a382R `_showSave` 显式 flex 复验保持 ✓。
- **file-tree**：`_tvNormPath` UNC 前缀保全/盘根尾分隔符保留/重复分隔符折叠（真机三形态 ✓）；idxLower O(1) 大小写兜底随 rebuild 重建；treeReveal 根匹配最深优先、逐层真实大小写纠正、`o._seq` 并发丢弃、隐藏期滚动轮询 2s 有界；tree-search 改走 `window.treeReveal` 包装版（序号链闭合）✓；tree-fileops normKey 小写化全调用方语义安全（R31 已验）✓。
- **log-viewer.js**：`_np` 去重与 editor 同口径（正斜杠+小写），gotoLogLine 三路径透传保持（R31 口径）✓。
- **settings.js 其余改动**：CPU 卡迁移（appearance 残块删除 + term pane 注入 + `_stBoostCard` 调用点同步）零残留 ✓；`#stPane .dd-cur + .dd-cur` 分割线只作用于兄弟块、首块无边 ✓；⚠/❌/✅/✨/🟢 全部清除且 esc() 覆盖面未回退（j.latest/j.notes/j.err/j.url 均 esc）✓。
- **harness 五文件**：emoji 清理（ICO16.eye/users/book/folder/camera/file/clipboard 全部键在 icons.js `_D` 中在场，ICO16 由统一循环构建无漏键）；tools.js '回答：' 前缀幂等两端一致（R30-1 闭环保持）；vcs.js symlink_hidden 计数链（j1/j2 两路落 D + 展示拼接）✓；managers.js 提示词 scope 选项文案改文字、onoff 徽标配色 span 包裹 ICO（无 emoji 回流）✓。
- **emoji 全量复扫**：web/ 渲染路径彩色 emoji 仅剩 S-B6 一处 ⚪；▶/⬇/■/⠿/⎇/↺/✓/✗/⟳/▾ 均 Emoji_Presentation=No 文本字形（a373 豁免类）✓。

---

## 五、方法说明

- **白盒**：`git diff 8251c58..HEAD` 逐文件精读（editor/nav/settings/monaco-bridge/file-tree/log-viewer/harness×5/tree-search/tree-fileops/sidebar/bit-calc/resources/proxy-panel/style.css + vendor cpp/shell 补丁），并回读各文件当前实现（matchKey、_renderState、_edReloadFromDisk、showFileSymbols、_tvNormPath、MONACO_LANG、icons.js `_D` 键表、editor_files.py 的 mtime/CAS 口径）与历史轮报告（audit_round30-35，已知项全部对齐不重报）。
- **真机**：CDP 9223 独立新 target ×7（rb36_verify*.py，Write 落盘后 python 执行，已删）：T0 打开真 tab + Monaco 就绪；T1 语言注册表 91 id 对照（S-B3）；T2 shebang/选项表对照（S-B5）；T3 md-pv 背色 computed 前后对比 + DOM 还原（S-B2）；T4/T4R/T7 限速 1.5s 竞态复现（S-B4）；T5/T5R 下拉取消行为捕获（S-B1）；T6 _tvNormPath 三形态；诊断脚本含 Response.json 打点与异常捕获（排除面板假死后确认 S-B4 真因是测试选择器失配——教训：**DOM 断言勿用内联样式子串选择器 `[style*="…"]`，Chrome 序列化带空格；用结构关系（.dd-cur 的 lastElementChild）**，与 R32"对齐必须双维"同类的验证方法学条目）。
- **清理**：所有测试在独立 target 内完成并关闭 target；md-pv 类已从 DOM 摘除、`_ddConfirm` mock 还原、`persist=false` 全程不落库、`hg-ed-lang-override`/nav_keys 未触碰、根库只读（终态 backend=sqlite/tags.db 完好）；工作区零文件改动（审计脚本与 diff 快照临时文件已删）。
- **已知项边界**：R30~R35 实锤（双前缀、冲突检测、S32-1、S33-1~4、S34-1~3、S35-1~6、S36-1）全部在其声明闭环面复验未回归；本报告 9 件与既有台账零重叠（S-B8 为 R33-3 的修法边界残留、S-B4 为 R33-1 改造的次生竞态，均属新问题非复发）。
