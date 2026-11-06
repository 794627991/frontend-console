// a333 批1：代码跳转（ctags 索引 + 编译白名单 + ELF 符号表）
// R15-1 实锤修正：standalone Monaco 对未知 uri 没有内容服务——provider
// 返回 uri 只会得到空白/无反应。改自定义跳转：Ctrl+Click/F12 → 查询 →
// 唯一可信候选 openFileSmart 直跳；多候选弹带徽标的候选面板（原批 2
// 提前落地）。provider 注册保留但恒返回 null（防 Monaco 原生空跳干扰）。
(function () {
  'use strict';

  function monacoWordAt(model, position) {
    // 实测部分列位/语言下 getWordAtPosition 返回空——行内容手动提词兜底
    try {
      const w = model.getWordAtPosition(position);
      if (w && w.word) return w.word;
    } catch (_) {}
    try {
      const line = model.getLineContent(position.lineNumber) || '';
      const ISW = c => /[A-Za-z0-9_$]/.test(c || '');
      // a365R（用户实测 _get_pty 后括号上按 F12 无反应）：旧兜底只向左探
      // 1 格——落在 '()' 或 '():' 上直接空词静默。向左滑到最近词字符
      // （限 8 格防无限滑），$:JS 词合法字符
      let i = Math.max(0, position.column - 1);
      let guard = 8;
      while (!ISW(line[i]) && i > 0 && guard-- > 0) i -= 1;
      if (!ISW(line[i])) return '';
      let s = i, e = i;
      while (s > 0 && ISW(line[s - 1])) s--;
      while (e < line.length && ISW(line[e])) e++;
      return line.slice(s, e);
    } catch (_) { return ''; }
  }

  function modelFilePath(model) {
    // Monaco uri.path 是 URL 编码形态（file:///d%3A/AI/...）——解码剥前导
    // 斜杠成 Windows 盘符路径。R15-6：含裸 % 的路径 decodeURIComponent
    // 抛 URIError——try 兜底退原文
    let p = '';
    try { p = decodeURIComponent(model.uri.path || ''); }
    catch (_) { p = model.uri.path || ''; }
    return p.replace(/^\/([A-Za-z]):/, '$1:');
  }

  // ============================================================
  // a360R（用户需求2，VSCode 同款）：导航历史 back / forward
  // VSCode 的命令是 workbench.action.navigateBack / navigateForward，默认
  // Alt+← / Alt+→（macOS Ctrl+- / Ctrl+Shift+-）。默认与 VSCode 一致用 Alt+← / Alt+→，键位可在设置页录制修改
  // （与 F12 那三项放一起）。
  //
  // 语义照抄 VSCode：
  //   · 栈里存「位置」{portId, path, line, col}，不是文件——同一文件的两个
  //     不同函数是两个历史项；
  //   · 连续跳到同一位置不重复压栈（否则来回跳一次要点好几次才能回去）；
  //   · back/forward 时**不压栈**，只移动游标；游标之后的位置在前进时被丢弃
  //     （标准浏览器历史语义）；
  //   · 只在「跳转类动作」压栈（转到定义、查找引用点击、工作区符号点击），
  //     普通切 tab 不算导航。
  // ============================================================
  const NAV_HIST = { stack: [], cur: -1, MAX: 200 };

  function _navPos(editor) {
    try {
      const m = editor.getModel();
      if (!m) return null;
      const p = editor.getPosition();
      return { path: modelFilePath(m), line: (p && p.lineNumber) || 1,
               col: (p && p.column) || 1 };
    } catch (_) { return null; }
  }

  // 可导航的路径：盘符路径 或 UNC 共享路径（a375R 审计 P2-5：原先只认盘符，
  // 工程放在 \\server\share 时整个历史功能静默失效）
  function _navPathOk(p) {
    return !!p && (/^[A-Za-z]:[\\/]/.test(p) || /^\\\\[^\\]+\\[^\\]+/.test(p));
  }

  function navPush(pos) {
    if (!pos || !_navPathOk(pos.path)) return;
    const s = NAV_HIST.stack, i = NAV_HIST.cur;
    const prev = i >= 0 ? s[i] : null;
    // 同一位置连续记录无意义（VSCode 同样去重）。
    // a375R（审计 P3-1）：只更新 col 不改 line；且**保留首次落点的列**——
    // VSCode 恢复历史条目时用的是该条目原始的 Selection，不会因为后来又
    // 在这一行别的位置停留过就被改写。
    if (prev && prev.path === pos.path && prev.line === pos.line) return;
    s.splice(i + 1);              // 丢弃游标之后的历史
    s.push(pos);
    if (s.length > NAV_HIST.MAX) s.shift();
    NAV_HIST.cur = s.length - 1;
  }

  function navJumpTo(pos) {
    if (!pos) return false;
    // 复用既有跳转通道：openFileSmart 会按路径去重并定位行列。
    // 返回 false 表示「目标已不可达」（文件被删/盘掉线）——openFileSmart
    // 在失败时会降级去开阅读器 tab（见审计 P2-3），这里给 noFallback
    // 让它直接失败返回，由调用方决定跳过。
    const r = openFileSmart(pos.path, 'auto',
                            { line: Math.max(1, pos.line || 1),
                              col: pos.col || 1, noFallback: true });
    if (r && typeof r.then === 'function') {
      // openFileSmart 是 async，返回 true / false / 'cancelled'
      // （'cancelled' = 用户在打开方式弹窗里点了取消，不算不可达）
      return r.catch(function () { return false; });
    }
    return true;
  }

  function _navStep(dir, budget) {
    // a375R（审计 P2-3，VSCode 同款）：目标文件已删除/不可达时，**跳过该项
    // 继续沿方向移动**，游标停在真正能到的那一项——不会出现「按了没反应，
    // 还多开一个空 tab」。
    // a377R（第2轮审计）：异步分支里递归 _navStep 时，`n` 是每次调用的局部
    // 变量 → 重置为 0，理论上可无限递归。改为**传预算**，每次递归减一。
    const s = NAV_HIST.stack;
    let left = (budget === undefined ? NAV_HIST.MAX : budget);
    while (s.length && left-- > 0) {
      const next = NAV_HIST.cur + dir;
      if (next < 0) { showBanner('已经是最早的位置', 1800); return; }
      if (next > s.length - 1) { showBanner('已经是最新的位置', 1800); return; }
      const prevCur = NAV_HIST.cur;
      NAV_HIST.cur = next;
      const item = s[next];
      const r = navJumpTo(item);
      if (r === false) {
        showBanner('目标位置已不可达，已跳过：' + (item.path || ''), 2600);
        continue;   // 沿同方向继续
      }
      if (r && typeof r.then === 'function') {
        // 异步通道：拿到结果后再决定是否继续跳（先返回，避免卡住按键）
        // 预算一并传下去——异步失败继续找的时候不能再从 MAX 重新数
        r.then(function (ok) {
          // a380R（第2轮审计 P3-2）：'cancelled' = 用户在打开方式弹窗里取消，
          // 不是不可达——游标退回原位，不报跳过、不继续找。
          // a381R（第3轮审计）：prevCur 是幂等的过期快照——用户等弹窗期间
          // 若又按了别的键，cur 已经变了，此时无条件赋值会把游标改回去。
          // 只在「游标仍停在我这一格」时才回退。
          if (ok === 'cancelled') {
            if (NAV_HIST.cur === next) NAV_HIST.cur = prevCur;
            return;
          }
          // a381R：异步失败继续找时，若用户在等待期间又按了键（cur 已变），
          // 继续沿原方向跳会覆盖用户的新操作——只在没被打断时继续。
          if (!ok) { if (NAV_HIST.cur === next) _navStep(dir, left); }
        }).catch(function () {});
      }
      return;
    }
  }

  function navigateBack() { _navStep(-1); }
  function navigateForward() { _navStep(1); }

  // 跳转类动作统一入口：先记下「从哪跳的」，再执行跳转。
  // a360R（关键）：**目标和来源都要进栈**。只压来源的话，第一次跳转后栈里
  // 只有 [A]、游标停在 0，navigateBack 直接判「已经是最早的位置」——永远
  // 回不去。VSCode 的语义是「跳到 B 之后，历史里有 A 和 B 两项」，
  // back 回到 A、forward 再回到 B。
  // a375R（审计 P2-6）：目标必须在**真正打开成功之后**才入栈——用户在
  // 「选择打开方式」弹窗里点取消时，原先会留下一个从未去过的幽灵历史项。
  // a378R：openFileSmart 是异步的，连续快速跳转 A→B→C 时三个 Promise 可能
  // 乱序 resolve → 历史顺序错乱。加序号，只有最新的那次跳转才写栈。
  let _jumpSeq = 0;
  function _jumpOpen(fromEditor, path, opts) {
    const from = _navPos(fromEditor);
    const mine = ++_jumpSeq;
    const commit = function () {
      if (mine !== _jumpSeq) return;   // 已被更新的跳转取代，丢弃
      navPush(from);
      navPush({ path: path, line: (opts && opts.line) || 1,
                col: (opts && opts.col) || 1 });
    };
    const r = openFileSmart(path, 'auto', opts);
    if (r && typeof r.then === 'function') {
      r.then(function (ok) {
        // a380R：'cancelled'（用户取消打开方式）是 truthy 但不是成功——
        // 必须显式排除，否则取消也会被记进历史
        if (!ok || ok === 'cancelled') return;
        commit();
      }).catch(function () {});
    } else {
      commit();                          // 同步路径兜底
    }
  }

  async function queryDefinition(model, position) {
    const word = monacoWordAt(model, position);
    if (!word || word.length < 2) return null;
    const file = modelFilePath(model);
    if (!/^[A-Za-z]:/.test(file)) return null;   // inmemory/未命名文件
    const r = await fetch('/api/nav/definition?file=' + encodeURIComponent(file) +
                          '&symbol=' + encodeURIComponent(word));
    const j = await r.json();
    if (!j.ok || !j.candidates || !j.candidates.length) return null;
    return j;
  }

  // 自定义跳转主入口（Ctrl+Click / F12 / Ctrl+F12 都走这）
  async function gotoDefinition(editor) {
    let model = null, pos = null;
    try {
      model = editor.getModel();
      pos = editor.getPosition();
    } catch (_) { return; }
    if (!model || !pos) return;
    let j = null;
    try { j = await queryDefinition(model, pos); } catch (_) { return; }
    if (!j) {
      showBanner('未找到定义（无索引或符号不在库内）——文件树右键可建索引', 2600);
      return;
    }
    const cands = j.candidates;
    if (j.auto || cands.length === 1) {
      const c = cands[0];
      _jumpOpen(editor, c.path, { line: Math.max(1, c.line || 1) });
      return;
    }
    _showCandidates(j, editor);
  }

  // 候选面板（多结果）：✓编译内 / ✗未编译 / ~头文件 徽标 + 路径分组
  function _showCandidates(j, srcEditor) {
    _closeCands();
    const ov = document.createElement('div');
    ov.id = 'navCandsPanel';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.25);z-index:9999;display:flex;align-items:flex-start;justify-content:center;padding-top:12vh;';
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) _closeCands(); });
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:640px;max-width:92vw;max-height:60vh;overflow:auto;padding:14px 16px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.4);';
    const title = document.createElement('div');
    title.textContent = '「' + j.symbol + '」的 ' + j.candidates.length + ' 个定义';
    title.style.cssText = 'font-weight:600;margin-bottom:8px;';
    card.appendChild(title);
    const badge = function (b) {
      return b === true ? '✓ 编译内' : (b === false ? '✗ 未编译' : '~ 头文件');
    };
    j.candidates.forEach(function (c) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:10px;align-items:center;padding:6px 8px;border-radius:6px;cursor:pointer;';
      row.onmouseenter = function () { row.style.background = 'var(--border)'; };
      row.onmouseleave = function () { row.style.background = ''; };
      const b = document.createElement('span');
      b.textContent = badge(c.in_build);
      b.style.cssText = 'font-size:11px;flex-shrink:0;color:' +
        (c.in_build === true ? 'var(--accent)' : (c.in_build === false ? 'var(--neon-red,#e5484d)' : 'var(--muted)'));
      const pathEl = document.createElement('span');
      pathEl.textContent = c.rel + ' :' + (c.line || 1);
      pathEl.style.cssText = 'font-family:var(--font-mono);font-size:12px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;';
      const kind = document.createElement('span');
      kind.textContent = c.kind || '';
      kind.style.cssText = 'font-size:11px;color:var(--muted);flex-shrink:0;';
      row.appendChild(b); row.appendChild(pathEl); row.appendChild(kind);
      row.onclick = function () {
        _closeCands();
        _jumpOpen(srcEditor, c.path, { line: Math.max(1, c.line || 1) });
      };
      card.appendChild(row);
    });
    ov.appendChild(card);
    document.body.appendChild(ov);
  }

  function _closeCands() {
    const el = document.getElementById('navCandsPanel');
    if (el) el.remove();
  }

  // ---- 工作区符号面板（Ctrl+T，批2）----
  let _symTimer = null;

  function showWorkspaceSymbols(ed) {
    _closeCands();
    const ov = document.createElement('div');
    ov.id = 'navSymPanel';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.25);z-index:9999;display:flex;align-items:flex-start;justify-content:center;padding-top:10vh;';
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) _closeSym(); });
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:640px;max-width:92vw;max-height:62vh;display:flex;flex-direction:column;padding:12px 14px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.4);';
    const input = document.createElement('input');
    input.className = 'dd-input';
    input.placeholder = '工作区符号搜索（前缀/子串）…';
    input.style.cssText = 'width:100%;box-sizing:border-box;';
    card.appendChild(input);
    const list = document.createElement('div');
    list.style.cssText = 'margin-top:8px;overflow:auto;flex:1;';
    card.appendChild(list);
    ov.appendChild(card);
    document.body.appendChild(ov);
    input.focus();
    const file = ed && ed.getModel() ? modelFilePath(ed.getModel()) : '';
    input.addEventListener('input', function () {
      if (_symTimer) clearTimeout(_symTimer);
      const q = input.value.trim();
      if (!q) { list.innerHTML = ''; return; }
      _symTimer = setTimeout(async () => {
        try {
          const r = await fetch('/api/nav/symbols?file=' + encodeURIComponent(file) +
                                '&q=' + encodeURIComponent(q));
          const j = await r.json();
          if (input.value.trim() !== q) return;   // 竞态守卫
          list.innerHTML = '';
          if (!j.ok || !j.items || !j.items.length) {
            const d = _h('div', j.err === 'no-index' ? '该文件不在索引库内' : '无匹配符号');
            d.style.cssText = 'color:var(--muted);font-size:12px;padding:8px;';
            list.appendChild(d);
            return;
          }
          j.items.forEach(function (it) {
            const row = document.createElement('div');
            row.className = 'nav-sym-row';
            row.style.cssText = 'display:flex;gap:10px;align-items:center;padding:5px 8px;border-radius:6px;cursor:pointer;';
            row.onmouseenter = function () { row.style.background = 'var(--border)'; };
            row.onmouseleave = function () { row.style.background = ''; };
            const n = _h('span', it.name);
            n.style.cssText = 'font-family:var(--font-mono);font-size:12.5px;font-weight:600;flex-shrink:0;max-width:220px;overflow:hidden;text-overflow:ellipsis;';
            const p = _h('span', it.rel + ' :' + (it.line || 1));
            p.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--muted);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            const k = _h('span', (it.kind || '') + (it.in_build === true ? ' ✓' : ''));
            k.style.cssText = 'font-size:11px;color:var(--muted);flex-shrink:0;';
            row.appendChild(n); row.appendChild(p); row.appendChild(k);
            const go = () => {
              _closeSym();
              _jumpOpen(ed, it.path, { line: Math.max(1, it.line || 1) });
            };
            row.onclick = go;
            list.appendChild(row);
          });
        } catch (_) {}
      }, 220);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); _closeSym(); }
      if (e.key === 'Enter') {
        const first = list.querySelector('.nav-sym-row');
        if (first) first.click();
      }
    });
  }

  // a383（VSCode Ctrl+Shift+O）：文件内符号速跳——当前文件大纲，空查询给
  // 全量（按行号排），输入即过滤，点击/回车跳行
  function showFileSymbols(ed) {
    _closeCands();
    _closeSym();
    const ov = document.createElement('div');
    ov.id = 'navSymPanel';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.25);z-index:9999;display:flex;align-items:flex-start;justify-content:center;padding-top:10vh;';
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) _closeSym(); });
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:560px;max-width:92vw;max-height:62vh;display:flex;flex-direction:column;padding:12px 14px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.4);';
    const input = document.createElement('input');
    input.className = 'dd-input';
    input.placeholder = '文件内符号（函数/类/成员，输入过滤；回车跳首项）…';
    input.style.cssText = 'width:100%;box-sizing:border-box;';
    card.appendChild(input);
    const list = document.createElement('div');
    list.style.cssText = 'margin-top:8px;overflow:auto;flex:1;';
    card.appendChild(list);
    ov.appendChild(card);
    document.body.appendChild(ov);
    input.focus();
    const file = ed && ed.getModel() ? modelFilePath(ed.getModel()) : '';
    let all = [];
    let selIdx = 0;
    const render = () => {
      list.innerHTML = '';
      const rows = [];
      all.forEach(function (it, idx) {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:10px;align-items:center;padding:4px 8px;border-radius:6px;cursor:pointer;' +
          (idx === selIdx ? 'background:var(--border);' : '');
        const k = _h('span', (it.kind || '?'));
        k.style.cssText = 'font-size:10.5px;color:var(--accent);flex-shrink:0;min-width:64px;';
        const n = _h('span', it.name);
        n.style.cssText = 'font-family:var(--font-mono);font-size:12.5px;font-weight:600;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;';
        const ln = _h('span', ':' + (it.line || 1));
        ln.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--muted);flex-shrink:0;';
        row.appendChild(k); row.appendChild(n); row.appendChild(ln);
        row.onclick = () => { _closeSym(); _jumpOpen(ed, it.path, { line: Math.max(1, it.line || 1), col: 1, selectLine: true }); };
        list.appendChild(row);
        rows.push(row);
      });
      if (rows[selIdx]) try { rows[selIdx].scrollIntoView({ block: 'nearest' }); } catch (_) {}
    };
    // 数据：一次拉全量（空 q），前端本地过滤（响应快）
    fetch('/api/nav/symbols?scope=file&file=' + encodeURIComponent(file) + '&q=')
      .then(r => r.json()).then(j => {
        if (!j.ok || !j.items) {
          const d = _h('div', j.err === 'no-index' ? '该文件不在索引库内（先在文件树右键建索引）' : '无符号');
          d.style.cssText = 'color:var(--muted);font-size:12px;padding:8px;';
          list.appendChild(d);
          return;
        }
        // S-B4（P3）：resolve 前用户已输入的过滤词被全量覆盖——渲染统一走
        // 过滤通道（与 input handler 同口径）
        _full = j.items;
        const q = input.value.trim().toLowerCase();
        all = q ? _full.filter(it => it.name.toLowerCase().includes(q)) : _full;
        selIdx = 0;
        render();
      }).catch(() => {});
    // R33-1（实锤：每键打后端，110MB 库每发 0.5-2.2s）：首拉已取全量
    // （limit 500），输入改为本地过滤（与注释本意一致）——0 后端流量
    let _full = [];
    input.addEventListener('input', function () {
      if (_symTimer) clearTimeout(_symTimer);
      _symTimer = setTimeout(() => {
        const q = input.value.trim().toLowerCase();
        selIdx = 0;
        all = q ? _full.filter(it => it.name.toLowerCase().includes(q)) : _full;
        render();
      }, 160);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); _closeSym(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); selIdx = Math.min(all.length - 1, selIdx + 1); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); selIdx = Math.max(0, selIdx - 1); render(); }
      else if (e.key === 'Enter' && all[selIdx]) {
        e.preventDefault();
        const it = all[selIdx];
        _closeSym();
        _jumpOpen(ed, it.path, { line: Math.max(1, it.line || 1), col: 1, selectLine: true });
      }
    });
  }

  function _closeSym() {
    if (_symTimer) { clearTimeout(_symTimer); _symTimer = null; }
    const el = document.getElementById('navSymPanel');
    if (el) el.remove();
  }

  // ---- 引用查找（Shift+F12，批3）----
  async function findReferences(ed) {
    let model = null, pos = null;
    try { model = ed.getModel(); pos = ed.getPosition(); } catch (_) { return; }
    if (!model || !pos) return;
    const word = monacoWordAt(model, pos);
    if (!word || word.length < 2) return;
    const file = modelFilePath(model);
    if (!/^[A-Za-z]:/.test(file)) return;
    let j = null;
    try {
      const r = await fetch('/api/nav/references?file=' + encodeURIComponent(file) +
                            '&symbol=' + encodeURIComponent(word));
      j = await r.json();
    } catch (e) { showBanner('引用查询失败: ' + e, 3000, true); return; }
    _closeCands();
    const ov = document.createElement('div');
    ov.id = 'navCandsPanel';   // 复用候选面板关闭链
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.25);z-index:9999;display:flex;align-items:flex-start;justify-content:center;padding-top:10vh;';
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) _closeCands(); });
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:720px;max-width:94vw;max-height:64vh;overflow:auto;padding:14px 16px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.4);';
    const title = _h('div', '「' + word + '」的引用 ' + ((j.items && j.items.length) || 0) + ' 处（定义行已排除）'
      + (j.truncated ? ' · 结果超 200 条已截断' : ''));
    title.style.cssText = 'font-weight:600;margin-bottom:8px;';
    card.appendChild(title);
    if (!j.ok || !j.items || !j.items.length) {
      // R16-9：err 透出。R17-6（实锤：no-index 文案死分支）：no-index 时
      // j.ok=False——分支顺序先判 err 值再判 ok
      const d = _h('div', j.err === 'no-index' ? '该文件不在索引库内' :
                         (!j.ok ? ('查询失败：' + (j.err || '')) : '无引用命中'));
      d.style.cssText = 'color:var(--muted);padding:8px;';
      card.appendChild(d);
    }
    (j.items || []).forEach(function (it) {
      const row = document.createElement('div');
      row.className = 'nav-ref-row';
      row.style.cssText = 'display:flex;gap:10px;align-items:center;padding:5px 8px;border-radius:6px;cursor:pointer;';
      row.onmouseenter = function () { row.style.background = 'var(--border)'; };
      row.onmouseleave = function () { row.style.background = ''; };
      const b = _h('span', it.in_build === true ? '✓' : (it.in_build === false ? '✗' : '~'));
      b.style.cssText = 'font-size:11px;flex-shrink:0;color:' +
        (it.in_build === true ? 'var(--accent)' : 'var(--muted)');
      // 用户实锤（行号截断）：路径+行号全显示优先于摘要——两行布局，
      // 第一行完整路径:行号（可断行），第二行摘要
      const locBox = document.createElement('div');
      locBox.style.cssText = 'flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;';
      const loc = _h('span', it.rel + ' :' + it.line);
      loc.style.cssText = 'font-family:var(--font-mono);font-size:11.5px;word-break:break-all;white-space:normal;line-height:1.35;';
      const sn = _h('span', it.snippet || '');
      sn.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      locBox.appendChild(loc); locBox.appendChild(sn);
      row.appendChild(b); row.appendChild(locBox);
      row.onclick = function () {
        _closeCands();
        // 用户实锤（跳转无高亮看不见）：openFileSmart 只定位不选中——
        // 定位后把目标行整行选中高亮（VSCode 跳转同款即时可见）
        _jumpOpen(ed, it.path, { line: it.line, col: 1, selectLine: true });
      };
      card.appendChild(row);
    });
    ov.appendChild(card);
    document.body.appendChild(ov);
  }

  // rel → 绝对路径（后端 items 已含绝对 path 字段）

  async function provideDefinition(model, position) {
    // R15-1：不再走 Monaco 原生 uri 跳转（standalone 无内容服务，空白）。
    // 保留注册只为占用 F12 原生行为，真实跳转由 addCommand 自定义链完成
    void model; void position;
    return null;
  }

  // ---- 可配置键位（a346）：默认 F12 / Shift+F12 / Ctrl+T，设置页可改 ----
  const NAV_KEYS = { def: 'f12', ref: 'shift+f12', sym: 'ctrl+t',
                     fsym: 'ctrl+shift+o',   // a383：文件内符号（VSCode Ctrl+Shift+O）
                     back: 'alt+arrowleft', fwd: 'alt+arrowright' };

  function loadNavKeys() {
    fetch('/api/theme').then(r => r.json()).then(j => {
      if (j && j.nav_keys && j.nav_keys.def) {
        applyKeys(j.nav_keys);
      }
    }).catch(() => {});
  }

  function keyLabel(spec) {
    // a360R：方向键显示为箭头（Ctrl+ARROWLEFT 太丑，VSCode 也是画箭头）
    const ARROW = { arrowleft: '←', arrowright: '→',
                    arrowup: '↑', arrowdown: '↓' };
    return spec.split('+').map(p =>
      ({ ctrl: 'Ctrl', shift: 'Shift', alt: 'Alt', meta: 'Meta' }[p]
       || ARROW[p] || p.toUpperCase())).join('+');
  }

  function matchKey(e, spec) {
    // spec 形如 'ctrl+shift+f12'——末段主键（大小写不敏感），ctrl/meta 视
    // 为同一修饰键（Windows 无区分意义）；要求修饰键精确匹配（避免配了
    // F12 却被 Ctrl+F12 误触）
    const parts = spec.split('+');
    const main = parts[parts.length - 1].toLowerCase();
    const key = (e.key || '').toLowerCase();
    if (!key || key !== main) return false;
    const wantCtrl = parts.includes('ctrl') || parts.includes('meta');
    const wantShift = parts.includes('shift');
    const wantAlt = parts.includes('alt');
    const hasCtrl = !!(e.ctrlKey || e.metaKey);
    return hasCtrl === wantCtrl && e.shiftKey === wantShift && e.altKey === wantAlt;
  }

  // Monaco KeyCode 映射（addAction 右键菜单显示快捷键文本用）
  function monacoKeybinding(spec) {
    try {
      const parts = spec.split('+');
      const main = parts[parts.length - 1];
      let kb = 0;
      if (parts.includes('ctrl')) kb |= monaco.KeyMod.CtrlCmd;
      if (parts.includes('shift')) kb |= monaco.KeyMod.Shift;
      if (parts.includes('alt')) kb |= monaco.KeyMod.Alt;
      const KC = monaco.KeyCode;
      const map = { f1: KC.F1, f2: KC.F2, f3: KC.F3, f4: KC.F4, f5: KC.F5, f6: KC.F6,
                    f7: KC.F7, f8: KC.F8, f9: KC.F9, f10: KC.F10, f11: KC.F11, f12: KC.F12 };
      if (map[main] !== undefined) kb |= map[main];
      else if (main.length === 1) {
        const A = 'A'.charCodeAt(0), Z = 'Z'.charCodeAt(0), c = main.toUpperCase().charCodeAt(0);
        if (c >= A && c <= Z) kb |= monaco.KeyCode.KeyA + (c - A);
        else return null;
      } else return null;
      return kb;
    } catch (_) { return null; }
  }

  // 顶层等待 Monaco 就绪后注册（c/cpp/python/javascript）
  function bindEditor(ed) {
    // R15-1：Ctrl+Click 自定义跳转（standalone Monaco 原生 uri 链无内容
    // 服务——见 provideDefinition 注释）。R21-2（实锤：监听累积泄漏）：
    // bindEditor 会被 onDidCreateEditor/loadNavKeys/registerAll/applyKeys
    // 多路触发——单实例只绑一次，否则 Ctrl+Click 一次发 N 个并发请求
    if (!ed._navMouseBound) {
      ed._navMouseBound = true;
      try {
        ed.onMouseDown(function (e) {
          if (e.event.ctrlKey && e.target.position) {
            gotoDefinition(ed);
          }
        });
      } catch (_) {}
    }
    // a346：右键菜单三项（Monaco addAction 自动挂 contextMenu + 显示快捷键）。
    // R21-1（高，实锤：冷启动从未注册）：onDidCreateEditor 的 fire 发生在
    // 编辑器构造完成前——同步 addAction 静默无效（disposable 有、菜单无）。
    // defer 到下一拍注册（实测有效）；applyKeys 重挂走同函数天然复用
    try {
      if (ed._navActions) ed._navActions.forEach(a => { try { a.dispose(); } catch (_) {} });
      ed._navActions = [];
      const add = (id, label, spec, fn) => {
        const kb = monacoKeybinding(spec);
        const opts = { id: 'nav.' + id, label: label + '（' + keyLabel(spec) + '）',
                       contextMenuGroupId: 'navigation', contextMenuOrder: 1.1,
                       run: function (edt) { fn(edt); } };
        if (kb) opts.keybindings = [kb];
        const doAdd = () => {
          try { ed._navActions.push(ed.addAction(opts)); } catch (_) {}
        };
        setTimeout(doAdd, 0);
      };
      add('def', '转到定义', NAV_KEYS.def, gotoDefinition);
      add('ref', '查找所有引用', NAV_KEYS.ref, findReferences);
      add('sym', '工作区符号搜索', NAV_KEYS.sym, showWorkspaceSymbols);
      add('fsym', '文件内符号', NAV_KEYS.fsym, showFileSymbols);
    } catch (_) {}
  }

  // a383（VSCode Hover）：悬停看定义——kind 徽标+定义签名（3 行摘要）+
  // 路径:行号。词级缓存（60s）防高频悬停打爆后端
  const _hoverCache = new Map();
  function _hoverDef(file, word) {
    const key = file + '|' + word;
    const hit = _hoverCache.get(key);
    if (hit && Date.now() - hit.t < 60000) return Promise.resolve(hit.d);
    return fetch('/api/nav/definition?file=' + encodeURIComponent(file) +
                 '&symbol=' + encodeURIComponent(word))
      .then(r => r.json()).then(j => {
        const d = j && j.ok ? j : null;
        if (_hoverCache.size > 120) _hoverCache.clear();
        _hoverCache.set(key, { t: Date.now(), d });
        return d;
      }).catch(() => null);
  }
  function provideHover(model, position) {
    try {
      const word = model.getWordAtPosition(position);
      if (!word || !word.word || word.word.length < 2) return null;
      const file = modelFilePath(model);
      if (!/^[A-Za-z]:/.test(file)) return null;
      return _hoverDef(file, word.word).then(j => {
        if (!j || !j.candidates || !j.candidates.length) return null;
        const c = j.candidates[0];
        const md = { value: '' };
        md.value = ((_s) => {
          let _max = 3;
          for (const _m of _s.matchAll(/`+/g)) _max = Math.max(_max, _m[0].length);
          const _f = '`'.repeat(_max + 1);
          return '**' + word.word + '** `' + (c.kind || 'symbol') + '`' +
            (c.in_build === true ? ' ✓编译内' : '') + (c.file_local ? ' ·本文件' : '') + '\n\n' +
            _f + '\n' + _s + '\n' + _f + '\n\n' +
            '`' + c.rel + ' :' + c.line + '`';
        })(String(c.snippet || ''));
        return { range: new monaco.Range(position.lineNumber, word.startColumn,
                                         position.lineNumber, word.endColumn),
                 contents: [{ isTrusted: false }, md] };
      });
    } catch (_) { return null; }
  }

  function registerAll() {
    ['c', 'cpp', 'python', 'javascript'].forEach(function (lang) {
      try {
        monaco.languages.registerDefinitionProvider(lang, {
          provideDefinition: provideDefinition,
        });
        try {
          monaco.languages.registerHoverProvider(lang, {   // a383：悬停看定义
            provideHover: provideHover,
          });
        } catch (_) {}
      } catch (e) { /* 语言 ID 未注册（该版本 Monaco 无此语言）——跳过 */ }
    });
    try {
      monaco.editor.onDidCreateEditor(bindEditor);
      (monaco.editor.getEditors() || []).forEach(bindEditor);   // 已存在实例
    } catch (_) {}
  }

  // a346：热应用（设置页保存后调用；重挂各编辑器的右键 action 文案）
  function applyKeys(cfg) {
    ['def', 'ref', 'sym', 'fsym', 'back', 'fwd'].forEach(k => {
      if (cfg[k]) NAV_KEYS[k] = String(cfg[k]);
    });
    try {
      (monaco.editor.getEditors() || []).forEach(bindEditor);
    } catch (_) {}
  }

  // 全局键位（capture 拦截——F12 原生开发者工具键、Ctrl+T 原生新标签页
  // 都被占位；键位来自 NAV_KEYS 可配置）
  function bindGlobalKeys() {
    document.addEventListener('keydown', function (e) {
      // R16-5：候选/引用/符号三面板统一 Esc 关闭（面板 DOM 非焦点，
      // input 级监听盖不全——document capture 兜底）
      if (e.key === 'Escape') {
        let closed = false;
        if (document.getElementById('navCandsPanel')) { _closeCands(); closed = true; }
        if (document.getElementById('navSymPanel')) { _closeSym(); closed = true; }
        if (closed) {
          e.preventDefault();
          e.stopPropagation();
          // R17-7（实锤：Esc 不还焦点）：面板关闭后把焦点还给可见编辑器，
          // 否则后续 F12/Shift+F12 因 hasTextFocus 落空完全哑火
          try {
            const ed2 = monaco.editor.getEditors().find(function (x) {
              return x.getDomNode() && x.getDomNode().offsetParent;
            });
            if (ed2) ed2.focus();
          } catch (_) {}
        }
        return;
      }
      const ed = window.monaco && monaco.editor && monaco.editor.getEditors
        ? monaco.editor.getEditors().find(function (x) {
            try { return x.hasTextFocus(); } catch (_) { return false; }
          })
        : null;
      if (ed && matchKey(e, NAV_KEYS.def)) {
        e.preventDefault(); e.stopPropagation(); gotoDefinition(ed); return;
      }
      if (ed && matchKey(e, NAV_KEYS.ref)) {
        e.preventDefault(); e.stopPropagation(); findReferences(ed); return;
      }
      if (ed && matchKey(e, NAV_KEYS.sym)) {
        e.preventDefault(); e.stopPropagation(); showWorkspaceSymbols(ed);
        return;
      }
      if (ed && matchKey(e, NAV_KEYS.fsym)) {   // a383：Ctrl+Shift+O 文件内符号
        e.preventDefault(); e.stopPropagation(); showFileSymbols(ed);
      }
      // a360R（用户需求2）：导航历史 back / forward。
      // a375R（第1轮审计 P2-4/P1-1）：接管范围要精确——不能一律放行，也不能
      // 一律抢。四个方向的真实归属：
      //   · Monaco 编辑器内：接管（VSCode 同款；Alt+←/→ 在 Windows Monaco 里
      //     没有默认绑定，不冲突）
      //   · xterm 终端内：**放行**——bash/readline 的 Alt+←/→ 是「按词移动
      //     光标」，抢了会破坏终端输入
      //   · 普通 input/textarea：放行（浏览器原生光标移动）
      //   · 其他（页面空白、树、面板）：接管，这样焦点不在编辑器时也能返回
      if (matchKey(e, NAV_KEYS.back) || matchKey(e, NAV_KEYS.fwd)) {
        const t = e.target;
        const tag = t && t.tagName ? t.tagName.toLowerCase() : '';
        const inMonaco = !!(t && t.closest && t.closest('.monaco-editor'));
        const inXterm = !!(t && t.closest && t.closest('.xterm'));
        const inPlainInput = !inMonaco && !inXterm &&
          (tag === 'input' || tag === 'textarea');
        if (!inXterm && !inPlainInput) {
          e.preventDefault(); e.stopPropagation();
          if (matchKey(e, NAV_KEYS.back)) navigateBack();
          else navigateForward();
          return;
        }
      }
    }, true);
  }

  function boot() {
    bindGlobalKeys();
    loadNavKeys();   // a346：配置键位（加载后热应用）
    if (typeof monacoInit !== 'function') return;
    monacoInit().then(registerAll).catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // ---------------------------------------------------------------- 索引管理弹层
  // 文件树右键「代码索引…」的唯一 UI（手动触发铁律）：弹层内先探测再给
  // 操作——无代码（无按钮）/ 可建（预估+建立）/ 已建（信息+重建+删除）
  function fmtSize(b) {
    if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB';
    if (b >= 1024) return (b / 1024).toFixed(0) + ' KB';
    return b + ' B';
  }

  let _pollTimer = null;

  function ui(path) {
    _closePanel();
    const ov = document.createElement('div');
    ov.id = 'navIdxPanel';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.32);z-index:9999;display:flex;align-items:center;justify-content:center;';
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) _closePanel(); });
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:520px;max-width:92vw;padding:18px 20px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.4);';
    ov.appendChild(card);
    document.body.appendChild(ov);
    _renderProbe(card, path);
  }

  function _closePanel() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    const el = document.getElementById('navIdxPanel');
    if (el) el.remove();
  }

  function _h(tag, txt, html) {
    // a373（用户铁律：UI 禁 emoji）：html=true 时可插 ICO16 SVG 图标串
    const e = document.createElement(tag);
    if (txt !== undefined) { if (html) e.innerHTML = txt; else e.textContent = txt; }
    return e;
  }

  async function _renderProbe(card, path) {
    card.innerHTML = '';
    card.appendChild(_h('div', '代码跳转索引'));
    const st = _h('div', '探测中…（浅层扫描）');
    st.style.cssText = 'margin-top:10px;font-size:12.5px;color:var(--muted);';
    card.appendChild(st);
    const sub = _h('div', path);
    sub.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--muted);margin-top:4px;word-break:break-all;';
    card.appendChild(sub);
    const btns = _h('div');
    btns.style.cssText = 'margin-top:14px;display:flex;gap:8px;justify-content:flex-end;';
    const closeB = _h('button', '关闭');
    closeB.className = 'btn ghost';
    closeB.onclick = _closePanel;
    btns.appendChild(closeB);
    card.appendChild(btns);
    let j = null;
    try {
      const r = await fetch('/api/nav/status?root=' + encodeURIComponent(path));
      j = await r.json();
    } catch (e) { j = { ok: false, err: String(e) }; }
    if (!document.getElementById('navIdxPanel')) return;   // 已关
    _renderState(card, path, j, st);
  }

  async function _renderState(card, path, j, st) {
    const btns = card.querySelector('div:last-child');
    if (!j || !j.ok) {
      st.textContent = '探测失败：' + ((j && j.err) || '网络错误');
      return;
    }
    const bAdd = _h('button', ICO16.search + ' 建立索引', true);
    bAdd.className = 'btn primary';
    bAdd.onclick = () => _startBuild(card, path);
    // R15-5（实锤：弹层死角）：indexed 判定必须在 has_code 之前——代码被
    // 移走（探测不到）但库还在时，仍要给已建态（重建/删除可达）
    if (!j.indexed) {
      if (!j.has_code) {
        st.textContent = '未发现代码文件（C/C++/py/js 等）——该目录不需要索引';
        st.style.color = 'var(--neon-red,#e5484d)';
        // R27-3（实锤：未建 ctags 时 codegraph 整体不可见）：两套索引独立
        // ——ctags 不需要 ≠ codegraph 不需要（claude 代码图有自己的价值）
        _renderCodegraph(st, path, btns);
        return;   // ctags 无按钮：不盲目；codegraph 区块自行决定
      }
      st.textContent = '✓ 发现代码文件（浅层抽样 ' + (j.probe_files || 0) + ' 个）。'
        + '首次索引需扫描全目录——网盘挂载的大库可能数分钟，结果存工具数据目录（不写工程目录）。';
      btns.insertBefore(bAdd, btns.lastChild);
      _renderCodegraph(st, path, btns);   // R27-3：两套独立，都要可见
      return;
    }
    const m = j.meta || {};
    st.innerHTML = '';
    const ok1 = _h('div', '✓ 索引已建立（' + (m.built_at || '') + '）');
    ok1.style.cssText = 'color:var(--accent);font-weight:600;';
    st.appendChild(ok1);
    st.appendChild(_h('div',
      '符号 ' + (m.code_files || 0) + ' · 编译白名单 ' + (m.cmd_count || 0) + ' .cmd / '
      + (m.o_count || 0) + ' .o' + (m.symbols ? ' · ELF 符号 ' + m.symbols : '')
      + ' · 占用 ' + fmtSize(m.size || 0) + '（存储感知可见）'));
    if (m.root_reachable === false) {
      const warn = _h('div', '索引对应的工程路径当前不可达（换盘/移动了？）——跳转可能失效，可重建');
      warn.style.color = '#e8a33d';
      st.appendChild(warn);
    }
    if (j.stale) {   // 批3：粗粒度过期提示（浅层 .cmd 命中 vs 建库记录）
      const warn2 = _h('div', '工程构建产物有变化（新编译/换树）——建议重建索引以刷新白名单');
      warn2.style.color = '#e8a33d';
      st.appendChild(warn2);
    }
    const bRe = _h('button', ICO16.refresh + ' 重建', true);
    bRe.className = 'btn primary';
    // 用户实锤：重建按钮不传 backend——想建 sqlite 却走 auto 全部重建。
    // 改为传下拉当前值（重建尊重用户选的档位）
    bRe.onclick = () => _startBuild(card, path, bkSel.value);
    // a390：查询后端三档切换（重建按钮左侧下拉；sqlite 走任务槽带进度）
    // 用户实锤：白色底——加 lv-btn 类统一深色主题
    const bkSel = _h('select');
    bkSel.className = 'lv-btn';
    bkSel.title = '查询后端：内存全量（小库最快·占内存）/ readtags（零建库·约0.2s/次）/ sqlite（大库·0~4ms·低内存）';
    bkSel.style.cssText = 'padding:2px 6px;font-size:11px;margin-left:6px;';
    const _curBk = m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory');
    bkSel.innerHTML = [['memory', '内存全量'], ['readtags', 'readtags'], ['sqlite', 'sqlite']]
      .map(([v, n2]) => `<option value="${v}"${_curBk === v ? ' selected' : ''}>${n2}</option>`).join('');
    bkSel.onchange = async () => {
      const v = bkSel.value;
      if (typeof _ddConfirm === 'function' &&
          !(await _ddConfirm('切换查询模式', v === 'sqlite'
            ? '构建 sqlite 快查索引（大库约 1 分钟，一次性；查询 0~4ms/内存 ~50MB）？'
            : `切到 ${v} 模式（删除 tags.db 立即生效）？`))) {
        // C-2+S-B1：①_renderState 二次调用命中死节点（btns 捕获 div:last-child
        // 落进 st 内部行）——改直接复位下拉；②弹窗 z=200 被面板 z=9999 遮挡
        // （见 P-5b 的 CSS 补丁），此处只需复位显示态
        bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));
        return;
      }
      try {
        const r = await fetch('/api/nav/reindex', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: path, backend: v }) });
        const d2 = await r.json();
        if (d2.ok) m.backend = v;   // R4-F1：第 4 失步出口——前瞻同步显示态。
                                    // 切档无 poll 轮询（/api/nav/poll 仅建索
                                    // 引流消费）；任务异步失败由索引面板重开
                                    // （按 meta 渲染）兜底显示回归
        showBanner(d2.ok ? '查询模式切换中（任务槽执行）' : ('切换失败：' + (d2.err || '')), 3000, !d2.ok);
        if (!d2.ok) bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));   // R3-3：:883 出口
      } catch (e) { showBanner('切换失败: ' + e, 3000, true);
        bkSel.value = ((m.backend || (m.code_files >= 200000 ? 'sqlite' : 'memory')));   // R3-3：:884 catch 出口
      }
    };
    btns.insertBefore(bkSel, btns.lastChild);
    const bDel = _h('button', ICO16.trash + ' 删除索引', true);
    bDel.className = 'btn ghost';
    bDel.style.color = '#e5484d';
    bDel.onclick = async () => {
      if (typeof _ddConfirm === 'function' && !(await _ddConfirm('删除索引', '删除该目录的跳转索引（' + fmtSize(m.size || 0) + '）？工程文件不受影响。'))) return;
      try {
        const r = await fetch('/api/nav/delete', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: path }) });
        const d = await r.json();
        showBanner(d.ok ? '索引已删除' : ('删除失败：' + (d.err || '')), 3000, !d.ok);
      } catch (e) { showBanner('删除失败: ' + e, 3000, true); }
      _closePanel();
    };
    btns.insertBefore(bDel, btns.lastChild);
    // nm 清单导入按钮已删（用户实锤「说好全自动怎么还要导入」）：符号级
    // 消歧的主路是建库时 pyelftools 直读 .o——全自动；Linux 侧导清单的
    // 边缘场景不值得一个按钮（API 端点保留，需要时可程序化调用）
    btns.insertBefore(bRe, btns.lastChild);
    // ---- Claude 代码图（codegraph，喂 claude 会话；与上方 ctags 跳转索引独立）----
    _renderCodegraph(st, path, btns);
  }

  // a360：codegraph 区块——状态行 + 建/重建 + 增量同步 + 删除
  async function _renderCodegraph(st, path, btns) {
    let j = null;
    try {
      const r = await fetch('/api/nav/cg_status?root=' + encodeURIComponent(path));
      j = await r.json();
    } catch (_) { return; }   // codegraph 未装时后端给 ok:false——仍显示提示
    if (!document.getElementById('navIdxPanel')) return;
    const line = _h('div');
    line.style.cssText = 'margin-top:10px;padding-top:8px;border-top:1px dashed var(--border);font-size:12px;';
    const head = _h('span', ICO16.robot + ' Claude 代码图（codegraph）', true);
    head.style.cssText = 'font-weight:600;display:block;margin-bottom:4px;';
    line.appendChild(head);
    if (!j.ok) {
      const e = _h('div', (j.err || '不可用'));
      e.style.color = 'var(--muted)';
      line.appendChild(e);
      st.appendChild(line);
      return;
    }
    const info = _h('div');
    line.appendChild(info);
    const mkBtn = (label, cls) => {
      const b = _h('button', label, true);   // a373：label 可含 ICO16 SVG
      b.className = cls;
      b.style.cssText = 'padding:2px 10px;font-size:11px;margin-left:6px;';
      return b;
    };
    const paint = (d) => {
      info.innerHTML = '';
      if (d.installed) {
        info.appendChild(_h('span', '✓ %d 文件 · %d 节点 · %d 边 · %.1fMB（claude 会话可直接查询）'
          .replace('%d', d.files).replace('%d', d.nodes).replace('%d', d.edges).replace('%.1f', d.db_mb)));
      } else {
        info.appendChild(_h('span', '未建索引——建后 claude 会话可函数级查询该工程代码'));
      }
    };
    paint(j);
    const bBuild = mkBtn(j.installed ? (ICO16.refresh + ' 重建') : (ICO16.search + ' 建立'), 'btn primary');
    bBuild.onclick = () => _cgRun(path, 'build');
    const bSync = mkBtn(ICO16.refresh + ' 增量同步', 'btn ghost');
    bSync.style.display = j.installed ? '' : 'none';
    bSync.title = '代码大改后秒级增量';
    bSync.onclick = () => _cgRun(path, 'sync');
    const bDel = mkBtn(ICO16.trash + ' 删除', 'btn ghost');
    bDel.style.cssText += 'color:#e5484d;';
    bDel.style.display = j.installed ? '' : 'none';
    bDel.onclick = async () => {
      if (typeof _ddConfirm === 'function' &&
          !(await _ddConfirm('删除代码图索引', '删除 <工程>/.codegraph/（claude 查询能力随之消失，可重建）？'))) return;
      try {
        const d = await (await fetch('/api/nav/cg_delete', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: path }) })).json();
        showBanner(d.ok ? '已删除' : ('失败：' + (d.err || d.msg)), 3000, !d.ok);
      } catch (e) { showBanner('失败: ' + e, 3000, true); }
      _closePanel();
    };
    line.appendChild(bBuild); line.appendChild(bSync); line.appendChild(bDel);
    st.appendChild(line);
  }

  function _cgRun(path, mode) {
    fetch('/api/nav/cg_build', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: path, mode }) })
      .then(r => r.json())
      .then(j => {
        if (!j.ok) { showBanner('启动失败：' + (j.err || ''), 4000, true); return; }
        // R26-2（实锤：codegraph 任务 UI 零反馈）：真开进度面板——与
        // ctags 建库同款（轮询同通道，日志/进度/取消/完成通知全有）
        const panel = document.getElementById('navIdxPanel');
        const card = panel && panel.firstChild;
        if (card) _renderProgress(card, path);
      })
      .catch(e => showBanner('启动失败: ' + e, 4000, true));
  }

  function _startBuild(card, path, backend) {
    // 用户实锤：重建按钮不传 backend → 后端走 auto → 想建 sqlite 却走
    // 全部重建流程。改为传下拉当前值（重建尊重用户选的档位）
    const body = backend ? { root: path, backend: backend } : { root: path };
    fetch('/api/nav/build', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) })
      .then(r => r.json())
      .then(j => {
        if (!j.ok) { showBanner('启动失败：' + (j.err || ''), 4000, true); return; }
        _renderProgress(card, path);
      })
      .catch(e => showBanner('启动失败: ' + e, 4000, true));
  }

  function _renderProgress(card, path) {
    card.innerHTML = '';
    card.appendChild(_h('div', '正在建立索引'));
    card.appendChild(_h('div', path)).style.cssText =
      'font-family:var(--font-mono);font-size:11px;color:var(--muted);margin-top:4px;word-break:break-all;';
    const barBox = _h('div');
    barBox.style.cssText = 'margin-top:12px;height:6px;background:var(--border);border-radius:3px;overflow:hidden;';
    const bar = _h('div');
    bar.style.cssText = 'height:100%;width:0;background:var(--accent);transition:width .3s;';
    barBox.appendChild(bar);
    card.appendChild(barBox);
    const txt = _h('div', '准备…');
    txt.style.cssText = 'margin-top:6px;font-size:12px;color:var(--muted);';
    card.appendChild(txt);
    const log = _h('div');
    log.style.cssText = 'margin-top:8px;max-height:150px;overflow:auto;font-size:11px;font-family:var(--font-mono);white-space:pre-wrap;color:var(--muted);';
    card.appendChild(log);
    const btns = _h('div');
    btns.style.cssText = 'margin-top:12px;display:flex;gap:8px;justify-content:flex-end;';
    const bCancel = _h('button', '取消');
    bCancel.className = 'btn ghost';
    bCancel.onclick = () => fetch('/api/nav/cancel', { method: 'POST' });
    btns.appendChild(bCancel);
    card.appendChild(btns);
    let seen = 0;
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(async () => {
      try {
        const r = await fetch('/api/nav/poll');
        const s = await r.json();
        bar.style.width = (s.percent || 0) + '%';
        txt.textContent = (s.phase || '') + ' · ' + (s.percent || 0) + '%' + (s.cancelling ? ' · 正在取消…' : '');
        const lg = s.log || [];
        for (; seen < lg.length && seen < 200; seen++) {
          const d = _h('div', lg[seen].msg);
          log.appendChild(d);
        }
        log.scrollTop = log.scrollHeight;
        if (!s.done) return;
        clearInterval(_pollTimer); _pollTimer = null;
        if (s.ok_done) {
          // R27-2（实锤：codegraph 任务完成恒"0 符号"）：result 按 kind 分流——
          // ctags 用 code_files（符号数），codegraph 用 files（文件数）
          const res = s.result || {};
          const doneTxt = res.kind === 'codegraph'
            ? '✓ 完成：' + (res.files || 0) + ' 文件'
            : '✓ 完成：' + (res.code_files || 0) + ' 符号';
          txt.textContent = doneTxt;
          showBanner('代码索引建立完成', 3000);
          bCancel.textContent = '关闭';
          bCancel.onclick = _closePanel;
        } else {
          txt.textContent = (s.cancelled ? '已取消' : '失败：' + (s.err || ''));
          bCancel.textContent = '关闭';
          bCancel.onclick = _closePanel;
        }
      } catch (e) { /* 轮询失败继续 */ }
    }, 800);
  }

  // 供 file-tree.js 右键入口 + editor 检测复用 + 设置页热应用
  window.NavJump = { registerAll: registerAll, ui: ui, applyKeys: applyKeys,
                     getKeys: () => ({ ...NAV_KEYS }), keyLabel: keyLabel,
                     // a360R：导航历史（设置页/右键菜单可直接触发）
                     goBack: navigateBack, goForward: navigateForward };
})();
