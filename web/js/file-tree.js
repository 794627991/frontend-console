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
  idxLower: new Map(),  // a382R：path.toLowerCase() -> 真实 path（大小写兜底 O(1)）
  seq: new Map(),       // path -> fetch 序号（防乱序，v2 的 children 级同款）
  active: '',           // 当前选中文件行（虚拟化后 class 态必须进数据）
  rendered: [-1, -1],
  decos: new Map(),    // a209批1：path -> {open, dirty}（编辑器联动装饰，paint 前现算）
  focus: '',           // a209批4 预留：键盘导航焦点行
  wMax: 0,             // 全树最宽行估算（rebuild 算一次；对抗审 a205R：原在
                       // paint 每帧全扫 rows，6301 行树滚动即每帧 O(n) 白耗）
  crumbsKey: '',       // 面包屑当前渲染的祖先链签名（变化才碰 DOM）
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
  // a382R（第3轮审计 P3-2）：大小写不敏感索引。treeReveal 的兜底查找原先
  // 每次全表遍历 + 逐键 toLowerCase（万级行 × 每次切编辑器 tab 都触发），
  // 建表后是 O(1)。
  _TV.idxLower = new Map();
  for (const r of rows) {
    const _l = String(r.path).toLowerCase();
    if (!_TV.idxLower.has(_l)) _TV.idxLower.set(_l, r.path);
  }
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
  // a253（用户定调）：✕ 挪到 wrap 层、跨两行整体垂直居中——名字+路径是
  // 一个整体，✕ 只跟名字行居中时视觉上"跑到了上面"
  if (r.t === 'root') {
    return `<div class="tree-root-wrap tree-root-head" data-path="${esc(r.path)}" data-dir="1" style="top:${top}px;left:0;width:max-content;min-width:100%">` +
      `<div class="tree-row tree-root-head${active}" data-dir="1" data-depth="0" data-notrunc="1"` +
      ` style="position:relative;left:0;top:0;padding-left:6px;">${arrow}${icon}<span class="t-name" title="${esc(r.path)}">${esc(r.name)}</span>${dot}</div>` +
      `<div class="tree-root-path">${esc(r.path)}</div>${rootX}</div>`;
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
async function treeReveal(path, opts) {
  // a336（用户需求1）：编辑器打开文件时同步定位到文件树。
  // 前提：该文件在已打开的根目录之下（else 直接返回，不打扰用户）。
  // 调用方传 {scroll:true} 时才滚动到可见——搜索结果点击（旧调用方）
  // 本来就靠这个定位，一并受益；不传时保持原行为（仅高亮）。
  const o = opts || {};
  if (!path) return false;
  // a375R（第1轮审计 P1-2/P2-1）：路径形态必须**先归一成树键形态**再判。
  // 树键来自 os.scandir 的 e.path，恒为「反斜杠 + 无尾分隔符」；而真实入口
  // 会给正斜杠（tree-fileops 的 joinPath）或混合形态（rg 输出的
  // `D:/AI/proj/src\file.py`）。此前 inRoot 归一了、下游 chain/idx/active
  // 没有 → 门开了但定位全失效，表现为「有时灵有时不灵」。
  const _np = _tvNormPath(path);
  // 盘根 / UNC 根必须有尾分隔符才能拼接比较：后端 abspath('D:\\') 保留尾
  // 分隔符，`rp + '\\'` 会变成 'D:\\\\'，任何子文件都不匹配（P1-2 实锤）。
  const inRoot = (_TV.roots || []).some(function (r) {
    const rp = _tvNormPath(r.path).replace(/\\+$/, '');
    return _np.toLowerCase() === rp.toLowerCase() ||
           _np.toLowerCase().startsWith(rp.toLowerCase() + '\\');
  });
  if (!inRoot) return false;
  // a382R（第3轮审计 P2-3）/ a384R（第4轮审计 P2 实锤）：父目录逐级展开必须
  // 用**磁盘真实大小写**，否则后端 _under_roots 的大小写敏感前缀比较会 400。
  // 但起点不能取 chain[0]——那是盘符层 `d:` 或 UNC 前缀 `\\`，`_tvExpand('d:')`
  // 在后端经 abspath 会落到**当前进程 cwd**，拿到完全无关的目录列表。
  // 正确起点 = _TV.roots 里**匹配到的那个根**（它本身已是真实大小写），
  // 从根往下逐段按父目录 cache 的条目名纠正。
  const _root = (_TV.roots || []).filter(function (r) {
    const rp = _tvNormPath(r.path).replace(/\\+$/, '');
    return _np.toLowerCase() === rp.toLowerCase() ||
           _np.toLowerCase().startsWith(rp.toLowerCase() + '\\');
  }).sort(function (a, b) {
    // 嵌套根时取更深的那个（长匹配优先）
    return _tvNormPath(b.path).length - _tvNormPath(a.path).length;
  })[0];
  // a385R（第5轮审计 P1 实锤）：这里**不能**去掉尾分隔符。盘根注册为
  // `D:\` 时，`_tvNormPath` 特意保留尾分隔符（否则 'D:\' 与 'D:' 同形），
  // 而下面无条件 `.replace(/\\+$/,'')` 又把它剥成 `D:` —— 后端
  // `os.path.abspath('D:')` 会解析成**当前进程 cwd**，第一轮就展开完全
  // 无关的目录列表，本轮要修的小写定位在盘根场景 100% 复现。
  // 保留原样后 `segs = _np.slice(rootReal.length)` 对 `D:\AI\x.py` 得
  // `AI\x.py`，切分正确；普通根本就无尾分隔符，不受影响。
  const rootReal = _tvNormPath(_root.path);
  // 从根到目标文件的逐段路径（根之后的部分）
  const segs = _np.slice(rootReal.length).split('\\').filter(Boolean);
  // 逐层展开：parent 从根开始，每展开一层就按 cache 里的真实名纠正下一段
  let parent = rootReal;
  for (let si = 0; si < segs.length; si++) {
    if (!_TV.open.has(parent)) {
      _tvExpand(parent);
      // 等待 cache 落地（拉取完成）——轮询 2s 兜底
      const t0 = Date.now();
      while (!_TV.cache.has(parent) && Date.now() - t0 < 2000) {
        await new Promise(r => setTimeout(r, 80));
        // a375R（审计 P2-2）：并发 reveal 时后发先至——被更新的请求取代就
        // 丢弃本次（否则先发慢完成的会把高亮/滚动覆盖回旧的）
        if (o._seq !== undefined && o._seq !== _tvRevealSeq) return false;
      }
    }
    const seg = segs[si];
    const c = _TV.cache.get(parent);
    // a384R：按大小写不敏感找真实名；**找不到就不改**（不能用猜测的段名
    // 拼出无关路径去展开——第4轮审计 P3 提到 cwd 同名目录会被误匹配）
    const ent = (c && c.entries && !c.err) ? c.entries.filter(function (e) {
      return e && String(e.name).toLowerCase() === seg.toLowerCase();
    })[0] : null;
    if (!ent) {
      // 该段不在父目录列表里（截断/隐藏/权限）：后面无法继续，直接落笔
      // 到「按原样拼接」的路径，由末端 idx 查找与 banner 兜底
      parent = null;
      break;
    }
    parent = ent.path;                 // 真实大小写
  }
  const _npReal = parent || _np;
  // a375R（审计 P2-2）：落笔前再比一次序号
  if (o._seq !== undefined && o._seq !== _tvRevealSeq) return false;
  // a380R（第2轮审计 P3-3）：_TV.idx 的键来自 os.scandir（磁盘真实大小写），
  // 而归一路径的盘符/目录大小写可能与之不同（Monaco 的 modelFilePath 给的是
  // 小写盘符）。直接 get 会扑空 → 高亮画不出来还弹「不在树中」的误报。
  // 先精确命中（用逐层纠正后的真实大小写），再退回大小写不敏感索引。
  let _key = _npReal;
  if (!_TV.idx.has(_key)) {
    _key = (_TV.idxLower && _TV.idxLower.get(_npReal.toLowerCase())) || _npReal;
  }
  _TV.active = _key;
  _TV.rendered = [-1, -1];
  _tvPaint();
  if (o.scroll) _tvScrollToPath(_key);
  // a375R（审计 P2-8）：目标行不在当前树视图（父目录被截断/文件被隐藏/
  // 形态不匹配）时，连高亮都画不出来——用户会觉得「点了没反应」。明说。
  if (!_TV.idx.has(_key)) {
    showBanner('该文件不在当前文件树视图中（可能被截断、隐藏或未在已打开的根下）', 3200);
  }
  return true;
}

// 路径归一：正斜杠→反斜杠、去尾分隔符、折叠重复分隔符。
// 只做形态归一，不动盘符大小写（比较处单独 toLowerCase）。
function _tvNormPath(p) {
  let s = String(p || '').replace(/\//g, '\\');
  // a377R（第2轮审计实锤）：UNC 前缀 `\\server\share` 的开头两个反斜杠是
  // 语义，不是重复分隔符——无脑 `\\{2,}` → `\` 会把 UNC 压成根相对路径，
  // UNC 项目下文件树定位整个失效。先摘出前缀，折叠完再拼回。
  const unc = /^\\\\/.test(s);
  if (unc) s = s.slice(2);
  s = s.replace(/\\{2,}/g, '\\');
  if (s.length > 1 && !/^[A-Za-z]:\\$/.test(s)) s = s.replace(/\\+$/, '');
  return unc ? '\\\\' + s : s;
}
// a375R：并发 reveal 序号（见 treeReveal 内的比对）。
// 包装在 window.treeReveal 上——内部调用方（含同文件）一律走包装版。
let _tvRevealSeq = 0;
const _treeRevealImpl = treeReveal;
window.treeReveal = function (path, opts) {
  _tvRevealSeq++;
  const _o = Object.assign({}, opts || {});
  _o._seq = _tvRevealSeq;
  // a375R（审计 P2-2）：返回值是 Promise，调用方（_edOnSwitchEditor）不 await
  // ——内部 rejection 会变成 unhandled rejection。这里统一吞掉并留日志。
  try {
    const r = _treeRevealImpl(path, _o);
    if (r && typeof r.catch === 'function') {
      r.catch(function (e) { if (window.console) console.warn('treeReveal:', e); });
    }
    return r;
  } catch (e) {
    if (window.console) console.warn('treeReveal:', e);
    return Promise.resolve(false);
  }
};

// a336：把目标行滚到可视区中部（VSCode 资源管理器 reveal 同款观感）。
// 虚拟列表自行管理 scrollTop，这里直接写滚动位置并让 _tvPaint 重绘窗口。
function _tvScrollToPath(path) {
  const host = $('treeRoots');
  if (!host) return;
  const i = _TV.idx.get(path);
  if (i === undefined || !_TV.tops) return;
  // a336：侧栏 sheet 可能没切到「文件树」（pane display:none → clientHeight=0）。
  // 此时先算出 desirable scrollTop，等可见时再补一次——否则这次定位的滚动
  // 白丢，用户切过去只能看到高亮在视口外。
  const apply = function () {
    const viewH = host.clientHeight || 0;
    if (!viewH) return false;
    const rowTop = _TV.tops[i];
    const rowH = _TV.ROW_H + (_TV.rows[i] && _TV.rows[i].t === 'root' ? 14 : 0);
    host.scrollTop = Math.max(0, rowTop - viewH / 2 + rowH / 2);
    _tvPaint();
    return true;
  };
  if (apply()) return;
  // 不可见：轮询到可见为止（2s 兜底，避免隐藏整天的标签页里挂个定时器）
  const t0 = Date.now();
  const tick = function () {
    if (apply()) return;
    if (Date.now() - t0 < 2000) setTimeout(tick, 120);
  };
  setTimeout(tick, 120);
}

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
  // a244（用户实锤截图）：空态提示是 refreshTree 用 innerHTML 塞进 host 的
  // 兄弟节点，添加首个根后 sizer 重建渲染，但残留的 .tree-empty 无人清
  // ——树与"点击上方打开文件夹"共存。所有渲染路径必经此处，统一拔除。
  if (total) { const e = host.querySelector('.tree-empty'); if (e) e.remove(); }
  if (!total) { sizer.innerHTML = ''; _tvCrumbsPaint(); return; }
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
  if (from === _TV.rendered[0] && to === _TV.rendered[1] && sizer.children.length) {
    _tvCrumbsPaint();
    return;
  }
  let html = '';
  for (let i = from; i < to; i++) html += _tvRowHtml(_TV.rows[i], i);
  sizer.innerHTML = html;
  _TV.rendered = [from, to];
  _tvCrumbsPaint();
}

// ---- 目录面包屑（VSCode sticky scroll 同款）：滚动后仍知道这屏属于哪个目录 ----
// 取视口顶部那一行，沿 rows 向前回溯它的祖先目录（行数组是 DFS 扁平结构，
// 祖先就是「depth 更小且尚未闭合」的那些行）。
// 显示规则对齐 VSCode：只要滚出了根目录（scrollTop > 0）且顶部行不是根行，
// 就常驻显示完整祖先链——不做「父行还可见就隐藏」之类的启发式：显隐来回
// 切换本身就是抽搐的来源，而且用户明确说过整目录时不显示最顶层不正常。
// 覆盖层绝对定位，完全不参与布局，所以常显也没有副作用。
function _tvCrumbsPaint() {
  const el = $('treeCrumbs');
  if (!el) return;
  const host = $('treeRoots');
  const rows = _TV.rows || [];
  const tops = _TV.tops || [];
  const wrap = el.closest('.tree-scroll-wrap');
  const show = () => {
    const wasHidden = el.hidden || !wrap || !wrap.classList.contains('has-crumbs');
    // a438（审计 P2）：让位式会让视口矮 22px、maxScroll 涨 22px。浏览器不会
    // 自动补这段差值——「End 键 / 拖滚动条到底」这类一次性跳到底的路径会
    // 停在旧 max 上，末行下沿被裁 10px，要再滚一次才真到底。
    // 只在「切换前就已贴底」时补，其它位置一律不动用户视野（短树里刚滚
    // 22px 也可能距底很近，用 d<=22 判会误跳成抽搐）。
    const atBottom = !!(wasHidden && host &&
      host.scrollTop + host.clientHeight >= host.scrollHeight - 1);
    el.hidden = false;
    if (wrap) wrap.classList.add('has-crumbs');
    if (atBottom) host.scrollTop = host.scrollHeight;
  };
  const hide = () => {
    if (wrap) wrap.classList.remove('has-crumbs');
    if (!el.hidden) { el.hidden = true; el.innerHTML = ''; _TV.crumbsKey = ''; }
  };
  if (!host || !rows.length || !tops.length) { hide(); return; }
  // 视口顶部那一行（scrollTop 落在哪行的区间里）
  let lo = 0, hi = rows.length - 1, cur = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((tops[mid] || 0) <= host.scrollTop) { cur = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  // 顶部就是根行（还没滚出根）：根名就在眼前，不必重复
  if (rows[cur].t === 'root') { hide(); return; }
  // 回溯祖先：DFS 扁平序里，祖先 = 前面 depth 更小的最近一行
  const chain = [];
  let want = rows[cur].depth;
  for (let i = cur; i >= 0 && want > 0; i--) {
    const r = rows[i];
    if (r.t === 'root') { chain.unshift({ path: r.path, name: r.name }); break; }
    if (r.dir && r.depth < want) {
      chain.unshift({ path: r.path, name: r.name });
      want = r.depth;
    }
  }
  if (!chain.length) { hide(); return; }
  const key = chain.map(c => c.path).join('\u0000');
  if (key === _TV.crumbsKey && !el.hidden && wrap && wrap.classList.contains('has-crumbs')) return;
  _TV.crumbsKey = key;
  el.innerHTML = chain.map(c =>
    `<div class="tree-crumb" data-crumb-path="${esc(c.path)}" title="${esc(c.path)}">` +
    dirIconHtml(true, 12) +
    `<span>${esc(c.name || c.path)}</span></div>`
  ).join('<span class="tree-crumb-sep">›</span>');
  show();
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
}

// a3xx（用户定调「跟随我都说了，全删，说全删就要全删，别留」）：
// _tvFocus 整套删除——点树项/展开/折叠后的自动滚动跟随全部去掉。
// 原来纵横向都跟随；用户两次明确要求删干净，不留半套。

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
    _tvCrumbsPaint();
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
// a258：眼睛图标两态（工具条 SVG 统一——文字钮退役）
const _EYE_SVG = (on) => '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
  (on
    ? '<path d="M1.8 8s2.4-4.2 6.2-4.2S14.2 8 14.2 8s-2.4 4.2-6.2 4.2S1.8 8 1.8 8z"/><circle cx="8" cy="8" r="2.1"/>'
    : '<path d="M1.8 8s2.4-4.2 6.2-4.2c1.5 0 2.8.5 3.9 1.2"/><path d="M14.2 8s-2.4 4.2-6.2 4.2c-1.5 0-2.8-.5-3.9-1.2"/><path d="M2.5 13.5l11-11"/>') +
  '</svg>';
function _treeSyncHiddenBtn() {
  const btn = $('treeHidden');
  if (!btn) return;
  btn.innerHTML = _EYE_SVG(_treeShowHidden);
  btn.classList.toggle('on', _treeShowHidden);
  btn.title = _treeShowHidden ? '隐藏文件显示中（. 开头条目）——点击隐藏' : '显示 . 开头的隐藏文件';
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
    }
});

// a209批2：contextmenu/快捷键/文件操作移驻 tree-fileops.js（命令层独立）

// 面包屑点击：把该目录行滚回视口顶部（VSCode 点面包屑跳回父级的同款语义）
$('treeCrumbs').addEventListener('click', e => {
  const c = e.target.closest('[data-crumb-path]');
  if (!c) return;
  const path = c.dataset.crumbPath;
  const i = _TV.idx.get(path);
  const host = $('treeRoots');
  if (i === undefined || !_TV.tops || !host) return;
  host.scrollTop = Math.max(0, _TV.tops[i] - 2);
  _tvPaint();
});

$('treeAddRoot').onclick = () => pickTreeDir();
$('treeHidden').onclick = () => _treeToggleHidden();
$('treeRefresh').onclick = () => {
  refreshTree();
  showBanner('目录已刷新', 1600);
};
_treeSyncHiddenBtn();
_tvDecosCalc();          // a209批1：初始装饰（后续由 editor.js 调 treeDecoRefresh）

refreshTree();
