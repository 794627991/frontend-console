# 内嵌浏览器（路线 A）白盒对抗审计 · 第 2 轮

- 基线：d9c8886（v4.1.0-a556）未变；输入材料：`round-1-whitebox.md`（自产）、`round-1-blackbox.md`（首次研读）、`patches/patch-round-1.md`（A1–A12 / D1–D6 / C 提案）
- 方法：补丁 diff 逐条对抗推演（含并发时序、调用点全量核对、守卫链推演）+ R1 存疑区逐条复核 + R1 未深挖面狩猎 + 关键主张的运行时实验（urllib 重定向/控制字符、`list(d.items())` 20 万次并发压测、CPython use-before-global 编译行为、tray.py AST 验证）
- 铁律遵守：未改任何代码；pytest 隔离 USERPROFILE

---

## 一、补丁对抗评审（A1–A12 逐条 + D 系评注）

### A1（删 `--disable-web-security`）—— 干净
全量回归面核查：`web/js` 无任何 iframe 创建点（grep 实证）；工具 UI 自身只做同源 `/api/*` 请求；`ExecuteScriptAsync` 事件推送不依赖同源策略；pywebview `IGNORE_SSL_ERRORS`/`ALLOW_FILE_URLS` 是独立机制。`_wv_args` 去项后 R24-3 去重逻辑（`_have_keys`）不受影响。无新面。

### A2（`_is_loopback` 按 hostname 判定）—— 干净
对抗形态逐一过：`http://127.0.0.1.evil.com` → hostname=`127.0.0.1.evil.com` 不在元组 → 拦截 ✓；`http://127.0.0.1@evil.com/`（userinfo 欺骗，旧子串判定同样中招）→ hostname=`evil.com` → 拦截 ✓（顺带修复 R1 未列形态）；`http://[::1]:8080/` → hostname=`::1` ✓；`urlsplit` 异常路径 → except 返回 False → 拦截（安全侧）。工具自身 URL `http://127.0.0.1:<port>` → 放行语义与原先一致。无新面。

### A3（`_cancel` 弃建）—— 双发去重路径核验通过；未发现可触发的毒化
任务点名的场景逐一推演：
1. **create 双发（`_pending` 去重）× dispose 在途**：create#1 → `_pending.add`；create#2 → `_pend_nav[t]=url2`；dispose → `elif t in _pending` → `_cancel.add` + `_pending.discard` + `_pend_nav.pop`（url2 正确随葬）→ `_build#1` 命中 cancel → 消费并返回，无孤儿 ✓。
2. **create→dispose→create（同 tab_id 三连）**：BeginInvoke FIFO 保证 `_build#1`（消费 cancel）先于 `_build#3`（正常建）执行——cancel 恰好被「它要取消的那一次 build」消费一次，不存在把后发 create 误杀的窗口（曾怀疑的毒化场景在 FIFO 下均自愈）。
3. 残留小瑕疵（不计新号）：dispose 的 cancel 分支不清 `_want`/`_want_seq`——被取消 tab 若恰是最近 show 意图，下一次 layout 到达时 `_apply_visibility` 找不到该 tab → 其余控件全藏（R1 已述的既有边缘，非 A3 引入）。
4. `_cancel`/`_pending` 跨 Flask/UI 线程的 set 原子操作无损坏风险。

### A4（`__webTabDead` 失败回收）—— **引入新问题，见 W14**
前端侧核验（任务点名的重入问题）：`Object.values(connections).find(...)` 是同步遍历，find 返回后才调 `closeEditorTab`；web conn 无 `dirty` → 跳过确认弹窗 → `_edCloseNow` 同步执行且 `delete connections[conn.portId]`（editor.js:1513）——无遍历中重入问题 ✓。`showBanner` 走 esc，`err` 文本无注入 ✓。后端侧 pop/discard/`_ui(_rm)` 均安全；**但 `m.ExecuteScriptAsync` 在池线程直调——见 W14**。

### W14【P2·补丁引入】A4 的失败推送违反 a549 线程亲和铁律，真实失败场景下修复自失效
- 位置：patch-round-1.md A4 diff（`src/web_tabs.py` `_init_done` 失败分支）：`m = self._main_cvw; if m: m.ExecuteScriptAsync(...)` 直接写在 ContinueWith **线程池回调**里。
- 依据：a549（34a9dcd）实锤该形态——ContinueWith 回调中访问 CoreWebView2 成员抛 InvalidOperationException，项目为此专门「全部归 UI 线程」。A4 把推送放在池线程：①违反项目自证的铁律，最坏情形未定义行为；②异常被 `except Exception: pass` 吞掉 → **`__webTabDead` 永不送达** → W13 要修的「tab 假活」在最需要它的失败路径上原样保留（A4 的 `_rm` 走了 `_ui`，控件回收生效，但前端无感知）。
- 修复方向：推送体（含 `_main_cvw` 取值）整体挪进 `self._ui(...)` 闭包。

### A5（就绪前 navigate 转 `_pend_nav`）—— 干净（任务点名的叠加推演无丢 URL）
与 create 双发「末次胜出」的两种到达顺序均推演：
1. `create(t,url1)` 在途 → `navigate(t,url3)`（`_go` 经 `_ui` 先于 `_on_ui` 执行）→ `_pend_nav[t]=url3` → 初始化完成 `_on_ui`：`Navigate(url1)` → pop 得 url3 → `Navigate(url3)`——末次胜出 ✓。
2. `_on_ui` 先执行（pop 时为空 → Navigate(url1)）→ `_go` 后执行：此时 CoreWebView2 已就绪 → 直 Navigate(url3) ✓。
两种顺序都无丢失；`_pend_nav` 的三方写入（Flask 线程 create 去重、UI 线程 `_go`、UI 线程 `_on_ui` pop）均为原子 dict 操作，last-writer-wins 语义正确。附带观察（不计号）：正常关 tab（ctl 已存在）路径不清 `_pend_nav`，A5 会使迟到条目多留一个字符串——dispose 后 `_go` 对已 Dispose 控件的访问被 except 捕获，无实害。

### A6（`_num` 收口）—— 干净（任务点名的三形态逐一核验）
- `1e308`：`float` 有限 → `int` 得 Python 大整数 → `System.Drawing.Rectangle(1e308,…)` 由 pythonnet 转换抛溢出 → 被 `layout._apply` 的 try 捕获（WARN），`_rect` 被污染但**下一次合法 layout 先重写 `_rect` 再 `_apply`，自愈**；无 500、无崩溃。
- `Infinity`/`1e400`：inf 检查/`OverflowError` → 回落 dft ✓。
- 嵌套对象/None/非法串：`float({...})`/`float(None)` → TypeError → dft ✓；`"1e2"` 等数字串被新接受（从 500 变为生效，良性放宽）。
- `on` 解析：`"false"→False`（修复达成）；`0→False`、`1→True`、`"TRUE"→True` 与旧语义兼容或改善；`None→False` 与旧 `bool(None)` 一致。
- 附带发现（不计号）：`sq` 缺省/0 时绕过 seq 门禁是**基线既有行为**（`d.get("sq") or 0` → `if sq:` 假），任何本机客户端可借此旁路乱序保护——归入 W8 语境，非 A6 引入。

### A7（`_SINGLE_KINDS` 移除 `'web'`）—— 干净
下游核查：抽屉分组用 `_GROUP_LABEL.web`/`_GROUP_ICON.web`（util.js 均已定义）；`switchTab` 包装器与 `_webCtlVisible` 不依赖平铺假设；进抽屉=后台 tab，10 分钟休眠计时照常工作（语义正确）。`sortKeyFn` web 桶 [8] 与 `_GROUP_ORDER.web=7` 的错位为基线既有，不受影响。

### A8（`_webNavigate` 显式目标）—— 修不干净，见 W15

### W15【P3·补丁修不干净】A8 只覆盖 3/6 个调用点，1s 唤醒巡检仍会跨 tab 恢复 URL
- 位置：`web/js/web-panel.js` 的 `_webNavigate` 调用点全量 6 处：:103、:175、:221、:230、:433、:495；A8 仅改 :175（地址栏）、:230（会话恢复）、:433（switchTab 唤醒）三处，补丁自述「调用点修正（3 处）」掩盖了缺口。
- 依据：:495 的 1s 兜底巡检（注释自述覆盖「display 变化不经 switchTab 的路径」）唤醒的是遍历中的 `c`，却调用 `_webNavigate(url)`（回落 `_webCur()`）——在 `_webActivePid` 为 null/陈旧（该巡检存在的非 switchTab 场景恰易如此）且存在多个网页 tab 时，`_webCur()` 按字典序回落第一个网页 conn → **URL 恢复进错误 tab**（B1 的同型残留）。:103/:221 两处紧随 `switchTab` 之后，`_webCur()` 恒等于目标，安全。
- 修复方向：:495 一并传 `c`（补丁再补一处）。

### A9（空 URI 降级）—— 干净
`u = str(a.Uri or "") or "about:blank"` → 恒真 → 推送 `__webTabNew("about:blank")` → 开空白新 tab（浏览器语义）；推送失败降级 `Navigate("about:blank")`。现有两条 `_on_new_window` 测试用例（非空 URI）不受影响。

### W16【P3·补丁行为变更未拍板】A10 scheme 白名单把 `file:` 放进地址栏直达通道
- 位置：A10 diff（`_webNormUrl`）：`/^(https?|file|ftp|about|mailto|javascript|data|ws|wss):/i` 全部原样放行。
- 依据：旧行为对 `file:///C:/Windows/win.ini` 补 `http://` 前缀（垃圾导航，无害）；新行为把它原样送进 `_webNavigate` → 后端 `Navigate('file:///...')`——WebView2 控件无 file 限制（`ALLOW_FILE_URLS` 是 pywebview 主窗设置），内嵌浏览器成为本地文件/UNC 共享（`file://server/share`）查看器。补丁文档只对 `javascript|data` 留了「一行取舍」的产品决策点，`file:` 未入讨论。触发=用户手输（收藏/会话恢复/`__webTabNew` 链路的 file: 均被 Chromium 渲染层拦截，不可达），风险有限但属未拍板的行为变更。
- 修复方向：白名单收窄为 `https?|about`，`file/javascript/data` 显式拦截并提示。

### W17【P3·补丁文档事实错误】A11 两处失实
- ①补丁注「`import threading` 仍被其他处使用，保留」——grep `src/web_tabs.py` 全文件，`threading` 唯一使用点是 :23 的 `_lock = threading.Lock()`；A11 删 `_lock` 后 `import threading` 成孤儿导入（与所删死代码同类）。
- ②A8 的「调用点修正（3 处）」——实际 6 处、遗漏 1 处实质缺口（W15）。
- 修复方向：A11 一并删孤儿 import；A8 补 :495 后更正计数。

### A12（设置页文案）—— 干净（纯文案）。

### D1（pagehide 回收 + seq 握手 + 纪元前缀）—— 方向正确；守卫通过性成立；时序与爆炸半径见 W20
- **守卫推演（任务点名）**：`sendBeacon` 以字符串体发送 → Content-Type `text/plain`；`_guard_local_origin`：同源 POST 的 Origin（`http://127.0.0.1:<port>`）命中 `_own` 放行（即便无 Origin 头也放行）；JSON 顶层守卫对 text/plain 同样 `force=True` 解析 → dict → 通过。`api_web_tabs` 的 `get_json(force=True)` 与守卫共用 Flask 缓存，不消费两次 ✓。守卫侧无障碍。
- `dispose_all` 返回 None → `jsonify(None)` → `null`/200，beacon 不读响应 ✓。纪元前缀 `web:<epoch>:<n>` 保持 `startsWith('web:')` 的 `sortKeyFn`/分组兼容 ✓。
- **W20【P3·补丁未提的时序】**：pagehide 的 beacon 与新页面的首批 `create/layout` 之间存在浏览器侧乱序窗口——beacon 迟到时会 **dispose_all 杀掉刚重建的 tab 并把 `_want_seq` 归零**（下一次 show 反而因 seq 大于 0 而正常，但已建控件被错杀）。叠加 D3 承认的多客户端爆炸半径（任一客户端刷新=全体回收）。修复方向：`dispose_all` 带 page 纪元令牌，后端只回收匹配纪元的控件（与 D1-3 的 epoch 前缀天然配套），或 beacon 改带「本页创建的 tab 列表」精确回收。

### D2/D3/D6 评注（方案级，无 diff 可攻）
- D2 的「显式 options 屏蔽环境变量继承」顺带构成 W1 的纵深防御——方向正确；但需注意显式 `AdditionalBrowserArguments` 会**顶掉**而非合并 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`（若该假设不成立，9223 与 9222 的端口冲突回到原点）——落地时需实测一次参数合并行为。
- D3 的「反向收紧：检测第二 UI 即拒绝」与 D1 的全局 dispose_all 冲突已在文档自我标注，维持。
- D6 errorhandler 方案与现有 JSON 口径一致，无面。

---

## 二、R1 存疑区复核（逐条：升级 / 关闭）

1. **CDP 9222 先占方向** → 维持存疑。机制链（独立 UDF=独立进程、同环境变量双注入、`find_page_target` origin 过滤）三环都有代码实证，唯「主 UI 先绑 9222、web tab 进程绑失败后静默继续」未经运行时验证。D2 落地（9223 显式端口）后此疑点自然消解。
2. **`javascript:`/`data:` 经 NewWindowRequested 的真实行为** → 维持存疑（需运行时）。注意 W16 使地址栏也加入放行面后，该实测的优先级上升。
3. **web-session 单槽互覆盖** → 关闭：代码层面确认为设计取舍（`_webSessionSave` 只存 `_webCur()`），多客户端场景归 D5 处理，不构成独立缺陷。
4. **`_cdp_alive` 不校验身份** → 关闭：代码确认探活只看 9222 有无 `/json/version` 200，第三方占用会误报「AI 可用」——无害级显示问题，记录即止。
5. **密码自动填充** → 关闭：凭据由 Chromium 密码管理器管理（DPAPI 按用户加密，UDF `%LOCALAPPDATA%\fc_webview_tabs`），按 origin 隔离无跨站填充；与用户本机装 Chrome 同级风险。唯一关联提醒已并入 W5 语境（孤儿控件带登录态驻留）。
6. **fetch_text 设计内 SSRF** → 部分升级为确凿 **W18**（证书校验全局关闭），其余维持设计取舍。
7. **overlay 联动点击放大** → 关闭：确认为纯性能/噪音项（每次点击一次 `show(true)` REST），无正确性影响；seq 加速副作用已在 W3/D1 语境记录。
8. **create env 等待 5s** → 关闭：threaded=True 下仅占请求线程，无服务级影响。
9. **W10「`list()` 快照非原子」** → **核伪关闭**。论证 + 实验：
   - C 层论证：`list(d.items())` 在 CPython 是单个 eval-loop 调用；dict 视图迭代纯 C 实现（`dictiter_iternext`），途中无 Python 回调、无 GIL 释放点；eval-breaker（线程切换检查点）只在字节码间生效 → 单次调用内不可被其他线程插入。
   - 实验：200k 次 `list(d.items())` 并发 200 键 dict 的持续增删，零 `RuntimeError`。
   - 结论：a555 注释声称的「list 快照防 dispose 竞态」针对的崩溃形态在 CPython 下本就不存在；W10 的成立部分只剩 `_lock` 死定义（A11 清理）与逻辑竞态（A3/A5 已补）。patch-round-1.md C 表的「部分核伪」判断正确。

---

## 三、新面狩猎（R1 未深挖面）

### W18【P3】`/api/web/fetch_text` 对所有 https 关闭证书校验，超出其自述的「内网自签」范围
- 位置：`src/web_proxy.py:82-85`：`ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE`；docstring（:69）只主张「内网 https 自签不校验（本地单用户工具语境）」。
- 依据：该 context 无差别用于**一切** https 取页——阅读模式/收藏命名/发给 Claude 对公网站点的取页全程不验证服务端证书：网络中间人可向阅读视图投喂任意「正文」、向「发给 Claude」注入受控文本（提示注入通道）、向收藏塞伪标题。升级自 R1 存疑 6（其余面维持设计取舍：起点 scheme 白名单有效、内网探测属工具语义）。
- 修复方向：默认 `create_default_context()`，仅对私网地址（RFC1918/回环/主机名解析为私网）回落不校验；或配置开关。

### W19【P3】`_safe_load` 非 http(s) scheme 直落 `_orig_load`：工具 UI 内 `file:` 链接可把主窗口导航到本地文件
- 位置：`src/main.py:810-816`——`_safe_load` 只对 `http(s)://` 走外链路由，**其余 scheme 无条件 `return _orig_load(url)`**。
- 依据与触发：主 UI 文档内 `target=_blank` 且 `href="file:///C:/..."` 的链接（Claude 回复渲染的链接、日志/笔记内容）→ pywebview `on_new_window_request` → `load_url` → `_safe_load` → 非 http(s) → 主窗口整页导航到该本地文件（工具 UI 被替换；file:// 页在 A1 修复后受同源策略约束，读 API 链不成立，危害限于 UI 劫持/钓鱼）。A2 只修了 http(s) 分支内部的回环判定，非 http(s) 的兜底放行原样保留。此 wrapper 属本次 diff 范围（a484/a489 引入）。
- 修复方向：`_safe_load` 对非 http(s) scheme 一律吞掉（Handled）并提示，仅放行工具自身 origin。

### 其余狩猎项（未发现新问题，证据见文末清单）
- `devtools_cdp.py` 全文 + main.py 挂接：无注入面；`suppress_origin=True` 是 CDP 握手必需；`ENDPOINT_FILE` 由 main.py 启动期写入（main.py:156），stale 时走 `TargetNotFound` 自愈文案。
- `web_proxy.py` 调用链封闭：仅 `server.py:1786`（register）与 `tests/test_web_fetch.py` 引用；`前端控制台.spec` 无直接引用。103 行全部有消费方，非孤儿。
- **fetch_text SSRF 深查（实测）**：起始 `file://` 被 :74 白名单拒（黑盒已证）；**重定向到 `file://` 实测被 urllib 拒**（`HTTPError: Redirection to url 'file:///...' is not allowed`）；URL 携带 `\r\n` 实测在发送层被拒（`InvalidURL: URL can't contain control characters`）→ 无响应拆分/header 注入；5MB `read` 上限有效；15s 超时；`LookupError` 编码兜底在位。
- **main.py:1430 `openDroppedFile` 转义（任务点名）**：`safe = open_file_path.replace('\\', '/').replace("'", "\\'")`——反斜杠**先**被替换为正斜杠，尾部反斜杠形态（`C:\foo\`）结构性不可能成为转义符（`C:/foo/'` 无歧义）；路径内 `'` 被正确转义；路径含换行/`\u2028` → JS 字符串字面量 SyntaxError → 被 `except: pass` 吞（静默不打开，无注入）。结论：安全。
- **tray.py a535 `global _tray`（:547）**：AST 验证 `_watchdog_loop` 内 `_tray` 的 Load@534 先于 Global@547——CPython 仅对「先**绑定**后声明」报 SyntaxError，先 Load 后声明合法且整个函数视 `_tray` 为全局（编译实验证实），a535 修复正确。
- **睡眠 10 分钟定时器**：`document.visibilityState === 'visible'` 前置使窗口最小化时不累计（合理）；`_ui.sleeping`/`_ui.reader` 均正确跳过；`_webWake` 双路径（switchTab 立即 + 1s 兜底）由 sleeping 标志天然去重；休眠期 `HistoryChanged` 会把返回键点亮（cosmetic，记录）。
- **阅读模式并发/状态机**：`rseq` 序号守卫覆盖连点与切换；`skipRestore` 防恢复导航死循环；reader 与 sleep 互斥；off 路径按栈顶恢复。
- **缩放记忆**：per-host localStorage 键、0.5–2 钳制、各 tab 宿主元素 inline zoom 独立；`web-zoom:` 空 host 键无害。
- **index.html a481 `overflow:hidden`**：topbar 子元素无自定义弹出层（仅原生 select，弹层不经 DOM 裁剪），无可达裁剪面。
- **settings.js / style.css 其余 hunk**：纯文案/样式，`_stCdpCard` 的 POST/重探 GET 分离兜底逻辑自洽。
- **B5 根因落地**：`server.py:3599` `python -m src.server` 独立入口硬编码 `port=8765`（主程序走动态端口）——黑盒环境项关闭，隔离实例应避开 8765 或加端口参数。

---

## 四、补丁回归面（A1–A12 采纳后）

### 会破的现有用例
- **无**。逐条核对：`tests/test_web_tabs_logic.py` 7 个用例均不触及 A3（无 dispose×pending 场景）、A5（无就绪前 navigate）、A9（URI 非空）、A11（不引用 `_lock`）；A4 的 `_FakeTask` 恒成功，失败分支不触发；A6/A12/A7/A8/A10/A1/A2 无对应测试层（REST 层无测试、前端无 JS 测试、main.py 无测试）。`tests/test_web_fetch.py` 纯函数不受影响。
- 隔离复跑确认：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**（本轮基线复验）。

### 需新增（只列清单）
1. A3：create 后（`_pending` 在途）立即 dispose → 断言 `_cancel` 命中、`_build` 零控件产出、`_pend_nav` 无残项；再加「create→dispose→create 同 id 三连」用例钉 FIFO 消费语义。
2. A4：`EnsureCoreWebView2Async` 抛异常的 fake task → 断言控件出 `_ctl`、`Dispose` 调用、`__webTabDead` 脚本**经 `_ui` 通道**发出（断言 BeginInvoke 队列而非直接调用——同时钉住 W14）。
3. A5：`_ctl` 有值但 CoreWebView2 None 时 navigate → 断言 URL 入 `_pend_nav` 且初始化完成后按末次胜出导航（两种到达顺序各一）。
4. A6：REST 层用例需先以 CLR 桩 fixture 安装 stub WebTabs（否则 `if not t` 短路使 `_num` 不可达）——`act=show` 传 `sq:"NaN"`/`on:"false"`、`layout` 传 `"abc"`/`NaN`/嵌套对象 → 断言 200 JSON 且语义正确。
5. A9：空 URI → 断言推送参数为 `about:blank`。
6. D1：`dispose_all` + `reset_session` → 断言 `_want_seq/_want/_pend_nav/_cancel` 归零且控件全 Dispose。
7. A2：`_is_loopback` 表驱动（子域/userinfo/IPv6/大写 host/畸形 URL）——需先把 helper 提为可导出（当前闭包内定义不可测，建议顺手提级）。
8. A10：`_webNormUrl` 表驱动（若引入 JS 测试设施）。
9. W15 回归：1s 巡检路径的定向导航用例（同 8）。

---

## 五、已排查未发现问题（防 R3 重复）

1. A1 回归面：无 iframe、无跨源消费方、去重逻辑无损——删除干净。
2. A2 全部对抗形态（子域/userinfo/IPv6/异常路径）与工具自身 URL 放行语义。
3. A3 双发去重 × dispose 的全部时序（含同 id 三连的 FIFO 自愈推演）。
4. A5 × create 末次胜出两种到达顺序（无丢 URL）；`_pend_nav` 三方写入原子性。
5. A6 的 1e308/Infinity/嵌套对象/None/数字串/`on` 各形态（1e308 由 Rectangle 转换抛错被 `_apply` try 捕获，下次合法 layout 自愈）。
6. A4 前端 `__webTabDead` 的遍历重入安全性（同步 find + `_edCloseNow` 同步清理 + `delete connections`）。
7. A7 抽屉分组下游（标签/图标/休眠计时/switchTab 包装器）。
8. A9 空 URI 降级语义。
9. D1 的 before_request 守卫通过性（text/plain + force=True + 同源 Origin）与纪元前缀兼容性。
10. W10 核伪：`list(dict.items())` C 层原子性论证 + 20 万次并发压测零 RuntimeError。
11. fetch_text：file:// 重定向拒（实测）、URL 控制字符发送层拒（实测）、5MB/15s 上限、编码兜底。
12. devtools_cdp.py 全文（无注入面、endpoint.json 生命周期、错误文案链）与 main.py `_patched_ready` 挂接时序（initial load 在包装安装前，不被 `_safe_load` 截胡）。
13. `web_proxy.py` 调用链封闭性（server.py register + tests，spec 无引用）。
14. main.py:1430 `openDroppedFile` 转义（尾部反斜杠结构性不可能、引号转义正确、换行静默失败）。
15. tray.py a535 `global` 修复（AST + 编译行为双重验证：Load-before-Global 合法且语义正确）。
16. 睡眠定时器/唤醒双路径/阅读模式 rseq 状态机/缩放记忆的并发与边界。
17. index.html a481 overflow:hidden 无可达裁剪面；settings.js/style.css 其余 hunk 无逻辑面。
18. B5 根因：`server.py:3599` 独立入口硬编码 8765——环境项关闭。
19. 基线测试隔离复跑：20 passed。
