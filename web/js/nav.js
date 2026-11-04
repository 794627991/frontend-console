// a333 批1：代码跳转（ctags 索引 + 编译白名单 + ELF 符号表）
// Monaco definitionProvider 按语言注册——F12/Ctrl+Click 原生跳转；
// 无索引静默 no result（建索引走文件树右键，绝不自动打扰）。
(function () {
  'use strict';

  function monacoWordAt(model, position) {
    const w = model.getWordAtPosition(position);
    return w ? w.word : '';
  }

  // 定义查询 → Monaco Definition 链接数组（多结果 Monaco 原生弹 peek 列表）
  async function provideDefinition(model, position) {
    try {
      const word = monacoWordAt(model, position);
      if (!word || word.length < 2) return null;
      // Monaco uri.path 是 URL 编码形态（file:///d%3A/AI/...）——先解码
      // 再剥前导斜杠成 Windows 盘符路径
      let file = decodeURIComponent(model.uri.path || '');
      file = file.replace(/^\/([A-Za-z]):/, '$1:');
      const r = await fetch('/api/nav/definition?file=' + encodeURIComponent(file) +
                            '&symbol=' + encodeURIComponent(word));
      const j = await r.json();
      if (!j.ok || !j.candidates || !j.candidates.length) return null;
      const out = [];
      j.candidates.forEach(function (c) {
        const uri = monaco.Uri.file(c.path);
        out.push({
          uri: uri,
          range: new monaco.Range(Math.max(1, c.line || 1), 1,
                                  Math.max(1, c.line || 1), 1),
          // 自定义字段：原生 peek 不展示，批 2 候选浮层用（✓编译内/✗未编译）
          navMeta: { in_build: c.in_build, kind: c.kind, rel: c.rel,
                     auto: j.auto, mode: j.mode },
        });
      });
      return out;
    } catch (_) {
      return null;   // 无网/后端未起：静默（不破坏编辑体验）
    }
  }

  // 顶层等待 Monaco 就绪后注册（c/cpp/python/javascript）
  function registerAll() {
    ['c', 'cpp', 'python', 'javascript'].forEach(function (lang) {
      try {
        monaco.languages.registerDefinitionProvider(lang, {
          provideDefinition: provideDefinition,
        });
      } catch (e) { /* 语言 ID 未注册（该版本 Monaco 无此语言）——跳过 */ }
    });
  }

  function boot() {
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
    if (!j.has_code) {
      st.textContent = '❌ 未发现代码文件（C/C++/py/js 等）——该目录不需要索引';
      st.style.color = 'var(--neon-red,#e5484d)';
      return;   // 无按钮：不盲目
    }
    if (!j.indexed) {
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
