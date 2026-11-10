// harness ask-md.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  
// v3.5.241（用户实测实锤「工作区没显示askuser的」）：副位非高频重绘——
// 秒表 interval 只更新时长文本不重画 headSub，askRender/askDone/Dismiss
// 后必须主动刷一次，否则「待答」永不出现（v3.5.240 的查询式跟随推断错误）
function _hgAskHeadSync() {
  try {
    if (typeof _turnHeadSubPaint === 'function' && _HG.grp) _turnHeadSubPaint(_HG.grp);
  } catch (_) {}
}
function askRender(it) {
    if (!it || !it.req_id) return;
    // v3.4.61（ZCode 形态）：幂等跳过——同 req_id 且未 done 的面板已在场
    // （SSE snapshot 保留窗重放同帧 / _hgAskSync 与活流竞速）直接 return，
    // 不再先删后建（重建会清掉用户半选/草稿）。不同 req_id（后端单槽换新）
    // 仍走删旧建新。查重域 _hgWrap：覆盖 dock（新代）与 flow（老代迁移前）
    const _old = _hgWrap.querySelector(`[data-hg-ask="${CSS.escape(it.req_id)}"]`);
    if (_old && !_old.classList.contains('done')) return;
    if (_old) _old.remove();
    const qs = Array.isArray(it.questions) ? it.questions : [];
    if (!qs.length) return;

    // v3.4.60：ZCode 方案改造——多题分页（一次一题）、序号 chip 替代 radio、
    // 脚区「左提示 + 忽略/提交」。硬约束：待答卡根 class 恒恰 'h-ask'
    // （12-sessions 弃快照豁免按 class="h-ask" 精确串判定），分页状态走 dataset
    const paged = qs.length > 1;
    const card = document.createElement('div');
    card.className = 'h-ask h-ask-dock';   // v3.4.61：dock 修饰类（根类 h-ask 保留——phResume 判据靠它）
    card.dataset.hgAsk = it.req_id;
    card.dataset.hgQs = JSON.stringify(qs);   // 问题原文（提交时作 answer 的 key）
    card.dataset.hgSel = '{}';                // 题号 -> [选中的 label]
    if (paged) card.dataset.hgPage = '0';
    qs.forEach((_hgQ, qi) => {
      const multi = !!_hgQ.multiSelect;
      const box = document.createElement('div');
      box.className = paged ? 'h-ask-q h-ask-page' : 'h-ask-q';
      if (paged && qi === 0) box.classList.add('cur');
      box.innerHTML =
        `<div class="h-ask-head"><span class="h-ask-badge">${esc(_hgQ.header || '请选择')}</span>` +
        `<span class="h-ask-title">${esc(_hgQ.question || '')}</span>` +
        (multi ? '<span class="h-ask-multi">可多选</span>' : '') +
        (paged ? `<span class="h-ask-pgr">` +
          `<button class="h-ask-pgv" data-hg-pg="-1" title="上一题">‹</button>` +
          `<span class="h-ask-pgn"></span>` +
          `<button class="h-ask-pgv" data-hg-pg="1" title="下一题">›</button></span>` : '') +
        '</div>';
      const opts = document.createElement('div');
      opts.className = 'h-ask-opts';
      (_hgQ.options || []).forEach((o, oi) => {
        const label = typeof o === 'string' ? o : (o.label || '');
        const desc = typeof o === 'string' ? '' : (o.description || '');
        const b = document.createElement('button');
        b.className = 'h-ask-opt';
        b.dataset.hgAskOpt = String(qi);
        b.dataset.hgAskLabel = label;
        b.dataset.hgAskMulti = multi ? '1' : '';
        b.innerHTML = `<span class="h-ask-num">${oi + 1}</span>` +
          `<span class="h-ask-opt-txt"><b>${esc(label)}</b>` +
          (desc ? `<span class="h-ask-desc">${esc(desc)}</span>` : '') + `</span>`;
        opts.appendChild(b);
      });
      box.appendChild(opts);
      // v2.24.3：每题自由输入（用户定调「选项不够时要能自己打字」）——
      // 留空提交=纯选项；只输入不点选也放行（自由作答）
      const ex = document.createElement('div');
      ex.className = 'h-ask-extra';
      // a446（用户实锤「黑色弹窗与 UI 风格不符」）：这是 Edge 的自动填充
      // 建议面板（标题「保存的信息」）——它把本输入框当成可记忆的表单字段，
      // 弹出浏览器自绘的深色候选层，样式我们完全控制不了。提问作答是临时
      // 内容，不该进自动填充库。
      // autocomplete=off 在 Chromium 对「疑似登录/地址」字段会被忽略，所以
      // 三管齐下：off + type=search（浏览器不把它当表单字段存）+ 不设 name
      // （无 name 的表单字段不参与自动填充库）。
      ex.innerHTML = `<input class="h-ask-x" type="search" data-hg-askx="${qi}"
        spellcheck="false" autocomplete="off" aria-autocomplete="none"
        placeholder="输入你的回答…" title="回车提交">`;
      box.appendChild(ex);
      card.appendChild(box);
    });
    const foot = document.createElement('div');
    foot.className = 'h-ask-foot';
    const hint = document.createElement('span');
    hint.className = 'h-ask-hint';
    hint.textContent = '点击选择，可自由输入';
    const ignore = document.createElement('button');
    ignore.className = 'h-ask-ignore';
    ignore.dataset.hgAskSend = it.req_id;
    ignore.textContent = '忽略';
    const submit = document.createElement('button');
    submit.className = 'h-ask-submit';
    submit.dataset.hgAskSend = it.req_id;
    submit.textContent = '提交';
    submit.disabled = true;
    foot.appendChild(hint);
    foot.appendChild(ignore);
    foot.appendChild(submit);
    card.appendChild(foot);
    if (paged) askPage(card, 0);   // pgn 文本/边界 disabled 一次到位
    // v3.4.61（ZCode 形态）：面板 dock 到输入框正上方（.hg-card-wrap 内
    // 输入卡紧前）——不再入消息流。回底非强制：面板恒可见（不随滚动走），
    // 只带出回合尾部语境，不剥夺翻历史自由。dock 元素来自静态脚手架，
    // 缺失=异常态，早退不建孤儿面板（全审 F4）
    if (!_hgAskDockEl) return;
    _hgAskDockEl.appendChild(card);
    _hgAskDockEl.classList.add('on');
    // v3.5.246：live 提问即计入组 counts.askN（与 hist 路径同源——重渲后
    // hist 建档重建 counts，两路互斥不叠加）
    try {
      const _ga = _HG.grp || (typeof grpEnsure === 'function' && grpEnsure(true));
      if (_ga) {
        _ga.counts = _ga.counts || {};
        _ga.counts.askN = (_ga.counts.askN || 0) + 1;
      }
    } catch (_) {}
    _hgAskHeadSync();   // v3.5.241：ask 到达刷副位「待答」
    _hgScrollBottom();
  }
  // v3.4.60：多题分页翻页（ZCode ‹ 1/2 ›）——只切 cur 类不重建 DOM（草稿/选中
  // 全保留）；当前页走根 dataset.hgPage（随快照序列化），总页数现算防漂移。
  // 委托入口在 20-main（.h-ask-pgv），delta=0 用于渲染初始化
  function askPage(card, delta) {
    const pages = card.querySelectorAll('.h-ask-page');
    if (!pages.length) return;
    const p0 = +(card.dataset.hgPage || 0) || 0;
    const p = Math.max(0, Math.min(pages.length - 1, p0 + (delta || 0)));
    card.dataset.hgPage = String(p);
    pages.forEach((pg, i) => pg.classList.toggle('cur', i === p));
    // 每页 head 各有一份 pager——全量同步（当前页那份可见，其余随页隐藏）
    card.querySelectorAll('.h-ask-pgn').forEach(n =>
      { n.textContent = (p + 1) + '/' + pages.length; });
    card.querySelectorAll('.h-ask-pgv').forEach(v => {
      const d = parseInt(v.dataset.hgPg || '0', 10);
      v.disabled = (p === 0 && d < 0) || (p === pages.length - 1 && d > 0);
    });
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
    // v3.4.60：多题时 hint 报进度（跨页未答可见）；答满恢复引导语
    const ht = card.querySelector('.h-ask-hint');
    if (ht) ht.textContent = (need > 1 && ok < need)
      ? `已答 ${ok}/${need} 题` : '点击选择，可自由输入';
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
  function askSubmit(reqId, ignore) {
    const card = _hgWrap.querySelector(`[data-hg-ask="${CSS.escape(reqId)}"]`);   // v3.4.61：查重域扩到 dock
    if (!card || card.classList.contains('done')) return;
    const qs = askQs(card), sel = askSel(card);
    const answer = {};
    const extras = {};   // v2.56：自由输入随卡片存档——askDone 回显用
    // v3.4.60：忽略（ZCode 方案）——每题作答「（用户已忽略此提问）」，后端
    // 原样回传给阻塞中的 MCP 调用方，协议不变；hgIgn 标记供摘要行措辞
    if (ignore) {
      qs.forEach((_q, qi) => {
        answer[(_q && _q.question) || ('问题' + (qi + 1))] = '（用户已忽略此提问）';
      });
      card.dataset.hgIgn = '1';
    } else {
      delete card.dataset.hgIgn;   // 全审 P1：正常路径入口清忽略标记——防「忽略失败→改选正常提交」摘要误标
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const chosen = (sel[qi] || []).slice();
      const extra = askExtraText(card, qi);       // v2.24.3 自由输入并入作答
      if (!chosen.length && !extra) return;
      if (extra) extras[qi] = extra;
      const qtext = (qs[qi] && qs[qi].question) || ('问题' + (qi + 1));
      answer[qtext] = chosen.concat(extra ? ['补充：' + extra] : []).join(', ');
    });
    }
    if (!Object.keys(answer).length) return;
    try { card.dataset.hgExtra = JSON.stringify(extras); } catch (_) {}
    try { card.dataset.hgAns = JSON.stringify(answer); } catch (_) {}   // v3.4.60：askDone 摘要兜底源
    const btn = card.querySelector('.h-ask-submit');
    const ign = card.querySelector('.h-ask-ignore');
    if (btn) { btn.disabled = true; btn.textContent = '提交中…'; }
    if (ign) ign.disabled = true;
    const _restore = () => {   // v3.4.60：失败恢复双钮（含忽略）
      if (btn) { btn.disabled = false; btn.textContent = '提交'; }
      if (ign) ign.disabled = false;
      delete card.dataset.hgIgn;   // 全审 P1：忽略提交失败回滚标记——残留会让后续正常提交的摘要误标「已忽略」
    };
    fetch('/api/harness/ask/answer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sid: _HG.sid, req_id: reqId, answer})
    }).then(r => r.json()).then(j => {
      if (!j.ok) { _restore(); renderRaw('提交失败：' + (j.err || '')); }
    }).catch(() => { _restore(); });
  }
  function askDone(it) {
    _hgAskHeadSync();   // v3.5.241：作答→刷副位去「待答」
    const card = _hgWrap.querySelector(`[data-hg-ask="${CSS.escape(it.req_id || '')}"]`);   // v3.4.61：查重域扩到 dock
    // v3.4.61（ZCode 形态）：card 不在场（ask_done 迟到 / 他窗已答面板已收缩 /
    // SSE snapshot 重放）也继续——结果行按 req_id 幂等，数据走 it.answer
    // answer 兜底链——帧回显 > askSubmit 随卡存档的 hgAns（帧缺字段时兜住）
    let ans = it.answer || {};
    if (card && !Object.keys(ans).length) {
      try { ans = JSON.parse(card.dataset.hgAns || '{}') || {}; } catch (_) { ans = {}; }
    }
    // card 缺席时无 hgQs——从 answer 的 key 构造伪题面（结果行只需问题文本）
    const qs = card ? askQs(card) : Object.keys(ans).map(k => ({ question: k }));
    const ign = !!(card && card.dataset.hgIgn === '1');
    if (card) {
      card.classList.add('done');   // phResume 判据翻面（dock 面板 done 后不再复暖占位）
      // v3.2.31：选择器加 [data-hg-ask-opt]——补充说明选项卡（hg-ask-xopt，div）
      // 复用 .h-ask-opt 视觉但无该属性，重复 askDone 时不被下面的 .on 翻转清掉
      card.querySelectorAll('.h-ask-opt[data-hg-ask-opt]').forEach(b => { b.disabled = true; });
    // 自由输入回显（两代 done 卡形态并存边界）：
    // · v3.2.31 起（新代）：展示位=选项列表内的「补充说明」xopt 卡片（下方
    //   追加）；disabled 输入框只是数据载体，CSS `.h-ask.done .h-ask-x
    //   { display:none }` 恒隐藏——v2.56 当年「填回输入框保留显示」的注释与
    //   该 CSS 矛盾，以本段为准。
    // · v2.56→v3.1h（旧代）：展示位=disabled 输入框/底部附注行。v3.2.31 前
    //   生成的快照恢复时 DOM 原样带回旧形态（本函数不会重跑重造），不做迁移。
    // 数据源优先 askSubmit 存的 hgExtra（随快照走）；缺失（历史重放老卡片）
    // 时从 answer 串解析「补充：」段兜底。
    let extras = {};
    try { extras = JSON.parse(card.dataset.hgExtra || '{}'); } catch (_) {}
    card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
      const qtext = (qs[qi] && qs[qi].question) || ('问题' + (qi + 1));   // 全审轻微①：与 askSubmit 同键族
      const chosen = ans[qtext];
      if (!chosen) return;
      box.querySelectorAll('.h-ask-opt[data-hg-ask-opt]').forEach(b => {
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
      // v3.2.31（需求1）：补充说明选项卡化——xopt 卡插入该题选项列表末尾
      //（幂等先清后插；div+无 data-hg-ask-opt：不参与 askPick，锁定展示）
      box.querySelectorAll('.hg-ask-xopt').forEach(x => x.remove());
      const _xv = ((inp && inp.value) || '').trim();
      if (_xv) {
        const _opts = box.querySelector('.h-ask-opts');
        if (_opts) {
          const _xc = document.createElement('div');
          _xc.className = 'h-ask-opt hg-ask-xopt on';
          _xc.title = '用户的补充说明（已随作答提交）';
          const _chip = box.querySelector('.h-ask-num') ? '<span class="h-ask-num">✎</span>'
                                                        : '<span class="h-ask-radio"></span>';
          _xc.innerHTML = _chip +
            '<span class="h-ask-opt-txt"><b><span class="hg-ask-xbadge">补充说明</span>' +
            esc(_xv) + '</b></span>';
          _opts.appendChild(_xc);
        }
      }
    });
    const foot = card.querySelector('.h-ask-foot');
    if (foot) foot.innerHTML = `<span class="h-ask-done">✓ 已提交</span>`;
    // DOM 选中态兜底（answer 两级全空时重建——快照恢复卡收到迟到 ask_done）
    if (!Object.keys(ans).length) {
      card.querySelectorAll('.h-ask-q').forEach((box, qi) => {
        const on = [...box.querySelectorAll('.h-ask-opt[data-hg-ask-opt].on')]
          .map(b => b.dataset.hgAskLabel).filter(Boolean);
        if (on.length) ans[(qs[qi] && qs[qi].question) || ('问题' + (qi + 1))] = on.join(', ');
      });
    }
    }   // if (card) 收口
    // v3.4.61（ZCode 形态）：先落 flow 结果行（先留痕后消失——动画被打断也不
    // 丢痕），面板随即收缩消失（不再折叠成卡占消息流）
    // v4.0.0-a44（用户实测「回答完问题后才出现的平铺行」）：结果行退役——
    // 信息已由消息流提问卡（h-askcard）回答区承载；V3 无卡保留留痕行
    if (card) _hgAskDismiss(card);
  }
  // v3.4.61：flow 结果行——dim 单行「✓ 问题 → 答案 [共 N 题]」复用 .h-ask-sum
  // 的 span 族；按 req_id 幂等（data-hg-askr）；override 供失效路（已失效/已随
  // 会话中断失效）改写文案。落点=当前活组根（ask 属回合中途暂停，答后续跑同
  // 组），组不活兜底 flow 根
  // 过渡必须有起点数值；none→0 不播动画），240ms 后 remove（setTimeout 不用
  // transitionend——tab 后台 transitionend 不触发）；空 dock 收 .on；贴底联动
  function _hgAskDismiss(panel, override) {
    _hgAskHeadSync();   // v3.5.241：面板收缩→刷副位
    if (!panel || !panel.isConnected) return;
    panel.classList.add('done');
    // v4.0.0-a45：失效路结果行同 a44 退役（v4 唯一基准，a138 删尽）
    try { panel.style.maxHeight = panel.offsetHeight + 'px'; void panel.offsetWidth; } catch (_) {}
    panel.classList.add('hg-out');
    setTimeout(() => {
      panel.remove();
      if (_hgAskDockEl && !_hgAskDockEl.children.length) _hgAskDockEl.classList.remove('on');
      if (typeof isNearBottom === 'function' && isNearBottom()) _hgScrollBottom();
    }, 240);
  }
  // v3.4.61：快照恢复 dock——面板 outerHTML 回填 + 老代迁移（flow 里恢复出的
  // 待答卡 DOM 原样搬进 dock，dataset/半选/草稿/分页全保）；提交门槛是派生态
  // 重算作保险。html 为空 = 清场（switchTo(null)）
  function _hgAskDockRestore(html) {
    if (!_hgAskDockEl) return;
    _hgAskDockEl.innerHTML = html || '';
    const legacy = _hgFlow.querySelector('.h-ask:not(.done)');
    if (legacy) _hgAskDockEl.appendChild(legacy);
    _hgAskDockEl.classList.toggle('on', !!_hgAskDockEl.querySelector('.h-ask:not(.done)'));
    const p = _hgAskDockEl.querySelector('.h-ask:not(.done)');
    if (p) { try { askCheckDone(p); } catch (_) {} }
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
  // v3.5.7（用户拍板「忽略用户消息的一切特殊字符，不做显示变化和排版」）：
  // 用户气泡纯文本渲染——此前走 mdBubble，贴 diff/注释（行首 #）会被解析
  // 成一级标题变满屏大字（用户实锤「太难看了」）。esc + 换行→br + 连续
  // 空格→nbsp 保缩进；AI 回复仍走 mdBubble 不受影响
  function plainBubble(text) {
    const b = document.createElement('div');
    b.className = 'h-bubble';
    b.innerHTML = '<p style="white-space:pre-wrap;">' + esc(String(text || '')) + '</p>';
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
    // v3.5.253（用户实锤「拖 Y:\nfs\1.png 点了无法预览」）：chip 改走 path= 回源——拖入的是原路径
    // （网络盘/桌面/工程目录），不落上传目录，name= 只查 _UPLOAD_DIR 必 404；path= 白名单
    // 三覆盖（上传目录/CLI Temp images/任意存在图片路径 v3.5.136）拖路径正中第三条
      h += `<span class="hg-att-mini" data-img="/api/harness/file?path=${encodeURIComponent(p)}" title="${esc(p)}">${ICO16.camera} ${esc(name)}</span>`;
    });
    (files || []).forEach(p => { h += `<span class="hg-att-mini">${ICO16.file} ${esc(String(p).split(/[\\/]/).pop())}</span>`; });
    return h;
  }
  function openLightbox(src) {
    const ov = document.createElement('div');
    ov.className = 'hg-lightbox';
    ov.innerHTML = `<img src="${esc(src)}" alt=""><button class="hg-lightbox-x" title="关闭 (Esc)">✕</button>`;
    // v3.5.256（用户需求）：原图已删除/路径失效 → 取后端 err 文案显提醒层
    // （后端 404=「文件不存在或已删除：<路径>」，其他失败回落通用文案）
    const _im = ov.querySelector('img');
    _im.onerror = async () => {
      let msg = '图片无法加载（文件可能已不存在或已删除）';
      try { const j = await (await fetch(src)).json(); if (j && j.err) msg = j.err; } catch (_) {}
      const tip = document.createElement('div');
      tip.className = 'hg-lightbox-err';
      tip.textContent = msg;
      _im.replaceWith(tip);
    };
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
  // 忠实序列化。批4（迁出主窗）：_hgSubSaveOpen 与 sub: 折叠键随段退役删除
  //——_hgLoadOpen 保留（openState 仍作「回放重建期」标志位被 groups 消费）
  function _hgLoadOpen(sid) {
    try { return JSON.parse(localStorage.getItem('hg-open:' + sid) || '{}') || {}; } catch(_) { return {}; }
  }
