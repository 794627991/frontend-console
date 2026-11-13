# 第 9 轮黑盒验证报告 —— 前端控制台「前端控制台 R9」（精简复验轮：R8 确定性补丁 + D 批设计实现）

- 轮次：round 9（前任因配额中断的 R9 验证，本 run 为重启后的完整精简复验）
- 日期：2026-11-13
- 测试对象：当前工作树（git status：`M src/devtools_cdp.py src/main.py src/web_proxy.py src/web_tabs.py web/js/settings.js web/js/sidebar-resize.js web/js/sidebar.js web/js/util.js web/js/web-panel.js web/style.css`；**`src/server.py` 零改动**——见 B27/B28 根因）。D 批实现落位：D1=web-panel.js pagehide epoch + F5/Ctrl+R 分区、D3=a=UI 心跳门控、D7=web_proxy.py `_web_is_private_host`/`net` 标注、D8=web-panel.js `_navSrc` 栈对账 + W29 GoBack 恢复；**D6（API JSON）全仓无实现**
- 方法：IAB（ZCode 内置浏览器）合成事件驱动（round-8 同口径）+ 只读 fetch/sendBeacon 记录器（单包裹，记录后透传原实现）+ console 直调内部函数（任务清单指定）+ 服务端访问日志仲裁；curl 直打 API 层（D6/D7）
- 成本纪律：全轮仅 4 张截图（3 张计划内关键截图 + 1 张顺带拍得的 D3=a 门控旁证）；其余全部以请求记录/console 证据代替；无矩阵重跑
- 铁律遵守：零代码修改（仓库仅新增本报告）；测试产物进临时目录 `C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r9-run2\`；结束全部还原（见 §八，含实机 4068 观察的如实记录）

---

## 终判结论

13 个测试格：**10 格通过、3 格失败（B26–B28，全部为「补丁缺口/未实现」型，无「新破坏」型）**。

| # | 测试点 | 判定 |
|---|---|---|
| 1① | D1 激活网页 tab：F5/Ctrl+R → 刷网页非整页 | ✅ 通过 |
| 1② | D1 激活非网页 tab：F5/Ctrl+R → 零请求吞掉 | ❌ **B26**（2 条 reload 泄漏到后台网页 tab） |
| 1③ | D1 阅读态 .web-body contextmenu 屏蔽 | ✅ 通过 |
| 2 | D1 epoch 回收（dispose_all beacon + 新纪元重建） | ✅ 通过 |
| 3 | D8 三站跨站导航栈对齐（◀◀/▶ 指针移动零污染） | ✅ 通过 |
| 4 | W29 GoBack 恢复（nav(about:blank)→back 非 nav(real_url)） | ✅ 通过 |
| 5 | D3=a 单 UI 收紧（buildWebPanelTab null+横幅、_webCtl second-ui-client） | ✅ 通过 |
| 6a | D6 GET /api/nonexistent → JSON | ❌ **B27**（Werkzeug HTML 404，D6 无实现） |
| 6b | D6 POST /api/status 错误方法 → 405 JSON | ❌ **B28**（Werkzeug HTML 405，同根） |
| 6c | D7 fetch_text 响应含 "net":"private" | ✅ 通过 |
| 6d | 「发给 Claude」无会话横幅 | ✅ 通过 |
| 7a | 侧栏 ✕ 关 tab：dispose + 零 /api/disconnect + 零幽灵 layout | ✅ 通过 |
| 7b | web-favs='"x"' 刷新后自愈 [] | ✅ 通过 |
| 7c | 非激活 tab 地址栏回车落所属 tab id | ✅ 通过 |

---

## 一、环境准备（全部操作留痕）

1. **清场**：开场 netstat 快照——18765=pid 6640（旧 r8v2 副本）、18999=pid 1320（`http.server --directory Temp/audit-bb-r9/testsite`）、19001/19002=pid 19880（`echo_v4.py`，存活可复用）、8765+56278=pid 4068（**用户实机，禁动**）。`taskkill /F` 显式杀 6640、1320，复验两端口清空。
2. **隔离实例**：robocopy 当前工作树 → `%TEMP%\audit-bb-r9-run2\`（排除 `.git/docs/data/dist/build`——dist 4.0G/build 207M 为 PyInstaller 产物，源码启动不需要）；副本 `src/server.py` 尾部 `port=8765`→`port=18765`（sed，仅副本）。
3. **独立 home**：`%TEMP%\audit-bb-home-r9-run2\.serialconsole_pro\config.json` = `{"data_dir":".../audit-bb-home-r9-run2/data"}`；`USERPROFILE=<临时home> python -m src.server` 后台启动（pid 24224，**未设 HARNESS_DEBUG_WEB——正常模式**，D1 处理器生效前提，实测 `__HG_DBG__===false`）。
4. **靶标**：18999 静态页（testsite 自 audit-bb-r9 复制进 run2，`http.server` pid 9748）；19001/19002 echo_v4 复用遗留 pid 19880。
5. **记录器声明**：页面加载后一次性安装只读 fetch 记录器（`window.__r9log`）与 sendBeacon 包裹（证据写 localStorage `r9beacon` 以跨刷新存活），记录后透传原调用；服务端访问日志全程仲裁。

环境准备完成后进入正式黑盒测试；此后唯一的注入类操作 = 任务清单明确指定的 console 直调（`_webSleep`/`_webRestore`/`buildWebPanelTab`/`_webCtl`/合成 KeyboardEvent/MouseEvent）与测 7b 的故障种子 `web-favs='"x"'`（该格被测行为本身）。

## 二、测试点 1：D1 刷新策略 —— ①③通过 / ②失败 → B26

### 格 ①：激活网页 tab，F5/Ctrl+R 刷网页非整页 ——【通过 ✅】

- 操作：顶栏地址栏开 `18999/plain.html` 网页 tab（`portId=web:32481851-vmis:1`，`tab=web-32481851-vmis-1`），保持激活；向 document 派发合成 `KeyboardEvent(key='F5')` 与 `KeyboardEvent(key='r', ctrlKey=true)`。
- 实测：两条事件均 `defaultPrevented===true`；请求记录恰为 2 条 `{"act":"reload","tab":"web-32481851-vmis-1"}`（**刷新网页**语义，非整页 reload）。
- 主文档未重载三重证据：派发前设 `window.__r9mark` 派发后仍在；`performance.timeOrigin` 不变；`performance.getEntriesByType('navigation').length===1`。
- 代码对应：web-panel.js:814-820（document 捕获段 keydown，`_webAct('reload', c.wrap)`）。

### 格 ②：激活非网页 tab，F5/Ctrl+R 零请求吞掉 ——【未翻转 → B26】

| 预期 | 实测 |
|---|---|
| 激活 tab 为非网页（Claude/harness）时派发 F5/Ctrl+R → **零请求**（吞掉，主文档不刷新） | `preventDefault` 生效（主文档确未刷新，半句成立），但请求记录出现 **2 条** `{"act":"reload","tab":"web-32481851-vmis-1"}`——**每键一条，打到后台网页 tab 上** |

- 现场：tab 栏激活项 = `harness:gui`（Claude 对话），网页 tab 已转后台（面板 display:none）；清分界后派发 F5 与 Ctrl+R，`/api/web` 侧唯一流量即上述 2 条 reload；主文档标记/timeOrigin 证据与格①同款成立。
- 根因（行为级坐实后的代码定位，仅用于刻画）：D1 处理器（web-panel.js:818）取 `const c = _webCur()` 判定「激活 tab 是网页」；而 `_webCur()`（web-panel.js:290-298，a554 注释）在**无激活网页 tab 时回落第一个网页 tab**，且 `switchTab` 切走时不清 `_webActivePid`（实测切换后仍为 `web:32481851-vmis:1`）→ 处理器把「用户停在 Claude tab」误判为「激活是网页」，F5 语义从「吞掉」变「刷掉用户后台正开着的网页」。补丁覆盖了 `_webCur()===null`（无网页 tab）与「激活即网页」两分支，漏了「多开且激活非网页」这第三分支。
- 判级：缺口型（D1 语义未完全落地），非新破坏型。真实实例后果：用户在 Claude/串口 tab 按 F5，后台网页 tab 被 Reload（可见页面突变+会话页面重载）。

### 格 ③：阅读态 .web-body 右键屏蔽 ——【通过 ✅】

- 操作：网页 tab 内点「☰ 阅读」（GUI，阅读态确认：reader display=''、web-host display='none'、正文 49 字符）；向 `[data-web-body]` 派发合成 `MouseEvent('contextmenu')`。
- 实测：`e.defaultPrevented===true`；`#ctxMenu` 保持隐藏（`offsetWidth/offsetHeight` 均 0），无任何菜单层出现；`__HG_DBG__===false`（正常模式路径，web-panel.js:806）。

## 三、测试点 2：D1 epoch 回收 ——【通过 ✅】

- **id 形态**（console 读连接对象）：`portId = web:<epoch>:<n>`（任务书写作 `web:<epoch>-<n>`；实际 portId 分隔符为**冒号**，`_tabId`/请求 `tab` 字段为**短横** `web-<epoch>-<n>`，web-panel.js:158-159）——形态含纪元段成立，分隔符差异如实记录。
- 双 tab：`web:32481851-vmis:1`、`web:32481851-vmis:2` 同纪元并存。
- **reload 抓 beacon**：`location.reload()`（工具化 tab.reload()）触发 pagehide → sendBeacon 证据（localStorage 捕获原文）：
  `{"act":"dispose_all","epoch":"32481851-vmis"}` → `/api/web/tabs`
  服务端仲裁：reload 时刻（09:21:21）`POST /api/web/tabs 200` 请求簇（全程共 192 条 POST /api/web/tabs 全 200）。
- **新页面新纪元**：刷新后 `_webPageEpoch = 32851799-21nz`（≠旧纪元）；等心跳仲裁窗口（6s，`web-ui-owner` 时间戳规则）过后建 tab，请求序列正常：`show(sq1)` → `create(url=…/plain.html, epoch=32851799-21nz, tab=web-32851799-21nz-1)` → `show(sq2..4)`。响应体为 `{"ok":false,"err":"控件管理器未装配"}`——隔离实例（纯 Flask，无 pywebview 宿主装配 WebTabs）的**预期形态**，请求级口径与 round-8 一致；round-8 §B21 已同款处理。
- 后端按 epoch 只动本纪元控件的语义在隔离实例无法直证（管理器未装配），本轮判据 = beacon 携带正确 epoch + 新纪元不受迟到 beacon 干扰（新纪元 tab 全功能，见截图 3）。

## 四、测试点 3：D8 跨站导航栈对齐 ——【通过 ✅】

- 三站（端口差异模拟跨站 host）：A=`127.0.0.1:18999/plain.html` → B=`127.0.0.1:18765/api/status` → C=`127.0.0.1:18999/special.html`，均走面板地址栏合成回车（真实用户路径）。
- 每站 push 请求：`{"act":"create","url":…,"epoch":…,"tab":"web-32851799-21nz-1"}`；栈读数：`[A] idx0` → `[A,B] idx1` → `[A,B,C] idx2`。
- **◀ 两次**（GUI 点击 `[data-web="back"]`）+ 模拟后端 SourceChanged 推送（隔离实例无 WebView2 事件回推，直调 `__webTabUrl(tabId, url)` 即后端 `_on_src` 推送的同名入口，round-8 合成口径）：
  - ◀#1：请求 `{"act":"back","tab":"web-32851799-21nz-1"}`；推送 B 后 `idx=1`、栈仍 `[A,B,C]`、地址栏=B；
  - ◀#2：同型；推送 A 后 `idx=0`、**栈仍 [A,B,C]（非旧污染形态 [A,B,C,B,A]）**、地址栏=A。
- **▶ 一次**：请求 `{"act":"fwd",…}`；推送 B 后 `idx=1`、**栈不膨胀**（长度恒 3）、地址栏=B。
- 代码对应：W28（web-panel.js:383-395 指针移动对账）+ W29 restore 消费（:371-380）。

## 五、测试点 4：W29 GoBack 恢复 ——【通过 ✅】（附两处测试假象排查）

- 现场：conn 栈顶（`_nav.idx` 指向）= `…/api/status`（真实页）。
- **console 直调 `_webSleep(conn)`**：请求序列 `{"act":"nav","url":"about:blank",…}` → `{"act":"show","on":false,"sq":13,…}`；`conn._blanked===true`、休眠罩 display:flex。
- **console 直调 `_webRestore(conn, 栈顶url)`**：`_blanked` 路径命中——请求记录**紧接一条 `{"act":"back","tab":"web-32851799-21nz-1"}`，无 `nav(real_url)`**（W29 核心断言 ✅；旧形态会发 `create(url=栈顶)` 使原生历史膨胀）。
- **按 ◀**：`{"act":"back",…}` 再发一条；地址栏保持 `…/api/status` 不变、栈顶值不变——不落白屏判据成立（隔离实例前端口径）。
- **假象排查（如实记录，不计缺陷）**：
  1. 首轮 restoreReqs 中混入 `create(url=api/status)+show(sq14)`：系**测试双触发**——手动 `_webRestore` 已消费 `_blanked`，1s 唤醒巡检（web-panel.js:596-607）再触发时走 `_webNavigate` 回落路径 push 了一个重复栈项（[A,B,B]）。真实应用单恢复路径（switchTab 唤醒或巡检二选一，先到先消费）不会双触发；干净复测轮（只 sleep、不手动 restore）栈零变化，证实污染来自测试自身而非出厂路径。
  2. 干净轮中巡检未在 2.2s 窗口内触发：IAB 隐藏页计时器冻结（见 §六 D3=a 同款环境现象）；真实实例切回 tab 由 switchTab 即时唤醒兜底。
  3. 上一轮遗留的未消费 `_navSrc='back'` 标记被本轮模拟推送消费（idx 2→1）：真实实例中休眠导航 about:blank 的 SourceChanged 会清未消费标记（web-panel.js:368 `c._navSrc = null`），隔离实例无该推送故标记滞留——环境假象。

## 六、测试点 5：D3=a 单 UI 收紧 ——【通过 ✅】

- 多页同源（同 localStorage）心跳仲裁实测：**隐藏页计时器会被 IAB 冻结**，旧页心跳 >6s 陈旧后，新页按 6 秒规则**合法**赢得归属（`web-ui-owner` 换手）——这本身是门控设计的正确行为；据此在「确定非 holder」的页面上验证门控：
  - `buildWebPanelTab('http://x')` → **返回 null**；零 tab、零 conn 创建（nTabs=0, nWebConns=0）；横幅原文：「**网页 tab 仅限主窗口使用（检测到第二个 UI 客户端）**」（截图 2）。
  - `_webCtl({_tabId:'web-fake'}, {act:'reload'})` → `{"ok":false,"err":"second-ui-client"}`（web-panel.js:307-309 单点收口）。
- **holder 页功能正常**：其 `buildWebPanelTab('http://x')` 正常建 tab（`web:33299104-92hu:1`），其 `_webCtl` 穿过前端门控到达后端（响应「控件管理器未装配」= 隔离环境预期，证明前端门未拦自己）。
- 旁证（顺带拍得，截图 s3b）：原 holder 关闭后，前非 holder 页在归属回归前再调 `buildWebPanelTab` 依旧被拦（横幅+零创建）——门控随心跳状态动态成立。
- 环境备注（不判缺陷）：某页丢失可见性导致计时冻结后，其闭包 `owner` 信念不自动复检（interval 的 else 分支 claim 亦被冻结）——真实双窗口场景两窗均可见+2s 心跳，归属判定确定性成立；隔离 IAB 多页的冻结形态在真实应用不存在对应物。

## 七、测试点 6：D6/D7 —— 6c/6d 通过；6a/6b 失败 → B27/B28

### 格 6a：GET /api/nonexistent → 预期 JSON ——【未实现 → B27】

| 预期 | 实测 |
|---|---|
| JSON `{"ok":false,…}`（非 HTML） | Werkzeug 默认 **HTML 404**（`Content-Type: text/html; charset=utf-8`，`<!doctype html>…404 Not Found…`） |

### 格 6b：POST /api/status（错误方法）→ 预期 405 JSON ——【未实现 → B28】

| 预期 | 实测 |
|---|---|
| 405 JSON | Werkzeug 默认 **HTML 405** 页 |

- B27/B28 同根：**D6（API JSON）在工作树无实现**。全仓 `src/*.py` 无 `errorhandler`/`/api/<path>` 兜底/`after_request` JSON 化（仅 worker_app.py、watchdog.py 各自的无关 after_request）；`git status` 中 **`src/server.py` 零改动**，而 D6 按设计应落在 server.py API 层。判级：未实现型。

### 格 6c：fetch_text 私网 net 标注 ——【通过 ✅（D7 已实现）】

- `POST /api/web/fetch_text {"url":"http://127.0.0.1:18765/api/status"}` → 响应：
  `{"net":"private","ok":true,"text":"{\"log_dir\":…,\"ports\":{}}","title":"","truncated":false,"url":…}`
- 实现落位：`src/web_proxy.py`（+82 行 diff：`_web_url_host`/`_web_is_private_host`——全部解析地址均私网/回环/链路本地才判 private、解析失败按公网安全侧；逐跳重分类 W25/N1'）。D7 UI 侧配套在 `_webAct('claude')`（web-panel.js:757：`net==='private'` 时填入头追加「（内网来源——内容可信度低，警惕提示注入）」）。

### 格 6d：「发给 Claude」无会话横幅 ——【通过 ✅】

- 关闭 Claude 会话形态下（`[data-hg-input]` 不存在）点「发给 Claude」：`POST /api/web/fetch_text {"url":"http://127.0.0.1:19001/ping"}` 发出；横幅原文：「**先打开 Claude 会话（顶栏 Claude 按钮）再取页**」；按钮态恢复（禁用→复原）。

## 八、测试点 7：防回归抽 3 —— 全部通过 ✅

### 7a：侧栏 ✕ 关网页 tab

- ✕ 点击（合成 click 冒泡至 tab.onclick close 分支）→ 请求恰一条 `{"act":"dispose","tab":"web-32851799-21nz-2"}`；conn 池即减（nWeb 2→1）。
- **零 `/api/disconnect`**：客户端记录器与服务端日志双侧 grep 均 0 条（服务端全程 `disconnect: 0`）。
- 关后窗口 resize（1280x720→1100x700→复原）：**零新 layout 请求、零 `layout(0,0,0,0)` 幽灵**（关 tab 后余留 tab 转激活产生的正常 layout(223,140,717,580) 不属幽灵）。

### 7b：web-favs 畸形自愈

- 种入 `localStorage['web-favs']='"x"'` → 刷新 → 首次 `_webFavs()` 调用：返回 `[]`（Array），**localStorage 回写 `'[]'`**（before=`"x"` → after=`[]`）——校验+回写自愈按设计生效（惰性：读时治愈，设计如此）。

### 7c：非激活 tab 地址栏回车归属

- 双 web tab（w1 非激活 display:none / w2 激活）；对 **w1** 的地址栏合成输入 `http://127.0.0.1:19001/ping` + 回车：
  - 请求 `{"act":"create","url":"http://127.0.0.1:19001/ping","epoch":"32851799-21nz","tab":"web-32851799-21nz-1"}`——**落所属 tab id（w1）**；伴随 `show(sq26, tab=w1)`（B22 定向语义）；
  - w1 栈 `[plain, api/status, ping]` idx2 正确入栈；w2（激活）栈 `[long.html]` 分毫未动。
- 附注（不计缺陷）：`show(true, w1)` 对隐藏 tab 的真实 HWND 后果（控件短暂前置）在隔离实例不可证——该显隐指令本身即 R8-B22 修复后的「定向所属 tab」语义，归属正确性以请求为判据。

## 九、截图证据（3 计划内 + 1 顺带）

- 截图 1 `screens-r9r2\s1_reader_mode.png`：网页 tab 阅读态全景（正文「普通测试页 Plain/hello」、双 tab 栏、工具栏）——测 1③ 现场形态。
- 截图 2 `screens-r9r2\s2_second_ui_banner.png`：非 holder 页 D3=a 拦截现场——右下红框横幅「网页 tab 仅限主窗口使用（检测到第二个 UI 客户端）」+ tab 栏空（零创建）——测 5。
- 截图 3 `screens-r9r2\s3_webpanel_webview.png`：归属回归后网页 tab 网页视图全景（地址栏完整 URL、◀▶⟳/★/阅读/发给Claude/浏览器 工具栏）——测 2「新页面建 tab 正常」与面板形态。
- 顺带 s3b `screens-r9r2\s3b_page1_gated_by_d3a.png`：原 holder 存续期间旧页被 D3=a 拦截（横幅在右下）——门控动态性旁证。

## 十、收集到的页面异常

- 全程（含刷新后）console 无未捕获异常可见 manifestations：无横幅异常、无面板布局破碎、无加载失败占位层弹出（`.web-err` 始终隐藏）；隔离实例 WebView2 控件不存在属预期形态（web-body 空白宿主区）。
- 唯一预期内提示流：首次启动数据目录弹窗、休眠罩（🌙 已休眠以省内存）——均为设计内 UI。

## 十一、环境还原记录

- 浏览器测试页关闭（controlled tab ×3 全闭）。
- 显式 taskkill：24224（隔离实例 18765）、9748（18999 静态靶标）、19880（echo_v4 19001/19002，前任遗留，一并还原）。
- 终态 netstat：18765/18999/19001/19002 全清（TEST-PORTS-CLEAR）。
- 测试产物全部位于 `%TEMP%\audit-bb-r9-run2\`（副本、home、日志 r9r2-server.log、截图 screens-r9r2\），仓库内唯一新增 = 本报告。

## 十二、实机 4068 观察（如实记录，非本审计操作所致）

- 开场快照（本报告 §一第 1 条）确认实机 pid 4068 在 8765/56278 监听；本审计全程**无任何指向 4068 的操作**（全部 taskkill 均显式 PID：6640/1320/24224/9748/19880，逐一可查）。
- 收尾 netstat（§十一）发现 4068 已不在运行、8765/56278 无监听、进程表无对应 python 进程；消亡时点无法回溯（期间跨度约 40 分钟，用户自行关闭或其他外部原因均可能）。判定：与本审计无信号交集，如实上报供主控/用户知悉。

---

*报告完。失败编号自 B26 起：B26（D1 非激活分支 reload 泄漏，缺口型）、B27/B28（D6 API JSON 未实现，未实现型）。*
