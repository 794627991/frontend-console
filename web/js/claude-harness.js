// ============================================================
// Claude Harness 界面化会话 v2（微信式多会话）。
// 与内嵌终端（claude.js connectClaude，ConPTY xterm 保真）平行的另一条
// 通道：后端 src/claude_harness.py spawn `claude -p --input/output-format
// stream-json`，NDJSON 事件原样透传，本文件负责全部渲染与会话管理
// （分层照 sugyan/claude-code-webui：后端薄透传、前端厚渲染）。
// v2 形态（对齐 ClaudeDesktop 截图）：左侧栏（新建/搜索/会话列表）+
// 中间气泡会话流 + 底部输入卡（附件/技能/模型 chips + 发送/停止）。
// 单例 tab：顶栏 Claude 只开一个本 tab，内部自由切换多会话；
// 会话元数据/上下文由后端持久化（~/.serialconsole_pro + --resume）。
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
      for (const k in i) { if (typeof i[k] === 'string' && i[k]) return `${k}=${i[k].slice(0, 60)}`; }
      return '';
    }
    if (typeof i.cmd === 'string') return i.cmd;
    return '';
  } catch(_) { return ''; }
}

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

// ---- 组件状态（模块级，tab 关闭即弃；会话本体在后端）----
const _HG = {
  conn: null,          // connections 里的 harness tab conn
  sid: null,           // 当前会话 sid（null=欢迎页/未建）
  dirty: false,        // 当前会话是否已发过消息（模型切换需新会话）
  model: null,         // 待用模型（新会话生效；空会话可即时换）
  models: null,        // {models:[], default} 拉取缓存
  skills: null, skillsCwd: null,
  sessions: [],        // /sessions 列表缓存
  seq: 0,              // SSE 游标（当前会话）
  cache: {},           // sid -> {html, seq} 气泡 DOM 快照（切回免重拉）
  sse: null,
  busy: false, alive: false,
  atts: [],            // 待发附件 [{name,path,size,isImg}]
  pendingFiles: null,  // 待上传的原生文件对象（file input / paste）
  pop: null,           // 当前打开的 popover（'skill'|'model'|null）
};

// ---- tab 构建（单例骨架同 bit-calc：已开只切换）----
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
      </div>
      <div class="hg-main">
        <div class="hg-top">
          <span class="hg-title" data-hg-title>新会话</span>
          <span class="hg-cwd lv-btn" data-hg-cwd title="会话工作目录"></span>
          <span class="hg-flex1"></span>
          <span class="hg-top-state" data-hg-state></span>
        </div>
        <div class="hg-flow" data-hg-flow></div>
        <div class="hg-card-wrap">
          <div class="hg-atts" data-hg-atts style="display:none"></div>
          <div class="hg-input-card">
            <textarea class="hg-input" data-hg-input rows="1" placeholder="给 Claude 发消息，Enter 发送 · Shift+Enter 换行 · 可粘贴图片" spellcheck="false"></textarea>
            <div class="hg-card-foot">
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
  switchTab(portId);

  // ---- 元素引用 ----
  const q = (s) => wrap.querySelector(s);
  const flow = q('[data-hg-flow]'), input = q('[data-hg-input]'),
        stateEl = q('[data-hg-state]'), costEl = q('[data-hg-cost]'),
        sendBtn = q('[data-hg-send]'), titleEl = q('[data-hg-title]'),
        cwdEl = q('[data-hg-cwd]'), attsEl = q('[data-hg-atts]'),
        listEl = q('[data-hg-sessions]'), searchEl = q('[data-hg-search]'),
        fileEl = q('[data-hg-file]');

  // ---- 气泡渲染 ----
  function renderMd(text) {
    const md = _harnessMdInstance();
    if (md) {
      const html = md.render(text || '');
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
  function attChipsHtml(images, files) {
    let h = '';
    (images || []).forEach(p => { h += `<span class="hg-att-mini">🖼 ${esc(String(p).split(/[\\/]/).pop())}</span>`; });
    (files || []).forEach(p => { h += `<span class="hg-att-mini">📄 ${esc(String(p).split(/[\\/]/).pop())}</span>`; });
    return h;
  }
  function addBubble(role, inner, cls) {
    const d = document.createElement('div');
    d.className = 'h-msg ' + role + (cls ? ' ' + cls : '');
    d.innerHTML = inner;
    flow.appendChild(d);
    flow.scrollTop = flow.scrollHeight;
    return d;
  }
  const renderUser = (text, images, files) => {
    hideWelcome();
    addBubble('user', `<div class="h-bubble">${(images?.length || files?.length) ? `<div class="hg-bubble-atts">${attChipsHtml(images, files)}</div>` : ''}${renderMd(text || '')}</div>`);
  };
  const renderAsst = (text, isSub) => {
    if (!text) return;
    hideWelcome();
    addBubble('asst', `<div class="h-bubble">${renderMd(text)}</div>`, isSub ? 'sub' : '');
  };
  const renderTool = (name, summary, isSub) => {
    hideWelcome();
    const d = document.createElement('div');
    d.className = 'h-tool' + (isSub ? ' sub' : '');
    d.innerHTML = `<span class="h-tool-name">${esc(name)}</span><span class="h-tool-arg">${esc(summary)}</span>`;
    flow.appendChild(d);
    flow.scrollTop = flow.scrollHeight;
  };
  const renderRaw = (text) => {
    const d = document.createElement('div'); d.className = 'h-raw'; d.textContent = text;
    flow.appendChild(d); flow.scrollTop = flow.scrollHeight;
  };
  const renderExit = (text) => {
    const d = document.createElement('div'); d.className = 'h-exit'; d.textContent = text;
    flow.appendChild(d); flow.scrollTop = flow.scrollHeight;
  };
  function hideWelcome() {
    const w = flow.querySelector('.hg-welcome');
    if (w) w.remove();
  }
  function showWelcome() {
    flow.innerHTML = `
      <div class="hg-welcome">
        <div class="hg-welcome-ico"><span class="claude-ico big"></span></div>
        <div class="hg-welcome-title">你好，我是 Claude</div>
        <div class="hg-welcome-desc">直接输入开始新对话，或从左侧选择历史会话继续。<br>支持 📎 附件、⚡ 技能（/命令）、🧠 模型切换。</div>
      </div>`;
  }

  function setBusy(b) {
    _HG.busy = b;
    conn.tab.querySelector('.led').classList.toggle('on', b);
    sendBtn.classList.toggle('stop', b);
    sendBtn.textContent = b ? '■' : '➤';
    sendBtn.title = b ? '停止生成' : '发送（Enter）';
    stateEl.textContent = b ? '思考中…' : (_HG.alive ? '就绪' : '');
  }

  // ---- CLI 事件 → 渲染（同 v1 分流）----
  function handleEvent(o) {
    const typ = o.type;
    if (typ === 'system') {
      const sub = o.subtype;
      if (sub === 'init') {
        _HG.alive = true;
        if (!_HG.busy) setBusy(false);
      } else if (sub === 'api_error' || sub === 'error') {
        renderRaw('⚠ ' + (o.error ? JSON.stringify(o.error).slice(0, 200) : JSON.stringify(o).slice(0, 200)));
      }
    } else if (typ === 'assistant') {
      const blocks = (o.message || {}).content || [];
      const isSub = !!o.parent_tool_use_id;
      for (const b of blocks) {
        if (b.type === 'text' && b.text) {
          if (isSub) renderAsst('[子代理] ' + b.text, true);
          else renderAsst(b.text);
        } else if (b.type === 'tool_use') {
          renderTool(b.name, _harnessToolSummary(b.name, b.input), isSub);
        }
      }
      flow.scrollTop = flow.scrollHeight;
    } else if (typ === 'user') {
      if (!o.isSynthetic && o.parent_tool_use_id) {
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
      costEl.textContent = `完成 · ${o.num_turns || 1} 轮${typeof cost === 'number' ? ' · $' + cost.toFixed(4) : ''}`;
      setBusy(false);
      if (o.subtype && o.subtype !== 'success')
        renderRaw(`⚠ 回复异常结束：${o.subtype}${o.result ? ' — ' + String(o.result).slice(0, 200) : ''}`);
      refreshSessions();
    }
  }

  // ---- SSE（当前会话唯一一条；切会话先关旧的）----
  function openSSE(sid, afterSeq) {
    if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
    if (!sid) return;
    const es2 = new EventSource(`/api/harness/stream?sid=${encodeURIComponent(sid)}&after_seq=${afterSeq || 0}`);
    _HG.sse = es2;
    es2.onmessage = (ev) => {
      let it;
      try { it = JSON.parse(ev.data); } catch(_) { return; }
      if (it.seq && it.seq > _HG.seq) _HG.seq = it.seq;
      if (it.kind === 'user_echo') { renderUser(it.text, it.images, it.files); setBusy(true); }
      else if (it.kind === 'event') handleEvent(it.data);
      else if (it.kind === 'raw') renderRaw(it.text);
      else if (it.kind === 'interrupted') { renderExit(it.text); setBusy(false); }
      else if (it.kind === 'exit') { _HG.alive = false; renderExit(it.text); setBusy(false); }
    };
    // onerror：EventSource 自动重连；重连由 after_seq 语义保障不重放已渲染部分
  }

  // ---- 会话切换 ----
  function saveCache() {
    if (_HG.sid) _HG.cache[_HG.sid] = { html: flow.innerHTML, seq: _HG.seq };
  }
  async function switchTo(sid, keepInput) {
    if (sid === _HG.sid && flow.querySelector('.h-msg, .hg-welcome')) return;
    saveCache();
    closePop();
    _HG.sid = sid; _HG.seq = 0; _HG.alive = false;
    if (!sid) _HG.dirty = false;   // 欢迎页=新会话，模型可即时切换
    clearAtts();
    costEl.textContent = '';
    if (!sid) {   // 欢迎页（未建会话）
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
      setBusy(false);   // 缓存快照不自带 busy 态；真 busy 由 SSE 回放 result 前事件再点亮
    } else {
      flow.innerHTML = '';
      try {
        const j = await (await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)).json();
        if (j.ok && _HG.sid === sid) {
          _HG.seq = j.seq || 0; _HG.alive = !!j.alive;
          if (!j.lines.length) showWelcome();
          else j.lines.forEach(l => {
            if (l.role === 'user') {
              const imgs = (l.files || []).filter(p => _HARNESS_IMG_EXT.test(p));
              const files = (l.files || []).filter(p => !_HARNESS_IMG_EXT.test(p));
              renderUser(l.text, imgs.length ? imgs : (l.images ? Array.from({ length: l.images }, (_, i) => '图片' + (i + 1)) : null), files);
            }
            else if (l.role === 'assistant') renderAsst(l.text);
            else if (l.role === 'tool') renderTool(l.text, l.summary || '');
          });
          setBusy(!!j.busy);
        }
      } catch(_) {}
    }
    const s = _HG.sessions.find(x => x.sid === sid);
    titleEl.textContent = (s && s.title) || '会话';
    cwdEl.textContent = s ? (s.cwd || '').split(/[\\/]/).pop() : '';
    conn.meta.label = titleEl.textContent;
    conn.meta.cwd = (s && s.cwd) || '';
    conn.tab.querySelector('.label').textContent = titleEl.textContent;
    openSSE(sid, _HG.seq);
    renderList();
    refreshSidebar();
    if (!keepInput) input.focus();
  }

  // ---- 会话列表 ----
  async function refreshSessions() {
    try {
      const j = await (await fetch('/api/harness/sessions')).json();
      if (j.ok) { _HG.sessions = j.sessions || []; renderList(); }
    } catch(_) {}
  }
  function renderList() {
    const kw = (searchEl.value || '').trim().toLowerCase();
    const items = _HG.sessions.filter(s => !kw || (s.title || '').toLowerCase().includes(kw));
    listEl.innerHTML = items.map(s => `
      <div class="hg-item${s.sid === _HG.sid ? ' active' : ''}" data-sid="${esc(s.sid)}" title="${esc(s.cwd || '')}">
        <div class="hg-item-row">
          <span class="hg-item-title">${esc(s.title || '新会话')}</span>
          <span class="hg-item-time">${_harnessRelTime(s.last_active)}</span>
        </div>
        <div class="hg-item-row">
          <span class="hg-item-sub">${esc((s.cwd || '').split(/[\\/]/).pop() || '~')}${s.model ? ' · ' + esc(s.model) : ''}</span>
          <span class="hg-item-acts">
            ${s.busy ? '<span class="hg-item-busy" title="回复中">●</span>' : ''}
            <button class="hg-item-act" data-act="rename" data-sid="${esc(s.sid)}" title="重命名">✎</button>
            <button class="hg-item-act del" data-act="del" data-sid="${esc(s.sid)}" title="删除会话">✕</button>
          </span>
        </div>
      </div>`).join('') || '<div class="hg-list-empty">暂无会话</div>';
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

  // ---- 新建 / 发送（新会话延迟建连：发出首条消息才 POST connect）----
  function newChat() {
    saveCache();
    switchTo(null);
  }
  q('[data-hg-new]').onclick = newChat;

  async function ensureSession() {
    if (_HG.sid) return _HG.sid;
    const r = await fetch('/api/harness/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model: _HG.model || ''})});
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
    input.value = ''; input.style.height = 'auto';
    costEl.textContent = '';
    clearAtts();
    try {
      const r = await fetch('/api/harness/send', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid, text, images, files})});
      const j = await r.json();
      if (!j.ok) {
        input.value = text;   // 失败退回输入框（附件 chip 已清，重试需重选——低概率路径取简单）
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
    try {
      await fetch('/api/harness/interrupt', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid})});
    } catch(_) {}
  }

  sendBtn.onclick = () => { _HG.busy ? stopGen() : send(); };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });

  // ---- 附件 ----
  function renderAtts() {
    if (!_HG.atts.length) { attsEl.style.display = 'none'; attsEl.innerHTML = ''; return; }
    attsEl.style.display = 'flex';
    attsEl.innerHTML = _HG.atts.map((a, i) => `
      <span class="hg-att-chip">${a.isImg ? '🖼' : '📄'} ${esc(a.name)}
        <button class="hg-att-x" data-i="${i}" title="移除">✕</button></span>`).join('');
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
  // 粘贴图片（textarea 聚焦时；不碰全局拖拽链路，铁律4）
  input.addEventListener('paste', (e) => {
    const fs = [...(e.clipboardData?.files || [])].filter(f => f && f.size);
    if (fs.length) { e.preventDefault(); uploadFiles(fs); }
  });

  // ---- popover（技能/模型）----
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
      closePop(); input.focus(); return;
    }
    const mi = e.target.closest('[data-model]');
    if (mi) {
      const m = mi.dataset.model;
      _HG.model = m;
      q('[data-hg-model]').innerHTML = '🧠 ' + esc(m) + ' ▾';
      if (!_HG.dirty) {
        // 空会话直接重挂：把所选 model 应用到下一次建连（未 connect 则无副作用）
        if (_HG.sid) {   // 已 connect 的空会话（极少见：connect 后没发过消息）→ 弃用重开
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

  // ---- 轻量模态（铁律2：禁原生 confirm/prompt，暗色同款）----
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

  // ---- 初始：拉会话列表，自动回到最近会话 ----
  showWelcome();
  (async () => {
    await refreshSessions();
    const last = _HG.sessions.find(s => s.has_history);
    if (last) switchTo(last.sid);
    else input.focus();
  })();
  return conn;
}

// ---- 关闭 tab：只断 SSE（会话本体后端保留，闲置自动回收进程；重开可继续）----
function _harnessClose(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
  _HG.conn = null; _HG.sid = null; _HG.cache = {};
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
