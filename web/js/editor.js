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
  // 外部 .note 入口（拖入/最近打开）传的是 /api/ed/open 返回的 JSON 字符串：
  // 不解析则 _edInitContent 判非对象 → 空块初始化 → Ctrl+S 把原文件覆盖成空笔记
  if (isNote && typeof content === 'string' && content.trim()) {
    try { content = JSON.parse(content); } catch (_) { content = null; }
  }
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
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${fileIconHtml(name || '.note', 14)}</span><span class="label">${esc(name || '未命名')}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
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
        <button class="lv-btn" data-ed-action="search" title="Ctrl+F 全局搜索（支持正则/排除）">🔍 搜索</button>
        <button class="lv-btn" data-ed-action="outline" title="显示/隐藏右侧大纲面板">☰ 大纲</button>
        <select class="lv-btn ed-enc-sel" data-ed-enc title="文件编码（切换后按所选编码重新读取；保存始终写 UTF-8）" style="display:none;">
          <option value="">编码：自动</option>
          <option value="utf-8">UTF-8</option>
          <option value="gb2312">GB2312</option>
          <option value="gbk">GBK</option>
          <option value="gb18030">GB18030</option>
          <option value="big5">Big5</option>
          <option value="latin-1">Latin-1</option>
        </select>
        <span class="lv-info" data-ed-info></span>
      </div>
      <div class="ed-main">
        <div class="ed-outline" style="display:none;">
          <div class="ed-outline-head">大纲<span class="ed-outline-actions" style="display:none;"><span class="ed-outline-act" data-act="collapseAll" title="全部折叠">⤠</span><span class="ed-outline-act" data-act="expandAll" title="全部展开">⤡</span></span></div>
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
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);   // 拖拽排序（tab-drag.js）
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
    usedEnc: null,             // 打开文件实际用的编码（编码下拉切换时重读）
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
  // 编码下拉（仅外部文件——站内 files/ 永远 UTF-8）：切换 = 脏检查后
  // 按所选编码重读原文件灌入 Monaco。自动探测报 GB18030 时下拉预选 GBK
  //（gb18030 是 gbk 超集，用户视角"这就是 GBK 文件"）。
  if (conn.extPath && !isNote) {
    const encSel = wrap.querySelector('[data-ed-enc]');
    if (encSel) {
      encSel.style.display = '';
      const _ue = window._edLastUsedEnc || '';
      encSel.title = '当前编码：' + (_ue || '自动探测') + '（切换后按所选编码重新读取原文件；保存始终写 UTF-8）';
      if (_ue === 'gb18030' || _ue === 'gbk') encSel.value = 'gbk';
      encSel.onchange = async () => {
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
          if (!j.ok) { showBanner('重读失败：' + (j.err || ''), 4000, true); return; }
          conn.usedEnc = j.used_enc;
          window._edLastUsedEnc = j.used_enc;
          conn.dirty = false;
          if (conn.monaco) {
            const pos = conn.monaco.getPosition();
            conn.monaco.setValue(j.text);
            try { conn.monaco.setPosition(pos); conn.monaco.revealLineInCenter(pos.lineNumber); } catch (_) {}
          } else if (conn.ta) conn.ta.value = j.text;
          conn.savedData = conn.monaco ? conn.monaco.getValue() : (conn.ta ? conn.ta.value : j.text);
          encSel.dataset.cur = enc;
          showBanner('已按 ' + (j.used_enc || '自动探测') + ' 重新读取', 2500);
        } catch(e) { showBanner('重读失败: ' + e, 4000, true); }
      };
    }
  }
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
      else if (act === 'delete') { if (conn.extPath) showBanner('外部文件不提供删除（请到文件管理器操作）', 3000, true); else edDelete(conn); }   // 按钮已移除，防御保留
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
        conn.monaco = await monacoCreate(conn.holder, typeof content === 'string' ? content : '', conn.meta.label);
        conn.monaco.onDidChangeModelContent(() => { _edMarkDirty(conn); conn._edSrcVer = (conn._edSrcVer || 0) + 1; _mdRenderPreview(conn); });
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
      conn.ta.addEventListener('input', () => { _edMarkDirty(conn); conn._edSrcVer = (conn._edSrcVer || 0) + 1; });
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
    // md/txt/其余：# 井号规则
    const lines = src.split('\n');
    const entries = [];
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
    window._edLastUsedEnc = isExtPath ? (j.used_enc || null) : null;
    const _c = buildEditorTab(name, content, isExtPath ? nameOrPath : null);
    if (_c) _c.usedEnc = j.used_enc || null;
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
  // Editor.js 实例先销毁（停掉内部 mutation 监听，防关 tab 后仍触发 onChange）
  if (conn.editor) { try { conn.editor.destroy(); } catch(e){} }
  // Monaco 同理（停掉 onDidChangeModelContent，防关 tab 后仍触发脏检测）
  if (conn.monaco) { try { conn.monaco.dispose(); } catch(e){} }
  // DiffEditor（diff tab）：编辑器与两侧 model 一并销毁（防泄漏 + 关 tab 后仍触发 onDidUpdateDiff）
  if (conn.diffEd) {
    try {
      const m = conn.diffEd.getModel();
      conn.diffEd.dispose();
      if (m) { m.original.dispose(); m.modified.dispose(); }
    } catch(e){}
  }
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
          <strong>📝 笔记</strong>
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
    if (!j.files.length) { listEl.innerHTML = '<div style="padding:20px;color:var(--muted);">暂无笔记，点击「新建笔记」创建</div>'; return; }
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
// ---- 文件打开方式选择弹窗（20~30M 提示用；小于 20M 用户主动选阅读器也复用）----
// mode: 'ask' 弹窗让选（含二进制选项）；'edit' 直接编辑器；'view' 直接阅读器；'hex' 直接二进制
function _showOpenModeDialog(path, sizeMB, withHex) {
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
                🔢 二进制打开<small style="color:var(--muted);font-weight:400;">　16 进制查看/编辑（任意文件）</small>
              </button>
              <button class="btn" id="openModeView" style="padding:10px 14px;text-align:left;justify-content:flex-start;">
                📖 阅读器打开<small style="color:var(--muted);font-weight:400;">　虚拟列表，大文件流畅（只读+搜索）</small>
              </button>
              <button class="btn" id="openModeEdit" style="padding:10px 14px;text-align:left;justify-content:flex-start;">
                ✏️ 编辑器打开<small style="color:var(--muted);font-weight:400;">　Monaco，可编辑保存</small>
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
      `${path}${sizeMB != null ? `（${sizeMB}MB）` : ''}\n` +
      (sizeMB != null && sizeMB > 20
        ? '文件超过 20MB：编辑器打开可能卡顿（Monaco 分词内存约为文件 3~5 倍），建议用阅读器。'
        : (withHex ? '未知类型文件，选择打开方式：' : '选择打开方式：'));
    m.classList.add('show');
  });
}

// ---- 统一文件打开入口（拖拽/最近/顶栏打开 共用）----
// mode: 'auto'（默认按大小规则）| 'edit' | 'view' | 'hex'
// 规则：未知/二进制类型 → 弹窗让选（二进制/阅读器/编辑器）；
//       已知文本：<20M 编辑器；20~30M 弹窗提示选（默认建议阅读器）；>30M 强制阅读器。
async function openFileSmart(path, mode) {
  const name = path.split(/[\/]/).pop().toLowerCase();
  const dot = name.lastIndexOf('.');
  const ext = dot > 0 ? name.slice(dot) : name;
  const isText = _DROP_TEXT_EXT.has(ext) || name === 'makefile' || name === 'readme';
  // 探测大小（失败按 0 处理走编辑器尝试）
  let size = 0, isTextSrv = isText;
  try {
    const r = await fetch('/api/file_info', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    const j = await r.json();
    if (j.ok) { size = j.size; isTextSrv = j.is_text; }
  } catch(e) {}
  const MB = size / 1024 / 1024;
  // 决策
  let how = mode || 'auto';
  if (how === 'auto') {
    if (!isTextSrv) how = await _showOpenModeDialog(path, MB ? MB.toFixed(1) : null, true);  // 未知类型：弹窗选（二进制/阅读器/编辑器）
    else if (MB > 30) how = 'view';                        // >30M 强制阅读器（Monaco 必卡）
    else if (MB > 20) how = await _showOpenModeDialog(path, MB.toFixed(1), false);  // 20~30M 提示选
    else how = 'edit';                                     // <20M 默认编辑器
    if (!how) return;                                      // 用户关掉了弹窗
  }
  if (how === 'hex') { buildHexViewerTab(path, name); return; }
  if (how === 'view') { buildLogViewer(path); return; }
  // edit：未知类型用户硬选编辑器——超 20M 后端会拒（大小前提由后端硬上限兜底），拒则降级
  try {
    // force=1：无后缀/未知类型按内容探测放行（去后缀的 json 等曾直接被白名单拒）
    const r = await fetch('/api/ed/open?force=1&path=' + encodeURIComponent(path));
    const j = await r.json();
    if (j.ok) {
      window._edLastUsedEnc = j.used_enc || null;
      if (typeof _recentAdd === 'function') _recentAdd({type:'file', key:'file:'+j.name, label:j.name, data:{kind:'edit', name:j.name, path:path, extPath: path}});
      const _c = buildEditorTab(j.name, j.text, path);
      if (_c) _c.usedEnc = j.used_enc || null;
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
  buildLogViewer(path);
}

async function openDroppedFile(path, fromRecent) {
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
    blob = await (await fetch('/api/ed/img_data/' + j2.url.split('/').pop())).blob();
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
