# 红队回归审计 · D 轮报告（修复在位性验证）

- **审计员**：红队回归审计员 D
- **日期**：2026-11-16
- **对象**：当前 HEAD `480c07d`（v4.1.0-a583），验证「审计后修复实施（SUMMARY 〇节：A1-A12 终态 / N1'-N5 / P1'' / D 批 / 第 11-13 例）+ 第 14-15 例（a571/a575）」在 HEAD 是否仍在
- **方法**：修复清单逐条 → `git show HEAD:<file>` 特征串定位 → 修复本体语义核对 → 配套（调用点/路由/桩/钉测）核对；全程 git 只读；pytest 以隔离 USERPROFILE 运行；另做三文件（web_tabs.py / web-panel.js / tray.py）全程版本考古（逐 commit diff 扫「删除修复特征串」与「重新引入坏模式」双向）
- **基线注意**：工作树含 a581 在途改动（src/server.py + web/index.html + sidebar.js + terminal-core.js + util.js + 未跟踪 src/shell_conn.py，本地 shell 终端功能）。**全部 HEAD 级验证以 `git show HEAD:` 为准**；在途 diff 逐 hunk 核对为纯增量（shell kind 分支），未触碰任何已审计修复。

---

## 一、终判

**验证 44 项修复 / 8 个指定风险点：源码级修复零丢失。** 唯一丢失发生在**测试层**（RD1：a556 排他显隐钉测被 a575 误改名后静默死亡）。回退事故（reflog：reset→32dcef7 后立即 reset→0127d7e）未造成任何已提交修复丢失；a567 误删 4 路由事故已被 a570 完整恢复并有钉测把守（实测通过）。

- pytest 全量（隔离 USERPROFILE）：**274 passed, 1 skipped, 10 subtests passed**（19.4s）
- `test_route_chain_complete` 单跑：**1 passed**（13 act 全可达 + 未知 act 必报 bad act）
- `test_web_tabs_logic.py + test_web_fetch.py`：**26 passed**
- 机械验证：`py_compile`（web_tabs/web_proxy/server/main/tray/devtools_cdp）全过；`node --check`（web-panel/util/sidebar/settings/sidebar-resize）全过（工作树）
- 注：pytest 运行于工作树；被在途改动触及的仅 src/server.py 的 shell 增量分支，web_tabs/web_proxy/tests 三者工作树与 HEAD 零差异（git status 实证），结论不受影响

---

## 二、逐条验证结果（44 项）

### A 系（12 项，终态口径）

| # | 修复 | HEAD 位置与核对 | 判定 |
|---|---|---|---|
| A1 | 删 `--disable-web-security`（W1/P0） | main.py：四旗保留（:1595-1598），该串仅存于 :1599 注释；全仓 grep 无实参 | ✅ 在 |
| A2 | `_is_loopback` hostname 精确判定（W2/P1） | main.py:807-816，urlsplit().hostname ∈ {127.0.0.1, localhost, ::1} | ✅ 在 |
| A3 | create 在途 dispose 弃建（W5/P1） | web_tabs.py:246 `_cancel` 集；:365-369 `_build` 弃建；:890-894 dispose→_pending 命中走 cancel | ✅ 在 |
| A4'' | 初始化失败回收 + `__webTabDead`（W13/W14/W21） | web_tabs.py:400-426：`err = str(e)` 先固化（W21）→ `_rm` 内 Remove/Dispose + 推送 `err`（W14，经 `_ui`）→ `_epochs.pop`；前端 `window.__webTabDead` web-panel.js:1058 | ✅ 在 |
| A5 | 就绪前 navigate 转 `_pend_nav`（W6/P2） | web_tabs.py:584-600 navigate：`CoreWebView2 is None → _pend_nav[tab_id]=url` | ✅ 在 |
| A6 | REST 入参收口 `_num` + 布尔穿透（W7/P2） | web_tabs.py:1041-1049 `_num`；show 分支 `_on/_all` isinstance 分派 | ✅ 在 |
| A7 | `_SINGLE_KINDS` 去 `'web'`（W9/P2） | util.js:64 `new Set(['harness','bitcalc','proxy','vcs'])` | ✅ 在 |
| A8'' | `_webCur()` 变体族全参数化（B1/B7/W15/W17/W26/W33） | `_webNavigate(url,c)`:759、`_webAct` wrap.dataset.portId:968-971、`_webReaderToggle(,,,c)`:884、`_webApplyZoom(,,,c)`:946、`_webSyncUI(c)`:957；调用点 351/359/771/778/878（巡检逐 tab）/979/983/1008/1012/1256（收藏删除全量同步） | ✅ 在 |
| A9 | NewWindowRequested 空 URI → about:blank（W12/P3） | web_tabs.py:558 `or "about:blank"` | ✅ 在 |
| A10'' | scheme 白名单收窄 + 双入口反馈（W16/W23/W35） | `_webNormUrl`:207-215（file/javascript/data/vbscript→''）；面板地址栏 banner:314、顶栏 banner:1110 | ✅ 在 |
| A11' | 死代码清理（W11/W17） | `WEB_PORTID`/`web-blank-hint`/`iframes()` 仅存注释；web_tabs.py `import threading` 计数 0 | ✅ 在 |
| A12 | CDP 文案止血（W4） | settings.js:787 现文案=「网页 tab 走独立端口 9223…」——**已被 D2 落地后的真文案取代**（止血的历史使命完成），非丢失 | ✅ 演进取代 |

### N 系（5 项）

| # | 修复 | HEAD 位置与核对 | 判定 |
|---|---|---|---|
| N1' | fetch_text 逐跳重分类 SSL ctx + 6 跳封顶（W18/W25） | web_proxy.py:101 `_NoRedirect`、:112-140 手动逐跳、:63/:71 `_web_url_host`/`_web_is_private_host` 模块级 | ✅ 在 |
| N2 | 非 http(s) scheme 拦截（W19/P3） | main.py:826-830 `if not (_u.startswith("http://") or ...): return` | ✅ 在 |
| N3 | web 关闭链接管（W22/P1） | sidebar.js:121 正则含 `web:`；util.js:243-247 抽屉批量 web→closeEditorTab | ✅ 在（双 hunk） |
| N4' | HTTPError 保全状态码（W30/P3） | web_proxy.py:148-152 `except HTTPError as he` → 「目标返回 HTTP %s」（在通用 except 之前） | ✅ 在 |
| N5 | `_webFavs` 校验+自愈（B13/P3） | web-panel.js:154-165（非数组/缺 url 过滤+回写） | ✅ 在 |

### P1''（W31/W32 全隐语义，R7 定稿）

- 后端：web_tabs.py:22 `_HIDE_ALL="__all__"`、:842 `show(,hide_all)`、:861 哨兵写 `_want`、:821-827 `_apply_visibility` 全隐分支（幂等，a575 后并入全挂起）；REST show 分支 `all` 参数透传（:1100-1104）
- 前端：`_webCtlVisible(on, all, target)`:432（`all→d.all=true`）；switchTab 直发守卫点已被第 11 例 `_webReconcileVis` 单一权威推演**收编**——want 条件含 `!reader && !sleeping`（:469），全隐经 :509 `_webCtlVisible(false, true)` 真实下发。语义完整保留，属架构演进非丢失
- 判定 ✅ 在

### D 批（D1/D2/D3=a/D6/D7/D8 + R9 缺口处置 + B26-B28）

| 项 | HEAD 核对 | 判定 |
|---|---|---|
| D1（W3 三重 + D1''/W24） | `_webPageEpoch` 随机后缀:25；pagehide beacon 带 epoch:54-59；`dispose_all(epoch)` 覆盖 `_ctl ∪ _pending`:898-923；`_epochs` 四处清理（create:361/dispose:881/A4'':409/pending:915） | ✅ 在 |
| D2（W4，9223+门控） | `_detect_cdp()`:1007-1025（DEBUG_WEB→config web_cdp 同口径）；`_ensure_env` 显式 options 四旗+条件 9223:281-290；`AreDevToolsEnabled=self._cdp`:474 | ✅ 在 |
| W37（9223 env 冲突修法） | web_tabs.py:302-308 pop→CreateAsync→finally 还原 | ✅ 在 |
| W38/W39 | devtools_cdp.py:264-269 evaluate 回落 `find_webtab_target`；`find_cdps` 已删（:27 注释在案） | ✅ 在 |
| D3=a（W8 单 UI 收紧） | 心跳仲裁 `web-ui-owner`:28-45；`buildWebPanelTab` 非 owner 拦截:227-231；`_webCtl` second-ui-client:402 | ✅ 在 |
| W40 | beacon owner 门:52-56；`dispose_all` 条件 reset（`if n or epoch is None`）:921 | ✅ 在（双半） |
| D6（W36/B27/B28） | server.py:185-190 `@app.errorhandler(404)/(405)` → `/api/*` JSON | ✅ 在 |
| D7=a+c | `net` 逐跳分类:113-116、响应 `net`:167；前端「（内网来源——内容可信度低…）」web-panel.js:1032 | ✅ 在 |
| D8（W28/W29） | `_navSrc` back/fwd/restore 对账:565-597；`_blanked`/`_webRestore`:843/:859；唤醒/巡检走 GoBack:799/:878 | ✅ 在 |
| W42 | restore 消费分支 display-guarded `_webActivePid` 复位:571-572 | ✅ 在 |
| B26 | F5/Ctrl+R 处理器改判 `activePortId`:1095-1100（_webCur 回落语义注释在案） | ✅ 在 |

### 第 11-15 例（用户实锤家族）

| 例 | 修复 | HEAD 核对 | 判定 |
|---|---|---|---|
| 11 | `_webReconcileVis` 单一权威推演 + hide_all + MutationObserver 兜底 | web-panel.js:451-516；2s 周期重推演:543；wrap style 观察器:527-538 | ✅ 在 |
| 12 | 兜底观察器回调修正 + 双真值 + R9.13 禁用结构化扫描 + `.tab-overflow-list` 入名单 | 回调为函数+pend 去抖:520-524；双真值 `onScreen ∧ actWeb===c`:458-468；`anyOverlayOpen` 仅类名快路径（modal/ctx-menu/webFavMenu/nf-menu/tab-overflow-list），结构化扫描禁用注释在案:674-683；`__fcDiag`:688 | ✅ 在 |
| 13 | 暗色底 + suspend 静止帧（CapturePreviewAsync→__webTabShot，≤4MB） | style.css:5847 `.web-body background: var(--bg)`（#101724 暗色）；后端 `t.suspend` web_tabs.py:640-730（R9.3/R9.5 加固 + `len(b64)<=4*1024*1024`:725 + 失败降级隐藏）；前端 `__webTabShot`:643、suspend act 路由在钉测内 | ✅ 在 |
| 14（a571/R9.14） | 镜像免发移除——全隐与目标显示每次真实下发 | :503-510（全隐每次 `_webCtlVisible(false,true)`）、:515（目标每次 `_webCtlVisible(true,false,target)`），R9.14 注释在案 | ✅ 在 |
| 15（a575） | TrySuspendAsync/Resume 渲染管线挂起 | web_tabs.py:792-822 `_suspend_ctl`/`_resume_ctl`；`_apply_visibility` 三分支全部挂接（全隐全挂:824、排他显示 Resume+BringToFront:830-836、只藏目标:840-844）；钉测 `test_hidden_tab_suspends_pipeline`/`test_hide_all_suspends_everything` 在套件中执行 | ✅ 在 |

---

## 三、8 个指定风险点核对

| # | 风险点 | 结论 |
|---|---|---|
| ① | a567 误删 4 路由 | **已恢复且有钉测**：HEAD dispatch 13 act（create/nav/back/fwd/reload/suspend/show/dispose/dispose_all/layout + pw_list/pw_reveal/pw_del）+ bad act 兜底（web_tabs.py:1062-1114）；`test_route_chain_complete` 反向钉「未知 act 必报 bad act」实测 1 passed |
| ② | R9.13 结构化浮层扫描禁用 | **真被禁用**：`anyOverlayOpen` 仅类名快速路径（含 a571 追加的 `.tab-overflow-list`），body 层 fixed/absolute∧z≥100∧相交扫描无残留代码，禁用注释与取舍理由在案（web-panel.js:677-683） |
| ③ | `closest('.close')` 修复 | **在**：web-panel.js:255（回退 ✕ 文字/SVG 双兼容上溯，`e.stopPropagation()` + closeEditorTab），回退 ✕ 后未被"清理" |
| ④ | tray.py 顶部 global（3.14 SyntaxError/R9.7） | **在**：`_watchdog_loop` 函数顶部 `global _tray`（tray.py:531），函数中段旧声明已删；AST/编译实测过。考古：该修入于 a565，回退弹跳后随 a567 祖先链保留（详见 §五） |
| ⑤ | `--disable-web-security` 已删（W1 P0） | **确认未回流**：HEAD 全源码 grep 仅注释命中；无任何一次回退/整文件覆盖把它带回 |
| ⑥ | observe(document)（非 documentElement） | **随功能退役，非丢失**：该修属于 `_PW_FORM_HELPER_JS`（a570 修的 R9.9 注入脚本），a579 用户决定整体移除密码助手（全量清除有案）；存留的 `_ANTI_AUTOSIGNIN_JS` 为 AddScriptToExecuteOnDocumentCreatedAsync + NavigationStarting 重注入，不依赖 MutationObserver |
| ⑦ | `var g=Date.now()` 防签到初值 | **在**：web_tabs.py:40 `_ANTI_AUTOSIGNIN_JS`；钉测 `test_anti_autosignin_injected` 断言 `var g=Date.now()` 在、`var g=0;` 不在，套件中执行 |
| ⑧ | AutofillServerCommunication 已禁 | **在**：web_tabs.py:289 `--disable-features=…,AutofillServerCommunication`（a582 根因4）；配套 `IsPasswordAutosaveEnabled/IsGeneralAutofillEnabled` 真属性名 + 回读日志（:440-455） |

---

## 四、丢失清单（RD 编号）

### RD1【测试钉丢失｜唯一确凿丢失】
- **原编号**：a556 修复「休眠/只藏目标」的回归钉测 `test_show_hide_one_semantics`（d9c8886 随 a556 修复引入）
- **丢失 commit**：`02d5db1`（v4.1.0-a575）——该提交把 `test_show_hide_one_semantics` **误改名为** `test_anti_autosignin_injected`，与 a557（5f4ad0f）引入的同名测试冲突；Python 后定义覆盖前定义 → **a556 语义钉测自 a575 起静默死亡**（pytest 计数不含它，无任何红灯）
- **当前状态**：修复本体健在（web_tabs.py `show` 排他分支 + 推演 want 条件），仅测试钉丢失；同名 dup 在 tests/test_web_tabs_logic.py:337（尸体，docstring 还是 a556 语义）与 :399（真 autosignin 钉，正常运行）
- **影响**：a556「show(false) 只藏目标、不得牵连活动 tab」失去回归保护；未来改动 show 分支时该语义破坏不再被套件捕获
- **重新应用建议**：把 :337 的 dup 改回唯一名 `test_show_hide_one_semantics`（一行改名，零逻辑改动）

### 观察项（非丢失，如实记录）
- **O-D1**：a565（c20f809）摘除「静止帧未生成」900ms 自报横幅 + `_shotAt` 诊断——commit 内注明「知情取舍」（CapturePreview 永挂形态归零信号，Python 侧诊断仍在）；suspend 修复本体保留于 HEAD。
- **O-D2**：a579（021e93f）用户决定退役密码助手，连带清除 observe(document)/`__fcPwHelperV`/WebMessage 桥/DPAPI 存储；a583 以密码管理器（pw_list/pw_reveal/pw_del 读原生 Login Data）重建并同步钉测——意图性演进链，非修复丢失。

---

## 五、版本考古（三文件全程扫描）

**扫描方法**：`git log --all -- <file>` 全部 commit 逐个 `git show --unified=0` 提取 `-`/`+` 行，匹配 38 个修复特征串（删除向）与 10 个坏模式串（回归再引入向）。

**回退事故（reflog 实证）**：
```
HEAD@{21}: commit 0127d7e (a567)
HEAD@{20}: reset: moving to 32dcef7   ← 回退发生（丢弃 a565-a567 提交引用）
HEAD@{19}: reset: moving to 0127d7e   ← 立即弹回，两 reset 之间零提交
```
两次 reset 间无提交、无新分支 → 已提交内容零丢失；代价是工作树在途内容被清（a571 提交说明「tray.py 3.14 SyntaxError 修复（重打）」即此事痕迹——修复本体在 a565 已入库，a567 树含之，弹回后自然恢复，无需真实重打）。

**「删除修复特征串」命中清单（全部核为合理演进，零事故漏网）**：

| commit | 删除内容 | 定性 |
|---|---|---|
| 02d5db1 (a575) | `test_show_hide_one_semantics` 定义名（被误改名） | **RD1 丢失点**（唯一） |
| 6ddea82 (a571) | 镜像免发两段（`_ctlShown!==false` 门控） | R9.14 修复本体（有意移除缺陷机制） |
| c20f809 (a565) | 静止帧自报横幅 + `_shotAt` | 知情取舍（O-D1） |
| c20f809 (a565) | tray.py 函数中段 `global _tray`（a535 版） | R9.7 修复本体（移到函数顶） |
| fe2aab4 (a563) | 旧 hide_all 免发注释 | 被推演架构取代 |
| 0127d7e (a567) | 4 条路由（show/dispose/dispose_all/layout）+ 旧版密码助手 | **事故**——a570 (2cc0ab7) 全量恢复 + 钉测防再犯 |
| 021e93f (a579) | `_PW_FORM_HELPER_JS` 全族（含 observe(document)） | 用户决定退役（O-D2） |
| 51177e4 (a560) | `_ANTI_AUTOSIGNIN_JS` 相关注释行 | 注释随 WEB_TAB_PASSWORD_AUTOFILL=False→True 翻转重写，守卫本体保留 |
| f9d6ec0/34a9dcd 等（a555/a549，审计前） | 旧架构代码 | 审计基线前史，不涉台账修复 |

**「回归再引入」反向扫描**：`--disable-web-security` 实参、`_SINGLE_KINDS` 含 'web'、`var g=0`、`observe(documentElement`、错属性 `PasswordAutofillEnabled`、`"127.0.0.1" not in` 子串判定、`bool(d.get("on", True))`——全部命中均为**修复前历史形态**或修复注释引用；a562（补丁合入）之后无任何一次回流。web_proxy.py 自 a562 后零改动（N1'/N4'/D7 无扰动面）。

---

## 六、结论与建议

1. **44 项修复 + 8 风险点全部核清：修复体系在 HEAD 完好**。历史三次高危情节（回退弹跳、a567 误删路由、多次并行改动）均未侵蚀已审计修复——a570 的恢复 + 钉测、a582/a583 的迭代均在「最小 diff、修不覆盖旧修」的纪律内。
2. **唯一行动项 = RD1**：tests/test_web_tabs_logic.py:337 重命名去重（恢复 a556 钉测）。建议顺手给测试文件加「重名检测」（CI 里 `python -c "import ast,..."` 扫同名 def，一行成本，防 a575 同款事故再犯）。
3. 遗留观察项照旧：W41（设计内竞态，记录）、O1（▶ 一次落白可走出）归桌面手册；R9.13 结构化浮层扫描重建待定位误判源。
4. 工作树 a581 在途改动（shell 终端）与审计修复零交集；提请合入时保持「不动 web_tabs.py 显隐/路由段」即可维持本报告结论。

*报告完。审计员 D，2026-11-16。git 全程只读；仓库唯一新增 = 本报告。*
