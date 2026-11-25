# 补丁审计报告 R3 · 前端组（白盒）

> 审计对象：doc/patch-log.md【第 3 轮修订·前端组】（R3-1 ~ R3-6）+ 附带项（R4-4 归入 P-21 的 settings.js:788/:1661 两处 ⬇）。
> 审计方法：①源码现状逐字核对（锚点漂移必查——r1/r2 两次教训；git 基线：web/ 与 HEAD 一致，仅 doc/ 未跟踪，r1/r2 所见行号全部复现，无漂移）②node 实证（脚本与补后产物落系统 TEMP\r3-audit-frontend，未入仓库：字面应用模拟 + node --check ×4 文件 + S-B8 围栏 4 用例回归 + matchAll 语义演示）③CDP 9223 只读验证（新开独立 target，验毕即关：运行时事实 4 项 + served bundle 与仓库字节一致性）④r2 裁决三缺陷（R2-1）逐项关闭确认。
> 本文件只裁决补丁提案，未修改任何工具源码。

---

## 结论先行

**6 件：PASS 1 · PASS with notes 5 · FAIL 0。附带项（R4-4 settings.js 两处 ⬇）核对通过并给出替换 diff。**

| 修订项 | 对应补丁 | 裁决 | 一句话 |
|---|---|---|---|
| R3-1 | P-25 终修 | **PASS with notes** | R2-1 三缺陷全部真修（标题头入 `-` 段 / `_m[0].length` / 引注转实），4 用例本轮独立复跑 ALL PASS；notes：`:633-634` R33-3 旧注释未入 `-` 段（残留面）+ diff 缩进统一 +2 漂移 |
| R3-2 | P-26 终稿 | **PASS with notes** | closeHexTab 死代码删除成立（全仓零命中 + 运行时 `typeof=undefined` 实证），锚点与 R2-2 `+` 段逐字对齐；notes：R2-2 头注释「四类有专属关闭函数」未同步更正，与本补丁自己的实证矛盾 |
| R3-3 | P-5 补强 | **PASS with notes** | :883/:884 两出口复位落实正确、三出口对称成立、补后语法通过；notes：`_curBk` 三轮未采纳（终态同式 ×3）+ 「面关闭」声明过强（存在第 4 失步出口=切档任务异步失败，见新发现 1） |
| R3-4 | P-14 补强 | **PASS with notes** | j2 后主护栏落点实测先于全部写点、monaco 分支护栏保留（双位并存）、S-B7 主场景覆盖闭环；notes：R2-5 承诺的 _edCheckDiskChanged stat 窗口护栏至今无 diff 形态（承诺滑落，见新发现 2） |
| R3-5 | P-21 补齐 | **PASS** | :1682 锚点逐字、ICO16.dotOff / `--muted` 键与变量双实证（静态+运行时）、与 :1680 dotOn span 结构逐项对称，零新问题零遗漏 |
| R3-6 | P-21 附带 | **PASS with notes** | 勘误推迟处置成立、⬇/⚪ 应清判定正确；notes：勘误连续两轮推迟且第 5 轮审计范围清单未登记，收官若不显式核对有三次滑落风险 |
| 附带 R4-4 | P-21 清单扩充 | **核对通过** | settings.js:788/:1661 行号/内容/出现次数全部吻合（⬇ 恰 2 处）；替换 diff 见附带项一节 |

---

## 逐件裁决详情

### R3-1（R2-1 FAIL 终修：hover 动态围栏 `md.value = IIFE(...)` 整体赋值 + `_m[0].length`）—— **PASS with notes**

**① 是否正确解决问题 —— 是（R2-1 三缺陷逐一确认关闭，node 复跑 ALL PASS）**

- **锚点现状核对（任务指定点①）**：nav.js:631-636 现状 = :631-632 标题头两行 + :633-634 R33-3 注释 + :635 围栏行 + :636 路径行。R3-1 diff 的 4 行 `-`（标题头 2 + 围栏 + 路径行）与文件 **内容逐字吻合**（本审计以 trim 后全等断言逐行核实）——r2 教训要求的「标题头+围栏+路径行整体替换」**删行范围与声称一致，标题头重复根因（R2-1 缺陷 A）已修**。
- **`_m[0].length` 语义（任务指定点③）**：node 实证 `matchAll(/`+/g)` 匹配对象无捕获组时 `.length` 恒 1、`m[0].length` 为实长（4 连反引号串：`length===1` vs `m[0].length===4`）——R2-1 缺陷 B（`_m.length` 回归）已修。补后文件无 `_m.length` 残写（正则断言通过）。
- **引注核实（R2-1 缺陷 C）**：台账括注「r2 审计员已按此形态 node 复跑 4 用例 ALL PASS——含 S-B8 主场景」与 patch-review-r2-frontend.md 第 43/176 行（"正确接线的 IIFE 版（`md.value = ((...)=>{...})(...)` + `_m[0].length`）4 用例 ALL PASS……两版逐字节等价"）相符——**引注由失实转实**。
- **本轮独立复现（任务指定点②）**：将 R3-1 `+` 段（台账逐字）+ R3-3 两出口字面应用到 nav.js 副本，**node --check 通过**（两种插入位变体均过——`-` 段不连续导致 + 块落位存在先/后注释两种解读，见 notes）；S-B8 围栏 4 用例（普通 snippet / 4 连反引号行 / 空 snippet / 8 连反引号串）全部通过：**开栏=闭栏=4/5/4/9**（恒 = 内容最长反引号串+1）、标题头唯一、内容区无可闭合行（CommonMark 闭合栏须 ≥ 开栏：`/^ {0,3}(`+)[ \t]*$/` 且长度 ≥ 开栏的行逐一排查为空）、**IIFE 版与语句前置版逐字节等价**——与 r2 预证结论一致。`_max=3` 初值保留 R33-3 原场景（0 缩进裸 ``` 不可闭合）。

**② 是否引入新问题 —— 无功能性问题，两处工艺瑕疵（notes）**

- **notes-1（`:633-634` 残留面）**：`-` 段 4 行跳过了中间的 R33-3 注释两行（:633-634），补后两变体中该注释均残留。其内容（"四反引号围栏，源码内 ``` 无法误闭合"）描述的是被替换的固定 4 反引号方案，与新代码（动态围栏）直接矛盾——陈旧注释与新注释并置。**非功能缺陷**（纯注释，node --check 通过即静默无损），但 r2 的终修要求原话是"删 :631-636 **全部**"——R3-1 满足了代码 4 行，差注释 2 行。落地时应顺手删掉这两行（或 `-` 段补入），即完全闭合 r2 要求。
- **notes-2（机械不可应用 + 缩进漂移）**：`-` 段 4 行在文件中不连续（中间夹注释）且 diff 未以上下文行标注 → `git apply`/`patch` 类工具字面应用必失配；且 4 行 `-` 缩进统一 +2（文件 8/10/10/10 空格 vs 台账 10/12/12/12），`+` 段新语句缩进 10 与上下文 `const md`（:630，8 空格）不一致。台账惯例是语义应用（r1/r2 同法），不受影响；落地时按文件实际缩进（8/10）对齐即可。**记录此点是为防"机械套 diff 失败被误判为锚点漂移"**。

**③ 是否遗漏更优方案 —— 否（可接受取舍）**

r2 首推语句前置版（少一层 IIFE 嵌套），R3-1 选择了 IIFE——但 r2 明文允许"如坚持 IIFE 则必须：删 :631-636 全部 + `+` 段以 `md.value = ` 开头 + `_m.length` 改回 `_m[0].length`"，R3-1 满足后两条、第一条差注释两行（见 notes-1），且该形态 r2 已预证、本轮复证与语句版逐字节等价。**非遗漏，取舍得当**。

---

### R3-2（R2-2 notes 落实：closeHexTab 死代码删行 + 注释实证表述）—— **PASS with notes**

**① 是否正确解决问题 —— 是**

- **现状锚点核对（任务指定点）**：R3-2 的 `-` 段与 R2-2 `+` 段的 4 行**逐字对齐**（本轮模拟"先 R2-2 插入、再 R3-2 重写"两步应用，replace 单点唯一命中），外层 `}` 上下文保留成立；插入位 sidebar.js:113 `function closeConnection(portId) {`（单参数，R2-2 已核）现状复现。
- **closeHexTab 死代码复核**：全仓 grep（web/ + src/）零命中；CDP 运行时 `typeof closeHexTab === 'undefined'` 实锤——该行 `typeof closeHexTab === 'function'` 恒 false 不可达，删除正确。
- **正则与前缀矩阵复核**：`/^(edit|hex|diff|bindiff):/` 四前缀注册点现状复现——`edit:`(editor.js:94) / `hex:`(hex-viewer.js:32) / `diff:`(diff-viewer.js:174) / `bindiff:`(hex-diff.js:205)；无误伤（`editor:`/`harness:`/`log:` 不命中，r2 已推演，本轮无漂移）。
- **新注释实证表述核实**：「产品路径四类统一走 closeEditorTab（sidebar.js:198/:233 实证）」——:198 `isEdit = kind==='editor'||'hex'||'diff'||'bindiff'`、:233 `else if (isEdit) closeEditorTab(pid);` 逐字在场，引注成立。closeEditorTab（editor.js:1384 顶层 async function）存在；closeConnection 调用点仍仅 sidebar.js:235 + terminal-core.js:76 两处，防御定位（D-3）不变。
- **补后语法**：R2-2+R3-2 终态应用后 node --check 通过；`typeof closeEditorTab` 存在性守卫保留（closeEditorTab 缺位时回落原分发逻辑，语义保守正确）。

**② 是否引入新问题 —— 一处注释残留（notes）**

- **notes（头注释矛盾残留）**：R2-2 三行头注释中第 3 行「——四类有**专属关闭函数**的 tab 统一转发（r1 审计员裁定 kind 列表）」未被 R3-2 重写保留下来——与本补丁自己的实证（四类**无**专属函数、统一 closeEditorTab）直接矛盾。一个专门修"失实注释"的补丁，自己头上留了一条失实注释。建议头注释第 3 行同步改为如「——四类统一转发 closeEditorTab（无专属关闭函数，r3 实证 closeHexTab 不存在）」。纯文档面，不影响裁决等级。

**③ 是否遗漏更优方案 —— 否**。r1 的 conn.meta.kind 判定案与正则案 r2 已裁等价（正则还能拦未注册 id）；hex-diff.js:180 `bindiff:loading:*` 瞬态 tab 命中正则后走 closeEditorTab :1386 `if (!conn) return` 静默返回（r2 新发现 2，本轮维持）。

---

### R3-3（R2-3 notes 落实：失败复位覆盖 :883/:884 两出口）—— **PASS with notes**

**① 是否正确解决问题 —— 是**

- **现状行号核对（任务指定点）**：:883 `showBanner(d2.ok ? ... : ('切换失败：' + ...), 3000, !d2.ok);` 与 :884 `} catch (e) { showBanner('切换失败: ' + e, 3000, true); }` 均逐字命中（补后 node --check 通过；catch 内加行后闭合括号落位正确）。
- **m 闭包可得性**：bkSel 定义于 `_renderState`（:866 起），`m` 是 `_renderState` 入参，onchange 箭头函数同闭包——:869 `const _curBk = m.backend || ...` 同作用域先例实证。复位表达式与 :869 同式同值，与初始 selected 渲染（:870-871）同源，取值正确性等价于初始渲染。
- **三出口对称完整性（任务指定点）**：①确认取消 → P-5 hunk 置 `bkSel.value = ...; return;`（复位）；②`!d2.ok` → R3-3 `if (!d2.ok) bkSel.value = ...`（:883 后，try 内）；③catch → R3-3 catch 内复位（:884）。**三出口对称成立**。

**② 是否引入新问题 —— 无功能性问题，两条 notes**

- **notes-1（`_curBk` 连续三轮未采纳）**：r1/r2 两轮建议复位写 `bkSel.value = _curBk;`（:869 已算好同值常量），R3-3 仍写全式。最终态（P-5+R3-3 应用后）该式出现 **3 处**（取消分支 + :883 + :884）。维护性欠账：改档位兜底逻辑时要同步三处。
- **notes-2（行号记账）**：P-5 取消分支 hunk（1 行换 5 行）先落地后 :883/:884 实际位移 +4（→ :887/:888）。R3-3 锚点内容唯一、应用无歧义，仅台账行号引用以"补 P-5 前"口径记账，复核时注意。
- 附带确认：P-5 hunk 的上下文行含 r1 已指出的 sqlite 文案漂移（:876 实际含"；查询 0~4ms/内存 ~50MB"），属 P-5 历史遗留（r2 已记"应用时按实际文本对齐"），非 R3-3 新问题。

**③ 是否遗漏更优方案 —— 有（边界，降级为新发现 1）**

台账声称「三出口对称后'显示与实际脱节'面关闭」**过强**：三出口只覆盖同步路径。第 4 失步出口 = `d2.ok===true` 后切档任务在后台线程执行（src/nav_api.py `work()`：sqlite 构建 / tags.db 删除），任务失败（catch → `ok=False`）时 meta.json 未变而 bkSel 已停在新值；且前端对切档任务**无轮询**（nav.js:1026 `_renderProgress` 的 800ms 轮询仅服务建索引流，onchange 不进入）→ 失步存续到面板重开/重渲染。连带：成功切换不回写 `m.backend`，同面板会话内第二次切换若失败，复位到的是**过期** `m.backend` 而非当前实际档位。修复方向见新发现区。R3-3 本身对声称范围内的三出口修得正确，故不降 FAIL。

---

### R3-4（R2-5 notes 落实：护栏双位并存——j2 后主护栏 + monaco 分支原护栏保留）—— **PASS with notes**

**① 是否正确解决问题 —— 是（S-B7 主场景覆盖闭环确认）**

- **editor.js 现状核对**：:1210 `const j2 = await r2.json();` / :1211 `if (!j2.ok) { showBanner('重读失败：' + (j2.err || ''), 4000, true); return; }`（diff 中 `...` 省略与实际行吻合）/ :1212 `let content = j2.text;` 逐字命中；插入位 = j2 后、render/setValue 前，**正是 r1 建议位**。
- **落点实测（本轮新增验证）**：将 P-14 两 hunk（_edJumpFresh stat 后 + monaco 分支）+ R3-4 hunk 字面应用后 node --check 通过；在 `_edReloadFromDisk` 函数切片内实测护栏偏移 505 **先于全部写点**（conn.editor.render 680 / conn.monaco.setValue 860 / conn.ta.value 1019 / _edSetBase 1048）——覆盖笔记（editor.render）、monaco（setValue）、textarea 三路全部写面与 _edSetBase/脏标志基准更新。
- **conn.portId 可得性**：conn 对象字面量含 `portId` 属性（editor.js:196），`connections[conn.portId] !== conn` 同款用法先例 :1496/:1511/:2291 在场；closeEditorTab → _edCloseNow 必经 `delete connections[conn.portId]`（:1496，现状在场）→ open 窗口内（甚至调用前）关 tab 一律被护栏捕获。
- **竞态闭环**：护栏（:1212）之后到函数尾**无任何 await**（:1213-1226 全同步）→ JS 单线程下"关 tab"无法楔入护栏与写点之间；护栏前的两个 await（fetch :1209 / json :1210）期间的关闭在护栏处必被捕获。**S-B7 主场景（open 窗口内关 tab → 对 disposed 实例 render/setValue → catch 误报"重读失败"）关闭**。
- **双位并存实测**：monaco 分支原护栏（P-14 hunk2，"disposed 防护"）保留在位——r2 指出的"上移=撤除"次生风险消除。

**② 是否引入新问题 —— 无**

函数头护栏（R2-5 形态）被 j2 后位替代属**等效覆盖**："调用前已关"同样被 j2 后护栏捕获（connections 条目已删），仅多一次无用 fetch（无害早退）。双护栏重复检查 = 早退，无害（r2 ③ 维持）。

**③ 是否遗漏更优方案 —— 无（但有一项承诺滑落，见新发现 2）**

r1 原案"单点 j2 后替代 monaco 分支位"与 R3-4"双位并存"等效（重复检查无害），双位更保守，非遗漏。**但** R2-5 作用域承诺的 `_edCheckDiskChanged` stat 窗口"同款一行"（r2 已给插入位：:1169 解析后与 :1183 `conn._dcAsking = true` 置位前之间——本轮现状复核 :1169/:1183 仍在位）在 P-14/R2-5/R3-4 **任何一版 diff 中都不存在**——P-14 按台账应用后该面仍裸奔（死 tab 弹差异弹窗 + `_dcAsking` 挂在已关 conn 上）。归 R2-5→R3-4 链的落实缺口，不计入 R3-4 本体 FAIL，但第 4 轮落地时必须补上。

---

### R3-5（r1 漏项补齐：P-21 dotOff muted 灰 span 包装）—— **PASS**

**① 是否正确解决问题 —— 是（全证据链闭合）**

- **settings.js:1682 现状核对**：`        : `⚪ 未运行 · 分发目录 ${esc(j.dir)}${ver}`;`（8 空格缩进）与 R3-5 `-` 行逐字吻合（仅行尾 CRLF 差异，台账惯例无碍）；⚪ 全文件**唯一**（replace 单点命中）；此行即 P-21 原补丁的 settings.js 落点，R3-5 在 P-21 基础上加包装，台账链自洽。
- **与 dotOn 绿色 span 对称性**：:1680 运行侧 `<span style="color:var(--neon-green);vertical-align:-2px">${ICO16.dotOn}</span>`——R3-5 的 `color:var(--muted);vertical-align:-2px` 与之逐项同构（仅色变量换中性灰），esc(j.dir)/`${ver}` 保留，语义"未运行=中性"正确。
- **ICO16.dotOff 键存在性**：icons.js:83 `dotOff: '<circle cx="8" cy="8" r="4"/>',` 在场，ICO16 由统一循环构建（:87-90）；`_icoWrap` 使用 `stroke="currentColor"`（icons.js:11）→ dotOff 描边圆正确继承 span 的 `--muted` 灰。
- **`--muted` 变量在位**：style.css :12/:67/:79/:91（默认 + 三主题四定义）；CDP 运行时实测 `getComputedStyle` → `#6d7f9d`。

**② 是否引入新问题 —— 无**。包装结构与运行侧先例完全一致，无新样式面。
**③ 是否遗漏更优方案 —— 无**。CSS class 方案反而偏离 dotOn 内联先例制造新差异；r1 建议原样落实。

---

### R3-6（R2-6 notes 落实：audit-b:187 勘误推迟）—— **PASS with notes**

- **文档性核验**：audit-b-frontend.md:187 现状未动（⬇ 仍在"豁免类"清单，逐字复现）——"推迟"属实记录；R3-6 对 ⬇/⚪ 的再判定（均 Emoji_Presentation=Yes、应清）与 P-21 口径一致，正确。
- **notes（滑落风险）**：勘误现已**连续两轮推迟**（R2-6 推迟→R3-6 再推迟至"汇总勘误批/巡查收官补注"），且【第 5 轮审计（r3）范围】清单（patch-log:1267-1271）未含此项——唯一载体是 R3-6 本段文字。r2 曾给过"本轮直接修订 audit-b:187"的选项（audit-b 是审计文档非工具源码，修订不违反铁律），再次推迟可接受但非最优。建议：收官检查单显式登记一行「audit-b:187 ⬇ 移出豁免表」，防第三次滑落。

---

## 附带项：R4-4 归入 P-21 的 settings.js:788/:1661 两处 ⬇（前端组执行项）—— 核对通过，替换 diff 如下

**现状核对**：settings.js:788 `          <button class="btn ghost" id="rsOnlineGo" disabled title="">⬇ 在线安装所选</button>`（模板串内，上一行 :787 rsGo 按钮已有 `${ICO16.wrench}` 插值先例）；settings.js:1661 `    res.innerHTML = '<div class="dd-sub">⬇ 下载并校验中…（内网一般几秒，完成后自动重启）</div>';`（**单引号串**）。⬇ 在 settings.js 全文件恰 2 处（:788/:1661 各 1），行号与 R4-4 声称完全一致；⬇（U+2B07）Emoji_Presentation=Yes 应清，判定正确。

**替换 diff**（按 a373 惯例"要么 SVG 要么不要"）：

```diff
（settings.js:788——资源状态弹窗按钮排）
-          <button class="btn ghost" id="rsOnlineGo" disabled title="">⬇ 在线安装所选</button>
+          <button class="btn ghost" id="rsOnlineGo" disabled title="">在线安装所选</button>
（主选=删：与 P-21 对 update_server.py ⬇ 的同款先例一致——按钮文字"在线安装所选"自足。
  备选=换 SVG：与左侧 rsGo 的 wrench 图标形成"安装对"对称——
  `<button class="btn ghost" id="rsOnlineGo" disabled title=""><span>${ICO16.download}</span> 在线安装所选</button>`
  ICO16.download 键已在场（icons.js:52），模板串内 ${} 插值合法。）

（settings.js:1661——升级进度消息）
-    res.innerHTML = '<div class="dd-sub">⬇ 下载并校验中…（内网一般几秒，完成后自动重启）</div>';
+    res.innerHTML = '<div class="dd-sub">下载并校验中…（内网一般几秒，完成后自动重启）</div>';
（主选=删：文案自足。该行是单引号串且属"消息文案"——icons.js 头注明文
  "消息文案、title 提示、日志正文里的符号是文本，不用本库"，
  故此处**不宜**换 ICO16 SVG；换图标需改引号或 + 拼接，不值。）
```

**P-21 位置列表同步更新**（R4-4 要求"更新 P-21 位置列表"）：

```diff
-**位置**：src/update_server.py:807/828/850（keycap 1️⃣2️⃣3️⃣）、:1006/:1025（⬇）；web/js/settings.js:1682（⚪）
+**位置**：src/update_server.py:807/828/850（keycap 1️⃣2️⃣3️⃣）、:1006/:1025（⬇）；web/js/settings.js:788/:1661（⬇，R4-4 归入）/:1682（⚪ → R3-5 包装 span）
```

（P-21 提议补丁的 settings.js 段相应由 1 行扩为 3 行；:1682 行以 R3-5 的包装 span 形态为准。）

---

## 新发现区（r3 独立发现，非 r1/r2 已知项复读）

1. **切档任务的"第 4 失步出口"（归 R3-3 边界，建议出 P-5c 或并入 P-5 收口）**：bkSel.onchange 三出口复位只覆盖同步路径。`POST /api/nav/reindex` 返回 `{ok:true}` 后切档在后台线程执行（nav_api.py `work()`），失败时 `_state.ok=False` 但 meta.json 未变——前端 bkSel 停在新值且**无轮询自愈**（`_renderProgress` 的 800ms 轮询仅服务建索引流，切档不进入）。连带缺陷：成功切换不回写 `m.backend`，同面板会话内第二次切换失败时复位到**过期档位**。最小修复（一行）：onchange 成功路径 `d2.ok && (m.backend = v)`；彻底修复：切档任务完成后触发 `_renderState` 刷新（或复用任务轮询）。
2. **`_edCheckDiskChanged` stat 窗口护栏承诺滑落（归 P-14 落实链）**：R2-5 明文"同款一行列入本补丁作用域"、r2 给出插入位（:1169 之后、:1183 `conn._dcAsking = true` 之前——本轮现状复核两锚点仍在位），但 P-14/R2-5/R3-4 三版 diff 均未包含该行。P-14 按台账应用后该窗口仍裸奔（S-B7 同族最后一块：stat fetch await 窗口内关 tab → 死 tab 弹差异弹窗 + 状态位挂已关 conn）。第 4 轮落地 P-14 时必须补上，建议插入位 `:1183` 之前（兼防死 tab 弹窗副作用）。
3. **台账 diff 的机械可应用性面（方法学条目）**：本轮 4 件带 diff 的修订中 3 件存在机械应用障碍——R3-1 `-` 段不连续（跳注释）+ 缩进统一 +2 漂移、R3-4 上下文行含 `...` 省略号、R3-2 锚点依赖"先应用 R2-2"的前置态。台账惯例是语义应用（三轮审计同法），不构成缺陷；但落地执行者若用 `git apply` 会误判"锚点漂移"。建议台账在每件 diff 前加一行"语义 diff，按行内容定位应用"声明，或统一补齐上下文行。
4. **served bundle 与仓库字节一致（运行实例结论可迁移）**：CDP 只读实证 `http://127.0.0.1:8867` 服务的 web/js/settings.js、nav.js 与仓库 `web/` 同名文件逐字节相等（v=4.1.0-a392 缓存参数下）——本轮全部静态结论对运行实例直接有效；同时运行时确认 `closeHexTab===undefined`、`closeEditorTab===function`、`ICO16.dotOff` 在场、`--muted=#6d7f9d` 四项事实。注意脚本挂载点为 `/web/js/`（探针首查 `/js/` 得 404，勿误读为 bundle 差异）。

---

## 附：审计过程记录

- 源码核对范围：web/js/nav.js（615-660 / 795-908 / 1000-1075）、web/js/sidebar.js（100-250）、web/js/editor.js（1157-1252 / portId 全查 / 1384-1520 抽查）、web/js/settings.js（770-795 / 1640-1700 / ⚪⬇ 全扫）、web/js/icons.js（1-93）、web/style.css（--muted 定义面）、src/nav_api.py（185-245 切档任务流）、doc/audit-b-frontend.md:187、doc/audit-summary-today.md（#21/#24 行）。
- node 实证（TEMP\r3-audit-frontend，未入仓库）：apply-check.js——①nav.js 字面应用 R3-1（两插入位变体）+ R3-3 → node --check ×2 通过；②sidebar.js 字面应用 R2-2+R3-2 → node --check 通过、closeHexTab 零残引；③editor.js 字面应用 P-14 两 hunk + R3-4 → node --check 通过、护栏-写点次序实测（505 < 680/860/1019/1048）、双位并存确认；④S-B8 围栏 4 用例（4/5/4/9 + 标题唯一 + 无可闭合行 + IIFE=语句版逐字节等价）+ matchAll `.length=1 恒 / m[0].length=实长` 演示。全部断言通过（2 个"FAIL"输出均为检查器设计项：R2-2 头注释残留面（成立）与检查器自身全文件 indexOf 误报（函数切片复测为 PASS，已排除））。
- CDP 9223 只读验证（cdp-probe.js，新开独立 target `?r=r3audit-probe`，验毕 `/json/close` 关闭，未触碰既有 6 个 page）：运行时 `typeof closeHexTab==='undefined'`、`typeof closeEditorTab==='function'`、`ICO16.dotOff` 在场且描边 currentColor、`--muted=#6d7f9d`；served `/web/js/settings.js`、`/web/js/nav.js` 与仓库同名文件**逐字节相等**。
- git 基线：web/ 与 HEAD（db9f27a）一致，仅 doc/ 未跟踪——r1/r2 行号全部复现，**无锚点漂移**；本轮锚点问题仅为 R3-1 的缩进 +2 漂移与 `-` 段跳注释（内容层零漂移）。
