# 内嵌浏览器（路线 A）白盒对抗审计 · 第 4 轮

- 基线：d9c8886 未变；输入材料：`patch-round-3.md`（N3/A4''/A10''/A8''/N4/N5/N1'/D1''）、`round-3-blackbox.md`（B10–B15）首次研读
- 方法：补丁逐条攻击（含 urllib 语义核验：`HTTPError.status` 存在性、`redirect_request` 返回 None → HTTPError 传播的源码确认）+ N3 关闭链全路径追踪（`_edCloseNow` 尾段/自动回切/包装器重入）+ 三份补丁叠装模拟 + 收敛面盘点
- 铁律遵守：零代码修改；pytest 隔离 USERPROFILE（复跑 **20 passed**）

---

## 一、补丁对抗评审（patch-round-3）

### A4''（err 固化）—— W21 修复成立；两处残余为观察级

- **彻底性核验**：`err = str(e)` 是普通局部变量（非 `as` 目标），不受块尾隐式 `del` 影响；`_rm` 闭包经 cell 捕获，延迟执行时稳定 ✓。`_rm` 内其余引用逐一核对：`self`（实例存活）、`ctl`（`_wire` 参数闭包）、`self._form`、`self._main_cvw`（**执行期现读**——取最新值，正确）、`tab_id`——无第二个晚绑定陷阱 ✓。
- `err` 生命周期：str 在 except 块内求值完成后以字符串入 cell，`json.dumps(err)` 无再求值风险 ✓。
- 重复失败/二次 dispose 安全性沿袭 R3 结论 ✓。
- **观察（不计号）**：①病态异常（自定义 `__str__` 抛错的异常类）会使 `err = str(e)` 本身抛出——清理（pop/_ui）被整体跳过且 ContinueWith 回调异常被 TPL 吞掉；建议 `err = e.__class__.__name__` 兜底或 try 包裹。②A4'' 把 `str(e)` 从 `_rm` 内（有 try）挪到 except 块（无 try）——仅上述病态场景下略劣于 A4'，正常异常无差。

### N3（W22 转发）—— 修复正确；三条任务点名路径逐一核验通过

- **「非激活 web tab 被侧栏关闭」的 switchTab 重入/自动回切**：完整追踪——`closeConnection(X)` →（N3 正则命中 `web:`）→ 包装器：dispose REST + `_ctlResize.disconnect()` + resize 监听移除 + `_webActivePid` 清理 → `origClose(X)`（editor.js:1394）→ web 无 `dirty` 跳过确认 → `_edCloseNow(conn)`（:1419 起，全部资源清理段均有 `if (conn.xxx)` 守卫，web 字段不存在自然跳过；`conn.tab.remove(); conn.wrap.remove(); delete connections[conn.portId]`）→ 仅当 `activePortId === conn.portId` 才回切：`switchTab(back || remaining[0], true)`。关闭**非激活** tab：无回切、激活态不动 ✓；关闭**激活** tab：包装器重入——此时 `_webActivePid` 已被清空，`prev = _webCur()` 按兜底取第一个存活网页 tab：回切目标为网页 tab 时 `isWeb` 分支显之 ✓；回切目标为非网页 tab 时 `else if (prev && prev._tabId)` 分支按 `activeWeb` 判定隐藏 prev 的控件 ✓（`_hgTabBack` 优先回「来路 tab」的逻辑对 web 同样成立）。**回切目标显隐正确**。
- **editor.js `closeEditorTab` 对 web portId 兼容性**：`_edCloseNow` 无任何 web 不兼容点（逐段核验：pollTimer/tickTimer/editor/monaco/diffEd/_dsEditor/_pdf*/vcs teardown 全部存在性守卫）；`closeEditorTab` 的 `conn.dirty` 未定义 → 无弹窗直接关 ✓；双击重复关闭第二路径 `if (!conn) return` ✓；`treeDecoRefresh/refreshSidebar` 无害 ✓。
- **`_webActivePid` 清理完整性**：包装器是现在唯一的 web 删除入口（tab ✕ / `__webTabDead` / N3 两条旁路全部汇入）→ 清理完整 ✓。
- **util.js 批量分支插入位置与 `_closeAllBusy`**：插入点在 forEach 内 harness 分支之后、`const isEd` 之前——web 分支 `return` 早于 isEd 的 TDZ 求值 ✓；非 web kind 正常到达 isEd ✓；`_closeAllBusy` 守卫包裹整个 forEach，插入不改变 busy 语义 ✓；批量关 web 时逐个走包装器（`closeEditorTab` 对 web 无 await，同步执行 `_edCloseNow`，快照 `toClose` 不受影响）✓；同批内自动回切可能对「下一个即将被关的 tab」发一次瞬时 show——多余 REST 但无害。
- 附带确认：W22 的 `POST /api/disconnect` 必败噪音请求随转发消失（patch §三 已记）✓。
- 残余（沿袭既有观察）：包装器内 dispose REST 是 fetch 非 beacon——仅页面卸载场景由 D1'' 的 pagehide beacon 兜底，单 tab 路径在网络异常时静默失败（基线语义，维持）。

### A10''（顶栏反馈）—— 干净；a556 空回车边界核验通过

- 任务点名的**全空格输入**：`bar.value = "   "` → `_webNormUrl` trim 后 '' → `!u` → `bar.value.trim()` 为空 → 走 `buildWebPanelTab()`（a556 空=开 tab 恢复会话）——与基线行为一致（基线对全空格同样开 tab），补丁**未改变**该边界，仅把「非空且非法协议」改道反馈 ✓。
- 非空非法协议 → banner + `return`（**跳过 blur**——焦点留在顶栏便于改错，合理的副作用，记录）✓。
- 面板栏（A10'）与顶栏（A10''）两条 banner 文案一致，notifyPop 同文案去重生效 ✓。

### A8''（三处 `_webSyncUI`）—— 干净

:611/:615 传 `_webAct` 的 `c`（B7 场景归属正确）；:732 改为遍历 `connections` 对全部 web tab 逐个 `_webSyncUI(cw)`——逐 tab 按各自栈顶判星，成本可忽略 ✓；与 `_webFavMenu(anchor)` 重建菜单的先后顺序无依赖（星标按钮在 wrap 不在菜单）✓；非 web conn 被 kind 判断跳过 ✓。

### N4（B12 文案收口）—— 修复方向成立，但引入状态码丢失，见 W30

- `_hint` 覆盖面核验：`UnicodeEncodeError`（B12 实锤形态）✓；`URLError` 兜住 urlopen 包装的 gaierror/ConnectionReset/refused ✓；`TimeoutError` 直发型几乎不可达（urlopen 的超时通常包成 `URLError(socket.timeout)`）→ 实际显示「无法连接目标」——文案略不精确但可接受；`ValueError` 覆盖控制字符 URL/畸形形态 ✓；其余只出类型名（如 `SSLError`/`ContentTooShortError`）——量级可控 ✓。
- **W30【P3·补丁引入】非重定向 HTTPError 的状态码丢失**：目标返回 404/403/500 → urllib 抛 `HTTPError`（`_kind='HTTPError'` 不在映射）→ 用户只见「取页失败：HTTPError」——**比基线（原文含 `HTTP Error 404: Not Found`）更不可诊断**；N1' 手动跳转循环里 `raise` 的非重定向 HTTPError 亦落入同径。修法：映射表加 `"HTTPError": "目标返回 HTTP %s" % (getattr(e, "status", None) or getattr(e, "code", None) or "?")`（`HTTPError.status`/`.code` 属性已核验存在）。

### N5（web-favs 校验自愈）—— 干净

- 「filter 后长度不变不回写」正确性：`ok.length === v.length` 时内容与原值全等（filter 是恒等映射）→ 跳过回写，避免每次读菜单的写放大 ✓；长度不等才回写自愈 ✓。
- `_webFavsSave` 内部 `slice(0,100)` 与 filter 的双重裁剪：先 filter 后（save 时）slice——手写超 100 条的畸形存储也被裁回 ✓；`_webFavs` 内调 `_webFavsSave` 无递归（Save 不回读）✓。
- 元素形态核验：`null`/数组/缺 url 对象全被滤除；`url` 为 string 但 `title` 为数字 → `f.title || _webShortUrl(url)` 与 `esc(String)` 链路安全 ✓；B13 的 `__proto__` 自有属性元素（含 url）保留且无污染路径（只读 url/title）✓；localStorage setItem 抛错（配额/禁用）被 catch 吞 ✓。

### N1'（手动逐跳重定向）—— 主体成立；一处状态码丢失并入 W30，两处观察

逐项核验（任务点名）：
- **HTTPError 携带 Location 的可靠性**：`_NoRedirect.redirect_request` 返回 None → `http_error_302` 源码 `if new is None: return`（实测确认）→ 无处理器消费 → 原始 3xx 以 **HTTPError** 冒泡，`he.headers.get("Location")` 为 3xx 响应头 ✓ 可靠。
- **303/307/308 语义**：四个状态码全部经 `redirect_request`（源码同构）→ 统一冒泡 ✓；fetch_text 只发 GET——303 的 POST→GET 转换与 307/308 的方法保持对 GET 均无差；每跳新建 `_req`（GET）与浏览器 GET 语义一致 ✓（B11 的 301/302/307/308 实测面全覆盖）。
- **urljoin 相对跳转**：相对/绝对/协议相对均正确解析 ✓；Location 含控制字符 → `startswith http` 仍放行 → 发送层 `InvalidURL` 拒绝（R2 实测）→ 落 N4 文案 ✓；Location 为空 → falsy → `raise` → N4 ✓。
- **逐跳 opener 重建开销**：≤6 个 opener，无连接复用（每跳新 TCP/TLS）——相对 15s 超时量级可忽略 ✓；每跳各做一次 `_web_is_private_host` DNS（+1 次/跳）可接受 ✓。
- **5MB 读取上限交互**：仅对最终响应 `with resp as r: raw = r.read(5MB)`；3xx 响应体不被读取 ✓。
- **resp 未 break 时泄漏**：重定向路径 `open` 抛异常 → `resp` 保持 None → for-else 返回「重定向次数过多」✓ 无悬挂；6 跳用尽后 else 分支正确（break 跳过 else）✓；HTTPError 的 `he.fp` 靠 CPython 引用计数在重绑定/循环结束时由 IOBose 终结器关闭——非泄漏（ResourceWarning 级）✓。
- **观察①（跳数×超时放大）**：每跳独立 15s → 最坏 6×15=90s 占用 Flask worker（基线 15s）——自伤型放大，建议跳数预算共享一个 deadline。
- **观察②**：`_NoRedirect` 类定义在函数体内每请求重建——微小开销，无害。

---

## 二、累计补丁叠装一致性（patch-round-1含修订 + 2 + 3 全应用模拟）

**hunk 冲突/重叠**：无。三条修订链均为「整块替换」式（A4→A4'→A4'' 同一失败分支；A10→A10' 整函数替换；A10'' 独立行段），按序应用无文本冲突。跨文件修改（web-panel.js 被 A8/A8'/A8''/A10'/A10''/N5/D1' 七个补丁触及）行段互不重叠（:46-65 / :80-93 / :171 / :201-230 / :394-436 / :495 / :576-615 / :655+ / :672-680 / :732）。

**语义抵消检查**：无作废。特别核验：
- A8→A8'→A8'' 链：A8' :405/:411/:412 与 A8 的 :394 签名改动同函数不同行段；A8'' 的 :611/:615/:732 是 A8' 清单外的独立点 ✓。
- A5（`_pend_nav`）× A3（cancel 时 pop `_pend_nav`）× D1''（cancel 路径补 `_epochs.pop`）——三者对同一 tab 的三份状态清理合并后完整 ✓。
- N1' 整体替换 N1 的 ctx 构造段（diff 明示删除行即 N1 产物）✓；N2 与 A2 在 `_safe_load` 内为串行叠加（外链拦截 → 非 http 吞 → 回环放行），终态语义自洽 ✓。
- D1'' 的 epoch 随机后缀改变 portId 形态（`web:<epoch>-<rand>:<n>`）——下游 `startsWith('web:')`（sortKeyFn）、`_webByTabId`（_tabId 精确匹配）、N3 正则 `^(…|web):` 全部兼容 ✓（A11 已删 `WEB_PORTID` 常量，无残留依赖）。

**叠装后已知残余风险清单**：
1. **W30**（N4 状态码丢失——本轮新立，随 N4 一并修）。
2. **W28/W29 开放**（本轮新立的基线双轨历史问题，现有补丁栈无一触及——见第一节外的新发现）。
3. **D 栈未落地**：W3（刷新三重错乱）、W4（CDP 触达）、W8（多客户端）、W24（D1'' 仍为设计稿）、B14——在 D1''/D2/D3 实现前全部维持。
4. N1' 跳数×超时放大（≤90s worker 占用，观察①）。
5. A4'' 病态 `str(e)`（观察①）。
6. A10'' 非法协议后焦点不离开顶栏（行为取舍，非缺陷）。
7. 包装器 per-tab dispose 为 fetch：页面卸载场景依赖 D1'' beacon（单 tab 关闭 + 瞬时网络错仍可漏）。
8. 测试债（W27 + patch §五 15-19）：现 20 用例零破坏，新增用例清单未落地。

---

## 三、新发现（W28–W30，含基线双轨历史面）

### W28【P3·基线】后退/前进污染前端 `_nav` 栈：跨站 back = push（栈膨胀、50 帽加速淘汰、会话栈失真）；同站 back = 原地覆盖（前进项暂失）

- 位置：`web/js/web-panel.js:314-327`（`__webTabUrl` 的栈规则）——该规则只为「用户导航」设计，却同样作用于**后退/前进产生的 SourceChanged**。
- 触发路径：A→B→C（跨站）后按 ◀ 回 B：`top=C`，`host(B)≠host(C)` → `slice(0, idx+1)` + `push(B)` → 栈变 `[A,B,C,B]`——后退**加**了一条；继续 back→A → `[A,B,C,B,A]`。同站形态（C 与 B 同 host）：back → `stack[idx] = B` → C 被覆盖丢失（前进到 C 时按同规则原地恢复——自愈）。
- 影响如实评估：栈的全部消费点（★/↗/发给Claude 的 URL、缩放 host、唤醒/会话恢复栈顶、阅读模式取页 URL）读的都是「栈顶=当前页」——**恰好保持正确**；实际危害 = 栈条目膨胀（50 帽加速淘汰真实历史）、`_webNavigate` 的 `slice(idx+1)` 保留幽灵中间项、会话栈与用户感知历史失真。P3。
- 修复方向：`__webTabUrl` 区分「导航来源」——GoBack/GoForward 期间对栈做 pop/idx--（后端可在事件里带导航类型，或前端在 `_webCtl back/fwd` 时打标志消费下一条 SourceChanged）。

### W29【P3·基线】休眠/阅读模式写入的 about:blank 原生历史项：唤醒/退出阅读后按 ◀ 落在白屏，地址栏停留旧 URL

- 位置：`web/js/web-panel.js:471`（`_webSleep` nav about:blank）、`:523`（`_webReaderToggle(true)` nav about:blank）、`:306`（`__webTabUrl` 对 about:blank 一律忽略）。
- 触发路径：唤醒/退出阅读用 `Navigate(url)` 新开条目 → 原生历史 `[…, B, about:blank, B']` → 用户按 ◀ → 控件落到 **about:blank（白屏）**；`__webTabUrl` 的 a556 守卫使前端**永不知情**——地址栏/胶囊保持 B'、无任何错误提示；`__webTabHist` 因 CanGoBack 仍为 true 而 keep ◀ 可按。再按一次 ◀ 或 ▶ 可走出（▶ 回 B'）。B11/B14 无涉，属三轮未触的「原生历史 vs 前端栈」双轨失步族的第二形态。
- 修复方向：与 W28 同根——内部导航（休眠/阅读）改用不进历史的方式（`Navigate` 后 GoBack 剔除，或后端为内部导航打「可回退剔除」标记），或唤醒改用 `GoBack/GoForward` 回到真实条目而非新 Navigate。

### W30【P3·补丁引入】见第一节 N4 段——非重定向 HTTPError 状态码丢失，「取页失败：HTTPError」比基线更不可诊断。

---

## 四、收敛评估（以 W1–W27 + B1–B15 全部确凿为底）

**三轮未触或仅表层、本轮已触破的面**：「前端 `_nav` 栈 vs 后端原生历史」双轨——R1-R3 只审过它的归属语义（B1/B7/A8 族），从未审过它的**内容语义**（W28/W29 即产出于此）。这证明「未触面」仍有矿。

**仍未触或仅表层的具体清单**（R5 候选）：
1. **桌面-only 控制级行为**（最大盲区，需验证手册）：`_webCtlSetup` 的 per-monitor DPI 迁移/`Form` 客户区原点假设/zoom×DPR 叠加；a551 浮层与 HWND 叠放的真机矩阵；休眠 10 分钟真机全链；target=_blank 真实流；加载失败层。
2. **`_ensure_env`/`install` 生命周期**：interop_dll_path 两条回退分支、`Path` 环境变量追加的幂等性、主窗口重建（tray/watchdog 路径）时 `install()` 二次装配与旧 `_tabs` 控件的关系——桌面-only。
3. **`_webSleep/_webWake` 状态机角落**：抽屉折叠触发的 display 翻转 × 休眠计时、`visibilityState` 中途切换、reader×sleep×多 tab 矩阵——部分桌面-only。
4. **`_webFavMenu` 其余分支**：恢复上次网页（无 URL 分支）、定位/视口钳制、close 监听清理——表层未深挖。
5. **`main.py _patched_ready`**：强制右键 × a483 全局 preventDefault 的交互面；`load_html` 等包装外方法——表层。
6. **D3 多客户端事件/广播语义**：黑盒仅有请求级实证（B14），控件级需桌面。
7. **双轨历史族的同类形态**：`__webTabNew` 开新 tab 与手输导航的栈交互、会话恢复后栈顶与实际页的偏差窗——本轮 W28/W29 的近邻。

**「R5 是否还可能产出新确凿」——明确回答：可能，但产出率已收敛。** 依据：确凿数 R1=13 → R2=7 → R3=7 → R4=3，且 R4 的两条基线新发现全部来自本轮首次触及的「双轨历史」面——说明静态白盒面**尚未穷尽但已接近**；剩余高概率区按序为：①D 栈（D1''/D2/D3）落地后的实现评审（行为重写必然引入新面，W24 的历史就是先例）；②桌面端验证手册执行时的控制级发现；③双轨历史族的近邻形态与 D3 会话语义。**建议 R5 形态 = 验证手册执行（桌面）+ D 栈实现 diff 评审，纯静态白盒可宣告收敛。**

---

## 五、桌面端验证手册（定稿，合并 R3 §四 10 项 + patch-round-3 §四 11-12 + 本轮增补）

前置（全部用例）：隔离 USERPROFILE 数据目录；确认 8765 端口占用状态；每项记录后端日志与任务管理器 msedgewebview2 子进程数。

| # | 项 | 步骤 | 预期 |
|---|---|---|---|
| 1 | D2 前置：`AdditionalBrowserArguments` 合并 vs 顶替 | 开 web_cdp 重启；web tab 开启后 `curl 127.0.0.1:9222/json/version` 与 `:9223/json/version`；主 UI 右键检查 Console 核对进程特性 | 顶替：9223 生效且 web tab 进程不吃环境变量（W1 纵深成立）；合并：9222 被争抢需换端口 |
| 2 | D2/W4：9223 触达网页 tab | `/json/list` 应含网页 tab 的外部 URL target；devtools_evaluate 取其 `document.title` | AI 可读写网页 tab 内容；9223 被占时浏览功能不受损 |
| 3 | 地址栏 `javascript:` 经 Navigate | 应用 A10' 前在基线测：地址栏输入 `javascript:alert(1)` 回车 | 预期静默拒绝/报错页；若执行则 A10' 拦截为必要 |
| 4 | A1 回归：三条外链链路 | ①Claude 回复外链点击 ②网页 tab 内 target=_blank ③主 UI window.open | 均开新网页 tab，无「点不开/被系统浏览器抢走」回归 |
| 5 | D1'' `dispose_all` 真实回收 | 开 2+ 网页 tab → 右键重新加载 → 查后端日志与子进程数；新开网页 tab 显隐正常 | 控件全回收；无「控件盖 UI」残留；seq 水位归零后切 tab 立即生效 |
| 6 | N2 后 pywebview 内部 load | 拖 .html 进主窗口；构造 `window.open('about:blank')`；ctrl+点击 file: 链接 | DnD 通道不受影响；非 http(s) 新窗口请求被吞且无崩溃 |
| 7 | A10' 放行 scheme 的 Navigate | 地址栏输入 `mailto:test@example.com`、`ws://x` | 预期报错页/静默失败；若拉起外壳（邮件客户端）需产品拍板 |
| 8 | N3/W22 回归 | 侧栏 ✕ 关网页 tab；抽屉「全部关闭」关网页组；随后 resize 窗口 | 后端日志见 dispose；resize 后其余控件布局正常（不再 50×50）；无 `/api/disconnect` 噪音请求 |
| 9 | a551 浮层 × 原生控件叠放 | 网页 tab 激活时依次开：新建连接 modal、右键菜单、收藏夹菜单 | 控件即时隐藏、浮层完整可见；关闭浮层后控件恢复 |
| 10 | 休眠真机 | 网页 tab 切走 ≥10min → 切回 | 自动唤醒恢复栈顶真实 URL；其余 tab 不受影响；切回即显（不等巡检） |
| 11 | N5 回归 | localStorage 写 `'web-favs' = "just-a-string"` → 开收藏菜单、面板点 ★ | 菜单可开、存储自愈回 `[]`、无报错 |
| 12 | N1'/N4 回归 | 靶标 301/302/307/308 跨协议链各一；私网自签 https 直取；404 目标；非 ASCII 主机 | 链路贯通且每跳按 host 重分类（公网段验证生效）；私网自签可读；404 →「目标返回 HTTP 404」（W30 修复后）；非 ASCII →「不支持该主机名/地址编码」 |
| 13 | W28/W29 复核 | A→B→C 跨站后按 ◀ 两次；休眠唤醒/阅读退出后按 ◀ | ◀ 行为正常但会话栈膨胀（W28 预期）；唤醒后首次 ◀ 落白屏且地址栏停留旧 URL（W29 预期）——修复后应恢复真实前页 |
| 14 | A4'' 失败注入（可选） | 临时破坏 UDF 目录权限使 `EnsureCoreWebView2Async` 失败 → 开网页 tab | tab 被前端关闭 + 红色 banner（`__webTabDead` 送达）——证明通知链通 |

---

## 六、已排查未发现问题（防 R5 重复）

1. A4'' `err` 固化彻底性（`_rm` 全部闭包引用逐一核对无第二晚绑定；`json.dumps(err)` 无再求值）。
2. N3 全链：`closeConnection` 转发 → 包装器清理 → `_edCloseNow` web 兼容性（逐段守卫核验）→ 自动回切 `activePortId/_hgTabBack` 语义 → 包装器重入的 `prev/_webActivePid/activeWeb` 三态 → 双击重复关闭幂等。
3. util.js 批量分支插入位置（TDZ/busy 守卫/快照语义）。
4. A10'' 全空格边界（基线行为未变）；面板/顶栏 banner 文案去重。
5. A8'' 三处调用点与 `_webFavMenu` 重建顺序无依赖。
6. N4 `_hint` 覆盖面（URLError 包装族/TimeoutError 实际形态/ValueError）。
7. N5 filter 恒等不回写、双重裁剪次序、`__proto__`/null/数组元素、setItem 异常路径。
8. N1' HTTPError-Location 可靠性（源码级确认）、303/307/308 GET 语义、urljoin 相对跳转、控制字符 Location 发送层拒、5MB 仅最终响应、for-else/resp=None 无悬挂、he.fp 引用计数关闭。
9. 三份补丁叠装：hunk 零冲突（web-panel.js 七补丁行段对账）、语义零作废（A4/A8/A10 三条修订链、N1→N1' 替换、A2+N2 串行）、epoch 后缀格式下游兼容（sortKeyFn/_webByTabId/N3 正则）。
10. B10 矩阵 = A8' 验收基线、B11 = N1' 佐证、B13 = N5 佐证、B14 = D1''/D3 佐证、B15 = A7 佐证——黑盒 R3 五项与补丁的对接关系全部成立。
11. 基线测试隔离复跑：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**。
12. `HTTPError.status/.code` 属性与 `http_error_302` 的 `redirect_request=None` 传播路径（源码级核验）。
