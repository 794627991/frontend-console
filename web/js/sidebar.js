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
    if (j.ok && Array.isArray(j.recent)) _recentList = j.recent.filter(it => it.type !== 'claude');
    renderRecentList();
  } catch(e) {}
}
async function connectPort(port, baud) {
  showBanner(`正在连接串口 ${port}@${baud} ...`, 0);   // 0=不自动消失，结果出来再定
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
    } else {
      showBanner(`串口连接失败：${j.err || '未知错误'}`, 6000, true);
    }
    return j;
  } catch(e) { showBanner(`串口连接请求失败：${e}`, 6000, true); return {ok: false, err: '连接请求失败：' + e}; }
}

async function connectSSH(host, port, username, password, key_path) {
  // SSH 建连最长 10s（TCP 超时）——期间右下角常驻「正在连接」，不能让用户干等无反馈
  showBanner(`正在连接 ${username}@${host}:${port} ...`, 0);
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
    } else {
      showBanner(`SSH 连接失败：${j.err || '未知错误'}`, 8000, true);
    }
    return j;
  } catch(e) { showBanner(`SSH 连接请求失败：${e}`, 8000, true); return {ok: false, err: 'SSH 连接请求失败：' + e}; }
}

async function connectTelnet(host, port) {
  showBanner(`正在连接 ${host}:${port} ...`, 0);
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'telnet', host, port})});
    const j = await r.json();
    if (j.ok) {
      const port_id = j.port_id;
      showBanner(`已连接 ${host}:${port}`);
      const conn = buildTerminal(port_id, {kind:'telnet', label:`${host}:${port}`, host});
      connections[port_id] = conn;
      switchTab(port_id);
      refreshSidebar();
      refreshGlobalStatus();
      _recentAdd({type:'telnet', key:`telnet:${host}:${port}`, label:`${host}:${port}`,
                  data:{host, port}});
    } else {
      showBanner(`Telnet 连接失败：${j.err || '未知错误'}`, 8000, true);
    }
    return j;
  } catch(e) { showBanner(`Telnet 连接请求失败：${e}`, 8000, true); return {ok: false, err: 'Telnet 连接请求失败：' + e}; }
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
      const isTelnet = conn.meta.kind === 'telnet';
      const isLog = conn.meta.kind === 'log';
      const isEdit = conn.meta.kind === 'editor' || conn.meta.kind === 'hex' || conn.meta.kind === 'diff' || conn.meta.kind === 'bindiff';
      const isClaude = conn.meta.kind === 'claude';
      // 编辑类 tab desc 前缀用后缀专属 SVG 图标（file-icons.js），hex/对比/日志保留 emoji
      const edIcon = (isEdit && conn.meta.kind === 'editor') ? fileIconHtml(conn.meta.label || '', 12) + ' 笔记'
                    : conn.meta.kind === 'bindiff' ? '🔀 bin 对比'
                    : isEdit ? (conn.meta.kind === 'hex' ? '🔧 hex' : '🔀 对比')
                    : isLog ? '📜 日志' : '';
      const descText = isSSH ? `SSH · ${conn.meta.host || ''}` : isTelnet ? `Telnet · ${conn.meta.host || ''}` : (isEdit || isLog) ? edIcon : isClaude ? `<span class="claude-ico"></span> Claude · ${(conn.meta.cwd || '').split(/[\\\\/]/).pop() || ''}` : `${conn.meta.baud || ''} baud`;
      const rowCount = conn.term ? conn.term.buffer.active.length : (conn.logState ? conn.logState.total : (isEdit ? _edStatText(conn) : 0));
      // 编辑器类 tab：未保存时名字带 * + dirty 类（led 橙色，与 _edMarkTab 同步）
      const isDirty = isEdit && conn.dirty;
      item.innerHTML = `
        <span class="led"></span>
        <div class="info">
          <div class="name">${(isDirty ? '*' : '') + esc(conn.meta.label || pid)}</div>
          <div class="desc">${((isEdit && conn.meta.kind === 'editor') || isClaude) ? descText : esc(descText)} · <span class="baud" data-rows>${isEdit ? rowCount : rowCount + ' 行'}</span></div>
        </div>
        <div class="actions"><button data-close="${pid}" title="${isLog ? '关闭' : '断开'}">✕</button></div>
      `;
      if (isDirty) item.classList.add('dirty');
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
    // 顶栏「N 个连接」指示器已移除（改为帮助按钮）；此函数仍被
    // init.js/连接流程调用——保留 /api/status 探活语义，元素不在就静默。
    const gs = $('globalStatus');
    if (gs) {
      const n = Object.keys(j.ports || {}).length;
      gs.textContent = n + ' 个连接';
      $('globalDot').className = 'dot' + (n ? ' on' : '');
    }
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
  // 断连 overlay 可见时按 R 立即重连（类 MobaXterm；焦点不在终端时走这里，
  // 终端内由 xterm attachCustomKeyEventHandler 同款处理——xterm 吞按键，document 收不到）
  if (!e.ctrlKey && !e.altKey && (e.key === 'r' || e.key === 'R') &&
      conn.discOverlay && conn.discOverlay.classList.contains('show')) {
    e.preventDefault();
    triggerReconnect(pid, conn);
    return;
  }
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
  $('btnRefreshPorts').style.display = '';   // 刷新按钮只跟串口（SSH 不需要枚举端口）
  $('connAuthPassword').style.display = ''; $('connAuthKey').style.display = 'none';
  $('connModal').classList.add('show');
};
$('connClose').onclick = () => $('connModal').classList.remove('show');
$('connCancel').onclick = () => $('connModal').classList.remove('show');
// 密码显隐：白色描边眼睛按钮（框外右侧）。点一下显示密码（眼睛划线），
// 再点恢复掩码。之前误信 WebView2 会给 type=password 渲染原生眼睛而删过
// 自加按钮——实际 pywebview/WebView2 默认不显示，导致功能整个消失。
const _connPassInput = $('connPass'), _connPassToggle = $('connPassToggle');
if (_connPassInput && _connPassToggle) {
  // 眼睛图标语义（用户实锤报反直觉后修正）：图标表示【当前状态】——
  // 明文可见 = 开眼，掩码隐藏 = 闭眼/划线眼。之前恰好画反（明文配划线、
  // 掩码配开眼），图2/3 两态都错。
  const EYE_OPEN_SVG = _connPassToggle.innerHTML;
  const EYE_OFF_SVG = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
    <line x1="1" y1="1" x2="23" y2="23"></line>
  </svg>`;
  const _passSyncEye = () => {
    const showing = _connPassInput.type === 'text';
    _connPassToggle.innerHTML = showing ? EYE_OPEN_SVG : EYE_OFF_SVG;
    _connPassToggle.title = showing ? '密码可见中，点击隐藏' : '密码已隐藏，点击显示';
  };
  _connPassToggle.onclick = () => {
    _connPassInput.type = _connPassInput.type === 'text' ? 'password' : 'text';
    _passSyncEye();
  };
  _passSyncEye();   // 初始态同步（之前初始显示也不对）
}

// 连接类型切换（串口/SSH）
let _connType = 'serial';
document.querySelectorAll('.conn-type-btn').forEach(btn => {
  btn.onclick = () => {
    _connType = btn.dataset.type;
    document.querySelectorAll('.conn-type-btn').forEach(b => b.classList.toggle('active', b === btn));
    $('connSerialFields').style.display = _connType === 'serial' ? 'flex' : 'none';
    $('connSSHFields').style.display = _connType === 'ssh' ? 'flex' : 'none';
    $('connTelnetFields').style.display = _connType === 'telnet' ? 'flex' : 'none';
    $('btnRefreshPorts').style.display = _connType === 'serial' ? '' : 'none';
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
    } else if (_connType === 'telnet') {
      const host = $('connTelnetHost').value.trim();
      const port = $('connTelnetPort').value.trim() || '23';
      if (!host) { errEl.textContent = '请填主机地址'; errEl.classList.add('show'); return; }
      btn.textContent = '连接中…';
      j = await connectTelnet(host, port);
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
$('btnRefreshPorts').onclick = async () => { await loadPorts(); showBanner('串口端口已刷新'); };

// 终端功能按钮（暂停/清屏/^C/^D/时间戳等）已移到各连接区顶部工具栏
// （terminal-core.js buildTerminal 内，仿日志 tab 的 log-viewer-toolbar），
// tab 栏保持整洁——按钮只作用于所属连接，不再作用于全局活动 tab。
// 关于按钮已改为「换肤」（js/theme.js 接管），版本号常驻标题栏「PRO v0.5.0」
// 顶栏「打开日志目录」已移除（日志库弹窗内有同功能入口 btnLogDirOpen）

// ============================================================
// 最近打开（SSH/串口/文件 快捷重开，后端 config.json 持久化 + 自动去重）
// ============================================================
const RECENT_ICON = { claude: '<span class="claude-ico"></span>', ssh: '🔗', serial: '🔌', telnet: '🖥' };  // 类型区分图标（claude 用官方星形标志；file 按后缀动态生成 fileIconHtml）
const RECENT_TYPE_NAME = { claude: 'Claude 会话', ssh: 'SSH', serial: '串口', telnet: 'Telnet', file: '文件' };
let _recentList = [];

async function loadRecentList() {
  try {
    const r = await fetch('/api/recent');
    const j = await r.json();
    // claude 会话条目不进「最近」（功能已移除）——历史遗留数据直接过滤掉
    if (j.ok) { _recentList = (j.recent || []).filter(it => it.type !== 'claude'); renderRecentList(); }
  } catch(e) {}
}

function renderRecentList() {
  const el = $('recentList');
  if (!el) return;
  if (!_recentList.length) {
    el.innerHTML = '<div class="recent-empty">暂无记录<br>连接/打开文件后自动记录</div>';
    return;
  }
  // 按类型分组，组内保持原新→旧顺序（claude 分组已移除——会话恢复改走
  // claude 自带 /resume 选择界面，不再在工具侧直连）
  const groups = [
    { type: 'serial', name: '串口' },
    { type: 'file',   name: '文件' },
    { type: 'ssh',    name: 'SSH' },
    { type: 'telnet', name: 'Telnet' },
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
  // claude 条目 label 动态替换：记入时固化的「Claude · 目录名」会重名且不随备注更新，
  // 按 session_id 从会话数据取当前显示名（备注 > aiTitle > 摘要，_claudeTitleMap）
  const showLabel = (it.type === 'claude' && it.data && it.data.resume &&
                    typeof _claudeTitleMap !== 'undefined' &&
                    _claudeTitleMap[it.data.resume]) || it.label;
  d.title = `${RECENT_TYPE_NAME[it.type]} · ${showLabel}（点击快速打开）`;
  // file 类型按后缀出专属 SVG 图标（file-icons.js），其余用类型 emoji
  const ico = it.type === 'file' ? fileIconHtml(it.label || it.data?.name || '', 14)
                                 : (RECENT_ICON[it.type] || '·');
  d.innerHTML = `
    <span class="ric">${ico}</span>
    <div class="info">
      <div class="name">${esc(showLabel)}</div>
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
  if (it.type === 'claude') {
    // claude 最近会话功能已移除（按用户要求）：不再按会话 id 直连恢复。
    // 兼容期处理——列表里若有历史遗留的 claude 条目，点击改为发 /resume 让
    // claude 自己弹会话选择界面，用户手动挑（宁可多一步，不直连会话）
    const d = it.data || {};
    if (typeof connectClaude === 'function') {
      connectClaude({cwd: d.cwd || '', resume: '__picker__'});
    }
    return;
  }
  if (it.type === 'serial') {
    const d = it.data || {};
    connectPort(d.port, d.baud || 115200);
  } else if (it.type === 'ssh') {
    const d = it.data || {};
    connectSSH(d.host, d.port || '22', d.username, d.password || '', d.key_path || '');
  } else if (it.type === 'telnet') {
    const d = it.data || {};
    connectTelnet(d.host, d.port || '23');
  } else if (it.type === 'file') {
    // 文件分发：外部文件（extPath 绝对路径，含拖入）统一走 openDroppedFile 智能分发
    // （文本类含小 .log → 编辑器，超大 .log/未知 → 查看器）；
    // 站内文件（files/ 内 .note/.txt 等，只有 name 无绝对路径）必须走 openEditorFile(name=)——
    // 之前一律 openDroppedFile 按绝对路径请求，后端拒收相对名 →「不支持的文件类型或文件不存在」。
    const d = it.data || {};
    if ((d.kind === 'diff' || d.kind === 'bindiff') && d.a && d.b) buildDiffViewerTab(d.a, d.b);   // 文件对比（文本/二进制）：A/B 两份快速重开
    else if (d.kind === 'hex' && d.path) buildHexViewerTab(d.path, d.name || it.label);   // bin/二进制：hex 模式快速重开
    else if (d.extPath && typeof openDroppedFile === 'function') openDroppedFile(d.extPath, true);   // true=快捷打开：跳过"活动 tab 是 claude 就灌路径进终端"分支
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
