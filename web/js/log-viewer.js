const HIST_ROW_H = 18;
const HIST_BUF = 10;
const HIST_PAGE = 200;
const HIST_CACHE_MAX = 5000;
const MAX_SCROLL_H = 10000000;
const RES_ROW_H = 20;   // 搜索结果列表虚拟行高（单行省略，title 看全文）
// 结果列表滚动高度上限：命中 × 20px 超 Chrome ~33.5M px 时浏览器会钳制滚动条，
// 尾部命中滚不到、跳转落错位。超限时改用线性缩放映射（同主视图 MAX_SCROLL_H 方案），
// 滚动条始终可达任意命中，无失真。
const RES_MAX_H = 10000000;
// scrollTop → 命中序号（超限缩放：末页可达映射，同 logScrollToRow 语义）
function resScrollToHit(conn, scrollTop) {
  const ls = conn.logState;
  const naturalH = ls.searchTotal * RES_ROW_H;
  if (naturalH <= RES_MAX_H) return Math.floor(scrollTop / RES_ROW_H);
  const innerH = RES_MAX_H;
  const viewH = conn.searchResults.clientHeight;
  const maxScroll = innerH - viewH;
  const maxHit = Math.max(0, ls.searchTotal - Math.ceil(viewH / RES_ROW_H));
  if (maxScroll <= 0) return 0;
  return Math.min(maxHit, Math.floor(scrollTop / maxScroll * maxHit));
}
// 命中序号 → scrollTop（缩放模式末尾 1 屏共享底部：序号钳到 maxHit 再映射，防越界）
function resHitToScroll(conn, hit) {
  const ls = conn.logState;
  const naturalH = ls.searchTotal * RES_ROW_H;
  if (naturalH <= RES_MAX_H) return hit * RES_ROW_H;
  const viewH = conn.searchResults.clientHeight;
  const maxScroll = RES_MAX_H - viewH;
  const maxHit = Math.max(0, ls.searchTotal - Math.ceil(viewH / RES_ROW_H));
  const h = Math.min(hit, maxHit);
  if (maxHit <= 0) return 0;
  return Math.floor(h / maxHit * maxScroll);
}

// 拖拽日志文件到窗口任意位置打开（含超大文件，走 G 级虚拟列表）
// 遮罩文案按当前活跃 tab 分发：claude/note 有各自的落点行为，不该说"打开日志"
let _dragOverlay = null;
let _dragCounter = 0;
function _dragOverlayText() {
  const c = activePortId && connections[activePortId];
  const kind = c && c.meta && c.meta.kind;
  if (kind === 'claude') return '<span class="claude-ico"></span> 松开把路径发给 Claude';
  // v2.2.1：对话 tab 拖入 → 加为对话附件（与 openDroppedFile 分发同步）
  if (kind === 'harness') return '<span class="claude-ico"></span> 松开添加为 Claude 对话附件';
  // a261：水印图标 SVG 化（引 icons.js note/file 字形，20px 配 22px 文案）；
  // 图标+文案包一层 span 保住内部空格（遮罩是 flex，裸 svg 会成独立 flex 项贴死文字）
  if (kind === 'editor' && c.isNote && c.editor)
    return '<span><svg width="20" height="20" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><path d="M4 2.5h4.5L12 6v7.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z"/><path d="M8.5 2.5V6H12"/><path d="M5.5 8.5h5M5.5 11h3.5"/></svg> 松开插入到笔记</span>';
  return '<span><svg width="20" height="20" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><path d="M4 2.5h4.5L12 6v7.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z"/><path d="M8.5 2.5V6H12"/></svg> 松开以打开文件</span>';
}
function showDragOverlay(show) {
  if (show && !_dragOverlay) {
    _dragOverlay = document.createElement('div');
    _dragOverlay.id = 'dragOverlay';
    _dragOverlay.innerHTML = _dragOverlayText();
    document.body.appendChild(_dragOverlay);
  } else if (show && _dragOverlay) {
    _dragOverlay.innerHTML = _dragOverlayText();   // 拖着悬停时切了 tab，文案同步
  } else if (!show && _dragOverlay) {
    _dragOverlay.remove(); _dragOverlay = null;
    return;
  }
}

// 对比弹窗开着时拖拽不显示全屏遮罩：A/B 栏位自身 dragover 高亮已是
// 落点提示（用户反馈：全屏大字水印横跨两栏压内容,还和栏位高亮叠出双框感）。
// 有意函数解包（monkey-patch）：保留原函数再包装一层加前置判断。
const _origShowDragOverlay = showDragOverlay;
// eslint-disable-next-line no-func-assign
showDragOverlay = function(show) {
  const dm = $('diffPickModal');
  if (show && dm && dm.classList.contains('show')) return;   // 弹窗场景：不出遮罩
  _origShowDragOverlay(show);
};
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
// 回调里 evaluate_js 调 openDroppedFile。这里仅 preventDefault（阻止 WebView2 导航到文件）
// 并隐藏遮罩——preventDefault 不影响 pywebview 的 drop_handler 触发。
// 注：开 Claude 会话后 WebView2 出站 IPC 有 10s 级延迟（拖放卡顿，已排查多轮
// 未根治——fetch/pywebview.api/长轮询/Chromium 开关全部试过均无效或更糟），
// 现保持原生链路（延迟稳定 ~12s、弹窗必出），待 WebView2 Runtime 层解决。
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
function buildLogViewer(path, gotoLine) {   // R28-5：gotoLine 行定位（大文件跳转）
  const name = path.split(/[\\\/]/).pop();
  const portId = 'log:' + name + ':' + Date.now();
  // 记入最近打开（文件类型，快捷重开走日志查看器；key 用文件名归一——
  // 日志库打开传 name、其他入口可能传完整路径，同文件只记一条。
  // 带 extPath：外部路径时「最近」重开可智能分发到编辑器）
  if (typeof _recentAdd === 'function') {
    const isExt = /^[a-zA-Z]:[\\/]|\\\\/.test(path);
    _recentAdd({type:'file', key:'file:'+name, label:name, data:{kind:'log', name:name, path:path, extPath: isExt ? path : ''}});
  }
  // 若已打开同名日志，切过去（a342：gotoLine 一并透传——原 return 丢弃，
  // 跳转已打开的大文件时定位静默失效）
  // a374：路径归一化比较——正/反斜杠形态差异会击穿去重偷开双胞胎 tab
  const _gotoLine = (typeof gotoLine === 'number' && gotoLine > 0) ? Math.floor(gotoLine) : 0;
  const _np = p => String(p || '').replace(/\\/g, '/').toLowerCase();
  for (const pid in connections) {
    if (connections[pid].meta && connections[pid].meta.kind === 'log' && _np(connections[pid].meta.path) === _np(path)) {
      switchTab(pid);
      if (_gotoLine > 0) gotoLogLine(connections[pid], _gotoLine);
      return;
    }
  }
  // 建 tab
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${fileIconHtml(name, 14)}</span><span class="label">${esc(name)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeLogViewer(portId); return; } switchTab(portId); };
  // 建 wrap（.term-area，内含日志查看器）
  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="log-viewer">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-lv-action="search"><span>${ICO16.search}</span> 搜索</button>
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
          <input type="text" class="log-search-input" placeholder="查找关键字…（回车搜索，再按回车跳下一个）" autocomplete="off" name="log_search_input">
          <input type="text" class="log-search-exclude" placeholder="排除（多个用 | 分隔，支持正则）" title="命中行含任一排除模式则剔除。多个用 | 分隔，支持正则。例：bsp.err | timeout" autocomplete="off" name="log_search_exclude">
          <button class="btn ghost log-search-btn">查找全部</button>
          <span class="log-search-count"></span>
          <span class="log-jump-goto">
            <span class="log-jump-lbl">跳到第</span>
            <input type="number" class="log-jump-input" min="1" step="1" placeholder="N" title="跳到第 N 个匹配（回车）" name="log_jump_input">
            <span class="log-jump-lbl">个</span>
          </span>
          <button class="btn ghost icon-btn log-search-collapse" title="折叠分栏">▾</button>
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
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);   // 拖拽排序（tab-drag.js）
  termArea.appendChild(wrap);
  // conn 对象
  const conn = {
    portId,  // 用于 await 后校验当前 conn 是否仍存活（防止用户在索引期间关闭/切换日志 tab）
    gotoLine: _gotoLine,   // R28-5：行定位（索引完成后滚动+闪烁）
    meta: { kind: 'log', label: name, path },
    tab, wrap,
    vlist: wrap.querySelector('.vlist'),
    vlistInner: wrap.querySelector('.vlist-inner'),
    statusEl: wrap.querySelector('.log-viewer-status'),
    infoEl: wrap.querySelector('[data-lv-info]'),
    searchPane: wrap.querySelector('.log-search-pane'),
    searchInput: wrap.querySelector('.log-search-input'),
    searchExclude: wrap.querySelector('.log-search-exclude'),
    searchResults: wrap.querySelector('.log-search-results'),
    searchCount: wrap.querySelector('.log-search-count'),
    jumpInput: wrap.querySelector('.log-jump-input'),
    logState: {
      name: path, total: 0, scaled: false, rows: new Map(),
      renderedStart: -1, renderedEnd: -1, renderSeq: 0,
      searchQ: '', searchExcludeQ: '', searchIdx: 0, curRow: -1,
      // 搜索结果：稀疏窗口缓存（命中序号→行对象），只留浏览位置附近 RES_WIN 条；
      // 总数 searchTotal 撑满滚动条，缺口按序号向后端精准回载，无上限无损失
      resultData: {}, resWinStart: 0, resWinEnd: 0, searchTotal: 0,
      resRenderStart: -1, resRenderEnd: -1,
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
  // 跳到第 N 个匹配：回车/失焦触发，滚结果列表到该序号（resEnsureRange 回载，
  // 主视图同步跳转高亮）。搜索前输入框禁用态由 doLogSearch 控制。
  conn.jumpInput.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const ls = conn.logState;
    const n = parseInt(conn.jumpInput.value, 10);
    if (!ls.searchQ || !ls.searchTotal) { showBanner('请先搜索（查找全部）再跳转'); return; }
    if (ls.searching) { showBanner('搜索进行中，请稍候'); return; }
    if (!n || n < 1 || n > ls.searchTotal) {
      showBanner('请输入 1 - ' + ls.searchTotal.toLocaleString() + ' 之间的序号');
      return;
    }
    ls.searchIdx = n - 1;
    // 结果列表滚到该序号（缩放模式经 resHitToScroll 映射，超 Chrome 上限不失真）
    conn.searchResults.scrollTop = resHitToScroll(conn, n - 1);
    ls.resRenderStart = -1; ls.resRenderEnd = -1;
    renderLogResults(conn);
    highlightLogSearchResult(conn, ls.searchIdx);
    // 主视图同步跳转（窗口缓存命中则立即，否则回载后跳）
    const l = ls.resultData[ls.searchIdx];
    if (l) jumpToLogRow(conn, l.row, l.row);
    else {
      resEnsureRange(conn, ls.searchIdx);
      waitResHitThenJump(conn, ls.searchIdx);
    }
  });
  // 结果列表：滚动虚拟渲染 + 到底续载 + 点击跳转（事件委托）
  initLogResultsEvents(conn);
  wrap.querySelector('.log-search-input').addEventListener('keydown', e => { if (e.key === 'Enter') doLogSearch(conn); });
  // 排除框回车同样触发搜索；内容变化时也整体复位（与关键字框一致）
  wrap.querySelector('.log-search-exclude').addEventListener('keydown', e => { if (e.key === 'Enter') doLogSearch(conn); });
  // 输入清空时复位整个搜索状态（染色/列表/计数/高亮/跳转框），保持一致
  wrap.querySelector('.log-search-input').addEventListener('input', e => {
    if (!e.target.value.trim() && conn.logState.searchQ) {
      const ls = conn.logState;
      ls.searchGen = (ls.searchGen || 0) + 1;  // 作废在途全量搜索：响应到达即丢弃，防旧词结果复活
      ls.searching = false;
      ls.searchQ = ''; ls.searchExcludeQ = ''; ls.searchIdx = 0; ls.searchTotal = 0;
      ls.resultData = {}; ls.resWinStart = 0; ls.resWinEnd = 0;
      if (ls.resPending) ls.resPending.clear();
      ls.curRow = -1;
      ls.resRenderStart = -1; ls.resRenderEnd = -1;
      conn.searchResults.innerHTML = ''; conn.searchResults._spacer = null; conn.searchResults._spacerH = null;
      conn.searchCount.textContent = '';
      ls.renderedStart = -1; ls.renderedEnd = -1;
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
  ls.searchQ = ''; ls.searchExcludeQ = ''; ls.resultData = {}; ls.searchIdx = 0;
  ls.searchTotal = 0; ls.resWinStart = 0; ls.resWinEnd = 0; ls.curRow = -1;
  ls.searchGen = (ls.searchGen || 0) + 1; ls.searching = false;  // 作废在途搜索
  ls.resRenderStart = -1; ls.resRenderEnd = -1;
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
    // R28-5（实锤：大文件行定位丢失）：外部传入 gotoLine（跳转/引用点击
    // 大于 30M 文件时降级到此）——滚动到目标行并闪烁标记（a342 与已打开
    // 去重分支统一走 gotoLogLine）
    if (conn.gotoLine > 0 && conn.gotoLine <= ls.total) {
      const _ln = conn.gotoLine;
      conn.gotoLine = 0;
      gotoLogLine(conn, _ln);
    }
    syncOpenLogs();  // 索引完成，带 total 再同步一次
  } catch(e) { if (connections[conn.portId] === conn) conn.statusEl.textContent = '加载失败：' + e; }
}

// a342：行定位统一入口（索引完成消费 + 已打开去重分支复用）——滚动到
// 目标行、闪烁标记、状态条"已定位"提示存活 3.2s。索引未完成（total=0）
// 时挂 conn.gotoLine 等索引回调消费
function gotoLogLine(conn, line) {
  const ls = conn.logState;
  if (!ls || !ls.total) { conn.gotoLine = line; return; }   // 索引未完，挂起
  if (line <= 0 || line > ls.total) return;
  conn.vlist.scrollTop = logRowToScroll(conn, line - 1);
  ls._pendingFlash = line - 1;   // flash 由 renderLogSlice 渲染落地拍消费
  renderLogSlice(conn);
  // a342 兜底：目标行本就在渲染区间（scrollTop 未变）时 renderLogSlice
  // 区间相同 early return，渲染拍不来——250ms 后补一拍（渲染拍先到则
  // _pendingFlash 已置空，这里自然跳过）
  setTimeout(() => {
    if (connections[conn.portId] !== conn || ls._pendingFlash == null) return;
    const rowEl = conn.vlistInner.querySelector('[data-row="' + ls._pendingFlash + '"]');
    if (rowEl) {
      rowEl.classList.add('lv-goto-flash');
      const _re = rowEl;
      setTimeout(() => _re.classList.remove('lv-goto-flash'), 2600);
      ls._pendingFlash = null;
    }
  }, 250);
  // renderLogSlice 是 async：文案等首拍落地（80ms）再刷；跨区间 fetch 期间
  // 显示区间还是旧值，但 scroll→renderLogSlice 完成后会带 _locNote 重拼兜底
  conn._locNote = '已定位第 ' + line + ' 行';
  setTimeout(() => { if (connections[conn.portId] === conn) refreshLogStatus(conn); }, 80);
  setTimeout(() => {
    if (connections[conn.portId] !== conn) return;
    conn._locNote = '';
    refreshLogStatus(conn);
  }, 3200);
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

// 行文本转 HTML：先在原始文本上找命中区间（大小写不敏感），逐段 esc 后拼 mark——
// 不在 esc 后的文本上匹配，避免用户搜实体片段（如 "lt;"、"amp;"）错切 HTML 实体
function hlSearchText(text, q) {
  if (!q) return esc(text);
  const lowText = (text || '').toLowerCase(), lowQ = q.toLowerCase();
  if (!lowQ) return esc(text);
  const ranges = [];
  let pos = 0, i;
  while ((i = lowText.indexOf(lowQ, pos)) !== -1) {
    ranges.push([i, i + q.length]);
    pos = i + q.length;
  }
  if (!ranges.length) return esc(text);
  let out = '', last = 0;
  for (const [s, e] of ranges) {
    out += esc(text.slice(last, s)) + '<mark class="hl-hit">' + esc(text.slice(s, e)) + '</mark>';
    last = e;
  }
  return out + esc(text.slice(last));
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
  // a342：行定位闪烁——渲染落地这拍消费（跨区间 fetch 耗时不可预估，
  // 固定延时挂 flash 会扑空：DOM 还是旧区间 querySelector 落空）
  if (ls._pendingFlash != null) {
    const rowEl = vp.querySelector('[data-row="' + ls._pendingFlash + '"]');
    if (rowEl) {
      rowEl.classList.add('lv-goto-flash');
      const _re = rowEl;
      setTimeout(() => _re.classList.remove('lv-goto-flash'), 2600);
      ls._pendingFlash = null;
    }
  }
  refreshLogStatus(conn);
}

// a342：状态条统一刷新（renderLogSlice / 行定位挂载与清除共用）——
// _locNote（行定位提示，存活 3.2s 与闪烁同步）在这里拼接，避免直接
// textContent += 被 scroll→renderLogSlice 异步重写覆盖
function refreshLogStatus(conn) {
  const ls = conn.logState;
  conn.statusEl.textContent = `共 ${ls.total.toLocaleString()} 行 · 显示 ${ls.renderedStart}-${ls.renderedEnd-1}` + (ls.scaled ? ' · 缩放' : '') + (conn._locNote ? ' · ' + conn._locNote : '');
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

// 查找全部 → 底部分栏列命中行。稀疏窗口缓存 + 虚拟列表：
// - 总数 searchTotal 撑满滚动条（真实全量计数，分毫不差，无上限）
// - resultData 是命中序号→行对象的窗口缓存，只保留浏览位置附近 RES_WIN 条，
//   滚出窗口即丢弃；可视区缺哪段就按命中序号向后端精准回载（O(1) seek 毫秒级）
// - 上下翻、滚到任意位置都顺滑，内存恒定 ~RES_WIN 条
const RES_WIN = 100000;   // 窗口缓存条数（约 10-18MB，滚 1/20 个列表才换窗）
async function doLogSearch(conn) {
  const q = conn.searchInput.value.trim();
  const ex = (conn.searchExclude ? conn.searchExclude.value.trim() : '');
  const ls = conn.logState;
  if (!q || !ls.name) return;
  // 已有结果且查询未变（关键字+排除串都一致）→ 跳转下一个（窗口缓存可能未含该序号：先回载再跳）
  if (ls.searchTotal && ls.searchQ === q && ls.searchExcludeQ === ex) {
    ls.searchIdx = (ls.searchIdx + 1) % ls.searchTotal;
    const l = ls.resultData[ls.searchIdx];
    if (l) {
      jumpToLogRow(conn, l.row, l.row);
    } else {
      // 数据在途：发起回载并轮询等待（上限 3s），到货即跳——不静默丢跳
      resEnsureRange(conn, ls.searchIdx);
      waitResHitThenJump(conn, ls.searchIdx);
    }
    highlightLogSearchResult(conn, ls.searchIdx);
    return;
  }
  // 新搜索进行中（首扫 G 级文件要数秒）：代次令牌作废在途请求——
  // 清空输入框复位/换词重搜不能取消 fetch，响应无条件写回会复活旧词结果。
  if (ls.searching) {
    // 新词回车：作废旧代次，当前输入成为最新请求，旧响应到达即丢弃
    if (ls.searchQ !== q || ls.searchExcludeQ !== ex) {
      ls.searchGen = (ls.searchGen || 0) + 1;
      ls.searching = false;
    } else {
      return;  // 同词重复回车：忽略，防并发重发全量扫描
    }
  }
  ls.searching = true;
  const myGen = (ls.searchGen = (ls.searchGen || 0) + 1);
  const myInput = conn.searchInput.value.trim();
  toggleLogSearchPane(conn, true);
  conn.searchCount.innerHTML = '<span class="spin">✳</span> 搜索中…';
  try {
    const r = await fetch('/api/log_search?name=' + encodeURIComponent(ls.name) + '&q=' + encodeURIComponent(q) + '&exclude=' + encodeURIComponent(ex) + '&limit=500');
    const j = await r.json();
    // 代次/输入不一致即丢弃：清空输入复位（gen++）与换词重搜都在此拦下旧响应
    if (myGen !== ls.searchGen || conn.searchInput.value.trim() !== myInput) { ls.searching = false; return; }
    ls.searching = false;
    if (!j.ok) { conn.searchCount.textContent = '失败：' + (j.err || ''); return; }
    if (connections[conn.portId] !== conn) return;  // 索引期间 tab 已关
    ls.searchQ = q; ls.searchExcludeQ = ex; ls.searchIdx = 0;
    ls.curRow = -1;  // 换词重搜：清上一词的命中行高亮
    ls.searchTotal = (typeof j.total === 'number' && j.total >= 0) ? j.total : (j.lines || []).length;
    // 窗口缓存初始化：首批 500 条从命中序号 0 开始
    ls.resultData = {};
    if (ls.resPending) ls.resPending.clear();
    ls.resWinStart = 0; ls.resWinEnd = 0;
    (j.lines || []).forEach((l, i) => { ls.resultData[i] = Object.assign({ hi: i }, l); });
    conn.searchResults.scrollTop = 0;
    ls.resRenderStart = -1; ls.resRenderEnd = -1;
    resEnsureRange(conn, 0);
    renderLogResults(conn);
    conn.searchCount.textContent = '命中 ' + ls.searchTotal.toLocaleString() + ' 处';
    // 主视图从此带关键字染色：强制重渲染当前可视区
    ls.renderedStart = -1; ls.renderedEnd = -1;
    if (ls.resultData[0]) { jumpToLogRow(conn, ls.resultData[0].row, ls.resultData[0].row); highlightLogSearchResult(conn, 0); }
    else renderLogSlice(conn);
  } catch(e) { ls.searching = false; conn.searchCount.textContent = '失败：' + e; }
  // 注意：清空输入框的复位逻辑（searchInput 的 input/change 事件）需同步
  // ls.searchGen++ 作废在途搜索，见 initLogSearchEvents。
}
// 确保命中序号 [s, s+RES_WIN) 内可视区附近的数据在窗口缓存里；缺段精准回载，
// 窗口外丢弃（换窗）。scroll 驱动，异步回载后自动重渲染。
// 换窗带滞回：中心 = floor(hitIdx/RES_WIN)*RES_WIN，浏览点离当前窗口中心
// 超过 RES_WIN/4 才换窗，避免在窗口边界来回滚时反复丢弃/回载抖动。
function resEnsureRange(conn, hitIdx) {
  const ls = conn.logState;
  if (!ls.searchTotal) return;
  const center = Math.floor(hitIdx / RES_WIN) * RES_WIN;
  const wantStart = Math.max(0, center - RES_WIN);
  const wantEnd = Math.min(ls.searchTotal, wantStart + RES_WIN * 3);
  const curCenter = (ls.resWinStart + Math.min(ls.resWinEnd, ls.resWinStart + RES_WIN * 3)) / 2;
  if (ls.resWinStart !== wantStart || ls.resWinEnd !== wantEnd) {
    // 已有窗口且浏览点仍在窗口内且偏离中心 < 半窗（窗口宽 3×RES_WIN）→ 不换（滞回）
    // 先判强制条件：可视/预载需求已越出窗口边界 → 必须扩窗/换窗，否则
    // hitIdx 落在 [resWinEnd-5, resWinEnd) 滞回带时回载响应被窗口过滤丢弃，
    // 渲染再触发回载 → 无限循环，可视区永久「加载中」。
    const needStart0 = Math.max(0, hitIdx - 500);
    const needEnd0 = Math.min(ls.searchTotal, hitIdx + 2000);
    const outOfWin = needStart0 < ls.resWinStart || needEnd0 > ls.resWinEnd;
    const inWin = hitIdx >= ls.resWinStart && hitIdx < ls.resWinEnd;
    const devi = Math.abs(hitIdx - curCenter);
    if (outOfWin || !inWin || devi > RES_WIN * 3 / 2 || ls.resWinEnd === 0) {
      ls.resWinStart = wantStart; ls.resWinEnd = wantEnd;
      // 丢弃窗口外缓存
      for (const k of Object.keys(ls.resultData)) {
        if (+k < wantStart || +k >= wantEnd) delete ls.resultData[k];
      }
    }
  }
  // 可视区 ± 预载区段
  const needStart = Math.max(0, hitIdx - 500);
  const needEnd = Math.min(ls.searchTotal, hitIdx + 2000);
  const missing = [];
  let i = needStart;
  while (i < needEnd) {
    if (ls.resultData[i] !== undefined) { i++; continue; }
    let j = i;
    while (j < needEnd && ls.resultData[j] === undefined) j++;
    missing.push([i, j]); i = j;
  }
  for (const [s, e] of missing) {
    // 后端单次上限 500：宽缺口按 500 切片；在途去重（resPending 段集合）
    for (let k = s; k < e; k += 500) {
      const segStart = k, segEnd = Math.min(e, k + 500);
      if (ls.resPending && ls.resPending.has(segStart)) continue;
      resFetchRange(conn, segStart, segEnd - segStart);
    }
  }
}
// 从后端按命中序号回载 [start, start+count) 到窗口缓存（异步，不阻塞滚动）
async function resFetchRange(conn, start, count) {
  const ls = conn.logState;
  if (!ls.searchQ) return;
  const myQ = ls.searchQ;  // 代次快照：回写前比对，防在途旧词响应污染新搜索
  const myEx = ls.searchExcludeQ || '';  // 排除串同做代次快照
  if (!ls.resPending) ls.resPending = new Set();
  ls.resPending.add(start);  // 在途标记：resEnsureRange 不重复发同段
  try {
    const r = await fetch('/api/log_search_page?name=' + encodeURIComponent(ls.name) + '&q=' + encodeURIComponent(myQ) + '&exclude=' + encodeURIComponent(myEx) + '&hit_start=' + start + '&count=' + count);
    const j = await r.json();
    ls.resPending.delete(start);
    if (!j.ok) return;
    if (ls.searchQ !== myQ || (ls.searchExcludeQ || '') !== myEx) return;  // 期间已换词/排除：丢弃
    // fetch 期间可能已换窗：只收下仍在窗口内的行
    (j.lines || []).forEach((l, i) => {
      const hi = start + i;
      if (ls.resWinStart <= hi && hi < ls.resWinEnd) ls.resultData[hi] = Object.assign({ hi }, l);
    });
    ls.resRenderStart = -1; ls.resRenderEnd = -1;
    renderLogResults(conn);
  } catch(e) {
    ls.resPending.delete(start);
  }
}
// 轮询等待某命中序号回载到窗口缓存后跳主视图（上限 3s，60ms 间隔）。
// 代次校验 + 去重：轮询前撤销上一个轮询器（ls._jumpTimer），轮询体校验
// searchQ/searchIdx 未被改变——3s 窗口内再回车会双轮询，后到者覆盖落点。
function waitResHitThenJump(conn, hitIdx) {
  const ls = conn.logState;
  if (ls._jumpTimer) { clearInterval(ls._jumpTimer); ls._jumpTimer = null; }
  const myQ = ls.searchQ, myEx = ls.searchExcludeQ || '', myIdx = hitIdx;
  const t0 = Date.now();
  const timer = setInterval(() => {
    if (connections[conn.portId] !== conn) { clearInterval(timer); ls._jumpTimer = null; return; }  // tab 已关
    // 期间已换词/换序号：本次跳转作废（新调用会带自己的轮询器）
    if (ls.searchQ !== myQ || (ls.searchExcludeQ || '') !== myEx || ls.searchIdx !== myIdx) {
      clearInterval(timer); ls._jumpTimer = null; return;
    }
    const d = ls.resultData[hitIdx];
    if (d) { clearInterval(timer); ls._jumpTimer = null; jumpToLogRow(conn, d.row, d.row); }
    else if (Date.now() - t0 > 3000) { clearInterval(timer); ls._jumpTimer = null; showBanner('跳转超时：数据回载未完成'); }
  }, 60);
  ls._jumpTimer = timer;
}
// 搜索结果虚拟渲染：只渲染可视区 ± 5 行（窗口缓存 ls.resultData{命中序号: 行}）
function renderLogResults(conn) {
  const ls = conn.logState;
  const el = conn.searchResults;
  const n = ls.searchTotal;
  // 占位撑滚动高度：命中×20px 超 RES_MAX_H 时钳制（浏览器 ~33.5M px 上限），
  // 滚动位置经 resScrollToHit 线性映射到命中序号，尾部仍可达、跳转不失真
  const naturalH = n * RES_ROW_H;
  const scaled = naturalH > RES_MAX_H;
  const spacerH = Math.min(naturalH, RES_MAX_H);
  if (!el._spacer || !el._spacer.isConnected) {
    el.innerHTML = '<div class="res-spacer"></div>';
    el._spacer = el.querySelector('.res-spacer');
    el._spacerH = null;
  }
  if (el._spacerH !== spacerH) { el._spacerH = spacerH; el._spacer.style.height = spacerH + 'px'; }
  const st = el.scrollTop, vh = el.clientHeight;
  const startHit = scaled ? resScrollToHit(conn, st) : Math.floor(st / RES_ROW_H);
  const start = Math.max(0, startHit - 5);
  const end = Math.min(n, startHit + Math.ceil(vh / RES_ROW_H) + 10);
  // 可视区有缺口 → 先触发回载，本次渲染已有数据，缺口行留空（回载到后自动补渲染）
  resEnsureRange(conn, start);
  if (start === ls.resRenderStart && end === ls.resRenderEnd) return;
  const q = ls.searchQ;
  let html = '';
  for (let i = start; i < end; i++) {
    const l = ls.resultData[i];
    // 行相对 viewport 顶排布（viewport 平移到 scrollTop），缩放/非缩放均正确——
    // 缩放模式下序号↔scrollTop 非线性，不能用序号换算的内容坐标定位行
    const topPx = (i - start) * RES_ROW_H;
    if (!l) {
      // 回载在途：占位提示行（数据到了 resFetchRange 会重渲染），不留无解释的空白
      html += '<div class="hline res-loading" style="position:absolute;top:' + topPx + 'px"><span class="spin">✳</span> 加载中…</div>';
      continue;
    }
    const text = hlSearchText(l.text || '', q);
    const tsHtml = l.ts ? '<span class="hts">' + fmtTs(l.ts) + '</span>' : '';
    // 结果行不做等级染色（用户反馈颜色错开不好看）：统一外观，仅选中行 active 高亮
    html += '<div class="hline' + (i === ls.searchIdx ? ' active' : '') + '" data-i="' + i + '" data-row="' + l.row + '" style="position:absolute;top:' + topPx + 'px" title="' + esc(l.text || '') + '"><span class="hrow">' + l.row + '</span>' + tsHtml + '<span class="htag">' + esc(l.tag||'') + '</span>' + text + '</div>';
  }
  // 可视区容器：平移到当前 scrollTop，行相对其顶排布（缩放/非缩放均正确——
  // 缩放时序号↔scrollTop 非线性，不能用序号换算的内容坐标定位行）
  let vp = el.querySelector('.res-viewport');
  if (!vp) { vp = document.createElement('div'); vp.className = 'res-viewport'; el.insertBefore(vp, el.children[1] || null); }
  vp.style.top = st + 'px';
  vp.innerHTML = html;
  // 移除 vp 之后可能残留的旧直接子行（历史版本挂在 el 上的行）
  while (el.lastElementChild && el.lastElementChild !== vp) el.lastElementChild.remove();
  ls.resRenderStart = start; ls.resRenderEnd = end;
}
// 滚动 + 点击（事件委托：虚拟列表 DOM 不断重建，逐行绑定不可行）
function initLogResultsEvents(conn) {
  conn.searchResults.addEventListener('scroll', () => renderLogResults(conn));
  conn.searchResults.addEventListener('click', e => {
    const line = e.target.closest('.hline[data-i]');
    if (!line) return;
    const ls = conn.logState;
    const idx = +line.dataset.i;
    ls.searchIdx = idx;
    jumpToLogRow(conn, +line.dataset.row, +line.dataset.row);
    highlightLogSearchResult(conn, idx);
  });
}
function highlightLogSearchResult(conn, idx) {
  // 虚拟列表：可视区行带 data-i，按序号高亮当前命中（不可见的行渲染时自带 active）
  conn.searchResults.querySelectorAll('.hline[data-i]').forEach(el => el.classList.toggle('active', +el.dataset.i === idx));
}
function toggleLogSearchPane(conn, show) {
  conn.searchPane.style.display = show ? 'flex' : 'none';
  conn.wrap.querySelector('.log-search-splitter').style.display = show ? 'block' : 'none';
  // 折叠按钮提示随状态变（▾ 折叠 / ▴ 展开）
  const collapseBtn = conn.wrap.querySelector('.log-search-collapse');
  if (collapseBtn) collapseBtn.textContent = show ? '▾' : '▴';
  if (show) {
    // 隐藏期间 clientHeight=0 会使虚拟列表渲染窗口算错：展开后强制按新尺寸重渲染
    const ls = conn.logState;
    ls.resRenderStart = -1; ls.resRenderEnd = -1;
    renderLogResults(conn);
    conn.searchInput.focus();
  }
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
    if (dragging) {
      dragging = false; document.body.style.cursor = '';
      renderLogSlice(conn);
      // 分栏高度变化：搜索结果列表可视区变大，renderLogResults 的
      // 相等性短路（start===resRenderStart && end===resRenderEnd）会跳过
      // 重渲染 → 底部新增区域空白。复位渲染游标强制重算。
      const ls = conn.logState;
      if (ls && ls.searchTotal) { ls.resRenderStart = -1; ls.resRenderEnd = -1; renderLogResults(conn); }
    }
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
    const ls = conn.logState;
    if (ls && ls._jumpTimer) clearInterval(ls._jumpTimer);  // 防关 tab 后轮询器残留
    conn.tab.remove(); conn.wrap.remove(); delete connections[portId];
  }
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0;
  });
  // 对齐 _edCloseNow/closeConnection（v4.1 同锤修复的漏网路径）：关非活动 tab
  // 不动激活态；关活动 tab 优先回「来时的 tab」，无来路才回排序首位
  const back = window._hgTabBack;
  window._hgTabBack = null;
  if (remaining.length) {
    // a455：自动回切不计 MRU（与 harness 关 tab 同约定）
    if (activePortId === portId) switchTab(back && connections[back] ? back : remaining[0], true);
  }
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon"><svg width="30" height="30" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 2.5v3M10.5 2.5v3"/><path d="M4 5.5h8v2a4 4 0 0 1-8 0z"/><path d="M8 11.5v2"/></svg></div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();
  refreshGlobalStatus();
  syncOpenLogs();  // 通知后端此日志已关闭
}

// ============================================================
// ============================================================
// TFTP 面板（侧边栏底部）
// ============================================================

// 模块化一期：转 ES module——跨文件/Python 裸引用消费名挂 window。
// 清单由 eslint no-undef 神谕反推（零启发式）：本文件转模块后，其余
// 文件/Python 推送的裸标识符引用全部经 window 解析。
window.buildLogViewer = buildLogViewer;
window.closeLogViewer = closeLogViewer;
window.renderLogResults = renderLogResults;
window.renderLogSlice = renderLogSlice;
window.toggleLogSearchPane = toggleLogSearchPane;
