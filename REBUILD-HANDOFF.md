# 重构交接文档（2026-10-20，v3.5.420，分支 refactor/subagent-registry）

> 用户拍板换会话重构。本文档 = 当前架构现状 + 全部未决问题（含根因线索）+ 修复优先级。
> 配套文档：`.hg-unify-plan.md`（单账制蓝图+404/408 收敛记录+ZCode 九机制报告结论）。

## 一、两图对比结论（用户提供的实证）

- **图 7（c2f720fa）= 已完成会话回放态**：MCP 工具行（🔧 devtools_eval）**带「完成」徽标** ✓
- **图 6（8198b368）= 正在执行的 live 会话**：同款 MCP 工具行**无任何徽标** ✗
- **结论：live 路径的 MCP 工具结果不回写徽章，重渲/回放后有**——live/重渲两套渲染的又一实证（用户"live 归一没归彻底"的指控成立）。

## 二、未决问题清单（按致命级排序）

### P0-1 live MCP 工具行无完成徽标（图 6/图 7 对比）
- 现象：live 会话中 MCP 工具（🔧 emoji 图标的行，如 devtools_eval）完成后头部右侧无徽章/耗时；同会话的 Bash/查询行有。
- 线索：renderOneToolResult（tools.js ~:754）写 `slots.innerHTML=statusBadge(st)` 应对任意行生效——疑点：①MCP 行的 `row._grouped` 判定（查阅聚组 `_HG_EXP_MCP_RE` 只收 codegraph_explore，devtools 不匹配，不应分组）②MCP 工具名 `mcp__devtools__devtools_eval` 在 `_H_TOOL_CFG` 无配置 → cfg 兜底路径 ③tool_result 的 content 结构非标准 text 块导致 renderOneToolResult 早退 ④**live 与回放的行构造不同**（回放走 hgToolCard done 形态带徽章，live 走 run 形态靠 result 回写——result 回写链对 MCP miss）。
- 取证起点：devtools 现场对比 live MCP 行与回放 MCP 行的 DOM（slots 内容/rowById 查找）。

### P0-2 live/重渲双渲染动作未归一（用户明确要求"动作也归一"）
- 现状：账本已单一（histAll 唯一+游标泵 _histPump），但渲染动作两种：游标泵差量 + 整窗重建 `_histRender`（保留三类：首建窗/指纹失配/切回自愈）。
- 用户拍板记录（本会话末）：要求**彻底归一**（消灭整窗，全部走泵）。这是大改造：切会话（switchTo）/自愈路径全改差量。**注意 R4 裁定项**（.hg-unify-plan.md:65）：切回有增长当前走泵保留流式残态，用户曾定调 204b 整窗重渲——本次"动作归一"与 204b 冲突，需用户再确认最终形态。
- P0-1 是本项的子症（live 行构造与回放行构造不同源）。

### P0-3 子代理窗格实时刷新（watcher 推送链未实证）
- 405 建的链：后端 subagent_watch.py watcher（1s 扫新鲜转写→emit subagent_delta）→ SSE → _subDeltaPing → follow 立即重建。
- 未实证：watcher 线程真在跑（_ensure_gc 挂点 routes.py:51）；_session_for 的 lineage 匹配是否命中；delta 事件是否真到达前端（console 无 [subagent_delta] 日志）。
- 取证：后端 log 加 watcher 启动/推送计数；前端 sse handleEvent 的 subagent_delta 分支加临时计数。

### P1-1 bash 执行失败行"换行"/高度变化（用户 419 记录的问题②前半）
- 现象描述不完整（无截图），疑点：err 徽章+耗时写入 slots 后头部行变高换行。
- 待用户截图取证。

### P1-2 工具卡折叠 CSS 三修教训
- 416 用 max-height: 0→60vh（406 grid-auto-rows 不折叠 / 411 min-height:0 塌陷两轮返工）。
- **纪律：CSS 新特性等价性必须 devtools 实测 computed height 再提交**。

### P2 遗留
- readonly.js:257 openSSE 调用位置与注释错位（零量级，reviewer 存档）
- emit-after-flush 次序残差（彻底闭合需后端随 transcript 返回 flushed 水位）
- 命令摘要超宽无省略号（识图右缘截断问题，未修）
- reviewer 窗格空问题的幻影档源头已修（418），但真档窗格「任务书+工作中」到终稿的过渡体验未验证

## 三、近期修复链（384-420，供回溯）

384/392（账本写回事故+回退）→393 对账补画→**394-400 单账游标制**（live 入账+泵渲染+seq 断档检测，全审三轮 FAIL→PASS）→401 SubagentHandback 信封五重静默→402/403 窗格冻死自愈+首铺接链→404 _subEnsure 唯一入口→405 watcher delta 推送→406-416 工具卡折叠三修+行高/徽章/图渲染系列→417/418 嵌套帧守卫（417 无效，418 补 owned_by_subagent/parent_task_id 真标记）→419 思考展开动画→420 终稿差量必达（done 后 follow 闸关=终稿永不渲染）。

**全诊报告关键结论存档**（reviewer a6fc21ceecb24a67c，本人即当事子代理）：
- 嵌套 system 帧真实标记 = `owned_by_subagent:true + parent_task_id + task_type:"local_*"`（非 assistant 帧的 parent_tool_use_id）
- 转写行 images 字段 = **计数数字**（transcript.py:367），非路径数组
- ack=snapshot 清场必须置 seq=0 否则保留窗重放帧全被 seq 门吞（418 已修）
- 部署纪律：改 sse.js 必须强刷页面+重启后端再验（406-417 多轮修在未刷新旧页上白烧实测）

## 四、重构建议起点

1. 先修 P0-1（live MCP 徽章）——它是 P0-2 双渲染最外显的伤口，取证即知 live result 回写链断在哪
2. P0-3 watcher 实证（加日志半小时的事）
3. P0-2 动作归一前必须与用户确认 R4 最终形态（泵差量 vs 整窗重渲）
4. 架构现状详见 .hg-unify-plan.md（ZCode 九机制对位+三层收敛记录）
