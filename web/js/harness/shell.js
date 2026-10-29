// harness 外壳(v3.0 自 claude-harness.js 顶层段原样搬移)

// ---- 关闭 tab ----
// ==================== v2.24 大会话 DOM 卸载（拖动卡顿根治）====================
// 现象链（用户对照实验定位）：harness 开大会话 → 所有拖动（文件拖入/命令库
// 排序/tab 换位，HTML5 与 OLE 两套机制）全卡 ~12s；空会话不卡；关 tab 恢复；
// /exit 杀进程仍卡；停 ctx/vision 轮询仍卡 → 元凶是大会话消息流的巨大 DOM
// （数千条消息/数万节点，display:none 仍占内存并拖累渲染进程 GC）。
// 修复：切走 harness tab 时把 flow innerHTML 快照到内存并清空 DOM，切回
// 恢复。busy 时不卸载（后台流式 append 依赖 flow 在场，快照覆盖会丢消息）。
;(function _hgFlowUnloadInit() {
  const _orig = switchTab;
  switchTab = function(portId) {
    // isHg/wasHg 必须在 try 块外声明（const 块级作用域——曾定义在 try 内、
    // 块外引用，每次切 tab 必抛 ReferenceError 且真正的切换动作永远不执行，
    // v2.31 未浏览器实测漏网：用户实锤「Claude 对话没反应/打开 settings 失败」）
    const isHg = portId === 'harness:gui';
    const wasHg = activePortId === 'harness:gui';
    try {
      if (wasHg && !isHg && !_HG.busy && _HG.flowEl && _HG.flowEl.innerHTML) {
        _HG.flowSnap = _HG.flowEl.innerHTML;
        _HG.flowEl.innerHTML = '';
      } else if (isHg && !wasHg && _HG.flowSnap && _HG.flowEl) {
        _HG.flowEl.innerHTML = _HG.flowSnap;
        _HG.flowSnap = '';
        _HG.flowEl.scrollTop = _HG.flowEl.scrollHeight;
        // v3.4.67：本路写入意图=回底，但 wrap 仍 display:none 时 scrollTop
        // 写入是 no-op 不触发 scroll 事件→粘底标志不会经事件回灌，显式置真
        // （轻审实锤的脱钩拽底变体）
        _HG.stickBtm = true;
      }
    } catch(_) {}
    // v2.31：harness tab 激活时右侧「终端助手」面板整体隐藏（v3.3 起会话
    // 动态在 harness 内部分屏——旧换装形态废止，面板对 harness 零用处）
    if (isHg !== wasHg) _hgPanelMode(isHg);
    return _orig(portId);
  };
})();

// ---- v3.3 右侧面板隐藏开关（顶层定义：switchTab 包装器与 _harnessClose
// 都在闭包外调用它；只依赖 index.html 静态节点 #aiPanel，无闭包状态）----
// 旧 _hgPanelMode 是「换装」（hg-mode 藏页签+改标题为会话动态）；会话动态
// 迁入分屏伪 tab 后换装废止——harness tab 激活期间面板整体 display:none，
// 切走/关 tab 即恢复原样（标题从未被改，折叠态由 aiToggle 自持不受影响）。
function _hgPanelMode(on) {
  const p = document.getElementById('aiPanel');
  if (!p) return;
  p.classList.toggle('hg-hide', !!on);
}

function _harnessClose(portId) {
  const _hgConn = connections[portId];
  if (!_hgConn) return;
  // v3.5.51（designer P0-7）：只读模式中关 tab——清 readonly/roViewSid 僵尸态
  //（否则重开 tab 后 setBusy 守卫永久早退）+ 拆 RO 层（force=濒死不 rebuild）
  if (_HG.readonly) {
    _HG.readonly = null; _HG.roViewSid = null;
    try { window.HgRO && window.HgRO.exit(true); } catch(_) {}
  }
  _HG.conn = null; _HG.sid = null; _HG.cache = {};
  _HG.rowById = {}; _HG.run = null;   // 批4：subRows/subBlk 段档随段退役删除
  // v2.15：补齐残留态复位。旧实现只清了上面这几个，重开 tab 后 dirty/busy/
  // activity 等沿用上一轮的值——dirty 漏复位会与「点 chip 删会话」叠加，
  // 重开后第一次点模型 chip 就可能删掉一条会话。tab 即将销毁，这里只需清
  // 状态，不用走 setBusy 更新界面。
  _HG.dirty = false; _HG.busy = false;
  _HG.initN = 0; _HG.agentModels = null;   // v2.35：init 计数/模型缓存随 tab 销毁（重开 tab 重新拉）
  _HG.dyn = null; _HG.todos = null; _HG.agents = null;   // v2.32：面板派生态随 tab 销毁
  // v2.46R（P5 测试挖出的潜伏 bug）：phStopTimer 是闭包私有函数，顶层
  // _harnessClose 引用它 → 组在场（回合进行中）关 tab 必抛 ReferenceError，
  // close 中途夭折：tab/wrap 不摘、connections 残留 → 再点按钮走「已存在即
  // switchTab」早退，留下 SSE 已死的僵尸 tab。改为内联同款清理（clearInterval
  // + 置空），不依赖闭包名
  if (_HG.grp && _HG.grp.phTimer) {
    try { clearInterval(_HG.grp.phTimer); } catch(_) {}
    _HG.grp.phTimer = null;
  }
  _HG.grp = null; _HG.activity = null;   // v2.18：组级抽屉（旧 drawer 单例已删）
  // v3.2R1(P2)：回合秒表随 tab 销毁全收（_turnHeadStop 是闭包私有，inline 同款清理）
  (_HG.turnTicks || []).forEach(t => { try { clearInterval(t); } catch(_) {} });
  _HG.turnTicks = [];
  _HG.think = null; _HG.noScroll = false; _HG.openState = null;
  _HG.skills = null; _HG.models = null;   // 技能/模型映射下次进 tab 重新拉
  // v3.3R（全审 P1/P2）：分屏窗格档随 tab 销毁全清（_subReset 全局函数）——
  // 旧只靠切会话/SSE reset 路径顺带清；关 tab 直接销毁时 _sub.tabs/dynEl 残留
  // 游离 DOM，重开 tab 若无历史会话自动 switchTo（全新用户/列表拉取失败）就
  // 没有自愈入口，胶囊点击会被 stale 档案短路开出空分屏（__dyn__/__dir__ 同款）
  try { _subReset(); } catch(_) {}
  _hgConn.tab.remove();
  _hgConn.wrap.remove();
  delete connections[portId];
  _hgPanelMode(false);   // v2.31：关 harness tab 还原右侧工具面板（剩余 tab 的 switchTab 会再兜一次）
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
  });
  if (remaining.length) switchTab(remaining[0]);
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon">📡</div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();
}

// ---- 顶栏 Claude 按钮分派 ----
let _claudeUiMode = null;
async function _getClaudeUiMode() {
  if (_claudeUiMode === null) {
    try {
      const j = await (await fetch('/api/theme')).json();
      _claudeUiMode = (j.ok && j.claude_ui_mode) ? j.claude_ui_mode : 'harness';
    } catch(_) { _claudeUiMode = 'harness'; }
  }
  return _claudeUiMode;
}
function setClaudeUiMode(m) { _claudeUiMode = m; }

async function claudeButtonAction() {
  const mode = await _getClaudeUiMode();
  if (mode === 'cli') connectClaude();
  else buildClaudeHarnessTab({});
}

// ---- 统一登录胶囊（侧栏底部）：代理/额度/机器人一次登录全通 ----
// 登录走共用接口 /api/proxy/credentials（单一事实源 lanz_credentials.json）；
// 凭据就位后端自动激活机器人（幂等），登出自动停用。未登录机器人不激活。
// 胶囊点击 → 冒泡弹窗（未登录=登录表单；已登录=状态+登出确认）。
function hgLoginRender(st) {
  document.querySelectorAll('[data-hg-login-toggle]').forEach(tg => {
    const dot = tg.querySelector('[data-hg-login-dot]');
    const txt = tg.querySelector('[data-hg-login-text]');
    if (!txt) return;
    if (st.username) {
      if (dot) { dot.className = 'hg-login-dot on'; }
      txt.textContent = st.username + ' 已登录';
    } else {
      if (dot) { dot.className = 'hg-login-dot off'; }
      txt.textContent = '未登录 · 机器人未激活';
    }
  });
  document.querySelectorAll('[data-hg-login-pop]').forEach(pop => {
    const off = pop.querySelector('[data-hg-login-off]');
    const on = pop.querySelector('[data-hg-login-on]');
    if (!off || !on) return;
    if (st.username) {
      off.style.display = 'none'; on.style.display = '';
      const name = pop.querySelector('[data-hg-login-name]');
      if (name) name.textContent = st.username + ' 已登录';
      const bot = pop.querySelector('[data-hg-login-bot]');
      if (bot) bot.textContent = st.running
        ? (st.connected ? '机器人：在线' : '机器人：连接中…') : '机器人：未运行';
    } else {
      off.style.display = ''; on.style.display = 'none';
    }
  });
}
function hgLoginTogglePop(force) {
  document.querySelectorAll('[data-hg-login-pop]').forEach(pop => {
    pop.style.display = (force !== undefined ? force
      : pop.style.display === 'none') ? '' : 'none';
  });
}
async function hgLoginRefresh() {
  try {
    const r = await fetch('/api/hiklink/status');
    const j = await r.json();
    if (j && j.ok) hgLoginRender(j);
  } catch (_) {}
}
document.addEventListener('click', async ev => {
  // 冒泡弹窗开合：点胶囊切换；点弹窗内部不关；点其他区域关闭
  const toggle = ev.target.closest('[data-hg-login-toggle]');
  if (toggle) { hgLoginTogglePop(); return; }
  if (!ev.target.closest('[data-hg-login-pop]')) hgLoginTogglePop(false);
  const loginBtn = ev.target.closest('[data-hg-login-btn]');
  if (loginBtn) {
    const pop = loginBtn.closest('[data-hg-login-pop]');
    const uEl = pop.querySelector('[data-hg-login-user]');
    const pEl = pop.querySelector('[data-hg-login-pwd]');
    const u = (uEl.value || '').trim(), p = pEl.value || '';
    if (!u || !p) { (u ? pEl : uEl).focus(); return; }
    loginBtn.disabled = true; const old = loginBtn.textContent;
    loginBtn.textContent = '登录中…';
    try {
      const r = await fetch('/api/proxy/credentials', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', username: u, password: p }) });
      const sj = await r.json().catch(() => ({}));
      // v2.2.2：写盘失败如实报错——旧版静默吞 + 乐观渲染「已登录」，
      // 凭据实际没落盘，重启就得重登（同事机实锤）
      if (!sj.ok) { showBanner(sj.msg || '登录保存失败', 4000, true); return; }
      // 凭据就位后端已自动激活；再显式触发一次（幂等），并即时回显登录态
      await fetch('/api/hiklink/activate', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
      hgLoginRender({ username: u, running: true, connected: false });
      pEl.value = '';
      setTimeout(hgLoginRefresh, 1500);
    } catch (_) {}
    loginBtn.disabled = false; loginBtn.textContent = old;
    return;
  }
  const outBtn = ev.target.closest('[data-hg-logout-btn]');
  if (outBtn) {
    try { await fetch('/api/proxy/credentials', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"action":"clear"}' }); } catch (_) {}
    hgLoginRefresh();
  }
});
setInterval(hgLoginRefresh, 30000);   // 低频保活（登录态/机器人在线显示）
hgLoginRefresh();

// ---- Proxy 状态按钮（输入卡上方，原顶部按钮迁入）：显示运行态+端口，点击开代理面板 ----
function hgProxyRefreshState() {
  const fetchIt = async () => {
    try {
      const r = await fetch('/api/proxy/status');
      const j = await r.json();
      let txt = '· 未运行', cls = ' off';
      if (j.already_running || j.running) {
        txt = '· 37349 运行中';
        cls = ' on';
        if (j.running && j.snapshot && j.snapshot.in_flight_retries > 0) txt += '（重试中）';
      } else if (j.port_busy) {
        txt = '· 端口被占'; cls = ' err';
      }
      document.querySelectorAll('[data-hg-proxy-state]').forEach(el => {
        el.textContent = txt;
        el.className = 'hg-proxy-state' + cls;
      });
    } catch (_) {}
  };
  fetchIt();
}
document.addEventListener('click', ev => {
  const btn = ev.target.closest('[data-hg-proxy-btn]');
  if (btn && typeof buildProxyTab === 'function') buildProxyTab();
});
// 事件通知（不轮询）：后端在代理状态变化点广播 SSE 信号，前端收到即拉一次
// status 同步显示。连接断开时 EventSource 自动重连；首屏状态由页面加载时
// 的 hgProxyRefreshState() 拉取。
try {
  const hgProxyES = new EventSource('/api/proxy/events');
  hgProxyES.onmessage = () => hgProxyRefreshState();
} catch (_) {}
hgProxyRefreshState();

// v3.5.243（开发期缓存穿透坑提醒）：页面 JS 的 ?v= 由后端长驻进程注入，
// 后端不重启则 URL 不变→浏览器命中旧缓存（用户刷新/重启页面均无效）。
// 加载时实时对比：页面注入版本 vs 后端当前版本，不一致提示重启工具。
(function () {
  try {
    var pageVer = (window._HG_VER || '').replace('v', '');
    if (!pageVer) return;
    fetch('/api/harness/version').then(r => r.json()).then(j => {
      var live = (j && j.harness) || '';
      if (live && pageVer !== live) {
        showBanner('工具内核已更新（页面 ' + pageVer + ' → 后端 ' + live
          + '）——请完全重启工具生效', 8000, true);
      }
    }).catch(() => {});
  } catch (_) {}
})();
