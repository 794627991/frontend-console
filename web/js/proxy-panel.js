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
        <span class="px-url" data-px-url title="当前 ANTHROPIC_BASE_URL">-</span>
        <span style="flex:1"></span>
        <button class="lv-btn" data-px-toggle>▶ 启动代理</button>
        <button class="lv-btn" data-px-mode="proxy" title="base_url 切到代理入口（8787/37349，重启 Claude Code 后生效）">切换为代理模式</button>
        <button class="lv-btn" data-px-mode="direct" title="base_url 切回内网网关直连">切换为直连模式</button>
      </div>
      <div class="px-tabs">
        <button class="px-tab px-tab-act" data-px-tab="main">概览</button>
        <button class="px-tab" data-px-tab="usage">用量统计</button>
      </div>
      <div class="px-body" data-px-page="main">
        <div class="px-msg" data-px-msg></div>

        <!-- 统计卡行：请求/成功率/重试/失败 + tokens + 免费/收费 -->
        <div class="px-stats" data-px-stats></div>

        <!-- 最近请求历史表（后端 snapshot req_history，增量插行） -->
        <div class="px-sec">
          <div class="px-sec-title">最近请求</div>
          <div class="px-hist" data-px-hist><div class="px-hint">代理启动后这里显示每个请求的模型/tokens/耗时（429 重试过的标红）</div></div>
        </div>

        <!-- headroom 压缩：一个配置按钮 + 状态条（内联 radio 易误点——
             改原版弹窗式：点按钮才出模式选择，主界面只读不选） -->
        <div class="px-sec">
          <div class="px-sec-title">headroom 压缩</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
            <button class="lv-btn" data-px-hr-cfg style="min-width:170px;">压缩模式：—</button>
            <span class="px-hr-stats" data-px-hr-stats style="font-family:var(--font-mono);font-size:12px;color:var(--muted);"></span>
          </div>
          <div class="px-hint">点「压缩模式」选择策略并立即生效：停旧 headroom → 按新模式拉起（冷启动 10-30s）→ 就绪自动切 base_url。失败自动回退关闭压缩。主模型 Lanz-Auto 带签名 thinking 不可压缩，压缩收益主要来自子代理与工具输出。</div>
        </div>

        <!-- 重试策略：原独立工具「重试配置」弹窗的能力回归（合入时漏带）。
             一个配置按钮 + 只读说明，编辑进弹窗（与 headroom 同款防误点） -->
        <div class="px-sec">
          <div class="px-sec-title">重试策略</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
            <button class="lv-btn" data-px-retry-cfg style="min-width:170px;">重试配置：—</button>
          </div>
          <div class="px-hint">429/5xx/网络异常自动重试（阶梯退避 1s→封顶，带抖动）。点「重试配置」编辑上限次数/最大时长/退避开关/退避封顶，保存即热生效——正在运行的代理立即应用，无需重启。默认无限重试（0=无限）。</div>
        </div>

        <!-- Lanz 额度区：登录 + 概览 + 三模型明细 + 模型用量排名（老 GUI 同款布局）-->
        <div class="px-sec">
          <div class="px-sec-title">Lanz 额度</div>
          <div class="px-quota-login" data-px-quota-login>
            <input name="px_q_user" data-px-q-user placeholder="内网 SSO 用户名" spellcheck="false" style="width:150px;">
            <span class="px-eye-wrap">
              <input name="px_q_pwd" data-px-q-pwd type="password" placeholder="密码（存本地 lanz_credentials.json）" spellcheck="false" style="width:220px;">
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
            <label class="px-q-auto" title="每 10 分钟自动刷新额度"><input type="checkbox" name="px_q_auto" data-px-q-auto checked> 自动刷新(10min)</label>
          </div>
          <div class="px-q-statrow">
            <span data-px-q-status style="font-size:12px;"></span>
            <span class="px-q-last" data-px-q-last>上次刷新 -</span>
          </div>
          <div data-px-quota-view></div>
          <div data-px-quota-rank></div>
        </div>

        <div class="px-hint" data-px-chain>链路：Claude Code → headroom(8787，压缩) → 重试代理(37349，429/5xx 自动重试) → 上游网关。退出工具自动停代理并回滚 base_url；异常退出下次启动自愈。</div>
        <div class="px-hint" data-px-direct>原 base_url（直连网关）：-</div>
      </div>

      <!-- 用量统计页：日×小时×模型聚合（180 天内），纯 CSS 堆叠柱状图 -->
      <div class="px-body" data-px-page="usage" style="display:none;">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <div class="px-tabs" style="margin:0;">
            <button class="px-tab px-tab-act" data-px-u-range="hour">当日按小时</button>
            <button class="px-tab" data-px-u-range="7d">近 7 日</button>
            <button class="px-tab" data-px-u-range="30d">近 30 日</button>
          </div>
          <span class="px-hint">按模型堆叠；保留最近 <span data-px-u-keep>180</span> 天</span>
        </div>
        <div class="px-stats" data-px-u-total></div>
        <div class="px-sec">
          <div class="px-sec-title" data-px-u-title>Token 用量（输入+输出）</div>
          <div class="px-usage-chart" data-px-u-chart></div>
          <div class="px-usage-x" data-px-u-x></div>
          <div class="px-legend" data-px-u-legend></div>
        </div>
        <div class="px-sec">
          <div class="px-sec-title">模型明细</div>
          <div data-px-u-table></div>
        </div>
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
  const hrCfgBtn = $p('[data-px-hr-cfg]');
  const retryCfgBtn = $p('[data-px-retry-cfg]');
  // ---- 面板内部 tab（概览/用量统计）：仅挂载点——用量逻辑全在
  // proxy-usage.js（独立积木），宿主文件不承载任何用量实现 ----
  const uPage = $p('[data-px-page="usage"]');
  const mainPage = $p('[data-px-page="main"]');
  wrap.querySelectorAll('[data-px-tab]').forEach(btn => {
    btn.onclick = () => {
      const page = btn.dataset.pxTab;
      wrap.querySelectorAll('[data-px-tab]').forEach(b => b.classList.toggle('px-tab-act', b === btn));
      mainPage.style.display = page === 'main' ? '' : 'none';
      uPage.style.display = page === 'usage' ? '' : 'none';
      if (page === 'usage' && window.pxUsageLoad) pxUsageLoad(wrap);
    };
  });
  if (window.pxUsageInit) pxUsageInit(wrap);

  const ST_CLS = {
    HEALTHY: 'px-healthy', RETRY: 'px-retry', FAILED: 'px-failed', STOPPED: 'px-stopped',
  };

  function _msg(text, bad) {
    msgEl.textContent = text || '';
    msgEl.style.color = bad ? 'var(--danger,#ff5468)' : 'var(--muted)';
    msgEl.style.display = text ? '' : 'none';   // 空态不占位（min-height+gap 会空出一条）
  }

  function _renderStats(snap) {
    // 未运行占位：px-stats 是 108px 小格 grid，hint 直接塞会挤进单格
    // 导致「无统计数据」换行+右侧全空（用户实锤）——跨满整行
    if (!snap) { statsEl.innerHTML = '<div class="px-hint" style="grid-column:1/-1;padding:10px 0;">代理未运行，无统计数据</div>'; return; }
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
    // 增量：只插新行到顶部（1s 轮询全量 snapshot，用游标判新）。
    // v2.56：统一「最新在最上」倒序语义——旧实现全量首刷按旧→新铺（顺序），
    // 增量块却插顶且块内旧→新（块内顺序与整表倒序打架）=打开 tab 后时间错乱。
    // 现在块内一律新→旧；表空首刷直接铺（等价倒序全量），与增量方向一致。
    if (total > conn.seenHist && hist.length) {
      const take = Math.min(total - conn.seenHist, hist.length);
      const rows = hist.slice(-take);
      const rebuild = histEl.children.length === 0;
      const frag = document.createDocumentFragment();
      for (const [ts, model, inTok, outTok, brief, elapsed] of [...rows].reverse()) {
        const t = new Date(ts * 1000).toLocaleTimeString('zh-CN', {hour12: false});
        const isOverload = elapsed > 30 || (inTok === 0 && outTok === 0);
        const div = document.createElement('div');
        div.className = 'px-hrow' + (isOverload ? ' px-hrow-bad' : '');
        div.title = brief || '';
        div.innerHTML = `<span class="px-h-t">${t}</span><span class="px-h-m">${esc(String(model || '?').slice(0, 24))}</span>` +
          `<span class="px-h-b">${esc(String(brief || ''))}</span>` +
          `<span class="px-h-i">in ${_pxTok(inTok)}</span><span class="px-h-o">out ${_pxTok(outTok)}</span>` +
          `<span class="px-h-e">${elapsed.toFixed(1)}s</span>`;
        frag.appendChild(div);
      }
      if (rebuild) {
        histEl.innerHTML = '';
        histEl.appendChild(frag);
      } else {
        histEl.insertBefore(frag, histEl.firstChild);
      }
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
    // 主面板不再摆 radio（易误点——用户实锤）：只更新配置按钮文案，
    // 选择动作全部进弹窗（仿原工具 _hr_mode_dialog）
    conn.hrState = j;
    const lab = { full: '完整压缩', light: '轻量压缩', off: '关闭' }[j.hr_mode] || '—';
    hrCfgBtn.textContent = '压缩模式：' + lab + (j.ccr && j.hr_mode !== 'off' ? ' · CCR' : '');
    hrCfgBtn.title = j.running ? '选择压缩策略（应用立即生效）'
      : '重试代理未启动：full/light 需先启动代理才能应用（off 可直接记住）';
  }

  async function _poll() {
    try {
      const r = await fetch('/api/proxy/status');
      const j = await r.json();
      if (!j.ok) {
        // 后端降级返回（status_err）——面板冻结假 STOPPED 比报错更误导
        if (!conn._pollErrShown) { conn._pollErrShown = true; _msg('状态获取失败: ' + (j.status_err || '未知'), true); }
        return;
      }
      conn._pollErrShown = false;
      badgeEl.textContent = j.status;
      badgeEl.className = 'px-badge ' + (ST_CLS[j.status] || 'px-stopped');
      urlEl.textContent = 'base_url: ' + (j.base_url || '(未设置)');
      // 链路说明尾段动态显示真实上游（不再写死 lanz）
      const chain = wrap.querySelector('[data-px-chain]');
      if (chain && j.upstream) chain.textContent = chain.textContent.replace(/→ .*。退出/, '→ ' + j.upstream + '。退出');
      // 原 base_url：当前方案的真实直连网关（切方案后应跟随变化，验证 405 修复的肉眼依据）
      const direct = wrap.querySelector('[data-px-direct]');
      if (direct) direct.textContent = '原 base_url（直连网关）：' + (j.direct_url || '(未设置)');
      toggleBtn.textContent = j.running ? '■ 停止代理' : '▶ 启动代理';
      if (j.already_running) _msg('检测到已有 Claude 代理实例在 37349 端口（原独立工具在跑）——面板仅展示，复用不杀', false);
      else if (j.port_busy) _msg('端口 37349 被其他程序占用，无法启动', true);
      else if (!msgEl.dataset.keep) _msg('');
      _renderStats(j.snapshot);
      _renderHist(j.snapshot);
      _renderQuota(j);
      _renderHrStats(j);
      _setHrUI(j);
      _setRetryUI(j);
      if (!j.headroom_exe && (j.hr_mode === 'full' || j.hr_mode === 'light')) {
        msgEl.dataset.keep = '1';
        _msg('未找到 headroom.exe（pip install headroom-ai[all]），压缩不可用；重试代理不受影响', true);
      }
    } catch(e) {
      // 网络/解析失败同样不静默——连不上的原因要上屏
      if (!conn._pollErrShown) { conn._pollErrShown = true; _msg('状态轮询失败: ' + e, true); }
    }
  }

  // tab 激活/切走控制轮询（流畅守则：看不见不轮询）。
  // switchTab 靠 wrap.style.display 切换，无回调可挂——tick 开头检测：
  // 隐藏即停 interval（下次 switchTab 回来时 startPoll 重建）。
  // 倒计时 1s tick 只更新「上次刷新 Ns 前」字符串（零网络），同随可见性启停。
  function _startPoll() {
    if (!conn.pollTimer) { conn.pollTimer = setInterval(_tickPoll, 3000)   /* v3.5.288: 1s→3s——代理状态无需秒级刷新（卡死报告 §6.4） */; _poll(); }
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

  // headroom 配置入口：主面板只剩这一个按钮，选择进弹窗（旧内联 radio 易误点）
  hrCfgBtn.onclick = () => _hrCfgModal();
  // 重试配置入口（同款防误点设计）
  retryCfgBtn.onclick = () => _retryCfgModal();

  // ---- 重试策略配置弹窗（原独立工具 _retry_dialog 的能力回归）----
  // 四字段：上限次数/最大时长/退避开关/退避封顶。0=无限（次数/时长）。
  // 保存 POST /api/proxy/retry → 写 retry_config.json + 热更 RETRY_CFG，
  // 在跑的代理立即生效（backoff_wait/check_retry_cap 每次调用都读它）。
  function _retryCfgFmt(c) {
    if (!c) return '重试配置：—';
    const n = c.max_attempts > 0 ? c.max_attempts + '次' : '无限';
    const t = c.max_retry_seconds > 0 ? c.max_retry_seconds + 's' : '无限';
    const b = c.backoff_enabled === false ? '关' : '开';
    return `重试配置：上限 ${n} ｜ 时长 ${t} ｜ 退避 ${b} ｜ 封顶 ${c.max_backoff_seconds}s`;
  }
  function _setRetryUI(j) {
    retryCfgBtn.textContent = _retryCfgFmt(j.retry_cfg);
    retryCfgBtn.title = '编辑 429/5xx 重试策略（保存即热生效，无需重启代理）';
  }
  function _retryCfgModal() {
    let m = $('pxRetryModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'pxRetryModal';
      m.innerHTML = `
        <div class="box" style="max-width:480px;">
          <div class="head"><strong>重试策略配置</strong>
            <div class="head-actions"><button class="btn ghost icon-btn" data-rt-x>✕</button></div></div>
          <div style="padding:14px 18px 4px;display:flex;flex-direction:column;gap:10px;font-size:13px;">
            <label style="display:flex;align-items:center;gap:10px;">
              <span style="width:110px;flex-shrink:0;">重试上限次数</span>
              <input type="number" name="px_rt_attempts" min="0" step="1" data-rt-attempts style="width:90px;">
              <span class="px-hint">0 = 无限重试（默认）</span></label>
            <label style="display:flex;align-items:center;gap:10px;">
              <span style="width:110px;flex-shrink:0;">最大重试时长（秒）</span>
              <input type="number" name="px_rt_seconds" min="0" step="1" data-rt-seconds style="width:90px;">
              <span class="px-hint">0 = 不限时；超时即放弃并返回错误</span></label>
            <label style="display:flex;align-items:center;gap:10px;">
              <span style="width:110px;flex-shrink:0;">阶梯退避</span>
              <input type="checkbox" name="px_rt_backoff" data-rt-backoff>
              <span class="px-hint">关 = 不逐次加长等待（固定最短间隔）</span></label>
            <label style="display:flex;align-items:center;gap:10px;">
              <span style="width:110px;flex-shrink:0;">退避封顶（秒）</span>
              <input type="number" name="px_rt_cap" min="0.1" step="0.5" data-rt-cap style="width:90px;">
              <span class="px-hint">单次等待上限，实际带随机抖动</span></label>
            <div class="px-hint" style="margin-top:4px;">保存即写 retry_config.json 并热更正在运行的代理，无需重启。命中上限后该请求以最后一次错误返回给客户端。</div>
          </div>
          <div style="display:flex;gap:10px;justify-content:flex-end;padding:12px 18px 16px;">
            <button class="btn ghost" data-rt-cancel>取消</button>
            <button class="btn primary" data-rt-save>保存</button>
          </div>
        </div>`;
      document.body.appendChild(m);
    }
    // 当前值预填（status 轮询带的 retry_cfg；没有则 GET 一次）
    const c = (conn.hrState && conn.hrState.retry_cfg) || null;
    const fill = (cfg) => {
      if (!cfg) return;
      m.querySelector('[data-rt-attempts]').value = cfg.max_attempts;
      m.querySelector('[data-rt-seconds]').value = cfg.max_retry_seconds;
      m.querySelector('[data-rt-backoff]').checked = cfg.backoff_enabled !== false;
      m.querySelector('[data-rt-cap]').value = cfg.max_backoff_seconds;
    };
    if (c) fill(c);
    else fetch('/api/proxy/retry').then(r => r.json()).then(j => { if (j.ok) fill(j.cfg); }).catch(() => {});
    const close = () => m.classList.remove('show');
    m.querySelector('[data-rt-x]').onclick = close;
    m.querySelector('[data-rt-cancel]').onclick = close;
    m.querySelector('[data-rt-save]').onclick = async () => {
      const saveBtn = m.querySelector('[data-rt-save]');
      saveBtn.disabled = true;
      try {
        const r = await fetch('/api/proxy/retry', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            max_attempts: parseInt(m.querySelector('[data-rt-attempts]').value, 10) || 0,
            max_retry_seconds: parseFloat(m.querySelector('[data-rt-seconds]').value) || 0,
            backoff_enabled: m.querySelector('[data-rt-backoff]').checked,
            max_backoff_seconds: parseFloat(m.querySelector('[data-rt-cap]').value) || 10,
          })});
        const j = await r.json();
        if (!j.ok) { _msg(j.msg || '保存失败', true); saveBtn.disabled = false; return; }
        retryCfgBtn.textContent = _retryCfgFmt(j.cfg);
        if (conn.hrState) conn.hrState.retry_cfg = j.cfg;   // 轮询回来前先自洽
        _msg('重试策略已保存并热生效', false);
        close();
      } catch(e) { _msg('请求失败: ' + e, true); }
      saveBtn.disabled = false;
    };
    m.classList.add('show');
  }

  // ---- headroom 压缩配置弹窗（仿原工具 _hr_mode_dialog，模式卡+CCR+预览）----
  // off 永远可选（代理未跑时=只记模式下次启动生效，原工具同款降级）；
  // full/light 在 headroom 缺失时禁用。应用一次 POST {mode, ccr} 同改。
  const HR_CARDS = [
    ['full', '完整压缩', 'ML + 结构化 · ~570MB', '收益: 压缩率最高（文本 Kompress + 结构化全开）\n减益: 内存 ~570MB（ML 模型常驻），冷启动 ~15s'],
    ['light', '轻量压缩', '仅结构化 · ~150MB', '收益: 内存 ~150MB（省 ~400MB），冷启动快\n减益: 文本类压缩归零，工具/日志/表格压缩保留（实测子代理仍 ~20%+）'],
    ['off', '关闭压缩', '不启动 headroom', '收益: 零额外内存、零冷启动等待\n减益: 无任何压缩收益，流量原样过重试代理'],
  ];
  const HR_NOTE = '注: 主模型 Lanz-Auto 带签名 thinking 块不可压缩，任何模式下主会话压缩都接近 0%；'
    + '压缩收益主要来自子代理（Lanz-Medium 实测 27%）与工具输出。';

  function _hrCfgModal() {
    const j = conn.hrState || {};
    const hasHr = !!j.headroom_exe;
    let m = $('pxHrModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'pxHrModal';
      m.innerHTML = `
        <div class="box" style="max-width:600px;">
          <div class="head"><strong>headroom 压缩配置</strong>
            <div class="head-actions"><button class="btn ghost icon-btn" data-hr-x>✕</button></div></div>
          <div style="padding:14px 18px 4px;">
            <div data-hr-warn></div>
            <div style="display:flex;flex-direction:column;gap:6px;">
              ${HR_CARDS.map(([k, t, sub, d]) => `
                <label class="px-hr-card" data-hr-card="${k}">
                  <input type="radio" name="pxhrmode" value="${k}">
                  <span class="px-hr-card-t">${t}</span>
                  <span class="px-hr-card-sub">${sub}</span>
                  <span class="px-hr-card-d">${esc(d)}</span>
                </label>`).join('')}
            </div>
            <div class="px-hr-ccr">
              <label><input type="checkbox" name="px_hr_ccr" data-hr-ccr> CCR 流压缩</label>
              <span data-hr-ccr-hint></span>
            </div>
            <div class="px-hint" style="margin:10px 0 0;">${esc(HR_NOTE)}</div>
          </div>
          <div style="display:flex;gap:10px;justify-content:flex-end;padding:12px 18px 16px;">
            <button class="btn ghost" data-hr-cancel>取消</button>
            <button class="btn primary" data-hr-apply>应用</button>
          </div>
        </div>`;
      document.body.appendChild(m);
    }
    const cards = m.querySelectorAll('[data-hr-card]');
    const ccrEl = m.querySelector('[data-hr-ccr]');
    const hintEl = m.querySelector('[data-hr-ccr-hint]');
    // 初始态：预选当前模式/CCR；full/light 需已装 headroom 且代理在跑
    // （与后端 apply_hr_mode 拒绝口径一致）；off 永远可选
    const canFull = hasHr && !!j.running;
    cards.forEach(lab => {
      const rb = lab.querySelector('input');
      rb.checked = rb.value === (j.hr_mode || 'off');
      lab.classList.toggle('px-dis', !canFull && rb.value !== 'off');
      rb.disabled = !canFull && rb.value !== 'off';
    });
    m.querySelector('[data-hr-warn]').innerHTML = hasHr ? ''
      : '<div style="color:var(--neon-orange);font-size:12px;margin-bottom:8px;">⚠ 未检测到 headroom.exe（pip install headroom-ai[all]），压缩不可用；重启工具可再试</div>';
    ccrEl.checked = !!j.ccr;
    const syncCcr = () => {
      const mode = (m.querySelector('[data-hr-card] input:checked') || {}).value || 'off';
      const dis = mode === 'off' || !hasHr;
      ccrEl.disabled = dis;
      m.querySelector('.px-hr-ccr').classList.toggle('px-dis', dis);
      hintEl.textContent = dis ? (mode === 'off' ? '（headroom 不启动，无意义）' : '（未安装 headroom）')
        : (ccrEl.checked ? '激进压缩 · /compact 可能卡死' : '保守 · 稳定');
      hintEl.style.color = dis ? 'var(--muted)' : (ccrEl.checked ? 'var(--neon-orange)' : 'var(--muted)');
    };
    // 每次打开重绑（_ddConfirm 同款坑：闭包复用旧 resolve）
    cards.forEach(lab => { lab.querySelector('input').onchange = syncCcr; });
    ccrEl.onchange = syncCcr;
    syncCcr();
    const close = () => m.classList.remove('show');
    m.querySelector('[data-hr-x]').onclick = close;
    m.querySelector('[data-hr-cancel]').onclick = close;
    m.querySelector('[data-hr-apply]').onclick = async () => {
      const mode = (m.querySelector('[data-hr-card] input:checked') || {}).value;
      if (!mode) return;
      const applyBtn = m.querySelector('[data-hr-apply]');
      applyBtn.disabled = true;
      try {
        const r = await fetch('/api/proxy/compression', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({mode, ccr: ccrEl.checked})});
        const jj = await r.json();
        _msg(jj.ok ? (mode === 'off' ? '已关闭压缩'
             : (j.running ? '切换中（headroom 冷启动 10-30s，就绪自动切 8787）'
                          : '已记住，启动代理后生效（下次启动自动拉起）'))
             : (jj.msg || '切换失败'), !jj.ok);
        if (jj.ok) { close(); _poll(); }
      } catch(e) { _msg('请求失败: ' + e, true); }
      applyBtn.disabled = false;
    };
    m.classList.add('show');
  }

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
