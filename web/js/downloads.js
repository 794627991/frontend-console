// 下载中心面板（2026-11-24 用户令：普通网页标签页的下载也要有进度显示和完成提示）。
//
// 位置：挂在 body 上的浮层（与「日志流」同一类），贴着被点的那个「下载」按钮展开
// （2026-11-25 用户令：入口在网页标签页工具栏，密码钥匙右边）；按钮此刻不可见时
// （用户停在别的标签页，比如正看着 AI 会话）退回样式表里的默认位置（右上）。
// 数据来源两条：
//   · 打开面板、或 SSE 可能漏帧时，全量拉 POST /api/downloads/list；
//   · 之后靠 SSE 增量更新——sense.js 把 kind="download" 的帧转给 window.DL.onEvent。
// 下载一开始就自动把面板弹出来（进度条实时走）；用户手动关掉后这一轮不再抢，
// 结束时改用应用内横幅报结果。面板开着时用户直接看得到，不重复弹横幅。
// 这里只做「看」和「打开 / 取消 / 移除记录」：删除下载文件本身只能在
// 设置→数据目录→可清理项里（且只对默认下载目录开放）。
(function () {
  // 2026-11-25 用户令：入口从工具顶栏移进**网页标签页工具栏**（密码钥匙
  // 右边）。那个按钮是每个网页 tab 各自渲染的（web-panel.js），所以这里
  // 不再找全局 #btnDownloads，而是由点击方（_webAct 的 'dl' 分支）把
  // 自己那个按钮传进来——面板就贴着被点的那个按钮展开。
  let anchorBtn = null;                     // 面板当前的定位基准按钮

  let panel = null, bodyEl = null, dirEl = null;
  let rows = new Map();                     // id → 记录
  let dir = '', shown = false, timer = 0;
  let _autoOpened = false;                  // 本轮下载是否已自动弹过面板（用户关掉后不抢）

  const post = async (p, b) => (await fetch(p, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })).json();
  const fmt = (n) => {
    n = +n || 0;
    const units = ['B', 'KB', 'MB', 'GB'];
    let u = 0;
    while (n >= 1024 && u < 3) { n /= 1024; u++; }
    return u ? n.toFixed(n < 10 ? 2 : n < 100 ? 1 : 0) + ' ' + units[u] : n + ' B';
  };
  const busyCount = () => { let n = 0; rows.forEach((r) => { if (r.state === 'in_progress') n++; }); return n; };

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'dlPanel';
    panel.className = 'dl-panel';
    panel.innerHTML =
      '<div class="dl-head">' +
      '  <span class="dl-title">下载</span>' +
      '  <span class="dl-dir" data-dl="dir" title="下载目录（点击打开）。可在 设置 → 数据目录 里修改"></span>' +
      '  <button class="dl-btn" data-dl="clear" title="清掉已结束的记录（不删文件）">清空记录</button>' +
      '  <button class="dl-btn" data-dl="close" title="关闭（Esc）">✕</button>' +
      '</div>' +
      '<div class="dl-body"></div>' +
      '<div class="dl-foot">下载不弹保存窗口，文件直接存进下载目录。删除下载文件请到 设置 → 数据目录。</div>';
    document.body.appendChild(panel);
    bodyEl = panel.querySelector('.dl-body');
    dirEl = panel.querySelector('[data-dl="dir"]');

    panel.querySelector('[data-dl="close"]').onclick = hide;
    panel.querySelector('[data-dl="clear"]').onclick = async () => {
      await post('/api/downloads/forget', { all: true });
      await refresh();
    };
    dirEl.onclick = () => { if (dir) post('/api/downloads/open', { path: dir }); };
    // 点面板和按钮以外的地方就收起
    document.addEventListener('mousedown', (e) => {
      if (!shown) return;
      if (panel.contains(e.target)) return;
      if (anchorBtn && anchorBtn.contains(e.target)) return;
      hide();
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && shown) hide(); });
    // SSE 万一断了：面板开着且有进行中的下载时每 2 秒全量对一次账
    setInterval(() => { if (shown && busyCount()) refresh(); }, 2000);
    return panel;
  }

  // 每个网页 tab 各有一个下载按钮：角标挂在**所有**按钮上（用户可能正看着
  // 任意一个 tab，只有当前 tab 的徽标有意义——但都挂了也不碍事，数值一致）
  function _allBtns() {
    return Array.from(document.querySelectorAll('[data-web="dl"]'));
  }

  function _paintBadges(n) {
    _allBtns().forEach((b) => {
      let bd = b.querySelector('.dl-badge');
      if (!bd) {
        bd = document.createElement('span');
        bd.className = 'dl-badge';
        b.appendChild(bd);
      }
      bd.textContent = String(n);
      bd.style.display = n ? '' : 'none';
    });
    _allBtns().forEach((b) => {
      b.title = n ? '下载（' + n + ' 个进行中）' : '下载（进度 / 打开 / 取消）';
    });
  }

  function hide() {
    shown = false;
    if (panel) panel.style.display = 'none';
    _allBtns().forEach((b) => b.classList.remove('on'));
  }

  function _isVisible(b) {
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  // show() 返回「面板真的弹出来了」：一个下载按钮都没有（没开过网页标签页）时
  // 无处可弹，调用方不要把这一轮记成「已自动弹过」
  function show() {
    // 基准按钮随它所在的标签页一起没了（标签页被关）：重新挑一个，优先此刻看得见的
    if (!anchorBtn || !anchorBtn.isConnected) {
      anchorBtn = _allBtns().find(_isVisible) || _allBtns()[0] || null;
    }
    ensurePanel();
    if (!anchorBtn) return false;
    shown = true;
    panel.style.display = 'flex';
    // 面板贴着**被点的那个按钮**：左缘对齐按钮左缘、按钮下方 6px 展开
    // （2026-11-25 用户令：入口在网页工具栏密码钥匙右边，面板就跟它走）。
    // 按钮此刻不可见（用户停在别的标签页——AI 在会话里触发了下载，而用户正看着
    // 会话）：它的位置读出来是 0，照着摆会把面板盖在工具左上角。这时清掉行内
    // 定位，退回样式表里的默认位置（右上）
    const r = anchorBtn.getBoundingClientRect();
    if (_isVisible(anchorBtn)) {
      const w = Math.min(440, window.innerWidth - 40);
      const left = Math.max(8, Math.min(Math.round(r.left), window.innerWidth - w - 8));
      const top = Math.round(r.bottom + 6);
      panel.style.left = left + 'px';
      panel.style.right = 'auto';
      panel.style.top = top + 'px';
      panel.style.maxHeight = Math.max(160, window.innerHeight - top - 12) + 'px';
    } else {
      panel.style.left = panel.style.top = panel.style.right = panel.style.maxHeight = '';
    }
    anchorBtn.classList.add('on');
    refresh();
    return true;
  }

  // 工具栏点击入口（web-panel.js 的 _webAct 'dl' 分支调这里）
  function toggleFrom(b) {
    if (shown && anchorBtn === b) { hide(); return; }
    anchorBtn = b || anchorBtn;
    show();
    if (panel) render();
  }

  async function refresh() {
    try {
      const j = await post('/api/downloads/list', {});
      if (!j || !j.ok) return;
      dir = j.dir || '';
      rows = new Map((j.downloads || []).map((r) => [r.id, r]));
      render();
    } catch (_) { /* 后端不通：面板保持原样 */ }
  }

  function stateText(r) {
    if (r.state === 'completed') return '已完成 · ' + fmt(r.received);
    if (r.state === 'cancelled') return '已取消';
    if (r.state === 'interrupted') return '失败：' + (r.error || '原因未知');
    const got = fmt(r.received);
    if (!r.total) return '下载中 · 已收 ' + got;
    // 速度 = 已收 / 已用时间（ts 是后端记的开始时刻，同一台机器，时钟一致）
    const used = Date.now() / 1000 - (+r.ts || 0);
    const speed = used > 1 ? ' · ' + fmt(r.received / used) + '/s' : '';
    return '下载中 · ' + got + ' / ' + fmt(r.total) + speed;
  }

  function render() {
    if (!bodyEl) return;
    const n = busyCount();
    _paintBadges(n);              // 每个网页 tab 的下载按钮都挂角标
    dirEl.textContent = dir;
    dirEl.title = '下载目录：' + dir + '（点击打开）。可在 设置 → 数据目录 里修改';
    const list = Array.from(rows.values()).reverse();     // 最新的在前
    if (!list.length) {
      bodyEl.innerHTML = '<div class="dl-empty">还没有下载记录</div>';
      return;
    }
    bodyEl.innerHTML = list.map((r) => {
      const pct = r.state === 'completed' ? 100
        : (r.total ? Math.min(99, Math.floor(100 * r.received / r.total)) : 0);
      const barCls = 'dl-bar' + (r.state === 'completed' ? ' done' : r.state === 'interrupted' ? ' bad' : '');
      const acts = [];
      if (r.state === 'in_progress') {
        if (window.fcShell && typeof window.fcShell.dlCancel === 'function') acts.push('cancel');
      } else {
        acts.push('forget');
        if (r.state === 'completed') acts.unshift('reveal', 'open');
      }
      return '<div class="dl-row" data-id="' + esc(r.id) + '">' +
        '<div class="dl-r1"><span class="dl-name" title="' + esc(r.path || r.filename) + '">' + esc(r.filename) + '</span>' +
        (r.state === 'in_progress' && r.total ? '<span class="dl-size">' + pct + '%</span>' : '') +
        '</div>' +
        '<div class="' + barCls + '"><i style="width:' + pct + '%"></i></div>' +
        '<div class="dl-r2"><span class="dl-state' + (r.state === 'interrupted' ? ' bad' : '') + '" title="' +
          esc(stateText(r)) + '">' + esc(stateText(r)) + '</span>' +
        acts.map((a) => '<button class="dl-btn' + (a === 'cancel' ? ' warn' : '') + '" data-act="' + a + '">' +
          ({ cancel: '取消', open: '打开', reveal: '所在文件夹', forget: '移除' })[a] + '</button>').join('') +
        '</div></div>';
    }).join('');
  }

  async function act(e) {
    const b = e.target.closest('[data-act]');
    const row = e.target.closest('.dl-row');
    if (!b || !row) return;
    const id = row.dataset.id;
    const r = rows.get(id) || {};
    const a = b.dataset.act;
    if (a === 'cancel') {
      if (window.fcShell && typeof window.fcShell.dlCancel === 'function') {
        const ok = await window.fcShell.dlCancel(id);
        if (!ok) showBanner('没能取消：这个下载可能已经结束了', 3000, true);
      }
    } else if (a === 'open' || a === 'reveal') {
      const j = await post('/api/downloads/open', { path: r.path, reveal: a === 'reveal' });
      if (!j || !j.ok) showBanner('打不开：' + ((j && j.err) || ''), 3200, true);
    } else if (a === 'forget') {
      rows.delete(id);
      await post('/api/downloads/forget', { id });
      render();
    }
  }

  function onEvent(item) {
    if (!item || item.kind !== 'download') return;
    ensurePanel();                        // 用户可能从没点过按钮：角标得先有地方显示
    const r = { id: item.id, filename: item.filename, state: item.state, received: item.received,
                total: item.total, path: item.path, error: item.error, ts: item.ts, source: item.source };
    rows.set(r.id, r);
    // 2026-11-25 用户实锤「下载时没有弹出下载进度」：原实现只在 done 且面板
    // 关着时弹横幅，下载**过程中**什么都不弹——用户看不到进度，以为没生效
    // （对照 WebView2/浏览器：一开始下载就出进度条）。
    // 改成：每笔下载 first 见到（started）就自动把面板弹出来，进度条实时走；
    // 用户手动关掉面板后不再抢——用 _autoOpened 记「这一轮已经自动开过」，
    // 避免第二个下载又把用户刚关掉的面板顶出来。
    if (item.event === 'started') {
      if (!shown && !_autoOpened) {
        // 只有真弹出来了才记「这一轮已自动开过」：一个下载按钮都没有时 show() 弹不出来，
        // 记了的话这一轮里用户打开网页标签页后它也不会再自动弹
        _autoOpened = show();
      }
    } else if (item.event === 'done') {
      if (!busyCount()) _autoOpened = false;   // 这一波都结束了：下一个下载可以再自动开
      if (!shown) {
        // 面板没开着：用横幅告诉用户结果（开着的时候他直接看得到）。
        // 入口在网页标签页工具栏（密码钥匙右边），2026-11-25 起不在右上角了
        const where = '，网页标签页工具栏的「下载」可打开';
        if (r.state === 'completed') showBanner('下载完成：' + r.filename + '（' + fmt(r.received) + '）' + where, 4200);
        else if (r.state === 'interrupted') showBanner('下载失败：' + r.filename + '（' + (r.error || '原因未知') + '）', 6000, true);
        else showBanner('已取消下载：' + r.filename, 3000);
      }
    }
    if (panel) render();
  }

  document.body.addEventListener('click', act);
  window.DL = { onEvent, refresh, toggleFrom };
  refresh();                              // 页面重载后把后端已有的记录拉回来
})();
