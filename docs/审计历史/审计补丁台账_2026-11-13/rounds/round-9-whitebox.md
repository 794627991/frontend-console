# R9 · 白盒对抗评审报告（D 批实施评审）

- **生成**：2026-11-13（R9 收尾）
- **对象**：基线 d9c8886 + R8 已合补丁 + D 批（D1 按用户修订口径 / D2 含追加门控修订 / D3=a / D6 / D7=a+c / D8）工作树，`git diff` 实测 **10 文件 +578/−125**（任务书所记 +542/−121 为追加门控修订前口径，以 `git diff --numstat` 为准）
- **性质**：对抗评审——只报告不修复；唯一写入本报告；git 仅 diff/log/show/grep
- **依据**：SUMMARY.md 台账 + patch-round-1（D1/D2/D3/D5/D6/D7）+ patch-round-2（D1'/D4'/D7）+ patch-round-3（D1''）+ patch-round-4（D8）+ R8 报告（W33-W35 已关闭、B25 已裁决）+ **用户 D1 修订口径**（正常模式工具 UI 本体不允许刷新；debug 刷新作用于全部 UI；网页 tab 自身刷新不受影响）+ **追加修改**（D2 的 9223 改 `_detect_cdp()` 门控 + `AreDevToolsEnabled=self._cdp`）
- **机械复核（独立重跑）**：`py_compile` 4 文件（main/web_tabs/web_proxy/devtools_cdp）✅、`node --check` 5 JS ✅、`USERPROFILE=$(mktemp -d) python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed** ✅

---

## 一、总体结论

D 批主体实现干净：**D1 修订口径代码级全符合、D8 生命周期穷举通过（W29 十步推演成立）、D3=a 单点收口成立、D7=a+c 正确、D2 追加门控与 a473/v3.4.99 口径一致**，epoch 端到端流完整，机械验证全绿，既有验收格抽 4 格代码级复核无回归。

发现 **2 个 P2 + 5 个 P3**：

| 编号 | 级 | 摘要 | 定性 |
|---|---|---|---|
| **W36** | P2 | **D6 未落盘**——全仓零 `errorhandler`，/api/* 的 404/405 仍为 Flask HTML | 拍板项缺失 |
| **W37** | P2 | **D2 的 9223 与主进程 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 结构性冲突**（启用模式该环境变量必含 9222；文档语义任一解读下 9223 均无法可靠到达网页 tab 进程；代码注释「显式 options 屏蔽环境变量继承」与文档相悖） | 实现有效性存疑，桌面实测裁决 |
| W38 | P3 | D2 对 mcp_server 五工具触达覆盖 3/5（evaluate 族无 webtab 回落） | 拍板目标部分达成 |
| W39 | P3 | `devtools_cdp.find_cdps` 零调用方（孤儿函数，W17 同族） | 死代码 |
| W40 | P3 | pagehide beacon 绕过 owner 仲裁 + `reset_session()` 无条件执行；REST 无 epoch → None=全回收与 D1'「无主不碰」口径相反 | 门控旁路/口径偏离 |
| W41 | P3 | 心跳 claim 竞态（双客户端同时 claim → ≤2s 双 owner 窗口）；localStorage 异常 fail-open | 设计内竞态记录 |
| W42 | P3 | D8 restore 消费分支不复位 `_webActivePid`（对照 back/fwd 分支与基线写入路径均有 display-guarded 复位）——巡检恢复路径（W15 场景）书签残留 | 新实现缺口 |

---

## 二、D1（用户修订口径）——代码级符合 ✅

### 2.1 正常模式禁整刷（三入口全封）

| 入口 | 实现 | 判定 |
|---|---|---|
| 浏览器级快捷键（F5/Ctrl+R/F12 等加速键） | main.py `:846` `AreBrowserAcceleratorKeysEnabled = bool(_wv_debug)`（on_loaded 回调内） | ✅ |
| 页面级 F5/Ctrl+R | web-panel.js `:812-821` capture keydown：`__HG_DBG__` 早退放行；正常模式 preventDefault + 激活 web tab → `_webAct('reload', c.wrap)`（阅读态=重取正文）否则吞 | ✅ |
| 右键菜单「重新加载」 | web-panel.js `:806` `if (!window.__HG_DBG__) { e.preventDefault(); return; }`——主 UI 文档全拦（含阅读/休眠态 .web-body 落主文档的右键=「web 上刷新刷掉整个工具」根因） | ✅ |

**作用域核验（任务点名）**：`AreBrowserAcceleratorKeysEnabled` 位于 main() 内嵌套回调（hunk 上下文 `def main():`），`_wv_debug` 在 main() `:1559` 赋值、回调在 `:1629 webview.start` 阻塞期间触发——闭包可达 ✅。副作用注记：该旗是全量浏览器加速键开关（不止 F5）——语义宽于用户令，WebView2 无细粒度等价物，记录不计缺陷。

**`__HG_DBG__` 注入链对照**：server.py `:449-463` `__HG_DBGF__` 占位符按 `DEBUG_WEB` 注入 `'1'`/`''`（带引号）→ index.html `:4` `window.__HG_DBG__ = __HG_DBGF__ === '1'`（严格字符串比较防裸 1）→ 两 handler 语义一致 ✅。

**网页 tab 自身刷新不受影响**：控件为独立 HWND+独立进程，控件内按键不达主文档 ✅；激活 web tab 时 F5 路由 `_webAct('reload', c.wrap)` → reader 态重取正文 / 普通 reload（`_webCtl` 单点收口 + owner 恒真）✅；休眠态 reload 作用 about:blank 无害（唤醒走 `_webRestore`）✅。`AreDevToolsEnabled=self._cdp`（web_tabs.py `:239`）落实 v3.4.99 终裁对网页 tab 同样成立 ✅。

### 2.2 pagehide → dispose_all(epoch) → reset_session

- **beacon（全模式）**：web-panel.js `:52-57`，`{act:'dispose_all', epoch: _webPageEpoch}`，sendBeacon 字符串体（R2 已核验 `get_json(force=True)` 可解析）✅。
- **`dispose_all(epoch=None)`**（web_tabs.py）：`_ctl` 按纪元 dispose + `_pending` 按纪元走 W24 取消路径（`_cancel.add`+`_pending.discard`+`_pend_nav.pop`+`_epochs.pop`）+ `reset_session()` ✅（D1'' 的 W24 空洞已闭合）。
- **`reset_session()`**：`_want_seq=0; _want=None; _pend_nav.clear(); _cancel.clear()` ✅。**与 `_HIDE_ALL` 交互**：reset 后 `_want=None` → `_apply_visibility` 幂等早退（不重排）；新页面 sq 从 1 起 > 0 无丢弃窗口 ✅。
- **`_epochs` 生命周期齐全性**（D1'' 清理补全三处）：create 登记 ✅、dispose pop ✅、A4'' 失败回收 pop ✅、dispose_all pending 清理 ✅。
- **epoch 端到端流**：`_webPageEpoch = Date.now()%1e8 + '-' + random`（D1'' 随机后缀采纳）→ portId/ctlId 带纪元（撞名/同毫秒双解）→ `_webNavigate` 的 create 带 epoch（初始 create 亦经 `_webNavigate`）→ beacon 按纪元回收 ✅。后端 create 的 `tab_id in self._ctl` 幂等路径不覆盖 `_epochs`（同页同纪元，无碍）✅。
- **口径偏离（并入 W40）**：D1' 修订「仅当 epoch ≥ 已见最大纪元才 reset」被简化为无条件 reset——单 owner 形态下（非 owner 不写）危害为零，随 W40 的 beacon 旁路一并记录；REST 层 `str(d.get('epoch') or '') or None` 把**无 epoch 请求映射为 None=全部回收**，与 D1' 「无 epoch 字段的旧调用按无主处理（不碰）」相反——当前唯一调用方（beacon）恒带 epoch，登记为口径偏离。

### 2.3 debug 全 UI 刷新

`webview.start(debug=_wv_debug)` + 加速键放行 + F5 handler 早退 → debug 刷新触发 pagehide beacon → 全模式回收 ✅（index.html debug-only beacon 未动，双 beacon 并存语义一致）。

---

## 三、D8 ——生命周期穷举 ✅（W42 一处缺口 + 观察项）

### 3.1 navSrc 生命周期（back/fwd）

| 环节 | 实现 | 判定 |
|---|---|---|
| 设置 | `_webAct('back'/'fwd')` → `c._navSrc = 'back'/'fwd'` 后发 `_webCtl` | ✅ |
| blank 清 | `__webTabUrl` about:blank 分支 `c._navSrc = null` | ✅ |
| navigate 清 | `_webNavigate` 入口 `c._navSrc = null`（用户导航优先） | ✅ |
| 对账消费 | back/fwd 分支：`expect = stack[idx+dir]`；**先清零后对账**——成功=指针移动（`idx+=dir`，display-guarded `_webActivePid` 复位 + 地址栏/标题更新），失败=已清零回落基线写入规则（同 host 替换栈顶/跨站 push，50 帽保持） | ✅ |
| restore 消费 | 先清零；栈顶对上（含空栈特例）→ 不动栈仅回填 `_ctlUrl`/地址栏；对不上 → 回落基线 | ✅ |
| **后端 no-op 的 stale 标记** | `go_back/go_forward`：`CanGoBack/CanGoForward` false → 无事件 → 标记滞留至下一事件；下次事件消费时对账成功则指针移动、失败则**已清零**回落写入 | ✅ 有界（影响限于栈簿记 W28 级，栈顶消费点恒正确） |

### 3.2 _blanked 生命周期

- sleep → `_blanked=true`（与 nav about:blank 同帧）✅；reader-ON → `if (!c._blanked)` 查重（防连点/休眠叠加堆叠多个 about:blank）✅；restore/reader-OFF 消费 → 置 false + `_navSrc='restore'` + `act:'back'` ✅；无 `_blanked` 回落 `Navigate(url)` ✅。

### 3.3 W29 十步推演（代码级）

B 激活 → sleep（native history `[…,B,about:blank]`，`_blanked=true`）→ 切回（switchTab `:443 _webActivePid=pid` 先置）→ wake → `_webNavTop` 跳脏 blank → `_webRestore` → `_blanked=false` + `_navSrc='restore'` + GoBack → SourceChanged(B) → restore 分支：url===栈顶本尊 → 不动栈、回填地址栏 ✅ **◀ 不落白屏**（下一 SourceChanged 走 back 对账：expect=stack[idx-1] 命中 → idx--）✅ **原生历史不膨胀**（无 B' 条目）✅。

**观察项 O1**：GoBack 恢复后 about:blank 仍留作 native 历史 **forward 条目** → 按 ▶ 一次落白屏（a556 过滤下前端不知情，再按走出）。较基线（◀ 落白 + B' 膨胀）改善，属 D8「GoBack 剔除」两案中未剔除条目的一案——手册回归格口径更新为「▶ 一次落白可走出、◀ 正常」。
**观察项 O2**：reader-ON during sleeping 查重成立（`!_blanked` 短路）；reader-exit during sleeping 的 `_webCtlVisible(true,false,c)` 显出控件仅程序化可达（休眠覆盖层挡按钮），switchTab 对 reader+sleeping 走全隐 ✅。
**W42（P3）**：restore 分支不复位 `_webActivePid`——巡检路径（`_webRestore` 取代了原 `_webNavigate(url, c)`，后者经 :490 复位）在 `_webActivePid` 陈旧时（W15 场景）恢复后书签残留 → 后续 `_webCur()` 族操作（F5 路由、无 wrap 的 `_webAct`）错靶。修法：restore 分支补 `if (c.wrap.style.display !== 'none') _webActivePid = c.portId;`（与 back/fwd 分支同款）。

### 3.4 SPA 上的 GoBack

`_webCtl(c,{act:'back'})` → 原生 GoBack（pushState 条目原生回退）→ SourceChanged 携实际 URL = 栈顶（栈顶本就取自 SourceChanged）→ 对账命中 ✅；重定向链对账失败回落基线写入 ✅（无死端：失败时 marker 已清）。

---

## 四、D2（含追加门控修订）——门控口径 ✅ / 9223 有效性存疑（W37）/ 覆盖 3/5（W38）

### 4.1 追加门控修订评审（三项逐答）

- **① `_detect_cdp` 与 main.py 口径一致性 ✅**：debug 分支 `from src.server import DEBUG_WEB` 与 main.py `:1559` 同源常量（install 在 `:853` 附近先于 `:1559`，自行导入读同一模块属性，值一致）；config 分支 `src.app_state.CONFIG_FILE` 同键 `web_cdp` 同读法；短路顺序（DEBUG_WEB 先判，命中即 True 不读 config）与 main.py `if not _wv_debug` 跳过 config 的**结果等价**（debug 下两者都开 9222/9223，config 值不影响结果）。矩阵：debug ON→9222+9223 双开；debug OFF+web_cdp ON→双开；全关→双无 ✅。
- **② cdp=False 功能面回归 ✅ 无**：阅读模式/收藏命名/发给 Claude 走 Flask `/api/web/fetch_text`（非 CDP）；导航/后退/前进/刷新/显隐/布局全走控件原生 API + ExecuteScriptAsync 事件推送（非 CDP）；`__webTabDead`/`__webTabNew` 等推送经 `_main_cvw` ✅。仅 AI devtools 触达缺失（=W4 基线现状，语义正确）。
- **③ D2 评审按门控更新**：见 4.2/4.3。

### 4.2 W37（P2）：9223 与主进程环境变量的结构性冲突（桌面实测裁决）

- main.py `:1596-1618` **无条件**导出 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`（合并外部值 + 四旗；且 `if _wv_debug or _web_cdp_cfg` → **9223 会被附带的两种模式（debug/web_cdp）下环境变量必含 9222**）。
- web_tabs `_ensure_env` 显式 `opts.AdditionalBrowserArguments`（四旗 + 条件 9223）。环境变量在 web tab 环境创建时仍在进程内（main.py 导出后未还原）。
- WebView2 文档对该交互的两代表述：环境变量**优先覆盖** options，或**追加**至命令行。任一解读下：覆盖 → 9223 丢失；追加 + Chromium 同名开关 last-wins（env 在后）→ **9222 胜出且被主 UI 先占** → 9223 失效。即 **9223 仅在环境变量恰好不含 9222 的模式才可能生效——而这与 D2 的启用条件（debug/web_cdp）恒互斥**。
- 代码注释断言「显式 AdditionalBrowserArguments 使本环境不再继承 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 环境变量（W1 纵深：参数完全确定化）」**与文档相悖**（该断言同时支撑 W1 纵深主张，实测一并裁决）。
- 失败形态优雅：`find_webtab_target` 抛 `TargetNotFound("9223 无可达网页 tab target…")` → 三工具回落报错，无回归；网页 tab 浏览功能不受损。
- **处置**：桌面验证手册已有 #1「D2 参数合并语义」条目——实测 `http://127.0.0.1:9223/json/version` 判定；若失效，修法=web_tabs `_ensure_env` 内临时 `os.environ.pop('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS')` → `CreateAsync` → 还原（loader 在 CreateAsync 内读 env；主 UI env 已建完，还原无副作用）。四旗与 9223 的注释措辞同步更正。
- 四旗本体（--disable-backgrounding-occluded-windows 等）两解读下均无害（与 env 同值去重/覆盖等值）。

### 4.3 W38（P3）+ W39（P3）

- **五工具触达矩阵**：console/screenshot/network 三工具经 `page_target_origin_probe` 回落链（origin 匹配失败 → `find_webtab_target()` 9223 首个非 blank 页面 target → `(port, tid, '')`，调用方解包 `_o` 弃用 origin——grep 核对 `:624/:693/:712` 三处均 `port, tid, _o` ✅ 兼容）→ **可达网页 tab**；`tool_devtools_eval`（:579）与 elements 扫描（:599）走 `devtools_cdp.evaluate()` → 内部直用 `find_cdp()`（9222）+ origin 匹配，**无 webtab 回落** → 仍仅主 UI。D2 触达覆盖 **3/5**——拍板目标部分达成，处置：evaluate 增补同款回落或登记为已知边界。
- **W39**：`find_cdps()`（:89-101）全仓零调用方——孤儿函数（W17 同族死代码）。处置：删除或由 web_cdp_live 探活扩 9223 时启用（见 4.4）。
- **D2 规格项 b 未实现**（登记）：D2-b「设置页 web_cdp_live 探活同步覆盖 9223」——server.py `_cdp_alive()`（:1347）仍 9222-only，settings.js 未动。与 W38 同批处置（可改用 `find_cdps()`——孤儿转正）。
- **9223 被占降级** ✅ 文档化（「与 9222 先占同款降级」，功能不受损）。

---

## 五、D3=a ——单点收口成立 ✅（W40/W41 两处边界）

- **_webCtl 单点收口**：前端 `/api/web/tabs` 触点穷举仅 2 处——`_webCtl`（:311，owner 短路）+ pagehide beacon（:53，**不经 owner**→W40）；后端 create/nav/back/fwd/reload/show/dispose/dispose_all/layout 全部经 REST 同一入口，无旁路 fetch ✅。非 owner 短路返回 `{ok:false, err:'second-ui-client'}`，调用方均 fire-and-forget 兼容 ✅。
- **buildWebPanelTab 非 owner 拦截**（banner + return null）：调用方（__webTabNew/顶栏/收藏恢复）不消费返回值 ✅。
- **owner 端零回归** ✅：claim 后恒 owner；owner 页面 setInterval 不受后台节流影响（主进程带 `--disable-background-timer-throttling`）✅。
- **W41（P3）**：claim 读-改-写无锁——双客户端同时首 claim 均读空 → 双写双 owner，靠 token 互斥在下一 2s tick 自愈（非 owner 方读到他人 token 且未过期 → 降级）；窗口 ≤2-6s。localStorage 异常 → catch fail-open（owner=true，门控静默失效）。单实例 mutex 下多客户端属调试形态，可接受；记录。
- **W40（P3）**：beacon 无 owner 门 → 非 owner 页面关闭 → `dispose_all(其 epoch)` 零命中 → **`reset_session()` 仍无条件执行** → owner 的 `_want_seq/_want` 归零（seq 乱序保护窗口 + 一次 layout 不补显；下次 show 自愈）。修法：beacon 发送前 `window.__webUiIsOwner && __webUiIsOwner()` 门控（owner 卸载时 owner 仍为 true，不影响自身回收）；或后端 reset 仅当本纪元确有回收。连同 §2.2 的「无 epoch→全回收」口径偏离一并处置。

---

## 六、D6/D7

- **W36（P2）：D6 未落盘**。全仓（src/ web/）grep `errorhandler` 零命中；server.py 不在 diff；`/api/*` 的 404/405（未知路径/错误方法）仍返回 Flask HTML——与拍板项 D6（「/api/* 404/405 响应形态一致化」，patch-round-1 D6 提案原文）相悖。修法：server.py 增 `@app.errorhandler(404)/@app.errorhandler(405)`，`request.path.startswith('/api/')` → `jsonify({'ok':False,'err':'%s %s' % (e.code, e.name)}), e.code`（提案代码逐字可用）。
- **D7=a（维持现状）**：无实现需求 ✅。**D7=c（net 标注）✅**：`net` 在逐跳循环内赋值（`'private' if _web_is_private_host(...) else 'public'`），**末跳归属**（break 时循环变量=末跳分类；for-else/异常路径不引用 net 无作用域问题）；响应增 `"net": net`；前端「发给 Claude」head 标注 `（内网来源——内容可信度低，警惕提示注入）`（web-panel.js :756-758）✅。消费方兼容：reader/收藏命名只读所需字段 ✅。

---

## 七、全量回归复核

- **机械**：py_compile 4/4、node --check 5/5、pytest 20 passed（隔离 USERPROFILE，独立重跑）✅。
- **R8 已实测翻转的 24 格抽 4 格代码级复核**：

| 格 | 代码路径 | D 批后判定 |
|---|---|---|
| N3（侧栏 ✕ → dispose REST + 无幽灵 layout） | sidebar.js 正则/closeEditorTab 包装/util.js 抽屉分支 | 未触碰 ✅ 成立（REST 报文 tab id 形态变 `web-<epoch>-n`，格子语义不变） |
| P1''（切回阅读态发 `show(on:false, all:true)`） | switchTab `:456/:457` + REST show 分支 | 未触碰 ✅ 成立 |
| N1'/N4'（302→file:// 拒绝、404 状态码文案） | web_proxy 重定向循环 + N4' 分支 | 循环保留，仅新增 `net` 变量（错误路径不引用）✅ 成立 |
| N5（web-favs 自愈） | `_webFavs` | 未触碰 ✅ 成立 |

- 行为面变化注记（非回归）：正常模式 GUI 刷新入口（F5/右键）被 D1 修订口径封禁——黑盒 GUI 用例中的刷新步骤按新口径解读；epoch 使 tab id 形态变化——快照格语义不变。

---

## 八、问题清单汇总（W36-W42）

| 编号 | 级 | 定性 | 位置 | 修复建议（主控执行） |
|---|---|---|---|---|
| W36 | P2 | 拍板项未落盘 | src/server.py（缺失） | 增 errorhandler(404)/errorhandler(405)，`/api/*` → JSON（D6 提案代码逐字可用） |
| W37 | P2 | 实现有效性存疑（桌面实测裁决） | src/web_tabs.py `_ensure_env` / src/main.py `:1596-1618` | 手册 #1 实测 `/json/version@9223`；若失效：`_ensure_env` 内临时 pop env var → CreateAsync → 还原；更正「不再继承环境变量」注释 |
| W38 | P3 | 拍板目标部分达成 | src/devtools_cdp.py `evaluate` | evaluate 增 webtab 回落（复用 `find_webtab_target`）或登记已知边界 |
| W39 | P3 | 死代码 | src/devtools_cdp.py `find_cdps` | 删除，或供 `_cdp_alive` 扩 9223 探活时转正（D2-b） |
| W40 | P3 | 门控旁路/口径偏离 | web-panel.js `:52` beacon / web_tabs.py `dispose_all` | beacon 前置 owner 门；后端 reset 仅当本纪元确有回收；REST 无 epoch 语义与 D1' 对齐（不碰）或文档化为 panic 语义 |
| W41 | P3 | 设计内竞态 | web-panel.js `:21-40` 心跳 | 记录（claim 原子化可用 localStorage 版本号比对或 BroadcastChannel；调试形态下收益有限） |
| W42 | P3 | 新实现缺口 | web-panel.js restore 消费分支 | 补 `if (c.wrap.style.display !== 'none') _webActivePid = c.portId;` |

**观察项（不计缺陷）**：O1 forward-blank 历史残留（▶ 一次落白可走出）；O2 reader×sleeping 叠加仅程序化可达；O3 stale navSrc 影响有界（消费时先清零）；O4 `AreBrowserAcceleratorKeysEnabled` 全量加速键面；O5 epoch 使 REST tab id 形态变化（快照语义不变）；O6 D1' epoch 门控简化为无条件 reset（单 owner 下无害，随 W40 处置）；O7 numstat 实测 +578/−125（任务书 −121/+542 为追加修订前口径）。

---

## 九、结论

- **D1（修订口径）代码级全符合**（三刷新入口封禁/作用域可达/`__HG_DBG__` 注入链一致/网页 tab 自身刷新不受影响）；**D8 生命周期穷举通过**（W29 十步成立，W42 一处复位缺口）；**D3=a 单点收口成立**（W40/W41 边界）；**D7=a+c 正确**；**D2 追加门控与 a473/v3.4.99 口径一致、cdp=False 零回归**——但 **9223 有效性受主进程环境变量结构性制约（W37），桌面实测裁决**。
- **机械验证全绿**（py_compile 4 / node --check 5 / pytest 20，独立重跑）；**既有验收格抽 4 复核零回归**。
- **移交主控**：W36 直接补实现；W37 归桌面手册裁决（附修法）；W38-W42 按 P3 批次处置；观察项 O1 归桌面手册回归格口径更新。
