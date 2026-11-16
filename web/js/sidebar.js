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
async function connectPort(port, baud, quiet) {
  // 任务型通知：转圈常驻，结果出来变 ✓/✗（多连接并发时各自一条向上堆叠）。
  // quiet=true（连接弹窗路径）：弹窗内已有「连接中…」按钮态 + 内联错误，
  // 通知栈再弹会双份提示（铁律②体验）——静默，失败由弹窗内联展示。
  const nid = quiet ? null : notifyTask({type:'serial', title:`正在连接 ${port}`, detail:`串口 @${baud}`});
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'serial', port, baud})});
    const j = await r.json();
    if (j.ok) {
      if (nid) notifyTaskDone(nid, {ok:true, title:`已连接 ${port}`, detail:`串口 @${baud}`});
      const conn = buildTerminal(port, {kind:'serial', baud, label:port});
      connections[port] = conn;
      switchTab(port);
      refreshSidebar();
      refreshGlobalStatus();
      _recentAdd({type:'serial', key:'serial:'+port, label:`${port} @${baud}`, data:{port, baud}});
    } else {
      if (nid) notifyTaskDone(nid, {ok:false, title:`串口连接失败`, detail:j.err || '未知错误', ms:8000});
    }
    return j;
  } catch(e) { if (nid) notifyTaskDone(nid, {ok:false, title:'串口连接请求失败', detail:String(e), ms:8000}); return {ok: false, err: '连接请求失败：' + e}; }
}

async function connectSSH(host, port, username, password, key_path, quiet) {
  // SSH 建连最长 10s（TCP 超时）——任务型通知转圈常驻，含 IP/账号，不能让用户干等无反馈
  const nid = quiet ? null : notifyTask({type:'ssh', title:`正在连接 ${username}@${host}:${port}`, detail:'SSH · TCP 超时最长 10s'});
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'ssh', host, port, username, password, key_path})});
    const j = await r.json();
    if (j.ok) {
      const port_id = j.port_id;
      if (nid) notifyTaskDone(nid, {ok:true, title:`已连接 ${username}@${host}:${port}`, detail:'SSH'});
      // v3.5.315：双开实例标签区分（后端序号 #2/#3… 只在多开时出现）
      const _dup = /#(\d+)$/.exec(port_id);
      const _lbl = `${username}@${host}` + (_dup ? ` ·${_dup[1]}` : '');
      const conn = buildTerminal(port_id, {kind:'ssh', label:_lbl, host, user:username});
      connections[port_id] = conn;
      switchTab(port_id);
      refreshSidebar();
      refreshGlobalStatus();
      // 密码随记录保存（本机工具、用户明确要求保存账号密码），快捷重开免重输
      _recentAdd({type:'ssh', key:`ssh:${host}:${port}:${username}`, label:`${username}@${host}:${port}`,
                  data:{host, port, username, password: password || '', key_path: key_path || ''}});
    } else {
      if (nid) notifyTaskDone(nid, {ok:false, title:`SSH 连接失败 ${host}:${port}`, detail:j.err || '未知错误', ms:8000});
    }
    return j;
  } catch(e) { if (nid) notifyTaskDone(nid, {ok:false, title:`SSH 连接请求失败 ${host}:${port}`, detail:String(e), ms:8000}); return {ok: false, err: 'SSH 连接请求失败：' + e}; }
}

async function connectTelnet(host, port, quiet) {
  const nid = quiet ? null : notifyTask({type:'telnet', title:`正在连接 ${host}:${port}`, detail:'Telnet'});
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'telnet', host, port})});
    const j = await r.json();
    if (j.ok) {
      const port_id = j.port_id;
      if (nid) notifyTaskDone(nid, {ok:true, title:`已连接 ${host}:${port}`, detail:'Telnet'});
      const conn = buildTerminal(port_id, {kind:'telnet', label:`${host}:${port}`, host});
      connections[port_id] = conn;
      switchTab(port_id);
      refreshSidebar();
      refreshGlobalStatus();
      _recentAdd({type:'telnet', key:`telnet:${host}:${port}`, label:`${host}:${port}`,
                  data:{host, port}});
    } else {
      if (nid) notifyTaskDone(nid, {ok:false, title:`Telnet 连接失败 ${host}:${port}`, detail:j.err || '未知错误', ms:8000});
    }
    return j;
  } catch(e) { if (nid) notifyTaskDone(nid, {ok:false, title:`Telnet 连接请求失败 ${host}:${port}`, detail:String(e), ms:8000}); return {ok: false, err: 'Telnet 连接请求失败：' + e}; }
}

// a581（用户需求）：本地终端——起来直接就是可敲命令的 shell 窗口
// 名字映射必须在 connectShell 之前定义：const 有 TDZ，函数体虽在调用时才求值，
// 但把常量放前面能消除「先调后定义」的阅读歧义。
const SHELL_LABEL = { cmd: '命令提示符', powershell: 'PowerShell', pwsh: 'PowerShell 7', bash: 'Git Bash' };
async function connectShell(shell, cwd, quiet) {
  const nid = quiet ? null : notifyTask({type:'shell', title:'正在打开终端', detail: shell});
  try {
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({kind:'shell', shell, cwd})});
    const j = await r.json();
    if (j.ok) {
      const port_id = j.port_id;
      const _dup = /:(\d+)$/.exec(port_id);
      const _name = (SHELL_LABEL[shell] || '终端');
      const _lbl = _name + (_dup && +_dup[1] > 1 ? ' ·' + _dup[1] : '');
      if (nid) notifyTaskDone(nid, {ok:true, title:'已打开 ' + _name, detail: j.cwd || ''});
      const conn = buildTerminal(port_id, {kind:'shell', label:_lbl, shell, cwd:j.cwd || cwd || ''});
      connections[port_id] = conn;
      switchTab(port_id);
      refreshSidebar();
      refreshGlobalStatus();
      _recentAdd({type:'shell', key:`shell:${shell}:${cwd || ''}`, label:_name + (cwd ? ' · ' + cwd : ''),
                  data:{shell, cwd: cwd || ''}});
      // 焦点抢到 xterm（照 claude tab 的做法），打开即可敲
      setTimeout(() => { try { conn.term && conn.term.focus(); } catch(e) {} }, 200);
    } else {
      if (nid) notifyTaskDone(nid, {ok:false, title:'打开终端失败', detail:j.err || '未知错误', ms:8000});
    }
    return j;
  } catch(e) { if (nid) notifyTaskDone(nid, {ok:false, title:'打开终端请求失败', detail:String(e), ms:8000}); return {ok: false, err: '打开终端请求失败：' + e}; }
}

function closeConnection(portId) {  // D-3（P3）附带防御：直调 closeConnection 绕过编辑器完整 dispose 链
  // （hex/diff/bindiff 无专属关闭函数——四类统一转发，sidebar.js:198/:233 实证）
  // （编辑器 _edCloseNow 的完整 dispose）=5 倍泄漏（3.1MB/次 vs 0.58MB）
  // R3 审计 W22（P1）：web 必须同样转发——web-panel 的 closeEditorTab
  // 包装负责 dispose REST + resize/layout 监听清理 + _webActivePid 清理；
  // 落本函数通用清理 = 控件永不 Dispose + 幽灵监听发 layout(0,0,0,0)
  // 把全部存活网页控件缩成 50×50（侧栏 ✕ 与抽屉批量关闭两条路径可达）
  if (/^(edit|hex|diff|bindiff|web):/.test(portId) &&
      typeof closeEditorTab === 'function') {
    closeEditorTab(portId); return;   // 产品路径统一走 closeEditorTab
                                      // （sidebar.js:198/:233 实证）
  }
  fetch('/api/disconnect', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId})});
  const conn = connections[portId];
  if (conn) {
    if (conn.sse) conn.sse.close();
    if (conn._webgl) { try { conn._webgl.dispose(); } catch(e){} }  // 释放 GPU 资源
    if (conn.term) { try { conn.term.dispose(); } catch(e){} }
    // 微批发送的 pending 定时器清理（防关闭后误发）
    if (conn._sendTimer) { clearTimeout(conn._sendTimer); conn._sendTimer = null; }
    // 自绘滚动条清理（terminal-core _termSbInit 的周期兜底计时器；DOM 随 wrap.remove 走）
    if (conn._sb) { clearInterval(conn._sb.timer); conn._sb = null; }
    // 移除串口搜索分栏的 document 级监听器，避免泄漏
    if (conn.termSplitMove) document.removeEventListener('mousemove', conn.termSplitMove);
    if (conn.termSplitUp) document.removeEventListener('mouseup', conn.termSplitUp);
    // a237 P1（第5轮A4）：面板类 tab（proxy/claude 等）从侧栏 ✕ 关闭落本函数，
    // 此前不清轮询定时器——proxy 的 pollTimer（3s /api/proxy/status）+
    // tickTimer（1s）空转到退出，脱离 DOM 的 display 残留让面板自停条件
    // 永不成立。对齐 _edCloseNow 的清理面
    if (conn.pollTimer) { clearInterval(conn.pollTimer); conn.pollTimer = null; }
    if (conn.tickTimer) { clearInterval(conn.tickTimer); conn.tickTimer = null; }
    if (conn.diskWatchTimer) { clearInterval(conn.diskWatchTimer); conn.diskWatchTimer = null; }
    // a237 P3：一次性微批/高亮定时器补清（200-500ms 悬挂窗口内不该再触发；
    // _kwTimer 到期还会在已 dispose 的 term 上抛未捕获异常）
    if (conn._resizeTimer) { clearTimeout(conn._resizeTimer); conn._resizeTimer = null; }
    if (conn._writeFlushTimer) { clearTimeout(conn._writeFlushTimer); conn._writeFlushTimer = null; }
    if (conn._kwTimer) { clearTimeout(conn._kwTimer); conn._kwTimer = null; }
    conn.tab.remove();
    conn.wrap.remove();
    delete connections[portId];
  }
  // 切换到第一个可用标签（复用全局 sortKeyFn）
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
  });
  // 对齐 _edCloseNow（v4.1 同锤修复的漏网路径）：关的不是活动 tab 不动激活态；
  // 关的是活动 tab 优先回「来时的 tab」（switchTab 记录），无来路才回排序首位。
  // 旧逻辑无条件切排序首位——关后台 tab 也把用户从当前视图拽走（第2轮盲测实锤）
  const back = window._hgTabBack;
  window._hgTabBack = null;
  if (remaining.length) {
    if (activePortId === portId) {
      // a455：自动回切不计 MRU（与 harness 关 tab 同约定）
      switchTab(back && connections[back] ? back : remaining[0], true);
    }
  } else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon"><svg width="30" height="30" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 2.5v3M10.5 2.5v3"/><path d="M4 5.5h8v2a4 4 0 0 1-8 0z"/><path d="M8 11.5v2"/></svg></div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
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
      // a239 B4-P2: 畸形 conn（meta 缺失）跳过本行而非抛 TypeError——原实现
      // 在 forEach 中段抛出会留下「计数已写、列表空白」的撕裂态（5s 轮询
      // 每轮重抛，侧栏永久空白）
      if (!conn || !conn.meta) { console.warn('skip malformed conn', pid); return; }
      const item = document.createElement('div');
      item.className = 'port-item connected' + (pid === activePortId ? ' active' : '');
      item.dataset.portId = pid;
      const isSSH = conn.meta.kind === 'ssh';
      const isTelnet = conn.meta.kind === 'telnet';
      const isLog = conn.meta.kind === 'log';
      const isEdit = conn.meta.kind === 'editor' || conn.meta.kind === 'hex' || conn.meta.kind === 'diff' || conn.meta.kind === 'bindiff';
      const isClaude = conn.meta.kind === 'claude';
      const isShell = conn.meta.kind === 'shell';
      const isHarness = conn.meta.kind === 'harness';
      // a434：版本面板（独立主区 tab）无连接语义，关闭走 closeEditorTab
      // （触发 _edCloseNow 的清理链）；误走 closeConnection 会发必然 404 的
      // /api/disconnect
      const isVcs = conn.meta.kind === 'vcs';
      // R-命名统一：网页 tab 副行显示当前站点（host+路径），不落串口兜底
      const isWeb = conn.meta.kind === 'web';
      const webUrlDesc = isWeb ? (() => {
        const u = conn._ctlUrl || (conn._nav && conn._nav.stack && conn._nav.stack[conn._nav.idx]) || '';
        try {
          const x = new URL(u);
          return (x.host + (x.pathname && x.pathname !== '/' ? x.pathname : '')).slice(0, 40);
        } catch (_) { return String(u).slice(0, 40); }
      })() : '';
      // 编辑类 tab desc 前缀用后缀专属 SVG 图标（file-icons.js）；hex/对比/日志
      // 用 icons.js 线性图标（a261：emoji 退役；内联位加 vertical-align 对齐）
      const edIcon = (isEdit && conn.meta.kind === 'editor') ? fileIconHtml(conn.meta.label || '', 12) + ' 笔记'
                    : conn.meta.kind === 'bindiff' ? '<span>' + ICO16.compare + '</span> bin 对比'
                    : isEdit ? (conn.meta.kind === 'hex' ? '<span>' + ICO16.wrench + '</span> hex'
                              : '<span>' + ICO16.compare + '</span> 对比')
                    : isLog ? '<span>' + ICO16.log + '</span> 日志' : '';
      // a209批4：编辑器/hex/对比外部文件副行显示【相对根路径】（用户点名
      //「打开的文件显示具体路径」）——VSCode OPEN EDITORS 同款信息密度
      const _pathTail = conn.extPath
        ? ((typeof _treeRootOf === 'function' && _treeRootOf(conn.extPath))
            ? String(conn.extPath).slice(_treeRootOf(conn.extPath).length + 1)
            : String(conn.extPath))
        : '';
      const descText = isSSH ? `SSH · ${conn.meta.host || ''}` : isTelnet ? `Telnet · ${conn.meta.host || ''}` : isShell ? `终端 · ${SHELL_LABEL[conn.meta.shell] || conn.meta.shell || ''}${conn.meta.cwd ? ' · ' + String(conn.meta.cwd).split(/[\\/]/).pop() : ''}` : (isEdit || isLog) ? (conn.extPath ? esc(_pathTail) : edIcon) : isVcs ? 'git / svn 工作副本' : isClaude ? `<span class="claude-ico"></span> Claude · ${(conn.meta.cwd || '').split(/[\\\\/]/).pop() || ''}` : isHarness ? `<span class="claude-ico"></span> Claude 对话 · ${(conn.meta.cwd || '').split(/[\\\\/]/).pop() || ''}` : isWeb ? webUrlDesc : `${conn.meta.baud || ''} baud`;
      const rowCount = conn.term ? conn.term.buffer.active.length : (conn.logState ? conn.logState.total : (isEdit ? _edStatText(conn) : 0));
      // 编辑器类 tab：未保存时名字带 * + dirty 类（led 橙色，与 _edMarkTab 同步）
      const isDirty = isEdit && conn.dirty;
      item.innerHTML = `
        <span class="led"></span>
        <div class="info">
          <div class="name">${(isDirty ? '*' : '') + esc(conn.meta.label || pid)}</div>
          <div class="desc" title="${conn.extPath ? esc(conn.extPath) : ''}">${(isEdit || isLog || isClaude || isHarness || isVcs) ? descText : esc(descText)}${isWeb ? '' : ' · <span class="baud" data-rows>' + (isEdit ? rowCount : rowCount + ' 行') + '</span>'}</div>
        </div>
        <div class="actions"><button data-close="${pid}" title="${isLog ? '关闭' : '断开'}">✕</button></div>
      `;
      if (isDirty) item.classList.add('dirty');
      item.onclick = (e) => {
        // hex 走 closeEditorTab（有脏确认）：落 closeConnection 会绕过
        // dirty 检查直接丢修改，还发一个必 404 的 /api/disconnect
        if (e.target.dataset.close) { e.stopPropagation();
          if (isLog) closeLogViewer(pid);
          else if (isEdit) closeEditorTab(pid);
          else if (isHarness) _harnessClose(pid);   // harness：SSE 清理 + 后端 /api/harness/disconnect
          else if (isVcs) closeEditorTab(pid);      // a434：版本面板（脏检查/清理链走通用）
          else closeConnection(pid);
          return; }
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
  // 【tab 位置不变量·用户铁律】tab 栏永不自动重排——除非用户手动移动（拖拽/
  // 固定/取消固定），位置永远保持打开时的落位（Chrome/所有浏览器的行为）。
  // 历史演进（均已退役）：
  //   v1 按类型桶自动重排（与侧栏列表同序）→ 用户新开的 tab 30s 内从末尾
  //     "跳"到类型组位置（乱七八糟的跳变源头）；
  //   v2 拖拽/pin 后让位 + a286R16 有 pinned 不重排——挡住了大部分但仍存在
  //     "无 pin 未拖拽"场景的重排跳变；
  //   v3（本条）整段重排退役：侧栏列表仍按类型排序展示（那是列表自己的排序），
  //     tab 栏只认用户的手。sortKeyFn/_tabOrderManual 保留定义（其他调用方
  //     仍在用），仅此处不再重排
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
  // 文档内搜索（v3.5.310 可配置，默认 Ctrl+F；loose=宽松保持原不排 Shift 行为）：
  // 日志 tab → 激活底部查找分栏
  const _docHit = (typeof hkMatch === 'function')
    ? hkMatch(e, window._HK && window._HK.docSearch, true)
    : (e.ctrlKey && (e.key === 'f' || e.key === 'F'));
  if (_docHit && activePortId) {
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
  // a581：telnet/shell 字段块也要复位——原来漏了 telnet，上次停在 telnet 时
  // 重开弹窗字段还亮着（既有缺陷，顺带修）
  $('connTelnetFields').style.display = 'none';
  $('connShellFields').style.display = 'none';
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
    $('connShellFields').style.display = _connType === 'shell' ? 'flex' : 'none';
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
      j = await connectSSH(host, port, username, password, key_path, true);
    } else if (_connType === 'telnet') {
      const host = $('connTelnetHost').value.trim();
      const port = $('connTelnetPort').value.trim() || '23';
      if (!host) { errEl.textContent = '请填主机地址'; errEl.classList.add('show'); return; }
      btn.textContent = '连接中…';
      j = await connectTelnet(host, port, true);
    } else if (_connType === 'shell') {
      const shell = $('connShellKind').value || 'cmd';
      const cwd = $('connShellCwd').value.trim();
      // 非空时必须是绝对路径（Windows 盘符或 UNC），否则后端子进程 cwd 会
      // 相对工具进程解析，用户看到「目录不存在」却不知为何
      if (cwd && !/^[a-zA-Z]:[\\/]|^\\\\/.test(cwd)) {
        errEl.textContent = '工作目录请填绝对路径，如 D:\\AI\\前端控制台';
        errEl.classList.add('show'); return;
      }
      btn.textContent = '打开中…';
      j = await connectShell(shell, cwd, true);
    } else {
      const port = $('connPort').value, baud = $('connBaud').value;
      if (!port) { errEl.textContent = '请选择串口'; errEl.classList.add('show'); return; }
      btn.textContent = '连接中…';
      j = await connectPort(port, baud, true);
    }
    if (j && j.ok) $('connModal').classList.remove('show');
    else { errEl.textContent = '失败：' + ((j && j.err) || '未知错误'); errEl.classList.add('show'); }
  } finally {
    btn.disabled = false; btn.textContent = oldText;
  }
};
$('btnRefreshPorts').onclick = async () => { await loadPorts(); showBanner('串口端口已刷新'); };
// a581：终端工作目录选择器（复用 pywebview 原生目录对话框，同 tftp 的写法）
const _shPick = $('connShellCwdPick');
if (_shPick) _shPick.onclick = async () => {
  try {
    if (!(window.pywebview && window.pywebview.api && window.pywebview.api.pick_dir))
      throw new Error('no-bridge');
    let d = await window.pywebview.api.pick_dir();
    if (Array.isArray(d)) d = d[0] || '';
    if (d) $('connShellCwd').value = d;
  } catch (e) {
    showBanner('目录选择器暂不可用，可直接输入路径', 3000, true);
  }
};

// 终端功能按钮（暂停/清屏/^C/^D/时间戳等）已移到各连接区顶部工具栏
// （terminal-core.js buildTerminal 内，仿日志 tab 的 log-viewer-toolbar），
// tab 栏保持整洁——按钮只作用于所属连接，不再作用于全局活动 tab。
// 关于按钮已改为「换肤」（js/theme.js 接管），版本号常驻标题栏「PRO v0.5.0」
// 顶栏「打开日志目录」已移除（日志库弹窗内有同功能入口 btnLogDirOpen）

// ============================================================
// 最近打开（SSH/串口/文件 快捷重开，后端 config.json 持久化 + 自动去重）
// ============================================================
const RECENT_ICON = { claude: '<span class="claude-ico"></span>', ssh: '<span>' + ICO16.link + '</span>', serial: '<span>' + ICO16.plug + '</span>', telnet: '<span>' + ICO16.monitor + '</span>', shell: '<span>' + ICO16.terminal + '</span>' };  // 类型区分图标（claude 用官方星形标志；file 按后缀动态生成 fileIconHtml）
const RECENT_TYPE_NAME = { claude: 'Claude 会话', ssh: 'SSH', serial: '串口', telnet: 'Telnet', file: '文件', shell: '终端' };
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
  el.innerHTML = '';
  // a430（用户令）：固定项置顶区——不按 SSH/串口分类，一行 = 类型前缀 +
  // label（例：串口 COM1 @115200 / SSH gaoyi13@ip / 文件 xxx.c）；
  // 下方为非固定的原状分组列表
  const pinned = _recentList.map((it, i) => ({it, i})).filter(x => x.it.pin);
  if (pinned.length) {
    const ph = document.createElement('div');
    ph.className = 'recent-group-head t-pin';
    ph.innerHTML = `◆ 置顶 <span class="g-line"></span>`;
    el.appendChild(ph);
    pinned.forEach(({it, i}) => el.appendChild(_recentItemEl(it, i, true)));
  }
  // 按类型分组，组内保持原新→旧顺序（claude 分组已移除——会话恢复改走
  // claude 自带 /resume 选择界面，不再在工具侧直连）
  const groups = [
    { type: 'serial', name: '串口' },
    { type: 'file',   name: '文件' },
    { type: 'ssh',    name: 'SSH' },
    { type: 'telnet', name: 'Telnet' },
    { type: 'shell',  name: '终端' },
  ];
  groups.forEach(g => {
    const items = _recentList.map((it, i) => ({it, i}))
      .filter(x => x.it.type === g.type && !x.it.pin);
    if (!items.length) return;
    const gh = document.createElement('div');
    gh.className = 'recent-group-head t-' + g.type;
    gh.innerHTML = `${RECENT_ICON[g.type] || '·'} ${g.name} <span class="g-line"></span>`;
    el.appendChild(gh);
    items.forEach(({it, i}) => el.appendChild(_recentItemEl(it, i)));
  });
}

function _recentItemEl(it, i, pinned) {
  const d = document.createElement('div');
  d.className = 'recent-item t-' + it.type + (pinned ? ' pinned' : '');
  // claude 条目 label 动态替换：记入时固化的「Claude · 目录名」会重名且不随备注更新，
  // 按 session_id 从会话数据取当前显示名（备注 > aiTitle > 摘要，_claudeTitleMap）
  const showLabel = (it.type === 'claude' && it.data && it.data.resume &&
                    typeof _claudeTitleMap !== 'undefined' &&
                    _claudeTitleMap[it.data.resume]) || it.label;
  d.title = `${RECENT_TYPE_NAME[it.type]} · ${showLabel}（点击快速打开）`;
  // file 类型按后缀出专属 SVG 图标（file-icons.js），其余用类型 emoji
  const ico = it.type === 'file' ? fileIconHtml(it.label || it.data?.name || '', 14)
                                 : (RECENT_ICON[it.type] || '·');
  // a430：固定项显示形态=「类型前缀 label」（如 串口 COM1 @115200），
  // 不再依赖分组头
  const nameHtml = pinned
    ? `<span class="pin-type">${esc(RECENT_TYPE_NAME[it.type] || it.type)}</span> ${esc(showLabel)}`
    : esc(showLabel);
  d.innerHTML = `
    <span class="ric">${ico}</span>
    <div class="info">
      <div class="name">${nameHtml}</div>
    </div>
    <div class="actions"><button data-del="${i}" title="从列表移除">✕</button></div>
  `;
  d.onclick = (e) => {
    if (e.target.dataset.del !== undefined) { e.stopPropagation(); removeRecentItem(i); return; }
    openRecentItem(it);
  };
  // a430（用户令）：右键菜单——固定/取消固定（无条件保存+置顶）
  d.oncontextmenu = (e) => {
    e.preventDefault();
    if (typeof buildCtxMenu !== 'function') return;
    buildCtxMenu(e.clientX, e.clientY, [
      { label: it.pin ? '取消固定' : '固定到置顶', action: () => toggleRecentPin(it) },
      { sep: true },
      { label: '从列表移除', action: () => removeRecentItem(i) },
    ]);
  };
  return d;
}

async function toggleRecentPin(it) {
  if (!it || !it.key) return;
  try {
    const r = await fetch('/api/recent', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin_toggle: it.key }) });
    const j = await r.json();
    if (j.ok && Array.isArray(j.recent)) {
      _recentList = j.recent.filter(x => x.type !== 'claude');
      renderRecentList();
    } else if (j.err) showBanner('固定失败：' + j.err, 2500, true);
  } catch (e) { showBanner('固定失败: ' + e, 2500, true); }
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
  } else if (it.type === 'shell') {
    const d = it.data || {};
    connectShell(d.shell || 'cmd', d.cwd || '');
  } else if (it.type === 'file') {
    // 文件分发：外部文件（extPath 绝对路径，含拖入）统一走 openDroppedFile 智能分发
    // （文本类含小 .log → 编辑器，超大 .log/未知 → 查看器）；
    // 站内文件（files/ 内 .note/.txt 等，只有 name 无绝对路径）必须走 openEditorFile(name=)——
    // 之前一律 openDroppedFile 按绝对路径请求，后端拒收相对名 →「不支持的文件类型或文件不存在」。
    const d = it.data || {};
    if ((d.kind === 'diff' || d.kind === 'bindiff') && d.a && d.b) buildDiffViewerTab(d.a, d.b);   // 文件对比（文本/二进制）：A/B 两份快速重开
    else if (d.kind === 'office' && d.path) openOfficeFile(d.path);   // a302：word/excel/ppt 快速重开（office viewer tab）
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
