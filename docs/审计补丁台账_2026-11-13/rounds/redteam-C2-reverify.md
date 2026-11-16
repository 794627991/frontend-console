# Redteam C2 · 注入修复复验（攻破 a584 修复本身）——2026-11-16

- 基线：HEAD `e564f24`（v4.1.0-a584），修复 diff `480c07d..HEAD -- src/server.py src/web_tabs.py web/js/web-panel.js`。
- 方法：每条修复先读 diff 定位改动语义，再以**对抗 payload 真实注入实测**（Python 3.14 真实 Flask test_client + 独占锁 sqlite、node 24 vm 桩 + 负控实验）回打修复面；修复未触及的原报告结论（esc / ExecuteScriptAsync / SQL 参数化）逐一回归复核。
- 纪律：仓库零改动（本报告除外）；真机密码库未碰；探针在 `D:\tmp\fc_redteam_c2\probes\`（p1~p4）。
- 总结：**RC1 修复确认（0/17 逃逸+负控）｜RC2 部分确认、REST 通道仍可攻破｜RC3 修复不完整（inf 仍 500，新 RC6/RC7 同族）｜RC4 修复确认（截断已除，挂起仍静默丢）｜RC5 修复确认（方向安全）**。新发现 RC6~RC10。

---

## RC1【修复确认】diag 单引号面 → 整句 json.dumps 双引号实参

- **两处都改**：`src/web_tabs.py:786`（suspend `_after` diag）与 `:816`（`_diag` → `_push`）。全仓 grep（`*.py`）`console.*` 仅此两处，均为
  `"console.warn(%s)" % json.dumps('[web-tabs] suspend: ' + ";".join(diag))`——整句（含前缀）作唯一 JSON 字符串**函数实参**。
- **17 类对抗 payload 实测**（node vm，`python -I json.dumps` 真实转义后注入执行）：
  `'); alert(1); ('`、`', ); alert(1); ('`（任务指定形态）、`"); alert(1); ("`、`');}alert(1);{('`、U+2028/U+2029、尾反斜杠、`\'; alert(1); \'`、NUL、`</script><img onerror>`、反引号 `${}`、`%s%n%p`、300 字符、`\n`/`\r\n`、`')]));alert(1);(('`——**全部 compiled=true、0 逃逸、参数以完整数据形态到达 console.warn**。
- **U+2028 质疑不成立**：json.dumps 默认 `ensure_ascii=True` → U+2028/2029 输出为 `\u2028`/`\u2029` 转义（实测 raw 字符不出现在产物中）。「json.dumps 不转义 U+2028」仅在 `ensure_ascii=False` 成立，本修复未关该开关。
- **实参表达式 vs 字符串字面量的转义差异**：实参形态下整段是双引号 JSON 字符串——`'` 成为普通数据（无需转义），`"`/`\`/控制符全被 json.dumps 转义，双引号定界不可破。**负控实验**：同 payload 回填旧单引号形态重建 `console.warn('[web-tabs] suspend: X'); alert(1); ('')` → vm 实测 `alert(1)` **真实执行**（executed=[["warn",["[web-tabs] suspend: X"]],[1]]）；新形态仅 warn 数据到达。
- 备注：diag 数据源仍全为内部诊断串（枚举/`%r` 异常文本），本次修复把「潜伏」面也结构性闭死（前缀并入 JSON 串后不存在引号语境混用）。

## RC2【部分修复确认 / 仍可攻破】

修复面实测（真实 Flask test_client + node 正则）：

1. **服务端 `_web_favs_clean` scheme 白名单**：19 条绕过矩阵全拒——`FILE://`/`File://`、前导空格/LF `file://`、UNC `\\server\share`、`//server/share`、`file\x00://`、`javascript:`（大小写 `JaVaScRiPt:`、空白拆分 ` java\nscript:`）、`data:`、`vbscript:`、`HTTP://`/`HTTPS://`/`hTtP://`（大写混合 http 也拒=**过严非过松**）、`http:/\n/example/`。仍放行仅 `http://a\x00b`（NUL 在 http URL 内）与 `http://ok.example/\evil`（反斜杠路径）——两者 scheme 真为 http，到达引擎只是垃圾主机/路径，**非 scheme 旁路**。
2. **历史存量（⑦）已兜底**：config.json 预埋 file://×2 + UNC + javascript: + 大写 http 收藏 → `GET /api/theme` 实测**读出即滤**（server.py:1532 出口走 `_web_favs_clean`），回读仅剩 `http://keep.example/`。
3. **web-session 通道（⑧）核过**：`_web_session_clean`（server.py:1441-1462）白名单实测未回归——config 预埋与 POST 双向注入 `file:///C:/secret.html`/`javascript:` 均被拒，idx 钳制正常。前端种子回填（web-panel.js:110-133）只滤 `typeof/about:blank`，但其数据源即服务端清洗产物，非独立缺口。
4. **前端消费端**：26 条 payload 对 `/^https?:\/\//i`（web-panel.js:1296）实测——所有危险形态 BLOCKED（banner 反馈）：`file` 三种大小写、前导空白/NUL 前缀、UNC、协议相对、`file\u0000://`、`javascript:` 各变体、`data:`、`vbscript:`、全角 `ｈｔｔｐ:`/`http：`、`\u2028http://`；放行仅真 http(s) 形态（`HTTP://` 大写放行 = 正常 http 导航，无危害）。

**仍可攻破（RC2 第 3 条未修）**：

- **REST `/api/web/tabs` create/nav 依旧零 scheme 校验**。stub 管理器录参实测：`file:///C:/Windows/win.ini`、`\\server\share\secret.xlsx`、`javascript:alert(document.cookie)`、`vbscript:msgbox`、`data:text/html,<h1>x` 经 `{"act":"nav"/"create"}` 全部**原样到达管理器层**（`navigate(('web:1', 'file:///C:/Windows/win.ini'))` 等，URL 逐字节一致）——源码链 `web_tabs.py:1110-1114 → create(:368)/navigate(:622) → cvw.Navigate(:437/:641)` 全程无检查。本机无鉴权进程一次 POST 即可让内嵌 WebView2 开本地文件/UNC（真机装配后端到端，R2-W16 已证控件无 file 限制）。**持久化钓鱼链（favs 投毒→重启→点击）已闭；一次性导航链未闭。**
- 本地 localStorage 恢复过滤器（web-panel.js:76-79）仍只滤 `about:blank`+typeof——非独立跳板（栈内容源头是 REST nav / 页面 Source 记录），但消费端 `_webNavigate`（:761，无 `_webNormUrl`）直发 REST create，兜底缺失与上条同根。
- **新候选面 RC8**（见下）：`__webTabNew`（web-panel.js:658）消费 NewWindowRequested 的 url 无任何 scheme 守卫。

## RC3【修复不完整——仍可攻破：inf 家族 500】

- 已修（实测 PASS）：`ts:"abc"`/dict/list/NaN/`"1e999"` 字符串/5000 位数字串（超 CPython 4300 位限制→ValueError 被 except 吞）→ 全部落 0；`1.5`/`true`/null 正常。
- **仍 500**：`{"web_favs":[{"url":"http://a/","ts":1e999}]}`——JSON 数字经 Python json.loads 变 `inf`，`int(inf)` 抛 **OverflowError**，`except (TypeError, ValueError)`（server.py:1416-1418）不含之——**真实 traceback 1626→1418**；裸 `Infinity`/`-Infinity` 字面量（json.loads 原生接受）同 500；`NaN` 正常（int(nan)=ValueError 被吞）。
- 崩溃在 `_save_config` 之前 → config 完好（实测磁盘回读一致）。危害仍=单请求拒绝服务+错误日志噪音（P3）。
- **同族第二处**：`{"tftp_pane_h":1e999|Infinity|-1e999}` → server.py:1630 裸 `int()` → **500**（NaN/字符串正常）——a563 既有代码，上轮 payload 未覆盖。
- 讽刺对照：同文件 `_web_session_clean` idx（:1457-1460，注释明写「a565 审计：Infinity→OverflowError 500」）与 web_tabs `_num`（:1094-1103）**都显式捕 OverflowError**——同型四处修二漏二。

## RC4【修复确认：截断丢数据已除 / 新问题：挂起仍静默丢】

- **原子写实测**：独占锁（BEGIN EXCLUSIVE）逼库进挂起路径 → surrogate origin（`http://x.example/surro\ud800gate`）→ `json.dump(ensure_ascii=False)` 写 `.tmp` 时 UnicodeEncodeError → 被捕、`os.replace` 未执行、**原 pending 文件一字节未动，先前 2 条挂起记录完整保留**——RC4 的「先截断后写」根因已除。
- **新问题**：①该条挂起删除**静默不落盘**：函数返回 `False`（「已挂起，退出后生效」语义）但 pending 文件无此条 → UI 假成功、该删除永不生效。原报告建议（`ensure_ascii=True` 或逐条 try 隔离）未采纳，仅靠原子写止损。②失败分支**遗留半截 `.tmp` 文件**在 DATA_DIR（实测残留，内容为截断 JSON）。③库空闲时 surrogate 走 immediate 路径：sqlite3 绑定直接 UnicodeEncodeError → 外层 except 落挂起 → 同①。
- RA4 精确删（origin+user 二元组）实测：同站 u1 精确删、u2/u3 保留；flush 的新旧格式兼容、surrogate 条目安全跳过、成功后 pending 文件移除——全部实测通过。

## RC5【修复确认：危险向已闭，口径仍不对称但方向安全】

- 服务端 `startswith(("http://","https://"))` 小写敏感 → 大写 `HTTP://` 被拒（过严）；前端正则 `/i` 大写放行——不对称仍在，但「能写入 config」∩「能被点击」只剩小写 http(s) + 内嵌 NUL/反斜杠垃圾，**无任何 scheme 旁路**。
- `http://a\x00b` 双端均放行 → 引擎层 DNS 垃圾解析失败，非注入面。

## 上轮结论复核（a584 修复后仍成立）

| 结论 | 复核方式 | 结果 |
|---|---|---|
| esc 13/13 | diff 核对（util.js 仅 shell 类型标签/图标，esc 未触）+ 13 类 payload 重跑 | residual=0/13 ✅ |
| ExecuteScriptAsync 双引号面 | 22 类 payload 重跑 `__webTabTitle(%s,%s)` 形态 + 全仓 7 处调用点核对（Dead/Shot/Title/Url/Hist/New/`__newWindow` + console.warn×2）全为 json.dumps 双引号实参 | 0 逃逸 0 编译失败 ✅ |
| RC1 面（原 98 中唯一失败项） | 17 类全打 | 0/17 ✅ |
| SQL 参数化 | 新 `[origin,user]` 二元组路径重跑 5 类 SQLi（`' OR 1=1--`、`'; DROP TABLE logins;--`、UNION、NUL+引号、反斜杠引号） | 全字面量匹配、表完整、0 误删 ✅ |
| U+2028 转义 | ensure_ascii=True 全仓未改 | ✅ |

## 新发现（RC6 起）

- **RC6【P3·实测 500】** `/api/theme` `web_favs[].ts` 浮点 `inf`（`1e999`/`Infinity`/`-Infinity`）→ OverflowError 500——RC3 修复不完整，server.py:1416-1418 except 缺 OverflowError。修法：对齐 `_web_session_clean`（+OverflowError）或直接复用 `_num` 语义。
- **RC7【P4·实测 500】** `/api/theme` `tftp_pane_h` `1e999`/`Infinity`/`-Infinity` → server.py:1630 裸 int() → 500（同族未修点）。
- **RC8【P3·候选，需真机确认】** `__webTabNew`（web-panel.js:658）无 scheme 守卫：web tab 内页面 `window.open(url)` → NewWindowRequested → `buildWebPanelTab(url,{newTab:true})` → REST create（本身无校验）→ cvw.Navigate。若 WebView2 对 file:/UNC 的 window.open 触发 NewWindowRequested 且 app-initiated Navigate 越过 web→file 限制（R2-W16 倾向成立），任意被浏览页面可让内嵌浏览器开本地文件/UNC。建议入口复用收藏点击同款 `/^https?:\/\//i`。javascript:/data: 经 window.open 引擎层拦（上轮已证 Navigate 不支持 javascript:）。
- **RC9【P4·琐碎】** `_pw_del_defer` 失败分支遗留 `pw_pending_del.json.tmp` 半截文件（RA5 原子写失败分支不清理 tmp）。
- **RC10【P4·琐碎】** `ts:10^400` 巨整数 200 落盘 → config.json 膨胀向量（上限 100 条×任意位数；建议钳 0..8e12 量级）。另 `ts` 5000 位数字串已被 CPython 4300 位限制兜成 ValueError→0（意外防住）。
- 琐碎注记（无编号）：web-panel.js:632 `t !== 'about:blank' && t !== 'about:blank'` 重复条件（疑本意含另一变量）；textContent 路径无安全影响。

## 修复建议汇总

1. RC6/RC7：两处 int() 的 except 补 `OverflowError`（同文件已有两处正确先例）；建议抽公共 `_safe_int(v, dft)`。
2. RC2 残余：`register()` create/nav 入口对 url 过与 `_web_favs_clean` 同款白名单（后端单点收口即同时覆盖 REST、恢复栈、`__webTabNew` 三链）。
3. RC8：`__webTabNew` 入口加 `/^https?:\/\//i`（即使后端收口也建议前端同拦给反馈）。
4. RC4 余项：挂起文件改 `ensure_ascii=True`（纯内部消费）；失败分支清 tmp。
5. RC10：ts 钳位。

## 探针存档

`D:\tmp\fc_redteam_c2\probes\`（保留供复核）：
- `p1_server.py`：服务端全矩阵（历史存量回读、19 条清洗绕过、17 条 ts、6 条 note、REST stub 录参 7 条、session 双向）——真实 Flask test_client + stub 管理器。
- `p2_node.mjs`：RC1 新面 17 类 + 旧面负控、fav 正则 26 条、`__webTabTitle` 22 类回归、esc 13 类。
- `p3_rc4.py`：RC4 原子写/独占锁挂起/精确删/flush 兼容/surrogate 全路径。
- `p4_extra.py`：config 完好性、tftp_pane_h 族、SQLi 回归。
