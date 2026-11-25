# 第 2 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能

- 轮次：round 2（R1 发现回归 + 同根变体 + SSRF 炮击 + 多客户端深化 + 未覆盖 UI 面 + D1 补丁预演）
- 日期：2026-11-13
- 测试对象：v4.1.0-a556（基线 d9c8886，与 R1 相同——R1 补丁仍为提案未应用）
- 方法：ZCode 内嵌浏览器（IAB）+ curl 直打 API + 临时靶标服务器（重定向/超大/非 HTML/echo）
- 证据目录（仓库外）：`C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2\screens\`
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068）全程未杀未干扰，仅 GET 类探测

---

## 0. 环境与工具通道说明

1. **端口隔离（R1 B5 环境修正落地）**：8765 起测前已被真实实例占用（netstat 证实）。处置：运行树整体拷贝到临时区 `$TMP/audit-bb-r2/`（src/web/vendor/ico/offline_*，约 3.5G），**仅改临时副本** `src/server.py:3599` 的端口 8765→18765，仓库零改动。隔离实例跑在 **127.0.0.1:18765**，与真实实例全程零冲突（启动后核验 8765 仍归 4068、`GET /api/status` 形态不变）。USERPROFILE 重定向沿用 R1 配置（数据目录在临时区）。
2. **真实输入通道冒烟（R1 遗留问题复核）**：新 origin 全新页面 **加载后立即** 测试——真实 Playwright 点击（`#btnLogs`）超时失败、真实 `fill()+press("Enter")` 无效果。**比 R1（约 1 分钟后失效）更早，t=0 即失效**，与 profile/无痕无关（IAB 无 profile 概念，已用全新 origin 复测）。判定：IAB 工具通道缺陷，非应用缺陷。本轮全程按任务书授权采用合成事件驱动（与应用内部 `el.click()` 同款），文本仍走真实 `fill()`。
3. 靶标：18999（静态靶页，沿用 R1）、19001（重定向/echo 服务器，临时脚本）。⚠ 测试过程记录：echo 服务器首版只实现 do_GET，POST 全 501 不记日志——第一轮 beacon 观测无效，修正 do_POST 后重测（下文数据均来自修正版）。

---

## 一、R1 发现回归结果

| R1 ID | 结论 | R2 证据 |
|---|---|---|
| B1 跨 tab 串导航 | **复现确认**（全新实例同路径同结果） | web:1 地址栏回车 → web:2 被导航（stack/input/pill 全变），web:1 不动 |
| B2 发送静默失败 | **部分修正 + 数据丢失确认**（见 R2-B3） | 横幅其实出现（类名 `.notify.err`）；输入仍被清空 |
| B3 多客户端会话互踩 | **复现确认 + 机制细化**（共享单栈，见 §四） | web-session 为共享单栈，双方共同追加，恢复互踩 |
| B4 协议不感知 | **复现确认** | `javascript:`/`file:` 补 http:// 入栈（本轮未做变体扩展） |
| B5 8765 端口冲突 | **环境项已解决**（端口隔离方案落地，无应用侧缺陷） | 18765 隔离实例方案 |
| B6 HTTP 形态一致性 | **复现确认** | 错误方法仍 HTML 404；无 Origin 放行、错 Origin 403 |

## 二、本轮新发现（确凿）

### R2-B1【P2】B1 同根变体：`_webAct` 全按钮族（star/read/claude/back/fwd/reload/sys）一律作用于「激活 tab」而非「按钮所属 tab」

- 根因：`_webAct(act, wrap)` 首行 `const c = _webCur()`（web-panel.js:576）——与 B1 的 `_webNavigate` 取 `_webCur()` 同一根因，影响面扩大到全部工具栏按钮。
- 行为级坐实（web:1=plain.html 非激活，web:2=long.html 激活）：
  1. **star**：点 web:1 的 ★ → 收藏进的是 **long.html（web:2 的 URL）**，web:1 的 plain.html 未被收藏（localStorage `web-favs` 证据）；
  2. **read（☰ 阅读模式）**：点 web:1 的 ☰ → **web:2 的面板**切到阅读模式（显示 long.html 正文），web:1 无变化；
  3. **claude（发给 Claude）**：点 web:1 的「发给 Claude」→ Claude 输入框填入 **web:2 的内容**（`[网页内容 「超长标题…」 http://127.0.0.1:18999/long.html]`），横幅「已填入 Claude 输入框」；截图 `r2_claude_variant.png`。
- 代码级同根（行为在无头下不可区分，但与 star/read/claude 同一入口同一行取值）：**back/fwd/reload**（`_webCtl(c,…)` 的 c 来自 `_webCur()`）与 **sys**（`url` 取 `_webCur()` 的栈顶）。
- 触达性：与 B1 相同——非激活面板不可见不可点，自然触发受限；桌面端若有焦点竞态/自动化/AI 驱动（本工具自带 AI 网页操作能力，web_cdp 开关）即成实际面。
- 复现步骤：双 tab → B 激活 → 对 A 面板按钮合成 click（或 DevTools 驱动）→ 观察落点在 B。
- 修复建议：与 R1 补丁 A8 同方向——`_webAct` 增加 conn 参数（调用点已有 `wrap`，取 `connections` 反查或传 conn）。

### R2-B2【P2】`/api/web/fetch_text` 是无内网限制的本机+局域网 HTTP 全读原语（R1 P3 备注，本轮升级并实锤）

- 逐项炮击结果（POST /api/web/fetch_text，全部 JSON 响应）：

| # | 目标 | HTTP | 结果 |
|---|---|---|---|
| 1 | `file:///C:/Windows/win.ini` | 400 | ✅ 拒绝（`仅支持 http(s) 链接`） |
| 2 | 自实例 18765 `/api/status` | 200 | ⚠ **内部 API JSON 泄露**（log_dir 路径等） |
| 3 | **真实实例 8765/** | 200 | ⚠⚠ **读出真实实例发布中心页面全文：「前端控制台 · 发布中心…默认密码 888888（发布者可在工具 设置→关于与升级 中修改）」** |
| 4 | **真实实例 56278 `/api/status`** | 200 | ⚠⚠ **读出真实实例状态 JSON（`log_dir: D:\Frontend Console\logs`）** |
| 5 | `http://localhost:18999/plain.html` | 200 | 正常取页（localhost 可达） |
| 6 | 302 → `file://`（19001/tofile） | 200(err) | ✅ urllib 重定向策略拦截（`Redirection to url 'file:///' is not allowed`） |
| 7 | **302 → 内网 http**（19001/tointranet → 18765/api/status） | 200 | ⚠ **重定向被跟随，内部 API JSON 泄露**（http→http 无任何限制） |
| 8 | 302 → `169.254.169.254`（云元数据形态） | — | 连接超时（网络不可达，黑盒环境限制；机制与 #7 同链路） |
| 9 | `http://evil.com@127.0.0.1:18999/plain.html`（userinfo 形态） | 200(err) | 未绕过：`getaddrinfo failed`（对 evil.com 发起了解析——urllib 层行为，无泄露） |
| 10 | 超大 60MB HTML | 200 | ✅ `truncated:true`，text 上限 **40000 字符**，title 正常提取（无内存爆量） |
| 11 | PNG 二进制 | 200 | 原样 mojibake 返回（2KB，truncated:false，title 空）——无 Content-Type 过滤 |
| 12 | JSON / 纯文本 | 200 | 原样返回（非 HTML 无害但无类型处理） |
| 13 | DNS 失败 | 200(err) | 优雅报错 |

- 结论：scheme 白名单（仅 http(s)）+ file 重定向拦截是仅有的两道防线；**回环、localhost、局域网、跨实例、重定向到内网全部可达**。最重实证是 #3：隔离实例通过该接口读到了**真实实例发布中心页面**（含默认密码提示文案）。
- 缓解背景：fetch_text 的 URL 来源是用户导航栈（地址栏/★/发给Claude），页面本身无法指定任意 URL——攻击面主要是「本机其他进程/脚本」与「AI 驱动链路」。建议：加内网/回环黑名单或至少对非用户显式确认的内网目标提示；截断上限与重定向白名单（http→http 同站）已有部分防护。

### R2-B3【P2】发送失败输入丢失（R1-B2 修正版）：有 3.5s 错误横幅，但用户输入仍被清空且不恢复

- 完整请求/响应链存档（harness 侧）：
  - 触发：Claude 对话页点击发送（`.hg-send`）→ 前端 `ensureSession()`（chatctl.js:89）
  - 请求：`POST /api/harness/connect`，`Content-Type: application/json`，body `{"model":"","cwd":"","permission":"auto","think":""}`（取自前端代码）
  - 响应：**HTTP 503**，body `{"err":"Claude 后端未就绪（worker 未启动）","ok":false}`
  - 服务端日志：`POST /api/harness/connect HTTP/1.1 503`（多次，含 curl 复现）
- UI 时序实测（send 点击后 300ms/1.5s 两点采样 + 截图 `r2_b2_send.png`）：
  - ✅ 修正 R1 结论：错误横幅**确实出现**（红色 `.notify.err` / `.n-title`「Claude 后端未就绪（worker 未启动）」，约 3.5s）——R1 报告「无任何反馈」是 +4s 采样错过横幅窗口所致；
  - ❌ 数据丢失确认：两次探针输入（「R2-B2 静默失败回归测试文本」等）点击发送后 `inputVal=""`——`send()` 先清空输入，`ensureSession` 的 `ok:false` 路径仅 `return null` **不恢复输入**（只有网络异常 catch 分支才恢复，chatctl.js:120-127）；
  - 结果：用户看到错误横幅一闪而过，但输入的文本永久丢失。
- 修复方向（与 patch 文档 D4 一致）：`ok:false` 路径补 `showBanner(err,…)` 已有 → 需补 **恢复输入框内容**。

---

## 三、已测未复现（R2 新增，防重复）

| # | 测试点 | 结果 |
|---|---|---|
| 1 | 阅读模式全链路：开（内容/标题/URL 正确）→ 导航自动关 → 再开 → 再点关 | ✅ 未复现 |
| 2 | 星标与当前 URL 同步：收藏 → 导航走星标灭 → 导航回星标亮（`var(--accent)` 精确对应） | ✅ 未复现 |
| 3 | 缩放记忆跨站隔离：`web-zoom:<host:port>` 按站隔离（127.0.0.1:18999=1.5 与 localhost:18999=0.8 互不串；导航/回切正确应用） | ✅ 未复现 |
| 4 | web-session 畸形 JSON 容错：截断 JSON / `[1,2,3]` 数组 / 1MB 超长——刷新不崩、UI 存活、恢复路径静默跳过；1MB 合法会话可恢复且保存时**自愈剔除冗余字段** | ✅ 未复现 |
| 5 | 时序轰炸：3 tab ×（快速切换全部 + 并发关非激活 tab）两轮（每轮 10-30 次，中途被工具 32s 上限打断后继续）——最终 conns↔pills↔wraps 三方一致、单一 active、无孤儿无重复 | ✅ 未复现（工具超时非应用卡死，页面即时响应） |
| 6 | 多客户端内存隔离：B 全程操作不影响 A 内存态，反之亦然 | ✅ 未复现（互踩仅发生在 localStorage 共享会话，见 §四） |
| 7 | fetch_text 超大响应截断（40K 字符上限）、file 协议拒绝、file 重定向拦截 | ✅ 防线有效 |

## 四、多客户端深化（R1-B3 机制细化 + 精确复现步骤存档）

共享 `web-session` 为**单栈共享模型**（非整键覆盖）：后写者把自己的导航**追加**到同一栈上。精确步骤（全部实测，localStorage 原值存档）：

1. 客户端 A 导航其 tab → `web-session = {"stack":[special,long,links],"idx":2}`；
2. 客户端 B 全新加载（pills=0，读到 A 的会话）→ B 空回车恢复 → **B 直接继承 A 的栈**并打开 links.html；
3. B 导航 bodyxss → 同栈追加：`{"stack":[special,long,links,bodyxss],"idx":3}`；
4. **A 刷新页面**（pagehide——当前代码无任何卸载清理）→ A 恢复前 conns=[]，空回车后 **A 打开的是 B 的 bodyxss**（A 自己最后所在 links.html 被顶掉）；
5. B 全程不受 A 刷新影响（内存态隔离），B 状态截图 `r2_clientB_state.png`（B 停在 bodyxss，pill/地址栏/侧栏一致）。

- 结论：单客户端设计下这是「多开页面共享同一会话」的自然结果；与 patch 文档 D5/D3 判断一致（写权归一或拒绝第二客户端）。事件单播问题（D3：事件只推 `_main_cvw`）在无头下不可观测（无 webview 事件泵），标注桌面端不可达。

## 五、D1 补丁预演（sendBeacon 链路实测，给 patch-round-1 D1 的可行性结论）

实测矩阵（页面 origin=127.0.0.1:18765；echo 服务器 19001 记录实际 Content-Type；服务端日志验证送达与解析）：

| 形态 | sendBeacon 返回 | 实际 Content-Type（echo 实测） | 服务端送达/解析 |
|---|---|---|---|
| `JSON.stringify` 字符串体（**D1 提案原样**） | true | **`text/plain;charset=UTF-8`**，body=`{"act":"dispose_all"}` | ✅ 同源送达，2 次 POST /api/web/tabs 均 HTTP 200 |
| `Blob(…,{type:'application/json'})` | true（同源）；**跨源 false 效果** | 同源到达；跨源未到达（application/json 触发 CORS 预检，echo 无 OPTIONS → 被拦） | ✅ 同源送达（200） |
| `URLSearchParams` | true | `application/x-www-form-urlencoded;charset=UTF-8` | —（对照） |
| **解析证明**：beacon → `/api/web/fetch_text` 且 body 含合法 url | true | text/plain | ✅ **HTTP 200**（解析失败本应 400「仅支持 http(s) 链接」）——beacon 请求体被 `get_json(force=True, silent=True)` 成功解析 |

**D1 可行性结论**：
1. ✅ 链路可通：`navigator.sendBeacon('/api/web/tabs', JSON.stringify({act:'dispose_all'}))` 在页面卸载场景语义成立，请求必达（同源）、body 必被解析（force=True 不挑 Content-Type）、origin 守卫不拦同源 beacon。
2. ✅ Content-Type 无障碍：字符串体是 `text/plain`，但 `force=True` 使其照常解析——D1 无需改请求头。
3. ⚠ 响应断言修正：现无 `dispose_all` act，但**无头实例在 act 分发前就被「控件管理器未装配」短路**（`{"ok":false,"err":"控件管理器未装配"}` 200）——任务书预期的 `{"ok":false,"err":"bad act"}` 只能在桌面端（manager 已装配）观察到，黑盒不可达。D1 落地后应在桌面端补验一次 dispose_all 真实回收。
4. ⚠ D1 注意项（patch 文档已提示，本轮实测佐证）：`dispose_all`+`reset_session` 在多客户端下互杀（见 §四）——落地时至少要接受「刷新即清空其他客户端」的单客户端语义。

## 六、黑盒不可达清单（R2 更新）

1. 桌面端 WebView2 真实行为（同 R1）：呼吸态、休眠/唤醒、target=_blank、加载失败层、`javascript:` Navigate 真实语义（A10 取舍点）。
2. `/api/web/tabs` 的 act 分发与 tab-id 校验（无头被「控件管理器未装配」短路）——**dispose_all 的 "bad act" 响应同样不可达**。
3. 事件单播（D3）观察：无头无事件泵，第二客户端「停在什么状态」只能给出 localStorage/内存态（已截图）。
4. userinfo 绕过的内因（`getaddrinfo failed` 的确切解析路径）——行为已记录（未绕过），根因需源码层确认。
5. 真实鼠标/键盘点击（IAB 工具通道，t=0 即失效）。

## 七、下一轮复用

- 隔离实例（已含端口修正的完整运行树，约 3.5G）：
  ```
  cd C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2
  USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server
  ```
  （端口 18765；与真实实例零冲突；数据目录同 R1 临时区）
- 靶标：18999（静态页：plain/special/long/links/xss-title/bodyxss/data.json/img.png/note.txt/big.html）、19001（重定向 +beacon echo，脚本 `$TMP/audit-bb-r2/redirect_server.py`）。
- 服务端日志：`$TMP/audit-bb-r2/server.log`；beacon 回显：`$TMP/audit-bb-r2/beacon_log.txt`。
