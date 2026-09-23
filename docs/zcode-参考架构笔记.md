# ZCode 参考架构笔记

> 源码位置：`D:\AI\FrontendHarness\ZCode`（zai-org/ZCode 浅克隆，2026-09-23）。
> 本文是对其工程的分析与「可抄清单」，供本项目（前端控制台 Pro：Flask + SSE + 原生 JS + pywebview）后续实施对照。
> 三份侦察报告（core / 前端 / 服务协议）含完整文件:行号指针，行文中的路径均相对仓库根。

## 总评

ZCode 是「Claude Code 的 GLM 同构实现」（~30 万行 TS），架构核心是**事件溯源**：一切运行时动作铸成带
`sessionId / turnId / sequenceNumber / traceId` 的 SessionEvent，先落 eventStore 再广播 eventSinks，
UI 状态由 EventReducer 归约事件得到。本项目已独立做出多处同构设计（滚动窗口分段加载 ≈ snapshotTailWindowRows、
v2.57 的 rp 过渡查重 ≈ coalesce/区间记账、审计闸 ≈ permission 事件链）——方向一致，差距在系统性。

## 一、立即可抄（低成本高收益）

| # | 机制 | 本项目痛点 | 抄什么 | 关键参考 |
|---|---|---|---|---|
| 1 | SSE 事件信封统一 | 事件 kind 散落字符串，断线续传字段弱 | 信封统一 `{seq, sessionId, turnId, type, timestamp, payload}`；type 常量清单集中管理（约 80 个事件一个文件） | `apps/zcode-cli/packages/contracts/src/events/session.events.ts:83` |
| 2 | logEpoch + subscribe(base) 断点续传 | 压缩/重写后旧 seq 失效无解 | 每会话 logEpoch（日志重写即更换）；重连带 `{epoch, seq}`：同 epoch 续 delta，不同发 snapshot 重建 | `packages/shared/src/zcode-protocol-v4/transport.ts:84` |
| 3 | 流式/完成双渲染路径 | 流式中仍跑 md 渲染与高亮 | 流式期间纯文本追加（pre-wrap），完成信号后一次性 renderMd 替换 + try/catch 降级纯文本 | `packages/ui/src/components/ai-elements/reasoning.tsx:559`（注释明说流式逐 chunk 跑 Markdown 越来越卡） |
| 4 | 工具输出协议层截断 | 各处散着 slice(2000) | 后端出口统一「头尾各 32KB」，UI 永不收大块 | `packages/shared/src/zcode-protocol-v4/core.ts:64` |
| 5 | 会话切换 keep-warm + 滚动记忆 | 切会话 DOM 清空重建、滚动位置丢 | `Map<sid, {dom, scrollTop, wasAtBottom}>` + 引用计数归零后 30s 延迟销毁；内容不足时挂起恢复意图，行到齐再落地 | `packages/ui/src/v4/sessionDataLayer.ts:72`、`ConversationTimeline.tsx:1438` |
| 6 | 代码高亮缓存池 | hljs 懒加载但无缓存 | `highlight(code)` 按 (lang, theme, 内容指纹) 做 Promise 缓存池；屏幕外代码块 `content-visibility: auto` | `packages/ui/src/lib/shikiHighlighter.ts:56`、`code-block.tsx:159` |
| 7 | UI token 化 | CSS 裸值 | 单根变量 `--ui-font-size` + calc 派生六级字档；语义色分层（文本三级/表面五级/diff 色独立）；主题=换 class | `DESIGN.md`、`packages/ui/src/styles.css:57,142` |
| 8 | SSE 心跳/判死参数 | 无心跳 | 5s keepalive、20s 无 ACK 判死；重放缓冲设上限，超限发明确 `event: reset` 让客户端走 snapshot | `packages/rpc/src/persistent-protocol.ts:77-81` |

## 二、中期架构级（一次一个）

9. **事件溯源投影**：会话状态全部由事件流 reduce（live/replay/snapshot 共用同一 seq 事实源）——打通断线
   续传、审计重放、崩溃恢复。配套「turn 窗口瞬态事件回收」控制多会话长跑内存
   （`apps/zcode-cli/packages/contracts/src/events/session-event-retention.ts`）。
10. **durable 输入账本**：排队输入先记账（admitted）再消费（promoted），两步同事务；崩溃后未 promoted 的
    输入明确标 discarded（`session-store.port.ts:843-867, 1162-1181`）。本项目「子代理执行中排队」已有雏形。
11. **架构治理 policy**：照根目录 `architecture-policy.yaml` 做 Python 版——声明式 import 白名单 + 唯一公开
    入口 + pre-commit 对 changed 文件校验 + 存量违规 baseline 豁免（import-linter 可实现）。
    两条纪律直接写进项目约定：「先更新 spec 再写代码」「状态唯一所有者、不用超时掩盖同步问题」。
12. **子代理镜像投影**：子代理事件落自己的会话流，父时间线只收摘要级镜像（工具 started/result + agentId 锚点，
    id 重映射 `tool_subagent_<agentId>_...`）——本项目子代理段与主窗关系的规范化版本
    （`core/src/subagent/tool-event-mirror.ts:19-99`）。
13. **两级 compaction**：先无模型 microcompact（旧工具输出清空，阈值×0.9、最少省 256 token）再上模型摘要；
    CompactBoundary 事件带 pre/post token 与保留游标（`core/src/compact/`）。管理 claude 长会话时可在控制台
    侧模拟 microcompact 语义（折叠已结束的 Read/Bash 结果）。
14. **append-only 分支游标**：回滚/重试不删消息，只挪 branchCut 游标并递增 branchGeneration，迟到旧分支结果
    按 generation 丢弃（`session-store.port.ts:277-294`）——做「编辑重发/回退」时照抄避免删除竞态。

## 三、不建议照抄（装备前提不同）

- 四层 RPC + 二进制帧 + NDJSON stdio 多级协议（Flask+SSE 单进程，信封+seq 已够）；
- SQLite Part 级转写存储（claude CLI 的 jsonl 格式不可选，只能侧路解析）；
- React/zustand/turn 级虚拟化全套（原生 JS 小面板，`content-visibility: auto` 一行 CSS 拿大头）；
- Electron/远程 workspace（串口场景不同；SSH Backend 抽象 + 行式 JSON 握手（跳 banner、失败带两侧诊断尾
  2048 字符）对设备连接有参考价值）。

## 四、已验证的同构设计（本项目已独立做出，无需重做）

- 滚动窗口分段加载 ≈ snapshotTailWindowRows（60 行尾窗 + 向上分页拉取）；
- v2.57 rp 过渡查重 ≈ coalesce/区间记账（(fromSeq,toSeq] 区间 + 前缀比对）；
- 审计闸 ≈ PermissionRequested/Resolved 事件链 + requestId 幂等应答；
- CommandInbox 串行 admission ≈ 「子代理执行中继续输入将排队」。

## 五、工具行/思考展示细节（v2.57 工具气泡的后续优化对照）

- 折叠默认值由**数据层**算好（running→展开、出最终答复→收起、中断→强制展开），不在点击时翻布尔；
- 收起 ≠ 立即卸载：延迟 300ms 卸载内容 DOM（等高度过渡）；展开先挂载再播动画；
- 思考流式时渲染纯文本，结束后升级 Markdown；流式摘要 = 最后一非空行；
- diff 先渲染纯文本行（+/− 着色），异步补高亮；重型 diff 库只进全屏查看器；
- 入场动画只播一次（模块级 Map 记 id，上限清理）。

## 六、工程纪律三件套（根目录文档本身即范本）

- `AGENTS.md`：面向 agent 的仓库纪律——「先更新 spec 再实现」「状态唯一所有者、事件顺序、幂等边界，
  不用超时掩盖同步」「bug 修复用中文注释说明原因与依据」（本项目已有同款）；
- `DESIGN.md`：给 agent 看的设计系统，最高优先级约束置顶并声明「违规按缺陷处理」；
- `architecture-policy.yaml` + `scripts/architecture/`：声明式架构治理（模块依赖白名单 / 唯一公开入口 /
  分层顺序 / owner），pre-push 对 changed 文件机器校验，存量违规走 baseline 豁免。

## 优先级建议

先做 1+2+4（事件信封/断点续传/截断，纯后端一周量级）→ 再做 3+5+6（前端渲染三件套）→ 7/8 随手 →
9-14 按痛感排期。
