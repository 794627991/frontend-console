# 第 5 轮黑盒对抗测试报告 —— 前端控制台「内嵌浏览器」功能（收敛判定轮）

- 轮次：round 5（幽灵累积终证 + 四轮验收快照定格 + 兜底新面速探 + 回归终扫）
- 日期：2026-11-13
- 测试对象：v4.1.0-a556 基线 d9c8886（patch-round-1/2/3/4 均为提案未应用；已读 patch-round-4.md，B16–B19 已登记为 N3/N5/N1' 验收基线）
- 方法：IAB 合成事件驱动 + 只读 fetch 记录器（格内重装守卫——本轮再次确认 IAB 存在**格间自动重载**现象，跨格页面状态不可假设，取证代码必须单格自足）+ curl/python 直打 + 靶标（18999 / 19001 / 19002 自签）
- 铁律遵守：零代码修改（仓库仅新增本报告）；真实实例（pid 4068）未杀未干扰，仅 GET 探测；结束时测试端口全清（已核验）

---

## 结论：零新确凿（B16–B19 基线全部复现且定格，无漂移）——黑盒面收敛

本轮未产生 B20 及之后的新编号：幽灵累积终证仅**细化**了 B17 的量化口径（不改变登记内容）；兜底新面（8KB URL/30 跳环/5MB session）全部干净；四轮回归终扫无漂移。

---

## 一、幽灵累积终证（B17 量化定稿 + N3 精确回归口径）

单格自足取证（3 tab → 连续侧栏 ✕ 关 2 个激活态 tab → 合成 resize），记录器抓取：

**第一轮（新建 web:2/3/4，web:4 激活）：**
- 侧栏 ✕ 关 web:4（激活态）→ 自动切 web:3 → 侧栏 ✕ 关 web:3（激活态）→ 存活 web:2；
- resize 后记录：`layout(0,0,0,0, tab:web-3)`、`layout(0,0,0,0, tab:web-4)`、`layout(223,140,717,580, tab:web-2)`——**2 个幽灵并存**，各发一次全零 layout。

**第二轮（中断运行的日志留存，等价重放）：**
- 再建 web:5/6/7 并同样关闭 2 个激活态 → resize 记录 **4 个幽灵同帧**（web-3/4/6/7 全零 layout）+ 存活 web-5 正常 layout——**幽灵跨轮线性累积：ghost 数 = 旁路（侧栏 ✕）关闭激活态 tab 的次数**。

**pill ✕ 正路对照（同页同记录器）**：新建 web:8（激活）→ 胶囊 ✕ 关闭（closeEditorTab 路径）：
```
POST /api/web/tabs   body: {"act":"dispose","tab":"web-8"}    ← dispose REST 正常发出
（无 /api/disconnect 噪音）
随后的 resize：幽灵列表仍为 4 个旧幽灵，无 web-8 —— 正路关闭零幽灵
```

**N3 应用后的精确回归口径**（同一测试脚本重放，全部应满足）：
1. 侧栏 ✕ 关闭 web tab 的请求序列中出现 `{"act":"dispose","tab":"web-N"}`；
2. 序列中**不再出现** `POST /api/disconnect {"port_id":"web:N"}`；
3. 合成 resize 后 `layout(x,y,w,h)` 全零条目数 = **0**（ghost 归零）；
4. 存活 tab 的 layout 正常（rect 非零）。

## 二、验收快照（d9c8886 基线，补丁应用后的对照基准）

### 快照 1：B7 变体族 12 格矩阵（R3/R4 建立并复核；A8' 验收基线）

| 操作 \ 目标 | 在激活 tab 上操作 | 在非激活 tab 上操作 |
|---|---|---|
| back | `tab:"<激活ctl>"` ✅ 正确 | **`tab:"<激活ctl>"`** ❌ 应为所属 ctl |
| fwd | ✅ 正确 | ❌ 串 |
| reload | ✅ 正确 | ❌ 串 |
| sys（↗浏览器） | open_url(激活 URL) ✅ | ❌ open_url(激活 URL) |
| Ctrl+滚轮 | 激活 tab 缩放 ✅ | ❌ 缩放落激活 tab（值/样式/记忆键三重） |
| Ctrl+0 | 激活 tab 复位 ✅ | ❌ 复位落激活 tab |
| star（R2） | ✅ | ❌ 收藏/取消激活 tab 的 URL |
| read（R2） | ✅ | ❌ 阅读模式开在激活面板 |
| claude（R2） | ✅ | ❌ 填入激活 tab 内容 |
| 顶栏回车（对照） | newTab 语义 ✅ | —（全局入口，无所属 tab 概念） |
| 面板内回车（对照） | 所属 tab 导航 ✅（激活态下两语义重合） | —（非激活面板不可见） |
| Ctrl+Enter（对照） | 新开 ✅ | —（同上） |

- R5 复核：wheel@非激活 格定性复现（缩放落非操作 tab；基线缩放值受历史 localStorage 污染，清洁数据以 R3/R4 为准）。

### 快照 2：B16 请求序列（N3 验收基线，R5 干净重采）

```
侧栏 ✕ 关闭激活态网页 tab（web:3）的完整相关请求：
POST /api/disconnect    body: {"port_id":"web:3"}          ← 必败噪音（N3 后应消失）
（无 POST /api/web/tabs {act:"dispose"}）                   ← dispose 缺失（N3 后应出现）
POST /api/web/tabs     body: {"act":"show","on":true,"sq":11,"tab":"web-2"}   ← 存活 tab 自动切换（正常）
POST /api/web/tabs     body: {"act":"layout","x":223,"y":140,"w":717,"h":580,"tab":"web-2"}  ×3（正常）
合成 resize 后：
POST /api/web/tabs     body: {"act":"layout","x":0,"y":0,"w":0,"h":0,"tab":"web-3"}   ← 幽灵（N3 后应归零）
POST /api/web/tabs     body: {"act":"layout","x":223,"y":140,"w":717,"h":580,"tab":"web-2"}   ← 存活（正常）
```

### 快照 3：B17 幽灵语义（N3 细化验收）

| 语义 | 基线行为 |
|---|---|
| 激活态侧栏 ✕ | 留 1 幽灵（resize 时发全零 layout，永久存活） |
| 后台态侧栏 ✕ | 不留幽灵（`display:none` 守卫拦截止） |
| pill ✕（closeEditorTab） | 不留幽灵 + dispose REST 发出 |
| 累积 | 线性：ghost 数 = 旁路激活态关闭次数（实测 2 轮 × 2 次 = 4 幽灵同帧） |
| 桌面级后果（存活控件缩 50×50） | 存疑（无头不可达，手册 #11） |

### 快照 4：B18 七格（N5 验收基线，R4 建立；R5 未复测变化）

| 格 | 基线行为 |
|---|---|
| 元素缺 url | 渲染正常；tooltip 泄露 `"undefined"`；点击开空白 tab |
| url=数字 | 渲染正常；点击 → 数字类型 URL 入导航栈（类型污染） |
| url=null | 渲染正常；同缺 url |
| 混合 4 元素 | 全渲染无崩溃 |
| 恰好 100 条 | 4ms 全渲染 |
| 尾斜杠重复 | 独立收藏共存（精确串去重，cosmetic 维持） |
| 容量上限 | `_webFavsSave` slice(0,100) 保最新 |

### 快照 5：B19 各格（N1' 验收基线，R4 建立；R5 复测）

| 格 | R4 基线 | R5 复测 |
|---|---|---|
| 重定向环 12 跳 | 0.098s 优雅失败（urllib 循环检测） | 30 跳同样 0.13s 优雅失败 ✅ 无漂移 |
| Location 空格/百分号 Unicode/相对路径 | 全通 | —（本轮未复测，R4 定格） |
| 302→跨主机自签 https | 取页成功（CERT_NONE 跨主机实锤——N1' 后此格必须翻转为失败） | —（R4 定格） |
| 8KB 超长 URL | — | ✅ 新增：全通（ok:true，URL 8136 字符回显，无长度限制）0.12s |
| 8KB+30 跳组合 | — | ✅ 新增：优雅失败 0.1s |

## 三、兜底新面速探（全部干净，无 B20）

| 探针 | 结果 |
|---|---|
| fetch_text 8KB URL | ✅ 接受并取页成功（无 URL 长度限制；回显完整） |
| fetch_text 30 跳重定向环 | ✅ 0.13s 优雅失败（urllib 循环检测），无挂死 |
| fetch_text 8KB+30 跳组合 | ✅ 同上 |
| web-session 5MB（合法结构+超长冗余） | ✅ 写入 15ms；reload 2.08s 完成（readyState complete）；UI 存活；恢复正常；**首次保存自愈至 55 字符**（冗余字段剔除，R3 结论复现） |

## 四、回归终扫（四轮清单抽查汇总——无漂移）

| 轮 | 抽查项 | 结果 |
|---|---|---|
| R1 | 收藏菜单 XSS 渲染（0 img/0 script） | ✅ |
| R1 | API 怪 id 优雅（负数 id/顶层数组/坏 JSON 与 R1 逐字一致） | ✅ |
| R1 | 多开/切换/关闭语义（本轮幽灵测试过程中 3 tab 全程正常） | ✅ |
| R2 | B7 wheel 格（定性） | ✅ 变体在 |
| R2 | 尾斜杠去重（精确串） | ✅（R4 定格，本轮引用） |
| R2 | API 8KB/30 跳边界（B11 族） | ✅ |
| R3 | 阅读模式剥离（R4 复测） | ✅ |
| R3 | 缩放跨站隔离（R3 定格；本轮 wheel 格引用） | ✅ |
| R3 | 幽灵/抽屉语义 | ✅ 本轮终证 |
| R4 | W22 请求序列 | ✅ 本轮干净重采 |
| R4 | B13 补形 | ✅ R4 定格 |
| R4 | 重启恢复（收藏/会话/设置三态） | ✅ R4 复测 |

## 五、黑盒不可达清单（R5 终版）

1. WebView2 原生控件级后果：幽灵 layout 的「存活控件缩 50×50」、休眠/唤醒、呼吸态、target=_blank、加载失败层、`javascript:` Navigate 语义（桌面 only）。
2. `/api/web/tabs` act 分发与 tab-id 校验（无头被「控件管理器未装配」短路）。
3. 抽屉「全部关闭」web 路径（W9 阻断；A7 落地后才可达）。
4. 事件单播（D3）控制级观察（无头无事件泵）。
5. 真实鼠标/键盘点击（IAB 工具通道 t=0 失效）。
6. IDN punycode 可解析场景（靶标环境无解析记录）。

## 六、下一轮复用

- 隔离实例：`cd C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-r2 && USERPROFILE="C:\Users\gaoyi13\AppData\Local\Temp\audit-bb-home" python -m src.server`（端口 18765）
- 靶标：`python $TMP/audit-bb-r2/echo_v3.py`（19001/19002，loop 上限已扩至 30 跳）+ 18999 静态页
- 工具经验：IAB **格间自动重载**会清空页面级记录器与内存态——多步取证必须单格自足（进入时重装记录器守卫 + 状态即时落盘返回值）
