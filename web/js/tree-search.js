// ============================================================
// a209批3：侧栏「搜索」sheet（对标 VSCode 资源管理器搜索）
// ------------------------------------------------------------
// 引擎：后端 /api/tree/search（vendor rg.exe SSE 流式，见
// src/tree_search.py）。前端 fetch streaming 消费（POST 不能用
// EventSource），渐进上屏；AbortController 取消。
// 结果树：文件组头（相对根路径 + N 命中）→ 命中行（行号 + snippet +
// <mark> 高亮）；点击命中行 → openFileSmart({line,col}) 落点光标；
// 点击组头 → 切文件树 sheet + treeReveal 定位。
// 渲染限额：DOM 最多 ~600 节点（200 match × 3），超出仅计数（红线）。
// ============================================================
(function () {
  'use strict';
  const $s = (sel) => document.querySelector(sel);
  const qEl = document.querySelector('[data-ts-q]');
  const caseEl = document.querySelector('[data-ts-case]');
  const rexEl = document.querySelector('[data-ts-rex]');
  const fnEl = document.querySelector('[data-ts-fn]');
  const scopeEl = document.querySelector('[data-ts-scope]');
  const resEl = document.querySelector('[data-ts-results]');
  const statEl = document.querySelector('[data-ts-stat]');

  let runSeq = 0;       // a213 审计 P3：重搜竞态——旧 run 收尾不得覆写新状态
  let lastTruncated = false;
  const st = {
    scope: '',          // '' = 全部根
    caseOn: false, regexOn: false, fnOn: false,
    ctrl: null,         // AbortController
    files: 0, hits: 0, domMatches: 0,
  };
  const DOM_CAP = 200;   // 命中行渲染上限（超出只计数）
  const BS = String.fromCharCode(92);

  function roots() { return (window._TV && _TV.roots) || []; }
  function relPath(p) {
    const np = String(p).split(BS).join('/');
    for (const r of roots()) {
      const rp = String(r.path).split(BS).join('/');
      if (np.startsWith(rp + '/')) return np.slice(rp.length + 1);
      if (np === rp) return r.name || rp;
    }
    return np;
  }
  function highlight(text, q) {
    // 字面高亮（正则/函数模式退化为不高亮——col 已可跳转）
    if (st.regexOn || st.fnOn || !q) return esc(text);
    const parts = String(text).split(q);
    return parts.map((x, i) => i === 0 ? esc(x) : '<mark>' + esc(q) + '</mark>' + esc(x)).join('');
  }

  // ---- 工具条交互（a221：条件变化立即重搜——VSCode 语义，无需回车确定）----
  function bindToggle(el, key) {
    el.onclick = () => {
      st[key] = !st[key]; el.classList.toggle('on', st[key]);
      if (qEl.value.trim()) run();   // 已有关键词：切换即按新模式重搜
    };
  }
  bindToggle(caseEl, 'caseOn');
  bindToggle(rexEl, 'regexOn');
  bindToggle(fnEl, 'fnOn');
  // 输入防抖 400ms 自动搜（VSCode 同款即时感；Enter 仍可立即触发、Esc 取消）
  let _deb = 0;
  qEl.addEventListener('input', () => {
    clearTimeout(_deb);
    _deb = setTimeout(() => { if (qEl.value.trim()) run(); }, 400);
  });
  scopeEl.onclick = () => {
    st.scope = '';
    scopeEl.textContent = '范围：全部根';
    scopeEl.title = '点击重置为全部根';
    if (qEl.value.trim()) run();   // a233 P3: 重置即重搜
  };

  // 对外入口：右键「在此文件夹中搜索」预填范围并聚焦（tree-fileops 扩展点）
  window.tsSearchIn = function (dirPath) {
    st.scope = dirPath || '';
    scopeEl.textContent = '范围：' + (dirPath ? relPath(dirPath) : '全部根');
    scopeEl.title = '范围：' + dirPath + '（点击重置为全部根）';
    // 切到搜索 sheet
    const tab = document.querySelector('.sidebar-sheet-tab[data-sheet="search"]');
    if (tab) tab.click();
    qEl.focus(); qEl.select();
  };

  // ---- SSE 消费（fetch streaming）----
  async function run() {
    const q = qEl.value.trim();
    if (!q) { resEl.innerHTML = '<div class="ts-empty">输入关键词回车搜索</div>'; return; }
    cancel();
    st.ctrl = new AbortController();
    st.files = 0; st.hits = 0; st.domMatches = 0;
    lastTruncated = false;
    const mySeq = ++runSeq;
    st.errMsg = '';
    clearTimeout(_deb);   // a233 P3: 立即 run 清残留防抖（原双搜）
    resEl.innerHTML = '';
    statEl.textContent = '搜索中…';
    statEl.classList.add('run');
    const t0 = Date.now();
    // 逐根搜索（scope 空时循环全部根；有 scope 单根）
    const scopes = st.scope ? [st.scope] : roots().map(r => r.path);
    if (!scopes.length) { statEl.textContent = '未登记任何根目录（文件树先添加文件夹）'; statEl.classList.remove('run'); return; }
    let aborted = false;
    st.ctrl.signal.addEventListener('abort', () => { aborted = true; });
    try {
      // a218：多根并行（原逐根 await 串行——N 根=N 倍总时长；rg 各自独立
      // 子进程，并行只受 IO 上限，与 VSCode 全仓搜索同语义）
      await Promise.all(scopes.map(sc => one(sc, q, () => aborted)));
    } catch (e) {
      if (!aborted) statEl.textContent = '搜索失败: ' + e;
    }
    if (mySeq !== runSeq) return;   // 已被更新搜索取代——不覆写新状态
    statEl.classList.remove('run');
    statEl.textContent = st.errMsg ? ('错误：' + st.errMsg) : ((aborted ? '已取消 · ' : '') +
      st.files + ' 文件 / ' + st.hits + ' 命中 · ' +
      ((Date.now() - t0) / 1000).toFixed(1) + 's' +
      (lastTruncated ? '（已达限额截断）' : ''));
  }

  function one(scope, q, isAborted) {
    return new Promise((resolve) => {
      fetch('/api/tree/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q, scope, case: st.caseOn, regex: st.regexOn, mode: st.fnOn ? 'function' : 'text' }),
        signal: st.ctrl.signal,
      }).then(r => {
        if (!r.ok) {   // a233 P2: 400/5xx 非 SSE 被静默吞
          // a234 复审：只写 statEl 文案无效——run 尾会无条件重写 statEl（同一轮
          // 微任务，中间无 paint），终态仍「0 命中」。错误必须走 st.errMsg 让
          // run 尾以「错误：HTTP xxx」呈现
          st.errMsg = 'HTTP ' + r.status;
          statEl.textContent = '部分根搜索失败: HTTP ' + r.status;
          return resolve();
        }
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        const pump = () => reader.read().then(({ done, value }) => {
          if (done || isAborted()) { resolve(); return; }
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf('\n\n')) >= 0) {
            const line = buf.slice(0, i).trim();
            buf = buf.slice(i + 2);
            if (line.startsWith('data: ')) {
              try { onEvent(JSON.parse(line.slice(6)), q); } catch (_) {}
            }
          }
          pump();
        }).catch(() => resolve());
        pump();
      }).catch(() => resolve());
    });
  }

  let curFileEl = null, curFileHead = null, curFilePath = '', curFileCount = 0;   // a213 审计 P2：head 独立引用（curFileEl 链式插入后变 hit 行，querySelector 计数失效→恒 1）
  function onEvent(ev, q) {
    if (ev.type === 'error') { st.errMsg = ev.err; return; }   // a233: run 尾统一展示
    if (ev.type === 'progress') {
      // 冷 IO 扫描期心跳：不再白屏死等（可点取消）
      if (st.ctrl) statEl.textContent = '扫描中… ' + ev.files + ' 文件 · ' + st.hits + ' 命中';
      return;
    }
    if (ev.type === 'file') {
      // a236 fuzz P3: 组头无封顶曾致万级文件=万级 DOM（200 承诺被打穿）
      if (st.domMatches >= DOM_CAP && resEl.children.length >= DOM_CAP) { st.files++; return; }
      st.files++;
      curFilePath = ev.path; curFileCount = 0;
      const head = document.createElement('div');
      head.className = 'ts-file';
      head.innerHTML = '<span class="ts-fpath" title="' + esc(ev.path) + '">' +
        esc(relPath(ev.path)) + '</span><span class="ts-fn">0</span>';
      head.onclick = () => {
        // 切树 sheet + reveal 定位
        const tab = document.querySelector('.sidebar-sheet-tab[data-sheet="tree"]');
        if (tab) tab.click();
        if (typeof treeReveal === 'function') treeReveal(ev.path);
      };
      resEl.appendChild(head);
      curFileEl = head; curFileHead = head;
      return;
    }
    if (ev.type === 'match') {
      st.hits++; curFileCount++;
      const fn = curFileHead && curFileHead.querySelector('.ts-fn');
      if (fn) fn.textContent = curFileCount;
      if (st.domMatches >= DOM_CAP) {
        if (st.domMatches === DOM_CAP) {
          const more = document.createElement('div');
          more.className = 'ts-more';
          more.textContent = '… 结果过多，仅渲染前 ' + DOM_CAP + ' 条（其余计数）';
          resEl.appendChild(more);
          st.domMatches++;
        }
        return;
      }
      st.domMatches++;
      const row = document.createElement('div');
      row.className = 'ts-hit';
      row.innerHTML = '<span class="ts-ln">' + ev.line + '</span>' +
        '<span class="ts-txt">' + highlight(ev.text, q) + '</span>';
      const p = ev.path || curFilePath;
      row.onclick = () => {
        if (typeof openFileSmart === 'function')
          openFileSmart(p, 'auto', { line: ev.line, col: ev.col || 1 });
      };
      // 追加到当前文件组（组头后）
      if (curFileEl && curFileEl.parentElement === resEl) {
        resEl.insertBefore(row, curFileEl.nextSibling);
        curFileEl = row;   // 链式插入保持组内顺序
      } else {
        resEl.appendChild(row);
      }
      return;
    }
    if (ev.type === 'summary') {
      if (ev.truncated) lastTruncated = true;   // a213 P3：run 尾部统一拼（原被整行覆盖）
    }
  }

  function cancel() {
    if (st.ctrl) { try { st.ctrl.abort(); } catch (_) {} st.ctrl = null; }
    statEl.classList.remove('run');
  }

  qEl.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); run(); }
    else if (e.key === 'Escape') { cancel(); qEl.blur(); }
  });
  statEl.onclick = () => { if (st.ctrl) cancel(); };   // 搜索中点击状态条取消

  // Ctrl+Alt+G：全局唤起搜索 sheet（Ctrl+Alt+F 已被笔记搜索占用）
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.altKey && (e.key === 'g' || e.key === 'G')) {
      e.preventDefault();
      window.tsSearchIn('');
    }
  });
})();
