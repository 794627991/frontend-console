# 红队终局审计（第四轮）· 清零终验报告

- **审计员**：终局审计员（第四轮；前两轮战果：R1 44 项回归 0 丢失 + RD1 钉测丢失、R2 复验 15 条新发现 RD2 等）
- **日期**：2026-11-16
- **对象**：HEAD `3e728c5`（v4.1.0-a585）——复验轮 15 条修复（RA12-RA18/RC6/RC7/RC9/RC10/RB7-1/RB7-2/RB8）的终验 + a584/a585 全量回归 + 遗留清点
- **方法**：四份复验报告（A2/B2/C2/D2-final）全部发现逐条在 a585 重验；对抗探针真运行（Flask test_client 33+ 断言、真实 WebTabs+CLR 桩强制交错探针含 a584 对照组、锁库/畸形库/巨整数/lone-surrogate 全形态）；pytest 全量（隔离 USERPROFILE）；py_compile/node --check 全量；AST 重名扫描；8 历史风险点 + a584 26 条签名逐一 grep 复核
- **纪律**：仓库零改动（本报告除外）；git 只读；探针全部落在 `%TEMP%\rt_final_zero\`（LOCALAPPDATA/DATA_DIR/CONFIG_FILE 三重定向隔离；全程未触碰真实密码库——真实 `Login Data` 事后验证 mtime 2026-11-12、0 行、无 journal 残留，完好）

---

## 一、终判

**未清零。复验轮 15 条：真修确认 8 条半（RA13/RA14/RA16/RA18/RB7-2/RB8/RC6/RC7/RD1），修复无效或自破 6 条（RW1-RW6），另 2 条新发现（RW7 已并入、RW8 新增）。网页域未处置问题数 = 8（RW1 起），终验不通过。**

| 编号 | 级 | 一句话 | 实测证据 |
|---|---|---|---|
| **RW1** | **高·回归** | RA12 接线断链：前端从 `/api/status` 取 token，但 token 只由 `/api/theme` 下发 → `__fcPwToken` 恒空 → 真实 UI 所有 pw_* 操作 403——**a585 把 a583 密码管理器 UI 全操作打死** | probe_ra12 [1][4]：`/api/status` keys=`['log_dir','ports']` 无 pw_token；同源 Origin+无 token 头 → 403 |
| **RW2** | **高** | RA12 威胁模型未闭：token 经**无鉴权 `GET /api/theme`** 暴露，本机任意进程 GET 即拿 → 双自指头+token → **200 全库明文**（与 a584 的 kill-shot 同效）；提交注释「本机其他进程无法预知」不成立；DNS rebinding 同样打穿（同源后可读 /api/theme） | probe_ra12b [3][3b]：token+`Host:localhost`+`Origin:http://localhost` → pw_list 200 items / pw_reveal 200 放行到解密层 |
| **RW3** | **P2** | RB7-1 修复是 no-op：dispose_all「快照→_cancel.add」窗口内 `_build` 完成的交错，a585 与 a584 行为**逐字相同**（100/100 孤儿+滞留 cancel 标记+二次 beacon 回收=0）；`_build` finally 的纪元随弃在该交错里运行于 `_cancel.add` 之前（检查恒 False），提交信息「100/100 → 0」与实测不符 | probe_rb7 a585/a584 对照：窗口X 两版均 100/100 |
| **RW4** | **中** | RA15 修复被自身 except 击穿：锁库场景（RA15 原始场景）下 DELETE 撞锁 per-item 吞掉 → 删后复核 SELECT 同样撞锁 → `except Exception: pass` 吞掉 → **落到 os.remove + INFO「N 条已删」假成功**，pending 销毁、行未删；「验证后清账」仅在复核查询自身能成功时成立 | probe_ra15b：EXCLUSIVE 锁库 flush 耗时 14.65s，INFO「1 条已删」，pending 文件消失，locker 视角行仍在 |
| **RW5** | **低** | RA17 半修：pw_reveal 侧已修好（finally close+remove，畸形库归一 200 ok:false、0 副本残留——实测过）；**pw_list 侧未修**——`_pw_entries` 无 except（畸形库裸 **500**，a584 RA7 修复引入的回归仍在）+ close 仍在 try 内（异常路径连接泄漏→副本残留+句柄暂锁，实测新增 1 个 LD.db 残留）；提交「消除 500 三态」只对 reveal 成立 | probe_ra15b：pw_list status=500 + 残留 1 个且锁死 |
| **RW6** | **琐碎** | RC9 未修：defer 失败分支遗留半截 `.tmp`（实测 UnicodeEncodeError 中断后 `pw_pending_del.json.tmp` 存在）；提交「挂起 .tmp 原子写已在 RA5」不实——RA5 原子写保护主文件，不清理 tmp | probe_tail：tmp存在=True |
| **RW7** | **琐碎** | RC10 未修：ts 无钳位，400 位巨整数原样落 config.json（上限≈100 条×4300 位≈40KB，方向安全但与声明不符）；提交「ts 截断已在清洗器」不实——清洗器截 title/note/url，**不钳 ts** | probe_pw_chain：len(ts)=400 原样落盘回读 |
| **RW8** | **低·新发现** | RA15 复核口径错位 → livelock：`user=""` 挂起条目 DELETE `username_value=''` 删 0 行，复核参数化 `?=''`（`u or ""`）恒真 → 命中该 origin 任意非空用户行 → WARN「未删净——挂起保留」**永久滞留**（每次退出 WARN、删除永不生效；方向保守不丢数据） | probe_tail：连续两次 flush 均保留，行=1 |

**真修确认（8 条）**：RA13（UI 补 `user: it.user`，后端精确删实测 u1 删 u2 留）、RA14（shutdown 两分支都 flush，`_tabs=None` 分支实测 0.028s 清账）、RA16（flush 损坏 WARN+放弃实测）、RA18（defer 失败 finally close，句柄实测释放）、RB7-2（stale 丢弃语义成立，见下节）、RB8（三次 shutdown 单次 grace、`_closing` 短路不睡但仍 flush、`_tabs=None`、退出后 create 拒绝——全实测过）、RC6/RC7（inf 落 0 不再 500——实测过）、RD1（双钉测各唯一、套件计数自洽）。

---

## 二、任务一：15 条逐条终验明细

### RA12（RW1+RW2）——修复自破 + 威胁模型未闭

代码链：`web_tabs.py:302` `PW_TOKEN = secrets.token_urlsafe(24)`（启动期随机✓）→ `server.py:1569` **`/api/theme` GET 响应**带 `pw_token` → `web_tabs.py:1187-1192` `_pw_guard` 双因子（X-FC-Token + Origin==http://Host）。

- **断链（RW1）**：`web-panel.js:1151` `fetch('/api/status')` 期望 `j.pw_token`，而 `api_status`（server.py:849）只返回 ports/log_dir。`__fcPwToken` 恒空串 → `if (__fcPwToken)` 恒假 → 请求无 `X-FC-Token` 头 → `_pw_guard` 403。**真实 UI 密码管理器的列出/显示/删除全部 403**。新钉测（route_chain 带 token）进程内直接 import token，测不到此断链。
- **暴露（RW2）**：`GET /api/theme` 无任何鉴权（本工具 /api/* 全开放设计）→ 本机进程两次调用（GET token + POST pw_list）即全库明文，与 a584 的 kill-shot 等效（probe 实测 200）。token 新增的真实防御面=「无凭据盲打必 403」（错 token/无 token 实测 403 ✓），对浏览器跨站是 Origin 已挡之后的第二层（冗余但无害），**对 RA12 宣称的「本机进程不可预知」为零防御**。注释（web_tabs.py:299-300「本机其他进程无法预知」）与事实不符。
- **最小修复建议**：① RW1 一行——web-panel.js 改 `fetch('/api/theme')`（或 server 把 pw_token 挂进 /api/status）；② RW2 二选一——(a) 注释/台账如实降级「token 只防无凭据盲打，本机进程防御依赖 OS 用户隔离（同用户进程本可直读 sqlite+DPAPI）」；(b) 真修——token 经 `ExecuteScriptAsync` 注入页面闭包（不经 HTTP GET），本机进程需读进程内存才能取得。

### RA13【确认】

web-panel.js:1197 `api({ act: 'pw_del', origin: it.origin, user: it.user })` 在位；pw_list items 携带 `{"origin","user"}`；后端精确删实测（u1 删、u2 留）。观察：`user=None=全删` 兼容语义保留（A2 建议的 400 未采纳）——UI 不再触发 None，但任何能过双因子的主体缺省仍全删（并入 RW2 威胁面）。

### RA14【确认】

`shutdown()`：`_closing` 短路分支 flush + 主分支无条件 `_pw_del_flush()`（`if _tabs is not None: flush_on_exit` 之后不再 else 隔断）。实测：`_tabs=None` + pending 文件 → shutdown → 文件清、行删、0.028s。

### RA15【RW4+RW8，部分失效】

已修面：库缺失/0 字节不 connect 不造假（实测 pending 保留+WARN ✓）；成功路径删后清账 ✓；空 pending 清理 ✓。失效面：**锁库场景假成功（RW4）**——复核块的整体 `except Exception: pass` 把「复核失败」当「复核通过」；**u="" livelock（RW8）**。修法：复核 except 改 `WARN + return`（复核失败=未验证=保留 pending）；复核谓词与 DELETE 对齐（u="" 只查 `username_value=''` 行）。

### RA16【确认】

flush 损坏路径：`json.load` 失败 → WARN「挂起文件损坏，已放弃」+ return（实测）。残留观察：损坏文件保留 → 每次退出重复 WARN（不隔离不删；无害，README 级）。

### RA17【RW5，半修】

- pw_reveal 侧 **修好**：con=None + finally{close; remove}，畸形库归一 `200 {"ok":false,"err":"库读取失败…"}`，干净基线下异常路径 **0 副本残留**（实测）。
- pw_list 侧 **未修**：`_pw_entries`（web_tabs.py:146-158）无 except → 畸形库 pw_list **裸 500**（traceback 实锤 `sqlite3.DatabaseError: file is not a database` 直穿 Flask）——这是 a584 RA7 修复引入、A2 轮 RA17d 点名的回归；close 仍在 try 内 execute 之后 → 异常路径连接泄漏 → finally 的 remove 被吞 → 副本残留（实测新增 1 个 LD.db，且句柄暂锁）。
- 修法（B2/A2 同款三段式）：`_pw_entries` 改 `try: connect/execute except: return []`（或归一 err）+ close/remove 挪 finally。

### RA18【确认】

defer 即时路径 `con = None` + finally close——畸形库 defer 后真实库文件立即可删（实测无 GC 依赖）。

### RB7-1【RW3，修复 no-op】

强制交错探针（真实 WebTabs + CLR 桩 + `_epochs.get` 钩子在 dispose_all 过滤步内排干 UI 队列——B2 同款方法）：

| 指标 | a584（修复前基线） | a585（修复后） |
|---|---|---|
| 窗口X 控件建成 | 100/100 | **100/100** |
| 纪元被 pop | 100/100 | 100/100 |
| 滞留 cancel 标记 | 100/100 | **100/100** |
| 二次 beacon 回收=0（孤儿实锤） | 100/100 | **100/100** |

根因：`_build` finally 的 `if tab_id in self._cancel: self._epochs.pop(...)` 在该交错里**运行于 pending 循环的 `_cancel.add` 之前**（钩子排水发生在过滤步，标记尚未写入）→ 检查恒 False → 与无修复完全一致。标记滞留+纪元被循环 pop 的孤儿结局不变。附带的 W5-late-build 场景（dispose 落在 _build 中途）两版亦逐字相同（50/50 孤儿）——那是 dispose() 顶部无条件 `_epochs.pop` 的既有 W5 窗口行为，非 a585 引入。**B2 的原建议（弃建判据改 epoch 归属校验：`_epochs.get(tab_id) != 创建时 epoch` 即弃建+清标记）才是有效修法，未采纳。**

### RB7-2【确认，含协调人指定组合时序实测】

实测时序（`_want_epoch=E2, sq=5` 在位）：

1. 旧纪元迟到 `show('old', sq=37, epoch=E1)` → `{"stale-epoch-dropped": true}`，`_want_epoch` 翻为 E1、水位 0→37——**意图被丢弃，不应用** ✓（a584 对照组：直接应用陈旧意图）。
2. **协调人问题实测：新纪元自己的 show（E2, sq=6）也被丢弃一次**——因 `_want_epoch` 已被迟到的 E1 翻走，E2 到达再次判定「换纪元」→ stale 丢弃。**自愈**：下一条心跳（E2, sq=7）epoch 一致 → 应用（new.Visible=True old.Visible=False）。
3. 前端侧核实：`_webReconcileVis` 2s 周期 + R9.14 恒发（目标显示每轮无条件重发、全隐每轮无条件重发，web-panel.js:493-516/543-548）→ 任何误丢弃 ≤2s 自愈，与提交声明「误丢弃 ≤2s 恒发自愈」一致。
4. 观察①：stale 路径在早退前已写 `self._want=(陈旧意图)` → **下一个 layout 的 `_apply` 会把它应用**（实测 old.Visible=True）——两版行为相同（a584 对照同样泄漏），属既有 ≤2s 自愈窗形态，非本轮新增。
5. 观察②：双活 UI 窗口交替纪元（每条都翻纪元→每条都丢）在真实前端**结构性不可达**——`_webCtl` 单点 owner 门（second-ui-client 一切 web 操作被拒，web-panel.js:401-403），非 owner 窗口发不出 show/hide_all。
6. 观察③：每次页面刷新后首条 show 必被 stale 丢弃一次（reset_session 置 `_want_epoch=None`）——设计内自愈窗，刷新可见性应用恒有 ≤2s 延迟（提交信息已声明接受）。

### RB8【确认】

实测：三次 shutdown（grace=200ms）→ 236ms/0ms/0ms，flush_on_exit 仅调 1 次；`_closing=True` 并发短路分支不睡但仍 flush；shutdown 后 `_tabs=None`、REST create 返回「控件管理器未装配」。观察：`flush_on_exit` 本体无早退门（重入保护全靠 shutdown 侧）；`_tabs = None` 在 try 内 flush 之后——若 flush_on_exit 抛异常则不置 None（生产中其内部全 try 包裹不会抛）；两线程同时过 guard 的 µs 窗口仍在（实害=多睡一个 grace）。

### RC6/RC7【确认】

`/api/theme` `web_favs[].ts=1e999` → 200 落 0；`tftp_pane_h=1e999` → 200 落 0（server.py:1416-1419/:1630-1633 补 OverflowError）。实测过。

### RC9【RW6，未修】/ RC10【RW7，未修】

见§一表。两条的 a585 提交声明（「已在 RA5」「已在清洗器」）均与实测不符——属于「记录级随批」被错误标注为已处置。

### RD1【确认】

`test_show_hide_one_semantics`（:341，docstring 带 RD1 案底）+ `test_anti_autosignin_injected`（:405）各唯一定义、全量套件实跑通过；AST 实证 tests/ 190 个模块级 def 零重名。

---

## 三、任务二：D2 §七 25 个钉测缺口补齐状态

a585 仅动了 route_chain（RA1/RA2 部分补齐）与 `_mk`（RB8 测试基建）。**25 个缺口：部分补 2、未补 23。**

| # | 缺口（D2 建议钉测名） | a585 状态 | 未补者的钉测建议（只建议不落盘） |
|---|---|---|---|
| RA1 | test_pw_guard_requires_matching_origin | **部分**（route_chain：带 token+同源 Origin 200 ✓；错 token 403 ✓） | 补两行负向：无 Origin+对 token → 403；对 token+异端口 Origin → 403 |
| RA2 | 并入上测 | **部分**（同上） | 补：`Origin: http://localhost`（缺端口）vs Host localhost:PORT → 403 |
| RA11 | test_shutdown_none_flushes_pending | 未补（`test_shutdown_none_safe` 仍只钉不抛；且因 RW1 需先修 UI 断链） | `_tabs=None`+造 pending → `shutdown(grace_ms=1)` 后 pending 文件不存在 |
| RA3 | test_pw_entries_removes_copy | 未补 | 合法库 pw_list 后 mkdtemp 差分无 LD.db 残留 |
| RA4 | test_pw_del_scoped_to_user | 未补 | 临时库两 user 同 origin，`pw_del user=其一` → 剩 1 行 |
| RA5 | test_pw_del_defer_concurrent_no_loss | 未补 | 双线程×10 defer → pending 20 条全在且为合法 JSON |
| RA6 | test_pw_pending_corrupt_rebuilds | 未补 | 写 `{"corrupt` → defer 后 pending 合法且含新条目 |
| RA7 | test_pw_reveal_malformed_db_graceful | 未补 | 非 sqlite 文件 → pw_reveal 200 且 ok:false；**顺带钉 pw_list 同形态（RW5）** |
| RA8 | test_pw_reveal_latest_by_date | 未补 | 两条同 origin+user → 返回 date_created 最新 |
| RB1 | test_create_fast_fail_while_closing | 未补 | `_env=None;_closing=True` → create 即返 err 且 <0.5s |
| RB2 | test_reset_session_preserves_cancel | 未补 | `_cancel.add('a')` → reset_session → `'a' in _cancel` 仍真 |
| RB4 | test_show_epoch_resets_seq_watermark | 未补 | show(sq=50,epoch=E1) → show(sq=1,epoch=E2) 不被丢；**顺带钉 RB7-2：E1 迟到 show 后 E2 首 show 丢一次+第二条应用（RW3 关联行为锚）** |
| RB5 | test_suspend_callback_respects_intent | 未补 | `_want=('t',True)` 触发 `_after` 等价路径 → Visible True；`_want=None` → False |
| RB7-1 | （本轮新增缺口） | 未补 | **RW3 的钉测**：钩子排水交错 + 二次 dispose_all(E1) recycled 必 ≥1（现状红灯） |
| RB8 | （本轮新增缺口） | 未补 | 三次 shutdown 累计耗时 < 2×grace；shutdown 后 `_tabs is None` |
| RA14/15/16 | （本轮新增缺口） | 未补 | RA14 同 RA11 行；RA15 锁库 flush 后 pending **必须仍存在**（现状红灯，RW4）；RA15e u="" 条目两次 flush 后 pending 保留且 WARN（现状红灯，RW8）；RA16 损坏 → WARN+不崩 |
| RA17/RA18 | （本轮新增缺口） | 未补 | RA17d：畸形库 pw_list 状态码 ≠500（现状红灯，RW5）；RA18：畸形库 defer 后库文件立即可删 |
| RC1 | test_suspend_diag_no_quote_escape | 未补 | 源码断言无 `"console.warn('[` 单引号形态；diag 含 `'` payload json 往返无损 |
| RC2/RC3 | test_web_favs_clean_scheme_whitelist | 未补 | POST file:// 收藏 → GET 回读无；`ts:"abc"` → 200 且 ts==0 |
| RC6/RC7 | （本轮新增缺口） | 未补 | `ts:1e999`/`tftp_pane_h:1e999` → 200 且落 0 |
| RA12 | （本轮新增缺口） | 未补 | **RW1 的钉测**：test_client `GET /api/status` 必含 `pw_token` 键（现状红灯）；**RW2 的口径钉**：POST `/api/theme` 不得 500（防 token 端点回归） |
| RD1 | 已有 | ✓ | — |
| 新需求 | 休眠保持标题 | 未补 | node 源码断言 `__webTabTitle` 含 trim+about:blank 忽略分支 |

**结论维持 D2 判断：钉测缺口是最大回退风险**——本轮 RW3/RW4/RW5/RW1 全部是「修复（或接线）无钉测保护」的直接产物：RB7-1 若有钉测当轮即红、RA12 断链若有端点钉测当轮即红。

---

## 四、任务三：a584/a585 批次回归数字

```
pytest 全量（隔离 USERPROFILE，不带 -I）:
  入库套件:      275 passed, 1 skipped, 10 subtests passed (19.07s)
                 （与 a584 基线持平——a585 改 2 测不增测；RD1 钉测在其中实跑）
  含并行未跟踪:  286 passed（多出 11 = tests/test_scheme_capacity.py，归属
                 harness/终端域并行工作，非网页域，全过）
route_chain:     单跑含（RA12 token 正向 13 act 全可达 + 错 token 403 反向钉 + bad act 兜底）
py_compile:      web_tabs/web_proxy/server/main/tray/devtools_cdp/shell_conn
                 + harness(lifecycle/routes/session) → 10 文件全过
node --check:    web/js/*.js 顶层 + web/js/harness/*.js 全过
重名扫描:        tests/ AST 190 模块级 def 零重名；web/js 零顶层重名
                 （bit-calc.js parsePrimary/parseMul/parseAdd ×2 为两个闭包
                 作用域内同名局部函数，a441 起既有，合法，非网页域）
8 历史风险点:    ① 13 act + bad act 兜底（:1279）✓ ② R9.13 禁用注释+__fcDiag ✓
                 ③ closest('.close') :255 ✓ ④ tray global（区段未触碰，D2 裁决
                 承继+py_compile 过）✓ ⑤ --disable-web-security 仅 main.py:1599
                 注释 ✓ ⑥ observe(document) 仅 a11y/web-panel body 观察器（无
                 密码助手残魂）✓ ⑦ var g=Date.now() :41 ✓ ⑧ AutofillServer-
                 Communication :373 ✓
a584 26 条签名:  A3/A5/A9/P1''/D1/D8/RB1/RB2/RB4/RB5/RC1/RC2（前端 :1306 白名单
                 +服务端 :1415）/_SINGLE_KINDS（util.js:66 无 web 无 shell）/标题
                 保持（trim+about:blank 忽略，含 O4 重复条件疵点原样）——全在位
a584 遗留观察:   O1（RB1/RB6 标签混淆）O2（REST create/nav 零 scheme 校验残留）
                 O3（mkdtemp 空目录累积）O5（_want_epoch 未在 __init__ 初始化）
                 O6（reveal 200 非 400 口径）O7（route_chain docstring「10 act」
                 滞后）O8（「26 全清」口径）——全部原样存在，本轮不计入 RW
                 （D2 已按「知情未修/观察」口径挂账）
reflog/工作树:   零 reset 零 stash；a585 为 HEAD
```

## 五、任务四：遗留清点终审

1. **工作树并行改动**（会话期间从 4 文件增长到 8 文件：harness lifecycle/routes/session、index.html、chatctl.js、shell.js、replay.js、style.css + 未跟踪 tests/test_scheme_capacity.py）：`git diff -- src/web_tabs.py src/server.py web/js/web-panel.js src/main.py web/js/settings.js` 为空 → **网页域零触碰，排除在本轮网页域审计外**。index.html 的 `aiRailHandle` 删除自洽（web/js 全域 0 残留引用）；新增 `aiPanelBtn` 属主 UI 面板域。任务前提中提到的 server.py/shell_conn.py 在途改动实况为干净（已入库或已还原）。
2. **test_server.bat**：非未跟踪——已于 a566（7c5e705）入库，内容为沙箱测试启动器（USERPROFILE 重定向），良性。
3. **web_passwords.json**：src/ + web/ 全量 grep 零引用（a579 提交已声明「历史数据不再读写，可手动删除」）——无孤儿引用，维持挂账口径。
4. **server.py / settings.js 未提交修正**：两者 `git diff HEAD` 均 0 行——工作树干净；server.py 的 a585 修复（RC6/RC7/pw_token）已入库；settings.js 最后触碰 a580 已入库。**无未完成的在途修正**。

## 六、残余观察项清单（不构成问题的记录）

- RA16 损坏 pending 文件保留 → 每次退出重复 WARN（不隔离；无害）。
- RB7-2 每次刷新首条 show 恒被 stale 丢弃一次（≤2s 自愈；设计内）。
- RB7-2 stale `_want` 经 layout 泄漏应用窗（µs-s 级；两版相同，自愈窗内）。
- RB8 `flush_on_exit` 本体无早退门、异常路径 `_tabs=None` 不执行（生产不触发）；并发双 guard µs 窗。
- RA13 `user=None=全删` 兼容语义保留（UI 已不再触发；与 RW2 威胁面并读）。
- `_pw_entries`/pw_reveal 的 `_pwdb_copy` 仍每次 mkdtemp——空目录累积（O3 既有）。
- 锁库场景 flush 耗时 ~15s（DELETE+复核各吃 5s busy timeout）——退出路径延迟放大，RW4 修复时应一并给 connect 设短 timeout。
- shutdown 注释行在 docstring 之前 → 字符串字面量不再是 docstring（纯风格）。

## 七、复现与探针

`%TEMP%\rt_final_zero\`（全部可独立重跑）：
- `probe_ra12.py` / `probe_ra12b.py`——RW1/RW2 全部断言（/api/status 无 token、/api/theme 暴露、kill-shot 200、无/错 token 403、UI 形态 403）
- `probe_rb7.py [a585|a584]`——RW3 对照矩阵（窗口X 100/100 两版全同 + W5 50/50 + RB7-2 时序 + layout 泄漏）
- `probe_w5_debug.py`——W5 单步（dispose 顶部无条件 epoch pop 实证）
- `probe_ra15b.py`——RW4 锁库假成功（14.65s + INFO 假日志 + pending 消失）+ RW5 畸形库 pw_list 500/残留 vs reveal 0 残留
- `probe_tail.py`——RW8 livelock + RA16/RC9/RA14
- `probe_rb8.py`——RB8 全形态
- `probe_pw_chain.py` / `probe_ra13.py`——RC6/RC7/RC10/RA15a/RA17/RA18/RA13

复现口径：`python -I <probe>`（探针自隔离 LOCALAPPDATA/DATA_DIR/CONFIG_FILE）；pytest 口径：`USERPROFILE=$(mktemp -d) python -m pytest tests/ -q`（不带 -I）。

---

## 八、结论

**不满足清零标准。** 8 项未处置（RW1 高回归 / RW2 高 / RW3 P2 / RW4 中 / RW5 低 / RW6 琐碎 / RW7 琐碎 / RW8 低新发现），其中 4 项（RW3/RW4/RW5/RW1）是「修复/接线无钉测保护」直接产物。修复建议已逐条给出最小修法；建议修完 RW1-RW5 后重跑终验（RW6/RW7 为声明勘误级，可与修复合批）。

*报告完。终局审计员，2026-11-16。git 全程只读；仓库唯一新增 = 本报告；真实密码库与真实 config 零触碰（事后验证完好）。*
