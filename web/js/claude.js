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
    const label = opts.label || (j.resume ? `🤖 恢复 ${j.resume.slice(0,8)}` : '🤖 Claude');
    const conn = buildTerminal(portId, {kind:'claude', label, cwd: j.cwd, baud: ''});
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
