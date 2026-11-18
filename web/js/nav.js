// a333 批1：代码跳转（ctags 索引 + 编译白名单 + ELF 符号表）
// R15-1 实锤修正：standalone Monaco 对未知 uri 没有内容服务——provider
// 返回 uri 只会得到空白/无反应。改自定义跳转：Ctrl+Click/F12 → 查询 →
// 唯一可信候选 openFileSmart 直跳；多候选弹带徽标的候选面板（原批 2
// 提前落地）。provider 注册保留但恒返回 null（防 Monaco 原生空跳干扰）。
// 模块化一期（js-modularization 分支）：已转 ES module——IIFE 壳已剥。
// 对外表面仅 window.NavJump（settings.js:170 window 守卫 + tree-fileops
// 菜单 action，均为运行时调用）。
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
  // a336（用户需求2，VSCode 同款）：导航历史 back / forward
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
  // a336（关键）：**目标和来源都要进栈**。只压来源的话，第一次跳转后栈里
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
    // a428（内网报告 问题5）：局部变量降级提示——ctags 不索引函数内局部
    // 变量，全是同名 struct member 时不自动跳（原跳到无关头文件误导）
    if (j.mode === 'ambiguous-local') {
      showBanner((j.err || '可能为函数内局部变量') + '——已弹候选列表', 3500);
      _showCandidates(j, editor);
      return;
    }
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
    // a336：方向键显示为箭头（Ctrl+ARROWLEFT 太丑，VSCode 也是画箭头）
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
      // a336（用户需求2）：导航历史 back / forward。
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
  let _navClockTimer = null;   // a426：独立计时器

  function ui(path) {
    // a452：切换目录查看 ≠ 放弃正在等选择的任务，只收面板不取消建库
    _closePanel(false);
    const ov = document.createElement('div');
    ov.id = 'navIdxPanel';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.32);z-index:9999;display:flex;align-items:center;justify-content:center;';
    // a392（用户实锤：点一下背景进度就没了，任务还在跑却看不到过程）：
    // 任务运行中禁背景关闭（资源安装弹窗同款①；✕/关闭仍可关——重开有恢复式显示②兜底）
    ov.addEventListener('mousedown', function (e) {
      if (e.target !== ov) return;
      if (ov.dataset.running === '1') return;
      _closePanel();
    });
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:520px;max-width:92vw;padding:18px 20px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.4);';
    ov.appendChild(card);
    document.body.appendChild(ov);
    _renderProbe(card, path);
  }

  // a452（审计 P2）：_closePanel 的「弹窗还在 ⇒ 关面板即放弃建库」语义只
  // 适用于**用户真的关闭**。ui()（右键另一个目录）也走 _closePanel，会把
  // 正在等用户选建库方式的任务静默取消——用户只觉得换了个目录，任务没了。
  // 加 cancelIfAsking 参数：切面板传 false，只收弹窗不动任务。
  function _closePanel(cancelIfAsking) {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_navClockTimer) { clearInterval(_navClockTimer); _navClockTimer = null; }
    const _td = document.getElementById('navTierDialog');
    if (_td) {
      // a456（第三轮审计 P2）：删弹窗也要受 cancelIfAsking 约束。原来
      // `_td.remove()` 无条件执行、只把 POST /cancel 挡在外面——切换目录
      // 时弹窗被摘掉、任务却还在后端等作答，用户再无任何作答入口，10 分钟
      // 后按 full 继续，收录方式选择静默丢失。切换目录时把弹窗留着。
      if (cancelIfAsking !== false) {
        _td.remove();
        // 弹窗还在说明建库线程正卡在「等用户选建库方式」。真正的关闭动作下
        // 用户再没有任何途径作答，后端会白等 10 分钟——视为放弃建库。
        fetch('/api/nav/cancel', { method: 'POST' }).catch(() => {});
      }
    }
    const el = document.getElementById('navIdxPanel');
    if (el) el.remove();
  }

  function _h(tag, txt, html) {
    // a344（用户铁律：UI 禁 emoji）：html=true 时可插 ICO16 SVG 图标串
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
    // a392 恢复式显示（资源安装同款②）：先查任务槽（零扫描即时）——本目录
    // 任务还在跑就直接恢复进度视图；误关/关完重开都能接上过程
    try {
      const pr = await fetch('/api/nav/poll');
      const ps = await pr.json();
      if (!document.getElementById('navIdxPanel')) return;   // 已关
      if (ps && ps.running && ps.root === path) {
        _renderProgress(card, path);
        return;
      }
    } catch (_) {}
    try {
      const r = await fetch('/api/nav/status?root=' + encodeURIComponent(path));
      j = await r.json();
    } catch (e) { j = { ok: false, err: String(e) }; }
    if (!document.getElementById('navIdxPanel')) return;   // 已关
    _renderState(card, path, j, st);
  }

  // a393（用户令：建库就要能选后端+全量方案下线）：档位下拉公共构造——
  // 只剩 readtags/sqlite 两方案；sqlite 无能力（旧 exe 缺件）藏项；
  // withAuto 给首次建库多一个『自动』档（按库大小自动判）；旧库 meta
  // backend=memory 显示兜底 readtags
  function _bkSel(cur, sqlOk, withAuto) {
    if (cur === 'memory') cur = 'readtags';
    const sel = _h('select');
    sel.className = 'lv-btn';
    sel.title = '查询后端：readtags（零建库·约0.2s/次）/ sqlite（大库·0~4ms·低内存）';
    sel.style.cssText = 'padding:2px 6px;font-size:11px;margin-left:6px;';
    const opts = (withAuto ? [['auto', '自动']] : [])
      .concat([['readtags', 'readtags'], ['sqlite', 'sqlite']])
      .filter(o => o[0] !== 'sqlite' || sqlOk);
    if (!opts.some(o => o[0] === cur)) cur = 'readtags';
    sel.innerHTML = opts.map(([v, n2]) =>
      `<option value="${v}"${cur === v ? ' selected' : ''}>${n2}</option>`).join('');
    return sel;
  }

  // a398（内网报告档B + 用户令：手动指定目录多选 UI 要做好、支持子目录）：
  // 收录范围行——检测到的配置展示 + 档位下拉 + 导入 JSON + 目录树多选。
  // 返回 div；当前选择经 card._scopeSel 闭包交给 _startBuild
  // a398（内网报告档B + 用户令：手动指定目录多选 UI 要做好、支持子目录）：
  // 收录范围行——检测到的配置展示 + 档位下拉 + 导入 JSON + 目录树多选 +
  // 清除已存。a398 审计#1（P0 XSS）：配置名一律 textContent，绝不拼
  // innerHTML；#9：下拉活性——载荷每次按下拉现值组装，导入/手选挂
  // card._scopeCfg 供 'cfg' 档引用；#10：全量档=显式整根 scope
  function _scopeRow(card, path, j) {
    const box = _h('div');
    box.style.cssText = 'margin-top:8px;padding:8px 10px;border:1px dashed var(--border);border-radius:8px;font-size:12px;';
    const sc = j.scope || null;
    const head = _h('div');
    head.style.cssText = 'margin-bottom:6px;';
    const _headTxt = (t) => { head.textContent = t; };
    const _headCfg = (cfg, srcLabel) => {
      head.textContent = '';
      head.append('收录范围：');
      const b = _h('b', cfg.name || '未命名范围');
      head.appendChild(b);
      head.append('（' + (cfg.tier || '') + '）——' + srcLabel +
        ((cfg.include && cfg.include.length) ? '，' + cfg.include.length + ' 目录' : ''));
    };
    if (sc && sc.source === 'project') {
      _headCfg(sc, '检测到工程配置 .fcpk-scope.json');
    } else if (sc && sc.source === 'saved') {
      _headCfg(sc, '上次保存的范围（换机不丢，删索引不影响）');
    } else if (sc && String(sc.source || '').startsWith('bad:')) {
      _headTxt('收录范围：配置解析失败（' + sc.source.slice(4) + '）——将按全量');
      head.style.color = 'var(--neon-red,#e5484d)';
    } else if (j.scope_detect && j.scope_detect.kind === 'sbuilder') {
      // a400/a402：零配置形态识别（用户定调：只显示检测到 sbuilder 方案，
      // 不写死平台模板）——产物树只读 .cmd/.o 不索引；档位按产物规模自动判
      _headTxt('检测到 sbuilder 方案（产物外挂 sbuilder/output/build，只读产物不索引副本）——自动档按产物规模判白名单/全量；零产物目录如未收录可加 fallback_full');
    } else {
      _headTxt('收录范围：未配置——小工程自动全量；大工程建议导入 JSON 或手选目录（跳过 sbuilder/output 这类产物外挂树，实测快 8 倍）');
    }
    box.appendChild(head);
    const row = _h('div');
    row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;align-items:center;';
    const sel = _h('select');
    sel.className = 'lv-btn';
    sel.style.cssText = 'padding:2px 6px;font-size:11px;';
    sel.title = '收录范围档位';
    const OPTS = [
      ['follow', (sc && sc.source === 'project') ? '跟随工程配置' : (sc && sc.source === 'saved') ? '跟随已存范围' : '自动'],
      ['whitelist', (j.scope_detect && j.scope_detect.kind === 'sbuilder')
        ? '白名单（sbuilder 方案）' : '白名单'],
      // a409：白名单优先——全量档仅在收录集零中间文件时实际生效
      ['full', '全量（仅收录集零中间文件时生效）'],
    ];
    const renderSel = () => {
      const cfg = card._scopeCfg;
      sel.innerHTML = OPTS.concat(cfg ? [['cfg', '本次导入/手选']] : [])
        .map(([v, n2]) => '<option value="' + v + '"' + ((sel.value || 'follow') === v ? ' selected' : '') + '>' + n2 + '</option>').join('');
    };
    renderSel();
    row.appendChild(sel);
    // 导入 JSON（a398#9：导入只挂 cfg+切档，不锁死下拉）
    const bImp = _h('button', '导入 JSON', false);
    bImp.className = 'btn ghost';
    bImp.style.cssText = 'padding:2px 10px;font-size:11px;';
    const fi = document.createElement('input');
    fi.type = 'file'; fi.accept = '.json,application/json'; fi.style.display = 'none';
    bImp.onclick = () => fi.click();
    fi.onchange = () => {
      const f = fi.files && fi.files[0];
      fi.value = '';
      if (!f) return;
      f.text().then(t => {
        let cfg;
        try { cfg = JSON.parse(t); }
        catch (e) { showBanner('JSON 解析失败：' + e, 4000, true); return; }
        if (!cfg || !Array.isArray(cfg.include) || !cfg.include.length) {
          showBanner('配置缺 include 数组（内网报告 §五 格式）', 4000, true); return; }
        cfg.tier = cfg.tier === 'full' ? 'full' : 'whitelist';
        card._scopeCfg = cfg;
        renderSel();            // a415R2 N12：先建选项再赋值（原顺序下拉仍显示「自动」）
        sel.value = 'cfg';
        _headCfg(cfg, '导入的 JSON，建库成功后保存复用');
        showBanner('已载入范围配置：' + (cfg.name || '未命名') + '，点「建立索引」生效', 3500);
      }).catch(e => showBanner('读取失败: ' + e, 4000, true));
    };
    row.appendChild(bImp); row.appendChild(fi);
    // 目录树多选
    const bPick = _h('button', '选择目录…', false);
    bPick.className = 'btn ghost';
    bPick.style.cssText = 'padding:2px 10px;font-size:11px;';
    bPick.onclick = () => _scopePick(path, dirs => {
      if (!dirs || !dirs.length) return;
      // a409（内网报告·用户令「只要有白名单一定用白名单」）：手选目录
      // **不指定档位**（原写死 full=私自全建，实测 tags 撑到数百 MB）——
      // 后端按收录集有无中间文件判：有→白名单，零→全量（唯一降档）。
      // a415R3 BUG-2：勾「整个目录」根行时 dirs=[''] 映射成 '.'
      card._scopeCfg = { version: 1, name: '手选 ' + dirs.length + ' 目录',
        tier: 'auto', manual: true, include: dirs.map(d => d || '.'),
        exclude_names: ['test', 'release_tmp'] };
      renderSel();            // a415R2 N12：同上
      sel.value = 'cfg';
      _headTxt('收录范围：手选 ' + dirs.length + ' 目录（有中间文件只索引白名单，零中间文件才全量；自动排除 test/release_tmp）——' +
        dirs.slice(0, 4).join('、') + (dirs.length > 4 ? ' 等' : ''));
      showBanner('已选 ' + dirs.length + ' 个目录（整目录递归收录），点「建立索引」生效', 3500);
    });
    row.appendChild(bPick);
    // 清除已存范围（a398#10：有 saved 才显示）
    if (sc && sc.source === 'saved') {
      const bClr = _h('button', '清除已存范围', false);
      bClr.className = 'btn ghost';
      bClr.style.cssText = 'padding:2px 10px;font-size:11px;color:#e5484d;';
      bClr.onclick = async () => {
        try {
          const r = await fetch('/api/nav/build', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ root: path, scope_clear: true }) });
          const d2 = await r.json();
          if (d2.ok) {
            delete card._scopeCfg;
            renderSel();
            _headTxt('收录范围：未配置——小工程自动全量');
            showBanner('已清除保存的范围（回到自动/全量）', 3000);
          } else if (d2.err) showBanner('清除失败：' + d2.err, 3000, true);
        } catch (e) { showBanner('清除失败: ' + e, 3000, true); }
      };
      row.appendChild(bClr);
    }
    box.appendChild(row);
    // a398#9：载荷按下拉**现值**组装（导入/手选经 cfg 档引用，可随时切走/切回）
    card._scopeSel = () => {
      const cfg = card._scopeCfg || null;
      const v = sel.value || 'follow';
      if (v === 'cfg' && cfg) return { scope: cfg };
      if (v === 'full') return { scope: { version: 1, name: '全量', tier: 'full', include: ['.'] } };
      if (v === 'whitelist') {
        if (cfg) return { scope: Object.assign({}, cfg, { tier: 'whitelist' }) };
        return { scope_tier: 'whitelist' };   // 后端发现工程/已存配置并强制档
      }
      // follow：后端自动发现（工程>已存>全量）。a415R2 N12：导入/手选的
      // cfg 只经 'cfg' 档生效——切回 follow 即放弃本次导入
      return null;   // follow 且无导入：后端自动发现（工程>已存>全量）
    };
    return box;
  }

  // a398：目录树多选弹层——懒加载（SMB 大目录不整树拉）、勾父=子随父
  // 收录（继承态锁定）、最小顶集语义零歧义。
  // a398（审计#28）四修：顶层去重复渲染/折叠根隐藏子项/勾整根后子项
  // 继承锁定（inh!==null 判空串）/条目超限提示
  function _scopePick(root, cb) {
    const ov = document.createElement('div');
    ov.id = 'navScopePick';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:10001;display:flex;align-items:center;justify-content:center;';
    const card = _h('div');
    card.style.cssText = 'width:540px;max-width:94vw;padding:14px 16px;border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.45);';
    const t = _h('div', '选择收录目录');
    t.style.cssText = 'font-weight:600;margin-bottom:4px;';
    card.appendChild(t);
    const hint = _h('div', '有编译产物的目录按白名单精准收录（快且准）；零产物目录自动整目录兜底；低覆盖目录建库日志会提示。勾了父目录，子目录随父收录；要细化子目录，先取消父目录。自动排除 test/release_tmp。');
    hint.style.cssText = 'font-size:11px;color:var(--muted);margin-bottom:8px;';
    card.appendChild(hint);
    const tree = _h('div');
    tree.style.cssText = 'max-height:330px;overflow:auto;border:1px solid var(--border);border-radius:8px;padding:6px;font-size:12px;';
    card.appendChild(tree);
    const foot = _h('div');
    foot.style.cssText = 'margin-top:10px;display:flex;gap:8px;justify-content:flex-end;align-items:center;';
    const cnt = _h('span', '');
    cnt.style.cssText = 'margin-right:auto;font-size:11px;color:var(--muted);';
    foot.appendChild(cnt);
    const bClr = _h('button', '清空');
    bClr.className = 'btn ghost';
    const bCancel = _h('button', '取消');
    bCancel.className = 'btn ghost';
    const bOk = _h('button', '确定收录');
    bOk.className = 'btn primary';
    foot.appendChild(bClr); foot.appendChild(bCancel); foot.appendChild(bOk);
    card.appendChild(foot);
    ov.appendChild(card);
    ov.addEventListener('mousedown', e => { if (e.target === ov) ov.remove(); });
    document.body.appendChild(ov);
    const sel = new Set();        // 已勾目录 rel 集（''=整个根）
    const expanded = new Set();   // 已展开目录
    const kids = {};              // rel → {dirs:[], files:n, truncated}（懒加载缓存）
    const ancSel = d => {
      if (sel.has('')) return '';
      if (sel.has(d)) return d;
      const parts = d ? d.split('/') : [];
      for (let i = parts.length - 1; i > 0; i--) {
        const p = parts.slice(0, i).join('/');
        if (sel.has(p)) return p;
      }
      return null;
    };
    const syncCnt = () => {
      cnt.textContent = sel.size ? ('已选 ' + sel.size + ' 个目录' +
        (sel.has('') ? '（整个目录）' : '')) : '未选';
    };
    const render = () => {
      syncCnt();
      tree.innerHTML = '';
      const mkRow = (rel, name, sub, depth) => {
        const r = _h('div');
        r.style.cssText = 'display:flex;align-items:center;gap:4px;padding:1px 0 1px ' + (depth * 16) + 'px;';
        const chk = document.createElement('input');
        chk.type = 'checkbox';
        const inh = ancSel(rel);
        chk.checked = inh !== null;
        chk.disabled = inh !== null && !sel.has(rel);   // 继承态锁定（'' 也是合法 inh）
        chk.title = (inh !== null && !sel.has(rel))
          ? '随 ' + (inh || '整个目录') + ' 收录' : '';
        chk.onchange = () => {
          if (chk.checked) {
            // 最小顶集语义：勾父清后代；勾根清全部
            if (rel === '') { sel.clear(); sel.add(''); }
            else {
              if (sel.has('')) sel.clear();
              for (const s of [...sel]) {
                if (s.startsWith(rel + '/')) sel.delete(s);
              }
              sel.add(rel);
            }
          } else sel.delete(rel);
          render();
        };
        r.appendChild(chk);
        const lab = _h('span', name + '');
        lab.style.cssText = 'flex:1;';
        if (inh !== null && !sel.has(rel)) lab.style.color = 'var(--muted)';
        r.appendChild(lab);
        if (sub || kids[rel]) {
          const ex = _h('button', expanded.has(rel) ? '▾' : '▸', false);
          ex.style.cssText = 'border:none;background:none;color:var(--muted);cursor:pointer;padding:0 4px;font-size:10px;';
          // a422（用户实锤：点名字不能展开、只有最右小三角能点，极易点串
          // 行）：展开逻辑抽出，目录名本身与三角同权——label 占满整行
          // （flex:1），点行即展开；复选框点击不受影响（不冒泡到 label）
          const _doExpand = async () => {
            if (expanded.has(rel)) { expanded.delete(rel); render(); return; }
            if (!kids[rel]) {
              ex.textContent = '⋯';
              try {
                const rj = await (await fetch('/api/nav/scope_tree?root=' +
                  encodeURIComponent(root) + '&rel=' + encodeURIComponent(rel))).json();
                if (!rj.ok) throw new Error(rj.err || '');
                kids[rel] = { dirs: rj.dirs || [], files: rj.files || 0,
                              truncated: !!rj.truncated };
              } catch (e) { showBanner('目录读取失败: ' + e, 3000, true); ex.textContent = '▸'; return; }
            }
            expanded.add(rel);
            render();
          };
          ex.onclick = _doExpand;
          lab.style.cursor = 'pointer';
          lab.onclick = _doExpand;
          r.appendChild(ex);
        }
        tree.appendChild(r);
        if (expanded.has(rel) && kids[rel]) {
          for (const d of kids[rel].dirs) mkRow(d.rel, d.name, d.sub, depth + 1);
          const _emp = _h('div', kids[rel].truncated
            ? '（子目录过多，仅显示前 800 个）' : '（无子目录）');
          _emp.style.cssText = 'color:var(--muted);padding-left:' + ((depth + 1) * 16) + 'px;font-size:11px;';
          if (!kids[rel].dirs.length || kids[rel].truncated) tree.appendChild(_emp);
        }
      };
      // 根行展开由 mkRow 内部递归渲染（a398#28：去掉外层重复循环）
      mkRow('', '（整个目录 ' + (root.split(/[\\/]/).pop() || root) + '）', true, 0);
    };
    (async () => {
      try {
        const rj = await (await fetch('/api/nav/scope_tree?root=' +
          encodeURIComponent(root) + '&rel=')).json();
        if (!rj.ok) throw new Error(rj.err || '');
        kids[''] = { dirs: rj.dirs || [], files: rj.files || 0, truncated: !!rj.truncated };
      } catch (e) { showBanner('目录读取失败: ' + e, 3000, true); }
      expanded.add('');
      render();
    })();
    bClr.onclick = () => { sel.clear(); render(); };
    bCancel.onclick = () => ov.remove();
    bOk.onclick = () => {
      const dirs = [...sel].sort();
      ov.remove();
      cb(dirs);
    };
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
        _renderCodegraph(st, path, btns, card);
        return;   // ctags 无按钮：不盲目；codegraph 区块自行决定
      }
      st.textContent = '✓ 发现代码文件（浅层抽样 ' + (j.probe_files || 0) + ' 个）。'
        + '首次索引需扫描全目录——网盘挂载的大库可能数分钟，结果存工具数据目录（不写工程目录）。';
      // a398：收录范围行（检测配置/档位/导入 JSON/目录树多选）
      st.appendChild(_scopeRow(card, path, j));
      // a393（用户实锤：建索引时不给选项，想选 readtags/sql 都不行）：建立
      // 按钮旁挂档位下拉（自动=按库大小判；全量方案已下线不提供）
      const fbSel = _bkSel('auto', j.sqlite_ok !== false, true);
      bAdd.onclick = () => _startBuild(card, path, fbSel.value);
      btns.insertBefore(fbSel, btns.lastChild);
      btns.insertBefore(bAdd, btns.lastChild);
      _renderCodegraph(st, path, btns, card);   // R27-3：两套独立，都要可见
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
    if (m.scope && m.scope.name) {   // a398：本次建库所用范围（meta 记录）
      st.appendChild(_h('div', '本次建库范围：' + m.scope.name +
        '（' + (m.scope.tier || '') + '，' +
        ((m.scope.include && m.scope.include.length) || 0) + ' 目录）——换范围用下方控件重选后重建'));
    }
    st.appendChild(_scopeRow(card, path, j));   // a398：换范围重选入口
    const bRe = _h('button', ICO16.refresh + ' 重建', true);
    bRe.className = 'btn primary';
    // 用户实锤：重建按钮不传 backend——想建 sqlite 却走 auto 全部重建。
    // 改为传下拉当前值（重建尊重用户选的档位）
    bRe.onclick = () => _startBuild(card, path, bkSel.value);
    // a369：查询后端切换（重建按钮左侧下拉；sqlite 走任务槽带进度）
    // a390：后端无 sqlite3 能力（旧版 exe 打包缺件）——藏 sql 档
    // a393（用户令：不允许全量方案）：档位只剩 readtags/sqlite；旧库
    // meta.backend=memory 显示/复位兜底 readtags（切档即迁移）
    const _sqlOk = j.sqlite_ok !== false;
    const _curBk = m.backend || (m.code_files >= 200000 ? 'sqlite' : 'readtags');
    const _defBk = ((_curBk === 'sqlite' && !_sqlOk) || _curBk === 'memory')
      ? 'readtags' : _curBk;
    const bkSel = _bkSel(_curBk, _sqlOk, false);
    bkSel.onchange = async () => {
      const v = bkSel.value;
      if (typeof _ddConfirm === 'function' &&
          !(await _ddConfirm('切换查询模式', v === 'sqlite'
            ? '构建 sqlite 快查索引（大库约 1 分钟，一次性；查询 0~4ms/内存 ~50MB）？'
            : `切到 ${v} 模式（删除 tags.db 立即生效）？`))) {
        // C-2+S-B1：①_renderState 二次调用命中死节点（btns 捕获 div:last-child
        // 落进 st 内部行）——改直接复位下拉；②弹窗 z=200 被面板 z=9999 遮挡
        // （见 P-5b 的 CSS 补丁），此处只需复位显示态
        bkSel.value = _defBk;
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
        if (!d2.ok) bkSel.value = _defBk;   // R3-3：:883 出口
      } catch (e) { showBanner('切换失败: ' + e, 3000, true);
        bkSel.value = _defBk;   // R3-3：:884 catch 出口
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
    _renderCodegraph(st, path, btns, card);
  }

  // a336：codegraph 区块——状态行 + 建/重建 + 增量同步 + 删除
  async function _renderCodegraph(st, path, btns, card) {
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
      // a392（用户实锤：.codegraph 残留/损坏 → status 解析失败 → 零按钮，
      // 重建/更新菜单全没）：排除"未安装"外都给重建出口（build 的 init
      // --force 无条件清场，能修复半成品/损坏的 .codegraph）
      if ((j.err || '').indexOf('未安装') === -1) {
        const bFix = _h('button', ICO16.refresh + ' 重建', true);
        bFix.className = 'btn primary';
        bFix.style.cssText = 'padding:2px 10px;font-size:11px;margin-left:6px;';
        bFix.onclick = () => _cgRun(path, 'build', card);
        line.appendChild(bFix);
      }
      st.appendChild(line);
      return;
    }
    const info = _h('div');
    line.appendChild(info);
    const mkBtn = (label, cls) => {
      const b = _h('button', label, true);   // a344：label 可含 ICO16 SVG
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
    bBuild.onclick = () => _cgRun(path, 'build', card);
    const bSync = mkBtn(ICO16.refresh + ' 增量同步', 'btn ghost');
    bSync.style.display = j.installed ? '' : 'none';
    bSync.title = '代码大改后秒级增量';
    bSync.onclick = () => _cgRun(path, 'sync', card);
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

  function _cgRun(path, mode, card) {
    fetch('/api/nav/cg_build', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: path, mode }) })
      .then(r => r.json())
      .then(j => {
        if (!j.ok) { showBanner('启动失败：' + (j.err || ''), 4000, true); return; }
        // R26-2（实锤：codegraph 任务 UI 零反馈）：真开进度面板——与
        // ctags 建库同款（轮询同通道，日志/进度/取消/完成通知全有）
        // a453（第二轮审计 P2）：必须用发起时那张卡片。原来在回调里取
        // `panel.firstChild`——请求在途时用户关了面板又对另一目录开了新
        // 面板，就会把 B 的卡片强行换成 A 的 codegraph 进度（poll 显示旧
        // root），随后 B 的正常渲染又覆盖它，留下指向已 detach 节点的
        // interval 无人清理。
        if (!card || !card.isConnected) return;
        _renderProgress(card, path);
      })
      .catch(e => showBanner('启动失败: ' + e, 4000, true));
  }

  function _startBuild(card, path, backend) {
    // 用户实锤：重建按钮不传 backend → 后端走 auto → 想建 sqlite 却走
    // 全部重建流程。改为传下拉当前值（重建尊重用户选的档位）
    const body = backend ? { root: path, backend: backend } : { root: path };
    // a398：收录范围载荷（_scopeRow 选择/导入/手选经 card._scopeSel 闭包）
    const _sc = (card._scopeSel && card._scopeSel()) || null;
    if (_sc) Object.assign(body, _sc);
    fetch('/api/nav/build', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) })
      .then(r => r.json())
      .then(j => {
        if (!j.ok) { showBanner('启动失败：' + (j.err || ''), 4000, true); return; }
        // a452（审计 P1）：面板可能在 fetch 在途时已被关闭（慢盘上点完立刻
        // 点背景，此时 dataset.running 还没置位，遮罩仍可关）。原实现照样
        // _renderProgress，在已脱离 DOM 的 card 上重建轮询与计时器，之后
        // 无人清理（_closePanel 早跑过了），后台每 800ms 空转到任务结束。
        // a453（第二轮审计 P2）：只按 id 查面板还不够——期间用户可能在
        // 另一目录打开了**新**面板，id 命中但 card 已不属于它。原实现会把
        // A 的进度渲染到脱离 DOM 的卡片上，还把 B 面板设成 running，用户在
        // B 点关闭会取消掉一个他以为不存在的任务。必须校验 card 仍连通。
        if (!card.isConnected) return;
        _renderProgress(card, path);
      })
      .catch(e => showBanner('启动失败: ' + e, 4000, true));
  }

  // a431：白名单覆盖率偏低时的建库方式选择弹窗——把实际数据显示给用户，
  // 由用户决定「只收白名单」还是「全量收源码」，不再由代码写死阈值行为。
  function _askTierDialog(info, txt) {
    const ov = document.createElement('div');
    ov.id = 'navTierDialog';   // a432：可被 _closePanel 统一清理
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);' +
      'z-index:10050;display:flex;align-items:center;justify-content:center;';
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:520px;max-width:92vw;padding:18px 20px;' +
      'border-radius:12px;background:var(--bg-panel);border:1px solid var(--border);' +
      'box-shadow:0 12px 40px rgba(0,0,0,.5);';
    const title = _h('div', '编译白名单可能不完整');
    title.style.cssText = 'font-size:14px;font-weight:600;margin-bottom:10px;';
    card.appendChild(title);
    const lines = [
      ['products', '编译产物', (info.o_count || 0) + ' 个 .o · ' + (info.cmd_files || 0) + ' 个 .cmd'],
      ['units', '推导出的源码单元', (info.units || 0) + ' 个'],
      ['all', '收录集内源码文件', (info.all_code || 0) + ' 个'],
      ['cover', '覆盖率', (info.cover || 0) + '%'],
    ];
    lines.forEach(([k, label, val]) => {
      const row = _h('div');
      row.style.cssText = 'display:flex;justify-content:space-between;' +
        'font-size:12px;padding:3px 0;font-family:var(--font-mono);';
      const a = _h('span', label);
      a.style.cssText = 'color:var(--muted);';
      const b = _h('span', val);
      if (k === 'cover') b.style.cssText = 'color:var(--accent);font-weight:600;';
      row.appendChild(a); row.appendChild(b);
      card.appendChild(row);
    });
    const hint = _h('div', '该工程可能尚未编译，或产物来自 SDK 预编译/外部构建系统。' +
      '请选择收录方式：');
    hint.style.cssText = 'font-size:12px;color:var(--muted);margin:12px 0 0;' +
      'line-height:1.6;';
    card.appendChild(hint);
    const opts = [
      ['full', '全量收源码（推荐）',
       '收录范围内所有 C/C++/汇编源码（' + (info.all_code || 0) + ' 个），索引更完整'],
      ['whitelist', '只收白名单',
       '仅收录能推出源的 ' + (info.units || 0) + ' 个单元，索引更小更快'],
    ];
    const wrap = _h('div');
    wrap.style.cssText = 'margin-top:12px;display:flex;flex-direction:column;gap:8px;';
    opts.forEach(([val, label1, desc]) => {
      const b = _h('button');
      b.className = 'btn';
      b.style.cssText = 'text-align:left;padding:10px 12px;line-height:1.5;';
      const t1 = _h('div', label1);
      t1.style.cssText = 'font-size:13px;font-weight:600;';
      const t2 = _h('div', desc);
      t2.style.cssText = 'font-size:11px;color:var(--muted);margin-top:2px;';
      b.appendChild(t1); b.appendChild(t2);
      b.onclick = () => { ov.remove(); _postTier(val); };
      wrap.appendChild(b);
    });
    card.appendChild(wrap);
    const btns = _h('div');
    btns.style.cssText = 'margin-top:12px;display:flex;justify-content:flex-end;';
    const cancel = _h('button', '放弃建库');
    cancel.className = 'btn ghost';
    cancel.onclick = () => { ov.remove(); _postTier('cancel'); };
    btns.appendChild(cancel);
    card.appendChild(btns);
    ov.appendChild(card);
    document.body.appendChild(ov);
    if (txt) txt.textContent = '等待选择建库方式…';

    function _postTier(choice) {
      // a452（审计 P2）：后端 10 分钟超时撤销提问后，前端还没轮询到，
      // 此时点选项拿到 409。原来无条件写「已选择：…」，用户以为选项生效，
      // 实际已按超时默认（全量）继续。先如实显示「提交中」，按结果再定。
      if (txt) txt.textContent = '提交选择…';
      fetch('/api/nav/tier', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ choice }),
      }).then(r => r.json().then(j => ({ ok: r.ok, j })))
        .then(({ ok, j }) => {
          if (ok && j && j.ok) {
            if (txt) txt.textContent = '已选择：' +
              ({ full: '全量收源码', whitelist: '只收白名单', cancel: '放弃建库' }[choice] || choice);
          } else if (txt) {
            txt.textContent = '选择未生效（' + ((j && (j.err || j.msg)) || '任务已结束') + '）';
          }
        })
        .catch(() => { if (txt) txt.textContent = '提交失败（网络异常）'; });
    }
  }

  function _renderProgress(card, path) {
    const _ov = document.getElementById('navIdxPanel');
    if (_ov) _ov.dataset.running = '1';   // a392：背景关闭禁令配套标记
    card.innerHTML = '';
    // a452：本轮的定时器句柄（闭包私有），清理只动自己
    let _myPoll = null, _myClock = null;
    // a426（需求：独立计时器 hh:mm:ss）：与进度条/阶段文案分离，只此一处报时间；
    // 其余日志里的「已用 Ns」全部去掉，避免多处读秒互相打架
    const headRow = _h('div');
    headRow.style.cssText = 'display:flex;align-items:baseline;gap:10px;';
    headRow.appendChild(_h('div', '正在建立索引'));
    const clock = _h('div', '00:00:00');
    clock.style.cssText = 'margin-left:auto;font-family:var(--font-mono);' +
      'font-size:15px;font-weight:600;color:var(--accent);letter-spacing:.5px;';
    headRow.appendChild(clock);
    card.appendChild(headRow);
    // a426：基准先用本地时刻，首次 poll 拿到后端 started 后校正
    // （关面板重开/刷新页面仍显示真实已用时间，不从 0 重数）
    let _t0 = Date.now();
    let _synced = false;
    const _fmt = (ms) => {
      const s = Math.max(0, Math.floor(ms / 1000));
      const hh = String(Math.floor(s / 3600)).padStart(2, '0');
      const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
      const ss = String(s % 60).padStart(2, '0');
      return hh + ':' + mm + ':' + ss;
    };
    clock.textContent = _fmt(0);
    if (_navClockTimer) clearInterval(_navClockTimer);
    _navClockTimer = _myClock = setInterval(() => {
      clock.textContent = _fmt(Date.now() - _t0);
    }, 1000);
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
    bCancel.onclick = () => {
      // a432：若建库正卡在「等用户选建库方式」，取消要同时把弹窗收掉
      const _td = document.getElementById('navTierDialog');
      if (_td) _td.remove();
      fetch('/api/nav/cancel', { method: 'POST' });
    };
    btns.appendChild(bCancel);
    card.appendChild(btns);
    let _rowByKey = {};   // a424：进度行 key -> DOM 节点（同类日志原地刷新）
    let _lastSeq = 0;     // a424：按 seq 增量拉取（后端裁剪后下标不再错位）
    let _tierAsked = false;   // a431：建库方式弹窗只弹一次
    if (_pollTimer) clearInterval(_pollTimer);
    // a452（审计 P1：误清后来任务的定时器）：句柄已在本函数顶部声明为
    // _myPoll/_myClock，回调结束时只清自己的。原来清的是模块级当前值——
    // 任务 A 的末次 poll 在途中，用户重开面板起了任务 B，A 的回调返回
    // done 时清掉的是 B 的 interval，B 的进度与日志永久停在初值。
    _pollTimer = _myPoll = setInterval(async () => {
      try {
        const r = await fetch('/api/nav/poll');
        const s = await r.json();
        if (!_synced && s.started) {
          _t0 = s.started * 1000; _synced = true;
          clock.textContent = _fmt(Date.now() - _t0);
        }
        bar.style.width = (s.percent || 0) + '%';
        txt.textContent = (s.phase || '') + ' · ' + (s.percent || 0) + '%' + (s.cancelling ? ' · 正在取消…' : '');
        const lg = s.log || [];
        // a434：后端日志上限 400 条，轮询间隔内产出过多时中间条目会被裁掉。
        // 后端上报已被裁掉的最大 seq，前端发现自己的进度落后于它才提示
        // （进度行原地替换也消耗 seq，不能只看条数或首条 seq）。
        const _drop = s.log_dropped || 0;
        if (_drop > _lastSeq) {
          // a452（审计 P2）：log_dropped 是**被裁掉的最后一条的 seq**，不是
          // 条目数。进度行原地替换同样消耗 seq，直接相减会把「合并」算成
          // 「丢失」（实际裁掉 100 条却提示省略 320 条）。改用对数估算：
          // 两者之比只有量级意义，措辞也据此降级为「约」。
          const _miss = _drop - _lastSeq;
          const d = _h('div', '（已省略约 ' + _miss + ' 条过程日志——建库仍在继续）');
          d.style.cssText = 'color:var(--muted);opacity:.7;';
          log.appendChild(d);
          _lastSeq = _drop;
        }
        for (const e of lg) {
          if (!e || e.seq <= _lastSeq) continue;
          _lastSeq = e.seq;
          if (e.key && _rowByKey[e.key]) {
            _rowByKey[e.key].textContent = e.msg;      // 同一行刷新
            continue;
          }
          const d = _h('div', e.msg);
          log.appendChild(d);
          if (e.key) _rowByKey[e.key] = d;
        }
        log.scrollTop = log.scrollHeight;
        // a431：白名单覆盖率偏低——弹窗让用户选建库方式（给实际数据）
        if (s.ask_tier && !_tierAsked) {
          _tierAsked = true;
          _askTierDialog(s.ask_tier, txt);
        } else if (!s.ask_tier && _tierAsked) {
          // a434：后端已撤销提问（10 分钟超时按全量继续 / 任务取消），
          // 弹窗若还开着必须收掉——否则用户点了只会拿到 409
          const _td3 = document.getElementById('navTierDialog');
          if (_td3) _td3.remove();
          _tierAsked = false;
        }
        if (!s.done) return;
        // a456（第三轮审计 P2：上一版的 early return 跳过了自己的清理）：
        // 必须先无条件停掉**本轮自己的**定时器，再对模块级引用加门。
        // 原来 `if (_pollTimer !== _myPoll) return;` 直接 return——任务 A 的
        // 最后一次 poll 在途时用户换目录起任务 B，A 的 interval 永不被
        // clear，此后每 800ms 仍打 /api/nav/poll 把 B 的日志往 A 已脱离
        // DOM 的容器里追加，直到刷新页面。
        clearInterval(_myPoll);
        if (_myClock) clearInterval(_myClock);
        const _mine = (_pollTimer === _myPoll);
        if (_mine) _pollTimer = null;
        if (_navClockTimer === _myClock) _navClockTimer = null;
        _myPoll = _myClock = null;
        // 全局 DOM（弹窗 / running 标志）属于**当前轮**，不是本轮就不碰——
        // 否则 A 的终态回调会删掉 B 正在等作答的弹窗、解除 B 的面板禁令。
        if (!_mine) return;
        // a434：任务已终态，遗留的建库方式弹窗必须收掉（否则挡住结果）
        const _td2 = document.getElementById('navTierDialog');
        if (_td2) _td2.remove();
        const _ov2 = document.getElementById('navIdxPanel');
        if (_ov2) delete _ov2.dataset.running;   // a392：任务终态解除背景关闭禁令
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
                     // a336：导航历史（设置页/右键菜单可直接触发）
                     goBack: navigateBack, goForward: navigateForward };
