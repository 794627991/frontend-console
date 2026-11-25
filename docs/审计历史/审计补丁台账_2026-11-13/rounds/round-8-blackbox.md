# 第 8 轮黑盒验收翻转测试报告 —— 前端控制台「内嵌浏览器」功能（补丁验收轮）

- 轮次：round 8（R1–R7 全部审计补丁合入后的**验收快照翻转测试**——与 R1–R7 相反，本轮测的是修复后代码）
- 日期：2026-11-13
- 测试对象：工作树 d9c8886 + **未提交审计补丁**（git status：9 文件修改 +293/-90；patch-round-1..6 全量合入；APP_VERSION 2.4.3，页面标题 v2.4.3，脚本版本参数 v=4.1.0-a467）
- 方法：IAB 合成事件驱动 + 只读 fetch 记录器（单包裹，**服务端日志仲裁**）+ curl/python 直打 + 靶标（18999 静态 / 19001 echo / 19002 自签 https；echo_v4 = echo_v3 全量 + 新增 /to-file、/notfound 两格）
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068，端口 8765）未杀未干扰、仅 GET 探测；测试产物进临时目录（截图 `C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r8\screens-r8\`）；隔离实例与靶标测试结束后全停、端口全清
- 环境：隔离实例**从补丁后仓库树重建**（旧临时副本 audit-bb-r2 为补丁前代码，弃用）——robocopy 仓库树→`%TEMP%\audit-bb-r8`（排除 .git/docs/data），副本内 `src/server.py` 尾部 port 8765→18765，新 home `audit-bb-home-r8`（config 指向独立 data_dir）

---

## 终判结论

24 个翻转格中 **19 格翻转确认**、**5 格未翻转**（B21–B25，**全部为「补丁未生效」型，无「新缺陷」型**——补丁没有引入新破坏）。回归抽查 6 项 + 基础冒烟 3 项全部无漂移。

> **【R8 补记（同日复验）】**主控修复 B21–B24（W33–W35）后复验：B21/B22/B23/B24 **4 格全部翻转确认**（隔离实例从修复后工作树重建，audit-bb-r8v2）；B25 改判**按设计**（私网自签不校验为 N1 设计内行为，见 §十三）。最终账目：**24/24 格关闭 = 23 格翻转确认 + 1 格改判按设计，零遗留**。B7 矩阵抽 2 格（★/⟳）与 B16 抽 1 格防回归全部保持翻转。详见 §十三。

未翻转的三项同根：**A8' 补丁只改了调用点、被调函数未接 conn 参数**（`_webNavigate`/`_webCtlVisible`/`_webApplyZoom` 三处死参数），补丁语义被静默丢弃。

---

## 一、测试点 1：B7 矩阵翻转（A8' 族——非激活 tab 操作归属）

场景：web-1 = plain.html（**非激活、面板 display:none**）、web-2 = special.html（**激活可见**）；对**非激活 web-1 面板**的按钮/地址栏合成事件驱动（既定口径）。截图 `screens-r8\t1_b7_twotabs.png`。

### 格 C：非激活面板地址栏回车 ——【未翻转 → B21】

| 预期（翻转后） | 实测 | 基线快照（R5 快照 1 / B1） |
|---|---|---|
| nav 请求带**所属 tab id**（web-1），激活 tab 不受影响 | `{"act":"create","url":"…/long.html","tab":"web-2"}`——**落激活 tab**；web-2 胶囊被改写为 long.html、其 webview 被导航、web-session 被污染；web-1 零请求 | 同型错位：非激活操作错落激活 tab（❌ 应为所属 ctl） |

- 记录器原文（双份）：`create(url=long.html, tab:"web-2")` ×2；实测状态 `pills=[plain(非激活), long(激活)]`，两面板地址框均显示 long.html（web-1 为我方输入残值，web-2 为真实导航）。
- **根因（行为级坐实后的代码定位，仅用于刻画）**：`web-panel.js:176` 面板 keydown 处理器已按补丁调用 `_webNavigate(u, conn)`（:187 注释「R2 审计 B1（A8）：导航目标=本 tab（conn）」在位），但 `:410` `function _webNavigate(url)` **签名未接第二参数**，函数体首行 `const c = _webCur()`——传入的 conn 被静默丢弃，**调用点补丁成为死代码**。
- 环境排除：已预热 HTTP 缓存（`fetch(cache:'reload')` 全部 6 个 JS）+ 硬刷新后重测；服务器端 `web-panel.js` 经 `cache:'reload'` 回读含全部补丁标记（「导航目标=本 tab」「全隐语义」「按钮属于哪个 wrap」均 true）——**排除旧脚本缓存干扰后结论维持**。

### 格 D：非激活面板 ★ 收藏 ——【翻转确认 ✅】

| 预期（翻转后） | 实测 | 基线快照（R2-B1/R5 快照 1） |
|---|---|---|
| 收藏/取消**所属 tab** 的 URL | `web-favs` 增 `plain.html`（web-1 的 URL）✅；标题经 `/api/web/fetch_text {"url":"…/plain.html"}` 取得（目标正确） | ❌ 收藏/取消激活 tab 的 URL（long.html） |

### 格 E：非激活面板 ☰ 阅读 / 退出阅读 ——【部分翻转：内容 ✅ / 控件显隐 ✗ → B22】

| 预期（翻转后） | 实测 | 基线快照（R6 §一 B10 现场 / R5 快照 1） |
|---|---|---|
| 阅读开在**所属 tab**：show(false, web-1) + nav(about:blank, web-1) | 内容侧 ✅：`nav(about:blank, tab:"web-1")` ×2 + `fetch_text(plain.html)` ×2（阅读视图取 web-1 内容）<br>**显隐侧 ✗**：`show(on:false, sq13, tab:"web-2")` ×2 + `show(on:true, sq14, tab:"web-2")` ×2——hide/show 对落在**激活 tab** | ❌ 阅读模式开在激活面板（show(false, tab:"web-2") 出现在操作 web:1 按钮时） |
| 退出阅读恢复所属 tab | 内容侧 ✅：`nav(plain.html, tab:"web-1")` ×2；显隐侧 ✗：`show(on:true, sq22, tab:"web-2")` ×2 | 同上 |

- 末态无害（web-2 控件先藏后显、终态可见），桌面后果 = 可见性抖动；但「作用于所属 tab」的补丁语义对显隐通道**未生效**。
- 同型根因：`_webCtlVisible(on)` 无 conn 参数、取 `_webCur()`（`_webReaderToggle` 内容路径已按补丁传 c，显隐路径丢弃）。

### 格 F：非激活面板「发给 Claude」 ——【翻转确认 ✅】

| 预期（翻转后） | 实测 | 基线快照（R2-B1） |
|---|---|---|
| 填入**所属 tab** 内容 | Claude 输入框（`hg-input`）= `[网页内容 「普通测试页 Plain」 http://127.0.0.1:18999/plain.html]\n\nhello`（web-1 的 URL/标题）✅ + 横幅「已填入 Claude 输入框（检查后发送）」✅ + `fetch_text(plain.html)` ✅ | ❌ 填入激活 tab 内容（long.html） |

- 前置：需先打开 Claude 会话（未开时横幅「先打开 Claude 会话（顶栏 Claude 按钮）再取页」——既有门控）。截图 `t1_b7_claude_banner.png`、`t1_b7_claude_filled.png`。

### 格 G：非激活面板 Ctrl+滚轮缩放 ——【未翻转 → B23】

| 预期（翻转后） | 实测 | 基线快照（R5 快照 1） |
|---|---|---|
| 缩放落**所属 tab**（值/样式/记忆键） | 记忆键 `web-zoom:127.0.0.1:18999` 1→1.1 ✅（两 tab 同 host，键无法区分归属）；**样式 ✗**：激活 web-2 的 `.web-frame.web-host` 得 `zoom:1.1`，非激活 web-1 保持 `zoom:1`——**样式落激活 tab** | ❌ 缩放落激活 tab（值/样式/记忆键三重） |

- 同型根因：`_webApplyZoom(z, host, c)` 调用点传 c、被调函数取 `_webCur()`。

**测试点 1 小结**：D/F 翻转、E 内容侧翻转、**C/G 未翻转 + E 显隐侧未翻转**——A8' 族三个被调函数（`_webNavigate`/`_webCtlVisible`/`_webApplyZoom`）同一模式死参数。

---

## 二、测试点 2：N3 翻转（侧栏 ✕ dispose + 幽灵归零）——【4/4 全翻转 ✅】

场景：pill 切至 web-2（long.html，顺带预检普通切换语义）→ 侧栏（`.port-item.active` ✕「断开」）关闭 → 合成 resize（R6 口径：`window.dispatchEvent(new Event('resize'))` ×2）。

| # | 预期（N3 回归口径，R5 §一） | 实测 | 基线快照（R5 快照 2） |
|---|---|---|---|
| 1 | dispose 请求出现 | `{"act":"dispose","tab":"web-2"}` ×2 ✅ | （无 dispose） |
| 2 | `/api/disconnect` 噪音消失 | 记录器过滤含 `/api/disconnect`，**0 条** ✅ | `POST /api/disconnect {"port_id":"web:2"}` 必败噪音 |
| 3 | resize 后全零 layout 数 = 0 | resize 后记录 **0 条 layout**（closed web-2 无幽灵）✅ | `layout(0,0,0,0, tab:web-2)` 幽灵 |
| 4 | 存活 tab layout 正常 | 切回 web-1 后 resize → `layout(223,140,717,580, tab:"web-1")` ×2（rect 非零）✅ | 存活正常（此项基线即正确） |

- 附加观察：关闭激活 web tab 后自动切 Claude tab，出现 `show(on:false, sq25, web-1)`（后台 web-1 控件隐藏——语义正常）。截图 `t2_n3_after_close.png`。

---

## 三、测试点 3：N5 翻转（web-favs 自愈）——【2/2 全翻转 ✅】

### 格 1：非数组畸形串 ——【翻转确认 ✅】

| 预期（翻转后） | 实测 | 基线快照（R3-B13） |
|---|---|---|
| 刷新后收藏菜单**可开** | 菜单打开，显示空态「还没有收藏——网页 tab 里点 ★ 或地址栏打开后收藏」✅（截图 `t0_smoke_favdel.png` 同型） | ❌ 菜单打不开（favs.map 抛异常无提示） |
| 键自愈回 `[]` | 菜单打开/首次访问后 `localStorage['web-favs']` = `"[]"` ✅（刷新后即时值仍为畸形串，随菜单渲染落盘自愈——延迟落盘形态，终态达成） | 存储保持畸形值直到手工清键 |

### 格 2：缺 url / 数字 url / null url 元素 ——【翻转确认 ✅】

| 预期（翻转后） | 实测 | 基线快照（R4 快照 4 七格） |
|---|---|---|
| 元素被过滤、无 undefined 泄露 | 写入 4 元素（缺 url / url=123 / url=null / 合法项）→ 刷新 → 菜单**仅渲染合法项**（valid-one），`itemTitles=[…plain.html]`，全文 0 个 "undefined" ✅（截图 `t3_n5_filter_menu.png`） | 缺 url 元素渲染 + tooltip 泄露 "undefined"；数字 url 入导航栈 |

---

## 四、测试点 4：fetch_text N1'/N4' 翻转（5 格，curl 直打 `POST /api/web/fetch_text`）

| 格 | 预期（翻转后） | 实测 | 基线快照 | 判定 |
|---|---|---|---|---|
| 1. 302→自签 https（19001/to-https-final） | **必须失败**（证书校验生效） | `{"ok":true,"text":"FINAL-OK"}`——**取页成功** | CERT_NONE 跨主机实锤（R4/R5） | **✗ B25（R8 补记改判：按设计**——私网自签不校验为 N1 设计内行为，见 §十三.2**）** |
| 1b. 直取自签 https 变体 | 失败 | `https://127.0.0.1:19002/final` 与 `https://localhost:19002/final` 均 `ok:true FINAL-OK`——**两种主机名均接受自签** | 同上 | ✗（B25 加固证据） |
| 2. 302→file://（19001/to-file） | 「重定向到不支持的协议」 | `{"err":"取页失败：重定向到不支持的协议","ok":false}` ✅ | urllib 原文 `Redirection to url 'file:///' is not allowed` | ✅ |
| 3. 404 目标（19001/notfound） | 「取页失败：目标返回 HTTP 404」 | `{"err":"取页失败：目标返回 HTTP 404","ok":false}` ✅ | 「取页失败：HTTPError」 | ✅ |
| 4. 私网自身 API（18765/api/status） | 仍可取（私网回落保持） | `ok:true` + /api/status JSON（log_dir 指向隔离 home）✅ | R2-B2 同 | ✅ 保持 |
| 5. 非 ASCII 主机（http://中国.example/） | 可读文案（不外露 latin-1 异常） | `{"err":"仅支持 http(s) 链接","ok":false}`（HTTP 400）——可读、无内部异常 ✅ | `'latin-1' codec can't encode…` 直出 | ✅ |

- B25 注记：公网证书严格性在本环境无法判定（`self-signed.badssl.com`/`expired.badssl.com` DNS 不可达：「无法连接目标（域名不存在或网络不可达）」；`https://www.baidu.com/` 正常取页）。按本轮验收口径「此格必须翻转为失败」**未达成**；若实现语义为「仅公网启用证书校验、私网回落保持宽松」，则该验收口径需主控复核改写——无论何种解释，R4 验收表所定格的那一格未翻转。

---

## 五、测试点 5：P1'' 翻转（W31/W32 阅读态全隐语义）——【3/3 全翻转 ✅】

场景：web-1（plain）激活态进阅读 → 开 web-2（special）→ **pill 切回阅读态 web-1** → 退出阅读 → 普通切换。

| 步骤 | 预期（P1'' 验收断言，R7 §一） | 实测（记录器原文） | 基线快照（R7 §一） |
|---|---|---|---|
| 切回阅读态 tab | **全隐请求**（`all:true` 或等价）取代排他 show；零矩形 layout 照旧（无害） | `{"act":"show","on":false,"sq":8,"all":true,"tab":"web-1"}` ×2 ✅（无排他 show）；`layout(0,0,0,0, web-1)` ×2 照旧 ✅ | **`show(on:true, sq12, tab:"web-1")`**（排他显示阅读态 A=W31/W32 缺陷本体）+ layout(0,0,0,0) ×2 |
| 退出阅读 | 恢复排他 show | `show(on:true, sq9, web-1)` + `nav(plain.html, web-1)` + `show(sq10, web-1)` + layout(223,140,717,580) ×4 ✅ | `show(true, sq41)+nav(原URL)+show(sq42)` |
| 普通切换 | 排他 show(on:true) 不变 | 切 web-2：`show(on:true, sq11/12/13, web-2)` 全排他 ✅（N3 场景中切换亦复核一致） | 排他 show 不变 |

---

## 六、测试点 6：A10''/A6 抽查

### 6a. 面板地址栏 `javascript:alert(1)` ——【翻转确认 ✅】

| 预期 | 实测 | 基线快照 |
|---|---|---|
| 横幅 + 零导航 | 红色横幅「**该协议不允许在内嵌浏览器打开**」✅（截图 `t6_a10_js_banner.png`）；记录器 **0 条** nav/create ✅；tab 数不变 ✅ | B4：javascript: 补 http:// 入栈 |

### 6b. 顶栏 `file:///C:/x` ——【部分翻转：零导航 ✅ / 横幅 ✗ → B24】

| 预期 | 实测 | 基线快照 |
|---|---|---|
| 横幅且不误开空 tab | **不误开空 tab** ✅（pills 恒 2、零 create/nav 请求，同步+400ms 双查）；**无横幅** ✗（顶栏路径静默吞掉非法协议；面板路径有横幅——A10'' 反馈面未覆盖顶栏） | 顶栏回车 newTab 语义（对照格，无协议变体定格） |

### 6c/6d/6e. REST `POST /api/web/tabs` ——【200 JSON 非 500 ✅；语义面无头不可观测（手册承接）】

| 探针 | 实测 | 判定 |
|---|---|---|
| `{"act":"show","on":true,"sq":"NaN","tab":"web-1"}` | HTTP **200** + `{"err":"控件管理器未装配","ok":false}` ✅ 非 500 | ✅ |
| `{"act":"show","on":"false","sq":100,"tab":"web-1"}` | HTTP 200 JSON ✅ | on:"false" 布尔解析语义与 sq 门控早退在无头被「控件管理器未装配」短路（R5 黑盒不可达清单 #2 同口径）→ 桌面验证手册承接 |
| `{"act":"show","on":"yes","sq":101,…}` / `{"act":"show","on":false,"all":"true","sq":102,…}`（P1'' REST 面） | 均 200 JSON ✅ | all 参数解析不 500 |
| 怪 id：tab=-5 / 1.5 / {"a":1} | 均 200 JSON 优雅 ✅ | 与 R1/R3 一致 |
| 顶层数组 `[1,2,3]` | HTTP **400** + `{"err":"请求体必须是 JSON 对象","ok":false}` ✅ | 与 R3「顶层数组 400 JSON」一致 |
| 坏 JSON `{bad json` | 200 优雅 ✅ | 与 R1 一致 |
| fetch_text url=123 | 400 `{"err":"仅支持 http(s) 链接"}` ✅ | 可读 |

---

## 七、测试点 7：全量回归抽查（6 项）+ 基础冒烟（3 项）——【全部无漂移 ✅】

| # | 项 | 实测 | 证据 |
|---|---|---|---|
| 1 | 收藏持久化（含 XSS 标题跨刷新） | special.html（标题含 `<script>alert(9)</script>`）入藏 → 刷新 → favs 原样、菜单纯文本渲染（menu DOM 0 script / 0 img）✅ | `t0_smoke_favmenu.png` |
| 2 | 设置开关持久 | **web_cdp 口径**：开关 on → `config.json` 即时 `"web_cdp": true` → off → `"web_cdp": false` ✅（与 R3 口径一致）。附注：终端「自动复制」开关 UI toggle 正常，但**无终端会话时不落盘**（config/localStorage 均无写入）——R3 原测含终端会话，环境差异记观察项 | config.json 前后对照 |
| 3 | API 怪 id 优雅 | 见 6c/6d 表——负数/浮点/对象 id、顶层数组、坏 JSON、怪参全优雅，与 R1/R3 逐项一致 ✅ | — |
| 4 | XSS 三面 | ① 收藏菜单：XSS 标题纯文本、0 script/0 img ✅ ② 阅读模式：special.html 阅读视图标题以文本呈现、pane 内 0 script/0 img、无 alert 弹窗 ✅ ③ tab 胶囊：label innerHTML 纯 URL 文本、无标签注入 ✅ | `t7_xss_reader.png` |
| 5 | resize 布局（900×500） | `scrollWidth 900 = clientWidth 900`、hOverflow:false；主页面与设置浮层均无横向溢出、顶栏正常压缩 ✅ | `t7_resize_900.png` |
| 6 | 重启恢复 | 杀隔离实例（PID 20324）→ 重启（新 PID 1860）→ 刷新：favs（含 XSS 标题）/ web-session / web-zoom 键三态完好、无首启数据目录弹窗 ✅；**空回车开网页 tab 恢复上次页**（a475 无 URL 恢复路径 GUI 可达：空输入回车 → 新 tab 落 plain.html）✅ | `t7_restart_restore.png` |
| 冒烟 1 | 页面加载 | 标题/面板/侧栏/助手全渲染 ✅ | `t0_smoke_initial.png` |
| 冒烟 2 | 收藏增删 | 面板 ★ toggle（favs `[]`↔入藏、title 收藏/取消翻转）+ 菜单内 ✕ 删除（空态文案出现）✅ | `t0_smoke_favdel.png` |
| 冒烟 3 | 设置开关 | 自动复制 checkbox 勾选/还原 + CDP 开关（config 即时写）✅ | — |

---

## 八、未翻转/新问题清单（B21 起——全部标注「补丁未生效」）

| 编号 | 级别 | 类型 | 内容 | 根因刻画 |
|---|---|---|---|---|
| **B21** | P2 | 补丁未生效 | **非激活面板地址栏回车落激活 tab**：`create(url, tab:"web-2")`、激活 tab 被导航、胶囊改写、web-session 污染（§一·格 C） | A8' 只改调用点：`_webNavigate(u, conn)` 的 **conn 参数被 `function _webNavigate(url)` 丢弃**（web-panel.js:410 仍 `const c = _webCur()`）——调用点补丁为死代码 |
| **B22** | P3 | 补丁未生效 | **非激活面板阅读进出，控件显隐 show 仍落激活 tab**（hide/show 对，末态正确、桌面为可见性抖动；内容归属已翻转） | 同型：`_webCtlVisible(on, all)` 无 conn 参数、取 `_webCur()`——`_webReaderToggle` 内容路径传 c 被丢弃 |
| **B23** | P3 | 补丁未生效 | **非激活面板 Ctrl+滚轮缩放样式落激活 tab**（web-2 `.web-frame` 得 zoom:1.1、web-1 保持 1；记忆键同 host 无法区分归属） | 同型：`_webApplyZoom(z, host, c)` 调用点传 c、被调函数取 `_webCur()` |
| **B24** | P3 | 补丁未生效（部分） | **顶栏非法协议静默吞掉**：file:/javascript: 零导航/不误开空 tab 达成，但顶栏路径**无横幅**（面板路径有）——A10'' 反馈面未覆盖顶栏入口 | 顶栏 Enter 处理器无 A10'' 的 showBanner 分支 |
| **B25** | P2 | **R8 补记改判：按设计** | **fetch_text 自签 https 仍被接受**：302→自签 https 与直取（127.0.0.1/localhost 双主机名）均 ok:true——原判「补丁未生效」经主控复核改判：**私网自签不校验为 N1 设计内行为**（web_proxy.py:93 docstring「内网 https 自签不校验（本地单用户…）」、:115「仅私网/回环目标回落不校验（内网自签）」自述）；公网自签严格性需公网环境，**桌面/手册承接** | 设计内回落；badssl 类公网自签目标实测留手册 |

> B21/B22/B23 为**同一根因的三种表现**：A8' 族补丁在调用点传 conn、在三个被调函数处参数缺失——修复方向明确（给三个函数加 conn 形参并替换 `_webCur()` 回落），风险低、面清晰。

---

## 九、观察项（不计缺陷）

1. **请求 ×1/×2 双发模式**：单动作经记录器常现同包双发（同 sq ×2）。**服务端日志仲裁**：一次星标动作 = 服务端实收 3 请求（fetch_text+show+layout），与单包裹记录器计数一致——双发为应用真实行为非记录器伪影；与 R6「双通道」/R7「单请求」合并图景相符（通道触发依 DOM 状态而变）。sq 门控使重复包幂等无害。
2. **IAB origin localStorage 跨轮污染**：IAB 按 origin（127.0.0.1:18765）持久 localStorage——R2–R7 各隔离实例共用该 origin，残留键（web-zoom 怪键、旧收藏）跨轮存活。本轮开局清理一次后重测；后续轮次应轮首清理。
3. **浏览器 HTTP 缓存跨轮共键**：?v=4.1.0-a467 版本参数在补丁前后相同 → 同 origin 缓存可能命中补丁前旧 JS（本轮格 C 首测即中此招，已用 `cache:'reload'` 预热+硬刷新排除）。后续轮次轮首必须预热。
4. **非激活面板地址栏残值**：输入未导航的值残留显示（cosmetic；真实用户在非激活面板本就无法输入，自动化路径才可达）。
5. **刷新后 tab 不自动恢复为正确语义**（a475：会话栈在下次开 tab 时消费；空回车恢复验证 ✅）——R3「刷新恢复」表述按此口径理解，非回归。
6. 终端「自动复制」开关无终端会话时不落盘（R3 口径差异，环境受限）——桌面/有终端会话场景由手册复核。

## 十、环境修正记录（按 skill 规范申报）

1. 开局清理 IAB origin localStorage（跨轮残留）→ 冒烟结果以相对增量读取，不受影响。
2. 格 C 首测作废一次（浏览器缓存补丁前旧 JS）：预热 6 个 JS（cache:'reload'）+ 硬刷新后重测——作废与重测均记录在案。
3. 双发仲裁实验一次（§九.1）：单包裹记录器 + 服务端日志对账。
4. 记录器守卫：每格检查 `window.__rec` 存在性，页面刷新后重装（单包裹）。

## 十一、复用与工具经验

- 隔离实例（补丁后树）：`cd %TEMP%\audit-bb-r8 && USERPROFILE=%TEMP%\audit-bb-home-r8 python -m src.server`（端口 18765；副本内 server.py 尾部 port 已改 18765）
- 靶标：`python %TEMP%\audit-bb-r8\echo_v4.py`（19001 http：loop/loc-space/loc-uni/loc-rel/to-https-final/**to-file**/final/echo-headers/**notfound**；19002 自签 https）+ 18999 静态（audit-bb-r8/testsite）
- 工具经验：⑥ **echo 靶标必须发 Content-Length**（HTTP/1.1 keep-alive 下无 CL 会挂死 curl/客户端——echo_v4 已修）；⑦ **同 origin 补丁前后必须预热 HTTP 缓存**（?v= 版本参数不变时浏览器缓存旧 JS，伪造「补丁未生效」）；⑧ 设置浮层单击后内容异步渲染需 ≥1.5s 再断言；点击用 dom_cua ref 路径最稳（cua 坐标在滚动容器内会漂移）；⑨ 请求计数仲裁必须用服务端日志（双通道双发会与记录器伪影混淆）。

## 十二、清理核验

测试结束时逐项回收：隔离实例（18765）与靶标（18999/19001/19002）进程全停、端口清零；用户真实实例（pid 4068，8765）全程未杀未干扰（仅早期 GET /api/status 探测两次）。仓库内唯一新增文件为本报告。

---

## 十三、复验补记（R8 同日——主控修复 B21–B24（W33–W35）后的翻转复验）

- 复验对象：工作树（修复合入后）再次拷贝重建隔离实例 `audit-bb-r8v2`（端口 18765，新 home `audit-bb-home-r8v2`）——**旧副本不含修复，弃用**；修复标记核对：`_webNavigate(url, c)`（:410）、`_webCtlVisible(on, all, target)` + `target || _webCur()`（:293-294，定向调用 :423/:535）、wheel/ctrl0 `connections[wrap.dataset.portId]`（:215/:225）、顶栏横幅分支（:715）全部在位；`web-panel.js` 31737 字节（R8 为 31232）。
- 环境规程复用 R8：JS 全量 `cache:'reload'` 预热 + 硬刷新 + localStorage 清零 + 双 tab 场景重建（web-1=plain 非激活隐藏 / web-2=special 激活可见）+ 单包裹记录器。
- 截图：`C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r8v2\screens-r8v2\`（t_r8v2_b24_topbar_banner.png）。

### 1. B21–B24 复验结果（4/4 翻转确认）

| 格 | 预期（翻转后） | 实测（记录器原文） | R8 未翻转基线 | 判定 |
|---|---|---|---|---|
| **B21** 非激活面板地址栏回车（long.html） | nav 请求带**所属 tab** id，激活 tab 不受扰 | `{"act":"create","url":"…/long.html","tab":"web-1"}`——落 web-1 ✅；web-1 胶囊改写 long.html、栈 [plain,long]；**web-2 胶囊/地址/零请求**（完全不受扰） | create 落 web-2、激活 tab 被污染 | **✅ 翻转** |
| **B22** 非激活面板阅读**进入** | show 带所属 id 且激活 tab 控件不受扰 | `show(on:false, sq23, web-1)` + `nav(about:blank, web-1)` + fetch_text(long.html)——**全带 web-1**；**web-2 零 show 流量** | show(false/true, web-2) hide/show 对落激活 tab | **✅ 翻转** |
| **B22** 非激活面板阅读**退出** | 同上 | `show(on:true, sq24, web-1)` + `nav(long.html, web-1)`——全带 web-1、web-2 零流量 | 同上 | **✅ 翻转** |
| **B23** 非激活面板 Ctrl+滚轮（pane/body/bar 三点派发） | zoom 落**所属 tab** | 前：双 frame `zoom:1`、键 `web-zoom:127.0.0.1:18999`=1；后：**web-1 frame `zoom:1.1`**、web-2 frame 保持 `zoom:1`、键 1.1——样式/值/记忆键三者一致落所属 tab | 样式落激活 web-2（web-1 保持 1） | **✅ 翻转** |
| **B24** 顶栏 `file:///C:/x` | 横幅出现（且零导航不误开 tab） | 横幅「该协议不允许在内嵌浏览器打开」**同步出现**（+400ms 仍在）✅；记录器 0 请求、pills 恒 2 ✅ | 顶栏静默吞掉无横幅 | **✅ 翻转** |
| **B24** 顶栏 `javascript:alert(1)` | 同上 | 同横幅 ✅、0 请求、pills 2 ✅ | 同上 | **✅ 翻转** |

### 2. B25 改判记录（按设计）

- 改判依据（主控复核 + 源内证据）：`src/web_proxy.py:93` docstring「……**内网 https 自签不校验（本地单用户**……）」、`:115`「R2 审计 W18（N1）：**仅私网/回环目标回落不校验（内网自签）**」——回环 19002 自签取页成功属 N1 设计内回落，非补丁失效。
- 原验收格「302→自签 https 必须失败」的预期口径与 N1 设计不一致，验收口径随本补记修正。
- **公网自签严格性**：需公网环境实测（badssl 类目标在本环境 DNS 不可达），**桌面/手册承接**。

### 3. 抽格防回归（B7 ×2 + B16 ×1）

| 抽格 | 操作 | 实测 | 判定 |
|---|---|---|---|
| B7·★ | 非激活 web-1 星标 | favs 增 **long.html**（web-1 URL，标题取回正确） | ✅ 翻转保持（R8-D 复现） |
| B7·⟳ | 非激活 web-1 刷新 | `{"act":"reload","tab":"web-1"}`——带所属 tab id | ✅ 翻转保持（R5 快照 1 基线「❌ 串激活」已修） |
| B16 | pill 切 web-2（激活）→ 侧栏 ✕ | `dispose(web-2)` 出现、**0 条 /api/disconnect**；自动切 web-1 排他 show(sq27/28)；resize 后 layout 全非零、`zeroRect:0` | ✅ 翻转保持（R8-N3 四断言复现） |

### 4. 复验附加观察

- R8 §九.1 的「请求 ×1/×2 双发」在复验轮全部观测为**单发**（create/show/nav/fetch_text/reload/dispose 均 ×1）——与 R6/R7 合并图景一致：双通道触发依 DOM 状态而变，非稳定行为，维持「不计缺陷」。
- 复验轮未发现任何新异常；修复未引入回归。

### 5. 最终账目（R8 + 补记）

- 原账：24 格 = 19 翻转 + 5 未翻转（B21–B25）。
- 补记后：**24/24 格关闭 = 23 格翻转确认（19 + B21/B22/B23/B24 复验翻转）+ 1 格改判按设计（B25），零遗留缺陷**。
