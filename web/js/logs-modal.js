let logsDirPath = '';
async function loadLogDir() {
  // 加载当前日志目录到输入框
  try {
    const r = await fetch('/api/log_dir');
    const j = await r.json();
    if (j.ok) {
      $('logDirInput').value = j.dir || '';
      logsDirPath = j.dir || '';
    }
  } catch(e) {}
}
async function openLogDir() {
  try {
    const r = await fetch('/api/log_dir/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'});
    const j = await r.json();
    if (j.ok) showBanner('已在资源管理器打开日志目录');
    else showBanner('打开失败：' + (j.err || ''), 6000, true);
  } catch(e) { showBanner('打开失败：' + e, 6000, true); }
}
async function openLogFile(name) {
  try {
    const r = await fetch('/api/open_log_file', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
    const j = await r.json();
    if (j.ok) showBanner('已在资源管理器定位：' + name);
    else showBanner('打开失败：' + (j.err || ''), 6000, true);
  } catch(e) { showBanner('打开失败：' + e, 6000, true); }
}
async function loadLogsList() {
  const list = $('logsList');
  list.innerHTML = '加载中…';
  try {
    const sortSel = $('logsSort');
    const sort = sortSel ? sortSel.value : 'time_desc';
    const _myReq = ++window._logsLseq || (window._logsLseq = 1);   // a239 B3-P3: 响应乱序令牌——连续切排序时旧响应晚到不再覆盖新结果
    const r = await fetch('/api/logs?sort=' + encodeURIComponent(sort));
    const j = await r.json();
    if (_myReq !== window._logsLseq) return;
    logsDirPath = j.dir || '';
    list.innerHTML = '';
    if (!j.logs.length) { list.innerHTML = '<div style="padding:20px;color:var(--muted);">暂无日志</div>'; return; }
    j.logs.forEach(l => {
      const d = document.createElement('div');
      d.className = 'item';
      const dt = new Date(l.mtime*1000);
      d.innerHTML = `<span>${esc(l.name)}<br><span class="sz">${dt.toLocaleString('zh-CN')} · ${(l.size/1024).toFixed(1)} KB</span></span>
        <span class="item-actions">
          <span class="act-btn open" data-view="${esc(l.name)}" title="在工具内打开此日志">📜 打开</span>
          <span class="act-btn open" data-open="${esc(l.name)}" title="在资源管理器中定位此文件">📁 定位</span>
          <span class="act-btn" data-replay="${esc(l.name)}" title="回放此日志">▶ 回放</span>
        </span>`;
      d.querySelector('[data-replay]').onclick = (ev) => { ev.stopPropagation(); $('logsModal').classList.remove('show'); openReplay(l.name); };
      d.querySelector('[data-open]').onclick = (ev) => { ev.stopPropagation(); openLogFile(l.name); };
      d.querySelector('[data-view]').onclick = (ev) => { ev.stopPropagation(); $('logsModal').classList.remove('show'); buildLogViewer(l.name); };
      list.appendChild(d);
    });
  } catch(e) { list.innerHTML = '加载失败'; }
}
$('btnLogs').onclick = async () => {
  $('logsModal').classList.add('show');
  // 恢复上次排序选择（默认 time_desc 最新在前）
  try { const saved = localStorage.getItem('logsSort'); if (saved && $('logsSort')) $('logsSort').value = saved; } catch(e){}
  await loadLogDir();
  await loadLogsList();
};
// 切换排序方式立即生效并记住
if ($('logsSort')) $('logsSort').onchange = () => {
  try { localStorage.setItem('logsSort', $('logsSort').value); } catch(e){}
  loadLogsList();
};
$('logsClose').onclick = () => $('logsModal').classList.remove('show');
$('btnLogDirApply').onclick = async () => {
  const dir = $('logDirInput').value.trim();
  if (!dir) { showBanner('目录不能为空', 2000); return; }
  try {
    const r = await fetch('/api/log_dir', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({dir})
    });
    const j = await r.json();
    if (j.ok) {
      showBanner('日志目录已切换：' + j.dir, 3000);
      await loadLogsList();
    } else {
      showBanner('设置失败：' + (j.err || '未知错误'), 3000, true);
    }
  } catch(e) { showBanner('设置失败：' + e, 3000, true); }
};
$('btnLogDirReset').onclick = async () => {
  try {
    const r = await fetch('/api/log_dir', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({dir: ''})
    });
    const j = await r.json();
    if (j.ok) {
      $('logDirInput').value = j.dir;
      showBanner('已恢复默认日志目录', 2000);
      await loadLogsList();
    }
  } catch(e) {}
};
$('btnLogDirOpen').onclick = openLogDir;

// ============================================================
// 回放
// ============================================================
