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
// ============================================================
const WEB_PORTID = 'web:panel';
const _webNav = { stack: [], idx: -1 };    // 只记本面板发起的导航

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
        <button class="btn ghost" data-web="claude" title="服务端取本页正文（无登录态页面）填入 Claude 输入框——带登录态的页面请让 AI 用 devtools 工具读">发给 Claude</button>
        <button class="btn ghost" data-web="sys" title="X-Frame-Options 拒嵌等场景：系统浏览器打开">↗ 浏览器</button>
      </div>
      <div class="web-body"><iframe class="web-frame" data-web-frame
        referrerpolicy="no-referrer-when-downgrade"></iframe></div>
    </div>`;
  termArea.appendChild(wrap);
  const conn = { portId, meta: { kind: 'web', label: '网页' }, tab, wrap };
  connections[portId] = conn;

  const $w = (s) => wrap.querySelector(s);
  const frame = $w('[data-web-frame]');
  const urlInput = $w('[data-web-input]');
  urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _webNavigate(_webNormUrl(urlInput.value)); }
  });
  wrap.querySelectorAll('[data-web]').forEach(b => b.onclick = () => _webAct(b.dataset.web, wrap));

  switchTab(portId);
  refreshSidebar();
  if (url) _webNavigate(url);
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
  frame.src = url;
  inp.value = url;
  c.tab.querySelector('.label').textContent = _webShortUrl(url).slice(0, 24);
  _webSyncUI();
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
      // 标题拿不到（跨域）——先取页接口回传 title，失败用 URL 短化
      let title = _webShortUrl(url);
      fetch('/api/web/fetch_text', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }) })
        .then(r => r.json()).then(j => { if (j && j.ok && j.title) title = j.title; })
        .catch(() => {})
        .finally(() => {
          _webFavsSave([{ url, title, ts: Date.now() }, ..._webFavs()]);
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
    if (e.key !== 'Enter') return;
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
  list.style.top = (r.top - list.offsetHeight - 6) + 'px';
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
