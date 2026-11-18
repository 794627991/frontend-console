// 后端日志面板（2.4.4，用户需求）：点标题栏版本号查看。
//
// 定位：这是**指定的调试手段**——任何报错、警告、有用信息都应能在里看到。
// 后端侧三层收口（src/backend_log.py）：接管 stdout/stderr、log() 主动埋点、
// 标准库 logging 桥接。容量 10MB（按字节，非按行数）。
//
// 交互：
//   · 点版本号开/关；开着时每 2s 增量拉新行（since=last_seq）
//   · 面板可拖动（抓标题栏），位置记在 localStorage
//   · 按级别过滤（全部 / 仅错误 / 仅警告+错误）、按来源标签过滤
//   · 「清空」只清内存缓冲，不影响任何磁盘文件
//   · 自动滚到底；用户手动往上翻时暂停自动滚动
// 模块化一期（js-modularization 分支）：本文件已转 ES module（index.html
// type="module"）——IIFE 壳已剥，缩进保持原样。对外表面仅
// window.__backendLogToggle 挂载（无任何 JS/Python 调用方，排障直调用途
// 照旧）；ICO16/showBanner 等全局读在模块里照常解析（模块执行时经典
// 脚本已全部就位）。
let panel = null;
  let timer = null;
  let lastSeq = 0;
  let autoScroll = true;
  let levelFilter = 'all';        // all | err | warn
  let tagFilter = '';
  let allRows = [];               // 本地全量（最多保留一个上限，防 DOM/内存无界）
  let droppedLocal = false;       // 本地因上限截断过（界面提示用）
  let gen = 0;
  let _verLabel = '';   // 导出/复制头部追溯用（界面不显示）                    // 会话代际：show/clear 递增，丢弃在途旧响应
  let inFlight = false;           // 同一时刻只允许一个请求在途（背压）
  let catchUpMs = 0;              // truncated 追赶的退避间隔
  let tagEvicted = false;         // 所选来源已被本地窗口淘汰（提示用）

  const LOCAL_MAX = 50000;        // 前端本地保留行数上限（导出/复制用，超大时提示导出）
  // 首屏一次拉的行数。全量（limit=0）在 10MB 短行缓冲下是 25 万条 / 34MB
  // JSON，打开面板要卡 0.5-1s、JS 堆 100MB+（实测）。取尾部 20000 条够看
  // 当前状况，更早的历史走「导出」。
  const FIRST_LIMIT = 20000;
  const LEVEL_CLASS = { error: 'bl-error', warn: 'bl-warn', info: '' };
  const POS_KEY = 'fcBackendLogPos';

  function fmtBytes(n) {
    if (!n) return '0';
    if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB';
    if (n >= 1024) return (n / 1024).toFixed(0) + 'KB';
    return n + 'B';
  }

  /** UTF-8 真实字节数（用于剪贴板阈值；TextEncoder 不存在时退化为近似）。 */
  function utf8Len(s) {
    try {
      if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(s).length;
    } catch (e) {}
    let n = 0;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      n += c < 0x80 ? 1 : c < 0x800 ? 2 : (c >= 0xD800 && c < 0xDC00) ? 4 : 3;
    }
    return n;
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'backendLogPanel';
    panel.className = 'bl-panel';
    panel.innerHTML =
      '<div class="bl-head">' +
      '  <span class="bl-title">后端日志</span>' +
      '  <select class="bl-sel" data-bl="level" title="按级别过滤">' +
      '    <option value="all">全部</option>' +
      '    <option value="warn">警告以上</option>' +
      '    <option value="err">仅错误</option>' +
      '  </select>' +
      '  <select class="bl-sel" data-bl="tag" title="按来源过滤"><option value="">全部来源</option></select>' +
      '  <span class="bl-meta"></span>' +
      '  <span class="bl-spacer"></span>' +
      '  <button class="bl-btn" data-bl="copy" title="一键复制当前筛选结果到剪贴板">复制</button>' +
      '  <button class="bl-btn" data-bl="export" title="导出完整日志为 .txt（含版本号，便于追溯）">导出</button>' +
      '  <button class="bl-btn" data-bl="clear" title="清空内存缓冲（不影响磁盘文件）">清空</button>' +
      '  <button class="bl-btn bl-ico" data-bl="reload" title="强制刷新（原 F5）"></button>' +
      '  <button class="bl-btn bl-ico" data-bl="devtools" title="打开开发者工具（原 F12）"></button>' +
      '  <button class="bl-btn" data-bl="close" title="关闭（Esc）">✕</button>' +
      '</div>' +
      '<div class="bl-body"></div>' +
      '<div class="bl-foot">日志只驻内存（10MB 环形缓冲），进程退出即消失。<span class="bl-hint">拖动标题栏可移动</span></div>';
    document.body.appendChild(panel);

    // a624（用户令）：F5/F12 快捷键已全局屏蔽，能力由这两个图标按钮承接
    panel.querySelector('[data-bl="reload"]').innerHTML = ICO16.refresh;
    panel.querySelector('[data-bl="devtools"]').innerHTML = ICO16.devtools;

    panel.querySelector('[data-bl="close"]').onclick = hide;
    panel.querySelector('[data-bl="reload"]').onclick = () => {
      if (window.__fcHardReload) window.__fcHardReload();
    };
    panel.querySelector('[data-bl="devtools"]').onclick = () => {
      fetch('/api/window/devtools', { method: 'POST' })
        .then(r => r.json())
        .then(j => { if (!j.ok) showBanner(j.err || '打开开发者工具失败', 3000, true); })
        .catch(() => showBanner('打开开发者工具失败', 3000, true));
    };
    panel.querySelector('[data-bl="copy"]').onclick = doCopy;
    panel.querySelector('[data-bl="export"]').onclick = doExport;
    panel.querySelector('[data-bl="clear"]').onclick = () => {
      // 代际递增：在途的旧响应回来后要丢弃，否则会把刚清掉的行「复活」
      // （实测：清空后 DOM 是 0 行，陈旧响应又把它塞回到 20 行）。
      // a623R（审计 #9）：allRows/lastSeq **必须在这里同步复位**——原来
      // 放 POST .then 里，窗口期 2s 轮询以旧 lastSeq 发 GET、响应带着新
      // 代际通过检查、在复位之后处理 → 清空前的行整批塞回。同步复位后
      // 在途响应要么被旧代际丢弃，要么之后的拉取以 since=0 重来。
      gen++;
      inFlight = false;
      catchUpMs = 0;
      allRows = [];
      lastSeq = 0;
      droppedLocal = false;
      render();
      fetch('/api/backend_log/clear', { method: 'POST' })
        .then(() => {
          // a623R 复审（审计 #2）：同步复位之外**再断根一次**——同步复位
          // 与后端 clear 落地之间，truncated 追赶链（无句柄的 setTimeout
          // refresh）可能以新代际 + since=0 拉到清空前整批（后端还没处理
          // 完 clear），响应在 .then 之后到达就永久滞留。这里 gen++ 使
          // 全部在途响应作废，再复位 + 重拉——以 clear 落地为终态。
          gen++;
          allRows = [];
          lastSeq = 0;
          droppedLocal = false;
          render();
          refresh();
        })
        .catch(() => {});
    };
    panel.querySelector('[data-bl="level"]').onchange = (e) => {
      levelFilter = e.target.value; render();
    };
    panel.querySelector('[data-bl="tag"]').onchange = (e) => {
      tagFilter = e.target.value; render();
    };
    const body = panel.querySelector('.bl-body');
    body.addEventListener('scroll', () => {
      autoScroll = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    });
    makeDraggable(panel);
    restorePos();
    return panel;
  }

  // ---- 导出 / 一键复制 ----
  function fmtLine(x) {
    const lv = x.level === 'error' ? '[ERR]'
      : x.level === 'warn' ? '[WRN]' : '[INF]';
    const tag = x.tag ? '[' + x.tag + ']' : '';
    const src = (x.src && x.src !== 'log') ? x.src : '';
    const parts = [x.ts, lv, tag, src, x.text];
    return parts.filter(Boolean).join(' ');
  }

  function doExport() {
    // 走后端落盘。原来用 `<a download>` 触发浏览器下载——在 WebView2 里
    // **永远失败**：init.js 在 document 捕获阶段对任意 a[href] 无条件
    // preventDefault（防就地导航），`<a download>` 的下载动作被一并取消；
    // 且 pywebview 6.2.1 默认 ALLOW_DOWNLOADS=False，第二道拦截。
    // 两处都失败后原来还无条件弹「已导出」，用户永远拿不到文件。
    // 现在改成 POST /api/backend_log/save：后端弹原生保存框（或退回桌面）
    // 真写盘成功才提示，并显示保存路径。
    // 实测：临时 a 挂在 panel 外会触发「外部点击隐藏」，点导出后面板立刻
    // 关闭——所以第二参数 true 让捕获阶段的 hide 跳过这次点击。
    showBanner('正在导出…', 1500);
    fetch('/api/backend_log/save', { method: 'POST' })
      .then(r => r.json())
      .then(j => {
        if (j && j.ok) {
          showBanner('已导出到 ' + j.path, 6000);
        } else {
          showBanner('导出失败：' + ((j && j.err) || '未知错误'), 5000, true);
        }
      })
      .catch(() => showBanner('导出失败（后端无响应）', 4000, true));
  }

  function doCopy() {
    // 一键复制：复制**当前筛选结果**（用户可能只想复制错误），不是全量。
    // 头部同样带版本号，粘到聊天/工单里能直接追溯。
    const rows = allRows.filter(passes);
    if (!rows.length) { showBanner('当前没有可复制的日志', 2500, true); return; }
    // 超大文本剪贴板写入在 WebView2 里会失败或卡住，先提示走导出。
    // 按 UTF-8 真实字节估算（中文 3 字节/字、emoji 最多 4）——原来按
    // String.length（UTF-16 码元）比，中文实际字节是它的 3 倍，保护形同虚设。
    const approx = utf8Len(rows.map(fmtLine).join('\n'));
    if (approx > 4 * 1024 * 1024) {
      showBanner('内容约 ' + fmtBytes(approx) + '，请用「导出」保存完整日志', 4000, true);
      return;
    }
    const ver = _verLabel || '';
    const head = [
      '='.repeat(60),
      '前端控制台 ' + ver + ' 后端日志',
      '导出时间 : ' + new Date().toLocaleString('zh-CN'),
      '条数     : ' + rows.length,
      '='.repeat(60),
      '',
    ].join('\n');
    const text = head + rows.map(fmtLine).join('\n') + '\n';
    const done = () => {
      const btn = panel.querySelector('[data-bl="copy"]');
      const old = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(() => { btn.textContent = old; }, 1500);
    };
    // 优先 Clipboard API；WebView2 里可能被权限拦，退回 execCommand
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallback());
    } else {
      fallback();
    }
    function fallback() {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, text.length);
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
      // execCommand 返回 false 表示「没复制成」（无选区/失焦/权限），是个
      // 静默失败：原来无条件调 done()，用户以为复制成功，实际粘贴出的是上
      // 一次剪贴板内容（实测 execCommand 返回 false 仍显示「已复制」）。
      if (ok) done();
      else showBanner('复制失败，请用「导出」保存日志', 3500, true);
    }
  }

  // ---- 拖动 ----
  function makeDraggable(el) {
    const head = el.querySelector('.bl-head');
    head.style.cursor = 'move';
    let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
    head.addEventListener('mousedown', (e) => {
      if (e.target.closest('button, select')) return;   // 别拖到按钮上
      dragging = true;
      const r = el.getBoundingClientRect();
      // 改用 left/top 绝对定位（原来是 top/left 固定值，拖动要换成像素）
      el.style.left = r.left + 'px';
      el.style.top = r.top + 'px';
      el.style.width = r.width + 'px';
      el.style.height = r.height + 'px';
      sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top;
      e.preventDefault();
      document.body.style.userSelect = 'none';
      const move = (ev) => {
        if (!dragging) return;
        let nx = ox + (ev.clientX - sx);
        let ny = oy + (ev.clientY - sy);
        // 钳在视口内，别拖到看不见的地方
        nx = Math.max(-el.offsetWidth + 60, Math.min(nx, window.innerWidth - 60));
        ny = Math.max(0, Math.min(ny, window.innerHeight - 40));
        el.style.left = nx + 'px';
        el.style.top = ny + 'px';
      };
      const up = () => {
        dragging = false;
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        window.removeEventListener('blur', up);
        document.removeEventListener('keydown', onEsc);
        savePos();
      };
      // Alt+Tab / 窗口失焦时 mouseup 可能永远收不到——原来会留下
      // body.userSelect='none' 永久锁死（全站文字选不中）且位置不落盘。
      // 与 web/js/sidebar-resize.js 的既有兜底一致：blur + Esc 双兜底。
      const onEsc = (ev) => { if (ev.key === 'Escape') up(); };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
      window.addEventListener('blur', up);
      document.addEventListener('keydown', onEsc);
    });
  }

  function savePos() {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify({
        left: panel.style.left, top: panel.style.top,
        width: panel.style.width, height: panel.style.height,
      }));
    } catch (e) {}
  }

  /** 把面板位置钳制回当前视口（标题栏必须可见，否则无法拖动/关闭）。 */
  function clampPos() {
    if (!panel) return;
    if (!panel.style.left || !panel.style.top) return;
    const w = panel.offsetWidth || 1;
    const h = panel.offsetHeight || 1;
    const vw = window.innerWidth || 1024;
    const vh = window.innerHeight || 768;
    let x = parseFloat(panel.style.left);
    let y = parseFloat(panel.style.top);
    if (!isFinite(x) || !isFinite(y)) return;
    // 至少留 60px 标题栏在视口内（与拖动时的钳制口径一致）
    x = Math.max(-w + 60, Math.min(x, vw - 60));
    y = Math.max(0, Math.min(y, vh - 40));
    panel.style.left = x + 'px';
    panel.style.top = y + 'px';
  }

  function restorePos() {
    try {
      const s = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
      if (!s) return;
      if (s.left) panel.style.left = s.left;
      if (s.top) panel.style.top = s.top;
      if (s.width) panel.style.width = s.width;
      if (s.height) panel.style.height = s.height;
      // a600 对抗审计：外接屏保存的位置在拔屏/窗口缩小后可能整个跑到视口外
      // （实测 left=3000px,top=2200px 时面板在视口内像素数为 0，连关闭按钮
      // 都点不到，只能清 localStorage 才能恢复）。读出来后必须按当前视口钳制。
      clampPos();
      panel.dataset.moved = '1';
    } catch (e) {}
  }

  // ---- 渲染 ----
  // 统一「来源标签」口径：主动埋点用 tag，流输出用 src（stdout 不带标签）。
  // a600 对抗审计：原来 passes() 用 `(x.tag||x.src||'')`，而 syncTagOptions()
  // 和 rowHtml() 用 `x.tag || (x.src!=='stdout' ? x.src : '')`——两者对
  // stdout 行判定不同，导致选「全部来源以外的某项」时 stdout 行显示标签却
  // 永远筛不出来。收敛到这一个函数。
  function labelOf(x) {
    return x.tag || (x.src && x.src !== 'stdout' && x.src !== 'log' ? x.src : '');
  }

  function passes(x) {
    if (levelFilter === 'err' && x.level !== 'error') return false;
    if (levelFilter === 'warn' && x.level === 'info') return false;
    if (tagFilter && labelOf(x) !== tagFilter) return false;
    return true;
  }

  function rowHtml(x) {
    const cls = LEVEL_CLASS[x.level] || '';
    const srcCls = x.src === 'stderr' ? ' bl-src-err' : '';
    const label = labelOf(x);
    return '<div class="bl-row ' + cls + srcCls + '" data-seq="' + x.seq + '">' +
      '<span class="bl-ts">' + esc(x.ts) + '</span>' +
      (label ? '<span class="bl-tag">' + esc(label) + '</span>' : '') +
      '<span class="bl-txt">' + esc(x.text) + '</span></div>';
  }

  const DOM_MAX = 2000;           // 面板一次最多渲染的行数（超出只显示尾部）

  // a623R（审计 #11）：追加式快路径的渲染游标——已渲染的最大 seq + 当前
  // DOM 是否为「本次过滤条件下的全量产物」。每 2s 轮询新行到达时若满足
  // 快路径条件只 append 增量行，不做 2000 行 innerHTML 全量重建（重解析
  // 数万节点是面板打开期最大 CPU 项，且全量重建抹掉用户选区）。
  let renderedTailSeq = 0;
  let renderedFull = false;
  let renderedFilterKey = '';

  function render() {
    if (!panel) return;
    const body = panel.querySelector('.bl-body');
    // 过滤条件与上次渲染时不同 → DOM 里是旧口径的行，只能全量
    const filterKey = levelFilter + '|' + tagFilter;
    if (filterKey !== renderedFilterKey) { renderedFull = false; renderedFilterKey = filterKey; }
    const rows = allRows.filter(passes);
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    if (!rows.length) {
      body.innerHTML = '<div class="bl-empty">' +
        (allRows.length ? '当前过滤条件下没有匹配的日志' : '还没有日志输出') + '</div>';
      renderedTailSeq = 0; renderedFull = false;
      return;
    }
    const last = rows[rows.length - 1];
    const hidden = rows.length - DOM_MAX;
    // 快路径：贴底 + 无截断 + DOM 尾行与游标吻合 + 确有新行 → 只 append。
    // 任一不满足（上翻看历史/切过滤/超 DOM_MAX/重渲染）走全量，语义不变。
    if (atBottom && renderedFull && hidden <= 0 && last.seq > renderedTailSeq &&
        body.lastElementChild && parseInt(body.lastElementChild.dataset.seq, 10) === renderedTailSeq) {
      let frag = '';
      for (const x of rows) {
        if (x.seq > renderedTailSeq) frag += rowHtml(x);
      }
      if (frag) body.insertAdjacentHTML('beforeend', frag);
      renderedTailSeq = last.seq;
      body.scrollTop = body.scrollHeight;   // 贴底分支 autoScroll 恒成立
      return;
    }
    // a600 对抗审计（滚动漂移）：原来每次新行到达都整块 innerHTML 重建，
    // 用户往上翻历史时滚动量不变但内容整体下移（实测每 2s 漂移 50 行、
    // 两次 100 行），根本没法看历史。现在：
    //   · 在底部（自动跟随）→ 直接只渲染尾部，保持贴底
    //   · 不在底部 → 记录视口内首个可见行的 seq，重建后按新序列恢复锚点
    const anchor = atBottom ? null : firstVisibleSeq(body);
    // 超出 DOM_MAX 时只渲染尾部，但必须**明确提示**——否则用户以为日志
    // 就这么多。完整内容请用「导出」。
    const tail = hidden > 0 ? rows.slice(-DOM_MAX) : rows;
    body.innerHTML =
      (hidden > 0
        ? '<div class="bl-empty">仅显示最近 ' + DOM_MAX + ' 行，'
          + '更早的 ' + hidden + ' 行请用「导出」查看</div>'
        : '') +
      tail.map(rowHtml).join('');
    renderedTailSeq = tail.length ? tail[tail.length - 1].seq : 0;
    renderedFull = true;
    if (anchor !== null) {
      restoreAnchor(body, anchor);
    } else if (autoScroll || atBottom) {
      body.scrollTop = body.scrollHeight;
    }
  }

  /** 视口内第一条可见行的 seq（行元素带 data-seq）。 */
  function firstVisibleSeq(body) {
    const top = body.scrollTop;
    const kids = body.children;
    for (let i = 0; i < kids.length; i++) {
      const el = kids[i];
      if (!el.dataset || el.dataset.seq === undefined) continue;
      if (el.offsetTop + el.offsetHeight > top) return parseInt(el.dataset.seq, 10);
    }
    return null;
  }

  /** 重建后把锚点行滚回视口顶部，避免内容漂移。 */
  function restoreAnchor(body, seq) {
    const sel = '.bl-row[data-seq="' + seq + '"]';
    const el = body.querySelector(sel);
    if (el) { body.scrollTop = el.offsetTop; return; }
    // 锚点行已被本地窗口淘汰：保持原滚动量（用户看的是历史，别强行弹底）
    body.scrollTop = Math.max(0, body.scrollTop);
  }

  function syncTagOptions() {
    const sel = panel.querySelector('[data-bl="tag"]');
    const tags = new Set();
    for (const x of allRows) {
      const t = labelOf(x);
      if (t) tags.add(t);
    }
    const cur = sel.value;
    sel.innerHTML = '<option value="">全部来源</option>' +
      Array.from(tags).sort().map(t =>
        '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('');
    if (cur && tags.has(cur)) { sel.value = cur; tagEvicted = false; }
    else if (cur) {
      // 所选的来源已被本地窗口淘汰（allRows 超 LOCAL_MAX 截断）。原来这里
      // 静默清空选择并切回「全部来源」，用户以为还在筛选、实际看到混杂
      // 结果（实测可见行数 100 → 2000），点复制还会把全部日志带出去。
      // 现在保留选择（附加一个占位项），并在 meta 里明说。
      tagFilter = cur;
      const opt = document.createElement('option');
      opt.value = cur;
      opt.textContent = cur + '（已淘汰）';
      sel.appendChild(opt);
      sel.value = cur;
      tagEvicted = true;
    }
  }

  function refresh() {
    if (!panel || panel.style.display === 'none') return;
    // 背压：同一时刻只允许一个请求在途。原来无互斥，2s 定时器与 truncated
    // 追赶、手动 refresh 会并发发出多个相同 since 的请求，旧响应后到会
    // 覆盖 lastSeq（游标回退）并造成重复行（实测同一响应叠加后 20 行里
    // 10 行重复）。inFlight 守卫是最简单可靠的解法。
    if (inFlight) return;
    inFlight = true;
    const myGen = gen;
    // a600 对抗审计：首屏原来是 limit=0（全量）。10MB 缓冲在短行场景能装
    // 25 万条、JSON 响应 34MB，打开面板直接卡 0.5-1s 且 JS 堆涨到 100MB+。
    // 改为首屏只取尾部一段（够看当前状况），往上翻历史请用「导出」。
    const lim = lastSeq === 0 ? FIRST_LIMIT : 20000;
    fetch('/api/backend_log?since=' + lastSeq + '&limit=' + lim)
      .then(r => r.json())
      .then(j => {
        inFlight = false;
        if (!j || !j.ok) return;
        // 会话代际：期间发生过 show()/clear()，这个响应属于旧会话，丢弃
        if (myGen !== gen) return;
        const incoming = j.lines || [];
        if (incoming.length) {
          // 只接受比游标新的行（乱序/重放防护），并按 seq 去重
          const fresh = incoming.filter(x => x.seq > lastSeq);
          if (fresh.length) {
            allRows = allRows.concat(fresh);
            if (allRows.length > LOCAL_MAX) {
              allRows = allRows.slice(-LOCAL_MAX);
              droppedLocal = true;        // 提示用户本地只保留最近部分
            }
            syncTagOptions();
            render();
          }
        } else if (!allRows.length) {
          render();
        }
        // 游标只允许前进（旧响应即使漏过代际检查也不会让它回退）
        if (j.last_seq > lastSeq) lastSeq = j.last_seq;
        const drop = j.dropped ? ' · 已丢弃 ' + j.dropped + ' 条（超容量）' : '';
        panel.querySelector('.bl-meta').textContent =
          fmtBytes(j.used_chars) + ' 字符 / ' + fmtBytes(j.capacity_chars) +
          ' · ' + (j.entries || 0) + ' 条' + drop +
          (j.truncated ? ' · 继续加载中' : '') +
          (j.head_truncated ? ' · 更早的行未加载（用「导出」看全部）' : '') +
          (j.lost ? ' · 已丢失 ' + j.lost + ' 条（你落后太久，缓冲已淘汰）' : '') +
          (droppedLocal ? ' · 本地仅保留最近 ' + LOCAL_MAX + ' 行' : '') +
          (tagEvicted ? ' · 所选来源已不在本地窗口' : '') +
          (j.installed === false ? ' · 缓冲未启用（子模式）' : '');
        // 后端一次没给完：退避后继续追，不做 setTimeout(...,0) 忙循环
        // （实测忙循环可达 4.2 QPS、单轮 77ms，占满主线程）。
        if (j.truncated) {
          catchUpMs = Math.min(catchUpMs ? catchUpMs * 2 : 120, 1500);
          setTimeout(refresh, catchUpMs);
        } else {
          catchUpMs = 0;
        }
      })
      .catch(() => {
        inFlight = false;
        catchUpMs = 0;
      });
  }

  function show() {
    ensurePanel();
    panel.style.display = 'flex';
    // 代际递增：关闭再开时，上一次会话还在途的响应必须作废，否则会往新
    // 会话的 allRows 里塞旧数据（实测 5 行变 9 行、游标回退到 since=4）。
    gen++;
    inFlight = false;
    catchUpMs = 0;
    lastSeq = 0;
    allRows = [];
    droppedLocal = false;
    autoScroll = true;
    // a662（用户令「界面版本号去掉」）：弹窗标题不再显示版本；仅导出/复制
    // 头部保留追溯用的版本号（从 /api/update/state 取，存模块变量）。
    fetch('/api/update/state').then(r => r.json()).then(j => {
      _verLabel = (j && j.current) ? 'v' + j.current : '';
    }).catch(() => {});
    render();
    refresh();
    if (!timer) timer = setInterval(refresh, 2000);
  }

  function hide() {
    if (panel) panel.style.display = 'none';
    if (timer) { clearInterval(timer); timer = null; }
  }

  function toggle() {
    if (panel && panel.style.display !== 'none') hide();
    else show();
  }

  function wire() {
    // a623R（审计 #2）：标题栏 ver 徽标在非最大化下被 a59x 的「纯图标」定调
    // 藏掉（.logo > span:not(.icon) 整链 display:none）——新增 topbar 图标钮
    // [data-bl-open] 作恒可见入口，与徽标共用同一 toggle
    document.querySelectorAll('[data-ver-badge], [data-bl-open]').forEach(el => {
      el.style.cursor = 'pointer';
      el.addEventListener('click', (e) => { e.stopPropagation(); toggle(); });
      if (el.tagName !== 'BUTTON') {
        el.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
        });
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panel && panel.style.display !== 'none') hide();
    });
    document.addEventListener('click', (e) => {
      if (!panel || panel.style.display === 'none') return;
      if (panel.contains(e.target)) return;
      if (e.target.closest && e.target.closest('[data-ver-badge], [data-bl-open]')) return;
      hide();
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
  window.__backendLogToggle = toggle;   // 排障/自动化可直调
