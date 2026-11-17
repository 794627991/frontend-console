// harness subpane.js (v3.0 自 buildClaudeHarnessTab 拆出;v3.2.6 窗格时间线重写——ZCode 子智能体模式)
  const _sub = { tabs: {}, order: [], active: null, manual: false };
  // a605：sid → 上次激活的子代理 tab。切会话会 _subReset 清空 tabs，用户
  // 要求「切回来保持上次打开的那个子代理」，重建时按它认领而非从头轮换。
  let _subActiveBySid = {};
  // a609：会话删除时回收该 sid 的 tab 记忆（原来只写不删，随会话数单调增长）
  function _subActiveBySidForget(sid) {
    if (!sid || !_subActiveBySid) return;
    try { delete _subActiveBySid[sid]; } catch (_) {}
  }
  window._sub = _sub;   // a65：v4bridge 子引擎按 tid 查 tab——const 不上 window，显式挂
  const _subTailBusy = {};   // 复审#1：转写喂数防重入锁（批1 重写时随 _subTailDead 声明块误删致通道整体 ReferenceError）
  // ==================== v3.2：子智能体目录（ZCode SubagentDirectorySidePane 移植）====================
  // 目录是一个常驻伪 tab（__dir__）：正在运行/已结束两组列表，行卡=状态图标+
  // 标题+状态词+摘要+相对时间；点行开该代理视图 tab（live 直开 / 已结束走回放）。
  // 数据源=live 档案 _HG.agents + 回放档案 dyn.agentsRpl（对照 useSessionSubagents
  // 的 running/ended 两段口径，我们无分页——量级远小于 ZCode 云端）
  const _SUB_DIR = '__dir__';
  // ==================== v3.3：会话动态页（分屏化，常驻伪 tab）====================
  // 右侧 #aiPanel 换装面板整体废止（21-shell _hgPanelMode 改纯隐藏），六分区
  // 骨架迁入分屏伪 tab __dyn__（同 __dir__ 生命周期：_subReset 清、按需重建、
  // 6-tab 逐出豁免、无 ✕；渲染序恒在队首）。骨架原为 index.html 静态节点
  //（v2.30 教训：页面加载早期向 harness wrap 内绑定会扑空）——懒建无此问题：
  // 绑定发生在用户点胶囊时，分屏 DOM 必然在场。sc 上 setAttribute('data-hg-dyn')
  // 让 20-main tick 的自愈重绑（querySelector('[data-hg-dyn]')）路径继续成立。
  const _SUB_DYN = '__dyn__';
  const _HG_DYN_SKELETON =
    `<div class="hg-sub-dir-head">会话动态</div>` +
    `<section class="hg-dyn-sec" data-hg-sec="stat">` +
      `<div class="hg-dyn-strow">` +
        `<span class="hg-dyn-dot"></span>` +
        `<span class="hg-dyn-stlabel" data-hg-d-st>就绪</span>` +
        `<b class="hg-dyn-dur" data-hg-d-stt></b>` +
      `</div>` +
      `<div class="hg-dyn-kv"><span class="k">模型</span><span class="v" data-hg-d-model>—</span></div>` +
      `<div class="hg-dyn-kv"><span class="k">思考</span><span class="v" data-hg-d-think>默认</span></div>` +
      `<div class="hg-dyn-kv"><span class="k">权限</span><span class="v" data-hg-d-perm>—</span></div>` +
      `<div class="hg-dyn-kv"><span class="k">三角色</span><span class="v act" data-hg-d-roles>…</span></div>` +
      `<div class="hg-dyn-kv"><span class="k">目录</span><span class="v" data-hg-d-cwd>~</span></div>` +
      `<div class="hg-dyn-kv ctx"><span class="k">上下文</span><span class="v" data-hg-d-ctx>待统计</span></div>` +
    `</section>` +
    `<section class="hg-dyn-sec" data-hg-sec="todos" hidden>` +
      `<div class="hg-dyn-sec-head">进程<span class="hg-dyn-pill" data-hg-d-tdone>0/0</span></div>` +
      `<div class="hg-dyn-bar"><i data-hg-d-tbar></i></div>` +
      `<div class="hg-dyn-todos" data-hg-d-tlist></div>` +
    `</section>` +
    `<section class="hg-dyn-sec" data-hg-sec="agents" hidden>` +
      `<div class="hg-dyn-sec-head">子代理 / 协作<span class="hg-dyn-pill run" data-hg-d-agrun hidden>0 运行中</span><button class="hg-dyn-dirbtn" data-hg-agdir hidden title="打开子智能体目录（正在运行/已结束全列表）"></button></div>` +
      `<div data-hg-d-aglist></div>` +
    `</section>` +
    `<section class="hg-dyn-sec" data-hg-sec="acts" hidden>` +
      `<div class="hg-dyn-sec-head">最近工具</div>` +
      `<div class="hg-dyn-acts" data-hg-d-acts></div>` +
    `</section>` +
    `<section class="hg-dyn-sec" data-hg-sec="turns" hidden>` +
      `<div class="hg-dyn-sec-head">回合历史<span class="hg-dyn-sub" data-hg-d-tsum></span></div>` +
      `<div class="hg-dyn-turns" data-hg-d-tlist></div>` +
    `</section>` +
    `<section class="hg-dyn-sec" data-hg-sec="files" hidden>` +
      `<div class="hg-dyn-sec-head">当前文件</div>` +
      `<div class="hg-dyn-files" data-hg-d-flist></div>` +
    `</section>`;
  function _subDynEnsure() {             // 动态页懒建（不夺焦点；a93T 运行分支也补建）
    if (!_subPaneEl || _sub.tabs[_SUB_DYN]) return;
    const sc = document.createElement('div');
    sc.className = 'hg-sub-msgs hg-dyn-pane'; sc.dataset.tid = _SUB_DYN;
    sc.setAttribute('data-hg-dyn', '');
    sc.innerHTML = _HG_DYN_SKELETON;
    _sub.tabs[_SUB_DYN] = { label: '动态', type: '__dyn__', desc: '会话动态', sc,
                            run: false, err: false, replay: false, model: '' };
    _sub.order.push(_SUB_DYN);
    _subBodyEl.appendChild(sc);
    sc.onclick = _hgDynClick;          // 覆盖式绑定（伪 tab 重建不叠加）；先绑 dynEl 再渲（首帧不扑空）
    dynEl = sc;
    // 轻审P1 同款（_subDirEnsure 口径）：不夺焦的 tab 必须显式隐藏——漏设会
    // 与激活 tab 平分 body 高度（空白下半屏）
    if (_sub.active !== _SUB_DYN) sc.style.display = 'none';
    // P1-1 修复（a116）：新建伪 tab 后必须重绘 tab 条（与 _subDirEnsure
    // 同口径）。a108 的「胶囊点击且已有运行中代理」分支先跑完 _subReopen×N
    // 与 _subDirEnsure，再调本函数；漏掉这次重绘 → tab 条停在上一次绘制结果，
    // 用户只看到「版本/目录」看不到「状态」，正是 a108 声称修掉的现象。
    try { if (typeof _subTabsPaint === 'function') _subTabsPaint(); } catch (_) {}
  }
  function _subDynOpen() {               // 动态页伪 tab（懒建；胶囊点击的展开面）
    if (!_subPaneEl) return;
    // a93T（用户定调「点开胶囊后，状态、版本、目录显示，固定顺序排最前」）：
    // 胶囊展开即两伪 tab 全量在场（_subDirEnsure 头部链式带动态页，
    // 均不夺焦点），此前只出目录/版本漏状态
    try { if (typeof _subDirEnsure === 'function') _subDirEnsure(); } catch (_) {}
    _subDynEnsure();
    _subShow(_SUB_DYN); _subTabsPaint(); _subActivate(_SUB_DYN);
    renderSideStatus();
    _hgRolesFetch(); _hgAgentModelsFetch();   // 原 _hgPanelEnterHook 职责随开随拉（点击天然节流）
    _sub.manual = true;                // 用户主动展开——回合终结不自动收（同 _subDirOpen/_subReopen 口径）
  }
  function _subDirRows() {
    // v3.5.22（用户需求「task 与子代理区分」）：后台任务独立分区——档案
    // v3.5.147（用户拍板「task 不要显示在子智能体目录——点开也无法回放，
    // 没意义」）：后台任务退出目录（主会话流行卡+悬浮 title 已承载其结果），
    // _HG.tasks 不再混入；v3.5.22 的目录分区与 1s 重绘条件一并退役
    // v3.5.147（用户拍板「只显示当天的子智能体，超期不用再显示」）：当天闸
    // （普通模式专用——只读模式 RO 目录不经此函数）：已结束/回放条目只留
    // 今天完成的（今天 00:00 起）；运行中不受限（跨零点仍在跑的必须可见）
    const _dayStart = (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); })();
    const rows = [];
    // v3.4.56（轻审复核 P3 收口）：运行中 live 档案的同 desc 回放条目滤除——
    // restore 时序/重建/快照各路差异全部在产出侧一处收口，目录不再双条
    const _runDescs = new Set();
    // a84（用户实锤「sendmessage 后变成 6 个子代理」）：档案级链去重——
    // 同 agentId/taskId 的多把键（原 tid/包装 tid/agentId 冷档）只留第一份
    //（续派归并在源头：v4bridge _applyOne 并入原档；此处只兜注册表 Sync
    // 与 live 归并的时序缝隙）。优先保 done=false 的一份：先扫一遍把运行中
    // 链键收进集合，第二遍产出行时让位
    const _chainLive = new Set();
    for (const tid in (_HG.agents || {})) {
      const a = _HG.agents[tid];
      if (!a || a.done) continue;
      const _cid = a.taskId || a.agentId || '';
      if (_cid) _chainLive.add(_cid);
    }
    const _seenIds = new Set();
    for (const tid in (_HG.agents || {})) {
      const a = _HG.agents[tid];
      // v3.5.306b（用户实锤「明明有至少一个设计一个审核的，目录啥都没有」）：
      // collab/Task 曾因「无转写可回放」退目录（v3.4.43/v3.5.163）——前提已
      // 变：v2.46R 起 task_started 修正路径回填 a.taskId=真实 agentId（转写
      // 可达），v3.5.296 起建档即补 desc 原名。有 id 可回放即放行进目录；
      // 仍无 id 的保持退出（点开必空的场景不复活）
      if (!a || a.replay) continue;
      if ((a.collab || (a.type || '') === 'Task') && !a.taskId && !a.agentId) continue;
      // a84：链去重——本档案的链键已有运行中档案在场且本条非运行中=让位；
      // 双运行中（归并缺失的兜底）也只留先入者
      {
        const _cid = a.taskId || a.agentId || '';
        if (_cid) {
          if (_chainLive.has(_cid) && a.done) continue;   // 已结束档案让位运行中链
          if (_seenIds.has(_cid)) continue;               // 双运行中兜底：留先入
          _seenIds.add(_cid);
        }
      }
      if (!a.done && a.desc) _runDescs.add(a.desc);
      rows.push(Object.assign({ tid }, a));
    }
    for (const a of ((_HG.dyn && _HG.dyn.agentsRpl) || [])) {
      if (a.desc && _runDescs.has(a.desc)) continue;   // v3.4.56:同名回放条目让位运行中
      if (a.agentId && _seenIds.has(a.agentId)) continue;   // a58R：同 aid 档案在场，回放档让位
      // v3.5.147 当天闸已拆（a273 用户需求「不限当天，超 20 默认收起」）——
      // 全量进列表，渲染层负责折叠
      // v3.5.306b：Task/协作回放条目同款放行（有 agentId 可回放即进，同上）
      if ((a.type || '') === 'Task' && !a.agentId) continue;
      // rid 补发（与 _dynAgents 同款持久发号——条目点击按 rid 回查存档）
      if (!a.rid) a.rid = 'rpl' + ((_HG.rplSeq = (_HG.rplSeq || 0) + 1));
      rows.push(Object.assign({ tid: a.rid, rpl: true }, a));
    }
    // 冷查询批3（I3 一链一档）：本地续派在 10-sse 归链并入原档（live）/
    // 后端 send 归链（Sync），目录天然一链一行——v3.5.322 链合并块退役
    const running = rows.filter(r => !r.done)
      .sort((x, y) => (x.t0 || 0) - (y.t0 || 0));
    // a273（用户需求）：不限当天——已结束全量按时间倒序；>20 条默认只显
    // 前 20，渲染层给「展开全部」钮（_subDirPaint 消费 _dirExpanded）
    const ended = rows.filter(r => r.done)
      .sort((x, y) => (y.doneAt || y.t0 || 0) - (x.doneAt || x.t0 || 0));
    return { running, ended };
  }
  let _dirExpanded = false;   // a273：已结束区折叠态（>20 条时默认收起）
  function _subDirRowHtml(r) {
    // 状态三态（对照 StatusIcon）：运行 spinner / 成功 ✓ / 失败 ✗ / 中断 ⏹
    const _run = !r.done;
    const st = _run ? 'run' : (r.interrupted ? 'stop' : (r.err ? 'err' : 'ok'));
    const stIco = { run: '◐', ok: '✓', err: '✗', stop: '⏹' }[st];
    const stTxt = { run: '运行中', ok: '已完成', err: '已失败', stop: '已中断' }[st];
    const title = ((_AGENT_LABEL[r.type] || r.type || '子代理') +
      (r.desc ? ' · ' + r.desc : '')).slice(0, 80);
    const sum = String(r.result || '').replace(/\s+/g, ' ').trim().slice(0, 120);
    // v3.2.31（bug5① 同源）：result 复述描述（CLI 透传摘要=description）时
    // 标题与摘要行同文——重复观感，摘要行让位。v3.2.31R（复审6）：复用
    // 08-tools _hgBriefDupDesc（显式两串入参），不再各持一份实现。
    // 已知权衡（记录不改）：120 字截断的前缀判定是启发式，跨界同文可能漏判
    const _dupDesc = !!sum && !!r.desc && _hgBriefDupDesc(r.desc, sum);
    // v3.2.6（ZCode 模式）：运行行时间位改秒表（对照 ConversationStatusPanel
    // 的 elapsed 计数——1s 重绘由 _subDirTick 驱动）；已结束保持相对时间
    const t = _run ? (r.t0 || 0) : (r.doneAt || 0);
    const timeTxt = _run ? (t ? _hgFmtDur(Math.max(0, (Date.now() - t) / 1000)) : '')
      : _harnessRelTime(t);
    return `<button class="hg-sub-dir-row ${st}" data-hg-dir="${esc(r.tid)}"` +
      ` data-hg-dir-rpl="${r.rpl ? '1' : ''}" title="${esc(title)}">` +
      `<span class="hg-sub-dir-ico">${stIco}</span>` +
      `<span class="hg-sub-dir-main"><span class="hg-sub-dir-t1">` +
      `<span class="hg-sub-dir-title">${esc(title)}</span>` +
      `<span class="hg-sub-dir-st">${stTxt}${r.bg ? ' · 后台' : ''}${r.collab ? ' · 协作' : ''}${r.rounds > 1 ? ' · 第' + r.rounds + '轮' : ''}</span></span>` +
      (sum && !_dupDesc ? `<span class="hg-sub-dir-sum">${esc(sum)}${String(r.result || '').trim().length > 120 ? '…' : ''}</span>` : '') +
      `</span>` +
      (timeTxt ? `<span class="hg-sub-dir-time">${esc(timeTxt)}</span>` : '') +
      `</button>`;
  }
  let _subDirTick = null;
  function _subDirTickStop() {
    if (_subDirTick) { clearInterval(_subDirTick); _subDirTick = null; }
  }
  function _subDirPaint() {
    const tb = _sub.tabs[_SUB_DIR];
    if (!tb || _sub.active !== _SUB_DIR || !tb.sc) return;
    const { running, ended } = _subDirRows();
    // a273：>20 条默认收起（前 20 + 「展开全部」钮）；点击展开/收起
    const _MAX = 20;
    const _folded = !_dirExpanded && ended.length > _MAX;
    const _shown = _folded ? ended.slice(0, _MAX) : ended;
    tb.sc.innerHTML =
      `<div class="hg-sub-dir-head">子智能体目录</div>` +
      `<div class="hg-sub-dir-sec">正在运行 · ${running.length}</div>` +
      (running.length ? running.map(_subDirRowHtml).join('')
        : `<div class="hg-sub-dir-empty">没有正在运行的子智能体</div>`) +
      `<div class="hg-sub-dir-sec">已结束 · ${ended.length}${_folded ? `（显示前 ${_MAX}）` : ''}</div>` +
      (_shown.length ? _shown.map(_subDirRowHtml).join('')
        : `<div class="hg-sub-dir-empty">还没有已结束的子智能体</div>`) +
      (ended.length > _MAX
        ? `<button class="hg-sub-dir-more" data-hg-dir-toggle="${_folded ? 'open' : 'close'}">` +
          `${_folded ? `▼ 展开全部（还有 ${ended.length - _MAX} 个）` : `▲ 收起`}</button>` : '');
    const _tg = tb.sc.querySelector('[data-hg-dir-toggle]');
    if (_tg) _tg.onclick = () => {
      _dirExpanded = _tg.dataset.hgDirToggle === 'open';
      _subDirPaint();
    };
    // v3.2.6：有运行行才起 1s 重绘（秒表走字）；目录失活/运行清空自停
    // v3.5.147：后台任务退出目录（用户拍板），tick 条件同步收窄
    if (running.length && !_subDirTick) {
      _subDirTick = setInterval(() => {
        if (_sub.active !== _SUB_DIR) { _subDirTickStop(); return; }
        if (!_subDirRows().running.length) { _subDirTickStop(); return; }
        _subDirPaint();
      }, 1000);
    }
  }
  function _subDirEnsure() {
    // v3.4.60（用户需求）：胶囊/动态页打开时同步把目录 tab 懒建在场（不夺
    // 焦点）——点胶囊不再只看到单个视图，目录列表随手可切。已建时零操作
    if (!_subPaneEl || _sub.tabs[_SUB_DIR]) return;
    const sc = document.createElement('div');
    sc.className = 'hg-sub-msgs hg-sub-dir'; sc.dataset.tid = _SUB_DIR;
    sc.style.display = 'none';   // 轻审P1：不夺焦的 tab 必须显式隐藏——CSS 层
                                 // .hg-sub-msgs 默认 flex 可见，漏设会与激活
                                 // tab 平分 body 高度（空白下半屏）
    _sub.tabs[_SUB_DIR] = { label: '目录', type: '__dir__', desc: '子智能体目录', sc,
                            run: false, err: false, replay: false, model: '' };
    _sub.order.push(_SUB_DIR);
    _subBodyEl.appendChild(sc);
    _subDirPaint();
    _subTabsPaint();
  }
  function _subDirOpen() {
    if (!_subPaneEl) return;
    if (!_sub.tabs[_SUB_DIR]) {
      const sc = document.createElement('div');
      sc.className = 'hg-sub-msgs hg-sub-dir'; sc.dataset.tid = _SUB_DIR;
      _sub.tabs[_SUB_DIR] = { label: '目录', type: '__dir__', desc: '子智能体目录', sc,
                              run: false, err: false, replay: false, model: '' };
      _sub.order.push(_SUB_DIR);
      _subBodyEl.appendChild(sc);
    }
    _subShow(_SUB_DIR); _subTabsPaint(); _subActivate(_SUB_DIR);
    _subDirPaint();
    _sub.manual = true;   // v3.2：目录是用户主动打开的视图——回合结束不自动收（同 _subReplay 口径）
  }
  function _subDirRowClick(tid, isRpl) {
    // v3.5.147：后台任务分支退役——tasks 已退出目录（用户拍板，无回放意义）
    if (isRpl) {
      // 回放档案条目（历史 Task 行派生）：rid 定位存档，agentId 开回放 tab
      const a = ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => (x.rid || '') === tid);
      if (!a) return;
      // v3.2R1(P2)：无 agentId 本地单 toast 即止——_subReplay('') 内部还会
      // 弹一条，双 banner 2.6s 内相继覆盖
      // v4.0.1（无条件可点开）：无 agentId 交解析漏斗——回放档 rid 不是
      // 真 id，挖不出就由漏斗兜底开目录，不再静默弹一句了事
      if (!a.agentId) { _subResolveOpen(tid, a.type, a.desc); return; }
      _subReplay('rpl:' + tid, a.type, a.desc, a.agentId, true);
      return;
    }
    const a = (_HG.agents || {})[tid];
    // v4.0.1（用户硬性要求「无条件能点开任意子代理」）：档案缺失原先是
    // 静默 return（点了毫无反应）——交给统一的解析漏斗，行上有 tid 就
    // 一定尝试解析到真实 agentId
    if (!a) { _subReopen(tid); return; }
    // v3.5.160 全审F3a：幻影档案（unresolved=降级 taskId 无转写）**不分
    // done/运行**一律走解析漏斗——notification 到达即 done:true 而
    // unresolved 保留，done 分支拿包装 taskId 硬开回放=「未找到」+noreplay
    // 锁（用户实锤 b7xvfmyip 形态在已结束入口存活）
    // v4.0.1：与 _subReopen 的幻影分支收口到同一函数，避免两处漏斗分叉
    if (a.unresolved && !a.agentId) { _subResolveOpen(tid, a.type, a.desc); return; }
    if (!a.done) {
      // v3.2.6（ZCode 模式）：协作代理运行中——段卡已隐、过程唯一可看面=窗格，
      // 有真实 taskId 即开全量回放+轮询镜像续流（force 重拉）；无 id 回落跳
      // 主流段锚点（数据缺失的老形态）
      if (a.collab) {
        const aid = a.taskId || a.agentId || '';
        if (aid) { _subReplay(tid, a.type, a.desc, aid, true); return; }
        // v4.0.1（用户硬性要求「无条件能点开任意子代理」）：无真实 id
        // 不再只弹 banner——走解析漏斗尝试从转写里挖出 agentId
        _subResolveOpen(tid, a.type, a.desc);
        return;
      }
      // v3.5.324（用户实锤「切会话再切回来，数据没了」）：运行中一律走
      // _subReopen（全量铺底+续流+归一+解析漏斗）——旧走 _subOpen 只建空壳
      // 实况 tab，SSE 仅喂切回后新到事件，切走期间的完整过程永久缺失
      _subReopen(tid);
      return;
    }
    // 已结束 → 回放 tab（collab 分支内部自理）。实测修复：force=true——369 只
    // 补了 _subReopen 路径，目录已结束行此直调无 force 时 tab 已在（replayed
    // 标记命中）只切换不重拉，旧版双通道乱序残留 DOM（终稿后跟中途文本冒充
    // 结论）继续可见；重开=全量重铺幂等
    _subReplay(tid, a.type, a.desc, a.taskId || a.agentId || '', true);
  }
  function _subReset() {
    // a605（用户要求「切会话保持上次打开的子代理界面」）：先把本会话的
    // active tab 记下来，重建后自愈补建时优先认领它，不要从头轮换。
    try {
      if (_HG.sid && _sub.active && String(_sub.active).indexOf('__') !== 0)
        (_subActiveBySid || (_subActiveBySid = {}))[_HG.sid] = _sub.active;
    } catch (_) {}
    // a64：v4 子 store 全量随清场关闭（切会话/删会话路径）——EventSource 不
    // 关=同域连接永久泄漏（6 条上限），几次切换后全前端请求排队发不出去
    try {
      if (typeof V4Main !== 'undefined' && V4Main.subCloseAll)
        V4Main.subCloseAll();
    } catch (_) {}
    // v3.2.6：先停全部窗格秒表/目录秒表再拆档（防孤儿 interval）
    _subDirTickStop();
    for (const k in _sub.tabs) {
      const tb = _sub.tabs[k];
      if (tb && tb.tick) { clearInterval(tb.tick); tb.tick = null; }   // v3.4：tick 挂 tab
    }
    _sub.tabs = {}; _sub.order = []; _sub.active = null; _sub.manual = false;
    dynEl = null;   // v3.3：动态页 sc 随清场销毁——防渲染进游离节点（重开由 _subDynOpen 重建）
    if (_subPaneEl) { _subPaneEl.style.display = 'none'; _subTabsEl.innerHTML = ''; _subBodyEl.innerHTML = ''; }
  }
  // ==================== v3.2.31：子代理窗格真分屏（需求2）====================
  // 窗格从 220~640px 窄侧栏升级为半屏分屏：宽度记忆改为百分比 hg-subpane-pct
  // （25%~75%，默认 50%），分母=聊天区总宽（.hg 宽 − 左侧会话栏宽，即
  // .hg-main + .hg-subpane）——「左右各约 50%」对用户视角的聊天区成立。
  // 拖拽（20-main _subRes mousedown）同口径计算。旧 hg-subpane-w（px）首次
  // 按 currentRegion 折算迁移一次，之后只读写 pct 键。
  function _hgSubRegion() {   // 聊天区总宽（px）；wrap 隐藏/未布局时 ≤0
    const hg = _hgWrap && _hgWrap.querySelector('.hg');
    if (!hg) return 0;
    const side = hg.querySelector('.hg-side');
    return hg.clientWidth - ((side && side.offsetWidth) || 0);
  }
  // v3.4.21（用户定调「非子代理界面默认收窄，子代理输出才保持当前宽度」）：
  // 分屏宽度按激活 tab 分档——动态/目录（状态视图）=窄档（默认 30%，独立
  // 记忆拖拽）；子代理实况/回放=宽档（hg-subpane-pct，默认 50%，既有记忆）
  function _subPanePctKey(tid) {
    const a = tid || _sub.active;
    return (a === _SUB_DYN || a === _SUB_DIR)
      ? 'hg-subpane-narrow-pct' : 'hg-subpane-pct';
  }
  function _hgSubPctGet(kOpt) {
    const k = kOpt || _subPanePctKey();
    try {
      const p = parseFloat(localStorage.getItem(k));
      if (p >= 25 && p <= 75) return p;
      if (k === 'hg-subpane-pct') {
        const w = +(localStorage.getItem('hg-subpane-w') || 0);
        if (w >= 220 && w <= 640) {
          const region = _hgSubRegion();
          if (region > 0) {
            const pct = Math.min(75, Math.max(25, w / region * 100));
            try { localStorage.setItem('hg-subpane-pct', pct.toFixed(2)); } catch(_) {}
            return pct;
          }
        }
      }
    } catch(_) {}
    return k === 'hg-subpane-narrow-pct' ? 30 : 50;
  }
  function _hgSubPctApply(pct) {
    if (!_subPaneEl) return;
    const region = _hgSubRegion();
    // wrap 隐藏（后台 tab 收到 Task 派发自动开窗格）时不写死 px——clientWidth
    // 恒 0 会把宽度焊成几十 px，切回 tab 窗格缩成一竖条；保持 CSS 默认 50%
    if (region <= 220) return;
    let px = Math.round(region * pct / 100);
    // v3.5.69（用户「适当缩窄」）：目录/动态窄档 cap 360px。
    // v3.5.70（用户实锤「历史子代理分页有点宽了 缩小一点」）：宽档（实况/
    // 回放）按百分比在宽屏上同样过宽——cap 620px（resizer 拖拽仍受 25~75%
    // 记忆，仅默认/超宽收敛）
    px = Math.min(px, _subPanePctKey() === 'hg-subpane-narrow-pct' ? 360 : 620);
    _subPaneEl.style.width = px + 'px';
  }
  function _subShow(pendingTid) {
    if (!_subPaneEl || _subPaneEl.style.display !== 'none') return;
    // v3.4.39（v3.4.38 复现实锤「还是从大变小」）：两处时序漏洞——
    // ① 档位 key 必须用 pendingTid：展开链里 _subShow 先于 _subActivate 跑，
    //    active 还是 null→误判宽档，首帧写 50%；
    // ② 过渡恢复必须等下一帧：reflow 固化首帧布局后同 tick 恢复过渡，随后
    //    _subActivate 的窄档写入即播 50%→30% 收缩动画（上次修的败因）。
    //    rAF 下一帧恢复，本 tick 内后续写宽全在禁用期，同值写入无动画
    _subPaneEl.style.transition = 'none';
    _hgSubPctApply(_hgSubPctGet(_subPanePctKey(pendingTid)));
    _subPaneEl.style.display = 'flex';
    void _subPaneEl.offsetWidth;
    requestAnimationFrame(() => { if (_subPaneEl) _subPaneEl.style.transition = ''; });
  }
  // ==================== v3.2.6：窗格时间线（ZCode 子智能体会话模式）====================
  // 对照 ZCode SubagentSessionSidePane = 完整 SessionPane（readOnly）的产品事实：
  // 子代理自己的会话用与主会话同款的回合结构呈现——turn-head（工作中 Ns /
  // 已工作 X · N 思考 · M 工具）+ 时间线（🧠 思考持续了 N 秒 / 工具行 / 查阅
  // 聚组 / 中间正文气泡按序穿插）+ 根区最终结论。live（SSE/轮询镜像增量）与
  // replay（转写 fetch 全量）同走一套行工厂，仅定稿时长来源不同（live=档案
  // t0 秒表；replay=rows 首末行 ts 差——transcript.py v3.2.6 起行行带 ts）
  function _subTabLabel(type, desc) {
    const d = String(desc || '').trim();
    if (d) return d.slice(0, 14) + (d.length > 14 ? '…' : '');
    return _AGENT_LABEL[type] || type || '子代理';
  }
  // v3.2.30（用户实锤「运行中的代理看不到发给它的消息，一次改全」）：live
  // 来向消息——Task 派发的 prompt / SendMessage 的追加 message。回放侧
  // （v3.2.21/24）已入线程并暴露化；live 窗格只靠事件镜像流（无 user 行）
  // ——派发时入队，tab 已开直接插、未开等 _subOpen/task_started 绑 id 后冲
  function _subUserQueue(key, text) {
    const t = String(text || '').trim();
    if (!key || !t) return;
    _HG.subUserQ = _HG.subUserQ || {};
    const q = (_HG.subUserQ[key] = _HG.subUserQ[key] || []);
    if (q.length < 20) q.push(t.slice(0, 1200));
    _subUserFlush(key);
  }
  function _subUserRowEl(text) {
    const u = document.createElement('div');
    u.className = 'h-msg user hg-sub-u';
    u.appendChild(mdBubble(String(text || '').slice(0, 1200)));
    return u;
  }
  // ==================== v3.4：续派归一（SendMessage 必须接回原子代理 tab）====
  // CLI 把 SendMessage 续派包装成新 task id——事件流/档案/段全按包装 id 走，
  // 不归一则窗格为每个包装 id 开独立 tab（用户实锤「绝对禁止」）。零状态归一：
  // tabs 直命中 → agents 反查（原始 tid 的 taskId/agentId 关联任一命中）→ 原键。
  // agents 档案天然携带三向关联（X.taskId=A、包装 b.id.taskId=A），无需 alias 表。
  function _subTid(pid) {
    // 冷查询批2：单点解析（tabs 直配 → aidKey → tidMap 得 aid →
    // tabs[aid] → tidMap 反扫）。tidMap 写点已完备（批1 I2），旧三向
    // 反查/链扫描退役。全审P3：补 aidKey 腿——p=agentId 形态（消息
    // 队列键=to/轮2 事件）在 live 窗口（tab 开于首见 tid、Sync 未到）
    // 靠它归回，旧向一（agents[t].taskId===p 扫描）的覆盖由此补齐
    const p = String(pid || '');
    if (!p || _sub.tabs[p]) return p;
    const ak = (_HG.aidKey || {})[p];
    if (ak && _sub.tabs[ak]) return ak;
    const aid = (_HG.tidMap || {})[p];
    if (aid) {
      if (_sub.tabs[aid]) return aid;
      for (const t in _HG.tidMap) {
        if (_HG.tidMap[t] === aid && _sub.tabs[t]) return t;
      }
      return aid;   // 归回 agentId（_subOpen/_subReopen 按它定位转写，绝不单开包装 tab）
    }
    return p;
  }
  // 冷查询批2：一链一档（归链后 done 即整链状态，链扫描退役）
  function _subAgRunning(tid) {
    const a = _hgAg(tid);
    return !!(a && !a.done);
  }
  function _subUserFlush(key) {
    const q = _HG.subUserQ;
    if (!q || !q[key] || !q[key].length) return;
    const tb = _sub.tabs[key] || _sub.tabs[_subTid(key)];   // 单点解析
    if (!tb || !tb.t || !tb.t.tl) return;   // 窗格未开——留队等开
    const texts = q[key];
    delete q[key];
    for (const text of texts) _subUserInto(tb, text);
  }
  // v3.4：来向消息落 tab——轮次模型的「消息N」。非新空工作区（有内容/已定稿）
  // =旧轮定格（已工作 X）+开新轮，消息气泡插新轮前 → 消息N+已工作N+结论N 时序
  function _subUserInto(tb, text) {
    let t = tb.t;
    // a122（双源合一，对向：v4bridge user 行同款）：子 feed 的 user 增量
    // （CLI 包装形文本）可能先到并已建轮插泡——原文队列后到时 60 字包含
    // 比对命中即跳过，不再二次切轮/插泡（防消息重复+幽灵空轮的反向时序）
    const _h60 = String(text || '').trim().slice(0, 60);
    if (_h60 && tb.sc) {
      const _exs = tb.sc.querySelectorAll('.hg-sub-u');
      for (let _i = _exs.length - 1; _i >= 0; _i--) {
        const _ex = (_exs[_i].textContent || '').trim();
        if (_ex && _ex.indexOf(_h60) >= 0) return;
      }
    }
    // v3.4R2（复审P5 重修）：pristine=当前轮无工作行且无结论（气泡在 .h-grp 外
    // 不计）——连发消息在同一轮内累积，直到有工作事件/定稿才切新轮；
    // 旧 turns<=1 子句才是残块真驱动因子（上轮修复无效已取证）
    const pristine = t && !t.done && t.tl && !t.tl.children.length
      && !(t.concl && t.concl.children.length);
    if (!pristine) {
      if (t && !t.done) _subTlFinalizeT(tb, t, {});
      t = _subTurnNew(tb);
    }
    const ws = t.tl.closest('.h-grp');
    const u = _subUserRowEl(text);
    if (ws && ws.parentElement) ws.parentElement.insertBefore(u, ws);
    else t.tl.appendChild(u);
  }
  // v3.4：tab 头（idline）——多轮模型的固定头部，轮块由 _subTurnNew 纵排其后
  function _subPaneScaffold(tb, type, model, desc) {
    const mdl = String(model || '').split('[')[0].trim();
    const ty = _AGENT_LABEL[type] || type || '子代理';
    const idline = document.createElement('div');
    idline.className = 'hg-sub-grp hg-sub-headline';
    idline.innerHTML =
      `<div class="hg-sub-idline">` +
      `<span class="h-ava ${_hgAvaCls(ty)}">${esc(String(ty).charAt(0).toUpperCase())}</span>` +
      `<span class="hg-sub-idline-ty">${esc(ty)}</span>` +
      (mdl ? `<span class="h-mmodel">${esc(mdl)}</span>` : '') +
      `</div>`;
    tb.sc.appendChild(idline);
    tb.turns = [];
    return _subTurnNew(tb, { t0: 0, desc });
  }
  // v3.4：轮块（消息N+已工作N+结论N 的工作段）——与主会话回合同构的 .h-grp
  function _subTurnNew(tb, opts) {
    opts = opts || {};
    const wrap = document.createElement('div');
    wrap.className = 'hg-sub-grp hg-sub-turn';
    wrap.innerHTML =
      `<div class="h-grp"><div class="h-grp-proc">` +
      `<button class="h-turn-head" data-hg-subtgl="1"><span class="h-chev">▸</span>` +
      `<span class="h-turn-label">工作中 0s</span><span class="h-turn-sub"></span></button>` +
      `<div class="h-turn-body"><div class="h-tl"></div></div>` +
      `</div><div class="hg-sub-concl"></div></div>`;
    tb.sc.appendChild(wrap);
    const t = { el: wrap, sc: tb.sc,   // sc=tab 滚动容器（既有 t.sc 消费方语义不变）
      head: wrap.querySelector('.h-turn-head'),
      label: wrap.querySelector('.h-turn-label'),
      subEl: wrap.querySelector('.h-turn-sub'),
      body: wrap.querySelector('.h-turn-body'),
      tl: wrap.querySelector('.h-tl'),
      concl: wrap.querySelector('.hg-sub-concl'),
      exp: null, stats: { think: 0, tool: 0 },
      t0: opts.t0 || 0, done: false, err: false, durTxt: '' };
    if (opts.desc) t.head.title = String(opts.desc).slice(0, 200);
    tb.turns.push(t);
    tb.t = t;
    return t;
  }
  // v3.4：轮级定稿（tb+turn 直取，不依赖 tid/active 指针——切轮定格旧轮用）
  function _subTlFinalizeT(tb, t, opt) {
    if (!tb || !t || t.done) return;
    opt = opt || {};
    _subTlSegFreeze(t);
    _subTlExpBreak(t);
    t.done = true;
    t.err = !!opt.err;
    const durMs = (opt.durMs > 0) ? opt.durMs
      : (t.t0 > 0 ? Math.max(0, Date.now() - t.t0) : 0);
    t.durTxt = durMs > 0 ? _hgTurnDurTxt(durMs) : '';
    _subTlHeadPaint(t);
    // 统一修复②（实测「结论=中途文本」终局）：记录式上移——渲染时记末条
    // 正文（t._lastAsst），定稿直接取；兜底全后代查询。旧 ':scope >' 只认
    // 未折叠直接子级：设计稿两条=折叠 wrap 永远漏配，末条误取中途行
    const last = (t._lastAsst && t._lastAsst.isConnected) ? t._lastAsst
      : (t.tl ? [...t.tl.querySelectorAll('.h-msg.asst')].pop() : null);
    if (last && t.concl) t.concl.appendChild(last);
    if (t.body && t.head && t.head.dataset.userToggled !== '1') t.body.classList.add('closed');
  }
  function _subTlThinkRow(raw, durTxt) {
    const seg = document.createElement('div');
    seg.className = 'h-think-seg';
    seg.dataset.raw = String(raw || '');
    // 懒渲染三件套与主链同款（pane 委托 _histLazyFill/_histLazyDrop 处置）
    seg.dataset.hgLazy = '1';
    seg.innerHTML = '<button class="h-think-seg-head"><span class="h-chev">▸</span>' +
      '<span class="h-think-seg-name"><span style="vertical-align:-2.5px">' + ICO16.brain + '</span> 思考</span>' +
      `<span class="h-think-seg-t">${esc(durTxt || '')}</span></button>` +
      '<div class="h-think-seg-body"></div>';
    return seg;
  }
  function _subTlTextRow(text, foldable) {
    // v2.37R6+（用户实测）：长文本（派发 prompt 全文等）默认折叠——阈值
    // 500 字符或 8 行，折叠态 clip ~8 行高 + 「展开 ∨/收起 ∧」钮（20-main
    // body 委托切换 .open）。折叠纯视觉层，行数统计/cap 不受影响；回放内容
    // 重拉可重建，折叠态不持久化（默认折叠即可）。短行与实时行不受影响。
    const long = String(text || '').length > 500
      || (String(text || '').match(/\n/g) || []).length >= 8;
    if (!foldable || !long) {
      const d = document.createElement('div');
      d.className = 'h-msg asst';
      d.appendChild(mdBubble(text));
      return d;
    }
    const wrap = document.createElement('div');
    wrap.className = 'hg-sub-fold-wrap folded';
    const body = document.createElement('div');
    body.className = 'h-msg asst hg-sub-fold-body';
    body.appendChild(mdBubble(text));
    const tog = document.createElement('span');
    tog.className = 'hg-sub-fold-tog';
    tog.textContent = '展开 ∨';
    tog.title = '展开全文 / 收起';
    wrap.appendChild(body);
    wrap.appendChild(tog);
    return wrap;
  }
  function _subTlToolRow(name, hint, tuid, input) {
    const row = document.createElement('div');
    row.className = 'h-tool col';
    if (tuid) row.dataset.tuid = tuid;
    const _cfg0 = _hCfg(name);
    row.dataset.hgKind = _cfg0.kind || '';   // v3.2.31：结果回点静噪判据（diff 行成功回执不落）
    row.style.setProperty('--h-accent',
      _H_KIND_COLOR[(_H_TOOL_CFG[name] || {}).kind] || 'var(--border)');
    row.innerHTML = _subToolHeadHtml(name, String(hint || '').slice(0, 300), '', {}) +
      `<div class="h-tool-coll"></div>`;
    // v3.2.31（bug3）：Edit/MultiEdit/Write 的改动体直接进折叠体——数据源是
    // tool_use input（old_string/new_string/content，事件流/轮询镜像/回放三路
    // 同源），渲染复用主流程同厂 _toolInputBodyHtml（diffHtml 删红增绿）。
    // 此前窗格时间线行只有头行摘要，结果回点只落系统回执（「has been updated
    // successfully」），改动本体不可见。改动卡生而展开（对齐主链 v3.2.26 定调
    // 与回放路径 v3.2.25 同款）。非 diff 类工具不填（结果/输出照旧由
    // _subResult/_fillRes 落折叠体，双源不冲突）
    if (input) {
      try {
        if (_cfg0.kind === 'diff') {
          const _v = _cfg0.get ? _cfg0.get(input) : '';
          const _coll = row.querySelector('.h-tool-coll');
          if (_coll) {
            _coll.innerHTML = _toolInputBodyHtml(_cfg0, _v);
            // 用户定调：所有工具卡默认不展开（v3.2.26「生而展开」定调撤销）
          }
          _hgDiffLineMemo(row, name, input);   // v3.4.62：diff 真实行号定位存档（结果点触发）
        }
      } catch(_) {}
    }
    return row;
  }
  function _subPaneStick(sc) {
    return sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;
  }
  // 时间线落位（窗格版 _tlPlace）：explore 类 → 当前查阅组；其余 → 断组直挂
  function _subTlPlace(t, row, name, input) {
    if (!t || !t.tl) return;
    if (_hgIsExplore(name, input)) {
      if (!t.exp || !t.exp.el.isConnected) {
        _subTlExpBreak(t);
        const grpEl = document.createElement('div');
        grpEl.className = 'h-tl-grp';   // v3.2.19：生而收起（主链 _tlPlace 同款）
        grpEl.innerHTML =
          `<button class="h-tl-grp-head"><span class="h-chev">▸</span>` +
          `<span class="h-tl-grp-name"><span style="vertical-align:-2.5px">${ICO16.search}</span> 查阅</span>` +
          `<span class="h-tl-grp-sum"></span></button>` +
          `<div class="h-tl-grp-body"></div>`;
        t.tl.appendChild(grpEl);
        t.exp = { el: grpEl, sum: { search: 0, list: 0, file: 0 }, keys: {} };
      }
      // v3.2.13：同目标重复子行折叠（主链 _tlPlace 同款去重键）
      const _ek = _hgExpKey(name, input);
      if (_ek && t.exp.keys[_ek]) return;
      if (_ek) t.exp.keys[_ek] = 1;
      const body = t.exp.el.querySelector('.h-tl-grp-body');
      if (body) body.appendChild(row);
      t.exp.sum[_hgExpBucket(name, input)]++;
      const sumEl = t.exp.el.querySelector('.h-tl-grp-sum');
      if (sumEl) {
        const live = _hgExpLiveTxt(name, input);
        sumEl.textContent = live ? '· ' + live : _hgExpSumTxt(t.exp.sum);
      }
    } else {
      _subTlExpBreak(t);
      t.tl.appendChild(row);
    }
  }
  // 查阅组断组：头部定格桶汇总；未被动过则收起（主链 _tlExpFlush 同语义）
  function _subTlExpBreak(t) {
    const e = t && t.exp;
    if (!e) { if (t) t.exp = null; return; }
    t.exp = null;
    if (!e.el || !e.el.isConnected) return;
    const sumEl = e.el.querySelector('.h-tl-grp-sum');
    if (sumEl) sumEl.textContent = _hgExpSumTxt(e.sum);
    if (e.el.dataset.userToggled !== '1') e.el.classList.remove('open');
  }
  // 冻结当前开口思考段（live 时长=now−t0；主链 endThinking 的窗格对偶）
  function _subTlSegFreeze(t) {
    if (!t || !t.tl) return;
    const open = t.tl.querySelector('.h-think-seg:not([data-hg-done])');
    if (!open) return;
    open.dataset.hgDone = '1';
    const te = open.querySelector('.h-think-seg-t');
    const t0 = +(open.dataset.t0 || 0);
    // v3.3.1：<3s 不显示——同批到达算出的 0/1 秒是切片噪声不是事实
    if (te && t0) {
      const _ms = Date.now() - t0;
      te.textContent = _ms >= 3000 ? '持续了 ' + _hgTurnDurTxt(_ms) : '持续了一小会';   // v3.4.44:短思考兜底
    }
  }
  function _subTlAppendRow(t, el) {
    if (!t || !t.tl) return;
    _subTlSegFreeze(t);
    _subTlExpBreak(t);
    t.tl.appendChild(el);
    _subTlCap(t);
  }
  function _subTlAppendTool(t, name, hint, tuid, input) {
    if (!t || !t.tl) return;
    _subTlSegFreeze(t);
    const row = _subTlToolRow(name, hint, tuid, input);   // v3.2.31：input 透传（diff 改动体）
    _subTlPlace(t, row, name, input || null);
    t.stats.tool++;
    _subTlCap(t);
  }
  // v3.2.6R（审计F5）：窗格时间线上限 220 行（旧 _subCap 的 tl 版）——live
  // 长跑子代理（SSE+轮询双源镜像）无界增长会拖垮 DOM/快照。溢出从头删并
  // 置「⬆ 已省略 N 行」提示条；explore 组整组删除时 t.exp 失联由
  // _subTlPlace 的 isConnected 判据自愈重建
  function _subTlCap(t) {
    if (!t || !t.tl) return;
    // a122（用户拍板「必须全有，性能优化参考主窗口」）：v4 轮放宽到 1200
    // ——子窗格轮组与主窗同享 content-visibility（a114）+ 懒体（data-hg-lazy），
    // 离屏轮跳过布局/绘制，成本模型与主窗回合渲染一致；V3 轮维持 220 不变。
    const cap = t.v4 ? 1200 : 220;
    while (t.tl.children.length > cap) {
      const first = t.tl.firstElementChild;
      if (!first) break;
      if (first.classList.contains('hg-sub-omit')) {
        first.dataset.omitted = String((+first.dataset.omitted || 0) + 1);
        // a261：图标位换 SVG——动态计数走 DOM 构建（textContent 不吃 HTML）
        first.textContent = '';
        const _omIco = document.createElement('span');
        _omIco.style.verticalAlign = '-2.5px';
        _omIco.innerHTML = ICO16.upload;
        first.appendChild(_omIco);
        first.appendChild(document.createTextNode(` 已省略 ${first.dataset.omitted} 行`));
        const victim = first.nextElementSibling;
        if (victim) victim.remove(); else first.remove();
      } else {
        const om = document.createElement('div');
        om.className = 'hg-sub-omit';
        om.dataset.omitted = '1';
        om.innerHTML = '<span style="vertical-align:-2.5px">' + ICO16.upload + '</span> 已省略 1 行';   // a261：纯静态串装 SVG 图标
        t.tl.insertBefore(om, first);
        first.remove();
      }
    }
  }
  function _subTlHeadPaint(t) {
    if (!t || !t.label) return;
    if (t.done) {
      t.label.textContent = (t.err ? '已停止' : '已工作') + (t.durTxt ? ' ' + t.durTxt : '');
    } else {
      t.label.textContent = '工作中 ' + _hgFmtDur((Date.now() - (t.t0 || Date.now())) / 1000);
    }
    if (t.subEl) {
      const s = t.stats;
      t.subEl.textContent = (s.think ? `· ${s.think} 思考 ` : '') +
                           (s.tool ? `· ${s.tool} 工具` : '');
    }
  }
  // 定稿：头「已工作 X」、结论气泡上移根区、体默认收起（尊重手动开合）
  // v3.4：轮自身账（t.t0 起）——续派轮不再错用首轮档案的 t0/doneAt
  function _subTlFinalize(tid, opt) {
    const tb = _sub.tabs[_subTid(tid)];
    if (!tb) return;
    _subTlFinalizeT(tb, tb.t, opt);
  }
  function _subOpen(tid, type, desc, replay, silent) {
    if (!_subPaneEl) return;
    tid = _subTid(tid);   // v3.4：续派包装 id 归一——命中原 tab 直接激活，绝不另开
    if (!_sub.tabs[tid]) {
      const sc = document.createElement('div');
      sc.className = 'hg-sub-msgs'; sc.dataset.tid = tid;
      // v2.35（P1-4）：tab 带模型角标（frontmatter 预显示；实跑 model 由
      // 子代理 assistant 事件到达时覆盖并重绘）
      // v2.35.1（F2）：运行态从档案派生——已完成代理被 tab 上限逐出后经
      // _subReopen 重建，不得回到「运行中」绿点（档案缺失的兜底才视为运行）
      // v2.38：replay=true=历史回放 tab（无绿点、置灰、带「回放」徽章）
      // v3.2.6：tab 标题优先用描述（ZCode 右侧 tab 用任务短题，类型进窗格头）
      const _ag = (_HG.agents || {})[tid] || {};
      // 冷查询批3：I3 后本地续派不再有 SendMessage 型独立档案，label 溯源
      // 分支退役（跨会话协作档 desc 恒有值直用）
      const _lbType = _ag.type || type, _lbDesc = desc || _ag.desc || '';
      _sub.tabs[tid] = { label: _subTabLabel(_lbType, _lbDesc), type: _lbType, desc: _lbDesc, sc,
                         run: replay ? false : (!('done' in _ag) || !_ag.done),
                         err: !!_ag.err, replay: !!replay,
                         model: _ag.model || '', t: null, turns: [], tick: null };
      _sub.order.push(tid);
      // v3.2：上限 6 个 tab，最旧让位（目录/动态伪 tab 常驻不让位，v3.3 加豁免 __dyn__）
      if (_sub.order.filter(x => x !== _SUB_DIR && x !== _SUB_DYN).length > 6) {
        const old = _sub.order.find(x => x !== _SUB_DIR && x !== _SUB_DYN);
        if (old != null) {
          const otb = _sub.tabs[old];
          // a609（审计 D5）：被逐出的正好是当前 active 时清空，否则 active
          // 悬空——silent 分支只隐藏新 sc，残留的旧 sc 无人隐藏，窗格在
          // 下一次 restore 前会堆叠多份内容。
          if (_sub.active === old) _sub.active = null;
          // a64：被逐出 tab 的 v4 子 store 同步关（el 随 sc.remove 脱离 DOM，
          // 此后无人能按 el 匹配到它——不关=EventSource 永久泄漏连接）
          try {
            if (otb && typeof V4Main !== 'undefined' && V4Main.on() && otb.sc)
              V4Main.subClose(otb.sc);
          } catch (_) {}
          if (otb && otb.tick) { clearInterval(otb.tick); otb.tick = null; }
          _sub.order = _sub.order.filter(x => x !== old);
          if (otb && otb.sc.parentNode) otb.sc.remove();
          delete _sub.tabs[old];
        }
      }
      _subBodyEl.appendChild(sc);
      // v3.2.6：ZCode 时间线脚手架（回放 fetch 会重建；live 即刻起跑秒表）
      // v3.4：脚手架=idline+首轮（多轮模型，续派轮由 _subUserInto/_subTurnNew 追加）
      _sub.tabs[tid].t = _subPaneScaffold(_sub.tabs[tid], type, _ag.model || '', desc);
      // v3.2.30：冲 live 来向消息队列（tid 键 + 已绑 agentId 键）
      _subUserFlush(tid);
      if (_ag.taskId) _subUserFlush(_ag.taskId);
      // v4-only：定稿收口全由 v4bridge 子引擎驱动（自有 _subTick，快照整建
      // 时接管），不起 V3 tick（曾与 state.final 定稿打架，a116）。即时头画
      // 保留（对抗审 P3-1/a142）：run 态先按档案 t0 画一次头，消除首快照
      // 到达前秒表冻结在 0s 的空窗——秒表跳动由 bridge 的 _subTick 接管
      if (_sub.tabs[tid].run && _ag.t0) {
        // 二轮审6：档案 t0 才预置——miss 时保持 t0=0 让 _subRebuild 锚到
        // 首行真实 ts（v3.5.191r3 铁律：t0 缺失不编造，编造=秒表虚起算）
        _sub.tabs[tid].t.t0 = _ag.t0;
        _subTlHeadPaint(_sub.tabs[tid].t);
      }
    }
    // a605（用户实锤「切回 A 会话后子代理面板每秒自动从左往右轮换」）：
    // 后台自愈路径（_subEnsure/_subThinkPollTick 的补建）不能抢焦点——
    // 原来无条件 _subActivate，自愈循环里按 _sub.order 逐个补建 tab 时，
    // 界面就被推着 1←2←3←4 地切。silent=true 只建不激活，补建完毕后由
    // _subRestoreActive 统一认领一次（用户要求「切会话保持上次打开的子代理」）。
    if (!silent) {
      _subShow(tid); _subTabsPaint(); _subActivate(tid);
    } else {
      // a605：后台补建不切 tab（原来每个补建都 _subActivate，界面被推着
      // 1←2←3←4 轮换）。a609：但也不能只调 _subTabsPaint——那会漏掉
      // 「隐藏其它 sc / 按档位写宽度 / V4 store 焦点」三件事，审计实测出
      // 窗格内容多份堆叠、可见 tab 的 store 被 pause 等 6 条缺陷。
      // 新 tab 先隐藏，界面状态交给 _subRestoreActive 统一同步（幂等；
      // active 悬空时它也会重新认领，覆盖 D5 逐出）。
      const scc = _sub.tabs[tid] && _sub.tabs[tid].sc;
      if (scc && _sub.active && _sub.active !== tid) scc.style.display = 'none';
      _subRestoreActive();
    }
  }

  /** a605/a609：自愈补建完成后统一恢复界面状态。

      两个职责，缺一不可：
        ① active 无效（null / 指向已逐出的 tab）时重新认领——优先本会话
           上次打开的那个（用户要求「切会话保持上次打开的子代理」），
           否则 order 里第一个**真实代理** tab（不能认领伪 tab，否则窗格
           停在「会话动态」且宽度错档——审计 D4）。
        ② active 本来有效时**也要同步 chrome**：silent 补建期间 V4Main
           的 subOpen 会把焦点抢走、新 sc 也没被隐藏（审计 D1/D2）。这里
           补一次 _subSyncChrome，幂等。
  */
  function _subRestoreActive() {
    if (!_sub.active || !_sub.tabs[_sub.active]) {
      let want = null;
      try { want = (_subActiveBySid || {})[_HG.sid] || null; } catch (_) {}
      const real = _sub.order.find(t => t !== _SUB_DYN && t !== _SUB_DIR
                                       && _sub.tabs[t]);
      const target = (want && _sub.tabs[want]) ? want : (real || _sub.order[0] || null);
      if (!target) return;
      // a609（审计 D3）：a75 契约是「派发即开窗」。但有历史 active（用户
      // 上次看的就是它）时无条件恢复——这也覆盖了用户收起窗格后切走再
      // 切回的情况。只有在既没历史 active、又是用户手动收起的状态下，
      // 才尊重用户意图不弹窗。
      const paneHidden = _subPaneEl && _subPaneEl.style.display === 'none';
      if (!paneHidden || (want && _sub.tabs[want])) _subShow(target);
      _subActivate(target);
      return;
    }
    // active 有效：只同步界面状态，不动 active、不滚到底、不重绘目录
    _subSyncChrome(_sub.active);
    _subTabsPaint();
  }
  // ===== 404 窗格数据管道唯一入口（ZCode subscribe 对位）=====
  // 「开 tab→铺底→续流→定稿」一条管道全链通。此前五个触发点各管一段的
  // 隐式接力（tool_use 开壳/task_started 建档/follow 挂 tick/目录 force/
  // 自愈兜底）=374 断链事故的结构根因：没有入口拥有全链，任何一环退役
  // 下游静默断。契约：tab 不在→建壳；从未铺底且 agentId 可得→force+alive
  // 铺底（_subReplay 内起 tick+follow 续流+按档案分诊定稿）；agentId 未
  // 得（task_started 未到）→挂起，task_started 再 ensure（幂等重入）；
  // 已铺底→零动作。**新增窗格触发点一律走本函数**（蓝图纪律）
  function _subEnsure(tid) {
    if (!tid) return null;
    const k = _subTid(tid);
    const a = (typeof _hgAg === 'function' ? _hgAg(tid) : null) || (_HG.agents || {})[k] || (_HG.agents || {})[tid];
    let tb = _sub.tabs[k];
    if (!tb) {
      // silent：后台自愈补建不能抢焦点（用户实锤「切回会话后子代理面板
      // 每 2-5 秒从左往右自动轮换」，根因就是这里逐个 _subOpen 时切界面）
      _subOpen(k, (a && a.type) || 'Task', (a && a.desc) || '', undefined, true);
      tb = _sub.tabs[k];
      if (!tb) return null;
    }
    if (tb.rpN) return tb;   // 已铺底：follow 已在跑（tick 内），零动作
    const aid = (a && (a.taskId || a.agentId)) || ((_HG.tidMap || {})[tid]) || ((_HG.tidMap || {})[k]) || '';
    if (!aid) return tb;     // agentId 未得：挂起等 task_started 重入
    if (tb._ensAt && Date.now() - tb._ensAt < 3000) return tb;   // 铺底在途防重入
    tb._ensAt = Date.now();
    _subReplay(k, (a && a.type) || 'Task', (a && a.desc) || '', aid, true, true,
               true /* silent：自愈补建不抢焦点 */);
    return tb;
  }
  function _subReplay(tid, type, desc, agentId, force, alive, silent) {
    if (!_subPaneEl) return;
    const tid0 = tid;     // v3.5.191r1：归一前键留存——解析漏斗回填档案落在
                          // 包装键，归一键可能无档案，双查防活代理误判死
    tid = _subTid(tid);   // v3.4：包装 id/真实 agentId 均归一到原子代理 tab 键
    const a = (_HG.agents || {})[tid] || {};
    // v3.5.273（用户实锤「怎么变成 Task 了？还没有名？」）：desc 空时档案
    // 补名——否则 tab 落裸类型字（「Task」），活跃调研子代理看不出是谁
    // v3.5.274（严查）：双键兜底——档案可能挂在包装键 tid0（归一键无档），
    // 与下方 _a2 生死判定同款双查
    // v3.5.280：正向映射终级兜底（S0/S1 直达/档案全 miss 时保实名）
    desc = desc || a.desc || ((_hgAg(tid0) || {}).desc) || '';
    // v2.57：协作档案有 taskId（=真实 agentId，v2.52 修复转写源后可拉全量）
    // ——不再走「过程不可回看」占位（过时判定，用户实锤途中关闭再开啥也没有）；
    // 无 taskId（连真实 id 都没反查到）才维持占位
    if (a.collab && !a.taskId && !agentId) {
      _subOpen(tid, type, desc, true, silent);
      const tb0 = _sub.tabs[tid];
      if (tb0 && tb0.t && !tb0.t.sc.dataset.collabNote) {
        tb0.t.sc.dataset.collabNote = '1';
        const n0 = document.createElement('div');
        n0.className = 'hg-sub-replay-note';
        n0.textContent = '独立会话协作代理——过程不可回看，仅结论可回看';
        tb0.t.sc.appendChild(n0);
        if (a.result) {
          const c0 = document.createElement('div');
          c0.className = 'h-msg asst';
          c0.appendChild(mdBubble(a.result));
          tb0.t.concl.appendChild(c0);
        }
        tb0.t.done = true; tb0.t.durTxt = '';
        _subTlHeadPaint(tb0.t);
      }
      _sub.manual = true;
      return;
    }
    agentId = agentId || a.taskId || a.agentId || '';
    // v4.0.1（用户硬性要求「无条件能点开任意子代理」）：无 agentId 不再
    // 弹 banner 了事——所有调用方（行卡/目录/胶囊）最后都汇到这里，是
    // 「点了必有反应」的最后一道关。交回解析漏斗按 tid 挖真实 agentId。
    if (!agentId) {
      if (typeof _subResolveOpen === 'function') { _subResolveOpen(tid, type, desc); return; }
      showBanner('该子代理没有 agentId 记录，无法回放', 2600); return;
    }
    // v3.5.189（用户实锤「SendMessage 明明活着却显示成了回放」）：tab 态按
    // 档案生死分——活代理=实况 tab（原名+绿点+秒表，镜像续流跟随当前环节），
    // 已结束=回放 tab（置灰徽章）。回放拉底机制不变（运行中也拉全量打底，
    // fetch 期挡增量/完成放行既有），仅 tab 态不再误标
    // 冷查询批2：单点解析（一链一档，链式双查/链活判定退役）
    const _a2 = a.done === undefined ? (_hgAg(tid0) || {}) : a;
    const _alive = (alive === true)
      || (alive !== false && (_a2 && !_a2.done));
    _subOpen(tid, type, desc, !_alive, silent);
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (!sc) return;
    // v4 归一管线（批E→a65 重构）：数据=子投影（快照铺底+delta 实时续流），
    // 渲染=bridge 子引擎（复用本文件 subpane kit，落点只在窗格容器——绝不
    // 触碰主窗 _histRender/_hgRowAdd，「子代理内容混进主窗」结构性根治）。
    // 空快照时 bridge 自带三级兜底（/subagent_replay→未找到+档案结论）
    // ——打开必有内容（无条件显示）。fetch 回放/tick follow 在此模式下退役
    {  // v4 唯一管线：子代理数据=子投影（快照铺底+delta 续流），渲染=bridge 子引擎
      sc.dataset.replayed = agentId;
      // 全审 P2（a116）：传 conclusion 容器——原调用只传 {tid,type,desc}，
      // v4main.js:150 兜底 null → v4bridge 的两段 conclEl 渲染恒为死代码。
      // （当前结论由 _paintConcl→t.concl 承担，本传参是让两条通路同口径
      // 收敛，避免下次改动误判哪条是活的。）
      var _ctb = _sub.tabs[tid];
      V4Main.subOpen(sc, agentId, { tid: tid, type: type, desc: desc,
                                    conclEl: (_ctb && _ctb.t && _ctb.t.concl) || null });
      _sub.manual = true;
      return;
    }
  }
  /** a609：把「激活一个 tab 时必须同步的界面状态」抽出来。

      a605 的 silent 实现只做了「不调 _subActivate」，漏了它顺带承担的三件
      事，审计实测出 6 条缺陷：
        ① 隐藏其它 sc（原来其余 .hg-sub-msgs 的 display 是 undefined，
           CSS 的 display:flex 让它们全部可见 → 多份内容在窗格里堆叠）；
        ② 按激活 tab 的档位写宽度（伪 tab 窄档 / 实代理宽档）；
        ③ V4Main.subFocus（新 tab 的 store 起流，其余 pause——漏了会让
           可见 tab 的 store 被 v4bridge 的 subOpen 副作用 pause 且永不恢复，
           窗格再也收不到新内容）。
      silent 补建后调用它一次即可，不需要切 tab、不需要滚动、不需要重绘目录。
  */
  function _subSyncChrome(tid) {
    if (!tid || !_sub.tabs[tid]) return;
    _subBodyEl.querySelectorAll('.hg-sub-msgs').forEach(x =>
      x.style.display = x.dataset.tid === tid ? '' : 'none');
    _hgSubPctApply(_hgSubPctGet());
    if (typeof V4Main !== 'undefined' && V4Main.on && V4Main.on()
        && V4Main.subFocus) { try { V4Main.subFocus(tid); } catch (_) {} }
  }

  function _subActivate(tid) {
    if (!_sub.tabs[tid]) return;
    _sub.active = tid;
    _subSyncChrome(tid);
    _subTabsPaint();
    // v3.2R1(P2)：目录不贴底滚动——_subScroll 为聊天流贴底设计，目录的主
    // 内容（正在运行）在顶部，贴底会直接落到已结束长列表尾
    // v3.3：动态页同豁免——状态总览主内容也在顶部（会话状态卡）
    if (tid !== _SUB_DIR && tid !== _SUB_DYN) _subScroll(tid);
    if (tid === _SUB_DIR) _subDirPaint();   // v3.2：目录激活即重绘（数据最新）
  }
  function _subTabsPaint() {
    if (!_subTabsEl) return;
    // v3.3：动态页渲染序恒在队首（order 数组保持插入序不动——_subDrop 的
    // `_sub.active = _sub.order[0]` 兜底行为不被扰动），目录及其余 tab 照旧
    // a93T（用户定调）：伪 tab 固定顺序「状态→版本→目录」恒排最前（与创建
    // 序无关），真实代理 tab 按原 order 跟后
    const _paint = [_SUB_DYN, _SUB_DIR].filter(t => _sub.tabs[t])
      .concat(_sub.order.filter(t => _sub.tabs[t]
        && t !== _SUB_DYN && t !== _SUB_DIR));
    _subTabsEl.innerHTML = _paint.map(t => {
      const tb = _sub.tabs[t];
      const _pseu = (t === _SUB_DIR || t === _SUB_DYN);   // 伪 tab：无 dot/无 ✕/悬浮只说视图
      // v2.35（P1-4）：模型进 tab（短名+悬浮全名）；tokens 进悬浮（CLI 侧计数）
      // a93S（用户令「模型名不要在 tab 上显示」）：可见角标撤除，模型只留
      // 悬浮 tooltip（头部 idline 已有完整模型名）
      const ag = (_HG.agents || {})[t] || {};
      const mdlFull = tb.model || '';
      const ttip = _pseu ? (tb.desc || tb.label)
        : [tb.desc || tb.label,
           mdlFull ? '模型：' + mdlFull : '模型：主链模型（内置/无定义文件）',
           ag.tokens ? `用量：${ag.tokens} tokens · ${ag.toolN || 0} 次工具` : '']
          .filter(Boolean).join('\n');
      return `<div class="hg-sub-tab${t === _sub.active ? ' active' : ''}${tb.run ? ' run' : tb.err ? ' err' : ''}${tb.replay ? ' replay' : ''}${t === _SUB_DIR ? ' dir' : t === _SUB_DYN ? ' dyn' : ''}"` +
        ` data-hg-subtab="${esc(t)}" title="${esc(ttip)}">` +
        (_pseu ? `<span class="hg-sub-dir-tabico">${t === _SUB_DYN ? '◉' : '☰'}</span>` : '<span class="hg-sub-dot"></span>') + esc(tb.label) +
        (tb.replay ? `<span class="hg-sub-rp">回放</span>` : '') +
        // 窗格重设计 P1-1：单-tab ✕——hover 才浮现（CSS 控制），运行中的 tab
        // 提示「任务继续后台跑」防误触焦虑；点击走 _subDrop（tab 条委托分支）
        // v3.2：目录伪 tab 常驻无 ✕（v3.3：动态页同）
        // v3.4R2：伪 tab（动态/目录）也可单独关闭——懒建机制保证随时重开
        `<span class="hg-sub-x2" data-hg-subclose="${esc(t)}" title="${esc(tb.run ? '关闭视图（任务继续在后台跑）' : _pseu ? '关闭（点胶囊/入口随时重开）' : '关闭该 tab')}">✕</span></div>`;
    }).join('');
  }
  function _subScroll(tid) {
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (sc) sc.scrollTop = sc.scrollHeight;
  }
  function _subCap(sc) { while (sc.children.length > 200) sc.removeChild(sc.firstElementChild); }
  function _subAppend(sc, html, noCap) {   // 兜底占位路径仍在用（v3.2.6 回放主体已改时间线）
    const d = document.createElement('div');
    d.innerHTML = html;
    sc.appendChild(d.firstElementChild || d);
    if (!noCap) _subCap(sc);
  }
  function _subTlGate(kind, text) {
    // 环境气泡过滤单点（问题d 根治）：黑名单对齐 transcript.py
    // _subagent_rows_from_jsonl 的协议噪音口径；SSE 摘要与 tail 喂入共用
    const t = String(text || '').trim();
    if (!t) return false;
    if (kind === 'text') {
      if (/^#(Environment|Notes|MCP Server Instructions)\b/.test(t)) return false;
      if (/^Caveat:/.test(t)) return false;
      if (/^<system-reminder>/.test(t)) return false;
    }
    return true;
  }
  async function _subTailFeed(aid) {
    // 转写增量→窗格+摘要（agentId 键；offset 账本 subTail[agentId] 内存化，
    // 不再落段 dataset——切会话清账后首拉全量，已铺底行由查重消化一次性浪费）
    if (!aid) return;
    // 全路径排查保险丝（实测教训：372 前 size=0 致账本丢失，无账本 offset=0
    // 全量重喂=中途行 append 到时间线尾冒充结论）：tab 已有铺底行（rpN>0）
    // 而账本缺失=账本丢失形态，跳过本轮（正确性优先于实时性——最坏缺增量，
    // 绝不乱序）；无铺底行=正常首拉全量。账本由铺底成功写（j.size，371/372）
    if (!(aid in _HG.subTail)) {
      const _tbF = _sub.tabs[_subTid(aid)];
      // a79：v4 tab 放行——保险丝防的是 V3 窗格无账本全量重喂乱序；v4
      // 窗格不消费尾流（尾流只喂主窗行卡实时摘要），且 v4 铺底从不写
      // subTail 账本（a75 派发即开窗=tab 几乎总早于首次成功拉取，账本
      // 永缺=保险丝永挡=_subLivePaint 永不执行，主窗卡冻结在初始描述）
      if (_tbF && (_tbF.rpN || 0) > 0 && !(_tbF.t && _tbF.t.v4)) return;
    }
    if (_subTailBusy[aid]) return;
    _subTailBusy[aid] = true;
    const sidAt = _HG.sid;
    try {
      const off = _HG.subTail[aid] || 0;
      const r = await fetch('/api/harness/subagent_tail?sid=' + encodeURIComponent(sidAt)
        + '&agent=' + encodeURIComponent(aid) + '&offset=' + off);
      const j = await r.json();
      if (_HG.sid !== sidAt || !j.ok || !j.found) return;
      if (typeof j.offset === 'number') _HG.subTail[aid] = j.offset;
      const txt = j.text || '';
      if (!txt) return;
      for (const ln of txt.split('\n')) {
        const s = ln.trim();
        if (!s) continue;
        let o; try { o = JSON.parse(s); } catch (_) { continue; }
        if (!o || o.isMeta) continue;   // isMeta 行整行丢（F3 白名单口径）
        const blocks = o.message && o.message.content;
        if (!Array.isArray(blocks)) continue;
        if (o.type === 'user') continue;   // user 行（tool_result/text）不进摘要
        const kept = [];
        for (const blk of blocks) {
          if (!blk) continue;
          if (blk.type === 'thinking' && String(blk.thinking || '').trim()) kept.push(blk);
          else if (blk.type === 'text' && _subTlGate('text', blk.text)) kept.push(blk);
          else if (blk.type === 'tool_use' && blk.name) kept.push(blk);
        }
        // 统一修复（v3.5.374）：窗格行喂入退役（_subFeed/_subResult 不再调）
        //——窗格内容唯一更新机制=follow 链「行数比对→全量重建」，增量
        // append/账本/查重锚从正确性依赖降为冗余防线；tail 只供单行卡摘要
        // 复审#9：计数退场归 SSE 单点（sse.js 状态层）——tail+SSE 双计且展示
        // 位以 tokens 为前提、完成时 usage 权威覆写，tail 侧只留摘要
        for (const blk of kept) {
          if (blk.type === 'thinking') _subLivePaint(aid, '思考中…');
          else if (blk.type === 'text') {
            _subLivePaint(aid, '正文 · ' + String(blk.text).replace(/\s+/g, ' ').trim().slice(0, 60));
          } else {
            const inp = blk.input || {};
            const hint = inp.command || inp.file_path || inp.path || inp.pattern ||
                         inp.query || inp.description || inp.subject || inp.prompt || '';
            _subLivePaint(aid, (_hToolLabel(blk.name) || '工具') + ' · ' + String(hint).slice(0, 64));
            // 复审①：toolN 计数同退 SSE 单点（367 漏删此一处）
          }
        }
      }
    } catch (_) {}
    finally { _subTailBusy[aid] = false; }
  }
  // ===== 408 窗格三态（_subThinkPollTick 自愈判据）=====
  // final = 已定稿（终稿已收口，无需再动）
  // shell = 建了壳但从未铺底（无轮对象，或 rpN=0 未拉到转写）
  // live  = 未定稿且已铺底（tick 活着即健康，tick 死=冻死窗格需自愈）
  // none  = 无 tab（伪 tab / 已拆除）
  function _subState(tb) {
    if (!tb) return 'none';
    if (tb.t && tb.t.done) return 'final';
    // a65：v4 pane 的健康源=store 连接（bridge 自带秒表+delta 续流），无
    // V3 tick 可停——按 live 判定且不触发 tick 死自愈（下方 tick 健康条件
    // 同步放行 v4），4s ensure 重开循环构造性消失
    if (tb.t && tb.t.v4) return 'live';
    if (!tb.t) return 'shell';
    if (!tb.rpN) return 'shell';
    return 'live';
  }
  function _subThinkPollTick() {
    // v3.5.51：只读模式早退（RO 期间 agents 已清空，本 tick 无有效工作）
    if (_HG.readonly) return;
    if (!_HG.sid) return;
    // busy 门槛：busy 或任一代理在跑（协作后台代理跨回合续跑的常态时段）
    // 402 冻死窗格自愈（用户实锤「全审子代理窗格空 12h」根因）：后台 agent
    // 跨回合时 _subEnd 停 tick（call_ 形态键 _subAgRunning 解析 miss）→
    // follow 链挂 tick 同死 → 窗格冻在空壳。follow 不再依赖 tick 存活——
    // 全局轮询对所有「未定稿但 tick 已死」的 tab 补行数校对重建（有新才动
    // DOM）+复活 tick；冻死窗格 2.5s 自愈
    for (const t in _sub.tabs) {
      const tb = _sub.tabs[t];
      if (String(t).indexOf('__') === 0) continue;   // 伪 tab（动态/目录/版本）
      const st = _subState(tb);
      // a65：v4 pane 无 V3 tick——live+store 即健康（tick 死自愈只属 V3 管线）
      if (st === 'final' || st === 'none'
          || (st === 'live' && (tb.tick || (tb.t && tb.t.v4)))) continue;
      try {
        // 404/408：自愈防线走 _subEnsure（唯一入口）；shell（空壳/从未铺底）
        // 或 tick 死的 live → ensure 管（铺底+复活，内置 3s 节流）；档案
        // miss 保守不动
        const aF = _hgAg(t);
        // 421（用户重启后仍实锤「结论没出来」——现场铁证：rpl1 tab rpN=201/tlN=95
        // 但 done=false+结论空，档案早 done=420 的 _subClose 修复只护"完成信号
        // 到达时在场"的 tab，此前冻死的 live 态 tab 无人管——自愈条件
        // `!aF.done || st==='shell'` 漏了「档案已 done 但 tab 冻在 live」形态）：
        // tab 未定稿且档案在场（任何死活）→ ensure（_subReplay 按档案分诊自然
        // 定稿+终稿必达，幂等）
        if (aF && st !== 'final') _subEnsure(t);
      } catch (_) {}
    }
    // a605：自愈补建可能新建了 tab 但（silent）没有激活——补完统一认领一次，
    // 优先本会话上次打开的那个子代理。已有效 active 时直接返回，不打扰用户。
    _subRestoreActive();
    if (!_HG.busy && !_hgAgentsRunning()) return;
    const ag = _HG.agents || {};
    for (const k in ag) {
      const a = ag[k];
      if (!a || a.done || (!a.taskId && !a.agentId)) continue;
      // 喂入键恒 agentId（taskId 归一后；_subFeed/_subResult/_subLivePaint
      // 内部经 _subTid/_hgAg 解析到 tab/行卡，与档案键空间无关）
      _subTailFeed(a.taskId || a.agentId || k);
    }
  }
  function _subEnd() {                     // 回合终结：全部定格；自动来源收起窗格
    let any = false;
    for (const t in _sub.tabs) {
      const tb = _sub.tabs[t];
      tb.run = false; any = true;
      // v3.2.6：停秒表（代理后台续跑时 _subFeed 会复活）；时间线定稿留给
      // 完成信号（task_notification→_subClose）——回合 result 不等于代理完
      // v3.2.6R2（审计N1）：collab 豁免——独立会话事件流不经本会话，
      // _subFeed 复活链对它不可达（唯一续流源=轮询镜像，无 tick 复活逻辑），
      // 停了就在 result→notification 窗口内秒表冻结（可达数分钟）
      if (tb.tick) {
        const _a = (_HG.agents || {})[t];
        // v3.4R2（复审N4）：豁免扩链式续派——续派在跑时轮 2 秒表不停
        if ((_a && !_a.done && _a.collab) || _subAgRunning(t)) continue;
        clearInterval(tb.tick); tb.tick = null;   // v3.4：tick 挂 tab
      }
    }
    if (any) _subTabsPaint();
    // v2.35（P0-3）：用户手动打开的窗格不自动收——用户正在围观，收走就是
    // 「弹了出来一会又收回去了」；只有 ✕ 手动关。切会话/关 tab 清空不变。
    if (_subPaneEl && !_sub.manual) _subPaneEl.style.display = 'none';
    // 内存治理（10.7GB 事故）：回合终结=离屏历史块自动收起（丢体保壳，
    // 与用户手动折叠同机制；histAll 账无损，点开回填）
    try { if (typeof _histCollapseOffscreen === 'function') _histCollapseOffscreen(); } catch (_) {}
  }
