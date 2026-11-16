# 红队攻击审计 · A2 复验轮报告（密码域——攻破自己的修复）

- **审计员**：红队密码域攻击者 A（复验轮 A2）
- **日期**：2026-11-16
- **对象**：HEAD `e564f24`（v4.1.0-a584）——上轮报告 RA1-RA11 的修复 diff `480c07d..HEAD`（src/web_tabs.py +172、src/server.py、web/js/web-panel.js、tests）
- **方法**：任务铁律「每条都要真探针」。三套探针全部真运行：① `src.server.app` test_client 33 断言（守卫矩阵 + 全链行为，假 Chromium 库走真 v10 AES-GCM + 真 DPAPI 包裹密钥）；② 活 Flask 服务器（werkzeug 真实 HTTP 栈）+ 原始套接字 5 形态（重复头/obs-fold/HTTP-1.0/kill-shot/正控）；③ **真浏览器**（ZCode 内建 Chromium）：跨端口真源攻击页 4 通道实测 + 同源 UI 正控。pytest 全量回归。git 只读，仓库零改动（探针落 `%TEMP%\ra2_scripts` + `%TEMP%\ra2_art`，pending 文件运行时重定向出仓）
- **工作树注意**：`M src/harness/*`、`M web/js/harness/chatctl.js` 为他队在途改动，与密码链无交集；探针 import 的模块与 HEAD 密码链零差异

---

## 一、终判

**上轮 11 条：修复确认 4 / 半修 3 / 仍可攻破（含修复无效）3 / 未修维持 2。新发现 7 条：高 1 / 中 2 / 低 4，其中 1 条为修复引入的回归（畸形库 pw_list 从优雅降级退化为裸 500）。**

守卫修复的真实边界（本轮最重要结论）：**`_pw_guard` 的全部输入（Origin、Host）对本机进程都是可自指伪造的**——它只防得住「浏览器跨站」（RA2 通道，已实测堵死），防不住 RA1 的本体威胁「本机任意进程两次调用导出全库明文」。修复注释声称「本机其他进程……全部 403」不成立：kill-shot 实测 **`Host: localhost` + `Origin: http://localhost` 两行头即可取明文，连端口号都不需要知道**；甚至 HTTP/1.0 完全不带 Host 头也放行（`request.host` 回落 SERVER_NAME）。

| 上轮 | 判定 | 一句话 |
|---|---|---|
| RA1 高 | **仍可攻破 → RA12** | 双自指头绕过 pw_guard，不知端口取全库明文（原始套接字 kill-shot 实测） |
| RA2 中 | **修复确认** | 真浏览器 4 通道（beacon/text-plain 表单/no-cors fetch/data:iframe）全 403、库零副作用 |
| RA3 中 | **半修 → RA17** | happy path 副本即删✓；畸形库两条路径副本残留+句柄锁死；空目录累积 |
| RA4 中 | **仍可攻破 → RA13** | 后端精确删能力已具备，但 web-panel.js:1187 的 pw_del **不传 user**——UI 一次点击照旧删光同站全部账号 |
| RA5 中 | **修复确认** | 持锁+原子替换：双线程×10 并发 20/20 不丢（上轮丢 14/1/10）、无 .tmp 残留 |
| RA6 低 | **半修 → RA16** | defer 重建+WARN✓；`_pw_del_flush` 损坏路径仍静默 return（退出时删除蒸发、文件永留、零告警） |
| RA7 低 | **半修+回归 → RA17** | reveal 500→200 归一 err✓；但 `_pw_entries` 的 except 分支被删 → **畸形库 pw_list 裸 500 HTML（修复引入回归）** |
| RA8 低 | **修复确认** | `ORDER BY date_created DESC` 实测取最新（100/200 → NEW-pw） |
| RA9 低 | **未修维持** | reveal 仍无二次认证、无审计（修复 diff 零涉及） |
| RA10 低 | **未修维持** | `_webPwMgr` 的 `api()` 仍绕过 `__webUiIsOwner` 单点门控（web-panel.js:1147 vs :401） |
| RA11 低 | **修复无效 → RA14** | `shutdown()` 的 `if _tabs is None: return` 在前，`else: _pw_del_flush()` 是**死代码**——实测 _tabs=None 时挂起删除不执行 |

**新发现一览**：

| 级别 | 编号 | 一句话 |
|---|---|---|
| 高 | RA12 | pw_guard 可被 Host/Origin 双自指（不知端口）与 HTTP/1.0 无 Host 旁路——RA1 本体威胁未修，守卫只具浏览器跨站防御价值 |
| 中 | RA13 | RA4 修复未接线：UI pw_del 无 user 字段 → None=全删语义仍被 UI 正常路径触发；另 user="" 时 200 ok 但 0 行命中（静默无操作陷阱） |
| 中 | RA14 | RA11 修复为死代码：早退在前，else 分支不可达，env 失败会话挂起删除永不 flush |
| 中 | RA15 | flush 失败时**假成功销毁 pending**：DB 仍锁或库缺失时照删文件+INFO「N 条已删」假日志+行未删；库缺失时还在 EBWebView 路径造出 0 字节假 Login Data |
| 低 | RA16 | RA6 半修：flush 损坏路径无重建无 WARN 不清理（defer 侧已修） |
| 低 | RA17 | 副本残留三态（reveal except 不删不关 / list finally 被锁死 / 空目录累积）+ **回归：pw_list 畸形库裸 500** |
| 低 | RA18 | `_pw_del_defer` 即时路径连接未 finally-close——失败后句柄滞留锁住真实库（实测 PermissionError，需 GC 才释放） |

---

## 二、逐条回打（RA1 起）

### RA1【高→仍可攻破】Origin 强一致校验——本机进程自指旁路（RA12）

修复形态：`web_tabs.py` register() 内 `_pw_guard()`：`org = (headers["Origin"]).strip().rstrip("/")`，要求 `org == "http://" + request.host`，否则 403。三个路由（pw_list/pw_reveal/pw_del）全部前置。

**任务四个子项实测**：

| 形态 | 结果 | 证据 |
|---|---|---|
| ① 尾斜杠 `Origin: http://127.0.0.1:8765/` | 放行（rstrip 设计如此，无害） | test_client G2=200 |
| ① 端口省略 `http://127.0.0.1` / `http://localhost` | 403（RA2 的无端口豁免在 pw 路由被堵） | G3/G3b=403 |
| ① 大小写 | scheme 大写 `HTTP://` → 403；**Host/Origin 一致大写自指** → 与小写同理放行（字符串精确比较，一致即过） | G9=403；G10/G11 |
| ② header 注入（Origin 值内 \r\n） | 浏览器 fetch API 禁止头值含 CRLF（构造即抛错）；HTTP 层折叠注入 obs-fold（`Origin: http://evil\r\n http://127.0.0.1:8800`）→ 头值合并为含空格串 ≠ 期望 → 403 | 原始套接字 R2=403 |
| ③ 重复 Origin 头 | werkzeug serving 合并为 `http://evil,http://127.0.0.1:8800` → ≠ → 403 | 原始套接字 R1=403 `{"err":"forbidden origin"}` |
| ④ WebView2 UI 侧 fetch 带什么 Origin——**修后 UI 还能用吗（真破坏性检查）** | **能用**。真浏览器打开 `http://127.0.0.1:8800/`（与 main.py:1222 pywebview 加载形态同源同构），页面上下文 fetch pw_list → `200 {"items":[alice,bob]}`；pw_reveal → `200 {"pw":"S3cret-Alice-9"}`（v10+DPAPI 全链通）。同源 POST fetch 自带 `Origin: http://127.0.0.1:8800` == request.host → 放行；外部浏览器走 `http://localhost:8765` 亦自洽 | 探针③正控 |

**攻破（RA12 本体）**——守卫的语义是「Origin 必须自指到 Host」，而本机进程对两者都完全可控：

- **kill-shot（连端口都不用知道）**：原始套接字发 `Host: localhost` + `Origin: http://localhost` + pw_reveal → **HTTP 200 `{"ok":true,"pw":"S3cret-Alice-9"}`**。全局守卫：host `localhost` 过 `_LOCAL_HOST_RE`、origin `http://localhost` 过 `_LOCAL_ORIGIN_RE` 无端口豁免；pw_guard：`http://localhost == "http://" + "localhost"` → 放行。上轮 RA1 的攻击成本从「两次 HTTP 调用」变成「两次 HTTP 调用+两行头」，威胁实质未变。
- **HTTP/1.0 无 Host 变体**：`POST HTTP/1.0` + 仅 `Origin: http://127.0.0.1:8800` → `request.host` 回落 SERVER_NAME:SERVER_PORT（即真实绑定值）→ 相等 → **200 全密码列表**。此变体需知端口，但证明守卫连「Host 必须到场」都不要求。
- test_client 复证 G10/G11：Host=Origin=localhost（无端口）→ pw_list 200 全 items。

**结论**：无凭据的 Origin 一致性校验在结构上不可能防本机进程。修复的真实价值=堵浏览器跨站（RA2 通道），对上轮 RA1 定级的威胁（本机任意进程/跨 OS 会话）为零防御。若要真修 RA1：启动期随机 token 经页面注入交 UI（请求头携带），或 pw_* 改本地命名管道。

### RA2【中→修复确认】盲 CSRF 通道全堵

任务子项实测（真 Chromium，攻击源 `http://127.0.0.1:8801`（真跨端口 Origin）+ data: iframe（null origin），目标 8800）：

| 通道 | 结果 |
|---|---|
| `navigator.sendBeacon` pw_del alice（text/plain 简单请求、无预检、响应不可读） | 403；alice 行完好 |
| 跨站表单 POST `enctype=text/plain` pw_del bob（顶层导航） | 403；表单目标页直接显示 `{"err":"forbidden origin","ok":false}`；bob 行完好 |
| fetch mode:no-cors（pw_reveal bob / pw_list） | 403；无副作用 |
| data: iframe（null Origin）fetch pw_del | 403；无副作用 |
| 服务端日志 | 4 条 POST 全 403（werkzeug 日志取证）；DB 复查 alice+bob 原样、pending 文件不存在 |

补充矩阵（test_client + 原始套接字）：无-Origin（MCP/urllib 豁免通道）→ pw 路由 403（G5）；异端口 Origin → 403（G4/R1 对照组）；`Origin: null` → 403（G7）；https scheme → 403（G6）；evil 后缀域名 → 403（G8）。全仓 grep 确认 pw 三路由无其他服务端调用方（仅 web-panel.js UI fetch）——修复不破坏任何内部无-Origin 通道。**RA2 修复确认，通道收口干净。**

### RA3【中→半修】副本即删——happy path 成立，异常路径三态残留（RA17）

- happy path：合法库 pw_list×3 → 目录差分：3 个新 mkdtemp 目录均**无 LD.db 残留**（副本文件即删✓）——但目录本身逐次累积（空目录，无敏感数据，清洁性缺口）。
- **畸形库 pw_reveal**（RA3c）：`_pwdb_copy` 成功→connect 成功（懒打开）→execute 抛 DatabaseError→except 直接 return——**该路径既不 `os.remove(db)` 也不 `con.close()`**。实测：副本残留于新 mkdtemp 目录 + `os.remove` 抛 PermissionError（句柄被泄漏连接锁死）。
- **畸形库 pw_list**（RA3d）：`_pw_entries` finally 里 remove——但 execute 抛出时连接同样未关（close 在 try 内 execute 之后）→ remove 被锁死吞掉 → 实测副本残留 + 句柄 LOCKED。
- 即时路径连带（RA18）：`_pw_del_defer` 即时 DELETE 失败（库被 Chromium 锁）→ except pass 无 finally close → 实测真实库文件句柄滞留（探针须 gc.collect() 才能删除文件）。长会话中反复失败的 pw_del 持续持有 EBWebView Login Data 句柄。

### RA4【中→仍可攻破】按 origin+user 精确删——后端已修，UI 未接线（RA13）

- 后端能力确认：`{"act":"pw_del","origin":O,"user":"a"}` → 只删 a 行✓（RA4c）；flush 对混排旧串+新二元组兼容✓（旧串全删/二元组精确删，RA4e）；`user=None` 仍=全删（注释称兼容层）。
- **UI 载荷实测（RA13 本体）**：web-panel.js:1187 逐字形态 `api({ act: 'pw_del', origin: it.origin })`——**无 user 字段** → 后端 `d.get("user", None)` → None → `DELETE WHERE origin_url=?`。实测 UI 载荷：同站 u1+u2 两行一次删光（`left=[('https://keep.example/', 'k1')]`）——与上轮 RA4 场景完全一致。web_tabs.py 修复注释「空 user 显式标记（None=全部，**UI 不再使用**）」与事实相反：UI 从未更新。
- 陷阱形态：`user:""` → `DELETE ... AND username_value=''` → 0 行命中但返回 `{"ok":true,"immediate":true}` → UI 显示「已删除」实际什么都没删。
- **修复要生效只需一行**：web-panel.js:1187 加 `user: it.user`（列表项已持有 user 字段）；建议同时把服务端 user 缺省语义从 None=全删改为 400。

### RA5【中→修复确认】并发挂起

持库锁（BEGIN EXCLUSIVE）双线程×10 pw_del 走挂起路径 → pending 文件 20/20 条目、无丢失（上轮 20 请求丢 14/1/10）；原子替换后无 `.tmp` 残留。`_pw_del_lock` + tmp+`os.replace` 修复确认。20 个并发请求全部经由 `_pw_guard`（多线程下 request 代理无串扰，顺带覆盖新攻击面①）。

### RA6【低→半修】损坏告警——defer 侧修了，flush 侧没修（RA16）

- 已修侧：损坏 pending + pw_del → WARN `pw_pending_del.json 损坏，已重建` + 文件重建（实测✓）。注意语义：重建=**旧挂起删除记录全部丢弃**（含合法记录），用户侧仅日志 WARN，UI 无提示——「重建丢数据」未向用户明示，只是从静默变成半静默。
- 「每次 scan 都会 WARN 刷屏吗」——pending 文件只有两个读取点：pw_del（defer）与退出（flush）。defer 首次读取即重建，后续不再 WARN——**无刷屏问题**。
- **未修侧（RA16）**：`_pw_del_flush` 的损坏路径原样未动：`json.load` 失败 → `except Exception: return`——无 WARN、不重建、不隔离 `.bad`、文件永留。实测：写入 `{"broken json no close` → flush 后文件原样、密码行原样、零日志。上轮 RA6 的原始场景（文件损坏 → 用户不再触发 pw_del → 退出时静默空转）**完整存活**。且 defer 侧的重建语义使局面更糟：若 pw_del 触发过重建（丢弃旧记录只留新一条），而那条新记录因退出时 flush 遇到「RA15 的锁库假成功」又被销毁——删除承诺多层蒸发。

### RA7【低→半修+回归】

- reveal 侧确认修复：畸形库 pw_reveal → `200 {"ok":false,"err":"库读取失败：DatabaseError('file is not a database')"}`，不再 500 HTML（上轮 RA7 主体）。
- **回归（RA17d，修复引入）**：`_pw_entries` 的修复把 `except Exception: return []` 整个删掉换成裸 `finally`——异常不再被吞。实测畸形库 pw_list：**未捕获 `sqlite3.DatabaseError: file is not a database` 直穿 Flask → 500 HTML**（上轮该路由是优雅 `items:[]`）。上轮 RA7 的 pw_list 半边被本轮修复重新打开。
- 连接卫生：两路由的 close 仍都在 try 内 execute 之后（except 路径泄漏，见 RA3c/RA3d/RA18）。

### RA8【低→修复确认】

假库两条 `alice@example.com`（date_created=100/200）→ reveal 返回 `NEW-pw`（date 200 那条）——`ORDER BY date_created DESC LIMIT 1` 生效。✓

### RA9【低→未修维持】

修复 diff 对 reveal 无二次认证/审计零涉及（无 re-auth、无 eventlog、无计数）。维持上轮低危判定。补一句本轮观察：结合 RA12，「任何本机进程两行头批量拉明文、无速率限制、无审计」的现状与上轮完全一致。

### RA10【低→未修维持】

`_webCtl` 的 `__webUiIsOwner` 门控在位（web-panel.js:401-403），`_webPwMgr` 的 `api()`（:1147-1150）仍直连 fetch 未走门控。维持上轮低危一致性缺口判定。

### RA11【低→修复无效】flush 调用链（RA14）

真机时序调用链（a584 修后）：`main._do_real_cleanup`（main.py:1250-1251 `from src import web_tabs as _wt; _wt.shutdown()`，在 taskkill 树杀前）→ `web_tabs.shutdown()` → `if _tabs is None: return` ← **早退在此** → 否则 `_tabs.flush_on_exit(grace_ms)` → 尾部 `_pw_del_flush()`（web_tabs.py:1014-1016，浏览器 Dispose+1200ms grace 之后）。

**修复死代码实测**：`shutdown()` 修复在 try 内加了 `else: _pw_del_flush()`，但 try 前面的 `if _tabs is None: return` 原样保留——else 分支**结构性不可达**。探针：`_tabs=None` + pending 文件含 `[origin,user]` + 库解锁 → `shutdown(grace_ms=1)` → **pending 文件原样、密码行未删、零日志**。对照组：`_tabs` 置非 None 桩 → flush 链正常执行、文件清掉（RA11c ✓）。即：WebView2 env 初始化失败的会话里，挂起删除永不执行——上轮 RA11 的场景原样存活，修复声明无效。

---

## 三、新发现明细

### RA12【高】pw_guard 对本机进程零防御——RA1 修复声明与实测不符

见 RA1 节。三种旁路形态（双自指无端口 / 双自指带端口 / HTTP-1.0 无 Host）+ 真实明文返回。修复注释「本机其他进程（两次调用导出全库明文的攻击）……全部 403」**不成立**。定级沿用上轮 RA1【高】。建议：pw_* 引入启动期随机 token（页面注入交 UI），Origin 校验保留但只作为浏览器跨站层；或改本地命名管道/Unix socket 摆脱 HTTP 头可伪造性。

### RA13【中】RA4 修复未接线：UI 删除仍按 origin 全删

见 RA4 节。一行修复：web-panel.js:1187 加 `user: it.user`。另：user="" 静默无操作陷阱（服务端应 400 或归一）。

### RA14【中→修复无效】RA11 死代码

见 RA11 节。修复写法与意图相反：`if _tabs is None: return` 应改为 `if _tabs is None: _pw_del_flush(); return`。

### RA15【中·新】flush 失败路径假成功销毁 pending + 造假库文件

`_pw_del_flush` 的结构是「循环内 per-item except pass → commit → os.remove(p) → INFO『N 条已删』」——**循环全败也照样走到 os.remove**。两个实测：

- **库仍被锁**（真机窗口：flush_on_exit 的 1200ms grace 后 Chromium 尚未释放；或本会话外还有进程持有该 profile）：pending `[[victim,u]]` + BEGIN EXCLUSIVE → flush → execute 全部 OperationalError 被吞 → commit 空 → **pending 文件被删** + INFO 日志 **`pw_del_flush: 1 条已删`** → 行原样。用户的「已标记删除——完全退出后生效」承诺静默蒸发，且日志给出**假成功审计记录**（比 RA6 静默更糟：有记录，记录是假的）。
- **库文件不存在**（env 从未建 tab / profile 被清）：flush 照样 `sqlite3.connect(_pwdb_path())` —— sqlite 在 **EBWebView/Default/ 下创建 0 字节空 Login Data**（假库文件污染 WebView2 profile 路径）+ pending 被删 + INFO 假日志。
- 修复方向：connect 后先探测 `logins` 表存在性/可写性；按 execute 成功行数决定是否 remove；全败时保留文件+WARN。

### RA16【低】RA6 半修（flush 损坏路径）

见 RA6 节。`_pw_del_flush` 的 `except Exception: return` 未获得 defer 侧同款重建+WARN+隔离。

### RA17【低】副本残留三态 + pw_list 500 回归（修复引入）

见 RA3/RA7 节。要点：(a) reveal except 路径不删副本不关连接；(b) list finally 的 remove 被泄漏句柄锁死；(c) 空目录累积；(d) **回归**：`_pw_entries` 修复误删了 `except Exception: return []` 优雅分支 → 畸形库 pw_list 裸 500 HTML。修法：三段式 try/except/finally——except 归一 `{"ok":false,"err":"密码库不可读"}`、finally 统一 close+remove（把 close 挪进 finally 即同时解 (a)(b)(e) 连接卫生）。

### RA18【低】defer 即时路径连接未 finally-close

见 RA3 末条。`_pw_del_defer` 的即时 DELETE 失败后连接靠 GC 回收，期间真实库文件句柄滞留（Windows 实测 PermissionError）。影响小（sqlite 并发打开不受碍），但与 RA17 同根：连接生命周期管理缺失。

---

## 四、攻击未成功的面（复验轮闭合清单）

| 任务面 | 结论 | 实证 |
|---|---|---|
| sendBeacon 无-Origin/跨站通道（data:/file:/null origin） | **堵死**。真浏览器 beacon → 403，行完好 | 探针③ |
| form POST enctype=text/plain 跨站表单 | **堵死**。顶层导航表单 → 响应页可见 `forbidden origin` | 探针③ |
| Origin 重复头 / obs-fold 折叠注入 / 头内 CRLF | **堵死**（合并值≠期望；fetch API 禁 CRLF） | 原始套接字 R1/R2 |
| 无端口/异端口/https/null/大写 scheme Origin | 全 403 | G3-G7/R3 对照 |
| **修后 UI 误伤** | **无误伤**：真 UI 页同源 fetch pw_list/pw_reveal 全通，v10+DPAPI 解密链完好 | 探针③正控 |
| _pw_guard 多线程/test_client 语义 | 无串扰（RA5 并发 20 请求经守卫）；闭包内重定义无碍 | 探针① RA5 |
| WebMessage 桥残留/旧 fetch 版注入脚本 | src/ grep `WebMessageReceived|PostWebMessage` 0 命中；即便长驻进程存在旧注入，其 fetch 携带页面源 Origin → 403（拒绝式降级，不放大） | grep + 守卫语义 |
| 修复 diff 新字符串拼接 | `console.warn(%s) % json.dumps('[web-tabs] suspend: '+diag)` 全量转义（比旧写法更安全）；「库读取失败：%r」无注入面；epoch/_closing/_cancel 为 D 域状态，pw 路由不读 | diff 审 + grep |
| pw_del user 非字符串（dict/int 经 JSON） | flush 绑定参数抛 → per-item pass → 行存活，无崩溃 | 代码路径 + RA4e 语义 |
| pytest 回归 | **287 passed, 10 subtests passed**（28.9s，含 a583 钉测与 RA1 Origin 钉测更新） | 本轮全量 |

**边界观察**：`user=None=全删` 的兼容语义本身就是持续暴露面——任何能过守卫的主体（含 RA12 旁路）不发 user 即全删。RA4 修复应把 None=全删收紧为显式 `user:"*"` 之类不可由缺省触发的值。

---

## 五、探针与复现

- 脚本（`%TEMP%\ra2_scripts\`）：
  - `probe_backend.py`——test_client 33 断言：守卫矩阵 G1-G12、RA4a/c/d/e、RA5/5b、RA6a/6b、RA8、RA11/11c、RA12、RA13、RA7a、RA3a-d
  - `probe_scoped.py`——RA3 目录差分隔离（排除历史 tmp 残留污染）+ defer 句柄滞留实证
  - `probe_raw.py`——活服务器 + 原始套接字 R1-R5（重复头/obs-fold/HTTP1.0 无 Host/kill-shot/正控）+ 攻击页生成
  - `probe_browsersrv.py` + `probe_dbcheck.py`——双端口常驻（8800 真实 app 假库 alice/bob；8801 跨端口攻击源）+ 库状态取证
- 工件：`%TEMP%\ra2_art\`（假 profile：Login Data 含 v10 AES-GCM 密文 + Local State 真 DPAPI 包裹密钥；attack.html 跨端口攻击页）
- 浏览器：ZCode 内建 Chromium——攻击页自动触发 4 通道 → 服务端日志 4×403、alice/bob 行完好、无 pending；同源正控 `pw_list 200 items` / `pw_reveal 200 S3cret-Alice-9`
- pytest：`287 passed, 10 subtests passed`（HEAD e564f24；工作树在途改动为他队 harness 域，与密码链无涉）
- git：零改动（仓库仅新增本报告）

## 六、修复优先级建议

1. **RA12**：pw_* 加凭据（启动期随机 token 经页面上下文交 UI，请求头校验）；Origin 校验保留为浏览器跨站层，注释改为如实声明边界（只防浏览器，不防本机进程）。
2. **RA13**：web-panel.js:1187 加 `user: it.user`；服务端 user 缺省改 400（或显式哨兵），消灭 None=全删的缺省触发。
3. **RA15**：flush 失败不得删 pending；按 execute 成功数决定清理；库缺失不 connect。
4. **RA14**：`if _tabs is None: return` → `if _tabs is None: _pw_del_flush(); return`（一行）。
5. **RA17/RA18**：连接生命周期统一 finally（close+remove）；`_pw_entries` 恢复 except 优雅分支（顺手消 pw_list 500 回归）。
6. **RA16**：flush 损坏路径对齐 defer（重建+WARN+隔离）。
7. RA9/RA10 仍挂账（维持低危）。
