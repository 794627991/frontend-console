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
  // a453（第二轮审计 P1）：必须转发第二个参数 auto。a452 给自动回切加了
  // 「不计 MRU」语义，但包装器签名只有 (portId)，`switchTab(rest, true)` 的
  // true 被这里吞掉，terminal-core 收到的 auto 是 undefined → 自动回切照样
  // 把无关 tab 顶到 MRU 最前，a452 的原现象一字未改。
  switchTab = function(portId, auto) {
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
    return _orig(portId, auto);
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
  // a444：折叠态展开按钮（标签栏右上角）跟着一起藏/显
  if (typeof window._aiPanelSyncBtn === 'function') window._aiPanelSyncBtn();
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
  // 二轮 P1-1：主 v4 store 随 tab 销毁关闭（EventSource/silentTimer 泄漏 +
  // RO force 路径曾给垂死 tab 反向新开流——readonly.exit 已加 !force 门）
  if (typeof V4Main !== 'undefined' && V4Main.close) {
    try { V4Main.close(); } catch(_) {}
  }
  _HG.conn = null; _HG.sid = null; _HG.cache = {};
  // a452（审计 P1）：关 tab 必须关掉本 tab 的弹窗。恢复会话/技能仓库/三角色
  // 等弹窗是自建 hg-modal-ov、挂 body 的，不随 wrap 移除——会盖在全窗上，
  // 误点「恢复」还会对已销毁面板发真实写请求。收口表统一 closeAll。
  // a453（第二轮审计 P2）：按**所有者**收口，不再全局清。表是全局单例，原来
  // 无条件 closeAll 会把版本面板（挂 body）正在用的确认框一起关掉，用户
  // 操作被打断。所有者由 modal.js 在创建时按「当时的活动 tab」打标。
  try {
    if (window._hgModalReg) window._hgModalReg.closeAll('harness:gui');
  } catch (_) {}
  // a672：负载悬浮卡已迁 Lanzi 专栏，harness tab 关闭不再需要清理它
  _HG.tps = null;
  _HG.ctxRing = null;   // a456：上下文圆环同属会话口径，随 tab 一起清
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
  // a453（第二轮审计 P1）：只有关的是**当前活动** tab 才自动回切。原来无条件
  // switchTab(remaining[0])——用户在编辑器/日志 tab 上乘关闭一个非活动的
  // harness tab，上下文会被强行切走（editor.js:1525 有这道门，这里缺）。
  if (remaining.length && activePortId === portId) {
    switchTab(remaining[0], true);   // a452：自动回切不计 MRU
  } else if (!remaining.length) {
    // 一个都不剩 → 空态。关的是非活动 tab 且仍有剩余时无需任何动作：
    // activePortId 仍指向一个存在的 tab（被上面的 gate 排除的正是这种情况）。
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon"><svg width="30" height="30" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="12.2" r="1.1"/><path d="M5 9.2a4.2 4.2 0 0 1 6 0"/><path d="M2.7 6.9a7.5 7.5 0 0 1 10.6 0"/></svg></div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';   // a261：信号 path 同库 signal 字形（30px 空态大图标）
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

// ---- 侧栏「机器人 / 登录」按钮：只做状态显示 + 打开 Lanzi 专栏 ----
// a672（用户定调）：机器人凭据与内网登录已整体迁到 Lanzi 专栏
// （web/js/lanzi/panel.js）。这里只保留侧栏按钮的指示灯与用户名显示——
// 点击行为由 panel.js 的捕获监听接管（直接切/开 Lanzi tab）。
// 数据源仍是 /api/lanzi/bot_status（后端 status_snapshot 原样）。
function hgBotOnline(st) { return !!(st.running && st.connected); }
function hgBotRemote(st) { return !!st.remote_running; }
function hgBotLed(st) {
  if (!st.manual) return 'hg-login-dot off';
  if (hgBotOnline(st) || hgBotRemote(st)) return 'hg-login-dot on';
  if (st.auth_failed) return 'hg-login-dot err';
  if (!st.running) return 'hg-login-dot idle';
  return 'hg-login-dot wait';
}

async function hgLoginRefresh() {
  try {
    // 带超时：worker 半死时裸 fetch 永不 settle，30s 定时器会累积 pending
    const ctl = new AbortController();
    const tid = setTimeout(() => ctl.abort(), 4000);
    let j;
    try {
      const r = await fetch('/api/lanzi/bot_status', { signal: ctl.signal });
      j = await r.json();
    } finally { clearTimeout(tid); }
    if (!j || !j.ok) return;
    document.querySelectorAll('[data-hg-login-toggle]').forEach(tg => {
      const dot = tg.querySelector('[data-hg-login-dot]');
      const txt = tg.querySelector('[data-hg-login-text]');
      if (dot) dot.className = hgBotLed(j);
      if (!txt) return;
      // 指示灯只表达机器人状态；用户名用颜色表达登录状态
      if (j.username) {
        txt.textContent = j.username;
        txt.className = 'hg-login-userlabel on';
      } else {
        txt.textContent = '未登录';
        txt.className = 'hg-login-userlabel off';
      }
    });
  } catch (_) {}
}
setInterval(hgLoginRefresh, 30000);   // 低频保活（机器人/登录态显示）
hgLoginRefresh();

// ---- Proxy 状态按钮：只显示代理运行态 + 点开代理面板 ----
// a672：模型负载悬浮卡已迁到 Lanzi 专栏（web/js/lanzi/panel.js，挂在
// Lanzi tab 上）——负载是 lanzi 网关的数据，不是代理转发的数据。

function hgProxyRefreshState() {
  const fetchIt = async () => {
    try {
      const _ac = new AbortController();
      const _to = setTimeout(() => { try { _ac.abort(); } catch(_) {} }, 8000);
      let j;
      try {
        const r = await fetch('/api/proxy/status', { signal: _ac.signal });
        j = await r.json();
      } finally { clearTimeout(_to); }
      let txt = '· 未运行', cls = ' off';
      if (j.already_running || j.running) {
        const retrying = (j.status === 'RETRY');
        txt = retrying ? '· 37349 重试中' : '· 37349 运行中';
        cls = ' on';
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

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._harnessClose = _harnessClose;
window.claudeButtonAction = claudeButtonAction;
window.hgLoginRefresh = hgLoginRefresh;
window.hgProxyRefreshState = hgProxyRefreshState;
window.setClaudeUiMode = setClaudeUiMode;
