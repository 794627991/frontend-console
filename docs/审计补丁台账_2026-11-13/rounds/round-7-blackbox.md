# 第 7 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能（确认轮）

- 轮次：round 7（W32 请求级基线定格 + 不变式抽查 + 回归快扫 4 项）
- 日期：2026-11-13
- 测试对象：v4.1.0-a556 基线 d9c8886（patch-round-1 至 6 均为提案未应用；已读 patch-round-6.md——W32 为 P1' 补丁引入的回归、修订版 P1'' 提出全隐语义 `all:true`，均未进代码，本轮实测即基线行为）
- 方法：IAB 合成事件驱动 + 只读 fetch 记录器（格内自足）+ curl/python 直打
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068）未杀未干扰，仅 GET 探测；结束时测试端口全清（已核验）

---

## 终判结论：零新确凿——黑盒终判维持

W32 请求级基线成功定格（P1'' 验收依据）；不变式「任意时刻最多一个 show(on:true) 在途」在基线请求级成立（严格串行、sq 单调递增、无并行突发）；回归 4 项全部无漂移。R6+R7 连续确认轮零新确凿。

---

## 一、W32 请求级基线定格（P1'' 验收依据）

场景（双 tab：A=web:1/plain 开阅读态，B=web:2/special 普通态激活可见）：

| 步骤 | 操作 | 请求序列（记录器原文，单包重复已按实际记录） |
|---|---|---|
| 切到 B（普通态） | pill click | `show(on:true, sq10, tab:"web-2")` + `show(on:true, sq11, tab:"web-2")` + `layout(223,140,717,580, web-2)` ×3 —— **基线排他显示 B**（此后后端 `_want=(B,True)`） |
| **切回阅读态 A ＝ W31/W32 缺陷本体** | pill click | **`show(on:true, sq12, tab:"web-1")`**（排他显示阅读态 A——修订版 P1'' 预期应改为全隐请求 `all:true` 或等价形态）+ **`layout(0,0,0,0, web-1)` ×2**（`_ctlPush` 30ms 定时器 + ResizeObserver 各一次，宿主隐藏读出全零） |
| 触发 resize | window resize | `layout(0,0,0,0, web-1)` ×1 —— 阅读态存续期间每次 resize 都发全零 layout |

**W32 请求级观测结论**：
1. 切回阅读态 tab 后**前端不再发出任何 show 请求**（MO-sync 守卫 `:376` 正确跳过阅读态——与 R6 一致）；后续只有零矩形 layout 持续发出（每次 `_ctlPush`/resize）。
2. 「陈旧 `_want` 被 `_apply_visibility` 重放」发生在**后端内部**（每个零矩形 layout 请求到达后端时触发重放）——无头实例控件管理器未装配、`_apply_visibility` 不可达，**请求级不可观测，桌面验证手册承接**（手册对应格：桌面端此序列下 B 的控件 Visible=True+BringToFront 覆盖 A 的阅读视图）。
3. P1'' 验收断言（请求级）：切回阅读态 tab 时，`show(on:true, tab:"web-1")` 消失，取而代之出现**全隐请求**（`{"act":"show","all":true,…}` 或等价）；零矩形 layout 请求照旧（无害）。

## 二、不变式抽查（请求级）：「任意时刻最多一个 show(on:true) 在途」

场景：3 个网页 tab（web:1/2/3）快速轮切 B→A→C→A→B→C + 中途阅读进入/退出（B10 变体使阅读落在 web:1——已知变体，不影响 show 序列结构）。捕获完整有序序列（22 条，关键段）：

```
show(true, sq19, web-2)  show(true, sq20, web-2)  layout(web-2, 717x580)×3     ← 切到 web:2
show(true, sq21, web-1)  show(true, sq22, web-1)  show(true, sq23, web-1)
layout(web-1, 717x580)×4                                                             ← 切到 web:1
show(true, sq24, web-3)  show(true, sq25, web-3)  layout(web-3, 717x580)×2           ← 切到 web:3
show(true, sq26, web-1)  show(true, sq27, web-1)  layout(web-1, 717x580)×2           ← 切到 web:1
show(false, sq28, web-1)  nav(about:blank, web-1)  layout(0,0,0,0, web-1)            ← 阅读进入（B10 落 web:1）
show(true, sq29, web-2)                                                              ← 切到 web:2
```

- **全部 show(true) 的 tab 值与切换目标一一对应，无串靶**（B10 变体只影响按钮类操作，切换类 pill 点击目标正确）。
- sq 严格单调递增（19→29），无同 sq 并行突发、无交错——**基线请求级满足「最多一个 show(on:true) 在途」的不变式**（前端同步串行发出）。
- 每次切换的 show 调用次数 2–3 次（包装器 + MO-sync 双通道；R6 观察的「每 sq 成对」为记录器双重包裹伪影，本轮单包裹记录器证实**实际每调用 1 请求**——修正 R6 报告 §1.3 的计数口径：a556 注释「两个独立 fetch」与单请求实测不符，以本轮实测为准）。
- 阅读进入/退出模式对正确：进入 = `show(false)+nav(about:blank)+layout(0,0,0,0)`；退出 = `show(true)+nav(原URL)`（R6 §1.1 复现）。

## 三、回归快扫（4 项——基线无漂移）

| 项 | 结果 |
|---|---|
| B7 矩阵 wheel 格 | ✅ 显式激活态下复现：wheel@非激活 web:1 → 激活 web:2 缩放 1→1.1（web:1 不动）——首次尝试因激活态歧义不定，显式设定后干净复现 |
| B16 幽灵 | ✅ 侧栏 ✕ 关激活态 tab → dispose 缺失（`disposeSent:false`）+ resize 幽灵 `layout(0,0,0,0, web-3)` 出现 |
| B18 星标 | ✅ 缺 url 元素 tooltip 泄露 `"undefined"`（2 项渲染正常） |
| B19 重定向 | ✅ 30 跳环 0.1s 优雅失败（urllib 循环检测） |

## 四、已测未复现清单（R7）

| # | 项 | 结果 |
|---|---|---|
| 1 | 切回阅读态 tab 发全隐请求（= P1'' 修复后行为） | ⛔ 基线发排他 show（本轮定格目标即此） |
| 2 | show 目标串靶（切换类） | ✅ 未复现（10/10 show 目标与切换一致） |
| 3 | show 并行突发/同 sq 交错 | ✅ 未复现（sq 严格单调） |
| 4 | 回归 4 项漂移 | ✅ 未复现 |
| 5 | 阅读态切换后前端额外 show 请求 | ✅ 未复现（仅零矩形 layout；重放为后端内部行为） |

## 五、复用与工具经验（增补）

- 隔离实例：`cd C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2 && USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server`（端口 18765）
- 靶标：`python $TMP/audit-bb-r2/echo_v3.py`（19001/19002）+ 18999 静态页
- 工具经验增补：④ 记录器**必须单包裹**——重复安装会把每请求记成两条（R4/R6 的「成对 show」部分为此伪影，R7 单包裹实测每调用 1 请求；a556 源码注释「两个独立 fetch」与实测不符，留白盒复核）；⑤ 轮切类多步序列总等待控制在 30s 内（IAB evaluate 上限），必要时拆格并在格首重验激活态——**激活态在格间不可假设**。
