# 第 1 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能

- 轮次：round 1（黑盒 GUI + HTTP API 对抗）
- 日期：2026-11-12 ~ 11-13
- 测试对象：v4.1.0-a556（d9c8886），网页 tab 面板全链路
- 方法：ZCode 内嵌浏览器（IAB）GUI 黑盒 + curl 直打 HTTP API；全程未修改任何代码
- 证据目录（绝对路径，仓库外）：`C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r1\screens\`

---

## 0. 环境准备记录（与测试区分）

1. 隔离实例：临时目录建 `audit-bb-home/.serialconsole_pro/config.json`（`data_dir` 指向临时区），以 `USERPROFILE=<临时区>` 启动无头实例。**全程 `git status` 保持 clean，仓库 data 目录零接触**（隔离实例数据全部落在临时目录）。
2. 启动命令修正：任务书给的 `python src/server.py` 会 `ModuleNotFoundError: No module named 'src'`（server.py 以 `src.` 前缀导入）。**正确命令为 `python -m src.server`**（仓库根执行）。
3. 本地靶页服务器：`$TMP/audit-bb-r1/testsite`（端口 18999），提供 XSS/特殊字符/超长标题靶页，未放入仓库。
4. ⚠ **端口发现**：真实实例（pid 4068）除 56278 外**同时持有 8765**（netstat 证实；8765 上无 `/api/status` 路由，返回 `not found`）。隔离实例启动后实测全部流量命中隔离实例（响应均含隔离实例特征），真实实例未受影响；隔离实例停止后 8765 归还真实实例。机制上疑似 Windows SO_REUSEADDR 双绑定/重绑定，见 B5。
5. ⚠ **工具通道异常（影响测试方式，非应用缺陷）**：页面加载约 1 分钟后，IAB 的可信鼠标事件与键盘事件停止送达页面（4 种点击方式全部无效；判别实验：合成 click 能正常触发 handler，证明应用 handler 完好）。经任务书授权，改用「浏览器 JS 驱动前端事件」作为替代通道（与应用内部 `el.click()` 同款），文本输入仍走真实 `fill()`。因此下述结论均基于「事件送达后的应用逻辑」，真实鼠标路径已单独标注。

---

## 一、确凿问题

### B1【P2】网页面板跨 tab 串导航：地址栏回车导航的是「激活 tab」而非「输入框所属 tab」

- 复现步骤：
  1. 打开两个网页 tab（A=web:1，B=web:3），B 处于激活态；
  2. 对 A 的面板内地址栏派发回车（输入 `javascript:alert(1)`；真实用户路径=点击 A 地址栏输入，等效）；
  3. 观察导航落点。
- 实际：**B（激活 tab）被导航**——B 的导航栈推入 `http://javascript:alert(1)`、B 的地址栏被改写、B 的胶囊标题变更；A 完全不动，A 的输入框保持原始串。
- 预期：回车=「当前输入框所属 tab」导航（代码注释自述语义）。
- 根因（行为+代码双重证实）：`_webNavigate()`（web-panel.js:394-396）取 `_webCur()`（激活连接）而非事件所属连接；keydown handler 对每个 tab 独立绑定但导航目标错位。
- 触达性说明：纯 GUI 下「不可见面板不可输入」，自然触发受限；但自动化/焦点竞态可触发，且违背面板自身声明的语义。
- 证据：`t1_initial_one_tab.png`（基线）；DOM 证据：web:1 `_nav.stack` 不变、web:3 `_nav.stack` 增加 `http://javascript:alert(1)`；`jsall/web-panel.js` 394 行（服务端拉取的公开静态资源）。

### B2【P2】发给 Claude：harness 后端不可用（503）时发送静默失败，消息丢失且无任何提示

- 复现步骤：
  1. 顶栏 Claude 打开 Claude 对话（无 worker 会话）；
  2. 网页面板「发给 Claude」正常填入正文（该步工作正常）；
  3. 点击发送按钮。
- 实际：前端发出 `POST /api/harness/connect` → 后端 503 `{"err":"Claude 后端未就绪（worker 未启动）","ok":false}`（响应形态本身优雅）；但 **UI 无任何反馈**：无气泡、无错误横幅、无 toast，输入框已被清空——用户输入静默丢失。
- 预期：失败时保留输入并给出可见错误提示（应用自身有 showBanner 机制但此路径未用）。
- 证据：`t3_send_clicked.png`（发送后无变化）；server.log `POST /api/harness/connect HTTP/1.1 503`；curl 复核响应体原文见上。
- 备注：无会话时的前置拦截是优雅的（红色横幅「先打开 Claude 会话（顶栏 Claude 按钮）再取页」，`t3_send_to_claude.png`）——只有发送链路静默。

### B3【P3】多客户端共享 `web-session`：last-write-wins 互踩，双方恢复出相同状态

- 复现步骤：同一隔离实例开 2 个浏览器页（A、B）→ A 导航到 long.html、B 导航到 special.html → 双方各自刷新页面 → 各自顶栏空回车恢复会话。
- 实际：共享 localStorage `web-session` 被 B 后写覆盖（`{"stack":[...special...],"idx":1}`）；**刷新后 A、B 恢复出完全相同的状态**（都是 special.html），A 的导航历史丢失。
- 预期：多客户端场景至少不互相覆盖（或按客户端隔离）。
- 影响评估：桌面端单实例互斥锁下不可达，浏览器多页场景可达；严重级 P3。
- 证据：`web-session` 键值前后对照（上文记录）。

### B4【P3】地址栏 URL 规范化不感知协议：`javascript:` / `file:` / 裸 `http://` 被无脑补 `http://` 前缀入历史栈

- 复现步骤：面板内地址栏分别输入并回车：`javascript:alert(1)`、`file:///C:/Windows/win.ini`、`http://`。
- 实际：三者均被 `_webNormUrl()`（web-panel.js:80-85）原样接受或补前缀（`http://javascript:alert(1)`、`http://file:///C:/Windows/win.ini`、`http://`）并推入导航栈、写进胶囊标题；后端对垃圾 URL 照单全收（200）。
- 预期：浏览器地址栏语义应识别协议（至少拦截/提示 javascript:、file: 等非 http(s) 目标）。
- 影响评估：无头下仅产生垃圾导航项；桌面 WebView2 对 `javascript:` 的 Navigate 通常是拒绝的（黑盒不可证实，标注存疑），故 XSS 风险低，主要是语义缺陷。
- 证据：上文 T1.6 记录（nav stack、pill label 原文）。

### B5【P3·存疑】8765 端口与真实实例冲突（环境级发现）

- 现象：真实实例（4068）持有 8765（8765 上 `GET /api/status` → `not found`，56278 上正常返回真实数据目录）；隔离实例启动后 8765 流量全部由隔离实例承接（响应特征证实），隔离实例停止后 8765 归还真实实例。
- 疑点：无法在黑盒下确定是「双绑定并存（SO_REUSEADDR，后绑者收流）」还是「真实实例周期性重试绑定」，两者对下一轮测试的操作含义不同。
- 风险：若真实实例的 WebView2 网页 tab 依赖 8765 上的自身服务，测试窗口内其请求会被隔离实例截走。
- 建议（给下一轮）：隔离实例加端口参数（`server.py:3599` 硬编码 8765）或测试前先确认 8765 空闲；报告复用命令见文末。

### B6【P3】HTTP 层一致性小问题

- 错误方法（`GET /api/web/tabs`）返回 Flask 默认 **HTML 404 页**而非 JSON（其余全端点均 JSON 优雅报错）。
- Origin 守卫只拦「Origin 存在且不匹配」（403），**无 Origin 的请求直接放行**进业务逻辑（curl/脚本本就拦不住，属设计取舍，记录备查）。
- 证据：curl 原文（见测试记录）。

---

## 二、已测未复现（防重复测试清单）

| # | 测试点 | 结果 |
|---|--------|------|
| 1 | 网页 tab 多开（a554 去单例化）：同面板 2 个 tab 并存、独立导航栈 | ✅ 未复现 |
| 2 | tab 切换（胶囊点击）、关闭激活 tab 自动切余、关闭最后一个回到干净空态 | ✅ 未复现 |
| 3 | 面板内地址栏：Ctrl+回车新开、空回车无副作用、带空格/换行输入 trim 正确 | ✅ 未复现 |
| 4 | 顶栏回车开新 tab（a556 语义）与空回车恢复会话 | ✅ 未复现（合成事件验证） |
| 5 | 收藏夹全链路：★收藏（服务端取真实 title）、菜单展示、点击收藏项新开 tab、✕ 删除、重复收藏=取消/重加（URL 去重不重复）、新收藏置顶 | ✅ 未复现 |
| 6 | 收藏持久化：重启隔离实例后 3 条收藏还在 | ✅ 未复现 |
| 7 | 特殊字符/对抗标题：`<script>`、`<img onerror>`、引号、emoji、1200 字超长标题——收藏菜单**全部纯文本渲染**（childElementCount=0，无 alert 弹窗），超长 CSS 截断不破布局 | ✅ 未复现 |
| 8 | 阅读模式 XSS：body 注入 script/img/伪链接 → 渲染层 0 script 0 img，纯文本 | ✅ 未复现 |
| 9 | 会话恢复：跨重启恢复上次栈顶（含遗留 b.example 会话） | ✅ 未复现 |
| 10 | 右键菜单（tab 胶囊）：「固定标签页/关闭」菜单与固定动作（pill 变 pinned） | ✅ 未复现 |
| 11 | 快速暴力切换 20 次：active 状态一致无错乱 | ✅ 未复现 |
| 12 | 窗口 resize（900x500）：布局自适应、无横向溢出、无重叠错位 | ✅ 未复现 |
| 13 | 设置联动：AI 网页操作（CDP）开关 开→配置 true→关→false→重开面板回显一致 | ✅ 未复现 |
| 14 | HTTP API 对抗（详单）：`/api/web/tabs` × {空 body、坏 JSON、未知 act、1MB title/url、顶层 JSON 数组、顶层字符串、id 负数/超大/浮点/字符串/null/对象、url=null、layout 负坐标}、50 并发重复 create | ✅ 全部优雅（JSON 错误、无 500、服务存活）；数组体 400+明确文案 |
| 15 | `/api/web/fetch_text` × {缺 url、错类型、javascript:/file: 拒绝} | ✅ 400 优雅拒绝（协议白名单有效） |
| 16 | `/api/open_url` × {缺 url、javascript:、file:、错类型} | ✅ 400 优雅拒绝 |
| 17 | 不可达地址 fetch_text | ✅ 优雅报错（`取页失败：<urlopen error timed out>`） |

---

## 三、黑盒不可达清单（含原因）

1. **WebView2 原生 tab 真实行为**（desktop-only，无头无 webview）：前进/后退/刷新的实际效果（无头下按钮走 `_webCtl` 静默无效，属可接受的降级但记录在案）、加载中呼吸态（a553）、后台休眠/唤醒全链路（a556，需 10 分钟后台窗口）、target=_blank 链接点击链路（浏览器模式内容区为空宿主，页面链接不可点）、加载失败提示层（无 webview 事件不触发——无头下导航垃圾 URL 亦无任何错误提示，见 `t7_restart_persistence.png` 的绿灯）。
2. **`/api/web/tabs` 的 tab-id 校验语义**：无头下所有动作短路于「控件管理器未装配」，id 校验逻辑覆盖不到。
3. **侧栏「最近」历史**：网页导航不入最近列表（列表为空），历史标题 XSS 面在此不可达（收藏标题 XSS 面已覆盖并通过）。
4. **真实用户鼠标点击路径**：IAB 工具通道失效（见 0.5），已按任务书授权改合成驱动；建议下一轮换环境复核一次「纯真实点击」冒烟。
5. **桌面端单实例相关**：按铁律未触碰（互斥锁行为未测）。

---

## 四、测试证据与驱动方式声明

- 截图证据（已逐张人工查验）：`C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r1\screens\` 下 `t0_initial_dialog.png`、`t1_*.png`、`t2_star_banner.png`、`t3_*.png`、`t4_settings_panel.png`、`t7_*.png`、`t8_*.png`、`t9_*.png`。
- 控制台日志：IAB 未提供只读 console 通道（tab capabilities 为空），以页面可见错误表现 + 服务端日志替代取证。
- 驱动方式：文本输入=真实 `fill()`；事件触发=合成事件（任务书授权的 DevTools 等价驱动）；判别实验证明应用 handler 完好（见 0.5）。
- 服务端原始日志：`$TMP/audit-bb-r1/server.log`、`server2.log`。

## 五、下一轮复用

- 隔离实例启动命令（仓库根执行）：
  ```
  USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server
  ```
  （前置：`$TMP/audit-bb-home/.serialconsole_pro/config.json` 已存在并指向临时数据目录；启动前建议确认 8765 未被真实实例占用，见 B5）
- 本地靶页服务器：`python -m http.server 18999 --bind 127.0.0.1`（目录 `$TMP/audit-bb-r1/testsite`，含 xss-title/special/long/links/bodyxss/plain 靶页）。
