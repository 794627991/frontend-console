// harness ask-md.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function askRender(it) {
    if (!it || !it.req_id) return;
    const old = _hgFlow.querySelector(`[data-hg-ask="${CSS.escape(it.req_id)}"]`);
    if (old) old.remove();
    const qs = Array.isArray(it.questions) ? it.questions : [];
    if (!qs.length) return;

    const card = document.createElement('div');
    card.className = 'h-ask';
    card.dataset.hgAsk = it.req_id;
    card.dataset.hgQs = JSON.stringify(qs);   // 问题原文（提交时作 answer 的 key）
    card.dataset.hgSel = '{}';                // 题号 -> [选中的 label]
    qs.forEach((_hgQ, qi) => {
      const multi = !!_hgQ.multiSelect;
      const box = document.createElement('div');
      box.className = 'h-ask-q';
      box.innerHTML =
        `<div class="h-ask-head"><span class="h-ask-badge">${esc(_hgQ.header || '请选择')}</span>` +
        `<span class="h-ask-title">${esc(_hgQ.question || '')}</span>` +
        (multi ? '<span class="h-ask-multi">可多选</span>' : '') + '</div>';
      const opts = document.createElement('div');
      opts.className = 'h-ask-opts';
      (_hgQ.options || []).forEach((o) => {
        const label = typeof o === 'string' ? o : (o.label || '');
        const desc = typeof o === 'string' ? '' : (o.description || '');
        const b = document.createElement('button');
        b.className = 'h-ask-opt';
        b.dataset.hgAskOpt = String(qi);
        b.dataset.hgAskLabel = label;
        b.dataset.hgAskMulti = multi ? '1' : '';
        b.innerHTML = `<span class="h-ask-radio"></span>` +
          `<span class="h-ask-opt-txt"><b>${esc(label)}</b>` +
          (desc ? `<span class="h-ask-desc">${esc(desc)}</span>` : '') + `</span>`;
        opts.appendChild(b);
      });
      box.appendChild(opts);
      // v2.24.3：每题自由输入（用户定调「选项不够时要能自己打字」）——
      // 留空提交=纯选项；只输入不点选也放行（自由作答）
      const ex = document.createElement('div');
      ex.className = 'h-ask-extra';
      ex.innerHTML = `<input class="h-ask-x" data-hg-askx="${qi}" spellcheck="false"
        placeholder="其他 / 补充说明（可直接输入，回车提交）">`;
      box.appendChild(ex);
      card.appendChild(box);
    });
    const foot = document.createElement('div');
    foot.className = 'h-ask-foot';
    const submit = document.createElement('button');
    submit.className = 'h-ask-submit';
    submit.dataset.hgAskSend = it.req_id;
    submit.textContent = '提交选择';
    submit.disabled = true;
    const hint = document.createElement('span');
    hint.className = 'h-ask-hint';
    hint.textContent = '选择后提交，AI 会继续';
    foot.appendChild(submit);
    foot.appendChild(hint);
    card.appendChild(foot);
    _hgFlow.appendChild(card);
    // v2.27：ask 卡片 = AI 阻塞等作答，必须让用户看见。无 force 的
    // scrollBottom 在翻历史时被 150px 阈值拦下（用户实锤「弹出时要自己
    // 翻页找」）。这里无条件把卡片顶部滚进视口：多题卡片从题1看起，
    // 而不是只露出提交按钮。
    _hgScrollBottom(true);
    requestAnimationFrame(() => card.scrollIntoView({ block: 'start' }));
  }
  function askQs(card) {
    try { return JSON.parse(card.dataset.hgQs || '[]'); } catch (_) { return []; }
  }
  function askSel(card) {
    try { return JSON.parse(card.dataset.hgSel || '{}'); } catch (_) { return {}; }
  }
  function askSelSet(card, sel) { card.dataset.hgSel = JSON.stringify(sel); }
  function askExtraText(card, qi) {
    const inp = card.querySelector(`[data-hg-askx="${qi}"]`);
    return inp ? inp.value.trim() : '';
  }
  function askCheckDone(card) {
    const sel = askSel(card);
    const need = card.querySelectorAll('.h-ask-q').length;
    let ok = 0;
    for (let k = 0; k < need; k++)
      if ((sel[k] || []).length || askExtraText(card, k)) ok++;
    const sb = card.querySelector('.h-ask-submit');
    if (sb) sb.disabled = ok < need;
  }
  function askPick(btn) {
    const card = btn.closest('.h-ask');
    if (!card || card.classList.contains('done')) return;
    const qi = btn.dataset.hgAskOpt;
    const multi = !!btn.dataset.hgAskMulti;
    const sel = askSel(card);
    if (!sel[qi]) sel[qi] = [];
    const label = btn.dataset.hgAskLabel || '';
    if (multi) {
      const i = sel[qi].indexOf(label);
      if (i >= 0) sel[qi].splice(i, 1); else sel[qi].push(label);
      btn.classList.toggle('on', i < 0);
    } else {
      sel[qi] = [label];
      card.querySelectorAll(`[data-hg-ask-opt="${qi}"]`).forEach(b => {
        b.classList.toggle('on', b === btn);
      });
    }
    askSelSet(card, sel);
    askCheckDone(card);
  }
  function askSubmit(reqId) {
    const card = _hgFlow.querySelector(`[data-hg-ask="${CSS.escape(reqId)}"]`);
    if (!card || card.classList.contains('done')) return;
    const qs = askQs(card), sel = askSel(card);
    const answer = {};
    const extras = {};   // v2.56：自由输入随卡片存档——askDone 回显用
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const chosen = (sel[qi] || []).slice();
      const extra = askExtraText(card, qi);       // v2.24.3 自由输入并入作答
      if (!chosen.length && !extra) return;
      if (extra) extras[qi] = extra;
      const qtext = (qs[qi] && qs[qi].question) || ('问题' + (qi + 1));
      answer[qtext] = chosen.concat(extra ? ['补充：' + extra] : []).join(', ');
    });
    if (!Object.keys(answer).length) return;
    try { card.dataset.hgExtra = JSON.stringify(extras); } catch (_) {}
    const btn = card.querySelector('.h-ask-submit');
    if (btn) { btn.disabled = true; btn.textContent = '提交中…'; }
    fetch('/api/harness/ask/answer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sid: _HG.sid, req_id: reqId, answer})
    }).then(r => r.json()).then(j => {
      if (!j.ok) { if (btn) { btn.disabled = false; btn.textContent = '提交选择'; } renderRaw('⚠ 提交失败：' + (j.err || '')); }
    }).catch(() => { if (btn) { btn.disabled = false; btn.textContent = '提交选择'; } });
  }
  function askDone(it) {
    const card = _hgFlow.querySelector(`[data-hg-ask="${CSS.escape(it.req_id || '')}"]`);
    if (!card) return;
    card.classList.add('done');
    card.querySelectorAll('.h-ask-opt').forEach(b => { b.disabled = true; });
    const ans = it.answer || {};
    const qs = askQs(card);
    // v2.56：自由输入回显——提交的自定义文本填回输入框（disabled 保留显示），
    // 不再「提交后自行填入那栏不显示」。数据源优先 askSubmit 存的 hgExtra
    // （随快照走）；缺失（历史重放老卡片）时从 answer 串解析「补充：」段兜底。
    let extras = {};
    try { extras = JSON.parse(card.dataset.hgExtra || '{}'); } catch (_) {}
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const qtext = (qs[qi] && qs[qi].question) || '';
      const chosen = ans[qtext];
      if (!chosen) return;
      box.querySelectorAll('.h-ask-opt').forEach(b => {
        b.classList.toggle('on', String(chosen).split(', ').indexOf(b.dataset.hgAskLabel) >= 0);
      });
      const inp = box.querySelector('.h-ask-x');
      if (inp) {
        let ex = extras[qi] || '';
        if (!ex) {
          const m = String(chosen).match(/(?:^|, )补充：(.*)$/);
          if (m) ex = m[1];
        }
        if (ex) {
          inp.value = ex;
          inp.title = '已提交的自由输入';
        }
        inp.disabled = true;
      }
    });
    const foot = card.querySelector('.h-ask-foot');
    if (foot) {
      // v3.1h：备注显式回显（用户实锤「备注没体现出来」——此前只回填 disabled
      // 输入框，视觉上像选项描述小字，看不出是自己的补充）。提交态在底部
      // 单独一行列出全部自由输入，历史重放同走此处（extras 从 answer 串兜底）。
      const notes = [];
      card.querySelectorAll('.h-ask-x').forEach(inp => {
        const v = (inp.value || '').trim();
        if (v) notes.push(v);
      });
      foot.innerHTML = `<span class="h-ask-done">✓ 已提交</span>` +
        (notes.length ? ` <span class="h-ask-note">📝 补充说明：${esc(notes.join('；'))}</span>` : '');
    }
  }
  // v3.0 高亮缓存池（对照 ZCode shikiHighlighter.ts:56 的指纹 key + 结果
  // 缓存）：key=语言:长度:首100:尾100（不存全文防 key 本身膨胀）；命中直接
  // innerHTML 回填跳过 hljs 解析（流式/lazy IO/重渲三路重复高亮同一代码块
  // 是 CPU 大户）。Map 插入序即 LRU 序，上限 500 逐出最老（ZCode 审计明记
  // tokensCache 无淘汰是 renderer 内存增长点——这里不重蹈）。
  const _hlCache = new Map();
  const _HL_CACHE_MAX = 500;
  function _hlKey(lang, raw) {
    return lang + ':' + raw.length + ':' + raw.slice(0, 100)
           + ':' + (raw.length > 100 ? raw.slice(-100) : '');
  }
  function codeBlockEnhance(container) {
    // markdown-it 产物里的 pre > code：套 ChatGPT 式容器（语言标签+复制钮）
    container.querySelectorAll('pre > code').forEach(code => {
      const pre = code.parentElement;
      if (pre.parentElement && pre.parentElement.classList.contains('hg-code')) return;  // 已处理
      const raw = code.textContent.replace(/\n$/, '');
      const m = /language-(\S+)/.exec(code.className || '');
      const lang = m ? m[1] : '';
      const box = document.createElement('div');
      box.className = 'hg-code';
      const head = document.createElement('div');
      head.className = 'hg-code-head';
      head.innerHTML = `<span>${esc(lang || 'text')}</span>`;
      const cp = document.createElement('button');
      cp.className = 'hg-code-copy'; cp.textContent = '复制'; cp.title = '复制代码';
      // 点击由 flow 委托处理（v2.12——快照恢复后行内绑定失活）
      head.appendChild(cp);
      pre.replaceWith(box);
      box.appendChild(head);
      box.appendChild(pre);
      if (window.hljs && lang && hljs.getLanguage(lang)) {
        try {
          const k = _hlKey(lang, raw);
          const hit = _hlCache.get(k);
          if (hit !== undefined) {
            code.innerHTML = hit; code.classList.add('hg-hl');
          } else {
            hljs.highlightElement(code); code.classList.add('hg-hl');
            _hlCache.set(k, code.innerHTML);
            if (_hlCache.size > _HL_CACHE_MAX)
              _hlCache.delete(_hlCache.keys().next().value);
          }
        } catch(_) {}
      }
    });
  }
  function copyText(t) {
    return new Promise(res => {
      let ok = false;
      try {
        navigator.clipboard.writeText(t).then(() => res(true)).catch(() => res(false));
        ok = true;   // async 路径已接管
      } catch(_) {}
      if (!ok) {
        try { const ta = document.createElement('textarea'); ta.value = t;
          document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); res(true); }
        catch(_) { res(false); }
      }
    });
  }
  function renderMd(text) {
    const md = _harnessMdInstance();
    if (md) {
      const html = md.render(_hgNormalizeFences(text || ''));
      const t = document.createElement('div');
      t.innerHTML = html;
      // v2.27.22：一律拦截就地导航——http(s) 链接转系统浏览器打开（后端
      // /api/open_url），其余（相对路径/伪协议）只提示。WebView 一旦离开
      // 应用页面整个工具就被错误页替换且无返回入口（用户实锤）
      t.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        a.addEventListener('click', e => {
          e.preventDefault();
          if (/^https?:/i.test(href)) {
            fetch('/api/open_url', {method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({url: href})}).catch(() => {});
          }
        });
        a.title = /^https?:/i.test(href) ? '在系统浏览器中打开' : '工具内不支持跳转内部链接';
      });
      _hgImgReserve(t);   // v3.2.11：已知尺寸的图片立即占位（防重渲后图载入高度突跳=抽搐根源之一）
      return t.innerHTML;
    }
    return '<p>' + esc(text).replace(/\n/g, '<br>') + '</p>';
  }
  // v3.2.11（用户实锤「滚动条抽搐」根源之二）：图片尺寸缓存——img 首次装载
  // 后记 src→宽高；重渲（扩段/收缩/切会话整体重建 DOM）时同图立即按
  // aspect-ratio 占位，不再「先 0 高、载完弹开 200+px」把贴底判定和滚动
  // 位置弹飞。监听挂 document 捕获 phase（img 的 load 不冒泡）
  const _hgImgSizeCache = {};
  function _hgImgReserve(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('img').forEach(im => {
      const c = _hgImgSizeCache[im.getAttribute('src') || ''];
      if (c) im.style.aspectRatio = c[0] + ' / ' + c[1];
    });
  }
  document.addEventListener('load', (e) => {
    const t = e.target;
    if (t && t.tagName === 'IMG' && t.naturalWidth > 0) {
      const k = t.getAttribute('src') || '';
      if (k && !_hgImgSizeCache[k]) _hgImgSizeCache[k] = [t.naturalWidth, t.naturalHeight];
    }
  }, true);
  function mdBubble(text) {
    const b = document.createElement('div');
    b.className = 'h-bubble';
    b.innerHTML = renderMd(text);
    // v2.24 懒高亮：历史路径（histAll 在场=重建/懒填）延后到可视时才增强+
    // 高亮（ChatGPT 式容器/复制钮/hljs 都是 CPU 大户，初始 50 条窗口里几十
    // 个代码块白高亮——默认翻阅根本看不到）。流式路径保持即时（用户正看）。
    if (_HG.histAll) _codeLazyEnhance(b); else codeBlockEnhance(b);
    return b;
  }
  function _codeLazyEnhance(container) {
    const codes = container.querySelectorAll('pre > code');
    if (!codes.length) return;
    if (typeof IntersectionObserver === 'undefined') { codeBlockEnhance(container); return; }
    if (!_codeIO) {
      _codeIO = new IntersectionObserver((ents) => {
        ents.forEach(en => {
          if (!en.isIntersecting) return;
          _codeIO.unobserve(en.target);
          const pre = en.target.parentElement;
          if (pre && pre.isConnected) codeBlockEnhance(pre.parentElement || pre);
        });
      }, { rootMargin: '200px' });   // 视口外 200px 提前量，滚动时亮得无感
    }
    codes.forEach(c => _codeIO.observe(c));
  }
  function attChipsHtml(images, files) {
    let h = '';
    // v2.3.3 data-img 走 /api/harness/file 只读接口——原来直接塞本地绝对路径
    // （C:\Users\...），WebView 安全策略禁止 http 页面加载本地文件，Lightbox
    // 弹了也是裂图（用户实锤「无法弹出显示」）。title 保留完整路径供核对。
    // v3.2.16（用户最后定调，复原）：chip 恒用 name=（上传目录原件，新旧后端
    // 都能回源）——v3.2.14 的 path= 依赖新路由，未重启后端时点开全裂
    (images || []).forEach(p => {
      const name = String(p).split(/[\\/]/).pop();
      h += `<span class="hg-att-mini" data-img="/api/harness/file?name=${encodeURIComponent(name)}" title="${esc(p)}">🖼 ${esc(name)}</span>`;
    });
    (files || []).forEach(p => { h += `<span class="hg-att-mini">📄 ${esc(String(p).split(/[\\/]/).pop())}</span>`; });
    return h;
  }
  function openLightbox(src) {
    const ov = document.createElement('div');
    ov.className = 'hg-lightbox';
    ov.innerHTML = `<img src="${esc(src)}" alt=""><button class="hg-lightbox-x" title="关闭 (Esc)">✕</button>`;
    ov.addEventListener('click', (e) => { if (e.target === ov || e.target.classList.contains('hg-lightbox-x')) ov.remove(); });
    ov.addEventListener('keydown', () => {});
    const escFn = (e) => { if (e.key === 'Escape') { ov.remove(); document.removeEventListener('keydown', escFn); } };
    document.addEventListener('keydown', escFn);
    _hgWrap.appendChild(ov);
  }
  // v3.2.1（用户实测问题2）：位置键开合记忆（_hgPathKey/_hgSaveOpen/
  // _hgApplyOpen）整体退役——键按 DOM 位置索引链编，跨 DOM 代际（v3.1 抽屉
  // ↔v3.2 时间线结构差、回滚截断、扩段窗移）同键指向不同元素，旧记录误开
  // 新行还误标 userToggled（用户实锤「终端默认全部不收起」）。重建统一默认
  // 收起；开合在当前 DOM 生命周期内有效，用户意图经快照 dataset（userToggled）
  // 忠实序列化。hg-open:<sid> 仓保留唯一消费方：sub:<agentId> 语义键（稳定
  // 不漂移，见 _hgSubSaveOpen / renderHistSub）
  function _hgLoadOpen(sid) {
    try { return JSON.parse(localStorage.getItem('hg-open:' + sid) || '{}') || {}; } catch(_) { return {}; }
  }
  function _hgSubSaveOpen(blk, isOpen) {
    const aid = blk && blk.dataset && blk.dataset.hgSubblock;
    if (!_HG.sid || !aid) return;
    try {
      const st = _hgLoadOpen(_HG.sid);
      // v3.2.1R(F5)：顺手清位置键时代遗留的非 sub: 死键（唯一写入方做迁移，
      // 老仓不再随会话累积撑 localStorage）
      Object.keys(st).forEach(k => { if (k.indexOf('sub:') !== 0) delete st[k]; });
      st['sub:' + aid] = isOpen ? 1 : 0;
      localStorage.setItem('hg-open:' + _HG.sid, JSON.stringify(st));
    } catch(_) {}
  }
