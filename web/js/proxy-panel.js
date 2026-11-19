// ============================================================
// Claude Proxy 面板（原 D:\AI\proxy 独立工具合入主窗口）
// - tab 骨架同 bit-calc（模式 A：单例 + connections 表 + tab/wrap DOM）
// - 后端 src/proxy.py：/api/proxy/status|start|stop|mode|compression|ccr|retry
// - Lanzi 额度/登录已迁出：web/js/lanzi/panel.js + /api/lanzi/*（a672）
// - 轮询：tab 激活时 1s（面板可见才轮询，切走停止——流畅守则）
// - 链路：Claude Code → 18788(billion-context 压缩) → 37349(重试代理) → lanz 内网网关
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
      <div class="px-body" data-px-page="main">
        <div class="px-msg" data-px-msg></div>

        <!-- 统计卡行：请求/成功率/重试/失败 + tokens -->
        <div class="px-stats" data-px-stats></div>

        <!-- 最近请求历史表（后端 snapshot req_history，增量插行） -->
        <div class="px-sec">
          <div class="px-sec-title">最近请求</div>
          <div class="px-hist" data-px-hist><div class="px-hint">代理启动后这里显示每个请求的模型/tokens/耗时（429 重试过的标红）</div></div>
        </div>

        <!-- billion-context 压缩：一个配置按钮 + 状态条（内联 radio 易误点——
             改原版弹窗式：点按钮才出模式选择，主界面只读不选） -->
        <div class="px-sec">
          <div class="px-sec-title">billion-context 压缩</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
            <button class="lv-btn" data-px-hr-cfg style="min-width:170px;">压缩模式：—</button>
            <span class="px-hr-stats" data-px-hr-stats style="font-family:var(--font-mono);font-size:12px;color:var(--muted);"></span>
          </div>
          <div class="px-hint">点「压缩模式」选择策略并立即生效：停旧实例 → 拉起 billion-context → 就绪自动切 base_url（期间走重试代理不断会话）。失败自动回退关闭压缩。模型驱动分层压缩（可逆，decompress 可恢复原文）；签名 thinking 块逐字节透传不可压缩，收益主要来自子代理与工具输出。需 Node ≥22 + npm install -g billion-context。</div>
        </div>

        <!-- 重试策略：原独立工具「重试配置」弹窗的能力回归（合入时漏带）。
             一个配置按钮 + 只读说明，编辑进弹窗（与压缩配置同款防误点） -->
        <div class="px-sec">
          <div class="px-sec-title">重试策略</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
            <button class="lv-btn" data-px-retry-cfg style="min-width:170px;">重试配置：—</button>
          </div>
          <div class="px-hint">429/5xx/网络异常自动重试（阶梯退避 1s→封顶，带抖动）。点「重试配置」编辑上限次数/最大时长/退避开关/退避封顶，保存即热生效——正在运行的代理立即应用，无需重启。默认无限重试（0=无限）。</div>
        </div>


        <!-- 用量统计（a672：原独立子 tab，现与概览同页——转发数据是一体的） -->
        <div class="px-sec">
          <div class="px-sec-title">用量统计
            <span class="px-rank-ago">按模型堆叠 · 保留最近 <span data-px-u-keep>180</span> 天</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
            <div class="px-tabs" style="margin:0;">
              <button class="px-tab px-tab-act" data-px-u-range="hour">当日按小时</button>
              <button class="px-tab" data-px-u-range="7d">近 7 日</button>
              <button class="px-tab" data-px-u-range="30d">近 30 日</button>
            </div>
          </div>
          <div class="px-stats" data-px-u-total></div>
          <div class="px-sec" style="margin:10px 0 0;">
            <div class="px-sec-title" data-px-u-title>Token 用量（输入+输出）</div>
            <div class="px-usage-chart" data-px-u-chart></div>
            <div class="px-usage-x" data-px-u-x></div>
            <div class="px-legend" data-px-u-legend></div>
          </div>
          <div class="px-sec" style="margin:10px 0 0;">
            <div class="px-sec-title">模型明细</div>
            <div data-px-u-table></div>
          </div>
        </div>

        <div class="px-hint" data-px-chain>链路：Claude Code → billion-context(18788，/bili/ 前缀压缩代理) → 重试代理(37349，429/5xx 自动重试) → 上游网关。退出工具自动停代理并回滚 base_url；异常退出下次启动自愈。压缩引擎 github.com/ranxianglei/billion-context（MIT，按条款署名）。</div>
        <div class="px-hint" data-px-direct>原 base_url（直连网关）：-</div>
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
  const hrStatsEl = $p('[data-px-hr-stats]');
  const hrCfgBtn = $p('[data-px-hr-cfg]');
  const retryCfgBtn = $p('[data-px-retry-cfg]');
  // ---- 面板内部 tab（概览/用量统计）：仅挂载点——用量逻辑全在
  // proxy-usage.js（独立积木），宿主文件不承载任何用量实现 ----
  // a672：概览与用量统计合并为同一页，不再有子 tab 切换
  if (window.pxUsageInit) pxUsageInit(wrap);

  const ST_CLS = {
    HEALTHY: 'px-healthy', RETRY: 'px-retry', FAILED: 'px-failed', STOPPED: 'px-stopped',
  };

  // a452：操作反馈（点按钮后的结果）用 _msgKeep 写，带 6s 保鲜期——
  // 期间轮询的状态文案让位，避免用户看不到自己刚点的结果。
  function _msgKeep(text, bad) {
    msgEl.dataset.keep = '1';
    msgEl.dataset.keepUntil = String(Date.now() + 6000);
    _msg(text, bad);
  }
  function _msg(text, bad) {
    msgEl.textContent = text || '';
    msgEl.style.color = bad ? 'var(--danger,#ff5468)' : 'var(--muted)';
    msgEl.style.display = text ? '' : 'none';   // 空态不占位（min-height+gap 会空出一条）
  }
  // 当前是否处于「操作反馈保鲜期」。所有会每轮重写 msgEl 的状态文案都先问它。
  function _msgHeld() {
    const until = parseInt(msgEl.dataset.keepUntil || '0', 10) || 0;
    return msgEl.dataset.keep === '1' && Date.now() < until;
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

  // a407：billion-context 唯一安装入口（用户令：移出资源包/安装库，代理
  // 面板联网下载一键装）。引擎在=不显示；不在=入口+进度（1s 轮询驱动）
  function _renderBiliInstall(j) {
    let row = document.getElementById('px-bili-inst');
    if (!j || j.bili_ready) {
      if (row) row.remove();
      return;
    }
    const inst = j.bili_install || {};
    if (!row) {
      row = document.createElement('div');
      row.id = 'px-bili-inst';
      row.style.cssText = 'margin-top:6px;padding:8px 10px;border:1px dashed var(--border);border-radius:8px;font-size:12px;';
      const head = document.createElement('div');
      const btn = document.createElement('button');
      btn.className = 'btn primary';
      btn.style.cssText = 'padding:2px 10px;font-size:11px;margin-right:8px;';
      btn.textContent = '联网下载安装压缩引擎';
      btn.title = 'npm install -g billion-context（机器需 Node ≥22 + 可达外网；内网无外联时装不上属预期）';
      btn.onclick = () => {
        btn.disabled = true;
        fetch('/api/proxy/bili_install', { method: 'POST' })
          .then(r => r.json())
          .then(d2 => { if (!d2.ok) _msg('启动失败：' + (d2.msg || ''), true); })
          .catch(e => _msg('启动失败: ' + e, true));
      };
      head.appendChild(btn);
      const tip = document.createElement('span');
      tip.style.color = 'var(--muted)';
      tip.textContent = 'billion-context 未安装（压缩不可用；重试代理不受影响）';
      head.appendChild(tip);
      row.appendChild(head);
      const log = document.createElement('div');
      log.style.cssText = 'margin-top:4px;max-height:90px;overflow:auto;font-size:11px;font-family:var(--font-mono);white-space:pre-wrap;color:var(--muted);';
      log.id = 'px-bili-inst-log';
      row.appendChild(log);
      hrStatsEl.parentElement.appendChild(row);
    }
    const logEl = document.getElementById('px-bili-inst-log');
    const lines = (inst.log || []).slice();
    if (inst.running) lines.push('… 安装进行中（联网下载）');
    if (inst.err) lines.push('✗ ' + inst.err);
    if (logEl) {
      const txt = lines.join('\n');
      if (logEl.textContent !== txt) {
        logEl.textContent = txt;
        logEl.scrollTop = logEl.scrollHeight;
      }
    }
  }

  function _renderHrStats(j) {
    // bili 压缩统计条：/__bili/stats 的 sessions 维度聚合（a201 换代——
    // headroom 的 agent_usage 结构随其退役；字段缺省 .get 口径兜底）
    if (!j.bili_running) {
      hrStatsEl.textContent = 'bili: 未运行（无压缩，仅重试代理）';
      hrStatsEl.style.color = 'var(--muted)';
      return;
    }
    const st = j.bili_stats;
    if (!st) {
      hrStatsEl.textContent = 'bili: 在线 :18788（stats 拉取中/失败）';
      hrStatsEl.style.color = 'var(--accent)';
      return;
    }
    // 对抗审 a206A 口径统一：reqs/saved 同源 /__bili/sessions 汇总（含历史
    // 会话），hit 为活会话 cached/input 全局比——后端 totals 三键直供
    const tot = st.totals || {};
    const reqs = tot.requests || 0, saved = tot.tokensSaved || 0;
    const hit = typeof tot.cacheHitPct === 'number' ? tot.cacheHitPct : null;
    hrStatsEl.textContent = `bili :18788 | ${_pxFnum(reqs)} 请求 | 压缩节省 ${_pxTok(saved)} token` +
      (hit !== null ? ` | 缓存命中 ${hit}%` : '');
    hrStatsEl.style.color = saved ? 'var(--accent)' : 'var(--muted)';
  }

  function _setHrUI(j) {
    // 主面板不再摆 radio（易误点——用户实锤）：只更新配置按钮文案，
    // 选择动作全部进弹窗（仿原工具 _hr_mode_dialog）
    conn.hrState = j;
    const lab = { on: '开启压缩', off: '关闭' }[j.bili_mode] || '—';
    hrCfgBtn.textContent = '压缩模式：' + lab;
    hrCfgBtn.title = j.running ? '选择压缩策略（应用立即生效）'
      : '重试代理未启动：开启压缩需先启动代理（关闭可直接记住）';
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
    // a452（第二轮审计）：这里原来无条件 _msg，3s 一轮把用户刚点的操作
    // 反馈盖掉（例如常驻的「已有实例在跑」提示压掉「自动刷新已开启」）。
    if (j.already_running) { if (!_msgHeld()) _msg('检测到已有 Claude 代理实例在 37349 端口（原独立工具在跑）——面板仅展示，复用不杀', false); }
    else if (j.port_busy) { if (!_msgHeld()) _msg('端口 37349 被其他程序占用，无法启动', true); }
    else if (!_msgHeld()) _msg('');
      _renderStats(j.snapshot);
      _renderHist(j.snapshot);
      _renderHrStats(j);
      _setHrUI(j);
      _setRetryUI(j);
      _renderBiliInstall(j);
      // 操作反馈保鲜期：bili 是常驻状态，不该抢用户刚点按钮的结果
      const _biliHold = _msgHeld();
      if (!j.bili_ready && j.bili_mode === 'on') {
        msgEl.dataset.biliKeep = '1';
        if (!_biliHold)
          _msg('压缩引擎未安装——下方「联网下载安装」一键装（需 Node ≥22 + 网络）；重试代理不受影响', true);
      } else if (j.bili_last_err) {
        // a203：后端切换失败会静默回退 off，原样只留一行 log——用户只看到
        // 「点了没反应」。把原因顶到面板上（切成功后后端清空该字段）。
        msgEl.dataset.biliKeep = '1';
        if (!_biliHold) _msg(j.bili_last_err, true);
      } else if (msgEl.dataset.biliKeep === '1' && !_msgHeld()) {
        // a452（审计）：原来这里删的是**共用的** dataset.keep，把操作反馈
        // 的 6s 保鲜期一并摧毁（实际只剩不到 3s）。bili 用自己的标志。
        delete msgEl.dataset.biliKeep;
        _msg('');
      }
    } catch(e) {
      // 网络/解析失败同样不静默——连不上的原因要上屏
      if (!conn._pollErrShown) { conn._pollErrShown = true; _msg('状态轮询失败: ' + e, true); }
    }
  }

  // tab 激活/切走控制轮询（流畅守则：看不见不轮询）。
  // switchTab 靠 wrap.style.display 切换，无回调可挂——tick 开头检测：
  // 隐藏即停 interval（下次 switchTab 回来时 startPoll 重建）。
  // a672：额度「上次刷新 Ns 前」倒计时随额度区一起迁到 Lanzi 专栏，
  // 代理面板这里不再需要 1s tick。
  function _startPoll() {
    if (!conn.pollTimer) { conn.pollTimer = setInterval(_tickPoll, 3000)   /* v3.5.288: 1s→3s——代理状态无需秒级刷新（卡死报告 §6.4） */; _poll(); }
  }
  function _stopPoll() {
    if (conn.pollTimer) { clearInterval(conn.pollTimer); conn.pollTimer = null; }
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

  // ---- bili 压缩配置弹窗（a201 换代自 headroom；模式卡+预览）----
  // off 永远可选（代理未跑=只记模式下次启动生效）；on 在 bili 缺失时禁用
  const HR_CARDS = [
    ['on', '开启压缩', '模型驱动分层压缩', '收益: tier-1/2/3 分层蒸馏（可逆，decompress 可恢复原文），子代理独立压缩命名空间，缓存友好设计（健康线 95-97% 命中）\n减益: 需 Node >=22 + npm install -g billion-context；压缩调用占少量 token（健康线 <=2%）'],
    ['off', '关闭压缩', '不启动 bili', '收益: 零额外内存、零冷启动等待\n减益: 无任何压缩收益，流量原样过重试代理'],
  ];
  const HR_NOTE = '注: 签名 thinking 块逐字节透传（签名校验要求），主会话该部分不可压缩；'
    + '收益主要来自子代理（独立压缩命名空间）与工具输出（95% 紧急截断）。';

  function _hrCfgModal() {
    const j = conn.hrState || {};
    const hasHr = !!j.bili_ready;
    let m = $('pxHrModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'pxHrModal';
      m.innerHTML = `
        <div class="box" style="max-width:600px;">
          <div class="head"><strong>billion-context 压缩配置</strong>
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
            <!-- 对抗审 a206A：CCR 勾选退役（headroom 特性，bili 无此开关） -->
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
    // 初始态：预选当前模式；on 需已装 billion-context 且代理在跑（与后
    // 端 apply_bili_mode 拒绝口径一致）；off 永远可选
    const canFull = hasHr && !!j.running;
    cards.forEach(lab => {
      const rb = lab.querySelector('input');
      rb.checked = rb.value === (j.bili_mode || 'off');
      lab.classList.toggle('px-dis', !canFull && rb.value !== 'off');
      rb.disabled = !canFull && rb.value !== 'off';
    });
    m.querySelector('[data-hr-warn]').innerHTML = hasHr ? ''
      : '<div style="color:var(--neon-orange);font-size:12px;margin-bottom:8px;"> 未检测到 billion-context（需 Node ≥22 + npm install -g billion-context），压缩不可用；重启工具可再试</div>';
    // CCR 勾选已退役（对抗审 a206A：headroom 特性对 bili 无效，空开关）
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
          body: JSON.stringify({mode})});
        const jj = await r.json();
        _msg(jj.ok ? (mode === 'off' ? '已关闭压缩'
             : (j.running ? '切换中（bili 启动中，就绪自动切压缩链路）'
                          : '已记住，启动代理后生效（下次启动自动拉起）'))
             : (jj.msg || '切换失败'), !jj.ok);
        if (jj.ok) { close(); _poll(); }
      } catch(e) { _msg('请求失败: ' + e, true); }
      applyBtn.disabled = false;
    };
    m.classList.add('show');
  }

  // 初始一次渲染 + 1s 轮询（_tickPoll 内检测 tab 可见性，切走自动停；
  // 切回时 switchTab 调 conn.onResumePoll 恢复）
  conn.onResumePoll = _startPoll;
  _startPoll();

  switchTab(portId);
  refreshSidebar();
  return conn;
}

// 模块化一期：转 ES module——跨文件/Python 裸引用消费名挂 window。
// 清单由 eslint no-undef 神谕反推（零启发式）：本文件转模块后，其余
// 文件/Python 推送的裸标识符引用全部经 window 解析。
window._pxFnum = _pxFnum;
window._pxTok = _pxTok;
window.buildProxyTab = buildProxyTab;
