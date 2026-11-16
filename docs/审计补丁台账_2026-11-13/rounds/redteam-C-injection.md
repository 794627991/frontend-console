# Redteam C · 注入专项（网页 tab 域）——2026-11-16

- 基线：HEAD `480c07d`（v4.1.0-a583）。工作树存在他人并行改动（server.py api_connect/api_recent、util.js/sidebar.js 的 shell tab 档、index.html），经 `git diff` 核对**均不触及本报告涉及代码**；`src/web_tabs.py`、`web/js/web-panel.js`、`src/web_proxy.py` 干净与 HEAD 一致。
- 方法：每条 payload 实际注入并观察（node 24 eval/DOM 桩、Python 3.14 sqlite/Flask test_client），记录「注入了但无害」与「注入且可利用」的区分。
- 纪律：仓库零改动（本报告除外）；git 只读；真实 Chromium 密码库（Login Data）一字未碰——SQL 实测全部指向临时复刻库；探针存 `D:\tmp\fc_redteam_c\probes\`（p1~p11）。
- 确凿发现：**5 条**（RC1 注入成立·潜伏 / RC2 防线旁路·端到端 / RC3·RC4·RC5 健壮性实测）。

---

## RC1【P2·注入成立、当前数据源潜伏】诊断推送面：json.dumps 输出被嵌进**单引号** JS 字面量

- 位置：`src/web_tabs.py:740` 与 `:769`（suspend 失败诊断 → 工具主 UI console）：
  `"console.warn('[web-tabs] suspend: %s')" % json.dumps(";".join(diag))`
- 根因：`json.dumps` 只转义 `"`/`\`/控制字符，**不转义 `'`**；而 `%s` 恰落在单引号字面量内 → 数据含 `'` 即提前终止字面量，余文成为代码。
- payload：`'); alert(1); ('` → 生成
  `console.warn('[web-tabs] suspend: "'); alert(1); ('"')`
- 实测（node p4/p5）：`alert(1)` 真实执行（桩内 `executed=[1]`；变体报 `alert is not defined` = 调用已发生）。对照面：双引号 `window.__webTabTitle(%s, %s)` 形态 98 条对抗 payload（U+2028/2029、`\` 结尾、NUL、`</script>`、反引号 `${}`、`%s%n`）**97/98 编译执行、参数全部以数据形态到达、0 逃逸**——唯一失败即本条单引号面（`quote` payload 语法错）。
- 危害评估：`diag` 当前全部为内部诊断串（`%r` 异常文本、枚举态标记），页面/用户可控数据暂不可达 → **潜伏注入**（一次重构让 diag 携带 tab 名/URL 即转活）。同型历史代码（a578 :716/:745）已存在，非本轮新引入。
- 修复建议：`"console.warn(%s)" % json.dumps("[web-tabs] suspend: " + text)`——整个文案作为唯一 JSON 字符串参数，杜绝引号语境混用。

## RC2【P1→P2·端到端实测】收藏/会话恢复/REST 三条入口绕过 scheme 拦截线（file:/UNC 进内嵌浏览器）

W16/A10'' 拍板的 `file:/javascript:/data:/vbscript:` 拦截**只覆盖地址栏入口**（`_webNormUrl`）。以下入口全部不经过它，实测旁路成立：

1. 服务端收藏清洗无 scheme 白名单：`src/server.py:1408-1410` `_web_favs_clean` 对 url 只查非空+≤2048。实测（p11，真实 Flask test_client）：
   `POST /api/theme {"web_favs":[{"url":"file:///C:/Users/victim/考核明细.xlsx","title":"会议纪要","ts":1}]}` → 200；`GET /api/theme` 原样回读 `file://…` 与 `file://nas-server/share/工资表.xls`。
2. 前端收藏消费不过 `_webNormUrl`：`web/js/web-panel.js:1292` 点击收藏 → `buildWebPanelTab(f.url,{newTab:true})` → `_webNavigate` 直发后端；启动种子（:183-199，`(cur.length?cur:srv)`）只过滤 `typeof url==='string'`。
3. 后端 `/api/web/tabs` create/nav 对 url **零校验**：`src/web_tabs.py:478` `cvw.Navigate(url or "about:blank")`（nav 同 :598）。REST 层无任何 scheme 检查（p11 实测请求穿透到控件管理器层，探针环境无控件装配故止于 env 错误；app-initiated `Navigate(file://)` WebView2 放行——R2-W16 已证「控件无 file 限制」）。
4. 本地 localStorage 会话恢复过滤器（web-panel.js:71-80）同样只挡 `about:blank`：实测 `file:///C:/Users/v/secrets.html` 与 `javascript:alert(1)` 均入 `_webSavedNav` 恢复栈（p10）。
- 完整攻击链（收藏路）：无鉴权本地进程读 `%HOME%\.serialconsole_pro\endpoint.json` 得端口（main.py:145-160 明文落盘）→ POST `/api/theme` 塞伪装标题的 file:// 收藏 → 重启后端口必变、localStorage 必空（main.py:957 free_port）→ 服务端种子回填 → 收藏菜单显示诱导标题 → 用户一次点击 → 内嵌 WebView2 打开本地文件/UNC 共享（内网侦察+钓鱼 UI）。CSRF 变体（工具 web tab 内的恶意页 fetch 本机端口）受 Chromium PNA 不确定性约束，作次要触达注记。
- 引擎边界实测/核对：`javascript:` 在 `cvw.Navigate` 不支持（异常被 :599 吞）；顶层 `data:` 被 Chromium 拒——故 javascript:/data: 收藏是死端，**file:/UNC 可用**。
- 修复建议：消费端统一收口——收藏点击/种子回填/恢复/REST create/nav 四处对 url 过 `_webNormUrl` 或后端等价白名单（`^(https?|about):`），与服务端 `_web_session_clean`（已正确白名单，实测 file:/javascript: 全拒）对齐。

## RC3【P3·实测 500】`web_favs[].ts` 非数值 → `/api/theme` 未捕获异常

- 位置：`src/server.py:1413` `"ts": int(it.get("ts") or 0)`；POST 侧 :1613-1616 无 try。
- payload：`{"web_favs":[{"url":"http://a/","ts":"abc"}]}` → **实测 500**（ValueError，真实 traceback 1616→1413）；`ts:{"x":1}` 同 500（TypeError）。`ts:true/1.5/null` 正常。
- 危害：单请求拒绝服务 + 错误日志噪音；崩溃发生在 `_save_config` 之前，config 未损坏（实测回读完好）。
- 修复：参照同文件 `_safe_cfg_int` 钳 0。

## RC4【P3·实测数据丢失】`pw_del` origin 含 lone surrogate → 挂起删除文件被截断清空

- 位置：`src/web_tabs.py:177-190` `_pw_del_defer`：sqlite 绑定 lone surrogate（JSON 入参合法，如 `"\ud800…"`）失败 → 落挂起分支 → `json.dump(..., ensure_ascii=False)` 写 UTF-8 时 `UnicodeEncodeError`。
- 实测（p7，临时复刻）：异常被吞、函数静默返回「已标记删除」，但 `open(p,"w")` 已先截断文件 → **先前挂起的全部删除记录丢失**（重载恢复 0 条）；该条删除也永不生效。
- 危害：功能完整性缺陷（删除假成功+历史挂起清零），非注入、非跨域。
- 修复：`ensure_ascii=True`（挂起文件纯内部消费，无需非 ASCII 原文）或逐条 try 隔离。

## RC5【P4·琐碎】cleaner 口径不对称

- `_web_session_clean`/`_web_favs_clean` 接受含 NUL 的 `http://a\x00b`（startswith http:// 即过，实测）；`HTTPS://UP`（大写 scheme）反被拒（startswith 大小写敏感，实测）——前端 `new URL` 大小写不敏感，两端口径不对称；到达后端仅成垃圾导航（引擎层拒），无注入面。随 RC2 修复顺手归一即可。

---

## 已防住的面（本轮实测，含防法）

| 面 | 防法 | 实测 |
|---|---|---|
| HTML/attr 注入（收藏菜单 title/`data-fav-i`、pw 菜单 title、行内编辑 value、reader 正文/标题、tab label、侧栏 name/desc/title、抽屉/溢出列表、ctx 菜单、notify） | `esc()`（util.js:1257，&<>"' 全转义）+ 大量 textContent；抽屉/溢出 `esc(lbl)`（util.js:443/706）、ctx `esc(it.label)` | 13/13 对抗 payload（`<img onerror>`、`"><script>`、attr 逃逸、反引号模板、`</div>`、U+2028、`\`、NUL、300 字符）转义后零危险字符残留（p10） |
| ExecuteScriptAsync 双引号面（`__webTabTitle/Url/Hist/New/Dead/Shot`、main.py `__newWindow`） | `json.dumps` 默认 ensure_ascii=True → U+2028/2029 变 `\uXXXX` 合法转义；`"`/`\`/NUL/控制符全转义 | 97/98 条编译执行成功、payload 以数据形态到达（p2/p5）；`%s%n` 在 console 单参数下不发生格式化（p2） |
| SQL 注入（pw_del/pw_del_flush/pw_reveal） | sqlite 全参数化 `?` | `' OR 1=1--`、`'; DROP TABLE logins;--`、UNION、宽字节、NUL 全按字面量匹配：0 误删、表完整、UNION 无命中（p6） |
| 挂起删除 JSON 文件 | json.dump/load 往返 | 引号/换行/NUL/U+2028/5000 字符无损往返（lone surrogate 见 RC4）（p7） |
| 会话恢复服务端种子 | `_web_session_clean` scheme 白名单 http(s) + idx 钳制 | file:/javascript: 全拒；idx 脏值（字符串/1e18/-5/inf/bool）全钳 0（p9/p11） |
| 地址栏 `_webNormUrl` | 显式 scheme 黑名单 + http 补全 | javascript:（大小写/前导空白）、data:、file:、vbscript: 全拦；`java\tscript:` 变体落 http:// 前缀后引擎层再拒（端口非数字）；`//evil`、UNC 补前缀后引擎层拒；`http://evil@127.0.0.1` userinfo 形态可达本机但仅涉地址栏防钓鱼（p10） |
| fetch_text | file:// 起点拒、逐跳白名单、5MB/40K 上限、错误内敛 | R2 已黑盒实测；本轮复核代码无回归 |
| base64 loader / eval / WebMessage 桥 / `_pw_fill_script` / `__PID__` 替换 | a579（021e93f）整体移除 | HEAD 全仓无引用（grep+git 实证）；a578 历史实现中 loader 内层为静态代码（无页面可控数据）、`PostWebMessageAsJson(json.dumps(...))` 用法正确——任务清单所列攻击面在 HEAD 已不存在 |
| JSON 深嵌套/`__proto__` | 前端 JSON.parse 全 try 兜底；服务端 cleaner 白名单重建对象（无合并 sink） | 深嵌套解析层 RecursionError 不入业务；`__proto__` 键被 cleaner 丢弃（p8/p9） |
| `__webTabShot` backgroundImage | 属性赋值（非 HTML sink）+ json.dumps 单参数 | 数据形态到达（p2） |
| `__fcDiag` 诊断通道 | 返回 `JSON.stringify` 字符串 | 无格式串/注入放大（p2） |

## 任务清单逐条核销

1. 收藏夹：备注/标题/URL → localStorage/菜单渲染 esc 全防；`data-fav-i` 数字索引不可注入；web-session→`/api/theme` 回显 → **RC2**（服务端无 scheme 白名单+消费端不过 `_webNormUrl`）。
2. 密码管理器：origin/user 渲染 esc 全防；`nm.textContent`/`dataset` 安全；pw_del origin → SQL 参数化全防（p6）；挂起 JSON → RC4（lone surrogate 截断）；WebMessage 注入面已随 a579 移除。
3. ExecuteScriptAsync 拼接面：`_pw_fill_script`/`_pw_form_helper`/`__PID__` **HEAD 已不存在**（a579 移除）；现存 `__webTabTitle/Url/New/Dead` 推送 json.dumps 全防（U+2028 实测转义）；**RC1**（diag 单引号面）。
4. 灵动岛/地址栏：`_webNormUrl` 黑名单实测稳固；label 只进 textContent/esc（`${ICO16}` 模板串内全部 esc）；web-session 服务端段白名单防住——旁路同 RC2（本地段过滤器只挡 about:blank）。
5. base64 loader eval 面：已移除，历史实现内层无页面可控数据（git 实证），无放大器。
6. `__fcDiag`/console.debug：返回 stringify 字符串、console 单参数字面量；`%s%n` 不发生格式化；RC1 为唯一例外（suspend/warn 面的引号语境混用）。

## 探针存档

`D:\tmp\fc_redteam_c\probes\`：p1/p5（ExecuteScriptAsync 面 98+12 条生成）、p2/p4（node eval 桩）、p3（diag 逃逸串）、p6/p7（sqlite 参数化+挂起 JSON，临时库）、p8/p9（cleaner 对抗矩阵）、p10（esc/_webNormUrl/恢复过滤器，源码自仓库实时提取）、p11（真实 Flask test_client：RC2 往返、RC3 500、pw 面 SQLi）。临时目录已清理。
