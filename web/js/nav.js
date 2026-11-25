// a333 批1：代码跳转（ctags 索引 + 编译白名单 + ELF 符号表）
// R15-1 实锤修正：standalone Monaco 对未知 uri 没有内容服务——provider
// 返回 uri 只会得到空白/无反应。改自定义跳转：Ctrl+Click/F12 → 查询 →
// 唯一可信候选 openFileSmart 直跳；多候选弹带徽标的候选面板（原批 2
// 提前落地）。provider 注册保留但恒返回 null（防 Monaco 原生空跳干扰）。
// 模块化一期（js-modularization 分支）：已转 ES module——IIFE 壳已剥。
// 对外表面仅 window.NavJump（settings.js:170 window 守卫 + tree-fileops
// 菜单 action，均为运行时调用）。
'use strict';

  // a570 对抗审计（P2·第十九轮）：本会话已发起取消的推荐 run_id（跨弹层共享）
  const _deadRuns = new Set();
  // a571：首次建库「确认弹窗 → 调整范围…」时带过去的一次性推荐结果，
  // 由 _scopeRow 消费（免一次 20~60 秒重扫）。
  // a572（内网评审 F1）：必须绑定工程根——原来是裸对象，任何失败路径
  // （409 / 探测失败 / 切目录）都会让它常驻，并在**下一个任意工程**被消费，
  // 把 A 的推荐灌进 B 的树、甚至覆盖 B 已落盘的配置。现在存 {path, rec}。
  let _pendingRec = null;
  // a572（内网评审 F6）：`ask_tier` 选「重新配置」后，面板建好要自动开树。
  // a573（第 2 轮审计 #2）：与 `_pendingRec` 同类，必须绑定工程根——原为裸
  // 布尔，置位后若 `_renderState` 早退（探测失败/无代码/面板已关）就常驻，
  // 会在**下一个任意工程**的面板上自动跑一次 20~60 秒推荐并弹树。
  let _openPickOnNext = null;   // null | {path}
  // a572（B10）/ a573（第 2 轮审计 #3）：弹窗作答反馈的保留截止时刻（ms）。
  // 原实现写入端取 `#navIdxPanel`（外层 ov）、读取端用 `card`（内层 .dd-cur），
  // 两个不同对象 -> 恒为 0，3 秒保留从未生效。改模块级统一读写。
  let _txtHoldUntil = 0;
  // a572（内网评审 F4）：弹窗「已弹过」标志——模块级、按后端 started 判轮次。
  // 原为 `_renderProgress` 的闭包局部，同目录重开面板会重置 -> 叠出多个同 id
  // 弹窗，清理只删第一个，剩余成为全屏孤儿遮罩。
  const _navAskSeen = { started: 0, tier: false, scope: false };
  // a576（第 2 轮审计·低）：同一工程「重配后重开面板」的排期去重。
  const _reopenOnce = new Set();

  // a573（第 2 轮审计 #6 + 第 3 轮）：工程根归一——统一分隔符 + 去尾分隔符 + 小写。
  // 第 3 轮审计实测：原来写成 `/[\/]+$/` 时 JS 把 `\/` 当成一个转义斜杠，
  // 反斜杠根本没被匹配 —— Windows 上「去尾分隔符」等于没做（`Z:\P\` 未剥）。
  // 这里完全不用正则，改用逐字符循环，杜绝转义歧义。
  function _normRoot(p) {
    const s0 = String(p || '');
    let out = '';
    for (let i = 0; i < s0.length; i++) {
      out += s0.charCodeAt(i) === 92 ? '/' : s0[i];
    }
    while (out.length > 1 && out[out.length - 1] === '/') {
      out = out.slice(0, -1);
    }
    if (out === '/') out = '';
    return out.toLowerCase();
  }
  function _sameRoot(a, b) { return _normRoot(a) === _normRoot(b); }

  // a572（内网评审 F1）：`_pendingRec` 的所有失败/早退路径统一清理。
  // 只有工程根匹配的才真正丢弃（别的工程的挂起项不能因本工程失败而被清）。
  function _dropPendingRec(path) {
    if (_pendingRec && _sameRoot(_pendingRec.path, path)) {
      _pendingRec = null;
    }
  }
  // a576（第 1 轮审计·低-3）：`_openPickOnNext` 与 `_pendingRec` 对称的清理
  // ——早退路径（探测失败/无代码/重开窗口内关面板）必须一起清，否则标志
  // 滞留到下一个任意工程的 _scopeRow 才被无条件清零，丢掉本工程的重开意图。
  function _dropOpenPick(path) {
    if (_openPickOnNext && _sameRoot(_openPickOnNext.path, path)) {
      _openPickOnNext = null;
    }
  }  // 与后端 nav_index._TMP_NAMES 同口径（walk 无条件硬剪）
  const _TMP_L = new Set(['tmp', 'temp', 'tmpdir', 'tempdir']);

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
    // a452：切换目录查看 ≠ 放弃正在等选择的任务，只收面板不取消建库。
    // a572（F2）：把「正在关的旧面板」所属工程传下去——弹窗按所属工程各自保留。
    const _oldP = document.getElementById('navIdxPanel');
    // a578（第 4 轮审计）：切目录同样是「放弃当前面板」——必须按旧工程根
    // 清掉挂起标志。原实现只传 closingPath，第 4 轮把清理改成「必须显式
    // dropPending」后这里被漏掉：点「调整范围…」后立刻切到别的目录，
    // reconfigure 分支永不执行，`_pendingRec` 滞留，之后在**另一个工程**
    // 的面板上弹「推荐结果已失效」，或回原工程时用陈旧推荐自动改范围。
    // 内部自动重开（reconfigure 分支的 _closePanel）此时旧面板已移除，
    // `_oldP` 为 null → 传 false，不会误清重开意图。
    _closePanel(false, (_oldP && _oldP.dataset.path) || undefined, !!_oldP);
    const ov = document.createElement('div');
    ov.id = 'navIdxPanel';
    ov.dataset.path = path || '';   // a572（F2）：面板所属工程根
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.32);z-index:9999;display:flex;align-items:center;justify-content:center;';
    // a392（用户实锤：点一下背景进度就没了，任务还在跑却看不到过程）：
    // 任务运行中禁背景关闭（资源安装弹窗同款①；✕/关闭仍可关——重开有恢复式显示②兜底）
    ov.addEventListener('mousedown', function (e) {
      if (e.target !== ov) return;
      if (ov.dataset.running === '1') return;
      _closePanel(true, path, true);
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
  function _closePanel(cancelIfAsking, closingPath, dropPending) {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
    if (_navClockTimer) { clearInterval(_navClockTimer); _navClockTimer = null; }
    // a572（内网评审 F2）：只有「弹窗的所属工程 === 正在关的工程」时才允许
    // 摘除并取消任务。原来只判 cancelIfAsking——用户关 B 的面板会把 A 正在
    // 等作答的 tier 弹窗删掉、并替 A 发 /api/nav/cancel，A 的建库被静默终止。
    // a576（第 1 轮审计·低-2）：closingPath 缺失时**不再**兜底放行。原来
    // `return true`，任何今后新增的无参 `_closePanel()` 调用都会立刻回到旧
    // bug——关 B 面板删掉 A 的弹窗并替 A 发 /api/nav/cancel（后端 nav_cancel
    // 只判全局 running，A 的建库被静默取消）。无法判定归属就不动别人的弹窗。
    const _ownsDlg = (el) => {
      if (!el) return false;
      if (closingPath === undefined) return false;
      // a575（第 5 轮审计 #1）：走 `_sameRoot` 归一，与 `_pendingRec` /
      // reconfigure 重开检查的口径一致。严格相等时，同一工程若曾以
      // `Z:\P` 与 `Z:/P`（或带尾分隔符）两种写法分别建弹窗/关面板，
      // 会判否 -> 关本工程面板时不摘自己的弹窗、也不发 cancel。
      return _sameRoot(el.dataset.root || '', closingPath);
    };
    const _td = document.getElementById('navTierDialog');
    if (_td && _ownsDlg(_td)) {
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
    // a572（B6）：`navScopeConfirm` 同样要在这里收掉——否则用户关掉面板后
    // 它成为孤儿遮挡层；点「调整范围…」进去的三态树会绑定在已删除的 card 上。
    const _sd = document.getElementById('navScopeConfirm');
    if (_sd && _ownsDlg(_sd)) {
      if (cancelIfAsking !== false) {
        _sd.remove();
        fetch('/api/nav/cancel', { method: 'POST' }).catch(() => {});
      }
    }
    // a570 对抗审计（P2·第十六轮）：切目录时三态树弹层必须一起收掉。
    // 原实现只移除 navIdxPanel/navTierDialog，navScopePick 留成孤儿层——
    // 它盖在新面板上、仍绑定已脱离 DOM 的旧 card，「建库」只写进死对象，
    // 用户以为选好了实际没生效。
    const _sp2 = document.getElementById('navScopePick');
    if (_sp2) {
      try { if (typeof _sp2._cleanup === 'function') _sp2._cleanup(true); }
      catch (_e) { /* 忽略 */ }
      if (_sp2.parentNode) _sp2.parentNode.removeChild(_sp2);
    }
    // a576（第 2 轮·低 → 第 3 轮·中）：用户**主动放弃**时要清挂起标志，
    // 但**内部自动重开**不能清。原实现无条件按 closingPath 清，把
    // reconfigure 分支「先 _closePanel 再置 _openPickOnNext」的顺序打乱——
    // `_pendingRec` 在重开前就被清掉，于是「调整范围…」丢掉已算好的推荐
    // 结果、退回 20~60 秒完整重扫。改由调用方显式声明。
    if (dropPending && closingPath !== undefined) {
      _dropPendingRec(closingPath);
      _dropOpenPick(closingPath);
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
    // a573（第 2 轮审计 #1）：原来直接绑 `_closePanel`——浏览器以 (event) 调用，
    // closingPath 恒 undefined，`_ownsDlg` 兜底返回 true，归属判断被绕过。
    // 关 B 的面板会删掉 A 的弹窗并替 A 发 /api/nav/cancel。显式传参。
    closeB.onclick = () => _closePanel(true, path, true);
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
    // a576（第 2 轮审计·中）：僵尸面板（card 已脱离 DOM）**不得**消费
    // `_pendingRec` / `_openPickOnNext`。原实现是无条件先置空再看归属：
    // 打开 A 面板后 probe 未回就切到 B，A 的 probe 回来时
    // `getElementById('navIdxPanel')` 只认 id 不认归属、命中 B 的面板，
    // 于是 A 的僵尸 `_scopeRow` 把此刻属于 B 的挂起标志清掉 —— B 的
    // 「调整范围…」/重配后三态树静默不弹。这里直接不进场。
    // a577（第 3 轮审计·低）：早退必须返回**可 append 的节点**——调用点写成
    // `st.appendChild(_scopeRow(...))`，返回 undefined 会抛 TypeError 并写进
    // 全局错误日志。
    if (!card || !card.isConnected) return _h('div');
    const box = _h('div');
    box.style.cssText = 'margin-top:8px;padding:8px 10px;border:1px dashed var(--border);border-radius:8px;font-size:12px;';
    const sc = j.scope || null;
    // a570 对抗审计（P2·第十七轮）：本次面板内已清除工程根配置
    let _scCleared = false;
    const head = _h('div');
    head.style.cssText = 'margin-bottom:6px;';
    const _headTxt = (t) => {
      head.textContent = t;
      head.style.color = '';   // a570 对抗审计：复用同一 head 元素，
                               // 不复位颜色会把正常状态渲染成告警色
    };
    const _withCounts = (cfg) => {
      const _d = (cfg && cfg.dirs) || {};
      const _c = { whitelist: 0, full: 0, off: 0 };
      // a570 对抗审计（P2·第二十轮）：与后端 `_norm_dirs` 同口径——导入的
      // 合法值可能带空格/大写（" FULL "），精确匹配会显示「白 0 · 全 0」。
      for (const k in _d) {
        const _v = String(_d[k]).trim().toLowerCase();
        if (_c[_v] !== undefined) _c[_v]++;
      }
      return Object.assign({}, cfg, { state_counts: _c });
    };
    const _headCfg = (cfg, srcLabel) => {
      head.textContent = '';
      head.style.color = '';   // 复位告警色（同 _headTxt）
      head.append('收录范围：');
      const b = _h('b', cfg.name || '未命名范围');
      head.appendChild(b);
      // a570：v2 摘要 = 白/全/不勾 计数
      const _c = cfg.state_counts || {};
      head.append('（' + (cfg.mode || 'manual') + '）——' + srcLabel +
        '，白 ' + (_c.whitelist || 0) + ' · 全 ' + (_c.full || 0) +
        ' · 不勾 ' + (_c.off || 0));
    };
    if (sc && sc.source === 'project') {
      _headCfg(sc, '读取工程配置 .fcpk-scope.json');
    } else if (sc && sc.source === 'v1-deprecated') {
      _headTxt('收录范围：旧版（v1）配置已废弃——下次建库会按推荐重新生成并覆盖');
      head.style.color = 'var(--neon-orange,#d29922)';
    } else if (sc && String(sc.source || '').startsWith('bad:')) {
      _headTxt('收录范围：配置解析失败（' + sc.source.slice(4) + '）——将按推荐重新生成');
      head.style.color = 'var(--neon-red,#e5484d)';
    } else if (j.scope_detect && j.scope_detect.kind === 'sbuilder') {
      _headTxt('检测到 buildroot/sbuilder 方案（产物外挂，只读 .cmd/.o 不索引副本）——点「选择目录…」查看推荐结果');
    } else {
      _headTxt('收录范围：未配置——点「选择目录…」由推荐器给出三态树，确认后建库');
    }
    box.appendChild(head);
    const row = _h('div');
    row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;align-items:center;';
    const sel = _h('select');
    sel.className = 'lv-btn';
    sel.style.cssText = 'padding:2px 6px;font-size:11px;';
    sel.title = '收录范围档位';
    const OPTS = [
      ['follow', (sc && sc.source === 'project') ? '读取工程配置' : '自动（按需推荐）'],
      ['whitelist', '白名单（只收编译产物推导出的源码）'],
      ['full', '全量（整树收录）'],
    ];
    const renderSel = () => {
      const cfg = card._scopeCfg;
      // a570 对抗审计（P2·第十七轮）：重建 options 前必须记下当前选择——
      // innerHTML 会重置 sel.value 到第一项，原实现靠「(sel.value ||
      // 'follow') === v」在重建**过程中**读，读到的是已被清空的值。
      const _cur = sel.value || 'follow';
      const _opts = OPTS.map(([v, n2]) => [v, v === 'follow' && _scCleared
        ? '自动（按需推荐）' : n2]);
      sel.innerHTML = _opts.concat(cfg ? [['cfg', '本次导入/手选']] : [])
        .map(([v, n2]) => '<option value="' + v + '">' + n2 + '</option>').join('');
      sel.value = (_cur === 'cfg' && !cfg) ? 'follow' : _cur;
      if (!sel.value) sel.value = 'follow';
    };
    renderSel();
    // a570 对抗审计（P2·第十六轮）：原下拉无 onchange，头部文字停在打开时的
    // 状态（「读取工程配置」），切到「全量」后头部仍那样写，展示与生效相反。
    const _syncSelHead = () => {
      const v = sel.value || 'follow';
      if (v === 'cfg' && card._scopeCfg) {
        _headCfg(_withCounts(card._scopeCfg), '本次导入/手选，建库成功后写入工程根');
        return;
      }
      if (v === 'whitelist') {
        _headTxt('收录范围：白名单档（按编译产物推导源码，整树统一）——点「建立索引」生效'
          + '（已有三态配置会被覆盖并备份为 .prev.bak）');
        return;
      }
      if (v === 'full') {
        _headTxt('收录范围：全量档（整树收录）——点「建立索引」生效'
          + '（已有三态配置会被覆盖并备份为 .prev.bak）');
        return;
      }
      // follow：回到打开面板时读到的状态
      // a570 对抗审计（P2·第十七轮）：「清除已存范围」后 sc 快照已失效，
      // 继续按它写「读取工程配置」与载荷(null)脱钩——这里按已清除处理。
      if (_scCleared) {
        _headTxt('收录范围：未配置（已清除已存范围）——小工程自动全量，'
          + '或点「选择目录…」重新配置');
        return;
      }
      if (sc && sc.source === 'project') {
        _headCfg(sc, '读取工程配置 .fcpk-scope.json（建库按此范围）');
      } else if (sc && sc.source === 'v1-deprecated') {
        _headTxt('收录范围：旧版（v1）配置已废弃——下次建库会按推荐重新生成并覆盖');
        head.style.color = 'var(--neon-orange,#d29922)';
      } else if (sc && String(sc.source || '').startsWith('bad:')) {
        _headTxt('收录范围：配置解析失败（' + sc.source.slice(4) + '）——将按推荐重新生成');
        head.style.color = 'var(--neon-red,#e5484d)';
      } else if (j.scope_detect && j.scope_detect.kind === 'sbuilder') {
        _headTxt('检测到 buildroot/sbuilder 方案（产物外挂，只读 .cmd/.o 不索引副本）——点「选择目录…」查看推荐结果');
      } else {
        _headTxt('收录范围：未配置——点「选择目录…」由推荐器给出三态树，确认后建库');
      }
    };
    sel.onchange = _syncSelHead;
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
        // a570：只认 v2。v1 同文件会被后端当「旧格式已废弃」，此处直接拦下
        // 比让用户建库后才发现更清楚。
        // a570 对抗审计（P2·第十七轮）：与后端 `_norm_scope_v2` **逐字对齐**
        // ——dirs 缺失/null 属合法（后端 `_norm_dirs(None)→{}`），此前前端
        // 一律拒绝，导致「前端拒/后端放行」的过度拦截。
        if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)
          || cfg.version !== 2) {
          showBanner('配置必须是 v2 格式（version:2 + dirs 对象）；旧 v1 格式已废弃',
            5000, true);
          return;
        }
        if (cfg.dirs !== undefined && cfg.dirs !== null
          && (typeof cfg.dirs !== 'object' || Array.isArray(cfg.dirs))) {
          showBanner('dirs 必须是对象（{相对路径: whitelist|full|off}）',
            5000, true);
          return;
        }
        const _dirsIn = cfg.dirs || {};
        // dirs 的值必须全是合法状态（后端 strip+lower 后比对）
        // a570 对抗审计（P2·第十八轮）：值必须是字符串——后端 `_norm_dirs`
        // 要求 isinstance(v, str)，而 String(["full"]) 会得到 "full" 让
        // 数组值被前端放行、建库才 400。
        const _badV = Object.keys(_dirsIn).find(
          k => typeof _dirsIn[k] !== 'string'
            || ['whitelist', 'full', 'off'].indexOf(
              _dirsIn[k].trim().toLowerCase()) < 0);
        if (_badV !== undefined) {
          showBanner('dirs 状态非法：' + _badV + ' = ' + _dirsIn[_badV] +
            '（只认 whitelist/full/off）', 5000, true);
          return;
        }
        // a570 对抗审计（P2·第三轮）：未知字段会被后端 `_norm_scope_v2`
        // 整体拒绝（「未知字段：…」）——在建库前就拦下并指名字段，比让
        // 用户在点「建立索引」后看到一条含糊的错误更清楚。
        // a576（第 2 轮审计·低-3）：`confirmed` 是 v2 合法字段（后端 _known
        // 已接受）——白名单漏了它，把 meta.scope 另存后「导入 JSON」会被
        // 前端以「未知字段：confirmed」整单拒绝。
        const _okKeys = ['version', 'name', 'mode', 'arch', 'dirs',
          'artifact_roots', 'exclude_names', 'confirmed'];
        const _badKeys = Object.keys(cfg).filter(k => _okKeys.indexOf(k) < 0);
        if (_badKeys.length) {
          showBanner('配置含未知字段：' + _badKeys.slice(0, 5).join('、') +
            '（只认 ' + _okKeys.join('/') + '）', 6000, true);
          return;
        }
        // 键的形态：绝对路径 / 盘符 / .. / 空键后端都会拒，提前拦
        // a570 对抗审计（P2·第十六轮）：反斜杠必须先归一（后端 _norm_dirs
        // 是 replace("\\","/") 之后才校验），否则 `a\..\b` 在这里被放行、
        // 到建库才 400。值与列表项同样按后端口径预校验。
        // a570 对抗审计（P2·第十七轮）：完全照抄后端步骤——先 strip 再归一，
        // 然后判绝对路径/空/../冒号。原来少了 strip，`{"  ":"off"}` 这类
        // 空白键被放行到建库才 400。
        const _normK = (k) => String(k).trim().replace(/\\/g, '/');
        // a570 对抗审计（P1·第十九轮）：根键 ""/"." 是合法形态（后端
        // `_norm_dirs` 接受并归一成 ""，用于表达「工程根自身」的收录状态）。
        // 前端原先一律拒，导致**后端自己导出的配置导不回来**。
        const _isRootKey = (k) => k === '' || k === '.';
        const _badK = Object.keys(_dirsIn).find(
          k => {
            if (_isRootKey(k)) return false;
            const raw = _normK(k);
            if (raw.charAt(0) === '/') return true;
            const p2 = raw.replace(/^\/+|\/+$/g, '');
            if (p2 === '' || p2 === '.') return true;
            const segs = p2.split('/').filter(s => s && s !== '.');
            return !segs.length || segs.some(s => s === '..' || s.indexOf(':') >= 0);
          });
        if (_badK !== undefined) {
          showBanner('dirs 含非法路径：' + JSON.stringify(_badK), 6000, true);
          return;
        }
        // 2026-11-23 总审计 a684-A6：tmp 类目录在 walk 里是无条件硬剪，显式
        // 配它必然是死配置。后端 `_norm_dirs`（a570 P1·第二十轮）对这类键
        // 是**忽略该键**并经 dropped 报告——判整份非法会让旧配置变 bad:，
        // 建库当无配置整棵全量重生成。前端原先整单拒（注释还写着同口径）：
        // 后端落盘的含 tmp 键配置走「导入 JSON」还原不了。现与后端同序：
        // 路径/值校验先过，再剔除 tmp 键并提示。
        const _tmpDropped = [];
        for (const _tmpKey of Object.keys(_dirsIn)) {
          if (_isRootKey(_tmpKey)) continue;
          const _tsegs = _normK(_tmpKey).replace(/^\/+|\/+$/g, '').split('/')
            .filter(s => s && s !== '.');
          if (_tsegs.some(s => _TMP_L.has(s.toLowerCase()))) {
            _tmpDropped.push(_tsegs.join('/'));
            delete _dirsIn[_tmpKey];
          }
        }
        // mode/arch 枚举 + mode=full/whitelist 时不允许 dirs（后端 _norm_scope_v2 同判）
        const _mode = String(cfg.mode || 'manual').trim().toLowerCase();
        if (['whitelist', 'manual', 'full'].indexOf(_mode) < 0) {
          showBanner('mode 只认 whitelist/manual/full（当前 ' + cfg.mode + '）',
            6000, true);
          return;
        }
        const _arch = String(cfg.arch || 'auto').trim().toLowerCase();
        if (['auto', 'arm', 'arm64'].indexOf(_arch) < 0) {
          showBanner('arch 只认 auto/arm/arm64（当前 ' + cfg.arch + '）', 6000, true);
          return;
        }
        // a570 对抗审计（P1·第十九轮）：根键例外——它只表达「根自身」，
        // 与 mode 同义，后端 `_norm_scope_v2` 也给它开了例外。
        const _nonRoot = Object.keys(_dirsIn).filter(k => !_isRootKey(k));
        if ((_mode === 'whitelist' || _mode === 'full') && _nonRoot.length) {
          showBanner('mode=' + _mode + ' 时全树统一，不能同时给 dirs 覆盖'
            + '（要按目录配置请用 mode=manual）', 6000, true);
          return;
        }
        // a570 对抗审计（P2·第二十轮）：`.` 与 `""` 是同一个根槽——同时出现时
        // 后端按 dict 顺序让后者覆盖前者，前端若只校验第一个就会「导入放行、
        // 建库 400」。直接拒，让用户明确选一个。
        const _rootKeys = Object.keys(_dirsIn).filter(k => _isRootKey(k));
        if (_rootKeys.length > 1) {
          showBanner('根状态只能写一个键（"." 或 ""，不要同时给）：'
            + _rootKeys.join('、'), 6000, true);
          return;
        }
        if (_mode === 'whitelist' || _mode === 'full') {
          // 与后端 `_norm_scope_v2` 同判：根键存在时取值必须等于 mode
          const _rk2 = _rootKeys[0];
          if (_rk2 !== undefined) {
            const _rv = String(_dirsIn[_rk2]).trim().toLowerCase();
            if (_rv !== _mode) {
              showBanner('mode=' + _mode + ' 与根状态 dirs["."]=' + _dirsIn[_rk2]
                + ' 矛盾', 6000, true);
              return;
            }
          }
        }
        // 路径列表（artifact_roots 可多段；exclude_names 只认单段目录名）
        for (const _key of ['artifact_roots', 'exclude_names']) {
          if (cfg[_key] === undefined || cfg[_key] === null) continue;
          if (!Array.isArray(cfg[_key])) {
            showBanner(_key + ' 必须是数组', 6000, true);
            return;
          }
          for (const _it of cfg[_key]) {
            // 后端 `_lst`：非字符串/空白项**跳过**（不拒），空 segs 也跳过
            if (typeof _it !== 'string' || !_it.trim()) continue;
            const _p = _normK(_it);
            const _sg = _p.split('/').filter(s => s && s !== '.');
            if (_p.charAt(0) === '/'
              || _sg.some(s => s === '..' || s.indexOf(':') >= 0)
              || (_key === 'exclude_names' && _sg.length > 1)) {
              showBanner(_key + ' 含非法路径：' + JSON.stringify(_it), 6000, true);
              return;
            }
          }
        }
        card._scopeCfg = Object.assign({
          name: '导入 ' + (cfg.name || '未命名'), mode: 'manual',
          arch: 'auto', dirs: {}, artifact_roots: [], exclude_names: [],
        }, cfg);
        renderSel();
        sel.value = 'cfg';
        _syncSelHead();
        // a570 对抗审计（P2·第五轮）：导入的 cfg 没有 state_counts，
        // _headCfg 会显示「白 0 · 全 0 · 不勾 0」。用 dirs 现算一份。
        _headCfg(_withCounts(card._scopeCfg),
          '导入的 JSON，建库成功后写入工程根');
        showBanner('已载入范围配置，点「建立索引」生效' +
          (_tmpDropped.length ? '；已忽略 ' + _tmpDropped.length +
            ' 个 tmp 类目录（建库时无条件跳过）：' +
            _tmpDropped.slice(0, 5).join('、') +
            (_tmpDropped.length > 5 ? ' 等' : '') : ''),
          _tmpDropped.length ? 7000 : 3500);
      }).catch(e => showBanner('读取失败: ' + e, 4000, true));
    };
    row.appendChild(bImp); row.appendChild(fi);
    // a570 对抗审计（P2·第十六轮）：只有导入没有导出——用户无法备份当前
    // 范围配置，只能去工程根翻 .fcpk-scope.json。
    // a570 对抗审计（P1·第十七轮）：导出必须**走后端落盘**。`<a download>`
    // 在壳内渲染层永远失败：init.js 捕获阶段对所有 a[href] 无条件
    // preventDefault（防就地导航）——会吞掉下载，前端却无条件弹「已导出」
    // （backend-log.js 已踩过同一个坑）。另外 status 下发的 scope 只是摘要
    // （无 dirs/arch/exclude_names，artifact_roots 还截断），拿它导出会丢配置。
    // 这里改走 POST /api/nav/scope_export：后端读真实配置存盘并回传路径。
    // 保存位置（2026-11-23 评审修正）：壳形态先经 fcShell.saveAs 弹保存框、
    // 把路径回传后端，取消即中止——此前后端去找已随 P4 删除的 pywebview
    // 保存框，从未弹出，每次导出都静默落桌面并按序号堆文件。
    const bExp = _h('button', '导出 JSON', false);
    bExp.className = 'btn ghost';
    bExp.style.cssText = 'padding:2px 10px;font-size:11px;';
    bExp.onclick = async () => {
      // a570 对抗审计（P2·第十八轮）：导出读的是**磁盘上已落盘的**配置，
      // 不是当前面板里尚未建库的改动——必须说清楚，否则用户以为导出的是
      // 刚导入/手选的那份。
      const _sel = sel.value || 'follow';
      if (_sel === 'cfg' || _sel === 'whitelist' || _sel === 'full') {
        showBanner('导出的是工程根已落盘的配置（当前下拉档位尚未建库），'
          + '若要导出本次选择请先建立索引', 7000, true);
      }
      let savePath = '';
      if (window.fcShell && typeof window.fcShell.saveAs === 'function') {
        try {
          savePath = await window.fcShell.saveAs({
            title: '导出范围配置',
            defaultName: 'fcpk-scope-'
              + ((path.replace(/[\\/]+$/, '').split(/[\\/]/).pop()) || 'project') + '.json',
            filters: [{ name: 'JSON', extensions: ['json'] }],
          });
        } catch (_) {
          showBanner('导出失败：无法打开保存框', 5000, true);
          return;
        }
        if (!savePath) return;   // 用户取消
      }
      showBanner('正在导出…', 1500);
      fetch('/api/nav/scope_export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: path, path: savePath }),
      }).then(r => r.json()).then(j => {
        if (j && j.ok) {
          showBanner('已导出到 ' + j.path + '，可再次「导入 JSON」还原', 7000);
        } else {
          showBanner('导出失败：' + ((j && j.err) || '未知错误'), 5000, true);
        }
      }).catch(() => showBanner('导出失败（后端无响应）', 4000, true));
    };
    row.appendChild(bExp);
    // 目录树多选
    const bPick = _h('button', '选择目录…', false);
    bPick.className = 'btn ghost';
    bPick.style.cssText = 'padding:2px 10px;font-size:11px;';
    bPick.onclick = () => _scopePick(path, res => {
      if (!res) return;
      const _n = Object.keys(res.dirs || {}).length;
      // a570：三态树返回 {dirs, artifact_roots, mode, rootDefault}，
      // 直接构成 v2 scope（后端 _norm_scope_v2 校验同形）
      card._scopeCfg = {
        version: 2,
        name: '手选 ' + _n + ' 个目录',
        mode: 'manual',
        arch: 'auto',
        dirs: res.dirs || {},
        artifact_roots: res.artifact_roots || [],
        exclude_names: [],
      };
      renderSel();
      sel.value = 'cfg';
      // a570 对抗审计（P1·第十五轮）：**不能**把 state_counts 写回
      // `_scopeCfg`——_scopeSel 原样把它当载荷，后端 `_norm_scope_v2` 会以
      // 「未知字段：state_counts」整单拒绝，建库必失败。只在展示处临时包裹。
      _headTxt('收录范围：三态树（白 ' +
        Object.values(res.dirs || {}).filter(v => v === 'whitelist').length +
        ' · 全 ' + Object.values(res.dirs || {}).filter(v => v === 'full').length +
        ' · 不勾 ' + Object.values(res.dirs || {}).filter(v => v === 'off').length +
        (res.artifact_roots && res.artifact_roots.length
          ? ' · 仅产物源 ' + res.artifact_roots.length : '') +
        '）——点「建立索引」生效');
      showBanner('已确认收录范围，点「建立索引」生效', 3500);
    });
    row.appendChild(bPick);
    // a571/a572：面板建好后自动开三态树。两种来源——
    //   ① 推荐确认弹窗的「调整范围…」-> `_pendingRec`（带推荐结果，免重扫）
    //   ② `ask_tier` 选「返回重新配置」-> `_openPickOnNext`（无结果，走一次扫描）
    // F1 / a573 #2：两者都必须**工程根匹配**才消费；且必须**各自独立**处理
    // ——原 `else if` 会让 `_pendingRec`（哪怕是别的工程的）把
    // `_openPickOnNext` 整个跳过，标志从此常驻并在下个工程误触发。
    const _autoOpen = () => {
      setTimeout(() => {
        if (card.isConnected && !document.getElementById('navScopePick')) {
          bPick.click();
        }
      }, 160);
    };
    let _consumed = false;   // 本次是否已自动开树（两者只取其一）
    if (_pendingRec) {
      const _pr = _pendingRec;
      _pendingRec = null;
      if (!_sameRoot(_pr.path, path)) {
        // 属于别的工程——丢弃，绝不套用
        showBanner('推荐结果已失效（工程已切换），请点「选择目录…」重新推荐',
                   4500, true);
      } else {
        _consumed = true;
        const _r = _pr.rec;
        setTimeout(() => {
          if (!card.isConnected) return;
          _scopePick(path, (res) => {
            if (!res) return;
            const _n = Object.keys(res.dirs || {}).length;
            card._scopeCfg = {
              version: 2, name: '手选 ' + _n + ' 个目录', mode: 'manual',
              arch: 'auto', dirs: res.dirs || {},
              artifact_roots: res.artifact_roots || [], exclude_names: [],
            };
            renderSel();
            sel.value = 'cfg';
            _syncSelHead();
            showBanner('已确认收录范围，点「建立索引」生效', 3500);
          }, (_r && _r.nodes && _r.nodes.length) ? _r : null);
        }, 160);
      }
    }
    // `if`（不是 else if）：与 `_pendingRec` 互不影响
    if (_openPickOnNext) {
      const _op = _openPickOnNext;
      _openPickOnNext = null;
      if (_sameRoot(_op.path, path) && !_consumed) {
        _consumed = true;
        _autoOpen();
      }
    }
    // 清除已存范围。a570 对抗审计：判据原为 source==='saved'（v1 时代），
    // v2 下 load_scope 只回 project / v1-deprecated / bad:*，该入口永不可见。
    if (sc && (sc.source === 'project' || sc.source === 'v1-deprecated'
      || String(sc.source || '').startsWith('bad:'))) {
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
            _scCleared = true;
            renderSel();
            sel.value = 'follow';
            _headTxt('收录范围：未配置（已清除已存范围）——小工程自动全量');
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
      // a570 对抗审计（P1·第十五轮）：只挑 v2 认的字段，避免任何展示用
      // 附加键（state_counts 等）随载荷发给后端导致整单被拒。
      if (v === 'cfg' && cfg) {
        return { scope: {
          version: 2, name: cfg.name, mode: cfg.mode || 'manual',
          arch: cfg.arch || 'auto', dirs: cfg.dirs || {},
          artifact_roots: cfg.artifact_roots || [],
          exclude_names: cfg.exclude_names || [],
        } };
      }
      // a570：v2 三档。全量/白名单档由后端按 mode 展开，不再带 include。
      if (v === 'full') return { scope: { version: 2, name: '全量',
        mode: 'full', arch: 'auto', dirs: {}, artifact_roots: [],
        exclude_names: [] } };
      if (v === 'whitelist') {
        // a570 对抗审计：原 `Object.assign({}, cfg, {mode:'whitelist'})` 保留
        // 了 dirs 里的显式 full/off 节点，实际是「白名单默认 + 手选覆盖」，
        // 与下拉文案承诺的纯白名单不一致。切档即清空显式覆盖。
        // a570 对抗审计（P2·第二十轮）：切「白名单」档必须**同时清空
        // artifact_roots**——只清 dirs 会让残留产物源目录（_inside_art）
        // 只收 .cmd/.o，其中源码被静默剪掉，与「纯白名单」文案不符。
        if (cfg) return { scope: Object.assign({}, cfg,
          { mode: 'whitelist', dirs: {}, artifact_roots: [] }) };
        return { scope_tier: 'whitelist' };   // 后端形态检测补产物源
      }
      // follow：读工程根 .fcpk-scope.json（v1 会被后端当无配置，走推荐器）
      return null;
    };
    return box;
  }

  // a398：目录树多选弹层——懒加载（SMB 大目录不整树拉）、勾父=子随父
  // 收录（继承态锁定）、最小顶集语义零歧义。
  // a398（审计#28）四修：顶层去重复渲染/折叠根隐藏子项/勾整根后子项
  // 继承锁定（inh!==null 判空串）/条目超限提示
  function _scopePick(root, cb, preset) {
    // a570 对抗审计（P2·第四轮）：单实例。原实现连点两次「选择目录…」会
    // 叠出两个弹层共享同一后端任务，关闭任一个都会取消该 root 的推荐；
    // 且切工程时旧弹层不会被 _closePanel 摘除，配置会静默落到旧 card。
    // a570 对抗审计（P1·第五轮）：移除旧弹层必须**同时停它的轮询**——
    // `_pollT` 是每个 _scopePick 各自的闭包变量，光 removeChild 会让旧
    // interval 继续每 600ms 打后端、并对 detached 节点 render，还把全局
    // 推荐槽占着（B 弹层只能看到「属于其他工程」）。
    // 旧弹层在创建时把清理函数挂到元素上，这里统一调用。
    const _prev = document.getElementById('navScopePick');
    if (_prev) {
      try { if (typeof _prev._cleanup === 'function') _prev._cleanup(true); }
      catch (_e) { /* 忽略 */ }
      if (_prev.parentNode) _prev.parentNode.removeChild(_prev);
    }
    const ov = document.createElement('div');
    ov.id = 'navScopePick';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:10001;display:flex;align-items:center;justify-content:center;';
    const card = _h('div');
    card.style.cssText = 'width:620px;max-width:96vw;padding:14px 16px;border-radius:12px;' +
      'background:var(--bg-panel);border:1px solid var(--border);box-shadow:0 12px 40px rgba(0,0,0,.45);';
    const t = _h('div', '收录范围配置');
    t.style.cssText = 'font-weight:600;margin-bottom:4px;';
    card.appendChild(t);
    const head2 = _h('div', '按目录设置收录方式：白名单（按编译产物精准推导）／全量（整树收录）／不勾（不收录）。' +
      '子目录默认继承最近的显式父级，可在子目录上覆盖。');
    head2.style.cssText = 'font-size:11px;color:var(--muted);margin-bottom:8px;line-height:1.6;';
    card.appendChild(head2);

    // ---- 顶部：推荐状态 + 操作 ----
    const top = _h('div');
    top.style.cssText = 'display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap;';
    const stLab = _h('span', '尚未推荐');
    stLab.style.cssText = 'flex:1;font-size:11px;color:var(--muted);min-width:160px;';
    const bRec = _h('button', '重新推荐', false);
    bRec.className = 'btn ghost';
    bRec.style.cssText = 'padding:2px 10px;font-size:11px;';
    const bExpand = _h('button', '全部展开', false);
    bExpand.className = 'btn ghost';
    bExpand.style.cssText = 'padding:2px 10px;font-size:11px;';
    top.appendChild(stLab); top.appendChild(bExpand); top.appendChild(bRec);
    card.appendChild(top);

    // 搜索框（G10 有上千目录，必需）
    const search = document.createElement('input');
    search.type = 'text';
    search.placeholder = '过滤目录名…';
    search.spellcheck = false;
    search.style.cssText = 'width:100%;margin-bottom:6px;padding:4px 8px;font-size:12px;' +
      'background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:6px;';
    card.appendChild(search);

    const tree = _h('div');
    tree.style.cssText = 'max-height:400px;overflow:auto;border:1px solid var(--border);' +
      'border-radius:8px;padding:6px;font-size:12px;';
    card.appendChild(tree);

    // 仅产物源汇总区
    const artBox = _h('div');
    artBox.style.cssText = 'margin-top:8px;padding:6px 8px;border:1px dashed var(--border);' +
      'border-radius:6px;font-size:11px;';
    card.appendChild(artBox);

    const foot = _h('div');
    foot.style.cssText = 'margin-top:10px;display:flex;gap:8px;justify-content:flex-end;align-items:center;';
    const cnt = _h('span', '');
    cnt.style.cssText = 'margin-right:auto;font-size:11px;color:var(--muted);';
    foot.appendChild(cnt);
    const bClr = _h('button', '全部清除');
    bClr.className = 'btn ghost';
    const bCancel = _h('button', '取消');
    bCancel.className = 'btn ghost';
    const bOk = _h('button', '建库');
    bOk.className = 'btn primary';
    foot.appendChild(bClr); foot.appendChild(bCancel); foot.appendChild(bOk);
    card.appendChild(foot);

    ov.appendChild(card);
    // a570 对抗审计（P2·第十六轮）：本弹层这一轮推荐任务的 run_id。关闭时
    // 带着它取消——同工程快速关/开时，旧弹层的 cancel 不会误杀新任务。
    let _runId = '';
    // a570 对抗审计：关闭弹层必须停轮询并请求后端取消——否则推荐任务
    // 会继续跑完（最长 300s/顶层目录），把槽霸占住让别的工程无法推荐，
    // 且 orphan interval 一直对已脱离 DOM 的节点执行 render。
    // a570 对抗审计（P2·第十七轮）：关闭时必须递增 epoch——否则启动 POST
    // 还在途时关闭，POST 返回后 `_myEpoch === _recEpoch` 成立，`_poll()` 会
    // 被重新拉起来（每 600ms 打后端、对已脱离 DOM 的树 render），而用户再
    // 没有取消入口，只能等后端守护超时。
    const _closePick = (doCancel) => {
      _stopPoll();
      _recEpoch++;
      if (doCancel && _runId) {
        _deadRuns.add(_runId);
        fetch('/api/nav/scope_recommend_cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: root, run_id: _runId }),
        }).catch(() => {});
      }
      if (ov.parentNode) ov.parentNode.removeChild(ov);
    };
    // 供「单实例守卫」在移除旧弹层时调用（停轮询 + 取消该 root 的任务）
    ov._cleanup = _closePick;
    ov.addEventListener('mousedown', e => {
      if (e.target === ov) _closePick(true);
    });
    document.body.appendChild(ov);

    // ---- 状态 ----
    // dirs: rel -> 'whitelist'|'full'|'off'  （只存显式节点）
    const dirs = {};
    const arts = new Set();        // artifact_roots（仅产物源）
    // a570 对抗审计（P1·第十六轮）：区分「用户手改」与「上一次推荐的产物」。
    // 原实现合并时拿整份 dirs 当手改，第二次推荐对已有目录全部失效且
    // banner 谎称「已保留 N 个手动目录」。_userSet 只记用户亲手写的键。
    const _userSet = new Set();
    // a572（F5）：用户**显式撤销**状态的节点（点当前生效值 = 回到继承）。
    // 与 `artsOff` 对称——没有它，下一次推荐会把用户刚撤销的状态静默写回。
    const dirsCleared = new Set();
    // a570 对抗审计（P2·第四轮）：记录用户**显式取消**的产物源。原只做
    // 「保留新增的」单向合并，用户取消勾选后被下一次推荐结果静默覆盖。
    const artsOff = new Set();
    // a570 对抗审计（P2·第十七轮）：区分「用户手勾的产物源」与「推荐产出的」
    const _userArts = new Set();
    const expanded = new Set(['']); // 已展开 rel
    const kids = {};               // rel -> {dirs:[{name,rel,sub}], files, truncated}
    const counts = {};             // rel -> {src,code,o,cmd,state,reason,warn}
    let rootDefault = 'whitelist';
    let recNodes = null;           // recommend_scope 返回的 nodes（含三元组）

    // 继承：向上找最近显式祖先
    // a570 对抗审计（P1）：dirs 的键一律 lower——后端 `_norm_dirs` 归一成
    // 小写、推荐器下发的也是小写，而树上 rel 来自磁盘（`Kernel`）。不统一
    // 会让推荐结果全部显示成「继承自根默认」，用户按所见确认却按 off/full
    // 剪枝。`kids` 仍用磁盘真实大小写（向后端请求目录时大小写要准）。
    const _k = (rel) => (rel || '').toLowerCase();
    const _ancState = (rel) => {
      let cur = _k(rel);
      while (true) {
        if (Object.prototype.hasOwnProperty.call(dirs, cur)) return { st: dirs[cur], from: cur };
        if (!cur) return { st: rootDefault, from: null };
        cur = cur.includes('/') ? cur.slice(0, cur.lastIndexOf('/')) : '';
      }
    };
    const _effState = (rel) => _ancState(rel).st;

    const _fmtN = (n) => {
      n = Number(n) || 0;
      if (n >= 1e4) return (n / 1e4).toFixed(1) + 'W';
      if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
      return String(n);
    };

    // 2026-11-23 总审计 a684-A5：预估文件数按**当前配置的生效状态**算。
    // 原实现把推荐节点的 code 全加——推荐 rootfs:off（3.9 万文件）时仍显示
    // 「预估 12W 文件」，建库后远小于预期。一级子目录能扣的也扣：off 顶层下
    // 显式勾选的子目录加回、live 顶层下 off 的子目录扣除（与 _keep_dir 的
    // 下钻规则同向）。白名单档实际只收编译过的，这里的 code 仍是上界。
    const _estFiles = () => (recNodes || []).reduce((a, n) => {
      if (!n || !n.rel) return a;
      const topOff = _effState(n.rel) === 'off';
      let v = topOff ? 0 : (Number(n.code) || 0);
      for (const s of (n.subs || [])) {
        if (!s || s.name === '__root__') continue;
        const c = Number(s.code) || 0;
        const subOff = _effState(n.rel + '/' + s.name) === 'off';
        if (topOff && !subOff) v += c;
        else if (!topOff && subOff) v -= c;
      }
      return a + Math.max(0, v);
    }, 0);

    const _syncCounts = () => {
      let wl = 0, fu = 0, of = 0;
      // 统计「显式节点 + 根默认」的分布（粗略：以显式节点计）
      for (const k in dirs) {
        if (dirs[k] === 'whitelist') wl++;
        else if (dirs[k] === 'full') fu++;
        else of++;
      }
      const files = _estFiles();
      cnt.textContent = '白 ' + wl + ' · 全 ' + fu + ' · 不勾 ' + of +
        (files ? ' · 预估 ' + _fmtN(files) + ' 文件' : '') +
        (arts.size ? ' · 仅产物源 ' + arts.size : '');
    };

    const _syncArtBox = () => {
      artBox.textContent = '';
      if (!arts.size) {
        artBox.style.display = 'none';
        return;
      }
      artBox.style.display = '';
      artBox.append('仅产物源（只读 .cmd/.o，不收录源码）：');
      const sp = _h('span', [...arts].sort().join('、'));
      sp.style.cssText = 'color:var(--accent);margin-left:4px;';
      artBox.appendChild(sp);
    };

    // 三态按钮组（互斥）
    const _stateBtns = (rel, current, onSet) => {
      const g = _h('span');
      g.style.cssText = 'display:inline-flex;gap:2px;flex:none;';
      [['whitelist', '白'], ['full', '全'], ['off', '不']].forEach(([v, label]) => {
        const b = _h('button', label, false);
        b.className = 'btn ghost';
        b.style.cssText = 'padding:0 6px;font-size:10px;line-height:16px;' +
          (current === v ? 'background:var(--accent);color:var(--bg);border-color:var(--accent);font-weight:600;' : '');
        b.title = v === 'whitelist' ? '白名单：按编译产物精准收录'
          : v === 'full' ? '全量：该子树所有代码文件都收录'
            : '不勾：该子树不进索引';
        b.onclick = (e) => { e.stopPropagation(); onSet(v); };
        g.appendChild(b);
      });
      return g;
    };

    const render = () => {
      _syncCounts();
      _syncArtBox();
      tree.textContent = '';
      const kw = (search.value || '').trim().toLowerCase();

      const mkRow = (rel, name, sub, depth, noState) => {
        // a570 对抗审计：过滤必须看**整棵子树**（原只看本行名+一级子目录名，
        // 深层匹配 a/b/foo 而 a/b 未展开时永远搜不到）。显式节点里也有名字。
        if (kw && rel) {
          const selfHit = name.toLowerCase().indexOf(kw) >= 0;
          const kidHit = kids[rel] && kids[rel].dirs.some(
            d => d.name.toLowerCase().indexOf(kw) >= 0);
          // a570 对抗审计（P1·第四轮）：rel 是磁盘大小写，dirs 的键是
          // lower——必须先归一再匹配，否则含大写的目录（Kernel/Src/
          // MDK-ARM）的深层命中全部失效。
          const rl = _k(rel);
          const subHit = Object.keys(dirs).some(
            k => k.indexOf(rl === '' ? '' : rl + '/') === 0 &&
              k.split('/').pop().toLowerCase().indexOf(kw) >= 0);
          if (!selfHit && !kidHit && !subHit) return;
        }
        const eff = _effState(rel);
        const rk = _k(rel);       // dirs 的键一律 lower
        const own = Object.prototype.hasOwnProperty.call(dirs, rk);
        const r = _h('div');
        r.style.cssText = 'display:flex;align-items:center;gap:4px;padding:2px 0 2px ' + (depth * 14) + 'px;';
        // 展开三角
        const ex = _h('button', expanded.has(rel) ? '▾' : '▸', false);
        ex.style.cssText = 'border:none;background:none;color:var(--muted);cursor:pointer;' +
          'padding:0 2px;font-size:10px;width:14px;flex:none;' + (sub ? '' : 'visibility:hidden;');
        ex.onclick = (e) => { e.stopPropagation(); _toggleExpand(rel); };
        r.appendChild(ex);
        // 目录名
        const lab = _h('span', name);
        lab.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;' +
          'white-space:nowrap;cursor:pointer;' +
          (own ? '' : 'color:var(--muted);');
        lab.title = own ? rel : (rel + '（继承自 ' + (_ancState(rel).from || '根默认') + '）');
        // 注：_stateBtns 的 rel 参数只用于回传给 onSet，已统一 lower
        lab.onclick = () => _toggleExpand(rel);
        r.appendChild(lab);
        // 三元组数据（若已推荐）
        const c = counts[rel] || counts[rk];
        if (c) {
          const d = _h('span',
            _fmtN(c.src) + '源 · ' + _fmtN(c.o) + 'o · ' + _fmtN(c.cmd) + 'cmd');
          d.style.cssText = 'flex:none;font-size:10px;color:var(--muted);font-family:var(--font-mono);' +
            'margin-left:6px;';
          if (c.warn) d.style.color = 'var(--neon-orange,#d29922)';
          r.appendChild(d);
        }
        // 三态按钮（根行不放——后端 _norm_dirs 拒绝空键，根默认态由
        // mode 表达；a570 对抗审计：原根行也挂按钮，点「全」会提交
        // dirs[''] 让后端建库直接失败）
        if (!noState) {
          r.appendChild(_stateBtns(rk, own ? dirs[rk] : eff, (v) => {
            // a570 对抗审计（P2·第四轮）：继承态下点当前生效值 = 回到继承，
            // 不要凭空造一个显式节点（否则父级改动不再影响它，且无视觉反馈）。
            // a570 对抗审计（P2·第五轮）：这是纯 no-op 点击，**不要**继续
            // 走下面的 arts 清理——原实现会把它塞进 artsOff 并静默清掉
            // 子目录的「仅产物源」勾选。
            const _backInherit = () => {
              // a570 对抗审计（P2·第十七轮）：回继承必须同时清掉「仅产物源」
              // 标记——否则载荷残留 artifact_roots:[该目录] 而该目录已不是
              // off，复选框 disabled 但 checked，用户无法取消，且随建库落盘
              // 成一条永不生效的死配置。
              delete dirs[rk];
              _userSet.delete(rk);
              // a572（F5）：记下「用户要这个节点回到继承」，下次推荐不许写回
              if (rk) dirsCleared.add(rk);
              if (arts.delete(rk)) { /* 已从产物源移除 */ }
              _userArts.delete(rk);
              artsOff.delete(rk);
              // a570 对抗审计（P2·第十八轮）：**后代**的仅产物源标记也要清
              // ——父目录回继承后，后代不再是 off 区，那条 artifact_roots
              // 永不生效且用户无法取消（与 set 分支的后代清理对称）。
              // a570 对抗审计（P1·第二十轮）：根行 rk === '' 时 `rk + '/'`
              // 是 "/"，而 artifact_roots 都是相对路径 —— 前缀匹配全部落空，
              // 后代「仅产物源」标记留下且用户无法取消（整棵子树源码被
              // _inside_art 静默剪掉）。空 rk 表示「整棵树」，匹配全部。
              const pfx = rk ? rk + '/' : '';
              for (const a of [...arts]) {
                if (!pfx || a.indexOf(pfx) === 0) {
                  arts.delete(a); _userArts.delete(a); artsOff.add(a);
                }
              }
              render();
            };
            const _noop = (!own && eff === v);
            if (_noop) {
              // a570 对抗审计（P2·第十九轮）：本行没有显式节点、点的又是
              // 当前生效值——这是**纯 no-op**，绝不能走 _backInherit（那会
              // 清掉后代的「仅产物源」标记，用户没表达任何意图）。原实现
              // 复用 _backInherit，把后代 arts 静默清空并写进 artsOff。
              render();
              return;
            }
            if (own && dirs[rk] === v) {
              // a570 对抗审计（P2·第十六轮）：own 且点自己当前值 = 回到继承
              // ——原实现无任何路径能删显式节点，节点永久脱离父级继承
              _backInherit();
              return;
            }
            dirs[rk] = v;
            _userSet.add(rk);
            dirsCleared.delete(rk);   // a572（F5）：用户重新显式设置，撤销「已清除」
            // 仅产物源只在 off 下有意义；切走时移除。a570 对抗审计：
            // 还要清掉**后代**的标记——原只删本节点，父级改白/全后
            // 子目录留着「灰掉但仍勾选」的矛盾态，且载荷仍把它写进
            // artifact_roots。
            if (v !== 'off') {
              // a570 对抗审计（P1·第二十轮）：根行（rk === ''）改成白/全时
              // 表示「整棵树都不再是 off 区」——后代所有「仅产物源」标记都
              // 失效，必须全清（`rk + '/'` 对空键给的是 "/"，匹配不到任何
              // 相对路径）。空 rk 也不要往 artsOff 里塞空串。
              const pfx = rk ? rk + '/' : '';
              if (rk) {
                arts.delete(rk);
                _userArts.delete(rk);
                artsOff.add(rk);
              }
              for (const a of [...arts]) {
                if (!pfx || a.indexOf(pfx) === 0 || a === rk) {
                  arts.delete(a); _userArts.delete(a); artsOff.add(a);
                }
              }
            }
            render();
          }));
          // 仅产物源复选框（只在 off 态可用）。a570 第十九轮：根行（rk=""）
          // 不放——artifact_roots 的空段会被后端 `_lst` 拒绝。
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = arts.has(rk);
          cb.disabled = eff !== 'off';
          cb.title = eff !== 'off' ? '「仅产物源」只在「不勾」状态下可用'
            : '该目录不收录源码，但仍扫描其中的 .cmd/.o 用于白名单推导';
          cb.style.cssText = 'flex:none;margin-left:4px;' + (eff !== 'off' ? 'opacity:.35;' : '');
          cb.onclick = (e) => e.stopPropagation();
          cb.onchange = () => {
            if (cb.checked) { arts.add(rk); _userArts.add(rk); artsOff.delete(rk); }
            else { arts.delete(rk); _userArts.delete(rk); artsOff.add(rk); }
            _syncArtBox(); _syncCounts();
          };
          if (rk) r.appendChild(cb);
        }
        tree.appendChild(r);
        if (expanded.has(rel)) {
          const k = kids[rel];
          if (!k) {
            const l = _h('div', '⋯');
            l.style.cssText = 'color:var(--muted);font-size:11px;padding-left:' + ((depth + 1) * 14) + 'px;';
            tree.appendChild(l);
            return;
          }
          for (const d of k.dirs) mkRow(d.rel, d.name, d.sub, depth + 1);          if (!k.dirs.length || k.truncated) {
            const emp = _h('div', k.truncated ? '（子目录过多，仅显示前 800 个）' : '（无子目录）');
            emp.style.cssText = 'color:var(--muted);font-size:11px;padding-left:' + ((depth + 1) * 14) + 'px;';
            tree.appendChild(emp);
          }
        }
      };
      // 根行（整个目录）。a570 对抗审计（P2·第十九轮）：后端现已接受根键
      // `""`（表达「工程根自身」的收录状态）——没有它，根直下源码
      // （rootfile.c / app.py）在建库时会被根默认 whitelist 排掉，面板
      // 却只显示「白 0 · 全 1」，用户完全看不出漏了文件。这里挂上三态按钮。
      const rootName = root.split(/[\\/]/).filter(Boolean).pop() || root;
      mkRow('', rootName, true, 0, false);
    };

    // a570 对抗审计（P2·第四轮）：把「按 recNodes 铺某层的子目录计数」抽成
    // 独立函数——推荐结果到达后对**已展开**的层重新铺一遍，否则那层的
    // 三元组列会被 counts 清空后永久消失（收起再展开也不恢复）。
    const _fillSubs = (rel) => {
      if (!recNodes) return;
      const _byRel = {};
      for (const n of recNodes) _byRel[n.rel] = n;
      const _curTop = (rel || '').toLowerCase();
      const _topNode = _byRel[_curTop];
      if (!_topNode || !_topNode.subs) return;
      for (const s of _topNode.subs) {
        if (s.name === '__root__') continue;
        counts[(_curTop + '/' + s.name).toLowerCase()] = {
          src: s.src, code: s.code, o: s.o, cmd: s.cmd, warn: false,
        };
      }
    };

    const _toggleExpand = async (rel) => {
      if (expanded.has(rel)) { expanded.delete(rel); render(); return; }
      if (!kids[rel]) {
        render();   // 先显示 ⋯
        try {
          const rj = await (await fetch('/api/nav/scope_tree?root=' +
            encodeURIComponent(root) + '&rel=' + encodeURIComponent(rel))).json();
          if (!rj.ok) throw new Error(rj.err || '');
          kids[rel] = { dirs: rj.dirs || [], files: rj.files || 0,
                        truncated: !!rj.truncated };
          // 懒加载同时把该层子目录的推荐数据挂上（recommend 只到一级）
          _fillSubs(rel);
        } catch (e) {
          showBanner('目录读取失败: ' + e, 3000, true);
          render();
          return;
        }
      }
      expanded.add(rel);
      render();
    };

    // ---- 推荐 ----------
    let _pollT = null;
    // a570 对抗审计（P2·第十六轮）：推荐在途时用户点「全部清除」，结果到达
    // 会把树重新填满且无提示——用户以为已清空，建库却按推荐收全树。
    // 每次推荐带 epoch，清除动作递增 epoch 使在途结果作废。
    let _recEpoch = 0;
    // a570 对抗审计（P2·第十八/十九轮）：`_deadRuns` 是模块级 Set（文件
    // 顶部声明）——必须跨弹层共享，否则关掉 A 再开 B 时 B 会接管一个
    // 已被取消的任务，用户没做任何操作却看到「推荐失败：已取消」。
    const _stopPoll = () => { if (_pollT) { clearInterval(_pollT); _pollT = null; } };
    const _setBusy = (busy, txt) => {
      bRec.disabled = busy;
      bOk.disabled = busy;
      stLab.textContent = txt || '';
    };
    const _runRecommend = async (force) => {
      const _myEpoch = ++_recEpoch;
      _setBusy(true, '推荐分析中…（首次需扫描全树，约 20~60 秒）');
      try {
        const r = await fetch('/api/nav/scope_recommend', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: root, force: !!force }),
        }).then(x => x.json());
        if (_myEpoch !== _recEpoch) {
          // 期间被「全部清除」或弹层关闭作废；若本次启动真的成功，
          // 必须把后端任务取消掉，别白占全局推荐槽。
          if (r.ok && r.run_id) {
            _deadRuns.add(r.run_id);
            fetch('/api/nav/scope_recommend_cancel', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ root: root, run_id: r.run_id }),
            }).catch(() => {});
          }
          return;
        }
        if (!r.ok) {
          if (r.err && r.err.indexOf('进行中') >= 0) {
            // a570 对抗审计（P2·第十八轮）：快速双击「选择目录…」时，
            // 弹层 1 的迟到成功会取消它自己刚启动的任务，弹层 2 收到
            // 「进行中」若直接接管，就会被那次取消打成「推荐失败：已取消」
            // ——用户没做任何取消动作。已作废的 run_id 不接管。
            if (r.run_id && _deadRuns.has(r.run_id)) {
              _setBusy(false, '上一个推荐任务正在退出——请再点一次「重新推荐」');
              return;
            }
            _poll(_myEpoch);
            return;
          }
          _setBusy(false, '推荐启动失败：' + (r.err || ''));
          return;
        }
        _runId = r.run_id || '';
        _poll(_myEpoch);
      } catch (e) {
        // a570 对抗审计（P2·第十八轮）：旧请求的 reject 迟到时不能改写
        // 新推荐的状态栏/按钮（否则用户可点「建库」按不完整范围落库）。
        if (_myEpoch !== _recEpoch) return;
        _setBusy(false, '推荐启动失败：' + e);
      }
    };
    let _pollErr = 0;
    const _poll = (_myEpoch) => {
      _stopPoll();
      _pollErr = 0;
      _pollT = setInterval(async () => {
        if (_myEpoch !== _recEpoch) { _stopPoll(); return; }
        try {
          const r = await fetch('/api/nav/scope_recommend_poll?root=' +
            encodeURIComponent(root)).then(x => x.json());
          // a570 对抗审计（P2·第十七轮）：await 期间用户可能点了「全部清除」
          // （_recEpoch++）——只在 await 之前查会漏掉这次响应，结果照旧
          // 填满树。这里补第二次比对，作废的响应直接丢弃。
          if (_myEpoch !== _recEpoch) { _stopPoll(); return; }
          if (!r.ok) {
            // a570 对抗审计（P2·第五轮）：响应体 ok=false（版本错配的
            // 全局 404/500 JSON）也要计入连续失败——原实现先清零再 return，
            // 20 次上限永远触发不了，UI 永久 busy。
            _pollErr++;
            if (_pollErr >= 20) {
              _stopPoll();
              _setBusy(false, '推荐轮询失败（后端返回错误）——请点「重新推荐」重试');
            }
            return;
          }
          _pollErr = 0;      // 正常响应才清零
          // a570 对抗审计：槽是全局的，若结果属于别的工程必须停——
          // 否则会把 A 的 dirs 当 B 的建库范围（跨工程静默剪错目录）
          if (r.mine === false) {
            _stopPoll();
            _setBusy(false, '推荐任务属于其他工程（' + (r.root || '') +
              '），请稍后重试');
            return;
          }
          if (r.running) {
            if (!_runId && r.run_id) _runId = r.run_id;   // 接管别人同 root 的在途任务
            stLab.textContent = '推荐分析中：' + (r.cur || r.phase || '') +
              (r.total ? ' (' + Math.min(r.total, (r.percent || 0) / 100 * r.total | 0) + '/' + r.total + ')' : '');
            return;
          }
          _stopPoll();
          if (!r.ok_done) {
            _setBusy(false, '推荐失败：' + (r.err || ''));
            return;
          }
          const res = r.result || {};
          _applyRec(res);
        } catch (_) {
          // a570 对抗审计（P2·第三轮）：持续失败会永久 busy——加计数上限，
          // 超限后恢复按钮并提示用户重试。
          // a570 对抗审计（P2·第四轮）：必须是**连续**失败（成功即清零），
          // 原按累计算，间歇抖动累计 20 次就会把正常任务判成失败。
          _pollErr++;
          if (_pollErr >= 20) {
            _stopPoll();
            _setBusy(false, '推荐轮询失败（网络/后端异常）——请点「重新推荐」重试');
          }
        }
      }, 600);
    };
    // a571：把推荐结果应用到树（从 _poll 里提出，供「确认弹窗 -> 调整范围」
    // 直通复用——那条路径已拿到推荐结果，不该再花 20~60 秒重扫一遍）。
    const _applyRec = (res) => {
      recNodes = res.nodes || [];
      // 应用推荐（原地替换，dirs 是 const——a570 对抗审计 P0：
      // 原写 `dirs = res.dirs || {}` 必抛 TypeError，且被 catch 吞掉，
      // 推荐结果永远应用不到树、busy 状态永不恢复）
      // a570 对抗审计（P1·第十六轮）：只认 _userSet 里用户亲手写的键。
      const _manual = {};
      for (const k of _userSet) {
        if (Object.prototype.hasOwnProperty.call(dirs, k)) _manual[k] = dirs[k];
      }
      // a570 对抗审计（P2·第十七轮）：产物源也要区分「用户手勾」与推荐产物。
      const _manualArts = new Set();
      for (const a of arts) {
        if (_userArts.has(a)) _manualArts.add(a);
      }
      for (const k in dirs) delete dirs[k];
      Object.assign(dirs, res.dirs || {}, _manual);
      // a572（F5）：用户显式撤销过的节点，推荐结果不许再填回来。
      for (const k of dirsCleared) delete dirs[k];
      rootDefault = res.mode === 'full' ? 'full' : 'whitelist';
      for (const k of Object.keys(_manual)) _userSet.add(k);
      arts.clear();
      for (const a of res.artifact_roots || []) {
        if (a) arts.add(a);
      }
      for (const a of _manualArts) arts.add(a);
      for (const a of artsOff) arts.delete(a);
      if (Object.keys(_manual).length) {
        showBanner('推荐完成；你手动设置过的 ' + Object.keys(_manual).length +
          ' 个目录已保留', 4500);
      }
      // 计数
      for (const key in counts) delete counts[key];
      for (const n of recNodes) {
        counts[(n.rel || '').toLowerCase()] = {
          src: n.src, code: n.code, o: n.o, cmd: n.cmd,
          warn: !!n.warn, reason: n.reason || '',
        };
      }
      // a570 对抗审计（P2·第四轮）：已展开的层要重新铺 subs，否则
      // counts 被清空后那些行的三元组列永久消失。
      for (const _r of Object.keys(kids)) _fillSubs(_r);
      _setBusy(false, '推荐完成（' + (res.scan_seconds ? res.scan_seconds + 's' : '') + '）：' +
        (res.detected && res.detected.length ? '检测到 ' + res.detected.join('、') : '未识别出特定构建系统'));
      render();
    };

    bRec.onclick = () => _runRecommend(true);
    bExpand.onclick = async () => {
      // 只展开已加载的一层；不递归（大工程防爆）
      // a570 对抗审计：expanded 初值含 ''（根），原逻辑先 add 全部再把根
      // 交给 _toggleExpand，后者见根已展开就去**收起**——按钮实际做反了。
      // 根未加载时先清掉展开标记再 toggle（让它走加载分支），然后展开其余。
      if (!kids['']) {
        expanded.delete('');
        await _toggleExpand('');
      }
      for (const k of Object.keys(kids)) {
        if (!expanded.has(k)) expanded.add(k);
      }
      // a570 对抗审计（P2·第十六轮）：根层加载失败时不能无条件标成已展开——
      // 否则每帧 render 都走「!k → ⋯」分支，根行永久假加载态，点一次只收起。
      if (kids[''] && !expanded.has('')) expanded.add('');
      render();
    };

    search.oninput = () => render();
    bClr.onclick = () => {
      for (const k in dirs) delete dirs[k];
      _userSet.clear();
      // a570 对抗审计（P2·第十六轮）：artsOff 必须一起清——用户点「全部清除」
      // 就是从头再来，残留的显式取消会在下一次推荐到达时静默删掉新结果。
      arts.clear();
      _userArts.clear();
      artsOff.clear();
      dirsCleared.clear();   // a572（F5）：与 artsOff 同理，全部清除即从头再来
      // 在途推荐结果作废（否则几秒后树被重新填满，用户以为清空失败），
      // 同时把后端任务取消掉，别白占全局推荐槽。
      _recEpoch++;
      _stopPoll();
      if (_runId) {
        _deadRuns.add(_runId);
        fetch('/api/nav/scope_recommend_cancel', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: root, run_id: _runId }),
        }).catch(() => {});
      }
      _setBusy(false, '已清除（在途推荐结果不再回填）');
      render();
    };
    bCancel.onclick = () => _closePick(true);
    bOk.onclick = () => {
      // 建库要用的推荐结果已拿到，任务本身无需再跑
      _closePick(true);
      const dirsCopy = Object.assign({}, dirs);
      const artsCopy = [...arts].sort();
      cb({ dirs: dirsCopy, artifact_roots: artsCopy,
           mode: 'manual', rootDefault });
    };

    // 首次打开：直接跑推荐（用户定调：工具先配好，用户确认即可）
    // a570 对抗审计（P1）：原实现只 render + 跑推荐，根层从未加载——
    // 树里只有根行「⋯」假加载态，用户看到空树。先加载根层再推荐。
    // 注意：expanded 初值含 ''（根），直接 _toggleExpand('') 会走「收起」
    // 分支。必须像 bExpand 那样先删标记再展开，才会真正加载根层。
    expanded.delete('');
    render();
    _toggleExpand('').catch(() => {});
    // a571：带预置推荐结果进来（「确认弹窗 -> 调整范围」路径）就直接应用，
    // 省掉 20~60 秒重扫。无预置则照旧跑推荐。
    if (preset && preset.nodes && preset.nodes.length) {
      _applyRec(preset);
    } else {
      _runRecommend(false);
    }
  }

  async function _renderState(card, path, j, st) {
    const btns = card.querySelector('div:last-child');
    if (!j || !j.ok) {
      st.textContent = '探测失败：' + ((j && j.err) || '网络错误');
      // a572（F1）：早退也必须清，否则跨工程泄漏
      // a576（第 1 轮审计·低-3）：两个挂起标志必须**对称**清理——原只清
      // `_pendingRec`，`_openPickOnNext` 会滞留到下一个任意工程的 _scopeRow。
      _dropPendingRec(path);
      _dropOpenPick(path);
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
        // a572（F1）/ a576 低-3：同上，两个标志对称清
        _dropPendingRec(path);
        _dropOpenPick(path);
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
      // a570 对抗审计：meta.scope 已是 v2（version/name/mode/source/dirs/…），
      // 原按 v1 读 tier/include 会永远显示「（，0 目录）」。
      const _scn = (m.scope.dirs && Object.keys(m.scope.dirs).length) || 0;
      st.appendChild(_h('div', '本次建库范围：' + m.scope.name +
        '（' + (m.scope.mode || m.scope.source || '') + '，' +
        _scn + ' 目录）——换范围用下方控件重选后重建'));
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
      _closePanel(true, path, true);
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
      _closePanel(true, path, true);
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
  function _askTierDialog(info, txt, path, rid) {
    // a572（内网评审 F4）：单实例守卫——重开面板会新建一份 _renderProgress
    // （原 `_tierAsked` 是它的闭包局部），同一个 id 会叠出多个元素，而清理用
    // getElementById 只删文档序第一个，其余成为 z=10050 的全屏孤儿遮罩。
    const _prev = document.getElementById('navTierDialog');
    if (_prev && _prev.parentNode) _prev.parentNode.removeChild(_prev);
    const ov = document.createElement('div');
    ov.id = 'navTierDialog';   // a432：可被 _closePanel 统一清理
    // a572（F2）：记录所属工程根——关「别的」工程的面板时不许动这个弹窗，
    // 更不许替它发 /api/nav/cancel（那会取消别人的建库任务）。
    ov.dataset.root = path || '';
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
      ['reconfigure', '返回重新配置收录范围',
       '回到三态树，按目录重新指定白名单/全量/不勾（适合「这个工程本身配错了」）'],
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
        // a572（F3）：回传任务凭证，后端校验不匹配则 409（残留弹窗作答）
        body: JSON.stringify({ choice, run_id: rid }),
      }).then(r => r.json().then(j => ({ ok: r.ok, j })))
        .then(({ ok, j }) => {
          if (ok && j && j.ok) {
            if (txt) txt.textContent = '已选择：' +
              ({ full: '全量收源码', whitelist: '只收白名单',
                 reconfigure: '重新配置收录范围', cancel: '放弃建库' }[choice] || choice);
            // a572（B10）：保留 3 秒，别让下一轮 poll 立刻覆写掉
            _txtHoldUntil = Date.now() + 3000;
          } else if (txt) {
            txt.textContent = '选择未生效（' + ((j && (j.err || j.msg)) || '任务已结束') + '）';
          }
        })
        .catch(() => { if (txt) txt.textContent = '提交失败（网络异常）'; });
    }
  }

  // a571（用户定调：首次建库必须弹窗二次确认，用户能决定增删哪些目录）：
  // 推荐器结果确认弹窗。列出三态分布 + 每个顶层目录的状态/三元组/理由，
  // 用户可直接「按推荐建库」，或「调整范围…」——后者走 reconfigure 取消路径，
  // 直接打开已有的三态树（_scopePick），用户在树上改完再点「建立索引」。
  function _askScopeDialog(rec, txt, path, rid) {
    // a572（内网评审 F4）：单实例守卫，同上。
    const _prev = document.getElementById('navScopeConfirm');
    if (_prev && _prev.parentNode) _prev.parentNode.removeChild(_prev);
    const ov = document.createElement('div');
    ov.id = 'navScopeConfirm';
    // a572（F2）：记录所属工程根，供 _closePanel 判定归属。
    ov.dataset.root = path || '';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);' +
      'z-index:10050;display:flex;align-items:center;justify-content:center;';
    const card = document.createElement('div');
    card.className = 'dd-cur';
    card.style.cssText = 'width:680px;max-width:94vw;max-height:86vh;display:flex;' +
      'flex-direction:column;padding:18px 20px;border-radius:12px;' +
      'background:var(--bg-panel);border:1px solid var(--border);' +
      'box-shadow:0 12px 40px rgba(0,0,0,.5);';
    const title = _h('div', '请确认收录范围');
    title.style.cssText = 'font-size:14px;font-weight:600;margin-bottom:8px;';
    card.appendChild(title);
    const nodes = (rec && rec.nodes) || [];
    const _cnt = { whitelist: 0, full: 0, off: 0 };
    for (const n of nodes) if (_cnt[n.state] !== undefined) _cnt[n.state]++;
    const sub = _h('div');
    sub.style.cssText = 'font-size:11.5px;color:var(--muted);' +
      'margin-bottom:12px;line-height:1.65;';
    sub.append('该工程尚无收录范围配置，已按编译产物分析出下面这份推荐——');
    // 统计行（色彩与下方徽标一致，用户一眼对上）
    const _stat = _h('div');
    _stat.style.cssText = 'margin-top:7px;display:flex;gap:14px;' +
      'font-size:12px;font-family:var(--font-mono);';
    [['whitelist', '白名单'], ['full', '全量'], ['off', '不勾']].forEach(
      ([k, lab]) => {
        const s0 = _h('span');
        const _c = { whitelist: 'var(--accent)', full: '#3fb950',
                     off: 'var(--muted)' }[k];
        s0.append(_h('span', lab));
        const v = _h('b', String(_cnt[k]));
        v.style.cssText = 'color:' + _c + ';margin-left:5px;font-size:13px;';
        s0.appendChild(v);
        _stat.appendChild(s0);
      });
    if (rec && rec.scan_seconds) {
      const t = _h('span', '分析耗时 ' + rec.scan_seconds + ' 秒');
      t.style.cssText = 'margin-left:auto;color:var(--muted);opacity:.75;';
      _stat.appendChild(t);
    }
    sub.appendChild(_stat);
    card.appendChild(sub);
    // 目录清单（可滚动）
    const list = document.createElement('div');
    list.style.cssText = 'flex:1;overflow:auto;border:1px solid var(--border);' +
      'border-radius:8px;font-size:12px;min-height:140px;' +
      'background:rgba(0,0,0,.18);';
    // 表头（与下面的列对齐）
    const _hdr = document.createElement('div');
    _hdr.style.cssText = 'display:grid;' +
      'grid-template-columns:minmax(110px,1.1fr) 76px minmax(190px,1.6fr);' +
      'gap:10px;padding:5px 10px;font-size:10.5px;letter-spacing:.4px;' +
      'color:var(--muted);text-transform:uppercase;' +
      'border-bottom:1px solid var(--border);' +
      'position:sticky;top:0;background:var(--bg-panel);z-index:1;';
    _hdr.appendChild(_h('span', '目录'));
    _hdr.appendChild(_h('span', '收录'));
    _hdr.appendChild(_h('span', '统计 / 依据'));
    list.appendChild(_hdr);
    const _lbl = { whitelist: '白名单', full: '全量', off: '不勾' };
    // 徽标底色：低透明度填充 + 同色文字，比纯色字更易扫读
    const _badge = {
      whitelist: 'color:var(--accent);background:rgba(88,166,255,.13);' +
        'border:1px solid rgba(88,166,255,.35);',
      full: 'color:#3fb950;background:rgba(63,185,80,.13);' +
        'border:1px solid rgba(63,185,80,.35);',
      off: 'color:var(--muted);background:rgba(128,128,128,.12);' +
        'border:1px solid rgba(128,128,128,.28);',
    };
    const _fmt = (n) => {
      n = Number(n) || 0;
      if (n >= 1e4) return (n / 1e4).toFixed(1) + '万';
      if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
      return String(n);
    };
    nodes.forEach((n, i) => {
      const row = _h('div');
      row.style.cssText = 'display:grid;' +
        'grid-template-columns:minmax(110px,1.1fr) 76px minmax(190px,1.6fr);' +
        'gap:10px;align-items:baseline;padding:6px 10px;' +
        (i % 2 ? 'background:rgba(255,255,255,.022);' : '');
      const nm = _h('span', (n.name || n.rel || ''));
      nm.style.cssText = 'font-family:var(--font-mono);overflow:hidden;' +
        'text-overflow:ellipsis;white-space:nowrap;';
      nm.title = (n.name || n.rel || '');
      const stt = _h('span', _lbl[n.state] || n.state);
      stt.style.cssText = 'justify-self:start;font-size:10.5px;font-weight:600;' +
        'padding:1px 7px;border-radius:9px;' + (_badge[n.state] || '');
      // 右侧：主行统计 + 次行依据
      const right = _h('span');
      right.style.cssText = 'min-width:0;';
      const _num = _h('span',
        _fmt(n.src) + ' 源 · ' + _fmt(n.o) + ' 单元 · ' + _fmt(n.cmd) + ' cmd');
      _num.style.cssText = 'font-family:var(--font-mono);font-size:11.5px;';
      if (n.warn) _num.style.color = 'var(--neon-orange,#d29922)';
      right.appendChild(_num);
      if (n.reason) {
        const rs = _h('span', n.reason);
        rs.style.cssText = 'display:block;color:var(--muted);opacity:.8;' +
          'font-size:10.5px;margin-top:1px;overflow:hidden;' +
          'text-overflow:ellipsis;white-space:nowrap;';
        rs.title = n.reason;
        right.appendChild(rs);
      }
      row.appendChild(nm); row.appendChild(stt); row.appendChild(right);
      list.appendChild(row);
    });
    card.appendChild(list);
    // 按钮
    const btns = _h('div');
    btns.style.cssText = 'margin-top:12px;display:flex;gap:8px;justify-content:flex-end;';
    const bCancel = _h('button', '放弃建库');
    bCancel.className = 'btn ghost';
    bCancel.onclick = () => { ov.remove(); _post('cancel'); };
    const bEdit = _h('button', '调整范围…');
    bEdit.className = 'btn ghost';
    bEdit.onclick = () => {
      _pendingRec = { path: path, rec: rec };
      ov.remove();
      _post('reconfigure');
    };
    const bOk = _h('button', '按推荐建库');
    bOk.className = 'btn primary';
    bOk.onclick = () => { ov.remove(); _post('accept'); };
    btns.appendChild(bCancel); btns.appendChild(bEdit); btns.appendChild(bOk);
    card.appendChild(btns);
    ov.appendChild(card);
    document.body.appendChild(ov);
    if (txt) txt.textContent = '等待确认收录范围…';

    function _post(choice) {
      if (txt) txt.textContent = '提交中…';
      fetch('/api/nav/scope_confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ choice, run_id: rid }),
      }).then(r => r.json().then(j => ({ ok: r.ok, j })))
        .then(({ ok, j }) => {
          if (ok && j && j.ok) {
            if (txt) {
              txt.textContent = choice === 'accept' ? '已确认，开始建库'
                : choice === 'reconfigure' ? '正在打开三态树…' : '已放弃建库';
              // a572（B10）：保留 3 秒，别让下一轮 poll 立刻覆写掉
              _txtHoldUntil = Date.now() + 3000;
            }
          } else {
            // a572（F1）：提交失败（最常见：任务已超时结束，409）-> 必须丢掉
            // 刚挂上的 `_pendingRec`，否则它会常驻并在**下一个任意工程**的
            // 三态树里被消费（跨工程污染）。
            if (choice === 'reconfigure') _pendingRec = null;
            if (txt) {
              txt.textContent = '未生效（' +
                ((j && (j.err || j.msg)) || '任务已结束') + '）';
            }
            showBanner('该确认已失效（任务可能已结束），请重新建立索引', 5000, true);
          }
        })
        .catch(() => {
          if (choice === 'reconfigure') _pendingRec = null;
          if (txt) txt.textContent = '提交失败（网络异常）';
        });
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
    // a572（内网评审 F4）：`_tierAsked` 原为**闭包局部**——同一目录重开面板
    // 会新建一份 `_renderProgress`，标志重置为 false，于是同一个 id 又弹一个。
    // 改用模块级 `_navAskSeen`，按后端下发的 `started`（任务启动时刻）判定
    // 是否换了一轮任务：换了才重置，同一任务内重开面板不再重复弹。
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
        // a572（B10）：弹窗作答的即时反馈（「已确认，开始建库」/「未生效…」）
        // 原被这里每 800ms 无条件覆写，用户根本看不到。给一个 3 秒的优先窗口。
        if (Date.now() > _txtHoldUntil) {
          txt.textContent = (s.phase || '') + ' · ' + (s.percent || 0) + '%' +
            (s.cancelling ? ' · 正在取消…' : '');
        }
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
        // a572（F4）：按「任务启动时刻」判一轮，同任务内重开面板不再重复弹。
        const _stared = s.started || 0;
        if (_navAskSeen.started !== _stared) {
          _navAskSeen.started = _stared;
          _navAskSeen.tier = false;
          _navAskSeen.scope = false;
        }
        if (s.ask_tier && !_navAskSeen.tier) {
          _navAskSeen.tier = true;
          _askTierDialog(s.ask_tier, txt, path, s.ask_tier_rid);
        } else if (!s.ask_tier && _navAskSeen.tier) {
          // a434：后端已撤销提问（10 分钟超时按全量继续 / 任务取消），
          // 弹窗若还开着必须收掉——否则用户点了只会拿到 409
          const _td3 = document.getElementById('navTierDialog');
          if (_td3) _td3.remove();
          _navAskSeen.tier = false;
        }
        // a571：首次建库——推荐结果交给用户确认增删再开跑
        if (s.ask_scope && !_navAskSeen.scope) {
          _navAskSeen.scope = true;
          _askScopeDialog(s.ask_scope, txt, path, s.ask_scope_rid);
        } else if (!s.ask_scope && _navAskSeen.scope) {
          const _sd3 = document.getElementById('navScopeConfirm');
          if (_sd3) _sd3.remove();
          _navAskSeen.scope = false;
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
        // a572（B7）：范围确认弹窗同理——终态（成功/失败/取消）都必须收掉。
        const _sd2 = document.getElementById('navScopeConfirm');
        if (_sd2) _sd2.remove();
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
          // a570 对抗审计（P2·第十六轮）：后端随 meta 下发被放弃的超时子树
          // （meta.scope.timeout_items），原来前端从不展示——用户看到「完成」，
          // 实际有子树没进索引。这里必须显式告警。
          const _tos = (res.scope && res.scope.timeout_items) || [];
          if (_tos.length) {
            // a570 对抗审计（P2·第十七轮）：元素是 {rel, elapsed} 对象，
            // 直接 join 会渲染成 [object Object]。
            const _tosN = _tos.slice(0, 3).map(x =>
              (x && typeof x === 'object') ? (x.rel || '(未知)') : String(x));
            const w = _h('div', '注意：本次有 ' + _tos.length +
              ' 个子树扫描超时未收录（' + _tosN.join('、') +
              (_tos.length > 3 ? ' 等' : '') + '）——可重建或调大超时');
            w.style.cssText = 'margin-top:6px;color:var(--neon-orange,#d29922);font-size:12px;';
            txt.parentNode.insertBefore(w, txt.nextSibling);
          }
          // a570 对抗审计（P2·第十六轮）：scope_saved=false 表示范围没写进
          // 工程根（只对本次建库生效），用户下次重建会丢失配置——必须提示。
          if (s.scope_saved === false) {
            // UI 禁 emoji 铁律把 ⚠ 点名为禁用字形——橙色文字本身即告警层级。
            const w2 = _h('div', '注意：收录范围未能写入工程根——下次建库需重新配置');
            w2.style.cssText = 'margin-top:6px;color:var(--neon-orange,#d29922);font-size:12px;';
            txt.parentNode.insertBefore(w2, txt.nextSibling);
          }
          showBanner('代码索引建立完成', 3000);
          bCancel.textContent = '关闭';
          bCancel.onclick = () => _closePanel(true, path, true);
        } else if (s.reason === 'reconfigure') {
          // a570·a571：不是真取消——用户选了「重新配置收录范围」。
          // 不显示「已取消」，直接重开面板并**打开三态树**。
          // a572（F6）：`ask_tier` 这条路径从不设 `_pendingRec`，原实现只
          // `ui(path)`，三态树根本不会打开——文案承诺落空。这里显式标记，
          // 让 `_scopeRow` 建好后直接开树（无推荐结果可复用，走一次扫描）。
          txt.textContent = '按你的选择返回配置…';
          bCancel.textContent = '关闭';
          bCancel.onclick = () => _closePanel(true, path, true);
          // a576（第 2 轮审计·低）：同一任务的重开最多排一次。原实现若
          // 被后端 `done` 与 `running=false` 的瞬间差异抢先，poll 会再次
          // 看到 done+reconfigure 并重排一次 200ms 重开，出现重复 ui()。
          const _rk = 'reopen:' + _normRoot(path);
          setTimeout(() => {
            if (_reopenOnce.has(_rk)) return;
            _reopenOnce.add(_rk);
            setTimeout(() => _reopenOnce.delete(_rk), 2000);
            // a572（F6 附带）：200ms 内用户可能已关闭面板或切了目录——
            // 无条件 ui(path) 会把面板抢回来。只在仍是本轮面板时才重开。
            const _still = document.getElementById('navIdxPanel');
            if (!_still || !_sameRoot(_still.dataset.path, path)) {
              // a576（第 1 轮审计·低-1）：用户在这个 200ms 窗口内关了面板
              // ——刚置的 `_openPickOnNext` 必须按根清掉，否则它会滞留下来，
              // 在**下一个任意工程**的 _scopeRow 上被无条件清零（丢掉本工程
              // 的重开意图）；同时清掉可能挂着的 `_pendingRec`。
              _dropOpenPick(path);
              _dropPendingRec(path);
              return;
            }
            _closePanel(true, path);
            _openPickOnNext = { path: path };   // _scopeRow 建好后自动开三态树
            ui(path);
          }, 200);
        } else {
          txt.textContent = (s.cancelled ? '已取消' : '失败：' + (s.err || ''));
          bCancel.textContent = '关闭';
          bCancel.onclick = () => _closePanel(true, path, true);
        }
      } catch (e) { /* 轮询失败继续 */ }
    }, 800);
  }

  // 供 file-tree.js 右键入口 + editor 检测复用 + 设置页热应用
  window.NavJump = { registerAll: registerAll, ui: ui, applyKeys: applyKeys,
                     getKeys: () => ({ ...NAV_KEYS }), keyLabel: keyLabel,
                     // a336：导航历史（设置页/右键菜单可直接触发）
                     goBack: navigateBack, goForward: navigateForward };
