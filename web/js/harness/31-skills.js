// 31-skills.js — 技能仓库（全屏独立页：发现/已安装/详情/离线包/汉化）。
// 数据源：后端 /api/skills/*（src/skills_repo.py，skills.sh 网页适配）。
// 交互约定：卡片渐进汉化（前 24 条批量元数据翻译）、中文搜索自动英译、
// 已安装区勾选导出离线包；详情页 markdown-it 渲染 + 中英切换。
'use strict';

const SK = {
  root: null, view: 'home', tab: 'top', topic: '全部', q: '', qEn: '',
  rows: null, inst: null, sel: new Set(), updates: {},   // updates: skill->bool
  det: null, detZh: false, loading: false,
};

function _skEsc(s) {
  return esc(String(s == null ? '' : s));
}

function _skIcon(name, size) {
  // 彩色首字母色块（参考图同款；色相由名字 hash 决定，稳定不闪）
  let h = 0;
  for (const ch of String(name || '?')) h = (h * 31 + ch.charCodeAt(0)) % 360;
  const c = (String(name || '?').trim()[0] || '?').toUpperCase();
  return '<span class="sk-ico" style="background:hsl(' + h + ',55%,42%);'
    + 'width:' + (size || 34) + 'px;height:' + (size || 34) + 'px;font-size:'
    + Math.round((size || 34) * 0.5) + 'px">' + _skEsc(c) + '</span>';
}

function _skFetch(url, opts) {
  return fetch(url, opts).then(r => r.json()).catch(() => ({ ok: false, err: '网络请求失败' }));
}

// ==================== 开关与骨架 ====================

function skRepoOpen() {
  if (!_hgWrap) { showBanner('请先进入 Claude 对话页', 2500, true); return; }
  if (!SK.root) {
    SK.root = document.createElement('div');
    SK.root.className = 'sk-repo';
    SK.root.innerHTML =
      '<div class="sk-top">' +
        '<button class="sk-back" data-sk-back title="返回会话">←</button>' +
        '<div class="sk-title"><b>技能仓库</b><span id="skSub">发现 · 安装 · 管理 Claude 技能</span></div>' +
        '<span class="sk-status" id="skStatus"></span>' +
        '<input class="sk-search" id="skSearch" placeholder="搜索技能（支持中文，自动英译）…">' +
        '<button class="sk-btn" data-sk-import title="导入离线包（内网一键安装）">📦 导入离线包</button>' +
        '<input type="file" id="skFile" accept=".zip" style="display:none">' +
      '</div>' +
      '<div class="sk-body" id="skBody"></div>';
    _hgWrap.appendChild(SK.root);
    SK.root.addEventListener('click', _skOnClick);
    SK.root.addEventListener('change', _skOnChange);
    SK.root.addEventListener('keydown', _skOnKey);
  }
  SK.root.classList.add('show');
  skLoadStatus();
  skLoadHome();
}

function skRepoClose() {
  if (SK.root) SK.root.classList.remove('show');
}

function _skOnClick(e) {
  const t = e.target;
  const hit = s => t.closest(s);
  if (hit('[data-sk-back]')) { SK.view === 'detail' ? skShowHome() : skRepoClose(); return; }
  if (hit('[data-sk-import]')) { const f = SK.root.querySelector('#skFile'); f.value = ''; f.click(); return; }
  const tab = hit('[data-sk-tab]');
  if (tab) { SK.tab = tab.dataset.skTab; skLoadHome(); return; }
  const tp = hit('[data-sk-topic]');
  if (tp) { SK.topic = tp.dataset.skTopic; skRenderHome(); return; }
  const card = hit('[data-sk-key]');
  if (card && !hit('button,input,label')) { skOpenDetail(card.dataset.skKey); return; }
  const ins = hit('[data-sk-install]');
  if (ins) { skInstall(ins.dataset.skInstall, ins); return; }
  const un = hit('[data-sk-uninstall]');
  if (un) { skUninstall(un.dataset.skUninstall); return; }
  const dis = hit('[data-sk-disable]');
  if (dis) { skDisable(dis.dataset.skDisable, dis.dataset.skOff === '1'); return; }
  if (hit('[data-sk-updates]')) { skCheckUpdates(); return; }
  if (hit('[data-sk-export]')) { skExport(); return; }
  if (hit('[data-sk-zh]')) { skDetailZh(); return; }
  if (hit('[data-sk-do-install]')) { skInstall(SK.det ? SK.det.key : '', hit('[data-sk-do-install]')); return; }
}

function _skOnChange(e) {
  if (e.target.id === 'skFile' && e.target.files[0]) skPackInspect(e.target.files[0]);
}

function _skOnKey(e) {
  if (e.target.id !== 'skSearch') return;
  if (e.key === 'Enter') {
    SK.q = e.target.value.trim();
    skLoadHome();
  }
}

// ==================== 数据加载 ====================

function skLoadStatus() {
  const el = SK.root.querySelector('#skStatus');
  _skFetch('/api/skills/status').then(r => {
    if (!r.ok) { el.innerHTML = '<i class="dot bad"></i>状态未知'; return; }
    const dot = r.skills_sh ? (r.github ? 'ok' : 'mid') : 'bad';
    const src = r.skills_sh ? 'skills.sh' : (r.github ? 'GitHub 兜底' : '不可达');
    el.innerHTML = '<i class="dot ' + dot + '"></i>' + _skEsc(src) +
      ' · 汉化:' + _skEsc(r.light_model || '未配置');
  });
}

function skLoadHome() {
  SK.loading = true;
  skRenderHome();
  const q = SK.q;
  const zh = /[一-鿿]/.test(q);
  const go = en => {
    _skFetch('/api/skills/registry?tab=' + encodeURIComponent(SK.tab) +
             '&q=' + encodeURIComponent(en || q)).then(r => {
      SK.loading = false;
      SK.rows = r.ok ? r.rows : null;
      if (r.ok) skZhPatch();
      skRenderHome();
      if (!r.ok) showBanner('榜单拉取失败：' + (r.err || ''), 3500, true);
    });
  };
  if (zh) {   // 中文搜索词→英译再过滤（失败降级原文过滤）
    _skFetch('/api/skills/translate', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'search', q }) })
      .then(r => go(r.ok ? r.en : ''));
  } else go('');
}

// 渐进汉化：前 24 条有英文 desc 的卡片批量翻译（结果进后端缓存，
// 下次 registry 直带 zh——本次先 patch 渲染）
function skZhPatch() {
  const need = (SK.rows || []).slice(0, 24)
    .filter(r => r.desc && !r.zh_desc)
    .map(r => ({ key: r.key, name: r.name, desc: r.desc }));
  if (!need.length) return;
  _skFetch('/api/skills/translate', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'meta', items: need }) }).then(r => {
    if (!r.ok || !r.map) return;
    for (const row of SK.rows || []) {
      const m = r.map[row.key];
      if (m) { row.zh_name = m.zh_name; row.zh_desc = m.zh_desc; }
    }
    if (SK.view === 'home') skRenderHome();
  });
}

function skLoadInstalled() {
  return _skFetch('/api/skills/installed').then(r => {
    SK.inst = r.ok ? r.skills : [];
    return SK.inst;
  });
}

// ==================== 首页渲染 ====================

const SK_TABS = [['top', '全部时间'], ['trending', '趋势 24h'], ['hot', '热门']];
const SK_TOPICS = ['全部', '开发工具', '内容创作', '数据分析', '效率提升', '其他'];

function skRenderHome() {
  if (SK.view !== 'home') return;
  const el = SK.root.querySelector('#skBody');
  const rows = (SK.rows || []).filter(r =>
    SK.topic === '全部' || (r.topic || '其他') === SK.topic);
  const inst = SK.inst || [];
  const instHtml = inst.length ? inst.map(skInstCard).join('')
    : '<div class="sk-empty">尚未安装任何技能——在下方 SkillHub 挑一个吧</div>';
  const grid = SK.loading
    ? '<div class="sk-empty">加载中…</div>'
    : (rows.length ? rows.map(skRowCard).join('')
      : '<div class="sk-empty">' + (SK.rows ? '没有匹配的技能' : 'skills.sh 不可达（检查外网连通）') + '</div>');
  el.innerHTML =
    '<div class="sk-sec"><div class="sk-sec-h"><b>已安装 ' + inst.length + '</b>' +
      '<span class="sk-sec-ops"><button class="sk-btn sm" data-sk-updates>检查更新</button>' +
      '<button class="sk-btn sm" data-sk-export' + (SK.sel.size ? '' : ' disabled') + '>导出离线包(' + SK.sel.size + ')</button></span></div>' +
      '<div class="sk-grid inst">' + instHtml + '</div></div>' +
    '<div class="sk-sec"><div class="sk-sec-h"><b>SkillHub 发现</b></div>' +
      '<div class="sk-chips">' + SK_TABS.map(t =>
        '<button class="sk-chip' + (SK.tab === t[0] ? ' on' : '') + '" data-sk-tab="' + t[0] + '">' + t[1] + '</button>').join('') +
      '<span class="sk-chip-sep"></span>' + SK_TOPICS.map(t =>
        '<button class="sk-chip' + (SK.topic === t ? ' on' : '') + '" data-sk-topic="' + t + '">' + t + '</button>').join('') +
      '</div>' +
      '<div class="sk-grid">' + grid + '</div></div>';
}

function skRowCard(r) {
  const zh = r.zh_desc ? '中文' : '';
  return '<div class="sk-card" data-sk-key="' + _skEsc(r.key) + '" title="' + _skEsc(r.desc || r.skill) + '">' +
    _skIcon(r.name) +
    '<div class="sk-card-m"><div class="sk-card-n"><b>' + _skEsc(r.zh_name || r.name) + '</b>' +
    (r.zh_name && r.zh_name !== r.name ? '<i class="sk-en">' + _skEsc(r.name) + '</i>' : '') +
    (zh ? '<u class="sk-zhtag">中</u>' : '') + '</div>' +
    '<div class="sk-card-d">' + _skEsc(r.zh_desc || r.desc || r.source) + '</div>' +
    '<div class="sk-card-f"><span>' + _skEsc(r.source) + '</span><span>⬇ ' + _skEsc(r.installs || '-') + '</span></div></div>' +
    '<button class="sk-btn sm pri" data-sk-install="' + _skEsc(r.key) + '">安装</button></div>';
}

function skInstCard(s) {
  const upd = SK.updates[s.name];
  return '<div class="sk-card' + (s.disabled ? ' off' : '') + '">' +
    '<input type="checkbox" class="sk-sel" data-sk-sel="' + _skEsc(s.name) + '"' +
    (SK.sel.has(s.name) ? ' checked' : '') + ' title="勾选导出离线包">' +
    _skIcon(s.name) +
    '<div class="sk-card-m"><div class="sk-card-n"><b>' + _skEsc(s.name) + '</b>' +
    (s.disabled ? '<u class="sk-offtag">已禁用</u>' : '') +
    (upd === true ? '<u class="sk-updtag">可更新</u>' : '') +
    (s.source !== 'user' ? '<u class="sk-srctag">' + _skEsc(s.source) + '</u>' : '') + '</div>' +
    '<div class="sk-card-d">' + _skEsc(s.desc || '') + '</div>' +
    (upd === false && s.origin ? '<div class="sk-card-f"><span>已是最新</span></div>' : '') + '</div>' +
    '<span class="sk-ops">' +
    (s.source === 'user'
      ? '<button class="sk-btn sm" data-sk-disable="' + _skEsc(s.name) + '" data-sk-off="' + (s.disabled ? '0' : '1') + '">' + (s.disabled ? '启用' : '禁用') + '</button>' +
        '<button class="sk-btn sm danger" data-sk-uninstall="' + _skEsc(s.name) + '">卸载</button>'
      : '<span class="sk-ro">' + _skEsc(s.source) + ' 级只读</span>') +
    '</span></div>';
}

// ==================== 已安装操作 ====================

function _skRefreshInst() {
  return skLoadInstalled().then(() => { if (SK.view === 'home') skRenderHome(); });
}

function skInstall(key, btn) {
  const parts = String(key).split('/');
  if (parts.length !== 3) return;
  if (btn) { btn.disabled = true; btn.textContent = '安装中…'; }
  _skFetch('/api/skills/install', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner: parts[0], repo: parts[1], skill: parts[2] }) })
    .then(r => {
      if (btn) { btn.disabled = false; btn.textContent = '安装'; }
      if (!r.ok) { showBanner('安装失败：' + (r.err || ''), 4000, true); return; }
      showBanner((r.conflict ? '已覆盖重装：' : '安装成功：') + parts[2] +
        (r.partial ? '（辅助文件部分缺失——SKILL.md 主体已装）' : ''), 4000);
      SK.updates[parts[2]] = false;
      _skRefreshInst();
      if (SK.view === 'detail' && SK.det && SK.det.key === key) skOpenDetail(key);
    });
}

function skUninstall(name) {
  if (!confirm('卸载技能「' + name + '」？其目录将被删除。')) return;
  _skFetch('/api/skills/uninstall', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill: name }) }).then(r => {
    if (!r.ok) { showBanner('卸载失败：' + (r.err || ''), 3500, true); return; }
    SK.sel.delete(name);
    showBanner('已卸载：' + name, 3000);
    _skRefreshInst();
  });
}

function skDisable(name, off) {
  _skFetch('/api/skills/disable', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill: name, off }) }).then(r => {
    if (!r.ok) { showBanner('操作失败：' + (r.err || ''), 3500, true); return; }
    showBanner(off ? '已禁用（新会话不再加载）' : '已启用', 3000);
    _skRefreshInst();
  });
}

function skCheckUpdates() {
  showBanner('正在检查更新（逐个比对上游）…', 2500);
  _skFetch('/api/skills/check_updates', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(r => {
    if (!r.ok) return;
    SK.updates = {};
    let n = 0;
    for (const u of r.updates || []) {
      SK.updates[u.skill] = u.has_update;
      if (u.has_update) n++;
    }
    showBanner(n ? '有 ' + n + ' 个技能可更新（卡片已标出，点发现页重装即升）'
                 : '全部已是最新', 4000);
    _skRefreshInst();
  });
}

function skExport() {
  const names = [...SK.sel];
  if (!names.length) { showBanner('先勾选要导出的技能', 2500, true); return; }
  _skFetch('/api/skills/pack/export', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names }) }).then(r => {
    if (!r.ok) { showBanner('导出失败：' + (r.err || ''), 4000, true); return; }
    showBanner('离线包已生成：' + r.path, 8000);
  });
}

// ==================== 离线包导入 ====================

function skPackInspect(file) {
  const fd = new FormData();
  fd.append('file', file);
  showBanner('解析离线包…', 2000);
  fetch('/api/skills/pack/inspect', { method: 'POST', body: fd })
    .then(r => r.json()).then(r => {
      if (!r.ok) { showBanner('导入失败：' + (r.err || ''), 4000, true); return; }
      _skPackModal(r.token, r.skills);
    });
}

function _skPackModal(token, skills) {
  const anyConflict = skills.some(s => s.conflict);
  const m = document.createElement('div');
  m.className = 'modal';
  m.innerHTML =
    '<div class="modal-box sk-pack-box"><h3>离线包导入预览</h3>' +
    '<div class="sk-pack-list">' + skills.map(s =>
      '<label><input type="checkbox" checked value="' + _skEsc(s.name) + '"> ' +
      _skEsc(s.name) + (s.conflict ? ' <u class="sk-updtag">已装·将覆盖</u>' : '') + '</label>'
    ).join('') + '</div>' +
    (anyConflict ? '<div class="sk-pack-tip">勾选「覆盖已装」才会替换同名技能，否则跳过</div>' : '') +
    '<label class="sk-pack-ow"><input type="checkbox" id="skPackOw"' + (anyConflict ? '' : ' disabled') + '> 覆盖已装技能</label>' +
    '<div class="modal-acts"><button class="sk-btn" id="skPackCancel">取消</button>' +
    '<button class="sk-btn pri" id="skPackGo">安装所选</button></div></div>';
  document.body.appendChild(m);
  requestAnimationFrame(() => m.classList.add('show'));
  m.querySelector('#skPackCancel').onclick = () => m.classList.remove('show');
  m.querySelector('#skPackGo').onclick = () => {
    const names = [...m.querySelectorAll('.sk-pack-list input:checked')].map(i => i.value);
    if (!names.length) { showBanner('未选择技能', 2500, true); return; }
    m.querySelector('#skPackGo').disabled = true;
    _skFetch('/api/skills/pack/apply', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, names, overwrite: m.querySelector('#skPackOw').checked }) })
      .then(r => {
        m.classList.remove('show');
        if (!r.ok) { showBanner('导入失败：' + (r.err || ''), 4000, true); return; }
        const bad = (r.failed || []).map(f => f.name).join('、');
        showBanner('导入完成：装 ' + (r.installed || []).length + ' 个' +
          ((r.skipped || []).length ? '，跳过 ' + r.skipped.length + ' 个（已装未勾覆盖）' : '') +
          (bad ? '，失败：' + bad : ''), 6000);
        _skRefreshInst();
      });
  };
}

// ==================== 详情页 ====================

function skOpenDetail(key) {
  const parts = String(key).split('/');
  if (parts.length !== 3) return;
  SK.det = null; SK.detZh = false; SK.view = 'detail';
  const el = SK.root.querySelector('#skBody');
  el.innerHTML = '<div class="sk-empty">加载详情…</div>';
  SK.root.querySelector('#skSearch').blur();
  _skFetch('/api/skills/detail?owner=' + encodeURIComponent(parts[0]) +
    '&repo=' + encodeURIComponent(parts[1]) + '&skill=' + encodeURIComponent(parts[2]))
    .then(r => {
      if (!r.ok) { el.innerHTML = '<div class="sk-empty">详情拉取失败</div>'; return; }
      SK.det = r.detail;
      skRenderDetail();
    });
}

function skShowHome() {
  SK.view = 'home';
  skRenderHome();
}

function skRenderDetail() {
  const d = SK.det;
  if (!d || SK.view !== 'detail') return;
  const el = SK.root.querySelector('#skBody');
  const mdSrc = (SK.detZh && d.body_zh) ? d.body_zh : (d.md || '');
  let bodyHtml = '';
  try {
    bodyHtml = window.markdownit
      ? window.markdownit({ breaks: true }).render(mdSrc)
      : '<pre>' + _skEsc(mdSrc) + '</pre>';
  } catch (e) { bodyHtml = '<pre>' + _skEsc(mdSrc) + '</pre>'; }
  const gloss = d.glossary && Object.keys(d.glossary).length
    ? '<div class="sk-gloss"><b>术语对照</b>' + Object.entries(d.glossary).slice(0, 12)
        .map(kv => '<span>' + _skEsc(kv[0]) + ' → ' + _skEsc(kv[1]) + '</span>').join('') + '</div>'
    : '';
  el.innerHTML =
    '<div class="sk-sec sk-det-h">' +
      _skIcon(d.name, 40) +
      '<div class="sk-card-m"><div class="sk-card-n"><b>' + _skEsc(d.zh_name || d.name) + '</b>' +
        '<i class="sk-en">' + _skEsc(d.name) + '</i></div>' +
        '<div class="sk-card-d">' + _skEsc(d.zh_desc || d.desc || '') + '</div>' +
        '<div class="sk-card-f"><span>' + _skEsc(d.owner + '/' + d.repo) + '</span>' +
        '<span>⬇ ' + _skEsc(d.installs || '-') + '</span>' +
        (d.files ? '<span>' + d.files.length + ' 个文件</span>' : '<span>文件清单不可得（API 限额）</span>') + '</div></div>' +
      '<span class="sk-ops">' +
        '<button class="sk-btn sm" data-sk-zh>' + (SK.detZh ? '看英文' : (d.body_zh ? '看中文' : '翻译正文')) + '</button>' +
        '<button class="sk-btn sm pri" data-sk-do-install>' + (d.zh_name ? '重装' : '安装') + '</button></span>' +
    '</div>' +
    (gloss || (SK.detZh && d.body_zh) ? '<div class="sk-review"><b>安装前校阅（' + (SK.detZh ? '中文译文' : '') + '）</b>' + gloss + '</div>' : '') +
    '<div class="sk-md">' + bodyHtml + '</div>';
  if (SK.detZh && !d.body_zh) skDetailZh();   // 点了「翻译正文」后自动渲染译文
}

function skDetailZh() {
  const d = SK.det;
  if (!d) return;
  if (SK.detZh) { SK.detZh = false; skRenderDetail(); return; }
  if (d.body_zh) { SK.detZh = true; skRenderDetail(); return; }
  const btn = SK.root.querySelector('[data-sk-zh]');
  if (btn) { btn.disabled = true; btn.textContent = '翻译中…'; }
  const parts = d.key.split('/');
  _skFetch('/api/skills/translate', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'body', owner: parts[0], repo: parts[1], skill: parts[2] }) })
    .then(r => {
      if (btn) { btn.disabled = false; btn.textContent = '翻译正文'; }
      if (!r.ok) { showBanner('翻译失败：' + (r.err || ''), 4000, true); return; }
      d.body_zh = r.body_zh;
      SK.detZh = true;
      skRenderDetail();
    });
}
