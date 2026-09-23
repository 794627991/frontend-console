// harness panel.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function _hgDyn() {
    return _HG.dyn || (_HG.dyn = { acts: [], turns: [], turnN: 0, turnTools: 0,
      todoSeen: {}, todoRowId: null, agentsRpl: [] });
  }
  function renderSideStatus() {          // 事件驱动刷新入口（旧名保留：事件流调用点零改动）
    if (!dynEl || _dynRaf) return;
    _dynRaf = requestAnimationFrame(() => {
      _dynRaf = 0; _hgDynRender();
      // v3.2R1(P2)：目录重绘并入同一 rAF——原先每个事件同步全量重建目录
      // innerHTML，事件密集时 mousedown/mouseup 之间行按钮被替换、点击落空；
      // 异常记 console（不静默吞）
      try { _subDirPaint(); } catch (e) { console.error('[hg-sub-dir] 目录刷新异常', e); }
    });
  }
  function _hgDynDirty() { renderSideStatus(); }   // 别名（setBusy/_hgDrawCtxRing 调；function 声明无 TDZ）
  const _ROLE_AGENTS = new Set(['executor', 'coder', 'dev', 'reviewer', 'designer']);
  function _isCollabWrap(type, bg) {
    return !!bg && !_ROLE_AGENTS.has(String(type || ''));
  }
  function _hgAgentsRunning() {          // 运行中子代理（Task 已起、未收到完成信号）
    return Object.values(_HG.agents || {}).some(a => !a.done);
  }
  function _hgPeerLines() {              // 协作转交线（已转交/识图转交，dataset 派生）
    return [..._hgFlow.querySelectorAll('.h-switch[data-peer]')];
  }
  function _hgPeerPending() {            // 还有未回传的协作等待（任意一条未定格）
    // v2.37R6：unknown（回合终结复核未检出回传）不算等待——否则输入框/
    // 面板永久挂「等待协作回传」
    // v2.41R2：stale（>30min 疑似残留）同步排除——与面板 C 区过滤/pill 口径
    // 统一为「stale/unknown 都不算等待」，防输入框提示与 pill 对同一状态相反
    return _hgPeerLines().some(el => !el.dataset.done
      && el.dataset.unknown !== '1' && el.dataset.stale !== '1');
  }
  function _hgInputState() {             // 输入框占位文案：运行态/子代理/协作等待联动
    let ph;
    if (_HG.busy && _hgAgentsRunning())
      ph = '子代理执行中——回复进行中，继续输入将排队，结束后自动发送';
    else if (_HG.busy)
      ph = '回复执行中——继续输入将排队，结束后自动发送';
    else if (_hgAgentsRunning())
      ph = '子代理后台执行中——现在输入将开启新回合（不影响子代理）';
    else if (_hgPeerPending())
      ph = '等待协作回传——现在输入将开启新回合（回传到达将归入其协作段）';
    else
      ph = '给 Claude 发消息，@ 引用文件，/ 选择技能 · 可直接粘贴图片';
    if (_hgInput.placeholder !== ph) _hgInput.placeholder = ph;
  }
  function _hgAgentModelsFetch() {
    if (_agentModelsTried) return;
    _agentModelsTried = true;
    fetch('/api/harness/agent_models').then(r => r.json())
      .then(j => {
        if (!j || !j.ok) return;
        _HG.agentModels = j.agents || {};
        // v2.35.1（F4）：缓存晚到时回填已开 tab——_subOpen 时缓存未就绪的
        // 条目 model 是空串，不回填则 frontmatter 预显示在 tab 永不出现
        // （实跑 model 到达的条目不动，仍以实跑为准）
        for (const t in _sub.tabs) {
          const tb = _sub.tabs[t];
          if (!tb.model) {
            const ty = tb.type || ((_HG.agents || {})[t] || {}).type || '';
            if (ty && _HG.agentModels[ty]) tb.model = _HG.agentModels[ty];
          }
        }
        renderSideStatus();              // 面板 C 区/详情卡的模型预显示跟随
        _subTabsPaint();                 // 已开 tab 的模型角标补显
      }).catch(() => { _agentModelsTried = false; });
  }
  function _hgAgentModelPre(type) {
    _hgAgentModelsFetch();
    return (_HG.agentModels && _HG.agentModels[type]) || '';
  }
  function _subReopen(tid) {
    if (!tid) return;
    if (!_sub.tabs[tid]) {
      const a = (_HG.agents || {})[tid];
      if (!a) { showBanner('历史子代理可从面板条目详情卡回放（转写数据源）', 2600); return; }
      const aid = a.taskId || a.agentId || '';
      if (a.done && aid) { _subReplay(tid, a.type, a.desc, aid); return; }
      _subOpen(tid, a.type, a.desc);
    }
    _sub.manual = true;                  // P0-3：手动来源——回合终结不自动收起，✕ 才收
    _subShow();
    _subActivate(tid);
  }
  function _subDrop(tid) {
    const tb = _sub.tabs[tid];
    if (!tb) return;
    if (tb.sc && tb.sc.parentNode) tb.sc.remove();
    delete _sub.tabs[tid];
    _sub.order = _sub.order.filter(t => t !== tid);
    if (_sub.active === tid) {
      _sub.active = _sub.order[0] || null;
      if (_sub.active) {
        const sc = _sub.tabs[_sub.active] && _sub.tabs[_sub.active].sc;
        if (sc) sc.style.display = '';
      }
    }
    _subTabsPaint();
    if (!_sub.order.length && _subPaneEl) _subPaneEl.style.display = 'none';
  }
  function _hgAgentsSweep(markErr) {     // 回合终结：在跑的子代理统一收尾（防假"运行中"）
    if (!_HG.agents) {
      // v2.43.1（R-FAIL1）：档案缺失（切会话往返重置）——按 DOM 段兜底定格
      // （重放 result/interrupted/exit 到达时档案三路全早退，段头会永久假
      // 「运行中」）。data-hg-bg 段非中断不收（后台代理跨回合续跑，与档案
      // 路径同语义——标记在段创建时从档案落 dataset，随快照携带）
      _hgFlow.querySelectorAll('.h-subblock:not(.done)').forEach(el => {
        if (!markErr && el.dataset.hgBg === '1') return;
        const pid = el.dataset.hgSubblock;
        if (pid) _subBlkFinish(pid, !!markErr);
      });
      return;
    }
    let swept = false;
    for (const id in _HG.agents) {
      const a = _HG.agents[id];
      // v2.35：后台代理（bg）在主回合 result 时不收——它还在跑，收尾信号是
      // task_notification；中断/退出（markErr）照收：进程没了，一切皆停
      if (!a.done && !(a.bg && !markErr)) {
        a.done = true; a.doneAt = Date.now();
        if (markErr) { a.err = true; a.interrupted = true; }
        _subBlkFinish(id, !!a.err);   // v2.43：主 flow 段头同步定格（防假"运行中"，bg 不收尾同档案语义）
        swept = true;
      }
    }
    if (swept) renderSideStatus();
  }
  function _hgTurnEnd(st, durMs) {       // 回合记账 ring（≤10）；dur 优先事件值（网关常缺失→本地差值）
    const d = _hgDyn();
    const dur = (durMs > 0) ? durMs : Date.now() - (_HG.actStart || Date.now());
    d.turns.push({ n: ++d.turnN, dur: Math.max(0, Math.round(dur / 1000)), st, tools: d.turnTools });
    if (d.turns.length > 10) d.turns.shift();
    d.turnTools = 0;
    renderSideStatus();
  }
  function _hgActPush(it) {              // 活动流 ring（≤20）；回放路径在调用方排除
    const d = _hgDyn();
    d.acts.push(it);
    if (d.acts.length > 20) d.acts.shift();
    renderSideStatus();
  }
  function _hgActDone(tid, st) {
    const a = ((_HG.dyn && _HG.dyn.acts) || []).find(x => x.tid === tid && !x.done);
    if (!a) return;
    a.done = true; a.doneAt = Date.now();
    a.err = (st === 'error' || st === 'denied');
    renderSideStatus();
  }
  async function _hgRolesFetch() {       // roles 只读拉取（缓存+刷面板；失败静默）
    try {
      const j = await (await fetch('/api/harness/roles')).json();
      if (j && j.ok) { _hgRolesCache = j; renderSideStatus(); }
      return j;
    } catch(_) { return null; }
  }
  function _hgCopyText(t) {
    if (!t) return;
    const p = navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject();
    p.then(() => showBanner('已复制', 1600)).catch(() => showBanner('复制失败', 2000, true));
  }
  function _hgJumpRow(tid) {             // 跳消息流工具行（只读操作，不碰快照状态机）
    const row = _HG.rowById[tid];
    if (!row || !row.isConnected) return;   // 卸载态防御（busy 中切过 tab）
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    row.classList.remove('hg-dyn-jump');
    void row.offsetWidth;                // 重启动画
    row.classList.add('hg-dyn-jump');
    setTimeout(() => row.classList.remove('hg-dyn-jump'), 1600);
  }
  function _hgAgentDetailEl(id, a) {
    const dur = a.done
      ? (a.t0 ? _hgFmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000))) : '—')
      : (a.t0 ? _hgFmtDur((Date.now() - a.t0) / 1000) + '（进行中）' : '—');
    // v2.35（P1-4）：模型行——实跑 model（子代理 assistant 事件实报）优先，
    // frontmatter 预显示兜底，都无=内置代理按 CLI 行为跑主链模型
    const mdl = a.model || (_HG.agentModels && _HG.agentModels[a.type]) || '';
    // 用量行——task_progress/task_notification 的 CLI 侧计数（total_tokens/
    // tool_uses）；网关会把 assistant.message.usage 置零（实测），不作为源
    const usageTxt = a.tokens
      ? `${(a.tokens / 1000).toFixed(1)}K tokens · ${a.toolN || 0} 次工具`
      : '';
    const d = document.createElement('div');
    d.className = 'hg-dyn-agdetail';
    d.innerHTML =
      (id && !a.replay ? `<div class="hg-dyn-kv"><span class="k">ID</span>` +
        `<span class="v mono" data-hg-copy="${esc(id)}" title="点击复制">${esc(id)}</span></div>` : '') +
      (a.replay ? '' :
        `<div class="hg-dyn-kv"><span class="k">模型</span><span class="v" title="${esc(mdl ? '实跑/frontmatter 模型' : '内置或无定义文件代理，按 CLI 行为跑主链模型')}">${esc(mdl || '主链模型')}${a.bg ? ' · 后台' : ''}</span></div>`) +
      (a.replay || !usageTxt ? '' :
        `<div class="hg-dyn-kv"><span class="k">用量</span><span class="v">${esc(usageTxt)}</span></div>`) +
      `<div class="hg-dyn-kv"><span class="k">起止</span><span class="v">` +
        `${a.t0 ? new Date(a.t0).toTimeString().slice(0, 8) : '—'} → ` +
        `${a.doneAt ? new Date(a.doneAt).toTimeString().slice(0, 8) : (a.done ? '历史' : '运行中')}</span></div>` +
      `<div class="hg-dyn-kv"><span class="k">耗时</span><span class="v">${dur}` +
        `${a.interrupted ? ' · 已中断' : a.err ? ' · 失败' : ''}</span></div>` +
      (a.desc ? `<div class="hg-dyn-agres">${esc(a.desc)}</div>` : '') +
      (a.result ? `<div class="hg-dyn-agres">${esc(a.result)}</div>` : '') +
      // v2.38：回放入口——带 agentId 的已完成代理（含历史条目）可开回放
      // 窗格（数据源=子代理转写）；协作代理只回看结论
      (a.done && !a.collab && (a.taskId || a.agentId)
        ? `<button class="hg-dyn-replay-btn" data-hg-replay="${esc(id)}"` +
          ` data-hg-replay-aid="${esc(a.taskId || a.agentId || '')}"` +
          ` data-hg-replay-type="${esc(a.type || '')}">▣ 回放该子代理过程</button>` : '') +
      (a.collab && a.result
        ? `<button class="hg-dyn-replay-btn" data-hg-replay="${esc(id)}"` +
          ` data-hg-replay-collab="1" data-hg-replay-type="${esc(a.type || '')}">▣ 回看协作结论</button>` : '');
    return d;
  }
  function _hgAgentToggle(rowEl) {       // 子代理行展开/收起详情卡（单开）
    const nxt = rowEl.nextElementSibling;
    if (nxt && nxt.classList.contains('hg-dyn-agdetail')) {
      nxt.remove();
      if (_HG.dyn) _HG.dyn.agentDetailOpen = null;
      return;
    }
    dynEl.querySelectorAll('.hg-dyn-agdetail').forEach(x => x.remove());
    const id = rowEl.dataset.hgAg || '';
    const a = (_HG.agents || {})[id]
      || ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => x.rid === id);
    if (!a) return;
    if (_HG.dyn) _HG.dyn.agentDetailOpen = id;
    rowEl.insertAdjacentElement('afterend', _hgAgentDetailEl(id, a));
  }
  function _hgDynRender() {
    if (!dynEl) return;
    for (const fn of [_dynStat, _dynTodos, _dynAgents, _dynActs, _dynTurns, _dynFiles]) {
      try { fn(); }
      catch (e) {
        // v2.37R6（C 区整栏消失②）：渲染失败降级为可见占位（区分无数据/
        // 渲染失败），不再只留 console 标记让整栏凭空蒸发
        try {
          console.error('[hg-dyn] 分区渲染异常', fn.name, e);
          // v2.39：错误文本直接上屏——WebView2 用户开不了 console，降级占位
          // 只说「详见 console」等于没有诊断信息（用户实锤无法反馈根因）
          const msg = esc(String((e && e.message) || e || '未知错误')).slice(0, 200);
          if (fn === _dynAgents) {
            const secA = _sec('agents');
            if (secA) {
              secA.hidden = false;
              const al = secA.querySelector('[data-hg-d-aglist]');
              if (al) al.innerHTML = '<div class="hg-sub-replay-note">子代理区渲染异常（已降级显示）：<b>' + msg + '</b></div>';
            }
          }
        } catch(_) {}
      }
    }
    try { _hgInputState(); } catch(_) {}   // v2.35：派生态变化连带输入框提示
  }
  function _sec(z) { return dynEl.querySelector(`[data-hg-sec="${z}"]`); }
  const _THINK_TXT = { low: '低', medium: '中', high: '高', max: '最高' };
  const _TURN_ICO = { ok: '✓', error: '✗', interrupt: '⏹', exit: '⏻' };
  const _FILE_TOOLS = ['Read', 'Edit', 'MultiEdit', 'Write', 'NotebookEdit'];
  const _hhmm = ts => new Date(ts).toTimeString().slice(0, 5);
  function _dynStat() {                  // A 会话状态：双来源口径——当前会话值(s.*)优先，无会话回退新会话参数(_HG.*)
    const sec = _sec('stat'); if (!sec) return;
    const s = _HG.sessions.find(x => x.sid === _HG.sid);
    const stEl = sec.querySelector('[data-hg-d-st]');
    const ttEl = sec.querySelector('[data-hg-d-stt]');
    // v2.35（P0-1②③）：非 busy 的「等待类」状态也算运行态——面板徽章与
    // 输入框提示同源派生（后台子代理在跑 / 协作回传未到，用户不再误判空闲）
    const agRun = _hgAgentsRunning(), peerWait = !agRun && _hgPeerPending();
    sec.classList.toggle('run', !!_HG.busy || agRun || peerWait);
    // v2.36：纯等待态（非 busy/无子代理、仅协作回传未到）状态点/秒表转「等待蓝」
    // ——与 C 区协作行/输入框提示同语义（仅类名调整，渲染逻辑零变化）
    sec.classList.toggle('wait', peerWait && !_HG.busy);
    let stTxt;
    if (_HG.compacting) stTxt = '正在压缩上下文';
    else if (_HG.busy && agRun) stTxt = '子代理执行中';
    else if (_HG.busy) stTxt = '回复中';
    else if (agRun) stTxt = '子代理后台执行中';
    else if (peerWait) stTxt = '等待协作回传';
    else if (!_HG.sid) stTxt = '新会话';
    else if (_HG.alive) stTxt = '就绪';
    else stTxt = '待命';
    stEl.textContent = stTxt;
    if (_HG.busy && _HG.actStart) {
      ttEl.dataset.t0 = _HG.actStart;
      ttEl.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - _HG.actStart) / 1000)));
    } else if (agRun) {
      // 非 busy 但子代理在跑（后台 Task）：计最早起跑的代理时长
      const t0 = Math.min(...Object.values(_HG.agents).filter(a => !a.done).map(a => a.t0 || Date.now()));
      ttEl.dataset.t0 = t0;
      ttEl.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
    } else if (peerWait) {
      const t0 = Math.min(..._hgPeerLines().filter(el => !el.dataset.done)
        .map(el => +(el.dataset.t0 || 0) || Date.now()));
      ttEl.dataset.t0 = t0;
      ttEl.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
    } else {
      delete ttEl.dataset.t0;
      const lt = (_HG.dyn && _HG.dyn.turns || []).filter(t => t.st === 'ok').pop();
      ttEl.textContent = lt ? '最近回合 ' + _hgFmtDur(lt.dur) : '';
    }
    const model = (s && s.model) || _HG.model || '';
    const think = (s && s.think) || _HG.thinkLv || null;
    const perm = (s && s.permission) || _HG.perm || 'auto';
    const cwd = (s && s.cwd) || _HG.cwd || '';
    sec.querySelector('[data-hg-d-model]').textContent = model || '—';
    sec.querySelector('[data-hg-d-model]').title = model ? '当前会话模型（chip 改的是新会话）' : '';
    sec.querySelector('[data-hg-d-think]').textContent = think ? (_THINK_TXT[think] || think) : '默认';
    sec.querySelector('[data-hg-d-perm]').textContent = perm === 'confirm' ? '每次确认' : '自动执行';
    const cw = sec.querySelector('[data-hg-d-cwd]');
    cw.textContent = cwd ? cwd.split(/[\\/]/).pop() : '~';
    cw.title = cwd || '';
    let ctxTxt = '待统计', warn = false;
    if (_HG.sid) {
      try {
        const v = JSON.parse(localStorage.getItem('hg-ctx:' + _HG.sid) || 'null');
        if (v && v.used > 0) {
          const mx = v.max || 256000;
          const pct = Math.round(v.used / mx * 100);
          ctxTxt = pct + '% · ' + (v.used / 1000).toFixed(1) + 'K/' + (mx / 1000).toFixed(0) + 'K';
          warn = pct >= 80;
        }
      } catch(_) {}
    }
    const cx = sec.querySelector('[data-hg-d-ctx]');
    cx.textContent = ctxTxt;
    cx.closest('.hg-dyn-kv').classList.toggle('warn', warn);
    const r = _hgRolesCache && _hgRolesCache.roles;
    const rEl = sec.querySelector('[data-hg-d-roles]');
    // 形态正确 + 模型名可读。/roles 响应自带 mode（strong/light）与
    // resolved（v2.53 含 designer/reviewer 各自实模型），按形态出对应角色
    // 行；两形态主会话都直干所有活——轻主力=设计者+审计者两个代理，
    // 重主力=只留审计者兜底
    const _mode = _hgRolesCache && _hgRolesCache.mode;
    const _res = (_hgRolesCache && _hgRolesCache.resolved) || {};
    if (r) {
      if (r.enabled) {
        const light = _mode === 'light';
        rEl.textContent = light ? '轻主力' : '重主力';
        rEl.title = light
          ? `轻主力模式（主会话直干所有活，点击打开配置面板）\n设计者 designer（只设计，不写代码不改文件）: ${_res.designer || _res.heavy || '…'}\n审计者 reviewer（只读对抗审核，PASS/FAIL）: ${_res.reviewer || _res.heavy || '…'}`
          : `重模型直干模式（主会话直干所有活，点击打开配置面板）\n审计兜底：单次直改超分级线自动派审计者对抗审计\n审计者: ${_res.reviewer || _res.heavy || '…'}`;
      } else {
        rEl.textContent = '关闭·直连';
        rEl.title = '直连干活（点击打开配置面板可启用三角色）';
      }
    } else rEl.textContent = '…';
  }
  function _dynTodos() {                 // B 进程（v3.1 ZCode 式重做）：分组清单——进行中 → / 待处理 ○ / 已完成 ✓，两组可折叠
    const sec = _sec('todos');
    const todos = _HG.todos || [];
    // v3.1：数据面扩容——todo 清单缺席但投影有活（回合计数/子代理）也出区
    //（「进程」的语义从 TodoWrite 清单扩为回合过程总览）
    const P = _HG.proj;
    const tt = (P && (P.status === 'running' ? P.turnTools : P.lastTurnTools)) || null;
    sec.hidden = !todos.length && !tt;
    if (sec.hidden) return;
    const d = _hgDyn();
    let html = '';
    // ---- 本回合活动计数行（投影 turnTools：N 工具 · N 搜索 · N 文件 …）----
    if (tt && tt.calls) {
      const bits = [tt.calls + ' 工具'];
      if (tt.searches) bits.push(tt.searches + ' 搜索');
      if (tt.reads) bits.push(tt.reads + ' 文件');
      if (tt.edits) bits.push(tt.edits + ' 编辑');
      if (tt.agents) bits.push(tt.agents + ' 子代理');
      html += '<div class="hg-proc-turn" title="'
        + (P.status === 'running' ? '本回合实时计数' : '上一回合计数') + '">'
        + (P.status === 'running' ? '<span class="hg-proc-live"></span>' : '')
        + esc(bits.join(' · ')) + '</div>';
    }
    if (todos.length) {
      const done = todos.filter(t => t.status === 'completed');
      const prog = todos.filter(t => t.status === 'in_progress');
      const pend = todos.filter(t => t.status !== 'completed' && t.status !== 'in_progress');
      const seen = d.todoSeen || {};
      // 折叠态：默认「已完成」收（有未完项时）、「待处理」开；点分组头切换
      if (d.procDoneOpen === undefined)
        d.procDoneOpen = !(pend.length + prog.length);
      if (d.procPendOpen === undefined) d.procPendOpen = true;
      const row = (t, st) => {
        const txt = (st === 'in_progress' && t.activeForm) ? t.activeForm : t.content;
        const ts = seen[t.content || ''];
        return `<div class="hg-proc-row ${st}" data-hg-todo title="${esc(t.content || '')}">` +
          `<span class="hg-proc-ico">${st === 'completed' ? '✓' : st === 'in_progress' ? '→' : '○'}</span>` +
          `<span class="hg-proc-tt">${esc(txt || '')}</span>` +
          (ts ? `<span class="hg-proc-ts">${_hhmm(ts)}</span>` : '') + '</div>';
      };
      if (prog.length) html += prog.map(t => row(t, 'in_progress')).join('');
      if (pend.length) html +=
        `<button class="hg-proc-grp" data-hg-proc-tgl="pend"><span class="h-chev${d.procPendOpen ? ' open' : ''}">‹</span>` +
        `<span class="hg-proc-grp-name">待处理 ${pend.length} 项</span></button>` +
        (d.procPendOpen ? pend.map(t => row(t, 'pending')).join('') : '');
      if (done.length) html +=
        `<button class="hg-proc-grp" data-hg-proc-tgl="done"><span class="h-chev${d.procDoneOpen ? ' open' : ''}">‹</span>` +
        `<span class="hg-proc-grp-name">已完成 ${done.length} 项</span></button>` +
        (d.procDoneOpen ? done.map(t => row(t, 'completed')).join('') : '');
    }
    sec.querySelector('[data-hg-d-tdone]').textContent =
      todos.length ? todos.filter(t => t.status === 'completed').length + '/' + todos.length : '';
    sec.querySelector('[data-hg-d-tbar]').style.width =
      todos.length ? (todos.filter(t => t.status === 'completed').length / todos.length * 100) + '%' : '0%';
    sec.querySelector('[data-hg-d-tlist]').innerHTML = html;
  }
  function _dynAgents() {                // C 子代理实况：运行中/60s 内完成/回放历史，点击展开
    const sec = _sec('agents');
    const list = Object.entries(_HG.agents || {}).map(([id, a]) => Object.assign({ id }, a));
    const running = list.filter(a => !a.done).sort((x, y) => x.t0 - y.t0);
    const finished = list.filter(a => a.done && Date.now() - a.doneAt < 60000).slice(-5);
    const rplAll = (_HG.dyn && _HG.dyn.agentsRpl) || [];
    // v2.39 修 TDZ：旧写法 map 回调里引用了正在初始化的 rpl 自身（rpl.length）
    // ——回调同步执行时 const 未赋值，「Cannot access 'rpl' before
    // initialization」实锤。此前 agentsRpl 恒空、回调不执行埋着不炸；v2.38
    // 历史回放填充后面板 C 区必炸降级。tail 中转替代自引用，rid 编号语义不变。
    const rplTail = rplAll.slice(-3);
    // v2.40 修断链：rid 必须写回存档对象。旧写法只把 rid 合进渲染副本
    // （Object.assign({rid...}, a)），存档条目本身没有 rid——条目点击走
    // _hgAgentToggle 时按 data-hg-ag 里的 rid 去 agentsRpl.find(x =>
    // x.rid === id)，存档无 rid 恒 miss → if(!a) return 静默无反应，详情
    // 卡（含「回放该子代理过程」按钮）整链不可达：副本上的 rid 是无根之
    // 木。这里给无 rid 的存档条目补发持久 rid 并写回存档（mutate 的是我
    // 们自己的数据对象，安全）：_HG.rplSeq 模块内自增发号，唯一且跨渲染
    // 稳定（数组 shift 后同条目 rid 不漂移），已有 rid 不重发；渲染副本
    // 改 Object.assign({}, a) 平移继承，rid 语义从「数组位置」变「持久
    // 序号」，rid 值本身无展示/无持久化消费，语义安全。
    rplTail.forEach(a => {
      if (!a.rid) a.rid = 'rpl' + ((_HG.rplSeq = (_HG.rplSeq || 0) + 1));
    });
    // v2.59：历史条目附 agentId 尾缀——同 desc 的多次派发（如多轮续审各记
    // 一条是真实记录）不再长得一模一样分不清
    const rpl = rplTail.map(a => Object.assign({}, a, {
      desc: (a.desc || '') + (a.agentId ? ' · ' + String(a.agentId).slice(-4) : '') }));
    // v2.35（P1-5）：协作代理（SendMessage 转交的独立会话/识图转交）——从
    // 消息流「已转交」线派生（dataset.peer/t0/done/psum 随快照序列化），
    // 带「协作」徽章与 Task 子代理视觉区分：peer 无实况事件流，点击只跳线
    // v2.37（P1-F①）：显示友好名（task_id→task_started 的 subagent_type 翻译，
    // 未知类型走 _AGENT_LABEL），裸会话 ID 收 title；同基名多条加委托序号
    // v2.37（P1-E）：协作包装的 agents 档案（collab 标记）与转交线同源去重
    // ——同委派已有转交线行的不再出档案行（两套并存会双行打架）
    const peerLines = _hgPeerLines();
    const peerIds = new Set(peerLines.map(el => el.dataset.peer));
    const _pbase = el => (_HG.peerNames && _HG.peerNames[el.dataset.peer])
      || _AGENT_LABEL[el.dataset.peer] || el.dataset.peer || '其他会话';
    const peers = peerLines
      // v2.41：unknown/stale 残留线不再派生面板协作行（用户实锤「一堆疑似
      // 残留永久挂着」）——它们没有 done 标记，旧过滤拦不住，重启后还随快照
      // 恢复回来。主 flow 转交线保留作历史记录；迟到的真实回传到达时
      // _hgPeerLineFreeze 定格（清 unknown/stale + 记 done）后按 60s 完成
      // 窗正常回面板。连带（正向）：stale 线不再计入「N 运行中」pill。
      .filter(el => el.dataset.unknown !== '1' && el.dataset.stale !== '1'
        && (!el.dataset.done || Date.now() - +(el.dataset.done) < 60000))
      .slice(-4);
    const list2 = list.filter(a => !(a.collab && a.taskId && peerIds.has(a.taskId)));
    const running2 = list2.filter(a => !a.done).sort((x, y) => x.t0 - y.t0);
    const finished2 = list2.filter(a => a.done && Date.now() - a.doneAt < 60000).slice(-5);
    const show = running2.concat(finished2, rpl);
    // v3.2：目录入口——区头「⏱ 已结束 N ›」开子代理目录 tab（ZCode 智能体
    // 区同款入口；有任意档案即可进目录——运行中的也列在目录里）
    // v3.2R1(P1)：计数与目录同源（_subDirRows 合并 live 档案+回放档案——
    // 只数 _HG.agents 会在 hist 回放会话上显示「已结束 0」而目录列着 N 条）
    const _dirBtn = sec.querySelector('[data-hg-agdir]');
    if (_dirBtn) {
      let endedN = 0;
      try { endedN = _subDirRows().ended.length; } catch(_) {}
      _dirBtn.hidden = false;
      _dirBtn.innerHTML = `⏱ 已结束 ${endedN} ›`;
    }
    sec.hidden = !show.length && !peers.length && !(_dirBtn && (list.length || rplAll.length));
    if (sec.hidden) return;
    const pill = sec.querySelector('[data-hg-d-agrun]');
    const pendPeers = peers.filter(el => !el.dataset.done);   // v2.41：unknown/stale 已在过滤头排除（R6 判定前移）
    pill.hidden = !running2.length && !pendPeers.length;
    pill.textContent = (running2.length + pendPeers.length) + ' 运行中';
    const _baseCount = {};
    peers.forEach(el => {
      const b = _pbase(el);
      _baseCount[b] = (_baseCount[b] || 0) + 1;
    });
    sec.querySelector('[data-hg-d-aglist]').innerHTML = show.map(a => {
      // v2.37（P1-E）：协作包装档案行——协作徽章 + 独立会话标注；无模型角标
      // （对端模型不可观测）、不进实况窗格；点击走转交线跳转分支
      if (a.collab) {
        // 已结束的协作行点击=详情卡（内含「回看协作结论」）；运行中的=跳转交线
        return `<div class="hg-dyn-agent peer ${a.done ? (a.err ? 'fail' : 'done') : 'run'}"` +
          ` ${a.done ? `data-hg-ag="${esc(a.id || '')}"` : 'data-hg-peer-row="1"'}` +
          ` title="${esc('协作代理（独立会话）· ' + (a.taskId || a.id || ''))}` +
          `${a.done ? ' · 已结束，点击看结论' : ' · 无实况窗格，点击尝试跳转交线'}">` +
          `<span class="hg-dyn-adot"></span>` +
          `<span class="hg-dyn-pbadge">协作</span>` +
          `<span class="hg-dyn-at">${esc(_AGENT_LABEL[a.type] || a.type)}</span>` +
          (a.desc ? `<span class="hg-dyn-desc" title="${esc(a.desc)}">${esc(a.desc)}</span>` : '') +
          (!a.done ? `<b class="hg-dyn-el" data-t0="${a.t0}">${a.t0 ? _hgFmtDur(Math.max(1, Math.round((Date.now() - a.t0) / 1000))) : '0s'}</b>` : '<b class="hg-dyn-el">已结束</b>') +
          '</div>';
      }
      // v2.36：中断态补 halt 修饰类（点/文字/耗时转橙，与失败红区分；仅类名）
      const cls = a.replay ? 'hist' : !a.done ? 'run'
        : (a.err ? (a.interrupted ? 'fail halt' : 'fail') : 'done');
      let el;
      // v2.59：渲染时即算实际耗时——innerHTML 重建每 3-4s 一批（事件驱动），
      // 硬编码 '0s' 占位要等下一轮 1s tick 才修正=时间反复归零（用户实锤）
      if (!a.done) el = `<b class="hg-dyn-el" data-t0="${a.t0}">${a.t0 ? _hgFmtDur(Math.max(1, Math.round((Date.now() - a.t0) / 1000))) : '0s'}</b>`;
      else if (a.replay) el = '<b class="hg-dyn-el">历史</b>';
      else if (a.err) el = `<b class="hg-dyn-el">${a.interrupted ? '已中断' : '失败'}</b>`;
      else el = `<b class="hg-dyn-el">${a.t0 ? _hgFmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000))) : '完成'}</b>`;
      const key = a.replay ? a.rid : a.id;
      // v2.35（P1-4）：模型角标——实跑 model 优先，frontmatter 预显示兜底，
      // 内置代理（无定义文件）标「主链模型」；后台代理加「后台」标
      const mdl = a.model || (_HG.agentModels && _HG.agentModels[a.type]) || '';
      const mdlTxt = a.replay ? '' :
        `<span class="hg-dyn-amdl" title="${esc(mdl ? '子代理模型：' + mdl : '内置/无定义文件代理，按 CLI 行为跑主链模型')}">${esc(mdl || '主链模型')}${a.bg ? ' · 后台' : ''}</span>`;
      return `<div class="hg-dyn-agent ${cls}" data-hg-ag="${esc(key || '')}"` +
        (a.tokens ? ` title="用量：${a.tokens} tokens · ${a.toolN || 0} 次工具"` : '') + `>` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-at">${esc(_AGENT_LABEL[a.type] || a.type)}</span>` +
        mdlTxt +
        (a.desc ? `<span class="hg-dyn-desc" title="${esc(a.desc)}">${esc(a.desc)}</span>` : '') +
        el + '</div>';
    }).join('') + peers.map(el => {
      const pend = !el.dataset.done;
      const t0 = +(el.dataset.t0 || 0) || Date.now();
      const doneAt = +(el.dataset.done || 0);
      // v2.37（P1-F①）：友好名 + 同基名委托序号——裸会话/任务 ID 永远收 title
      const raw = el.dataset.peer || '其他会话';
      const base = _pbase(el);
      const sameBase = peers.filter(x => _pbase(x) === base)
        .sort((a, b) => (+(a.dataset.t0 || 0)) - (+(b.dataset.t0 || 0)));
      const disp = _baseCount[base] > 1 ? `${base}·#${sameBase.indexOf(el) + 1}` : base;
      const durTxt = doneAt ? _hgFmtDur(Math.max(1, Math.round((doneAt - t0) / 1000))) : '';
      const sum = el.dataset.psum || '';
      // v2.41R2：过滤头已排除 unknown/stale 线（不上面板），此处 stale/unknown
      // 恒 false，「疑似残留/状态未知」分支全不可达，摘除死代码；标记逻辑本身
      // 保留在 dataset 派生层，供 _hgPeerPending/迟回传定格/verify 等消费
      return `<div class="hg-dyn-agent peer ${pend ? 'run' : 'done'}" data-hg-peer-row="1"` +
        ` title="${esc(raw !== disp ? raw + '\n' : '')}${pend ? '协作中：独立会话无实况窗格，点击跳转交线' : '已回传，点击跳转交线'}">` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-pbadge">协作</span>` +
        `<span class="hg-dyn-at">${esc(disp)}</span>` +
        `<span class="hg-dyn-desc">${esc(pend ? '等待结论回传' : (sum ? sum : '已回传'))}</span>` +
        (pend ? `<b class="hg-dyn-el" data-t0="${t0}">${_hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)))}</b>` : `<b class="hg-dyn-el">${durTxt}</b>`) + '</div>';
    }).join('');
    // v2.39：重渲恢复已展开的详情卡——上面 innerHTML 全量覆盖会把插在行后
    // 的详情卡冲掉（用户实锤「点击展开后不一会又缩回去」）。条目已滚出列表
    // （60s 完成窗口/上限 5）则清展开态，不复活孤儿卡。
    const openId = (_HG.dyn || {}).agentDetailOpen;
    if (openId) {
      const row = sec.querySelector(`[data-hg-d-aglist] [data-hg-ag="${CSS.escape(openId)}"]`);
      const a = (_HG.agents || {})[openId]
        || ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => x.rid === openId);
      if (row && a) row.insertAdjacentElement('afterend', _hgAgentDetailEl(openId, a));
      else if (_HG.dyn) _HG.dyn.agentDetailOpen = null;
    }
  }
  function _dynActs() {                  // E 最近工具：ring 20 条倒序，点击跳消息流，Bash 可复制
    const sec = _sec('acts');
    const acts = (_HG.dyn && _HG.dyn.acts) || [];
    sec.hidden = !acts.length;
    if (!acts.length) return;
    sec.querySelector('[data-hg-d-acts]').innerHTML = acts.slice().reverse().map(a => {
      const cls = a.done ? (a.err ? 'fail' : 'done') : 'run';
      const el = !a.done
        ? `<b class="hg-dyn-el" data-t0="${a.t0}">0s</b>`
        : `<b class="hg-dyn-el">${a.err ? '失败' : _hgFmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000)))}</b>`;
      const cp = a.kind === 'bash' && a.preview
        ? `<button class="hg-dyn-actcp" data-hg-actcp="${esc(a.tid)}" title="复制命令">⧉</button>` : '';
      return `<div class="hg-dyn-act ${cls}" data-hg-act="${esc(a.tid)}" title="${esc(a.preview || a.label || '')}">` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-at">${esc(a.label || a.name)}</span>` +
        `<span class="hg-dyn-desc">${esc(String(a.preview || '').slice(0, 60))}</span>${cp}${el}</div>`;
    }).join('');
  }
  function _dynTurns() {                 // F 回合历史：ring 10 条倒序 + 累计
    const sec = _sec('turns');
    const turns = (_HG.dyn && _HG.dyn.turns) || [];
    sec.hidden = !turns.length;
    if (!turns.length) return;
    const sum = turns.reduce((s2, t) => s2 + t.dur, 0);
    sec.querySelector('[data-hg-d-tsum]').textContent = '累计 ' + _hgFmtDur(sum);
    sec.querySelector('[data-hg-d-tlist]').innerHTML = turns.slice().reverse().map(t =>
      `<div class="hg-dyn-turn ${t.st}"><span class="hg-dyn-tk">${_TURN_ICO[t.st] || '·'}</span>` +
      `<span class="hg-dyn-tn">#${t.n}</span><span class="hg-dyn-td">${_hgFmtDur(t.dur)}</span>` +
      (t.tools ? `<span class="hg-dyn-tt2">${t.tools} 工具</span>` : '') + '</div>').join('');
  }
  function _dynFiles() {                 // G 当前文件：活动流派生最近 3 个文件路径
    const sec = _sec('files');
    const acts = (_HG.dyn && _HG.dyn.acts) || [];
    const files = [];
    for (let i = acts.length - 1; i >= 0 && files.length < 3; i--) {
      const a = acts[i];
      if (_FILE_TOOLS.includes(a.name) && a.preview && !files.includes(a.preview)) files.push(a.preview);
    }
    sec.hidden = !files.length;
    if (!files.length) return;
    sec.querySelector('[data-hg-d-flist]').innerHTML = files.map(f =>
      `<div class="hg-dyn-file" title="${esc(f)}">${esc(f.split(/[\\/]/).pop())}</div>`).join('');
  }
