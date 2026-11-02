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
    if (!window.confirm('移入回收站：' + baseName(path) + '\n（可从系统回收站恢复）')) return;
    const j = await fileops({ op: 'delete', path });
    if (j) tabsAfterDelete(path);
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
  const tr = $('treeRoots');
  if (tr) { tr.tabIndex = 0; tr.style.outline = 'none'; }
})();
