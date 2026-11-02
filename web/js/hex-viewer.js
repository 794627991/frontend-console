// ============================================================
// 十六进制查看/编辑器（类 HxD 布局，参考 1.png）
// 偏移(蓝) | hex 字节(nibble 双色：高4位蓝/低4位紫) | ASCII(不可打印为点)
// 每行 16 字节；字节点击选中，键盘输入 hex 直接改值；Ctrl+F 搜索(hex/文本)；
// 跳转偏移（0x 前缀支持）。
// 大文件分块加载：≤16MB 整读可编辑；>16MB 只读分块（512KB/块，滚动按需拉取）。
// Intel HEX(.hex/.ihx)：intelHexParse 解析成二进制镜像进同一界面，保存回 hex 文本。
// tab 体系与编辑器同构：connections + switchTab + closeEditorTab。
// ============================================================

const HEX_CHUNK = 512 * 1024;      // 分块大小（与后端 /api/hex/read 上限一致）
const HEX_EDIT_MAX = 16 * 1024 * 1024;  // 可编辑上限，超过只读

async function buildHexViewerTab(path, name) {
  // 同文件去重：已开则激活
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'hex' && c.hexPath === path) { switchTab(pid); return; }
  }
  // 任务型通知：hex 打开要 meta 探测 + 首屏分块读取，大文件有等待
  const nid = notifyTask({type:'hex', title:'正在打开 hex', detail:name});
  // meta 探测
  let size = 0, isIhex = false;
  try {
    const r = await fetch('/api/hex/meta', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    const j = await r.json();
    if (!j.ok) { notifyTaskDone(nid, {ok:false, title:'hex 打开失败', detail:j.err || '文件不可读', ms:5000}); return; }
    size = j.size; isIhex = j.ihex;
  } catch(e) { notifyTaskDone(nid, {ok:false, title:'hex 打开失败', detail:'读取文件信息失败: ' + e, ms:5000}); return; }

  const portId = 'hex:' + path + ':' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${fileIconHtml(name, 14)}</span><span class="label">${esc(name)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-hx-action="save" title="Ctrl+S">💾 保存</button>
        <button class="lv-btn" data-hx-action="goto" title="跳转偏移（支持 0x 前缀）">⤓ 跳转</button>
        <button class="lv-btn" data-hx-action="find" title="Ctrl+F 搜索（hex 字节或文本）">🔍 搜索</button>
        <select name="hx_view" class="hx-view-sel" data-hx-view title="查看方式：进制 × 位宽分组（HxD 同款）">
          <option value="8" selected>十六进制(8 位)</option>
          <option value="16">十六进制(16 位)</option>
          <option value="32">十六进制(32 位)</option>
          <option value="64">十六进制(64 位)</option>
          <option value="u8">无符号十进制(8 位)</option>
          <option value="u16">无符号十进制(16 位)</option>
          <option value="u32">无符号十进制(32 位)</option>
          <option value="u64">无符号十进制(64 位)</option>
        </select>
        <label class="hx-zero-toggle" title="0x00 字节灰色弱化显示（ImHex 同款），可配置">
          <input type="checkbox" data-hx-zero name="hg_hx_zero"> 00 灰显
        </label>
        <span class="lv-info" data-hx-info></span>
      </div>
      <div class="hx-body">
        <div class="hx-goto-bar" style="display:none">
          <span>偏移(h):</span><input type="text" data-hx-goto-input name="hx_goto" placeholder="如 0x100 或 256">
          <button class="lv-btn" data-hx-action="gotoOk">跳转</button>
          <button class="lv-btn" data-hx-action="gotoCancel">✕</button>
        </div>
        <div class="hx-find-bar" style="display:none">
          <span>查找:</span><input type="text" data-hx-find-input name="hx_find" placeholder="hex（如 55 AA）或文本">
          <button class="lv-btn" data-hx-action="findNext">下一个</button>
          <button class="lv-btn" data-hx-action="findAll">全部</button>
          <button class="lv-btn" data-hx-action="findCancel">✕</button>
          <span class="hx-find-count" data-hx-find-count></span>
        </div>
        <div class="hx-main">
          <div class="hx-scroll" data-hx-scroll tabindex="0">
            <div class="hx-head-row"><span class="hx-off"></span><span class="hx-hexcol" data-hx-head></span><span class="hx-ascii"></span></div>
            <div class="hx-scroll-inner">
              <div class="hx-canvas" data-hx-canvas></div>
            </div>
          </div>
          <div class="hx-inspector">
            <div class="hx-insp-title">数据检视</div>
            <div class="hx-insp-grid" data-hx-insp></div>
            <div class="hx-insp-be"><label><input type="radio" name="hx-be" value="le" checked> 小端序</label><label><input type="radio" name="hx-be" value="be"> 大端序</label></div>
          </div>
        </div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);   // 拖拽排序（tab-drag.js）
  termArea.appendChild(wrap);

  const conn = {
    portId,
    meta: { kind: 'hex', label: name },
    tab, wrap,
    hexPath: path, size, isIhex,
    editable: size <= HEX_EDIT_MAX && !isIhex || isIhex,  // ihex 解析后镜像通常远小于文本
    dirty: false,
    scroll: wrap.querySelector('[data-hx-scroll]'),
    canvas: wrap.querySelector('[data-hx-canvas]'),
    infoEl: wrap.querySelector('[data-hx-info]'),
    gotoBar: wrap.querySelector('.hx-goto-bar'),
    gotoInput: wrap.querySelector('[data-hx-goto-input]'),
    findBar: wrap.querySelector('.hx-find-bar'),
    findInput: wrap.querySelector('[data-hx-find-input]'),
    findCount: wrap.querySelector('[data-hx-find-count]'),
    inspEl: wrap.querySelector('[data-hx-insp]'),
    bigEndian: false,
    // HxD「查看方式」：hexN=十六进制 N 位分组，uN=无符号十进制 N 位分组
    viewMode: '8', viewBytes: 1, viewDec: false,
    // 0x00 灰色弱化开关（可配置，localStorage 持久化）
    zeroGray: (localStorage.getItem('hx_zeroGray') ?? '1') === '1',
    bytes: null, chunkCache: null, chunkBuf: null, chunkStart: -1,
    cursor: -1, findHits: [], findIdx: -1, _findQ: null,
    rowHeight: 22, renderedFrom: -1, renderedTo: -1,
  };
  connections[portId] = conn;

  // ---- 数据加载 ----
  // a237 P2：分块循环全部走可中止 fetch（_edCloseNow abort）——关 tab 后
  // 只读大文件的整读/搜索不再空转 2000+ 串行请求拉完整个文件
  conn._hxAbort = new AbortController();
  const fetchChunk = async (offset, length) => {
    const r = await fetch('/api/hex/read', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path, offset, length}), signal: conn._hxAbort.signal});
    const j = await r.json();
    if (!j.ok) throw new Error(j.err || 'read fail');
    return Uint8Array.from(atob(j.data), c => c.charCodeAt(0));
  };
  conn.fetchChunk = fetchChunk;

  try {
    if (conn.editable) {
      // 后端 /api/hex/read 单次硬钳 512KB（HEX_CHUNK），必须分块循环读满 size
      // ——单次整读时 conn.bytes 只有前 512KB 而 size 仍完整：滚动渲染越界
      // BigInt(undefined) 崩溃，Ctrl+S 把大文件截断成 512KB（数据丢失）
      let raw = new Uint8Array(size);
      for (let off = 0; off < size; off += HEX_CHUNK) {
        const b = await fetchChunk(off, Math.min(HEX_CHUNK, size - off));
        raw.set(b, off);
      }
      if (isIhex) {
        if (typeof intelHexParse !== 'function') throw new Error('Intel HEX 解析器未加载');
        const parsed = intelHexParse(new TextDecoder().decode(raw));
        raw = parsed.data;   // 0xFF 填充空洞的连续镜像
        conn.size = raw.length;
      }
      conn.bytes = raw;
    } else {
      conn.chunkCache = new Map();   // 只读窗口模式：当前渲染窗口的字节
    }
  } catch(e) {
    notifyTaskDone(nid, {ok:false, title:'hex 打开失败', detail:(e.message || e), ms:6000});
    _edCloseNow(conn);
    return;
  }

  // ---- 只读大文件：滚动窗口取块（渲染前确保窗口字节在手） ----
  conn.ensureWindow = async (fromOff, toOff) => {
    if (conn.bytes) return;
    const ci = Math.floor(fromOff / HEX_CHUNK);
    if (conn.chunkStart !== ci * HEX_CHUNK) {
      const b = await fetchChunk(ci * HEX_CHUNK, HEX_CHUNK);
      // 跨块窗口：拼两块
      if (toOff >= (ci + 1) * HEX_CHUNK && (ci + 1) * HEX_CHUNK < conn.size) {
        const b2 = await fetchChunk((ci + 1) * HEX_CHUNK, HEX_CHUNK);
        const merged = new Uint8Array(b.length + b2.length);
        merged.set(b); merged.set(b2, b.length);
        conn.chunkBuf = merged;
      } else conn.chunkBuf = b;
      conn.chunkStart = ci * HEX_CHUNK;
    }
  };
  conn.byteAt = (i) => {
    if (conn.bytes) return conn.bytes[i] ?? 0;   // 越界兜底 0，防 BigInt(undefined) 渲染崩溃
    if (conn.chunkBuf && i >= conn.chunkStart && i < conn.chunkStart + conn.chunkBuf.length)
      return conn.chunkBuf[i - conn.chunkStart];
    return 0;   // 窗口外（ensureWindow 已保证不出现）
  };

  // ---- 渲染 ----
  const ROW_BYTES = 16;
  conn.render = () => {
    const rows = Math.ceil(conn.size / ROW_BYTES);
    conn.canvas.style.height = (rows * conn.rowHeight) + 'px';
    const first = Math.floor(conn.scroll.scrollTop / conn.rowHeight);
    const count = Math.ceil(conn.scroll.clientHeight / conn.rowHeight) + 8;
    const from = Math.max(0, first - 4), to = Math.min(rows, first + count);
    _hxRenderRows(conn, from, to);
  };
  conn.scroll.addEventListener('scroll', () => {
    // 只读大文件：先确保窗口字节再画（异步），小文件直接画
    if (conn.bytes) conn.render();
    else conn.ensureWindow(fromOff(conn), toOff(conn)).then(() => conn.render()).catch(() => {});
    function fromOff(c) { return Math.max(0, Math.floor(c.scroll.scrollTop / c.rowHeight) * 16 - 64); }
    function toOff(c) { const r = Math.ceil((c.scroll.scrollTop + c.scroll.clientHeight) / c.rowHeight); return Math.min(c.size, r * 16 + 64); }
  });

  // ---- 选中/编辑 ----
  // 选区（ImHex/HxD 同款）：单击=单字节光标；Shift+点击/拖选=多字节范围——
  // 数据检视按选区解释（如选中 4 字节看 Uint32），而非固定从光标取
  conn.selStart = -1; conn.selEnd = -1;   // 闭区间；-1 无选区
  conn.canvas.addEventListener('mousedown', e => {
    const cell = e.target.closest('[data-hx-i]');
    if (!cell) return;
    const i = +cell.dataset.hxI;
    if (e.shiftKey && conn.cursor >= 0) {
      conn.selStart = Math.min(conn.cursor, i);
      conn.selEnd = Math.max(conn.cursor, i);
    } else {
      conn.cursor = i;
      conn.selStart = i; conn.selEnd = i;
      conn._dragging = true;   // 拖选
    }
    _hxPaintSel(conn);
    _hxUpdateInfo(conn);
    conn.scroll.focus();
    e.preventDefault();
  });
  conn.canvas.addEventListener('mousemove', e => {
    if (!conn._dragging) return;
    const cell = e.target.closest('[data-hx-i]');
    if (!cell) return;
    const i = +cell.dataset.hxI;
    if (i !== conn.selEnd) {
      conn.selStart = Math.min(conn.cursor, i);
      conn.selEnd = Math.max(conn.cursor, i);
      _hxPaintSel(conn);
      _hxUpdateInfo(conn);
    }
  });
  // a237 P1：mouseup 挂 document（拖出画布也要结束拖选）但必须存 conn——
  // 匿名闭包会钉死 conn.bytes（可编辑文件整读 ≤16MB）+ 脱离 wrap，
  // _edCloseNow 统一摘除
  conn._hxUp = () => { conn._dragging = false; };
  document.addEventListener('mouseup', conn._hxUp);
  conn.canvas.addEventListener('dblclick', e => {
    // 双击字节 = 取消选区回单光标
    const cell = e.target.closest('[data-hx-i]');
    if (!cell) return;
    conn.cursor = +cell.dataset.hxI;
    conn.selStart = conn.selEnd = -1;
    _hxPaintSel(conn);
    _hxUpdateInfo(conn);
  });
  conn.scroll.addEventListener('keydown', e => {
    if (!conn.editable || conn.cursor < 0) return;
    if (/^[0-9a-fA-F]$/.test(e.key)) {
      e.preventDefault();
      const off = conn.cursor;
      conn._editState = conn._editState || { hi: null };
      if (conn._editState.hi === null) {
        conn._editState.hi = parseInt(e.key, 16);
      } else {
        const v = (conn._editState.hi << 4) | parseInt(e.key, 16);
        conn._editState.hi = null;
        conn.bytes[off] = v;
        conn.dirty = true;
        _hxMarkDirty(conn);
        conn.cursor = Math.min(off + 1, conn.size - 1);
        _hxRenderRows(conn, conn.renderedFrom, conn.renderedTo, true);
        _hxPaintSel(conn);
        _hxUpdateInfo(conn);
      }
    } else if (e.key === 'ArrowRight') { e.preventDefault(); conn.cursor = Math.min(conn.cursor + 1, conn.size - 1); _hxPaintSel(conn); _hxUpdateInfo(conn); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); conn.cursor = Math.max(conn.cursor - 1, 0); _hxPaintSel(conn); _hxUpdateInfo(conn); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); conn.cursor = Math.min(conn.cursor + ROW_BYTES, conn.size - 1); _hxPaintSel(conn); _hxUpdateInfo(conn); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); conn.cursor = Math.max(conn.cursor - ROW_BYTES, 0); _hxPaintSel(conn); _hxUpdateInfo(conn); }
  });

  // ---- 工具栏 ----
  // 工具栏 + 跳转/查找条按钮统一处理（绑 wrap——× 按钮在 gotoBar/findBar 内，
  // 只绑 toolbar 收不到这些点击，曾导致「× 关不掉」）
  wrap.addEventListener('click', async e => {
    const btn = e.target.closest('[data-hx-action]');
    if (!btn) return;
    const act = btn.dataset.hxAction;
    if (act === 'save') _hxSave(conn);
    else if (act === 'goto') { conn.gotoBar.style.display = 'flex'; conn.gotoInput.focus(); }
    else if (act === 'gotoOk') {
      const v = conn.gotoInput.value.trim();
      const off = /^0x/i.test(v) ? parseInt(v, 16) : parseInt(v, 10);
      if (!isNaN(off) && off >= 0 && off < conn.size) { conn.gotoBar.style.display = 'none'; _hxScrollToOffset(conn, off); }
      else showBanner('偏移无效（0 ~ 0x' + (conn.size - 1).toString(16).toUpperCase() + '）', 3000, true);
    }
    else if (act === 'gotoCancel') conn.gotoBar.style.display = 'none';
    else if (act === 'find') { conn.findBar.style.display = 'flex'; conn.findInput.focus(); }
    else if (act === 'findNext') _hxFindNext(conn);
    else if (act === 'findAll') _hxFindAll(conn);
    else if (act === 'findCancel') { conn.findBar.style.display = 'none'; conn.findHits = []; conn._findQ = null; conn.findCount.textContent = ''; _hxRenderRows(conn, conn.renderedFrom, conn.renderedTo, true); }
  });
  conn.gotoInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); conn.gotoInput.blur(); wrap.querySelector('[data-hx-action="gotoOk"]').click(); } });
  conn.findInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); _hxFindNext(conn); } });
  // 字节序切换（数据检视 + 分组显示）
  wrap.querySelectorAll('input[name="hx-be"]').forEach(r => {
    r.addEventListener('change', () => { conn.bigEndian = r.value === 'be'; _hxRenderInspector(conn); _hxRenderRows(conn, conn.renderedFrom, conn.renderedTo, true); _hxPaintSel(conn); });
  });
  // 查看方式（HxD 同款）：hex 8/16/32/64 位分组 / 无符号十进制分组
  const viewSel = wrap.querySelector('[data-hx-view]');
  if (viewSel) viewSel.addEventListener('change', () => {
    const v = viewSel.value;
    conn.viewMode = v;
    conn.viewDec = v[0] === 'u';
    conn.viewBytes = parseInt(v.replace('u', ''), 10) / 8;
    conn.renderedFrom = -1;   // 强制重画
    _hxRenderHead(conn);
    conn.render();
    _hxPaintSel(conn);
  });
  // 0x00 灰显开关（可配置）：localStorage 持久化 + 全部已开 hex tab 即时生效
  const zeroCk = wrap.querySelector('[data-hx-zero]');
  if (zeroCk) {
    zeroCk.checked = conn.zeroGray;
    zeroCk.addEventListener('change', () => {
      try { localStorage.setItem('hx_zeroGray', zeroCk.checked ? '1' : '0'); } catch(e) {}
      // 同步所有 hex tab（多文件同偏好）
      for (const pid in connections) {
        const c = connections[pid];
        if (!c || !c.meta || c.meta.kind !== 'hex') continue;
        c.zeroGray = zeroCk.checked;
        c.renderedFrom = -1;
        _hxRenderHead(c);
        c.render();
        _hxPaintSel(c);
      }
    });
  }
  wrap.addEventListener('keydown', e => {
    // 此点刻意保持 strict（不传 loose）：hex 原条件大小写敏感、Ctrl+Shift+F
    // 原本不命中——loose 反而新增命中改变原行为（复审 R1 已声明）
    if (typeof hkMatch === 'function'
        ? hkMatch(e, window._HK && window._HK.docSearch)
        : ((e.ctrlKey || e.metaKey) && e.key === 'f')) { e.preventDefault(); conn.findBar.style.display = 'flex'; conn.findInput.focus(); }
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); _hxSave(conn); }
  });
  // 关 tab 脏确认（closeEditorTab 调）：应用风格弹窗
  conn.confirmClose = () => _hxConfirm('未保存的修改',
    `「${name}」有未保存的修改，关闭将丢失。确定关闭？`);

  notifyTaskDone(nid, {ok:true, title:'hex 已打开', detail:name});
  switchTab(portId);
  conn.render();
  if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+name, label:name, data:{kind:'hex', name, path}});
}

// ---- 列头：随查看方式重建（HxD 同款，分组位宽对齐数据列） ----
// 列头与数据行组必须用完全相同的 class/宽度规则（曾因两侧宽度类不一致全错位）
const _HX_DEC_W = {1: 3, 2: 5, 4: 10, 8: 20};   // 每组字节数 → 十进制字符宽
// 组样式（列头/数据共用）：十进制右对齐 + ch 定宽；hex 左对齐 + 固定 min-width
function _hxGrpClass(conn) {
  const bw = conn.viewBytes;
  if (conn.viewDec) return ' dec hx-dec' + bw;
  return bw > 1 ? ' hx-b-g' + bw : '';
}
function _hxGrpStyle(conn) {
  if (!conn.viewDec) return '';
  return ` style="min-width:${_HX_DEC_W[conn.viewBytes] + 1}ch;text-align:right"`;   // +1ch 组间空隙
}
function _hxRenderHead(conn) {
  const head = conn.wrap.querySelector('[data-hx-head]');
  if (!head) return;
  const bw = conn.viewBytes;   // 每组字节数
  let html = '';
  for (let g = 0; g < 16 / bw; g++) {
    const off = g * bw;
    const txt = conn.viewDec ? String(off).padStart(_HX_DEC_W[bw], ' ') : off.toString(16).toUpperCase().padStart(bw * 2, '0');
    html += `<span class="hx-b hx-b-head${_hxGrpClass(conn)}"${_hxGrpStyle(conn)}>${esc(txt)}</span>`;
  }
  head.innerHTML = html;
}

// ---- 渲染行区间：偏移 + 数据区（按查看方式分组）+ ASCII 三栏 ----
function _hxRenderRows(conn, from, to, force) {
  if (!force && from === conn.renderedFrom && to === conn.renderedTo && conn.canvas.children.length) return;
  const frag = document.createDocumentFragment();
  const hitSet = conn.findHits.length ? new Set(conn.findHits) : null;
  const bw = conn.viewBytes;   // 分组字节数（1/2/4/8）
  // 组内字节序：大端原序显示，小端逆序（HxD 小端下 16/32/64 位组内低字节在前）
  const order = conn.bigEndian ? null : Array.from({length: bw}, (_, i) => bw - 1 - i);
  const grpVal = (off, len) => {
    // 取 off 起 len 字节按组内字节序拼值
    let v = 0n;
    for (let k = 0; k < len; k++) {
      const idx = order ? off + order[k] : off + k;
      v = (v << 8n) | BigInt(conn.byteAt(idx));
    }
    return v;
  };
  for (let r = from; r < to; r++) {
    const off = r * 16;
    const row = document.createElement('div');
    row.className = 'hx-row';
    row.style.top = (r * conn.rowHeight) + 'px';
    let hexHtml = '', asciiHtml = '';
    const rendered = new Set();   // 本行已被分组渲染过的字节下标
    for (let c = 0; c < 16; c += bw) {
      const i = off + c;
      if (i >= conn.size) { hexHtml += '<span class="hx-b hx-b-empty"></span>'; for (let k = 0; k < bw && off + c + k < 16; k++) asciiHtml += '<span class="hx-a hx-a-empty"></span>'; continue; }
      const avail = Math.min(bw, conn.size - i);
      const v = avail === bw ? grpVal(i, bw) : null;   // 尾部残组（不足 bw 字节）不拼值
      let txt;
      if (v === null) txt = '—'.repeat(1);
      else if (conn.viewDec) txt = v.toString(10).padStart(_HX_DEC_W[bw], ' ');   // 十进制定宽右对齐（列列对齐关键）
      else txt = v.toString(16).toUpperCase().padStart(bw * 2, '0');
      const z = (v === 0n && conn.zeroGray) ? ' z' : '';   // 全 0 组灰色弱化（可配置）
      // 组内每个字节保留 data-hx-i（点击/选区定位到字节级）——首字节承载展示文本
      hexHtml += `<span class="hx-b${_hxGrpClass(conn)}${z}"${_hxGrpStyle(conn)} data-hx-i="${i}">${esc(txt)}</span>`;
      for (let k = 0; k < bw; k++) rendered.add(i + k);
      // ASCII 列仍逐字节
      for (let k = 0; k < bw; k++) {
        const ai = i + k;
        if (ai >= conn.size) { asciiHtml += '<span class="hx-a hx-a-empty"></span>'; continue; }
        const b = conn.byteAt(ai);
        const az = (b === 0 && conn.zeroGray) ? ' z' : '';
        const ch = b >= 32 && b < 127 ? esc(String.fromCharCode(b)) : '.';
        asciiHtml += `<span class="hx-a${az}" data-hx-i="${ai}">${ch}</span>`;
      }
    }
    row.innerHTML = `<span class="hx-off">${off.toString(16).toUpperCase().padStart(8, '0')}</span>` +
      `<span class="hx-hexcol">${hexHtml}</span><span class="hx-ascii">${asciiHtml}</span>`;
    frag.appendChild(row);
  }
  conn.canvas.innerHTML = '';
  conn.canvas.appendChild(frag);
  conn.renderedFrom = from; conn.renderedTo = to;
}

// ---- 选区高亮：重画当前窗口（含 cur/sel/hit 三态；分组模式下组=选区任命中） ----
function _hxPaintSel(conn) {
  const s = conn.selStart, t = conn.selEnd;
  const inSel = i => s >= 0 && t >= s && i >= s && i <= t;
  const hits = conn.findHits.length ? new Set(conn.findHits) : null;
  const hitOf = i => hits && hits.has(i);
  const grpHit = i => {   // 分组显示时组内任一字节命中搜索则整组高亮
    const bw = conn.viewBytes || 1;
    if (bw === 1) return hitOf(i);
    for (let k = 0; k < bw; k++) if (hitOf(i + k)) return true;
    return false;
  };
  conn.canvas.querySelectorAll('[data-hx-i]').forEach(el => {
    const i = +el.dataset.hxI;
    el.classList.toggle('cur', i === conn.cursor);
    el.classList.toggle('sel', inSel(i) && (s !== t || s === conn.cursor ? true : false));
    el.classList.toggle('hit', grpHit(i));
  });
  // 选区行滚进视图（光标行）
  if (conn.cursor >= 0) {
    const y = Math.floor(conn.cursor / 16) * conn.rowHeight;
    if (y < conn.scroll.scrollTop) conn.scroll.scrollTop = y;
    else if (y + conn.rowHeight > conn.scroll.scrollTop + conn.scroll.clientHeight)
      conn.scroll.scrollTop = y + conn.rowHeight - conn.scroll.clientHeight;
  }
}

function _hxScrollToOffset(conn, off) {
  conn.scroll.scrollTop = Math.floor(off / 16) * conn.rowHeight;
  conn.cursor = off;
  conn.render();
  _hxPaintSel(conn);
  _hxUpdateInfo(conn);
}

function _hxUpdateInfo(conn) {
  const cur = conn.cursor >= 0 ? ' · 偏移 0x' + conn.cursor.toString(16).toUpperCase() : '';
  conn.infoEl.textContent = (conn.editable ? '' : '只读 · ') +
    conn.size.toLocaleString() + ' 字节' + cur + (conn.dirty ? ' · 未保存' : ' · 已保存');
  _hxRenderInspector(conn);
}

// ---- 数据检视（HxD「特殊编辑器」同款）：光标处多类型解释 + 字节序 ----
function _hxRenderInspector(conn) {
  const el = conn.inspEl;
  if (!el) return;
  if (conn.cursor < 0) { el.innerHTML = '<div class="hx-insp-empty">点击字节查看</div>'; return; }
  // 优先按选区解释：选中多字节时从 selStart 取数（字节范围选择，HxD/ImHex 同款）
  const hasSel = conn.selStart >= 0 && conn.selEnd > conn.selStart;
  const off = hasSel ? conn.selStart : conn.cursor;
  const n = (bytes) => {   // 取 off 起的 bytes 字节（跨文件尾截断）
    const out = [];
    for (let i = 0; i < bytes && off + i < conn.size; i++) out.push(conn.byteAt(off + i));
    return out;
  };
  const be = conn.bigEndian;
  const num = (bs, signed) => {
    if (!bs.length) return null;
    // 字节序：be 原序，le 反序
    const arr = be ? bs : bs.slice().reverse();
    let v = 0n;
    for (const b of arr) v = (v << 8n) | BigInt(b);
    const bits = BigInt(bs.length * 8);
    if (signed) {
      const signBit = 1n << (bits - 1n);
      if (v >= signBit) v -= (1n << bits);
    }
    return v;
  };
  const i8 = n(1), i16 = n(2), i24 = n(3), i32 = n(4), i48 = n(6), i64 = n(8);
  // 浮点：DataView 按 IEEE754 位模式组（littleEndian 参数 = !be）
  const f16 = i16.length === 2 ? new DataView(new Uint8Array(i16).buffer).getFloat16 ? new DataView(new Uint8Array(i16).buffer).getFloat16(0, !be) : null : null;
  const bf16 = i16.length === 2 ? _hxBFloat16(i16, be) : null;
  const f32 = i32.length === 4 ? new DataView(new Uint8Array(i32).buffer).getFloat32(0, !be) : null;
  const f64 = i64.length === 8 ? new DataView(new Uint8Array(i64).buffer).getFloat64(0, !be) : null;
  // LEB128 变长整数（ImHex 同款）：每字节低 7 位有效，最高位继续标志
  const leb = (signed) => {
    let v = 0n, shift = 0n;
    for (const b of n(10)) {
      v |= BigInt(b & 0x7F) << shift;
      shift += 7n;
      if (!(b & 0x80)) {
        if (signed && shift < 64n && (b & 0x40)) v -= (1n << shift);   // 符号扩展
        return v;
      }
      if (shift > 70n) break;   // 防御：最多 10 字节
    }
    return null;
  };
  const u32v = i32.length === 4 ? num(i32, false) : null;
  const rgba = u32v !== null ? 'R:' + ((Number(u32v) >> 24) & 255) + ' G:' + ((Number(u32v) >> 16) & 255) + ' B:' + ((Number(u32v) >> 8) & 255) + ' A:' + (Number(u32v) & 255) : null;
  const time32 = u32v !== null && Number(u32v) < 4102444800 ? new Date(Number(u32v) * 1000).toLocaleString() : null;   // 2100 年前视为 unix 秒
  // ASCII：光标处 16 字节的可打印串
  const a16 = n(16).map(b => (b >= 32 && b < 127) ? String.fromCharCode(b) : '.').join('');
  const hex16 = i16.length ? Array.from(n(16)).map(b => b.toString(16).toUpperCase().padStart(2, '0')).join(' ') : '';
  // 二进制展示：按选区字节数取 8/16/32/64 位（ImHex 同款，选区优先）
  const selN = hasSel ? conn.selEnd - conn.selStart + 1 : 1;
  const binBytes = selN >= 8 ? n(8) : selN >= 4 ? n(4) : selN >= 2 ? n(2) : n(1);
  // 字节序组位串：大端直接拼接，小端字节逆序（高位在前展示）
  const binArr = be ? binBytes : binBytes.slice().reverse();
  const binStr = binArr.length ? binArr.map(b => b.toString(2).padStart(8, '0')).join(' ') : null;
  const row = (name, val, title) =>
    `<div class="hx-insp-row" title="${title}"><span class="hx-insp-k">${name}</span><span class="hx-insp-v">${val === null ? '—' : esc(String(val))}</span></div>`;
  el.innerHTML =
    row('Binary', binStr, '二进制 ' + (binArr.length * 8) + ' 位（按选区/字节序）') +
    row('Bool', i8.length ? (i8[0] === 0 ? 'false' : i8[0] === 1 ? 'true' : 'Invalid') : null, '布尔') +
    row('Int8', num(i8, true), '有符号 8 位') +
    row('Uint8', num(i8, false), '无符号 8 位') +
    row('Int16', num(i16, true), '有符号 16 位') +
    row('Uint16', num(i16, false), '无符号 16 位') +
    row('Int24', num(i24, true), '有符号 24 位') +
    row('Uint24', num(i24, false), '无符号 24 位') +
    row('Int32', num(i32, true), '有符号 32 位') +
    row('Uint32', num(i32, false), '无符号 32 位') +
    row('Int48', num(i48, true), '有符号 48 位') +
    row('Uint48', num(i48, false), '无符号 48 位') +
    row('Int64', num(i64, true), '有符号 64 位') +
    row('Uint64', num(i64, false), '无符号 64 位') +
    row('SLEB128', leb(true), '有符号变长整数') +
    row('ULEB128', leb(false), '无符号变长整数') +
    row('Float16', f16 === null ? null : (isFinite(f16) ? f16.toFixed(4) : 'Inf/NaN'), 'IEEE754 半精度') +
    row('BFloat16', bf16 === null ? null : (isFinite(bf16) ? bf16.toFixed(4) : 'Inf/NaN'), '脑浮点 16') +
    row('Float32', f32 === null ? null : (isFinite(f32) ? f32.toFixed(6) : 'Inf/NaN'), 'IEEE754 单精度') +
    row('Float64', f64 === null ? null : (isFinite(f64) ? f64.toPrecision(15) : 'Inf/NaN'), 'IEEE754 双精度') +
    row('RGBA8', rgba, '32 位颜色（大端 RGBA 排列）') +
    row('Time32', time32, 'unix 秒时间戳') +
    row('HEX', hex16, (hasSel ? '选区起' : '光标起') + ' 16 字节') +
    row('ASCII', a16, (hasSel ? '选区起' : '光标起') + ' 16 字符（不可打印为点）');
  // 顶部选区范围信息条（有选区时显示）
  if (hasSel) {
    const cnt = conn.selEnd - conn.selStart + 1;
    el.insertAdjacentHTML('afterbegin',
      `<div class="hx-insp-sel">选区 0x${conn.selStart.toString(16).toUpperCase()} ~ 0x${conn.selEnd.toString(16).toUpperCase()} (${cnt} 字节)</div>`);
  }
}
// bfloat16：高 16 位 = float32 的高 16 位（脑浮点，ImHex 同款）
function _hxBFloat16(bs, be) {
  const u16 = be ? (bs[0] << 8) | bs[1] : (bs[1] << 8) | bs[0];
  const f32u = (u16 << 16) >>> 0;
  return new DataView(new Uint32Array([f32u]).buffer).getFloat32(0, true);
}

function _hxMarkDirty(conn) {
  const lbl = conn.tab.querySelector('.label');
  if (lbl && !lbl.textContent.startsWith('*')) lbl.textContent = '*' + lbl.textContent;
}

// ---- 应用风格确认弹窗（替代原生 confirm——画风统一） ----
function _hxConfirm(title, msg) {
  return new Promise(resolve => {
    let m = document.getElementById('hxConfirmModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'hxConfirmModal';
      m.innerHTML = `
        <div class="box" style="max-width:380px;">
          <div class="head"><strong id="hxConfirmTitle">确认</strong>
            <div class="head-actions"><button class="btn ghost icon-btn" id="hxConfirmClose">✕</button></div>
          </div>
          <div style="padding:18px 20px;">
            <div id="hxConfirmMsg" style="color:var(--muted);font-size:12px;line-height:1.6;margin-bottom:16px;word-break:break-all;"></div>
            <div style="display:flex;gap:10px;justify-content:flex-end;">
              <button class="btn ghost" id="hxConfirmNo">取消</button>
              <button class="btn primary" id="hxConfirmYes">确定</button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(m);
    }
    m.querySelector('#hxConfirmTitle').textContent = title;
    m.querySelector('#hxConfirmMsg').textContent = msg;
    const finish = v => { m.classList.remove('show'); resolve(v); };
    m.querySelector('#hxConfirmYes').onclick = () => finish(true);
    m.querySelector('#hxConfirmNo').onclick = () => finish(false);
    m.querySelector('#hxConfirmClose').onclick = () => finish(false);
    m.classList.add('show');
  });
}

// ---- 搜索：hex 字节序列（含空格/0x）或 ASCII 文本 ----
function _hxParseQuery(q) {
  q = (q || '').trim();
  if (!q) return null;
  const hexNorm = q.replace(/0x/gi, '').replace(/[\s,]+/g, '');
  // hex 判定：全 hex 字符 + 偶数长度 +（带空格/0x 或长度>4 纯 hex 视为字节）
  if (/^[0-9a-fA-F]+$/.test(hexNorm) && hexNorm.length % 2 === 0 &&
      (/\s|0x/i.test(q) || hexNorm.length > 4)) {
    const out = [];
    for (let i = 0; i < hexNorm.length; i += 2) out.push(parseInt(hexNorm.substr(i, 2), 16));
    return Uint8Array.from(out);
  }
  return new TextEncoder().encode(q);
}
function _hxSearchBuf(buf, pat, base, hits) {
  const first = pat[0], n = pat.length;
  for (let i = 0; i + n <= buf.length; i++) {
    if (buf[i] !== first) continue;
    let ok = true;
    for (let j = 1; j < n; j++) { if (buf[i + j] !== pat[j]) { ok = false; break; } }
    if (ok) { hits.push(base + i); if (hits.length > 500) return; }
  }
}
async function _hxSearchAll(conn, pat) {
  const hits = [];
  try {
    if (conn.bytes) {
      _hxSearchBuf(conn.bytes, pat, 0, hits);
    } else {
      for (let ci = 0; ci * HEX_CHUNK < conn.size; ci++) {
        // a237 P2：关 tab（_hxAbort）/重开同路径后旧循环立即停——
        // 此前会按 512KB/块把 1GB 文件 2000+ 次串行拉完，纯空转
        if (connections[conn.portId] !== conn) return hits;
        const b = await conn.fetchChunk(ci * HEX_CHUNK, HEX_CHUNK);
        _hxSearchBuf(b, pat, ci * HEX_CHUNK, hits);
        if (hits.length > 500) break;
      }
    }
  } catch (e) {
    if (e && e.name === 'AbortError') return hits;   // 关 tab 中止，静默
    throw e;
  }
  return hits;
}
// ---- 搜索命中 → 高亮（多字节命中高亮整个序列；分组模式亮组） ----
function _hxPaintHits(conn) {
  const pat = _hxParseQuery(conn._findQ);   // 命中长度 = 搜索模式长度
  const plen = pat ? pat.length : 1;
  const bw = conn.viewBytes || 1;
  const hitSet = new Set();
  for (const h of conn.findHits) {
    if (bw > 1) hitSet.add(Math.floor(h / bw) * bw);   // 分组模式：亮整组
    else for (let k = 0; k < plen; k++) hitSet.add(h + k);   // 单字节模式：高亮整个命中序列
  }
  conn.canvas.querySelectorAll('[data-hx-i]').forEach(el => {
    el.classList.toggle('hit', hitSet.has(+el.dataset.hxI));
  });
}
// 跳到命中：选区 = 命中首字节起的 plen 字节（多字节命中直接可视）
function _hxJumpHit(conn, off) {
  const pat = _hxParseQuery(conn._findQ);
  const plen = pat ? pat.length : 1;
  _hxScrollToOffset(conn, off);
  conn.selStart = off; conn.selEnd = Math.min(off + plen - 1, conn.size - 1);
  _hxPaintSel(conn);
  _hxUpdateInfo(conn);
}
async function _hxFindNext(conn) {
  const q = conn.findInput.value;
  const pat = _hxParseQuery(q);
  if (!pat) { conn.findCount.textContent = ''; return; }
  if (conn._findQ !== q || !conn.findHits.length) {
    conn.findHits = await _hxSearchAll(conn, pat);
    conn._findQ = q; conn.findIdx = -1;
    _hxRenderRows(conn, conn.renderedFrom, conn.renderedTo, true);
    _hxPaintHits(conn);
  }
  if (!conn.findHits.length) { conn.findCount.textContent = '无命中'; return; }
  conn.findIdx = (conn.findIdx + 1) % conn.findHits.length;
  conn.findCount.textContent = (conn.findIdx + 1) + '/' + conn.findHits.length;
  _hxJumpHit(conn, conn.findHits[conn.findIdx]);
}
async function _hxFindAll(conn) {
  const pat = _hxParseQuery(conn.findInput.value);
  if (!pat) return;
  conn.findHits = await _hxSearchAll(conn, pat);
  conn._findQ = conn.findInput.value; conn.findIdx = -1;
  conn.findCount.textContent = conn.findHits.length ? (conn.findHits.length + ' 处') : '无命中';
  _hxRenderRows(conn, conn.renderedFrom, conn.renderedTo, true);
  _hxPaintHits(conn);
  if (conn.findHits.length) _hxJumpHit(conn, conn.findHits[0]);
}

// ---- 保存 ----
async function _hxSave(conn) {
  if (!conn.editable || !conn.bytes) { showBanner('只读模式（超过 16MB），不能保存', 4000, true); return; }
  try {
    let b64;
    if (conn.isIhex) {
      // Intel HEX：镜像 → hex 文本（16 字节/行，含 EOF 记录）
      // 超 64KB 镜像必须发 type 04 扩展线性地址记录——只发 type 00 时
      // 地址字段 (off & 0xFFFF) 会回绕，后半 64KB 全写到错误地址=固件损坏
      let out = '';
      let extSeg = -1;   // 当前已输出的扩展段（高 16 位），-1 表示尚未输出任何
      const emitExt = (seg) => {
        const sum = (2 + ((seg >> 8) & 0xFF) + (seg & 0xFF)) & 0xFF;
        const chk = ((0x100 - sum) & 0xFF).toString(16).toUpperCase().padStart(2, '0');
        out += ':02000004' + seg.toString(16).toUpperCase().padStart(4, '0') + chk + '\n';
        extSeg = seg;
      };
      for (let off = 0; off < conn.bytes.length; off += 16) {
        const seg = (off >> 16) & 0xFFFF;
        if (seg !== extSeg) emitExt(seg);
        const len = Math.min(16, conn.bytes.length - off);
        let sum = len + ((off >> 8) & 0xFF) + (off & 0xFF);
        let data = '';
        for (let i = 0; i < len; i++) { const b = conn.bytes[off + i]; sum += b; data += b.toString(16).toUpperCase().padStart(2, '0'); }
        const chk = ((0x100 - (sum & 0xFF)) & 0xFF).toString(16).toUpperCase().padStart(2, '0');
        out += ':' + len.toString(16).toUpperCase().padStart(2, '0') +
               (off & 0xFFFF).toString(16).toUpperCase().padStart(4, '0') + '00' + data + chk + '\n';
      }
      out += ':00000001FF\n';
      b64 = btoa(out);
    } else {
      let s = '';
      for (let i = 0; i < conn.bytes.length; i += 8192)
        s += String.fromCharCode.apply(null, conn.bytes.subarray(i, Math.min(i + 8192, conn.bytes.length)));
      b64 = btoa(s);
    }
    const r = await fetch('/api/hex/save', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path: conn.hexPath, data: b64})});
    const j = await r.json();
    if (!j.ok) throw new Error(j.err);
    conn.dirty = false;
    const lbl = conn.tab.querySelector('.label');
    if (lbl && lbl.textContent.startsWith('*')) lbl.textContent = lbl.textContent.slice(1);
    _hxUpdateInfo(conn);
    showBanner('已保存 ' + j.size.toLocaleString() + ' 字节');
  } catch(e) { showBanner('保存失败: ' + (e.message || e), 4000, true); }
}
