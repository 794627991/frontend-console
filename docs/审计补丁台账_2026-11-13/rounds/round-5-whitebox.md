# 内嵌浏览器（路线 A）白盒对抗审计 · 第 5 轮（收敛判定轮）

- 基线：d9c8886 未变；输入材料：`patch-round-4.md`（N4'/D8）、`round-4-blackbox.md`（B16–B19）首次研读
- 方法：补丁评审（N4' 分支序/D8 方向坑位）+ R4 候选三块静态终扫（逐行推演）+ 双轨历史第三形态排查 + D3 会话语义静态推演
- 铁律遵守：零代码修改；pytest 隔离 USERPROFILE（复跑 **20 passed**）

---

## 一、补丁评审（patch-round-4）

### N4'（W30 修复）—— 干净（一处 nit 观察级）

- **分支顺序**：`except urllib.request.HTTPError as he:` 置于 `except Exception as e:` 之前——HTTPError（URLError→OSError 子族）优先命中，其余落通用分支 ✓；N1' 循环内 `raise` 的非重定向 HTTPError 亦落入专门分支拿到状态码 ✓；重定向 HTTPError 已在循环内消费、不会误入 ✓。
- **`getattr(he, "status", "?")` 兜底**：本项目 Python 3.14 实测 `HTTPError.status` 存在 ✓；**nit（观察）**：`status` 是 3.9+ 属性，更老解释器回落 `"?"`——更稳写法 `getattr(he,"status",None) or getattr(he,"code",None) or "?"`（`.code` 为实例属性，类级 hasattr 探不到，已在 R4 验证）。不构成缺陷。
- 通用分支的 `_hint` 映射与其余路径沿袭 R3 评审结论 ✓。

### D8（W28+W29 设计）—— 方向可行；三个坑位作为观察登记（同意「不单独热修、与 D 栈同批」）

1. **「前端打标志消费下一条 SourceChanged」对重定向脆弱**：一次 GoBack 可能触发**多条** SourceChanged（30x 链每跳一条）——单标志会吞掉第一条后把后续真实导航误分类。更稳的替代：**期望 URL 对账**——前端 back/fwd 时把预期栈顶 URL 一并下发（`_nav` 栈本来就是前端权威），`__webTabUrl` 按预期对账归类 pop/replace/push；对不上（重定向落点）时按现规则入栈并回写预期。
2. **「Navigate 后 GoBack 剔除」存在提交时序坑**：GoBack 在导航未提交时无效/被吞 → about:blank 条目残留（W29 半修）。替代：内部导航优先 `GoBack/GoForward` 回真实条目（原生历史里就在），仅在无可回条目时才 `Navigate`；或接受残余并文档化。
3. **必须保持的既有语义**：a556 的 about:blank 事件过滤、`_webNavTop` 跳脏栈顶、A8'/B10 的 tab 归属语义——patch §二风险注记已完整列出，**同意**「导航语义重写不单独热修、与 D 栈（W3/W4/W8/D1''）同批实现同批验证」。

---

## 二、静态可达清单终扫（R4 候选三块 + 双轨第三形态 + D3）

### ① `_webSleep`/`_webWake` 状态机角落 —— 发现一例，W31；其余干净

- **W31【P2·基线】切回阅读态网页 tab：switchTab 包装器缺 reader 守卫，原生控件盖住阅读视图，UI 态与实态相反**
  - 位置：`web/js/web-panel.js:436`（`_webCtlVisible(true)` 无条件执行）；对照 `:376`（overlay-sync 的 show 分支有 `!c._ui.reader` 守卫——两处不对称即缺陷证明）；阅读态入口 `:509-523`（`rd` 显示 + `host` 隐藏 + 控件隐藏）。
  - 触发路径（纯 GUI 可达）：网页 tab A 开 ☰ 阅读（控件隐藏、阅读视图显示）→ 切到网页 tab B → 切回 A → 包装器 `isWeb` 分支只处理 `sleeping`（:433-435），**未检查 `reader`** → `_webCtlVisible(true)` → 后端显示 A 控件 → **HWND 原生窗口压在阅读 DOM 之上**，用户看到实时网页而非阅读正文；`c._ui.reader` 仍为 true、按钮态不变。
  - 无自愈：overlay-sync 的 show 分支被 `!reader` 挡住、且**没有**「reader 态下控件可见 → 纠正隐藏」的分支；60s 休眠巡检与 1s 唤醒巡检均不涉 reader 显隐。状态保持到用户再点一次 ☰（toggle 关闭并恢复）或切走再切回（再次触发同缺陷）。
  - 修复方向：:436 改为 `if (!c._ui.reader) _webCtlVisible(true);`（照抄 sync 的守卫条件），或 reader 态切回走 `_webCtlVisible(false)`。
- 其余角落逐项推演**干净**：①抽屉折叠（A7 落地后）不产生绕过 switchTab 的 wrap display 翻转——非激活 tab 本就 none、激活 tab 不折叠，休眠计时不误计；②`visibilityState` 中途切换：最小化期计时冻结（不重置不清零）语义可接受，激活 tab 在 hidden 期走 else 分支清零 ✓；③reader×sleep×多 tab 矩阵：巡检跳过 reader/sleeping、唤醒路径不触碰 reader 态、B 休眠不影响 A 阅读（`_apply_visibility` 排他显示对已隐藏的 A 幂等）；④create 在途时休眠：nav 落空（no tab）、show(false) 走 `_want` 记账，切回由包装器唤醒 + 在途 create 的原始 URL 兜底 ✓；⑤`_hidSec` 生命周期（sleep 不清、wake 清零、重藏重计）✓；⑥休眠 tab 作为 `_webCur()` 的入口不存在（关闭自动回切必经包装器唤醒）✓。

### ② `_webFavMenu` 其余分支 —— 干净

- **恢复上次网页（无 URL 分支）**：`data-fav-resume` 仅在 `_wc = _webCur()` 存在且栈顶非空时渲染（:694-696）→ 有网页 tab 时点击 = `buildWebPanelTab()` → `pid && !newTab` 路径聚焦现有 tab（其栈顶正是标签所示 URL，label 与结果一致）；无网页 tab 时**该项根本不渲染** → 不存在「标签承诺恢复却给空白」的谎言面 ✓。开机一次性 `_webSavedNav` 与菜单恢复是两条独立路径，互不干扰 ✓。
- **定位/视口钳制**：`offsetHeight` 在 appendChild 之后读取（测量正确）；先上后下 + 视口双钳制；`max-height:60vh + overflow-y:auto` 兜住 100 条超长菜单 ✓。
- **close 监听清理**：自清理式（下次 document click 上 `list.contains` 为假 → removeEventListener）——菜单被 item 点击 `list.remove()` 或 ★ 双击 `old.remove()` 后，旧监听最多存活一次点击，有界非泄漏 ✓；`anchor` 的 stopPropagation + `ev.target !== anchor` 防开菜单即关 ✓。
- **删除分支索引**：`data-fav-i` 渲染期定格、单线程内点击、删后重建菜单——无 stale index ✓；B18 的怪异元素面已被 N5 过滤器覆盖 ✓。

### ③ `main.py _patched_ready` 交互面 —— 干净

- **强制右键 × a483 全局 preventDefault**：时序正确——pywebview `_orig_ready` 先按 debug 设 `AreDefaultContextMenusEnabled`，补丁后置覆盖为 True；DOM 层 web-panel.js 捕获阶段对 `.web-body` 外 `preventDefault` 恰好压制原生菜单、`.web-body` 内放行——两层设计互恰，无冲突面 ✓。
- **`load_html` 等包装外方法**：`NavigateToString` 路径不经 `load_url` → 不受 `_safe_load` 影响 ✓；全仓无应用级 `load_html`/`load_url` 调用方（R2 已核，snip 为独立子进程）✓。
- **与 `_safe_load` 的时序**：包装安装于 `_patched_ready` 末尾；initial load（edgechromium:306）在 `_orig_ready` 内、包装前执行 ✓；NewWindowRequested 最早也只能在 ready 后由交互触发 → 必经包装 ✓；`_patched_ready` 整体失败（import 失败）→ 无包装、无右键、无 WebTabs 装配 → REST 「未装配」优雅降级，工具其余功能完好（代码注释已声明）✓。

### 双轨历史第三形态排查（reload / Ctrl+R / SPA）—— 无新形态

- `reload` → `CoreWebView2.Reload()` 重载当前条目：**不加历史项**；SourceChanged 同 URL → 同 host 原地覆盖规则 → 栈顶原值更新，无膨胀 ✓；落在 about:blank 上 reload = 重载空白（W29 的次生无害面）。
- SPA `history.pushState`：触发 SourceChanged → 同 host 原地覆盖 → SPA 路由被正确跟踪、无污染 ✓；页面内 `history.back()` → 原生回退 → 跨站 push 污染（W28 已覆盖，非新形态）。
- `__webTabNew` 新 tab：全新控件全新历史，无交互 ✓。
- 结论：双轨失步收敛为 W28（back/fwd 污染）与 W29（内部导航进历史）两形态，无第三形态。

### D3 会话语义静态推演 —— 无新缺陷（W8 维持）

- 事件单播（`_main_cvw` 唯一目标）、sq 全局单水位、Bounds 后写者胜——三项 W8 结论在 D1''（纪元后缀 id）落地后依然成立：纪元只解 **tab id 撞名**（B14），不解 **sq 水位互弃**与 **broadcast 缺失**——与 patch-round-2 D1' 注记、patch-round-4 §五的判断一致 ✓。
- D3 的「检测第二 UI 即拒绝」需要注册握手（首访 layout/show 携带 epoch 登记会话）——静态推演可行，无结构障碍；登记前的窗口期（第二客户端首批请求）仍会串——实现评审时须覆盖。
- B14 的跨客户端浮层串隐在 D1''+D3 组合下的残余：D3 落地前 B14 维持确凿。

---

## 三、正式收敛结论

**本轮产出 1 条确凿（W31，P2）。静态白盒面在此条之后宣告穷尽——R1–R5 确凿序列 13→7→7→3→1，全部为 P2/P3 收尾项，无 P0/P1 级新面存留于静态可达域。**

### (a) 双通道（白盒×黑盒）已穷尽的面
1. `src/web_tabs.py` 全部：生命周期（create/dedup/cancel/dispose/init 失败）、命令族、REST 入参、Bounds 布局、事件推送、线程亲和、锁语义。
2. `web/js/web-panel.js` 全部：tab 管理、工具栏按钮族（B10 矩阵收口）、地址栏双入口、阅读模式、休眠/唤醒、收藏夹全分支、发给 Claude、浮层联动、switchTab/closeEditorTab 包装器、`_webCtl` 失败路径。
3. 双轨历史：归属语义（B1/B7 族）+ 内容语义（W28/W29/W31）+ 第三形态排查（无）。
4. `/api/web/fetch_text` 全对抗面：scheme、重定向（自动/手动/环/跨协议）、证书、截断、头反射、并发、编码、错误文案。
5. `web-favs`/`web-session` 容错与畸形全格；`_webCtlSetup` 生命周期与三条关闭路径（W22/B16/B17 收口）。
6. CDP 链：解禁双路、端口绑定、目标过滤、devtools_cdp 全文。
7. `main.py` 启动参数、`_patched_ready`/`_safe_load`、`web_cdp` 配置链；util.js 抽屉/关闭分派/sidebar `closeConnection`；index/settings/style 各 hunk。
8. 四份补丁（patch-round-1..4）逐条对抗 + 三/四份叠装一致性；测试质量（W27）与 20 用例基线。

### (b) 移交桌面验证手册的面（双通道均不可达，手册 14 项见 round-4-whitebox §五）
per-monitor DPI 与 `Form` 原点假设、a551×HWND 叠放矩阵、休眠 10 分钟真机全链、target=_blank 真实流、加载失败层、`_ensure_env`/`install` 二次装配（主窗重建路径）、`javascript:` 经 Navigate 真实行为、A1 三条外链回归、D1'' dispose_all 真实回收、N2 内部 load、N3 幽灵 layout 桌面级后果（B17 的 50×50 存疑项）、W31 修复回归（建议并入手册）。

### (c) D 栈实现后必须重审的面（实现评审清单，供补丁应用后使用）
1. **D1''**：`dispose_all(epoch)` 对 `_ctl ∪ _pending` 并集处置与 A3 cancel/A4'' fail 路径的 `_epochs` 清理是否齐全；`reset_session` 的 epoch≥max 门控与新页面 seq 恢复；pagehide beacon 与新页首批 create 的时序（W20 残留验证）；epoch 随机后缀的下游兼容回归。
2. **D2**：`AdditionalBrowserArguments` 合并 vs 顶替语义（手册 #1）；9223 被占降级路径；devtools 多端口 target 发现与 tab→target 映射的正确性（`find_page_target` 改造后不得重新引入 origin 过滤盲区）。
3. **D3**：会话注册握手前的窗口期、事件扇出后端实现（SSE/队列）不引入新注入面、Bounds/`_want` per-sid 隔离、「拒绝第二客户端」的判定点。
4. **D8**：W28/W29 导航语义重写——回归 B10 十二格矩阵、a556 about:blank 过滤、`_webNavTop`、会话恢复语义；重定向多 SourceChanged 场景（观察 1）。
5. **D5/D7**：web-session 写权归一；fetch_text 内网标记与 D7 拍板项落地形态。
6. **A 系全量落地回归**：20 用例 + patch §五 21 类新增用例；W31 修复纳入 A8'' 批次（同函数族）。

---

## 四、已排查未发现问题（终版防重复清单）

1. N4' 分支序与 getattr 兜底（nit：老解释器 status 缺失回落 "?"）。
2. D8 方向三坑位（标志消费的重定向脆弱性 / GoBack 剔除的提交时序 / 既有语义保持）——均已登记为设计观察。
3. 休眠状态机六角落（抽屉翻转/visibilityState/reader×sleep×多 tab/create 在途/`_hidSec`/sleeping-as-cur 不可达）。
4. `_webFavMenu` 恢复分支语义自洽（无网页 tab 时不渲染、不存在「承诺恢复却空白」）、定位钳制、close 监听自清理、删除索引新鲜度。
5. `_patched_ready` 三交互（右键×preventDefault 时序、load_html 旁路、`_safe_load` 包装时序与失败降级）。
6. 双轨第三形态：reload 不加历史项、SPA pushState 走同 host 覆盖、`__webTabNew` 隔离——均无污染。
7. D3 静态推演（单播/sq/Bounds/注册握手可行性）——无 W8 之外新缺陷。
8. B16/B17（N3 验收基线：dispose 缺失 + 幽灵 layout 请求级实证 + 后台态 display:none 守卫细化）、B18（N5 七格验收基线）、B19（N1' 验收基线：12 跳环 0.098s 优雅失败、CERT_NONE 跨主机实锤）——四条与补丁的对接关系全部成立；B17 的桌面级后果维持「手册 #11 存疑」。
9. N3 第二 hunk 的可达性时序（A7 落地前 web 不进抽屉——应用顺序约束已确认）。
10. 基线测试隔离复跑：`USERPROFILE=<临时目录> python -m pytest tests/test_web_tabs_logic.py tests/test_web_fetch.py -q` → **20 passed**。
