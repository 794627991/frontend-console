// ============================================================
// docview / harness-pane —— harness 分屏里的文档标签（文档 6.2）
//
// 两种标签（6.2.1）：
//   __doca__      AI 文档标签，一个会话一个单例，内容随 AI 调用切换
//   __docu<N>__   用户文档标签，每个路径一个，AI 不碰
//
// 标签档案（6.2.2）在 subpane 的 _sub.tabs 里，额外带 pseudo/path/by/inst
// 与 onDestroy。**伪标签判据走 _subIsPseudo**（subpane.js），这里只负责置
// pseudo: true。
//
// 切会话（6.2.5）：_subReset 开头调 beforeReset(sid) 记下并销毁；切回来调
// restoreForSession(sid) 只重建记录不渲染，是否展开看 _subUserOpenGet(sid)。
// ============================================================

import { mount } from './core.js';
import { parseAnchor, kindOfPath } from './anchor.js';
import { esc } from './esc.js';

const DOCA = '__doca__';
const DOCU_PREFIX = '__docu';
const MAX_USER_TABS = 8;

/** sid → { agent: {path,at}|null, user: [{path,at}], activeTid } */
const _bySid = {};
/** 当前会话的用户标签：tid → { path, at, lastActive } */
let _userSeq = 0;

function sid() { try { return window._HG && window._HG.sid || ''; } catch (_) { return ''; } }
function sub() { return window._sub; }

/**
 * 分屏的主体容器（`[data-hg-subbody]`）。
 * **不能读 `_sub.bodyEl`**——那是个不存在的字段，subpane.js 里的 `_subBodyEl`
 * 是模块内变量，从外面拿不到（本文件曾往里 append 到 undefined，标签条上
 * 有名字、面板一片空白）。唯一可靠的入口是 DOM 属性。
 */
function subBody() {
  try { return document.querySelector('[data-hg-subbody]'); } catch (_) { return null; }
}

function _rec() {
  const s = sid() || '_';
  return _bySid[s] || (_bySid[s] = { agent: null, user: [], activeTid: '' });
}

/** 有没有 AI 会话页；没有就建一个（照 ai-browser 的做法）。 */
function _ensureHarnessTab() {
  if (typeof window.buildClaudeHarnessTab === 'function') {
    try { window.buildClaudeHarnessTab({}); } catch (_) {}
  }
}

/**
 * 建一个文档标签。已有同 tid 的标签时**换内容**（AI 标签是单例）。
 * @param {string} tid
 * @param {string} path
 * @param {{at?, by?, activate?, userIntent?}} opt
 */
export async function ensureTab(tid, path, opt) {
  opt = opt || {};
  const S = sub();
  if (!S || !S.tabs) return null;
  const existing = S.tabs[tid];
  if (existing) {
    // 同一标签换内容：销毁旧实例再装新的
    if (existing.inst) {
      try { existing.inst.destroy(); } catch (_) {}
    }
    existing.inst = null;
    existing.path = path;
    existing.label = _labelOf(path);
    existing.desc = path;
    existing.at = opt.at || '';
    existing.sc.innerHTML = '';
    existing._loaded = false;
  } else {
    _createTabShell(tid, path, opt);
  }
  if (opt.activate) activate(tid, opt.userIntent);
  return await _loadInto(tid, opt);
}

function _labelOf(path) {
  const n = String(path || '').split(/[\\/]/).pop() || '文档';
  return n.length > 14 ? n.slice(0, 14) + '…' : n;
}

function _createTabShell(tid, path, opt) {
  const S = sub();
  const sc = document.createElement('div');
  sc.className = 'hg-sub-msgs hg-doc-pane';
  sc.dataset.tid = tid;
  S.tabs[tid] = {
    label: _labelOf(path), type: '__doc__', desc: path, sc,
    run: false, err: false, replay: false, model: '',
    pseudo: true,             // 6.2.3：伪标签统一判据
    path, by: opt.by || 'user', at: opt.at || '',
    inst: null, _loaded: false,
    onDestroy() { if (this.inst) { try { this.inst.destroy(); } catch (_) {} this.inst = null; } },
  };
  S.order.push(tid);
  const body = subBody();
  if (body) body.appendChild(sc);
  sc.style.display = 'none';
  _bindPaneDrop(sc);
}

/** 拖文件到**已打开的文档面板**上也打开它（2026-11-26 用户实测：
 *  「拖拽无效，直接被 claude 全覆盖了」）。
 *  editor.js 的全局 capture drop 已对本面板让路，事件能走到这里。 */
function _bindPaneDrop(sc) {
  if (sc._dvDropBound) return;
  sc._dvDropBound = true;
  sc.addEventListener('dragover', (e) => {
    if (!e.dataTransfer) return;
    if (!Array.from(e.dataTransfer.types || []).includes('Files')) return;
    e.preventDefault();               // 允许成为落点
  });
  sc.addEventListener('drop', (e) => {
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    e.preventDefault();
    e.stopPropagation();              // 本面板接了，别再让全局分发再处理一次
    const p = _pathOfFile(e.dataTransfer.files[0]);
    if (p) _openDocPath(p);
  });
}

/** 把文档装进标签的容器。 */
async function _loadInto(tid, opt) {
  const S = sub();
  const tb = S && S.tabs && S.tabs[tid];
  if (!tb) return null;
  if (tb._loaded && tb.inst) {
    if (opt.at) { try { tb.inst.locate(opt.at); } catch (_) {} }
    return tb.inst;
  }
  tb._loaded = true;
  const host = document.createElement('div');
  host.className = 'dv-pane-host';
  tb.sc.innerHTML = '';
  tb.sc.appendChild(host);
  try {
    const inst = await mount(host, { path: tb.path, kind: kindOfPath(tb.path), host: 'harness' });
    tb.inst = inst;
    if (opt.at) { try { inst.locate(opt.at); } catch (_) {} }
    _paintTabs();
    return inst;
  } catch (e) {
    tb._loaded = false;
    const d = document.createElement('div');
    d.className = 'office-err';
    d.textContent = '打开失败：' + ((e && e.message) || String(e));
    tb.sc.appendChild(d);
    return null;
  }
}

function _paintTabs() {
  try { if (typeof window._subTabsPaint === 'function') window._subTabsPaint(); } catch (_) {}
}

/** 激活某个标签（含展开窗格）。 */
export function activate(tid, userIntent) {
  const S = sub();
  if (!S || !S.tabs || !S.tabs[tid]) return;
  if (typeof window._subShow === 'function') window._subShow(tid, !!userIntent);
  S.manual = !!userIntent || S.manual;
  if (typeof window._subActivate === 'function') window._subActivate(tid);
  const r = _rec();
  r.activeTid = tid;
}

// ------------------------------------------------------------------
// 对外的三个入口（6.1.1）
// ------------------------------------------------------------------

/**
 * 用户点了聊天里的路径：开一个用户文档标签。
 * 同一路径已有标签就激活它，不重复开（6.2.1 的「每个路径一个」）。
 */
export async function openInHarness(path, opt) {
  opt = opt || {};
  const p = String(path || '');
  if (!p || !kindOfPath(p)) return null;
  _ensureHarnessTab();
  const S = sub();
  if (!S || !S.tabs) return null;

  // 找已存在的同路径用户标签
  let tid = null;
  for (const t of Object.keys(S.tabs)) {
    const tb = S.tabs[t];
    if (tb && tb.pseudo && tb.path === p && String(t).indexOf(DOCU_PREFIX) === 0) { tid = t; break; }
  }
  if (!tid) {
    // 数量上限 8：超出时关掉最久没激活的（6.2.6）
    const users = Object.keys(S.tabs).filter(t => String(t).indexOf(DOCU_PREFIX) === 0);
    if (users.length >= MAX_USER_TABS) {
      let oldest = users[0], min = Infinity;
      for (const t of users) {
        const la = (S.tabs[t] && S.tabs[t].lastActive) || 0;
        if (la < min) { min = la; oldest = t; }
      }
      try { window._subDrop(oldest); } catch (_) {}
    }
    _userSeq += 1;
    tid = DOCU_PREFIX + _userSeq + '__';
  }
  const tb0 = S.tabs[tid];
  if (tb0) tb0.lastActive = Date.now();
  const inst = await ensureTab(tid, p, { at: opt.at || '', by: 'user', activate: true, userIntent: true });
  if (S.tabs[tid]) S.tabs[tid].lastActive = Date.now();
  // 记住：用户开过这个会话的文档
  const r = _rec();
  if (!r.user.some(u => u.path === p)) r.user.push({ path: p, at: opt.at || '' });
  _markUserOpen(true);
  return inst;
}

function _markUserOpen(v) {
  try {
    if (typeof window._subUserOpenMark === 'function') window._subUserOpenMark(sid(), !!v);
  } catch (_) {}
}

/**
 * AI 的 open_document：装进 AI 文档标签（单例）。
 * 用户手动打开的同路径标签**不动**（AC-3.7）——AI 标签自己再加载一份。
 */
export async function agentOpen(reqId, path, at) {
  _ensureHarnessTab();
  const inst = await ensureTab(DOCA, String(path || ''), { at: at || '', by: 'agent', activate: true, userIntent: false });
  _rec().agent = { path: String(path || ''), at: at || '', reqId };
  return inst;
}

/** AI 的 show_in_viewer：滚到第一个目标、高亮全部、显示说明条。 */
export async function agentShow(reqId, targets, note, seq) {
  const S = sub();
  const tb = S && S.tabs && S.tabs[DOCA];
  const path = (targets && targets[0] && targets[0].path) || (tb && tb.path) || '';
  if (!tb || (path && tb.path !== path)) {
    await agentOpen(reqId, path, '');
  }
  const tb2 = sub().tabs[DOCA];
  if (!tb2) return { found: false };
  if (!tb2._loaded || !tb2.inst) await _loadInto(DOCA, {});
  activate(DOCA, false);
  try {
    return tb2.inst.reveal(targets, note, seq);
  } catch (e) {
    if (window.console) console.warn('[docview] reveal 失败', e);
    return { found: false };
  }
}

// ------------------------------------------------------------------
// 切会话（6.2.5）
// ------------------------------------------------------------------

/** _subReset 开头调：记下当前文档标签，然后销毁全部实例。 */
export function beforeReset(s) {
  const st = _bySid[s] || (_bySid[s] = { agent: null, user: [], activeTid: '' });
  st.agent = null; st.user = []; st.activeTid = '';
  const S = sub();
  if (!S || !S.tabs) return;
  for (const t of Object.keys(S.tabs)) {
    const tb = S.tabs[t];
    if (!tb || !tb.pseudo || !tb.path) continue;
    if (t === DOCA) {
      st.agent = { path: tb.path, at: tb.at || '' };
      if (S.active === t) st.activeTid = t;
    } else if (String(t).indexOf(DOCU_PREFIX) === 0) {
      st.user.push({ path: tb.path, at: tb.at || '' });
      if (S.active === t) st.activeTid = t;
    }
  }
}

/** 切回会话后调：只重建记录，不渲染；是否展开看用户的打开意图。 */
export function restoreForSession(s) {
  const st = _bySid[s];
  if (!st) return;
  const S = sub();
  if (!S || !S.tabs) return;
  const wants = (() => {
    try { return window._subUserOpenGet && window._subUserOpenGet(s) === true; } catch (_) { return false; }
  })();
  // 重建 shell（不渲染）
  const rebuild = (tid, item, by) => {
    if (!item || !item.path) return;
    if (S.tabs[tid]) return;
    _createTabShell(tid, item.path, { by });
  };
  if (st.agent) rebuild(DOCA, st.agent, 'agent');
  st.user.forEach((u, i) => rebuild(DOCU_PREFIX + (i + 1) + '__', u, 'user'));
  if (st.user.length > _userSeq) _userSeq = st.user.length;
  _paintTabs();
  if (!wants) return;   // 用户没表达「要开着」→ 只重建记录
  const target = st.activeTid && S.tabs[st.activeTid] ? st.activeTid
    : (st.agent && S.tabs[DOCA] ? DOCA : (S.tabs[DOCU_PREFIX + '1__'] ? DOCU_PREFIX + '1__' : ''));
  if (!target) return;
  activate(target, true);
  _loadInto(target, { at: (S.tabs[target] || {}).at || '' });
}

/** 供 subpane 的 tab 点击分支判断伪标签（导出到 window）。 */
export function isDocTab(t) {
  return t === DOCA || (!!t && String(t).indexOf(DOCU_PREFIX) === 0);
}

// ------------------------------------------------------------------
// 「打开文件」伪 tab（2026-11-26 用户令）
//
// 用户原话：「整合在现有胶囊，点击胶囊，展开 tab 页，动态，目录，打开文件
// （在该 tab 页中，再打开对应文件，要有符合工具的 UI 美化）」。
//
// 所以它不是胶囊旁边的按钮，而是和「动态」「目录」同级的第三个伪 tab：
//   · 面板顶部：一个醒目的「选择文件」大按钮（走壳的原生对话框）
//   · 中部：支持类型说明 + 拖放区
//   · 底部：本次会话打开过的文档（点一下重新打开）
// 选中的文档走 openInHarness 开成用户文档标签，并登记进后端索引给 AI 用。
// ------------------------------------------------------------------

const DOCOPEN = '__docopen__';
/** 导出给 index.js 登记（main.js 的 tab 点击分支据此懒建） */
export const DOCOPEN_TID = DOCOPEN;
const RECENT_MAX = 12;
let _recentDocs = [];      // [{path, at, ts}]——本次会话内存内，不落盘

function _docOpenRecentAdd(path) {
  _recentDocs = _recentDocs.filter(r => r.path !== path);
  _recentDocs.unshift({ path, ts: Date.now() });
  if (_recentDocs.length > RECENT_MAX) _recentDocs.length = RECENT_MAX;
}

const ICON_SVG = body => '<svg viewBox="0 0 16 16" width="16" height="16" fill="none" ' +
  'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" ' +
  'stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
const _ICO = {
  folderOpen: ICON_SVG('<path d="M1.8 12.5l1.4-4.4h9.9l1.1 4.4z"/>' +
    '<path d="M2.5 12.5V4.5a1 1 0 0 1 1-1h2.6l1.4 1.8h4a1 1 0 0 1 1 1v1.8"/>'),
  file: ICON_SVG('<path d="M4 2.5h4.5L12 6v7.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z"/>' +
    '<path d="M8.5 2.5V6H12"/>'),
};

const _SKELETON =
  '<div class="hg-docopen-pane">' +
    '<div class="dv-open-hero">' +
      '<button class="dv-open-pick" data-dv-pick>' +
        '<span class="dv-open-ico">' + _ICO.folderOpen + '</span>' +
        '<span class="dv-open-pick-t">选择文件…</span>' +
      '</button>' +
      '<div class="dv-open-hint">支持 Word、PDF、Excel、PowerPoint 与常见图片；' +
        '也可以把文件直接拖到这里</div>' +
    '</div>' +
    '<div class="dv-open-drop" data-dv-drop>' +
      '<div class="dv-open-drop-ico">' + _ICO.file + '</div>' +
      '<div class="dv-open-drop-t">拖放文件到此处</div>' +
    '</div>' +
    '<div class="dv-open-sec" data-dv-recent-sec hidden>' +
      '<div class="dv-open-sec-head">本次打开</div>' +
      '<div class="dv-open-recent" data-dv-recent></div>' +
    '</div>' +
    '<div class="dv-open-note">打开后文档会出现在右侧标签里，AI 也能直接读取它的内容。</div>' +
  '</div>';

/** 懒建「打开文件」伪 tab（与 _subDynEnsure 同口径：不夺焦点）。 */
export function ensureDocOpenTab() {
  const S = sub();
  if (!S || !S.tabs) return null;
  if (S.tabs[DOCOPEN]) return S.tabs[DOCOPEN];
  const body = subBody();
  if (!body) return null;
  const sc = document.createElement('div');
  sc.className = 'hg-sub-msgs hg-docopen-msgs';
  sc.dataset.tid = DOCOPEN;
  sc.innerHTML = _SKELETON;
  S.tabs[DOCOPEN] = {
    label: '打开文件', type: '__docopen__', desc: '打开一份文档到分屏（AI 也能读）', sc,
    run: false, err: false, replay: false, model: '',
    pseudo: true,             // 6.2.3：伪标签统一判据
  };
  S.order.push(DOCOPEN);
  body.appendChild(sc);
  sc.style.display = 'none';
  _bindDocOpenPane(sc);
  _paintDocOpenRecent(sc);
  _paintTabs();
  return S.tabs[DOCOPEN];
}

/** 打开并激活「打开文件」伪 tab（用户点 tab 条时也走这里）。 */
export function openDocOpenTab() {
  const tb = ensureDocOpenTab();
  if (!tb) return;
  activate(DOCOPEN, true);
  _paintDocOpenRecent(tb.sc);
}

function _bindDocOpenPane(sc) {
  const pick = sc.querySelector('[data-dv-pick]');
  if (pick) pick.onclick = () => _pickAndOpen();
  const drop = sc.querySelector('[data-dv-drop]');
  // **整个面板都接拖放**，不只在虚线框上（2026-11-26 用户实测：拖到面板
  // 任意位置都应该在这里打开——用户不会精确瞄准那个小框）。虚线框只是
  // 「可以拖」的可见提示，高亮仍归它。
  const accepts = (e) => !!(e.dataTransfer &&
    Array.from(e.dataTransfer.types || []).includes('Files'));
  sc.addEventListener('dragover', (e) => {
    if (!accepts(e)) return;
    e.preventDefault();          // 不 preventDefault → drop 不触发
    if (drop) drop.classList.add('hot');
  });
  sc.addEventListener('dragleave', (e) => {
    // 只在真正离开面板时取消高亮（内部元素间移动会连发 dragleave）
    const rt = e.relatedTarget;
    if (rt && rt.closest && rt.closest('.hg-docopen-msgs')) return;
    if (drop) drop.classList.remove('hot');
  });
  sc.addEventListener('drop', (e) => {
    if (!accepts(e)) return;
    e.preventDefault();
    e.stopPropagation();         // 本面板接了，别再让全局分发处理一次
    if (drop) drop.classList.remove('hot');
    const f = e.dataTransfer.files[0];
    // 壳里 <input type=file> 给的 File 没有真实路径；只有 Electron 的
    // webUtils.getPathForFile 或 pywebview 的拖放事件才有。
    // **Electron 下必须先走 fcShell.pathForFile**——File.path 是 Electron 32
    // 起已移除的旧属性，只认 f.path 会永远拿不到（2026-11-26 实测：拖进
    // 「打开文件」面板只弹「拿不到路径」提示）。
    const p = _pathOfFile(f);
    if (p) _openDocPath(p);
    else _flash(sc, '拖放拿不到文件路径，请用「选择文件」按钮');
  });
  const recent = sc.querySelector('[data-dv-recent]');
  if (recent) {
    recent.onclick = (e) => {
      const row = e.target.closest('[data-dv-path]');
      if (row) _openDocPath(decodeURIComponent(row.dataset.dvPath));
    };
  }
}

/** 从拖放的 File 取真实绝对路径。三条通道按可靠性排序：
 *  ① Electron 壳的 webUtils.getPathForFile（Electron 32+ 唯一可靠途径，
 *     旧 `File.path` 已移除）
 *  ② pywebview 形态：File 上带 path / __path
 *  ③ 都没有 → 返回空串，调用方提示改用「选择文件」 */
function _pathOfFile(f) {
  if (!f) return '';
  try {
    if (window.fcShell && typeof window.fcShell.pathForFile === 'function') {
      const p = window.fcShell.pathForFile(f);
      if (p) return p;
    }
  } catch (_) {}
  return f.path || f.__path || '';
}

function _flash(sc, msg) {  const note = sc.querySelector('.dv-open-note');
  if (!note) return;
  const old = note.textContent;
  note.textContent = msg;
  note.classList.add('warn');
  setTimeout(() => {
    if (!note.isConnected) return;
    note.textContent = old;
    note.classList.remove('warn');
  }, 3500);
}

async function _pickAndOpen() {
  const api = window.pywebview && window.pywebview.api;
  if (!api || typeof api.pick_any !== 'function') {
    const sc = sub().tabs[DOCOPEN] && sub().tabs[DOCOPEN].sc;
    if (sc) _flash(sc, '当前形态不支持选文件，请在主界面标签页打开');
    return;
  }
  let path = '';
  try {
    path = await api.pick_any();
  } catch (e) {
    const sc = sub().tabs[DOCOPEN] && sub().tabs[DOCOPEN].sc;
    if (sc) _flash(sc, '文件选择框打开失败：' + String((e && e.message) || e).slice(0, 80));
    return;
  }
  if (!path) return;   // 用户取消
  await _openDocPath(path);
}

/** 打开一个路径：校验类型 → openInHarness → 登记索引。 */
async function _openDocPath(path) {
  // 从任意文档面板拖进来的情况：DOCOPEN 那个伪标签不一定建过，取不到就
  // 没有地方 flash，静默继续（打开本身照常完成）
  const tb = sub() && sub().tabs && sub().tabs[DOCOPEN];
  const sc = tb && tb.sc;
  if (!kindOfPath(path)) {
    if (sc) _flash(sc, '不支持的文件类型：' + String(path).split('.').pop());
    return;
  }
  if (!window.DocView || !window.DocView.openInHarness) {
    if (sc) _flash(sc, '文档模块未加载');
    return;
  }
  try {
    const inst = await window.DocView.openInHarness(path, { by: 'user' });
    if (inst && inst.ready) await inst.ready;
    _docOpenRecentAdd(path);
    if (sc) _paintDocOpenRecent(sc);
    // 登记给后端索引：AI 之后能直接 search / read（不必再 open 一遍）
    if (inst) {
      const info = inst.info || {};
      fetch('/api/doc/report_open', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          req_id: '',   // 手动打开：没有等待方，只登记索引
          ok: true,
          document: {
            path: inst.path, kind: inst.kind, title: info.title || '',
            bytes: info.bytes || 0, revision: info.revision || '',
            outline: (info.outline || []).slice(0, 200),
            units: (info.units || []).map(u => ({ at: u.at, text: u.text || '' })),
          },
        }),
      }).catch(() => {});
    }
  } catch (e) {
    if (sc) _flash(sc, '打开失败：' + String((e && e.message) || e).slice(0, 100));
  }
}

function _paintDocOpenRecent(sc) {
  const sec = sc.querySelector('[data-dv-recent-sec]');
  const box = sc.querySelector('[data-dv-recent]');
  if (!sec || !box) return;
  if (!_recentDocs.length) { sec.hidden = true; box.innerHTML = ''; return; }
  sec.hidden = false;
  box.innerHTML = _recentDocs.map(r => {
    const name = String(r.path).split(/[\\/]/).pop();
    const kind = kindOfPath(r.path) || '';
    return '<div class="dv-open-row" data-dv-path="' + encodeURIComponent(r.path) + '" title="' +
      esc(r.path) + '">' +
      '<span class="dv-open-row-ico">' + _ICO.file + '</span>' +
      '<span class="dv-open-row-n">' + esc(name) + '</span>' +
      '<span class="dv-open-row-k">' + esc(kind) + '</span></div>';
  }).join('');
}

// ------------------------------------------------------------------
// 后端推来的请求（6.4.3）：打开 / 定位，然后回传结果
// ------------------------------------------------------------------

/** 回传一个请求结果。失败不抛（后端可能已超时清理，返回 404 是正常的）。 */
async function _report(route, body) {
  try {
    await fetch('/api/doc/' + route, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (_) { /* 后端超时后回传失败是预期内的，忽略 */ }
}

/** 把实例的 info 整理成 report_open 需要的 document 结构（6.6）。 */
function _documentOf(inst) {
  const info = inst.info || {};
  return {
    path: inst.path,
    kind: inst.kind,
    title: info.title || '',
    bytes: info.bytes || 0,
    revision: info.revision || '',
    outline: (info.outline || []).slice(0, 200),
    units: (info.units || []).map(u => ({ at: u.at, text: u.text || '' })),
  };
}

/**
 * 后端 `doc_open`：在 AI 文档标签里打开并回传大纲与分页文本。
 * 失败时回传 {ok:false, code, err}，让工具那边拿到中文原因（AC-3.8）。
 */
export async function onOpenRequest(req) {
  const reqId = req.req_id;
  const path = String(req.path || '');
  let inst = null;
  try {
    inst = await agentOpen(reqId, path, req.at || '');
    if (!inst) throw new Error('文档面板没能打开这份文件');
    if (inst.ready) await inst.ready;
  } catch (e) {
    await _report('report_open', {
      req_id: reqId, ok: false, code: 'open_failed',
      err: '打开失败：' + String((e && e.message) || e),
    });
    return;
  }
  await _report('report_open', { req_id: reqId, ok: true, document: _documentOf(inst) });
}

/**
 * 后端 `doc_show`：定位并高亮，回传每个目标是否找到。
 * targets 里的 anchor 已经是规范化后的位置（不带路径）。
 */
export async function onShowRequest(req) {
  const reqId = req.req_id;
  const path = String(req.path || '');
  const list = (req.targets || []).map(t => ({
    anchor: t.anchor,
    quote: t.quote || '',
  }));
  const S = sub();
  const tb = S && S.tabs && S.tabs[DOCA];
  try {
    if (!tb || tb.path !== path) await agentOpen(reqId, path, list[0] ? list[0].anchor : '');
    const tb2 = sub().tabs[DOCA];
    if (!tb2 || !tb2.inst) throw new Error('文档面板没能打开这份文件');
    if (tb2.inst.ready) await tb2.inst.ready;
    activate(DOCA, false);
    // reveal 一次吃全部目标（滚到第一个、高亮全部、显示说明条）
    tb2.inst.reveal(list, req.note || '', req.seq);
    // 逐个回报 found：**不能重复调 reveal**（后一次会覆盖前一次的高亮，
    // 而 reveal 会清掉 dv-reveal 再涂）。改用只判定不绘制的 probe。
    const located = list.map(t => {
      let found = false;
      try {
        found = tb2.inst.probe
          ? !!tb2.inst.probe(t.anchor)
          : !!(tb2.inst.locate(t.anchor) || {}).found;
      } catch (_) { found = false; }
      return { at: t.anchor, found };
    });
    await _report('report_show', { req_id: reqId, ok: true, path, located });
  } catch (e) {
    await _report('report_show', {
      req_id: reqId, ok: false, code: 'show_failed',
      err: '定位失败：' + String((e && e.message) || e),
    });
  }
}

export { DOCA, DOCU_PREFIX };
