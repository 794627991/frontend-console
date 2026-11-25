# 红队攻击审计 · A 轮报告（网页 tab 密码功能全链）

- **审计员**：红队密码域攻击者 A
- **日期**：2026-11-16
- **对象**：当前 HEAD `480c07d`（v4.1.0-a583）——网页 tab 密码链：a578（WebMessage 桥）/ a582（登录态记忆四根因）/ a583（🔑 原生密码库管理器）三批提交
- **方法**：全部结论以**实际运行探针**为准——真实 DPAPI（CryptProtectData/CryptUnprotectData）、真实 AES-GCM（cryptography 50）、真实 sqlite、真实 Flask app（`src.server.app` test_client，与 tests/test_route_smoke.py 同源）、Node 24 逐字复用生产 `esc()`+渲染模板注入 18 组 payload；pytest 全量（隔离 USERPROFILE）。git 只读，仓库零改动（data/ 为 gitignored，探针全部落在 `%TEMP%\ra_scripts`（脚本）与 `%TEMP%\ra_art`（假数据工件））
- **基线注意**：工作树含在途改动（src/server.py + 4 个 js + 未跟踪 src/shell_conn.py，本地 shell 功能）。**全部验证以 HEAD 代码语义为准**；探针 import 的模块与 HEAD 的密码链零差异（在途 diff 为 shell 增量分支）

---

## 一、终判

**确凿发现 11 条：高 1 / 中 4 / 低 6。** 任务预设的最大攻击面（a578 WebMessage 桥协议 / pw_reveal 页面广播 / `__FC_LAST` 缓存）**在 HEAD 已整体不存在**——a579 把 a578 的 `_on_webmsg`、注入脚本、REST pw 四路由全量清除（`git show 021e93f --stat`：-233 行），a583 的密码管理器走纯 REST（工具主 UI 同源 fetch），无任何 WebMessageReceived / PostWebMessageAsJson 通道（全仓 grep 实证，仅 tests 假桩残留）。「页面脚本读全部站点密码列表/明文」的结构性通道不存在。

- pytest 全量（隔离 USERPROFILE）：**274 passed, 1 skipped, 10 subtests passed**（19.91s）
- 自建探针：后端密码链 21/21 行为确认（1 条初判 FAIL 为探针自身变量复用 bug，证据行显示服务端行为正确——`{'err': 'not-found', 'ok': False}`）；服务端守卫 10/10；XSS 渲染 18/18 全惰性

| 级别 | 编号 | 一句话 |
|---|---|---|
| 高 | RA1 | pw_reveal/pw_list 零鉴权：无 Origin 头的 loopback POST 直接回全部明文——本机任意进程/其他 OS 会话可导出全库密码 |
| 中 | RA2 | 无端口 Origin（`http://localhost`/`127.0.0.1` = 80 口）被守卫放行 → 盲 CSRF pw_del |
| 中 | RA3 | `_pwdb_copy` 每次调用把整库 Login Data 拷进新 mkdtemp 目录且永不清理——%TEMP% 无限堆积含明文用户名/origin 元数据与密码密文的库副本 |
| 中 | RA4 | pw_del 按 origin_url 全删：UI 一行=origin+user，一次点击删光该站点**所有**用户名的密码 |
| 中 | RA5 | pw_pending_del.json 读-改-写竞态丢更新（实测 20 删丢 14/1/10）且非原子写 |
| 低 | RA6 | pending 文件损坏 → `_pw_del_flush` 永久静默失效，删除承诺破裂、文件永不清理 |
| 低 | RA7 | 畸形密码库 → pw_reveal 未捕获 500 + sqlite 连接泄漏（无 try/finally）；_pw_entries 异常路径同型泄漏 |
| 低 | RA8 | 同 origin+user 多条时 pw_reveal `LIMIT 1` 任意取行 |
| 低 | RA9 | 明文 reveal 无 OS 凭据二次认证、无 eventlog 审计 |
| 低 | RA10 | `_webPwMgr` 自带 fetch 绕过 `__webUiIsOwner` 单点门控 |
| 低 | RA11 | WebTabs 装配失败（`_tabs=None`）时挂起删除永不 flush |

---

## 二、确凿发现（RA1 起，全部实测）

### RA1【高】密码 REST API 零鉴权——本地任意主体两次 HTTP 调用导出全部明文

- **位置**：`src/web_tabs.py:1066-1083`（pw_reveal）、`:1063-1065`（pw_list）；守卫 `src/server.py:388-413`——**仅校验 Host/Origin，无任何凭据**；绑定 `src/server.py:3762`（host=127.0.0.1）
- **攻击**：守卫对**不带 Origin 头**的 POST 一律放行（`server.py:394` `if origin:` 才检查——MCP/worker urllib 需要这条豁免）。浏览器页面的跨源 fetch 无法省略 Origin，但**本机任意原生进程、其他 OS 用户会话（Windows loopback 为机器级共享，跨会话可达——此条为分析，未实测他会话）、或任何本地浏览器直开的同源页面/控制台**都不受 Origin 语义约束
- **实测**（probe2 G5，真实 `src.server.app` test_client，无 cookie 无 token 无 Origin）：
  `POST /api/web/tabs {"act":"pw_reveal","origin":"https://example.com/","user":"alice"}` → **HTTP 200 `{"ok":true,"pw":"S3cret-Alice-1"}`**
  pw_list 同样裸放行（G4 items=12）。DPAPI「同用户才能解」的边界被 API 打穿：B 会话的进程让 A 用户的工具进程代为解密并送达明文
- **影响**：共享/多用户机器上的跨用户明文密码导出；本机任意恶意软件免 DPAPI 知识直取全库；无速率限制、无审计
- **建议**：API 增加凭据（启动期随机 token 经安全信道交 UI）或对 pw_* 路由强制同源 Origin+同端口校验 + reveal 计数审计

### RA2【中】无端口 loopback Origin 放行 → 盲 CSRF 删除密码

- **位置**：`src/server.py:384-385` `_LOCAL_ORIGIN_RE = ^https?://(127\.0\.0\.1|localhost|\[::1\])/?$`（复审 F5 的故意豁免：**不带端口**的 loopback origin 一律放行，`server.py:400`）
- **攻击**：`http://localhost:80` 或 `http://127.0.0.1:80`（Origin 头即 `http://localhost`，浏览器省略默认端口）上的任何可执行脚本页面——本机其他 Web 应用被注入/带 XSS 的路由器管理页/恶意本地服务——发 `Content-Type: text/plain` 简单请求（无预检）携带 JSON 体即可驱动 pw_del
- **实测**（probe2 G4b）：`Origin: http://localhost` + text/plain JSON `{"act":"pw_del","origin":"https://blind.example/"}` → **HTTP 200 `{"immediate":true,"ok":true"}`，删除真实执行**
- **边界**：读面不可利用——Flask 全站无 ACAO 头（grep 实证 0 处），跨源 fetch 读响应被浏览器默认拒（G4/G8 实测 acao=False）。故只能盲删（origin 可猜测：常见 SSO/邮箱域），完整性损失
- **建议**：Origin 校验去掉无端口豁免，或对 pw_* 路由要求带端口的 `_own` 精确同源

### RA3【中】%TEMP% 无限堆积密码库副本（永不清理、进程退出后仍可读）

- **位置**：`src/web_tabs.py:60-71` `_pwdb_copy`——每次 `tempfile.mkdtemp()` 新建目录拷入整库 `LD.db`，**无任何删除/清理路径**（全函数无 unlink；退出流程亦不回收）；pw_list 与 pw_reveal 每次点击都触发一次
- **实测**（probe1 P6）：3 次调用 `_pw_entries` → %TEMP% 新增 **3 个 tmp* 目录各含完整 13 行 Login Data**（username_value/origin_url 为**明文**、password_value 为可解密密文），探针进程退出后仍在。真机上每次开一次密码菜单、每次点一只眼睛都新增一份
- **影响**：敏感数据散布面随使用线性增长；同用户任意进程免工具免 DPAPI 直读元数据（浏览足迹+用户名清单），密文+Local State（同目录树常驻）可离线解；磁盘残留跨越工具生命周期
- **建议**：固定单个临时文件+用后即删（try/finally），或内存临时库（`sqlite3.connect(':memory:')` 前 `serialize`/逐表拷贝）

### RA4【中】pw_del 按 origin 全删——UI 行级语义与后端实际效果不符

- **位置**：`src/web_tabs.py:171` 与 `:207` `DELETE FROM logins WHERE origin_url=?`（仅 origin 一个条件）；前端每行展示 `user @ origin`（web-panel.js:1156-1157）
- **实测**（probe1 P4）：库里 `u1@del.example`、`u2@del.example` 两行，前端视角两条独立记录；一次 pw_del(origin=del.example) → **rows_left=1（keep.example 那条），两行全没**，`immediate:true` 无任何「将删除同站 2 条」提示
- **影响**：用户想删一个用户名的密码却静默删光同站全部（多账号站典型受害）；数据不可恢复（无回收站；若库锁定走 pending，同样全删）
- **建议**：DELETE 加 `AND username_value=?`（UI 已持有 user），immediate 提示条数

### RA5【中】pending 删除文件并发丢更新 + 非原子写

- **位置**：`src/web_tabs.py:177-187`——读 json→append→`json.dump(open(p,"w"))` 覆写，无锁、无 tmp+rename 原子替换；Flask `threaded=True`（server.py:3762）下两次快速「删除」即并发进入
- **实测**（probe1 P5 race，双线程各删 10 个 origin，库持锁走挂起路径）：3 轮试验 pending 文件最终条数 **丢失 14/1/10 条**（20 请求）；丢失的删除静默蒸发，UI 已显示「已标记删除——完全退出后生效」
- **连带**：非原子覆写正是 RA6 损坏形态的制造者（两线程交错写/写中被杀）
- **建议**：文件锁（msvcrt/portalocker）+ tmp+rename；或 pending 改 sqlite 表

### RA6【低】pending 文件损坏 → flush 永久静默失效

- **位置**：`src/web_tabs.py:199-202`——`json.load` 失败直接 `return`（无 WARN、无自愈、无备份）
- **实测**（probe1 P5）：pending 文件写入 `{"corrupt oops` → `_pw_del_flush()` 后**两行密码原样健在、文件原样健在**（对照：文件完好时 flush 正确删除并清文件）。此后每次退出都空转，用户的删除永远不生效且无从得知
- **建议**：损坏时告警+重命名隔离 `.bad`+空表重建；flush 结果回写状态供 UI 查询

### RA7【低】畸形密码库 → pw_reveal 未捕获 500 + sqlite 连接泄漏

- **位置**：`src/web_tabs.py:1074-1077`——`con = sqlite3.connect(db); con.execute(...)` 无 try/finally；`:148-156` `_pw_entries` 异常路径同样不 close
- **实测**（probe1 P3）：Login Data 为非 sqlite 文件时 pw_list 优雅返回 `items:[]`（:155 except 吞掉），但 pw_reveal **HTTP 500 HTML**（`sqlite3.DatabaseError: file is not a database` 直穿，Flask traceback 实录）；泄漏的连接在 Windows 上还锁住 %TEMP% 的 LD.db 副本，加重 RA3。库损坏来源现实存在：拷贝时 Chromium 正在写（_pwdb_copy 的 copyfile 无一致性保障）
- **建议**：try/finally + `except sqlite3.Error` 归一为 `{"ok":false,"err":"密码库不可读"}`

### RA8【低】同 origin+user 多条密码时 reveal 任意取行

- **位置**：`src/web_tabs.py:1075-1077` `... LIMIT 1` 无 ORDER BY
- **实测**（probe1 P3）：两行 `alice@example.com`（S3cret-Alice-1/-2）→ reveal 返回 `S3cret-Alice-1`（插入序第一条，非「最新」）。Chromium 允许同 origin+user 多条（不同 signon realm/时间），用户看到的是「任意一条」
- **建议**：按 date_created 排序取最新，或列表去重聚合

### RA9【低】明文 reveal 无二次认证、无审计

- **位置**：`src/web_tabs.py:1066-1083`（无 re-auth）；全仓 eventlog 模块与 pw 路由零交集（grep 实证）；后端日志仅记删除条数（:213），不记明文（明文不进日志——此项是干净的）
- **影响**：与 Chromium 原生管理器（新版本 reveal 前要求设备凭据）相比，任何人坐到屏幕前/任何同源上下文一键导出全部明文（结合 RA1 则连「坐到屏幕前」都不需要）。无审计 trail 意味着明文被批量拉取后无迹可查
- **建议**：reveal 前置 Windows Hello/凭据提示 + eventlog 记录 pw_reveal 计数与来源

### RA10【低】密码管理器 fetch 绕过「非主 UI 客户端禁令」

- **位置**：`web/js/web-panel.js:1147-1150` `_webPwMgr` 的 `api()` 直连 fetch，未走 `_webCtl` 的 `__webUiIsOwner` 单点门控（:401-403，R4-D3a「非主 UI 客户端禁止一切网页 tab 后端操作」）
- **实测**（probe3 源码断言）：`pw mgr api() skips __webUiIsOwner gate: true`
- **影响**：第二 UI 客户端（同机另一浏览器开 http://127.0.0.1:8765）被禁止操纵网页 tab，却可任意 pw_list/pw_reveal/pw_del。一致性缺口（RA1 已证 API 本身无鉴权，故不独立升级）
- **建议**：api() 并入同一门控或明确豁免理由入档

### RA11【低】WebTabs 装配失败时挂起删除永不执行

- **位置**：`src/web_tabs.py:1120-1125` `shutdown()` 首行 `if _tabs is None: return`；`_pw_del_flush` 仅在 `flush_on_exit` 尾部被调（:959-962）；挂起文件入口在 pw_del（:188）
- **影响**：WebView2 环境初始化失败的会话里用户执行删除（挂起路径必成功，因无浏览器持锁反而不成立——实际是「本会话曾建 tab 成功、退出时 env 已死」等边角），`_tabs=None` 的退出不 flush，pending 无限期滞留（RA6 损坏面随之增大）
- **建议**：`shutdown()` 在 `_tabs is None` 时仍直接调用 `_pw_del_flush()`

---

## 三、攻击未成功的面（攻击 ≠ 漏洞——列出以闭合任务清单）

| 任务面 | 结论 | 实证 |
|---|---|---|
| **WebMessage 桥协议攻击**（无 id/重复 id/超长 id/嵌套 body/body 非 dict/`__fc` 类型欺骗） | **面不存在**：a579 已删净 `_on_webmsg`/`WebMessageReceived`/注入脚本；HEAD 全仓 grep 仅 tests 假桩（`test_web_tabs_logic.py:76,122`）与 pywebview 主 UI 自身通道（main.py:1516，与密码无关） | git show 021e93f（-233 行）+ HEAD grep |
| **origin 防伪绕过 / cvw.Source 导航中途竞态** | 同上随桥消失。HEAD 唯一消费者 `_on_src`（web_tabs.py:518-528）只在**工具主 UI** 执行 `json.dumps` 拼接的 URL 推送，无安全决策依赖 Source；iframe 第三方脚本无任何 postMessage→宿主通道 | web_tabs.py 全文 + grep |
| **pw_reveal 明文广播/两 tab 混淆/iframe 汇聚读明文** | REST 请求-响应式，响应只回发起 fetch 的工具 UI 文档；无广播语义；页面脚本被 a239 守卫+无 ACAO 双重挡死 | probe2 G2/G4/G8 |
| **明文进 console/日志/DOM 残留** | 后端零明文日志（仅删条数，:213）；前端 reveal 经 `textContent`（:1175，无 innerHTML 注入面），菜单关闭即 `remove()`，无 `__FC_LAST` 类缓存（a578 遗物已随删） | grep + probe3 |
| **SQL 注入（origin_url/user 拼接）** | 全参数化。SQLi 形态参数返回 `not-found`；`x'; DROP TABLE logins;--` 作 origin 删一行都删不掉、表完好 | probe1 P3/P4 |
| **DPAPI/v10 畸形密文全层矩阵** | 空/3B/15B(nonce only)/1MB 垃圾/坏 base64 key/坏 JSON Local State/非 DPAPI 前缀 key/错密钥——全部 `(False, msg)` 优雅返回，零崩溃；err 串仅含 `InvalidTag()` 等，**无密钥材料泄漏**（探针断言 key-leak=False）；非 UTF-8 明文走 `decode("utf-8","replace")`；v20 落降级提示 | probe1 P2 七态矩阵 |
| **v10 密钥不可用降级** | Local State 缺失/损坏 → `(False,"v10 密钥不可用")`，不抛 | probe1 P2 |
| **密码管理器菜单 XSS（origin/user 含 HTML/引号/JS）** | **18/18 payload 全惰性**：生产 `esc()`（util.js:1257，转义 `&<>"'` 五字符）使 title 属性与文本节点无任何未转义定界符存活；`javascript:` 仅落入 title/文本（永不作 href）；reveal 明文经 textContent——**密码本身含 `<script>` 也不活** | probe3（逐字复用 esc+模板） |
| **删除确认绕过** | `confirm()` 在位（web-panel.js:1184）。服务端无确认概念——真正防线是 RA1/RA2 未闭合的 API 层，已另计 | probe3 断言 |
| **DNS rebinding 读密码** | Host 白名单拦（G1/G7 403 `forbidden host`） | probe2 |
| **网页 tab 内 evil.com 读密码列表/明文** | Origin 检查 403（G2）+ 无 ACAO 不可读（G4/G8）；其他 loopback 端口 origin 亦 403（G3，复审 F5 在位） | probe2 |
| **`__FC_LAST` 缓存污染** | 缓存不存在于 HEAD（a578 专有，a579 随删） | grep 0 命中 |

**边界观察（未定级，无法在本环境实测）**：`_pw_del_defer` 直写路径（web_tabs.py:170）在 Chromium 恰好未持锁时对**运行中的活库**执行外部 DELETE——sqlite 锁保证不损坏，但 Chromium 内存态可能复活条目或状态漂移；需真机浏览器行为验证。probe1 已证：库未被锁时 pw_del 一律 `immediate:true` 直写成功（不检测「Chromium 是否在跑」，只检测「库是否可写」）。

---

## 四、探针与复现

- 脚本：`%TEMP%\ra_scripts\probe1_core.py`（后端 21 断言）、`probe2_guard.py`（守卫 10 断言）、`probe3_xss.js`（XSS 18 payload）
- 工件：`%TEMP%\ra_art\`（假数据：自造 Login Data + Local State，真实 DPAPI/AESGCM 加密的假密码；探针环境曾实证 USERPROFILE 重定向会破坏 DPAPI masterkey 查找——复现时必须在 import 后恢复原 USERPROFILE）
- pytest（隔离 USERPROFILE）：`274 passed, 1 skipped, 10 subtests passed, 19.91s`；含 a583 钉测（pw 三路由存在性 :443、DPAPI 真往返+v10 构造真解 :486-514）
- git：零改动（工作树与审计前基线逐项一致：5 个在途 M + src/shell_conn.py 未跟踪）

## 五、修复优先级建议

1. **RA1+RA2+RA9**（同一根治点）：pw_* 路由加凭据/严格同源（去无端口豁免）+ reveal 审计
2. **RA3**：_pwdb_copy 用后即删
3. **RA4**：DELETE 带 username_value
4. **RA5+RA6+RA11**：pending 文件锁+原子写+损坏自愈+无条件 flush
5. RA7/RA8/RA10 顺手修
