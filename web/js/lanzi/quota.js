// lanzi/quota.js — Lanzi 专栏的「额度」渲染（a673 模块化拆分）
//
// 职责边界：只负责把后端 status 的额度字段画进给定的 DOM 槽，不自己发请求、
// 不持有轮询。宿主 panel.js 每次 /api/lanzi/status 回来调一次 renderQuota。
//
// 依赖 window.esc（util.js 经典脚本导出）；数字缩写走 lanzi/util.js。
import { lzFnum, lzTok } from './util.js';

/**
 * @param {object} els  {statusEl, lastEl, gateEl, quotaViewEl, rankEl, loadsEl}
 * @param {object} j    /api/lanzi/status 的响应
 * @param {object} ctl  {conn, userEl, pwdEl, autoEl, autoReloginEl, msg, msgHeld}
 */
export function renderQuota(els, j, ctl) {
  const { statusEl, lastEl, gateEl, quotaViewEl, rankEl } = els;
  const { conn, userEl, pwdEl, autoEl, autoReloginEl, msg, msgHeld } = ctl;

  // ---- 生效闸：非 lanzi 上游时额度区给明确提示（用户定调：全部显示并提示）----
  // 用内容签名比对，避免每 3s 无脑重建同一段 DOM（会重置选中/滚动位置，
  // 文字也无法拖选）。
  _renderGate(gateEl, j);

  // ---- 登录态徽标 ----
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
  lastEl.textContent = _lastText(conn);

  // 两个开关以后端持久化值为准回填（用户没在操作时）——迁移前
  // proxy-panel 有这段，漏搬会让「已关自动刷新」在重开后仍显示勾选。
  if (autoEl && document.activeElement !== autoEl)
    autoEl.checked = j.quota_auto !== false;
  if (autoReloginEl && document.activeElement !== autoReloginEl)
    autoReloginEl.checked = j.quota_auto_relogin !== false;

  // ---- 状态消息（操作反馈保鲜期内让位）----
  if (state === 'locked')
    msg('账号已被 SSO 锁定，已停止自动登录（每次尝试都会重置锁定计时）。'
      + '请等待 8~30 分钟或联系 itsm@hikvision.com 解锁后再手动刷新。', true);
  else if (msgHeld()) { /* 操作反馈优先，跳过本轮状态文案 */ }
  else if (state === 'error' || state === 'fetch_err')
    msg((state === 'error' ? '登录失败: ' : '查询失败: ') + (lg.msg || ''), true);
  else if (state === 'online') msg('');

  // ---- 凭据回填（用户动过的字段不回填，见 _dirty 语义）----
  if (!userEl._dirty && j.quota_username && !userEl.value) userEl.value = j.quota_username;
  if (!pwdEl._dirty && j.quota_password && !pwdEl.value) pwdEl.value = j.quota_password;

  renderLoads(els, j);

  // ---- 额度概览 ----
  const ov = j.quota_overview;
  if (!ov) {
    quotaViewEl.innerHTML = '<div class="px-hint">登录后显示额度（10 分钟自动刷新）</div>';
    return;
  }
  const tile = (u, l) => {
    u = u || 0; l = l || 0;
    const hot = l && u / l >= 0.85;
    return `<span class="px-q-tile ${hot ? 'px-q-hot' : ''}">${lzFnum(u)} / ${lzFnum(l)}</span>`;
  };
  let html = `<div class="px-q-row"><span class="px-q-k">今日外部</span>${tile(ov.externalDailyUsed, ov.externalDailyLimit)}` +
    `<span class="px-q-k">今日内部</span>${tile(ov.internalDailyUsed, ov.internalDailyLimit)}` +
    `<span class="px-q-k">请求</span><span class="px-q-tile">${lzFnum(ov.dailyRequestCount)}</span></div>`;
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
        `<span>已用 ${lzFnum(m.used)}</span><span>还剩 ${lzFnum(m.remain)}</span><span>${m.pct}%</span></div>`;
    }).join('') + '</div>';
  }
  quotaViewEl.innerHTML = html;

  // ---- 模型用量排名 ----
  const rank = j.quota_rank || [];
  if (rank.length) {
    let rhtml = '<div class="px-rank-title">模型用量排名' +
      (j.quota_ts ? `<span class="px-rank-ago">上次刷新 ${new Date(j.quota_ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })}</span>` : '') +
      '</div><div class="px-rank"><div class="px-rank-h"><span>模型</span><span>tokens</span><span>费用</span><span>积分</span><span>请求数</span></div>';
    rank.forEach(m => {
      rhtml += `<div class="px-rank-r"><span class="px-rank-m">${esc(String(m.finalModel || '?'))}</span>` +
        `<span>${lzTok(m.tokens)}</span><span>${(m.cost || 0).toFixed(2)}</span>` +
        `<span>${(m.credits || 0).toFixed(2)}</span><span>${lzFnum(m.requestCount)}</span></div>`;
    });
    rankEl.innerHTML = rhtml + '</div>';
  } else {
    rankEl.innerHTML = '';
  }
}

// ---- 模型负载面板（专栏内的常驻区块，与悬浮卡数据同源）----
export function renderLoads(els, j) {
  const { loadsEl } = els;
  if (!loadsEl) return;
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

function _renderGate(gateEl, j) {
  const sig = j.lanz_active ? 'on' : 'off|' + (j.upstream_host || '');
  if (gateEl.dataset.sig === sig) return;   // 内容没变不重写（保住选中/滚动）
  gateEl.dataset.sig = sig;
  if (j.lanz_active) { gateEl.innerHTML = ''; return; }
  gateEl.innerHTML = '<div class="px-hint" style="margin-bottom:8px;">当前上游 <code>' +
    esc(j.upstream_host || '未知') + '</code> 不是 lanzi 网关，额度/负载不可用。' +
    '登录与机器人不受影响。</div>';
}

function _lastText(conn) {
  if (!conn.quotaTs) return '上次刷新 -';
  const ago = Math.max(0, Math.round(Date.now() / 1000 - conn.quotaTs));
  const t = new Date(conn.quotaTs * 1000).toLocaleTimeString('zh-CN', { hour12: false });
  return `上次刷新 ${t} (${ago}s 前)`;
}
