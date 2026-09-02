const HIST_ROW_H = 18;
const HIST_BUF = 10;
const HIST_PAGE = 200;
const HIST_CACHE_MAX = 5000;
const MAX_SCROLL_H = 10000000;

// 拖拽日志文件到窗口任意位置打开（含超大文件，走 G 级虚拟列表）
let _dragOverlay = null;
let _dragCounter = 0;
function showDragOverlay(show) {
  if (show && !_dragOverlay) {
    _dragOverlay = document.createElement('div');
    _dragOverlay.id = 'dragOverlay';
    _dragOverlay.textContent = '📄 松开以打开日志';
    document.body.appendChild(_dragOverlay);
  } else if (!show && _dragOverlay) {
    _dragOverlay.remove(); _dragOverlay = null;
  }
}
document.body.addEventListener('dragenter', e => {
  e.preventDefault();
  if (e.dataTransfer && e.dataTransfer.types && e.dataTransfer.types.includes('Files')) {
    _dragCounter++; showDragOverlay(true);
  }
});
document.body.addEventListener('dragover', e => { e.preventDefault(); });
document.body.addEventListener('dragleave', e => {
  e.preventDefault();
  _dragCounter--;
  if (_dragCounter <= 0) { _dragCounter = 0; showDragOverlay(false); }
});
// drop 事件由 pywebview 原生处理（main.py 注册，能拿到 File.pywebviewFullPath 绝对路径），
// 回调里 evaluate_js 调 buildLogViewer。这里仅 preventDefault（阻止 WebView2 导航到文件）
// 并隐藏遮罩——preventDefault 不影响 pywebview 的 drop_handler 触发。
document.body.addEventListener('drop', e => {
  e.preventDefault();
  _dragCounter = 0; showDragOverlay(false);
});

// 同步已打开日志列表到后端（打开/关闭日志 tab 时调用，让 MCP/AI 能感知）
function syncOpenLogs() {
  const logs = [];
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'log') {
      logs.push({
        name: c.meta.label,
        path: c.meta.path,
        port_id: pid,
        total: c.logState ? c.logState.total : 0,
      });
    }
  }
  try { fetch('/api/ai/open_logs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({logs})}); } catch(e) {}
}

// 构建日志查看 tab（类似 buildTerminal，但用虚拟列表替代 xterm）
function buildLogViewer(path) {
  const name = path.split(/[\\\/]/).pop();
  const portId = 'log:' + name + ':' + Date.now();
  // 若已打开同名日志，切过去
  for (const pid in connections) {
    if (connections[pid].meta && connections[pid].meta.kind === 'log' && connections[pid].meta.path === path) {
      switchTab(pid); return;
    }
  }
  // 建 tab
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led" style="color:var(--accent)">📜</span><span class="label">${esc(name)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeLogViewer(portId); return; } switchTab(portId); };
  // 建 wrap（.term-area，内含日志查看器）
  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="log-viewer">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-lv-action="search">🔍 搜索</button>
        <button class="lv-btn" data-lv-action="top" title="跳到开头">⤒ 顶部</button>
        <button class="lv-btn" data-lv-action="bottom" title="跳到末尾">⤓ 底部</button>
        <span class="lv-info" data-lv-info></span>
      </div>
      <div class="log-viewer-top">
        <div class="vlist"><div class="vlist-inner"></div></div>
      </div>
      <div class="log-search-splitter"></div>
      <div class="log-search-pane">
        <div class="log-search-head">
          <input type="text" class="log-search-input" placeholder="查找关键字…（回车搜索，再按回车跳下一个）" autocomplete="off">
          <button class="btn ghost log-search-btn">查找全部</button>
          <span class="log-search-count"></span>
          <button class="btn ghost log-search-collapse" title="折叠分栏">▾</button>
        </div>
        <div class="log-search-results"></div>
      </div>
      <div class="log-viewer-status">正在索引…</div>
    </div>`;
  // 移除 empty-state，插 tab + wrap
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  // tab 插到 .tab-bar-actions 之前（按钮组左侧）——appendChild 会跑到按钮右边
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  termArea.appendChild(wrap);
  // conn 对象
  const conn = {
    portId,  // 用于 await 后校验当前 conn 是否仍存活（防止用户在索引期间关闭/切换日志 tab）
    meta: { kind: 'log', label: name, path },
    tab, wrap,
    vlist: wrap.querySelector('.vlist'),
    vlistInner: wrap.querySelector('.vlist-inner'),
    statusEl: wrap.querySelector('.log-viewer-status'),
    infoEl: wrap.querySelector('[data-lv-info]'),
    searchPane: wrap.querySelector('.log-search-pane'),
    searchInput: wrap.querySelector('.log-search-input'),
    searchResults: wrap.querySelector('.log-search-results'),
    searchCount: wrap.querySelector('.log-search-count'),
    logState: {
      name: path, total: 0, scaled: false, rows: new Map(),
      renderedStart: -1, renderedEnd: -1, renderSeq: 0,
      searchQ: '', searchResults: [], searchIdx: 0,
      searchNextOffset: -1, searchLoadingMore: false, curRow: -1,
    },
  };
  connections[portId] = conn;
  // 工具栏按钮
  wrap.querySelectorAll('.lv-btn').forEach(btn => {
    btn.onclick = () => {
      const act = btn.dataset.lvAction;
      if (act === 'search') { toggleLogSearchPane(conn, true); conn.searchInput.focus(); conn.searchInput.select(); }
      else if (act === 'top') { conn.vlist.scrollTop = 0; }
      else if (act === 'bottom') { conn.vlist.scrollTop = conn.vlistInner.offsetHeight; }
    };
  });
  // 滚动事件（节流，绑定到本 conn 的 vlist）
  let scrollTimer = null;
  conn.vlist.addEventListener('scroll', () => {
    if (scrollTimer) return;
    scrollTimer = setTimeout(() => { scrollTimer = null; renderLogSlice(conn); }, 50);
  });
  // 查找分栏：拖分隔条调高度
  initLogSplitter(conn);
  // 查找全部按钮
  wrap.querySelector('.log-search-btn').onclick = () => doLogSearch(conn);
  // 结果列表滚动到底 → 续载下 500 条命中
  conn.searchResults.addEventListener('scroll', () => {
    const el = conn.searchResults;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) loadMoreLogSearch(conn);
  });
  wrap.querySelector('.log-search-input').addEventListener('keydown', e => { if (e.key === 'Enter') doLogSearch(conn); });
  // 输入清空时去掉主视图关键字染色（保持与搜索状态一致）
  wrap.querySelector('.log-search-input').addEventListener('input', e => {
    if (!e.target.value.trim() && conn.logState.searchQ) {
      conn.logState.searchQ = '';
      conn.logState.renderedStart = -1; conn.logState.renderedEnd = -1;
      renderLogSlice(conn);
    }
  });
  wrap.querySelector('.log-search-collapse').onclick = () => {
    const isShown = conn.searchPane.style.display !== 'none';
    toggleLogSearchPane(conn, !isShown);
  };
  // 加载日志
  openLogInViewer(conn);
  switchTab(portId);
  refreshSidebar();
  syncOpenLogs();  // 通知后端已打开此日志（total 索引完后再同步一次）
}

// 打开日志：建索引 + 初始化虚拟列表
async function openLogInViewer(conn) {
  const ls = conn.logState;
  ls.rows = new Map();
  ls.renderedStart = -1; ls.renderedEnd = -1;
  ls.searchQ = ''; ls.searchResults = []; ls.searchIdx = 0;
  ls.searchNextOffset = -1; ls.curRow = -1;
  conn.searchInput.value = '';
  conn.vlist.scrollTop = 0;
  conn.statusEl.textContent = '正在索引…';
  try {
    const r = await fetch('/api/log_count?name=' + encodeURIComponent(ls.name));
    const j = await r.json();
    // 索引期间用户可能已关闭此日志 tab 或切到别的 tab，校验当前 conn 仍存活
    if (connections[conn.portId] !== conn) return;
    if (!j.ok) { conn.statusEl.textContent = '错误：' + (j.err || ''); return; }
    ls.total = j.total;
    const naturalH = ls.total * HIST_ROW_H;
    ls.scaled = naturalH > MAX_SCROLL_H;
    conn.vlistInner.innerHTML = '';
    conn.vlistInner.style.height = Math.min(naturalH, MAX_SCROLL_H) + 'px';
    conn.statusEl.textContent = `共 ${ls.total.toLocaleString()} 行` + (ls.scaled ? ' · 缩放模式' : '');
    renderLogSlice(conn);
    syncOpenLogs();  // 索引完成，带 total 再同步一次
  } catch(e) { if (connections[conn.portId] === conn) conn.statusEl.textContent = '加载失败：' + e; }
}

// scrollTop → 行号（缩放末页可达映射）
function logScrollToRow(conn, scrollTop) {
  const ls = conn.logState;
  if (!ls.scaled) return Math.floor(scrollTop / HIST_ROW_H);
  const innerH = Math.min(ls.total * HIST_ROW_H, MAX_SCROLL_H);
  const viewH = conn.vlist.clientHeight;
  const maxScroll = innerH - viewH;
  const maxRow = Math.max(0, ls.total - Math.ceil(viewH / HIST_ROW_H));
  if (maxScroll <= 0) return 0;
  return Math.min(maxRow, Math.floor(scrollTop / maxScroll * maxRow));
}
// 行号 → scrollTop
function logRowToScroll(conn, row) {
  const ls = conn.logState;
  if (!ls.scaled) return row * HIST_ROW_H;
  const innerH = Math.min(ls.total * HIST_ROW_H, MAX_SCROLL_H);
  const viewH = conn.vlist.clientHeight;
  const maxScroll = innerH - viewH;
  const maxRow = Math.max(0, ls.total - Math.ceil(viewH / HIST_ROW_H));
  if (maxRow <= 0) return 0;
  return Math.floor(row / maxRow * maxScroll);
}

// 确保区间已加载
async function ensureLogRange(conn, start, end) {
  const ls = conn.logState;
  start = Math.max(0, start); end = Math.min(ls.total, end);
  const missing = [];
  let i = start;
  while (i < end) {
    if (ls.rows.has(i)) { i++; continue; }
    let j = i;
    while (j < end && !ls.rows.has(j)) j++;
    missing.push([i, j]); i = j;
  }
  const fetches = [];
  for (const [s, e] of missing) {
    for (let k = s; k < e; k += HIST_PAGE) {
      const off = k, lim = Math.min(HIST_PAGE, e - k);
      fetches.push(
        fetch('/api/log_page?name=' + encodeURIComponent(ls.name) + '&offset=' + off + '&limit=' + lim)
          .then(r => r.json()).then(j => {
            if (j.ok) (j.lines || []).forEach((l, idx) => ls.rows.set(off + idx, l));
          }).catch(() => {})
      );
    }
  }
  if (fetches.length) await Promise.all(fetches);
}

// 行文本转 HTML：esc 后对当前搜索关键字加 <mark> 高亮（大小写不敏感）
function hlSearchText(text, q) {
  if (!q) return esc(text);
  // esc 后再匹配：q 也 esc，保持与 esc 后文本同一坐标系
  const eText = esc(text), eQ = esc(q);
  const lowText = eText.toLowerCase(), lowQ = eQ.toLowerCase();
  if (!lowQ) return eText;
  let out = '', pos = 0, i;
  while ((i = lowText.indexOf(lowQ, pos)) !== -1) {
    out += eText.slice(pos, i) + '<mark class="hl-hit">' + eText.slice(i, i + eQ.length) + '</mark>';
    pos = i + eQ.length;
  }
  return out + eText.slice(pos);
}

// 渲染可视区切片
async function renderLogSlice(conn) {
  const ls = conn.logState;
  if (!ls.name || !ls.total) return;
  const vlist = conn.vlist, inner = conn.vlistInner;
  const scrollTop = vlist.scrollTop;
  const viewH = vlist.clientHeight;
  const startRow = Math.max(0, logScrollToRow(conn, scrollTop));
  const viewportRows = Math.ceil(viewH / HIST_ROW_H);
  const renderStart = startRow;
  const endRow = Math.min(ls.total, startRow + viewportRows + HIST_BUF);
  if (renderStart === ls.renderedStart && endRow === ls.renderedEnd) return;
  const mySeq = ++ls.renderSeq;
  await ensureLogRange(conn, renderStart, endRow);
  if (mySeq !== ls.renderSeq) return;
  let vp = inner.querySelector('.vlist-viewport');
  if (!vp) { vp = document.createElement('div'); vp.className = 'vlist-viewport'; inner.appendChild(vp); }
  vp.style.top = scrollTop + 'px';
  let html = '';
  for (let r = renderStart; r < endRow; r++) {
    const l = ls.rows.get(r);
    if (!l) continue;
    const top = (r - renderStart) * HIST_ROW_H;
    const kc = l.tag === 'error' ? 'kw-error' : l.tag === 'warning' ? 'kw-warning' : (l.tag === 'info' || l.tag === 'comment') ? 'kw-info' : '';
    // 搜索关键字染色（ls.searchQ 存在时命中词 <mark>）；当前选中命中行额外高亮（ls.curRow）
    const text = hlSearchText(l.text || '', ls.searchQ || '');
    // 工具日志自带时间戳（外部纯文本 ts=0 不显示）
    const tsHtml = l.ts ? `<span class="hts">${fmtTs(l.ts)}</span>` : '';
    html += `<div class="hline ${kc}${r === ls.curRow ? ' cur' : ''}" style="top:${top}px" data-row="${r}" title="${esc(l.text || '')}"><span class="hrow">${r}</span>${tsHtml}<span class="htag">${esc(l.tag||'')}</span>${text}</div>`;
  }
  vp.innerHTML = html;
  ls.renderedStart = renderStart; ls.renderedEnd = endRow;
  if (ls.rows.size > HIST_CACHE_MAX) {
    const keepFrom = renderStart - HIST_CACHE_MAX / 2, keepTo = endRow + HIST_CACHE_MAX / 2;
    for (const k of ls.rows.keys()) { if (k < keepFrom || k > keepTo) ls.rows.delete(k); }
  }
  conn.statusEl.textContent = `共 ${ls.total.toLocaleString()} 行 · 显示 ${renderStart}-${endRow-1}` + (ls.scaled ? ' · 缩放' : '');
}

// 跳到日志某行（居中）。curRow 指定时同时高亮该行（搜索结果点击/跳转用）
function jumpToLogRow(conn, row, curRow) {
  const ls = conn.logState;
  const innerH = Math.min(ls.total * HIST_ROW_H, MAX_SCROLL_H);
  const viewH = conn.vlist.clientHeight;
  const viewportRows = Math.ceil(viewH / HIST_ROW_H);
  const startRow = Math.max(0, Math.min(ls.total - viewportRows, row - Math.floor(viewportRows / 2)));
  conn.vlist.scrollTop = Math.max(0, Math.min(innerH - viewH, logRowToScroll(conn, startRow)));
  ls.renderedStart = -1; ls.renderedEnd = -1;
  if (typeof curRow === 'number' && curRow >= 0) {
    ls.curRow = curRow;
  }
  renderLogSlice(conn);
}

// 查找全部 → 底部分栏列命中行（滚动到底自动续载下 500 条）
async function doLogSearch(conn) {
  const q = conn.searchInput.value.trim();
  const ls = conn.logState;
  if (!q || !ls.name) return;
  // 已有结果且查询未变 → 跳转下一个
  if (ls.searchResults.length && ls.searchQ === q) {
    ls.searchIdx = (ls.searchIdx + 1) % ls.searchResults.length;
    jumpToLogRow(conn, ls.searchResults[ls.searchIdx], ls.searchResults[ls.searchIdx]);
    highlightLogSearchResult(conn, ls.searchIdx);
    return;
  }
  toggleLogSearchPane(conn, true);
  conn.searchCount.innerHTML = '<span class="spin">✳</span> 搜索中…';
  try {
    const r = await fetch('/api/log_search?name=' + encodeURIComponent(ls.name) + '&q=' + encodeURIComponent(q) + '&limit=500');
    const j = await r.json();
    if (!j.ok) { conn.searchCount.textContent = '失败：' + (j.err || ''); return; }
    ls.searchResults = (j.lines || []).map(l => l.row);
    ls.searchQ = q; ls.searchIdx = 0;
    ls.searchNextOffset = (typeof j.next_offset === 'number') ? j.next_offset : -1;
    ls.searchTotal = (typeof j.total === 'number') ? j.total : ls.searchResults.length;
    // total 是后端扫全量的真实命中数；列表初始显示前 500 条，滚动到底续载
    const total = ls.searchTotal;
    conn.searchResults.innerHTML = (j.lines || []).map((l, idx) => {
      const kc = l.tag === 'error' ? 'kw-error' : l.tag === 'warning' ? 'kw-warning' : (l.tag === 'info' || l.tag === 'comment') ? 'kw-info' : '';
      // 结果列表里关键字也染色（与主视图一致）
      const text = hlSearchText(l.text || '', q);
      const tsHtml = l.ts ? `<span class="hts">${fmtTs(l.ts)}</span>` : '';
      return `<div class="hline ${kc}" data-row="${l.row}" data-idx="${idx}" title="${esc(l.text || '')}"><span class="hrow">${l.row}</span>${tsHtml}<span class="htag">${esc(l.tag||'')}</span>${text}</div>`;
    }).join('') + (ls.searchNextOffset >= 0
      ? `<div class="search-more" data-more>已显示前 ${ls.searchResults.length} 条（共 ${total.toLocaleString()} 处命中），往下滚动加载更多…</div>`
      : '');
    bindLogSearchResultClicks(conn);
    conn.searchCount.textContent = `命中 ${total.toLocaleString()} 处`;
    // 主视图从此带关键字染色：强制重渲染当前可视区
    ls.renderedStart = -1; ls.renderedEnd = -1;
    if (ls.searchResults.length) { jumpToLogRow(conn, ls.searchResults[0], ls.searchResults[0]); highlightLogSearchResult(conn, 0); }
    else renderLogSlice(conn);
  } catch(e) { conn.searchCount.textContent = '失败：' + e; }
}
// 结果行点击事件统一绑定（初始/续载后复用，dataset.bound 防重复）
function bindLogSearchResultClicks(conn) {
  const ls = conn.logState;
  conn.searchResults.querySelectorAll('.hline').forEach(el => {
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.onclick = () => {
      const idx = +el.dataset.idx;
      ls.searchIdx = idx;
      jumpToLogRow(conn, +el.dataset.row, +el.dataset.row);
      highlightLogSearchResult(conn, idx);
    };
  });
}
// 滚动到底 → 用 next_offset 续载下 500 条命中
async function loadMoreLogSearch(conn) {
  const ls = conn.logState;
  if (ls.searchLoadingMore || ls.searchNextOffset < 0 || !ls.searchQ) return;
  ls.searchLoadingMore = true;
  try {
    const r = await fetch('/api/log_search?name=' + encodeURIComponent(ls.name) + '&q=' + encodeURIComponent(ls.searchQ) + '&limit=500&offset=' + ls.searchNextOffset);
    const j = await r.json();
    if (!j.ok) return;
    const more = j.lines || [];
    ls.searchNextOffset = (typeof j.next_offset === 'number') ? j.next_offset : -1;
    if (!more.length) { ls.searchNextOffset = -1; return; }
    const q = ls.searchQ;
    const html = more.map((l, idx) => {
      const rIdx = ls.searchResults.length + idx;
      const kc = l.tag === 'error' ? 'kw-error' : l.tag === 'warning' ? 'kw-warning' : (l.tag === 'info' || l.tag === 'comment') ? 'kw-info' : '';
      const text = hlSearchText(l.text || '', q);
      const tsHtml = l.ts ? `<span class="hts">${fmtTs(l.ts)}</span>` : '';
      return `<div class="hline ${kc}" data-row="${l.row}" data-idx="${rIdx}" title="${esc(l.text || '')}"><span class="hrow">${l.row}</span>${tsHtml}<span class="htag">${esc(l.tag||'')}</span>${text}</div>`;
    }).join('');
    ls.searchResults.push(...more.map(l => l.row));
    const tail = conn.searchResults.querySelector('[data-more]');
    if (tail) tail.remove();
    conn.searchResults.insertAdjacentHTML('beforeend', html + (ls.searchNextOffset >= 0
      ? `<div class="search-more" data-more>已显示 ${ls.searchResults.length} 条（共 ${(ls.searchTotal||ls.searchResults.length).toLocaleString()} 处命中），往下滚动加载更多…</div>`
      : ''));
    bindLogSearchResultClicks(conn);
  } catch(e) {
  } finally {
    ls.searchLoadingMore = false;
  }
}
function highlightLogSearchResult(conn, idx) {
  conn.searchResults.querySelectorAll('.hline').forEach((el, i) => el.classList.toggle('active', i === idx));
}
function toggleLogSearchPane(conn, show) {
  conn.searchPane.style.display = show ? 'flex' : 'none';
  conn.wrap.querySelector('.log-search-splitter').style.display = show ? 'block' : 'none';
  // 折叠按钮提示随状态变（▾ 折叠 / ▴ 展开）
  const collapseBtn = conn.wrap.querySelector('.log-search-collapse');
  if (collapseBtn) collapseBtn.textContent = show ? '▾' : '▴';
  if (show) { conn.searchInput.focus(); }
}

// 拖分隔条调分栏高度
function initLogSplitter(conn) {
  const splitter = conn.wrap.querySelector('.log-search-splitter');
  const pane = conn.searchPane;
  const top = conn.wrap.querySelector('.log-viewer-top');
  let dragging = false, startY = 0, startH = 0;
  splitter.addEventListener('mousedown', e => {
    dragging = true; startY = e.clientY; startH = pane.offsetHeight;
    document.body.style.cursor = 'row-resize'; e.preventDefault();
  });
  // 存到 conn 以便 closeLogViewer 移除，避免 document 级监听器泄漏
  conn._splitMove = e => {
    if (!dragging) return;
    const dh = e.clientY - startY;
    const newH = Math.max(60, Math.min(startH - dh, conn.wrap.clientHeight - 100));
    pane.style.height = newH + 'px';
    top.style.flex = '1';
  };
  conn._splitUp = () => {
    if (dragging) { dragging = false; document.body.style.cursor = ''; renderLogSlice(conn); }
  };
  document.addEventListener('mousemove', conn._splitMove);
  document.addEventListener('mouseup', conn._splitUp);
}

// 关闭日志 tab
function closeLogViewer(portId) {
  const conn = connections[portId];
  if (conn) {
    // 移除 document 级拖拽监听器，避免泄漏
    if (conn._splitMove) document.removeEventListener('mousemove', conn._splitMove);
    if (conn._splitUp) document.removeEventListener('mouseup', conn._splitUp);
    conn.tab.remove(); conn.wrap.remove(); delete connections[portId];
  }
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0;
  });
  if (remaining.length) switchTab(remaining[0]);
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon">📡</div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();
  refreshGlobalStatus();
  syncOpenLogs();  // 通知后端此日志已关闭
}

// ============================================================
// ============================================================
// TFTP 面板（侧边栏底部）
// ============================================================
