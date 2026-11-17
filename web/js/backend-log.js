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
(function () {
  let panel = null;
  let timer = null;
  let lastSeq = 0;
  let autoScroll = true;
  let levelFilter = 'all';        // all | err | warn
  let tagFilter = '';
  let allRows = [];               // 本地全量（最多保留一个上限，防 DOM/内存无界）
  let droppedLocal = false;       // 本地因上限截断过（界面提示用）

  const LOCAL_MAX = 50000;        // 前端本地保留行数上限（导出/复制用，超大时提示导出）
  const LEVEL_CLASS = { error: 'bl-error', warn: 'bl-warn', info: '' };
  const POS_KEY = 'fcBackendLogPos';

  function fmtBytes(n) {
    if (!n) return '0';
    if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB';
    if (n >= 1024) return (n / 1024).toFixed(0) + 'KB';
    return n + 'B';
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'backendLogPanel';
    panel.className = 'bl-panel';
    panel.innerHTML =
      '<div class="bl-head">' +
      '  <span class="bl-title">后端日志</span>' +
      '  <span class="bl-ver" title="当前版本（导出文件头部也带版本号）"></span>' +
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
      '  <button class="bl-btn" data-bl="close" title="关闭（Esc）">✕</button>' +
      '</div>' +
      '<div class="bl-body"></div>' +
      '<div class="bl-foot">日志只驻内存（10MB 环形缓冲），进程退出即消失。<span class="bl-hint">拖动标题栏可移动</span></div>';
    document.body.appendChild(panel);

    panel.querySelector('[data-bl="close"]').onclick = hide;
    panel.querySelector('[data-bl="copy"]').onclick = doCopy;
    panel.querySelector('[data-bl="export"]').onclick = doExport;
    panel.querySelector('[data-bl="clear"]').onclick = () => {
      fetch('/api/backend_log/clear', { method: 'POST' })
        .then(() => { allRows = []; lastSeq = 0; droppedLocal = false;
                      render(); refresh(); })
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
    // 走后端导出：头部带版本号/平台/缓冲统计，用户要求「日志要带版本号
    // 好追溯」。用 a[download] 触发下载，不在本函数里拼大字符串。
    const a = document.createElement('a');
    a.href = '/api/backend_log/export';
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    showBanner('已导出日志（含版本号与平台信息）', 3000);
  }

  function doCopy() {
    // 一键复制：复制**当前筛选结果**（用户可能只想复制错误），不是全量。
    // 头部同样带版本号，粘到聊天/工单里能直接追溯。
    const rows = allRows.filter(passes);
    if (!rows.length) { showBanner('当前没有可复制的日志', 2500, true); return; }
    // 超大文本（>4MB）剪贴板写入在 WebView2 里会失败或卡住，先提示走导出
    const approx = rows.reduce((n, x) => n + (x.text ? x.text.length : 0), 0);
    if (approx > 4 * 1024 * 1024) {
      showBanner('内容约 ' + fmtBytes(approx) + '，请用「导出」保存完整日志', 4000, true);
      return;
    }
    const ver = (panel.querySelector('.bl-ver') || {}).textContent || '';
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
      ta.select();
      try { document.execCommand('copy'); done(); }
      catch (e) { showBanner('复制失败，请用「导出」', 3000, true); }
      ta.remove();
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
        savePos();
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
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

  function restorePos() {
    try {
      const s = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
      if (!s) return;
      if (s.left) panel.style.left = s.left;
      if (s.top) panel.style.top = s.top;
      if (s.width) panel.style.width = s.width;
      if (s.height) panel.style.height = s.height;
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
    return '<div class="bl-row ' + cls + srcCls + '">' +
      '<span class="bl-ts">' + esc(x.ts) + '</span>' +
      (label ? '<span class="bl-tag">' + esc(label) + '</span>' : '') +
      '<span class="bl-txt">' + esc(x.text) + '</span></div>';
  }

  const DOM_MAX = 2000;           // 面板一次最多渲染的行数（超出只显示尾部）

  function render() {
    if (!panel) return;
    const body = panel.querySelector('.bl-body');
    const rows = allRows.filter(passes);
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    if (!rows.length) {
      body.innerHTML = '<div class="bl-empty">' +
        (allRows.length ? '当前过滤条件下没有匹配的日志' : '还没有日志输出') + '</div>';
      return;
    }
    // 超出 DOM_MAX 时只渲染尾部，但必须**明确提示**——否则用户以为日志
    // 就这么多（a600 对抗审计）。完整内容请用「导出」。
    const hidden = rows.length - DOM_MAX;
    const tail = hidden > 0 ? rows.slice(-DOM_MAX) : rows;
    body.innerHTML =
      (hidden > 0
        ? '<div class="bl-empty">仅显示最近 ' + DOM_MAX + ' 行，'
          + '更早的 ' + hidden + ' 行请用「导出」查看</div>'
        : '') +
      tail.map(rowHtml).join('');
    if (autoScroll || atBottom) body.scrollTop = body.scrollHeight;
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
    if (cur && tags.has(cur)) sel.value = cur;
    else if (cur) { sel.value = ''; tagFilter = ''; }
  }

  function refresh() {
    if (!panel || panel.style.display === 'none') return;
    // a600 对抗审计：首屏原来是 limit=20000。10MB 缓冲在短行场景能装
    // 远多于 2 万条（5000 条短行仅 20 万字符），首批只取 2 万条后 lastSeq
    // 直接跳到最新，中间那些行**永远不会再拉**（面板看着有数据，实则丢了一段）。
    // 改为首屏不限量（0=后端不截断），之后的增量仍按 since 拉。
    const lim = lastSeq === 0 ? 0 : 20000;
    fetch('/api/backend_log?since=' + lastSeq + '&limit=' + lim)
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok) return;
        const incoming = j.lines || [];
        if (incoming.length) {
          allRows = allRows.concat(incoming);
          if (allRows.length > LOCAL_MAX) {
            allRows = allRows.slice(-LOCAL_MAX);
            droppedLocal = true;        // 提示用户本地只保留最近部分
          }
          syncTagOptions();
          render();
        } else if (!allRows.length) {
          render();
        }
        lastSeq = j.last_seq || 0;
        const drop = j.dropped ? ' · 已丢弃 ' + j.dropped + ' 条（超容量）' : '';
        panel.querySelector('.bl-meta').textContent =
          fmtBytes(j.used_chars) + ' / ' + fmtBytes(j.capacity_chars) +
          ' · ' + (j.entries || 0) + ' 条' + drop +
          (j.truncated ? ' · 继续加载中' : '') +
          (droppedLocal ? ' · 本地仅保留最近 ' + LOCAL_MAX + ' 行' : '') +
          (j.installed === false ? ' · 缓冲未启用（子模式）' : '');
        // 后端一次没给完（新行数超过 limit）：snapshot 已把 last_seq 停在
        // 本次实际返回的最后一条，这里立即再拉一轮把剩下的追上，否则要
        // 等下一个 2s 周期才继续（面板会短暂少一段）。
        if (j.truncated) setTimeout(refresh, 0);
      })
      .catch(() => {});
  }

  function show() {
    ensurePanel();
    panel.style.display = 'flex';
    lastSeq = 0;
    allRows = [];
    droppedLocal = false;
    autoScroll = true;
    // 版本号显示在面板标题旁（用户令「启动时必须带上版本号，好追溯」）——
    // 与标题栏徽标同源（/api/update/state），保证与导出文件里的一致
    fetch('/api/update/state').then(r => r.json()).then(j => {
      const el = panel.querySelector('.bl-ver');
      if (el) el.textContent = (j && j.current) ? 'v' + j.current : '';
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
    document.querySelectorAll('[data-ver-badge]').forEach(el => {
      el.style.cursor = 'pointer';
      el.addEventListener('click', (e) => { e.stopPropagation(); toggle(); });
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panel && panel.style.display !== 'none') hide();
    });
    document.addEventListener('click', (e) => {
      if (!panel || panel.style.display === 'none') return;
      if (panel.contains(e.target)) return;
      if (e.target.closest && e.target.closest('[data-ver-badge]')) return;
      hide();
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
  window.__backendLogToggle = toggle;   // 排障/自动化可直调
})();
