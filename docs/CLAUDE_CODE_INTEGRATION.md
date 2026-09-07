# 集成 Claude Code 设计方案（路线 A+C）

> 定稿：2026-09-05。路线决策：**内嵌终端跑真实 claude CLI（xterm 保真）+ 旁路状态面板**。
> 参照项目：claudecodeui ★13.6k（node-pty+xterm 同款技术栈）、ccstatusline ★12.8k（statusline+transcript 状态感知）、claude-run ★670（~/.claude 会话列表 UI）。
> **修订 2026-09-07**：第 1、2 期已实施并通过验收；此后一轮体验打磨的落地情况见文末「§8 实施状态与后续修订」。

## 0. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 (pywebview/WebView2)                                    │
│  ├─ 顶栏 [🤖 Claude] → connectClaude() → 新 tab (xterm)      │
│  ├─ buildTerminal 复用（meta.kind='claude'，前端链路零改动） │
│  └─ 右面板 pane「🤖 Claude」← 5s 轮询 /api/claude/*           │
├─────────────────────────────────────────────────────────────┤
│ Flask 后端                                                    │
│  ├─ /api/connect kind='claude' → ClaudeConnection            │
│  ├─ /api/resize（新）→ pty.set_size                           │
│  ├─ /api/claude/sessions /skills /status（新）                │
│  ├─ /api/claude/statusline /hook（第 3 期：CC → 后端上报）     │
│  └─ src/claude_conn.py: pywinpty ConPTY ← 继承 BaseConnection │
├─────────────────────────────────────────────────────────────┤
│ claude CLI (真实进程，ConPTY)  ~/.claude/ (jsonl/skills/settings)│
└─────────────────────────────────────────────────────────────┘
```

核心原则：
1. **终端保真**——走既有 xterm→SSE→PTY 链路零改动。BaseConnection 模板方法让 ClaudeConnection 对前端完全透明（前端只认 port_id + meta.kind）。
2. **状态面板是独立旁路**——读 `~/.claude` 文件系统 + statusline/hook 上报端点，两者仅通过 port_id / session_id 关联。
3. **不写坏用户配置**——settings.json 修改前必须备份、只增不删、可精确还原。

## 1. ClaudeConnection（src/claude_conn.py，新文件）

### 1.1 claude 可执行解析 `_resolve_claude_exe()`

按序解析（每步 `os.path.isfile` 验证），结果模块级缓存：
1. 环境变量 `SERIAL_CLAUDE_EXE`（用户覆盖口）
2. `shutil.which("claude.exe")`（直接命中最理想）
3. `shutil.which("claude")` 解析到 `claude.CMD` → 推导同目录 `node_modules\@anthropic-ai\claude-code\bin\claude.exe`（npm shim 标准布局，本机实测存在）
4. 兜底：返回 .CMD 路径 + `_is_cmd_shim=True`，spawn 用 `["cmd.exe", "/c", path]`
5. 全部落空 → 抛错，中文消息含 `npm i -g @anthropic-ai/claude-code` 安装指引

### 1.2 类设计

```python
class ClaudeConnection(BaseConnection):
    kind = "claude"
    def __init__(self, cwd=None, resume=None, cols=120, rows=30, port_id=None)
```

- **`_io_open`**：`pywinpty.PtyProcessUnicode.PtyProcess.spawn(argv, dimensions=(rows, cols), cwd, env)`（懒加载）。argv 带 `--resume <id>`（可选）。env 必须完整（ConPTY 要求），`TERM=xterm-256color`、`COLORTERM=truecolor`。**cwd 必须显式传**（默认 `~`），否则会话开在工具目录。
- **`_io_read_chunk`**：`self._proc.read(8192)` 阻塞读，UTF-8 encode 返回。进程不存活 → `_handle_eof()`。
- **EOF 语义（与 SSH 最大差异）**：claude 退出是语义事件不是故障——置 `alive=False` 让 reader 自然退出、`append_line` 提示「进程已退出」、`_io_close()`，**不重连**。`_io_reconnect` 恒 `return False`。
- **`_io_write`**：`self._proc.write(str)`（Unicode 版接 str）。
- **`_io_close`**：`terminate(force=True)`，幂等（`if self._proc is None: return`）。cmd shim 场景必要时补 `taskkill /T /F`。
- **`resize(rows, cols)`**：`self._proc.set_size(rows, cols)`（pywinpty 参数序 rows, cols），持锁。
- **`start()` 覆盖：不落盘**——Claude 自带 `~/.claude` 转写，工具的行式日志存 TUI 重绘流无回看价值；buf 保留（分栏搜索/分析/AI 感知仍工作）。`new_log()` 覆盖防炸；前端 claude tab 不显示「＋📋 新日志」按钮。
- **port_id**：新会话 `claude:<自增>`；resume `claude:r-<id前8位>`（后端分配，`/api/connect` 内去重）。

### 1.3 /api/connect 分支（src/server.py）

`elif kind == "claude":`——解析 cwd（默认 `~`）/resume，`_ports_lock` 内构造 + 注册 + 异常回收（半构造对象 close，沿用 #9 修复的模式），错误经 `_humanize_claude_error` 转可操作中文。

### 1.4 /api/resize（新端点）

`POST {port_id, cols, rows}` → `p.resize(rows, cols)`；非 claude kind 返回 `{ok:False, err:"该连接不支持"}`。

### 1.5 statusline/hook 上报端点（第 3 期占位）

- `POST /api/claude/statusline`：存 `_claude_status[session_id] = {..., ts}`（app_state 新状态区，照 `_mcp_calls` 模式 + lock）
- `POST /api/claude/hook`：入 `_claude_events` deque(maxlen=100)
- 面板靠 ts 超时（>120s 过期）自动判定非活跃，SSE 断开不清。

## 2. 前端 Claude 终端 tab（web/js/claude.js 新文件）

### 2.1 connectClaude——复用 buildTerminal 不复制

```js
async function connectClaude(opts = {})   // {cwd, resume, label}
// POST /api/connect kind='claude' → buildTerminal(portId, {kind:'claude', label, cwd, baud:''})
// → connections[portId] → switchTab → refreshSidebar/refreshGlobalStatus
```

buildTerminal 仅两处小改（terminal-core.js）：
- tab 标题 `@baud` 显示：`meta.kind === 'ssh' || 'claude'` 时不显示
- claude tab 隐藏「＋📋 新日志」按钮

### 2.2 resize 转发

`conn.term.onResize` → debounce 200ms → `POST /api/resize`（尺寸变化短路；初始 fit 触发一次无害且正确——纠正 spawn 时猜测的 120x30）。

### 2.3 关闭兼容——零改动

`closeConnection` 无条件 POST /api/disconnect + 前端清理；后端泛 kind `p.close()` 走基类杀 PTY；EOF 后 alive=False 仍在 `_ports`，✕ 走同路径，close 幂等。

### 2.4 既有文件改动点

| 文件 | 改动 |
|---|---|
| util.js sortKeyFn | `claude:` 前缀 → `[4, pid]` 新档（不改会混进 SSH 档） |
| sidebar.js descText | isClaude 分支：`🤖 Claude · cwd尾段` |
| index.html 顶栏 | `<button id="btnClaude">🤖 Claude</button>`（换肤左侧） |
| index.html 脚本 | `<script src="web/js/claude.js">`（init.js 前） |

## 3. Claude 面板（右面板新 pane「🤖 Claude」）

### 3.1 数据源（src/claude_sessions.py，新文件）

**`list_sessions(limit=50)`**：扫 `~/.claude/projects/*/*.jsonl`，按 last_ts 降序返回
`{session_id, cwd, project_dir_name, first_msg, title, last_ts, first_ts, approx_msgs, size, active}`。
- **cwd 从 jsonl 首行 `cwd` 字段还原**（目录名如 `D--AI------Pro` 非 ASCII 全塌成 `-`，不可靠——实测首行有 cwd）
- 每文件只读头 64KB + 尾 128KB 两窗（seek(-tail, 2) 对齐 `\n`），不全文遍历
- 首条用户消息排除 `<local-command-caveat>`/`<command-name>`/tool_result；`{"type":"ai-title"}` 行优先
- 消息数 = 尾窗正则近似计数；`active` = mtime < 60s
- 模块级缓存 `path → (mtime, size, parsed)`，5s 轮询常态成本≈0
- 半行（claude 写到一半）跳过不抛

**`list_skills(cwd=None)`**：扫 `~/.claude/skills/*/SKILL.md` + `<cwd>/.claude/skills/*/SKILL.md` + `~/.claude/plugins/*/skills/*/SKILL.md`，frontmatter 正则提 name/description（不引 yaml 库），返回含 `source: user|project|plugin`。

**`claude_status()`**：聚合 `{tool_sessions（_ports 中 kind='claude'）, external_active（jsonl 活跃）, statusline（第 3 期）}`。

### 3.2 端点（server.py）

`GET /api/claude/sessions`、`GET /api/claude/skills`、`GET /api/claude/status`。

### 3.3 pane（claude.js）

index.html 加 `.panel-tab data-pane="claude"`（replay.js 通用 forEach 自动接住切换）+ pane 容器三个 section：
- **运行中会话**：本工具连接（点行 switchTab）+ 外部活跃会话（标「外部进程」）
- **历史会话（点击恢复）**：时间 · 项目尾段 · 首条消息摘要（60 字）· 活跃点；整行 onclick → `resumeClaudeSession(s)` → `connectClaude({cwd, resume: session_id})`
- **技能**：名字加粗 + 描述灰字 + source 徽标，只读

轮询照 analyze 模式（init.js）：5s setInterval + pane 可见性判断。

### 3.4 实时状态：MVP 与进阶分层

- **MVP（第 2 期）零配置三层信号**：① `_ports` 本工具连接（进程存活/EOF 全知）；② jsonl mtime<60s 判外部活跃；③ active 会话尾窗最后 5 条 entry 的 type/ts → 「最近在执行工具调用」级粗粒度状态。
- **进阶（第 3 期）statusline/hook 上报**：拿 model/context 用量/当前工具等细粒度。**本机 settings.json 的 statusLine 已被 statusline.py 占用**——一键配置生成 wrapper 脚本 `~/.serialconsole_pro/cc_statusline.py`（读 stdin → 透传原命令保留原输出 → 异步 POST 后端）；原命令存工具 config.json `claude_statusline_prev` 供还原。hooks 用 **append** 不替换。写前逐字节备份 + 临时文件 os.replace 原子替换。面板显示「已接入 ✓」+「停用」按钮。

## 4. 会话恢复

- sessions 列表每项含恢复所需全部字段（session_id + 从首行还原的 cwd）
- 点击 → `connectClaude({cwd, resume})` → PTY 内 `claude --resume <id>`；id 不存在时 CLI 自行报错退出 → EOF 提示路径闭环
- EOF 后 tab 保留（报错可查），✕ 清理；不自动重连/关闭

## 5. 分期实施与验收

### 第 1 期：最小闭环（内嵌终端跑真 claude）
改动：claude_conn.py、server.py（connect 分支 + /api/resize）、claude.js、index.html、terminal-core.js、util.js、sidebar.js。前置 `pip install pywinpty`。
**验收**：点「🤖 Claude」新 tab 跑起 CLI 可对话；中文无乱码、ANSI 正常；resize 生效不错位；`/exit` 后「进程已退出」提示、✕ 后无残留进程；未装 claude 得到中文报错（SERIAL_CLAUDE_EXE 指向不存在路径模拟）。

### 第 2 期：会话面板 MVP
改动：claude_sessions.py、server.py 3 个 GET、claude.js pane 渲染、index.html pane、init.js 轮询。
**验收**：50 个历史会话字段与 jsonl 实际相符（抽 2 对照）；点历史会话 --resume 回到上下文；技能三来源正确列出；运行中区分本工具/外部；pane 不可见时不发请求（DevTools network 确认）。

### 第 3 期：详细状态接入（statusline wrapper + hooks）
改动：server.py 上报端点 + app_state 状态区、wrapper/hook 脚本生成、claude.js 接入按钮 + 渲染。
**验收**：启用前自动备份；用户原 statusline 仍正常；面板 model/context/工具事件与 CLI 一致；停用后 settings.json 与备份 diff 一致恢复。

### 第 4 期：打磨与分发
EOF 后 tab LED 变灰；终端工具栏「⏵ 恢复上次会话」；MCP 工具暴露 tool_list_claude_sessions / tool_connect_claude；打包 spec hiddenimports 加 src.claude_conn、src.claude_sessions、pywinpty，**exe 冒烟**：spawn→交互→resize→terminate 全通过（DLL 漏收时 spec binaries 显式补 `pywinpty/*.dll`）。

## 6. 风险清单与对策

| # | 风险 | 对策 |
|---|---|---|
| 1 | pywinpty 阻塞读 vs Flask 线程 | 一连接一 reader 线程（基类模型），阻塞读零轮询开销；close 时先 terminate 使 read 解除，基类 join(1s) 兜底。ConPTY 需 Win10 1903+（本机 19045 ✓） |
| 2 | claude 路径解析（cmd shim / PATHEXT / 未装） | 5 级解析 + 缓存 + SERIAL_CLAUDE_EXE 覆盖口；报错含安装指引 |
| 3 | 写坏用户 settings.json | 逐字节备份 + 只增不删（hooks append）+ 原值存 config.json 精确还原 + os.replace 原子替换 |
| 4 | jsonl 大文件性能 | 头尾窗口读 + mtime/size 双 key 缓存 + 轮询仅 pane 可见时发生 |
| 5 | xterm resize 与 PTY 同步 | onResize debounce 200ms + 尺寸短路 + 后端持锁串行 |
| 6 | pywinpty 打包 | hiddenimports 明列 + exe 冒烟硬验收 + DLL 漏收 spec binaries 补 |
| 7 | claude CLI 升级改行为 | --resume 是稳定接口；statusline schema 解析全容错（缺字段显示 —） |
| 8 | 强杀进程残留 | terminate(force=True)；cmd shim 进程树第 4 期实测，必要时 taskkill /T /F |
| 9 | xterm fidelity 不及 Windows Terminal | 核心体验 100% 可用（VS Code 同架构铁证）；缺内联图片（sixel）等边缘能力；保底升级路径：换 wezterm web 或嵌真 wt.exe |

## 7. 关键文件

- 修改：src/server.py、src/app_state.py（第 3 期状态区）、web/js/terminal-core.js、web/js/util.js、web/js/sidebar.js、web/js/init.js、web/index.html
- 新增：src/claude_conn.py、src/claude_sessions.py、web/js/claude.js
- 模板参照：src/base_conn.py（连接契约）、src/ssh_conn.py（活样板）

## 8. 实施状态与后续修订（2026-09-07）

### 8.1 分期落地情况

| 期 | 状态 | 说明 |
|---|---|---|
| 第 1 期 最小闭环 | ✅ 已实施验收 | ConPTY 跑真实 CLI，中文/ANSI/resize/EOF 语义均按设计落地 |
| 第 2 期 会话面板 MVP | ✅ 已实施验收 | sessions/skills/status 三端点 + 右面板四子 sheet（活跃/历史/技能/MCP） |
| 第 3 期 statusline/hook 上报 | ⬜ 未实施 | 暂无排期 |
| 第 4 期 打磨与分发 | 🔶 部分 | MCP 工具已并入（observe 即可看 claude 连接）；打包/exe 冒烟未做 |

### 8.2 体验打磨落地记录（2026-09-07 会话）

设计定稿后针对内嵌 claude 的一轮集中打磨，全部已实施生效：

- **滚轮翻阅（terminal-core.js）**：双模式分流——**生成中**滚轮转 PgUp/PgDn，claude TUI 打开 transcript 滚动视图（只翻内容不动输入框；实测 2.1.239 仅生成中响应翻阅，空闲穷举 PgUp/Shift+PgUp/Ctrl+E/B/Y/O/方向键/SGR 鼠标序列均无效）；**空闲**滚轮走 xterm 原生 scrollback `scrollLines` 全屏翻，onData 打字自动跳回底部。
  - 生成中判据（多次翻车的教训沉淀）：**体量门槛 + 短窗口**——`_rawVol` 只累计 >100 字节 chunk（空闲时 spinner/状态栏微刷新帧仅几十字节），2.5s 清零；门槛 300 字节。不用"最近有输出"判据（微刷新会永远误判）。
  - **打字回显豁免**：每敲一键 TUI 重绘输入区（数百字节大 chunk）会误推高 `_rawVol` → 打字时滚轮被误分流成无效 PgUp，"输入文字时翻不了页"。onData 记 `_keyTs`，敲键后 250ms 内到达的 chunk 不计入 `_rawVol`。
  - 曾试并否决：空闲放行原生滚轮（TUI 常开鼠标上报会吃掉）、按最近输出时窗分流（微刷新误判）、jsonl 解析历史回看覆盖层 claude-history.js（用户否决，代码已删；后端 `/api/claude/transcript` + `claude_sessions.export_session_transcript` 保留备复用）。
- **主题跟随（claude_conn.py / theme.js / server.py）**：启动每会话建 `--settings` 临时文件注入 theme（亮色用 light-ansi 走 ANSI 16 色，让 xterm 亮色调色板解释代码块色）；运行中切换走 /theme 菜单注入闭环——`set_light_theme()` 从 buf 清洗行定位 ❯ 光标 → `(target-cur)%8` 发 ↓（菜单循环回绕实测成立）→ Enter → 验证 "Theme set to …" 确认文本，失败 Esc 兜底。settings 文件热重载实测无效（2.1.239）。限制：生成中/有草稿时切换自动放弃。
- **Shift+右键直接粘贴**（terminal-core.js contextmenu）：与 Ctrl+V 同款；Ctrl+右键上下文菜单。
- **启动即聚焦**（claude.js +300ms 延迟 focus，ConPTY 启动输出重渲染会夺焦点；main.py on_loaded show+focus）。
- **WebView2 缓存**（server.py after_request 禁缓存头）：多次前端改动"不生效"的总根因。
- **感知面板 claude 碎片过滤**（server.py `_claude_sense_ok`）：恢复会话启动重绘一次灌 8000+ 碎片行污染感知 → 只准入有语义文本行。
- **「最近」列表显示备注名**（init.js 启动即调 refreshClaudePanel 建 `_claudeTitleMap`）：此前 5s 轮询仅面板可见时刷新，启动时全显示固化 label 分不清。
- **快捷打开文件绕过 claude 拦截**（editor.js `openDroppedFile(path, fromRecent)`）：此前开着 claude 点「最近」文件，路径被灌进 claude 输入框（拖拽语义误伤）。

### 8.3 已知限制

- claude 全局 settings.json 设 auto 主题时，ConPTY 链路下 OSC 11 背景查询失灵，claude 按 Windows 系统深色回退——显示暗色是 claude 已知行为，非本工具问题（本工具侧已用 --settings 显式注入规避）。
- 空闲态翻阅是 scrollback 残影流（TUI 不切备用屏），非干净对话回看；干净回看如将来需要，走保留的 transcript 导出接口另做 UI。

### 8.4 第 2 期深化：会话面板实装修订（2026-09-07 后续会话）

第 2 期验收后的一轮面板深化，对 §3/§4 设计的落地偏差与新增能力：

- **主体会话判定（重要口径修正）**：`_parse_session` 只认 user 行 `promptSource='typed'` 且 `origin.kind='human'` 的 jsonl——后台 agent 转写（promptSource='sdk'）、queue-operation/compact 碎片全部不进列表（实测 35→24，与 claude agents 总览口径一致）。
- **标题优先级**：备注（工具 config.json `claude_notes` 键，✎ 弹项目风格 modal 改名，POST /api/claude/note）> aiTitle/agentName > 首条消息摘要。备注只影响工具内显示，不动 claude jsonl。
- **摘要=最后一条 typed 用户消息**（反映当前进展，首条"你好"无信息量）：尾窗找不到时反向分块扫描兜底（512KB 块、行级前缀探测 `b'"promptSource":"typed"'`、封顶 64MB）——长会话末尾 128KB 全是 tool_result 时尾窗够不着。
- **active 判定放宽 15min**：60s 窗口把 idle 会话（等输入/长思考不写 jsonl）误判进历史。
- **后台会话打开本体**：`--resume` 后台运行中的会话被 claude 拒绝（红字）；/api/connect 用 `_bg_sessions_running()`（wmic 扫进程命令行 `--session-id`，**必须 CREATE_NO_WINDOW** 否则 GUI 进程闪黑色 cmd 窗；wmic 输出 GBK 需 bytes 手解）检测命中后自动转 `claude agents` TUI，回车接管——CLI 无 attach flag，这是官方唯一路径。用户明确要求"打开本体"而非 --fork 分叉。
- **恢复免信任确认**：`_trust_workspace(cwd)` 恢复前把 cwd 的 `hasTrustDialogAccepted` 写 true（~/.claude.json projects 段，原子 tmp+replace，只动该目录）——从面板恢复=用户主动信任，不再卡 trust folder 确认。
- **面板结构演进**：Claude 档一级子 sheet 活跃/历史/技能/MCP；**MCP 从独立顶栏档并入**为子 sheet，内嵌二级页签（工具：后端地址+已注册工具 / 最近调用）。panel-tabs 剩 4 档，横向滚动条移除。子 sheet 切换必须按父容器分组（`sheetsRow.parentElement :scope > .claude-sheet-pane`）——全局 querySelector 切换会让两级页签互相关误关。
- **会话卡**：两行模板（标题+状态标签+✎ / 摘要+id 8 位）；长名 `flex:1; min-width:0` 自己截断（否则把标签挤竖排）；重名卡自动拼相对时间区分；活跃卡与历史卡同模板（弃用旧 claude-run 单行 flex 类——与两行模板叠类挤压排版）；`external_active` 计数排除本工具已开会话（同一会话被数两次虚高）。
- **「最近」列表 claude 条目动态名**：`_claudeTitleMap`（session_id→备注/aiTitle）渲染时替换固化 label「Claude·目录名」；打开时 tab 名同步。
