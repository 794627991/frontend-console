// ============================================================
// a209批2：文件树文件操作层（右键全家桶 + 内联编辑 + 快捷键 + tab 联动）
// ------------------------------------------------------------
// 独立成文件（与树渲染内核解耦）：本文件只做「命令」，数据失效走
// file-tree.js 暴露的 treeInvalidate/treeDecoRefresh/refreshTree。
// 依赖脚本序：ctx-menu.js（buildCtxMenu）→ file-tree.js（树内核）
//   → 本文件。后端：/api/tree/fileops（mkdir|touch|rename|copy|delete，
//   delete 走系统回收站可恢复）。
// ============================================================
(function () {
  'use strict';
  const SEP = String.fromCharCode(92);   // 反斜杠（避免任何转义歧义）
  const baseName = (p) => String(p).split('/').pop().split(SEP).pop();
  const dirName = (p) => {
    const i = Math.max(String(p).lastIndexOf('/'), String(p).lastIndexOf(SEP));
    return i > 0 ? String(p).slice(0, i) : '';
  };
  // a213 审计 P1：原 pre 只拼 '/'——extPath 反斜杠 startsWith 恒 false，
  // 目录级 rename/delete 子孙联动全灭（改后 tab 按旧路径保存=旧位置复活）。
  // 归一化前缀比较（双斜杠统一）
  const normKey = (x) => String(x).split(SEP).join('/');
  const isUnder = (child, dir) => {
    const c = normKey(child), d = normKey(dir).replace(/\/$/, '');
    return c === d || c.startsWith(d + '/');
  };

  function rootOf(path) {
    let best = '';
    for (const r of (window._TV ? _TV.roots : [])) {
      if (normKey(path) === normKey(r.path) || isUnder(path, r.path))
        if (!best || r.path.length > best.length) best = r.path;
    }
    return best;
  }
  window._treeRootOf = rootOf;   // a209批4：sidebar 副行相对路径判定用
  function relPath(path) {
    const root = rootOf(path);
    return root && path !== root ? String(path).slice(root.length + 1).split(SEP).join('/') : path;
  }

  async function fileops(body, okMsg) {
    try {
      const r = await fetch('/api/tree/fileops', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '操作失败', 4000, true); return null; }
      if (j.parent && typeof treeInvalidate === 'function') treeInvalidate(j.parent);
      if (okMsg) showBanner(okMsg, 2400);
      return j;
    } catch (e) { showBanner('操作失败: ' + e, 4000, true); return null; }
  }

  // ---- 打开 tab 联动（重命名/删除后防幽灵 tab）----
  function tabsAfterRename(oldP, newP) {

    for (const pid in connections) {
      const c = connections[pid];
      if (!c || !c.extPath) continue;
      if (c.extPath === oldP) {
        c.extPath = newP;
        const nm = baseName(newP);
        if (c.meta) c.meta.label = nm;
        const lb = c.tab && c.tab.querySelector('.label');
        if (lb) lb.textContent = (c.dirty ? '*' : '') + nm;
        if (c.tab) c.tab.title = newP;   // a213 审计 P3：悬浮路径同步
      } else if (isUnder(c.extPath, oldP) && c.extPath !== oldP) {
        // 归一改写：新前缀 + 旧相对尾巴（保持 extPath 原生分隔符形态）
        const cutLen = String(oldP).length;
        const tail = String(c.extPath).slice(cutLen).replace(/^[/\\]/, '');
        c.extPath = String(newP) + String(c.extPath).charAt(cutLen) + tail;
        if (c.tab) c.tab.title = c.extPath;
      }
    }
    if (typeof treeDecoRefresh === 'function') treeDecoRefresh();
  }
  function tabsAfterDelete(delP) {

    for (const pid of Object.keys(connections)) {
      const c = connections[pid];
      if (!c || !c.extPath) continue;
      if (c.extPath === delP || isUnder(c.extPath, delP)) {
        try { closeEditorTab(pid); } catch (_) {}
      }
    }
    if (typeof treeDecoRefresh === 'function') treeDecoRefresh();
  }

  // ---- 删除（统一入口：确认弹窗 + 回收站 + tab 联动）----
  async function doDelete(path) {
    // a252（复审F3）：UNC/网络路径=永久删；映射盘（Y:\…）Windows 上也不经
    // 回收站——前端无法区分映射盘，文案如实两可，不再单方面承诺"可恢复"
    if (window.confirm('删除：' + baseName(path) +
        '\n（本地盘移入回收站可恢复；网络/映射盘为永久删除）')) {
      const j = await fileops({ op: 'delete', path });
      if (j) tabsAfterDelete(path);
    }
  }
  function doRename(rowEl, path) {
    inlineInput(rowEl, baseName(path), (v) => {
      if (v === baseName(path)) return;
      fileops({ op: 'rename', path, name: v }).then(j => { if (j) tabsAfterRename(path, j.new); });
    });
  }

  // ---- 内联输入（新建/重命名；树内 input 先例 _treeInlineDirInput——WebView2 可能禁 prompt）----
  function inlineInput(anchorRow, initial, onOk) {
    const host = $('treeRoots');
    if (!host || host.dataset.editing) return;
    host.dataset.editing = '1';
    const inp = document.createElement('input');
    inp.value = initial || '';
    inp.style.cssText = 'position:relative;display:block;width:62%;font:11px var(--font-mono);' +
      'background:var(--bg-input);color:var(--fg);border:1px solid var(--accent);' +
      'border-radius:4px;padding:2px 6px;outline:none;z-index:5;margin:2px 0 2px ' +
      ((parseInt(((anchorRow || {}).style || {}).paddingLeft, 10) || 6) + 14) + 'px';
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      delete host.dataset.editing;
      const v = inp.value.trim();
      inp.remove();
      if (ok && v) onOk(v);
      if (typeof _tvPaint === 'function') _tvPaint();
    };
    inp.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Enter') finish(true);
      else if (e.key === 'Escape') finish(false);
    });
    inp.addEventListener('blur', () => finish(false));
    const sizer = host.querySelector('.tree-sizer') || host;
    sizer.insertBefore(inp, sizer.firstChild);
    inp.focus(); inp.select();
  }

  // ---- 右键命令表 ----
  $('treePane').addEventListener('contextmenu', e => {
    const row = e.target.closest('[data-path]');
    if (!row) return;
    e.preventDefault();
    const path = row.dataset.path;
    const isDir = row.dataset.dir === '1';
    const isRoot = row.classList.contains('tree-root-head');
      const items = [];
    if (isDir) {
      items.push(
        { icon: '📄', label: '新建文件', action: () => inlineInput(row, '', v =>
            fileops({ op: 'touch', dir: path, name: v }, '已新建 ' + v)) },
        { icon: '📁', label: '新建文件夹', action: () => inlineInput(row, '', v =>
            fileops({ op: 'mkdir', dir: path + '/' + v }, '已新建 ' + v)) },
        { sep: true });
    } else {
      items.push({ icon: '📂', label: '打开', action: () =>
        typeof openFileSmart === 'function' && openFileSmart(path, 'auto') });
    }
    items.push({ icon: '📁', label: '在资源管理器中' + (isDir ? '打开' : '显示'), action: async () => {
      try {
        const r = await fetch('/api/tree/reveal', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
        const j = await r.json();
        if (!j.ok) showBanner(j.err || '打开失败', 4000, true);
      } catch (err) { showBanner('打开失败: ' + err, 4000, true); }
    } });
    if (!isRoot) {
      items.push(
        { sep: true },
        { icon: '✏️', label: '重命名', shortcut: 'F2', action: () => doRename(row, path) },
        { icon: '🗑', label: '删除（入回收站）', shortcut: 'Del', action: () => doDelete(path) });
    }
    items.push(
      { sep: true },
      { icon: '📋', label: '复制路径', action: () => {
        try { navigator.clipboard.writeText(path); showBanner('已复制路径', 1600); } catch (_) {}
      } });
    if (!isRoot) {
      items.push({ icon: '📋', label: '复制相对路径', action: () => {
        try { navigator.clipboard.writeText(relPath(path)); showBanner('已复制相对路径', 1600); } catch (_) {}
      } });
    }
    if (isDir && typeof window.tsSearchIn === 'function') {
      items.push({ icon: '🔍', label: '在此文件夹中搜索', action: () => window.tsSearchIn(path) });
    }
    if (isRoot) {
      items.push({ icon: '✕', label: '移除根（不删文件）', action: () => {
        fetch('/api/tree/remove_root', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) })
          .then(r => r.json()).then(j => { if (j.ok && typeof refreshTree === 'function') refreshTree(); });
      } });
    }
    if (typeof buildCtxMenu === 'function') buildCtxMenu(e.clientX, e.clientY, items);
  });

  // ---- 快捷键（树聚焦时；作用于 active 行——点击/右键即设）----
  // a209批4：↑↓←→ 键盘导航（VSCode 树同款）——focus 行即 active 行
  function navKey(e) {
    const T = window._TV;
    if (!T || !T.rows.length) return false;
    let i = T.idx.get(T.active);
    if (i === undefined) i = -1;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      i = Math.min(T.rows.length - 1, i + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      i = Math.max(0, i <= 0 ? 0 : i - 1);
    } else if (e.key === 'ArrowRight') {
      const r = T.rows[i];
      if (r && r.dir && !T.open.has(r.path)) {
        e.preventDefault();
        const el = document.querySelector('#treeRoots [data-path="' + CSS.escape(r.path) + '"]');
        if (el) el.click();
      } else if (r) { e.preventDefault(); navKey({ key: 'ArrowDown', preventDefault(){} }); }
      return true;
    } else if (e.key === 'ArrowLeft') {
      const r = T.rows[i];
      if (r && r.dir && T.open.has(r.path)) {
        e.preventDefault();
        const el = document.querySelector('#treeRoots [data-path="' + CSS.escape(r.path) + '"]');
        if (el) el.click();
      } else if (r && r.depth > 0) {
        // 跳到父行
        for (let j = i - 1; j >= 0; j--) {
          if (T.rows[j].depth < r.depth && T.rows[j].dir) {
            e.preventDefault();
            const p = T.rows[j].path;
            T.active = p; T.rendered = [-1, -1];
            if (typeof _tvPaint === 'function') _tvPaint();
            if (typeof _tvFocus === 'function') _tvFocus(p);
            break;
          }
        }
      }
      return true;
    } else return false;
    // a213 审计 P2：empty/more 行无 path——落在其上永久卡死。沿方向找
    // 下一个有效行
    const down = e.key === 'ArrowDown';
    let j = i, r = null;
    for (let k = 0; k < T.rows.length; k++) {
      if (j < 0 || j >= T.rows.length) break;
      const cand = T.rows[j];
      if (cand && cand.path && cand.t !== 'loading' && cand.t !== 'err') { r = cand; break; }
      j += down ? 1 : -1;
    }
    if (r) {
      T.active = r.path;
      T.rendered = [-1, -1];
      if (typeof _tvPaint === 'function') _tvPaint();
      if (typeof _tvFocus === 'function') _tvFocus(r.path);
    }
    return true;
  }
  $('treePane').addEventListener('keydown', e => {
    // a213 审计 P2：工具栏按钮在 treePane 内——焦点在 button/input 时按键
    // 交还原生行为（按钮 Enter 激活），不劫持
    if (e.target.closest('button, input')) return;
    // a256：新建快捷键（树面板聚焦时作用域内生效，不与全局冲突）
    if (e.ctrlKey && !e.altKey && (e.key === 'n' || e.key === 'N')) {
      e.preventDefault();
      if (e.shiftKey) doNewFolder();
      else doNewFile();
      return;
    }
    if (navKey(e)) return;
    const path = window._TV && _TV.active;
    if (!path) return;
    const el = document.querySelector('#treeRoots [data-path="' + CSS.escape(path) + '"]');
    if (!el) return;
    const isRoot = el.classList.contains('tree-root-head');
    if (e.key === 'F2' && !isRoot) {
      e.preventDefault(); doRename(el, path);
    } else if ((e.key === 'Delete') && !isRoot) {
      e.preventDefault(); doDelete(path);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (el.dataset.dir === '1') el.click();
      else if (typeof openFileSmart === 'function') openFileSmart(path, 'auto');
    }
  });
  // ---- a256：VSCode Explorer 工具条——新建文件/文件夹 + 一键展开⇄收起 ----
  // 目标目录解析：active 是目录→自身；是文件→父目录；无选中→第一个根。
  // 空树不给建（提示先打开文件夹——与空态引导一致）
  function targetDir() {
    const T = window._TV;
    if (!T || !T.roots.length) {
      showBanner('请先「打开文件夹」添加一个根目录', 3200, true);
      const b = $('treeAddRoot'); if (b) b.focus();
      return null;
    }
    const p = T.active && T.idx && T.idx.has(T.active) ? T.active : null;
    const row = p ? T.rows[T.idx.get(p)] : null;
    if (row && row.dir) return row.path;
    if (p) return dirName(p) || T.roots[0].path;   // 文件→父目录（父必开过）
    return T.roots[0].path;
  }
  // 展开目标目录（若可见且未展开），确保新条目落点可见
  function ensureOpen(dir) {
    const T = window._TV;
    if (!T || T.open.has(dir)) return;
    const row = T.idx && T.idx.get(dir) !== undefined ? T.rows[T.idx.get(dir)] : null;
    if (row && row.dir && typeof _tvExpand === 'function') _tvExpand(dir);
  }
  const joinPath = (d, n) => d.replace(/[\\/]+$/, '') + '/' + n;
  function doNewFile() {
    const d = targetDir();
    if (!d) return;
    ensureOpen(d);
    inlineInput(null, '', async v => {
      const j = await fileops({ op: 'touch', dir: d, name: v }, '已新建 ' + v);
      if (j && typeof openFileSmart === 'function')
        openFileSmart(joinPath(d, v), 'auto');   // VSCode 同款：建完即开
    });
  }
  function doNewFolder() {
    const d = targetDir();
    if (!d) return;
    ensureOpen(d);
    inlineInput(null, '', async v => {
      const j = await fileops({ op: 'mkdir', dir: joinPath(d, v) }, '已新建 ' + v);
      if (j) ensureOpen(joinPath(d, v));   // 建完展开新文件夹（空目录提示立现）
    });
  }
  // 一键展开⇄收起（智能切换）：
  // 有展开项→全部收起（先快照）；全收→有快照恢复快照（未缓存的目录补拉取），
  // 无快照→展开各根第一层。绝不无界递归展开（大目录树 Y:\nfs 场景安全）
  function doToggleExpand() {
    const T = window._TV;
    if (!T || !T.roots.length) { showBanner('请先「打开文件夹」添加一个根目录', 3200, true); return; }
    if (T.open.size) {
      T._lastOpen = new Set(T.open);
      T.open.clear();
      T.cache.clear();
      T.rendered = [-1, -1];
      if (typeof _tvRebuild === 'function') _tvRebuild();
      const host = $('treeRoots');
      if (host) host.scrollTop = 0;
      return;
    }
    if (T._lastOpen && T._lastOpen.size) {
      T.open = new Set(T._lastOpen);
      T.rendered = [-1, -1];
      if (typeof _tvRebuild === 'function') _tvRebuild();
      // 恢复时被清掉的缓存逐目录补拉（_tvExpand 幂等：已在 open 只触发拉取）
      for (const p of T.open) {
        if (!T.cache.has(p) && typeof _tvExpand === 'function') _tvExpand(p);
      }
      return;
    }
    for (const r of T.roots) {
      if (typeof _tvExpand === 'function') _tvExpand(r.path);
    }
  }
  // 图标/提示态同步：包一层 _tvRebuild（所有结构变更必经）——有展开项显
  // 「全部收起」态（accent 高亮），全收显「展开」态
  const _ICO_COLLECT = '<path d="M3 5.5h6M3 10.5h6"/><path d="M10.3 9.2l2.4-2.4 2.4 2.4"/>';
  const _ICO_EXPAND = '<path d="M3 5.5h6M3 10.5h6"/><path d="M10.3 5.6l2.4 2.4 2.4-2.4"/>';
  const _ICO_EXPAND_ROOTS = '<path d="M3 4h7M3 7.5h7M3 11h7"/><path d="M11.2 8.6l2-2 2 2M13.2 6.6v4.8"/>';
  function syncToggleIcon() {
    const b = $('treeCollapse');
    if (!b) return;
    const T = window._TV || {};
    const svg = b.querySelector('svg');
    if (!svg) return;
    if (T.open && T.open.size) {
      svg.innerHTML = _ICO_COLLECT;
      b.classList.add('on');
      b.title = '全部收起（当前 ' + T.open.size + ' 项展开）\n再次点击：恢复收起前状态';
    } else if (T._lastOpen && T._lastOpen.size) {
      svg.innerHTML = _ICO_EXPAND;
      b.classList.remove('on');
      b.title = '展开（恢复上次展开的 ' + T._lastOpen.size + ' 项）';
    } else {
      svg.innerHTML = _ICO_EXPAND_ROOTS;
      b.classList.remove('on');
      b.title = '展开各根目录第一层';
    }
  }
  try {
    const _rb = window._tvRebuild;
    if (_rb) {
      window._tvRebuild = function () {
        const r = _rb.apply(this, arguments);
        syncToggleIcon();
        return r;
      };
    }
  } catch (_) {}
  const bNF = $('treeNewFile'), bNFd = $('treeNewFolder'), bCol = $('treeCollapse');
  if (bNF) bNF.onclick = doNewFile;
  if (bNFd) bNFd.onclick = doNewFolder;
  if (bCol) bCol.onclick = doToggleExpand;
  window._treeToggleExpand = doToggleExpand;   // 验证/测试口

  const tr = $('treeRoots');
  if (tr) { tr.tabIndex = 0; tr.style.outline = 'none'; }
})();
