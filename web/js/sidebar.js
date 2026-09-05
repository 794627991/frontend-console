async function loadPorts() {
  try {
    const r = await fetch('/api/ports');
    const j = await r.json();
    const connPort = $('connPort');
    connPort.innerHTML = '';
    if (!j.ports.length) {
      connPort.innerHTML = '<option value="">（无可用串口）</option>';
      return;
    }
    j.ports.forEach(p => {
      const o = document.createElement('option');
      o.value = p.device;
      o.textContent = `${p.device} — ${p.description}`;
      connPort.appendChild(o);
    });
    const connBaud = $('connBaud');
    connBaud.innerHTML = '';
    (j.bauds || [115200]).forEach(b => {
      const o = document.createElement('option');
      o.value = b; o.textContent = b;
      if (b === 115200) o.selected = true;
      connBaud.appendChild(o);
    });
  } catch(e) {}
}

// 返回后端 j（{ok, err}）；失败不再右下角弹泡——由连接弹窗内联显示，
// 成功才由调用方关弹窗。异常统一转 {ok:false, err}。
async function _recentAdd(item) {
  // 记录最近打开（失败静默——列表是辅助功能，不能阻塞连接流程）。
  // 后端响应带去重后的最新列表，直接同步进 _recentList 再渲染——
  // 之前渲染的是本地旧数组，导致"打开后不显示、重启才显示"。
  try {
    const r = await fetch('/api/recent', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(item)});
    const j = await r.json();
    if (j.ok && Array.isArray(j.recent)) _recentList = j.recent;
    renderRecentList();
  } catch(e) {}
}
async function connectPort(port, baud) {
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'serial', port, baud})});
    const j = await r.json();
    if (j.ok) {
      showBanner(`已连接 ${port}@${baud}`);
      const conn = buildTerminal(port, {kind:'serial', baud, label:port});
      connections[port] = conn;
      switchTab(port);
      refreshSidebar();
      refreshGlobalStatus();
      _recentAdd({type:'serial', key:'serial:'+port, label:`${port} @${baud}`, data:{port, baud}});
    }
    return j;
  } catch(e) { return {ok: false, err: '连接请求失败：' + e}; }
}

async function connectSSH(host, port, username, password, key_path) {
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'ssh', host, port, username, password, key_path})});
    const j = await r.json();
    if (j.ok) {
      const port_id = j.port_id;
      showBanner(`已连接 ${username}@${host}:${port}`);
      const conn = buildTerminal(port_id, {kind:'ssh', label:`${username}@${host}`, host, user:username});
      connections[port_id] = conn;
      switchTab(port_id);
      refreshSidebar();
      refreshGlobalStatus();
      // 密码随记录保存（本机工具、用户明确要求保存账号密码），快捷重开免重输
      _recentAdd({type:'ssh', key:`ssh:${host}:${port}:${username}`, label:`${username}@${host}:${port}`,
                  data:{host, port, username, password: password || '', key_path: key_path || ''}});
    }
    return j;
  } catch(e) { return {ok: false, err: 'SSH 连接请求失败：' + e}; }
}

function closeConnection(portId) {
  fetch('/api/disconnect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId})});
  const conn = connections[portId];
  if (conn) {
    if (conn.sse) conn.sse.close();
    if (conn._webgl) { try { conn._webgl.dispose(); } catch(e){} }  // 释放 GPU 资源
    if (conn.term) { try { conn.term.dispose(); } catch(e){} }
    // 微批发送的 pending 定时器清理（防关闭后误发）
    if (conn._sendTimer) { clearTimeout(conn._sendTimer); conn._sendTimer = null; }
    // 移除串口搜索分栏的 document 级监听器，避免泄漏
    if (conn.termSplitMove) document.removeEventListener('mousemove', conn.termSplitMove);
    if (conn.termSplitUp) document.removeEventListener('mouseup', conn.termSplitUp);
    conn.tab.remove();
    conn.wrap.remove();
    delete connections[portId];
  }
  // 切换到第一个可用标签（复用全局 sortKeyFn）
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
  });
  if (remaining.length) {
    switchTab(remaining[0]);
  } else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon">📡</div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();
  refreshGlobalStatus();
}

function refreshSidebar() {
  const ids = Object.keys(connections);
  $('portCount').textContent = ids.length;
  if (!ids.length) {
    if (_sidebarKey !== 'empty') {
      _sidebarKey = 'empty';
      portList.innerHTML = '<div class="empty-state" style="padding:30px 10px;"><div class="desc">点击「新建连接」或「新建笔记」添加内容</div></div>';
    }
    return;
  }
  // 排序：串口[0] < SSH[1] < 日志[2]（sortKeyFn 全局定义，closeConnection/closeLogViewer 复用）
  ids.sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
  });
  // 脏检查：连接集合 + active tab + 各 tab 标题 变化才重建整个列表 DOM；
  // 行数（每次刷新必变）只更新对应 span 文本，避免 5s 一次全量 innerHTML 重建叠加重排
  const key = ids.join('|') + '#' + activePortId + '#' + ids.map(pid => (connections[pid].meta && connections[pid].meta.label) || '').join('|');
  if (key !== _sidebarKey) {
    _sidebarKey = key;
    portList.innerHTML = '';
    ids.forEach(pid => {
      const conn = connections[pid];
      const item = document.createElement('div');
      item.className = 'port-item connected' + (pid === activePortId ? ' active' : '');
      item.dataset.portId = pid;
      const isSSH = conn.meta.kind === 'ssh';
      const isLog = conn.meta.kind === 'log';
      const isEdit = conn.meta.kind === 'editor' || conn.meta.kind === 'hex';
      const isClaude = conn.meta.kind === 'claude';
      const descText = isSSH ? `SSH · ${conn.meta.host || ''}` : isLog ? `📜 日志` : isEdit ? (conn.meta.kind === 'hex' ? `🔧 hex` : `📝 笔记`) : isClaude ? `🤖 Claude · ${(conn.meta.cwd || '').split(/[\\\\/]/).pop() || ''}` : `${conn.meta.baud || ''} baud`;
      const rowCount = conn.term ? conn.term.buffer.active.length : (conn.logState ? conn.logState.total : (isEdit ? _edStatText(conn) : 0));
      item.innerHTML = `
        <span class="led"></span>
        <div class="info">
          <div class="name">${esc(conn.meta.label || pid)}</div>
          <div class="desc">${esc(descText)} · <span class="baud" data-rows>${isEdit ? rowCount : rowCount + ' 行'}</span></div>
        </div>
        <div class="actions"><button data-close="${pid}" title="${isLog ? '关闭' : '断开'}">✕</button></div>
      `;
      item.onclick = (e) => {
        // hex 走 closeEditorTab（有脏确认）：落 closeConnection 会绕过
        // dirty 检查直接丢修改，还发一个必 404 的 /api/disconnect
        if (e.target.dataset.close) { e.stopPropagation(); (isLog ? closeLogViewer(pid) : isEdit ? closeEditorTab(pid) : closeConnection(pid)); return; }
        switchTab(pid);
      };
      portList.appendChild(item);
    });
  } else {
    // 只更新行数（轻量：改 textContent，不重建 DOM）。编辑器 tab 显示字符数
    ids.forEach(pid => {
      const el = portList.querySelector(`.port-item[data-port-id="${CSS.escape(pid)}"] [data-rows]`);
      if (!el) return;
      const conn = connections[pid];
      const isEdit = conn.meta && conn.meta.kind === 'editor';
      const n = isEdit ? _edStatText(conn)
        : conn.term ? conn.term.buffer.active.length
        : (conn.logState ? conn.logState.total : 0);
      const t = isEdit ? n : n + ' 行';
      if (el.textContent !== t) el.textContent = t;
    });
  }
  // 标签栏同序重排（复用全局 sortKeyFn）——当前顺序已一致时跳过，不动 DOM。
  // 用户手动拖过 tab（_tabOrderManual，tab-drag.js）后让位：不再自动重排，
  // 尊重用户顺序；全部 tab 关闭回到空态时重置（下次恢复默认排序）
  if (typeof _maybeResetTabOrder === 'function') _maybeResetTabOrder();
  if (typeof _tabOrderManual !== 'undefined' && _tabOrderManual) return;
  const tabEls = Array.from(tabs.querySelectorAll('.tab'));
  const curIds = tabEls.map(t => t.dataset.portId);
  const wantIds = ids.concat(curIds.filter(id => !connections[id]));
  const needSort = curIds.length !== wantIds.length || curIds.some((id, i) => id !== wantIds[i]);
  if (needSort) {
    tabEls.sort((a, b) => {
      const ka = sortKeyFn(a.dataset.portId), kb = sortKeyFn(b.dataset.portId);
      return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
    });
    const actions = tabs.querySelector('.tab-bar-actions');
    tabEls.forEach(t => tabs.insertBefore(t, actions));
  }
}
let _sidebarKey = '';

async function refreshGlobalStatus() {
  try {
    const r = await fetch('/api/status');
    const j = await r.json();
    const n = Object.keys(j.ports || {}).length;
    $('globalStatus').textContent = n + ' 个连接';
    $('globalDot').className = 'dot' + (n ? ' on' : '');
  } catch(e) {}
}

// ============================================================
// 键盘输入（v0.3.0：xterm 自带输入，cmdInput 隐藏框不再承载焦点；
// 这里仅保留全局快捷键：Ctrl+End 跳底、Ctrl+L 清屏等）
// ============================================================
document.addEventListener('keydown', (e) => {
  // Ctrl+F：日志 tab → 激活底部查找分栏并聚焦输入框
  if (e.ctrlKey && (e.key === 'f' || e.key === 'F') && activePortId) {
    const conn = connections[activePortId];
    if (conn && conn.meta && conn.meta.kind === 'log') {
      e.preventDefault();
      toggleLogSearchPane(conn, true);
      if (conn.searchInput.value) conn.searchInput.select();
      return;
    }
  }
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn) return;
  const pid = activePortId;
  // 只在 xterm 未获焦点时拦截这些全局快捷键，避免与 xterm 输入冲突
  if (e.ctrlKey && e.key === 'End') { e.preventDefault(); jumpToBottom(pid); return; }
});

async function loadHistory(portId) {
  try {
    const r = await fetch('/api/history?port_id=' + encodeURIComponent(portId));
    const j = await r.json();
    const conn = connections[portId];
    if (conn) conn.history = j.history || [];
  } catch(e) {}
}

// 点击终端区聚焦 xterm（但点击搜索分栏/输入框时不抢焦点，让用户能正常输入）
document.addEventListener('click', (e) => {
  if (!activePortId) return;
  // 点击落在搜索分栏内（输入框/结果列表/分隔条）→ 不抢焦点
  if (e.target.closest('.term-search-pane') || e.target.closest('.term-search-splitter')) return;
  if (e.target.closest('.output-wrap')) {
    const conn = connections[activePortId];
    if (conn) try { conn.term.focus(); } catch(err){}
  }
});

// ============================================================
// 顶栏按钮
// ============================================================
$('btnNewConn').onclick = async () => {
  await loadPorts();
  // 清掉上次连接的内联错误
  const errEl = $('connErr'); if (errEl) { errEl.classList.remove('show'); errEl.textContent = ''; }
  // 每次打开重置为默认（串口 + 密码认证），避免残留上次的 SSH/密钥选择
  _connType = 'serial'; _sshAuth = 'password';
  document.querySelectorAll('.conn-type-btn').forEach(b => b.classList.toggle('active', b.dataset.type === 'serial'));
  document.querySelectorAll('.conn-auth-btn').forEach(b => b.classList.toggle('active', b.dataset.auth === 'password'));
  // 注意：显示时必须设 'flex'（而非 ''）——两个字段块是 flex 列布局（gap 撑内部间距），
  // 设 '' 会回退成默认 block，内部 gap 失效、间距又挤回老样子
  $('connSerialFields').style.display = 'flex'; $('connSSHFields').style.display = 'none';
  $('connAuthPassword').style.display = ''; $('connAuthKey').style.display = 'none';
  $('connModal').classList.add('show');
};
$('connClose').onclick = () => $('connModal').classList.remove('show');
$('connCancel').onclick = () => $('connModal').classList.remove('show');
// 密码显隐：用 WebView2 对 type=password 原生的眼睛按钮（框内右缘），不自加

// 连接类型切换（串口/SSH）
let _connType = 'serial';
document.querySelectorAll('.conn-type-btn').forEach(btn => {
  btn.onclick = () => {
    _connType = btn.dataset.type;
    document.querySelectorAll('.conn-type-btn').forEach(b => b.classList.toggle('active', b === btn));
    $('connSerialFields').style.display = _connType === 'serial' ? 'flex' : 'none';
    $('connSSHFields').style.display = _connType === 'ssh' ? 'flex' : 'none';
  };
});
// SSH 认证方式切换（密码/密钥）
let _sshAuth = 'password';
document.querySelectorAll('.conn-auth-btn').forEach(btn => {
  btn.onclick = () => {
    _sshAuth = btn.dataset.auth;
    document.querySelectorAll('.conn-auth-btn').forEach(b => b.classList.toggle('active', b === btn));
    $('connAuthPassword').style.display = _sshAuth === 'password' ? '' : 'none';
    $('connAuthKey').style.display = _sshAuth === 'key' ? '' : 'none';
  };
});

// 连接流程全程在弹窗内进行：确认→按钮"连接中…"禁用→失败红字显示在弹窗里
// （SSH 超时要等 ~10s，之前先关弹窗再右下角弹泡，中间像卡死无响应）；成功才关弹窗。
$('connConfirm').onclick = async () => {
  const errEl = $('connErr');
  errEl.classList.remove('show'); errEl.textContent = '';
  let j = null;
  const btn = $('connConfirm'), oldText = btn.textContent;
  btn.disabled = true;
  try {
    if (_connType === 'ssh') {
      const host = $('connHost').value.trim();
      const port = $('connSshPort').value.trim() || '22';
      const username = $('connUser').value.trim();
      if (!host || !username) { errEl.textContent = '请填主机和用户名'; errEl.classList.add('show'); return; }
      const password = _sshAuth === 'password' ? $('connPass').value : '';
      const key_path = _sshAuth === 'key' ? $('connKeyPath').value.trim() : '';
      if (_sshAuth === 'key' && !key_path) { errEl.textContent = '请填写密钥路径'; errEl.classList.add('show'); return; }
      // 密码可为空（部分设备空密码可进），后端自动处理
      btn.textContent = '连接中…';
      j = await connectSSH(host, port, username, password, key_path);
    } else {
      const port = $('connPort').value, baud = $('connBaud').value;
      if (!port) { errEl.textContent = '请选择串口'; errEl.classList.add('show'); return; }
      btn.textContent = '连接中…';
      j = await connectPort(port, baud);
    }
    if (j && j.ok) $('connModal').classList.remove('show');
    else { errEl.textContent = '❌ ' + ((j && j.err) || '未知错误'); errEl.classList.add('show'); }
  } finally {
    btn.disabled = false; btn.textContent = oldText;
  }
};
$('btnRefreshPorts').onclick = async () => { await loadPorts(); showBanner('端口列表已刷新'); };

// 终端功能按钮（暂停/清屏/^C/^D/时间戳等）已移到各连接区顶部工具栏
// （terminal-core.js buildTerminal 内，仿日志 tab 的 log-viewer-toolbar），
// tab 栏保持整洁——按钮只作用于所属连接，不再作用于全局活动 tab。
// 关于按钮已改为「换肤」（js/theme.js 接管），版本号常驻标题栏「PRO v0.5.0」
// 顶栏「打开日志目录」已移除（日志库弹窗内有同功能入口 btnLogDirOpen）

// ============================================================
// 最近打开（SSH/串口/文件 快捷重开，后端 config.json 持久化 + 自动去重）
// ============================================================
const RECENT_ICON = { ssh: '🔗', serial: '🔌', file: '📄' };  // 类型区分图标
const RECENT_TYPE_NAME = { ssh: 'SSH', serial: '串口', file: '文件' };
let _recentList = [];

async function loadRecentList() {
  try {
    const r = await fetch('/api/recent');
    const j = await r.json();
    if (j.ok) { _recentList = j.recent || []; renderRecentList(); }
  } catch(e) {}
}

function renderRecentList() {
  const el = $('recentList');
  if (!el) return;
  if (!_recentList.length) {
    el.innerHTML = '<div class="recent-empty">暂无记录<br>连接/打开文件后自动记录</div>';
    return;
  }
  // 按类型分组（串口/文件/SSH），组内保持原新→旧顺序
  const groups = [
    { type: 'serial', name: '串口' },
    { type: 'file',   name: '文件' },
    { type: 'ssh',    name: 'SSH' },
  ];
  el.innerHTML = '';
  groups.forEach(g => {
    const items = _recentList.map((it, i) => ({it, i})).filter(x => x.it.type === g.type);
    if (!items.length) return;
    const gh = document.createElement('div');
    gh.className = 'recent-group-head t-' + g.type;
    gh.innerHTML = `${RECENT_ICON[g.type] || '·'} ${g.name} <span class="g-line"></span>`;
    el.appendChild(gh);
    items.forEach(({it, i}) => el.appendChild(_recentItemEl(it, i)));
  });
}

function _recentItemEl(it, i) {
  const d = document.createElement('div');
  d.className = 'recent-item t-' + it.type;
  d.title = `${RECENT_TYPE_NAME[it.type]} · ${it.label}（点击快速打开）`;
  d.innerHTML = `
    <span class="ric">${RECENT_ICON[it.type] || '·'}</span>
    <div class="info">
      <div class="name">${esc(it.label)}</div>
    </div>
    <div class="actions"><button data-del="${i}" title="从列表移除">✕</button></div>
  `;
  d.onclick = (e) => {
    if (e.target.dataset.del !== undefined) { e.stopPropagation(); removeRecentItem(i); return; }
    openRecentItem(it);
  };
  return d;
}

async function removeRecentItem(i) {
  const kept = _recentList.filter((_, idx) => idx !== i);
  try {
    await fetch('/api/recent', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({replace: kept})});
    _recentList = kept;
    renderRecentList();
  } catch(e) { showBanner('移除失败', 3000, true); }
}

function openRecentItem(it) {
  if (it.type === 'serial') {
    const d = it.data || {};
    connectPort(d.port, d.baud || 115200);
  } else if (it.type === 'ssh') {
    const d = it.data || {};
    connectSSH(d.host, d.port || '22', d.username, d.password || '', d.key_path || '');
  } else if (it.type === 'file') {
    // 文件分发：外部文件（extPath 绝对路径，含拖入）统一走 openDroppedFile 智能分发
    // （文本类含小 .log → 编辑器，超大 .log/未知 → 查看器）；
    // 站内文件（files/ 内 .note/.txt 等，只有 name 无绝对路径）必须走 openEditorFile(name=)——
    // 之前一律 openDroppedFile 按绝对路径请求，后端拒收相对名 →「不支持的文件类型或文件不存在」。
    const d = it.data || {};
    if (d.kind === 'hex' && d.path) buildHexViewerTab(d.path, d.name || it.label);   // bin/二进制：hex 模式快速重开
    else if (d.extPath && typeof openDroppedFile === 'function') openDroppedFile(d.extPath);
    else if (d.kind === 'log') buildLogViewer(d.name || d.path);
    else if (typeof openEditorFile === 'function') openEditorFile(d.name || d.path);
  }
}

// 侧栏双 sheet 切换（打开 / 最近）
document.querySelectorAll('.sidebar-sheet-tab').forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll('.sidebar-sheet-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.sidebar-sheet-pane').forEach(p =>
      p.classList.toggle('active', p.dataset.sheet === tab.dataset.sheet));
  };
});


// ============================================================
// 日志库
// ============================================================
