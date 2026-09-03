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
    } else {
      showBanner('连接失败：' + (j.err || '未知错误'), 8000, true);
    }
  } catch(e) { showBanner('连接请求失败：' + e, 8000, true); }
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
    } else {
      showBanner('SSH 连接失败：' + (j.err || '未知错误'), 8000, true);
    }
  } catch(e) { showBanner('SSH 连接请求失败：' + e, 8000, true); }
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
      portList.innerHTML = '<div class="empty-state" style="padding:30px 10px;"><div class="desc">点击「新建连接」或「新建文件」添加内容</div></div>';
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
      const isEdit = conn.meta.kind === 'editor';
      const descText = isSSH ? `SSH · ${conn.meta.host || ''}` : isLog ? `📜 日志` : isEdit ? `📝 文本` : `${conn.meta.baud || ''} baud`;
      const rowCount = conn.term ? conn.term.buffer.active.length : (conn.logState ? conn.logState.total : (isEdit ? (conn.ta ? conn.ta.value.length : 0) : 0));
      item.innerHTML = `
        <span class="led"></span>
        <div class="info">
          <div class="name">${esc(conn.meta.label || pid)}</div>
          <div class="desc">${esc(descText)} · <span class="baud" data-rows>${rowCount}${isEdit ? ' 字符' : ' 行'}</span></div>
        </div>
        <div class="actions"><button data-close="${pid}" title="${isLog ? '关闭' : '断开'}">✕</button></div>
      `;
      item.onclick = (e) => {
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
      const n = isEdit ? (conn.ta ? conn.ta.value.length : 0)
        : conn.term ? conn.term.buffer.active.length
        : (conn.logState ? conn.logState.total : 0);
      const t = n + (isEdit ? ' 字符' : ' 行');
      if (el.textContent !== t) el.textContent = t;
    });
  }
  // 标签栏同序重排（复用全局 sortKeyFn）——当前顺序已一致时跳过，不动 DOM
  const tabEls = Array.from(tabs.querySelectorAll('.tab'));
  const curIds = tabEls.map(t => t.dataset.portId);
  const wantIds = ids.concat(curIds.filter(id => !connections[id]));
  const needSort = curIds.length !== wantIds.length || curIds.some((id, i) => id !== wantIds[i]);
  if (needSort) {
    tabEls.sort((a, b) => {
      const ka = sortKeyFn(a.dataset.portId), kb = sortKeyFn(b.dataset.portId);
      return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : kb[1] > kb[1] ? 1 : 0);
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
  // 每次打开重置为默认（串口 + 密码认证），避免残留上次的 SSH/密钥选择
  _connType = 'serial'; _sshAuth = 'password';
  document.querySelectorAll('.conn-type-btn').forEach(b => b.classList.toggle('active', b.dataset.type === 'serial'));
  document.querySelectorAll('.conn-auth-btn').forEach(b => b.classList.toggle('active', b.dataset.auth === 'password'));
  $('connSerialFields').style.display = ''; $('connSSHFields').style.display = 'none';
  $('connAuthPassword').style.display = ''; $('connAuthKey').style.display = 'none';
  $('connModal').classList.add('show');
};
$('connClose').onclick = () => $('connModal').classList.remove('show');
$('connCancel').onclick = () => $('connModal').classList.remove('show');

// 连接类型切换（串口/SSH）
let _connType = 'serial';
document.querySelectorAll('.conn-type-btn').forEach(btn => {
  btn.onclick = () => {
    _connType = btn.dataset.type;
    document.querySelectorAll('.conn-type-btn').forEach(b => b.classList.toggle('active', b === btn));
    $('connSerialFields').style.display = _connType === 'serial' ? '' : 'none';
    $('connSSHFields').style.display = _connType === 'ssh' ? '' : 'none';
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

$('connConfirm').onclick = () => {
  if (_connType === 'ssh') {
    const host = $('connHost').value.trim();
    const port = $('connSshPort').value.trim() || '22';
    const username = $('connUser').value.trim();
    if (!host || !username) { showBanner('请填主机和用户名', 3000, true); return; }
    const password = _sshAuth === 'password' ? $('connPass').value : '';
    const key_path = _sshAuth === 'key' ? $('connKeyPath').value.trim() : '';
    if (!password && !key_path) { showBanner('请填密码或密钥路径', 3000, true); return; }
    $('connModal').classList.remove('show');
    connectSSH(host, port, username, password, key_path);
  } else {
    const port = $('connPort').value, baud = $('connBaud').value;
    if (!port) { showBanner('请选择串口', 3000, true); return; }
    $('connModal').classList.remove('show');
    connectPort(port, baud);
  }
};
$('btnRefreshPorts').onclick = async () => { await loadPorts(); showBanner('端口列表已刷新'); };

// 顶栏全局按钮（作用于当前活动标签）
$('btnPause').onclick = () => {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.term) return;  // 日志 tab 无 term，跳过
  conn.paused = !conn.paused;
  $('btnPause').textContent = conn.paused ? '▶' : '⏸';
  if (!conn.paused) { conn.autoScroll = true; conn.term.scrollToBottom(); }
};
$('btnClear').onclick = () => {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.term) return;  // 日志 tab 无 term，跳过
  conn.term.clear();
  conn.kwDecorLastRow = 0;
  conn.kwDecorations.forEach(d => { try { d.dispose(); } catch(e){} });
  conn.kwDecorations = [];
  fetch('/api/clear_buffer', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: activePortId})});
};
$('btnNewLog').onclick = async () => {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.term) return;  // 日志 tab 无 term，跳过
  const r = await fetch('/api/new_log', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: activePortId})});
  const j = await r.json();
  showBanner('已开新日志：' + (j.log_path || ''));
};
$('btnCtrlC').onclick = () => { if (activePortId) termSendRaw(activePortId, [3]); };
$('btnTs').onclick = () => {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || conn.meta.kind === 'log') return;
  conn.tsEnabled = !conn.tsEnabled;
  $('btnTs').classList.toggle('active', conn.tsEnabled);
  showBanner(conn.tsEnabled ? '已开启时间戳注入（新输出行首加 [HH:MM:SS.mmm]）' : '已关闭时间戳注入');
};
$('btnCtrlD').onclick = () => { if (activePortId) termSendRaw(activePortId, [4]); };
$('btnJumpBottomMain').onclick = () => { if (activePortId) jumpToBottom(activePortId); };
$('btnAbout').onclick = () => showBanner('终端控制台 Pro · xterm.js 终端 + 搜索/感知/分析 · v0.5.0', 5000);
// 打开日志目录（顶栏快捷入口）
$('btnOpenLogDir').onclick = async () => {
  try {
    const r = await fetch('/api/log_dir/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'});
    const j = await r.json();
    if (j.ok) showBanner('已在资源管理器打开日志目录');
    else showBanner('打开失败：' + (j.err || ''), 6000, true);
  } catch(e) { showBanner('打开失败：' + e, 6000, true); }
};

// ============================================================
// 日志库
// ============================================================
