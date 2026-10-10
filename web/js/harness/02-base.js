// ============================================================
// Claude Harness 界面化会话 v2.1（微信式多会话 + claudecodeui 抄作业）。
// 与内嵌终端（claude.js connectClaude，ConPTY xterm 保真）平行的另一条
// 通道：后端 src/claude_harness.py spawn `claude -p --input/output-format
// stream-json`，NDJSON 事件原样透传，本文件负责全部渲染与会话管理。
// v2.1 移植清单（源：siteboon/claudecodeui，仅借鉴交互设计，代码重写）：
//   - 工具调用配置注册表（toolConfigs）+ 单行/折叠两种渲染 + 状态徽章
//   - 连续同名工具自动分组折叠（x3 + preview）
//   - Bash 命令行：$ 前缀 + 输出折叠 + 行数提示
//   - 代码块：hljs 高亮 + 语言标签 + 复制按钮（ChatGPT 式）
//   - thinking 折叠展示（流式展开、结束自动收起、计时）
//   - @ 文件引用（触发下拉/键盘选择/高亮 overlay）
//   - 输入历史（↑ 回溯 ↓ 前进，localStorage 按会话分桶）
//   - 图片内联预览 + Lightbox
//   - 活动指示（v2.19：行内胶囊，动词轮换 + 计时，与上下文环并排）
//   - 单行 ```x``` 折叠成 `x`（normalizeInlineCodeFences）
// 设计文档：docs/CLAUDE_CODE_INTEGRATION.md §8.6
// ============================================================

let _harnessMd = null;
function _harnessMdInstance() {
  if (_harnessMd === null)
    // v2.27.22：linkify 关闭——linkify-it 把裸词当域名（.py/.js 等都是合法
    // 顶级域）自动补 http:// 前缀，代码引用 proxy.py 变成可点外链，点击后
    // WebView 就地导航离开工具页面（ERR_NAME_NOT_RESOLVED 占满窗口，
    // 用户实锤"退不出去"）。显式 markdown 链接 [x](url) 不受影响
    _harnessMd = window.markdownit ? window.markdownit({ html: false, linkify: false, typographer: false, breaks: false }) : false;
  return _harnessMd;
}

// 单行 ```x``` 折叠成 `x`（防模型输出的伪行内代码破坏渲染；源 chatFormatting.ts）
function _hgNormalizeFences(text) {
  if (!text) return text;
  return text.replace(/```[ \t]*([^\n\r]+?)[ \t]*```/g, '`$1`');
}

// ---- 工具图标（emoji 版，避免引图标库）----
const _H_TOOL_ICO = {
  Read: '📖', Write: '✍️', Edit: '✏️', MultiEdit: '✏️', NotebookEdit: '📓',
  Bash: '💻', PowerShell: '🖥️', Grep: '🔍', Glob: '📂',
  WebFetch: '🌐', WebSearch: '🔎', Task: '✦', Agent: '✦',   // v3.3.12：机器人 emoji 太丑（用户定调），换中性星符 ✦
  TodoWrite: '📝', TodoRead: '📋', AskUserQuestion: '❓',
  TaskCreate: '📌', TaskUpdate: '📌', TaskList: '📌', TaskGet: '📌',
  Skill: '🧩', EnterPlanMode: '🗺️', ExitPlanMode: '🗺️', exit_plan_mode: '🗺️',
};
function _hToolIco(name) {
  const n = name || '';
  if (_H_TOOL_ICO[n]) return _H_TOOL_ICO[n];
  if (n.indexOf('mcp__') === 0) return '🔌';
  return '🔧';
}
// mcp__server__tool → tool (server)（源 toolConfigs.ts formatToolName；server 名可含 _，取最后一个 __ 切）
function _hToolLabel(name) {
  const n = name || '';
  const i = n.indexOf('mcp__') === 0 ? n.lastIndexOf('__') : -1;
  return i > 4 ? `${n.slice(i + 2)} (${n.slice(5, i)})` : n;
}

// ---- 工具调用注册表（源 toolConfigs.ts，vanilla 简化版）----
// mode: 'one-line'（单行）| 'collapsible'（折叠组）| 'hidden'（不渲染 input）
// result: 'hide'（成功时藏）| 'inline'（结果并入折叠组）| 'none'（不渲染结果）
const _H_TOOL_CFG = {
  Bash:      { mode: 'one-line', kind: 'bash',   get: i => i.command || i.cmd || '' },
  PowerShell:{ mode: 'one-line', kind: 'bash',   get: i => i.command || i.cmd || '' },
  Read:      { mode: 'one-line', kind: 'file',   get: i => i.file_path || '', result: 'hide' },
  Write:     { mode: 'collapsible', kind: 'diff', title: i => (i.file_path || '').split(/[\\/]/).pop() || '文件', badge: '新建', defaultOpen: true, get: i => ({ old: '', neu: i.content || '' }) },
  Edit:      { mode: 'collapsible', kind: 'diff', title: i => (i.file_path || '').split(/[\\/]/).pop() || '文件', badge: '编辑', defaultOpen: true, get: i => ({ old: i.old_string || '', neu: i.new_string || '' }) },
  MultiEdit: { mode: 'collapsible', kind: 'diff', title: i => (i.file_path || '').split(/[\\/]/).pop() || '文件', badge: '编辑', defaultOpen: true, get: i => ({ old: (i.edits || []).map(e => e.old_string || '').join('\n'), neu: (i.edits || []).map(e => e.new_string || '').join('\n') }) },
  NotebookEdit:{ mode: 'one-line', kind: 'file', get: i => i.notebook_path || i.file_path || '' },
  Grep:      { mode: 'one-line', kind: 'search', get: i => i.pattern || '', sec: i => i.path ? `in ${i.path}` : '' },
  Glob:      { mode: 'one-line', kind: 'search', get: i => i.pattern || '', sec: i => i.path ? `in ${i.path}` : '' },
  WebSearch: { mode: 'one-line', kind: 'web',    get: i => i.query || '' },
  WebFetch:  { mode: 'one-line', kind: 'web',    get: i => i.url || '' },
  TodoWrite: { mode: 'collapsible', kind: 'todo', title: i => {
      const todos = Array.isArray(i?.todos) ? i.todos : [];
      if (!todos.length) return '更新清单';
      const done = todos.filter(t => t?.status === 'completed').length;
      const act = todos.find(t => t?.status === 'in_progress');
      if (act) return `${act.activeForm || act.content} — ${done}/${todos.length}`;
      return done === todos.length ? `完成 — ${done}/${todos.length}` : `${done}/${todos.length} 完成`;
    }, get: i => ({ todos: i.todos || [] }), result: 'hide', defaultOpen: true },
  TodoRead:  { mode: 'one-line', kind: 'todo', get: () => '读取清单' },
  TaskCreate:{ mode: 'collapsible', kind: 'task', title: i => i.subject || '创建任务',
    get: i => [i.description && '描述：' + i.description,
               i.activeForm && '进行时显示：' + i.activeForm].filter(Boolean).join('\n'),
    result: 'hide' },
  TaskUpdate:{ mode: 'collapsible', kind: 'task',
    title: i => [i.taskId ? '#' + i.taskId : '', i.status || '', i.subject ? `"${i.subject}"` : ''].filter(Boolean).join(' → ') || '更新任务',
    get: i => i.description || (i.status ? '状态 → ' + i.status : ''), result: 'hide' },
  TaskList:  { mode: 'one-line', kind: 'task', get: () => '列出任务' },
  TaskGet:   { mode: 'one-line', kind: 'task', get: i => i.taskId ? '#' + i.taskId : '查看任务' },
  // v2.39：CLI 新版（2.1.267+）把子代理工具 Task 改名 Agent——此前照抄旧
  // Task 配置时多了 result:'hide'，完成报告被隐藏，主窗口看不到回传摘要
  // （旧 CLI 的 Task 路径正常，用户实锤「另一台电脑完全不一样」）。与 Task
  // 对齐：完成后报告摘要直显、全文收折叠体。
  Agent:     { mode: 'collapsible', kind: 'agent', badge: '子代理', title: i => [i.subagent_type || 'Agent', i.description].filter(Boolean).join(' · ') || '子代理', get: i => i.prompt || '' },
  // v2.21：派子代理显性化——紫色「子代理」徽章 + 运行秒表 + 完成后报告
  // 摘要（悬停看更多），报告全文收折叠体（完成有内容自动走 renderOneToolResult）
  Task:      { mode: 'collapsible', kind: 'agent', badge: '子代理', title: i => [i.subagent_type || 'Agent', i.description].filter(Boolean).join(' · ') || '子代理', get: i => i.prompt || '' },
  AskUserQuestion: { mode: 'collapsible', kind: 'question', title: i => {
      const qs = Array.isArray(i?.questions) ? i.questions : [];
      if (qs.length === 1) return `${qs[0]?.header || '问题'}${i?.answers?.[qs[0]?.question] ? ' — ' + i.answers[qs[0].question] : ''}`;
      return qs.length + ' 个问题';
    }, get: i => i.questions || [], result: 'hide', defaultOpen: true },
  ExitPlanMode: { mode: 'collapsible', kind: 'plan', title: () => '实施计划', get: i => String(i?.plan || '').replace(/\\n/g, '\n'), result: 'hide', defaultOpen: true },
  exit_plan_mode: { mode: 'collapsible', kind: 'plan', title: () => '实施计划', get: i => String(i?.plan || '').replace(/\\n/g, '\n'), result: 'hide', defaultOpen: true },
  Skill:     { mode: 'one-line', kind: 'skill', get: i => i.skill || '' },
  // Default：未注册工具走参数摘要（按键优先级抽 80 字符，不千篇一律 Parameters）
  Default:   { mode: 'collapsible', kind: 'default', title: i => {
      for (const k of ['command', 'file_path', 'pattern', 'query', 'url', 'path', 'skill', 'name', 'prompt'])
        if (typeof i?.[k] === 'string' && i[k]) return i[k].slice(0, 80);
      try { return JSON.stringify(i).slice(0, 80); } catch(_) { return ''; }
    }, get: i => { try { return JSON.stringify(i, null, 2); } catch(_) { return String(i); } } },
};
function _hCfg(name) { return _H_TOOL_CFG[name] || _H_TOOL_CFG.Default; }

// 工具类别 → 折叠组左边框色（源 CollapsibleDisplay borderColorMap）
const _H_KIND_COLOR = {
  diff: 'var(--h-amber, #d29922)', bash: 'var(--h-green, #3fb950)',
  search: 'var(--muted)', web: 'var(--h-sky, #58a6ff)', todo: 'var(--h-violet, #8957e5)',
  task: 'var(--h-violet, #8957e5)', agent: 'var(--h-purple, #a371f7)',
  plan: 'var(--h-indigo, #6e7ee8)', question: 'var(--h-sky, #58a6ff)',
  file: 'var(--muted)', default: 'var(--border)', skill: 'var(--accent)',
};

// 拒绝语义（源 ToolRenderer deriveToolStatus）：denied 橙 vs error 红
const _H_DENIAL = ['user denied tool use', 'tool disallowed by settings',
                   'permission request timed out', 'permission request cancelled'];

function _harnessRelTime(ts) {
  if (!ts) return '';
  const d = Date.now() - ts;
  if (d < 60e3) return '刚刚';
  if (d < 3600e3) return Math.floor(d / 60e3) + ' 分钟前';
  if (d < 86400e3) return Math.floor(d / 3600e3) + ' 小时前';
  if (d < 7 * 86400e3) return Math.floor(d / 86400e3) + ' 天前';
  const dt = new Date(ts);
  return (dt.getMonth() + 1) + '月' + dt.getDate() + '日';
}

const _HARNESS_IMG_EXT = /\.(png|jpe?g|gif|webp|bmp)$/i;

// ---- 多模态标记（v2.20）：描边眼睛 SVG。emoji 👁 随系统字形走，用户嫌丑；
// SVG 跟随文字色（currentColor），尺寸/粗细可控。 ----
const _HG_EYE = '<svg class="hg-eye" viewBox="0 0 24 24" aria-hidden="true">' +
  '<path d="M2.2 12S6 5.6 12 5.6 21.8 12 21.8 12 18 18.4 12 18.4 2.2 12 2.2 12z"/>' +
  '<circle cx="12" cy="12" r="3.1"/></svg>';

// ---- 组件状态 ----
const _HG = {
  conn: null, sid: null, dirty: false,
  model: null, models: null,
  skills: null,
  sessions: [],
  seq: 0,
  epoch: null,          // v3.0：日志代际水位（/rewind 换代即失效，SSE/轮询双通道校验）
  lastFrameAt: 0,       // v3.0：最近一帧（含 ka 心跳）到达时刻——20s 无帧看门狗强制重连
  proj: null,           // v3.1：前端事件投影（23-reducer 维护，进程面板/回合摘要的状态源）
  cacheWarm: {},        // v3.1：keep-warm 延迟销毁定时器（sid -> timer，切回即取消）
  cwd: null,            // v2.7：项目目录（新会话 cwd；null=默认 ~）
  perm: 'auto',         // v2.20：权限模式 auto|confirm（新会话 connect 带上）
  thinkLv: null,        // v2.20：思考等级 null|low|medium|high|max（勿与 think 思考段混淆）
  cache: {},            // sid -> {html, seq}（气泡快照）
  sse: null,
  busy: false, alive: false,
  atts: [],
  pop: null,            // 'skill' | 'model' | 'file' | null
  rowById: {},          // tool_use_id -> 工具行 DOM（挂结果用）
  subRows: {},          // v2.43：子代理段内工具行 parent_tool_use_id -> {tool_use_id: row}（段内结果配对，不入主链 rowById）
  subBlk: {},           // v2.43：子代理段 {pid: {root,head,body,seg,timer,t0}}（主 flow 化段；DOM 为持久源，切回按 data-hg-subblock 认回）
  uidN: 0,              // 无 id tool_use 的兜底计数
  run: null,            // 当前同名工具 run {name, head, rows, pending}（源 toolGrouping：run≥2 折叠）
  think: null,          // 当前活动思考段 {seg, grp}（v2.18：分段条目制）
  grp: null,            // 当前消息组（v2.18：抽屉随组走，替代 drawer/drawerThink 单例）
  asstText: false,      // 本轮 AI 是否已输出文本（占位动画/思考组头判据）
  histNav: null,        // 输入历史导航 {history, index, draft, recalled}
  mention: null,        // @ 引用状态 {at, files, sel}
  HIST_PAGE: 50,        // v2.24 多段式历史：每段渲染条数（大会话 DOM 瘦身，懒抽屉后再砍一档）
  lastTs: 0,            // v2.24.5 微信式时间条：上一条时间（>5min 才插新条）
  // v3.2.10（用户定调「绝对不允许封顶」）：HIST_CAP 置 Infinity——任何会话
  // 都可完整翻阅到第一条。DOM 防爆不靠封顶，靠三件套：回合默认折叠（头+
  // 结论行）+ 工具/思考懒抽屉（点开才渲染）+ 上滑渐进加载（不翻不载）；
  // 回合间快速定位走左缘回合导航轨（hg-rail，ZCode ConversationTurnNavigator
  // 同款——刻度悬停预览、点击跳转、未渲染回合先扩窗再定位）
  HIST_CAP: Infinity,
  histAll: null,        // 当前会话全量 transcript 行（多段渲染源）
  histStart: 0,         // 已渲染起点 index（0=全量）
  histLive: false,      // v2.35.2：histAll 是否经窗口渲染建立 DOM 对应（快照恢复的懒填不算——滚动扩收的放行门）
  histStale: false,     // v2.43.2（R2-缺口A）：降级标记——已确认漂移但忙碌未重渲，saveCache 存 'stale' 哨兵、恢复强制重渲
  archivedTurns: 0,     // v3.5.61：主窗口已归档轮数（归档提示文案用，切会话清零重算）
  histBuilding: false,  // v3.2.13：原子渲染（游离缓冲）进行中——isConnected 判据的缓冲期豁免（grpEnsure/_tlPlace/_tlExpFlush）
  imgSrv: null,         // 图片服务路径标记（后端 /api/harness/img/<sid>/file）
  activity: null,       // 活动指示 {start, verbTimer, tickTimer}
  actStart: 0,
  echoFast: null,       // v2.20：乐观渲染的 echo 去重窗口 {text}（SSE 回声跳过）
  queues: {},           // v2.20：消息排队 sid -> [{text, images, files}]
  qTimer: null,         // 排队泵去抖 timer
  compacting: false,    // v2.20：压缩进行中（分割线只插一次，恢复时补「完成」）
  compactT0: 0,         // 压缩开始时刻（动态秒表）
  compactUsed: 0,       // 压缩开始时的上下文规模（分割线里展示规模用）
  compactTimer: null,   // 秒表 tick
  dyn: null,            // v2.32 右侧面板派生态 {acts,turns,turnN,turnTools,todoSeen,todoRowId}（_hgDyn 惰建，切会话/关 tab 置 null）
  initN: 0,             // v2.35：本 SSE 流已见的 system/init 数——第 2 个起=CLI 自发新回合（后台任务通知/协作回传），前端即时亮运行态
  agentModels: null,    // v2.35：/agent_models 缓存 {类型: 模型名}（Task 起跑时预显示子代理模型；实跑模型以子代理事件 message.model 覆盖）
  peerNames: {},        // v2.37（P1-F①）：task_id/原始名 → 友好名映射（task_started 的 subagent_type 翻译；协作行显示用，完整 id 收 title）
  tasks: null,          // v3.5.22：后台任务档案 tid→{desc,t0,done,doneAt,err,cancelled,result,el}
                        // 与 agents 彻底分离（后台 shell 无转写，不进子代理体系）
  peerSent: null,       // v2.39：SendMessage tool_use_id → to 映射（task_notification 按 tool_use_id 反查原转交线名，修回传气泡配不上线）
  scheme: '',           // v3.5.98：当前激活 API 方案名（refreshSessions 刷新；会话卡对比标注 ⇄ 异方案）
};

// ---- 抽屉：工具名 → 展示名（用户口径：bash*n read*m grep*x 编辑*y）----
const _H_DRAWER_NAME = {
  Bash: 'Bash', PowerShell: 'Bash',
  Read: 'Read', Grep: 'Grep', Glob: 'Glob',
  Edit: '编辑', MultiEdit: '编辑', NotebookEdit: '编辑',
  Write: '新建', WebSearch: '搜索', WebFetch: '网页',
  Agent: '子代理', Task: '子代理', Skill: '技能',
  TodoWrite: '清单', TodoRead: '清单',
  TaskCreate: '任务', TaskUpdate: '任务', TaskList: '任务', TaskGet: '任务',
};
function _hDrawerName(tool) {
  if (_H_DRAWER_NAME[tool]) return _H_DRAWER_NAME[tool];
  return (tool || '').indexOf('mcp__') === 0
    ? (tool.slice(tool.lastIndexOf('__') + 2) || '工具') : (tool || '工具');
}

// ---- 输入历史（源 useInputHistory.ts：localStorage 按会话分桶，100 条/100 桶 LRU）----
const _HG_HIST_KEY = 'hg-input-history';
function _hgHistRead(scope) {
  if (!scope) return [];
  try {
    const store = JSON.parse(localStorage.getItem(_HG_HIST_KEY) || '{}');
    return Array.isArray(store[scope]) ? store[scope].filter(x => typeof x === 'string') : [];
  } catch(_) { return []; }
}
function _hgHistAppend(scope, text) {
  if (!scope || !text.trim()) return;
  try {
    const store = JSON.parse(localStorage.getItem(_HG_HIST_KEY) || '{}');
    const entries = (Array.isArray(store[scope]) ? store[scope] : []);
    if (entries[entries.length - 1] === text) return;
    delete store[scope];
    store[scope] = [...entries, text].slice(-100);
    const keys = Object.keys(store);
    for (const k of keys.slice(0, Math.max(0, keys.length - 100))) delete store[k];
    localStorage.setItem(_HG_HIST_KEY, JSON.stringify(store));
  } catch(_) {}
}

