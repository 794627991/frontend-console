# 第 4 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能

- 轮次：round 4（W22 双路径基线实证 + 后果链 + B13/B11 补形 + 回归快扫）
- 日期：2026-11-13
- 测试对象：v4.1.0-a556 基线 d9c8886（patch-round-1/2/3 均为提案未应用；已读 patch-round-3.md，本轮产物即 N3/N5/N1' 的验收基线）
- 方法：IAB 合成事件驱动 + **只读 fetch 记录器**（包裹 window.fetch 仅记录不改行为——本轮核心取证手段）+ curl/python 直打 + 靶标（18999 静态 / 19001 http / 19002 自签 https）
- 证据目录（仓库外）：`C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r3\screens\`（延续）+ 服务日志 `$TMP/audit-bb-r2/server5.log`、`server6.log`
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068）未杀未干扰，仅 GET 探测

---

## 一、确凿发现（新编号 B16 起）

### B16【P1·确凿】W22 基线实证（请求级）：侧栏 ✕ 关网页 tab = 必败 disconnect + dispose REST 缺失 + resize 幽灵 layout(0,0,0,0)

**路径①侧栏 ✕**（sidebar.js:113 `closeConnection` 转发白名单 `^(edit|hex|diff|bindiff):` 不含 web，落通用清理）。用只读 fetch 记录器抓到的完整请求序列（两次独立关闭 web:1、web:2 均一致）：

```
POST /api/disconnect   body: {"port_id":"web:1"}     ← 必败噪音请求（web 无连接语义）
（无任何 POST /api/web/tabs {act:"dispose"}）         ← dispose REST 缺失（W22 主证）
（其后只有例行轮询 /api/status 等）
```

- 通用清理实际效果（行为观测）：`conn.tab.remove(); conn.wrap.remove(); delete connections[pid]` 均执行——**DOM 三件套（胶囊/内容区/侧栏行）干净移除**，但 `_webCtlSetup` 注册的 `window resize` 监听与 ResizeObserver 随闭包**存活**。
- **幽灵 layout 实证**：关闭后触发窗口 resize（合成 `window.dispatchEvent(new Event('resize'))`——与真实用户拖窗同监听通道；注：IAB `setViewportSize` 不派发 window resize 事件，为工具限制）：

```
POST /api/web/tabs   body: {"act":"layout","x":0,"y":0,"w":0,"h":0,"tab":"web-1"}   ← 幽灵（已删 wrap 读出全零 rect）
POST /api/web/tabs   body: {"act":"layout","x":223,"y":140,"w":537,"h":510,"tab":"web-3"}  ← 存活 tab 正常 layout（同帧并发）
```

- 关闭时机上无 layout 发出（Chromium 对「元素从 DOM 移除」不触发 ResizeObserver 通知——幽灵只在**下一次窗口 resize**时显形）。
- **细化（W22 白盒描述的补充）**：幽灵 layout 只由「关闭时处于**激活态**」的 tab 留下的幽灵发出——后台态（wrap display:none）关闭的 tab 其幽灵被 `if (conn.wrap.style.display === 'none') return` 守卫永久静默（实测：侧栏 ✕ 关后台 web:2 后，resize 只见 web-1 幽灵、无 web-2 幽灵）。
- **路径②抽屉「全部关闭」**：黑盒不可达——web tab 永不进抽屉（R3-B15/W9：12 个 web tab 无 `.tab-drawer-bar`），批量循环（util.js:243）遍历不到 web pid。N3 第二 hunk（web 分支注入批量循环）需在 A7（`_SINGLE_KINDS` 移除 `'web'`）落地后才有可达路径——验收时序注意。
- 请求级记录即 **N3 验收基线**：修后应见 `{"act":"dispose","tab":"web-N"}` 且无 disconnect 噪音、无幽灵 layout。

### B17【P2·确凿】幽灵监听随侧栏关闭**累积**（W22 后果链）

- 场景：开 web:1（激活）→ 侧栏 ✕ 关 web:1 → 开 web:2/web:3 → 侧栏 ✕ 关激活态 web:2？——按 B16 细化改为等价构造：**每关闭一个激活态网页 tab，即新增一个永久幽灵**（实测两个采样点：单幽灵 → 双幽灵窗口期各发一次 `layout(0,0,0,0)`，幽灵互不抵消、不衰减）。
- 存活 tab 的 layout 与幽灵 layout 同帧并发（请求级记录见 B16 代码块）。
- 桌面端后果（存活控件被缩 50×50、按陈旧 `_want` 重排显隐）依赖后端 `layout()` 对全零 rect 的处理逻辑——无头被「控件管理器未装配」短路，**桌面级后果标注存疑**，请求级实证为确凿。

### B18【P3·确凿】B13 补形（N5 过滤器验收基线）：web-favs「合法但怪异」逐格行为

| 格 | 输入 | 菜单渲染 | 星标/点击语义 |
|---|---|---|---|
| 元素缺 url | `[{title:'无url元素'},…]` | ✅ 渲染 2 项；**tooltip 泄露字符串 `"undefined"`**（`esc(f.url)` 直出） | 点击 → `buildWebPanelTab(undefined)` → 开**空白新 tab**（无导航） |
| url 为数字 | `[{url:12345,…}]` | ✅ 正常渲染 | 点击 → 导航栈推入**数字类型 URL**（类型污染贯通到 stack/localStorage） |
| url 为 null | `[{url:null,…}]` | ✅ 渲染 | 同缺 url（空白 tab） |
| 混合（正常+缺+数字+null） | 4 元素 | ✅ 全渲染无崩溃 | — |
| 恰好 100 条 | 100 元素 | ✅ 4ms 全渲染（视口钳制） | — |
| 尾斜杠重复 | `plain.html` + `plain.html/` | ✅ **两条共存**——去重仅按精确字符串 | 对带斜杠 URL 星标 toggle = 取消该精确串（行为自洽） |
| 容量上限 | — | `_webFavsSave` `slice(0,100)`：超量时**保留最新 100 条**（新条目 unshift 头部） | — |

- 星标匹配 `f.url === url` 为精确串比较：数字/null 元素永远不匹配当前页 → 不影响星标态。
- N5 过滤器（补丁提案）落地后以本表逐格验收。

### B19【P2·确凿】B11 补形（N1' 修复直接基线）：重定向环优雅快速失败 + CERT_NONE 跨主机链路贯通

| # | 项 | 结果 |
|---|---|---|
| 28 | **重定向环 12 跳**（A→B→A…） | ✅ **0.098s 优雅失败**（非挂 15s、非无限跟随）：`HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop`——urllib 循环检测兜底 |
| 29 | Location 带原生空格（`/final?x=1 2`） | ✅ 宽松解析，取页成功 |
| 30 | Location 百分号 Unicode | ✅ 取页成功 |
| 31 | Location 相对路径 | ✅ 正确解析到 /final |
| 32 | **302 → 跨主机自签 https（私网 19002）** | ✅ 取页成功——**CERT_NONE 链路跨主机成立**（N1'「默认验证、私网回落」的前置现状：当前基线对所有 https 一律不验证书，黑盒实锤） |

---

## 二、观察项（不计缺陷）

1. **IAB 工具注**：`setViewportSize` 不派发 window `resize` 事件——本轮幽灵 layout 用合成事件触发同一监听通道取证；真实用户拖窗必触发（监听注册在 `window.addEventListener('resize', push)`，web-panel.js:273）。
2. **IAB 长会话绑定劣化**：8 个历史标签页并存时 evaluate 间歇超时（32s），关闭残留页后瞬时恢复（6ms）——工具侧，非应用缺陷。
3. **readyState 长期 interactive**：页面功能正常但 `document.readyState` 不达 complete（某资源悬挂，疑似 Claude 面板 SSE）——多次会话复现，不影响功能，记录备查。
4. 双回车重复历史项、凭据 URL 入栈、IME 守卫有效——延续 R3 结论，本轮未复测变化。

## 三、回归快扫（三轮清单抽查 5 项 + B7 矩阵 3 格——基线无漂移）

| 项 | 结果 |
|---|---|
| 收藏持久化 | ✅ 重启后 2 条收藏完好（xss-title+plain），会话恢复 special tab，无首启弹窗 |
| 设置开关持久 | ✅ web_cdp on→true / off→false（中断恢复后补齐复位），重启后仍 false |
| API 怪 id 优雅 | ✅ 负数/对象 id、坏 JSON → 200 优雅；顶层数组 → 400 JSON——与 R1 一致 |
| XSS 三面 | ✅ 收藏菜单 0 img/0 script（3 项全渲染）、阅读模式 0 script/0 img、胶囊纯文本 |
| resize 布局 | ✅ 900x500 无横向溢出、web-bar 正常 |
| B7 矩阵抽 3 格（star/back/wheel @ 非激活） | ✅ **三格全部复现变体**：star@web:3 取消的是激活 tab（web:4）的收藏（favs [xss,plain] 实证）、back → `tab:"web-4"`、wheel → web:4 缩至 1.1 而 web:3 不动——A8' 基线稳定 |

## 四、已测未复现清单（R4 全量）

| # | 测试点 | 结果 |
|---|---|---|
| 1 | 侧栏 ✕ 关闭的 DOM 三件套移除（胶囊/内容区/侧栏行同步干净） | ✅ 未复现（问题不在 DOM 清理，在 dispose REST 缺失与幽灵监听） |
| 2 | 关闭时机即发幽灵 layout（Chromium 对 DOM 移除不触发 RO） | ✅ 未复现（幽灵只在下次 resize 显形） |
| 3 | 后台态关闭 tab 的幽灵（display:none 守卫拦截） | ✅ 未复现（守卫有效——幽灵语义细化） |
| 4 | web-favs 各怪异格崩溃/原型污染/溢出 | ✅ 未复现（仅 tooltip "undefined" 与类型污染为记录项） |
| 5 | 重定向环挂死/无限跟随 | ✅ 未复现（0.1s 优雅失败） |
| 6 | Location 空格/Unicode/相对路径解析失败 | ✅ 未复现 |
| 7 | 抽屉「全部关闭」关闭网页组 | ⛔ 黑盒不可达（W9：web 不进抽屉，N3 第二 hunk 无可达路径） |
| 8 | 幽灵 layout 的桌面端后果（存活控件 50×50） | ⛔ 黑盒不可达（无头无控件管理器——请求级已证，桌面级存疑） |
| 9 | 回归 5 项 + B7 三格漂移 | ✅ 未复现 |

## 五、下一轮复用

- 隔离实例：`cd C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2 && USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server`（端口 18765）
- 靶标：`python $TMP/audit-bb-r2/echo_v3.py`（19001 http：loop 重定向环/loc-space/loc-uni/loc-rel/to-https-final/final/echo-headers；19002 自签 https：final）+ `python -m http.server 18999 --bind 127.0.0.1`（目录 `$TMP/audit-bb-r1/testsite`）
- 服务日志：`$TMP/audit-bb-r2/server5.log`（W22 主测）、`server6.log`（重启回归）
- 工具经验：IAB 多页长会话会绑定劣化——每轮开始清残留 IAB tab；页面级 fetch 记录器是 W22/N3 类「请求序列」取证的最简手段（只读包裹，不改行为）。
