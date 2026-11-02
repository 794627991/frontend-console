// ============================================================
// 文件树工作区（类 VSCode 资源管理器）：侧栏第三 sheet「文件树」。
// - 多根工作区：根目录登记制（config.json tree_roots 持久化，重启恢复）
// - 懒加载：展开才 POST /api/tree/list 拉单层（绝不递归，首守则：流畅）
// - 事件委托：整个 #treePane 一个 click listener，几千行零延迟
// - 文件点击一行分发 openFileSmart(path,'auto')（hex/编辑器/日志自动分流）
// - 拖文件夹进窗口 = 设为根（editor.js openDroppedFile 的 is_dir 分支调 addTreeRoot）
// 安全：/api/tree/* 只允许枚举已登记根的子树内路径（src/file_tree.py 门卫）。
// ============================================================

// ---- 添加根（登记 + 刷新）----
async function addTreeRoot(path) {
  if (!path) return;
  try {
    const r = await fetch('/api/tree/add_root', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
    const j = await r.json();
    if (j.ok) { refreshTree(); return true; }
    showBanner('添加文件夹失败：' + (j.err || '未知错误'), 4000, true);
  } catch(e) { showBanner('添加文件夹失败: ' + e, 4000, true); }
  return false;
}

// ---- 选择文件夹（原生对话框，照抄 tftp.js pickTftpDir 模式）----
async function pickTreeDir() {
  // 原生目录对话框（pywebview js_api，main.py FileBridge.pick_dir 已存在）。
  // 取消（空串）直接中止；js bridge 序列化异常拿到数组时归一化。
  try {
    if (window.pywebview && pywebview.api && pywebview.api.pick_dir) {
      let dir = await pywebview.api.pick_dir();
      if (Array.isArray(dir)) dir = dir[0] || '';
      if (dir) return addTreeRoot(dir);
      return;   // 用户取消
    }
  } catch(e) {}
  // js bridge 不可用兜底：内联输入（WebView2 可能禁 window.prompt）
  _treeInlineDirInput();
}
function _treeInlineDirInput() {
  const host = $('treeRoots');
  if (host.dataset.editing) return;
  host.dataset.editing = '1';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = '输入文件夹绝对路径，回车确认';
  input.style.cssText = 'width:100%;font-family:var(--font-mono);font-size:10px;background:var(--bg-input,#111);border:1px solid var(--accent);border-radius:5px;padding:4px 6px;color:var(--fg);outline:none;margin:4px 0';
  host.insertBefore(input, host.firstChild);
  input.focus();
  let done = false;
  const finish = (apply) => {
    if (done) return; done = true;
    delete host.dataset.editing;
    input.remove();
    if (apply) { const v = input.value.trim().replace(/^["']|["']$/g, ''); if (v) addTreeRoot(v); }
  };
  input.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}

// ---- 根列表渲染（每根一行头 + 可展开根节点）----

const _TV = {
  roots: [],            // [{path, name}]
  open: new Set(),      // 展开的目录 path
  cache: new Map(),     // path -> {entries, truncated} | {err}
  rows: [],             // 扁平行 [{t, path, name, dir, depth, open, n, msg}]
  idx: new Map(),       // path -> 行号（对焦 O(1)）
  seq: new Map(),       // path -> fetch 序号（防乱序，v2 的 children 级同款）
  active: '',           // 当前选中文件行（虚拟化后 class 态必须进数据）
  rendered: [-1, -1],
  ROW_H: 22, BUF: 12,
  raf: 0,
};

function _tvPad(depth) { return 6 + depth * 14; }

// ---- 扁平行数组推导（DFS）+ 索引/宽度估算 ----
function _tvRebuild() {
  const rows = [];
  for (const root of _TV.roots) {
    rows.push({ t: 'root', path: root.path, name: root.name, dir: true,
                depth: 0, open: _TV.open.has(root.path) });
    _tvPush(rows, root.path, 1);
  }
  _TV.rows = rows;
  _TV.idx = new Map(rows.map((r, i) => [r.path, i]));
  _TV.rendered = [-1, -1];
  _tvPaint();
}

function _tvPush(rows, path, depth) {
  if (!_TV.open.has(path)) return;
  const c = _TV.cache.get(path);
  if (!c) { rows.push({ t: 'loading', path, depth }); return; }
  if (c.err) { rows.push({ t: 'err', depth, msg: c.err }); return; }
  for (const e of c.entries) {
    rows.push({ t: e.dir ? 'dir' : 'file', path: e.path, name: e.name,
                dir: !!e.dir, depth, open: _TV.open.has(e.path) });
    if (e.dir) _tvPush(rows, e.path, depth + 1);
  }
  if (c.truncated) rows.push({ t: 'more', depth, n: c.truncated });
}

// ---- 窗口渲染（hex-diff 同款窗口模式：innerHTML 重建，行数 ~50 成本可忽略）----
function _tvRowHtml(r, i) {
  const top = i * _TV.ROW_H;
  const pad = _tvPad(r.depth);
  const st = `top:${top}px;left:0;padding-left:${pad}px;` + (r.depth > 20 ? '' : '');
  if (r.t === 'loading')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">加载中…</div>`;
  if (r.t === 'err')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">${esc(r.msg || '读取失败')}</div>`;
  if (r.t === 'more')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">…还有 ${Number(r.n).toLocaleString()} 项未显示</div>`;
  const arrow = r.dir
    ? `<span class="arrow"${r.open ? ' style="transform:rotate(90deg)"' : ''}>▶</span>` : '<span class="arrow"></span>';
  const icon = r.t === 'root' ? dirIconHtml(r.open, 14)
             : r.dir ? dirIconHtml(r.open, 13) : fileIconHtml(r.name, 13);
  const active = r.path === _TV.active ? ' active' : '';
  const rootX = r.t === 'root'
    ? `<span class="root-x" title="从文件树移除该文件夹（不删除磁盘文件）">✕</span>` : '';
  return `<div class="tree-row${r.t === 'root' ? ' tree-root-head' : ''}${active}" data-path="${esc(r.path)}"` +
    (r.dir ? ' data-dir="1"' : '') + ` data-depth="${r.depth}"` +
    (r.t === 'root' ? ' data-notrunc="1"' : '') +
    ` style="${st}">${arrow}${icon}<span class="t-name" title="${esc(r.path)}">${esc(r.name)}</span>${rootX}</div>`;
}

function _tvPaint() {
  const host = $('treeRoots');
  if (!host) return;
  const total = _TV.rows.length;
  let sizer = host.querySelector('.tree-sizer');
  if (!sizer) {
    sizer = document.createElement('div');
    sizer.className = 'tree-sizer';
    host.appendChild(sizer);
  }
  if (!total) {
    sizer.innerHTML = host.querySelector('.tree-empty') ? '' : '';
    return;
  }
  // sizer 宽度：全树最深+最长行的估算（mono 11px ≈ 7.2px/字符，含箭头图标 42px
  // 余量）——撑出横滚让深层长名完整可达（用户实锤语义：不许省略号裁名）
  let wMax = 0;
  for (const r of _TV.rows) {
    if (!r.name) continue;
    const w = _tvPad(r.depth) + r.name.length * 7.2 + 60;
    if (w > wMax) wMax = w;
  }
  sizer.style.height = (total * _TV.ROW_H) + 'px';
  sizer.style.minWidth = Math.max(100, Math.round(wMax)) + 'px';
  const first = Math.max(0, Math.floor(host.scrollTop / _TV.ROW_H) - _TV.BUF);
  const count = Math.ceil(host.clientHeight / _TV.ROW_H) + _TV.BUF * 2;
  const from = first, to = Math.min(total, first + count);
  if (from === _TV.rendered[0] && to === _TV.rendered[1] && sizer.children.length) return;
  let html = '';
  for (let i = from; i < to; i++) html += _tvRowHtml(_TV.rows[i], i);
  sizer.innerHTML = html;
  _TV.rendered = [from, to];
}

// ---- 展开 / 折叠（数据操作 + 重建；fetch 按 path 记 seq 防乱序）----
async function _tvExpand(path) {
  _TV.open.add(path);
  const seq = (_TV.seq.get(path) || 0) + 1;
  _TV.seq.set(path, seq);
  _tvRebuild();          // loading 行立即出现
  let j;
  try {
    const r = await fetch('/api/tree/list', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path, hidden: _treeShowHidden})});
    j = await r.json();
  } catch(e) {
    if (_TV.seq.get(path) === seq) { _TV.cache.set(path, {err: '读取失败'}); _tvRebuild(); }
    return;
  }
  if (_TV.seq.get(path) !== seq) return;   // 后发请求已覆盖，本次作废
  if (!j.ok) { _TV.cache.set(path, {err: j.err || '读取失败'}); _tvRebuild(); return; }
  _TV.cache.set(path, {entries: j.entries || [], truncated: j.truncated || 0});
  _tvRebuild();
  _tvFocus(path, true);  // 展开对焦：父行钉视口 + 子行首行露出（v2 语义）
}

function _tvCollapse(path) {
  _TV.open.delete(path);
  _TV.cache.delete(path);   // 折叠即弃缓存（v2 只读视图不缓存，同款）
  _tvRebuild();
  _tvFocus(path);           // 折叠对焦被折叠行
}

// ---- 对焦（v2 _treeReveal 语义的虚拟化版：纵向行号判据，横向按缩进深度）----
function _tvFocus(path, firstChild) {
  const host = $('treeRoots');
  const i = _TV.idx.get(path);
  if (!host || i === undefined) return;
  const H = _TV.ROW_H, vpad = 40;
  let minTop = i * H, maxBottom = minTop + H;
  if (firstChild) {
    const c = _TV.rows[i + 1];   // 子层首行（或 loading/截断行）
    if (c) maxBottom = (i + 1) * H + H;
  }
  let vy = host.scrollTop;
  if (minTop < host.scrollTop) vy = Math.max(0, minTop - vpad);
  else if (maxBottom > host.scrollTop + host.clientHeight)
    vy = Math.max(0, maxBottom - host.clientHeight + vpad);
  // 横向：子层缩进左缘（首元素真实左缘 ≈ 行 padding）双向滚入
  const depth = (_TV.rows[i] || {}).depth || 0;
  const left = _tvPad(depth + 1);
  let hx = host.scrollLeft;
  if (left > host.scrollLeft + host.clientWidth) hx = Math.max(0, left - 24);
  else if (left < host.scrollLeft) hx = Math.max(0, left - 24);
  if (hx !== host.scrollLeft || vy !== host.scrollTop)
    host.scrollTo({ left: hx, top: vy, behavior: 'smooth' });
}

// ---- 根列表 ----
async function refreshTree() {
  const host = $('treeRoots');
  if (!host) return;
  if (host.dataset.editing) return;   // 内联输入中不重建
  let roots = [];
  try {
    const r = await fetch('/api/tree/roots');
    const j = await r.json();
    if (j.ok) roots = j.roots || [];
  } catch(e) { return; }
  if (!roots.length) {
    _TV.roots = []; _TV.open.clear(); _TV.cache.clear();
    _tvRebuild();
    const host2 = $('treeRoots');
    let s = host2.querySelector('.tree-sizer');
    if (s) s.remove();
    host2.innerHTML = `<div class="tree-empty">点击上方「打开文件夹」选择目录，<br>或直接把文件夹拖进窗口</div>`;
    return;
  }
  // v2.59 同语义：刷新 = 收起态复位（展开集/缓存清空）
  _TV.roots = roots.map(p => ({ path: p, name: (p.split(/[\\/]/).pop() || p) }));
  _TV.open.clear();
  _TV.cache.clear();
  _TV.rendered = [-1, -1];
  _tvRebuild();
  host.scrollTop = 0;
}

// ---- 显示隐藏文件开关（展开集整体重拉，全部落账后一次重建）----
let _treeShowHidden = false;
function _treeSyncHiddenBtn() {
  const btn = $('treeHidden');
  btn.textContent = _treeShowHidden ? '隐藏' : '显示';
  btn.classList.toggle('primary', _treeShowHidden);
  btn.title = _treeShowHidden ? '当前显示隐藏文件，点击隐藏 . 开头条目' : '显示 . 开头的隐藏文件';
}
async function _treeToggleHidden() {
  _treeShowHidden = !_treeShowHidden;
  _treeSyncHiddenBtn();
  const paths = [..._TV.open];
  await Promise.all(paths.map(async p => {
    const seq = (_TV.seq.get(p) || 0) + 1;
    _TV.seq.set(p, seq);
    try {
      const r = await fetch('/api/tree/list', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({path: p, hidden: _treeShowHidden})});
      const j = await r.json();
      if (_TV.seq.get(p) !== seq) return;
      if (j.ok) _TV.cache.set(p, {entries: j.entries || [], truncated: j.truncated || 0});
    } catch(_) {}
  }));
  _tvRebuild();
}

// ---- 滚动：rAF 节流窗口重渲 ----
$('treeRoots').addEventListener('scroll', () => {
  if (_TV.raf) return;
  _TV.raf = requestAnimationFrame(() => { _TV.raf = 0; _tvPaint(); });
}, { passive: true });

// ---- 事件委托（click/contextmenu 语义与 v2 一致）----
$('treePane').addEventListener('click', async e => {
  const x = e.target.closest('.root-x');
  if (x) {
    e.stopPropagation();
    const path = x.closest('[data-path]').dataset.path;
    try {
      const r = await fetch('/api/tree/remove_root', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
      const j = await r.json();
      if (j.ok) refreshTree(); else showBanner(j.err || '移除失败', 4000, true);
    } catch(err) { showBanner('移除失败: ' + err, 4000, true); }
    return;
  }
  const row = e.target.closest('[data-path]');
  if (!row) return;
  const path = row.dataset.path;
  if (row.dataset.dir === '1') {
    // 根行（无缓存记录的 path 且在 roots）也走同一开关
    if (_TV.open.has(path)) _tvCollapse(path);
    else _tvExpand(path);
    return;
  }
  if (typeof openFileSmart === 'function') {
    _TV.active = path;
    _tvPaint();
    openFileSmart(path, 'auto');
    _tvFocus(path);
  }
});

$('treePane').addEventListener('contextmenu', e => {
  const row = e.target.closest('[data-path]');
  if (!row) return;
  e.preventDefault();
  const path = row.dataset.path;
  const isDir = row.dataset.dir === '1';
  const m = $('ctxMenu');
  m.innerHTML = `<div class="ctx-item" data-act="reveal">📂 在资源管理器中${isDir ? '打开' : '显示'}</div>`;
  m.style.display = 'block';
  m.style.left = Math.min(e.clientX, window.innerWidth - m.offsetWidth - 4) + 'px';
  m.style.top = Math.min(e.clientY, window.innerHeight - m.offsetHeight - 4) + 'px';
  m.querySelectorAll('.ctx-item').forEach(it => {
    it.onclick = async () => {
      hideCtxMenu();
      try {
        const r = await fetch('/api/tree/reveal', {method:'POST',
          headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
        const j = await r.json();
        if (!j.ok) showBanner(j.err || '打开失败', 4000, true);
      } catch(err) { showBanner('打开失败: ' + err, 4000, true); }
    };
  });
});

$('treeAddRoot').onclick = () => pickTreeDir();
$('treeHidden').onclick = () => _treeToggleHidden();
$('treeRefresh').onclick = () => {
  refreshTree();
  showBanner('目录已刷新', 1600);
};
_treeSyncHiddenBtn();

refreshTree();
