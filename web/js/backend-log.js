// 后端日志面板（2.4.4，用户需求）：点标题栏版本号查看。
//
// 背景：以前 run_debug.bat 用 python.exe 启动，会弹一个 cmd 黑框，排障时
// 看的就是那个框里的 print。现在改 pythonw 无框启动，日志由后端环形缓冲
// （src/backend_log.py，只驻内存不写盘）接管，这里负责取出来显示。
//
// 交互：
//   · 点版本号开/关；面板开着时每 2s 增量拉新行（since=last_seq）
//   · Esc 或点面板外关闭
//   · 「清空」只清内存缓冲，不影响任何磁盘文件
//   · 自动滚到底；用户手动往上翻时暂停自动滚动（避免抢走阅读位置）
(function () {
  let panel = null;
  let timer = null;
  let lastSeq = 0;
  let autoScroll = true;

  const LEVEL_CLASS = { error: 'bl-error', warn: 'bl-warn', info: '' };

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'backendLogPanel';
    panel.className = 'bl-panel';
    panel.innerHTML =
      '<div class="bl-head">' +
      '  <span class="bl-title">后端日志</span>' +
      '  <span class="bl-meta"></span>' +
      '  <span class="bl-spacer"></span>' +
      '  <button class="bl-btn" data-bl="clear" title="清空内存缓冲（不影响磁盘文件）">清空</button>' +
      '  <button class="bl-btn" data-bl="close" title="关闭（Esc）">✕</button>' +
      '</div>' +
      '<div class="bl-body"></div>' +
      '<div class="bl-foot">日志只驻内存，进程退出即消失（用户指定不写盘）</div>';
    document.body.appendChild(panel);

    panel.querySelector('[data-bl="close"]').onclick = hide;
    panel.querySelector('[data-bl="clear"]').onclick = () => {
      fetch('/api/backend_log/clear', { method: 'POST' })
        .then(() => { lastSeq = 0; const b = panel.querySelector('.bl-body'); b.innerHTML = ''; refresh(); })
        .catch(() => {});
    };
    const body = panel.querySelector('.bl-body');
    body.addEventListener('scroll', () => {
      // 距底 >30px 视为用户在读历史，暂停自动滚
      autoScroll = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    });
    return panel;
  }

  function rowHtml(x) {
    const cls = LEVEL_CLASS[x.level] || '';
    const srcCls = x.src === 'stderr' ? ' bl-src-err' : '';
    return '<div class="bl-row ' + cls + srcCls + '">' +
      '<span class="bl-ts">' + esc(x.ts) + '</span>' +
      '<span class="bl-txt">' + esc(x.text) + '</span></div>';
  }

  function render(list, append) {
    const body = panel.querySelector('.bl-body');
    if (!append) body.innerHTML = '';
    if (!list.length) {
      if (!append) body.innerHTML = '<div class="bl-empty">还没有日志输出</div>';
      return;
    }
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    body.insertAdjacentHTML('beforeend', list.map(rowHtml).join(''));
    if (append ? (autoScroll && atBottom) : true) body.scrollTop = body.scrollHeight;
    // 行数上限与后端一致（2000），前端再兜一层防 DOM 无限增长
    while (body.childElementCount > 2000) body.removeChild(body.firstElementChild);
  }

  function refresh() {
    if (!panel || panel.style.display === 'none') return;
    const append = lastSeq > 0;
    fetch('/api/backend_log?since=' + lastSeq + '&limit=2000')
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok) return;
        render(j.lines || [], append);
        lastSeq = j.last_seq || 0;
        const meta = panel.querySelector('.bl-meta');
        meta.textContent = (j.capacity ? '缓冲 ' + j.capacity + ' 条' : '') +
          (j.installed === false ? ' · 缓冲未启用（子模式）' : '');
      })
      .catch(() => {});
  }

  function show() {
    ensurePanel();
    panel.style.display = 'flex';
    lastSeq = 0;
    autoScroll = true;
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
