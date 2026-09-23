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
| `tests/test_eventlog.py`（新增，44 check） | 44/44 |
| `tests/test_roles_routing.py`（既有 155 check） | 155/155 |
| `compileall src` | OK |
| 前端主链 stub 冒烟（tools/_chain_smoke.js） | 全过 |
| 前端未定义引用（_undef_check.js 改动前后对比） | 140→140（零新增） |
| state 对账（_state_audit.js） | 38/38 |
| Flask test client 集成冒烟（stream 三态/events/transcript/tool_full/meta/GC 重建） | 全过 |
| run.bat 真机启动 | 窗口正常 |

## 三、未落项与迁移路线（笔记 9-14 的余量）

1. **前端 handleEvent → reducer handler 迁移**：信封已统一（type 字段），500 行 if/else 分派可逐块搬运成 reducer 投影——搬运不是重构，每块独立可验。
2. **durable 输入账本**（admitted→promoted 两步同事务）：当前排队纯前端内存（`_HG.queues`），刷新即丢；send 路径记录账本 + 崩溃恢复时明确标 discarded。
3. **子代理镜像投影**（tool-event-mirror）：子代理事件归自己的流、主时间线只收摘要镜像——当前 `_subFeed`/`_subBlk` 双处显示是它的雏形。
4. **两级 compaction**：管理 claude 长会话时在控制台侧模拟 microcompact 语义（折叠已结束的 Read/Bash 结果）。
5. **append-only 分支游标**（branchCut/branchGeneration）：做「编辑重发/回退」时照抄，避免删除竞态；与本期 epoch 换代机制同源可复用。
6. **delta 流式**：CLI 开 `--include-partial-messages` 后，流式类型进 `TRANSIENT_SESSION_EVENT_TYPES` 即激活回收机制（机制已预埋）。
7. **前端 keep-warm 会话层**（Map<sid,{dom,refCount,timer}> + 30s 延迟销毁）：当前 innerHTML 快照缓存（LRU 10）+ 滚动记忆已达成 UX 目标；全 DOM keep-warm 需重写 switchTo，收益/风险比暂不划算。

## 四、纪律（与 ZCode AGENTS.md 同款，本项目既有约定重申）

- 先更新 spec（本文/注释里的行为规格）再写代码；
- 状态唯一所有者：busy/turn 以 eventlog 投影为准，不再新加散落旗；
- bug 修复用中文注释说明原因与依据（含用户实测记录）；
- `py tools/architecture_check.py` 进 pre-commit（新增违规阻塞）。
