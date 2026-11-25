# 对抗式终审报告（C 组·黑盒功能攻击）——28 补丁修复后验证

- 审计对象：`http://127.0.0.1:8867`（a393，28 补丁全量落盘后）+ CDP 9223 真实页面
- 方式：黑盒功能攻击——HTTP API + CDP 真实 DOM/键盘/鼠标事件，全部从用户视角触发；fixture 自建自清
- 环境：Windows 10 19045 / Python 3.14.7 / SlikSvn 1.14.5 / Y: 真实 SMB 网络盘（\\10.1.13.30\gaoyi13）
- 时窗：2026-11-06 09:40 ~ 11:10
- 已知不重复报：doc/patch-apply-backend.md、doc/patch-apply-frontend.md 的全部发现

---

## 一、结论先行

**12 个攻击项：10 项 PASS、2 项实锤。28 补丁的修复效果在用户视角下 10/12 成立；2 个实锤分别是 P3 级服务器崩溃（并发查询期间切档 → 进程段错误死亡，已两轮独立复现）与 P4 级 emoji 残留（banner 文案 ⏪ 两处，补丁清单外）。**

| # | 攻击项 | 判定 |
|---|---|---|
| 1 | P-1 多槽缓存：两库交替 60 次 | **PASS**（并发场景归入实锤 1） |
| 2 | P-2/P-4/P-18 符号查询三档对照 | **PASS** |
| 3 | P-3/P-7 文件操作 | 串行 **PASS**；并发切档+查询 → **实锤 1（崩溃）** |
| 4 | P-5 档位下拉三场景 | **PASS**（任务异步失败→重开恢复子场景未能注入，记未覆盖） |
| 5 | P-8 网络盘真删/链接区分 | **PASS** |
| 6 | P-9 fsym 改键生效 | **PASS** |
| 7 | P-12 fsym 过滤词不被覆盖 | **PASS** |
| 8 | P-13 查询过的库删除 | **PASS** |
| 9 | P-14 跳转窗口内关 tab | **PASS** |
| 10 | P-21 全 UI emoji 复扫 | **实锤 2（⏪ 两处）** |
| 11 | P-22/P-24 语言下拉 | **PASS** |
| 12 | P-25 四反引号 hover | **PASS** |

---

## 二、逐项结果

### 1. P-1 多槽缓存（两库交替 F12/Ctrl+T 各 30 次）— PASS

fixture：projA（sqlite 档，12 符号含中文/大小写混合）+ projB（sqlite 档，44 文件）。串行交替 definition(projA)↔symbols(projB) 共 60 次：

- **结果正确**：60/60（Application→symbols_src.py:5、beta_func_中文 每轮命中）
- **句柄**：268 → 232 → 212（**Δ-56，不升反降**——多槽复用连接，无泄漏）
- **延迟**：首 10 次均 178ms → 末 10 次均 52ms（无劣化，缓存热后更快；最大 488ms 为 readtags 子进程首查）
- 服务器全程存活

注：任务书要求的"两库交替各 30 次"以 API 直打完成（F12/Ctrl+T 的网络投影）；键盘→API 的接线由 P-9/P-12 的真实按键测试旁证。**并发形态的交替（撞切档）归入实锤 1**。

### 2. P-2/P-4/P-18 符号查询三档对照 — PASS

同一 fixture（projA）在 memory/readtags/sqlite 三档下跑同一组查询，全部结果一致且正确：

| 查询 | sqlite | readtags | memory |
|---|---|---|---|
| `appl` / `Appl`（大小写混合前缀） | Application+application | 同 | 同 |
| `get_中文` / `GET_中文` | get_中文+Get_中文 | 同 | 同 |
| `蓝牙`（纯中文） | 蓝牙配置类 | 同 | 同 |
| `probe_work` / `PROBE_WORK`（CI） | 双命中 | 同 | 同 |
| F12 `get_中文`/`蓝牙配置类`/`Application` | symbols_src.py 正确行号 | 同 | 同 |

readtags 档中文 F12（P-4 桥接）：命中且行号与 sqlite 基准一致。readtags 档时延 0.4~6s/查询（该档已知口径：每次起子进程+中文走 dump，与档位提示一致；大库下有 `_ascii_dump` mtime 缓存）。

P-18 转义注入（readtags 档）：`q=-l`、`q=-i`、`q=-p`、`symbol=-l`、`symbol=-` 全部返回 **0 结果、无尖峰**（200~430ms），正常查询 `appl` 同时命中——argv 注入面（S37-7）从用户视角封闭。

### 3. P-3/P-7 文件操作 — 串行 PASS / 并发实锤（见实锤 1）

串行场景（S37-2 原型）：sqlite 档查询 3 次（连接进多槽缓存）→ 立即 build 重建 → 任务成功、**meta.backend 保持 sqlite（无 readtags 静默降级）**、库目录无 `.tmp` 残留、sizes.db=20480 与磁盘一致。上次运行中观察到的"ok=False err=''" 经复测确认为并行 D 组审计占住任务槽导致 POST 未被接受（409 重试窗口耗尽），非产品缺陷。

### 4. P-5 档位下拉（CDP 真实 UI 三步）— PASS

CDP 持久 target 上走完整用户路径：文件树右键 finalcf-ui → 「代码索引…」→ 建库（memory）→ 重开面板：

- **场景 A（改档→取消→回弹）**：下拉改 readtags → 确认弹窗出现，`z-index=10001`（R2-3 生效），elementFromPoint 取弹窗中心**命中弹窗内部**（真实可见，C-2 遮挡修复成立）→ 点「取消」→ 下拉回弹 memory ✓
- **场景 B（改档→确认→切成功）**：确认后后端 meta 切到 readtags，面板下拉显示 readtags ✓
- **场景 C（任务失败→显示恢复）**：主库长任务占槽期间切档 → POST 409（d2.ok=false 出口）→ 下拉复位为真实档 sqlite（R3-3 :883 出口生效）✓。R4-F1 前瞻同步（POST ok 后 m.backend=v）在两次"POST 成功+任务成功"场景中显示正确；**「POST 成功但任务异步失败→面板重开恢复」子场景尝试两类注入（外部锁 tags/tags.db、槽竞争）均未能制造出稳定的任务失败（锁被重试链绕开、POST 溜进槽间隙），记为未覆盖**——该出口的逻辑代码在场（nav.js:897-901）且 patch-apply-frontend 已用受控探针验证，非回归证据。

### 5. P-8 网络盘真删/符号链接区分（Y: 真实 SMB 盘）— PASS

Y:\nfs 下新建 svnadmin 仓库 + checkout 工作副本，提交普通文件 real_target.c 与符号链接 sym_link.c（svn:special），删除两者后调 `/api/vcs/changes`：

- **真删的 real_target.c 可见**（st="!"）✓
- **符号链接 sym_link.c 隐藏**，`symlink_hidden=1` ✓

附记（非产品缺陷，留档）：本机 SlikSvn 1.14.5 Windows 客户端会把 `svn:special` 属性**传染给同批提交/链接目标对应的普通文件**（分离 commit、不存在目标名逐一实验证实：仓库端 r1 属性为空，传染发生在客户端写 wc.db 阶段）。此时面板按 wc.db 如实过滤会把被污染的普通文件一并隐藏——数据源被上游工具污染所致，Linux 团队仓库（真实场景）无此形态；修正 fixture 的 wc.db 后过滤行为即恢复精确。建议知悉即可，不立项。

### 6. P-9 fsym 改键（设置页→保存→刷新→生效）— PASS

设置页点击「文件内符号」键钮 → 录制 F4（钮文变 F4）→ 点本 pane「保存」→ 拦截确认 POST body `{"nav_keys":{...,"fsym":"f4",...}}` → GET /api/theme 返回 `fsym=f4`（**白名单落盘，S37-5 修复生效**）→ `location.reload()` → 重新打开文件 → monaco 聚焦后按 F4 → **文件内符号面板打开**——改键→保存→刷新→生效全链成立。（测试后已恢复默认并复核 config。）

注：设置 pane 内有多个同名「保存」按钮（终端设置等），DOM 自动化需按容器定位；人工操作无歧义，不算问题。

### 7. P-12 fsym 首拉竞态（打开面板立即输入）— PASS

finalcf-ui 切 readtags 档（首拉时延 0.3s+，制造真实竞态窗口）：F4 打开面板 → **0ms 内**（resolve 前）输入 `zzzz` → 2.6s 后（fetch 已 resolve）面板**保持空列表**（无全量泄漏）✓ → 清空输入后全量 3 符号回归 ✓ → 输入 `ui` 过滤正常 ✓。S-B4 的"过滤词被全量覆盖"未复现，P-12 修复成立。

### 8. P-13 delete（查询过的库→删除→目录消失）— PASS

projC 建库（sqlite）→ definition 查询命中（连接进缓存）→ POST /api/nav/delete → `{"ok":true}`、libs 列表无残留、**库目录（nav\86fa9e56…）从磁盘消失**、工程目录不受影响。D-4 的"静默 ok+残留"未复现。

### 9. P-14 跳转护栏（跳转窗口内快速关 tab）— PASS

外部 touch 源文件（mtime+30s 制造重读路径）→ monaco 光标置于符号 → F12 跳转 → 分别在 **+25ms / +200ms / +500ms** 点编辑器 tab ✕ 关闭 → 等 2.6s 收集全部通知：**零"重读失败/disposed/destroyed"类误弹**（S-B7 未复现，护栏链成立）。tab 存活时正常跳转不受影响。

### 10. P-21 全 UI emoji 复扫 — 实锤 2（见实锤区）

当前页面 DOM（2010 个文本节点）零彩色 emoji ✓；**源码层扫描发现两处会渲染的彩色 emoji 残留**（banner 文案 ⏪），在 P-21 补丁位置清单之外。

### 11. P-22/P-24 语言下拉 — PASS

- 下拉 24 选项：**makefile 不在** ✓（P-22 撤死项生效）
- **ruby 在** ✓（P-24 生效）
- localStorage 种入 `hg-ed-lang-override={"…ui_src.py":"makefile"}` 后重开文件：下拉 `value=""、selectedIndex=0`，**显示「语言：自动」**——patch-apply-frontend 建议的记忆值兜底已落码并生效，无"显示空白"回归。

### 12. P-25 hover 四反引号 snippet — PASS

snip_src.py 定义行+下 2 行窗口内含 ```` 行（sqlite 档 definition snippet 实测含四反引号）。CDP Input 域真实 mousemove 悬停 snipTest → hover 出现：

- 标题 **snipTest 只出现 1 次**（无 R2-1 式标题重复）
- **代码块完整**（```` 行作为内容在场，未被当闭合栏截断）
- **路径行 `snip_src.py :4` 在场**（S-B8 的"路径行被吞"未复现——动态围栏长度=内容最长反引号串+1 生效）

---

## 三、实锤区

### 实锤 1（P3）：并发查询期间切换档位 → 服务器进程段错误死亡

**复现路径（两轮独立复现 + 三次现场死亡）**：

1. **独立干净复现**（无任何并行干扰）：8 个查询线程持续打 `/api/nav/definition`（两个 sqlite 档库交替）+ `/api/nav/symbols`，1 个线程循环 `POST /api/nav/reindex`（readtags↔sqlite 交替）。**12.2 秒后服务器进程死亡**：全部连接 ConnectionReset，随后端口无人监听。统计：121 次 definition + 116 次 symbols 成功、66 次 reindex 被接受后崩溃。bash 记录退出码 **139（Segmentation fault）**。
2. **服务器日志铁证**（我方第二次起的实例，stdout 全程留档 `.zcode/tmp/finalcf/server_stdout*.log`）：死亡时刻的最后一条日志恒为 **`POST /api/nav/reindex → 200`（任务被接受）**，同秒并发查询洪流（每秒数十条 200）戛然而止，进程 SIGSEGV。第二次死亡（10:00:08）与第三次死亡（10:08:56，57 次 reindex POST 中的最后一次 200）模式完全一致。
3. **用户提供的原实例（PID 19304）同样死法**：09:51 前后死亡时并行 D 组健壮审计的 22 线程混合攻击（查询+reindex 循环）正在打同一服务器，其 watchdog 时间线（`.zcode/tmp/resdgd/timeline1.tsv`）记录 `PROC GONE / PORT-DEAD`。三次死亡全部落在"reindex 被接受 + 并发查询在途"的窗口。

**用户视角影响**：索引面板切档操作与任何正在进行的符号查询（自己多开、或同事经分发页同时用）并发时，整个控制台后端（串口/编辑器/文件树全部 API）瞬间死亡且无人重启——比 S37-2 当年的"静默降级"严重一个量级。

**黑盒归因链**（不下白盒结论，供白盒组定位）：P-3 落盘的 reindex/build `work()` 前置 `nav_index._close_tagdb()`（S37-2 修复），在 P-1 多槽改造后语义=**关闭全部库的常驻连接**；与此同时其他请求线程正持有这些连接执行 sqlite 语句。`close` 与在途语句的竞态落在 C 扩展层 → 段错误。patch-apply-backend 的 P-1 探针只测过"`_get_tagdb` 锁内 `_old.close()` 撞在途查询"（结果为等待 534~593ms、不崩溃），**未测 `_close_tagdb` 锁外 close 撞在途语句**——本实锤不在其已知发现内。

**修复方向建议**（供补丁组）：切档/重建窗口期对查询侧让路（patch-log P-6 的 `_db_busy` 结构化互斥是现成提案，被 P-3 重试方案替代后此场景证明重试不够）；或 `_close_tagdb` 改为延迟关闭/换代（新连接换入、旧连接等在途语句结束后再关）。

### 实锤 2（P4）：banner 文案彩色 emoji ⏪ 两处残留（P-21 补丁清单外）

- `web/js/harness/chatctl.js:334`：`showBanner(j.ok ? ('⏪ ' + j.msg + '——发送消息即续上') …)`
- `web/js/harness/main.js:1094`：`showBanner('⏪ ' + j.msg, 3600);`

⏪（U+23EA）Emoji_Presentation=Yes（V8 `\p{Emoji_Presentation}` 判定，与 P-21 清单里 1️⃣2️⃣3️⃣⬇ 同类），showBanner → notifyPop 直接渲染进 DOM 文本。用户触发 harness 会话「回退/回滚」成功时可见，违反"UI 要么 SVG 要么不要"铁律。当前页面 DOM 扫描零命中只因本次会话未触发过这两个 banner——源码渲染链明确，无需触发即成立。P-21 的位置清单（update_server.py 五处 + settings.js 三处）未覆盖 harness 目录。

---

## 四、环境事件与测试影响（非实锤，留档）

1. **并行 D 组审计共用同一 8867 服务器**：其 22 线程混合攻击与 fixture 清理在本组测试期间多次扰动任务槽（409）并造成服务器死亡（归因见实锤 1 的第 3 点）；其 fixture 清理曾连带删除本组 finalcf-ui 库一次（重建后继续）。本组所有判定均在排除干扰的干净窗口取得。
2. **config.json 清空事故（本组责任）**：10:21 一次本地排障 `import src.file_tree` 触发 app_state 初始化副作用，config.json 被隔离为 `.bad` 并只剩 `{"recent"}`（期间 vcs 面板对 Y: 盘根返回 400 即此因）。**10 分钟内从 `.bad`（30 键完整）恢复 config.json 与 .bak**，服务器进程内存态全程未受影响，data_dir/tree_roots/nav_keys 复核一致。教训已固化：黑盒排障一律走 HTTP/文件直读，不 import src.*。
3. **服务器实例更替**：测试期间 8867 由原 PID 19304（死亡）→ 本组重启 3 次（其中 2 次死于实锤 1 场景，均留有完整 stdout 日志）。收尾时服务器为最后重启的实例、运行正常；并行 D 组亦有一次自行重启。

## 五、留存物

- 服务器死亡日志：`D:\AI\前端控制台\.zcode\tmp\` 已随 fixture 清理删除前，关键行已摘录本报告；D 组 watchdog 时间线 `.zcode/tmp/resdgd/timeline1.tsv`（并行组资产，未动）。
- fixture 已全清：`D:\AI\前端控制台\finalcf-ui\`、`.zcode\tmp\finalcf\`（projA/B/C、svnrepo×5、micro、脚本）、`Y:\nfs\finalcf-svn-wc{,2,3}`；nav 库经 `/api/nav/delete` 删除（libs 仅剩会话前已有的 3 个 r35 fixture 库与主库 f93dd）。
- config 复核：30 键完整，tree_roots/nav_keys/data_dir 与基线一致（fsym 已恢复 ctrl+shift+o）；localStorage 种子已清；CDP 测试 target 已关闭。
