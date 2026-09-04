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
function buildEditorTab(name, content, extPath) {
  // content：.note 传 Editor.js JSON 对象；.txt 传字符串；草稿传 null
  // extPath：外部绝对路径（拖入文件）——保存写回原路径，不走 files/ 目录
  const isNote = name ? name.toLowerCase().endsWith('.note') : true;  // 草稿默认 .note
  // 已打开同名文件 → 切过去
  if (name) {
    for (const pid in connections) {
      const c = connections[pid];
      if (c && c.meta && c.meta.kind === 'editor' && c.meta.label === name) {
        switchTab(pid); return;
      }
    }
  }
  const portId = 'edit:' + (name || 'draft') + ':' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led" style="color:var(--accent)">📝</span><span class="label">${esc(name || '未命名')}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
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
        <button class="lv-btn" data-ed-action="save" title="Ctrl+S">💾 保存</button>
        <button class="lv-btn" data-ed-action="saveas" title="Ctrl+Shift+S">另存为…</button>
        <button class="lv-btn" data-ed-action="rename" title="双击标签页标题可快捷改名">重命名</button>
        <button class="lv-btn" data-ed-action="delete">删除</button>
        <button class="lv-btn" data-ed-action="search" title="Ctrl+F 全局搜索（支持正则/排除）">🔍 搜索</button>
        <button class="lv-btn" data-ed-action="outline" title="显示/隐藏右侧大纲面板">☰ 大纲</button>
        <span class="lv-info" data-ed-info></span>
      </div>
      <div class="ed-main">
        <div class="ed-outline" style="display:none;">
          <div class="ed-outline-head">大纲</div>
          <div class="ed-outline-list"></div>
          <div class="ed-outline-stats"></div>
        </div>
        <div class="ed-scroll">
          <div class="ed-holder"></div>
        </div>
        <div class="ed-md-splitter" style="display:none"></div>
        <div class="ed-md-preview" style="display:none;"><div class="md-preview-body"></div></div>
      </div>
      <div class="term-search-pane ed-search-pane" style="display:none">
        <div class="term-search-head">
          <input type="text" class="term-search-input ed-search-q" placeholder="查找…（回车搜索，正则支持）" autocomplete="off">
          <input type="text" class="term-search-exclude ed-search-ex" placeholder="排除（多个用 | 分隔，支持正则）" autocomplete="off">
          <span class="term-search-count ed-search-count"></span>
          <button class="btn ghost term-search-collapse ed-search-collapse" title="折叠分栏">▾</button>
        </div>
        <div class="term-search-results ed-search-results"></div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  termArea.appendChild(wrap);
  const conn = {
    portId,
    meta: { kind: 'editor', label: name || '未命名' },
    tab, wrap,
    holder: wrap.querySelector('.ed-holder'),
    infoEl: wrap.querySelector('[data-ed-info]'),
    outline: wrap.querySelector('.ed-outline'),
    outlineList: wrap.querySelector('.ed-outline-list'),
    outlineStats: wrap.querySelector('.ed-outline-stats'),
    isNote,
    editor: null,         // Editor.js 实例（.note）
    monaco: null,         // Monaco 实例（txt/md/code，_edInitContent 建）
    ta: null,             // textarea（Monaco 失败降级 fallback）
    savedData: null,      // 上次保存/打开的内容（脏检测基准）
    onDisk: !!name,
    dirty: false,
    extPath: extPath || null,  // 外部绝对路径：保存写回原文件，另存为/重命名禁用
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
    const pvBtn = document.createElement('button');
    pvBtn.className = 'lv-btn';
    pvBtn.dataset.edAction = 'mdpreview';
    pvBtn.title = '显示/隐藏 Markdown 预览分栏';
    pvBtn.textContent = '👁 预览';
    wrap.querySelector('[data-ed-action="search"]').after(pvBtn);
    _mdBindSplitter(wrap);
  }
  connections[portId] = conn;
  // 初始化编辑区（异步：Editor.js 实例化）
  _edInitContent(conn, content);
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
      else if (act === 'delete') { if (conn.extPath) showBanner('外部文件不提供删除（请到文件管理器操作）', 3000, true); else edDelete(conn); }
      else if (act === 'outline') edToggleOutline(conn);
    };
  });
  // 快捷键 Ctrl+S / Ctrl+Shift+S：挂 document 全局生效——
  // 之前挂 wrap 上，焦点必须落在编辑区（block 内）keydown 才冒泡到 wrap，
  // 点了工具栏/大纲后按 Ctrl+S 失灵。全局监听只在「当前活动 tab 是本编辑器」时处理。
  document.addEventListener('keydown', e => {
    if (activePortId !== portId) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (e.shiftKey) { if (conn.extPath) showBanner('外部文件不支持另存为（直接保存到原路径）', 3000, true); else edSaveAs(conn); }
      else edSave(conn);
      return;
    }
    // Ctrl+F：编辑器全局搜索分栏（同日志/串口——全局搜索是基础文本能力）
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
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
  });
  switchTab(portId);
  refreshSidebar();
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
        onChange: () => { _edMarkDirty(conn); },
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
        conn.monaco = await monacoCreate(conn.holder, typeof content === 'string' ? content : '', conn.meta.label);
        conn.monaco.onDidChangeModelContent(() => _edMarkDirty(conn));
        conn.monaco.onDidChangeCursorPosition(() => _edUpdateInfo(conn));
      } catch(e) {
        showBanner('Monaco 加载失败，已降级纯文本：' + e, 6000, true);
        conn.monaco = null;
      }
    } else if (typeof monacoCreate === 'function' && isMd) {
      // .md：Monaco 源码编辑 + markdown-it 实时预览分栏
      try {
        // 分栏容器：预览列插到 ed-scroll 之后（HTML 已在 buildEditorTab 预置 ed-md-preview）
        conn.monaco = await monacoCreate(conn.holder, typeof content === 'string' ? content : '', conn.meta.label);
        conn.monaco.onDidChangeModelContent(() => { _edMarkDirty(conn); _mdRenderPreview(conn); });
        conn.monaco.onDidChangeCursorPosition(() => _edUpdateInfo(conn));
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
      conn.ta.addEventListener('input', () => _edMarkDirty(conn));
      conn.ta.addEventListener('keyup', () => _edUpdateInfo(conn));
      conn.ta.addEventListener('click', () => _edUpdateInfo(conn));
      if (isMd) _mdRenderPreview(conn);
    }
    conn.savedData = conn.monaco ? conn.monaco.getValue() : conn.ta.value;
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
function _edMarkDirty(conn) {
  // .note 的 onChange 即视为脏（比对 JSON 成本高且 await 别扭）；
  // 保存后 savedData 更新 + dirty 复位。纯文本精确比对字符串（Monaco/textarea 同源）。
  const cur = conn.isNote ? null : (conn.monaco ? conn.monaco.getValue() : (conn.ta ? conn.ta.value : ''));
  const dirty = conn.isNote ? true : (cur !== conn.savedData);
  if (dirty !== conn.dirty) { conn.dirty = dirty; _edMarkTab(conn); }
  _edUpdateInfo(conn);
}

// ---- 脏标记：tab 标题加 *（Notepad++ 风格）----
function _edMarkTab(conn) {
  // 原地改名中：标题 span 已换成输入框，改名结束后统一刷新
  if (conn._renaming) return;
  conn.tab.querySelector('.label').textContent = (conn.dirty ? '*' : '') + conn.meta.label;
  // 同步左侧列表里的文件名（改名后立即生效，不等 30s 轮询）
  const item = portList.querySelector(`.port-item[data-port-id="${CSS.escape(conn.portId)}"] .name`);
  if (item) item.textContent = conn.meta.label;
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
  _edRenderOutline(conn);   // 大纲面板开着时同步刷新（内容/块变化即更新）
}

// ---- 右侧大纲面板：标题层级导航 + 块类型统计 ----
function edToggleOutline(conn) {
  const shown = conn.outline.style.display !== 'none';
  conn.outline.style.display = shown ? 'none' : 'flex';
  if (!shown) _edRenderOutline(conn);
}
function _edRenderOutline(conn) {
  if (!conn.outline || conn.outline.style.display === 'none') return;
  // Monaco（txt/md/code）：解析 # 标题行生成大纲（# 井号层级，md 标准语法）
  if (conn.monaco || conn.ta) {
    const src = conn.monaco ? conn.monaco.getValue() : conn.ta.value;
    const lines = src.split('\n');
    const entries = [];
    // 统计口径与 .note 版对应：标题/列表/代码/引用按 md 语法粗判
    const types = { '标题': 0, '列表': 0, '代码': 0, '引用': 0 };
    let inCode = false;
    for (let i = 0; i < lines.length; i++) {
      const t = lines[i];
      if (/^\s*```/.test(t)) { inCode = !inCode; types['代码']++; continue; }
      if (inCode) continue;
      const m = /^(#{1,6})\s+(.*)$/.exec(t);
      if (m) { entries.push({ level: m[1].length, text: m[2].trim(), line: i + 1 }); types['标题']++; }
      else if (/^\s*[-*+]\s/.test(t) || /^\s*\d+\.\s/.test(t)) types['列表']++;
      else if (/^\s*>/.test(t)) types['引用']++;
    }
    conn.outlineList.innerHTML = entries.length
      ? entries.map((e, i) =>
          `<div class="ed-outline-item" data-i="${i}" style="padding-left:${(e.level-1)*12+8}px">${esc(e.text || '(无标题)')}</div>`).join('')
      : '<div class="ed-outline-empty">暂无标题行<br>用 # 井号标题（md）或标题块组织内容后在此生成目录</div>';
    conn.outlineList.querySelectorAll('.ed-outline-item').forEach(item => {
      item.onclick = () => {
        const e = entries[+item.dataset.i];
        if (!e) return;
        if (conn.monaco) { conn.monaco.revealLineInCenter(e.line); conn.monaco.setPosition({ lineNumber: e.line, column: 1 }); }
        else if (conn.ta) {
          let pos = 0;
          for (let i = 0; i < e.line - 1; i++) pos += lines[i].length + 1;
          conn.ta.focus();
          conn.ta.setSelectionRange(pos, pos);
          const lineH = parseFloat(getComputedStyle(conn.ta).lineHeight) || 20;
          conn.ta.scrollTop = Math.max(0, (e.line - 5) * lineH);
        }
      };
    });
    conn.outlineStats.innerHTML = Object.entries(types)
      .filter(([, v]) => v)
      .map(([k, v]) => `<span class="ed-outline-stat">${esc(k)} ${v}</span>`).join('');
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
    const pos = conn.monaco.getPosition() || { line: 1, column: 1 };  // 初始化竞态时可能为空，兜底 1,1
    const len = conn.monaco.getModel() ? conn.monaco.getModel().getValueLength() : 0;
    return `行 ${pos.line}，列 ${pos.column} · ${len} 字符`;
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
  try {
    const isExtPath = /^[a-zA-Z]:[\\/]|\\\\/.test(nameOrPath);  // Windows 绝对路径/UNC
    const r = await fetch('/api/ed/open?' + (isExtPath
      ? 'path=' + encodeURIComponent(nameOrPath)
      : 'name=' + encodeURIComponent(nameOrPath)));
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '打开失败', 4000, true); return; }
    const name = j.name || nameOrPath;
    const isNote = name.toLowerCase().endsWith('.note');
    // .note 存 JSON，.txt 存纯文本
    let content = j.text;
    if (isNote) { try { content = JSON.parse(j.text); } catch(e) { content = { blocks: [] }; } }
    // 记入最近打开（文件类型，快捷重开走编辑器）
    if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+name, label:name, data:{kind:'edit', name:name, path:nameOrPath, extPath: isExtPath ? nameOrPath : ''}});
    buildEditorTab(name, content, isExtPath ? nameOrPath : null);
  } catch(e) { showBanner('打开失败: ' + e, 4000, true); }
}

// ---- 保存：草稿/未落盘 → tab 标题原地改名（定名即保存）；已落盘 → 覆盖保存 ----
async function edSave(conn) {
  if (!conn.onDisk) { edRenamePrompt(conn); return; }
  const content = await _edGetContent(conn);
  if (content === null) { showBanner('读取内容失败', 4000, true); return; }
  const text = conn.isNote ? JSON.stringify(content) : content;
  try {
    // 外部文件（拖入）：写回原绝对路径；站内文件：按名写 files/
    const body = conn.extPath ? {path: conn.extPath, text} : {name: conn.meta.label, text};
    const r = await fetch('/api/ed/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '保存失败', 4000, true); return; }
    conn.savedData = content;
    conn.dirty = false; _edMarkTab(conn); _edUpdateInfo(conn);
    showBanner('已保存 ' + (conn.extPath || conn.meta.label), 1500);
    // 保存成功即入最近列表（草稿定名/已有文件覆盖保存都会走到这）
    if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+conn.meta.label, label:conn.meta.label, data:{kind:'edit', name:conn.meta.label, path:conn.meta.label, extPath: conn.extPath || ''}});
  } catch(e) { showBanner('保存失败: ' + e, 4000, true); }
}

// ---- 另存为：同样走 tab 原地改名（改名确认后即另存为新文件）----
function edSaveAs(conn) { edRenamePrompt(conn); }

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
  const curExt = conn.onDisk ? _edExt(conn.meta.label) : '.note';  // 后缀：默认 note，落盘保留原后缀
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
      const text = conn.isNote ? JSON.stringify(content) : content;
      try {
        const r = await fetch('/api/ed/save_as', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({new_name: nn, text})});
        const j = await r.json();
        if (!j.ok) { showBanner(j.err || '保存失败', 4000, true); _edMarkTab(conn); return; }
        conn.meta.label = j.name;
        conn.savedData = content;
        conn.onDisk = true;
        conn.dirty = false;
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
async function edDelete(conn) {
  if (conn.onDisk) {
    if (!confirm(`确定删除「${conn.meta.label}」？此操作不可恢复。`)) return;
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
function closeEditorTab(portId) {
  const conn = connections[portId];
  if (!conn) return;
  if (conn.dirty) {
    if (!confirm(`「${conn.meta.label}」有未保存的修改，关闭将丢失。确定关闭？`)) return;
  }
  _edCloseNow(conn);
}
function _edCloseNow(conn) {
  // Editor.js 实例先销毁（停掉内部 mutation 监听，防关 tab 后仍触发 onChange）
  if (conn.editor) { try { conn.editor.destroy(); } catch(e){} }
  // Monaco 同理（停掉 onDidChangeModelContent，防关 tab 后仍触发脏检测）
  if (conn.monaco) { try { conn.monaco.dispose(); } catch(e){} }
  conn.tab.remove(); conn.wrap.remove();
  delete connections[conn.portId];
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    if (ka[0] !== kb[0]) return ka[0] - kb[0];
    return ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0;
  });
  if (remaining.length) switchTab(remaining[0]);
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon">📡</div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';
  }
  refreshSidebar();  // 同步左侧列表
}

// ---- 新建文件：只建草稿 tab（.note 块笔记），不落盘 ----
function newEditorFile() {
  buildEditorTab(null, null);
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
          <strong>📝 文件</strong>
          <div class="head-actions">
            <button class="btn ghost" id="filesNew" title="新建笔记（不落盘，保存时才写文件）">＋ 新建笔记</button>
            <button class="btn ghost icon-btn" id="filesOpenDir" title="在资源管理器中打开 files/ 目录">📁</button>
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
    if (!j.files.length) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">暂无文件，点击「新建笔记」创建</div>'; return; }
    listEl.innerHTML = '';
    j.files.forEach(f => {
      const d = document.createElement('div');
      d.className = 'item';
      const dt = new Date(f.mtime*1000);
      const kb = f.size >= 1024 ? (f.size/1024).toFixed(1) + ' KB' : f.size + ' B';
      const icon = f.name.toLowerCase().endsWith('.note') ? '📝' : (f.name.toLowerCase().endsWith('.txt') ? '📄' : '📄');
      d.innerHTML = `<span>${icon} ${esc(f.name)}<br><span class="sz">${dt.toLocaleString('zh-CN')} · ${kb}</span></span>
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
  const btn = conn.wrap.querySelector('.ed-search-collapse');
  if (btn) btn.textContent = toShow ? '▾' : '▴';
  if (toShow) conn.wrap.querySelector('.ed-search-q').focus();
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
let _mdIt = null;   // markdown-it 实例单例（延迟建）
function _mdInstance() {
  if (_mdIt) return _mdIt;
  // markdown-it.min.js（vendor，index.html 已引）暴露 window.markdownit
  _mdIt = window.markdownit ? window.markdownit({ html: false, linkify: true, typographer: false, breaks: false }) : null;
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
function _mdRenderPreview(conn) {
  const pv = conn.wrap.querySelector('.ed-md-preview');
  if (!pv) return;
  const md = _mdInstance();
  const src = conn.monaco ? conn.monaco.getValue() : (conn.ta ? conn.ta.value : '');
  if (!md) { pv.innerHTML = '<div class="md-preview-err">markdown-it 未加载（vendor/markdown-it 缺失）</div>'; return; }
  pv.innerHTML = md.render(src || '');
  // 锚点链接安全：内部相对链接禁跳（工具内无路由），只留外链新开
  pv.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (!/^https?:/i.test(href)) { a.addEventListener('click', e => e.preventDefault()); a.title = '工具内不支持跳转内部链接'; }
  });
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
async function openDroppedFile(path) {
  const name = path.split(/[\/]/).pop().toLowerCase();
  const dot = name.lastIndexOf('.');
  const ext = dot > 0 ? name.slice(dot) : name;
  if (_DROP_TEXT_EXT.has(ext) || name === 'makefile' || name === 'readme') {
    try {
      const r = await fetch('/api/ed/open?path=' + encodeURIComponent(path));
      const j = await r.json();
      if (j.ok) {
        if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+j.name, label:j.name, data:{kind:'edit', name:j.name, path:path, extPath: path}});
        buildEditorTab(j.name, j.text, path);
        return;
      }
      // .log 超限/异常 → 回落只读查看器；其他文本报错
      if (ext !== '.log') { showBanner(j.err || '打开失败', 4000, true); return; }
    } catch(e) { if (ext !== '.log') { showBanner('打开失败: ' + e, 4000, true); return; } }
  }
  buildLogViewer(path);   // .log 超限/未知类型：只读日志查看器（G 级虚拟列表）
}
