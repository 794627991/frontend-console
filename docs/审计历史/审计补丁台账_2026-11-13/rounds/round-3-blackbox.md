# 第 3 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能

- 轮次：round 3（B7 变体族全矩阵 + fetch_text 深化 + localStorage 对抗 + UI 状态机轰炸 + 多客户端浮层联动 + 回归快扫）
- 日期：2026-11-13
- 测试对象：v4.1.0-a556 基线 d9c8886（patch-round-1/2 均为提案未应用，本轮实测即基线行为；读毕 `patch-round-2.md`，本轮产出直接对接 A8'/N1/D3/D1' 的验收点）
- 方法：IAB 合成事件驱动（真实输入通道 t=0 失效，与 R2 一致）+ curl/python 直打 API + 临时靶标（18999 静态 / 19001 echo-重定向 / 19002 自签 https）
- 证据目录（仓库外）：`C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r3\screens\`
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068）未杀未干扰，仅 GET 探测
- ⚠ 副作用披露：矩阵测试中「↗ 浏览器」按钮两行走通 `/api/open_url` → `webbrowser.open()`（server.py:1778），隔离实例**两次拉起系统默认浏览器**指向本地靶页 `http://127.0.0.1:18999/special.html`（应用对有效 http URL 的设计行为，无害，如实记录）

---

## 一、确凿发现（新编号 B10 起）

### B10【P2·确凿】B7 变体族矩阵补全：6 种操作 ×（激活/非激活）全格——非激活侧全部错落在激活 tab 上（A8' 验收基线）

方法：双 tab（web:1=plain.html 非激活、web:2=special.html 激活），页面内装**只读 fetch 记录器**（不改行为，仅记录 `/api/web/tabs`、`/api/open_url` 的 URL+body）+ 每 action 后读双面板 `.web-host` 样式/`_ui.zoom`/localStorage 记忆键。

| 操作 | 在激活 tab 上操作 | 在非激活 tab（web:1）上操作 | 判定 |
|---|---|---|---|
| back | `{"act":"back","tab":"web-2"}` ✅ | **`{"act":"back","tab":"web-2"}`** ❌ 应为 web-1 | 串 |
| fwd | `tab:"web-2"` ✅ | **`tab:"web-2"`** ❌ | 串 |
| reload | `tab:"web-2"` ✅ | **`tab:"web-2"`** ❌ | 串 |
| sys（↗浏览器） | open_url(web-2 的 special.html) ✅ | **open_url(special.html)** ❌（应为 plain.html） | 串 |
| Ctrl+滚轮 | web:2 zoom 1→1.1、记忆键=1.1 ✅ | **web:2 zoom 1→1.1**、web:1 全不动 ❌（值/样式/记忆键三重落点全错） | 串 |
| Ctrl+0 | web:2 复位 ✅ | **web:2 的 1.7 被复位**、web:1 不动 ❌ | 串 |

- 三重错落细节（滚轮/Ctrl+0）：`_webApplyZoom` 内 `c=_webCur()` 一处取值同时污染 ①缩放值 `c._ui.zoom` ②本面板 `.web-host` 样式 ③localStorage `web-zoom:<激活tab的host>` 记忆键（web-panel.js:553-563）；事件监听虽绑在各 wrap 自己的 body/wrap 上（:200/:211），效果全走激活 tab。
- 与 R2-B1（star/read/claude）合并：**7 种操作 × 2 条件矩阵全部坐实**，唯一同根 = 「所属 tab」语义缺失。A8' 补丁的 `_webAct/_webReaderToggle/_webApplyZoom/_webSyncUI` 参数化清单与本矩阵一一对应，可作为其验收基线。
- 触达性：非激活面板不可见不可点（同 B7），但 AI 网页操作（web_cdp）/自动化路径可达。

### B11【P2·确凿】fetch_text 深化：跨协议重定向链全贯通 + 自签 https 被接受（CERT_NONE 黑盒实锤）——B8 结论加固

在自建靶标（19001 http + 19002 自签 https）上逐项实测：

| # | 项 | 结果 |
|---|---|---|
| 17-20 | **301/302/307/308 四种状态 × http→https→http 跨协议链** | **全部贯通**：`CHAIN-END` 返回，200（R2 的 302→内网结论扩展为全状态码、跨协议） |
| 21 | **自签 https 直取** | **成功返回**——`CERT_NONE` 黑盒实锤（patch N1「公网可被中间人投喂正文」的前提成立） |
| 16 | 响应头反射（内部请求头带出） | ✅ 干净：仅 `accept-encoding: identity`、伪造 Chrome 124 UA、`accept-language: zh-CN`、`connection: close`——**无 cookie/无 token/无内部头泄露** |
| 22 | gzip 炸弹（1GB 解压态） | **不成立**：请求头 `accept-encoding: identity` + 应用不解压 → 返回原始 gzip 字节 mojibake，40K 截断生效，全程 2.5s，无内存爆量 |
| 23-24 | 精确 40000/40001 字符 | 40000→`truncated:false` len=40000；40001→`truncated:true` len=40000——**上限恰为 40000 字符，边界精确** |
| 10-12 | application/json / octet-stream / text | 原样返回（无 Content-Type 过滤，二进制 mojibake 但有界） |
| 25 | IDN punycode（xn--…） | 优雅报错（getaddrinfo failed，靶标环境无解析记录） |
| 26/新 | **IDN 非 ASCII 主机** | 见 B12 |
| 27 | 并发 20 个 fetch（每个 1s 延迟靶标） | ✅ **20/20 成功**，总耗时 2.56s（ThreadingTCPServer 表现良好），服务后置存活 |

- 结论维持 R2-B8：仅有的防线 = scheme 白名单 + file 重定向拦截 + 40K 截断；内网/跨协议重定向/自签 https 全放行。

### B12【P3·确凿】非 ASCII 主机取页失败时内部 Python 异常文本外露

- 复现：`POST /api/web/fetch_text {"url":"http://中国.example/"}`（干净 UTF-8 编码）。
- 实际：`{"err":"取页失败：'latin-1' codec can't encode characters in position 0-1: ordinal not in range(256)","ok":false}`——**原始 Python 编码异常文本直出**（http.client 对非 latin-1 主机头的编码崩溃）。
- 预期：统一用户可读文案（如「不支持该主机名」），不暴露内部异常形态。与 R1 记录的 `<urlopen error …>` 形态同类，属同一包装缺口。
- 影响：信息泄露量极小（仅异常类名/位置），P3。

### B13【P3·确凿】web-favs 畸形（非数组）→ 收藏功能整体静默失效且无自愈

- 复现：`localStorage.setItem('web-favs','"just-a-string"')` →
  1. 顶栏 ★ 收藏菜单**打不开**（`favs.map` 抛异常，无提示、无 toast）；
  2. 面板内星标 toggle **静默无效**（异常被内层吞掉，无反馈，存储保持畸形值）；
  3. 刷新/重启均不修复——收藏功能死亡直到手工清键。
- 预期：读失败时回落空数组或至少提示（同文件 web-session 的恢复路径就有 try/catch 静默跳过——两处容错口径不一）。
- 同批其它畸形结构**均安全**：
  - 元素含 `__proto__` 键：JSON.parse 产生**自有属性**，无原型污染（实测 `Object.prototype.polluted` 为 undefined），菜单渲染正常；
  - 120 条收藏：菜单 7ms 构建、120 项全渲染、视口钳制（rect 432h）不出屏；
  - 1MB 单条 title：91ms 构建、CSS 截断显示、布局不破。

### B14【P2·确凿】多客户端 tab id 碰撞 → 浮层联动（a551）跨客户端串隐（D3/D1' 关键佐证）

- 场景构造：客户端 A 刷新（`_webSeq` 归零）→ A 空 Enter 建 tab → **A 的控件 id = `web-1`，与客户端 B 既有控件 id `web-1` 撞名**（各页面独立计数、后端按不透明字符串索引）。
- 实测序列（A 页只读记录器）：
  - A 打开设置浮层 → 立发 `{"act":"show","on":false,"sq":4,"tab":"web-1"}` ×2；
  - A 关闭浮层 → `{"act":"show","on":true,"sq":6,"tab":"web-1"}` + layout。
- 推断（桌面端可达）：后端 `_ctl` 按 tab id 索引——A 的浮层 show(on:false) 会作用到 **B 的同名控件**；叠加 patch 文档 D1-② 已证实的「create 撞 id = navigate 旧控件」，双客户端下 A/B 的显隐与导航互相污染。
- 无头边界：控件级结果不可观测（无原生控件），以上为请求级实证；结论支撑 D3（会话隔离/拒绝第二客户端）与 D1'（纪元令牌）的必要性。

### B15【P3·确认】W9 黑盒再证：web tab 永不进抽屉，12 个仍全平铺

- 连开至 12 个 web tab：`.tab-drawer-bar` 始终不存在、7/12 全平铺、胶囊压缩至图标态（「127…」）仍可点、scrollWidth 不溢出（截图 `r3_drawer_flat.png` / `r3_restart_restore.png` 为 12-tab 场景）。
- 与 patch A7（`_SINGLE_KINDS` 移除 `'web'`）判断一致；现基线下多开会把 tab 条压满但功能可用。

---

## 二、观察项（不计缺陷）

1. **双回车**：同输入连续两次回车 → 导航栈推入两个重复项（[A,A,A]）——与真实浏览器「每次回车=一次导航」语义一致，非缺陷。
2. **凭据 URL**：`http://user:pass@host` 完整入导航栈并持久化进 `web-session`（胶囊/地址栏 UI 层不显示凭据）——与 Chrome 历史行为相同，记录备查。
3. **IME 组合态守卫有效**：`isComposing:true` 的 Enter 被正确忽略（web-panel.js:171 守卫生效），输入框保持原文。
4. **10KB 粘贴**：全量接受（input 10276 字符、栈顶完整、胶囊 24 字符截断），无崩溃。
5. **B3 模型再证（畸形中间态）**：truncated session → A/B 双方恢复均静默跳过 → B 开新 tab 导航写回合法 session → A 刷新后恢复出 **B 的页面**（跨客户端传染路径与 R2 完全一致）。
6. **zoom 怪键**：`web-zoom:<NaN>`（parseFloat 回落 1）、换行/500 字符 host 键闲置无干扰——键名不可经导航注入（host 由 URL 解析器产出），读取路径安全。

## 三、回归快扫（R1「已测未复现」抽查 6 项——基线无漂移）

| 项 | 结果 |
|---|---|
| 收藏持久化 | ✅ 3 条（含 XSS payload 标题）跨重启完好 |
| 设置开关持久 | ✅ web_cdp on→配置 true、off→false，重启后仍 false |
| API 怪 id 优雅 | ✅ 负数/浮点/对象 id、1MB title、坏 JSON 全 200 优雅；顶层数组 400 JSON——与 R1 一致 |
| XSS 三面 | ✅ 收藏菜单 0 img/0 script、阅读模式 0 script/0 img、tab 胶囊纯文本（`pillIsText:true`） |
| resize 布局 | ✅ 900x500 无横向溢出、web-bar 正常折行 |
| 重启恢复 | ✅ 会话恢复 xss-title tab、无首启弹窗、收藏/设置三态齐全（截图 `r3_restart_restore.png`） |

## 四、已测未复现清单（R3 全量）

| # | 测试点 | 结果 |
|---|---|---|
| 1 | Ctrl+滚轮 / Ctrl+0 在激活 tab 上操作（基线格） | ✅ 未复现 |
| 2 | fetch_text 头反射（无敏感内部头带出） | ✅ 未复现 |
| 3 | gzip 炸弹（identity+不解压+40K 截断，2.5s 无爆量） | ✅ 未复现 |
| 4 | 40000/40001 字符边界精确 | ✅ 未复现 |
| 5 | 并发 20 fetch（20/20 成功、服务存活） | ✅ 未复现 |
| 6 | 301/302/307/308 跨协议链（作为 SSRF 通路的确认记录在 B11，非缺陷项复现） | —（记录） |
| 7 | web-favs `__proto__` 元素（无原型污染） | ✅ 未复现 |
| 8 | web-favs 120 条 / 1MB 单条渲染 | ✅ 未复现 |
| 9 | web-zoom NaN 值/怪键读取路径 | ✅ 未复现 |
| 10 | Ctrl+Enter 连开 5 + 逐关 ×3 轮（conns/pills/wraps 每采样点三方一致、终态单 tab 无孤儿） | ✅ 未复现 |
| 11 | IME isComposing 守卫 | ✅ 未复现 |
| 12 | 10KB 粘贴 / 凭据 URL 显示与导航 | ✅ 未复现 |
| 13 | web-session 畸形 → 恢复跳过（A/B 双侧） | ✅ 未复现 |
| 14 | zoom 记忆跨站隔离（R2 回归） | ✅ 未复现 |

## 五、黑盒不可达清单（R3）

1. WebView2 真实控件级结果：浮层 show(on:false) 对**另一客户端控件**的实际显隐效果（无头无原生控件——B14 为请求级实证）；休眠/唤醒、呼吸态、target=_blank、加载失败层（同 R1/R2）。
2. `/api/web/tabs` act 分发与 tab-id 校验（无头被「控件管理器未装配」短路）。
3. IDN punycode 可解析场景（靶标环境无该 DNS 记录，仅记 getaddrinfo failed 形态）。
4. gzip 解压路径的内存表现（应用请求 identity 且不解压——若未来实现解压需重测）。
5. 真实鼠标/键盘（IAB 工具通道 t=0 失效，延续 R2）。

## 六、下一轮复用

- 隔离实例：`cd C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2 && USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server`（端口 18765，临时副本已含端口修正）
- 靶标：`python $TMP/audit-bb-r2/echo_v2.py`（19001 http + 19002 自签 https；含 echo-headers/red301-308/mid/final/gzip-bomb/exact-40000/40001/json-type/binary-type/slow + beacon 记录）；静态页 `python -m http.server 18999 --bind 127.0.0.1`（目录 `$TMP/audit-bb-r1/testsite`）
- 服务日志：`$TMP/audit-bb-r2/server3.log`（主测）、`server4.log`（重启回归）
