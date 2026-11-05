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
  const normKey = (x) => String(x).split(SEP).join('/').toLowerCase();   // a374：+小写（Windows 大小写不敏感）
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
      if (normKey(c.extPath) === normKey(oldP)) {   // a374：斜杠形态免疫（面板反斜杠/树正斜杠）
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
  // a257（用户实锤：原生 confirm 不可接受）：工具自有暗色弹窗——危险风格
  // （红色标题图标 + danger 按钮），Enter 确认 / Esc 取消 / 点遮罩取消
  function confirmDeleteUI(path) {
    return new Promise(resolve => {
      let m = document.getElementById('treeDelModal');
      if (!m) {
        m = document.createElement('div');
        m.className = 'modal';
        m.id = 'treeDelModal';
        m.innerHTML = `
          <div class="box" style="max-width:420px;">
            <div class="head"><strong style="display:inline-flex;align-items:center;gap:8px;">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--neon-red)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10"/><path d="M6.5 4.5v-1a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1"/><path d="M4.5 4.5l.7 8a1 1 0 0 0 1 .9h3.6a1 1 0 0 0 1-.9l.7-8"/><path d="M6.7 7.5v3.2M9.3 7.5v3.2"/></svg>删除确认</strong>
              <div class="head-actions"><button class="btn ghost icon-btn" id="treeDelClose">✕</button></div>
            </div>
            <div style="padding:16px 20px;">
              <div style="font-size:12px;color:var(--muted);margin-bottom:6px;">将删除：</div>
              <div id="treeDelName" style="font-size:13px;color:var(--fg-bright);font-family:var(--font-mono);font-weight:600;word-break:break-all;margin-bottom:6px;"></div>
              <div id="treeDelPath" style="font-size:10px;color:var(--muted);font-family:var(--font-mono);word-break:break-all;margin-bottom:14px;"></div>
              <div style="font-size:11px;line-height:1.7;color:var(--neon-orange,var(--muted));border-left:2px solid var(--border);padding-left:10px;">
                本地盘移入回收站可恢复；网络/映射盘为永久删除
              </div>
              <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px;">
                <button class="btn ghost" id="treeDelNo">取消</button>
                <button class="btn danger" id="treeDelYes" style="font-weight:600;">删 除</button>
              </div>
            </div>
          </div>`;
        document.body.appendChild(m);
        m.addEventListener('mousedown', e => {   // 点遮罩=取消（mousedown 而非 click：box 内冒泡不算）
          if (e.target === m) m._finish && m._finish(false);
        });
        document.addEventListener('keydown', e => {
          if (!m.classList.contains('show')) return;
          if (e.key === 'Escape') { e.preventDefault(); m._finish && m._finish(false); }
          else if (e.key === 'Enter') { e.preventDefault(); m._finish && m._finish(true); }
        });
      }
      m.querySelector('#treeDelName').textContent = baseName(path);
      m.querySelector('#treeDelPath').textContent = path;
      m._finish = v => { m.classList.remove('show'); m._finish = null; resolve(v); };
      m.querySelector('#treeDelYes').onclick = () => m._finish && m._finish(true);
      m.querySelector('#treeDelNo').onclick = () => m._finish && m._finish(false);
      m.querySelector('#treeDelClose').onclick = () => m._finish && m._finish(false);
      m.classList.add('show');
      const yes = m.querySelector('#treeDelYes');
      setTimeout(() => yes.focus(), 50);   // 焦点给删除钮：Enter 直删，Esc 取消
    });
  }
  window._treeConfirmDelete = confirmDeleteUI;   // 验证/复用口
  async function doDelete(path) {
    if (!(await confirmDeleteUI(path))) return;
    const j = await fileops({ op: 'delete', path });
    if (j) tabsAfterDelete(path);
  }
  function doRename(rowEl, path) {
    inlineInputEdit(path, true, baseName(path), (v) => {
      if (v === baseName(path)) return;
      fileops({ op: 'rename', path, name: v }).then(j => { if (j) tabsAfterRename(path, j.new); });
    });
  }

  // ---- 内联输入（a258：VSCode 同款定位）-----------------------------------
  // 重命名：输入框覆盖在行内（名字位置，行高内垂直居中）
  // 新建：  输入框落在目标文件夹行的**下一行**、缩进一级——VSCode 的"在
  //         文件夹里创建"就是把这个位置给你看。老版固定在树顶=完全看不出
  //         会建到哪里（用户实锤）
  // path 解析不出行号时回退树顶（老行为兜底）
  function rowIndexOf(path) {
    return window._TV && _TV.idx ? _TV.idx.get(path) : undefined;
  }
  function inlineInputEdit(path, overlay, initial, onOk) {
    const host = $('treeRoots');
    if (!host || host.dataset.editing) return;
    const T = window._TV;
    const idx = rowIndexOf(path);
    if (idx === undefined || !T.rows[idx]) { inlineInputTop(initial, onOk); return; }
    host.dataset.editing = '1';
    const r = T.rows[idx];
    const tops = T.tops || [];
    const rowTop = (tops[idx] !== undefined) ? tops[idx] : idx * T.ROW_H;
    const rowH = r.t === 'root' ? 36 : T.ROW_H;
    const IH = 20;   // 输入框高（行 22 内嵌）
    const top = overlay ? rowTop + Math.max(1, Math.round((rowH - IH) / 2))
                        : rowTop + rowH + 1;
    const pad = (typeof _tvPad === 'function' ? _tvPad(overlay ? r.depth : r.depth + 1) : 6 + r.depth * 14);
    const inp = document.createElement('input');
    inp.value = initial || '';
    inp.placeholder = overlay ? '' : '输入名称，Enter 确认';
    inp.style.cssText = 'position:absolute;top:' + top + 'px;left:' + (pad + 4) + 'px;right:12px;height:' + IH + 'px;' +
      'font:11px var(--font-mono);background:var(--bg-input);color:var(--fg);' +
      'border:1px solid var(--accent);border-radius:4px;padding:0 6px;outline:none;z-index:6;';
    // 滚动到输入框可见
    const vh = host.clientHeight || 300;
    if (top < host.scrollTop + 4) host.scrollTop = Math.max(0, top - 6);
    else if (top + IH + 6 > host.scrollTop + vh) host.scrollTop = top + IH + 6 - vh;
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
    sizer.appendChild(inp);
    // 新建在末行下方时把 sizer 撑高一拍，防输入框落在可视区外
    const minH = top + IH + 6;
    const curH = parseInt(sizer.style.height, 10) || 0;
    if (curH < minH) sizer.style.height = minH + 'px';
    inp.focus(); inp.select();
  }
  // 老兜底：树顶输入（行号不可解析时）
  function inlineInputTop(initial, onOk) {
    const host = $('treeRoots');
    if (!host || host.dataset.editing) return;
    host.dataset.editing = '1';
    const inp = document.createElement('input');
    inp.value = initial || '';
    inp.style.cssText = 'position:relative;display:block;width:62%;font:11px var(--font-mono);' +
      'background:var(--bg-input);color:var(--fg);border:1px solid var(--accent);' +
      'border-radius:4px;padding:2px 6px;outline:none;z-index:5;margin:2px 0 2px 20px';
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
  // 展开目录并等缓存落账（新建前奏：保证输入框落点行存在）
  async function prepDirForCreate(dir) {
    const T = window._TV;
    if (!T) return;
    if (!T.open.has(dir) && typeof _tvExpand === 'function') _tvExpand(dir);
    for (let i = 0; i < 25 && !T.cache.has(dir); i++)
      await new Promise(r => setTimeout(r, 100));
    await new Promise(r => setTimeout(r, 60));
  }

  // ---- a259：右键菜单图标全套 SVG（emoji 退役；14px 线性描边与工具条
  // 同语言，currentColor 跟随 hover 变色）----
  const _ico = d => '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + d + '</svg>';
  const CI = {
    newFile: _ico('<path d="M4 2.5h4.5L12 6v6.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z"/><path d="M8.5 2.5V6H12"/><path d="M11.5 9v5M9 11.5h5"/>'),
    newFolder: _ico('<path d="M2.5 11.5v-7a1 1 0 0 1 1-1h2.6l1.4 1.8h4a1 1 0 0 1 1 1v1.2"/><path d="M2.5 11.5l1.2-3.7h9.6l1 3.7z"/><path d="M12.5 10v4M10.5 12h4"/>'),
    openFile: _ico('<path d="M4 2.5h4.5L12 6v7.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z"/><path d="M8.5 2.5V6H12"/><path d="M6.4 12l3.2-3.2M9.6 11.7V9.1H7"/>'),
    reveal: _ico('<path d="M1.8 12.5l1.4-4.4h9.9l1.1 4.4z"/><path d="M2.5 12.5V4.5a1 1 0 0 1 1-1h2.6l1.4 1.8h4a1 1 0 0 1 1 1v1.8"/>'),
    rename: _ico('<path d="M9.7 3.3l3 3L6.5 12.5l-3.5.9.9-3.5z"/><path d="M8.5 4.5l3 3"/>'),
    del: _ico('<path d="M3 4.5h10"/><path d="M6.5 4.5v-1a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1"/><path d="M4.5 4.5l.7 8a1 1 0 0 0 1 .9h3.6a1 1 0 0 0 1-.9l.7-8"/><path d="M6.7 7.5v3.2M9.3 7.5v3.2"/>'),
    copy: _ico('<rect x="5.5" y="5.5" width="8" height="8" rx="1"/><path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2"/>'),
    search: _ico('<circle cx="7" cy="7" r="4.2"/><path d="M10.2 10.2L14 14"/>'),
    compare: _ico('<rect x="1.5" y="4" width="5.5" height="8.5" rx="1"/><rect x="9" y="3.5" width="5.5" height="8.5" rx="1"/><path d="M7.6 8h1.6M8.2 6.8L9.4 8l-1.2 1.2"/>'),
    removeRoot: _ico('<path d="M2.5 11.5v-7a1 1 0 0 1 1-1h2.6l1.4 1.8h4a1 1 0 0 1 1 1v1.2"/><path d="M2.5 11.5l1.2-3.7h9.6l1 3.7z"/><path d="M6.2 12.3h3.6"/>')
  };

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
        { icon: CI.newFile, label: '新建文件', action: async () => {
            await prepDirForCreate(path);
            inlineInputEdit(path, false, '', v =>
              fileops({ op: 'touch', dir: path, name: v }, '已新建 ' + v));
          } },
        { icon: CI.newFolder, label: '新建文件夹', action: async () => {
            await prepDirForCreate(path);
            inlineInputEdit(path, false, '', v =>
              fileops({ op: 'mkdir', dir: path + '/' + v }, '已新建 ' + v));
          } },
        { sep: true });
    } else {
      items.push({ icon: CI.openFile, label: '打开', action: () =>
        typeof openFileSmart === 'function' && openFileSmart(path, 'auto') });
      // a260（用户实锤：树右键对比）——与 tab 右键共享 A 状态（diff-viewer.js
      // 的 _diffCtxA），树上选 A、tab 上比（或反过来）互通
      if (typeof diffPickSetA === 'function') {
        const a = typeof diffPickA === 'function' ? diffPickA() : null;
        const isA = a === path;
        const aName = a && typeof _diffCtxNameOf === 'function' ? _diffCtxNameOf(a) : '';
        items.push(
          { sep: true },
          { icon: CI.compare, label: '选择以进行对比' + (isA ? '（当前 A）' : ''),
            disabled: isA, action: () => diffPickSetA(path) },
          { icon: CI.compare,
            label: a && !isA ? '与选对比（A：' + aName + '）' : '与选进行对比' + (!a ? '（未选 A）' : ''),
            disabled: !a || isA, action: () => diffPickCompare(path) });
      }
    }
    items.push({ icon: CI.reveal, label: '在资源管理器中' + (isDir ? '打开' : '显示'), action: async () => {
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
        { icon: CI.rename, label: '重命名', shortcut: 'F2', action: () => doRename(row, path) },
        { icon: CI.del, label: '删除（入回收站）', shortcut: 'Del', action: () => doDelete(path) });
    }
    items.push(
      { sep: true },
      { icon: CI.copy, label: '复制路径', action: () => {
        try { navigator.clipboard.writeText(path); showBanner('已复制路径', 1600); } catch (_) {}
      } });
    if (!isRoot) {
      items.push({ icon: CI.copy, label: '复制相对路径', action: () => {
        try { navigator.clipboard.writeText(relPath(path)); showBanner('已复制相对路径', 1600); } catch (_) {}
      } });
    }
    if (isDir && typeof window.tsSearchIn === 'function') {
      items.push({ icon: CI.search, label: '在此文件夹中搜索', action: () => window.tsSearchIn(path) });
    }
    // a333：代码跳转索引（手动触发唯一入口——弹层内探测三态：无代码/
    // 可建 / 已建（重建·删除）；绝不自动建库）
    if (isDir && typeof window.NavJump === 'object' && window.NavJump.ui) {
      items.push({ icon: CI.search, label: '代码索引…', action: () => window.NavJump.ui(path) });
    }
    if (isRoot) {
      items.push({ icon: CI.removeRoot, label: '移除根（不删文件）', action: () => {
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
    prepDirForCreate(d).then(() => {
      inlineInputEdit(d, false, '', async v => {
        const j = await fileops({ op: 'touch', dir: d, name: v }, '已新建 ' + v);
        if (j && typeof openFileSmart === 'function')
          openFileSmart(joinPath(d, v), 'auto');   // VSCode 同款：建完即开
      });
    });
  }
  function doNewFolder() {
    const d = targetDir();
    if (!d) return;
    prepDirForCreate(d).then(() => {
      inlineInputEdit(d, false, '', async v => {
        const j = await fileops({ op: 'mkdir', dir: joinPath(d, v) }, '已新建 ' + v);
        if (j) ensureOpen(joinPath(d, v));   // 建完展开新文件夹（空目录提示立现）
      });
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
