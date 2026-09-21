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
  WebFetch: '🌐', WebSearch: '🔎', Task: '🤖', Agent: '🤖',
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
  Write:     { mode: 'collapsible', kind: 'diff', title: i => (i.file_path || '').split(/[\\/]/).pop() || '文件', badge: '新建', get: i => ({ old: '', neu: i.content || '' }) },
  Edit:      { mode: 'collapsible', kind: 'diff', title: i => (i.file_path || '').split(/[\\/]/).pop() || '文件', badge: '编辑', get: i => ({ old: i.old_string || '', neu: i.new_string || '' }) },
  MultiEdit: { mode: 'collapsible', kind: 'diff', title: i => (i.file_path || '').split(/[\\/]/).pop() || '文件', badge: '编辑', get: i => ({ old: (i.edits || []).map(e => e.old_string || '').join('\n'), neu: (i.edits || []).map(e => e.new_string || '').join('\n') }) },
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
  cwd: null,            // v2.7：项目目录（新会话 cwd；null=默认 ~）
  perm: 'auto',         // v2.20：权限模式 auto|confirm（新会话 connect 带上）
  thinkLv: null,        // v2.20：思考等级 null|low|medium|high|max（勿与 think 思考段混淆）
  cache: {},            // sid -> {html, seq}（气泡快照）
  sse: null,
  busy: false, alive: false,
  atts: [],
  pop: null,            // 'skill' | 'model' | 'file' | null
  rowById: {},          // tool_use_id -> 工具行 DOM（挂结果用）
  uidN: 0,              // 无 id tool_use 的兜底计数
  run: null,            // 当前同名工具 run {name, head, rows, pending}（源 toolGrouping：run≥2 折叠）
  think: null,          // 当前活动思考段 {seg, grp}（v2.18：分段条目制）
  grp: null,            // 当前消息组（v2.18：抽屉随组走，替代 drawer/drawerThink 单例）
  asstText: false,      // 本轮 AI 是否已输出文本（占位动画/思考组头判据）
  histNav: null,        // 输入历史导航 {history, index, draft, recalled}
  mention: null,        // @ 引用状态 {at, files, sel}
  HIST_PAGE: 50,        // v2.24 多段式历史：每段渲染条数（大会话 DOM 瘦身，懒抽屉后再砍一档）
  lastTs: 0,            // v2.24.5 微信式时间条：上一条时间（>5min 才插新条）
  HIST_CAP: 300,        // v2.24 正常模式翻阅上限——更早的进「只读禅模式」看
  histAll: null,        // 当前会话全量 transcript 行（多段渲染源）
  histStart: 0,         // 已渲染起点 index（0=全量）
  histLive: false,      // v2.35.2：histAll 是否经窗口渲染建立 DOM 对应（快照恢复的懒填不算——滚动扩收的放行门）
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
  peerSent: null,       // v2.39：SendMessage tool_use_id → to 映射（task_notification 按 tool_use_id 反查原转交线名，修回传气泡配不上线）
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

// ---- tab 构建（单例）----
function buildClaudeHarnessTab(opts = {}) {
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'harness') { switchTab(pid); return; }
  }
  const portId = 'harness:gui';
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico claude-ico"></span><span class="label">Claude 对话</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); _harnessClose(portId); return; } switchTab(portId); };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="hg">
      <div class="hg-side">
        <div class="hg-side-head">
          <button class="hg-new-btn" data-hg-new title="新建会话">✚ 新建会话</button>
          <button class="hg-new-btn hg-recover-btn" data-hg-recover title="扫描磁盘上的会话记录，找回列表里消失的会话（异常丢失/误删都可找回）">⟲ 恢复会话</button>
        </div>
        <div class="hg-search-wrap"><input class="hg-search" data-hg-search placeholder="搜索会话" spellcheck="false"></div>
        <div class="hg-sessions" data-hg-sessions></div>
        <button class="hg-prompt-btn" data-hg-vision title="识图配置（MCP 识图模型/端点映射/提示词）">👁 识图配置</button>
        <button class="hg-prompt-btn" data-hg-roles-cfg title="三角色配置：开关/模型槽/端点角色映射/审计模式与免审线（保存后下条消息热更生效）。双形态：轻快主模型=轻主力+designer；高级主模型=决策者+executor/coder">👥 三角色</button>
        <button class="hg-prompt-btn" data-hg-prompt title="管理自定义提示词（全局/项目，会话启动时注入）">📜 提示词</button>
        <button class="hg-prompt-btn" data-hg-proxy-btn title="Claude 代理：重试代理（429/5xx 自动重试）+ 用量统计。点开代理面板">
          <img src="/ico/proxy.png" alt="proxy" style="width:14px;height:14px;vertical-align:-2px;"> Proxy
          <span class="hg-proxy-state" data-hg-proxy-state>检测中…</span>
        </button>
        <button class="hg-prompt-btn hg-login-side" data-hg-login-toggle title="统一登录（代理/额度/机器人一次登录全通）。点击展开登录/登出">
          <span class="hg-login-dot off" data-hg-login-dot></span>
          <span data-hg-login-text>未登录 · 机器人未激活</span>
        </button>
        <div class="hg-login-pop" data-hg-login-pop style="display:none">
          <div data-hg-login-off>
            <input class="hg-login-inp" data-hg-login-user placeholder="用户名" spellcheck="false" autocomplete="username">
            <input class="hg-login-inp" data-hg-login-pwd type="password" placeholder="密码" autocomplete="current-password">
            <button class="hg-prompt-btn" data-hg-login-btn>登录</button>
          </div>
          <div data-hg-login-on style="display:none">
            <div class="hg-pop-row"><span class="hg-login-dot on"></span><span data-hg-login-name>已登录</span><button class="hg-pop-logout" data-hg-logout-btn title="登出（停用机器人）">登出</button></div>
            <div class="hg-pop-row hg-login-bot" data-hg-login-bot></div>
          </div>
        </div>
      </div>
      <div class="hg-main">
        <div class="hg-top">
          <span class="hg-cwd lv-btn" data-hg-cwd title="会话项目目录"></span>
          <span class="hg-title" data-hg-title>新会话</span>
          <span class="hg-flex1"></span>
          <span class="hg-vis-ind" data-hg-visind style="display:none"></span>
          <span class="hg-top-state" data-hg-state></span>
        </div>
        <div class="hg-flow" data-hg-flow></div>
        <div class="hg-card-wrap">
          <div class="hg-queue" data-hg-queue style="display:none"></div>
          <div class="hg-quote" data-hg-quote style="display:none">
            <span class="hg-quote-tag">引用</span>
            <span class="hg-quote-body" data-hg-quote-body></span>
            <button class="hg-quote-x" data-hg-quote-x title="取消引用">✕</button>
          </div>
          <div class="hg-atts" data-hg-atts style="display:none"></div>
          <div class="hg-input-card">
            <div class="hg-card-head">
              <button class="hg-proj" data-hg-proj title="选择项目目录（新会话直接在该目录下打开）">📁 <span data-hg-projname>选择项目</span> ▾</button>
            </div>
            <div class="hg-input-stack">
              <div class="hg-input-overlay" data-hg-overlay aria-hidden="true"></div>
              <textarea class="hg-input" data-hg-input rows="1" placeholder="给 Claude 发消息，@ 引用文件，/ 选择技能 · 可直接粘贴图片" spellcheck="false"></textarea>
            </div>
            <div class="hg-mention-drop" data-hg-mention style="display:none"></div>
            <div class="hg-card-foot">
              <button class="hg-chip hg-chip-ico" data-hg-att title="添加附件（文档会以路径给模型读取）">＋</button>
              <button class="hg-chip hg-chip-ico" data-hg-snip title="截图并标注（Snipaste 式框选/箭头/马赛克/文字；确认后自动挂为附件并复制剪贴板）">📷</button>
              <button class="hg-chip" data-hg-perm title="工具执行权限（对新会话生效）">🛡 自动执行 ▾</button>
              <button class="hg-chip hg-chip-ico" data-hg-skill title="加载技能（插入 /技能名）">⚡</button>
              <span class="hg-flex1"></span>
              <span class="hg-activity" data-hg-activity style="display:none"></span>
              <span class="hg-cost" data-hg-cost></span>
              <button class="hg-chip" data-hg-think title="思考深度（对新会话生效；等级越高思考越充分）">💭 思考 ▾</button>
              <button class="hg-chip" data-hg-model title="选择模型（对新会话生效）">🧠 模型 ▾</button>
              <button class="hg-send" data-hg-send title="发送（Enter）" aria-label="发送">
                <svg class="hg-ic-send" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.4 21 12 4 4.6v5.5l10.6 1.9L4 13.9z"/></svg>
                <svg class="hg-ic-stop" viewBox="0 0 24 24" aria-hidden="true"><rect x="4.5" y="4.5" width="15" height="15" rx="3"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="hg-subpane" data-hg-subpane style="display:none">
        <div class="hg-sub-resizer" data-hg-subres title="拖拽调宽"></div>
        <div class="hg-sub-wrap">
          <div class="hg-sub-head">
            <div class="hg-sub-tabs" data-hg-subtabs></div>
            <button class="hg-sub-x" data-hg-subx title="收起窗格（手动打开的窗格回合结束不自动收起；收起后点消息流子代理行或面板条目可重开）">✕</button>
          </div>
          <div class="hg-sub-body" data-hg-subbody></div>
        </div>
      </div>
      <input type="file" data-hg-file multiple style="display:none">
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);
  // 登录条 DOM 随 tab 创建——创建后立刻拉一次登录态（页面加载时的首轮
  // 渲染发生在 DOM 存在之前，会扑空停在「未登录」默认态）
  if (typeof hgLoginRefresh === 'function') setTimeout(hgLoginRefresh, 150);
  // 开启 Claude 联动：确保重试代理在跑（无则后台拉起无 headroom 的轻量
  // 代理，30s 未就绪自动回退直连）。fire-and-forget，不阻塞 tab 打开。
  fetch('/api/proxy/ensure', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{"for_claude":true}' }).catch(() => {});
  if (typeof hgProxyRefreshState === 'function') setTimeout(hgProxyRefreshState, 300);

  const conn = {
    portId,
    meta: { kind: 'harness', label: 'Claude 对话', cwd: '' },
    tab, wrap,
    sse: null, onResumePoll: null,
  };
  connections[portId] = conn;
  _HG.conn = conn;
  _HG.cache = {};
  _HG.atts = [];
  _HG.attsBy = {};   // v2.3.0：未发送附件按会话暂存（切走存/切回恢复，用户实锤丢图）
  _HG.sid = null;
  _HG.rowById = {}; _HG.uidN = 0; _HG.run = null;
  _HG.think = null; _HG.grp = null; _HG.histNav = null; _HG.mention = null;
  switchTab(portId);

  const q = (s) => wrap.querySelector(s);
  const flow = q('[data-hg-flow]'), input = q('[data-hg-input]'),
        stateEl = q('[data-hg-state]'), costEl = q('[data-hg-cost]'),
        sendBtn = q('[data-hg-send]'), titleEl = q('[data-hg-title]'),
        cwdEl = q('[data-hg-cwd]'), attsEl = q('[data-hg-atts]'),
        listEl = q('[data-hg-sessions]'), searchEl = q('[data-hg-search]'),
        fileEl = q('[data-hg-file]'), overlayEl = q('[data-hg-overlay]'),
        mentionEl = q('[data-hg-mention]'), actEl = q('[data-hg-activity]');
  // v2.24 大会话 DOM 卸载（见 _hgFlowUnloadInit）：切走 tab 快照清空、切回恢复
  _HG.flowEl = flow;
  _HG.flowSnap = '';

  const scrollBottom = (force) => {
    if (_HG.noScroll) return;   // v2.16：历史重建期间不滚（几百行逐行 append 会反复重排）
    // v2.20：用户翻上去看历史时不抢滚动条——距底 >150px 视为在看历史，
    // 流式新内容到达不再拽到底（用户实测「看之前思考时 AI 一回复就被拉到
    // 最下面」）。force=true（自己发消息、切会话回底）不受限。
    if (!force && flow.scrollHeight - flow.scrollTop - flow.clientHeight > 150) return;
    flow.scrollTop = flow.scrollHeight;
    // 布局二次兜底：活动指示条弹出/气泡内图片加载等会在同帧稍后改变 flow 高度，
    // 下一帧再滚一次，保证"发送后我的消息在底部"（v2.5 用户反馈修复）
    requestAnimationFrame(() => { flow.scrollTop = flow.scrollHeight; });
  };

  // ==================== 交互式提问卡片（v2.17）====================
  // 模型调 mcp__harness__ask_user → 后端 emit kind:'ask' → 这里渲染成可点选项。
  // 提交后 POST /ask/answer，后端唤醒阻塞中的 MCP 工具调用，模型拿到选择继续。
  function askRender(it) {
    if (!it || !it.req_id) return;
    const old = flow.querySelector(`[data-hg-ask="${CSS.escape(it.req_id)}"]`);
    if (old) old.remove();
    const qs = Array.isArray(it.questions) ? it.questions : [];
    if (!qs.length) return;

    const card = document.createElement('div');
    card.className = 'h-ask';
    card.dataset.hgAsk = it.req_id;
    card.dataset.hgQs = JSON.stringify(qs);   // 问题原文（提交时作 answer 的 key）
    card.dataset.hgSel = '{}';                // 题号 -> [选中的 label]
    qs.forEach((q, qi) => {
      const multi = !!q.multiSelect;
      const box = document.createElement('div');
      box.className = 'h-ask-q';
      box.innerHTML =
        `<div class="h-ask-head"><span class="h-ask-badge">${esc(q.header || '请选择')}</span>` +
        `<span class="h-ask-title">${esc(q.question || '')}</span>` +
        (multi ? '<span class="h-ask-multi">可多选</span>' : '') + '</div>';
      const opts = document.createElement('div');
      opts.className = 'h-ask-opts';
      (q.options || []).forEach((o) => {
        const label = typeof o === 'string' ? o : (o.label || '');
        const desc = typeof o === 'string' ? '' : (o.description || '');
        const b = document.createElement('button');
        b.className = 'h-ask-opt';
        b.dataset.hgAskOpt = String(qi);
        b.dataset.hgAskLabel = label;
        b.dataset.hgAskMulti = multi ? '1' : '';
        b.innerHTML = `<span class="h-ask-radio"></span>` +
          `<span class="h-ask-opt-txt"><b>${esc(label)}</b>` +
          (desc ? `<span class="h-ask-desc">${esc(desc)}</span>` : '') + `</span>`;
        opts.appendChild(b);
      });
      box.appendChild(opts);
      // v2.24.3：每题自由输入（用户定调「选项不够时要能自己打字」）——
      // 留空提交=纯选项；只输入不点选也放行（自由作答）
      const ex = document.createElement('div');
      ex.className = 'h-ask-extra';
      ex.innerHTML = `<input class="h-ask-x" data-hg-askx="${qi}" spellcheck="false"
        placeholder="其他 / 补充说明（可直接输入，回车提交）">`;
      box.appendChild(ex);
      card.appendChild(box);
    });
    const foot = document.createElement('div');
    foot.className = 'h-ask-foot';
    const submit = document.createElement('button');
    submit.className = 'h-ask-submit';
    submit.dataset.hgAskSend = it.req_id;
    submit.textContent = '提交选择';
    submit.disabled = true;
    const hint = document.createElement('span');
    hint.className = 'h-ask-hint';
    hint.textContent = '选择后提交，AI 会继续';
    foot.appendChild(submit);
    foot.appendChild(hint);
    card.appendChild(foot);
    flow.appendChild(card);
    // v2.27：ask 卡片 = AI 阻塞等作答，必须让用户看见。无 force 的
    // scrollBottom 在翻历史时被 150px 阈值拦下（用户实锤「弹出时要自己
    // 翻页找」）。这里无条件把卡片顶部滚进视口：多题卡片从题1看起，
    // 而不是只露出提交按钮。
    scrollBottom(true);
    requestAnimationFrame(() => card.scrollIntoView({ block: 'start' }));
  }

  // 卡片状态存在 dataset 而非 JS 属性：切走再切回走的是 innerHTML 快照路径
  // （_HG.cache），元素被重建、JS 属性全丢，但 dataset 随 HTML 一起回来。
  // 这与 v2.12 把抽屉开合委托化是同一个坑。
  function askQs(card) {
    try { return JSON.parse(card.dataset.hgQs || '[]'); } catch (_) { return []; }
  }
  function askSel(card) {
    try { return JSON.parse(card.dataset.hgSel || '{}'); } catch (_) { return {}; }
  }
  function askSelSet(card, sel) { card.dataset.hgSel = JSON.stringify(sel); }

  // 每题作答齐备判定：选项选中 or 自由输入有内容（v2.24.3 输入也算作答）
  function askExtraText(card, qi) {
    const inp = card.querySelector(`[data-hg-askx="${qi}"]`);
    return inp ? inp.value.trim() : '';
  }
  function askCheckDone(card) {
    const sel = askSel(card);
    const need = card.querySelectorAll('.h-ask-q').length;
    let ok = 0;
    for (let k = 0; k < need; k++)
      if ((sel[k] || []).length || askExtraText(card, k)) ok++;
    const sb = card.querySelector('.h-ask-submit');
    if (sb) sb.disabled = ok < need;
  }

  // 点击选项（flow 委托调用）：单选置换、多选切换
  function askPick(btn) {
    const card = btn.closest('.h-ask');
    if (!card || card.classList.contains('done')) return;
    const qi = btn.dataset.hgAskOpt;
    const multi = !!btn.dataset.hgAskMulti;
    const sel = askSel(card);
    if (!sel[qi]) sel[qi] = [];
    const label = btn.dataset.hgAskLabel || '';
    if (multi) {
      const i = sel[qi].indexOf(label);
      if (i >= 0) sel[qi].splice(i, 1); else sel[qi].push(label);
      btn.classList.toggle('on', i < 0);
    } else {
      sel[qi] = [label];
      card.querySelectorAll(`[data-hg-ask-opt="${qi}"]`).forEach(b => {
        b.classList.toggle('on', b === btn);
      });
    }
    askSelSet(card, sel);
    askCheckDone(card);
  }

  function askSubmit(reqId) {
    const card = flow.querySelector(`[data-hg-ask="${CSS.escape(reqId)}"]`);
    if (!card || card.classList.contains('done')) return;
    const qs = askQs(card), sel = askSel(card);
    const answer = {};
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const chosen = (sel[qi] || []).slice();
      const extra = askExtraText(card, qi);       // v2.24.3 自由输入并入作答
      if (!chosen.length && !extra) return;
      const qtext = (qs[qi] && qs[qi].question) || ('问题' + (qi + 1));
      answer[qtext] = chosen.concat(extra ? ['补充：' + extra] : []).join(', ');
    });
    if (!Object.keys(answer).length) return;
    const btn = card.querySelector('.h-ask-submit');
    if (btn) { btn.disabled = true; btn.textContent = '提交中…'; }
    fetch('/api/harness/ask/answer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sid: _HG.sid, req_id: reqId, answer})
    }).then(r => r.json()).then(j => {
      if (!j.ok) { if (btn) { btn.disabled = false; btn.textContent = '提交选择'; } renderRaw('⚠ 提交失败：' + (j.err || '')); }
    }).catch(() => { if (btn) { btn.disabled = false; btn.textContent = '提交选择'; } });
  }

  // 用户提交后定稿卡片：显示已选、禁用交互
  function askDone(it) {
    const card = flow.querySelector(`[data-hg-ask="${CSS.escape(it.req_id || '')}"]`);
    if (!card) return;
    card.classList.add('done');
    card.querySelectorAll('.h-ask-opt').forEach(b => { b.disabled = true; });
    const ans = it.answer || {};
    const qs = askQs(card);
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const qtext = (qs[qi] && qs[qi].question) || '';
      const chosen = ans[qtext];
      if (!chosen) return;
      box.querySelectorAll('.h-ask-opt').forEach(b => {
        b.classList.toggle('on', String(chosen).split(', ').indexOf(b.dataset.hgAskLabel) >= 0);
      });
    });
    const foot = card.querySelector('.h-ask-foot');
    if (foot) foot.innerHTML = `<span class="h-ask-done">✓ 已提交</span>`;
  }

  // ==================== markdown / 代码块 ====================
  function codeBlockEnhance(container) {
    // markdown-it 产物里的 pre > code：套 ChatGPT 式容器（语言标签+复制钮）
    container.querySelectorAll('pre > code').forEach(code => {
      const pre = code.parentElement;
      if (pre.parentElement && pre.parentElement.classList.contains('hg-code')) return;  // 已处理
      const raw = code.textContent.replace(/\n$/, '');
      const m = /language-(\S+)/.exec(code.className || '');
      const lang = m ? m[1] : '';
      const box = document.createElement('div');
      box.className = 'hg-code';
      const head = document.createElement('div');
      head.className = 'hg-code-head';
      head.innerHTML = `<span>${esc(lang || 'text')}</span>`;
      const cp = document.createElement('button');
      cp.className = 'hg-code-copy'; cp.textContent = '复制'; cp.title = '复制代码';
      // 点击由 flow 委托处理（v2.12——快照恢复后行内绑定失活）
      head.appendChild(cp);
      pre.replaceWith(box);
      box.appendChild(head);
      box.appendChild(pre);
      if (window.hljs && lang && hljs.getLanguage(lang)) {
        try { hljs.highlightElement(code); code.classList.add('hg-hl'); } catch(_) {}
      }
    });
  }
  function copyText(t) {
    return new Promise(res => {
      let ok = false;
      try {
        navigator.clipboard.writeText(t).then(() => res(true)).catch(() => res(false));
        ok = true;   // async 路径已接管
      } catch(_) {}
      if (!ok) {
        try { const ta = document.createElement('textarea'); ta.value = t;
          document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); res(true); }
        catch(_) { res(false); }
      }
    });
  }
  function renderMd(text) {
    const md = _harnessMdInstance();
    if (md) {
      const html = md.render(_hgNormalizeFences(text || ''));
      const t = document.createElement('div');
      t.innerHTML = html;
      // v2.27.22：一律拦截就地导航——http(s) 链接转系统浏览器打开（后端
      // /api/open_url），其余（相对路径/伪协议）只提示。WebView 一旦离开
      // 应用页面整个工具就被错误页替换且无返回入口（用户实锤）
      t.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        a.addEventListener('click', e => {
          e.preventDefault();
          if (/^https?:/i.test(href)) {
            fetch('/api/open_url', {method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({url: href})}).catch(() => {});
          }
        });
        a.title = /^https?:/i.test(href) ? '在系统浏览器中打开' : '工具内不支持跳转内部链接';
      });
      return t.innerHTML;
    }
    return '<p>' + esc(text).replace(/\n/g, '<br>') + '</p>';
  }
  function mdBubble(text) {
    const b = document.createElement('div');
    b.className = 'h-bubble';
    b.innerHTML = renderMd(text);
    // v2.24 懒高亮：历史路径（histAll 在场=重建/懒填）延后到可视时才增强+
    // 高亮（ChatGPT 式容器/复制钮/hljs 都是 CPU 大户，初始 50 条窗口里几十
    // 个代码块白高亮——默认翻阅根本看不到）。流式路径保持即时（用户正看）。
    if (_HG.histAll) _codeLazyEnhance(b); else codeBlockEnhance(b);
    return b;
  }
  // v2.24 懒高亮：代码块进视口才增强+高亮（IntersectionObserver 单例，滚到
  // 哪亮到哪；懒抽屉点开时其内容也经此通道——挂在视口内的即刻触发）
  let _codeIO = null;
  function _codeLazyEnhance(container) {
    const codes = container.querySelectorAll('pre > code');
    if (!codes.length) return;
    if (typeof IntersectionObserver === 'undefined') { codeBlockEnhance(container); return; }
    if (!_codeIO) {
      _codeIO = new IntersectionObserver((ents) => {
        ents.forEach(en => {
          if (!en.isIntersecting) return;
          _codeIO.unobserve(en.target);
          const pre = en.target.parentElement;
          if (pre && pre.isConnected) codeBlockEnhance(pre.parentElement || pre);
        });
      }, { rootMargin: '200px' });   // 视口外 200px 提前量，滚动时亮得无感
    }
    codes.forEach(c => _codeIO.observe(c));
  }

  // ==================== 附件 chip / 图片预览 ====================
  function attChipsHtml(images, files) {
    let h = '';
    // v2.3.3 data-img 走 /api/harness/file 只读接口——原来直接塞本地绝对路径
    // （C:\Users\...），WebView 安全策略禁止 http 页面加载本地文件，Lightbox
    // 弹了也是裂图（用户实锤「无法弹出显示」）。title 保留完整路径供核对。
    (images || []).forEach(p => {
      const name = String(p).split(/[\\/]/).pop();
      h += `<span class="hg-att-mini" data-img="/api/harness/file?name=${encodeURIComponent(name)}" title="${esc(p)}">🖼 ${esc(name)}</span>`;
    });
    (files || []).forEach(p => { h += `<span class="hg-att-mini">📄 ${esc(String(p).split(/[\\/]/).pop())}</span>`; });
    return h;
  }
  function openLightbox(src) {
    const ov = document.createElement('div');
    ov.className = 'hg-lightbox';
    ov.innerHTML = `<img src="${esc(src)}" alt=""><button class="hg-lightbox-x" title="关闭 (Esc)">✕</button>`;
    ov.addEventListener('click', (e) => { if (e.target === ov || e.target.classList.contains('hg-lightbox-x')) ov.remove(); });
    ov.addEventListener('keydown', () => {});
    const escFn = (e) => { if (e.key === 'Escape') { ov.remove(); document.removeEventListener('keydown', escFn); } };
    document.addEventListener('keydown', escFn);
    wrap.appendChild(ov);
  }

  // ==================== 过程抽屉（v2.7：非回答过程全部收进折叠抽屉）====
  // v2.11：双抽屉——「思考」（thinking 段）与「执行」（工具调用）各一个，
  // 都靠 AI 侧（左）对齐放 AI 气泡上方；busy 且 AI 尚未输出文本时，思考
  // 抽屉组头动画显示「AI 正在思考中…」，回复结束才定稿收尾。
  // v2.12：抽屉开合改为 flow 级事件委托——innerHTML 快照恢复（切会话再切回）
  // 不丢监听器；多个抽屉各自独立开合互不影响。
  // ==================== 抽屉/工具展开状态的持久化 ====================
  // 用户诉求：关掉 tab 再打开历史会话，「思考/工具展开情况不能丢」。
  // 同一 tab 内切走再切回走 innerHTML 快照，DOM 状态本来就保真；关 tab 后
  // 只能按 transcript 重建，默认值全会复位。这里按「结构路径」（flow 子索引
  // 逐层下钻）记开合状态到 localStorage——不依赖后端 id，重建后元素位置一致
  // 即能对上；流式阶段前面的元素不增删，路径同样稳定。
  function _hgPathKey(el) {
    const p = [];
    let n = el;
    while (n && n !== flow) { p.unshift(Array.prototype.indexOf.call(n.parentNode.children, n)); n = n.parentNode; }
    return p.join('/');
  }
  function _hgLoadOpen(sid) {
    try { return JSON.parse(localStorage.getItem('hg-open:' + sid) || '{}') || {}; } catch(_) { return {}; }
  }
  function _hgSaveOpen(el) {
    if (!_HG.sid) return;
    try {
      const st = _hgLoadOpen(_HG.sid);
      st[_hgPathKey(el)] = el.classList.contains('open') ? 1 : 0;
      localStorage.setItem('hg-open:' + _HG.sid, JSON.stringify(st));
    } catch(_) {}
  }
  // 重建期把记下的状态贴回元素（流式期 _HG.openState 为 null，不干预默认值）。
  // 没有记录时用 defOpen：历史抽屉默认收起（正文可见、过程细节按需展开），
  // 出错工具行默认展开（错误信息不该藏）。
  function _hgApplyOpen(el, defOpen) {
    const st = _HG.openState;
    if (!st) return;
    const k = _hgPathKey(el), has = k in st;
    el.classList.toggle('open', has ? !!st[k] : !!defOpen);
    // 有记录 = 用户碰过 → 标记住，重建末尾的 grpFinalize(true) 不再自动收它
    if (has) el.dataset.userToggled = '1';
  }

  // ---- 消息组基元（v2.18）----
  // 组 = .h-grp{ .h-grp-proc{ .h-drawer.think + .h-drawer.exec } + AI 气泡们 }。
  // 每轮 renderUser 开新组，思考/工具归属自己的消息组（用户点名：所有思考
  // 挤一个抽屉里分不清是哪次思考、哪个消息触发的执行）。活状态（counts/
  // segCount/t0）存 dataset——innerHTML 快照恢复后 JS 属性全丢，dataset 随
  // HTML 回来（与 v2.12 userToggled 进 dataset 同一个坑的对策）。
  function grpFromDom(root, thinkBox, execBox) {
    const g = {
      root,
      proc: root.querySelector('.h-grp-proc'),
      think: { box: thinkBox, body: thinkBox.querySelector('.h-drawer-body'),
               title: thinkBox.querySelector('.h-drawer-title'),
               stats: thinkBox.querySelector('[data-hg-dslots]') },
      exec: { box: execBox, body: execBox.querySelector('.h-drawer-body'),
              title: execBox.querySelector('.h-drawer-title'),
              stats: execBox.querySelector('[data-hg-dstats]'),
              slots: execBox.querySelector('[data-hg-dslots]') },
      ph: null, phTimer: null, phIdx: 0,
      counts: null,               // null = 未从 dataset 恢复
    };
    if (g.exec.stats) {
      try { g.counts = JSON.parse(g.exec.stats.dataset.counts || 'null'); } catch(_) { g.counts = null; }
    }
    // v2.20（2.png 空壳胶囊）：无内容的抽屉整体隐藏。新建组本来就 display:none
    // （见 grpEnsure），这里按 body 内容推导——快照恢复 inline style 会在、
    // 回扫接回走现场状态，但旧快照/边界路径没有标记，推导一劳永逸：
    // 空组什么都不显示（比「思考：无 / 执行：无」更干净）。
    const thKids = g.think.body ? g.think.body.children.length : 0;
    const exKids = g.exec.body ? g.exec.body.children.length : 0;
    const exCnt = g.counts && Object.keys(g.counts).length ? 1 : 0;
    thinkBox.style.display = thKids ? '' : 'none';
    execBox.style.display = (exKids || exCnt) ? '' : 'none';
    return g;
  }
  function grpEnsure(live) {
    let g = _HG.grp;
    if (g && g.root && g.root.isConnected) return g;
    // 快照恢复（切会话切回）后 _HG.grp 失联 → 扫 flow 最后一个组接回来。
    // 占位动画不重启：正文该到已到才走得到恢复路径。
    // v2.18.1：已定稿的组（dataset.finalized）不接回——正文切组刚定稿旧组，
    // 回扫必须放它过去，让下面新建组承接新回复。
    const root = flow.querySelector('.h-grp:last-of-type:not([data-finalized])');
    if (root) {
      const thinkBox = root.querySelector('.h-drawer.think');
      const execBox = root.querySelector('.h-drawer.exec');
      if (thinkBox && execBox) { _HG.grp = grpFromDom(root, thinkBox, execBox); return _HG.grp; }
    }
    // 新建组
    const nr = document.createElement('div');
    nr.className = 'h-grp';
    const proc = document.createElement('div');
    proc.className = 'h-grp-proc';
    // v2.39（dev）：组头归属标识（头像+「轻主力 · 模型」徽章）——用户实锤
    // 胶囊只有数字统计看不出这组活是谁干的。与子代理消息行（renderAsst
    // isSub）同款视觉语言。建在 head 按钮内 chev 之后：实时/历史重建都走
    // 本新建分支自动生效；快照恢复回扫（grpFromDom）不重建 head，标识随
    // innerHTML 序列化自动携带；grpFinalize/startThinking/drawerCount 只
    // 重写 title/stats span，不碰标识。两抽屉头各一份——纯思考组/纯工具组
    // 单抽屉显示时归属也在。
    const owner = _hgOwnerBadge();
    const thinkBox = document.createElement('div');
    thinkBox.className = 'h-drawer think';
    thinkBox.innerHTML =
      `<button class="h-drawer-head"><span class="h-chev">▸</span>` +
      owner +
      `<span class="h-drawer-title">🧠 思考</span>` +
      `<span class="h-tslots" data-hg-dslots></span></button>` +
      `<div class="h-drawer-body"></div>`;
    const execBox = document.createElement('div');
    execBox.className = 'h-drawer exec';
    execBox.innerHTML =
      `<button class="h-drawer-head"><span class="h-chev">▸</span>` +
      owner +
      `<span class="h-drawer-title">💻 执行</span>` +
      `<span class="h-drawer-stats" data-hg-dstats></span>` +
      `<span class="h-tslots" data-hg-dslots></span></button>` +
      `<div class="h-drawer-body"></div>`;
    proc.appendChild(thinkBox);
    proc.appendChild(execBox);
    // v2.20（2.png 空壳胶囊）：新组抽屉先隐藏——纯文本回复的组（无思考无工具）
    // 不再渲染「🧠 思考 / 💻 执行」空壳胶囊+「完成」徽章；有内容时由
    // startThinking / drawerCount 翻回显示。
    thinkBox.style.display = 'none';
    execBox.style.display = 'none';
    nr.appendChild(proc);
    addRow(nr);
    g = grpFromDom(nr, thinkBox, execBox);
    g.counts = {};                 // 新组才清；恢复组从 dataset 读
    if (g.think.stats) g.think.stats.dataset.segCount = '0';
    // 重建期：按记录恢复开合；无记录则默认收起（流式期 openState=null 不干预）
    _hgApplyOpen(thinkBox, false);
    _hgApplyOpen(execBox, false);
    _HG.grp = g;
    // v2.25：压缩开始会把进行中的组定稿（grpFinalize→phRemove 连占位气泡
    // 一起摘掉），压缩后模型继续推理 → startThinking/renderToolUse 在这里
    // 起新组——本轮不是新用户消息，renderUser 的 phStart 不会再触发 →
    // 「自动压缩完成」分割线到首条正文之间一片空白（用户截图红箭头：
    // 自动压缩完成后的提示/气泡又没了）。本轮仍在跑且尚无正文时补回占位，
    // 正文到达 renderAsst 会 phRemove 让位。
    if (_HG.busy && !_HG.asstText) phStart(g);
    return g;
  }
  function thinkSegCount(g) {
    return +((g.think.stats && g.think.stats.dataset.segCount) || 0) || 0;
  }
  function thinkSegCountSet(g, n) {
    if (g.think.stats) g.think.stats.dataset.segCount = String(n);
  }
  // 占位气泡：AI 消息泡未输出内容时的活泼文案轮换（用户明确要求，每轮独立）
  const _PH_WORDS = ['AI 正在思考中…', 'AI 正在翻阅资料…', 'AI 正在敲代码…',
    'AI 正在整理思路…', 'AI 正在细细品你的话…', 'AI 正在路上狂奔…',
    'AI 正在灵光乍现…', 'AI 马上就好了…'];
  function phStart(g) {
    if (!g.ph) {
      // v2.20：先认领快照恢复留下的冻结占位（grpFromDom ph:null 丢了引用），
      // 认不到再新建——否则 phResume 后会叠出第二个占位气泡
      const frozen = g.root.querySelector(':scope > .h-msg.asst.ph');
      if (frozen) g.ph = frozen;
      else {
        const d = document.createElement('div');
        d.className = 'h-msg asst ph';
        d.innerHTML = `<div class="h-bubble"><span class="hg-ph-word" data-hg-phw>AI 正在思考中…</span><span class="hg-ph-dots"><i></i><i></i><i></i></span></div>`;
        g.root.appendChild(d);
        g.ph = d;
      }
    }
    phStopTimer(g);
    g.phIdx = 0;
    g.phTimer = setInterval(() => {
      if (!g.ph || !g.ph.isConnected) { phStopTimer(g); return; }
      g.phIdx = (g.phIdx + 1) % _PH_WORDS.length;
      const w = g.ph.querySelector('[data-hg-phw]');
      if (w) w.textContent = _PH_WORDS[g.phIdx];
    }, 3500);
  }
  function phStopTimer(g) {
    if (g && g.phTimer) { clearInterval(g.phTimer); g.phTimer = null; }
  }
  function phRemove(g) {
    phStopTimer(g);
    if (g && g.ph) { g.ph.remove(); g.ph = null; return; }
    // v2.20：快照恢复的组 ph 引用是 null（grpFromDom 丢引用），但 DOM 里
    // 可能残留冻结占位——SSE 补放的 assistant 正文渲染时要把物理元素一并清掉，
    // 否则冻结的「AI 正在思考中…」和真实答案同时挂屏。
    if (g && g.root) {
      const frozen = g.root.querySelector(':scope > .h-msg.asst.ph');
      if (frozen) frozen.remove();
    }
  }
  // v2.20（3.png）：切回 busy 会话后占位气泡复活。快照恢复的 grpFromDom
  // ph:null 不认 DOM 里的 ph 元素（timer 轮换永久丢失，文案冻结）；transcript
  // 重建的 renderUser(live=false) 压根不建 ph——两条路径切回「正在回复」的
  // 会话都看不到「AI 正在思考中…」。恢复条件收紧到尾部未定稿组且尚无正文，
  // 已有正文/已定稿的会话不补（避免凭空多出气泡）。
  function phResume() {
    // 已有活的组对象且占位在屏（从未切走）→ 不用救，重开 timer 反而双计时
    const root = flow.querySelector('.h-grp:last-of-type:not([data-finalized])');
    if (_HG.grp && _HG.grp.root === root && _HG.grp.ph && _HG.grp.ph.isConnected) return;
    if (!root) {
      // 尾部没有活组 = transcript 重建的 busy 会话末行是 user（renderUser
      // (live=false) 不建组）——等价于「刚发完消息」：建组 + 占位。
      // 调用方必须已确认 busy，否则会凭空造出占位气泡。
      const g = grpEnsure(true);
      phStart(g);
      return;
    }
    const thinkBox = root.querySelector('.h-drawer.think');
    const execBox = root.querySelector('.h-drawer.exec');
    if (!thinkBox || !execBox) return;
    if (root.querySelector(':scope > .h-msg.asst:not(.ph)')) return;   // 正文已出，不占位
    const g = grpFromDom(root, thinkBox, execBox);
    _HG.grp = g;
    phStart(g);     // 冻结占位由 phStart 认领复用（不新建第二个）
  }
  // flow 级事件委托：抽屉组头/工具折叠行点击 → 只切自己
  // （v2.12 修「点一个全展开」+「切会话再切回后点不开」——innerHTML 快照恢复
  //   不丢监听器，每行每抽屉独立开合）
  // v2.24.3：提问卡片自由输入——输入即视为该题已作答（放行提交）；回车直接提交
  flow.addEventListener('input', (e) => {
    if (e.target.classList && e.target.classList.contains('h-ask-x')) {
      const card = e.target.closest('.h-ask');
      if (card) askCheckDone(card);
    }
  });
  flow.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('h-ask-x')) {
      e.preventDefault();
      const card = e.target.closest('.h-ask');
      const sb = card && card.querySelector('.h-ask-submit');
      if (sb && !sb.disabled) askSubmit(card.dataset.hgAsk);
    }
  });
  flow.addEventListener('click', (e) => {
    // v2.35（P0-2）：子代理消息行/工具行点击 → 重开实时窗格并切到对应
    // tab（✕ 收起后同一子代理还在跑时的重开入口；窗格已开=切 tab）
    // v2.35.1（F1/F7）：行内交互子元素放行——折叠头(.h-tool-head 展开/收起)、
    // 复制钮(.h-tool-copy 与气泡内 .hg-code-copy)、折叠体(.h-tool-coll)是
    // 既有交互（v2.12 起委托在此链后段），不得被整行重开劫持
    const subRow = e.target.closest('[data-hg-sub]');
    if (subRow && !e.target.closest('.h-tool-head, .h-tool-copy, .h-tool-coll, .hg-code-copy')) {
      _subReopen(subRow.dataset.hgSub); return;
    }
    // v2.35（P1-5）：「已转交」线点击 → 说明（协作代理是独立会话，无实况
    // 事件流可看，不伪装成能点开实况；回传以 📥 气泡呈现）
    if (e.target.closest('.h-switch[data-peer]')) {
      // v2.37R6：stale 线点击给核实口径
      const swp = e.target.closest('.h-switch[data-peer]');
      showBanner(swp.dataset.stale === '1'
        ? '该等待线超 30 分钟未回传，疑似残留——回传若到达会自动定格'
        : '协作代理是独立会话，无实时窗格——回传到达会以 📥 气泡呈现', 3200);
      return;
    }
    // 交互提问卡片（v2.17）：选项点击 / 提交
    const aOpt = e.target.closest('.h-ask-opt');
    if (aOpt) { askPick(aOpt); return; }
    const aSend = e.target.closest('.h-ask-submit');
    if (aSend) { askSubmit(aSend.dataset.hgAskSend); return; }
    const dHead = e.target.closest('.h-drawer-head');
    if (dHead) {
      const box = dHead.closest('.h-drawer');
      if (box) {
        box.classList.toggle('open');
        box.dataset.userToggled = '1';       // 写进 DOM——快照恢复后依然记得用户碰过
        _hgSaveOpen(box);                    // v2.16：关 tab 后重建也不丢
      }
      return;
    }
    // 思考段条目（v2.18）：段头点击 → 只切该段（开=懒渲染填 / 合=丢弃清空）
    const sHead = e.target.closest('.h-think-seg-head');
    if (sHead) {
      const seg = sHead.closest('.h-think-seg');
      if (seg) {
        const opening = !seg.classList.contains('open');
        if (opening) _histLazyFill(seg); else _histLazyDrop(seg);
        seg.classList.toggle('open'); _hgSaveOpen(seg);
      }
      return;
    }
    // v2.21：段尾右下角「收起 ⌄」→ 收该段（读完整段后原地收，不用滚回顶部）
    const sFold = e.target.closest('.h-think-seg-fold');
    if (sFold) {
      const seg = sFold.closest('.h-think-seg');
      if (seg) { _histLazyDrop(seg); seg.classList.remove('open'); _hgSaveOpen(seg); }
      return;
    }
    const tHead = e.target.closest('.h-tool-head');
    if (tHead) {
      const row = tHead.closest('.h-tool');
      if (row) {
        const opening = !row.classList.contains('open');
        if (opening) _histLazyFill(row); else _histLazyDrop(row);
        row.classList.toggle('open'); _hgSaveOpen(row);
      }
      return;
    }
    // 代码块/Bash 命令复制钮（v2.12 委托化——快照恢复后行内绑定会失活）
    const cp = e.target.closest('.hg-code-copy, .h-tool-copy');
    if (cp) {
      // 复制内容就近取：代码块取同容器 pre>code 文本；Bash 行取 .h-tool-arg 文本
      const codeBox = cp.closest('.hg-code');
      const txt = codeBox ? codeBox.querySelector('pre > code')?.textContent.replace(/\n$/, '')
        : cp.closest('.h-tool')?.querySelector('.h-tool-arg')?.textContent;
      if (txt) copyText(txt).then(ok => {
        if (ok) { const orig = cp.textContent; cp.textContent = '✓';
          setTimeout(() => cp.textContent = orig, 1500); }
      });
      return;
    }
    // 附件图片 chip → Lightbox
    const img = e.target.closest('[data-img]');
    if (img) openLightbox(img.dataset.img);
    // v2.22：用户消息重发（气泡右上刷新钮）——同内容再走一遍发送管线
    const rb = e.target.closest('.h-resend');
    if (rb) {
      const m = rb.closest('.h-msg.user');
      let atts = null;
      try { atts = JSON.parse(m?.dataset.ratts || 'null'); } catch(_) {}
      const text = m?.dataset.rtext || '';
      if (_HG.busy) queuePush({ text, images: atts?.images || [], files: atts?.files || [] });
      else dispatch(text, atts?.images || [], atts?.files || [], true);
      return;
    }
    // v2.22：编辑后重发——原文与附件填回输入框，改完正常发送
    const eb = e.target.closest('.h-edit');
    if (eb) {
      const m = eb.closest('.h-msg.user');
      let atts = null;
      try { atts = JSON.parse(m?.dataset.ratts || 'null'); } catch(_) {}
      input.value = m?.dataset.rtext || '';
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 200) + 'px';
      renderOverlay(input.value);
      _HG.atts = [];
      (atts?.images || []).forEach(p => _HG.atts.push(
        { name: String(p).split(/[\\/]/).pop(), path: p, size: 0, isImg: true }));
      (atts?.files || []).forEach(p => _HG.atts.push(
        { name: String(p).split(/[\\/]/).pop(), path: p, size: 0, isImg: false }));
      renderAtts();
      input.focus();
      scrollBottom();
    }
  });
  function drawerCount(toolName) {
    const g = grpEnsure(true);                  // 计数进当前组执行抽屉
    g.exec.box.style.display = '';              // v2.20：第一个工具到位，执行抽屉翻回显示
    if (!g.counts) g.counts = {};
    const n = _hDrawerName(toolName);
    g.counts[n] = (g.counts[n] || 0) + 1;
    // chips ≤8 个，超出折叠成「…」——组头收起态必须小（用户：总体只占一小部分）
    const entries = Object.entries(g.counts);
    const shown = entries.slice(0, 8).map(([k, v]) => `<span class="h-drawer-chip">${esc(k)}×${v}</span>`).join('');
    g.exec.stats.innerHTML = shown + (entries.length > 8 ? '<span class="h-drawer-chip">…</span>' : '');
    g.exec.stats.dataset.counts = JSON.stringify(g.counts);   // 快照恢复用
    scrollBottom();
  }
  // 组定稿（result / 新一轮 renderUser / 正文切组）：徽章 + 未手动碰过时自动收
  function grpFinalize(auto) {
    const g = _HG.grp;
    if (!g) return;
    phRemove(g);
    // v2.20 修复：定稿把组头「思考 N 次」重写为纯文本——流式中带的脉动
    // 动画（hg-think-anim）此前无人摘，回复结束后还在闪。
    // 无思考段的组（空壳抽屉）不动，别把初始标题改写成「思考 0 次」。
    const _segN = thinkSegCount(g);
    if (g.think.title && _segN > 0)
      g.think.title.innerHTML = '🧠 思考 ' + _segN + ' 次';
    if (g.think.stats) g.think.stats.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    if (g.exec.slots) g.exec.slots.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    // v2.21：纯思考/工具组（整组没有正文气泡）定稿时补一行弱提示——
    // 模型常连跑几十轮工具（text 全是 "\n\n" 占位被过滤），组头下面悬空
    // 看着像回复丢了（用户实测困惑点）。有正文/空壳组不补。
    if (!g.root.querySelector(':scope > .h-msg.asst') && !g.root.querySelector(':scope > .h-grp-notext') &&
        ((_segN > 0) || (g.counts && Object.keys(g.counts).length))) {
      const tip = document.createElement('div');
      tip.className = 'h-grp-notext';
      tip.textContent = '（本轮为思考/工具操作，无文字回复）';
      g.root.appendChild(tip);
    }
    // 用户手动开过不强制收；自动收只在用户在底部跟读时（v2.12 判据，按组生效）
    if (auto) {
      if (g.think.box.dataset.userToggled !== '1' && isNearBottom()) g.think.box.classList.remove('open');
      if (g.exec.box.dataset.userToggled !== '1' && isNearBottom()) g.exec.box.classList.remove('open');
    }
    g.root.dataset.finalized = '1';   // v2.18.1：已定稿——grpEnsure 回扫不得接回
    _HG.grp = null;      // 下轮 renderUser 开新组
  }
  function drawerAppend(el, kind) {
    const g = grpEnsure(true);
    (kind === 'think' ? g.think.body : g.exec.body).appendChild(el);
    scrollBottom();
  }

  // ==================== 气泡基元 ====================
  function hideWelcome() {
    const w = flow.querySelector('.hg-welcome');
    if (w) w.remove();
  }
  function addRow(el) {
    hideWelcome();
    flow.appendChild(el);
    scrollBottom();
    return el;
  }
  // ==================== v2.24.5 微信式时间条 ====================
  // 距上一条时间 >5 分钟才插（微信同款），插在触发消息前；格式分级：
  // 今天 HH:mm / 昨天 HH:mm / 今年 M月d日 HH:mm / 跨年 yyyy年M月d日。
  function _timeFmt(ms) {
    const d = new Date(ms), n = new Date();
    const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    const sameDay = (a, b) => a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    if (sameDay(d, n)) return hm;
    const yst = new Date(n); yst.setDate(n.getDate() - 1);
    if (sameDay(d, yst)) return '昨天 ' + hm;
    const md = (d.getMonth() + 1) + '月' + d.getDate() + '日';
    return d.getFullYear() === n.getFullYear() ? md + ' ' + hm
      : d.getFullYear() + '年' + md + ' ' + hm;
  }
  function _maybeTimeBar(ms, host) {
    if (!ms) return;
    if (ms - (_HG.lastTs || 0) < 5 * 60 * 1000) return;
    _HG.lastTs = ms;
    const t = document.createElement('div');
    t.className = 'h-time';
    t.dataset.ms = String(ms);
    t.textContent = _timeFmt(ms);
    (host || flow).appendChild(t);
  }

  function renderUser(text, images, files, live, tsMs) {
    grpFinalize(false);                       // v2.18：上一组定稿，本组接棒
    _maybeTimeBar(tsMs || Date.now());        // v2.24.5 微信式时间条（气泡前）
    endThinking(); closeRun();
    _HG.asstText = false;                     // 本轮 AI 尚未输出文本（占位/组头判据）
    const d = document.createElement('div');
    d.className = 'h-msg user';
    if (images?.length || files?.length) {
      const at = document.createElement('div');
      at.className = 'h-bubble-atts';
      at.innerHTML = attChipsHtml(images, files);   // 点击 Lightbox 由 flow 委托（v2.12）
      d.appendChild(at);
    }
    // v2.20：只发图不带文字 → mdBubble('') 是个空白气泡（用户嫌丑）；
    // 有附件且无文字时给一行占位文案，气泡不再空壳
    const body = (text && text.trim()) || ((images?.length || files?.length) ? '*（图片/附件，见上方）*' : '');
    d.appendChild(mdBubble(body));
    // v2.22：一键重发 + 编辑后重发——原始内容存 dataset（属性可随
    // innerHTML 快照恢复），钮 hover 显示，点击走 flow 委托
    d.dataset.rtext = text || '';
    d.dataset.ratts = JSON.stringify({ images: images || [], files: files || [] });
    const acts = document.createElement('div');
    acts.className = 'h-macts';
    acts.innerHTML =
      '<button class="h-mact h-resend" title="重发这条消息">↻</button>' +
      '<button class="h-mact h-edit" title="编辑后重发（原文+附件填回输入框）">✎</button>';
    d.appendChild(acts);
    addRow(d);
    if (live !== false) {
      const g = grpEnsure(true);
      phStart(g);                              // AI 未输出前的活泼占位（每轮独立）
    }
    return d;
  }
  // v2.28.13：user_echo 兜底去重——快照恢复场景 echoFast 可能已丢（切走时
  // 清空且旧快照没有该字段），快照里已有乐观气泡，重放的 echo 再画就双份
  // （用户实锤：A 发消息→切 B→切回 A，出现两条同文同图消息）。与最后一条
  // 用户气泡同文同附件 → 判定已画过。rtext/ratts 是 dataset 属性，随
  // innerHTML 快照序列化，跨恢复仍可比。
  function _hgEchoDup(it) {
    const us = flow.querySelectorAll('.h-msg.user');
    const last = us[us.length - 1];
    if (!last) return false;
    if ((last.dataset.rtext || '').trim() !== (it.text || '').trim()) return false;
    try {
      const ra = JSON.parse(last.dataset.ratts || '{}');
      if ((ra.images || []).join('\u0001') !== (it.images || []).join('\u0001')) return false;
      if ((ra.files || []).join('\u0001') !== (it.files || []).join('\u0001')) return false;
    } catch (_) { return false; }
    return true;
  }
  // v2.37（P1-C）：头像色板哈希——纯 CSS 语义变量（--hgd-*/--accent），零写死
  // 色零外部资源；同名恒同色（按首字符 charCode 取模）
  function _hgAvaCls(name) {
    const c = (String(name || '?').charCodeAt(0) || 63) % 5;
    return 'h-ava-' + c;
  }
  // v2.39（dev）：主会话组头归属标识 HTML——与子代理消息行同款「小头像+
  // 角色徽章」视觉语言。模型取 _HG.model 剥 [1M]（同 renderAsst 的 bare
  // 规则）；形态名从 _hgRolesCache 判 light/strong（判据同 renderAsst 角色
  // 徽章，roles 关/缓存未到只显模型名，不编造）；双空返回 ''（会话没选过
  // 模型且缓存未到——组头保持原样，不抛错不占位）。头像取色字符模型名
  // 优先（与 renderAsst 主分支一致：主会话头像色随模型变）。
  function _hgOwnerBadge() {
    const bare = String(_HG.model || '').split('[')[0].trim();
    const rj = _hgRolesCache;
    const role = (rj && rj.ok && rj.roles && rj.roles.enabled)
      ? (rj.mode === 'light' ? '轻主力' : '决策者') : '';
    if (!bare && !role) return '';
    const ac = bare || role;
    const txt = role && bare ? role + ' · ' + bare : (role || bare);
    return `<span class="h-drawer-owner">` +
      `<span class="h-ava ${_hgAvaCls(ac)}" style="width:12px;height:12px;font-size:8px;">${esc(ac.charAt(0).toUpperCase())}</span>` +
      `<span class="h-mmodel" title="本组思考/工具归属：主会话${bare ? '，模型 ' + esc(bare) : ''}">${esc(txt)}</span></span>`;
  }
  function renderAsst(text, isSub, subId, model) {
    // v2.16：空白/纯换行的 text 块不渲染。模型每轮都会吐一个 "\n\n" 占位块，
    // 旧判据 `if (!text)` 挡不住 → 每条渲染成一个空白气泡（历史重建后满屏空白
    // 圆角条）。重建与流式两条路径都走这里，一并对齐。
    if (!text || !String(text).trim()) return;
    // v2.18.1（3.png）：组合制 = 思考+工具+回复，按正文切分。当前组已出过正文
    // → 后续正文属下一条回复：先定稿，让新组头（思考/工具）落在新正文上方。
    // 子代理输出（isSub）是父代理工具的产物，归父组不切分。
    const cur = _HG.grp;
    if (_HG.asstText && cur && cur.root && cur.root.querySelector(':scope > .h-msg.asst')) {
      grpFinalize(true);
    }
    _HG.asstText = true;                       // v2.11：AI 已输出文本
    // v2.18：正文进当前组（组不存在说明是组外场景——快照恢复等，兜底建组）
    const g = grpEnsure(true);
    phRemove(g);                               // 正文接管，占位动画退场
    const d = document.createElement('div');
    d.className = 'h-msg asst' + (isSub ? ' sub' : '');
    // v2.35：子代理消息行挂 parent id——点击重开实时窗格并切到对应 tab
    // （P0-2：✕ 收起后同一子代理还在跑时，消息流行就是重开入口）
    if (isSub && subId) d.dataset.hgSub = subId;
    d.appendChild(mdBubble(text));
    // v2.37（P1-C）+ v2.37R6（徽章间歇缺失）：任何路径的 AI 气泡都至少有
    // 头像——实跑 model 可得（实时事件自带 message.model，缺省回退会话模型）
    // 必带徽章；历史旧数据无 model 只画头像不画徽章（不编造归属）。
    // 徽章/头像均为纯 class+dataset，随 innerHTML 快照序列化
    if (!isSub) {
      const bare = model ? String(model).split('[')[0] : '';
      const meta = document.createElement('div');
      meta.className = 'h-mmeta';
      // v2.38 角色徽章：三角色开启时按形态标主会话角色（strong=决策者/
      // light=轻主力）。缓存未拉到不标——不编造归属。样式复用 h-mmodel，
      // 加右距与模型徽章隔开。
      const rj = _hgRolesCache;
      const roleB = (rj && rj.ok && rj.roles && rj.roles.enabled)
        ? `<span class="h-mmodel" style="margin-right:6px;" title="三角色形态下的主会话角色">${rj.mode === 'light' ? '轻主力' : '决策者'}</span>`
        : '';
      meta.innerHTML = `<span class="h-ava ${_hgAvaCls(bare || 'AI')}">${esc((bare || 'AI').charAt(0).toUpperCase())}</span>` +
        roleB +
        (bare ? `<span class="h-mmodel" title="本条回复的实跑模型">${esc(bare)}</span>` : '');
      d.appendChild(meta);
    } else {
      // v2.39（dev）：子代理灰行归属标识——用户实锤：子代理中间输出文本行
      // 无任何归属，不知道是谁说的。数据源 _sub.tabs[subId]（Task 派单时
      // _subOpen 建档，label 已是 _AGENT_LABEL 翻译名；model 为实跑模型，
      // 随子代理 assistant 事件到达覆盖）。注意 renderAsst 的 model 参数对
      // isSub 恒 null（调用处 isSub ? null : ...，主链专用），isSub 分支只能
      // 自取档案。tab 被上限逐出/极端时序缺档 → 退「子代理」不抛错。历史
      // 重建路径不产生 sub 行（后端转写滤掉带 parent_tool_use_id 的行，
      // src/claude_harness.py），空档兜底已覆盖全部可达场景。
      const tab = _sub.tabs[subId] || {};
      const label = tab.label || '子代理';
      const bare = tab.model ? String(tab.model).split('[')[0] : '';
      const ac = tab.type || bare || label;   // 头像取色字符：类型优先（同型恒同色）
      const meta = document.createElement('div');
      meta.className = 'h-mmeta';
      meta.innerHTML =
        `<span class="h-ava ${_hgAvaCls(ac)}" style="width:12px;height:12px;font-size:8px;">${esc(ac.charAt(0).toUpperCase())}</span>` +
        `<span class="h-mmodel" title="子代理：${esc(label)}${bare ? '，实跑模型 ' + esc(bare) : ''}">${esc(bare ? label + ' · ' + bare : label)}</span>`;
      d.appendChild(meta);
    }
    if (!isSub) {                          // v2.28.16：回滚按钮（回合边界授予）
      const bar = document.createElement('div');
      bar.className = 'hg-msg-acts';
      bar.innerHTML =
        '<button class="hg-mact" data-hg-rewind title="回滚到本条所在回合结束：之后的全部丢弃（自动全量备份）">⏪ 回滚到这里</button>';
      d.appendChild(bar);
      // 锚点 = 正文前缀（随 dataset 序列化，实时/回放两路同源；后端按它
      // 定位「这条消息所在回合的 result」做截断）
      try { d.dataset.rwa = String(text).trim().slice(0, 60); } catch(_) {}
      _HG.lastAsstEl = d;                  // result 到达时授予 can-rewind
    }
    g.root.appendChild(d);
    scrollBottom();
  }
  // v2.28.16：「回滚」按钮授予（用户定调三连，终版语义）：按钮挂在
  // 【每个定下来的 AI 回合的最后一条消息】上——回合完成（result）授予，
  // 之后不摘（每个回合边界都是合法回滚点；生成中的回合没有按钮）。
  // can-rewind 类随 innerHTML 快照序列化；点击走 flow 级事件委托——
  // 快照克隆丢 onclick 的既有解法（同 h-macts）。
  function _hgGrantRewind() {
    const last = _HG.lastAsstEl
      || [...flow.querySelectorAll('.h-msg.asst')].filter(el => !el.classList.contains('sub')).pop();
    if (last && last.isConnected && last.dataset.rwa) last.classList.add('can-rewind');
  }
  // v2.28.12：回滚后重拉转写重建消息流（丢弃的回合从界面消失）
  async function _hgReloadFlow() {
    const sid = _HG.sid;
    if (!sid) return;
    try {
      const j = await (await fetch('/api/harness/transcript?sid=' + encodeURIComponent(sid))).json();
      if (!j.ok || _HG.sid !== sid) return;
      _HG.seq = j.seq || 0; _HG.alive = !!j.alive;
      _HG.visionCalls = null; _HG.peerWait = null;
      if (!j.lines.length) { flow.innerHTML = ''; showWelcome(); }
      else _histRender(j.lines, Math.max(0, j.lines.length - _HG.HIST_PAGE));
      setBusy(false);
      refreshSessions();
      scrollBottom(true);
    } catch(_) {}
  }
  function renderRaw(text) {
    const d = document.createElement('div'); d.className = 'h-raw'; d.textContent = text;
    addRow(d);
  }
  function renderExit(text) {
    const d = document.createElement('div'); d.className = 'h-exit'; d.textContent = text;
    addRow(d);
  }
  // v2.20：模型切换分割线（会话内换模型即时生效的可见反馈）
  function renderSwitch(model) {
    const d = document.createElement('div'); d.className = 'h-switch';
    d.innerHTML = '<span></span><i>已切换模型 · ' + esc(model) + '</i><span></span>';
    addRow(d);
    scrollBottom();
  }
  // v2.27.23：超窗续命分割线——[系统] 历史注入后台化的可见标记（一行带过）
  function renderRenew(text) {
    const d = document.createElement('div'); d.className = 'h-switch hg-renew';
    d.innerHTML = '<span></span><i>♻️ ' + esc(text) + '</i><span></span>';
    addRow(d);
  }
  // v2.34：审计警示气泡——light 形态回合结算审计的可见出口（warn 档唯一
  // 动作；auto 档续发补审指令时也先出这条）。红色居中卡片，区别于用户/
  // AI 气泡与灰色 raw 行：这是 harness 的裁决信息，用户必须知情。回放路径
  // （role='audit' 行）与实时（kind='audit' 事件）共用，切会话形态一致。
  function renderAudit(text) {
    const d = document.createElement('div');
    d.className = 'h-audit';
    d.textContent = text;
    addRow(d);
  }
  // v2.27.3：识图/跨会话协作的过程可见性（用户定调：全程要有反馈）——
  // 转交 = 分割线；回传 = 专属气泡。原实现回传内容直接被丢弃（user 事件
  // 只处理 tool_result），结论"凭空消失"，只有主会话转述才可见。
  // v2.28.3：定格指定识图分割线（多调用并发时 peerWait 单槽不够用——
  // 每条线按 tool_use_id 对应自己的元素，各自定格互不干扰）
  // v2.35：定格时落 data-done（epoch ms）——面板「协作代理」行与输入框
  // 「等待协作回传」态都从线的 dataset 派生，随 innerHTML 快照序列化
  function _hgVisionFreeze(el, err) {
    if (!el || !el.isConnected) return;
    const i = el.querySelector('i');
    if (!i) return;
    const dur = fmtDur((Date.now() - (+(el.dataset.t0 || 0))) / 1000);
    i.innerHTML = err
      ? '📤 已转交 · ⚠ 识图失败 · 用时 ' + dur
      : '📤 已转交 · 📥 已回传 · 用时 ' + dur;
    el.dataset.done = String(Date.now());
    _hgPeerLineStop(el);                  // v2.35.2（P1 多槽）：停该线自己的计时器
  }
  // v2.28.3：回合终结（result/中断/进程退出）仍未回传的识图线——停表并
  // 标注，不让秒表空转到天荒地老
  function _hgVisionSweep(dead) {
    const vc = _HG.visionCalls;
    if (!vc) return;
    for (const id in vc) {
      const el = vc[id];
      const i = el && el.querySelector('i');
      if (i) i.innerHTML = '📤 已转交 · 等待结论回传' + (dead ? '（回合已结束）' : '（历史未完成）');
      if (el) el.dataset.done = String(Date.now());   // v2.35：未回传也定格（面板协作行收口）
      _hgPeerLineStop(el);              // v2.35.2（P1 多槽）：各线停各的计时器
    }
    _HG.visionCalls = null;
  }
  // v2.28：识图 MCP 转交线历史回看——静态渲染（后端已算好 dur），无计时器
  // v2.35.1（观察项补齐）：与实时线同构落 dataset（peer/t0/done/psum）——面板
  // 「协作」行与输入框等待态对两条路径一致。历史行一律定格：dur 有值用真实
  // 完成时刻（t0+dur，60s 窗自然滤掉旧行）；无值=历史未完成，不冒充在等
  function renderVisionRelayHist(l) {
    const d = document.createElement('div'); d.className = 'h-switch';
    const t0 = l.ts ? (Date.parse(l.ts) || 0) : 0;
    d.dataset.peer = '识图';
    if (t0) d.dataset.t0 = String(t0);
    if (l.dur != null) {
      d.dataset.done = String(t0 + Math.max(0, l.dur) * 1000);
    } else {
      d.dataset.done = String(t0 || Date.now());
      d.dataset.psum = '历史未完成（未回传）';
    }
    d.innerHTML = l.dur != null
      ? '<span></span><i>' + (l.err ? '📤 已转交 · ⚠ 识图失败' : '📤 已转交 · 📥 已回传')
        + ' · 用时 ' + esc(fmtDur(l.dur)) + '</i><span></span>'
      : '<span></span><i>📤 已转交 识图 · 等待结论回传（历史未完成）</i><span></span>';
    addRow(d);
  }
  function renderPeerRelay(to, t0ms) {    // 📤 已转交分割线（带等待计时）
    // v2.35.2（P1 多槽）：不再「新转交接管旧等待」——每条线自己的计时器自己
    // 走（此前新线会停掉旧线的表，旧线读秒冻死在半途；并发转交各对各的线）
    const d = document.createElement('div'); d.className = 'h-switch';
    d.innerHTML = '<span></span><i>📤 已转交 ' + esc(to || '其他会话') +
      ' · 等待结论回传 · <b class="hg-peer-t">0s</b></i><span></span>';
    addRow(d);
    const t0 = t0ms || Date.now();        // v2.3.2：历史重建传行内 ts（真实起点）
    d.dataset.t0 = String(t0);            // 快照恢复后重启计时用
    d.dataset.peer = to || '其他会话';     // v2.35：协作方名进 dataset——面板协作行/等待态派生 + 快照序列化
    renderSideStatus();                   // v2.35：面板协作行 + 输入框等待态跟随
    _hgPeerTimerStart(d, t0);
    scrollBottom();
    return d;                             // v2.28.3：识图多调用并发时按 id 对线
  }
  // v2.3.2：等待计时器独立函数——快照恢复（switchTo innerHTML 重建）后
  // 原 interval 已死、计时冻结在快照时刻；恢复路径对未定格线重挂 interval。
  // v2.35.2（P1 多槽）：计时器挂线元素（d._peerTimer）——每条线独立停/走，
  // 重挂防叠（快照恢复连点/重复恢复场景）；_HG.peerWait 仍指向最新一条
  //（识图 sweep 等旧调用方的兼容单槽）。
  function _hgPeerTimerStart(d, t0) {
    const tb = d.querySelector('.hg-peer-t');
    if (!tb) return;
    if (d._peerTimer) clearInterval(d._peerTimer);
    const timer = setInterval(() => {
      if (!tb.isConnected) { clearInterval(timer); return; }
      tb.textContent = fmtDur((Date.now() - t0) / 1000);
    }, 1000);
    d._peerTimer = timer;
    _HG.peerWait = { el: d, t0, timer };
  }
  // v2.35.2（P1 多槽）：停单条线的计时器（并释放指向它的 peerWait 单槽）
  function _hgPeerLineStop(el) {
    if (el && el._peerTimer) { clearInterval(el._peerTimer); el._peerTimer = null; }
    if (_HG.peerWait && _HG.peerWait.el === el) _HG.peerWait = null;
  }
  // v2.35.2（P1 多槽）：定格单条转交线（文案/耗时/dataset，面板与等待态收口）
  function _hgPeerLineFreeze(el, psum) {
    if (!el || !el.isConnected) return;
    _hgPeerLineStop(el);
    const i = el.querySelector('i');
    const dur = fmtDur((Date.now() - (+(el.dataset.t0 || 0) || Date.now())) / 1000);
    if (i) i.innerHTML = '📤 已转交 · 📥 已回传 · 用时 ' + dur;
    el.dataset.done = String(Date.now());
    // v2.41：定格即已回传——清 unknown/stale 残留标记。不清则迟到的真实
    // 回传打在 unknown 线上后标记滞留：面板 C 区过滤（不显 unknown/stale 线）
    // 会把「已回传」误埋掉，协作行行尾也错显「状态未知」而非用时
    delete el.dataset.unknown;
    delete el.dataset.stale;
    if (psum) el.dataset.psum = String(psum).replace(/\s+/g, ' ').trim().slice(0, 120);
    renderSideStatus();
  }
  // v2.35.2（P1 多槽）：回传到达按**协作方名**配对定格——回传事件只有发信方
  // 名（renderPeer 的 name / 代播的 from-name），与转交线的 data-peer（收信
  // 方名）同名对上；同名多条按 FIFO 取最早未定格；无匹配退最早未定格
  //（与旧单槽行为等价的兜底）。交错时序（relay1,relay2,peer1,peer2）自此
  // 各对各的线，不再串。
  function _hgPeerFreezeByName(name, text, strict) {
    // v2.35.2（R1）：排除仍被识图链路跟踪的线——并行多图各线 data-peer 同为
    // 「识图」，按名配对会误冻还在跑的兄弟线；本线 result 到达时已从
    // visionCalls delete（:2353），自身定格不受影响
    const lines = _hgPeerLines().filter(el => !el.dataset.done
        && !(_HG.visionCalls && Object.values(_HG.visionCalls).includes(el)));
    if (!lines.length) return null;
    const hit = name && lines.find(el => (el.dataset.peer || '') === name);
    if (!hit) {
      // v2.37（P1-F②）：strict 只许按名精确配对——协作包装的 task_notification
      // 用；不命中不许误冻无关在途线
      if (strict) return null;
      _hgPeerLineFreeze(lines[0], text);
      return lines[0];
    }
    _hgPeerLineFreeze(hit, text);
    return hit;
  }
  // v2.37R6（陈旧 pending 自愈）：①兜底复核——回合终结时对仍 pending 的
  // 线批量核实其 peer 转写是否存在 final result：有=定格「已回传」，无=
  // 标「状态未知」而非永久「等待中」；②显示上限——pending 超 30 分钟在
  // 秒表 tick 里标 stale（疑似残留），停表防无限秒表误导。均落 dataset
  //（随快照序列化，切会话往返不复发）。
  function _hgPeerVerifyPending() {
    const pend = _hgPeerLines().filter(el => !el.dataset.done);
    if (!pend.length || !_HG.sid) return;
    // R6 复审 C：核实上限 10 条显式化——超出部分标「未核实」（≠「状态未知」，
    // 没查过不许冒充查过）
    const checked = pend.slice(0, 10);
    const rest = pend.slice(10);
    const sidAt = _HG.sid;
    const sinces = checked.map(el => el.dataset.t0 || 0);
    fetch(`/api/harness/peer_result_check?sid=${encodeURIComponent(sidAt)}&peers=${encodeURIComponent(checked.map(el => el.dataset.peer).join(','))}&sinces=${encodeURIComponent(sinces.join(','))}`)
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok || _HG.sid !== sidAt) return;
        let changed = false;
        // R6 复审 B：端点只认 timestamp ≥ 线起点的 result（旧回合不算）——
        // found=True 才定格「已回传（转写核实补记）」；其余标「状态未知」，
        // unknown 一并清 stale（G：先 stale 后 verify 两处口径统一）
        for (const el of checked) {
          if (el.dataset.done || !el.isConnected) continue;
          if (j.results && j.results[el.dataset.peer]) {
            el.dataset.done = String(Date.now());
            // v2.41R2：unknown 必须一并清——上一回合标过 unknown 的线本次核
            // 实命中补记 done 时，若残留 unknown 会被面板 C 区过滤（不显
            // unknown/stale 线）误埋，「已回传（转写核实补记）」行消失。与
            // _hgPeerLineFreeze 的清标记保持同一不变量：定格即清残留标记
            delete el.dataset.unknown;
            delete el.dataset.stale;
            _hgPeerLineStop(el);
            const i0 = el.querySelector('i');
            if (i0) i0.innerHTML = '📤 已转交 · 📥 已回传（转写核实补记）';
            el.dataset.psum = '（转写核实补记：回传已发生）';
          } else {
            el.dataset.unknown = '1';
            delete el.dataset.stale;
            _hgPeerLineStop(el);
            const i1 = el.querySelector('i');
            if (i1) i1.innerHTML = '📤 已转交 · 状态未知（回合已结束，回传未在转写中确认）';
          }
          changed = true;
        }
        for (const el of rest) {
          if (el.dataset.done || !el.isConnected) continue;
          el.dataset.unverified = '1';   // 没查过：独立标记，不冒充状态未知
          changed = true;
        }
        if (changed) renderSideStatus();
      }).catch(() => {});
  }
  const _PEER_STALE_MS = 30 * 60 * 1000;   // 30 分钟显示上限
  function _hgPeerStaleSweep() {           // 秒表 tick 内逐秒巡检（cheap）
    flow.querySelectorAll('.h-switch[data-peer]:not([data-done]):not([data-stale])').forEach(el => {
      const t0 = +(el.dataset.t0 || 0);
      if (t0 && Date.now() - t0 > _PEER_STALE_MS) {
        el.dataset.stale = '1';
        if (el._peerTimer) { clearInterval(el._peerTimer); el._peerTimer = null; }
        const i = el.querySelector('i');
        if (i) {
          const nm = el.dataset.peer || '其他会话';
          i.innerHTML = '📤 已转交 ' + esc(nm) + ' · 疑似残留，点击核实（等待超 30 分钟）';
        }
      }
    });
  }
  function _hgPeerWaitStop(done) {        // 回传到达=定格用时；切会话=静默清理
    const w = _HG.peerWait; _HG.peerWait = null;
    if (!w) return;
    clearInterval(w.timer);
    if (w.el) w.el._peerTimer = null;
    if (done && w.el && w.el.isConnected)
      _hgPeerLineFreeze(w.el);            // 单槽兼容路径（不携带摘要——摘要走按名配对）
  }
  function renderPeer(name, text, to, noDedup) {  // 📥 回传气泡（区别于 user/AI）
    // v2.3.2：代播回传带 to（收件人 peer 名）——防串台污染。
    // v2.3.10 修致命错位（用户实锤"回传到了界面没有"）：to 是回信方写的
    // 收件人名（本会话 CLI 名如 pro-62），而转交线上写的是发信时的收件人
    // （识图会话）——两个名字方向相反，旧门控拿 to 匹配转交线必失败，
    // 代播回传被静默丢弃。改为：有任一未定格转交线即收（会话只在自己
    // 等结论时才会收到代播，且去重已兜双份；名不匹配的极端串台由
    // name 头标自说明，不再静默吞）。
    // R6 复审 H：门控补 unknown 线——「状态未知」文案替换掉「等待结论回传」
    // 后，to 门控按文本找会丢；迟到的真实回传仍要能被接收渲染。
    if (to) {
      const waiting = [...flow.querySelectorAll('.h-switch[data-peer]')]
        .some(el => !el.dataset.done
          && (el.textContent.includes('等待结论回传') || el.dataset.unknown === '1'
            || el.dataset.stale === '1'));
      if (!waiting) return;
    }
    // 去重：主会话自身 jsonl 检测与代播可能双份（空闲期回传两条链都通）。
    // R6 复审 F：历史回放路径跳过 60s 窗判重——连续多条历史回传内容相近时
    // 会被误吞（转写里每一行都是独立事实，不存双发歧义）
    if (!noDedup) {
      const sig = (text || '').slice(0, 120);
      if (renderPeer._seen && renderPeer._seen.t === sig &&
          Date.now() - renderPeer._seen.at < 60000) return;
      renderPeer._seen = { t: sig, at: Date.now() };
    }
    // v2.35.2（P1 多槽）：回传按协作方名配对定格对应转交线——并发转交/
    // 交错回传（relay1,relay2,peer1,peer2）各对各的线不串；摘要随定格写入
    // dataset（面板协作行「已回传」展示用，随快照序列化切会话可派生）
    _hgPeerFreezeByName(name, text);
    grpFinalize(false);
    endThinking(); closeRun();
    const d = document.createElement('div'); d.className = 'h-peer';
    const head = document.createElement('div'); head.className = 'h-peer-head';
    // v2.37（P1-C）：回传方头像徽标（首字母圆形色标，与模型标识同色板哈希）
    const _pn = name || '其他会话';
    head.innerHTML = `<span class="h-ava ${_hgAvaCls(_pn)}">${esc(_pn.charAt(0).toUpperCase())}</span>` +
      `📥 ${esc(_pn)} 回传`;
    d.appendChild(head);
    const b = document.createElement('div'); b.className = 'h-bubble';
    b.innerHTML = renderMd(text || '');
    d.appendChild(b);
    addRow(d);
    scrollBottom();
    return d;
  }
  // v2.20：压缩过程动态分割线。CLI 只给「开始/结束」两个信号，没有进度
  // 百分比——给真实信息：耗时秒表 + 被压缩的上下文规模，不编假数字。
  function renderCompaction(done) {
    let el = flow.querySelector('.h-switch[data-hg-compact]');
    if (!done && !el) {
      // v2.3.13：压缩分割线只归发起压缩的会话。压缩中切到别的会话，1s 计时器
      // 仍在跑，会在「当前打开的 flow」（=别的会话消息流）里新建「正在压缩」
      // 线并冻进它的快照（用户实锤「当前会话压缩，另一个会话也出现压缩显示」）。
      if (_HG.compactSid && _HG.compactSid !== _HG.sid) return;
      el = document.createElement('div');
      el.className = 'h-switch';
      el.dataset.hgCompact = '1';
      el.innerHTML = '<span></span><i></i><span></span>';
      addRow(el);
    }
    if (!el) return;
    const secs = _HG.compactT0 ? fmtDur((Date.now() - _HG.compactT0) / 1000) : '';
    // v2.28.4：压缩来源两途——窗口临近自动触发，或 /compact 手动触发
    // （CLI 2.1.267 实测 headless 下斜杠命令真实执行），分割线统一渲染，
    // 带上压缩前规模（用户问过「为啥 150K 就压」，信息透明少猜谜）
    const scale = _HG.compactUsed ? ' · 压缩前约 ' + (_HG.compactUsed / 1000).toFixed(0) + 'K tokens' : '';
    el.querySelector('i').textContent = done
      ? '上下文压缩完成' + scale + ' · 用时 ' + secs
      : '正在压缩上下文 · 已 ' + secs + scale;
    scrollBottom();
  }
  function _hgCompactionEnd() {
    if (!_HG.compacting) return;
    _HG.compacting = false;
    _HG.compactSid = null;
    clearInterval(_HG.compactTimer);
    renderCompaction(true);
    // v2.27.4：status 恢复事件若丢（result 兜底到这里），活动词一并退出特殊态
    actWord(null);
  }

  // ==================== 历史重建（切回会话时按 transcript 行还原气泡/抽屉）====
  // v2.16：从 switchTo 里抽出来，并补上 thinking 行——history 里的「思考过程」
  // 抽屉此前完全丢失（后端 transcript_for 不产出，前端也不认 role='thinking'）。
  // v2.18：重建与流式走同一条路径（renderUser(live=false) / startThinking /
  // endThinking / renderHistTool）——旧 renderHistThinking 把一轮多段 thinking
  // 合并进一个 holder 的分叉删掉，思考分段两条路径一致。
  function renderHistTool(l, hi) {
    // v2.15：与 renderToolUse 的 collapsible 分支同构的结构
    // （.h-tool.col > .h-tool-head[.h-tslots] + .h-tool-coll）。
    // v2.24 懒抽屉：正常行 body 不渲染（dataset.hi 记行号，点开 _histLazyFill
    // 现填）；错误行保持立即渲染+默认展开（错误信息不该藏）。
    const d = document.createElement('div');
    const err = !!l.err;
    d.className = 'h-tool col' + (err ? ' err open' : '');
    // v2.21：历史回放同样带工具徽章（子代理等），与流式路径一致
    const hbc = _H_TOOL_CFG[l.text] || {};
    d.innerHTML =
      `<button class="h-tool-head"><span class="h-chev">▸</span>` +
      `<span class="h-tool-name">${_hToolIco(l.text)} ${esc(_hToolLabel(l.text))}</span>` +
      (hbc.badge ? `<span class="h-tool-badge">${esc(hbc.badge)}</span>` : '') +
      `<span class="h-tslots">${statusBadge(err ? 'error' : 'completed')}</span></button>` +
      `<div class="h-tool-coll">${err ? _histToolBodyHtml(l) : ''}</div>`;
    if (hi != null) {
      d.dataset.hi = String(hi);
      d.dataset.hgLazy = err ? '' : '1';   // 错误行已填（hgLazy 空）；收起丢弃后由 Drop 重置
    }
    drawerCount(l.text);
    drawerAppend(d, 'exec');
    _hgApplyOpen(d, !!l.err);   // 重建期：恢复上次开合；无记录时错误行默认展开
  }
  function renderHistLine(l, hi) {
    if (l.role === 'peer') {          // v2.27.3：跨会话回传（识图结论）历史回看
      renderPeer(l.name, l.text, null, true);   // R6 复审 F：历史路径跳过 60s 判重
    }
    else if (l.role === 'vision_relay') {  // v2.28：识图 MCP 转交线（历史回看）
      renderVisionRelayHist(l);
    }
    else if (l.role === 'renew') {    // v2.27.23：超窗续命注入折叠为一行分割线
      renderRenew(l.text);
    }
    else if (l.role === 'audit') {    // v2.34：审计警示卡回放（v2.34.1 与实时同文本，
      grpFinalize(true);              // 由 audit log 并入；对齐实时分支先定稿上一组，
      renderAudit(l.text);            // 否则纯工具收尾回合的补审卡会挂错进前组）
    }
    else if (l.role === 'user') {
      const imgs = (l.files || []).filter(p => _HARNESS_IMG_EXT.test(p));
      const files = (l.files || []).filter(p => !_HARNESS_IMG_EXT.test(p));
      // v2.24.1 回退气泡壳化：renderUser 承担组管线边界（上一组定稿/开新组），
      // 壳化绕过管线导致思考/工具挂错组（排序乱，用户实测不可接受）——
      // 正确性优先，历史气泡恢复全渲染（懒抽屉+懒高亮已覆盖大头开销）。
      renderUser(l.text, imgs, files, false, l.ts ? new Date(l.ts).getTime() : 0);
    }
    else if (l.role === 'assistant') renderAsst(l.text, false, null, l.model || _HG.model || '');
    else if (l.role === 'thinking') {
      // v2.24 懒抽屉：历史思考段只建壳（默认收起），点开才渲染 markdown——
      // 大会话重建的大头就是几十 K 字符的 thinking 渲染
      startThinking(true);                 // 重建路径：段结构同流式，无计时动画
      if (_HG.think && _HG.think.seg && hi != null) {
        _HG.think.seg.dataset.hi = String(hi);
        _HG.think.seg.dataset.hgLazy = '1';
      } else appendThinking(l.text);       // 兜底：无行号（理论不达）
      endThinking(true);                   // hist 模式：不显示时长（不编造）、不自动收
    }
    else if (l.role === 'tool') {
      // v2.3.2：历史重建补画转交等待线——transcript 的工具行此前只画抽屉，
      // 切回/刷新后转交线凭空消失（用户实锤「绝大多数看不到读秒」）。线的
      // 起点用行内 ts（后端 v2.3.2 审计 P1 已补）；收件人取 input.to（summary
      // 对 SendMessage 恒空——审计 P1b）；若后续有 peer 行，renderPeer 定格
      if (l.text === 'SendMessage' || (l.text || '').startsWith('⚙ SendMessage')) {
        renderPeerRelay((l.input && l.input.to) || '识图会话',
                        l.ts ? new Date(l.ts).getTime() : 0);
      }
      renderHistTool(l, hi);
    }
  }

  // ==================== v2.24.1 气泡视口化（已回退）====================
  // 曾实现「壳+滚入渲染/滚出销毁」，但 renderUser/renderAsst 承担组管线边界
  // （定稿/开组/asstText 判定），壳化绕过管线 → 思考/工具挂错组。正确性
  // 优先回退；未来重做必须保留管线调用、只懒填 bubble 内容。
  // v2.24 懒抽屉：展开时按 dataset.hi 从 _HG.histAll 取原始数据现渲染
  // （快照恢复后 dataset 仍在、histAll 同生命周期在——两条路径都成立）。
  // 用户定调「闭合即丢弃」：收起时清空 body 并重置懒标记——开才消耗、
  // 合即零占用（反复开关重渲染单段 markdown ~几十 ms，可接受）。
  function _histLazyFill(el) {
    if (!el || el.dataset.hgLazy !== '1' || el.dataset.hi == null) return;
    const fill = () => {
      const l = _HG.histAll && _HG.histAll[+el.dataset.hi];
      if (!l) return;
      try {
        if (el.classList.contains('h-think-seg')) {
          const body = el.querySelector('.h-think-seg-body');
          if (body && !body.children.length) {
            body.innerHTML = renderMd(l.text || '');
            _codeLazyEnhance(body);            // v2.24 懒高亮（点开即在视口，即刻触发）
          }
        } else if (el.classList.contains('h-tool')) {
          const coll = el.querySelector('.h-tool-coll');
          if (coll && !coll.children.length) coll.innerHTML = _histToolBodyHtml(l);
        }
        el.dataset.hgLazy = '';
      } catch(_) {}
    };
    if (!_HG.histAll) {
      // v2.25：快照恢复路径 histAll 为空（switchTo 切会话时清掉防串会话，
      // 而快照恢复不拉 transcript）——先拉数据再填。否则「已点开的段」切回
      // 来展开永远空白，点了也填不上（用户实测：早起会话的历史思考点不开）
      const sidAt = _HG.sid;
      _histFetch(sidAt).then(ok => { if (ok && _HG.sid === sidAt) fill(); });
      return;
    }
    fill();
  }
  function _histLazyDrop(el) {
    if (!el || el.dataset.hi == null) return;   // 流式内容（无行号）不丢——丢了无法恢复
    try {
      if (el.classList.contains('h-think-seg')) {
        const body = el.querySelector('.h-think-seg-body');
        if (body) body.innerHTML = '';
      } else if (el.classList.contains('h-tool')) {
        const coll = el.querySelector('.h-tool-coll');
        if (coll) coll.innerHTML = '';
      }
      el.dataset.hgLazy = '1';
    } catch(_) {}
  }
  function _histToolBodyHtml(l) {
    const out = l.result ? String(l.result) : '';
    return (l.summary ? `<div class="h-tool-arg">${esc(l.summary)}</div>` : '') +
      (out ? `<div class="h-tool-out${l.err ? ' err-txt' : ''}">${esc(out.length > 4000 ? out.slice(0, 4000) + '…' : out)}</div>` : '');
  }

  // ==================== thinking 分段条目（v2.18：用户点名重写）====
  // 旧版一轮所有 thinking 挤一个抽屉正文里，分不清哪次思考；
  // 现在每段 thinking 一个可折叠条目（.h-think-seg），组头统计「思考 N 次」。
  // 段边界：text / tool_use 块到来（handleEvent 里 endThinking，调用点不变）。
  // 段起始时间存 seg.dataset.t0——快照恢复后可续算，JS 属性会丢。
  function isNearBottom() {
    return flow.scrollHeight - flow.scrollTop - flow.clientHeight < 120;
  }
  // ==================== v2.27：后台回复后切回，焦点不在最新回复 ====================
  // 根因：切走 tab 后容器 display:none，后台 SSE 照常收事件渲染，但
  // display:none 容器里 scrollBottom 全部失效（scrollHeight=0，scrollTop 写
  // 不进）——切回时视口停在离开瞬间的偏移，而内容已长出一大截。修法：
  // MutationObserver 盯容器 style（正是 switchTab 翻 display 的位置），
  // 离开时记下是否贴底，切回时若贴底强制回底一次（双 rAF 等 display:flex
  // 生效、布局回填后再滚，否则又算出 0 尺寸）。翻历史中切走的不拽底。
  let _hgLeftNearBottom = false;
  new MutationObserver(() => {
    if (wrap.style.display === 'none') {
      _hgLeftNearBottom = isNearBottom();
    } else if (_hgLeftNearBottom) {
      _hgLeftNearBottom = false;
      requestAnimationFrame(() => requestAnimationFrame(() => scrollBottom(true)));
    }
  }).observe(wrap, { attributes: true, attributeFilter: ['style'] });
  function startThinking(hist) {
    if (_HG.think && _HG.think.seg && _HG.think.seg.isConnected) return;
    const g = grpEnsure(true);
    g.think.box.style.display = '';             // v2.20：第一段思考到位，思考抽屉翻回显示
    const n = thinkSegCount(g) + 1;
    thinkSegCountSet(g, n);
    // 组头：「思考 N 次」；流式中带脉动动画，历史重建（hist）静态——
    // v2.20 修复：旧代码无条件加 anim，而定稿/重建后没人摘，已完成的会话
    // 组头还在闪（用户实测）。定稿侧 grpFinalize 也会重写为纯文本兜底。
    if (g.think.title) g.think.title.innerHTML = hist
      ? '🧠 思考 ' + n + ' 次'
      : '🧠 思考 <span class="hg-think-anim">' + n + ' 次</span>';
    const seg = document.createElement('div');
    // v2.24 懒抽屉：历史段默认收起（点开才渲染正文）；流式段保持展开
    seg.className = 'h-think-seg' + (hist ? '' : ' open');
    if (!hist) {
      seg.dataset.t0 = String(Date.now());   // hist：无真实起始时间，不存不编造
      seg.dataset.n = String(n);
    }
    seg.innerHTML =
      `<button class="h-think-seg-head"><span class="h-chev">▸</span>` +
      `<span class="h-think-seg-name">第 ${n} 段思考</span>` +
      `<span class="h-think-seg-t" data-hg-seg-t data-hg-think-t>0s</span></button>` +
      `<div class="h-think-seg-body"></div>` +
      // v2.21：段尾右下角收起钮——长思考读到尾顺手收，不用滚回顶部点头
      `<i class="h-think-seg-fold" title="收起本段">收起 ⌄</i>`;
    g.think.body.appendChild(seg);
    _HG.think = { seg, grp: g };
    if (!_grpHasAsst()) {
      // 本组还没正文 → 抽屉保持展开 + 段计时动画（thinkHeadUpdate 驱动）
      if (!hist && g.think.box.dataset.userToggled !== '1') g.think.box.classList.add('open');
      if (!hist) thinkHeadUpdate();
    } else if (!hist) {
      segHeadUpdate(seg);
    }
  }
  // 活动思考段组头状态：本组尚无 AI 正文时脉动「思考中…」，其余实时计时
  // v2.18.1：组级判据（全局 asstText 在正文切组后语义漂移——新组思考该重新脉动）
  function _grpHasAsst() {
    const g = _HG.grp;
    return !!(g && g.root && g.root.querySelector(':scope > .h-msg.asst'));
  }
  function thinkHeadUpdate() {
    const t = _HG.think;
    if (!t || !t.seg.isConnected) return;
    if (!_grpHasAsst()) {
      const te = t.seg.querySelector('[data-hg-think-t]');
      if (te) { te.innerHTML = '<span class="hg-think-anim">思考中…</span>'; }
    } else segHeadUpdate(t.seg);
  }
  // 段头计时文案（fmtDur）
  function segHeadUpdate(seg) {
    const te = seg && seg.querySelector('[data-hg-think-t]');
    if (!te) return;
    const t0 = +(seg.dataset.t0 || 0);
    te.textContent = t0 ? fmtDur((Date.now() - t0) / 1000) : '';
  }
  function appendThinking(text) {
    if (!_HG.think || !_HG.think.seg.isConnected) startThinking();
    const seg = _HG.think.seg;
    const holder = seg.querySelector('.h-think-seg-body');
    // v2.15：insertAdjacentHTML 只追加增量（innerHTML += 是 O(n²) 且丢事件）
    holder.insertAdjacentHTML('beforeend', renderMd(text));
    thinkHeadUpdate();
    scrollBottom();
  }
  function fmtDur(sec) {
    // v2.3 问题3：h/m/s 分级显示（>1h 用 h m，>1min 用 m s，否则 s）
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm' + (sec % 60 ? sec % 60 + 's' : '');
    return Math.floor(sec / 3600) + 'h' + Math.floor((sec % 3600) / 60) + 'm' + (sec % 60 ? sec % 60 + 's' : '');
  }
  function endThinking(hist) {
    const t = _HG.think;
    if (!t) return;
    _HG.think = null;
    const seg = t.seg;
    const te = seg.querySelector('[data-hg-think-t]');
    const t0 = +(seg.dataset.t0 || 0);
    if (hist || !t0) {
      // 历史重建：无真实起始时间，不编造时长
      if (te) te.textContent = hist ? '' : te.textContent;
    } else {
      if (te) te.textContent = fmtDur((Date.now() - t0) / 1000);
      // 仅当用户没碰过且在底部跟读时自动收段（正文已在段里，收起只留段头）
      if (seg.dataset.userToggled !== '1' && isNearBottom()) seg.classList.remove('open');
    }
  }

  // ==================== 工具调用渲染（源 toolConfigs + ToolRenderer + BashCommandDisplay）====================
  function statusBadge(st) {
    // running 蓝 / completed 绿 / error 红 / denied 橙
    const map = { running: ['运行中', 'b-run'], completed: ['完成', 'b-done'],
                  error: ['出错', 'b-err'], denied: ['拒绝', 'b-deny'] };
    const [txt, cls] = map[st] || ['', ''];
    return `<span class="h-tbadge ${cls}">${txt}</span>`;
  }
  function deriveStatus(res) {
    if (!res) return 'running';
    // v2.15：字段名修正。这是 SDK 的 tool_result 块，用 snake_case `is_error`
    // （后端 claude_harness.py 读的也是 is_error，本机 jsonl 里 is_error 出现
    // 3415 次、isError 0 次）。旧写法读 res.isError 恒为 undefined，deriveStatus
    // 永远返回 'completed' —— 红色「出错」徽章、row 的 err class、错误输出自动
    // 展开三条路径全部不可达，工具报错在界面上一直显示为绿色「完成」。
    if (res.is_error || res.isError) {
      const c = String(res.content || '').toLowerCase().trim();
      return _H_DENIAL.some(m => c.includes(m)) ? 'denied' : 'error';
    }
    return 'completed';
  }

  function resultText(res) {
    const c = res && res.content;
    if (typeof c === 'string') return c;
    if (Array.isArray(c)) return c.filter(b => b && b.type === 'text').map(b => b.text).join('\n');
    try { return JSON.stringify(c); } catch(_) { return String(c || ''); }
  }

  function diffHtml(oldS, newS) {
    // v2.8：真 LCS 行 diff（此前"交集着色"把未变行整段吞掉，大编辑只剩
    // 一两行——用户实测「咋可能只改了这点」。现在未变行作为上下文暗显，
    // 折叠展示改动段全貌；改动段外超 3 行的未变区间折叠成「… N 行不变」）
    const ol = String(oldS || '').split('\n'), nl = String(newS || '').split('\n');
    const n = ol.length, m = nl.length;
    // LCS 动态规划（O(n*m) 内存；Edit 的 old/new 一般几十行，可承受，
    // 超大输入（>4000 行）退回旧交集法防卡顿）
    if (n * m > 4000 * 4000) {
      let h = '';
      nl.forEach(l => { if (!ol.includes(l)) h += `<div class="d-add">+ ${esc(l)}</div>`; });
      ol.forEach(l => { if (!nl.includes(l)) h += `<div class="d-del">- ${esc(l)}</div>`; });
      return h || '<div class="d-info">(无文本差异)</div>';
    }
    const dp = Array.from({length: n + 1}, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = ol[i] === nl[j] ? dp[i+1][j+1] + 1 : Math.max(dp[i+1][j], dp[i][j+1]);
    // 回溯产出 op 序列：'=' 上下文 / '+' 增 / '-' 删
    const ops = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (ol[i] === nl[j]) { ops.push(['=', ol[i]]); i++; j++; }
      else if (dp[i+1][j] >= dp[i][j+1]) { ops.push(['-', ol[i]]); i++; }
      else { ops.push(['+', nl[j]]); j++; }
    }
    while (i < n) { ops.push(['-', ol[i++]]); }
    while (j < m) { ops.push(['+', nl[j++]]); }
    // 改动段外的长未变区间折叠（≤3 行直显，>3 行收成一行摘要）
    let h = '';
    const CTX = 3;
    let k = 0;
    const mark = (op, line) => {
      h += op === '=' ? `<div class="d-ctx">${esc(line)}</div>`
          : op === '+' ? `<div class="d-add">+ ${esc(line)}</div>`
          : `<div class="d-del">- ${esc(line)}</div>`;
    };
    while (k < ops.length) {
      // 当前位置往前/后各留 CTX 行上下文；中间的长等值段折叠
      if (ops[k][0] === '=') {
        // 量出这段等值长度
        let e = k;
        while (e < ops.length && ops[e][0] === '=') e++;
        const len = e - k;
        const prevIsChange = k > 0;                      // 前面是改动段 → 头部留 CTX
        const nextIsChange = e < ops.length;             // 后面是改动段 → 尾部留 CTX
        let from = k, to = e;
        if (prevIsChange && nextIsChange && len > CTX * 2) {
          for (let x = k; x < k + CTX; x++) mark('=', ops[x][1]);
          h += `<div class="d-info">… ${len - CTX * 2} 行不变 …</div>`;
          for (let x = e - CTX; x < e; x++) mark('=', ops[x][1]);
        } else if (prevIsChange && !nextIsChange && len > CTX) {
          for (let x = k; x < k + CTX; x++) mark('=', ops[x][1]);
          h += `<div class="d-info">… ${len - CTX} 行不变 …</div>`;
        } else if (!prevIsChange && nextIsChange && len > CTX) {
          h += `<div class="d-info">… ${len - CTX} 行不变 …</div>`;
          for (let x = e - CTX; x < e; x++) mark('=', ops[x][1]);
        } else {
          for (let x = k; x < e; x++) mark('=', ops[x][1]);
        }
        k = e;
      } else { mark(ops[k][0], ops[k][1]); k++; }
    }
    return h || '<div class="d-info">(无文本差异)</div>';
  }
  function todoHtml(todos) {
    const ICO = { completed: '✅', in_progress: '🔄', pending: '⬜' };
    return (todos || []).map(t =>
      `<div class="t-item"><span>${ICO[t.status] || '⬜'}</span><span>${esc(t.activeForm || t.content || t.subject || '')}</span></div>`).join('');
  }

  // 连续同名工具分组（源 toolGrouping.ts：run≥2 → 折叠为一行 ×N + preview）。
  // 流式场景 tool_result 事件只往已有行上挂状态、不新增行，所以 run 的边界
  // 是"新视觉元素"：文本/thinking 块、异名或折叠类工具、用户消息、result。
  // 分组成员（第 2 个起）不单独渲染，其结果状态聚合到组头（错误显红）。
  function closeRun() { _HG.run = null; }
  function toolRunPush(name, row) {
    const r = _HG.run;
    if (r && r.name === name) {
      r.rows.push(row);
      row._grouped = true; row._groupHead = r.head;
      const named = r.rows.slice(0, 2).map(x => x._preview).filter(Boolean);
      const extra = r.rows.length - named.length;   // 按实际拼出条数计（源 buildGroupPreview）
      const arg = r.head.querySelector('.h-tool-arg');
      if (arg) arg.textContent = `×${r.rows.length}  ${named.join(', ')}${extra > 0 ? `, +${extra} more` : ''}`;
      return true;   // 已并入组，不单独显示
    }
    _HG.run = { name, head: row, rows: [row] };
    return false;
  }

  function renderToolUse(b, isSub, subId) {
    const name = b.name || '';
    const id = b.id || ('anon' + (++_HG.uidN));
    const cfg = _hCfg(name);
    const label = _hToolLabel(name);
    if (cfg.mode === 'hidden') return;

    // 注意：这里不 closeRun——run 的边界是文本/thinking/用户消息/result；
    // tool_use 本身若是同名工具正是 run 的延续，由 toolRunPush 判定并入组。
    let row;
    if (cfg.mode === 'one-line') {
      row = document.createElement('div');
      row.className = 'h-tool' + (isSub ? ' sub' : '');
      const sec = cfg.sec ? cfg.sec(b.input) : '';
      row.innerHTML =
        `<span class="h-tool-name">${_hToolIco(name)} ${esc(label)}</span>` +
        `<span class="h-tool-arg">${esc(cfg.get(b.input) || '')}</span>` +
        (sec ? `<span class="h-tool-sec">${esc(sec)}</span>` : '') +
        `<span class="h-tslots"></span>`;
      // Bash 类：命令可复制（源 action:'copy'；点击由 flow 委托处理，v2.12）
      if (cfg.kind === 'bash') {
        const cp = document.createElement('button');
        cp.className = 'h-tool-copy'; cp.textContent = '复制'; cp.title = '复制命令';
        row.appendChild(cp);
      }
    } else {
      // collapsible：折叠组（左边框按类别着色，源 CollapsibleDisplay）
      row = document.createElement('div');
      row.className = 'h-tool col' + (isSub ? ' sub' : '') + (cfg.defaultOpen ? ' open' : '');
      row.style.setProperty('--h-accent', _H_KIND_COLOR[cfg.kind] || 'var(--border)');
      const title = typeof cfg.title === 'function' ? cfg.title(b.input) : (cfg.title || label);
      let bodyHtml = '';
      const v = cfg.get ? cfg.get(b.input) : '';
      if (cfg.kind === 'diff') bodyHtml = `<div class="h-diff">${diffHtml(v.old, v.neu)}</div>`;
      else if (cfg.kind === 'todo') bodyHtml = todoHtml(v.todos || v);
      else if (cfg.kind === 'question') bodyHtml = (v || []).map(q =>
        `<div class="t-item"><span>❓</span><span><b>${esc(q.header || '')}</b> ${esc(q.question || '')}${(q.options || []).map(o => `<span class="q-opt">${esc(typeof o === 'string' ? o : o.label)}</span>`).join('')}</span></div>`).join('');
      else bodyHtml = `<div class="h-tool-body">${renderMd(String(v))}</div>`;
      row.innerHTML =
        `<button class="h-tool-head"><span class="h-chev">▸</span>` +
        `<span class="h-tool-name">${_hToolIco(name)} ${esc(title)}</span>` +
        (cfg.badge ? `<span class="h-tool-badge">${esc(cfg.badge)}</span>` : '') +
        `<span class="h-tslots"></span></button><div class="h-tool-coll">${bodyHtml}</div>`;
    }
    row._preview = (cfg.mode === 'one-line' ? cfg.get(b.input) : (typeof cfg.title === 'function' ? cfg.title(b.input) : label)) || '';
    row._name = name;
    row._cfg = cfg;
    row._id = id;
    row.dataset.tid = id;                 // 快照恢复后重扫挂 rowById 用
    // v2.35：子代理内部工具行挂 parent id——点击重开实时窗格（P0-2）
    if (isSub && subId) row.dataset.hgSub = subId;
    _HG.rowById[id] = row;
    // v2.21：子代理行运行秒表——子代理一跑几分钟，主流毫无动静，没有
    // 秒表就像卡死。完成时由 renderOneToolResult 清表。
    if (cfg.kind === 'agent' && !isSub) {
      const slot = row.querySelector('.h-tslots');
      const t0 = Date.now();
      row._agentTimer = setInterval(() => {
        if (slot) slot.innerHTML = statusBadge('running') +
          ' <span class="h-tsec">' + Math.round((Date.now() - t0) / 1000) + 's</span>';
      }, 1000);
    }
    drawerCount(name);                    // v2.7：计数进抽屉组头（Bash×3 · Read×5 …）
    // v2.8：抽屉时代不再合并同名 run——每条 Bash/Read/Grep 调用都是独立过程行
    // （用户明确要能看到每一次执行；组头徽章已承担"×N 汇总"职责）
    _HG.run = { name, head: row, rows: [row] };
    drawerAppend(row, 'exec');             // v2.11：过程行进执行抽屉（不再散落消息流）
    // v2.32 面板：活动流记录（ring buffer 20 条；历史回放不记只看实时）
    if (!_HG.openState)
      _hgActPush({ tid: id, name, label, preview: row._preview || '', kind: cfg.kind, t0: Date.now() });
  }

  // 工具结果挂接（源 shouldHideToolResult：成功藏、错误永远显）
  function renderToolResult(o) {
    const c = o.message && o.message.content;
    const blocks = Array.isArray(c) ? c : [];
    // v2.15：一条 user 消息可携带多个 tool_result（并行工具调用一次全回）。
    // 旧实现用 find() 只取首个 → 其余工具行永远停在「运行中」，结果与错误
    // 都不显示。后端 transcript_for 也是按 trs 全量遍历的，这里对齐。
    const trs = blocks.filter(b => b && b.type === 'tool_result');
    if (!trs.length) return;
    for (const tr of trs) renderOneToolResult(tr);
  }

  function renderOneToolResult(tr) {
    const row = _HG.rowById[tr.tool_use_id];
    if (!row) {
      // 无对应行（transcript 重建的孤立结果）→ 单行摘要（v2.7：也进抽屉）
      const txt = resultText(tr).slice(0, 120);
      const d = document.createElement('div');
      d.className = 'h-tool-res';
      d.textContent = txt ? '↳ ' + txt.replace(/\s+/g, ' ') : '↳ (完成)';
      drawerAppend(d, 'exec');
      return;
    }
    const cfg = row._cfg || {};
    const st = deriveStatus(tr);
    if (!_HG.openState) _hgActDone(tr.tool_use_id, st);   // v2.32 面板：活动流定格
    // v2.21：子代理秒表收表（历史重建/分组恢复无 timer，置空无妨）
    if (row._agentTimer) { clearInterval(row._agentTimer); row._agentTimer = null; }
    // 分组成员：结果状态聚合到组头（成功不刷组头徽章避免闪烁，错误标红）
    const showRow = row._grouped ? row._groupHead : row;
    const slots = showRow.querySelector('.h-tslots');
    if (slots && st !== 'completed') slots.innerHTML = statusBadge(st);
    else if (slots && !row._grouped) slots.innerHTML = statusBadge(st);
    // v2.21：子代理完成摘要——点开折叠体才见报告太隐身，徽章旁给
    // 报告首行 60 字（悬浮看前 400 字）；全文仍在折叠体
    if (cfg.kind === 'agent' && st === 'completed' && !row._grouped && slots) {
      const full = resultText(tr).replace(/\s+/g, ' ').trim();
      if (full) slots.innerHTML = statusBadge(st) +
        ` <span class="h-tagent-brief" title="${esc(full.slice(0, 400))}">${esc(full.slice(0, 60))}${full.length > 60 ? '…' : ''}</span>`;
    }
    showRow.classList.toggle('err', st === 'error' || st === 'denied');
    // 结果折叠体（成功默认藏，错误永远显）
    const hideOk = cfg.result === 'hide' || cfg.kind === 'bash' || cfg.kind === 'diff';
    const txt = resultText(tr);
    if (row._grouped) {
      // 分组成员：状态已聚合到组头，输出不单独展示（组头 err 红底足够辨识）
      return;
    }
    if (st !== 'completed' && txt) {
      // 错误：展开显示
      const body = row.querySelector('.h-tool-coll') || (() => {
        row.classList.add('col');
        const h = document.createElement('button'); h.className = 'h-tool-head';
        h.innerHTML = `<span class="h-chev">▸</span><span class="h-tool-name">输出</span><span class="h-tslots"></span>`;
        const co = document.createElement('div'); co.className = 'h-tool-coll';
        row.appendChild(h); row.appendChild(co);
        row.style.setProperty('--h-accent', 'var(--neon-red, #e06c75)');
        return co;
      })();
      row.classList.add('open');
      const pre = document.createElement('div');
      pre.className = 'h-tool-out err-txt';
      pre.textContent = txt.slice(0, 4000);
      body.appendChild(pre);
    } else if (!hideOk && txt && txt !== '(no content)') {
      // 成功但有内容（WebFetch/Grep 等配置允许展示）→ 收进折叠体（默认收起）
      const body = row.querySelector('.h-tool-coll');
      if (body) {
        const pre = document.createElement('div');
        pre.className = 'h-tool-out';
        const lines = txt.split('\n').length;
        pre.textContent = txt.length > 8000 ? txt.slice(0, 8000) + '…' : txt;
        body.appendChild(pre);
        if (cfg.kind === 'bash') {
          // 行数提示（源 BashCommandDisplay）
          row.querySelector('.h-tool-sec') || row.insertAdjacentHTML('beforeend', `<span class="h-tool-sec">${lines} 行输出</span>`);
        }
      }
    } else if (cfg.kind === 'bash' && txt) {
      // bash 成功输出：折叠体默认收起 + 行数提示
      const body = row.querySelector('.h-tool-coll') || (() => {
        row.classList.add('col');
        const h = document.createElement('button'); h.className = 'h-tool-head';
        h.innerHTML = `<span class="h-chev">▸</span><span class="h-tool-name">输出</span><span class="h-tslots"></span>`;
        const co = document.createElement('div'); co.className = 'h-tool-coll';
        row.appendChild(h); row.appendChild(co);
        return co;
      })();
      const pre = document.createElement('div');
      pre.className = 'h-tool-out';
      pre.textContent = txt.length > 8000 ? txt.slice(0, 8000) + '…' : txt;
      body.appendChild(pre);
      row.insertAdjacentHTML('beforeend', `<span class="h-tool-sec">${txt.split('\n').length} 行</span>`);
    }
    // tool_result 只挂状态不新增行——不终结 run（源 rendersNothing 不打断连续 run）
  }

  // ==================== 活动指示（源 ActivityIndicator）====================
  // v2.19：原来它是一条独立的横栏，杵在输入卡上方（带边框、停止钮），用户
  // 点名「这个栏不要了」——改成输入卡底部行里的一个小胶囊，和上下文环并排。
  // 停止钮一并删除：右下角那颗圆钮本就是停止态（setBusy 已切成 ■ + stopGen），
  // 同一动作两个入口，留着只是噪音。
  const _ACT_WORDS = ['思考中', '处理中', '分析中', '执行中', '检索中', '推理中'];
  let _actWordIdx = 0;
  function actStart(sinceMs) {
    if (_HG.activity) return;
    // v2.26：计时起点优先用后端的 busy_since——切会话回来/自愈纠偏时
    // 不能从「现在」重新计时（用户实锤：执行中切走再切回，计时被清 0）
    _HG.actStart = sinceMs || Date.now();
    _actWordIdx = 0;
    actEl.style.display = 'inline-flex';
    actEl.innerHTML = `<span class="hg-act-dot"></span><span class="hg-act-word" data-hg-aw>思考中</span><span class="hg-act-t" data-hg-act-t>0s</span>`;
    _HG.activity = {
      verb: setInterval(() => {
        // v2.27.4：压缩等特殊状态（actWord 设的 hg-act-special）词固定不轮换
        // ——原实现 4s 必换词，把「正在压缩上下文…」顶掉，用户实测只显示一瞬。
        const w = actEl.querySelector('[data-hg-aw]');
        if (!w || w.classList.contains('hg-act-special')) return;
        _actWordIdx = (_actWordIdx + 1) % _ACT_WORDS.length;
        w.textContent = _ACT_WORDS[_actWordIdx];
      }, 4000),
      tick: setInterval(() => {
        const t = actEl.querySelector('[data-hg-act-t]');
        if (t) t.textContent = fmtDur((Date.now() - _HG.actStart) / 1000);
      }, 1000),
    };
  }
  function actStop() {
    if (!_HG.activity) return;
    clearInterval(_HG.activity.verb); clearInterval(_HG.activity.tick);
    _HG.activity = null;
    actEl.style.display = 'none';
  }
  // v2.7：压缩等特殊状态覆盖活动词（word=null 恢复轮换）
  function actWord(word) {
    if (!actEl || actEl.style.display === 'none') return;
    const w = actEl.querySelector('[data-hg-aw]');
    if (!w) return;
    if (word) { w.textContent = word; w.classList.add('hg-act-special'); }
    else { w.textContent = _ACT_WORDS[_actWordIdx]; w.classList.remove('hg-act-special'); }
  }

  // ==================== 上下文用量环（v2.3 问题4：替代金额显示）====================
  // v2.16 口径修正：旧实现把 result 事件 usage 的 input+cache_read+cache_creation
  // +output 相加当作「上下文用量」，但那算的是**本轮消耗量**——cache_read 是缓存
  // 命中的读取量，一轮十几万属正常且便宜，多轮对话里它必然累积撞满窗口，于是
  // 环恒为满环、橙色警示恒亮（用户实测标题「上下文 5941.0K / 200.0K tokens（100%）」,
  // 5941K ≈ 本会话 30 轮的 Σ）。一个恒满的指标等于没有指标。
  // 真正该表达的是「离上限还有多远」= 最近一轮喂进模型的输入总量
  // （input + cache_read + cache_creation；output 是产出，不占输入窗口）。
  // 窗口取 modelUsage.<model>.contextWindow（CLI 权威值），缺失回退 256K。
  // 切回旧会话/重开 tab 时 result 事件不重放，故按 sid 持久化恢复。
  const _HG_CTX_FALLBACK = 256000;
  function _hgCtxKey(sid) { return 'hg-ctx:' + sid; }
  function _hgCtxRestore(sid) {
    let v = null;
    if (sid) { try { v = JSON.parse(localStorage.getItem(_hgCtxKey(sid)) || 'null'); } catch(_) {} }
    const s = _HG.sessions.find(x => x.sid === sid);
    const mname = (s && s.model) || (_HG.models && _HG.models.default) || '';
    // v2.27.16：记忆窗口带模型归属校验（renderCtxRing 同款）——旧记录无
    // model 字段或与当前模型不符 → 丢弃窗口值，按模型名重推，防 [1M] 会话
    // 残留的 1M 分母跟着小窗口模型走（Lanz-Auto 虚报 /1000.0K）。
    const sameModel = v && mname &&
      (v.model || '').toLowerCase() === mname.toLowerCase();
    if (v && v.used > 0 && v.used <= (v.max || _HG_CTX_FALLBACK) && sameModel)
      _hgDrawCtxRing(v.used, v.max || _HG_CTX_FALLBACK);
    else _hgDrawCtxRing(0, /1m/i.test(mname) ? 1000000 : _HG_CTX_FALLBACK);
    // v2.20：记忆里的 max 可能是旧代码存的 256K 兜底值（1M 模型被压成
    // /256K、84% 虚报，用户实测）——恢复路径同样按模型名校正窗口并写回，
    // 别只靠每轮结束的 _hgCtxPoll 纠偏。
    if (/1m/i.test(mname) && ((v && v.max) || 0) < 1000000) {
      const used = (v && v.used > 0) ? v.used : 0;
      _hgDrawCtxRing(used, 1000000);
      try { localStorage.setItem(_hgCtxKey(sid), JSON.stringify({used, max: 1000000, model: mname})); } catch(_) {}
    }
  }
  function _hgDrawCtxRing(used, ctxMax, note) {
    const pct = Math.min(100, used / ctxMax * 100);
    // v2.6：viewBox 与 CSS 显示尺寸一致（24），r=10 + stroke 3 → 直径 23 < 24 不裁边；
    // 此前 r=9 贴 viewBox 边缘，缩放裁切导致"圆环爆掉"
    const VB = 24, R = 10, C = 2 * Math.PI * R;
    const col = pct >= 95 ? 'var(--neon-red, #e06c75)'
              : pct >= 80 ? 'var(--neon-orange, #d29922)' : 'var(--accent)';
    const fmtTok = n => n >= 1000 ? (n / 1000).toFixed(1) + 'K' : n;
    costEl.innerHTML =
      `<svg class="hg-ctx-ring" viewBox="0 0 ${VB} ${VB}">` +
      `<circle cx="${VB / 2}" cy="${VB / 2}" r="${R}" fill="none" stroke="var(--border)" stroke-width="3"/>` +
      `<circle cx="${VB / 2}" cy="${VB / 2}" r="${R}" fill="none" stroke="${col}" stroke-width="3"` +
      ` stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - pct / 100)}"` +
      ` stroke-linecap="round" transform="rotate(-90 ${VB / 2} ${VB / 2})"/></svg>` +
      `<span class="hg-ctx-pct">${Math.round(pct)}%</span>`;
    // v2.20：0 用量（新会话/未统计）不冒充 256K 假窗口，title 直说待统计；
    // v2.21：note 允许调用方替换占位说明（压缩后待首轮）
    costEl.title = used > 0
      ? `当前上下文 ${fmtTok(used)} / ${fmtTok(ctxMax)} tokens（${Math.round(pct)}%）`
      : (note || '上下文用量：首轮回复后统计');
    costEl.classList.toggle('warn', pct >= 80);
    _hgDynDirty();   // v2.32 面板：上下文行跟随（localStorage 即数据总线，零新轮询）
  }
  function renderCtxRing(o) {
    const u = o.usage || {};
    const used = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) +
                 (u.cache_creation_input_tokens || 0);
    if (typeof used !== 'number' || used <= 0) return;
    let ctxMax = _HG_CTX_FALLBACK;
    const mu = o.modelUsage || {};
    for (const k in mu) {
      // v2.20（3.png 假 100%）：取全部 entry 的最大窗口，不再见好就收——
      // 网关可能把子代理/识图等小窗口模型与主模型一起报上来，首个 entry
      // 若是小窗（如 256K），真实用量被小分母放大成假满环。
      if (mu[k] && typeof mu[k].contextWindow === 'number' && mu[k].contextWindow > ctxMax) {
        ctxMax = mu[k].contextWindow;
      }
    }
    // v2.20（3.png 假 100%）：used > ctxMax = 网关把全会话累计口径塞进了
    // 单轮 usage（实测 ~20 轮 × ~70K ≈ 1.4M，clamp 后恒显 100%）。单轮真实
    // 用量物理不可能超窗（超了 API 直接报错，不会有 success result）——
    // 必是坏数据：丢弃本轮，环保留上一轮合法值。
    if (used > ctxMax) return;
    // v2.20：本事件没带 modelUsage（assistant 事件就不带）→ 沿用该会话上次
    // 记到的窗口，避免没 result 校准时就退 256K 假分母
    // v2.27.16：记忆窗口带模型归属。切方案/切模型后旧 max 不可继承——
    // [1M] 会话残留的 1000000 分母让 Lanz-Auto 虚报 /1000.0K（用户实锤
    // 85.3K 显示 9%）。归属不符或旧记录无 model 字段 → 按当前模型名重推
    // （带 [1M]/[1m] → 1M，其余 256K 兜底），下次写入带上模型名自愈。
    if (ctxMax === _HG_CTX_FALLBACK && _HG.sid) {
      let rec = null;
      try { rec = JSON.parse(localStorage.getItem(_hgCtxKey(_HG.sid)) || 'null') || {}; } catch(_) { rec = {}; }
      const cur = (o.model || _HG.model || '').toLowerCase();
      if (rec.max && cur && (rec.model || '').toLowerCase() === cur) {
        ctxMax = rec.max;
      } else {
        ctxMax = /1m/.test(cur) ? 1000000 : _HG_CTX_FALLBACK;
      }
    }
    _hgDrawCtxRing(used, ctxMax);
    if (_HG.sid) { try { localStorage.setItem(_hgCtxKey(_HG.sid), JSON.stringify({used, max: ctxMax, model: o.model || _HG.model || ''})); } catch(_) {} }
  }

  // v2.20：每轮结束（result/interrupted/exit 任意原因）拉一次真实上下文用量。
  // v2.21：改为 5s 定时轮询（用户要求实时刷新）——后端 /ctx 是 jsonl 尾部
  // 1MB 倒扫，单次几毫秒，5s 一次无性能感；生成中 jsonl 也在流式落盘，
  // 能看到上下文实时增长。页面隐藏时跳过、上一请求未回时不再叠加。
  let _hgCtxInFlight = false;
  function _hgCtxPoll() {
    if (!_HG.sid || _hgCtxInFlight) return;
    const sid = _HG.sid;
    _hgCtxInFlight = true;
    fetch('/api/harness/ctx?sid=' + encodeURIComponent(sid))
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok || j.sid !== _HG.sid) return;
        // v2.20：中断轮次没有 result → 接口 window=0 → 前端曾退 256K 假分母
        // （1M 模型显示成 /256K，84% 虚高）。模型名带窗口线索（glm-5.3[1M]）
        // 时按名推断，兜住没有任何 result 校准过的会话。
        let win = j.window || 0;
        if (!win && /1m/i.test(j.model || (_HG.model || ''))) win = 1000000;
        // v2.21：压缩后尚未有新轮次 → jsonl 主链读数已归零，环也归零，
        // 不能继续画压缩前的旧值（用户实测 708K 残留）
        if (!(j.used > 0)) {
          if (j.compacted) _hgDrawCtxRing(0, win || _HG_CTX_FALLBACK, '上下文已压缩 · 首轮回复后统计');
          return;
        }
        renderCtxRing({ usage: { input_tokens: j.used },
                        modelUsage: win ? { _w: { contextWindow: win } } : null });
      }).catch(() => {})
      .finally(() => { _hgCtxInFlight = false; });
  }
  setInterval(() => { if (!document.hidden) _hgCtxPoll(); }, 5000);

  function setBusy(b, sinceMs) {
    _HG.busy = b;
    conn.tab.querySelector('.led').classList.toggle('on', b);
    sendBtn.classList.toggle('stop', b);
    sendBtn.title = b ? '停止生成' : '发送（Enter）';
    sendBtn.setAttribute('aria-label', b ? '停止生成' : '发送');
    stateEl.textContent = b ? '' : (_HG.alive ? '就绪' : '');
    _hgInputState();   // v2.35：输入框提示按运行态/子代理/协作等待派生（P0-1②③；空闲文案同 v2.20）
    if (b) actStart(sinceMs);
    else { actStop(); queuePump(); _hgCtxPoll(); }
    _hgDynDirty();   // v2.32 面板：状态区运行态徽章/计时跟随
  }
  // v2.26:busy 状态自愈——SSE 事件丢失/断线重连竞态会让前端 _HG.busy 与
  // 后端真实状态脱节(用户实锤「AI 在工作但显示未在应答」,活动指示器消失)。
  // 5s 轮询会话列表纠偏,指示器永远反映后端真实 busy;计时起点同步用
  // busy_since(切会话回来不清零,用户实锤)。
  setInterval(() => {
    if (document.hidden || !_HG.sid || !_HG.sse) return;
    fetch('/api/harness/sessions').then(r => r.json()).then(j => {
      if (!j || !j.ok) return;
      const s = (j.sessions || []).find(x => x.sid === _HG.sid);
      if (s && !!s.busy !== _HG.busy) setBusy(!!s.busy, s.busy_since);
    }).catch(() => {});
  }, 5000);

  // ==================== CLI 事件 → 渲染 ====================
  function handleEvent(o) {
    const typ = o.type;
    if (typ === 'system') {
      const sub = o.subtype;
      if (sub === 'init') {
        _HG.alive = true;
        // v2.35（P0-1）：stream-json 每回合起跑都发一条 system/init（stdin 开着
        // 实测）——第 2 个起=CLI 自发新回合（后台任务完成通知/协作回传续跑）。
        // 后端同规则已补置 busy（会话列表 5s 自愈轮询的方向源头），前端这里
        // 即时亮运行态不等轮询；revive 重启的新进程首 init 不在此列（闭包级
        // 计数跨 revive 连续，靠后端 send() 占位的路径不受影响）。
        _HG.initN = (_HG.initN || 0) + 1;
        if (_HG.initN > 1 && !_HG.busy) setBusy(true);
        else if (!_HG.busy) setBusy(false);
      } else if (sub === 'task_started' || sub === 'task_progress'
                 || sub === 'task_notification') {
        // v2.35（P1-4/P0-1②）：Task 生命周期系统事件（主链事件、不带
        // parent_tool_use_id，但带 tool_use_id 指回 Task 调用）——
        // · task_started：is_backgrounded 标记后台代理（主回合 result 不收
        //   掉它，收尾等 task_notification）；tool_use 事件丢失时兜底建行
        // · task_progress/task_notification：CLI 侧计的子代理用量
        //   （total_tokens/tool_uses/duration_ms）——assistant.message.usage
        //   被网关置零（实测 input/output 恒 0），这是唯一可靠用量源
        const tid = o.tool_use_id;
        // v2.37（P1-F①）：task_id → 友好名映射（协作行显示「审核·#2」这类，
        // 裸 id 收 title）
        if (o.task_id) {
          const lb = _AGENT_LABEL[o.subagent_type] || o.subagent_type || '';
          if (lb) _HG.peerNames[o.task_id] = lb;
        }
        // v2.37（P1-E）：协作包装（后台+非角色类型）——不开窗格（旧版本误开
        // 的空白 tab 就地清掉），但建 collab 档案供面板 C 区协作行展示；
        // 回传定格走下方严格配对（task_notification 无档案分支同款）
        if (sub === 'task_started'
            && _isCollabWrap(o.subagent_type, o.is_backgrounded)) {
          _subDrop(tid);
          if (tid) {
            (_HG.agents || (_HG.agents = {}))[tid] = {
              type: o.subagent_type || 'Task', desc: o.description || '',
              t0: Date.now(), done: false, doneAt: 0,
              collab: true, bg: true, taskId: o.task_id || '' };
            renderSideStatus();
          }
        } else if (tid) {
          if (!_HG.agents && sub === 'task_started') _HG.agents = {};
          let a = _HG.agents && _HG.agents[tid];
          if (!a && _HG.agents && sub === 'task_started') {
            // 兜底建档（Task tool_use 已建档时零改动）：t0 用当下近似
            a = _HG.agents[tid] = {
              type: o.subagent_type || 'Task', desc: o.description || '',
              t0: Date.now(), done: false, doneAt: 0 };
          }
          if (a) {
            if (sub === 'task_started') {
              a.bg = !!o.is_backgrounded;
              a.taskId = o.task_id || '';
            } else {
              // v2.35.1（F3）：用量与收尾解耦——task_notification 是完成信号，
              // usage 缺失（失败态通知常见）也必须收档，否则面板/输入框永久
              // 卡「运行中」；有 usage 才记 tokens/工具数
              if (o.usage) {
                a.tokens = o.usage.total_tokens || 0;
                a.toolN = o.usage.tool_uses || 0;
              }
              if (sub === 'task_notification' && !a.done) {
                a.done = true; a.doneAt = Date.now();
                a.err = !!(o.status && o.status !== 'completed'
                           && o.status !== 'success');
                a.result = String(o.summary || '').trim().slice(0, 400) || a.result;
                _subClose(tid, a.err);
              }
            }
            renderSideStatus();
          }
        }
        // v2.37（P1-F②）：协作包装的完成通知——严格按名配对定格对应转交线
        // （不命中不兜底，防误冻无关在途线）。对有档案的真实子代理同样尝试
        // （它们无转交线，strict 不命中即 no-op）
        // v2.39 勘误：旧注释称「task_id 即 to 的 agentId 实测同源」——实为
        // CLI 包装新 id 与 to 恒不相等（回传气泡不显示的根因，见下）
        if (sub === 'task_notification') {
          const sum = String(o.summary || '').trim().slice(0, 120);
          // v2.39：SendMessage 续派的包装任务——task_id 是 CLI 包装新 id，
          // 先按建线时记的 tool_use_id→to 映射反查原线名（peerSent），命中
          // 即原线精确配对；原有 task_id/subagent_type 两级兜底不变。
          const sentTo = (_HG.peerSent || {})[o.tool_use_id];
          const _hit = _hgPeerFreezeByName(sentTo, sum, true)
              || _hgPeerFreezeByName(o.task_id, sum, true)
              || _hgPeerFreezeByName(o.subagent_type, sum, true);
          if (_hit) renderSideStatus();
          // v2.37R3（复审C）：仅协作语境上报（该 task 是 collab 档案，或本
          // 会话存在 pending 转交线）——普通 Task 子代理完成不记，防
          // paired=false 淹没取证信号；同源假设失效案例仍全落日志
          const _rec = tid ? ((_HG.agents || {})[tid] || {}) : {};
          if (_rec.collab || _hgPeerPending()) {
            try {
              fetch('/api/harness/peer_pair_log', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sid: _HG.sid, task: o.task_id || '',
                                       name: (_hit && _hit.dataset.peer) || '', ok: !!_hit }) })
                .catch(() => {});
            } catch(_) {}
          }
        }
      } else if (sub === 'status') {
        // v2.7：压缩状态（实测 CLI 事件：status:"compacting" 开始 / "requesting" 恢复）
        // v2.20：压缩是长动作（几十秒），只在底栏小胶囊提示不够醒目——
        // 消息流里插动态分割线（耗时秒表 + 压缩对象规模；CLI 不吐进度
        // 百分比，不编假数字）
        if (o.status === 'compacting') {
          if (!_HG.compacting) {
            _HG.compacting = true;
            _HG.compactSid = _HG.sid;   // v2.3.13：归属会话——计时器不许把线画进别的会话
            _HG.compactT0 = Date.now();
            try { _HG.compactUsed = (JSON.parse(localStorage.getItem(_hgCtxKey(_HG.sid)) || 'null') || {}).used || 0; } catch(_) { _HG.compactUsed = 0; }
            grpFinalize(true);
            renderCompaction(false);
            clearInterval(_HG.compactTimer);
            _HG.compactTimer = setInterval(() => {
              if (!_HG.compacting) return clearInterval(_HG.compactTimer);
              renderCompaction(false);
            }, 1000);
          }
          actWord('正在压缩上下文…');
        } else {
          if (_HG.compacting) _hgCompactionEnd();
          actWord(null);
        }
      } else if (sub === 'api_error' || sub === 'error') {
        renderRaw('⚠ ' + (o.error ? JSON.stringify(o.error).slice(0, 200) : JSON.stringify(o).slice(0, 200)));
      }
    } else if (typ === 'assistant') {
      const blocks = (o.message || {}).content || [];
      const isSub = !!o.parent_tool_use_id;
      // v2.35（P0-1 兜底）：主链 assistant 事件到达而前端还认为空闲 = 一条
      // 没观察到起点的回合正在跑（后端同规则已置 busy，这里即时亮，不等
      // 5s 自愈轮询——轮询间隔内徽章空窗正是用户看到的「运行状态消失」）
      if (!isSub && !_HG.busy && _HG.sid) setBusy(true);
      // v2.20：网关下 result 事件的 usage 常缺失（用户实测环恒 0%）——
      // assistant 事件的 message.usage 同口径（转写实测有值：input+cache_read+
      // cache_creation），到达即刷环，不依赖 result
      if (!isSub && (o.message || {}).usage)
        renderCtxRing({ usage: o.message.usage, modelUsage: o.modelUsage });
      // v2.35（P1-4）：子代理实跑模型——assistant 事件自带 message.model
      // （网关映射后的真名，优先于 frontmatter 预显示），首见即记入档案
      if (isSub && o.parent_tool_use_id && (o.message || {}).model
          && _HG.agents && _HG.agents[o.parent_tool_use_id]) {
        const _sa = _HG.agents[o.parent_tool_use_id];
        if (_sa.model !== o.message.model) {
          _sa.model = o.message.model;
          if (_sub.tabs[o.parent_tool_use_id]
              && _sub.tabs[o.parent_tool_use_id].model !== o.message.model) {
            _sub.tabs[o.parent_tool_use_id].model = o.message.model;
            _subTabsPaint();
          }
          renderSideStatus();
        }
      }
      for (const b of blocks) {
        if (b.type === 'thinking' && b.thinking) { closeRun(); appendThinking(b.thinking); }
        else if (b.type === 'text' && b.text && b.text.trim()) { endThinking(); closeRun(); renderAsst(b.text, isSub, o.parent_tool_use_id, isSub ? null : ((o.message || {}).model || _HG.model || '')); }
        else if (b.type === 'tool_use') {
          endThinking();
          // v2.32 面板：TodoWrite 更新任务清单 + 首见时刻打标（事件无时间戳，
          // 近似值）+ 记最近清单行 id（点任务项跳消息流用）
          if (b.name === 'TodoWrite' && b.input && Array.isArray(b.input.todos)) {
            _HG.todos = b.input.todos;
            const d = _hgDyn(), now = Date.now();
            if (b.id) d.todoRowId = b.id;
            for (const t of _HG.todos) {
              const key = t.content || '';
              if (!(key in d.todoSeen)) d.todoSeen[key] = now;
            }
            renderSideStatus();
          }
          if ((b.name === 'Task' || b.name === 'Agent') && b.id && !isSub) {
            // v2.37（P1-E）：协作包装（后台+非角色类型）——SendMessage 委托的
            // 独立会话被 CLI 包装成后台 Task：无本会话事件流，开实况 tab 必
            // 空白。不开 tab、不建代理档（C 区协作行由同委派的转交线派生，
            // 数据源单一不重复）；旧版本已开的空白 tab 就地清掉
            const _ty = (b.input && (b.input.subagent_type || b.input.agent_type)) || b.name;
            if (_isCollabWrap(_ty, b.input && b.input.run_in_background)) {
              _subDrop(b.id);
            } else {
              (_HG.agents || (_HG.agents = {}))[b.id] = {
                type: _ty,
                desc: (b.input && b.input.description) || '',
                t0: Date.now(), done: false, doneAt: 0,
                // v2.35（P1-4）：起跑即预显模型——~/.claude/agents frontmatter
                // （_hgAgentModels 惰拉缓存）；子代理事件到达后以实跑
                // message.model 覆盖。读不到（内置代理 Explore/Plan 等）标「主链模型」
                model: _hgAgentModelPre(_ty) };
              _subOpen(b.id, _HG.agents[b.id].type, _HG.agents[b.id].desc);   // v2.33：窗格开 tab
            }
            renderSideStatus();
          }
          // v2.32 面板：回合内工具计数（主流工具；子代理内部调用不算）
          if (!isSub && b.name !== 'TodoWrite') _hgDyn().turnTools++;
          // v2.28.5：识图双通道——网关名（主通道，服务端执行无本地事件）与
          // 本地名 mcp__vision__analyze_image（兜底，客户端执行）。客户端执行
          // 的识图调用出 📤 转交线+秒表（替代工具卡），tool_result 到达时
          // 定格对应线并渲染 📥 回传气泡；按 id 记线，并行多图各对各的线
          if (!isSub && (b.name === 'mcp__vision__analyze_image'
                         || b.name === 'mcp__4_5v_mcp__analyze_image')) {
            const el = renderPeerRelay('识图');
            (_HG.visionCalls || (_HG.visionCalls = {}))[b.id] = el;
          } else {
            renderToolUse(b, isSub, o.parent_tool_use_id);
            // v2.27.3：转交识图/其他会话 = 强过程反馈，分割线比收起的工具行显眼
            // v2.39：记 tool_use_id → to 映射——SendMessage 续派后台代理时 CLI
            // 包装成新 Task，task_notification.task_id 是包装后的新 id，与线的
            // data.peer(=input.to) 永不相等 → strict 配对恒 miss → 线被标「状态
            // 未知」回传气泡不显示（用户实锤）。notification 时按 tool_use_id
            // 反查此映射即命中原线。
            if (!isSub && b.name === 'SendMessage' && b.input && b.input.to) {
              (_HG.peerSent || (_HG.peerSent = {}))[b.id] = b.input.to;
              renderPeerRelay(b.input.to);
            }
          }
        }
      }
      // v2.33：子代理消息分流进实时窗格（主 flow 照旧画灰色 sub 行，双处显示）
      if (isSub) _subFeed(o.parent_tool_use_id, blocks);
      scrollBottom();
    } else if (typ === 'user') {
      // v2.3.12：/compact 摘要行不渲染——它是模型续命记忆，显示成用户气泡是噪音
      // （历史重建路径后端已拦成 renew 行，这里挡实时流里漏网的）
      if (o.isCompactSummary) return;
      const c0 = (o.message || {}).content;
      // v2.33：子代理内部的 tool_result 也分流进窗格（user 事件同带
      // parent_tool_use_id；不属于已跟踪 tab 的忽略）
      if (Array.isArray(c0) && o.parent_tool_use_id && _sub.tabs[o.parent_tool_use_id])
        for (const b of c0)
          if (b && b.type === 'tool_result') _subResult(o.parent_tool_use_id, b);
      // v2.32 面板：子代理回场——tool_result 对上在跑的 Task 即完成，
      // 顺手存结果摘要/失败标志（面板完成行展示用，纯前端两行）
      // v2.35：后台 Task（run_in_background）的 tool_result 只是「已派出」
      // 确认——代理还在跑，收尾等 task_notification（bg 标记来自 task_started）
      if (Array.isArray(c0) && _HG.agents) {
        let hitAgent = false;
        for (const b of c0) {
          if (b && b.type === 'tool_result' && _HG.agents[b.tool_use_id]
              && !_HG.agents[b.tool_use_id].done
              && !_HG.agents[b.tool_use_id].bg) {
            const a = _HG.agents[b.tool_use_id];
            a.done = true;
            a.doneAt = Date.now();
            a.err = !!b.is_error;
            a.result = resultText(b).slice(0, 400);
            // v2.38：agentId 落档——Task tool_result 文本自带「agentId: xxx」
            //（与 task_started 的 task_id 同源），回放窗格靠它定位子代理转写
            a.agentId = a.taskId
              || (resultText(b).match(/agentId:\s*([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
            _subClose(b.tool_use_id, a.err);   // v2.33：窗格 tab 定格 ✓/✗
            hitAgent = true;
          }
        }
        if (hitAgent) renderSideStatus();
      }
      // v2.28.3：识图 MCP 回传——按 tool_use_id 在 pending 线里对号，
      // 定格它自己的分割线+渲染 📥 气泡（并行多图互不串线）
      if (Array.isArray(c0) && _HG.visionCalls) {
        const tr = c0.find(b => b && b.type === 'tool_result'
          && _HG.visionCalls[b.tool_use_id]);
        if (tr) {
          const el = _HG.visionCalls[tr.tool_use_id];
          delete _HG.visionCalls[tr.tool_use_id];
          const vtxt = Array.isArray(tr.content)
            ? tr.content.filter(x => x && x.type === 'text').map(x => x.text).join('\n')
            : String(tr.content || '');
          // 先定格本线再画气泡。renderPeer 的按名配对已排除识图跟踪中的线
          // （v2.35.2 R1），不会误冻还在跑的并行兄弟线；下方 pw 摘还仅剩
          // 单槽兼容兜底路径在用
          const pw = _HG.peerWait;
          _HG.peerWait = null;
          _hgVisionFreeze(el, !!tr.is_error);
          renderPeer('识图', vtxt.trim() || '（识图失败，无返回内容）');
          if (pw && pw.el !== el) _HG.peerWait = pw;   // 他线还在等，还回去继续计时
          scrollBottom();
          return;
        }
      }
      // v2.27.3：跨会话回传（识图结论等）——专属气泡，不再凭空消失
      let peerText = '';
      if (typeof c0 === 'string' && c0.trim().startsWith('Another Claude session sent a message'))
        peerText = c0;
      else if (Array.isArray(c0)) {
        const tb = c0.find(b => b && b.type === 'text' && typeof b.text === 'string'
          && b.text.trim().startsWith('Another Claude session sent a message'));
        if (tb) peerText = tb.text;
      }
      if (peerText) {
        const nm = peerText.match(/from-name="([^"]*)"/);
        const body = peerText.match(/<cross-session-message[^>]*>([\s\S]*)<\/cross-session-message>/);
        renderPeer(nm ? nm[1] : '其他会话', (body ? body[1] : peerText).trim());
        return;
      }
      // v2.37（P1-F②）：agent-message 通知形态的协作回传——CLI 对 agent 会话
      // （含 SendMessage 委托的独立会话/协作包装 task）回传的另一包装，此前
      // 不被任何回传路径识别：原始 XML 被当普通 user 气泡渲染、对应转交线
      // 永远停在「等待结论回传」。识别→提取发信方与正文→renderPeer（内部
      // 按名配对定格转交线）。v2.37R2（复审5）：必须开闭标签对齐才判——
      // 用户手打的半个 <agent-message 标签不得误触发
      let agMsg = '';
      const _AG_MSG_RE = /<agent-message[^>]*>[\s\S]*<\/agent-message>/;
      if (typeof c0 === 'string' && _AG_MSG_RE.test(c0)) agMsg = c0;
      else if (Array.isArray(c0)) {
        const tb2 = c0.find(b => b && b.type === 'text' && _AG_MSG_RE.test(b.text || ''));
        if (tb2) agMsg = tb2.text;
      }
      if (agMsg) {
        const anm = agMsg.match(/from-name="([^"]*)"/) || agMsg.match(/\bname="([^"]*)"/);
        const abody = agMsg.match(/<agent-message[^>]*>([\s\S]*?)<\/agent-message>/);
        renderPeer(anm ? anm[1] : '协作代理',
                   (abody ? abody[1] : agMsg.replace(/<[^>]+>/g, '')).trim());
        return;
      }
      // 用户真实消息打断工具 run；工具结果事件不动 run（rendersNothing 思想）
      if (!Array.isArray(c0) || !c0.some(b => b && b.type === 'tool_result')) closeRun();
      const hasToolResult = Array.isArray(c0) && c0.some(b => b && b.type === 'tool_result');
      if (!o.isSynthetic && hasToolResult) {
        renderToolResult(o);
        scrollBottom();
      }
    } else if (typ === 'result') {
      _hgCompactionEnd();                  // v2.20：status 恢复事件若丢，result 兜底收压缩态
      endThinking();
      closeRun();
      _hgVisionSweep(true);                // v2.28.3：回合终结算清未回传的识图线
      // v2.32：回合终结——还在跑的子代理统一收尾（收不到 tool_result 的
      // 结束都不标失败；中断/退出的收尾在各自分支标「已中断」）
      _hgAgentsSweep(false);
      _subEnd();                           // v2.33：窗格收起（跑完随回合结束消失）
      _hgPeerVerifyPending();              // v2.37R6（兜底复核②）：pending 线追溯核实
      _hgTurnEnd(o.subtype === 'success' ? 'ok' : 'error',
                 typeof o.duration_ms === 'number' ? o.duration_ms : 0);
      grpFinalize(true);                   // v2.18：本轮组定稿——用户没手动
                                          // 操作过且在底部跟读时自动收起（想看再点开，
                                          // 各抽屉独立开合）
      _hgGrantRewind();                    // v2.28.15：回合定稿——回滚按钮授予最后一条 AI 消息
      // v2.3 问题4：不显示金额，显示上下文用量环（⭕ 百分比，256K 实窗口径）
      renderCtxRing(o);
      setBusy(false);
      if (o.subtype && o.subtype !== 'success')
        renderRaw(`⚠ 回复异常结束：${o.subtype}${o.result ? ' — ' + String(o.result).slice(0, 200) : ''}`);
      refreshSessions();
    }
  }

  // ==================== SSE ====================
  function openSSE(sid, afterSeq) {
    if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
    _HG.initN = 0;   // v2.35：init 计数随流重置——新流首个 init=进程待机，不算回合起跑（跨会话/重开 tab 不残留）
    if (!sid) return;
    const es2 = new EventSource(`/api/harness/stream?sid=${encodeURIComponent(sid)}&after_seq=${afterSeq || 0}`);
    _HG.sse = es2;
    es2.onmessage = (ev) => {
      let it;
      try { it = JSON.parse(ev.data); } catch(_) { return; }
      // v2.25：防重放——EventSource 断线自动重连用的还是创建时的旧
      // after_seq，后端把缓冲事件从旧位置重发一遍：user_echo 重放 × 乐观
      // 去重窗口已被首次消费清空 → 用户消息画出两条（用户实测「蹦出来
      // 两条我发的命令」）。同一会话内 seq 严格递增，≤当前值的一律是重放。
      if (it.seq) {
        if (it.seq <= _HG.seq) return;
        _HG.seq = it.seq;
      }
      // v2.5：先 setBusy（弹活动指示条，改变 flow 高度）再渲染消息——
      // 渲染内部 scrollBottom 含 rAF 二次兜底，否则指示条挤出消息导致刚发的消息不在底
      if (it.kind === 'user_echo') {
        setBusy(true);
        // v2.20：乐观渲染 → echo 到达即跳过（echoFast 只顶一条，连发两条
        // 相同文本时第二条照常走事件渲染，不会吞）
        if (_HG.echoFast && _HG.echoFast.text === (it.text || '')) _HG.echoFast = null;
        else if (!_hgEchoDup(it)) renderUser(it.text, it.images, it.files);
      }
      else if (it.kind === 'event') handleEvent(it.data);
      else if (it.kind === 'peer') { grpFinalize(true); renderPeer(it.name, it.text, it.to); }
      else if (it.kind === 'renew') { grpFinalize(true); renderRenew(it.text); }
      // v2.34：审计警示（light 回合结算违规）——回合已终结，定稿当前组再出红卡
      else if (it.kind === 'audit') { grpFinalize(true); renderAudit(it.text); scrollBottom(); }
      else if (it.kind === 'raw') renderRaw(it.text);
      else if (it.kind === 'ask') { grpFinalize(true); askRender(it); }
      else if (it.kind === 'ask_done') askDone(it);
      else if (it.kind === 'interrupted') {
        endThinking(); _hgVisionSweep(true); grpFinalize(true); renderExit(it.text); setBusy(false);
        // v2.32：中断收尾——在跑的子代理标「已中断」（原缺口：只有 result
        // 分支收尾，点 ■ 停止后子代理假"运行中"+计时狂跳）
        _hgAgentsSweep(true); _hgTurnEnd('interrupt', 0);
        _subEnd();                         // v2.33：窗格收起
        // v2.15：通知 stopGen 兜底逻辑「事件到了」，别重复收尾
        try { document.dispatchEvent(new CustomEvent('hg-interrupted', {detail: _HG.sid})); } catch(_) {}
      }
      else if (it.kind === 'exit') {
        endThinking(); _hgVisionSweep(true); _HG.alive = false; grpFinalize(true); renderExit(it.text); setBusy(false);
        _hgAgentsSweep(true); _hgTurnEnd('exit', 0);   // v2.32：同上，进程退出也收
        _subEnd();                         // v2.33：窗格收起
      }
      // v2.20：会话内切模型 → 消息流插一条分割线（「已切换模型 · xxx」）
      else if (it.kind === 'model_switched') {
        grpFinalize(true);
        renderSwitch(it.text || '默认模型');
      }
    };
  }

  // ==================== 会话切换 ====================
  function _hgHasHistory(sid) {
    const s = _HG.sessions.find(x => x.sid === sid);
    return !!(s && s.has_history);
  }
  function saveCache() {
    if (!_HG.sid) return;
    // v2.28.13：echoFast 随快照保存——切走时 2420 行会清空它，但快照 html
    // 里已经带着乐观渲染的用户气泡；若 user_echo 尚未到达（快速切走），
    // 切回来重放的 echo 对不上已清空的去重窗口 → 双画（用户实锤 A→B→A
    // 出两条同文消息）。随快照存取，恢复后重放 echo 仍能命中跳过。
    // v2.37（P0-A）：窗口账目随快照存——恢复路径重建 histStart/histLive，
    // 使滚动扩收机制在快照态重新成立（此前快照恢复后 histLive=false 且
    // histStart 丢失，上滑扩段被 v2.35.2 的门拦死，历史够不着）
    _HG.cache[_HG.sid] = { html: flow.innerHTML, seq: _HG.seq,
                           echoFast: _HG.echoFast || null,
                           histStart: _HG.histStart, histLive: _HG.histLive };
    // v2.25：快照 LRU 上限 10——大会话 innerHTML 每份可达数十 MB，无上限
    // 来回切会话会攒爆内存（审计 §三.8）
    const keys = Object.keys(_HG.cache);
    for (const k of keys.slice(0, Math.max(0, keys.length - 10))) delete _HG.cache[k];
  }
  // ==================== v2.24 滚动窗口式历史加载（大会话 DOM 瘦身）====================
  // 根因（对照实验闭环）：大会话数千条消息全量渲染 → 数万 DOM 节点，即便
  // harness tab 切走（display:none）仍拖累渲染进程（内存/GC）——所有拖动
  // （文件拖入/命令库排序/tab 换位）卡 ~12s；空会话不卡、关 tab 恢复。
  // 方案（用户定调：省 + 流畅第一）：恢复会话只渲染尾部 HIST_PAGE 条；
  // 上滑到顶自动扩一段；拉回底部自动收缩回尾部段——DOM 恒定 1~2 段。
  // 扩/收都从新起点全量重渲（renderHistLine 顺序敏感：thinking/工具归组依赖
  // 时序，prepend 乱序会组错乱），扩段锚定滚动、收缩回贴底。
  function _histRender(lines, start) {
    _HG.lastTs = 0;   // v2.24.5：重建期时间条从零起算（第一条 user 带时间）
    // v2.24 CAP：正常模式渲染起点不得越过 capStart（翻阅上限）——更早的
    // 历史只能进「只读禅模式」看（_roEnter），保住正常模式的 DOM 省流
    const capStart = Math.max(0, lines.length - _HG.HIST_CAP);
    start = Math.max(start, capStart);
    start = Math.min(start, lines.length);   // v2.37R2（复审4）：上界钳制——账目越界时 slice 为空只剩错误计数
    _HG.histAll = lines;
    _HG.histStart = start;
    _HG.histLive = true;   // v2.35.2：窗口渲染完成——histAll/DOM 建立对应，滚动扩收自此放行
    flow.innerHTML = '';
    if (start > 0) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      // v2.24.2：上滑到顶一律进只读禅模式（busy 时不能重渲主 flow——会炸掉
      // 流式中的活组；CAP 上限同理）——文案统一，行为一致
      bar.innerHTML = '📖 剩 ' + start + ' 条更早消息——<b>点击进入只读模式</b>查看';
      // 点击走 flow 级事件委托（下方绑定一次）：bar 在扩/收/重渲中反复重建，
      // 直绑 onclick 一旦在某次重建竞态中丢失就永久点不动（用户实锤「又不好使了」）
      flow.appendChild(bar);
    }
    if (!lines.length) return;
    _HG.noScroll = true;                        // v2.16：逐行 append 不反复重排
    _HG.openState = _hgLoadOpen(_HG.sid);       // 上次开合状态（重建期贴回）
    try {
      // v2.28.16：边渲染边标回合边界——assistant 行之后的下一条 user 行
      // 意味着该回合已收尾，最后一条 AI 消息授予回滚按钮；流末尾的回合
      // （后面没有 user 行）在循环外补授（它就是最新定下的回合）
      let lastAsst = null;
      lines.slice(start).forEach((l, i) => {
        renderHistLine(l, start + i);
        // v2.37R4（DOM 收缩）：行尾戳——每行渲染完后在 flow 最后一个元素上
        // 记「到此为止已含第 hi 行」。增量收缩按戳定位头部边界（无戳孩子
        // 属于下一个带戳孩子=同一条线的先导元素），账目与 DOM 恒一致
        const _last = flow.lastElementChild;
        if (_last) _last.dataset.hEnd = String(start + i);
        // v2.30：回放恢复最新任务清单（TodoWrite 的 input 里有 todos）
        if (l.role === 'tool' && l.text === 'TodoWrite'
            && l.input && Array.isArray(l.input.todos)) _HG.todos = l.input.todos;
        // v2.32 面板：回放重建最近的子代理条目（无精确时刻→显示「历史」，
        // 不参与 sweep；只留最近 5 条防长会话堆积）
        if (l.role === 'tool' && (l.text === 'Task' || l.text === 'Agent')
            && l.input && (l.input.description || l.input.subagent_type || l.input.agent_type)) {
          const d = _hgDyn();
          d.agentsRpl = d.agentsRpl || [];
          // v2.38：从结果文本提取 agentId——历史条目的回放窗格靠它定位转写
          const _aid = (l.result && String(l.result).match(/agentId:\s*([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
          d.agentsRpl.push({
            type: l.input.subagent_type || l.input.agent_type || 'Task',
            desc: l.input.description || '', t0: 0, done: true, doneAt: 0, replay: true,
            agentId: _aid });
          if (d.agentsRpl.length > 5) d.agentsRpl.shift();
        }
        if (l.role === 'assistant') lastAsst = _HG.lastAsstEl;
        else if (l.role === 'user' && lastAsst && lastAsst.dataset.rwa) {
          lastAsst.classList.add('can-rewind');
          lastAsst = null;
        }
      });
      if (lastAsst && lastAsst.dataset.rwa) lastAsst.classList.add('can-rewind');
      renderSideStatus();     // v2.30：回放后刷新侧栏动态（todos 已从工具行重建）
    }
    finally { _HG.noScroll = false; _HG.openState = null; }
  }

  let _histBusy = false;   // 重渲期间防 scroll 重入
  // v2.37R4（DOM 收缩）：增量摘头——目标保留尾部 HIST_PAGE 行。按行尾戳
  // （dataset.hEnd，_histRender 逐行落）划组：无戳孩子属于下一个带戳孩子
  // （同一条线的先导元素），整组同进退。无任何戳（旧快照 DOM）=安全放弃。
  // 视口用 scrollHeight 差回锚 scrollTop——可见内容一个像素都不动。
  // 账目联动：histStart 同步前移（saveCache 存的就是收缩后的窗口值，
  // rewind 双钳制不受影响）；扩段（上滑）仍走 _histRefresh 全量重渲，
  // 账目由 _histRender 重建，往复互逆不漂移
  function _hgShrinkHead() {
    if (!_HG.histAll || !_HG.histAll.length) return;
    const keepStart = _HG.histAll.length - _HG.HIST_PAGE;
    const children = [...flow.children];
    const before = flow.scrollHeight;
    let newStart = -1;
    let i = 0;
    // v2.37R5（终审·严重）：内层扫戳触底=尾部无戳（实时追加的活动内容），
    // 视作保留区——带标签 break 出外层，统一落到函数尾收尾。旧实现此处
    // return 硬退：已摘的组不回滚，而 histStart/入口条/scrollTop 回锚全被
    // 跳过 → 消息流只剩活动尾、历史无入口、断裂态被 saveCache 存档。
    // 纯无戳旧快照（一次都没摘，newStart<0）仍走静默放弃。
    outer: while (i < children.length) {
      const group = [children[i]];
      let hEnd = (children[i].dataset && children[i].dataset.hEnd != null)
        ? +children[i].dataset.hEnd : null;
      let j = i;
      while (hEnd == null) {
        j++;
        if (j >= children.length) break outer;   // 尾部无戳=保留，收尾
        group.push(children[j]);
        if (children[j].dataset && children[j].dataset.hEnd != null) {
          hEnd = +children[j].dataset.hEnd;
        }
      }
      if (hEnd >= keepStart) break;              // 触到保留区，摘头结束
      for (const g of group) g.remove();
      newStart = hEnd + 1;
      i = j + 1;
    }
    if (newStart < 0) return;                    // 纯无戳：零摘除，安全放弃
    _HG.histStart = newStart;
    // 视口锚定：scrollTop 减去被移除的高度，无闪屏无跳动
    // （先按纯摘除量回锚，再插入口条并补偿其高度——v2.37R6：此前锚定在
    // 插条之后、用「摘除量-条高」的差值，每轮收缩视口净上漂一条高度）
    flow.scrollTop = Math.max(0, flow.scrollTop - (before - flow.scrollHeight));
    // 头部若仍有更早历史，重建只读入口条（原条已随头部组摘除）
    if (newStart > 0 && !flow.querySelector('.hg-hist-more')) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      bar.innerHTML = '📖 剩 ' + newStart + ' 条更早消息——<b>点击进入只读模式</b>查看';
      flow.insertBefore(bar, flow.firstChild);
      flow.scrollTop += bar.offsetHeight;        // 条插入头部 → 视口同步下移补偿
    }
  }
  // v2.25：只拉 transcript 存 histAll、不重渲——快照恢复路径补数据用
  // （切会话时 histAll 被清防串会话，快照里「已点开」的懒段要补填就得有数据）
  async function _histFetch(sidAt) {
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return false;
      _HG.histAll = j.lines || [];
      return true;
    } catch(_) { return false; }
  }
  // v2.24.11 扩/收缩前必须重拉 transcript：histAll 是切会话时拉的快照，
  // 流式期间的新消息（用户刚发的+AI 回复）不在里面——直接用旧快照重渲会
  // 把它们从界面上抹掉（用户实测「消息突然没了」；jsonl 完好=纯显示层丢失）
  async function _histRefresh(sidAt, start) {
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return;   // 会话已切走，弃
      const lines = j.lines || [];
      _histRender(lines, start == null ? lines.length - _HG.HIST_PAGE : start);
    } catch(_) {}
  }
  // 主层「进入只读模式」提示条：事件委托（绑一次永在，bar 重建不丢点击）
  flow.addEventListener('click', (e) => {
    const bar = e.target.closest('.hg-hist-more');
    if (bar && flow.contains(bar)) { e.stopPropagation(); _roEnter(); }
  });
  // v2.28.16：回滚按钮事件委托——按消息文本锚点回滚（每个定下的回合边界
  // 都可回滚到那里）。按钮 innerHTML 随气泡生成/随快照克隆，直绑 onclick
  // 会丢（同 h-macts 既有解法），flow 级委托一次永在
  flow.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-hg-rewind]');
    if (!btn || !flow.contains(btn)) return;
    e.stopPropagation();
    if (_HG.busy) { showBanner('AI 正在回复，结束后再回滚', 2400, true); return; }
    if (!_HG.sid) { showBanner('当前没有活动会话', 2000, true); return; }
    const host = btn.closest('.h-msg.asst');
    const anchor = host && host.dataset.rwa;
    if (!anchor) { showBanner('这条消息没有回滚锚点', 2400, true); return; }
    btn.disabled = true;
    try {
      const r = await fetch('/api/harness/rewind', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid, anchor})});
      const j = await r.json();
      if (!j.ok) { showBanner('回滚失败：' + (j.err || '未知'), 3600, true); return; }
      showBanner('⏪ ' + j.msg, 3600);
      await _hgReloadFlow();
    } catch(err) { showBanner('回滚失败：' + err, 3000, true); }
    btn.disabled = false;
  });
  flow.addEventListener('scroll', () => {
    // v2.35.2（P0 切会话信息丢失根因）：histLive 门——histAll 只有在真正的
    // 窗口渲染（_histRender，含扩/收缩重渲）之后才与 DOM 建立对应关系；
    // 快照恢复路径的懒段补填（_histFetch）也会填 histAll，但 histStart 停在
    // 0、DOM 是快照内容——此时滚动窗口判定（shown=全长-0>100 且在底部 →
    // 收缩重渲）会把刚恢复的消息流整个炸掉重拉转写（用户实锤「切走再切回
    // 全部重新刷新」）。非窗口态一律不进扩/收缩分支；懒段展开按 hi 索引取
    // 数据不受影响。
    if (!_HG.histAll || !_HG.histLive || _HG.busy || _histBusy) return;
    const nearTop = flow.scrollTop <= 60;
    const distBottom = flow.scrollHeight - flow.scrollTop - flow.clientHeight;
    const shown = _HG.histAll.length - _HG.histStart;
    if (nearTop && _HG.histStart > 0) {
      // 上滑到顶：自动扩一段，锚定滚动（视觉位置不跳）。到 CAP 上限或
      // busy 时不再扩也不自动进只读（用户定调 v2.24.8：只读模式仅点击
      // 提示条进入——上滑自动进在回底部途中误触，烦人）
      const capStart = Math.max(0, _HG.histAll.length - _HG.HIST_CAP);
      if (_HG.histStart > capStart && !_HG.busy) {
        _histBusy = true;
        const anchorH = flow.scrollHeight - flow.scrollTop;
        const sidAt = _HG.sid;
        _histRefresh(sidAt, _HG.histStart - _HG.HIST_PAGE).then(() => {
          flow.scrollTop = flow.scrollHeight - anchorH;
          requestAnimationFrame(() => { _histBusy = false; });
        });
      }
    } else if (distBottom <= 4 && shown > _HG.HIST_PAGE * 2
               && Date.now() - (_HG.histRestoredAt || 0) > 400
               && Date.now() - (_HG.lastShrinkAt || 0) > 500) {
      // 拉回底部收缩（DOM 瘦身）：v2.37R4 改**增量收缩**——直接摘除头部
      // 整组节点+histStart 前移，不再 _histRefresh 全量重渲。旧实现重拉
      // 转写重渲=闪屏（v2.35.2 起被 histLive 门拦死=DOM 无限膨胀），增量
      // 方案两者兼得：账目与 DOM 恒一致，无闪屏、无网络请求。
      // v2.37R6（P0 回归收紧）：触发判据从 ≤80px 收到 ≤4px（真正贴底）——
      // 80px 时长距下行中途即触发，摘头+回锚把用户视口反复上提（📖 条
      // 插入再叠加 30px 下移偏差），与扩段形成拉锯=「拉不到底」的体感；
      // 另加 500ms 速率限制兜残余循环
      _HG.lastShrinkAt = Date.now();
      _hgShrinkHead();
    }
  }, { passive: true });

  // ==================== v2.3.11 只读模式（独立积木 harness-readonly.js）====================
  // ZCode 方案完整重构：默认只显结论，「已工作 Xs」总开关分级展开过程（思考/
  // 工具行二级折叠）。实现全部在 web/js/harness-readonly.js（window.HgReadonly），
  // 这里只做依赖注入薄适配——闭包助手打包传过去，零全局耦合。
  function _roDeps() {
    return {
      _HG, wrap,
      esc, mdBubble, renderMd, attChipsHtml, statusBadge,
      toolIco: _hToolIco, toolLabel: _hToolLabel, toolBodyHtml: _histToolBodyHtml,
      lazyFill: _histLazyFill, lazyDrop: _histLazyDrop,
      openLightbox,          // v2.3.12：只读层附件 chip 点开预览（委托经 deps 注入）
      timeFmt: _timeFmt, fmtDur, imgExt: _HARNESS_IMG_EXT,
      onEmpty: () => { const bar = flow.querySelector('.hg-hist-more');
                       if (bar) bar.innerHTML = '⚠ 没有可查阅的历史'; }
    };
  }
  function _roEnter() {
    // 主层「进入只读」提示条入口（事件委托绑在 flow click）。失败必须上屏——
    // 静默会让用户以为按钮坏了。快照恢复路径 histAll 为空时先拉再进（v2.25）。
    try {
      if (!window.HgReadonly) throw new Error('只读模块未加载（harness-readonly.js 缺失）');
      if (!_HG.histAll || !_HG.histAll.length) {
        const sidAt = _HG.sid;
        if (!sidAt || _HG._roFetching) return;
        _HG._roFetching = true;
        _histFetch(sidAt).then(ok => {
          _HG._roFetching = false;
          if (_HG.sid !== sidAt) return;
          if (ok) _roEnter();
          else {
            const bar = flow.querySelector('.hg-hist-more');
            if (bar) bar.innerHTML = '⚠ 历史拉取失败——<b>点击重试</b>';
          }
        });
        return;
      }
      window.HgReadonly.enter(_roDeps());
    } catch (e) {
      console.error('[只读模式]', e);
      const bar = flow.querySelector('.hg-hist-more');
      if (bar) bar.innerHTML = '⚠ 只读模式打开失败: ' + esc(String(e)) + '（点击重试）';
    }
  }
  function _roExit() {
    if (window.HgReadonly) window.HgReadonly.exit();
  }

  async function switchTo(sid, keepInput) {
    if (sid === _HG.sid && flow.querySelector('.h-msg, .hg-welcome')) {
      // v2.15：点的是当前会话 → 早返回。但 busy 卡死时用户正是靠「重点一下
      // 当前会话」自救，这里不能什么都不做：至少按后端真实值纠偏一次。
      if (sid) {
        // v2.35.2（P0 加固）：SSE 归属校验——历史竞态（切换竞速/早返回）可能
        // 让 _HG.sse 停在别的会话的流上：内容看着正常、事件永远不来。归属
        // 不符即重开本会话流（after_seq 用当前 seq，不重放已渲染事件）。
        try {
          const own = _HG.sse && _HG.sse.url
            && _HG.sse.url.includes('sid=' + encodeURIComponent(sid));
          if (!own) openSSE(sid, _HG.seq);
        } catch(_) {}
        fetch(`/api/harness/events?sid=${encodeURIComponent(sid)}&after_seq=${_HG.seq}`)
          .then(r => r.json())
          .then(j => { if (j.ok && _HG.sid === sid) { setBusy(!!j.busy, j.busy_since); if (j.busy) phResume(); } })
          .catch(() => { if (_HG.sid === sid) setBusy(false); });
      }
      return;
    }
    saveCache();
    const prevSid = _HG.sid;            // v2.3.0：旧会话 id（未发送附件暂存归属）
    closePop(); closeMention();
    setQuote(null);                     // v2.27：引用属于当前输入草稿，切会话不跨带
    _hgPeerWaitStop();                  // v2.27.5：转交等待计时器不跨会话残留
    endThinking(); closeRun();
    if (_HG.grp) phStopTimer(_HG.grp);   // v2.18：防御性清占位 timer（isConnected 自杀是兜底）
    _hgMentionReset();          // v2.15：@ 引用高亮不跨会话残留
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;   // v2.18：组级抽屉
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false;   // v2.24：多段历史渲染源不复用（防串会话）；v2.35.2：histLive 随切重置（快照恢复态不进滚动扩收）
    _HG.todos = null; _HG.agents = null;     // v2.30：会话动态随会话切换重置（todos 由回放重建）
    _HG.dyn = null;                          // v2.32 面板派生态不跨会话（活动流/回合史/打标全重建）
    _subReset();                             // v2.33：子代理实时窗格不跨会话
    _HG.think = null; _HG.noScroll = false; _HG.openState = null;   // v2.16：重建态不跨会话残留
    _HG.sid = sid; _HG.seq = 0; _HG.alive = false;
    // v2.15：dirty 语义修正。旧实现只在「发送成功」置 true、只在
    // switchTo(null) 置 false —— 冷启动自动进的是历史会话（has_history），
    // dirty 仍是 false，于是点一下模型/项目 chip 就会走 `if (!_HG.dirty)`
    // 分支把这条历史会话 DELETE 掉并杀掉其进程（实测可复现：打开历史会话、
    // 不发消息、点模型 → 会话从列表消失）。这里改为按「目标会话是否已落盘」
    // 判定：缓存里有 or 服务端标记 has_history 的会话，都不是可丢弃的新会话。
    _HG.dirty = !!(sid && (_HG.cache[sid] || _hgHasHistory(sid)));
    // v2.15：busy 不能跨会话沿用。旧实现只重置 _HG.alive，busy 靠下面那次
    // events 请求的 .then(setBusy) 纠偏，而 catch 把失败整个吞掉 —— 请求
    // 失败/非 ok 时 busy 停在 true，发送键恒为 ■、活动条恒计时、send() 被
    // 拦下，点 ■ 又回到这条死循环。这里先无条件清掉，真实值由 events 回填。
    setBusy(false);
    costEl.classList.remove('warn');   // 清文本不清 class 会让空用量环留着橙色警示
    // v2.3.0：未发送的附件随会话暂存/恢复——切走时把当前 atts 归档到旧会话
    // 名下，切回时取回该会话的暂存（原来无条件清空，用户贴的图切一圈回来
    // 就没了）。发送成功的清空在 send 尾部（清 attsBy），互不干扰。
    if (prevSid) _HG.attsBy[prevSid] = _HG.atts;
    _HG.atts = (sid && _HG.attsBy[sid]) || [];
    renderAtts();
    _HG.echoFast = null;               // v2.20：切会话清乐观渲染去重窗口（防串会话吞 echo）
    _hgCtxRestore(sid);                // 切回旧会话：恢复该会话上次的上下文用量（result 不重放）
    if (!sid) {
      flow.innerHTML = '';
      showWelcome();
      openSSE(null); setBusy(false);
      titleEl.textContent = '新会话'; cwdEl.textContent = '';
      renderList(); renderQueue();
      input.focus();
      return;
    }
    const c = _HG.cache[sid];
    if (c) {
      flow.innerHTML = c.html; _HG.seq = c.seq;
      _HG.echoFast = c.echoFast || null;   // v2.28.13：去重窗口随快照恢复（防重放双画）
      // v2.37（P0-A）：窗口账目重建——快照 DOM 是上一次 _histRender 的窗口
      // （histStart 起的尾部段），账目随快照存取（见 saveCache）。histLive
      // 置 true 需 histAll 数据在场：拉一次 transcript 只填数据不重渲
      // （转写只追加，[0..histStart) 前缀稳定，DOM 尾段与 histAll 对应成立，
      // 上滑扩段自此可用；旧缓存无账目字段 → 维持 v2.35.2 安全态走只读条）。
      // 还原后 400ms 内不进收缩分支——程序化 scrollBottom 会触发 scroll 事件，
      // >2 页的快照会被立刻「收段」重渲（观感=又刷了一遍）
      _HG.histStart = (typeof c.histStart === 'number') ? c.histStart : 0;
      _HG.histRestoredAt = Date.now();
      if (c.histLive && !_HG.histAll) {
        _histFetch(sid).then(ok => {
          if (ok && _HG.sid === sid) {
            // v2.37R2（复审4）：账目越界钳制——快照存账后该会话在别窗做过
            // 回滚（转写被截断），histStart 可能越过现在的行数
            if (_HG.histStart > _HG.histAll.length) _HG.histStart = _HG.histAll.length;
            _HG.histLive = true;
            renderSideStatus();   // 面板 B/C 回放数据此路也会补齐（todos 等）
          }
        });
      }
      scrollBottom(true);              // v2.25：快照恢复也回底——与 _histRender 路径
                                       // 一致（用户实测「新建会话再切回，焦点不在最下面」）
      // v2.3.13：快照里冻结的压缩分割线——本会话没有仍在进行的压缩就定格成
      // 完成态（压缩结束事件只在原会话 SSE 里到达，切走期间错过时这里兜底），
      // 不让「正在压缩 · 已 X」冻死在消息流里
      const cdiv = flow.querySelector('.h-switch[data-hg-compact]');
      if (cdiv && !(_HG.compacting && _HG.compactSid === sid)) {
        const ci = cdiv.querySelector('i');
        if (ci && !ci.textContent.includes('完成')) ci.textContent = '上下文压缩完成';
      }
      // v2.25：快照里「已点开」的懒段/懒工具，切回来必须显示内容——histAll
      // 已被切会话清空，先拉 transcript 再补填（否则展开=空白壳，用户实测
      // 「早起会话的历史思考点不开了」）
      const lazyOpen = flow.querySelectorAll('.h-think-seg.open[data-hg-lazy="1"], .h-tool[data-hg-lazy="1"]');
      if (lazyOpen.length && !_HG.histAll) {
        _histFetch(sid).then(ok => {
          if (ok && _HG.sid === sid) lazyOpen.forEach(el => _histLazyFill(el));
        });
      }
      // v2.24.5：时间条状态从 DOM 恢复（最后一条 .h-time 的 ms）
      _HG.lastTs = +((([...flow.querySelectorAll('.h-time')].pop() || {}).dataset || {}).ms || 0);
      // v2.3.2：未定格的转交等待线重启计时——快照（innerHTML 字符串）不
      // 带 interval，恢复后计时冻结在快照时刻（用户实锤「读秒不走」）。
      // v2.35.2（P1 多槽）：全部未定格线各重挂各的计时器（此前只挂最后
      // 一条，更早的线读秒冻死）；peerWait 指向最后一条（兼容识图 sweep）。
      // 旧快照的线没有 data-peer——按文本兜底识别，一并重挂
      const relayEls = new Set(flow.querySelectorAll('.h-switch[data-peer]:not([data-done])'));
      flow.querySelectorAll('.h-switch .hg-peer-t').forEach(tb => {
        const sw = tb.closest('.h-switch');
        if (sw && !sw.dataset.peer && !sw.dataset.done
            && sw.textContent.includes('等待结论回传')) relayEls.add(sw);
      });
      relayEls.forEach(rl => _hgPeerTimerStart(rl, +(rl.dataset.t0 || 0) || Date.now()));
      // 快照恢复后重建 rowById（busy 会话切回时 tool_result 事件要挂回行）
      flow.querySelectorAll('[data-tid]').forEach(el => { _HG.rowById[el.dataset.tid] = el; });
      // v2.9：缓存恢复不能盲目清 busy——切走时正在回复的会话，切回后
      // 事件继续流入但 user_echo 已在 seq 之前（不重放），活动条/停止钮
      // 再也不弹（用户实测「有实际对话但无计时条、发送键不变■」）。
      // 后端 events 接口顺带返回真实 busy，按它恢复
      fetch(`/api/harness/events?sid=${encodeURIComponent(sid)}&after_seq=${_HG.seq}`)
        .then(r => r.json())
        .then(j => { if (j.ok && _HG.sid === sid) { setBusy(!!j.busy, j.busy_since); if (j.busy) phResume(); } })   // v2.20（3.png）：快照里的冻结占位复活
        .catch(() => { if (_HG.sid === sid) setBusy(false); });
    } else {
      flow.innerHTML = '';
      try {
        const j = await (await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)).json();
        if (j.ok && _HG.sid === sid) {
          _HG.seq = j.seq || 0; _HG.alive = !!j.alive;
          if (!j.lines.length) showWelcome();
          else _histRender(j.lines, Math.max(0, j.lines.length - _HG.HIST_PAGE));
          // v2.20（3.png）：busy 会话尾部组是「进行中」的组——transcript 只到
          // 已落盘部分，无条件定稿会把组关死还漏占位气泡。留活 + 补占位，
          // SSE 续传事件经 grpEnsure 回扫正常接回。
          if (j.busy) phResume();
          else grpFinalize(true);          // transcript 末尾若挂着未收的组 → 定稿自动收起
          scrollBottom(true);              // 切会话回底（不受翻历史保护限制）
          setBusy(!!j.busy, j.busy_since);   // v2.26：计时起点带后端 busy_since（切回来不清零）
        }
      } catch(_) {}
    }
    // v2.35.2（P0 加固）：transcript 分支有 await——期间用户可能已切去别的
    // 会话（快切/双击竞速）。此刻本调用已是过期调用：chrome（标题/目录/chip）
    // 与 openSSE 若照跑，会把「显示 A、事件流却挂 B、标题 C」的错位态焊死，
    // 且过期流的小 seq 事件全被防重放守卫吞掉，会话从此假死。归属不符即弃。
    if (_HG.sid !== sid) return;
    const s = _HG.sessions.find(x => x.sid === sid);
    // v2.7：项目优先——cwd 目录名在前（accent），claude 会话名在后
    cwdEl.textContent = s ? (s.cwd || '').split(/[\\/]/).pop() || '~' : '';
    // v2.19：切回历史会话 → 「新会话将打开的目录」跟随该会话的项目，
    // 同项目连续开会话不用每轮重选（会话无 cwd 时不动用户手选的值）。
    if (s && s.cwd && _HG.cwd !== s.cwd) {
      _HG.cwd = s.cwd; _hgSaveCwd(s.cwd); projChipLabel();
    }
    // v2.20：权限/思考等级同理跟随会话恢复显示
    if (s) {
      if (s.permission && s.permission !== _HG.perm) { _HG.perm = s.permission; permChipLabel(); }
      const st = s.think || null;
      if (st !== _HG.thinkLv) { _HG.thinkLv = st; thinkChipLabel(); }
      // 模型跟随会话恢复（用户要求：打开历史会话直接显示之前用的模型）。
      // 元数据 model=None 的会话（从没显式选过）实际跑的是 settings 默认
      // 模型——显示默认名，别回退成空态「模型」让用户以为丢了。
      const sm = s.model || (_HG.models && _HG.models.default) || null;
      if (sm && sm !== _HG.model) {
        _HG.model = sm;
        q('[data-hg-model]').innerHTML = '🧠 ' + esc(sm) + ' ▾';
      }
    }
    titleEl.textContent = (s && s.title) || '会话';
    conn.meta.label = titleEl.textContent;
    conn.meta.cwd = (s && s.cwd) || '';
    conn.tab.querySelector('.label').textContent = titleEl.textContent;
    openSSE(sid, _HG.seq);
    renderList();
    renderQueue();                   // v2.20：排队条按会话各自恢复
    refreshSidebar();
    if (!keepInput) input.focus();
  }

  function showWelcome() {
    flow.innerHTML = `
      <div class="hg-welcome">
        <div class="hg-welcome-ico"><span class="claude-ico big"></span></div>
        <div class="hg-welcome-title">你好，我是 Claude</div>
        <div class="hg-welcome-desc">直接输入开始新对话，或从左侧选择历史会话继续。<br>支持 📎 附件、@ 文件引用、⚡ 技能、🧠 模型切换。</div>
      </div>`;
  }

  // v2.19：多模态判定（口径与后端 /models 的 mm 一致；会话列表打 👁 用）
  function _hgMm(m) {
    return !!(_HG.models && (_HG.models.mm || []).includes(m));
  }
  fetch('/api/harness/models').then(r => r.json())
    .then(j => {
      if (!j || !j.ok) return;
      _HG.models = j; renderList();
      // v2.20：预取回来时当前会话若已切入且 model=None（跑的是默认模型），
      // 补显示默认名——switchTo 时 _HG.models 可能还没到，chip 空过一次
      const s = _HG.sessions.find(x => x.sid === _HG.sid);
      const sm = (s && s.model) || j.default;
      if (sm && !_HG.model) {
        _HG.model = sm;
        q('[data-hg-model]').innerHTML = '🧠 ' + esc(sm) + ' ▾';
      }
    })
    .catch(() => {});

  // ==================== 会话列表 ====================
  async function refreshSessions() {
    try {
      const j = await (await fetch('/api/harness/sessions')).json();
      if (j.ok) { _HG.sessions = j.sessions || []; renderList(); }
    } catch(_) {}
  }

  // ==================== 消息排队（v2.20，参考 ZCode 交互）====================
  // 当前回复执行中继续输入 → 不再被「正在回复中」拦下，而是排进队列：
  // 输入卡上方出现排队条（⠿ 草稿缩略 + ↑立即 / ✎编辑 / 🗑删除），当前
  // 回复结束（result/interrupted → setBusy(false)）自动依序发送。
  // 队列按 sid 隔离，切会话各看各的。
  const queueEl = q('[data-hg-queue]');
  // ==================== 引用消息（v2.27，微信同款）====================
  // 右键消息气泡 → 「引用」→ 输入卡上方出引用条（只读，✕ 取消）→ 发送时
  // 拼成「[引用 xx 的消息]…[我的问题]…」——引用内容随消息落转写，AI 能
  // 同时看到被引原文和用户新表达，历史回看也完整。
  const quoteEl = q('[data-hg-quote]');
  const quoteBodyEl = q('[data-hg-quote-body]');
  function setQuote(q) {
    _HG.quote = q || null;
    if (!_HG.quote) { quoteEl.style.display = 'none'; return; }
    const brief = _HG.quote.text.replace(/\s+/g, ' ').trim();
    quoteBodyEl.textContent = `${_HG.quote.who}：${brief.length > 60 ? brief.slice(0, 59) + '…' : brief}`;
    quoteBodyEl.title = _HG.quote.text;          // 悬浮看全文
    quoteEl.style.display = 'flex';
    input.focus();
  }
  q('[data-hg-quote-x]').onclick = () => setQuote(null);
  // 右键消息气泡 → 迷你菜单（贴鼠标）。只做引用一项，克制。
  flow.addEventListener('contextmenu', (e) => {
    // 命中范围：正文气泡(.h-msg)，或右键思考/执行抽屉(.h-drawer)时落到
    // 所在消息组的 AI 正文——用户视角「右键这条回复」不分抽屉还是正文
    const m = e.target.closest('.h-msg')
      || (e.target.closest('.h-grp') || {}).querySelector('.h-msg.asst')
      || null;
    if (!m || !flow.contains(m)) return;
    e.preventDefault();
    const old = wrap.querySelector('.hg-ctxmenu');
    if (old) old.remove();
    const who = m.classList.contains('user') ? '我' : 'AI';
    // 用户气泡优先 dataset.rtext（发送原文，干净）；AI 气泡取正文——
    // clone 后剔除 button/抽屉钮等 UI 元素再取文本，避免混入「复制」等字样
    let text = (m.dataset && m.dataset.rtext) || '';
    if (!text) {
      const b = m.querySelector('.h-bubble');
      if (b) {
        const c = b.cloneNode(true);
        c.querySelectorAll('button').forEach(x => x.remove());
        text = c.innerText || c.textContent || '';
      }
    }
    text = (text || '').trim();
    if (!text) return;
    const menu = document.createElement('div');
    menu.className = 'hg-ctxmenu';
    menu.innerHTML = `<div class="hg-ctx-item" data-hg-ctx-quote>❝ 引用此消息</div>`;
    // v2.27.2：fixed 定位直接用视口坐标挂 body——之前 absolute 挂 flow 换算
    // 内容坐标，实测会随滚动/祖先定位飞走（用户截图菜单贴顶）。fixed 永远
    // 贴鼠标，与滚动无关（微信同款）。
    menu.style.position = 'fixed';
    menu.style.left = '0'; menu.style.top = '0';
    document.body.appendChild(menu);
    let x = e.clientX, y = e.clientY;
    if (x + menu.offsetWidth > window.innerWidth - 8) x = window.innerWidth - menu.offsetWidth - 8;
    if (y + menu.offsetHeight > window.innerHeight - 8) y = window.innerHeight - menu.offsetHeight - 8;
    menu.style.left = Math.max(4, x) + 'px';
    menu.style.top = Math.max(4, y) + 'px';
    menu.querySelector('[data-hg-ctx-quote]').onclick = () => {
      menu.remove();
      setQuote({ who, text });
    };
    const close = (ev) => {
      if (menu.contains(ev.target)) return;
      menu.remove();
      document.removeEventListener('mousedown', close, true);
      flow.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close, true);
    };
    setTimeout(() => {
      document.addEventListener('mousedown', close, true);
      flow.addEventListener('scroll', close, true);
      window.addEventListener('resize', close, true);
    }, 0);
  });
  function _hgQueueKey() { return _HG.sid || '_new'; }
  // v2.25：拖动排序状态。拖拽中挂起 renderQueue 重建——重建会把被抓住的
  // 元素从文档摘下，pointer capture 随之失效，拖到一半掉链子。
  let qDrag = null;               // {from, i, after, item}
  function renderQueue() {
    if (qDrag) return;            // 拖拽中不重建，松手后统一重渲
    const list = _HG.queues[_hgQueueKey()] || [];
    const lenChanged = queueEl._lastLen !== list.length;
    queueEl.style.display = list.length ? 'flex' : 'none';
    queueEl._lastLen = list.length;
    // v2.25：排队条顶高/收起会改变消息流视口高——原本在底部跟读时自动回底，
    // 不用用户手动翻页（用户需求）。翻阅历史中（不在底部）不打扰。
    if (lenChanged && typeof isNearBottom === 'function' && isNearBottom()) {
      requestAnimationFrame(() => scrollBottom());
    }
    queueEl.innerHTML = list.map((it, i) => {
      let t = String(it.text || '').replace(/\s+/g, ' ').trim();
      const nAt = (it.images || []).length + (it.files || []).length;
      if (nAt) t = (t ? t + ' ' : '') + '📎×' + nAt;
      if (t.length > 60) t = t.slice(0, 59) + '…';
      return `<div class="hg-q-item" data-i="${i}" title="${esc(it.text || '')}">` +
        `<span class="hg-q-grip" data-i="${i}" title="拖动排序（按住抓手上下拖）">⠿</span>` +
        `<span class="hg-q-text">${esc(t || '（空）')}</span>` +
        `<button class="hg-q-act" data-qact="now" data-i="${i}" title="中断当前回复，立即发送这条">↑ 立即</button>` +
        `<button class="hg-q-act" data-qact="edit" data-i="${i}" title="放回输入框编辑">✎</button>` +
        `<button class="hg-q-act" data-qact="del" data-i="${i}" title="丢弃">🗑</button>` +
        `</div>`;
    }).join('');
  }
  function queuePush(it) {
    const key = _hgQueueKey();
    (_HG.queues[key] = _HG.queues[key] || []).push(it);
    renderQueue();
    showBanner('已排队：当前回复结束后自动发送', 2200);
  }
  function queuePump() {
    // setBusy(false) 的尾巴：600ms 去抖后把队首发出去（dispatch 成功 →
    // setBusy(true) → 本轮完 → 再次 setBusy(false) → 泵下一条，链式排空）
    clearTimeout(_HG.qTimer);
    _HG.qTimer = setTimeout(async () => {
      if (_HG.busy || !_HG.sid) { renderQueue(); return; }
      const key = _hgQueueKey(), list = _HG.queues[key] || [];
      if (!list.length) { renderQueue(); return; }
      const it = list.shift();
      _HG.queues[key] = list;
      renderQueue();
      const ok = await dispatch(it.text || '', it.images || [], it.files || [], false);
      // v2.35.1（F6）：后端「正在回复」拒收（前端误判空闲的窄窗口竞态，如
      // 切回运行中会话的 events 回填前）——条目回队首不丢；dispatch 已按
      // 后端真相同步置 busy，泵链靠 fire 时的 busy 检查自然挂起，真回合
      // 结束（setBusy(false)）再泵。其余失败维持原行为（banner 已示因）
      if (!ok && /正在回复/.test(dispatch.rej || '')) {
        const cur = _HG.queues[key] || [];
        cur.unshift(it);
        _HG.queues[key] = cur;
        renderQueue();
      }
    }, 600);
  }
  // v2.25：排队条拖动排序。用 pointer 事件而非 HTML5 dnd——dnd 在 WebView2
  // 里要额外处理 drop 目标判定，pointer 直接按行中线算落点更稳。
  // 抓手是唯一拖动入口（data-i 标在抓手上，不靠 closest 反查，避免点到
  // 按钮时误判）。
  function qEndDrag(commit) {
    if (!qDrag) return;
    const d = qDrag;
    qDrag = null;
    d.item.classList.remove('dragging');
    queueEl.querySelectorAll('.drop-before,.drop-after')
      .forEach(x => x.classList.remove('drop-before', 'drop-after'));
    const key = _hgQueueKey();
    const list = (_HG.queues[key] || []).slice();
    if (commit && d.target != null && list.length > 1 && d.i < list.length) {
      const it = list.splice(d.i, 1)[0];
      let to = d.target - (d.target > d.i ? 1 : 0);   // 移除后目标下标左移
      to = Math.max(0, Math.min(list.length, to));
      list.splice(to, 0, it);
      _HG.queues[key] = list;
    }
    renderQueue();
  }
  queueEl.addEventListener('pointerdown', (e) => {
    const grip = e.target.closest('.hg-q-grip');
    if (!grip || e.button !== 0) return;
    const item = grip.closest('.hg-q-item');
    if (!item) return;
    e.preventDefault();
    qDrag = { i: +grip.dataset.i, target: null, item };
    item.classList.add('dragging');
    grip.setPointerCapture(e.pointerId);
  });
  queueEl.addEventListener('pointermove', (e) => {
    if (!qDrag) return;
    const items = Array.from(queueEl.querySelectorAll('.hg-q-item'));
    let target = items.length;            // 默认落到末尾
    let after = false;
    for (let k = 0; k < items.length; k++) {
      const r = items[k].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { target = k; after = false; break; }
      target = k + 1; after = true;
    }
    if (target === qDrag.target && after === qDrag.after) return;
    qDrag.target = target;
    qDrag.after = after;
    items.forEach(x => x.classList.remove('drop-before', 'drop-after'));
    const ref = items[target];
    if (ref) ref.classList.add(after ? 'drop-after' : 'drop-before');
  });
  queueEl.addEventListener('pointerup', () => qEndDrag(true));
  queueEl.addEventListener('pointercancel', () => qEndDrag(false));
  queueEl.addEventListener('click', (e) => {
    const b = e.target.closest('[data-qact]');
    if (!b) return;
    const key = _hgQueueKey(), arr = _HG.queues[key] || [];
    const i = +b.dataset.i;
    if (i >= arr.length) return;
    if (b.dataset.qact === 'del') {
      arr.splice(i, 1); renderQueue();
    } else if (b.dataset.qact === 'edit') {
      const it = arr.splice(i, 1)[0]; renderQueue();
      input.value = it.text || '';
      renderOverlay(input.value);
      if ((it.images || []).length || (it.files || []).length)
        showBanner('附件不随草稿返回，请重新添加', 3000, true);
      input.focus();
    } else if (b.dataset.qact === 'now') {
      const it = arr.splice(i, 1)[0];
      arr.unshift(it); renderQueue();
      stopGen();               // interrupted → setBusy(false) → 泵先发它
    }
  });
  // ==================== v2.32 右侧面板会话动态（六分区监视器）====================
  // 设计文档 docs/设计_2026-09-20_右侧会话动态面板.md。面板=纯派生监视器：
  // 不持状态机，一切从 _HG + sessions + localStorage 派生；骨架是 index.html
  // 静态节点（v2.30 教训：挂 harness wrap 内 q() 扑空=面板永不显示）；事件
  // 驱动 rAF 合并全量重渲；秒表是全局单例 interval 只改 textContent。
  let dynEl = document.querySelector('[data-hg-dyn]');   // v2.37（P0-B）：let——面板 DOM 被外层重建时可重联（见 tick 自愈）
  const _hgAiPanel = document.getElementById('aiPanel');
  // 面板换装开关 _hgPanelMode 在顶层（闭包外的 switchTab 包装器与 _harnessClose
  // 都要调它）；本闭包负责给它装「进入面板时拉 roles + 刷一遍」的钩子。
  let _hgRolesCache = null;   // 最近一次 /roles 响应（面板三角色行与左侧按钮同源）
  const _AGENT_LABEL = { executor: '执行者', coder: '编程者', designer: '设计者', dev: '开发', reviewer: '审核', 'general-purpose': '通用子代理' };

  // ---- 派生态与入口 ----
  function _hgDyn() {
    return _HG.dyn || (_HG.dyn = { acts: [], turns: [], turnN: 0, turnTools: 0,
      todoSeen: {}, todoRowId: null, agentsRpl: [] });
  }
  let _dynRaf = 0;
  function renderSideStatus() {          // 事件驱动刷新入口（旧名保留：事件流调用点零改动）
    if (!dynEl || _dynRaf) return;
    _dynRaf = requestAnimationFrame(() => { _dynRaf = 0; _hgDynRender(); });
  }
  function _hgDynDirty() { renderSideStatus(); }   // 别名（setBusy/_hgDrawCtxRing 调；function 声明无 TDZ）

  // ==================== v2.35 运行派生态（P0-1②③ / P1-4 / P1-5）====================
  // 输入框/面板的「等待类」状态全部派生自已有事实（agents 档案 + 转交线
  // dataset），不另持状态机——快照往返后从 DOM 即可重建，零序列化负担。
  // v2.37（P1-E）：协作包装判定——CLI 对 SendMessage 委托的独立会话会包装
  // 成后台 Task（subagent_type 非本工具角色名）。后台 + 非角色类型一律按
  // 协作对待：不开实况窗格 tab（独立会话事件流不经过本会话，开了必是空白
  // tab），归面板 C 区协作行。宁可误杀真实后台通用代理的可围观性（罕见，
  // 主 flow 仍有灰行），不再伪装能点开实况。
  const _ROLE_AGENTS = new Set(['executor', 'coder', 'dev', 'reviewer', 'designer']);
  function _isCollabWrap(type, bg) {
    return !!bg && !_ROLE_AGENTS.has(String(type || ''));
  }
  function _hgAgentsRunning() {          // 运行中子代理（Task 已起、未收到完成信号）
    return Object.values(_HG.agents || {}).some(a => !a.done);
  }
  function _hgPeerLines() {              // 协作转交线（已转交/识图转交，dataset 派生）
    return [...flow.querySelectorAll('.h-switch[data-peer]')];
  }
  function _hgPeerPending() {            // 还有未回传的协作等待（任意一条未定格）
    // v2.37R6：unknown（回合终结复核未检出回传）不算等待——否则输入框/
    // 面板永久挂「等待协作回传」
    // v2.41R2：stale（>30min 疑似残留）同步排除——与面板 C 区过滤/pill 口径
    // 统一为「stale/unknown 都不算等待」，防输入框提示与 pill 对同一状态相反
    return _hgPeerLines().some(el => !el.dataset.done
      && el.dataset.unknown !== '1' && el.dataset.stale !== '1');
  }
  function _hgInputState() {             // 输入框占位文案：运行态/子代理/协作等待联动
    let ph;
    if (_HG.busy && _hgAgentsRunning())
      ph = '子代理执行中——回复进行中，继续输入将排队，结束后自动发送';
    else if (_HG.busy)
      ph = '回复执行中——继续输入将排队，结束后自动发送';
    else if (_hgAgentsRunning())
      ph = '子代理后台执行中——现在输入将开启新回合（不影响子代理）';
    else if (_hgPeerPending())
      ph = '等待协作回传——现在输入将开启新回合（回传到达会以 📥 气泡呈现）';
    else
      ph = '给 Claude 发消息，@ 引用文件，/ 选择技能 · 可直接粘贴图片';
    if (input.placeholder !== ph) input.placeholder = ph;
  }
  // ---- P1-4：子代理模型名（起跑预显示；实跑模型由子代理 assistant 事件覆盖）----
  let _agentModelsTried = false;         // 只拉一次（失败允许重试）
  function _hgAgentModelsFetch() {
    if (_agentModelsTried) return;
    _agentModelsTried = true;
    fetch('/api/harness/agent_models').then(r => r.json())
      .then(j => {
        if (!j || !j.ok) return;
        _HG.agentModels = j.agents || {};
        // v2.35.1（F4）：缓存晚到时回填已开 tab——_subOpen 时缓存未就绪的
        // 条目 model 是空串，不回填则 frontmatter 预显示在 tab 永不出现
        // （实跑 model 到达的条目不动，仍以实跑为准）
        for (const t in _sub.tabs) {
          const tb = _sub.tabs[t];
          if (!tb.model) {
            const ty = tb.type || ((_HG.agents || {})[t] || {}).type || '';
            if (ty && _HG.agentModels[ty]) tb.model = _HG.agentModels[ty];
          }
        }
        renderSideStatus();              // 面板 C 区/详情卡的模型预显示跟随
        _subTabsPaint();                 // 已开 tab 的模型角标补显
      }).catch(() => { _agentModelsTried = false; });
  }
  function _hgAgentModelPre(type) {
    _hgAgentModelsFetch();
    return (_HG.agentModels && _HG.agentModels[type]) || '';
  }
  // P0-2：手动重开子代理实时窗格（面板运行中条目 / 消息流子代理行点击入口）
  // v2.38：已完成且带 agentId 的代理 → 回放窗格（数据源转写，历史也能看）；
  // 切会话后档案丢失 → 提示语更新为回放口径
  function _subReopen(tid) {
    if (!tid) return;
    if (!_sub.tabs[tid]) {
      const a = (_HG.agents || {})[tid];
      if (!a) { showBanner('历史子代理可从面板条目详情卡回放（转写数据源）', 2600); return; }
      const aid = a.taskId || a.agentId || '';
      if (a.done && aid) { _subReplay(tid, a.type, a.desc, aid); return; }
      _subOpen(tid, a.type, a.desc);
    }
    _sub.manual = true;                  // P0-3：手动来源——回合终结不自动收起，✕ 才收
    _subShow();
    _subActivate(tid);
  }
  // v2.37（P1-E）：摘除一个窗格 tab（协作包装误开/超限让位共用）——内容、
  // 序表、激活态一并清；最后一个 tab 顺带收起窗格
  function _subDrop(tid) {
    const tb = _sub.tabs[tid];
    if (!tb) return;
    if (tb.sc && tb.sc.parentNode) tb.sc.remove();
    delete _sub.tabs[tid];
    _sub.order = _sub.order.filter(t => t !== tid);
    if (_sub.active === tid) {
      _sub.active = _sub.order[0] || null;
      if (_sub.active) {
        const sc = _sub.tabs[_sub.active] && _sub.tabs[_sub.active].sc;
        if (sc) sc.style.display = '';
      }
    }
    _subTabsPaint();
    if (!_sub.order.length && _subPaneEl) _subPaneEl.style.display = 'none';
  }

  function _hgAgentsSweep(markErr) {     // 回合终结：在跑的子代理统一收尾（防假"运行中"）
    if (!_HG.agents) return;
    let swept = false;
    for (const id in _HG.agents) {
      const a = _HG.agents[id];
      // v2.35：后台代理（bg）在主回合 result 时不收——它还在跑，收尾信号是
      // task_notification；中断/退出（markErr）照收：进程没了，一切皆停
      if (!a.done && !(a.bg && !markErr)) {
        a.done = true; a.doneAt = Date.now();
        if (markErr) { a.err = true; a.interrupted = true; }
        swept = true;
      }
    }
    if (swept) renderSideStatus();
  }
  function _hgTurnEnd(st, durMs) {       // 回合记账 ring（≤10）；dur 优先事件值（网关常缺失→本地差值）
    const d = _hgDyn();
    const dur = (durMs > 0) ? durMs : Date.now() - (_HG.actStart || Date.now());
    d.turns.push({ n: ++d.turnN, dur: Math.max(0, Math.round(dur / 1000)), st, tools: d.turnTools });
    if (d.turns.length > 10) d.turns.shift();
    d.turnTools = 0;
    renderSideStatus();
  }
  function _hgActPush(it) {              // 活动流 ring（≤20）；回放路径在调用方排除
    const d = _hgDyn();
    d.acts.push(it);
    if (d.acts.length > 20) d.acts.shift();
    renderSideStatus();
  }
  function _hgActDone(tid, st) {
    const a = ((_HG.dyn && _HG.dyn.acts) || []).find(x => x.tid === tid && !x.done);
    if (!a) return;
    a.done = true; a.doneAt = Date.now();
    a.err = (st === 'error' || st === 'denied');
    renderSideStatus();
  }
  async function _hgRolesFetch() {       // roles 只读拉取（缓存+刷面板；失败静默）
    try {
      const j = await (await fetch('/api/harness/roles')).json();
      if (j && j.ok) { _hgRolesCache = j; renderSideStatus(); }
      return j;
    } catch(_) { return null; }
  }
  function _hgCopyText(t) {
    if (!t) return;
    const p = navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject();
    p.then(() => showBanner('已复制', 1600)).catch(() => showBanner('复制失败', 2000, true));
  }
  function _hgJumpRow(tid) {             // 跳消息流工具行（只读操作，不碰快照状态机）
    const row = _HG.rowById[tid];
    if (!row || !row.isConnected) return;   // 卸载态防御（busy 中切过 tab）
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    row.classList.remove('hg-dyn-jump');
    void row.offsetWidth;                // 重启动画
    row.classList.add('hg-dyn-jump');
    setTimeout(() => row.classList.remove('hg-dyn-jump'), 1600);
  }
  // v2.39：详情卡构建抽纯函数——_dynAgents 重渲（秒表 tick/SSE 都触发
  // renderSideStatus）是 innerHTML 全量覆盖，插入在行后的详情卡每次都被
  // 冲掉（用户实锤「点击展开后不一会又缩回去」）。展开态记 dyn.agentDetailOpen，
  // _dynAgents 重建后按 id 恢复插回。
  function _hgAgentDetailEl(id, a) {
    const dur = a.done
      ? (a.t0 ? fmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000))) : '—')
      : (a.t0 ? fmtDur((Date.now() - a.t0) / 1000) + '（进行中）' : '—');
    // v2.35（P1-4）：模型行——实跑 model（子代理 assistant 事件实报）优先，
    // frontmatter 预显示兜底，都无=内置代理按 CLI 行为跑主链模型
    const mdl = a.model || (_HG.agentModels && _HG.agentModels[a.type]) || '';
    // 用量行——task_progress/task_notification 的 CLI 侧计数（total_tokens/
    // tool_uses）；网关会把 assistant.message.usage 置零（实测），不作为源
    const usageTxt = a.tokens
      ? `${(a.tokens / 1000).toFixed(1)}K tokens · ${a.toolN || 0} 次工具`
      : '';
    const d = document.createElement('div');
    d.className = 'hg-dyn-agdetail';
    d.innerHTML =
      (id && !a.replay ? `<div class="hg-dyn-kv"><span class="k">ID</span>` +
        `<span class="v mono" data-hg-copy="${esc(id)}" title="点击复制">${esc(id)}</span></div>` : '') +
      (a.replay ? '' :
        `<div class="hg-dyn-kv"><span class="k">模型</span><span class="v" title="${esc(mdl ? '实跑/frontmatter 模型' : '内置或无定义文件代理，按 CLI 行为跑主链模型')}">${esc(mdl || '主链模型')}${a.bg ? ' · 后台' : ''}</span></div>`) +
      (a.replay || !usageTxt ? '' :
        `<div class="hg-dyn-kv"><span class="k">用量</span><span class="v">${esc(usageTxt)}</span></div>`) +
      `<div class="hg-dyn-kv"><span class="k">起止</span><span class="v">` +
        `${a.t0 ? new Date(a.t0).toTimeString().slice(0, 8) : '—'} → ` +
        `${a.doneAt ? new Date(a.doneAt).toTimeString().slice(0, 8) : (a.done ? '历史' : '运行中')}</span></div>` +
      `<div class="hg-dyn-kv"><span class="k">耗时</span><span class="v">${dur}` +
        `${a.interrupted ? ' · 已中断' : a.err ? ' · 失败' : ''}</span></div>` +
      (a.desc ? `<div class="hg-dyn-agres">${esc(a.desc)}</div>` : '') +
      (a.result ? `<div class="hg-dyn-agres">${esc(a.result)}</div>` : '') +
      // v2.38：回放入口——带 agentId 的已完成代理（含历史条目）可开回放
      // 窗格（数据源=子代理转写）；协作代理只回看结论
      (a.done && !a.collab && (a.taskId || a.agentId)
        ? `<button class="hg-dyn-replay-btn" data-hg-replay="${esc(id)}"` +
          ` data-hg-replay-aid="${esc(a.taskId || a.agentId || '')}"` +
          ` data-hg-replay-type="${esc(a.type || '')}">▣ 回放该子代理过程</button>` : '') +
      (a.collab && a.result
        ? `<button class="hg-dyn-replay-btn" data-hg-replay="${esc(id)}"` +
          ` data-hg-replay-collab="1" data-hg-replay-type="${esc(a.type || '')}">▣ 回看协作结论</button>` : '');
    return d;
  }
  function _hgAgentToggle(rowEl) {       // 子代理行展开/收起详情卡（单开）
    const nxt = rowEl.nextElementSibling;
    if (nxt && nxt.classList.contains('hg-dyn-agdetail')) {
      nxt.remove();
      if (_HG.dyn) _HG.dyn.agentDetailOpen = null;
      return;
    }
    dynEl.querySelectorAll('.hg-dyn-agdetail').forEach(x => x.remove());
    const id = rowEl.dataset.hgAg || '';
    const a = (_HG.agents || {})[id]
      || ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => x.rid === id);
    if (!a) return;
    if (_HG.dyn) _HG.dyn.agentDetailOpen = id;
    rowEl.insertAdjacentElement('afterend', _hgAgentDetailEl(id, a));
  }
  // 点击交互（onclick 覆盖式绑定：闭包随 tab 重开重执行，addEventListener 会叠加）
  if (dynEl) dynEl.onclick = (e) => {
    const cp = e.target.closest('[data-hg-copy]');
    if (cp) { e.stopPropagation(); _hgCopyText(cp.dataset.hgCopy); return; }
    // v2.38：详情卡「回放该子代理过程」→ 回放窗格（转写数据源）
    const rb = e.target.closest('[data-hg-replay]');
    if (rb) {
      e.stopPropagation();
      const rid = rb.dataset.hgReplay;
      const a = (_HG.agents || {})[rid]
        || ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => x.rid === rid) || {};
      if (rb.dataset.hgReplayCollab) {
        _subReplay(rid, rb.dataset.hgReplayType || a.type || '协作', a.desc || '', '');
      } else {
        const aid = rb.dataset.hgReplayAid || a.taskId || a.agentId || '';
        if (!aid) { showBanner('该子代理没有 agentId 记录，无法回放', 2600); return; }
        _subReplay(rid, rb.dataset.hgReplayType || a.type || 'Task', a.desc || '', aid);
      }
      return;
    }
    const acp = e.target.closest('[data-hg-actcp]');
    if (acp) {
      e.stopPropagation();
      const a = ((_HG.dyn || {}).acts || []).find(x => x.tid === acp.dataset.hgActcp);
      if (a) _hgCopyText(a.preview || '');
      return;
    }
    if (e.target.closest('[data-hg-act]')) { _hgJumpRow(e.target.closest('[data-hg-act]').dataset.hgAct); return; }
    if (e.target.closest('[data-hg-todo]')) {
      const rid = (_HG.dyn || {}).todoRowId;
      if (rid) _hgJumpRow(rid);
      return;
    }
    // v2.35（P0-2/P1-5）：运行中子代理行点击=重开实时窗格并切 tab（窗格已开
    // =切 tab）；已完成行保持展开详情卡；协作代理行=跳消息流对应转交线
    const pr = e.target.closest('[data-hg-peer-row]');
    if (pr) {
      const lines = _hgPeerLines();
      const pend = lines.filter(el => !el.dataset.done);
      const target = (pend.length ? pend : lines).slice(-1)[0];
      if (target) {
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        target.classList.remove('hg-dyn-jump');
        void target.offsetWidth;
        target.classList.add('hg-dyn-jump');
        setTimeout(() => target.classList.remove('hg-dyn-jump'), 1600);
      } else {
        showBanner('该协作没有对应的转交线（无消息流记录）', 2400);
      }
      return;
    }
    const ag = e.target.closest('[data-hg-ag]');
    if (ag) {
      if (ag.classList.contains('run')) { _subReopen(ag.dataset.hgAg); return; }
      _hgAgentToggle(ag);
      return;
    }
    // v2.37（P1-D）：三角色行点击=打开配置面板（开关进面板管理，防误触；
    // 旧行为是点击直接切开关，用户明确不要）
    if (e.target.closest('[data-hg-d-roles]')) { openRolesCfg(); return; }
  };

  // ---- 渲染（分区独立重建，空区 hidden）----
  // v2.37（P0-B）：分区隔离——任何一区抛异常不再饿死后续区（旧实现单 rAF
  // 回调内顺序执行，首区异常=后面全部保持初始 hidden，「面板只剩 A 区」的
  // 形态）；异常落 console 带 [hg-dyn] 标记供现场取证
  function _hgDynRender() {
    if (!dynEl) return;
    for (const fn of [_dynStat, _dynTodos, _dynAgents, _dynActs, _dynTurns, _dynFiles]) {
      try { fn(); }
      catch (e) {
        // v2.37R6（C 区整栏消失②）：渲染失败降级为可见占位（区分无数据/
        // 渲染失败），不再只留 console 标记让整栏凭空蒸发
        try {
          console.error('[hg-dyn] 分区渲染异常', fn.name, e);
          // v2.39：错误文本直接上屏——WebView2 用户开不了 console，降级占位
          // 只说「详见 console」等于没有诊断信息（用户实锤无法反馈根因）
          const msg = esc(String((e && e.message) || e || '未知错误')).slice(0, 200);
          if (fn === _dynAgents) {
            const secA = _sec('agents');
            if (secA) {
              secA.hidden = false;
              const al = secA.querySelector('[data-hg-d-aglist]');
              if (al) al.innerHTML = '<div class="hg-sub-replay-note">子代理区渲染异常（已降级显示）：<b>' + msg + '</b></div>';
            }
          }
        } catch(_) {}
      }
    }
    try { _hgInputState(); } catch(_) {}   // v2.35：派生态变化连带输入框提示
  }
  function _sec(z) { return dynEl.querySelector(`[data-hg-sec="${z}"]`); }
  const _THINK_TXT = { low: '低', medium: '中', high: '高', max: '最高' };
  const _TURN_ICO = { ok: '✓', error: '✗', interrupt: '⏹', exit: '⏻' };
  const _FILE_TOOLS = ['Read', 'Edit', 'MultiEdit', 'Write', 'NotebookEdit'];
  const _hhmm = ts => new Date(ts).toTimeString().slice(0, 5);
  function _dynStat() {                  // A 会话状态：双来源口径——当前会话值(s.*)优先，无会话回退新会话参数(_HG.*)
    const sec = _sec('stat'); if (!sec) return;
    const s = _HG.sessions.find(x => x.sid === _HG.sid);
    const stEl = sec.querySelector('[data-hg-d-st]');
    const ttEl = sec.querySelector('[data-hg-d-stt]');
    // v2.35（P0-1②③）：非 busy 的「等待类」状态也算运行态——面板徽章与
    // 输入框提示同源派生（后台子代理在跑 / 协作回传未到，用户不再误判空闲）
    const agRun = _hgAgentsRunning(), peerWait = !agRun && _hgPeerPending();
    sec.classList.toggle('run', !!_HG.busy || agRun || peerWait);
    // v2.36：纯等待态（非 busy/无子代理、仅协作回传未到）状态点/秒表转「等待蓝」
    // ——与 C 区协作行/输入框提示同语义（仅类名调整，渲染逻辑零变化）
    sec.classList.toggle('wait', peerWait && !_HG.busy);
    let stTxt;
    if (_HG.compacting) stTxt = '正在压缩上下文';
    else if (_HG.busy && agRun) stTxt = '子代理执行中';
    else if (_HG.busy) stTxt = '回复中';
    else if (agRun) stTxt = '子代理后台执行中';
    else if (peerWait) stTxt = '等待协作回传';
    else if (!_HG.sid) stTxt = '新会话';
    else if (_HG.alive) stTxt = '就绪';
    else stTxt = '待命';
    stEl.textContent = stTxt;
    if (_HG.busy && _HG.actStart) {
      ttEl.dataset.t0 = _HG.actStart;
      ttEl.textContent = fmtDur(Math.max(1, Math.round((Date.now() - _HG.actStart) / 1000)));
    } else if (agRun) {
      // 非 busy 但子代理在跑（后台 Task）：计最早起跑的代理时长
      const t0 = Math.min(...Object.values(_HG.agents).filter(a => !a.done).map(a => a.t0 || Date.now()));
      ttEl.dataset.t0 = t0;
      ttEl.textContent = fmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
    } else if (peerWait) {
      const t0 = Math.min(..._hgPeerLines().filter(el => !el.dataset.done)
        .map(el => +(el.dataset.t0 || 0) || Date.now()));
      ttEl.dataset.t0 = t0;
      ttEl.textContent = fmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
    } else {
      delete ttEl.dataset.t0;
      const lt = (_HG.dyn && _HG.dyn.turns || []).filter(t => t.st === 'ok').pop();
      ttEl.textContent = lt ? '最近回合 ' + fmtDur(lt.dur) : '';
    }
    const model = (s && s.model) || _HG.model || '';
    const think = (s && s.think) || _HG.thinkLv || null;
    const perm = (s && s.permission) || _HG.perm || 'auto';
    const cwd = (s && s.cwd) || _HG.cwd || '';
    sec.querySelector('[data-hg-d-model]').textContent = model || '—';
    sec.querySelector('[data-hg-d-model]').title = model ? '当前会话模型（chip 改的是新会话）' : '';
    sec.querySelector('[data-hg-d-think]').textContent = think ? (_THINK_TXT[think] || think) : '默认';
    sec.querySelector('[data-hg-d-perm]').textContent = perm === 'confirm' ? '每次确认' : '自动执行';
    const cw = sec.querySelector('[data-hg-d-cwd]');
    cw.textContent = cwd ? cwd.split(/[\\/]/).pop() : '~';
    cw.title = cwd || '';
    let ctxTxt = '待统计', warn = false;
    if (_HG.sid) {
      try {
        const v = JSON.parse(localStorage.getItem('hg-ctx:' + _HG.sid) || 'null');
        if (v && v.used > 0) {
          const mx = v.max || 256000;
          const pct = Math.round(v.used / mx * 100);
          ctxTxt = pct + '% · ' + (v.used / 1000).toFixed(1) + 'K/' + (mx / 1000).toFixed(0) + 'K';
          warn = pct >= 80;
        }
      } catch(_) {}
    }
    const cx = sec.querySelector('[data-hg-d-ctx]');
    cx.textContent = ctxTxt;
    cx.closest('.hg-dyn-kv').classList.toggle('warn', warn);
    const r = _hgRolesCache && _hgRolesCache.roles;
    const rEl = sec.querySelector('[data-hg-d-roles]');
    // v2.37（P1-D）：形态正确 + 模型名可读——旧文案写死「决策者+执行者/编程
    // 者」且取 r.executor（配置里无此字段→恒「?」）。/roles 响应自带
    // mode（strong/light）与 resolved（按当前方案解析出的实模型），按形态
    // 出对应角色行；轻主力=dev+reviewer（共用编程者槽），决策者=执行者/编程者
    const _mode = _hgRolesCache && _hgRolesCache.mode;
    const _res = (_hgRolesCache && _hgRolesCache.resolved) || {};
    if (r) {
      if (r.enabled) {
        const light = _mode === 'light';
        rEl.textContent = light ? '轻主力' : '决策者';
        rEl.title = light
          ? `轻主力模式（点击打开配置面板）\ndev: ${_res.coder || '…'}\nreviewer: ${_res.coder || '…'}`
          : `决策者派发模式（点击打开配置面板）\n执行者: ${_res.executor || '…'}\n编程者: ${_res.coder || '…'}（结构禁权）`;
      } else {
        rEl.textContent = '关闭·直连';
        rEl.title = '直连干活（点击打开配置面板可启用三角色）';
      }
    } else rEl.textContent = '…';
  }
  function _dynTodos() {                 // B 任务进度：pill + 进度条 + 完整清单 + 首见时刻
    const sec = _sec('todos');
    const todos = _HG.todos || [];
    sec.hidden = !todos.length;
    if (!todos.length) return;
    const done = todos.filter(t => t.status === 'completed').length;
    sec.querySelector('[data-hg-d-tdone]').textContent = done + '/' + todos.length;
    sec.querySelector('[data-hg-d-tbar]').style.width = (done / todos.length * 100) + '%';
    const seen = (_HG.dyn && _HG.dyn.todoSeen) || {};
    sec.querySelector('[data-hg-d-tlist]').innerHTML = todos.map(t => {
      const st = t.status || 'pending';
      const txt = (st === 'in_progress' && t.activeForm) ? t.activeForm : t.content;
      const ts = seen[t.content || ''];
      return `<div class="hg-dyn-todo ${st}" data-hg-todo title="${esc(t.content || '')}">` +
        `<span class="hg-dyn-ck">${st === 'completed' ? '✓' : st === 'in_progress' ? '◐' : '○'}</span>` +
        `<span class="hg-dyn-tt">${esc(txt || '')}</span>` +
        (ts ? `<span class="hg-dyn-ts">${_hhmm(ts)}</span>` : '') + '</div>';
    }).join('');
  }
  function _dynAgents() {                // C 子代理实况：运行中/60s 内完成/回放历史，点击展开
    const sec = _sec('agents');
    const list = Object.entries(_HG.agents || {}).map(([id, a]) => Object.assign({ id }, a));
    const running = list.filter(a => !a.done).sort((x, y) => x.t0 - y.t0);
    const finished = list.filter(a => a.done && Date.now() - a.doneAt < 60000).slice(-5);
    const rplAll = (_HG.dyn && _HG.dyn.agentsRpl) || [];
    // v2.39 修 TDZ：旧写法 map 回调里引用了正在初始化的 rpl 自身（rpl.length）
    // ——回调同步执行时 const 未赋值，「Cannot access 'rpl' before
    // initialization」实锤。此前 agentsRpl 恒空、回调不执行埋着不炸；v2.38
    // 历史回放填充后面板 C 区必炸降级。tail 中转替代自引用，rid 编号语义不变。
    const rplTail = rplAll.slice(-3);
    // v2.40 修断链：rid 必须写回存档对象。旧写法只把 rid 合进渲染副本
    // （Object.assign({rid...}, a)），存档条目本身没有 rid——条目点击走
    // _hgAgentToggle 时按 data-hg-ag 里的 rid 去 agentsRpl.find(x =>
    // x.rid === id)，存档无 rid 恒 miss → if(!a) return 静默无反应，详情
    // 卡（含「回放该子代理过程」按钮）整链不可达：副本上的 rid 是无根之
    // 木。这里给无 rid 的存档条目补发持久 rid 并写回存档（mutate 的是我
    // 们自己的数据对象，安全）：_HG.rplSeq 模块内自增发号，唯一且跨渲染
    // 稳定（数组 shift 后同条目 rid 不漂移），已有 rid 不重发；渲染副本
    // 改 Object.assign({}, a) 平移继承，rid 语义从「数组位置」变「持久
    // 序号」，rid 值本身无展示/无持久化消费，语义安全。
    rplTail.forEach(a => {
      if (!a.rid) a.rid = 'rpl' + ((_HG.rplSeq = (_HG.rplSeq || 0) + 1));
    });
    const rpl = rplTail.map(a => Object.assign({}, a));
    // v2.35（P1-5）：协作代理（SendMessage 转交的独立会话/识图转交）——从
    // 消息流「已转交」线派生（dataset.peer/t0/done/psum 随快照序列化），
    // 带「协作」徽章与 Task 子代理视觉区分：peer 无实况事件流，点击只跳线
    // v2.37（P1-F①）：显示友好名（task_id→task_started 的 subagent_type 翻译，
    // 未知类型走 _AGENT_LABEL），裸会话 ID 收 title；同基名多条加委托序号
    // v2.37（P1-E）：协作包装的 agents 档案（collab 标记）与转交线同源去重
    // ——同委派已有转交线行的不再出档案行（两套并存会双行打架）
    const peerLines = _hgPeerLines();
    const peerIds = new Set(peerLines.map(el => el.dataset.peer));
    const _pbase = el => (_HG.peerNames && _HG.peerNames[el.dataset.peer])
      || _AGENT_LABEL[el.dataset.peer] || el.dataset.peer || '其他会话';
    const peers = peerLines
      // v2.41：unknown/stale 残留线不再派生面板协作行（用户实锤「一堆疑似
      // 残留永久挂着」）——它们没有 done 标记，旧过滤拦不住，重启后还随快照
      // 恢复回来。主 flow 转交线保留作历史记录；迟到的真实回传到达时
      // _hgPeerLineFreeze 定格（清 unknown/stale + 记 done）后按 60s 完成
      // 窗正常回面板。连带（正向）：stale 线不再计入「N 运行中」pill。
      .filter(el => el.dataset.unknown !== '1' && el.dataset.stale !== '1'
        && (!el.dataset.done || Date.now() - +(el.dataset.done) < 60000))
      .slice(-4);
    const list2 = list.filter(a => !(a.collab && a.taskId && peerIds.has(a.taskId)));
    const running2 = list2.filter(a => !a.done).sort((x, y) => x.t0 - y.t0);
    const finished2 = list2.filter(a => a.done && Date.now() - a.doneAt < 60000).slice(-5);
    const show = running2.concat(finished2, rpl);
    sec.hidden = !show.length && !peers.length;
    if (sec.hidden) return;
    const pill = sec.querySelector('[data-hg-d-agrun]');
    const pendPeers = peers.filter(el => !el.dataset.done);   // v2.41：unknown/stale 已在过滤头排除（R6 判定前移）
    pill.hidden = !running2.length && !pendPeers.length;
    pill.textContent = (running2.length + pendPeers.length) + ' 运行中';
    const _baseCount = {};
    peers.forEach(el => {
      const b = _pbase(el);
      _baseCount[b] = (_baseCount[b] || 0) + 1;
    });
    sec.querySelector('[data-hg-d-aglist]').innerHTML = show.map(a => {
      // v2.37（P1-E）：协作包装档案行——协作徽章 + 独立会话标注；无模型角标
      // （对端模型不可观测）、不进实况窗格；点击走转交线跳转分支
      if (a.collab) {
        // 已结束的协作行点击=详情卡（内含「回看协作结论」）；运行中的=跳转交线
        return `<div class="hg-dyn-agent peer ${a.done ? (a.err ? 'fail' : 'done') : 'run'}"` +
          ` ${a.done ? `data-hg-ag="${esc(a.id || '')}"` : 'data-hg-peer-row="1"'}` +
          ` title="${esc('协作代理（独立会话）· ' + (a.taskId || a.id || ''))}` +
          `${a.done ? ' · 已结束，点击看结论' : ' · 无实况窗格，点击尝试跳转交线'}">` +
          `<span class="hg-dyn-adot"></span>` +
          `<span class="hg-dyn-pbadge">协作</span>` +
          `<span class="hg-dyn-at">${esc(_AGENT_LABEL[a.type] || a.type)}</span>` +
          (a.desc ? `<span class="hg-dyn-desc" title="${esc(a.desc)}">${esc(a.desc)}</span>` : '') +
          (!a.done ? `<b class="hg-dyn-el" data-t0="${a.t0}">0s</b>` : '<b class="hg-dyn-el">已结束</b>') +
          '</div>';
      }
      // v2.36：中断态补 halt 修饰类（点/文字/耗时转橙，与失败红区分；仅类名）
      const cls = a.replay ? 'hist' : !a.done ? 'run'
        : (a.err ? (a.interrupted ? 'fail halt' : 'fail') : 'done');
      let el;
      if (!a.done) el = `<b class="hg-dyn-el" data-t0="${a.t0}">0s</b>`;
      else if (a.replay) el = '<b class="hg-dyn-el">历史</b>';
      else if (a.err) el = `<b class="hg-dyn-el">${a.interrupted ? '已中断' : '失败'}</b>`;
      else el = `<b class="hg-dyn-el">${a.t0 ? fmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000))) : '完成'}</b>`;
      const key = a.replay ? a.rid : a.id;
      // v2.35（P1-4）：模型角标——实跑 model 优先，frontmatter 预显示兜底，
      // 内置代理（无定义文件）标「主链模型」；后台代理加「后台」标
      const mdl = a.model || (_HG.agentModels && _HG.agentModels[a.type]) || '';
      const mdlTxt = a.replay ? '' :
        `<span class="hg-dyn-amdl" title="${esc(mdl ? '子代理模型：' + mdl : '内置/无定义文件代理，按 CLI 行为跑主链模型')}">${esc(mdl || '主链模型')}${a.bg ? ' · 后台' : ''}</span>`;
      return `<div class="hg-dyn-agent ${cls}" data-hg-ag="${esc(key || '')}"` +
        (a.tokens ? ` title="用量：${a.tokens} tokens · ${a.toolN || 0} 次工具"` : '') + `>` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-at">${esc(_AGENT_LABEL[a.type] || a.type)}</span>` +
        mdlTxt +
        (a.desc ? `<span class="hg-dyn-desc" title="${esc(a.desc)}">${esc(a.desc)}</span>` : '') +
        el + '</div>';
    }).join('') + peers.map(el => {
      const pend = !el.dataset.done;
      const t0 = +(el.dataset.t0 || 0) || Date.now();
      const doneAt = +(el.dataset.done || 0);
      // v2.37（P1-F①）：友好名 + 同基名委托序号——裸会话/任务 ID 永远收 title
      const raw = el.dataset.peer || '其他会话';
      const base = _pbase(el);
      const sameBase = peers.filter(x => _pbase(x) === base)
        .sort((a, b) => (+(a.dataset.t0 || 0)) - (+(b.dataset.t0 || 0)));
      const disp = _baseCount[base] > 1 ? `${base}·#${sameBase.indexOf(el) + 1}` : base;
      const durTxt = doneAt ? fmtDur(Math.max(1, Math.round((doneAt - t0) / 1000))) : '';
      const sum = el.dataset.psum || '';
      // v2.41R2：过滤头已排除 unknown/stale 线（不上面板），此处 stale/unknown
      // 恒 false，「疑似残留/状态未知」分支全不可达，摘除死代码；标记逻辑本身
      // 保留在 dataset 派生层，供 _hgPeerPending/迟回传定格/verify 等消费
      return `<div class="hg-dyn-agent peer ${pend ? 'run' : 'done'}" data-hg-peer-row="1"` +
        ` title="${esc(raw !== disp ? raw + '\n' : '')}${pend ? '协作中：独立会话无实况窗格，点击跳转交线' : '已回传，点击跳转交线'}">` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-pbadge">协作</span>` +
        `<span class="hg-dyn-at">${esc(disp)}</span>` +
        `<span class="hg-dyn-desc">${esc(pend ? '等待结论回传' : (sum ? sum : '已回传'))}</span>` +
        (pend ? `<b class="hg-dyn-el" data-t0="${t0}">0s</b>` : `<b class="hg-dyn-el">${durTxt}</b>`) + '</div>';
    }).join('');
    // v2.39：重渲恢复已展开的详情卡——上面 innerHTML 全量覆盖会把插在行后
    // 的详情卡冲掉（用户实锤「点击展开后不一会又缩回去」）。条目已滚出列表
    // （60s 完成窗口/上限 5）则清展开态，不复活孤儿卡。
    const openId = (_HG.dyn || {}).agentDetailOpen;
    if (openId) {
      const row = sec.querySelector(`[data-hg-d-aglist] [data-hg-ag="${CSS.escape(openId)}"]`);
      const a = (_HG.agents || {})[openId]
        || ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => x.rid === openId);
      if (row && a) row.insertAdjacentElement('afterend', _hgAgentDetailEl(openId, a));
      else if (_HG.dyn) _HG.dyn.agentDetailOpen = null;
    }
  }
  function _dynActs() {                  // E 最近工具：ring 20 条倒序，点击跳消息流，Bash 可复制
    const sec = _sec('acts');
    const acts = (_HG.dyn && _HG.dyn.acts) || [];
    sec.hidden = !acts.length;
    if (!acts.length) return;
    sec.querySelector('[data-hg-d-acts]').innerHTML = acts.slice().reverse().map(a => {
      const cls = a.done ? (a.err ? 'fail' : 'done') : 'run';
      const el = !a.done
        ? `<b class="hg-dyn-el" data-t0="${a.t0}">0s</b>`
        : `<b class="hg-dyn-el">${a.err ? '失败' : fmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000)))}</b>`;
      const cp = a.kind === 'bash' && a.preview
        ? `<button class="hg-dyn-actcp" data-hg-actcp="${esc(a.tid)}" title="复制命令">⧉</button>` : '';
      return `<div class="hg-dyn-act ${cls}" data-hg-act="${esc(a.tid)}" title="${esc(a.preview || a.label || '')}">` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-at">${esc(a.label || a.name)}</span>` +
        `<span class="hg-dyn-desc">${esc(String(a.preview || '').slice(0, 60))}</span>${cp}${el}</div>`;
    }).join('');
  }
  function _dynTurns() {                 // F 回合历史：ring 10 条倒序 + 累计
    const sec = _sec('turns');
    const turns = (_HG.dyn && _HG.dyn.turns) || [];
    sec.hidden = !turns.length;
    if (!turns.length) return;
    const sum = turns.reduce((s2, t) => s2 + t.dur, 0);
    sec.querySelector('[data-hg-d-tsum]').textContent = '累计 ' + fmtDur(sum);
    sec.querySelector('[data-hg-d-tlist]').innerHTML = turns.slice().reverse().map(t =>
      `<div class="hg-dyn-turn ${t.st}"><span class="hg-dyn-tk">${_TURN_ICO[t.st] || '·'}</span>` +
      `<span class="hg-dyn-tn">#${t.n}</span><span class="hg-dyn-td">${fmtDur(t.dur)}</span>` +
      (t.tools ? `<span class="hg-dyn-tt2">${t.tools} 工具</span>` : '') + '</div>').join('');
  }
  function _dynFiles() {                 // G 当前文件：活动流派生最近 3 个文件路径
    const sec = _sec('files');
    const acts = (_HG.dyn && _HG.dyn.acts) || [];
    const files = [];
    for (let i = acts.length - 1; i >= 0 && files.length < 3; i--) {
      const a = acts[i];
      if (_FILE_TOOLS.includes(a.name) && a.preview && !files.includes(a.preview)) files.push(a.preview);
    }
    sec.hidden = !files.length;
    if (!files.length) return;
    sec.querySelector('[data-hg-d-flist]').innerHTML = files.map(f =>
      `<div class="hg-dyn-file" title="${esc(f)}">${esc(f.split(/[\\/]/).pop())}</div>`).join('');
  }
  // 秒级计时：全局单例 interval（闭包随 tab 重开重执行，直接 setInterval 会
  // 叠加）；仅 hg-mode 可见且页面可见才动，且只改 textContent 不重建 DOM。
  if (!window._hgDynTick) {
    window._hgDynTick = setInterval(() => {
      // v2.37（P0-B/F③）：自愈先于 hg-mode 守卫——①面板 DOM 被外层重建后
      // dynEl 失联（ detached 节点真值仍为真，渲染进死节点=面板只见初始态）
      // → 重联重渲；②消息流里未定格转交线的秒表计时器丢失（快照恢复遗漏/
      // 异常路径清掉）→ 按 dataset 重挂。两者都是每秒一次的廉价扫描。
      try {
        if (!dynEl || !dynEl.isConnected) {
          const nd = document.querySelector('[data-hg-dyn]');
          if (nd && nd !== dynEl) { dynEl = nd; renderSideStatus(); }
        }
      } catch(_) {}
      try {
        _hgPeerStaleSweep();   // v2.37R6：>30min 标疑似残留并停表
        flow.querySelectorAll('.h-switch[data-peer]:not([data-done]):not([data-stale]):not([data-unknown])').forEach(rl => {
          if (!rl._peerTimer) _hgPeerTimerStart(rl, +(rl.dataset.t0 || 0) || Date.now());
        });
      } catch(_) {}
      if (document.hidden || !_hgAiPanel || !_hgAiPanel.classList.contains('hg-mode')) return;
      dynEl.querySelectorAll('[data-t0]').forEach(el => {
        el.textContent = fmtDur(Math.max(1, Math.round((Date.now() - +(el.dataset.t0 || 0)) / 1000)));
      });
      // 状态区活动词跟随（压缩等特殊词以 actEl 为准，面板同词）
      if (_HG.busy) {
        const src = actEl.querySelector('[data-hg-aw]');
        const stEl = dynEl.querySelector('[data-hg-d-st]');
        if (stEl && src && src.classList.contains('hg-act-special')) stEl.textContent = src.textContent;
      }
    }, 1000);
  }
  _hgPanelEnterHook = () => { _hgRolesFetch(); _hgAgentModelsFetch(); renderSideStatus(); };
  renderSideStatus();                    // 闭包（重）执行完先刷一遍（如重开 tab 恢复现场）

  // ==================== v2.33 子代理实时窗格 ====================
  // 主会话派 Agent(dev/reviewer/executor…) 时，聊天区右侧自动弹出可调宽窗格，
  // 按 parent_tool_use_id 精确分流显示各子代理的实时文本/工具调用（并行多开
  // 分 tab）。定位：临时实时镜像视图——主 flow 的灰色 sub 行照旧保留（历史
  // 完整性不动），回合终结窗格收起（主 flow 是唯一持久记录处）。
  const _subPaneEl = q('[data-hg-subpane]');
  const _subTabsEl = q('[data-hg-subtabs]');
  const _subBodyEl = q('[data-hg-subbody]');
  // v2.35（P0-3）：manual=用户手动打开/重开的窗格——回合终结不自动收起，
  // 只有 ✕ 手动关；自动弹出的窗格（Task 起跑）保持原行为（回合终结收起）。
  const _sub = { tabs: {}, order: [], active: null, manual: false };
  function _subReset() {
    _sub.tabs = {}; _sub.order = []; _sub.active = null; _sub.manual = false;
    if (_subPaneEl) { _subPaneEl.style.display = 'none'; _subTabsEl.innerHTML = ''; _subBodyEl.innerHTML = ''; }
  }
  function _subShow() {
    if (!_subPaneEl || _subPaneEl.style.display !== 'none') return;
    let w = 0;
    try { w = +(localStorage.getItem('hg-subpane-w') || 0); } catch(_) {}
    _subPaneEl.style.width = (w >= 220 && w <= 640 ? w : 320) + 'px';
    _subPaneEl.style.display = 'flex';
  }
  function _subOpen(tid, type, desc, replay) {
    if (!_subPaneEl) return;
    if (!_sub.tabs[tid]) {
      const sc = document.createElement('div');
      sc.className = 'hg-sub-msgs'; sc.dataset.tid = tid;
      // v2.35（P1-4）：tab 带模型角标（frontmatter 预显示；实跑 model 由
      // 子代理 assistant 事件到达时覆盖并重绘）
      // v2.35.1（F2）：运行态从档案派生——已完成代理被 tab 上限逐出后经
      // _subReopen 重建，不得回到「运行中」绿点（档案缺失的兜底才视为运行）
      // v2.38：replay=true=历史回放 tab（无绿点、置灰、带「回放」徽章）
      const _ag = (_HG.agents || {})[tid] || {};
      _sub.tabs[tid] = { label: _AGENT_LABEL[type] || type, type, desc, sc,
                         run: replay ? false : (!('done' in _ag) || !_ag.done),
                         err: !!_ag.err, replay: !!replay,
                         model: _ag.model || '' };
      _sub.order.push(tid);
      if (_sub.order.length > 6) {          // 上限 6 个 tab，最旧让位
        const old = _sub.order.shift();
        if (_sub.tabs[old] && _sub.tabs[old].sc.parentNode) _sub.tabs[old].sc.remove();
        delete _sub.tabs[old];
      }
      _subBodyEl.appendChild(sc);
    }
    _subShow(); _subTabsPaint(); _subActivate(tid);
  }
  // v2.38：历史子代理回放窗格——数据源是子代理自己的转写（独立 session
  // jsonl，经 /subagent_replay 按 agentId 取），不是内存事件流；切会话快照
  // 往返后内容随 DOM 保留，仍可重开重拉（源在转写，永远可重建）
  // v2.41：不可回放结论记忆（agentId 全局唯一作键）——found=false 即转写
  // 文件不存在（旧会话/被清理/跨会话协作），重拉永远同结果；记入本集后
  // 再点「回放该子代理过程」直接出示结论不发请求。同 tab 防重由既有
  // sc.dataset.replayed 承担（fetch 前写入、found=false 不清除即早退），本集
  // 补 tab 被上限逐出/_subDrop 后重开的场景（新 sc 无标记，否则会重拉）。
  // v2.42：后端已加新版 CLI tasks 转写兜底源，found=false 场景收窄但仍有
  // （转写被清理等），文案同步改中性不再断言具体原因
  const _subNoreplay = new Set();
  const _subNoReplayNote = () =>
    '<div class="hg-sub-replay-note">未找到该子代理的转写记录，历史过程不可回放</div>';
  function _subReplay(tid, type, desc, agentId) {
    if (!_subPaneEl) return;
    const a = (_HG.agents || {})[tid] || {};
    // 协作包装（P1-E 边界）：独立会话无本侧可拉的事件流转写——只展示结论
    if (a.collab) {
      _subOpen(tid, type, desc, true);
      const sc0 = _sub.tabs[tid] && _sub.tabs[tid].sc;
      if (sc0 && !sc0.dataset.collabNote) {
        sc0.dataset.collabNote = '1';
        // v2.37R4（终审1）：拆两次 _subAppend——单根 append 语义下双根模板
        // 的第二个 div（结论正文）会被整体丢弃
        _subAppend(sc0, `<div class="hg-sub-replay-note">独立会话协作代理——过程不可回看，仅结论可回看</div>`, true);
        _subAppend(sc0, `<div class="hg-sub-msg">${esc(a.result || '（无结论记录）')}</div>`, true);
      }
      _sub.manual = true;
      return;
    }
    if (!agentId) { showBanner('该子代理没有 agentId 记录，无法回放', 2600); return; }
    _subOpen(tid, type, desc, true);
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (!sc) return;
    if (sc.dataset.replayed === agentId) { _sub.manual = true; return; }   // 已拉过
    if (_subNoreplay.has(agentId)) {      // v2.41：已判定不可回放——直接出示结论，不再发请求
      sc.innerHTML = '';
      sc.dataset.replayed = agentId;
      _subAppend(sc, _subNoReplayNote(), true);
      _sub.manual = true;
      return;
    }
    sc.innerHTML = '';
    sc.dataset.replayed = agentId;
    _subAppend(sc, `<div class="hg-sub-replay-note">回放加载中…</div>`, true);
    _sub.manual = true;
    const sidAt = _HG.sid;
    fetch(`/api/harness/subagent_replay?sid=${encodeURIComponent(sidAt || '')}&agent=${encodeURIComponent(agentId)}`)
      .then(r => r.json())
      .then(j => {
        // v2.37R2（复审1）：失败路径必须清 replayed 标记并给错误文案——标记
        // 不清则重点按钮永远早退，唯一恢复=切走重切
        if (!j || !j.ok || _HG.sid !== sidAt) {
          const scf = _sub.tabs[tid] && _sub.tabs[tid].sc;
          if (scf) {
            delete scf.dataset.replayed;
            if (_HG.sid === sidAt) {   // 会话已切走的不动现flow（可能已属别会话窗格）
              scf.innerHTML = '';
              _subAppend(scf, `<div class="hg-sub-replay-note">${(j && j.err) ? esc('回放读取失败：' + j.err) : '回放读取失败——重新点击「回放该子代理过程」可重试'}</div>`, true);
            }
          }
          return;
        }
        const sc2 = _sub.tabs[tid] && _sub.tabs[tid].sc;
        if (!sc2) return;
        sc2.innerHTML = '';
        if (!j.found) {
          // v2.42：后端双源（projects 旧源+新版 CLI tasks 兜底）均未命中——
          // 文件不存在是持久事实，重拉永远同结果；记住结论，重点/重开不再发请求
          _subNoreplay.add(agentId);
          _subAppend(sc2, _subNoReplayNote(), true);
          return;
        }
        if (!(j.rows || []).length) {
          // v2.41R2：转写存在但无可渲染行——与「没有独立转写」是两回事，给中性
          // 文案且不进 noreplay 集（tab 重开后可重试，防误判永久锁死回放入口）
          _subAppend(sc2, '<div class="hg-sub-replay-note">转写存在但无可回放内容</div>', true);
          return;
        }
        _subAppend(sc2, `<div class="hg-sub-replay-note">回放 · ${esc(_AGENT_LABEL[type] || type)} · ${j.rows.length} 条记录</div>`, true);
        for (const row of j.rows) {
          if (row.k === 'text') {
            // 每行带头像+模型徽章（P1-C 体系复用）——标明这句话是谁发的
            // v2.37R4（终审1）：拆两次 _subAppend——单根 append 下双根模板
            // 的第二个 div（row.text 正文）会被整体丢弃
            const bare = String(row.model || '').split('[')[0] || row.model || '未知';
            _subAppend(sc2, `<div class="hg-sub-msg"><span class="h-ava ${_hgAvaCls(bare)}">${esc(bare.charAt(0).toUpperCase())}</span>` +
              `<span class="h-mmodel">${esc(bare)}</span></div>`, true);
            // 窗格重设计 P1-3：正文升级 md 渲染（懒高亮）——回放一次灌几十条，
            // 即时增强必卡，IO 挂上滚到哪亮到哪
            _subAppendEl(sc2, _subMdRow(row.text), true);
          } else if (row.k === 'note') {
            _subAppend(sc2, `<div class="hg-sub-replay-note">${esc(row.text)}</div>`, true);
          } else if (row.k === 'tool') {
            // 窗格重设计 P2-7：回放行直接定格 done（历史已完结）；转写无
            // tool_use_id，不做配对
            _subAppend(sc2, `<div class="hg-sub-tool done"><span class="hg-sub-tdot"></span>${esc(_hDrawerName(row.name || ''))}` +
              (row.hint ? ` · ${esc(row.hint)}` : '') + '</div>', true);
          } else if (row.k === 'result') {
            // 窗格重设计 P2-8：同实况结果行——超 120 字可点击展开全文
            const rfull = String(row.text || '');
            const rtxt = rfull.replace(/\s+/g, ' ').trim().slice(0, 120);
            _subAppend(sc2, `<div class="hg-sub-res${row.err ? ' err' : ''}"` +
              (rfull.trim().length > 120 ? ` data-hg-subfull="${esc(rfull)}" title="点击展开全文"` : '') +
              `>↳ ${esc(rtxt || '完成')}</div>`, true);
          }
        }
        _subScroll(tid);
      })
      .catch(() => {
        const sc3 = _sub.tabs[tid] && _sub.tabs[tid].sc;
        if (sc3) {
          delete sc3.dataset.replayed;   // v2.37R2（复审1）：清标记，重点即重拉
          sc3.innerHTML = ''; _subAppend(sc3, `<div class="hg-sub-replay-note">回放拉取失败（网络）——重新点击「回放该子代理过程」可重试</div>`, true);
        }
      });
    _subScroll(tid);
  }
  function _subActivate(tid) {
    if (!_sub.tabs[tid]) return;
    _sub.active = tid;
    _subBodyEl.querySelectorAll('.hg-sub-msgs').forEach(x =>
      x.style.display = x.dataset.tid === tid ? '' : 'none');
    _subTabsPaint(); _subScroll(tid);
  }
  function _subTabsPaint() {
    if (!_subTabsEl) return;
    _subTabsEl.innerHTML = _sub.order.filter(t => _sub.tabs[t]).map(t => {
      const tb = _sub.tabs[t];
      // v2.35（P1-4）：模型进 tab（短名+悬浮全名）；tokens 进悬浮（CLI 侧计数）
      const ag = (_HG.agents || {})[t] || {};
      const mdlFull = tb.model || '';
      const mdlShort = mdlFull.length > 14 ? mdlFull.slice(0, 13) + '…' : mdlFull;
      const ttip = [tb.desc || tb.label,
                    mdlFull ? '模型：' + mdlFull : '模型：主链模型（内置/无定义文件）',
                    ag.tokens ? `用量：${ag.tokens} tokens · ${ag.toolN || 0} 次工具` : '']
        .filter(Boolean).join('\n');
      return `<div class="hg-sub-tab${t === _sub.active ? ' active' : ''}${tb.run ? ' run' : tb.err ? ' err' : ''}${tb.replay ? ' replay' : ''}"` +
        ` data-hg-subtab="${esc(t)}" title="${esc(ttip)}">` +
        `<span class="hg-sub-dot"></span>${esc(tb.label)}` +
        (tb.replay ? `<span class="hg-sub-rp">回放</span>` : '') +
        (mdlShort ? `<span class="hg-sub-mdl">${esc(mdlShort)}</span>` : '') +
        // 窗格重设计 P1-1：单-tab ✕——hover 才浮现（CSS 控制），运行中的 tab
        // 提示「任务继续后台跑」防误触焦虑；点击走 _subDrop（tab 条委托分支）
        `<span class="hg-sub-x2" data-hg-subclose="${esc(t)}" title="${esc(tb.run ? '关闭视图（任务继续在后台跑）' : '关闭该 tab')}">✕</span></div>`;
    }).join('');
  }
  function _subScroll(tid) {
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (sc) sc.scrollTop = sc.scrollHeight;
  }
  // 窗格重设计 P1-4：cap 删首不再静默——首删插「⬆ 已省略 N 行」提示条占住
  // 头部，其后每删一条只累进计数（不重复插）；提示条自身占 1 个行名额。
  // 回放路径 noCap 绕过本函数，语义不变
  function _subCap(sc) {
    while (sc.children.length > 200) {
      const first = sc.firstElementChild;
      if (!first) break;
      if (first.classList.contains('hg-sub-omit')) {
        first.dataset.omitted = String((+first.dataset.omitted || 0) + 1);
        first.textContent = `⬆ 已省略 ${first.dataset.omitted} 行`;
        // 提示条已是首条：真正该删的是它后面那条内容行
        const victim = first.nextElementSibling;
        if (victim) victim.remove(); else first.remove();
      } else {
        const om = document.createElement('div');
        om.className = 'hg-sub-omit';
        om.dataset.omitted = '1';
        om.textContent = '⬆ 已省略 1 行';
        sc.insertBefore(om, first);
        first.remove();
      }
    }
  }
  function _subAppend(sc, html, noCap) {   // 上限 200 条/子代理，溢出删首条
    const d = document.createElement('div');
    d.innerHTML = html;
    sc.appendChild(d.firstElementChild || d);
    // v2.37R3（复审A）：noCap=true=回放路径——回放 201~202 行（含头部 note）
    // 会被 200 上限削掉头部 note 和领命首行、「已截断」告知自身也保不住，
    // 故整段绕过 cap；实时 tab 的 200 上限语义不变
    if (!noCap) _subCap(sc);
  }
  // 窗格重设计 P1-3（复审勘误）：元素直挂的必要性只在懒高亮——
  // _codeLazyEnhance 的 IO observe 的是元素实例，字符串通道（outerHTML→
  // innerHTML 克隆）进 DOM 的新节点永不被 observe、永不增强。链接拦截不
  // 构成理由：renderMd 自身就 return t.innerHTML，直绑监听器每次渲染必丢
  // （与通道无关），窗格链接点击实际由 init.js 的 document 捕获阶段全局
  // 拦截器兜底。窗格不进快照（无 innerHTML 重建），IO 绑定随元素存活到
  // tab 关闭
  function _subAppendEl(sc, el, noCap) {
    sc.appendChild(el);
    if (!noCap) _subCap(sc);
  }
  // 窗格重设计 P1-3：窗格 md 行工厂——renderMd 内核 + 复用 .h-bubble 全局
  // 排版规则（p/pre/code/ul），窗格窄列字号由 .hg-sub-msgmd 收敛（.h-msg
  // 作用域的气泡 padding 不命中本行）；高亮走懒增强——子代理长代码白高亮
  // 是 CPU 大户，滚到视口才亮
  function _subMdRow(text) {
    const d = document.createElement('div');
    d.className = 'h-bubble hg-sub-msgmd';
    d.innerHTML = renderMd(text);
    _codeLazyEnhance(d);
    return d;
  }
  function _subFeed(parentId, blocks) {
    if (!_sub.tabs[parentId]) return;
    const sc = _sub.tabs[parentId].sc;
    // 窗格重设计 P1-5：贴底跟随判定——必须在 append 之前测距底（append 后
    // scrollHeight 被新内容撑大，测出来恒不贴底）；≤80px=用户正跟读最新输出，
    // 才跟随滚动，上翻查看历史时不拽人
    const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;
    // v2.35：回合终结定格过的 tab，若对应代理其实还在跑（后台 Task 跨回合
    // 续跑），事件继续流入时恢复绿点脉冲——别让冻结态骗人
    const _ag = (_HG.agents || {})[parentId];
    if (_sub.tabs[parentId].run !== true && _ag && !_ag.done) {
      _sub.tabs[parentId].run = true;
      _subTabsPaint();
    }
    // 窗格重设计 P2-9：实况补头像+模型徽章行（对齐回放形态，消除两套不一致）。
    // 仅插一次（dataset 标记）；模型取实跑值（档案最新）优先、tab 建档快照兜底，
    // 都无（内置代理跑主链模型）用 tab 名——不编造，至少有头像色标
    if (!sc.dataset.avabadge) {
      sc.dataset.avabadge = '1';
      const mdl = (_ag && _ag.model) || _sub.tabs[parentId].model || _sub.tabs[parentId].label || '';
      const bare = String(mdl).split('[')[0] || mdl;
      const av = document.createElement('div');
      av.className = 'hg-sub-msg';
      av.innerHTML = `<span class="h-ava ${_hgAvaCls(bare)}">${esc(bare.charAt(0).toUpperCase())}</span>` +
        `<span class="h-mmodel">${esc(bare)}</span>`;
      sc.insertBefore(av, sc.firstElementChild);
    }
    for (const b of blocks) {
      // 窗格重设计 P1-3：文本行从裸 esc 升级 md 渲染（markdown-it + 懒高亮；
      // 元素直挂保懒高亮 IO 绑定，链接拦截由 init.js 全局捕获兜底）——
      // 子代理中间结论是 markdown，渲染质量对齐主 flow
      if (b.type === 'text' && b.text && b.text.trim())
        _subAppendEl(sc, _subMdRow(b.text));
      else if (b.type === 'thinking' && b.thinking) {
        // 窗格重设计 P2-6：thinking 进窗格——块粒度一行（不合并段），默认
        // 收起防淹；全文存 dataset，首次展开才 renderMd（懒渲染，量大不卡）。
        // 行内交互全走窗格体级委托（_subBodyEl onclick）
        const th = document.createElement('div');
        th.className = 'hg-sub-think';
        th.dataset.raw = b.thinking;
        th.innerHTML = '<button class="hg-sub-think-head" title="点击展开/收起思考过程">' +
          '<span>💭 思考</span><span class="hg-sub-think-chev">›</span></button>' +
          '<div class="hg-sub-think-body"></div>';
        _subAppendEl(sc, th);
      }
      else if (b.type === 'tool_use') {
        const inp = b.input || {};
        const hint = inp.command || inp.file_path || inp.path || inp.pattern ||
                     inp.query || inp.description || inp.subject || inp.prompt || '';
        // 窗格重设计 P2-7：工具行带状态点（灰=进行中）+ data-tuid——tool_result
        // 到达时按 tool_use_id 精确回点变绿（SSE 里 tool_use.id 与
        // tool_result.tool_use_id 同源恒可配对，并行工具交错不错标）
        _subAppend(sc, `<div class="hg-sub-tool" data-tuid="${esc(b.id || '')}">` +
          `<span class="hg-sub-tdot"></span>${esc(_hDrawerName(b.name || ''))}` +
          (hint ? ` · ${esc(String(hint).slice(0, 80))}` : '') + '</div>');
      }
    }
    if (stick) _subScroll(parentId);
  }
  function _subResult(parentId, tr) {
    if (!_sub.tabs[parentId]) return;
    const sc = _sub.tabs[parentId].sc;
    const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;   // P1-5：append 前测（同 _subFeed）
    const full = resultText(tr).trim();
    const txt = full.replace(/\s+/g, ' ').trim().slice(0, 120);
    // 窗格重设计 P2-7：结果到达回点对应工具行——data-tuid 精确配对优先；
    // miss（id 缺失/行已被 cap 裁掉）回退从尾往前找第一条未定格的工具行
    // （SSE 流序下 tool_result 紧跟 tool_use；已 done 的行说明配对过别的
    // 结果，跳过——并行交错时也能落到真正没收到结果的那条上）
    let toolRow = tr.tool_use_id
      ? sc.querySelector(`.hg-sub-tool[data-tuid="${CSS.escape(tr.tool_use_id)}"]`) : null;
    if (!toolRow)
      for (let el = sc.lastElementChild; el; el = el.previousElementSibling) {
        if (el.classList.contains('hg-sub-tool') && !el.classList.contains('done')) { toolRow = el; break; }
      }
    if (toolRow && !toolRow.classList.contains('done')) toolRow.classList.add('done');
    // 窗格重设计 P2-8：超 120 字的结果行不再截死——全文存 dataset，点击
    // 委托展开/收起
    _subAppend(sc, `<div class="hg-sub-res${tr.is_error ? ' err' : ''}"` +
      (full.length > 120 ? ` data-hg-subfull="${esc(full)}" title="点击展开全文"` : '') +
      `>↳ ${esc(txt || '完成')}</div>`);
    if (stick) _subScroll(parentId);
  }
  function _subClose(tid, err) {
    const tb = _sub.tabs[tid];
    if (!tb) return;
    tb.run = false; tb.err = !!err;
    _subTabsPaint();
  }
  function _subEnd() {                     // 回合终结：全部定格；自动来源收起窗格
    let any = false;
    for (const t in _sub.tabs) { _sub.tabs[t].run = false; any = true; }
    if (any) _subTabsPaint();
    // v2.35（P0-3）：用户手动打开的窗格不自动收——用户正在围观，收走就是
    // 「弹了出来一会又收回去了」；只有 ✕ 手动关。切会话/关 tab 清空不变。
    if (_subPaneEl && !_sub.manual) _subPaneEl.style.display = 'none';
  }
  if (_subTabsEl) _subTabsEl.onclick = (e) => {
    // 窗格重设计 P1-1/P1-2：单-tab ✕——✕ 在 [data-hg-subtab] 容器内部，
    // 分支必须放在激活分支之前并 return（否则点 ✕ 变切 tab）。运行态要在
    // drop 之前取（drop 后 tab 档案即散）；运行中给去向 toast——任务在后台
    // 继续，面板子代理区/主 flow 子代理行随时可重开（_subReopen）
    const xc = e.target.closest('[data-hg-subclose]');
    if (xc) {
      e.stopPropagation();
      const tid = xc.dataset.hgSubclose;
      const wasRun = !!(_sub.tabs[tid] && _sub.tabs[tid].run);
      _subDrop(tid);
      if (wasRun) showBanner('已关闭视图——任务继续后台运行，可在面板子代理区重新打开', 3200);
      return;
    }
    const t = e.target.closest('[data-hg-subtab]');
    if (t) _subActivate(t.dataset.hgSubtab);
  };
  // 窗格重设计：窗格体行内交互全走 body 级事件委托——行是流式动态 append +
  // cap 删首，逐行直绑不可维护且 innerHTML 重建即丢（主 flow v2.12 的坑）。
  // md 代码块复制钮本在 flow 委托里，但窗格在 flow 外够不着，此处补一条
  // 同款分支。onclick 覆盖式绑定（闭包随 harness tab 重开重执行）
  if (_subBodyEl) _subBodyEl.onclick = (e) => {
    // md 代码块复制钮（就近取同容器 pre>code 文本）
    const cp = e.target.closest('.hg-code-copy');
    if (cp) {
      const codeBox = cp.closest('.hg-code');
      const code = codeBox && codeBox.querySelector('pre > code');
      if (code) copyText(code.textContent.replace(/\n$/, '')).then(ok => {
        if (ok) { const orig = cp.textContent; cp.textContent = '✓';
          setTimeout(() => cp.textContent = orig, 1500); }
      });
      return;
    }
    // P2-6：thinking 折叠行——首展懒渲染（dataset.raw → renderMd），再点收起
    const thHead = e.target.closest('.hg-sub-think-head');
    if (thHead) {
      const row = thHead.closest('.hg-sub-think');
      const body = row && row.querySelector('.hg-sub-think-body');
      if (row && body) {
        if (!row.classList.contains('open') && body.dataset.filled !== '1') {
          body.innerHTML = renderMd(row.dataset.raw || '');
          _codeLazyEnhance(body);
          body.dataset.filled = '1';
        }
        row.classList.toggle('open');
      }
      return;
    }
    // P2-8：结果行点击展开全文（data-hg-subfull 只在超 120 字的行上，短行不可
    // 点；dataset 键按浏览器规则转驼峰：data-hg-subfull → hgSubfull。属性名
    // 刻意避开拖宽条已有的 data-hg-subres 钩子，防全局选择器歧义）
    const resRow = e.target.closest('[data-hg-subfull]');
    if (resRow) {
      const full = resRow.dataset.hgSubfull || '';
      if (resRow.classList.toggle('open')) resRow.textContent = '↳ ' + full;
      else resRow.textContent = '↳ ' + full.replace(/\s+/g, ' ').trim().slice(0, 120);
      return;
    }
  };
  const _subRes = q('[data-hg-subres]');
  if (_subRes) _subRes.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const right = _subPaneEl.getBoundingClientRect().right;
    const move = (ev) => {
      const w = Math.min(640, Math.max(220, Math.round(right - ev.clientX)));
      _subPaneEl.style.width = w + 'px';
      try { localStorage.setItem('hg-subpane-w', w); } catch(_) {}
    };
    const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
  const _subX = q('[data-hg-subx]');
  if (_subX) _subX.onclick = () => {
    if (_subPaneEl) _subPaneEl.style.display = 'none';
    _sub.manual = false;   // v2.35（P0-3）：手动关即退出「回合终结不自动收起」模式
  };

  function renderList() {
    const kw = (searchEl.value || '').trim().toLowerCase();
    const items = _HG.sessions.filter(s => !kw || (s.title || '').toLowerCase().includes(kw)
      || (s.cwd || '').toLowerCase().includes(kw));
    // v2.3.9 项目分组视图（用户需求：一个项目多个会话归一组查找）：
    // 按 cwd basename 分组、组按组内最近活跃排序、组内会话按活跃排序。
    // v2.3.13 单会话组同样可折叠（用户实锤「单会话不能收缩」）——组头带
    // chev、点击开合，多会话组额外有计数徽章；开合 localStorage 持久化。
    const groups = new Map();   // proj -> {items: [], latest: 0, cwd: ''}
    for (const s of items) {
      const proj = (s.cwd || '').split(/[\\/]/).pop() || '~';
      let g = groups.get(proj);
      if (!g) { g = { items: [], latest: 0, cwd: s.cwd || '' }; groups.set(proj, g); }
      g.items.push(s);
      if ((s.last_active || 0) > g.latest) g.latest = s.last_active;
    }
    const ordered = [...groups.entries()].sort((a, b) => (b[1].latest || 0) - (a[1].latest || 0));
    // 折叠态：localStorage hg-grp:<proj>:closed（单会话组同权可折）
    const html = ordered.map(([proj, g]) => {
      g.items.sort((a, b) => (b.last_active || 0) - (a.last_active || 0));
      const multi = g.items.length > 1;
      const closed = (() => { try { return localStorage.getItem('hg-grp:' + proj + ':closed') === '1'; } catch(_) { return false; } })();
      const anyBusy = g.items.some(s => s.busy);
      const hasActive = g.items.some(s => s.sid === _HG.sid);
      let h = '';
      // 组头（所有组可折叠；多会话组带计数徽章）
      h += `<div class="hg-grp${closed ? ' closed' : ''}${hasActive ? ' active-grp' : ''}"
             data-grp="${esc(proj)}"
             title="${esc(g.cwd)}">
              <span class="hg-grp-chev">▸</span>
              <span class="hg-grp-name">${esc(proj)}</span>
              <span class="hg-grp-count">${multi ? g.items.length : ''}</span>
              ${anyBusy ? '<span class="hg-item-busy" title="回复中">●</span>' : ''}
              <span class="hg-grp-time">${_harnessRelTime(g.latest)}</span>
            </div>`;
      if (!closed) {
        // v2.3.13 子项统一 grp-child 分层（缩进+左侧竖线）——单会话组也要
        // 同款层次（用户实锤「单会话没有像多会话有分层效果」）；时间只在
        // 组头显示（单会话组头时间即该会话活跃时间，不重复出独立时间行）
        h += g.items.map(s => `
          <div class="hg-item${s.sid === _HG.sid ? ' active' : ''} grp-child" data-sid="${esc(s.sid)}" title="${esc(s.cwd || '')} · ${esc(s.title || '')}">
            <div class="hg-item-row">
              <span class="hg-item-title">${esc(s.title || '新会话')}</span>
              <span class="hg-item-acts">
                ${s.busy ? '<span class="hg-item-busy" title="回复中">●</span>' : ''}
                <button class="hg-item-act" data-act="rename" data-sid="${esc(s.sid)}" title="重命名">✎</button>
                <button class="hg-item-act del" data-act="del" data-sid="${esc(s.sid)}" title="删除会话">✕</button>
              </span>
            </div>
            <div class="hg-item-row">
              <span class="hg-item-sub">${s.model ? esc(s.model) + (_hgMm(s.model) ? ' ' + _HG_EYE : '') : ''}</span>
            </div>
          </div>`).join('');
      }
      return h;
    }).join('');
    listEl.innerHTML = html || '<div class="hg-list-empty">暂无会话</div>';
  }
  // v2.3.9 组头点击：折叠/展开（localStorage 记忆），不影响选会话
  listEl.addEventListener('click', (e) => {
    const grp = e.target.closest('.hg-grp');
    if (grp) {
      e.stopPropagation();
      const key = 'hg-grp:' + grp.dataset.grp + ':closed';
      const closed = grp.classList.toggle('closed');
      try { closed ? localStorage.setItem(key, '1') : localStorage.removeItem(key); } catch(_) {}
      renderList();
    }
  });
  // v2.2.1：相对时间随钟表 tick 且对话中实时刷新（用户实锤：对话进行中
  // 列表仍定格旧时间——refreshSessions 只在回复结束才拉，60s 只重渲旧数据
  // 没用）。这里 60s 真拉一次列表（一个轻 GET）：对话中的会话时间滚动到
  // 「1分钟前/刚刚」，活跃会话按 last_active 排到最前。
  setInterval(() => {
    refreshSessions();
  }, 60000);
  listEl.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-act]');
    if (act) {
      e.stopPropagation();
      const sid = act.dataset.sid;
      if (act.dataset.act === 'del') {
        const ok = await hgConfirm('删除会话', '删除后该会话从列表移除（~/.claude 转写保留）。确定删除？');
        if (!ok) return;
        await fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid})});
        delete _HG.cache[sid];
        delete _HG.attsBy[sid];   // v2.3.0：暂存附件随会话清
        delete _HG.queues[sid];   // v2.25：排队草稿随会话清（审计 §三.9）
        try { localStorage.removeItem('hg-open:' + sid); localStorage.removeItem('hg-ctx:' + sid); } catch(_) {}   // v2.16：连开合/用量记录一起清
        if (_HG.sid === sid) switchTo(null); else refreshSessions();
      } else if (act.dataset.act === 'rename') {
        const s = _HG.sessions.find(x => x.sid === sid);
        const t = await hgPrompt('重命名会话', '会话名称', (s && s.title) || '');
        if (t === null) return;
        await fetch('/api/harness/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid, title: t})});
        refreshSessions();
        if (_HG.sid === sid) { titleEl.textContent = t || '会话'; conn.tab.querySelector('.label').textContent = titleEl.textContent; }
      }
      return;
    }
    const item = e.target.closest('.hg-item');
    if (item && item.dataset.sid) switchTo(item.dataset.sid);
  });
  searchEl.addEventListener('input', renderList);

  // ==================== 发送 ====================
  function newChat() {
    saveCache(); switchTo(null);
    // v2.25：新建 = 无工程默认状态——上个会话的项目目录不再继承（用户实测
    // 「点新建会话，打开的还是串口控制台Pro，不对」）。发消息时 cwd 为空
    // 即开在默认 ~；chip 回显「选择项目」。切回历史会话仍跟随恢复该会话的
    // 项目（v2.19）；localStorage 的 hg-last-cwd 不动，留给下次启动恢复。
    if (_HG.cwd) { _HG.cwd = null; projChipLabel(); }
  }
  q('[data-hg-new]').onclick = newChat;

  async function ensureSession() {
    if (_HG.sid) return _HG.sid;
    const r = await fetch('/api/harness/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model: _HG.model || '', cwd: _HG.cwd || '',
                            permission: _HG.perm || 'auto', think: _HG.thinkLv || ''})});
    const j = await r.json();
    if (!j.ok) {
      // v2.19：恢复的「上次项目目录」已被删/移动 → 清记录回退 ~ 重试一次，
      // 而不是卡在报错里让用户手动重选。
      if (j.err && j.err.includes('目录不存在') && _HG.cwd) {
        showBanner('上次的项目目录已不存在：' + _HG.cwd, 3500, true);
        _HG.cwd = null; _hgSaveCwd(null); projChipLabel();
        return ensureSession();
      }
      if (j.err && j.err.includes('未检测到 claude')) { openClaudeSetup(); }
      showBanner(j.err || '会话创建失败', 3500, true);
      return null;
    }
    _HG.sid = j.sid; _HG.seq = 0; _HG.alive = true;
    titleEl.textContent = '新会话';
    cwdEl.textContent = (j.cwd || '').split(/[\\/]/).pop() || '~';
    openSSE(j.sid, 0);
    refreshSessions();
    return j.sid;
  }

  // v2.20：发送核心从 send() 抽出——排队泵（queuePump）发送队列项走同一
  // 条路（乐观渲染 + POST + 回滚）。restoreInput=true 时失败把文本放回
  // 输入框（手动发送场景）；排队项失败只 banner（文本无处可回）。
  async function dispatch(text, images, files, restoreInput) {
    const sid = await ensureSession();
    if (!sid) return false;
    // v2.27：引用拼装——取出即清（排队泵逐条 dispatch 时只有第一条带引用，
    // 后续排队项是新输入的独立消息）
    let out = text || '';
    if (_HG.quote && out.trim()) {
      const qt = _HG.quote.text.length > 2000
        ? _HG.quote.text.slice(0, 2000) + '…（引用已截断）' : _HG.quote.text;
      out = `[引用 ${_HG.quote.who} 的消息]\n${qt}\n\n[我的问题]\n${text}`;
      setQuote(null);
    }
    text = out;
    _hgHistAppend(sid, text);          // 输入历史（记录到真实会话 scope）
    _HG.histNav = null;
    // v2.20：乐观渲染——connect 一回来就画出自己的气泡。原实现要等 SSE 的
    // user_echo 绕一圈才显示，新会话冷启动时「发出去半天上面没动静」（用户
    // 实测）。echoFast 让随后到达的 SSE 同文本 echo 跳过，不双渲染。
    const el = renderUser(text, images, files);
    _HG.echoFast = { text: text || '' };
    scrollBottom(true);                 // 自己发的消息无条件回底
    setBusy(true);
    try {
      const r = await fetch('/api/harness/send', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid, text, images, files})});
      const j = await r.json();
      if (!j.ok) {
        try { el.remove(); } catch(_) {}       // 回滚乐观气泡
        endThinking(); grpFinalize(false);
        dispatch.rej = String(j.err || '');    // v2.35.1（F6）：失败原因外显（queuePump 据此判可回队）
        // v2.35.1（F6）：后端「正在回复」= 后端真忙（前端误判空闲的竞态）——
        // 同步置 busy 而非清空闲：清空闲会连锁触发泵链把整队消息逐条打进
        // 拒收丢弃；置 busy 则泵链挂起、排队条目由 queuePump 回队首，真回合
        // 结束再发。直发（非泵）命中则按排队语义入队，消息不丢。其余失败
        // 维持原行为（清空闲 + 文本回输入框）
        if (/正在回复/.test(dispatch.rej)) {
          setBusy(true);
          if (restoreInput) queuePush({ text: text || '', images: images || [], files: files || [] });
        }
        else {
          setBusy(false);
          if (restoreInput) input.value = text;
        }
        showBanner(j.err || '发送失败', 3000, true);
        return false;
      }
      dispatch.rej = '';
      _HG.dirty = true;
      refreshSessions();
      return true;
    } catch(e) {
      dispatch.rej = 'network';
      try { el.remove(); } catch(_) {}
      endThinking(); grpFinalize(false); setBusy(false);
      if (restoreInput) input.value = text;
      showBanner('发送失败：' + e, 3000, true);
      return false;
    }
  }
  // ==================== 内建斜杠命令（v2.21）====================
  // harness 跑的是 claude -p headless：CLI 的交互式命令（/resume /clear…）
  // 到不了进程。输入 / 开头且命中下表 → 前端本地执行（不排队、不发后端，
  // busy 时也即时生效）；其余 /xxx 照常发送，技能/项目自定义命令不受影响。
  const HG_SLASH = [
    ['/help', '内建命令一览'],
    ['/resume', '切换会话（左侧列表高亮）'],
    ['/clear', '新建会话（原会话保留可切回）'],
    ['/model', '打开模型菜单；/model 名 直接切换（模糊匹配）'],
    ['/status', '会话状态与上下文用量'],
    ['/compact', '手动压缩上下文（可附保留要点：/compact 保留串口配置等）'],
    ['/rewind', '回退最近 N 个完整回合，默认 1（爆窗/坏回合逃生门；历史自动备份）'],
    ['/roles', '三角色设计说明（决策者/执行者/编程者与当前配置）'],
    ['/mcp', 'MCP 服务器列表与连接状态（代跑 claude mcp list）'],
    ['/exit', '退出 claude 进程（会话保留，发送自动恢复）'],
  ];
  // v2.25：CLI 纯交互命令——harness 跑的是 claude -p（headless 无 TTY），
  // 这些命令进去没有渲染面，直接发送只会被模型当普通文本白白消费一轮
  // 回复。本地拦下说明去向，不进对话。
  const HG_SLASH_DEAD = [
    ['/ide', '连接 IDE（headless 无此通道，用终端交互模式操作）'],
    ['/vim', 'vim 编辑模式（交互 TUI 专属）'],
    ['/terminal-setup', '终端按键配置（交互 TUI 专属）'],
    ['/statusline', '状态栏定制（交互 TUI 专属）'],
    ['/login', '账号登录（交互流程，headless 无法弹授权页）'],
    ['/logout', '账号登出（同上，在终端交互模式里操作）'],
    ['/doctor', '安装诊断（交互 TUI 专属）'],
    ['/install-github-app', 'GitHub App 引导（需浏览器授权流程）'],
    ['/migrate-installer', '安装迁移（交互 TUI 专属）'],
    ['/release-notes', '版本说明（交互 TUI 专属）'],
    ['/privacy-settings', '隐私设置（交互 TUI 专属）'],
    ['/config', '设置面板（headless 下改配置用本工具 设置 → API 配置）'],
    ['/permissions', '权限面板（会话级权限在工具栏「权限」切换）'],
    ['/hooks', 'Hooks 管理（直接改 ~/.claude/settings.json）'],
    ['/memory', '记忆文件（直接编辑 CLAUDE.md / 项目 memory）'],
    ['/add-dir', '追加工作目录（本工具按会话指定 cwd，无需追加）'],
    ['/context', '上下文明细（/status 已展示用量环）'],
    ['/cost', '费用统计（v2.3 起不显示金额，用量见 /status）'],
    ['/agents', '子代理面板（对话流里可看子代理过程抽屉）'],
    ['/plugins', '插件管理（直接改 ~/.claude 配置）'],
    ['/rewind', '回退检查点（交互 TUI 专属）'],
    ['/todos', '任务列表（模型回复中会展示任务进度）'],
    ['/export', '导出对话（暂不支持，可在 ~/.claude/projects 找转写）'],
  ];
  function renderSysCard(title, rows) {
    const d = document.createElement('div');
    d.className = 'h-syscard';
    d.innerHTML = '<div class="h-syscard-t">' + esc(title) + '</div>' +
      rows.map(r => '<div class="h-syscard-r"><b>' + esc(r[0]) + '</b><span>' + esc(r[1]) + '</span></div>').join('');
    addRow(d);
    scrollBottom();
  }
  // v2.21：从模型菜单点击分支抽出——/model 名 复用同一条切换路径
  function applyModel(m) {
    // v2.27.10：乐观更新失败必须回滚芯片——切模型被拒（回复中 409）时
    // 芯片已显示新模型而会话实际还是旧模型（用户实锤：以为切到多模态
    // flash，实际一直跑非多模态 glm-5.3，发图全变 CDN 链接还以为坏了）
    const prev = _HG.model;
    const chip = q('[data-hg-model]');
    const setChip = (mm) => { chip.innerHTML = '🧠 ' + esc(mm || '默认') + ' ▾'; };
    _HG.model = m;
    setChip(m);
    if (_HG.sid) {
      fetch('/api/harness/set_model', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid, model: m})})
        .then(r => r.json())
        .then(j => {
          if (!j.ok) {
            _HG.model = prev; setChip(prev);   // 回滚：芯片如实反映会话模型
            showBanner((j.err || '切换模型失败') + '（仍用 ' + (prev || '默认') + '）', 3500, true);
          }
        })
        .catch(() => { _HG.model = prev; setChip(prev); showBanner('切换模型失败', 3000, true); });
      refreshSessions();
    } else showBanner('模型 ' + m + ' 将用于新会话', 2200);
  }
  async function execSlash(raw) {
    const m = raw.match(/^\/([a-z0-9_-]+)(?:\s+([\s\S]*))?$/i);
    if (!m) return false;
    const cmd = m[1].toLowerCase(), arg = (m[2] || '').trim();
    if (!HG_SLASH.some(x => x[0] === '/' + cmd) && !HG_SLASH_DEAD.some(x => x[0] === '/' + cmd)) return false;
    // v2.25：CLI 纯交互命令——本地拦下说明去向，不进对话
    const dead = HG_SLASH_DEAD.find(x => x[0] === '/' + cmd);
    if (dead && cmd !== 'help') {
      renderSysCard('CLI 交互命令（headless 不可用）', [[dead[0], dead[1]]]);
      return true;
    }
    if (cmd === 'help') {
      renderSysCard('内建命令（本地执行，不进入对话）', HG_SLASH);
      renderSysCard('CLI 交互命令（headless 不可用，已本地拦截）', HG_SLASH_DEAD);
    } else if (cmd === 'mcp') {
      // v2.25：headless 没有 CLI 的 MCP 面板——后端代跑 claude mcp list，
      // 原文按行渲染（server 名拆到左列，其余含连接状态在右列）
      (async () => {
        let j = null;
        try { j = await (await fetch('/api/harness/mcp_list')).json(); } catch(_) {}
        if (!j || !j.ok) {
          renderSysCard('MCP 服务器', [['查询失败', (j && j.err) || '网络错误']]);
          return;
        }
        const rows = String(j.output || '').split(/\r?\n/).filter(s => s.trim()).map(s => {
          const i = s.indexOf(':');
          return (i > 0 && i < 40) ? [s.slice(0, i).trim(), s.slice(i + 1).trim()] : ['', s.trim()];
        });
        renderSysCard('MCP 服务器（claude mcp list 实时状态）', rows.length ? rows : [['（空）', '没有配置任何 MCP 服务器']]);
      })();
    } else if (cmd === 'resume') {
      const side = wrap.querySelector('.hg-side');
      if (side) { side.classList.remove('flash'); void side.offsetWidth; side.classList.add('flash'); }
      searchEl.focus();
      showBanner('点击左侧会话即可切换', 2200);
    } else if (cmd === 'clear') {
      newChat();
      showBanner('已新建会话', 2000);
    } else if (cmd === 'model') {
      if (!arg) { q('[data-hg-model]').click(); return true; }
      await fetchModels();      // v2.25：每次重新拉（配置方案切换后模型映射变了）
      const kw = arg.toLowerCase();
      const hits = (_HG.models.models || []).filter(x => x.toLowerCase().includes(kw));
      if (hits.length === 1) { applyModel(hits[0]); showBanner('已切换模型 · ' + hits[0], 2400); }
      else if (!hits.length) showBanner('没有匹配「' + arg + '」的模型', 3000, true);
      else showBanner('匹配到多个：' + hits.join(' / '), 3400, true);
    } else if (cmd === 'status') {
      let ctx = null;
      if (_HG.sid) {
        try { ctx = await (await fetch('/api/harness/ctx?sid=' + encodeURIComponent(_HG.sid))).json(); } catch(_) {}
      }
      const rows = [
        ['会话', _HG.sid ? _HG.sid.slice(0, 8) + '…' : '未创建'],
        ['模型', _HG.model || (_HG.models && _HG.models.default) || '默认'],
        ['项目', _HG.cwd || '未选择'],
        ['进程', _HG.alive ? (_HG.busy ? '运行中 · 正在生成回复' : '空闲待命') : '未运行（发送消息自动恢复）'],
        ['权限', _HG_PERMS[_HG.perm] || '自动执行'],
        ['思考', _HG.thinkLv ? (_HG_THINKS[_HG.thinkLv] || _HG.thinkLv) : '默认'],
      ];
      if (ctx && ctx.ok && ctx.window) {
        const pct = ctx.used ? Math.round(ctx.used / ctx.window * 100) + '%' : '—';
        const u = ctx.used ? (ctx.used / 1000).toFixed(1) + 'K / ' + (ctx.window / 1000).toFixed(0) + 'K (' + pct + ')' : '';
        rows.push(['上下文', ctx.compacted ? (u ? u + ' · ' : '') + '压缩后待首轮回复' : (u || '首轮回复后统计')]);
      }
      renderSysCard('会话状态', rows);
    } else if (cmd === 'compact') {
      // v2.28.4：实测 CLI 2.1.267 headless（stream-json stdin）下，用户消息
      // 里的斜杠命令会被真实执行——发 /compact 触发 compacting 状态事件
      // →压缩→重新 init（事件流 v2.20 已有分割线渲染）。走正常发送管线，
      // 压缩过程与耗时照常显示；arg 作为保留要点附给 CLI。
      // v2.28.10：后端超窗守卫已放行 /compact（拒发锁死出口的实锤修复）。
      await dispatch('/compact' + (arg ? ' ' + arg : ''), null, null, false);
    } else if (cmd === 'rewind') {
      // v2.28.11：会话回退——截断转写到最后第 N 个完整回合（备份保全量），
      // 杀进程，下次发消息 --resume 续上回退后的上下文。爆死态（/compact
      // 都压不动）与「上一轮搞砸了」的统一逃生门。
      if (!_HG.sid) { showBanner('当前没有活动会话', 2200); return true; }
      const n = Math.max(1, Math.min(50, parseInt(arg, 10) || 1));
      try {
        const r = await fetch('/api/harness/rewind', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({sid: _HG.sid, turns: n})});
        const j = await r.json();
        showBanner(j.ok ? ('⏪ ' + j.msg + '——发送消息即续上')
                        : ('回退失败：' + (j.err || '未知')), 4600, !j.ok);
      } catch(e) { showBanner('回退失败：' + e, 3000, true); }
    } else if (cmd === 'roles') {
      // v2.29.2：三角色设计说明——含按当前 API 方案解析出的实际模型。
      // v2.30.2 双形态：主会话轻快模型 → 轻主力模式（designer 代理），
      // 强模型 → 决策者模式（executor/coder + 结构禁权）
      (async () => {
        let j = null;
        try { j = await (await fetch('/api/harness/roles')).json(); } catch(_) {}
        const r = (j && j.roles) || {};
        const rs = (j && j.resolved) || {};
        const light = j && j.mode === 'light';
        const modeRows = light ? [
          ['当前形态', '轻主力（主会话是轻快模型）——日常对话/跑腿杂活自己干，攻坚走 dev+reviewer 两个强模型'],
          ['开发', `dev 代理（${rs.coder || '按当前方案自动识别'}）——编码/debug/方案思考一个上下文打通（designer 已并入），自测通过再交`],
          ['审核', `reviewer 代理（${rs.coder || '按当前方案自动识别'}）——对抗审核：假定代码有错，专门挑毛病（需求符合性/逻辑/健壮性/安全/一致性），只审不改，PASS/FAIL 二选一`],
          ['标准流程', 'dev 实现 → reviewer 对抗审核 → FAIL 回 dev 修 → 复审，致命/严重问题清零才收 → 主会话汇总答复'],
        ] : [
          ['当前形态', '决策者（主会话是高级模型）——只承接/派发/审核/汇总，干活工具已结构性禁用'],
          ['执行者', `executor 代理（${rs.executor || '按当前方案自动识别'}）——信息收集/查日志/排查/跑命令/debug/杂活`],
          ['编程者', `coder 代理（${rs.coder || '按当前方案自动识别'}）——编码攻坚，改完自测再交`],
        ];
        renderSysCard('三角色设计（双形态）', [
          ...modeRows,
          ['状态', r.enabled === false ? '已关闭（config.json harness_roles.enabled）' : '已启用'],
          // v2.34：审计信息进 /roles 输出（用户定调：判定用客观事实，配置要看得见）
          ['审计模式', !r.enabled ? '—（三角色未启用）'
            : light ? (r.audit_mode === 'off' ? '关闭（audit_mode=off）'
              : r.audit_mode === 'warn' ? '仅警示（audit_mode=warn）——回合结束盘点工具调用，违规出红色警示不自动续发'
              : '自动补审（audit_mode=auto，默认）——回合结束盘点工具调用记录，直改超线/跳过 reviewer 自动续发要求补审；连续 3 回合违规降级为仅警示')
            : '不适用（决策者形态结构禁权已保证，不审计）'],
          ['免审线', !r.enabled ? '—' : light
            ? `主会话直改单回合累计 ≤ ${Number.isFinite(parseInt(r.max_free_lines, 10)) ? Math.max(0, parseInt(r.max_free_lines, 10)) : 3} 行免审（max_free_lines，可配，0=任何直改都须派 dev）；超出或多文件改动须派 dev+reviewer`
            : '—（strong 形态无直改）'],
          ['推荐配置', '主模型配轻快模型（如 glm-5.3-flash/flashx）——对话与杂活省 token，攻坚/审核走强模型代理，即轻主力形态'],
          ['模型解析', '端点映射（harness_roles.model_map）→ 当前方案模型表自动识别（轻快模型→执行者档，dev/reviewer 取强模型档）→ 配置兜底；换 API 方案自动适配'],
          ['形态判定', '主会话模型名带轻快词（flash/turbo/light/mini/air…）= 轻主力形态，否则决策者形态；切模型下条消息自动换形态'],
        ]);
      })();
    } else if (cmd === 'exit') {
      if (!_HG.sid) { showBanner('当前没有活动会话', 2200); return true; }
      fetch('/api/harness/kill', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
      showBanner('进程退出中，发送消息自动恢复', 2600);
    }
    return true;
  }
  // 输入 / 前缀即弹 CLI 式命令菜单：内建命令 + 技能一起过滤，↑↓ 选择、
  // Enter/Tab 执行、Esc 关闭；继续打字收窄，出现空格/其他内容即关
  // ==================== 技能中文描述（v2.27「技能需要翻译」）====================
  // 菜单此前一直空白：后端 /skills 给的是 desc 字段，前端读的却是
  // s.description——字段名对不上，描述从没渲染出来过。这里顺带给常见
  // 英文技能配中文一句话说明（命中优先显示；未命中的显示原 desc，
  // 用户自装的中文技能天然中文）。
  const SKILL_ZH = {
    'data-analysis': '数据分析与可视化：查库、报表、表格自动化',
    'database-operations': '数据库设计/迁移/SQL优化/索引/N+1 治理',
    'doc-coauthoring': '结构化文档协作撰写（方案/规格/决策文档）',
    'find-skills': '发现并安装新技能',
    'hiklink-claw-cli': 'HikLink 企业通讯 CLI：发消息/云文档/日程/会议',
    'hiklink-cloud-doc-toolkit': '在线云文档（表格编辑器）单元格自动化 CLI',
    'hikvision-enc-query': '查海康产品加密配置（按物料代码）',
    'hikvision-spec-query': '查海康产品 SPEC 规格说明书/产品参数',
    'kernel-weekly': '抓 LWN 周刊生成中文内核周报档案',
    'log-analyzer': '日志解析/检索/错误模式/堆栈分析',
    'maas-kb-management': 'MaaS 知识库与文档一站式管理',
    'mermaid-diagram': '生成 Mermaid 图（流程/架构/时序/脑图）',
    'office': 'Excel/Word/PPT/Google 文档处理与自动化',
    'pdf-text-extractor': 'PDF 文本提取（支持 OCR）',
    'playwright-scraper-skill': 'Playwright 网页抓取（带反爬处理）',
    'self-improving-agent': '沉淀纠错与经验，持续自我改进',
    'software-platform-ops': '海康软件平台组件配置表/换包/构建打包',
    'sso-login': '自动化 SSO 登录，取可复用的会话 cookie',
    'stop-slop-zh': '去除中文 AI 腔，让文字更自然',
    'windows-ui-automation': 'Windows GUI 自动化（鼠标/键盘/窗口）',
    'dataviz': '图表/仪表盘设计系统（配色/可访问性）',
    'claude-api': 'Claude API/SDK 参考（模型/定价/流式）',
    'planning-with-files': '文件式任务计划（task_plan/findings/progress）',
    'code-review': '审查当前 diff/PR 的正确性与可简化点',
    'simplify': '对当前改动做复用/简化/效率清理并应用',
    'security-review': '对当前分支改动做安全审查',
    'init': '生成 CLAUDE.md 项目说明文件',
    'run': '启动项目应用并驱动验证改动',
    'loop': '按周期重复运行某个提示词/命令',
  };
  function _skillDesc(s) {
    // 键归一化：技能 name 可能是「Data Analysis」（大写+空格）而映射键是
    // data-analysis（小写连字符）——统一 lower+空格/下划线转连字符再查
    const n = (s.name || '').toLowerCase().replace(/[\s_]+/g, '-');
    const d = s.desc || s.description || '';
    return SKILL_ZH[n] || (_HG.skillZh || {})[n] || (_HG.skillZh || {})[d] || d;
  }
  // v2.27「技能需要翻译」长期方案：静态映射兜底常见技能；新装技能的英文
  // desc 由后端调 settings.json 配的模型翻译，落 ~/.serialconsole_pro/
  // skill_zh_cache.json 持久缓存——零人工维护，缓存命中后零延迟。
  function _skillZhSync() {
    const norm = (n) => (n || '').toLowerCase().replace(/[\s_]+/g, '-');
    const need = (_HG.skills || []).filter(s => {
      const d = (s.desc || '').trim();
      return d && !/[一-鿿]/.test(d) && !SKILL_ZH[norm(s.name)];
    });
    if (!need.length) return;
    fetch('/api/harness/skill_zh/translate', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({items: need.map(s => ({name: s.name, desc: s.desc}))})})
      .then(r => r.json()).then(j => {
        if (!j.ok || !j.map) return;
        _HG.skillZh = Object.assign({}, _HG.skillZh, j.map);
        // 菜单若开着：热替换各项描述，不用关了重开（v2.27.1 修：openPop
        // 此前不带 kind 类，.hg-pop.skill 永远查不到，热替换从未生效）
        const pop = wrap.querySelector('.hg-pop.skill');
        if (pop) pop.querySelectorAll('[data-skill]').forEach(el => {
          const s = (_HG.skills || []).find(x => x.name === el.dataset.skill);
          if (!s) return;
          const span = el.querySelector('span');
          if (span) span.textContent = _skillDesc(s).slice(0, 60);
        });
        if (_HG.pop === 'slash') slashMenuUpdate();
      }).catch(() => {});
  }
  function slashMenuUpdate() {
    const mm = input.value.match(/^\/([a-z0-9_-]*)$/i);
    if (!mm) { if (_HG.pop === 'slash') closePop(); return; }
    const kw = mm[1].toLowerCase();
    const built = HG_SLASH.filter(x => x[0].slice(1).startsWith(kw))
      .map(x => ({ slash: x[0].slice(1), desc: x[1] }));
    const sk = (_HG.skills || []).filter(s => (s.name || '').toLowerCase().startsWith(kw))
      .map(s => ({ skill: s.name, desc: _skillDesc(s).slice(0, 70) }));
    const list = built.concat(sk);
    if (!list.length) { if (_HG.pop === 'slash') closePop(); return; }
    _HG.slashList = list; _HG.slashSel = 0;
    const html = '<div class="hg-pop-list">' + list.map((x, i) =>
      `<div class="hg-pop-item${i === 0 ? ' on' : ''}" data-i="${i}"><b>/${esc(x.slash || x.skill)}</b><span>${esc(x.desc || '')}</span></div>`).join('') +
      '</div><div class="hg-pop-foot">ⓘ 输入内容以搜索命令、技能</div>';
    const p = openPop('slash', input, html);
    // openPop 的 left/bottom 按 card-wrap 坐标系算，而挂载点 .hg-input-stack
    // 自身是定位元素——照搬会错位（菜单飘进消息区）。这里按 stack 原位
    // 重定位：与 textarea 同宽、贴其上缘 6px（参考 CLI 的命令面板位置）
    if (p) {
      p.style.left = '0';
      p.style.right = '0';
      p.style.width = 'auto';
      p.style.bottom = 'calc(100% + 6px)';
    }
    // 技能懒加载：首次敲 / 后台拉一次，到了重弹把技能补进菜单
    if (!_HG.skills) {
      _HG.skills = [];
      fetch('/api/harness/skills').then(r => r.json()).then(j => {
        _HG.skills = (j.ok && j.skills) || [];
        _HG.skillZh = (j.ok && j.zh) || {};
        _skillZhSync();
        if (_HG.pop === 'slash') slashMenuUpdate();
      }).catch(() => {});
    }
  }
  function slashHighlight() {
    const p = wrap.querySelector('.hg-pop.slash');
    if (!p) return;
    const items = p.querySelectorAll('.hg-pop-item');
    items.forEach((el, i) => el.classList.toggle('on', i === _HG.slashSel));
    const cur = items[_HG.slashSel];
    if (cur) cur.scrollIntoView({ block: 'nearest' });
  }
  function handleSlashKey(e) {
    if (_HG.pop !== 'slash') return false;
    const list = _HG.slashList || [];
    if (!list.length) return false;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = list.length;
      _HG.slashSel = e.key === 'ArrowDown' ? (_HG.slashSel + 1) % n : (_HG.slashSel - 1 + n) % n;
      slashHighlight();
      return true;
    }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) {
      e.preventDefault();
      slashPick(list[_HG.slashSel >= 0 ? _HG.slashSel : 0]);
      return true;
    }
    if (e.key === 'Escape') { e.preventDefault(); closePop(); return true; }
    return false;
  }
  function slashPick(x) {
    if (!x) return;
    closePop();
    input.value = ''; input.style.height = 'auto'; renderOverlay('');
    if (x.slash) {
      if (x.slash === 'model') q('[data-hg-model]').click();
      else execSlash('/' + x.slash);
    } else {
      input.value = '/' + x.skill + ' ';           // 技能：插入待补参（同⚡按钮行为）
      renderOverlay(input.value);
      input.focus();
    }
  }

  async function send() {
    const text = input.value.trim();
    if (!text && !_HG.atts.length) return;
    // v2.21：内建斜杠命令本地执行（附件与命令互斥，命令不需要附件）
    if (!_HG.atts.length && text.startsWith('/')) {
      const c0 = text.split(/\s/, 1)[0].toLowerCase();
      // v2.25：DEAD 表命中也本地执行（拦下 CLI 交互命令，不发后端白耗一轮）
      if (HG_SLASH.some(x => x[0] === c0) || HG_SLASH_DEAD.some(x => x[0] === c0)) {
        input.value = ''; input.style.height = 'auto'; renderOverlay('');
        execSlash(text);
        return;
      }
    }
    const images = _HG.atts.filter(a => a.isImg).map(a => a.path);
    const files = _HG.atts.filter(a => !a.isImg).map(a => a.path);
    // v2.20：回复执行中不再拦「正在回复中」——排进队列（ZCode 式），
    // 结束后自动发送；排队条上可 ↑立即 / ✎编辑 / 🗑丢弃
    if (_HG.busy) {
      queuePush({ text, images, files });
      input.value = ''; input.style.height = 'auto'; renderOverlay('');
      clearAtts();
      if (_HG.sid) delete _HG.attsBy[_HG.sid];   // 已随消息带走，暂存别再还回来
      return;
    }
    input.value = ''; input.style.height = 'auto'; renderOverlay('');
    clearAtts();
    if (_HG.sid) delete _HG.attsBy[_HG.sid];
    dispatch(text, images, files, true);
  }

  async function stopGen() {
    if (!_HG.sid) return;
    const sid = _HG.sid;
    // v2.15：停止必须自带兜底。复位的唯一来源是后端回一条 `interrupted`
    // 事件，而后端 interrupt() 在「自身 busy 已是 false」时直接返回错误、
    // 不发任何事件（进程刚退出、事件丢失、会话查无此 sid 都会走到这条）。
    // 旧实现不看响应也不兜底 → 前端永远停在生成态，输入框被 busy 拦住，
    // 点 ■ 再走一遍同样的路径，形成死循环。
    let gotEvent = false;
    const onInt = (e) => { if (e.detail === sid) gotEvent = true; };
    try {
      document.addEventListener('hg-interrupted', onInt);
      const r = await fetch('/api/harness/interrupt', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid})});
      const j = await r.json().catch(() => null);
      if (!j || !j.ok) {
        // 后端明确拒绝（没有进行中的回复）→ 前端本就该收工
        if (_HG.sid === sid) setBusy(false);
        if (j && j.err) showBanner(j.err, 2500);
        return;
      }
      // 后端已受理：等 interrupted 事件；超时没等到就自行收尾
      await new Promise(res => setTimeout(res, 1500));
      if (!gotEvent && _HG.sid === sid) setBusy(false);
    } catch(_) {
      if (_HG.sid === sid) setBusy(false);
    } finally {
      document.removeEventListener('hg-interrupted', onInt);
    }
  }

  sendBtn.onclick = () => { _HG.busy ? stopGen() : send(); };

  // ---- 键盘链（源 useChatComposerState：命令菜单 → mention → 历史 → Enter）----
  input.addEventListener('keydown', (e) => {
    if (handleMentionKey(e)) return;                    // @ 下拉优先
    if (handleSlashKey(e)) return;                      // / 命令菜单次之（v2.21）
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault(); send(); return;
    }
    if (handleHistoryKey(e)) return;                     // ↑↓ 历史
    if (e.key === 'Escape' && _HG.busy) { e.preventDefault(); stopGen(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
    renderOverlay(input.value);
    updateMention();
    slashMenuUpdate();          // v2.21：/ 前缀弹内建命令+技能菜单
  });

  // ---- 输入历史（源 useInputHistory：空框 ↑ 回溯、到底恢复 draft）----
  function handleHistoryKey(e) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return false;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return false;
    const value = input.value;
    const nav = _HG.histNav;
    const untouched = nav && value === nav.recalled;
    if (e.key === 'ArrowUp') {
      if (value !== '' && !untouched) return false;
      const history = untouched ? nav.history : _hgHistRead(_HG.sid || 'draft');
      if (!history.length) return false;
      e.preventDefault();
      if (untouched && nav.index === 0) return true;
      const idx = untouched ? nav.index - 1 : history.length - 1;
      const draft = untouched ? nav.draft : value;
      _HG.histNav = { history, index: idx, draft, recalled: history[idx] };
      input.value = history[idx];
      input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 200) + 'px';
      renderOverlay(input.value);
      requestAnimationFrame(() => input.setSelectionRange(input.value.length, input.value.length));
      return true;
    }
    if (!untouched) return false;
    e.preventDefault();
    if (nav.index >= nav.history.length - 1) {
      input.value = nav.draft; _HG.histNav = null;
      renderOverlay(input.value);
    } else {
      _HG.histNav = { history: nav.history, index: nav.index + 1, draft: nav.draft, recalled: nav.history[nav.index + 1] };
      input.value = _HG.histNav.recalled;
      renderOverlay(input.value);
    }
    return true;
  }

  // ---- @ 文件引用（源 useFileMentions：触发/下拉/键盘/插入/高亮）----
  const _HG_MENTION_FILES = [];   // 已引用路径（overlay 高亮用）
  // v2.15：跨会话要清空。它是闭包常量，switchTo/newChat/_harnessClose 都够不到，
  // 旧实现下在会话 A 用 @ 引用过文件后切到 cwd 完全不同的会话 B，overlay 的
  // 路径高亮仍按 A 的路径匹配（串味）。所有切会话/新建入口统一调它。
  function _hgMentionReset() { _HG_MENTION_FILES.length = 0; }
  function closeMention() {
    mentionEl.style.display = 'none';
    _HG.mention = null;
  }
  function updateMention() {
    const pos = input.selectionStart;
    const before = input.value.slice(0, pos);
    const at = before.lastIndexOf('@');
    if (at === -1) { closeMention(); return; }
    const query = before.slice(at + 1);
    if (query.includes(' ')) { closeMention(); return; }
    _HG.mention = { at, query, sel: -1, files: null };
    const cwd = (conn.meta.cwd) || '';
    fetch(`/api/harness/files?cwd=${encodeURIComponent(cwd)}&q=${encodeURIComponent(query)}`)
      .then(r => r.json())
      .then(j => {
        if (!_HG.mention || _HG.mention.at !== at) return;   // 闭包校验防过期响应
        _HG.mention.files = (j.ok && j.files) || [];
        renderMention();
      }).catch(() => {});
    renderMention(true);   // 立即显示 loading
  }
  function renderMention(loading) {
    const m = _HG.mention;
    if (!m) { closeMention(); return; }
    const files = m.files || [];
    if (!files.length && !loading) { closeMention(); return; }
    mentionEl.style.display = 'block';
    mentionEl.innerHTML = loading && !files.length ? '<div class="hg-pop-empty">搜索文件…</div>'
      : files.map((f, i) => `<div class="hg-mention-item${i === m.sel ? ' sel' : ''}" data-mi="${i}"><b>${esc(f.name)}</b><span>${esc(f.path)}</span></div>`).join('')
        || '<div class="hg-pop-empty">无匹配文件</div>';
  }
  mentionEl.addEventListener('mousedown', (e) => {
    const it = e.target.closest('.hg-mention-item');
    if (it && _HG.mention) { e.preventDefault(); selectMention(_HG.mention.files[+it.dataset.mi]); }
  });
  function handleMentionKey(e) {
    const m = _HG.mention;
    if (!m || !m.files || !m.files.length) return false;
    if (e.key === 'ArrowDown') { e.preventDefault(); m.sel = m.sel < m.files.length - 1 ? m.sel + 1 : 0; renderMention(); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); m.sel = m.sel > 0 ? m.sel - 1 : m.files.length - 1; renderMention(); return true; }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) {
      e.preventDefault();
      selectMention(m.files[m.sel >= 0 ? m.sel : 0]);
      return true;
    }
    if (e.key === 'Escape') { e.preventDefault(); closeMention(); return true; }
    return false;
  }
  function selectMention(f) {
    if (!f) return;
    const m = _HG.mention;
    const before = input.value.slice(0, m.at);
    const rest = input.value.slice(m.at);
    const sp = rest.indexOf(' ');
    const after = sp !== -1 ? rest.slice(sp) : '';
    input.value = `${before}${f.path} ${after}`;
    const caret = before.length + f.path.length + 1;
    if (!_HG_MENTION_FILES.includes(f.path)) _HG_MENTION_FILES.push(f.path);
    closeMention();
    input.focus();
    requestAnimationFrame(() => input.setSelectionRange(caret, caret));
    renderOverlay(input.value);
  }
  // 高亮 overlay：与 textarea 同字体同 padding 的镜像层，只画 @ 引用路径的
  // 底色高亮，文字本身透明；textarea 文字正常显示叠在其上（源 renderInputWithMentions，
  // 原版是透明文字+镜像层，这里反过来更稳——镜像层透明文字+真文字在上）。
  function renderOverlay(text) {
    if (!text || !_HG_MENTION_FILES.length) { overlayEl.innerHTML = ''; return; }
    const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const sorted = [..._HG_MENTION_FILES].sort((a, b) => b.length - a.length);
    const re = new RegExp(`(${sorted.map(escRe).join('|')})`, 'g');
    overlayEl.innerHTML = text.split(re).map(p =>
      sorted.includes(p) ? `<span class="hg-mention-hl">${esc(p)}</span>` : esc(p)
    ).join('');
  }
  input.addEventListener('scroll', () => { overlayEl.scrollTop = input.scrollTop; overlayEl.scrollLeft = input.scrollLeft; });

  // ==================== 附件 ====================
  // v2.19：缩略图原来直接拿本地绝对路径当 <img src>（http 页面加载不了盘符路径）
  // → 破图占位符，且破图时浏览器把文件名当 alt 渲染出来，紧跟着又拼了一遍
  // a.name，于是显示成「🖼 2.png 2.png」。改走 /api/harness/file 只读路由；
  // alt 留空、onerror 直接隐藏图片（宁可只剩文件名，也不出破图框）。
  function _attUrl(a) {
    return '/api/harness/file?name=' + encodeURIComponent(String(a.path).split(/[\\/]/).pop());
  }
  function renderAtts() {
    if (!_HG.atts.length) { attsEl.style.display = 'none'; attsEl.innerHTML = ''; return; }
    attsEl.style.display = 'flex';
    attsEl.innerHTML = _HG.atts.map((a, i) => {
      const url = a.isImg ? _attUrl(a) : '';
      return `<span class="hg-att-chip">` + (a.isImg
        ? `<img class="hg-att-thumb" src="${esc(url)}" alt="" title="${esc(a.name)}" data-img="${esc(url)}" onerror="this.style.display='none'">`
        : `<span class="hg-att-ico">📄</span>`) +
        `<span class="hg-att-name" title="${esc(a.name)}">${esc(a.name)}</span>` +
        `<button class="hg-att-x" data-i="${i}" title="移除">✕</button></span>`;
    }).join('');
    attsEl.querySelectorAll('[data-img]').forEach(t => t.onclick = () => openLightbox(t.dataset.img));
  }
  function clearAtts() { _HG.atts = []; renderAtts(); }
  attsEl.addEventListener('click', (e) => {
    const x = e.target.closest('.hg-att-x');
    if (x) { _HG.atts.splice(+x.dataset.i, 1); renderAtts(); }
  });
  q('[data-hg-att]').onclick = () => fileEl.click();
  // v2.3.12 内置截图：公共入口 window.harnessSnipStart 已升级为工具级模块
  // web/js/snip.js（用户定调：截图不局限 Claude——确认后复制剪贴板必有，
  // Claude 对话在场才顺带挂附件）。📷 按钮走等比适配路径（不切窗口）。
  q('[data-hg-snip]').onclick = () => window.harnessSnipStart && window.harnessSnipStart(false);
  async function uploadFiles(list) {
    for (const f of list) {
      if (f.size > 20 * 1024 * 1024) { showBanner(`「${f.name}」超过 20MB，跳过`, 3000, true); continue; }
      try {
        const b64 = await new Promise((res, rej) => {
          const fr = new FileReader();
          fr.onload = () => res(String(fr.result).split(',')[1] || '');
          fr.onerror = rej;
          fr.readAsDataURL(f);
        });
        const j = await (await fetch('/api/harness/upload', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({name: f.name, data_b64: b64})})).json();
        if (!j.ok) { showBanner(`上传「${f.name}」失败：${j.err}`, 3000, true); continue; }
        _HG.atts.push({name: j.name, path: j.path, size: j.size, isImg: _HARNESS_IMG_EXT.test(j.name)});
        renderAtts();
      } catch(e) { showBanner(`上传「${f.name}」失败：${e}`, 3000, true); }
    }
  }
  fileEl.addEventListener('change', () => { uploadFiles([...fileEl.files]); fileEl.value = ''; });
  input.addEventListener('paste', (e) => {
    const fs = [...(e.clipboardData?.files || [])].filter(f => f && f.size);
    if (fs.length) { e.preventDefault(); uploadFiles(fs); }
  });
  // v2.2.1：按磁盘路径直接加附件（拖拽进对话 tab 的文件走这——文件已在盘上，
  // 无需上传复制，Claude 直接 Read 原路径）。图片限 20MB（防撑爆上下文），
  // 其他类型不限（大日志让 Claude 自己 Read 更合理）。
  window.harnessAddFilesByPath = async (paths) => {
    let added = 0;
    for (const p of (paths || [])) {
      const name = String(p).split(/[\\/]/).pop() || 'file';
      const isImg = _HARNESS_IMG_EXT.test(name);
      if (isImg) {
        try {
          const j = await (await fetch('/api/file_info', {method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: p})})).json();
          if (j.ok && j.size > 20 * 1024 * 1024) {
            showBanner(`「${name}」超过 20MB，跳过`, 3000, true); continue;
          }
        } catch(_) {}
      }
      _HG.atts.push({name, path: p, size: 0, isImg});
      added++;
    }
    if (added) {
      renderAtts();
      showBanner(added === 1 ? '已加为对话附件（发送时随消息带上）' : `已加 ${added} 个附件`, 2500);
      input.focus();
    }
  };

  // ==================== popover（技能/模型）====================
  function closePop() {
    if (_HG.pop) { const p = wrap.querySelector('.hg-pop'); if (p) p.remove(); _HG.pop = null; }
  }
  function openPop(kind, anchor, html) {
    closePop();
    _HG.pop = kind;
    const p = document.createElement('div');
    // v2.27.1：kind 落到 class（.hg-pop.slash 等样式选择器一直依赖它，
    // 此前漏加导致斜杠菜单紧凑样式从未生效、技能热替换也查不到 .hg-pop.skill）
    p.className = 'hg-pop ' + kind;
    p.innerHTML = html;
    anchor.parentElement.appendChild(p);
    const ar = anchor.getBoundingClientRect(), wr = wrap.querySelector('.hg-card-wrap').getBoundingClientRect();
    p.style.left = Math.max(6, Math.min(ar.left - wr.left, wr.width - p.offsetWidth - 6)) + 'px';
    // v2.20：菜单底部贴 anchor 上缘悬浮。原来 CSS 写死 bottom:calc(100% - 2px)
    // 相对整个 card-wrap——菜单弹到输入区整体的上方（改版后那里直接是聊天流），
    // 用户反馈「不是悬浮贴着显示，跑上面显示了」。改内联按 anchor 实际位置算。
    p.style.bottom = (wr.bottom - ar.top + 6) + 'px';
    return p;
  }
  q('[data-hg-skill]').onclick = async (e) => {
    if (_HG.pop === 'skill') { closePop(); return; }
    const anchor = e.currentTarget;
    if (!_HG.skills) {
      try {
        const j = await (await fetch('/api/harness/skills')).json();
        _HG.skills = (j.ok && j.skills) || [];
        _HG.skillZh = (j.ok && j.zh) || {};
      } catch(_) { _HG.skills = []; }
    }
    _skillZhSync();
    const items = _HG.skills.length
      ? _HG.skills.map(s => `<div class="hg-pop-item" data-skill="${esc(s.name)}"><b>/${esc(s.name)}</b><span>${esc(_skillDesc(s).slice(0, 60))}</span></div>`).join('')
      : '<div class="hg-pop-empty">未发现技能（~/.claude/skills 或项目 .claude/skills）</div>';
    openPop('skill', anchor, `<div class="hg-pop-title">技能</div>${items}`);
  };
  // v2.25：每次打开都重拉——配置方案切换会改 settings.json 的模型映射，
  // 旧实现只在 tab 存续期拉一次，切方案后模型下拉仍显示旧网关的模型
  // （后端已按 settings.json mtime 失效缓存，这里配合即时拉新）。
  function fetchModels() {
    return fetch('/api/harness/models').then(r => r.json())
      .then(j => { if (j && j.ok) { _HG.models = j; renderList(); } return _HG.models; })
      .catch(() => _HG.models || {models: [], default: null});
  }
  q('[data-hg-model]').onclick = async (e) => {
    if (_HG.pop === 'model') { closePop(); return; }
    const anchor = e.currentTarget;
    await fetchModels();
    const cur = _HG.model || _HG.models.default;
    // v2.19：多模态模型打 👁——这类模型的会话自己读图
    // v2.28.1：两态——真多模态 👁 / 其余全部走 MCP 通道（无需标记）
    const mmSet = new Set(_HG.models.mm || []);
    const items = (_HG.models.models || []).map(m =>
      `<div class="hg-pop-item${m === cur ? ' on' : ''}" data-model="${esc(m)}"><b>${esc(m)}</b>${
        mmSet.has(m) ? `<span title="多模态：可直接读图">${_HG_EYE} 多模态</span>`
        : ''}${m === _HG.models.default ? '<span>默认</span>' : ''}</div>`).join('')
      || '<div class="hg-pop-empty">读取 settings.json 模型映射失败</div>';
    openPop('model', anchor, `<div class="hg-pop-title">模型（会话内切换即时生效，上下文保留）</div>${items}`);
  };
  wrap.addEventListener('click', async (e) => {
    // v2.21：命令菜单点选（内建命令直接执行，技能插入待补参）
    const sit = e.target.closest('.hg-pop.slash .hg-pop-item');
    if (sit) {
      e.stopPropagation();
      slashPick((_HG.slashList || [])[+sit.dataset.i]);
      return;
    }
    const si = e.target.closest('[data-skill]');
    if (si) {
      input.value = (input.value ? input.value.replace(/\s*$/, ' ') : '') + '/' + si.dataset.skill + ' ';
      renderOverlay(input.value);
      closePop(); input.focus(); return;
    }
    // v2.20：项目目录下拉（最近目录 + 浏览）
    const di = e.target.closest('[data-dir]');
    if (di) {
      const d = di.dataset.dir;
      closePop();
      if (d === '__browse__') {
        let dir = '';
        if (window.pywebview && pywebview.api && pywebview.api.pick_dir)
          dir = await pywebview.api.pick_dir() || '';
        if (dir) setProj(dir);
      } else if (d) setProj(d);
      return;
    }
    const pe = e.target.closest('[data-perm]');
    if (pe) {
      _HG.perm = pe.dataset.perm || 'auto';
      permChipLabel();
      if (!_HG.dirty) {
        if (_HG.sid) {
          fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
          switchTo(null);
        }
        showBanner('权限「' + _HG_PERMS[_HG.perm] + '」将用于当前新会话', 2400);
      } else showBanner('当前会话已有对话，权限将在新建会话生效', 2800);
      closePop(); return;
    }
    const tk = e.target.closest('[data-think]');
    if (tk) {
      _HG.thinkLv = tk.dataset.think || null;
      thinkChipLabel();
      if (!_HG.dirty) {
        if (_HG.sid) {
          fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
          switchTo(null);
        }
        showBanner('思考等级「' + (_HG.thinkLv ? _HG_THINKS[_HG.thinkLv] : '默认') + '」将用于当前新会话', 2400);
      } else showBanner('当前会话已有对话，思考等级将在新建会话生效', 2800);
      closePop(); return;
    }
    const mi = e.target.closest('[data-model]');
    if (mi) {
      // v2.20（强需求）：会话内直接换模型——后端 quiet 杀进程 + --resume
      // 同 session 重启，上下文连续，新模型下次回复即生效；SSE 回
      // model_switched 事件在消息流里渲染分割线。不再要求新建会话。
      // v2.21：逻辑抽到 applyModel，/model 名 命令复用同一条路
      applyModel(mi.dataset.model);
      closePop(); return;
    }
    // v2.20 修复：.hg-proj 也持有自己的 popover（原豁免只认 .hg-chip，
    // 点项目选择器 → onclick 刚 openPop → 冒泡到这里又 closePop，
    // 菜单闪一下就没了，表现为「项目下拉无效」）
    if (!e.target.closest('.hg-pop') && !e.target.closest('.hg-chip')
        && !e.target.closest('.hg-proj')) closePop();
  });
  if (_HG.model) q('[data-hg-model]').innerHTML = '🧠 ' + esc(_HG.model) + ' ▾';

  // ==================== 项目目录（v2.7；v2.20 改版）====
  // 参考 ZCode 布局：选择器挪到输入卡顶部（📁 目录名 ▾），下拉给最近
  // 目录 + 浏览。持久化 + 最近目录列表（localStorage）；切回历史会话时
  // cwd 同步过来——同项目连续开会话不必每轮重选。
  function _hgSaveCwd(dir) {
    try { dir ? localStorage.setItem('hg-last-cwd', dir)
             : localStorage.removeItem('hg-last-cwd'); } catch(_) {}
  }
  function _hgCwdHist() {
    try { return JSON.parse(localStorage.getItem('hg-cwd-hist') || '[]') || []; } catch(_) { return []; }
  }
  function _hgCwdPush(dir) {
    const h = _hgCwdHist().filter(x => x !== dir);
    h.unshift(dir);
    try { localStorage.setItem('hg-cwd-hist', JSON.stringify(h.slice(0, 6))); } catch(_) {}
  }
  try { _HG.cwd = localStorage.getItem('hg-last-cwd') || null; } catch(_) {}
  function projChipLabel() {
    const el = wrap.querySelector('[data-hg-projname]');
    if (el) el.textContent = _HG.cwd ? (_HG.cwd.split(/[\\/]/).pop() || _HG.cwd) : '选择项目';
  }
  function setProj(dir) {
    _HG.cwd = dir; _hgSaveCwd(dir); _hgCwdPush(dir); projChipLabel();
    if (!_HG.dirty) {
      if (_HG.sid) {
        fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
        switchTo(null);
      }
      showBanner('新会话将打开在 ' + dir, 2600);
    } else {
      showBanner('当前会话已有对话，新会话将打开在 ' + dir, 3200);
    }
  }
  q('[data-hg-proj]').onclick = (e) => {
    if (_HG.pop === 'proj') { closePop(); return; }
    const cur = _HG.cwd;
    const dirs = (cur ? [cur] : []).concat(_hgCwdHist().filter(d => d !== cur));
    const items = dirs.map(d =>
      `<div class="hg-pop-item${d === cur ? ' on' : ''}" data-dir="${esc(d)}"><b>${esc(d.split(/[\\/]/).pop() || d)}</b><span>${esc(d)}</span></div>`).join('')
      || '<div class="hg-pop-empty">还没有选择过项目目录</div>';
    openPop('proj', e.currentTarget,
      `<div class="hg-pop-title">项目目录（新会话打开在此）</div>${items}` +
      `<div class="hg-pop-item" data-dir="__browse__"><b>📂 浏览其他目录…</b></div>`);
  };
  projChipLabel();

  // ==================== 权限 / 思考等级（v2.20，参考 ZCode）====
  // 权限：auto=工具直接执行（现状）；confirm=写操作前用 ask_user 卡片确认。
  // 思考等级：→ 后端 MAX_THINKING_TOKENS。都是新会话参数（同模型 chip 语义）。
  const _HG_PERMS = {auto: '自动执行', confirm: '变更前确认'};
  const _HG_THINKS = {low: '低', medium: '中', high: '高', max: '最高'};
  const _HG_THINK_TOK = {low: '4K', medium: '10K', high: '20K', max: '32K'};
  function permChipLabel() {
    const b = q('[data-hg-perm]'); if (b) b.textContent = '🛡 ' + (_HG_PERMS[_HG.perm] || '自动执行') + ' ▾';
  }
  function thinkChipLabel() {
    const b = q('[data-hg-think]'); if (b) b.textContent = '💭 ' + (_HG.thinkLv ? '思考·' + _HG_THINKS[_HG.thinkLv] : '思考') + ' ▾';
  }
  q('[data-hg-perm]').onclick = (e) => {
    if (_HG.pop === 'perm') { closePop(); return; }
    const items = Object.keys(_HG_PERMS).map(k =>
      `<div class="hg-pop-item${k === _HG.perm ? ' on' : ''}" data-perm="${k}"><b>${_HG_PERMS[k]}</b><span>${k === 'auto' ? '工具直接执行' : '写文件/改状态前弹卡片确认'}</span></div>`).join('');
    openPop('perm', e.currentTarget, `<div class="hg-pop-title">权限（对新会话生效）</div>${items}`);
  };
  q('[data-hg-think]').onclick = (e) => {
    if (_HG.pop === 'think') { closePop(); return; }
    const items = `<div class="hg-pop-item${!_HG.thinkLv ? ' on' : ''}" data-think=""><b>默认</b><span>CLI 自主决定</span></div>` +
      Object.keys(_HG_THINKS).map(k =>
        `<div class="hg-pop-item${k === _HG.thinkLv ? ' on' : ''}" data-think="${k}"><b>${_HG_THINKS[k]}</b><span>${_HG_THINK_TOK[k]} tokens</span></div>`).join('');
    openPop('think', e.currentTarget, `<div class="hg-pop-title">思考等级（对新会话生效）</div>${items}`);
  };
  permChipLabel(); thinkChipLabel();

  // ==================== 识图状态指示（v2.28.2 简化）====================
  // 识图会话退役、MCP 接管后，识图过程直接显示在对话流里（📤 转交线+秒表 →
  // 📥 回传气泡），无需 3s 轮询/冒泡/状态机——按钮只静态反映开关态。
  const visIndEl = q('[data-hg-visind]');
  const visBtnEl = q('[data-hg-vision]');
  if (visIndEl) visIndEl.style.display = 'none';   // 顶栏指示器退役
  async function paintVisionBtn() {
    let j = null;
    try { j = await (await fetch('/api/harness/vision_status')).json(); } catch(_) {}
    if (!visBtnEl) return;
    visBtnEl.innerHTML = _HG_EYE + ' 识图配置 <span class="hg-vstat ' +
      (j && j.ok && j.enabled ? 'ok' : 'off') + '">· ' +
      ((j && j.ok && j.enabled) ? '已启用（MCP）' : '未启用') + '</span>';
  }
  paintVisionBtn();
  // 保存/开关变化后由面板流程刷新——简单起见每 30s 兜底刷一次
  setInterval(paintVisionBtn, 30000);

  // ==================== 三角色（v2.38 整合）====================
  // v2.38：「三角色」快捷开关按钮删除（与配置面板重复，用户实锤「这俩
  // 配置重复了」）——启用/停用统一走「三角色」配置面板里的开关（保存
  // POST /roles 全量含 enabled）。这里只做启动缓存预热：主气泡的角色
  // 徽章（决策者/轻主力）渲染要读 _hgRolesCache。
  _hgRolesFetch();

  // ==================== 识图配置（v2.28.2：MCP 后端）====================
  // 识图双通道（v2.28.5）：主通道=网关内置 mcp__4_5v_mcp__analyze_image
  // （服务端执行）；兜底=本地 mcp__vision__analyze_image（harness_vision_mcp，
  // 主通道失败后传本地路径）。此处配置的是兜底通道的模型/端点映射/提示词。
  // 这里配置 MCP 的识图模型/端点映射/提示词——多方案适配：不同 base_url
  // 方案可各配各的识图模型（lanz 配 Lanz 系、bigmodel 配 glm 系）。
  // 配置即行为：MCP 每次调用时读盘，改完即刻生效，无需重启会话。
  q('[data-hg-vision]').onclick = async () => {
    let j = null;
    try { j = await (await fetch('/api/harness/vision')).json(); } catch(_) {}
    if (!j || !j.ok) { showBanner('读取识图配置失败', 3000, true); return; }
    const saved = await hgVisionManager(j);
    if (saved === null) return;                 // 取消不动
    try {
      const r = await fetch('/api/harness/vision', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(saved)});
      const jr = await r.json();
      if (!jr.ok) { showBanner(jr.err || '保存失败', 3000, true); return; }
      showBanner(saved.enabled ? '识图配置已保存（MCP 通道，即刻生效）' : '识图已关闭', 3000);
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
  // 识图配置界面（v2.28.2）：开关 + MCP 识图模型 + 端点映射 + 提示词 +
  // 真多模态名单（可恢复默认）。返回对象=保存；null=取消。
  function hgVisionManager(init) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const cfg = { ...(init.vision || {}) };
      const def = init.defaults || {};
      const models = init.models || [];
      const curModel = cfg.model || '';
      const opts = ['<option value=""' + (curModel ? '' : ' selected') + '>默认（' + 'glm-5.3-flash）</option>']
        .concat(models.map(m => `<option value="${esc(m)}"${m === curModel ? ' selected' : ''}>${esc(m)}</option>`))
        .join('');
      const mapText = Object.entries(cfg.model_map || {})
        .map(([k, v]) => `${k}=${v}`).sort().join('\n');
      ov.innerHTML = `<div class="hg-modal hg-modal-vision"><div class="hg-modal-title">👁 识图配置</div>
        <div class="hg-modal-body hg-vision-hint">识图走 MCP 通道（analyze_image 工具，随会话常备，无后台进程）。此处配置 MCP 调用的识图模型与提示词，<b>保存即生效</b>。主会话模型是真多模态则直读，不经过这里。</div>
        <div class="hg-vision-row">
          <label class="hg-vision-switch"><input type="checkbox" data-hg-v-on${cfg.enabled ? ' checked' : ''}> 启用识图</label>
          <span class="hg-vision-state" style="font-size:11px;color:var(--muted);">MCP 通道 · 无后台进程</span>
        </div>
        <div class="hg-vision-grid">
          <label>识图模型（MCP 后端，需多模态；当前方案未命中下方映射时用此项）
            <select data-hg-v-model>${opts}</select></label>
        </div>
        <label class="hg-vision-prompt-lab">端点模型映射（每行一条：端点关键字=模型名——多方案适配，按当前 base_url 匹配，最长关键字命中优先）
          <textarea class="hg-vision-mm" data-hg-v-map spellcheck="false" style="height:56px;font-family:var(--font-mono);"
            placeholder="open.bigmodel.cn=glm-5.3-flash&#10;lanz.hikvision.com=Lanz-Medium-V">${esc(mapText)}</textarea></label>
        <label class="hg-vision-prompt-lab">多模态模型名单（逗号分隔，模型下拉的 👁 标记以此为准；名单外的模型一律走 MCP 识图通道）
          <input class="hg-vision-mm" data-hg-v-mm spellcheck="false"
                 value="${esc((cfg.mm_extra || []).join(', '))}"
                 placeholder="如：glm-5.3 flash, Lanz-Medium-V（前缀匹配，填一个即可覆盖其 [1M] 变体）"></label>
        <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
          <button class="btn ghost" data-hg-v-probe style="font-size:11px;">🔍 检测识图模型能否读图</button>
          <span data-hg-v-probe-out style="font-size:11px;color:var(--muted);"></span>
        </div>
        <label class="hg-vision-prompt-lab">识图提示词（作为识图请求的 system）
          <textarea class="hg-vision-prompt" data-hg-v-prompt spellcheck="false"></textarea></label>
        <div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };
      const ta = ov.querySelector('[data-hg-v-prompt]');
      const mapEl = ov.querySelector('[data-hg-v-map]');
      const modelEl = ov.querySelector('[data-hg-v-model]');
      const onEl = ov.querySelector('[data-hg-v-on]');
      const mmEl = ov.querySelector('[data-hg-v-mm]');
      ta.value = cfg.mcp_prompt || def.mcp_prompt || '';
      // v2.25：运行时探测——发张纯红测试图让该模型 Read，答对即多模态并
      // 自动并入名单（后端缓存，二次点秒回）。拿不准网关模型名是什么能力
      // 时点一下就行，不用猜也不用记。
      const probeBtn = ov.querySelector('[data-hg-v-probe]');
      const probeOut = ov.querySelector('[data-hg-v-probe-out]');
      probeBtn.onclick = async () => {
        const m = modelEl.value.trim() || init.default_model || '';
        if (!m) { probeOut.textContent = '请先在上方选择识图模型'; return; }
        probeBtn.disabled = true;
        probeOut.textContent = '探测中——直读测试（真多模态检测），约 5~60s…';
        try {
          const r = await fetch('/api/harness/mm_probe', {method:'POST',
            headers:{'Content-Type':'application/json'}, body: JSON.stringify({model: m})});
          const j = await r.json();
          if (j && j.ok) {
            // v2.28.1 两态：inline ✅ 真多模态 / mcp 🔧 走 MCP 通道（默认）
            const icon = j.mode === 'inline' ? '✅' : '🔧';
            probeOut.textContent = icon + ' ' + (j.msg || '') + (j.cached ? '（缓存）' : '');
            if (j.mode === 'inline') {
              const cur = (mmEl.value || '').split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean);
              if (!cur.some(x => m === x || m.startsWith(x) || x.startsWith(m)))
                mmEl.value = ((mmEl.value || '').replace(/\s+$/, '') ? mmEl.value.replace(/\s+$/, '') + ', ' : '') + m;
            }
          } else probeOut.textContent = '探测失败：' + ((j && j.err) || '未知');
        } catch(e) { probeOut.textContent = '探测失败：' + e; }
        probeBtn.disabled = false;
      };
      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('恢复默认提示词', false, () => { ta.value = def.mcp_prompt || ''; ta.focus(); });
      mkBtn('保存', true, () => close({
        enabled: onEl.checked,
        model: modelEl.value.trim(),
        mcp_prompt: ta.value.trim(),
        // v2.25：多模态手补名单随保存落盘（后端按前缀匹配，覆盖 [1M] 变体）
        mm_extra: (ov.querySelector('[data-hg-v-mm]').value || '')
          .split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean),
        // v2.28.3：端点模型映射——发 "端点关键字=模型名" 字符串行（后端按此
        // 解析；此前误发 [k,v] 元组数组，后端 str() 后无 '=' 被静默丢弃）
        model_map: (mapEl.value || '').split(/\n+/).map(s => s.trim())
          .filter(x => x.includes('=')),
      }));
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
      wrap.appendChild(ov);
      modelEl.focus();
    });
  }

  // ==================== 三角色配置（v2.34）====================
  // 整节配置入口（此前只能手改 config.json）：开关/模型槽/端点角色映射/
  // 审计模式/免审线。v2.38 起唯一入口（快捷开关按钮已删，开关在面板里）。
  // 保存走 POST /roles（merge 写盘）：模型槽/免审线在引导词里 →
  // 指纹热更下条消息换词重启 + agents 重生成；audit_mode 回合结算读盘即
  // 时生效。模式与识图面板同款（hgVisionManager）。
  // v2.37（P1-D）：配置面板打开主体抽函数——按钮与面板 C 区三角色行共用
  async function openRolesCfg() {
    let j = null;
    try { j = await (await fetch('/api/harness/roles')).json(); } catch(_) {}
    if (!j || !j.ok) { showBanner('读取三角色配置失败', 3000, true); return; }
    const saved = await hgRolesManager(j);
    if (saved === null) return;                 // 取消不动
    try {
      const r = await fetch('/api/harness/roles', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(saved)});
      const jr = await r.json();
      if (!jr.ok) { showBanner(jr.err || '保存失败', 3000, true); return; }
      showBanner('👥 三角色配置已保存——模型槽/免审线随下条消息热更生效（agents 自动重生成），审计模式立即生效', 4200);
      _hgRolesFetch();                          // 缓存刷新（气泡角色徽章同源）
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  }
  q('[data-hg-roles-cfg]').onclick = openRolesCfg;
  // 三角色配置界面（v2.34）：开关 + 形态展示（只读）+ 两模型槽 + 端点
  // 角色映射 + 审计模式/免审线。返回对象=保存；null=取消。
  function hgRolesManager(init) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const cfg = { ...(init.roles || {}) };
      const models = init.models || [];
      const light = init.mode === 'light';
      const dm = init.default_model || '';
      const mkOpts = (cur) => {
        const ms = models.slice();
        if (cur && !ms.includes(cur)) ms.push(cur);   // 配置值不在当前方案表也保留可选项
        return ['<option value=""' + (cur ? '' : ' selected') + '>默认（按当前方案自动识别）</option>']
          .concat(ms.map(m => `<option value="${esc(m)}"${m === cur ? ' selected' : ''}>${esc(m)}</option>`))
          .join('');
      };
      const mapText = Object.entries(cfg.model_map || {})
        .map(([k, v]) => `${k}=${v.executor},${v.coder}`).sort().join('\n');
      const am = cfg.audit_mode || 'auto';
      // 0 是合法免审线（任何直改都违规），不能用 || 兜底——那会把 0 变 3
      const mflDef = parseInt(cfg.max_free_lines, 10);
      const mflShow = Number.isFinite(mflDef) ? Math.max(0, mflDef) : 3;
      ov.innerHTML = `<div class="hg-modal hg-modal-vision"><div class="hg-modal-title">👥 三角色配置</div>
        <div class="hg-modal-body hg-vision-hint">三角色双形态按<b>主会话模型</b>自动二选一（名字带 flash/turbo/light 等轻快词=轻主力，否则=决策者）。保存后模型槽/免审线随下条消息热更生效（agents 自动重生成），审计模式立即生效。</div>
        <div class="hg-vision-row">
          <label class="hg-vision-switch"><input type="checkbox" data-hg-r-on${cfg.enabled ? ' checked' : ''}> 启用三角色</label>
          <span class="hg-vision-state" style="font-size:11px;">当前形态：<b>${light ? '轻主力' : '决策者'}</b>（主模型 ${esc(dm || '未设置')} → ${light ? 'dev + reviewer' : 'executor + coder，结构禁权'}）</span>
        </div>
        <div class="hg-vision-grid">
          <label>执行者模型（轻快槽：strong 形态 executor 用；light 形态主会话即执行者，不装 executor）
            <select data-hg-r-ex>${mkOpts(cfg.executor_model || '')}</select></label>
          <label>编程者模型（强模型槽：strong 形态 coder；light 形态 dev/reviewer 共用）
            <select data-hg-r-co>${mkOpts(cfg.coder_model || '')}</select></label>
        </div>
        <label class="hg-vision-prompt-lab">端点角色映射（每行：端点关键字=执行者模型,编程者模型——按当前 base_url 匹配，优先于自动识别；编程者可省略=与执行者同）
          <textarea class="hg-vision-mm" data-hg-r-map spellcheck="false" style="height:56px;font-family:var(--font-mono);"
            placeholder="open.bigmodel.cn=glm-5.3-flash,glm-5.3&#10;lanz.hikvision.com=Lanz-Flash,Lanz-Max">${esc(mapText)}</textarea></label>
        <div class="hg-vision-grid">
          <label>审计模式（仅 light 形态生效：回合结算盘点工具调用，直改超线/跳过 reviewer 的兜底）
            <select data-hg-r-am>
              <option value="auto"${am === 'auto' ? ' selected' : ''}>auto · 违规自动续发补审（默认）</option>
              <option value="warn"${am === 'warn' ? ' selected' : ''}>warn · 仅红色警示</option>
              <option value="off"${am === 'off' ? ' selected' : ''}>off · 关闭审计</option>
            </select></label>
          <label>直改免审线（行）：light 形态主会话单回合累计直改（Edit/Write）超此线且未派 reviewer 即违规${light ? '' : '（当前 strong 形态不审计）'}
            <input class="hg-vision-mm" type="number" min="0" max="100000" data-hg-r-mfl
                   value="${mflShow}"></label>
        </div>
        <div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };
      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('保存', true, () => close({
        enabled: ov.querySelector('[data-hg-r-on]').checked,
        executor_model: ov.querySelector('[data-hg-r-ex]').value.trim(),
        coder_model: ov.querySelector('[data-hg-r-co]').value.trim(),
        // 端点角色映射——发 "关键字=执行者,编程者" 行（后端按行解析，与识图
        // 面板 model_map 的行式体验一致）
        model_map: (ov.querySelector('[data-hg-r-map]').value || '')
          .split(/\n+/).map(s => s.trim()).filter(x => x.includes('=')),
        audit_mode: ov.querySelector('[data-hg-r-am]').value,
        // 0 合法（任何直改违规），parseInt 后 Number.isFinite 判非法回 3
        max_free_lines: (() => { const v = parseInt(
          ov.querySelector('[data-hg-r-mfl]').value, 10);
          return Number.isFinite(v) ? Math.max(0, v) : 3; })(),
      }));
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
      wrap.appendChild(ov);
      ov.querySelector('[data-hg-r-ex]').focus();
    });
  }

  // ==================== 自定义提示词（v2.8：多条目 + 全局/项目作用域）====
  // 每个会话进程启动时后端 --append-system-prompt 注入（新会话/复活同路径）：
  // 启用的全局条目对全部会话生效；项目条目只对 cwd 目录名匹配的会话生效。
  // 入口在左栏最底部（用户指定位置）；管理界面 = 条目列表 + 每条
  // v2.27：恢复会话——列表唯一来源是注册表 claude_harness.json，它一旦被
  // 清（写入撕裂/多开覆盖）会话就"看不见"了，但转写还在磁盘上。这里扫出
  // 注册表里没有的 jsonl 让用户手动找回（异常丢失/误删都能自救）。
  q('[data-hg-recover]').onclick = async () => {
    showBanner('正在扫描磁盘上的会话记录…', 2000);
    let items = [];
    try {
      const j = await (await fetch('/api/harness/recoverable')).json();
      if (!j.ok) { showBanner(j.err || '扫描失败', 3000, true); return; }
      items = j.items || [];
    } catch(e) { showBanner('扫描失败：' + e, 3000, true); return; }
    const ov = document.createElement('div');
    ov.className = 'hg-modal-ov';
    const fmtSize = (n) => n >= 1048576 ? (n/1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n/1024)) + ' KB';
    const shortCwd = (c) => String(c || '').replace(/\//g, '\\').split('\\').filter(Boolean).slice(-1)[0] || '未知项目';
    ov.innerHTML = `<div class="hg-modal hg-modal-recover"><div class="hg-modal-title">⟲ 恢复会话</div>
      <div class="hg-modal-body hg-recover-hint">以下是磁盘上有记录、但不在当前列表里的会话。恢复只是找回入口，不启动任何进程；点开会话发消息即自动续上原上下文。</div>
      <div class="hg-recover-list"></div>
      <div class="hg-modal-acts"><button class="btn ghost" data-hg-r-close>关闭</button></div></div>`;
    const listEl = ov.querySelector('.hg-recover-list');
    const close = () => ov.remove();
    ov.querySelector('[data-hg-r-close]').onclick = close;
    function render() {
      if (!items.length) {
        listEl.innerHTML = '<div class="hg-list-empty">没有可恢复的会话——列表里的会话和磁盘记录是对得上的</div>';
        return;
      }
      listEl.innerHTML = items.map((it, i) => it._done
        ? `<div class="hg-r-item done"><span class="hg-r-title">✓ ${esc(it.title)}</span><span class="hg-r-meta">已恢复到列表</span></div>`
        : `<div class="hg-r-item">
             <div class="hg-r-info">
               <div class="hg-r-title" title="${esc(it.title)}">${esc(it.title)}</div>
               <div class="hg-r-meta">${_harnessRelTime(it.last_active)} · 你的消息×${it.human || 0}${it.human_more ? '+' : ''} · ${fmtSize(it.size)} · ${esc(shortCwd(it.cwd))}</div>
             </div>
             <button class="btn ghost hg-r-btn" data-i="${i}">恢复</button>
           </div>`).join('');
      listEl.querySelectorAll('.hg-r-btn').forEach(btn => {
        btn.onclick = async () => {
          const it = items[+btn.dataset.i];
          btn.disabled = true; btn.textContent = '恢复中…';
          try {
            const j = await (await fetch('/api/harness/recover', {method:'POST',
              headers:{'Content-Type':'application/json'},
              body: JSON.stringify({session_id: it.session_id, title: it.title})})).json();
            if (!j.ok) { showBanner(j.err || '恢复失败', 3000, true); btn.disabled = false; btn.textContent = '恢复'; return; }
            it._done = true;
            render();
            refreshSessions();
            showBanner('已找回：' + it.title, 2400);
          } catch(e) { showBanner('恢复失败：' + e, 3000, true); btn.disabled = false; btn.textContent = '恢复'; }
        };
      });
    }
    render();
    document.body.appendChild(ov);
  };
  // 备注/作用域/开关/编辑/删除，整表保存。
  q('[data-hg-prompt]').onclick = async () => {
    let prompts = [];
    try { prompts = (await (await fetch('/api/harness/system_prompt?cwd=' + encodeURIComponent(_HG.cwd || ''))).json()).prompts || []; }
    catch(_) {}
    const saved = await hgPromptManager(prompts, _HG.cwd || '');
    if (saved === null) return;   // 取消不动
    try {
      const r = await fetch('/api/harness/system_prompt', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({prompts: saved})});
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '保存失败', 3000, true); return; }
      showBanner(saved.length ? `已保存 ${saved.length} 条提示词，新会话/复活后生效` : '提示词已清空', 2400);
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
  // 提示词管理界面：条目卡片列表（备注入卡片头，正文 textarea 编辑）。
  // 返回新数组=保存；null=取消。卡片上的状态即时反映到返回值。
  function hgPromptManager(items, cwd) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const list = items.map(it => ({ ...it }));   // 工作副本，保存才落库
      ov.innerHTML = `<div class="hg-modal hg-modal-prompt"><div class="hg-modal-title">📜 自定义提示词</div>
        <div class="hg-modal-body hg-prompt-hint">会话启动时注入（新建/复活）。🌐 全局对所有会话生效；📁 项目只对目录名匹配的会话生效（填目录名如「串口控制台Pro」）。备注是给自己看的标签。</div>
        <div class="hg-prompt-list"></div>
        <div class="hg-modal-acts"></div></div>`;
      const listEl = ov.querySelector('.hg-prompt-list');
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };

      function render() {
        listEl.innerHTML = '';
        list.forEach((it, idx) => {
          const card = document.createElement('div');
          card.className = 'hg-prompt-item' + (it.enabled ? '' : ' off');
          card.innerHTML =
            `<div class="hg-prompt-item-head">` +
            `<input class="hg-prompt-note" placeholder="备注（如：中文注释规范）" value="${esc(it.note || '')}">` +
            `<select class="hg-prompt-scope">` +
            `<option value="global"${it.scope !== 'project' ? ' selected' : ''}>🌐 全局</option>` +
            `<option value="project"${it.scope === 'project' ? ' selected' : ''}>📁 项目</option>` +
            `</select>` +
            `<input class="hg-prompt-proj" placeholder="目录名" value="${esc(it.project || '')}"${it.scope === 'project' ? '' : ' style="display:none"'}${it.active === false ? ' title="当前项目不匹配（不会注入本会话）"' : ''}>` +
            `<button class="hg-prompt-onoff" title="启用/停用">${it.enabled ? '🟢' : '⚪'}</button>` +
            `<button class="hg-prompt-del" title="删除">✕</button></div>` +
            `<textarea class="hg-prompt-ta" spellcheck="false" placeholder="提示词正文…"></textarea>`;
          const ta = card.querySelector('.hg-prompt-ta');
          ta.value = it.text || '';
          ta.oninput = (e) => { it.text = e.target.value; };
          card.querySelector('.hg-prompt-note').oninput = (e) => { it.note = e.target.value; };
          card.querySelector('.hg-prompt-scope').onchange = (e) => {
            it.scope = e.target.value;
            card.querySelector('.hg-prompt-proj').style.display = it.scope === 'project' ? '' : 'none';
          };
          card.querySelector('.hg-prompt-proj').oninput = (e) => { it.project = e.target.value.trim(); };
          card.querySelector('.hg-prompt-onoff').onclick = () => { it.enabled = !it.enabled; render(); };
          card.querySelector('.hg-prompt-del').onclick = () => { list.splice(idx, 1); render(); };
          listEl.appendChild(card);
        });
        if (!list.length)
          listEl.innerHTML = '<div class="hg-prompt-empty">还没有提示词条目。点下方「＋ 新增」创建。</div>';
      }

      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('＋ 新增', false, () => {
        list.push({ id: '', scope: 'global', project: '', note: '', text: '', enabled: true, active: undefined });
        render();
        listEl.lastElementChild && listEl.lastElementChild.querySelector('.hg-prompt-ta').focus();
      });
      mkBtn('保存', true, () => {
        // 空正文条目丢弃；scope=project 但目录名为空 → 提示防误伤
        if (list.some(it => it.scope === 'project' && !it.project)) {
          showBanner('项目条目必须填目录名（或改回全局）', 3000, true);
          return;
        }
        close(list.filter(it => (it.text || '').trim()));
      });
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') close(null);
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) close(list.filter(it => (it.text || '').trim()));
      });
      wrap.appendChild(ov);
      render();
    });
  }

  // ==================== 轻量模态（铁律2）====================
  function hgModal(title, bodyHtml, buttons) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      ov.innerHTML = `<div class="hg-modal"><div class="hg-modal-title">${esc(title)}</div>${bodyHtml}<div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const inp0 = ov.querySelector('input');
      buttons.forEach((b) => {
        const btn = document.createElement('button');
        btn.className = 'btn' + (b.primary ? ' primary' : '');
        btn.textContent = b.label;
        btn.onclick = () => { const v = typeof b.value === 'function' ? b.value(inp0) : b.value; ov.remove(); resolve(v); };
        acts.appendChild(btn);
      });
      ov.addEventListener('click', (e) => { if (e.target === ov) { ov.remove(); resolve(null); } });
      wrap.appendChild(ov);
      const inp = inp0;
      if (inp) { inp.focus(); inp.select();
        inp.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { const b = buttons[buttons.length - 1]; const v = typeof b.value === 'function' ? b.value(inp) : b.value; ov.remove(); resolve(v); }
          if (e.key === 'Escape') { ov.remove(); resolve(null); }
        }); }
    });
  }
  function hgConfirm(title, msg) {
    return hgModal(title, `<div class="hg-modal-body">${esc(msg)}</div>`,
      [{label: '取消', value: false}, {label: '删除', primary: true, value: true}]);
  }
  function hgPrompt(title, label, val) {
    return hgModal(title, `<div class="hg-modal-body"><label>${esc(label)}</label><input data-hg-mi value="${esc(val || '')}"></div>`,
      [{label: '取消', value: null}, {label: '保存', primary: true, value: (inp) => (inp ? inp.value.trim() : '')}]);
  }

  conn.onResumePoll = () => { if (_HG.conn === conn) input.focus(); };

  // ==================== 初始 ====================
  showWelcome();
  _hgDrawCtxRing(0, _HG_CTX_FALLBACK);   // v2.20：上下文环常态显示（0% 占位）
  (async () => {
    await refreshSessions();
    const last = _HG.sessions.find(s => s.has_history);
    if (last) switchTo(last.sid);
    else input.focus();
  })();
  return conn;
}

// ---- 关闭 tab ----
// ==================== v2.24 大会话 DOM 卸载（拖动卡顿根治）====================
// 现象链（用户对照实验定位）：harness 开大会话 → 所有拖动（文件拖入/命令库
// 排序/tab 换位，HTML5 与 OLE 两套机制）全卡 ~12s；空会话不卡；关 tab 恢复；
// /exit 杀进程仍卡；停 ctx/vision 轮询仍卡 → 元凶是大会话消息流的巨大 DOM
// （数千条消息/数万节点，display:none 仍占内存并拖累渲染进程 GC）。
// 修复：切走 harness tab 时把 flow innerHTML 快照到内存并清空 DOM，切回
// 恢复。busy 时不卸载（后台流式 append 依赖 flow 在场，快照覆盖会丢消息）。
;(function _hgFlowUnloadInit() {
  const _orig = switchTab;
  switchTab = function(portId) {
    // isHg/wasHg 必须在 try 块外声明（const 块级作用域——曾定义在 try 内、
    // 块外引用，每次切 tab 必抛 ReferenceError 且真正的切换动作永远不执行，
    // v2.31 未浏览器实测漏网：用户实锤「Claude 对话没反应/打开 settings 失败」）
    const isHg = portId === 'harness:gui';
    const wasHg = activePortId === 'harness:gui';
    try {
      if (wasHg && !isHg && !_HG.busy && _HG.flowEl && _HG.flowEl.innerHTML) {
        _HG.flowSnap = _HG.flowEl.innerHTML;
        _HG.flowEl.innerHTML = '';
      } else if (isHg && !wasHg && _HG.flowSnap && _HG.flowEl) {
        _HG.flowEl.innerHTML = _HG.flowSnap;
        _HG.flowSnap = '';
        _HG.flowEl.scrollTop = _HG.flowEl.scrollHeight;
      }
    } catch(_) {}
    // v2.31：harness tab 激活时右侧「终端助手」整面板换装为会话动态
    if (isHg !== wasHg) _hgPanelMode(isHg);
    return _orig(portId);
  };
})();

// ---- v2.31 右侧面板换装开关（顶层定义：switchTab 包装器与 _harnessClose
// 都在闭包外调用它；只依赖 index.html 静态节点 #aiPanel，无闭包状态）----
// v2.32：进入面板时通过钩子通知闭包（拉 roles + 刷面板）。钩子由
// buildClaudeHarnessTab 闭包赋值；顶层脚本先于闭包执行，let 已初始化。
let _hgPanelEnterHook = null;
function _hgPanelMode(on) {
  const p = document.getElementById('aiPanel');
  if (!p) return;
  p.classList.toggle('hg-mode', !!on);
  const tt = p.querySelector('.ai-head-detail .title');
  const ts = p.querySelector('.ai-head-detail .sub');
  if (tt) tt.textContent = on ? '会话动态' : '终端助手';
  if (ts) ts.textContent = on ? '会话 · 任务 · 子代理 · 工具 · 回合' : '搜索 · 感知 · 分析 · 命令';
  if (on && typeof _hgPanelEnterHook === 'function') {
    try { _hgPanelEnterHook(); } catch(_) {}
  }
}

function _harnessClose(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
  _HG.conn = null; _HG.sid = null; _HG.cache = {};
  _HG.rowById = {}; _HG.run = null;
  // v2.15：补齐残留态复位。旧实现只清了上面这几个，重开 tab 后 dirty/busy/
  // activity 等沿用上一轮的值——dirty 漏复位会与「点 chip 删会话」叠加，
  // 重开后第一次点模型 chip 就可能删掉一条会话。tab 即将销毁，这里只需清
  // 状态，不用走 setBusy 更新界面。
  _HG.dirty = false; _HG.busy = false;
  _HG.initN = 0; _HG.agentModels = null;   // v2.35：init 计数/模型缓存随 tab 销毁（重开 tab 重新拉）
  _HG.dyn = null; _HG.todos = null; _HG.agents = null;   // v2.32：面板派生态随 tab 销毁
  if (_HG.grp) phStopTimer(_HG.grp);   // v2.18：防御性清占位 timer（isConnected 自杀是兜底）
  _HG.grp = null; _HG.activity = null;   // v2.18：组级抽屉（旧 drawer 单例已删）
  _HG.think = null; _HG.noScroll = false; _HG.openState = null;
  _HG.skills = null; _HG.models = null;   // 技能/模型映射下次进 tab 重新拉
  conn.tab.remove();
  conn.wrap.remove();
  delete connections[portId];
  _hgPanelMode(false);   // v2.31：关 harness tab 还原右侧工具面板（剩余 tab 的 switchTab 会再兜一次）
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
  });
  if (remaining.length) switchTab(remaining[0]);
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon">📡</div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();
}

// ---- 顶栏 Claude 按钮分派 ----
let _claudeUiMode = null;
async function _getClaudeUiMode() {
  if (_claudeUiMode === null) {
    try {
      const j = await (await fetch('/api/theme')).json();
      _claudeUiMode = (j.ok && j.claude_ui_mode) ? j.claude_ui_mode : 'harness';
    } catch(_) { _claudeUiMode = 'harness'; }
  }
  return _claudeUiMode;
}
function setClaudeUiMode(m) { _claudeUiMode = m; }

async function claudeButtonAction() {
  const mode = await _getClaudeUiMode();
  if (mode === 'cli') connectClaude();
  else buildClaudeHarnessTab({});
}

// ---- 统一登录胶囊（侧栏底部）：代理/额度/机器人一次登录全通 ----
// 登录走共用接口 /api/proxy/credentials（单一事实源 lanz_credentials.json）；
// 凭据就位后端自动激活机器人（幂等），登出自动停用。未登录机器人不激活。
// 胶囊点击 → 冒泡弹窗（未登录=登录表单；已登录=状态+登出确认）。
function hgLoginRender(st) {
  document.querySelectorAll('[data-hg-login-toggle]').forEach(tg => {
    const dot = tg.querySelector('[data-hg-login-dot]');
    const txt = tg.querySelector('[data-hg-login-text]');
    if (!txt) return;
    if (st.username) {
      if (dot) { dot.className = 'hg-login-dot on'; }
      txt.textContent = st.username + ' 已登录';
    } else {
      if (dot) { dot.className = 'hg-login-dot off'; }
      txt.textContent = '未登录 · 机器人未激活';
    }
  });
  document.querySelectorAll('[data-hg-login-pop]').forEach(pop => {
    const off = pop.querySelector('[data-hg-login-off]');
    const on = pop.querySelector('[data-hg-login-on]');
    if (!off || !on) return;
    if (st.username) {
      off.style.display = 'none'; on.style.display = '';
      const name = pop.querySelector('[data-hg-login-name]');
      if (name) name.textContent = st.username + ' 已登录';
      const bot = pop.querySelector('[data-hg-login-bot]');
      if (bot) bot.textContent = st.running
        ? (st.connected ? '机器人：在线' : '机器人：连接中…') : '机器人：未运行';
    } else {
      off.style.display = ''; on.style.display = 'none';
    }
  });
}
function hgLoginTogglePop(force) {
  document.querySelectorAll('[data-hg-login-pop]').forEach(pop => {
    pop.style.display = (force !== undefined ? force
      : pop.style.display === 'none') ? '' : 'none';
  });
}
async function hgLoginRefresh() {
  try {
    const r = await fetch('/api/hiklink/status');
    const j = await r.json();
    if (j && j.ok) hgLoginRender(j);
  } catch (_) {}
}
document.addEventListener('click', async ev => {
  // 冒泡弹窗开合：点胶囊切换；点弹窗内部不关；点其他区域关闭
  const toggle = ev.target.closest('[data-hg-login-toggle]');
  if (toggle) { hgLoginTogglePop(); return; }
  if (!ev.target.closest('[data-hg-login-pop]')) hgLoginTogglePop(false);
  const loginBtn = ev.target.closest('[data-hg-login-btn]');
  if (loginBtn) {
    const pop = loginBtn.closest('[data-hg-login-pop]');
    const uEl = pop.querySelector('[data-hg-login-user]');
    const pEl = pop.querySelector('[data-hg-login-pwd]');
    const u = (uEl.value || '').trim(), p = pEl.value || '';
    if (!u || !p) { (u ? pEl : uEl).focus(); return; }
    loginBtn.disabled = true; const old = loginBtn.textContent;
    loginBtn.textContent = '登录中…';
    try {
      const r = await fetch('/api/proxy/credentials', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', username: u, password: p }) });
      const sj = await r.json().catch(() => ({}));
      // v2.2.2：写盘失败如实报错——旧版静默吞 + 乐观渲染「已登录」，
      // 凭据实际没落盘，重启就得重登（同事机实锤）
      if (!sj.ok) { showBanner(sj.msg || '登录保存失败', 4000, true); return; }
      // 凭据就位后端已自动激活；再显式触发一次（幂等），并即时回显登录态
      await fetch('/api/hiklink/activate', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
      hgLoginRender({ username: u, running: true, connected: false });
      pEl.value = '';
      setTimeout(hgLoginRefresh, 1500);
    } catch (_) {}
    loginBtn.disabled = false; loginBtn.textContent = old;
    return;
  }
  const outBtn = ev.target.closest('[data-hg-logout-btn]');
  if (outBtn) {
    try { await fetch('/api/proxy/credentials', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"action":"clear"}' }); } catch (_) {}
    hgLoginRefresh();
  }
});
setInterval(hgLoginRefresh, 30000);   // 低频保活（登录态/机器人在线显示）
hgLoginRefresh();

// ---- Proxy 状态按钮（输入卡上方，原顶部按钮迁入）：显示运行态+端口，点击开代理面板 ----
function hgProxyRefreshState() {
  const fetchIt = async () => {
    try {
      const r = await fetch('/api/proxy/status');
      const j = await r.json();
      let txt = '· 未运行', cls = ' off';
      if (j.already_running || j.running) {
        txt = '· 37349 运行中';
        cls = ' on';
        if (j.running && j.snapshot && j.snapshot.in_flight_retries > 0) txt += '（重试中）';
      } else if (j.port_busy) {
        txt = '· 端口被占'; cls = ' err';
      }
      document.querySelectorAll('[data-hg-proxy-state]').forEach(el => {
        el.textContent = txt;
        el.className = 'hg-proxy-state' + cls;
      });
    } catch (_) {}
  };
  fetchIt();
}
document.addEventListener('click', ev => {
  const btn = ev.target.closest('[data-hg-proxy-btn]');
  if (btn && typeof buildProxyTab === 'function') buildProxyTab();
});
// 事件通知（不轮询）：后端在代理状态变化点广播 SSE 信号，前端收到即拉一次
// status 同步显示。连接断开时 EventSource 自动重连；首屏状态由页面加载时
// 的 hgProxyRefreshState() 拉取。
try {
  const hgProxyES = new EventSource('/api/proxy/events');
  hgProxyES.onmessage = () => hgProxyRefreshState();
} catch (_) {}
hgProxyRefreshState();
