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
  // 2026-11-26（文档 6.1.1 / Step 1 的 1g）：图片也走文档预览。
  // 目的不是「看图」（编辑器已有图片预览），而是**统一缩放/适应窗口/背景**，
  // 并且为 Step 2 的「聊天流路径可点」提供一个统一的打开入口。
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image',
  webp: 'image', bmp: 'image', ico: 'image', svg: 'image',
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
  // 2026-11-26（AC-1.8）：旧的 10MB 预检取消——新引擎是流式/按需挂载的，
  // 大 docx/xlsx 能直接开。PDF 本来就不限；ppt 的 200MB 预检也一并去掉
  //（不再走 COM 转 PDF，没有那个开销了）。
  // 保留一道兜底上限只是防把浏览器拖死：500MB 以上的文件提示改用资源管理器。
  if (kind !== 'pdf') {
    try {
      const fi = await fetch('/api/file_info', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
      const fj = await fi.json();
      if (fj.ok && fj.size > 500 * 1024 * 1024) {
        showBanner(`${name} ${(fj.size/1024/1024).toFixed(0)}MB 过大，请用资源管理器打开`, 5000, true);
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

  if (kind === 'pdf') {
    // PDF Pro：专用 UI（工具栏+侧栏+虚拟化页面区）。A01：pdf 链保持现有库不动。
    _ovPdfBuildUI(wrap, conn, path, name);
    const dsBtn = wrap.querySelector('[data-ov-dsedit]');
    if (dsBtn) dsBtn.onclick = () => _ovOnlyOfficeEdit(conn);
  } else if (kind === 'ppt' || kind === 'excel') {
    // 2026-11-26 用户令（D01/D02/D04）：
    //  · ppt 不再走「本机 PowerPoint COM 转 PDF」——慢、没装 Office 就开不了、
    //    依赖会后台启动 PowerPoint。改用 @aiden0z/pptx-renderer 直接渲染。
    //  · excel 不再走自研编辑网格（用户评价「效果极差」，D02 要求代码直接删）。
    //    改用 @extend-ai/react-xlsx 的 wasm 引擎，**只读**（D01）。
    // 两者都交给 office-engine.js；OnlyOffice 编辑按钮原样保留（D03）。
    wrap.innerHTML = `
      <div class="office-viewer ov-doc-engine">
        <div class="office-toolbar">
          <span class="office-title">${esc(name)}</span>
          <span class="office-info" data-ov-info>加载中…</span>
          <span style="flex:1"></span>
          <span class="office-readonly-tag" title="文档预览为只读。需要编辑请用右侧「全功能编辑」（需本机安装 OnlyOffice）">只读</span>
          <button class="btn ghost" data-ov-dsedit title="OnlyOffice 全功能编辑（需本机安装，未装给安装指引）">✎ 全功能编辑</button>
        </div>
        <div class="office-body ov-doc-stage" data-ov-body>
          <div class="office-loading">正在加载文件…</div>
        </div>
      </div>`;
  } else if (kind === 'image') {
    // 2026-11-26（Step 1 的 1g）：图片预览。只读、无 OnlyOffice 入口
    //（图片没有「全功能编辑」这回事）。
    // 用 object-fit:contain 铺满可用区，背景用深色以便看清透明 PNG。
    wrap.innerHTML = `
      <div class="office-viewer ov-doc-engine">
        <div class="office-toolbar">
          <span class="office-title">${esc(name)}</span>
          <span class="office-info" data-ov-info>加载中…</span>
          <span style="flex:1"></span>
          <span class="office-readonly-tag">只读</span>
          <button class="btn ghost" data-ov-img-fit="contain" title="适应窗口">适应</button>
          <button class="btn ghost" data-ov-img-fit="actual" title="原始大小（超出可滚动）">1:1</button>
        </div>
        <div class="office-body ov-doc-stage" data-ov-body>
          <div class="office-loading">正在加载图片…</div>
        </div>
      </div>`;
  } else {
    // docx：原有简单 UI（A01：docx 渲染链保持 docx-preview 不动）
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
  const dsBtn2 = wrap.querySelector('[data-ov-dsedit]');
  if (dsBtn2) dsBtn2.onclick = () => _ovOnlyOfficeEdit(conn);
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);
  switchTab(portId);

  // a32x（用户实锤 pptx 打开 Uncaught TypeError: Cannot set properties of
  // null）：ppt 与 pdf 同走 _ovPdfBuildUI（上面的 78 行分支已把 wrap.innerHTML
  // 换成 PDF UI，DOM 里根本没有 [data-ov-body]）——此处只排了 'pdf'，ppt 仍
  // 进简单 UI 分支，querySelector 拿到 null 后 body.innerHTML 必炸。
  // 2026-11-26：ppt / excel 改走新引擎（见上面分支），DOM 里**有** [data-ov-body]，
  // 但渲染函数不同，所以单独一条路径。
  if (kind === 'ppt' || kind === 'excel') {
    setTimeout(async () => {
      const body = wrap.querySelector('[data-ov-body]');
      const info = wrap.querySelector('[data-ov-info]');
      try {
        const resp = await fetch('/api/office/read?path=' + encodeURIComponent(path));
        if (!resp.ok) {
          body.innerHTML = `<div class="office-err">文件读取失败（${resp.status}）</div>`;
          return;
        }
        const buf = await resp.arrayBuffer();
        info.textContent = (buf.byteLength / 1024).toFixed(0) + ' KB';
        await _ovRenderEngine(conn, kind, buf, body, info);
      } catch (e) {
        body.innerHTML = `<div class="office-err">加载失败: ${esc(String(e && e.message || e))}</div>`;
        if (info) info.textContent = '加载失败';
      }
    }, 0);
  } else if (kind === 'image') {
    // 图片：直接用 blob URL（不走 arrayBuffer→canvas，省一次拷贝，
    // 大图也能立刻显示；退订由 conn._imgUrl 在关闭 tab 时 revoke）。
    setTimeout(() => {
      const body = wrap.querySelector('[data-ov-body]');
      const info = wrap.querySelector('[data-ov-info]');
      const img = new Image();
      img.className = 'ov-image';
      img.alt = name;
      img.onload = () => {
        if (info) info.textContent = img.naturalWidth + '×' + img.naturalHeight
          + ' · ' + (body.dataset.bytes || '');
        body.innerHTML = '';
        body.appendChild(img);
        conn._imgEl = img;
      };
      img.onerror = () => {
        body.innerHTML = '<div class="office-err">图片解码失败（格式不受支持或文件损坏）</div>';
        if (info) info.textContent = '解码失败';
      };
      // 适应 / 1:1 切换
      wrap.querySelectorAll('[data-ov-img-fit]').forEach((b) => {
        b.onclick = () => {
          const mode = b.dataset.ovImgFit;
          img.classList.toggle('ov-image-actual', mode === 'actual');
          body.classList.toggle('ov-doc-stage-scroll', mode === 'actual');
        };
      });
      fetch('/api/office/read?path=' + encodeURIComponent(path))
        .then((r) => {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.blob();
        })
        .then((blob) => {
          if (info) info.textContent = (blob.size / 1024).toFixed(0) + ' KB';
          body.dataset.bytes = (blob.size / 1024).toFixed(0) + ' KB';
          conn._imgUrl = URL.createObjectURL(blob);
          img.src = conn._imgUrl;
        })
        .catch((e) => {
          body.innerHTML = `<div class="office-err">加载失败: ${esc(String(e && e.message || e))}</div>`;
          if (info) info.textContent = '加载失败';
        });
    }, 0);
  } else if (kind !== 'pdf') {
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

// 2026-11-26 用户令（D01/D02/D04）：pptx / xlsx 走 office-engine.js 的新引擎。
// 只读（D01）；渲染实例挂到 conn 上，关标签时一并释放（AC-1.12 无残留监听）。
async function _ovRenderEngine(conn, kind, buf, body, info) {
  const eng = window.OfficeEngine;
  if (!eng) {
    body.innerHTML = '<div class="office-err">渲染引擎未加载（office-engine.js）</div>';
    return;
  }
  body.innerHTML = '<div class="office-loading">正在渲染…</div>';
  const t0 = (window.performance && performance.now) ? performance.now() : Date.now();
  try {
    // 让渲染器自己管布局：容器需 position:relative + 撑满
    const host = document.createElement('div');
    host.className = 'ov-engine-host';
    body.innerHTML = '';
    body.appendChild(host);
    const h = await eng.openDocument(host, kind, buf, { onDone: () => {} });
    if (!h) { body.innerHTML = '<div class="office-err">不支持的文档类型</div>'; return; }
    conn.officeHandle = h;                 // 关闭标签时 dispose
    const ms = Math.round(((window.performance && performance.now) ? performance.now() : Date.now()) - t0);
    const extra = [];
    if (kind === 'ppt' && h.slideCount) extra.push(h.slideCount + ' 页');
    if (kind === 'xlsx' && h.sheetName) extra.push('工作表：' + h.sheetName);
    if (h.errors && h.errors.length) extra.push('失败 ' + h.errors.length + ' 页');
    if (info) info.textContent = [extra.join(' · '), ms + 'ms'].filter(Boolean).join(' · ');
    // Ctrl+滚轮缩放（2026-11-26 用户令，见 _ovDocxBindZoom 注释）
    _ovEngineBindZoom(body, kind, h);
  } catch (e) {
    body.innerHTML = `<div class="office-err">渲染失败：${esc(String(e && e.message || e))}</div>`;
    if (info) info.textContent = '渲染失败';
    if (window.console) console.error('[office-engine]', kind, e);
  }
}

// 引擎文档（pptx / xlsx）的 Ctrl+滚轮缩放。两个库各有自己的接口：
//   pptx -> viewer.setZoom(百分比)，外层已包 throttle
//   xlsx -> controller.setZoomScale(倍率)
// 走 OfficeEngine 返回的 handle，不直接碰库内部对象。
function _ovEngineBindZoom(body, kind, h) {
  if (!body || body._ovZoomBound || !h) return;
  body._ovZoomBound = true;
  let pct = 100;
  let t = 0;
  body.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    if (Date.now() - t < 80) return;      // 两个库的缩放都要重排/重绘
    t = Date.now();
    pct = Math.min(300, Math.max(50, pct + (e.deltaY < 0 ? 10 : -10)));
    try {
      if (kind === 'ppt' && typeof h.setZoom === 'function') h.setZoom(pct);
      else if (kind === 'excel') {
        const c = h.controller;
        if (c && typeof c.setZoomScale === 'function') c.setZoomScale(pct / 100);
      }
    } catch (_) {}
  }, { passive: false });
}

// ============================================================
// Ctrl+滚轮缩放（2026-11-26 用户令）
//
// 用户原话：「正常 word、pdf 等都应该有 ctrl+鼠标滚轮放大才对啊！我发现
// 无论是主菜单还是 AI 打开文件 tab 显示也不生效，是不是没对接上？」
// 确实没对接：此前主界面 docx 只有「大纲 / 全功能编辑」两个按钮，PDF 只有
// 工具条上的 ＋－，没有任何滚轮处理。
//
// **不动应用界面缩放**：Chromium 的 ctrl+wheel 默认会缩放整个页面，那是
// 全应用级的（Electron 里通常被禁掉，所以表现为「完全没反应」）。这里
// preventDefault 后只改文档自身的 transform，应用界面尺寸不变。
// ============================================================
function _ovDocxBindZoom(body, container, conn) {
  if (!body || body._ovZoomBound) return;
  body._ovZoomBound = true;
  let pct = 100;
  const apply = () => {
    // docx-preview 的 section 是固定 A4 宽（≈794px）。这里用 transform 缩放，
    // transform-origin 设 top center：宽轴居中放大，不偏左。
    container.querySelectorAll('.docx-wrapper > section').forEach(s => {
      s.style.transformOrigin = 'top center';
      s.style.transform = pct === 100 ? '' : 'scale(' + (pct / 100) + ')';
      if (pct === 100) s.style.marginBottom = '';
      else s.style.marginBottom = Math.round(16 - (s.offsetHeight || 1123) * (1 - pct / 100) / 2) + 'px';
    });
    if (conn) conn._docxZoom = pct;
    if (typeof showBanner === 'function') { /* 不打横幅，避免刷屏 */ }
  };
  let t = 0;
  body.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    if (Date.now() - t < 60) return;      // 节流：重排代价不低
    t = Date.now();
    pct = Math.min(300, Math.max(50, pct + (e.deltaY < 0 ? 10 : -10)));
    apply();
  }, { passive: false });
}


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
        <input autocomplete="off" type="text" class="ov-pdf-search" data-ov-search placeholder="搜索…（Enter）" spellcheck="false"
          style="width:160px;background:var(--bg-input);border:1px solid var(--border);border-radius:4px;padding:3px 8px;color:var(--fg);font-size:11px;outline:none;">
        <span class="ov-pdf-search-info" data-ov-searchinfo style="font-size:10px;color:var(--muted);min-width:60px;"></span>
        <span style="width:8px"></span>
        <button class="btn ghost lv-btn" data-ov-prev title="上一页">◀</button>
        <input autocomplete="off" type="text" data-ov-page style="width:36px;text-align:center;background:var(--bg-input);border:1px solid var(--border);border-radius:3px;color:var(--fg);font-size:11px;font-family:var(--font-mono);outline:none;" value="1">
        <span data-ov-total style="font-size:10px;color:var(--muted);font-family:var(--font-mono);">/?</span>
        <button class="btn ghost lv-btn" data-ov-next title="下一页">▶</button>
        <span style="width:8px"></span>
        <button class="btn ghost lv-btn" data-ov-zoomout title="缩小">－</button>
        <span data-ov-zoom style="font-size:10px;color:var(--muted);min-width:36px;text-align:center;font-family:var(--font-monospace;">100%</span>
        <button class="btn ghost lv-btn" data-ov-zoomin title="放大">＋</button>
        <button class="btn ghost lv-btn" data-ov-outline-btn title="目录/书签">☰</button>
        ${conn.officeKind === 'ppt' ? '<button class="btn ghost lv-btn" data-ov-dsedit title="OnlyOffice 全功能编辑（需本机安装）">✎ 编辑</button>' : ''}
      </div>
      <div class="ov-pdf-main">
        <div class="ov-pdf-outline" style="display:none;">
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
    // a32x（对抗审 P3）：失败时把工具栏那句「首次转换需启动 PowerPoint，
    // 请稍候…」一并改掉，否则「转换中」与「加载失败」同时挂着自相矛盾
    infoEl.textContent = '加载失败';
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
    // R6-3（实锤：缩放连按双 label）：await 期间 setZoom 可能已清 innerHTML
    // 重建并另启渲染——本任务 canvas 已 detached 即过期，跳过 label 追加
    if (!canvas.isConnected) return;
    label.textContent = pageNum + ' / ' + conn._pdfDoc.numPages;
    el.appendChild(label);
    el.style.minHeight = Math.round(viewport.height) + 'px';
  } catch (e) {
    // 过期任务的失败不应把新任务的画布打成错误占位——el 里 canvas 还在就别覆盖
    if (!el.querySelector('canvas')) {
      el.innerHTML = `<div class="office-err">页面 ${pageNum} 渲染失败</div>`;
      conn._pdfRendered.delete(pageNum);
    }
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
    // R5-3（实锤：缩放后相邻页永久占位）：IO 只在相交状态变化时回调——缩放
    // 前后都在视口±rootMargin 内的页永不重发。按 rect 主动渲染当前相交页
    const vr = pagesEl.getBoundingClientRect();
    const m = vr.height * 2;   // 与 IO rootMargin(200%) 对齐
    conn._pdfPageEls.forEach((el, i) => {
      if (i + 1 === conn._pdfCurrent) return;   // 已渲染
      const r = el.getBoundingClientRect();
      if (r.bottom > vr.top - m && r.top < vr.bottom + m) _ovPdfRenderPage(conn, i + 1);
    });
  };
  wrap.querySelector('[data-ov-zoomin]').onclick = () => setZoom(conn._pdfZoom + 0.25);
  wrap.querySelector('[data-ov-zoomout]').onclick = () => setZoom(conn._pdfZoom - 0.25);
  // Ctrl+滚轮缩放（2026-11-26 用户令：「正常 word、pdf 等都应该有 ctrl+
  // 鼠标滚轮放大才对啊！我发现无论是主菜单还是 AI 打开文件 tab 显示也不生效」）。
  // passive:false 才能 preventDefault；不动应用界面缩放，只动文档。
  // 节流 80ms：setZoom 会清空渲染集合并重画，连续滚动不打节流会排队卡死。
  let _zwT = 0;
  pagesEl.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;              // 普通滚轮保持滚动
    e.preventDefault();
    const now = Date.now();
    if (now - _zwT < 80) return;
    _zwT = now;
    setZoom(conn._pdfZoom + (e.deltaY < 0 ? 0.25 : -0.25));
  }, { passive: false });

  // 目录（a461 修复：按钮与面板原本共用 data-ov-outline——querySelector 恒
  // 命中按钮本身，点「☰」变成把按钮藏掉、面板从未打开（a283 起即坏）。
  // 按钮改用与 docx 侧一致的 data-ov-outline-btn，面板按类名切换）
  wrap.querySelector('[data-ov-outline-btn]').onclick = () => {
    const panel = wrap.querySelector('.ov-pdf-outline');
    panel.style.display = panel.style.display === 'none' ? '' : 'none';
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
          if (Array.isArray(dest) && dest[0] != null) {
            // a461：dest[0] 两种形态都接——引用对象（标准）走 getPageIndex，
            // 直接给页码数字（部分生成器的写法）就地 +1。原先数字形态静默不跳
            let pg;
            if (typeof dest[0] === 'object') pg = await conn._pdfDoc.getPageIndex(dest[0]) + 1;
            else if (typeof dest[0] === 'number') pg = dest[0] + 1;
            if (pg >= 1 && pg <= conn._pdfDoc.numPages) {
              const el = conn._pdfPageEls[pg - 1];
              if (el) { el.scrollIntoView({ block: 'start' }); conn._pdfCurrent = pg; wrap.querySelector('[data-ov-page]').value = pg; }
            }
          }
        } catch (_) {}
      };
    }
    list.appendChild(div);
    if (it.items && it.items.length) _ovPdfOutlineRender(conn, wrap, it.items, depth + 1);
  });
}

// ============================================================
// docx / xlsx（a280 引擎，非 PDF 路径）
// 2026-11-26（D01/D02/D04）：只剩 docx 还走这里。ppt / excel 已改走
// office-engine.js 的新引擎（openOfficeFile 里单独分发，不进本函数）。
// ============================================================
async function _ovRenderSimple(kind, buf, body, wrap, conn) {
  if (kind === 'word') return _ovRenderDocx(buf, body, wrap, conn);
  body.innerHTML = '<div class="office-err">不支持的文件类型</div>';
}

// a449（内网包）：blob URL 回收——useBase64URL:false 后 docx-preview 以
// URL.createObjectURL 挂图，不自动 revoke；tab 关闭与同 tab 重渲染前调用，
// 否则反复开关大图文档会累积泄漏整批 blob
function _ovRevokeBlobs(scope) {
  (scope || document).querySelectorAll('img[src^="blob:"]').forEach(img => {
    try { URL.revokeObjectURL(img.src); } catch (_) {}
    img.removeAttribute('src');
  });
}

async function _ovRenderDocx(buf, body, wrap, conn) {
  if (typeof docx === 'undefined') { body.innerHTML = '<div class="office-err">docx-preview 库未加载</div>'; return; }
  // a449（内网包）：同一 tab 重渲染前回收上一轮 blob URL（docx-preview 不
  // 自动 revoke，重开/重渲同文档会累积泄漏）；渲染期显示体量进度（原为空白，
  // 用户无法区分「在跑」和「卡死」）
  try { _ovRevokeBlobs(body); } catch (_) {}
  const _mb = buf && buf.byteLength ? buf.byteLength / 1048576 : 0;
  body.innerHTML = '<div class="docx-container"><div class="office-loading">'
    + '正在渲染' + (_mb > 1 ? '（' + _mb.toFixed(1) + ' MB）' : '') + '…</div></div>';
  const container = body.firstChild;
  let _timeout = null;
  try {
    // a449：超时 10s→60s。renderAsync 是异步的（内部 await Promise.allSettled
    // 等全部图片），定时器可正常触发；3MB/52 图的大文档渲染远超 10s——
    // 原超时会在渲染中途撕掉容器（注释曾误写「渲染是同步的」）
    _timeout = setTimeout(() => {
      if (container._rendering) {
        container._rendering = false;
        body.innerHTML = '<div class="office-err">Word 渲染超时（60s）——文档过大或图片过多，可改用 OnlyOffice 全功能编辑</div>';
      }
    }, 60000);
    container._rendering = true;
    await docx.renderAsync(buf, container, null, {
      inWrapper: true, breakPages: true, renderHeaders: true, renderFooters: true,
      // a449：关 base64 内联。52 图 2.91MB→base64 3.89MB（+33%）且解码是
      // 主线程同步计算；blob URL（createObjectURL）O(1) 挂载。代价是不自
      // 动回收——_ovRevokeBlobs 在渲染前与 tab 关闭两路回收
      useBase64URL: false, ignoreLastRenderedPageBreak: false,
    });
    container._rendering = false;
    clearTimeout(_timeout);
    container.classList.add('docx-themed');
    // a290 全功能：docx 目录索引侧栏——从文档结构提取标题（a704：
    // styles.xml 的 outlineLvl → TOC 域 → 字号启发式，见 _ovDocxOutline）。
    // 解析失败只是少一条大纲，不影响文档显示。
    try { await _ovDocxOutline(body, container, conn, buf); } catch (_) {}
    // a449 复审：进度提示按「renderAsync 会替换容器内容」假设置入容器内，
    // 但该假设未在真浏览器验证过——若库是追加式写入，提示会残留在文档
    // 顶部。渲染完成后防御性摘除（替换式则此处无节点，空操作）
    container.querySelectorAll('.office-loading').forEach(n => n.remove());
    // Ctrl+滚轮缩放（2026-11-26 用户令，见 _ovDocxBindZoom 注释）
    try { _ovDocxBindZoom(body, container, conn); } catch (_) {}
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

// a704：从 docx 的 styles.xml 提取「样式 → 大纲级别」映射。
// 这是标题结构**唯一权威**的来源——Word 导航窗格（视图→导航窗格）的判定就
// 是 <w:outlineLvl>（0 起，9 = 正文级别），与字号大小、与样式是否叫 Heading
// 都无关。实测三份文档说明单靠 DOM 特征全部漏判：
//   · ECC 文档：标题靠自定义样式（docx_1/2/3），字号与正文同为 13px
//   · iotop   ：标题同样 13px，且**没有** TOC 域（只有 styles.xml 的 outlineLvl）
//   · HTOP    ：styles.xml 里一个 outlineLvl 都没有（真·无结构，不该建大纲）
// docx-preview 把 Word 的 styleId 直接拼成类名 docx_<styleId>（ECC 的
// styleId=1/2/3 → docx_1/2/3，正好是 heading 1/2/3），所以拿到映射后用
// 类名后缀精确匹配段落即可，不必猜。
async function _ovDocxStyleLevels(buf) {
  if (!buf || typeof JSZip === 'undefined' || typeof DOMParser === 'undefined') return null;
  try {
    const zip = await JSZip.loadAsync(buf);
    const f = zip.file('word/styles.xml');
    if (!f) return null;
    const xml = await f.async('string');
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    if (doc.querySelector('parsererror')) return null;
    const map = new Map();   // styleId → '1'..'9'
    doc.querySelectorAll('style').forEach(st => {
      const id = st.getAttribute('w:styleId') || st.getAttribute('styleId');
      if (!id) return;
      const ol = st.querySelector('outlineLvl');
      if (!ol) return;
      const v = parseInt(ol.getAttribute('w:val') || ol.getAttribute('val'), 10);
      // 0~8 = 1~9 级大纲；9 在 Word 里是「正文文本」级别（TOC Heading 就用它），排除
      if (!(v >= 0 && v <= 8)) return;
      map.set(id, String(Math.min(6, v + 1)));
    });
    return map.size ? map : null;
  } catch (_) { return null; }   // 解不开就走后面的兜底，不影响文档显示
}

// a704 用户实锤（D:\doc\ECC错误处理与UBI数据完整性保障机制分析验证.docx
// 无大纲）：这份文档标题用 Word 自定义样式（渲染成 docx_1/2/3 数字类，没有
// docx_heading*），且字号与正文同为 13px —— 字号启发式（_ovDocxHeadsBySize）
// 在「标题与正文同字号、只靠样式区分」的文档上天然无解。但它的 Word 目录
// （TOC 域）是完好的：docx-preview 把 TOC 条目渲染成
//     <p class="docx_NN"><a href="#_Toc123456789">标题文字 页码</a></p>
// 层级体现在条目左缘缩进（实测 0/28/56px 精确对应三级；库用 margin-left
// 表达，但有的文档用 padding/缩进字符，所以量渲染位置而不是读 CSS）。
// 所以直接读 TOC —— 它就是 Word 自己认定的标题结构，比字号启发式准得多，
// 且大纲内容与文档里打印出来的目录完全一致。
// 返回 [{ el, lvl, text }]，el 是正文里对应书签的锚点元素（跳转目标）。
// 局限：TOC 是「生成目录那一刻」的快照，后期新增的标题不在里面，所以它排在
// styles.xml 的 outlineLvl 之后。
function _ovDocxHeadsByToc(container) {
  const rows = [];
  const seen = new Set();
  for (const a of container.querySelectorAll('a[href^="#_Toc"]')) {
    const id = (a.getAttribute('href') || '').slice(1);   // "#_Toc123" → "_Toc123"
    if (!id || seen.has(id)) continue;                    // 同一条目可能被拆成多个 a
    const target = container.querySelector('[id="' + id + '"]');
    if (!target) continue;                                // 锚点不在本文档（TOC 过期/跨文档）
    const p = a.closest('p');
    if (!p) continue;
    // 文字：去掉条目尾部的页码（Word 用制表位右对齐，DOM 里退化成「空白+数字」）
    const text = (p.textContent || '').replace(/\s+\d+\s*$/, '').trim();
    if (!text) continue;
    seen.add(id);
    rows.push({ el: target, text, left: Math.round(p.getBoundingClientRect().left) });
  }
  if (rows.length < 2) return [];
  // 层级 = 条目左缘去重升序后的档位。上限 6 级（Word 目录默认 3 级，
  // 深文档可到 4~6）。所有条目左缘相同 → 全是 lv1（至少大纲出现）。
  const lvls = [...new Set(rows.map(r => r.left))].sort((x, y) => x - y).slice(0, 6);
  return rows.map(r => ({
    el: r.el, text: r.text,
    lvl: String(Math.min(6, lvls.indexOf(r.left) + 1)),
  }));
}

// a704：按 styles.xml 的 outlineLvl 建大纲。docx-preview 把 styleId 拼成
// 类名 docx_<styleId>，所以 styleId=2 → 段落类 docx_2。用类名**精确**匹配
// （className.split(/\s+/)），不能 contains——docx_1 会命中 docx_11/21/31
// （ECC 文档里那正是 TOC 条目，会把打印出来的目录页也收进大纲）。
function _ovDocxHeadsByStyle(container, levels) {
  const out = [];
  for (const p of container.querySelectorAll('p')) {
    const cls = (p.className || '').split(/\s+/);
    let lvl = null;
    for (const c of cls) {
      // docx_<styleId>；styleId 可能含下划线/连字符，取首个 docx_ 前缀后的全部
      if (c.indexOf('docx_') !== 0) continue;
      const sid = c.slice(5);
      if (levels.has(sid)) { lvl = levels.get(sid); break; }
    }
    if (!lvl) continue;
    const text = (p.textContent || '').trim();
    if (!text) continue;              // 空段（分页/书签残留）不算标题
    out.push({ el: p, lvl, text });
  }
  return out;
}

async function _ovDocxOutline(body, container, conn, buf) {
  // a311（用户实锤"大纲没了"）：Y 盘 H11 文档标题用的是自定义样式（渲染出
  // docx_743 数字类）→ 栏消失。此后曾误以为 docx-preview 会把 Word 标题渲染成
  // <p class="docx_heading1..6">——**那是错的**，这个库从不生成 heading 类名，
  // 只输出 docx_<styleId>（见 _ovDocxStyleLevels 注释）。a704 按权威顺序重排：
  //   1) styles.xml 的 <w:outlineLvl>  → Word 导航窗格用的就是它，唯一权威
  //   2) Word 目录域（TOC）             → Word 生成目录时的快照，能跳转
  //   3) 字号启发式                     → 纯猜，标题与正文同字号时必失效
  // 三级都空了才不建栏（HTOP 那类真无结构的文档）。
  let heads = [];
  const levels = await _ovDocxStyleLevels(buf);
  if (levels) heads = _ovDocxHeadsByStyle(container, levels);
  if (heads.length < 2) heads = _ovDocxHeadsByToc(container);
  if (heads.length < 2) {
    heads = _ovDocxHeadsBySize(container).map(p => ({
      el: p, lvl: String(p.dataset.ovHlvl || 3), text: (p.textContent || '').trim(),
    })).filter(h => h.text);
  }
  if (heads.length < 2) return;   // 真没有标题结构不建栏
  // 层级归一化：某些文档最低一级标题就是「标题 3」（jbd2.docx 实测全是
  // lv3/lv4），照搬会让整条大纲缩进两级、右边空出大片。把用到的层级压缩到
  // 从 1 开始连续编号，视觉上等同「按出现的最浅标题对齐」。
  const used = [...new Set(heads.map(h => Number(h.lvl)))].sort((a, b) => a - b);
  if (used[0] !== 1) {
    const remap = new Map(used.map((v, i) => [v, String(Math.min(6, i + 1))]));
    heads.forEach(h => { h.lvl = remap.get(Number(h.lvl)) || h.lvl; });
  }
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
  const items = heads.map((h) => {
    const d = document.createElement('div');
    d.className = 'ov-docx-outline-item lv' + h.lvl;
    d.textContent = h.text.slice(0, 40) || '(无标题)';
    d.onclick = () => h.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    bar.appendChild(d);
    return d;
  });
  body.appendChild(bar);
  // 滚动高亮当前节（rAF 合并，同全站滚动优化惯例）
  // a704：改用视口坐标判定。原来读 h.offsetTop —— docx-preview 的
  // offsetParent 是各个 <section class="docx">，每页重新计数（实测同一文档
  // 里后一个标题的 offsetTop 比前一个还小），而 scroller.scrollTop 是整篇
  // 文档的累计滚动量，两者不同坐标系 → 高亮永远错位（点 3.1.1 会高亮到
  // 第 8 章）。getBoundingClientRect 与 offsetParent 无关，一并对齐。
  let raf = 0;
  const onScroll = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const st = scroller.getBoundingClientRect().top + 80;
      let cur = 0;
      heads.forEach((h, i) => { if (h.el.getBoundingClientRect().top <= st) cur = i; });
      items.forEach((d, i) => d.classList.toggle('cur', i === cur));
    });
  };
  scroller.addEventListener('scroll', onScroll);
  onScroll();
  // 关 tab 时监听随 conn 清理（office-viewer 关闭钩子若无须手动——scroller 是 body 随 wrap 移除，监听自动失效）
}

// 2026-11-26 用户令（D02）：xlsx 自研可编辑网格整段删除（用户评价「效果极差」）。
// 换代：pptx / xlsx 一律走 office-engine.js 的只读渲染引擎（D01）；
// 唯一的编辑途径是 OnlyOffice（D03 要求其接口原样保留，见 _ovOnlyOfficeEdit）。
// 一并消失的还有 /api/office/write 的前端调用点（原 _ovXlsxWriteAoa 内的那句）。

// 模块化一期（js-modularization 分支）：转 ES module——裸顶层声明转为模块
// 作用域，跨文件消费名补挂 window（消费者均 typeof 守卫运行时：editor.js
// :1501/:2351；openOfficeFile 的既有挂载 :133 不变）。
window._officeKindOf = _officeKindOf;
window._ovRevokeBlobs = _ovRevokeBlobs;
