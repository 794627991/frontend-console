// 下载中心面板（2026-11-24 用户令：普通网页标签页的下载也要有进度显示和完成提示）。
//
// 位置：挂在 body 上的浮层（与「日志流」同一类），右缘对齐顶栏的「下载」按钮。
// 数据来源两条：
//   · 打开面板、或 SSE 可能漏帧时，全量拉 POST /api/downloads/list；
//   · 之后靠 SSE 增量更新——sense.js 把 kind="download" 的帧转给 window.DL.onEvent。
// 面板没开着时，下载完成 / 失败 / 取消用应用内横幅提示；开着时用户直接看得到，不重复弹。
// 这里只做「看」和「打开 / 取消 / 移除记录」：删除下载文件本身只能在
// 设置→数据目录→可清理项里（且只对默认下载目录开放）。
(function () {
  const btn = document.getElementById('btnDownloads');
  if (!btn) return;                         // 页面结构不对就不挂

  let panel = null, bodyEl = null, dirEl = null, badge = null;
  let rows = new Map();                     // id → 记录
  let dir = '', shown = false, timer = 0;

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
    badge = document.createElement('span');
    badge.className = 'dl-badge';
    badge.style.display = 'none';
    btn.appendChild(badge);                 // 按钮需 position:relative（见样式）

    panel.querySelector('[data-dl="close"]').onclick = hide;
    panel.querySelector('[data-dl="clear"]').onclick = async () => {
      await post('/api/downloads/forget', { all: true });
      await refresh();
    };
    dirEl.onclick = () => { if (dir) post('/api/downloads/open', { path: dir }); };
    // 点面板和按钮以外的地方就收起
    document.addEventListener('mousedown', (e) => {
      if (!shown) return;
      if (panel.contains(e.target) || btn.contains(e.target)) return;
      hide();
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && shown) hide(); });
    // SSE 万一断了：面板开着且有进行中的下载时每 2 秒全量对一次账
    setInterval(() => { if (shown && busyCount()) refresh(); }, 2000);
    return panel;
  }

  function hide() {
    shown = false;
    if (panel) panel.style.display = 'none';
    btn.classList.remove('on');
  }

  function show() {
    ensurePanel();
    shown = true;
    panel.style.display = 'flex';
    // 右缘对齐按钮的右缘；按钮被挤到窗口外时退回一个安全位置
    const r = btn.getBoundingClientRect();
    panel.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + 'px';
    btn.classList.add('on');
    refresh();
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
    badge.textContent = String(n);
    badge.style.display = n ? '' : 'none';
    btn.title = n ? '下载（' + n + ' 个进行中）' : '下载';
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
    if (item.event === 'done' && !shown) {
      // 面板没开着：用横幅告诉用户结果（开着的时候他直接看得到）
      if (r.state === 'completed') showBanner('下载完成：' + r.filename + '（' + fmt(r.received) + '），右上角「下载」可打开', 4200);
      else if (r.state === 'interrupted') showBanner('下载失败：' + r.filename + '（' + (r.error || '原因未知') + '）', 6000, true);
      else showBanner('已取消下载：' + r.filename, 3000);
    }
    if (panel) render();
  }

  btn.onclick = () => { if (shown) hide(); else show(); };
  document.body.addEventListener('click', act);
  window.DL = { onEvent, refresh };
  refresh();                              // 页面重载后把后端已有的记录拉回来
})();
