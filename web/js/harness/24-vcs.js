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
    _vcsEl = null;
    _HG.vcs = { root: (_HG.vcs || {}).root || '', data: null, log: null,
                out: '', busy: false, sel: new Set(), ts: 0 };
  }
  let _vcsTick = null;
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
    if (_vcsLogBusy) return;           // 防连点重复 fetch
    _vcsLogBusy = true;
    fetch('/api/vcs/log', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: _HG.vcs.root, limit: 30 }) })
      .then(r => r.json()).then(j => {
        _vcsLogBusy = false;
        _HG.vcs.log = j.ok ? (j.commits || []) : null;
        _vcsPaint();
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
      `<div class="hg-vcs-acts"><button class="btn ghost" name="hg_vcs_logbtn" ${canOp ? '' : 'disabled'}>📜 最近提交</button>` +
      `<button class="btn ghost" name="hg_vcs_refresh" ${_HG.vcs.busy ? 'disabled' : ''}>⟳ 刷新</button></div>` +
      (_HG.vcs.log ? `<div class="hg-vcs-sec">最近提交（点行看该提交改了什么）</div>` + _HG.vcs.log.map(c =>
        `<div class="hg-vcs-logrow" data-vcsrev="${esc(c.rev || '')}" title="${esc(c.msg || '')}" style="cursor:pointer;">` +
        `<span class="hg-vcs-logrev">${esc(c.short || c.rev || '')}</span>` +
        `<span class="hg-vcs-logmsg">${esc((c.msg || '').slice(0, 60))}</span>` +
        `<span class="hg-vcs-logau">${esc(c.author || '')}</span></div>` +
        `<div class="hg-vcs-cfiles" data-vcsfiles="${esc(c.rev || '')}" style="display:none;"></div>`).join('')
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
    // v3.5.127（用户实锤「提交后点刷新不显示最新提交，要点两次」）：旧逻辑
    // 有数据时第一次点只清空不重拉——无条件重拉才是「刷新」语义
    if (lb) lb.onclick = () => _vcsReloadLog();
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
              fr.onclick = async () => {
                fr.style.opacity = '.5';
                try {
                  const j2 = await (await fetch('/api/vcs/commit_diff', { method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ root: _HG.vcs.root, rev,
                                           path: fr.dataset.path, st: fr.dataset.st }) })).json();
                  if (j2.ok) buildDiffViewerTab(j2.a, j2.b);
                  else showBanner('提交 diff 获取失败：' + (j2.err || ''), 4000, true);
                } catch (e) { showBanner('提交 diff 获取失败：' + e, 4000, true); }
                fr.style.opacity = '';
              };
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
