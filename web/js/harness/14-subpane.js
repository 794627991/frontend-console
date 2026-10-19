// harness subpane.js (v3.0 自 buildClaudeHarnessTab 拆出;v3.2.6 窗格时间线重写——ZCode 子智能体模式)
  const _sub = { tabs: {}, order: [], active: null, manual: false };
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
  const _SUB_VCS = '__vcs__';   // v3.5.117：版本页签（git/svn，24-vcs.js）
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
  function _subDynOpen() {               // 动态页伪 tab（懒建；胶囊点击的展开面）
    if (!_subPaneEl) return;
    if (!_sub.tabs[_SUB_DYN]) {
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
    }
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
    for (const tid in (_HG.agents || {})) {
      const a = _HG.agents[tid];
      // v3.5.306b（用户实锤「明明有至少一个设计一个审核的，目录啥都没有」）：
      // collab/Task 曾因「无转写可回放」退目录（v3.4.43/v3.5.163）——前提已
      // 变：v2.46R 起 task_started 修正路径回填 a.taskId=真实 agentId（转写
      // 可达），v3.5.296 起建档即补 desc 原名。有 id 可回放即放行进目录；
      // 仍无 id 的保持退出（点开必空的场景不复活）
      if (!a || a.replay) continue;
      if ((a.collab || (a.type || '') === 'Task') && !a.taskId && !a.agentId) continue;
      if (!a.done && a.desc) _runDescs.add(a.desc);
      rows.push(Object.assign({ tid }, a));
    }
    for (const a of ((_HG.dyn && _HG.dyn.agentsRpl) || [])) {
      if (a.desc && _runDescs.has(a.desc)) continue;   // v3.4.56:同名回放条目让位运行中
      if ((a.doneAt || a.t0 || 0) < _dayStart) continue;   // v3.5.147：当天闸
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
    const ended = rows.filter(r => r.done && (r.doneAt || r.t0 || 0) >= _dayStart)
      .sort((x, y) => (y.doneAt || 0) - (x.doneAt || 0)).slice(0, 50);
    return { running, ended };
  }
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
    tb.sc.innerHTML =
      `<div class="hg-sub-dir-head">子智能体目录</div>` +
      `<div class="hg-sub-dir-sec">正在运行 · ${running.length}</div>` +
      (running.length ? running.map(_subDirRowHtml).join('')
        : `<div class="hg-sub-dir-empty">没有正在运行的子智能体</div>`) +
      `<div class="hg-sub-dir-sec">已结束（今天） · ${ended.length}</div>` +
      (ended.length ? ended.map(_subDirRowHtml).join('')
        : `<div class="hg-sub-dir-empty">今天还没有已结束的子智能体</div>`);
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
    try { if (typeof _vcsEnsure === 'function') _vcsEnsure(); } catch (_) {}   // v3.5.117：版本 tab 同步懒建（不夺焦点）
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
      if (!a.agentId) { showBanner('该历史子代理无 agentId 记录，无法回放', 2600); return; }
      _subReplay('rpl:' + tid, a.type, a.desc, a.agentId);
      return;
    }
    const a = (_HG.agents || {})[tid];
    if (!a) return;
    // v3.5.160 全审F3a：幻影档案（unresolved=降级 taskId 无转写）**不分
    // done/运行**一律走解析漏斗——notification 到达即 done:true 而
    // unresolved 保留，done 分支拿包装 taskId 硬开回放=「未找到」+noreplay
    // 锁（用户实锤 b7xvfmyip 形态在已结束入口存活）
    if (a.unresolved && !a.agentId) {
      showBanner('正在定位该子代理（扫主会话转写）…', 2500);
      fetch('/api/harness/subagent_resolve?sid=' + encodeURIComponent(_HG.sid) +
            '&tid=' + encodeURIComponent(tid))
        .then(r => r.json()).then(j => {
          if (j && j.ok === true && j.kind === 'agent' && j.agentId) {
            a.unresolved = false; a.agentId = j.agentId; a.taskId = j.agentId;
            _subReplay(tid, a.type, a.desc, j.agentId, true);
          } else if (j && j.kind === 'task') {
            showBanner('这是后台命令任务（Bash 后台执行），没有子代理转写', 4000);
          } else {
            showBanner('找不到该子代理的转写记录（可能已被清理）', 4000);
          }
        }).catch(() => showBanner('子代理定位请求失败', 4000));
      return;
    }
    if (!a.done) {
      // v3.2.6（ZCode 模式）：协作代理运行中——段卡已隐、过程唯一可看面=窗格，
      // 有真实 taskId 即开全量回放+轮询镜像续流（force 重拉）；无 id 回落跳
      // 主流段锚点（数据缺失的老形态）
      if (a.collab) {
        const aid = a.taskId || a.agentId || '';
        if (aid) { _subReplay(tid, a.type, a.desc, aid, true); return; }
        // v3.2.6R（审计F4）：无真实 id——段卡已隐，跳段是 display:none 上的
        // no-op；明确告知（与 agentline 死点击 banner 同口径）
        showBanner('该协作代理无 agentId 记录，过程暂不可回看', 2600);
        return;
      }
      // v3.5.324（用户实锤「切会话再切回来，数据没了」）：运行中一律走
      // _subReopen（全量铺底+续流+归一+解析漏斗）——旧走 _subOpen 只建空壳
      // 实况 tab，SSE 仅喂切回后新到事件，切走期间的完整过程永久缺失
      _subReopen(tid);
      return;
    }
    _subReplay(tid, a.type, a.desc, a.taskId || a.agentId || '');   // 已结束 → 回放 tab（collab 分支内部自理）
  }
  function _subReset() {
    // v3.2.6：先停全部窗格秒表/目录秒表再拆档（防孤儿 interval）
    _subDirTickStop();
    for (const k in _sub.tabs) {
      const tb = _sub.tabs[k];
      if (tb && tb.tick) { clearInterval(tb.tick); tb.tick = null; }   // v3.4：tick 挂 tab
    }
    _sub.tabs = {}; _sub.order = []; _sub.active = null; _sub.manual = false;
    dynEl = null;   // v3.3：动态页 sc 随清场销毁——防渲染进游离节点（重开由 _subDynOpen 重建）
    try { if (typeof _vcsReset === 'function') _vcsReset(); } catch (_) {}   // v3.5.117：版本页 sc 同清
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
    return (a === _SUB_DYN || a === _SUB_DIR || a === _SUB_VCS)
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
    // 冷查询批2：单点解析（tabs 直配 → tidMap 得 aid → tabs[aid] →
    // tidMap 反扫）。tidMap 写点已完备（批1 I2：task_started/SendMessage/
    // collab/前台回执/镜像 aid/Sync 全写），旧三向反查/链扫描退役。
    // 反扫版覆盖「Sync 后目录行 agentId 键而 tab 还在首见 tid 键」的
    // 旧漏配形态（tidMap[t]===aid 命中即归）
    const p = String(pid || '');
    if (!p || _sub.tabs[p]) return p;
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
    const texts = t.tl ? [...t.tl.querySelectorAll(':scope > .h-msg.asst')] : [];
    const last = texts[texts.length - 1];
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
      '<span class="h-think-seg-name">🧠 思考</span>' +
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
            row.classList.add('open');
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
          `<span class="h-tl-grp-name">🔍 查阅</span>` +
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
  function _subTlAppendThink(t, raw) {
    if (!t || !t.tl) return;
    _subTlSegFreeze(t);
    // v3.4.73（用户实锤窗格内思考文本成对重复）：SSE 源（_subFeed）与轮询
    // 镜像（_subPaneMirror）双源并发喂同一 tab——旧查重锚只认回放铺底行
    // （hgRp 标），两源插入的行都不带标 → 后到源恒判「未见」再插一份=每条
    // 成对。插入前对最近 think 段做双向前缀互查（镜像=全文/SSE=分片，互为
    // 前缀）；命中即跳过。插入后打 hgRp 标供他源查重
    const _norm = s => String(s || '').replace(/\s+/g, '');
    const _n = _norm(raw);
    if (_n && [...t.tl.querySelectorAll('.h-think-seg[data-raw]')].slice(-8)
        .some(el => { const a = _norm(el.dataset.raw || '');
          return !!a && (_n.startsWith(a) || a.startsWith(_n)); }))
      return;
    // v3.2.13：思考行不再断查阅组（主链 startThinking 同款；对照 ZCode 组跨
    // 思考累积）——思考段挂组后，后续查阅继续回填进组体
    const seg = _subTlThinkRow(raw, '');
    seg.dataset.hgRp = '1';
    seg.dataset.t0 = String(_hgPrevRowAt());   // v3.3.1：起点挂上一事件时刻（自身到达恒 0 秒）
    t.tl.appendChild(seg);
    t.stats.think++;
    _subTlCap(t);
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
    while (t.tl.children.length > 220) {
      const first = t.tl.firstElementChild;
      if (!first) break;
      if (first.classList.contains('hg-sub-omit')) {
        first.dataset.omitted = String((+first.dataset.omitted || 0) + 1);
        first.textContent = `⬆ 已省略 ${first.dataset.omitted} 行`;
        const victim = first.nextElementSibling;
        if (victim) victim.remove(); else first.remove();
      } else {
        const om = document.createElement('div');
        om.className = 'hg-sub-omit';
        om.dataset.omitted = '1';
        om.textContent = '⬆ 已省略 1 行';
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
  function _subTlTickStart(tid) {
    // v3.4：tick 从轮迁到 tab（每 tab 单 interval，画活跃轮 tb.t）——切轮后
    // 新轮秒表自动接续，无需重启 interval
    const tb = _sub.tabs[tid];
    if (!tb || tb.tick) return;
    tb.tick = setInterval(() => {
      const cur = _sub.tabs[tid];
      if (!cur || cur !== tb) { clearInterval(tb.tick); tb.tick = null; return; }
      const t = cur.t;
      if (!t || t.done) return;   // 无活跃轮/已定稿——空转等待新轮
      _subTlHeadPaint(t);
      // v3.5.279（用户最后通牒「无条件」）：活代理恒定跟随——不再做断流
      // 检测/不依赖镜像记账（那些条件本身会失效）。只要档案活着：①窗格
      // 永不定稿（被误定稿即复活保持「工作中」）②每 10s 无条件拉转写，
      // 行数有增才重建（内容无变化不动 DOM 零闪烁）。镜像在喂时轮询空转
      // 兜底；镜像断了轮询就是唯一跟随通道——无论断因，永远在刷新。
      try {
        // 冷查询批2：单点解析 + 一链一档（done 即整链状态，链式判定/
        // 链环收口退役——转写终态只收本档）
        const _aF = _hgAg(cur.tid0 || tid);
        if (_aF && !_aF.done && _sub.active === tid) {
          // ① 活档案覆写定稿——「保持工作中」
          if (t.done) { t.done = false; t.durTxt = ''; _subTlHeadPaint(t); }
          // ② 无条件轮询（10s 节流；拉取在途/手动重拉期不并发）
          if (!cur.replay && !cur.followInflight
              && Date.now() - (cur.lastFollow || 0) > 10000) {
            cur.lastFollow = Date.now();
            cur.followInflight = true;
            const _aidF = _aF.taskId || _aF.agentId || '';
            if (_aidF) {
              fetch('/api/harness/subagent_replay?sid=' + encodeURIComponent(_HG.sid || '') +
                    '&agent=' + encodeURIComponent(_aidF))
                .then(r => r.json()).then(jf => {
                  cur.followInflight = false;
                  const tbF = _sub.tabs[tid];
                  if (!tbF || tbF !== cur || !jf || !jf.ok) return;
                  const _rowsF = jf.rows || [];
                  // v3.5.281（用户关切「孤儿停不下来」）：转写终态行=权威判死
                  // ——CLI 写完会话才落 k:'final'，慢任务无此行不会错杀；SSE
                  // 完成事件丢失导致的孤儿档案在此收口（done 翻转→tick 复活
                  // /轮询自然停→行卡定稿→胶囊/目录计数归位）
                  const _fin = _rowsF.length && _rowsF[_rowsF.length - 1].k === 'final'
                    ? _rowsF[_rowsF.length - 1] : null;
                  if (_fin && _aF && !_aF.done) {
                    _aF.done = true; _aF.doneAt = Date.now();
                    _aF.result = String(_fin.text || _aF.result || '').slice(0, 2000);
                    _aF.err = !!_fin.err;
                    try {
                      const _rowF = (_HG.rowById || {})[cur.tid0] || (_HG.rowById || {})[tid];
                      if (_rowF && typeof _hgAgentRowState === 'function')
                        _hgAgentRowState(cur.tid0 || tid, !!_fin.err, _aF.result);
                    } catch (_) {}
                  }
                  const nNew = _rowsF.length;
                  if (nNew > (tbF.rpN || 0)) _subReplayForce(tid);   // 有新行才重建（final 行也计入→重建后窗格自然定稿）
                }).catch(() => { cur.followInflight = false; });
            } else cur.followInflight = false;
          }
        }
      } catch (_) {}
      // 开口思考段活字时长（完成定格由 _subTlSegFreeze 收「持续了 N」）
      const open = t.tl && t.tl.querySelector('.h-think-seg:not([data-hg-done])');
      if (open) {
        const te = open.querySelector('.h-think-seg-t');
        const t0 = +(open.dataset.t0 || 0);
        if (te && t0) te.textContent = _hgTurnDurTxt(Date.now() - t0);
      }
    }, 1000);
  }
  // 定稿：头「已工作 X」、结论气泡上移根区、体默认收起（尊重手动开合）
  // v3.4：轮自身账（t.t0 起）——续派轮不再错用首轮档案的 t0/doneAt
  function _subTlFinalize(tid, opt) {
    const tb = _sub.tabs[_subTid(tid)];
    if (!tb) return;
    _subTlFinalizeT(tb, tb.t, opt);
  }
  function _subOpen(tid, type, desc, replay) {
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
      if (_sub.order.filter(x => x !== _SUB_DIR && x !== _SUB_DYN && x !== _SUB_VCS).length > 6) {
        const old = _sub.order.find(x => x !== _SUB_DIR && x !== _SUB_DYN && x !== _SUB_VCS);
        if (old != null) {
          const otb = _sub.tabs[old];
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
      if (_sub.tabs[tid].run) {
        _sub.tabs[tid].t.t0 = _ag.t0 || Date.now();
        _subTlHeadPaint(_sub.tabs[tid].t);
        _subTlTickStart(tid);
      }
    }
    _subShow(tid); _subTabsPaint(); _subActivate(tid);
  }
  const _subNoreplay = new Set();
  const _subNoReplayNote = () =>
    '<div class="hg-sub-replay-note">未找到该子代理的转写记录，历史过程不可回放</div>';
  // v3.2.6R2：运行中代理的回放重试（CLI 刷盘有延迟——fetch 早于落盘时铺底
  // 空，5s 后再拉一次；限 3 次防循环，tab 已换/已定稿/已有行即不再试）。
  // R6（审计）：计数挂 **tab 档案**（tb._retry）——retry 触发的 force 重拉会
  // 整体重建 scaffold（tb.t 换新对象），挂 t 上每轮归零、上限恒不可达
  // v3.5.278：断流自愈的强制重拉（tick 检测镜像断流时调）——force 直通
  // replayed 早退守卫，重建脚手架拉最新转写；type/desc/agentId 取自档案
  function _subReplayForce(tid) {
    const tb = _sub.tabs && _sub.tabs[tid];
    if (!tb) return;
    const a = (_HG.agents || {})[tb.tid0 || tid] || (_HG.agents || {})[tid] || {};
    const _aid = a.taskId || a.agentId || '';
    if (!_aid) return;
    _subReplay(tid, a.type || 'Task', a.desc || '', _aid, true);
  }
  function _subReplayRetry(tid, type, desc, agentId) {
    const tb = _sub.tabs[tid];
    if (!tb) return;
    tb._retry = (tb._retry || 0) + 1;
    if (tb._retry > 3) return;
    setTimeout(() => {
      const cur = _sub.tabs[tid];
      const sc = cur && cur.sc;
      if (!sc || !cur.t || cur.t.done || (cur.t.tl && cur.t.tl.children.length)) return;
      const a = (_HG.agents || {})[tid];
      if (!a || a.done) return;
      delete sc.dataset.replayed;
      _subReplay(tid, type, desc, agentId, true);
    }, 5000);
  }
  function _subReplay(tid, type, desc, agentId, force, alive) {
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
      _subOpen(tid, type, desc, true);
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
    if (!agentId) { showBanner('该子代理没有 agentId 记录，无法回放', 2600); return; }
    // v3.5.189（用户实锤「SendMessage 明明活着却显示成了回放」）：tab 态按
    // 档案生死分——活代理=实况 tab（原名+绿点+秒表，镜像续流跟随当前环节），
    // 已结束=回放 tab（置灰徽章）。回放拉底机制不变（运行中也拉全量打底，
    // fetch 期挡增量/完成放行既有），仅 tab 态不再误标
    // 冷查询批2：单点解析（一链一档，链式双查/链活判定退役）
    const _a2 = a.done === undefined ? (_hgAg(tid0) || {}) : a;
    const _alive = (alive === true)
      || (alive !== false && (_a2 && !_a2.done));
    _subOpen(tid, type, desc, !_alive);
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (!sc) return;
    if (sc.dataset.replayed === agentId && !force) { _sub.manual = true; return; }   // 已拉过
    // v3.2.6：拉取期头行给加载态（脚手架默认「工作中」对回放 tab 是误导）
    {
      const tbL = _sub.tabs[tid];
      if (tbL && tbL.t && tbL.t.label) tbL.t.label.textContent = '回放加载中…';
    }
    if (_subNoreplay.has(agentId)) {      // v2.41：已判定不可回放——直接出示结论，不再发请求
      sc.innerHTML = '';
      sc.dataset.replayed = agentId;
      _subAppend(sc, _subNoReplayNote(), true);
      // v3.5.204b（用户实锤「task 点开啥也没有」）：转写文件已被系统清理
      // 是数据事实（Temp 生命周期），但任务结论在档案——miss 时附结论
      // 气泡，点开至少看到「干了什么的结论」而非纯报错
      const _ra = (_HG.agents || {})[tid] || (_HG.agents || {})[tid0] || {};
      if (_ra.result) {
        const c = document.createElement('div');
        c.className = 'h-msg asst';
        c.appendChild(mdBubble(String(_ra.result)));
        sc.appendChild(c);
      }
      _sub.manual = true;
      return;
    }
    sc.dataset.replayed = agentId;
    _sub.manual = true;
    if (_sub.tabs[tid]) {   // v2.57：fetch 期间挡镜像增量（防污染），完成后放行
      _sub.tabs[tid].replay = true;
      _sub.tabs[tid].tid0 = tid0;   // v3.5.278：归一前键留 tab（断流自愈判档案活）
    }
    const sidAt = _HG.sid;
    fetch(`/api/harness/subagent_replay?sid=${encodeURIComponent(sidAt || '')}&agent=${encodeURIComponent(agentId)}`)
      .then(r => r.json())
      .then(j => {
        // v2.37R2（复审1）：失败路径必须清 replayed 标记并给错误文案——标记
        // 不清则重点按钮永远早退，唯一恢复=切走重切
        const _tf = _sub.tabs[tid];
        if (_tf) _tf.replay = false;   // v2.57：fetch 已收敛——放行镜像增量
        if (!j || !j.ok || _HG.sid !== sidAt) {
          const scf = _sub.tabs[tid] && _sub.tabs[tid].sc;
          if (scf) {
            delete scf.dataset.replayed;
            if (_HG.sid === sidAt) {   // 会话已切走的不动现flow（可能已属别会话窗格）
              scf.innerHTML = '';
              _subAppend(scf, `<div class="hg-sub-replay-note">${(j && j.err) ? esc('回放读取失败：' + j.err) : '回放读取失败——重新点击可重试'}</div>`, true);
            }
          }
          return;
        }
        const tb2 = _sub.tabs[tid];
        const sc2 = tb2 && tb2.sc;
        if (!sc2) return;
        tb2.rpN = (j.rows || []).length;   // v3.5.279：铺底行数基准（无条件轮询比对有新才重建）
        // v3.2.6：重建时间线脚手架（清「回放加载中」占位）
        sc2.innerHTML = '';
        // v3.4：脚手架=idline+首轮；后续 k:'user' 行切新轮（多轮回放）
        tb2.turns = [];
        let t = tb2.t = _subPaneScaffold(tb2, type, tb2.model || a.model || '', desc);   // v3.4R（全审P1）：let——user 行切轮重赋值
        const note = (txt) => {
          const n = document.createElement('div');
          n.className = 'hg-sub-replay-note';
          n.textContent = txt;
          sc2.insertBefore(n, sc2.firstChild);
        };
        if (!j.found) {
          // v2.42：后端双源（projects 旧源+新版 CLI tasks 兜底）均未命中——
          // 文件不存在是持久事实，重拉永远同结果；记住结论，重点/重开不再发请求
          // v3.2.6R2：运行中代理的转写可能只是尚未生成——不进 noreplay 锁
          // （完成后的重开要能重试），保持运行态等镜像续流
          const _runA = (_HG.agents || {})[tid];
          if (_runA && !_runA.done) {
            t.t0 = _runA.t0 || Date.now();
            _subTlHeadPaint(t);
            _subTlTickStart(tid);
            note('转写尚未生成——实况继续');
            _subReplayRetry(tid, type, desc, agentId);
            return;
          }
          _subNoreplay.add(agentId);
          t.done = true; t.durTxt = '';
          _subTlHeadPaint(t);   // v3.2.6R（审计F2）：失败分支也定稿头——不卡「工作中 0s」假态
          note('未找到该子代理的转写记录');
          return;
        }
        if (!(j.rows || []).length) {
          // v2.41R2：转写存在但无可渲染行——与「没有独立转写」是两回事，给中性
          // 文案且不进 noreplay 集（tab 重开后可重试，防误判永久锁死回放入口）
          // v3.2.6R2：运行中同理不锁不封顶——CLI 刷盘有延迟，保持运行态续流
          const _runB = (_HG.agents || {})[tid];
          if (_runB && !_runB.done) {
            t.t0 = _runB.t0 || Date.now();
            _subTlHeadPaint(t);
            _subTlTickStart(tid);
            note('转写暂无可回放内容——实况继续');
            _subReplayRetry(tid, type, desc, agentId);
            return;
          }
          t.done = true; t.durTxt = '';
          _subTlHeadPaint(t);   // v3.2.6R（审计F2）：同上
          note('转写存在但无可回放内容');
          return;
        }
        if (_sub.tabs[tid]) _sub.tabs[tid]._retry = 0;   // v3.2.6R6：铺底成功重置重试额度
        // v3.5.273（用户实锤「明明是活跃的子代理，还是回放状态？」）：活代理
        // 拉全量打底≠回放——措辞按档案生死分（旧一律「回放 · …」误导）
        // 冷查询批2：fetch 后实时单点解析（双键回退退役）
        const _aNow = _hgAg(tid) || _hgAg(tid0) || {};
        // v3.5.278（用户实锤图6「已工作45秒」）：活代理铺底后轮 t0 用档案
        // 起跑时刻——转写首行 ts 是落盘时刻（CLI 刷盘延迟），当 t0=首行 ts
        // 秒表被重置成「刚起跑」，与真实运行时长（胶囊 31 分）矛盾
        if (!_aNow.done && _aNow.t0 && t) t.t0 = _aNow.t0;
        note(_aNow.done
          ? `回放 · ${_AGENT_LABEL[type] || type} · ${j.rows.length} 条记录`
          : `实况 · 已载 ${j.rows.length} 条历史，跟随中`);
        // ---- v3.2.6：rows → 时间线（与 live 同厂行；ts 事实分级）----
        const _tsGet = r0 => (r0 && r0.ts) ? Date.parse(r0.ts) : 0;
        const pend = [];       // 开口思考段（时长=下一带 ts 行差）
        let lastTs = 0;
        const openTools = [];  // v3.3.9：并行工具 FIFO 配对队列——旧 lastTool 单槽，并行批
                               // （一条 assistant 多 tool_use + 一条 user 多 result）第二个
                               // result 必落 ↳ 孤儿行（用户实锤审核回放里的裸代码行）
        const _fillRes = (toolRow, text, err) => {
          toolRow.dataset.done = '1';
          toolRow.classList.toggle('err', !!err);
          const slots = toolRow.querySelector('.h-tslots');
          if (slots) slots.innerHTML = statusBadge(err ? 'error' : 'completed');
          const full = String(text || '').trim();
          const coll = toolRow.querySelector('.h-tool-coll');
          // v3.2.31（bug3 静噪）：diff 行改动体已在场时成功回执不落（主链
          // hideOk 同口径）；错误输出照显，无改动体的行（后端缺 input）回执照显
          const _quiet = !err && toolRow.dataset.hgKind === 'diff'
            && !!toolRow.querySelector('.h-diff');
          if (coll && full && full !== '(no content)' && !_quiet) {
            const d = document.createElement('div');
            d.className = 'h-tool-out' + (err ? ' err-txt' : '');
            d.textContent = full.length > 2000 ? full.slice(0, 2000) + '…' : full;
            coll.appendChild(d);
          }
          if (!err) _hgDiffLineFix(toolRow);   // v3.4.62：成功改盘才定位（轻审P2）；回放路文件已是改后态
        };
        for (const row of (j.rows || [])) {
          const ts = _tsGet(row);
          if (ts > 0 && !t.t0) t.t0 = ts;   // v3.4R（全审P3a）：轮 t0=本轮首行 ts（首轮 scaffold 硬编码 0）
          // v3.3.1：本行之前的行 ts——思考段起点改挂前一行（同一 assistant
          // 消息 thinking 与 tool_use 同 ts，挂自身 ts 恒 0 秒）
          const _rowPrevTs = lastTs;
          if (ts > 0) {
            for (const p of pend) {
              const te = p.seg.isConnected ? p.seg.querySelector('.h-think-seg-t') : null;
              const _dur = ts - p.ts;
              if (te) te.textContent = _dur >= 3000 ? '持续了 ' + _hgTurnDurTxt(_dur) : '持续了一小会';   // v3.4.44:短思考兜底
            }
            pend.length = 0;
            lastTs = ts;
          }
          if (row.k === 'text') {
            const el = _subTlTextRow(row.text, true);   // 回放行长文默认折叠
            // v3.2.31R（复审1·严重）：rp 镜像查重锚必须打在折叠 body 上——
            // 打在 wrap 上时 textContent 含「展开 ∨」钮文本，_subPaneMirror
            // 的 want.startsWith(got) 恒 false，重叠窗口防双份失效（>500
            // 字符文本行双份插入）。body 的 textContent=纯正文，锚语义成立
            (el.querySelector('.hg-sub-fold-body') || el).dataset.hgRp = '1';
            // v3.4.73R（复核 P5）：raw 锚同打在 body 上——SSE 侧 [data-raw]
            // 查重锚覆盖回放行（含折叠行），raw 对 raw 与 8000 截断前缀自洽
            (el.querySelector('.hg-sub-fold-body') || el).dataset.raw = String(row.text || '');
            _subTlAppendRow(t, el);
          } else if (row.k === 'user') {
            // v3.2.24（用户定调「像 ZCode 一样直接暴露，不要收进工作区」）：
            // 来向消息（派发提示/追加）不进时间线——插到工作区（.h-grp）前面，
            // 回合收起/展开都恒可见；多条按到达序竖排
            // v3.2.30：与 live 队列（_subUserQueue）双源去重——同文前缀已在
            // 场就不重复插（运行中窗格先收 live 气泡、中途 force 回放再来）
            _subTlSegFreeze(t);
            _subTlExpBreak(t);
            const _txtHead = String(row.text || '').trim().slice(0, 60);
            const _dup = [...t.sc.querySelectorAll('.hg-sub-u')].some(
              x => (x.textContent || '').trim().indexOf(_txtHead) === 0);
            if (!_dup) {
              // v3.4（D6）：多轮回放——user 行切轮：当前轮有内容则按 ts 定格
              // 「已工作」，开新轮后气泡插新轮工作区前（消息N+已工作N+结论N）
              if (t.tl && t.tl.children.length) {
                _subTlFinalizeT(tb2, t, { durMs: (ts > 0 && t.t0 > 0) ? Math.max(0, ts - t.t0) : 0 });
                t = _subTurnNew(tb2, { t0: ts || 0 });
              }
              const u = document.createElement('div');
              u.className = 'h-msg user hg-sub-u';
              u.appendChild(mdBubble(String(row.text || '').slice(0, 1200)));
              u.dataset.hgRp = '1';
              const ws = t.tl && t.tl.closest('.h-grp');
              if (ws && ws.parentElement) ws.parentElement.insertBefore(u, ws);
              else _subTlAppendRow(t, u);
            }
          } else if (row.k === 'note') {
            const n = document.createElement('div');
            n.className = 'hg-sub-replay-note';
            n.textContent = row.text || '';
            n.dataset.hgRp = '1';
            _subTlAppendRow(t, n);
          } else if (row.k === 'think') {
            const seg = _subTlThinkRow(row.text || '', '');
            seg.dataset.hgRp = '1';
            _subTlAppendRow(t, seg);
            t.stats.think++;
            // v3.3.1：起点挂上一行 ts（_rowPrevTs），自身 ts 是同消息批时刻
            if (ts > 0 || _rowPrevTs > 0)
              pend.push({ seg, ts: (_rowPrevTs > 0 && (!ts || _rowPrevTs < ts)) ? _rowPrevTs : ts });
          } else if (row.k === 'tool') {
            _subTlSegFreeze(t);
            // v3.3.9：tid 作 tuid——运行中 force 回放重建后，live 结果按 tuid 精确配对
            const tw = _subTlToolRow(row.name || '', row.hint || '', row.tid || '');
            tw.dataset.hgRp = '1';   // 铺底标——镜像增量查重锚
            tw.dataset.fp = (row.name || '') + ' ' + String(row.hint || '').slice(0, 80);
            // v3.2.25（用户实锤「历史回放看不到改动」）：Edit/Write 的输入体
            // 直接进折叠体（old→new diff / 写入内容），与主流程 live 同构
            // v3.2.26（用户实锤「要展开才能看，凭什么？」）：改动卡生而展开
            if (row.in) {
              try {
                const _cfg = _hCfg(row.name || '');
                const _v = _cfg.get ? _cfg.get(row.in) : '';
                const _coll0 = tw.querySelector('.h-tool-coll');
                if (_coll0) _coll0.innerHTML = _toolInputBodyHtml(_cfg, _v);
                tw.classList.add('open');
                _hgDiffLineMemo(tw, row.name || '', row.in);   // v3.4.62：回放 diff 行存档（try 内：edits 异常不炸整个回放，轻审P4）
              } catch(_) {}
            }
            // v3.2.6R2（审计N2）：Bash/PowerShell 的只读命令用 hint（=command
            // 摘要）合成伪 input——rows 结构无 input，聚组判定才不退化。
            // v3.2.6R3（审计残留）：row.w=后端按全量命令证明的写盘标记
            //（重定向常在尾部，120 字截断漏检）——w 行不合成伪 input，
            // _hgIsExplore(null input) 即直挂，绝不把写命令聚进查阅组
            const _pin = (row.name === 'Bash' || row.name === 'PowerShell') && !row.w
              ? { command: String(row.hint || '') } : null;
            _subTlPlace(t, tw, row.name || '', _pin);
            t.stats.tool++;
            openTools.push(tw);
          } else if (row.k === 'result') {
            const _tw = openTools.shift();
            if (_tw && _tw.isConnected && _tw.dataset.done !== '1') {
              _fillRes(_tw, row.text, row.err);
            }
            // v3.4.65（用户实锤「莫名换行文字。必须解决」）：配对失败的 result
            // 摘要不再裸落时间线顶层——孤儿 ↳ 行观感=上一行（思考/查阅头）莫名
            // 续一段代码文字。翻 v3.3.9「结果不丢」的落行承诺：截断摘要信息价值
            // ≈0，完整结果在 ▣ 回放转写里可看
          }
        }
        for (const p of pend) {
          const te = p.seg.isConnected ? p.seg.querySelector('.h-think-seg-t') : null;
          const _dur2 = lastTs - p.ts;
          if (te) te.textContent = _dur2 >= 3000 ? '持续了 ' + _hgTurnDurTxt(_dur2) : '持续了一小会';   // v3.4.44:短思考兜底
        }
        // 定稿：dur=首末行 ts 差（缺 ts 落无数字「已工作」——不编造）。
        // v3.2.6R（审计F3）：collab 运行行 force 回放=「铺底即续流」——代理
        // 未 done 不定稿（定稿会封死 _subTlFinalize 的 done 守卫：续流增量
        // 落进已收起体、秒表不复活、最终时长不含续跑段）。保持运行态：秒表
        // 即刻起跑、体保持开、task_notification 到达再正式定稿
        // v3.4（D6）：续派链上任一包装在跑=保持运行态（归一后 agents[T].done
        // 只代表首轮，旧判定会把续派中的最后一轮错误定稿）
        if (_subAgRunning(tid)) {
          t.t0 = t.t0 || Date.now();
          _subTlHeadPaint(t);
          _subTlTickStart(tid);
        } else {
          // v3.4R（全审P3b）：末轮 dur=轮自身账（lastTs−本轮 t0）——旧 tsAll
          // 全转写首末差在多轮时代入跨轮跨度+轮间空转，末轮「已工作」虚大
          const durMs = (lastTs > 0 && t.t0 > 0) ? Math.max(0, lastTs - t.t0) : 0;
          t.done = true;
          t.durTxt = durMs > 0 ? _hgTurnDurTxt(durMs) : '';
          _subTlHeadPaint(t);
          const texts = [...t.tl.querySelectorAll(':scope > .h-msg.asst')];
          const last = texts[texts.length - 1];
          if (last && t.concl) t.concl.appendChild(last);
          t.body.classList.add('closed');
        }
        _subScroll(tid);
      })
      .catch(() => {
        const _tc = _sub.tabs[tid];
        if (_tc) _tc.replay = false;   // v2.57R：网络失败路径也放行镜像（与 .then 同口径）
        const sc3 = _sub.tabs[tid] && _sub.tabs[tid].sc;
        if (sc3) {
          delete sc3.dataset.replayed;   // v2.37R2（复审1）：清标记，重点即重拉
          sc3.innerHTML = ''; _subAppend(sc3, `<div class="hg-sub-replay-note">回放拉取失败（网络）——重新点击可重试</div>`, true);
        }
      });
    _subScroll(tid);
  }
  function _subActivate(tid) {
    if (!_sub.tabs[tid]) return;
    _sub.active = tid;
    _subBodyEl.querySelectorAll('.hg-sub-msgs').forEach(x =>
      x.style.display = x.dataset.tid === tid ? '' : 'none');
    _subTabsPaint();
    _hgSubPctApply(_hgSubPctGet());   // v3.4.22：宽度按激活 tab 分档（窄/宽过渡）
    // v3.2R1(P2)：目录不贴底滚动——_subScroll 为聊天流贴底设计，目录的主
    // 内容（正在运行）在顶部，贴底会直接落到已结束长列表尾
    // v3.3：动态页同豁免——状态总览主内容也在顶部（会话状态卡）
    if (tid !== _SUB_DIR && tid !== _SUB_DYN && tid !== _SUB_VCS) _subScroll(tid);
    if (tid === _SUB_DIR) _subDirPaint();   // v3.2：目录激活即重绘（数据最新）
    if (tid === _SUB_VCS) { try { if (typeof _vcsActivate === 'function') _vcsActivate(); } catch (_) {} }
  }
  function _subTabsPaint() {
    if (!_subTabsEl) return;
    // v3.3：动态页渲染序恒在队首（order 数组保持插入序不动——_subDrop 的
    // `_sub.active = _sub.order[0]` 兜底行为不被扰动），目录及其余 tab 照旧
    const _paint = (_sub.tabs[_SUB_DYN] ? [_SUB_DYN] : [])
      .concat(_sub.order.filter(t => _sub.tabs[t] && t !== _SUB_DYN));
    _subTabsEl.innerHTML = _paint.map(t => {
      const tb = _sub.tabs[t];
      const _pseu = (t === _SUB_DIR || t === _SUB_DYN || t === _SUB_VCS);   // 伪 tab：无 dot/无 ✕/悬浮只说视图
      // v2.35（P1-4）：模型进 tab（短名+悬浮全名）；tokens 进悬浮（CLI 侧计数）
      const ag = (_HG.agents || {})[t] || {};
      const mdlFull = tb.model || '';
      const mdlShort = mdlFull.length > 14 ? mdlFull.slice(0, 13) + '…' : mdlFull;
      const ttip = _pseu ? (tb.desc || tb.label)
        : [tb.desc || tb.label,
           mdlFull ? '模型：' + mdlFull : '模型：主链模型（内置/无定义文件）',
           ag.tokens ? `用量：${ag.tokens} tokens · ${ag.toolN || 0} 次工具` : '']
          .filter(Boolean).join('\n');
      return `<div class="hg-sub-tab${t === _sub.active ? ' active' : ''}${tb.run ? ' run' : tb.err ? ' err' : ''}${tb.replay ? ' replay' : ''}${t === _SUB_DIR ? ' dir' : t === _SUB_DYN ? ' dyn' : ''}"` +
        ` data-hg-subtab="${esc(t)}" title="${esc(ttip)}">` +
        (_pseu ? `<span class="hg-sub-dir-tabico">${t === _SUB_DYN ? '◉' : t === _SUB_VCS ? '⎇' : '☰'}</span>` : '<span class="hg-sub-dot"></span>') + esc(tb.label) +
        (tb.replay ? `<span class="hg-sub-rp">回放</span>` : '') +
        (mdlShort ? `<span class="hg-sub-mdl">${esc(mdlShort)}</span>` : '') +
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
  // v3.2.6：轮询镜像增量（think/text）→ 窗格时间线行（v2.57R 的 rp 铺底
  // 前缀查重保留——回放 tab fetch 收敛放行后的重叠窗口防双份）
  function _subPaneMirror(pid, kind, text) {
    const _tbM = _sub.tabs && _sub.tabs[pid];   // v3.5.278：喂入记账（断流检测的数据源）
    if (_tbM) _tbM.lastFeed = Date.now();
    pid = _subTid(pid);   // v3.4：续派包装 id 归一
    const tb = _sub.tabs[pid];
    if (!tb || !tb.t || !text || !String(text).trim()) return;
    if (tb.replay) return;   // v2.55R：回放 tab 由 fetch 全量自建，镜像增量不得污染
    const t = tb.t;
    // v3.4R2（复审N4）：续派轮复活三件——轮询是 collab 续派唯一活况源，
    // _subEnd 已停秒表；运行态/轮 t0/tick 不在此复活，轮 2 秒表永冻结
    if (_subAgRunning(pid)) {
      if (tb.run !== true) { tb.run = true; _subTabsPaint(); }
      if (t && !t.done) t.t0 = t.t0 || Date.now();
      if (!tb.tick) _subTlTickStart(pid);
    }
    const stick = _subPaneStick(t.sc);
    const rp = [...t.tl.querySelectorAll('[data-hg-rp="1"]')].slice(-8);
    const norm = s => String(s || '').replace(/\s+/g, '');
    if (kind === 'think') {
      // 单向前缀比对（镜像=全文、rp=截断前缀）：md 截断边界落在行内标记时
      // 前缀性质可破——启发式容差
      if (rp.some(el => {
        const a = norm(el.dataset.raw || '');
        return !!a && norm(text).startsWith(a);
      }))
        return;
      _subTlAppendThink(t, text);
    } else {
      const row = _subTlTextRow(text);
      row.dataset.hgRp = '1';   // v3.4.73：镜像插入行同打标——SSE 源查重锚覆盖两源
      row.dataset.raw = String(text || '');   // v3.4.73R：raw 锚（与 SSE 分支同构，raw 对 raw 互比）
      const want = norm(row.textContent);
      if (want && rp.some(el => {
        const got = norm(el.textContent);
        return !!got && want.startsWith(got);
      }))
        return;
      _subTlAppendRow(t, row);
    }
    if (stick) _subScroll(pid);
  }
  // v3.2.6：live 窗格喂入（SSE 子代理块：thinking/text/tool_use）——全部走
  // 时间线行工厂；think 开口段活字/断组/贴底与主链同口径
  function _subFeed(parentId, blocks) {
    parentId = _subTid(parentId);   // v3.4：续派包装 id 归一（事件流按包装 id 走）
    const tb = _sub.tabs[parentId];
    if (!tb || !tb.t) return;
    const t = tb.t;
    const stick = _subPaneStick(t.sc);
    // v2.35：回合终结定格过的 tab，若对应代理其实还在跑（后台 Task 跨回合
    // 续跑），事件继续流入时恢复绿点脉冲——别让冻结态骗人；秒表一并复活
    // v3.4R（全审P2）：复活判定改链式续派运行态——归一后 agents[X].done
    // 只代表首轮，续派在跑时 tb 仍须亮运行态
    if (tb.run !== true && _subAgRunning(parentId)) {
      tb.run = true;
      _subTabsPaint();
    }
    if (tb.run && !t.done && !tb.tick) { t.t0 = t.t0 || Date.now(); _subTlTickStart(parentId); }
    for (const b of blocks) {
      if (!b) continue;
      if (b.type === 'thinking' && String(b.thinking || '').trim()) {
        _subTlAppendThink(t, b.thinking);
      } else if (b.type === 'text' && String(b.text || '').trim()) {
        // v3.4.73R（复核 P1）：text 双源查重改 raw 对 raw（行存 dataset.raw、
        // 锚取 .h-msg.asst[data-raw] 互比）——旧写法拿原始 markdown 对渲染后
        // textContent 比，md 格式差异（#/反引号/链接）恒不匹配=半修。raw 锚
        // 顺带覆盖长文折叠行（hg-sub-fold-body 孙级）；命中跳过；插入打 hgRp
        const _normT = s => String(s || '').replace(/\s+/g, '');
        const _wantT = _normT(b.text);
        const _dupT = _wantT && [...t.tl.querySelectorAll('.h-msg.asst[data-raw]')].slice(-8)
          .some(el => { const _g = _normT(el.dataset.raw || '');
            return !!_g && (_wantT.startsWith(_g) || _g.startsWith(_wantT)); });
        if (!_dupT) {
          const _rowT = _subTlTextRow(b.text);
          _rowT.dataset.hgRp = '1';
          _rowT.dataset.raw = String(b.text);
          _subTlAppendRow(t, _rowT);
        }
      } else if (b.type === 'tool_use' && b.name) {
        // v3.3.1：handback 交付——最终报告在工具 input 里不是文本块，照出工具行
        // =报告永不可见（后端转写行同口径改 text）。取 input 最长字符串字段。
        // v3.3.2R(F6)：镜像工具行（handleEvent renderToolUse 先插、
        // _subBlkAppendTool 镜像进 tl）让位摘除——报告本体替换工具壳，防双行
        if (b.name === 'SubagentHandback') {
          let _rep = '';
          for (const _v of Object.values(b.input || {}))
            if (typeof _v === 'string' && _v.length > _rep.length) _rep = _v;
          if (_rep.trim()) {
            if (b.id) {
              const _mir = t.tl.querySelector(`.h-tool[data-tuid="${CSS.escape(b.id)}"]`);
              if (_mir) _mir.remove();
            }
            _subTlAppendRow(t, _subTlTextRow(_rep));
            continue;
          }
        }
        // v2.55R：对称查重——同一事件里镜像（_subBlkAppendTool）先插、本分支
        // 后插，只查一侧必双份；两侧都查后无论谁先谁后均只落一行
        if (b.id && t.tl.querySelector(`.h-tool[data-tuid="${CSS.escape(b.id)}"]`))
          continue;
        const inp = b.input || {};
        const hint = inp.command || inp.file_path || inp.path || inp.pattern ||
                     inp.query || inp.description || inp.subject || inp.prompt || '';
        _subTlAppendTool(t, b.name, hint, b.id || '', inp);
      }
    }
    _subTlHeadPaint(t);
    if (stick) _subScroll(parentId);
  }
  // v3.2.6：工具结果回点窗格时间线（tuid 精确配对优先；miss 回退 FIFO 首个
  // 未定格行——v3.3.9 并行批口径，与回放 openTools 同源；全 miss 落孤立 ↳
  // 行——结果不丢）
  function _subResult(parentId, tr) {
    parentId = _subTid(parentId);   // v3.4：续派包装 id 归一
    const tb = _sub.tabs[parentId];
    if (!tb || !tb.t) return;
    const t = tb.t;
    const stick = _subPaneStick(t.sc);
    const full = resultText(tr).trim();
    let toolRow = tr.tool_use_id
      ? t.tl.querySelector(`.h-tool[data-tuid="${CSS.escape(tr.tool_use_id)}"]`) : null;
    if (!toolRow) {
      // v3.3.9：兜底改 FIFO 首个未定格行——并行批按完成序消费，与回放同口径
      const all = [...t.tl.querySelectorAll('.h-tool')];
      for (const el of all) {
        if (el.dataset.done !== '1') { toolRow = el; break; }
      }
    }
    if (!toolRow) {
      // v3.4.65（用户实锤「莫名换行文字」）：同回放路径——孤儿结果不落行，
      // 完整结果在 ▣ 回放转写可看（翻 v3.3.9 落行承诺）
      return;
    }
    if (toolRow.dataset.done === '1') return;
    const bad = !!tr.is_error;
    toolRow.dataset.done = '1';
    toolRow.classList.toggle('err', bad);   // v3.2.5 口径：错误只标红不自动展开
    const slots = toolRow.querySelector('.h-tslots');
    if (slots) slots.innerHTML = statusBadge(bad ? 'error' : 'completed');
    if (full && full !== '(no content)') {
      const coll = toolRow.querySelector('.h-tool-coll');
      // v3.2.31（bug3 静噪）：diff 行改动体已在场时成功回执不落（主链 hideOk
      // 同口径）；错误输出照显，无改动体的行回执照显
      const _quiet = !bad && toolRow.dataset.hgKind === 'diff'
        && !!toolRow.querySelector('.h-diff');
      if (coll && !_quiet) {
        const d = document.createElement('div');
        d.className = 'h-tool-out' + (bad ? ' err-txt' : '');
        d.textContent = full.length > 2000 ? full.slice(0, 2000) + '…' : full;
        coll.appendChild(d);
      }
    }
    if (!bad) _hgDiffLineFix(toolRow);   // v3.4.62：成功改盘才定位（轻审P2）；live 镜像路（幂等）
    if (stick) _subScroll(parentId);
  }
  function _subClose(tid, err) {
    _subBlkFinish(tid, err);  // v2.43：主 flow 段头定格（不依赖窗格 tab 存活）
    // v3.4：窗格 tab 按 _subTid 归一——包装任务的完成信号定格原子代理 tab 的活跃轮
    const tb = _sub.tabs[_subTid(tid)];
    if (!tb) return;
    tb.run = false; tb.err = !!err;
    _subTlFinalize(tid, { err });   // v3.2.6：窗格时间线定稿（已工作 X + 结论上移）
    _subTabsPaint();
  }
  function _subBlkFinish(tid, err, aidForce) {
    if (!_subBlkAdopt(tid)) return;    // 段不在（无过程行的代理/协作包装）——无事可做
    _subBlkState(tid, err);
    // 冷查询批2：单点解析（段键 tid → 档案，_hgAg 直配→aidKey→tidMap）
    const _a = (typeof _hgAg === 'function' ? _hgAg(tid) : null) || {};
    // v2.46R（P4）：档案 taskId 优先——续派形态下它是 peerSent 反查的真实
    // agentId，aidForce（notification.task_id）是 CLI 包装新 id；常规 Agent
    // 两者同值（v2.44 实证同源），顺序翻转零影响
    // v3.5.160 全审F3b：幻影档案（unresolved=taskId 是降级包装 id 无转写）
    // **不落 hgSubr**——可见的「▣ 回放」钮拿包装 id 直开会「未找到」+noreplay
    // 锁，且污染 S0 取证前提（hgSubr 恒真实 agentId）；unresolved 档案的
    // 跳转走 _subDirRowClick 解析漏斗
    const _aid = _a.unresolved && !_a.agentId
      ? (aidForce || '')
      : (_a.taskId || aidForce || _a.agentId || '');
    const _b = _HG.subBlk && _HG.subBlk[tid];
    if (_b && _b.head && _aid && !_b.head.dataset.hgSubr) {
      _b.head.dataset.hgSubr = _aid;
      _b.head.dataset.hgSubType = _a.type || 'Task';
      _b.head.dataset.hgSubDesc = String(_a.desc || '').slice(0, 120);
      _subBlkActsPaint(_b);   // v2.45：hgSubr 后到——「▣ 回放」钮此时才具备数据
    }
    // v2.44：思考回填——CLI 不向 stream-json 转发子代理（sidechain）thinking
    // 块（实测铁证：本会话事件缓冲主链 thinking 10/10 到达、子代理 0/146，
    // 全量躺在子代理转写 jsonl 里），实时段内永远等不到思考事件。定格且
    // agentId 在手时按转写把思考行补进段内——与历史路径同数据源（回放接口
    // _subagent_rows_for 双源），完成即完整。hgBackfill 标记防重入（多次
    // 完成信号/收尾 sweep 不会重复拉取）；段不在/无 aid 静默跳过
    // v2.46R（P2）：定格先 drain 尾部再回填——轮询已停（tick 跳过 done 段），
    // 最后一次轮询与完成信号之间新落盘的 thinking 若不补读，「段内有思考
    // 即整体跳过」的回填守卫会把它永久丢了（最后一轮 thinking 落在完成前
    // 0-2s 概率极高）。drain 到无推进后回填：轮询插过→守卫拦重复；没插过
    // →回填全量，两不误
    if (_b && _b.root && _b.body && _aid && !_b.root.dataset.hgBackfill) {
      // v2.58：续派切段——该 agentId 的活跃段已切到他段时，本段（旧轮）不得
      // 再发起 drain（共享账本的增量字节属于新段，灌进来=串段）
      if ((_HG.subTailSeg || {})[_aid] && (_HG.subTailSeg || {})[_aid] !== tid) {
        _b.root.dataset.hgBackfill = '1';   // 占位防重复判定，不发起
      } else {
        _b.root.dataset.hgBackfill = '1';
        _subTailDrainThenBackfill(tid, _aid);
      }
    }
    // v2.47（需求2）：协作段连包装 id 都没有（task_started 事件缺 task_id 且
    // peerSent 未命中）——回填无从发起，直接占位，不空壳
    else if (_b && _b.root && !_aid && _b.root.dataset.hgCollab === '1')
      _subCollabNoTranscriptNote(tid);
  }
  async function _subBlkBackfill(tid, aid) {
    const sidAt = _HG.sid;
    try {
      const r = await fetch('/api/harness/subagent_replay?sid=' + encodeURIComponent(sidAt)
        + '&agent=' + encodeURIComponent(aid));
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return;
      // v2.47（需求2）：协作段三源全 miss（确实无独立落盘）——段体放
      // 「该协作无独立转写」占位，不空壳卡死；真实子代理 miss（旧会话/已
      // 清理）维持原静默（有段内实时行撑着，不冒充断档）
      if (!j.found) { _subCollabNoTranscriptNote(tid); return; }
      _subBlkMergeThinks(tid, j.rows || []);
    } catch(_) {}
  }
  function _subCollabNoTranscriptNote(tid) {
    const b = _HG.subBlk && _HG.subBlk[tid];
    if (!b || !b.root || !b.body || b.root.dataset.hgCollab !== '1'
        || b.root.dataset.hgCollabNote === '1') return;
    b.root.dataset.hgCollabNote = '1';
    if (b.body.querySelectorAll('.h-think-seg, .h-tool, .h-tool-res, .h-msg, .h-subblock-note').length)
      return;   // 轮询喂过/占位已在——不叠
    const n = document.createElement('div');
    n.className = 'h-subblock-note';
    n.textContent = '（该协作无独立转写——CLI 未落盘其会话，过程不可围观；完成状态以段头为准）';
    b.body.appendChild(n);
  }
  function _subBlkMergeThinks(tid, rows) {
    const b = _HG.subBlk && _HG.subBlk[tid];
    if (!b || !b.body || !b.root.isConnected) return;
    // v2.53：text 气泡同回填（用户定调段内与主会话一致——思考+工具+消息）
    if (!rows.some(r => r && (r.k === 'think' || r.k === 'text') && String(r.text || '').trim())) return;
    if (b.body.querySelectorAll('.h-think-seg').length) return;
    _subSecNormalize(b);   // 旧快照遗留布局先归节（回填只认节结构）
    // 边界映射预备：段内气泡序 / replay text 序（头区|尾区）
    const bubbles = [...b.body.children].filter(el => el.classList.contains('h-msg'));
    const B = bubbles.length;
    const noteAt = rows.findIndex(r => r && r.k === 'note');
    const isTailRow = i => noteAt >= 0 && i > noteAt;
    const textIdx = rows.map((r, i) => (r && r.k === 'text' && !isTailRow(i)) ? 0
      : (r && r.k === 'text' ? 1 : -1));   // 0=头区 text 1=尾区 text
    const headTextN = textIdx.filter(x => x === 0).length;
    const tailTextN = textIdx.filter(x => x === 1).length;
    // replay text 序号（全区连续编号）→ 段内气泡下标
    const ordToBubble = o => {
      if (o < 0) return -1;
      if (o < headTextN) return Math.min(o, Math.max(0, B - 1));          // 头区恒等
      return Math.max(0, B - tailTextN + (o - headTextN));                // 尾区对齐尾部
    };
    // 每行右侧最近 text 的全区序号（-1=右侧再无 text）
    const nextOrd = new Array(rows.length).fill(-1);
    {
      let acc = -1;
      let seen = headTextN + tailTextN;
      for (let i = rows.length - 1; i >= 0; i--) {
        nextOrd[i] = acc;
        if (textIdx[i] >= 0) { seen--; acc = seen; }
      }
    }
    // 目标节：边界气泡之前的最近节。v2.48R（复审 P1）：回走必须以 text 气泡
    // （及段内 note——同类的位置边界）为停点——旧实现一路回穿中间气泡落到
    // 任意更早的节，中段纯思考区间（两气泡间无节）的回填思考会呈现到前一张
    // 气泡之前=时序颠倒（reviewer shim 三形态实锤）。撞气泡/到头=该气泡前
    // 就地新建节；紧邻前节（气泡前一个就是节）照常命中，不多建
    const secBefore = bubble => {
      let el = bubble.previousElementSibling;
      while (el && !el.classList.contains('h-subsec')
             && !el.classList.contains('h-msg')
             && !el.classList.contains('h-subblock-note')) el = el.previousElementSibling;
      if (el && el.classList.contains('h-subsec')) return el;
      const sec = document.createElement('div');
      sec.className = 'h-subsec';
      b.body.insertBefore(sec, bubble);
      return sec;
    };
    // 末节=body 尾部的节。v2.48R：旧实现取「最后一个节」——段尾是气泡时
    // （常态：最终报告收尾）尾随思考会被塞进气泡前的节=呈现先于最终文本
    // （时序颠倒的第三形态）。尾非节则尾建（尾随思考的时序在最后一条
    // text 之后，本就该有独立尾节）
    const lastSec = () => {
      const last = b.body.lastElementChild;
      if (last && last.classList.contains('h-subsec')) return last;
      const sec = document.createElement('div');
      sec.className = 'h-subsec';
      b.body.appendChild(sec);
      return sec;
    };
    rows.forEach((r, i) => {
      if (!r || !String(r.text || '').trim()) return;
      const bi = ordToBubble(nextOrd[i]);
      // v2.53：text 行回填成气泡（与实时 _subText 同构），插在其右侧边界
      // 气泡前（时序位）；与轮询双源防重——归一文本已在段内任一气泡即跳过
      if (r.k === 'text') {
        const norm = s => String(s || '').replace(/\s+/g, '');
        const want = norm(r.text);
        if (!want) return;
        if ([...b.body.querySelectorAll('.h-msg.sub')]
            .some(el => norm(el.textContent) === want)) return;
        const d = document.createElement('div');
        d.className = 'h-msg asst sub';
        d.appendChild(mdBubble(r.text));
        if (bi >= 0 && bi < B && bubbles[bi]) b.body.insertBefore(d, bubbles[bi]);
        else b.body.appendChild(d);
        return;
      }
      if (r.k !== 'think') return;
      const sec = (bi >= 0 && bi < B && bubbles[bi]) ? secBefore(bubbles[bi]) : lastSec();
      const dr = _subSecDrawer(sec, 'think');
      const seg = _subThinkShell(false);
      seg.dataset.raw = String(r.text);
      seg.dataset.hgLazy = '1';
      dr.querySelector('.h-drawer-body').appendChild(seg);
      _subSecCount(sec);
    });
    // note 省略行随回填落段尾（与回放窗格口径一致）
    if (noteAt >= 0 && rows[noteAt] && rows[noteAt].text) {
      const nEl = document.createElement('div');
      nEl.className = 'h-subblock-note';
      nEl.textContent = String(rows[noteAt].text);
      b.body.appendChild(nEl);
    }
  }
  const _subTailBusy = {}; // agentId → 拉取在途标记（防 2s 内重入叠请求）
  const _subTailDead = {}; // agentId → 停喂标记（无账本且重插风险行已在段体——
  function _subFullFeedTid(tid) {
    const a = (_HG.agents || {})[tid];
    if (a) return !!(a.collab && (_HG.peerSent || {})[tid]);
    const b = _HG.subBlk && _HG.subBlk[tid];
    return !!(b && b.root && b.root.dataset.hgFullfeed === '1');
  }
  function _subThinkPollTick() {
    // v3.5.51（designer B2）：只读模式早退——_subCollabDomPoll 会扫 RO flow
    // 的协作段并把主会话在跑代理的 agentId 标 _subTailDead（退出后停喂增量）；
    // RO 期间 agents 已被清空，本 tick 本就无有效工作
    if (_HG.readonly) return;
    if (!_HG.sid) return;
    // v2.47（需求2）：协作段 DOM 兜底扫描先于 busy 门槛——切会话往返后
    // agents 档案已清（task_started 不重放）而协作代理还在后台跑，且那正是
    // 主流空闲（!busy）的常态时段，放门槛后面会被饿死；扫描本身只是一次
    // querySelectorAll（无协作段=零成本）
    _subCollabDomPoll();
    // v2.47（需求2）：busy 门槛放宽为「busy 或任一代理在跑」——协作包装
    // 后台执行，主回合 result 后 busy 已 false 而任务仍在跑；纯空闲（无在跑
    // 代理）仍零请求
    if (!_HG.busy && !_hgAgentsRunning()) return;
    const ag = _HG.agents || {};
    for (const tid in ag) {
      const a = ag[tid];
      // v2.47：collab 不再一票跳过——段已建（需求2）、taskId=peerSent 反查
      // 的真实 id（P4），转写三源可增量读
      if (!a || a.done || !a.taskId) continue;
      // v2.58：续派切段——该 agentId 的增量喂给**当前活跃段**（subTailSeg
      // 映射在 SendMessage 派发时切到新段），旧段即使档案未 done 也不再吃
      // 内容（用户实锤「续审内容跑回第一个审计段」）
      // subagent-registry F3（全审）：Sync 后遍历键=agentId 而首轮 Task 无
      // subTailSeg 映射——旧兜底 tgt=键本身会让 _subBlkGet(aid) 新建第二张
      // 段卡（原段冻结断流）。改按条目 tids 链找在场段；全 miss 才落键
      const _tgtSeg = (_HG.subTailSeg || {})[a.taskId]
        || ((a.tids || []).find(t => _HG.subBlk && _HG.subBlk[t]
              && _HG.subBlk[t].root && _HG.subBlk[t].root.isConnected
              && !_HG.subBlk[t].root.classList.contains('done')))
        || tid;
      const tgt = _tgtSeg;
      const b = _HG.subBlk && _HG.subBlk[tgt];
      if (!b || !b.root || !b.root.isConnected || b.root.classList.contains('done')) {
        // v3.5.127（用户实锤「切会话回来子代理段变回放定格不刷新」）：协作段
        // 有 _subCollabDomPoll 的 DOM 兜底认回，普通段没有对等物——切走时
        // _subReset 清了 subBlk 映射，主循环空查全跳过=段定格。补对称认回：
        // _subBlkGet 从快照 DOM 认回段（t0 从段头「运行中 Ns」还原+秒表复活）
        const bb = _subBlkGet(tgt);
        if (!bb || !bb.root || !bb.root.isConnected || bb.root.classList.contains('done')) continue;
      }
      _subTailFetch(tgt, a.taskId, _subFullFeedTid(tgt));
    }
  }
  function _subCollabDomPoll() {
    _hgFlow.querySelectorAll('.h-subblock[data-hg-collab]:not(.done)').forEach(el => {
      const pid = el.dataset.hgSubblock;
      const hd = el.querySelector('.h-subblock-head');
      const aid = hd && hd.dataset.hgSubr;
      if (!pid || !aid || !el.isConnected) return;
      // v2.58：续派切段——映射指向他段时本段已让位，不得再吃共享账本增量
      //（否则同一 agentId 的内容被拆进新旧两段）
      if ((_HG.subTailSeg || {})[aid] && (_HG.subTailSeg || {})[aid] !== pid) return;
      // 走 _subBlkGet（非 _subBlkAdopt）——认回分支连秒表一起复活（t0 从段头
      // 「运行中 Ns」还原）；段在本循环刚查到且仍在流（isConnected 双保险），
      // adopt 必中、不会走到新建分支
      const b = _subBlkGet(pid);
      if (!b) return;
      _subTailFetch(pid, aid, true);
    });
  }
  async function _subTailFetch(tid, aid, fullFeed) {
    if (_subTailBusy[aid]) return;
    if (_subTailDead[aid]) return;   // 已判定消费位不可知——不重读（见下）
    _subTailBusy[aid] = true;
    const sidAt = _HG.sid;
    try {
      // v2.47R（复审1）：offset 账本自愈下沉到消费点——切会话往返 subTail 清账
      // 后，完成信号（通知重放）可能先于下一轮 tick 的兜底扫描直达 drain，
      // 从 0 全量重读会把段内已插行整体双份插入。就地按段 dataset 的快照续
      // 读位（hgTailOff）种账，不依赖轮询节拍。无续读位时的停喂判据按消费形
      // 态收口（防误伤新段——SSE 先喂了行、轮询尚未起跑是常态）：
      // · think+text（真实/误杀代理，v2.54R）：段内已有思考行或消息气泡
      //   即停——两者只可能来自轮询/回填（SSE 不转发子代理 thinking/text），
      //   有行无账=旧版喂过账丢了，重读必重插；tool 行不经本路重插，不拦
      // · fullFeed（真 SendMessage 协作）：段内有任意过程行即停——独立会话
      //   行只能来自本轮询自喂，有行无账=旧版喂过，全量重读必整体重插
      if (!(aid in _HG.subTail)) {
        const _sb = _HG.subBlk && _HG.subBlk[tid];
        const _offDs = _sb && _sb.root && +_sb.root.dataset.hgTailOff;
        if (_offDs > 0) _HG.subTail[aid] = _offDs;
        else {
          const _bd = _sb && _sb.body;
          const fedAlready = fullFeed
            ? (_bd && _bd.querySelectorAll('.h-think-seg, .h-tool, .h-tool-res, .h-msg, .h-subblock-note').length)
            : (_bd && _bd.querySelectorAll('.h-think-seg, .h-msg.sub').length);
            // v2.54R：非 fullFeed 现在也喂 text（.h-msg.sub）——「有行无账」
            // 守卫必须把它算进去，否则 offset 账丢后从 0 重读会整体双份
          if (fedAlready) { _subTailDead[aid] = true; return; }
          _HG.subTail[aid] = 0;
        }
      }
      const off = _HG.subTail[aid] || 0;
      const r = await fetch('/api/harness/subagent_tail?sid=' + encodeURIComponent(sidAt)
        + '&agent=' + encodeURIComponent(aid) + '&offset=' + off);
      const j = await r.json();
      if (_HG.sid !== sidAt || !j.ok || !j.found) return;   // 切走/无转写：下轮再试
      if (typeof j.offset === 'number') {
        _HG.subTail[aid] = j.offset;
        // v2.47：已消费 offset 落段 dataset——随 innerHTML 快照携带，切会话
        // 往返 subTail 重置后 DOM 兜底扫描按它续读（从 0 重读=已插内容双份）
        const _b = _HG.subBlk && _HG.subBlk[tid];
        if (_b && _b.root && _b.root.isConnected) _b.root.dataset.hgTailOff = String(j.offset);
      }
      const txt = j.text || '';
      if (!txt) return;
      // 解析新增完整行：真实子代理取 thinking + text（v2.53 用户定调：段内
      // 必须与主会话一致有消息气泡——实测现行 CLI 的 SSE 已不转发子代理
      // text 事件，轮询是文本唯一来源；_subText 自带段尾同文去重防双份）；
      // 协作段 fullFeed 全喂（独立会话无事件流，轮询是唯一源）
      const lines = txt.split('\n');
      for (const ln of lines) {
        const s = ln.trim();
        if (!s) continue;
        let o; try { o = JSON.parse(s); } catch(_) { continue; }
        const blocks = o && o.message && o.message.content;
        if (!Array.isArray(blocks)) continue;
        for (const blk of blocks) {
          if (!blk) continue;
          if (blk.type === 'thinking' && String(blk.thinking || '').trim())
            _subThink(tid, blk.thinking, true);
          else if (blk.type === 'text' && String(blk.text || '').trim())
            _subText(tid, blk.text, true);
          else if (fullFeed && blk.type === 'tool_use' && blk.name) {
            // v3.3.1：handback 报告按正文入段（与后端转写行/窗格 _subFeed 同口径）
            if (blk.name === 'SubagentHandback') {
              let _rp = '';
              for (const _v of Object.values(blk.input || {}))
                if (typeof _v === 'string' && _v.length > _rp.length) _rp = _v;
              if (_rp.trim()) { _subText(tid, _rp, true); continue; }
            }
            renderToolUse(blk, true, tid);
          }
          else if (fullFeed && blk.type === 'tool_result' && blk.tool_use_id)
            _subToolResult(tid, blk);
        }
      }
    } catch(_) {}
    finally { _subTailBusy[aid] = false; }
  }
  async function _subTailDrainThenBackfill(tid, aid) {
    const sidAt = _HG.sid;
    // v2.47（需求2）：协作段 drain 也全喂——最后一次轮询与完成信号之间新
    // 落盘的 text/tool 行不补读就永久丢（与 P2 思考 drain 同理）
    const _ff = _subFullFeedTid(tid);
    try {
      for (let k = 0; k < 6; k++) {
        let wait = 0;
        while (_subTailBusy[aid] && wait < 3000) {
          await new Promise(r => setTimeout(r, 120)); wait += 120;
        }
        if (_HG.sid !== sidAt) return;   // 会话已切走：段随快照冻结，回填也弃
        const off0 = _HG.subTail[aid] || 0;
        await _subTailFetch(tid, aid, _ff);
        if ((_HG.subTail[aid] || 0) <= off0) break;   // 无推进=已到文件尾
      }
    } catch(_) {}
    _subBlkBackfill(tid, aid);
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
  }
