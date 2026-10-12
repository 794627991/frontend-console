// ============================================================
// 24-vcs.js (v3.5.117)：右栏「版本」页签——git / svn 工作副本查看与常用写。
// 设计依据 designer 方案：伪 tab 机制同动态/目录（14-subpane _SUB_VCS）；
// API /api/vcs/*（src/vcs.py，文件树登记根安全模型）；diff 复用
// buildDiffViewerTab（后端把旧版本物化成临时文件，前端拿两真实路径开
// Monaco Diff）；写操作全显式确认，不含 push/还原/冲突解决（边界）。
// 状态：_HG.vcs = {root, data, log, out, busy, sel:Set, ts}
// ============================================================
  _HG.vcs = { root: '', data: null, log: null, out: '', busy: false, sel: new Set(), ts: 0 };
  let _vcsEl = null;                 // 版本页 sc 容器（随 _subReset/_subDrop 清）
  let _vcsLogBusy = false;           // log 拉取防连点
  let _vcsTs = 0;                    // 上次 status 拉取时刻（30s 激活缓存）
  const _VCS_ST_CLS = { M: 'm', A: 'a', D: 'd', R: 'r', '?': 'u', C: 'c', '!': 'd' };
  const _VCS_ST_TXT = { M: '改', A: '增', D: '删', R: '移', '?': '未纳管', C: '冲突', '!': '丢失' };

  function _vcsEnsure() {            // 懒建 tab（不夺焦点；_subDirEnsure 同步调）
    if (!_subPaneEl || _sub.tabs[_SUB_VCS]) return;
    const sc = document.createElement('div');
    sc.className = 'hg-sub-msgs hg-vcs-pane'; sc.dataset.tid = _SUB_VCS;
    _sub.tabs[_SUB_VCS] = { label: '版本', type: '__vcs__', desc: 'git / svn 版本控制', sc,
                            run: false, err: false, replay: false, model: '' };
    _sub.order.push(_SUB_VCS);
    _subBodyEl.appendChild(sc);
    // v3.5.119（用户实锤「子代理窗格只显示一半，点开版本页签就好了」）：
    // 本函数是「不夺焦点」懒建（_subDirEnsure 头部随四入口触发）——新 sc
    // 不像动态/目录那样紧跟 _subActivate(自己) 接管显示，裸 append 会以
    // display:'' 叠在当前激活窗格上把内容挤掉一半。藏住，激活交给
    // _subActivate 统一切换
    if (_sub.active !== _SUB_VCS) sc.style.display = 'none';
    _vcsEl = sc;
    sc.innerHTML = '<div class="hg-vcs-loading">…</div>';
  }
  function _vcsReset() {             // 分屏清场/伪 tab 关闭：引用随 _sub.tabs 拆档置空
    _vcsHistClose();                 // v3.5.133（designer D10）：弹窗防御性关闭——唯一收口防陈旧态
    _vcsEl = null;
    _HG.vcs = { root: (_HG.vcs || {}).root || '', data: null, log: null,
                out: '', busy: false, sel: new Set(), ts: 0 };
  }

  // ==================== v3.5.133 提交历史弹窗（designer 方案 v1）====================
  // 左列表(≤100)右详情 master-detail；数据吃 _HG.vcs.log 共享源（秒开），
  // 打开时后台补刷新；点文件 → commit_diff → buildDiffViewerTab 主区 diff tab
  //（harness tab 隐藏不销毁，回切弹窗原样）；Esc/遮罩/按钮/reset 四路关闭
  // 全走 _vcsHistClose 唯一收口。
  let _vcsHist = null;               // {ov, sel, seq, files:Map, escFn, q, qlog, ...}
  let _vcsHistLseq = 0;              // L2：模块级单调——重开窗口期间旧响应不可穿透

  function _vcsFmtDt(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return String(iso || '');
    const p = n => String(n).padStart(2, '0');
    return (d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  // 公共 diff 点击（designer 5.7）：面板展开行与弹窗详情共用一份实现
  function _vcsFileDiffClick(rev, path, st, rowEl) {
    (async () => {
      if (rowEl) rowEl.style.opacity = '.5';
      try {
        const j = await (await fetch('/api/vcs/commit_diff', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: _HG.vcs.root, rev, path, st }) })).json();
        if (j.ok) { try { buildDiffViewerTab(j.a, j.b); } catch (e) { showBanner('diff 打开失败：' + e, 4000, true); } }
        else showBanner('提交 diff 获取失败：' + (j.err || ''), 4000, true);
      } catch (e) { showBanner('提交 diff 获取失败：' + e, 4000, true); }
      if (rowEl) rowEl.style.opacity = '';
    })();
  }

  // ==================== v2（designer S2/S3/S4）====================
  // 累积式分页 + 查询态分离 + 筛选工具栏 + pager + deco/复制/键盘
  function _vcsHistQfp() {
    const q = _vcsHist.q;
    return JSON.stringify([q.text, q.author, q.since, q.until]);
  }
  function _vcsHistActive() {          // 活动数据（浏览累积 / 查询累积）
    return _vcsHist.querying ? _vcsHist.qlog : _HG.vcs.log;
  }
  function _vcsHistBusy() {
    return _vcsHist.querying ? _vcsHist.qbusy : _vcsLogBusy;
  }
  function _vcsHistTotal() {
    return _vcsHist.querying ? _vcsHist.qtotal : _HG.vcs.total;
  }

  // 列表数据入口（浏览/查询路由 + lseq/指纹双竞态校验）
  function _vcsHistFetch(reset) {
    const H = _vcsHist;
    if (!H) return;
    const lseq = (H.lseq = ++_vcsHistLseq);   // L2：模块级单调令牌
    const fp = _vcsHistQfp();
    if (H.querying) H.qbusy = true;
    const arr = H.querying ? H.qlog : (_HG.vcs.log = _HG.vcs.log || []);
    const skip = reset ? 0 : arr.length;
    const oldest = arr.length ? arr[arr.length - 1].rev : '';
    const isSvn = ((_HG.vcs.data || {}).vcs === 'svn');
    const body = { root: _HG.vcs.root, limit: 100, skip: isSvn ? 0 : skip };
    if (isSvn && !reset && oldest) body.before_rev = String(parseInt(oldest, 10) - 1 || 0);
    Object.assign(body, H.q);
    fetch('/api/vcs/log', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) })
      .then(r => r.json()).then(j => {
        if (!H || H.lseq !== lseq || _vcsHistQfp() !== fp) return;   // 竞态：旧响应丢弃
        if (H.querying) H.qbusy = false;
        if (!j.ok) {
          H.fetchErr = j.err || '获取失败';
          if (!H.querying) { _HG.vcs.log = null; _HG.vcs.total = undefined; }
          _vcsHistPaintList(true);
          return;
        }
        H.fetchErr = null;
        if (reset) H.exhausted = false;
        const tgt = H.querying ? H.qlog : _HG.vcs.log;
        const known = new Set(tgt.map(c => c.rev));
        const add = (j.commits || []).filter(c => c.rev && !known.has(c.rev));
        if (reset) { tgt.length = 0; tgt.push(...(j.commits || [])); }
        else tgt.push(...add);
        // P2：后端仅 skip==0 附 total——追加响应无 total 时保住已有精确值
        //（旧写法 undefined 覆盖 → 翻一页「共523条」降级「已载200条」）
        if (j.total !== undefined) {
          if (H.querying) H.qtotal = j.total;
          else _HG.vcs.total = j.total;
        }
        // P4：svn 无 total 的终点信号——追加响应去重后零新增=已到最早
        if (!reset && add.length === 0) H.exhausted = true;
        // 漂移补齐：skip 语义下新提交顶入取不满一页 → 追拉（≤3 轮）
        if (!reset && !isSvn && add.length < (j.commits || []).length
            && (j.commits || []).length >= 100 && H.rounds < 3) {
          H.rounds++;
          _vcsHistFetch(false);
          return;
        }
        H.rounds = 0;
        if (reset && H.sel && !tgt.some(c => c.rev === H.sel)) {
          H.sel = null;
          const d = H.ov.querySelector('[data-vcs-hdetail]');
          if (d) d.innerHTML = '<div class="hg-vcs-empty">← 在左侧选择一个提交查看详情</div>';
        }
        _vcsHistPaintList(true);
        if (!H.querying) _vcsPaint();   // 面板共享源同步
      }).catch(e => {
        if (H && H.lseq === lseq) {
          if (H.querying) H.qbusy = false;
          H.fetchErr = String(e);
          _vcsHistPaintList(true);
        }
      });
  }

  function _vcsHistOpen() {
    if (_vcsHist) { return; }        // 双开守卫
    const D = _HG.vcs.data;
    if (!D || !D.tool) { showBanner('当前工程不可用版本控制操作', 3000, true); return; }
    const isSvn = D.vcs === 'svn';
    const size = parseInt(localStorage.getItem('hg-vcs-histsize') || '20', 10) || 20;
    const ov = document.createElement('div');
    ov.className = 'hg-modal-ov';
    const escFn = (e) => {
      if (e.key === 'Escape') { _vcsHistClose(); return; }
      // S4：↑↓ 键盘导航（焦点不在输入控件时）
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && _vcsHist) {
        const t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA')) return;
        const rows = Array.from(_vcsHist.ov.querySelectorAll('[data-hrev]'));
        if (!rows.length) return;
        e.preventDefault();
        let idx = rows.findIndex(r => r.dataset.hrev === _vcsHist.sel);
        idx = e.key === 'ArrowDown' ? Math.min(rows.length - 1, idx + 1)
                                    : Math.max(0, idx <= 0 ? 0 : idx - 1);
        rows[idx].click();
        rows[idx].scrollIntoView({ block: 'nearest' });
      }
    };
    document.addEventListener('keydown', escFn);
    _vcsHist = { ov, sel: null, seq: 0, files: new Map(), escFn,
                 q: { text: '', author: '', since: '', until: '' },
                 qlog: [], qbusy: false, qtotal: undefined, querying: false, exhausted: false,
                 page: 1, size, lseq: 0, rounds: 0, fetchErr: null, debT: null };
    const dateInp = (k, ph) =>
      `<input type="date" class="hg-vcs-hdate" data-vcs-hq="${k}" title="${ph}">`;
    ov.innerHTML =
      `<div class="hg-modal hg-modal-vcslog">` +
        `<div class="hg-modal-title">📜 提交历史 · ${esc(D.vcs || '')}${D.branch ? ' · ⎇ ' + esc(D.branch) : ''}</div>` +
        `<div class="hg-vcs-htool">` +
          `<input class="hg-vcs-hsearch" data-vcs-hq="text" placeholder="${isSvn ? '🔍 关键字（svn 整串匹配，含作者/日期）' : '🔍 关键字（多词 AND，含正文）'}" spellcheck="false">` +
          (isSvn ? '' :
            `<input class="hg-vcs-hauthor" data-vcs-hq="author" list="hg-vcs-authors" placeholder="👤 作者" spellcheck="false">` +
            `<datalist id="hg-vcs-authors"></datalist>`) +
          `<button class="btn ghost hg-vcs-chip" data-vcs-chip="today">今天</button>` +
          `<button class="btn ghost hg-vcs-chip" data-vcs-chip="7d">近7天</button>` +
          `<button class="btn ghost hg-vcs-chip" data-vcs-chip="30d">近30天</button>` +
          dateInp('since', '起始日期') + `<span class="hg-vcs-hsep">~</span>` + dateInp('until', '结束日期') +
          `<button class="btn ghost" data-vcs-hclear style="display:none;">✕ 清除筛选</button>` +
        `</div>` +
        `<div class="hg-vcs-hbody">` +
          `<div class="hg-vcs-hlist" data-vcs-hlist></div>` +
          `<div class="hg-vcs-hdetail" data-vcs-hdetail>` +
            `<div class="hg-vcs-empty">← 在左侧选择一个提交查看详情</div>` +
          `</div>` +
        `</div>` +
        `<div class="hg-vcs-hpager">` +
          `<button class="btn ghost icon-btn" data-vcs-hprev title="上一页">‹</button>` +
          `<span data-vcs-hpginfo class="hg-vcs-hpginfo">—</span>` +
          `<button class="btn ghost icon-btn" data-vcs-hnext title="下一页（末页自动加载更早）">›</button>` +
          `<span class="hg-vcs-hsep">每页</span>` +
          `<select class="hg-vcs-hsize" data-vcs-hsize>` +
            [20, 50, 100].map(n => `<option value="${n}"${n === size ? ' selected' : ''}>${n}</option>`).join('') +
          `</select>` +
          `<span style="flex:1"></span>` +
          `<span data-vcs-hcount class="hg-vcs-hpginfo"></span>` +
        `</div>` +
        `<div class="hg-modal-acts">` +
          `<button class="btn ghost" data-vcs-hrefresh>⟳ 刷新</button>` +
          `<span style="flex:1"></span>` +
          `<button class="btn ghost" data-vcs-hclose>关闭</button>` +
        `</div>` +
      `</div>`;
    ov.addEventListener('click', (e) => { if (e.target === ov) _vcsHistClose(); });
    ov.querySelector('[data-vcs-hclose]').onclick = () => _vcsHistClose();
    ov.querySelector('[data-vcs-hrefresh]').onclick = () => {
      // P8：⟳ 统一回补语义——查询态走 fetch(reset)，浏览态走 _vcsReloadLog
      //（回补到已载量 ≤500，不缩回 100）
      if (_vcsHist && _vcsHist.querying) _vcsHistFetch(true);
      else _vcsReloadLog();
    };
    ov.querySelector('[data-vcs-hprev]').onclick = () => {
      if (_vcsHist && _vcsHist.page > 1) { _vcsHist.page--; _vcsHistPaintList(true); }
    };
    ov.querySelector('[data-vcs-hnext]').onclick = () => {
      const H = _vcsHist; if (!H) return;
      const arr = _vcsHistActive();
      const pages = Math.max(1, Math.ceil(arr.length / H.size));
      if (H.page < pages) { H.page++; _vcsHistPaintList(true); return; }
      // 当前末页且可能还有更早——拉下一块（svn 无 total：exhausted 信号
      // 或非整百启发式；before_rev 已到 r1 边界不再发）
      const atEnd = _vcsHistTotal() != null ? arr.length >= _vcsHistTotal()
        : (H.exhausted || !(arr.length % 100 === 0));
      const oldest = arr.length ? arr[arr.length - 1].rev : '';
      const svnEnd = ((_HG.vcs.data || {}).vcs === 'svn')
        && oldest && parseInt(oldest, 10) <= 1;
      if (!atEnd && !svnEnd && !_vcsHistBusy()) { H.page++; _vcsHistFetch(false); }
    };
    ov.querySelector('[data-vcs-hsize]').onchange = (e) => {
      if (!_vcsHist) return;
      _vcsHist.size = +e.target.value || 20;
      try { localStorage.setItem('hg-vcs-histsize', String(_vcsHist.size)); } catch (_) {}
      const arr = _vcsHistActive();
      _vcsHist.page = Math.min(_vcsHist.page, Math.max(1, Math.ceil(arr.length / _vcsHist.size)));
      _vcsHistPaintList(true);
    };
    // 筛选绑定（S3）：输入防抖 400ms / 日期即变 / chips 快捷档 / 清除
    const _applyQ = () => {
      const H = _vcsHist; if (!H) return;
      const has = !!(H.q.text || H.q.author || H.q.since || H.q.until);
      H.querying = has;
      H.page = 1;
      H.qlog.length = 0;
      H.ov.querySelector('[data-vcs-hclear]').style.display = has ? '' : 'none';
      const dl = H.ov.querySelector('#hg-vcs-authors');
      if (dl) {
        const seen = new Set();
        dl.innerHTML = Array.from(_HG.vcs.log || []).map(c => c.author)
          .filter(a => a && !seen.has(a) && seen.add(a)).slice(0, 30)
          .map(a => `<option value="${esc(a)}">`).join('');
      }
      _vcsHistFetch(true);   // 两态统一走 fetch（浏览态 reset=⟳ 同义）
    };
    const _debounced = () => {
      clearTimeout(_vcsHist.debT);
      _vcsHist.debT = setTimeout(_applyQ, 400);
    };
    ov.querySelectorAll('[data-vcs-hq]').forEach(inp => {
      const k = inp.dataset.vcsHq;
      if (k === 'text' || k === 'author') inp.addEventListener('input', () => { _vcsHist.q[k] = inp.value.trim(); _debounced(); });
      else inp.addEventListener('change', () => { _vcsHist.q[k] = inp.value; _applyQ(); });
    });
    ov.querySelectorAll('[data-vcs-chip]').forEach(c => c.onclick = () => {
      const H = _vcsHist; if (!H) return;
      const fmt = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
      const back = n => { const d = new Date(); d.setDate(d.getDate() - n); return fmt(d); };
      const today = fmt(new Date());
      if (c.dataset.vcsChip === 'today') { H.q.since = today; H.q.until = today; }
      else if (c.dataset.vcsChip === '7d') { H.q.since = back(6); H.q.until = today; }
      else { H.q.since = back(29); H.q.until = today; }
      const si = ov.querySelector('[data-vcs-hq="since"]'); if (si) si.value = H.q.since;
      const ui = ov.querySelector('[data-vcs-hq="until"]'); if (ui) ui.value = H.q.until;
      ov.querySelectorAll('.hg-vcs-chip').forEach(x => x.classList.remove('on'));
      c.classList.add('on');
      _applyQ();
    });
    ov.querySelector('[data-vcs-hclear]').onclick = () => {
      const H = _vcsHist; if (!H) return;
      H.q = { text: '', author: '', since: '', until: '' };
      ov.querySelectorAll('[data-vcs-hq]').forEach(i => i.value = '');
      ov.querySelectorAll('.hg-vcs-chip').forEach(c => c.classList.remove('on'));
      _applyQ();
    };
    _hgWrap.appendChild(ov);
    // 打开必补拉（R2/R3 语义）；先显已载再补
    if (!_vcsLogBusy) _vcsReloadLog();
    _vcsHistPaintList(false);
  }

  function _vcsHistClose() {
    if (!_vcsHist) return;
    clearTimeout(_vcsHist.debT);
    try { document.removeEventListener('keydown', _vcsHist.escFn); } catch (_) {}
    _vcsHist.ov.remove();
    _vcsHist = null;   // 查询态随弹窗即焚（designer D6）
  }

  function _vcsHistPaintList(keepSel) {
    if (!_vcsHist) return;
    const H = _vcsHist;
    const listEl = H.ov.querySelector('[data-vcs-hlist]');
    if (!listEl) return;
    const arr = _vcsHistActive();
    if (H.fetchErr) {
      listEl.innerHTML = '<div class="hg-vcs-empty">' + esc(H.fetchErr) + '——点 ⟳ 刷新重试</div>';
      _vcsHistPager();
      return;
    }
    if (!arr) {
      listEl.innerHTML = '<div class="hg-vcs-empty">' + (H.querying
        ? (_vcsHistBusy() ? '搜索中…' : '无匹配——调整关键字/时间范围')
        : (_vcsLogBusy ? '加载中…' : '暂无数据——点 ⟳ 刷新')) + '</div>';
      _vcsHistPager();
      return;
    }
    if (!arr.length) {
      listEl.innerHTML = '<div class="hg-vcs-empty">' + (
        _vcsHistBusy() ? (H.querying ? '搜索中…' : '加载中…')
        : H.querying ? '无匹配提交——调整关键字/时间范围，或 ✕ 清除筛选'
        : '还没有提交记录') + '</div>';
      _vcsHistPager();
      return;
    }
    if (keepSel && H.sel && !arr.some(c => c.rev === H.sel)) {
      H.sel = null;
      const d = H.ov.querySelector('[data-vcs-hdetail]');
      if (d) d.innerHTML = '<div class="hg-vcs-empty">← 在左侧选择一个提交查看详情</div>';
    }
    const pages = Math.max(1, Math.ceil(arr.length / H.size));
    H.page = Math.min(H.page, pages);
    const pg = arr.slice((H.page - 1) * H.size, H.page * H.size);
    listEl.innerHTML = pg.map(c =>
      `<div class="hg-vcs-hlrow${c.rev === H.sel ? ' on' : ''}" data-hrev="${esc(c.rev || '')}">` +
        `<span class="hg-vcs-logrev">${esc(c.short || c.rev || '')}${c.deco ? `<span class="hg-vcs-deco">${esc(c.deco)}</span>` : ''}</span>` +
        `<span class="hg-vcs-logmsg">${esc((c.msg || '').slice(0, 44))}</span>` +
        `<span class="hg-vcs-logdt">${esc(_vcsFmtDt(c.date))}</span>` +
        `<span class="hg-vcs-logau">${esc(c.author || '')}</span>` +
        `<span class="hg-vcs-copybtn" data-copy="${esc(c.rev || '')}" title="复制完整修订号">⧉</span>` +
      `</div>`).join('');
    listEl.querySelectorAll('[data-hrev]').forEach(row => {
      row.onclick = (e) => {
        if (e.target.closest('[data-copy]')) return;
        _vcsHistSelect(row.dataset.hrev);
      };
    });
    listEl.querySelectorAll('[data-copy]').forEach(b => b.onclick = (e) => {
      e.stopPropagation();
      try {
        navigator.clipboard.writeText(b.dataset.copy)
          .then(() => showBanner('已复制 ' + b.dataset.copy.slice(0, 12) + '…', 1800))
          .catch(() => showBanner('复制失败', 2000, true));
      } catch (_) { showBanner('复制失败', 2000, true); }
    });
    _vcsHistPager();
  }

  function _vcsHistPager() {
    const H = _vcsHist; if (!H) return;
    const arr = _vcsHistActive();
    const info = H.ov.querySelector('[data-vcs-hpginfo]');
    const cnt = H.ov.querySelector('[data-vcs-hcount]');
    const prev = H.ov.querySelector('[data-vcs-hprev]');
    const next = H.ov.querySelector('[data-vcs-hnext]');
    const n = (arr || []).length;
    const pages = Math.max(1, Math.ceil(n / H.size));
    const total = _vcsHistTotal();
    const atEnd = total != null ? n >= total : (H.exhausted || !(n && n % 100 === 0));
    if (info) info.textContent = n ? `第 ${H.page}/${pages} 页` : '—';
    if (prev) prev.disabled = H.page <= 1;
    if (next) next.disabled = !n || (H.page >= pages && atEnd && !_vcsHistBusy());
    if (cnt) {
      if (!n) cnt.textContent = '';
      else if (total != null) cnt.textContent = `共 ${total} 条`;
      else cnt.textContent = `已载 ${n} 条` + (atEnd ? '（已到最早）' : '');
    }
  }

  function _vcsHistSelect(rev) {
    if (!_vcsHist || !rev) return;
    _vcsHist.sel = rev;
    _vcsHist.ov.querySelectorAll('[data-hrev]').forEach(r =>
      r.classList.toggle('on', r.dataset.hrev === rev));
    _vcsHistDetail(rev);
  }

  function _vcsHistDetail(rev) {
    if (!_vcsHist) return;
    const dEl = _vcsHist.ov.querySelector('[data-vcs-hdetail]');
    if (!dEl) return;
    const c = _vcsHistActive().find(x => x.rev === rev);
    if (!c) { dEl.innerHTML = '<div class="hg-vcs-empty">提交不在当前视图（可能被筛选/翻页移出）</div>'; return; }
    const seq = ++_vcsHist.seq;
    const cached = _vcsHist.files.get(rev);
    const _meta = () =>
      `<div class="hg-vcs-hmeta"><b title="${esc(c.rev)}">${esc(c.short || c.rev)}</b>` +
      (c.deco ? `<span class="hg-vcs-deco">${esc(c.deco)}</span>` : '') +
      `<span>${esc(c.author || '')}</span><span>${esc(_vcsFmtDt(c.date))}</span></div>` +
      `<div class="hg-vcs-hmsg">${esc(c.msg || '')}</div>` +
      `<div class="hg-vcs-sec">改动文件</div>`;
    if (cached) {
      dEl.innerHTML = _meta() + (cached instanceof Error
        ? `<div class="hg-vcs-empty">${esc(cached.message || '加载失败')}（点 ⟳ 刷新重试）</div>`
        : (cached.length
          ? cached.map(f => `<div class="hg-vcs-cfrow" data-hpath="${esc(f.path)}" data-hst="${esc(f.st)}">${esc(f.st)} ${esc(f.path)}</div>`).join('')
          : '<div class="hg-vcs-empty">该提交无文件级改动记录</div>'));
      dEl.querySelectorAll('.hg-vcs-cfrow').forEach(fr =>
        fr.onclick = () => _vcsFileDiffClick(rev, fr.dataset.hpath, fr.dataset.hst, fr));
      return;
    }
    dEl.innerHTML = _meta() + '<div class="hg-vcs-empty">加载文件清单中…</div>';
    fetch('/api/vcs/commit_files', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: _HG.vcs.root, rev }) })
      .then(r => r.json()).then(j => {
        if (!_vcsHist || _vcsHist.sel !== rev || _vcsHist.seq !== seq) return;
        if (!j.ok) {
          _vcsHist.files.set(rev, new Error(j.err || '获取失败'));
        } else {
          const fl = j.files || [];
          _vcsHist.files.set(rev, fl);
          dEl.innerHTML = _meta() + (fl.length
            ? fl.map(f => `<div class="hg-vcs-cfrow" data-hpath="${esc(f.path)}" data-hst="${esc(f.st)}">${esc(f.st)} ${esc(f.path)}</div>`).join('')
              + (fl.length >= 200 ? '<div class="hg-vcs-hlfoot">至多显示前 200 个文件</div>' : '')
            : '<div class="hg-vcs-empty">该提交无文件级改动记录</div>');
          dEl.querySelectorAll('.hg-vcs-cfrow').forEach(fr =>
            fr.onclick = () => _vcsFileDiffClick(rev, fr.dataset.hpath, fr.dataset.hst, fr));
          return;
        }
        _vcsHistDetail(rev);
      }).catch(e => {
        if (!_vcsHist || _vcsHist.sel !== rev || _vcsHist.seq !== seq) return;
        _vcsHist.files.set(rev, new Error(String(e)));
        _vcsHistDetail(rev);
      });
  }

  function _vcsTickStart() {         // v3.5.124（用户需求）：激活期 60s 静默轮询
    if (_vcsTick) return;            // git 改动/外部命令后自动跟上；不用太频繁
    _vcsTick = setInterval(() => {   // 失活自停（目录秒表 _subDirTick 同款惯例）
      if (_sub.active !== _SUB_VCS) { clearInterval(_vcsTick); _vcsTick = null; return; }
      if (!_HG.vcs.busy && _vcsEl) _vcsReload();
    }, 60000);
  }
  function _vcsActivate(force) {     // 激活按需刷新（30s 缓存；写操作后 force 由调用方传 _vcsReload）
    if (!_vcsEl) return;
    _vcsTickStart();
    const now = Date.now();
    if (!force && (_HG.vcs.data || _HG.vcs.busy) && now - _vcsTs < 30000) { _vcsPaint(); return; }
    if (!_HG.vcs.busy) _vcsReload();
    else _vcsPaint();
  }

  // ---- 数据 ----
  function _vcsReload() {
    _HG.vcs.busy = true; _vcsTs = Date.now(); _vcsPaint();
    fetch('/api/tree/roots').then(r => r.json()).then(jr => {
      const roots = (jr && jr.ok) ? (jr.roots || []) : [];
      if (!_HG.vcs.root) {
        const saved = localStorage.getItem('hg-vcs-root');
        _HG.vcs.root = (saved && roots.includes(saved)) ? saved
          : (roots.includes(_HG.cwd) ? _HG.cwd : (roots[0] || ''));
      }
      if (!_HG.vcs.root) {
        _HG.vcs.busy = false;
        if (_vcsEl) _vcsEl.innerHTML = '<div class="hg-vcs-empty">先在左侧文件树「＋」打开一个工程目录，这里会显示它的 git / svn 状态。</div>';
        return;
      }
      localStorage.setItem('hg-vcs-root', _HG.vcs.root);
      return fetch('/api/vcs/status', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: _HG.vcs.root }) }).then(r => r.json()).then(js => {
        _HG.vcs.busy = false;
        _HG.vcs.data = js.ok ? js : { err: js.err || '状态获取失败', vcs: null };
        _vcsPaint();
      });
    }).catch(e => { _HG.vcs.busy = false; _HG.vcs.data = { err: String(e) }; _vcsPaint(); });
  }
  function _vcsReloadLog() {
    // v2：浏览态回补——从已载量一次拿够（reset 语义，弹窗/面板双视图同步）
    if (_vcsLogBusy) return;           // 防连点重复 fetch
    _vcsLogBusy = true;
    const hadLen = (_HG.vcs.log || []).length;
    fetch('/api/vcs/log', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: _HG.vcs.root,
                             limit: Math.max(100, Math.min(500, hadLen || 100)) }) })
      .then(r => r.json()).then(j => {
        _vcsLogBusy = false;
        _HG.vcs.log = j.ok ? (j.commits || []) : null;
        _HG.vcs.total = j.ok ? j.total : undefined;
        _vcsPaint();
        if (_vcsHist && !_vcsHist.querying) {
          // 轻审R1：Error 缓存条目随刷新失效（「点⟳重试」承诺兑现）+当前选中重拉详情
          let _errCleared = false;
          for (const k of Array.from(_vcsHist.files.keys())) {
            if (_vcsHist.files.get(k) instanceof Error) { _vcsHist.files.delete(k); _errCleared = true; }
          }
          _vcsHistPaintList(true);   // 弹窗开着：保选中重绘左列
          if (_errCleared && _vcsHist.sel) _vcsHistDetail(_vcsHist.sel);
        }
      }).catch(() => { _vcsLogBusy = false; });
  }
  function _vcsApi(path, body, label, done) {
    _HG.vcs.busy = true; _vcsPaint();
    fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(Object.assign({ root: _HG.vcs.root }, body || {})) })
      .then(r => r.json().then(j => ({ st: r.status, j })).catch(() => ({ st: r.status, j: null })))
      .then(({ st, j }) => {
        _HG.vcs.busy = false;
        const ok = !!(j && j.ok);
        if (!ok) {
          const why = (j && j.err) ? j.err : ('HTTP ' + st);
          showBanner(label + '失败：' + why, 6000, true);
          if (j && j.out) { _HG.vcs.out = j.out; }
        }
        if (done) done(ok, j || {});
        else if (ok) _vcsReload();
        else _vcsPaint();
      })
      .catch(e => { _HG.vcs.busy = false; showBanner(label + '失败：' + e, 5000, true); _vcsPaint(); });
  }

  // ---- 渲染 ----
  function _vcsPaint() {
    if (!_vcsEl) return;
    const D = _HG.vcs.data;
    const rootsSel = _vcsRootsHtml();
    if (!D) { _vcsEl.innerHTML = rootsSel + '<div class="hg-vcs-loading">加载中…</div>'; return; }
    if (D.err && !D.vcs) {
      _vcsEl.innerHTML = rootsSel +
        `<div class="hg-vcs-empty">${esc(D.err)}</div>` +
        `<div class="hg-vcs-acts"><button class="btn ghost" name="hg_vcs_refresh">⟳ 重试</button></div>`;
      _vcsBind(true);
      return;
    }
    const head = _vcsHeadHtml(D);
    if (!D.vcs) { _vcsEl.innerHTML = rootsSel + head; _vcsBind(false); return; }
    const files = D.files || [];
    const nSel = _HG.vcs.sel.size;
    const canOp = D.tool && !_HG.vcs.busy;
    _vcsEl.innerHTML = rootsSel + head +
      `<div class="hg-vcs-acts">` +
      `<button class="btn ghost" name="hg_vcs_commit" ${canOp && nSel ? '' : 'disabled'}>☑ 提交（${nSel}）</button>` +
      `<button class="btn ghost" name="hg_vcs_update" ${canOp ? '' : 'disabled'}>⇩ ${D.vcs === 'git' ? 'Pull' : 'Update'}</button>` +
      `<span class="hg-vcs-hint">勾选后提交；点行看改动</span></div>` +
      (files.length
        ? `<div class="hg-vcs-files">` + files.map((f, i) => _vcsFileHtml(f, i)).join('') + `</div>`
          + (D.truncated ? `<div class="hg-vcs-more">还有 ${D.truncated} 个文件未显示（用命令行查看）</div>` : '')
        : `<div class="hg-vcs-empty">工作区干净，没有未提交的改动。</div>`) +
      (_HG.vcs.out ? `<div class="hg-vcs-out"><div class="hg-vcs-out-t">上次命令输出</div><pre>${esc(_HG.vcs.out.slice(0, 4000))}</pre></div>` : '') +
      `<div class="hg-vcs-acts"><button class="btn ghost" name="hg_vcs_logbtn" ${canOp ? '' : 'disabled'}>📜 提交历史</button>` +
      `<button class="btn ghost" name="hg_vcs_refresh" ${_HG.vcs.busy ? 'disabled' : ''}>⟳ 刷新</button></div>` +
      // v3.5.133（用户拍板「面板只显示最近20条」）：内嵌列表 20 封顶，全量
      // 走「提交历史」弹窗（_vcsHistOpen）
      (_HG.vcs.log ? `<div class="hg-vcs-sec">最近提交（点行看该提交改了什么）</div>` + _HG.vcs.log.slice(0, 20).map(c =>
        `<div class="hg-vcs-logrow" data-vcsrev="${esc(c.rev || '')}" title="${esc(c.msg || '')}" style="cursor:pointer;">` +
        `<span class="hg-vcs-logrev">${esc(c.short || c.rev || '')}</span>` +
        `<span class="hg-vcs-logmsg">${esc((c.msg || '').slice(0, 60))}</span>` +
        `<span class="hg-vcs-logau">${esc(c.author || '')}</span></div>` +
        `<div class="hg-vcs-cfiles" data-vcsfiles="${esc(c.rev || '')}" style="display:none;"></div>`).join('') +
        (_HG.vcs.log.length > 20
          ? `<div class="hg-vcs-hlfoot">已显示最近 20 / 共 ${_HG.vcs.total || _HG.vcs.log.length} 条——点上方 📜 看全部</div>` : '')
        : '');
    _vcsBind(true);
  }
  function _vcsRootsHtml() {
    return `<div class="hg-vcs-rootrow"><span class="hg-vcs-roott">工程</span>` +
      `<select name="hg_vcs_root" class="hg-vcs-root"><option value="">加载中…</option></select>` +
      `<button class="btn ghost icon-btn" name="hg_vcs_refresh" title="刷新状态" style="flex-shrink:0;">⟳</button></div>`;
  }
  function _vcsHeadHtml(D) {
    if (D.err && D.vcs) {
      return `<div class="hg-vcs-head"><span class="hg-vcs-badge">${esc(D.vcs)}</span>` +
        `<span class="hg-vcs-warn">${esc(D.err)}</span></div>`;
    }
    if (!D.vcs) {
      return `<div class="hg-vcs-head"><span class="hg-vcs-badge none">非版本控制目录</span>` +
        `<span class="hg-vcs-warn">当前工程目录没有 .git / .svn 标记。</span></div>`;
    }
    if (!D.tool) {
      return `<div class="hg-vcs-head"><span class="hg-vcs-badge">${esc(D.vcs)}</span>` +
        `<span class="hg-vcs-warn">${esc(D.vcs)} 客户端未安装——安装 ${esc(D.vcs)} 命令行并重启工具后可用（查看不受影响的数据以缓存为准）。</span></div>`;
    }
    const rev = D.rev ? ' · ' + D.rev : '';
    const ab = (D.vcs === 'git' && (D.ahead || D.behind))
      ? ` · ↑${D.ahead || 0} ↓${D.behind || 0}` : '';
    return `<div class="hg-vcs-head"><span class="hg-vcs-badge ${esc(D.vcs)}">${esc(D.vcs)}</span>` +
      `<span class="hg-vcs-branch">⎇ ${esc(D.branch || '(未知)')}${esc(rev)}${esc(ab)}</span>` +
      `<span class="hg-vcs-count">${(D.files || []).length} 个改动</span></div>`;
  }
  function _vcsFileHtml(f, i) {
    const cls = _VCS_ST_CLS[f.st] || 'm';
    const checked = _HG.vcs.sel.has(f.rel) ? ' checked' : '';
    const ren = f.st === 'R' && f.old_rel
      ? `<span class="hg-vcs-ren">${esc(f.old_rel)} →</span>` : '';
    return `<div class="hg-vcs-frow" data-i="${i}">` +
      `<span class="hg-vcs-st ${cls}" title="${_VCS_ST_TXT[f.st] || f.st}">${esc(f.st)}</span>` +
      `<input type="checkbox" name="hg_vcs_f" class="hg-vcs-ck" data-rel="${esc(f.rel)}"${checked} title="勾选纳入提交">` +
      `<span class="hg-vcs-fpath" title="${esc(f.path)}">${ren}${esc(f.rel)}</span>` +
      (f.st === '?' ? `<button class="btn ghost icon-btn" name="hg_vcs_addone" data-rel="${esc(f.rel)}" title="svn add / git add 纳入版本控制" style="flex-shrink:0;">＋</button>` : '') +
      `</div>`;
  }
  function _vcsBind(paintRoots) {
    if (!_vcsEl) return;
    if (paintRoots) {
      const sel = _vcsEl.querySelector('select[name="hg_vcs_root"]');
      if (sel) {
        fetch('/api/tree/roots').then(r => r.json()).then(j => {
          const roots = (j && j.ok) ? (j.roots || []) : [];
          if (!roots.includes(_HG.vcs.root) && roots.length) _HG.vcs.root = roots[0];
          sel.innerHTML = roots.map(r0 =>
            `<option value="${esc(r0)}"${r0 === _HG.vcs.root ? ' selected' : ''}>${esc(r0)}</option>`).join('')
            || '<option value="">（文件树为空）</option>';
        }).catch(() => {});
        sel.onchange = () => {
          _HG.vcs.root = sel.value; localStorage.setItem('hg-vcs-root', sel.value);
          _HG.vcs.data = null; _HG.vcs.log = null; _HG.vcs.sel = new Set();
          _vcsReload(); _vcsReloadLog();
        };
      }
    }
    _vcsEl.querySelectorAll('[name="hg_vcs_refresh"]').forEach(b =>
      b.onclick = () => { _HG.vcs.sel = new Set(); _vcsReload(); });
    const lb = _vcsEl.querySelector('[name="hg_vcs_logbtn"]');
    // v3.5.133（用户需求「历史提交新增一个弹窗 UI 式显示」）：按钮改开
    // 提交历史弹窗（打开时后台补刷新——v3.5.127「无条件重拉」语义由弹窗
    // 承接：无缓存即拉，有缓存先显后刷）
    if (lb) lb.onclick = () => _vcsHistOpen();
    _vcsEl.querySelectorAll('.hg-vcs-ck').forEach(ck => ck.onchange = () => {
      if (ck.checked) _HG.vcs.sel.add(ck.dataset.rel); else _HG.vcs.sel.delete(ck.dataset.rel);
      const cb = _vcsEl.querySelector('[name="hg_vcs_commit"]');
      if (cb) { cb.textContent = '☑ 提交（' + _HG.vcs.sel.size + '）'; cb.disabled = !_HG.vcs.sel.size; }
    });
    _vcsEl.querySelectorAll('.hg-vcs-frow').forEach(row => {
      row.onclick = (e) => {
        if (e.target.closest('input') || e.target.closest('button')) return;
        const f = (_HG.vcs.data && _HG.vcs.data.files || [])[+row.dataset.i];
        if (!f) return;
        _HG.vcs.busy = true; _vcsPaint();
        fetch('/api/vcs/diff', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: _HG.vcs.root, path: f.rel, st: f.st }) })
          .then(r => r.json()).then(j => {
            _HG.vcs.busy = false; _vcsPaint();
            if (j.ok) { try { buildDiffViewerTab(j.a, j.b); } catch (e) { showBanner('diff 打开失败：' + e, 4000, true); } }
            else showBanner('diff 获取失败：' + (j.err || ''), 4000, true);
          }).catch(e => { _HG.vcs.busy = false; _vcsPaint(); showBanner('diff 获取失败：' + e, 4000, true); });
      };
    });
    // v3.5.131（用户批注「历史提交无法点开查看」）：提交行点击展开该提交
    // 改动文件清单；文件行点击物化父/本修订两版开 diff 对比
    _vcsEl.querySelectorAll('.hg-vcs-logrow[data-vcsrev]').forEach(row => {
      row.onclick = async () => {
        const rev = row.dataset.vcsrev;
        const box = _vcsEl.querySelector('[data-vcsfiles="' + CSS.escape(rev) + '"]');
        if (!rev || !box) return;
        if (box.style.display !== 'none') { box.style.display = 'none'; return; }   // 再点收起
        if (!box.dataset.loaded) {
          box.innerHTML = '<div class="hg-vcs-empty">加载中…</div>';
          box.style.display = 'block';
          try {
            const j = await (await fetch('/api/vcs/commit_files', { method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ root: _HG.vcs.root, rev }) })).json();
            if (!j.ok) { box.innerHTML = '<div class="hg-vcs-empty">' + esc(j.err || '获取失败') + '</div>'; return; }
            box.dataset.loaded = '1';
            box.innerHTML = (j.files || []).map(f =>
              `<div class="hg-vcs-cfrow" data-rev="${esc(rev)}" data-path="${esc(f.path)}" data-st="${esc(f.st)}" title="查看该提交中此文件的改动">${esc(f.st)} ${esc(f.path)}</div>`).join('')
              || '<div class="hg-vcs-empty">该提交无文件级改动记录</div>';
            box.querySelectorAll('.hg-vcs-cfrow').forEach(fr => {
              // 轻审R4：改调公共 _vcsFileDiffClick——旧内联副本无 buildDiffViewerTab
              // 异常防护（unhandled rejection 无提示），与弹窗版已漂移
              fr.onclick = () => _vcsFileDiffClick(rev, fr.dataset.path, fr.dataset.st, fr);
            });
          } catch (e) {
            box.innerHTML = '<div class="hg-vcs-empty">获取失败：' + esc(String(e)) + '</div>';
          }
        } else box.style.display = 'block';
      };
    });
    _vcsEl.querySelectorAll('[name="hg_vcs_addone"]').forEach(b => b.onclick = (e) => {
      e.stopPropagation();
      const rel = b.dataset.rel;
      const v = (_HG.vcs.data || {}).vcs;
      hgModal('纳入版本控制',
        `<div class="hg-modal-body">将执行 ${esc(v === 'svn' ? 'svn add' : 'git add')}：\n${esc(rel)}</div>`,
        [{ label: '取消', value: false }, { label: '执行', primary: true, value: true }])
        .then(ok => {
          if (!ok) return;
          _vcsApi('/api/vcs/add', { paths: [rel] }, 'add');
        });
    });
    const ub = _vcsEl.querySelector('[name="hg_vcs_update"]');
    if (ub) ub.onclick = () => {
      const v = (_HG.vcs.data || {}).vcs;
      const cmd = v === 'git' ? 'git pull --ff-only' : 'svn update（冲突 postpone 保现场）';
      hgModal(v === 'git' ? 'Pull 拉取更新' : 'Update 更新',
        `<div class="hg-modal-body">将在 ${esc(_HG.vcs.root)}\n执行 ${esc(cmd)}</div>`,
        [{ label: '取消', value: false }, { label: '执行', primary: true, value: true }])
        .then(ok => {
        if (!ok) return;
        _vcsApi('/api/vcs/update', {}, '更新', (ok2, j) => {
          if (j && j.out) _HG.vcs.out = j.out;
          if (ok2 && j.conflicts && j.conflicts.length)
            showBanner('⚠ 更新引入冲突 ' + j.conflicts.length + ' 个——请用 svn/git 命令行处理', 8000, true);
          _vcsReload();
        });
      });
    };
    const cb = _vcsEl.querySelector('[name="hg_vcs_commit"]');
    if (cb) cb.onclick = () => _vcsCommitModal();
  }
  function _vcsCommitModal() {
    const D = _HG.vcs.data || {};
    const all = D.files || [];
    const selPaths = all.filter(f => _HG.vcs.sel.has(f.rel));
    if (!selPaths.length) { showBanner('先勾选要提交的文件', 3000, true); return; }
    const nNew = selPaths.filter(f => f.st === '?').length;
    const ov = document.createElement('div');
    ov.className = 'hg-modal-ov';
    ov.innerHTML =
      `<div class="hg-modal"><div class="hg-modal-title">提交 ${selPaths.length} 个文件（${esc(D.vcs || '')}）</div>` +
      `<div class="hg-modal-body">` +
      selPaths.map(f => `<div class="hg-vcs-cfile"><span class="hg-vcs-st ${_VCS_ST_CLS[f.st] || 'm'}">${esc(f.st)}</span>${esc(f.rel)}</div>`).join('') +
      (nNew ? `<div class="hg-vcs-cnew">⚠ 其中 ${nNew} 个新文件将自动 ${D.vcs === 'svn' ? 'svn add' : 'git add'} 纳入</div>` : '') +
      `<textarea name="hg_vcs_msg" class="hg-vcs-msg" rows="3" placeholder="提交说明（必填，Ctrl+Enter 提交）" spellcheck="false"></textarea>` +
      `</div><div class="hg-modal-acts"></div></div>`;
    const acts = ov.querySelector('.hg-modal-acts');
    const ta = ov.querySelector('textarea[name="hg_vcs_msg"]');
    const close = () => ov.remove();
    const doCommit = () => {
      const msg = ta.value.trim();
      if (!msg) { showBanner('提交说明必填', 3000, true); ta.focus(); return; }
      close();
      _vcsApi('/api/vcs/commit', { paths: selPaths.map(f => f.rel), message: msg },
              '提交', (ok2, j) => {
        if (j && j.out) _HG.vcs.out = j.out;
        if (ok2) { _HG.vcs.sel = new Set(); showBanner('已提交' + (j.rev ? ' ' + j.rev : ''), 3500); }
        _vcsReload(); _vcsReloadLog();
      });
    };
    const mk = (label, primary, fn) => {
      const b = document.createElement('button');
      b.className = 'btn' + (primary ? ' primary' : ''); b.textContent = label;
      b.onclick = fn; acts.appendChild(b);
    };
    mk('取消', false, close);
    mk('提交', true, doCommit);
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doCommit(); }
    });
    _hgWrap.appendChild(ov);
    ta.focus();
  }
