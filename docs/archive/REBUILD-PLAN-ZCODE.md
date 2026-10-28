# harness 前后端归一重构方案（ZCode 模式移植，2026-10-20 定稿）

> 目标：所有数据先走后端落盘整合，前端只消费后端投影；流式/重渲两套渲染归一为一条管线；
> 三条子代理红线（隔离/实时刷新/结论正确）按 ZCode 机制落地。

## 一、ZCode 归一架构本质（四份取证结论汇总）

```
[CLI 事件] → eventStore.append（唯一 seq 权威）→ durable 持久化（先落盘）
          → notify sinks → ProductProjection（reducer 纯函数，产 delta[]）
          → 每订阅者 coalesce buffer → 30ms flush 打帧 → SSE/长连接下发
          → 前端 ConversationProjectionStore.applyFrame（唯一写入方）
          → buildTurnUnits（按 turn 分桶）→ 行渲染器（按 kind 分发，DOM 按 key 复用）
```

四条铁律（照抄）：
1. **persist-before-publish**：事件先入账落盘再发布，live/replay/snapshot 的 seq 全来自同一账本
2. **投影=事件纯函数**：投影快照推进复用协议同一 apply——投影与 delta 流逐字节一致是构造保证
3. **delta 操作封闭**：只有 row.appended / row.upserted / row.removed / row.delta / state.updated；
   表达不了的结构变化一律服务端发 snapshot resync，客户端没有猜结构的代码路径
4. **DOM 是投影的纯函数**：前端 store 唯一写入方是 applyFrame；snapshot 整体替换绝不 merge；
   断档不猜（fromSeq !== local.seq → 携 base 重订阅，服务端裁决 resume/snapshot）

## 二、与我们工程的差距（当前病灶 → 归一解法）

| 当前病灶 | 位置 | 归一解法 |
|---|---|---|
| 工具行不入账（「设计3」） | histcache.js:12 | 工具行入投影：status 封闭枚举+startedAt/endedAt/output 全在行内，终态 upsert 清 progress |
| live 直改 DOM（工具卡 run 形态） | tools.js:673 renderToolUse | 事件→投影→行渲染器；live 只是把 delta 帧连续 apply |
| 整窗重建 11 处触发点 | _histRender 全部调用方 | 前端整窗只剩「收到 snapshot 帧」一种；由服务端单方裁决（epoch 失配/保留窗越界/背压溢出） |
| 方案B（回合终 400ms 重渲规整） | sse.js:727-835 | 天然退役：投影行生而终态形态（done 行一次成型含徽章），无需重渲规整 |
| P0-1 live MCP 无完成徽章 | tools.js:763 | 工具终态= row.upserted（status/output/endedAt 在行内），徽章是行状态纯函数 |
| 用户消息本地先行/丢消息向量 | _hgRowAdd/live 账 | 无乐观气泡：命令上行→overlay 登记（不含文本不渲染）→投影回推 userInput 行→reconcile 撤 overlay；2s watchdog 静默则重订阅恢复，绝不伪造 |
| _subState 未定义（活 bug） | subpane.js:1565 | 子代理管道重写，整体退役 |
| 子代理轮询全量重建（_subReplay follow） | subpane.js:696-792 | 子 pane 订阅子会话 topic，与主会话同一 store/apply/渲染管线，delta 直推 |
| watcher 推送链未实证 | subagent_watch.py | 后端事件路由统一：子代理事件按 child sessionId 进自己的投影+publisher（对位 ingestDetachedLiveSession） |

## 三、行模型（9 基础 kind + 我们的扩展行）

基础（ZCode 同款）：turnHeader / userInput / assistantText / reasoning / toolCall / subagent / timelineMarker
扩展（保住现有功能形态）：
- vision（识图卡：prompt/src/dur/结果卡内定格）——对位 artifact 行
- peer（协作回传通知行 .h-sub-notify + 转交线）
- sysnote / renew / audit / exit / modelSwitch —— 对位 timelineMarker 族
- 排队 guide —— A 区 state（queue.items），非消息行
行规则：row 自包含（渲染任一行不需看别的行）；结构变化换整行（upserted）；文本增长只 append（row.delta）；
rowId 后端 reducer 单调分配永不复用；turnId 是行上的标签不是容器。

## 四、后端设计（src/harness）

1. **eventlog/ 保留强化**：SessionEventLog 已有锁内 seq——升级为唯一权威源（现有 bump_epoch 直接对位 logEpoch）。
2. **新增 projection.py**（对位 ProductProjection）：每会话一实例；applyEvent(cli_event) → deltas[]；
   内部快照推进复用 apply 语义（构造保证）。行构造/终态收口/耗时聚合（activeMs）全在 reducer。
3. **新增 publisher.py**（对位 conversation-topic-publisher）：每订阅者 buffer（filter→coalesce→打帧）；
   30ms flush 窗；条数/字节双上限溢出→resyncRequired→发 snapshot。保留窗（近期 N 条 delta log）。
4. **/stream v2 协议**：subscribe 参数带 base{epoch, seq}；服务端裁决 resume（保留窗内回放差量）或
   snapshot（尾窗行+A 区状态，fromSeq=0）；帧信封 {topic, subId, fromSeq, toSeq, kind:snapshot|deltas}。
5. **hydration**：冷启动从既有 transcript JSONL 反向合成事件重放进 reducer（reduce(transcript) ≡ reduce(events)），
   旧会话无缝消费；子代理三源转写合成子会话事件流。
6. **子代理路由**：CLI 子代理转写事件按 agentId 归入子会话投影（watcher 扫描保留作采集源，改产事件入账）；
   父投影只收 subagent 行（spawned→running / stopped→终态）+ Agent 工具行终态（结论=tool result）。

## 五、前端设计（web/js/harness）

1. **新增 v4store.js**（对位 ConversationProjectionStore）：state{status, snapshot, overlay}；
   applyFrame 唯一写入方；断档→resubscribe(携 base)；overlay 只喂 watchdog 不渲染。
2. **新增 v4render.js**（对位 turnRenderUnits+RowView）：buildTurnUnits(rows)（分桶/running 判定/工作组头/可见性过滤）
   → renderTimeline(units)（容器按 turnId key 对齐复用；行按 rowId 对齐；kind 分发到行渲染器）。
   行渲染器复用现有工具卡/气泡/思考段的 CSS 形态（视觉不变）。
3. **live tail**：流式中的最后一个 turn 放正常文档流（虚拟/窗口列表外），高度增长即时反映不跳。
4. **发送链路**：submit→POST /send（带 commandId）→overlay 登记→投影回推 userInput 行→reconcile；
   ACK 后 2s 投影静默→自动 resubscribe。输入框 ACK 成功才清空。
5. **动画**：新行/新工具卡 900ms 纯 opacity 淡入（按 rowId/toolId 登记防重播）；spinner= lastTurn.isRunning 纯函数；
   思考滚播保留现有形态；prefers-reduced-motion 尊重。
6. **滚动锚定**：following 只认用户来源滚动；程序化贴底 instant scrollTop；上翻即解除跟随。
7. **子代理**：主窗口 subagent 行配对 Agent 工具行（parentToolCallId 精确绑定，非 FIFO）；
   子 pane = v4store.acquire(childTopic)——同一 store 类，同一渲染器，只读。结论渲染=Agent 工具行终态展开区。

## 六、施工分批（每批自测通过+提交，遵守 bump 版本纪律）

- 批A 协议层：rows/delta/apply/coalesce 的 Python+JS 双实现 + 黄金测试夹具（JSON 用例集双端跑绿——替代 ZCode 的双端共享代码）
- 批B 后端：projection.py（含 hydration）+ publisher.py + /stream v2 + 子代理事件路由
- 批C 前端 store：v4store.js（applyFrame/断档重订阅/overlay+watchdog）+ 单测
- 批D 前端渲染：v4render.js（units/行渲染器复用现有 CSS/live tail/滚动锚定）
- 批E 子代理：subagent 行+Agent 卡配对+子 pane 同管线+结论回传+完成后宽限
- 批F 切换+退役：主视图切新管线；退役 sse 直改/方案B/histAll 游标制/11 处 _histRender/_subReplay 轮询/_subState bug
- 批G 动画打磨+全链回归（用户验收清单）+ reviewer 全审

## 七、已知取舍

- SSE 保留作传输载体（不换 WebSocket）：POST 命令 + SSE 下行帧，够用且改动面小。
- 视觉形态不变：CSS/工具卡/气泡/思考段样式全部保留，只换数据与渲染管线。
- 旧会话兼容：hydration 保证既有 transcript 全量可回放。
- R4 终裁（归一后自然消解）：切回会话=重新订阅，服务端裁决——live 且可续传→resume 差量（残态=现实），
  否则 snapshot 定态。前端不再有「泵 vs 整窗」的选择。
