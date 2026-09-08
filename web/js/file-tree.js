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
    host.innerHTML = `<div class="tree-empty">点击上方「打开文件夹」选择目录，<br>或直接把文件夹拖进窗口</div>`;
    return;
  }
  let html = '';
  for (const root of roots) {
    const name = root.split(/[\\/]/).pop() || root;
    html += `
      <div class="tree-root" data-root="${esc(root)}">
        <div class="tree-root-head" data-path="${esc(root)}" data-dir="1" data-depth="0">
          <span class="arrow">▶</span>${dirIconHtml(false, 14)}
          <span class="t-name" title="${esc(root)}">${esc(name)}</span>
          <span class="root-x" title="从文件树移除该文件夹（不删除磁盘文件）">✕</span>
        </div>
      </div>`;
  }
  host.innerHTML = html;
}

// ---- 显示隐藏文件开关（VSCode files.exclude 同款语义）----
// 关（默认）：. 开头条目不显示也不算"还有 N 项"；开：全部显示。
// 切换后重拉所有【已展开】目录——open 态留在 dataset.open 上，重拉即保留展开层级。
let _treeShowHidden = false;
function _treeSyncHiddenBtn() {
  const btn = $('treeHidden');
  btn.textContent = _treeShowHidden ? '隐藏' : '显示';
  btn.classList.toggle('primary', _treeShowHidden);   // 按下态：青色主按钮
  btn.title = _treeShowHidden ? '当前显示隐藏文件，点击隐藏 . 开头条目' : '显示 . 开头的隐藏文件';
}
function _treeToggleHidden() {
  _treeShowHidden = !_treeShowHidden;
  _treeSyncHiddenBtn();
  // 展开态收集：所有 data-open=1 的行重新拉子层（children 已存在则直接复用容器）
  document.querySelectorAll('#treeRoots [data-open="1"]').forEach(row => {
    delete row.dataset.open;   // 让 _treeToggle 走"展开"分支（reload 语义）
    _treeToggle(row, true);
  });
}
// ---- 展开目录：children 容器插到【行后】（不是 root 末尾）——
// 之前 append 到 .tree-root 末尾，多目录展开后 children 按展开时间堆叠，
// 树序错乱（子项"跑"到别的目录下面，用户实锤报层级反直觉）。
// reload=true（隐藏文件开关切换）：容器已存在直接重拉内容，不动 open/图标态。
async function _treeToggle(row, reload) {
  const path = row.dataset.path;
  if (row.dataset.open === '1') {   // 折叠：销毁子 DOM（只读视图不缓存）
    const ch = row.parentElement.querySelector(`.tree-children[data-parent="${_cssEsc(path)}"]`);
    if (ch) ch.remove();
    delete row.dataset.open;
    const ar = row.querySelector('.arrow'); if (ar) ar.style.transform = '';
    const ic = row.querySelector('svg'); if (ic) ic.outerHTML = dirIconHtml(false, 14);
    return;
  }
  // 展开：容器插到本行正下方（树序 = 行序，天然正确）
  const depth = (+row.dataset.depth || 0) + 1;
  let ch = row.parentElement.querySelector(`.tree-children[data-parent="${_cssEsc(path)}"]`);
  if (!ch) {
    ch = document.createElement('div');
    ch.className = 'tree-children';
    ch.dataset.parent = path;
    row.after(ch);   // 行后插入——不在 root 末尾堆叠
  }
  ch.innerHTML = '<div class="tree-more">加载中…</div>';
  row.dataset.open = '1';
  const ar = row.querySelector('.arrow'); if (ar) ar.style.transform = 'rotate(90deg)';
  const ic = row.querySelector('svg'); if (ic) ic.outerHTML = dirIconHtml(true, 14);
  // 防乱序记在【ch 自己】身上：隐藏开关快速切换/连点展开时旧响应不覆盖新内容。
  // 不能用全局计数——展开 A 目录后展开 B，A 的响应回来就被全局 seq 判"过期"，
  // A 永远停在加载中（用户实锤：根节点一直加载中）。
  ch.dataset.seq = String((+ch.dataset.seq || 0) + 1);
  const seq = +ch.dataset.seq;
  let j;
  try {
    const r = await fetch('/api/tree/list', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({path, hidden: _treeShowHidden})});
    j = await r.json();
  } catch(e) { if (+ch.dataset.seq === seq && ch.isConnected) ch.innerHTML = '<div class="tree-more">读取失败</div>'; return; }
  if (+ch.dataset.seq !== seq || !ch.isConnected) return;   // 已有更新请求/容器已销毁，本次作废
  if (!j.ok) { ch.innerHTML = `<div class="tree-more">${esc(j.err || '读取失败')}</div>`; return; }
  if (!j.entries.length) { ch.innerHTML = '<div class="tree-more">（空目录）</div>'; return; }
  let html = '';
  for (const e of j.entries) {
    // 超 20 层 CSS 梯度兜不住时行内补缩进（14px/层，与 CSS 梯度同节拍）
    const dp = depth > 20 ? ` padding-left:${6 + depth * 14}px;` : '';
    if (e.dir) {
      html += `<div class="tree-row" data-path="${esc(e.path)}" data-dir="1" data-depth="${depth}"${dp ? ` style="${dp.trim()}"` : ''}>
        <span class="arrow">▶</span>${dirIconHtml(false, 13)}<span class="t-name" title="${esc(e.path)}">${esc(e.name)}</span></div>`;
    } else {
      html += `<div class="tree-row" data-path="${esc(e.path)}" data-depth="${depth}"${dp ? ` style="${dp.trim()}"` : ''}>
        <span class="arrow"></span>${fileIconHtml(e.name, 13)}<span class="t-name" title="${esc(e.path)}">${esc(e.name)}</span></div>`;
    }
  }
  if (j.truncated) html += `<div class="tree-more">…还有 ${Number(j.truncated).toLocaleString()} 项未显示</div>`;
  ch.innerHTML = html;
}

// 属性选择器里的路径转义（data-parent 含引号/反斜杠时的 CSS 转义）
function _cssEsc(s) { return String(s).replace(/["\\]/g, '\\$&'); }

// ---- 事件委托：整个 pane 一个 listener ----
$('treePane').addEventListener('click', async e => {
  // 删根 ✕ 优先拦截（在 .tree-root-head 内，closest .tree-row 会先命中头行）
  const x = e.target.closest('.root-x');
  if (x) {
    e.stopPropagation();
    const root = x.closest('.tree-root').dataset.root;
    try {
      const r = await fetch('/api/tree/remove_root', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: root})});
      const j = await r.json();
      if (j.ok) refreshTree(); else showBanner(j.err || '移除失败', 4000, true);
    } catch(err) { showBanner('移除失败: ' + err, 4000, true); }
    return;
  }
  const row = e.target.closest('[data-path]');
  if (!row) return;
  if (row.dataset.dir === '1') { _treeToggle(row); return; }
  // 文件：openFileSmart 自动分流（hex/编辑器/日志查看器），与拖拽打开同链路
  if (typeof openFileSmart === 'function') {
    $('treePane').querySelectorAll('.tree-row.active').forEach(el => el.classList.remove('active'));
    row.classList.add('active');
    openFileSmart(row.dataset.path, 'auto');
  }
});

$('treeAddRoot').onclick = () => pickTreeDir();
$('treeHidden').onclick = () => _treeToggleHidden();
_treeSyncHiddenBtn();   // 初始文案（HTML 静态写「显示」，JS 兜底同步）

// 启动：拉根列表（DOM 在 index.html 静态存在，config 持久化的根直接恢复）
refreshTree();
