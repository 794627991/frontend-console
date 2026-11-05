// ============================================================
// 块笔记编辑器（Editor.js）：files/ 目录下 .note（块笔记）与 .txt（纯文本）
// v0.6.21：新建文件默认 .note——块式编辑（类 OneNote/Notion），可粘贴图片、
// 插表格/清单/代码块/引用，标题/分隔线，行内标记（粗体用内联 tool）。
// .note 数据 = Editor.js JSON（{time, blocks:[...]}），图片经 /api/ed/upload_img
// 存 files/images/，渲染走 /api/ed/img/ 静态路由。
// 引擎 vendor 化（同 xterm 模式，离线可用）：vendor/editorjs*.umd.js
// 设计参考（Notepad++）：tab * 脏标记、双击标题改名、关闭确认。
// 后端：src/editor_files.py（/api/ed/*），文件存 <工具目录>/files/
//
// 保存模型：新建只建草稿 tab（「未命名」），首次保存/双击改名才落盘。
// ============================================================

// Editor.js 工具集（.note 用）。行内：Marker 高亮 + InlineCode 代码。
// Image 走 upload_img 上传。/ 键唤出块菜单。
// toolbox.title 汉化（Editor.js 默认文案是英文：Heading/List/…）。
function _edTools() {
  return {
    header: { class: Header, toolbox: { title: '标题' },
      config: { placeholder: '输入标题…', levels: [1,2,3], defaultLevel: 2,
        levelConfig: {'1':'大标题','2':'中标题','3':'小标题'} } },
    list: { class: EditorjsList, toolbox: { title: '列表' },
      config: { placeholder: '列表项…' } },
    checklist: { class: Checklist, toolbox: { title: '清单' },
      config: { placeholder: '待办事项…' } },
    table: { class: Table, toolbox: { title: '表格' } },
    image: { class: ImageTool, toolbox: { title: '图片' }, config: {
      uploader: { uploadByFile: _edUploadImage, uploadByUrl: null },
      captionPlaceholder: '图片说明（可空）',
    }},
    quote: { class: Quote, toolbox: { title: '引用' },
      config: { captionPlaceholder: '', quotePlaceholder: '引用内容…' } },
    code: { class: CodeTool, toolbox: { title: '代码块' } },
    delimiter: { class: Delimiter, toolbox: { title: '分隔线' } },
    paragraph: { text: { inlineToolbar: ['marker', 'inlineCode', 'bold'] } },
  };
}
async function _edUploadImage(file) {
  // Editor.js uploader 协议：返回 {success:1, file:{url}} 或 {success:0}
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/ed/upload_img', {method: 'POST', body: fd});
    const j = await r.json();
    if (!j.ok) return { success: 0 };
    return { success: 1, file: { url: '/api/ed/img/' + j.url.split('/')[1] } };
  } catch(e) { return { success: 0 }; }
}

// ---- 编辑器 tab 构建（模式同 buildLogViewer：tab + term-area wrap + connections 表）----
// name=null 表示未命名草稿（尚未保存到磁盘）
function buildEditorTab(name, content, extPath, fileMtime, draftExt) {
  // content：.note 传 Editor.js JSON 对象；.txt 传字符串；草稿传 null
  // extPath：外部绝对路径（拖入文件）——保存写回原路径，不走 files/ 目录
  // fileMtime：打开时磁盘 mtime（后台改动检测基准；null=草稿/旧调用不检测）
  // draftExt：草稿默认后缀（v2.27「新建文件」下拉；'.note'/'.txt'/'.md'/自定义，
  //           默认 '.note'）——决定块编辑/纯文本形态与首次落盘的默认后缀
  const isNote = name ? name.toLowerCase().endsWith('.note')
                      : ((draftExt || '.note').toLowerCase() === '.note');
  // 外部 .note 入口（拖入/最近打开）传的是 /api/ed/open 返回的 JSON 字符串：
  // 不解析则 _edInitContent 判非对象 → 空块初始化 → Ctrl+S 把原文件覆盖成空笔记
  let _noteCorrupted = false;
  if (isNote && typeof content === 'string' && content.trim()) {
    try { content = JSON.parse(content); } catch (_) {
      content = null;
      _noteCorrupted = true;   // a238 P2-4：损坏的 .note（截断/手改坏）不能静默空开——条件反射 Ctrl+S 会把可救内容覆盖成空笔记
    }
    if (content && (typeof content !== 'object' || Array.isArray(content))) {
      content = null; _noteCorrupted = true;   // JSON 合法但非笔记对象（数组/数字）同样按损坏处理
    }
  }
  // 已打开同名文件 → 切过去
  // a238 P1-5（第5轮A2）：外部文件去重必须「全路径相等」——原先只比 label
  // （=basename），E:\proj2\a.c 会被 D:\bsp\a.c 的旧 tab 劫持：用户以为打开了
  // 新文件，编辑后 Ctrl+S 内容写进第一个文件（写错文件，无任何视觉征兆）
  if (name) {
    for (const pid in connections) {
      const c = connections[pid];
      if (c && c.meta && c.meta.kind === 'editor' && c.meta.label === name) {
        if (extPath || c.extPath) {
          if (String(c.extPath || '') === String(extPath || '')) { switchTab(pid); return c; }
          continue;   // 同名不同路径：不劫持，新开 tab
        }
        switchTab(pid); return c;   // a209批1：去重分支也返回 conn（openFileSmart 行号跳转需要拿到实例）
      }
    }
  }
  const portId = 'edit:' + (name || 'draft') + ':' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${fileIconHtml(name || '.note', 14)}</span><span class="label">${esc(name || '未命名')}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  if (extPath) tab.title = extPath;   // a209批4：悬浮显完整路径
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };
  // 双击 tab 标题 → 快捷改名（外部文件禁用——保持原路径）
  tab.querySelector('.label').ondblclick = (e) => {
    e.stopPropagation();
    const c = connections[portId];
    if (c && c.extPath) { showBanner('外部文件不支持重命名（保持原路径）', 3000, true); return; }
    edRenamePrompt(c);
  };
  // wrap（.term-area 内含编辑器）
  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-ed-action="save" title="Ctrl+S"><span>${ICO16.save}</span> 保存</button>
        <button class="lv-btn" data-ed-action="saveas" title="Ctrl+Shift+S">另存为…</button>
        <button class="lv-btn" data-ed-action="rename" title="双击标签页标题可快捷改名">重命名</button>
        <button class="lv-btn" data-ed-action="search" title="Ctrl+F 全局搜索（支持正则/排除）">${ICO16.search} 搜索</button>
        <button class="lv-btn" data-ed-action="outline" title="显示/隐藏右侧大纲面板">${ICO16.note} 大纲</button>
        <button class="lv-btn" data-ed-action="links" title="显示/隐藏双链面板（链入/链出/标签）">${ICO16.link} 链接</button>
        <button class="lv-btn" data-ed-action="exportmd" title="导出为 Markdown（同目录同名 .md，图片相对路径）">${ICO16.download} .md</button>
        <select name="ed_enc" class="lv-btn ed-enc-sel" data-ed-enc title="文件编码（切换后按所选编码重新读取；保存按当前编码回写）" style="display:none;">
          <option value="">编码：自动</option>
          <option value="utf-8">UTF-8</option>
          <option value="gb2312">GB2312</option>
          <option value="gbk">GBK</option>
          <option value="gb18030">GB18030</option>
          <option value="big5">Big5</option>
          <option value="latin-1">Latin-1</option>
        </select>
        <select name="ed_mdtheme" class="lv-btn ed-mdtheme-sel" data-ed-mdtheme title="MD 预览配色（即时生效）" style="display:none;">
        </select>
        <span class="lv-info" data-ed-info></span>
        <span class="ed-path" data-ed-path title=""></span>
      </div>
      <div class="ed-main">
        <div class="ed-outline" style="display:none;">
          <div class="ed-outline-head">大纲<span class="ed-outline-actions" style="display:none;"><span class="ed-outline-act" data-act="collapseAll" title="全部折叠">⤠</span><span class="ed-outline-act" data-act="expandAll" title="全部展开">⤡</span></span></div>
          <div class="ed-outline-list"></div>
          <div class="ed-outline-stats"></div>
        </div>
        <div class="ed-links" style="display:none;">
          <div class="ed-links-head"><span>${ICO16.link}</span> 链接</div>
          <div class="ed-links-list"></div>
        </div>
        <div class="ed-scroll">
          <div class="ed-holder"></div>
        </div>
        <div class="ed-md-splitter" style="display:none"></div>
        <div class="ed-md-preview" style="display:none;"><div class="md-preview-body"></div></div>
      </div>
      <div class="term-search-splitter ed-search-splitter" style="display:none" title="拖动调节查找分栏高度"></div>
      <div class="term-search-pane ed-search-pane" style="display:none">
        <div class="term-search-head">
          <input type="text" name="ed_search_q" class="term-search-input ed-search-q" placeholder="查找…（回车搜索，正则支持）" autocomplete="off">
          <input type="text" name="ed_search_ex" class="term-search-exclude ed-search-ex" placeholder="排除（多个用 | 分隔，支持正则）" autocomplete="off">
          <span class="term-search-count ed-search-count"></span>
          <button class="btn ghost term-search-collapse ed-search-collapse" title="折叠分栏">▾</button>
        </div>
        <div class="term-search-results ed-search-results"></div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);   // 拖拽排序（tab-drag.js）
  termArea.appendChild(wrap);
  const conn = {
    portId,
    meta: { kind: 'editor', label: name || '未命名' },
    tab, wrap,
    holder: wrap.querySelector('.ed-holder'),
    infoEl: wrap.querySelector('[data-ed-info]'),
    pathEl: wrap.querySelector('[data-ed-path]'),
    outline: wrap.querySelector('.ed-outline'),
    outlineList: wrap.querySelector('.ed-outline-list'),
    outlineStats: wrap.querySelector('.ed-outline-stats'),
    isNote,
    draftExt: name ? '' : (draftExt || '.note'),  // 草稿默认后缀（落盘定名时补）
    editor: null,         // Editor.js 实例（.note）
    monaco: null,         // Monaco 实例（txt/md/code，_edInitContent 建）
    ta: null,             // textarea（Monaco 失败降级 fallback）
    savedData: null,      // 上次保存/打开的内容（脏检测基准）
    onDisk: !!name,
    dirty: false,
    extPath: extPath || null,  // 外部绝对路径：保存写回原文件，另存为/重命名禁用
    usedEnc: null,             // 打开文件实际用的编码（编码下拉切换时重读）
    fileMtime: fileMtime || null,   // 磁盘 mtime 基准（后台改动检测，_edWatchDisk 用）
    diskWatchTimer: null,      // 检测定时器（tab 可见才开，切走停——流畅守则）
    diskWatchAsked: null,      // 已弹窗提醒的 mtime（同一次外部改动不重复弹）
    // 全局搜索分栏（纯文本；.note 也支持——按块文本搜）
    edSearchPane: null, edSearchQ: null, edSearchEx: null,
    edSearchResults: null, edSearchCount: null,
    edSearchState: { results: [], idx: 0 },
  };
  // .md 分栏预览：预览列显示 + 工具栏加「预览」开关
  const _isMd = name ? name.toLowerCase().endsWith('.md') : false;
  if (_isMd) {
    wrap.querySelector('.ed-md-preview').style.display = '';
    // 分隔条必须显式设 'block'——inline 起始是 display:none，设 '' 会回落到
    // inline 的 none（不走 CSS），永远不可见（上一轮拖不动的根因）
    wrap.querySelector('.ed-md-splitter').style.display = 'block';
    // a303：预览按钮改三态下拉（用户令：只显示原文 / 只显示预览 / 同步显示）
    const pvSel = document.createElement('select');
    pvSel.className = 'lv-btn';
    pvSel.dataset.edAction = 'mdmode';
    pvSel.title = '编辑/预览布局模式';
    pvSel.innerHTML =
      '<option value="both">☐ 同步显示</option>' +
      '<option value="src">☐ 只显示原文</option>' +
      '<option value="pv">☐ 只显示预览</option>';
    wrap.querySelector('[data-ed-action="search"]').after(pvSel);
    conn._mdMode = 'both';
    pvSel.onchange = () => _mdApplyMode(conn, pvSel.value);
    _mdBindSplitter(wrap);
  }
  connections[portId] = conn;
  // 编码下拉（仅外部文件——站内 files/ 永远 UTF-8）：切换 = 脏检查后
  // 按所选编码重读原文件灌入 Monaco。自动探测报 GB18030 时下拉预选 GBK
  //（gb18030 是 gbk 超集，用户视角"这就是 GBK 文件"）。
  if (conn.extPath && !isNote) {
    const encSel = wrap.querySelector('[data-ed-enc]');
    if (encSel) {
      encSel.style.display = '';
      const _ue = window._edLastUsedEnc || '';
      encSel.title = '当前编码：' + (_ue || '自动探测') + '（切换后按所选编码重新读取原文件；保存按当前编码回写）';
      if (_ue === 'gb18030' || _ue === 'gbk') encSel.value = 'gbk';
      encSel.onchange = async () => {
        // （编码切换逻辑续，见下方）
        if (conn.dirty) {
          const ok = await _edConfirm('切换编码会放弃未保存的修改，继续？');
          if (!ok) { encSel.value = encSel.dataset.cur || ''; return; }
        }
        const enc = encSel.value;
        try {
          const q = '/api/ed/open?force=1&path=' + encodeURIComponent(conn.extPath) +
                    (enc ? '&enc=' + encodeURIComponent(enc) : '');
          const r = await fetch(q);
          const j = await r.json();
          // a246 P3（a238复审）：重读失败回拨下拉——文件仍是旧编码，下拉
          // 却停在新选择上=状态失同步
          if (!j.ok) {
            encSel.value = encSel.dataset.cur || '';
            showBanner('重读失败：' + (j.err || ''), 4000, true); return;
          }
          conn.usedEnc = j.used_enc;
          window._edLastUsedEnc = j.used_enc;
          conn.dirty = false;
    if (typeof treeDecoRefresh === 'function') treeDecoRefresh();
          if (conn.monaco) {
            const pos = conn.monaco.getPosition();
            conn.monaco.setValue(j.text);
            try { conn.monaco.setPosition(pos); conn.monaco.revealLineInCenter(pos.lineNumber); } catch (_) {}
          } else if (conn.ta) conn.ta.value = j.text;
          _edSetBase(conn, j.text);   // a238：EOL 基线归一 + _eol 探测
          conn.hasBom = !!j.has_bom;  // a238 P1-3：切编码后 BOM 状态跟随重读结果
          conn.fileMtime = j.mtime || conn.fileMtime;   // 重读了磁盘：基准同步，防误报
          encSel.dataset.cur = enc;
          showBanner('已按 ' + (j.used_enc || '自动探测') + ' 重新读取', 2500);
        } catch(e) { showBanner('重读失败: ' + e, 4000, true); }
      };
    }
  }
  // a281：MD 预览配色下拉——.md 文件才显示，选项从 _MD_PV_THEMES 填充
  if ((name || '').toLowerCase().endsWith('.md')) {
    const mdSel = wrap.querySelector('[data-ed-mdtheme]');
    if (mdSel) {
      mdSel.style.display = '';
      mdSel.innerHTML = _MD_PV_THEMES.map(t =>
        `<option value="${t.id}"${(_mdPvTheme || 'auto') === t.id ? ' selected' : ''}>${t.name}</option>`
      ).join('');
      mdSel.onchange = () => {
        _mdPvSetTheme(mdSel.value);
        showBanner('MD 预览配色：' + (_MD_PV_THEMES.find(t => t.id === mdSel.value) || {}).name, 1800);
      };
    }
  }
  // 初始化编辑区（异步：Editor.js 实例化）
  // v3.5.297：.note 正文 Ctrl+点击 [[双链]] 跳转（notes-nav.js，捕获期委托）
  if (typeof nnBindWikiClick === 'function') { try { nnBindWikiClick(conn); } catch (_) {} }
  _edInitContent(conn, content);
  // a238 P2-4：损坏的 .note 以空笔记打开后强制置脏（关闭/切换时必弹确认）+
  // 显式警示——否则条件反射 Ctrl+S 会原子覆盖掉磁盘上可救的半截 JSON
  if (_noteCorrupted) {
    conn.dirty = true;
    showBanner('⚠ ' + (name || extPath || '笔记') + ' 内容已损坏（非合法笔记 JSON），以空白打开——直接保存会覆盖原文件，建议先「另存为」抢救内容', 9000, true);
    _edMarkTab(conn);
  }
  // 搜索分栏事件：回车搜索（Shift+回车跳下一个）、排除框回车、折叠按钮
  const qEl = wrap.querySelector('.ed-search-q');
  qEl.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (e.shiftKey) { const st = conn.edSearchState; if (st.results.length) { st.idx = (st.idx + 1) % st.results.length; edJumpToHit(conn, st.idx); } }
    else doEdSearch(conn);
  });
  wrap.querySelector('.ed-search-ex').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); doEdSearch(conn); } });
  wrap.querySelector('.ed-search-collapse').onclick = () => edToggleSearchPane(conn);
  initEdSplitter(conn);   // 查找分栏：拖分隔条调高度
  // 工具栏按钮
  wrap.querySelectorAll('.lv-btn').forEach(btn => {
    btn.onclick = () => {
      const act = btn.dataset.edAction;
      if (act === 'save') edSave(conn);
      else if (act === 'search') edToggleSearchPane(conn);
      else if (act === 'mdpreview') {
        const pv = conn.wrap.querySelector('.ed-md-preview');
        const sp = conn.wrap.querySelector('.ed-md-splitter');
        const show = pv.style.display === 'none';
        pv.style.display = show ? '' : 'none';
        // 分隔条跟预览列同显隐（显式 block/none——设 '' 会回落 inline 的 none）
        if (sp) sp.style.display = show ? 'block' : 'none';
        if (show) _mdRenderPreview(conn);
      }
      else if (act === 'saveas') { if (conn.extPath) showBanner('外部文件不支持另存为（直接保存到原路径）', 3000, true); else edSaveAs(conn); }
      else if (act === 'rename') { if (conn.extPath) showBanner('外部文件不支持重命名（保持原路径）', 3000, true); else edRenamePrompt(conn); }
      else if (act === 'delete') { if (conn.extPath) showBanner('外部文件不提供删除（请到文件管理器操作）', 3000, true); else edDelete(conn); }   // 按钮已移除，防御保留
      else if (act === 'outline') edToggleOutline(conn);
      else if (act === 'links') { if (typeof nnToggleLinks === 'function') nnToggleLinks(conn); }   // v3.5.297 双链反链面板
      else if (act === 'exportmd') { if (typeof nnExportMd === 'function') nnExportMd(conn); }   // v3.5.299 导出 .md
    };
  });
  // 快捷键 Ctrl+S / Ctrl+Shift+S：挂 document 全局生效——
  // 之前挂 wrap 上，焦点必须落在编辑区（block 内）keydown 才冒泡到 wrap，
  // 点了工具栏/大纲后按 Ctrl+S 失灵。全局监听只在「当前活动 tab 是本编辑器」时处理。
  // a237 P0：handler 必须存 conn——匿名闭包会把整个 conn 图（savedData 全文/
  // undo 快照栈/脱离的 wrap）钉到 document 上，关闭 tab 后无从移除，开关
  // 大文件 ×N 次即数百 MB 永久驻留（_edCloseNow 统一摘除）
  conn._docKey = e => {
    if (activePortId !== portId) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (e.shiftKey) { if (conn.extPath) showBanner('外部文件不支持另存为（直接保存到原路径）', 3000, true); else edSaveAs(conn); }
      else edSave(conn);
      return;
    }
    // 文档内搜索（v3.5.310 可配置，默认 Ctrl+F；loose 保持原宽松）：编辑器全局搜索分栏
    if (typeof hkMatch === 'function'
        ? hkMatch(e, window._HK && window._HK.docSearch, true)
        : ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f')) {
      e.preventDefault();
      edToggleSearchPane(conn, true);
      return;
    }
    // 「/」开块菜单、Ctrl+/ 开块设置：Editor.js 只在编辑区持有焦点时响应
    // （slashPressed 检查 e.target 在 UI wrapper 内），点击工具栏/大纲后失焦失灵。
    // 全局兜底：焦点不在 block 内时，先聚焦最后块再转发给 Editor.js 工具条。
    if (!conn.isNote || !conn.editor) return;
    // 焦点在别处输入框（改名框/右侧搜索框等）时按 / 是正常输入，不拦截
    const ae = document.activeElement;
    if (ae && ae !== document.body && !conn.holder.contains(ae) &&
        (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)) return;
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (!conn.holder.contains(document.activeElement) || !document.activeElement.isContentEditable) {
        e.preventDefault();
        try { conn.editor.caret.setToLastBlock('end'); } catch(_) {}
      }
      return;  // 焦点在 block 内时 Editor.js 自己处理（空块插 "/" 开菜单）
    }
    if (e.code === 'Slash' && (e.ctrlKey || e.metaKey)) {
      if (!conn.holder.contains(document.activeElement) || !document.activeElement.isContentEditable) {
        e.preventDefault();
        try { conn.editor.caret.setToLastBlock('end'); } catch(_) {}
        setTimeout(() => { try { conn.editor.toolbar.toggleBlockSettings(true); } catch(_) {} }, 0);
      }
      return;
    }
  };
  document.addEventListener('keydown', conn._docKey);
  switchTab(portId);
  refreshSidebar();
  if (typeof treeDecoRefresh === 'function') treeDecoRefresh();   // a213 P2：打开即着色
  return conn;
}

// ---- 编辑区初始化：.note 建 Editor.js；.txt 建 textarea ----
async function _edInitContent(conn, content) {
  if (conn.isNote) {
    try {
      const data = (content && typeof content === 'object' && content.blocks) ? content : { blocks: [] };
      conn.editor = new EditorJS({
        holder: conn.holder,
        tools: _edTools(),
        data,
        placeholder: '输入内容，按 / 插入块（标题/图片/表格/清单…），可直接粘贴截图',
        minHeight: 60,
        // 核心与插件 UI 文案汉化（Editor.js 默认英文）。
        // 注意：词典必须包在 i18n.messages 里——Editor.js 只读 config.i18n.messages
        // 喂给 setDictionary，直接放 i18n 下整份词典不生效（曾因此全英文）。
        i18n: {
          messages: {
            toolNames: { Text: '文本', Heading: '标题', List: '列表', Checklist: '清单',
              Table: '表格', Image: '图片', Quote: '引用', Code: '代码块', Delimiter: '分隔线',
              Link: '链接', Bold: '粗体', Italic: '斜体', Marker: '高亮',
              'Unordered List': '无序列表', 'Ordered List': '有序列表' },
            tools: {
              table: { 'With headings': '带表头', 'Without headings': '无表头',
                'Add row above': '上方插入行', 'Add row below': '下方插入行',
                'Add column to left': '左侧插入列', 'Add column to right': '右侧插入列',
                'Delete row': '删除行', 'Delete column': '删除列' },
              // 引用块设置菜单：插件用 api.i18n.t('Align Left') 查 tools.quote 命名空间
              quote: { 'Align Left': '左对齐', 'Align Center': '居中对齐' },
              // 列表设置菜单（含有序列表的 Start with / Counter type 子菜单）
              list: { 'Unordered': '无序列表', 'Ordered': '有序列表', 'Checklist': '清单',
                'Start with': '起始编号', 'Counter type': '编号样式',
                'Numeric': '数字', 'Lower Roman': '小写罗马数字', 'Upper Roman': '大写罗马数字',
                'Lower Alpha': '小写字母', 'Upper Alpha': '大写字母' },
              image: { 'Select an Image': '选择图片', 'Caption': '说明',
                'Stretch image': '拉伸图片', 'With background': '带背景',
                'With border': '带边框', 'With caption': '显示说明',
                "Couldn't upload image. Please try another.": '上传失败，请换一张试试',
                'Couldn’t upload image. Please try another.': '上传失败，请换一张试试' },
              // 行内工具条「转换」弹出层的块类型名走各工具命名空间
              paragraph: { 'To paragraph': '转段落' },
              header: { 'To heading': '转标题' },
              link: { 'Add a link': '添加链接' },
              stub: { 'The block can not be displayed correctly.': '该块无法正确显示' },
            },
            blockTunes: {
              'delete': { Delete: '删除' },
              'moveUp': { 'Move up': '上移' },
              'moveDown': { 'Move down': '下移' },
            },
            inlineToolbar: {
              converter: { 'To paragraph': '转段落', 'To heading': '转标题', 'Convert to': '转换为' },
            },
            ui: {
              // 块左侧工具条 hover 提示（默认 "Click to tune"/"or drag to move"/"Click to delete"）
              blockTunes: {
                toggler: { 'Click to tune': '点击调整（Ctrl+/）', 'or drag to move': '或拖动移动' },
                'delete': { 'Click to delete': '点击删除' },
              },
              toolbar: { toolbox: { 'Add': '添加块（/ 或 Ctrl+/）' } },
              popover: { 'Filter': '筛选', 'Nothing found': '未找到', 'Convert to': '转换为' },
            },
          },
        },
        onChange: () => { _edMarkDirty(conn); if (conn._edUndoHook) conn._edUndoHook(); if (typeof nnHlSchedule === 'function') nnHlSchedule(conn); },
        onReady: () => {
          // ---- Quote 对齐补丁（只打一次）----
          // vendor 版 quote 插件 bug：_toggleTune 只写 data.alignment，render() 从不
          // 应用 text-align，也不触发块重渲染——点"Align Center"只改数据，外观不动。
          // 补丁：_toggleTune 里直接对块根元素设 text-align；render 后按已存数据恢复
          // （刷新/重开文件时对齐样式不丢）。
          if (!Quote._alignPatched) {
            Quote._alignPatched = true;
            const origRender = Quote.prototype.render;
            const origToggle = Quote.prototype._toggleTune;
            Quote.prototype.render = function() {
              const el = origRender.call(this);
              if (this.data.alignment) el.style.textAlign = this.data.alignment;
              return el;
            };
            Quote.prototype._toggleTune = function(v) {
              origToggle.call(this, v);
              try {
                const holder = this.api.blocks.getById(this.block.id)?.holder;
                if (holder) holder.style.textAlign = v === 'center' ? 'center' : '';
              } catch(_) {}
            };
          }
          _edUpdateInfo(conn);
          // v3.5.302：.note 撤销/重做（Editor.js 核心不含 undo，官方
          // editorjs-undo 插件未 vendor 化=Ctrl+Z 从来无效——自研轻量快照栈）
          if (typeof _edUndoInit === 'function') { try { _edUndoInit(conn); } catch (_) {} }
          // v3.5.308（全审F3）：初始渲染不产生 onChange——打开笔记时补一次
          // 染色调度，否则「阅读态染色」主场景缺席（须先编辑才染色）
          if (typeof nnHlSchedule === 'function') { try { nnHlSchedule(conn); } catch (_) {} }
        },
      });
      conn.savedData = data;
      _edBindLightbox(conn);   // 图片双击放大灯箱
    } catch(e) {
      // Editor.js 加载失败（vendor 缺失等）→ 降级 textarea 纯文本，保可用
      showBanner('块编辑器加载失败，已降级纯文本：' + e, 6000, true);
      conn.isNote = false;
    }
  }
  if (!conn.isNote) {
    const isMd = (conn.meta.label || '').toLowerCase().endsWith('.md');
    if (typeof monacoCreate === 'function' && !isMd) {
      // Monaco（VSCode 同款内核）：语法高亮/内置查找替换/行号/minimap
      // 失败自动降级 textarea（vendor 缺失/异常时保可用）
      try {
        conn.monaco = await monacoCreate(conn.holder, typeof content === 'string' ? content : '', conn.meta.label, conn.extPath || null);
        try { conn._m = conn.monaco.getModel(); } catch(_) {}
        conn.monaco.onDidChangeModelContent(() => { _edMarkDirty(conn); conn._edSrcVer = (conn._edSrcVer || 0) + 1; });
        conn.monaco.onDidChangeCursorPosition(() => _edUpdateInfo(conn));
      } catch(e) {
        showBanner('Monaco 加载失败，已降级纯文本：' + e, 6000, true);
        conn.monaco = null;
      }
    } else if (typeof monacoCreate === 'function' && isMd) {
      // .md：Monaco 源码编辑 + markdown-it 实时预览分栏
      try {
        // 分栏容器：预览列插到 ed-scroll 之后（HTML 已在 buildEditorTab 预置 ed-md-preview）
        conn.monaco = await monacoCreate(conn.holder, typeof content === 'string' ? content : '', conn.meta.label, conn.extPath || null);
        try { conn._m = conn.monaco.getModel(); } catch(_) {}
        conn.monaco.onDidChangeModelContent(() => { _edMarkDirty(conn); conn._edSrcVer = (conn._edSrcVer || 0) + 1; _mdRenderPreview(conn); });
        conn.monaco.onDidChangeCursorPosition(() => _edUpdateInfo(conn));
        conn.monaco.onDidScrollChange(() => {   // 源码滚动 → 预览跟着滚
          // v2.25：这次源码滚动若是「预览→源码」同步自己写的，别再回灌预览——
          // 回灌按标题锚点定位，会把用户在两锚之间的自由位置拽回锚点顶
          // （用户实测：预览里往下翻一些就被拽回来。预览端才是主阅口）
          if (conn._mdPvDriven && Date.now() - conn._mdPvDriven < 150) return;
          if (_mdRaf) return;                    // 每帧最多一次，连续滚动不挤压主线程
          _mdRaf = requestAnimationFrame(() => { _mdRaf = 0; _mdSyncScroll(conn); });
        });
        _mdRenderPreview(conn);
      } catch(e) {
        showBanner('Monaco 加载失败，已降级纯文本：' + e, 6000, true);
        conn.monaco = null;
      }
    }
    if (!conn.monaco) {
      conn.ta = document.createElement('textarea');
      conn.ta.className = 'editor-area';
      conn.ta.spellcheck = false;
      conn.ta.value = typeof content === 'string' ? content : '';
      conn.holder.appendChild(conn.ta);
      conn.ta.addEventListener('input', () => { _edMarkDirty(conn); conn._edSrcVer = (conn._edSrcVer || 0) + 1; _mdRenderPreview(conn); });
      conn.ta.addEventListener('scroll', () => {
        if (!isMd || _mdRaf) return;
        if (conn._mdPvDriven && Date.now() - conn._mdPvDriven < 150) return;   // v2.25：预览驱动的滚动勿回灌
        _mdRaf = requestAnimationFrame(() => { _mdRaf = 0; _mdSyncScroll(conn); });
      }, { passive: true });
      conn.ta.addEventListener('keyup', () => _edUpdateInfo(conn));
      conn.ta.addEventListener('click', () => _edUpdateInfo(conn));
      if (isMd) _mdRenderPreview(conn);
    }
    _edSetBase(conn, typeof content === 'string' ? content
      : (conn.monaco ? conn.monaco.getValue() : conn.ta.value));   // a238：EOL 基线（草稿 null→空串）
  }
  _edUpdateInfo(conn);
}

// ---- 取当前内容（保存用）：.note 返回 JSON 对象，纯文本返回字符串 ----
async function _edGetContent(conn) {
  if (conn.isNote && conn.editor) {
    try { return await conn.editor.save(); } catch(e) { return null; }
  }
  if (conn.monaco) return conn.monaco.getValue();
  return conn.ta ? conn.ta.value : '';
}

// ---- 脏检测：当前内容 vs 上次保存 ----
// a238 P1-2（第5轮A2）：EOL 基线管理——后端读侧已 newline='' 保留 \r\n；
// Monaco 的 model EOL 跟随内容、getValue 按 model EOL 返回，textarea 的
// value 被浏览器归一为 \n（HTML 规范）。统一策略：基线（savedData）与比对
// 都归一为 \n，保存发送前按打开时探测的 _eol 重展开——CRLF 文件保存后
// 不再被整文件改写成 LF（git diff 爆红/.reg 解析失败的主因）
function _edNormEol(s) { return String(s).replace(/\r\n/g, '\n'); }
function _edSetBase(conn, content) {
  if (!conn.isNote && typeof content === 'string') {
    if (content.indexOf('\r\n') >= 0) conn._eol = 'crlf';
    else if (!conn._eol) conn._eol = 'lf';
    conn.savedData = _edNormEol(content);
  } else {
    conn.savedData = content;   // .note 对象 / 空内容
  }
}
function _edOutText(conn, content) {
  if (conn.isNote || conn._eol !== 'crlf' || typeof content !== 'string') return content;
  return content.replace(/\r\n/g, '\n').replace(/\n/g, '\r\n');
}
function _edMarkDirty(conn) {
  if (!conn.isNote) {
    // 纯文本精确比对字符串（Monaco/textarea 同源；比对统一归一化 EOL）
    const cur = conn.monaco ? conn.monaco.getValue() : (conn.ta ? conn.ta.value : '');
    const dirty = _edNormEol(cur) !== conn.savedData;
    if (dirty !== conn.dirty) {
      conn.dirty = dirty; _edMarkTab(conn);
      if (typeof treeDecoRefresh === 'function') treeDecoRefresh();   // a231 去重（原相邻双调）   // a213 审计 P2：.note 分支联动
    }
    _edUpdateInfo(conn);
    return;
  }
  // v3.5.309（复审N1）：.note 脏判定改内容比对——染色包 span 等视觉层 DOM
  // 变更同样触发 onChange，但 save() 经 sanitizer 提纯后数据不变，不能置脏
  // （旧实现恒 true：打开含双链/标签的笔记 ~1.2s 后假「未保存」，保存后点击
  // 染色块又变脏=保存链路语义被打断）。blocks-only JSON 比对（键序由同一
  // 引擎生成稳定；undo 的 snap 已证明此成本可接受）+ 300ms 去抖合并；save
  // 失败保守置脏。残余：外部工具手写的老 .note 键序可能不同→首开显示脏，
  // 保存一次即自愈（键序归一为引擎输出）。
  clearTimeout(conn._dirtyT);
  conn._dirtyT = setTimeout(async () => {
    try {
      const data = await conn.editor.save();
      const cur = JSON.stringify((data && data.blocks) || []);
      const base = (conn.savedData && conn.savedData.blocks)
        ? JSON.stringify(conn.savedData.blocks) : '[]';
      const dirty = cur !== base;
      if (dirty !== conn.dirty) { conn.dirty = dirty; _edMarkTab(conn); }
      _edUpdateInfo(conn);
    } catch (_) {
      if (!conn.dirty) { conn.dirty = true; _edMarkTab(conn);
        if (typeof treeDecoRefresh === 'function') treeDecoRefresh(); }   // a213 P2
      _edUpdateInfo(conn);
    }
  }, 300);
}

// ---- 脏标记：tab 标题加 *（Notepad++ 风格）+ tab/左栏列表同步未保存类 ----
function _edMarkTab(conn) {
  // 原地改名中：标题 span 已换成输入框，改名结束后统一刷新
  if (conn._renaming) return;
  conn.tab.querySelector('.label').textContent = (conn.dirty ? '*' : '') + conn.meta.label;
  // tab 未保存视觉态（橙色小点由 CSS 渲染，比纯 * 更显眼）
  conn.tab.classList.toggle('dirty', !!conn.dirty);
  // 同步左侧列表：名字带 * + 未保存类（led 变橙），不等 30s 轮询
  const item = portList.querySelector(`.port-item[data-port-id="${CSS.escape(conn.portId)}"]`);
  if (item) {
    item.classList.toggle('dirty', !!conn.dirty);
    const name = item.querySelector('.name');
    if (name) name.textContent = (conn.dirty ? '*' : '') + conn.meta.label;
  }
}

// ---- 图片双击放大灯箱：点击/Esc 关闭，滚轮缩放 ----
// 事件委托挂在 conn.holder 上（块增删不丢监听）；灯箱单例挂 body。
function _edBindLightbox(conn) {
  conn.holder.addEventListener('dblclick', e => {
    const img = e.target.closest('.image-tool__image-picture');
    if (!img) return;
    e.preventDefault();
    _edShowLightbox(img.src);
  });
}
function _edShowLightbox(src) {
  let lb = $('edLightbox');
  if (!lb) {
    lb = document.createElement('div');
    lb.className = 'ed-lightbox';
    lb.id = 'edLightbox';
    lb.innerHTML = '<img alt="">';
    lb.onclick = () => _edHideLightbox();
    document.body.appendChild(lb);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') _edHideLightbox();
    });
  }
  lb.querySelector('img').src = src;
  lb.style.display = 'flex';
}
function _edHideLightbox() {
  const lb = $('edLightbox');
  if (lb) lb.style.display = 'none';
}
// ---- 状态栏：块数/字符数 + 保存态 ----
function _edUpdateInfo(conn) {
  conn.infoEl.textContent = _edStatText(conn) + _edStateText(conn);
  // a222（用户批注「希望显示文件的路径」）：工具栏右侧常显完整路径——
  // 站内 files/ 显示相对名；外部文件显绝对路径。hover title 同值
  if (conn.pathEl) {
    const p = conn.extPath || '';
    conn.pathEl.textContent = p;
    conn.pathEl.title = p;
    // a229 自检 E1：站内文件无路径——空 span 仍吃 margin-left:auto 会抢
    // lv-info 的右贴位（统计信息错位左移）。无路径即隐（display 收放）
    conn.pathEl.style.display = p ? '' : 'none';
  }
  _edRenderOutline(conn);   // 大纲面板开着时同步刷新（内容/块变化即更新）
}

// ---- 右侧大纲面板：标题层级导航 + 块类型统计 ----
function edToggleOutline(conn) {
  const shown = conn.outline.style.display !== 'none';
  conn.outline.style.display = shown ? 'none' : 'flex';
  if (!shown) _edRenderOutline(conn);
}
// ---- 代码文件大纲：按语言语法结构解析（class/def/函数名层级导航）----
// Monaco basic-languages 只是着色器、没有 symbol provider（那是 LSP 的事），
// 所以轻量正则解析常见语言的定义行。# 井号规则只用于 md/txt——
// 代码文件的 # 是注释，曾被整当 md 标题列出 56 条注释（大纲异常）。
const _CODE_OUTLINE = {
  // Python：class / def，缩进映射层级（1 级=顶格，2 级=一层缩进内）
  py: [
    { re: /^(class)\s+([A-Za-z_]\w*)/, lv: 1, kind: '类' },
    { re: /^(\s*)def\s+([A-Za-z_]\w*)/, lv: 2, kind: '函数', indent: true },
  ],
  // a220：Shell（.sh/.bash 强需求）——tree-sitter bash 失败时的正则兜底。
  // 此前 .sh 不在表内：ts 偶发失败（wasm 加载竞态/异常）即回落井号规则，
  // #!/bin/sh 与 # 注释全变「标题」条目——函数全丢（用户实锤「解析异常」）
  sh: [
    // 三种形式：foo() 独行（{ 下行）/ foo() { 同行 / function bar { 无括号
    // （无括号时必须行尾 { ——否则单词命令 true/exit 误报）
    { re: /^\s*(?:function\s+)?([A-Za-z_][\w.-]*)\s*\(\s*\)\s*\{?\s*$/, lv: 1, kind: '函数' },
    { re: /^\s*(?:function\s+)?([A-Za-z_][\w.-]*)\s*\{\s*$/, lv: 1, kind: '函数' },
    { re: /^\s*([A-Za-z_][\w.-]*(?:\s*\|\s*[A-Za-z_*][\w.-]*)*)\)\s*$/, lv: 2, kind: '分支' },
  ],
  // C/C++/Java/JS/TS/C#/Go/Rust… 大括号语言：类型/函数定义行（简化启发式）
  c: [
    { re: /^(?:typedef\s+)?struct\s+([A-Za-z_]\w*)/, lv: 1, kind: '结构体' },
    { re: /^class\s+([A-Za-z_]\w*)/, lv: 1, kind: '类' },
    { re: /^(?:[A-Za-z_][\w:<>,\s*&]*?\s[*&]?\s*)([A-Za-z_]\w*)\s*\([^;]*$/, lv: 2, kind: '函数' },
  ],
};
const _CODE_OUTLINE_EXT = {
  // 后缀 → 解析器（py 一族走 py；花括号语言走 c 启发式；其余 null=井号规则）
  '.py': 'py', '.pyw': 'py', '.pyi': 'py',
  '.c': 'c', '.h': 'c', '.cpp': 'c', '.hpp': 'c', '.cc': 'c', '.cxx': 'c', '.hh': 'c', '.hxx': 'c',
  '.java': 'c', '.cs': 'c', '.go': 'c', '.rs': 'c', '.swift': 'c', '.scala': 'c', '.kotlin': 'c',
  '.js': 'c', '.ts': 'c', '.php': 'c', '.m': 'c', '.mm': 'c',
  '.sh': 'sh', '.bash': 'sh',
};
function _outlineCodeEntries(src, ext) {
  const parserKey = _CODE_OUTLINE_EXT[(ext || '').toLowerCase()];
  const rules = parserKey ? _CODE_OUTLINE[parserKey] : null;
  if (!rules) return null;
  const lines = src.split('\n');
  const entries = [];
  let inBlock = false;   // Python """docstring""" 内不解析
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i];
    if (parserKey === 'py') {
      const dq = (t.match(/"""/g) || []).length;
      if (inBlock) { if (dq) inBlock = false; continue; }
      if (dq % 2 === 1) { inBlock = true; continue; }
    } else {
      // 花括号语言：块注释/字符串行粗跳（单行 // 注释靠行首规则天然不命中）
      const trimmed = t.trim();
      if (trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;
    }
    for (const r of rules) {
      const m = r.re.exec(t);
      if (m) {
        // c 组规则只有 1 个捕获组（py 组有 2 个）：统一取最后一个捕获组，
        // 否则 c 组取名 m[2]=undefined → 大纲全显「函数 undefined」
        entries.push({ level: r.lv, text: (r.kind ? r.kind + ' ' : '') + m[m.length - 1], line: i + 1 });
        break;
      }
    }
  }
  return entries;
}

function _edRenderOutline(conn) {
  if (!conn.outline || conn.outline.style.display === 'none') return;
  // Monaco/textarea 纯文本：代码文件（c/sh/py/json 系）优先 tree-sitter 真语法树解析，
  // 失败回落正则启发式；md/txt 用 # 井号规则（代码的 # 是注释，不能当标题）
  if (conn.monaco || conn.ta) {
    const src = conn.monaco ? conn.monaco.getValue() : conn.ta.value;
    // 内容版本短路：光标移动/保存也触发本函数，但内容未变时跳过重解析
    // （大 json 全量 tree-sitter parse 昂贵；折叠状态已存 conn._edFold 不怕丢）。
    // _edSrcVer 由 onDidChangeModelContent/textarea input 递增
    const ver = conn._edSrcVer || 0;
    if (conn._edOutlineVer === ver && conn.outlineList.children.length) return;
    conn._edOutlineVer = ver;
    const label = (conn.meta.label || '').toLowerCase();
    const dotI = label.lastIndexOf('.');
    const ext = dotI > 0 ? label.slice(dotI) : '';
    const isMd = ext === '.md';
    // 异步渲染代际守卫：tsOutline 异步返回前若又触发了重渲染（光标移动/保存），
    // 旧 promise 的结果要丢弃——否则旧结果晚到覆盖新渲染（竞态闪烁）
    const gen = (conn._edOutlineGen = (conn._edOutlineGen || 0) + 1);
    const renderEntries = entries => {
      if (gen !== conn._edOutlineGen) return false;   // 已被更新的渲染取代
      if (!entries || !entries.length) return false;
      // json 大纲：条目带 kids 字段（tsOutline 递归键标记），按嵌套关系可折叠
      const foldable = entries.some(e => e.kids !== undefined);
      const _actions = conn.outline.querySelector('.ed-outline-actions');
      if (_actions && !foldable) _actions.style.display = 'none';   // 代码/md 大纲无折叠按钮
      // 折叠状态存 conn（跨渲染保留）：光标移动/保存等会反复触发 _edRenderOutline，
      // _folded 挂在条目对象上会被重渲染清掉 → 全部折叠后点单项跳转就整树弹开（曾现 bug）
      if (!conn._edFold) conn._edFold = {};
      entries.forEach(e => { if (e.kids !== undefined) e._folded = conn._edFold[e.text + '@' + e.line]; });
      conn.outlineList.innerHTML = entries.map((e, i) => {
        const arrow = foldable && e.kids
          ? `<span class="ed-outline-fold" data-i="${i}">${e._folded ? '▸' : '▾'}</span>` : (foldable ? '<span class="ed-outline-fold" style="visibility:hidden">▾</span>' : '');
        return `<div class="ed-outline-item${foldable ? ' ed-outline-foldable' : ''}" data-i="${i}" style="padding-left:${(e.level-1)*12+8}px">${arrow}${esc(foldable ? (e.text || '') : (e.kind ? e.kind + ' ' : '') + e.text)}</div>`;
      }).join('');
      // 折叠状态：隐藏所有 depth > 折叠键 depth 的后续条目，直到遇到 depth <= 该值的键
      const applyFold = () => {
        const items = conn.outlineList.querySelectorAll('.ed-outline-item');
        const hidden = new Set();
        for (let i = 0; i < entries.length; i++) {
          const e = entries[i];
          items[i].classList.toggle('ed-outline-hidden', hidden.has(i));
          if (e.kids && e._folded) {
            for (let j = i + 1; j < entries.length && entries[j].depth > e.depth; j++) hidden.add(j);
          }
        }
      };
      if (foldable) {
        conn.outlineList.querySelectorAll('.ed-outline-fold:not([style])').forEach(f => {
          f.onclick = ev => {
            ev.stopPropagation();
            const e = entries[+f.dataset.i];
            if (!e) return;
            e._folded = !e._folded;
            conn._edFold[e.text + '@' + e.line] = e._folded;   // 状态写回 conn，重渲染后还原
            f.textContent = e._folded ? '▸' : '▾';
            applyFold();
          };
        });
        applyFold();
        // 标题栏「全部折叠/展开」按钮：只对 json 树大纲显示（代码大纲无折叠）
        const actions = conn.outline.querySelector('.ed-outline-actions');
        if (actions) {
          actions.style.display = 'inline-flex';
          actions.querySelectorAll('.ed-outline-act').forEach(btn => {
            btn.onclick = () => {
              const collapse = btn.dataset.act === 'collapseAll';
              entries.forEach(e => {
                if (e.kids) {
                  e._folded = collapse;
                  conn._edFold[e.text + '@' + e.line] = collapse;
                }
              });
              conn.outlineList.querySelectorAll('.ed-outline-fold:not([style])').forEach(f => { f.textContent = collapse ? '▸' : '▾'; });
              applyFold();
            };
          });
        }
      }
      conn.outlineList.querySelectorAll('.ed-outline-item').forEach(item => {
        item.onclick = () => {
          const e = entries[+item.dataset.i];
          if (!e) return;
          if (conn.monaco) { conn.monaco.revealLineInCenter(e.line); conn.monaco.setPosition({ lineNumber: e.line, column: 1 }); }
        };
      });
      const kinds = {};
      entries.forEach(e => { kinds[e.kind || '定义'] = (kinds[e.kind || '定义'] || 0) + 1; });
      conn.outlineStats.innerHTML = Object.entries(kinds)
        .map(([k, v]) => `<span class="ed-outline-stat">${esc(k)} ${v}</span>`).join('');
      return true;
    };
    const finishCode = () => {
      if (!renderEntries(_outlineCodeEntries(src, ext))) {
        conn.outlineList.innerHTML = '<div class="ed-outline-empty">未解析到类/函数定义<br>（大纲按语法结构生成：class/def/函数签名）</div>';
        conn.outlineStats.innerHTML = '';
      }
    };
    // tree-sitter 支持 4 类语言（c/sh/py/json 系）：异步解析，结果回来再渲染
    if (typeof tsOutline === 'function' && typeof TS_LANG_EXT_HAS === 'function' && TS_LANG_EXT_HAS(ext)) {
      tsOutline(src, ext).then(entries => {
        if (entries && entries.err) {
          // 语法树失败：面板显示原因（不再无声回落——上次 Language 导出写错就无声了）
          conn.outlineList.innerHTML = `<div class="ed-outline-empty">语法树解析失败<br>${esc(entries.err)}</div>`;
          conn.outlineStats.innerHTML = '';
          return;
        }
        if (entries && entries.length) renderEntries(entries);
        else finishCode();
      }).catch(e => {
        conn.outlineList.innerHTML = `<div class="ed-outline-empty">语法树解析失败<br>${esc(String(e))}</div>`;
        conn.outlineStats.innerHTML = '';
      });
      return;
    }
    if (_CODE_OUTLINE_EXT[ext]) { finishCode(); return; }
    // md/txt：a282 大纲重写——markdown-it 令牌化替代正则手写
    // （旧法三大缺陷：代码块内 # 误判/setext 标题不识别/层级嵌套不可折叠。
    // markdown-it 的 token 有 type+tag+map+level，天然正确处理以上全部）
    const mdOutline = (() => {
      const md = _mdInstance();
      if (!md) return null;
      const tokens = md.parse(src, {});
      const entries = [];
      for (let i = 0; i < tokens.length; i++) {
        const tk = tokens[i];
        if (tk.type !== 'heading_open') continue;
        // 下一个 token 是 inline，其 children[0].content = 标题文本
        const inline = tokens[i + 1];
        const text = inline && inline.children
          ? inline.children.map(c => c.content || '').join('').trim()
          : (inline ? inline.content || '' : '');
        // map = [起始行, 结束行]（0-based）——+1 变 1-based 行号
        const line = (tk.map && tk.map[0] != null) ? tk.map[0] + 1 : 0;
        // tag = h1~h6 → level
        const level = parseInt((tk.tag || 'h1').slice(1)) || 1;
        entries.push({ level, text: text || '(无标题)', line, kids: undefined });
      }
      return entries;
    })();
    if (mdOutline && mdOutline.length) {
      // a282R2：直接渲染（不走 renderEntries 闭包——其生成守卫/折叠逻辑
      // 与 md 条目形状不完全兼容导致空渲染 IAB 实锤两次）
      conn.outlineList.innerHTML = mdOutline.map((e, i) =>
        `<div class="ed-outline-item" data-i="${i}" style="padding-left:${(e.level-1)*12+8}px">${esc(e.text || '(无标题)')}</div>`
      ).join('');
      conn.outlineList.querySelectorAll('.ed-outline-item').forEach(item => {
        item.onclick = () => {
          const e = mdOutline[+item.dataset.i];
          if (!e || !conn.monaco) return;
          conn.monaco.revealLineInCenter(e.line);
          conn.monaco.setPosition({ lineNumber: e.line, column: 1 });
        };
      });
      const hCount = {};
      mdOutline.forEach(e => { hCount['H' + e.level] = (hCount['H' + e.level] || 0) + 1; });
      conn.outlineStats.innerHTML = Object.entries(hCount)
        .map(([k, v]) => `<span class="ed-outline-stat">${k} ${v}</span>`).join('');
    } else {
      conn.outlineList.innerHTML = '<div class="ed-outline-empty">暂无标题行<br>用 # 井号标题组织内容后在此生成目录</div>';
      conn.outlineStats.innerHTML = '';
    }
    return;
  }
  if (!conn.isNote) return;
  const blocks = conn.holder.querySelectorAll('.ce-block');
  // 大纲：只列标题块（h1/h2/h3 按层级缩进），点击滚动到对应块
  const entries = [];
  blocks.forEach((b, i) => {
    const h = b.querySelector('h1.ce-header, h2.ce-header, h3.ce-header');
    if (h) entries.push({ level: +h.tagName[1], text: h.textContent.trim(), el: b });
  });
  conn.outlineList.innerHTML = entries.length
    ? entries.map((e, i) =>
        `<div class="ed-outline-item" data-i="${i}" style="padding-left:${(e.level-1)*12+8}px">${esc(e.text || '(无标题)')}</div>`).join('')
    : '<div class="ed-outline-empty">暂无标题块<br>用「标题」块组织笔记后在此生成目录</div>';
  conn.outlineList.querySelectorAll('.ed-outline-item').forEach(item => {
    item.onclick = () => {
      const e = entries[+item.dataset.i];
      if (e && e.el) conn.wrap.querySelector('.ed-scroll').scrollTo({ top: e.el.offsetTop - 40, behavior: 'smooth' });
    };
  });
  // 统计：块类型分布
  const types = {};
  blocks.forEach(b => {
    if (b.querySelector('.ce-header')) types['标题'] = (types['标题']||0) + 1;
    else if (b.querySelector('.cdx-list')) types['列表'] = (types['列表']||0) + 1;
    else if (b.querySelector('.cdx-checklist')) types['清单'] = (types['清单']||0) + 1;
    else if (b.querySelector('.tc-wrap, .tc-table')) types['表格'] = (types['表格']||0) + 1;
    else if (b.querySelector('.image-tool')) types['图片'] = (types['图片']||0) + 1;
    else if (b.querySelector('.cdx-quote')) types['引用'] = (types['引用']||0) + 1;
    else if (b.querySelector('.ce-code')) types['代码'] = (types['代码']||0) + 1;
    else types['文本'] = (types['文本']||0) + 1;
  });
  conn.outlineStats.innerHTML = Object.entries(types)
    .map(([k, v]) => `<span class="ed-outline-stat">${esc(k)} ${v}</span>`).join('');
}
// 侧边栏与状态栏共用的统计文案（不含保存态）
function _edStatText(conn) {
  if (conn.isNote) {
    const blocks = conn.holder ? conn.holder.querySelectorAll('.ce-block').length : 0;
    return `${blocks} 块`;
  }
  if (conn.monaco) {
    // Monaco getPosition() 返回 {lineNumber, column}——字段是 lineNumber 不是 line（曾中招）
    const pos = conn.monaco.getPosition() || { lineNumber: 1, column: 1 };
    const len = conn.monaco.getModel() ? conn.monaco.getModel().getValueLength() : 0;
    return `行 ${pos.lineNumber}，列 ${pos.column} · ${len} 字符`;
  }
  if (conn.ta) {
    const pos = conn.ta.selectionStart;
    const before = conn.ta.value.slice(0, pos);
    const line = before.split('\n').length;
    const col = pos - (before.lastIndexOf('\n') + 1) + 1;
    return `行 ${line}，列 ${col} · ${conn.ta.value.length} 字符`;
  }
  return '';
}
function _edStateText(conn) {
  return !conn.onDisk ? ' · 未保存到磁盘' : (conn.dirty ? ' · 未保存' : ' · 已保存');
}

// ---- 打开已有文件：files/ 内按 name；外部绝对路径按 path（拖入文件，可编辑）----
async function openEditorFile(nameOrPath) {
  // 任务型通知：外部大文件读取有等待（网络盘/大文本），并发打开各自一条
  const _n = nameOrPath.split(/[\\/]/).pop();
  const nid = notifyTask({type:'file', title:'正在打开', detail:_n});
  try {
    const isExtPath = /^[a-zA-Z]:[\\/]|\\\\/.test(nameOrPath);  // Windows 绝对路径/UNC
    const r = await fetch('/api/ed/open?' + (isExtPath
      ? 'path=' + encodeURIComponent(nameOrPath)
      : 'name=' + encodeURIComponent(nameOrPath)));
    const j = await r.json();
    if (!j.ok) { notifyTaskDone(nid, {ok:false, title:'打开失败', detail:j.err || '未知错误', ms:5000}); return; }
    notifyTaskDone(nid, {ok:true, title:'已打开', detail:_n});
    const name = j.name || nameOrPath;
    const isNote = name.toLowerCase().endsWith('.note');
    // .note 存 JSON，.txt 存纯文本
    let content = j.text;
    if (isNote) { try { content = JSON.parse(j.text); } catch(e) { content = { blocks: [] }; } }
    // 记入最近打开（文件类型，快捷重开走编辑器）
    if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+name, label:name, data:{kind:'edit', name:name, path:nameOrPath, extPath: isExtPath ? nameOrPath : ''}});
    window._edLastUsedEnc = isExtPath ? (j.used_enc || null) : null;
    const _c = buildEditorTab(name, content, isExtPath ? nameOrPath : null, j.mtime || null);
    if (_c) { _c.usedEnc = j.used_enc || null; _c.hasBom = !!j.has_bom; }   // a238：BOM 状态随打开结果记录（保存回补依据）
  } catch(e) { notifyTaskDone(nid, {ok:false, title:'打开失败', detail:String(e), ms:5000}); }
}

// ---- 保存：草稿/未落盘 → tab 标题原地改名（定名即保存）；已落盘 → 覆盖保存 ----
async function edSave(conn, _forceOverwrite) {
  if (!conn.onDisk) { edRenamePrompt(conn); return; }
  const content = await _edGetContent(conn);
  if (content === null) { showBanner('读取内容失败', 4000, true); return; }
  const text = _edOutText(conn, conn.isNote ? JSON.stringify(content) : content);
  try {
    // 外部文件（拖入）：写回原绝对路径；站内文件：按名写 files/
    // a238（第5轮A2）：enc/bom 按打开时的编码状态回写（GBK 文件不再被静默
    // 转 UTF-8）；expect_mtime = 打开基准 mtime，磁盘被外部改动时后端 409
    const body = conn.extPath
      ? {path: conn.extPath, text,
         enc: (conn.usedEnc && !conn.isNote) ? conn.usedEnc : undefined,
         bom: !!conn.hasBom && !conn.isNote,
         expect_mtime: (_forceOverwrite || conn.fileMtime == null) ? undefined : conn.fileMtime}
      : {name: conn.meta.label, text,
         // a245 P2（a238复审）：站内 files/ 分支同样回传 enc/bom——后端早已
         // 接收（_write_text_atomic 按 enc 回写），此前漏发=GBK 站内文件保存
         // 被静默转 UTF-8。笔记（editorjs JSON）恒 utf-8，与 extPath 分支同排除
         enc: (conn.usedEnc && !conn.isNote) ? conn.usedEnc : undefined,
         bom: !!conn.hasBom && !conn.isNote};
    const r = await fetch('/api/ed/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const j = await r.json();
    if (r.status === 409 && j.conflict) {
      // 保存撞上外部改动（lost-update 防线）：复用磁盘改动三选弹窗
      // reload=丢弃内存取磁盘版 / keep=用内存覆盖磁盘（强制） / ignore=放弃保存
      const pick = await _edDiskChangedModal(conn, null);
      if (pick === 'reload') { _edReloadFromDisk(conn); return; }
      // a246 P3（a238复审）：不再置 fileMtime=null——_forceOverwrite 已让 body
      // 跳过 expect_mtime（CAS），null 反而有害：强制保存失败后基准丢失，
      // 磁盘改动检测对该 tab 永久失效。成功路径下方 j.mtime 会刷新基准
      if (pick === 'keep') { return edSave(conn, true); }
      return;   // ignore：不保存
    }
    if (!j.ok) { showBanner(j.err || '保存失败', 4000, true); return; }
    _edSetBase(conn, content);
    // a238 P2-3：不再硬写 dirty=false——保存往返期间的新击键会被误标干净，
    // 关 tab 时 dirty=false 不弹确认直接丢字。以刚保存内容为基线重比对
    _edMarkDirty(conn);
    if (typeof treeDecoRefresh === 'function') treeDecoRefresh(); _edMarkTab(conn); _edUpdateInfo(conn);
    // a238 P3-1：保存响应直接带新 mtime（原二次异步 stat 失败会让下轮轮询
    // 把自己的保存误判为外部改动）
    if (j.mtime) { conn.fileMtime = j.mtime; conn.diskWatchAsked = null; conn._fileGoneWarned = false; }
    showBanner('已保存 ' + (conn.extPath || conn.meta.label), 1500);
    // v3.5.297：保存后反链面板自动刷新（链入/链出与磁盘内容保持一致）
    if (typeof nnRefreshLinksIfOpen === 'function') { try { nnRefreshLinksIfOpen(conn); } catch (_) {} }
    // 保存成功即入最近列表（草稿定名/已有文件覆盖保存都会走到这）
    if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+conn.meta.label, label:conn.meta.label, data:{kind:'edit', name:conn.meta.label, path:conn.meta.label, extPath: conn.extPath || ''}});
  } catch(e) { showBanner('保存失败: ' + e, 4000, true); }
}

// ---- 后台改动检测：磁盘 mtime ≠ 打开基准 → 暗色弹窗让用户选择 ----
// 场景：编辑器开着文本文件，后台进程（编译输出/脚本/另一个会话）改了磁盘内容。
// 三选：重新加载（丢内存）/ 保留内存版（标 dirty，之后可覆盖保存或另存）/ 忽略本次。
// 轮询：tab 激活时每 5s 查 /api/ed/stat（轻量 mtime+size），切走暂停——流畅守则。
function _edDiskChangedModal(conn, diskMtime) {
  return new Promise(resolve => {
    let m = document.getElementById('edDiskChangedModal');
    if (m) m.remove();
    m = document.createElement('div');
    m.className = 'modal';
    m.id = 'edDiskChangedModal';
    m.innerHTML = `
      <div class="box" style="max-width:440px;">
        <div class="head"><strong>文件已在磁盘上被修改</strong>
          <div class="head-actions"><button class="btn ghost icon-btn" id="edDcClose">✕</button></div>
        </div>
        <div style="padding:16px 20px;font-size:12px;line-height:1.8;color:var(--fg);">
          <b>${esc(conn.meta.label)}</b> 被其他程序修改了（后台进程/另一个会话写入）。
          <br><span style="color:var(--muted);">内存里的内容没有被动过，磁盘上是新版本——两边现在不一致：</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;padding:4px 20px 8px;">
          <button class="btn primary" id="edDcReload" style="width:100%;text-align:left;">
            ↻ 重新加载磁盘版（内存修改将被丢弃）</button>
          <button class="btn ghost" id="edDcKeep" style="width:100%;text-align:left;">
            ✎ 保留内存版（标记为有改动，之后可覆盖保存 / 另存为）</button>
          <button class="btn ghost" id="edDcIgnore" style="width:100%;text-align:left;color:var(--muted);">
            <span>${ICO16.next}</span> 忽略本次（继续编辑，下次改动再提醒）</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    const finish = v => { m.classList.remove('show'); setTimeout(() => m.remove(), 200); resolve(v); };
    m.querySelector('#edDcReload').onclick = () => finish('reload');
    m.querySelector('#edDcKeep').onclick = () => finish('keep');
    m.querySelector('#edDcIgnore').onclick = () => finish('ignore');
    m.querySelector('#edDcClose').onclick = () => finish('ignore');
    m.classList.add('show');
  });
}

async function _edCheckDiskChanged(conn) {
  if (!conn.onDisk || !conn.fileMtime) return;
  // 弹窗挂起中不重复查（同一文件弹一次，等用户选完再继续）
  if (conn._dcAsking) return;
  try {
    const q = conn.extPath
      ? '/api/ed/stat?path=' + encodeURIComponent(conn.extPath)
      : '/api/ed/stat?name=' + encodeURIComponent(conn.meta.label);
    const r = await fetch(q);
    const j = await r.json();
    if (!j.ok) {
      // 文件被外部删除/不可访问：一次性提示（不弹选择——没有可重载的东西）
      if (conn.fileMtime && !conn._fileGoneWarned) {
        conn._fileGoneWarned = true;
        showBanner('⚠ ' + conn.meta.label + ' 在磁盘上已不存在（被外部删除？），内存版保留', 5000, true);
      }
      return;
    }
    // mtime 变了且不是已经弹过这一版（diskWatchAsked 记录弹过的 mtime）
    if (Math.abs(j.mtime - conn.fileMtime) < 0.001) return;
    if (conn.diskWatchAsked !== null && Math.abs(j.mtime - conn.diskWatchAsked) < 0.001) return;
    // 差异仅在毫秒内（自己保存触发的 os.replace 通常 <1ms 内被下一轮查到，
    // 但保存已更新 fileMtime——走到这说明真不是自己写的）→ 弹
    conn._dcAsking = true;
    conn.diskWatchAsked = j.mtime;
    const choice = await _edDiskChangedModal(conn, j.mtime);
    conn._dcAsking = false;
    if (choice === 'reload') {
      await _edReloadFromDisk(conn);
    } else if (choice === 'keep') {
      // 保留内存版：标记 dirty（有改动状态），用户之后自行覆盖保存（写回时
      // mtime 基准更新）或另存为。不动 savedData——脏检测基准仍是打开时内容。
      conn.dirty = true; _edMarkTab(conn); _edUpdateInfo(conn);
      if (typeof treeDecoRefresh === 'function') treeDecoRefresh();   // a213 P2：保留内存版
      showBanner('已保留内存版并标记改动——可「保存」覆盖磁盘或「另存为」保留两版', 4000);
    }
    // ignore：什么都不动，diskWatchAsked 已记录本次 mtime，同一改动不再弹
  } catch(_) {}   // stat 网络失败静默（下轮再查）
}

// 重读磁盘（同编码切换链路）：内容/基准/脏标志一起刷新。
// a238：从 _edCheckDiskChanged 抽出——保存撞外部改动（409）选「重载」时复用
async function _edReloadFromDisk(conn) {
  try {
    const enc = conn.usedEnc || '';
    const oq = (conn.extPath
      ? '/api/ed/open?force=1&path=' + encodeURIComponent(conn.extPath)
      : '/api/ed/open?name=' + encodeURIComponent(conn.meta.label))
      + (enc ? '&enc=' + encodeURIComponent(enc) : '');
    const r2 = await fetch(oq);
    const j2 = await r2.json();
    if (!j2.ok) { showBanner('重读失败：' + (j2.err || ''), 4000, true); return; }
    let content = j2.text;
    if (conn.isNote) { try { content = JSON.parse(j2.text); } catch(_) { content = { blocks: [] }; } }
    if (conn.editor) { conn.editor.render(content); }
    else if (conn.monaco) {
      const pos = conn.monaco.getPosition();
      conn.monaco.setValue(j2.text);
      try { conn.monaco.setPosition(pos); conn.monaco.revealLineInCenter(pos.lineNumber); } catch(_) {}
    } else if (conn.ta) conn.ta.value = j2.text;
    _edSetBase(conn, content);
    conn.hasBom = !!j2.has_bom;
    conn.dirty = false;
    if (typeof treeDecoRefresh === 'function') treeDecoRefresh(); _edMarkTab(conn); _edUpdateInfo(conn);
    conn.fileMtime = j2.mtime;
    conn._fileGoneWarned = false;
    showBanner('已重新加载 ' + conn.meta.label, 2000);
  } catch(e) { showBanner('重读失败: ' + e, 4000, true); }
}

// a372（用户实锤：引用/跳转落点概率性错位无高亮）：已打开 tab 的内容是
// 打开时点的旧版本，磁盘后续被改（外部工具/构建/另一会话）——引用面板
// 的行号来自 rg 搜磁盘新版，jump 按行号盲跳旧版 tab = 落点内容错位
// （旧版 2174 行是新版 469 行的内容），selectLine 高亮落在不相关的行。
// 跳转前校验 mtime：不 dirty 静默重读磁盘版再跳；dirty（有未保存修改）
// 尊重内存编辑不重读，提示一次后照跳
async function _edJumpFresh(conn) {
  try {
    if (!conn || !conn.onDisk || !conn.fileMtime || !conn.extPath) return;
    // 不做结果缓存：打开（旧版 changed=false）→磁盘改→3s 内跳转的窗口里
    // 缓存会跳过 stat（验证实测踩中）；跳转低频，stat 本地几 ms 足够便宜
    const r = await fetch('/api/ed/stat?path=' + encodeURIComponent(conn.extPath));
    const j = await r.json();
    const changed = !!(j.ok && Math.abs(j.mtime - conn.fileMtime) >= 0.001);
    if (!changed) return;
    if (!conn.dirty) { await _edReloadFromDisk(conn); return; }
    if (!conn._jfWarned) {
      conn._jfWarned = true;
      showBanner('⚠ ' + conn.meta.label + ' 磁盘已有新版本（内存版有未保存修改未自动重读），跳转行号可能偏移', 5000, true);
    }
  } catch (_) {}
}

// ---- 另存为：同样走 tab 原地改名（改名确认后即另存为新文件）----
function edSaveAs(conn) { edRenamePrompt(conn); }

// 编辑器 tab 的磁盘检测调度：切到该 tab 时启动 5s 轮询，切走暂停。
// _edOnSwitchEditor 在 terminal-core.js switchTab 里调（kind==='editor' 分支）。
function _edStartDiskWatch(conn) {
  if (!conn.onDisk || !conn.fileMtime) return;
  if (!conn.diskWatchTimer) {
    conn.diskWatchTimer = setInterval(() => {
      if (conn.wrap.style.display === 'none') return;   // 不可见跳过本轮（不清，切回即续）
      _edCheckDiskChanged(conn);
    }, 5000);
  }
}
function _edStopDiskWatch(conn) {
  if (conn.diskWatchTimer) { clearInterval(conn.diskWatchTimer); conn.diskWatchTimer = null; }
}
function _edOnSwitchEditor(conn) {
  if (!conn || !conn.meta || conn.meta.kind !== 'editor' || conn.isDiff) return;
  if (conn.fileMtime) _edStartDiskWatch(conn);
  // a360R（用户需求1，VSCode 同款）：切到编辑器 tab 时，文件树同步定位到
  // 该文件——已打开的根目录逐级展开并滚动到可见。
  // 只对「在树根之下」的绝对路径生效：treeReveal 内部先判 inRoot，不在任何
  // 根下的独立文件直接返回 false，不会去动树（用户明确要求：单独打开的
  // 文件不需要这个动作）。.note 草稿与站内 files/ 文件 extPath 为 null，天然跳过。
  const _xp = conn.extPath;
  if (_xp && typeof window.treeReveal === 'function') {
    try { window.treeReveal(_xp, { scroll: true }); } catch (_) {}
  }
}

// ---- 改名入口（工具栏按钮 / 双击 tab 标题共用）：标题原地变输入框 ----
// 无 prompt 弹窗；Enter 确认 / Esc 取消 / 失焦确认。
// 输入框只显主名不带后缀（防止改名把后缀弄丢/改错）；提交时自动补回后缀：
// - 草稿：默认 .note；已落盘：保留原文件后缀。用户显式输入了后缀（含 .）则尊重。
function _edBaseName(label) {
  const i = label.lastIndexOf('.');
  return i > 0 ? label.slice(0, i) : label;   // '.gitignore' 这类点开头整名保留
}
function _edExt(label) {
  const i = label.lastIndexOf('.');
  return i > 0 ? label.slice(i) : '';
}
function edRenamePrompt(conn) {
  if (!conn || conn._renaming) return;
  const label = conn.tab.querySelector('.label');
  conn._renaming = true;
  const curExt = conn.onDisk ? _edExt(conn.meta.label) : (conn.draftExt || '.note');  // 后缀：草稿按「新建文件」所选，落盘保留原后缀
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'tab-rename-input';
  // 宽度跟随内容自适应（ch 单位近似等宽字符宽度）
  const fit = () => { inp.style.width = Math.max(8, inp.value.length + 2) + 'ch'; };
  inp.value = conn.onDisk ? _edBaseName(conn.meta.label) : '新建笔记';
  if (!conn.onDisk) {
    // 草稿：拉后端不冲突默认名预填主名。
    // 用户已动手改过输入则不再覆盖（否则打字被回填冲掉）
    fetch('/api/ed/default_name?ext=' + encodeURIComponent(curExt)).then(r => r.json()).then(j => {
      if (j.ok && conn._renaming && !inp._userEdited && document.activeElement === inp) {
        inp.value = _edBaseName(j.name); fit();
      }
    }).catch(() => {});
  }
  label.textContent = '';
  label.appendChild(inp);
  inp.focus(); inp.select();
  fit();
  inp.addEventListener('input', () => { inp._userEdited = true; fit(); });
  const finish = async (commit) => {
    if (!conn._renaming) return;
    conn._renaming = false;
    const base = inp.value.trim();
    inp.remove();
    // 输入只输入了新后缀形式（如 '.md'）→ 主名沿用原值只换后缀
    let nn = base;
    if (base.startsWith('.') && conn.onDisk) nn = _edBaseName(conn.meta.label) + base;
    else if (base && !base.includes('.')) nn = base + curExt;   // 没写后缀 → 补默认
    if (!commit || !nn || nn === conn.meta.label) { _edMarkTab(conn); return; }
    if (!conn.onDisk) {
      // 草稿：定名保存（含当前内容，保存后才算落盘）
      const content = await _edGetContent(conn);
      if (content === null) { showBanner('读取内容失败', 4000, true); _edMarkTab(conn); return; }
      const text = _edOutText(conn, conn.isNote ? JSON.stringify(content) : content);
      try {
        const r = await fetch('/api/ed/save_as', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({new_name: nn, text})});
        const j = await r.json();
        if (!j.ok) { showBanner(j.err || '保存失败', 4000, true); _edMarkTab(conn); return; }
        conn.meta.label = j.name;
        _edSetBase(conn, content);   // a238：EOL 基线（新名落盘沿用当前 EOL/编码状态）
        conn.onDisk = true;
        conn.dirty = false;
    if (typeof treeDecoRefresh === 'function') treeDecoRefresh();
        showBanner('已保存 ' + j.name, 1500);
      } catch(e) { showBanner('保存失败: ' + e, 4000, true); }
    } else {
      // 已落盘：重命名磁盘文件
      try {
        const r = await fetch('/api/ed/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({old: conn.meta.label, new: nn})});
        const j = await r.json();
        if (!j.ok) { showBanner(j.err || '重命名失败', 4000, true); _edMarkTab(conn); return; }
        conn.meta.label = j.name;
        showBanner('已重命名为 ' + j.name, 1500);
      } catch(e) { showBanner('重命名失败: ' + e, 4000, true); }
    }
    _edMarkTab(conn); _edUpdateInfo(conn);
  };
  inp.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  inp.addEventListener('blur', () => finish(true));  // 失焦=确认（点别处自然生效）
  inp.addEventListener('click', e => e.stopPropagation());
}

// ---- 删除（已落盘才有东西可删；脏内容一并丢，双重确认）----
// 工具栏删除按钮已按用户要求移除（误点危险），入口不再存在
async function edDelete(conn) {
  if (conn.onDisk) {
    if (!(await _edConfirm(`确定删除「${conn.meta.label}」？此操作不可恢复。`))) return;
    try {
      const r = await fetch('/api/ed/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: conn.meta.label})});
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '删除失败', 4000, true); return; }
    } catch(e) { showBanner('删除失败: ' + e, 4000, true); return; }
  }
  _edCloseNow(conn);
  showBanner('已删除', 1500);
}

// ---- 关闭 tab：脏则确认（确定=丢弃修改直接关，取消=留在编辑器）----
async function closeEditorTab(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (conn.dirty) {
    // 应用风格确认弹窗（原生 confirm 画风不符）；hex tab 的 conn 有 _hxConfirm
    let ok;
    if (typeof conn.confirmClose === 'function') ok = await conn.confirmClose();
    else ok = await _edConfirm(`「${conn.meta.label}」有未保存的修改，关闭将丢失。确定关闭？`);
    if (!ok) return;
  }
  _edCloseNow(conn);
}
// 通用确认弹窗（编辑器 tab 共用；仿 hex-viewer 的 _hxConfirm 画风）
function _edConfirm(msg) {
  return new Promise(resolve => {
    let m = document.getElementById('edConfirmModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'edConfirmModal';
      m.innerHTML = `
        <div class="box" style="max-width:380px;">
          <div class="head"><strong>确认</strong>
            <div class="head-actions"><button class="btn ghost icon-btn" id="edConfirmClose">✕</button></div>
          </div>
          <div style="padding:18px 20px;">
            <div id="edConfirmMsg" style="color:var(--muted);font-size:12px;line-height:1.6;margin-bottom:16px;word-break:break-all;"></div>
            <div style="display:flex;gap:10px;justify-content:flex-end;">
              <button class="btn ghost" id="edConfirmNo">取消</button>
              <button class="btn primary" id="edConfirmYes">确定</button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(m);
    }
    m.querySelector('#edConfirmMsg').textContent = msg;
    const finish = v => { m.classList.remove('show'); resolve(v); };
    m.querySelector('#edConfirmYes').onclick = () => finish(true);
    m.querySelector('#edConfirmNo').onclick = () => finish(false);
    m.querySelector('#edConfirmClose').onclick = () => finish(false);
    m.classList.add('show');
  });
}
function _edCloseNow(conn) {
  // 磁盘检测轮询清掉（编辑器 tab 专属；proxy 等面板 tab 的 pollTimer 下一行通用清理）
  if (conn.diskWatchTimer) { clearInterval(conn.diskWatchTimer); conn.diskWatchTimer = null; }
  // 面板类 tab（proxy 等）带轮询 interval：关 tab 必清（wrap 脱离 DOM 后
  // display 残留 "flex"，面板自己的可见性检测兜不住，不清会空拉到退出）
  if (conn.pollTimer) { clearInterval(conn.pollTimer); conn.pollTimer = null; }
  // proxy 面板的「上次刷新 Ns 前」倒计时 interval 同理
  if (conn.tickTimer) { clearInterval(conn.tickTimer); conn.tickTimer = null; }
  // Editor.js 实例先销毁（停掉内部 mutation 监听，防关 tab 后仍触发 onChange）
  if (conn.editor) { try { conn.editor.destroy(); } catch(e){} }
  // Monaco 同理（停掉 onDidChangeModelContent，防关 tab 后仍触发脏检测）
  if (conn.monaco) { try { conn.monaco.dispose(); } catch(e){} }
  // R15-2（实锤：model 陈旧覆盖磁盘）：a333 起带 uri 的 model 在全局
  // registry 复用——关 tab 必须 dispose，否则重开时 getModel 拿旧内容、
  // 外部修改被旧值覆盖（数据丢失链）。md 分栏/其他实例同 uri 亦然。
  // 内存诊断实锤补刀：无 extPath 的 inmemory model（新建文件/.bat 等）
  // 此前永不 dispose——connections 清空后 model registry 仍残留（实测
  // 0 tab 存活 2 model），长会话下 Monaco model/worker 累积。统一：uri
  // model 按 extPath dispose；inmemory model 按实例当前 model dispose
  if (conn.monaco || conn.extPath) {
    try {
      if (window.monaco && monaco.editor) {
        if (conn.extPath) {
          const _m = monaco.editor.getModel(monaco.Uri.file(conn.extPath));
          if (_m) _m.dispose();
        } else if (conn._m) {
          conn._m.dispose();
        }
      }
    } catch(e) {}
  }
  // 查找分栏 splitter 的 document 级拖拽监听移除（防泄漏，同 closeLogViewer）
  if (conn._edSplitMove) document.removeEventListener('mousemove', conn._edSplitMove);
  if (conn._edSplitUp) document.removeEventListener('mouseup', conn._edSplitUp);
  // a237 P0/P1/P2（第5轮A4）：per-tab 的 document 级监听器统一摘除——
  // keydown（编辑器 Ctrl+S/Ctrl+F/slash；diff/bindiff 的 F7/导航）与
  // hex 的拖选 mouseup。匿名挂载无从移除，会把 conn 图（全文/字节缓冲/
  // 脱离 wrap）永久钉死在 document 上，开关 tab ×N 即累积驻留
  if (conn._docKey) document.removeEventListener('keydown', conn._docKey);
  if (conn._dvKey) document.removeEventListener('keydown', conn._dvKey);
  if (conn._bdKey) document.removeEventListener('keydown', conn._bdKey);
  if (conn._hxUp) document.removeEventListener('mouseup', conn._hxUp);
  // a237 P2：hex 只读大文件的后台分块拉取中止（关 tab 即停，防 2000+ 串行 fetch 空转到文件尾）
  if (conn._hxAbort) { try { conn._hxAbort.abort(); } catch(e){} }
  // DiffEditor（diff tab）：编辑器与两侧 model 一并销毁（防泄漏 + 关 tab 后仍触发 onDidUpdateDiff）
  if (conn.diffEd) {
    try {
      const m = conn.diffEd.getModel();
      conn.diffEd.dispose();
      if (m) { m.original.dispose(); m.modified.dispose(); }
    } catch(e){}
  }
  // a309R3 M8（第2轮审查）：office tab 资源清理（参照 hex/editor 同模式）——
  // _dsEditor：OnlyOffice 编辑器实例（内部 iframe/websocket 不销毁即常驻）；
  // _pdfTask/_pdfDoc：pdf.js 文档与 worker（100MB 级 PDF 关 tab 不清即驻留）；
  // _pdfIO：页面虚拟化 IntersectionObserver；_outlineRO：docx 大纲栏
  // ResizeObserver（a314 自绘条已删，_ovSbV/H 挂载点不再产生——清理段保留
  // 防御旧引用，无害）
  if (conn._dsEditor) { try { conn._dsEditor.destroyEditor(); } catch(e){} conn._dsEditor = null; }
  if (conn._pdfTask) { try { conn._pdfTask.destroy(); } catch(e){} conn._pdfTask = null; conn._pdfDoc = null; }
  if (conn._pdfIO) { try { conn._pdfIO.disconnect(); } catch(e){} conn._pdfIO = null; }
  if (conn._outlineRO) { try { conn._outlineRO.disconnect(); } catch(e){} conn._outlineRO = null; }
  if (conn.wrap) {
    conn.wrap.querySelectorAll('[data-ov-body], [data-ov-pages]').forEach(h => {
      if (h._ovSbV) { clearTimeout(h._ovSbV.hideT); h._ovSbV = null; }
      if (h._ovSbH) { clearTimeout(h._ovSbH.hideT); h._ovSbH = null; }
    });
  }
  conn.tab.remove(); conn.wrap.remove();
  delete connections[conn.portId];
  if (typeof treeDecoRefresh === 'function') treeDecoRefresh();   // a209批1：树 open/dirty 装饰联动
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0;
  });
  // v4.1：关闭的是当前活动 tab → 优先回「来时的 tab」（switchTab 记录），
  // 来路已关/无来路才回排序首位。claude 会话开对比的流：claude → diff →
  // 关 diff 应回 claude，旧逻辑回排序首位会被已开的文件 tab 顶掉（用户实锤）。
  // 关的不是活动 tab：不动激活态（旧逻辑无条件切排序首位，关后台 tab 也把
  // 用户拽走）
  const back = window._hgTabBack;
  window._hgTabBack = null;
  if (remaining.length) {
    if (activePortId === conn.portId) {
      switchTab(back && connections[back] ? back : remaining[0]);
    }
  }
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon"><svg width="30" height="30" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 2.5v3M10.5 2.5v3"/><path d="M4 5.5h8v2a4 4 0 0 1-8 0z"/><path d="M8 11.5v2"/></svg></div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();  // 同步左侧列表
}

// ---- 新建文件：只建草稿 tab（.note 块笔记），不落盘 ----
function newEditorFile() {
  buildEditorTab(null, null);
}

// ---- v2.27「新建文件」下拉：笔记 / .txt / .md / 自定义后缀 ----
// 草稿只定形态与默认后缀，落盘仍发生在首次保存/改名（原保存模型不动）。
function newFileMenuShow(anchor) {
  const old = document.querySelector('.nf-menu');
  if (old) { old.remove(); return; }
  const menu = document.createElement('div');
  menu.className = 'nf-menu';
  menu.innerHTML = `
    <div class="nf-item" data-ext=".note"><b><span>${ICO16.note}</span> 笔记</b><span>块式编辑，可贴图（.note）</span></div>
    <div class="nf-item" data-ext=".txt"><b><span>${ICO16.file}</span> 纯文本</b><span>.txt</span></div>
    <div class="nf-item" data-ext=".md"><b><span>${ICO16.note}</span> Markdown</b><span>.md</span></div>
    <div class="nf-custom">
      <input class="nf-ext-inp" data-nf-ext placeholder="自定义后缀，如 .log / .csv" spellcheck="false" name="hg_nf_ext">
      <button class="btn ghost nf-ext-go" data-nf-go>新建</button>
    </div>`;
  menu.style.position = 'fixed';
  menu.style.left = '0'; menu.style.top = '0';
  document.body.appendChild(menu);
  const ar = anchor.getBoundingClientRect();
  let x = ar.left, y = ar.bottom + 6;
  if (x + menu.offsetWidth > window.innerWidth - 8) x = window.innerWidth - menu.offsetWidth - 8;
  if (y + menu.offsetHeight > window.innerHeight - 8) y = ar.top - menu.offsetHeight - 6;
  menu.style.left = Math.max(6, x) + 'px';
  menu.style.top = Math.max(6, y) + 'px';
  const create = (ext) => {
    menu.remove();
    buildEditorTab(null, null, null, null, ext);
  };
  menu.querySelectorAll('.nf-item').forEach(it => {
    it.onclick = () => create(it.dataset.ext);
  });
  const inp = menu.querySelector('[data-nf-ext]');
  const go = menu.querySelector('[data-nf-go]');
  const commitCustom = () => {
    let ext = inp.value.trim().toLowerCase();
    if (!ext) { inp.focus(); return; }
    if (!ext.startsWith('.')) ext = '.' + ext;
    if (!/^\.[a-z0-9_-]+$/.test(ext)) { inp.value = ''; inp.placeholder = '后缀只能用字母/数字/-_'; inp.focus(); return; }
    create(ext);
  };
  go.onclick = commitCustom;
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); commitCustom(); } });
  const close = (ev) => {
    if (menu.contains(ev.target) || anchor.contains(ev.target)) return;
    menu.remove();
    document.removeEventListener('mousedown', close, true);
  };
  setTimeout(() => document.addEventListener('mousedown', close, true), 0);
}

// ---- files/ 文件列表弹窗：复用日志库 modal 风格 ----
async function showFilesModal() {
  let modal = $('filesModal');
  if (!modal) {
    modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'filesModal';
    modal.innerHTML = `
      <div class="box">
        <div class="head">
          <strong><span>${ICO16.note}</span> 笔记</strong>
          <div class="head-actions">
            <button class="btn ghost" id="filesSearchBtn" title="全库搜索（Ctrl+Alt+F）"><span>${ICO16.search}</span> 搜索</button>
            <button class="btn ghost" id="filesNew" title="新建笔记（不落盘，保存时才写文件）">＋ 新建笔记</button>
            <button class="btn ghost icon-btn" id="filesOpenDir" title="在资源管理器中打开 files/ 目录">${ICO16.folderOpen}</button>
            <button class="btn ghost icon-btn" id="filesClose">✕</button>
          </div>
        </div>
        <div class="list" id="filesList" style="max-height:60vh;"></div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#filesClose').onclick = () => modal.classList.remove('show');
    modal.querySelector('#filesOpenDir').onclick = () => fetch('/api/ed/open_dir', {method:'POST', headers:{'Content-Type':'application/json'}, body: '{}'});
    modal.querySelector('#filesNew').onclick = () => { modal.classList.remove('show'); newEditorFile(); };
  }
  modal.classList.add('show');
  const listEl = modal.querySelector('#filesList');
  listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">加载中…</div>';
  try {
    const r = await fetch('/api/ed/list');
    const j = await r.json();
    if (!j.ok) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">加载失败</div>'; return; }
    if (!j.files.length) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">暂无笔记，点击「新建笔记」创建</div>'; return; }
    listEl.innerHTML = '';
    // v3.5.298：标签 chips 行注入（notes-nav.js——#tag 聚合筛选，点选过滤列表）
    if (typeof nnRenderTagFilter === 'function') { try { nnRenderTagFilter(modal, listEl); } catch (_) {} }
    j.files.forEach(f => {
      const d = document.createElement('div');
      d.className = 'item';
      d.dataset.name = f.name;   // v3.5.298：标签筛选按文件名过滤（notes-nav.js）
      const dt = new Date(f.mtime*1000);
      const kb = f.size >= 1024 ? (f.size/1024).toFixed(1) + ' KB' : f.size + ' B';
      const icon = f.name.toLowerCase().endsWith('.note') ? ICO16.note : ICO16.file;
      d.innerHTML = `<span><span>${icon}</span> ${esc(f.name)}<br><span class="sz">${dt.toLocaleString('zh-CN')} · ${kb}</span></span>
        <span class="item-actions">
          <span class="act-btn open" data-open="${esc(f.name)}" title="打开编辑此文件">✎ 编辑</span>
        </span>`;
      d.onclick = () => { modal.classList.remove('show'); openEditorFile(f.name); };
      d.querySelector('[data-open]').onclick = (ev) => { ev.stopPropagation(); modal.classList.remove('show'); openEditorFile(f.name); };
      listEl.appendChild(d);
    });
  } catch(e) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">加载失败: ' + esc(String(e)) + '</div>'; }
}

// ---- 编辑器全局搜索（纯文本 textarea 为主，.note 按块文本降级支持）----
// 搜索 + 排除（| 分隔正则）+ 结果列表 + 点击/回车跳转。与日志/串口搜索语法一致。
function edToggleSearchPane(conn, show) {
  const pane = conn.wrap.querySelector('.ed-search-pane');
  const st = !pane.style.display || pane.style.display === 'none';
  const toShow = show !== undefined ? show : st;
  pane.style.display = toShow ? 'flex' : 'none';
  // splitter 与分栏同开同关（display:none 时不可拖、也不占 5px）
  const splitter = conn.wrap.querySelector('.ed-search-splitter');
  if (splitter) splitter.style.display = toShow ? 'block' : 'none';
  const btn = conn.wrap.querySelector('.ed-search-collapse');
  if (btn) btn.textContent = toShow ? '▾' : '▴';
  if (toShow) conn.wrap.querySelector('.ed-search-q').focus();
}
// 拖分隔条调查找分栏高度（仿 initLogSplitter；Monaco automaticLayout 自适应免手动 layout）
function initEdSplitter(conn) {
  const splitter = conn.wrap.querySelector('.ed-search-splitter');
  if (!splitter) return;
  const pane = conn.wrap.querySelector('.ed-search-pane');
  let dragging = false, startY = 0, startH = 0;
  splitter.addEventListener('mousedown', e => {
    dragging = true; startY = e.clientY; startH = pane.offsetHeight;
    document.body.style.cursor = 'row-resize'; e.preventDefault();
  });
  conn._edSplitMove = e => {
    if (!dragging) return;
    const dh = e.clientY - startY;
    // 往上拖（dh<0）pane 变大；钳到 60px ~ 编辑器区高-100
    const newH = Math.max(60, Math.min(startH - dh, conn.wrap.clientHeight - 100));
    pane.style.height = newH + 'px';
  };
  conn._edSplitUp = () => {
    if (dragging) { dragging = false; document.body.style.cursor = ''; }
  };
  document.addEventListener('mousemove', conn._edSplitMove);
  document.addEventListener('mouseup', conn._edSplitUp);
}
async function doEdSearch(conn) {
  const qEl = conn.wrap.querySelector('.ed-search-q');
  const exEl = conn.wrap.querySelector('.ed-search-ex');
  const cntEl = conn.wrap.querySelector('.ed-search-count');
  const resEl = conn.wrap.querySelector('.ed-search-results');
  const q = qEl.value.trim();
  const exRaw = exEl.value.trim();
  if (!q) { cntEl.textContent = ''; resEl.innerHTML = ''; return; }
  cntEl.innerHTML = '<span class="spin">✳</span> 搜索中…';
  // 取文本源：Monaco/textarea 全文；.note 取纯文本拼接（行号近似按块）
  let lines;
  if (conn.monaco) lines = conn.monaco.getValue().split('\n');
  else if (conn.ta) lines = conn.ta.value.split('\n');
  else if (conn.editor) {
    try {
      const data = await conn.editor.save();
      lines = (data.blocks || []).map(b => {
        const t = b.data;
        if (!t) return '';
        if (typeof t.text === 'string') return t.text;
        if (Array.isArray(t.items)) return t.items.join(' ');
        if (Array.isArray(t.content)) return t.content.join(' ');
        if (typeof t.caption === 'string') return t.caption;
        return '';
      });
    } catch(e) { lines = []; }
  } else lines = [];
  // 编译正则（非法降级字面），排除模式同串口搜索语法
  let re = null;
  try { re = new RegExp(q, 'i'); } catch(e) {}
  const matches = t => re ? re.test(t) : t.toLowerCase().includes(q.toLowerCase());
  const exPats = [];
  if (exRaw) exRaw.split('|').forEach(seg => {
    seg = seg.trim(); if (!seg) return;
    try { exPats.push(new RegExp(seg, 'i')); }
    catch(e) { exPats.push(new RegExp(seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i')); }
  });
  const inEx = t => { for (const p of exPats) if (p.test(t)) return true; return false; };
  const hits = [];
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i];
    if (matches(t) && !inEx(t)) hits.push({ line: i + 1, text: t });
  }
  const st = conn.edSearchState;
  st.results = hits; st.idx = 0;
  resEl.innerHTML = hits.map((l, i) =>
    `<div class="hline" data-i="${i}" title="${esc(l.text)}"><span class="hrow">${l.line}</span> ${esc(l.text.length > 200 ? l.text.slice(0,200)+'…' : l.text)}</div>`
  ).join('') || '<div style="padding:10px;color:var(--muted);">无命中</div>';
  resEl.querySelectorAll('.hline').forEach(el => {
    el.onclick = () => { st.idx = +el.dataset.i; edJumpToHit(conn, st.idx); };
  });
  cntEl.textContent = hits.length ? `命中 ${hits.length} 处` : '无命中';
  if (hits.length) edJumpToHit(conn, 0);
}
function edJumpToHit(conn, idx) {
  const st = conn.edSearchState;
  const hit = st.results[idx];
  if (!hit) return;
  conn.wrap.querySelectorAll('.ed-search-results .hline').forEach((el, i) => el.classList.toggle('active', i === idx));
  if (conn.monaco) {
    // Monaco：滚动定位到命中行 + 选中整行
    conn.monaco.revealLineNearTop(hit.line);
    conn.monaco.setPosition({ lineNumber: hit.line, column: 1 });
    const lineLen = (conn.monaco.getModel().getLineContent(hit.line) || '').length;
    try { conn.monaco.setSelection({ startLineNumber: hit.line, startColumn: 1, endLineNumber: hit.line, endColumn: lineLen + 1 }); } catch(_) {}
    conn.monaco.focus();
  } else if (conn.ta) {
    // textarea：选中该行并滚到可见。value 定位用 lineStart/End
    const lines = conn.ta.value.split('\n');
    let pos = 0;
    for (let i = 0; i < hit.line - 1; i++) pos += lines[i].length + 1;
    conn.ta.focus();
    conn.ta.setSelectionRange(pos, pos + (lines[hit.line - 1] || '').length);
    // 滚动到选中行：textarea scrollTop 按行高估算
    const lineH = parseFloat(getComputedStyle(conn.ta).lineHeight) || 20;
    conn.ta.scrollTop = Math.max(0, (hit.line - 5) * lineH);
  } else if (conn.editor) {
    // .note：滚到对应块（块序 = 行号）
    const blocks = conn.holder.querySelectorAll('.ce-block');
    const el = blocks[hit.line - 1];
    if (el) conn.wrap.querySelector('.ed-scroll').scrollTo({ top: el.offsetTop - 40, behavior: 'smooth' });
  }
}

// ============================================================
// .md 实时预览（markdown-it，GitHub 20k+ star 解析器）
// 左源码右预览分栏：ed-main 内预置 .ed-md-preview 列，编辑时同步渲染。
// ============================================================
// 预览占位/滚动同步所需的样式随资源域一并注入（不占 index.html 的样式入口）
const _ED_EXTRA_CSS = `
.ed-md-preview .md-preview-ph { color: var(--muted); font-size: 12px; padding: 12px 0; }
`;
if (!document.getElementById('edExtraStyle')) {
  const _st = document.createElement('style');
  _st.id = 'edExtraStyle';
  _st.textContent = _ED_EXTRA_CSS;
  document.head.appendChild(_st);
}

let _mdIt = null;   // markdown-it 实例单例（延迟建）
function _mdInstance() {
  if (_mdIt) return _mdIt;
  // markdown-it.min.js（vendor，index.html 已引）暴露 window.markdownit。
  // v2.27.22：linkify 关闭——裸词（.py/.js 是合法顶级域）会被补成 http://
  // 外链，预览里点击就把 WebView 导航出工具（同 harness 修复）
  _mdIt = window.markdownit ? window.markdownit({ html: false, linkify: false, typographer: false, breaks: false }) : null;
  if (_mdIt) {
    // 标题挂源码行号（token.map 起始行，转 1-based 对齐 Monaco 行号）：
    // 滚动同步以此为锚——「源码看到第五章」才能映射成「预览跳到第五章」
    const _def = _mdIt.renderer.rules.heading_open
      || ((tokens, idx, opts, env, self) => self.renderToken(tokens, idx, opts));
    _mdIt.renderer.rules.heading_open = (tokens, idx, opts, env, self) => {
      const tk = tokens[idx];
      if (tk.map) tk.attrSet('data-md-line', String(tk.map[0] + 1));
      return _def(tokens, idx, opts, env, self);
    };
  }
  return _mdIt;
}
// ---- md 分屏拖拽：分隔条 col-resize，自由调节源码/预览比例 ----
function _mdBindSplitter(wrap) {
  const splitter = wrap.querySelector('.ed-md-splitter');
  const preview = wrap.querySelector('.ed-md-preview');
  const main = wrap.querySelector('.ed-main');
  if (!splitter || !preview) return;
  splitter.addEventListener('mousedown', e => {
    e.preventDefault();
    const startX = e.clientX;
    const total = main.getBoundingClientRect().width;
    // 拖拽前预览列宽度（比例基准）
    const startW = preview.getBoundingClientRect().width;
    let moved = false;
    const move = ev => {
      const dx = ev.clientX - startX;
      if (Math.abs(dx) > 2) moved = true;
      // 方向修正：预览列在右侧、随 .ed-scroll(flex:1) 伸缩锚定左缘。
      // 往左拖鼠标 dx<0，分隔条应左移 dx —— 预览宽变化是位移的相反数（-dx），
      // 所以这里用 startW - dx。曾用 startW + dx 导致分隔条与鼠标反向跑（往左拖它往右）。
      const w = Math.max(total * 0.15, Math.min(total * 0.85, startW - dx));
      preview.style.width = w + 'px';
      preview.style.flexShrink = '0';
      // Monaco 容器宽随分栏变化由 automaticLayout 接管
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      splitter._dragging = false;
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
}
// a279 批1：MD 预览主题色独立配置（auto/dark/light/paper）
// a281：MD 预览配色方案（工具栏下拉，比设置面板的 4 档更丰富）
const _MD_PV_THEMES = [
  { id: 'auto',       name: '跟随全局' },
  { id: 'dark',       name: '暗色' },
  { id: 'light',      name: '亮色' },
  { id: 'paper',      name: '护眼纸色' },
  { id: 'github',     name: 'GitHub' },
  { id: 'dracula',    name: 'Dracula' },
  { id: 'solarized',  name: 'Solarized 暗' },
  { id: 'nord',       name: 'Nord' },
  { id: 'sepia',      name: '复古棕' },
  { id: 'mint',       name: '薄荷绿' },
];
let _mdPvTheme = '';
// a303：MD 布局三态（用户令）：src=只原文（预览藏）/ pv=只预览（编辑器藏）/
// both=同步分栏（默认）。编辑器列 ed-scroll 与预览列 ed-md-preview 显隐切换
function _mdApplyMode(conn, mode) {
  conn._mdMode = mode;
  const wrap = conn.wrap;
  const pv = wrap.querySelector('.ed-md-preview');
  const sp = wrap.querySelector('.ed-md-splitter');
  const scroll = wrap.querySelector('.ed-scroll');
  if (!pv || !scroll) return;
  if (mode === 'src') {
    pv.style.display = 'none';
    pv.classList.remove('mdpv-full');
    if (sp) sp.style.display = 'none';
    scroll.style.display = '';
  } else if (mode === 'pv') {
    pv.style.display = '';
    pv.classList.add('mdpv-full');   // a305：撑满全宽（原 50% 定宽留右侧黑块）
    if (sp) sp.style.display = 'none';
    scroll.style.display = 'none';
    _mdRenderPreview(conn);
  } else {
    pv.style.display = '';
    pv.classList.remove('mdpv-full');   // both 模式回 50% 分栏
    if (sp) sp.style.display = 'block';
    scroll.style.display = '';
    _mdRenderPreview(conn);
  }
}
function _mdPvApplyTheme(pv) {
  const t = _mdPvTheme || 'auto';
  // a281：清所有主题类再挂当前（新增配色全部走 .md-pv-<id>）
  pv.className = pv.className.replace(/\s*md-pv-\S+/g, '');
  if (t === 'auto') {
    const th = document.documentElement.getAttribute('data-theme') || 'deepblue';
    const darks = ['deepblue','onedark','darkgreen','dracula','amber','celadon','rose'];
    pv.classList.add(darks.includes(th) ? 'md-pv-dark' : 'md-pv-light');
  } else if (t !== 'paper') {
    pv.classList.add('md-pv-' + t);
  }
  // paper = 不挂类（走默认 --note-* 恒亮护眼）
}
(async () => {
  try {
    const j = await (await fetch('/api/theme')).json();
    if (j.ok && j.md_preview_theme) _mdPvTheme = j.md_preview_theme;
  } catch (_) {}
})();
window._mdPvSetTheme = (t, persist) => {
  _mdPvTheme = t;
  document.querySelectorAll('.ed-md-preview').forEach(_mdPvApplyTheme);
  // 同步所有工具栏下拉
  document.querySelectorAll('[data-ed-mdtheme]').forEach(sel => { sel.value = t; });
  if (persist !== false) {
    try { fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ md_preview_theme: t }) }); } catch (_) {}
  }
};
function _mdRenderPreview(conn) {
  const pv = conn.wrap.querySelector('.ed-md-preview');
  if (!pv) return;
  _mdPvApplyTheme(pv);   // a279：每次渲染同步主题类
  _mdBindPvScroll(conn, pv);   // 预览自身滚动 → 源码跟随（只绑一次）
  const src = conn.monaco ? conn.monaco.getValue() : (conn.ta ? conn.ta.value : '');
  const ps = pv.scrollTop, psL = pv.scrollLeft;   // 重建前的位置：重建后还原，避免预览跳回顶部
  // 源文本无变化则纯还原滚动（拖分隔条/切大纲都走这里渲染，不该丢阅读位置）
  if (conn._mdLastSrc === src && pv.firstChild) {
    pv.scrollTop = ps; pv.scrollLeft = psL;
    return;
  }
  const md = _mdInstance();
  if (!md) { pv.innerHTML = '<div class="md-preview-err">markdown-it 未加载（vendor/markdown-it 缺失）</div>'; return; }
  // 高亮是异步的、图片又无固有尺寸——两者落地都会改变布局，故分两步：
  // 先只放一行占位（同步返回，输入不卡），下一帧再贴正文并校准滚动
  // 上一版已高亮的代码块：源码 → 高亮后的 HTML。重建后源码没变的块直接贴回结果。
  // 原实现把整页 HTML 合成一串再去比单块，永远不相等，等于每次按键全量重高亮。
  const prevHl = new Map();
  pv.querySelectorAll('pre code').forEach(el => { if (el.querySelector('span')) prevHl.set(el.textContent, el.innerHTML); });
  const raw = md.render(src || '');
  conn._mdLastSrc = src;
  const body = [];
  { const t = document.createElement('div'); t.innerHTML = raw; while (t.firstChild) body.push(t.removeChild(t.firstChild)); }
  const cs = getComputedStyle(pv);
  const slots = Math.max(1, (src.match(/\n/g) || []).length + 1);
  const apply = () => {
    if (conn._mdLastSrc !== src) return;   // 已被更新的渲染取代
    pv.innerHTML = '';
    body.forEach(n => pv.appendChild(n));
    // 锚点链接安全：内部相对链接禁跳（工具内无路由），只留外链新开
    pv.querySelectorAll('a[href]').forEach(a => {
      const href = a.getAttribute('href') || '';
      if (!/^https?:/i.test(href)) { a.addEventListener('click', e => e.preventDefault()); a.title = '工具内不支持跳转内部链接'; }
    });
    // v3.5.297：[[双链]] 渲染为可点击链接（notes-nav.js，无 href 不与上方拦截冲突）
    if (typeof nnLinkifyPreview === 'function') { try { nnLinkifyPreview(pv, conn); } catch (_) {} }
    if (typeof hljs !== 'undefined' && hljs.highlightElement) {
      pv.querySelectorAll('pre code').forEach(el => {
        const hit = prevHl.get(el.textContent);
        if (hit != null) { el.innerHTML = hit; return; }   // 该块源码未变，直接贴回上一版高亮
        try { hljs.highlightElement(el); } catch(_) {}
      });
    }
    _mdPinBlockImages(pv);   // 图片无固有尺寸：按源码宽高比补占位框，免得读图后整页位移
    // 内容高度变了，这一帧的同步必须放行（否则会被刚发生的按键同步的静默期挡掉）
    conn._mdSyncAt = 0;
    _mdSyncScroll(conn);
    requestAnimationFrame(() => { conn._mdSyncAt = 0; _mdSyncScroll(conn); });   // 图片/高亮落地后二次校准
  };
  // 只有大文档才值得插占位等一帧（重排代价高，先给个接近的高度免得滚动位跳）；
  // 小文档直接同步贴正文——原来每键都清空闪一次「渲染中…」，输入观感很差。
  if (slots > 400) {
    const ph = document.createElement('div');
    ph.className = 'md-preview-ph';
    ph.textContent = '渲染中…';
    pv.innerHTML = '';
    pv.appendChild(ph);
    const need = Math.min(1.6, slots * (parseFloat(cs.lineHeight) || 21.5) / Math.max(1, pv.clientHeight));
    if (need > 1 && pv.clientHeight) ph.style.minHeight = Math.round(pv.clientHeight * need - 24) + 'px';
    setTimeout(apply, 0);
  } else {
    apply();
  }
}

// ---- 图片占位：解码前按 width/height 属性或 alt 里 NxN 尺寸补 aspect-ratio ----
// 设备截图/寄存器图常带尺寸标注；无尺寸的按 16:9 估，解码后自然尺寸接管（不影响最终显示）
function _mdPinBlockImages(root) {
  root.querySelectorAll('img').forEach(img => {
    if (img.closest('a')) return;
    let w = parseFloat(img.getAttribute('width')) || 0;
    let h = parseFloat(img.getAttribute('height')) || 0;
    if (!w || !h) {
      const m = /(\d{2,4})\s*[x×*]\s*(\d{2,4})/.exec(img.getAttribute('alt') || '');
      if (m) { w = +m[1]; h = +m[2]; }
    }
    img.style.aspectRatio = (w && h) ? (w + ' / ' + h) : '16 / 9';
    img.style.objectFit = 'contain';
  });
}

// ---- 源码↔预览滚动同步（双向防回环）----
// 锚点：源码标题行号（Monaco 行号 / textarea 行号）↔ 预览里对应标题元素，
// 行号由 _mdInstance 给 heading_open 挂的 data-md-line 提供。锚点区间内线性插值，平滑不跳。
//
// 两条硬约束（原实现都踩了）：
// 1) 位置一律用「相对预览内容顶（含 padding）」的坐标：anchor.offsetTop 依赖
//    offsetParent，而 .ed-md-preview / .ed-main 都没有 position，offsetParent 会跑到
//    更外层，算出来根本不是滚动容器的坐标 → 直接换成 clientHeight/scrollTop 自洽的算式。
// 2) 防回环只在「程序化滚动后的极短窗口」内生效，且两个方向共用同一个窗口时间戳；
//    原实现把 240ms 的静默期写在同步入口，用户连续滚源码时 240ms 内的滚动全被丢弃，
//    预览只有 ~4 次/秒 → 这就是「一点不流畅」的来源。
const _MD_SYNC_GUARD = 80;    // ms：程序化滚动后忽略反向回传的窗口，只够挡住回声，不挡用户手势
let _mdRaf = 0;               // rAF 节流句柄：源码滚动每帧最多同步一次

// 预览的 padding-top：内容偏移 A（相对内容顶）落到视口顶时，scrollTop = A + pt
function _mdPvPad(pv) { return parseFloat(getComputedStyle(pv).paddingTop) || 0; }
// 锚点的内容偏移：相对「预览内容顶（padding 边）」的距离，与 scrollTop 同一坐标系
function _mdAnchorTop(a, pv, pt) {
  return a.getBoundingClientRect().top - pv.getBoundingClientRect().top + pv.scrollTop - pt;
}
function _mdSyncScroll(conn) {
  const pv = conn.wrap.querySelector('.ed-md-preview');
  if (!pv) return;
  if (conn._mdSyncAt && Date.now() - conn._mdSyncAt < _MD_SYNC_GUARD) return;   // 预览刚被程序化滚动，勿回灌
  const top = _mdSrcScrollTop(conn);
  if (top == null) return;
  const anchors = pv.querySelectorAll('[data-md-line]');
  const pt = _mdPvPad(pv);
  const max = Math.max(0, pv.scrollHeight - pv.clientHeight);
  let want;
  if (anchors.length) {
    const line = _mdSrcLineAtTop(conn, top);
    // 包住当前行的区间：lo = 最后一个不晚于 line 的锚（缺省「第 1 行 / 预览顶部」）
    let lo = 1, loY = 0, hi = line, hiY = pv.scrollHeight;
    for (const a of anchors) {
      const l = +a.dataset.mdLine;
      const y = _mdAnchorTop(a, pv, pt);
      if (l <= line) { lo = l; loY = y; }
      else { hi = l; hiY = y; break; }
    }
    const span = hi - lo;
    const off = span > 0 ? loY + (hiY - loY) * ((line - lo) / span) : loY;
    want = off + pt;   // 内容偏移 → scrollTop
  } else {
    // 无标题文档：无锚点可插值，按「两边总高之比」等比映射，至少不会一滚就到底
    const sh = _mdSrcScrollHeight(conn);
    want = (sh > 0 ? top / sh : 0) * max;
  }
  const next = Math.max(0, Math.min(want, max));
  if (Math.abs(pv.scrollTop - next) > 0.5) pv.scrollTop = next;
  conn._mdSyncAt = Date.now();
}
// 源码可见区顶部对应行号。
// Monaco 直接问可见范围（第一行），比「行高 × 行号」准——wordWrap 开着时
// 长行占多个视觉行，按行高估会一路累积偏差，滚到文档后半段就越同步越歪。
function _mdSrcLineAtTop(conn, top) {
  if (conn.monaco) {
    try {
      const r = conn.monaco.getVisibleRanges();
      if (r && r.length && r[0].startLineNumber) return r[0].startLineNumber;
    } catch(_) {}
    try { return top / (conn.monaco.getOption(monaco.editor.EditorOption.lineHeight) || 19) + 1; } catch(_) {}
  }
  return top / _mdLineHeight(conn) + 1;
}
function _mdSrcScrollTop(conn) {
  if (conn.monaco) { try { return conn.monaco.getScrollTop(); } catch(_) { return null; } }
  if (conn.ta) return conn.ta.scrollTop;
  return null;
}
function _mdSrcScrollHeight(conn) {
  if (conn.monaco) { try { return conn.monaco.getScrollHeight(); } catch(_) { return 0; } }
  if (conn.ta) return conn.ta.scrollHeight;
  return 0;
}
// textarea 行高：从 computed style 实读（字体/缩放随设置变），只量一次
function _mdLineHeight(conn) {
  if (conn._mdLh) return conn._mdLh;
  let lh = 19;
  try {
    const cs = getComputedStyle(conn.ta);
    lh = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.5) || 19;
  } catch(_) {}
  return (conn._mdLh = lh);
}
// 预览 → 源码：连续插值跟随（v2.25 重写）。旧实现「吸附最近标题行」——
// 锚点之间/尾部区间全靠猜，预览拉到底源码还差十几行（用户实测「已经拉到
// 底部了」源码没跟上）。现在与「源码→预览」对称：找包住预览视口顶的锚
// 区间，按比例插值源码 scrollTop；区间端点天然对齐（预览顶=源码顶、
// 预览底=源码底），到底/到顶严格同步。
function _mdSrcViewportH(conn) {
  if (conn.monaco) { try { return conn.monaco.getDomNode().clientHeight || 300; } catch(_) { return 300; } }
  return conn.ta ? conn.ta.clientHeight : 300;
}
function _mdSrcTotalLines(conn) {
  if (conn.monaco) { try { return conn.monaco.getModel().getLineCount(); } catch(_) { return 1; } }
  return conn.ta ? (conn.ta.value.split('\n').length || 1) : 1;
}
function _mdSyncFromPv(conn, pv) {
  const anchors = Array.from(pv.querySelectorAll('[data-md-line]'));
  const pt = _mdPvPad(pv);
  const pvTop = pv.scrollTop;
  const srcMax = Math.max(0, _mdSrcScrollHeight(conn) - _mdSrcViewportH(conn));
  const lh = conn.monaco
    ? (function () { try { return conn.monaco.getOption(monaco.editor.EditorOption.lineHeight) || 19; } catch(_) { return 19; } })()
    : _mdLineHeight(conn);
  // v2.25 关键修：Monaco 开 wordWrap 时「逻辑行 × 行高」与实际 y 系统性偏差
  // （长段落折成多个视觉行，越往后偏得越多——预览 85% 源码 55% 即此）。
  // getTopForLineNumber 返回折行后的真实 y，必须用它。
  const srcYof = (ln) => {
    if (conn.monaco) {
      try { const y = conn.monaco.getTopForLineNumber(Math.max(1, ln)); if (typeof y === 'number' && isFinite(y)) return y; } catch(_) {}
    }
    return (ln - 1) * lh;
  };
  let srcWant;
  if (anchors.length) {
    // 包住预览视口顶的锚区间；无下锚=文档顶（y=0,行1），无上锚=文档底
    let loLine = 1, loY = 0, hiLine = null, hiY = 0;
    for (const a of anchors) {
      const y = _mdAnchorTop(a, pv, pt);
      if (y <= pvTop - pt) { loLine = +a.dataset.mdLine; loY = y; }
      else { hiLine = +a.dataset.mdLine; hiY = y; break; }
    }
    let loSrc = srcYof(loLine), hiSrc, hiYv;
    if (hiLine == null) {
      hiLine = _mdSrcTotalLines(conn);
      hiSrc = srcMax;
      hiYv = Math.max(0, pv.scrollHeight - pv.clientHeight - pt);
    } else {
      hiSrc = srcYof(hiLine); hiYv = hiY;
    }
    const spanY = hiYv - loY;
    const ratio = spanY > 0 ? Math.max(0, Math.min(1, (pvTop - pt - loY) / spanY)) : 0;
    srcWant = loSrc + (hiSrc - loSrc) * ratio;
  } else {
    const pvMax = Math.max(0, pv.scrollHeight - pv.clientHeight);
    srcWant = pvMax > 0 ? (pvTop / pvMax) * srcMax : 0;
  }
  if (conn.monaco) { try { conn.monaco.setScrollTop(Math.max(0, srcWant)); } catch(_) {} }
  else if (conn.ta) conn.ta.scrollTop = Math.max(0, srcWant);
}
// 预览 → 源码：在预览里滚动，源码跟到对应位置（看图想改源码的自然诉求）
function _mdBindPvScroll(conn, pv) {
  if (conn._mdPvBound) return;
  conn._mdPvBound = true;
  let raf = 0;
  pv.addEventListener('scroll', () => {
    if (conn._mdSyncAt && Date.now() - conn._mdSyncAt < _MD_SYNC_GUARD) return;   // 程序化滚动回传，忽略
    if (raf) return;   // 每帧最多定位一次，连续滚动不刷 Monaco
    raf = requestAnimationFrame(() => {
      raf = 0;
      conn._mdPvDriven = Date.now();   // v2.25：标方向——下面的源码滚动是预览引起的，禁止回灌预览
      _mdSyncFromPv(conn, pv);
    });
  }, { passive: true });
}


// .log 特殊：小文件（<20MB）也进编辑器可编辑；超限后端报错自动回落只读查看器。
// ---- 拖放文件分发：文本类后缀 → 编辑器（可编辑）；其余 → 日志查看器（只读）----
// 后缀白名单与后端 _EXT_TEXT 保持同步（.pyw 等曾漏——手列白名单补齐）
const _DROP_TEXT_EXT = new Set(['.txt','.note','.md','.json','.csv','.ini','.cfg','.conf','.yaml','.yml',
  '.c','.h','.cpp','.hpp','.py','.bat','.cmd','.sh','.ps1','.js','.ts','.html','.css','.xml','.sql',
  '.dts','.dtsi','.mak','.mk','.s','.lds','.te','.fc','.log',
  '.pyw','.pyi','.cc','.cxx','.hh','.hxx','.java','.kt','.kts','.rs','.go','.rb','.php','.pl','.lua',
  '.tcl','.awk','.r','.jl','.nim','.zig','.m','.mm','.cs','.vb','.fs','.fsx','.scala','.groovy','.swift','.dart',
  '.v','.sv','.svh','.vhd','.vhdl','.asm','.sln','.props','.targets','.gradle','.properties','.toml','.proto',
  '.tf','.tfvars','.graphql','.gql','.ipynb','.nix','.editorconfig','.gitignore','.gitattributes','.npmrc',
  '.bashrc','.zshrc','.profile','.dockerignore']);
// ---- 文件打开方式选择弹窗（20~30M 提示用；小于 20M 用户主动选阅读器也复用）----
// mode: 'ask' 弹窗让选（含二进制选项）；'edit' 直接编辑器；'view' 直接阅读器；'hex' 直接二进制
// a242：大小显示复用全局 _fmtSize（tftp.js 定义，加载序在后覆盖同名）——
// GB 档已在 tftp.js 侧补齐，此处不再重复定义
function _showOpenModeDialog(path, sizeBytes, withHex, why) {
  return new Promise(resolve => {
    let m = $('openModeModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'openModeModal';
      m.innerHTML = `
        <div class="box" style="max-width:420px;">
          <div class="head"><strong id="openModeTitle">选择打开方式</strong>
            <div class="head-actions"><button class="btn ghost icon-btn" id="openModeClose">✕</button></div>
          </div>
          <div style="padding:18px 20px;">
            <div id="openModeDesc" style="color:var(--muted);font-size:12px;line-height:1.6;margin-bottom:16px;word-break:break-all;"></div>
            <div style="display:flex;flex-direction:column;gap:10px;">
              <button class="btn" id="openModeHex" style="padding:10px 14px;text-align:left;justify-content:flex-start;">
                ${ICO16.hex} 二进制打开<small style="color:var(--muted);font-weight:400;">　16 进制查看/编辑（任意文件）</small>
              </button>
              <button class="btn" id="openModeView" style="padding:10px 14px;text-align:left;justify-content:flex-start;">
                ${ICO16.book} 阅读器打开<small style="color:var(--muted);font-weight:400;">　虚拟列表，大文件流畅（只读+搜索）</small>
              </button>
              <button class="btn" id="openModeEdit" style="padding:10px 14px;text-align:left;justify-content:flex-start;">
                ${ICO16.pencil} 编辑器打开<small style="color:var(--muted);font-weight:400;">　Monaco，可编辑保存</small>
              </button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(m);
      m.querySelector('#openModeClose').onclick = () => { m.classList.remove('show'); resolve(null); };
    }
    const finish = v => { m.classList.remove('show'); resolve(v); };
    m.querySelector('#openModeEdit').onclick = () => finish('edit');
    m.querySelector('#openModeView').onclick = () => finish('view');
    m.querySelector('#openModeHex').onclick = () => finish('hex');
    m.querySelector('#openModeHex').style.display = withHex ? '' : 'none';   // 仅未知/二进制类型显示二进制选项
    m.querySelector('#openModeDesc').textContent =
      `${path}${sizeBytes != null ? `（${_fmtSize(sizeBytes)}）` : ''}\n` +
      (sizeBytes != null && sizeBytes > 20 * 1024 * 1024
        ? '文件超过 20MB：编辑器打开可能卡顿（Monaco 分词内存约为文件 3~5 倍），建议用阅读器。'
        : (why === 'mixed'
            ? '文件里既有可读文本，也有不少无法识别的字节（常见于串口抓的日志、被截断的文件）。用编辑器打开可能看到零星乱码，保存会原样写回；用十六进制可逐字节核对。'
            : (why === 'binary'
                ? '检测到大量无法识别的字节，多半是二进制文件。编辑器打开通常会显示乱码，脚本/文档类文件反而可能是编码问题——按需要选。'
                : (withHex ? '未知类型文件，选择打开方式：' : '选择打开方式：'))));
    m.classList.add('show');
  });
}

// ============================================================
// v3.5.302 .note 撤销/重做（自研轻量快照栈）
// Editor.js 核心不含 undo，官方 editorjs-undo 插件未 vendor 化=Ctrl+Z 从来
// 无效（DevTools 构造复证实锤）。快照栈方案：onChange → 400ms 去抖存
// editor.save() 全量快照（上限 100，覆盖打字/粘贴/回车/工具栏块操作全部
// 变更源）；Ctrl+Z / Ctrl+Y|Ctrl+Shift+Z 在 holder 捕获期接管（preventDefault
// 压掉 contenteditable 的半残原生栈，块级操作原生栈本就会断）；恢复走
// blocks.render 全量重渲，恢复态与栈顶相同不重复压栈（render 触发的
// onChange 被busy 标志+同串比对双保险跳过）。
// v3.5.306（designer 补档风险1实锤）：本函数曾被误插进 openFileSmart 函数体
// 内部=顶层 typeof 检查恒 false=落盘版死代码（热注入验证掩盖作用域错误）——
// 上提到文件顶层，教训：插入位置必须核对外层函数边界
// ============================================================
function _edUndoInit(conn) {
  if (!conn.editor || conn._edUndo) return;
  const st = { stack: [], idx: -1, busy: false, timer: null };
  conn._edUndo = st;
  const snap = async () => {
    if (st.busy) return;
    try {
      const data = await conn.editor.save();
      const json = JSON.stringify((data && data.blocks) || []);
      if (st.stack[st.idx] === json) return;             // 无变化不压栈
      st.stack = st.stack.slice(0, st.idx + 1);          // 截断 redo 分支
      st.stack.push(json);
      if (st.stack.length > 100) st.stack.shift();
      st.idx = st.stack.length - 1;
    } catch (_) {}
  };
  conn._edUndoHook = () => { clearTimeout(st.timer); st.timer = setTimeout(snap, 400); };
  const apply = async dir => {
    // v3.5.308（全审F11b）：冲刷 400ms 去抖 pending——打字后 400ms 内按
    // Ctrl+Z，把当前内容立即入栈再退，否则最近输入丢失且无 redo
    if (st.timer) { clearTimeout(st.timer); st.timer = null; await snap(); }
    const ni = st.idx + dir;
    if (ni < 0 || ni >= st.stack.length) return;         // 到栈底/顶
    st.idx = ni;
    st.busy = true;                                      // render 触发的 onChange 不入栈
    try {
      let blocks = [];
      try { blocks = JSON.parse(st.stack[ni]) || []; } catch (_) { blocks = []; }
      await conn.editor.blocks.render({ blocks });
    } catch (_) {}
    st.busy = false;
  };
  conn.holder.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey)) return;
    // v3.5.308（全审F11a）：行内工具条输入框（链接 URL 等）焦点在 INPUT/
    // TEXTAREA——放行其原生撤销，不整机回滚块
    const tg = e.target;
    if (tg && (tg.tagName === 'INPUT' || tg.tagName === 'TEXTAREA')) return;
    const k = (e.key || '').toLowerCase();
    if (k === 'z' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); apply(-1); }
    else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); e.stopPropagation(); apply(1); }
  }, true);
  snap();                                                // 初始快照（undo 底）
}

// ---- 统一文件打开入口（拖拽/最近/顶栏打开 共用）----
// mode: 'auto'（默认按大小规则）| 'edit' | 'view' | 'hex'
// 规则：未知/二进制类型 → 弹窗让选（二进制/阅读器/编辑器）；
//       已知文本：<20M 编辑器；20~30M 弹窗提示选（默认建议阅读器）；>30M 强制阅读器。
// a209批1：第三参 opts（可选，6 个既有调用点零感知）：{line, col}——打开后落点
// 到指定行列（文件树搜索跳转/树 reveal 用）。Monaco revealLineNearTop +
// setPosition 语义与 notes-nav nnJumpLine 同源（4 处先例）；col 缺省 1
async function openFileSmart(path, mode, opts) {
  if (typeof path !== 'string' || !path) return;   // a239 B4-P3: null/undefined 原在 .split 抛未捕获 rejection
  const jump = (conn, o) => {
    // a213 审计 P1：新开分支 buildEditorTab 同步返回时 monaco 尚未创建
    // （_edInitContent 异步）——原实现恒 no-op。轮询等待就绪（80ms 步进，
    // 3s 兜底——与 notes-nav nnOpenAndJump 同思路）
    if (!conn || !o || !o.line || conn.isNote) return;   // .note 无 monaco，白轮 3s
    const t0 = Date.now();
    const tryJump = () => {
      const m = conn.monaco;
      if (m && m.revealLineNearTop) {
        try {
          m.revealLineNearTop(o.line);
          m.setPosition({ lineNumber: o.line, column: o.col || 1 });
          // a365（用户实锤：跳转后看不到落点）：selectLine=true 时整行选中
          // 高亮——跳转/引用点击后第一眼可见（VSCode 同款）
          if (o.selectLine) {
            try {
              const len = m.getModel().getLineMaxColumn(o.line);
              m.setSelection({ startLineNumber: o.line, startColumn: 1,
                              endLineNumber: o.line, endColumn: len });
            } catch (_) {}
          }
          try { m.focus(); } catch (_) {}
        } catch (_) {}
        return;
      }
      // a231 审计 P3：conn.isConnected 从未被赋值（恒真死代码）——改按
      // connections 注册表存活性判（关 tab 即停轮询）
      if (Date.now() - t0 < 3000 && connections[conn.portId] === conn) setTimeout(tryJump, 80);
    };
    tryJump();
  };
  const name = path.split(/[\/]/).pop().toLowerCase();
  const dot = name.lastIndexOf('.');
  const ext = dot > 0 ? name.slice(dot) : name;
  // a280→a281R：Office 文件分发——先同步判扩展名（_officeKindOf 返回非空
  // 才是 Office 文件），再调 async 的 openOfficeFile。原写法直接调
  // openOfficeFile(path) 当同步用——async 函数返回 Promise 恒真，导致
  // 所有文件都被拦截、编辑器路径永远不可达（用户实锤 .md 都打不开）
  if (typeof _officeKindOf === 'function' && _officeKindOf(path)) {
    openOfficeFile(path);   // async，自己管 tab 创建，不需要 await
    return;
  }
  const isText = _DROP_TEXT_EXT.has(ext) || name === 'makefile' || name === 'readme';
  // 探测大小与内容分级（失败按 0/未知处理走编辑器尝试）
  let size = 0, isTextSrv = isText, kindSrv = '';
  try {
    const r = await fetch('/api/file_info', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    const j = await r.json();
    if (j.ok) { size = j.size; isTextSrv = j.is_text; kindSrv = j.kind || ''; }
  } catch(e) {}
  const MB = size / 1024 / 1024;
  // a357R（用户定调）：打开方式的选择权交给用户。
  //   text   → 直接进编辑器（少量坏字节不影响阅读）
  //   mixed  → 弹窗让用户选（可识别与不可识别都不少，猜不准就别替用户猜）
  //   binary → 默认十六进制，但弹窗仍给阅读器/编辑器（结构文件除外）
  let how = mode || 'auto';
  if (how === 'auto') {
    if (kindSrv === 'mixed') how = await _showOpenModeDialog(path, size || null, true, 'mixed');
    else if (kindSrv === 'binary' || !isTextSrv) {
      how = await _showOpenModeDialog(path, size || null, true, 'binary');
    }
    else if (MB > 30) how = 'view';                        // >30M 强制阅读器（Monaco 必卡）
    else if (MB > 20) how = await _showOpenModeDialog(path, size, false);  // 20~30M 提示选
    else how = 'edit';                                     // <20M 默认编辑器
    if (!how) return;                                      // 用户关掉了弹窗
  }

  if (how === 'hex') { buildHexViewerTab(path, name); return; }
  if (how === 'view') { buildLogViewer(path, opts && opts.line); return; }   // R28-5：行号透传
  // edit：未知类型用户硬选编辑器——超 20M 后端会拒（大小前提由后端硬上限兜底），拒则降级
  try {
    // force=1：无后缀/未知类型按内容探测放行（去后缀的 json 等曾直接被白名单拒）
    const r = await fetch('/api/ed/open?force=1&path=' + encodeURIComponent(path));
    const j = await r.json();
    if (j.ok) {
      window._edLastUsedEnc = j.used_enc || null;
      if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+j.name, label:j.name, data:{kind:'edit', name:j.name, path:path, extPath: path}});
      const _c = buildEditorTab(j.name, j.text, path, j.mtime || null);
      if (_c) {
        _c.usedEnc = j.used_enc || null;
        // a372：去重分支拿到的是已打开 tab（内容可能是旧版）——跳前校验
        // 磁盘 mtime，不 dirty 先重读（行号=磁盘新版口径，落点才对得上）
        await _edJumpFresh(_c);
        jump(_c, opts);   // 新开即跳；去重分支（switchTab 已返回 conn）同跳
      }
      return;
    }
    // 后端仍拒（真二进制/超限/不存在）：二进制改切 hex（阅读器看乱码没意义），其余降级阅读器
    if (j.err && /类型|二进制/.test(j.err)) {
      showBanner('该文件是二进制（含 NUL 字节），已切换 16 进制查看器', 4000, true);
      buildHexViewerTab(path, name);
      return;
    }
    showBanner('编辑器无法打开（' + (j.err || '未知错误') + '），已切换阅读器', 4000, true);
  } catch(e) { showBanner('打开失败: ' + e, 4000, true); return; }
  buildLogViewer(path, opts && opts.line);   // R28-5：降级阅读器同款行号透传
}

// v3.5.76（拖附件 4s+ 根修）：pywebview 的 on('drop') 只注册 drop 不取消
// dragover——按 HTML 规范 dragover 未被 preventDefault 则页面不是合法落点，
// drop 事件不会正常触发；WebView2 宿主只能按导航消化 OS 拖放、拖放会话超时
// 后才回灌 web 内容 = 4~12s 变长延迟。这里全局取消 Files 类 dragover（文本
// 内部拖拽不受影响），页面即时成为合法落点，drop 毫秒级派发——ZCode/Electron
// 同理（renderer 有 dragover 处理，宿主不抢拖放）。配套取消 Files 类 drop 的
// 默认行为（防浏览器把落点文件当导航目标）
['dragover', 'drop'].forEach(evt => {
  window.addEventListener(evt, e => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files'))
      e.preventDefault();
  }, true);
});
// v3.5.76：拖拽计时探针（右上角浮层，20s 自隐）——html-drop→py-drop→js→done
// 各跳时刻，一屏定位延迟段。v3.5.78（用户要求「只有 debug 打开才显示」）：
// 默认 no-op；开启=URL 带 ?debug 或 localStorage hg-dbg=1。
// v3.5.79：①Ctrl+Shift+D 随时切换 debug（banner 反馈）②慢拖（全程>1.5s）
// 自动现形——健康时永远不弹，出问题自带证据（各跳时刻自动上屏）
const __dragProbeShow = (tag) => {
  try {
    let el = document.getElementById('__dragProbe');
    if (!el) {
      el = document.createElement('div');
      el.id = '__dragProbe';
      el.style.cssText = 'position:fixed;top:8px;right:8px;z-index:99999;background:rgba(0,0,0,.85);color:#7fd1ff;font:11px/1.6 Consolas,monospace;padding:6px 10px;border-radius:6px;pointer-events:none;white-space:pre';
      document.body.appendChild(el);
    }
    el.textContent += (el.textContent ? '\n' : '') + tag + '  ' + new Date().toLocaleTimeString('en-GB', { hour12: false });
    clearTimeout(window.__dragProbeT);
    window.__dragProbeT = setTimeout(() => el.remove(), 20000);
  } catch (_) {}
};
window.__dragDbg = (function () {
  try { return localStorage.getItem('hg-dbg') === '1' || /[?&]debug/.test(location.search); }
  catch (_) { return false; }
})();
window.__dragProbe = () => {};
function __dragProbeSync() { window.__dragProbe = window.__dragDbg ? __dragProbeShow : function () {}; }
__dragProbeSync();
window.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
    try { localStorage.setItem('hg-dbg', window.__dragDbg ? '0' : '1'); } catch (_) {}
    window.__dragDbg = !window.__dragDbg;
    __dragProbeSync();
    if (typeof showBanner === 'function') showBanner(window.__dragDbg ? '拖拽计时探针：已开启' : '拖拽计时探针：已关闭', 2000);
  }
});
window.addEventListener('drop', () => { window.__dragT0 = Date.now(); window.__dragProbe && __dragProbe('html-drop'); }, true);
// v3.5.73：原生拖拽多文件入口（main.py 全量透传）——harness 活动时全部
// 加为对话附件（用户拖 5 个文件就该进 5 个附件）；其余 tab 保持首文件行为
// （编辑器/阅读器一次开一个是合理交互），旧码在 Python 侧 break 只发第一个
async function openDroppedFiles(paths) {
  if (!Array.isArray(paths) || !paths.length) return;
  // v3.5.85：双发去重（快通道+兜底慢路万一并发）——同路径清单 2s 内只处理
  // 一次（对齐单文件时代 openDroppedFile._last 的既有语义）
  const _sig = paths.slice().sort().join('\u0001');
  const _now = Date.now();
  if (openDroppedFiles._last && openDroppedFiles._last.s === _sig && _now - openDroppedFiles._last.t < 2000) return;
  openDroppedFiles._last = { s: _sig, t: _now };
  window.__dragProbe && __dragProbe('js-recv ' + paths.length + '个');
  // 对比弹窗优先（对齐 openDroppedFile 既有语义，v3.5.73 建多文件通道时
  // 漏抄此分支）：弹窗在开，拖入文件填 A/B 栏——否则下一行 harness 判定
  // 抢跑，claude 会话活动时拖对比文件会被整组挂成对话附件（用户实锤）
  const dm = typeof $ === 'function' && $('diffPickModal');
  if (dm && dm.classList.contains('show') && typeof window._diffPickDrop === 'function') {
    for (const p of paths.slice(0, 2)) window._diffPickDrop(p);   // 依次填 A/B，多出的丢弃
    return;
  }
  const harnessActive = activePortId && connections[activePortId] &&
    connections[activePortId].meta && connections[activePortId].meta.kind === 'harness';
  if (harnessActive && typeof window.harnessAddFilesByPath === 'function') {
    await window.harnessAddFilesByPath(paths);
    window.__dragProbe && __dragProbe('atts-done');
    // v3.5.79：慢拖自动现形（非 debug 也不吞证据）——html-drop→完成超 1.5s
    // 强制上屏，各跳时刻可见即定位延迟段
    const _d = Date.now() - (window.__dragT0 || Date.now());
    if (_d > 1500) __dragProbeShow('⚠ 慢拖 ' + (_d / 1000).toFixed(1) + 's（drop→完成）');
    return;
  }
  return openDroppedFile(paths[0], false);
}
async function openDroppedFile(path, fromRecent) {
  // v2.24：双拖放通道去重（.NET 原生 DragDrop 即时 + pywebview 兜底延迟
  // ~12s 可能先后到达）——同路径 2s 内只处理一次
  const _now = Date.now();
  if (openDroppedFile._last && openDroppedFile._last.p === path && _now - openDroppedFile._last.t < 2000)
    return;
  openDroppedFile._last = { p: path, t: _now };
  // 对比弹窗开着：拖入的文件填 A/B 栏（不打开、不灌 claude/笔记）。
  // drop_handler 只回调这里（唯一原生路径通道），弹窗在开就归它。
  const dm = typeof $ === 'function' && $('diffPickModal');
  if (dm && dm.classList.contains('show') && typeof window._diffPickDrop === 'function') {
    if (window._diffPickDrop(path)) return;
  }
  // 拖入的是【文件夹】：设为文件树根（不弹打开方式——之前对目录弹的
  // "选择打开方式"三种全失败）。is_dir 由 /api/file_info 探测，目录名
  // 任意后缀不影响判定（isdir 是唯一判据）。
  try {
    const r = await fetch('/api/file_info', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    const j = await r.json();
    if (j.ok && j.is_dir && typeof addTreeRoot === 'function') {
      if (await addTreeRoot(path)) showBanner('已添加到文件树: ' + path, 3000);
      return;
    }
  } catch(_) {}   // 探测失败（网络等）继续走文件链路
  // 拖到程序员计算器 tab 上的文件：当前活动 tab 是计算器 → 直接算哈希
  // （计算器内 hashBox 的 drop 只做视觉高亮；真实路径只有这个全局通道有）
  if (!fromRecent && activePortId && connections[activePortId] &&
      connections[activePortId].meta && connections[activePortId].meta.kind === 'bitcalc' &&
      typeof connections[activePortId].hashFile === 'function') {
    connections[activePortId].hashFile(path);
    return;
  }
  // 拖到 claude 终端 tab 上的文件：claude 输入框不吃原生拖拽，直接把路径
  // 当文本"打字"进终端（termSendRaw 走 /api/send_raw，claude 收到路径字符串
  // 就能读文件——图片也能识图）。用户正对着 claude tab 拖，意图明确，不该弹打开方式。
  // fromRecent=true（「最近」快捷打开）时跳过：点快捷项的意图是打开文件本身，
  // 若当前活动 tab 恰好是 claude 会话，路径会被灌进对话输入框（"被 claude 拦截"）。
  if (!fromRecent && activePortId && connections[activePortId] &&
      connections[activePortId].meta && connections[activePortId].meta.kind === 'claude') {
    const safe = path.replace(/\\/g, '/');
    for (let i = 0; i < safe.length; i++) {
      const code = safe.charCodeAt(i);
      if (code < 128) termSendRaw(activePortId, [code]);
      else { for (const b of new TextEncoder().encode(safe[i])) termSendRaw(activePortId, [b]); }
    }
    showBanner('已把路径发给 Claude（回车确认发送）', 3000);
    return;
  }
  // v2.2.1：拖到 Claude 对话 tab（界面化 harness）上的文件 → 直接作为对话
  // 附件（发送时随消息带上，Claude Read 原路径）。此前只有 CLI 终端 tab 有
  // 分支，harness tab 拖文件掉到 openFileSmart 变"打开文件"（用户实锤回归：
  // 最开始拖进对话就是给 claude 的）。fromRecent=true 同上跳过。
  if (!fromRecent && activePortId && connections[activePortId] &&
      connections[activePortId].meta && connections[activePortId].meta.kind === 'harness' &&
      typeof window.harnessAddFilesByPath === 'function') {
    window.harnessAddFilesByPath([path]);
    return;
  }
  // 拖到笔记 tab（.note，Editor.js 在场）：图片直接作为图块插入——
  // 与 note 内部粘贴图同款体验（上传 files/images/ 后插 image 块），
  // 不弹"打开方式"。
  if (activePortId && connections[activePortId] &&
      connections[activePortId].meta && connections[activePortId].meta.kind === 'editor') {
    const c = connections[activePortId];
    if (c.isNote && c.editor) {   // .note 的 Editor.js 实例（.txt 是 Monaco 不走这）
      const ext = (path.split('.').pop() || '').toLowerCase();
      if (['png','jpg','jpeg','gif','webp','bmp'].includes(ext)) {
        try {
          const j = await _edInsertImageFromPath(path);
          if (j) return;
        } catch(_) {}
      }
    }
  }
  openFileSmart(path, 'auto');
}

// 从磁盘绝对路径把图片插进当前 .note：fetch 转 Blob → 走 /api/ed/upload_img
// （复用既有上传链：魔数校验 + 落盘 files/images/），成功后插 image 块到编辑器尾部。
async function _edInsertImageFromPath(path) {
  let blob;
  try {
    const r = await fetch('file:///' + path.replace(/\\/g, '/'));
    blob = await r.blob();
  } catch(_) {
    // WebView2 拦 file:// → 经后端中转
    const j2 = await (await fetch('/api/ed/proxy_img', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})})).json();
    if (!j2.ok) { showBanner('读取图片失败：' + (j2.err || path), 4000, true); return true; }
    blob = await (await fetch('/api/ed/img/' + j2.url.split('/').pop())).blob();   // a238 P2-7：原 img_data 路由不存在（404 JSON 被当 Blob 上传→魔数必拒→拖图恒失败），正确路由是 /api/ed/img/
  }
  const ext = (path.split('.').pop() || '').toLowerCase();
  const file = new File([blob], 'img.' + ext, {type: 'image/' + (ext === 'jpg' ? 'jpeg' : ext)});
  const up = await _edUploadImage(file);
  if (!up.success) { showBanner('图片插入失败', 3000, true); return true; }
  const c = connections[activePortId];
  const index = c.editor.blocks.getBlocksCount();
  c.editor.blocks.insert('image', { file: { url: up.file.url } }, undefined, index, false);
  return true;
}

// ---- 顶栏「📂 打开」：原生文件选择框（pywebview 桥 pick_any），选中后智能分发 ----
// 非 pywebview 环境（纯浏览器调试）降级 input[type=file]，但拿不到绝对路径，
// 只能走 FileReader 临时内容——此处直接提示不支持。
const btnOpen = $('btnOpenFile');
if (btnOpen) {
  btnOpen.onclick = async () => {
    try {
      const path = await pywebview.api.pick_any();
      if (path && typeof path === 'string') openFileSmart(path, 'auto');
    } catch(e) {
      // pywebview 未就绪（页面刚载入 500ms 内）重试一次
      setTimeout(async () => {
        try {
          const path = await pywebview.api.pick_any();
          if (path && typeof path === 'string') openFileSmart(path, 'auto');
        } catch(_) { showBanner('文件选择器暂不可用，可把文件拖入窗口', 3000, true); }
      }, 600);
    }
  };
}
