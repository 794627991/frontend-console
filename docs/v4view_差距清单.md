# v4view ↔ V3 形态差距全清单（2026-10-20 首轮实测取证）

> 用户结论：V4 界面「相当于完全无法使用的程度」。本文档 = 差距作战图，逐项对齐后才可再灰度。
> 实测环境：run_debug_v4.bat（a13/a14），会话=重构（407 行投影，13 user/84 asst/工具卡近百）。

## P0 交互断裂（不可用级）

| # | 问题 | 实测证据 | V3 形态 | 修法方向 |
|---|---|---|---|---|
| 1 | **AskUserQuestion 渲染成原始 JSON 卡** | 工具卡抽检：`🔌 {"questions":[{"header":"切换方式"...` 直接裸奔 | askRender 交互面板：问题卡片+2-4 可点选项+提交+倒计时+ask_done 定格 | v4view 对 tool=='mcp__harness__ask_user'/AskUserQuestion 走 askRender/askDone 管线（ask-md.js 复用）；running 态画面板、终态画已选结果 |
| 2 | 无 header 组假秒表「工作中 6时10分」 | paintHead 无 hdr 默认 running | 「已工作 Xs」 | a14 已修（hydration 建 t1 header + 无 hdr 强制 success），**待刷新验证** |

## P1 形态错误（观感级，待逐项核验）

| # | 疑点 | 现状 | 核验方法 |
|---|---|---|---|
| 3 | 识图卡形态 | visionCards=4 存在，形态未对比（V3=识图卡：图缩略+prompt+结果定格+点开） | 截图对比 |
| 4 | 子代理行卡 | peerRows=2（V3=.h-sub-notify 通知行+点击开窗格）；子代理窗格 v4 分支未实测 | 派一个子代理实测 |
| 5 | 工具卡「🖊 0」类怪头 | 疑似个别工具 cfg.get/title 返回异常；主流卡（Bash/Read/Write）形态已验正常 | 全量工具卡 name+arg 抽查 |
| 6 | sysnote 行 | 1 条在场，形态未对比 | 截图 |
| 7 | marker 行（renew/audit/exit/interrupted） | 未实测（本会话可能没有） | 构造场景 |

## P2 交互链未验证（V3 全量功能域，v4 下逐一点名）

- [ ] 中断/停止按钮（busy 态）
- [ ] 回滚到此处（h-macts 的回滚锚）
- [ ] 复制/重发/编辑后重发（dataset.rtext/ratts 委托）
- [ ] 长消息折叠展开（longfold/hgFold）
- [ ] 排队条（queue UI 增删改排）
- [ ] 子代理窗格全链（目录/实况/回放/结论区）
- [ ] 只读模式进出（RO_enter/exit 与 v4 store 协作）
- [ ] 思考段 live 滚播/展开裁切（419/422 的教训区）
- [ ] 上下文环/工时/活动指示条（fx）
- [ ] 附件 chips/缩略图/Lightbox
- [ ] 时间条（_maybeTimeBar 微信式）
- [ ] @ 文件引用 mention
- [ ] 模型/cwd chip 切换
- [ ] 会话切换往返完整性（快照/冷开两路）
- [ ] 后端重启恢复（hydration/补放去重实测）
- [ ] rewind 回滚换代（epoch/bump）

## 架构纪律（修时必守）

1. 渲染问题一律在 v4view.js 内解决（设计文档 §8.2），禁止回调旧基元（renderUser/grpEnsure 族）。
2. 纯叶子可复用白名单：mdBubble/plainBubble/attChipsHtml/hgToolCard/statusBadge/esc/openLightbox + **ask-md 的 askRender/askDone（待评估纯度）**。
3. 每修一项必须 V3↔V4 同屏对比验证（截图级），不许「应该对了」。
4. 修完 P0+P1 全部 + P2 逐项打勾后才可再灰度（run_debug_v4.bat）；期间日常用 run_debug.bat（V3，一行未动）。

## 已验证正常（不必重查）

- 历史渲染完整性（407 行全渲染，13 user/84 asst）
- 主流工具卡形态（Bash 命令全文/Read 文件路径/Write 文件名+arg）
- 思考段默认折叠（CSS max-height:0，.open 才展开；live 流式段展开=正常）
- 用户气泡右对齐（right 统一 1304）
- 滚动贴底（scrollTop 17707/18395 贴底状态）
- 贴底跟随/上翻打断（stickBtm 语义）
- subagent/peer/sysnote/vision 行存在性
