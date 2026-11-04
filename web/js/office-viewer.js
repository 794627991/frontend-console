// ============================================================
// Office 文件查看器 Pro（a283）：PDF 极致性能 + 全文搜索 + 目录
// 100MB 芯片手册场景：流式加载（range 请求）+ 虚拟化页面渲染 +
// 懒提取文本 + 渐进式搜索 + PDF 书签目录 + 页码导航 + 缩放
// docx/xlsx 沿用 a280 引擎，pdf 全面重写
// ============================================================
const _OFFICE_EXTS = {
  docx: 'word', doc: 'word',
  pdf: 'pdf',
  xlsx: 'excel', xls: 'excel', csv: 'excel',
  pptx: 'ppt', ppt: 'ppt',
};

function _officeKindOf(path) {
  const m = path.toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? _OFFICE_EXTS[m[1]] : null;
}

// a290R：Luckysheet 方案撤回（AMD loader / 全局 $ 冲突连环坑）——内置自建编辑网格 + OnlyOffice 分层

async function openOfficeFile(path) {
  const kind = _officeKindOf(path);
  if (!kind) return false;
  const name = path.split(/[\\/]/).pop();
  // 大文件预检（PDF 流式不限；PPT 后端 COM 转 PDF 不吃前端 buffer 走 200MB 上限；
  // 其他 >10MB 拒）
  if (kind !== 'pdf' && kind !== 'ppt') {
    try {
      const fi = await fetch('/api/file_info', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
      const fj = await fi.json();
      if (fj.ok && fj.size > 10 * 1024 * 1024) {
        showBanner(`${name} ${(fj.size/1024/1024).toFixed(1)}MB 过大，请用资源管理器打开`, 5000, true);
        return true;
      }
    } catch (_) {}
  }
  if (kind === 'ppt') {
    try {
      const fi = await fetch('/api/file_info', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
      const fj = await fi.json();
      if (fj.ok && fj.size > 200 * 1024 * 1024) {
        showBanner(name + ' ' + (fj.size/1024/1024).toFixed(1) + 'MB 过大', 5000, true);
        return true;
      }
    } catch (_) {}
  }
  const portId = 'office:' + path + ':' + Date.now();
  // 去重
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'office' && c.officePath === path) { switchTab(pid); return true; }
  }

  const tab = document.createElement('div');
  tab.className = 'tab'; tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${window.ICO ? ICO16.file : ''}</span>` +
    `<span class="label">${esc(name)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; }
    switchTab(portId);
  };

  const wrap = document.createElement('div');
  wrap.className = 'term-area'; wrap.dataset.portId = portId; wrap.style.display = 'none';

  const conn = { portId, meta: { kind: 'office', label: name }, tab, wrap, officePath: path, officeKind: kind, dirty: false };
  connections[portId] = conn;
  // a302：Office 文件也记入最近打开（用户实锤：word/excel/ppt 打开后最近列表
  // 不显示——_recentAdd 只在编辑器/拖拽文本路径调用，office 分发早于它们）。
  // kind:'office' 交给 openRecentItem → openDroppedFile → 再回 openOfficeFile（闭环）
  if (typeof _recentAdd === 'function') {
    _recentAdd({ type: 'file', key: 'file:' + path, label: name,
      data: { kind: 'office', name, path, extPath: path } });
  }

  if (kind === 'pdf' || kind === 'ppt') {
    // PDF Pro：专用 UI（工具栏+侧栏+虚拟化页面区）。
    // a290 全功能：PPT/pptx 也走此链——后端 PowerPoint COM 转 PDF（缓存），
    // 前端全套 PDF 引擎（虚拟化/搜索/缩放/翻页）。_pdfSrc 指向 aspdf 转换端点
    if (kind === 'ppt') {
      conn._pdfSrc = '/api/office/read?aspdf=1&path=' + encodeURIComponent(path);
      conn._pdfConvNote = '首次转换需启动 PowerPoint，请稍候…';
    }
    _ovPdfBuildUI(wrap, conn, path, name);
    const dsBtn = wrap.querySelector('[data-ov-dsedit]');
    if (dsBtn) dsBtn.onclick = () => _ovOnlyOfficeEdit(conn);
  } else {
    // docx/xlsx/ppt：原有简单 UI
    wrap.innerHTML = `
      <div class="office-viewer">
        <div class="office-toolbar">
          <span class="office-title">${esc(name)}</span>
          <span class="office-info" data-ov-info>加载中…</span>
          <span style="flex:1"></span>
          <button class="btn ghost" data-ov-outline-btn title="显示/隐藏目录大纲" style="display:none;">☰ 大纲</button>
          <button class="btn ghost" data-ov-dsedit title="OnlyOffice 全功能编辑（需本机安装，未装给安装指引）">✎ 全功能编辑</button>
        </div>
        <div class="office-body" data-ov-body><div class="office-loading">正在加载文件…</div></div>
      </div>`;
  }

  // a290：office-toolbar 的 OnlyOffice 编辑钮绑定（docx/xlsx 场景）
  const dsBtn2 = wrap.querySelector('[data-ov-dsedit]');
  if (dsBtn2) dsBtn2.onclick = () => _ovOnlyOfficeEdit(conn);
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);
  switchTab(portId);

  if (kind !== 'pdf') {
    // docx/xlsx/ppt 用 setTimeout 跳出事件上下文
    setTimeout(async () => {
      const body = wrap.querySelector('[data-ov-body]');
      const info = wrap.querySelector('[data-ov-info]');
      try {
        const resp = await fetch('/api/office/read?path=' + encodeURIComponent(path));
        if (!resp.ok) { body.innerHTML = `<div class="office-err">文件读取失败（${resp.status}）</div>`; return; }
        const buf = await resp.arrayBuffer();
        info.textContent = (buf.byteLength / 1024).toFixed(0) + ' KB';
        await _ovRenderSimple(kind, buf, body, wrap, conn);
      } catch (e) { body.innerHTML = `<div class="office-err">加载失败: ${esc(String(e))}</div>`; }
    }, 0);
  }
  return true;
}
window.openOfficeFile = openOfficeFile;

// ============================================================
// PDF Pro 渲染器（虚拟化+搜索+目录）
// ============================================================
// a290 全功能：OnlyOffice 真·全功能编辑（docx/xlsx/pptx Office 级保真编辑）。
// 探测本机 Document Server：装了=完整编辑器；没装=安装指引（现有链不受影响）
async function _ovOnlyOfficeEdit(conn) {
  const path = conn.officePath;
  try {
    showBanner('正在检测 OnlyOffice…', 2000);
    const r = await fetch('/api/office/ds/config?path=' + encodeURIComponent(path));
    const j = await r.json();
    if (!j.ok) {
      if (j.install_hint) showBanner('未安装 OnlyOffice：' + j.install_hint, 10000, true);
      else showBanner(j.err || '不可用', 5000, true);
      return;
    }
    if (j.jwt_hint) showBanner(j.jwt_hint, 10000, true);
    // 动态加载 DS api.js（once）
    if (!window._dsApiReady) {
      await new Promise((res, rej) => {
        const sc = document.createElement('script');
        sc.src = j.dsUrl + '/web-apps/apps/api/documents/api.js';
        sc.onload = res; sc.onerror = () => rej(new Error('api.js 加载失败'));
        document.head.appendChild(sc);
      });
      window._dsApiReady = true;
    }
    // 全屏编辑容器（盖在 wrap 上，自绘关闭钮回到预览）
    const host = conn.wrap;
    host.querySelectorAll('.ov-ds-editor').forEach(e => e.remove());
    const el = document.createElement('div');
    el.className = 'ov-ds-editor';
    const pid = 'ds-' + Date.now();
    el.innerHTML = `<div style="position:absolute;inset:0;"><div id="${pid}" style="width:100%;height:100%;"></div>
      <button class="btn ghost" style="position:absolute;top:6px;right:8px;z-index:10;" title="关闭编辑器（回到预览）">✕ 预览</button></div>`;
    host.appendChild(el);
    el.querySelector('button').onclick = () => { if (conn._dsEditor) { try { conn._dsEditor.destroyEditor(); } catch(_) {} conn._dsEditor = null; } el.remove(); };
    conn._dsEditor = new DocsAPI.DocEditor(pid, j.config);
    showBanner('OnlyOffice 编辑器已打开（保存=写回原文件，.bak 备份）', 4000);
  } catch (e) {
    showBanner('OnlyOffice 打开失败: ' + String(e).slice(0, 120), 6000, true);
  }
}

function _ovPdfBuildUI(wrap, conn, path, name) {
  wrap.innerHTML = `
    <div class="ov-pdf">
      <div class="ov-pdf-toolbar">
        <span class="office-title">${esc(name)}</span>
        <span class="ov-pdf-info" data-ov-info>加载中…</span>
        <span style="flex:1"></span>
        <input type="text" class="ov-pdf-search" data-ov-search placeholder="搜索…（Enter）" spellcheck="false"
          style="width:160px;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;padding:3px 8px;color:var(--fg);font-size:11px;outline:none;">
        <span class="ov-pdf-search-info" data-ov-searchinfo style="font-size:10px;color:var(--muted);min-width:60px;"></span>
        <span style="width:8px"></span>
        <button class="btn ghost lv-btn" data-ov-prev title="上一页">◀</button>
        <input type="text" data-ov-page style="width:36px;text-align:center;background:var(--bg-input);border:1px solid var(--border);border-radius:3px;color:var(--fg);font-size:11px;font-family:var(--font-mono);outline:none;" value="1">
        <span data-ov-total style="font-size:10px;color:var(--muted);font-family:var(--font-mono);">/?</span>
        <button class="btn ghost lv-btn" data-ov-next title="下一页">▶</button>
        <span style="width:8px"></span>
        <button class="btn ghost lv-btn" data-ov-zoomout title="缩小">－</button>
        <span data-ov-zoom style="font-size:10px;color:var(--muted);min-width:36px;text-align:center;font-family:var(--font-monospace;">100%</span>
        <button class="btn ghost lv-btn" data-ov-zoomin title="放大">＋</button>
        <button class="btn ghost lv-btn" data-ov-outline title="目录/书签">☰</button>
        ${conn.officeKind === 'ppt' ? '<button class="btn ghost lv-btn" data-ov-dsedit title="OnlyOffice 全功能编辑（需本机安装）">✎ 编辑</button>' : ''}
      </div>
      <div class="ov-pdf-main">
        <div class="ov-pdf-outline" data-ov-outline style="display:none;">
          <div class="ov-pdf-outline-head">目录</div>
          <div class="ov-pdf-outline-list" data-ov-outlinelist></div>
        </div>
        <div class="ov-pdf-pages" data-ov-pages tabindex="0">
          <div class="office-loading">正在加载 PDF…</div>
        </div>
      </div>
      <div class="ov-pdf-searchbar" data-ov-searchbar style="display:none;">
        <span class="ov-pdf-search-results" data-ov-results></span>
        <button class="btn ghost lv-btn" data-ov-prevhit title="上一个">↑</button>
        <button class="btn ghost lv-btn" data-ov-nexthit title="下一个">↓</button>
        <button class="btn ghost lv-btn" data-ov-closesearch title="关闭搜索">✕</button>
      </div>
    </div>`;

  _ovPdfInit(conn, path, wrap);
}

async function _ovPdfInit(conn, path, wrap) {
  if (typeof pdfjsLib === 'undefined') { wrap.querySelector('[data-ov-pages]').innerHTML = '<div class="office-err">pdf.js 未加载</div>'; return; }
  const pagesEl = wrap.querySelector('[data-ov-pages]');
  const infoEl = wrap.querySelector('[data-ov-info]');
  try {
    // a283R：先 fetch 整个文件到 ArrayBuffer 再传给 pdf.js（data 模式）——
    // url 模式下 page.render() 内部要按需拉字体/图片资源，在我们的 API
    // 端点上会挂起。data 模式全部数据已在内存，render 零网络依赖。
    // 大文件牺牲一些首屏时间换取渲染可靠性。
    // a290：PPT 走 aspdf 转换链（conn._pdfSrc），普通 PDF 直读
    if (conn._pdfConvNote) infoEl.textContent = conn._pdfConvNote;
    const resp = await fetch(conn._pdfSrc || ('/api/office/read?path=' + encodeURIComponent(path)));
    if (!resp.ok) {
      let err = '文件读取失败 ' + resp.status;
      try { const j = await resp.json(); if (j.err) err = j.err; } catch (_) {}
      throw new Error(err);
    }
    const buf = await resp.arrayBuffer();
    const task = pdfjsLib.getDocument({ data: buf });
    conn._pdfTask = task;
    const pdf = await task.promise;
    conn._pdfDoc = pdf;
    conn._pdfZoom = 1.0;
    conn._pdfCurrent = 1;
    conn._pdfTexts = new Map();    // pageNum → textContent（搜索用懒提取）
    conn._pdfRendered = new Set(); // 已渲染的页号
    conn._pdfSearchHits = [];      // [{page, str, index}]
    conn._pdfSearchIdx = -1;
    conn._pdfPageEls = [];         // 每页的 DOM 容器

    const total = pdf.numPages;
    infoEl.textContent = total + ' 页';
    wrap.querySelector('[data-ov-total]').textContent = '/' + total;
    wrap.querySelector('[data-ov-page]').value = 1;

    // 目录
    try {
      const outline = await pdf.getOutline();
      if (outline && outline.length) {
        conn._pdfOutline = outline;
        _ovPdfOutlineRender(conn, wrap);
      }
    } catch (_) { /* 无目录 */ }

    // 虚拟化页面：为每页建占位 div，IntersectionObserver 按需渲染
    pagesEl.innerHTML = '';
    for (let i = 1; i <= total; i++) {
      const div = document.createElement('div');
      div.className = 'ov-pdf-page';
      div.dataset.page = i;
      div.innerHTML = `<div class="ov-pdf-page-loading">${i}</div>`;
      pagesEl.appendChild(div);
      conn._pdfPageEls.push(div);
    }
    // 预估每页高度（用第 1 页 viewport），设占位高度防滚动跳动
    try {
      const p1 = await pdf.getPage(1);
      const vp1 = p1.getViewport({ scale: conn._pdfZoom });
      conn._pdfPageW = vp1.width;
      conn._pdfPageH = vp1.height;
      conn._pdfPageEls.forEach(el => {
        el.style.minHeight = Math.round(vp1.height * conn._pdfZoom) + 'px';
      });
    } catch (_) {}

    // IntersectionObserver：可见±1页渲染，远处卸载
    conn._pdfIO = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const pg = +entry.target.dataset.page;
          _ovPdfRenderPage(conn, pg);
        }
      });
    }, { root: pagesEl, rootMargin: '200% 0px' }); // 提前 2 屏渲染
    conn._pdfPageEls.forEach(el => conn._pdfIO.observe(el));

    // 翻页/缩放/搜索
    _ovPdfBindControls(conn, wrap);

    // 渲染第 1 页
    _ovPdfRenderPage(conn, 1);

  } catch (e) {
    pagesEl.innerHTML = `<div class="office-err">PDF 加载失败: ${esc(String(e).slice(0, 200))}</div>`;
  }
}

async function _ovPdfRenderPage(conn, pageNum) {
  if (conn._pdfRendered.has(pageNum)) return;
  conn._pdfRendered.add(pageNum);
  const el = conn._pdfPageEls[pageNum - 1];
  if (!el) return;
  try {
    const page = await conn._pdfDoc.getPage(pageNum);
    const viewport = page.getViewport({ scale: conn._pdfZoom });
    const canvas = document.createElement('canvas');
    canvas.className = 'ov-pdf-canvas';
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.maxWidth = '100%';
    // a283R2：先挂 DOM 再 render——detached canvas 的 2D context 在
    // VMware 虚拟桌面上可能挂起（用户实锤 page.render 不返回）
    el.innerHTML = '';
    el.appendChild(canvas);
    const label = document.createElement('div');
    label.className = 'ov-pdf-page-label';
    const ctx = canvas.getContext('2d');
    await page.render({ canvasContext: ctx, viewport }).promise;
    label.textContent = pageNum + ' / ' + conn._pdfDoc.numPages;
    el.appendChild(label);
    el.style.minHeight = Math.round(viewport.height) + 'px';
  } catch (e) {
    el.innerHTML = `<div class="office-err">页面 ${pageNum} 渲染失败</div>`;
    conn._pdfRendered.delete(pageNum);
  }
}

function _ovPdfBindControls(conn, wrap) {
  const pagesEl = wrap.querySelector('[data-ov-pages]');
  const pageInput = wrap.querySelector('[data-ov-page]');
  const zoomEl = wrap.querySelector('[data-ov-zoom]');

  const goTo = (pg) => {
    pg = Math.max(1, Math.min(conn._pdfDoc.numPages, pg));
    conn._pdfCurrent = pg;
    pageInput.value = pg;
    const el = conn._pdfPageEls[pg - 1];
    if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  wrap.querySelector('[data-ov-prev]').onclick = () => goTo(conn._pdfCurrent - 1);
  wrap.querySelector('[data-ov-next]').onclick = () => goTo(conn._pdfCurrent + 1);
  pageInput.onchange = () => goTo(parseInt(pageInput.value) || 1);

  // 滚动检测当前页
  pagesEl.addEventListener('scroll', () => {
    if (pagesEl.scrollTop === 0) { conn._pdfCurrent = 1; pageInput.value = 1; return; }
    // 二分找当前可见页
    const mid = pagesEl.scrollTop + pagesEl.clientHeight / 2;
    for (let i = 0; i < conn._pdfPageEls.length; i++) {
      const el = conn._pdfPageEls[i];
      const top = el.offsetTop, bot = top + el.offsetHeight;
      if (mid >= top && mid < bot) {
        conn._pdfCurrent = i + 1; pageInput.value = i + 1; return;
      }
    }
  }, { passive: true });

  // 缩放
  const setZoom = (z) => {
    conn._pdfZoom = Math.max(0.25, Math.min(4.0, z));
    zoomEl.textContent = Math.round(conn._pdfZoom * 100) + '%';
    conn._pdfRendered.clear();
    // 重新渲染所有已观察的页（IO 自动触发）
    conn._pdfPageEls.forEach(el => {
      el.style.minHeight = Math.round(conn._pdfPageH * conn._pdfZoom) + 'px';
      el.innerHTML = `<div class="ov-pdf-page-loading">${el.dataset.page}</div>`;
    });
    // 立即渲染当前页
    _ovPdfRenderPage(conn, conn._pdfCurrent);
  };
  wrap.querySelector('[data-ov-zoomin]').onclick = () => setZoom(conn._pdfZoom + 0.25);
  wrap.querySelector('[data-ov-zoomout]').onclick = () => setZoom(conn._pdfZoom - 0.25);

  // 目录
  wrap.querySelector('[data-ov-outline]').onclick = () => {
    const outline = wrap.querySelector('[data-ov-outline]');
    outline.style.display = outline.style.display === 'none' ? '' : 'none';
  };

  // 键盘
  pagesEl.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'PageDown') { e.preventDefault(); goTo(conn._pdfCurrent + 1); }
    else if (e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); goTo(conn._pdfCurrent - 1); }
    else if (e.key === '/' && !e.ctrlKey) { e.preventDefault(); wrap.querySelector('[data-ov-search]').focus(); }
  });

  // 搜索
  const searchInput = wrap.querySelector('[data-ov-search]');
  const searchInfo = wrap.querySelector('[data-ov-searchinfo]');
  const searchResults = wrap.querySelector('[data-ov-results]');
  const searchBar = wrap.querySelector('[data-ov-searchbar]');
  searchInput.onkeydown = async (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const q = searchInput.value.trim().toLowerCase();
    if (!q) { searchBar.style.display = 'none'; return; }
    searchBar.style.display = 'flex';
    searchResults.textContent = '搜索中…';
    conn._pdfSearchHits = [];
    conn._pdfSearchIdx = -1;
    // 渐进式：逐页提取文本并搜索
    for (let pg = 1; pg <= conn._pdfDoc.numPages; pg++) {
      let text = conn._pdfTexts.get(pg);
      if (!text) {
        try {
          const page = await conn._pdfDoc.getPage(pg);
          const tc = await page.getTextContent();
          text = tc.items.map(item => item.str).join(' ').toLowerCase();
          conn._pdfTexts.set(pg, text);
        } catch (_) { text = ''; }
      }
      let idx = text.indexOf(q);
      while (idx !== -1) {
        conn._pdfSearchHits.push({ page: pg, index: idx, snippet: text.substring(Math.max(0, idx - 20), idx + q.length + 30).trim() });
        idx = text.indexOf(q, idx + q.length);
      }
      searchResults.textContent = `${conn._pdfSearchHits.length} 处（${pg}/${conn._pdfDoc.numPages}页）`;
    }
    searchResults.textContent = conn._pdfSearchHits.length + ' 处匹配';
    searchInfo.textContent = conn._pdfSearchHits.length + ' hits';
    if (conn._pdfSearchHits.length) _ovPdfGoHit(conn, wrap, 0);
  };
  wrap.querySelector('[data-ov-prevhit]').onclick = () => {
    if (conn._pdfSearchHits.length) {
      _ovPdfGoHit(conn, wrap, (conn._pdfSearchIdx - 1 + conn._pdfSearchHits.length) % conn._pdfSearchHits.length);
    }
  };
  wrap.querySelector('[data-ov-nexthit]').onclick = () => {
    if (conn._pdfSearchHits.length) {
      _ovPdfGoHit(conn, wrap, (conn._pdfSearchIdx + 1) % conn._pdfSearchHits.length);
    }
  };
  wrap.querySelector('[data-ov-closesearch]').onclick = () => { searchBar.style.display = 'none'; };
}

function _ovPdfGoHit(conn, wrap, idx) {
  conn._pdfSearchIdx = idx;
  const hit = conn._pdfSearchHits[idx];
  if (!hit) return;
  wrap.querySelector('[data-ov-results]').textContent = `${idx + 1}/${conn._pdfSearchHits.length}：P${hit.page} "${hit.snippet}"`;
  const el = conn._pdfPageEls[hit.page - 1];
  if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function _ovPdfOutlineRender(conn, wrap, items, depth) {
  items = items || conn._pdfOutline;
  depth = depth || 0;
  const list = wrap.querySelector('[data-ov-outlinelist]');
  if (depth === 0) list.innerHTML = '';
  items.forEach(it => {
    const div = document.createElement('div');
    div.className = 'ov-pdf-outline-item';
    div.style.paddingLeft = (depth * 14 + 8) + 'px';
    div.textContent = it.title || '(无标题)';
    div.title = it.title || '';
    if (it.dest !== undefined) {
      div.onclick = async () => {
        try {
          let dest = it.dest;
          if (typeof dest === 'string') dest = await conn._pdfDoc.getDestination(dest);
          if (Array.isArray(dest) && dest[0] && typeof dest[0] === 'object') {
            const pg = await conn._pdfDoc.getPageIndex(dest[0]) + 1;
            const el = conn._pdfPageEls[pg - 1];
            if (el) { el.scrollIntoView({ block: 'start' }); conn._pdfCurrent = pg; wrap.querySelector('[data-ov-page]').value = pg; }
          }
        } catch (_) {}
      };
    }
    list.appendChild(div);
    if (it.items && it.items.length) _ovPdfOutlineRender(conn, wrap, it.items, depth + 1);
  });
}

// ============================================================
// docx / xlsx / ppt（a280 引擎，非 PDF 路径）
// ============================================================
async function _ovRenderSimple(kind, buf, body, wrap, conn) {
  if (kind === 'word') return _ovRenderDocx(buf, body, wrap, conn);
  if (kind === 'excel') return _ovRenderXlsx(buf, body, wrap, conn);
  if (kind === 'ppt') return _ovRenderPptx(buf, body, wrap, conn);
  body.innerHTML = '<div class="office-err">不支持的文件类型</div>';
}

async function _ovRenderDocx(buf, body, wrap, conn) {
  if (typeof docx === 'undefined') { body.innerHTML = '<div class="office-err">docx-preview 库未加载</div>'; return; }
  body.innerHTML = '<div class="docx-container"></div>';
  const container = body.firstChild;
  let _timeout = null;
  try {
    _timeout = setTimeout(() => {
      if (container._rendering) {
        container._rendering = false;
        body.innerHTML = '<div class="office-err">Word 渲染超时</div>';
      }
    }, 10000);
    container._rendering = true;
    await docx.renderAsync(buf, container, null, {
      inWrapper: true, breakPages: true, renderHeaders: true, renderFooters: true,
      useBase64URL: true, ignoreLastRenderedPageBreak: false,
    });
    container._rendering = false;
    clearTimeout(_timeout);
    container.classList.add('docx-themed');
    // a290 全功能：docx 目录索引侧栏——从渲染 DOM 提取 h1-h6（docx-preview 按
    // Word 标题样式映射 heading），点击跳转 + 滚动高亮当前节
    _ovDocxOutline(body, container, conn);
    // a316：终端同款自绘滚动条（移植 _termSbInit，原生层 none 全隐）
    if (typeof _ovSbMount === 'function') _ovSbMount(body);
  } catch (e) {
    container._rendering = false;
    if (_timeout) clearTimeout(_timeout);
    body.innerHTML = `<div class="office-err">Word 渲染失败: ${esc(String(e).slice(0, 200))}</div>`;
  }
}

// a311：字号启发式标题识别（文档无标准 Heading 样式时的兜底）。
// 算法：统计全部段落字号取中位数 → 比中位数大 ≥20% 且文字 ≤60 字的段落视为
// 标题候选；层级 = 按候选字号降序分档（最大档 lv1、次档 lv2、其余 lv3）。
// 返回带 dataset.ovHlvl 的 p 列表（_ovDocxOutline 的 lv 提取优先读它）
function _ovDocxHeadsBySize(container) {
  const ps = [...container.querySelectorAll('p')].filter(p => (p.textContent || '').trim().length >= 2);
  if (ps.length < 8) return [];   // 段落太少不猜
  // docx-preview 把 run 字号放段内 span 的内联 style（p 级 computed 恒默认
  // 13px，实测 span=29.3px）——字号取「段内最大 span 字号」，无 span 回落 p 级
  const fsOf = p => {
    let mx = 0;
    p.querySelectorAll('span[style*="font-size"]').forEach(sp => {
      const v = parseFloat(sp.style.fontSize) || 0;
      if (v > mx) mx = v;
    });
    return mx || parseFloat(getComputedStyle(p).fontSize);
  };
  const sizes = ps.map(fsOf).filter(x => x > 0).sort((a, b) => a - b);
  const mid = sizes[Math.floor(sizes.length / 2)] || 12;
  const thr = mid * 1.2;
  const cands = [];
  for (const p of ps) {
    const txt = (p.textContent || '').trim();
    const fs = fsOf(p);
    if (fs >= thr && txt.length <= 60) {
      p.dataset.ovHfs = fs;
      cands.push(p);
    }
  }
  if (cands.length < 2 || cands.length > ps.length * 0.4) return [];   // 太多=误判（满页大字）
  // 字号分档（去重字号降序 → 前 3 档 = lv1/2/3）
  const lvls = [...new Set(cands.map(p => p.dataset.ovHfs))].map(Number).sort((a, b) => b - a).slice(0, 3);
  cands.forEach(p => { p.dataset.ovHlvl = String(Math.min(3, lvls.indexOf(Number(p.dataset.ovHfs)) + 1)); });
  return cands;
}

function _ovDocxOutline(body, container, conn) {
  // docx-preview 渲染 Word 标题样式为 <p class="docx_heading1..6">（不是 h 标签）。
  // a311（用户实锤"大纲没了"）：Y 盘 H11 文档标题用的是自定义样式（渲染出
  // docx_743 数字类，无 heading 类）→ 栏消失。兜底：无 heading 类时按字号
  // 启发式识别标题（正文中位数字号 ×1.25 以上的独立短段 ≈ 标题），字号分档映射层级
  let heads = [...container.querySelectorAll('[class*="docx_heading"]')];
  if (heads.length < 2) {
    heads = _ovDocxHeadsBySize(container);
  }
  if (heads.length < 2) return;   // 真没有标题结构不建栏
  const scroller = body;   // office-body 是滚动容器
  const bar = document.createElement('div');
  bar.className = 'ov-docx-outline';
  // a300：目录栏 fixed 视口级（不随文档滚走）——top 精确对齐 body 的视口顶
  const place = () => {
    const br2 = body.getBoundingClientRect();
    bar.style.top = Math.max(0, Math.round(br2.top)) + 'px';
    bar.style.left = Math.max(0, Math.round(br2.left)) + 'px';
  };
  place();
  bar.style.bottom = '0';
  // a309R2 M4（审查实锤：侧栏拖宽后大纲栏漂移 237px 压侧栏）——ResizeObserver
  // 盯 body 布局变化重定位；挂 conn 供关 tab 时 disconnect
  try {
    const ro = new ResizeObserver(place);
    ro.observe(body);
    conn._outlineRO = ro;
  } catch (_) {}
  // a302R：目录栏改 MD 大纲同款——完全隐藏/显示（用户令："我要全隐藏，
  // 类似 md 预览大纲那种效果，新增一个按钮的事情"）。工具栏「☰ 大纲」钮切换，
  // 隐藏后文档占满全宽（margin-left 归零，非 44px 窄条）
  bar.innerHTML = '<div class="ov-docx-outline-title">目录</div>';
  const obBtn = conn.wrap.querySelector('[data-ov-outline-btn]');
  if (obBtn) {
    obBtn.style.display = '';
    obBtn.onclick = () => {
      const show = bar.style.display === 'none';
      bar.style.display = show ? '' : 'none';
      obBtn.classList.toggle('active', show);
      bar.classList.toggle('hidden', !show);
    };
  }
  const items = heads.map((h, i) => {
    const m = /docx_heading(\d)/.exec(h.className);
    const lvl = (m && m[1]) || h.dataset.ovHlvl || 3;
    const d = document.createElement('div');
    d.className = 'ov-docx-outline-item lv' + lvl;
    d.textContent = (h.textContent || '').trim().slice(0, 40) || '(无标题)';
    d.onclick = () => h.scrollIntoView({ behavior: 'smooth', block: 'start' });
    bar.appendChild(d);
    return d;
  });
  body.appendChild(bar);
  // 滚动高亮当前节（rAF 合并，同全站滚动优化惯例）
  let raf = 0;
  const onScroll = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const st = scroller.scrollTop + 80;
      let cur = 0;
      heads.forEach((h, i) => { if (h.offsetTop <= st) cur = i; });
      items.forEach((d, i) => d.classList.toggle('cur', i === cur));
    });
  };
  scroller.addEventListener('scroll', onScroll);
  onScroll();
  // 关 tab 时监听随 conn 清理（office-viewer 关闭钩子若无须手动——scroller 是 body 随 wrap 移除，监听自动失效）
}

async function _ovRenderXlsx(buf, body, wrap, conn) {
  // a290R 全功能（用户令：excel 必须可编辑）：自建可编辑网格——零运行时依赖
  // （Luckysheet 与页面 AMD loader/全局 $ 冲突连环坑，撤回）。
  // 能力：单元格编辑 / 公式（=开头，+-*/、SUM/AVG/MIN/MAX/COUNT、A1:B3 区间、裸引用）/
  // 行列插删 / 多 sheet 切换 / 撤销 / 合并单元格保真 / 保存写回 .xlsx（.bak 备份）。
  // Office 级完整编辑（图表/样式）走工具栏「✎ 全功能编辑」（OnlyOffice 分层）。
  if (typeof XLSX === 'undefined') { body.innerHTML = '<div class="office-err">SheetJS 库未加载</div>'; return; }
  try {
    const data = new Uint8Array(buf);
    // H4（a309R3）：cellNF 保留数字格式 z（日期/货币显示的落盘载体）、cellStyles
    // 保留样式 s 与 !rows/!cols——保存写回不再剥格式（配合 _ovXlsxWriteAoa 迁移）
    const wb = XLSX.read(data, { type: 'array', cellNF: true, cellStyles: true });
    conn._wb = wb; conn._sheetIdx = 0; conn._undo = [];
    // SheetJS 丢的无缓存公式从 xml 补捞（每 sheet 一张 addr→公式 表）
    conn._zipFormulas = {};
    for (const sn of wb.SheetNames) {
      Object.assign(conn._zipFormulas, await _ovXlsxFormulasFromZip(buf, sn));
    }
    body.innerHTML =
      '<div class="xlsx-edit-bar">' +
      '<button class="btn ghost" data-xa="undo" title="撤销">↶ 撤销</button>' +
      '<span style="width:6px"></span>' +
      '<button class="btn ghost" data-xa="insrow" title="在选中行上方插行">＋行</button>' +
      '<button class="btn ghost" data-xa="delrow" title="删除选中行">－行</button>' +
      '<span style="width:6px"></span>' +
      '<button class="btn ghost" data-xa="inscol" title="在选中列左侧插列">＋列</button>' +
      '<button class="btn ghost" data-xa="delcol" title="删除选中列">－列</button>' +
      '<span style="flex:1"></span>' +
      '<span style="font-size:10px;color:var(--muted)">单元格直接编辑；公式 =A1+B2 / =SUM(B1:B3)</span>' +
      '<span style="width:8px"></span>' +
      '<button class="btn ghost" data-xa="save" title="写回 .xlsx（自动 .bak 备份）">保存</button>' +
      '</div>' +
      '<div class="xlsx-tabs" data-xa-tabs></div>' +
      '<div class="xlsx-table-wrap" data-xa-table></div>';
    _ovXlsxBindBar(conn, body);
    _ovXlsxRenderTabs(conn);
    _ovXlsxRenderTable(conn);
    const _sbHost = conn.wrap.querySelector('[data-ov-body]');
    if (_sbHost && typeof _ovSbMount === 'function') _ovSbMount(_sbHost);
    // openpyxl 等工具写的公式无缓存值（<v></v> 空串）——读入后全表现算一遍，
    // 公式格立即显示计算值（而非空）。M7（审查实锤：打开即 persist 会把白名单
    // 外公式 VLOOKUP 等的缓存 v 清零落盘）——只算只显示，不写回
    _ovXlsxRecalcAll(conn);
    if (conn._aoa.some(row => row.some(c => c && c.f))) { _ovXlsxRenderTable(conn); }
  } catch (e) {
    body.innerHTML = '<div class="office-err">Excel 渲染失败: ' + esc(String(e).slice(0, 200)) + '</div>';
  }
}

// ---- 自建编辑网格 ----
async function _ovXlsxFormulasFromZip(buf, sheetName) {
  // SheetJS 社区版丢弃无缓存值的公式 cell（openpyxl 写 <v></v> 空串）。xlsx=zip，
  // 用 JSZip 解 sheet xml 捞 <c r><f> 公式兜底（逻辑经页内插桩逐行验证）
  try {
    if (typeof JSZip === 'undefined') return {};
    const zip = await JSZip.loadAsync(buf);
    const wbXml = await zip.file('xl/workbook.xml').async('string');
    const relsXml = await zip.file('xl/_rels/workbook.xml.rels').async('string');
    const nameEsc = sheetName.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    const re1 = new RegExp('<sheet\\s[^>]*name="' + nameEsc + '"[^>]*r:id="(rId\\d+)"');
    const m = re1.exec(wbXml)
      || new RegExp('<sheet\\s[^>]*r:id="(rId\\d+)"[^>]*name="' + nameEsc + '"').exec(wbXml);
    if (!m) return {};
    const m2 = new RegExp('<Relationship[^>]*Id="' + m[1] + '"[^>]*>').exec(relsXml);
    const tgt = m2 ? (/Target="([^"]+)"/.exec(m2[0]) || [])[1] : null;
    if (!m2 || !tgt) return {};
    const path = 'xl/' + tgt.replace(/^\/?xl\//, '');
    const f = zip.file(path);
    if (!f) return {};
    const shXml = await f.async('string');
    const out = {};
    const re = /<c r="([A-Z]+\d+)"[^>]*>\s*<f>([^<]+)<\/f>/g;
    let mm;
    while ((mm = re.exec(shXml))) {
      const fx = mm[2].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
      out[sheetName + '!' + mm[1]] = '=' + fx;
    }
    return out;
  } catch (_) { return {}; }
}

function _ovXlsxAoa(conn) {
  const ws = conn._wb.Sheets[conn._wb.SheetNames[conn._sheetIdx]];
  const R = XLSX.utils.decode_range(ws['!ref'] || 'A1');
  const aoa = [];
  const sn = conn._wb.SheetNames[conn._sheetIdx];
  for (let r = R.s.r; r <= R.e.r; r++) {
    const row = [];
    for (let c = R.s.c; c <= R.e.c; c++) {
      let cell = ws[XLSX.utils.encode_cell({ r, c })] || null;
      // SheetJS 丢弃的无缓存公式 cell——从 zip 补捞表合成（v 由现算填）
      if (!cell && conn._zipFormulas) {
        const f = conn._zipFormulas[sn + '!' + XLSX.utils.encode_cell({ r, c })];
        if (f) cell = { t: 'n', v: 0, f, w: f };
      }
      row.push(cell);
    }
    aoa.push(row);
  }
  return aoa;
}
function _ovXlsxWriteAoa(conn, aoa) {
  const name = conn._wb.SheetNames[conn._sheetIdx];
  const old = conn._wb.Sheets[name];
  const ws = XLSX.utils.aoa_to_sheet(aoa.map(row =>
    row.map(c => (c && c.f) ? (c.v !== undefined ? c.v : 0) : (c ? c.v : null))));   // v 优先（w 是显示文本，写了数字变 t=str）
  for (let r = 0; r < aoa.length; r++) for (let c = 0; c < (aoa[r] || []).length; c++) {
    const cell = aoa[r][c];
    if (!cell) continue;
    const addr = XLSX.utils.encode_cell({ r, c });
    const oc = old ? old[addr] : null;
    if (cell.f) {
      // H3（审查实锤：存出 <f>=SUM(...)</f> 双等号——OOXML 的 <f> 不含前导
      // =，SheetJS 原样写入即公式损坏）。写回前剥 =（内部表示保留 = 前缀）
      const f = String(cell.f).replace(/^=/, '');
      // H4（a309R3 审查实锤：保存丢数字格式/日期/超链接）：公式与缓存值都
      // 未变的格 → 整格沿用旧对象（z/s/t/l/w 全保）——aoa_to_sheet 重建只
      // 有裸值，格式信息只在旧 ws 的格对象上
      if (oc && oc.f === f && oc.v === cell.v) { ws[addr] = oc; continue; }
      const out = Object.assign({}, cell, { f });
      if (oc && oc.z && !out.z) out.z = oc.z;   // 编辑过的公式格也保数字格式
      if (oc && oc.l && !out.l) out.l = oc.l;
      ws[addr] = out;
    } else {
      // H4：非公式格值未变 → 整格沿用旧对象（z 数字格式/日期/超链接 l/
      // 文本型数字 t='s' 全保——「007」不再被写成数值 7）
      if (oc && !oc.f && oc.v === cell.v) { ws[addr] = oc; continue; }
      if (oc && oc.z && !cell.z) cell.z = oc.z;   // 编辑过的格保数字格式（改日期格的值）
      if (oc && oc.l && !cell.l) cell.l = oc.l;   // 改超链接格显示文本不丢链接
    }
  }
  if (old && old['!merges']) ws['!merges'] = old['!merges'];
  if (old && old['!cols']) ws['!cols'] = old['!cols'];
  // H4：行高迁移（旧 ws 的 !rows + 用户拖拽 _rowH 覆盖）——此前一律丢
  const rows = (old && old['!rows']) ? old['!rows'].slice() : [];
  if (conn._rowH) for (const k in conn._rowH) {
    const ri = +k; rows[ri] = Object.assign({}, rows[ri], { hpx: conn._rowH[k] });
  }
  if (rows.length) ws['!rows'] = rows;
  // a295 用户拖拽的列宽同样落盘
  if (conn._colW) {
    const cols = ws['!cols'] ? ws['!cols'].slice() : [];
    for (const k in conn._colW) {
      const ci = +k; cols[ci] = Object.assign({}, cols[ci], { wpx: conn._colW[k] });
    }
    ws['!cols'] = cols;
  }
  conn._wb.Sheets[name] = ws;
}
// 公式求值（安全子集：数字/单元格引用/区间 + +-*/() 与 SUM/AVG/AVERAGE/MIN/MAX/COUNT）
function _ovXlsxEval(formula, conn) {
  const aoa = conn._aoa;
  const cellVal = (r, c) => {
    const cell = aoa[r] && aoa[r][c];
    if (!cell) return 0;
    if (typeof cell.v === 'number') return cell.v;
    const n = parseFloat(cell.v);
    return isNaN(n) ? 0 : n;
  };
  let js = formula.replace(/^=/, '');
  js = js.replace(/(SUM|AVG|AVERAGE|MIN|MAX|COUNT)\(([A-Z]+\d+):([A-Z]+\d+)\)/gi, (m, fn, a, b) => {
    const A = XLSX.utils.decode_cell(a), B = XLSX.utils.decode_cell(b);
    const vals = [];
    for (let r = A.r; r <= B.r; r++) for (let c = A.c; c <= B.c; c++) vals.push(cellVal(r, c));
    if (!vals.length) return '0';
    const f = fn.toUpperCase();
    if (f === 'SUM') return '(' + vals.join('+') + ')';
    if (f === 'AVG' || f === 'AVERAGE') return '((' + vals.join('+') + ')/' + vals.length + ')';
    if (f === 'MIN') return 'Math.min(' + vals.join(',') + ')';
    if (f === 'MAX') return 'Math.max(' + vals.join(',') + ')';
    return String(vals.length);
  });
  js = js.replace(/\b([A-Z]+)(\d+)\b/g, (m, col, row) =>
    String(cellVal(parseInt(row, 10) - 1, XLSX.utils.decode_col(col))));
  // 安全白名单校验（仅数字/运算/Math.min max）
  if (!/^[\d+\-*/(). ,]*$/.test(js.replace(/Math\.(min|max)/g, 'X'))) return null;
  try {
    const v = Function('"use strict";return (' + js + ')')();
    return (typeof v === 'number' && isFinite(v)) ? v : null;
  } catch (_) { return null; }
}
function _ovXlsxSnapshot(conn) {
  conn._undo.push(JSON.stringify(conn._aoa));
  if (conn._undo.length > 50) conn._undo.shift();
}
function _ovXlsxRenderTabs(conn) {
  const body = conn.wrap.querySelector('[data-ov-body]');
  const tabs = body.querySelector('[data-xa-tabs]');
  tabs.innerHTML = '';
  conn._wb.SheetNames.forEach((name, i) => {
    const b = document.createElement('button');
    b.className = 'btn ghost' + (i === conn._sheetIdx ? ' active' : '');
    b.textContent = name;
    b.onclick = () => { conn._sheetIdx = i; _ovXlsxRenderTabs(conn); _ovXlsxRenderTable(conn); };
    tabs.appendChild(b);
  });
}
// a295：列宽/行高拖拽（document 级 move/up，拖完套样式+记尺寸；双击复位）
function _ovXlsxBindColGrip(conn, grip, c) {
  grip.addEventListener('mousedown', e => {
    e.preventDefault(); e.stopPropagation();
    const th = grip.parentElement;
    const holder = conn.wrap.querySelector('[data-xa-table]');
    const table = holder.querySelector('table');
    const startX = e.clientX;
    const cells = table ? [...table.querySelectorAll('tr')].map(tr => tr.children[c + 1]) : [];
    const startW = th.getBoundingClientRect().width;
    const move = ev => {
      const w = Math.max(36, Math.round(startW + ev.clientX - startX));
      th.style.width = w + 'px';
      cells.forEach(td => { if (td) { td.style.width = w + 'px'; td.style.maxWidth = w + 'px'; } });
      conn._colW[c] = w;
      grip.classList.add('on');
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      grip.classList.remove('on');
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
  grip.addEventListener('dblclick', () => {
    delete conn._colW[c];
    _ovXlsxRenderTable(conn);
  });
}
function _ovXlsxBindRowGrip(conn, grip, r) {
  grip.addEventListener('mousedown', e => {
    e.preventDefault(); e.stopPropagation();
    const tr = grip.closest('tr');
    const startX = e.clientY;
    const startH = tr.getBoundingClientRect().height;
    const move = ev => {
      const h = Math.max(20, Math.round(startH + ev.clientY - startX));
      tr.style.height = h + 'px';
      conn._rowH[r] = h;
      grip.classList.add('on');
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      grip.classList.remove('on');
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
  grip.addEventListener('dblclick', () => {
    delete conn._rowH[r];
    _ovXlsxRenderTable(conn);
  });
}

function _ovXlsxRenderTable(conn) {
  const body = conn.wrap.querySelector('[data-ov-body]');
  const holder = body.querySelector('[data-xa-table]');
  conn._aoa = _ovXlsxAoa(conn);
  const table = document.createElement('table');
  table.className = 'xlsx-edit-table';
  // a295：用户列宽/行高（拖拽手柄写入；渲染时套用）。纯 DOM 构建（innerHTML
  // 拼接会丢手柄的事件绑定）
  if (!conn._colW) conn._colW = {};
  if (!conn._rowH) conn._rowH = {};
  const hr = document.createElement('tr');
  hr.appendChild(document.createElement('th'));   // 角格
  (conn._aoa[0] || []).forEach((_, c) => {
    const th = document.createElement('th');
    th.textContent = XLSX.utils.encode_col(c);
    const w = conn._colW[c];
    if (w) th.style.width = w + 'px';
    const grip = document.createElement('div');
    grip.className = 'x-col-grip';
    grip.title = '拖动调整列宽（双击复位）';
    _ovXlsxBindColGrip(conn, grip, c);
    th.appendChild(grip);
    hr.appendChild(th);
  });
  const addColTh = document.createElement('th');
  addColTh.style.cssText = 'width:26px;cursor:pointer';
  addColTh.title = '加一列';
  addColTh.textContent = '＋';
  addColTh.onclick = () => {
    _ovXlsxSnapshot(conn);
    conn._aoa.forEach(row => row.push(null));
    _ovXlsxPersist(conn); _ovXlsxRenderTable(conn);
  };
  hr.appendChild(addColTh);
  table.appendChild(hr);
  conn._aoa.forEach((row, r) => {
    const tr = document.createElement('tr');
    const rh = document.createElement('td');
    rh.className = 'xlsx-row-head'; rh.textContent = r + 1;
    rh.style.position = 'relative';
    const hRow = conn._rowH[r];
    if (hRow) { tr.style.height = hRow + 'px'; }
    rh.onclick = () => {
      table.querySelectorAll('tr').forEach(x => x.classList.remove('selrow'));
      tr.classList.add('selrow'); conn._selRow = r;
    };
    // a295：行高拖拽手柄（行首格底缘）
    const rgrip = document.createElement('div');
    rgrip.className = 'x-row-grip';
    rgrip.title = '拖动调整行高（双击复位）';
    _ovXlsxBindRowGrip(conn, rgrip, r);
    rh.appendChild(rgrip);
    tr.appendChild(rh);
    row.forEach((cell, c) => {
      const td = document.createElement('td');
      td.contentEditable = 'true';
      td.spellcheck = false;
      const show = cell ? (cell.f ? (cell._cv !== undefined ? cell._cv : cell.v) : (cell.w !== undefined ? cell.w : cell.v)) : '';
      td.textContent = (show === undefined || show === null) ? '' : String(show);
      td.dataset.r = r; td.dataset.c = c;
      if (cell && cell.f) td.classList.add('hasf');
      td.addEventListener('focus', () => {
        // M6 + a309R3 实锤（第2轮）：_editBase 必须记「focus 后展示的文本」。
        // 公式格 focus 会把格内容换成公式本体——SheetJS 读入的 f 无 '=' 前缀，
        // 旧实现对「显示值」比对必不等 → 未编辑的 blur 把公式当用户输入写成
        // 文本格（公式损毁 + undo 污染）。展示统一补 '='（与编辑输入一致），
        // _editBase 同步取该文本——未编辑 blur 即无操作
        let base = String(show);
        if (cell && cell.f) {
          base = '=' + String(cell.f).replace(/^=/, '');
          td.textContent = base;
        }
        conn._editBase = base;
        conn._sel = { r, c };
      });
      td.addEventListener('blur', () => {
        const txt = td.textContent.trim();
        if (txt === (conn._editBase !== undefined ? conn._editBase : String(show))) {
          // 未编辑：恢复显示值（focus 时公式格被换成公式文本，无编辑不重建表格）
          td.textContent = (show === undefined || show === null) ? '' : String(show);
          return;
        }   // M6：与 focus 时展示文本比对（a309R3：含公式文本）
        _ovXlsxSnapshot(conn);
        const num = parseFloat(txt);
        if (txt === '') conn._aoa[r][c] = null;
        else if (txt.startsWith('=')) {
          const cv = _ovXlsxEval(txt, conn);
          conn._aoa[r][c] = { t: 'n', v: cv !== null ? cv : 0, f: txt, w: String(cv !== null ? cv : txt), _cv: cv !== null ? cv : '?' };
        } else if (!isNaN(num) && /^[-+\d.eE]+$/.test(txt)) conn._aoa[r][c] = { t: 'n', v: num, w: txt };
        else conn._aoa[r][c] = { t: 's', v: txt, w: txt };
        _ovXlsxRecalcAll(conn);
        _ovXlsxPersist(conn);
        // M5（审查实锤：同步重建把用户正点击的下一格 detach——每次编辑后要
        // 点两次才能进下一格）。重建延迟到 rAF：本次 click 先落在旧 DOM，
        // 重建后焦点自然恢复
        requestAnimationFrame(() => _ovXlsxRenderTable(conn));
      });
      td.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); td.blur(); }
        if (e.key === 'Tab') {
          e.preventDefault(); td.blur();
          const nx = table.querySelector('td[data-r="' + r + '"][data-c="' + (c + 1) + '"]');
          if (nx) nx.focus();
        }
      });
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  const ar = document.createElement('tr');
  ar.innerHTML = '<td colspan="' + ((conn._aoa[0] || []).length + 2) + '" style="text-align:center;cursor:pointer;color:var(--muted);padding:6px">＋ 加一行</td>';
  ar.querySelector('td').onclick = () => {
    _ovXlsxSnapshot(conn);
    conn._aoa.push((conn._aoa[0] || []).map(() => null));
    _ovXlsxPersist(conn); _ovXlsxRenderTable(conn);
  };
  table.appendChild(ar);
  holder.innerHTML = '';
  holder.appendChild(table);
}
function _ovXlsxRecalcAll(conn) {
  (conn._aoa || []).forEach(row => row.forEach(cell => {
    if (cell && cell.f) {
      const v = _ovXlsxEval(cell.f, conn);
      if (v !== null) { cell._cv = v; cell.v = v; cell.w = String(v); }
      else { cell._cv = '?'; /* M7：eval 失败保留原 v/w——不置 0（原缓存值 Excel 算的，比 0 强） */ }
    }
  }));
}
function _ovXlsxPersist(conn) { _ovXlsxWriteAoa(conn, conn._aoa); }
function _ovXlsxBindBar(conn, body) {
  body.querySelector('.xlsx-edit-bar').onclick = async e => {
    const b = e.target.closest('button[data-xa]');
    if (!b) return;
    const act = b.dataset.xa;
    const r = conn._selRow, c = conn._sel ? conn._sel.c : 0;
    if (act === 'undo') {
      const snap = conn._undo.pop();
      if (snap) { conn._aoa = JSON.parse(snap); _ovXlsxRecalcAll(conn); _ovXlsxPersist(conn); _ovXlsxRenderTable(conn); }
      return;
    }
    if (act === 'save') {
      try {
        b.disabled = true; b.textContent = '保存中…';
        // H5（审查实锤：CSV 被写回 xlsx 二进制——扩展名仍 .csv 双不开）：
        // 按原扩展选 bookType
        const isCsv = /\.csv$/i.test(conn.officePath || '');
        const out = XLSX.write(conn._wb, { bookType: isCsv ? 'csv' : 'xlsx', type: 'array' });
        const resp = await fetch('/api/office/write?path=' + encodeURIComponent(conn.officePath), { method: 'POST', body: out });
        const j = await resp.json();
        if (j.ok) {
          b.textContent = '已保存';
          showBanner('已保存 ' + conn.meta.label + '（.bak 备份在旁）', 3000);
          setTimeout(() => { b.textContent = '保存'; b.disabled = false; }, 1200);
        } else throw new Error(j.err);
      } catch (err) {
        b.disabled = false; b.textContent = '保存';
        showBanner('保存失败: ' + String(err).slice(0, 100), 5000, true);
      }
      return;
    }
    _ovXlsxSnapshot(conn);
    if (act === 'insrow') conn._aoa.splice(Math.max(r !== undefined ? r : 0, 0), 0, (conn._aoa[0] || []).map(() => null));
    if (act === 'delrow') { if (r !== undefined && conn._aoa[r]) conn._aoa.splice(r, 1); else if (conn._aoa.length) conn._aoa.pop(); }
    if (act === 'inscol') conn._aoa.forEach(row => row.splice(Math.max(c, 0), 0, null));
    if (act === 'delcol') conn._aoa.forEach(row => { if (row[c] !== undefined) row.splice(c, 1); });
    _ovXlsxRecalcAll(conn); _ovXlsxPersist(conn); _ovXlsxRenderTable(conn);
  };
}

async function _ovRenderPptx(buf, body, wrap, conn) {
  // a290：PPT 正常流程在 openOfficeFile 入口已拦截走 PDF Pro UI（COM 转 PDF），
  // 此函数仅为旧 tab 残留的防御提示
  body.innerHTML = `<div class="office-err" style="padding:24px;">请关闭此 tab 重新打开——
    PPT 现在以 PDF 引擎打开（保真渲染+搜索+缩放，首次转换需启动 PowerPoint）。</div>`;
}
