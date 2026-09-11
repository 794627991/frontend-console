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
//   - 活动指示条（动词轮换 + 计时 + Stop (esc)）
//   - 单行 ```x``` 折叠成 `x`（normalizeInlineCodeFences）
// 设计文档：docs/CLAUDE_CODE_INTEGRATION.md §8.6
// ============================================================

let _harnessMd = null;
function _harnessMdInstance() {
  if (_harnessMd === null)
    _harnessMd = window.markdownit ? window.markdownit({ html: false, linkify: true, typographer: false, breaks: false }) : false;
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
  Agent:     { mode: 'collapsible', kind: 'agent', title: i => i.description || i.subagent_type || '子代理', get: i => i.prompt || '', result: 'hide' },
  Task:      { mode: 'collapsible', kind: 'agent', title: i => `子代理 / ${i.subagent_type || 'Agent'}: ${i.description || ''}`, get: i => i.prompt || '' },
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

// ---- 组件状态 ----
const _HG = {
  conn: null, sid: null, dirty: false,
  model: null, models: null,
  skills: null,
  sessions: [],
  seq: 0,
  cwd: null,            // v2.7：项目目录（新会话 cwd；null=默认 ~）
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
  imgSrv: null,         // 图片服务路径标记（后端 /api/harness/img/<sid>/file）
  activity: null,       // 活动指示 {start, verbTimer, tickTimer}
  actStart: 0,
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
        </div>
        <div class="hg-search-wrap"><input class="hg-search" data-hg-search placeholder="搜索会话" spellcheck="false"></div>
        <div class="hg-sessions" data-hg-sessions></div>
        <button class="hg-prompt-btn" data-hg-vision title="识图会话配置（多模态识图，转交主会话的看图任务）">👁 识图会话</button>
        <button class="hg-prompt-btn" data-hg-prompt title="管理自定义提示词（全局/项目，会话启动时注入）">📜 提示词</button>
      </div>
      <div class="hg-main">
        <div class="hg-top">
          <span class="hg-cwd lv-btn" data-hg-cwd title="会话项目目录"></span>
          <span class="hg-title" data-hg-title>新会话</span>
          <span class="hg-flex1"></span>
          <span class="hg-top-state" data-hg-state></span>
        </div>
        <div class="hg-flow" data-hg-flow></div>
        <div class="hg-card-wrap">
          <div class="hg-activity" data-hg-activity style="display:none"></div>
          <div class="hg-atts" data-hg-atts style="display:none"></div>
          <div class="hg-input-card">
            <div class="hg-input-stack">
              <div class="hg-input-overlay" data-hg-overlay aria-hidden="true"></div>
              <textarea class="hg-input" data-hg-input rows="1" placeholder="给 Claude 发消息…  @ 引用文件 · / 技能 · 粘贴图片" spellcheck="false"></textarea>
            </div>
            <div class="hg-mention-drop" data-hg-mention style="display:none"></div>
            <div class="hg-card-foot">
              <button class="hg-chip" data-hg-proj title="选择项目目录（新会话直接在该目录下打开）">📁 项目</button>
              <button class="hg-chip" data-hg-att title="添加附件（文档会以路径给模型读取）">📎 附件</button>
              <button class="hg-chip" data-hg-skill title="加载技能（插入 /技能名）">⚡ 技能 ▾</button>
              <button class="hg-chip" data-hg-model title="选择模型（对会话生效）">🧠 模型 ▾</button>
              <span class="hg-flex1"></span>
              <span class="hg-cost" data-hg-cost></span>
              <button class="hg-send" data-hg-send title="发送（Enter）">➤</button>
            </div>
          </div>
        </div>
      </div>
      <input type="file" data-hg-file multiple style="display:none">
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

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

  const scrollBottom = () => {
    if (_HG.noScroll) return;   // v2.16：历史重建期间不滚（几百行逐行 append 会反复重排）
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
    scrollBottom();
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
    // 每题都选了才放行提交
    const need = card.querySelectorAll('.h-ask-q').length;
    let ok = 0;
    for (let k = 0; k < need; k++) if ((sel[k] || []).length) ok++;
    const sb = card.querySelector('.h-ask-submit');
    if (sb) sb.disabled = ok < need;
  }

  function askSubmit(reqId) {
    const card = flow.querySelector(`[data-hg-ask="${CSS.escape(reqId)}"]`);
    if (!card || card.classList.contains('done')) return;
    const qs = askQs(card), sel = askSel(card);
    const answer = {};
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const chosen = (sel[qi] || []).slice();
      if (!chosen.length) return;
      const qtext = (qs[qi] && qs[qi].question) || ('问题' + (qi + 1));
      answer[qtext] = chosen.join(', ');
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
      t.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        if (!/^https?:/i.test(href)) { a.addEventListener('click', e => e.preventDefault()); a.title = '工具内不支持跳转内部链接'; }
      });
      return t.innerHTML;
    }
    return '<p>' + esc(text).replace(/\n/g, '<br>') + '</p>';
  }
  function mdBubble(text) {
    const b = document.createElement('div');
    b.className = 'h-bubble';
    b.innerHTML = renderMd(text);
    codeBlockEnhance(b);
    return b;
  }

  // ==================== 附件 chip / 图片预览 ====================
  function attChipsHtml(images, files) {
    let h = '';
    (images || []).forEach(p => { h += `<span class="hg-att-mini" data-img="${esc(p)}" title="${esc(p)}">🖼 ${esc(String(p).split(/[\\/]/).pop())}</span>`; });
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
    return g;
  }
  function grpEnsure(live) {
    let g = _HG.grp;
    if (g && g.root && g.root.isConnected) return g;
    // 快照恢复（切会话切回）后 _HG.grp 失联 → 扫 flow 最后一个组接回来。
    // 占位动画不重启：正文该到已到才走得到恢复路径。
    const root = flow.querySelector('.h-grp:last-of-type');
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
    const thinkBox = document.createElement('div');
    thinkBox.className = 'h-drawer think';
    thinkBox.innerHTML =
      `<button class="h-drawer-head"><span class="h-chev">▸</span>` +
      `<span class="h-drawer-title">🧠 思考</span>` +
      `<span class="h-tslots" data-hg-dslots></span></button>` +
      `<div class="h-drawer-body"></div>`;
    const execBox = document.createElement('div');
    execBox.className = 'h-drawer exec';
    execBox.innerHTML =
      `<button class="h-drawer-head"><span class="h-chev">▸</span>` +
      `<span class="h-drawer-title">💻 执行</span>` +
      `<span class="h-drawer-stats" data-hg-dstats></span>` +
      `<span class="h-tslots" data-hg-dslots></span></button>` +
      `<div class="h-drawer-body"></div>`;
    proc.appendChild(thinkBox);
    proc.appendChild(execBox);
    nr.appendChild(proc);
    addRow(nr);
    g = grpFromDom(nr, thinkBox, execBox);
    g.counts = {};                 // 新组才清；恢复组从 dataset 读
    if (g.think.stats) g.think.stats.dataset.segCount = '0';
    // 重建期：按记录恢复开合；无记录则默认收起（流式期 openState=null 不干预）
    _hgApplyOpen(thinkBox, false);
    _hgApplyOpen(execBox, false);
    _HG.grp = g;
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
      const d = document.createElement('div');
      d.className = 'h-msg asst ph';
      d.innerHTML = `<div class="h-bubble"><span class="hg-ph-word" data-hg-phw>AI 正在思考中…</span><span class="hg-ph-dots"><i></i><i></i><i></i></span></div>`;
      g.root.appendChild(d);
      g.ph = d;
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
    if (g && g.ph) { g.ph.remove(); g.ph = null; }
  }
  // flow 级事件委托：抽屉组头/工具折叠行点击 → 只切自己
  // （v2.12 修「点一个全展开」+「切会话再切回后点不开」——innerHTML 快照恢复
  //   不丢监听器，每行每抽屉独立开合）
  flow.addEventListener('click', (e) => {
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
    // 思考段条目（v2.18）：段头点击 → 只切该段
    const sHead = e.target.closest('.h-think-seg-head');
    if (sHead) {
      const seg = sHead.closest('.h-think-seg');
      if (seg) { seg.classList.toggle('open'); _hgSaveOpen(seg); }
      return;
    }
    const tHead = e.target.closest('.h-tool-head');
    if (tHead) {
      const row = tHead.closest('.h-tool');
      if (row) { row.classList.toggle('open'); _hgSaveOpen(row); }
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
  });
  function drawerCount(toolName) {
    const g = grpEnsure(true);                  // 计数进当前组执行抽屉
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
  // 组定稿（result / 新一轮 renderUser）：徽章 + 未手动碰过时自动收
  function grpFinalize(auto) {
    const g = _HG.grp;
    if (!g) return;
    phRemove(g);
    if (g.think.stats) g.think.stats.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    if (g.exec.slots) g.exec.slots.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    // 用户手动开过不强制收；自动收只在用户在底部跟读时（v2.12 判据，按组生效）
    if (auto) {
      if (g.think.box.dataset.userToggled !== '1' && isNearBottom()) g.think.box.classList.remove('open');
      if (g.exec.box.dataset.userToggled !== '1' && isNearBottom()) g.exec.box.classList.remove('open');
    }
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
  function renderUser(text, images, files, live) {
    grpFinalize(false);                       // v2.18：上一组定稿，本组接棒
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
    d.appendChild(mdBubble(text || ''));
    addRow(d);
    if (live !== false) {
      const g = grpEnsure(true);
      phStart(g);                              // AI 未输出前的活泼占位（每轮独立）
    }
  }
  function renderAsst(text, isSub) {
    // v2.16：空白/纯换行的 text 块不渲染。模型每轮都会吐一个 "\n\n" 占位块，
    // 旧判据 `if (!text)` 挡不住 → 每条渲染成一个空白气泡（历史重建后满屏空白
    // 圆角条）。重建与流式两条路径都走这里，一并对齐。
    if (!text || !String(text).trim()) return;
    _HG.asstText = true;                       // v2.11：AI 已输出文本
    // v2.18：正文进当前组（组不存在说明是组外场景——快照恢复等，兜底建组）
    const g = grpEnsure(true);
    phRemove(g);                               // 正文接管，占位动画退场
    const d = document.createElement('div');
    d.className = 'h-msg asst' + (isSub ? ' sub' : '');
    d.appendChild(mdBubble(text));
    g.root.appendChild(d);
    scrollBottom();
  }
  function renderRaw(text) {
    const d = document.createElement('div'); d.className = 'h-raw'; d.textContent = text;
    addRow(d);
  }
  function renderExit(text) {
    const d = document.createElement('div'); d.className = 'h-exit'; d.textContent = text;
    addRow(d);
  }

  // ==================== 历史重建（切回会话时按 transcript 行还原气泡/抽屉）====
  // v2.16：从 switchTo 里抽出来，并补上 thinking 行——history 里的「思考过程」
  // 抽屉此前完全丢失（后端 transcript_for 不产出，前端也不认 role='thinking'）。
  // v2.18：重建与流式走同一条路径（renderUser(live=false) / startThinking /
  // endThinking / renderHistTool）——旧 renderHistThinking 把一轮多段 thinking
  // 合并进一个 holder 的分叉删掉，思考分段两条路径一致。
  function renderHistTool(l) {
    // v2.15：与 renderToolUse 的 collapsible 分支同构的结构
    // （.h-tool.col > .h-tool-head[.h-tslots] + .h-tool-coll），
    // 并把后端带的 result（输出）与 err（错误标记）补回来。
    const d = document.createElement('div');
    d.className = 'h-tool col' + (l.err ? ' err open' : '');
    const out = l.result ? String(l.result) : '';
    d.innerHTML =
      `<button class="h-tool-head"><span class="h-chev">▸</span>` +
      `<span class="h-tool-name">${_hToolIco(l.text)} ${esc(_hToolLabel(l.text))}</span>` +
      `<span class="h-tslots">${statusBadge(l.err ? 'error' : 'completed')}</span></button>` +
      `<div class="h-tool-coll">${l.summary ? `<div class="h-tool-arg">${esc(l.summary)}</div>` : ''}` +
      (out ? `<div class="h-tool-out${l.err ? ' err-txt' : ''}">${esc(out.length > 4000 ? out.slice(0, 4000) + '…' : out)}</div>` : '') +
      `</div>`;
    drawerCount(l.text);
    drawerAppend(d, 'exec');
    _hgApplyOpen(d, !!l.err);   // 重建期：恢复上次开合；无记录时错误行默认展开
  }
  function renderHistLine(l) {
    if (l.role === 'user') {
      const imgs = (l.files || []).filter(p => _HARNESS_IMG_EXT.test(p));
      const files = (l.files || []).filter(p => !_HARNESS_IMG_EXT.test(p));
      renderUser(l.text, imgs, files, false);
    }
    else if (l.role === 'assistant') renderAsst(l.text);
    else if (l.role === 'thinking') {
      startThinking(true);                 // 重建路径：段结构同流式，无计时动画
      appendThinking(l.text);
      endThinking(true);                   // hist 模式：不显示时长（不编造）、不自动收
    }
    else if (l.role === 'tool') renderHistTool(l);
  }

  // ==================== thinking 分段条目（v2.18：用户点名重写）====
  // 旧版一轮所有 thinking 挤一个抽屉正文里，分不清哪次思考；
  // 现在每段 thinking 一个可折叠条目（.h-think-seg），组头统计「思考 N 次」。
  // 段边界：text / tool_use 块到来（handleEvent 里 endThinking，调用点不变）。
  // 段起始时间存 seg.dataset.t0——快照恢复后可续算，JS 属性会丢。
  function isNearBottom() {
    return flow.scrollHeight - flow.scrollTop - flow.clientHeight < 120;
  }
  function startThinking(hist) {
    if (_HG.think && _HG.think.seg && _HG.think.seg.isConnected) return;
    const g = grpEnsure(true);
    const n = thinkSegCount(g) + 1;
    thinkSegCountSet(g, n);
    // 组头：「思考 N 次」；busy 中加脉动点
    if (g.think.title) g.think.title.innerHTML = '🧠 思考 <span class="hg-think-anim">' + n + ' 次</span>';
    const seg = document.createElement('div');
    seg.className = 'h-think-seg open';
    if (!hist) {
      seg.dataset.t0 = String(Date.now());   // hist：无真实起始时间，不存不编造
      seg.dataset.n = String(n);
    }
    seg.innerHTML =
      `<button class="h-think-seg-head"><span class="h-chev">▸</span>` +
      `<span class="h-think-seg-name">第 ${n} 段思考</span>` +
      `<span class="h-think-seg-t" data-hg-seg-t data-hg-think-t>0s</span></button>` +
      `<div class="h-think-seg-body"></div>`;
    g.think.body.appendChild(seg);
    _HG.think = { seg, grp: g };
    if (!_HG.asstText) {
      // AI 还没输出正文 → 抽屉保持展开 + 段计时动画（thinkHeadUpdate 驱动）
      if (!hist && g.think.box.dataset.userToggled !== '1') g.think.box.classList.add('open');
      if (!hist) thinkHeadUpdate();
    } else if (!hist) {
      segHeadUpdate(seg);
    }
  }
  // 活动思考段组头状态：本轮尚无 AI 正文时脉动「思考中…」，其余实时计时
  function thinkHeadUpdate() {
    const t = _HG.think;
    if (!t || !t.seg.isConnected) return;
    if (!_HG.asstText) {
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

  function renderToolUse(b, isSub) {
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
    _HG.rowById[id] = row;
    drawerCount(name);                    // v2.7：计数进抽屉组头（Bash×3 · Read×5 …）
    // v2.8：抽屉时代不再合并同名 run——每条 Bash/Read/Grep 调用都是独立过程行
    // （用户明确要能看到每一次执行；组头徽章已承担"×N 汇总"职责）
    _HG.run = { name, head: row, rows: [row] };
    drawerAppend(row, 'exec');             // v2.11：过程行进执行抽屉（不再散落消息流）
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
    // 分组成员：结果状态聚合到组头（成功不刷组头徽章避免闪烁，错误标红）
    const showRow = row._grouped ? row._groupHead : row;
    const slots = showRow.querySelector('.h-tslots');
    if (slots && st !== 'completed') slots.innerHTML = statusBadge(st);
    else if (slots && !row._grouped) slots.innerHTML = statusBadge(st);
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

  // ==================== 活动指示条（源 ActivityIndicator）====================
  const _ACT_WORDS = ['思考中', '处理中', '分析中', '执行中', '检索中', '推理中'];
  let _actWordIdx = 0;
  function actStart() {
    if (_HG.activity) return;
    _HG.actStart = Date.now();
    _actWordIdx = 0;
    actEl.style.display = 'flex';
    actEl.innerHTML = `<span class="hg-act-dot"></span><span class="hg-act-word" data-hg-aw>思考中</span><span data-hg-act-t>0s</span><span class="hg-flex1"></span><button class="hg-act-stop" data-hg-stop title="停止 (Esc)">停止 ⏹</button>`;
    actEl.querySelector('[data-hg-stop]').onclick = stopGen;
    _HG.activity = {
      verb: setInterval(() => {
        _actWordIdx = (_actWordIdx + 1) % _ACT_WORDS.length;
        const w = actEl.querySelector('[data-hg-aw]');
        if (w) w.textContent = _ACT_WORDS[_actWordIdx];
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
    if (v && v.used > 0) _hgDrawCtxRing(v.used, v.max || _HG_CTX_FALLBACK);
    else costEl.innerHTML = '';
  }
  function _hgDrawCtxRing(used, ctxMax) {
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
    costEl.title = `当前上下文 ${fmtTok(used)} / ${fmtTok(ctxMax)} tokens（${Math.round(pct)}%）`;
    costEl.classList.toggle('warn', pct >= 80);
  }
  function renderCtxRing(o) {
    const u = o.usage || {};
    const used = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) +
                 (u.cache_creation_input_tokens || 0);
    if (typeof used !== 'number' || used <= 0) return;
    let ctxMax = _HG_CTX_FALLBACK;
    const mu = o.modelUsage || {};
    for (const k in mu) {
      if (mu[k] && typeof mu[k].contextWindow === 'number' && mu[k].contextWindow > 0) {
        ctxMax = mu[k].contextWindow; break;
      }
    }
    _hgDrawCtxRing(used, ctxMax);
    if (_HG.sid) { try { localStorage.setItem(_hgCtxKey(_HG.sid), JSON.stringify({used, max: ctxMax})); } catch(_) {} }
  }

  function setBusy(b) {
    _HG.busy = b;
    conn.tab.querySelector('.led').classList.toggle('on', b);
    sendBtn.classList.toggle('stop', b);
    sendBtn.textContent = b ? '■' : '➤';
    sendBtn.title = b ? '停止生成' : '发送（Enter）';
    stateEl.textContent = b ? '' : (_HG.alive ? '就绪' : '');
    if (b) actStart(); else actStop();
  }

  // ==================== CLI 事件 → 渲染 ====================
  function handleEvent(o) {
    const typ = o.type;
    if (typ === 'system') {
      const sub = o.subtype;
      if (sub === 'init') {
        _HG.alive = true;
        if (!_HG.busy) setBusy(false);
      } else if (sub === 'status') {
        // v2.7：压缩状态（实测 CLI 事件：status:"compacting" 开始 / "requesting" 恢复）
        if (o.status === 'compacting') actWord('正在压缩上下文…');
        else actWord(null);
      } else if (sub === 'api_error' || sub === 'error') {
        renderRaw('⚠ ' + (o.error ? JSON.stringify(o.error).slice(0, 200) : JSON.stringify(o).slice(0, 200)));
      }
    } else if (typ === 'assistant') {
      const blocks = (o.message || {}).content || [];
      const isSub = !!o.parent_tool_use_id;
      for (const b of blocks) {
        if (b.type === 'thinking' && b.thinking) { closeRun(); appendThinking(b.thinking); }
        else if (b.type === 'text' && b.text && b.text.trim()) { endThinking(); closeRun(); renderAsst(b.text, isSub); }
        else if (b.type === 'tool_use') { endThinking(); renderToolUse(b, isSub); }
      }
      scrollBottom();
    } else if (typ === 'user') {
      const c0 = (o.message || {}).content;
      // 用户真实消息打断工具 run；工具结果事件不动 run（rendersNothing 思想）
      if (!Array.isArray(c0) || !c0.some(b => b && b.type === 'tool_result')) closeRun();
      const hasToolResult = Array.isArray(c0) && c0.some(b => b && b.type === 'tool_result');
      if (!o.isSynthetic && hasToolResult) {
        renderToolResult(o);
        scrollBottom();
      }
    } else if (typ === 'result') {
      endThinking();
      closeRun();
      grpFinalize(true);                   // v2.18：本轮组定稿——用户没手动
                                          // 操作过且在底部跟读时自动收起（想看再点开，
                                          // 各抽屉独立开合）
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
    if (!sid) return;
    const es2 = new EventSource(`/api/harness/stream?sid=${encodeURIComponent(sid)}&after_seq=${afterSeq || 0}`);
    _HG.sse = es2;
    es2.onmessage = (ev) => {
      let it;
      try { it = JSON.parse(ev.data); } catch(_) { return; }
      if (it.seq && it.seq > _HG.seq) _HG.seq = it.seq;
      // v2.5：先 setBusy（弹活动指示条，改变 flow 高度）再渲染消息——
      // 渲染内部 scrollBottom 含 rAF 二次兜底，否则指示条挤出消息导致刚发的消息不在底
      if (it.kind === 'user_echo') { setBusy(true); renderUser(it.text, it.images, it.files); }
      else if (it.kind === 'event') handleEvent(it.data);
      else if (it.kind === 'raw') renderRaw(it.text);
      else if (it.kind === 'ask') { grpFinalize(true); askRender(it); }
      else if (it.kind === 'ask_done') askDone(it);
      else if (it.kind === 'interrupted') {
        endThinking(); grpFinalize(true); renderExit(it.text); setBusy(false);
        // v2.15：通知 stopGen 兜底逻辑「事件到了」，别重复收尾
        try { document.dispatchEvent(new CustomEvent('hg-interrupted', {detail: _HG.sid})); } catch(_) {}
      }
      else if (it.kind === 'exit') { endThinking(); _HG.alive = false; grpFinalize(true); renderExit(it.text); setBusy(false); }
    };
  }

  // ==================== 会话切换 ====================
  function _hgHasHistory(sid) {
    const s = _HG.sessions.find(x => x.sid === sid);
    return !!(s && s.has_history);
  }
  function saveCache() {
    if (_HG.sid) _HG.cache[_HG.sid] = { html: flow.innerHTML, seq: _HG.seq };
  }
  async function switchTo(sid, keepInput) {
    if (sid === _HG.sid && flow.querySelector('.h-msg, .hg-welcome')) {
      // v2.15：点的是当前会话 → 早返回。但 busy 卡死时用户正是靠「重点一下
      // 当前会话」自救，这里不能什么都不做：至少按后端真实值纠偏一次。
      if (sid) {
        fetch(`/api/harness/events?sid=${encodeURIComponent(sid)}&after_seq=${_HG.seq}`)
          .then(r => r.json())
          .then(j => { if (j.ok && _HG.sid === sid) setBusy(!!j.busy); })
          .catch(() => { if (_HG.sid === sid) setBusy(false); });
      }
      return;
    }
    saveCache();
    closePop(); closeMention();
    endThinking(); closeRun();
    if (_HG.grp) phStopTimer(_HG.grp);   // v2.18：防御性清占位 timer（isConnected 自杀是兜底）
    _hgMentionReset();          // v2.15：@ 引用高亮不跨会话残留
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;   // v2.18：组级抽屉
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
    clearAtts();
    _hgCtxRestore(sid);                // 切回旧会话：恢复该会话上次的上下文用量（result 不重放）
    if (!sid) {
      flow.innerHTML = '';
      showWelcome();
      openSSE(null); setBusy(false);
      titleEl.textContent = '新会话'; cwdEl.textContent = '';
      renderList();
      input.focus();
      return;
    }
    const c = _HG.cache[sid];
    if (c) {
      flow.innerHTML = c.html; _HG.seq = c.seq;
      // 快照恢复后重建 rowById（busy 会话切回时 tool_result 事件要挂回行）
      flow.querySelectorAll('[data-tid]').forEach(el => { _HG.rowById[el.dataset.tid] = el; });
      // v2.9：缓存恢复不能盲目清 busy——切走时正在回复的会话，切回后
      // 事件继续流入但 user_echo 已在 seq 之前（不重放），活动条/停止钮
      // 再也不弹（用户实测「有实际对话但无计时条、发送键不变■」）。
      // 后端 events 接口顺带返回真实 busy，按它恢复
      fetch(`/api/harness/events?sid=${encodeURIComponent(sid)}&after_seq=${_HG.seq}`)
        .then(r => r.json())
        .then(j => { if (j.ok && _HG.sid === sid) setBusy(!!j.busy); })
        .catch(() => { if (_HG.sid === sid) setBusy(false); });
    } else {
      flow.innerHTML = '';
      try {
        const j = await (await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)).json();
        if (j.ok && _HG.sid === sid) {
          _HG.seq = j.seq || 0; _HG.alive = !!j.alive;
          if (!j.lines.length) showWelcome();
          else {
            // v2.16：重建期间禁自动滚底——几百行逐行 append 会反复触发重排，卡且无意义
            _HG.noScroll = true;
            _HG.openState = _hgLoadOpen(sid);   // 上次记录的开合状态（重建期间贴回）
            try { j.lines.forEach(l => renderHistLine(l)); }
            finally { _HG.noScroll = false; _HG.openState = null; }
          }
          grpFinalize(true);               // transcript 末尾若挂着未收的组 → 定稿自动收起
          scrollBottom();
          setBusy(!!j.busy);
        }
      } catch(_) {}
    }
    const s = _HG.sessions.find(x => x.sid === sid);
    // v2.7：项目优先——cwd 目录名在前（accent），claude 会话名在后
    cwdEl.textContent = s ? (s.cwd || '').split(/[\\/]/).pop() || '~' : '';
    titleEl.textContent = (s && s.title) || '会话';
    conn.meta.label = titleEl.textContent;
    conn.meta.cwd = (s && s.cwd) || '';
    conn.tab.querySelector('.label').textContent = titleEl.textContent;
    openSSE(sid, _HG.seq);
    renderList();
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

  // ==================== 会话列表 ====================
  async function refreshSessions() {
    try {
      const j = await (await fetch('/api/harness/sessions')).json();
      if (j.ok) { _HG.sessions = j.sessions || []; renderList(); }
    } catch(_) {}
  }
  function renderList() {
    const kw = (searchEl.value || '').trim().toLowerCase();
    const items = _HG.sessions.filter(s => !kw || (s.title || '').toLowerCase().includes(kw)
      || (s.cwd || '').toLowerCase().includes(kw));
    // v2.7：项目信息优先——第一行=项目目录名（cwd basename），第二行=claude 会话名 · 模型
    listEl.innerHTML = items.map(s => {
      const proj = (s.cwd || '').split(/[\\/]/).pop() || '~';
      return `
      <div class="hg-item${s.sid === _HG.sid ? ' active' : ''}" data-sid="${esc(s.sid)}" title="${esc(s.cwd || '')} · ${esc(s.title || '')}">
        <div class="hg-item-row">
          <span class="hg-item-proj">${esc(proj)}</span>
          <span class="hg-item-time">${_harnessRelTime(s.last_active)}</span>
        </div>
        <div class="hg-item-row">
          <span class="hg-item-title">${esc(s.title || '新会话')}</span>
          <span class="hg-item-acts">
            ${s.busy ? '<span class="hg-item-busy" title="回复中">●</span>' : ''}
            <button class="hg-item-act" data-act="rename" data-sid="${esc(s.sid)}" title="重命名">✎</button>
            <button class="hg-item-act del" data-act="del" data-sid="${esc(s.sid)}" title="删除会话">✕</button>
          </span>
        </div>
        <div class="hg-item-row">
          <span class="hg-item-sub">${s.model ? esc(s.model) : ''}</span>
        </div>
      </div>`;}).join('') || '<div class="hg-list-empty">暂无会话</div>';
  }
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
  function newChat() { saveCache(); switchTo(null); }
  q('[data-hg-new]').onclick = newChat;

  async function ensureSession() {
    if (_HG.sid) return _HG.sid;
    const r = await fetch('/api/harness/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model: _HG.model || '', cwd: _HG.cwd || ''})});
    const j = await r.json();
    if (!j.ok) {
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

  async function send() {
    const text = input.value.trim();
    if (!text && !_HG.atts.length) return;
    if (_HG.busy) { showBanner('claude 正在回复中，可点 ■ 停止', 2500, true); return; }
    const images = _HG.atts.filter(a => a.isImg).map(a => a.path);
    const files = _HG.atts.filter(a => !a.isImg).map(a => a.path);
    const sid = await ensureSession();
    if (!sid) return;
    _hgHistAppend(sid, text);          // 输入历史（记录到真实会话 scope）
    _HG.histNav = null;
    input.value = ''; input.style.height = 'auto'; renderOverlay('');
    clearAtts();
    try {
      const r = await fetch('/api/harness/send', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid, text, images, files})});
      const j = await r.json();
      if (!j.ok) {
        input.value = text;
        showBanner(j.err || '发送失败', 3000, true);
        return;
      }
      _HG.dirty = true;
      setBusy(true);
      refreshSessions();
    } catch(e) {
      input.value = text;
      showBanner('发送失败：' + e, 3000, true);
    }
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
  function renderAtts() {
    if (!_HG.atts.length) { attsEl.style.display = 'none'; attsEl.innerHTML = ''; return; }
    attsEl.style.display = 'flex';
    attsEl.innerHTML = _HG.atts.map((a, i) => `
      <span class="hg-att-chip">${a.isImg ? `<img class="hg-att-thumb" src="${esc(a.path)}" title="${esc(a.name)}" data-img="${esc(a.path)}">` : '📄'} ${esc(a.name)}
        <button class="hg-att-x" data-i="${i}" title="移除">✕</button></span>`).join('');
    attsEl.querySelectorAll('[data-img]').forEach(t => t.onclick = () => openLightbox(t.dataset.img));
  }
  function clearAtts() { _HG.atts = []; renderAtts(); }
  attsEl.addEventListener('click', (e) => {
    const x = e.target.closest('.hg-att-x');
    if (x) { _HG.atts.splice(+x.dataset.i, 1); renderAtts(); }
  });
  q('[data-hg-att]').onclick = () => fileEl.click();
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

  // ==================== popover（技能/模型）====================
  function closePop() {
    if (_HG.pop) { const p = wrap.querySelector('.hg-pop'); if (p) p.remove(); _HG.pop = null; }
  }
  function openPop(kind, anchor, html) {
    closePop();
    _HG.pop = kind;
    const p = document.createElement('div');
    p.className = 'hg-pop';
    p.innerHTML = html;
    anchor.parentElement.appendChild(p);
    const ar = anchor.getBoundingClientRect(), wr = wrap.querySelector('.hg-card-wrap').getBoundingClientRect();
    p.style.left = Math.max(6, Math.min(ar.left - wr.left, wr.width - p.offsetWidth - 6)) + 'px';
  }
  q('[data-hg-skill]').onclick = async (e) => {
    if (_HG.pop === 'skill') { closePop(); return; }
    const anchor = e.currentTarget;
    if (!_HG.skills) {
      try {
        const j = await (await fetch('/api/harness/skills')).json();
        _HG.skills = (j.ok && j.skills) || [];
      } catch(_) { _HG.skills = []; }
    }
    const items = _HG.skills.length
      ? _HG.skills.map(s => `<div class="hg-pop-item" data-skill="${esc(s.name)}"><b>/${esc(s.name)}</b><span>${esc((s.description || '').slice(0, 60))}</span></div>`).join('')
      : '<div class="hg-pop-empty">未发现技能（~/.claude/skills 或项目 .claude/skills）</div>';
    openPop('skill', anchor, `<div class="hg-pop-title">技能</div>${items}`);
  };
  q('[data-hg-model]').onclick = async (e) => {
    if (_HG.pop === 'model') { closePop(); return; }
    const anchor = e.currentTarget;
    if (!_HG.models) {
      try { _HG.models = await (await fetch('/api/harness/models')).json(); } catch(_) { _HG.models = {models: [], default: null}; }
    }
    const cur = _HG.model || _HG.models.default;
    const items = (_HG.models.models || []).map(m =>
      `<div class="hg-pop-item${m === cur ? ' on' : ''}" data-model="${esc(m)}"><b>${esc(m)}</b>${m === _HG.models.default ? '<span>默认</span>' : ''}</div>`).join('')
      || '<div class="hg-pop-empty">读取 settings.json 模型映射失败</div>';
    openPop('model', anchor, `<div class="hg-pop-title">模型（有对话的会话需新建才生效）</div>${items}`);
  };
  wrap.addEventListener('click', (e) => {
    const si = e.target.closest('[data-skill]');
    if (si) {
      input.value = (input.value ? input.value.replace(/\s*$/, ' ') : '') + '/' + si.dataset.skill + ' ';
      renderOverlay(input.value);
      closePop(); input.focus(); return;
    }
    const mi = e.target.closest('[data-model]');
    if (mi) {
      const m = mi.dataset.model;
      _HG.model = m;
      q('[data-hg-model]').innerHTML = '🧠 ' + esc(m) + ' ▾';
      if (!_HG.dirty) {
        if (_HG.sid) {
          fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
          switchTo(null);
        }
        showBanner('模型 ' + m + ' 将用于当前新会话', 2200);
      } else {
        showBanner('当前会话已有对话，' + m + ' 将在新建会话生效', 2800);
      }
      closePop(); return;
    }
    if (!e.target.closest('.hg-pop') && !e.target.closest('.hg-chip')) closePop();
  });
  if (_HG.model) q('[data-hg-model]').innerHTML = '🧠 ' + esc(_HG.model) + ' ▾';

  // ==================== 项目目录（v2.7：新会话直接开在所选目录）====
  // 原生目录选择（pywebview pick_dir 已有）；选中后影响下一个新会话——
  // 当前会话没对话内容时立即重建（同模型 chip 语义），有内容则提示新建后生效。
  function projChipLabel() {
    const btn = q('[data-hg-proj]');
    if (!btn) return;
    btn.innerHTML = _HG.cwd
      ? '📁 ' + esc(_HG.cwd.split(/[\\/]/).pop() || _HG.cwd)
      : '📁 项目';
  }
  q('[data-hg-proj]').onclick = async () => {
    let dir = '';
    if (window.pywebview && pywebview.api && pywebview.api.pick_dir) {
      dir = await pywebview.api.pick_dir() || '';
    }
    if (!dir) return;                     // 取消选择不动
    _HG.cwd = dir;
    projChipLabel();
    if (!_HG.dirty) {
      if (_HG.sid) {
        fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
        switchTo(null);
      }
      showBanner('新会话将打开在 ' + dir, 2600);
    } else {
      showBanner('当前会话已有对话，新会话将打开在 ' + dir, 3200);
    }
  };
  projChipLabel();

  // ==================== 识图会话配置（v2.14）====================
  // 后台常驻一个专用识图会话（固定多模态模型 + 固定 peer 名字）。主会话
  // 不具备看图能力，需要识图时用 Claude Code 原生的 SendMessage 把图片
  // 路径交给它，结论自动回传——不走 MCP、不自造通道。
  // 「固定基础提示词」不占提示词列表位置，直接注入识图会话进程。
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
      if (!saved.enabled) { showBanner('识图会话已关闭', 2600); return; }
      // 保存后立即拉起，省得等下一轮 GC（用户改完就想知道能不能用）
      const rs = await (await fetch('/api/harness/vision/start', {method:'POST'})).json();
      if (rs.ok) showBanner(`识图会话已就绪（${rs.name} · ${rs.model || '默认模型'}），新会话即可转交识图`, 3600);
      else showBanner('配置已存，但识图会话启动失败：' + (rs.err || '未知'), 4200, true);
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
  // 识图配置界面：开关 + 会话名 + 模型 + 固定基础提示词（可恢复默认）。
  // 返回对象=保存；null=取消。
  function hgVisionManager(init) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const cfg = { ...(init.vision || {}) };
      const def = init.defaults || {};
      const models = init.models || [];
      const curModel = cfg.model || '';
      const opts = ['<option value=""' + (curModel ? '' : ' selected') + '>默认模型</option>']
        .concat(models.map(m => `<option value="${esc(m)}"${m === curModel ? ' selected' : ''}>${esc(m)}</option>`))
        .join('');
      ov.innerHTML = `<div class="hg-modal hg-modal-vision"><div class="hg-modal-title">👁 识图会话</div>
        <div class="hg-modal-body hg-vision-hint">后台常驻一个专用会话负责看图，主会话需要识图时经 Claude Code 原生会话通讯把图片交给它，结论自动回传。<b>改了开关/模型/提示词会让旧会话失效，下条消息自动用新配置重启。</b></div>
        <div class="hg-vision-row">
          <label class="hg-vision-switch"><input type="checkbox" data-hg-v-on${cfg.enabled ? ' checked' : ''}> 启用识图会话</label>
          <span class="hg-vision-state" data-hg-v-state></span>
        </div>
        <div class="hg-vision-grid">
          <label>会话名（主会话按它寻找，支持中文）
            <input data-hg-v-name value="${esc(cfg.name || def.name || '')}" placeholder="${esc(def.name || '')}"></label>
          <label>识图模型（多模态）
            <select data-hg-v-model>${opts}</select></label>
        </div>
        <label class="hg-vision-prompt-lab">固定基础提示词（注入识图会话，不占提示词列表）
          <textarea class="hg-vision-prompt" data-hg-v-prompt spellcheck="false"></textarea></label>
        <div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };
      const ta = ov.querySelector('[data-hg-v-prompt]');
      const nameEl = ov.querySelector('[data-hg-v-name]');
      const modelEl = ov.querySelector('[data-hg-v-model]');
      const onEl = ov.querySelector('[data-hg-v-on]');
      ta.value = cfg.prompt || def.prompt || '';
      const stateEl = ov.querySelector('[data-hg-v-state]');
      const paint = () => {
        stateEl.textContent = init.running ? '● 运行中' : (onEl.checked ? '○ 未运行（保存后自动拉起）' : '已关闭');
        stateEl.className = 'hg-vision-state' + (init.running ? ' on' : '');
      };
      onEl.onchange = paint;
      paint();

      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('恢复默认提示词', false, () => { ta.value = def.prompt || ''; ta.focus(); });
      mkBtn('保存', true, () => close({
        enabled: onEl.checked,
        model: modelEl.value.trim(),
        name: nameEl.value.trim() || (def.name || ''),
        prompt: ta.value.trim(),
      }));
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
      wrap.appendChild(ov);
      nameEl.focus();
    });
  }

  // ==================== 自定义提示词（v2.8：多条目 + 全局/项目作用域）====
  // 每个会话进程启动时后端 --append-system-prompt 注入（新会话/复活同路径）：
  // 启用的全局条目对全部会话生效；项目条目只对 cwd 目录名匹配的会话生效。
  // 入口在左栏最底部（用户指定位置）；管理界面 = 条目列表 + 每条
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
  (async () => {
    await refreshSessions();
    const last = _HG.sessions.find(s => s.has_history);
    if (last) switchTo(last.sid);
    else input.focus();
  })();
  return conn;
}

// ---- 关闭 tab ----
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
  if (_HG.grp) phStopTimer(_HG.grp);   // v2.18：防御性清占位 timer（isConnected 自杀是兜底）
  _HG.grp = null; _HG.activity = null;   // v2.18：组级抽屉（旧 drawer 单例已删）
  _HG.think = null; _HG.noScroll = false; _HG.openState = null;
  _HG.skills = null; _HG.models = null;   // 技能/模型映射下次进 tab 重新拉
  conn.tab.remove();
  conn.wrap.remove();
  delete connections[portId];
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
