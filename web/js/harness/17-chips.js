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
    if (b) b.textContent = _HG.perm === 'confirm' ? '🛡 变更前确认 ▾' : '🛡';   // v3.4.27（用户定调）：权限 chip 图标模式——默认态不显字，非默认显字提醒
  }
  function thinkChipLabel() {
    const b = _hgQ('[data-hg-think]'); if (b) b.textContent = '💭 ' + (_HG.thinkLv ? '思考·' + _HG_THINKS[_HG.thinkLv] : '思考') + ' ▾';
  }
