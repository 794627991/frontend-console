// harness chips.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function fetchModels() {
    return fetch('/api/harness/models').then(r => r.json())
      .then(j => { if (j && j.ok) { _HG.models = j; renderList(); } return _HG.models; })
      .catch(() => _HG.models || {models: [], default: null});
  }
  function _hgSaveCwd(dir) {
    try { dir ? localStorage.setItem('hg-last-cwd', dir)
             : localStorage.removeItem('hg-last-cwd'); } catch(_) {}
  }
  function _hgCwdHist() {
    try { return JSON.parse(localStorage.getItem('hg-cwd-hist') || '[]') || []; } catch(_) { return []; }
  }
  function _hgCwdPush(dir) {
    const h = _hgCwdHist().filter(x => x !== dir);
    h.unshift(dir);
    try { localStorage.setItem('hg-cwd-hist', JSON.stringify(h.slice(0, 6))); } catch(_) {}
  }
  function projChipLabel() {
    const el = _hgWrap.querySelector('[data-hg-projname]');
    if (el) el.textContent = _HG.cwd ? (_HG.cwd.split(/[\\/]/).pop() || _HG.cwd) : '选择项目';
  }
  function setProj(dir) {
    _HG.cwd = dir; _hgSaveCwd(dir); _hgCwdPush(dir); projChipLabel();
    if (!_HG.dirty) {
      if (_HG.sid) {
        fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
        switchTo(null);
      }
      showBanner('新会话将打开在 ' + dir, 2600);
    } else {
      showBanner('当前会话已有对话，新会话将打开在 ' + dir, 3200);
    }
  }
  const _HG_PERMS = {auto: '自动执行', confirm: '变更前确认'};
  const _HG_THINKS = {low: '低', medium: '中', high: '高', max: '最高'};
  const _HG_THINK_TOK = {low: '4K', medium: '10K', high: '20K', max: '32K'};
  function permChipLabel() {
    const b = _hgQ('[data-hg-perm]');
        if (b) {
      // a261：SVG 图标（ICO.shield）；确认态显字提醒（v3.4.27 语义不变）
      b.innerHTML = _HG.perm === 'confirm'
        ? (window.ICO ? ICO.shield : '') + ' 变更前确认 ▾'
        : (window.ICO ? ICO.shield : '');
      b.classList.toggle('perm-confirm', _HG.perm === 'confirm');   // v3.4.31：确认态橙色醒目
    }   // v3.4.27（用户定调）：权限 chip 图标模式——默认态不显字，非默认显字提醒
  }
  function thinkChipLabel() {
    const b = _hgQ('[data-hg-think]'); if (b) b.textContent = (_HG.thinkLv ? _HG_THINKS[_HG.thinkLv] : '默认') + ' ▾';   // v3.4.33：只显档位值（ZCode 同款）
  }

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._HG_PERMS = _HG_PERMS;
window._HG_THINKS = _HG_THINKS;
window._HG_THINK_TOK = _HG_THINK_TOK;
window._hgCwdHist = _hgCwdHist;
window._hgSaveCwd = _hgSaveCwd;
window.fetchModels = fetchModels;
window.permChipLabel = permChipLabel;
window.projChipLabel = projChipLabel;
window.setProj = setProj;
window.thinkChipLabel = thinkChipLabel;
