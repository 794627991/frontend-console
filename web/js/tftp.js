let _tftpRunning = false;
let _httpFilePort = 8081;    // HFS 端口（:8081 span 可点击内联修改）
let _tftpTransfersKey = '';  // 传输区脏检查 key（含进度，进行中每秒变）
let _tftpFilesKey = '';      // 文件区脏检查 key（只在文件集变化时变）
let _tftpActive = false;     // 有进行中传输（轮询频率切换，不查 DOM)
function _fmtSize(n) {
  if (n == null) return '';
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + 'GB';   // a242：GB 档（全局共享函数，打开方式弹窗同用）
  if (n >= 1048576) return (n / 1048576).toFixed(1) + 'MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + 'KB';
  return n + 'B';
}
let _tftpPollBusy = false;   // a267：在飞守卫——上个请求没回来不发下一个（防挂起请求堆满连接池）
async function refreshTftp() {
  if (_tftpPollBusy) return;   // devtools 追踪实锤：NFS 挂起时 2s 轮询堆了 49 个排队请求
  _tftpPollBusy = true;
  // a267：4s 超时自断——服务器/网络盘挂死时主动放弃，别占着连接池等
  const _ac = new AbortController();
  const _tm = setTimeout(() => _ac.abort(), 4000);
  try {
    const r = await fetch('/api/tftp/status', { signal: _ac.signal });
    const j = await r.json();
    if (!j.ok) return;
    _tftpRunning = j.running;
    const tg = $('tftpToggle');
    // 合并开关：TFTP 与 HFS 同启同停，状态以 TFTP 为准（后端保证一致）
    tg.classList.toggle('on', j.running);
    $('tftpToggleText').textContent = j.running ? '已运行' : '未运行';
    // HFS 端口显示（自定义端口后跟随）
    try {
      const hr = await fetch('/api/httpfile/status');
      const hj = await hr.json();
      if (hj.ok && !$('httpFilePort').dataset.editing) $('httpFilePort').textContent = ' : ' + hj.port;
    } catch(e) {}
    if (j.root_dir && !$('tftpDirPath').dataset.editing) $('tftpDirPath').textContent = j.root_dir;
    // 两个独立容器分别脏检查：传输区含进度（bytes 变化必须刷新进度条），
    // 文件区只在文件集变化时刷新。分区可折叠，折叠状态纳入脏检查 key。
    const transfersEl = $('tftpTransfers');
    const filesEl = $('tftpFiles');
    const secState0 = (n) => { try { return localStorage.getItem('tftpSec_' + n) !== '0'; } catch(e) { return true; } };
    // 传输区：最近传输在上（5 行滚动），进行中每秒刷新进度
    const transfers = j.transfers || [];
    // 记录有无进行中传输，供轮询频率切换（不查 DOM，避免冷启动漏掉前几秒进度）
    _tftpActive = transfers.some(t => t.status !== 'done' && t.status !== 'error');
    const tKey = JSON.stringify([secState0('transfers'),
      transfers.map(t => [t.status, t.bytes, t.total, t.filename, t.err, t.via])]);
    if (tKey !== _tftpTransfersKey) {
      _tftpTransfersKey = tKey;
      const tOpen = secState0('transfers');
      const secArrow = (open) => open ? '▾' : '▸';
      let thtml = `<div class="tftp-sec" data-sec="transfers" title="点击折叠/展开"><span>${secArrow(tOpen)} 最近传输</span><span>${transfers.length}</span></div>`;
      if (tOpen) {
        if (transfers.length) {
          thtml += transfers.map(t => {
            const active = t.status !== 'done' && t.status !== 'error';
            // get=设备下载(RRQ,有total)，put=设备上传(WRQ,total可能null)
            const icon = t.status === 'done' ? '✓' : t.status === 'error' ? '✗' : (t.kind === 'get' ? ICO.upload : ICO.download);
            const hasTotal = active && t.total;
            const pct = hasTotal ? Math.min(100, Math.round(t.bytes / t.total * 100)) : 0;
            const size = t.status === 'done'
              ? _fmtSize(t.bytes)
              : (hasTotal ? `${_fmtSize(t.bytes)}/${_fmtSize(t.total)} · ${pct}%` : _fmtSize(t.bytes));
            const tip = (t.kind === 'get' ? '设备下载' : '设备上传') + (t.via === 'hfs' ? ' · HFS' : ' · TFTP');
            // 来源标签：区分 TFTP/HFS 传输
            const viaTag = `<span class="tftp-via ${t.via === 'hfs' ? 'via-hfs' : 'via-tftp'}">${t.via === 'hfs' ? 'HFS' : 'TFTP'}</span>`;
            // 无 total（WRQ 未协商 tsize）时进度条用不确定条纹动画，至少表明在传输
            const barStyle = hasTotal ? `width:${pct}%` : '';
            const barClass = hasTotal ? '' : 'indeterminate';
            return `<div class="tftp-item ${active ? 'active' : t.status}" title="${tip} · ${t.peer}${t.err ? ' · ' + esc(t.err) : ''}">
              <span class="icon">${icon}</span>
              ${viaTag}
              <span class="name">${esc(t.filename)}</span>
              <span class="size">${size}</span>
              <div class="bar ${barClass}"><i style="${barStyle}"></i></div>
            </div>`;
          }).join('');
        } else {
          thtml += `<div class="tftp-empty"><div>暂无传输</div><div class="hint">设备端执行 tftp 命令即可上传/下载</div></div>`;
        }
      }
      transfersEl.innerHTML = thtml;
    }
    // 文件区：目录文件在下，占余下空间
    const files = j.files || [];
    const fKey = JSON.stringify([secState0('files'), files.map(f => [f.name, f.size])]);
    if (fKey !== _tftpFilesKey) {
      _tftpFilesKey = fKey;
      const fOpen = secState0('files');
      const secArrow = (open) => open ? '▾' : '▸';
      let fhtml = `<div class="tftp-sec" data-sec="files" title="点击折叠/展开"><span>${secArrow(fOpen)} 目录文件</span><span>${files.length}</span></div>`;
      if (fOpen) {
        if (files.length) {
          fhtml += files.map(f => `
            <div class="tftp-file" title="${esc(f.name)} · ${_fmtSize(f.size)}">
              <span class="icon">${ICO.file}</span>
              <span class="name">${esc(f.name)}</span>
              <span class="size">${_fmtSize(f.size)}</span>
            </div>`).join('');
        } else {
          fhtml += `<div class="tftp-empty"><div>目录为空或未选择</div></div>`;
        }
      }
      filesEl.innerHTML = fhtml;
    }
  } catch(e) {} finally {
    clearTimeout(_tm);
    _tftpPollBusy = false;
  }
}
// 分区标题点击折叠/展开（事件委托，绑定到两个容器；状态 localStorage 记忆）
[$('tftpTransfers'), $('tftpFiles')].forEach(el => {
  el.addEventListener('click', e => {
    const sec = e.target.closest('.tftp-sec');
    if (!sec || !sec.dataset.sec) return;
    const key = 'tftpSec_' + sec.dataset.sec;
    const open = (function(){ try { return localStorage.getItem(key) !== '0'; } catch(e){ return true; } })();
    try { localStorage.setItem(key, open ? '0' : '1'); } catch(e) {}
    refreshTftp();
  });
});
// TFTP 面板高度拖拽调节 + localStorage 记忆
(function initTftpResizer() {
  const resizer = $('tftpResizer');
  const pane = $('tftpPane');
  if (!resizer || !pane) return;
  // 恢复记忆高度（clamp 到合理范围防窗口变小后面板超界）
  try {
    const h = parseInt(localStorage.getItem('tftpPaneH') || '', 10);
    if (h >= 180 && h <= window.innerHeight - 200) pane.style.height = h + 'px';
  } catch(e) {}
  let dragging = false, startY = 0, startH = 0;
  resizer.addEventListener('mousedown', e => {
    dragging = true; startY = e.clientY; startH = pane.offsetHeight;
    resizer.classList.add('dragging');
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    // 向上拖增大：clientY 减小 → 高度增加
    const h = Math.max(180, Math.min(startH + (startY - e.clientY), window.innerHeight - 200));
    pane.style.height = h + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove('dragging');
    document.body.style.userSelect = '';
    try { localStorage.setItem('tftpPaneH', pane.offsetHeight); } catch(e) {}
  });
})();

// 合并开关：TFTP + HFS 同启同停（目录共享；HFS 端口默认 8081，点 :8081 内联修改）
$('tftpToggle').onclick = async () => {
  try {
    if (_tftpRunning) {
      // 停：两个服务都停
      await fetch('/api/httpfile/stop', {method:'POST'});
      await fetch('/api/tftp/stop', {method:'POST'});
      showBanner('TFTP/HFS 已停止');
    } else {
      // 起：先 TFTP（定目录），再 HFS（随目录 + 自定义端口）
      const r1 = await fetch('/api/tftp/start', {method:'POST'});
      const j1 = await r1.json();
      if (!j1.ok) { showBanner(j1.msg || j1.err || 'TFTP 启动失败', 4000, true); refreshTftp(); return; }
      const r2 = await fetch('/api/httpfile/start', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({port: _httpFilePort})});
      const j2 = await r2.json();
      showBanner(j2.ok ? `TFTP/HFS 已启动（HFS 端口 ${_httpFilePort}）` : (j2.msg || 'HFS 启动失败（TFTP 正常）'), j2.ok ? 3000 : 4000, !j2.ok);
    }
    refreshTftp();
  } catch(e) { showBanner('TFTP/HFS 操作失败', 4000, true); }
};
// 端口内联编辑（仿 _tftpInlineDirInput）：回车提交 / Esc 取消 / 失焦中止
$('httpFilePort').addEventListener('click', e => {
  e.stopPropagation();
  const span = $('httpFilePort');
  if (span.dataset.editing) return;
  const old = span.textContent.replace(/^:/, '') || '8081';
  span.dataset.editing = '1';
  const input = document.createElement('input');
  input.type = 'text'; input.value = old;
  input.style.cssText = 'width:52px;font-family:var(--font-mono);font-size:10px;background:var(--bg-input,#111);border:1px solid var(--accent);border-radius:5px;padding:2px 4px;color:var(--fg);outline:none';
  span.textContent = '';
  span.appendChild(input);
  input.focus(); input.select();
  let done = false;
  const finish = (apply) => {
    if (done) return; done = true;
    delete span.dataset.editing;
    const v = input.value.trim();
    if (apply && v && v !== old) {
      const n = parseInt(v, 10);
      if (n >= 1 && n <= 65535) {
        _httpFilePort = n;
        span.textContent = ' : ' + n;
        if (_tftpRunning) {  // 运行中改端口：只重启 HFS（TFTP 不受影响）
          fetch('/api/httpfile/stop', {method:'POST'}).then(() =>
            fetch('/api/httpfile/start', {method:'POST',
              headers:{'Content-Type':'application/json'}, body: JSON.stringify({port: n})})
          ).then(() => refreshTftp()).catch(() => {});
          showBanner('HFS 端口已切换为 ' + n);
        } else {
          showBanner('HFS 端口已设为 ' + n + '，启动后生效');
        }
        return;
      }
      showBanner('端口号无效（1-65535）', 4000, true);
    }
    span.textContent = ' : ' + old;
  };
  input.addEventListener('keydown', ev => {
    ev.stopPropagation();
    if (ev.key === 'Enter') finish(true);
    else if (ev.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
});
async function pickTftpDir() {
  // 原生目录对话框（pywebview js_api）。取消（空串）直接中止——不弹输入框
  try {
    if (window.pywebview && pywebview.api && pywebview.api.pick_dir) {
      let dir = await pywebview.api.pick_dir();
      // 防御：js bridge 序列化异常时可能拿到数组形态，归一化为字符串
      if (Array.isArray(dir)) dir = dir[0] || '';
      if (dir) return setTftpDir(dir);
      return;  // 用户取消对话框，什么都不做
    }
  } catch(e) {}
  // js bridge 不可用兜底：内联输入（WebView2 可能禁用 window.prompt，不能用）
  _tftpInlineDirInput();
}
function _tftpInlineDirInput() {
  // 内联路径输入：把路径 span 换成 input，回车提交 / Esc 取消 / 失焦中止
  const span = $('tftpDirPath');
  if (span.dataset.editing) return;
  const old = span.textContent === '选择目录…' ? '' : span.textContent;
  span.dataset.editing = '1';
  const input = document.createElement('input');
  input.type = 'text';
  input.value = old;
  input.style.cssText = 'width:100%;font-family:var(--font-mono);font-size:10px;background:var(--bg-input,#111);border:1px solid var(--accent);border-radius:5px;padding:4px 6px;color:var(--fg);outline:none';
  span.textContent = '';
  span.appendChild(input);
  input.focus(); input.select();
  let done = false;
  const finish = (apply) => {
    if (done) return; done = true;
    delete span.dataset.editing;
    const v = input.value.trim().replace(/^["']|["']$/g, '');  // 容忍手输时带引号
    span.textContent = apply && v ? v : (old || '选择目录…');
    if (apply && v) setTftpDir(v);
    else refreshTftp();  // 恢复原显示
  };
  input.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}
async function setTftpDir(dir) {
  try {
    const r = await fetch('/api/tftp/set_dir', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({root_dir: dir})});
    const j = await r.json();
    if (j.ok) { showBanner('TFTP 目录已切换: ' + dir); refreshTftp(); }
    else showBanner(j.err || '目录无效', 4000, true);
  } catch(e) { showBanner('设置目录失败', 4000, true); }
}
$('tftpPickDir').onclick = pickTftpDir;
$('tftpDirPath').onclick = pickTftpDir;
$('tftpTypeDir').onclick = _tftpInlineDirInput;  // 手动输入（支持 UNC/网络盘/任意路径）
refreshTftp();
// 传输进度刷新：空闲 2s 兜底，进行中 0.5s 抓进度。
// 关键：active 状态用 JS 变量从 status 响应记录，不查 DOM——传输刚启动时 DOM 还没
// 渲染出 active 项，查 DOM 会漏掉前 10s 进度（设备升完才显示结果的根因）。
// a265（用户实锤串口敲键 1s+）：空闲轮询加可见性门控——页面后台/面板收起
// 时停轮。TFTP 根在网络盘（Y:\nfs）时每次 status 都是 30+ 次网络 stat，
// 慢轮询会占满浏览器同源 6 连接池，把串口按键 POST 挤成秒级排队。
// 进行中（_tftpActive）不受门控：进度必须跟。
setInterval(() => {
  if (_tftpActive) return;
  if (document.hidden) return;
  const pane = $('tftpPane');
  if (pane && pane.offsetHeight === 0) return;   // 面板收起
  refreshTftp();
}, 2000);       // 空闲兜底
setInterval(() => { if (_tftpActive) refreshTftp(); }, 500);          // 进行中抓进度

// 初始化
// ============================================================
