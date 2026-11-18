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
  // 恢复记忆高度。a451（用户实锤：拖好高度下次启动又回去了）：原实现
  // `if (h >= 180 && h <= innerHeight - 200)` 越界就**整个丢弃**，回落到
  // CSS 的 50%——用户在最大化窗口里拖到 900px，下次以小窗口启动就判越界、
  // 记忆等于没存。改为 clamp 到合法区间：越界说明窗口尺寸变了，不是记忆
  // 失效；存的值本身保留，窗口再变大仍能恢复原高度。
  let _savedH = 0;
  let dragging = false, startY = 0, startH = 0;   // a563：声明上移（_applySaved 让位判断需要，避免 TDZ）
  let _collapsed = false;      // a564：折叠态（只剩标题栏，VSCode 面板语义）
  let _dragCollapse = false;   // 拖拽过程中「本次将折叠」预判
  let _dragMoved = false;      // a565 审计 BUG-2a：纯点击（无位移）≠拖拽
  const COLLAPSE_TH = 90;      // 拖到 90px 以下 → 松手折叠
  try { _savedH = parseInt(localStorage.getItem('tftpPaneH') || '', 10) || 0; } catch(e) {}
  try { _collapsed = localStorage.getItem('tftpPaneCollapsed') === '1'; } catch(e) {}

  // a564：折叠/展开。折叠=只剩标题栏（高度 auto，dir/list 藏）；展开=
  // 上次展开高度（无记忆则父容器 35% 兜底）。save=落盘（本地+服务端）
  function _setCollapsed(on, save) {
    _collapsed = !!on;
    if (_collapsed) {
      pane.classList.add('collapsed');
      pane.style.height = '';            // 高度交还 CSS（auto=标题栏）
    } else {
      pane.classList.remove('collapsed');
      _applySaved();
    }
    if (save !== false) {
      try { localStorage.setItem('tftpPaneCollapsed', _collapsed ? '1' : '0'); } catch (e) {}
      _uploadSaved(true);   // a565 审计 BUG-1：折叠态变更强制落盘
    }
  }
  // a564：默认展开高度——有记忆用记忆，否则父容器 35%（VSCode 面板默认观感）
  function _defaultExpandH() {
    if (_savedH >= 60) return _savedH;
    const b = _paneBounds();
    if (!b) return 300;
    return Math.max(b[0], Math.min(Math.round((pane.parentElement.clientHeight) * 0.35), b[1]));
  }
  // a564：标题栏点击=切换折叠（启动/停止按钮与端口编辑等交互区除外）
  const _head = pane.querySelector('.tftp-head');
  if (_head) {
    _head.style.cursor = 'pointer';
    _head.title = '点击折叠 / 展开（拖到最小也可折叠）';
    const _ind = document.createElement('span');
    _ind.className = 'tftp-collapse-ind';
    _head.prepend(_ind);
    _head.addEventListener('click', e => {
      if (e.target.closest && e.target.closest('#tftpToggle, #httpFilePort'))
        return;
      _setCollapsed(!_collapsed);
    });
  }
  // a452（审计 P2）：上下限不能都用视口算——窗口 <380 时
  // `max(180, innerHeight-200)` 退化成 180，min/max 互相抵消，面板固定
  // 180px；而 .tftp-pane 是 flex-shrink:0 + 父容器 overflow:hidden，容器
  // 不足时底部文件列表被整块裁掉且用户无法再缩小。下限改成跟**父容器
  // 实际可用高度**比较，并保证下限不高于可用高度。
  function _paneBounds() {
    const parent = pane.parentElement;
    const avail = parent ? parent.clientHeight : window.innerHeight;
    // a563（用户实锤：修了多次仍未真正修复）：父容器不可测（隐藏/尚未
    // 布局，clientHeight<=0）时返回 null——原先会一路算出 [0,0] 把恢复
    // clamp 成 0px 钉死面板，且窗口不再 resize 就无人再救。恢复/重套用
    // 见到 null 一律跳过，等可测时再套
    if (avail <= 0) return null;
    // a452（第二轮审计 P2）：hi 可小于 60（窗口高<260 或父容器高<120），
    // 原来 lo 仍被 Math.max(60, ...) 强抬到 60 → 返回值 [60,60] 下限反超
    // 上限，clamp 退化成常量、把高度钉死 60px（还超出可用高度，父容器
    // overflow:hidden 继续裁）——正是 a452 想修的场景在极极端尺寸下的残存。
    // 上限低于 60 时下限跟着降，保证 lo <= hi 恒成立。
    const hi = Math.max(0, Math.min(window.innerHeight - 200, avail - 60));
    const lo = Math.max(0, Math.min(60, hi));
    return [lo, hi];
  }
  function _clampPaneH(h) {
    const b = _paneBounds();
    return b ? Math.max(b[0], Math.min(h, b[1])) : null;
  }
  // a563：恢复=「意图高度的重套用」，可安全重复调用。原先只在 IIFE 时
  // 执行一次——启动瞬间父容器/窗口未就绪（pywebview 先显窗后最大化、
  // 侧栏首帧前 clientHeight=0 等）这一次就废了，之后再无人补。
  // 四重兜底（rAF×2 / load / 300ms / 1200ms）+ ResizeObserver 盯父容器
  // （侧栏开合、布局沉淀、窗口最大化全覆盖），任何时序下终会套上。
  let _appliedLog = false;
  function _readSaved() {
    // a563（根因自愈）：每次重套用前重读 localStorage——历版都在 IIFE
    // 只读一次，首读撞上启动竞态（存储暂空/读取异常被 catch 成 0）则
    // 该页终身 _savedH=0，所有兜底在 <60 早退永不再读，面板恒回 CSS 50%
    try { _savedH = parseInt(localStorage.getItem('tftpPaneH') || '', 10) || 0; }
    catch (e) {}
  }
  // a563（真正根治）：主应用每次启动端口随机 → localStorage 按 origin
  //（含端口）隔离 → 跨启动必空——这才是「拖好的高度重启就丢、修了多次
  // 未真正修复」的根源。服务端 config.json 通道（与 sidebar_w/calc_history
  // 同款）：启动种子（服务端 → 本地），拖拽保存（本地 + 去抖上传）
  (function () {
    fetch('/api/theme').then(r => r.json()).then(j => {
      const srvH = parseInt(j && j.tftp_pane_h, 10) || 0;
      let curLocal = 0;
      try { curLocal = parseInt(localStorage.getItem('tftpPaneH') || '', 10) || 0; }
      catch (e) {}
      if (curLocal >= 60) {
        // 本地已有（同 origin 重开/本启动已拖过）：本地为准；与服务端不一致
        // 则回传对齐（迟到种子绝不覆盖用户刚拖的新高度）
        if (srvH !== curLocal) { _savedH = curLocal; _uploadSaved(); }
      } else if (srvH >= 60) {
        // 新 origin（端口变了）localStorage 必空 → 服务端种子
        _savedH = srvH;
        try { localStorage.setItem('tftpPaneH', String(srvH)); } catch (e) {}
        _applySaved();
      }
      // a564/a565 审计 BUG-3：折叠态对齐——本地键已有（含本启动用户刚
      // 操作过）则本地为准、差异回传（与高度同款防护）；原先无条件以服务
      // 端为准，迟到种子会把用户刚做的折叠当场弹回并连抹三层
      const srvC = !!(j && j.tftp_pane_collapsed);
      let curC = null;
      try { curC = localStorage.getItem('tftpPaneCollapsed'); } catch (e) {}
      if (curC === null) {
        // 新 origin（本地无键）→ 服务端种子
        try { localStorage.setItem('tftpPaneCollapsed', srvC ? '1' : '0'); } catch (e) {}
        if (srvC !== _collapsed) _setCollapsed(srvC, false);
      } else if ((curC === '1') !== srvC) {
        _uploadSaved(true);   // 本地为准，回传对齐
      }
    }).catch(() => {});
  })();
  function _uploadSaved(force) {
    // a565 审计 BUG-1：force=折叠态变更——必须落盘（原早退条件把「纯
    // collapsed=false」的 POST 也挡掉，从不拖高度的用户展开后面板跨启动
    // 自己又折叠了）；非 force 的纯高度路径维持原守卫。
    if (!force && _savedH < 60 && !_collapsed) return;
    // a565 审计：owner 门（与 web_favs 上传口径一致——第二 UI 不写 config）
    if (window.__webUiIsOwner && !window.__webUiIsOwner()) return;
    clearTimeout(_uploadSaved._t);
    _uploadSaved._t = setTimeout(() => {
      try {
        const body = { tftp_pane_collapsed: _collapsed };
        if (_savedH >= 60) body.tftp_pane_h = _savedH;
        fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body) }).catch(() => {});
      } catch (e) {}
    }, 500);
  }
  function _applySaved() {
    if (dragging) return;             // a563：拖拽进行中不干预（sweep/RO 让位）
    if (_collapsed) return;           // a564：折叠态高度交还 CSS，不套用
    _readSaved();
    // a564：无记忆时不再裸退（留 50%）——展开默认=父容器 35%（VSCode
    // 面板观感），仅套用不写入记忆
    const target = _savedH >= 60 ? _savedH : _defaultExpandH();
    const h = _clampPaneH(target);
    if (h == null) return;            // 父容器不可测：等下一轮兜底
    if (pane.style.height === h + 'px') return;   // 已套用幂等
    pane.style.height = h + 'px';
    if (!_appliedLog) {
      _appliedLog = true;
      try { console.debug('[tftp-pane] 恢复高度', target, '->', h); } catch (e) {}
    }
  }
  // a563 诊断探针（复发时控制台一键定位断在哪环）
  window.__tftpH = function () {
    return { saved: _savedH, style: pane.style.height, h: pane.offsetHeight,
             collapsed: _collapsed, bounds: _paneBounds(), innerH: window.innerHeight };
  };
  _setCollapsed(_collapsed, false);   // a564：启动即套折叠态（如有）
  _applySaved();
  requestAnimationFrame(() => requestAnimationFrame(_applySaved));
  window.addEventListener('load', _applySaved);
  setTimeout(_applySaved, 300);
  setTimeout(_applySaved, 1200);
  // a563：慢扫尾——前 15s 每秒一次（覆盖所有晚就绪：存储/布局/最大化/
  // 侧栏沉淀），幂等无副作用。之后完全交 ResizeObserver 常驻
  let _sweepN = 0;
  const _sweep = setInterval(() => {
    _applySaved();
    if (++_sweepN >= 15) clearInterval(_sweep);
  }, 1000);
  // a563：ResizeObserver 替代（并保留）window resize——父容器高度变化
  // 的所有路径（侧栏拖宽/开合、启动布局沉淀、窗口最大化）都触发重套用。
  // rAF + setTimeout 双发：窗口被遮挡时 rAF 挂起，定时器兜底照跑
  let _rszPending = false;
  const _coalesced = () => {
    if (_rszPending) return;
    _rszPending = true;
    const _run = () => { _rszPending = false; _applySaved(); };
    requestAnimationFrame(_run);
    setTimeout(_run, 120);
  };
  window.addEventListener('resize', _coalesced);
  try {
    new ResizeObserver(_coalesced).observe(pane.parentElement || pane);
  } catch (e) {}
  resizer.addEventListener('mousedown', e => {
    dragging = true; startY = e.clientY; startH = pane.offsetHeight;
    resizer.classList.add('dragging');
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    _dragMoved = true;                 // a565 审计：有位移才算拖拽
    // 向上拖增大：clientY 减小 → 高度增加。a452：上下限与恢复同一口径
    // （原硬编码 180 / innerHeight-200，小窗口下与恢复逻辑打架）。
    // a563：_paneBounds 可测性守卫（父容器隐藏时 null，跳过该帧）
    const b = _paneBounds();
    if (!b) return;
    const raw = startH + (startY - e.clientY);
    // a564（VSCode 语义）：拖到阈值以下 → 预览贴标题栏，松手折叠
    if (raw < COLLAPSE_TH) {
      _dragCollapse = true;
      const headEl = pane.querySelector('.tftp-head');
      pane.style.height = (headEl ? headEl.offsetHeight : 34) + 'px';
      return;
    }
    _dragCollapse = false;
    const h = Math.max(b[0], Math.min(raw, b[1]));
    pane.style.height = h + 'px';
  });
  // a565 审计 RISK-4：mouseup 丢失（系统弹窗/切窗）不再粘手+残留折叠判定
  const _dragReset = () => {
    dragging = false;
    _dragCollapse = false;
    _dragMoved = false;
    resizer.classList.remove('dragging');
    document.body.style.userSelect = '';
  };
  window.addEventListener('blur', _dragReset);
  document.documentElement.addEventListener('mouseleave', _dragReset);
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove('dragging');
    document.body.style.userSelect = '';
    // a565 审计 BUG-2a：纯点击（按下-抬起无位移）≠拖拽——折叠态轻点
    // 分隔条按「点击展开」处理（走 _setCollapsed 的记忆/默认高度），
    // 绝不读 CSS 50% 的瞬时 offsetHeight 污染高度记忆；展开态轻点=无操作
    if (!_dragMoved) {
      _dragCollapse = false;
      if (_collapsed) _setCollapsed(false);
      return;
    }
    _dragMoved = false;
    // a564：本次拖拽判定折叠 → 折叠（保留 _savedH=上次展开高度，VSCode 同款）
    if (_dragCollapse) {
      _dragCollapse = false;
      _setCollapsed(true);
      return;
    }
    // a564：从折叠态拖开 → 摘折叠类（不走红 _setCollapsed 的 _applySaved，
    // 保住本次拖出来的高度），再按常规保存。
    // a565 审计 BUG-2b：摘类必须同步本地折叠键（原先残留 '1' → 同端口
    // 重启闪跳/三态错乱）
    if (_collapsed) {
      _collapsed = false;
      pane.classList.remove('collapsed');
      try { localStorage.setItem('tftpPaneCollapsed', '0'); } catch (e) {}
    }
    try {
      // a563：保存侧加值域守卫——父容器异常压缩态下 offsetHeight 可能
      // 落到离谱小值，别把坏值写进记忆（<60 一律不存，保留旧值）
      const h = pane.offsetHeight;
      if (h >= 60) {
        localStorage.setItem('tftpPaneH', h);
        _savedH = h;   // a451：同步内存值，resize 才有正确意图高度
        _uploadSaved();   // a563：服务端持久化（跨启动端口变化不丢）
        try { console.debug('[tftp-pane] 记忆高度', h); } catch (e) {}
      }
    } catch(e) {}
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
// a268（用户实锤「TFTP/HFS 关了轮询还在跑」）：停机不再 2s 轮询——启停/
// 切目录都有显式 refreshTftp，高频轮询只在运行中有意义。停机留 10s 慢速
// 哨兵（捕获 MCP/外部启停），三档频率：传输中 0.5s > 运行中 2s > 停机 10s。
setInterval(() => {
  if (!_tftpRunning || _tftpActive) return;      // 仅运行中且无传输
  if (document.hidden) return;
  const pane = $('tftpPane');
  if (pane && (pane.offsetHeight === 0 || pane.classList.contains('collapsed'))) return;   // 面板收起/折叠（a564）
  refreshTftp();
}, 2000);       // 运行中空闲
setInterval(() => {
  if (_tftpRunning || _tftpActive) return;       // 仅停机态
  if (document.hidden) return;
  refreshTftp();
}, 10000);      // 停机哨兵：外部/MCP 启停兜底
setInterval(() => { if (_tftpActive) refreshTftp(); }, 500);          // 进行中抓进度

// 初始化
// ============================================================

// 模块化一期：转 ES module——跨文件/Python 裸引用消费名挂 window。
// 清单由 eslint no-undef 神谕反推（零启发式）：本文件转模块后，其余
// 文件/Python 推送的裸标识符引用全部经 window 解析。
window._fmtSize = _fmtSize;
