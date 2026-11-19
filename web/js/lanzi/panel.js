// lanzi/panel.js — Lanzi 专栏宿主（a672 建栏；a673 模块化拆分）
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
// 本文件只做「宿主」：建 tab / 搭 DOM / 轮询调度 / teardown / 事件装配。
// 具体渲染与动作分在：
//   util.js       转义、数字缩写、消息区（保鲜期语义）
//   quota.js      额度 + 模型负载面板 + 非 lanzi 网关提示
//   robot.js      机器人状态灯/凭据表单/保存
//   loads-tip.js  模型负载悬浮卡（Lanzi 标签 + 侧栏机器人按钮两处悬停）
//
// 接口：/api/lanzi/*（status|login|logout|refresh|relogin|auto|auto_relogin
//       |sso_probe|bot_status|bot_activate|bot_credentials）
'use strict';

import { mkMsgArea } from './util.js';
import { renderQuota } from './quota.js';
import { createRobotUI } from './robot.js';
import { bindHover, hide as hideLoadsTip } from './loads-tip.js';

const LANZI_ID = 'lanzi:main';
const POLL_MS = 3000;

export function buildLanziTab() {
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

  const els = {
    msgEl: wrap.querySelector('[data-lz-msg]'),
    statusEl: wrap.querySelector('[data-lz-status]'),
    lastEl: wrap.querySelector('[data-lz-last]'),
    userEl: wrap.querySelector('[data-lz-user]'),
    pwdEl: wrap.querySelector('[data-lz-pwd]'),
    gateEl: wrap.querySelector('[data-lz-gate]'),
    quotaViewEl: wrap.querySelector('[data-lz-quota-view]'),
    rankEl: wrap.querySelector('[data-lz-quota-rank]'),
    loadsEl: wrap.querySelector('[data-lz-loads]'),
    botDotEl: wrap.querySelector('[data-lz-bot-dot]'),
    botStateEl: wrap.querySelector('[data-lz-bot-state]'),
    botBadgeEl: wrap.querySelector('[data-lz-bot-badge]'),
    botIdEl: wrap.querySelector('[data-lz-bot-id]'),
    botSecEl: wrap.querySelector('[data-lz-bot-secret]'),
    botSaveBtn: wrap.querySelector('[data-lz-bot-save]'),
    activeEl: wrap.querySelector('[data-lz-active]'),
  };
  const { msgEl, userEl, pwdEl, activeEl } = els;
  const autoEl = wrap.querySelector('[data-lz-auto]');
  const autoReloginEl = wrap.querySelector('[data-lz-autologin]');

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
  window._lzConn = conn;   // 侧栏按钮跳转复用

  const { msg, msgKeep, msgHeld } = mkMsgArea(msgEl);

  // ---- 轮询：每拍拿 status + bot_status 分发给渲染器 ----
  async function poll() {
    try {
      const j1 = await fetch('/api/lanzi/status').then(r => r.json()).catch(() => null);
      if (!j1 || !j1.ok) return;
      renderQuota(els, j1, {
        conn, userEl, pwdEl, autoEl, autoReloginEl, msg, msgHeld,
      });
      activeEl.textContent = '上游：' + (j1.upstream_host || '-');

      const j2 = await fetch('/api/lanzi/bot_status').then(r => r.json()).catch(() => null);
      // j2 失败时**不渲染**：会清空「上一次已知的 manual/app_id」，
      // 导致「Secret 留空沿用旧值」被误拦（后端实际支持）
      if (j2 && j2.ok) robotUI.render(j2, j1);
    } catch (_) {}
  }

  function startPoll() {
    if (conn.pollTimer) return;
    poll();
    conn.pollTimer = setInterval(() => {
      if (wrap.style.display === 'none') { stopPoll(); return; }
      poll();
    }, POLL_MS);
  }
  function stopPoll() {
    if (conn.pollTimer) { clearInterval(conn.pollTimer); conn.pollTimer = null; }
  }
  // switchTab 切回时由 terminal-core 调（kind==='lanzi' 分支）
  conn.onResumePoll = startPoll;

  // ---- 机器人（状态灯 + 凭据表单）----
  const robotUI = createRobotUI(els, { msgKeep, onChanged: poll });

  // ---- 登录/登出/刷新/重登/探测 ----
  userEl.addEventListener('input', () => { userEl._dirty = true; });
  pwdEl.addEventListener('input', () => { pwdEl._dirty = true; });

  // 眼睛切换（密码/密钥各一）：点击切换 input type
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

  wrap.querySelector('[data-lz-save]').onclick = async () => {
    const u = userEl.value.trim(), p = pwdEl.value;
    if (!u || !p) { msgKeep('用户名/密码不能为空', true); return; }
    msgKeep('正在登录…');
    try {
      const j = await fetch('/api/lanzi/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p })
      }).then(r => r.json());
      // 只在输入框仍是本次提交内容时清 dirty（在途期间用户改过就不清）
      if (j.ok) {
        if (userEl.value.trim() === u) userEl._dirty = false;
        if (pwdEl.value === p) pwdEl._dirty = false;
      }
      msgKeep(j.msg || (j.ok ? '已保存，开始登录' : '登录失败'), !j.ok);
      poll();
    } catch (e) { msgKeep('请求失败: ' + e, true); }
  };

  wrap.querySelector('[data-lz-logout]').onclick = async () => {
    try {
      const j = await fetch('/api/lanzi/logout', { method: 'POST' }).then(r => r.json());
      userEl.value = ''; pwdEl.value = '';
      userEl._dirty = false; pwdEl._dirty = false;
      conn.quotaTs = 0;
      msgKeep(j.msg || '已断开登录', !j.ok);
      poll();
    } catch (e) { msgKeep('请求失败: ' + e, true); }
  };

  wrap.querySelector('[data-lz-refresh]').onclick = async () => {
    try {
      const j = await fetch('/api/lanzi/refresh', { method: 'POST' }).then(r => r.json());
      msgKeep(j.msg || (j.ok ? '已触发刷新' : '刷新失败'), !j.ok);
      setTimeout(poll, 1200);
    } catch (e) { msgKeep('请求失败: ' + e, true); }
  };

  wrap.querySelector('[data-lz-relogin]').onclick = async () => {
    // 强制重登：丢旧 session 换新 client 全新登录。只动额度登录态。
    if (!(await _ddConfirm('强制重登',
      '丢弃当前登录会话，用保存的凭据重新登录拉取额度？\n（代理转发不受任何影响，只刷新额度登录状态）'))) return;
    try {
      const j = await fetch('/api/lanzi/relogin', { method: 'POST' }).then(r => r.json());
      msgKeep(j.msg || (j.ok ? '已触发强制重登' : '触发失败'), !j.ok);
      setTimeout(poll, 1500);
    } catch (e) { msgKeep('请求失败: ' + e, true); }
  };

  wrap.querySelector('[data-lz-probe]').onclick = async () => {
    // 匿名探测：不提交任何凭据，不会重置 SSO 锁定计时
    msgKeep('正在匿名探测 SSO 状态…');
    try {
      const j = await fetch('/api/lanzi/sso_probe').then(r => r.json());
      if (!j.ok) { msgKeep('探测失败: ' + (j.error || ''), true); return; }
      if (j.locked === true) msgKeep('SSO 判定：锁定中 — ' + (j.hint || ''), true);
      else if (j.locked === false) msgKeep('SSO 判定：未锁定 — ' + (j.hint || ''));
      else msgKeep('SSO 无法判定 — ' + (j.hint || ''));
    } catch (e) { msgKeep('探测失败: ' + e, true); }
  };

  // 两个独立开关（后端是真相源，勾选态由 renderQuota 回填）
  autoEl.onchange = async (e) => {
    try {
      const j = await fetch('/api/lanzi/auto', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto: e.target.checked })
      }).then(r => r.json());
      msgKeep(j.msg || '', !j.ok);
    } catch (err) { e.target.checked = !e.target.checked; msgKeep('请求失败: ' + err, true); }
  };
  autoReloginEl.onchange = async (e) => {
    try {
      const j = await fetch('/api/lanzi/auto_relogin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_relogin: e.target.checked })
      }).then(r => r.json());
      msgKeep(j.msg || '', !j.ok);
    } catch (err) { e.target.checked = !e.target.checked; msgKeep('请求失败: ' + err, true); }
  };

  // ---- 收尾钩子（editor.js 的 _edCloseNow 按 kind==='lanzi' 调用）----
  window._lzTeardown = function () {
    try { stopPoll(); } catch (_) {}
    try { hideLoadsTip(); } catch (_) {}
    if (window._lzConn === conn) window._lzConn = null;
  };

  startPoll();
  switchTab(LANZI_ID);
  if (typeof refreshSidebar === 'function') refreshSidebar();
  return conn;
}

// 悬浮卡的两处悬停委托（模块级挂一次即可；tab 关闭重开天然跟随 DOM）
bindHover();

// 侧栏「机器人」按钮点击 → 打开本 tab（用户定调：不再弹浮层）。
// 用 capture 抢占 harness 侧任何冒泡监听。
document.addEventListener('click', (ev) => {
  const tg = ev.target && ev.target.closest
    ? ev.target.closest('[data-hg-login-toggle]') : null;
  if (!tg) return;
  ev.preventDefault();
  ev.stopPropagation();
  if (window._lzConn && document.contains(window._lzConn.wrap)) {
    switchTab(LANZI_ID);
  } else {
    buildLanziTab();
  }
}, true);

// 经典脚本/其他模块按 window.buildLanziTab 调用（panel.js 自身解析时尚未
// 走 export，故两处都挂）
window.buildLanziTab = buildLanziTab;
