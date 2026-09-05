// ============================================================
// Claude Code 集成（第 1 期）：顶栏按钮 → /api/connect kind='claude'
// → 复用 buildTerminal 建 xterm tab（ConPTY 跑真实 claude CLI，保真终端）。
// 设计文档：docs/CLAUDE_CODE_INTEGRATION.md
// ============================================================

async function connectClaude(opts = {}) {
  // opts: {cwd, resume, label} —— resume 场景由 Claude 面板调用
  try {
    const body = {kind: 'claude', cwd: opts.cwd || '', resume: opts.resume || ''};
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
    return j;
  } catch(e) {
    showBanner('claude 启动请求失败: ' + e, 5000, true);
    return {ok: false};
  }
}
