// lanzi/panel.js — Lanzi 专栏（a672，用户需求：机器人/内网登录/额度三合一）
//
// 为什么单独一个 tab：原来额度挤在代理面板里、登录/机器人挤在 harness 侧栏
// 小浮层里，三样都跟「代理转发」没直接关系，只是历史上都挂在代理模块下。
// 现在集中成一个专栏，代理面板回到纯粹转发职责。
//
// 生效范围（用户定调）：额度/负载只在**上游 host 是 lanz.hikvision.com**
// 时才有意义。判据取后端下发的 lanz_active（认上游、不认 base_url——代理
// 会改 base_url，上游不会）。非 lanzi 网关时额度区显示占位提示，登录与
// 机器人照常可用。
//
// 接口：/api/lanzi/*（status|login|logout|refresh|relogin|auto|auto_relogin
//       |sso_probe|bot_status|bot_activate|bot_credentials）
'use strict';

const LANZI_ID = 'lanzi:main';

// 数字缩写（与后端 lanzi.api.fnum / 代理 _pxFnum 同口径）
function _lzFnum(n) {
  n = Number(n) || 0;
  if (n >= 1e8) return String(Math.round(n));
  if (n >= 1e4) return (n / 1e4).toFixed(1) + 'W';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
}
function _lzTok(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
}

function buildLanziTab() {
  // 单例：已开就激活
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'lanzi') { switchTab(pid); return connections[pid]; }
  }

  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = LANZI_ID;
  tab.innerHTML = '<span class="led"></span>' +
    '<span class="tab-ico" title="Lanzi"><img src="/ico/lanz.png" alt="" ' +
    'style="width:16px;height:16px;vertical-align:-3px;"></span>' +
    '<span class="label">Lanzi</span><span class="baud"></span>' +
    '<span class="close" title="关闭">✕</span>';
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(LANZI_ID); return; }
    switchTab(LANZI_ID);
  };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = LANZI_ID;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <span class="px-badge px-stopped" data-lz-bot-badge>机器人</span>
        <span class="px-url" data-lz-active title="当前上游主机">上游：-</span>
        <span class="hg-flex1"></span>
        <button class="lv-btn" data-lz-refresh title="立即刷新额度（沿用当前登录）">↻ 刷新</button>
      </div>
      <div class="px-body">
        <div class="px-msg" data-lz-msg></div>

        <!-- 账号登录（内网 SSO） -->
        <div class="px-sec">
          <div class="px-sec-title">内网登录</div>
          <div class="px-quota-login">
            <input autocomplete="off" name="lz_user" data-lz-user placeholder="内网 SSO 用户名" spellcheck="false" style="width:150px;">
            <span class="px-eye-wrap">
              <input autocomplete="off" name="lz_pwd" data-lz-pwd type="password" placeholder="密码" spellcheck="false" style="width:200px;">
              <button class="px-eye" data-lz-eye title="显示/隐藏密码" tabindex="-1" aria-label="显示或隐藏密码">${window.ICO16 ? ICO16.eye : ''}</button>
            </span>
            <button class="lv-btn" data-lz-save>登录</button>
            <button class="lv-btn" data-lz-relogin title="登录失效时的自救：丢弃旧会话强制重新登录">强制重登</button>
            <button class="lv-btn" data-lz-logout title="删除本地凭据（机器人不受影响）">断开</button>
            <label class="px-q-auto" title="每 10 分钟自动刷新额度"><input type="checkbox" name="lz_auto" data-lz-auto checked> 自动刷新(10min)</label>
            <label class="px-q-auto" title="登录失败时自动重登（SSO 锁定期间建议关闭）"><input type="checkbox" name="lz_autologin" data-lz-autologin checked> 自动重登</label>
          </div>
          <div class="px-q-statrow">
            <span data-lz-status></span>
            <span class="px-q-last" data-lz-last>上次刷新 -</span>
            <span class="hg-flex1"></span>
            <button class="lv-btn" data-lz-probe title="匿名探测 SSO 是否锁定（不提交任何凭据，不会重置锁定计时）">探测锁定</button>
          </div>
        </div>

        <!-- 机器人凭据（手填 App ID / Secret） -->
        <div class="px-sec">
          <div class="px-sec-title">机器人</div>
          <div class="px-quota-login">
            <span class="lz-dot off" data-lz-bot-dot></span>
            <span class="px-q-k" data-lz-bot-state>未配置凭据</span>
          </div>
          <div class="px-quota-login">
            <input class="lz-inp" data-lz-bot-id placeholder="App ID" spellcheck="false" autocomplete="off" name="lz_bot_id" style="width:240px;">
            <span class="px-eye-wrap">
              <input class="lz-inp" data-lz-bot-secret type="password" placeholder="App Secret" autocomplete="new-password" name="lz_bot_secret" style="width:240px;">
              <button class="px-eye" data-lz-bot-eye title="显示/隐藏密钥" tabindex="-1" aria-label="显示或隐藏密钥">${window.ICO16 ? ICO16.eye : ''}</button>
            </span>
            <button class="lv-btn" data-lz-bot-save title="保存后立即用该机器人重连">保存机器人</button>
          </div>
        </div>

        <!-- 额度（只在 lanzi 上游时有效） -->
        <div class="px-sec">
          <div class="px-sec-title">Lanz 额度</div>
          <div data-lz-gate></div>
          <div data-lz-quota-view></div>
          <div data-lz-quota-rank></div>
          <div data-lz-loads></div>
        </div>
      </div>
    </div>`;

  const tabs = document.getElementById('tabs');
  const termArea = document.getElementById('termArea');
  // 冷启动无 tab 时主区有 .empty-state；不摘掉它会与新面板叠在一起
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const $p = (sel) => wrap.querySelector(sel);
  const msgEl = $p('[data-lz-msg]');
  const statusEl = $p('[data-lz-status]');
  const lastEl = $p('[data-lz-last]');
  const userEl = $p('[data-lz-user]');
  const pwdEl = $p('[data-lz-pwd]');
  const gateEl = $p('[data-lz-gate]');
  const quotaViewEl = $p('[data-lz-quota-view]');
  const rankEl = $p('[data-lz-quota-rank]');
  const loadsEl = $p('[data-lz-loads]');
  const botDotEl = $p('[data-lz-bot-dot]');
  const botStateEl = $p('[data-lz-bot-state]');
  const botBadgeEl = $p('[data-lz-bot-badge]');
  const activeEl = $p('[data-lz-active]');

  const conn = {
    // portId 必填：editor.js 的 _edCloseNow 用 `delete connections[conn.portId]`
    // 出册，缺它会删到 undefined 键——连接表残留幽灵项，侧栏/抽屉多一行，
    // 再次打开时单例命中已摘 DOM 的僵尸 conn，主区永久空白（必须刷页）。
    portId: LANZI_ID,
    meta: { kind: 'lanzi', label: 'Lanzi' },
    tab, wrap,
    pollTimer: null,
    quotaTs: 0,
  };
  connections[LANZI_ID] = conn;
  window._lzConn = conn;   // 供 shell.js 的按钮跳转复用

  // ---- 消息区（与代理面板同款保鲜期语义）----
  function _msg(text, bad) {
    msgEl.textContent = text || '';
    msgEl.style.color = bad ? 'var(--danger,#ff5468)' : 'var(--muted)';
    msgEl.style.display = text ? '' : 'none';
  }
  function _msgKeep(text, bad) {
    msgEl.dataset.keep = '1';
    msgEl.dataset.keepUntil = String(Date.now() + 6000);
    _msg(text, bad);
  }
  function _msgHeld() {
    const until = parseInt(msgEl.dataset.keepUntil || '0', 10) || 0;
    return msgEl.dataset.keep === '1' && Date.now() < until;
  }

  function _lastText() {
    if (!conn.quotaTs) return '上次刷新 -';
    const ago = Math.max(0, Math.round(Date.now() / 1000 - conn.quotaTs));
    const t = new Date(conn.quotaTs * 1000).toLocaleTimeString('zh-CN', { hour12: false });
    return `上次刷新 ${t} (${ago}s 前)`;
  }

  // ---- 机器人状态灯（语义与 harness 侧栏一致，勿各自造）----
  function _botLed(j) {
    if (!j.manual) return 'lz-dot off';
    if (j.running && j.connected) return 'lz-dot on';
    if (j.remote_running) return 'lz-dot on';
    if (j.auth_failed) return 'lz-dot err';
    if (!j.running) return 'lz-dot idle';
    return 'lz-dot wait';
  }
  function _botPhase(j) {
    if (!j.manual) return '未配置凭据';
    if (j.running && j.connected) return '在线';
    if (j.remote_running) return '在线（本机另一进程 PID ' + j.remote_pid + '）';
    if (j.auth_failed) return '凭据被拒，请检查 App ID/Secret';
    if (!j.running) return j.kick_note || '已保存，未运行';
    return '连接中…';
  }

  // ---- 额度渲染（自 proxy-panel 平移，布局/口径不变）----
  function _renderQuota(j) {
    const lg = j.quota_login;
    const state = lg ? lg.state : null;
    const mk = (t, c) => `<span class="px-badge ${c}">${esc(t)}</span>`;
    if (state === 'logging') statusEl.innerHTML = mk('● 登录中…', 'px-retry');
    else if (state === 'online') statusEl.innerHTML = mk('● 在线 ' + (lg.user || ''), 'px-healthy');
    else if (state === 'error') statusEl.innerHTML = mk('登录失败', 'px-failed');
    else if (state === 'locked') statusEl.innerHTML = mk('账号锁定 · 已停止自动登录', 'px-failed');
    else if (state === 'fetch_err') statusEl.innerHTML = mk('查询失败', 'px-failed');
    else if (!j.has_credentials) statusEl.innerHTML = mk('● 未登录', 'px-stopped');
    else statusEl.innerHTML = '';

    if (j.quota_ts) conn.quotaTs = j.quota_ts;
    lastEl.textContent = _lastText();
    // 两个开关以后端持久化值为准回填（用户没在操作时）——迁移前
    // proxy-panel 有这段，漏搬会让「已关自动刷新」在重开后仍显示勾选。
    const _autoEl = $p('[data-lz-auto]');
    if (_autoEl && document.activeElement !== _autoEl)
      _autoEl.checked = j.quota_auto !== false;
    const _autoReloginEl = $p('[data-lz-autologin]');
    if (_autoReloginEl && document.activeElement !== _autoReloginEl)
      _autoReloginEl.checked = j.quota_auto_relogin !== false;

    if (state === 'locked')
      _msg('账号已被 SSO 锁定，已停止自动登录（每次尝试都会重置锁定计时）。'
        + '请等待 8~30 分钟或联系 itsm@hikvision.com 解锁后再手动刷新。', true);
    else if (_msgHeld()) { /* 操作反馈优先 */ }
    else if (state === 'error' || state === 'fetch_err')
      _msg((state === 'error' ? '登录失败: ' : '查询失败: ') + (lg.msg || ''), true);
    else if (state === 'online') _msg('');

    if (!userEl._dirty && j.quota_username && !userEl.value) userEl.value = j.quota_username;
    if (!pwdEl._dirty && j.quota_password && !pwdEl.value) pwdEl.value = j.quota_password;

    _renderLoads(j);

    const ov = j.quota_overview;
    if (!ov) {
      quotaViewEl.innerHTML = '<div class="px-hint">登录后显示额度（10 分钟自动刷新）</div>';
      return;
    }
    const tile = (u, l) => {
      u = u || 0; l = l || 0;
      const hot = l && u / l >= 0.85;
      return `<span class="px-q-tile ${hot ? 'px-q-hot' : ''}">${_lzFnum(u)} / ${_lzFnum(l)}</span>`;
    };
    let html = `<div class="px-q-row"><span class="px-q-k">今日外部</span>${tile(ov.externalDailyUsed, ov.externalDailyLimit)}` +
      `<span class="px-q-k">今日内部</span>${tile(ov.internalDailyUsed, ov.internalDailyLimit)}` +
      `<span class="px-q-k">请求</span><span class="px-q-tile">${_lzFnum(ov.dailyRequestCount)}</span></div>`;
    if (ov.hasBudget) {
      const tot = ov.totalCredits || 0, r = ov.usageRate || 0;
      html += `<div class="px-q-row"><span class="px-q-k">剩余积分</span><span class="px-q-tile">${Math.round(ov.remainCredit || 0)}</span>` +
        `<span class="px-q-k">总消耗</span><span class="px-q-tile">${Math.round(tot)}${r ? ` (${Math.round(r * 100)}%)` : ''}</span></div>`;
    }
    const models = j.quota_models || [];
    if (models.length) {
      html += '<div class="px-q-models">' + models.map(m => {
        const hot = m.limit && m.used / m.limit >= 0.85;
        return `<div class="px-q-model ${hot ? 'px-q-hot' : ''}"><span class="px-q-mk">${esc(m.name)}</span>` +
          `<span>已用 ${_lzFnum(m.used)}</span><span>还剩 ${_lzFnum(m.remain)}</span><span>${m.pct}%</span></div>`;
      }).join('') + '</div>';
    }
    quotaViewEl.innerHTML = html;

    const rank = j.quota_rank || [];
    if (rank.length) {
      let rhtml = '<div class="px-rank-title">模型用量排名' +
        (j.quota_ts ? `<span class="px-rank-ago">上次刷新 ${new Date(j.quota_ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</span>` : '') +
        '</div><div class="px-rank"><div class="px-rank-h"><span>模型</span><span>tokens</span><span>费用</span><span>积分</span><span>请求数</span></div>';
      rank.forEach(m => {
        rhtml += `<div class="px-rank-r"><span class="px-rank-m">${esc(String(m.finalModel || '?'))}</span>` +
          `<span>${_lzTok(m.tokens)}</span><span>${(m.cost || 0).toFixed(2)}</span>` +
          `<span>${(m.credits || 0).toFixed(2)}</span><span>${_lzFnum(m.requestCount)}</span></div>`;
      });
      rankEl.innerHTML = rhtml + '</div>';
    } else {
      rankEl.innerHTML = '';
    }
  }

  // 模型负载：数据由后端只在上游是 lanz 时下发
  function _renderLoads(j) {
    const loads = j.model_loads;
    if (!loads || !loads.length) {
      loadsEl.innerHTML = (j.model_loads_err && j.lanz_active)
        ? '<div class="px-sec-title">模型负载<span class="px-rank-ago">' + esc(j.model_loads_err) + '</span></div>'
        : '';
      return;
    }
    const lvTxt = { jam: '拥挤', busy: '繁忙', normal: '正常', idle: '空闲' };
    loadsEl.innerHTML = '<div class="px-sec-title">模型负载' +
      '<span class="px-rank-ago">' +
      (j.model_loads_ts ? '更新于 ' + new Date(j.model_loads_ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : '') +
      '</span></div><div class="px-loads">' + loads.map(m => {
        const pct = (m.pct == null) ? null : m.pct;
        const cls = m.level ? ' px-load--' + m.level : '';
        return '<div class="px-load-row"><span class="px-load-name">' + esc(m.name) + '</span>' +
          '<span class="px-load-bar' + cls + '"><i style="width:' + (pct == null ? 0 : pct) + '%"></i></span>' +
          '<span class="px-load-pct' + cls + '">' + (pct == null ? '--' : pct + '%') +
          (m.level ? ' · ' + lvTxt[m.level] : '') + '</span>' +
          (m.active != null && m.max != null ? '<span class="px-load-num">' + m.active + '/' + m.max + '</span>' : '') +
          '</div>';
      }).join('') + '</div>';
  }

  // 生效闸：非 lanzi 上游时额度区给明确提示（用户定调：全部显示并提示）
  function _renderGate(j) {
    if (j.lanz_active) { gateEl.innerHTML = ''; return; }
    gateEl.innerHTML = '<div class="px-hint" style="margin-bottom:8px;">当前上游 <code>' +
      esc(j.upstream_host || '未知') + '</code> 不是 lanzi 网关，额度/负载不可用。' +
      '登录与机器人不受影响。</div>';
  }

  // ---- 机器人渲染 ----
  let _lzLastBot = {};
  function _renderBot(bot, status) {
    // bot_status 与 status 的机器人字段同名（status_snapshot 直传），
    // 合并后的对象同时含 running/connected/manual/app_id 等
    const j = Object.assign({}, status || {}, bot || {});
    _lzLastBot = j;   // 保存机器人时判「沿用旧密钥」要用
    botDotEl.className = _botLed(j);
    botStateEl.textContent = _botPhase(j);
    botBadgeEl.textContent = '机器人 ' + (j.manual ? (_botPhase(j) || '在线') : '未配置');
    botBadgeEl.className = 'px-badge ' + ((j.running && j.connected) || j.remote_running
      ? 'px-healthy' : (j.auth_failed ? 'px-failed' : 'px-stopped'));
    const idEl = $p('[data-lz-bot-id]');
    if (idEl) {
      if (j.app_id && !idEl.dataset.dirty && !idEl.value) idEl.value = j.app_id;
      if (idEl.dataset.dirty && j.app_id && idEl.value === j.app_id) idEl.dataset.dirty = '';
    }
    const secEl = $p('[data-lz-bot-secret]');
    if (secEl) {
      if (j.app_secret && !secEl.dataset.dirty && !secEl.value) secEl.value = j.app_secret;
      if (secEl.dataset.dirty && j.app_secret && secEl.value === j.app_secret) secEl.dataset.dirty = '';
    }
  }

  // ---- 轮询 ----
  async function _poll() {
    try {
      const j1 = await fetch('/api/lanzi/status').then(r => r.json()).catch(() => null);
      if (!j1 || !j1.ok) return;
      _renderGate(j1);
      _renderQuota(j1);
      activeEl.textContent = '上游：' + (j1.upstream_host || '-');

      const j2 = await fetch('/api/lanzi/bot_status').then(r => r.json()).catch(() => null);
      // j2 失败时不写 _lzLastBot：manual/app_id 会被清空，导致
      // 「Secret 留空沿用旧值」被误拦（后端实际支持）
      if (j2 && j2.ok) _renderBot(j2, j1);
    } catch (_) {}
  }

  function _startPoll() {
    if (conn.pollTimer) return;
    _poll();
    conn.pollTimer = setInterval(() => {
      if (wrap.style.display === 'none') { _stopPoll(); return; }
      _poll();
    }, 3000);
  }
  function _stopPoll() {
    if (conn.pollTimer) { clearInterval(conn.pollTimer); conn.pollTimer = null; }
  }
  conn.onResumePoll = _startPoll;

  // ---- 输入交互 ----
  userEl.addEventListener('input', () => { userEl._dirty = true; });
  pwdEl.addEventListener('input', () => { pwdEl._dirty = true; });
  const botIdEl = $p('[data-lz-bot-id]');
  const botSecEl = $p('[data-lz-bot-secret]');
  botIdEl.addEventListener('input', () => { botIdEl.dataset.dirty = '1'; });
  botSecEl.addEventListener('input', () => { botSecEl.dataset.dirty = '1'; });

  // 眼睛切换（密码/密钥各一）
  wrap.querySelectorAll('.px-eye').forEach(btn => {
    btn.onclick = () => {
      const inp = btn.parentElement.querySelector('input');
      if (!inp) return;
      const show = inp.type === 'password';
      inp.type = show ? 'text' : 'password';
      btn.classList.toggle('px-eye-on', show);
      btn.title = show ? '隐藏' : '显示';
    };
  });

  $p('[data-lz-save]').onclick = async () => {
    const u = userEl.value.trim(), p = pwdEl.value;
    if (!u || !p) { _msgKeep('用户名/密码不能为空', true); return; }
    _msgKeep('正在登录…');
    try {
      const j = await fetch('/api/lanzi/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p })
      }).then(r => r.json());
      if (j.ok) {
        if (userEl.value.trim() === u) userEl._dirty = false;
        if (pwdEl.value === p) pwdEl._dirty = false;
      }
      _msgKeep(j.msg || (j.ok ? '已保存，开始登录' : '登录失败'), !j.ok);
      _poll();
    } catch (e) { _msgKeep('请求失败: ' + e, true); }
  };

  $p('[data-lz-logout]').onclick = async () => {
    try {
      const j = await fetch('/api/lanzi/logout', { method: 'POST' }).then(r => r.json());
      userEl.value = ''; pwdEl.value = '';
      userEl._dirty = false; pwdEl._dirty = false;
      conn.quotaTs = 0;
      _msgKeep(j.msg || '已断开登录', !j.ok);
      _poll();
    } catch (e) { _msgKeep('请求失败: ' + e, true); }
  };

  $p('[data-lz-refresh]').onclick = async () => {
    try {
      const j = await fetch('/api/lanzi/refresh', { method: 'POST' }).then(r => r.json());
      _msgKeep(j.msg || (j.ok ? '已触发刷新' : '刷新失败'), !j.ok);
      setTimeout(_poll, 1200);
    } catch (e) { _msgKeep('请求失败: ' + e, true); }
  };

  $p('[data-lz-relogin]').onclick = async () => {
    if (!(await _ddConfirm('强制重登',
      '丢弃当前登录会话，用保存的凭据重新登录拉取额度？\n（代理转发不受任何影响，只刷新额度登录状态）'))) return;
    try {
      const j = await fetch('/api/lanzi/relogin', { method: 'POST' }).then(r => r.json());
      _msgKeep(j.msg || (j.ok ? '已触发强制重登' : '触发失败'), !j.ok);
      setTimeout(_poll, 1500);
    } catch (e) { _msgKeep('请求失败: ' + e, true); }
  };

  $p('[data-lz-probe]').onclick = async () => {
    _msgKeep('正在匿名探测 SSO 状态…');
    try {
      const j = await fetch('/api/lanzi/sso_probe').then(r => r.json());
      if (!j.ok) { _msgKeep('探测失败: ' + (j.error || ''), true); return; }
      if (j.locked === true) _msgKeep('SSO 判定：锁定中 — ' + (j.hint || ''), true);
      else if (j.locked === false) _msgKeep('SSO 判定：未锁定 — ' + (j.hint || ''));
      else _msgKeep('SSO 无法判定 — ' + (j.hint || ''));
    } catch (e) { _msgKeep('探测失败: ' + e, true); }
  };

  const autoEl = $p('[data-lz-auto]');
  autoEl.onchange = async (e) => {
    try {
      const j = await fetch('/api/lanzi/auto', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto: e.target.checked })
      }).then(r => r.json());
      _msgKeep(j.msg || '', !j.ok);
    } catch (err) { e.target.checked = !e.target.checked; _msgKeep('请求失败: ' + err, true); }
  };
  const autoReloginEl = $p('[data-lz-autologin]');
  autoReloginEl.onchange = async (e) => {
    try {
      const j = await fetch('/api/lanzi/auto_relogin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_relogin: e.target.checked })
      }).then(r => r.json());
      _msgKeep(j.msg || '', !j.ok);
    } catch (err) { e.target.checked = !e.target.checked; _msgKeep('请求失败: ' + err, true); }
  };

  $p('[data-lz-bot-save]').onclick = async () => {
    const id = (botIdEl.value || '').trim();
    let secret = (botSecEl.value || '').trim();
    const keepSecret = !secret && id && _lzLastBot.manual && _lzLastBot.app_id === id;
    if (id && !secret && !keepSecret) { _msgKeep('请填写 App Secret', true); return; }
    if (!id && secret) { _msgKeep('请填写 App ID', true); return; }
    if (!id && !secret && _lzLastBot.manual !== false
        && !confirm('将清除已保存的机器人凭据并断开当前机器人连接，确定吗？')) return;
    const btn = $p('[data-lz-bot-save]');
    btn.disabled = true; const old = btn.textContent; btn.textContent = '保存中…';
    try {
      const j = await fetch('/api/lanzi/bot_credentials', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: id, app_secret: secret })
      }).then(r => r.json());
      _msgKeep(j.msg || (j.ok ? '已保存' : '保存失败'), !j.ok);
      setTimeout(_poll, 1500);
    } catch (e) { _msgKeep('保存请求失败: ' + e, true); }
    btn.disabled = false; btn.textContent = old;
  };
  // tab 关闭时的收尾钩子（editor.js 的 _edCloseNow 按 kind==='lanzi' 调用）
  window._lzTeardown = function () {
    try { _stopPoll(); } catch (_) {}
    try { _lzTipHide(); } catch (_) {}
    _lzTipAnchor = null;
    if (window._lzConn === conn) window._lzConn = null;
  };

  _startPoll();
  switchTab(LANZI_ID);
  if (typeof refreshSidebar === 'function') refreshSidebar();

  // 侧栏「机器人/登录」按钮点击 → 打开本 tab（用户定调）
  return conn;
}

// 侧栏按钮跳转：捕获阶段吞掉 harness 的浮层逻辑（浮层已随面板迁走）
// 兜底：harness shell.js 里那条「点胶囊开浮层」的监听会先注册（模块加载
// 顺序在 main.js/shell.js 之前保证不了），所以这里用 capture 抢占。
document.addEventListener('click', (ev) => {
  const tg = ev.target && ev.target.closest
    ? ev.target.closest('[data-hg-login-toggle]') : null;
  if (!tg) return;
  ev.preventDefault();
  ev.stopPropagation();
  if (window._lzConn && document.contains(window._lzConn.wrap)) {
    switchTab('lanzi:main');
  } else {
    buildLanziTab();
  }
}, true);

// ---- 模型负载悬浮卡（a672：自 harness/shell.js 平移，挂到 Lanzi tab 上）----
// 用户定调：原来悬在 Proxy 按钮上，现在悬在 Lanzi（机器人+登录）入口上。
// 数据源仍是 /api/lanzi/status 的 model_loads（只有上游是 lanz 时下发）。
let _lzLoads = null;
let _lzLoadsErr = '';
let _lzLoadsSupported = true;
let _lzTip = null;
let _lzTipAnchor = null;
let _lzTipTick = null;

function _lzTipEl() {
  if (_lzTip && document.contains(_lzTip)) return _lzTip;
  const el = document.createElement('div');
  el.className = 'hg-loads-tip';
  el.style.display = 'none';
  document.body.appendChild(el);
  _lzTip = el;
  return el;
}

function _lzTipPaint(anchor) {
  const tip = _lzTipEl();
  const loads = _lzLoads;
  if (!loads || !loads.length) {
    tip.innerHTML = '<div class="hg-loads-row"><span class="hg-loads-name" ' +
      'style="color:var(--muted)">' +
      (_lzLoadsErr ? esc(_lzLoadsErr) : '负载加载中…') + '</span></div>';
  } else {
    tip.innerHTML = loads.map(m => {
      const pct = (m.pct == null) ? null : m.pct;
      const cls = m.level ? ' px-load--' + m.level : '';
      return '<div class="hg-loads-row"><span class="hg-loads-name">' + esc(m.name) + '</span>' +
        '<span class="hg-loads-bar' + cls + '"><i style="width:' + (pct == null ? 0 : pct) + '%"></i></span>' +
        '<span class="hg-loads-pct' + cls + '">' + (pct == null ? '--' : pct + '%') + '</span></div>';
    }).join('');
  }
  tip.style.display = 'block';
  const r = anchor.getBoundingClientRect();
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  // 标签在窗口顶部，优先向下弹；下方放不下再向上
  let top = r.bottom + 6;
  if (top + th > window.innerHeight - 8) top = Math.max(8, r.top - th - 6);
  const avail = window.innerHeight - 16;
  if (th > avail) { tip.style.maxHeight = avail + 'px'; tip.style.overflowY = 'auto'; top = 8; }
  else { tip.style.maxHeight = ''; tip.style.overflowY = ''; }
  tip.style.top = Math.round(Math.max(8, Math.min(top, window.innerHeight - th - 8))) + 'px';
  let left = r.left;
  if (left + tw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - tw - 8);
  tip.style.left = Math.round(left) + 'px';
}

function _lzTipHide() {
  if (_lzTip) _lzTip.style.display = 'none';
  _lzTipStopTick();
}

function _lzTipStopTick() {
  if (_lzTipTick) { clearInterval(_lzTipTick); _lzTipTick = null; }
}

function _lzTipTickStart(anchor) {
  _lzTipStopTick();
  _lzTipTick = setInterval(() => {
    if (!_lzTip || _lzTip.style.display === 'none') { _lzTipStopTick(); return; }
    _lzTipAnchor = anchor;
    _lzTipFetch(anchor);
  }, 20000);
}

async function _lzTipFetch(anchor) {
  try {
    const j = await fetch('/api/lanzi/status').then(r => r.json());
    if (!j || !j.ok) return;
    _lzLoads = (j.model_loads && j.model_loads.length) ? j.model_loads : null;
    _lzLoadsErr = j.model_loads_err || '';
    _lzLoadsSupported = j.model_loads_supported !== false;
    if (!_lzLoadsSupported) {
      _lzLoadsErr = '';
      _lzTipHide();
      _lzTipAnchor = null;
      return;
    }
    if (anchor && _lzTip && _lzTip.style.display !== 'none') _lzTipPaint(anchor);
  } catch (_) {}
}

// 挂在 Lanzi 标签上（委托：标签可能晚于本模块创建）。
// 只在模块加载时挂一次——若写进 buildLanziTab 内部，关键在于本段代码在
// 模块顶层；tab 关闭重开不会重复挂（委托天然跟随 DOM）。
// 两个悬停锚点（用户需求）：顶部 Lanzi 标签 + harness 侧栏「机器人」按钮。
// 后者让用户不开面板也能一眼看到负载。
function _lzHoverAnchor(target) {
  if (!target || !target.closest) return null;
  return target.closest('.tab[data-port-id="lanzi:main"]')
    || target.closest('[data-hg-login-toggle]');
}
// 委托挂在 document 上：标签/侧栏按钮都可能晚于本模块创建，且 tab 关闭
// 重开不会重复挂（委托天然跟随 DOM）。
document.addEventListener('mouseover', ev => {
  const anchor = _lzHoverAnchor(ev.target);
  if (!anchor) return;
  if (anchor.contains(ev.relatedTarget)) return;   // 子元素间移动不算重入
  // 已知上游不支持负载（非 lanzi 网关）时不出卡——否则每次悬停先闪一张
  // 「负载加载中…」空卡再消失（一次悬停一次闪烁 + 一次多余请求）
  if (!_lzLoadsSupported) { _lzTipHide(); return; }
  _lzTipAnchor = anchor;
  _lzTipFetch(anchor);
  _lzTipPaint(anchor);
  _lzTipTickStart(anchor);
});
document.addEventListener('mouseout', ev => {
  const anchor = _lzHoverAnchor(ev.target);
  if (!anchor) return;
  if (anchor.contains(ev.relatedTarget)) return;
  _lzTipAnchor = null;
  _lzLoadsErr = '';
  _lzTipHide();
});

window.buildLanziTab = buildLanziTab;
