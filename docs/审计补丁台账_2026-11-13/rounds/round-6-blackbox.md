# 第 6 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能（终判轮）

- 轮次：round 6（W31 基线定格 + 五轮回归终扫 + 终判）
- 日期：2026-11-13
- 测试对象：v4.1.0-a556 基线 d9c8886（patch-round-1 至 5 均为提案未应用；已读 patch-round-5.md，P1' = switchTab 包装器补阅读/休眠守卫一行）
- 方法：IAB 合成事件驱动 + 只读 fetch 记录器（格内自足）+ curl/python 直打 + 靶标（18999 / 19001 / 19002 自签）
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068）未杀未干扰，仅 GET 探测；结束时测试端口全清（已核验）

---

## 终判结论：零确凿·黑盒终判成立

R1–R5 黑盒确凿台账（B1–B19）全部保持登记且基线无漂移；本轮 W31 基线成功定格（P1' 验收依据）；兜底抽查零新发现。黑盒通道收敛（连续 R5/R6 两轮零新确凿）。

---

## 一、W31 基线定格（P1' 验收依据，请求级）

### 1.1 阅读态生命周期全序列（双 tab：A=web:1/plain、B=web:2/special）

| 步骤 | 操作 | 请求序列（记录器原文） |
|---|---|---|
| 开阅读（A 激活态点击） | read | `show(on:false, sq37, tab:"web-1")` ×2 + `nav(about:blank, web-1)` ×2 —— 正确隐藏控件 + webview 置空 |
| 切到 B | pill click | `show(on:true, sq38, tab:"web-2")` ×2 + `show(on:true, sq39, tab:"web-2")` ×2 + `layout(223,140,717,580, web-2)` ×6 —— 正常切换基线（每次切换 **2 对 show(true)**：包装器 + MutationObserver sync 双通道） |
| **切回 A（阅读态）＝ W31 关键** | pill click | **`show(on:true, sq40, tab:"web-1")` ×2** ← **W31 坐实：阅读态切回仍显原生控件**（P1' 应用后此对消失）+ **`layout(0,0,0,0, web-1)` ×4**（阅读态宿主隐藏、RO/push 读出全零 rect——P1' 不改此行为，桌面端对已隐藏控件 layout 0×0，记录备查） |
| 退出阅读 | read | `show(on:true, sq41)×2` + `nav(plain.html)×2` + `show(on:true, sq42)×2` + layout×4 —— 恢复路径齐全（与 P1' 无死端核验吻合：退出阅读经 `_webReaderToggle` 内部恢复显出） |

### 1.2 reader×sleep 组合边界（sleeping 态经状态注入使可达，已声明）

切回 sleeping 标记 tab 的序列：`show(on:true, sq28)×2` + `nav(栈顶 plain.html)×2`（唤醒路径：`_webWake` + `_webNavigate` 内部 show/nav）+ `show(on:true, sq29)×2`（包装器无条件调用）+ layout×4。

- **边界定格**：休眠切回 = **2 对 show(true)**（唤醒路径 1 对 + 包装器 1 对）。P1' 应用后：包装器对被守卫移除 → 剩唤醒路径 1 对（无死端，显出语义保持）。
- 复测注记：本轮首次尝试因历史轮注入的 sleeping 残留标记使 read 点击被唤醒路径吞掉（未成阅读态）——归一化标记后干净捕获；这也是 P1' 注释「唤醒路径经 _webNavigate 内部 show 照常显出」的行为级佐证。

### 1.3 附带复证（同批捕获）

- **B10 变体现场**：在非激活面板上点击 read 按钮 → 阅读模式开在**激活 tab** 上（`show(on:false, tab:"web-2")` 出现在操作 web:1 按钮时）——A8'/B10 基线再证。
- show(true) 双通道：每次 `_webCtlVisible(true)` 实际发出 **2 个相同请求**（a556 注释「show:true/false 是两个独立 fetch」的行为级证实）——N3/P1' 验收计数时按「对」折算。

## 二、回归终扫（跨五轮抽查 6 项 + 快照抽 3 格——全部无漂移）

| 来源 | 项 | 结果 |
|---|---|---|
| R1 | API 怪 id 优雅（负数 id 200 优雅 / 顶层数组 400 JSON / 坏 JSON 200 优雅） | ✅ 逐字一致 |
| R1 | 收藏功能主链（存取/菜单/去重） | ✅（B18 格内渲染 2 项正常） |
| R2 | B16 请求序列（侧栏 ✕：disconnect 噪音 + dispose 缺失） | ✅ 复现（本轮变体：disconnect 噪音 ×2——双通道同款，计数按对折算，W22 主证不变） |
| R2 | B11 族 30 跳重定向环 | ✅ 0.1s 优雅失败 |
| R3 | 缩放跨站隔离（web-zoom:host:port 键 1.3 正确应用） | ✅ |
| R3 | B18 缺 url tooltip 泄露 `"undefined"` | ✅ 复现 |
| R4 | B7 矩阵（本轮经 B10 变体现场间接复证：read@非激活 → 落激活 tab） | ✅ |
| R5 | 幽灵累积语义（B16 序列捕获中无幽灵发出——关闭时未 resize，语义一致） | ✅ |

## 三、已测未复现清单（R6 补充）

| # | 项 | 结果 |
|---|---|---|
| 1 | 阅读态切回**不**发 show(true)（= W31 修复后行为） | ⛔ 基线发出（本轮定格目标即此） |
| 2 | reader×sleep 边界异常/挂死 | ✅ 未复现（序列干净、恢复路径齐全） |
| 3 | 五轮回归项漂移 | ✅ 未复现 |

## 四、终判说明

- 六轮黑盒累计确凿台账：B1–B19（19 条，编号含 B10–B19 台账沿用），其中 P1×2（B16/W22、B1 族）、P2×6、P3×11；全部已转化为 patch-round-1 至 5 的验收基线（N3/N5/N1'/A8'/P1'）。
- 本轮零新确凿；R5+R6 连续两轮黑盒零新确凿 → **黑盒终判成立**。
- 剩余桌面验证项（黑盒不可达，移交桌面手册）：幽灵 layout 50×50 后果、休眠/唤醒真机、target=_blank、`javascript:` Navigate、dispose_all 真实回收、a551 叠放——详见 patch-round-4/5 与 round-3/4-whitebox §五。

## 五、复用与工具经验（终版）

- 隔离实例：`cd C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2 && USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server`（端口 18765）
- 靶标：`python $TMP/audit-bb-r2/echo_v3.py`（19001/19002）+ 18999 静态页
- 工具经验三条：① IAB 格间自动重载——多步取证单格自足 + 记录器格内重装守卫；② IAB `setViewportSize` 不派发 window resize 事件——resize 类取证用合成事件触发同一监听；③ IAB 长会话多页绑定劣化——轮首清理残留 IAB tab。
