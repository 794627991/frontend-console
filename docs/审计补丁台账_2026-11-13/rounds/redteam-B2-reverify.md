# Redteam B · 复验轮：攻破 RB1–RB6/RB-JS 修复本身（a584）

- **生成**：2026-11-16
- **对象**：HEAD `e564f24`（v4.1.0-a584），修复 diff = `git diff 480c07d..HEAD -- src/web_tabs.py web/js/web-panel.js`；上轮报告 `rounds/redteam-B-concurrency.md`
- **攻击者**：并发红队 B（复验轮）——任务是攻破修复，不是重复原发现
- **性质**：对抗审计——只报告不修复；唯一写入本报告；git 仅 diff/log/show/grep/status；探针全部位于 `%TEMP%\rtb_reverify\`（未进仓库）
- **方法**：上轮同款三件套对修复版重跑 + 定向新时序——①真实多线程 Python 探针（importlib 原样加载 `src/web_tabs.py`，仅桩 CLR 面；UI 线程三形态 + ContinueWith 池线程 + `_epochs.get`/`_want_seq` 属性钩子做强制交错，逻辑字节码零改动）；②node 模糊执行器（原样提取 `_webReconcileVis`/`_webCtlVisible` 函数体，适配新增 `epoch` 字段）；③机械复核 `USERPROFILE=$(mktemp -d) python -m pytest tests/ -q`

---

## 一、总体结论

**六个 P1/P2 修复主体全部站住**：RB2 复活 300/300→**0/300**、RB4 死 UI 10/10→**0/10**（两变体）、RB5 陈旧隐藏 100/100→**0/100**、RB1 停摆 ~5s→**0.0000s**、RB6 退出期 create 快速失败确认。模糊 96,000 次下发对比：孤儿 ×82轮→×4（仅剩 RB2b 类）、真陈旧隐藏 ×14→**0**、逃逸异常 0→0。

但复验挖出 **5 条新发现（RB7 起）**：最重的是 **RB7-1**——RB2 的修法（`_cancel` 由 `_build` 消费自清）没有封住 `dispose_all` pending 循环自身的非原子性：`_build` 在「快照已含 tid → `_cancel.add`」窗口内完成时，控件照建、纪元被 pop、取消标记永久滞留 → **同纪元 beacon 永不回收的孤儿**（强制交错 100/100；野生模糊 I9 ×3/96,000 自然命中）。其次是 **RB7-2**——RB4 的 epoch 重置无归属鉴别：旧纪元迟到 show 会**翻转 `_want_epoch` + 水位归零 + 陈旧意图被应用**（≤2s 自愈窗）；双活 UI 窗口场景下 sq 门 2000/2000 全翻转失效。

| 编号 | 级 | 摘要 | 探针证据 |
|---|---|---|---|
| **RB7-1** | **P2** | `dispose_all` pending 循环非原子 vs `_build` 消费：快照→`_cancel.add` 之间 `_build` 完成 = 控件建成 + `_epochs.pop` + cancel 标记滞留 → 纪元 beacon 永不回收（RB2 同实体孤儿，窗口收窄至 µs 级但野生仍命中） | 强制 **100/100**（含「同纪元 beacon 二次回收=0」断言）；野生 I9 **×3/96,000** |
| **RB7-2** | P3 | show 的 epoch 重置无归属鉴别：任意新 epoch（含**旧纪元迟到的**）都抢占 `_want_epoch` + 水位归零，且**该条陈旧命令自身过门被应用**（错 tab 显示/全隐 ≤2s）；双活 UI 窗口 = 门永久失效 | 翻转+陈旧意图应用 **确定性复现**；双窗交替 2000/2000 翻转、通过率 100% |
| RB8 | 低 | `flush_on_exit` 无重入门 + `shutdown()` 不清 `_tabs` + `main.py _do_real_cleanup` 3 个未守卫调用点（on_closing:1354/:1369、托盘兜底:1435）→ 双路径退出每次多睡一个 grace | 3 次退出调用累计 sleep 600ms（grace=200×3）；`_pw_del_flush` 幂等无害 |
| RB9 | 移交A | `_pw_guard` 的「本机其他进程 403」宣称不成立：Origin 头可伪造（`Origin==http://Host` 探针 **200 PASS**）；DNS rebinding 下 Host/Origin 双双攻击者可控（**200 PASS**，pw_reveal/pw_del 全通过）——仅浏览器 CSRF 面被关闭（403 ✓） | Flask test_client 实测矩阵 6 行 |
| RB10 | 低·移交A | `_pw_del_del_lock` 只锁 defer；`_pw_del_flush`（退出路径）无锁「读旧表→sqlite→os.remove」→ 关停 1.2s 窗口内 pw_del 端点仍活（RB1 窗口），其挂起项被 flush 的 remove 抹掉 = **一条密码删除永久丢失**（无重试路径） | 确定性复现：defer 返回 False「已挂起，退出后生效」+ 文件被删 + 库中行仍在 |

**逐条复验裁决**：

| 原编号 | 裁决 | 要点 |
|---|---|---|
| RB1（P2） | **修复确认** | grace 风暴 120 轮 0 异常 0 ok:True；rb1b create 后置 0.0000s 快速失败「正在退出」（原 ~5s） |
| RB2（P1） | **修复确认 + 修复引入新洞 RB7-1** | 0/300 复活（原 300/300）；`reset_session` 不再碰 `_cancel`（0/300 回归）；消费自清 0/200 残留；`_cancel` 泄漏有界（UI 死时 ≤在途数 200/200，排水后 0；前端 id 含 `web-<epoch>-<n>` 无碰撞）；但 pending 循环竞态 = RB7-1 |
| RB3（P3） | **未修（上轮已接受）**，不变 | 自然 0/20000（switchinterval=1e-6）、强制 50/50，与上轮持平 |
| RB4（P1） | **修复确认 + 修复引入新洞 RB7-2** | 变体 a（recycle=0）：10/10→**0/10** 丢弃；变体 b（beacon 丢失）：10/10→**0/10**；自愈时长：epoch 恒发下水位重置后**首条 show 即通过**（2s 推演拍兜底、用户操作 0s）；无 epoch 的兼容调用方仍受旧水位支配（by design，前端唯一 show 发送点已恒带 epoch，静态资源 no-cache 无旧 JS 风险） |
| RB5（P2） | **修复确认** | 0/100 陈旧隐藏（原 100/100）；边缘三项全良性：`_want=None` 首建隐藏后首条 show 即恢复（前端只在「已显→藏」才发 suspend，不可达）；dispose 中途迟到 `_after` 0 逃逸异常、状态干净（Visible-on-disposed 被 try 吞、`__webTabShot` 前端忽略未知 tid）；GIL 读 `_want` 20,000 写 ×3 读 0 撕裂 |
| RB6（P2） | **部分修复**（残留见下） | 修复面：closing 期 create 20 次 0.000s 快速失败 ✓；closing 期 show/nav/back/fwd/reload/suspend/layout **0/3000** 异常（`_ctl.get`→None 全部安全）✓。残留：①create 已过闸、`_build` 跨越边界的 zombie **仍 50/50**（`_build`/`_wire` 不复查 `_env`，EnsureCoreWebView2Async(None) 同步异常仅记日志、无 `_rm` 回收；`_epochs` 已被 flush 清空 → beacon 不可回收）——实害降级：进程退出在即、taskkill 树杀兜底；②`_closing=True` 与 `_env=None` 两语句间微窗 ~ns（强制 200/200，信息级） |
| RB-JS1（P3） | 未修，纵深缺口原样 | `!_a` 单真值回落仍在（web-panel.js:464）；现状不可达结论不变 |
| RB-JS2（P3） | 未修，原样 | R9.14 恒发无最小间隔；修复版 JS 模糊 10,000 序列 × 12 op **零违例**（提取器已适配 epoch 字段） |

---

## 二、新发现明细

### RB7-1（P2）dispose_all pending 循环非原子——RB2 修复的残余复活窗

`web_tabs.py:964-970`：pending 循环是「`list(self._pending)` 快照 → 过滤 `self._epochs.get(t)==epoch` → `_cancel.add` → `_pending.discard` → `_pend_nav.pop` → `_epochs.pop`」五步复合操作，与 UI 线程正在执行的 `_build` 无任何互斥。**致命交错**：快照已含 tid，过滤调用 `_epochs.get` 期间 `_build` 在 UI 线程完整跑完（cancel 判空 → 建控件 + 父挂 + 入 `_ctl`），随后循环照常 `_cancel.add`（标记永久滞留——`_build` 已经过了检查点，无人消费）+ `_epochs.pop` → 控件在 `_ctl` 存活但**纪元已失**：后续任何 `dispose_all("E*")` 循环一按 `self._epochs.get(tid)==epoch` 恒 None 不匹配 → **永不回收**，与原 RB2 同实体（仅 panic `dispose_all(None)`/退出可清）。探针：`_epochs.get` 钩子窗内排水 UI 队列 **100/100** 建出「已取消」控件，100 个滞留 cancel 标记，100/100 同纪元 beacon 二次回收=0；野生模糊（未注入任何钩子）I9「在 `_ctl` 存活且无纪元」**×3/96,000** 自然命中（round 219 等）。窗口=快照→add（µs 级，原 RB2 是整条 reset_session 路径）；真实触发面=刷新风暴期 UI 积压，`dispose_all`（Flask 线程）与 `_build`（UI 线程）并发。修法方向：`_build` 消费 cancel 前改查 `self._epochs.get(tab_id) != my_epoch`（顺带封 RB2 残余），或 pending 循环整体与 `_build` 同锁。

### RB7-2（P3）epoch 重置无归属鉴别——旧纪元迟到命令翻转并应用陈旧意图

`web_tabs.py:905-907`：`if epoch is not None and epoch != _want_epoch: _want_epoch=epoch; _want_seq=0`——对 epoch 来源零鉴别。**Coordinator 提问的「旧页迟到 show(旧 epoch)」确为新洞**：时序 `_want_epoch=E2, sq=5` → 迟到 `show(old, sq=37, epoch=E1)` → `_want_epoch` 翻成 E1、水位 37、**`_want=(old,True)` 陈旧意图被应用并排队 `_apply`**（错 tab 压顶/全隐，hwnd 盖 UI 形态）→ 新页下一条 show（≤2s 推演拍）翻回 E2 自愈。较修复前（水位 37 永久压死 = 20-74s 死 UI）大幅改善，但「≤2s 错显示」是新增的可复现形态。放大场景：**双活 UI 窗口**（复制窗口/浏览器同开第二份 UI，各自 `_webPageEpoch`）：每条命令都翻转 → 水位每次归零 → a556 乱序门**通过率 100%**（探针 2000/2000 翻转）→ 两窗排他意图按到达序互相 flap，恰是 a556 修的原 bug 在双窗下复活。修法方向：epoch 归属鉴别（`create` 登记的 `_epochs` 值集合成员校验 / 单一「当前纪元」只升不降）。

### RB8（低）退出链无重入守卫——双路径退出多睡一个 grace

`flush_on_exit` 无 `_closing` 早退门（置位后不拒绝重入）；`shutdown()` 的 `if _tabs is None: return` 后**不清 `_tabs`** → 二次调用完整重跑；`main.py` `_do_real_cleanup` 有 3 个未守卫调用点（`on_closing` 1354/直退 1369、托盘 destroy 失败兜底 1435）——兜底路径与 closing 竞态时每个额外调用多睡 `grace_ms`（探针：3 次调用累计 600ms/ grace=200）。`_pw_del_flush` 幂等（首调即删文件）无实害。修法方向：`flush_on_exit` 开头 `if self._closing: return`，或 `shutdown()` 置 `_tabs=None`。

### RB9（移交 A 组定级）_pw_guard 对其宣称的本机进程威胁无效 + rebinding 旁路

`web_tabs.py:1119-1127` 守卫注释宣称「本机其他进程……全部 403」——实际判定是 `Origin == "http://" + Host` 的**回显比较**，两者对任何非浏览器客户端都是可伪造字段：本地进程 `Origin: http://127.0.0.1:<port>` 即 **200 PASS**（真实 `register()` + Flask test_client 实测）；DNS rebinding 下 `Host: evil.example:8765` + `Origin: http://evil.example:8765` 同构 **200 PASS**（pw_reveal 全库明文 / pw_del 盲删均可达；Chrome PNA 可缓解新式浏览器，非普遍防线）。守卫真实关闭的是浏览器 CSRF 面（错配 Origin → 403 ✓ 实测）。修复宣称与实测不符，建议 A 组复核 RA1 威胁模型（本机进程可直连 sqlite+DPAPI 的话此门价值本就有限，宜改注释降期望或加共享密钥）。

### RB10（低，移交 A 组）_pw_del_flush 无锁读+删 vs defer 持锁 RMW——关停窗口丢一条删除

RA5 把读-改-写锁进 `_pw_del_lock`，但 `_pw_del_flush`（`web_tabs.py:217-245`）**不走锁**：`json.load 旧表 → sqlite DELETE → os.remove`。RB1 的 1.2s grace 窗口内 `pw_del` 端点仍活（库仍被 Chromium 锁 → defer 走挂起文件路径），与已开跑的 flush 交错：flush 读旧表 → defer 追加写回 → flush 的 `os.remove` 把新项抹掉 → **defer 已回执「已挂起，退出后生效」的删除永久丢失**（库中行仍在、无重试路径）。确定性复现（defer 的 sqlite 失败阶段用坏路径等价替换「库被锁」，flush 侧 0.45s 延迟模拟 sqlite 时延）：defer=False + 文件已删 + 行仍在。修法方向：flush 同样持 `_pw_del_lock`（其持锁段仅文件 IO+sqlite，无嵌套锁、无死锁面； defer 持锁段亦仅文件 RMW——两锁面核查无嵌套）。

---

## 三、探针清单与数字

目录 `%TEMP%\rtb_reverify\`（上轮 `%TEMP%\rtb_conc_probe\` 原样保留未动；仓库零写入）：

| 文件 | 内容 | 结果 |
|---|---|---|
| `harness.py` | 上轮 CLR 桩原样复用 | — |
| `probe_reverify.py` | RB1b/RB2×2/RB4×3/RB5×4/RB6×4/RB3 定向复验 + RB7-1 首版钩子（未命中，作废） | 见下表 |
| `probe_rb7_1.py` | RB7-1 `_epochs.get` 钩子强制交错（快照→cancel.add 窗）+ 同纪元 beacon 二次回收断言 | **100/100** 建成+滞留+不可回收 |
| `probe_fuzz2.py` | 修复版模糊：6 线程 × 40 op × 400 轮 = **96,000 下发**；show 恒带 epoch（对齐真实前端）；不变式 I1/I2/I3(真同纪元回归)/I5/I6(含 layout 自愈判定)/I7(翻转)/I9(无纪元活控件) | 真 RB3 回归 **0**；I6 ×2（均 layout 即愈=设计窗口，真陈旧隐藏 **0**）；I5 ×4（RB2b 类）；I9 ×3（RB7-1 野生）；epoch 翻转 8041（8.4%）；`_cancel` 峰值 2；逃逸异常 **0** |
| `probe_pw_guard.py` | 真实 `register()` + Flask test_client 守卫矩阵 | 无 Origin 403 / 同源 200 / **伪造 Origin 200** / **rebinding 200** / CSRF 403 / pw_del rebinding 200 |
| `probe_pw_flush_race.py` | RA5 flush 无锁竞态（确定性时序） | **丢一条删除**：defer=False「已挂起」+ 文件被 flush remove + 库中行仍在 |
| `fuzz_reconcile2.js` | 上轮提取器适配 epoch 字段，对修复版 `web-panel.js` | 10,000 序列 × 12 op **零违例** |

关键对照（修复前 → 修复后）：

| 指标 | 上轮（480c07d） | 本轮（e564f24） |
|---|---|---|
| RB2 复活 | 300/300 | **0/300** |
| RB4 变体 a/b 丢弃 | 10/10 + 10/10 | **0/10 + 0/10** |
| RB5 陈旧隐藏 | 100/100 | **0/100** |
| RB1b create 停摆 | ~5s/次 | **0.0000s** |
| RB6 跨越 zombie | 50/50 | **50/50**（残留，实害降级） |
| 模糊孤儿 | ×82 轮 | ×4（RB2b 类）+ I9 ×3（RB7-1 类） |
| 模糊真陈旧隐藏 | ×14 | **0**（×2 为 layout 即愈的设计窗口） |
| 逃逸异常 | 0 | 0 |
| RB3 同纪元水位回退 | 0/20000 自然 + 50/50 强制 | 0/20000 + 50/50（不变） |

机械复核：`USERPROFILE=$(mktemp -d) python -m pytest tests/ -q` → **286 passed, 1 skipped, 10 subtests passed (19.31s)** ✅（上轮 274——修复提交新增 12 个测试全绿）；`node --check web/js/web-panel.js` ✅；本审计未改任何仓库文件（本报告除外）。

复现：`cd %TEMP%\rtb_reverify && python -I probe_reverify.py && python -I probe_rb7_1.py && python -I probe_fuzz2.py 400 && python -I probe_pw_guard.py && python -I probe_pw_flush_race.py && node fuzz_reconcile2.js`

## 四、修复优先级建议（只建议不实施）

1. **RB7-1**：`_build` 弃建判据从「`tab_id in _cancel`」改为「`self._epochs.get(tab_id) != 创建时 epoch`」（顺带消灭滞留标记），或 dispose_all pending 循环与 `_build` 互斥。
2. **RB7-2**：epoch 只升不降（create 登记的纪元集合成员校验；陌生 epoch 拒收或仅当页无存活控件时接纳）。
3. **RB10/RB8**：flush 持 `_pw_del_lock`；`flush_on_exit` 加 `_closing` 早退门。
4. **RB9**：改守卫注释如实声明只防浏览器 CSRF；如需真防本机进程，须共享密钥或命名管道。
