let senseState = { lines: [], filter: 'ALL' };
function connectAiSSE() {
  aiSse = new EventSource('/api/ai/stream');
  aiSse.onmessage = (e) => {
    try {
      const item = JSON.parse(e.data);
      if (item.kind) return; // 跳过 screen/screenctl 帧（不进感知流）
      senseState.lines.push(item);
      if (senseState.lines.length > 200) senseState.lines.shift();
      renderSense();
    } catch(err) {}
  };
  aiSse.onerror = () => {
    aiSse.close();
    setTimeout(connectAiSSE, 2000);
  };
}

// ---- MCP 状态标签：后端地址 + 已注册工具 + 最近调用 ----
async function refreshMcpInfo() {
  try {
    const r = await fetch('/api/ai/mcp_info');
    const j = await r.json();
    if (!j.ok) return;
    // 状态点：有 backend_url 即后端在跑（MCP server 能否连上由最近调用推断）
    const dot = $('mcpStatusDot'), txt = $('mcpStatusText');
    if (j.backend_url) { dot.className = 'dot on'; txt.textContent = 'MCP 后端运行中'; }
    else { dot.className = 'dot'; txt.textContent = 'MCP 后端未运行'; }
    $('mcpBackendUrl').textContent = j.backend_url || '—（endpoint.json 未找到）';
    // 脏检查：工具列表内容没变就跳过 innerHTML 重建（5s 一次全量重建会叠加重排/ GC，输入时感知卡顿）
    const tools = j.tools || [];
    // 子 sheet 计数徽章（MCP 档内「工具」sheet）：工具数
    const mc = document.querySelector('.claude-sheet-tab[data-sheet="mcp-tools"] .count');
    if (mc && mc.textContent !== String(tools.length)) mc.textContent = tools.length;
    const toolsKey = tools.map(t => t.name).join(',');
    if (toolsKey !== _mcpToolsKey) {
      _mcpToolsKey = toolsKey;
      $('mcpTools').innerHTML = tools.length ? tools.map(t =>
        `<div class="mcp-tool"><span class="tname">${esc(t.name)}</span><span class="tdesc">${esc(t.desc)}</span></div>`).join('') : '<div class="mcp-empty">—</div>';
    }
    // 最近调用
    const calls = j.recent_calls || [];
    const callsEl = $('mcpCalls');
    // 子 sheet 计数徽章（MCP 档内「最近调用」sheet）：调用数
    const cc = document.querySelector('.claude-sheet-tab[data-sheet="mcp-calls"] .count');
    if (cc && cc.textContent !== String(calls.length)) cc.textContent = calls.length;
    // key 用最后一条的 ts+tool+args+总数：秒精度 ts 同秒两次调用 + 封顶 20 条后 len 不变都会撞 key
    const last = calls[calls.length - 1];
    const callsKey = last ? `${last.ts}|${last.tool}|${last.args}|${calls.length}` : '0';
    if (callsKey === _mcpCallsKey) return;  // 无新调用，跳过重建
    _mcpCallsKey = callsKey;
    if (!calls.length) { callsEl.innerHTML = '<div class="mcp-empty">暂无调用记录（Claude Code 调用 MCP 工具后会显示）</div>'; return; }
    callsEl.innerHTML = calls.slice(-20).reverse().map(c => {
      const d = new Date(c.ts * 1000);
      const ts = d.toTimeString().slice(0, 8);
      return `<div class="mcp-call ${c.ok ? 'ok' : 'fail'}"><span class="ctime">${ts}</span><span class="ctool">${esc(c.tool)}</span> <span class="cargs">${esc(c.args || '')}</span></div>`;
    }).join('');
  } catch(e) {}
}
let _mcpToolsKey = '', _mcpCallsKey = '';
function kwClassOf(text) {
  const t = text.toLowerCase();
  if (/\b(error|fail|panic|fatal|denied|refused|abort|crash|oom|killed)\b/.test(t)) return 'kw-error';
  if (/\b(warn|warning|deprecated|timeout|retry|overflow)\b/.test(t)) return 'kw-warning';
  if (/\b(info|notice|starting|started|stopped|detected|ready)\b/.test(t)) return 'kw-info';
  return '';
}
function renderSense() {
  const list = $('senseList');
  const filter = senseState.filter;
  // 端口筛选 chip
  const ports = ['ALL', ...new Set(senseState.lines.map(l => l.port))];
  const filterEl = $('senseFilter');
  filterEl.innerHTML = ports.map(p =>
    `<span class="chip ${p === filter ? 'active' : ''}" data-port="${esc(p)}">${esc(p === 'ALL' ? '全部' : p)}</span>`
  ).join('');
  filterEl.querySelectorAll('.chip').forEach(c => c.onclick = () => { senseState.filter = c.dataset.port; renderSense(); });
  // 行
  let shown = senseState.lines;
  if (filter !== 'ALL') shown = shown.filter(l => l.port === filter);
  const recent = shown.slice(-50);
  list.innerHTML = recent.map(it => {
    const kc = kwClassOf(it.text || '');
    return `<div class="sense-line ${kc}" data-port="${esc(it.port)}"><span class="port-tag">[${esc(it.port)}]</span>${esc((it.text || '').slice(0, 200))}</div>`;
  }).join('');
  list.scrollTop = list.scrollHeight;
  // 点击行跳转到该串口标签
  list.querySelectorAll('.sense-line').forEach(el => el.onclick = () => {
    const pid = el.dataset.port;
    if (connections[pid]) switchTab(pid);
  });
}

// ---- 分析标签 ----
// 4 类关键字正则
