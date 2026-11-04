// ============================================================
// 全局状态
// ============================================================
const $ = id => document.getElementById(id);
const banner = $('banner');
const portList = $('portList');
const tabs = $('tabs');
const termArea = $('termArea');

// a275 批1c（ZCode #33 DOM 泄漏防线）：页面不可见时全局禁 CSS 动画——
// Chromium 隐藏期不出帧，CSSTransition 无法结算，被虚拟列表/折叠收起的
// 元素被 DocumentTimeline 强引用拖住整棵子树无法 GC（ZCode 实测隐藏期
// 23.5 万节点不回收）。hidden 时加 <html data-document-hidden>，
// CSS 侧全局 transition:none/animation:none
document.addEventListener('visibilitychange', () => {
  document.documentElement.toggleAttribute('data-document-hidden', document.hidden);
});
document.documentElement.toggleAttribute('data-document-hidden', document.hidden);

let connections = {};   // port_id -> conn（含 term/fit/search/xtermWrap/sse 等）
let activePortId = null;

// a286: Tab 栏终极方案——双模式（Chrome 平铺 / Edge 分组抽屉）+ Pin
;(function _tabOverflowInit() {
  const tabsEl = document.getElementById('tabs');
  if (!tabsEl) return;
  const btn = document.getElementById('tabOverflowBtn');
  if (!btn) return;
  let list = null;

  // ===== 配置 =====
  let _tabMode = 'flat';          // 'flat' = Chrome 平铺 | 'drawer' = 分组抽屉
  let _pinned = new Set();         // 固定的 portId
  const _GROUP_LABEL = {
    serial: '串口', ssh: 'SSH', telnet: 'Telnet',
    claude: 'Claude', harness: 'Claude',
    editor: '编辑器', hex: 'Hex', diff: '对比', bindiff: 'Bin对比',
    log: '日志', office: '文件', proxy: '代理', bitcalc: '计算器',
  };
  const _GROUP_ICON = {
    serial: ICO16.plug, ssh: ICO16.terminal, telnet: ICO16.terminal,
    claude: ICO16.zap, harness: ICO16.zap,
    editor: ICO16.file, hex: ICO16.hex, diff: ICO16.compare, bindiff: ICO16.compare,
    log: ICO16.log, office: ICO16.folderOpen, proxy: ICO16.gear, bitcalc: ICO16.calc,
  };
  const _groupOf = c => (c.meta && c.meta.kind) || 'other';
  // 第7轮盲测P5：列表/抽屉组序对齐标签栏的 sortKey 类型序（串口→SSH→日志→
  // 编辑器类→Claude→…），原来跟 connections 插入序导致"Claude 在日志前"不一致
  const _GROUP_ORDER = { serial: 0, ssh: 1, telnet: 1, log: 2, diff: 3, editor: 3,
    hex: 3, bindiff: 3, office: 3, bitcalc: 3, note: 3, claude: 4, harness: 5, proxy: 6 };
  // 用户需求：单例类型（claude/计算器/代理——只会存在一个实例）在抽屉模式下
  // 不收进抽屉，直接平铺显示——收进抽屉要点两次才能到达，没意义。
  // 用户实锤：工具里"Claude"入口开的是 harness kind（Claude 对话），必须一起收
  const _SINGLE_KINDS = new Set(['claude', 'harness', 'bitcalc', 'proxy']);
  // 用户拖过的胶囊组序（位置不变量：拖过的组永远按用户序渲染，新组按默认序附后）
  const _userGroupOrder = [];
  const _groupLabel = k => _GROUP_LABEL[k] || '其他';
  const _groupIcon = k => _GROUP_ICON[k] || ICO16.file;
  // 统一关闭：直接点 tab 自己的 ✕——各模块（terminal=后端断连/editor=脏确认/
  // log/harness/office...）的关闭语义由各自 handler 负责，零重复实现零误判
  const _tabClose = pid => {
    const c = connections[pid];
    const closeEl = c && c.tab && c.tab.querySelector('.close');
    if (closeEl) closeEl.click();
  };
  // 关闭即清 pin（捕获阶段，先于各模块 handler、不 stopPropagation 不影响关闭）：
  // 覆盖 tab ✕ / 右键菜单 / 列表 ✕ 全部路径（都落 .close click）。不清的话串口
  // pid 稳定可重合——关 COM2 后重开同 pid 会被旧 pin 命中，出现"无圆点却不进
  // 抽屉组"的怪状态。取消脏确认时 tab 回来 pin 已摘，代价仅是重新固定一次
  tabsEl.addEventListener('click', e => {
    if (!e.target.classList || !e.target.classList.contains('close')) return;
    const tabEl = e.target.closest('.tab');
    if (!tabEl || !tabEl.dataset.portId) return;
    _pinned.delete(tabEl.dataset.portId);
    tabEl.classList.remove('pinned');
    // 第3轮盲测实锤：关闭后 ⋮ 计数/抽屉胶囊滞留旧值数秒——后台 rAF 节流时
    // MutationObserver 兜底不跑。同步关闭路径（终端类）在下一 tick 同步刷，
    // 计数/胶囊即刻正确；脏确认路径 tab 未删，刷新无害
    setTimeout(() => { checkOverflow(); rebuild(); }, 0);
  }, true);

  // 从 config 恢复模式
  (async () => {
    try {
      const j = await (await fetch('/api/theme')).json();
      if (j.ok && j.tab_mode) _tabMode = j.tab_mode;
    } catch (_) {}
    applyMode();
  })();
  window._tabSetMode = (m) => {
    _tabMode = m;
    try { fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ tab_mode: m })}); } catch (_) {}
    applyMode();
  };
  window._tabGetMode = () => _tabMode;

  // ===== 模式应用 =====
  function applyMode() {
    tabsEl.classList.toggle('drawer-mode', _tabMode === 'drawer');
    rebuild();
  }

  // ===== Pin =====
  window._tabTogglePin = (pid) => {
    if (_pinned.has(pid)) _pinned.delete(pid); else _pinned.add(pid);
    const conn = connections[pid];
    if (conn && conn.tab) {
      conn.tab.classList.toggle('pinned', _pinned.has(pid));
      if (_pinned.has(pid)) {
        // 固定 tab 插入固定区末尾（第4轮盲测：Chrome 习惯是追加到固定组最后，
        // 而非最前——原 firstChild 插法导致"最新固定者排最左"与主流相反）。
        // 第5轮盲测实锤：classList.toggle 先把自身计入 .pinned——不排除自身的话
        // ref=自身.nextSibling，insertBefore(自身,自身.nextSibling)=原地不动
        // （平铺模式 pin 永不移位；抽屉模式"看似最左"只是前面的 tab 全隐藏）
        const pinnedEls = [...tabsEl.querySelectorAll('.tab.pinned')].filter(t => t !== conn.tab);
        const ref = pinnedEls.length
          ? pinnedEls[pinnedEls.length - 1].nextSibling
          : tabsEl.firstChild;
        tabsEl.insertBefore(conn.tab, ref);
      } else {
        // 第2轮盲测实锤：取消固定后停在原地（仍固定 tab 之前）——
        // 破坏"固定区在最左"的排序不变量。移回非固定区：最后一个固定 tab 之后
        const pinnedEls = [...tabsEl.querySelectorAll('.tab.pinned')];
        const ref = pinnedEls.length
          ? pinnedEls[pinnedEls.length - 1].nextSibling
          : tabsEl.firstChild;
        tabsEl.insertBefore(conn.tab, ref);
      }
    }
    // 盲测实锤（高）：pin 是用户的顺序意图，必须像手动拖拽一样让位——
    // 否则 init.js 每 30s 的 refreshSidebar 会按类型桶自动重排，
    // 把固定 tab 从最左排回 sortKey 序（无操作状态下自发重排）
    if (typeof _tabManualOrder === 'function') _tabManualOrder();
    rebuild(true);
    showBanner(_pinned.has(pid) ? '已固定标签页' : '已取消固定', 1500);
  };

  // Tab 右键统一菜单（固定 + 关闭 + 文件类 tab 的快捷对比项）。
  // a286 注：文件 tab 的对比菜单原由 diff-viewer.js 的 #tabs contextmenu 提供，
  // 两边都渲染进 #ctxMenu 会互相覆盖——本 handler 先注册先执行，统一拼菜单
  // 并打 _tabMenuHandled 标记，diff-viewer.js 侧见到标记即让位（功能不丢，只是并进来了）
  // 盲测实锤：抽屉模式下 tab 隐藏，对比入口不可达——列表项也挂同一菜单（_tabCtxMenu 公共化）
  function _tabCtxMenu(x, y, pid) {
    const conn = connections[pid];
    if (!conn) return;
    const lbl = conn && conn.meta ? conn.meta.label || pid : pid;
    const isPinned = _pinned.has(pid);
    if (typeof buildCtxMenu !== 'function') return;
    const items = [];
    // 文件类 tab：并入 diff-viewer 的对比项（状态逻辑复用其全局函数）
    const diffPath = (typeof _diffCtxPathOf === 'function') ? _diffCtxPathOf(pid) : null;
    if (diffPath) {
      const a = (typeof diffPickA === 'function') ? diffPickA() : null;
      const isA = diffPath === a;
      items.push(
        { icon: ICO16.compare, label: '选择以进行对比' + (isA ? '（当前 A）' : ''),
          disabled: isA,
          action: () => { if (typeof diffPickSetA === 'function') diffPickSetA(diffPath); } },
        { icon: ICO16.compare, label: '与选进行对比' + (!a ? '（未选 A）' : ''),
          disabled: !a || isA,
          action: () => { if (typeof diffPickCompare === 'function') diffPickCompare(diffPath); } },
        { sep: true },
      );
    }
    // 盲测实锤：长文件名 slice 硬截断易误导——超长加省略号
    const short = lbl.length > 20 ? lbl.slice(0, 18) + '…' : lbl;
    items.push(
      { icon: ICO16.pin,
        label: isPinned ? '取消固定' : '固定标签页',
        action: () => _tabTogglePin(pid) },
      { sep: true },
      { icon: ICO16.x, label: '关闭「' + short + '」',
        action: () => _tabClose(pid) },
    );
    buildCtxMenu(x, y, items);
  }
  tabsEl.addEventListener('contextmenu', e => {
    const tabEl = e.target.closest('.tab');
    if (!tabEl) return;
    const pid = tabEl.dataset.portId;
    // 未注册 connections 的 tab（如 hex-diff 二进制对比的"计算中"临时 tab）：
    // 关闭/固定对其均无效，弹菜单只会给用户"点了没反应"的假按钮——
    // 直接 return 保持原生右键行为（与 a285 时代一致）
    if (!pid || !connections[pid]) return;
    e.preventDefault();
    e._tabMenuHandled = true;
    _tabCtxMenu(e.clientX, e.clientY, pid);
  });
  // 注：不挂 dblclick 固定——tab 标题双击已被「快捷改名」占用（editor.js），不抢

  // ===== 平铺模式（Chrome）：自动收缩 + ⋮ 溢出 =====
  function checkOverflow() {
    const has = tabsEl.scrollWidth > tabsEl.clientWidth;
    // 第7轮盲测P3：flex 压缩能把 tab 全压到 28px 图标态而不触发 scrollWidth
    // 溢出——无标题无 ✕ 又无 ⋮ 兜底，用户完全无法辨识 tab。tab 压破 50px
    // （标题将不可读）即视为需要 ⋮
    const tight = [...tabsEl.querySelectorAll('.tab')].some(t => {
      const w = t.getBoundingClientRect().width;
      return w > 0 && w < 50;
    });
    const count = Object.keys(connections).filter(k => connections[k] && connections[k].tab).length;
    btn.style.display = has || tight || (_tabMode === 'drawer' && count > 0) ? '' : 'none';
    btn.textContent = '⋮ ' + count;
  }

  // ===== 分组下拉 =====
  function buildList() {
    // 第7轮盲测P7：已无任何 tab 时不再重建列表（防离屏幽灵列表），直接收起
    if (!Object.keys(connections).some(k => connections[k] && connections[k].tab)) {
      close(); checkOverflow(); return;
    }
    if (list) list.remove();
    list = document.createElement('div');
    list.className = 'tab-overflow-list';
    const groups = {};
    const order = [];
    for (const pid in connections) {
      const c = connections[pid];
      if (!c || !c.tab) continue;
      const g = _groupOf(c);
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push({ pid, c });
    }
    order.sort((a, b) => (_GROUP_ORDER[a] ?? 9) - (_GROUP_ORDER[b] ?? 9));
    let html = '';
    order.forEach(g => {
      html += `<div class="tab-overflow-group">${esc(_groupLabel(g))} · ${groups[g].length}</div>`;
      // 第2轮盲测实锤：⋮ 列表与抽屉列表行为对齐——补 📌 固定钮（原来只显
      // 示固定图标不可点，抽屉列表可点，不一致）+ 右键菜单（原来没有）
      html += groups[g].map(({ pid, c }) => {
        const lbl = (c.meta && c.meta.label) || pid;
        const act = pid === activePortId ? ' active' : '';
        const pinCls = _pinned.has(pid) ? ' pinned' : '';
        return `<div class="tab-overflow-item${act}${pinCls}" data-pid="${esc(pid)}">` +
          `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(lbl)}</span>` +
          `<span class="ov-pin" data-pin="${esc(pid)}" title="${_pinned.has(pid) ? '取消固定' : '固定到标签栏'}">${ICO16.pin}</span>` +
          `<span class="ov-close" data-close="${esc(pid)}" title="关闭">✕</span></div>`;
      }).join('');
    });
    list.innerHTML = html;
    document.body.appendChild(list);
    const br = btn.getBoundingClientRect();
    list.style.top = (br.bottom + 4) + 'px';
    list.style.right = Math.max(8, window.innerWidth - br.right) + 'px';
    list.classList.add('show');
    list.querySelectorAll('.tab-overflow-item').forEach(item => {
      // 第2轮盲测实锤：⋮ 列表项右键无反应（抽屉列表有）——挂同一统一菜单。
      // 第3轮盲测：右键时保持列表开着（连续对多项右键不必重开）；点菜单项
      // 后由 document click 兜底收起（操作完成）
      item.oncontextmenu = e => {
        e.preventDefault();
        e.stopPropagation();
        _tabCtxMenu(e.clientX, e.clientY, item.dataset.pid);
      };
      item.onclick = e => {
        const closeEl = e.target.closest('[data-close]');
        if (closeEl) {
          e.stopPropagation();
          _tabClose(closeEl.dataset.close);
          buildList();
          // 盲测实锤：列表里关掉最后一个 tab 后 ⋮ 残留旧计数（"⋮ 1"）——
          // rAF/interval 在后台节流时兜底不可靠，关闭路径同步刷一次
          if (!Object.keys(connections).some(k => connections[k] && connections[k].tab)) {
            close();
            checkOverflow();
          }
          return;
        }
        const pinEl = e.target.closest('[data-pin]');
        if (pinEl) {
          e.stopPropagation();
          _tabTogglePin(pinEl.dataset.pin);
          buildList();
          return;
        }
        switchTab(item.dataset.pid);
        close();
      };
    });
  }
  const close = () => { if (list) { list.remove(); list = null; } };
  btn.onclick = e => { e.stopPropagation(); if (list) close(); else buildList(); };
  // 第9轮缺陷2：冒泡监听被 ✕ handler 的 stopPropagation 拦截 → 改捕获+stop。
  // 第10轮缺陷1/2（高，上轮回归）：捕获监听把 _tabClose 的合成 click（点列表 ✕ →
  // 内部 closeEl.click()，target 在列表外）误判为外部点击——close+stop 拦死了
  // 关闭链（tab 关不掉、列表被关）；同理拦截右键菜单项动作（菜单残留）。
  // 放行两类：isTrusted=false 的程序化点击（内部逻辑链）；ctxMenu 弹开期间的
  // 菜单项点击（菜单交互优先，动作执行后自行收起）
  document.addEventListener('click', e => {
    if (!e.isTrusted) return;
    if (!list || list.contains(e.target) || e.target === btn) return;
    close();
    const m = document.getElementById('ctxMenu');
    if (m && m.style.display === 'block' && m.contains(e.target)) return;
    e.stopPropagation();
  }, true);

  // 从抽屉栏 DOM 读当前胶囊序写回 _userGroupOrder（拖拽换序后调用；rebuild 按此渲染）
  window._ovSyncGroupOrder = _syncGroupOrder;   // tab-drag v2 胶囊换序后同步组序
  function _syncGroupOrder() {
    _userGroupOrder.length = 0;
    document.querySelectorAll('.tab-drawer-bar .tab-drawer').forEach(d =>
      _userGroupOrder.push(d.dataset.group));
  }

  // ===== 抽屉模式渲染 =====
  let drawerBar = null;
  let _lastSig = '';   // 渲染签名：防 MutationObserver 自触发死循环
  function _sig() {
    const parts = [];
    for (const pid in connections) {
      const c = connections[pid];
      if (!c || !c.tab) continue;
      parts.push(pid + ':' + _groupOf(c) + ':' + (_pinned.has(pid) ? 1 : 0));
    }
    return _tabMode + '|' + activePortId + '|' + parts.join(',');
  }
  function rebuild(force) {
    // 先清死 pid：关闭的固定 tab 残留 _pinned（串口 pid 稳定可重合——重开
    // 同名串口会被旧 pin 命中，出现"无圆点却不进抽屉组"的怪状态）
    for (const p of _pinned) if (!connections[p]) _pinned.delete(p);
    const sig = _sig();
    if (!force && sig === _lastSig) return;
    _lastSig = sig;
    // 清旧抽屉。先救出住在栏内的 tab（用户拖进胶囊间的单例）——旧栏 remove
    // 会连带丢弃它们。记录每个 tab 的锚胶囊（其前面最近的组，null=在首个
    // 胶囊前），新栏建成后精确放回同组胶囊之后——用户拖的粒度（哪个胶囊
    // 前/后）跨 rebuild 保真
    let _barResidents = [];
    if (drawerBar) {
      _barResidents = [...drawerBar.querySelectorAll('.tab')].map(t => {
        let g = null, el = t;
        while ((el = el.previousElementSibling)) {
          if (el.classList.contains('tab-drawer')) { g = el.dataset.group; break; }
        }
        return { t, g };
      });
      _barResidents.forEach(({ t }) => tabsEl.insertBefore(t, drawerBar.nextSibling));
      drawerBar.remove(); drawerBar = null;
    }
    // 显示/隐藏原生 tab。只隐藏「已注册 connections」的——hex-diff 的
    // 二进制对比"计算中"临时 tab 不注册 connections（算完自移除），
    // 无条件隐藏会让它在抽屉模式下凭空消失（平铺模式可见，行为退化）
    const isDrawer = _tabMode === 'drawer';
    tabsEl.querySelectorAll('.tab').forEach(t => {
      const pid = t.dataset.portId;
      const known = pid && connections[pid];
      // 单例 kind（claude/计算器/代理）不隐藏——直接平铺，一点即达
      const single = known && _SINGLE_KINDS.has(_groupOf(connections[pid]));
      t.style.display = (isDrawer && known && !single && !_pinned.has(pid)) ? 'none' : '';
    });
    if (!isDrawer) { checkOverflow(); return; }

    // 建抽屉栏
    drawerBar = document.createElement('div');
    drawerBar.className = 'tab-drawer-bar';
    const groups = {};
    const order = [];
    for (const pid in connections) {
      const c = connections[pid];
      if (!c || !c.tab || _pinned.has(pid)) continue;
      const g = _groupOf(c);
      if (_SINGLE_KINDS.has(g)) continue;   // 单例不进抽屉（平铺直达）
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(pid);
    }
    // 用户拖过的组按 _userGroupOrder 排（位置不变量），未拖过的新组按默认类型序附后
    order.sort((a, b) => {
      const ia = _userGroupOrder.indexOf(a), ib = _userGroupOrder.indexOf(b);
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return (_GROUP_ORDER[a] ?? 9) - (_GROUP_ORDER[b] ?? 9);
    });
    order.forEach(g => {
      const pids = groups[g];
      const active = pids.find(p => p === activePortId);
      const activeLbl = active && connections[active] && connections[active].meta ?
        connections[active].meta.label || '' : '';
      const btn = document.createElement('div');
      btn.className = 'tab-drawer' + (active ? ' active' : '');
      btn.dataset.group = g;
      // 第7轮盲测P2：title 只挂 active span 时，窄视口让位态 span 宽 0——悬停
      // 胶囊任何位置都无 tooltip。挂胶囊整体：有活跃名显名，无则显组名
      // 第9轮盲测缺陷5（低）：title 只有活跃名——窄形态只剩 title 时丢类型/数量
      // 信息。改为完整语义：类型名 · N 个 · 活跃：xxx
      btn.title = _groupLabel(g) + ' · ' + pids.length + ' 个' + (activeLbl ? ' · 活跃：' + activeLbl : '');
      btn.innerHTML =
        `<span class="tab-drawer-icon">${_groupIcon(g)}</span>` +
        `<span class="tab-drawer-label">${esc(_groupLabel(g))}</span>` +
        `<span class="tab-drawer-count">${pids.length}</span>` +
        // 第4轮盲测：活跃名不用 JS slice 硬砍（"root@10.0.0."即 12 字符截断产物，
        // 无省略号）——完整交给 CSS（max-width:130px + ellipsis），title 悬浮看全名
        (activeLbl ? `<span class="tab-drawer-active" title="${esc(activeLbl)}">${esc(activeLbl)}</span>` : '');
      // 点击 → 分组下拉
      btn.onclick = e => {
        e.stopPropagation();
        buildGroupList(g, pids, btn);
      };
      // 拖拽已并入 tab-drag v2 容器级（吸附+指示线+胶囊换序+tab 落胶囊前后
      // +固定区挡板），此处仅预置 draggable（发起拖拽的前提）
      btn.draggable = true;
      drawerBar.appendChild(btn);
    });
    // 插到右缘 sticky 区（tab-bar-actions/⋮）之前——与所有 tab 的插入位一致
    const anchor = tabsEl.querySelector('.tab-bar-actions') || btn;
    tabsEl.insertBefore(drawerBar, anchor);
    // 栏内居民放回：锚组胶囊之后（组已消失的放栏后）——精确还原用户放置
    _barResidents.forEach(({ t, g }) => {
      if (!t.isConnected) return;   // 居民已被关掉
      const cap = g !== null
        ? drawerBar.querySelector('.tab-drawer[data-group="' + CSS.escape(g) + '"]')
        : drawerBar.querySelector('.tab-drawer');   // 原"首个胶囊前"→新首个胶囊前
      if (cap) drawerBar.insertBefore(t, g !== null ? cap.nextSibling : cap);
      else tabsEl.insertBefore(t, drawerBar.nextSibling);
    });
    // 单例 tab 保证在抽屉栏之前（视觉序：固定区 → 单例平铺 → 抽屉）。
    // 用户实锤：原判断 nextSibling !== drawerBar 要求单例「紧贴」抽屉栏——
    // 每次切换 tab 的 rebuild 都把拖拽过的单例按打开序强制归位（claude 拖到
    // 第三位，切个 tab 就跳回第一）。改为只判断「是否在抽屉栏之前」：
    // 在前就不动（用户拖拽序保留），仅落在栏后的（新开的）才挪到栏前
    for (const pid in connections) {
      const c = connections[pid];
      if (!c || !c.tab || _pinned.has(pid) || !_SINGLE_KINDS.has(_groupOf(c))) continue;
      if (c.tab.dataset.userPlaced) continue;   // 用户手动放过的（拖到胶囊前后）不动
      // 在位 = 在抽屉栏之前 或 在抽屉栏内部（用户拖进栏内的不许被 rebuild 拽出；
      // compareDocumentPosition 对祖先返回 PRECEDING|CONTAINS 而非 FOLLOWING，需先判 contains）
      const insideBar = drawerBar.contains(c.tab);
      const alreadyBefore = insideBar ||
        (c.tab.compareDocumentPosition(drawerBar) & Node.DOCUMENT_POSITION_FOLLOWING);
      if (!alreadyBefore) tabsEl.insertBefore(c.tab, drawerBar);
    }
    checkOverflow();
  }

  // 分组下拉（点抽屉弹出该组的 tab 列表）
  // 注：所有关闭路径统一走 _groupCloseList，保证 document 监听必摘除
  // （旧写法 null 判定后监听永不自摘，开 N 次漏 N 个）
  let groupList = null, _groupDocClose = null;
  function _groupCloseList() {
    if (groupList) { groupList.remove(); groupList = null; }
    if (_groupDocClose) { document.removeEventListener('click', _groupDocClose); _groupDocClose = null; }
  }
  function _groupRenderItems(group, anchorEl) {
    // 锚点防脱离：✕/📌 分支里 _tabClose→switchTab→rebuild 或 _tabTogglePin→rebuild(true)
    // 都会重建 drawerBar，旧抽屉按钮随即脱离 DOM——此时 getBoundingClientRect()
    // 返回全 0，列表会闪跳到屏幕左上角。脱离即关列表（与 MutationObserver 兜底一致）
    if (!anchorEl || !anchorEl.isConnected) { _groupCloseList(); return; }
    const pids = Object.keys(connections).filter(p => {
      const c = connections[p];
      return c && c.tab && !_pinned.has(p) && _groupOf(c) === group;
    });
    if (!pids.length) { _groupCloseList(); return; }
    groupList.dataset.group = group;
    groupList.innerHTML = `<div class="tab-overflow-group">${esc(_groupLabel(group))} · ${pids.length}</div>` +
      pids.map(pid => {
        const c = connections[pid];
        const lbl = (c && c.meta && c.meta.label) || pid;
        const act = pid === activePortId ? ' active' : '';
        const pin = _pinned.has(pid) ? ' pinned' : '';
        return `<div class="tab-overflow-item${act}${pin}" data-pid="${esc(pid)}">` +
          `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(lbl)}</span>` +
          `<span class="ov-pin" data-pin="${esc(pid)}" title="${_pinned.has(pid) ? '取消固定' : '固定到标签栏'}">${ICO16.pin}</span>` +
          `<span class="ov-close" data-close="${esc(pid)}" title="关闭">✕</span></div>`;
      }).join('');
    const br = anchorEl.getBoundingClientRect();
    groupList.style.top = (br.bottom + 4) + 'px';
    groupList.style.left = Math.max(4, Math.min(br.left, window.innerWidth - 260)) + 'px';
    groupList.querySelectorAll('.tab-overflow-item').forEach(item => {
      // 盲测实锤：抽屉模式下 tab 全隐藏，文件类 tab 的对比入口不可达——
      // 列表项右键挂同一统一菜单（tab 上右键的完整等价物）。
      // 第3轮盲测：右键时保持列表开着（与 ⋮ 列表一致）；点菜单项后由
      // _groupDocClose 兜底收起
      item.oncontextmenu = e => {
        e.preventDefault();
        e.stopPropagation();
        _tabCtxMenu(e.clientX, e.clientY, item.dataset.pid);
      };
      item.onclick = e => {
        const closeEl = e.target.closest('[data-close]');
        if (closeEl) {
          e.stopPropagation();
          _tabClose(closeEl.dataset.close);
          // 异步关闭（脏确认）后 MutationObserver 兜底刷新；先同步刷一次
          const g = groupList ? groupList.dataset.group : null;
          const anc = anchorEl;
          if (g) _groupRenderItems(g, anc);
          rebuild();
          return;
        }
        const pinEl = e.target.closest('[data-pin]');
        if (pinEl) {
          e.stopPropagation();
          const g = groupList ? groupList.dataset.group : null;
          const anc = anchorEl;
          _tabTogglePin(pinEl.dataset.pin);
          // 固定后该 pid 移出本组：组空则关列表，否则重渲（锚点仍是原抽屉）
          if (groupList && g) _groupRenderItems(g, anc);
          return;
        }
        switchTab(item.dataset.pid);
        _groupCloseList();
      };
    });
  }
  function buildGroupList(group, pids, anchorEl) {
    if (groupList && groupList.dataset.group === group) { _groupCloseList(); return; }
    _groupCloseList();
    groupList = document.createElement('div');
    groupList.className = 'tab-overflow-list show';
    document.body.appendChild(groupList);
    _groupRenderItems(group, anchorEl);
    // 第9轮缺陷2 同锤 + 第10轮缺陷1/2 同修：合成点击与菜单交互放行（见上方 ⋮ 列表监听注释）
    _groupDocClose = e => {
      if (!e.isTrusted) return;
      if (!groupList || groupList.contains(e.target)) return;
      _groupCloseList();
      const m = document.getElementById('ctxMenu');
      if (m && m.style.display === 'block' && m.contains(e.target)) return;
      e.stopPropagation();
    };
    setTimeout(() => document.addEventListener('click', _groupDocClose, true), 0);
  }

  // switchTab 时更新抽屉显示（由 terminal-core.js 调用）
  window._tabDrawerUpdate = () => rebuild();

  // 连接增删时重渲染 + 刷新打开中的下拉（脏确认等异步关闭后列表不残留）
  new MutationObserver(() => requestAnimationFrame(() => {
    rebuild();
    if (list) buildList();
    if (groupList) {
      // 抽屉本体已重建，锚点失效——直接关（用户重开一次即可，避免悬浮错位）
      _groupCloseList();
    }
  })).observe(tabsEl, { childList: true });
  // 第9轮盲测缺陷1（高）：1280→400 直达时 resize 瞬间 checkOverflow 读到侧栏
  // transition（width .3s）中间态算错 has/tight → ⋮ 误隐藏；2s interval 虽会
  // 兜底但前台有 2s 空窗（盲测环境 interval 被宿主节流则"持续丢失"）。
  // resize 后 400ms（transition 完成）补一脚同步真值
  window.addEventListener('resize', () => { checkOverflow(); setTimeout(checkOverflow, 400); });
  // 第9轮盲测缺陷4（低）：Esc 能关右键菜单却关不掉 ⋮/抽屉列表——行为统一
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { if (list) close(); if (groupList) _groupCloseList(); }
  });
  setInterval(checkOverflow, 2000);
  checkOverflow();
})();
let aiSse = null;

// banner 已改右下角悬浮冒泡，不占布局空间，无需再重 fit 终端。
// （保留函数引用兼容旧调用点。）
function refitAllTerms() {}

// ============================================================
// 通知栈（v1.1.2）：右下角向上堆叠的多条冒泡，支持并发长任务各自一条。
// 旧 showBanner(msg,ms,isErr) 是单例 DOM，多个并发操作互相覆盖——多个 SSH
// 同时快捷打开时只剩最后一条。任务型 API：
//   const nid = notifyTask({icon, title, detail})      → 进行中（转圈）
//   notifyTaskDone(nid, {ok, title, detail, ms})       → ✓/✗ 后自动消失
//   notifyPop(msg, ms, isErr)                          → 普通一次性冒泡（等价旧 showBanner）
// 样式见 style.css .notify-* 区块；栈容器 #notifyStack 动态创建不占布局。
// ============================================================
function _notifyStack() {
  let el = document.getElementById('notifyStack');
  if (!el) {
    el = document.createElement('div');
    el.id = 'notifyStack';
    document.body.appendChild(el);
  }
  return el;
}
// claude 用自绘星形图标（.claude-ico 内联 SVG，与顶栏按钮/tab 同款），不用 emoji——
// emoji 在不同系统字体下渲染不一致（Win10 是黑白轮廓），自绘 SVG 才能保品牌色 D97757。
const _NOTIFY_ICON = { ssh: ICO16.link, serial: ICO16.plug, telnet: ICO16.monitor, file: ICO16.file, diff: ICO16.compare, hex: ICO16.hex, log: ICO16.log, claude: '<span class="claude-ico"></span>', generic: ICO16.gear };

function _notifyBuild(o) {
  const d = document.createElement('div');
  d.className = 'notify' + (o.isErr ? ' err' : '');
  const icon = o.icon || _NOTIFY_ICON[o.type] || _NOTIFY_ICON.generic;
  d.innerHTML = `
    <span class="n-ico">${icon}</span>
    <div class="n-body">
      <div class="n-title">${esc(o.title || '')}</div>
      ${o.detail ? `<div class="n-detail">${esc(o.detail)}</div>` : ''}
    </div>
    <span class="n-state"></span>
    <span class="n-close" title="关闭">✕</span>
  `;
  return d;
}
function _notifyMount(d, ms) {
  const stack = _notifyStack();
  // 栈封顶 6 条：超出丢最旧（FIFO）——连环点 20 个快捷打开时不能让转圈
  // 通知盖满半屏（铁律①流畅/可用性）。被丢的条若是常驻任务(无 timer)，
  // 后续 notifyTaskDone 会静默 no-op（DOM 已 remove，_closed 检查兜住）
  // a231 审计 P0：原 while 靠 _notifyDismiss 的 200ms 异步 remove 减计数——
  // 同步循环里定时器不派发、live HTMLCollection 长度不变 → 无限循环整页冻结
  // （第 5 条并发通知必触发）。同步摘除；DOM 首位才是最旧（column-reverse
  // 只反转视觉不反转 DOM 序——旧注释判错，原代码丢的是最新通知）
  while (stack.children.length >= 4) {
    stack.children[0].remove();
  }
  stack.appendChild(d);
  // 入场动画（CSS .notify 定义）后自动消失（ms=0 常驻，由任务完成时关闭）
  if (ms) {
    d._timer = setTimeout(() => _notifyDismiss(d), ms);
  }
  return d;
}
function _notifyDismiss(d) {
  if (d._timer) { clearTimeout(d._timer); d._timer = null; }
  if (d._closed) return;
  d._closed = true;
  d.classList.add('out');
  setTimeout(() => d.remove(), 200);   // 等 slide-out 动画
}

// 任务型：发起（进行中，转圈）→ 返回 nid
function notifyTask({type, icon, title, detail}) {
  const d = _notifyBuild({icon, type, title, detail});
  d.querySelector('.n-state').innerHTML = '<span class="n-spin"></span>';
  d.querySelector('.n-close').onclick = () => _notifyDismiss(d);
  d.onclick = (e) => { if (!e.target.closest('.n-close')) _notifyDismiss(d); };   // a233 P2: 点体即关（a226 漏任务型）
  _notifyMount(d, 0);   // 常驻直到 done
  return d;
}
// 任务型：结束（ok=true ✓ 绿 / false ✗ 红），改状态后自动消失
function notifyTaskDone(nid, {ok, title, detail, ms=5000}) {
  const d = nid;
  if (!d || d._closed) return;
  if (title) d.querySelector('.n-title').textContent = title;
  if (detail !== undefined) {
    const det = d.querySelector('.n-detail');
    if (detail) { if (!det) { const nd = document.createElement('div'); nd.className = 'n-detail'; nd.textContent = detail; d.querySelector('.n-body').appendChild(nd); } else det.textContent = detail; }
    else if (det) det.remove();
  }
  const st = d.querySelector('.n-state');
  st.innerHTML = ok ? '✓' : '✗';
  d.classList.toggle('err', !ok);
  d._timer = setTimeout(() => _notifyDismiss(d), ok ? Math.min(ms, 4000) : ms);
}

// 一次性冒泡（旧 showBanner 等价，但走堆叠栈不覆盖其他通知）
function notifyPop(msg, ms=4000, isErr=false, type) {
  // v3.2.20（用户实锤同文案提示连刷 7~8 条）：同文去重——栈内在场的相同
  // 文案+相同级别不再重复弹，仅重置其驻留计时（重要信息不被刷屏淹没）
  try {
    const dup = [..._notifyStack().children].find(n =>
      !n._closed && n.classList.contains('err') === !!isErr &&
      (n.querySelector('.n-title') || {}).textContent === String(msg));
    if (dup) {
      if (dup._timer) clearTimeout(dup._timer);
      dup._timer = setTimeout(() => _notifyDismiss(dup), ms || 4000);
      return dup;
    }
  } catch(_) {}
  const d = _notifyBuild({title: msg, isErr, type});
  d.querySelector('.n-state').innerHTML = isErr ? '✗' : '✓';
  d.querySelector('.n-close').onclick = () => _notifyDismiss(d);
  // a226（用户实锤「ⓘ 连点卡死、通知不消失、点哪都没反应」）：通知体
  // 点击即关——12s 常驻通知墙曾盖住右下功能区且只有小 ✕ 可点，误以为
  // 工具死锁；现在点通知任意处即消失
  d.onclick = (e) => { if (!e.target.closest('.n-close')) _notifyDismiss(d); };
  _notifyMount(d, ms || 4000);
  return d;
}

// 旧 API 兼容层：全部转发到通知栈（153 个既有调用点不动）
function showBanner(msg, ms=4000, isErr=false) {
  notifyPop(msg, ms, isErr);
}

// ---- 工具面板渐隐滚动条（用户需求：常显小丑→悬浮工作区渐显）------------
// 通用自绘：原生滚动条视觉已由 CSS 隐藏（Fluent 绘制层宽度不可控+伪元素
// 不吃 transition,渐隐只能自绘 DOM 才能做）。面板需 position:relative
// （CSS 已给六容器配好）。内容不溢出自动隐藏；拖拽锁 sb-drag 防拖出面板
// 时条闪没；400ms 周期兜底（列表增删不触发 scroll 事件）。返回清理函数
const _HG_FADE_SB_VER = 6;   // 挂载实例版本：行为变更时递增——旧实例自动拆重建
function _hgFadeSb(el) {
  if (el && el._hgFadeSb && el._hgFadeSb.ver !== _HG_FADE_SB_VER) {
    // 旧版本实例在位（页面 JS 缓存半新半旧的第三层：函数实例本身——服务端
    // 文件再新,页面内存里跑的还是旧函数,旧实例占位新挂载永不重入,用户实锤
    // 「修了效果一样」）。拆旧建新,行为变更递增版本号即生效
    clearInterval(el._hgFadeSb.timer);
    if (el._hgFadeSb.sb) el._hgFadeSb.sb.remove();
    delete el._hgFadeSb;
  }
  if (!el || el._hgFadeSb) return () => {};
  el.classList.add('hg-fade-sb-host');   // v5：CSS 通配标记（隐藏原生条）
  // v4 结构修正（用户实锤「条随内容滚出去/消失」）：absolute 子元素放在
  // 滚动容器**内部**会随内容一起被滚走（CSS 经典坑；终端条无此问题是挂
  // 在不滚的 .xterm-wrap 上）。改为挂「非滚动的父级锚点」，按宿主 rect
  // 动态定位——锚点不滚,条稳定悬浮。显隐改 JS mouseenter/leave 挂
  // sb-drag 类（借既有显形规则,不依赖新 CSS 到达）
  const anchor = el.parentElement || el;
  if (anchor === el) return () => {};   // 无父级（不该发生）放弃托管
  if (getComputedStyle(anchor).position === 'static') anchor.style.position = 'relative';
  el._hgFadeSb = { ver: _HG_FADE_SB_VER };
  const sb = document.createElement('div');
  sb.className = 'hg-fade-sb';
  const th = document.createElement('div');
  th.className = 'hg-fade-sb-th';
  sb.appendChild(th);
  anchor.appendChild(sb);
  // 自愈：宿主 innerHTML 整体重写不影响（条在锚点上不在宿主里），锚点
  // innerHTML 重写时重插
  const ensureInDom = () => {
    if (sb.parentNode !== anchor) anchor.appendChild(sb);
  };
  let dragging = false;   // 拖拽期间宿主 mouseleave 不收条
  const paint = () => {
    if (!el.isConnected || !anchor.isConnected) return;
    ensureInDom();
    const sh = el.scrollHeight, ch = el.clientHeight;
    if (sh <= ch + 4) { sb.style.display = 'none'; return; }
    sb.style.display = '';
    // 条相对锚点定位：宿主可视区映射（每拍校准,布局变化自适应）
    const er = el.getBoundingClientRect(), ar = anchor.getBoundingClientRect();
    const top = Math.max(0, er.top - ar.top + 4);
    const trackH = Math.max(40, er.height - 8);
    sb.style.top = top + 'px';
    sb.style.bottom = 'auto';
    sb.style.height = trackH + 'px';
    const thH = Math.max(32, Math.round(ch / sh * trackH));
    const maxTop = trackH - thH;
    th.style.height = thH + 'px';
    th.style.top = (maxTop > 0 ? el.scrollTop / (sh - ch) * maxTop : 0) + 'px';
  };
  sb.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const trackH = sb.clientHeight, thH = th.offsetHeight;
    const maxTop = trackH - thH;
    if (e.target === th) {
      dragging = true;
      sb.classList.add('sb-drag');
      const startY = e.clientY, startScroll = el.scrollTop;
      const move = (ev) => {
        if (maxTop <= 0) return;
        el.scrollTop = startScroll +
          (ev.clientY - startY) / maxTop * (el.scrollHeight - el.clientHeight);
      };
      const up = () => {
        dragging = false;
        if (!hovering) sb.classList.remove('sb-drag');
        removeEventListener('mousemove', move);
        removeEventListener('mouseup', up);
      };
      addEventListener('mousemove', move);
      addEventListener('mouseup', up);
    } else {
      const y = e.clientY - sb.getBoundingClientRect().top;
      const cur = parseFloat(th.style.top) || 0;
      el.scrollTop += (y < cur ? -1 : 1) * el.clientHeight * 0.9;
    }
  });
  let hovering = false;
  el.addEventListener('mouseenter', () => { hovering = true; sb.classList.add('sb-drag'); paint(); });
  el.addEventListener('mouseleave', () => {
    hovering = false;
    if (!dragging) sb.classList.remove('sb-drag');
  });
  el.addEventListener('scroll', paint, { passive: true });
  // v6 性能事故复盘（trace 实锤 44500 次 paint/145s）：每容器独立 400ms
  // interval 废除——改由全局单 600ms 循环统一刷（托管 IIFE）+scroll 即时
  paint();
  Object.assign(el._hgFadeSb, { sb, paint, anchor });   // ver 已在开头写入
  return () => { sb.remove(); delete el._hgFadeSb; };
}

// ---- 渐隐滚动条全局托管（用户拍板全站统一）--------------------------------
// 性能事故复盘（用户 trace 铁证：145s 窗 Layout 100.9s/1 万次,scanAll 单次
// 18.5s×5 + paint 44500 次——主动扫描三宗罪：全 DOM getComputedStyle、每
// 容器独立 interval、observer 增量逐节点样式读）→ 惰性事件驱动。
// v7 补启动粗条闪变（用户截图实锤：启动时原生粗条可见,悬浮才换细条——
// 惰性挂载的固有窗口期）：scroll/capture 委托零成本发现溢出容器——任何
// 容器「滚动或内容增删引发 scroll 信号」即被捕获挂条,启动即接管,粗条
// 窗口只在「从未滚动且鼠标未到」的面板残留（此时它也无从被看见,无感）。
// pointerover 保留兜底（纯 hover 未滚场景）。
(function () {
  const EXCLUDE = '.xterm-viewport, .hg-fade-sb, .hg-fade-sb-th, .hg-term-sb';
  const _hosts = new Set();
  const tryMount = (n) => {
    if (!n || n.nodeType !== 1 || n._hgFadeSb) return false;
    if (n.matches && n.matches(EXCLUDE)) return false;
    let oy;
    try { oy = getComputedStyle(n).overflowY; } catch (_) { return false; }
    if (oy !== 'auto' && oy !== 'scroll') return false;
    _hgFadeSb(n);
    if (n._hgFadeSb) { _hosts.add(n); return true; }
    return false;
  };
  // 滚动捕获委托：滚动事件沿捕获相位从 document 顶下来,第一个命中目标
  // 即溢出容器本身——零遍历成本,启动后任何滚动信号都即时接管
  document.addEventListener('scroll', (e) => {
    tryMount(e.target);
  }, { capture: true, passive: true });
  // 静态区填充捕获（启动粗条窗口的第二路径）：目录文件/最近列表是启动期
  // innerHTML 填充——只涨 scrollHeight 不发 scroll 事件。轻量 observer 只盯
  // 侧栏子树（低频区,终端热区不observe）;查询范围=侧栏内（O(数百)）——
  // 对抗审修正:曾误写 document.querySelectorAll 全局扫（O(全文档)×每秒）
  const _bootMo = new MutationObserver(() => {
    const side = document.querySelector('.sidebar');
    if (!side) return;
    side.querySelectorAll('.tftp-list, .tftp-transfers, .tftp-files, .recent-list, .port-list, .tree-roots')
      .forEach(tryMount);
  });
  const _bootArm = () => {
    const side = document.querySelector('.sidebar');
    if (side) _bootMo.observe(side, { childList: true, subtree: true });
    else setTimeout(_bootArm, 500);
  };
  _bootArm();
  // hover 兜底（未滚动纯悬浮场景）
  document.addEventListener('pointerover', (e) => {
    let n = e.target;
    while (n && n !== document.body && n.nodeType === 1) {
      if (n._hgFadeSb) return;
      if (tryMount(n)) return;
      n = n.parentElement;
    }
  }, { passive: true });
  // 全局单循环统一 paint 已挂载容器（断连自动出册）
  setInterval(() => {
    for (const el of _hosts) {
      if (!el.isConnected || !el._hgFadeSb || !el._hgFadeSb.paint) {
        // a237 P3：出册同时摘自绘条本体——宿主被单独 remove（而非父层
        // innerHTML 重建）时，条以内联样式残留在 anchor 上成幽灵可见
        if (el._hgFadeSb && el._hgFadeSb.sb) { try { el._hgFadeSb.sb.remove(); } catch (_) {} }
        _hosts.delete(el);
        continue;
      }
      try { el._hgFadeSb.paint(); } catch (_) {}
    }
  }, 600);
})();
function fmtTs(ms) {
  const d = new Date(ms);
  return d.toLocaleTimeString('zh-CN', {hour12:false}) + '.' + String(ms % 1000).padStart(3,'0');
}
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

// v3.5.109（designer 方案 O1）：写操作统一包装——义务化响应校验，替代各
// 调用点裸 .catch(()=>{})（order 400 静默 3 年的教训：写操作不看响应码，
// 失败无声丢失）。非 2xx 也尝试解析 JSON；j.ok 不真/解析失败/网络错一律
// 失败路径并 banner（label 前缀调用方定文案）。返回 {ok, j} 供调用方做
// 回滚/后续逻辑；成功静默不弹（调用方需要成功提示的自己发）。
async function apiPost(path, body, opt) {
  opt = opt || {};
  try {
    const r = await fetch(path, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}) });
    let j = null;
    try { j = await r.json(); } catch (_) {}          // 5xx HTML 错误页等
    if (!j || !j.ok) {
      const why = (j && j.err) ? ('：' + j.err) : ('（HTTP ' + r.status + '）');
      showBanner((opt.label || '操作失败') + why, 4000, true);
      return { ok: false, j };
    }
    return { ok: true, j };
  } catch (e) {
    showBanner((opt.label || '操作失败') + '：网络或服务错误', 4000, true);
    return { ok: false, j: null };
  }
}
// 连接排序：串口[0] < SSH[1] < 日志[2] < 编辑器[3] < claude[4]，同类内按自然序
function sortKeyFn(pid) {
  const m = /^COM(\d+)$/i.exec(pid);
  if (m) return [0, parseInt(m[1], 10)];  // 串口：COM 号数字序
  if (pid.startsWith('log:')) return [2, pid];  // 日志：字典序
  if (pid.startsWith('diff:')) return [3, 'd' + pid];  // 对比：编辑器组，字典序排最前（log/编辑器都是数字段后缀）
  if (pid.startsWith('edit:')) return [3, pid];  // 编辑器：字典序（排在日志后）
  if (pid.startsWith('claude:')) return [4, pid];  // claude 终端：字典序（排在编辑器后）
  if (pid.startsWith('harness:')) return [5, pid];  // claude harness 对话：字典序（排在 claude 终端后）
  // 第8轮盲测缺陷2：bitcalc/proxy 原落默认桶（SSH 前）与 ⋮ 列表组序
  // （编辑器类/代理）矛盾——补齐桶位对齐 _GROUP_ORDER
  if (pid.startsWith('bitcalc:')) return [3, pid];  // 计算器：编辑器类桶
  if (pid.startsWith('proxy:')) return [6, pid];    // 代理面板：最后
  return [1, pid];  // SSH：字典序
}

// ============================================================
// 关键字高亮（error/warning/info 等）
// v0.3.0：改用 xterm decoration 实现（见下方 highlightNewKw），
// 旧的 DOM textNode 高亮函数 highlightKeywords 已废弃移除。
// ============================================================
// （KW_RULES / KW_COLOR 已移至下方 xterm decoration 区块统一定义）

// ============================================================
// 终端标签页 & 输出区管理
// ============================================================
// 注：实际终端元素由 buildTerminal() 创建，此处不再保留死代码。

// 重新设计：每个连接有自己的 xterm 终端容器

// ============================================================
// v3.5.310 可配置快捷键（设置页录制式）：文档内搜索（原 Ctrl+F）/ 全库
// 笔记搜索（原 Ctrl+Alt+F）。_HK 由启动 GET /api/theme 填充，设置页改键
// 后热更新 window._HK。
// hkMatch(e, combo, loose)：loose=true（文档内搜索——原 sidebar/editor 条件
// 不排 Shift/Alt，宽松保持）；loose 缺省=严格（三修饰键精确匹配，全库搜索
// 原语义）。轻审 F2：strict 语义不可放宽到 docSearch，否则 ctrl+f 吞掉
// ctrl+alt+f。
// ============================================================
function hkMatch(e, combo, loose) {
  if (!combo) return false;
  const parts = String(combo).toLowerCase().split('+').filter(Boolean);
  if (!parts.length) return false;
  const key = parts[parts.length - 1];
  if ((e.key || '').toLowerCase() !== key) return false;
  // 纵深防御（复审 R2）：直连 POST 塞 'win+f' 类脏配置时，未知修饰段使按键
  // 永不命中——比「退化成裸键触发」安全（UI 录制器产不出此类值）
  if (parts.slice(0, -1).some(mm => !['ctrl', 'alt', 'shift'].includes(mm))) return false;
  const chk = (want, got) => (loose ? (!want || got) : want === got);
  if (!chk(parts.includes('ctrl'), !!e.ctrlKey)) return false;
  if (!chk(parts.includes('alt'), !!e.altKey)) return false;
  if (!chk(parts.includes('shift'), !!e.shiftKey)) return false;
  return true;
}
window._HK = { docSearch: 'ctrl+f', notesSearch: 'ctrl+alt+f' };
(function () {
  fetch('/api/theme').then(r => r.json()).then(j => {
    if (!j || !j.ok) return;
    if (typeof j.doc_search_hotkey === 'string' && j.doc_search_hotkey)
      window._HK.docSearch = j.doc_search_hotkey;
    if (typeof j.notes_search_hotkey === 'string' && j.notes_search_hotkey)
      window._HK.notesSearch = j.notes_search_hotkey;
  }).catch(() => {});
})();
