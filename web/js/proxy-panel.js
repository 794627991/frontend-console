// ============================================================
// Claude Proxy 面板（原 D:\AI\proxy 独立工具合入主窗口）
// - tab 骨架同 bit-calc（模式 A：单例 + connections 表 + tab/wrap DOM）
// - 后端 src/proxy.py：/api/proxy/status|start|stop|mode|compression|ccr|quota|credentials
// - 轮询：tab 激活时 1s（面板可见才轮询，切走停止——流畅守则）
// - 链路：Claude Code → 8787(headroom 压缩) → 37349(重试代理) → lanz 内网网关
// ============================================================

function _pxFnum(n) {
  // 数字缩写（后端 _fnum 同款）：12345 → 12.3k
  n = Number(n) || 0;
  if (n >= 1e8) return Math.round(n).toString();
  if (n >= 1e4) return (n / 1e4).toFixed(1) + 'W';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return Number.isInteger(n) ? n.toString() : n.toFixed(1);
}
function _pxTok(n) {
  // token 缩写：1234567 → 1.23M（后端 core.fmt_tok 同款）
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(2) + 'k';
  return String(n);
}

function buildProxyTab() {
  // 单例：已开就激活
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'proxy') { switchTab(pid); return; }
  }
  const portId = 'proxy:' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico"><img src="/ico/proxy.png" style="width:14px;height:14px;vertical-align:-2px;" alt=""></span><span class="label">Claude Proxy</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <span class="px-badge px-stopped" data-px-status-badge>STOPPED</span>
        <button class="lv-btn" data-px-toggle>▶ 启动代理</button>
        <span class="px-url" data-px-url title="当前 ANTHROPIC_BASE_URL">-</span>
        <span style="flex:1"></span>
        <button class="lv-btn" data-px-mode="proxy" title="base_url 切到代理入口（8787/37349，重启 Claude Code 后生效）">切换为代理模式</button>
        <button class="lv-btn" data-px-mode="direct" title="base_url 切回内网网关直连">切换为直连模式</button>
      </div>
      <div class="px-body">
        <div class="px-msg" data-px-msg></div>

        <!-- 统计卡行：请求/成功率/重试/失败 + tokens + 免费/收费 -->
        <div class="px-stats" data-px-stats></div>

        <!-- 最近请求历史表（后端 snapshot req_history，增量插行） -->
        <div class="px-sec">
          <div class="px-sec-title">最近请求</div>
          <div class="px-hist" data-px-hist><div class="px-hint">代理启动后这里显示每个请求的模型/tokens/耗时（429 重试过的标红）</div></div>
        </div>

        <!-- 压缩模式 + CCR + 压缩统计条 -->
        <div class="px-sec">
          <div class="px-sec-title">headroom 压缩</div>
          <div class="px-hr-stats" data-px-hr-stats style="font-family:var(--font-mono);font-size:12px;color:var(--muted);margin-bottom:8px;">headroom: 未运行（无压缩，仅重试代理）</div>
          <div class="px-hr-row" data-px-hr-row>
            <label><input type="radio" name="px-hr-${portId}" value="full"> 完整压缩（ML + 结构化，省流量最多，吃 ~570MB 内存）</label>
            <label><input type="radio" name="px-hr-${portId}" value="light"> 轻量压缩（仅结构化，省 ~400MB 内存）</label>
            <label><input type="radio" name="px-hr-${portId}" value="off"> 关闭压缩（headroom 不启动，直接走重试代理）</label>
            <label class="px-ccr" title="CCR 流压缩。激进——/compact 可能卡死，不确定就别勾"><input type="checkbox" data-px-ccr> CCR 流压缩（激进·/compact 可能卡死）</label>
          </div>
          <div class="px-hint">切换立即生效：停旧 headroom → 按新模式拉起（冷启动 10-30s）→ 就绪自动切 base_url。失败自动回退关闭压缩。主模型 Lanz-Auto 带签名 thinking 不可压缩，压缩收益主要来自子代理与工具输出。</div>
        </div>

        <!-- Lanz 额度区：登录 + 概览 + 三模型明细 + 模型用量排名（老 GUI 同款布局）-->
        <div class="px-sec">
          <div class="px-sec-title">Lanz 额度</div>
          <div class="px-quota-login" data-px-quota-login>
            <input data-px-q-user placeholder="内网 SSO 用户名" spellcheck="false" style="width:150px;">
            <span class="px-eye-wrap">
              <input data-px-q-pwd type="password" placeholder="密码（存本地 lanz_credentials.json）" spellcheck="false" style="width:220px;">
              <button class="px-eye" data-px-q-eye title="显示/隐藏密码" tabindex="-1" aria-label="显示或隐藏密码">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
              </button>
            </span>
            <button class="lv-btn" data-px-q-save>登录</button>
            <button class="lv-btn" data-px-q-refresh title="立即刷新额度（沿用当前登录）">↻ 刷新</button>
            <button class="lv-btn" data-px-q-relogin title="登录失效（多天不用后获取不到数据）时的自救：丢弃旧会话强制重新登录。只刷新登录状态，代理链路不受影响">强制重登</button>
            <button class="lv-btn" data-px-q-logout title="删除本地凭据">断开</button>
            <label class="px-q-auto" title="每 10 分钟自动刷新额度"><input type="checkbox" data-px-q-auto checked> 自动刷新(10min)</label>
          </div>
          <div class="px-q-statrow">
            <span data-px-q-status style="font-size:12px;"></span>
            <span class="px-q-last" data-px-q-last>上次刷新 -</span>
          </div>
          <div data-px-quota-view></div>
          <div data-px-quota-rank></div>
        </div>

        <div class="px-hint">链路：Claude Code → headroom(8787，压缩) → 重试代理(37349，429/5xx 自动重试) → lanz 内网网关。退出工具自动停代理并回滚 base_url；异常退出下次启动自愈。</div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const conn = {
    portId,
    meta: { kind: 'proxy', label: 'Claude Proxy' },
    tab, wrap,
    pollTimer: null,
    tickTimer: null,   // 「上次刷新 Ns 前」倒计时 1s 纯字符串更新（老 GUI 同款）
    quotaTs: 0,        // 最近一次 quota_ts（毫秒）
    seenHist: 0,     // 历史表增量游标（后端 req_history_total）
  };
  connections[portId] = conn;

  const $p = (sel) => wrap.querySelector(sel);
  const badgeEl = $p('[data-px-status-badge]');
  const toggleBtn = $p('[data-px-toggle]');
  const urlEl = $p('[data-px-url]');
  const msgEl = $p('[data-px-msg]');
  const statsEl = $p('[data-px-stats]');
  const histEl = $p('[data-px-hist]');
  const quotaViewEl = $p('[data-px-quota-view]');
  const quotaRankEl = $p('[data-px-quota-rank]');
  const qStatusEl = $p('[data-px-q-status]');
  const qLastEl = $p('[data-px-q-last]');
  const qUserEl = $p('[data-px-q-user]');
  const qPwdEl = $p('[data-px-q-pwd]');
  const qEyeBtn = $p('[data-px-q-eye]');
  const qSaveBtn = $p('[data-px-q-save]');
  const qRefreshBtn = $p('[data-px-q-refresh]');
  const qReloginBtn = $p('[data-px-q-relogin]');
  const qLogoutBtn = $p('[data-px-q-logout]');
  const qAutoEl = $p('[data-px-q-auto]');
  const hrStatsEl = $p('[data-px-hr-stats]');

  const ST_CLS = {
    HEALTHY: 'px-healthy', RETRY: 'px-retry', FAILED: 'px-failed', STOPPED: 'px-stopped',
  };

  function _msg(text, bad) {
    msgEl.textContent = text || '';
    msgEl.style.color = bad ? 'var(--danger,#ff5468)' : 'var(--muted)';
  }

  function _renderStats(snap) {
    if (!snap) { statsEl.innerHTML = '<div class="px-hint">代理未运行，无统计数据</div>'; return; }
    const total = snap.total_requests || 0;
    const succ = snap.total_success || 0;
    const rate = total ? (succ * 100 / total).toFixed(1) : '100.0';
    const fails = (snap.total_giveups || 0) + (snap.total_client_gone || 0);
    const up = snap.uptime_seconds || 0;
    const upTxt = up >= 3600 ? `${(up/3600).toFixed(1)}h` : up >= 60 ? `${(up/60).toFixed(0)}m` : `${Math.floor(up)}s`;
    const cards = [
      ['总请求', _pxFnum(total)],
      ['成功率', rate + '%'],
      ['429/5xx', _pxFnum(snap.total_overloads)],
      ['重试', _pxFnum(snap.total_retries)],
      ['失败', _pxFnum(fails)],
      ['输入 tokens', _pxTok(snap.total_input_tokens)],
      ['输出 tokens', _pxTok(snap.total_output_tokens)],
      ['免费/收费', _pxFnum(snap.free_requests) + ' / ' + _pxFnum(snap.fee_requests)],
      ['运行', upTxt],
    ];
    statsEl.innerHTML = cards.map(([k, v]) =>
      `<div class="px-card"><div class="px-card-k">${k}</div><div class="px-card-v">${v}</div></div>`).join('');
  }

  function _renderHist(snap) {
    if (!snap) { histEl.innerHTML = '<div class="px-hint">代理未运行</div>'; conn.seenHist = 0; return; }
    const hist = snap.req_history || [];
    const total = snap.req_history_total || 0;
    const hint = histEl.querySelector('.px-hint');
    if (hint) hint.remove();
    // 增量：只插新行到顶部（1s 轮询全量 snapshot，用游标判新）
    if (total > conn.seenHist && hist.length) {
      const take = Math.min(total - conn.seenHist, hist.length);
      const rows = hist.slice(-take);
      const frag = document.createDocumentFragment();
      for (const [ts, model, inTok, outTok, brief, elapsed] of rows) {
        const t = new Date(ts * 1000).toLocaleTimeString('zh-CN', {hour12: false});
        const isOverload = elapsed > 30 || (inTok === 0 && outTok === 0);
        const div = document.createElement('div');
        div.className = 'px-hrow' + (isOverload ? ' px-hrow-bad' : '');
        div.title = brief || '';
        div.innerHTML = `<span class="px-h-t">${t}</span><span class="px-h-m">${esc(String(model || '?').slice(0, 24))}</span>` +
          `<span class="px-h-i">in ${_pxTok(inTok)}</span><span class="px-h-o">out ${_pxTok(outTok)}</span>` +
          `<span class="px-h-e">${elapsed.toFixed(1)}s</span>`;
        frag.appendChild(div);
      }
      histEl.insertBefore(frag, histEl.firstChild);
      while (histEl.children.length > 200) histEl.removeChild(histEl.lastChild);
      conn.seenHist = total;
    } else if (total < conn.seenHist) {
      // 代理重启过：清表重画
      conn.seenHist = 0;
      histEl.innerHTML = '';
    }
    if (!histEl.children.length) histEl.innerHTML = '<div class="px-hint">暂无请求</div>';
  }

  function _setQStatus(text, cls) {
    // 状态点统一风格：绿=在线 黄=进行中 红=失败 灰=无（老 GUI 同款语义）
    qStatusEl.innerHTML = text ? `<span class="px-badge ${cls}">${text}</span>` : '';
  }

  function _setQButtons(state) {
    // 按钮启停态（老 GUI config(state=) 平移）：
    // 登录成功/在线 → 启用刷新/断开；登录中禁刷新（防重复提交）；
    // 登录失败/查询失败禁刷新（GUI 同款：对着失败态反复点刷新无意义）。
    const online = state === 'online';
    const busy = state === 'logging';
    qRefreshBtn.disabled = busy || state === 'error' || state === 'fetch_err';
    qReloginBtn.disabled = !online && state !== 'error' && state !== 'fetch_err' && state !== 'logging';
    qLogoutBtn.disabled = busy;
  }

  function _qLastText() {
    // 「上次刷新 HH:MM:SS (Ns 前)」——老 GUI _refresh_quota_age 平移。
    // quota_ts 是秒级时间戳；无数据显示「-」。
    if (!conn.quotaTs) return '上次刷新 -';
    const ago = Math.max(0, Math.round(Date.now() / 1000 - conn.quotaTs));
    const t = new Date(conn.quotaTs * 1000).toLocaleTimeString('zh-CN', { hour12: false });
    return `上次刷新 ${t} (${ago}s 前)`;
  }

  function _renderQuota(j) {
    // 登录态优先用后端独立槽 quota_login（data 事件不再覆盖登录态——
    // 老版单槽 bug：登录成功后状态永远停在「登录中」）
    const lg = j.quota_login;
    const state = lg ? lg.state : null;
    if (state === 'logging') _setQStatus('● 登录中…', 'px-retry');
    else if (state === 'online') _setQStatus('● 在线 ' + esc(lg.user || ''), 'px-healthy');
    else if (state === 'error') _setQStatus('⚠ 登录失败', 'px-failed');
    else if (state === 'fetch_err') _setQStatus('⚠ 查询失败', 'px-failed');
    else if (!j.has_credentials) _setQStatus('● 未登录', 'px-stopped');
    _setQButtons(state || (j.has_credentials ? '' : undefined));
    if (state === 'error' || state === 'fetch_err')
      _msg((state === 'error' ? '登录失败: ' : '查询失败: ') + (lg.msg || ''), true);
    else if (state === 'online' && !msgEl.dataset.keep) _msg('');

    // 倒计时基准：data 到了刷新 quotaTs（status 轮询里 quota_ts 不变不动）
    if (j.quota_ts) conn.quotaTs = j.quota_ts;
    qLastEl.textContent = _qLastText();
    // 自动刷新 checkbox 同步（后端是真相源；用户点击瞬间先本地翻转防抖动）
    if (document.activeElement !== qAutoEl) qAutoEl.checked = j.quota_auto !== false;

    const ov = j.quota_overview;
    // 凭据已存：预填用户名（密码不回传，明文存本地已是既定约定）
    if (j.quota_username && !qUserEl.value) qUserEl.value = j.quota_username;
    if (!ov) { quotaViewEl.innerHTML = '<div class="px-hint">登录后显示额度（10 分钟自动刷新）</div>'; return; }
    const tile = (u, l) => {
      u = u || 0; l = l || 0;
      const hot = l && u / l >= 0.85;
      return `<span class="px-q-tile ${hot ? 'px-q-hot' : ''}">${_pxFnum(u)} / ${_pxFnum(l)}</span>`;
    };
    let html = `<div class="px-q-row"><span class="px-q-k">今日外部</span>${tile(ov.externalDailyUsed, ov.externalDailyLimit)}<span class="px-q-k">今日内部</span>${tile(ov.internalDailyUsed, ov.internalDailyLimit)}<span class="px-q-k">请求</span><span class="px-q-tile">${_pxFnum(ov.dailyRequestCount)}</span></div>`;
    if (ov.hasBudget) {
      const tot = ov.totalCredits || 0;
      const r = ov.usageRate || 0;
      html += `<div class="px-q-row"><span class="px-q-k">剩余积分</span><span class="px-q-tile">${Math.round(ov.remainCredit || 0)}</span><span class="px-q-k">总消耗</span><span class="px-q-tile">${Math.round(tot)}${r ? ` (${Math.round(r*100)}%)` : ''}</span></div>`;
    }
    const models = j.quota_models || [];
    if (models.length) {
      html += '<div class="px-q-models">' + models.map(m => {
        const hot = m.limit && m.used / m.limit >= 0.85;
        return `<div class="px-q-model ${hot ? 'px-q-hot' : ''}"><span class="px-q-mk">${m.name}</span>` +
          `<span>已用 ${_pxFnum(m.used)}</span><span>还剩 ${_pxFnum(m.remain)}</span><span>${m.pct}%</span></div>`;
      }).join('') + '</div>';
    }
    quotaViewEl.innerHTML = html;
    // 模型用量排名表（老 GUI q_model_tree 平移：模型/tokens/费用/积分/请求数）
    const rank = j.quota_rank || [];
    if (rank.length) {
      let rhtml = '<div class="px-rank-title">模型用量排名' +
        (j.quota_ts ? `<span class="px-rank-ago">上次刷新 ${new Date(j.quota_ts * 1000).toLocaleTimeString('zh-CN', {hour12: false})}</span>` : '') +
        '</div><div class="px-rank">' +
        '<div class="px-rank-h"><span>模型</span><span>tokens</span><span>费用</span><span>积分</span><span>请求数</span></div>';
      rank.forEach(m => {
        rhtml += `<div class="px-rank-r"><span class="px-rank-m">${esc(String(m.finalModel || '?'))}</span>` +
          `<span>${_pxTok(m.tokens)}</span><span>${(m.cost || 0).toFixed(2)}</span>` +
          `<span>${(m.credits || 0).toFixed(2)}</span><span>${_pxFnum(m.requestCount)}</span></div>`;
      });
      quotaRankEl.innerHTML = rhtml + '</div>';
    } else {
      quotaRankEl.innerHTML = '';
    }
  }

  function _renderHrStats(j) {
    // headroom 压缩统计条（老 GUI hr_label 平移：在线 :8787 │ 已处理 N │ 压缩节省 X (Y%)）
    if (!j.hr_running) {
      hrStatsEl.textContent = 'headroom: 未运行（无压缩，仅重试代理）';
      hrStatsEl.style.color = 'var(--muted)';
      return;
    }
    const st = j.hr_stats;
    if (!st) {
      hrStatsEl.textContent = 'headroom: 在线 :8787（stats 拉取中/失败）';
      hrStatsEl.style.color = 'var(--accent)';
      return;
    }
    const agents = (st.agent_usage || {}).agents || [];
    const ag = agents[0] || {};
    const saved = ag.tokens_saved || ((st.cost || {}).total_tokens_saved) || 0;
    const before = ag.before_tokens || 0;
    const pct = before ? (saved * 100 / before).toFixed(1) + '%' : '-';
    const modeTxt = j.hr_mode && j.hr_mode !== 'full' ? ` │ 模式 ${j.hr_mode}` : '';
    const ccrTxt = j.ccr ? ' │ CCR 开' : '';
    hrStatsEl.textContent = `headroom :8787${modeTxt}${ccrTxt}  │ 已处理 ${_pxFnum(ag.requests || 0)} 请求 │ 压缩节省 ${_pxTok(saved)} token (${pct})`;
    hrStatsEl.style.color = saved ? 'var(--accent)' : 'var(--muted)';
  }

  function _setHrUI(j) {
    // 原版顺序（用户实锤）：headroom 需要先启动重试代理才可用——
    // 代理没跑时完整/轻量压缩与 CCR 置灰（后端 apply_hr_mode 同口径拒绝），
    // 「关闭压缩」保持可点（启动前也能把记忆模式改回 off）
    const en = !!j.running;
    wrap.querySelectorAll('[data-px-hr-row] input[type=radio]').forEach(r => {
      r.checked = (r.value === (j.hr_mode || 'off'));
      r.disabled = (r.value !== 'off') && !en;
      r.closest('label').classList.toggle('px-dis', r.disabled);
    });
    const ccr = $p('[data-px-ccr]');
    ccr.checked = !!j.ccr;
    ccr.disabled = !en;
    ccr.closest('label').classList.toggle('px-dis', !en);
  }

  async function _poll() {
    try {
      const r = await fetch('/api/proxy/status');
      const j = await r.json();
      if (!j.ok) return;
      badgeEl.textContent = j.status;
      badgeEl.className = 'px-badge ' + (ST_CLS[j.status] || 'px-stopped');
      urlEl.textContent = 'base_url: ' + (j.base_url || '(未设置)');
      toggleBtn.textContent = j.running ? '■ 停止代理' : '▶ 启动代理';
      if (j.already_running) _msg('检测到已有 Claude 代理实例在 37349 端口（原独立工具在跑）——面板仅展示，复用不杀', false);
      else if (j.port_busy) _msg('端口 37349 被其他程序占用，无法启动', true);
      else if (!msgEl.dataset.keep) _msg('');
      _renderStats(j.snapshot);
      _renderHist(j.snapshot);
      _renderQuota(j);
      _renderHrStats(j);
      _setHrUI(j);
      if (!j.headroom_exe && (j.hr_mode === 'full' || j.hr_mode === 'light')) {
        msgEl.dataset.keep = '1';
        _msg('未找到 headroom.exe（pip install headroom-ai[all]），压缩不可用；重试代理不受影响', true);
      }
    } catch(_) {}
  }

  // tab 激活/切走控制轮询（流畅守则：看不见不轮询）。
  // switchTab 靠 wrap.style.display 切换，无回调可挂——tick 开头检测：
  // 隐藏即停 interval（下次 switchTab 回来时 startPoll 重建）。
  // 倒计时 1s tick 只更新「上次刷新 Ns 前」字符串（零网络），同随可见性启停。
  function _startPoll() {
    if (!conn.pollTimer) { conn.pollTimer = setInterval(_tickPoll, 1000); _poll(); }
    if (!conn.tickTimer) conn.tickTimer = setInterval(() => { qLastEl.textContent = _qLastText(); }, 1000);
  }
  function _stopPoll() {
    if (conn.pollTimer) { clearInterval(conn.pollTimer); conn.pollTimer = null; }
    if (conn.tickTimer) { clearInterval(conn.tickTimer); conn.tickTimer = null; }
  }
  async function _tickPoll() {
    if (wrap.style.display === 'none') { _stopPoll(); return; }
    await _poll();
  }

  toggleBtn.onclick = async () => {
    toggleBtn.disabled = true;
    try {
      const running = badgeEl.textContent !== 'STOPPED';
      const r = await fetch('/api/proxy/' + (running ? 'stop' : 'start'), {method: 'POST'});
      const j = await r.json();
      _msg(j.msg || (j.ok ? '完成' : '操作失败'), !j.ok);
      if (running) conn.seenHist = 0;
      _poll();
    } catch(e) { _msg('请求失败: ' + e, true); }
    toggleBtn.disabled = false;
  };

  wrap.querySelectorAll('[data-px-mode]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await fetch('/api/proxy/mode', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({mode: btn.dataset.pxMode})});
        const j = await r.json();
        if (!j.ok) { _msg('切换失败: ' + (j.changed || []).join('; '), true); return; }
        _msg(j.changed.length ? '已切换，重启 Claude Code / 开新会话后生效' : '已是目标模式，无需切换');
      } catch(e) { _msg('请求失败: ' + e, true); }
    };
  });

  wrap.querySelectorAll('[data-px-hr-row] input[type=radio]').forEach(r => {
    r.onchange = async () => {
      try {
        const resp = await fetch('/api/proxy/compression', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({mode: r.value})});
        const j = await resp.json();
        _msg(j.ok ? '压缩模式切换中（headroom 冷启动 10-30s）' : (j.msg || '切换失败'), !j.ok);
      } catch(e) { _msg('请求失败: ' + e, true); }
    };
  });
  $p('[data-px-ccr]').onchange = async (e) => {
    try {
      await fetch('/api/proxy/ccr', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({on: e.target.checked})});
      _msg(e.target.checked ? 'CCR 已开启（激进模式，/compact 可能卡死）' : 'CCR 已关闭');
    } catch(err) { _msg('请求失败: ' + err, true); }
  };

  // 密码明文/密文眼睛切换（SSH 客户端同款）：点击切换 input type，
  // 图标状态用 CSS class 表达（睁眼=password 可切显示，闭眼=明文中）
  qEyeBtn.onclick = () => {
    const show = qPwdEl.type === 'password';
    qPwdEl.type = show ? 'text' : 'password';
    qEyeBtn.classList.toggle('px-eye-on', show);
    qEyeBtn.title = show ? '隐藏密码' : '显示密码';
  };

  qSaveBtn.onclick = async () => {
    const u = qUserEl.value.trim();
    const p = qPwdEl.value;
    if (!u || !p) { _setQStatus('⚠ 用户名/密码不能为空', 'px-failed'); return; }
    _setQButtons('logging');
    try {
      const r = await fetch('/api/proxy/credentials', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: u, password: p})});
      const j = await r.json();
      _setQStatus(j.ok ? '● 登录中…' : '⚠ 保存失败', j.ok ? 'px-retry' : 'px-failed');
      _msg(j.ok ? '凭据已保存，正在登录…' : (j.msg || '保存失败'), !j.ok);
    } catch(e) { _msg('请求失败: ' + e, true); }
  };
  qRefreshBtn.onclick = async () => {
    qRefreshBtn.disabled = true;
    try {
      const r = await fetch('/api/proxy/quota', {method: 'POST'});
      const j = await r.json();
      if (!j.ok) { _setQStatus('⚠ ' + (j.msg || '刷新失败'), 'px-failed'); qRefreshBtn.disabled = false; }
      else { _setQStatus('● 刷新中…', 'px-retry'); _msg(''); }
    } catch(e) { _msg('请求失败: ' + e, true); qRefreshBtn.disabled = false; }
  };
  qReloginBtn.onclick = async () => {
    // 强制重登：换新 client 丢旧 session 全新登录（多天不用后登录失效的自救）。
    // 只动额度查询登录态，重试代理/headroom 链路零触碰。
    if (!(await _ddConfirm('强制重登', '丢弃当前登录会话，用保存的凭据重新登录拉取额度？\n（代理转发不受任何影响，只刷新额度登录状态）'))) return;
    try {
      const r = await fetch('/api/proxy/quota', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({force: true})});
      const j = await r.json();
      if (!j.ok) _setQStatus('⚠ ' + (j.msg || '触发失败'), 'px-failed');
      else { _setQStatus('● 重登中…', 'px-retry'); _msg('已触发强制重登，稍候看登录状态'); }
    } catch(e) { _msg('请求失败: ' + e, true); }
  };
  qLogoutBtn.onclick = async () => {
    try {
      await fetch('/api/proxy/credentials', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'clear'})});
      conn.quotaTs = 0;
      qPwdEl.value = '';
      quotaViewEl.innerHTML = '<div class="px-hint">已断开。登录后显示额度</div>';
      quotaRankEl.innerHTML = '';
      qLastEl.textContent = '上次刷新 -';
      _setQStatus('● 未登录', 'px-stopped');
      _setQButtons(undefined);
      _msg('已断开登录，本地凭据已删除');
    } catch(e) { _msg('请求失败: ' + e, true); }
  };
  qAutoEl.onchange = async (e) => {
    // 自动刷新开关（老 GUI checkbox 平移），后端是真相源
    try {
      await fetch('/api/proxy/quota', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({auto: e.target.checked})});
      _msg(e.target.checked ? '自动刷新已开启（每 10 分钟）' : '自动刷新已关闭（手动刷新仍可用）');
    } catch(err) {
      e.target.checked = !e.target.checked;   // 回滚
      _msg('请求失败: ' + err, true);
    }
  };

  // 初始一次渲染 + 1s 轮询（_tickPoll 内检测 tab 可见性，切走自动停；
  // 切回时 switchTab 调 conn.onResumePoll 恢复）
  conn.onResumePoll = _startPoll;
  _startPoll();

  switchTab(portId);
  refreshSidebar();
  return conn;
}
