// ============================================================
// 文件对比查看器：Monaco DiffEditor（VSCode 同款双栏 diff 内核）
// 引擎零新增——vendor/monaco 的 editor.main 本就内置 createDiffEditor
// （对比 react-diff-viewer 等 GitHub 方案：那些要么底层也是 Monaco，
// 要么要引 React，重且离线打包麻烦；直接用现成内核最优）。
// tab 体系与编辑器/hex 同构：connections + switchTab + closeEditorTab。
// 入口：顶栏「🔀 对比」→ 左右两栏选择弹窗（点击/拖拽放文件）；
//       MCP 工具 compare_files（后端 /api/ai/compare_files → SSE open_diff）。
// 差异导航：IStandaloneDiffEditor.goToDiff('next'/'previous')——d.ts 公开 API
// （DiffEditorWidget 原型方法，非 accessibleDiffViewer action——那个是
// 无障碍朗读视图，不跳转视觉光标，之前误用导致按钮无效）。
// ============================================================

// ---- 读取单份文件文本（复用编辑器后端 /api/ed/open，任意绝对路径）----
// 二进制判定：任一文件含 NUL 或解码替换符>5% 即视为二进制（hex-viewer 的
// 后缀白名单方案不适用——对比入口拿到的可能是任意路径）。
const _binCheckCache = new Map();
// a237 P3：缓存封顶 512（路径→bool）——无上限时长跑每对比一个新文件永久 +1 条
function _binCheckRemember(p, v) {
  if (_binCheckCache.size >= 512) _binCheckCache.delete(_binCheckCache.keys().next().value);
  _binCheckCache.set(p, v);
}
async function _diffIsBinary(aPath, bPath) {
  const check = async (p) => {
    if (_binCheckCache.has(p)) return _binCheckCache.get(p);
    let bin = false;
    try {
      const r = await fetch('/api/read_text?q=' + encodeURIComponent(p));
      const j = await r.json();
      if (!j.ok) bin = true;   // 读不了（二进制被拒/文件大）→ 当二进制交给 hex diff 试
      else {
        const t = j.text;
        if (t.indexOf('\x00') >= 0) bin = true;
        else {
          const bad = (t.match(/�/g) || []).length;
          if (t.length && bad / t.length > 0.05) bin = true;
        }
      }
    } catch (_) { bin = true; }
    _binCheckRemember(p, bin);
    return bin;
  };
  return (await check(aPath)) || (await check(bPath));
}

async function _diffReadFile(path) {
  // files/<名>：编辑器内建目录文件，走 name 分支（files/ 目录随数据目录迁移，绝对路径会失效）
  let url;
  if (path.startsWith('files/')) url = '/api/ed/open?name=' + encodeURIComponent(path.slice(6));
  // 其余（绝对路径 / 日志库裸名）走 read_text：_resolve_log_path 两种都认
  else url = '/api/read_text?q=' + encodeURIComponent(path);
  const r = await fetch(url);
  const j = await r.json();
  if (!j.ok) return { err: j.err || '读取失败' };
  return { name: j.name || path.split(/[\\/]/).pop(), text: j.text };
}

// ---- 信息栏：A/B 文件名 + 差异行数（onDidUpdateDiff 后刷新）----
function _diffUpdateInfo(conn) {
  if (!conn.infoEl) return;
  const s = conn._diffStat || { added: 0, removed: 0 };
  const total = conn._diffCount || 0;
  conn.infoEl.textContent =
    `A: ${conn.aName} ↔ B: ${conn.bName} · 共 ${total} 处差异 · +${s.added} 行 -${s.removed} 行`;
}

// ---- diff 计算完成 → 统计差异处数/行数，首次自动滚到第一处差异 ----
// 行数口径：行号区间长度（end-start+1；start=0 表示纯增/删，区间长 0）。
// 之前用 originalContentDidChange 等"字段"判增删——ILineChange 根本没这字段
// （臆造 undefined 恒 false），统计恒 +0 -0。
function _diffCountLines(conn, first) {
  try {
    const changes = conn.diffEd.getLineChanges() || [];
    let added = 0, removed = 0;
    for (const ch of changes) {
      const oCnt = ch.originalEndLineNumber > 0
        ? (ch.originalEndLineNumber - ch.originalStartLineNumber + 1) : 0;
      const mCnt = ch.modifiedEndLineNumber > 0
        ? (ch.modifiedEndLineNumber - ch.modifiedStartLineNumber + 1) : 0;
      added += mCnt;
      removed += oCnt;
    }
    conn._diffStat = { added, removed };
    conn._diffCount = changes.length;
    // 无差异明确告知（「对比中…」永不消失的教训：完成态必须可见）
    conn.infoEl.classList.toggle('diff-same', changes.length === 0);
  } catch (_) {}
  _diffUpdateInfo(conn);
}

// ---- 构建对比 tab：aPath/bPath 绝对路径 ----
// 复用打开：同 A/B 组合已开 → 直接切过去
async function buildDiffViewerTab(aPath, bPath) {
  // 二进制文件分流：文本 diff（Monaco）读二进制是乱码，走字节级 hex diff
  if (typeof buildHexDiffTab === 'function' && await _diffIsBinary(aPath, bPath)) {
    return buildHexDiffTab(aPath, bPath);
  }
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'diff' &&
        ((c.aPath === aPath && c.bPath === bPath) || (c.aPath === bPath && c.bPath === aPath))) {
      switchTab(pid); return;
    }
  }
  // 任务型通知：文本对比读文件（两份并行），多任务并发各自一条冒泡
  const aName0 = aPath.split(/[\\/]/).pop(), bName0 = bPath.split(/[\\/]/).pop();
  const nid = notifyTask({type:'diff', title:'正在对比', detail:`${aName0} ↔ ${bName0}`});
  // 读取两份（并行）
  const [a, b] = await Promise.all([_diffReadFile(aPath), _diffReadFile(bPath)]);
  if (a.err) { notifyTaskDone(nid, {ok:false, title:'对比失败', detail:'A 文件读取：' + a.err, ms:6000}); return; }
  if (b.err) { notifyTaskDone(nid, {ok:false, title:'对比失败', detail:'B 文件读取：' + b.err, ms:6000}); return; }
  const aName = a.name, bName = b.name;
  const label = aName === bName ? `${aName}（对比）` : `${aName} ↔ ${bName}`;
  const portId = 'diff:' + aPath + '|' + bPath + ':' + Date.now();

  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico"><svg width="14" height="14" viewBox="0 0 22 22" aria-hidden="true"><rect x="3" y="2" width="9" height="13" rx="2" fill="var(--accent)" opacity="0.35"/><rect x="10" y="7" width="9" height="13" rx="2" fill="var(--accent)" opacity="0.6"/></svg></span><span class="label">${esc(label)}</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; }
    switchTab(portId);
  };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <button class="lv-btn" data-diff-action="swap" title="交换 A/B（左右互换重新对比）">⇄ 互换</button>
        <button class="lv-btn" data-diff-action="inline" title="并排/内联视图切换（内联 = 行内 +/- 标记）">▤ 内联</button>
        <button class="lv-btn" data-diff-action="nav-prev" title="上一处差异">▲ 上一处</button>
        <button class="lv-btn" data-diff-action="nav-next" title="下一处差异">▼ 下一处</button>
        <span class="lv-sep"></span>
        <button class="lv-btn" data-diff-action="wrap" title="切换超长行折行">↩ 折行</button>
        <button class="lv-btn" data-diff-action="collapse" title="折叠未变化区域（只看差异段）">⇕ 折叠未变</button>
        <span class="lv-info" data-diff-info>对比中…</span>
      </div>
      <div class="ed-main">
        <div class="diff-holder"></div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const conn = {
    portId,
    meta: { kind: 'diff', label },
    tab, wrap,
    aPath, bPath, aName, bName,
    holder: wrap.querySelector('.diff-holder'),
    infoEl: wrap.querySelector('[data-diff-info]'),
    diffEd: null,
    dirty: false,   // 只读查看器无脏态（closeEditorTab 走 dirty 检查需有此字段）
    _diffStat: { added: 0, removed: 0 }, _diffCount: 0, _firstDiffShown: false,
    _inline: false, _wrap: false, _collapse: false,
  };
  connections[portId] = conn;

  // Monaco DiffEditor 实例化（vendor 引擎按需加载，首次有加载等待）
  let monaco;
  try {
    monaco = await monacoInit();
  } catch (e) {
    notifyTaskDone(nid, {ok:false, title:'对比失败', detail:'Monaco 加载失败：' + e, ms:6000});
    _edCloseNow(conn);
    return;
  }
  conn.diffEd = monaco.editor.createDiffEditor(conn.holder, {
    theme: _monacoThemeName(),
    automaticLayout: true,
    fontSize: 13,
    renderSideBySide: true,        // 默认并排双栏（内联可切）
    originalEditable: false,       // A 侧（基准）只读
    ignoreTrimWhitespace: false,   // 空白差异也标（排缩进错位有用）
    renderIndicators: true,
    scrollBeyondLastLine: false,
    wordWrap: 'off',
    diffWordWrap: 'off',
    unicodeHighlight: { ambiguousCharacters: false },   // 中文标点不标黄
    scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
    padding: { top: 8 },
    // 未变化区域折叠：默认关（开着首屏只见小窗，小文件反别扭）；「折叠未变」按钮开
    hideUnchangedRegions: { enabled: false, minimumLineCount: 4, contextLineCount: 3, revealLineCount: 20 },
  });
  conn.diffEd.setModel({
    original: monaco.editor.createModel(a.text, monacoLangFor(aName)),
    modified: monaco.editor.createModel(b.text, monacoLangFor(bName)),
  });
  // diff 异步计算完成 → 统计 + 首次自动跳到第一处差异（用户开对比就是要看差异，
  // 落在最顶上还得自己翻——revealFirstDiff 官方 API，等 diff 算完直接落点）
  conn.diffEd.onDidUpdateDiff(() => {
    _diffCountLines(conn);
    if (!conn._firstDiffShown) {
      conn._firstDiffShown = true;
      try { conn.diffEd.revealFirstDiff(); } catch (_) {}
    }
  });

  // 工具栏
  wrap.querySelectorAll('.lv-btn').forEach(btn => {
    btn.onclick = () => {
      const act = btn.dataset.diffAction;
      if (act === 'swap') {
        // 交换 A/B：互换 model + 路径/文件名/标题（BSP 常用：反转"正常 vs 异常"基准方向）
        const { original, modified } = conn.diffEd.getModel();
        conn.diffEd.setModel({ original: modified, modified: original });
        [conn.aPath, conn.bPath] = [conn.bPath, conn.aPath];
        [conn.aName, conn.bName] = [conn.bName, conn.aName];
        conn.meta.label = conn.aName === conn.bName ? `${conn.aName}（对比）` : `${conn.aName} ↔ ${conn.bName}`;
        conn.tab.querySelector('.label').textContent = conn.meta.label;
        _diffUpdateInfo(conn);
      }
      else if (act === 'inline') {
        conn._inline = !conn._inline;
        conn.diffEd.updateOptions({ renderSideBySide: !conn._inline });
        btn.classList.toggle('active', conn._inline);
      }
      else if (act === 'wrap') {
        // 折行（全通道）：顶层 wordWrap+diffWordWrap（最初版做法，并排视图走
        // wordWrapOverride1=diffWordWrap 通道）+ 两侧内嵌编辑器直接 updateOptions
        // （内联视图时 vendor 强制 override=off，顶层选项够不着，只能直改内嵌）。
        // 两路都设，任何视图模式下都生效。
        conn._wrap = !conn._wrap;
        const w = conn._wrap ? 'on' : 'off';
        conn.diffEd.updateOptions({ wordWrap: w, diffWordWrap: w });
        conn.diffEd.getOriginalEditor().updateOptions({ wordWrap: w });
        conn.diffEd.getModifiedEditor().updateOptions({ wordWrap: w });
        btn.classList.toggle('active', conn._wrap);
      }
      else if (act === 'collapse') {
        // 折叠未变化区域：hideUnchangedRegions 开关（VSCode 同款；diff 已计算才有意义）。
        // minimumLineCount 开时降为 1：默认 4 行连续未变才折，4~5 行的小文件
        // （BSP 单配置段对比）永远够不着阈值 → 按钮点了没反应的观感；降为 1
        // 单行未变也折，小文件立见效，大文件行为不变（默认关着，开了就要折）
        conn._collapse = !conn._collapse;
        conn.diffEd.updateOptions({
          hideUnchangedRegions: conn._collapse
            ? { enabled: true, minimumLineCount: 1, contextLineCount: 1, revealLineCount: 20 }
            : { enabled: false, minimumLineCount: 4, contextLineCount: 3, revealLineCount: 20 },
        });
        btn.classList.toggle('active', conn._collapse);
      }
      else if (act === 'nav-prev' || act === 'nav-next') {
        // 差异导航：goToDiff 公开 API（d.ts 声明、DiffEditorWidget 原型实现）
        try {
          conn.diffEd.getModifiedEditor().focus();
          conn.diffEd.goToDiff(act === 'nav-next' ? 'next' : 'previous');
        } catch (_) {}
      }
    };
  });

  // 键盘兜底：F7/Shift+F7 跳差异（焦点在工具栏时 Monaco 自带 keybinding 不触发）
  // a237 P2：存 conn 由 _edCloseNow 统一摘除（匿名挂载钉死 conn + 脱离 wrap）
  conn._dvKey = e => {
    if (activePortId !== portId) return;
    if (e.key === 'F7') {
      e.preventDefault();
      try {
        conn.diffEd.getModifiedEditor().focus();
        conn.diffEd.goToDiff(e.shiftKey ? 'previous' : 'next');
      } catch (_) {}
    }
  };
  document.addEventListener('keydown', conn._dvKey);

  notifyTaskDone(nid, {ok:true, title:'对比已打开', detail:label});
  switchTab(portId);
  refreshSidebar();
  // 记入最近打开
  if (typeof _recentAdd === 'function') _recentAdd({
    type: 'file', key: 'diff:' + aPath + '|' + bPath, label,
    data: { kind: 'diff', a: aPath, b: bPath },
  });
  return conn;
}

// ============================================================
// 对比文件选择弹窗：左右两栏（A 基准 / B 对比），点击选文件或拖拽放入
// 两栏齐了 →「开始对比」可点。也支持只换一栏（从最近/日志库场景）。
// ============================================================
function _diffPickModal() {
  let m = $('diffPickModal');
  if (m) return m;
  m = document.createElement('div');
  m.className = 'modal';
  m.id = 'diffPickModal';
  m.innerHTML = `
    <div class="box" style="max-width:720px;">
      <div class="head">
        <strong>🔀 文件对比</strong>
        <div class="head-actions">
          <button class="btn ghost" id="diffPickClear" title="清空两栏重新选">清空</button>
          <button class="btn ghost icon-btn" id="diffPickClose">✕</button>
        </div>
      </div>
      <div style="padding:16px 20px;">
        <div class="diff-pick-grid">
          <div class="diff-pick-side" id="diffPickA" data-side="a">
            <div class="diff-pick-tag">A · 基准</div>
            <div class="diff-pick-zone">
              <div class="diff-pick-empty">点击选择文件<br>或把文件拖到这里</div>
              <div class="diff-pick-file" style="display:none;">
                <span class="ico">📄</span><span class="fname"></span><span class="rm" title="移除">✕</span>
              </div>
            </div>
          </div>
          <div class="diff-pick-vs">VS</div>
          <div class="diff-pick-side" id="diffPickB" data-side="b">
            <div class="diff-pick-tag">B · 对比</div>
            <div class="diff-pick-zone">
              <div class="diff-pick-empty">点击选择文件<br>或把文件拖到这里</div>
              <div class="diff-pick-file" style="display:none;">
                <span class="ico">📄</span><span class="fname"></span><span class="rm" title="移除">✕</span>
              </div>
            </div>
          </div>
        </div>
        <div style="display:flex;justify-content:flex-end;margin-top:16px;gap:10px;">
          <button class="btn ghost" id="diffPickCancel">取消</button>
          <button class="btn primary" id="diffPickGo" disabled>开始对比</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(m);
  const st = { a: '', b: '' };   // 两栏的绝对路径
  m._st = st;                   // 拖拽落点填充走全局函数（openDroppedFile 转发）

  const sync = () => {
    // 每栏：有路径显示文件名卡（空态藏），两栏齐 → 开始对比可点
    for (const side of ['a', 'b']) {
      const z = m.querySelector(`.diff-pick-side[data-side="${side}"]`);
      const empty = z.querySelector('.diff-pick-empty');
      const file = z.querySelector('.diff-pick-file');
      const has = !!st[side];
      empty.style.display = has ? 'none' : '';
      file.style.display = has ? 'flex' : 'none';
      if (has) file.querySelector('.fname').textContent = st[side].split(/[\\/]/).pop();
      z.classList.toggle('filled', has);
      z.classList.remove('dragover');
    }
    m.querySelector('#diffPickGo').disabled = !(st.a && st.b);
  };

  // 点击栏 → 原生文件框选单份
  const pick = async side => {
    try {
      const path = await pywebview.api.pick_any();
      if (path && typeof path === 'string') { st[side] = path; sync(); }
    } catch (_) {
      showBanner('文件选择器暂不可用', 3000, true);
    }
  };
  // 拖拽填栏：pywebview 原生 drop 是 WebView2 下唯一能拿绝对路径的通道，
  // drop_handler 回调走 openDroppedFile——弹窗开着时转到这里填 A/B 栏。
  // 之前在 DOM drop 里 stopPropagation + 拿 files[i].path：WebView2 拿不到
  // path → 遮罩（body drop 隐藏）收不到事件永不消失（用户报的 bug）。
  // 落点规则：拖动时 hover 到哪栏就填哪栏（dragover 持续刷新 _hoverSide，
  // 用户拖到 A 栏松手 → 填 A，所见即所得）；没 hover 栏位（松在弹窗空白处）
  // → 空栏优先 A，其次 B。目标栏已有文件 = 覆盖（换文件是常见意图）。
  let _hoverSide = null;
  window._diffPickDrop = (path) => {
    const side = _hoverSide || (st.a ? 'b' : 'a');
    st[side] = path;
    sync();
    return true;   // 已消费：openDroppedFile 不再打开文件
  };
  for (const side of ['a', 'b']) {
    const z = m.querySelector(`.diff-pick-side[data-side="${side}"]`);
    z.onclick = e => {
      // 点 ✕ 移除（不冒泡触发选文件）
      if (e.target.classList.contains('rm')) { e.stopPropagation(); st[side] = ''; sync(); return; }
      pick(side);
    };
    // dragover/dragleave 只管高亮 + 记录落点栏（不 preventDefault drop——
    // 原生通道要收；dragover 高频触发，只改一个变量零开销）
    z.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); z.classList.add('dragover'); _hoverSide = side; });
    z.addEventListener('dragleave', () => { z.classList.remove('dragover'); if (_hoverSide === side) _hoverSide = null; });
  }

  m.querySelector('#diffPickClear').onclick = () => { st.a = ''; st.b = ''; sync(); };
  m.querySelector('#diffPickClose').onclick = m.querySelector('#diffPickCancel').onclick =
    () => m.classList.remove('show');
  m.querySelector('#diffPickGo').onclick = () => {
    m.classList.remove('show');
    buildDiffViewerTab(st.a, st.b);
  };
  sync();
  return m;
}

// ---- 顶栏「🔀 对比」：弹左右两栏选择弹窗 ----
function openDiffPicker() {
  _diffPickModal().classList.add('show');
}

// 最近列表快捷打开分发（sidebar.js openRecentItem 调）
function openDiffFromRecent(data) {
  if (data && data.a && data.b) buildDiffViewerTab(data.a, data.b);
}

// ============================================================
// 打开文件 tab 右键快捷对比：「选择以进行对比」（记为 A）→
// 到另一文件 tab 右键「与选进行对比」（作 B）→ 直接开对比。
// 复用 search.js 的 #ctxMenu 元素与 .ctx-item/.ctx-sep 样式（UI 风格统一）。
// ============================================================
let _diffCtxA = null;   // 已「选择以进行对比」的文件（A）

// 各类文件 tab → 可对比的路径标识（files/<名> 或绝对路径）；非文件 tab 返回 null
function _diffCtxPathOf(pid) {
  const c = connections[pid];
  if (!c || !c.meta) return null;
  const k = c.meta.kind;
  if (k === 'editor' || k === 'note') {
    if (c.extPath) return c.extPath;
    if (c.onDisk && c.meta.label) return 'files/' + c.meta.label;
    return null;   // 未命名新建文件没有磁盘内容，无从对比
  }
  if (k === 'log' && c.meta.path) return c.meta.path;
  if (k === 'hex' && c.hexPath) return c.hexPath;
  return null;   // 终端/对比 tab 不参与
}

function _diffCtxNameOf(p) {
  return (p.startsWith('files/') ? p.slice(6) : p.split(/[\\/]/).pop());
}

// ---- a260：树右键对比入口（与 tab 右键共享 _diffCtxA 状态，两侧互通——
// 树上选 A、tab 上比，或反过来，都行）----
function diffPickSetA(path) {
  _diffCtxA = path;
  showBanner(`已选为对比 A（基准）：${_diffCtxNameOf(path)}。到另一文件上右键「与选进行对比」`, 4000);
}
function diffPickCompare(path) {
  if (!_diffCtxA || _diffCtxA === path) return false;
  const a = _diffCtxA;
  _diffCtxA = null;   // 用完即清（避免残留指向已删/已改文件）
  buildDiffViewerTab(a, path);
  return true;
}
function diffPickA() { return _diffCtxA; }

// 右键菜单主体（样式与终端右键菜单同源）
function _showDiffCtxMenu(x, y, pid) {
  const m = $('ctxMenu');
  const path = _diffCtxPathOf(pid);
  const name = path ? _diffCtxNameOf(path) : '';
  const isA = path && path === _diffCtxA;
  const noA = !_diffCtxA;
  const sameAsA = path && _diffCtxA && path === _diffCtxA;
  m.innerHTML = [
    `<div class="ctx-item${isA ? ' disabled' : ''}" data-act="pickA">🔀 选择以进行对比${isA ? '（当前 A）' : ''}</div>`,
    `<div class="ctx-item${(noA || sameAsA) ? ' disabled' : ''}" data-act="pickB" title="${noA ? '先在另一文件上「选择以进行对比」' : ''}">🔀 与选进行对比${noA ? '（未选 A）' : ''}</div>`,
  ].join('');
  m.style.display = 'block';
  const mw = m.offsetWidth, mh = m.offsetHeight;
  m.style.left = Math.min(x, window.innerWidth - mw - 4) + 'px';
  m.style.top = Math.min(y, window.innerHeight - mh - 4) + 'px';
  m.querySelectorAll('.ctx-item').forEach(it => {
    it.onclick = () => {
      hideCtxMenu();
      if (it.classList.contains('disabled')) return;
      if (it.dataset.act === 'pickA') {
        _diffCtxA = path;
        showBanner(`已选为对比 A（基准）：${name}。在另一文件上右键「与选进行对比」`, 4000);
      } else {
        const a = _diffCtxA;
        buildDiffViewerTab(a, path);
        _diffCtxA = null;   // 用完即清，下次重新选（避免残留指向已关文件）
      }
    };
  });
}

// 委托绑定：#tabs 上右键文件类 tab → 快捷对比菜单（终端 tab 右键不动——
// 终端是 Ctrl+右键菜单，普通右键留给 xterm 自身行为）
document.getElementById('tabs').addEventListener('contextmenu', e => {
  const tabEl = e.target.closest('.tab');
  if (!tabEl) return;
  const pid = tabEl.dataset.portId;
  if (!pid || !_diffCtxPathOf(pid)) return;
  e.preventDefault();
  _showDiffCtxMenu(e.clientX, e.clientY, pid);
});

// 左栏「打开」列表项右键 → 同一菜单（port-item 与 tab 是同一 conn 的两处入口）
document.getElementById('portList').addEventListener('contextmenu', e => {
  const item = e.target.closest('.port-item');
  if (!item) return;
  const pid = item.dataset.portId;
  if (!pid || !_diffCtxPathOf(pid)) return;
  e.preventDefault();
  _showDiffCtxMenu(e.clientX, e.clientY, pid);
});
