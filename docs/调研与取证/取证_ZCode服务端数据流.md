# ZCode 服务端数据流架构深度取证报告

> 2026-10-20 · v4 归一重构批前取证（Explore 子代理产出，行号实测）
> 代码根：`D:\AI\FrontendHarness\ZCode`。定位纠正：`packages/server` 只是「远程连接/部署」外壳；
> 真正的服务端数据面在 **`apps/zcode-cli/packages/bootstrap/src/zcode-protocol-v4/`（权威投影+发布器）
> + `apps/zcode-cli/packages/core/src/runtime/`（事件账本+落盘）**，`packages/shared/src/zcode-protocol-v4/`
> 放协议纯函数，`packages/services/src/zcode-agent/` 是桌面 Host 的转发层。

## Q1 会话转写如何落盘

**结论**：三层存储，职责分离：
1. **事件日志（seq 唯一权威源）**：`InMemorySessionEventStore`——每条 `SessionEvent.append()` 单调分配 `sequenceNumber`（`apps/zcode-cli/packages/contracts/src/events/in-memory-session-event-store.ts:62-75`）：
   ```ts
   async append(event: SessionEvent): Promise<SessionEvent> {
     const state = this.stateFor(event.sessionId);
     const sequenceNumber =
       event.sequenceNumber > 0 ? event.sequenceNumber : state.latestSequenceNumber + 1;
     // 计数器只增不减：淘汰不能让后续 getLatestSequenceNumber()+1 生成重复 seq。
     state.latestSequenceNumber = Math.max(state.latestSequenceNumber, sequenceNumber);
     const storedEvent = { ...event, sequenceNumber };
     state.events.push(storedEvent);
   ```
   瞬态事件（ModelStreaming 等）按 turn 窗口淘汰，seq 不复用。
2. **可读转写（durable transcript）**：SQLite 单库 `~/.zcode/cli/db/db.sqlite`（`apps/zcode-cli/packages/adapters/src/storage/session-store/paths.ts:6-8`），表为 `message` / `part` / `session_entry` / `session_input`，行粒度 = 消息行 + part 行（文本 part、tool part、reasoning part、timeline part）。写入是**逐事件、随发生即时写**，不是每轮 join：`saveMessage`/`savePart` 都是 upsert（`repositories/messages.ts:40-101,113-182`）。用户消息的入账特别设计成**账本与消息同事务**：`sessionStore.promoteSessionInput({id, message, parts})`（`core/src/runtime/methods/message-persistence.ts:148-154`），注释原文：「账本置 promoted 与 message/parts 持久化走同一事务——杜绝『queue 已消费但 transcript 无 user message』的孤儿窗口」。
3. **写入与发布的顺序**（persist-before-publish 闸门）：`appendEvent`（`core/src/runtime/methods/events.ts:82-110`）：
   ```ts
   // live sink 以前拿到的是 createSessionEvent 默认的 sequenceNumber=0，
   // 而 replay/read 路径拿到的是 eventStore 补号后的事件……
   // 这里只发布已落库事件，让 live、replay、snapshot 的 eventSeq 全部来自同一个 event store。
   const storedEvent = await this.eventStore.append(event);
   await persistDurableSessionEvent.call(this, storedEvent, traceContext);
   await recordToolUsageFromEvent(this, storedEvent, traceContext);
   await this.notifyEventSinks(storedEvent, traceContext);
   ```
   seq/版本号维护：**seq = 事件序（eventStore 分配）**；**revision = 投影结构版本**（行结构变化+特定 A 区键变化 +1，规则封闭于 `bootstrap/src/zcode-protocol-v4/projection-state.ts:190-225` `deltaBumpsRevision`，`row.delta` 流式追加不 bump）；**logEpoch = 每个会话 publisher 出生时随机 ID**（`v4-gateway.ts:554-556` `defaultLogEpoch`），epoch 变即一切 rowId/续传基准作废。冷启动恢复时序号由 transcript 反向合成：`bootstrap/src/zcode-protocol-v4/transcript-hydration.ts:1-11`（「reduce(transcript) ≡ reduce(events)」，把 message 库反合成为 reducer 能吃的 SessionEvent，复用整套归约器）。

## Q2 服务端投影构建

**结论**：投影 = **事件溯源 reducer 的纯函数产物**，`ProductProjection`（`bootstrap/src/zcode-protocol-v4/product-projection.ts:432-521`）。每个会话一个实例，`applyEvent(event)` 归约一条权威事件返回 `ConversationDelta[]`，并用协议同一个 `applyConversationDeltas` 推进自身快照（`product-projection.ts:1077-1080`）——**投影与 delta 流逐字节一致是构造保证**（文件头注释 1-9 行）：
```ts
// ProductProjection —— CLI 权威投影第二 reducer。
// 输入：CLI 事件日志（SessionEvent，权威事实源）；输出：ConversationDelta[]。
// 快照推进复用协议规范 apply（applyConversationDeltas）——投影演进与 delta 流
// 逐字节一致是构造保证，黄金测试再用独立重放交叉验证。
```
**行的统一表达**：`packages/shared/src/zcode-protocol-v4/rows.ts:433-444` 判别联合，9 种行：`turnHeader / userInput / assistantText / reasoning / toolCall / artifact / subagent / hookInvocation / timelineMarker`——消息行、工具行、思考行在同一 schema 里，只是 `kind` 不同。**rowId**：`rows.ts:17-19`「rowId：session 内单调、永不复用、事件日志的确定性纯函数」，由 reducer 内 `nextRowId++` 分配（`product-projection.ts:5633-5645` `rowBase`，同时盖 `createdAt`（CLI 事件时钟）与 `createdAtSeq`）。三条结构性规则写在 `rows.ts:3-5`：**row 自包含（渲染任一行不需看别的行）；结构变化换整行（row.upserted）；文本增长用 append（row.delta）；turn 是 row 上的标签不是容器**。行的稳定身份另有 `entityId`（持久实体身份，命令寻址用它，rowId 只是本次物化）。投影与 transcript 的关系：投影不读 transcript 运行（live 全靠事件流）；冷恢复才从 transcript 合成事件重放（Q1 第 3 点）。快照 A 区（控制/队列/usage/goal 等）+ B 区（rows 尾窗）见 `snapshot.ts:471-511`。

## Q3 订阅推送机制

**结论**：**事件驱动的长连接推送**（非轮询、非前端拉）。物理载体是 JSON-RPC 通知（stdio NDJSON / ws），方法表在 `packages/shared/src/zcode-protocol-v4/transport.ts:332-384`（`v4/conversation/subscribe|resync|unsubscribe`、`v4/command`）+ `:407-415`（下行通知 `v4/conversation/frame`）。变化检测**纯内存事件**：core `notifyEventSinks` → `server-operations.ts:3082` `context.v4Gateway?.ingest(sessionId, event)` → 投影推进 → 订阅者 buffer → 按 `flushWindowMs` 定时打帧（continuous 30ms / replayable 150ms，`core.ts:34-59` DELIVERY_PROFILES；定时器在 `v4-gateway.ts:3343-3370` scheduleFlush，`timer.unref()` 不挂进程）。**没有文件 watcher**——文件库只是恢复源。

**先发什么后发什么**：subscribe RPC 只回 ACK（`transport.ts:440-447`「公共 response 严格只含 ACK。initial snapshot/resume 由 server 的 request-scoped post-response outbox 在 response line 之后作为 owned notification 发出」）。服务端裁决在 `conversation-topic-publisher.ts:834-883`：
```ts
const resumable =
  base !== undefined &&
  base.logEpoch === this.logEpoch &&
  base.seq >= this.floorSeq &&      // 保留窗（默认 2000 条事件）内
  base.seq <= this.currentSeq;
if (!resumable) {
  // … payload: { kind: "snapshot", snapshot: this.getWireSnapshotForSubscription(subscription) }
// resume：保留窗内 (base.seq, current] 重放，与在线续流同一条 filter→编码→coalesce 管线。
const replay = coalesceConversationDeltas(
  this.encodeDeltasForSubscription(
    this.log.flatMap((entry) => (entry.seq > base.seq ? entry.deltas : [])), …));
```
首帧 snapshot 固定 `fromSeq: 0`（transport.ts:167「区间记账 (fromSeq, toSeq]；snapshot 帧 fromSeq 固定为 0」），且**服务端单方裁决整窗替换**：wire snapshot 只带尾部 60 行（`publisher getWireSnapshotForProfile :338-358` + `PROTOCOL_V4_LIMITS.snapshotTailWindowRows: 60`），更早历史走 `v4/conversation/rowsRange` 游标分页。**delta 结构（四操作封闭集合）**：`delta.ts:104-118`：
```ts
z.object({ op: z.literal("row.appended"), row: conversationRowSchema }),
z.object({ op: z.literal("row.upserted"), row: conversationRowSchema }),
z.object({ op: z.literal("row.removed"), fromRowId: z.number() }),
z.object({ op: z.literal("row.delta"), rowId: z.number(),
           path: streamablePathSchema, append: z.string() }),
z.object({ op: z.literal("state.updated"), patch: statePatchSchema }),
```
文件头（delta.ts:2-9）明说设计意图：「没有 row.inserted（中间插入）、没有 row.moved、没有字段级 JSON patch——凡此模型表达不了的结构变化，服务端一律发 snapshot resync，刻意压缩客户端错误面」。帧扇出带 per-subscriber filter+coalesce+字节/条数双限额 buffer，溢出即标记 resyncRequired 转发 snapshot（publisher `ingest :565-623`，`appendConversationSubscriberBuffer :223-247`）。

## Q4 「用户输入无本地先行」

**结论**：用户消息行**只来自服务端投影回推**；前端唯一的本地态是 `optimisticCommands` overlay——一个 `{commandId, type, issuedAt}` 的「命令已上行、服务端尚未在投影中确认」登记项（`packages/ui/src/v4/conversationProjectionStore.ts:102-107`），**不含任何消息文本、不渲染成消息行**（文件头 1-7 行：「除 optimistic overlay（pending 命令展示）外，本 store 不产生任何 conversation 事实」）。

**完整链路**（回推延迟 = 命令 RPC 往返 + TurnStarted 事件落库 + ≤1 个 flushWindow）：
1. 前端发 `v4/command`（sendText）并 `markCommandPending`（store:1292-1297）。
2. Host 转发（`services/src/zcode-agent/zcodeAgentService.ts:5902+`）→ CLI 命令层：`CommandInbox` FIFO admission（`bootstrap/.../command-inbox.ts:58-70`，串行分配 `admissionSeq`）→ `startPromptTurn`（`commands/prompt-turn.ts:113-146`）→ core `sendInput` → turn 执行体先 append **TurnStarted 事件**（携带 `input: displayInput` 全文 + `intent.sourceCommandId`，`core/src/runtime/methods/turn.ts:321-353`）→ appendEvent 内 eventStore 编号+持久化后 notify sinks（events.ts:104-110）→ gateway.ingest → ProductProjection `onTurnStarted` 产出 `row.appended(turnHeader)` + `row.appended(userInput origin=realUser)`（`product-projection.ts:2105-2118, 2120-2156`；行构造 `projection-rows.ts:78-112`，text 直接取 `payload.input`）→ publisher buffer → ≤flushWindowMs(30ms) 打成 deltas 帧 → host relay（`zcodeAgentService.ts:2240-2289` 按 topic 分流 `v4/conversation/frame` 通知）→ renderer store `handleFrame/applyFrame`（conversationProjectionStore.ts:618-771）→ React 渲染。消息正文落 SQLite（persistUserPrompt，turn.ts:541-555）与 queue 账本 promotion 同事务。
3. **对账而非乐观插入**：`reconcileOptimistic`（store:1354-1377）只在权威投影里出现同 `sourceCommandId` 的 `queue.items` 或 `userInput` row（origin=realUser）时撤掉 overlay；若 ACK 后 2s 投影仍静默，`expectAcceptedInputProjection`（store:1307-1334，`ACCEPTED_INPUT_PROJECTION_GRACE_MS = 2_000` 于 :47）触发 same-sub recovery——注释原文：「这里不伪造消息，只在有限窗口后复用既有 same-sub recovery」。

## Q5 resync 机制

**结论**：触发条件三类，**不是一律重发 snapshot——先尝试同订阅续传，续不动才 snapshot**：
1. **seq 断档（客户端检出的区间失配）**：store `applyFrame`（conversationProjectionStore.ts:711-732）：
   ```ts
   if (current && frame.toSeq <= current.seq) { …静默丢弃迟到/重复帧… }
   if (!current || frame.fromSeq !== current.seq) {
     // 规则 2：断档不猜。状态本身仍是 seq=current.seq 时刻的一致投影（这帧没碰它），
     // 所以 base 仍合法——重订阅让服务端裁决续传或全量；若断档发生在 subscribe 的
     // resume 续传帧上（服务端已裁决过一次仍不衔接），丢 base 强制 snapshot 防循环。
     … this.connect({ forceSnapshot: true }) / this.requestRecovery(…)
   ```
2. **epoch 失配 / base 越过保留窗（服务端检出）**：publisher `subscribeReserved :834-839`——`base.logEpoch !== this.logEpoch` 或 `base.seq < floorSeq`（保留窗 2000 条被逐出）→ 回 snapshot。rehydrate（投影重建）也强制全部订阅 resync（publisher `rehydrate :680-688`，`resyncRequired = true`）。
3. **订阅者 buffer 溢出（背压）**：publisher `ingest :614-618` 溢出 → `resyncRequired = true`，下次 `reserveFlush :922-938` 直接发 snapshot 帧重对齐（「两级背压」，`resync :1093-1101`）。

**前后端各做什么**：前端调 `v4/conversation/resync`（`conversationResyncParamsSchema` transport.ts:469-481，带自己确认的 `base{logEpoch, seq}` + `forceSnapshot`，**不能拿服务端 sentSeq 猜**）；服务端 `resyncReserved`（publisher:967-1043）：可续传则从保留窗回放 `(base.seq, current]` deltas（ACK mode=resume），否则发 `fromSeq:0` 的 snapshot 帧（ACK mode=snapshot）。内容确定性解析失败（wire fault）走 `SUBSCRIPTION_CONTENT_REJECTED`（`wire-fault.ts:22-42`），恢复阶梯同样是 same-sub resync → 升级。客户端 apply 侧「snapshot 整体替换，绝不 merge」（store:673-709 规则 1）。

## Q6 工具调用/MCP 工具行

**结论**：工具行是 `toolCall` row（`rows.ts:203-231`），状态机字段 `status: inputStreaming → pendingApproval → running → success/error/cancelled`（:210）。服务端 reducer 按事件迁移：
- 出生：`ToolCallScheduled` → `row.appended` status=inputStreaming（`product-projection.ts:3072-3128`；流式输入经 `row.delta path:"inputText"` 追加，replayable profile 会被过滤，所以定稿 upsert 必须带完整 inputText——:3093-3095 注释）。
- 运行中：`ToolCallStarted` → `projectToolActivity` upsert status=running + `startedAt` + 有界 `outputPreview`（:3131-3142；progress 事件 :3148-3184「只在 running 时写：终态之后迟到的进度通知不能把 success/error 行重新点亮」）。
- 终态：`ToolCallResult` → `row.upserted`（:3204-3219）：`status: success|error`、`progress: undefined`（终态清除）、`output: buildToolOutput(...)`、`endedAt: this.ms(event)`；失败带 `error:{code,message}`。工具输出超限截断 head+tail 各 32KB 并带 `truncated.ref`（`projection-rows.ts:171-190`）。`ToolCallError` 取消→cancelled（:3278-3299）。**MCP 工具行**：`display.kind === "mcp_tool"` 携带 `serverName`（`toolDisplay.ts:123-124,257-258`）作为行内装饰载荷，解析失败只丢卡片载荷不拒整行（rows.ts:215-217）。
- **前端徽标数据源**：全部在行内。工具耗时 = `startedAt/endedAt`；轮级「已工作」= turnHeader 的 `activeMs`（TurnComplete 时由 CLI 事件聚合写入，`upsertTurnHeader :5438-5470`，controlOnly 轮刻意不带 0 工时 :2264-2270），高频道次拆分 `modelDurationMs/toolDurationMs/otherDurationMs` 由 CLI 侧 `highspeedModelDurationByTurnId` + 工具区间并集计算（:5497-5524）；UI 侧派生见 `packages/ui/src/v4/SessionPane.tsx:1402`（`header.activeMs ?? (header.endedAt - header.startedAt)`）——**UI 不从输入文本或 duration 反推执行语义（rows.ts:79「执行语义由 CLI 投影裁决；UI 不得根据输入文本或 duration 反推」）**。

## Q7 逻辑时钟/排序

**结论**：**每个 session 一条单调 seq 流，所有来源先入 eventStore 编号，再按序消费**：
- 唯一编号源：`InMemorySessionEventStore.append`（Q1）。「live、replay、snapshot 的 eventSeq 全部来自同一个 event store」（events.ts:87-89）。
- **乱序重排（gap buffer）**：事件先各自 await 持久化再 notify，N+1 可能先于 N 到达投影——gateway `normalizeRuntimeEventSequence`（`v4-gateway.ts:3205-3269`）按 raw seq 暂存 `pendingByRawSeq`，**只连续 drain**（`sourceEventSeq+1` 缺口不越过），保住 queue/stream 总序；`SessionResumed` 是 epoch 边界，清边界前 pending（:3222-3233）；失败/取消的事件**仍消费 raw 序号**以解除后续阻塞但不成为 canonical fact（:3258-3263）。冷合成事件重编号为 1..N 时用 `offset = lastTransportSeq - sourceEventSeq` 建立 N-C 偏移（:3200-3204）。
- **多来源隔离而非全局排序**：主会话/系统事件走本 session 流；**子代理是独立 session、独立 topic**——child 事件按自己的 sessionId 路由到独立 publisher（`server-operations.ts:3054-3065` → `v4-gateway.ingestDetachedLiveSession :1057-1083`），父会话时间线只收一条 `subagent` row（`rows.ts:264-279`，`childSessionId` 存在 → UI 下钻订阅 child topic，**不内嵌 child rows**）；child 镜像到父 runtime 的 tool 事件被显式排除出父投影（`product-projection.ts:5604-5610` `isMirroredSubagentToolEvent`：「完整工具历史只应由 child topic 物化」）。轮内归属由 `productTurnIdByRuntimeTurnId` 映射裁决（queue drain 切轮，:480-484），行归属 `turnIdOf` 归入最新 productTurn（:5647-5651）——**客户端零归属逻辑**。
- 前缀一致性由「同一 reducer + 同一 apply 纯函数」保证：`packages/shared/src/zcode-protocol-v4/apply.ts:1-8`（「coalesce 的『语义保持』就以本函数为裁判——applyAll(s, coalesce(ds)) 必须与 applyAll(s, ds) 逐字节一致（黄金测试）。客户端 store 的 apply 逻辑是本函数的宿主化改写，不得引入额外分支」）。

## 与 Python + 原生 JS 环境的移植对位建议

1. **照抄「一条事实流水线」**：Python 后端对位 `eventStore.append → durable persist → notify sinks` 三步闸门（events.ts:104-110）。seq 权威源必须唯一（一个 SQLite `events` 表的 AUTOINCREMENT 或内存计数器+落库），所有投影、重放、快照水位共用它——这是「账本唯一」的落点。
2. **协议纯函数双端共享**：ZCode 把 rows/delta/snapshot/apply/coalesce 全放 `packages/shared`（TS 双端 import）。Python+JS 做不到共享代码，就把 `apply` 的语义做成**黄金测试夹具共享**：一份 JSON 测试用例集（事件序列→期望 snapshot），Python 端与 JS 端各自实现必须同时跑绿——这是「投影+apply 纯函数共用」的可执行替身。
3. **行模型四操作 + 「表达不了就 resync」**：直接采纳封闭操作集（append/upsert/removeSuffix-fromRowId/delta-append）与「row 自包含、结构变化换整行、流式只 append」三条规则；客户端永远不需要结构猜测代码——迁移/重排/字段级 patch 一律触发服务端 snapshot。删除 op 用 `removeSuffix(fromRowId)`（编辑/重试分支）而非任意删除。
4. **订阅机制**：单条长连接（SSE+POST 命令通道），subscribe 只回 ACK、initial 帧随后发；帧信封带 `(topic, subscriptionId, fromSeq, toSeq, sentAt)` 区间记账；服务端每订阅者一个 coalesce buffer（30ms flush 窗 + 条数/字节双上限，溢出降级 snapshot）。
5. **resync 对位**：客户端只持「断档不猜」两条规则（fromSeq!==local.seq → 携 base 重订阅；resume 续传帧再断档 → 丢 base 强制 snapshot）。服务端保留窗（如 2000 事件）+ logEpoch（每次后端进程/会话实例重建生成新 ID）。
6. **用户输入红线落地**：前端发消息后只登记 `{commandId, issuedAt}` overlay（最多画一个发送中指示），文本永不本地成行；后端在 user 消息落库事务提交后发 TurnStarted 等价事件，投影产出 userInput 行回推；ACK 后投影静默 2s 触发 recovery。这套 overlay/reconcile/watchdog 逻辑（conversationProjectionStore.ts:1291-1385）可直接翻译。
7. **工具行**：status 封闭枚举 + startedAt/endedAt/progress/output(截断+ref) 全在行内，终态清除 progress；耗时由后端聚合（activeMs）下发，前端不做时钟推算。

## 关键文件索引

- 协议：`D:\AI\FrontendHarness\ZCode\packages\shared\src\zcode-protocol-v4\{rows,delta,snapshot,apply,coalesce,transport,core,wire-fault,toolDisplay}.ts`
- 服务端投影/发布：`D:\AI\FrontendHarness\ZCode\apps\zcode-cli\packages\bootstrap\src\zcode-protocol-v4\{product-projection,conversation-topic-publisher,v4-gateway,transcript-hydration,projection-rows,projection-state}.ts` 与 `commands\{command-inbox,input-admission,prompt-turn}.ts`
- 账本/落盘：`apps\zcode-cli\packages\core\src\runtime\methods\{events,message-persistence,turn}.ts`、`contracts\src\events\in-memory-session-event-store.ts`、`adapters\src\storage\session-store\{paths.ts,repositories\messages.ts}`
- Host 转发：`packages\services\src\zcode-agent\zcodeAgentService.ts`
- 客户端：`packages\ui\src\v4\conversationProjectionStore.ts`、`agentConversationTransport.ts`
