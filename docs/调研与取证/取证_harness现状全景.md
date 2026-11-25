# harness 全景地图（事实清单，不含重构建议）

> 2026-10-20 · v4 归一重构批前取证（Explore 子代理产出）· 对象为**重构前**的 v3.5.424 基线
> 代码根：`D:\AI\串口控制台Pro-子代理重构`。背景文档：`REBUILD-HANDOFF.md`（v3.5.420 交接+P0 清单）、`.hg-unify-plan.md`（单账游标制蓝图 394-400 + 404/408 收敛记录）。以下行号均为当期工作区实测。

## 0. 规模数据

**web\js\harness：28 个 JS，共 15,419 行**。最大 5 个：
| 文件 | 行数 |
|---|---|
| main.js | 2134 |
| subpane.js | 1612 |
| sse.js | 1302 |
| vcs.js | 1038 |
| panel.js | 939 |

**src\harness：20 个 py，共 9,144 行**。最大 5 个：routes.py 2152、session.py 1979、transcript.py 1035、roles.py 830、subagent_projection.py 596。
关联模块：`src/eventlog/`（7 文件 929 行：bus.py/store.py/log.py/reducer.py/truncate.py/types.py）是 SSE 事件账本底层（SessionBus:47、store.resume_mode:203、log.emit:45/subscribe:55/frames:61/bump_epoch:69）。

脚本加载序（web/index.html）：state → base → ask-md → groups → subblk → relay → hist → tools → fx → **sse → histcache → sessions** → panel → subpane → chatctl → input-fx → chips → managers → modal → main → shell → readonly → reducer → vcs → registry → fev → **store → skills**（store/reducer/fev/registry 在后面加载，靠函数提升+调用时序解耦）。

## 1. 前端模块职责表（web\js\harness\）

| 文件 | 行数 | 一句话职责 |
|---|---|---|
| main.js | 2134 | `buildClaudeHarnessTab` 主入口：DOM 拼装/事件绑定/交互委托/全局定时器（含 `_hgSubTailTick = setInterval(_subThinkPollTick, 2000)` **main.js:1387**） |
| subpane.js | 1612 | 子代理窗格体系：目录/动态/版本三个伪 tab + 实况/回放 tab；`_subEnsure` 唯一入口(:864)、`_subReplay` 铺底(:905)、tick 跟随轮询(:696)、`_subDeltaPing`(:1544) |
| sse.js | 1302 | SSE 客户端：`openSSE`(:962)/`handleEvent`(:2)/ack 三态(:973)/看门狗(:943)/快照清场 `_hgSseResetLocal`(:868)/`_hgSseRebuild`(:907)/`saveCache`(:1201)/方案B重渲(:727-835) |
| vcs.js | 1038 | 右栏「版本」伪 tab（git/svn 工作副本，调 /api/vcs/*） |
| panel.js | 939 | 会话动态页 `renderSideStatus`(rAF 合并)+子代理档案辅助：`_subReopen`(:203)/`_subDrop`(:306)/`_hgAgentsSweep`(:329)/`_hgAgentModelPre`(:199) |
| tools.js | 937 | 工具卡渲染：`hgToolCard` 合一构造(:582)、`renderToolUse`(:673)、`renderOneToolResult`(:731)、查阅聚组(:297-440)、diffHtml(:115)、agentline(:449-575)、后台任务卡(:854-937) |
| groups.js | 896 | 回合组结构：`grpEnsure`(:48)/`grpFinalize`(:366)/`renderUser`(:694)/`renderAsst`(:802)/`_hgTurnReopen`(:558)/`addRow`(:618)/`_hgEchoDup`(:786) |
| sessions.js | 853 | 切会话 `switchTo`(:76)（快照命中/冷开两路）、覆盖度审计 `_hgCoverageAudit`(:9)、`_hgBusyResync`(:67)、队列 UI(:701-823)、live 档案桶 `_hgLiveAgentsRestore`(:606) |
| relay.js | 644 | 杂项行渲染 raw/exit/switch/renew/audit/sysnote(:104-194)、识图卡(:201-355)、peer 转交线/回传(:356-601)、`_hgReloadFlow` 重渲(:17)、压缩线(:603) |
| chatctl.js | 621 | 会话列表/项目分组/搜索（renderList 族）与发送框控制 |
| ask-md.js | 568 | AskUserQuestion 面板 askRender/askDone + markdown 渲染 `renderMd`(:440)/`mdBubble`(:485) |
| hist.js | 539 | 回放行渲染 `renderHistLine`(:36)/`renderHistTool`(:2)/懒填(:205-269) + 思考段 startThinking(:328)/appendThinking(:469)/endThinking(:501)/滚播器(:416-468) |
| skills.js | 529 | 技能仓库全屏独立页（/api/skills/*） |
| histcache.js | 406 | **单账游标制核心**：`_hgRowAdd`(:7)/`_histPump`(:17)/`_hgMergeLive`(:29)/`_histRender`(:41)/`_histFetch`(:369)/`_histRefresh`(:386)/`_hgRplRebuild`(:336) |
| managers.js | 386 | 识图按钮 paintVisionBtn/上下文环/角色徽章等管理器 UI |
| reducer.js | 372 | 前端事件投影纯函数 `_hgReduce`（proj/entries 单一状态源）+ `_hgToolBadges`(:358) |
| readonly.js | 276 | 只读模式 RO_enter(:26)/RO_view(:126)/RO_exit(:197)，window.HgRO 导出(:276) |
| shell.js | 264 | harness 外壳/大会话 DOM 卸载（switchTab 换走时快照清空）/关 tab |
| base.js | 252 | 工具配置注册表 `_H_TOOL_CFG`(:62)/`_hCfg`(:115)/`_hToolIco`(:46)/`_hToolLabel`(:53)/`_H_KIND_COLOR`(:118)/`_HARNESS_IMG_EXT`(:141) |
| store.js | 204 | dispatch 管线：`_HG_STORE`(订阅/rAF 合并,:8)、`_hgRunFx`(:40)、`_hgRenderEntries`(:77,游标:76)、`_hgTurnWrapup`(:169)、`_hgDispatch`(:197) |
| fx.js | 174 | 活动指示条 actStart/busy 计时动效 |
| input-fx.js | 146 | @ 文件引用 mention 下拉/高亮 |
| registry.js | 138 | 子代理注册表消费层：`_hgAg` 单点解析(:29)/`_hgRegSync`(:44)/`_hgRegSyncSoon`(:128)（后端 /agents 为权威） |
| chips.js | 47 | 模型/cwd chip 辅助（fetchModels/_hgSaveCwd） |
| state.js | 43 | 跨文件共享全局（_hgWrap/_hgFlow/_hgInput/_HG 等 DOM 引用声明） |
| fev.js | 39 | FEV 事件模型目录（JSDoc 契约）+ `_fevUserFilter`（user 行过滤单一实现） |
| modal.js | 33 | 通用模态框 hgModal |
| subblk.js | 27 | 段体系退役幸存件：`_subToolHeadHtml`(:5)/`_toolInputBodyHtml`(:19) 共用工具行工厂 |

### 重点文件展开

**sse.js（SSE 事件入口）**
- `handleEvent(o)` :2 —— CLI stream-json 原始事件分发：system(:7-282, task_started/notification 建档收档 :21-255)、assistant(:283-491, thinking/text/tool_use 块)、user(:492-700, tool_result/识图回传/peer 回传/sysnote)、result(:701-858)。
- `openSSE(sid, afterSeq)` :962 —— EventSource `/api/harness/stream?sid=&after_seq=&epoch=`；ack 三态 resume/snapshot/reset(:973-1006)；`onmessage` seq 防重放(:1015-1017) + **397 seq 断档检测置 histStale**(:1022)；信封分发 user_echo(:1042)/event(:1058)/peer(:1074)/turn_hold(:1076)/turn_complete(:1080)/interrupted(:1124)/exit(:1166)/model_switched(:1184)。
- `subagent_delta` 入口 :6 —— `if (typ==='subagent_delta' && o.agent) { _subDeltaPing(o.agent); return; }`。
- 方案B：result 后 400ms `_histFetch`→`_histRender` 整窗重渲(:727-835)。

**store.js（dispatch/handlers）**
- `_hgDispatch(ev)` :197 —— FEV→`_hgReduce`（纯归约，产 fx）→`_hgRunFx`→`_HG_STORE.mark('proj')`。live 与 hist 同一入口。
- `_hgRenderEntries()` :77 —— entries 增量游标消费：renew/audit/raw/sysnote/model_switched/turn_exit/turn_interrupted/assistant_text/user_message(:110 三件套锚定 live)/peer_return(识图卡配对)/assistant_thinking(live 分形态)。

**histcache.js（histAll 账本 + _histPump 游标泵）**
- `_hgRowAdd(row)` :7 —— 唯一写入：push histAll + `row._sq=seq`(:10) + `histDirty=true`(:12, 工具行不入账导致脏账) + `_histPump()`。
- `_histPump()` :17 —— 从 `max(histCursor, histStart)` 渲染到账尾，推进 `histCursor=len`(:25)。
- `_hgMergeLive(lines, old, fs)` :29 —— fetch 版与旧账合并保尾。
- `_histRender(lines, start, opt)` :41 —— 整窗渲染器：20 回合窗口起点(:70-83)、HIST_CAP/段头回退(:86-93)、游离缓冲原子换入(:103-113)、`histCursor=len` 对齐+兜底泵(:322-325)、归档条(:302-317)、活组头秒表(:264-286)。
- `_histFetch` :369（busy 真值/lines_seq 水位存档）、`_histRefresh` :386（守卫满足走泵差量，否则整窗）。

**sessions.js（切会话/整窗重建）**
- `switchTo(sid)` :76 —— 清场块(:96-155, 含 histCursor=0 :109)、快照命中路(:230-503)：histFp 指纹校验(:282-288)、**切回有增长→游标泵差量(:345-352, R4 现行形态)**；冷开路(:504-560)：fetch→`_histRender`→phResume/覆盖度审计/busyResync。
- `_hgCoverageAudit` :9 —— hEnd 账目 vs 转写行数，gap>阈→`_hgReloadFlow` 自愈（频控 10min/3 次）。

**hist.js** —— `renderHistLine(l, hi)` :36 是回放行唯一分发：peer→dispatch(:71)、sysnote(:78)、vision_relay(:81)、exit(:86)、renew(:93)、audit(:100)、user→dispatch(:121)、assistant/thinking→dispatch(:128/:137)、tool→SendMessage 隐藏线(:145-164)+`renderHistTool`(:165)、sub_*→`renderHistSub`(:169-172)。`renderHistTool` :2 → **hgToolCard done 形态一次成型（徽章在内, hist.js:19-26）**。

**relay.js** —— `_hgReloadFlow` :17（keepDom 清场→fetch→_histRender→phResume）；`renderPeer` :493（401 信封静默 :495、识图卡分流 :574-584、`.h-sub-notify` 通知行、`.h-peer` 平铺已退役）；识图卡 `_hgVisionCardBuild` :221/`_hgVisionResult` :248。

**subpane.js / subblk.js（子代理窗格）**
- 目录伪 tab `__dir__`(:9)、动态 `__dyn__`(:17)、版本 `__vcs__`(:18)；`_subDirRows` :74（running/ended 两段+当天闸）、`_subDirPaint` :150、`_subDirRowClick` :203。
- 键归一 `_subTid` :375（tabs 直配→aidKey→tidMap）；来向消息 `_subUserQueue` :356/`_subUserInto` :411。
- **`_subEnsure(tid)` :864-881 —— 404 唯一入口**：tab 不在建壳→agentId 可得则 force+alive 铺底→未得挂起等 task_started 重入→已铺底零动作。
- `_subReplay` :905 —— fetch `/subagent_replay`→rows 重建时间线（多轮 user 切轮、final 行判死 :761 在 tick 内、铺底写 `tb.rpN` 与 tail 账本）。
- `_subTlTickStart` :696 —— 1s tick：活档案覆写复活(:710-716)、**无条件 follow 轮询（≥2.5s 节流：fetch replay→行数比对→有增 `_subReplayForce`；k:'final' 判死收口）**。
- `_subDeltaPing` :1544 —— delta 推送消费：`lastFollow=0` 打破节流 + 起 tick。
- `_subThinkPollTick` :1552 —— 2s 全局轮询：伪 tab 自愈（走 _subEnsure）+ `_subTailFeed`（单行卡摘要）。
- `_subClose` :1431 —— 完成收口 + **420：600ms 后强制行数校对（终稿必达）** :1453。
- ⚠ **`_subState` 在 subpane.js:1565 被调用但全仓库无定义**（见 §6 P0-3）。

### 前端调用关系图（文字版）
```
index.html 按序加载 28 文件（全局函数互调，无模块系统）
main.js buildClaudeHarnessTab ──┬─ 初始化 state.js 全局/DOM
                                 ├─ setInterval(_subThinkPollTick, 2s) [:1387]
                                 └─ 交互委托 → tools/groups/subpane 函数

【live 数据流】
sse.js openSSE ──EventSource──> /api/harness/stream
  ├─ onmessage: user_echo → _hgRowAdd(histcache) → _histPump → renderHistLine(hist)
  │     └─ renderHistLine → _hgDispatch(store) → _hgReduce(reducer) → _hgRenderEntries
  │           └─ → renderUser/renderAsst/startThinking/appendThinking(groups/hist)
  ├─ kind=event → handleEvent(sse)
  │     ├─ assistant text/thinking(主链) → _hgRowAdd（入账）
  │     ├─ tool_use(主链) → renderToolUse(tools) → hgToolCard(run) → _tlPlace（不入账，直挂 DOM）
  │     ├─ tool_result → renderToolResult(tools) → renderOneToolResult（回写 run 行徽章）
  │     ├─ Task/Agent tool_use → _HG.agents 建档 + _subEnsure(subpane)
  │     └─ task_started/task_notification → 档案生命周期 + _subClose/_hgAgentRowState
  ├─ subagent_delta → _subDeltaPing(subpane:1544) → tick follow → _subReplayForce
  └─ result → _hgTurnWrapup(store) + 方案B: _histFetch→_histRender(:761)

【fetch/切会话流】
sessions.js switchTo ─┬─ 快照命中 → _histFetch → histFp 校验 → 失配 _histRender / 增长 _histPump
                      └─ 冷开 → /transcript → _histRender(j.lines, winStart, noFinalize)
histcache._histRefresh（守卫）→ _histPump 或 _histRender
hist.js _histLazyFill（点开懒填，失配→_histRender）

【重渲/自愈流】
_hgCoverageAudit/_hgBusyResync → relay._hgReloadFlow(:17) → _histRender
sse._hgSseRebuild(:907) → /transcript → _histRender → openSSE

【子代理窗格流】
sse(tool_use/task_started) → _subEnsure(subpane:864) → _subReplay(:905, fetch /subagent_replay)
  → 铺底 rpN/size → tick 每 2.5s fetch replay 行数比对 → _subReplayForce
  → _subDeltaPing(推送触发) / _subThinkPollTick(main:1387 2s 兜底) / _subTailFeed(摘要)
panel._subReopen(:203)（目录点击/行卡）→ 解析漏斗 /subagent_resolve → _subReplay
registry._hgRegSync(:44) ← /agents 冷查询（F5/切会话/事件 2s debounce）

【渲染基元】groups(grpEnsure/grpFinalize/renderUser/renderAsst/addRow) + hist(思考段) +
tools(hgToolCard/diffHtml) + subblk(_subToolHeadHtml) + relay(杂项行/识图/peer)
+ ask-md(renderMd/mdBubble) ← 被上述所有路径消费
readonly(RO_*) 复用 _histRender/start=0；vcs/skills/chatctl/managers/chips/fx/input-fx/modal 为外围 UI
```

## 2. 当前数据流全景

### ① live 路径（SSE→构造行→入账→泵渲染）
1. 后端 `session._reader_loop`（session.py:1542）逐行读 CLI stdout → `emit`（session.py:1667）→ `SessionEventLog.emit`（eventlog/log.py:45，锁内 seq/截断）→ store→bus→SSE（routes.py:518 `/stream`）。
2. 前端 `openSSE`（sse.js:962）onmessage：seq 防重放+断档检测→按 kind 分发。
3. **消息行**（user_echo/assistant text/thinking）：`_hgRowAdd`（histcache.js:7）构造 `{role,text,ts,live:1,files,_sq:seq}` append 进 `_HG.histAll` → `_histPump` → `renderHistLine`（hist.js:36）→ `_hgDispatch`（store.js:197）→ `_hgRenderEntries` → `renderUser/renderAsst/closeRun+appendThinking`。live=1 打动画/滚播。
4. **工具行**：`handleEvent` assistant.tool_use → `renderToolUse`（tools.js:673）→ `hgToolCard({phase:'run'})` **不入账**（histcache.js:12 注释「工具行不入账（设计3）」），经 `_tlPlace`（tools.js:397）直挂当前组时间线。结果回写：user.tool_result → `renderOneToolResult`（tools.js:731）。
5. result 帧 → `_hgDispatch(turn_complete)` + `_hgTurnWrapup` + **方案B**：400ms 后 `_histFetch`→非 busy 则 `_histRender` 整窗换 hist 规整形态。

### ② fetch 路径
- `_histFetch(sid)`：GET `/api/harness/transcript`→`histAll = _hgMergeLive(j.lines, 旧账, j.lines_seq)`（保未落盘 live 行）。
- 快照恢复路：指纹 `_histPrefixFp` 校验→失配且 idle → `_histRender`；**有增长→`histCursor = DOM最大hEnd+1; _histPump()` 差量**。
- `_histRefresh`：`histLive && !histStale && !histDirty && cursor>0 && cursor<=lines.length` 才泵差量，否则 `_histRender` 整窗。

### ③ 整窗重建路径（`_histRender` 全部触发点）
| # | 触发点 | 位置 | 场景 |
|---|---|---|---|
| 1 | sse.js 方案B | sse.js:761 | 回合终 400ms 重渲规整形态 |
| 2 | `_hgSseRebuild` | sse.js:926 | ack=reset（/rewind 换代）重建 |
| 3 | 快照恢复指纹失配 | sessions.js:284 | histFp 不符/stale 哨兵（idle） |
| 4 | 冷开无快照 | sessions.js:524 | 首开/快照弃用 |
| 5 | `_hgReloadFlow` | relay.js:51 | 覆盖度审计自愈/busyResync/回滚后 |
| 6 | reload 失败重试 | relay.js:93 | 重渲异常兜底再拉 |
| 7 | 懒填点校验失败 | hist.js:230 | hi 错位对账 |
| 8 | 懒填 fetch 后失配 | hist.js:260 | 指纹校验分支 |
| 9 | `_histRefresh` 守卫不满足 | histcache.js:400 | 冷启动/降级/脏账 |
| 10 | RO_view 全量 | readonly.js:145 | 只读模式（start=0） |
| 11 | RO_exit 有增长 | readonly.js:245 | 退出只读补增长 |

### live 与回放行构造不同源的具体位置（P0-1 根）
- **消息行已同源**：live `_hgRowAdd` 入账→pump→`renderHistLine`→dispatch；hist 冷读同走 `renderHistLine`。区别仅 `live:1` 透传。
- **工具行仍双轨**：live= `renderToolUse`→`hgToolCard(phase:'run')`（tools.js:682，tslots 生而空 tools.js:633）+ `renderOneToolResult` 回写；回放= `renderHistTool`→`hgToolCard(phase:'done')`（hist.js:19-26，**徽章+懒体一次成型**）。
- **live MCP 完成徽标缺失的精确代码**：`renderOneToolResult` tools.js:763 —— `if (slots && st !== 'completed') slots.innerHTML = statusBadge(st);`（完成态刻意不写徽章防噪）；agent 类完成徽章在 :767-772 有单独分支，**非 agent 的 MCP 工具完成后 live 徽章无任何写入点**——只有等方案B/切回重渲后由 done 形态补上。

## 3. 后端模块职责表（src\harness\）

| 文件 | 行数 | 一句话职责 |
|---|---|---|
| routes.py | 2152 | Blueprint `/api/harness/*` 全部 HTTP/SSE 路由（含 /stream :518、/transcript :588、/agents :1213、子代理三接口 :788/:867/:1016） |
| session.py | 1979 | `HarnessSession`（:29）：进程 start/kill/revive、`_reader_loop`(:1542) 事件泵、busy/hold(:1598-1690)、审计结算(:534)、排队泵(:1067)、peer 回传检测(:1411)、`emit`(:1854) |
| transcript.py | 1035 | 转写落盘格式与解析：`transcript_for`(:106) 产 lines、子代理段注入 `_inject_subagent_blocks`(:903)、回放 rows `_subagent_rows_from_jsonl`(:676)、三源候选(:842)、中断痕迹 trace(:49) |
| roles.py | 830 | 三档形态（light/mid/heavy）角色定义、引导词、agents 安装、审计线/设计线判定 |
| subagent_projection.py | 596 | 子代理冷查询投影纯函数：`collect_main_facts`(:88) 主 jsonl→事实表、`child_outcome_from_tail`(:184) 尾探终局、`project`(:320) 状态判定链（RUNNING1~3/ENDED1~4 :536-595） |
| vision_mcp.py | 479 | 识图 MCP server（stdio，本地兜底 analyze_image） |
| vision.py | 415 | 识图配置读写/多模态判定/peer 注册清理 |
| subagent_readmodel.py | 279 | 冷查询读模型（IO 层）：主 jsonl 水位增量吸收(:135)、子代理尾探、meta.json 父子链接、投影缓存；`get_model`(:273) 每会话一只 |
| ask_mcp.py | 246 | 交互提问 MCP server（ask_user 长轮询） |
| audit.py | 233 | 审计记账常量/警示卡落盘/回放读回 |
| bridges.py | 169 | 系统提示词引导段（TOKEN_RULES/识图/ask/confirm 桥文本+指纹） |
| lifecycle.py | 124 | `_get_or_create`(:18)/GC 线程(:59)/`_ensure_gc`(:80, **watcher 启动唯一挂点 :86-90)/peer 轮询线程(:95) |
| audit_hook.py | 104 | PreToolUse 事中闸 hook 进程（调 /audit_gate） |
| meta.py | 99 | claude_harness.json 元数据读写 |
| prompts.py | 78 | 用户自定义系统提示词 |
| consts.py | 72 | 共享常量（_sessions/_sessions_lock/上传目录等） |
| askmcp.py | 65 | ask+vision MCP 的 --mcp-config 配置文件生成 |
| models.py | 46 | available_models（settings.json 解析） |
| __init__.py | 20 | 包入口（HARNESS_VERSION） |

### 重点展开

**transcript.py（转写落盘格式）** —— `/transcript` 返回的 line 形态（`transcript_for` :106）：
- `user`：`{role:'user', text≤8000, ts, images:<int 计数>, files:[路径]}`（**images 是计数数字**——:367-368；files 从附件行剥出）。
- `assistant`：`{role:'assistant', text, ts, model}`；`thinking`：`{role:'thinking', text, ts}`。
- `tool`：`{role:'tool', text:<工具名>, summary, input, result, tid, ts}`；Edit 行由 routes `_dln_inject` 注入 `dln:[真实行号]`。
- 特殊行：`renew`/`sysnote`/`peer`/`vision_relay`(:464-471, prompt/src/tid/chan/dur)/`exit`(:511, 来自 harness_trace.jsonl)。
- 子代理注入：`_inject_subagent_blocks`(:903) 在 Task/Agent 派发行后插 `sub_open/sub_text/sub_think/sub_tool/sub_result/sub_note`（最近 3 段全量，其余 stub）；`_subagent_rows_from_jsonl`(:676) 头 150+尾 50 窗口，顶层 result 行透出 `k:'final'`。
- 三源候选 `_subagent_transcript_candidates`(:842)：① projects/<proj>/<agentId>.jsonl ② %LOCALAPPDATA%\Temp\claude\<proj>\<csid>\tasks\<id>.output ③ projects/<csid>/subagents/agent-<id>.jsonl。

**session.py** —— `emit` :1854 是事件唯一出口（截断→锁内 seq→store→bus）；`_reader_loop` :1542：init#2 起补 busy、result 时 hold 分流（turn_hold 先于 result，真收尾 emit turn_complete）；`_check_peer_lines` :1411 转写尾扫 peer 回传 emit kind:'peer'；`_emit_task_mirror` :1175 产 subagent_started/subagent_result 镜像；`stale_hold_repair` :1379 跨进程孤儿 hold 对账；排队泵 `_queue_pump` :1067（800ms 延迟/3s 重试/世代作废）。

**subagent_watch.py（watcher 推送）** —— 全局单线程 daemon `_watch_loop`(:48)：每 1s 扫 mtime<120s 的子代理转写文件，按内存 `_offsets` 读整行增量（256KB 上限），经 `_session_for`(:39, lineage 匹配 csid) 定位会话后 `s.emit({kind:'event',data:{type:'subagent_delta',agent,offset,text}})`。`ensure_started`(:117) 由 lifecycle._ensure_gc(:86-90) 调用，而 `_ensure_gc()` 全仓唯一调用点= **routes.py:51（/connect 路由内）**——后端重启后若前端从未调 /connect，watcher 不在跑。原版只扫源③（subagents 目录），源②（tasks 目录）不扫。

**subagent_projection.py / subagent_readmodel.py（冷查询投影）** —— `/agents`→`get_model(sid).refresh(s)`：主 jsonl 按字节水位增量吸收成事实表（缩水即全清）、meta.json toolUseId 父子链接、候选尾探（mtime/size 门控）→ `project` 现算 `{agents, tidMap, rev}`。状态链：RUNNING1 转写新鲜 / 1b 尾探 mid_flight+新鲜 / 2 bg 无终态证据+进程活 / 3 前台无 result+busy；ENDED1 notify / 2 前台 result / 3 尾探终局 / 4 证据不足。

## 4. 后端接口清单（/api/harness/*）

| 路径 | 方法 | 用途（行号） | 前端调用方 |
|---|---|---|---|
| /connect | POST | 新建/复活会话；**_ensure_gc 挂点 :51** | main.js 建会话/切回 |
| /send | POST | 发消息 :145 | chatctl send |
| /interrupt | POST | 中断（杀进程）:166 | 停止按钮 |
| /kill | POST | /exit 退出进程 :178 | 输入框命令 |
| /rewind | POST | 回退回合/消息级回滚（bump_epoch）:327 | 回滚按钮 |
| /stream | GET(SSE) | 事件流 subscribe(base) 三态 ack :518 | sse.js openSSE:970 |
| /events | GET | 轮询兜底+epoch 校验+proj 种子 :1190 | sse.js `_hgEventsPoll`:1291 |
| /transcript | GET | 历史行（lines/seq/lines_seq/busy/epoch）:588 | histcache/sessions/relay/readonly 等 |
| /sessions | GET | 会话列表 :551 | sessions refreshSessions、readonly |
| /queue, /queue_act | GET/POST | durable 排队账本 :379/:404 | sessions queuePush、store fx |
| /ctx | GET | 上下文用量 :445 | managers 上下文环 |
| /set_model | POST | 会话内切模型 :461 | chips 模型下拉 |
| /rename, /delete | POST | 改名 :1239 / 删会话 :1254 | chatctl 列表操作 |
| /recoverable, /recover | GET/POST | 孤儿会话扫描/找回 :1386/:1398 | chatctl 恢复入口 |
| /diff_lines | POST | Edit diff 真实行号定位 :690 | tools `_hgDiffLineFix` |
| **/subagent_replay** | GET | 子代理转写回放 rows（含 size）:788 | subpane `_subReplay`、tick follow |
| **/subagent_tail** | GET | 子代理转写增量尾读 :1016 | subpane `_subTailFeed` |
| **/subagent_resolve** | GET | tid→agentId 解析漏斗 :867 | subpane/panel 回放入口 |
| **/agents** | GET | 子代理冷查询投影（唯一权威）:1213 | registry `_hgRegSync` |
| /peer_pair_log | POST | 回传配对审计 :1088 | sse.js:248 |
| /peer_result_check | GET | 转交线转写核实 :1106 | relay |
| /audit_gate | GET | 事中闸判定 :740 | audit_hook.py |
| /ask/reply, /ask/poll, /ask/answer | POST | 交互提问登记/长轮询/作答 :86/:103/:129 | ask_mcp/ask-md |
| /models, /agent_models | GET | 模型清单 :1446 / 子代理类型→模型 :1777 | chips、panel |
| /mcp_list | GET | 代跑 claude mcp list :1458 | 输入框 /mcp |
| /vision_status, /vision, /mm_probe | GET/POST | 识图形态/配置/探测 | managers、识图面板 |
| /system_prompt | GET/POST | 自定义提示词 :1533/:1569 | 设置面板 |
| /roles | GET/POST | 三档角色配置 :1736/:1817 | managers/面板 |
| /version | GET | harness 版本 :1722 | 关于/诊断 |
| /skills, /skill_zh/translate | GET/POST | 技能列表/LLM 汉化 :1892/:1992 | skills.js |
| /files | GET | @ 引用候选 :2021 | input-fx |
| /upload, /file | POST/GET | 附件上传/原件回源 :2073/:2108 | 输入框附件、chips |

## 5. 子代理数据流现状（404/408 收敛后的形态）

**后端检测→推送链（405 建，P0-3 未实证）**：
1. CLI 落盘子代理转写（三源形态，transcript.py:842）。
2. `subagent_watch._watch_loop`（1s 扫新鲜转写，offset 增量）→ `s.emit({kind:'event', data:{type:'subagent_delta', agent, offset, text}})` → SSE `/stream` 下发。
3. watcher 启动链：`routes./connect:51` → `lifecycle._ensure_gc:80` → `subagent_watch.ensure_started:117`。**后端重启后若前端从未调 /connect，watcher 不在跑**。
4. 会话归属：`_session_for` 按 lineage 匹配，miss 即跳过（不推送）。

**前端管道**：
- `sse.js:6`：`subagent_delta` → `_subDeltaPing(agent)`。
- `_subDeltaPing`：tab 存在且未定稿且非 replay → `lastFollow=0`（打破 2.5s 节流）+ 起 tick。
- tick（1s）：活档案覆写复活 → follow 轮询 `fetch /subagent_replay` → 行数比对 → 有增才 `_subReplayForce`（**全量重建**）→ `k:'final'` 尾行判死收口。
- 兜底：`_subThinkPollTick`（2s）——伪 tab 自愈 + `_subTailFeed` 单行卡摘要。
- **⚠ 本轮新发现的硬事实（P0-3 直接相关）**：`_subState(tb)` 在 **subpane.js:1565 被调用但整个仓库无定义**。`_subThinkPollTick` 的 for 循环在第一个真实子代理 tab 上即抛 ReferenceError（未被 try 包裹），**整个 2s 兜底 tick 自此中止：404/408 自愈防线与 `_subTailFeed` 摘要轮询在有窗格 tab 打开后全部失效，console 每 2s 报未捕获 ReferenceError**。408 应落地的三态（shell/live/final）在代码中不存在——该函数在 408 之后的某次改动中丢失或从未落盘。

## 6. 已知问题定位（REBUILD-HANDOFF P0/P1/P2 的代码现状）

**P0-1 live MCP 工具行无完成徽标**
- live 构造：`renderToolUse` tools.js:673 → `hgToolCard({phase:'run'})` → tslots 生而空（tools.js:633 `${done ? statusBadge(...) : ''}`）。
- 结果回写：`renderOneToolResult` tools.js:731；**徽章写入被 `st !== 'completed'` 门拦住（tools.js:763）**——completed 刻意不写（防噪设计），仅 error/denied 写；agent 类完成徽章有独立分支（:767-772）。
- 回放构造：`renderHistTool` hist.js:2 → done 形态一次成型（hist.js:19-26）。
- 结论（事实）：非 agent 类工具（含全部 MCP）live 完成徽章无写入点；徽章只能由方案B/切回重渲补上。**根因位置=tools.js:763 + 工具行不入账（histcache.js:12）**。

**P0-2 live/重渲双渲染动作未归一**
- 泵差量：`_histPump` histcache.js:17-26；整窗：`_histRender` 现存触发点 11 处（见 §2③ 表）——比 HANDOFF 所记「三类」多出方案B/RO/_histRefresh 守卫/懒填对账/重试等。
- R4 冲突现场：切回有增长走泵保留流式残态（sessions.js:345-352），204b 的「切回必重渲」仅在注释中留有一行改回指引。

**P0-3 watcher 推送链未实证**
- 后端链完整在码，但无任何启动/推送计数日志（watcher 内仅异常静默）。
- 启动挂点唯一：routes.py:51（/connect）；lineage 匹配 miss 即静默跳过；前端消费闸（tab 不在/已定稿/replay 中即丢弃，无计数留痕）。
- **新增事实：兜底轮询 `_subThinkPollTick` 因 `_subState` 未定义在第一个真实 tab 后整体死亡**；反之 watcher 失效时窗格跟随只剩 tick 内 follow 轮询（不受该 bug 影响）。

**P1-1 bash 失败行「换行」**：err 徽章写入 tools.js:763 + failmark 追加 tools.js:784-797 + 错误体升级 tools.js:806-820——高度变化的候选位（无截图，仅定位）。

**P2 readonly openSSE 错位**：readonly.js:260 `openSSE(anchor, _HG.fetchedSeq || _HG.seq)` 位于 `_histFetch(anchor)` 的 .then **之外**同步执行——而其上方注释（:257-259「B组P1：openSSE 移入 fetch.then」）与代码不一致；RO_enter 的 resetLocal 已把 `_HG.seq=0`，此处水位取的是陈旧 fetchedSeq 或 0，会触发 ack=snapshot 清场重放（与注释描述的修复意图相反）。

**P2 emit-after-flush 次序残差**：transcript 接口已带 `lines_seq` 读窗前水位，前端 `_hgMergeLive` 按其保尾——「彻底闭合需后端随 lines 返回 flushed 水位」仍为遗留状态。

## 7. 补充事实（重构需知的地雷清单，纯事实）

1. **`_subState` 未定义**（subpane.js:1565）——见 §5/§6，当前活 bug。
2. 工具行不入账是显式设计（histcache.js:12-14「设计3」），由此派生 `histDirty` 脏账守卫（histcache.js:397）与方案B整窗校正。
3. `images` 字段前后端口径：后端=计数 int（transcript.py:367-368）；前端 live 入账曾用 images+files 双字段致 407 修复。
4. dist/前端控制台_debug 内有同源构建副本（含同样的 `_subState` 使用），重构时勿改 dist。
5. `_HG_ENVELOPE_TAKEN`（sse.js:959）列出 FEV 已接管的信封 kind——dispatch 与 legacy 分派双轨并存（store.js:196 注释「分批收编」）。
6. 回滚/换代协议：`/rewind` → `s.log.bump_epoch()` → 前端 ack=reset → `_hgSseRebuild`；分支世代 `_gen` 作废旧队列。
7. 会话删除同步回收 readmodel（routes.py:1261-1268）。
8. `_peer_poll_loop`（lifecycle.py:95）只扫「有 SSE 订阅者」的会话。
