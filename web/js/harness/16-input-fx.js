// harness input-fx.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  const _HG_MENTION_FILES = [];   // 已引用路径（overlay 高亮用）
  function _hgMentionReset() { _HG_MENTION_FILES.length = 0; }
  function closeMention() {
    _hgMentionEl.style.display = 'none';
    _HG.mention = null;
  }
  function updateMention() {
    const pos = _hgInput.selectionStart;
    const before = _hgInput.value.slice(0, pos);
    const at = before.lastIndexOf('@');
    if (at === -1) { closeMention(); return; }
    const query = before.slice(at + 1);
    if (query.includes(' ')) { closeMention(); return; }
    _HG.mention = { at, query, sel: -1, files: null };
    const cwd = (_hgConn.meta.cwd) || '';
    fetch(`/api/harness/files?cwd=${encodeURIComponent(cwd)}&q=${encodeURIComponent(query)}`)
      .then(r => r.json())
      .then(j => {
        if (!_HG.mention || _HG.mention.at !== at) return;   // 闭包校验防过期响应
        _HG.mention.files = (j.ok && j.files) || [];
        renderMention();
      }).catch(() => {});
    renderMention(true);   // 立即显示 loading
  }
  function renderMention(loading) {
    const m = _HG.mention;
    if (!m) { closeMention(); return; }
    const files = m.files || [];
    if (!files.length && !loading) { closeMention(); return; }
    _hgMentionEl.style.display = 'block';
    _hgMentionEl.innerHTML = loading && !files.length ? '<div class="hg-pop-empty">搜索文件…</div>'
      : files.map((f, i) => `<div class="hg-mention-item${i === m.sel ? ' sel' : ''}" data-mi="${i}"><b>${esc(f.name)}</b><span>${esc(f.path)}</span></div>`).join('')
        || '<div class="hg-pop-empty">无匹配文件</div>';
  }
  function handleMentionKey(e) {
    const m = _HG.mention;
    if (!m || !m.files || !m.files.length) return false;
    if (e.key === 'ArrowDown') { e.preventDefault(); m.sel = m.sel < m.files.length - 1 ? m.sel + 1 : 0; renderMention(); return true; }
    if (e.key === 'ArrowUp') { e.preventDefault(); m.sel = m.sel > 0 ? m.sel - 1 : m.files.length - 1; renderMention(); return true; }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) {
      e.preventDefault();
      selectMention(m.files[m.sel >= 0 ? m.sel : 0]);
      return true;
    }
    if (e.key === 'Escape') { e.preventDefault(); closeMention(); return true; }
    return false;
  }
  function selectMention(f) {
    if (!f) return;
    const m = _HG.mention;
    const before = _hgInput.value.slice(0, m.at);
    const rest = _hgInput.value.slice(m.at);
    const sp = rest.indexOf(' ');
    const after = sp !== -1 ? rest.slice(sp) : '';
    _hgInput.value = `${before}${f.path} ${after}`;
    const caret = before.length + f.path.length + 1;
    if (!_HG_MENTION_FILES.includes(f.path)) _HG_MENTION_FILES.push(f.path);
    closeMention();
    _hgInput.focus();
    requestAnimationFrame(() => _hgInput.setSelectionRange(caret, caret));
    renderOverlay(_hgInput.value);
  }
  function renderOverlay(text) {
    if (!text || !_HG_MENTION_FILES.length) { _hgOverlayEl.innerHTML = ''; return; }
    const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const sorted = [..._HG_MENTION_FILES].sort((a, b) => b.length - a.length);
    const re = new RegExp(`(${sorted.map(escRe).join('|')})`, 'g');
    _hgOverlayEl.innerHTML = text.split(re).map(p =>
      sorted.includes(p) ? `<span class="hg-mention-hl">${esc(p)}</span>` : esc(p)
    ).join('');
  }
  function _attUrl(a) {
    return '/api/harness/file?name=' + encodeURIComponent(String(a.path).split(/[\\/]/).pop());
  }
  function renderAtts() {
    if (!_HG.atts.length) { _hgAttsEl.style.display = 'none'; _hgAttsEl.innerHTML = ''; return; }
    _hgAttsEl.style.display = 'flex';
    _hgAttsEl.innerHTML = _HG.atts.map((a, i) => {
      const url = a.isImg ? _attUrl(a) : '';
      return `<span class="hg-att-chip">` + (a.isImg
        ? `<img class="hg-att-thumb" src="${esc(url)}" alt="" title="${esc(a.name)}" data-img="${esc(url)}" onerror="this.style.display='none'">`
        : `<span class="hg-att-ico">📄</span>`) +
        `<span class="hg-att-name" title="${esc(a.name)}">${esc(a.name)}</span>` +
        `<button class="hg-att-x" data-i="${i}" title="移除">✕</button></span>`;
    }).join('');
    _hgAttsEl.querySelectorAll('[data-img]').forEach(t => t.onclick = () => openLightbox(t.dataset.img));
  }
  function clearAtts() { _HG.atts = []; renderAtts(); }
  async function uploadFiles(list) {
    for (const f of list) {
      if (f.size > 20 * 1024 * 1024) { showBanner(`「${f.name}」超过 20MB，跳过`, 3000, true); continue; }
      try {
        const b64 = await new Promise((res, rej) => {
          const fr = new FileReader();
          fr.onload = () => res(String(fr.result).split(',')[1] || '');
          fr.onerror = rej;
          fr.readAsDataURL(f);
        });
        const j = await (await fetch('/api/harness/upload', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({name: f.name, data_b64: b64})})).json();
        if (!j.ok) { showBanner(`上传「${f.name}」失败：${j.err}`, 3000, true); continue; }
        _HG.atts.push({name: j.name, path: j.path, size: j.size, isImg: _HARNESS_IMG_EXT.test(j.name)});
        renderAtts();
      } catch(e) { showBanner(`上传「${f.name}」失败：${e}`, 3000, true); }
    }
  }
  function closePop() {
    if (_HG.pop) { const p = _hgWrap.querySelector('.hg-pop'); if (p) p.remove(); _HG.pop = null; }
  }
  function openPop(kind, anchor, html) {
    closePop();
    _HG.pop = kind;
    const p = document.createElement('div');
    // v2.27.1：kind 落到 class（.hg-pop.slash 等样式选择器一直依赖它，
    // 此前漏加导致斜杠菜单紧凑样式从未生效、技能热替换也查不到 .hg-pop.skill）
    p.className = 'hg-pop ' + kind;
    p.innerHTML = html;
    anchor.parentElement.appendChild(p);
    const ar = anchor.getBoundingClientRect(), wr = _hgWrap.querySelector('.hg-card-wrap').getBoundingClientRect();
    p.style.left = Math.max(6, Math.min(ar.left - wr.left, wr.width - p.offsetWidth - 6)) + 'px';
    // v2.20：菜单底部贴 anchor 上缘悬浮。原来 CSS 写死 bottom:calc(100% - 2px)
    // 相对整个 card-wrap——菜单弹到输入区整体的上方（改版后那里直接是聊天流），
    // 用户反馈「不是悬浮贴着显示，跑上面显示了」。改内联按 anchor 实际位置算。
    p.style.bottom = (wr.bottom - ar.top + 6) + 'px';
    return p;
  }
