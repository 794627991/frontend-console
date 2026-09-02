// ============================================================
// 文本编辑器（v0.6.20）：files/ 目录下的多文档 tab 编辑器
// 设计参考（Notepad++）：多文档 tab、标题 * 脏标记、Ctrl+S 保存、
// Ctrl+Shift+S 另存为、关闭未保存确认、行列/字数状态栏。
// 引擎取舍（调研 CodeMirror/Monaco）：纯文本场景 textarea + 原生 undo
// 已够用，零依赖不引重型编辑器引擎。
// 后端：src/editor_files.py（/api/ed/*），文件存 <工具目录>/files/
//
// 保存模型：新建文件只建草稿 tab（标题「未命名」），不在磁盘落文件；
// Ctrl+S 时若为草稿/另存为则要求文件名 → 首次保存才真正写盘。
// （用户要求：创建 ≠ 保存）
// ============================================================

// ---- 编辑器 tab 构建（模式同 buildLogViewer：tab + term-area wrap + connections 表）----
// name=null 表示未命名草稿（尚未保存到磁盘）
function buildEditorTab(name, text) {
  // 已打开同名文件 → 切过去
  if (name) {
    for (const pid in connections) {
      const c = connections[pid];
      if (c && c.meta && c.meta.kind === 'editor' && c.meta.label === name) {
        switchTab(pid); return;
      }
    }
  }
  const portId = 'edit:' + (name || 'draft') + ':' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led" style="color:var(--accent)">📝</span><span class="label">${esc(name || '未命名')}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };
  // 双击 tab 标题 → 快捷改名（Notepad++ 式）
  tab.querySelector('.label').ondblclick = (e) => { e.stopPropagation(); edRenamePrompt(connections[portId]); };
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
        <button class="lv-btn" data-ed-action="rename" title="双击标签页标题可快捷改名">重命名</button>
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
    meta: { kind: 'editor', label: name || '未命名' },
    tab, wrap,
    ta: wrap.querySelector('.editor-area'),
    infoEl: wrap.querySelector('[data-ed-info]'),
    savedText: text,      // 上次保存/打开时的内容（脏检测基准）
    onDisk: !!name,       // 是否已落盘（草稿 false：关闭即丢弃，改名=另存为）
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
      else if (act === 'rename') edRenamePrompt(conn);
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
  const state = !conn.onDisk ? ' · 未保存到磁盘' : (conn.dirty ? ' · 未保存' : ' · 已保存');
  conn.infoEl.textContent = `行 ${line}，列 ${col} · ${conn.ta.value.length} 字符${state}`;
}

// ---- 打开已有文件 ----
async function openEditorFile(name) {
  try {
    const r = await fetch('/api/ed/open?name=' + encodeURIComponent(name));
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '打开失败', true); return; }
    buildEditorTab(name, j.text);
  } catch(e) { showBanner('打开失败: ' + e, true); }
}

// ---- 保存：草稿/未落盘 → 先问名（同另存为）；已落盘 → 覆盖保存 ----
async function edSave(conn) {
  if (!conn.onDisk) return edSaveAs(conn);
  try {
    const r = await fetch('/api/ed/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: conn.meta.label, text: conn.ta.value})});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '保存失败', true); return; }
    conn.savedText = conn.ta.value;
    conn.dirty = false; _edMarkTab(conn); _edUpdateInfo(conn);
    showBanner('已保存 ' + conn.meta.label, false, 1500);
  } catch(e) { showBanner('保存失败: ' + e, true); }
}

// ---- 另存为：输入新名（后端生成不冲突默认名预填），保存后 tab 改名并标记已落盘 ----
async function edSaveAs(conn) {
  let def = conn.meta.label;
  if (!conn.onDisk) {
    try {
      const r = await fetch('/api/ed/default_name');
      const j = await r.json();
      if (j.ok) def = j.name;
    } catch(e) {}
  }
  const nn = prompt('文件名（保存到 files/ 目录）：', def);
  if (!nn) return;
  try {
    const r = await fetch('/api/ed/save_as', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({new_name: nn.trim(), text: conn.ta.value})});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '另存为失败', true); return; }
    conn.meta.label = j.name;
    conn.savedText = conn.ta.value;
    conn.onDisk = true;
    conn.dirty = false; _edMarkTab(conn); _edUpdateInfo(conn);
    showBanner('已保存 ' + j.name, false, 1500);
  } catch(e) { showBanner('另存为失败: ' + e, true); }
}

// ---- 改名入口（工具栏按钮 / 双击 tab 标题共用）----
// 草稿：改名 = 直接定名保存（未落盘时这是最自然的路径）
function edRenamePrompt(conn) { return conn.onDisk ? edRename(conn) : edSaveAs(conn); }

// ---- 重命名已落盘文件（不改内容）----
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

// ---- 删除（已落盘才有东西可删；脏内容一并丢，双重确认）----
async function edDelete(conn) {
  if (conn.onDisk) {
    if (!confirm(`确定删除「${conn.meta.label}」？此操作不可恢复。`)) return;
    try {
      const r = await fetch('/api/ed/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: conn.meta.label})});
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '删除失败', true); return; }
    } catch(e) { showBanner('删除失败: ' + e, true); return; }
  }
  _edCloseNow(conn);
  showBanner('已删除', false, 1500);
}

// ---- 关闭 tab：脏则确认（确定=丢弃修改直接关，取消=留在编辑器）----
function closeEditorTab(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (conn.dirty) {
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

// ---- 新建文件：只建草稿 tab，不落盘（首次 Ctrl+S / 双击改名时才写文件）----
function newEditorFile() {
  buildEditorTab(null, '');
}

// ---- files/ 文件列表弹窗：复用日志库 modal 风格（.modal .box + .item/.act-btn）----
async function showFilesModal() {
  let modal = $('filesModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'filesModal';
    modal.innerHTML = `
      <div class="box">
        <div class="head">
          <strong>📝 文本文件</strong>
          <div class="head-actions">
            <button class="btn ghost" id="filesNew" title="新建文本（不落盘，保存时才写文件）">＋ 新建文本</button>
            <button class="btn ghost icon-btn" id="filesOpenDir" title="在资源管理器中打开 files/ 目录">📁</button>
            <button class="btn ghost icon-btn" id="filesClose">✕</button>
          </div>
        </div>
        <div class="list" id="filesList" style="max-height:60vh;"></div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#filesClose').onclick = () => modal.classList.remove('show');
    modal.querySelector('#filesOpenDir').onclick = () => fetch('/api/ed/open_dir', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'});
    modal.querySelector('#filesNew').onclick = () => { modal.classList.remove('show'); newEditorFile(); };
  }
  modal.classList.add('show');
  const listEl = modal.querySelector('#filesList');
  listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">加载中…</div>';
  try {
    const r = await fetch('/api/ed/list');
    const j = await r.json();
    if (!j.ok) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">加载失败</div>'; return; }
    if (!j.files.length) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">暂无文件，点击「新建文本」创建</div>'; return; }
    listEl.innerHTML = '';
    j.files.forEach(f => {
      const d = document.createElement('div');
      d.className = 'item';
      const dt = new Date(f.mtime*1000);
      const kb = f.size >= 1024 ? (f.size/1024).toFixed(1) + ' KB' : f.size + ' B';
      d.innerHTML = `<span>${esc(f.name)}<br><span class="sz">${dt.toLocaleString('zh-CN')} · ${kb}</span></span>
        <span class="item-actions">
          <span class="act-btn open" data-open="${esc(f.name)}" title="打开编辑此文件">✎ 编辑</span>
        </span>`;
      d.onclick = () => { modal.classList.remove('show'); openEditorFile(f.name); };
      d.querySelector('[data-open]').onclick = (ev) => { ev.stopPropagation(); modal.classList.remove('show'); openEditorFile(f.name); };
      listEl.appendChild(d);
    });
  } catch(e) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">加载失败: ' + esc(String(e)) + '</div>'; }
}
