function buildTerminal(portId, meta) {
  // 标签
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span>${esc(meta.label || portId)}</span><span style="color:var(--muted);font-size:10px;">${meta.kind === 'ssh' || meta.kind === 'claude' || meta.kind === 'telnet' ? '' : '@'+meta.baud}</span> <span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeConnection(portId); return; }
    switchTab(portId);
  };
  // 终端区
  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    ${meta.kind === 'claude' ? '' : `
    <div class="term-toolbar">
      <button class="lv-btn term-tb-pause" title="暂停/恢复滚屏">⏸ 暂停</button>
      <button class="lv-btn term-tb-clear" title="清屏（只清显示，缓冲历史不丢）">⊘ 清屏</button>
      <button class="lv-btn term-tb-newlog" title="从此刻起记录到新日志文件">＋📋 新日志</button>
      <button class="lv-btn term-tb-ctrlc" title="发送 Ctrl-C 中断">^C</button>
      <button class="lv-btn term-tb-ctrld" title="发送 Ctrl-D (EOF)">^D</button>
      <button class="lv-btn term-tb-jump" title="跳到底部跟随实时 (Ctrl+End)">⤓ 跳底</button>
      <button class="lv-btn term-tb-ts" title="时间戳注入：新输出行首加 [HH:MM:SS.mmm]，排障定位用">⏱ 时间戳</button>
    </div>`}
    <div class="output-wrap">
      <div class="xterm-wrap" data-xterm="${portId}"></div>
      <div class="xterm-bottom-pad"></div>
      <div class="term-search-splitter"></div>
      <div class="term-search-pane">
        <div class="term-search-head">
          <input type="text" class="term-search-input" placeholder="查找关键字…（回车搜索全部，Shift+回车跳下一个）" autocomplete="off">
          <input type="text" class="term-search-exclude" placeholder="排除（多个用 | 分隔，支持正则）" title="命中行含任一排除模式则剔除。多个用 | 分隔，支持正则。例：bsp.err | timeout" autocomplete="off">
          <span class="term-search-count"></span>
          <button class="btn ghost term-search-collapse" title="折叠分栏">▾</button>
        </div>
        <div class="term-search-results"></div>
      </div>
    </div>
  `;

  // 终端工具栏（仿日志 tab 的 log-viewer-toolbar）：串口/SSH 专属功能按钮
  // 放连接区内，tab 栏保持整洁——按钮只作用于本连接
  // claude 终端不渲染工具栏（上面的 innerHTML 已跳过）：串口专属功能（清屏/时间戳/
  // 暂停滚屏/新日志）对 claude 无意义，^C/^D/跳底也不再要——按需求整栏去掉。
  const _noTb = meta.kind === 'claude';
  const tb = _noTb ? {} : {
    pause: wrap.querySelector('.term-tb-pause'),
    clear: wrap.querySelector('.term-tb-clear'),
    newlog: wrap.querySelector('.term-tb-newlog'),
    ctrlc: wrap.querySelector('.term-tb-ctrlc'),
    ctrld: wrap.querySelector('.term-tb-ctrld'),
    jump: wrap.querySelector('.term-tb-jump'),
    ts: wrap.querySelector('.term-tb-ts'),
  };
  if (!_noTb) {
    tb.pause.onclick = () => {
      conn.paused = !conn.paused;
      tb.pause.textContent = conn.paused ? '▶ 继续' : '⏸ 暂停';
      tb.pause.classList.toggle('active', conn.paused);
      if (!conn.paused) { conn.autoScroll = true; try { conn.term.scrollToBottom(); } catch(e){} }
    };
    tb.clear.onclick = () => {
      try { conn.term.clear(); } catch(e){}
      conn.kwDecorLastRow = 0;
      conn.kwDecorations.forEach(d => { try { d.dispose(); } catch(e){} });
      conn.kwDecorations = [];
      fetch('/api/clear_buffer', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId})});
    };
    tb.newlog.onclick = async () => {
      try {
        const r = await fetch('/api/new_log', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId})});
        const j = await r.json();
        showBanner('已开新日志：' + (j.log_path || ''));
      } catch(e) { showBanner('开新日志失败：' + e, 6000, true); }
    };
    tb.ctrlc.onclick = () => termSendRaw(portId, [3]);
    tb.ctrld.onclick = () => termSendRaw(portId, [4]);
    tb.jump.onclick = () => jumpToBottom(portId);
    tb.ts.onclick = () => {
      conn.tsEnabled = !conn.tsEnabled;
      tb.ts.classList.toggle('active', conn.tsEnabled);
      showBanner(conn.tsEnabled ? '已开启时间戳注入（新输出行首加 [HH:MM:SS.mmm]）' : '已关闭时间戳注入');
    };
  }

  const conn = {
    portId,  // 用于搜索分栏调 /api/search 时定位连接（不依赖 activePortId）
    meta, tab, wrap,
    xtermWrap: wrap.querySelector(`[data-xterm="${portId}"]`),
    term: null, fit: null, search: null,
    sse: null,
    paused: false,
    autoScroll: true,
    pendingRaw: '',   // 历史加载期间缓冲的实时 raw，loadBuffer 完成后 flush
    // 历史分页（基于后端 buf，xterm 滚动到底即实时流；向上翻历史用分页 API）
    hasMore: true,
    oldestSeq: null,
    loadingMore: false,
    loadingHistory: false,
    // 全屏模式（top/htop）：仅用于显示提示条
    inScreen: false,
    screenOverlay: null,
    // 命令行流式高亮状态：cmdHL=true 表示当前处于命令行（# 之后），逐字符染绿
    cmdHL: false,
    // 关键字常驻高亮：记录已加 decoration 的行范围
    kwDecorLastRow: 0,
    kwDecorations: [],
    // 串口搜索分栏（仿日志查看器）
    termSearchPane: wrap.querySelector('.term-search-pane'),
    termSearchInput: wrap.querySelector('.term-search-input'),
    termSearchExclude: wrap.querySelector('.term-search-exclude'),
    termSearchResults: wrap.querySelector('.term-search-results'),
    termSearchCount: wrap.querySelector('.term-search-count'),
    termSearchState: { q: '', ex: '', results: [], idx: 0 },
    termSplitMove: null, termSplitUp: null,
  };

  // ---- 创建 xterm 实例 ----
  conn.term = new Terminal({
    fontFamily: '"Cascadia Code", "JetBrains Mono", "Consolas", "Menlo", monospace',
    fontSize: (typeof termFontSize === 'number') ? termFontSize : 13,   // 设置/Ctrl+=/- 全局字号
    lineHeight: 1.3,
    cursorBlink: true,
    cursorStyle: 'bar',
    scrollback: 100000,       // 大回滚缓冲，配合后端分页
    allowProposedApi: true,
    convertEol: false,        // 保留原始 \r\n，设备输出原样
    theme: _termThemeFor(document.documentElement.getAttribute('data-theme') || 'deepblue'),
  });
  conn.fit = new FitAddon.FitAddon();
  conn.search = new SearchAddon.SearchAddon();
  conn.term.loadAddon(conn.fit);
  conn.term.loadAddon(conn.search);
  try { conn.term.loadAddon(new WebLinksAddon.WebLinksAddon()); } catch(e) {}
  conn.term.open(conn.xtermWrap);
  // WebGL2 renderer：GPU 加速 glyph 渲染，高吞吐滚动不再卡（Tabby/Windows Terminal 同思路）。
  // 加载失败（无 WebGL2/驱动异常）自动回退默认 DOM 渲染，不影响功能
  try {
    if (window.WebglAddon) {
      const webgl = new WebglAddon.WebglAddon();
      webgl.onContextLoss(() => { try { webgl.dispose(); } catch(_){} });
      conn.term.loadAddon(webgl);
      conn._webgl = webgl;
    }
  } catch(e) {}
  conn._fitTerm = () => { try { conn.fit.fit(); } catch(e) {} };   // 字号热调后重排（theme.js applyFontSettings 用）
  try { conn.fit.fit(); } catch(e) {}

  // ---- PTY 尺寸同步（claude 终端）：xterm onResize → /api/resize → ConPTY setwinsize。
  // debounce 200ms（拖拽窗口 fit 高频触发）；尺寸未变短路。初始 fit 也会触发一次——
  // 恰好把真实尺寸同步给 PTY（纠正 spawn 时猜测的 120x30），无害且正确。
  conn._lastCols = 0; conn._lastRows = 0;
  conn.term.onResize(({cols, rows}) => {
    if (!conn.meta || conn.meta.kind !== 'claude') return;
    clearTimeout(conn._resizeTimer);
    conn._resizeTimer = setTimeout(() => {
      if (connections[portId] !== conn) return;
      if (conn._lastCols === cols && conn._lastRows === rows) return;
      conn._lastCols = cols; conn._lastRows = rows;
      fetch('/api/resize', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({port_id: portId, cols, rows})}).catch(() => {});
    }, 200);
  });

  // ---- Ctrl+C 复制选中（有选中→复制；无选中→发 ^C 中断）----
  // ---- Ctrl+V 粘贴剪贴板内容到串口 ----
  // ---- Ctrl+F 查找全部（打开串口下方搜索分栏，列出全部命中行）----
  conn.term.attachCustomKeyEventHandler(e => {
    if (e.type !== 'keydown') return true;
    // Ctrl+=/- / 0：字号调节（xterm 捕获键盘，document keydown 收不到——
    // 必须在 xterm 的自定义处理里接管，否则"终端内快捷键调字号不生效"）
    if (e.ctrlKey && !e.altKey && !e.shiftKey) {
      if (e.key === '+' || e.key === '=') {
        if (typeof applyFontSettings === 'function')
          applyFontSettings(Math.max(10, Math.min(24, termFontSize + 1)), uiZoom, true);
        return false;
      }
      if (e.key === '-' || e.key === '_') {
        if (typeof applyFontSettings === 'function')
          applyFontSettings(Math.max(10, Math.min(24, termFontSize - 1)), uiZoom, true);
        return false;
      }
      if (e.key === '0') {
        if (typeof applyFontSettings === 'function') applyFontSettings(13, 100, true);
        return false;
      }
    }
    if (e.ctrlKey && e.key === 'c') {
      const sel = conn.term.getSelection();
      if (sel) { try { navigator.clipboard.writeText(sel); } catch(_){} return false; }
    }
    if (e.ctrlKey && (e.key === 'v' || e.key === 'V')) {
      // 异步读剪贴板（原生 Win32，无 WebView2 权限弹窗），拿到文本后编码为字节发给串口
      _pasteToConn(conn);
      return false;  // 阻止 xterm 默认行为
    }
    if (e.ctrlKey && (e.key === 'f' || e.key === 'F')) {
      toggleTermSearchPane(conn, true);
      conn.termSearchInput.focus(); conn.termSearchInput.select();
      return false;
    }
    return true;
  });

  // ---- 终端快捷键映射（config.json term_keys，设置界面可改）----
  // right_action: ctrl_menu（Ctrl+右键弹菜单，默认）/ right_menu（右键直接弹菜单）
  //              / right_paste（右键直接粘贴）；Shift+右键恒为粘贴（PuTTY 习惯）
  // auto_copy: 选中松开鼠标即自动复制（PuTTY 风格）
  conn.termKeys = { right_action: 'ctrl_menu', auto_copy: false };
  fetch('/api/theme').then(r => r.json()).then(j => {
    if (j.ok && j.term_keys) conn.termKeys = j.term_keys;
  }).catch(() => {});
  conn.term.onSelectionChange(() => {
    if (conn.termKeys && conn.termKeys.auto_copy) {
      const sel = conn.term.getSelection();
      if (sel) { try { navigator.clipboard.writeText(sel); } catch(_){} }
    }
  });

  // ---- Ctrl+右键上下文菜单 / Shift+右键直接粘贴（PuTTY 习惯，与 Ctrl+V 同款）----
  conn.xtermWrap.addEventListener('contextmenu', e => {
    if (e.shiftKey) {  // Shift+右键 = 粘贴剪贴板
      e.preventDefault();
      _pasteToConn(conn, true);
      return;
    }
    const act = (conn.termKeys && conn.termKeys.right_action) || 'ctrl_menu';
    if (act === 'right_paste') {  // 右键直接粘贴（不弹菜单）
      e.preventDefault();
      _pasteToConn(conn, true);
      return;
    }
    if (act === 'right_menu') {   // 右键直接弹菜单（不需 Ctrl）
      e.preventDefault();
      showCtxMenu(e.clientX, e.clientY, conn);
      return;
    }
    if (!e.ctrlKey) return;  // ctrl_menu：普通右键保持 xterm 默认行为
    e.preventDefault();
    showCtxMenu(e.clientX, e.clientY, conn);
  });

  // ---- claude TUI 滚轮 → PgUp/PgDn（最初方案，唯一模式）----
  // claude TUI 只在流式生成中响应 PgUp/PgDn（打开 transcript 滚动视图，只翻内容
  // 不动输入框），生成结束视图自动关闭；空闲时穷举实测无任何键能开滚动视图。
  // 滚轮一律转 PgUp/PgDn：生成中即翻即响应；空闲时按键被 TUI 吃掉、无副作用。
  // （此前几轮的双模式分流/_rawVol 判据方案全部回退——生成中/空闲判据误判导致
  //  "滚轮不响应"反复翻车，宁可空闲滚轮无效也不牺牲生成中翻阅的可靠性。）
  conn._wheelAcc = 0;
  conn.xtermWrap.addEventListener('wheel', e => {
    if (!(conn.meta && conn.meta.kind === 'claude')) return;
    e.preventDefault();
    e.stopPropagation();
    const dir = e.deltaY > 0 ? 1 : -1;
    if (Math.sign(conn._wheelAcc) !== dir) conn._wheelAcc = 0;   // 反向时丢半截累积，防抖
    conn._wheelAcc += e.deltaY;
    const lines = Math.trunc(conn._wheelAcc / 40);   // 40 Δ/行
    if (!lines) return;
    conn._wheelAcc -= lines * 40;
    const seq = lines > 0 ? '\x1b[6~' : '\x1b[5~';   // PgDn / PgUp（实测有效）
    const bytes = [];
    for (let i = 0; i < seq.length; i++) bytes.push(seq.charCodeAt(i));
    termSendRaw(portId, bytes);
  }, {capture: true, passive: false});

  // ---- xterm 输入 → 串口 ----
  conn.term.onData(data => {
    if (conn.paused) return;
    // claude 空闲翻页中开始打字：立刻跳回底部——全翻模式下输入框画在缓冲区
    // 底部（claude 不切备用屏），翻上去后不可见，不跳回用户会以为输入丢了
    if (conn.meta && conn.meta.kind === 'claude' && !conn.autoScroll) {
      conn.autoScroll = true;
      try { conn.term.scrollToBottom(); } catch(e){}
    }
    // data 是字符串（已按字符拆分），编码为字节发送
    const bytes = [];
    for (let i = 0; i < data.length; i++) {
      const code = data.charCodeAt(i);
      if (code < 128) bytes.push(code);
      else { for (const b of new TextEncoder().encode(data[i])) bytes.push(b); }
    }
    if (bytes.length) termSendRaw(portId, bytes);
  });

  // ---- 滚动检测：到底自动跟实时 ----
  // 注：深历史翻阅走「📜 历史」tab（虚拟列表，G 级不卡），主 xterm 不再 reset 重写加载更早历史
  conn.term.onScroll(() => {
    const vp = conn.xtermWrap.querySelector('.xterm-viewport');
    if (!vp) return;
    const atBottom = vp.scrollHeight - vp.scrollTop - vp.clientHeight < 30;
    conn.autoScroll = atBottom;
  });

  // ---- 全屏模式提示条（xterm 自身处理全屏序列，这里只显示提示 + 退出按钮）----
  // claude 终端不建：新版 claude fullscreen renderer 的 TUI 重绘会触发全屏检测误报
  // （提示条「top/htop」对 claude 完全不适用且遮挡界面）；串口/SSH 场景保持不变
  if (meta.kind !== 'claude') {
    const overlay = document.createElement('div');
    overlay.className = 'screen-overlay';
    overlay.dataset.screen = portId;
    overlay.innerHTML = `
      <div class="screen-hint">
        <span class="dot"></span><span>全屏模式（top/htop）— 实时刷新中</span>
        <span class="esc" data-screen-esc="${portId}">退出 ↩</span>
      </div>
    `;
    wrap.querySelector('.output-wrap').appendChild(overlay);
    conn.screenOverlay = overlay;
    overlay.querySelector(`[data-screen-esc="${portId}"]`).onclick = () => {
      termSendRaw(portId, [3]);  // Ctrl-C 中断 top
    };
  }

  // 插入 DOM
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  // 标签按 COM 号数字排序插入：找到第一个比当前大的标签，插它前面
  const _comKey = pid => { const m = /^COM(\d+)$/i.exec(pid); return m ? +m[1] : 9999; };
  const curKey = _comKey(portId);
  let inserted = false;
  for (const t of tabs.querySelectorAll('.tab')) {
    if (_comKey(t.dataset.portId) > curKey) {
      tabs.insertBefore(tab, t);
      inserted = true;
      break;
    }
  }
  if (!inserted) tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  termArea.appendChild(wrap);
  // 拖拽排序（所有 tab 类型通用，见 tab-drag.js）
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);

  // SSE
  connectSSE(portId, conn);

  // 串口搜索分栏：拖分隔条 + 回车搜索 + 折叠按钮
  initTermSplitter(conn);
  // 回车重新搜索（串口 buf 动态变化，每次都需重搜）；Shift+回车跳下一个命中
  conn.termSearchInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      if (e.shiftKey) {
        const st = conn.termSearchState;
        if (st.results.length) {
          st.idx = (st.idx + 1) % st.results.length;
          jumpToTermHit(conn, st.idx);
          highlightTermHit(conn, st.idx);
        }
      } else {
        doTermSearch(conn);
      }
    }
  });
  wrap.querySelector('.term-search-collapse').onclick = () => {
    const isShown = conn.termSearchPane.style.display !== 'none';
    toggleTermSearchPane(conn, !isShown);
  };
  // 排除框回车触发搜索（与关键字框一致）；改动时不清空，只等回车重新搜
  conn.termSearchExclude.addEventListener('keydown', e => { if (e.key === 'Enter') doTermSearch(conn); });

  // 加载历史缓冲（写入 xterm）
  loadBuffer(portId, conn);
  return conn;
}

function switchTab(portId) {
  activePortId = portId;
  // 标签
  tabs.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.portId === portId));
  // 终端区
  termArea.querySelectorAll('.term-area').forEach(w => w.style.display = w.dataset.portId === portId ? 'flex' : 'none');
  // 侧边栏
  portList.querySelectorAll('.port-item').forEach(p => p.classList.toggle('active', p.dataset.portId === portId));
  // 切换后重新 fit 并聚焦 xterm（等 display:flex 生效后再 fit，否则算出 0 尺寸）
  const conn = connections[portId];
  if (conn) {
    if (conn.meta.kind === 'log') {
      // 日志 tab：重渲染虚拟列表（display:flex 后尺寸才正确）
      requestAnimationFrame(() => requestAnimationFrame(() => renderLogSlice(conn)));
    } else if (conn.meta.kind === 'editor') {
      // 编辑器 tab：.note 聚焦 Editor.js 区，.txt 聚焦 textarea
      requestAnimationFrame(() => {
        try {
          if (conn.editor && conn.holder) {
            const ce = conn.holder.querySelector('.codex-editor [contenteditable]');
            if (ce) ce.focus();
          } else if (conn.ta) conn.ta.focus();
        } catch(e){}
      });
    } else {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        try { conn.fit.fit(); } catch(e){}
        try { conn.term.focus(); } catch(e){}
      }));
    }
    // 若分析标签正显示，刷新一次（数据源已切到新连接的 buffer）
    const activePane = document.querySelector('.panel-tab.active');
    if (activePane && activePane.dataset.pane === 'analyze') renderAnalyze();
  }
}

// 窗口/面板尺寸变化时重新 fit 活动 xterm
window.addEventListener('resize', () => {
  const conn = connections[activePortId];
  if (conn) {
    if (conn.meta.kind === 'log') {
      renderLogSlice(conn);
      // 搜索结果列表同渲染：容器变高不触发 scroll，renderLogResults 的
      // 相等性短路继续成立 → 底部新增区域空白。复位渲染游标强制重算。
      const ls = conn.logState;
      if (ls && ls.searchTotal) { ls.resRenderStart = -1; ls.resRenderEnd = -1; renderLogResults(conn); }
    }
    else { try { conn.fit.fit(); } catch(e){} }
  }
});

// SSE 收到 raw 字节流 → 写入 xterm；screenctl → 切换提示条
function appendRaw(portId, text) {
  const conn = connections[portId];
  if (!conn || conn.paused) return;
  // 历史还在加载时先缓冲 raw，等历史写完再 flush，避免实时数据插到历史前面/重复
  if (conn.loadingHistory) { conn.pendingRaw += text; return; }
  // 写合并：多个 SSE chunk 攒一帧再一次性 write，减少 xterm.write 调用次数。
  // 高吞吐时每次 write 都有同步解析开销，合并后渲染次数 ≈ 帧率（60fps），输入不再卡顿。
  // flush 调度用 rAF + 500ms setTimeout 双保险：窗口最小化时 rAF 停发，
  // setTimeout 仍被节流执行（~1s 一次），队列持续消化不会无界堆积
  conn._writeQueue = (conn._writeQueue || '') + text;
  if (conn._writeQueue.length > 1048576) {  // 1MB 保险上限：超限同步 flush 防极端堆积
    const data = conn._writeQueue;
    conn._writeQueue = '';
    if (conn._writePending) { clearTimeout(conn._writeFlushTimer); conn._writePending = false; }
    try { conn.term.write(data); } catch(e) {}
    return;
  }
  if (conn._writePending) return;
  conn._writePending = true;
  const flush = () => {
    if (connections[portId] !== conn) { conn._writeQueue = ''; return; }
    conn._writePending = false;
    const data = conn._writeQueue;
    conn._writeQueue = '';
    if (data && !conn.paused) {
      let out = data;
      // 命令行流式高亮：先在原始流上识别行首 #/$/> （时间戳会破坏行首判断，故高亮在前）
      if (!conn.inScreen) out = _hlCmdStream(out, conn);
      // 时间戳注入：在高亮后的行首插时间戳（ts 在 ANSI 高亮码之前，两者共存）
      if (conn.tsEnabled && !conn.inScreen) out = _injectTs(out, conn);
      conn.term.write(out);
      // 关键字常驻高亮：对新写入的行扫描
      scheduleKwHighlight(conn);
      // 跟随到底：xterm 只在"精确贴底"时才自动滚，onScroll 的 30px 宽容阈值内
      // （autoScroll=true 但视口差零点几行）新数据不触发内建滚动，底部空隙随数据
      // 增长越拉越大——偶现留白 3~4 行的根因。跟随模式下显式贴底纠偏。
      if (conn.autoScroll && !conn.inScreen) { try { conn.term.scrollToBottom(); } catch(e){} }
    }
  };
  requestAnimationFrame(flush);
  conn._writeFlushTimer = setTimeout(flush, 500);  // 后台兜底（rAF 停发时最多 500ms 必 flush）
}
// 逐行时间戳注入（tio 同款，BSP 排障刚需）：每行行首加 [HH:MM:SS.mmm]。
// 只处理行式输出：全屏应用（top/htop，inScreen）期间原样透传，不破坏光标控制。
// 按 \n 切分，每个非首段的行开始处插时间戳（行首 \r 先剥离再放回）。
// 退格/回车覆盖等字符级控制在行内原样保留。
function _tsNow() {
  const d = new Date();
  return d.toTimeString().slice(0, 8) + '.' + String(d.getMilliseconds()).padStart(3, '0');
}
function _injectTs(data, conn) {
  if (conn._tsAtLS === undefined) conn._tsAtLS = true;  // 跨 chunk 行首状态
  const parts = data.split('\n');
  const ts = '\x1b[90m[' + _tsNow() + ']\x1b[0m ';
  let out = '';
  for (let i = 0; i < parts.length; i++) {
    let seg = parts[i];
    const atLS = (i === 0) ? conn._tsAtLS : true;  // 首段沿用跨 chunk 状态，其余段都在行首
    if (i > 0) out += '\n';
    if (seg === '') continue;         // 空段（连续 \n）：不注入
    let pre = '';
    if (seg.startsWith('\r')) { pre = '\r'; seg = seg.slice(1); }
    if (seg === '') { out += pre; continue; }  // 行只有 \r：不注入
    out += pre + (atLS ? ts : '') + seg;
  }
  // 最后一段无 \n（未闭合）：保持其行首状态；有 \n：回到行首
  conn._tsAtLS = parts[parts.length - 1] === '' || data.endsWith('\n');
  return out;
}
// 命令行流式高亮（mobaxterm 风格）：# 提示符及之后用户输入逐字符染色。
// 关键约束：串口命令是逐字符 echo 的，不能整行缓冲重写（否则 # ls# ls 重复）。
// 故逐 chunk 扫描，状态 conn.cmdHL 跨 chunk 保持：遇行首 # 进命令行（紫提示符+绿后续），
// 遇 \n/\r 退出复位；ANSI 控制序列与 \b 等控制符整体透传，不改变高亮状态。
function _hlCmdStream(data, conn) {
  if (conn.cmdHL === undefined) conn.cmdHL = false;
  if (conn._hlAtLS === undefined) conn._hlAtLS = true;  // 是否在行首（未见可见字符）
  let out = '';
  for (let i = 0; i < data.length; i++) {
    const ch = data[i];
    const code = data.charCodeAt(i);
    // ANSI 控制序列 \x1b[...letter：整段透传，不影响高亮状态
    if (ch === '\x1b') {
      let j = i + 1;
      if (data[j] === '[') {
        j++;
        while (j < data.length && !/[\x40-\x7e]/.test(data[j])) j++;
        if (j < data.length) j++;
      } else { j = i + 2; }
      out += data.slice(i, j);
      i = j - 1;
      continue;
    }
    // \n / \r：退出命令行，复位色
    if (ch === '\n' || ch === '\r') {
      if (conn.cmdHL) { out += '\x1b[0m'; conn.cmdHL = false; }
      out += ch;
      conn._hlAtLS = true;
      continue;
    }
    // 行首 # ：进入命令行（紫色提示符 + 绿色后续输入）
    if ((ch === '#' || ch === '$' || ch === '>') && conn._hlAtLS && !conn.cmdHL) {
      out += '\x1b[92m' + ch;
      conn.cmdHL = true;
      conn._hlAtLS = false;
      continue;
    }
    // 空格/制表：行首空白不取消行首状态（让  # 仍触发）；命令行内原样
    if (ch === ' ' || ch === '\t') { out += ch; continue; }
    // 其他控制符（\b \v \f 等）：透传，不改变行首状态
    if (code < 0x20) { out += ch; continue; }
    // 可见字符：命令行内原样（绿色作用中），非命令行原样；取消行首状态
    out += ch;
    conn._hlAtLS = false;
  }
  return out;
}
function enterScreen(portId, conn) {
  if (conn.inScreen) return;
  if (!conn.screenOverlay) return;   // claude tab 不建 overlay（防误报），事件忽略
  conn.inScreen = true;
  conn.screenOverlay.classList.add('show');
}
function exitScreen(portId, conn) {
  if (!conn.inScreen) return;
  conn.inScreen = false;
  if (conn.screenOverlay) conn.screenOverlay.classList.remove('show');
}

// 构建一行 DOM（仅回放面板仍用 DOM 行渲染，主终端已改用 xterm）
function buildLineDiv(item) {
  const div = document.createElement('div');
  div.className = 'line tag-' + (item.tag || 'text');
  if (item.seq != null) div.dataset.seq = item.seq;
  const ts = document.createElement('span');
  ts.className = 'ts';
  ts.textContent = item.ts ? fmtTs(item.ts) : '';
  div.appendChild(ts);
  div.appendChild(document.createTextNode(item.text || ''));
  return div;
}

// DOM 节点上限：方向性裁剪（v0.3.0 已废弃，xterm 自管缓冲；保留空壳避免引用报错）
function trimDom(conn) {}

function renderTermInput(conn) {}

function termSendRaw(portId, bytes) {
  // 微批合并：连续按键（打字/粘贴）攒 ≤8ms 一批一次 POST。
  // 之前每键一次 fetch：WebView2 网络栈 + Flask 线程开销叠加，打字时输入明显迟缓。
  // 8ms < 人感知阈值且不影响交互命令（回车后的命令行完整性由设备端解析）。
  let b = connections[portId];
  if (!b) {  // 未知连接（已关闭）：直接发，走原路径
    fetch('/api/send_raw', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId, bytes})});
    return;
  }
  b._sendQ = (b._sendQ || []).concat(bytes);
  if (b._sendTimer) return;
  b._sendTimer = setTimeout(() => {
    b._sendTimer = null;
    const q = b._sendQ; b._sendQ = [];
    if (!q.length || connections[portId] !== b) return;
    fetch('/api/send_raw', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({port_id: portId, bytes: q})});
  }, 8);
}

function connectSSE(portId, conn) {
  conn.sse = new EventSource('/api/stream?port_id=' + encodeURIComponent(portId));
  conn.sse.onmessage = (e) => {
    try {
      const item = JSON.parse(e.data);
      if (item.kind === 'raw') {
        appendRaw(portId, item.data);
        return;
      }
      if (item.kind === 'screenctl') {
        if (item.state === 'exit') exitScreen(portId, conn);
        else if (item.state === 'enter') enterScreen(portId, conn);
        return;
      }
    } catch(err) {}
  };
  conn.sse.onerror = () => {
    conn.sse.close();
    setTimeout(() => { if (connections[portId]) connectSSE(portId, conn); }, 2000);
  };
}

// ============================================================
// 关键字常驻高亮（xterm decoration）
// ============================================================
