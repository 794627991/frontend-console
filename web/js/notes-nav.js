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
  const _myReq = ++window._nnLseq || (window._nnLseq = 1);   // a239 B3-P3: 连续两次搜索旧响应晚到不再覆盖新结果
  let j;
  try {
    const r = await fetch('/api/notes/search', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q,
        case: ov.querySelector('#nnSearchCase').checked,
        regex: ov.querySelector('#nnSearchRe').checked }) });
    j = await r.json();
  } catch (e) { if (_myReq === window._nnLseq) res.innerHTML = '<div class="nn-search-empty">搜索失败: ' + esc(String(e)) + '</div>'; return; }
  if (_myReq !== window._nnLseq) return;
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
  // .note 的 Editor.js 实例化同步、块渲染异步（全审 G2：旧条件恒零等待）——
  // 等 .ce-block 首块渲染出来再跳（上限 3s 兜底；Monaco/ta 同步就绪直接过）
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    if (conn.monaco || conn.ta) break;
    if (conn.editor && conn.holder
        && conn.holder.querySelectorAll('.ce-block').length > 0) break;
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

// ---- 全局快捷键（全库搜索，v3.5.310 可配置，默认 Ctrl+Alt+F，严格三键匹配）----
// 注：文档内搜索默认 Ctrl+F（sidebar.js 等，可配置）。两键若被用户设成相同
// 组合，本监听（页面捕获层）先于冒泡层命中=全库搜索优先——设置页帮助文如实
// 提示勿设同键，无自动撞键检测。
document.addEventListener('keydown', e => {
  if (typeof hkMatch === 'function'
      ? hkMatch(e, window._HK && window._HK.notesSearch)
      : (e.ctrlKey && e.altKey && !e.shiftKey && (e.key === 'f' || e.key === 'F'))) {
    e.preventDefault(); e.stopPropagation();
    nnSearchShow();
  }
}, true);

// ============================================================
// v3.5.297 双链 [[]] + 反链面板
// ============================================================

// 反链面板开关（editor.js 工具栏 🔗 链接按钮 → 这里）
function nnToggleLinks(conn) {
  const pn = conn.wrap.querySelector('.ed-links');
  if (!pn) return;
  const show = pn.style.display === 'none';
  pn.style.display = show ? '' : 'none';
  if (show) nnRefreshLinks(conn);
}

// 面板开着才刷（edSave 成功钩子调用——「保存后刷新可见」）
function nnRefreshLinksIfOpen(conn) {
  const pn = conn.wrap.querySelector('.ed-links');
  if (pn && pn.style.display !== 'none') nnRefreshLinks(conn);
}

async function nnRefreshLinks(conn) {
  const pn = conn.wrap.querySelector('.ed-links');
  const list = pn && pn.querySelector('.ed-links-list');
  if (!pn || !list) return;
  const name = conn.extPath ? '' : (conn.meta.label || '');
  if (!name) { list.innerHTML = '<div class="ed-links-empty">外部文件不参与链接图谱（库仅限 files/ 内）</div>'; return; }
  list.innerHTML = '<div class="ed-links-empty">加载中…</div>';
  let j;
  try {
    const r = await fetch('/api/notes/backlinks?name=' + encodeURIComponent(name));
    j = await r.json();
  } catch (e) { list.innerHTML = '<div class="ed-links-empty">加载失败: ' + esc(String(e)) + '</div>'; return; }
  if (!j.ok) { list.innerHTML = '<div class="ed-links-empty">' + esc(j.err || '加载失败') + '</div>'; return; }
  conn._nnLinks = j;
  const _row = (cls, html) => `<div class="ed-links-row ${cls}">${html}</div>`;
  let html = '';
  // 链入
  html += `<div class="ed-links-sec">链入（${j.incoming.length}）</div>`;
  html += j.incoming.length
    ? j.incoming.map(x => _row('ed-links-in',
        `<span class="ed-links-name" data-nnopen="${esc(x.from)}" data-nnline="${esc(String(x.at_line || 1))}" title="${esc(x.snippet)}">📄 ${esc(x.from)}</span>` +
        `<span class="ed-links-cnt">×${esc(String(x.count))}</span>`)).join('')
    : '<div class="ed-links-none">没有其他笔记引用本文</div>';
  // 链出
  html += `<div class="ed-links-sec">链出（${j.outgoing.length}）</div>`;
  html += j.outgoing.length
    ? j.outgoing.map(x => x.resolved
        ? _row('ed-links-out',
            `<span class="ed-links-name" data-nnopen="${esc(x.resolved)}" data-nnline="1" title="点击打开">📄 ${esc(x.target)}</span>` +
            `<span class="ed-links-cnt">×${esc(String(x.count))}</span>`)
        : _row('ed-links-missing',
            `<span class="ed-links-name miss" data-nnnew="${esc(x.target)}" title="目标不存在，点击新建">⚠ ${esc(x.target)}</span>` +
            `<span class="ed-links-cnt">未创建</span>`)).join('')
    : '<div class="ed-links-none">本文没有 [[]] 双链（正文中写 [[目标名]] 即可链接）</div>';
  // 本文标签
  html += `<div class="ed-links-sec">本文标签</div>`;
  html += j.tags.length
    ? `<div class="ed-links-tags">` + j.tags.map(t => `<span class="ed-links-tag">#${esc(t)}</span>`).join('') + `</div>`
    : '<div class="ed-links-none">没有 #标签</div>';
  html += `<div class="ed-links-foot"><button class="btn ghost icon-btn" data-nnrel title="重新扫描">⟳</button></div>`;
  list.innerHTML = html;
  // 绑定：打开目标 / 新建缺失目标 / 手动刷新
  list.querySelectorAll('[data-nnopen]').forEach(el => {
    el.onclick = () => nnOpenAndJump(el.dataset.nnopen, +el.dataset.nnline || 1);
  });
  list.querySelectorAll('[data-nnnew]').forEach(el => {
    el.onclick = async () => {
      const t = el.dataset.nnnew;
      const nm = t.toLowerCase().endsWith('.note') || t.toLowerCase().endsWith('.md')
        || t.toLowerCase().endsWith('.txt') ? t : t + '.note';
      const ok = await _edConfirm('目标「' + t + '」不存在，新建 ' + nm + '？');
      if (!ok) return;
      try {
        const r = await fetch('/api/ed/save_as', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_name: nm, text: '' }) });
        const jj = await r.json();
        if (!jj.ok) { showBanner(jj.err || '新建失败', 4000, true); return; }
        showBanner('已创建 ' + nm, 2500);
        nnRefreshLinks(conn);
      } catch (e) { showBanner('新建失败: ' + e, 4000, true); }
    };
  });
  const rel = list.querySelector('[data-nnrel]');
  if (rel) rel.onclick = () => nnRefreshLinks(conn);
}

// ---- .note 正文 Ctrl+点击双链跳转（VSCode follow-link 心智：普通单击照常编辑）----
// holder click 委托捕获期：ctrl 按下时用 caretRangeFromPoint 取落点文本向两侧
// 扩展出 [[..]]；取不到静默放行（退化为普通点击）。WebView2=Chromium 支持。
function nnBindWikiClick(conn) {
  const holder = conn.holder;
  if (!holder || holder._nnWiki) return;
  holder._nnWiki = true;
  holder.addEventListener('click', e => {
    if (!e.ctrlKey) return;   // Ctrl+点击=跟随双链；普通单击照常编辑光标
    const text = _nnTextAtPoint(e);
    const m = text && text.match(/\[\[([^\[\]\n]{1,120})\]\]/);
    if (!m) return;
    e.preventDefault(); e.stopPropagation();
    const target = m[1].trim();
    // 全审 S1：面板数据（conn._nnLinks）只在面板开过才有——默认态不能依赖它
    // 判「不存在」。先候选名探测（命中已存在文件即打开），全失败才走新建确认。
    const hit = conn._nnLinks && conn._nnLinks.outgoing
      && conn._nnLinks.outgoing.find(x => x.target === target);
    if (hit && hit.resolved) { nnOpenAndJump(hit.resolved, 1); return; }
    nnTryOpen([target, target + '.note', target + '.md', target + '.txt'],
      target, conn);
  }, true);
}
function _nnTextAtPoint(e) {
  try {
    if (!document.caretRangeFromPoint) return '';
    const r = document.caretRangeFromPoint(e.clientX, e.clientY);
    if (!r || !r.startContainer) return '';
    const node = r.startContainer;
    const txt = node.textContent || '';
    if (!txt) return '';
    const off = r.startOffset;
    // 向两侧扩展 140 字符窗口（[[ 与 ]] 限 120，够覆盖），在窗口内找包含 off 的 [[]]
    const lo = Math.max(0, off - 140), hi = Math.min(txt.length, off + 140);
    const seg = txt.slice(lo, hi);
    const m = seg.match(/\[\[([^\[\]\n]{1,120})\]\]/g) || [];
    for (const s of m) {
      const at = seg.indexOf(s);
      if (off - lo >= at && off - lo <= at + s.length) return s;
    }
    return '';
  } catch (_) { return ''; }
}
async function nnConfirmCreate(target, conn) {
  const nm = target.toLowerCase().endsWith('.note') || target.toLowerCase().endsWith('.md')
    || target.toLowerCase().endsWith('.txt') ? target : target + '.note';
  const ok = await _edConfirm('「' + target + '」不存在，新建 ' + nm + '？');
  if (!ok) return;
  try {
    const r = await fetch('/api/ed/save_as', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: nm, text: '' }) });
    const j = await r.json();
    if (!j.ok) { showBanner(j.err || '新建失败', 4000, true); return; }
    showBanner('已创建 ' + nm, 2500);
    if (conn) nnRefreshLinks(conn);
  } catch (e) { showBanner('新建失败: ' + e, 4000, true); }
}

// ---- .md 预览列双链渲染（_mdRenderPreview 的 apply() 挂点调用）----
// [[..]] 是纯文本不是 md 语法，markdown-it 不会给 a 标签——在渲染完的文本节点
// 里把 [[..]] 包成 <a class="nn-wlink">（无 href，不触发外链拦截逻辑）。
function nnLinkifyPreview(pv, conn) {
  if (!pv) return;
  const walker = document.createTreeWalker(pv, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.parentNode && /^(A|CODE|PRE|MARK|STYLE)$/.test(n.parentNode.tagName))
      ? NodeFilter.FILTER_REJECT
      : (n.nodeValue && n.nodeValue.includes('[[') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT)
  });
  const targets = [];
  while (walker.nextNode()) targets.push(walker.currentNode);
  if (!targets.length) return;
  for (const node of targets) {
    const txt = node.nodeValue;
    let html = '', pos = 0, m;
    const re = /\[\[([^\[\]\n]{1,120})\]\]/g;
    while ((m = re.exec(txt))) {
      html += esc(txt.slice(pos, m.index));
      const t = m[1].trim();
      html += `<a class="nn-wlink" data-nnw="${esc(t)}" title="双链：${esc(t)}（Ctrl+库内搜索可达）">[[${esc(t)}]]</a>`;
      pos = m.index + m[0].length;
    }
    html += esc(txt.slice(pos));
    const span = document.createElement('span');
    span.innerHTML = html;
    node.parentNode.replaceChild(span, node);
  }
  if (!pv._nnWlinkBound) {
    pv._nnWlinkBound = true;
    pv.addEventListener('click', e => {
      const a = e.target.closest('.nn-wlink');
      if (!a) return;
      e.preventDefault();
      const t = a.dataset.nnw;
      // 全审 L2：候选名直接探测打开（旧死请求 backlinks 响应未用，删）
      nnTryOpen([t, t + '.note', t + '.md', t + '.txt'], t, conn);
    });
  }
}
// 依次尝试候选名打开（openEditorFile 失败会静默返回）——全失败提示新建
async function nnTryOpen(cands, label, conn) {
  for (const c of cands) {
    if (!c) continue;
    const before = Object.keys(connections).length;
    await openEditorFile(c);
    await new Promise(r => setTimeout(r, 150));
    let opened = false;
    for (const pid in connections) {
      const cc = connections[pid];
      if (cc && cc.meta && cc.meta.kind === 'editor' && cc.meta.label === c) { opened = true; break; }
    }
    if (opened) return;
    if (Object.keys(connections).length > before) return;   // 新 tab 已建（外部路径等）
    void label;
  }
  nnConfirmCreate(label, conn);
}

// ============================================================
// v3.5.301 图片右键复制（用户需求）：库内图片（/api/ed/img/*）右键直接复制
// 图片本体到剪贴板——非 png 先经 canvas 转 png（剪贴板只收位图，gif 取静帧）；
// 外部图片不拦（保留原生菜单）。document 级事件委托，零挂点不碰 Editor.js。
// ============================================================
document.addEventListener('contextmenu', e => {
  const img = e.target.closest('img');
  if (!img) return;
  const src = img.currentSrc || img.src || '';
  if (!src.includes('/api/ed/img/')) return;
  e.preventDefault();
  nnCopyImage(src);
});
async function nnCopyImage(url) {
  try {
    let blob = await (await fetch(url)).blob();
    if (blob.type !== 'image/png') {
      blob = await new Promise((resolve, reject) => {
        const im = new Image();
        im.onload = () => {
          const cv = document.createElement('canvas');
          cv.width = im.naturalWidth;
          cv.height = im.naturalHeight;
          cv.getContext('2d').drawImage(im, 0, 0);
          cv.toBlob(b => b ? resolve(b) : reject(new Error('canvas 转换失败')), 'image/png');
        };
        im.onerror = () => reject(new Error('图片解码失败'));
        im.src = URL.createObjectURL(blob);
      });
    }
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    showBanner('已复制图片，可直接粘贴到聊天/文档', 2200);
  } catch (e) { showBanner('复制图片失败: ' + (e && e.message || e), 3500, true); }
}

// ============================================================
// v3.5.305 双链/标签 输入补全 + 阅读态染色（用户实锤「没有特殊化显示，
// 没有快捷键快速打标签快速引入」）
// ============================================================

// ---- 补全浮层 ----
const _nnSug = { ov: null, items: [], idx: 0, ce: null, triggerLen: 0, kind: '' };
const _nnSugFileCache = { t: 0, list: [] };
const _nnSugTagCache = { t: 0, list: [] };

function _nnSugHide() {
  if (_nnSug.ov) { _nnSug.ov.remove(); _nnSug.ov = null; }
  _nnSug.ce = null; _nnSug.items = []; _nnSug.kind = '';
}

async function _nnSugData(kind) {
  const c = kind === 'file' ? _nnSugFileCache : _nnSugTagCache;
  if (Date.now() - c.t < 60000) return c.list;
  try {
    const r = await fetch(kind === 'file' ? '/api/ed/list' : '/api/notes/tags');
    const j = await r.json();
    c.list = j.ok ? (kind === 'file'
      ? (j.files || []).map(f => f.name)
      : (j.tags || []).map(t => t.tag)) : [];
  } catch (_) { c.list = []; }
  c.t = Date.now();
  return c.list;
}

// caret 前缀检测：块内光标前文本 → {kind, prefix, triggerLen} 或 null
function _nnSugDetect(ce) {
  const sel = window.getSelection();
  if (!sel.rangeCount) return null;
  const rng = sel.getRangeAt(0);
  if (!rng.collapsed || !ce.contains(rng.startContainer)) return null;
  const node = rng.startContainer;
  if (node.nodeType !== 3) return null;
  const before = (node.nodeValue || '').slice(0, rng.startOffset);
  let m = before.match(/\[\[([^\[\]\n]{0,100})$/);
  if (m) return { kind: 'file', prefix: m[1], triggerLen: m[1].length + 2 };
  m = before.match(/(^|[\s，。、；：！？（）()【】、"'`.,;:!?-])#([\p{L}_][\p{L}\p{N}_]{0,30})$/u);
  if (m) return { kind: 'tag', prefix: m[2], triggerLen: m[2].length + 1 };
  return null;
}

function _nnSugShow(ce, kind, prefix) {
  _nnSug.ce = ce; _nnSug.kind = kind; _nnSug.triggerLen = prefix.length + (kind === 'file' ? 2 : 1);
  if (!_nnSug.ov) {
    const ov = document.createElement('div');
    ov.className = 'nn-sug';
    ov.id = 'nnSugOv';
    document.body.appendChild(ov);
    _nnSug.ov = ov;
  }
  // 定位：caret 屏幕坐标
  const sel = window.getSelection();
  let rect = null;
  if (sel.rangeCount) {
    const r = sel.getRangeAt(0).cloneRange();
    const span = document.createElement('span');
    span.textContent = '​';
    r.insertNode(span);
    rect = span.getBoundingClientRect();
    span.remove();
    ce.normalize();
  }
  if (rect) {
    const ov2 = _nnSug.ov;
    ov2.style.left = Math.min(rect.left, window.innerWidth - 280) + 'px';
    ov2.style.top = Math.min(rect.bottom + 4, window.innerHeight - 200) + 'px';
  }
}

function _nnSugPaint(list) {
  const ov = _nnSug.ov;
  ov.innerHTML = list.map((x, i) =>
    `<div class="nn-sug-it${i === _nnSug.idx ? ' on' : ''}" data-i="${i}">${esc(x)}</div>`).join('');
  ov.querySelectorAll('.nn-sug-it').forEach(el => {
    el.onclick = () => { _nnSug.idx = +el.dataset.i; _nnSugApply(); };
  });
  const on = ov.querySelector('.nn-sug-it.on');
  if (on) on.scrollIntoView({ block: 'nearest' });
}

function _nnSugApply() {
  const { ce, items, idx, kind } = _nnSug;
  const text = items[idx];
  _nnSugHide();
  if (!ce || !text || !ce.isConnected) return;
  const full = kind === 'file' ? '[[' + text + ']]' : '#' + text + ' ';
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  const rng = sel.getRangeAt(0);
  const node = rng.startContainer;
  if (node.nodeType !== 3) return;
  const off = rng.startOffset;
  // v3.5.308（全审F7）：应用前复验触发串仍在光标前——浮层开着按 Home/End/
  // PgUp 移了光标（无 input 事件不触发重检测）时，按旧 triggerLen 盲删会错乱
  const det = _nnSugDetect(ce);
  if (!det || det.kind !== kind) return;
  const full2 = kind === 'file' ? '[[' + text + ']]' : '#' + text + ' ';
  node.nodeValue = node.nodeValue.slice(0, Math.max(0, off - det.triggerLen))
    + full2 + node.nodeValue.slice(off);
  const caret = Math.max(0, off - det.triggerLen) + full2.length;
  void full;
  const nr = document.createRange();
  nr.setStart(node, caret);
  nr.collapse(true);
  sel.removeAllRanges();
  sel.addRange(nr);
  ce.dispatchEvent(new Event('input', { bubbles: true }));   // 脏标记联动
}

// 编辑器内输入驱动（document 捕获 input，委托到 .note 可编辑区）
document.addEventListener('input', e => {
  const ce = e.target;
  if (!ce || !ce.isContentEditable) return;
  const flow = ce.closest('.term-area');
  if (!flow || typeof connections === 'undefined') return;
  const det = _nnSugDetect(ce);
  if (!det) { _nnSugHide(); return; }
  _nnSugData(det.kind).then(list => {
    if (_nnSug.ce !== ce || _nnSug.kind !== det.kind) return;
    const redet = _nnSugDetect(ce);
    if (!redet || redet.kind !== det.kind) { _nnSugHide(); return; }
    const p = (redet.prefix || '').toLowerCase();
    const hits = list.filter(x => !p || x.toLowerCase().includes(p)).slice(0, 8);
    if (!hits.length) { _nnSugHide(); return; }
    _nnSug.items = hits; _nnSug.idx = 0;
    _nnSugShow(ce, det.kind, redet.prefix);
    _nnSugPaint(hits);
  });
}, true);
// keydown：补全浮层的 ↑↓/Enter/Esc（捕获期，浮层在场才拦）
document.addEventListener('keydown', e => {
  if (!_nnSug.ov) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault(); e.stopPropagation();
    _nnSug.idx = (_nnSug.idx + (e.key === 'ArrowDown' ? 1 : _nnSug.items.length - 1)) % _nnSug.items.length;
    _nnSugPaint(_nnSug.items);
  } else if (e.key === 'Enter') {
    e.preventDefault(); e.stopPropagation();
    _nnSugApply();
  } else if (e.key === 'Escape') {
    e.preventDefault(); e.stopPropagation();
    _nnSugHide();
  }
}, true);
document.addEventListener('click', e => {
  if (_nnSug.ov && !e.target.closest('.nn-sug') && !e.target.closest('.nn-sug-it')) _nnSugHide();
});

// ---- 阅读态染色（非聚焦块包 span.nn-hl，聚焦即还原；编辑中块不处理避免
// caret 扰动）。零污染真实机制（全审F9修正）：Editor.js paragraph save() 取
// innerHTML，但 Saver 落盘前走 sanitizer 白名单——span 非白名单被 unwrap 保
// 文本（vendor 偏移 ~50478 实证）。注意：未来任何工具写 sanitize:{text:true}
// 这类放行配置即破此防线——新内联工具必须走对象形 sanitize。
function _nnUnwrapHl(scope) {
  scope.querySelectorAll('span.nn-hl').forEach(sp => {
    sp.parentNode.replaceChild(document.createTextNode(sp.textContent), sp);
  });
  // v3.5.308（全审F6）：合并拆散的相邻文本节点——Ctrl+点击的落点窗口检测
  // 只读单节点文本，不合并则相邻片段里的 [[..]] 找不到
  try { scope.normalize(); } catch (_) {}
}
const _NN_HL_TEXT = /(\[\[[^\[\]\n]{1,120}\]\])|(#[\p{L}_][\p{L}\p{N}_]{0,39}?(?=$|[\s，。、；：！？（）【】《》「」"'`,;:!?.\-(){}[\]|*=+&%$@~^<>/]))/gu;
const _nnHlSig = new WeakMap();   // 块文本签名——打断「染色DOM变更→onChange→再染色」自激环（designer补档风险2）
function _nnHlBlock(blk) {
  if (blk.contains(document.activeElement)) return;   // 编辑中块不动
  const hasHl = !!blk.querySelector('span.nn-hl');
  const sig = blk.textContent || '';
  if (hasHl && _nnHlSig.get(blk) === sig) return;     // 已染色且文本未变→跳过（自激环断点）
  if (hasHl) _nnUnwrapHl(blk);   // 重扫前还原旧标记
  const walker = document.createTreeWalker(blk, NodeFilter.SHOW_TEXT, {
    acceptNode: n => {
      const p = n.parentNode;
      if (!p || /^(MARK|CODE|A|STYLE|SCRIPT|TEXTAREA)$/.test(p.tagName)) return NodeFilter.FILTER_REJECT;
      const v = n.nodeValue || '';
      return (v.includes('[[') || v.includes('#')) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }
  });
  const targets = [];
  while (walker.nextNode()) targets.push(walker.currentNode);
  for (const node of targets) {
    const txt = node.nodeValue;
    _NN_HL_TEXT.lastIndex = 0;
    if (!_NN_HL_TEXT.test(txt)) continue;
    _NN_HL_TEXT.lastIndex = 0;
    let html = '', pos = 0, m;
    while ((m = _NN_HL_TEXT.exec(txt))) {
      const s = m[0];
      const isHex = s.startsWith('#') && /^[0-9a-f]{3}$|^[0-9a-f]{6}$/i.test(s.slice(1));
      html += esc(txt.slice(pos, m.index));
      if (!isHex) html += `<span class="nn-hl ${s.startsWith('[[') ? 'nn-hl-w' : 'nn-hl-t'}">${esc(s)}</span>`;
      else html += esc(s);                             // hex 颜色码不染色（对齐后端排除）
      pos = m.index + s.length;
    }
    html += esc(txt.slice(pos));
    const span = document.createElement('span');
    span.innerHTML = html;
    node.parentNode.replaceChild(span, node);
  }
  _nnHlSig.set(blk, blk.textContent || '');
}
let _nnHlTimer = null;
function nnHlSchedule(conn) {
  clearTimeout(_nnHlTimer);
  _nnHlTimer = setTimeout(() => {
    try {
      conn.holder.querySelectorAll('.ce-block').forEach(_nnHlBlock);
    } catch (_) {}
  }, 800);
}
// 聚焦块还原（编辑态纯文本不扰动 caret）
document.addEventListener('focusin', e => {
  const blk = e.target.closest && e.target.closest('.ce-block');
  if (blk && blk.querySelector('span.nn-hl')) _nnUnwrapHl(blk);
}, true);

// ============================================================
// v3.5.298 标签 #tag 聚合（📝 笔记弹窗顶部 chips，点选过滤文件列表）
// ============================================================
let _nnTagMap = null;    // name -> [tags]（过滤用，随 chips 一起拉）

async function nnRenderTagFilter(modal, listEl) {
  // 已有 chips 行：先移除重建（列表每次 show 都重渲，chips 跟随刷新）
  const old = modal.querySelector('.nn-tag-row');
  if (old) old.remove();
  const row = document.createElement('div');
  row.className = 'nn-tag-row';
  row.innerHTML = '<span class="nn-tag-loading">标签加载中…</span>';
  listEl.parentNode.insertBefore(row, listEl);
  let j;
  try {
    const r = await fetch('/api/notes/tags');
    j = await r.json();
  } catch (e) { row.innerHTML = '<span class="nn-tag-loading">标签加载失败</span>'; return; }
  if (!j.ok || !j.tags.length) { row.innerHTML = '<span class="nn-tag-loading">没有 #标签（正文中写 #标签 即自动收集）</span>'; return; }
  _nnTagMap = {};
  for (const t of j.tags) for (const f of t.files) (_nnTagMap[f] = _nnTagMap[f] || []).push(t.tag);
  row.innerHTML = '<span class="nn-tag-cap">🏷</span>' + j.tags.map(t =>
    `<span class="nn-tag-chip" data-nntag="${esc(t.tag)}" title="${esc(String(t.count))} 个文件">#${esc(t.tag)} <i>${esc(String(t.count))}</i></span>`).join('');
  row.querySelectorAll('.nn-tag-chip').forEach(ch => {
    ch.onclick = () => nnFilterListByTag(modal, listEl, ch.dataset.nntag);
  });
}

function nnFilterListByTag(modal, listEl, tag) {
  const chip = modal.querySelector('.nn-tag-chip.on');
  const active = chip && chip.dataset.nntag === tag ? null : tag;   // 再点同 chip=取消
  modal.querySelectorAll('.nn-tag-chip').forEach(c => c.classList.toggle('on', c.dataset.nntag === active));
  listEl.querySelectorAll('.item').forEach(it => {
    const name = it.dataset.name || '';
    const tags = (_nnTagMap && _nnTagMap[name]) || [];
    it.style.display = (!active || tags.includes(active)) ? '' : 'none';
  });
}

// ============================================================
// v3.5.299 导出 .md（仅 .note；当前编辑内容所见即所得，409 确认覆盖）
// ============================================================
async function nnExportMd(conn) {
  if (!conn.isNote) { showBanner('仅块笔记（.note）支持导出 .md', 3000, true); return; }
  const content = await _edGetContent(conn);
  if (content === null) { showBanner('读取内容失败', 4000, true); return; }
  await nnExportDo(conn, content, false);
}
async function nnExportDo(conn, content, overwrite) {
  try {
    const r = await fetch('/api/notes/export_md', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: conn.meta.label, blocks: content, overwrite }) });
    const j = await r.json();
    if (j.exists && !overwrite) {
      const ok = await _edConfirm('已存在 ' + (j.err || '').replace('已存在 ', '') + '，覆盖？');
      if (ok) await nnExportDo(conn, content, true);
      return;
    }
    if (!j.ok) { showBanner(j.err || '导出失败', 4000, true); return; }
    showBanner('已导出 ' + j.name + '（files/ 目录，图片相对路径可直接进 Obsidian）', 3500);
    fetch('/api/ed/open_dir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  } catch (e) { showBanner('导出失败: ' + e, 4000, true); }
}
