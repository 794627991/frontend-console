// ============================================================
// 网页 tab（a473，用户令：路线 A——工具内浏览内网页面）
// - iframe 承载：WebView2 应用档 cookie 共享——SSO 在应用内登录一次，
//   之后所有内网 iframe 免登（比系统浏览器还顺手）
// - 已知边界（跨域安全模型，如实记录）：
//   ① 页内点链接后，父页读不到 iframe 当前 URL（地址栏只显示「最近一次
//      我们发起的导航」）；后退/重载基于自有栈（重载式导航，页内链后退
//      会重新加载——可控性优先）
//   ② X-Frame-Options 拒嵌的站点：界面留「系统浏览器打开」一键兜底
//   ③ 页面 title 拿不到——收藏命名取 URL 短化 + 取页接口回传 title
// - 「发给 Claude」：POST /api/web/fetch_text（服务端取页转文本，无登录
//   态页面）→ 填入 Claude 输入框由用户确认发送；带登录态页面走 CDP 工具
//
// a475（用户令「不止做成，更要做好——性能流畅是根本」·借鉴 Edge/Chrome）：
// - 睡眠标签页（Edge sleeping tabs）：切走 10 分钟后 iframe 置空省内存
//   （重 JS 内网页一页 100-300MB 后台零占用），切回自动唤醒恢复
// - 阅读模式（Reader）：fetch_text 文本视图替代 iframe——零 JS 燃烧、
//   文本可选中、GBK 已修；同时是拒嵌站点（X-Frame-Options）的完整降级
// - 会话恢复（session restore）：导航栈持久化，重开网页 tab 回到上次页
// - 站点缩放记忆（per-site zoom）：Ctrl+滚轮缩放，按 host 记忆
// ============================================================
const WEB_PORTID = 'web:panel';
const _webNav = { stack: [], idx: -1 };    // 只记本面板发起的导航
const _webUi = { sleeping: false, reader: false, zoom: 1 };   // a475：面板态
const _WEB_SLEEP_MIN = 10;                 // a475：切走 N 分钟后休眠（分钟）

// a475 会话恢复：启动时读上次栈（重开网页 tab 无显式 URL 时回到上次页）
try {
  const _saved = JSON.parse(localStorage.getItem('web-session') || 'null');
  if (_saved && Array.isArray(_saved.stack) && _saved.stack.length) {
    _webNav.stack = _saved.stack.slice(0, 50);
    _webNav.idx = Math.min(Math.max(-1, _saved.idx | 0), _webNav.stack.length - 1);
  }
} catch (_) {}
function _webSessionSave() {
  try { localStorage.setItem('web-session', JSON.stringify(
    { stack: _webNav.stack, idx: _webNav.idx })); } catch (_) {}
}
// a475 睡眠巡检：网页 tab 不在前台累计计时（60s 一查，开销可忽略），
// 到时置空 iframe（进程回收由 Chromium 完成）；前台/休眠态即停
setInterval(() => {
  const c = connections[WEB_PORTID];
  if (!c || _webUi.sleeping || _webUi.reader) return;
  if (c.wrap.style.display === 'none' && document.visibilityState === 'visible') {
    c._hidSec = (c._hidSec || 0) + 60;
    if (c._hidSec >= _WEB_SLEEP_MIN * 60) _webSleep(c);
  } else {
    c._hidSec = 0;
  }
}, 60000);

function _webFavs() {
  try { return JSON.parse(localStorage.getItem('web-favs') || '[]'); } catch (_) { return []; }
}
function _webFavsSave(v) {
  try { localStorage.setItem('web-favs', JSON.stringify(v.slice(0, 100))); } catch (_) {}
}
function _webShortUrl(u) {
  try {
    const x = new URL(u);
    return (x.host + x.pathname).replace(/\/$/, '') + (x.search || '');
  } catch (_) { return u; }
}
function _webNormUrl(s) {
  s = String(s || '').trim();
  if (!s) return '';
  if (/^https?:\/\//i.test(s)) return s;
  return 'http://' + s;    // 内网多为 http 裸主机名——缺省补 http
}

function buildWebPanelTab(url) {
  let pid = null;
  for (const p in connections) {
    const c = connections[p];
    if (c && c.meta && c.meta.kind === 'web') { pid = p; break; }
  }
  if (pid) {
    switchTab(pid);
    if (url) _webNavigate(url);
    return connections[pid];
  }
  const portId = WEB_PORTID;
  _webNav.stack = []; _webNav.idx = -1;   // 新建即清（上次会话的栈不复活）
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${ICO16.link}</span>` +
    `<span class="label">网页</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; }
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
               placeholder="输入内网地址回车打开（Jenkins / svn web / itsm / wiki…）">
        <button class="btn ghost icon-btn" data-web="star" title="收藏 / 取消收藏当前页">★</button>
        <button class="btn ghost" data-web="read" title="阅读模式：文本视图（零脚本执行、可选可搜；拒嵌站点也能读）">☰ 阅读</button>
        <button class="btn ghost" data-web="claude" title="服务端取本页正文（无登录态页面）填入 Claude 输入框——带登录态的页面请让 AI 用 devtools 工具读">发给 Claude</button>
        <button class="btn ghost" data-web="sys" title="X-Frame-Options 拒嵌等场景：系统浏览器打开">↗ 浏览器</button>
      </div>
      <div class="web-body" data-web-body>
        <iframe class="web-frame" data-web-frame
          referrerpolicy="no-referrer-when-downgrade"></iframe>
        <div class="web-reader" data-web-reader style="display:none;"></div>
        <div class="web-sleep" data-web-sleep style="display:none;">
          <div>🌙 已休眠以省内存（后台超过 10 分钟）<br><span class="web-sleep-sub">正在唤醒…</span></div>
        </div>
      </div>
    </div>`;
  termArea.appendChild(wrap);
  const conn = { portId, meta: { kind: 'web', label: '网页' }, tab, wrap };
  connections[portId] = conn;

  const $w = (s) => wrap.querySelector(s);
  const frame = $w('[data-web-frame]');
  const urlInput = $w('[data-web-input]');
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); _webNavigate(_webNormUrl(urlInput.value)); }
  });
  wrap.querySelectorAll('[data-web]').forEach(b => b.onclick = () => _webAct(b.dataset.web, wrap));
  // a475 站点缩放记忆：Ctrl+滚轮缩放（iframe 元素级 zoom，跨域安全模型
  // 允许——缩的是宿主元素不是内容文档）；按 host 记忆，Ctrl+0 复位
  const body = wrap.querySelector('[data-web-body]');
  body.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const c2 = connections[WEB_PORTID];
    const url = _webNav.stack[_webNav.idx] || '';
    const host = (() => { try { return new URL(url).host; } catch (_) { return ''; } })();
    let z = (c2 && c2._zoom) || 1;
    z = Math.min(2, Math.max(0.5, z * (e.deltaY < 0 ? 1.1 : 0.9)));
    _webApplyZoom(z, host);
  }, { passive: false });
  wrap.addEventListener('keydown', (e) => {
    if (e.ctrlKey && (e.key === '0' || e.key === 'Num0')) {
      e.preventDefault();
      const url = _webNav.stack[_webNav.idx] || '';
      const host = (() => { try { return new URL(url).host; } catch (_) { return ''; } })();
      _webApplyZoom(1, host);
    }
  });

  switchTab(portId);
  refreshSidebar();
  if (url) _webNavigate(url);
  else if (_webNav.idx >= 0 && _webNav.stack[_webNav.idx]) {
    // a475 会话恢复：无显式 URL 的首开回到上次离开的页面（栈已在模块
    // 加载时从 localStorage 恢复）
    _webNavigate(_webNav.stack[_webNav.idx]);
  }
  return conn;
}

function _webCur() {
  return connections[WEB_PORTID];
}
function _webNavigate(url) {
  const c = _webCur();
  if (!c || !url) return;
  const frame = c.wrap.querySelector('[data-web-frame]');
  const inp = c.wrap.querySelector('[data-web-input]');
  _webNav.stack = _webNav.stack.slice(0, _webNav.idx + 1);
  _webNav.stack.push(url);
  if (_webNav.stack.length > 50) _webNav.stack.shift();
  _webNav.idx = _webNav.stack.length - 1;
  _webSessionSave();                       // a475 会话恢复
  // a475：新导航唤醒休眠态 + 退出阅读态
  _webWake(c);
  if (_webUi.reader) _webReaderToggle(false);
  frame.src = url;
  inp.value = url;
  c.tab.querySelector('.label').textContent = _webShortUrl(url).slice(0, 24);
  _webApplyZoom(_webZoomFor(url), _webHostOf(url));   // a475 站点缩放记忆
  _webSyncUI();
}

// ---- a475：休眠/唤醒（Edge sleeping tabs 等价物）----
function _webSleep(c) {
  _webUi.sleeping = true;
  const ov = c.wrap.querySelector('[data-web-sleep]');
  const frame = c.wrap.querySelector('[data-web-frame]');
  if (ov) ov.style.display = 'flex';
  if (frame) frame.src = 'about:blank';    // 释放渲染进程（Chromium 回收）
}
function _webWake(c) {
  if (!_webUi.sleeping) return;
  _webUi.sleeping = false;
  c._hidSec = 0;
  const ov = c.wrap.querySelector('[data-web-sleep]');
  if (ov) ov.style.display = 'none';
}
// 切回网页 tab 自动唤醒（switchTab 后由面板自身的 display 变化可见）：
// 用 1s 轻探针——面板在场且 display 非 none 且休眠中 → 恢复 URL
setInterval(() => {
  const c = connections[WEB_PORTID];
  if (c && _webUi.sleeping && c.wrap.style.display !== 'none') {
    _webWake(c);
    const url = _webNav.stack[_webNav.idx];
    if (url) c.wrap.querySelector('[data-web-frame]').src = url;
  }
}, 1000);

// ---- a475：阅读模式（Reader）----
function _webReaderToggle(on) {
  const c = _webCur();
  if (!c) return;
  const rd = c.wrap.querySelector('[data-web-reader]');
  const frame = c.wrap.querySelector('[data-web-frame]');
  const btn = c.wrap.querySelector('[data-web="read"]');
  const url = _webNav.stack[_webNav.idx] || '';
  _webUi.reader = on;
  if (!on) {
    rd.style.display = 'none';
    frame.style.display = '';
    if (btn) btn.textContent = '☰ 阅读';
    return;
  }
  if (!url) return;
  rd.innerHTML = '<div class="web-reader-load">正在取正文…</div>';
  rd.style.display = '';
  frame.style.display = 'none';
  if (btn) btn.textContent = '▦ 网页';
  fetch('/api/web/fetch_text', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }) })
    .then(r => r.json()).then(j => {
      if (!_webUi.reader) return;          // 用户已切回网页视图——丢弃
      if (!j || !j.ok) {
        rd.innerHTML = '<div class="web-reader-err">取正文失败：'
          + esc(((j && j.err) || '未知')) + '——用 ↗ 浏览器打开</div>';
        return;
      }
      rd.innerHTML = '<div class="web-reader-head">' + esc(j.title || _webShortUrl(url))
        + (j.truncated ? ' <span class="web-reader-trunc">（超长已截断）</span>' : '')
        + '<span class="web-reader-url">' + esc(url) + '</span></div>'
        + '<div class="web-reader-body">' + esc(j.text).replace(/\n/g, '<br>') + '</div>';
    }).catch(e => {
      if (_webUi.reader)
        rd.innerHTML = '<div class="web-reader-err">取正文失败：' + esc(String(e)) + '</div>';
    });
}

// ---- a475：站点缩放记忆 ----
function _webHostOf(url) {
  try { return new URL(url).host; } catch (_) { return ''; }
}
function _webZoomFor(url) {
  const h = _webHostOf(url);
  try { return parseFloat(localStorage.getItem('web-zoom:' + h)) || 1; } catch (_) { return 1; }
}
function _webApplyZoom(z, host) {
  const c = connections[WEB_PORTID];
  if (!c) return;
  c._zoom = z;
  const frame = c.wrap.querySelector('[data-web-frame]');
  const rd = c.wrap.querySelector('[data-web-reader]');
  if (frame) frame.style.zoom = z;
  if (rd) rd.style.fontSize = (13 * z) + 'px';
  if (host) { try { localStorage.setItem('web-zoom:' + host, String(z)); } catch (_) {} }
}
function _webSyncUI() {
  const c = _webCur();
  if (!c) return;
  const url = _webNav.stack[_webNav.idx] || '';
  c.wrap.querySelector('[data-web="back"]').disabled = _webNav.idx <= 0;
  c.wrap.querySelector('[data-web="fwd"]').disabled = _webNav.idx >= _webNav.stack.length - 1;
  const favs = _webFavs();
  const starred = url && favs.some(f => f.url === url);
  const starBtn = c.wrap.querySelector('[data-web="star"]');
  starBtn.style.color = starred ? 'var(--accent)' : '';
  starBtn.title = starred ? '取消收藏当前页' : '收藏当前页';
}
function _webAct(act, wrap) {
  const c = _webCur();
  if (!c) return;
  const frame = c.wrap.querySelector('[data-web-frame]');
  const url = _webNav.stack[_webNav.idx] || '';
  if (act === 'back' && _webNav.idx > 0) {
    _webNav.idx--;
    frame.src = _webNav.stack[_webNav.idx];
    c.wrap.querySelector('[data-web-input]').value = _webNav.stack[_webNav.idx];
    c.tab.querySelector('.label').textContent = _webShortUrl(_webNav.stack[_webNav.idx]).slice(0, 24);
    _webSyncUI();
  } else if (act === 'fwd' && _webNav.idx < _webNav.stack.length - 1) {
    _webNav.idx++;
    frame.src = _webNav.stack[_webNav.idx];
    c.wrap.querySelector('[data-web-input]').value = _webNav.stack[_webNav.idx];
    c.tab.querySelector('.label').textContent = _webShortUrl(_webNav.stack[_webNav.idx]).slice(0, 24);
    _webSyncUI();
  } else if (act === 'reload' && url) {
    frame.src = url;
  } else if (act === 'read') {
    _webReaderToggle(!_webUi.reader);
  } else if (act === 'sys' && url) {
    fetch('/api/open_url', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }) }).catch(() => {});
  } else if (act === 'star' && url) {
    let favs = _webFavs();
    if (favs.some(f => f.url === url)) {
      favs = favs.filter(f => f.url !== url);
      _webFavsSave(favs);
      showBanner('已取消收藏', 1600);
    } else {
      // 标题拿不到（跨域）——先取页接口回传 title，失败用 URL 短化。
      // 审计修：取页最长 15s，窗口期连点会重复收藏——按钮禁用 + 写入按
      // url 去重 upsert 双保险
      const starBtn = c.wrap.querySelector('[data-web="star"]');
      starBtn.disabled = true;
      let title = _webShortUrl(url);
      fetch('/api/web/fetch_text', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }) })
        .then(r => r.json()).then(j => { if (j && j.ok && j.title) title = j.title; })
        .catch(() => {})
        .finally(() => {
          const favs = _webFavs().filter(f => f.url !== url);   // 去重 upsert
          _webFavsSave([{ url, title, ts: Date.now() }, ...favs]);
          starBtn.disabled = false;
          showBanner('已收藏：' + title, 2000);
          _webSyncUI();
        });
      return;
    }
    _webSyncUI();
  } else if (act === 'claude' && url) {
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
        const head = '[网页内容 ' + (j.title ? '「' + j.title + '」 ' : '') + url + ']'
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
  }
}

// 顶部地址栏 + tab 栏收藏星标（index.html 静态节点，此处绑定）
(function () {
  const bar = document.getElementById('topUrlBar');
  if (bar) bar.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing) return;
    e.preventDefault();
    const u = _webNormUrl(bar.value);
    if (!u) return;
    buildWebPanelTab(u);
    bar.blur();
  });
  const fav = document.getElementById('tabFavBtn');
  if (fav) fav.onclick = (e) => { e.stopPropagation(); _webFavMenu(fav); };
})();

function _webFavMenu(anchor) {
  const old = document.getElementById('webFavMenu');
  if (old) { old.remove(); return; }
  const favs = _webFavs();
  const cur = (_webNav.stack[_webNav.idx] || '');
  const list = document.createElement('div');
  list.id = 'webFavMenu';
  list.className = 'web-fav-menu';
  let html = '<div class="web-fav-title">收藏夹</div>';
  if (cur && connections[WEB_PORTID]) {
    const starred = favs.some(f => f.url === cur);
    html += `<div class="web-fav-cur" data-fav-act="${starred ? 'unstar' : 'star'}">`
      + (starred ? '★ 取消收藏当前网页' : '☆ 收藏当前网页') + '</div>';
  }
  html += favs.map((f, i) =>
    `<div class="web-fav-item" data-fav-i="${i}" title="${esc(f.url)}">`
    + `<span class="web-fav-name">${esc(f.title || _webShortUrl(f.url))}</span>`
    + `<span class="web-fav-x" data-fav-del="${i}" title="删除">✕</span></div>`).join('');
  if (!favs.length) html += '<div class="web-fav-empty">还没有收藏——网页 tab 里点 ★ 或地址栏打开后收藏</div>';
  list.innerHTML = html;
  document.body.appendChild(list);
  const r = anchor.getBoundingClientRect();
  list.style.right = Math.max(8, window.innerWidth - r.right - 4) + 'px';
  // 审计修：上方放不下（菜单高于锚点上沿距离）时改锚点下方开，且钳到视口
  const topUp = r.top - list.offsetHeight - 6;
  list.style.top = (topUp >= 8 ? topUp : Math.min(r.bottom + 6,
    Math.max(8, window.innerHeight - list.offsetHeight - 8))) + 'px';
  const close = (ev) => {
    if (!list.contains(ev.target) && ev.target !== anchor) {
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
      _webSyncUI();
      return;
    }
    const act = e.target.closest('[data-fav-act]');
    if (act) {
      e.stopPropagation();
      if (cur) _webAct('star');   // toggle：已收藏→取消，未收藏→收藏
      list.remove();
      return;
    }
    const item = e.target.closest('[data-fav-i]');
    if (item) {
      const f = _webFavs()[+item.dataset.favI];
      if (f) buildWebPanelTab(f.url);
      list.remove();
    }
  });
}
