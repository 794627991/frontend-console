# 内嵌浏览器（路线 A）白盒对抗审计 · 第 3 轮

- 基线：d9c8886 未变；输入材料：`patch-round-2.md`（A4'/A8'/A10'/A11'/D1'/N1/N2 + D7/D4'）、`round-2-blackbox.md`（B7/B8/B9）首次研读
- 方法：补丁逐条攻击（含 CPython 语义实验：except 变量闭包捕获的隐式 `del e` 实测复现 NameError）+ 判定表全量对账（grep 基线 17 个 `_webCur()` 调用表达式）+ 关闭路径全链路追踪（tab ✕ / 侧栏 ✕ / 批量关闭 / `__webTabDead`）+ 测试质量评审 + 逐 hunk 复核
- 铁律遵守：零代码修改；pytest 隔离 USERPROFILE（本轮复跑 **20 passed**）

---

## 一、补丁对抗评审

### A4'（失败推送并入 `_rm`）—— **引入新 bug，见 W21；控件回收半边核验通过**

除 W21 外核验：
- 「重复异常安全性」：两次失败的 `_init_done` 各自产生独立 except 块、独立 cell、独立 `_rm` 闭包——无交叉污染；同一 tab 只会失败一次（失败后已出 `_ctl`，后续 create 走全新建）。
- `json.dumps(tab_id)` 编码安全；`__webTabDead` 前端块维持不变的安全性沿袭 R2 结论（同步 find + `_edCloseNow` 同步清理）。
- 既有代码无同类隐患：grep `web_tabs.py` 全部 `except ... as e` 的 `e` 均为**块内立即消费**（`_log`），无延迟闭包引用——W21 为 A4' 独有引入。

### W21【P2·补丁引入】A4' 的 `_rm` 闭包捕获 except 变量 `e`，块尾隐式 `del e` 清空 cell → 延迟执行时 `str(e)` 抛 NameError 被吞，`__webTabDead` 永不送达（换机制重演 W14 的自失效）

- 位置：patch-round-2.md A4' diff——`def _rm(): ... json.dumps(str(e)) ...` 定义在 `except Exception as e:` 块内、经 `self._ui(_rm)` **延后**到 UI 线程执行。
- 确凿依据（运行时实测，Python 3.14.7）：CPython 在 except 块结束时对 `as e` 变量执行隐式 `del e`；`e` 被内层函数引用时是 cell 变量，`del` 清空 cell → `_rm` 稍后执行 `str(e)` 抛 `NameError: cannot access free variable 'e' where it is not associated with a value in enclosing scope`。实测脚本完整复现：`inside_block` 正常、延迟调用 `pushed=None`、异常被 `_rm` 内层的 `except Exception: pass` 吞掉。
- 后果链：`_rm` 前半段（Remove/Dispose，在 NameError 之前、独立 try 内）仍生效 → 死控件被回收 ✓；但推送段 `json.dumps(str(e))` 的 NameError 恰落在 `ExecuteScriptAsync` 外层 try 内被吞 → **`__webTabDead` 永不送达 → 前端 tab 永远空白假活、无提示**——A4' 宣称的「通知前端关 tab」半边完全失效（W14 是线程亲和异常，W21 是 NameError，同一自失效结局）。
- 修复方向：在 except 块内先固化 `err = str(e)`，`_rm` 闭包改捕获 `err`（普通局部变量，无隐式删除问题）；R3 建议测试 #10 的断言应同时钉住「经 BeginInvoke 通道」与「消息非空」。

### A8'（`_webCur()` 变体族参数化）—— 方向正确；判定表 20 项全量对账**同意**；遗留 3 个无参调用点，见 W26

- 判定表逐项复核（grep 基线实际 17 个调用表达式，全覆盖；表内 :365 为注释行、:502/:553/:564/:576 与实际 def 行 :501/:553/:564/:576 一致——无漂移）：
  - **:46 `_webSessionSave` 归 D5 —— 同意**。单槽会话模型下「保存激活 tab 的栈」就是该槽的语义；`__webTabUrl`（:325）在后台 tab 更新 `_nav` 后触发保存，写入的是激活栈——与模型自洽（后台 tab 的导航变更本就不入会话槽），非 B7 变体。
  - **:99** 紧随 `switchTab(pid)`，wrapper 已置 `_webActivePid=pid` → `_webCur()` 恒等于目标 —— 同意。
  - **:280 `_webCtlVisible` / :365(注释):373 浮层联动 —— 同意**。屏幕上同时至多有一个网页控件=激活 tab 的，显隐/浮层联动天然是「激活语义」（a551 正是按此设计）；:373 的 `anyOverlayOpen` → 藏当前屏上控件无错位面。
  - **:689/:694/:698 收藏夹菜单 —— 同意**。入口是顶栏 tab 栏的全局 ★ 按钮，作用对象=「当前浏览上下文」即激活 tab；`data-fav-i` 点击走 `buildWebPanelTab(f.url, newTab)` 与 `_webCur` 无关。
  - :395（A8 已参数化）、:201/:211/:495/:502/:553/:564/:576（本补丁修订）—— 一致。
- `connections[(wrap && wrap.dataset.portId) || ''] || _webCur()` 取值链核验：`wrap.dataset.portId` 在 `buildWebPanelTab` 创建时设置（:124）✓；**无 wrap 的调用点回落正确**——`_webFavMenu` 的 `_webAct('star')`（:744）与 errLayer 的 `_webAct('read'/'sys')`（:187-188）不传 wrap → 回落激活，均为激活语义入口，A8' 不破坏 ✓。
- 6 处调用点补齐核对：`_webApplyZoom` 全部 3 处（:206/:214/:411）✓、`_webReaderToggle` 全部 3 处（:405/:582/:586，`skipRestore=false` 语义正确——重载重取正文）✓、`_webSyncUI` :412 ✓——**但 `_webSyncUI` 还有 3 个无参调用点未列入，见 W26**。
- 「第 7 处变体」结论：**存在，即 W26**（详见第二节）。

### W26【P3·补丁修不干净】A8' 参数化 `_webSyncUI` 后遗留 3 个无参调用点，回落激活造成按钮态失步（其中 :732 用户可达）

- 位置：`web/js/web-panel.js:611`、`:615`（`_webAct` star 分支）、`:732`（`_webFavMenu` 删除收藏分支）。
- 依据：A8' 把 `_webSyncUI(c)` 参数化却未改这 3 处——
  1. :611/:615：B7 场景（合成/AI 驱动对非激活 tab 点 ★）下收藏落 `c` 的 URL，但 `_webSyncUI()` 更新的是**激活 tab** 的星标按钮——用户点的那颗 ★（在 c 的 wrap 里）状态不变；
  2. :732：**真实用户可达**——收藏夹全局菜单里删除某条收藏，若该 URL 恰是某个**后台**网页 tab 的当前页，该 tab 的 ★ 保持高亮（脏态），直到下次导航才被 `_webSyncUI` 纠正。
- 修复方向：三处传入对应 conn（:611/:615 传 `_webAct` 的 `c`；:732 遍历 `connections` 找 `f.url === `_nav 栈顶` 的网页 tab 逐个 sync，或接受轻微脏态在注释声明）。

### A10'（白名单收窄 + 面板反馈）—— 面板侧干净；顶栏侧漏配，见 W23

- 正则核验：`/^(file|javascript|data|vbscript):/i` 拦截 → `return ''`；`/^(https?|about|mailto|ftp|ws|wss):/i` 放行（/i 大写兼容；trim 先行）✓；`about:blank` 仍可达（会话/内部语义）✓。
- 面板地址栏反馈：`if (!u) { if (urlInput.value.trim()) showBanner(...); return; }` —— 正确区分「空输入静默」与「非法协议提示」✓。
- `mailto:`/`ws:`/`ftp:` 放行后经 `Navigate` 的真实行为未实测（WebView2 对非 http 协议可能是报错页/外壳启动）——列入桌面端清单 #7。
- **W23【P3·补丁漏配】拦截反馈只加在面板地址栏；顶栏把「非法协议」静默当「空输入」→ 误开一个会话恢复空 tab**。位置：`web/js/web-panel.js:676`（`if (!u) { buildWebPanelTab(); bar.blur(); return; }`，A10' 未触及）。顶栏输入 `file:///C:/x` → `_webNormUrl` 返回 '' → 走 a556 的「空回车=开网页 tab（恢复会话）」语义 → 用户得到一个无关的空 tab + 零反馈。修复方向：顶栏同样加 `if (bar.value.trim() && !u) showBanner('该协议不允许在内嵌浏览器打开',…)` 后再走空输入分支。

### A11'（补删 `import threading`）—— 干净
删后 `src/web_tabs.py` 模块级 import 仅剩 `json`（`json.dumps` 多处使用 ✓）；其余 import 全部为函数级延迟导入（`os/clr/webview/System/...`），各有使用，无新孤儿。

### D1'（纪元令牌 dispose_all）—— 设计成立；有一个空洞，见 W24

核验通过的部分：epoch 与 A3 `_cancel` 叠加（dispose cancel 路径清 `_pend_nav`，epoch 记录随创建写入——cancel 的 tab 无 epoch 残留问题，见下小项）；「epoch ≥ 已见最大纪元才 reset_session」正确防旧纪元 beacon 打回新页面 seq 水位；epoch 前缀 id 与 `startsWith('web:')` 兼容（R2 已核）；旧调用无 epoch 按「无主」跳过——混合版本窗口小（`no-cache` 头使旧 JS 缓存罕见），可接受。
- 小项（观察，不计号）：「`_epochs` 随 dispose 清理」需同时覆盖 A3 的 cancel 路径与 A4' 的失败回收路径（补丁只写了 dispose）——漏清只是条目级小泄漏；同毫秒双页面纪元碰撞概率可忽略，建议 epoch 追加随机后缀。

### W24【P2·补丁空洞】D1' 的 `dispose_all(epoch)` 只遍历 `_ctl`，不覆盖 `_pending`/`_cancel` 在途 create——刷新落在 create 在途时孤儿照建，且纪元隔离使其永不可回收

- 位置：patch-round-2.md D1' 设计（基线 `dispose_all`：`for tid in list(self._ctl.keys()): self.dispose(tid)`，web_tabs.py:400-402）。
- 触发路径：页面卸载（刷新）时恰有 create 在途——`_pending` 中的 tab 不在 `_ctl` → `dispose_all` 看不见 → 无 cancel、无 dispose → 随后 `_build` 照常建控件（W5 原型）。更糟：该控件 `_epochs` 记录的是**旧纪元**，此后任何 `dispose_all(新纪元)` 都按纪元不匹配跳过——**D1' 的纪元隔离把 A3 的修复对这条路径永久关闭**，孤儿直到进程退出。首开 tab 的 create 还有最长 5s 的 env 等待窗口（web_tabs.py:117-122），「首开即刷新」落在窗口内完全现实。
- 修复方向：`dispose_all(epoch)` 同时遍历 `_pending`（匹配纪元 → 走 A3 的 cancel 路径）并清对应 `_epochs`；或 `dispose_all` 直接复用 `dispose(tid)` 对 `_ctl ∪ _pending` 的并集。

### N1（私网回落证书校验）—— 主逻辑干净；重定向绕分类，见 W25

核验通过：多记录混合（任一公网 → 按 public 验证，安全侧）✓；解析失败/空 host → except/empty → public ✓；`getaddrinfo` 一次 DNS 开销相对取页 IO 可接受 ✓；IPv6 `::1`/`fe80::`/`fc00::` 分别命中 loopback/link-local/private ✓；http 明文目标不受 ctx 影响（B8 的内网 http 场景保持可用）✓。
- TOCTOU：检查时解析私网 → 连接时 DNS/hosts 指向公网 → **CERT_NONE 套在公网连接上**（坏方向）；补丁文档只声明了反方向（公网→私网）「收益有限」——两方向都该写明。概率低（需本机解析劫持），维持观察不单列。
- IPv4-mapped IPv6（`::ffff:10.0.0.1`）被 `is_private` 判 False（按 IPv6 处理）——getaddrinfo 正常返回 AF_INET 时不可达此形态，边缘记录。

### W25【P3·设计缺口】N1 按原始 host 一次性分类，ctx 随 urllib 重定向继承——私网目标 302 跳公网 = 不验证的公网连接

- 位置：N1 diff（`web_proxy.py`）——`ctx` 按入口 URL 的 host 构造，`urlopen` 自动跟随重定向（B8 #7 实测 http→http 内网跳转被跟随）且**复用同一 ctx**。
- 触发：`https://<私网自签>/r` 302 → `https://public.example.com` → 后程连接以 CERT_NONE 进行 → 中间人可投喂公网页面正文（阅读视图/发给 Claude 注入）。反方向（公网验证 ctx → 私网自签）表现为取页失败（可用性降级非安全洞）。
- 修复方向：自定义 `HTTPRedirectHandler` 在每次重定向按新 host 重建 ctx；或私网回落仅限 http（放弃私网 https）。

### N2（非 http(s) 一律拦截）—— 干净（全仓调用方逐一核对）

`load_url` 调用方全量 grep 核对：
1. pywebview 内部 2 处（edgechromium.py:261 NewWindowRequest、:306 initial load）——前者是被拦截的目标本体，后者发生在包装安装前（R2 已核）且为回环 http；
2. **`src/snip.py:300/452/457/464` `win.load_url(_page_url())`（4 处）**——`_page_url()` = `http://127.0.0.1:<port>/web/screenshot.html`（snip.py:215-219，回环 http ✓），且截图窗跑在**独立子进程**（`window_main`，不经 `main()` 的类级补丁）——双保险不受 N2 影响；
3. 应用层无其他 `window.load_url` 调用（grep 实证）。
非 http(s) 新窗口请求被静默吞（无用户反馈）——符合 W19 修复方向；`window.open('about:blank')` 从「主窗口被清空」变为「无操作」为净改善。回环 http(s) 双路径确认放行。

---

## 二、B7 变体族终扫（任务 2）

以 A8' 判定表为底的全文件再过：`_webCur()`（17 个调用表达式，全部入表）之外，摸 conn 的其余路径逐个核验——
- 事件回推族（`__webTabUrl/Hist/Title/Load/New`、`__webTabDead`）全部经 tid → `_webByTabId`/`Object.values().find` 精确归属 ✓；
- `__newWindow` → `buildWebPanelTab`（新建，无归属问题）✓；
- 两个 interval（60s 休眠巡检 / 1s 唤醒巡检）遍历 `connections` 用局部 `c` ✓（:495 已被 A8' 参数化）；
- `switchTab` 包装器 / `closeEditorTab` 包装器用 `connections[pid]` ✓；
- `_webSleep(c)/_webWake(c)/_webNavTop(c)/_webCtl(conn,d)/_webCtlSetup(conn)` 均显式传参 ✓；
- **残留变体 = `_webSyncUI()` 的 3 个无参调用点（:611/:615/:732）——已立 W26**；`_webReaderToggle` 内部 `_webCtlVisible(true)`（:514）在「后台 tab 退出阅读态」的合成场景下显隐的是激活 tab 控件——真实使用中 c 恒为激活 tab，不单列（观察）。
结论：无第 8 处漏网；变体族收敛为 W26 的 3 个调用点。

---

## 三、新面狩猎（任务 3）

### W22【P1·新面】侧栏 ✕ 与分组批量关闭绕过 web-panel 关闭包装——后端控件永不 dispose + 幽灵 resize 监听把存活控件缩成 50×50

- 位置：`web/js/sidebar.js:113-151`（`closeConnection` 的编辑器族转发正则只认 `^(edit|hex|diff|bindiff):`，web 落通用清理：`conn.tab.remove(); conn.wrap.remove(); delete connections[portId]`，**无 dispose REST、无 `_ctlResize.disconnect()`、无 `window.removeEventListener('resize', _ctlPush)`、无 `_webActivePid` 清理**）；两条产品可达触发路径：
  1. **侧栏行 ✕**（sidebar.js:238-250）：web tab 的 `data-close` → 非 log/edit/harness/vcs → `else closeConnection(pid)`；
  2. **抽屉分组「全部关闭」**（util.js:229-246 批量循环）：`kind === 'web'` 不在 `isEd` 列表 → `closeConnection(pid)`。
- 后果链（每个被旁路关闭的 web tab）：
  1. 后端 WebView2 控件永不 Dispose → W5 级隐形孤儿（加载完整页面、持有会话，直到进程退出）——a555 修的泄漏面与 R1 补丁 A3 全部只覆盖 `closeEditorTab` 路径；
  2. `window` 级 resize 监听残留：幽灵 `push` 在每次窗口 resize 触发——对已从 DOM 摘除的 wrap 读 `style.display`（残留 'flex'）→ `getBoundingClientRect()` 全零 → 发送 `layout(0,0,0,0)` → 后端 `int(max(0,50))` → **所有存活网页控件被缩到 50×50**，且 `_apply_visibility` 按陈旧 `_want`（可能指向已删 tab）重排显隐——幽灵 actively 致损；
  3. 额外一发注定失败的 `POST /api/disconnect {port_id:"web:…"}`（无害噪音）。
- 修复方向：`closeConnection` 顶部把 `^web:` 与编辑器族一并转发 `closeEditorTab(portId)`（一行）；批量关闭的 `isEd` 列表加 `web` 或同走转发；补一条「侧栏 ✕ 关 web tab → 后端 `_ctl` 清空」的回归用例。

### W27【P3·测试质量】test_web_tabs_logic.py：实现级断言 + mock 时序失真，恰好抹平本项目真实的 bug 类

- 逐项评审（348 行、7 用例）：
  1. **mock 失真（主项）**：`_FakeTask.ContinueWith` **同步立即回调**（test_web_tabs_logic.py:99-101）——真实 ContinueWith 在线程池异步续延；`FakeForm` 的 async 模式只复现 BeginInvoke 队列一层。结果：a549/W14/W21 这一族「池线程续延 × UI 队列」的时序 bug 在测试里结构性不可见；async 模式用例（create 去重、show 守卫）仅覆盖 BeginInvoke 维度。
  2. **名为竞态实为顺序**：`test_show_snapshot_vs_dispose_race` 在 `mode='sync'` 下先跑完 show 再启动 dispose 线程——零交错，「并发不抛」的断言实为顺序冒烟，测试名过度承诺。
  3. **实现级耦合**：断言直接摸 `t._ctl['t1'].Visible`、`cvw.navigated`、`FakeCtl.n_created`——对逻辑层测试可接受（该文件自述不碰真 CLR），但重构即碎，行为等价改写会误报。
  4. **覆盖缺口**：零 REST 层用例（A6 的 `_num` 收口在 `register` 闭包内且 `get_tabs()` 未装配即短路，现状不可测——需拆 handler 或装桩 WebTabs）；零 JS 侧用例；无 W22 双路径关闭、无 `dispose_all`/`reset_session`（R2 已列，本轮补 W22/W24 两类）。
  5. 正面：`test_disposed_event_no_crash`、`test_new_window_fallback_navigates`、`test_env_failed_fast_return` 是行为级钉测，质量良好；CLR 桩的父包占位处理（Microsoft.Web.* 逐级）细致。
- 建议方向（不改文件）：fake task 改「延迟派发续延」可测异步序；新增 BeginInvoke 通道断言（R2 建议测试 #10 已含）；W22/W24 用例；REST 层引入 Flask test client + 桩装配。

### 其余狩猎项（未立号，证据见文末清单）

- **web-favs 写入路径与 100 上限**：写入 3 处（star 前插、菜单删除 splice、批量同上）全部经 `_webFavsSave` → `v.slice(0,100)` 恒裁剪 ✓；读取 try/catch 容错 ✓；收藏去重按 URL 精确串（尾斜杠变体会产生重复条目）——cosmetic 观察。
- **`_webCtlSetup`/`_ctlPush`/`_ctlResize` 生命周期**：a555 修复（wrapper 内 disconnect + removeEventListener）对 tab ✕ / 关激活自动回切 / `__webTabDead` 三条路径覆盖完整；**漏的恰是 W22 的两条旁路**——即本轮唯一泄漏面。
- **:325 / :732 上下文**：:325（`__webTabUrl` 触发 `_webSessionSave`）——单槽模型下写激活栈为设计语义（A8' 判定表 :46 行的延伸，成立）；:732 见 W26。
- **index.html 14 行**：boot 脚本合并（a547 修复形态复核成立）、topbar 三列包裹、topUrlBar（无 type 属性默认 text，无碍）、tabFavBtn、web-panel.js 加载序（terminal-core:522 / editor:538 先于 web-panel:551，wrapper 捕获时机正确）。
- **util.js 9 行**：web 的 label/icon/组序/`sortKeyFn [8]`——`[8]` 与 `_GROUP_ORDER.web=7` 错位为基线既有，相对次序（web 在 proxy 之后）两处一致，良性。
- **settings.js 48 行**：CDP 卡逻辑自洽（POST/重探 GET 分离兜底、`toggleAttribute` 强制态）；其余为文案。
- **style.css 106 行（重点层叠）**：`.web-fav-menu z-index:10001` 与 a551 的 `#webFavMenu` 联动藏控件配套成立（DOM 无法压过 HWND，靠隐藏控件腾出视野）✓；`.web-sleep z2`/`.web-err z3` 仅在控件隐藏时有意义，与 a551 一致 ✓；`.web-body{background:#fff}` 首帧白闪——cosmetic；`.web-bar` flex 无 wrap，极窄窗口挤压输入框（min-width 120px 兜底）——cosmetic；`.top-url-bar:focus max-width 380px` 超出 grid 轨道 300px 时溢出到 gap（无裁剪、不推挤）——与 a480/a482 的取舍一致，观察。
- **`_webCtl` 失败路径**：非 2xx/网络错 → `.catch(()=>({ok:false}))` 全静默——本地单用户可接受；唯一主动致损路径是 W22 的幽灵 push（失败的不是 fetch 而是多发的 ghost）。

---

## 四、桌面端验证清单（双通道均无法无头验证）

| # | 项 | 步骤 | 预期 |
|---|---|---|---|
| 1 | D2 前置：`AdditionalBrowserArguments` 显式设置与 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 是合并还是顶替 | 主程序开 web_cdp；web tab 开启后在 9222/9223 分别 `GET /json/version`；再在主 UI 右键检查 → Console 查 `navigator.userAgent`/特性以辨认进程参数 | 若顶替：9223 生效且 web tab 进程不再吃环境变量（W1 纵深成立）；若合并：9222 被两进程争抢需换端口 |
| 2 | D2/W4：9223 独立 CDP 触达网页 tab | 同上；`/json/list` 应列出网页 tab 的外部 URL target；用 devtools_evaluate 对该 target 取 `document.title` | AI 能读/操作网页 tab 内容（W4 修复达成）；9223 被占时网页 tab 功能不受损（降级路径） |
| 3 | 地址栏 `javascript:` 经 WebView2 `Navigate` 的真实行为 | 桌面实例地址栏输入 `javascript:alert(1)` 回车（A10' 落地后被拦截——需在 A10' 应用前测，或临时以 `__webTabNew` 链路验证） | 预期静默拒绝/报错页（WebView2 文档语义）；若执行则 A10' 的拦截为必要 |
| 4 | A1 回归：三条外链链路 | ①Claude 回复含外链点击 ②网页 tab 内 target=_blank 链接 ③主 UI 内 window.open 外链 | 三者均应开新网页 tab（`__webTabNew`），不依赖同源禁用；无「点不开/被系统浏览器抢走」回归 |
| 5 | D1' `dispose_all` 真实回收 | 桌面开 2+ 网页 tab → 刷新主 UI（右键重新加载）→ 后端日志确认 `_ctl` 清空；新开网页 tab 正常显隐 | 控件全部回收（任务管理器 msedgewebview2 子进程数回落）；无「控件盖住 UI」残留 |
| 6 | N2 后 pywebview 内部 load 行为 | 拖一个 .html 文件进主窗口；`window.open('about:blank')`（经 Claude 回复链接构造）；ctrl+点击 file: 链接 | 拖放仍走 pywebview DnD 通道（不走 load_url）；file:/about: 新窗口请求被吞且无崩溃 |
| 7 | A10' 放行 scheme 的 Navigate 行为 | 地址栏输入 `mailto:test@example.com`、`ws://x`（白名单放行项） | 预期报错页或静默失败；若触发外壳启动（邮件客户端）需产品拍板是否收窄 |
| 8 | W22 修复回归 | 侧栏 ✕ 关一个网页 tab、抽屉组「全部关闭」关网页组 | 后端日志确认 dispose 到达；窗口 resize 后其余网页 tab 布局正常（不再 50×50） |
| 9 | a551 浮层 × 原生控件叠放 | 网页 tab 激活时依次打开：新建连接 modal、右键菜单、收藏夹菜单 | 控件即时隐藏、浮层完整可见；关闭浮层后控件恢复（桌面-only 的 HWND 层级验证） |
| 10 | 休眠 10 分钟真机行为 | 网页 tab 切走 ≥10min → 切回 | 自动唤醒恢复栈顶真实 URL（非 about:blank）；休眠期其他 tab 不受影响 |

---

## 五、已排查未发现问题（防 R4 重复）

1. A4' 重复失败/交叉污染安全性（独立 except 块独立 cell）；既有 `web_tabs.py` 无其他「闭包捕获 except 变量后延迟使用」形态（全量 grep 逐处核对均为块内立即消费）。
2. A8' 取值链（`wrap.dataset.portId` 创建期设置）、无 wrap 调用点回落（`_webFavMenu`/errLayer）、`skipRestore` 传参语义。
3. A8' 判定表 20 项全量对账（grep 17 调用表达式 + def + 注释行逐一归位，无漂移无遗漏）。
4. A10' 正则形态（大写 scheme/trim/空串）与面板反馈逻辑；`about:blank` 通道保留。
5. A11' 后 web_tabs.py 无孤儿 import（模块级仅 json 且在用；函数级延迟导入全部有消费）。
6. N1 多记录混合/解析失败/空 host/IPv6 分类全部安全侧；getaddrinfo 开销评估。
7. N2 全仓 `load_url` 调用方核对（pywebview 内部 2 处 + snip.py 4 处独立子进程回环 http）——无合法调用方被误伤。
8. D1' 与 A3 `_cancel` 的叠加（cancel 路径无 epoch 记录残留问题）；纪元比较/无主语义/前缀兼容。
9. web-favs 三条写入路径 + `slice(0,100)` 恒裁剪 + 读取容错。
10. `_webCtlSetup` 生命周期在 wrapper 覆盖的三条关闭路径上无泄漏（漏网即 W22）。
11. `_webSessionSave` :325/:403 上下文（单槽模型自洽，归 D5 成立）。
12. index.html / util.js / settings.js / style.css 全部 hunk（含 a547 形态、脚本加载序、`sortKeyFn [8]` vs `_GROUP_ORDER 7` 良性错位、`.web-fav-menu` z-index 与 a551 联动的配套性、topbar overflow:hidden 无可达裁剪面）。
13. `_webCtl` 失败路径静默语义（本地单用户可接受）。
14. 基线测试隔离复跑：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**。
