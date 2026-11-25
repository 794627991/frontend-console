# Redteam B · 网页 tab 域并发/线程模型攻击报告

- **生成**：2026-11-16
- **对象**：基线 HEAD `480c07d`（v4.1.0-a583），工作树含他人未合改动（`src/server.py` 等 M 项，与本审计无关）
- **攻击者**：并发攻击者 B——专属攻击面 `src/web_tabs.py` 全部共享可变状态（`_ctl/_want/_want_seq/_epochs/_pending/_cancel/_env/_rect/_layout_seen/_cdp`）+ 线程模型 + `web/js/web-panel.js` 可见性推演
- **性质**：对抗审计——只报告不修复；唯一写入本报告；git 仅 diff/log/show/grep/status；探针全部位于临时目录 `%TEMP%\rtb_conc_probe\`（未进仓库）
- **方法**：
  1. **真实多线程 Python 探针**（核心手段）：`importlib` 从仓库原样加载 `web_tabs.py` 源码（共享状态逻辑零改动），仅对 CLR 面做桩（`System/System.Drawing/System.IO/Microsoft.Web.WebView2.*`），模拟三种线程：Flask 线程（`threading.Thread` + Barrier 对齐）、UI 线程（BeginInvoke 队列三形态：同步 / backlog 积压 / 真实泵线程）、ContinueWith 池线程（`FakeTask` 延迟回调）。确定性场景 RB1–RB6 + 随机交错模糊（6 Flask 线程 × 40 操作 × 400 轮 = **96,000 次命令下发**，不变式 I1 孤儿 / I2 可见≤1 / I3 水位单调 / I5 双建 / I6 陈旧隐藏）。
  2. **node 模糊执行器**：从 `web-panel.js` **原样提取** `_webReconcileVis`/`_webCtlVisible` 函数体（仅 `++_webCtlSeq` → 盒变量以跨调用持久化），随机操作序列（开/关/切换/阅读/休眠/浮层/残留 flex/周期推演）**10,000 序列 × 12 操作**，断言推演不变式（winner=max-sq 命令必须等于 first-want-match；无目标时不得有 show-winner；双 show 必须 sq 序保护）。
  3. **机械复核**：`USERPROFILE=$(mktemp -d) python -m pytest tests/ -q` → **274 passed, 1 skipped, 10 subtests passed (19.07s)** ✅；`py_compile src/web_tabs.py` ✅；`node --check web/js/web-panel.js` ✅

---

## 一、总体结论

线程模型 = Flask threaded（`main.py:964` `threaded=True`，每请求一线程）+ UI 线程 BeginInvoke 队列 + ContinueWith 池线程（`_wire._init_done`、suspend `_done`）+ JS 侧 5 个 `setInterval`（60s 睡眠巡检 / 1s 唤醒 / 2s 推演 / 3s MO 补挂 / 2s owner 心跳）+ pagehide beacon——**全部无锁共享**。逐字段 GIL 原子性成立（tuple/int/set/dict 单操作），但**复合「检查→操作」普遍不原子**，且退出路径（`flush_on_exit` 在 `close_all_ports()` **之前**跑，`main.py:1250→1252`）留下 1.2s 活 Flask 窗口。

**确凿发现 8 条：高 2 / 中 3 / 低 3**（另有 2 项负结果 + 2 项专项证伪）。最重的一条（RB2）是 `dispose_all` 自己刚写入的 `_cancel` 标记被自己调用的 `reset_session()` 清掉，**300/300 确定性复现已取消 tab 的控件复活**。

| 编号 | 级 | 摘要 | 探针证据 |
|---|---|---|---|
| **RB2** | **P1** | `dispose_all` 的 `reset_session()` 清掉它刚加的 `_cancel` 标记 → 已取消的在途 create 复活为隐形孤儿控件（父挂 + 入 `_ctl` + 走完整导航链，`_epochs` 已被 pop → 后续按纪元回收永不命中，只能靠 panic `dispose_all(None)`/退出清除） | **300/300** 轮确定性复现 |
| **RB4** | **P1** | 刷新后 seq 水位失配（任务书 ④，**D1 未完全落地**）：三变体全实证——(a) 逐个关 tab 后刷新：`dispose_all(E1)` recycle=0 → W40 跳过 reset → 旧水位压死新页全部 show；(b) beacon 丢失：无任何 reset 路径；(c) reset 后旧页迟到 sq 重新抬升水位（**show 无 epoch 标签**）→ 二次全丢 | 三变体各 **10/10 命令被丢弃**；模糊跨纪元互踩 **×1039**/400 轮 |
| **RB1** | P2 | flush 退出竞态（任务书 ①）：`_ctl.clear()` 后 1.2s grace 内 Flask 仍服务——**证伪崩溃假设**（get→None 走 no-tab；快照内已 Dispose 控件再 Dispose 幂等，桩计数实证无异常），**实害=停摆**：`_env=None` 但 `_env_failed=False` → 每个 create 烧 50×100ms 重试 = **每个 Flask 线程钉死 5s** 后才回 err | RB1 120 轮 0 崩溃；RB1b 时间缩放实测 0.13s→真实 ~5s |
| **RB5** | P2 | suspend 抓帧异步窗口（100-300ms）：`CapturePreviewAsync` 完成回调 `_after` **无条件** `ctl.Visible=False`，不回查 `_want`——窗口内的更新 show 被陈旧完成回调隐藏（用户正看的 tab 闪黑，恢复靠下一拍推演 ≤200ms/2s） | **100/100** 轮复现；模糊 I6 自然命中 ×14/400 轮 |
| **RB6** | P2 | flush 边界 zombie：create 在 Flask 线程过了 `_env` 检查，`_build` 在 flush 置 `_env=None` **之后**才被 UI 线程执行（BeginInvoke 延迟=窗口，UI 积压下达秒级）→ `EnsureCoreWebView2Async(None)` 异常被 `_wire` 的 try 吞 → 父挂+入 `_ctl` 的僵尸控件，`ok:True` 已回执前端，无恢复路径 | **50/50** 轮复现 |
| **RB3** | P3 | show sq 门读-比-写非原子（任务书 ③）：强制抢占（延迟 gate 读取）**50/50** 水位回退且陈旧 `_want` 胜出（此后 `sq<=新低水位` 的重复旧令重新获准入内）；真实 GIL 20,000 轮 × 4 线程 **0 命中**（窗口 ~百 ns，需双请求 µs 级同时）→ 结构成立、现实概率极低 | 50/50 强制 / 0/20000 自然 |
| **RB-JS1** | P3 | 推演 `_a` 空值旁路（R9.3 单真值回落）：`connections[activePortId]` 为 undefined 时 `!_a` 短路 `actWeb===c` 守卫 → 残留 flex 的 web wrap（字典序第一个）被推演**显示**（hwnd 盖 UI）。真实路径 `activePortId=null ⟺ 全 tab 关闭 ⟺ 无 wrap`（唯一写 null 处 editor.js:1534）→ 纵深缺口非现行 bug | node 模糊 V4 ×824 建模命中 |
| **RB-JS2** | P3 | 推演无节流上限：class 高频 churn 页面（动画/加载指示）每事件循环 tick 合并一次推演，每次 ≥1 fetch（R9.14 恒发）+ 30ms `_ctlPush`——无绝对频率上限；**无自反馈环**（reconcile 不写 class/不写 wrap.style；`__webTabShot` 写 `.web-host` 不在 wrap-MO 观察面（无 subtree）；`web-loading` 由后端推、每航次 2 次额外推演有界）→ 效果=放大 RB3 窗口碰撞率 | 静态推演 + MO 观察面核对 |

**负结果（证伪）**：
- **RB2b**：create 双发去重 TOCTOU（`_pending` 检查→add 窗口 ~ns）——4000 轮 × 2 Barrier 对齐线程 + `switchinterval=1e-6` **未复现** → 理论存在、不可利用（且真实连点间隔 ~50-200ms，`_pending` 生存期覆盖）。
- **JS 推演核心**：10,000 序列 × 12 操作，按「winner=max-sq 命令 == 推演预期选择」精确语义断言**全绿**——推演逻辑成立；其「后端按 sq 丢弃迟到旧令」的前提恰被 RB3/RB4 破坏（丢弃与回退都发生在后端）。

**专项疑问裁决**（任务书 ①②③④）：
- **① flush TOCTOU**：证伪「崩溃/再 Dispose 炸」——`_close_all` 对快照内已 Dispose 控件再 `Controls.Remove+Dispose` 幂等（WinForms 语义 + 桩双 Dispose 计数无异常）；dispose 的 `_rm` 排在 `_close_all` 后同理。实害改判 RB1（5s 停摆）与 RB6（zombie）。另注：`_form.BeginInvoke` 失败时降级**在调用线程直执行 `_close_all`**（非 UI 线程跨线程控件访问，外层 try 兜底）——信息级。
- **② `_epochs` 复合操作竞态**：dict 单操作原子未被打破；「检查+添加」不原子窗口归入 RB2/RB7 孤儿机制（dispose_all 快照 `_pending` 时 epoch 未写入 → 漏判）。无独立缺陷。
- **③ sq 门竞态**：见 RB3。
- **④ 前端 `_webCtlSeq` vs 后端 `_want_seq`**：**成立**，D1 的「beacon reset」是 lossy 的三重路径（RB4 a/b/c）——根因：`sq` 无 epoch 命名空间 + reset 依赖 sendBeacon 必达 + W40 零命中跳过 reset 的组合。

**TrySuspendAsync/Dispose 竞态**（任务书点名）：`_apply_visibility` 的 `TrySuspendAsync` fire-and-forget 与随后 dispose 的 Dispose 并发——同步异常被 `_suspend_ctl`/`_resume_ctl` try 吞；task fault 未观察（.NET 4.5+ 不致死）——**信息级，不立缺陷**。dispose 后迟到 WebMessage/事件回调：六个处理器均有 try（a555 W13/W14 防线），模糊 **逃逸异常 0**/96,000 操作——防线有效。

---

## 二、发现明细

### RB2（P1）dispose_all 清掉自己的取消标记 → 已取消 create 复活为隐形孤儿

`web_tabs.py:898-918`：dispose_all 在 `_pending` 清理循环里 `self._cancel.add(tid)`，随后 `if n or epoch is None: self.reset_session()` → `reset_session` 里 **`self._cancel.clear()`**（`:972`）把刚加的标记一并清空。若 `_build`（UI 闭包）在此之后才上 UI 线程执行（刷新风暴期 BeginInvoke 积压，窗口毫秒~秒级），`if tab_id in self._cancel` 判空 → 照常建控件 + 父挂 + `self._ctl[tab_id]=ctl` + `_wire` 完整导航链。此时 `_epochs` 已被 pop → 后续任何 `dispose_all("E2")` 按纪元匹配 `self._epochs.get(tid)==epoch` 恒 None ≠ "E2" → **永不回收**：隐藏 WebView2 控件携带完整浏览会话（内存 + 渲染进程 + 可能的网络活动）存活到 panic 或退出。

探针：backlog UI 模式按 create→dispose_all→drain 顺序 300 轮，**300/300** 复活；`assert not wt._cancel` 证明标记确被自清。修法方向（未实施）：`reset_session` 不清 `_cancel`（改由 `_build` 消费时 discard，现状单 dispose 路径即如此）；或 cancel 标记带 epoch、reset 只清非本纪元。

### RB4（P1）刷新后 sq 水位失配——D1 的 beacon reset 是 lossy 的（④）

前端 `_webCtlSeq` 每页从 0 起；后端 `_want_seq` 是**全局**水位，重置只有一条路：pagehide beacon `dispose_all(epoch)` → 且仅当 `recycled>0` 才 `reset_session()`（W40）。三变体：

| 变体 | 场景 | 结果（探针） |
|---|---|---|
| a | 逐个关掉 web tab 后刷新（常见操作） | `dispose_all(E1)` recycle=**0** → 不 reset → 新页 sq=1..30 **全部被 `sq <= _want_seq` 丢弃**，死 UI 直到新页累计发出 >30 条可见性命令（2s 周期推演 1-2 条/拍 ≈ **20-74s**） |
| b | beacon 丢失（快速刷新/进程终止时 sendBeacon 未达） | 水位 50 原样存活，**无任何 reset 路径**，10/10 丢弃 |
| c | beacon 已 reset，但旧页迟到的 `show(sq=37)` 后到 | **show 无 epoch 标签**（REST 只透传 sq）→ 37>0 接受 → 水位 0→37 → 新页 10/10 再次全丢 |

模糊佐证：双页面（双纪元）重叠期间，每纪元独立计数器写同一全局水位 → 跨纪元互踩 **×1039**/400 轮。缓解只在「beacon 必达 + 晚于新页首条 show 到达 + 本纪元确有存活控件」三条件同时成立时有效。修法方向：`sq` 携带 epoch（或 create 到新 epoch 时重置水位）；reset 后忽略旧纪元 sq。

### RB1（P2）flush 退出竞态——grace 窗口内 Flask 仍服务（①）

`_do_real_cleanup` 先 `_wt.shutdown()`（内含 `flush_on_exit` 的 `sleep(grace_ms=1200)`）**后** `close_all_ports()`（main.py:1250→1252）→ 整个 grace 期 `/api/web/tabs` 可达。探针 120 轮风暴（create/dispose/show/layout/suspend 混发）**零异常**——`_ctl.get` 走 no-tab、快照内已 Dispose 控件再 Dispose 幂等（任务书 ① 的「崩溃」假设证伪）。实害：
- `_env=None` 而 `_env_failed` 仍 False → create 不走快速失败，烧满 50×100ms → **每调用 5s Flask 线程停摆**（RB1b 缩放实测），N 并发 create = N 线程钉死 5s；
- 结合 RB6 产生 zombie。修法方向：flush 开头置 `self._env_failed = True`（复用 a555 快速失败），并 `_want/_layout_seen` 一并作废。

### RB5（P2）suspend 完成回调陈旧隐藏——100-300ms 窗口内 show 被回滚

suspend 链：UI 线程 `_do` 起抓帧 → 池线程 `_done` 读帧 → 再 BeginInvoke `_after`：**无条件** `ctl.Visible = False`（`web_tabs.py:717-720`），不回查 `_want`/`_layout_seen`。若抓帧期间用户切回该 tab（show 已应用，`Visible=True`），`_after` 落地瞬间把它藏掉——正被观看的 tab 闪黑/冻结，靠 R9.6 第二拍（200ms）或 2s 周期推演自愈。探针 100/100；模糊 I6（意图可见但静默态被藏）自然命中 ×14/400 轮。修法方向：`_after` 回查 `self._want == (tab_id, True)` 则不隐藏、帧照推。

### RB6（P2）flush 边界 zombie——create 过 env 检查、_build 撞上 env=None

create（Flask 线程）在 `if not self._env` 处读到环境仍在 → 排队 `_build`；flush（另一线程）随后 `_ctl.clear()` + `_env=None`；UI 线程之后执行 `_build`：照建控件、父挂、`_wire` → `EnsureCoreWebView2Async(None)` 同步抛 → `_wire` 的 try 只记日志 → 控件滞留 `_ctl` + form.Controls，初始化链死，前端早已拿到 `ok:True`。窗口=create→`_build` 的 UI 延迟（刷新风暴期秒级）。探针 50/50。修法方向：`_wire` 判 `self._env is None` 直接走 `_rm` 回收路径（与 R3 W13 失败回收同款）。

### RB3（P3）show sq 门读-比-写非原子（③）

`web_tabs.py:854-857`：`if sq <= self._want_seq: return` 与 `self._want_seq = sq` 之间无原子性。强制抢占探针（`_SeqDelay` 子类把 gate 读取停车 50ms，逻辑字节码不变）：T(sq=5) 停车后 T(sq=6) 完整通过，5 醒来仍过门写 5 → **50/50** 水位 6→5 回退 + 最终 `_want` 是陈旧 sq=5 的意图；此后 `sq<=5` 的重复旧令重新获准入内。真实 GIL（`switchinterval=1e-6`）20,000 轮 × 4 线程 0 命中——窗口约百 ns 且需双请求 µs 级同到 → 现实概率极低，但 RB-JS2 的 fetch 风暴会抬高碰撞率。修法方向：门与写入合并为 `if sq > self._want_seq: self._want_seq = sq; ...`（先写后判 `_want`），或对 show 加实例锁。

### RB-JS1（P3）推演 `_a` 空值旁路

`web-panel.js:457` `const _a = connections[activePortId]`——当 activePortId 悬空（指向已删 conn）时 `_a=null` → `want = onScreen && (!_a || actWeb===c) && ...` 的 `!_a` 短路掉激活守卫 → 字典序第一个 onScreen 的 web wrap 被选为目标并**显示**（node 模糊 ×824 建模命中）。现状唯一写 null 处（editor.js:1534）语义是「全部 tab 已关」→ 无 wrap 可 flex → 不可达；但抽屉/悬浮等第三方路径若将来在 activePortId 悬空时残留 flex wrap，该旁路即 hwnd 外泄复发点（且 2s 周期推演会**持续维持**泄漏态）。属 R9.3 注释明示的 deliberate fallback——记录为纵深缺口。

### RB-JS2（P3）推演无节流上限 + 反馈环核查

触发面：body-MO（subtree+class）每 tick 合并一次、wrap-MO（自身 style）每 tick 一次、pointerdown/click/contextmenu 捕获、2s 周期、switchTab/阅读/休眠/唤醒显式调用。无自反馈环：reconcile 只发 fetch 与 30ms `_ctlPush`（getBoundingClientRect+fetch，零 DOM 写）；`__webTabShot` 写 `.web-host`（wrap 的**子**元素，wrap-MO 无 subtree 观察不到）；`web-loading` class 由后端 `__webTabLoad` 推（每航次 NavigationStarting/Completed 各一次 → 2 次额外推演，有界）。但 R9.14「目标每次恒发 show」使每次推演 ≥1 fetch：class 高频 churn 页面（轮播/动画）下 ~60-120 fetch/s → Flask 线程风暴 → 提高 RB3 百 ns 窗口的碰撞概率、并放大 RB4 的丢弃面（sq 快速推进）。无绝对上限，建议对恒发加最小间隔（如 500ms）。

### 线程模型逐字段核验（无独立缺陷项）

- `_rect`/`_want` 为元组整体赋值（单 STORE_ATTR）GIL 原子；`_layout_seen`/`_env_failed` 布尔原子；`_want_seq` int 原子但复合门不原子（RB3）。
- `_apply_visibility`/`layout._apply` 均 `list()` 快照迭代（a555 修复在位），模糊 96,000 操作 **RuntimeError 0**。
- dispose 后迟到事件（`go_back` 的 `CanGoBack`、`_on_hist`、`_on_src` 等）全部 try 保护，探针逃逸异常 0。
- `_pw_del_defer`/`_pw_entries` 并发 sqlite：共享读复制 + timeout=0.3 + 全 try——非本域主攻面，未立缺陷（`_pwdb_copy` 每次 mkdtemp 不清理属资源泄漏，非并发，已口头记录）。

---

## 三、探针清单与复现

目录 `%TEMP%\rtb_conc_probe\`（仓库零写入）：

| 文件 | 内容 | 结果 |
|---|---|---|
| `harness.py` | CLR 桩（System/WinForms/WebView2）+ FakeForm 三形态（sync/backlog/uitread 泵线程）+ FakeTask（延迟 ContinueWith）+ 不变式检查 | — |
| `probe_deterministic.py` | RB1(120轮)/RB1b/RB2(300)/RB2b(4000)/RB3(20000+50强制)/RB4/RB4c/RB5(100)/RB6(50) | 6 HIT + 2 ok（RB1 崩溃面证伪、RB2b 证伪） |
| `probe_fuzz.py` | 6 Flask 线程 × 40 op × 400 轮 = 96,000 下发；不变式 I1/I2/I3(分纪元)/I5/I6 | 孤儿 ×82 轮、跨纪元互踩 ×1039、陈旧隐藏 ×14、逃逸异常 0 |
| `fuzz_reconcile.js` | 真实函数体提取，10,000 序列 × 12 op | 精确语义下**零违例**（粗语义 V1-V4 为建模伪影，已裁决） |
| `debug_seq.js` | 失败序列逐步回放（op 轨迹） | 判定 V2/V3/V4 为伪影 |

复现：`cd %TEMP%\rtb_conc_probe && python -I probe_deterministic.py && python -I probe_fuzz.py 400 && node fuzz_reconcile.js`

机械复核：`USERPROFILE=$(mktemp -d) python -m pytest tests/ -q` → **274 passed, 1 skipped, 10 subtests**（全绿，本审计未改任何仓库文件）。

## 四、修复优先级建议（只建议不实施）

1. **RB2**：`reset_session` 不清 `_cancel`（或 cancel 带 epoch）——一行级改动，消灭 P1 孤儿复活。
2. **RB4**：`sq` 加 epoch 命名空间（create 新 epoch 时重置水位 + show 校验 epoch），beacon 丢失才有兜底。
3. **RB1**：flush 开头 `_env_failed=True`（复用 a555）→ grace 期 create 快速失败不占线程。
4. **RB5**：suspend `_after` 回查 `_want` 再隐藏。
5. **RB6**：`_wire` 遇 `_env is None` 走 `_rm` 回收。
6. RB3/RB-JS1/RB-JS2：低成本加固（show 先写后判 / `_a` 判 `activePortId` 存在性而非 conn 真值 / 恒发加最小间隔）。
