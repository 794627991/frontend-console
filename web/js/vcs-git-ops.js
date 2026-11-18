// ============================================================
// a650：版本面板的分支 / stash / 标签 / 智能操作对话框
//
// 设计原则（与 vcs-panel.js 既有风格一致）：
//   · 一律自建弹窗（不改 hgModal，避免影响其它模块），点击遮罩关闭
//   · 所有写操作二次确认；丢弃改动额外要求输入确认（不可逆）
//   · 后端 409（工作区脏、需 allow_* 标志）要如实呈现，绝不静默
// ============================================================

let _vcsDlg = null;

function _vcsDlgClose() {
  _vcsCfmClose();                  // 确认框盖在上面，一起收，避免孤儿浮层
  if (_vcsDlg) { _vcsDlg.remove(); _vcsDlg = null; }
}

/** 建一个通用弹窗骨架，返回 {ov, body, acts, close} */
function _vcsDlgShell(title, sub) {
  _vcsDlgClose();
  const ov = document.createElement('div');
  ov.className = 'hg-vcs-rdlg';
  ov.innerHTML =
    `<div class="hg-vcs-rdlg-card">` +
    `<div class="hg-vcs-rdlg-title">${esc(title)}` +
    (sub ? `<span class="hg-vcs-rdlg-sub2">${esc(sub)}</span>` : '') +
    `<button class="btn ghost hg-vcs-rdlg-x" name="dlg_close">✕</button></div>` +
    `<div class="hg-vcs-rdlg-body"></div>` +
    `<div class="hg-vcs-rdlg-acts"></div></div>`;
  document.body.appendChild(ov);
  ov.addEventListener('click', (e) => { if (e.target === ov) _vcsDlgClose(); });
  const close = () => _vcsDlgClose();
  ov.querySelector('[name="dlg_close"]').onclick = close;
  _vcsDlg = ov;
  return {
    ov,
    body: ov.querySelector('.hg-vcs-rdlg-body'),
    acts: ov.querySelector('.hg-vcs-rdlg-acts'),
    close,
  };
}

function _vcsPost(path, body) {
  return fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ root: VCS.root }, body || {})),
  }).then(r => r.json().then(j => Object.assign({ _status: r.status }, j)))
    .catch(e => ({ ok: false, err: String(e) }));
}

// a650：自建对话框里的二次确认**不能**用 hgModal——它的遮罩 z-index 是 40，
// 而 .hg-vcs-rdlg 是 10060，确认框会被开着的分支/标签弹窗整块盖住，
// 用户看到的是「点了没反应」。这里给一份同层级（更高）的实现。
let _vcsCfm = null;
function _vcsAsk(title, bodyHtml, buttons) {
  return new Promise((resolve) => {
    _vcsCfmClose();
    const ov = document.createElement('div');
    ov.className = 'hg-vcs-rdlg hg-vcs-cfm';
    ov.innerHTML =
      `<div class="hg-vcs-rdlg-card">` +
      `<div class="hg-vcs-rdlg-title">${esc(title)}</div>` +
      `<div class="hg-modal-body hg-pre">${bodyHtml}</div>` +
      `<div class="hg-vcs-rdlg-acts"></div></div>`;
    document.body.appendChild(ov);
    _vcsCfm = ov;
    const acts = ov.querySelector('.hg-vcs-rdlg-acts');
    let done = false;
    const fin = (v) => {
      if (done) return;
      done = true;
      try { document.removeEventListener('keydown', onKey); } catch (_) {}
      try { ov.remove(); } catch (_) {}
      if (_vcsCfm === ov) _vcsCfm = null;
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); fin(null); }
    };
    document.addEventListener('keydown', onKey);
    ov.addEventListener('click', (e) => { if (e.target === ov) fin(null); });
    (buttons || []).forEach((b) => {
      const btn = document.createElement('button');
      btn.className = 'btn' + (b.primary ? ' primary' : '');
      btn.textContent = b.label;
      btn.onclick = () => fin(b.value);
      acts.appendChild(btn);
    });
    const first = acts.querySelector('.btn.primary') || acts.querySelector('.btn');
    if (first) first.focus();
  });
}
function _vcsCfmClose() {
  if (_vcsCfm) { try { _vcsCfm.remove(); } catch (_) {} _vcsCfm = null; }
}
function _vcsConfirm(title, bodyHtml, okLabel, cancelLabel) {
  return _vcsAsk(title, bodyHtml, [
    { label: cancelLabel || '取消', value: false },
    { label: okLabel || '确认', value: true, primary: true },
  ]);
}

// ==================== 分支对话框 ====================
function _vcsBranchDialog() {
  const D = VCS.data || {};
  if (D.vcs !== 'git') {
    showBanner('svn 没有分支概念（可查看历史 / 修订号）', 3500, true);
    return;
  }
  const ui = _vcsDlgShell('分支', VCS.root || '');
  ui.body.innerHTML = '<div class="hg-vcs-rdlg-msg">读取分支列表…</div>';

  function paint() {
    _vcsPost('/api/vcs/branches').then(j => {
      if (!j.ok) {
        ui.body.innerHTML =
          `<div class="hg-vcs-rdlg-msg err">${esc(j.err || '读取失败')}</div>`;
        return;
      }
      const local = j.local || [];
      const remote = j.remote || [];
      ui.body.innerHTML =
        (j.warn ? `<div class="hg-vcs-rdlg-msg warn">${esc(j.warn)}</div>` : '') +
        (j.detached
          ? `<div class="hg-vcs-rdlg-msg warn">当前处于游离 HEAD（未在任何分支上）——切换分支可回到正常状态。</div>`
          : '') +
        `<div class="hg-vcs-brlist">` +
        (local.length ? local.map(b => {
          const cur0 = b.current ? ' cur' : '';
          const ab = (b.ahead || b.behind)
            ? `<span class="hg-vcs-brab">${b.ahead ? '↑' + b.ahead : ''}${b.behind ? ' ↓' + b.behind : ''}</span>` : '';
          return `<div class="hg-vcs-brrow${cur0}" data-br="${esc(b.name)}">` +
            `<span class="hg-vcs-brname">${b.current ? '● ' : '○ '}${esc(b.name)}</span>` +
            `<span class="hg-vcs-brrev">${esc(b.rev || '')}</span>${ab}` +
            `<span class="hg-vcs-brsub" title="${esc(b.subject || '')}">${esc((b.subject || '').slice(0, 40))}</span>` +
            `<button class="btn ghost hg-vcs-brgo" data-go="${esc(b.name)}"` +
            `${b.current ? ' disabled' : ''}>切换</button>` +
            `<button class="btn ghost hg-vcs-brdel" data-del="${esc(b.name)}"` +
            `${b.current ? ' disabled' : ''} title="删除分支">✕</button></div>`;
        }).join('') : '<div class="hg-vcs-rdlg-msg">暂无本地分支</div>') +
        `</div>` +
        (remote.length
          ? `<div class="hg-vcs-brsec">远程分支（${remote.length}）</div>` +
            `<div class="hg-vcs-brlist">` + remote.map(b =>
              `<div class="hg-vcs-brrow"><span class="hg-vcs-brname">${esc(b.name)}</span>` +
              `<span class="hg-vcs-brrev">${esc(b.rev || '')}</span>` +
              `<span class="hg-vcs-brsub" title="${esc(b.subject || '')}">${esc((b.subject || '').slice(0, 40))}</span></div>`
            ).join('') + `</div>`
          : '');

      ui.body.querySelectorAll('[data-go]').forEach(b => b.onclick = () => {
        const name = b.dataset.go;
        _vcsBranchSwitch(name, paint);
      });
      ui.body.querySelectorAll('[data-del]').forEach(b => b.onclick = () => {
        const name = b.dataset.del;
        _vcsConfirm('删除分支',
          `将执行 <code>git branch -d ${esc(name)}</code>\n` +
          `未合并的分支会被拒绝——确需强删请用命令行 -D。`, '删除')
          .then(ok => {
            if (!ok) return;
            _vcsPost('/api/vcs/branch/delete', { name }).then(r => {
              if (!r.ok) { showBanner(r.err || '删除失败', 5000, true); return; }
              showBanner('已删除分支 ' + name, 2500);
              paint(); _vcsReload();
            });
          });
      });
    });
  }

  ui.acts.innerHTML =
    `<input class="hg-vcs-rdlg-input" name="newbr" placeholder="新分支名（从当前 HEAD 创建）" spellcheck="false">` +
    `<button class="btn ghost" name="mkbr">新建</button>` +
    `<button class="btn ghost" name="refresh">刷新</button>`;
  const nb = ui.acts.querySelector('[name="newbr"]');
  const mk = () => {
    const name = (nb.value || '').trim();
    if (!name) { showBanner('请填分支名', 2500, true); return; }
    _vcsPost('/api/vcs/branch/create', { name }).then(r => {
      if (!r.ok) { showBanner(r.err || '创建失败', 5000, true); return; }
      showBanner('已创建分支 ' + name, 2500);
      nb.value = ''; paint();
    });
  };
  ui.acts.querySelector('[name="mkbr"]').onclick = mk;
  nb.onkeydown = (e) => { if (e.key === 'Enter') mk(); };
  ui.acts.querySelector('[name="refresh"]').onclick = paint;
  paint();
}

/** 切换分支；工作区脏时（409）给三条出路 */
function _vcsBranchSwitch(name, after) {
  _vcsPost('/api/vcs/branch/switch', { name }).then(j => {
    if (j.ok) {
      showBanner('已切换到 ' + (j.branch || name), 2500);
      if (after) after();
      _vcsReload(); _vcsReloadLog();
      return;
    }
    if (j._status === 409 && j.dirty) {
      const n = (j.files || []).length;
      _vcsAsk('工作区有未提交改动',
        `切换到 <code>${esc(name)}</code> 前需要处理 ` +
        `<b>${n}</b> 个改动：\n\n` +
        (j.files || []).slice(0, 12).map(f => '· ' + esc(f)).join('\n') +
        (n > 12 ? `\n…另有 ${n - 12} 个` : '') +
        `\n\n选择处理方式：`,
        [
          { label: '取消', value: false },
          { label: '先 Stash', value: 'stash' },
          { label: '强制交给 git', value: 'ignore' },
        ]).then(act => {
          if (!act) return;
          if (act === 'stash') {
            _vcsPost('/api/vcs/stash', { action: 'push', message: '切换分支前自动暂存' })
              .then(r => {
                if (!r.ok) { showBanner(r.err || 'stash 失败', 5000, true); return; }
                showBanner('已暂存改动，正在切换…', 2000);
                _vcsPost('/api/vcs/branch/switch', { name }).then(j2 => {
                  if (!j2.ok) { showBanner(j2.err || '切换失败', 6000, true); return; }
                  showBanner('已切换到 ' + name + '（改动在 Stash 里，记得取回）', 5000);
                  if (after) after();
                  _vcsReload(); _vcsReloadLog();
                });
              });
          } else if (act === 'ignore') {
            _vcsPost('/api/vcs/branch/switch', { name, dirty: 'ignore' }).then(j2 => {
              if (!j2.ok) { showBanner(j2.err || '切换失败', 8000, true); return; }
              showBanner('已切换到 ' + name, 2500);
              if (after) after();
              _vcsReload(); _vcsReloadLog();
            });
          }
        });
      return;
    }
    showBanner(j.err || '切换失败', 6000, true);
  });
}

// ==================== Stash 对话框 ====================
function _vcsStashDialog() {
  const D = VCS.data || {};
  if (D.vcs !== 'git') { showBanner('svn 无 stash', 3000, true); return; }
  const ui = _vcsDlgShell('Stash 暂存', VCS.root || '');
  ui.body.innerHTML = '<div class="hg-vcs-rdlg-msg">读取…</div>';

  function paint() {
    _vcsPost('/api/vcs/stash', { action: 'list' }).then(j => {
      if (!j.ok) {
        ui.body.innerHTML = `<div class="hg-vcs-rdlg-msg err">${esc(j.err || '读取失败')}</div>`;
        return;
      }
      const list = j.stashes || [];
      ui.body.innerHTML = list.length
        ? `<div class="hg-vcs-brlist">` + list.map((s, i) =>
            `<div class="hg-vcs-strow">` +
            `<span class="hg-vcs-brrev">${esc(s.ref)}</span>` +
            `<span class="hg-vcs-brsub">${esc((s.msg || '').slice(0, 60))}</span>` +
            `<button class="btn ghost" data-pop="${i}">取出</button>` +
            `<button class="btn ghost" data-drop="${i}">删除</button></div>`).join('') + `</div>`
        : '<div class="hg-vcs-rdlg-msg">暂无 stash</div>';
      ui.body.querySelectorAll('[data-pop]').forEach(b => b.onclick = () => {
        const i = +b.dataset.pop;
        _vcsPost('/api/vcs/stash', { action: 'pop', index: i }).then(r => {
          if (!r.ok) { showBanner(r.err || '取出失败（可能有冲突）', 6000, true); return; }
          showBanner('已取出 stash', 2500); paint(); _vcsReload();
        });
      });
      ui.body.querySelectorAll('[data-drop]').forEach(b => b.onclick = () => {
        const i = +b.dataset.drop;
        _vcsConfirm('删除 stash', '删除后这些改动将无法找回，确认？', '删除')
          .then(ok => {
            if (!ok) return;
            _vcsPost('/api/vcs/stash', { action: 'drop', index: i }).then(r => {
              if (!r.ok) { showBanner(r.err || '删除失败', 5000, true); return; }
              paint();
            });
          });
      });
    });
  }

  ui.acts.innerHTML =
    `<input class="hg-vcs-rdlg-input" name="stmsg" placeholder="说明（可选）" spellcheck="false">` +
    `<button class="btn ghost" name="push">存入当前改动</button>` +
    `<button class="btn ghost" name="refresh">刷新</button>`;
  ui.acts.querySelector('[name="push"]').onclick = () => {
    const msg = ui.acts.querySelector('[name="stmsg"]').value;
    _vcsPost('/api/vcs/stash', { action: 'push', message: msg }).then(r => {
      if (!r.ok) { showBanner(r.err || 'stash 失败', 5000, true); return; }
      showBanner('已暂存', 2000);
      ui.acts.querySelector('[name="stmsg"]').value = '';
      paint(); _vcsReload();
    });
  };
  ui.acts.querySelector('[name="refresh"]').onclick = paint;
  paint();
}

// ==================== 丢弃改动（不可逆，双重确认）====================
function _vcsDiscardSelected() {
  const files = (VCS.data && VCS.data.files) || [];
  const sel = files.filter(f => VCS.sel.has(f.rel));
  if (!sel.length) { showBanner('先勾选要丢弃的文件', 2500, true); return; }
  _vcsConfirm('丢弃工作区改动（不可逆）',
    `以下 <b>${sel.length}</b> 个文件的未提交改动将被丢弃：\n\n` +
    sel.slice(0, 15).map(f => '· ' + esc(f.rel)).join('\n') +
    (sel.length > 15 ? `\n…另有 ${sel.length - 15} 个` : '') +
    `\n\n执行前会自动快照到数据目录，但仍建议先确认。\n继续？`, '确认丢弃')
    .then(ok => {
      if (!ok) return;
      _vcsPost('/api/vcs/discard', {
        paths: sel.map(f => f.rel), confirm: true,
      }).then(j => {
        if (!j.ok) {
          // 部分失败时 removed 可能有内容——如实说清做了什么、没做什么
          const done = (j.removed || []).length;
          showBanner('丢弃失败' + (done ? '（已处理 ' + done + ' 项）' : '') +
            '：' + (j.err || ''), 9000, true);
          VCS.sel = new Set();
          _vcsReload();
          return;
        }
        let msg = '已丢弃 ' + sel.length + ' 个改动';
        if (j.snapshot) msg += '（快照：' + j.snapshot + '）';
        else if (j.snapshot_err) msg += '（本次没有快照）';
        showBanner(msg + (j.snapshot_err ? '　注意：' + j.snapshot_err : ''),
          j.snapshot_err ? 9000 : 6000, !!j.snapshot_err);
        VCS.sel = new Set();
        _vcsReload();
      });
    });
}

// ==================== 标签对话框 ====================
function _vcsTagsDialog() {
  const D = VCS.data || {};
  if (D.vcs !== 'git') { showBanner('svn 用 tags 目录约定，无标签命令', 4000, true); return; }
  const ui = _vcsDlgShell('标签', VCS.root || '');
  ui.body.innerHTML = '<div class="hg-vcs-rdlg-msg">读取…</div>';

  function paint() {
    _vcsPost('/api/vcs/tags', { action: 'list' }).then(j => {
      if (!j.ok) {
        ui.body.innerHTML = `<div class="hg-vcs-rdlg-msg err">${esc(j.err || '读取失败')}</div>`;
        return;
      }
      const tags = j.tags || [];
      ui.body.innerHTML = tags.length
        ? `<div class="hg-vcs-brlist">` + tags.map(t =>
            `<div class="hg-vcs-strow"><span class="hg-vcs-brname">${esc(t.name)}</span>` +
            `<span class="hg-vcs-brrev">${esc(t.rev || '')}</span>` +
            `<span class="hg-vcs-brsub">${esc((t.msg || '').slice(0, 50))}</span>` +
            `<button class="btn ghost" data-deltag="${esc(t.name)}">✕</button></div>`).join('') + `</div>`
        : '<div class="hg-vcs-rdlg-msg">暂无标签</div>';
      ui.body.querySelectorAll('[data-deltag]').forEach(b => b.onclick = () => {
        const name = b.dataset.deltag;
        _vcsConfirm('删除标签', `删除标签 <code>${esc(name)}</code>？（不删提交）`, '删除')
          .then(ok => {
            if (!ok) return;
            _vcsPost('/api/vcs/tags', { action: 'delete', name }).then(r => {
              if (!r.ok) { showBanner(r.err || '删除失败', 5000, true); return; }
              paint();
            });
          });
      });
    });
  }

  ui.acts.innerHTML =
    `<input class="hg-vcs-rdlg-input" name="tname" placeholder="标签名（如 v1.0.0）" spellcheck="false">` +
    `<input class="hg-vcs-rdlg-input" name="tmsg" placeholder="附注（可选，填了就是含注释的标签）" spellcheck="false">` +
    `<button class="btn ghost" name="mktag">创建</button>` +
    `<button class="btn ghost" name="refresh">刷新</button>`;
  ui.acts.querySelector('[name="mktag"]').onclick = () => {
    const name = (ui.acts.querySelector('[name="tname"]').value || '').trim();
    const message = (ui.acts.querySelector('[name="tmsg"]').value || '').trim();
    if (!name) { showBanner('请填标签名', 2500, true); return; }
    _vcsPost('/api/vcs/tags', { action: 'create', name, message }).then(r => {
      if (!r.ok) { showBanner(r.err || '创建失败', 5000, true); return; }
      showBanner('已创建标签 ' + name, 2500);
      ui.acts.querySelector('[name="tname"]').value = '';
      ui.acts.querySelector('[name="tmsg"]').value = '';
      paint();
    });
  };
  ui.acts.querySelector('[name="refresh"]').onclick = paint;
  paint();
}
