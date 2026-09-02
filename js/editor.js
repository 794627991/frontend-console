// ============================================================
// 文本编辑器（v0.6.20）：files/ 目录下的多文档 tab 编辑器
// 设计参考（Notepad++）：多文档 tab、标题 * 脏标记、Ctrl+S 保存、
// Ctrl+Shift+S 另存为、关闭未保存确认、行列/字数状态栏。
// 引擎取舍（调研 CodeMirror/Monaco）：纯文本场景 textarea + 原生 undo
// 已够用，零依赖不引重型编辑器引擎。
// 后端：src/editor_files.py（/api/ed/*），文件存 <工具目录>/files/
// ============================================================

// ---- 编辑器 tab 构建（模式同 buildLogViewer：tab + term-area wrap + connections 表）----
function buildEditorTab(name, text) {
  // 已打开同名文件 → 切过去
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'editor' && c.meta.label === name) {
      switchTab(pid); return;
    }
  }
  const portId = 'edit:' + name + ':' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led" style="color:var(--accent)">📝</span><span class="label">${esc(name)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };
  // wrap（.term-area 内含编辑器）
  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-ed-action="save" title="Ctrl+S">💾 保存</button>
        <button class="lv-btn" data-ed-action="saveas" title="Ctrl+Shift+S">另存为…</button>
        <button class="lv-btn" data-ed-action="rename">重命名</button>
        <button class="lv-btn" data-ed-action="delete">删除</button>
        <span class="lv-info" data-ed-info></span>
      </div>
      <textarea class="editor-area" spellcheck="false" wrap="off"></textarea>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  termArea.appendChild(wrap);
  const conn = {
    portId,
    meta: { kind: 'editor', label: name },
    tab, wrap,
    ta: wrap.querySelector('.editor-area'),
    infoEl: wrap.querySelector('[data-ed-info]'),
    savedText: text,      // 上次保存/打开时的内容（脏检测基准）
    dirty: false,
  };
  connections[portId] = conn;
  conn.ta.value = text;
  _edUpdateInfo(conn);
  // 输入 → 脏标记 + 状态栏刷新
  conn.ta.addEventListener('input', () => {
    const dirty = conn.ta.value !== conn.savedText;
    if (dirty !== conn.dirty) { conn.dirty = dirty; _edMarkTab(conn); }
    _edUpdateInfo(conn);
  });
  // 光标移动 → 行列刷新
  conn.ta.addEventListener('keyup', () => _edUpdateInfo(conn));
  conn.ta.addEventListener('click', () => _edUpdateInfo(conn));
  // 快捷键：Ctrl+S 保存 / Ctrl+Shift+S 另存为（编辑器聚焦时 textarea 的 keydown 捕获）
  conn.ta.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (e.shiftKey) edSaveAs(conn);
      else edSave(conn);
    }
  });
  // 工具栏按钮
  wrap.querySelectorAll('.lv-btn').forEach(btn => {
    btn.onclick = () => {
      const act = btn.dataset.edAction;
      if (act === 'save') edSave(conn);
      else if (act === 'saveas') edSaveAs(conn);
      else if (act === 'rename') edRename(conn);
      else if (act === 'delete') edDelete(conn);
    };
  });
  switchTab(portId);
  conn.ta.focus();
  return conn;
}

// ---- 脏标记：tab 标题加 *（Notepad++ 风格）----
function _edMarkTab(conn) {
  conn.tab.querySelector('.label').textContent = (conn.dirty ? '*' : '') + conn.meta.label;
}

// ---- 状态栏：行列 + 字符数 ----
function _edUpdateInfo(conn) {
  const pos = conn.ta.selectionStart;
  const before = conn.ta.value.slice(0, pos);
  const line = before.split('\n').length;
  const col = pos - (before.lastIndexOf('\n') + 1) + 1;
  conn.infoEl.textContent = `行 ${line}，列 ${col} · ${conn.ta.value.length} 字符${conn.dirty ? ' · 未保存' : ''}`;
}

// ---- 打开文件（新建走 /api/ed/new 后也进这里）----
async function openEditorFile(name) {
  try {
    const r = await fetch('/api/ed/open?name=' + encodeURIComponent(name));
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '打开失败', true); return; }
    buildEditorTab(name, j.text);
  } catch(e) { showBanner('打开失败: ' + e, true); }
}

// ---- 保存 ----
async function edSave(conn) {
  try {
    const r = await fetch('/api/ed/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: conn.meta.label, text: conn.ta.value})});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '保存失败', true); return; }
    conn.savedText = conn.ta.value;
    conn.dirty = false; _edMarkTab(conn); _edUpdateInfo(conn);
    showBanner('已保存 ' + conn.meta.label, false, 1500);
  } catch(e) { showBanner('保存失败: ' + e, true); }
}

// ---- 另存为：输入新名（默认带原文件名），保存后 tab 改名 ----
async function edSaveAs(conn) {
  const nn = prompt('另存为（files/ 目录下的新文件名）：', conn.meta.label);
  if (!nn) return;
  try {
    const r = await fetch('/api/ed/save_as', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({new_name: nn.trim(), text: conn.ta.value})});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '另存为失败', true); return; }
    conn.meta.label = j.name;
    conn.savedText = conn.ta.value;
    conn.dirty = false; _edMarkTab(conn); _edUpdateInfo(conn);
    showBanner('已另存为 ' + j.name, false, 1500);
  } catch(e) { showBanner('另存为失败: ' + e, true); }
}

// ---- 重命名（不改内容）----
async function edRename(conn) {
  const nn = prompt('重命名文件：', conn.meta.label);
  if (!nn) return;
  try {
    const r = await fetch('/api/ed/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({old: conn.meta.label, new: nn.trim()})});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '重命名失败', true); return; }
    conn.meta.label = j.name;
    _edMarkTab(conn); _edUpdateInfo(conn);
    showBanner('已重命名为 ' + j.name, false, 1500);
  } catch(e) { showBanner('重命名失败: ' + e, true); }
}

// ---- 删除（脏内容一并丢，双重确认）----
async function edDelete(conn) {
  if (!confirm(`确定删除「${conn.meta.label}」？此操作不可恢复。`)) return;
  try {
    const r = await fetch('/api/ed/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: conn.meta.label})});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '删除失败', true); return; }
  } catch(e) { showBanner('删除失败: ' + e, true); return; }
  _edCloseNow(conn);
  showBanner('已删除', false, 1500);
}

// ---- 关闭 tab：脏则确认（不保存/保存/取消）----
function closeEditorTab(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (conn.dirty) {
    // 简洁三选：确认框「确定」=丢弃修改直接关，「取消」=留在编辑器
    if (!confirm(`「${conn.meta.label}」有未保存的修改，关闭将丢失。确定关闭？`)) return;
  }
  _edCloseNow(conn);
}
function _edCloseNow(conn) {
  conn.tab.remove(); conn.wrap.remove();
  delete connections[conn.portId];
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0;
  });
  if (remaining.length) switchTab(remaining[0]);
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon">📡</div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
}

// ---- 新建文件按钮：后端建空文件 → 开编辑 tab ----
async function newEditorFile() {
  try {
    const r = await fetch('/api/ed/new', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '新建失败', true); return; }
    buildEditorTab(j.name, '');
  } catch(e) { showBanner('新建失败: ' + e, true); }
}

// ---- files/ 文件列表弹窗：打开已有文件 ----
async function showFilesModal() {
  // 复用日志库 modal 的外壳样式（#filesModal 动态建，不占 index.html）
  let modal = $('filesModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.className = 'modal conn-modal';
    modal.id = 'filesModal';
    modal.innerHTML = `
      <div class="box">
        <div class="head">
          <strong>文本文件（files/）</strong>
          <button class="btn ghost icon-btn" id="filesClose">✕</button>
        </div>
        <div id="filesList" style="max-height:400px;overflow-y:auto;padding:8px;"></div>
        <div class="actions" style="padding:8px;">
          <button class="btn ghost" id="filesOpenDir">📁 打开目录</button>
          <button class="btn primary" id="filesNew">＋ 新建文本</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#filesClose').onclick = () => modal.classList.remove('show');
    modal.querySelector('#filesOpenDir').onclick = () => fetch('/api/ed/open_dir', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'});
    modal.querySelector('#filesNew').onclick = () => { modal.classList.remove('show'); newEditorFile(); };
  }
  modal.classList.add('show');
  const listEl = modal.querySelector('#filesList');
  listEl.innerHTML = '<div style="color:var(--muted);padding:10px;">加载中…</div>';
  try {
    const r = await fetch('/api/ed/list');
    const j = await r.json();
    if (!j.ok) { listEl.innerHTML = '<div style="color:var(--muted);padding:10px;">加载失败</div>'; return; }
    if (!j.files.length) { listEl.innerHTML = '<div style="color:var(--muted);padding:10px;">暂无文件，点击「新建文本」创建</div>'; return; }
    listEl.innerHTML = j.files.map(f => {
      const kb = f.size >= 1024 ? (f.size/1024).toFixed(1) + 'KB' : f.size + 'B';
      const mt = new Date(f.mtime*1000).toLocaleString('zh-CN', {hour12:false});
      return `<div class="file-item" data-ed-name="${esc(f.name)}" style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border);cursor:pointer;">
        <span>📄</span><span style="flex:1">${esc(f.name)}</span>
        <span style="color:var(--muted);font-size:11px;">${kb}</span>
        <span style="color:var(--muted);font-size:11px;">${mt}</span></div>`;
    }).join('');
    listEl.querySelectorAll('.file-item').forEach(item => {
      item.onclick = () => { modal.classList.remove('show'); openEditorFile(item.dataset.edName); };
    });
  } catch(e) { listEl.innerHTML = '<div style="color:var(--muted);padding:10px;">加载失败: ' + esc(String(e)) + '</div>'; }
}
