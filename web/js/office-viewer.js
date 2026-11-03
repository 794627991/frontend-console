// ============================================================
// Office 文件查看器（a280）：docx / pdf / xlsx / pptx 统一入口
// 主题跟随全局（容器绑 --bg-panel/--fg/--border CSS 变量）
// 入口：openFileSmart 按扩展名分发 → openOfficeFile(path, ext)
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
  // a280R：先查文件大小——>10MB 的 docx 渲染会卡死前端（用户实锤）
  try {
    const fi = await fetch('/api/file_info', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    const fj = await fi.json();
    if (fj.ok && fj.size > 10 * 1024 * 1024) {
      showBanner(`${name} ${(fj.size/1024/1024).toFixed(1)}MB 过大（>10MB 上限），请用资源管理器打开`, 5000, true);
      return true;
    }
  } catch (_) {}
  const portId = 'office:' + path + ':' + Date.now();

  // 去重：同文件已开则切过去
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'office' && c.officePath === path) {
      switchTab(pid); return true;
    }
  }

  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${ICO16.file}</span>` +
    `<span class="label">${esc(name)}</span><span class="baud"></span>` +
    `<span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; }
    switchTab(portId);
  };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="office-viewer">
      <div class="office-toolbar">
        <span class="office-title">${esc(name)}</span>
        <span class="office-info" data-ov-info>加载中…</span>
        <span style="flex:1"></span>
        <button class="btn ghost lv-btn" data-ov-zoomout title="缩小">－</button>
        <span data-ov-zoom style="font-family:var(--font-mono);min-width:44px;text-align:center;font-size:11px;">100%</span>
        <button class="btn ghost lv-btn" data-ov-zoomin title="放大">＋</button>
      </div>
      <div class="office-body" data-ov-body>
        <div class="office-loading">正在加载文件…</div>
      </div>
    </div>`;

  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const conn = {
    portId, meta: { kind: 'office', label: name },
    tab, wrap, officePath: path, officeKind: kind,
    dirty: false,
  };
  connections[portId] = conn;

  // 加载文件并渲染
  const body = wrap.querySelector('[data-ov-body]');
  const info = wrap.querySelector('[data-ov-info]');
  try {
    const resp = await fetch('/api/office/read?path=' + encodeURIComponent(path));
    if (!resp.ok) {
      body.innerHTML = `<div class="office-err">文件读取失败（${resp.status}）</div>`;
      return true;
    }
    const buf = await resp.arrayBuffer();
    info.textContent = (buf.byteLength / 1024).toFixed(0) + ' KB';
    await _ovRender(kind, buf, body, wrap, conn);
  } catch (e) {
    body.innerHTML = `<div class="office-err">加载失败: ${esc(String(e))}</div>`;
  }
  switchTab(portId);
  return true;
}
window.openOfficeFile = openOfficeFile;

// ---- 各类型渲染器 ----
async function _ovRender(kind, buf, body, wrap, conn) {
  if (kind === 'word') return _ovRenderDocx(buf, body, wrap, conn);
  if (kind === 'pdf') return _ovRenderPdf(buf, body, wrap, conn);
  if (kind === 'excel') return _ovRenderXlsx(buf, body, wrap, conn);
  if (kind === 'ppt') return _ovRenderPptx(buf, body, wrap, conn);
  body.innerHTML = '<div class="office-err">不支持的文件类型</div>';
}

// Word (.docx / .doc——.doc 后端自动转 .docx 再返回)
async function _ovRenderDocx(buf, body, wrap, conn) {
  if (typeof docx === 'undefined') {
    body.innerHTML = '<div class="office-err">docx-preview 库未加载（vendor/docx-preview 缺失）</div>';
    return;
  }
  body.innerHTML = '<div class="docx-container"></div>';
  const container = body.firstChild;
  try {
    // a280R：超时保护——渲染卡死时 10s 后放弃并提示（防工具冻死）
    const timeout = setTimeout(() => {
      if (container._rendering) {
        container._rendering = false;
        body.innerHTML = '<div class="office-err">Word 渲染超时（文件可能过大或格式异常），请用资源管理器打开</div>';
      }
    }, 10000);
    container._rendering = true;
    await docx.renderAsync(buf, container, null, {
      inWrapper: true, breakPages: true, renderHeaders: true, renderFooters: true,
      useBase64URL: true, ignoreLastRenderedPageBreak: false,
    });
    container._rendering = false;
    clearTimeout(timeout);
    container.classList.add('docx-themed');
  } catch (e) {
    container._rendering = false;
    clearTimeout(timeout);
    body.innerHTML = `<div class="office-err">Word 渲染失败: ${esc(String(e).slice(0, 200))}</div>`;
  }
}

// PDF
async function _ovRenderPdf(buf, body, wrap, conn) {
  if (typeof pdfjsLib === 'undefined') {
    body.innerHTML = '<div class="office-err">pdf.js 库未加载（vendor/pdfjs 缺失）</div>';
    return;
  }
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.js';
  try {
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    conn._pdfDoc = pdf;
    conn._pdfPage = 1;
    conn._pdfZoom = 1.0;
    wrap.querySelector('[data-ov-info]').textContent = pdf.numPages + ' 页';
    // 翻页/缩放按钮
    const zIn = wrap.querySelector('[data-ov-zoomin]');
    const zOut = wrap.querySelector('[data-ov-zoomout]');
    const zVal = wrap.querySelector('[data-ov-zoom]');
    if (zIn) zIn.onclick = () => { conn._pdfZoom = Math.min(3, conn._pdfZoom + 0.2); zVal.textContent = Math.round(conn._pdfZoom * 100) + '%'; _ovPdfPage(conn, body); };
    if (zOut) zOut.onclick = () => { conn._pdfZoom = Math.max(0.3, conn._pdfZoom - 0.2); zVal.textContent = Math.round(conn._pdfZoom * 100) + '%'; _ovPdfPage(conn, body); };
    // 键盘翻页
    body.tabIndex = 0;
    body.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'PageDown') { conn._pdfPage = Math.min(pdf.numPages, conn._pdfPage + 1); _ovPdfPage(conn, body); }
      else if (e.key === 'ArrowUp' || e.key === 'PageUp') { conn._pdfPage = Math.max(1, conn._pdfPage - 1); _ovPdfPage(conn, body); }
    });
    await _ovPdfPage(conn, body);
    body.focus();
  } catch (e) {
    body.innerHTML = `<div class="office-err">PDF 渲染失败: ${esc(String(e).slice(0, 200))}</div>`;
  }
}

async function _ovPdfPage(conn, body) {
  const page = await conn._pdfDoc.getPage(conn._pdfPage);
  const viewport = page.getViewport({ scale: conn._pdfZoom });
  const canvas = document.createElement('canvas');
  canvas.className = 'pdf-canvas';
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const ctx = canvas.getContext('2d');
  await page.render({ canvasContext: ctx, viewport }).promise;
  const label = document.createElement('div');
  label.className = 'pdf-page-label';
  label.textContent = `${conn._pdfPage} / ${conn._pdfDoc.numPages}`;
  body.innerHTML = '';
  body.appendChild(canvas);
  body.appendChild(label);
}

// Excel (.xlsx/.xls/.csv)
async function _ovRenderXlsx(buf, body, wrap, conn) {
  if (typeof XLSX === 'undefined') {
    body.innerHTML = '<div class="office-err">SheetJS 库未加载（vendor/xlsx 缺失）</div>';
    return;
  }
  try {
    const data = new Uint8Array(buf);
    const wb = XLSX.read(data, { type: 'array' });
    conn._wb = wb;
    conn._sheetIdx = 0;
    // Sheet 切换 tab
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
  // 提取 <table> 部分（sheet_to_html 会包完整 HTML 文档）
  const tableMatch = html.match(/<table[\s\S]*?<\/table>/i);
  conn._xlsxWrap.innerHTML = tableMatch ? tableMatch[0] : '<div class="office-err">空工作表</div>';
}

// PPT (.pptx) — 暂无成熟纯前端库，显示信息+提示
async function _ovRenderPptx(buf, body, wrap, conn) {
  body.innerHTML = `<div class="office-ppt-placeholder">
    <div style="margin-bottom:12px;">${window.ICO ? ICO16.note : ''}</div>
    <div style="font-size:14px;color:var(--fg);margin-bottom:8px;">PowerPoint 文件</div>
    <div style="font-size:11px;color:var(--muted);line-height:1.6;">
      文件大小: ${(buf.byteLength / 1024).toFixed(0)} KB<br>
      纯前端 PPT 渲染库尚不成熟，暂不支持内嵌预览。<br>
      可在资源管理器中打开查看。
    </div></div>`;
}
