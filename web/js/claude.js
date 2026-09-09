// ============================================================
// Claude Code 集成（第 1 期）：顶栏按钮 → /api/connect kind='claude'
// → 复用 buildTerminal 建 xterm tab（ConPTY 跑真实 claude CLI，保真终端）。
// 设计文档：docs/CLAUDE_CODE_INTEGRATION.md
// ============================================================

async function connectClaude(opts = {}) {
  // opts: {cwd, resume, label} —— resume 场景由 Claude 面板调用；
  // resume='__picker__' 是侧栏兼容哨兵：不带会话 id 启动 claude，进 TUI 后
  // 自动敲 /resume 让用户在 claude 自带的会话选择界面里挑（不直连具体会话）
  const pickerMode = opts.resume === '__picker__';
  try {
    // 工具壳体是亮色主题时，让本会话 claude 也用 light 主题（后端经 --settings
    // 注入，只作用于该进程，不写配置文件、不影响其他终端的会话）
    const curTheme = document.documentElement.getAttribute('data-theme') || 'deepblue';
    const lightTheme = LIGHT_THEMES.includes(curTheme);
    const body = {kind: 'claude', cwd: opts.cwd || '',
                  resume: pickerMode ? '' : (opts.resume || ''),
                  light_theme: lightTheme};
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)});
    const j = await r.json();
    if (!j.ok) {
      // claude CLI 缺失 → 弹安装引导窗（联网/离线双通道），不再只弹 banner
      if (j.err && j.err.includes('未检测到 claude')) { openClaudeSetup(); return j; }
      showBanner(j.err || 'claude 启动失败', 6000, true); return j;
    }
    const portId = j.port_id;
    // tab 结构与其他类型统一：led（进程状态灯）+ 图标 + 文字；emoji 不再塞 label
    const label = opts.label || (j.resume ? `恢复 ${j.resume.slice(0,8)}` : 'Claude');
    const conn = buildTerminal(portId, {kind:'claude', label, cwd: j.cwd, baud: ''});
    // buildTerminal 的 tab 无图标位——claude tab 补一个（官方星形标志），插在 led 后
    const ico = document.createElement('span');
    ico.className = 'tab-ico claude-ico';
    conn.tab.insertBefore(ico, conn.tab.querySelector('span:nth-child(2)'));
    connections[portId] = conn;
    switchTab(portId);
    refreshSidebar();
    refreshGlobalStatus();
    showBanner(j.msg || 'claude 已启动');
    // 新开/恢复 claude 会话后立即聚焦终端：用户打开就是为了输入，不想先点一下
    // switchTab 里已有 term.focus()，但 claude TUI 启动时 ConPTY 输出会触发
    // xterm 内部重新渲染/滚动，可能再次夺走焦点——延迟再抢一次，确保落在输入框
    setTimeout(() => {
      try { if (connections[portId] === conn) conn.term.focus(); } catch(_){}
    }, 300);
    // picker 模式：等 TUI 就绪后自动敲 /resume，弹出 claude 自带会话选择界面
    if (pickerMode) {
      setTimeout(() => {
        try {
          if (connections[portId] === conn) {
            const bytes = [];
            for (const ch of '/resume\r') bytes.push(ch.charCodeAt(0));
            termSendRaw(portId, bytes);
          }
        } catch(_){}
      }, 1500);
    }
    // 恢复的会话不再记入「最近」——该功能已按用户要求移除（问题反复，回归
    // 「自己 /resume 选会话」的原生流程：侧栏/快捷打开不再直连具体会话）
    return j;
  } catch(e) {
    showBanner('claude 启动请求失败: ' + e, 5000, true);
    return {ok: false};
  }
}

// ============================================================
// Claude 安装引导窗：首次打开检测不到 CLI 时弹出。
// 双通道：联网（npm install -g）/ 离线（打包资源静默装：Git+Node+claude-code）。
// 后端 src/claude_setup.py；日志轮询 /api/claude/setup_poll。
// ============================================================

let _csPollTimer = null;

async function openClaudeSetup() {
  let m = $('claudeSetupModal');
  if (!m) {
    m = document.createElement('div');
    m.className = 'modal';
    m.id = 'claudeSetupModal';
    m.innerHTML = `
      <div class="box" style="width:560px;">
        <div class="head">
          <strong>安装 Claude Code</strong>
          <div class="head-actions"><button class="btn ghost icon-btn" id="csClose">✕</button></div>
        </div>
        <div style="padding:16px 20px;display:flex;flex-direction:column;gap:12px;">
          <div id="csDetect" style="font-size:12px;line-height:1.8;"></div>
          <div id="csErr" style="color:var(--neon-red);font-size:11px;display:none;"></div>
          <div id="csLog" class="cs-log" style="display:none;"></div>
        </div>
        <div class="actions" style="padding:0 20px 16px;display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;">
          <button class="btn ghost" id="csPack" title="把本机的 Git 安装器 + Node MSI + claude-code 包打成一个 zip，拷到无网机器离线安装">📦 制作离线包</button>
          <button class="btn ghost" id="csOfflineZip" title="选择已有 claude-offline.zip 静默安装">📂 用离线包安装</button>
          <button class="btn ghost" id="csOfflineDirect" title="用本机已下载的安装环境资源直接静默安装（无需 zip）">⚡ 离线直装</button>
          <button class="btn primary" id="csOnline" title="npm install -g @anthropic-ai/claude-code（需联网 + Node）">🌐 联网安装</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    $('csClose').onclick = () => { _csStopPoll(); m.classList.remove('show'); };
    $('csPack').onclick = () => _csPickPackDir();
    $('csOfflineZip').onclick = () => _csPickZip();
    $('csOfflineDirect').onclick = () => _csStart('offline');
    $('csOnline').onclick = () => _csStart('online');
  }
  m.classList.add('show');
  _csDetectRender();
}

async function _csDetectRender() {
  const el = $('csDetect');
  el.innerHTML = '<span style="color:var(--muted)">检测中…</span>';
  try {
    const st = await (await fetch('/api/claude/setup_status')).json();
    const row = (label, ok, extra='') =>
      `<div>${ok ? '<span style="color:var(--accent)">✓</span>' : '<span style="color:var(--neon-red)">✗</span>'} ${label}${extra ? ` <span style="color:var(--muted);font-size:11px;">${extra}</span>` : ''}</div>`;
    const mb = st.pkg_size ? ` · ${(st.pkg_size/1024/1024).toFixed(0)} MB` : '';
    const res = [];
    if (st.claude) res.push(row('Claude CLI 已安装 —— 无需安装，直接点顶栏 Claude 打开', true));
    res.push(row('Node.js / npm', st.node && st.npm, st.node ? '' : '离线包/直装会静默安装'));
    res.push(row('Git', st.git, st.git ? '' : '离线包/直装会静默安装'));
    res.push(row('claude-code 包（离线打包源）', !!st.pkg_dir, st.pkg_dir ? st.pkg_dir.split('\\\\').pop() + mb : '本机没有 npm 包，只能联网装或用 zip'));
    if (st.git_installer || st.node_installer) res.push(row('离线安装器资源（D:\\AI\\安装环境）', true,
      [st.git_installer, st.node_installer].filter(Boolean).map(p => p.split('\\\\').pop()).join(' + ')));
    else res.push('<span style="color:var(--muted);font-size:11px;">未找到离线安装器资源（D:\\AI\\安装环境）——只能联网安装或用已有 zip</span>');
    el.innerHTML = res.join('');
    // 联网按钮始终显示：Node/Git 缺了会自动静默补装（下载官方安装器），
    // 不再把"无 npm"当拦截条件
    $('csOnline').style.display = '';
    $('csOfflineDirect').style.display = (st.pkg_dir || st.git_installer || st.node_installer) ? '' : 'none';
    $('csPack').style.display = st.pkg_dir ? '' : 'none';
  } catch (e) {
    el.innerHTML = '<span style="color:var(--neon-red)">检测失败: ' + esc(String(e)) + '</span>';
  }
}

function _csStopPoll() {
  if (_csPollTimer) { clearInterval(_csPollTimer); _csPollTimer = null; }
}

function _csStart(mode, extra) {
  const api = mode === 'pack' ? '/api/claude/setup_offline_pack' : '/api/claude/setup_install';
  const body = extra || (mode === 'online' ? {mode:'online'} : {mode:'offline'});  const logEl = $('csLog');
  logEl.style.display = '';
  logEl.innerHTML = '';
  ['csPack','csOfflineZip','csOfflineDirect','csOnline'].forEach(id => $(id).disabled = true);
  fetch(api, {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)})
    .then(r => r.json())
    .then(j => {
      if (!j.ok) { $('csErr').style.display = ''; $('csErr').textContent = j.err || '启动失败'; return; }
      _csStopPoll();
      _csPollTimer = setInterval(async () => {
        try {
          const s = await (await fetch('/api/claude/setup_poll')).json();
          logEl.innerHTML = (s.log || []).map(l =>
            `<div>${esc(l.msg)}</div>`).join('');
          logEl.scrollTop = logEl.scrollHeight;
          if (s.done) {
            _csStopPoll();
            ['csPack','csOfflineZip','csOfflineDirect','csOnline'].forEach(id => $(id).disabled = false);
            if (s.ok) {
              showBanner('Claude Code 安装完成');
              _csDetectRender();
              // 装好后直接拉起 claude（用户点安装就是为了用）
              setTimeout(() => { $('claudeSetupModal').classList.remove('show'); connectClaude(); }, 800);
            } else {
              $('csErr').style.display = '';
              $('csErr').textContent = s.err || '安装失败';
            }
          }
        } catch(_) {}
      }, 700);
    })
    .catch(e => {
      ['csPack','csOfflineZip','csOfflineDirect','csOnline'].forEach(id => $(id).disabled = false);
      $('csErr').style.display = ''; $('csErr').textContent = '请求失败: ' + e;
    });
}

function _csPickPackDir() {
  // 打包输出目录：pywebview 原生目录选择（pick_dir 已有），默认桌面
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_dir) {
    window.pywebview.api.pick_dir().then(d => {
      _csStart('pack', {out_dir: d || ''});
    }).catch(() => showBanner('目录选择失败', 3000, true));
  } else {
    _csStart('pack', {out_dir: ''});   // 后端默认桌面
  }
}

function _csPickZip() {
  // 前端文件选择：pywebview 原生对话框（pick_any，不限制类型，返回 str）
  if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_any) {
    window.pywebview.api.pick_any().then(p => {
      const path = Array.isArray(p) ? p[0] : p;
      if (path && /\.zip$/i.test(path)) _csStart('offline', {mode:'offline', zip_path:path});
      else if (path) showBanner('请选择 claude-offline.zip 离线包', 3000, true);
    }).catch(() => showBanner('文件选择失败', 3000, true));
  } else {
    // pywebview bridge 不可用（纯浏览器调试态）：退回原生 input[type=file]
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.zip';
    inp.onchange = () => {
      const f = inp.files[0];
      // 浏览器态拿不到绝对路径（fakepath）——提示走后端通道
      if (f) showBanner('WebView 桥不可用：请在工具窗口内操作', 3000, true);
    };
    inp.click();
  }
}

// ============================================================
// Claude 面板（第 2 期）：运行中会话 / 历史会话（点击恢复）/ 技能
// 数据源：GET /api/claude/status + /api/claude/sessions + /api/claude/skills
// 轮询由 init.js 驱动（pane 可见才发请求，照 analyze 模式）
// ============================================================

// 时间戳 → 相对时间（"3 分钟前"），面板紧凑显示
function _claudeRelTime(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  if (diff < 86400 * 30) return Math.floor(diff / 86400) + ' 天前';
  return new Date(t).toLocaleDateString();
}

// 脏检查 key：内容没变跳过 innerHTML 重建（照 refreshMcpInfo 模式）
let _claudeSessionsKey = '', _claudeRunningKey = '', _claudeSkillsKey = '';

// 会话备注：✎ 点击弹模态框（项目 modal 风格，不用原生 prompt），POST /api/claude/note。
// 标题优先级：备注 > aiTitle > 首条消息。后端写工具 config.json（claude_notes 键）。
function _claudeEditNote(sessionId, curTitle) {
  let m = $('claudeNoteModal');
  if (!m) {
    m = document.createElement('div');
    m.className = 'modal';
    m.id = 'claudeNoteModal';
    m.innerHTML = `
      <div class="box" style="width:420px;">
        <div class="head">
          <strong>会话备注</strong>
          <div class="head-actions"><button class="btn ghost icon-btn" id="claudeNoteClose">✕</button></div>
        </div>
        <div style="padding:18px 20px;display:flex;flex-direction:column;gap:14px;">
          <input type="text" id="claudeNoteInput" class="note-input" placeholder="备注名（留空清除——显示优先于 AI 标题）" autocomplete="off" maxlength="60">
          <div id="claudeNoteHint" style="color:var(--muted);font-size:11px;line-height:1.5;"></div>
        </div>
        <div class="actions" style="padding:0 20px 18px;display:flex;justify-content:flex-end;gap:8px;">
          <button class="btn ghost" id="claudeNoteCancel">取消</button>
          <button class="btn primary" id="claudeNoteSave">保存</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    const finish = () => m.classList.remove('show');
    $('claudeNoteClose').onclick = finish;
    $('claudeNoteCancel').onclick = finish;
    $('claudeNoteSave').onclick = () => {
      const note = $('claudeNoteInput').value.trim();
      fetch('/api/claude/note', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({session_id: m.dataset.sid, note})})
        .then(() => { finish(); _claudeSessionsKey = ''; _claudeRunningKey = ''; refreshClaudePanel(); })
        .catch(() => showBanner('备注保存失败', 3000, true));
    };
    // 回车保存 / Esc 取消（项目 modal 惯例）
    $('claudeNoteInput').addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); $('claudeNoteSave').click(); }
      if (e.key === 'Escape') { e.preventDefault(); finish(); }
    });
  }
  m.dataset.sid = sessionId;
  $('claudeNoteInput').value = curTitle || '';
  // 提示行带会话 ID 尾段（识别是哪个会话）
  $('claudeNoteHint').textContent = '会话 ' + (sessionId || '').slice(0, 8) + ' · 备注只影响本工具内显示';
  m.classList.add('show');
  setTimeout(() => { $('claudeNoteInput').focus(); $('claudeNoteInput').select(); }, 50);
}

// 卡片生成共用：会话行（含 ✎ 备注按钮）+ 点击行为绑定。
// sel 容器、resume 恢复逻辑与历史/活跃两 sheet 一致。
function _claudeSessionCard(s, opts = {}) {
  const dirName = (s.cwd || '').split(/[\\\\/]/).pop() || s.project;
  const hasNote = !!s.note;
  return `<div class="claude-sess" data-resume="${esc(s.session_id)}" data-cwd="${esc(s.cwd || '')}" data-title="${esc(s.title || s.summary || '')}" data-sid="${esc(s.session_id)}" title="${esc((hasNote ? '备注：' + s.note + ' · ' : '') + (s.title ? dirName + ' · ' : '') + (s.summary || '') + '  @' + (s.cwd || ''))}">
    <div class="srow1">
      ${opts.live ? '<span class="live-dot"></span>' : ''}
      <span class="cdir${hasNote ? ' noted' : ''}">${esc(s.title || s.summary || dirName)}</span>
      ${opts.ext ? '<span class="cstate">外部</span>' : ''}
      <span class="ctime">${esc(opts.time || '')}</span>
      <button class="note-btn" data-note="${esc(s.session_id)}" title="改备注（显示优先）">✎</button>
    </div>
    <div class="srow2"><span class="sum">${esc(s.title ? (s.summary || dirName) : dirName)}</span><span class="sid">${esc((s.session_id || '').slice(0, 8))}</span></div>
  </div>`;
}
function _claudeBindCards(container) {
  container.querySelectorAll('.claude-sess').forEach(el => {
    el.querySelector('.note-btn').onclick = (e) => {
      e.stopPropagation();
      const c = el.querySelector('.cdir');
      _claudeEditNote(el.dataset.sid, c ? c.textContent : '');
    };
    el.onclick = () => {
      const exist = `claude:r-${(el.dataset.resume || '').slice(0, 8)}`;
      if (connections[exist]) { switchTab(exist); return; }
      connectClaude({resume: el.dataset.resume, cwd: el.dataset.cwd, label: el.dataset.title || 'Claude'});
    };
  });
}
document.querySelectorAll('.claude-sheet-tab').forEach(tab => {
  tab.onclick = () => {
    // 按父容器分组切换：MCP 子 sheet 内嵌第二级页签（工具/最近调用），
    // 与一级（活跃/历史/技能/MCP）互不干扰——全局切换会互相误关。
    // 结构约定：.claude-sheets（页签行）与 .claude-sheet-pane（内容）是兄弟，
    // 都挂在同一个父容器下——切换只动本容器内的 pane。
    const sheetsRow = tab.parentElement;
    sheetsRow.querySelectorAll('.claude-sheet-tab').forEach(t => t.classList.toggle('active', t === tab));
    sheetsRow.parentElement.querySelectorAll(':scope > .claude-sheet-pane').forEach(p =>
      p.classList.toggle('active', p.dataset.sheet === tab.dataset.sheet));
  };
});
function _claudeSetCount(id, n) {
  const el = $(id);
  if (el && el.textContent !== String(n)) el.textContent = n;
}

// 会话标题映射（session_id → 当前显示名，含备注/aiTitle）——供「最近」列表
// 渲染时替换固化 label：_recentAdd 记的是「Claude · 目录名」，之后改备注/aiTitle
// 变了旧 label 就全是重名，必须按 id 动态取当前名
let _claudeTitleMap = {};
function _claudeUpdateTitleMap(sessions) {
  const m = {};
  (sessions || []).forEach(s => { m[s.session_id] = s.title || s.summary || ''; });
  _claudeTitleMap = m;
  if (typeof renderRecentList === 'function') renderRecentList();
}

// 重名区分：同名会话卡（aiTitle/首条消息相同——测试会话常见）光看名字分不出来，
// 给重名卡的名字后面拼上相对时间（"17 分钟前"）区分。三处列表共用。
function _claudeMarkDupNames(sessions) {
  const byName = {};
  (sessions || []).forEach(s => { (byName[s.title] = byName[s.title] || []).push(s); });
  Object.values(byName).forEach(arr => {
    if (arr.length > 1) {
      arr.forEach(s => {
        s.title = s.title + ' · ' + (_claudeRelTime(s.last_ts || s.first_ts) || s.session_id.slice(0, 8));
      });
    }
  });
  return sessions;
}

async function refreshClaudePanel() {
  try {
    // 状态聚合（本工具连接 + 外部活跃计数）
    const rs = await (await fetch('/api/claude/status')).json();
    // 活跃 sheet：本工具打开的 + 外部活跃的（历史会话里 active 的那批）
    const ss = await (await fetch('/api/claude/sessions?limit=50')).json();
    const sessions = _claudeMarkDupNames(ss.sessions || []);
    _claudeUpdateTitleMap(sessions);
    const activeExt = sessions.filter(s => s.active);
    const dot = $('claudeStatusDot'), txt = $('claudeStatusText');
    const nMine = (rs.mine || []).length, nExt = rs.external_active || 0;
    if (nMine) { dot.className = 'dot on'; txt.textContent = `${nMine} 个会话运行中` + (nExt ? ` · 外部活跃 ${nExt}` : ''); }
    else if (nExt) { dot.className = 'dot on'; txt.textContent = `外部活跃 ${nExt} 个会话`; }
    else { dot.className = 'dot'; txt.textContent = '无运行中的会话'; }
    _claudeSetCount('claudeActiveCount', nMine + nExt);
    _claudeSetCount('claudeHistoryCount', sessions.length - nExt);
    _claudeSetCount('claudeSkillCount', -1);   // 占位：技能数到手后覆盖

    const runningEl = $('claudeRunning');
    // key 含 label（重命名/aiTitle 更新生效）与外部活跃集（进出活跃态刷新）
    const runKey = (rs.mine || []).map(m => `${m.port_id}:${m.label}:${m.alive}`).join(',') + '#' +
                   activeExt.map(s => s.session_id).join(',');
    if (runKey !== _claudeRunningKey) {
      _claudeRunningKey = runKey;
      // 运行中卡片升级成完整会话卡（含摘要行/✎ 备注/会话 id）——与历史卡同模板，
      // 不再挂 claude-run 类（旧单行 flex 样式与两行模板打架把排版挤坏），
      // 点击行为靠 data-port 属性绑定：切到对应终端 tab
      const mineRows = (rs.mine || []).map(m => {
        // 重名标记后的标题优先（与面板其余卡片口径一致）；无会话数据回退 label
        const marked = sessions.find(s => s.session_id === m.resume);
        const card = _claudeSessionCard(
          {session_id: m.resume || m.port_id, title: (marked && marked.title) || m.label,
           summary: (marked && marked.summary) || m.summary || '',
           cwd: m.cwd, note: (marked && marked.note) || m.note},
          {live: true, time: m.alive ? '运行中' : '已退出'});
        return card.replace('<div class="claude-sess"', `<div class="claude-sess" data-port="${esc(m.port_id)}"`);
      }).join('');
      // 外部活跃会话卡片：点击同样恢复进来（与历史一致），带 ✎ 备注入口
      const extRows = activeExt.filter(s => !(rs.mine || []).some(m => m.resume === s.session_id))
        .map(s => _claudeSessionCard(s, {live: true, ext: true})).join('');
      runningEl.innerHTML = (mineRows + extRows) || '<div class="claude-empty">无活跃会话</div>';
      _claudeBindCards(runningEl);   // 先绑通用（备注 ✎），再按 data-port 覆盖运行中卡为切 tab
      runningEl.querySelectorAll('.claude-sess[data-port]').forEach(r =>
        r.onclick = () => switchTab(r.dataset.port));
    }

    // 历史 sheet：非活跃的主体会话（活跃的在「活跃」sheet）
    const sessEl = $('claudeSessions');
    const history = sessions.filter(s => !s.active);
    const sessKey = history.map(s => `${s.session_id}:${s.mtime}:${s.title}`).join(',');
    if (sessKey !== _claudeSessionsKey) {
      _claudeSessionsKey = sessKey;
      sessEl.innerHTML = history.length
        ? history.map(s => _claudeSessionCard(s, {time: _claudeRelTime(s.last_ts || s.first_ts)})).join('')
        : '<div class="claude-empty">暂无历史会话</div>';
      _claudeBindCards(sessEl);
    }

    // 技能 sheet（cwd 取当前 claude tab 的，没有则不带 → 只有 user+plugin）
    const curClaude = Object.values(connections).find(c => c.meta && c.meta.kind === 'claude');
    const sk = await (await fetch('/api/claude/skills' + (curClaude && curClaude.meta.cwd ? '?cwd=' + encodeURIComponent(curClaude.meta.cwd) : ''))).json();
    const skillsEl = $('claudeSkills');
    const skills = sk.skills || [];
    _claudeSetCount('claudeSkillCount', skills.length);
    const skillsKey = skills.map(s => `${s.source}:${s.name}`).join(',');
    if (skillsKey !== _claudeSkillsKey) {
      _claudeSkillsKey = skillsKey;
      skillsEl.innerHTML = skills.length ? skills.map(s =>
        `<div class="claude-skill">
           <span class="sk-name">${esc(s.name)}</span>
           <span class="sk-src src-${esc(s.source)}">${s.source === 'user' ? '用户' : s.source === 'project' ? '项目' : '插件'}</span>
           <div class="sk-desc">${esc(s.desc || '')}</div>
         </div>`).join('') : '<div class="claude-empty">—</div>';
    }
  } catch(e) {}
}
