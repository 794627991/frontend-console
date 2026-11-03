// ============================================================
// 只读模式 v2（v3.5.50 彻底重修，v3.5.51 按 designer 方案落地）
// 与主窗口完全同款：主渲染管线（_histRender）+ 同款交互委托
// （_hgFlowClick/_hgFlowClick2 经 enter deps 传入——两函数在
// buildClaudeHarnessTab 闭包内，跨脚本按名不可达，designer B1）+
// 子代理段/分屏同状态 + 回合导航轨。
// 差异只有：无左侧会话栏、无输入框、flow 限宽居中留白、顶部横条
// （退出 / 会话列表抽屉——含主窗口 20 条外的过往会话）。
//
// 机制（稳定优先，designer 方案定稿）：
// 进入 = _HG.readonly=sid + roViewSid → 断 v4 投影 store（V4Main.close，
//   防 delta 画进 RO 视图）→ _hgFlow 指向 RO 容器 → 隐藏 side/flowwrap/
//   card-wrap → fetch transcript 走 _histRender 渲染。
// 退出 = 清 readonly/roViewSid → rail 归位 → _hgFlow 指回主 flow →
//   V4Main.switch(anchor) 投影快照整窗重建（旧 _hgSseRebuild+openSSE
//   断点续传已随批G 退役）。
// 跨会话跳转（抽屉点其他会话）= RO_view：同场重渲（不回主视图）。
// 变更类操作（回滚/重发/编辑重发）在主层 handler 内被 readonly 守卫拦截。
// ============================================================
'use strict';

let _ro = null;   // {sid, gen, root, drawer, drawerList, fw, flow, rail, busyTimer, fc, fc2, snapPeerSent}

function RO_active() { return !!_HG.readonly; }

function RO_enter(sid, deps) {
  if (!sid || _HG.readonly) return;
  const fc = (deps && deps.fc) || null;
  const fc2 = (deps && deps.fc2) || null;
  if (!fc || !fc2) return;   // 交互委托缺失=只读层不可交互，拒绝进入
  const meta = (_HG.sessions || []).find(x => x.sid === sid) || {};
  _HG.readonly = sid;
  _HG.roViewSid = sid;
  // v3.5.53（复核问题1 修复配套）：anchorSid=进入只读时的主会话——退出
  // rebuild 判定用锚（浏览过多档会话后 readonly 已非锚值，不能拿它判定）
  _ro = { sid, anchorSid: sid, gen: 1, dgen: 1, fc, fc2, snapPeerSent: _HG.peerSent };
  // （旧主 SSE 断连块已随批G 退役——v4 下 _HG.sse 恒 null，看门狗亦不存）
  // v4：投影 store 同步断开（否则 delta 持续画进 RO 视图）；RO_exit 由
  // V4Main.switch 重建
  try { V4Main.close(); } catch (_) {}
  if (typeof _hgPeerWaitStop === 'function') _hgPeerWaitStop();
  if (typeof actStop === 'function') actStop();
  // 隐藏主视图三件：左栏 / flowwrap（flow+rail+jumpbtm+capsule）/ 输入区
  const side = document.querySelector('.hg-side');
  const flowwrap = document.querySelector('.hg-flowwrap');
  const cardwrap = document.querySelector('.hg-card-wrap');
  const rail = flowwrap && flowwrap.querySelector('[data-hg-rail]');
  if (side) side.style.display = 'none';
  if (flowwrap) flowwrap.style.display = 'none';
  if (cardwrap) cardwrap.style.display = 'none';
  // RO 期间分屏保持可见（子代理目录/回放窗格在 RO 里照常使用）
  const subpane = document.querySelector('[data-hg-subpane]');
  const subOrigDisplay = subpane ? subpane.style.display : '';
  if (subpane) subpane.style.display = 'flex';
  // v3.5.75（用户拍板「和主窗保持一致,左右间隔一定间距即可」）：flow 占满
  // RO 区（导轨贴左缘/滚动条贴右缘），内容列靠左 820 列+flow 自带 padding
  // 20/32 固定间距——v3.5.65-74 的居中/中线偏移尝试全部退役，零计算
  // RO DOM（插在 flowwrap 同层前；分屏 .hg-subpane 保持原位=自动让位）
  const root = document.createElement('div');
  root.className = 'hg-ro';
  root.innerHTML =
    '<div class="hg-ro-bar">' +
      '<button class="hg-ro-btn" data-ro-list title="全部会话列表（含主窗口外的过往会话）">☰ 会话</button>' +
      '<b class="hg-ro-title"><span style="vertical-align:-2.5px">' + ICO16.book + '</span> 只读模式 · ' + esc(meta.title || sid.slice(-6)) + '</b>' +
      '<span class="hg-ro-hint">只看历史 · 后台照常运行 · 点子代理行开分屏回放</span>' +
      '<button class="hg-ro-btn hg-ro-exit" data-ro-exit title="退出只读，回到正常会话（自动补齐后台期间的消息）">✕ 退出只读</button>' +
    '</div>' +
    '<div class="hg-ro-body">' +
      '<div class="hg-ro-drawer" data-ro-drawer style="display:none">' +
        '<div class="hg-ro-drawer-head">全部会话（点击切换查看）</div>' +
        '<div data-ro-dlist class="hg-ro-dlist"></div>' +
      '</div>' +
      '<div class="hg-rov-wrap">' +
        '<div class="hg-rov-fw">' +
          '<div class="hg-flow" data-ro-flow></div>' +
        '</div>' +
      '</div>' +
    '</div>';
  const host = flowwrap ? flowwrap.parentElement : document.querySelector('.hg');
  if (flowwrap) host.insertBefore(root, flowwrap); else host.appendChild(root);
  _ro = Object.assign(_ro, {
    root,
    drawer: root.querySelector('[data-ro-drawer]'),
    drawerList: root.querySelector('[data-ro-dlist]'),
    fw: root.querySelector('.hg-rov-fw'),
    flow: root.querySelector('[data-ro-flow]'),
    rail: root.querySelector('.hg-rov-fw'),   // v3.5.64：_ro.rail=定位父级 fw（退出时从这找回原 rail）
    subpaneEl: subpane, subpaneDisp: subOrigDisplay,   // 退出时恢复分屏显示
  });
  _ro.flow.addEventListener('scroll', () => {
    if (typeof _hgRailActiveRaf === 'function') _hgRailActiveRaf();
  }, { passive: true });
  // 交互同款：主层命名 handler（deps 传入）绑 RO flow
  _ro.flow.addEventListener('click', fc);
  _ro.flow.addEventListener('click', fc2);
  // rail 节点整体挪入 fw 首位（v3.5.64 用户实锤「只读导轨是空壳」：旧码
  // 建 <nav class="hg-rail" data-ro-rail> 外层再嵌原 rail——外层 .hg-rail
  // 默认 display:none 且嵌套后 absolute 定位塌陷。直接放 .hg-rov-fw
  // （position:relative 同主 flowwrap 形态）下无嵌套；_hgRailEl 引用不变，
  // _hgRailSync/_hgRailActive/点击跳转（绑在 rail 自身）照常工作
  if (rail) {
    _ro.fw.insertBefore(rail, _ro.fw.firstChild);
    rail.classList.add('show');   // .hg-rail 默认 display:none，需 .show 才可见
  }
  // _hgFlow 指向 RO 容器 + 清目标会话态（主会话态退出时 _hgSseRebuild 全量重建）
  _hgFlow = _ro.flow;
  if (typeof _hgSseResetLocal === 'function') _hgSseResetLocal();
  _HG.histAll = null; _HG.histLive = false; _HG.histStart = 0; _HG.histCursor = 0;
  // v3.5.69（用户 v3.5.65 拍板「默认打开」恢复）：进只读即开会话列表抽屉
  _ro.drawer.style.display = 'flex';
  RO_drawerRender();
  RO_view(sid);
  // 后台 busy 信标（5s 查主 sid 的 busy——纯显示，不 setBusy 不抢渲染）
  _ro.busyTimer = setInterval(() => {
    if (!_ro || !_ro.root || !_ro.root.isConnected) { clearInterval(_ro.busyTimer); _ro.busyTimer = null; return; }
    if (document.hidden) return;
    fetch('/api/harness/sessions').then(r => r.json()).then(j => {
      if (!j || !j.ok || !_ro) return;
      const s = (j.sessions || []).find(x => x.sid === _HG.sid);
      const b = _ro.root.querySelector('[data-ro-list]');
      if (b && s) b.textContent = (s.busy ? '● 后台进行中 · ' : '☰ ') + '会话';
    }).catch(() => {});
  }, 5000);
}

// RO 内切换查看的会话（抽屉跳转）：同场重渲（不回主视图）
function RO_view(sid) {
  if (!_ro) return;
  const gen = ++_ro.gen;
  fetch('/api/harness/transcript?sid=' + encodeURIComponent(sid))
    .then(r => r.json())
    .then(j => {
      // 守卫：readonly 已退 / 已切别的会话（gen 变）——迟到渲染弃
      if (!j || !j.ok || _HG.readonly !== sid || !_ro || _ro.sid !== sid || _ro.gen !== gen) return;
      _hgFlow = _ro.flow;
      if (typeof _hgSseResetLocal === 'function') _hgSseResetLocal();
      _HG.histAll = null; _HG.histLive = false; _HG.histStart = 0; _HG.histCursor = 0;
      if (!j.lines.length) {
        _ro.flow.innerHTML = '<div class="hg-list-empty" style="padding:40px;text-align:center;color:var(--muted)">该会话暂无历史内容</div>';
        return;
      }
      // 主渲染管线（designer 确认：与主窗口完全同款；noFinalize 对齐 switchTo 冷开）
      // v3.5.62（用户实锤「只读也只能看最近20条」）：start=0 全量渲染——
      // 窗口化起点（_hgHistWinStart）是主窗口 DOM 控制手段，只读要的就是全量；
      // 配套：_trimOldTurns 已加 readonly 守卫（renderUser 路径不再裁 20 轮）
      _histRender(j.lines, 0, { noFinalize: !!j.busy });
      if (j.busy) { if (typeof phResume === 'function') phResume(true); }
      else grpFinalize(true, { hist: true, turnEnd: true });
      if (typeof _hgRailSync === 'function') _hgRailSync();
      // v3.5.60（用户实锤「直接归底不展开工作区」）：撤 _hgScrollBottom——
      // RO 渲染后保持在顶部（看历史从上往下），不跳到底部
      _ro.flow.scrollTop = 0;
      // 默认展开子代理目录（方便查看过往子代理状态）
      if (typeof _subDirOpen === 'function') { try { _subDirOpen(); } catch (_) {} }
    })
    .catch(() => {});
}

function RO_drawerRender() {
  if (!_ro || !_ro.drawerList) return;
  // v3.5.69（v3.5.66 真修复移植）：抽屉独立 dgen——共用 _ro.gen 时 RO_view
  // 的 ++gen 会把在途抽屉 fetch 判过期丢掉（drawerRender 先发、RO_view 随即
  // ++gen，响应回来守卫必弃=抽屉恒空白「会话框没了」）
  const gen = ++_ro.dgen;
  fetch('/api/harness/sessions').then(r => r.json()).then(j => {
    // 世代守卫：退出/重进后在途旧响应不渲染进新抽屉
    if (!j || !j.ok || !_ro || _ro.dgen !== gen) return;
    const list = (j.sessions || []).slice().sort((a, b) =>
      (b.last_active || 0) - (a.last_active || 0));
    _ro.drawerList.innerHTML = list.map(s =>
      '<div class="hg-ro-ditem' + (s.sid === _HG.readonly ? ' cur' : '') + '" data-ro-dsid="' + esc(s.sid) + '" title="' + esc(s.cwd || '') + '">' +
        '<span class="hg-ro-dtitle">' + esc(s.title || '新会话') + '</span>' +
        '<span class="hg-ro-dmeta">' + (s.busy ? '● 后台运行中' : '历史会话') + '</span>' +
      '</div>').join('') || '<div class="hg-ro-ditem">（无会话）</div>';
    _ro.drawerList.querySelectorAll('[data-ro-dsid]').forEach(el => {
      el.onclick = () => {
        const dsid = el.dataset.roDsid;
        if (dsid === _HG.readonly) return;
        // v3.5.53（复核问题1 修复）：浏览态三处 sid 同步更新——守卫按当前
        // readonly 放行渲染（旧码不更新=守卫恒真=抽屉切换整体死亡）
        _HG.readonly = dsid;
        _HG.roViewSid = dsid;
        _ro.sid = dsid;
        // v3.5.177（用户实锤「点到了但焦点没变，还是显示最上面那个只读会话」）：
        // 切换后视觉焦点跟随——顶部标题与列表高亮同步（旧码只改状态变量，
        // cur 类和标题都是进 RO 时写死的，切会话后视觉停在进入时会话）
        const t2 = el.querySelector('.hg-ro-dtitle');
        const tb = _ro.root.querySelector('.hg-ro-title');
        // a261：图标位换 SVG——动态标题走 DOM 构建（textContent 不吃 HTML，
        // 防注入口径与旧代码一致）
        if (tb && t2) {
          tb.textContent = '';
          const _ico = document.createElement('span');
          _ico.style.verticalAlign = '-2.5px';
          _ico.innerHTML = ICO16.book;
          tb.appendChild(_ico);
          tb.appendChild(document.createTextNode(' 只读模式 · ' + t2.textContent));
        }
        _ro.drawerList.querySelectorAll('[data-ro-dsid]').forEach(el2 =>
          el2.classList.toggle('cur', el2.dataset.roDsid === dsid));
        RO_view(dsid);
      };
    });
  }).catch(() => {});
}

function RO_exit(force) {
  if (!_ro) return;
  const rail = _ro.rail && _ro.rail.querySelector('[data-hg-rail]');
  const flowwrap = document.querySelector('.hg-flowwrap');
  // rail 救回 flowwrap（RO 销毁前——节点在 RO 子树里会一起没）；摘 .show
  // 交回主窗口 _hgRailSync 按回合数决定显隐（RO 期间被强制 show 过）
  if (rail && flowwrap) { rail.classList.remove('show'); flowwrap.insertBefore(rail, flowwrap.firstChild); }
  const sid = _HG.readonly;
  // 清守卫在前——退出流程内的 rebuild/setBusy 要恢复工作
  _HG.readonly = null;
  _HG.roViewSid = null;
  if (_ro.busyTimer) { clearInterval(_ro.busyTimer); _ro.busyTimer = null; }
  if (_ro.root) _ro.root.remove();
  // 恢复 peerSent 快照（designer P2：B 的 resumedAgentId 映射不残留进 A）
  if (_ro.snapPeerSent !== null) _HG.peerSent = _ro.snapPeerSent;
  const anchor = _ro.anchorSid;   // v3.5.53：进入只读时的主会话（退出 rebuild 判定锚）
  const roSub = _ro.subpaneEl, roSubDisp = _ro.subpaneDisp;
  _ro = null;
  // 恢复布局
  const side = document.querySelector('.hg-side');
  const cardwrap = document.querySelector('.hg-card-wrap');
  if (side) side.style.display = '';
  if (flowwrap) flowwrap.style.display = '';
  if (cardwrap) cardwrap.style.display = '';
  if (roSub) roSub.style.display = roSubDisp;
  // _hgFlow 指回主 flow（rebuild 的 resetLocal 清的是它）
  _hgFlow = document.querySelector('[data-hg-flow]');
  // v3.5.215（用户实锤「退出只读也有白屏过程」）：退出不做清场重放——
  // 主 flow 旧 DOM 本就完整（RO 只隐藏未清空），先直接显示（无白屏），
  // 后台拉转写有增长→窗口重渲一次做对（keepDom 原子换入；busy 传
  // noFinalize+phResume 接秒表），末尾 V4Main.switch 以投影快照权威覆盖
  // （旧 _hgSseRebuild/openSSE 断点续传已随批G 退役）。force=true 仅供
  // 关 tab 濒死路径
  if (!force && anchor && _HG.sid === anchor) {
    if (typeof _histFetch === 'function') {
      _histFetch(anchor).then((ok) => {
        if (!ok || _HG.sid !== anchor || _HG.readonly) return;
        let hEnd = 0;
        try {
          _hgFlow.querySelectorAll('[data-h-end]').forEach(el => {
            hEnd = Math.max(hEnd, +(el.dataset.hEnd || 0)); });
        } catch (_) {}
        if (_HG.histAll && _HG.histAll.length - 1 > hEnd) {
          // C组G4：busy 用 fetchedBusy（_histFetch 刚刷新的后端真值）——
          // RO 期间 SSE 断，_HG.busy 冻结陈旧：true→幻影工作中头空转；
          // false→活组被定稿后新帧另起组=分裂
          const _b = (_HG.fetchedBusy != null) ? _HG.fetchedBusy : !!_HG.busy;
          _histRender(_HG.histAll, _HG.histStart | 0, { noFinalize: _b });
          if (_b && typeof phResume === 'function') phResume(true);
          // 410：spin 恢复内聚于 _histRender 尾部（409），调用方散补退役
          try { _hgScrollBottom(true); } catch (_) {}
        }
        // A组G1：RO_enter resetLocal 清掉的 dyn/todos/agents 重建（无增长
        // 分支不跑渲染循环=无人重建，侧栏/目录空）+agents restore
        try { _hgRplRebuild && _hgRplRebuild(); } catch (_) {}
        if (typeof _hgLiveAgentsRestore === 'function') { try { _hgLiveAgentsRestore(anchor); } catch (_) {} }
        try { renderSideStatus(); } catch (_) {}
      });
    }
    // B组P1 历史注：openSSE 时代用 transcript 回带的真 seq 重开流；v4 起
    // 投影 store 接管恢复（snapshot 重建为权威形态，覆盖上方过渡渲染）
    { const _tgt = anchor || _HG.sid;
      if (_tgt) V4Main.switch(_tgt); }
  } else if (!force && _HG.sid) {
    // 二轮 P1-1：force=关 tab 濒死路径不得重开投影流（shell 侧随关 V4Main.close）
    V4Main.switch(_HG.sid);
  }
}

// 横条按钮委托（会话列表开关/退出）——RO DOM 建完后绑
document.addEventListener('click', (e) => {
  if (!_HG.readonly || !_ro || !_ro.root || !_ro.root.contains(e.target)) return;
  if (e.target.closest('[data-ro-exit]')) { RO_exit(); return; }
  if (e.target.closest('[data-ro-list]')) {
    const d = _ro.drawer;
    d.style.display = d.style.display === 'none' ? 'flex' : 'none';
    if (d.style.display === 'flex') RO_drawerRender();
  }
});

// 全局暴露（20-main 入口传 deps 调用）
window.HgRO = { enter: RO_enter, exit: RO_exit };
