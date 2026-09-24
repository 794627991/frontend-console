# ZCode 架构方案落地 v1（v2.4.0 / refactor/zcode-arch）

> 源方案：`docs/zcode-参考架构笔记.md`（ZCode 源码分析的可抄清单）。
> 本文记录第一期落地的内容、wire 协议、与 ZCode 机制的对照表、以及未落项的迁移路线。
> 分支：`refactor/zcode-arch`（基于 `refactor/harness-split@0a7aaa8` 叠加，主仓 master 不受影响）。

## 一、本期落地（笔记优先级 1+2+4+8 → 3+5+6+7 → 11-治理）

### 1. 事件溯源层 `src/eventlog/`（新增包，对照 ZCode contracts + eventStore + publisher）

| 模块 | 对照 ZCode | 内容 |
|---|---|---|
| `types.py` | session.events.ts | 事件类型常量清单（`SessionEventType`，snake_case）；信封注入（seq/ts/epoch/sid/turn/type/kind）；turn 窗口瞬态回收策略（`TRANSIENT_SESSION_EVENT_TYPES` 本期为空集，机制预埋） |
| `store.py` | in-memory-session-event-store.ts | 锁内分配 seq（**修 v2.x 竞态**：reader/HTTP/peer 轮询并发 emit 同号乱序）；deque(maxlen=2000) 保留窗 + floor_seq；resume/snapshot/reset 三态判定；bump_epoch（日志重写）/restore（GC 重建续号续代）；计数器只增不减 |
| `bus.py` | persistent-protocol.ts + publisher | subscribe(base) 三态；订阅队列先行→快照回放→live 段按 seq 去重（无漏无重）；慢订阅者队列满→清积压投 reset（不再"丢最旧塞最新"）；ka 心跳 5s（`event: ka` 命名事件，SSE 注释行 JS 不可见做不了看门狗） |
| `truncate.py` | core.ts + projection-rows.ts | 终态工具输出头尾各 32KB 截断（UTF-8 字节口径，多字节切点 errors=ignore）；`_truncated:{total_bytes,ref}` 元数据；stash LRU（32 条/4MB） |
| `reducer.py` | event-reducer.ts | 纯函数投影（status/turn/turn_count/last_error）；未知类型只 bump（前向兼容）；live/replay 共用同一归约；store.append 内嵌增量归约 |
| `log.py` | —— | 每会话门面（store+bus+stash），HarnessSession 唯一对接点 |

### 2. harness 后端接入（`src/harness/`）

- `session.py`：`events/_seq/clients` 三件套收编为 `self.log`；`emit()` = 截断→锁内盖章→落 store→广播（对照"先落 eventStore 再广播"）；**turn 边界显式化**（`_turn_start/_turn_end`，起跑点=send 占位/CLI 自发回合/peer 续跑，收尾点=result/中断/异常退出）——此前靠 `data.type=='result'` 隐式判定；`_seq` 保留为只读属性（兼容位）。
- `routes.py`：`/stream` 换 subscribe(base) 协议；`/events` 轮询兜底带 epoch（轮询通道不再只有 seq 盲区）；`/transcript` 带 epoch；`/rewind` 成功后 `bump_epoch()`（转写重写=换代，客户端旧水位作废）；新增 `/tool_full?sid=&ref=`（截断全文按需拉取）。
- `lifecycle.py`：GC 重建 `restore(epoch, seq)`——同代续号可 resume；旧 meta 无 epoch 换新代（一次性 snapshot 重建代价）。
- `meta`：`claude_harness.json` 会话条目新增 `epoch` 字段（v2.35.2 的 seq 续号机制扩展）。

### 3. SSE wire 协议（v2.4.0 起）

```
GET /api/harness/stream?sid=<sid>&epoch=<base_epoch>&after_seq=<base_seq>

event: ack                      ← 连接首帧
data: {"mode":"resume|snapshot|reset","epoch":...,"seq":last,"floor_seq":floor}

mode=reset 时紧随：
event: reset
data: {"epoch":...,"reason":"epoch-mismatch"}     ← 生成器终止，客户端走 transcript 重建

mode=snapshot 时：客户端先清场，随后重放保留窗（普通 data 帧）
mode=resume 时：直接补 (base_seq, last] 增量（普通 data 帧）

data: {..., "seq":N, "ts":..., "sid":..., "epoch":..., "turn":..., "type":"...", "kind":"..."}   ← 事件帧
event: ka                       ← 空闲 5s 心跳
data: {}

event: reset                    ← 慢订阅者积压超 500 被服务端显式断开
data: {"reason":"slow-subscriber"}
```

三态判定（对照 conversation-topic-publisher.ts:743-788）：
- `resume`：`base.epoch == 当前 epoch` 且 `floor <= base.seq <= last`
- `snapshot`：base 缺失 / base.seq 落在保留窗外 / 越过 last
- `reset`：epoch 不匹配（/rewind 换代）

### 4. 前端（`web/js/harness/`）

- `10-sse.js`：openSSE 换新协议（ack/reset/ka 监听 + epoch 水位随 `_HG.epoch`）；**20s 无帧看门狗**（5s 巡检，判死强制重连带水位续传）；`_hgSseResetLocal`（snapshot 清场）/`_hgSseRebuild`（reset→transcript 重建→新水位重开流）；`_hgEventsPoll` 轮询兜底兼 epoch 校验；saveCache 存 epoch + 滚动五元组。
- `12-sessions.js`：switchTo 恢复 epoch；**滚动记忆**（对照 chatSessionScrollMemory：贴底→回底跟读；否则恢复 clamp 后的 scrollTop，rAF 等布局结算）。
- `20-main.js`：扩段分支补 `histRestoredAt` 400ms 守卫（恢复写 scrollTop 不误触自动扩段）。
- `03-ask-md.js`：**hljs 高亮缓存池**（对照 shikiHighlighter：指纹 key=`lang:len:head100:tail100`，LRU 500）。
- `07-hist.js`：**思考双渲染路径**（对照 reasoning.tsx:559 注释——流式逐块跑 md 越来越卡）：流式 textNode O(1) 追加 + pre-wrap；endThinking 定稿一次性 renderMd 升级（失败降级保留纯文本）。
- `02-base.js`：`_HG.epoch` / `_HG.lastFrameAt` 状态位。

### 5. CSS token（`web/style.css`）

- `--ui-font-size` 基准 + 七档派生（`--fs-2xs..xl`，与既有硬编码值逐一等值，视觉零变化）；harness 区 109 处 font-size 已 token 化。
- 代码块语义色 `--code-bg/--code-fg/--code-muted`（亮色 8 主题统一覆盖——代码块从此跟主题换肤）。
- `.hg-code` 加 `content-visibility:auto + contain-intrinsic-size:auto 200px`（视口外代码块跳渲染）。

### 6. 架构治理（对照 architecture-policy.yaml + scripts/architecture/）

- `architecture-policy.yaml`：声明式模块清单（eventlog managed:true 零外部依赖 + 唯一公开入口 `__init__.py`；harness 登记未治理 managed:false——渐进迁移）。
- `tools/architecture_check.py`：AST 提取 import 边；模块归属=roots 最长前缀；依赖白名单/深 import/行数/循环四规则；`--changed` 只查 git 改动波及；baseline 指纹豁免（只有新增违规退出码 1）。

## 二、验证记录

| 项 | 结果 |
|---|---|
| `tests/test_eventlog.py`（v3.0 44 check → v3.1 增至 60） | 60/60 |
| `tests/test_ledger.py`（v3.1 新增：账本/世代/泵/镜像 17 check） | 17/17 |
| `tests/test_roles_routing.py`（既有 155 check） | 155/155 |
| `tests/test_route_smoke.py`（42 路由 43 方法，含 /queue /queue_act） | 全健康 |
| `compileall src` | OK |
| 前端主链 stub 冒烟（tools/_chain_smoke.js，含 23-reducer） | 全过 |
| 前端未定义引用（_undef_check.js） | 23-reducer 零命中 |
| state 对账（_state_audit.js） | 38/38 |
| Flask test client 集成冒烟（stream 三态/events/transcript/tool_full/meta/GC 重建） | 全过 |
| 真机启动 + 浏览器视觉验收（进程面板/思考头/徽标/diff/摘要行/spinner） | 全过 |
| run.bat 真机启动 | 窗口正常 |

## 三、v3.1 第二期落地（原迁移路线 1-5、7 → 已全部落地或收窄）

原「未落项」清账（对照 ZCode 截图三张定调：进程跟踪 UI + DOM 节省全套）：

1. **✅ 前端 reducer 起步**（原路线 1 收窄落地）：新增 `web/js/harness/23-reducer.js`
   ——`_HG.proj` 只由事件信封归约（SSE 每帧先过 `_hgProjEvent` 再走 legacy
   分派），/events 响应带 `proj` 种子。本期投影驱动「进程」面板与回合摘要行；
   handleEvent 的 500 行分派迁移仍按块推进（搬运不是重构）。
2. **✅ durable 输入账本**（原路线 2，#10）：`session._inbox` 服务端真源，
   `queue_admit/queue_discard/queue_to_head/bump_generation/_queue_pump`；
   POST /queue（客户端预生成 id 防事件/响应双画）、GET /queue（切会话种子）、
   /queue_act（now/del/order）。事件 `input_admitted/promoted/discarded`，
   随 meta 落盘（`inbox`/`gen` 字段），GC/重启由 lifecycle 恢复；回合终结
   800ms 延迟自动泵，失败条目作废不静默。前端 `_HG.queues` 退化为渲染缓存。
3. **✅ 子代理镜像事件**（原路线 3，#12）：reader 循环把 CLI
   task_started/task_notification 合成 `subagent_started/subagent_result`
   干净生命周期事件（tid/agent_type/desc/bg/task_id/ok/brief/tokens/tool_n），
   reducer 落 `proj.agents`；前端既有 20 段 Task 解析（协作包装/转交线/段壳）
   不动——消费端不同不冲突。
4. **✅ microcompact**（原路线 4，#13）：store 增保留窗字节计数，新回合
   开跑且总量超 1.5MB 时，把旧回合 >4KB 的 cli_stream 正文/工具输出就地折叠
   （头尾各 200 字符 + `已折叠 N 字节` 标记 + `_folded` 元数据）。live 已
   广播流零影响——只利好 replay/慢订阅补发与内存。
5. **✅ 分支世代**（原路线 5，#14）：`_gen` 世代号随 meta 持久，/rewind 在
   bump_epoch 同时 `bump_generation()`——旧代排队输入全部作废并事件通知。
6. **✅ 前端 keep-warm**（原路线 7 收窄落地）：快照 LRU 10 超限时不再即时
   delete，保温 30s（`_HG.cacheWarm` 定时器，切回即取消）——A→B→A 快切
   命中热快照零重建，稳态内存不变。加 `content-visibility:auto +
   contain-intrinsic-size`（.h-msg/.h-tool/.h-think-seg/.h-subblock/.h-peer）
   离屏行跳过布局/绘制（对照 ZCode DOM 节省）。
7. **✅ 进程跟踪 UI 重做**（对照截图定调）：右侧面板 B 区「任务进度」→
   「进程」——ZCode 式分组清单（进行中 → / 待处理 N 项 ○ / 已完成 N 项 ✓，
   两组可折叠）+ 本回合实时工具计数行（投影驱动）。主流程：思考段头
   「思考 · 持续了 N 秒」；工具行挂文件类型色块徽标（js/py/css…）与
   `+N -N` diff 计数（前后缀裁剪 O(n) 逼近，LCS 留给抽屉全文）；失败行
   「执行失败」点状下划线标记；回合终结插「🔍 查阅 · N 搜索 · N 文件」
   摘要胶囊；流底 spinner「正在执行…」。

仍未落（有意保留）：delta 流式（等 CLI `--include-partial-messages`）、
回放路径的回合摘要行补齐（转写重建无事件流，新回合起自然稠密）。

## 四、纪律（与 ZCode AGENTS.md 同款，本项目既有约定重申）

- 先更新 spec（本文/注释里的行为规格）再写代码；
- 状态唯一所有者：busy/turn 以 eventlog 投影为准，不再新加散落旗；
- bug 修复用中文注释说明原因与依据（含用户实测记录）；
- `py tools/architecture_check.py` 进 pre-commit（新增违规阻塞）。

## 五、v3.2 第三期落地（ZCode 三大件：回合闭合 + 内联时间线 + 子代理目录）

对照 ZCode 源码逐件抄明白（源文件注记在各条），四张截图全部兑现：

1. **✅ 回合自动闭合「已工作 N 分 N 秒 ›」**（对照 `conversationTurnWorkSegments.ts`
   + `ConversationTurnGroup.tsx` AssistantHistoryStatus）：
   - 组结构改造：`.h-grp-proc{ .h-turn-head + .h-turn-body{ .h-drawer.think + .h-tl } }`，
     正文气泡在组根（折叠区外永远可见——ZCode 的 visibleAssistantTextRow 语义）；
   - 工时三源分级（对照 activeMs 规则）：CLI `result.duration_ms`（冻结事实）→
     回放下一条 user ts 差值 → 本地差值兜底；历史「已工作」绝不吃当前时钟；
   - 文案三态：运行中「工作中 Ns」（live 秒表，`_HG.turnTicks` 登记、切会话/
     SSE reset 全收）→ 完成「已工作 X · N 工具」→ 中断「已停止 · X」；
   - 折叠规则：回放默认收 / live 底部跟读自动收 / 用户点过头永不强制收
     （userToggled 进 dataset 随快照走）；旧快照（v3.1 双抽屉结构）恢复走
     legacy 分支字节级兼容。
2. **✅ 主流程内联工具时间线**（对照 `ToolCallBlocks/ToolLayout.tsx` + explore.tsx）：
   - 执行抽屉退役：工具行进 `.h-tl` 左脊柱时间线（1px 竖线 + 缩进行），
     renderToolUse 与 renderHistTool（回放）同走 `_tlPlace`——两路聚组一致；
   - **查阅聚组**（对照 `exploreToolCall.ts`）：Read/Glob/Grep/WebSearch/WebFetch
     + 只读 Bash（rg/ls/cat/git status 正则族，写命令排除）连续聚成
     「🔍 查阅 · N 搜索 · M 文件」折叠组；运行态头部显最新子行动（活字），
     断组定格汇总并自动收；展开=左竖线子行树（懒填懒丢照旧）；
     组内失败冒泡到组头（showFailureStatus 同款，收起也可见）；
   - diff 行号列（d-ln，+/= 新文件行号、- 旧文件行号）+ 新增绿底/竖条；
   - Bash 单行卡升级 oneclick（终端 command ˅ 展开输出）。
3. **✅ 子智能体目录**（对照 `SubagentDirectorySidePane.tsx` +
   `useSessionSubagents.ts`）：右栏常驻「☰ 目录」伪 tab（不让位不关闭），
   正在运行/已结束分组列表（状态图标 ◐✓✗⏹ + 标题 + 状态词 + 摘要 120 字 +
   相对时间）；点行开视图——运行中→live 实况 tab、已结束→回放 tab（协作代理
   走结论回看分支）；数据源=live 档案 `_HG.agents` + 回放档案 `dyn.agentsRpl`
   （rid 持久发号）；面板 C 区头「⏱ 已结束 N ›」入口，事件驱动刷新。

**验证**：结构断言（折叠头文案命中 883000ms 冻结工时、聚组桶汇总、行号、
oneclick、目录三态行）+ 五项交互点击（回合头/查阅组头/终端卡/编辑卡/目录行）
+ 视觉验收 5/5 PASS（闭合态全景：已工作行+正文+目录 tab）；全量回归
（eventlog 60 / ledger 17 / roles 155 / 主链冒烟 / state 38 / undef 符号级零新增 /
架构 0 违规）；版本 2.3.3。

## 六、v3.2 对抗审计循环（三轮全 PASS 收口）

流程：双对抗代理并行（核心渲染/接线目录CSS 两攻击面）→ 修复 → 复审 → 直到双 PASS。

- **R1（双 FAIL）**：1×P0——回放定稿吃当前时钟（4 条路径：transcript 尾组×2、
  renderAsst 切组、audit 行；「已工作」随墙上时钟增长）；5×P1——diff 折叠区间
  行号不推进、写命令误判 explore（find -delete/重定向/解释器）、oneclick 输出体
  点击误收起、「已结束 N」漏计 agentsRpl（与目录内容矛盾）、运行中 collab 目录
  行开空白实况 tab；另 9×P2（turnTicks 无界增长、_harnessClose 漏收秒表、
  phResume thinkBox 空崩、fallback diff 无行号、PS/复合命令判定不对称、查阅组
  开合不持久化、目录重绘不节流+异常静默、rpl 双 banner、目录贴底滚动、
  CSS 死变量/空规则/新旧规则叠加）。
- **修复要点**：工时三级事实分级（durMs > endTs−t0 > live 时钟；回放态缺事实
  显示无数字「已工作」，对照 chat.history.worked）；行号计数器前置消除 TDZ +
  三个折叠分支照推；explore 写排除补全（对照 ZCode SHELL_REDIRECT_WRITE_RE
  全集）+ PS 读 cmdlet/复合 git；oneclick 排除输出体；计数与 _subDirRows 同源；
  collab 运行行跳主 flow 段；秒表摘除+关闭钩子；查阅组/oneclick 开合进
  hg-open 持久化；目录重绘并入 rAF + console.error；diff 选择器提级显式 padding。
- **R2（核心 PASS/接线 FAIL）**：11 项全核销，但修复引入 3 新 P2——diff 行号
  3px 边框补偿被误删（行号列锯齿）、oneclick 劫持 tHead 丢持久化、collab 跳段
  取段错（漏 tid 直查/取最旧段/缺展开记忆与高亮）。
- **R3（双 PASS 终审）**：3 项增量修复全部核销（.d-ln 负边距对冲与基线逐字
  一致；_hgSaveOpen 补入 oneclick 分支；collab 两级定位取 DOM 最晚段 + 三件套
  对齐 _hgCollabSegFind）；无新增缺陷。
- **验证**：浏览器结构断言（24h 前回放回合=无数字「已工作」、live 432100ms=
  「已工作 7 分 12 秒」冻结、python -c 独立行、rpl-only「已结束 1」、oneclick
  三态交互 allPass）+ 真源码提取 diffHtml 4 分支用例/22 正则用例 node 实测 +
  全量回归（60/17/155 + 冒烟 + state 38 + undef 符号级零新增 + 架构 0 违规）。
- **存档接受项**：重定向子句对引号内 ">" 搜索词保守排除（08-tools 注释）、
  openState 位置键一次性升级漂移（观感）、toolRunPush 预存死代码、
  duration_ms 字段依赖 CLI 事实（缺省回退安全）。

## 七、v3.2.1 用户实测修复（回滚后回合不收起 + 终端卡形态）与对抗审计 R1-R3

用户实测两问题：①回滚过往会话后完成的回合没有收起；②终端卡默认全部展开且
点不动、没有命令文本。逐层定位出**六处根因**，全部修复并三轮对抗收口。

- **问题1 根因（3 处）**：a) `grpFinalize` 折叠条件
  `(opt.hist || (auto && isNearBottom()))` 在回放重建期（scrollTop 在顶恒
  false）与 renderAsst 切组定稿（不带 hist）路径全漏收；b) 回滚处理器
  `_hgReloadFlow` 重建后缺尾组定稿（switchTo/_hgSseRebuild 有、它没有）；
  c) switchTo 快照缓存恢复原样回放开着的 turn-body，坏形态跨快照往返固化。
- **问题2 根因（3 处）**：a) 回放 bash 行（renderHistTool）头模板无命令
  arg——只剩「Bash」秃头；b) **位置键开合记忆体系性缺陷**——`_hgPathKey`
  按 DOM 位置索引链编键存 localStorage，跨 DOM 代际（v3.1 抽屉↔v3.2 时间线
  结构差、回滚截断、扩段窗移）同键指向不同元素，旧记录误开新行还误标
  userToggled（R1 审计已标记为接受项，实测坐实）；c) `_tlExpFlush` 查阅组
  收起依赖 isNearBottom，回放期恒 false。
- **修复口径（用户定调「完成默认收起，必须默认都是收起状态」→ 对照 ZCode
  AssistantHistoryStatus 定稿态）**：
  1. `grpFinalize` 折叠无条件化（仅 `userToggled` 例外——该意图经快照
     dataset 忠实序列化；定稿收的是最新段，视口下方无上抽突跳）；
  2. 尾组定稿下沉 `_histRender` 渲染器本体（`opt.noFinalize` 逃生口留给
     busy 活组 phResume）——扩段/指纹漂移/懒填失败等全部重渲路径一并修好；
  3. switchTo 快照恢复后扫 `.h-grp[data-finalized=1]`：收体（userToggled
     例外）+ 可见「工作中 Ns」残头（app 中途被杀的冻结秒表）定格「已工作」；
  4. 位置键体系整体退役（`_hgPathKey/_hgSaveOpen/_hgApplyOpen` 删除）：
     重建统一默认收起，开合只在当前 DOM 生命周期内有效；`hg-open:<sid>` 仓
     仅剩 `sub:<agentId>` 语义键（稳定不漂移，写入方顺手迁移清死键）；
  5. 回放 bash 行头补命令 arg（前 80 字 + title 全文悬浮）；错误行默认开
     （className 'err open' 承担，错误信息不该藏）；
  6. `_tlExpFlush(histMode)`：回放态必收、live 保持 v2.12 底部跟读判据；
     histMode 由 grpFinalize 用 `_hist` 事实分级传递（尾组定稿发生在
     openState 清空后，只看 openState 会丢回放语义）。
  7. `_hgReloadFlow` 对齐 `_hgSseRebuild`：全清场（行映射/秒表/查阅组）+
     epoch 同步 + `delete cache[sid]`。
- **对抗审计（同一代理三轮）**：R1 FAIL(2)+P3×4 → F1 尾组定稿矩阵缺口
  （扩段/指纹漂移/懒填重渲路径，坏形态可固化）、F2 切走期间回合结束的快照
  残尾永不定稿（result 到达时 `_HG.grp` 空早退）、F3 arg 缺 title、F5 位置键
  死数据、F6 `_hgReloadFlow` 映射不重置，全修；R2 PASS+P3×3 → R2-1 认回
  扩到 interrupted/exit（抽 `_hgTailAdopt()` 三分支共用，返回是否认回）、
  R2-2 `_histRefresh`/`_hgReloadFlow` await 后复检 busy、R2-3 认回定稿传
  hist 切断「切走空闲段」工时虚增，全修；R3 终审 PASS 无新发现。
- **验证**：浏览器全路径断言——重建（14/14 收起、15/15 arg、0 非错误行默认
  开、4/4 查阅组收）、扩段重渲（14→28 组尾组定稿+头可见）、快照往返（无意图
  0 开、用户点开 1 保留）、直跑 `_hgReloadFlow`（回滚路径全绿）、点击交互
  （回合头开合/终端卡懒填展开-收起）+ 截图目检（「已工作 · 2 工具」收起态 +
  「▸ >_ Bash git log --oneline -5」单行卡 + 查阅组收起 = ZCode 形态）+
  全量回归（eventlog 60/60、冒烟、state 38、undef 符号级零新增、架构 0）。
- **行为变化存档**：识图回传/ask/peer 等中段边界定稿现在也收体（= ZCode 段落
  闭合模型，语义自洽无内容丢失）；重定向保守排除等 v3.2 存档项不变。

## 八、v3.2.2→v3.2.4 回合模型重构（用户三轮实测定调）与对抗审计 R1-R2

用户对 v3.2.1 的三条连续反馈，逐条定调并落地为**一回合一组一头条一结论**的
ZCode 回合模型：

- **v3.2.2-a「除了最终结论其他全部收起」**：grpFinalize 增 turnEnd 语义——
  中段定稿把组内正文折进 turn-body；「无文字回复」tip 随入体；正文判定放宽
  到任意深度。
- **v3.2.2-b「没显示工作时长」**：行级 ts 账（histLineTs=当前行=组起点 /
  histActTs=末次非 user 活动=定稿终点，renderHistLine 顶部记/底部后置入账
  ——后置使渲染中定稿恰读到被定稿组末活动）；renderUser 回放 endTs 改
  histActTs（旧口径下一条 user ts 含阅读空闲虚增）。
- **v3.2.3「一个回合整合在一起统一计时」**：**删除 renderAsst 切组定稿**
  （v2.18.1 的按正文切组把一条 user 消息拆成 N 条「已工作」分段计时，用户
  实锤 4 连头）——user→result 全部内容进同一组，定稿一次，头带总工时总
  工具数；turnEnd 只留最后一条正文在根区。
- **v3.2.4「思考和工具调用要有顺序」**：思考段直接挂进工具时间线（段名带
  序号「🧠 思考 N」，汇总胶囊退役为隐藏容器——segCount 统计与 grpFromDom
  认回判据仍依赖）；中间正文定稿折体时按 renderAsst 记的 `_tlAt` 锚点
  insertBefore 插回时间线（_shift 补偿先插后移）——思考↔工具↔中间正文
  全程时序一致；头副位 `· N 思考 · M 工具`；CSS：tl 内思考段透明底+紫左
  边框、tl 内正文裸气泡（藏头像/徽章）。
- **连带实锤修复**：src/harness/meta.py `_meta_load` 的 `_meta = {...}` 模块
  级重绑定让 `from .meta import _meta` 别名（routes/lifecycle/session/
  `__init__`）停在初始空 dict——先 import 后 load 的启动序冷启动
  /api/harness/sessions 恒返空表（盘面 3 条返回 0）。改 clear+update 原地
  更新，别名恒同享真值。
- **对抗审计**：R1 FAIL(6)——F1(P2) 纯正文组折进「无头+收体+内联 none 空
  时间线」三重隐藏（加 `_hasWork` 门+tl 翻显防御）、F2 switchTo 未清 ts 账
  （连带切断 pendingTurnT0 跨会话秒表虚吃链）、F3 renew 回放缺定稿（时序
  倒挂）、F4 回滚钮授到时间线内正文（三处 `!closest('.h-tl')` 守卫）、
  F5 重建兜底缺 turnEnd（死路径一致性）、F6 中段边界+续跑零内容（接受存
  档，F1 门已消除恶化路径）——前五全修；R2 终审 PASS 无新发现。
- **验证**：真实会话 3 user 消息→3 组 3 头（「已工作 4 分 36 秒 · 9 思考 ·
  8 工具」等统一工时）；开体时间线 T1→Bash→T2→正文→Bash→T3→正文→查阅组
  →T6→… 严格交替；根区每组恰 1 条最终结论；rewindInTl=0；截图目检协调；
  冷启动会话列表 3/3；回归全绿（py 全部/冒烟/state38/undef 符号级零新增/
  架构 0）。
- **存档接受项**：压缩/协作/审计等中段边界仍裂组（边界线本就是可见分割，
  各段独立计时）；快照恢复态 `_tlAt` expando 丢失回落体尾（重建必重算）；
  修复前快照存量 can-rewind 残留（LRU 10 份自愈）。

## 九、v3.2.5 思考段 ZCode 形态收尾（用户三连反馈）与对抗审计

- **「思考几的描述不要，要思考持续了几秒」**：思考段名去序号（「🧠 思考」）；
  回放段时长用**行 ts 邻行差**——thinking 行 dispatch 挂 `_HG.thinkPend=
  {seg,t0}`，下一条带 ts 的行到达时定格「持续了 N 秒」（`_hgTurnDurTxt`
  中文口径；转写无段级终点事实，邻行差是唯一诚实口径；同秒双段降级为空
  不编造）；live endThinking 文案统一中文。pend 清零三点：_histRender 起/
  _hgSseResetLocal/switchTo。
- **「出错了也不要自动展开，只标红」**：'err open'→'err'（回放主链+段内），
  live 错误分支去 add('open')——红色 err 边框+失败徽章+live failmark 标红，
  错误体仍立即渲染进折叠体（点开即见，非懒加载），信息可达性保留。
- **「字体被挡住了」**：oneclick 终端卡直挂 arg 单行省略（nowrap+ellipsis，
  窄面板 flex 收缩降阶不重叠不消失）；live bash 补 title 全文悬浮（对齐回放
  卡 argTitle）；思考体左距加大（16px）+ ul/ol 补 1.4em 缩进（序号压线）。
- **对抗审计**：R1 FAIL(1×P3)——`calc(100%-160px)` 固定预留极窄面板钳 0
  （命令消失）→ 改 `max-width:100%` 弹性降阶 + title 补救入口；R2 终审
  PASS（含属性转义/层叠/快照序列化核验）。
- **验证**：「🧠 思考持续了 2 秒」形态、5 错误行全收起红标（collHasContent
  点开可见）、命令省略号与徽章不重叠；回归全绿。

## 十、v3.2.6 子智能体 ZCode 模式（单行任务卡 + 窗格时间线）

用户定调「子智能体效果全部优化成 ZCODE 模式」（对照截图 = ZCode 运行中会话：
主流内单行任务卡 + 右侧自动打开的子代理会话标签页，子代理自己的会话用主会话
同款完整时间线呈现）。

### 产品模型（ZCode 源码 mining 结论）
- `ToolCallBlocks/renderers/agent.tsx`：Agent/Task 在父对话**只保留单行摘要**
  （BotIcon + 「子智能体」类别词 + 类型名彩色高亮 + 描述；运行中该行由
  animateSummaryContent 流式显示最新子活动），`canToggle=false` 无展开体；
  行尾动作钮 = 在右侧打开；`autoCollapseOnComplete`。
- `SubagentSessionSidePane.tsx`：右侧 tab = 完整 SessionPane（readOnly）——
  子代理会话与主会话**同一渲染器**（回合头/思考/工具时间线）。
- 目录（SubagentDirectorySidePane）与状态面板（ConversationStatusPanel 的
  agent section：运行行 elapsed 计数 + 已结束 N）我们 v3.2 已有对应物。

### 主流：单行任务卡（.h-tool.agentline）
- `_hgAgentRowBuild`（08-tools.js）：`🤖 子智能体 | 类型chip（类型名哈希
  取色，h-ava-0..4 文字色变体）| 描述（单行省略+title全文）| .h-ag-live
  实时活动流（accent 脉冲）| .h-tslots 状态徽章/秒表/完成摘要`。整行点击=
  开窗格（live→_subReopen / 已结束→_subReplay），不再折叠展开。
- 接入点四路：live renderToolUse（agent 分支）/ 回放 renderHistTool（agent
  分支 + `_HG.lastAgRow` 只活一行，紧随的 sub_open 行回绑 hgSubr/类型/描述）
  / task_started 兜底建行（tool_use 丢失）/ task_notification 定格
  （`_hgAgentRowState`，与 renderOneToolResult 幂等互备）。
- 实时活动流 `_subLivePaint` 三钩：_subThink「思考中…」/ _subText「正文 ·
  前60字」/ _subBlkAppendTool「工具label · 摘要」；完成清空。
- **子代理段卡（.h-subblock）视觉退役**：CSS `display:none!important`。段根
  保留 DOM 作机器挂点（认回/轮询兜底扫描/快照恢复/思考回填/续派切段账本），
  该系全部 JS 零改动——主流唯一入口=单行卡，过程细节统一进窗格。

### 窗格：子代理会话时间线（14-subpane.js 重写）
- `_subPaneScaffold`：`.hg-sub-grp = hg-sub-idline(身份行: 头像+类型+模型)
  + h-grp(回合头[工作中 Ns→已工作 X · N 思考 · M 工具] + h-turn-body>h-tl)
  + hg-sub-concl(根区最终结论)`。tab 标题改描述优先（ZCode 用任务短题）。
- 行工厂与主链同类同款：`_subTlThinkRow`（🧠 思考+持续时长，懒渲染走
  _histLazyFill/_histLazyDrop 同出口）、`_subTlTextRow`（md 气泡）、
  `_subTlToolRow`（折叠头+结果进 coll）、`_subTlPlace`（explore 查阅聚组
  + `_subTlExpBreak` 断组定格桶汇总）。
- live：`_subFeed`（SSE think/text/tool_use）+ 轮询镜像 `_subPaneMirror`
  （rp 铺底前缀查重保留）+ `_subBlkAppendTool` 镜像（tuid 查重 + rp 指纹）
  + `_subResult`（tuid 配对→回退最后未定格行→孤立 ↳ 行）；开口思考段
  `_subTlSegFreeze` 活字→「持续了 N 秒」；`_subTlTickStart` 1s 秒表
  （tick 闭包自愈判据 + _subReset/_subDrop/_subTlFinalize/_subEnd 四路清理）。
- replay：`_subReplay` fetch rows → 同厂行全量铺（rp 标记防镜像重投），
  ts 事实分级——总时长=首末行 ts 差、思考时长=邻行 ts 差、缺 ts 落无数字
  「已工作」（不编造）；定稿默认收起体、最后一条正文气泡上移根区。
- 定稿双路幂等（t.done 守卫）：task_notification→`_subClose`→
  `_subTlFinalize`；回合终结 `_hgAgentsSweep`（前台代理）同调；bg 代理
  跨回合续跑时 `_subEnd` 只停秒表，`_subFeed` 恢复 run 即复活。
- 目录：运行行时间位改秒表走字（`_subDirTick` 1s 重绘，失活/清空自停）；
  collab 运行行点击改 `_subReplay` force（段卡已隐，窗格是唯一过程面）。

### 后端（transcript.py）
- subagent rows 行行带 `ts`（think/text/tool/result）——窗格时间线的时长
  事实源。
- **修实测 bug**：现行 CLI 会先落一个 0 字节 Temp tasks `<taskId>.output`
  占位、真转写在 `projects/<主会话id>/subagents/agent-<id>.jsonl`——旧
  「rows is not None 即返回」被占位文件解析出的 [] 短路，回放恒空。改空
  解析继续试下一候选、全空才如实回空表（前端中性文案，不进 noreplay 锁）。

### 交互委托（20-main.js）
- 主流：agentline 整行点击分支置于 .h-tool-head 通配之前（开窗格，无折叠）。
- 窗格体级委托：回合头开合（userToggled 防定稿收走用户正看的体）/ 思考段
  懒渲染 / 查阅组头 / 工具头；旧 hg-sub-think-head/hg-sub-tool-head/
  data-hg-subfull 分支随旧行工厂退役。

### 验证
- 浏览器实测（真实 CLI 派发）：单行卡「🤖 子智能体 general-purpose 侦察
  工作区结构 运行中 1s→✓完成+摘要」；窗格自动开 tab（描述短题+模型角标），
  时间线「已工作 36 秒 · 2 思考 · 2 工具」+ 查阅组 + 思考持续行；回放 fetch
  （含 ts）「已工作 19 秒」+ 结论上移根区 + 体默认收起；目录「正在运行·0/
  已结束·1」行卡；切会话往返单行卡/hgSubr/隐藏段全保持；截图目检协调。
- 回归：node --check 全过 / 冒烟 / state 38 / 架构 0 / undef 符号级零新增 /
  py 测试 60+17+155+42 全过。
- 对抗审计：见下节记录。
- **对抗审计（5 轮全闭环）**：R1 FAIL(1×P2+4×P3)——F1 live 单行卡不回写
  agentId（切会话往返后点击死寂+入口全灭）→ `_hgAgentRowBindAid` 三路回写
  （task_started 即回写不等完成）+ 死点击 banner；F2 回放 !found/空分支头卡
  「工作中 0s」→ 失败分支同定稿；F3 collab force 回放铺底即封顶（续流进已
  收起体、秒表不复活）→ 运行态不定稿（秒表即刻起跑，notification 再定稿）；
  F4 SendMessage 续派/stub 段失去全部入口 → agentsRpl 补 resumedAgentId 条
  目 + collab 无 aid 改 banner；F5 窗格时间线失去 200 行上限 → `_subTlCap`
  （220 行+省略提示条）。R2 FAIL(2×P3)——N1 collab 秒表被 _subEnd 停摆无
  复活链 → collab 未 done 豁免；N2 Bash 只读命令窗格聚组失效（镜像/回放两
  路 input 恒 null）→ `row._rin` 随行 + 回放 hint 伪 input。R3/R4 FAIL(1×P3)
  ——回放伪 input 120 字截断漏检尾部重定向/写动词 → 后端 `_SUBAGENT_CMD_
  WRITE_RE`（前端 _HG_EXP_WRITE_RE 四分支完整复刻，re.I 对齐）按**全量命令**
  落 `w:1`，前端 w 行不合成伪 input（绝不把写命令聚进查阅组）。R5 终审
  PASS（四分支逐字符对照全等、无新引入面）。
- **R6/R7（用户实锤「点了说无 agentId」+「运行中不能点开看」）**：async 代理
  （Task 结果=启动确认文本，agentId 在其中，但 sub_open 注入依赖转写非空）
  历史重建时行未绑 hgSubr → 四层修复：工厂预置 hgSubType/hgSubDesc 锚键 +
  agentsRpl 建档即回绑（不依赖转写）+ 点击三源兜底（agents 档案→行 hgSubr→
  agentsRpl 按 type+desc 查）+ 运行中重开走 force 回放铺底即续流（中途 ✕ 再
  点不再是白板；!found/空 rows 尊重运行态不锁 noreplay，_subReplayRetry 5s
  延迟重拉限 3 次——R7 计数迁移到 tab 档案防 scaffold 重建归零）。浏览器复
  现验证：新进程恢复→点行→「回放 · Explore · 8 条记录」全时间线；运行中关
  窗格再点行→「工作中 11s 实况继续」→完成后全量时间线+结论。R7 终审 PASS。

## 十一、v3.2.7 只读模式退役——上滑懒加载 + DOM 封顶（用户定调）

「只读模式退役！但是懒加载保留：只有翻到上面之后才加载！然后全部保持
现有的 zcode 模式，随便翻阅，但是 dom 不能爆，太早的信息不懒加载要有
这个侧边能力，可以通过这种侧边方式快速定位到会话！」

- **只读模式退役**：_roDeps/_roEnter/_roExit 整体删除，hist-more 提示条不再
  进只读；22-readonly.js（window.HgReadonly）留盘成不可达死码。
- **上滑/点击懒加载（既有机制强化）**：v2.35.2 的滚顶自动扩段保留；提示条
  可扩态改「📖 剩 N 条更早消息——点击加载更早（上滑自动加载）」，点击=
  同款 _histRefresh 大窗口重渲 + anchorH 差回锚——全部内容走现有 ZCode 渲染
  器（回合头/时间线/思考段），翻阅体验与主流一致。
- **DOM 封顶**：HIST_CAP 300→1200（硬顶）；≤1200 行会话可翻到顶（实测
  1169 行→46 组全渲染、提示条消失）；到顶后提示条切封顶 notice
  （hg-hist-cap 纯文本）：「已到浏览上限（已载入最近 N 行，更早内容不载入
  防卡顿）——早期内容请从左侧会话列表打开对应早期会话查看」，不可点。
- **修实测 bug（R8）**：_histBusy 复位原在 requestAnimationFrame——后台标签
  页 rAF 不触发，卡 true 后点击/上滑扩段永久堵死（连点序列实测 1119 卡死
  抓到）；点击与 scroll 两路均改同步复位。
- **验证**：连点推进 1119→742、滚顶 15 轮自动扩到 0、cap=300 覆盖下扩到
  869 出封顶条且点击无动作、readonly 层全程未出现；回归全绿（undef 符号级
  零新增——两条旧误报随死码消失）。
- **对抗审计（R8/R9）**：R8 FAIL(1×P3)——扩段 .then 缺 sid 校验（fetch 在途
  切会话→旧锚定 scrollTop 写进新会话 flow；scroll 分支 v2.24 预存在缺陷被
  点击分支复制）→ 两处 .then 首行加 `sid !== sidAt` 守卫（弃锚定+放行 busy）；
  R9 终审 PASS（含快切回环/busy 堵塞连带面核验）。另修实测 bug：_histBusy
  复位原在 rAF（后台标签不触发→扩段入口永久堵死，连点 1119 卡死实测），
  两路改同步复位。HIST_CAP 注释钉死实测口径（1200 行 9.4k px 无卡顿、末跳
  百毫秒级、上调前需重测）。

## 十二、v3.2.8 一键跳底浮动钮

- 「增加一键跳底功能」：消息流右下浮动圆钮「↓」（输入卡上方），离底
  >350px 浮现、贴底隐藏；点击瞬时直跳 flow 底（长距离 smooth 滚动慢且晕），
  贴底自然触发既有增量收缩（DOM 顺带瘦身）。
- 结构：`.hg-flow` 包一层 `.hg-flowwrap`（flex:1/min-height:0/relative），
  钮是 flow 的**兄弟**——_histRender 的 innerHTML='' 与快照序列化/恢复都
  只动 flow，钮不随渲灭、不入快照；`.hg-flow` 的 flex:1 移入
  `.hg-flowwrap > .hg-flow`（内部子选择器全不受影响，审计 A 全核）。
- 显隐在 scroll 监听顶部刷新（先于 histLive 门，任何渲染态生效）；onclick
  直绑（模板静态元素，tab 重建随 build 重绑）。state_audit 计数改动态（39 名）。
- 审计 R10 一次 PASS（抖动/阈值带/快照隔离/销毁回收全核）。实测：贴底隐藏、
  滚顶浮现、点击直跳+隐藏+收缩、中段再现；回归全绿。

## 十三、v3.2.9 封顶条=早期会话选择器（用户澄清）

用户澄清：封顶态不能只给一句「去左侧会话列表」的提示——**侧边能力必须能
跳转到所有早期会话**。

- 封顶条改为可点：「⬆ 已到浏览上限（已载入最近 N 行，更早内容不载入防
  卡顿）——**点击选择早期会话 ↗**」。
- 点击弹出**会话选择器**（.hg-sess-pop，fixed 挂 body、锚条位置上下自适应
  +视口钳制）：全部会话按活跃排序（数据源 `_HG.sessions` 与侧栏同源），
  行=标题+项目+模型+相对时间，当前会话虚线标记（点它仅收起）；点选
  `switchTo(sid)` 直跳（与侧栏行完全同路径）；再点条=toggle 收起、外点、
  Esc 均收（keydown/mousedown 双 capture listener 挂 document，随统一
  close 摘除；toggle 走 hg-close 事件同一条 close 语义，无幽灵 listener）。
- 审计 R11 FAIL(1×P3：Esc 挂 pop 节点而焦点在条上不可达)→改 document
  capture（顺带修 B 注记的 toggle 幽灵 out）→R12 终审 PASS（TDZ/幂等/
  并存链全核）。实测：封顶弹层（3 会话含当前标记）、行点跳转全切、外点
  收起、toggle；回归全绿。

## 十四、v3.2.10 回合导航轨 + v3.2.11 滚动体验修复（用户四连反馈）

### v3.2.10：废除封顶 + ZCode 同款回合导航轨（用户纠偏十一/十三）
- **封顶废除**：HIST_CAP 置 Infinity——任何会话任何时候可完整翻阅到第一条
  （用户定调「绝对不允许封顶」）；DOM 防爆=回合默认折叠+懒抽屉+渐进加载，
  非封顶。v3.2.9 的封顶条/会话选择器整体退役删除。
- **回合导航轨**（.hg-rail，flowwrap 左缘，ZCode ConversationTurnNavigator 同款）：
  每条用户提问一枚刻度（悬停 title 预览、当前视口回合高亮+轨自滚跟随）；
  点击跳转——已渲染刻度平滑滚到该回合，未渲染刻度先扩窗到该行
  （_histRefresh）再凭 data-turn-hi 章定位。轨数据=histAll 未渲染区 + flow
  已渲染 user 气泡并集；sync 挂六处（_histRender 尾/live renderUser/收缩/
  快照恢复/清场×2）。
- 实测：985 行会话点首刻度直达第一条（histStart 985→0 无封顶）；轨顶层
  函数化（初版误入 builder 闭包→全局调用 ReferenceError，chain_smoke 抓出）。

### v3.2.11：滚动体验四修（用户：「滚动条抽搐」「上滑要下再上」「旧回合未整合」「刻度顶到底有问题」）
1. **原子渲染**（_histRender）：全部行先落**游离缓冲**再一次 replaceChildren 换
   入——旧实现逐行 append 活 DOM，几百行渲染期间滚动条逐帧长高（=抽搐），
   锚定前中间态可被绘制（=上滑手势被打断、要下再上）。游离期对子模块透明
   （addRow/grpEnsure 全走 _hgFlow 引用）；早退路径先归还引用防泄漏。
2. **图片尺寸缓存**（03-ask-md `_hgImgSizeCache` + `_hgImgReserve`）：img 首载
   后记 src→宽高（document 捕获 load），重渲时同图立即按 aspect-ratio 占位
   ——消灭「先 0 高、载完弹开 200+px」把贴底判定/滚动位置弹飞（抽搐另一半
   根源，实测每轮重渲 +247px 突跳）。
3. **收缩防抖**：贴底**滞留 600ms** 才摘头（旧实现冲底瞬间就摘=拇指跳变打断
   手势）；自续期定时器（被内容增长顶离时重试，上界 8 轮——图片装载期的
   贴底漂移不再吞掉收缩）；离开底部即取消。
4. **旧结构快照作废**（12-sessions）：恢复时无 .h-turn-body 的快照（v3.2 前
   DOM）弃用走 transcript 重渲——「有的回合没整合在一起」（思考/工具散着
   无折叠头）的根源；nearTop 60→100 放宽扩段触发。
- 实测：扩段链 935→…→0 逐级原子换入；贴底滞留后收缩（hs 0→915，轨重建
  16 未渲染+3 已渲染，active 跟随）；刻度顶→底→再点未渲染刻度全通。
- 按用户要求本轮免对抗审计（「只有我要求你审计才审计」）。

## 十五、v3.2.12 聊天框净化 + 分页退役（用户四连反馈，免审计轮）

1. **贴图路径文本不裸显**（用户：「这种信息不要出现在我的聊天框里面」）：
   CLI 把粘贴图写成 `[Image: source: 路径]` 文本回显——transcript.py 提取路径
   进 files（前端出图片缩略卡，复用既有 data-img 管线），文本剥除；live 的
   user_echo 同款处理（与乐观渲染形态对齐，echoFast 去重同源）。实测旧噪音
   会话 28 处提取、界面 8 张缩略卡、路径文本零残留。
2. **中断消息不显示**：`[Request interrupted by user( for tool use)]`、
   `Continue from where you left off.`（含自动重启变体）user 行整行丢弃
   （transcript.py `_NOISE_RE` + live user_echo 前置滤除）；assistant
   `No response requested.` 从文本剥除（同轮思考/工具保留——中断前的工作
   不丢）。`This session is being continued...`（自动续命摘要）折叠 renew 线
   （同 /compact 口径）。
3. **图的问题**：即 1 的图片缩略化（占位文本→真实缩略图，点击灯箱）。
4. **分页退役**（用户：「上滑显示历史不要了！只要往上滑就显示历史，DOM 你
   处理，为啥 ZCode 能」）：`_histRender` 恒全量（start=0，一次原子换入），
   扩段/贴底收缩/「剩 N 条」条/cap 全部退役；ZCode 靠虚拟化管 DOM，我们靠
   **回合默认折叠（头+结论行极廉价，979 行会话整流仅 ~3.5k px）+ 代码/图片
   懒增强 + 原子渲染**。旧的部分窗口快照（histStart>0）作废重渲。刻度轨/
   跳底钮保留。
- 实测：重构会话打开即 histStart=0/无剩余条/轨 17 枚全渲染/8 图缩略；
  回归全绿。本轮按用户要求免审计。

## 十六、v3.2.13 贴图回显退役 + 查阅组真整合（用户截图两处标注，免审计轮）

用户裸截图两处红标：①「图 2.png（图片/附件，见上方）」占位卡——「不要给我
渲染出来」；②工具/思考区碎片——「没修复好」。

### A. 贴图回显三路退役
- 数据源实况：每次贴图 CLI 落三条相邻行——base64 image 块（真图，含
  harness_uploads 附件标记）+ attachment 行 + `[Image: source: …]` 纯回显行。
  回显行无信息量，v3.2.12 只把它转缩略，仍渲染占位卡。
- transcript.py：纯回显行（剥标记后无文字、无他附件）整条丢弃；仅当回显与
  真实文字混行时保留（剥标记+路径进 files）。附带防御：marker-only 孪生行
  （无文字无图、files 为上一 user 行子集且上行 images>0）同丢——纯文件附件
  无 base64 孪生，不满足判据不会误伤（nonlocal _last_u 跨代判据）。
- 10-sse.js live echo：同款判据整条不渲染（_HG.echoFast = null 后 return）。
- 04-groups.js renderUser：「*（图片/附件，见上方）*」占位正文退役（v2.20
  文案谢幕）——无文字时正文体整块不渲染，附件 chips 已表达一切。
- 实测：2d835190 会话 1144 行，echo-text 残留 0、孪生残留 0、占位 0。

### B. 查阅组真整合（含根因修复）
- 根因（本修的主体）：v3.2.11 原子渲染把全程画进游离缓冲，grpEnsure 的
  `g.root.isConnected` 快路径在缓冲期恒 false → 每行都走认回重建 wrapper →
  g.exp 逐行丢失 → **每个 explore 工具各开一个单子行查阅组**（用户截图的
  碎片墙正是它）；_tlExpFlush 的 isConnected 早退又让组头永远停在运行态
  活字、组永远开着。
- 修复：_HG.histBuilding 缓冲期旗标（_histRender try/finally 与早退三处
  归位）——grpEnsure 快路径、_tlPlace 组在场判据、_tlExpFlush 定稿守卫
  三处同判豁免。窗格侧渲染进已连接 DOM，不受影响（_subTlPlace 的
  isConnected 是 _subTlCap 删组自愈判据，保留）。
- 整合三件套（对照 ZCode exploreToolCall 组跨思考累积）：
  1. codegraph_explore 入组：_HG_EXP_MCP_RE 白名单（(^|_)codegraph_explore$）
     → explore 判定/搜索桶/「探索 xx」活字（主链+窗格共享这三函数）；
  2. 思考不再断组：startThinking（07）与 _subTlAppendThink（14）撤断组，
     思考行照常按序挂组后，后续查阅回填进组体；断组只留写类工具/正文/
     回合边界（renderUser 兜底冲组——grpFinalize 先行冲，双保险）；
  3. 同目标去重：_hgExpKey(name,input)（R:file/G:pattern/O:pattern/S:query/
     F:url/E:query/C:command），组内重复子行不入 DOM 不计数（主链+窗格）。
- 实测（2d835190 全量重渲）：查阅组 164→84（37 组多子行）、游离 codegraph
  行 0、组头活字 132→0（全定格桶汇总）、未点开组全收、真实重复子行 0、
  回合 53→43（10 个认回竞态分裂组消失）、刻度轨 50 枚完好。
- 回归：node --check×6、chain_smoke 全过、state_audit 41、architecture 0、
  ledger 17/17、route_smoke 42、roles_routing 全过。本轮免审计（用户令）。

## 十七、v3.2.14 贴图并名：一次一图一原件名（用户「不能出现两次」）

用户裸截图实锤 v3.2.13 遗留：单张贴图渲染出**两枚 chip**——「🖼
b535b34a_image.png」（base64 行的应用上传 hash 名附件）+「🖼 1.png」（
[Image: source] 回显行附件）。用户定调：后端自行处理，我要看的时候同一张
图**只出现一次**，且要**原先的名字**。

- transcript.py 并名：纯回显行丢弃前，把上一条 user 行（base64 孪生）里
  的 `*_image.png` 附件逐个改写为回显路径（原名 + CLI Temp 原件）；无
  marker 附件的罕见流回退为直接并入。实测 2d835190：28 个图行全部
  images 数=附件数、hash 名残留 0、echo 残留 0，4 连图（4.png~7.png）同
  样正确并名。
- routes.py /api/harness/file 补 path= 分支：白名单整路径回源——
  _UPLOAD_DIR 任意原件 + %TEMP%/claude/**/images/ 下的图片（父目录名必须
  是 images + 图片扩展名 + realpath 包含校验），name= 旧分支保留（旧快照
  兼容）。test client 实测：Temp 原件 200、上传原件 200、越界 403×2、
  旧 name= 200。
- 03-ask-md.js attChipsHtml：data-img 改传整路径（path=）——并名后附件
  指向 Temp 原件，name= 查上传目录会 404；输入区新上传预览（16-input-fx）
  仍是上传目录内文件，name= 照常。
- 10-sse.js live 并名对偶：纯回显跳过前把乐观渲染行的 _image.png chip
  改写为回显路径（label/title/data-img 三同步）——live 与回放同名同源。
- 回归：chain_smoke 全过、state 41、undef 无新符号、route_smoke 42 健康、
  ledger 17/17。免审计（用户令）。

## 十八、v3.2.15 回合归纳 + 刻度贴底转正（用户两张标注截图，免审计轮）

用户两张截图：①同一回合拆成三个「已工作」头——「为什么没有归纳在一个
会话内？」；②翻到底刻度轨不在底——「我都翻到底了，为啥条显示不是底？」

### ① 回合归纳：renderPeer 撤 grpFinalize
- 实测定位（2d835190 全量重渲 + data-hi 范围映射）：43 个组里所有非 user
  边界全部对齐 peer 行（hi=154/172/271/411/499/507/631/678/695/753/1116/
  1119/1124）——06-relay renderPeer 的 grpFinalize(false) 把 SendMessage
  协作回传当成了回合终点。但 SendMessage 是同一模型回合的中途接力（工具
  调用-结果环，回合没结束），回传本体早已走 v2.49 归一进子代理段，定稿
  主组纯属旧独立气泡时代的残留。
- 修复：撤掉该 grpFinalize（endThinking/closeRun 保留——思考段确实暂停）。
  真回合边界不动：result/下一 user 行/renderUser→grpFinalize 照旧。
- 实测：问题1 回合三个头（34 思考·70 工具 / 3·12 / 1分7秒·2·2）归一为
  「已工作 30 分 56 秒 · 39 思考 · 84 工具」；全会话 43 组 → 30 组 =
  30 个 user 回合，逐回合核验无一多组。

### ② 刻度贴底：_hgRailActive 贴底特判
- 根因：激活判据「el.offsetTop <= scrollTop+80」在末回合正文高于 80px
  时永远够不到最后一枚（末 user 行 offsetTop 9206 vs 贴底锚线 9162——
  绝对贴底也差 44px）。凡末回合 AI 回复超过 80px 的会话必现。
- 修复：贴底（scrollHeight-scrollTop-clientHeight ≤ 4px）直接点亮最后
  一枚。实测：50 枚轨贴底激活 idx=49（末枚），跳底钮照旧正确隐藏。
- 回归：chain_smoke 全过、state 41、undef 无新符号。免审计（用户令）。

## 十九、v3.2.16 复原收敛（用户最后定调：图片在气泡上方+默认占位气泡+可点开预览+历史无链接行）

用户最终裁定（最后警告）：v3.2.13/14 两轮把贴图体验改乱了——「上个版本
至少我图片还能打开」。需求只有一条：**我发图片 → 图片缩略在消息气泡上
方、气泡是最开始的默认占位气泡（*（图片/附件，见上方）*）、图片随时点开
预览；看历史时消息列内不许出现一大条图片链接行**。

- 04-groups renderUser：占位气泡完整复原（v2.20 原表达式原样回归）。
- 03-ask-md attChipsHtml：chip 恒用 name=（上传目录原件）——v3.2.14 的
  path= 依赖新路由，未重启后端时点开全裂（用户实锤）。上传副本恒久存
  在、新旧后端 name= 都 200。
- transcript.py：撤 v3.2.14 的 hash→Temp 原名改写与路径并入——回显标记
  一律剥掉、路径绝不进 files（Temp 路径只会出死链 chip）；剥完空壳整行
  丢弃。图行附件恒为上传副本。
- 10-sse live echo：同款收敛（剥标记+空壳跳过，撤 chip 改写）。
- 07-hist 前端防线：旧后端（未重启进程）仍发的回显行（无文字+附件全是
  CLI Temp images 路径）整条跳过——**不重启也能干净**；组管线边界语义
  （定稿上一组）在跳过分支保留。
- 实测（用户当前运行实例，未重启）：30 条真实 user 消息（20 条回显行消
  失）、链接行 0、chip 在气泡上方+占位气泡、点击 chip 灯箱打开真图加载
  （667px）。回归：smoke 全过/state 41/ledger 17/route 42。

## 二十、v3.2.17 新会话垃圾治理（用户实锤「多出了一大堆的新会话」）

- 根因：tests/test_route_smoke.py 按路由表逐条「空 body POST」——
  /api/harness/connect 空 sid 即真建会话，且测试进程的 Flask 实例与用户
  应用共享 ~/.serialconsole_pro/claude_harness.json——**每跑一轮回归就往
  用户会话列表塞一条空「新会话」**（cwd=expanduser 默认、has_history
  false、无 csid 是其指纹）。历轮回归累积成「一大堆」。
- 修复：冒烟对 /connect 跳过 POST（带状态副作用的入口不打空参），其余
  42 路由照旧。
- 验证：跑一轮冒烟前后 meta 文件 md5 完全一致（不再写用户状态）；当前
  会话表 3 条真实会话、垃圾 0（用户已手清的残留确认无存）。浏览器测试
  标签页已关闭（不再作为用户实例的第二个客户端）。

## 二十一、v3.2.18 跳底钮重做（用户定调「丑，修！」）

- 原形（v3.2.8）：半透明底 + accent 40% 淡描边 + 文字箭头「↓」——对比度
  低、观感单薄、图标与描边两种蓝不一致（用户特写截图实锤）。
- 重做：实底 accent 填充 38px 圆钮 + 2.6 描边 SVG 粗箭头（退役文字字形）
  + 双层投影（外投影 + inset 顶部高光）；悬停上浮 2px + 提亮，按压回缩
  0.92；深浅主题同形（accent 随主题变量）。实测（浅色主题）：实心蓝圆 +
  深色锐利箭头 + 柔和浮起投影，无样式异常；本次开页未新增会话（3 真实
  0 垃圾）。

## 二十二、v3.2.19 执行中默认不展开 + 思考体宽度约束（用户三图实锤）

- 执行过程中默认不展开（用户定调）：①实况思考段不再生而 open（07-hist
  `h-think-seg + open` → 恒收起；头上秒表/「思考中」照跑，点击照常展开；
  回放态本就收起）②查阅组两侧生而收起（08-tools _tlPlace 与 14-subpane
  _subTlPlace 的 `h-tl-grp open` → `h-tl-grp`——运行态活字仍实时上组头，
  对照 ZCode 折叠组 + collapsedChildSummary）。窗格思考行本就收起。
- 思考无宽度限制的根因：`word-break: break-word` 不参与 min-content 宽度
  计算——长路径/长 token 仍把容器顶宽、从灰底块溢出。改
  `overflow-wrap: anywhere`（参与内在尺寸，长 token 在容器内折行）+
  `min-width: 0`，作用于主链思考体/纯文本流式态/内嵌 pre·code 与窗格
  思考体同款四组规则。
- 实测（2d835190 全量回放）：230 思考段/全部查阅组默认 0 展开；抽测 25
  个长思考体展开态横向溢出 0（scrollWidth==clientWidth）；回归
  smoke 全过/state 41。

## 二十三、v3.2.20 执行中顺序可见 + 三处清扫（用户四图实锤，含上轮误读致歉）

上轮「执行过程中默认不展开」我收过了头——用户真实诉求（本轮四图+「上一
轮我就发图了」）：执行中要能看到**时序**，正常应该是 思考→工具→消息→
思考→工具→消息→终结消息 交替。

- **顺序可见（核心）**：中间正文不再堆组根等定稿折回——renderAsst 到达
  即 append 进时间线（落在当前思考段/工具行之后，实时/回放同路）；
  grpFinalize(turnEnd) 把 tl 内最后一条正文提回根区作最终结论（+
  can-rewind 授予），纯正文组同样成立（提回后体空，根区可见）。实测
  2d835190：30 组根区正文全 ≤1（29 带结论+回滚钮）、111 条中间正文全在
  tl，抽样时间线序「TGTTTMGTMWWTWTMTWT」（思考/查阅/正文/工具全交错）。
  v3.2.4 的 _tlAt 锚点折体逻辑保留为旧快照回落。
- 「最近工具」头上的「点击跳转消息流」死标签移除（用户明示：不行就去
  掉）；行级点击/复制不受影响。
- banner 同文去重（util.notifyPop）：栈内在场同文案+同级别不再重复弹，
  仅重置驻留计时——「无 agentId 无法回放」连刷 7~8 条的刷屏根治。实测
  连发 3 次同文仅 1 条在场。
- 回合末「🔍 查阅 · …」残留胶囊：不再挂消息流根（悬在结论/回滚钮后像
  残留），改挂回合体内顶部（展开即见，收起态根区干净）；回放路径本就
  不产（仅 live 投影），根区残留实测 0。
- 回归：smoke 全过/state 41。免审计（用户令）。

## 二十四、v3.2.21 子代理回放根治 + 有来有回（用户四图+「为啥不能回放」）

排查实锤（12ea 会话全链）：后端候选三形态齐备、解析正常、回放接口 196
行正常返回——断点不在链路在**数据缺口**，两个：

- **缺口① 重试覆盖**：同 tool_use_id 先报错后成功的重试，配对逻辑「已有
  result 就跳过」保了先到的错（42 字符无 id），带 agentId 的成功结果被
  丢弃。修：err→ok 允许覆盖（成功清 err）。
- **缺口② 空结果无 id**：部分派发主转写结果为空（len 0/7），id 无从提
  取。修：agentId 兜底反查——subagents/agent-<id>.meta.json 文件名即
  agentId，toolUseId 精确对齐（行补 tid 字段），desc+agentType 兜底；结
  果超长时 id 前置防截断。实测 12ea：7/7 派发全部有 id（原 5/7）。
- **有来有回（用户定调）**：子代理侧 user 行（首次派发提示/SendMessage
  追加）此前不入 rows——窗格只见单向干活流。修：解析器提 user 行（滤
  tool_result 载体与 < 协议噪音），窗格回放渲染右对齐来向气泡（回合边
  界：冻结思考+断查阅组）。实测线程序 U T T R T T T R…——完整对话流。
  重复派发语义一并答清：SendMessage 续派同一智能体（线程连续可见），
  Task 新派 = 新实例（CLI 语义）。
- 回归：smoke 全过/ledger 17/architecture 0/state 41。免审计（用户令）。

## 二十五、v3.2.22 快照恢复重建子代理目录（用户实锤「有的还点不开」）

- 排查（新实例 65252 已带 v3.2.21 后端）：转写 7/7 有 id、回放接口正常、
  SendMessage 结果全带 resumedAgentId——真凶是**切会话往返**：切走时
  agentsRpl 清空，切回走快照恢复路径（innerHTML 直灌，不跑行渲染循环），
  agentsRpl 永不重建 → 子代理目录空壳/条目点不开。复现：12ea 首开 5 条、
  切走切回 0 条。
- 修复：新增 _hgRplRebuild()（从 histAll 直接重建 agentsRpl，Task/Agent +
  SendMessage 续派同款提取/去重/上限；DOM 不动——快照 dataset 已带
  hg-subr 绑定），挂进 12-sessions 快照恢复的两个转写补填分支（新账目
  histLive 路径 + 旧账目直填路径）。
- 实测：切走切回后 5 条全在（全带 id）、逐条点击 5 窗格全开；新后端下
  窗格「有来有回」真实在场——5 窗格合计来向气泡 8、思考 126、工具 168、
  结论 111。回归 smoke 全过/state 41。

## 二十六、v3.2.23 来向气泡宽度塌缩修复（用户实锤「来都被收收缩了」）

- 现象：子代理窗格的来向消息（派发提示/追加消息）被压成右对齐窄条，
  长文挤成 4000px 高细柱、文字截断不可读。
- 根因：`.hg-sub-u` 用 `align-self: flex-end` 右对齐——时间线是 flex
  column，flex-end 触发 shrink-to-fit，CJK 长文的 min-content 宽度极窄
  （~98px），可用宽计算又受瞬时布局影响，整行塌缩。
- 修复：改 `width: fit-content` + `margin-left: auto`（内容取宽 +
  自动左推右对齐，max-width:88% 封顶），气泡字体回 fs-base。实测：
  1026×486 正常几何、右对齐、长文完整换行可读（截图目检通过）。
- 回归：smoke 全过。

## 二十七、v3.2.24 来向消息暴露 + 窗格自适应窗宽（用户纠偏：「像 ZCode
一样直接暴露，不要收进工作区」「自适应窗口，别让我左右拖」）

- ① 暴露：回放 user 行不再进时间线——插到工作区（.h-grp）前面，回合
  收起/展开都恒可见（多条按到达序竖排）；ZCode 同款会话面语义。
- ② 自适应：窗格内容曾整链被 min-content 撑到 1166~1191px（窗格仅
  ~284px，查阅组/长路径是元凶）逼出横向拖动。修：.hg-sub-msgs 链
  min-width:0 + width:100%（阻断 min-content 上传）、工具行/组头/参数/
  输出 overflow-wrap:anywhere（长词容器内折行）、overflow-x:hidden
  （行内戳出硬裁，无横向滚动条）。
- 实测：回合收起态 scrollW=clientW=284（零拖动）、展开态 296px 行内
  戳出被 hidden 裁掉（拖不动）；来向气泡在工作区外暴露、250px 宽完整
  可读；截图目检通过。smoke 全过。

## 二十八、v3.2.25 历史回放看得到改动（用户红字实锤「所有编辑都是这样子，看不到改动？」）

- 先按用户邀请澄清了截图（此前两轮看错图致歉）：红框圈的是 Write/Edit
  工具卡在历史回放里只有「File created/updated successfully」一行，
  实际写入/改动内容不可见。
- 主流程修复（07-hist _histToolBodyHtml）：折叠体输入与 live 同构——
  cfg.get(input) → _toolInputBodyHtml（Edit=old→new 红绿 diff、Write=
  写入内容、Todo/Question 同款），summary/结果行随后。实测 214 张
  Edit/Write 卡抽 12 张全有 diff（截图目检红绿对照清晰）。
- 窗格配套（transcript.py + 14-subpane）：子代理 rows 给 Edit/Write 附
  输入体（old/new/content 各截 3000），窗格回放同画 diff/内容
  （_fillRes 为 append，输入体+结果共存）。注：现有存量子代理全是
  Bash heredoc 写文件（152 Bash/0 Edit），此路对新 CLI 的 Edit 型子代
  理生效。
- 回归：smoke 全过/ledger 17。
