# R8 · 白盒验证轮报告（合入保真度 + 对抗终审）

- **生成**：2026-11-13（R8 收尾）
- **对象**：基线 d9c8886 + 已合入补丁的工作树（`git diff` 9 文件，实测 **+293/−90**；任务书所记 −84 与 git 实测不符，以 `git diff --shortstat` 为准）
- **性质**：**验证轮**——只报告不修复；未改动 `docs/审计补丁台账_2026-11-13/` 以外任何文件；未做任何改变工作树/历史的 git 操作（仅 diff/log/show/grep）
- **依据**：`SUMMARY.md`（终版台账）→ `patches/patch-round-1..6.md` 全部修订链终态（A4''、A8'→A8''、A10'→A10''、A11→A11'、N1→N1'、N4→N4'、P1'→P1''）→ 需要时回查 `rounds/round-1..7-*` 复现口径（B1、W15、W23 的实锤场景）
- **D 系核对**：D1/D1''/D2/D3/D5/D7/D8（及 harness 范围外 D4'）按拍板保持提案未合——grep 证实 `_epochs`、`dispose_all` act、9223、pagehide beacon、per-sid 均不存在于代码——**符合预期，不计漏**。

---

## 一、总体结论

**合入保真度 ≠ 100%**：共 **3 个 hunk 漏合**（全部为「补丁文档里存在、工作树里没有」的确定性补丁 hunk，无错锚点、无语义走样、无多余改动）：

| 编号 | 位置 | 缺失 hunk | 定性 | 后果 |
|---|---|---|---|---|
| **W33** | `web/js/web-panel.js:410-411` | A8 主 hunk：`_webNavigate` 签名参数化 | 合入错误·P2 | **B1（跨 tab 串导航）修复失效**；W15 修复失效；3 个已应用的定向调用点实参被 JS 静默丢弃 |
| **W34** | `web/js/web-panel.js:449` | A8 第三调用点 hunk（switchTab 唤醒路径传 `c`） | 合入错误·P3 | 与补丁终态不符（该处行为当前等价，见 §三.1 依赖分析） |
| **W35** | `web/js/web-panel.js:712` | A10'' 顶栏地址栏反馈 hunk（W23） | 合入错误·P3 | **W23（顶栏误开会话恢复空 tab + 零反馈）修复失效** |

除上述 3 处外，**其余全部 hunk（A1-A7、A9、A11'、A12、A4''、A5、A6、A8'、A8''、A10''面板 hunk、N1'、N2、N3 两处、N4'、N5、P1'' 前后端全部 hunk）逐 hunk 对账干净，语义零走样**。对抗终审四条点名链路（_HIDE_ALL 四点、closeEditorTab 转发闭环、web_proxy 重定向循环、机械笔误排查）全部通过。机械验证独立复核通过。

---

## 二、合入保真度 · 逐 hunk 对账表

判定口径：✅=应用且与补丁终态一致（注释措辞差异不计）；⚠=应用但注释级偏差（§五备注）；❌=缺失。

### src/main.py（2 处 hunk 面）

| 补丁 | 锚点 | 判定 | 核对要点 |
|---|---|---|---|
| A1【P0/W1】 | `:1577` | ✅ | `--disable-web-security` 及 a501 注释块已删，R1 审计注释就位；`--remote-debugging-port=9222` 条件追加链保持 |
| A2【P1/W2】 | `:806` | ✅ | `_is_loopback`（urlsplit().hostname 精确判定 + 异常回落 False）+ `_safe_load` 判定改 `not _is_loopback(_u)` |
| N2【P3/W19】 | `:818` | ⚠ | 非 http(s) 一律吞（仅放行 http(s) 落 `_orig_load`）；A2+N2 叠加顺序正确（先外链截胡 → 非 http(s) 拦截 → 回环 http(s) 放行）。⚠ 注释写「R3 审计 W19」——W19 实为 **R2** 发现（round-2-whitebox §W19、patch-round-2 §二 N2），轮次标注笔误，见 §五备注 1 |

### src/web_tabs.py（10 处 hunk 面）

| 补丁 | 锚点 | 判定 | 核对要点 |
|---|---|---|---|
| A11+A11'【P3/W11/W17】 | `:19-23` | ✅ | `import threading`、`_lock` 双删；原位由 P1'' `_HIDE_ALL` 常量顶替 |
| A3【P1/W5】① | `:52` | ✅ | `self._cancel = set()` 登记于 `_pend_nav` 与 `_env_failed` 之间 |
| A3 ② | `:139` | ✅ | `_build` 首行 cancel 检查 → discard + return（弃建） |
| A4''【P1/W13+W14+W21】 | `:171-197` | ✅ | `err = str(e)` 在 `_log` 后、进闭包前固化（W21）；`_rm` 含 `_ctl/_pend_nav` 双 pop + Controls.Remove/Dispose + `__webTabDead` 推送（W14：经 `self._ui(_rm)` UI 线程通道）；`json.dumps(err)` 非空 |
| A9【P3/W12】 | `:288` | ✅ | `u = str(a.Uri or "") or "about:blank"` |
| A5【P2/W6】 | `:323` | ✅ | `_go` 内 `ctl.CoreWebView2 is None → _pend_nav[tab_id]=url`（末次胜出） |
| P1''① `_apply_visibility` | `:383` | ✅ | `tab_id == _HIDE_ALL` 全隐分支位于 `if visible:` 之前；`list(self._ctl.values())` 快照 + 幂等全隐 + 不动 BringToFront |
| P1''② `show` 签名 | `:399-417` | ✅ | `show(self, tab_id, visible, sq=0, hide_all=False)`；`_want = (_HIDE_ALL, False) if hide_all else (tab_id, bool(visible))`；sq 门控在前、pending 补显分支保持 |
| A3 ③ `dispose` | `:437-449` | ✅ | `ctl` 命中走 `_ui(_rm)`；`elif tab_id in self._pending` → `_cancel.add` + `_pending.discard` + `_pend_nav.pop`（A3 终态形态） |
| A6+P1''③ REST | `:506-543` | ✅ | `_num`（NaN/inf/溢出回落默认，except 三类）+ layout 四参收口 + show 分支 `_on`/`_all` 双布尔收口（isinstance bool / 字符串白名单 `("true","1","yes","on")`）+ `_num("sq")` + `hide_all` 透传——A6 与 P1'' 的 REST 叠加正确（P1'' 定稿的 A6 已应用形态） |

### src/web_proxy.py（3 处 hunk 面）

| 补丁 | 锚点 | 判定 | 核对要点 |
|---|---|---|---|
| N1 配套 helpers【P3/W18】 | `:63-84` | ✅ | `_web_url_host` / `_web_is_private_host` 模块级（全部解析地址私网/回环/链路本地才 True，解析失败按公网——安全侧） |
| N1'【P3/W25】 | `:101-146` | ✅ | `_NoRedirect(redirect_request→None)`；手动循环 `for _hop in range(6)` + for-else「重定向次数过多」；**逐跳** `_ssl.create_default_context()` + `_web_is_private_host(_web_url_host(cur))` 回落 CERT_NONE + 每跳重建 opener（HTTPSHandler(ctx) + _NoRedirect）+ 每跳新建 Request（UA/Accept-Language 保持）；HTTPError 分支：301/302/303/307/308 且有 Location → `_urljoin` 相对解析 → 非 http(s) Location 返回 400「重定向到不支持的协议」→ `continue`；否则 `raise`；成功 `break` → `with resp` 读 5MB + charset 探测。N1 的私网回落语义并入每跳 |
| N4+N4'【P3/B12+P3/W30】 | `:147-162` | ✅ | `except urllib.request.HTTPError` 先于 `except Exception`（分支序正确，重定向 HTTPError 已在循环内消费，此处只接非重定向）；状态码分支 `getattr(he, "status", "?")`；通用分支 `_hint` 映射（UnicodeEncodeError/URLError/TimeoutError/ValueError）+ 类型名兜底，异常原文零外露 |

### web/js/web-panel.js（18 处 hunk 面，3 ❌）

| 补丁 | 锚点（现文件） | 判定 | 核对要点 |
|---|---|---|---|
| A11① WEB_PORTID | `:17-20` | ✅ | 常量与注释删；全仓 grep 无外部引用（web/index.html、其余 JS 均无） |
| N5【P3/B13】 | `:67-76` | ✅ | 非数组回写 `[]` + 元素 `typeof x.url === 'string'` 过滤 + 回写自愈 + catch 双保险 |
| A10''①【P3/W16】 `_webNormUrl` | `:90-95` | ✅ | `file|javascript|data|vbscript` 显式拦截返 `''`；`https?|about|mailto|ftp|ws|wss` 放行；裸主机补 `http://` |
| A11② blank-hint div | `:154-157` | ✅ | `web-blank-hint` 元素删（配套 style.css ✅） |
| A10'② 面板地址栏反馈 | `:180-184` | ✅ | 非空输入被拦成 `''` → `showBanner('该协议不允许在内嵌浏览器打开', 2500, true)`；真空输入静默 |
| A8① 调用点 `:173` | `:189` | ✅ | `_webNavigate(u, conn)`（但见 ❌ W33：实参现被丢弃） |
| A8' Ctrl+滚轮/Ctrl+0 | `:220/:228` | ✅ | `_webApplyZoom(z, host, c2)` / `_webApplyZoom(1, host, cz)` |
| A8② 调用点 `:230` | `:244` | ✅ | 会话恢复 back-nav `_webNavigate(conn._nav.stack[...], conn)`（同上，实参现被丢弃） |
| P1''① `_webCtlVisible(on, all)` | `:293-301` | ✅ | `const d = { act:'show', on:!!on, sq:++_webCtlSeq }; if (all) d.all = true;` |
| A8' `_webNavigate` 体内三参化 | `:421/:427/:428` | ✅ | `_webReaderToggle(false,true,c)` / `_webApplyZoom(...,c)` / `_webSyncUI(c)` |
| P1''② switchTab 包装器 | `:451-458` | ✅ | `if (!c._ui.reader && !c._ui.sleeping) _webCtlVisible(true); else _webCtlVisible(false, true);`（P1'' 终稿逐字一致；P1' 守卫行已被整体替换，无残留） |
| A8' 巡检 `:495` | `:516` | ✅ | `_webNavigate(url, c)`（实参现被丢弃——W15 修复失效） |
| A8' `_webReaderToggle` | `:522-523` | ✅ | `(on, skipRestore, c)` + `c = c || _webCur()` |
| A8' `_webApplyZoom`/`_webSyncUI` | `:574-575/:585-586` | ✅ | 同型参数化 |
| A8' `_webAct` | `:596-599` | ⚠ | `const c = connections[(wrap && wrap.dataset.portId) || ''] || _webCur()`；⚠ 补丁末行注释「wrap.dataset.portId 即按钮所属 tab」未搬入（语义零差异） |
| A8' reload/read 分支 | `:605/:609` | ✅ | `_webReaderToggle(true, false, c)` / `_webReaderToggle(!c._ui.reader, false, c)` |
| A8'' star 双分支 + fav 菜单 | `:634/:638/:768-772` | ✅ | `_webSyncUI(c)` ×2；删除收藏后 `for (const pid in connections)` 全量 web `_webSyncUI(cw)` |
| A4 前端 `__webTabDead` | `:681-691` | ✅ | find（kind==='web' && _tabId===tabId）→ showBanner + `closeEditorTab(c.portId)` |
| **❌ W33：A8 签名 hunk** | `:410-411` | ❌ | 仍为 `function _webNavigate(url) { const c = _webCur();`——参数化未应用 |
| **❌ W34：A8 调用点 `:433`** | `:449` | ❌ | 仍为 `if (u) _webNavigate(u);`——switchTab 唤醒路径未传 `c` |
| **❌ W35：A10''② 顶栏反馈** | `:712` | ❌ | 仍为 `if (!u) { buildWebPanelTab(); bar.blur(); return; }`——顶栏非空非法协议输入被当「空=开网页 tab」，零反馈（W23 未修） |

### 其余 4 文件

| 文件 | 补丁 | 判定 | 核对要点 |
|---|---|---|---|
| web/js/util.js | A7 + N3-② | ✅✅ | `_SINGLE_KINDS` 去 `'web'`；抽屉批量关闭 `kind==='web'` → `closeEditorTab` 分支（位于 harness 分支后、isEd 判定前，与补丁锚点一致） |
| web/js/sidebar.js | N3-① | ✅ | 转发正则 `/^(edit|hex|diff|bindiff|web):/` → `closeEditorTab(portId); return;` |
| web/js/sidebar-resize.js | A11③④ | ✅✅ | `iframes` helper 与 mousedown/mouseup 两处 `pointerEvents` 调用全删（附带新增一句说明注释，语义无涉） |
| web/js/settings.js | A12 | ✅ | CDP 文案「操作工具主界面（网页 tab 内容暂不可达，修复中）」 |
| web/style.css | A11⑤ | ✅ | `.web-blank-hint` 两条规则删，替换为审计注释 |

**多余改动排查**：9 文件的全部 diff hunk 均能映射到补丁终态（或其注释性微调），无一处无主改动；工作树除 `docs/审计补丁台账_2026-11-13/`（untracked）外无其他文件触碰。

---

## 三、修订链合并正确性（专项）

### 1. A8 链（B1/A8 → A8'/W15+B7 → A8''/W26）——**断裂，见 W33/W34**

grep 全量核对（现文件行号）：

| 函数 | 签名 | 判定 |
|---|---|---|
| `_webNavigate` | `function _webNavigate(url)` `:410` | **❌ 未参数化（W33）** |
| `_webReaderToggle` | `(on, skipRestore, c)` `:522` | ✅ |
| `_webApplyZoom` | `(z, host, c)` `:574` | ✅ |
| `_webSyncUI` | `(c)` `:585` | ✅ |
| `_webAct` | `(act, wrap)` + wrap 定向 `:596-599` | ✅ |

`_webNavigate` 全部 6 个调用点：`:114`（顶栏口，无参——A8 自述无需改，`switchTab(pid)` 后 `_webCur()` 恒等目标）、`:189`（传 conn）、`:235`（建 tab 初航，无参——同 :114 判定）、`:244`（传 conn）、`:449`（**无参，❌ W34**）、`:516`（传 c）。

**W33 后果分析**：JS 对多余实参静默丢弃 → `:189/:244/:516` 三处已应用的目标实参**全部无效**，行为回落基线 `_webCur()`：

- **B1 失效（P2）**：黑盒 R1 已实锤「对非激活 tab A 的地址栏回车 → 导航落在激活 tab B」（round-1-blackbox §B1，含派发与点击双路径）。签名缺失后该行为原样保留。
- **W15 失效（P3）**：1s 巡检在 `_webActivePid` 为 null/陈旧且多 web tab 时按字典序回落第一个 web conn（round-2-whitebox §W15）——定向实参被丢弃后该残留原样保留。
- `:244` 会话恢复：`switchTab(portId)` 先行 → `_webCur()` 恒等目标，实际无行为差（但补丁终态应为定向）。

**修复依赖**：W33（签名）必须先行；W34 依赖 W33 落地后才有意义。修复后 6 调用点与 A8/A8' 终态完全对齐，无任何调用点因参数化「变活」而产生新行为（`:114/:235` 无参回落不变）。

### 2. A4 链（A4 → A4' → A4''）——✅ 干净

终态三要素齐备：`err = str(e)` 闭包前固化（W21 的 CPython `del e` 实锤修复）；推送并入 `_rm` 经 `self._ui`（W14 线程亲和）；前端 `__webTabDead` 同步 find + closeEditorTab（W14 评审维持不变）。建议测试 #10/#17（BeginInvoke 通道 + err 非空双钉）的静态前提已满足。

### 3. A10 链（A10 → A10' → A10''）——**半断裂，见 W35**

`_webNormUrl` 收窄 ✅ + 面板反馈 ✅ + **顶栏反馈 ❌**。W23 场景现态复推：顶栏输入 `file:...`/`javascript:...` → `_webNormUrl` 返 `''` → `:712` 当「空=开网页 tab」→ 误开一个会话恢复空 tab 且零反馈——与 round-3-whitebox §W23 的基线缺陷一致，未修复。

### 4. A11 → A11' ——✅ 干净

五处死代码（WEB_PORTID、blank-hint div+css、iframes×2、`_lock`）+ 孤儿 `import threading` 全删；grep 证实无引用残留。

### 5. N1 → N1' ——✅ 干净

N1 的「入口 host 一次性分类」已被 N1' 的「逐跳重分类」完整取代（每跳 `_web_is_private_host(_web_url_host(cur))`）；N1 的 helpers 原样保留并服务于逐跳判定。基线的死变量（外置 `req`、`urlopen(..., context=ctx)` 形态）清理干净，无残留引用。补丁中 `_NoRedirect` 定义于 imports 之后、`data = ...` 之前，实际锚点在 400 守卫之后——纯锚点位移，语义零差异。

### 6. N4 → N4' ——✅ 干净

HTTPError 专门分支位于通用分支**之前**（Python except 序），重定向消费后 `raise` 的非重定向 HTTPError 落状态码分支，其余落 `_hint`/类型名分支。W30（404/403/500 可诊断性不低于基线）达成。

### 7. N1/N2/N4/N5 与 A 系叠加 ——✅ 干净

- `_safe_load` 的 **A2+N2 叠加**：http(s) 非回环 → 外链截胡 return；非 http(s) → 吞掉 return；仅 http(s) 回环落 `_orig_load`——与 patch-round-2 N2「基于 A2 修订版叠加」的终态逐字一致。
- `api_web_tabs` 的 **A6+P1'' 叠加**：`_num` + on/all 双布尔收口 + `_num("sq")` + `hide_all` 第四参——即 P1'' 定稿所示「A6 应用形态」的 REST 段。
- **W22 两处**：sidebar.js 正则（第一 hunk，即时可达）+ util.js 抽屉 web 分支（第二 hunk，依赖 A7 先落地——A7 已在）双双就位；`_SINGLE_KINDS` 无 `'web'`（A7）与 closeConnection 转发构成闭环（§四.2）。

### 8. P1' → P1'' ——✅ 干净

P1' 的一行守卫已被 P1'' 整体替换（`:451-458` 五行注释 + if/else 两行），无 P1' 残留文本；前后端六点（`_HIDE_ALL` 常量、show 签名、`_want` 哨兵写入、`_apply_visibility` 全隐分支、REST `all` 透传、前端 `_webCtlVisible(on, all)` + switchTab 包装器）与 patch-round-6 定稿 diff 逐字一致。R7 验收口径（切回阅读态 tab 应发 `show(on:false, all:true)`）在代码层就位。

---

## 四、对抗终审（合入后最终形态）

### 1. web_tabs.py `_HIDE_ALL` 四点链路 ——✅ 通过

1. **常量**：`_HIDE_ALL = "__all__"`（模块级，`_lock` 原位）。
2. **show 签名**：`hide_all=False` 第四参；sq 门控照常（`hide_all` 不绕过乱序丢弃）；`_want` 写哨兵时 `visible` 参数忽略；pending 补显分支（`visible and tab_id not in _ctl and tab_id in _pending`）语义保持——`_webCtlVisible(false, true)` 传 on=false 时该分支天然不触发，REST 层手传 `on:true, all:true` 时 intent 先记哨兵再补显，无死端。
3. **`_apply_visibility` 全隐分支**：位于排他/只藏分支之前；`list(self._ctl.values())` 快照防 dispose 竞态；幂等；不动 BringToFront（恢复排他显示时由 `show(X,True)` 统一前置）。执行通道：`show._apply` 与 `layout._apply` 均经 `self._ui`（UI 线程，a549 铁律）。
4. **REST 透传**：`all` 字段布尔收口（bool 原样 / 字符串白名单）→ `hide_all`。
5. **哨兵碰撞**：前端 tab id 现态为 `web-<n>`（D1 纪元前缀未合入），恒不等于 `"__all__"`——无碰撞面。⚠ 但 `_HIDE_ALL` 注释自述「前端 tab id 恒为 web:<epoch>:<n> 形态」的前提因 D1 未合而不成立（结论不变，见 §五备注 2）。
6. **时序对抗**：`_want=(X,True)`（陈旧排他意图）→ 切回阅读态发 hide-all → 后续任意 layout `_apply` 均走全隐分支——W32 十步时序的「陈旧 `_want` 经补显弹出他 tab」根因被切断；休眠（target-only `show(on:false)`）与阅读（`_webCtlVisible(false)` target-only）语义不受全隐分支影响（只有 switchTab 的 else 分支发 `all:true`）。

### 2. web-panel.js → sidebar.js → closeEditorTab 转发闭环 ——✅ 通过

- **路径 1（侧栏 ✕）**：sidebar.js `:250 else closeConnection(pid)` → `:122` 正则命中 `web:` → `closeEditorTab(portId)`。
- **路径 2（抽屉全部关闭）**：util.js `:243` `kind==='web'` → `closeEditorTab(pid)`（A7 已使 web 可进抽屉，两 hunk 依赖关系满足）。
- **包装层**（web-panel.js `:470-484`）：web kind → dispose REST（`_webCtl(c,{act:'dispose'})`）+ `_ctlResize.disconnect()` + `resize` 监听移除 + `_webActivePid` 清理 → `origClose(pid)`（editor.js `:1394`，dirty 检查 web conn 无 dirty 字段直通）→ `_edCloseNow` 通用清理。
- **脚本加载序**：util.js → sidebar.js → editor.js → web-panel.js（index.html :518/:525/:538/:551）；`closeConnection` 的 `typeof closeEditorTab === 'function'` 运行时守卫 + web-panel 的包装 IIFE 在 editor.js 之后执行——闭环成立，幽灵 layout(0,0,0,0) 与必败 `/api/disconnect` 噪音两源头均被切断（B16 验收断言的静态前提满足）。
- **`__webTabDead` → closeEditorTab**：同一包装层被复用（dispose REST + 监听清理齐备），A4 前端块安全。

### 3. web_proxy.py 手动重定向循环 ——✅ 通过

- **六跳**：`for _hop in range(6)` + for-else——第 6 跳仍为重定向时 `continue` 触发 else → 「重定向次数过多」优雅失败（与补丁同构，B19 的 12/30 跳环场景收敛为 ≤6 迭代）。
- **逐跳 ctx**：每跳新建 `create_default_context()` + 私网判定回落 CERT_NONE + 新 opener——私网 302 → 公网段必须验证（B19 翻转格的静态前提满足）。
- **HTTPError 分支顺序**：循环内先消费重定向（301/302/303/307/308 + Location），非重定向 `raise` → 外层 `except HTTPError`（N4' 状态码）→ 外层 `except Exception`（N4 `_hint`）。三层的分层与 patch-round-3 N1' + patch-round-4 N4' 的合成终态一致。
- **拒绝面**：非 http(s) Location（file:/data: 等）→ 400；入口非 http(s) → 400（保持）。
- **完整性**：`_urljoin` 处理相对 Location；`with resp` 关闭最终响应；`text` 作用域贯穿到 `_web_html_to_text`；基线 `req`/`urlopen(context=)` 死形态零残留；`he.status` 在本仓 Python3 环境可用（pytest 实证）。
- 循环内重定向 hop 的 HTTPError 响应体未显式 close——GC 兜底、基线同风险、补丁同构，不计缺陷（观察项）。

### 4. 机械合入笔误/遗漏调用点排查 ——✅ 通过（除 §二 已列 3 处）

- 全部 `_webCur()` 现存 20 处逐一对照 A8' 判定表：`:45`（_webSessionSave）、`:110`（顶栏口）、`:215/:225`（滚轮/复位局部）、`:294`（_webCtlVisible）、`:389`（浮层联动）、`:411`（_webNavigate 内——因 W33 仍为无参回落）、`:438`（switchTab prev）、`:523/:576/:586`（三函数回落）、`:599`（_webAct 兜底）、`:725/:730/:734`（侧栏入口/最近）——归属全部与判定表一致，无第 8 处漏网。
- `closeConnection` 正则、`_SINGLE_KINDS`、`__webTabDead`、`__newWindow`、`showBanner` 引用、`_webCtl` 字典透传（`d.all` 直达 REST）无笔误。
- Python 三文件 `py_compile` 通过；JS 五文件 `node --check` 通过。

---

## 五、机械验证复核（独立重跑）

| 项 | 命令 | 结果 |
|---|---|---|
| pytest | `USERPROFILE=$(mktemp -d) python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` | **20 passed in 0.25s**（与主控预跑一致） |
| node --check | web-panel.js / util.js / sidebar.js / sidebar-resize.js / settings.js | **5/5 OK**（与主控预跑一致） |
| py_compile（附加） | `python -m py_compile src/main.py src/web_tabs.py src/web_proxy.py` | 3/3 OK |

### 备注级事项（不计缺陷，主控可顺手处置）

1. **main.py `:821` 注释轮次标注笔误**：N2 注释写「R3 审计 W19（N2）」——W19 为 **R2** 发现（round-2-whitebox §W19、patch-round-2 §二 N2 自述「R2 审计 W19」）。仅注释，无语义影响。
2. **web_tabs.py `:23` `_HIDE_ALL` 注释前提陈旧**：「前端 tab id 恒为 web:<epoch>:<n> 形态」——D1 纪元前缀按拍板未合入，现态为 `web-<n>`。防碰撞结论不变（id 恒以 `web` 开头且不含 `__all__`）；若 D1'' 未来落地，注释自动复原为真。
3. **若干 hunk 的注释行与补丁文本有轻微删节/改写**（`_webAct` 缺「wrap.dataset.portId 即按钮所属 tab」一行、A6 show 分支注释按 P1'' 合并态改写、sidebar-resize 新增一句说明）——语义零差异，不追。
4. 任务书「+293/−84」与 git 实测「+293/−90」不符——以 `git diff --shortstat` 为准。

---

## 六、问题清单（W33 起）

### W33【合入错误·P2】A8 主 hunk 漏合：`_webNavigate` 未参数化，B1/W15 修复整体失效

- **位置**：`web/js/web-panel.js:410-411`
- **现态**：`function _webNavigate(url) {` + `const c = _webCur();`
- **依据**：patch-round-1 A8 主 hunk（修订警示链 A8→A8' 未改此 hunk 形态）；B1 黑盒实锤（round-1-blackbox §B1）与 W15 白板推演（round-2-whitebox §W15）所依赖的正是此参数化。
- **后果**：`:189`（地址栏，B1）、`:516`（巡检，W15）、`:244`（会话恢复）三处已应用的第二实参被 JS 静默丢弃 → 三处修复全部惰性化，行为回落基线 `_webCur()`。
- **修复**（主控执行）：
  ```diff
  --- a/web/js/web-panel.js
  +++ b/web/js/web-panel.js
  @@ -410,3 +410,3 @@
  -function _webNavigate(url) {
  -  const c = _webCur();
  +function _webNavigate(url, c) {
  +  c = c || _webCur();        // R1 审计 B1（A8）：可指定目标 tab——非激活 tab 的
  +                             // 地址栏回车原会导航到激活 tab（本 tab 纹丝不动）
     if (!c || !url) return;
  ```
- **修复后回归**：①B10 十二格矩阵（A8' 验收基线）；②round-1-blackbox §B1 派发复现应翻转为「A 自身导航」；③W15 巡检定向；④`:114/:235` 两处无参调用行为不变；⑤`node --check` + 20 pytest 不破坏。

### W34【合入错误·P3】A8 第三调用点 hunk 漏合：switchTab 唤醒路径未定向

- **位置**：`web/js/web-panel.js:449`
- **现态**：`if (u) _webNavigate(u);`（switchTab 包装器内睡眠唤醒恢复，`c` 为目标 tab）
- **依据**：patch-round-1 A8 调用点修正第三处（`:433` → `_webNavigate(u, c)`）。
- **后果**：该处 `:443` 已先置 `_webActivePid = pid`，`_webCur()` 恒等 `c`，**当前行为等价**——但与补丁终态不符，且语义依赖「隐式回落恰好命中」而非显式定向（W33 修复后若此处仍无参，属 belt-and-braces 缺席）。
- **修复**（依赖 W33 先行）：`if (u) _webNavigate(u, c);`

### W35【合入错误·P3】A10'' 顶栏反馈 hunk 漏合：W23 修复失效

- **位置**：`web/js/web-panel.js:712`
- **现态**：`if (!u) { buildWebPanelTab(); bar.blur(); return; }   // 空=开网页 tab（有会话则恢复）`
- **依据**：patch-round-3 A10''（W23：顶栏把 `file:`/`javascript:` 等被 `_webNormUrl` 拦成 `''` 的非空输入当「空输入」→ 误开一个会话恢复空 tab 且零反馈；hunk 尾部上下文已含 a556 的 `buildWebPanelTab(u, { newTab: true })` 行，锚点无歧义）。
- **后果**：面板地址栏有拦截反馈（A10'② 已合），顶栏同型输入仍静默误开 tab——W23 场景原样保留。
- **修复**（主控执行）：
  ```diff
  --- a/web/js/web-panel.js
  +++ b/web/js/web-panel.js
  @@ -712,1 +712,6 @@
  -    if (!u) { buildWebPanelTab(); bar.blur(); return; }   // 空=开网页 tab（有会话则恢复）
  +    if (!u) {
  +      // R3 审计 W23：非空输入被 _webNormUrl 拦成 ''（file:/javascript: 等）
  +      // = 非法协议，给可见反馈；真空输入才走「开网页 tab（恢复会话）」
  +      if (bar.value.trim()) { showBanner('该协议不允许在内嵌浏览器打开', 2500, true); return; }
  +      buildWebPanelTab(); bar.blur(); return;
  +    }
  ```
- **修复后回归**：顶栏输入 `javascript:alert(1)` / `file:///C:/` → 横幅反馈、不开 tab；真空输入 / 有会话恢复路径不变；面板地址栏行为不变。

**无「新缺陷」**：除 3 处漏合外，未发现合入动作本身引入的任何新问题（无错锚点、无语义走样、无多余改动、无笔误调用点）。

---

## 七、结论

- **合入保真度**：3/30 余 hunk 缺失（W33/W34/W35，全部为「漏合」而非「合错」），其余全部干净、修订链叠加正确、D 系未合符合预期——**保真度未达 100%**。
- **对抗终审**：除漏合三处对应的功能面外，四条点名链路（`_HIDE_ALL` 四点、closeEditorTab 闭环、web_proxy 重定向循环、笔误排查）**通过**；机械验证独立复核通过（20 pytest / 5 node --check / 3 py_compile）。
- **移交主控**：按 §六 三条修复建议执行（W33 → W34 → W35 顺序），修复后按各自回归清单复核；§五备注 1/2 两条注释可顺手更正。

---

## 八、R8.1 复验（主控 W33/W34/W35 + B22/B23 修复后）——本节为最终判定，取代 §六/§七 的未决状态

### 8.1 九处修复逐处核对（git diff 全量）

| # | 修复 | 现文件位置 | 判定 | 核对要点 |
|---|---|---|---|---|
| ① | **W33**：`_webNavigate(url, c)` 签名 + `c = c || _webCur()` | `:410-412` | ✅ | 与 A8 补丁终态一致；体内 `:421/:427/:428`（readerToggle/zoom/syncUI 传 c）已在位 |
| ② | **W34**：switchTab 唤醒 `_webNavigate(u, c)` | `:449` | ✅ | 与 A8 第三调用点终态一致 |
| ③ | **W35**：顶栏 A10'' 横幅分支 | `:709-717` | ✅ | 非空拦截 → `showBanner('该协议不允许在内嵌浏览器打开', 2500, true)` + return；真空 → `buildWebPanelTab(); bar.blur(); return;`；尾部 a556 `buildWebPanelTab(u, { newTab: true })` 上下文原样保留——与 patch-round-3 A10'' 一致 |
| ④ | B23：wheel `c2 = connections[wrap.dataset.portId] || _webCur()` | `:215` | ✅ | 事件归属本 wrap（较 A8' 字面的 `_webCur()` 更精确，符合 B7 原则）；`wrap.dataset.portId` 于 `:135` 赋值（tab 侧 `:121`），解析有效；`_webApplyZoom(z, host, c2)` 定向 |
| ⑤ | B23：Ctrl+0 `cz` 同型 | `:225` | ✅ | 同上 |
| ⑥ | B22：`_webCtlVisible(on, all, target)` 第三参 | `:293-294` | ✅ | `target || _webCur()`；`all` 哨兵/`sq`/`_ctlPush` 语义保持 |
| ⑦ | B22：`:423` `_webCtlVisible(true, false, c)` | `:423` | ✅ | _webNavigate 内定向本 tab（与刚置的 `_webActivePid` 一致，无行为冲突） |
| ⑧ | B22：退阅读 `_webCtlVisible(true, false, c)` | `:535` | ✅ | 激活态与原行为等价；程序化后台形态定向 c |
| ⑨ | B22：进阅读 `_webCtlVisible(false, false, c)` | `:543` | ✅ | target-only 隐藏——后台进阅读不再错藏激活 tab（B22 本体） |

**保持不动核对**：`:391/:393`（浮层联动）与 `:466`（非 web 回切）保持 1 参激活语义 ✅；`:456/:457`（P1'' switchTab 全隐/排他）未动 ✅；`_webSleep` 直发 `show(on:false)` 未动 ✅。全仓 `_webCtlVisible(` 穷举 9 处（含定义）无遗漏调用点；`_webNavigate` 6 调用点全部核销（`:114/:235` 无参回落、其余 4 处定向）。

**定向性对抗**：`_webNavigate`/`_webReaderToggle` 全部可达路径中 c 均为当前显示 tab（`:114/:189/:235/:244/:449/:516` 逐一复核），B22 的定向 show 不会产生「后台 tab 排他显出、HWND 盖住激活 UI」的新形态；后台进阅读（仅程序化可达）为 target-only 隐藏，无副作用。

**改动面收敛**：numstat 全仓 308/100，较 R8 审计态（293/90）**仅 web-panel.js +15/−10**（恰为上述 6 项 footprint），其余 8 文件字节级不变。

### 8.2 机械复核（独立重跑）

- `node --check` 5/5 OK；`USERPROFILE=$(mktemp -d) python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**（独立复跑）。

### 8.3 W33/W34/W35 关闭判定

- **W33【合入错误·P2】→ 关闭**（修复与 A8 终态一致；B1/W15 定向链恢复）。
- **W34【合入错误·P3】→ 关闭**（同上）。
- **W35【合入错误·P3】→ 关闭**（与 patch-round-3 A10'' 一致；W23 顶栏格恢复）。

### 8.4 B25 裁决：**按设计关闭**（改判，非「补丁未生效」）

1. **N1/N1' 设计语义明文**：patch-round-2 N1——「默认走系统验证；仅当目标解析为私网/回环/链路本地地址时回落不校验（内网自签场景，**维持 docstring 语义**）」；合并后 `web_proxy.py` docstring：「内网 https 自签不校验（本地单用户工具语境，与浏览器『继续访问』同权）」；`_web_is_private_host` docstring：「私网/回环/链路本地 → True」。
2. **B25 实测目标为回环**：`https://127.0.0.1:19002/final` 与 `https://localhost:19002/final`（round-8-blackbox §四格 1b）→ getaddrinfo 全回环 → `is_loopback` → 设计内回落 CERT_NONE → 取页成功 = **设计内行为**。
3. **同表交叉证据证明新路径确实生效**：round-8-blackbox §四第 2 格（302→file:// 被拒，N1' 专属文案「重定向到不支持的协议」）、第 3 格（「目标返回 HTTP 404」，N4'）、第 5 格（N4 可读文案）全部翻转成功——若 N1' 未生效，第 2/3 格不可能翻转；第 4 格（私网自身 API 仍可取）恰为设计回落本身。
4. **R4 验收格口径误标**：B19 #32 原格目标即「跨主机自签 https（**私网 19002**）」——回环目标在 N1' 语义下本就不应翻转，「必须失败」仅对**公网**目标成立。round-8-blackbox §四注记已自行给出该二选一，此处裁决取「实现语义为设计内回落」分支。
5. **处置**：B25 改判「按设计关闭」；**公网自签严格性**（badssl 类公网目标证书校验生效、中间人投喂被拒）列入桌面验证手册（隔离环境 badssl DNS 不可达无法实测），手册条目同步改写 R4 该格验收口径（「私网/回环自签接受=设计内；公网自签必须失败」）。

### 8.5 遗留

- **代码遗留：无**。
- R8 报告 §五备注 1/2（main.py N2 注释轮次笔误「R3」应为「R2」；`_HIDE_ALL` 注释「web:<epoch>:<n>」前提因 D1 未合而陈旧——结论不变）仍未更正，不阻塞，主控可顺手处置。
- 桌面验证手册承接项 +1：公网自签严格性实测（B25 改判后新增口径）。
