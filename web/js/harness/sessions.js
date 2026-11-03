// harness sessions.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  // （_hgCoverageAudit/_hgBusyResync 已随批G 退役——v4 下渲染覆盖度由
  //  store snapshot 整建构造性保证，V3 重渲自愈链不复存在）
  async function switchTo(sid, keepInput) {
    // v3.5.224（诊断报告「重渲风暴」）：切回静默窗起点——5s 内兜底类全量
    // 重渲（resync/审计自愈）全跳，只留快照命中路的那一次（切回全显已满足）
    _HG.lastSwitchAt = Date.now();
    // a59（用户实测「主窗口乱套」根因）：v4 的同会话再入判据不能用 DOM——
    // 快照是网络往返，flow 空窗期（rebuild 前）判据失效→再入走进清场块把
    // 账本清空，而下方 v4Switch 同 sid 又早返回不重建=账本(4行)与DOM(21组)
    // 永久脱节→任何按账本的裁窗/重排把画面打乱。v4 下 store 归属即权威：
    // 同 sid 且 store 已连=纯早返回；V3 保持 DOM 判据不变
    // a59：v4 下 store 归属即权威——同 sid 且 store 已连=纯早返回
    if (sid === _HG.sid && _HG.v4Cur && _HG.v4Cur.sid === sid) return;
    saveCache();
    const prevSid = _HG.sid;            // v2.3.0：旧会话 id（未发送附件暂存归属）
    closePop(); closeMention();
    setQuote(null);                     // v2.27：引用属于当前输入草稿，切会话不跨带
    _hgPeerWaitStop();                  // v2.27.5：转交等待计时器不跨会话残留
    endThinking(); closeRun();
    if (_HG.grp) phStopTimer(_HG.grp);   // v2.18：防御性清占位 timer（isConnected 自杀是兜底）
    _turnHeadStop();   // v3.2：回合秒表随切会话全收
    _hgMentionReset();          // v2.15：@ 引用高亮不跨会话残留
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;   // v2.18：组级抽屉
    _HG.subTail = {};   // v2.46：tail 轮询 offset 随会话切换重置（防串会话读错文件位；批4：subRows/subBlk/subTailSeg 随段退役删）
    _HG.fetchedBusy = null;   // C组T5：随切会话清（防陈旧值误用）
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false;   // v2.24：多段历史渲染源不复用（防串会话）；v2.35.2：histLive 随切重置（快照恢复态不进滚动扩收）
    _HG.histCursor = 0;   // 398-P2：主切换清场（审 P2——六处清点漏此主点，旧会话游标残留经快照路泵=异会话重渲/丢行）
    // v3.4.52（致命双会话实锤「全部变成回放了但是实际是在工作的」）：运行中
    // 子代理 live 档案随会话暂存——原样清空后，切回走转写重渲会把运行中的
    // 子代理当历史回放建档且 task_started 不会重放=永久假回放
    if (prevSid && _HG.agents) {
      const _lv = {};
      for (const t in _HG.agents) {
        const a = _HG.agents[t];
        if (a && !a.done && (!a.sid || a.sid === prevSid)) _lv[t] = a;   // 无 sid=旧档案/当前会话派发，一并暂存
      }
      _HG.liveAgentsBy = _HG.liveAgentsBy || {};
      if (Object.keys(_lv).length) _HG.liveAgentsBy[prevSid] = _lv;
      else delete _HG.liveAgentsBy[prevSid];
    }
    _HG.todos = null; _HG.agents = null;     // v2.30：会话动态随会话切换重置（todos 由回放重建）
    // v3.4.54：识图 pending 线随切会话清场（此前漏在重置块外——切走后
    // sweep 的 sid 校验兜底，切回靠事件重放重建；DOM 随 flow 销毁，桶存无意义）
    Object.values(_HG.visionCalls || {}).forEach(_hgPeerLineStop);
    _HG.visionCalls = null;
    // v3.5.216（用户定调「重渲规整但要保留流式细节——后台/子代理等显示
    // 全没了，统一」）：tasks 随切会话**暂存**（原 v3.5.22 直接清=切回重渲
    // 后任务卡永久消失）。CLI 不落转写是事实，但档案在内存（跨切换保留
    // 即可）；notification 到达时档案在场=正常定格（后端 events 接口
    // busy/事件流按 sid 路由，不跨会话误投）
    if (_HG.tasks) {
      Object.values(_HG.tasks).forEach(t => t.el && _taskStop(t.el));
      if (prevSid) {
        const _tk = {};
        for (const k in _HG.tasks) { const t = _HG.tasks[k]; if (t && !t.done) _tk[k] = t; }
        _HG.tasksBy = _HG.tasksBy || {};
        if (Object.keys(_tk).length) _HG.tasksBy[prevSid] = _tk;
        else delete _HG.tasksBy[prevSid];
      }
    }
    _HG.tasks = null;
    _HG.dyn = null;                          // v2.32 面板派生态不跨会话（活动流/回合史/打标全重建）
    _HG.proj = null;                         // v3.1：前端投影不跨会话（/events 种子重建）
    _subReset();                             // v2.33：子代理实时窗格不跨会话
    _HG.think = null; _HG.noScroll = false; _HG.openState = null;   // v2.16：重建态不跨会话残留
    _HG.stickBtm = true;   // v3.4.67：粘底跟读态随会话切换复位（新会话默认贴底）
    // v3.2.4R(F2)：行级 ts 账与回合起点随会话切换清零（对齐 _hgSseResetLocal；
    // pendingTurnT0 残留会让下个会话 phResume 续跑组的秒表虚吃上会话时刻）
    _HG.histLineTs = 0; _HG.histActTs = 0; _HG.pendingTurnT0 = null; _HG.thinkPend = null;
    _HG.prevRowAt = 0; _HG.lastRowAt = 0;   // v3.3.1(F5)：事件时刻账不跨会话（新会话思考起点防吃上一会话时刻）
    _HG.noInputTids = null; _HG.noInputMiss = 0;   // v3.3.14R（轻审问题1）：缺令账不跨会话（防重试预算烧穿）
    _HG.sid = sid; _HG.seq = 0; _HG.epoch = null; _HG.alive = false;
    // v3.5.4（用户实锤「重启后新消息仍轻主力」）：sid 就绪即重拉 roles——
    // 启动时的 _hgRolesFetch 赶不上 sid（切回会话才有），cache 固化方案
    // 默认判定的形态，新消息徽章随之错档；切会话补拉（带 sid 实跑判定）
    // v3.5.43：识图徽章同款——旧码只启动+30s 兜底刷，重启后首刷不带 sid
    // 恒显「已启用（MCP）」，等半个轮询周期才变「多模态直读」；切会话即刻刷
    if (typeof _hgRolesFetch === 'function') _hgRolesFetch();
    if (typeof paintVisionBtn === 'function') paintVisionBtn();
    // v2.15：dirty 语义修正。旧实现只在「发送成功」置 true、只在
    // switchTo(null) 置 false —— 冷启动自动进的是历史会话（has_history），
    // dirty 仍是 false，于是点一下模型/项目 chip 就会走 `if (!_HG.dirty)`
    // 分支把这条历史会话 DELETE 掉并杀掉其进程（实测可复现：打开历史会话、
    // 不发消息、点模型 → 会话从列表消失）。这里改为按「目标会话是否已落盘」
    // 判定：缓存里有 or 服务端标记 has_history 的会话，都不是可丢弃的新会话。
    // 内存批（对抗审 C-P0）：v4 模式快照缓存不再写入（saveCache 门禁），
    // 本行的 cache 项保护随之消失——v4 的 dirty 由 v4bridge._rebuild 在
    // 数据到达时（快照有行）补置 true，比切换时刻判定更准（首条消息已发、
    // jsonl 尚未 flush 的窄窗内 has_history 仍 false，但快照必有行）
    _HG.dirty = !!(sid && (_HG.cache[sid] || _hgHasHistory(sid)));
    // v2.15：busy 不能跨会话沿用。旧实现只重置 _HG.alive，busy 靠下面那次
    // events 请求的 .then(setBusy) 纠偏，而 catch 把失败整个吞掉 —— 请求
    // 失败/非 ok 时 busy 停在 true，发送键恒为 ■、活动条恒计时、send() 被
    // 拦下，点 ■ 又回到这条死循环。这里先无条件清掉，真实值由 events 回填。
    setBusy(false);
    _hgCostEl.classList.remove('warn');   // 清文本不清 class 会让空用量环留着橙色警示
    // v2.3.0：未发送的附件随会话暂存/恢复——切走时把当前 atts 归档到旧会话
    // 名下，切回时取回该会话的暂存（原来无条件清空，用户贴的图切一圈回来
    // 就没了）。发送成功的清空在 send 尾部（清 attsBy），互不干扰。
    if (prevSid) _HG.attsBy[prevSid] = _HG.atts;
    _HG.atts = (sid && _HG.attsBy[sid]) || [];
    renderAtts();
    _hgCtxRestore(sid);                // 切回旧会话：恢复该会话上次的上下文用量（result 不重放）
    _hgQueueSeed(sid);                 // v3.1：durable 队列从服务端账本初始化（#10）
    // v4 归一管线（批F 灰度开关，验收后常开）：清场与状态账完成后全权接管
    // ——store connect 收 snapshot 整建 + delta 增量；旧 openSSE/histFetch/
    // _histRender 路径不再执行（sse.js/histcache.js 批G 退役）
    // v4 归一管线：清场与状态账完成后全权接管——store connect 收 snapshot
    // 整建 + delta 增量（新建会话 UI 由 v4Switch(null) 自带；旧 openSSE/
    // histFetch/快照恢复/冷开重拉路径已随批G 退役）
    // 对抗审 P1-1（a141）：ask dock 是全局单件——切会话必须清空，否则 A 的
    // 待答卡悬浮在 B 上、提交还带错 sid；切回 A 由 feed state.ask 重建
    _hgAskDockRestore('');
    V4Main.switch(sid, keepInput);
  }
  // v3.4.52（致命双会话实锤「全部变成回放了但是实际是在工作的」）：切走时
  // 暂存的运行中子代理 live 档案回填当前会话——转写重渲只会产出回放档案
  // （task_started 不会重放），不回填=运行中子代理永久假回放。行卡同步回
  // 运行态；桶内已完成的条目顺带清理
  // subagent-registry 阶段2：注册表为主路（_hgRegSync 拉 /agents 权威清单
  // 重建 _HG.agents——刷新/切会话后的真状态/任务名/续派链全由此来），
  // 下方内存桶逻辑保留为**同步降级**（/agents 请求在途/失败时先保运行态
  // 显示，Sync 到达后收编覆盖）
  function _hgLiveAgentsRestore(sid) {
    // 冷查询批5：主路=regSync（/agents 权威，行回绑在其 95-106 行同职责；
    // agentsRpl 去重在 _subDirRows 产出侧 _runDescs 同职责）。桶仅做
    // Sync 在途/失败的降级显示：缺键并置，Sync 到达后收编覆盖
    if (typeof _hgRegSync === 'function') _hgRegSync(sid);
    const lv = (_HG.liveAgentsBy || {})[sid];
    if (!lv) return;
    for (const t in lv) {
      const a = lv[t];
      // a155R2 观测点位1：桶 running 档即将被已落的冷查询终态条目顶掉——
      // sendAt（轮次栅栏）随之丢失的入口。零行为变化，记 ⓘ 诊断日志
      const _cur = (_HG.agents || {})[t];
      if (!a.done && _cur && (_cur.done || _cur.err || _cur.stopped)) {
        if (typeof _hgSyncAudit === 'function')
          _hgSyncAudit('切回覆盖', t, '桶档running sendAt=' + (a.sendAt || 0)
            + ' ← 冷查终态 doneAt=' + (_cur.doneAt || 0)
            + ' err=' + !!_cur.err + ' stopped=' + !!_cur.stopped);
      }
      if (a.done || (_HG.agents || {})[t]) { delete lv[t]; continue; }
      _HG.agents = _HG.agents || {};
      _HG.agents[t] = a;
    }
    if (!Object.keys(lv).length) delete _HG.liveAgentsBy[sid];
  }
  // v3.5.143：按档案认回转写重渲的伪 tid 行。hgSubr===taskId 精确匹配优先
  //（task_started 落的 id 与回放行回绑的 hgSubr 同源）；退化按 desc 等值
  //（与 _hgLiveAgentRunning 同口径，hgSubDesc 工厂侧 slice(0,120) 对齐）。
  // v3.5.145（全审F2）：未完成判据改 data-final 终态标记（三处完成落点统一
  // 标记）——旧 .h-tagent-brief 判据不可靠：回放行恒无 brief、live 完成路径
  // 摘要与 desc 同文时也省略，同名 desc 已完成历史行会被误绑
  function _hgAgentRowFindByDesc(a) {
    if (!a) return null;
    const rows = _hgFlow.querySelectorAll('.h-tool.agentline');
    if (a.taskId) {
      for (const r of rows)
        if (r.dataset.hgSubr === a.taskId && !r.dataset.final) return r;
    }
    const d = String(a.desc || '').trim().slice(0, 120);
    if (!d) return null;
    for (const r of rows) {
      const tid = String(r.dataset.tid || '');
      if ((!tid || tid.indexOf('ag') === 0) && !r.dataset.final) {   // 伪键/无键行才可认领
        const rd = String(r.dataset.hgSubDesc || '').trim();
        if (rd === d) return r;
      }
    }
    return null;
  }
  // v3.5.143：秒表复活（ABA 回绑）——渲染单元与派发 interval 共用
  // （_hgAgentSlotPaint），游离自杀守卫同款
  function _hgAgentRowTimerRestart(r, t0) {
    if (!r || !r.isConnected) return;
    // a88（用户实锤「秒表永远 0s」）：v4 同步链每次事件都携 fresh now 重启
    // 计时器——首见时刻记在行上（r._agT0），后续 restart 不再被重置，秒表
    // 从首次绘制起正常走（同步开始后槽位切「同步中」，见 _hgAgentSlotPaint）
    if (!t0) t0 = r._agT0 || Date.now();
    if (!r._agT0) r._agT0 = t0;
    if (r._agentTimer) { clearInterval(r._agentTimer); r._agentTimer = null; }
    _hgAgentSlotPaint(r, t0);
    r._agentTimer = setInterval(() => {
      if (!r.isConnected) { clearInterval(r._agentTimer); r._agentTimer = null; return; }
      _hgAgentSlotPaint(r, t0);
    }, 1000);
  }
  // v3.4.55（轻审 P2）：转写重渲路行卡是伪 tid（'ag'+hi）不进 rowById——
  // 回放工厂建行时按 desc 查桶判定「运行中」，直接画运行徽章
  function _hgLiveAgentRunning(desc) {
    const lv = (_HG.liveAgentsBy || {})[_HG.sid];
    if (!lv) return false;
    const d = String(desc || '').trim();
    if (!d) return false;
    for (const t in lv) {
      const a = lv[t];
      if (!a.done && a.desc && a.desc === d) return true;
    }
    return false;
  }
  function showWelcome() {
    _hgFlow.innerHTML = `
      <div class="hg-welcome">
        <div class="hg-welcome-ico"><span class="claude-ico big"></span></div>
        <div class="hg-welcome-title">你好，我是 Claude</div>
        <div class="hg-welcome-desc">直接输入开始新对话，或从左侧选择历史会话继续。<br>支持 <span style="vertical-align:-2.5px">${ICO16.clip}</span> 附件、@ 文件引用、<span style="vertical-align:-2.5px">${ICO16.zap}</span> 技能、<span style="vertical-align:-2.5px">${ICO16.brain}</span> 模型切换。</div>
      </div>`;
  }
  function _hgMm(m) {
    return !!(_HG.models && (_HG.models.mm || []).includes(m));
  }
  // v3.5.296b2（全审 G2）：乱序守卫——10s 轮询/SSE/重命名多触发源并发时，
  // 迟到响应用旧数据覆盖新数据（busy/标题短暂回退）。仿 _qSyncSeq 自增序号，
  // 响应到达时序号已过期即丢弃（_sessSeq 由最近的调用持有真值）
  let _sessSeq = 0;
  async function refreshSessions() {
    const seq = ++_sessSeq;
    try {
      const j = await (await fetch('/api/harness/sessions')).json();
      if (seq !== _sessSeq) return;   // 已有更新请求在途/完成——本次作废
      if (j.ok) { _HG.sessions = j.sessions || []; _HG.scheme = j.scheme || ''; renderList(); }
    } catch(_) {}
  }
  function setQuote(_hgQ) {
    _HG.quote = _hgQ || null;
    if (!_HG.quote) { quoteEl.style.display = 'none'; return; }
    const brief = _HG.quote.text.replace(/\s+/g, ' ').trim();
    quoteBodyEl.textContent = `${_HG.quote.who}：${brief.length > 60 ? brief.slice(0, 59) + '…' : brief}`;
    quoteBodyEl.title = _HG.quote.text;          // 悬浮看全文
    quoteEl.style.display = 'flex';
    _hgInput.focus();
  }
  function _hgQueueKey() { return _HG.sid || '_new'; }
  // v3.4.77（用户实锤「前台看不到堆积消息」）：队列前后端对账——
  // input_promoted 事件先摘 UI 条目，泵发送失败回插靠 input_admitted 事件
  // 加回；该事件若因 SSE 丢帧/竞速没到 → 后端队列有条目、前台显示无
  // =「消息消失」（后端仍在按泵节奏重试，最终发出——用户视角「莫名到达」）。
  // 回合终结（setBusy(false)）时拉服务端真源校准渲染缓存，id 序不同才重渲
  let _qSyncSeq = 0;
  function _hgQueueSync() {
    const sid = _HG.sid, seq = ++_qSyncSeq;
    if (!sid) return;
    fetch('/api/harness/queue?sid=' + encodeURIComponent(sid))
      .then(r => r.json())
      .then(j => {
        if (!j.ok || seq !== _qSyncSeq || _HG.sid !== sid) return;
        const key = _hgQueueKey();
        const cur = (_HG.queues[key] || []).map(x => x.id).join(',');
        const srv = (j.queue || []).map(e => e.id).join(',');
        if (cur !== srv) {
          // 以服务端为准重建（text/att 完整带回；本地草稿字段如乐观 images
          // 保留——同 id 条目服务端字段优先）
          const prev = {};
          (_HG.queues[key] || []).forEach(x => { prev[x.id] = x; });
          _HG.queues[key] = (j.queue || []).map(e => Object.assign(
            {}, prev[e.id] || {}, e.text !== undefined ? {
              id: e.id, text: e.text || '',
              images: e.images || [], files: e.files || [] } : {}));
          renderQueue();
        }
      }).catch(() => {});
  }
  function renderQueue() {
    if (qDrag) return;            // 拖拽中不重建，松手后统一重渲
    const list = _HG.queues[_hgQueueKey()] || [];
    const lenChanged = queueEl._lastLen !== list.length;
    queueEl.style.display = list.length ? 'flex' : 'none';
    queueEl._lastLen = list.length;
    // v2.25：排队条顶高/收起会改变消息流视口高——原本在底部跟读时自动回底，
    // 不用用户手动翻页（用户需求）。翻阅历史中（不在底部）不打扰。
    if (lenChanged && typeof isNearBottom === 'function' && isNearBottom()) {
      requestAnimationFrame(() => _hgScrollBottom());
    }
    queueEl.innerHTML = list.map((it, i) => {
      let t = String(it.text || '').replace(/\s+/g, ' ').trim();
      // v3.1：事件路径入列的条目只有 att 附件计数（POST 乐观条目有完整数组）
      const nAt = ((it.images || []).length + (it.files || []).length) || (it.att || 0);
      if (nAt) t = (t ? t + ' ' : '') + '📎×' + nAt;
      if (t.length > 60) t = t.slice(0, 59) + '…';
      return `<div class="hg-q-item" data-i="${i}" title="${esc(it.text || '')}">` +
        `<span class="hg-q-grip" data-i="${i}" title="拖动排序（按住抓手上下拖）">⠿</span>` +
        `<span class="hg-q-text">${esc(t || '（空）')}</span>` +
        `<button class="hg-q-act" data-qact="now" data-i="${i}" title="中断当前回复，立即发送这条">↑ 立即</button>` +
        `<button class="hg-q-act" data-qact="edit" data-i="${i}" title="放回输入框编辑">${ICO.pencil}</button>` +
        `<button class="hg-q-act" data-qact="del" data-i="${i}" title="丢弃">${ICO.trash}</button>` +
        `</div>`;
    }).join('');
  }
  function queuePush(it) {
    // v3.1（#10）：排队输入升级为服务端 durable 账本——POST /queue 入队
    //（跨设备/跨重启可见，回合终结由后端自动泵真发）。id 客户端预生成并
    // 随 POST 提交（服务端直接采用）——SSE input_admitted 事件常先于 POST
    // 响应到达，同 id 去重是防双画的锚点；本地数组只是渲染缓存
    // v3.5.109：迁移 apiPost 统一写包装（失败 banner 由包装层发，本函数
    // 只做回滚；O4——乐观变更必须定义失败路径）
    if (!it.id) it.id = 'q' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const key = _hgQueueKey();
    const arr = _HG.queues[key] = _HG.queues[key] || [];
    arr.push(it);
    renderQueue();
    showBanner('已排队：当前回复结束后自动发送', 2200);
    apiPost('/api/harness/queue', { sid: _HG.sid, id: it.id, text: it.text || '',
                                    images: it.images || [], files: it.files || [] },
            { label: '排队失败' }).then(res => {
      if (res.ok) {
        renderQueue();
      } else {
        // 入队失败（会话不在等）：回滚本地条目（banner 已由 apiPost 发）
        const cur = _HG.queues[key] || [];
        const i = cur.indexOf(it);
        if (i >= 0) cur.splice(i, 1);
        renderQueue();
      }
    });
  }
  function queuePump() {
    // v3.1（#10）：泵已上移服务端（回合终结 _queue_pump 真发 + input_promoted
    // 事件通知）——前端只负责把队列条目按服务端事件同步渲染。此函数保留
    // 是 setBusy(false) 的既有调用点，职责退化为纯重渲
    renderQueue();
  }
  function qEndDrag(commit) {
    if (!qDrag) return;
    const d = qDrag;
    qDrag = null;
    d.item.classList.remove('dragging');
    queueEl.querySelectorAll('.drop-before,.drop-after')
      .forEach(x => x.classList.remove('drop-before', 'drop-after'));
    const key = _hgQueueKey();
    const list = (_HG.queues[key] || []).slice();
    if (commit && d.target != null && list.length > 1 && d.i < list.length) {
      const it = list.splice(d.i, 1)[0];
      let to = d.target - (d.target > d.i ? 1 : 0);   // 移除后目标下标左移
      to = Math.max(0, Math.min(list.length, to));
      list.splice(to, 0, it);
      _HG.queues[key] = list;
      // v3.1（#10）：新顺序上报服务端账本（后端泵按账本顺序出队；无 id
      // 的乐观条目——POST 未返回——由后续事件对齐，这里只发已有 id 的）
      const ids = list.map(x => x.id).filter(Boolean);
      if (ids.length)
        // v3.5.109（designer D）：响应带落账后的权威 id 序——按它重建本地
        // 缓存，「写响应即对账」，收窄排序后被回合终结对账弹回旧序的窗口；
        // 失败 banner 由 apiPost 统一发
        apiPost('/api/harness/queue_act', { sid: _HG.sid, act: 'order', ids },
                { label: '排序上报失败——发送将按原顺序' }).then(res => {
          if (res.ok && Array.isArray(res.j.queue)) {
            const byId = {};
            list.forEach(x => { byId[x.id] = x; });
            _HG.queues[key] = res.j.queue.map(id => byId[id]).filter(Boolean);
            renderQueue();
          }
        });
    }
    renderQueue();
  }
  // v3.3.1（用户定调「只轻主力+设计+审核」）：工坊系花名（明镜/大匠/疾行者）
  // 退役——显示名回归朴素。标识符（dev.md/subagent_type/agents 文件名）不动，
  // 本表只服务旧会话回放/旧安装文件的显示层
  // v3.5.303（用户最终确认令「决不能出现 task 或 sendmessage」）：Task/
  // SendMessage 是 CLI 协议裸类型字，非真名——映射成中文兜底词，全前端
  // 20+ 处 `_AGENT_LABEL[type] || type` 消费点一次性收口（真名仍优先：
  // desc/peerSent 反查在前，本表只兜 desc 也空的极端态）
  const _AGENT_LABEL = { executor: '执行', coder: '编程', designer: '设计', dev: '开发', reviewer: '审核', 'general-purpose': '通用子代理', Task: '子代理', SendMessage: '协作代理' };
  // v3.5.296（用户实锤「SendMessage 往来的代理显示成 Task，要求显示原名」）：
  // to 形态三收——角色名（reviewer/designer）出中文短名；已知 agentId/taskId
  // 反查本会话档案原名；其余原样（超长 id 截短）。供 SendMessage 续派建档
  // 补 desc（tab 名/状态胶囊/agentline 全链显示走档案 desc，此处修好全好）
  function _peerLabel(to) {
    const t = String(to || '').trim();
    if (!t) return '';
    if (_AGENT_LABEL[t]) return _AGENT_LABEL[t];
    const hit = Object.values(_HG.agents || {})
      .find(a => a && (a.agentId === t || a.taskId === t));
    if (hit) return hit.desc || _AGENT_LABEL[hit.type] || t;
    return t.length > 24 ? t.slice(0, 8) + '…' : t;
  }
  // v3.5.309（用户定调「名字不是必须审核+xxx设计+xxx，而是 AI 派出去的
  // 真实的任务名」）：真实任务内容就是名字本身（不加角色前缀不拼接）——
  // msg 由 10-sse 在 SendMessage tool_use 时记入 _HG.peerMsg（首行60字）；
  // 内容缺失才退角色短名（_peerLabel），再无才是终极兜底词
  function _peerDesc(to, msg) {
    const m = String(msg || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    if (m) return m;
    return _peerLabel(to);
  }
