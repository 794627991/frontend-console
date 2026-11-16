// ============================================================
// 网页 tab（a544 终局形态，用户令「最终形态」）——WebView2 真浏览器控件
//
// 架构：每个网页 tab = 一个完整的 WebView2 浏览器控件实例（Python 侧
// src/web_tabs.py 管理，与 Edge 标签页同级）——XFO/CSP/document.domain/
// 防盗链/返回栈等 iframe+代理时代的一切限制结构性消失。本文件只保留
// 工具栏 UI 与命令转发（REST /api/web/tabs），控件本体在工具窗口内
// 与本面板的 web-body 区域像素级对齐（布局经 rect 上报）。
//
// 地址栏/返回/前进 = 控件原生（SourceChanged/HistoryChanged 事件经
// ExecuteScriptAsync 回推：__webTabUrl/__webTabHist/__webTabTitle）。
// 新窗口（target=_blank/window.open）= NewWindowRequested → __webTabNew
// → 本面板内导航（不弹系统浏览器）。
//
// 保留功能：阅读模式（fetch_text）/「发给 Claude」/收藏/会话恢复/
// 站点缩放（阅读态）。iframe 时代的代理/软过渡/逃逸检测全部退役
//（用户令「没用全删」）。
// ============================================================
// a554 多开：每个网页 tab 独立 portId（web:1 web:2 …）+ 独立导航栈/面板态
// （挂 conn._nav/_ui）。R1 审计 W11：WEB_PORTID 死常量已删（全仓无代码
// 引用）；_webCur() 返回当前激活的网页 tab；__newWindow/收藏 → 新 tab。
let _webSeq = 0;                           // 面板序号（portId 与控件 tab id 同源）
// R4 审计 D1（W3）：页面纪元——刷新后 _webSeq 归零也不再与后端幸存控件
// 撞名（W3-②/B14 同解）；随机后缀杜绝同毫秒双页面碰撞
const _webPageEpoch = (Date.now() % 1e8) + '-' + Math.random().toString(36).slice(2, 6);
// R4 审计 D3=a（用户拍板：不做多客户端）——单 UI 收紧：localStorage 心跳
// 仲裁，先到者得主（6s 心跳 / 2s 周期）；非主 UI 客户端禁止网页 tab 操作
(function () {
  const KEY = 'web-ui-owner';
  const TOKEN = Math.random().toString(36).slice(2) + '-' + Date.now();
  let owner = false;
  function claim() {
    try {
      const cur = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!cur || (Date.now() - cur.ts) > 6000 || cur.token === TOKEN) {
        localStorage.setItem(KEY, JSON.stringify({ token: TOKEN, ts: Date.now() }));
        owner = true;
      }
    } catch (_) { owner = true; }
  }
  claim();
  setInterval(function () {
    if (owner) { try { localStorage.setItem(KEY, JSON.stringify({ token: TOKEN, ts: Date.now() })); } catch (_) {} }
    else claim();
  }, 2000);
  window.__webUiIsOwner = function () { return owner; };
})();
// R4 审计 D1（W3）：页面卸载（刷新/关闭）→ 按纪元回收本页网页控件 + 后端
// 会话水位归零。全模式生效（debug 整 UI 刷新同样要回收网页控件）；后端
// 按 epoch 只动本页创建的 tab，刷新后新纪元控件不被迟到的 beacon 误杀。
window.addEventListener('pagehide', function () {
  // R9 审计 W40：非 owner 页面卸载不得触发全局回收/会话重置（否则副窗
  // 关闭会把 owner 的 seq 水位/显隐意图打掉）。owner 卸载时 owner 恒真，
  // 自身回收不受影响。
  if (window.__webUiIsOwner && !window.__webUiIsOwner()) return;
  try {
    navigator.sendBeacon('/api/web/tabs',
      JSON.stringify({ act: 'dispose_all', epoch: _webPageEpoch }));
  } catch (_) {}
});
let _webActivePid = null;                  // 当前激活的网页 tab portId
let _webCtlSeq = 0;                        // a556：show 命令序号（乱序丢弃，见 _webCtlVisible）
const _WEB_SLEEP_MIN = 10;                 // a475：切走 N 分钟后休眠（分钟）

function _mkNav() { return { stack: [], idx: -1 }; }
function _mkUi() { return { sleeping: false, reader: false, zoom: 1, rseq: 0 }; }

// a475 会话恢复：启动时读上次栈（重开网页 tab 无显式 URL 时回到上次页）
let _webSavedNav = null;                   // a554：恢复用（首开时消费）
try {
  const _saved = JSON.parse(localStorage.getItem('web-session') || 'null');
  if (_saved && Array.isArray(_saved.stack)) {
    // a556：过滤脏 about:blank（修复前的休眠会把它写进栈）
    _webSavedNav = {
      stack: _saved.stack.filter(x => typeof x === 'string'
        && x !== 'about:blank').slice(0, 50),
      idx: -1 };
    _webSavedNav.idx = _webSavedNav.stack.length
      ? Math.min(Math.max(0, _saved.idx | 0), _webSavedNav.stack.length - 1) : -1;
  }
} catch (_) {}
let _webSessSrvReady = false;   // a565：种子完成前不上传（防空态覆盖服务端）
function _webSessionSave() {
  const c = _webCur();
  const nav = c && c._nav;
  try { localStorage.setItem('web-session', JSON.stringify(
    nav || { stack: [], idx: -1 })); } catch (_) {}
  // a565：跨启动持久化——localStorage 按 origin（含随机端口）隔离，
  // 每次重启端口必变 = 「恢复上次网页」从未真正生效。服务端 config
  // 通道（与 web_favs/tftp_pane_h 同款）。owner 门 + 去抖防连发
  if (_webSessSrvReady && !(window.__webUiIsOwner && !window.__webUiIsOwner())) {
    clearTimeout(_webSessionSave._t);
    _webSessionSave._t = setTimeout(() => {
      try {
        const n = nav || { stack: [], idx: -1 };
        fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ web_session: {
            stack: n.stack.filter(x => typeof x === 'string'
              && x !== 'about:blank').slice(0, 50), idx: n.idx | 0 } })
        }).catch(() => {});
      } catch (_) {}
    }, 1500);   // a565 审计：1500ms 去抖——SPA 页内跳转也触发保存，防 config 写放大
  }
}
// a565 启动种子：新 origin 的 localStorage 必空 → 从服务端回填（favs 同款：
// 本地有值本地为准并回传对齐；迟到种子不覆盖已恢复/已导航的状态）
(function () {
  fetch('/api/theme').then(r => r.json()).then(j => {
    _webSessSrvReady = true;
    const srv = (j && typeof j.web_session === 'object' && j.web_session)
      ? j.web_session : null;
    if (!srv || !Array.isArray(srv.stack) || !srv.stack.length) return;
    let cur = null;
    try { cur = JSON.parse(localStorage.getItem('web-session') || 'null'); } catch (_) {}
    const curOk = !!(cur && Array.isArray(cur.stack) && cur.stack.length);
    if (_webSavedNav) return;   // 已从本地恢复/已开 tab 导航过——绝不覆盖
    if (!curOk) {
      // 新端口场景：服务端种子（含 about:blank 过滤与 idx 钳制，同 a556）
      _webSavedNav = {
        stack: srv.stack.filter(x => typeof x === 'string'
          && x !== 'about:blank').slice(0, 50),
        idx: -1 };
      _webSavedNav.idx = _webSavedNav.stack.length
        ? Math.min(Math.max(0, srv.idx | 0), _webSavedNav.stack.length - 1) : -1;
      try { localStorage.setItem('web-session', JSON.stringify(_webSavedNav)); } catch (_) {}
    } else if (JSON.stringify(cur) !== JSON.stringify(srv)) {
      // a565 审计：兑现注释——本地为准，差异回传对齐（favs 同款），同
      // origin 重开时服务端不再滞后到下次导航
      try {
        fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ web_session: cur }) }).catch(() => {});
      } catch (_) {}
    }
  }).catch(() => { _webSessSrvReady = true; });
})();
// a475 睡眠巡检：网页 tab 不在前台累计计时（60s 一查，开销可忽略），
// 到时置空 iframe（进程回收由 Chromium 完成）；前台/休眠态即停
setInterval(() => {
  // a554 多开：每个隐藏的网页 tab 独立计时休眠
  for (const pid in connections) {
    const c = connections[pid];
    if (!c || !c.meta || c.meta.kind !== 'web' || !c._ui) continue;
    if (c._ui.sleeping || c._ui.reader) continue;
    if (c.wrap.style.display === 'none' && document.visibilityState === 'visible') {
      c._hidSec = (c._hidSec || 0) + 60;
      if (c._hidSec >= _WEB_SLEEP_MIN * 60) _webSleep(c);
    } else {
      c._hidSec = 0;
    }
  }
}, 60000);

function _webFavs() {
  // R3 审计 B13：非数组/元素缺 url 的畸形历史值原先原样返回 → 上层
  // .map/.splice 抛错，收藏功能整体静默失效且永不自愈。校验 + 回写自愈。
  try {
    const v = JSON.parse(localStorage.getItem('web-favs') || '[]');
    if (!Array.isArray(v)) { _webFavsSave([]); return []; }
    const ok = v.filter(x => x && typeof x === 'object' && typeof x.url === 'string');
    if (ok.length !== v.length) _webFavsSave(ok);
    return ok;
  } catch (_) { try { _webFavsSave([]); } catch (_e) {} return []; }
}
let _webFavsSrvReady = false;   // 启动种子完成前不上传（防本地空态覆盖服务端）
function _webFavsSave(v) {
  const arr = v.slice(0, 100);
  try { localStorage.setItem('web-favs', JSON.stringify(arr)); } catch (_) {}
  // R-命名统一·跨启动持久化：localStorage 按 origin（含随机端口）隔离，
  // 每次重启端口必变 = 收藏必丢（用户实锤）。服务端 config.json 通道
  // （与 sidebar_w / calc_history 同款兼职）。owner 门 + 去抖防连发。
  if (_webFavsSrvReady && !(window.__webUiIsOwner && !window.__webUiIsOwner())) {
    clearTimeout(_webFavsSave._t);
    _webFavsSave._t = setTimeout(() => {
      try {
        fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ web_favs: _webFavs().slice(0, 100) }) }).catch(() => {});
      } catch (_) {}
    }, 400);
  }
}
// 启动种子：新 origin 的 localStorage 必空 → 从服务端回填；本地已有
// （种子完成前用户抢先收藏）→ 本地优先 + 差异回写。完成后才允许上传。
(function () {
  fetch('/api/theme').then(r => r.json()).then(j => {
    const srv = Array.isArray(j.web_favs) ? j.web_favs.filter(
      x => x && typeof x.url === 'string') : [];
    let cur = [];
    try { cur = JSON.parse(localStorage.getItem('web-favs') || '[]'); } catch (_) {}
    if (!Array.isArray(cur)) cur = [];
    const merged = (cur.length ? cur : srv).slice(0, 100);
    try { localStorage.setItem('web-favs', JSON.stringify(merged)); } catch (_) {}
    if (JSON.stringify(merged) !== JSON.stringify(srv)) {
      try {
        fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ web_favs: merged }) }).catch(() => {});
      } catch (_) {}
    }
    _webFavsSrvReady = true;
  }).catch(() => { _webFavsSrvReady = true; });
})();
function _webShortUrl(u) {
  try {
    const x = new URL(u);
    return (x.host + x.pathname).replace(/\/$/, '') + (x.search || '');
  } catch (_) { return u; }
}
function _webNormUrl(s) {
  s = String(s || '').trim();
  if (!s) return '';
  // R2/R3 审计 W16（A10''）：file:/javascript:/data:/vbscript: 显式拦截
  //（返回 '' 由调用方给可见反馈）；已知 scheme 原样放行；localhost:8080
  // 这类「形似 scheme」的主机:端口 仍走补全。
  if (/^(file|javascript|data|vbscript):/i.test(s)) return '';
  if (/^(https?|about|mailto|ftp|ws|wss):/i.test(s)) return s;
  return 'http://' + s;    // 内网多为 http 裸主机名——缺省补 http
}
// a556：栈顶取值（跳过脏 about:blank——修复前旧会话可能已把休眠产生的
// about:blank 存进 web-session，唤醒/恢复不能落在它上面）
function _webNavTop(c) {
  while (c._nav.idx >= 0 && c._nav.stack[c._nav.idx] === 'about:blank')
    c._nav.idx--;
  return c._nav.idx >= 0 ? c._nav.stack[c._nav.idx] : '';
}

function buildWebPanelTab(url, opts) {
  // R4 审计 D3=a：非主 UI 客户端禁止开网页 tab（心跳仲裁见文件头）
  if (window.__webUiIsOwner && !window.__webUiIsOwner()) {
    showBanner('网页 tab 仅限主窗口使用（检测到第二个 UI 客户端）', 4000, true);
    return null;
  }
  const newTab = !!(opts && opts.newTab);
  // 无 newTab 且已有网页 tab：聚焦 + 当前 tab 导航（顶栏输入语义）
  // a555 审计修：原取「第一个创建的」web tab——用户停在 web:2 时顶栏回车
  // 会被拽到 web:1。浏览器语义=当前激活 tab（无激活回落第一个）
  const cur = _webCur();
  let pid = cur ? cur.portId : null;
  if (pid && !newTab) {
    switchTab(pid);
    if (url) _webNavigate(url);
    return connections[pid];
  }
  // a554 多开 + R4 审计 D1（W3）：tab id 加页面纪元——刷新后 _webSeq 归零
  // 也不再与后端幸存控件撞名（B14 多客户端撞名同解）
  const portId = 'web:' + _webPageEpoch + ':' + (++_webSeq);
  const ctlId = 'web-' + _webPageEpoch + '-' + _webSeq;
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${ICO16.link}</span>` +
    `<span class="label">网页</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    // R9.8：关闭钮已 SVG 化（ICO16.x 内嵌 path）——点击 target 是 svg/path
    // 而非 .close 本身，classList.contains 判不中（用户实锤关闭失效）。
    // closest 沿树上溯，文本字形与内嵌 SVG 双兼容
    if (e.target.closest('.close')) { e.stopPropagation(); closeEditorTab(portId); return; }
    switchTab(portId);
  };
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="web-pane">
      <div class="web-bar">
        <button class="btn ghost icon-btn" data-web="back" title="后退（基于本面板导航记录）">◀</button>
        <button class="btn ghost icon-btn" data-web="fwd" title="前进">▶</button>
        <button class="btn ghost icon-btn" data-web="reload" title="重载">⟳</button>
        <input class="web-url" data-web-input spellcheck="false" autocomplete="off"
               placeholder="输入网址，回车打开">
        <button class="btn ghost icon-btn" data-web="star" title="收藏 / 取消收藏当前页">${ICO16.star}</button>
        <button class="btn ghost icon-btn" data-web="pw" title="密码管理：查看 / 显示 / 删除已保存的站点密码">${ICO16.key}</button>
        <button class="btn ghost" data-web="read" title="阅读模式：文本视图（零脚本执行、可选可搜；拒嵌站点也能读）">${ICO16.book} 阅读</button>
        <button class="btn ghost" data-web="claude" title="取本页正文填入 Claude 输入框——需登录态的页面请让 AI 用 devtools 工具读">发给 Claude</button>
        <button class="btn ghost" data-web="sys" title="X-Frame-Options 拒嵌等场景：系统浏览器打开">${ICO16.openExt} 浏览器</button>
      </div>
      <div class="web-body" data-web-body>
        <!-- a544：WebView2 控件宿主区（控件由 Python 叠放其上，像素对齐） -->
        <div class="web-frame web-host"></div>
        <div class="web-reader" data-web-reader style="display:none;"></div>
        <div class="web-sleep" data-web-sleep style="display:none;">
          <div>${ICO16.hourglass} 已休眠以省内存（后台超过 10 分钟）<br><span class="web-sleep-sub">正在唤醒…</span></div>
        </div>
        <div class="web-err" data-web-err style="display:none;">
          <div class="web-err-title"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5l6 10.5H2z"/><path d="M8 6.5v3.2M8 11.4v.1"/></svg> 页面加载异常</div>
          <div class="web-err-msg">可能是网络不可达（内网无外联？）或网站拒绝被嵌入。</div>
          <div class="web-err-acts">
            <button class="btn" data-web-err="read">${ICO16.book} 用阅读模式打开</button>
            <button class="btn ghost" data-web-err="sys">${ICO16.openExt} 在系统浏览器中打开</button>
            <button class="btn ghost" data-web-err="dismiss">继续等待</button>
          </div>
        </div>
      </div>
    </div>`;
  termArea.appendChild(wrap);
  const conn = { portId, meta: { kind: 'web', label: '网页' }, tab, wrap,
                  _nav: _mkNav(), _ui: _mkUi(), _tabId: ctlId };
  connections[portId] = conn;

  const $w = (s) => wrap.querySelector(s);
  _webCtlSetup(conn);                      // a544：控件创建 + 布局跟随
  const urlInput = $w('[data-web-input]');
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      const u = _webNormUrl(urlInput.value);
      if (!u) {
        // R3 审计 W23/A10''：非空输入被 _webNormUrl 拦成 ''（file:/javascript:
        // 等）= 非法协议，给可见反馈；真空输入才静默返回
        if (urlInput.value.trim()) showBanner('该协议不允许在内嵌浏览器打开', 2500, true);
        return;
      }
      // a554 多开：回车=当前 tab 导航；Ctrl+回车=开新网页 tab
      // R2 审计 B1（A8）：导航目标=本 tab（conn），非激活 tab
      if (e.ctrlKey) buildWebPanelTab(u, { newTab: true });
      else _webNavigate(u, conn);
    }
  });
  wrap.querySelectorAll('[data-web]').forEach(b => b.onclick = () => _webAct(b.dataset.web, wrap));
  // a488：加载失败提示层按钮
  const errLayer = wrap.querySelector('[data-web-err]');
  if (errLayer) {
    errLayer.addEventListener('click', (e) => {
      const b = e.target.closest('[data-web-err]');
      if (!b || b === errLayer) return;
      const act = b.dataset.webErr;
      errLayer.style.display = 'none';
      if (act === 'read') _webAct('read');
      else if (act === 'sys') _webAct('sys');
      // dismiss：继续等待（层收起，iframe 继续加载）
    });
  }
  // a475 站点缩放记忆（审计修·降级如实）：DOM 事件不冒泡出 iframe——网页
  // 视图下 iframe 全覆盖容器，此监听只在**阅读态**（reader div 在上层）可达。
  // 网页视图缩放需 CDP（Emulation.setPageScaleFactor），待 CDP 普开后接入；
  // iframe 内 Ctrl+滚轮会触发 Chromium 内建整页缩放（缩放整个工具 UI）——
  // 已知行为，可与阅读缩放并存。按 host 记忆，Ctrl+0 复位
  const body = wrap.querySelector('[data-web-body]');
  body.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const c2 = connections[wrap.dataset.portId] || _webCur();   // R8 审计 B23：事件属于本 wrap
    const url = (c2 && c2._nav.stack[c2._nav.idx]) || '';
    const host = (() => { try { return new URL(url).host; } catch (_) { return ''; } })();
    let z = (c2 && c2._ui && c2._ui.zoom) || 1;   // a555：原读 c2._zoom 字段错位
    z = Math.min(2, Math.max(0.5, z * (e.deltaY < 0 ? 1.1 : 0.9)));
    _webApplyZoom(z, host, c2);
  }, { passive: false });
  wrap.addEventListener('keydown', (e) => {
    if (e.ctrlKey && (e.key === '0' || e.key === 'Num0')) {
      e.preventDefault();
      const cz = connections[wrap.dataset.portId] || _webCur();   // R8 审计 B23
      const url = (cz && cz._nav.stack[cz._nav.idx]) || '';
      const host = (() => { try { return new URL(url).host; } catch (_) { return ''; } })();
      _webApplyZoom(1, host, cz);
    }
  });

  switchTab(portId);
  refreshSidebar();
  if (url) {
    _webNavigate(url);
  } else if (_webSavedNav && _webSavedNav.idx >= 0
             && _webSavedNav.stack[_webSavedNav.idx]) {
    // a475 会话恢复（a554 改为一次性消费）：无显式 URL 的首开回到上次页。
    // a565 审计（启用器发现）：恢复目标=stack[idx]（用户上次实际所在，
    // 可能停在后退中途）而非栈顶——a565 之前 localStorage 跨启动必空，
    // 这条路径从未真正执行过，旧的「回栈顶」语义随持久化修通首次暴露
    conn._nav = _webSavedNav;
    _webSavedNav = null;
    const _k = conn._nav.idx;
    // a555 审计修：_webNavigate 会再 push（恢复后首次后退成空转）——
    // idx 先退一位，push 后恰好回到 _k
    conn._nav.idx = _k - 1;
    _webNavigate(conn._nav.stack[_k], conn);
  }
  return conn;
}

function _webCur() {
  // a554 多开：当前激活的网页 tab（无激活时回落第一个网页 tab）
  const a = connections[_webActivePid];
  if (a && a.meta && a.meta.kind === 'web') return a;
  for (const p in connections) {
    const c = connections[p];
    if (c && c.meta && c.meta.kind === 'web') return c;
  }
  return null;
}
// ============ a544：WebView2 控件命令层（终局形态） ============
// 控件 REST 调用（src/web_tabs.py 的 /api/web/tabs）——a554：带 conn
// （每个网页 tab 独立控件 id，挂 conn._tabId）
function _webCtl(conn, d) {
  // a555 审计修：conn 空时原兜底 'web-1' 会操纵 1 号控件（打错 tab）
  if (!conn || !conn._tabId) return Promise.resolve({ ok: false });
  // R4 审计 D3=a：非主 UI 客户端禁止一切网页 tab 后端操作（单点收口）
  if (window.__webUiIsOwner && !window.__webUiIsOwner()) {
    return Promise.resolve({ ok: false, err: "second-ui-client" });
  }
  d.tab = conn._tabId;
  return fetch('/api/web/tabs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(d)
  }).then(r => r.json()).catch(() => ({ ok: false }));
}

// 面板创建：控件 create + 布局跟随（ResizeObserver 持续上报 rect，
// 物理像素 = DIP × devicePixelRatio——WinForms Bounds 是物理像素）
function _webCtlSetup(conn) {
  const body = conn.wrap.querySelector('[data-web-body]');
  const host = conn.wrap.querySelector('.web-host');
  const push = () => {
    if (conn.wrap.style.display === 'none') return;   // 隐藏时不布局
    const r = host.getBoundingClientRect();
    const sx = window.devicePixelRatio || 1;
    const sy = sx;   // WinForms 同一 DPI
    _webCtl(conn, { act: 'layout', x: r.left * sx, y: r.top * sy,
                    w: r.width * sx, h: r.height * sy });
  };
  conn._ctlResize = new ResizeObserver(push);
  conn._ctlResize.observe(host);
  window.addEventListener('resize', push);
  conn._ctlPush = push;
  push();
}

// tab 显示状态联动（switchTab 钩不到——用 display 探针 + 显式调用）
function _webCtlVisible(on, all, target) {
  const c = target || _webCur();   // R8 审计 B22：可指定目标（后台 tab 阅读进出）
  if (!c || !c._tabId) return;
  c._ctlShown = all ? false : !!on;   // R-外泄根治：本地镜像（推演免抖动）
  // a556：带序号——show:true/false 是两个独立 fetch，浏览器多连接下到达
  // Python 的顺序无保证；乱序时后发的隐藏被先发的显示覆盖 → 控件压在
  // 其他 tab 上（用户实锤「网页没进抽屉」）。Python 侧按 seq 丢弃迟到旧令
  const d = { act: 'show', on: !!on, sq: ++_webCtlSeq, epoch: _webPageEpoch };
  if (all) d.all = true;   // R6 审计 W32：全隐语义（后端 _want=(HIDE_ALL,False)）
  // RB4：epoch 随行——新页面首个 show 让后端重置 seq 水位（防刷新死 UI）
  _webCtl(c, d);
  if (on && c._ctlPush) setTimeout(c._ctlPush, 30);   // 显示后重对齐
}

// ---- R-外泄根治（家族第 11 次修复=断根）：可见性单一权威推演 ----
// 家族史（a551/a553/a555×2/a556/W3/W31/W32/W22/B22/用户截图第 11 例）反复
// 复发的根因：可见性由 ~10 处代码各自「下令」，每处只检查自己知道的状态，
// 任何新路径（抽屉/悬浮胶囊/关闭回切……）忘发命令 = HWND 外泄（DOM 永远
// 遮不住原生控件）。本函数把「下令」改为「推演」：从全局状态推导每个
// 控件应有的可见性并只对**变化**下发——任何路径只需触发它，不可能漏状态。
function _webReconcileVis() {
  let target = null;
  // R9.3 收紧：双真值——wrap 在屏（switchTab 落点）∧ 激活 tab 恰为它
  // （activePortId）。单靠 onScreen 会在「激活非网页 tab + 某网页 wrap
  // display 残留 flex」（抽屉/悬浮残留形态，用户实锤第 11 例）时漏藏；
  // activePortId 未定义（启动首帧）时回落 onScreen 单真值。
  const _a = (typeof activePortId !== 'undefined') ? connections[activePortId] : null;
  const actWeb = (_a && _a.meta && _a.meta.kind === 'web') ? _a : null;
  for (const pid in connections) {
    const c = connections[pid];
    if (!c || !c.meta || c.meta.kind !== 'web' || !c._tabId) continue;
    const onScreen = c.wrap && c.wrap.style.display !== 'none';
    const want = onScreen && (!_a || actWeb === c)
      && !c._ui.reader && !c._ui.sleeping
      && !(window.__webOverlayOpen && window.__webOverlayOpen());
    if (want) { target = c; break; }   // 屏上至多一个 wrap，命中即唯一
  }
  // R9.6·反冻结自愈：若顶层激活 tab 就是网页、且它在屏/非阅读/非休眠/
  // 无浮层——按不变式它必须可见。推演循环却没选中它 = 某个连结项被陈旧
  // 状态（残留 flex/中间态）污染 → 信任屏幕真值强改为它（静默自愈；
  // 2s 周期推演持续兜底，异常形态仅体现为偶见控件闪一下）。
  if (!target) {
    const aw = (typeof activePortId !== 'undefined') ? connections[activePortId] : null;
    const awOK = aw && aw.meta && aw.meta.kind === 'web' && aw.wrap
      && aw.wrap.style.display !== 'none' && !aw._ui.reader && !aw._ui.sleeping
      && !(window.__webOverlayOpen && window.__webOverlayOpen());
    if (awOK) {
      target = aw;   // R9.6·反冻结自愈：信任屏幕真值（静默，不打扰）
    }
  }
  if (!target) {
    // 无应可见控件：正被看到的那个走「静止帧」（suspend=抓帧→隐藏→回推，
    // 用户接受静止不接受白屏）；其余零散可见（不应存在）走全隐兜底
    const shown = Object.values(connections).filter(
      c => c && c.meta && c.meta.kind === 'web' && c._ctlShown === true);
    if (shown.length === 1) {
      const sc = shown[0];
      _webCtl(shown[0], { act: 'suspend' });
      shown[0]._ctlShown = false;
      return;
    }
    // R9.14：不再依赖镜像判断「是否有变化」——每次全隐都真实下发
    //（幂等）。镜像免发建立在「前后端一致」假设上，后端 BeginInvoke
    // 乱序/吞指令会使假设失效 → 冻结死锁（用户实证：手发 show 即恢复）
    _webCtlVisible(false, true);
    for (const pid in connections) {
      const c = connections[pid];
      if (c && c.meta && c.meta.kind === 'web') c._ctlShown = false;
    }
    return;
  }
  for (const pid in connections) {
    const c = connections[pid];
    if (!c || !c.meta || c.meta.kind !== 'web' || !c._tabId || c === target) continue;
    if (c._ctlShown === true) {
      _webCtl(c, { act: 'suspend' });   // 静止帧：抓帧→隐藏→回推
      c._ctlShown = false;
    } else if (c._ctlShown !== false) {
      _webCtlVisible(false, false, c);   // 只发变化
    }
  }
  // R9.14：目标显示每次真实下发（幂等）——不依赖镜像判断。静止帧
  // 不清除：活页面（HWND）就位后背景被盖住无碍，下次隐藏瞬间旧帧立即
  // 可见（迟到帧也比暗底强），新帧到达即覆盖
  _webCtlVisible(true, false, target);
}
// 兜底钩子：任何代码路径（含本文件未知的抽屉/悬浮/第三方）只要翻动
// web wrap 的 display，0 推演延迟内必被捕获——「不可能漏路径」的保证。
(function () {
  let pend = false;
  const onStyleMut = () => {   // R9.3 修复：回调必须是函数（此前误传
    if (pend) return;          // MutationObserver 实例 → 每 3s TypeError，
    pend = true;               // 兜底观察器从未挂上=外泄兜底失效）
    setTimeout(() => { pend = false; _webReconcileVis(); }, 0);
  };
  const arm = () => {
    for (const pid in connections) {
      const c = connections[pid];
      if (c && c.meta && c.meta.kind === 'web' && c.wrap && !c._visMo) {
        c._visMo = new MutationObserver(onStyleMut);
        c._visMo.observe(c.wrap, { attributes: true, attributeFilter: ['style'] });
      }
    }
  };
  arm();
  setInterval(arm, 3000);   // 新建 web tab 补挂（create 后此处自然覆盖）
})();
// R9.6·反冻结兜底：任何一次推演算错/漏触发（概率态）最多存活 2 秒——
// 周期重推演；镜像一致时零网络请求，成本可忽略
setInterval(function () {
  try {
    if (Object.values(connections).some(
        c => c && c.meta && c.meta.kind === 'web')) _webReconcileVis();
  } catch (_) {}
}, 2000);

// Python 控件事件回推（ExecuteScriptAsync 调入）
function _webByTabId(tid) {
  for (const p in connections) {
    const c = connections[p];
    if (c && c._tabId === tid) return c;
  }
  return null;
}
window.__webTabUrl = function (tid, url) {
  // a555 审计修：去掉 || _webCur() 兜底——已 dispose 控件的迟到事件会
  // 串进无关 tab 改它的地址栏/导航栈；tid 查无即丢弃
  const c = _webByTabId(tid);
  if (!c) return;
  // a556（用户实锤：后台 tab 一段时间变 about:blank 且唤醒不恢复）：
  // 休眠/阅读模式会把控件导航到 about:blank——该事件若入栈，about:blank
  // 成为栈顶（还会存进 web-session），唤醒时「恢复」的就是 about:blank。
  // 原生 about:blank 只可能来自内部释放，一律忽略（顺带清未消费的
  // back/fwd 对账标记，防跨事件残留）
  if (!url || url === 'about:blank') { c._navSrc = null; return; }
  // R4 审计 W29（D8）：restore 消费——GoBack 回到的就是栈顶本尊，不动栈
  //（内部 about:blank 不再新进历史条目，原生历史不膨胀）
  if (c._navSrc === 'restore') {
    c._navSrc = null;
    if (url === c._nav.stack[c._nav.idx] || !c._nav.stack[c._nav.idx]) {
      // R9 审计 W42：与 back/fwd 分支同款——前台恢复才置激活（巡检路径
      // _webActivePid 陈旧时，恢复后 _webCur 族操作不再错靶）
      if (c.wrap.style.display !== 'none') _webActivePid = c.portId;
      c._ctlUrl = url;
      const inpR = c.wrap.querySelector('[data-web-input]');
      if (inpR && document.activeElement !== inpR) inpR.value = url;
      return;
    }
    // 栈顶对不上（异常形态）→ 回落下方原规则
  }
  // R4 审计 W28（D8）：后退/前进 = 移动栈指针而非写入（期望 URL 对账；
  // 对账失败=重定向中转等形态，回落下方原写入规则）
  if (c._navSrc === 'back' || c._navSrc === 'fwd') {
    const dir = c._navSrc === 'back' ? -1 : 1;
    const expect = c._nav.stack[c._nav.idx + dir];
    c._navSrc = null;
    if (expect === url) {
      c._nav.idx += dir;
      if (c.wrap.style.display !== 'none') _webActivePid = c.portId;
      c._ctlUrl = url;
      const inpN = c.wrap.querySelector('[data-web-input]');
      if (inpN && document.activeElement !== inpN) inpN.value = url;
      _webSetLabel(c, _webShortUrl(url));   // R-命名统一
      return;
    }
  }
  // a555 审计修：仅前台 tab 可置激活——后台 tab 的延迟 SourceChanged
  // （重定向收尾/慢加载/SPA pushState）会偷走激活态，后续工具栏操作
  // 全打到错误 tab
  if (c.wrap.style.display !== 'none') _webActivePid = c.portId;
  c._ctlUrl = url;                          // 真实 URL（含页内跳转）
  const inp = c.wrap.querySelector('[data-web-input]');
  if (inp && document.activeElement !== inp) inp.value = url;
  // 栈：同 host 的页内跳转替换栈顶，跨站 push（会话恢复语义保留）
  const top = c._nav.stack[c._nav.idx];
  if (top) {
    try {
      const a = new URL(url), b = new URL(top);
      if (a.host === b.host) c._nav.stack[c._nav.idx] = url;
      else { c._nav.stack = c._nav.stack.slice(0, c._nav.idx + 1);
             c._nav.stack.push(url); c._nav.idx = c._nav.stack.length - 1;
             // a555 审计修：页内跨站 push 无上限（_webNavigate 有 50 帽）
             if (c._nav.stack.length > 50) { c._nav.stack.shift(); c._nav.idx--; } }
    } catch (_) {}
    _webSessionSave();
  }
  _webSetLabel(c, _webShortUrl(url));   // R-命名统一
};
window.__webTabHist = function (tid, back, fwd) {
  const c = _webByTabId(tid);
  if (!c) return;
  c._canBack = back === true; c._canFwd = fwd === true;
  const bb = c.wrap.querySelector('[data-web="back"]');
  const ff = c.wrap.querySelector('[data-web="fwd"]');
  if (bb) bb.disabled = !back;
  if (ff) ff.disabled = !fwd;
};
window.__webTabTitle = function (tid, title) {
  const c = _webByTabId(tid);
  // 用户令：后台回收（休眠→about:blank）不得把网页名刷成空白——
  // 空/空白标题（about:blank 阶段推送）直接忽略，保留最后真实标题
  var t = String(title || '').trim();
  // a591：检查用 t（已 trim），赋值也要用 t——原来检查 t、传原文 title，
  // 首尾带空白的标题会以原样进标签（与判据不一致）。
  if (c && t && t !== 'about:blank') _webSetLabel(c, t);
};
// 控件内 window.open / target=_blank → 本面板内导航
// 控件导航开始/完成 → 加载指示（刷新转圈+地址栏呼吸，a553 找回）
window.__webTabLoad = function (tid, on) {
  const c = _webByTabId(tid);
  if (!c) return;
  c.wrap.classList.toggle('web-loading', !!on);
};
// R-外泄根治·静止帧：控件隐藏前后端抓的当前画面 → 占位背景（页面看
// 起来被「冻结」而非变白；重新显示时由 reconcile 清除露出活页面）
window.__webTabShot = function (tid, dataUrl) {
  const c = _webByTabId(tid);
  if (!c || !c.wrap) return;
  const host = c.wrap.querySelector('.web-host');
  if (host) {
    // 无条件上帧：活页面（HWND）可见时背景被盖住无碍；迟到帧保留到下次
    // 隐藏瞬间立即生效（比暗底强）。滤镜=「已暂停」的视觉语义（用户令）
    host.style.backgroundImage = 'url("' + dataUrl + '")';
    host.style.backgroundSize = '100% 100%';
    host.style.backgroundRepeat = 'no-repeat';
    host.style.filter = 'brightness(0.8) saturate(0.85)';
  }
};
window.__webTabNew = function (url) {
  // a554 多开：控件内新窗口请求 → 开新网页 tab（浏览器语义）
  if (url) buildWebPanelTab(url, { newTab: true });
};

// a550：modal 联动——新建连接等弹窗（.modal.show）打开时网页控件必须
// 隐藏：WebView2 控件是 WinForms 原生子窗口，窗口层级永远在主 UI 的
// DOM 之上，任何 z-index 都压不过（用户实锤：新建连接 UI 被网页盖住）
(function () {
  // a555 审计修（浏览器实测实锤）：①可见性判定改实测——#ctxMenu 常驻
  // DOM、inline style 为空靠 CSS 默认 display:none 隐藏，原
  // .ctx-menu:not([style*="display: none"]) 从页面加载起就永久误匹配
  // → sync 一跑就把网页控件全藏；②右键/收藏菜单经 style.display 开关
  // （class 观察器看不见），补 pointerdown/click/contextmenu 捕获联动
  //（开菜单的 contextmenu 在显示前、关菜单的 click 在隐藏前——延迟一
  // 拍查实测可见性）；③a554 去单例后 connections[WEB_PORTID] 恒 null，
  // 原判定整体失效，改 _webCur()
  const shown = (el) => !!(el && (el.offsetWidth || el.offsetHeight));
  // R-外泄根治·浮层检测结构化（家族第 11 修教训：类名名单永远补不全——
  // 本例「新建文件」下拉 .nf-menu 不在名单 → 控件不藏 → HWND 啃掉菜单下半截）：
  // ① 类名快速路径（modal/ctx/fav/nf-menu）；
  // R9.13 临时禁用结构兜底扫描（家族第 14/15 例实锤：矩形相交判定在
  // 真实环境产生幻影 → 控件被永久隐藏 = 全黑冻结，且无浮层也持续）。
  // 只保留类名快速路径。代价：未在名单里的自定义浮层会啃控件边缘
  // （cosmetic），换取「绝不无端冻结」。待定位到具体误判源后重建。
  // a592（用户实锤「点 🔑 没反应/一闪而过」）：原名单写死 #webFavMenu，
  // 密码菜单 id 是 #webPwMenu、两者只共用 .web-fav-menu 类 → 密码菜单
  // 不在名单 → WebView2 原生控件不隐藏 → 菜单被原生子窗口整块盖住，
  // 用户只看到闪一下。改按类名匹配，两个菜单与将来同族浮层一并覆盖。
  const anyOverlayOpen = () => {
    if ([...document.querySelectorAll('.modal, .ctx-menu, .web-fav-menu, .nf-menu, .tab-overflow-list')]
        .some(shown)) return true;
    return false;
  };
  // R9.13 诊断：冻结现场在【工具主界面】console 跑 __fcDiag()，一次给出
  // 推演的全部输入（激活/在屏/阅读/休眠/浮层判定/各 tab 镜像/候选浮层）
  window.__fcDiag = function () {
    try {
      const a = connections[activePortId];
      const webTabs = Object.values(connections).filter(
        c => c && c.meta && c.meta.kind === 'web').map(c => ({
          pid: c.portId,
          wrapShown: c.wrap && c.wrap.style.display !== 'none',
          ctlShown: c._ctlShown,
          reader: !!(c._ui && c._ui.reader),
          sleeping: !!(c._ui && c._ui.sleeping),
          label: (c.meta.label || '').slice(0, 24)
        }));
      return JSON.stringify({
        active: activePortId,
        activeKind: a && a.meta ? a.meta.kind : null,
        activeWeb: !!(a && a.meta && a.meta.kind === 'web'),
        wrapShown: !!(a && a.wrap && a.wrap.style.display !== 'none'),
        reader: !!(a && a._ui && a._ui.reader),
        sleeping: !!(a && a._ui && a._ui.sleeping),
        overlay: !!(window.__webOverlayOpen && window.__webOverlayOpen()),
        pwMO: !!window.__fcPwMO,
        webTabs: webTabs,
        cands: [...document.querySelectorAll('.modal,.ctx-menu,#webFavMenu,.nf-menu')]
          .map(e => ({ c: (e.className || e.id || '').slice(0, 40),
                       w: e.offsetWidth, h: e.offsetHeight,
                       vis: getComputedStyle(e).visibility }))
          .filter(x => x.w > 0 || x.h > 0)
      });
    } catch (e) { return 'diag-error: ' + e.message; }
  };
  window.__webOverlayOpen = anyOverlayOpen;   // R-外泄根治：推演函数读取
  // a592：同步强制推演一次并**立即**下发隐藏——异步观察器要等两帧，
  // 浮层首帧会被原生控件盖住（用户实锤「点 🔑 一闪而过」）。浮层打开时
  // 直接把当前所有 web 控件的可见意图置 false（幂等，浮层关闭后
  // _webReconcileVis 会按状态重新显示）。
  window.__webHideCtlNow = function () {
    try {
      for (const pid in connections) {
        const c = connections[pid];
        if (c && c.meta && c.meta.kind === 'web' && c._ctlShown) {
          c._ctlShown = false;
        }
      }
      _webCtlVisible(false, true);
    } catch (_) {}
  };
  let pend = false;
  const sync = () => {
    pend = false;
    _webReconcileVis();   // R-外泄根治：浮层开合只是推演触发器之一
  };
  const queue = () => {
    if (pend) return;
    pend = true;
    setTimeout(sync, 0);
  };
  const mo = new MutationObserver(queue);
  mo.observe(document.body, {
    subtree: true, attributes: true,
    attributeFilter: ['class']
  });
  ['pointerdown', 'click', 'contextmenu'].forEach(ev =>
    document.addEventListener(ev, queue, true));
})();

// R-命名统一（用户实锤「多开全是『网页』分不清」）：tab DOM 与
// conn.meta.label 必须同步——抽屉/悬浮组/侧栏/分组胶囊读的全是
// meta.label（此前建 tab 时写死「网页」，导航后永不更新）。命名优先级：
// 页面真实标题（DocumentTitle）> 短网址 > 兜底「网页」。
function _webSetLabel(c, text) {
  if (!c) return;
  const t = (String(text || '').trim() || '网页').slice(0, 24);
  const changed = c.meta.label !== t;
  c.meta.label = t;
  const el = c.tab.querySelector('.label');
  if (el) el.textContent = t;
  // 侧栏/抽屉有渲染缓存（key 含 meta.label）——仅在真变化时去抖刷新
  if (changed && typeof refreshSidebar === 'function') {
    clearTimeout(_webSetLabel._rsT);
    _webSetLabel._rsT = setTimeout(() => {
      try { refreshSidebar(); } catch (_) {}
    }, 500);
  }
}

// 导航（终局：控件 Navigate，无代理无软过渡）
function _webNavigate(url, c) {
  c = c || _webCur();    // R8 审计 W33（合入漏项）：接 B1/W15 的定向实参
  if (!c || !url) return;
  c._navSrc = null;      // 用户导航优先——丢弃未消费的 back/fwd 对账标记

  c._nav.stack = c._nav.stack.slice(0, c._nav.idx + 1);
  c._nav.stack.push(url);
  if (c._nav.stack.length > 50) c._nav.stack.shift();
  c._nav.idx = c._nav.stack.length - 1;
  _webActivePid = c.portId;                // a554：导航即激活
  _webSessionSave();
  _webWake(c);
  if (c._ui.reader) _webReaderToggle(false, true, c);
  _webCtl(c, { act: 'create', url, epoch: _webPageEpoch });   // 幂等：已有则等价 navigate
  _webReconcileVis();   // R-外泄根治：替代定向 show（地址栏回车=本 tab 在屏）
  const inp = c.wrap.querySelector('[data-web-input]');
  if (inp) inp.value = url;
  _webSetLabel(c, _webShortUrl(url));
  _webApplyZoom(_webZoomFor(url), _webHostOf(url), c);
  _webSyncUI(c);
}

// switchTab 联动（切到/切离网页 tab 时控件显隐）——包一层原 switchTab
(function () {
  const orig = window.switchTab;
  if (typeof orig !== 'function') return;
  window.switchTab = function (pid, auto) {
    // a555 审计修：透传 auto 参——丢了会被 _tabTouch 记成用户访问
    // （MRU 污染，a452/a455 防过的回归）
    const prev = _webCur();
    orig(pid, auto);
    const c = connections[pid];
    const isWeb = !!(c && c.meta && c.meta.kind === 'web');
    if (isWeb) {
      _webActivePid = pid;
      // a556（用户实锤：切回休眠 tab 干等 1s 巡检）：立即唤醒+恢复上次
      // URL，不等 1s 兜底巡检；「正在唤醒…」只在导航完成前一瞬可见
      if (c._ui && c._ui.sleeping) {
        _webWake(c);
        const u = _webNavTop(c);              // a556：跳过脏 about:blank
        if (u) _webRestore(c, u);   // R4 审计 W29（D8）：GoBack 恢复不加历史条目
      }
      // 目标 tab 控件显示 + 布局对齐；其余网页 tab 控件隐藏
      // R-外泄根治：可见性全部收敛到推演（W31/W32 的阅读态守卫、a551
      // 浮层联动、B22 定向语义全部由 _webReconcileVis 统一推导）
      _webReconcileVis();
      // R9.6·第二拍：suspend 回推帧/后端隐藏完成在 ~100-300ms 后——
      // 二次推演吸收该窗口内的任何中间态
      setTimeout(_webReconcileVis, 200);
      if (c._ctlPush) setTimeout(c._ctlPush, 30);
    } else if (prev && prev._tabId) {
      // a555 审计修：关活动网页 tab 时 closeEditorTab 内部会自动回切
      // （switchTab 重入）——若回切目标是另一个网页 tab，这里不得再隐藏
      // （原先照藏 → 回切后的网页 tab 控件消失，用户看到空面板）
      const a = (typeof activePortId !== 'undefined')
        ? connections[activePortId] : null;
      const activeWeb = !!(a && a.meta && a.meta.kind === 'web');
      if (!activeWeb) _webReconcileVis();   // R-外泄根治
    }
  };
  // 关 tab 联动：关闭网页 tab → dispose 控件
  const origClose = window.closeEditorTab;
  if (typeof origClose === 'function') {
    window.closeEditorTab = function (pid) {
      const c = connections[pid];
      if (c && c.meta && c.meta.kind === 'web' && c._tabId) {
        try { _webCtl(c, { act: 'dispose' }); } catch (_) {}
        // a555 审计修：解绑布局跟随——原先每关一个网页 tab 泄漏一份
        // window 级 resize 闭包（强持 conn/wrap，还对已 dispose 控件发 layout）
        try { if (c._ctlResize) c._ctlResize.disconnect(); } catch (_) {}
        try { if (c._ctlPush) window.removeEventListener('resize', c._ctlPush); } catch (_) {}
        if (_webActivePid === pid) _webActivePid = null;
      }
      return origClose(pid);
    };
  }
})();

// ---- a475 休眠（a544 适配控件）----
function _webSleep(c) {
  c._ui.sleeping = true;
  const ov = c.wrap.querySelector('[data-web-sleep]');
  if (ov) ov.style.display = 'flex';
  _webCtl(c, { act: 'nav', url: 'about:blank' });   // 释放页面
  c._blanked = true;   // R4 审计 W29（D8）：原生历史已进 about:blank——唤醒走 GoBack 不加条目
  // a556 + R-外泄根治：休眠=可见性状态变化 → 交推演（原先此处的定向
  // show(false) 与全部散装命令一并退役）
  _webReconcileVis();
}
function _webWake(c) {
  if (!c._ui.sleeping) return;
  c._ui.sleeping = false;
  c._hidSec = 0;
  const ov = c.wrap.querySelector('[data-web-sleep]');
  if (ov) ov.style.display = 'none';
  _webReconcileVis();   // R-外泄根治：唤醒=状态变化（恢复无 URL 时也不漏）
}
// R4 审计 W29（D8）：内部 about:blank 的恢复走原生 GoBack——不新进历史
// 条目（原先 Navigate(u) 使原生历史 [.., B, about:blank, B'] 膨胀，用户
// 按 ◀ 落白屏且 a556 过滤使前端不知情）。无 back 可用时回落 Navigate。
function _webRestore(c, url) {
  if (c._blanked) {
    c._blanked = false;
    c._navSrc = 'restore';       // 下一条 SourceChanged 不动栈（B 即栈顶本尊）
    _webCtl(c, { act: 'back' });
    return;
  }
  _webNavigate(url, c);
}
// 切回网页 tab 自动唤醒：恢复上次 URL（a556：switchTab 包装器已内联
// 立即唤醒，这里作兜底巡检——display 变化不经 switchTab 的路径）
setInterval(() => {
  // a554 多开：任意隐藏中的休眠网页 tab 回前台即唤醒
  for (const pid in connections) {
    const c = connections[pid];
    if (!c || !c.meta || c.meta.kind !== 'web' || !c._ui) continue;
      if (c._ui.sleeping && c.wrap.style.display !== 'none') {
      _webWake(c);
      const url = _webNavTop(c);               // a556：跳过脏 about:blank
      if (url) _webRestore(c, url);   // R4 审计 W29（D8）+ R2 审计 W15：定向 + GoBack 恢复
    }
  }
}, 1000);

// ---- a475 阅读模式（a544 适配控件）----
function _webReaderToggle(on, skipRestore, c) {
  c = c || _webCur();        // R2 审计 B7：可指定所属 tab（同型变体）
  if (!c) return;
  const rd = c.wrap.querySelector('[data-web-reader]');
  const host = c.wrap.querySelector('.web-host');
  const btn = c.wrap.querySelector('[data-web="read"]');
  const url = (c._nav && c._nav.stack[c._nav.idx]) || '';
  if (on && !url) return;
  c._ui.reader = on;
  if (!on) {
    rd.style.display = 'none';
    host.style.display = '';
    if (btn) btn.innerHTML = ICO16.book + ' 阅读';
    _webReconcileVis();   // R-外泄根治：阅读退出=状态变化 → 推演
    if (!skipRestore && url) {
      // R4 审计 W29（D8）：恢复走原生 GoBack（不加历史条目）；无
      // _blanked/无 back 可用（后端 no-op）时回落 Navigate
      if (c._blanked) { c._blanked = false; c._navSrc = 'restore'; _webCtl(c, { act: 'back' }); }
      else _webCtl(c, { act: 'nav', url });
    }
    return;
  }
  rd.innerHTML = '<div class="web-reader-load">正在取正文…</div>';
  rd.style.display = '';
  host.style.display = 'none';
  // 阅读态：控件隐藏 + about:blank 释放页面 JS
  // R4 审计 W29（D8）：进 about:blank 前查重——已在全隐态（连点/休眠
  // 叠加）不重复导航，防原生历史堆叠多个 about:blank
  if (!c._blanked) {
    c._blanked = true;
    _webCtl(c, { act: 'nav', url: 'about:blank' });
  }
  _webReconcileVis();   // R-外泄根治：阅读进入=状态变化 → 推演
  // 序号守卫（审计 O1）：连点 back/fwd 旧响应晚归不覆盖新正文
  const mySeq = (c._ui.rseq = (c._ui.rseq || 0) + 1);
  fetch('/api/web/fetch_text', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }) })
    .then(r => r.json()).then(j => {
      if (!c._ui.reader || mySeq !== c._ui.rseq) return;
      if (!j || !j.ok) {
        rd.innerHTML = '<div class="web-reader-err">取正文失败：'
          + esc(((j && j.err) || '未知')) + '——用「浏览器」按钮打开</div>';
        return;
      }
      rd.innerHTML = '<div class="web-reader-head">' + esc(j.title || _webShortUrl(url))
        + (j.truncated ? ' <span class="web-reader-trunc">（超长已截断）</span>' : '')
        + '<span class="web-reader-url">' + esc(url) + '</span></div>'
        + '<div class="web-reader-body">' + esc(j.text).replace(/\n/g, '<br>') + '</div>';
    }).catch(e => {
      if (c._ui.reader && mySeq === c._ui.rseq)
        rd.innerHTML = '<div class="web-reader-err">取正文失败：' + esc(String(e)) + '</div>';
    });
}

// ---- a475 站点缩放（阅读态 + 宿主区视觉缩放）----
function _webHostOf(url) {
  try { return new URL(url).host; } catch (_) { return ''; }
}
function _webZoomFor(url) {
  const h = _webHostOf(url);
  try { return parseFloat(localStorage.getItem('web-zoom:' + h)) || 1; } catch (_) { return 1; }
}
function _webApplyZoom(z, host, c) {
  // a555 审计修：原 connections[WEB_PORTID] 恒 null——缩放全链路死代码
  c = c || _webCur();        // R2 审计 B7：可指定所属 tab（同型变体）
  if (!c) return;
  c._ui.zoom = z;
  const hostEl = c.wrap.querySelector('.web-host');
  const rd = c.wrap.querySelector('[data-web-reader]');
  if (hostEl) hostEl.style.zoom = z;
  if (rd) rd.style.fontSize = (13 * z) + 'px';
  if (host) { try { localStorage.setItem('web-zoom:' + host, String(z)); } catch (_) {} }
}
function _webSyncUI(c) {
  c = c || _webCur();        // R2 审计 B7：可指定所属 tab（同型变体）
  if (!c) return;
  const url = (c._nav && c._nav.stack[c._nav.idx]) || '';
  // a544：按钮态由控件事件回推（__webTabHist）维护——这里只管收藏星
  const favs = _webFavs();
  const starred = url && favs.some(f => f.url === url);
  const starBtn = c.wrap.querySelector('[data-web="star"]');
  starBtn.style.color = starred ? 'var(--accent)' : '';
  starBtn.title = starred ? '取消收藏当前页' : '收藏当前页';
}
function _webAct(act, wrap) {
  // R2 审计 B7：按钮属于哪个 wrap 就操作哪个 tab——原取 _webCur()，
  // 对非激活 tab 点 收藏/阅读/发给Claude/后退/前进/刷新 全落在激活 tab 上。
  const c = connections[(wrap && wrap.dataset.portId) || ''] || _webCur();
  if (!c) return;
  const url = (c._nav && c._nav.stack[c._nav.idx]) || '';
  // R4 审计 W28（D8）：后退/前进打导航来源标记——下一条 SourceChanged
  // 对栈做指针移动而非写入（对账见 __webTabUrl）
  if (act === 'back') { c._navSrc = 'back'; _webCtl(c, { act: 'back' }); return; }
  if (act === 'fwd') { c._navSrc = 'fwd'; _webCtl(c, { act: 'fwd' }); return; }
  if (act === 'reload') {
    if (c._ui.reader) _webReaderToggle(true, false, c);    // 阅读态重载=重取正文
    else _webCtl(c, { act: 'reload' });
    return;
  }
  if (act === 'read') { _webReaderToggle(!c._ui.reader, false, c); return; }
  if (act === 'sys' && url) {
    fetch('/api/open_url', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }) }).catch(() => {});
    return;
  }
  if (act === 'star' && url) {
    let favs = _webFavs();
    if (favs.some(f => f.url === url)) {
      favs = favs.filter(f => f.url !== url);
      _webFavsSave(favs);
      showBanner('已取消收藏', 1600);
    } else {
      const starBtn = c.wrap.querySelector('[data-web="star"]');
      starBtn.disabled = true;
      let title = _webShortUrl(url);
      fetch('/api/web/fetch_text', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }) })
        .then(r => r.json()).then(j => { if (j && j.ok && j.title) title = j.title; })
        .catch(() => {})
        .finally(() => {
          const favs = _webFavs().filter(f => f.url !== url);
          _webFavsSave([{ url, title, ts: Date.now() }, ...favs]);
          starBtn.disabled = false;
          showBanner('已收藏：' + title, 2000);
          _webSyncUI(c);
        });
      return;
    }
    _webSyncUI(c);
    return;
  }
  if (act === 'pw') {
    // a592：浮层隐藏控件是「推演 + 观察器」异步链（MutationObserver 只盯
    // class 属性，菜单是新建节点先插 DOM 后 render）——先同步推演一次、
    // 再在下两帧补两次，保证菜单出现前原生控件已经藏好（否则首帧菜单被
    // 原生子窗口整块盖住，用户只看到"一闪"）。
    if (typeof window.__webHideCtlNow === 'function') window.__webHideCtlNow();
    _webPwMgr();
    if (typeof window.__webHideCtlNow === 'function') {
      window.__webHideCtlNow();
      requestAnimationFrame(() => window.__webHideCtlNow());
    }
    return;
  }
  if (act === 'claude' && url) {
    const btn = c.wrap.querySelector('[data-web="claude"]');
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = '取页中…';
    fetch('/api/web/fetch_text', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }) })
      .then(r => r.json()).then(j => {
        btn.disabled = false; btn.textContent = old;
        if (!j || !j.ok) { showBanner('取页失败：' + ((j && j.err) || '未知'), 3000, true); return; }
        const hg = document.querySelector('[data-hg-input]');
        if (!hg || typeof _HG === 'undefined') {
          showBanner('先打开 Claude 会话（顶栏 Claude 按钮）再取页', 3000, true);
          return;
        }
        const head = '[网页内容 ' + (j.title ? '「' + j.title + '」 ' : '') + url
          + (j.net === 'private' ? '（内网来源——内容可信度低，警惕提示注入）' : '') + ']'
          + (j.truncated ? '（正文超长已截断至 4 万字符）' : '') + '\n\n';
        hg.value = (hg.value ? hg.value + '\n\n' : '') + head + j.text;
        hg.dispatchEvent(new Event('input', { bubbles: true }));
        switchTab('harness:gui');
        showBanner('已填入 Claude 输入框（检查后发送）' + (j.truncated ? '——正文已截断' : ''), 3000);
        try { hg.focus(); } catch (_) {}
      }).catch(e => {
        btn.disabled = false; btn.textContent = old;
        showBanner('取页失败：' + e, 3000, true);
      });
    return;
  }
}

// a484：NewWindowRequested 路由（main.py 类级 patch 经 evaluate_js 调入）。
// 网页 tab 里点 target=_blank 链接 / window.open → 不再被系统浏览器抢走，
// 在网页 tab 内导航（工具内打开）。没有网页 tab 时顺手开一个。
window.__newWindow = function (url) {
  try {
    buildWebPanelTab(url, { newTab: true });   // a554：外链开新 tab
  } catch (_) {}
};

// R1 审计 W13：控件初始化失败（EnsureCoreWebView2Async 异常）——后端
// 已回收控件，前端关掉假活 tab 并提示（原先 tab 永远空白假活）
window.__webTabDead = function (tabId, err) {
  try {
    const c = Object.values(connections).find(
      x => x && x.meta && x.meta.kind === 'web' && x._tabId === tabId);
    if (c) {
      showBanner('网页 tab 初始化失败：' + (err || '未知'), 4000, true);
      closeEditorTab(c.portId);
    }
  } catch (_) {}
};

// a483：右键分区放行。pywebview 非 debug 全局禁右键，现改为全局开（main.py
// on_loaded 置 AreDefaultContextMenusEnabled=True）——本页除网页 tab 外的
// 全部区域在捕获阶段 preventDefault 恢复屏蔽；.web-body 内放行原生菜单
// （刷新/后退/复制/查看源码/检查等；跨域 iframe 内右键由渲染进程直接出
// 原生菜单，事件不达父页，天然放行）。各模块自建右键菜单（文件树/tab/
// 终端等）本就自带 preventDefault + stopPropagation，不受影响。
document.addEventListener('contextmenu', (e) => {
  // R4 审计 D1（用户定调）：正常模式工具 UI 本体不允许刷新——主 UI 文档
  // 一律不放行原生菜单（其「重新加载」= 整工具刷新；「web 上刷新刷掉整
  // 个工具」的根因：阅读/休眠态控件隐藏后 .web-body 右键落到主文档菜单）。
  // WebView2 控件 HWND 覆盖区的右键由控件自身处理（事件不到主文档，
  // 天然放行不受影响）。debug 模式保留原行为。
  if (!window.__HG_DBG__) { e.preventDefault(); return; }
  const inWeb = e.target && e.target.closest
      && e.target.closest('.web-body, .web-reader');
  if (!inWeb) e.preventDefault();
}, true);
// R4 审计 D1（用户定调）：正常模式 F5/Ctrl+R 不再整刷工具——激活 tab 是
// 网页时改刷该网页（浏览器语义），否则吞掉；debug 模式放行（整 UI 刷新
// =调试能力，index.html 的 pagehide 清场照旧）。
document.addEventListener('keydown', (e) => {
  if (window.__HG_DBG__) return;
  if (!(e.key === 'F5' || (e.ctrlKey && /^r$/i.test(e.key)))) return;
  e.preventDefault();
  // R9 审计 B26：只认「激活 tab 恰为网页」——_webCur() 有回落第一个
  // 网页 conn 的语义，激活非网页 tab 时按它取会把 reload 泄漏给后台
  // 网页 tab。激活判定用 activePortId（顶层激活 tab 的权威来源）。
  const a = (typeof activePortId !== 'undefined') ? connections[activePortId] : null;
  if (a && a.meta && a.meta.kind === 'web' && a.wrap) _webAct('reload', a.wrap);
}, true);

// 顶部地址栏 + tab 栏收藏星标（index.html 静态节点，此处绑定）
(function () {
  const bar = document.getElementById('topUrlBar');
  if (bar) bar.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing) return;
    e.preventDefault();
    const u = _webNormUrl(bar.value);
    // R3 审计 W23/A10''（R8 W35 补漏合）：非空输入被拦成 '' = 非法协议，
    // 给可见反馈；真空输入才走「开网页 tab（恢复会话）」
    if (!u) {
      if (bar.value.trim()) { showBanner('该协议不允许在内嵌浏览器打开', 2500, true); return; }
      buildWebPanelTab(); bar.value = ''; bar.blur(); return;   // 灵动岛：清空+缩回
    }
    // a556（用户令）：顶栏输入网址回车即开新网页 tab——浏览器地址栏语义
    buildWebPanelTab(u, { newTab: true });
    bar.value = ''; bar.blur();   // 灵动岛：清空+缩回（打开网址不受影响）
  });
  const fav = document.getElementById('tabFavBtn');
  if (fav) fav.onclick = (e) => { e.stopPropagation(); _webFavMenu(fav); };
})();

let __fcPwToken = '';   // RA12：密码管理器鉴权 token（boot 后经 /api/status 取得）
let __fcPwTokenPromise = null;   // a591：token 拉取的 in-flight 共享（防首次打开 403）
// ---- a583 密码管理器：列出原生密码库（Chromium Login Data）已存站点，
// 支持显示明文（后端三层解密）与删除（库锁定时挂起、退出后生效） ----
function _webPwMgr() {
  const old = document.getElementById('webPwMenu');
  if (old) { old.remove(); return; }
  const anchor = document.querySelector('[data-web="pw"]');
  const menu = document.createElement('div');
  menu.id = 'webPwMenu';
  menu.className = 'web-fav-menu';
  menu.innerHTML = '<div class="web-fav-title">密码管理 · 读取中…</div>';
  document.body.appendChild(menu);
  // a592（用户实锤「往上弹」）：工具条贴着窗口顶部，锚点上方永远放不下，
  // 原逻辑先试上方、放不下才落下方——但首个 render 前菜单高度只有一行
  // 「读取中」，此时上方判定可能成立 → 菜单向上弹。改为**默认向下**：
  // 只有下方确实放不下且上方放得下才向上（与下拉框直觉一致）。
  const pos = () => {
    const r = anchor.getBoundingClientRect();
    menu.style.right = Math.max(8, window.innerWidth - r.right - 4) + 'px';
    const h = menu.offsetHeight;
    const below = r.bottom + 6;
    const above = r.top - h - 6;
    const fitsBelow = below + h <= window.innerHeight - 8;
    const fitsAbove = above >= 8;
    let top;
    if (fitsBelow) top = below;
    else if (fitsAbove) top = above;
    else top = Math.max(8, window.innerHeight - h - 8);
    menu.style.top = top + 'px';
  };
  pos();
  const close = (ev) => {
    if (!menu.contains(ev.target) && !(anchor && anchor.contains(ev.target))) {
      menu.remove();
      document.removeEventListener('click', close, true);
    }
  };
  setTimeout(() => document.addEventListener('click', close, true), 0);
  // a591：token 必须「先取后用」——原实现发起 fetch 后不等结果就往下走，
  // 首次打开（刷新页面后第一次点 🔑）必然无 token → pw_list 403 →
  // render([]) → 把一个有密码的库显示成「还没有保存过密码」。第二次才正常。
  const ensurePwToken = () => {
    if (__fcPwToken) return Promise.resolve(__fcPwToken);
    if (__fcPwTokenPromise) return __fcPwTokenPromise;
    __fcPwTokenPromise = fetch('/api/status').then(r => r.json()).then(j => {
      if (j && j.pw_token) __fcPwToken = j.pw_token;
      return __fcPwToken;
    }).catch(() => null).finally(() => { __fcPwTokenPromise = null; });
    return __fcPwTokenPromise;
  };
  const api = (body) => {
    // 每次调用都先确保 token 就位（并发调用共享同一个 in-flight promise）
    return ensurePwToken().then(() => {
      const headers = { 'Content-Type': 'application/json' };
      if (__fcPwToken) headers['X-FC-Token'] = __fcPwToken;   // RA12：密码端点鉴权
      return fetch('/api/web/tabs', {
        method: 'POST', headers,
        body: JSON.stringify(body)
      }).then(r => r.json()).catch(() => ({ ok: false }));
    });
  };
  const render = (items) => {
    menu.innerHTML = '<div class="web-fav-title">密码管理' +
      (items.length ? ' · ' + items.length + ' 个站点' : '') + '</div>' +
      (items.length ? items.map((it, i) =>
        '<div class="web-fav-item" data-pwi="' + i + '" title="' + esc(it.origin) + '">' +
        '<span class="web-fav-name">' + esc((it.user || '（无用户名）') + ' @ ' +
          (it.origin || '').replace(/^https?:\/\//, '')) + '</span>' +
        '<span class="web-fav-x" data-pw-show="' + i + '" title="显示密码">' + ICO16.eye + '</span>' +
        '<span class="web-fav-x" data-pw-edit="' + i + '" title="修改密码">' + ICO16.pencil + '</span>' +
        '<span class="web-fav-x" data-pw-del="' + i + '" title="删除">✕</span></div>'
      ).join('')
      : '<div class="web-fav-empty">原生密码库还没有保存过密码——在网页 tab 登录时点保存条即可</div>');
    pos();
    let cur = items;
    menu.onclick = (e) => {
      const sh = e.target.closest('[data-pw-show]');
      if (sh) {
        e.stopPropagation();
        const it = cur[+sh.dataset.pwShow];
        const row = sh.closest('.web-fav-item');
        const nm = row.querySelector('.web-fav-name');
        if (nm.dataset.shown) { nm.textContent = nm.dataset.orig; delete nm.dataset.shown; return; }
        nm.dataset.orig = nm.textContent; nm.dataset.shown = '1';
        nm.textContent = '解密中…';
        api({ act: 'pw_reveal', origin: it.origin, user: it.user }).then(j => {
          nm.textContent = (j && j.ok) ? (it.user || '(无用户名)') + ' | ' + (j.pw || '(空)')
            : '❌ ' + ((j && j.err) || '解密失败');
        });
        return;
      }
      // a592（用户实锤「只能显隐，不能手动改」）：改密码——行内换成输入框，
      // 回车保存 / Esc 取消。库被 Chromium 占用的情形由后端挂起、退出时落盘。
      const ed = e.target.closest('[data-pw-edit]');
      if (ed) {
        e.stopPropagation();
        const it = cur[+ed.dataset.pwEdit];
        const row = ed.closest('.web-fav-item');
        if (!row || row.dataset.editing) return;
        row.dataset.editing = '1';
        const nm = row.querySelector('.web-fav-name');
        const orig = nm.innerHTML;
        nm.innerHTML = '<input class="web-fav-note-inp" data-pw-inp ' +
          'placeholder="输入新密码后回车保存" spellcheck="false" autocomplete="off" name="web_pw_new">';
        const inp = nm.querySelector('[data-pw-inp]');
        inp.focus();
        const done = (save) => {
          delete row.dataset.editing;
          if (!save) { nm.innerHTML = orig; return; }
          const val = inp.value;
          nm.textContent = '保存中…';
          api({ act: 'pw_edit', origin: it.origin, user: it.user, pw: val }).then(j => {
            if (j && j.ok) {
              nm.textContent = (it.user || '(无用户名)') + ' @ ' +
                (it.origin || '').replace(/^https?:\/\//, '');
              showBanner(j.immediate
                ? '密码已修改'
                : '已记录修改——完全退出工具后生效（密码库运行中被浏览器锁定）',
                3500, !j.immediate);
            } else {
              nm.innerHTML = orig;
              showBanner('修改失败：' + ((j && j.err) || '未知错误'), 3000, true);
            }
          });
        };
        inp.addEventListener('keydown', ev => {
          if (ev.key === 'Enter') { ev.preventDefault(); done(true); }
          else if (ev.key === 'Escape') { ev.preventDefault(); done(false); }
          ev.stopPropagation();
        });
        inp.addEventListener('blur', () => { if (row.dataset.editing) done(true); });
        return;
      }
      const dl = e.target.closest('[data-pw-del]');
      if (dl) {
        e.stopPropagation();
        const it = cur[+dl.dataset.pwDel];
        if (!confirm('删除 ' + (it.origin || '') + ' 的已存密码？')) return;
        api({ act: 'pw_del', origin: it.origin, user: it.user }).then(j => {
          if (j && j.ok) {
            showBanner(j.immediate ? '已删除' : '已标记删除——完全退出工具后生效（密码库运行中被浏览器锁定）', 3500, !j.immediate);
            if (j.immediate) render(cur.filter(x => x !== it));
          } else showBanner('删除失败', 2500, true);
        });
        return;
      }
    };
  };
  // a591：403/失败不能渲染成「还没有保存过密码」——那是把鉴权失败说成空库，
  // 用户会以为自己的密码丢了。只有 ok 且 items 为空才是真·空态。
  api({ act: 'pw_list' }).then(j => {
    if (!j || !j.ok) {
      menu.innerHTML = '<div class="web-fav-title">密码管理</div>' +
        '<div class="web-fav-empty">无法读取密码库：' + esc((j && j.err) || '请求失败') +
        '' + '（再点一次 🔑 重试）</div>';
      pos();
      return;
    }
    render(j.items || []);
  });
}

function _webFavMenu(anchor) {
  const old = document.getElementById('webFavMenu');
  if (old) { old.remove(); return; }
  // a592：同密钥菜单——首帧前先同步收掉原生控件，否则菜单被 HWND 盖住
  if (typeof window.__webHideCtlNow === 'function') window.__webHideCtlNow();
  const favs = _webFavs();
  const cur = (_webCur() && _webCur()._nav.stack[_webCur()._nav.idx]) || '';
  const list = document.createElement('div');
  list.id = 'webFavMenu';
  list.className = 'web-fav-menu';
  let html = '<div class="web-fav-title">收藏夹</div>';
  const _wc = _webCur();
  if (_wc && _wc._nav.idx >= 0 && _wc._nav.stack[_wc._nav.idx]) {
    html += `<div class="web-fav-cur" data-fav-resume>${ICO16.restore} 恢复上次网页（${esc(_webShortUrl(_wc._nav.stack[_wc._nav.idx]))}）</div>`;
  }
  if (cur && _webCur()) {   // a555 审计修：原 connections[WEB_PORTID] 恒 null，入口永不渲染
    const starred = favs.some(f => f.url === cur);
    html += `<div class="web-fav-cur" data-fav-act="${starred ? 'unstar' : 'star'}">`
      + (starred
        ? ICO16.star + ' 取消收藏当前网页'
        : '<span style="opacity:0.45">' + ICO16.star + '</span> 收藏当前网页') + '</div>';
  }
  html += favs.map((f, i) =>
    `<div class="web-fav-item" data-fav-i="${i}" title="${esc(f.url + (f.note ? ' · 备注：' + f.note : ''))}">`
    + `<span class="web-fav-name">${esc(f.note || f.title || _webShortUrl(f.url))}</span>`
    + `<span class="web-fav-x" data-fav-edit="${i}" title="编辑备注">${ICO16.pencil}</span>`
    + `<span class="web-fav-x" data-fav-del="${i}" title="删除">✕</span></div>`).join('');
  if (!favs.length) html += '<div class="web-fav-empty">还没有收藏——网页 tab 里点收藏按钮，或地址栏打开后收藏</div>';
  list.innerHTML = html;
  document.body.appendChild(list);
  const r = anchor.getBoundingClientRect();
  list.style.right = Math.max(8, window.innerWidth - r.right - 4) + 'px';
  // 审计修：上方放不下（菜单高于锚点上沿距离）时改锚点下方开，且钳到视口
  const topUp = r.top - list.offsetHeight - 6;
  list.style.top = (topUp >= 8 ? topUp : Math.min(r.bottom + 6,
    Math.max(8, window.innerHeight - list.offsetHeight - 8))) + 'px';
  const close = (ev) => {
    // R9.12：★ 按钮内嵌 SVG 后点击 target 是 svg/path 而非按钮本身，
    // ev.target !== anchor 误判「点在外面」→ 先移除再被 onclick 当作
    // 重新打开 → 菜单永远收不回（用户实锤）。与 editor.js nf-menu 同款
    // contains 判定：点在锚点元素内 = 不是外点
    if (!list.contains(ev.target) && !(anchor && anchor.contains(ev.target))) {
      list.remove();
      document.removeEventListener('click', close, true);
    }
  };
  setTimeout(() => document.addEventListener('click', close, true), 0);
  list.addEventListener('click', (e) => {
    const del = e.target.closest('[data-fav-del]');
    if (del) {
      e.stopPropagation();
      const favs2 = _webFavs();
      favs2.splice(+del.dataset.favDel, 1);
      _webFavsSave(favs2);
      list.remove();
      _webFavMenu(anchor);
      // R3 审计 W26：删除的收藏可能正被任意后台网页 tab 持有——逐个
      // 同步星标态（web tab 数量少，全量同步成本可忽略）
      for (const pid in connections) {
        const cw = connections[pid];
        if (cw && cw.meta && cw.meta.kind === 'web') _webSyncUI(cw);
      }
      return;
    }
    if (e.target.closest('[data-fav-resume]')) {
      e.stopPropagation();
      buildWebPanelTab();
      list.remove();
      return;
    }
    const act = e.target.closest('[data-fav-act]');
    if (act) {
      e.stopPropagation();
      if (cur) _webAct('star');   // toggle：已收藏→取消，未收藏→收藏
      list.remove();
      return;
    }
    // R-命名统一·备注编辑：铅笔按钮进入行内编辑（输入框+对勾），对勾/Enter 保存
    const okBtn = e.target.closest('[data-fav-note-ok]');
    if (okBtn) {
      e.stopPropagation();
      const row = okBtn.closest('[data-fav-i]');
      const inp = row && row.querySelector('.web-fav-note-inp');
      if (inp) _webFavSaveNote(list, anchor, +row.dataset.favI, inp.value);
      return;
    }
    const edBtn = e.target.closest('[data-fav-edit]');
    if (edBtn) {
      e.stopPropagation();
      _webFavEnterEdit(list, anchor, +edBtn.dataset.favEdit);
      return;
    }
    const item = e.target.closest('[data-fav-i]');
    if (item) {
      if (item.dataset.favEditing) return;   // 编辑态：行内点击不触发打开
      const f = _webFavs()[+item.dataset.favI];
      // RC2（红队）：消费端 scheme 白名单——历史/种子回填的 file:// 收藏
      // 点击即拦（服务端清洗只管新写入，存量数据在此兜底）
      if (f && /^https?:\/\//i.test(f.url)) buildWebPanelTab(f.url, { newTab: true });
      else if (f) showBanner('该收藏协议不允许在内嵌浏览器打开', 2500, true);
      list.remove();
    }
  });
}

// R-命名统一·备注编辑：行内编辑态（移除 data-fav-i 的打开语义由
// favEditing 标记拦截；Enter/对勾 保存、Esc 取消）
function _webFavEnterEdit(list, anchor, idx) {
  const row = list.querySelector(`[data-fav-i="${idx}"]`);
  const f = _webFavs()[idx];
  if (!row || !f) return;
  row.dataset.favEditing = '1';
  const name = row.querySelector('.web-fav-name');
  row.querySelectorAll('.web-fav-x').forEach(x => { x.style.display = 'none'; });
  name.innerHTML = `<input class="web-fav-note-inp" maxlength="100" placeholder="备注（留空清除）" value="${esc(f.note || '')}">`
    + `<span class="web-fav-x" data-fav-note-ok title="保存">${ICO16.check}</span>`;
  const inp = name.querySelector('input');
  if (inp) {
    inp.focus();
    inp.select();
    inp.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault(); ev.stopPropagation();
        _webFavSaveNote(list, anchor, idx, inp.value);
      } else if (ev.key === 'Escape') {
        ev.preventDefault(); ev.stopPropagation();
        _webFavMenu(anchor);
      }
    });
  }
}
function _webFavSaveNote(list, anchor, idx, val) {
  const favs = _webFavs();
  const f = favs[idx];
  if (f) {
    const note = String(val || '').trim().slice(0, 100);
    if (note) f.note = note; else delete f.note;
    _webFavsSave(favs);
  }
  list.remove();
  _webFavMenu(anchor);
}

