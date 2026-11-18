// ============================================================
// vcs-panel.js (a434，用户令「版本独立成自带入口，与 Claude 解耦」)：
// 原 24-vcs.js 是 Claude 对话页的子窗格伪 tab（_SUB_VCS），只有打开 Claude
// 界面才存在；版本本身与 Claude 无关（看的是 git/svn 工作副本），故迁为
// 主区独立 tab——顶栏「Claude」与「计算器」之间新增入口。
// 保留全部既有能力：工程选择 / 改动列表 / 勾选提交 / pull·update / 提交
// 历史弹窗（master-detail + 筛选 + 翻页）/ 点行进 diff。
// 与 Claude 的联动：工程候选仍吃 _HG.cwd 与各会话 cwd（Claude 当前在哪个
// 工程，这里就能直接选到）。
// API /api/vcs/*（src/vcs.py，文件树登记根安全模型）；diff 复用
// buildDiffViewerTab；写操作全显式确认，不含 push/还原/冲突解决（边界）。
// 状态：VCS = {root, data, log, out, busy, sel:Set, ts}
// ============================================================
const VCS = { root: '', data: null, log: null, out: '', busy: false, sel: new Set(), ts: 0,
  // a438（审计 P2）：最近提交里「已展开改动清单」的 rev 集合 + 清单缓存。
  // 原实现只把展开态放在 DOM 上，_vcsPaint 重建 innerHTML 就全折叠了。
  exp: new Set(), cfCache: new Map() };
window.VCS = VCS;                 // 调试/兼容：原 VCS 的读取方
const VP_PORTID = 'vcs:panel';    // 主区 tab 的单例 portId
let _vpEl = null;                 // 面板根（主区 tab 内），tab 关闭时置空
let _vpAlive = false;             // tab 是否在场（60s 轻轮询的存活判据）
let _vcsLogBusy = false;          // log 拉取防连点
// v3.5.265（Q2-3）：回补响应竞态令牌——_vcsReloadLog 与 _vcsHistFetch 共
// 写 hg.vcs.log，后到的整体替换曾确定性覆盖翻页追加（新增消失/页码回跳）
let _vcsLogSeq = 0;
let _vcsTs = 0;                   // 上次 status 拉取时刻（30s 激活缓存）
let _vcsTick = null;              // 60s 轻轮询定时器
const _VCS_ST_CLS = { M: 'm', A: 'a', D: 'd', R: 'r', '?': 'u', C: 'c', '!': 'd' };
const _VCS_ST_TXT = { M: '改', A: '增', D: '删', R: '移', '?': '未纳管', C: '冲突', '!': '丢失' };

// ==================== 生命周期（主区 tab）====================
// 入口：顶栏「版本」按钮 → init.js 绑 buildVcsPanelTab。单例，已开即切过去。
// 关闭：editor.js 的 _edCloseNow 检测 meta.kind==='vcs' 后调 vcsPanelTeardown。
// 与本功能无关的 harness 状态（_sub/_hgWrap）已全部解耦，Claude 页面不开也能用。
function vcsPanelTeardown() {
  _vcsHistClose();                 // v3.5.133（designer D10）：弹窗防御性关闭
  // a650：分支/Stash/标签弹窗是自建浮层（不进收口表），面板关了必须显式收掉
  try { _vcsDlgClose(); } catch (_) {}
  // a438（审计 P1）：挂 body 的确认弹窗没有宿主可跟随销毁——面板已关但
  // 弹窗还盖在全窗上，误点「执行」会对已销毁面板发真实 git add / pull。
  // a456（第二轮审计 P2）：必须限定 owner。收口表改成按 owner 归组后，
  // 无参调用会关掉**所有**弹窗（含 Claude 面板的），别人的确认框被无辜收掉。
  try { if (window._hgModalReg) window._hgModalReg.closeAll('vcs:panel'); } catch (_) {}
  // 三路审计 C-F2：SSH 配置弹窗自管宿主（挂 body、不进 _hgModalReg 收口
  // 表）——teardown 必须显式收掉，否则面板销毁后弹窗仍悬浮，保存/测试/
  // 断开继续对真实后端配置生效（a438-P1 同型缺陷）。
  const _rdlg = document.getElementById('hgVcsRemoteDlg');
  if (_rdlg) _rdlg.remove();
  _vpAlive = false;
  _vpEl = null;
  if (_vcsTick) { clearInterval(_vcsTick); _vcsTick = null; }
  // root 保留：下次打开还是同一个工程
  VCS.data = null; VCS.log = null; VCS.out = ''; VCS.busy = false;
  VCS.sel = new Set();
  VCS.exp = new Set(); VCS.cfCache = new Map(); VCS.cfPending = new Set();   // a438：展开态与清单缓存随面板关闭清（换新 Map 即作废在途结果）
}
function buildVcsPanelTab() {
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'vcs') { switchTab(pid); return; }
  }
  const portId = VP_PORTID;
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">${ICO16.branch}</span>` +
    `<span class="label">版本控制</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => {
    if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; }
    switchTab(portId);
  };
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = '<div class="hg-vcs-pane" data-vcs-root></div>';
  termArea.appendChild(wrap);

  const conn = { portId, meta: { kind: 'vcs', label: '版本控制' }, tab, wrap };
  connections[portId] = conn;

  _vpEl = wrap.querySelector('[data-vcs-root]');
  _vpAlive = true;
  _vpEl.innerHTML = '<div class="hg-vcs-loading">…</div>';

  switchTab(portId);
  refreshSidebar();
  _vcsActivate(true);
  return conn;
}
// 在场期 60s 轻轮询（git 改动/外部命令后自动跟上；不改动列表重扫）
// a437：失活自停（旧 harness 伪 tab 同语义）——面板不在前台时白扫本地面没意义；
// 切回由 switchTab 的 vcs 钩子经 _vcsActivate → _vcsTickStart 重新武装
function _vcsTickStart() {
  if (_vcsTick) return;
  _vcsTick = setInterval(() => {
    if (!_vpAlive || !_vpEl) { clearInterval(_vcsTick); _vcsTick = null; return; }
    if (typeof activePortId !== 'undefined' && activePortId !== VP_PORTID) {
      clearInterval(_vcsTick); _vcsTick = null; return;
    }
    if (!VCS.busy) _vcsReload(true);
  }, 60000);
}
// 激活按需刷新（30s 缓存；写操作后由调用方传 force）
function _vcsActivate(force) {
  if (!_vpEl) return;
  _vcsTickStart();
  const now = Date.now();
  if (!force && (VCS.data || VCS.busy) && now - _vcsTs < 30000) { _vcsPaint(); return; }
  if (!VCS.busy) _vcsReload();
  else _vcsPaint();
}
// a455：网络盘首次进入自动弹一次 SSH 引导（每个工程只弹一次，本地记忆）。
// 纯本地盘不会弹——_vcsRemoteAutoAsk 只在 remote_used==='smb' 且未配置时生效。
function _vcsRemoteAutoAsk() {
  if (!VCS.root) return;
  const D = VCS.data || {};
  if (D.remote_used !== 'smb') return;
  const root0 = VCS.root;               // 三路审计 C-F4：回调复检基准
  const key = 'hg-vcs-ssh-asked:' + root0;
  try { if (localStorage.getItem(key)) return; } catch (_) { return; }
  fetch('/api/vcs/remote/probe', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root: root0 }) })
    .then(r => r.json()).then(j => {
      // 已配置过（或非网络盘）就不再打扰。
      // 三路审计 C-F4：600ms 窗口里面板可能已关/工程已切——不复检会出现
      // 「依据 A 工程的探测结论给 B 工程弹引导」或面板销毁后弹窗照弹。
      if (!_vpAlive || VCS.root !== root0) return;
      if (!j || !j.ok || j.configured || !j.is_network) return;
      try { localStorage.setItem(key, '1'); } catch (_) {}
      if (!document.getElementById('hgVcsRemoteDlg')) _vcsRemoteDialog();
    }).catch(() => {});
}
// 弹窗宿主：面板可能在任何 tab 之上打开，统一挂 body 层（不受 tab 显隐影响）
function _vpModalHost() { return document.body; }

// ==================== v3.5.133 提交历史弹窗（designer 方案 v1）====================
// 左列表(≤100)右详情 master-detail；数据吃 VCS.log 共享源（秒开），
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
        body: JSON.stringify({ root: VCS.root, rev, path, st }) })).json();
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
  return _vcsHist.querying ? _vcsHist.qlog : VCS.log;
}
function _vcsHistBusy() {
  return _vcsHist.querying ? _vcsHist.qbusy : _vcsLogBusy;
}
function _vcsHistTotal() {
  // a650：图形视图带 --all，后端 total 仍是 rev-list --count HEAD 的口径
  // （不含其它分支），拿它判终点会提前截断——图形模式下当「未知」处理。
  if (_vcsHist && _vcsHist.graph) return undefined;
  return _vcsHist.querying ? _vcsHist.qtotal : VCS.total;
}

// 列表数据入口（浏览/查询路由 + lseq/指纹双竞态校验）
// v3.5.148：cb 参数——跳页（_vcsHistGoto）串行补拉用；所有收尾路径必达
function _vcsHistFetch(reset, cb) {
  const H = _vcsHist;
  if (!H) { if (cb) cb(); return; }
  const lseq = (H.lseq = ++_vcsHistLseq);   // L2：模块级单调令牌
  _vcsLogSeq++;   // v3.5.265（Q2-3）：作废在途回补响应（同数组双写者互斥）
  const fp = _vcsHistQfp();
  if (H.querying) H.qbusy = true;
  const arr = H.querying ? H.qlog : (VCS.log = VCS.log || []);
  const skip = reset ? 0 : arr.length;
  const oldest = arr.length ? arr[arr.length - 1].rev : '';
  const isSvn = ((VCS.data || {}).vcs === 'svn');
  // v3.5.265（Q2-2）：limit 取用户选定每页条数（原硬编码 100——「每页 20」
  // 选了也只按 100 拉，默认只显示 100 条的观感来源之一）
  const _lim = H.size || 100;
  const body = { root: VCS.root, limit: _lim, skip: isSvn ? 0 : skip };
  if (H.graph && !isSvn) { body.graph = 1; body.all = 1; }
  if (isSvn && !reset && oldest) body.before_rev = String(parseInt(oldest, 10) - 1 || 0);
  Object.assign(body, H.q);
  fetch('/api/vcs/log', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) })
    .then(r => r.json()).then(j => {
      if (!H || H.lseq !== lseq || _vcsHistLseq !== lseq || _vcsHistQfp() !== fp) return;   // 竞态：旧响应丢弃（R2：活读模块级单调——关窗重开窗口期旧响应双保险拦截）
      if (H.querying) H.qbusy = false;
      if (!j.ok) {
        H.fetchErr = j.err || '获取失败';
        if (!H.querying) { VCS.log = null; VCS.total = undefined; }
        _vcsHistPaintList(true);
        if (cb) cb();
        return;
      }
      H.fetchErr = null;
      if (reset) H.exhausted = false;
      const tgt = H.querying ? H.qlog : VCS.log;
      const known = new Set(tgt.map(c => c.rev));
      const add = (j.commits || []).filter(c => c.rev && !known.has(c.rev));
      if (reset) { tgt.length = 0; tgt.push(...(j.commits || [])); }
      else tgt.push(...add);
      // P2：后端仅 skip==0 附 total——追加响应无 total 时保住已有精确值
      //（旧写法 undefined 覆盖 → 翻一页「共523条」降级「已载200条」）
      if (j.total !== undefined) {
        if (H.querying) H.qtotal = j.total;
        else VCS.total = j.total;
      }
      // P4：svn 无 total 的终点信号——追加响应去重后零新增=已到最早
      if (!reset && add.length === 0) H.exhausted = true;
      // v3.5.265（Q2-1）：记录本页返回量——svn 无 total 时终点判据从
      // 「整百启发式」改「本页不足 limit」（恰整百时旧启发式恒判未到底）
      H.lastBatch = (j.commits || []).length;
      H.lastLimit = _lim;
      // 漂移补齐：skip 语义下新提交顶入取不满一页 → 追拉（≤3 轮）
      if (!reset && !isSvn && add.length < (j.commits || []).length
          && (j.commits || []).length >= _lim && H.rounds < 3) {
        H.rounds++;
        _vcsHistFetch(false, cb);
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
      if (cb) cb();
    }).catch(e => {
      if (H && H.lseq === lseq) {
        if (H.querying) H.qbusy = false;
        H.fetchErr = String(e);
        _vcsHistPaintList(true);
      }
      if (cb) cb();
    });
}

function _vcsHistOpen() {
  // v3.5.265（Q3 次选嫌疑自愈）：守卫为真但 DOM 无弹窗=历史异常泄漏态——
  // 复位放行，不再永久「点了没反应」
  if (_vcsHist && !_vcsHist.ov || (_vcsHist && !_vcsHist.ov.isConnected)) { _vcsHist = null; }
  if (_vcsHist) { return; }        // 双开守卫
  const D = VCS.data;
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
               page: 1, size, lseq: 0, rounds: 0, fetchErr: null, debT: null,
               graph: false };   // a650：图形视图（--graph --all，合并分叉可见）
  const dateInp = (k, ph) =>
    `<input type="date" name="hg_vcs_hdate_${k}" class="hg-vcs-hdate" data-vcs-hq="${k}" title="${ph}">`;
  ov.innerHTML =
    `<div class="hg-modal hg-modal-vcslog">` +
      `<div class="hg-modal-title"><span style="vertical-align:-2.5px">${ICO16.log}</span> 提交历史 · ${esc(D.vcs || '')}${D.branch ? ' · ⎇ ' + esc(D.branch) : ''}</div>` +
      `<div class="hg-vcs-htool">` +
        `<input autocomplete="off" name="hg_vcs_hsearch" class="hg-vcs-hsearch" data-vcs-hq="text" placeholder="${isSvn ? '关键字（svn 整串匹配，含作者/日期）' : '关键字（多词 AND，含正文）'}" spellcheck="false">` +
        (isSvn ? '' :
          `<input autocomplete="off" name="hg_vcs_hauthor" class="hg-vcs-hauthor" data-vcs-hq="author" list="hg-vcs-authors" placeholder="作者" spellcheck="false">` +
          `<datalist id="hg-vcs-authors"></datalist>`) +
        `<button class="btn ghost hg-vcs-chip" data-vcs-chip="today">今天</button>` +
        `<button class="btn ghost hg-vcs-chip" data-vcs-chip="7d">近7天</button>` +
        `<button class="btn ghost hg-vcs-chip" data-vcs-chip="30d">近30天</button>` +
        dateInp('since', '起始日期') + `<span class="hg-vcs-hsep">~</span>` + dateInp('until', '结束日期') +
        (isSvn ? '' : `<button class="btn ghost hg-vcs-chip" data-vcs-graph title="显示分叉 / 合并连线（--graph --all）">图形</button>`) +
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
        `<select name="hg_vcs_hsize" class="hg-vcs-hsize" data-vcs-hsize>` +
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
    // v3.5.265（Q2-1）：svn 无 total 终点=本页不足 limit（整百启发式在恰
    // 载满一页时恒真=「还能加载」逐百新增的元凶）
    const atEnd = _vcsHistTotal() != null ? arr.length >= _vcsHistTotal()
      : (H.exhausted || (H.lastBatch != null && H.lastBatch < (H.lastLimit || 100)));
    const oldest = arr.length ? arr[arr.length - 1].rev : '';
    const svnEnd = ((VCS.data || {}).vcs === 'svn')
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
      dl.innerHTML = Array.from(VCS.log || []).map(c => c.author)
        .filter(a => a && !seen.has(a) && seen.add(a)).slice(0, 30)
        .map(a => `<option value="${esc(a)}">`).join('');
    }
    _vcsHistFetch(true);   // 两态统一走 fetch（浏览态 reset=⟳ 同义）
  };
  const _debounced = () => {
    clearTimeout(_vcsHist.debT);
    _vcsHist.debT = setTimeout(_applyQ, 400);
  };
  // a650：图形视图开关——只影响新拉取的查询，就地切换不串数据
  const _gbtn = ov.querySelector('[data-vcs-graph]');
  if (_gbtn) _gbtn.onclick = () => {
    const H = _vcsHist; if (!H) return;
    H.graph = !H.graph;
    _gbtn.classList.toggle('on', H.graph);
    _gbtn.title = H.graph ? '图形视图已开（--graph --all）——点击关闭'
                          : '显示分叉 / 合并连线（--graph --all）';
    _vcsHistFetch(true);
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
  _vpModalHost().appendChild(ov);
  // 打开必补拉（R2/R3 语义）；先显已载再补
  if (!_vcsLogBusy) _vcsReloadLog();
  _vcsHistPaintList(false);
}

function _vcsHistClose() {
  if (!_vcsHist) return;
  _vcsHistLseq++;   // R2 终修（复核建议）：关窗即失效在途令牌——重开瞬间的 RTT 窗口也拦
  clearTimeout(_vcsHist.debT);
  try { document.removeEventListener('keydown', _vcsHist.escFn); } catch (_) {}
  const _ovC = _vcsHist.ov;
  _vcsHist = null;   // v3.5.265（Q3）：置空前置于 remove——remove 抛错也不留死守卫
  try { _ovC.remove(); } catch (_) {}
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
      (c.graph ? `<span class="hg-vcs-graph">${esc(c.graph)}</span>` : '') +
      `<span class="hg-vcs-logrev">${esc(c.short || c.rev || '')}${c.deco ? `<span class="hg-vcs-deco">${esc(c.deco)}</span>` : ''}</span>` +
      `<span class="hg-vcs-logmsg">${esc((c.msg || '').slice(0, 44))}</span>` +
      (c.ins != null ? `<span class="hg-vcs-stat" title="${esc(c.ins || 0)} 增 / ${esc(c.del || 0)} 删">` +
        `<b class="up">+${esc(c.ins || 0)}</b> <b class="del">-${esc(c.del || 0)}</b></span>` : '') +
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
  const loadedPages = Math.max(1, Math.ceil(n / H.size));
  const total = _vcsHistTotal();
  // v3.5.265（Q2-1）：同 hnext——svn 终点=本页不足 limit
  const atEnd = total != null ? n >= total : (H.exhausted || (H.lastBatch != null && H.lastBatch < (H.lastLimit || 100)));
  // v3.5.148（用户批注「初始页数不对，803 条应按总数显示页数」）：总数已知
  //（git rev-list/查询 qtotal）显示真实总页数；svn 无 total 保持已载页数诚实
  const vpages = total != null ? Math.max(1, Math.ceil(total / H.size)) : loadedPages;
  if (info) {
    // v3.5.148：页码可编辑跳转（Enter/失焦触发 _vcsHistGoto——已载内直跳、
    // 不足自动补拉）；重绘重建 input，值随 H.page
    info.innerHTML = n ? `第 <input autocomplete="off" name="hg_vcs_hpgin" class="hg-vcs-hpgin" value="${H.page}" ` +
      `title="输入页码回车跳转（共 ${vpages} 页）"> / ${vpages} 页` : '—';
    const inp = info.querySelector('.hg-vcs-hpgin');
    if (inp) inp.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault(); e.stopPropagation();
      const v = parseInt(inp.value, 10);
      if (v >= 1) _vcsHistGoto(v);
    });
  }
  if (prev) prev.disabled = H.page <= 1;
  // next 可点性按已载页判定（› 到已载末页再点=拉下一块，累积式语义不变）
  if (next) next.disabled = !n || (H.page >= loadedPages && atEnd && !_vcsHistBusy());
  if (cnt) {
    if (!n) cnt.textContent = '';
    else if (total != null) cnt.textContent = `共 ${total} 条`;
    else cnt.textContent = `已载 ${n} 条` + (atEnd ? '（已到最早）' : '');
  }
}

// v3.5.148（用户批注「没有页跳转」）：跳到第 p 页——已载内直跳；不足自动
// 串行补拉（每轮 100 条，guard 12 轮封顶防巨仓长拉；svn 无 total 按
// exhausted/非整百启发式判到底）；deepseek 首次跳远页会有 1~2s 补拉延迟
function _vcsHistGoto(p) {
  const H = _vcsHist; if (!H) return;
  const arr = _vcsHistActive();
  if (!arr || !arr.length) return;
  const total = _vcsHistTotal();
  const vpages = total != null ? Math.max(1, Math.ceil(total / H.size))
    : Math.max(1, Math.ceil(arr.length / H.size));
  p = Math.min(p, vpages);
  const need = p * H.size;
  if (arr.length >= need || (total != null && arr.length >= total)) {
    H.page = p; _vcsHistPaintList(true); return;
  }
  if (_vcsHistBusy()) return;
  let guard = 0;
  const _step = () => {
    const a2 = _vcsHistActive();
    const t2 = _vcsHistTotal();
    const endKnown = t2 != null ? a2.length >= t2
      : (H.exhausted || !(a2.length && a2.length % 100 === 0));
    if (a2.length >= need || endKnown || ++guard > 12 || !H.ov.isConnected) {
      H.page = Math.min(p, Math.max(1, Math.ceil(a2.length / H.size)));
      _vcsHistPaintList(true);
      return;
    }
    _vcsHistFetch(false, _step);
  };
  _step();
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
    body: JSON.stringify({ root: VCS.root, rev }) })
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


// ---- 数据 ----
// v3.5.264：lite=true（60s tick 用）只拉 status 本身；svn 的 changes 补拉
// 跳过——改动列表只在激活/手动⟳/写操作后全量扫
function _vcsReload(lite) {
  if (!lite) VCS.showUnv = false;   // v3.5.292：全量刷新重置未版本控制折叠态（默认干净视图=svn st -q）
  VCS.busy = true; _vcsTs = Date.now(); _vcsPaint();
  fetch('/api/tree/roots').then(r => r.json()).then(jr => {
    const roots = (jr && jr.ok) ? (jr.roots || []) : [];
    // v3.5.251（用户定调）：当前 Claude 会话工程目录并入（去重——文件树
    // 已含时不再列）；AI 正在操作的工程不看文件树也能直接看它的 git/svn
    const hgCwd = (typeof _HG !== 'undefined' && _HG.cwd) || null;
    if (hgCwd && !roots.includes(hgCwd)) roots.push(hgCwd);
    // v4.0.1（用户拍板「已打开的工程，不用必须在文件树打开就能看 git」）：
    // 所有会话的工程目录都进候选——后端 _project_roots 同口径放行
    for (const s of ((typeof _HG !== 'undefined' && _HG.sessions) || [])) {
      if (s && s.cwd && !roots.includes(s.cwd)) roots.push(s.cwd);
    }
    if (!VCS.root) {
      const saved = localStorage.getItem('hg-vcs-root');
      VCS.root = (saved && roots.includes(saved)) ? saved
        : (roots.includes(hgCwd) ? hgCwd : (roots[0] || ''));
    }
    if (!VCS.root) {
      VCS.busy = false;
      if (_vpEl) _vpEl.innerHTML = '<div class="hg-vcs-empty">先在左侧文件树「＋」打开一个工程目录，这里会显示它的 git / svn 状态。</div>';
      return;
    }
    localStorage.setItem('hg-vcs-root', VCS.root);
    return fetch('/api/vcs/status', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: VCS.root }) }).then(r => r.json()).then(js => {
      VCS.busy = false;
      // v3.5.267（全审严重项）：lite tick 不抹已载改动列表——svn 轻响应恒
      // files:[]+changes_pending，整体替换会把已扫出的改动清成假「干净」；
      // lite 只更新版本头，files/changes_* 沿用现值
      if (js.ok && lite && js.changes_pending && VCS.data && !VCS.data.err) {
        // svn 轻响应：只更新版本头，files/changes_* 沿用现值
        VCS.data.rev = js.rev || VCS.data.rev;
        VCS.data.branch = js.branch || VCS.data.branch;
        VCS.data.ahead = js.ahead; VCS.data.behind = js.behind;
      } else {
        // v3.5.268（复核）：git/非 lite 整体换新——git tick 自带完整新鲜
        // files（v3.5.124「改动/外部命令后自动跟上」既定用途不失效）
        VCS.data = js.ok ? js : { err: js.err || '状态获取失败', vcs: null };
      }
      _vcsPaint();
      // v3.5.264（Q1）：svn status 已轻量化（只有 info）——改动列表由
      // changes 端点惰性补拉（独立 chgBusy，不置灰 logbtn）
      if (js.ok && !lite) setTimeout(_vcsRemoteAutoAsk, 600);
      if (js.ok && js.changes_pending && !VCS.chgBusy && !lite) _vcsReloadChanges();
      // v3.5.266（用户需求「点到版本，最近提交就后台刷出来，不等点提交
      // 历史」）：激活即后台补拉最近提交（_vcsLogBusy 防连点；lite tick
      // 不拉——60s 轻轮询保持 info 级）
      if (!lite && !_vcsLogBusy) _vcsReloadLog();
    });
  }).catch(e => { VCS.busy = false; VCS.data = { err: String(e) }; _vcsPaint(); });
}
// v3.5.264（Q1）：改动列表独立拉取（svn 全树 status 长耗时，后端 90s 超时）
// v3.5.272（报告 §6 分层加载）：两段式——顶层 --depth empty 秒回（实测
// 0.45s vs 全树 39~54s）立即出列表，全树后台补扫完成后覆盖
function _vcsReloadChanges() {
  if (VCS.chgBusy || !VCS.root) return;
  VCS.chgBusy = true; _vcsPaint();
  // v3.5.275（对抗审 F3/F5）：世代计数——切工程/写操作成功都 ++chgGen
  // 作废在途链（旧链收尾只清 busy 不写已 stale 数据），并按 pending 重臂
  // 新扫描（F3-A 挂死根治：旧链不再占死新工程的补拉门）
  const _gen0 = (VCS.chgGen = (VCS.chgGen || 0) + 1);
  const _root0 = VCS.root;
  const _stale = () => (VCS.chgGen || 0) !== _gen0 || VCS.root !== _root0;
  const _rearm = () => {   // F3-A：旧链收尾后新态仍待扫且无人扫→重臂（限2次防死循环）
    if (VCS.chgBusy || !VCS.data || !VCS.data.changes_pending) return;
    // v3.5.276（复审 R2）：重试耗尽置失败叙事——封顶直 return 会留
    // pending 无在途无终态=渲染落「0 个改动/工作区干净」假净
    if ((VCS.chgRetry || 0) >= 2) {
      if (VCS.data && !VCS.data.err && VCS.data.changes_pending) {
        VCS.data.changes_timeout = true;
        VCS.data.changes_pending = false;
        _vcsPaint();   // v3.5.277（终审 X1）：调用方 paint 在 rearm 之前——
                       // 封顶变异后无重绘=终帧假净滞留至下次 tick（≤60s 有界窗）
      }
      return;
    }
    VCS.chgRetry = (VCS.chgRetry || 0) + 1;
    _vcsReloadChanges();
  };
  const _chg = (shallow) => fetch('/api/vcs/changes', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root: _root0, shallow: shallow ? 1 : 0 }) })
    .then(r => r.json());
  let _j1ok = false;
  _chg(true).then(j1 => {
    // v3.5.276（复审 R6）：已作废短路二段（不再为旧 root 白跑 39~90s
    // 全树），直接落收尾——null 经 stale 分支早退+rearm 即时接管新工程
    if (_stale()) return null;
    if (j1 && j1.ok && VCS.data && !VCS.data.err) {
      _j1ok = true;
      VCS.data.files = j1.files || [];
      VCS.data.truncated = j1.truncated || 0;
      VCS.data.truncated_unv = j1.truncated_unv || 0;   // a455：被截断的未版本控制数
      VCS.data.symlink_hidden = j1.symlink_hidden || 0;   // vcs-report：网络盘符号链接误报过滤计数
      VCS.data.changes_timeout = false;
      VCS.data.changes_shallow = !j1.shallow_skipped;   // a455：远端已给全量
      _vcsPaint();
      // a455：远端模式下第一段就是全量，跳过第二段（省一次往返）
      if (j1.shallow_skipped) {
        VCS.data.changes_pending = false;
        VCS.chgRetry = 0;
        return null;
      }
    }
    return _chg(false);   // 二段：全树补扫
  }).then(j2 => {
    VCS.chgBusy = false;
    if (_stale()) { _vcsPaint(); _rearm(); return; }   // 已作废：结果弃+重臂
    // a455：一段已含全量（远端模式）时不去请求二段，j2 为 null——
    // 这不是失败，保持一段结果即可，绝不能落到下面的「二段失败」叙事。
    // 三路审计 C-F1：717 行那次 paint 时 chgBusy/pending 还是旧值（渲染
    // 「全树扫描中…」），随后早退跳过了终态 paint——干净远程仓库会整屏
    // 卡在扫描态最长 60s。此处补终态重绘。
    if (j2 === null && _j1ok) { _vcsPaint(); return; }
    if (VCS.data && !VCS.data.err) {
      if (j2 && j2.ok) {
        if (j2.changes_timeout) {
          // F8 改良：全树超时保留 shallow 已示列表，仅置超时叙事（不空屏）
          // v3.5.276（R5）：shallow 标记保留——正文列表尾据此标注「仅顶层」
          VCS.data.changes_timeout = true;
        } else {
          VCS.data.files = j2.files || [];
          VCS.data.truncated = j2.truncated || 0;
          VCS.data.truncated_unv = j2.truncated_unv || 0;   // a455：被截断的未版本控制数
          VCS.data.symlink_hidden = j2.symlink_hidden || 0;   // vcs-report：网络盘符号链接误报过滤计数
          VCS.data.changes_timeout = false;
          VCS.data.changes_shallow = false;
        }
        VCS.data.changes_pending = false;
        VCS.chgRetry = 0;
      } else if (_j1ok) {
        // F3-B：一段成功二段失败——shallow 列表在场+失败叙事
        // v3.5.277（终审 X2）：shallow 保留——footnote 同挂（文案已通用化）
        VCS.data.changes_timeout = true;
        VCS.data.changes_pending = false;
      } else {
        // F3-C：两段皆败——绝不允许落「干净」假象，置失败叙事
        VCS.data.changes_timeout = true;
        VCS.data.changes_shallow = false;
        VCS.data.changes_pending = false;
      }
    }
    _vcsPaint();
  }).catch(() => {
    VCS.chgBusy = false;
    // F3-C 同款：异常收尾不得假净
    if (!_stale() && VCS.data && !VCS.data.err) {
      VCS.data.changes_timeout = true;
      VCS.data.changes_shallow = false;
      VCS.data.changes_pending = false;
    }
    _vcsPaint(); _rearm();
  });
}
function _vcsReloadLog() {
  // v2：浏览态回补——从已载量一次拿够（reset 语义，弹窗/面板双视图同步）
  if (_vcsLogBusy) return;           // 防连点重复 fetch
  _vcsLogBusy = true;
  const myseq = (_vcsLogSeq = ++_vcsLogSeq);
  _vcsHistLseq++;   // v3.5.265：同时作废翻页在途响应（同数组双写者互斥）
  fetch('/api/vcs/log', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // v3.5.267（全审一般项）：回补语义改「头部增量」——固定拉最新 100
    // 去重后拼到已载数组头，不动尾部更早条目。旧「按 hadLen 整量重拉+
    // 整体替换」在 hadLen>500 时被后端 _LOG_CAP 截断=确定性缩水（v3.5.265
    // 声称修实则只去了前端上限）；且天然不再丢翻页已载条目
    body: JSON.stringify({ root: VCS.root, limit: 100 }) })
    .then(r => r.json()).then(j => {
      _vcsLogBusy = false;
      // v3.5.265（Q2-3）：翻页/重开窗口后迟到的回补响应丢弃——不再覆盖
      // _vcsHistFetch 已 push 的更早条目
      if (myseq !== _vcsLogSeq) return;
      if (!j.ok) { VCS.log = null; VCS.total = undefined; }
      else {
        const _oldL = VCS.log || [];
        const _known = new Set(_oldL.map(c => c.rev));
        const _addH = (j.commits || []).filter(c => c.rev && !_known.has(c.rev));
        VCS.log = _addH.concat(_oldL);
        // v3.5.268（复核轻微项）：svn 拼头后 rev 相邻性校验——两轮回补间隔
        // 新增 >100 时新头与旧头间有中段空洞，r 差>1 整体重建（git 是 sha
        // 无序不可判，维持拼头——空洞自愈出口在查询态 reset）
        if (_addH.length && _oldL.length
            && ((VCS.data || {}).vcs === 'svn')) {
          const _nh = parseInt(_addH[_addH.length - 1].rev, 10) || 0;
          const _oh = parseInt(_oldL[0].rev, 10) || 0;
          if (_nh && _oh && _nh + 1 < _oh) VCS.log = (j.commits || []).slice();
        }
        if (j.total !== undefined) VCS.total = j.total;   // P2：无 total 不覆盖已有精确值
      }
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
  VCS.busy = true; _vcsPaint();
  fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.assign({ root: VCS.root }, body || {})) })
    .then(r => r.json().then(j => ({ st: r.status, j })).catch(() => ({ st: r.status, j: null })))
    .then(({ st, j }) => {
      VCS.busy = false;
      const ok = !!(j && j.ok);
      if (!ok) {
        const why = (j && j.err) ? j.err : ('HTTP ' + st);
        showBanner(label + '失败：' + why, 6000, true);
        if (j && j.out) { VCS.out = j.out; }
      }
      // v3.5.276（复审 R1）：gen++ 提到 ok 公共层——update/commit 走 done
      // 回调曾漏作废在途链，提交前扫描快照照样回盖（F5 只修了 add 路径）
      if (ok) VCS.chgGen = (VCS.chgGen || 0) + 1;
      if (done) done(ok, j || {});
      else if (ok) _vcsReload();
      else _vcsPaint();
    })
    .catch(e => { VCS.busy = false; showBanner(label + '失败：' + e, 5000, true); _vcsPaint(); });
}

// ---- 渲染 ----
function _vcsPaint() {
  if (!_vpEl) return;
  const D = VCS.data;
  const rootsSel = _vcsRootsHtml();
  if (!D) { _vpEl.innerHTML = rootsSel + '<div class="hg-vcs-loading">加载中…</div>'; return; }
  if (D.err && !D.vcs) {
    _vpEl.innerHTML = rootsSel +
      `<div class="hg-vcs-empty">${esc(D.err)}</div>` +
      `<div class="hg-vcs-acts"><button class="btn ghost" name="hg_vcs_refresh">⟳ 重试</button></div>`;
    _vcsBind(true);
    return;
  }
  const head = _vcsHeadHtml(D);
  if (!D.vcs) { _vpEl.innerHTML = rootsSel + head; _vcsBind(false); return; }
  const files = D.files || [];
  // v3.5.292（用户实锤「svn 一大堆没用的改动文件，平时敲 svn st -q」）：svn 的
  // ? 未版本控制文件（内核编译产物/临时文件为主，动辄几百个）默认折叠成一条
  // 汇总——实质改动 M/A/D/R/C 不再被淹没。git 有 .gitignore 不需要此过滤，
  // 维持原样。展开后 ? 行照常渲染：二元组保原数组索引（_vcsBind 的
  // files[data-i] 取行不串位），＋add/勾选提交链路不变（vcs.py 勾选 ? 先
  // svn add 再提交）。showUnv 在 _vcsReload 全量刷新/切工程时重置回折叠。
  const _svn = D.vcs === 'svn';
  const _core = [], _unv = [];
  if (_svn) files.forEach((f, i) => { (f.st === '?' ? _unv : _core).push([f, i]); });
  const _coreN = _svn ? _core.length : files.length;
  const _showUnv = _svn && !!VCS.showUnv;
  const nSel = VCS.sel.size;
  const canOp = D.tool && !VCS.busy;
  _vpEl.innerHTML = rootsSel + head +
    `<div class="hg-vcs-acts">` +
    `<button class="btn ghost" name="hg_vcs_commit" ${canOp && nSel ? '' : 'disabled'}>☑ 提交（${nSel}）</button>` +
    `<button class="btn ghost" name="hg_vcs_update" ${canOp ? '' : 'disabled'}>⇩ ${D.vcs === 'git' ? 'Pull' : 'Update'}</button>` +
    // a650：git 专属操作组（svn 无对应概念，按 D.vcs 隐藏而不是置灰）
    (D.vcs === 'git' ? `<button class="btn ghost" name="hg_vcs_push" ${canOp ? '' : 'disabled'} ` +
      `title="推送到远端（不自动执行）">⇧ Push</button>` : '') +
    // a650：勾选相关操作常驻渲染（勾选时只切 disabled，不重绘——否则
    // 条件渲染的按钮要等下次整块刷新才出现）
    (D.vcs === 'git' ? `<button class="btn ghost" name="hg_vcs_unstage" ${canOp && nSel ? '' : 'disabled'} ` +
      `title="把勾选文件移出暂存区（相当于 git restore --staged）">撤销暂存</button>` : '') +
    `<button class="btn ghost hg-vcs-danger" name="hg_vcs_discard" ${canOp && nSel ? '' : 'disabled'} ` +
    `title="${D.vcs === 'git' ? '丢弃勾选文件的工作区改动（不可逆，会先自动快照）' : 'revert 勾选文件（不可逆，会先自动快照）'}">丢弃改动</button>` +
    (D.vcs === 'git' ? `<button class="btn ghost" name="hg_vcs_stash" ${canOp ? '' : 'disabled'} ` +
      `title="暂存管理（stash 列表 / 存入 / 取出）">Stash</button>` +
      `<button class="btn ghost" name="hg_vcs_fetch" ${canOp ? '' : 'disabled'} ` +
      `title="只取远端更新不合并，先看清再决定">Fetch</button>` : '') +
    (D.vcs === 'git' ? `<button class="btn ghost" name="hg_vcs_tags" ${canOp ? '' : 'disabled'} ` +
      `title="标签管理（创建 / 删除）">标签</button>` : '') +
    `<span class="hg-vcs-hint">勾选后提交；点行看改动</span></div>` +
    (_coreN
      ? `<div class="hg-vcs-files">` + (_svn
          ? _core.map(([f, i]) => _vcsFileHtml(f, i)).join('')
          : files.map((f, i) => _vcsFileHtml(f, i)).join('')) + `</div>`
        + (D.truncated ? `<div class="hg-vcs-more">还有 ${D.truncated} 个实质改动未显示（用命令行查看）</div>` : '')
        // v3.5.276（R5）：超时但列表在场=顶层结果，明示口径消解头部「未获取」张力
        + (D.changes_timeout && D.changes_shallow ? `<div class="hg-vcs-more">以上为顶层扫描结果（全树扫描未完成，完整改动请用命令行 svn status 查看或点 ⟳ 重试）</div>` : '')
      : D.changes_timeout
        ? `<div class="hg-vcs-empty">全树改动扫描超时（网络盘大仓库）——版本信息已就绪；改动列表请用命令行 svn status 查看。</div>`
        : (D.changes_pending && (VCS.chgBusy || D.changes_shallow))
          ? `<div class="hg-vcs-empty">改动列表扫描中…（网络盘大仓库可能需要数十秒）</div>`
          : (_svn && (_unv.length || D.truncated_unv))
            ? `<div class="hg-vcs-empty">没有实质改动（${_unv.length ? '另有 ' + _unv.length + ' 个未版本控制文件已折叠，点下方展开可 svn add' : D.truncated_unv + ' 个未版本控制文件因 500 条额度截断未显示'}）。</div>`
            : `<div class="hg-vcs-empty">工作区干净，没有未提交的改动。</div>`) +
    // 三路审计 C-F6：core≥500 时未版本控条目为 0 但 truncated_unv 可能上万
    // ——原条件 _unv.length 非零才渲染折叠区，截断信息两处消费点全不可达。
    (_svn && (_unv.length || D.truncated_unv)
      ? `<div class="hg-vcs-unv" data-vcs-unv="1">` +
        (_showUnv
          ? `<div class="hg-vcs-unv-t">▾ 未版本控制 ${_unv.length}${D.truncated_unv ? '+' : ''} 个（点收起）——勾选后提交时先 svn add 再提交${D.truncated_unv ? '；另有 ' + D.truncated_unv + ' 个未列出' : ''}</div><div class="hg-vcs-files">` + _unv.map(([f, i]) => _vcsFileHtml(f, i)).join('') + `</div>`
          : `<div class="hg-vcs-unv-t">▸ 未版本控制 ${_unv.length || D.truncated_unv}${D.truncated_unv && _unv.length ? '+' : ''} 个（${_unv.length ? '编译产物/临时文件为主——点展开' + (D.truncated_unv ? '，仅列出前 ' + _unv.length + ' 个' : '') : '全部因 500 条额度截断未列出——实质改动占满了额度'}）</div>`) + `</div>`
      : '') +
    (VCS.out ? `<div class="hg-vcs-out"><div class="hg-vcs-out-t">上次命令输出</div><pre>${esc(VCS.out.slice(0, 4000))}</pre></div>` : '') +
    // v3.5.265（Q3 首选嫌疑缓解）：busy 期置灰同时给明确提示（旧=静默灰
    // 按钮，svn 扫描窗内点击零反馈=「点了不弹窗」的主观来源）
    `<div class="hg-vcs-acts"><button class="btn ghost" name="hg_vcs_logbtn" ${canOp ? '' : 'disabled'} title="${VCS.busy ? '状态扫描中，稍候再点' : ''}"><span style="vertical-align:-2.5px">${ICO16.log}</span> 提交历史${VCS.busy ? '（扫描中…）' : ''}</button>` +
    `<button class="btn ghost" name="hg_vcs_refresh" ${VCS.busy ? 'disabled' : ''}>⟳ 刷新</button></div>` +
    // v3.5.133（用户拍板「面板只显示最近20条」）：内嵌列表 20 封顶，全量
    // 走「提交历史」弹窗（_vcsHistOpen）
    (VCS.log ? `<div class="hg-vcs-sec">最近提交（点行看该提交改了什么）</div>` + VCS.log.slice(0, 20).map(c =>
      `<div class="hg-vcs-logrow" data-vcsrev="${esc(c.rev || '')}" title="${esc(c.msg || '')}" style="cursor:pointer;">` +
      `<span class="hg-vcs-logrev">${esc(c.short || c.rev || '')}</span>` +
      `<span class="hg-vcs-logmsg">${esc((c.msg || '').slice(0, 60))}</span>` +
      (c.ins != null ? `<span class="hg-vcs-stat"><b class="up">+${esc(c.ins || 0)}</b> <b class="del">-${esc(c.del || 0)}</b></span>` : '') +
      `<span class="hg-vcs-logau">${esc(c.author || '')}</span></div>` +
      `<div class="hg-vcs-cfiles" data-vcsfiles="${esc(c.rev || '')}"${VCS.exp.has(c.rev) ? '' : ' style="display:none;"'}></div>`).join('') +
      (VCS.log.length > 20
        ? `<div class="hg-vcs-hlfoot">已显示最近 20 / 共 ${VCS.total || VCS.log.length} 条——点上方历史按钮看全部</div>` : '')
      : '');
  _vcsBind(true);
  if (!VCS.log) return;   // a438：无提交列表（还没加载/加载失败）就没有展开态要恢复
  // a438（审计 P2）：展开态存数据层，重绘后自动恢复（原来只在 DOM 上，
  // _vcsPaint 重建 innerHTML 即全部折叠——30s 内切回版本 tab 必现）。
  // 展开的提交需要重新拉文件清单（DOM 里的内容也随重绘没了）。
  // 清掉已不在当前列表（切工程/刷新掉出前 20）的记录后再重建，避免白拉。
  const alive = new Set((VCS.log || []).slice(0, 20).map(c => c.rev || ''));
  [...VCS.exp].forEach(r => { if (!alive.has(r)) VCS.exp.delete(r); });
  VCS.exp.forEach(rev => {
    const box = _vpEl.querySelector('[data-vcsfiles="' + CSS.escape(rev) + '"]');
    if (box) _vcsLoadCommitFiles(rev, box);   // 有缓存直接渲染，没缓存再 fetch
  });
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
  // v3.5.271（SVN 报告完整版 Q4）：changes_timeout 时不得显示「0 个改动」
  //——空数组是「未获取」不是「干净」，头部与正文必须同一叙事（旧=UI 说谎，
  // 会诱导用户误判工作区干净而漏提交）
  // v3.5.275 F7：在途扫描（busy/shallow）优先于超时叙事——重扫期间头部
  // 显「扫描中」不滞留「未获取」；挂起（pending 无 busy）由失败叙事兜底
  // v3.5.292：svn 头部计数同步排除 ? 未版本控制（与正文折叠口径一致）——
  // 「500 个改动」实为 2 个 M + 498 个编译产物，必须说的是实质改动数
  const _svnU = D.vcs === 'svn' ? (D.files || []).filter(f => f.st === '?') : [];
  const _chgTxt = (D.changes_pending && (VCS.chgBusy || D.changes_shallow)) ? '全树扫描中…'
    : D.changes_timeout ? '改动数未获取（扫描超时）'
    : `${(D.files || []).length - _svnU.length} 个改动` +
      (_svnU.length || D.truncated_unv ? `（另有 ${_svnU.length}${D.truncated_unv && _svnU.length ? '+' : ''} 个未版本控制）` : '') +
      (D.symlink_hidden ? `（已隐藏 ${D.symlink_hidden} 项网络盘符号链接误报）` : '');
  return `<div class="hg-vcs-head"><span class="hg-vcs-badge ${esc(D.vcs)}">${esc(D.vcs)}</span>` +
    // a650：分支名从只读文本改成可点击下拉（git 才有分支；svn 维持只读）
    `<button class="hg-vcs-branch hg-vcs-branchbtn" name="hg_vcs_branch" ` +
    `title="${D.vcs === 'git' ? '点击切换 / 管理分支' : 'svn 无分支概念'}">` +
    `⎇ ${esc(D.branch || '(游离 HEAD)')}${esc(rev)}${esc(ab)}</button>` +
    `<span class="hg-vcs-count">${_chgTxt}</span>` +
    _vcsRemoteChip(D) + `</div>`;
}

// a455：头部右侧的「执行方式」芯片。三种态：
//   ssh   —— 已配置且正在用远端（绿点）
//   smb   —— 网络盘但没配 / 刚回退（橙点，可点开引导）
//   local —— 纯本地盘（灰点，不打扰；纯 Windows 环境就停在这）
function _vcsRemoteChip(D) {
  const mode = (D && D.remote_used) || '';
  const hint = (D && D.remote_hint) || '';
  if (mode === 'ssh') {
    return `<button class="hg-vcs-rmchip on" name="hg_vcs_remote" title="正在用构建机执行版本命令（SSH 加速）">` +
      `SSH 加速</button>`;
  }
  if (mode === 'smb') {
    // a455：区分「根本没配」和「配了但这次失败了」——后者不能再说「建议启用」，
    // 用户会以为自己没配过，反复重填。
    if (hint) {
      return `<button class="hg-vcs-rmchip warn" name="hg_vcs_remote" ` +
        `title="SSH 已配置但本次回退到本地：${esc(hint)}">已配置·已回退</button>`;
    }
    return `<button class="hg-vcs-rmchip warn" name="hg_vcs_remote" ` +
      `title="当前走网络盘本地 svn，扫描很慢——建议启用 SSH 加速">本地·建议 SSH</button>`;
  }
  return '';
}
function _vcsFileHtml(f, i) {
  const cls = _VCS_ST_CLS[f.st] || 'm';
  const checked = VCS.sel.has(f.rel) ? ' checked' : '';
  const ren = f.st === 'R' && f.old_rel
    ? `<span class="hg-vcs-ren">${esc(f.old_rel)} →</span>` : '';
  return `<div class="hg-vcs-frow" data-i="${i}">` +
    `<span class="hg-vcs-st ${cls}" title="${_VCS_ST_TXT[f.st] || f.st}">${esc(f.st)}</span>` +
    `<input type="checkbox" name="hg_vcs_f" class="hg-vcs-ck" data-rel="${esc(f.rel)}"${checked} title="勾选纳入提交">` +
    `<span class="hg-vcs-fpath" title="${esc(f.path)}">${ren}${esc(f.rel)}</span>` +
    (f.st === '?' ? `<button class="btn ghost icon-btn" name="hg_vcs_addone" data-rel="${esc(f.rel)}" title="svn add / git add 纳入版本控制" style="flex-shrink:0;">＋</button>` : '') +
    `</div>`;
}
// a438（审计 P2）：提交行的改动清单加载/渲染（点击与重绘恢复共用一份）。
// 缓存按 rev 存，重绘后直接重放，不再重复打接口。
function _vcsLoadCommitFiles(rev, box) {
  box.style.display = 'block';
  const render = (files) => {
    box.dataset.loaded = '1';
    box.innerHTML = files.map(f =>
      `<div class="hg-vcs-cfrow" data-rev="${esc(rev)}" data-path="${esc(f.path)}" data-st="${esc(f.st)}" title="查看该提交中此文件的改动">${esc(f.st)} ${esc(f.path)}</div>`).join('')
      || '<div class="hg-vcs-empty">该提交无文件级改动记录</div>';
    box.querySelectorAll('.hg-vcs-cfrow').forEach(fr => {
      // 轻审R4：改调公共 _vcsFileDiffClick——旧内联副本无 buildDiffViewerTab
      // 异常防护（unhandled rejection 无提示），与弹窗版已漂移
      fr.onclick = () => _vcsFileDiffClick(rev, fr.dataset.path, fr.dataset.st, fr);
    });
  };
  const cached = VCS.cfCache.get(rev);
  if (cached) { render(cached); return; }
  if (box.dataset.loaded) return;      // 已渲染过且无缓存变化
  // a438：在途去重——连续两次 _vcsPaint 会各拿一个新 box，旧回调因
  // document.contains 判假被丢弃，但请求已经白发了一发。按 rev 记在途。
  if (!VCS.cfPending) VCS.cfPending = new Set();
  if (VCS.cfPending.has(rev)) { box.innerHTML = '<div class="hg-vcs-empty">加载中…</div>'; return; }
  VCS.cfPending.add(rev);
  // a456（第三轮审计 P1：上一版按请求递增代际，把并发请求互相作废）：
  // 判据改为**快照 cfCache 引用**。teardown / 换工程会把 cfCache 换成新 Map，
  // 引用不等即说明「面板已关/已换工程」，语义正好；同时并发展开多个提交时
  // 它们共享同一个 Map，互不干扰。
  const myCache = VCS.cfCache;
  box.innerHTML = '<div class="hg-vcs-empty">加载中…</div>';
  fetch('/api/vcs/commit_files', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root: VCS.root, rev }) })
    .then(r => r.json())
    .then(j => {
      VCS.cfPending.delete(rev);
      if (myCache !== VCS.cfCache) return;   // 面板已关/已换工程，结果作废
      // a452（审计 P2）：缓存先写，再做存活检查。原来存活检查在 set 之前，
      // 请求途中 _vcsPaint 重绘（30s 轮询）会让旧 box 失效 → 直接 return，
      // 结果永不进缓存，新 box 一直停在「加载中…」，要再触发一次重绘才恢复。
      if (j.ok) VCS.cfCache.set(rev, j.files || []);
      // 面板可能在请求途中被关掉
      if (!_vpEl || !document.contains(box)) return;
      if (!j.ok) { box.innerHTML = '<div class="hg-vcs-empty">' + esc(j.err || '获取失败') + '</div>'; return; }
      render(j.files || []);
    })
    .catch(e => {
      VCS.cfPending.delete(rev);
      if (myCache !== VCS.cfCache) return;
      if (!_vpEl || !document.contains(box)) return;
      box.innerHTML = '<div class="hg-vcs-empty">获取失败：' + esc(String(e)) + '</div>';
    });
}

function _vcsBind(paintRoots) {
  if (!_vpEl) return;
  if (paintRoots) {
    const sel = _vpEl.querySelector('select[name="hg_vcs_root"]');
    if (sel) {
      fetch('/api/tree/roots').then(r => r.json()).then(j => {
        const roots = (j && j.ok) ? (j.roots || []) : [];
        // v4.0.1：会话工程目录同样并入（后端 _project_roots 同口径放行
        // ——已打开的工程不必先在文件树登记）
        const hgCwd = (typeof _HG !== 'undefined' && _HG.cwd) || null;
    if (hgCwd && !roots.includes(hgCwd)) roots.push(hgCwd);
        for (const s of ((typeof _HG !== 'undefined' && _HG.sessions) || []))
          if (s && s.cwd && !roots.includes(s.cwd)) roots.push(s.cwd);
        if (!roots.includes(VCS.root) && roots.length) VCS.root = roots[0];
        sel.innerHTML = roots.map(r0 =>
          `<option value="${esc(r0)}"${r0 === VCS.root ? ' selected' : ''}>${esc(r0)}</option>`).join('')
          || '<option value="">（文件树为空）</option>';
      }).catch(() => {});
      sel.onchange = () => {
        VCS.chgGen = (VCS.chgGen || 0) + 1;   // v3.5.275 F3-A：作废在途扫描链
        VCS.root = sel.value; localStorage.setItem('hg-vcs-root', sel.value);
        VCS.data = null; VCS.log = null; VCS.sel = new Set();
        VCS.exp = new Set(); VCS.cfCache = new Map(); VCS.cfPending = new Set();   // a438：换工程，展开态/缓存在途都属于旧工程（换新 Map 即作废）
        _vcsReload(); _vcsReloadLog();
      };
    }
  }
  _vpEl.querySelectorAll('[name="hg_vcs_refresh"]').forEach(b =>
    b.onclick = () => { VCS.sel = new Set(); _vcsReload(); });
  const lb = _vpEl.querySelector('[name="hg_vcs_logbtn"]');
  // v3.5.133（用户需求「历史提交新增一个弹窗 UI 式显示」）：按钮改开
  // 提交历史弹窗（打开时后台补刷新——v3.5.127「无条件重拉」语义由弹窗
  // 承接：无缓存即拉，有缓存先显后刷）
  if (lb) lb.onclick = () => _vcsHistOpen();
  // a455：执行方式芯片 → SSH 配置弹窗
  const _rmc = _vpEl.querySelector('[name="hg_vcs_remote"]');
  if (_rmc) _rmc.onclick = (e) => { e.stopPropagation(); _vcsRemoteDialog(); };
  // a650：分支 / stash / 标签 / push / fetch / 撤销暂存 / 丢弃改动
  const _brb = _vpEl.querySelector('[name="hg_vcs_branch"]');
  if (_brb) _brb.onclick = (e) => {
    e.stopPropagation();
    if ((VCS.data || {}).vcs === 'git') _vcsBranchDialog();
    else showBanner('svn 没有分支概念（可查看历史 / 修订号）', 3000, true);
  };
  const _stb = _vpEl.querySelector('[name="hg_vcs_stash"]');
  if (_stb) _stb.onclick = () => _vcsStashDialog();
  const _tgb = _vpEl.querySelector('[name="hg_vcs_tags"]');
  if (_tgb) _tgb.onclick = () => _vcsTagsDialog();
  const _fab = _vpEl.querySelector('[name="hg_vcs_fetch"]');
  if (_fab) _fab.onclick = () => {
    hgModal('Fetch 只取不合并',
      `<div class="hg-modal-body">在 ${esc(VCS.root)}\n执行 git fetch --prune\n\n` +
      `只更新远端引用，不动工作区和当前分支；看完 ahead/behind 再决定 Pull。</div>`,
      [{ label: '取消', value: false }, { label: '执行', primary: true, value: true }])
      .then(ok => {
        if (!ok) return;
        _vcsApi('/api/vcs/fetch', {}, 'Fetch', (ok2, j) => {
          if (j && j.out) VCS.out = j.out;
          _vcsReload();
        });
      });
  };
  const _psb = _vpEl.querySelector('[name="hg_vcs_push"]');
  if (_psb) _psb.onclick = () => {
    const D = VCS.data || {};
    const br = D.branch || '';
    hgModal('Push 推送到远端',
      `<div class="hg-modal-body">将把本地${br ? '分支 ' + esc(br) + ' ' : ''}推送到 origin\n` +
      `（git push origin ${esc(br || '(当前分支)')}）\n\n远端若已有本地没有的提交会被拒绝——先 Fetch/Pull 看清。</div>`,
      [{ label: '取消', value: false }, { label: '推送', primary: true, value: true }])
      .then(ok => {
        if (!ok) return;
        _vcsApi('/api/vcs/push', {}, 'Push', (ok2, j) => {
          if (j && j.out) VCS.out = j.out;
          _vcsReload();
        });
      });
  };
  const _unb = _vpEl.querySelector('[name="hg_vcs_unstage"]');
  if (_unb) _unb.onclick = () => {
    const files = ((VCS.data || {}).files) || [];
    const sel = files.filter(f => VCS.sel.has(f.rel));
    if (!sel.length) return;
    _vcsApi('/api/vcs/unstage', { paths: sel.map(f => f.rel) }, '撤销暂存', () => _vcsReload());
  };
  const _dcb = _vpEl.querySelector('[name="hg_vcs_discard"]');
  if (_dcb) _dcb.onclick = () => _vcsDiscardSelected();
  _vpEl.querySelectorAll('.hg-vcs-ck').forEach(ck => ck.onchange = () => {
    if (ck.checked) VCS.sel.add(ck.dataset.rel); else VCS.sel.delete(ck.dataset.rel);
    // a650：提交/撤销暂存/丢弃改动共用勾选态——只切 disabled，不整块重绘
    const n = VCS.sel.size;
    const _can = !!((VCS.data || {}).tool) && !VCS.busy;
    const cb = _vpEl.querySelector('[name="hg_vcs_commit"]');
    if (cb) { cb.textContent = '☑ 提交（' + n + '）'; cb.disabled = !(n && _can); }
    ['hg_vcs_unstage', 'hg_vcs_discard'].forEach(nm => {
      const b = _vpEl.querySelector('[name="' + nm + '"]');
      if (b) b.disabled = !(n && _can);
    });
  });
  // v3.5.292：未版本控制折叠条展开/收起（? 文件行自身有点击开 diff，冒泡到此按 frow 放行）
  const _uv = _vpEl.querySelector('[data-vcs-unv]');
  if (_uv) _uv.onclick = (e) => {
    if (e.target.closest('input') || e.target.closest('button')
        || e.target.closest('.hg-vcs-frow')) return;
    VCS.showUnv = !VCS.showUnv; _vcsPaint();
  };
  _vpEl.querySelectorAll('.hg-vcs-frow').forEach(row => {
    row.onclick = (e) => {
      if (e.target.closest('input') || e.target.closest('button')) return;
      const f = (VCS.data && VCS.data.files || [])[+row.dataset.i];
      if (!f) return;
      VCS.busy = true; _vcsPaint();
      fetch('/api/vcs/diff', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: VCS.root, path: f.rel, st: f.st }) })
        .then(r => r.json()).then(j => {
          VCS.busy = false; _vcsPaint();
          if (j.ok) { try { buildDiffViewerTab(j.a, j.b); } catch (e) { showBanner('diff 打开失败：' + e, 4000, true); } }
          else showBanner('diff 获取失败：' + (j.err || ''), 4000, true);
        }).catch(e => { VCS.busy = false; _vcsPaint(); showBanner('diff 获取失败：' + e, 4000, true); });
    };
  });
  // v3.5.131（用户批注「历史提交无法点开查看」）：提交行点击展开该提交
  // 改动文件清单；文件行点击物化父/本修订两版开 diff 对比
  _vpEl.querySelectorAll('.hg-vcs-logrow[data-vcsrev]').forEach(row => {
    row.onclick = () => {
      const rev = row.dataset.vcsrev;
      const box = _vpEl.querySelector('[data-vcsfiles="' + CSS.escape(rev) + '"]');
      if (!rev || !box) return;
      if (box.style.display !== 'none') {          // 再点收起
        box.style.display = 'none';
        VCS.exp.delete(rev);                       // a438：收起也要落数据态
        return;
      }
      VCS.exp.add(rev);
      _vcsLoadCommitFiles(rev, box);
    };
  });
  _vpEl.querySelectorAll('[name="hg_vcs_addone"]').forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    const rel = b.dataset.rel;
    const v = (VCS.data || {}).vcs;
    hgModal('纳入版本控制',
      `<div class="hg-modal-body">将执行 ${esc(v === 'svn' ? 'svn add' : 'git add')}：\n${esc(rel)}</div>`,
      [{ label: '取消', value: false }, { label: '执行', primary: true, value: true }])
      .then(ok => {
        if (!ok) return;
        _vcsApi('/api/vcs/add', { paths: [rel] }, 'add');
      });
  });
  const ub = _vpEl.querySelector('[name="hg_vcs_update"]');
  if (ub) ub.onclick = () => {
    const v = (VCS.data || {}).vcs;
    const cmd = v === 'git' ? 'git pull --ff-only' : 'svn update（冲突 postpone 保现场）';
    hgModal(v === 'git' ? 'Pull 拉取更新' : 'Update 更新',
      `<div class="hg-modal-body">将在 ${esc(VCS.root)}\n执行 ${esc(cmd)}</div>`,
      [{ label: '取消', value: false }, { label: '执行', primary: true, value: true }])
      .then(ok => {
      if (!ok) return;
      _vcsApi('/api/vcs/update', {}, '更新', (ok2, j) => {
        if (j && j.out) VCS.out = j.out;
        if (ok2 && j.conflicts && j.conflicts.length)
          showBanner('更新引入冲突 ' + j.conflicts.length + ' 个——请用 svn/git 命令行处理', 8000, true);
        _vcsReload();
      });
    });
  };
  const cb = _vpEl.querySelector('[name="hg_vcs_commit"]');
  if (cb) cb.onclick = () => _vcsCommitModal();
}
function _vcsCommitModal() {
  const D = VCS.data || {};
  const all = D.files || [];
  const selPaths = all.filter(f => VCS.sel.has(f.rel));
  if (!selPaths.length) { showBanner('先勾选要提交的文件', 3000, true); return; }
  const nNew = selPaths.filter(f => f.st === '?').length;
  const ov = document.createElement('div');
  ov.className = 'hg-modal-ov';
  ov.innerHTML =
    `<div class="hg-modal"><div class="hg-modal-title">提交 ${selPaths.length} 个文件（${esc(D.vcs || '')}）</div>` +
    `<div class="hg-modal-body">` +
    selPaths.map(f => `<div class="hg-vcs-cfile"><span class="hg-vcs-st ${_VCS_ST_CLS[f.st] || 'm'}">${esc(f.st)}</span>${esc(f.rel)}</div>`).join('') +
    (nNew ? `<div class="hg-vcs-cnew"><span style="vertical-align:-2.5px">${ICO16.warn}</span> 其中 ${nNew} 个新文件将自动 ${D.vcs === 'svn' ? 'svn add' : 'git add'} 纳入</div>` : '') +
    `<textarea name="hg_vcs_msg" class="hg-vcs-msg" rows="3" placeholder="提交说明（必填，Ctrl+Enter 提交）" spellcheck="false"></textarea>` +
    `</div><div class="hg-modal-acts"></div></div>`;
  const acts = ov.querySelector('.hg-modal-acts');
  const ta = ov.querySelector('textarea[name="hg_vcs_msg"]');
  let close = () => ov.remove();
  // a455（第三轮审计 P1）：这个自建弹窗原来既不登记收口表、也不在 teardown
  // 里摘除——面板关掉后它还挂在 body 上，用户点「提交」会用 teardown 特意
  // 保留的 VCS.root 照发真实 /api/vcs/commit。正是 a438-P1 要堵的写请求。
  // 必须在绑按钮之前替换成 wrapped：按钮闭包拿到的才是带退册的那一版。
  try {
    if (typeof hgModalTrack === 'function') close = hgModalTrack(ov, close);
  } catch (_) {}
  const doCommit = () => {
    const msg = ta.value.trim();
    if (!msg) { showBanner('提交说明必填', 3000, true); ta.focus(); return; }
    close();
    _vcsApi('/api/vcs/commit', { paths: selPaths.map(f => f.rel), message: msg },
            '提交', (ok2, j) => {
      if (j && j.out) VCS.out = j.out;
      if (ok2) { VCS.sel = new Set(); showBanner('已提交' + (j.rev ? ' ' + j.rev : ''), 3500); }
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
  _vpModalHost().appendChild(ov);
  ta.focus();
}


// ==================== a455/a455：SSH 远端加速（版本面板内，不进设置页）====================
// 两层模型（用户实锤：换个 svn 就要重填密码，太怪）：
//   连接档案（主机/账号/口令/密钥）—— 全局共用一份，配一次到处复用
//   工程映射（本地目录 → 远端目录）—— 每个工程一条，通常自动推导
// UI：
//   · 网络盘工程 → 头部橙色芯片；纯本地盘 → 不显示芯片、不打扰
//   · 弹窗顶部「连接」下拉：已有档案直接选，新工程只需确认远端路径
//   · 无任何档案时显示完整表单；有档案时可「新建连接」「管理连接」
function _vcsRemoteDialog() {
  const old = document.getElementById('hgVcsRemoteDlg');
  if (old) old.remove();
  const root = VCS.root || '';
  const ov = document.createElement('div');
  ov.id = 'hgVcsRemoteDlg';
  ov.className = 'hg-vcs-rdlg';
  ov.innerHTML = '<div class="hg-vcs-rdlg-card"><div class="hg-vcs-rdlg-sub">读取配置…</div></div>';
  document.body.appendChild(ov);
  ov.addEventListener('click', (e) => { if (e.target === ov) ov.remove(); });

  fetch('/api/vcs/remote/probe', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root }) })
    .then(r => r.json())
    .then(j => _vcsRemoteRender(ov, root, j || {}))
    .catch(e => {
      const c = ov.querySelector('.hg-vcs-rdlg-card');
      if (c) c.innerHTML = '<div class="hg-vcs-rdlg-msg err">配置读取失败：'
        + esc(String(e)) + '</div>';
    });
}

function _vcsRemoteRender(ov, root, p) {
  const entry = p.entry || {};
  const isNet = !!p.is_network;
  const profiles = p.profiles || [];
  const hasProf = profiles.length > 0;
  const card = ov.querySelector('.hg-vcs-rdlg-card');
  const sub = isNet
    ? (p.configured
        ? '当前工程在<b>网络盘 ' + esc(p.drive || '') + '</b> 上，已接入 SSH 加速——'
          + '版本命令在构建机上执行，全树扫描从数十秒降到 2 秒级。'
        : '检测到工程位于<b>网络盘 ' + esc(p.drive || '') + '</b>——本地 svn 需逐个文件走网络，'
          + '全树扫描通常要数十秒。<br>接入构建机后改为远端执行，一次扫描约 2 秒。')
    : ('当前工程在<b>本地盘 ' + esc(p.drive || '') + '</b> 上，本地 svn 已是毫秒级，'
       + '无需 SSH 加速。<br>若该目录其实是映射盘但没被识别出来，可在此手动配置。');

  // 选中哪个档案：当前工程已配 → 用它；否则用第一个（复用现有连接）
  const selPid = entry.profile_id || (hasProf ? profiles[0].id : '');
  const curProf = profiles.find(x => x.id === selPid) || {};
  const auth = curProf.auth || 'password';

  let html =
    '<div class="hg-vcs-rdlg-title">' + (p.configured ? 'SSH 加速（已配置）' : '启用 SSH 加速') + '</div>' +
    '<div class="hg-vcs-rdlg-sub">' + sub + '</div>' +
    '<div class="hg-vcs-rdlg-row"><label>工程（本地）</label>' +
      '<input data-rm-f="local_root" value="' + esc(root) + '" readonly></div>';

  // ── 连接选择（有档案时）──
  if (hasProf) {
    html += '<div class="hg-vcs-rdlg-row"><label>连接</label>' +
      '<select data-rm-f="profile_id">' +
      profiles.map(x => `<option value="${esc(x.id)}"${x.id === selPid ? ' selected' : ''}>`
        + esc((x.name || x.host) + '  ·  ' + x.user + '@' + x.host + ':' + x.port)
        + '</option>').join('') +
      '<option value="__new">＋ 新建连接…</option>' +
      '</select></div>';
  }

  // a455：远端路径不再让用户填——保存时后端自己到构建机上找这个工程。
  // 已定位到的只读展示出来，纯粹是让用户知道「它找到了哪儿」。
  html +=
    '<div class="hg-vcs-rdlg-row"><label>远端位置</label>' +
      '<input data-rm-f="remote_root_readonly" readonly value="' +
      esc(entry.remote_root || '') + '" placeholder="保存时自动定位（无需填写）"></div>';

  // ── 新连接表单（无档案 / 选了「新建连接」时显示）──
  const showNew = !hasProf;
  html += '<div data-rm-newconn style="' + (showNew ? '' : 'display:none;') + '">' +
    '<div class="hg-vcs-rdlg-row"><label>名称</label>' +
      '<input data-rm-f="name" placeholder="构建机（可留空）" value=""></div>' +
    '<div class="hg-vcs-rdlg-row"><label>主机</label>' +
      '<input data-rm-f="host" placeholder="10.1.74.239" value="' + esc(curProf.host || '') + '"></div>' +
    '<div class="hg-vcs-rdlg-row"><label>端口</label>' +
      '<input data-rm-f="port" value="' + esc(String(curProf.port || 22)) + '"></div>' +
    '<div class="hg-vcs-rdlg-row"><label>用户名</label>' +
      '<input data-rm-f="user" placeholder="gaoyi13" value="' + esc(curProf.user || '') + '"></div>' +
    '<div class="hg-vcs-rdlg-row"><label>认证方式</label>' +
      '<select data-rm-f="auth">' +
        '<option value="password"' + (auth === 'password' ? ' selected' : '') + '>密码登录</option>' +
        '<option value="key"' + (auth === 'key' ? ' selected' : '') + '>私钥文件</option>' +
        '<option value="agent"' + (auth === 'agent' ? ' selected' : '') + '>SSH Agent</option>' +
      '</select></div>' +
    '<div class="hg-vcs-rdlg-row" data-rm-pwd style="' + (auth === 'password' ? '' : 'display:none;') + '">' +
      '<label>密码</label><input type="password" data-rm-f="password" placeholder="填写登录密码"></div>' +
    '<div class="hg-vcs-rdlg-row" data-rm-key style="' + (auth === 'key' ? '' : 'display:none;') + '">' +
      '<label>私钥文件</label><input data-rm-f="key_path" placeholder="留空 = 自动生成 ~/.ssh/id_ed25519" value="' +
      esc(curProf.key_path || '') + '"></div>' +
    '</div>';

  html +=
    '<div class="hg-vcs-rdlg-msg info" data-rmr-msg style="display:none;"></div>' +
    '<div class="hg-vcs-rdlg-acts">' +
      (p.configured ? '<button class="btn ghost" data-rm="del">断开此工程</button>' : '') +
      (hasProf && p.configured ? '<button class="btn ghost" data-rm="deploy">一键部署公钥（免密）</button>' : '') +
      '<button class="btn ghost" data-rm="test">测试连接</button>' +
      '<button class="btn ghost" data-rm="cancel">取消</button>' +
      '<button class="btn primary" data-rm="save">保存</button>' +
    '</div>';

  card.innerHTML = html;

  const q = (s) => card.querySelector(s);
  const val = (f) => {
    const el = q('[data-rm-f="' + f + '"]');
    return el ? String(el.value || '').trim() : '';
  };
  const msgEl = q('[data-rmr-msg]');
  const msg = (txt, kind) => {
    if (!msgEl) return;
    msgEl.style.display = txt ? '' : 'none';
    msgEl.className = 'hg-vcs-rdlg-msg ' + (kind || 'info');
    msgEl.textContent = txt || '';
  };
  if (p.hint) msg('回退原因：' + p.hint, 'err');

  const body = () => {
    const pid = val('profile_id');
    const isNew = !pid || pid === '__new';
    // a455：不传 remote_root——后端会自己到构建机上定位这个工程
    const b = { root: root, enabled: true };
    if (isNew) {
      Object.assign(b, {
        host: val('host'), user: val('user'), port: val('port') || 22,
        auth: val('auth') || 'password',
        password: val('password') || undefined,
        key_path: val('key_path'),
        name: val('name'),
      });
    } else {
      b.profile_id = parseInt(pid, 10);
    }
    return b;
  };

  // 切换连接档案 → 显示/隐藏新连接表单（路径由后端探测，无前端联动）
  const psel = q('[data-rm-f="profile_id"]');
  if (psel) psel.onchange = () => {
    const isNew = psel.value === '__new';
    const nc = q('[data-rm-newconn]');
    if (nc) nc.style.display = isNew ? '' : 'none';
    const rr = q('[data-rm-f="remote_root_readonly"]');
    if (rr && !isNew) rr.value = '';   // 换连接后旧路径不再适用，保存时重新探测
  };

  const asel = q('[data-rm-f="auth"]');
  if (asel) asel.onchange = () => {
    const a = asel.value;
    q('[data-rm-pwd]').style.display = (a === 'password') ? '' : 'none';
    q('[data-rm-key]').style.display = (a === 'key') ? '' : 'none';
  };

  card.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => {
    const act = b.dataset.rm;
    if (act === 'cancel') { ov.remove(); return; }
    if (act === 'del') {
      fetch('/api/vcs/remote/delete', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: root }) })
        .then(r => r.json()).then(() => {
          ov.remove();
          // 三路审计 C-F3：断开是明确的「不要」——落 asked 键。否则 600ms
          // 后 auto-ask 以引导形态把刚关掉的弹窗原地复活（键未落过的工程）。
          try { localStorage.setItem('hg-vcs-ssh-asked:' + root, '1'); } catch (_) {}
          _vcsReload();
        })
        .catch(() => msg('断开失败', 'err'));
      return;
    }
    b.disabled = true;
    const re = () => { b.disabled = false; };
    if (act === 'save' || act === 'test') {
      fetch('/api/vcs/remote/save', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body()) })
        .then(r => r.json()).then(s => {
          if (!s.ok) { re(); msg('保存失败：' + (s.err || ''), 'err'); return null; }
          if (act === 'save') {
            re(); ov.remove(); _vcsReload();
            showBanner('已接入 SSH 加速', 2500);
            return null;
          }
          msg('正在测试连接…', 'info');
          return fetch('/api/vcs/remote/test', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ root: root }) }).then(r => r.json()).then(t => {
            re();
            if (t.ok) {
              msg('连接成功（' + (t.latency_ms || 0) + ' ms）'
                  + (t.svn_version ? '\n远端 svn ' + t.svn_version : '')
                  + (t.git_version ? '\n远端 ' + t.git_version : ''), 'ok');
            } else {
              msg('连接失败：' + (t.err || '未知原因')
                  + '\n可改用「一键部署公钥」走免密登录，或核对主机/端口/用户名/密码。', 'err');
            }
          });
        })
        .catch(e => { re(); msg('请求失败：' + String(e), 'err'); });
      return;
    }
    if (act === 'deploy') {
      msg('正在用已保存的密码登录并部署公钥…', 'info');
      fetch('/api/vcs/remote/deploy_key', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: root }) })
        .then(r => r.json()).then(d => {
          re();
          if (d.ok) {
            msg('公钥已部署，已切换为免密登录。\n公钥：' + (d.pub || ''), 'ok');
            setTimeout(() => { ov.remove(); _vcsReload(); }, 1200);
          } else {
            msg((d.err || '部署失败')
                + (d.pub ? '\n可手动追加到远端 ~/.ssh/authorized_keys：\n' + d.pub : ''), 'err');
          }
        })
        .catch(e => { re(); msg('部署失败：' + String(e), 'err'); });
    }
  });
}
