# ZCode 子代理（subagent/task agent）机制深度取证报告

> 2026-10-20 · v4 归一重构批前取证（Explore 子代理产出，行号实测）
> 代码根：`D:\AI\FrontendHarness\ZCode`。运行时引擎实际在 `apps/zcode-cli/packages/{core,bootstrap,contracts}`（CLI 进程），`packages/{services,ui,client,server}` 是桌面 Host 与 Renderer。路径缩写：
> `CORE = apps/zcode-cli/packages/core/src`，`BOOT = apps/zcode-cli/packages/bootstrap/src`，`SHARED = packages/shared/src`，`UI = packages/ui/src`，`SVC = packages/services/src`。

## 问 1：子代理会话/转写与主会话的数据层隔离

**结论：子代理 = 同一 sessionStore/eventStore 里的独立 SessionId（`subagent_<agentId>`，taskType=`subagent_child`），事件按 `event.sessionId` 分库；父会话事件日志只落 3 个生命周期事件（SubagentSpawned/Message/Stopped），子代理正文绝不写父转写；工具事件仅在内存中"镜像"转发给外部 sink（带 `source:"subagent"` 改写 ID），不落父事件日志、且被 v4 投影显式过滤。**

1) 独立会话 ID + 独立输出目录（每次 spawn 新建）：
- `CORE\subagent\runner.ts:803-816`
  ```ts
  function createSubagentLifecycle(...): SubagentLifecycle {
    const agentId = options.createAgentId?.() ?? `agent_${crypto.randomUUID()}`;
    const childSessionId = createSessionId(`subagent_${agentId}`);
    ...
    const agentOutputDir = join(
      options.outputRootDir ?? join(tmpdir(), "zcode-agents"),
      request.sessionId,   // 按父会话分目录
      agentId,             // 每个 agent 一目录：metadata.json/output.txt/task.output
    );
  ```

2) 子代理是完整 `AgentRuntime`，用 childSessionId 做事件持久化，与父共享同一 store 实例（隔离靠 sessionId 键，不靠不同数据库）：
- `CORE\runtime\methods\subagent.ts:254-318`
  ```ts
  const childRuntime = new AgentRuntime(
    request.sessionId,            // = lifecycle.childSessionId
    {
      ...
      parentSessionId: this.sessionId,
      taskType: "subagent_child",
      ...
    },
    {
      ...
      eventStore: this.eventStore,        // 同一 store，事件按 child sessionId 落库
      sessionStore: deps.sessionStore,
  ```

3) persist-before-spawn：`SubagentSpawned` 发布前，child session 必须已持久化（并发派生时目录查询不会读到"少一个 child"）：
- `CORE\runtime\methods\subagent.ts:422-429`
  ```ts
  // 父会话过去先发布 SubagentSpawned，child 的首轮 executeTurn 才落库。
  // 并发派生时目录查询会在两者之间读到少一个 child。这里把持久化提升为发布前闸门。
  await childRuntime.ensureSessionPersistedForExternalActivity(request.prompt, {...});
  ...
  await notifySessionReady();   // → runner 才 emit SubagentSpawned
  ```

4) 子事件的路由与镜像（嵌套帧在父侧的标记方式）：
- `CORE\runtime\methods\subagent.ts:356-386`
  ```ts
  eventSink: {
    onSessionEvent: async (event) => {
      request.reportActivity?.();
      // child runtime 的事件已经按 childSessionId 落库，但旧链路只把
      // 少量工具事件镜像给 parent sink，导致 UI 订阅 child topic 后只能拿到打开时
      // 的 hydration，后续流式内容不会更新。raw child event 只通知父 runtime 的
      // 外部 sinks，不再次 append，因此不会重复持久化；bootstrap 再按 event.sessionId
      // 把它路由到 child publisher。
      await this.notifyEventSinks(event, { ...request.traceContext, sessionId: request.sessionId });
      const mirroredEvent = mirrorSubagentToolEvent(event, {...});
      if (!mirroredEvent) return;
      // parent mirror 保留原语义：父会话只看到 subagent 摘要/工具活动，raw child
      // 正文不会污染父 timeline。
      await this.notifyEventSinks(mirroredEvent, { ...request.traceContext, sessionId: this.sessionId });
  ```
- 镜像改写规则：`CORE\subagent\tool-event-mirror.ts:16-17, 64-83, 164-166` — toolCallId 重写为 `tool_subagent_<agentId>_<childToolCallId>`，payload 加 `agentId/agentType/childSessionId/childToolCallId/parentToolCallId/description/source:"subagent"`（background 时加 `background:true`）。镜像只走 `notifyEventSinks`（不 `appendEvent`），所以**不进父事件日志持久层**；父事件日志里真正的"嵌套标记"是 3 个生命周期事件（`SubagentSpawned/Message/Stopped`，经 `emitParentEvent → this.appendEvent` 落库，见 `CORE\runtime\methods\subagent.ts:81-84`、`CORE\runtime\methods\events.ts:82-110`）。

5) Host 侧按事件自己的 sessionId 路由（子会话有独立投影 topic）：
- `BOOT\zcode-protocol\server-operations.ts:3054-3065`
  ```ts
  if (String(event.sessionId) !== record.app.sessionId) {
    // subagent runtime 复用父 runtime 的外部 event sink，但 raw child event
    // 仍属于 child session。无条件用 parent record id ingest 会让 child topic 打开后
    // 不再更新，同时还可能错误 bump 父任务活动时间。这里必须先按事件自己的 sessionId
    // 路由并返回；parent mirror event 本身使用 parent sessionId，继续走下方既有链路。
    context.v4Gateway?.ingestDetachedLiveSession(String(event.sessionId), event, record.app.sessionId);
    return;
  }
  ```

6) 主任务索引隔离：`subagent_child` 永不写入主任务列表索引（`SVC\zcode-agent\zcodeTaskServiceAdapter.ts:1508-1510`：`if (snapshot.session.sessionKind === "subagent_child") return meta;`）；历史污染由 `SVC\zcode-agent\repairSubagentTaskIndex.ts:30-44` 只按权威身份清理索引、不删 Agent 转录。

## 问 2：主会话 UI 中子代理的形态与数据来源

**结论：主窗口里子代理 = 普通工具卡（Agent/Task toolCall 行）+ 一条隐藏配对的 `subagent` 行；subagent 行本身无正文，只有 status/summaryText/childSessionId。子代理的工具调用在 v4 主时间线被完全过滤（连折叠形态都没有）；唯一例外是权限类交互事件必须镜像到父会话（确认窗只从父会话投影生成）。**

1) `subagent` 行 schema（无内容字段；`childSessionId` 是下钻订阅句柄）：
- `SHARED\zcode-protocol-v4\rows.ts:263-279`
  ```ts
  // subagent。前提：subagent 镜像事件必须进事件日志。
  export const subagentRowSchema = z.object({
    ...rowBaseFields,
    kind: z.literal("subagent"),
    // 触发该子智能体的 Agent/Task 工具调用；并发 spawn 顺序不可作为关联依据。
    parentToolCallId: z.string().optional(),
    subagentType: z.string(),
    status: z.enum(["running", "success", "failed", "cancelled"]),
    summaryText: z.string(),
    // 存在 → UI 可下钻订阅 conversation/<childSessionId>（不内嵌 child rows）。
    childSessionId: z.string().optional(),
  ```

2) 子代理行由 reducer 从 Subagent* 生命周期事件物化（spawn 建行、stopped 收口）：
- `BOOT\zcode-protocol-v4\product-projection.ts:4373-4437`（onSubagentSpawned：`row.appended`，status="running"，summaryText=description/prompt）与 `4496-4541`（onSubagentStopped：按 `mapSubagentStatus`（5731-5742：completed/success→success；cancelled/stopped→cancelled；其余→failed）upsert 终态行，`endedAt`）。

3) 配对：Agent 工具行 ↔ subagent 行按 `parentToolCallId` 精确绑定（并发安全的修复注释）：
- `UI\v4\conversationAssistantWorkItems.ts:202-237`
  ```ts
  /**
   * Agent 工具行 ↔ subagent 行必须按 parentToolCallId 精确配对。
   * 同一轮并发 Agent 工具的 tool call 行按模型输出顺序出现，但 SubagentSpawned
   * 事件按异步调度顺序到达；旧 FIFO 会把一个 Agent 的标题与另一个 childSessionId 拼在一起。
   */
  ...
  const host = agentToolByTurnAndCallId.get(`${row.turnId}\0${row.parentToolCallId}`);
  ```
  配对后 subagent 行不再单独渲染（同文件 316-333），改为产出 `{kind:"agentToolCall", row, subagentRow}`；未配对的裸行只是异常兜底一行字（`UI\v4\ConversationRowView.tsx:2302-2316`：`{row.subagentType} · {row.status} — {row.summaryText}`）。

4) 主时间线过滤子代理工具活动（红线 1 的投影层保证）：
- `BOOT\zcode-protocol-v4\product-projection.ts:5604-5610`
  ```ts
  private isMirroredSubagentToolEvent(event: SessionEvent): boolean {
    const payload = event.payload as unknown as Record<string, unknown>;
    // Bug 原因：child tool lifecycle 会镜像到父 runtime，但它不是父 session 的工具事实。
    // V4 过去把 mirror 当普通 ToolCallRow，导致 main timeline 展示 child 的 Read/Bash，
    // 并让 replayable snapshot 同样带上脏 row。完整工具历史只应由 child topic 物化。
    return payload.source === "subagent";
  }
  ```
  所有工具事件 reducer 入口第一行都是 `if (this.isMirroredSubagentToolEvent(event) || !this.isRunning()) return [];`（3073/3132/3149/3187/3279）。

5) Agent 卡片形态：单行摘要 + 不可展开（产品边界注释）：
- `UI\ToolCallBlocks\renderers\agent.tsx:366-377`
  ```tsx
  <ToolLayout
    ...
    canToggle={false}
    forceOpen={false}
    summaryAction={summaryAction}
    // 产品边界：Agent/Task 在父对话中只保留单行摘要；完整 child timeline 统一从
    // 右侧 tab / 手机抽屉查看，因此这里既不自动展开，也不提供手动展开入口。
    kindLabel={fallbackLabel}
  ```
  `summaryAction` 是"在右侧打开"按钮（`UI\v4\ConversationAgentToolCallRow.tsx:63-72`，点击 `openSubagentSessionFromSummary` 用 `childSessionId` 打开侧 pane）。

6) 例外：权限交互必须镜像（否则子代理权限卡死在子会话）：
- `CORE\subagent\tool-event-mirror.ts:108-131`
  ```ts
  // 修复原因：V4 只从父 task 的实时投影生成阻塞交互；仅转发 broker request 会让
  // 子 agent 的 permission / AskUserQuestion 停留在子 session，父界面无法响应。
  const mirroredPayload = { ...payload, toolCallId, ..., childSessionId: context.childSessionId, ...
    ...(event.type === SessionEventType.PermissionRequested
      ? { origin: buildSubagentInteractionOrigin(context, event.turnId) } : {}) };
  ```

## 问 3：子代理专属 pane 的订阅与实时刷新

**结论：与主会话完全同一套订阅管线。子代理 pane = `SessionDataLayer.acquire(childSessionId)` → topic `v4/conversation/<childSessionId>` → 同一 `ConversationProjectionStore`。实时刷新 = CLI 侧把 raw child event 经 `ingestDetachedLiveSession` 喂进 child 自己的 publisher → 按 delivery profile（continuous 30ms flush）打 delta 帧 → renderer 按 topic 扇入 apply。**

1) 内嵌下钻（消息流里的轻量输出区）——挂载即订阅、卸载即释放：
- `UI\v4\SubagentDrilldown.tsx:37-49`
  ```tsx
  export const SubagentDrilldown = memo(function SubagentDrilldown({ childSessionId, context }) {
    const { layer } = useV4Conversation();
    const [lease, setLease] = useState<SessionLease | null>(null);
    useEffect(() => {
      const nextLease = layer.acquire(childSessionId);
      setLease(nextLease);
      return () => nextLease.release();
    }, [layer, childSessionId]);
    const state = useConversationProjection(lease);
  ```
  （只显示最近 20 条 assistantText 行，嵌套抑制下钻：52-55 `inSubagentDrilldown: true`。）

2) 右侧全量 pane：`SessionPane` 直接以 childSessionId 打开（只读）：
- `UI\app-shell\SubagentSessionSidePane.tsx:41-62`
  ```tsx
  <V4PaneConversationProvider scope={scope}>
    <SessionPane paneId={tab.id} sessionId={tab.childSessionId}
      openTrigger="subagent" rootSessionId={tab.rootSessionId} readOnly ... />
  </V4PaneConversationProvider>
  ```

3) 同一订阅管线（引用计数租约，首引用触发 subscribe）：
- `UI\v4\sessionDataLayer.ts:62-98`
  ```ts
  // 连接级单监听：按 topic 扇入到各 store（pane 间共享的正是这一条连接）。
  this.offFrame = this.transport.onFrame((frame, context) => {
    this.entries.get(frame.topic)?.store.handleFrame(frame, context);
  });
  ...
  const topic = conversationTopic(sessionId);   // "v4/conversation/<sessionId>"
  ...
  const store = new ConversationProjectionStore(topic, this.transport, this.rowPool);
  void store.connect({ rendererPrepareStartedAt: startedAt });
  ```

4) CLI 侧：运行中的 child 没有独立 bootstrap record，但 raw child events 会先建立 publisher（红线 2 的服务端保证）：
- `BOOT\zcode-protocol-v4\v4-gateway.ts:1054-1083`
  ```ts
  /**
   * subagent child 使用父 record 的外部 sink，但保留独立 session topic。显式登记这类
   * detached live session，避免把任意偶然存在的 cold publisher 都误判为运行中 child。
   */
  ingestDetachedLiveSession(sessionId, event, parentSessionId?) {
    ...
    this.detachedLiveSessions.add(sessionId);
    if (parentSessionId && parentSessionId !== sessionId) { this.detachedChildParent.set(...); ... }
    if (event.type === SessionEventType.TurnComplete || TurnError) this.detachedTerminalAt.set(sessionId, Date.now());
    else if (event.type === SessionEventType.TurnStarted) this.detachedTerminalAt.delete(sessionId);
    this.ingest(sessionId, event);
  }
  ```
  订阅判定：`v4-gateway.ts:3314-3321` `hasLiveConversation = host.sessionExists(id) || detachedLiveSessions.has(id)`。

5) 帧节奏（delta 推送而非轮询）：
- `SHARED\zcode-protocol-v4\core.ts:34-45`：`DELIVERY_PROFILES.continuous = { flushWindowMs: 30, streamPaths: { text: true, inputText: true, "output.text": true, summaryText: true } }`（replayable 150ms）。
- Renderer apply：`UI\v4\conversationProjectionStore.ts:711-737` —— `fromSeq` 衔接才 apply deltas；断档不猜，自动重订阅让服务端裁决 resume/snapshot（718-732），保证实时流不丢不乱。

## 问 4：完成时结论回传与渲染、竞态处理

**结论：前台结论 = 子代理最终消息作为 Agent 工具的 tool result 回到父会话（父事件日志 ToolCallResult），主窗口 Agent 卡展开区渲染 toolCall.content（"Agent output"）；后台结论 = 通知文本同步写入父 runtime 命令队列（变成 origin=backgroundResult、backgroundSource=subagent 的 userInput 行）+ SubagentStopped 终态事件。渲染正确性由 5 层机制保证：同一事务物化 subagent 行与运行态、persist-before-spawn、终态 snapshot 优先合并、后台启动 ACK 不算 completed、child publisher 终态后 120s 宽限 + 冷恢复兜底。**

1) 前台：子代理结束 → 写 artifacts → registry 终态 → emit SubagentStopped → AgentOutput 作为工具结果返回父 loop：
- `CORE\subagent\runner.ts:335-371`
  ```ts
  const completed = winner.kind === "completed" ? winner.completed : await guardedCompletionPromise;
  ...
  await writeCompletedAgentArtifacts(lifecycle, request, completed.output);
  registry.update(lifecycle.agentId, (task) => ({ ...withoutRuntimeMessageState(task),
    status: "completed", completedAt: new Date(), output: completed.output, ... }));
  await emitSubagentEvent(options, SessionEventType.SubagentStopped, request,
    lifecycle.runTraceContext, { agentId..., childSessionId..., parentToolCallId...,
      status: "completed", totalDurationMs..., totalToolUseCount..., totalTokens... });
  ```
  `AgentCompletedOutput.content[0].text = childResult.response`（1173-1189），即子代理最终消息。工具描述明示红线语义：`CORE\tool\handlers\agent.ts:106` `"The agent's final message is returned to you as the tool result; it is not shown to the user — relay what matters."`（工具结果渲染在 Agent 卡"Agent output"区：`UI\ToolCallBlocks\renderers\agent.tsx:322-333` + `agentHelpers.ts:215-225 getAgentActivityContent`；后台时优先 taskNotification.result 摘要而非 output_file 全文）。

2) 后台：完成通知**同步**入父命令队列（TypeScript 层面拒绝 async enqueue 防 fake-notified）：
- `CORE\subagent\runner.ts:85-93`（`enqueueParentTaskNotification` 注释："background completion 必须同步写入父 runtime command queue；返回 undefined 可让 TypeScript 拒绝 async enqueue"）与 `1833-1891`（enqueueBackgroundNotification：`originMeta: { backgroundSource: "subagent", title, workId }`，`registry.update(..., notified: true)` 去重防双通知）。

3) 竞态防护 A —— subagent 行与运行态目录在同一事件事务物化（避免 spawn 后查询落在中间态）：
- `BOOT\zcode-protocol-v4\product-projection.ts:4150-4164`
  ```ts
  /**
   * Subagent row 与摘要投影在同一个 event transaction 内 materialize。
   * 旧 UI 在 spawn 后另查 session/subagents；7 个并发 child 中查询若恰好落在
   * [spawn 事件, 查询] 之间……
   */
  ```

4) 竞态防护 B —— 后台启动 ACK 不许投影成 completed（结论未到不显示完成）：
- `SVC\zcode-agent\zcodeTaskServiceAdapter.ts:5197-5202`
  ```ts
  if (isBackgroundAgentLaunchResult(toolName, result)) {
    // Agent 后台启动 ACK 只是子 agent 已创建，不代表子 agent 已完成；
    // 投影成 completed 会让前端在真实 completion 前把 subagent 卡片误标为完成。
    return "in_progress";
  }
  ```

5) 竞态防护 C —— 终态 snapshot 为事实源但保留 live 镜像的父子归属/大字段：
- `SVC\zcode-agent\zcodeTaskServiceAdapter.ts:858-878`
  ```ts
  // 终态 snapshot 来自父 session message parts，可能没有 live mirror 的
  // subagent parentToolCallId/raw/output。这里把 snapshot 作为终态事实源，同时保留
  // live 协议事件已经提供的父子归属和大字段，避免 task_complete 后工具树被覆盖丢失。
  ```

6) 竞态防护 D —— 子代理结论全文永远可取（不依赖内存 publisher 存活）：
- child publisher 终态后保留 120s 再释放：`BOOT\zcode-protocol-v4\v4-gateway.ts:496-497` `DETACHED_CHILD_PUBLISHER_GRACE_MS = 120_000`；释放后再订阅走 cold resume（child 作为 subagent_child 持久化在 session store，1086-1102 prune 逻辑）。CLI 重启后冷 hydration 从父工具部件合成 subagent 行：`BOOT\zcode-protocol-v4\transcript-hydration.ts:495-523, 725-744`（childSessionId 从 output/metadata 恢复，缺失时按 `createSessionId(\`subagent_${agentId}\`)` 重算——与 runner 生成规则一致）。历史目录查询：`BOOT\zcode-protocol\server-operations.ts:1694-1785 listSessionSubagents`。rewind/后台完成竞态：`CORE\runtime\methods\runtime-command-generation.ts:32-66`（branchGeneration 不匹配的 SubagentStopped/Message 直接丢弃，旧分支结果不得污染新分支）。

## 问 5：生命周期管理（启动/并行/取消/失败/超时）

1) **启动**：模型调用 `Agent`（aka Task）工具 → executor 带 `parentToolCallId: context.toolCallId`（`CORE\tool\handlers\agent.ts:189, 207`）→ `port.launch()` 分流：`run_in_background`/profile.background=true 走 `start()`（立即返回 `AgentBackgroundedOutput`，ACK：149-163），否则前台 `run()` 阻塞 await（`CORE\subagent\runner.ts:144-174`）。前台注册 running task 前先写 metadata.json，失败即撤注册防 fake running（184-200）。

2) **并行**：每个子代理独立 agentId/childSessionId/AbortController/registry 条目（runner.ts:134-136），父 loop 多个 Agent 工具并发执行；`InMemoryRuntimeTaskRegistry` 管全部任务（`CORE\runtime-task\registry.ts`）。前台可在运行中被转后台：`Promise.race([completion, waitForBackgroundRequest, autoBackgroundTimer])`（runner.ts:312-333）。UI 并发正确性靠 `parentToolCallId` 配对（问 2 第 3 条）。

3) **取消**：`stopTask` → abort controller 触发（runner.ts:550-569）；父 Stop 信号经 `guardSubagentPromiseWithAbort` 保证 Agent 工具不会永远停在 running（1272-1328，注释："子运行时或模型适配器在 abort 后可能永不 settle；外层 Agent 必须自己监听父 signal"）；停止终态统一写 metadata/output 并 emit `SubagentStopped(status:"stopped"→投影 cancelled)`（1658-1664、1689-1743）。父会话 stopTargetKind 含 `"subagent"`（`SHARED\zcode-protocol-v4\snapshot.ts:40-51`）。

4) **失败**：前台 catch 写 `writeFailedAgentArtifacts` + registry failed + `SubagentStopped(status:"failed", error)`（runner.ts:385-435，错误分级：wrapper 是 `CHILD_RUNTIME_FAILED`，真实 provider 错误在 cause 链）；后台 `finalizeBackgroundFailure` 同构（1576-1649，且用 `selectExecutionErrorMessage` 保留 provider 原文）。

5) **超时**：不活动 watchdog（默认 `DEFAULT_MODEL_STREAM_IDLE_TIMEOUT_MS`）到点 abort，错误码 `CHILD_RUNTIME_FAILED`+retryable（runner.ts:1194-1270）。

6) **UI 层表现**：运行中 = Agent 卡 running + 状态面板 Agents 分区行（可点开 pane、可 Stop）；后台转后台后 = backgroundWorks 出现 kind=subagent 条目（`SubagentSpawned(background:true)` 同事务补 `BackgroundWorkSummary`，product-projection.ts:4440-4483）；完成 = 行终态 + （后台）backgroundResult 消息行（`origin: "backgroundResult"` + `originMeta.backgroundSource: "subagent"`，`SHARED\zcode-protocol-v4\rows.ts:127-143`）。

## 问 6：主会话投影中子代理行的状态机与徽标数据来源

1) **行状态机（SubagentRow.status）**：`running → success | failed | cancelled`（rows.ts:270）。驱动源：
- `running`：onSubagentSpawned（product-projection.ts:4373-4437）
- 终态：onSubagentStopped 按 `mapSubagentStatus`（5731-5742）
- 运行中增量：`SubagentMessage` → `row.delta(summaryText, append)`（4485-4494）。

2) **运行态目录（快照 A 区权威字段，非 renderer 缓存）**：
- `SHARED\zcode-protocol-v4\snapshot.ts:383-403`
  ```ts
  // subagent 运行态属于 conversation 权威投影，而不是 renderer 查询缓存。
  // ended 详情保持 cursor query；snapshot 只携带目录总数，避免运行中并发数量依赖查询时序。
  export const runningSubagentSummarySchema = z.object({
    childSessionId, agentId?, toolCallId?, subagentType, title, summary?,
    status: z.enum(["running", "waiting", "blocked"]), startedAt? });
  export const subagentProjectionStateSchema = z.object({
    revision, childSessionIds, running, endedTotal });
  ```
  waiting/blocked 的推导：`product-projection.ts:4258-4292` —— `waiting` = pendingInteractions 里有 `origin.kind === "subagent"` 且 `origin.childSessionId` 匹配；`blocked` = backgroundWorks 中 kind=subagent 且 `work.blocked`。整个目录在每次相关事件事务内重算，语义无变化则不发 delta（4300-4309，revision 单调 +1）。

3) **UI 消费（状态面板徽标/行）**：`UI\v4\conversationStatusPanelModel.ts:341-428` 把 `snapshot.subagents.running` 与 `backgroundWorks`（kind=subagent、按唯一 childSessionId 精确联接，重复身份宁可不显示控制也不能停错任务，366-375）join 出 `runningSubagentWorks`（含 `controlWorkId/cancellable` → Stop 入口）。渲染：`UI\v4\ConversationStatusPanel.tsx:1433-1562`（BotIcon + title + 秒级 elapsed 计时 1464-1468 + 整行透明按钮打开子会话 pane 1527-1540 + 独立 Stop 按钮）。

4) **徽标颜色**：优先配置色 → 工具原始字段色 → 名称 hash 色：`UI\ToolCallBlocks\renderers\agent.tsx:235-248`（内置 agent 有显式色防 hash 变红，subagentsService.ts:108-110）。

## 子代理数据流完整时序（文字版）

```
[启动]
1. 模型发起 Agent/Task 工具调用（父 AgentRuntime，parentToolCallId=父工具ID）
2. SubagentPort.launch → 前台 run() 或后台 start()
3. createSubagentLifecycle：agentId、childSessionId=subagent_<agentId>、输出目录（runner.ts）
4. registry.register(running) + 写 metadata.json（状态 running）
5. new AgentRuntime(childSessionId, {taskType:"subagent_child", eventStore=父store实例, sessionStore=父store})
6. child.ensureSessionPersistedForExternalActivity(prompt)  ← 先落盘
7. onSessionReady → emitParentEvent(SubagentSpawned) → 父 appendEvent（父事件日志持久化）
   → bootstrap onSessionEvent（父 record）→ v4Gateway.ingest(父sessionId)
   → product-projection.onSubagentSpawned → row.appended(SubagentRow, running)
   → 同事务 materializeSubagentProjection → state.updated(subagents.running)
   → flush 帧(30ms) → renderer ConversationProjectionStore.apply → 主窗口 Agent 卡 running
   [若 background:true] 同事务补 backgroundWorks 条目（状态面板出现可 Stop 行）

[运行中（实时刷新，红线 2）]
8. child executeTurn：每个事件 child.appendEvent → 按 childSessionId 落 eventStore（子转写持久层）
9. 父侧 eventSink 双路通知（不重复持久化）：
   a) raw child event → notifyEventSinks(sessionId=childId)
      → bootstrap onSessionEvent 发现 event.sessionId≠父record → ingestDetachedLiveSession(childId)
      → child publisher（detached，无独立 record）→ 子代理 pane/drilldown 的
        v4/conversation/<childId> 订阅者收到 delta 帧（与主会话同一 SessionDataLayer/管线）
   b) mirrorSubagentToolEvent（仅工具/权限类）→ notifyEventSinks(sessionId=父Id)
      → v4 父投影按 source="subagent" 丢弃（主窗口不出现子工具行）
      → 权限事件例外：生成 pendingInteraction(origin.kind="subagent") → 子状态变 waiting，确认窗在父会话弹出
10. 子代理 pane：SessionDataLayer.acquire(childId) → subscribe topic → 快照+delta 实时渲染

[完成（结论正确渲染，红线 3）]
11. child TurnComplete → childResult.response=最终消息
12. 前台：writeCompletedAgentArtifacts(output.txt/task.output/metadata.json completed)
    → registry completed → emit SubagentStopped(status:"completed")（父日志持久化）
    → 父投影 onSubagentStopped → row.upserted(success, endedAt) + subagents.running 移除/endedTotal+1（同事务）
    → AgentOutput 作为父 Agent 工具 ToolCallResult 落父转写 → Agent 卡变 success，
      展开区"Agent output"渲染最终消息全文（工具结果不进消息流正文，模型负责转述）
    后台：finalizeBackgroundCompletion → 同步 enqueueParentTaskNotification
    （父命令队列 task-notification，notified 去重）→ 前台空闲时变成
      userInput(origin=backgroundResult, backgroundSource=subagent) 行 + 通知文本（含 result 摘要/output_file）
    同时 SubagentStopped(background:true) 收口 subagent 行与 backgroundWorks
13. child TurnComplete 亦走 9a → 子 pane 收到终帧；publisher 保留 120s（DETACHED_CHILD_PUBLISHER_GRACE_MS）
    后无订阅者则释放；再订阅 → cold resume 从 sessionStore(subagent_child) 冷恢复完整转写
    （CLI 重启同理：transcript-hydration 从父工具部件合成 subagent 行，childSessionId 可重算）

[失败/取消/超时] 同 12 骨架，status=failed(error 原文)/cancelled(stopped)；watchdog/abort guard 保证父工具必达终态；
rewind 竞态由 branchGeneration 拒收旧分支 Subagent* 事件。
```

**对三条红线的机制映射**：红线 1（任务内容不进主窗口）= `isMirroredSubagentToolEvent` 投影过滤 + SubagentRow 无内容字段 + Agent 卡 `canToggle=false` 单行摘要 + subagent_child 不进主任务索引；红线 2（实时刷新）= raw child event 直通父外部 sink → `ingestDetachedLiveSession` 建 child publisher → 子 pane 与主会话共用 SessionDataLayer/30ms continuous delta；红线 3（结论正确渲染）= persist-before-spawn、行+目录同事务物化、终态 snapshot 优先合并（保留 live 父子归属）、后台 ACK 不投影 completed、120s publisher 宽限 + sessionStore 冷恢复兜底。
