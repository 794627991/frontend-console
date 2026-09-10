// ============================================================
// Claude Harness 界面化会话（第 4 期）：stream-json 聊天 tab。
// 与内嵌终端（claude.js connectClaude，ConPTY xterm 保真）平行的另一条
// 通道：后端 src/claude_harness.py spawn `claude -p --input/output-format
// stream-json`，NDJSON 事件原样透传，本文件负责全部渲染
// （分层照 sugyan/claude-code-webui：后端薄透传、前端厚渲染）。
// 设计文档：docs/CLAUDE_CODE_INTEGRATION.md
// ============================================================

let _harnessMd = null;
function _harnessMdInstance() {
  if (_harnessMd === null)
    _harnessMd = window.markdownit ? window.markdownit({ html: false, linkify: true, typographer: false, breaks: false }) : false;
  return _harnessMd;
}

// 工具名 → 命令行摘要（tool_use 块的 input 里挑最关键的一个字段显示）
function _harnessToolSummary(name, input) {
  const i = input || {};
  try {
    if (name === 'Read' || name === 'Write' || name === 'Edit') return i.file_path || '';
    if (name === 'Bash' || name === 'PowerShell') return i.command || i.cmd || '';
    if (name === 'Grep' || name === 'Glob') return i.pattern || '';
    if (name === 'WebFetch' || name === 'WebSearch') return i.url || i.query || '';
    if (name.startsWith('mcp__')) {
      // MCP 工具：参数值取第一个字符串字段
      for (const k in i) { if (typeof i[k] === 'string' && i[k]) return `${k}=${i[k].slice(0, 60)}`; }
      return '';
    }
    if (typeof i.cmd === 'string') return i.cmd;
    return '';
  } catch(_) { return ''; }
}

// ---- tab 构建（单例骨架同 bit-calc/proxy-panel：connections 表 + tab/wrap DOM）----
function buildClaudeHarnessTab(opts = {}) {
  // 单例：已开就切换（工具内只开一个 harness，多点击=切回对应 tab）
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'harness') { switchTab(pid); return; }
  }
  const portId = 'harness:' + Date.now();
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
    <div class="harness">
      <div class="harness-toolbar">
        <span class="lv-btn harness-cwd" data-h-cwd title="会话工作目录">${esc((opts.cwd || '').split(/[\\\\/]/).pop() || '~')}</span>
        <span class="lv-info" data-h-state></span>
        <button class="lv-btn" data-h-new title="新开会话（当前会话保留在 ~/.claude 转写）">✚ 新会话</button>
        <button class="lv-btn" data-h-clear title="清空当前显示（不动 ~/.claude 转写）">清空</button>
      </div>
      <div class="harness-flow" data-h-flow></div>
      <div class="harness-inputbar">
        <textarea data-h-input rows="1" placeholder="输入消息，Enter 发送 · Shift+Enter 换行" spellcheck="false"></textarea>
        <button class="btn primary" data-h-send title="发送（Enter）">发送</button>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const conn = {
    portId,
    meta: { kind: 'harness', label: 'Claude 对话', cwd: opts.cwd || '' },
    tab, wrap,
    backendId: null,     // 后端 harness 会话 port_id（harness:N）
    sse: null,
    busy: false,
    seq: 0,
    // 渲染状态：当前 assistant 消息在流的哪个块（流式增量追加）
    _curAsst: null,       // 当前 assistant 消息 DOM
    _curTool: null,       // 当前 tool_use 摘要 DOM
    _pollTimer: null,
  };
  connections[portId] = conn;
  switchTab(portId);

  const flow = wrap.querySelector('[data-h-flow]');
  const input = wrap.querySelector('[data-h-input]');
  const stateEl = wrap.querySelector('[data-h-state]');
  const sendBtn = wrap.querySelector('[data-h-send]');

  const setState = (txt, isBusy) => {
    stateEl.textContent = txt || '';
    conn.busy = !!isBusy;
    sendBtn.disabled = !!isBusy;
    sendBtn.textContent = isBusy ? '思考中…' : '发送';
  };

  // ---- 事件渲染 ----
  // kind: user_echo（本地回显）/ event（CLI NDJSON 原样）/ raw（杂音）/ exit
  function addMsg(role, html) {
    const d = document.createElement('div');
    d.className = 'h-msg ' + role;
    d.innerHTML = html;
    flow.appendChild(d);
    flow.scrollTop = flow.scrollHeight;
    return d;
  }
  function renderMd(text) {
    const md = _harnessMdInstance();
    if (md) {
      const html = md.render(text);
      // 链接只留外链新开（同 editor.js _mdRenderPreview 安全策略）
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
  function renderUser(text) {
    addMsg('user', `<div class="h-bubble">${renderMd(text)}</div>`);
  }
  function renderAsst(text) {
    if (!text) return;
    addMsg('asst', `<div class="h-bubble">${renderMd(text)}</div>`);
  }
  function renderTool(name, summary, parent) {
    const d = document.createElement('div');
    d.className = 'h-tool' + (parent ? ' sub' : '');
    d.innerHTML = `<span class="h-tool-name">${esc(name)}</span><span class="h-tool-arg">${esc(summary)}</span>`;
    flow.appendChild(d);
    flow.scrollTop = flow.scrollHeight;
    return d;
  }
  function renderRaw(text) {
    const d = document.createElement('div');
    d.className = 'h-raw';
    d.textContent = text;
    flow.appendChild(d);
    flow.scrollTop = flow.scrollHeight;
  }
  function renderExit(text) {
    const d = document.createElement('div');
    d.className = 'h-exit';
    d.textContent = text;
    flow.appendChild(d);
    flow.scrollTop = flow.scrollHeight;
  }

  // 一条 CLI NDJSON 事件 → 渲染（事件模型：system/assistant/user/result，
  // assistant.message.content 数组含 text/thinking/tool_use 块）
  function handleEvent(o) {
    const typ = o.type;
    if (typ === 'system') {
      const sub = o.subtype;
      if (sub === 'init') {
        conn.meta.label = 'Claude 对话';
        setState('就绪 · ' + (o.model || ''), false);
      } else if (sub === 'api_error' || sub === 'error') {
        renderRaw('⚠ ' + (o.error ? JSON.stringify(o.error).slice(0, 200) : JSON.stringify(o).slice(0, 200)));
      }
      // hook_started/hook_response/thinking_tokens 等杂音不渲染（保流畅）
    } else if (typ === 'assistant') {
      const msg = o.message || {};
      const blocks = msg.content || [];
      const isSub = !!o.parent_tool_use_id;   // 子代理消息：缩进折叠样式
      for (const b of blocks) {
        if (b.type === 'text' && b.text) {
          if (isSub) {
            const d = document.createElement('div');
            d.className = 'h-msg asst sub';
            d.innerHTML = `<div class="h-bubble">${renderMd('[子代理] ' + b.text)}</div>`;
            flow.appendChild(d);
          } else {
            renderAsst(b.text);
          }
        } else if (b.type === 'tool_use') {
          renderTool(b.name, _harnessToolSummary(b.name, b.input), isSub);
        }
        // thinking 块不渲染（体积大且非用户视角内容；转写可在 ~/.claude 查看）
      }
      flow.scrollTop = flow.scrollHeight;
    } else if (typ === 'user') {
      // tool_result 回显（isSynthetic 的系统注入消息不渲染）
      if (!o.isSynthetic && o.parent_tool_use_id) {
        // 工具结果：折叠一行摘要（点击展开太重，v1 只显示有结果标记）
        const c = o.message && o.message.content;
        const txt = Array.isArray(c)
          ? c.map(x => x && x.type === 'text' ? x.text : '').join('').slice(0, 120)
          : (typeof c === 'string' ? c.slice(0, 120) : '');
        const d = document.createElement('div');
        d.className = 'h-tool-res';
        d.textContent = txt ? '↳ ' + txt.replace(/\s+/g, ' ').slice(0, 120) : '↳ (完成)';
        flow.appendChild(d);
        flow.scrollTop = flow.scrollHeight;
      }
    } else if (typ === 'result') {
      const cost = o.total_cost_usd;
      const turns = o.num_turns;
      setState(`完成 · ${turns || 1} 轮${typeof cost === 'number' ? ' · $' + cost.toFixed(4) : ''}`, false);
      const el = wrap.querySelector('.h-exit');
      if (o.subtype && o.subtype !== 'success') {
        renderRaw(`⚠ 回复异常结束：${o.subtype}${o.result ? ' — ' + String(o.result).slice(0, 200) : ''}`);
      }
    }
  }

  // ---- SSE ----
  function connectSSE(backendId, afterSeq) {
    if (conn.sse) { try { conn.sse.close(); } catch(_) {} }
    const es2 = new EventSource(`/api/harness/stream?port_id=${encodeURIComponent(backendId)}&after_seq=${afterSeq || 0}`);
    conn.sse = es2;
    es2.onmessage = (ev) => {
      let it;
      try { it = JSON.parse(ev.data); } catch(_) { return; }
      if (it.seq && it.seq > conn.seq) conn.seq = it.seq;
      if (it.kind === 'user_echo') renderUser(it.text);
      else if (it.kind === 'event') handleEvent(it.data);
      else if (it.kind === 'raw') renderRaw(it.text);
      else if (it.kind === 'exit') { renderExit(it.text); setState('会话已结束', false); }
    };
  }

  // ---- 会话启动 ----
  async function startSession(resume) {
    const cwd = opts.cwd || '';
    const nid = notifyTask({type:'claude', title:'正在启动 Claude 对话', detail: cwd || '新会话'});
    try {
      const r = await fetch('/api/harness/connect', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({cwd, resume: resume || ''})});
      const j = await r.json();
      if (!j.ok) {
        if (j.err && j.err.includes('未检测到 claude')) { notifyTaskDone(nid, {ok:false, title:'claude 未安装', detail:'已弹安装引导'}); openClaudeSetup(); return; }
        notifyTaskDone(nid, {ok:false, title:'Claude 对话启动失败', detail:j.err || '未知错误', ms:6000});
        renderRaw('⚠ ' + (j.err || '启动失败'));
        return;
      }
      conn.backendId = j.port_id;
      conn.seq = 0;
      conn.meta.cwd = j.cwd;
      wrap.querySelector('[data-h-cwd]').textContent = (j.cwd || '').split(/[\\\\/]/).pop() || '~';
      setState('启动中…', false);
      connectSSE(j.port_id, 0);
      notifyTaskDone(nid, {ok:true, title:'Claude 对话已启动', detail: j.cwd});
      refreshSidebar();
      input.focus();
    } catch(e) {
      notifyTaskDone(nid, {ok:false, title:'Claude 对话启动请求失败', detail:String(e), ms:6000});
    }
  }

  // ---- 发送 ----
  async function send() {
    const text = input.value.trim();
    if (!text) return;
    if (!conn.backendId) { showBanner('会话未启动', 2500, true); return; }
    if (conn.busy) { showBanner('claude 正在回复中，请稍候', 2500, true); return; }
    input.value = '';
    input.style.height = 'auto';
    try {
      const r = await fetch('/api/harness/send', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({port_id: conn.backendId, text})});
      const j = await r.json();
      if (!j.ok) {
        input.value = text;   // 失败退回输入框
        showBanner(j.err || '发送失败', 3000, true);
        return;
      }
      setState('思考中…', true);   // user_echo 到 SSE 后渲染；result 事件后回就绪
    } catch(e) {
      input.value = text;
      showBanner('发送失败：' + e, 3000, true);
    }
  }

  // ---- 控件绑定 ----
  sendBtn.onclick = send;
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 140) + 'px';
  });
  wrap.querySelector('[data-h-new]').onclick = () => {
    // 新会话：不动后端旧进程（旧会话进程随 tab 关闭回收），直接重开
    flow.innerHTML = '';
    conn.backendId = null;
    conn.seq = 0;
    if (conn.sse) { try { conn.sse.close(); } catch(_) {} conn.sse = null; }
    startSession('');
  };
  wrap.querySelector('[data-h-clear]').onclick = () => { flow.innerHTML = ''; };
  conn.onResumePoll = () => { input.focus(); };   // switchTab 切回时聚焦输入框

  startSession(opts.resume || '');
  return conn;
}

// ---- 关闭 tab：清 SSE + 通知后端回收会话进程 ----
function _harnessClose(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (conn.sse) { try { conn.sse.close(); } catch(_) {} }
  if (conn.backendId) {
    fetch('/api/harness/disconnect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({port_id: conn.backendId})}).catch(() => {});
  }
  if (conn._pollTimer) { clearInterval(conn._pollTimer); conn._pollTimer = null; }
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

// ---- 顶栏 Claude 按钮分派（init.js 调用）：按设置走 harness 或 CLI ----
let _claudeUiMode = null;   // null=未拉取
async function _getClaudeUiMode() {
  if (_claudeUiMode === null) {
    try {
      const j = await (await fetch('/api/theme')).json();
      _claudeUiMode = (j.ok && j.claude_ui_mode) ? j.claude_ui_mode : 'harness';
    } catch(_) { _claudeUiMode = 'harness'; }
  }
  return _claudeUiMode;
}
function setClaudeUiMode(m) { _claudeUiMode = m; }   // 设置页保存后同步内存缓存

async function claudeButtonAction() {
  const mode = await _getClaudeUiMode();
  if (mode === 'cli') connectClaude();
  else buildClaudeHarnessTab({});
}
