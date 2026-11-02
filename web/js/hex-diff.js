// ============================================================
// 二进制文件对比（hex diff）：双栏字节视图，差异字节高亮 + 导航。
// 背景：Monaco DiffEditor 走 /api/read_text 按文本读，bin 固件对比是乱码
// （用户需求：两个 2 进制也要能对比）。GitHub 无合适的独立 JS 二进制
// diff 库（hex.js/ImHex Web 是完整编辑器主体，不能只抠对比），自建：
// 后端 /api/bin/diff 用 difflib.SequenceMatcher 出字节级差异块，
// 前端复用 hex-viewer 的行渲染结构（偏移|hex|ASCII，类 HxD）双栏对比。
// 对齐策略：按差异块对齐——两栏独立渲染（A/B 尺寸可不同），每处差异
// 两侧行内高亮差异字节区间；导航按块跳转，两栏同步滚动。
// ============================================================

const HXD_ROW = 16;   // 每行 16 字节（与 hex-viewer 一致）

// ---- 取差异标记：side('a'|'b') + 字节偏移 → 是否在差异块内（二分查找）----
function _hxdMakeLookup(blocks, side) {
  const key = side === 'a' ? ['a_start', 'a_end'] : ['b_start', 'b_end'];
  const list = blocks.map(b => [b[key[0]], b[key[1]]]).sort((x, y) => x[0] - y[0]);
  return (i) => {
    let lo = 0, hi = list.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (i < list[mid][0]) hi = mid - 1;
      else if (i >= list[mid][1]) lo = mid + 1;
      else return true;
    }
    return false;
  };
}

// ---- 渲染一侧可视行区间（窗口式，复用 hex-viewer 的 .hx-* 样式）----
// 只看差异模式：差异行按【差异行序号】紧凑重排（行内偏移列仍显示真实
// 地址）。之前只靠 CSS display:none 隐藏非差异行，但行是绝对定位
// （top=原始行号×rowH），隐藏后差异行仍停在原位置——中间大片空洞、
// 篇幅不缩短、滚动/跳转窗口计算全错（用户截图报的 bug）。
function _hxdRenderSide(side) {
  const c = side.conn;
  const onlyDiff = c.onlyDiff;
  const vr = side.visibleRows;
  // 紧凑坐标：只看差异 = slots 查表（数据行+分裂标识行）；普通 = 原始行
  const total = onlyDiff ? side.slots.length : side.rows;
  const first = Math.floor(side.scroll.scrollTop / side.rowH);
  const count = Math.ceil(side.scroll.clientHeight / side.rowH) + 4;
  const from = Math.max(0, first - 2), to = Math.min(total, first + count);
  if (from === side.renderedFrom && to === side.renderedTo && side.canvas.children.length) return;
  const frag = document.createDocumentFragment();
  const isDiff = side.lookup;
  for (let slot = from; slot < to; slot++) {
    const r = onlyDiff ? null : slot;
    if (onlyDiff) {
      const s = side.slots[slot];
      if (s.br !== undefined) {
        // 分裂标识行（头断点 prevR=-1 从文件头起算；尾断点 nextR=末行）
        const prevR = s.br > 0 ? vr[s.br - 1] : -1;
        const nextR = s.br < vr.length ? vr[s.br] : side.rows - 1;
        const gap = (nextR - prevR - 1) * HXD_ROW;
        const br = document.createElement('div');
        br.className = 'hxd-break';
        br.style.top = (slot * side.rowH) + 'px';
        br.innerHTML = `<span class="bx-gap">↕ 跳过 ${gap.toLocaleString()} 字节（0x${Math.max(0, (prevR + 1) * HXD_ROW).toString(16).toUpperCase()} ~ 0x${Math.max(0, nextR * HXD_ROW - 1).toString(16).toUpperCase()}）</span>`;
        frag.appendChild(br);
        continue;
      }
      var row0 = s.row;
    } else var row0 = slot;
    const off = row0 * HXD_ROW;
    const row = document.createElement('div');
    row.className = 'hx-row' + (side.rowHasDiff(row0) ? ' hxd-row-diff' : '');
    row.style.top = (slot * side.rowH) + 'px';      // 定位按紧凑槽位
    let hexHtml = '', asciiHtml = '';
    for (let j = 0; j < HXD_ROW; j++) {
      const i = off + j;
      if (i >= side.size) {
        hexHtml += '<span class="hx-b hx-b-empty"></span>';
        asciiHtml += '<span class="hx-a hx-a-empty"></span>';
        continue;
      }
      const b = side.byteAt(i);
      // 字节级高亮：等长文件按【真实字节比对】标色，不信块区间——后端块是
      // 64B 合并间距的粗粒度（1089B 块内可能只有 24 个真实差异字节），按块
      // 区间标色会把大段相同内容整片标绿/红（用户实锤报的 bug）。不等长
      // 文件无逐字节对齐关系，仍按块区间标。
      let d;
      if (side.conn.aSize === side.conn.bSize) {
        const other = side === side.conn.sideA ? side.conn.sideB : side.conn.sideA;
        // 对侧该字节块未加载（byteAt 兜底 0）时先不标——假阳性比晚标更糟；
        // ensureWindow 补载后 reloaded 重渲染会带上真实比对结果
        const cs = other.chunkSize || 512 * 1024;   // chunk 大小存 side 上（HXD_CHUNK 是 makeSide 局部量，顶层渲染函数够不着）
        const oc = other._chunks.get(i / cs | 0);
        d = (oc && i < other.size && side.byteAt(i) !== oc[i % cs]) ? ' d' : '';
      } else {
        d = isDiff(i) ? ' d' : '';
      }
      hexHtml += `<span class="hx-b${d}">${b.toString(16).toUpperCase().padStart(2, '0')}</span>`;
      const ch = b >= 32 && b < 127 ? esc(String.fromCharCode(b)) : '.';
      asciiHtml += `<span class="hx-a${d}">${ch}</span>`;
    }
    row.innerHTML = `<span class="hx-off">${off.toString(16).toUpperCase().padStart(8, '0')}</span>` +
      `<span class="hx-hexcol">${hexHtml}</span><span class="hx-ascii">${asciiHtml}</span>`;
    frag.appendChild(row);
  }
  side.canvas.innerHTML = '';
  side.canvas.appendChild(frag);
  side.renderedFrom = from; side.renderedTo = to;
  // 可视窗口字节异步补载（大文件不全量进内存）：窗口内首次有块落地
  // → 重渲染补真实字节（窗口外滚回来时会再触发，_pending 防重复请求）
  if (side.ensureWindow) {
    let fromRow, toRow;
    if (onlyDiff) {
      // 本窗口覆盖的数据行范围（断点行无数据，取窗口内首/末数据行）
      let firstRow = -1, lastRow = -1;
      for (let s = from; s < to; s++) {
        const e = side.slots[s];
        if (e && e.row !== undefined) { if (firstRow < 0) firstRow = e.row; lastRow = e.row; }
      }
      if (firstRow < 0) return;   // 窗口全是断点行
      fromRow = firstRow; toRow = lastRow + 1;
    } else { fromRow = from; toRow = to; }
    side.ensureWindow(fromRow * HXD_ROW, Math.min(side.size, toRow * HXD_ROW)).then(reloaded => {
      if (reloaded) { side.renderedFrom = -1; _hxdRenderSide(side); }
    });
  }
}

// ---- 行级差异标记 + 只看差异的可见行表 ----
// visibleRows：差异行 ±CTX 行（上下文）升序去重；breaks：相邻可见行地址
// 不连续的断点（渲染时插分裂标识行）。偏移列仍显示真实地址。
const HXD_CTX_ROWS = 3;   // 差异前后各多显示 3 行上下文
function _hxdMarkRowDiffs(side) {
  const rows = side.rows;
  const arr = new Uint8Array(rows);
  const lookup = side.lookup;
  for (const b of side.conn.blocks) {
    const s = side.keyOf(b)[0], e = side.keyOf(b)[1];
    for (let i = s; i < e && i < side.size; i++) arr[i / HXD_ROW | 0] = 1;
  }
  side.rowHasDiff = r => !!arr[r];
  // diffRows（导航目标）与 visibleRows（只看差异渲染，含 ±3 行上下文）
  side.diffRows = [];
  for (let r = 0; r < rows; r++) if (arr[r]) side.diffRows.push(r);
  const vis = new Set();
  for (const r of side.diffRows)
    for (let k = Math.max(0, r - HXD_CTX_ROWS); k <= Math.min(rows - 1, r + HXD_CTX_ROWS); k++) vis.add(k);
  side.visibleRows = [...vis].sort((a, b) => a - b);
  // 断点：可见行地址不连续处（含头尾——第一处差异之前/最后一处差异
  // 之后被跳过的部分也要有分裂标识，用户需求）
  const vr = side.visibleRows;
  side.visibleBreaks = [];
  if (vr.length) {
    if (vr[0] > 0) side.visibleBreaks.push(0);   // 头部断点（在 vr[0] 前）
    for (let i = 1; i < vr.length; i++)
      if (vr[i] !== vr[i - 1] + 1) side.visibleBreaks.push(i);
    if (vr[vr.length - 1] < rows - 1) side.visibleBreaks.push(vr.length);   // 尾部断点
  }
  // 槽位表 slots[k] = {br: vIdx | row}：k 紧凑序号 → 断点（vIdx）或数据行。
  // 预计算一次（O(n)），渲染/跳转 O(1) 查表——二分推导曾两次 off-by-one，
  // 查表不会错。
  side.slots = [];
  {
    const bset = new Set(side.visibleBreaks);
    for (let v = 0; v <= vr.length; v++) {
      if (bset.has(v)) side.slots.push({ br: v });   // 断点槽（v=vr.length 是尾部）
      if (v < vr.length) side.slots.push({ row: vr[v] });
    }
  }
  side.diffIdx = -1;
}

async function buildHexDiffTab(aPath, bPath) {
  // 复用打开：同 A/B 组合已开 → 切过去
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'bindiff' &&
        ((c.aPath === aPath && c.bPath === bPath) || (c.aPath === bPath && c.bPath === aPath))) {
      switchTab(pid); return;
    }
  }
  // 后台计算提醒：100MB 对比要数秒~十几秒（独立子进程算，不卡 UI），
  // 不提示的话用户以为没点上（用户需求）。先弹 tab + 计算中提示，
  // diff 返回后再建视图。
  const portId0 = 'bindiff:loading:' + aPath + '|' + bPath + ':' + Date.now();
  const loadTab = document.createElement('div');
  loadTab.className = 'tab';
  loadTab.dataset.portId = portId0;
  loadTab.innerHTML = `<span class="led"></span><span class="tab-ico">⏳</span><span class="label">${esc((aPath.split(/[\\/]/).pop() + ' ↔ ' + bPath.split(/[\\/]/).pop()))}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  loadTab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); loadTab.remove(); return; } };
  const es0 = termArea.querySelector('.empty-state');
  if (es0) es0.remove();
  tabs.insertBefore(loadTab, tabs.querySelector('.tab-bar-actions'));
  // 任务型通知：二进制对比后台算（100MB 需数秒~十几秒），转圈常驻到结果出来
  const nid = notifyTask({type:'hex', title:'正在二进制对比', detail:`${aPath.split(/[\\/]/).pop()} ↔ ${bPath.split(/[\\/]/).pop()}（后台计算，不卡其他操作）`});

  // 后端字节 diff
  let j;
  try {
    const r = await fetch('/api/bin/diff', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({a: aPath, b: bPath})});
    j = await r.json();
    if (!j.ok) { loadTab.remove(); notifyTaskDone(nid, {ok:false, title:'二进制对比失败', detail:j.err || '未知错误', ms:6000}); return; }
  } catch(e) { loadTab.remove(); notifyTaskDone(nid, {ok:false, title:'二进制对比请求失败', detail:String(e), ms:6000}); return; }
  loadTab.remove();   // 计算完成，临时 tab 退场，正式对比 tab 顶上

  const aName = (j.a || aPath).split(/[\\/]/).pop();
  const bName = (j.b || bPath).split(/[\\/]/).pop();
  const label = aName === bName ? `${aName}（bin 对比）` : `${aName} ↔ ${bName}`;
  const portId = 'bindiff:' + aPath + '|' + bPath + ':' + Date.now();

  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico"><svg width="14" height="14" viewBox="0 0 22 22" aria-hidden="true"><rect x="3" y="2" width="9" height="13" rx="2" fill="var(--accent)" opacity="0.35"/><rect x="10" y="7" width="9" height="13" rx="2" fill="var(--accent)" opacity="0.6"/></svg></span><span class="label">${esc(label)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-hxd-action="nav-prev" title="上一处差异">▲ 上一处</button>
        <button class="lv-btn" data-hxd-action="nav-next" title="下一处差异">▼ 下一处</button>
        <button class="lv-btn" data-hxd-action="only-diff" title="只看差异行（其余行隐藏，行号保留真实偏移）">≡ 只看差异</button>
        <span class="lv-info" data-hxd-info>对比中…</span>
      </div>
      <div class="hxd-main">
        <div class="hxd-side" data-hxd-side="a">
          <div class="hxd-side-tag">A · ${esc(aName)} · ${j.a_size} B</div>
          <div class="hx-scroll hxd-scroll" data-hxd-scroll-a tabindex="0">
            <div class="hx-scroll-inner"><div class="hx-canvas" data-hxd-canvas-a></div></div>
          </div>
        </div>
        <div class="hxd-gap"></div>
        <div class="hxd-side" data-hxd-side="b">
          <div class="hxd-side-tag">B · ${esc(bName)} · ${j.b_size} B</div>
          <div class="hx-scroll hxd-scroll" data-hxd-scroll-b tabindex="0">
            <div class="hx-scroll-inner"><div class="hx-canvas" data-hxd-canvas-b></div></div>
          </div>
        </div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const conn = {
    portId, meta: { kind: 'bindiff', label },
    tab, wrap, aPath, bPath, aName, bName,
    infoEl: wrap.querySelector('[data-hxd-info]'),
    aSize: j.a_size, bSize: j.b_size, blocks: j.blocks,
    dirty: false, onlyDiff: false, _navIdx: -1,
  };
  connections[portId] = conn;

  // ---- 两侧数据加载已改窗口式（_hxdRenderSide 内 ensureWindow 按需补块） ----
  const rowH = 22;
  // ---- 两侧数据：窗口式按需加载（100MB 文件不整读进前端内存） ----
  // 复用 /api/hex/read 512KB 分块：byteAt 仅缓存窗口内返回真实字节，
  // 未加载窗口返回 0 兜底先渲染，_hxdRenderSide 每次滚动异步补块，
  // 补完重渲染（参照 hex-viewer 的 chunkCache/ensureWindow 模式）。
  const HXD_CHUNK = 512 * 1024;    // 与后端 READ_CHUNK 一致
  const HXD_MAX_CHUNKS = 8;        // 每侧缓存 8 块 = 4MB（可视窗口 ~100 行足够）
  const makeSide = (size, sideKey, path) => {
    const s = {
      conn, path, size, rowH, chunkSize: HXD_CHUNK,   // 顶层 _hxdRenderSide 真实比对要用
      keyOf: b => sideKey === 'a' ? [b.a_start, b.a_end] : [b.b_start, b.b_end],
      scroll: wrap.querySelector(sideKey === 'a' ? '[data-hxd-scroll-a]' : '[data-hxd-scroll-b]'),
      canvas: wrap.querySelector(sideKey === 'a' ? '[data-hxd-canvas-a]' : '[data-hxd-canvas-b]'),
      renderedFrom: -1, renderedTo: -1,
      _chunks: new Map(),   // chunkIdx → Uint8Array
      _pending: new Set(),  // 加载中的 chunkIdx（防重复请求）
      _bad: new Set(),      // 加载失败的 chunkIdx（本 tab 不再重试，防失败循环）
    };
    s.rows = Math.ceil(size / HXD_ROW);
    s.canvas.style.height = (s.rows * rowH) + 'px';
    s.lookup = _hxdMakeLookup(j.blocks, sideKey);
    s.byteAt = i => {
      if (i < 0 || i >= s.size) return 0;
      const ch = s._chunks.get(i / HXD_CHUNK | 0);
      return ch ? ch[i % HXD_CHUNK] : 0;
    };
    // 补载可视窗口字节：返回 Promise<是否新加载了块>（true 时调用方重渲染）。
    // 缓存超上限时淘汰离当前窗口最远的块（滚动自然滑出旧的）。
    s.ensureWindow = async (fromB, toB) => {
      if (toB <= fromB) return false;
      const c0 = Math.max(0, fromB / HXD_CHUNK | 0);
      const c1 = Math.min(Math.ceil(s.size / HXD_CHUNK) - 1, (toB - 1) / HXD_CHUNK | 0);
      const missing = [];
      for (let ci = c0; ci <= c1; ci++) {
        if (!s._chunks.has(ci) && !s._pending.has(ci) && !s._bad.has(ci)) {
          s._pending.add(ci); missing.push(ci);
        }
      }
      while (s._chunks.size + missing.length > HXD_MAX_CHUNKS && s._chunks.size) {
        let far = null, fd = -1;
        for (const k of s._chunks.keys()) {
          const d = Math.max(k - c1, c0 - k);
          if (d > fd) { fd = d; far = k; }
        }
        s._chunks.delete(far);
      }
      if (!missing.length) return false;
      await Promise.all(missing.map(async ci => {
        try {
          const r = await fetch('/api/hex/read', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({path: s.path, offset: ci * HXD_CHUNK,
                                 length: Math.min(HXD_CHUNK, s.size - ci * HXD_CHUNK)})});
          const jj = await r.json();
          if (jj.ok && jj.data) s._chunks.set(ci, Uint8Array.from(atob(jj.data), c => c.charCodeAt(0)));
          else s._bad.add(ci);
        } catch (_) { s._bad.add(ci); }
        finally { s._pending.delete(ci); }
      }));
      return true;
    };
    _hxdMarkRowDiffs(s);
    return s;
  };
  const sideA = makeSide(j.a_size, 'a', aPath);
  const sideB = makeSide(j.b_size, 'b', bPath);
  conn.sideA = sideA; conn.sideB = sideB;

  // ---- 渲染 + 双栏同步滚动（跟动方不回弹：区分用户滚动来源） ----
  const renderSide = s => _hxdRenderSide(s);
  let syncFrom = null;   // 正在驱动对端的来源侧（防滚动事件回环）
  const syncScroll = (src, dst) => {
    if (syncFrom) return;
    syncFrom = src;
    dst.scroll.scrollTop = src.scroll.scrollTop;
    requestAnimationFrame(() => { syncFrom = null; });
  };
  for (const [s, other] of [[sideA, sideB], [sideB, sideA]]) {
    s.scroll.addEventListener('scroll', () => {
      renderSide(s);
      syncScroll(s, other);
      _hxdSyncNavOnScroll();
    });
  }
  // 滚动时反向同步导航指针：视口顶行落在哪个块 → 信息栏跟随更新
  // （用户滚动浏览差异块时右上角"差异 N/758"必须跟手，之前只有按钮跳转
  // 才更新——用户报"滑了很多块右上角没变化"）
  const _hxdSyncNavOnScroll = () => {
    if (!j.blocks.length) return;
    const sA = sideA;
    // 视口顶行的 A 侧字节偏移（普通/只看差异两种坐标）
    let topRow;
    if (conn.onlyDiff) {
      const slot = Math.floor(sA.scroll.scrollTop / rowH);
      const e = sA.slots[slot];
      if (!e || e.row === undefined) return;
      topRow = e.row;
    } else {
      topRow = Math.floor(sA.scroll.scrollTop / rowH);
    }
    const off = topRow * HXD_ROW;
    // 二分找 off 落在/最近的块（blocks 按 a_start 升序）
    let lo = 0, hi = j.blocks.length - 1, best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const b = j.blocks[mid];
      if (off < b.a_start) hi = mid - 1;
      else { best = mid; lo = mid + 1; }   // a_start <= off 的最大块
    }
    if (best >= 0 && conn._navIdx !== best) {
      conn._navIdx = best;
      const b = j.blocks[best];
      conn.infoEl.textContent =
        `差异 ${best + 1}/${j.blocks.length} · A @0x${b.a_start.toString(16).toUpperCase()} · B @0x${b.b_start.toString(16).toUpperCase()}`;
    }
  };
  renderSide(sideA); renderSide(sideB);

  // ---- 信息栏 ----
  const diffRows = Math.max(sideA.diffRows.length, sideB.diffRows.length);
  conn.infoEl.textContent = `共 ${j.blocks.length} 处差异 · ${diffRows} 行涉及 · A ${j.a_size} B ↔ B ${j.b_size} B`;
  conn.infoEl.classList.toggle('diff-same', j.blocks.length === 0);
  if (!j.blocks.length) showBanner('两份二进制文件完全相同', 4000);

  // ---- 差异导航：按块序号跳（B 侧同步滚到对应块行） ----
  // 只看差异下 scrollTop 是【紧凑槽位】坐标（可见行+分裂行），需先映射
  // 回槽位；普通模式直接原始行号×rowH。
  // 只看差异下 scrollTop 是【紧凑槽位】坐标；slots 查表：找该行所在/
  // 最近数据行槽位（跳到差异行本体，不断点行上）。二分 slots（row 单调）。
  const compactSlotOf = (side, row) => {
    const sl = side.slots;
    if (!sl || !sl.length) return -1;
    let lo = 0, hi = sl.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (sl[mid].row === undefined || sl[mid].row < row) lo = mid + 1; else hi = mid; }
    return lo;
  };
  const jumpToBlock = (k) => {
    if (k < 0 || k >= j.blocks.length) return;
    conn._navIdx = k;
    const b = j.blocks[k];
    const rowA = (b.a_start / HXD_ROW) | 0, rowB = (b.b_start / HXD_ROW) | 0;
    let yA = rowA * rowH, yB = rowB * rowH;
    if (conn.onlyDiff) {
      const sA = compactSlotOf(sideA, rowA), sB = compactSlotOf(sideB, rowB);
      if (sA >= 0) yA = sA * rowH;
      if (sB >= 0) yB = sB * rowH;
    }
    // 各自滚到自己的块行（两文件偏移不同,同步滚动无意义,按块对齐）
    sideA.scroll.scrollTop = Math.max(0, yA - sideA.scroll.clientHeight / 3);
    sideB.scroll.scrollTop = Math.max(0, yB - sideB.scroll.clientHeight / 3);
    renderSide(sideA); renderSide(sideB);
    conn.infoEl.textContent =
      `差异 ${k + 1}/${j.blocks.length} · A @0x${b.a_start.toString(16).toUpperCase()} · B @0x${b.b_start.toString(16).toUpperCase()}`;
    // 滚动事件会触发的 syncScroll 已由 syncFrom 防环；这里手动渲染后同步信息
  };
  // 首屏自动落第一处差异（与 Monaco diff 的 revealFirstDiff 同思路）
  if (j.blocks.length) jumpToBlock(0);

  // ---- 工具栏 ----
  wrap.querySelectorAll('.lv-btn').forEach(btn => {
    btn.onclick = () => {
      const act = btn.dataset.hxdAction;
      if (act === 'nav-prev' || act === 'nav-next') {
        if (!j.blocks.length) return;
        let k = conn._navIdx;
        k = act === 'nav-next' ? Math.min(k + 1, j.blocks.length - 1) : Math.max(k - 1, 0);
        jumpToBlock(k);
      } else if (act === 'only-diff') {
        // 只看差异：紧凑重排（差异行 ±3 行上下文 + 地址断点分裂标识行）
        conn.onlyDiff = !conn.onlyDiff;
        btn.classList.toggle('active', conn.onlyDiff);
        for (const s of [sideA, sideB]) {
          s.renderedFrom = -1;
          s.canvas.style.height = conn.onlyDiff
            ? (s.slots.length * rowH) + 'px'
            : (s.rows * rowH) + 'px';
          renderSide(s);
        }
        // 切换后停在当前导航差异处（不重置到顶部）
        if (conn._navIdx >= 0 && j.blocks.length) jumpToBlock(Math.min(conn._navIdx, j.blocks.length - 1));
      }
    };
  });
  // F7/Shift+F7 导航（与文本 diff 一致）
  // a237 P2：存 conn 由 _edCloseNow 统一摘除（匿名挂载钉死脱离的双栏 wrap）
  conn._bdKey = e => {
    if (activePortId !== portId) return;
    if (e.key === 'F7') {
      e.preventDefault();
      const btn = wrap.querySelector(e.shiftKey ? '[data-hxd-action="nav-prev"]' : '[data-hxd-action="nav-next"]');
      if (btn) btn.click();
    }
  };
  document.addEventListener('keydown', conn._bdKey);

  notifyTaskDone(nid, {ok:true, title:'二进制对比已打开', detail:label});
  switchTab(portId);
  refreshSidebar();
  if (typeof _recentAdd === 'function') _recentAdd({
    type: 'file', key: 'bindiff:' + aPath + '|' + bPath, label,
    data: { kind: 'bindiff', a: aPath, b: bPath },
  });
  return conn;
}
