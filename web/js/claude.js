// ============================================================
// Claude Code 集成（第 1 期）：顶栏按钮 → /api/connect kind='claude'
// → 复用 buildTerminal 建 xterm tab（ConPTY 跑真实 claude CLI，保真终端）。
// 设计文档：docs/CLAUDE_CODE_INTEGRATION.md
// ============================================================

async function connectClaude(opts = {}) {
  // opts: {cwd, resume, label} —— resume 场景由 Claude 面板调用
  try {
    // 工具壳体是亮色主题时，让本会话 claude 也用 light 主题（后端经 --settings
    // 注入，只作用于该进程，不写配置文件、不影响其他终端的会话）
    const curTheme = document.documentElement.getAttribute('data-theme') || 'deepblue';
    const lightTheme = LIGHT_THEMES.includes(curTheme);
    const body = {kind: 'claude', cwd: opts.cwd || '', resume: opts.resume || '',
                  light_theme: lightTheme};
    const r = await fetch('/api/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || 'claude 启动失败', 6000, true); return j; }
    const portId = j.port_id;
    // tab 结构与其他类型统一：led（进程状态灯）+ 图标 + 文字；emoji 不再塞 label
    const label = opts.label || (j.resume ? `恢复 ${j.resume.slice(0,8)}` : 'Claude');
    const conn = buildTerminal(portId, {kind:'claude', label, cwd: j.cwd, baud: ''});
    // buildTerminal 的 tab 无图标位——claude tab 补一个（🤖），插在 led 后
    const ico = document.createElement('span');
    ico.className = 'tab-ico';
    ico.textContent = '🤖';
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
    // 恢复的会话记入「最近」（key=会话 id 去重置顶）——新会话不记（id 未知，无重开价值）
    if (j.resume && typeof _recentAdd === 'function') {
      const dirName = (j.cwd || '').split(/[\\/]/).pop() || '';
      _recentAdd({type:'claude', key:'claude:' + j.resume, resume: j.resume,
                  label:`Claude · ${dirName}`, data:{resume: j.resume, cwd: j.cwd}});
    }
    return j;
  } catch(e) {
    showBanner('claude 启动请求失败: ' + e, 5000, true);
    return {ok: false};
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
    document.querySelectorAll('.claude-sheet-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.claude-sheet-pane').forEach(p =>
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
