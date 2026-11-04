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
      const ISW = c => /[A-Za-z0-9_]/.test(c || '');
      let i = Math.max(0, position.column - 1);
      if (!ISW(line[i])) i -= 1;          // 边界外（词尾点击）向左探一格
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
      openFileSmart(c.path, 'auto', { line: Math.max(1, c.line || 1) });
      return;
    }
    _showCandidates(j);
  }

  // 候选面板（多结果）：✓编译内 / ✗未编译 / ~头文件 徽标 + 路径分组
  function _showCandidates(j) {
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
        openFileSmart(c.path, 'auto', { line: Math.max(1, c.line || 1) });
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
              openFileSmart(it.path, 'auto', { line: Math.max(1, it.line || 1) });
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
      + (j.truncated ? ' · ⚠ 结果超 200 条已截断' : ''));
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
      const loc = _h('span', it.rel + ' :' + it.line);
      loc.style.cssText = 'font-family:var(--font-mono);font-size:11.5px;flex-shrink:0;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      const sn = _h('span', it.snippet || '');
      sn.style.cssText = 'font-family:var(--font-mono);font-size:11px;color:var(--muted);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      row.appendChild(b); row.appendChild(loc); row.appendChild(sn);
      row.onclick = function () { _closeCands(); openFileSmart(it.path, 'auto', { line: it.line }); };
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

  // 顶层等待 Monaco 就绪后注册（c/cpp/python/javascript）
  function bindEditor(ed) {
    // R15-1：Ctrl+Click 自定义跳转（standalone Monaco 原生 uri 链无内容
    // 服务——见 provideDefinition 注释）
    try {
      ed.onMouseDown(function (e) {
        if (e.event.ctrlKey && e.event.leftButton && e.target.position) {
          gotoDefinition(ed);
        }
      });
    } catch (_) {}
  }

  function registerAll() {
    ['c', 'cpp', 'python', 'javascript'].forEach(function (lang) {
      try {
        monaco.languages.registerDefinitionProvider(lang, {
          provideDefinition: provideDefinition,
        });
      } catch (e) { /* 语言 ID 未注册（该版本 Monaco 无此语言）——跳过 */ }
    });
    try {
      monaco.editor.onDidCreateEditor(bindEditor);
      (monaco.editor.getEditors() || []).forEach(bindEditor);   // 已存在实例
    } catch (_) {}
  }

  // 全局键位：F12 转定义 / Shift+F12 查引用 / Ctrl+T 工作区符号
  // （capture 拦截——F12 原生开发者工具键、Ctrl+T 原生新标签页都被占位）
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
      if (e.key === 'F12' && ed) {
        e.preventDefault();
        e.stopPropagation();
        if (e.shiftKey) findReferences(ed);
        else gotoDefinition(ed);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 't' || e.key === 'T')) {
        if (!ed) return;
        e.preventDefault();
        e.stopPropagation();
        showWorkspaceSymbols(ed);
      }
    }, true);
  }

  function boot() {
    bindGlobalKeys();
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

  function _h(tag, txt) {
    const e = document.createElement(tag);
    if (txt !== undefined) e.textContent = txt;
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
    const bAdd = _h('button', '🔍 建立索引');
    bAdd.className = 'btn primary';
    bAdd.onclick = () => _startBuild(card, path);
    // R15-5（实锤：弹层死角）：indexed 判定必须在 has_code 之前——代码被
    // 移走（探测不到）但库还在时，仍要给已建态（重建/删除可达）
    if (!j.indexed) {
      if (!j.has_code) {
        st.textContent = '❌ 未发现代码文件（C/C++/py/js 等）——该目录不需要索引';
        st.style.color = 'var(--neon-red,#e5484d)';
        return;   // 无按钮：不盲目
      }
      st.textContent = '✓ 发现代码文件（浅层抽样 ' + (j.probe_files || 0) + ' 个）。'
        + '首次索引需扫描全目录——网盘挂载的大库可能数分钟，结果存工具数据目录（不写工程目录）。';
      btns.insertBefore(bAdd, btns.lastChild);
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
      const warn = _h('div', '⚠ 索引对应的工程路径当前不可达（换盘/移动了？）——跳转可能失效，可重建');
      warn.style.color = '#e8a33d';
      st.appendChild(warn);
    }
    if (j.stale) {   // 批3：粗粒度过期提示（浅层 .cmd 命中 vs 建库记录）
      const warn2 = _h('div', '⚠ 工程构建产物有变化（新编译/换树）——建议重建索引以刷新白名单');
      warn2.style.color = '#e8a33d';
      st.appendChild(warn2);
    }
    const bRe = _h('button', '↻ 重建');
    bRe.className = 'btn primary';
    bRe.onclick = () => _startBuild(card, path);
    const bDel = _h('button', '🗑 删除索引');
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
    // 批3：nm 清单可选导入（Linux 侧 find -name '*.o' | xargs nm -A
    // --defined-only > syms.txt 拷回后导入——符号级消歧对齐真机）
    const bNm = _h('button', '📥 导入 nm 清单…');
    bNm.className = 'btn ghost';
    bNm.onclick = async () => {
      let f = '';
      try {
        if (window.pywebview && pywebview.api && pywebview.api.pick_any) {
          const r = await pywebview.api.pick_any();
          f = (typeof r === 'string') ? r : ((r && r.path) || '');
        }
      } catch (_) {}
      if (!f) f = window.prompt('nm -A 清单文件路径（syms.txt）：', '') || '';
      if (!f) return;
      try {
        const r = await fetch('/api/nav/import_nm', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: path, file: f.trim() }) });
        const d = await r.json();
        showBanner(d.ok ? ('nm 清单导入完成：' + d.msg) : ('导入失败：' + (d.err || d.msg)), 5000, !d.ok);
      } catch (e) { showBanner('导入失败: ' + e, 4000, true); }
    };
    btns.insertBefore(bNm, btns.lastChild);
    btns.insertBefore(bRe, btns.lastChild);
  }

  function _startBuild(card, path) {
    fetch('/api/nav/build', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: path }) })
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
          txt.textContent = '✓ 完成：' + ((s.result && s.result.code_files) || 0) + ' 符号';
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

  // 供 file-tree.js 右键入口 + editor 检测复用
  window.NavJump = { registerAll: registerAll, ui: ui };
})();
