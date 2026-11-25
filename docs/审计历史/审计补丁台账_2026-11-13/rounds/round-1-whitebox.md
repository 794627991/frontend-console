# 内嵌浏览器（路线 A）白盒对抗审计 · 第 1 轮

- 基线：d9c8886（v4.1.0-a556），分支 master，审计范围 `git diff 6504d07^..HEAD`（85 提交，a473→a556）
- 方法：HEAD 现状逐文件精读 + 关键 hunk 上下文 + pywebview 源码（site-packages/edgechromium.py）旁证；只读不改
- 环境：Windows / Git Bash；测试以隔离 USERPROFILE 运行

---

## 一、确凿发现

### W1【P0·安全】`--disable-web-security` 是 a501 iframe 时代残留，现全局生效于 web tab 浏览器进程——网页 tab 里任何网站可跨源读取本地 GET API（含任意文件读）

- 位置：`src/main.py:1569`（`_wv_args` 内 `--disable-web-security`）；`src/web_tabs.py:80-83`（`CreateAsync(None, udf, None)` 不带 options）；`src/server.py:364-398`（`_guard_local_origin` 只查 POST/PUT/DELETE/PATCH 的 Origin）；`src/server.py:2704`（`/api/read_text` 任意路径读文件）。
- 依据与触发路径：
  1. 该开关是 a501 为「iframe + 代理」架构加的（注释自述"唯一可靠路径是渲染引擎层禁用同源检查"）。a544 退役 iframe 后原生控件根本不需要它，但它仍留在 `_wv_args` 里，经 `os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]`（main.py:1594）下发。
  2. web tab 控件的环境以 `CreateAsync(None, udf, None)` 创建：options 为 None，WebView2 按文档回落读取 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 环境变量 → **网页 tab 的独立浏览器进程同样带 `--disable-web-security`**。（旁证：main UI 进程是 pywebview 显式设了 `AdditionalBrowserArguments='--disable-features=ElasticOverscroll'` 的，9222 端口仍经环境变量送达并在生产验证可用——证明环境变量与显式参数合并生效。）
  3. 后端 `/api/*` 的 GET 端点无 Origin 守卫（`_guard_local_origin` 只拦写方法），平时靠浏览器 CORS（响应无 ACAO 头）挡住外部页面读取；`--disable-web-security` 把这道防线在渲染层关掉。
  4. 可读面实证：`GET /api/read_text?q=<绝对路径>` 直接读本机任意 ≤30MB 文本文件（server.py:2704）；`GET /api/history`、`GET /api/buffer` 吐终端历史/屏显内容。
  5. 端口发现：后端绑随机端口，但攻击页在渲染层可对 `http://127.0.0.1:<port>/api/status` 做快速端口扫描（同源检查已关，失败响应可读），Windows 动态端口区间可秒级扫完。
  6. 完整链：用户在网页 tab 打开任意恶意站 → 该站 JS 扫出后端端口 → `fetch('/api/read_text?q=C:/...')` 读任意文件/终端历史并外传。全程无需用户二次交互。
- 修复方向：a544 架构下删掉 `--disable-web-security`（原生控件无同源需求）；若保守，至少为 web tab 环境单独创建 options 不继承该参数；同时给 GET 敏感端点补 Origin/同源校验。

### W2【P1·安全】`_safe_load` 外链拦截用子串包含判定 `"127.0.0.1" not in _u`，可被任意包含该字面量的外部 URL 绕过 → 主 UI 窗口被导航到攻击者页面

- 位置：`src/main.py:806-817`。
- 依据与触发路径：pywebview `OPEN_EXTERNAL_LINKS_IN_BROWSER=False` 时，主 UI 的 NewWindowRequest 走 `self.load_url(url)`（edgechromium.py:255-262 实证），被包装成 `_safe_load`。判定是**子串包含**：`http://127.0.0.1.evil.com/`（真实可注册的子域形态）或 `https://evil.com/?r=127.0.0.1` 都包含 `"127.0.0.1"` → 判为本机 URL → `return _orig_load(url)` → 主窗口整页导航到外部内容（工具 UI 被替换，钓鱼/DoS）。叠加 W1：主 UI 进程同样带 `--disable-web-security`，落地后的攻击者页面即获得与 W1 相同的 GET API 任意读链（此处无需端口扫描——页面可通过 `performance`/错误探测或直接复用扫端口路径）。触发面：Claude 回复/日志/笔记里的可点外链（target=_blank 即走此链）。
- 修复方向：解析 URL 后判定 host 是否精确等于本机回环（`urlparse(_u).hostname in ('127.0.0.1','localhost','::1')`），而不是子串搜索。

### W3【P1·功能】主 UI 刷新后 web tab 状态机三重错乱：seq 门禁永不重置 + tab id 双端复用 + 旧控件不 dispose——控件可永久盖住工具 UI 且无法再隐藏

- 位置：`src/web_tabs.py:48-49、364-367`（`_want_seq` 只增不减、进程内永存）；`web/js/web-panel.js:25、106-107`（`_webCtlSeq`/`_webSeq` 是页面本地计数，刷新即归零）；`web/index.html:8-15`（pagehide 仅 debug 下 beacon 回收串口/SSH，web tab 控件无任何卸载清理，server.py:1152 `api_reload_disconnect` 同样只 `close_all_ports()`）；`src/main.py:820`（a483 无条件开右键菜单 → WebView2 默认菜单含「重新加载」，生产版可达）。
- 依据与触发路径（右键 → 重新加载）：
  1. 刷新后前端 sq 从 1 重新计数，后端 `_want_seq` 已是刷新前累计值（每次 tab 切换/浮层联动/点击都 `++`，数值可观）→ `sq <= _want_seq` 全部丢弃（web_tabs.py:366）。此后**一切 show/hide（含 a550 浮层联动隐藏）失效**；若刷新前有可见控件，它继续压在工具 UI 上，用户点弹窗也无法触发隐藏。
  2. 新页面 tab id 从 `web-1` 重新分配，与后端幸存控件撞名：`create('web-1',…)` 命中 `tab_id in self._ctl`（web_tabs.py:125）→ 直接 navigate **刷新前的旧控件**。
  3. 刷新前所有控件无 dispose → 全部泄漏（隐藏态、持有各站会话与内存）；layout 到达后 `_apply_visibility` 按**陈旧 `_want`**（如 `('web-3', True)`）显隐 → 显示错页控件、藏掉新 tab 控件。
- 修复方向：pagehide 统一 dispose 全部 web 控件（不限 debug）；seq 改握手同步（页面装载后先取后端水位或后端按连接重置）；tab id 加页面实例前缀。

### W4【P1·功能】CDP 解禁（a473）在 a544 架构切换后打不到目标：devtools_* 永远只能操作工具主 UI 文档，无法触达任何网页 tab 页面（半删残留）

- 位置：`src/web_tabs.py:81-83`（独立 UDF `fc_webview_tabs` → 独立浏览器进程）；`src/devtools_cdp.py:98-111`（`find_page_target` 只认 url 以工具后端 origin 开头的 target）；`src/main.py:1571`（9222 固定端口）。
- 依据与触发路径：
  1. web tab 控件与主 UI 不同 UDF = 两个浏览器进程；`--remote-debugging-port=9222` 两进程都带（同一环境变量），主 UI 进程先启动先绑定，web tab 进程绑 9222 失败后静默继续——CDP 服务端只在主 UI 进程存在。
  2. 即便可达，`find_page_target` 按「url 以 `http://127.0.0.1:<port>` 开头」过滤 target，网页 tab 加载的外部站 URL 永不入选。
  3. 结果：设置页承诺「AI 可用 devtools_* 工具直接操作内嵌浏览器（读页面/点按钮/填表单/截图/看网络请求）」（settings.js:782-784）对真正的网页内容完全失效——iframe 时代网页活在主 UI 文档内所以 CDP 够得着，a544 搬走后无人重接。AI 只能 evaluate 工具自身 UI 文档。
- 修复方向：web tab 环境显式创建 options 指定独立 CDP 端口（或经 `/json/list` 多端口发现），devtools_cdp 按 tab 选择 target；至少先修设置页文案与实际能力一致。

### W5【P1·功能】dispose 与 create 在途竞态 → 已关闭 tab 的控件成永不 Dispose 的孤儿（隐藏状态下加载完整网页、持有会话）

- 位置：`src/web_tabs.py:128-153`（create：`_pending` 标记 → BeginInvoke `_build`）、`src/web_tabs.py:385-398`（dispose：`self._ctl.pop` 查无即返回 ok，不感知 `_pending`）。
- 依据与触发路径：create 的 REST 响应先于 `_build` 执行（BeginInvoke 异步）。用户在控件尚未建好时关 tab（点 ✕）：dispose 在 Flask 线程 `pop` 返回 None → `{"ok": True}`；随后 UI 线程照常执行 `_build` → 建控件、加进 `_ctl`、接线、`Navigate(url)` → 完整页面在隐形控件里加载。该控件无人再引用：前端 conn 已删，`_want` 不会再指向它，直到进程退出才释放。`_pend_nav` 也不清理。复现窗口 = create 响应到 `_build` 执行之间（UI 线程忙时可达数百 ms），快速「开 → 关」即可触发。
- 修复方向：dispose 命中 `_pending` 时登记取消标记，`_build` 开头检查后直接返回（不 Add 不 Navigate）；顺带清 `_pend_nav`。

### W6【P2·功能】控件已入 `_ctl` 但 CoreWebView2 未就绪的窗口期内 navigate 被静默吞掉（返回 ok=True）

- 位置：`src/web_tabs.py:125-127`（`tab_id in self._ctl` → 走 `navigate`）、`src/web_tabs.py:288-293`（`ctl.CoreWebView2.Navigate(url)`，CoreWebView2 为 None 时 AttributeError 进 WARN 日志）。
- 依据与触发路径：`_build` 把控件写入 `_ctl` 后，`EnsureCoreWebView2Async` 仍在异步初始化（数百 ms）。此窗口内第二次导航（如快速连改地址回车、`__webTabNew` 开新 tab 后立刻导航）→ create 命中 `in _ctl` 分支 → navigate → `CoreWebView2 is None` → 异常吞掉 → **URL 丢失**，REST 返回 `ok=True`；地址栏已显示新 URL 而控件停在旧页/白屏，用户重试才恢复。a555 的 `_pend_nav` 只覆盖 `_pending` 在途窗口，不覆盖此初始化窗口。
- 修复方向：CoreWebView2 未就绪时把 URL 记入 `_pend_nav`（复用末次胜出机制），初始化完成后补导航。

### W7【P2·健壮性】`/api/web/tabs` 入参不设防：非数字/NaN/Infinity 触发裸 500，`on` 布尔判定被字符串穿透

- 位置：`src/web_tabs.py:405-407`（`int(x)`/`int(y)`/`int(w)`/`int(h)`）、`src/web_tabs.py:461-464`（`int(d.get("sq") or 0)`、`bool(d.get("on", True))`）。
- 依据：`request.get_json(force=True, silent=True)` 接受 Python JSON 宽松字面量，`{"act":"layout","x":NaN}` 解析为 `float('nan')` → `int(nan)` ValueError → 未捕获 → 500（HTML 错误页，非 JSON）；`"x"` 同样 500，`Infinity` → OverflowError 500；`{"act":"show","on":"false"}` → `bool("false")`=True。前端自身不发脏值，但这是本地 HTTP 面，任何本机客户端/脚本可直接打；before_request 的 JSON 非 dict 收口（server.py:385-390）不覆盖标量字段类型。
- 修复方向：try/except 回落默认值（照抄 server.py `_q_int` 模式）；`on` 用 `is True`/显式转换。

### W8【P2·多客户端】双 UI 客户端（或刷新前后两代页面）并存时事件、seq、tab id、Bounds 四面互踩

- 位置：`src/web_tabs.py:211-220`（事件仅 `ExecuteScriptAsync` 单播到内嵌主 UI 的 CoreWebView2——HTTP 连入的第二客户端收不到任何回推事件）；`web_tabs.py:364-367`（`_want_seq` 进程级单水位，两个页面的本地计数互相视为「迟到旧令」丢弃）；`web-panel.js:106-107`（两端各自从 `web:1/web-1` 起号必然撞车）；`web_tabs.py:405-421`（后到的 layout 直接覆盖前一个客户端的 Bounds）。
- 依据：工具是单窗口形态，但 Flask 服务对任意本机浏览器开放（127.0.0.1）；用户在 Edge 里再开一个 `http://127.0.0.1:<port>` 即构成第二客户端。此时 B 客户端：地址栏/按钮态永不更新（事件零送达）、show 指令大概率被 seq 丢弃、操作落到 A 客户端创建的同名控件上。
- 修复方向：声明单客户端假设并在服务端检测第二来源拒绝/提示；或事件改 SSE 广播 + seq 按客户端会话隔离。

### W9【P2·功能】`_SINGLE_KINDS` 仍含 `'web'`（a473 单开时代残留）→ a554 多开后网页 tab 永不进抽屉

- 位置：`web/js/util.js:62`。
- 依据：`_isFlat = (kind,cnt) => _SINGLE_KINDS.has(kind) || cnt<2`——web 命中 Set 恒平铺。a452 已为 claude 记录过同款事故的后果（注释原文：「多个 claude tab 永不进抽屉，tab 栏被平铺占满压成图标态」），a554 网页去单例化时漏删此项。连开 3+ 网页 tab 即复现 tab 栏溢出压成图标态。
- 修复方向：从 `_SINGLE_KINDS` 移除 `'web'`，让数量判定自然接管。

### W10【P2·并发】`_ctl` 双线程读写无锁：dispose 在 Flask 线程 pop、`_build` 在 UI 线程写；`list()` 快照本身非原子；`_lock` 定义未用

- 位置：`src/web_tabs.py:23`（`_lock` 全文零引用）、`src/web_tabs.py:146`（UI 线程写 `_ctl`）、`src/web_tabs.py:387`（Flask 线程 pop）、`src/web_tabs.py:344、415`（`list(self._ctl.items()/values())`）。
- 依据：CPython 中 `list(d.items())` 复制期间被并发修改可抛 `RuntimeError: dictionary changed size during iteration`——a555 注释声称「list 快照防 dispose 竞态」，但快照动作本身就是被竞态的对象；窗口极窄但存在（Flask 线程 dispose.pop 恰落在 UI 线程 layout/show 的 list() 复制中途）→ `_apply` 内异常被外层 try 吞掉，当次显隐半途而废（表现为偶发切 tab 不显形，无崩溃）。模块顶的 `_lock` 是死代码，说明锁意图存在但未落地。
- 修复方向：pop/写都归 UI 线程（dispose 也 BeginInvoke），或真正用上 `_lock`；快照改 `dict(self._ctl)` 后再取视图同样不解决问题，需锁。

### W11【P3·残留】a545 大扫除后的孤儿/死代码合集

- `src/web_tabs.py:23`：`_lock` 死定义（并入 W10 亦可）。
- `src/web_tabs.py:400-402`：`dispose_all` 无任何调用方（全局 grep 仅定义处）——app 退出无统一回收路径，靠进程终止兜底。
- `web/js/web-panel.js:22`：`WEB_PORTID` 注释称「外部模块引用判断 kind」——全仓 grep 无任何外部引用，纯死常量；其存在的理由（a555 三处注释还在解释 `connections[WEB_PORTID]` 恒 null）已随 a555 修复消失。
- `web/js/web-panel.js:146-148` + `web/style.css` `.web-blank-hint`：a493 的 XFO 提示条 DOM 每个新 tab 都在创建，但**无任何代码切换其显隐**——原生控件架构下永不可见，死 UI。
- `web/js/web-panel.js:149-157、180-191`：a488 的 `.web-err` 加载失败层只有 click 处理器（只会隐藏自己），**无任何代码将其置为可见**——死 UI（原生控件的加载错误不再经前端层暴露）。
- `web/js/sidebar-resize.js:30-44`：a524 的 `iframes().forEach(pointerEvents)` ——a544 后全站 `web/js` 已无任何 iframe 创建点（grep 实证），两个 querySelectorAll 恒为空集，死逻辑。
- `src/web_proxy.py`：文件名/蓝图名仍叫 web_proxy，注释自述「代理路由全部退役」，实际只剩 `fetch_text`——名实不符（保留功能本身有三处真实消费，非孤儿，见「已排查」#9）。
- `web/js/web-panel.js:575`：`_webAct(act, wrap)` 的 `wrap` 形参从未使用（所有动作走 `_webCur()`），注册处却逐按钮传入，误导读者以为动作作用于所属面板。

### W12【P3·边界】NewWindowRequested 空 URI 被吞无降级

- 位置：`src/web_tabs.py:255-269`。`u` 为空串时 `set_Handled(True)` 后既不推送（`u` 假值）也不走降级导航（`if u and not _push(...)`）→ `window.open('')`/空 href 的 `_blank` 请求无声无息。低频但与 a555「不再静默吞」的修法不一致。
- 修复方向：空 URI 时降级为本 tab 打开空页或忽略且不置 Handled。

### W13【P3·健壮性】`EnsureCoreWebView2Async` 异步失败后 tab 假活：控件永留 `_ctl`，无重试、无回收、无前端可见失败态

- 位置：`src/web_tabs.py:163-168`（`_init_done` 仅 `_log` 后 return，控件保留在 `_ctl`）、`web_tabs.py:113-124`（`_env_failed` 只在 create 入口检查，env 中途失败不置位）。
- 依据：初始化失败（env 中途失效、运行时崩溃）→ 该 tab 永远白屏，后续 create 复用死控件走 navigate 失败路径（同 W6），前端无任何失败提示。与 a488 删除的失败提示层叠加后，失败完全不可见。
- 修复方向：初始化失败时从 `_ctl` 移除并 Dispose 控件、置 `_env_failed`，让下一次 create 能重建。

---

## 二、存疑 / 观察（未达确凿，供下轮验证）

1. **端口先占方向是推断**：W4 的「主 UI 进程先绑 9222」基于启动顺序（webview.start 先于首个 web tab），未实测第二进程绑失败后的行为（Chromium 记日志继续运行 vs 环境创建失败）。即便方向相反（web tab 进程绑到 9222），`find_page_target` 的 origin 过滤仍使 devtools 到不了网页 tab，结论不变。
2. **NewWindowRequested 对 `javascript:`/`data:` URI 的处置**：`__webTabNew` 链路不做 scheme 白名单（web-panel.js:349-352 → `_webNavigate` → 后端 `Navigate`）。Chromium 对渲染进程发起的 javascript:/顶层 data: 导航有内建拦截，大概率无害，未实测确认。
3. **`web-session` 只存激活 tab 的栈**（web-panel.js:45-50 `_webSessionSave` 取 `_webCur()`）：多开时代其余 tab 的导航栈重启即丢，属设计取舍而非缺陷；若产品期望「恢复所有网页 tab」需改多槽。
4. **`_cdp_alive` 探活不校验身份**（server.py:1347-1353）：本机任意进程占用 9222 的 `/json/version` 即令设置页显示「AI 可用」，误报可能，无害级。
5. **密码自动填充（a552）**：凭据由 Chromium 密码管理器管理，DPAPI 按用户加密落盘于 `%LOCALAPPDATA%\fc_webview_tabs`（Login Data），按 origin 隔离无跨站填充；卸载不清理该目录。风险与用户本机装 Chrome 同级，可接受；注意它使 W5 的孤儿控件「更有内容」（隐藏页可带登录态驻留）。
6. **`/api/web/fetch_text` 属设计内 SSRF**（本地单用户工具语义，自签不校验），且有 Origin 守卫挡外部页面 POST 直调；但在 W1 的读链下可被间接当内网代理用，W1 修复后自然收敛。
7. **overlay 联动的点击放大效应**：a550 的 sync 挂在 `pointerdown/click/contextmenu` 捕获上，网页 tab 激活期间**每次点击**都发一次 `show(true)` REST（web-panel.js:371-390）——无功能问题，但持续制造无谓请求并快速推高 seq（放大 W3 刷新后的失配窗口）。
8. **`create` 的 env 等待循环**（web_tabs.py:117-122）在 Flask 请求线程内最长同步阻塞 5s×并发请求数，threaded=True 下无服务级影响，仅浪费线程。

---

## 三、已排查未发现问题（防下轮重复）

1. **a549 线程亲和全量复核**：六个 CLR 事件处理器（SourceChanged/NavigationStarting/NavigationCompleted/HistoryChanged/NewWindowRequested/DocumentTitleChanged）均由 WebView2 在 UI 线程派发，处理器体内只读 UI 线程属性；两个 `ContinueWith` 回调（`_init_done`、env `_done`）在线程池侧只触 `t.Result`，控件操作全部再 BeginInvoke 归 UI 线程；navigate/back/fwd/reload/layout/show/dispose 的闭包全部经 `_ui()`。未发现残留的跨线直碰。
2. **ExecuteScriptAsync 注入面**：`json.dumps`（ensure_ascii 默认开）对引号/反斜杠/换行/U+2028-2029 产出合法 JS 字符串字面量；title/URL 到前端后仅 `textContent`/`inp.value`/`esc()` 消费；`</script>` 形态不适用（JS 执行通道非 HTML 内嵌）。未发现注入点。
3. **前后端事件契约**：后端推 5 事件（`__webTabUrl/__webTabLoad/__webTabHist/__webTabNew/__webTabTitle`）+ main.py 推 `__newWindow`，与 web-panel.js 定义逐一同名同参；`_webByTabId` 查无即弃，跨 tab/已 dispose 迟到事件不串扰（a555 修复成立）。
4. **收藏夹 / 发给Claude 的 DOM 注入**：`_webFavMenu` 全部插值经 `esc()`（属性双引号场景引号已转义）；reader 正文 `esc()` 后再 `<br>` 替换；showBanner→notifyPop 走 `esc()`；发给 Claude 走 `textarea.value` 纯文本。未发现 XSS。
5. **a556 后台休眠三连修复复验**：`show(false)` 只藏目标（`_apply_visibility` else 分支）；sq 乱序丢弃（`sq <= _want_seq`）；`__webTabUrl` 忽略 `about:blank` + `_webNavTop` 跳脏栈顶 + 恢复加载时过滤旧会话；switchTab 立即唤醒不等巡检。代码层成立。
6. **a554 多开隔离**：每 tab 独立 conn/`_nav`/`_ui`/控件实例/原生历史栈；缩放按 host 记忆且各 tab 宿主元素各自持有 inline zoom。
7. **Bounds/DPI**：DIP×devicePixelRatio 换算正确（WinForms Bounds 物理像素、表单客户区=DOM 视口）；隐藏 tab 不上报布局；ResizeObserver+resize+30ms 补推覆盖 maximize/跨屏 DPR 变化；坐标无可达 NaN 源（rect 来自 getBoundingClientRect）。
8. **顶栏/面板回车（a556）**：两处 keydown 均查 `e.isComposing`（IME 回车不触发）；顶栏回车恒 newTab（用户令）、面板回车导航当前 + Ctrl+回车开新；连续回车行为与「即多开」语义一致。
9. **web_proxy.py 残留 103 行非孤儿**：`/api/web/fetch_text` 有三处真实消费（reader/收藏命名/发给Claude）；`_web_detect_charset`/`_web_html_to_text` 被 tests 直测。
10. **index.html a547 修复成立**：boot 脚本已合并为单个合法 `<script>` 块，无孤立开标签。
11. **a535 tray `global _tray` 修复、a546 诊断日志退役**成立；server.py `web_cdp` 配置键读写、`web_cdp_live` 服务端探活链路自洽（且修掉了前端跨源 fetch 9222 的死码）。
12. **CDP 攻击面**：端口仅 loopback（Chromium 固有）、默认关闭、需配置键+重启、与 debug 两布尔分离（main.py:1531-1546）——除 W4 的「打不到目标」外无越权暴露。
13. **测试**：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**（0.37s）。盲区：W3（刷新/seq）、W5（dispose×create 竞态）、W6（初始化窗口期导航）、W7（REST 脏入参）、W9（抽屉判定）均无用例覆盖；现有用例集中于 a555 六项修复的钉测。
