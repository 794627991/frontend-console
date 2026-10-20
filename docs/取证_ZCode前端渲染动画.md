# ZCode 参考实现前端渲染与动画机制深度取证报告

> 2026-10-20 · v4 归一重构批前取证（Explore 子代理产出，行号实测）
> 代码根：`D:\AI\FrontendHarness\ZCode`。核心结论先行：**ZCode 前端是「单一投影 store + 纯函数 apply + 按 turn 聚合的行渲染器」架构。live 与历史回放是同一条管线（同一 store、同一 apply、同一渲染组件），没有任何「live 直改 DOM」旁路；用户消息不走乐观气泡，而是「命令上行 + 权威投影回显 + 2 秒 watchdog 自愈」；流式动画的平滑性靠服务端 30ms flush 合帧 + running turn 脱离虚拟列表（live tail 放正常文档流）+ 新块 900ms 淡入三件事共同保证。** `stream-animate` 包是一个独立的流式帧率测量实验室（benchmark 工具），不是生产动画代码。

## 1. 前端状态模型：投影存哪里、apply 怎么写、DOM 怎么推导

### 1.1 投影存在哪里

每个会话一个 `ConversationProjectionStore`（外部 store，不依赖 Redux），由 `SessionDataLayer` 按 topic 管理、引用计数共享：
- `packages/ui/src/v4/sessionDataLayer.ts:52-98` —— `Map<topic, store>`，首个引用触发 subscribe：
  ```ts
  export class SessionDataLayer {
    private readonly entries = new Map<string, SessionEntry>();
    acquire(sessionId: string): SessionLease {
      ...
      const store = new ConversationProjectionStore(topic, this.transport, this.rowPool);
      entry = { store, refCount: 1, keepWarmTimer: null };
      this.entries.set(topic, entry);
      openKind = "cold";
      void store.connect({ rendererPrepareStartedAt: startedAt });
  ```
- 状态形状 `packages/ui/src/v4/conversationProjectionStore.ts:109-118`：
  ```ts
  export interface ConversationStoreState {
    status: ConversationStoreStatus;          // connecting | live | error | closed
    snapshot: ConversationSnapshot | null;    // 权威投影（含 rows.window 尾窗）
    subscriptionId: string | null;
    optimisticCommands: readonly OptimisticCommand[];  // 唯一允许的非权威态（overlay）
    loadingOlder: boolean;
    ...
  ```
- store 的三条铁律写在文件头（`conversationProjectionStore.ts:2-7`）：
  ```
  //   1. snapshot → 整体替换，绝不 merge；
  //   2. delta 帧仅在区间衔接（frame.fromSeq === snapshot.seq）时 apply，断档不猜、不缓存补偿；
  //   3. base 与状态同生共死——断档时状态未被污染，携当前水位重订阅，由服务端裁决 resume/snapshot。
  // 除 optimistic overlay（pending 命令展示）外，本 store 不产生任何 conversation 事实。
  ```

### 1.2 apply 纯函数

apply 是协议的一部分，规范实现放在 shared 包（客户端与服务端共用同一份语义）：
- `packages/shared/src/zcode-protocol-v4/apply.ts:72-116`（不可变，输入旧 snapshot + delta，输出新 snapshot）：
  ```ts
  export function applyConversationDelta(
    snapshot: ConversationSnapshot,
    delta: ConversationDelta,
  ): ConversationSnapshot {
    switch (delta.op) {
      case "row.appended":
        return { ...snapshot, rows: { ...snapshot.rows,
          window: [...snapshot.rows.window, delta.row],
          totalCount: snapshot.rows.totalCount + 1,
          firstRowId: snapshot.rows.firstRowId ?? delta.row.rowId } };
      case "row.upserted": {
        const index = snapshot.rows.window.findIndex((row) => row.rowId === delta.row.rowId);
        if (index === -1) return snapshot;      // §4.3：未加载 rowId = no-op
        const window = [...snapshot.rows.window];
        window[index] = delta.row;
        return { ...snapshot, rows: { ...snapshot.rows, window } };
      }
      case "row.removed": { ... filter(row => row.rowId < delta.fromRowId) ... }
      case "row.delta": { ... appendToRow(target, delta.path, delta.append) ... }
      case "state.updated":
        return { ...snapshot, ...delta.patch };   // 键级整体替换，绝不深合并
  ```
- delta 操作集合是**封闭的**（`packages/shared/src/zcode-protocol-v4/delta.ts:2-9` 注释 + 104-118 schema）：只有 `row.appended / row.upserted / row.removed / row.delta / state.updated`（外加 pluginUi live-only 与 workflowRun 键级增量）。注释明确：「没有 row.inserted（中间插入）、没有 row.moved、没有字段级 JSON patch——凡此模型表达不了的结构变化，服务端一律发 snapshot resync，刻意压缩客户端错误面」。

- store 侧帧应用入口 `conversationProjectionStore.ts:664-736`：snapshot 帧整体替换（673-684），delta 帧先做连续性检查再 apply：
  ```ts
  if (!current || frame.fromSeq !== current.seq) {
    // 规则 2：断档不猜。… 重订阅让服务端裁决续传或全量
    ...
  }
  const applied = applyConversationDeltas(current, frame.payload.deltas);
  // seq 是快照对齐水位（R-03），delta 帧应用完推进到帧右端点。
  const next = this.shareDeltaRows({ ...applied, seq: frame.toSeq }, frame.payload.deltas);
  ```

- 流式文本的 append 语义（`apply.ts:39-49`）：`row.delta` 只做字符串拼接，且只允许作用于流式态行：
  ```ts
  function appendToRow(row: ConversationRow, path: StreamablePath, append: string): ConversationRow {
    switch (path) {
      case "text":
        if (row.kind === "assistantText" || row.kind === "reasoning") {
          return { ...row, text: row.text + append };
        }
  ```

### 1.3 「DOM 是投影的纯函数」如何落实

四层机制，无手写 diff：
1. **UI 只读快照**：组件经 `useSyncExternalStore` 订阅 store（`packages/ui/src/v4/useConversationProjection.ts:19-26`）。
2. **派生层（render units）是纯函数**：`ConversationTimeline.tsx:453-465` 用 `useMemo` 从 rows 构建 turn 级渲染单元；store 内还有行对象结构共享池（`conversationProjectionStore.ts:794-818` `shareDeltaRows`——row.upserted/appended 的新行按值换回池中旧引用，row.delta 只登记避免流式逐帧深比较），使 React 的引用相等性判断即等价于值相等性。
3. **React 按 key 增量 reconcile**：虚拟列表 item key = `turnId`（`conversationTurnRenderUnits.ts:321-333`）；行渲染器 `ConversationRowView` 是 `memo`（`ConversationRowView.tsx:2318-2322`：「虚拟列表逐行渲染，父投影变化时只有 props 真正变化的行才重渲染」）。DOM 更新粒度 = **按 turn（虚拟行）+ 行级 memo**。
4. **副作用与内容分离**：滚动/测高/贴底全部通过 layout effect 与 ResizeObserver 作用于容器（不碰内容 DOM），内容 DOM 永远只由 JSX 从 snapshot 推导。

## 2. 流式动画：stream-animate 是什么、动画怎么实现

### 2.1 stream-animate 包的真实身份（重要澄清）
`packages/stream-animate` 是一个**独立的测量实验室**（dev tool），不是生产渲染代码：
- `packages/stream-animate/package.json`：`"private": true`，仅依赖 react/vite，不被 ui/web/client 引用。
- 它用真实流式请求，把每个字符到达事件按时间戳分桶到 60/120fps 的帧里，统计每帧字符数、峰值、预测（`packages/stream-animate/src/server/frameBuckets.ts:9-45`），用于验证「流式 delta 的到达分布」在渲染帧预算内是否平滑（为 flush 窗口调参提供数据）。

### 2.2 生产端「批量合帧」——服务端 30ms flush + coalesce
平滑的第一道保障在**服务端管线**，不在前端：
- 交付 profile（`packages/shared/src/zcode-protocol-v4/core.ts:34-45`）：桌面 continuous `flushWindowMs: 30`，web replayable `flushWindowMs: 150`。
- CLI publisher 每订阅者维护 flush buffer，「filter → coalesce → 打帧」，由宿主按 flushWindowMs 定时驱动（`apps/zcode-cli/packages/bootstrap/src/zcode-protocol-v4/conversation-topic-publisher.ts:914-947` `reserveFlush`）。
- 合并规则是语义保持的纯函数（`packages/shared/src/zcode-protocol-v4/coalesce.ts:1-10, 122-147`）：相邻同 (rowId,path) 的 row.delta 拼接、相邻 state.updated 浅合并、row.upserted 吞掉同 rowId 更早的 row.delta、row.removed 是屏障……「coalesce(deltas) 与逐条投递等价」有黄金测试保证。

**所以前端每 ~30ms 收到一帧合并后的 delta，apply 一次、React 重渲染一次**——天然不阻塞、不逐 token 抖动；打字输入框（composer）与时间线是兄弟节点，渲染互不牵连。

### 2.3 running turn 脱离虚拟列表（live tail）——防跳动核心
`packages/ui/src/v4/conversationTimelineLiveTail.ts:9-28`：
```ts
/**
 * running turn 继续放在绝对定位虚拟行里时，正文 DOM 会先长高，
 * ResizeObserver 下一帧才回填 totalSize/scrollTop，导致轮尾 ChatLoading 来回跳。
 * 只把真正的最后一个 running unit 拆成 normal-flow live tail；历史或陈旧 running
 * 行仍归虚拟列表，避免扩大常驻 DOM。
 */
export function splitConversationTimelineLiveTail(units) {
  const liveUnitIndex = units.length - 1;
  const liveUnit = units[liveUnitIndex];
  if (!liveUnit?.isRunning) return { virtualizedUnits: units, liveUnit: null, liveUnitIndex: null };
  return { virtualizedUnits: units.slice(0, liveUnitIndex), liveUnit, liveUnitIndex };
}
```
即：**只有正在流式的最后一轮放在正常文档流（虚拟列表外），高度增长即时反映、ResizeObserver 只用于缓存测高与贴底**（`ConversationTimeline.tsx:1246-1295` 对 live tail 单独挂 ResizeObserver，测高后仅在仍持有滚动权时贴底）。轮次终结时该 unit 回到虚拟列表（`ConversationTimeline.tsx:466-469` 每次 rows 变化重新 split）。

### 2.4 新内容淡入（900ms opacity）与工具卡入场
- CSS 入场动画只有 opacity，无位移（合成层友好）：`packages/ui/src/styles.css:966-1053`：
  ```css
  @keyframes zcode-stream-text-in { 0% { opacity: 0; } 100% { opacity: 1; } }
  [data-zcode-stream-animate="true"] {
    animation: zcode-stream-text-in 900ms cubic-bezier(0.16, 1, 0.3, 1)
      var(--zcode-stream-animation-delay, 0ms) both;
    will-change: opacity;
  }
  @media (prefers-reduced-motion: reduce) { ... animation: none; }   /* 全部尊重减动效 */
  ```
- 工具卡入场动画**只在流式期间新出现的 tool 上播一次**，按 toolId 全局登记防重播（虚拟列表重挂/切任务不重播）：`packages/ui/src/ToolCallBlocks.tsx:160-195`：
  ```ts
  const toolEntranceAnimationKey = `${streamingEntranceKeyPrefix}:${toolCall.toolId}`;
  // tool 在流式对话中新出现时如果没有淡入，会和同一段文字的渐入节奏割裂。
  // 这里按 toolId 记录已经展示过的 tool，切换任务或虚拟列表重挂时不重复播放。
  ```
  渲染处 `ToolCallBlocks.tsx:383`：`data-zcode-tool-stream-animate={shouldPlayEntranceAnimation ? "true" : undefined}`。播放后 1000ms 定时移除 data-attr。
- 预览卡批量出现时用 `--zcode-stream-animation-delay` 做级联错峰（`AssistantPreviewCards.tsx:296-299`）。

### 2.5 思考流（reasoning）滚播
不展开正文，trigger 行内做**单行滚播**：取流式文本最后一个非空行，单行视口溢出后每次内容增长把 `scrollLeft` 推到末尾（新内容在右、旧内容左移），左右 16px 渐变 mask：
- `packages/ui/src/components/ai-elements/reasoning.tsx:252-267`（摘要提取）+ `:244-248`：
  ```ts
  export function scrollReasoningSummaryToEnd(viewport) { viewport.scrollLeft = viewport.scrollWidth; }
  export function resolveReasoningStreamingSummary(streamingText: string) {
    const lines = streamingText.replace(/\r\n?/gu, "\n").split("\n");
    for (let index = lines.length - 1; index >= 0; index -= 1) {   // 取最后一个非空行
      const text = lines[index]?.trim() ?? "";
      if (text.length > 0) return { key: String(index), text };
  ```
- 滚动同步 effect（`reasoning.tsx:300-327`）：内容变化 + ResizeObserver 双触发；运行态文案用 `animated-gradient-text` 流光（纯 CSS），**不用旋转 loader**（注释：「thinking 会在长流式回复里持续存在，旋转 loader 会长期占用渲染资源」）。
- 流式与完成态都默认折叠，`autoCollapseKey={streaming ? null : row.state}` 保证状态边界不覆盖用户手动展开（`ConversationRowView.tsx:1781-1804`）。

### 2.6 正文流式渲染
assistant 正文用 streamdown（流式容错 markdown）按块渲染，**没有逐字打字机动画**——文本按 30ms 帧到达，新块挂载时吃 900ms 淡入；完成态切 static 模式避免 Streamdown 内部状态循环（React #185 规避）：`packages/ui/src/components/ai-elements/message.tsx:700-706`：
```ts
export function resolveMessageStreamdownMode(renderStreaming: boolean): MessageStreamdownMode {
  // 只有真实流式输出进入 streaming，历史/完成态内容固定走 static
  return renderStreaming ? "streaming" : "static";
}
```

### 2.7 工具卡/工作组开合过渡
- 「已工作」折叠区用 Radix Collapsible；自动收起时用 `!important` 覆盖 Radix 测量内联样式以播放高度动画（`styles.css:1056-1078`）。
- 运行中时钟「工作中 N 秒」由 Timeline 的共享 UI 时钟驱动：仅在存在 running unit 时以 1000ms interval 更新 `liveNowMs`（`ConversationTimeline.tsx:618-631`），完成态耗时用协议事实（header.activeMs/endedAt），拒绝用 UI 时钟（`conversationTurnWorkSegments.ts:50-64` 注释：「完成态缺少 activeMs/endedAt 时不能继续吃当前时钟，否则历史『已工作』会随时间增长」）。

## 3. live 与历史回放：同一条管线（证实）

**结论：同一管线，无旁路。** 证据链：
1. **同一 store、同一订阅**：冷打开（首帧 snapshot）与 live 增量都进 `ConversationProjectionStore.handleFrame`，都调同一个 `applyFrame`（`conversationProjectionStore.ts:617-662`）。历史回放/刷新/新设备 = 重新 `connect()` 拿 snapshot 整体替换；live = 连续 delta apply。切会话 = 释放旧 lease、acquire 新 lease（`sessionDataLayer.ts:76-122`），组件树不变，只是 props 换了一份 rows。
2. **Timeline 只吃快照**：`packages/ui/src/v4/SessionPane.tsx:5604-5618`：
   ```tsx
   <ConversationTimeline
     rows={timelineSnapshot?.rows.window ?? []}
     totalCount={timelineSnapshot?.rows.totalCount ?? 0}
     canLoadOlder={timelineSnapshot ? hasOlderRows(timelineSnapshot) : false}
     loadingOlder={state.loadingOlder}
     onLoadOlder={handleLoadOlder}
   ```
   没有第二个消息 DOM 写入者。
3. **滚动加载历史不重建窗口**：`loadOlder` 以窗口首行 rowId 为游标调 `rows/range` query，结果**按 rowId 键控前插合并进同一个 `rows.window`**（`conversationProjectionStore.ts:257-265` + `:1047-1086`）：
   ```ts
   export function mergeOlderRows(window, fetched): ConversationRow[] | null {
     const firstRowId = window[0]?.rowId ?? Number.POSITIVE_INFINITY;
     const older = fetched.filter((row) => row.rowId < firstRowId);
     if (older.length === 0) return null;
     return [...older, ...window];
   }
   ```
   三重陈旧读防护：`atLogEpoch` 不匹配整体丢弃、在途期间窗口首行变化丢弃、`loadingOlder` 单飞防重入。
4. **「live 直改 DOM」旁路不存在**：全仓库检索，store 的唯一写入方是 `handleFrame`（订阅帧）、`loadOlder/loadAllOlder/refreshPlans`（只读 query）与 optimistic overlay 三个方法；`optimisticCommands` 没有任何 UI 渲染消费者——它只喂 watchdog。ChatLoading/工作组头/用户气泡全部从 `rows.window` 派生。
5. **断档自愈也是同管线**：delta 断档不猜——同订阅 resync（恢复阶梯 resume→forceSnapshot，`:863-1007`）；订阅换代则携水位 fresh subscribe，服务端裁决 resume/snapshot（`:440-443` subscribe 带 base）。

## 4. 用户消息出现链路与「正在执行」动画

### 4.1 发送链路（无本地伪造消息）
路径：`ConversationComposer.submit` → `SessionPane.dispatchCommand("sendText", ...)` → RPC `v4/command` → 权威投影出现 `userInput` row（带 `sourceCommandId`）→ 时间线渲染。
- **输入框不先行清空**：`ConversationComposer.tsx:1601-1614`——`handleEditorSubmit` 返回 `false`「编辑器不自行 reset，由 submit 成功后经 inputApiRef.clear() 清空——失败时草稿留在输入框」。
- **命令上行前的动作**（`SessionPane.tsx:1898-1934`）：构造信封（commandId = uuidv7，重试不变，`commandFactory.ts:51-72`）；**先持久化恢复账本再上行**：
  ```ts
  const envelope = createCommandEnvelope({ type, sessionId: targetSessionId, payload, ... });
  // 必须早于第一次上行：transport error/renderer refresh 后仍有可查询线索。
  pendingCommandRegistry.record(envelope, ...);           // localStorage 持久，TTL 24h
  if (lease?.store && type !== "createSession") {
    lease.store.markCommandPending({ commandId: envelope.commandId, type: envelope.type, issuedAt: envelope.issuedAt });
  }
  ```
- **ACK 后的 watchdog**（`SessionPane.tsx:1986-1994` + `conversationProjectionStore.ts:1307-1334`）：ACK accepted/duplicate 只代表 CLI admission；若 2 秒内投影中没有出现本命令的 queue item 或 `userInput(origin=realUser, sourceCommandId)` 行，**不重放命令、不伪造消息**，只复用 same-sub recovery 拉回权威投影。
- **用户消息行何时渲染**：服务端投影发出 `row.appended { userInput, sourceCommandId }` → store apply → render unit 重建 → `UserInputRowView` → `ConversationUserInputBubble`。overlay 条目在 `reconcileOptimistic` 里以 `sourceCommandId` 对账退场（`:1354-1377`）。发送失败则 `settleCommand` 移除 overlay。
- 排队中的输入（guide）由权威 `snapshot.queue` 派生渲染（`pendingGuideProjection.ts:13-32` 按 `delivery.admitted === "guide"` 分流），在时间线尾部独立列表，不冒充已发出的消息。

### 4.2 「正在执行」动画的状态驱动
- 权威信号 = **turnHeader 行的 `state`**：`conversationTurnRenderUnits.ts:159-180`：
  ```ts
  function resolveTurnRunning(draft, options): boolean {
    if (draft.header) {
      if (draft.header.executionKind === "controlOnly") return false;
      // turnHeader 是 projection 的权威轮次边界；已终态主轮不能被
      // 同轮仍在运行的 background tool/subagent 行重新推成 running。
      return draft.header.state === "running";
    }
  ```
- spinner（ChatLoading）只挂在**最后一轮 + running + 无交互阻塞**：`ConversationTurnGroup.tsx:217-243` `TurnChatLoadingSlot` + `chatLoadingVisibility.ts:38-62`：
  ```ts
  export function shouldShowTurnChatLoading({ blockedByActiveWork, blockedByInteraction, isLastTurn, isRunning, rows }) {
    if (!isLastTurn || !isRunning || blockedByActiveWork || blockedByInteraction) return false;
    // pendingInteractions / activeWorks 是权威事实源，但恢复或乱序窗口
    // 可能先只有行状态；行级 fallback 避免权限…出现时底部 loading 短暂闪回。
    return !rows.some((row) => row.kind === "toolCall" && row.status === "pendingApproval") && ...;
  }
  ```
  注释还写明 spinner 的可见性原则（`ConversationTurnGroup.tsx:236-239`）：「running 是 ChatLoading 的权威事实；额外静默计时会让 projection 更新反复重启可见性」——即 **loading 消失不需要清理定时器，因为它的存在就是状态的纯函数**。

## 5. 大列表性能：虚拟化、测高、滚动跟随

### 5.1 虚拟化结构
- 历史区：`@tanstack/react-virtual`，overscan 8，动态测高（`ConversationTimeline.tsx:783-803`）。
- 测高用 ResizeObserver 优先（不触发同步 layout），真实高度写入组件级 LRU 缓存 `TimelineRowHeightCache`（`timelineRowHeightCache.ts:18-61`，上限 4000 条、按 turnId 键、会话切换整体清空）。
- **running turn 不进虚拟列表**（见 2.3 live tail），子代理 drilldown 也不虚拟化只取最近 20 条文本（`SubagentDrilldown.tsx:17-19`）。
- 服务端快照只给尾部窗口 `snapshotTailWindowRows: 60`（`core.ts:75`），`firstRowId` 判定是否还有更早。

### 5.2 贴底/上翻打断状态机（纯函数，`timelineScrollAnchor.ts`）
- 跟随语义（文件头 `:1-9`）：「following 表达用户滚动权，不是瞬时几何快照：只有真实用户滚动输入可以改变它；程序化贴底、terminal 折叠和 virtualizer 测高补偿产生的 scroll 事件只更新几何账目」。
- 离底判定 48px 容差（`:13`）；**只有 source === "user" 的 scroll 才改 following**（`:57-65`）。
- **滚动事件来源分类**（`ConversationTimeline.tsx:1335-1351`）：wheel/touch/keyboard/scrollbar 捕获的「用户意图」（TTL 1200ms）> 程序化滚动标记 > 250ms 布局保护窗 > 兜底视为用户。
- **贴底前对账**（`timelineScrollAnchor.ts:169-197` `reconcileFollowingForContentAnchor`）解决经典竞态：用户 wheel 上滚后、scroll 事件派发前恰逢内容 commit，过期 following=true 会把用户拽回底部——规则是「明确向上滚动 → 立即解除跟随，同帧 terminal/layout commit 也必须让位」。捕获阶段登记意图的代码在 `ConversationTimeline.tsx:867-880`：
  ```ts
  const markUserScrollIntent = useCallback((intent) => {
    ...
    // running -> terminal 会在同一帧迁移 live tail、折叠工作历史并触发
    // virtualizer 测高。向上滚动必须在 scroll 事件之前先拿走滚动权
    if (intent === "awayFromBottom" && element && element.scrollHeight > element.clientHeight) {
      commitFollowing(false);
    }
  }, [commitFollowing]);
  ```
- 贴底动作在 `useLayoutEffect`（绘制前，无闪动，`ConversationTimeline.tsx:1770-1808`）；**贴底必须 instant scrollTop 赋值**（`:1102-1109` 注释：「smooth 的中间帧会被 scroll 判定误读为『离底』」）。
- **前插（loadOlder）锚定**：既有 turn key 稳定不重挂，前插只撑高 totalSize，`scrollTop += delta` 恢复阅读位置（`timelineScrollAnchor.ts:212-276` + `ConversationTimeline.tsx:1710-1768`）。
- **提前两个视口预取**（`timelineScrollAnchor.ts:279-306`）：`LOAD_OLDER_TRIGGER_PX = 64`、`historyPrefetchTriggerPx = max(64, viewport*2)`。
- 「回到底部」按钮：`shouldShowBackToBottom = !following && rowCount > 0`（`:200-205`）。
- 会话切换时：清测高缓存 + 重置 prepend 基线 + 从 renderer-local scroll memory 恢复历史位置，并 `overflowAnchor: "none"` 禁用浏览器原生 scroll anchoring（Chrome 会把 sticky composer 选作锚点覆盖恢复值）。

## 6. 占位/骨架屏机制：如何保证不留占位气泡

**结论：没有「用户消息占位气泡」这种东西**——因为不做乐观消息，就没有清理问题。占位类 UI 全部是「状态的纯函数」，状态翻转即消失：
- 用户消息：唯一临时态是 `optimisticCommands`（store 内 overlay），**不渲染任何气泡**，只用于 watchdog 对账；权威 row/queue 一出现即被 `reconcileOptimistic` 移除（`conversationProjectionStore.ts:1354-1377`），失败/被拒由 `settleCommand` 移除。
- 正在执行 spinner：`TurnChatLoadingSlot` 的可见性 = `shouldShowTurnChatLoading(...)`，轮次终态（turnHeader.state != running）或出现权限弹窗时自动 false；槽位 `min-h-5` 防止出现/消失时布局跳动（`ConversationTurnGroup.tsx:233`）。
- 排队输入：渲染的是权威 `queue.items`，不是本地预测（`pendingGuideProjection.ts:8-13` 注释：「旧 UI 直接渲染 queue.items，导致等待 model-step 注入的 guide 被误画成下一轮消息。这里只按权威 admitted delivery 分流展示，不复制、不改写」）。
- gen-ui 卡片 pending 态：流式中引用未解析时显示「等待生成中」小卡，completed 后按解析结果替换或显示「未完成」（`gen-ui/components/GenUiMessageResponse.tsx:52-64`）。
- 工具卡入场动画的清理：播放后 1s 定时移除 data-attr（`ToolCallBlocks.tsx:185-195`），且按 toolId 登记，重挂不重播、不残留。
- 行级「空内容裁剪」：reasoning 流式空文本返回 null（`ConversationRowView.tsx:1788-1790`）；`ConversationAssistantWorkItems` 在无可渲染项时整容器不创建（`ConversationTurnGroup.tsx:446-451`：「只有确认内层存在可渲染项后才创建 CollapsibleContent，让外壳与内容一起消失」）——双重防「空壳占位」。

## 7. UI 组件结构与行分发

### 7.1 核心组件树（聊天主链路）
```
SessionPane.tsx (5604: <ConversationTimeline rows=... pendingGuides=... bottomDock=<Composer...>>)
└─ ConversationTimeline.tsx (2122, memo)        虚拟滚动 + 滚动锚定 + loadOlder + find
   ├─ [虚拟历史区] virtualRows.map → ConversationTurnGroup (unit=历史turn)
   ├─ [live tail] (2013-2041, normal flow)  → ConversationTurnGroup (unit=running turn)
   ├─ ConversationPendingGuideList (排队 guide)
   └─ bottomDock = ConversationComposer (sticky)
ConversationTurnGroup.tsx (1766, memo)          一个 turn = 一个渲染单元
└─ ConversationWorkSegmentFlow (730)            工作段（Collapsible）
   ├─ AssistantHistoryStatus (640-728)          ★「工作组头」：工作中N秒/已工作N秒 + 折叠触发器
   ├─ flowItems → ConversationAssistantWorkItems / ConversationTurnRow / ConversationTurnCuaGroupRow...
   └─ TurnChatLoadingSlot (217-243)             ★spinner 槽
ConversationTurnRow.tsx (43) → ConversationRowView.tsx (2398, memo)   ★行渲染器
└─ switch (row.kind) (2341-2395):
   userInput      → UserInputRowView → ConversationUserInputBubble
   assistantText  → AssistantTextRowView → GenUiMessageResponse → MessageResponse(streamdown)
   reasoning      → ReasoningRowView → Reasoning/ReasoningTrigger(滚播)
   turnHeader     → TurnHeaderRowView（调试性渲染，render unit 已消费）
   timelineMarker → TimelineMarkerRowView（fork/compact/modelChange 分隔线）
   toolCall       → ToolCallRowView → ToolCallBlock → resolveToolCallRenderer（按工具族分发渲染器）
   subagent       → SubagentRowView（兜底摘要）+ Agent 行配对 → SubagentDrilldown（展开时）
   artifact       → ArtifactRowView
```

### 7.2 投影行 → 渲染单元的聚合
`buildConversationTurnRenderUnits`（`conversationTurnRenderUnits.ts:399-443`）把全序 rows 按 `turnId` 分桶成 turn 单元，再做可见性过滤（空 reasoning 裁掉、EnterPlanMode 裁掉、turnHeader/timelineOnly 处理）、轮尾拆分、工作段构建（`conversationTurnWorkSegments.ts`）。虚拟列表的 item 是 **turn**，不是 row——这既是大列表性能单位，也是「工作组头 + 折叠历史 + 最终正文」布局的单位。

### 7.3 子代理 pane
`SubagentDrilldown.tsx:1-60`：内嵌子会话只读预览，「复用 SessionDataLayer 租约（引用计数天然支持同会话多订阅视图），展开挂 lease、折叠卸载即释放」——即子代理 pane 与主对话**走完全相同的投影管线**，只是不虚拟化、只取最近 20 条 assistantText。

## 无框架原生 JS 移植要点

用原生 JS 复刻「投影 + apply + 行渲染器」，最简可行结构（对应关系：store→普通对象+监听器；useSyncExternalStore→自定义订阅；React memo→按 key 的 DOM 复用；render units→一次 reduce）：

1. **单一事实源（~60 行）**：`store = { state, listeners, setState(patch), subscribe(fn) }`。铁律照抄：只允许 `applyFrame(frame)` 一个写入方；snapshot 整体替换；`frame.fromSeq !== snapshot.seq` 时丢帧重订阅；断档不猜。
2. **apply 纯函数（照抄 apply.ts 的 switch）**：`applyDeltas(snapshot, deltas)` 不可变更新。rowId 用递增整数，`row.removed` 从 fromRowId 截断，`row.delta` 按 (rowId, path) 字符串拼接。**操作集保持封闭**，表达不了的变化发 snapshot。
3. **渲染 = 两段派生 + 按 key 的 DOM diff**：
   - `buildTurnUnits(rows)`：一次线性扫描按 turnId 分桶（含 isRunning 判定 = header.state、工作组头耗时、可见性过滤），每单元 key = turnId。
   - `renderTimeline(units)`：容器内按 key 对齐现有子节点——已挂载的 turn 用 `updateTurnNode(el, unit)` 更新（内部再按 rowId 对齐行子节点），新 turn `createTurnNode(unit)`，消失的移除。配合「row 对象值不变就复用旧引用」的结构共享，更新判断退化为 `oldRow === newRow`。
   - `createRowNode(row)` 按 `row.kind` switch 分发到 9 个行渲染器函数。
4. **流式平滑三件套（照抄要点）**：
   - 服务端/本地代理层做 **30ms flush + 合并**（同 rowId 的 append 拼接），前端每帧最多一次 setState。
   - **正在流式的最后一个 turn 放正常文档流**（虚拟列表外），历史 turn 绝对定位进虚拟窗口。
   - 新挂载节点加 `.stream-in`（900ms opacity 0→1，`prefers-reduced-motion` 关闭）；按元素 id 登记已播过的入场动画防重挂重播。
5. **滚动跟随状态机（照抄 timelineScrollAnchor.ts，纯函数可直接移植）**：
   - `following` 只由「用户来源」的 scroll 改变；wheel/touchstart/keydown 捕获阶段登记意图（TTL ~1.2s）；程序化贴底打 rAF 标记；内容 commit 时先 `reconcile(following, 意图, 几何)` 再决定 `scrollTop = scrollHeight`（instant，不用 smooth）。
   - loadOlder 前插后 `scrollTop += (newTotalSize - oldTotalSize)`；测高用 ResizeObserver 写入 `Map<turnId, height>` LRU 缓存。
6. **发送链路（不做乐观气泡）**：
   ```js
   const cmd = { commandId: uuidv7(), type: "sendText", payload, ... };
   pendingLedger.record(cmd);            // localStorage，刷新后可对账
   store.markPending(cmd.commandId);     // 仅内部 overlay，不渲染
   const ack = await send(cmd);
   if (ack.accepted) armWatchdog(cmd.commandId, 2000); // 投影静默则重订阅，绝不重放/伪造
   ```
   用户消息 DOM 只在投影出现 `userInput` row 时由行渲染器创建；输入框在 ACK 成功后才清空。spinner = `lastTurn.isRunning && !blocked` 的纯函数节点。
7. **管线唯一性检查**（移植后自测）：全代码库只允许一个函数创建/删除消息行 DOM（行渲染器）；「live」和「历史」只是同一 store 的两种帧来源；滚动加载历史 = 合并进同一 rows 数组，绝不整窗重建。只要这条不破，用户消息必现、组头必现、spinner 必现、无占位残留这四条红线就是状态机的自然推论。
