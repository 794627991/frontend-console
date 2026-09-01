let searchState = { q: '', idx: -1, total: 0 };
const SEARCH_DECOR = {
  matchBackground: 'rgba(255,214,102,0.35)',
  matchOverviewRuler: '#ff9d00',
  activeMatchBackground: 'rgba(0,212,255,0.45)',
  activeMatchColor: '#ffffff',
};
function clearSearchHighlights() {
  // 清掉搜索 decoration（带 class 的）
  if (activePortId && connections[activePortId] && connections[activePortId].search) {
    try { connections[activePortId].search.clearDecorations(); } catch(e){}
  }
  searchState.idx = -1;
  searchState.total = 0;
  $('searchCount').textContent = '';
}
function applySearchHighlights(q) {
  clearSearchHighlights();
  if (!q || !activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.term || !conn.search) return;
  // 统计总数：遍历 buffer 行匹配（与 search addon 的大小写设置一致）
  let total = 0;
  const buf = conn.term.buffer.active;
  const low = q.toLowerCase();
  for (let r = 0; r < buf.length; r++) {
    const ln = buf.getLine(r);
    if (!ln) continue;
    const t = ln.translateToString(true).toLowerCase();
    let pos = 0;
    while ((pos = t.indexOf(low, pos)) !== -1) { total++; pos += low.length; }
  }
  searchState.total = total;
  searchState.idx = total ? 1 : -1;
  $('searchCount').textContent = total ? (total + ' 处') : '无';
  if (!total) return;
  // findNext 会用 SEARCH_DECOR 高亮所有匹配，并定位到第一个
  conn.search.findNext(q, {
    caseSensitive: false, wholeWord: false, incremental: false,
    decorations: SEARCH_DECOR,
  });
}
function gotoSearchMark(idx) {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.search) return;
  const q = searchState.q;
  if (!q) return;
  const opts = { caseSensitive: false, wholeWord: false, incremental: false, decorations: SEARCH_DECOR };
  if (idx < 0) {
    conn.search.findPrevious(q, opts);
    if (searchState.idx > 1) searchState.idx--;
    else searchState.idx = searchState.total;
  } else {
    conn.search.findNext(q, opts);
    if (searchState.idx < searchState.total) searchState.idx++;
    else searchState.idx = 1;
  }
  $('searchCount').textContent = searchState.total ? (searchState.idx + '/' + searchState.total) : '无';
}
$('searchInput').addEventListener('input', (e) => {
  const q = e.target.value.trim();
  searchState.q = q;
  if (q) applySearchHighlights(q); else clearSearchHighlights();
});
$('searchInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (e.shiftKey) gotoSearchMark(-1);
    else gotoSearchMark(1);
  }
});
$('searchPrev').onclick = () => gotoSearchMark(-1);
$('searchNext').onclick = () => gotoSearchMark(1);

// ---- Ctrl+右键上下文菜单 ----
// 原生读剪贴板粘贴到连接（Ctrl+V 与菜单「粘贴到终端」共用）。
// 走 pywebview js_api 的 Win32 读剪贴板，绕开 navigator.clipboard.readText
// 首次触发的 WebView2「允许粘贴吗」权限弹窗。
function _pasteToConn(conn, notify) {
  const doPaste = (text) => {
    if (!text) { if (notify) showBanner('剪贴板为空'); return; }
    if (connections[conn.portId] !== conn) return;
    // 多行粘贴警告（Tabby 同款防误操作）：>1 行或超 500 字符需确认，
    // 防止误把配置文件/脚本整段灌进设备破坏现场
    const lines = text.split(/\r?\n/);
    if (lines.length > 1 || text.length > 500) {
      const preview = text.length > 60 ? text.slice(0, 60) + '…' : text;
      const desc = lines.length > 1
        ? `即将粘贴 ${lines.length} 行 / ${text.length} 字符（首行: ${preview.replace(/\n/g, ' ⏎ ')}）`
        : `即将粘贴 ${text.length} 字符（${preview}）`;
      if (!confirm(desc + '\n\n确定粘贴到终端？')) {
        if (notify) showBanner('已取消粘贴');
        return;
      }
    }
    const bytes = Array.from(new TextEncoder().encode(text));
    termSendRaw(conn.portId, bytes);
    if (notify) showBanner('已粘贴 ' + text.length + ' 字符');
  };
  if (window.pywebview && pywebview.api && pywebview.api.read_clipboard) {
    pywebview.api.read_clipboard().then(doPaste).catch(() => {
      if (notify) showBanner('读取剪贴板失败');
    });
  } else {
    // pywebview bridge 未就绪（页面加载早期）时兜底走 Web API
    navigator.clipboard.readText().then(doPaste).catch(() => {});
  }
}
const _ctxMenu = () => $('ctxMenu');
function showCtxMenu(x, y, conn) {
  const m = _ctxMenu();
  const hasSel = !!(conn.term && conn.term.getSelection());
  m.innerHTML = [
    `<div class="ctx-item${hasSel ? '' : ' disabled'}" data-act="copySel">📋 复制选中</div>`,
    `<div class="ctx-item" data-act="copyAll">📋 复制全部内容</div>`,
    `<div class="ctx-item" data-act="paste">📥 粘贴到终端</div>`,
    `<div class="ctx-sep"></div>`,
    `<div class="ctx-item" data-act="find">🔍 查找（高亮跳转）</div>`,
    `<div class="ctx-item" data-act="findAll">🔍 查找全部（分栏列表）</div>`,
    `<div class="ctx-sep"></div>`,
    `<div class="ctx-item" data-act="clear">⌫ 清屏</div>`,
  ].join('');
  // 定位（防溢出右下边界）
  m.style.display = 'block';
  const mw = m.offsetWidth, mh = m.offsetHeight;
  m.style.left = Math.min(x, window.innerWidth - mw - 4) + 'px';
  m.style.top = Math.min(y, window.innerHeight - mh - 4) + 'px';
  // 菜单项点击
  m.querySelectorAll('.ctx-item').forEach(it => {
    it.onclick = () => {
      const act = it.dataset.act;
      hideCtxMenu();
      if (act === 'copySel' && hasSel) {
        try { navigator.clipboard.writeText(conn.term.getSelection()); } catch(_){}
      } else if (act === 'copyAll') {
        // 遍历 xterm buffer 全部行，join 成纯文本写剪贴板
        const buf = conn.term.buffer.active;
        const lines = [];
        for (let r = 0; r < buf.length; r++) {
          const ln = buf.getLine(r);
          if (ln) lines.push(ln.translateToString(true));
        }
        try { navigator.clipboard.writeText(lines.join('\n')); showBanner('已复制全部 ' + lines.length + ' 行'); } catch(_){}
      } else if (act === 'paste') {
        // 原生读剪贴板（无权限弹窗），编码后作为原始字节发到串口/SSH
        _pasteToConn(conn, true);
      } else if (act === 'find') {
        // 右侧面板搜索（高亮跳转，现有行为）
        $('searchInput').focus(); $('searchInput').select();
      } else if (act === 'findAll') {
        toggleTermSearchPane(conn, true);
        conn.termSearchInput.focus(); conn.termSearchInput.select();
      } else if (act === 'clear') {
        try { conn.term.clear(); } catch(e){}
      }
    };
  });
}
function hideCtxMenu() { _ctxMenu().style.display = 'none'; }
// 点击菜单外、滚动、ESC 关闭菜单
document.addEventListener('click', hideCtxMenu);
document.addEventListener('scroll', hideCtxMenu, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideCtxMenu(); });

// ---- 串口搜索分栏（仿日志查看器） ----
function toggleTermSearchPane(conn, show) {
  conn.termSearchPane.style.display = show ? 'flex' : 'none';
  conn.wrap.querySelector('.term-search-splitter').style.display = show ? 'block' : 'none';
  const collapseBtn = conn.wrap.querySelector('.term-search-collapse');
  if (collapseBtn) collapseBtn.textContent = show ? '▾' : '▴';
  // 显示/隐藏后终端高度变化，需重新 fit。
  // 注意：分栏 35% 高度此刻是同步生效的（display 直接改，布局立刻收缩），
  // fit 拿到的已是收缩后高度。但 WebGL canvas 的 style 高度更新是异步的
  // （xterm resize 链内部走 addRefreshCallback），保险起见 fit 后再补一次。
  try { conn.fit.fit(); } catch(e){}
  requestAnimationFrame(() => { try { conn.fit.fit(); } catch(e){} });
  if (show) conn.termSearchInput.focus();
}
async function doTermSearch(conn) {
  const q = conn.termSearchInput.value.trim();
  const st = conn.termSearchState;
  if (!q || !conn.term) return;
  conn.termSearchCount.textContent = '搜索中…';
  // 直接在 xterm buffer 内搜索（用户看到的内容），不调后端 /api/search。
  // 后端 buf 的 \r 处理与 xterm 不同（buf 拆行，xterm 同行覆盖），用后端结果
  // 跳转 xterm 会导致行号错位（"串行"问题）。xterm buffer 是最准确的搜索源。
  const buf = conn.term.buffer.active;
  const low = q.toLowerCase();
  const hits = [];
  for (let r = 0; r < buf.length; r++) {
    const ln = buf.getLine(r);
    if (!ln) continue;
    const t = ln.translateToString(true);
    if (t.toLowerCase().indexOf(low) !== -1) {
      hits.push({ row: r, text: t });
    }
  }
  st.q = q; st.results = hits; st.idx = 0;
  // 渲染命中行列表
  conn.termSearchResults.innerHTML = hits.map((l, idx) => {
    const text = esc((l.text || '').replace(/\r/g, ''));
    return `<div class="hline" data-idx="${idx}" title="${text}"><span class="hrow">${l.row}</span> ${text}</div>`;
  }).join('') || '<div style="padding:10px;color:var(--muted);">无命中</div>';
  conn.termSearchResults.querySelectorAll('.hline').forEach(el => {
    el.onclick = () => {
      const idx = +el.dataset.idx;
      st.idx = idx;
      jumpToTermHit(conn, idx);
      highlightTermHit(conn, idx);
    };
  });
  conn.termSearchCount.textContent = hits.length ? `命中 ${hits.length} 处` : '无命中';
  if (hits.length) { jumpToTermHit(conn, 0); highlightTermHit(conn, 0); }
}
// 跳到第 idx 个命中：st.results[idx].row 是搜索时记录的 xterm 行号，直接定位。
// 搜索在 xterm buffer 内完成，行号与显示一致，无错位。
function jumpToTermHit(conn, idx) {
  if (!conn.term || !conn.termSearchState) return;
  const st = conn.termSearchState;
  if (!st.results.length || idx < 0 || idx >= st.results.length) return;
  const found = st.results[idx].row;
  const buf = conn.term.buffer.active;
  // 行号可能因 reflow/新数据流入而漂移，校验仍在范围内
  if (found < 0 || found >= buf.length) return;
  try {
    // 跳转即脱离底部：关掉自动跟随（appendRaw 的 scrollToBottom 不再拽回底部），
    // 否则终端还在刷时每次跳转都被实时流拉回底部，必须先手动上翻才能跳。
    // 用户重新滚到底时 onScroll 会自动恢复 autoScroll。
    conn.autoScroll = false;
    // scrollToLine 把目标行滚到视图顶部；select 选中整行高亮（蓝底，xterm 内置最稳定）。
    // 滚动与选区/decoration 同帧触发时，viewport scrollTop 同步（syncScrollArea）与
    // WebGL canvas 重绘存在竞争——偶发"内容只显示上半截、下部空白"（重绘未覆盖新视口）。
    // 拆开：先滚（让 viewport/ydisp 同步完成），下一帧再选区+高亮。
    conn.term.scrollToLine(found);
    requestAnimationFrame(() => {
      if (connections[conn.portId] !== conn || !conn.term) return;
      try {
        conn.term.select(0, found, conn.term.cols);
      } catch(e){}
      if (conn.term.registerDecoration) {
        const offset = Math.round(found - conn.term.buffer.active.ybase - conn.term.buffer.active.y);
        const dec = conn.term.registerDecoration({
          marker: conn.term.registerMarker(offset),
          x: 0,
          width: conn.term.cols,
          backgroundColor: '#00d4ff',
          layer: 'top',
        });
        // 3 秒后淡出，避免堆积
        if (dec) setTimeout(() => { try { dec.dispose(); } catch(_){} }, 3000);
      }
    });
  } catch(e){}
}
function highlightTermHit(conn, idx) {
  conn.termSearchResults.querySelectorAll('.hline').forEach((el, i) => el.classList.toggle('active', i === idx));
}
// 拖分隔条调分栏高度（仿 initLogSplitter）
function initTermSplitter(conn) {
  const splitter = conn.wrap.querySelector('.term-search-splitter');
  const pane = conn.termSearchPane;
  const top = conn.wrap.querySelector('.xterm-wrap');
  let dragging = false, startY = 0, startH = 0;
  splitter.addEventListener('mousedown', e => {
    dragging = true; startY = e.clientY; startH = pane.offsetHeight;
    document.body.style.cursor = 'row-resize'; e.preventDefault();
  });
  conn.termSplitMove = e => {
    if (!dragging) return;
    const dh = e.clientY - startY;
    const newH = Math.max(60, Math.min(startH - dh, conn.wrap.clientHeight - 100));
    pane.style.height = newH + 'px';
  };
  conn.termSplitUp = () => {
    if (dragging) { dragging = false; document.body.style.cursor = ''; try { conn.fit.fit(); } catch(e){} }
  };
  document.addEventListener('mousemove', conn.termSplitMove);
  document.addEventListener('mouseup', conn.termSplitUp);
}

// ---- 感知标签：实时数据流（全局 SSE） ----
