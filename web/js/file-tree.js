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
  decos: new Map(),    // a209批1：path -> {open, dirty}（编辑器联动装饰，paint 前现算）
  focus: '',           // a209批4 预留：键盘导航焦点行
  wMax: 0,             // 全树最宽行估算（rebuild 算一次；对抗审 a205R：原在
                       // paint 每帧全扫 rows，6301 行树滚动即每帧 O(n) 白耗）
  ROW_H: 22, BUF: 12,
  raf: 0,
};
window._TV = _TV;   // a213 审计 P0：顶层 const 不进 window——tree-fileops/
                    // tree-search 读 window._TV 全 undefined（键盘/相对路径/
                    // 全根搜索三链死读的根因，三审计交叉实锤）

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
  _TV.wMax = 0;
  for (const r of rows) {
    if (!r.name) continue;
    const w = _tvPad(r.depth) + Math.min(r.name.length, 4096) * 7.2 + 60;   // a235: 敌意超长名封顶（5MB 名曾致 907ms 布局逼近红线）
    if (w > _TV.wMax) _TV.wMax = w;
  }
  _tvTops();
  _TV.rendered = [-1, -1];
  _tvPaint();
}

// a225：累计高度数组（根行=36px 含路径子行，其余 22px）。top(i)=tops[i]，
// 总高=末项+末行高；scrollTop→行号用二分（_tvPaint）
function _tvTops() {
  const n = _TV.rows.length;
  const tops = new Array(n);
  let y = 0;
  for (let i = 0; i < n; i++) {
    tops[i] = y;
    y += _TV.ROW_H + (_TV.rows[i].t === 'root' ? 14 : 0);
  }
  _TV.tops = tops;
  _TV.totalH = y;
}

function _tvPush(rows, path, depth) {
  if (!_TV.open.has(path)) return;
  const c = _TV.cache.get(path);
  if (!c) { rows.push({ t: 'loading', path, depth }); return; }
  if (c.err) { rows.push({ t: 'err', depth, msg: c.err }); return; }
  if (!c.entries.length) { rows.push({ t: 'empty', depth }); return; }
  // a236 fuzz P2: 后端重复 path（嵌套根天然产生）曾致 48 行同 active+跳转
  // /操作目标分裂——入缓存前按 path 去重（保持后写胜并入语义）；
  // P1 纵深：name 强转 String（非字符串曾致 fileIconHtml TypeError）
  const seen = new Set();
  const entries = [];
  for (const raw of c.entries) {
    if (!raw || raw.path === undefined || seen.has(raw.path)) continue;
    seen.add(raw.path);
    let _nm = raw.name;   // a239 B4-P3: 敌意 toString() 副作用防护（String(raw.name) 可被劫持抛出穿透 rebuild）
    if (typeof _nm !== 'string') { try { _nm = String(_nm == null ? '' : _nm); } catch (_) { _nm = ''; } }
    entries.push({ dir: !!raw.dir, name: _nm,
                   path: String(raw.path) });
  }
  for (const e of entries) {
    rows.push({ t: e.dir ? 'dir' : 'file', path: e.path, name: e.name,
                dir: !!e.dir, depth, open: _TV.open.has(e.path) });
    if (e.dir) _tvPush(rows, e.path, depth + 1);
  }
  if (c.truncated) rows.push({ t: 'more', depth, n: c.truncated });
}

// ---- 窗口渲染（hex-diff 同款窗口模式：innerHTML 重建，行数 ~50 成本可忽略）----
// a225：行高不恒定（根行=名字行+路径小字行共 36px）——top 取累计高度数组
// _TV.tops（rebuild 时 O(n) 算一次）；scrollTop→行号换算在 _tvPaint 二分
function _tvRowHtml(r, i) {
  const top = _TV.tops ? _TV.tops[i] : i * _TV.ROW_H;
  const pad = _tvPad(r.depth);
  const st = `top:${top}px;left:0;padding-left:${pad}px;`;
  if (r.t === 'loading')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">加载中…</div>`;
  if (r.t === 'err')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">${esc(r.msg || '读取失败')}</div>`;
  if (r.t === 'more')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">…还有 ${Number(r.n).toLocaleString()} 项未显示</div>`;
  if (r.t === 'empty')
    return `<div class="tree-more" style="top:${top}px;left:0;padding-left:${pad}px">（空目录）</div>`;
  const arrow = r.dir
    ? `<span class="arrow"${r.open ? ' style="transform:rotate(90deg)"' : ''}>▶</span>` : '<span class="arrow"></span>';
  const icon = r.t === 'root' ? dirIconHtml(r.open, 14)
             : r.dir ? dirIconHtml(r.open, 13) : fileIconHtml(r.name, 13);
  const active = r.path === _TV.active ? ' active' : '';
  const deco = (r.t === 'file' && _TV.decos.get(r.path)) || {};
  const openCls = deco.open ? ' tree-open' : '';
  const dot = deco.dirty ? '<span class="tree-dot-dirty" title="未保存修改">●</span>' : '';
  const rootX = r.t === 'root'
    ? `<span class="root-x" title="从文件树移除该文件夹（不删除磁盘文件）">✕</span>` : '';
  // a225：根行=双行容器（名字行 + 路径小字行）——多根同名场景（两个 trunk
  // 都叫 src 但实际路径不同）一眼可辨；路径灰显不抢焦点，hover 全路径
  if (r.t === 'root') {
    return `<div class="tree-root-wrap tree-root-head" data-path="${esc(r.path)}" data-dir="1" style="top:${top}px;left:0;width:max-content;min-width:100%">` +
      `<div class="tree-row tree-root-head${active}" data-dir="1" data-depth="0" data-notrunc="1"` +
      ` style="position:relative;left:0;top:0;padding-left:6px;">${arrow}${icon}<span class="t-name" title="${esc(r.path)}">${esc(r.name)}</span>${dot}${rootX}</div>` +
      `<div class="tree-root-path">${esc(r.path)}</div></div>`;
  }
  return `<div class="tree-row${active}${openCls}" data-path="${esc(r.path)}"` +
    (r.dir ? ' data-dir="1"' : '') + ` data-depth="${r.depth}"` +
    ` style="${st}">${arrow}${icon}<span class="t-name" title="${esc(r.path)}">${esc(r.name)}</span>${dot}${rootX}</div>`;
}

// a209批1：编辑器联动装饰现算（editor conn 的 extPath/dirty）。dirty/保存变化
// 走 treeDecoRefresh 轻刷新（只重算 decos + 失效窗口重渲，不动 rows/idx）
function _tvDecosCalc() {
  const m = new Map();
  try {
    for (const pid in connections) {
      const c = connections[pid];
      if (!c || !c.meta || c.meta.kind !== 'editor' || !c.extPath) continue;
      const d = m.get(c.extPath) || {};
      d.open = true;
      if (c.dirty) d.dirty = true;
      m.set(c.extPath, d);
    }
  } catch (_) {}
  _TV.decos = m;
}
function treeDecoRefresh() {
  _tvDecosCalc();
  _TV.rendered = [-1, -1];
  _tvPaint();
}
window.treeDecoRefresh = treeDecoRefresh;

// a209批2 预留：局部失效（文件操作后只重拉受影响目录，保留其余展开态）
function treeInvalidate(dirPath) {
  const p = String(dirPath || '');
  if (!p) return;
  _TV.cache.delete(p);
  if (_TV.open.has(p)) {
    _tvExpand(p);   // 展开态：重拉（内部 seq 自增防旧响应）
  } else {
    const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf(String.fromCharCode(92)));
    const parent = i > 0 ? p.slice(0, i) : '';
    if (parent && _TV.cache.has(parent)) _TV.cache.delete(parent);
    // a213 审计 P1：原 else 只清缓存不重拉——父目录展开态下 rebuild 后子层
    // 恒 loading 行无人 fetch，树卡「加载中」（未展开目录上新建即触发）。
    // 父展开则重拉；收起态清缓存即可（下次展开自然拉新）
    if (parent && _TV.open.has(parent)) _tvExpand(parent);
    else _tvRebuild();
  }
}
window.treeInvalidate = treeInvalidate;

// a209批3：reveal 到树（搜索结果点击文件头定位）——逐父段展开到目标，
// 期间显示 loading（复用展开态）；目标不可达（截断/权限）时提示
async function treeReveal(path) {
  // a213 审计 P1：原实现 norm 正斜杠逐段拼——与树键（后端 scandir 恒反斜杠）
  // 形成双键空间：open/cache 写幽灵正斜杠键、行推导永不命中（reveal 无效+
  // 同目录双 cache 污染）。改为原路径逐 dirname 上溯，键与树完全同形
  const chain = [];
  let cur = String(path);
  while (true) {
    const i = Math.max(cur.lastIndexOf('/'), cur.lastIndexOf(String.fromCharCode(92)));
    if (i <= 0) break;
    cur = cur.slice(0, i);
    chain.unshift(cur);
  }
  for (const dirPath of chain) {
    if (!_TV.open.has(dirPath)) {
      _tvExpand(dirPath);
      // 等待 cache 落地（拉取完成）——轮询 2s 兜底
      const t0 = Date.now();
      while (!_TV.cache.has(dirPath) && Date.now() - t0 < 2000) {
        await new Promise(r => setTimeout(r, 80));
      }
    }
  }
  _TV.active = path;
  _TV.rendered = [-1, -1];
  _tvPaint();
  _tvFocus(path);
}
window.treeReveal = treeReveal;

function _tvPaint() {
  const host = $('treeRoots');
  if (!host) return;
  if (host.dataset.editing) return;   // a231: 内联编辑中不冲掉 input（否则 editing 锁死）
  const total = _TV.rows.length;
  let sizer = host.querySelector('.tree-sizer');
  if (!sizer) {
    sizer = document.createElement('div');
    sizer.className = 'tree-sizer';
    host.appendChild(sizer);
  }
  if (!total) { sizer.innerHTML = ''; return; }
  // sizer 宽度用 rebuild 预计算值（撑横滚让深层长名完整可达——用户实锤
  // 语义：不许省略号裁名）
  sizer.style.height = (_TV.totalH || total * _TV.ROW_H) + 'px';
  sizer.style.minWidth = Math.max(100, Math.round(_TV.wMax)) + 'px';
  // a225：scrollTop→行号二分 tops（行高不恒定）
  const tops = _TV.tops || [];
  let lo = 0, hi = total - 1, from = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((tops[mid] || 0) <= host.scrollTop) { from = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  from = Math.max(0, from - _TV.BUF);
  let to = from;
  const visBottom = host.scrollTop + host.clientHeight + _TV.BUF * _TV.ROW_H;
  while (to < total && (tops[to] || 0) < visBottom) to++;
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
  // a208 实锤修复（用户报「展开后点不回去」）：原 a206C 版两个坑——
  // ①[..._TV.cache] 把 Map 展开成 [key, value] 二元组数组（Set 展开才是
  // 元素），k.startsWith 直接 TypeError 中断收起整链；②尾部斜杠正则在
  // 转义损耗下只匹配 / 不匹配 \（Windows 尾分隔符不吃）。改为
  // .keys() 迭代 + 零正则循环去尾
  // a213 审计 P3（a208 遗留）：pre 拼的是 '/' 而树键反斜杠——后代清理在
  // Windows 恒空转（只删本级）。归一化比较（双斜杠统一正斜杠）
  const _BS = String.fromCharCode(92);
  const _nk = (x) => String(x).split(_BS).join('/');
  const _self = _nk(path);
  const _pre = _self + '/';
  for (const k of [..._TV.open]) if (_nk(k) === _self || _nk(k).startsWith(_pre)) _TV.open.delete(k);
  for (const k of [..._TV.cache.keys()]) if (_nk(k) === _self || _nk(k).startsWith(_pre)) _TV.cache.delete(k);
  for (const k of [..._TV.seq.keys()]) if (_nk(k) === _self || _nk(k).startsWith(_pre)) _TV.seq.delete(k);
  _tvRebuild();
  _tvFocus(path);           // 折叠对焦被折叠行
}

// ---- 对焦（v2 _treeReveal 语义的虚拟化版：纵向行号判据，横向按缩进深度）----
function _tvFocus(path, firstChild) {
  const host = $('treeRoots');
  const i = _TV.idx.get(path);
  if (!host || i === undefined) return;
  const H = _TV.ROW_H, vpad = 40;
  const tops = _TV.tops || [];
  const minTop = (tops[i] !== undefined) ? tops[i] : i * H;
  let maxBottom = minTop + H;
  if ((_TV.rows[i] || {}).t === 'root') maxBottom += 14;   // 根行含路径子行
  if (firstChild) {
    // 子层首行=下一行且深度更大（对抗审 a206C：空目录/末行时下一行是
    // 兄弟或根，不得纳入对焦）
    const me = _TV.rows[i], c = _TV.rows[i + 1];
    if (c && me && c.depth > me.depth)
      maxBottom = (tops[i + 1] !== undefined ? tops[i + 1] : (i + 1) * H) + H;
  }
  let vy = host.scrollTop;
  if (minTop < host.scrollTop) vy = Math.max(0, minTop - vpad);
  else if (maxBottom > host.scrollTop + host.clientHeight)
    vy = Math.max(0, maxBottom - host.clientHeight + vpad);
  // 横向：双向滚入——展开对焦子层缩进左缘（depth+1）；折叠/点行对焦
  // 本行左缘（depth；对抗审 a205R：原恒 +1，折叠回浅层横滚偏一层）
  const depth = (_TV.rows[i] || {}).depth || 0;
  const left = _tvPad(firstChild ? depth + 1 : depth);
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
// 对抗审 a206C：sheet 隐藏期 clientHeight=0（首绘兜底 24 行）→ 切回/
// 窗口 resize 时无 scroll 事件，窗口不重算出现空带。ResizeObserver 一次
// 挂载兜住两类容器尺寸变化（幂等 paint，守卫挡重复）
try {
  new ResizeObserver(() => _tvPaint()).observe($('treeRoots'));
} catch (_) {}

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
    // 对抗审 a206C P1（CDP 实证）：active 写数据后 _tvPaint 的窗口判重
    // 守卫早退（from/to 未变）→ 高亮到不了 DOM；滚动/展开时才跳现且滞后
    // 一拍。active-only 变更必须失效窗口强制重渲
    _TV.active = path;
    _TV.rendered = [-1, -1];
    _tvPaint();
    openFileSmart(path, 'auto');
    _tvFocus(path);
  }
});

// a209批2：contextmenu/快捷键/文件操作移驻 tree-fileops.js（命令层独立）

$('treeAddRoot').onclick = () => pickTreeDir();
$('treeHidden').onclick = () => _treeToggleHidden();
$('treeRefresh').onclick = () => {
  refreshTree();
  showBanner('目录已刷新', 1600);
};
_treeSyncHiddenBtn();
_tvDecosCalc();          // a209批1：初始装饰（后续由 editor.js 调 treeDecoRefresh）

refreshTree();
