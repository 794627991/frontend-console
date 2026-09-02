// 回放核心：不再把全量行拉到前端（G 级日志会几百 MB 内存 + 每次拖拽全量重建
// DOM 百万节点，直接卡死）。改为：打开只拉元信息；播放按需分页拉行；拖拽
// 用 /api/replay_seek 二分定位行号；replayBody DOM 节点数设上限，超出裁掉
// 头部旧行——回放只看"最新输出"，裁头不影响体验却保住内存。
let replayData = null, replayTimer = null, replayIdx = 0, replayStartTs = 0, replayBaseReal = 0;
let replayName = null, replayMeta = null, replayLoading = false, replayEOF = false;
const REPLAY_DOM_MAX = 2000;      // replayBody 最大保留节点数
const REPLAY_PAGE = 2000;         // 单次分页拉取行数
async function openReplay(name) {
  const panel = $('replayPanel');
  $('replayTitle').textContent = '回放：' + name;
  stopReplay();
  replayName = name; replayMeta = null; replayIdx = 0; replayEOF = false;
  replayStartTs = 0; replayBaseReal = 0;
  $('replayBody').innerHTML = '';
  $('replayInfo').textContent = '加载中…';
  panel.classList.add('show');
  const r = await fetch('/api/replay/' + encodeURIComponent(name));
  const j = await r.json();
  if (!j.ok) { $('replayInfo').textContent = j.err || '加载失败'; return; }
  replayMeta = j;
  replayData = { first_ts: j.first_ts, last_ts: j.last_ts, total: j.total };
  replayStartTs = j.first_ts || 0;   // 元信息到手即定播放起点
  replayBaseReal = Date.now();
  const dur = j.dur || 0;
  $('replayTotal').textContent = fmtDur(dur);
  $('replayInfo').textContent = `${j.total} 行 · 时长 ${fmtDur(dur)}`;
  $('replaySeek').max = Math.max(1, Math.floor(dur));
  if (!j.total) { $('replayInfo').textContent = '空'; return; }
  playReplay();
}
function fmtDur(s){ const m=Math.floor(s/60), ss=Math.floor(s%60); return String(m).padStart(2,'0')+':'+String(ss).padStart(2,'0'); }
function _trimReplayDom() {
  const body = $('replayBody');
  while (body.childNodes.length > REPLAY_DOM_MAX) body.removeChild(body.firstChild);
}
function renderReplayLine(item) {
  const body = $('replayBody');
  const div = document.createElement('div');
  div.className = 'line tag-' + (item.tag||'text');
  const ts = document.createElement('span'); ts.className='ts'; ts.textContent = item.ts?fmtTs(item.ts):'';
  div.appendChild(ts);
  div.appendChild(document.createTextNode(item.text||''));
  body.appendChild(div);
  _trimReplayDom();
  body.scrollTop = body.scrollHeight;
}
// 分页拉取 replayIdx 起的行，渲染所有 ts <= 播放头的行并推进 replayIdx。
// 未到播放头的行不渲染也不推进（下次再拉同一页）——否则行会整页跳失。
async function _fetchReplayLines() {
  if (replayLoading || !replayName) return;
  replayLoading = true;
  try {
    const r = await fetch(`/api/replay_page?name=${encodeURIComponent(replayName)}&offset=${replayIdx}&limit=${REPLAY_PAGE}`);
    const j = await r.json();
    if (!j.ok) return;
    const total = j.total || 0;
    const lines = (j.lines || []).filter(l => (l.ts||0) > 0);  // 过滤脏行（ts=0）
    if (replayIdx + (j.lines||[]).length >= total) replayEOF = true;  // 本页已到文件尾
    const cur = replayCurTs();
    let shown = 0;
    for (const l of lines) {
      if (l.ts > cur) break;   // 未到播放头：停本页，保留 replayIdx 供下次重拉
      renderReplayLine(l);
      shown++;
    }
    replayIdx += shown;
  } catch(e) {} finally { replayLoading = false; }
}
function replayCurTs() {
  if (!replayData) return -1;
  const speed = parseFloat($('replaySpeed').value)||1;
  return replayStartTs + (Date.now() - replayBaseReal) * speed;
}
function playReplay() {
  if (!replayData || replayTimer) return;
  const tick = () => {
    const cur = replayCurTs();
    if (cur >= replayData.last_ts && replayEOF) { stopReplay(); return; }
    $('replaySeek').value = Math.floor((cur - replayData.first_ts)/1000);
    $('replayTime').textContent = fmtDur((cur - replayData.first_ts)/1000);
    _fetchReplayLines();  // 内部防重入（replayLoading），未到播放头的行留待下帧
    replayTimer = requestAnimationFrame(tick);
  };
  replayTimer = requestAnimationFrame(tick);
}
function stopReplay() { if (replayTimer) { cancelAnimationFrame(replayTimer); replayTimer = null; } }
$('btnReplayPlay').onclick = () => { replayBaseReal = Date.now(); playReplay(); };
$('btnReplayPause').onclick = stopReplay;
$('btnReplayClose').onclick = () => { stopReplay(); $('replayPanel').classList.remove('show'); };
$('replaySpeed').onchange = () => {
  // 以当前播放头为新起点续播（未开播时不动 replayStartTs）
  if (replayTimer || replayBaseReal) replayStartTs = replayCurTs();
  replayBaseReal = Date.now();
  stopReplay(); playReplay();
};
// 拖拽进度条：input 只更新时间标签（廉价），change（松手）才真正 seek——
// 旧版 oninput 每帧全量重建 DOM，G 级日志拖几下就卡死。
$('replaySeek').oninput = function() {
  $('replayTime').textContent = fmtDur(parseInt(this.value));
};
$('replaySeek').onchange = async function() {
  if (!replayName || !replayData) return;
  stopReplay();
  const v = parseInt(this.value);
  const target = (replayData.first_ts||0) + v*1000;
  $('replayBody').innerHTML = '';
  replayIdx = 0; replayEOF = false;
  // 二分定位目标行号，前端零扫描
  try {
    const r = await fetch(`/api/replay_seek?name=${encodeURIComponent(replayName)}&ts=${target}`);
    const j = await r.json();
    if (j.ok) replayIdx = j.row;
  } catch(e) {}
  replayStartTs = target;
  replayBaseReal = Date.now();
  $('replayTime').textContent = fmtDur(v);
  playReplay();
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
