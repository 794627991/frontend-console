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

async function openOfficeFile(path) {
  const kind = _officeKindOf(path);
  if (!kind) return false;
  const name = path.split(/[\\/]/).pop();
  // 大文件预检（PDF 走流式不限，其他 >10MB 拒）
  if (kind !== 'pdf') {
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

  if (kind === 'pdf') {
    // PDF Pro：专用 UI（工具栏+侧栏+虚拟化页面区）
    _ovPdfBuildUI(wrap, conn, path, name);
  } else {
    // docx/xlsx/ppt：原有简单 UI
    wrap.innerHTML = `
      <div class="office-viewer">
        <div class="office-toolbar">
          <span class="office-title">${esc(name)}</span>
          <span class="office-info" data-ov-info>加载中…</span>
          <span style="flex:1"></span>
        </div>
        <div class="office-body" data-ov-body><div class="office-loading">正在加载文件…</div></div>
      </div>`;
  }

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
    const resp = await fetch('/api/office/read?path=' + encodeURIComponent(path));
    if (!resp.ok) throw new Error('文件读取失败 ' + resp.status);
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
    const ctx = canvas.getContext('2d');
    await page.render({ canvasContext: ctx, viewport }).promise;
    el.innerHTML = '';
    el.appendChild(canvas);
    const label = document.createElement('div');
    label.className = 'ov-pdf-page-label';
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
  } catch (e) {
    container._rendering = false;
    if (_timeout) clearTimeout(_timeout);
    body.innerHTML = `<div class="office-err">Word 渲染失败: ${esc(String(e).slice(0, 200))}</div>`;
  }
}

async function _ovRenderXlsx(buf, body, wrap, conn) {
  if (typeof XLSX === 'undefined') { body.innerHTML = '<div class="office-err">SheetJS 库未加载</div>'; return; }
  try {
    const data = new Uint8Array(buf);
    const wb = XLSX.read(data, { type: 'array' });
    conn._wb = wb;
    conn._sheetIdx = 0;
    const tabs = document.createElement('div');
    tabs.className = 'xlsx-tabs';
    wb.SheetNames.forEach((name, i) => {
      const b = document.createElement('button');
      b.className = 'btn ghost' + (i === 0 ? ' active' : '');
      b.textContent = name;
      b.onclick = () => {
        conn._sheetIdx = i;
        tabs.querySelectorAll('button').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        _ovXlsxSheet(conn, body);
      };
      tabs.appendChild(b);
    });
    body.innerHTML = '';
    body.appendChild(tabs);
    const tableWrap = document.createElement('div');
    tableWrap.className = 'xlsx-table-wrap';
    body.appendChild(tableWrap);
    conn._xlsxWrap = tableWrap;
    _ovXlsxSheet(conn, body);
  } catch (e) {
    body.innerHTML = `<div class="office-err">Excel 渲染失败: ${esc(String(e).slice(0, 200))}</div>`;
  }
}

function _ovXlsxSheet(conn, body) {
  const wb = conn._wb;
  const name = wb.SheetNames[conn._sheetIdx];
  const ws = wb.Sheets[name];
  const html = XLSX.utils.sheet_to_html(ws, { editable: false });
  const tableMatch = html.match(/<table[\s\S]*?<\/table>/i);
  conn._xlsxWrap.innerHTML = tableMatch ? tableMatch[0] : '<div class="office-err">空工作表</div>';
}

async function _ovRenderPptx(buf, body, wrap, conn) {
  body.innerHTML = `<div class="office-ppt-placeholder">
    <div style="margin-bottom:12px;">${window.ICO ? ICO16.note : ''}</div>
    <div style="font-size:14px;color:var(--fg);margin-bottom:8px;">PowerPoint 文件</div>
    <div style="font-size:11px;color:var(--muted);line-height:1.6;">
      文件大小: ${(buf.byteLength / 1024).toFixed(0)} KB<br>
      纯前端 PPT 渲染库尚不成熟，暂不支持内嵌预览。
    </div></div>`;
}
