// AI 浏览器（2026-11-24 用户需求：AI 用 CDP 操作网页时，页面显示在 AI 会话右侧
// 分屏，用户看着 AI 操作——而不是无头模式看不见、或 AI 直接操作工具界面）。
// 用户拍板四项：会话右侧分屏 / devtools_* 默认目标=AI 浏览器（显式 target=app
// 才操作工具界面）/ 光标+点击涟漪+状态条 / AI 操作时自动展开，收起后仍可后台
// 运行和截图。形态参考 ZCode Browser Use（内嵌 <webview> + 右侧分屏）。
//
// 形态：分屏里的「AI 浏览器」伪 tab 只是一块**占位框**；真正的 <webview> 常驻在
// 一个挂 body 的固定定位「舞台」里。展开时舞台对齐占位框；收起（窗格关 / 切到
// 别的分屏 tab / harness tab 不激活）时舞台转后台态——近乎透明、固定 1280×800、
// 不吃鼠标。为什么不把 webview 直接放分屏里：
//   ① webview 节点在 DOM 里一搬家，guest 就销毁重建（页面状态全丢）；
//   ② 窗格 display:none / harness wrap 隐藏时 guest 不可见，实测这种状态下
//      Page.captureScreenshot 挂死不返回；近乎透明的后台态截图正常（ZCode 同款手法）。
//
// 数据流（对端：后端 src/ai_browser.py、壳 electron/main.js 的 AI 浏览器段）：
//   后端 ─ui_action: ai_browser_open→ open()：切到 AI 会话页、展开分屏、建舞台；
//   webview dom-ready → fcShell.aiBrowserAttach(wcId) → 壳取 CDP targetId 报后端登记；
//   后端每步操作 ─ui_action: ai_browser_op→ op()：光标 / 涟漪 / 状态条。
// 用户可随时接管：舞台前台态就是普通网页视图，不加输入锁（与 ZCode 一致）。
//
// 对抗审计（2026-11-24，三判官）后的修正，均在相应位置标注：
//   · open() 不再把会话记成「想让分屏开着」（那是用户动作才记的，见 a638）；
//   · op() 到达时舞台不在就先 open()（展开请求可能丢在 SSE 断线期间）；
//   · 拖分屏分隔条期间舞台不吃鼠标（guest 内的事件不冒泡到主窗口文档）；
//   · 转后台态时让网页视图失焦；网页渲染进程崩溃时自动重载并回到「未连接」；
//   · 后台态下长时间没有 AI 操作就拆掉舞台（释放网页渲染进程）。

const AIBR_TID = '__aibr__';
// 与 electron/main.js（AIBR_PARTITION）、src/ai_browser.py（PARTITION）三处对齐
const AIBR_PARTITION = 'persist:fc-ai-browser';
const AIBR_IDLE = '等待 AI 操作';
const AIBR_IDLE_MS = 5000;      // 这么久没有新操作：状态条回空闲、光标淡出
// 后台态下这么久没有 AI 操作就拆舞台：网页渲染进程常驻不便宜（页面里的视频、
// 音频、定时器都会继续跑），而用户既没在看、AI 也没在用。前台态（用户正看着）
// 不拆。数值挂在 window.AI_BR.reapMs 上，隔离验证时可调小
const AIBR_REAP_MS = 10 * 60 * 1000;

const _S = {
  pane: null, slot: null, stage: null, wv: null, fx: null, cursor: null,
  urlEl: null, badgeEl: null, statusEl: null, busyT: 0, reapT: 0,
  front: false, attached: false, attBusy: false, crashed: false,
  ro: null, roObs: null, queued: false,
};

function _ico(name) { return (typeof ICO16 !== 'undefined' && ICO16[name]) || ''; }

// ---- 舞台：常驻 body 的 <webview>（只建一次，不在 DOM 里搬家）----
function _ensureStage() {
  if (_S.stage && _S.stage.isConnected) return;
  const stage = document.createElement('div');
  stage.className = 'hg-aibr-stage hg-aibr-bg';      // 生于后台态：对齐之后再转前台
  const wv = document.createElement('webview');
  wv.setAttribute('partition', AIBR_PARTITION);
  // allowpopups 必须存在（空值即可）：window.open 请求才能到主进程 handler——
  // 壳凭分区名把它改道回本视图（web-panel.js 同款注意点）
  wv.setAttribute('allowpopups', '');
  wv.setAttribute('src', 'about:blank');
  // display 不能写 block：Electron 45 实测 guest 视口高度会钉死 150（web-panel.js）
  wv.style.cssText = 'border:0;display:flex;background:var(--bg-deep,#14161c);';
  const fx = document.createElement('div');
  fx.className = 'hg-aibr-fx';
  const cursor = document.createElement('div');
  cursor.className = 'hg-aibr-cursor';
  fx.appendChild(cursor);
  stage.appendChild(wv);
  stage.appendChild(fx);
  document.body.appendChild(stage);
  _S.stage = stage; _S.wv = wv; _S.fx = fx; _S.cursor = cursor;
  _S.attached = false;
  _S.crashed = false;
  _wire(wv);
  // 舞台可能是回收后重建的，面板与占位框还在：把尺寸观察重新挂上，否则舞台
  // 不再跟随占位框（对抗复审实锤——回收时断开了观察器，再打开时面板没重建，
  // 观察器也就没恢复）
  _observeSlot();
}

function _wire(wv) {
  // 取 webContentsId 必须等 dom-ready（did-attach 里取会抛错——实测）；
  // dom-ready 每次页面加载都会来，_attach 自带去重
  wv.addEventListener('dom-ready', () => {
    _S.crashed = false;        // 页面加载成功 = 上次崩溃已经救回来了：下次还能再自动重载一次
    _attach(false);
  });
  wv.addEventListener('did-navigate', (e) => _url(e.url));
  wv.addEventListener('did-navigate-in-page', (e) => _url(e.url));
  wv.addEventListener('page-title-updated', (e) => {
    if (_S.urlEl) _S.urlEl.title = e.title || '';
  });
  wv.addEventListener('did-start-loading', () => { if (_S.pane) _S.pane.classList.add('loading'); });
  wv.addEventListener('did-stop-loading', () => { if (_S.pane) _S.pane.classList.remove('loading'); });
  wv.addEventListener('did-fail-load', (e) => {
    // -3 = ABORTED（导航被打断，正常现象，不算失败）
    if (e.isMainFrame && e.errorCode !== -3) _status('加载失败：' + (e.errorDescription || ('错误 ' + e.errorCode)), false);
  });
  wv.addEventListener('render-process-gone', (e) => {
    // 网页渲染进程崩溃：壳与后端的登记指向的已是死页。回到「未连接」（下次
    // dom-ready 重新登记），自动重载一次——只一次，免得坏页面把崩溃循环下去
    _S.attached = false;
    _paintBadge();
    _status('网页视图已崩溃' + (e && e.reason ? '（' + e.reason + '）' : ''), false);
    if (_S.crashed) return;
    _S.crashed = true;
    setTimeout(() => { try { wv.reload(); } catch (_) {} }, 300);
  });
  if (window.fcShell && typeof window.fcShell.onAiBrowserOpenUrl === 'function') {
    window.fcShell.onAiBrowserOpenUrl((u) => { try { wv.loadURL(u); } catch (_) {} });
  }
}

async function _attach(force) {
  if (_S.attBusy || (_S.attached && !force)) return;
  if (!(window.fcShell && typeof window.fcShell.aiBrowserAttach === 'function')) return;
  _S.attBusy = true;
  try {
    const r = await window.fcShell.aiBrowserAttach(_S.wv.getWebContentsId());
    // 只认壳明确回的 ok：壳在后端没确认登记时也会回失败，这里不能再默认成功
    _S.attached = !!(r && r.ok === true);
    if (!_S.attached) console.warn('[ai-browser] 视图登记失败：', (r && r.err) || r);
  } catch (e) {
    _S.attached = false;
  } finally {
    _S.attBusy = false;
    _paintBadge();
  }
}

function _paintBadge() {
  if (!_S.badgeEl) return;
  _S.badgeEl.textContent = _S.attached ? 'AI 已连接' : 'AI 未连接';
  _S.badgeEl.classList.toggle('on', _S.attached);
}

function _wvUrl() {
  // getURL 与 getWebContentsId 一样：webview 必须已挂上并发出 dom-ready 才能调，
  // 舞台刚建那一刻调会抛错（端到端实锤：open() 因此中断，窗格没展开）
  try { return _S.wv ? _S.wv.getURL() : 'about:blank'; } catch (_) { return 'about:blank'; }
}

// 占位框尺寸一变（拖分隔条 / 窗格开合 / 切 tab / 窗口缩放）就重新对齐舞台。
// 面板还在、舞台却换过了（回收后重建）的情况也要能重新挂上——所以做成
// 「保证在盯着当前占位框」的幂等操作，而不是只在建面板时挂一次
function _observeSlot() {
  if (!(_S.slot && typeof ResizeObserver !== 'undefined')) return;
  if (_S.ro && _S.roObs === _S.slot) return;          // 已经在盯着它
  if (_S.ro) { try { _S.ro.disconnect(); } catch (_) {} }
  _S.ro = new ResizeObserver(_queueSync);
  _S.ro.observe(_S.slot);
  _S.roObs = _S.slot;
}

// ---- 面板：分屏里的伪 tab（占位框 + 工具栏 + 状态条）----
function _ensurePane() {
  const sub = window._sub;
  const body = document.querySelector('[data-hg-subbody]');
  if (!sub || !body) return false;                  // AI 会话页不在
  const old = sub.tabs[AIBR_TID];
  if (old && old.sc && old.sc.isConnected) {
    _S.pane = old.sc;
    _S.slot = old.sc.querySelector('[data-aibr-slot]');
    _S.urlEl = old.sc.querySelector('[data-aibr-url]');
    _S.badgeEl = old.sc.querySelector('[data-aibr-badge]');
    _S.statusEl = old.sc.querySelector('[data-aibr-status]');
    _paintBadge();
    _observeSlot();          // 面板没重建，但舞台可能被回收后换过了
    return true;
  }
  // 重建（AI 会话页重开 / 切会话清场后，面板 DOM 已被清掉；舞台不受影响）
  const sc = document.createElement('div');
  sc.className = 'hg-sub-msgs hg-aibr-pane';
  sc.dataset.tid = AIBR_TID;
  sc.innerHTML =
    '<div class="hg-aibr-bar">' +
      '<button class="hg-aibr-btn" data-aibr="back" title="后退">' + _ico('back') + '</button>' +
      '<button class="hg-aibr-btn" data-aibr="fwd" title="前进">' + _ico('forward') + '</button>' +
      '<button class="hg-aibr-btn" data-aibr="reload" title="重新加载">' + _ico('refresh') + '</button>' +
      '<span class="hg-aibr-url" data-aibr-url>about:blank</span>' +
      '<span class="hg-aibr-badge" data-aibr-badge title="前端控制台壳是否已把这个网页视图登记给后端">AI 未连接</span>' +
    '</div>' +
    '<div class="hg-aibr-slot" data-aibr-slot></div>' +
    '<div class="hg-aibr-status"><span class="hg-aibr-dot"></span><span data-aibr-status>' + AIBR_IDLE + '</span></div>';
  sub.tabs[AIBR_TID] = { label: 'AI 浏览器', type: '__aibr__', desc: 'AI 正在操作的网页（可直接接管点击输入）',
    sc, run: false, err: false, replay: false, model: '', _userOpened: true };
  if (sub.order.indexOf(AIBR_TID) < 0) sub.order.push(AIBR_TID);
  body.appendChild(sc);
  // 不夺焦的 tab 必须显式隐藏（subpane._subDynEnsure 同款教训：漏设会与激活
  // tab 平分 body 高度）
  if (sub.active !== AIBR_TID) sc.style.display = 'none';
  _S.pane = sc;
  _S.slot = sc.querySelector('[data-aibr-slot]');
  _S.urlEl = sc.querySelector('[data-aibr-url]');
  _S.badgeEl = sc.querySelector('[data-aibr-badge]');
  _S.statusEl = sc.querySelector('[data-aibr-status]');
  sc.querySelector('[data-aibr="back"]').onclick = () => { try { _S.wv.goBack(); } catch (_) {} };
  sc.querySelector('[data-aibr="fwd"]').onclick = () => { try { _S.wv.goForward(); } catch (_) {} };
  sc.querySelector('[data-aibr="reload"]').onclick = () => { try { _S.wv.reload(); } catch (_) {} };
  _paintBadge();
  _url(_wvUrl());
  try { window._subTabsPaint(); } catch (_) {}
  _observeSlot();
  // 面板可能被别人整个移除（用户点 tab 上的 ✕、切会话清场、被逐出）：占位框
  // 一脱离 DOM，ResizeObserver 就不再报告——舞台会以不透明、吃鼠标的前台态
  // 留在原地，盖住分屏里此刻显示的内容（端到端实锤）。所以再盯一层「分屏
  // body 的直接子节点增删」，任何变化都重新对齐一次
  if (!body._aibrMo && typeof MutationObserver !== 'undefined') {
    body._aibrMo = new MutationObserver(_queueSync);
    body._aibrMo.observe(body, { childList: true });
  }
  return true;
}

function open() {
  if (!(window.fcShell && typeof window.fcShell.aiBrowserAttach === 'function')) return;   // 非壳形态
  // 上次网页视图崩溃后自动重载没能救回来（crashed 没被 dom-ready 复位）：节点还在
  // 但已是死的，_ensureStage 见节点在就不重建——先拆掉，给 AI 一个新视图
  if (_S.stage && _S.crashed) _teardownStage();
  _ensureStage();
  // 用户拍板：AI 一开始操作就自动展开。没停在 AI 会话页就切过去（没有就建）
  if (typeof window.buildClaudeHarnessTab === 'function') {
    try { window.buildClaudeHarnessTab({}); } catch (_) {}
  }
  // 逐步兜底：面板创建失败不能连累后面的展开与同步（调用方 sense.js 的 SSE
  // 回调有总兜底的 try/catch，这里抛出去只会被静默吞掉，什么都看不见）
  let hasPane = false;
  try { hasPane = _ensurePane(); } catch (e) { console.warn('[ai-browser] 面板创建失败', e); }
  if (!hasPane && !(window._sub && window._sub.tabs)) return;
  try {
    // 第二个参数是「用户动作」标记：AI 自动展开不是用户动作，不能把会话记成
    // 「想让分屏开着」——那会让用户亲手关掉的分屏在切回会话时自己弹出来
    // （subpane._subShow 的 userIntent / a638 的用户关闭意图优先）
    window._subShow(AIBR_TID, false);
    window._sub.manual = true;      // AI 在用：回合终结不自动收起（subpane._subEnd）
    window._subActivate(AIBR_TID);
  } catch (e) { console.warn('[ai-browser] 展开分屏失败', e); }
  _attach(true);                    // 后端重启过登记表时会再要一次：重新登记是幂等的
  _queueSync();
}

// ---- 舞台对齐：前台 = 跟随占位框；后台 = 近乎透明、固定尺寸、不吃鼠标 ----
function _queueSync() {
  if (_S.queued) return;
  _S.queued = true;
  requestAnimationFrame(_sync);
}

function _sync() {
  _S.queued = false;
  const stage = _S.stage;
  if (!stage) return;
  const slot = _S.slot;
  const r = (slot && slot.isConnected) ? slot.getBoundingClientRect() : null;
  const front = !!(r && r.width > 20 && r.height > 20);
  if (front) {
    if (!_S.front) {
      stage.className = 'hg-aibr-stage hg-aibr-front';
      _S.front = true;
      _touchReap();                  // 回到前台：用户正看着，停掉回收计时
    }
    const w = Math.round(r.width), h = Math.round(r.height);
    stage.style.left = Math.round(r.left) + 'px';
    stage.style.top = Math.round(r.top) + 'px';
    stage.style.width = w + 'px';
    stage.style.height = h + 'px';
    if (_S.wv) { _S.wv.style.width = w + 'px'; _S.wv.style.height = h + 'px'; }
  } else if (_S.front) {
    stage.className = 'hg-aibr-stage hg-aibr-bg';
    stage.style.left = stage.style.top = stage.style.width = stage.style.height = '';
    if (_S.wv) { _S.wv.style.width = ''; _S.wv.style.height = ''; }
    _S.front = false;
    // 网页里的输入框可能还握着键盘焦点：收起后按键不该继续打进网页
    try { _S.wv.blur(); } catch (_) {}
    // 「后台态下多久没有 AI 操作」从转后台的这一刻起算。只在状态转换时起计时、
    // 不在每次 _sync 里续命：_sync 的触发源包括全应用任意一次界面过渡，那样
    // 等于应用在用就永远不回收（对抗复审实锤）
    _touchReap();
  }
}
window.addEventListener('resize', _queueSync);
// 窗口从最小化 / 被遮挡恢复可见时重新对齐：不可见期间 requestAnimationFrame
// 不执行，期间排队的对齐要靠这一下补上（可见性恢复后 rAF 也会补跑，双保险）
document.addEventListener('visibilitychange', _queueSync);
// 占位框「位置变、尺寸不变」的平移（布局过渡结束时）不算尺寸变化，
// ResizeObserver 不会报——过渡结束补一次对齐
document.addEventListener('transitionend', _queueSync, true);

// ---- 空闲回收：后台态下长时间没有 AI 操作就拆舞台 ----
// 计时只在三处重置：op()（AI 的每一步操作）、open()、以及「前台态转后台态」的
// 那一刻。别的地方不要续命（见 _sync 里的说明）
function _touchReap() {
  if (_S.reapT) { clearTimeout(_S.reapT); _S.reapT = 0; }
  if (!_S.stage || _S.front) return;         // 前台态：用户正看着，不回收
  const ms = (window.AI_BR && window.AI_BR.reapMs) || AIBR_REAP_MS;
  _S.reapT = setTimeout(_reapStage, ms);
}

function _reapStage() {
  _S.reapT = 0;
  if (!_S.stage || _S.front) return;         // 到期时用户正看着：不拆
  _teardownStage('网页视图已回收（长时间没有操作），下次操作时重新打开');
}

function _teardownStage(statusText) {
  if (_S.reapT) { clearTimeout(_S.reapT); _S.reapT = 0; }
  if (_S.ro) { try { _S.ro.disconnect(); } catch (_) {} }
  _S.ro = null;
  _S.roObs = null;
  const st = _S.stage;
  _S.stage = _S.wv = _S.fx = _S.cursor = null;
  _S.attached = false;
  _S.front = false;
  if (st && st.parentNode) st.parentNode.removeChild(st);
  // guest 销毁 → 壳通知后端清登记；下次 AI 操作 open() 重建（网页回到空白页）
  _paintBadge();
  _status(statusText, false);
}

// ---- 拖分屏分隔条期间舞台不吃鼠标 ----
// guest 内的鼠标事件不冒泡到主窗口文档：鼠标一旦划进网页区域，分隔条就收不到
// mousemove / mouseup——拖拽卡在那一刻，松手也收不到。分隔条自身只有 5px 宽，
// 窗格宽度还有 .25s 过渡，从宽往窄拖时鼠标很容易跑到它前面去
document.addEventListener('mousedown', (e) => {
  if (!_S.stage || !e.target || !e.target.closest) return;
  if (e.target.closest('[data-hg-subres]')) _S.stage.classList.add('hg-aibr-drag');
}, true);
function _dragShieldOff() {
  if (_S.stage) _S.stage.classList.remove('hg-aibr-drag');
}
window.addEventListener('mouseup', _dragShieldOff, true);
window.addEventListener('blur', _dragShieldOff);

// ---- 操作指示：光标 / 点击涟漪 / 状态条 ----
function _shortUrl(u) {
  const s = String(u || '');
  const bare = s.replace(/^https?:\/\//i, '').replace(/^www\./i, '');
  return bare.length > 80 ? bare.slice(0, 80) + '…' : bare;
}

function _status(text, busy) {
  if (_S.statusEl) _S.statusEl.textContent = text;
  if (_S.pane) _S.pane.classList.toggle('busy', !!busy);
  if (_S.busyT) clearTimeout(_S.busyT);
  _S.busyT = 0;
  if (busy) {
    _S.busyT = setTimeout(() => {
      _S.busyT = 0;
      if (_S.statusEl) _S.statusEl.textContent = AIBR_IDLE;
      if (_S.pane) _S.pane.classList.remove('busy');
      if (_S.cursor) _S.cursor.classList.remove('on');
    }, AIBR_IDLE_MS);
  }
}

function _url(u) {
  if (_S.urlEl) {
    _S.urlEl.textContent = _shortUrl(u) || 'about:blank';
    _S.urlEl.title = u || '';
  }
}

function _ripple(x, y) {
  if (!_S.fx) return;
  const el = document.createElement('div');
  el.className = 'hg-aibr-ripple';
  el.style.left = x + 'px';
  el.style.top = y + 'px';
  _S.fx.appendChild(el);
  setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, 700);
}

function op(d) {
  if (!d) return;
  // 展开请求可能丢在 SSE 断线期间：指示帧来了、舞台却不在，就自己展开
  if (!_S.stage) open();
  if (!_S.stage) return;
  try { _ensurePane(); } catch (e) { console.warn('[ai-browser] 面板创建失败', e); }   // 面板可能被清场（切会话）
  const x = Number(d.x), y = Number(d.y);
  if (d.x != null && d.y != null && isFinite(x) && isFinite(y)) {
    // 光标先平滑移过去：后端发完这条 0.3s 后才发真实鼠标事件（看得见「移过去、再点」）
    _S.cursor.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    _S.cursor.classList.add('on');
    if (d.op === 'click') _ripple(x, y);
  }
  const label = d.label || '', text = d.text || '';
  let msg = '';
  if (d.op === 'navigate') {
      msg = /^(重新加载|后退|前进)$/.test(text) ? '正在' + text + '…'
        : '正在打开 ' + _shortUrl(text) + '…';
  } else if (d.op === 'click') msg = '点击 ' + label;
  else if (d.op === 'type') msg = '向 ' + label + ' 输入：' + text;
  else if (d.op === 'press') msg = '按键 ' + text;
  else if (d.op === 'eval') msg = '执行脚本：' + text;
  else if (d.op === 'dom') msg = '查找元素 ' + text;
  else if (d.op === 'screenshot') msg = '截图' + text;
  else if (d.op === 'wait') msg = '等待 ' + text;
  else if (d.op === 'console') msg = '读取控制台';
  else if (d.op === 'network') msg = '查看网络请求' + (text ? '：' + text : '');
  else if (d.op === 'download') msg = text;   // 下载：后端给的是整句（开始 / 完成 / 取消 / 失败）
  _status(msg || '操作中…', true);
  _queueSync();          // 面板可能是刚重建的：立刻对齐一次，不等观察器报
  _touchReap();
}

// 调试 / 验证用快照（不暴露内部对象）
function state() {
  const r = _S.slot && _S.slot.isConnected ? _S.slot.getBoundingClientRect() : null;
  return {
    stage: !!(_S.stage && _S.stage.isConnected),
    front: _S.front, attached: _S.attached, crashed: _S.crashed,
    ro: !!(_S.ro && _S.roObs === _S.slot),     // 尺寸观察器在盯着占位框（舞台跟随的前提）
    pane: !!(_S.pane && _S.pane.isConnected),
    active: (window._sub && window._sub.active) || null,
    slot: r ? [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] : null,
    url: _wvUrl(),
  };
}

window.AI_BR = { open, op, state, reapMs: AIBR_REAP_MS };
