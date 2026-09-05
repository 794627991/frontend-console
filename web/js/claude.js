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

async function refreshClaudePanel() {
  try {
    // 运行中（本工具 + 外部活跃）
    const rs = await (await fetch('/api/claude/status')).json();
    const dot = $('claudeStatusDot'), txt = $('claudeStatusText');
    const nMine = (rs.mine || []).length, nExt = rs.external_active || 0;
    if (nMine) { dot.className = 'dot on'; txt.textContent = `${nMine} 个会话运行中` + (nExt ? ` · 外部活跃 ${nExt}` : ''); }
    else if (nExt) { dot.className = 'dot on'; txt.textContent = `外部活跃 ${nExt} 个会话`; }
    else { dot.className = 'dot'; txt.textContent = '无运行中的会话'; }

    const runningEl = $('claudeRunning');
    const runKey = (rs.mine || []).map(m => `${m.port_id}:${m.alive}`).join(',') + '#' + nExt;
    if (runKey !== _claudeRunningKey) {
      _claudeRunningKey = runKey;
      const mineRows = (rs.mine || []).map(m =>
        `<div class="claude-run" data-port="${esc(m.port_id)}">
           <span class="live-dot"></span>
           <span class="cname">${esc((m.cwd || '').split(/[\\\\/]/).pop() || m.port_id)}</span>
           <span class="cstate">${m.alive ? '运行中' : '已退出'}</span>
         </div>`).join('');
      runningEl.innerHTML = mineRows ||
        (nExt ? `<div class="claude-empty">外部进程活跃（本工具未打开）</div>` : '<div class="claude-empty">—</div>');
      runningEl.querySelectorAll('.claude-run').forEach(r =>
        r.onclick = () => switchTab(r.dataset.port));
    }

    // 历史会话（点击恢复）
    const ss = await (await fetch('/api/claude/sessions?limit=30')).json();
    const sessEl = $('claudeSessions');
    const sessions = ss.sessions || [];
    const sessKey = sessions.map(s => `${s.session_id}:${s.mtime}:${s.active ? 1 : 0}`).join(',');
    if (sessKey !== _claudeSessionsKey) {
      _claudeSessionsKey = sessKey;
      if (!sessions.length) {
        sessEl.innerHTML = '<div class="claude-empty">暂无会话（~/.claude/projects 为空）</div>';
      } else {
        sessEl.innerHTML = sessions.map(s => {
          const dirName = (s.cwd || '').split(/[\\\\/]/).pop() || s.project;
          // title = aiTitle 优先（后台总览同款会话名），无则首条消息摘要；
          // 目录名降级进 title 属性提示
          return `<div class="claude-sess" data-resume="${esc(s.session_id)}" data-cwd="${esc(s.cwd || '')}" data-title="${esc(s.title || s.summary || '')}" title="${esc((s.title ? dirName + ' · ' : '') + (s.summary || '') + '  @' + (s.cwd || ''))}">
            <div class="srow1">
              ${s.active ? '<span class="live-dot"></span>' : ''}
              <span class="cdir">${esc(s.title || s.summary || dirName)}</span>
              <span class="ctime">${esc(_claudeRelTime(s.last_ts || s.first_ts))}</span>
            </div>
            <div class="srow2">${esc(s.title ? (s.summary || dirName) : dirName)}</div>
          </div>`;
        }).join('');
        sessEl.querySelectorAll('.claude-sess').forEach(el =>
          el.onclick = () => {
            // 已打开的恢复会话直接切过去（后端按 resume 去重报错，前端先自查）
            const exist = `claude:r-${(el.dataset.resume || '').slice(0, 8)}`;
            if (connections[exist]) { switchTab(exist); return; }
            // tab 标题用会话名（不是「恢复+哈希」——哈希对用户无意义）
            const label = el.dataset.title || `Claude`;
            connectClaude({resume: el.dataset.resume, cwd: el.dataset.cwd, label});
          });
      }
    }

    // 技能（cwd 取当前 claude tab 的，没有则不带 → 只有 user+plugin）
    const curClaude = Object.values(connections).find(c => c.meta && c.meta.kind === 'claude');
    const sk = await (await fetch('/api/claude/skills' + (curClaude && curClaude.meta.cwd ? '?cwd=' + encodeURIComponent(curClaude.meta.cwd) : ''))).json();
    const skillsEl = $('claudeSkills');
    const skills = sk.skills || [];
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
