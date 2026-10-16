// ============================================================
// 笔记库导航（notes-nav.js）：全局全文搜索（第 1 步）；双链/反链/标签/导出
// 随后续步骤长成。设计来源：designer 方案 v3.5.296（/api/notes/* 只读扫描，
// 与 /api/ed/* 零接触）。
// 快捷键 Ctrl+Alt+F 全库搜索——Ctrl+F 已是「当前文档内搜索」（sidebar.js），
// Ctrl+Shift+F 会被它一并吃掉（未排除 shiftKey），故取三键组合。
// ============================================================

// ---- 全库搜索浮层 ----
function nnSearchShow() {
  let ov = document.getElementById('nnSearchOv');
  if (!ov) {
    ov = document.createElement('div');
    ov.className = 'modal';
    ov.id = 'nnSearchOv';
    ov.innerHTML = `
      <div class="box nn-search-box">
        <div class="head"><strong>🔎 全库搜索</strong>
          <div class="head-actions"><span class="nn-search-hint">Ctrl+Alt+F</span>
            <button class="btn ghost icon-btn" id="nnSearchClose">✕</button></div></div>
        <div class="nn-search-bar">
          <input type="text" id="nnSearchQ" class="nn-search-q" placeholder="搜索全部笔记/文本文件…（回车搜索，支持正则）" autocomplete="off">
          <label class="nn-search-opt" title="区分大小写"><input type="checkbox" id="nnSearchCase">Aa</label>
          <label class="nn-search-opt" title="按正则解释（非法自动降级为字面量）"><input type="checkbox" id="nnSearchRe">.*</label>
        </div>
        <div class="nn-search-res" id="nnSearchRes" style="max-height:56vh;"></div>
      </div>`;
    document.body.appendChild(ov);
    ov.querySelector('#nnSearchClose').onclick = () => ov.classList.remove('show');
    ov.addEventListener('click', e => { if (e.target === ov) ov.classList.remove('show'); });
    const q = ov.querySelector('#nnSearchQ');
    q.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); nnDoSearch(); }
      if (e.key === 'Escape') ov.classList.remove('show');
    });
  }
  ov.classList.add('show');
  const q = ov.querySelector('#nnSearchQ');
  q.focus(); q.select();
}

// 📝 笔记弹窗的 🔍 按钮（模板静态节点，懒创建无绑定时机——document 委托）
document.addEventListener('click', e => {
  if (e.target.closest('#filesSearchBtn')) {
    const fm = document.getElementById('filesModal');
    if (fm) fm.classList.remove('show');
    nnSearchShow();
  }
});

async function nnDoSearch() {
  const ov = document.getElementById('nnSearchOv');
  if (!ov) return;
  const res = ov.querySelector('#nnSearchRes');
  const q = ov.querySelector('#nnSearchQ').value.trim();
  if (!q) return;
  res.innerHTML = '<div class="nn-search-empty">搜索中…</div>';
  let j;
  try {
    const r = await fetch('/api/notes/search', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q,
        case: ov.querySelector('#nnSearchCase').checked,
        regex: ov.querySelector('#nnSearchRe').checked }) });
    j = await r.json();
  } catch (e) { res.innerHTML = '<div class="nn-search-empty">搜索失败: ' + esc(String(e)) + '</div>'; return; }
  if (!j.ok) { res.innerHTML = '<div class="nn-search-empty">' + esc(j.err || '搜索失败') + '</div>'; return; }
  if (!j.files.length) { res.innerHTML = '<div class="nn-search-empty">没有命中</div>'; return; }
  const _hl = (sn, marks) => {
    // marks 区间前端高亮（后端已算好坐标，前端不二次跑正则——规避方言差异）
    let out = '', pos = 0;
    for (const [s, e] of (marks || [])) {
      out += esc(sn.slice(pos, s)) + '<mark>' + esc(sn.slice(s, e)) + '</mark>';
      pos = e;
    }
    return out + esc(sn.slice(pos));
  };
  let html = `<div class="nn-search-stat">${esc(String(j.total_hits))} 处命中 / ${esc(String(j.files.length))} 个文件 · ${esc(String(j.took_ms))}ms` +
    (j.truncated ? '（已达上限，仅显示部分）' : '') +
    (j.skipped_big ? ` · ${esc(String(j.skipped_big))} 个超大文件未纳入` : '') + '</div>';
  for (const f of j.files) {
    html += `<div class="nn-search-file"><div class="nn-search-fh" data-nnfile="${esc(f.name)}">📄 ${esc(f.name)}</div>`;
    for (const h of f.hits) {
      html += `<div class="nn-search-hit" data-nnfile="${esc(f.name)}" data-nnline="${esc(String(h.line))}">` +
        `<span class="nn-search-ln">${esc(String(h.line))}</span><span class="nn-search-sn">` +
        _hl(h.snippet, h.marks) + '</span></div>';
    }
    html += '</div>';
  }
  res.innerHTML = html;
  res.querySelectorAll('.nn-search-hit').forEach(el => {
    el.onclick = () => nnOpenAndJump(el.dataset.nnfile, +el.dataset.nnline || 1);
  });
}

// 打开文件并跳到行（.note 的 line=块序，.txt/.md=物理行——后端口径）。
// openEditorFile 同名已开时内部只 switchTab（buildEditorTab 提前 return），
// 两条路径统一从 connections 按 meta.label 找回 conn。
async function nnOpenAndJump(name, line) {
  const ov = document.getElementById('nnSearchOv');
  if (ov) ov.classList.remove('show');
  await openEditorFile(name);
  let conn = null;
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'editor' && c.meta.label === name) { conn = c; break; }
  }
  if (!conn) return;
  // .note 的 Editor.js 实例化是异步的：等 editor 就绪再跳块（上限 3s 兜底）
  for (let i = 0; i < 30 && !conn.editor && !conn.monaco && !conn.ta; i++) {
    await new Promise(r => setTimeout(r, 100));
  }
  nnJumpLine(conn, line);
}

// 跳行三分支（Monaco 行定位 / textarea 选中 / .note 块滚动——与 editor.js
// edJumpToHit 同款落点，但独立实现不碰其搜索分栏状态）
function nnJumpLine(conn, line) {
  if (!line || line < 1) return;
  if (conn.monaco) {
    conn.monaco.revealLineNearTop(line);
    conn.monaco.setPosition({ lineNumber: line, column: 1 });
    conn.monaco.focus();
  } else if (conn.ta) {
    const lines = conn.ta.value.split('\n');
    let pos = 0;
    for (let i = 0; i < Math.min(line - 1, lines.length); i++) pos += lines[i].length + 1;
    conn.ta.focus();
    conn.ta.setSelectionRange(pos, pos + (lines[line - 1] || '').length);
    const lineH = parseFloat(getComputedStyle(conn.ta).lineHeight) || 20;
    conn.ta.scrollTop = Math.max(0, (line - 5) * lineH);
  } else if (conn.editor && conn.holder) {
    const blocks = conn.holder.querySelectorAll('.ce-block');
    const el = blocks[line - 1];
    if (el) {
      const sc = conn.wrap.querySelector('.ed-scroll');
      if (sc) sc.scrollTo({ top: el.offsetTop - 40, behavior: 'smooth' });
      try {
        el.style.transition = 'background .2s'; el.style.background = 'var(--accent-bg, rgba(74,158,255,.12))';
        setTimeout(() => { el.style.background = ''; el.style.transition = ''; }, 900);
      } catch (_) {}
    }
  }
}

// ---- 全局快捷键 Ctrl+Alt+F（全库搜索）----
// 注：Ctrl+F=当前文档内搜索（sidebar.js，未排除 shiftKey），故全库取 Ctrl+Alt+F。
document.addEventListener('keydown', e => {
  if (e.ctrlKey && e.altKey && !e.shiftKey && (e.key === 'f' || e.key === 'F')) {
    e.preventDefault(); e.stopPropagation();
    nnSearchShow();
  }
}, true);
