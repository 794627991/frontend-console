let replayData = null, replayTimer = null, replayIdx = 0, replayStartTs = 0, replayBaseReal = 0;
async function openReplay(name) {
  const panel = $('replayPanel');
  $('replayTitle').textContent = '回放：' + name;
  const r = await fetch('/api/replay/' + encodeURIComponent(name));
  const j = await r.json();
  replayData = j.lines || [];
  replayIdx = 0;
  $('replayBody').innerHTML = '';
  if (!replayData.length) { $('replayInfo').textContent = '空'; panel.classList.add('show'); return; }
  const first = replayData[0].ts, last = replayData[replayData.length-1].ts;
  const dur = (last - first)/1000;
  $('replayTotal').textContent = fmtDur(dur);
  $('replayInfo').textContent = `${replayData.length} 行 · 时长 ${fmtDur(dur)}`;
  $('replaySeek').max = Math.max(1, Math.floor(dur));
  panel.classList.add('show');
  playReplay();
}
function fmtDur(s){ const m=Math.floor(s/60), ss=Math.floor(s%60); return String(m).padStart(2,'0')+':'+String(ss).padStart(2,'0'); }
function renderReplayLine(item) {
  const body = $('replayBody');
  const div = document.createElement('div');
  div.className = 'line tag-' + (item.tag||'text');
  const ts = document.createElement('span'); ts.className='ts'; ts.textContent = item.ts?fmtTs(item.ts):'';
  div.appendChild(ts);
  div.appendChild(document.createTextNode(item.text));
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}
function playReplay() {
  if (!replayData || replayTimer) return;
  const speed = parseFloat($('replaySpeed').value)||1;
  replayStartTs = replayData[replayIdx]?.ts || 0;
  replayBaseReal = Date.now();
  const tick = () => {
    if (replayIdx >= replayData.length) { stopReplay(); return; }
    const now = Date.now();
    const elapsed = (now - replayBaseReal) * speed;
    const cur = replayStartTs + elapsed;
    while (replayIdx < replayData.length && replayData[replayIdx].ts <= cur) {
      renderReplayLine(replayData[replayIdx]); replayIdx++;
    }
    $('replaySeek').value = Math.floor((cur - replayData[0].ts)/1000);
    $('replayTime').textContent = fmtDur((cur - replayData[0].ts)/1000);
    replayTimer = requestAnimationFrame(tick);
  };
  replayTimer = requestAnimationFrame(tick);
}
function stopReplay() { if (replayTimer) { cancelAnimationFrame(replayTimer); replayTimer = null; } }
$('btnReplayPlay').onclick = playReplay;
$('btnReplayPause').onclick = stopReplay;
$('btnReplayClose').onclick = () => { stopReplay(); $('replayPanel').classList.remove('show'); };
$('replaySpeed').onchange = () => { stopReplay(); playReplay(); };
$('replaySeek').oninput = function() {
  stopReplay();
  const v = parseInt(this.value);
  if (!replayData.length) return;
  const target = replayData[0].ts + v*1000;
  replayIdx = 0;
  $('replayBody').innerHTML = '';
  while (replayIdx < replayData.length && replayData[replayIdx].ts < target) {
    renderReplayLine(replayData[replayIdx]); replayIdx++;
  }
  $('replayTime').textContent = fmtDur(v);
};

// ============================================================
// 右侧工具面板（搜索 / 感知 / 分析 / 命令）
// ============================================================
$('aiToggle').onclick = () => {
  const p = $('aiPanel');
  p.classList.toggle('collapsed');
  $('aiToggle').textContent = p.classList.contains('collapsed') ? '‹' : '›';
};
// 折叠后点击图标重新展开
$('aiPanel').querySelector('.ai-icon').addEventListener('click', () => {
  const p = $('aiPanel');
  if (p.classList.contains('collapsed')) {
    p.classList.remove('collapsed');
    $('aiToggle').textContent = '›';
  }
});

// ---- 标签页切换 ----
document.querySelectorAll('.panel-tab').forEach(tab => {
  tab.onclick = () => {
    const pane = tab.dataset.pane;
    document.querySelectorAll('.panel-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.panel-tab-pane').forEach(p => p.classList.toggle('active', p.dataset.pane === pane));
    if (pane === 'analyze') renderAnalyze();
    if (pane === 'cmd') renderCmdPane();
  };
});

// ---- 搜索（v0.3.0：用 xterm SearchAddon + decoration 高亮） ----
