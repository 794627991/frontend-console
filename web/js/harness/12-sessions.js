// harness sessions.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  // v3.4.68R3（用户实锤「切B切回A 工作中的显示全没了，等很多秒都不复原」）：
  // 渲染覆盖度自检公共入口——转写数据/渲染器都无罪（transcript_for 实测 871 行
  // 全在、v3.4.52 行级隔离健全），丢失发生在渲染完成之后的某层清场/竞速
  // （snapshot 清场、快照往返、二次重建），历史多轮单点追凶失败。三个重建
  // 出口（冷开/快照命中/snapshot 清场重放）统一在尘埃落定后调这里：flow 的
  // hEnd 账目贴不住转写末行（缺口>5）即整帧重渲自愈 + banner 页面可见化
  // （自愈是否触发用户直接看得到，不再依赖控制台；自愈频发=根因仍在的信号）
  function _hgCoverageAudit(sid, totalLines, tag, opts) {
    if (_HG.sid !== sid || !totalLines) return;
    // A组S1：审计窗 2s（原 5s 把切换路径全部审计排期(2.3-3.5s)挡成死代码
    // =sse-snapshot 清场后无自愈兜底）；resync 窗保持 5s（防风暴两路 900/
    // 2100ms 仍被挡）。2.3s+ 的审计排期落窗外，覆盖兜底恢复
    if (Date.now() - (_HG.lastSwitchAt || 0) < 2000) return;
    // v3.5.196：重建在途/刚恢复不审计——reload 清场期（keepDom 后为旧 DOM）
    // 与渲染中的 DOM 账目必然不完整，hEnd=0 误判巨 gap 触发连锁自愈重渲
    // （用户 trace 实锤「rendered hEnd=0 gap=5722 auto re-render」+连着
    // 空白帧）；histRestoredAt 1.5s 内换入/trim/补尾未稳也不审
    if (_HG.histRebuilding) return;
    if (Date.now() - (_HG.histRestoredAt || 0) < 1500) return;
    // v3.5.164（轻审 F1/F2 回修，取代 v3.5.137 的一刀切）：误报机制只在
    // 「快照基准」路径成立——snapshot-hit/sse-snapshot 的 totalLines 是离开
    // 会话瞬间的快照行数，busy 会话离开后持续产出，2s 审计时 live 增量使
    // histAll 恒领先 DOM 账目十行级 → gap 必超阈误触发全量重渲（trace 实测
    // 两遍 ParseHTML 各 ~2.1 万次/750ms，切会话卡 3~4s 主因）。这类路径
    // busy 时跳过自愈（渲染兜底：snapshot-hit=无条件 resync、sse-snapshot=
    // 2100ms 无条件 resync）。sse-rebuild/reload-flow/cold-rebuild 的
    // totalLines 是本批渲染行数（fetch 捕获值），live 增量既不抬基准也不盖
    // 戳——gap>阈 即真丢行，busy 下保留审计（那是无 R5 兜底路径的唯一防线）
    const _snapBase = !!(opts && opts.snapshotBase);
    if (_snapBase && _HG.busy) return;
    let _hEnd = 0;
    try {
      _hgFlow.querySelectorAll('[data-h-end]').forEach(el => {
        _hEnd = Math.max(_hEnd, +(el.dataset.hEnd || 0));
      });
    } catch (_) { return; }
    const _gap = (totalLines - 1) - _hEnd;
    // v3.4.68R4：阈值 5→2——实测「当前轮恰好 4 行渲染失败」时 gap=4 被旧阈值
    // 漏过（banner 不弹+内容缺，双重失守的盲区）。v3.5.164：非快照基准路径
    // 恒用 2（R4 盲区不重开）；快照基准路径 idle 时 gap≈0 本就不触发，阈值
    // 比例化只为防御性容差，且忙时已整体跳过
    const _thr = _snapBase ? Math.max(3, Math.ceil(totalLines * 0.02)) : 2;
    if (_gap <= _thr) return;
    // 频控：10 分钟窗口最多自愈 3 次——清场竞速若循环发生，无限重渲只会闪屏
    const _now = Date.now();
    _HG.covAuditN = (_HG.covAuditN || []).filter(t => _now - t < 600000);
    if (_HG.covAuditN.length >= 3) {
      try { console.error('[harness] coverage gap persists @' + tag
        + ' (gap=' + _gap + ') — self-heal rate-limited'); } catch (_) {}
      return;
    }
    _HG.covAuditN.push(_now);
    _hgDiag('audit', '@' + tag + ' gap=' + _gap + '（lines=' + totalLines + ' hEnd=' + _hEnd + '）→ 自愈重渲');
    try { console.info('[harness] transcript coverage gap @' + tag
      + ': lines=' + totalLines + ' rendered hEnd=' + _hEnd
      + ' gap=' + _gap + ' — auto re-render'); } catch (_) {}
    try { showBanner('检测到消息流显示不完整（缺 ' + _gap + ' 行），已自动重建', 4000, true); } catch (_) {}
    _hgReloadFlow();
  }
  // v3.4.69d（用户拍板恢复）：busy 会话切回后无条件重渲一次——「A 还在运行
  // 就必须一字不差全显示」是硬需求，条件判定（审计 gap）已被实测证明有盲区
  // （gap=4 漏过、清场时序漂移漏过）。重渲成本一次本地 fetch+几百 ms，换
  // 确定性。上一版撤除的原因（头丢/动态丢/不贴底）实为 _hgReloadFlow 缺三件
  // 配套，现已补齐：phResume（头+秒表）/ _hgLiveAgentsRestore（运行中动态）/
  // 两帧+600ms 回底兜底。idle 会话不触发
  function _hgBusyResync(sid, delay) {
    setTimeout(() => {
      if (_HG.sid !== sid || !_HG.busy) return;
      // v3.5.224：切回静默窗（5s）内跳过——切回已由快照命中路全显一次，
      // 此路在窗内再跑只会与它互相点火重渲风暴（实测 35s 13 轮）
      if (Date.now() - (_HG.lastSwitchAt || 0) < 5000) return;
      _hgReloadFlow();
    }, delay || 800);
  }
  async function switchTo(sid, keepInput) {
    // v3.5.224（诊断报告「重渲风暴」）：切回静默窗起点——5s 内兜底类全量
    // 重渲（resync/审计自愈）全跳，只留快照命中路的那一次（切回全显已满足）
    _HG.lastSwitchAt = Date.now();
    if (sid === _HG.sid && _hgFlow.querySelector('.h-msg, .hg-welcome')) {
      // v2.15：点的是当前会话 → 早返回。但 busy 卡死时用户正是靠「重点一下
      // 当前会话」自救，这里不能什么都不做：至少按后端真实值纠偏一次。
      if (sid) {
        // v2.35.2（P0 加固）：SSE 归属校验——历史竞态（切换竞速/早返回）可能
        // 让 _HG.sse 停在别的会话的流上：内容看着正常、事件永远不来。归属
        // 不符即重开本会话流（after_seq 用当前 seq，不重放已渲染事件）。
        try {
          const own = _HG.sse && _HG.sse.url
            && _HG.sse.url.includes('sid=' + encodeURIComponent(sid));
          if (!own) openSSE(sid, _HG.seq);
        } catch(_) {}
        _hgEventsPoll(sid);
      }
      return;
    }
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
    // v2.43：子代理段随会话切换重置（段计时器停掉；段 DOM 随 flow 重建，内存档不跨会话残留）
    Object.values(_HG.subBlk || {}).forEach(b => { if (b && b.timer) clearInterval(b.timer); });
    _HG.subRows = {}; _HG.subBlk = {};
    _HG.subTail = {};   // v2.46：实时思考轮询 offset 随会话切换重置（防串会话读错文件位）
    _HG.subTailSeg = {};   // v2.58：续派切段映射随会话重置
    _HG.fetchedBusy = null;   // C组T5：随切会话清（防陈旧值误用）
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false;   // v2.24：多段历史渲染源不复用（防串会话）；v2.35.2：histLive 随切重置（快照恢复态不进滚动扩收）
    _HG.histStale = false;   // v2.43.2（R2-缺口A）：降级标记随切会话重置（恢复时按快照 histFp 重新判定）
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
    _HG.echoFast = null;               // v2.20：切会话清乐观渲染去重窗口（防串会话吞 echo）
    _hgCtxRestore(sid);                // 切回旧会话：恢复该会话上次的上下文用量（result 不重放）
    _hgQueueSeed(sid);                 // v3.1：durable 队列从服务端账本初始化（#10）
    if (!sid) {
      _hgFlow.innerHTML = '';
      _hgAskDockRestore('');   // v3.4.61：新会话清 dock（旧面板不跨会话残留）
      showWelcome();
      openSSE(null); setBusy(false);
      _hgTitleEl.textContent = '新会话'; _hgCwdEl.textContent = '';
      renderList(); renderQueue();
      _hgRailSync();   // v3.2.10：空 flow 收轨
      _hgInput.focus();
      return;
    }
    let c = _HG.cache[sid];
    // v3.2.11（用户实锤「有的回合没整合在一起」）：旧结构快照（v3.2 前的
    // DOM：无 .h-turn-body 回合闭合结构）恢复后思考/工具/正文永远散着——
    // 弃快照走 transcript 重渲，全部回合统一新结构（头+折叠体+根区结论）
    // v3.2.12：部分窗口快照（histStart>0，分页时代的产物）同样作废——恒
    // 全量渲染后没有扩段机器，残缺 DOM 会让上半段历史翻不到
    if (c && c.html && c.html.indexOf('h-turn-body') === -1
        && c.html.indexOf('h-grp') !== -1) c = null;
    // v3.5.191r2：窗口化渲染（v3.5.191）下窗口快照（histStart>0）是合法
    // 完整形态——「上半段历史」入口是归档条进只读（不再靠上滑），原判定
    // 前提（恒全量+上滑扩段）已退役。保留它会打死快照秒开：每次切回都弃
    // 快照走全量重渲（用户实锤「静态来回切都不是秒开了」）
    // if (c && typeof c.histStart === 'number' && c.histStart > 0) c = null;
    // v3.5.198：stale 哨兵快照不再弃——弃了=无快照冷开（清场白屏等 13MB
    // fetch，用户 trace 实锤连环白屏）。改为照常恢复显示（旧内容总比白屏
    // 好），账目漂移由既有 histFp 校验分支处理（busy 降级 histStale 待重
    // 渲 / idle 直接重渲一次做对）；ask 豁免语义由「恢复不弃」天然满足
    //（v3.4.60/v3.4.61 原注释留档）
    // v3.2.28（用户实锤「切走再切回工作区被截断，回合完成后还是截断态」）：
    // 切走时回合还在跑（openTurn）——快照注定残缺（离开期间过程行只靠事件
    // 回放，环形缓冲有限会丢），弃快照走 transcript 全量重渲（含 busy 续占
    // 位/SSE 接续，与首开同路），回合完成与否都拿到完整工作区
    // v3.3.2R(F2)：待答 ask 卡豁免弃快照——CLI 正阻塞等选择，离开期间零
    // 事件（无过程行可丢），快照反而完整；弃了走转写重建必丢卡（transcript
    // 无 ask 行、ask 帧只在弹出时 emit 一次不重放），用户无从作答只能中断
    // 自救。判定按序列化 className 精确值：待答卡=class="h-ask"（done 卡是
    // "h-ask done collapsed"，不命中）
    // v3.5.201b（用户实锤「A(活跃)→B→A 点击后明显迟滞」）：openTurn 快照
    // 不再弃——弃了=每次切回全量 fetch 13MB+渲染（迟滞真身）。改为照常
    // 恢复（旧内容秒显），离开期间新增的过程行由既有「有增长→窗口重渲
    // 一次做对」分支补全（histAll 拉到后对比 DOM hEnd 账目，有增长立即重
    // 渲=完整工作区）。v3.2.28 担心的「过程行丢失」由重渲兜底而非弃整个
    // 快照；ask 豁免语义由不弃天然满足（v3.3.2R F2 场景）
    // if (c && c.openTurn && !(c.askPanel
    //     || (c.html && c.html.indexOf('class="h-ask"') !== -1))) c = null;
    if (c) {
      // v3.1：keep-warm 命中——取消该快照的延迟销毁（saveCache 排程的 30s
      // 定时器），热快照继续作为 LRU 一员存活
      if (_HG.cacheWarm && _HG.cacheWarm[sid]) {
        clearTimeout(_HG.cacheWarm[sid]);
        delete _HG.cacheWarm[sid];
      }
      _hgFlow.innerHTML = c.html; _HG.seq = c.seq;
      _hgAskDockRestore(c.askPanel);   // v3.4.61：dock 面板回挂（含老代 flow 待答卡迁移）
      // v3.2.1（用户实测问题1）：快照里开着的已完成回合体规整回默认收起——
      // 快照存的是离开瞬间的 DOM（live 定稿时可能没收/存的是重建期的开态），
      // 恢复后按「完成默认收」清扫：用户点开过的（userToggled 随 dataset 序列
      // 化，忠实可信）保留。顺带把快照冻结的「工作中 Ns」残头（app 中途被杀
      // 的活组、interval 不随 innerHTML 走）定格为无数字「已工作」——工时事
      // 实已不可考，不编造。进行中组（无 data-finalized）不动：busy 恢复路径
      // phResume 要接着用它的体
      _hgFlow.querySelectorAll('.h-grp[data-finalized="1"]').forEach(g => {
        const head = g.querySelector('.h-turn-head');
        const body = g.querySelector('.h-turn-body');
        if (head && body && head.dataset.userToggled !== '1') body.classList.add('closed');
        const lbl = head && head.querySelector('.h-turn-label');
        if (lbl && lbl.textContent.indexOf('工作中') === 0) lbl.textContent = '已工作';
      });
      _HG.epoch = c.epoch || null;     // v3.0：代际水位随快照存取（与 seq 同进退）
      _HG.echoFast = c.echoFast || null;   // v2.28.13：去重窗口随快照恢复（防重放双画）
      // v2.37（P0-A）：窗口账目重建——快照 DOM 是上一次 _histRender 的窗口
      // （histStart 起的尾部段），账目随快照存取（见 saveCache）。histLive
      // 置 true 需 histAll 数据在场：拉一次 transcript 只填数据不重渲
      // （转写只追加，[0..histStart) 前缀稳定，DOM 尾段与 histAll 对应成立，
      // 上滑扩段自此可用；旧缓存无账目字段 → 维持 v2.35.2 安全态走只读条）。
      // 还原后 400ms 内不进收缩分支——程序化 scrollBottom 会触发 scroll 事件，
      // >2 页的快照会被立刻「收段」重渲（观感=又刷了一遍）
      _HG.histStart = (typeof c.histStart === 'number') ? c.histStart : 0;
      _HG.histRestoredAt = Date.now();
      // v2.25：快照里「已点开」的懒段/懒工具，切回来必须显示内容——histAll
      // 已被切会话清空，拉 transcript 后补填（否则展开=空白壳，用户实测
      // 「早起会话的历史思考点不开」）。v2.43.2：选择器补 .open（原漏——
      // 把关闭行也预填，废了懒加载）；补填并入下面主路（单次拉取）
      const lazyOpen = _hgFlow.querySelectorAll('.h-think-seg.open[data-hg-lazy="1"], .h-tool.open[data-hg-lazy="1"]');
      if (c.histLive && !_HG.histAll) {
        _histFetch(sid).then(ok => {
          if (ok && _HG.sid === sid) {
            // v2.37R2（复审4）：账目越界钳制——快照存账后该会话在别窗做过
            // 回滚（转写被截断），histStart 可能越过现在的行数
            if (_HG.histStart > _HG.histAll.length) _HG.histStart = _HG.histAll.length;
            // v2.43.1（R-FAIL3）+ v2.43.2（R2-缺口A）：前缀指纹不符/stale
            // 哨兵=中插变更——旧 DOM 账目整体作废，重渲自愈；忙碌（后台回
            // 合进行中，重渲会炸掉活组）降级：弃 histAll、扩收门保持关、置
            // histStale 让下次快照带 'stale'（恢复强制重渲，漂移保护不丢失）
            if (c.histFp === 'stale'
                || (c.histFp != null && _histPrefixFp(_HG.histAll, _HG.histStart | 0) !== c.histFp)) {
              if (!_HG.busy) _histRender(_HG.histAll, _HG.histStart | 0);
              else { _HG.histAll = null; _HG.histStale = true; }
              if (_HG.tasksBy) delete _HG.tasksBy[sid];   // A组S3c：防残档下次复活
              return;
            }
            _HG.histLive = true;
            _hgRplRebuild();   // v3.2.22：快照恢复不跑渲染循环——子代理目录条目在此重建（否则切回后空壳点不开）
            renderSideStatus();   // 面板 B/C 回放数据此路也会补齐（todos 等）
            // v3.5.165（用户定调「一次做对，渲染全对」）：快照 DOM 是切走瞬间的——
            // 切走期间有产出（histAll 比 DOM 账目多行）且会话空闲（无活组可炸）时，
            // 立即全量重渲一次做对：不再走「先显示一半 → 2s 审计发现缺口 → 再卡
            // 一遍重渲」的两段式（trace 实测两遍 ParseHTML 各 ~2.1 万次）。有增量
            // 且 busy → 不在此重渲（活组在场，重渲炸活组——R2-缺口A 既有约束），
            // 交由下方 R5 resync（900ms，用户拍板的切回全显路径）渲染全；无增量 →
            // 快照即全，什么都不用做。审计照挂作核对（重渲/增量路径均 gap≈0 不触发）
            const _snapHEnd = (() => { let m = 0;
              try { _hgFlow.querySelectorAll('[data-h-end]').forEach(el => {
                m = Math.max(m, +(el.dataset.hEnd || 0)); }); } catch (_) {} return m; })();
            // v3.5.197（用户实锤「上一回合的内容渲染进了新回合」）：有增长
            // 一律窗口重渲一次做对（busy 传 noFinalize 留活组+phResume 认回
            // 接续秒表，t0 由行 ts 保真不归 0）——v3.5.194 的 busy 增量补尾
            // 退役：补尾手写渲染路径连爆两雷（绕过行尾记账→审计误判巨 gap
            // 触发空白期+上回合内容重复渲染进新回合），增量路径复杂度不可
            // 控。窗口重渲成本实测 150-260ms（长任务级，keepDom 原子换入无
            // 空白期），确定性换复杂度。无增长快照即最新，不做任何事。
            // v3.5.204b（用户定调「重渲染的格式更完美，全部使用重渲染
            // 格式」）：一律窗口重渲——快照仅作 fetch 期的秒显垫底，
            // histAll 就绪即替换为重渲完美格式（快照存的是切走瞬间的
            // 流式残留形态，重渲才是结构化终态；无增长也渲）。busy 传
            // noFinalize 留活组+phResume 认回接续秒表（t0 行 ts 保真）。
            const _busy2 = (_HG.fetchedBusy != null) ? _HG.fetchedBusy : !!_HG.busy;
            // 自测矩阵实锤修复：T2 注释回修误删 _he2 声明段——切回链
            // fetch.then 抛 ReferenceError(unhandledrejection)=phResume/live
            // 回填/贴底全断。补回 DOM 账目水位计算
            let _he2 = 0;
            try { _hgFlow.querySelectorAll('[data-h-end]').forEach(el => {
              _he2 = Math.max(_he2, +(el.dataset.hEnd || 0)); }); } catch (_) {}
            // v3.5.227+230（思考保留+历史完整）：无增长不动 DOM（live 思考
            // 保留——转写未落盘的思考只在屏上）；有增长整窗重渲（完整 20
            // 回合窗口，历史完整；exactStart 追加模式已因整替丢历史事故退役）
            if (_HG.histAll.length - 1 > _he2) {
              // v3.5.230（用户实锤「历史全没了」紧急回修）：v3.5.227 用
              // exactStart 追加是错的——_histRender 的原子换入把 flow 整替
              // 成「只有新增行」（hEnd 前的历史全被换掉=241 轮消失，重蹈
              // v3.5.195 补尾覆辙）。改回整窗重渲（histStart 起，完整 20
              // 回合窗口）：无增长不动 DOM（live 思考保留）语义不变；有
              // 增长=工具已落盘（思考也随之落）→整窗渲含思考，两全
              _histRender(_HG.histAll, _HG.histStart | 0, { noFinalize: _busy2 });
            }
            if (_busy2 && typeof phResume === 'function') phResume(true);
            // v3.5.216：重渲只回放转写行——live-only 元素（运行中子代理
            // 档案/后台任务卡）不在转写里，重渲后统一回填（用户定调
            // 「重渲规整+流式细节统一」）
            if (typeof _hgLiveAgentsRestore === 'function') { try { _hgLiveAgentsRestore(sid); } catch (_) {} }
            if (_HG.tasksBy && _HG.tasksBy[sid]) {
              const _tk = _HG.tasksBy[sid];
              for (const k in _tk) {
                const t = _tk[k];
                // A组S3b：快照 html 已含任务卡（v227 无增长恢复路径）——
                // DOM 在场则跳过重建（原无条件 _taskStart=同 tid 双卡+旧卡
                // 冻结运行中永不清）
                if (_hgFlow.querySelector('.h-taskcard[data-tid="' + k + '"], [data-tid="' + k + '"].h-taskcard')) continue;
                try { _taskStart(k, t.desc || ''); } catch (_) { continue; }
                const t2 = (_HG.tasks || {})[k];
                if (t2) Object.assign(t2, t, { el: t2.el });   // 恢复原档案（t0/desc），卡用新建的
              }
              delete _HG.tasksBy[sid];
            }
            // v3.5.205b（用户实锤「重渲必现：执行中动画消失+不贴底」）：重渲
            // 换入清了流底 spinner（innerHTML 重建），busy 真值未变 setBusy
            // 不会重调——幂等重挂（在场即不重加，06-relay 冷开同款）；
            // 贴底三重兜底同冷开（图片/字体懒结算撑高会再偏，两帧+600ms）
            if (typeof _hgSpinShow === 'function') { try { _hgSpinShow(_busy2); } catch (_) {} }
            try { _hgScrollBottom(true); } catch (_) {}
            requestAnimationFrame(() => requestAnimationFrame(() => { try { _hgScrollBottom(true); } catch (_) {} }));
            setTimeout(() => { if (_HG.sid === sid) { try { _hgScrollBottom(true); } catch (_) {} } }, 600);
            setTimeout(() => { if (_HG.sid === sid)
              _hgCoverageAudit(sid, _HG.histAll ? _HG.histAll.length : 0,
                'snapshot-hit-refresh', { snapshotBase: true }); }, 2000);
            // v2.43.2（R2-缺口A）：懒行补填并入主路——旧实现另起 fetch 先于
            // events 到达，busy 判定失真，漂移分支抢跑重渲炸掉快照（实测）。
            // v3.5.165：保持在最后——重渲分支会重建 DOM，补填须查新树
            lazyOpen.forEach(el => _histLazyFill(el));
          }
        });
      } else if (lazyOpen.length && !_HG.histAll) {
        // 旧账目快照（无 histLive/histFp，v2.37 前的缓存）：维持 v2.25 直填
        // （无指纹可校验；中插变更由补填内的点校验/下次全量渲染兜底）
        _histFetch(sid).then(ok => {
          if (ok && _HG.sid === sid) { lazyOpen.forEach(el => _histLazyFill(el)); _hgRplRebuild(); }
        });
      }
      // v3.0 滚动记忆恢复（对照 ZCode chatSessionScrollMemory）：离开时贴底
      // → 回底（继续跟读）；否则恢复钳制后的 scrollTop（clamp 到当前可滚
      // 范围——DOM 未到齐时恢复值被压小，内容补齐后自然落位）。rAF 等
      // innerHTML 回填后的布局结算再写 scrollTop（同步写会被旧布局吞掉）。
      if (c.scroll && !c.scroll.atBottom) {
        // v3.4.67：离开时在看历史——粘底态显式置假。重置块的 stick=true 置位
        // 在本分支不成立（用户不在底），且恢复写 scrollTop 可能是 no-op（写入
        // 值==当前值不触发事件）→ 标志与实际位置脱钩=读历史被拽底（轻审实锤）。
        // rAF 写入后再按实测 gap 精确回填（内容钳制后可能恰好贴底）。
        _HG.stickBtm = false;
        _HG.noScroll = true;           // 恢复写 scrollTop 触发的 scroll 事件不得进扩收分支
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const max = _hgFlow.scrollHeight - _hgFlow.clientHeight;
            if (max > 0) _hgFlow.scrollTop = Math.min(Math.max(c.scroll.top, 0), max);
            _HG.stickBtm = (_hgFlow.scrollHeight - _hgFlow.scrollTop -
                            _hgFlow.clientHeight) < 120;   // v3.4.67：按落点实测
            _HG.noScroll = false;
          });
        });
      } else {
        // v3.4.75（用户实锤「切任意会话都不在底部」）：快照命中路（30s 保温，
        // A→B→A 快切恒走此路）的回底此前只有一次+一帧 rAF——innerHTML 回填后
        // 折叠行/图片/字体的布局结算远晚于一帧，写早了 scrollHeight 还小=停
        // 半空。对齐冷开路三重兜底：两帧 + 600ms 终兜
        _hgScrollBottom(true);
        requestAnimationFrame(() => requestAnimationFrame(() => _hgScrollBottom(true)));
        setTimeout(() => { if (_HG.sid === sid) _hgScrollBottom(true); }, 600);
      }
      // v2.3.13：快照里冻结的压缩分割线——本会话没有仍在进行的压缩就定格成
      // 完成态（压缩结束事件只在原会话 SSE 里到达，切走期间错过时这里兜底），
      // 不让「正在压缩 · 已 X」冻死在消息流里
      const cdiv = _hgFlow.querySelector('.h-switch[data-hg-compact]');
      if (cdiv && !(_HG.compacting && _HG.compactSid === sid)) {
        const ci = cdiv.querySelector('i');
        if (ci && !ci.textContent.includes('完成')) ci.textContent = '上下文压缩完成';
      }
      // v2.24.5：时间条状态从 DOM 恢复（最后一条 .h-time 的 ms）
      _HG.lastTs = +((([..._hgFlow.querySelectorAll('.h-time')].pop() || {}).dataset || {}).ms || 0);
      // v2.3.2：未定格的转交等待线重启计时——快照（innerHTML 字符串）不
      // 带 interval，恢复后计时冻结在快照时刻（用户实锤「读秒不走」）。
      // v2.35.2（P1 多槽）：全部未定格线各重挂各的计时器（此前只挂最后
      // 一条，更早的线读秒冻死）；peerWait 指向最后一条（兼容识图 sweep）。
      // 旧快照的线没有 data-peer——按文本兜底识别，一并重挂
      const relayEls = new Set(_hgFlow.querySelectorAll('.h-switch[data-peer]:not([data-done]), .h-tool.h-vision[data-peer]:not([data-done])'));
      _hgFlow.querySelectorAll('.h-switch .hg-peer-t').forEach(tb => {
        const sw = tb.closest('.h-switch');
        if (sw && !sw.dataset.peer && !sw.dataset.done
            && sw.textContent.includes('等待结论回传')) relayEls.add(sw);
      });
      relayEls.forEach(rl => _hgPeerTimerStart(rl, +(rl.dataset.t0 || 0) || Date.now()));
      // 快照恢复后重建 rowById（busy 会话切回时 tool_result 事件要挂回行）
      // v2.43.1（R-FAIL2）：段内工具行按所在段归 subRows（不入主链 rowById）
      // ——恢复瞬间（下一子代理事件未到、subBlk/subRows 尚空）到达的子代理
      // tool_result 不再被 :2846 守卫丢弃，段内徽章照常定格
      _hgFlow.querySelectorAll('[data-tid]').forEach(el => {
        // 全审 P4：pending 识图卡重注册回 visionCalls（迟到 tool_result 走
        // 10-sse 正路定格），且不入 rowById（renderOneToolResult 会把全文误
        // 灌空折叠体、用户点开时被懒填整体覆盖=回传被抹）
        if (el.classList.contains('h-vision')) {
          if (el.dataset.tid && !el.dataset.done) {
            (_HG.visionCalls || (_HG.visionCalls = {}))[el.dataset.tid] = el;
            _hgVisionPaint(el, 'run');
            _hgPeerTimerStart(el, +(el.dataset.t0 || 0) || Date.now());   // v3.5.8：快照恢复的 run 卡起表（旧漏：表不走）
          }
          return;
        }
        const blk = el.closest('.h-subblock');
        if (blk && blk.dataset.hgSubblock) {
          const _sp = blk.dataset.hgSubblock;
          ((_HG.subRows[_sp]) || (_HG.subRows[_sp] = {}))[el.dataset.tid] = el;
        } else {
          _HG.rowById[el.dataset.tid] = el;
        }
      });
      // v3.4.52：运行中子代理 live 档案回填（快照命中路）——目录/动态页
      // 恢复「正在运行」态，点行 live 直开不再假回放
      _hgLiveAgentsRestore(sid);
      // v2.9：缓存恢复不能盲目清 busy——切走时正在回复的会话，切回后
      // 事件继续流入但 user_echo 已在 seq 之前（不重放），活动条/停止钮
      // 再也不弹（用户实测「有实际对话但无计时条、发送键不变■」）。
      // 后端 events 接口顺带返回真实 busy，按它恢复（v3.0 兼带 epoch 校验）
      _hgEventsPoll(sid);
      _hgRailSync();   // v3.2.10：快照恢复后重建轨（未渲染区项待 histAll 补全后自动出现）
    } else {
      // v3.5.198（用户实测白屏专项：切 13MB 大会话 n=0 全程白屏）：不再预清
      // flow——上一个会话的内容保留在屏（总比白屏好），fetch 完成由
      // _histRender 原子换入（v3.5.196 已撤渲染器预清）；顶部插轻量加载
      // 指示（换入时被 replaceChildren 自然清掉）。dock 照清（A 的待答面板
      // 已随入口 saveCache 存进 A 快照，不清则 B 的 _hgAskSync 当僵尸）
      _hgAskDockRestore('');
      try {
        var _ld = document.createElement('div');
        _ld.className = 'hg-spin-row';
        _ld.innerHTML = '<span class="hg-spin"></span><span>加载会话内容…</span>';
        _hgFlow.insertBefore(_ld, _hgFlow.firstChild);
      } catch (_) {}
      _HG.histRebuilding = sid;   // 复审 P5：冷开转写在途窗口（同 _hgSseRebuild
                                  // 三处同款 sid 化标志——空 flow 不入快照）
      try {
        const j = await (await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)).json();
        if (j.ok && _HG.sid === sid) {
          _HG.seq = j.seq || 0; _HG.epoch = j.epoch || null; _HG.alive = !!j.alive;
          if (!j.lines.length) showWelcome();
          else _histRender(j.lines, _hgHistWinStart(j.lines),
                           { noFinalize: !!j.busy });   // v3.2.1R(F1)：尾组定稿在渲染器内；busy 活组留给 phResume
          // v2.20（3.png）：busy 会话尾部组是「进行中」的组——transcript 只到
          // 已落盘部分，无条件定稿会把组关死还漏占位气泡。留活 + 补占位，
          // SSE 续传事件经 grpEnsure 回扫正常接回。
          // v3.4.71（复核 P3 返工·方案 a）：busy 真值经参数传入 phResume——
          // setBusy 保持旧序（phResume 后）不先加 spinner（认回选择器已加固，
          // 双保险）；setBusy 回填活动条/发送键态
          if (j.busy) phResume(true);
          else grpFinalize(true, { hist: true, turnEnd: true });   // 幂等兜底（渲染器内已定稿则早退）；v3.2.2 turnEnd
          _hgDiag('cold', '冷开重建 lines=' + j.lines.length + ' busy=' + !!j.busy + ' phResume=' + (j.busy ? '已带参调' : '跳过'));
          _hgLiveAgentsRestore(sid);   // v3.4.52：转写重渲路同样回填运行中子代理 live 档案
          _hgAskSync(sid);   // v3.4.61：冷开路 seq 已跳过 ask 帧——待答面板靠后端快照拉回
          _hgScrollBottom(true);              // 切会话回底（不受翻历史保护限制）
          // v3.4.68（用户实锤「每次重开都不是直达底部的」）：回底后图片懒加载/
          // 字体结算/phResume 占位补画仍会撑高 flow（_hgScrollBottom 的 rAF
          // 二次滚只覆盖一帧）——再兜两帧 + 600ms 终兜，确保重开直达底部
          requestAnimationFrame(() => requestAnimationFrame(() => _hgScrollBottom(true)));
          setTimeout(() => { if (_HG.sid === sid) _hgScrollBottom(true); }, 600);
          // v3.4.68R2：覆盖度审计（gap≥3 才触发，条件性兜底）+ R5 无条件 resync
          // （用户拍板：切回 busy 会话后直接重渲一次，等效一条新消息的全量渲染）
          setTimeout(() => _hgCoverageAudit(sid, j.lines.length, 'cold-rebuild'), 2000);
          if (j.busy) _hgBusyResync(sid, 800);   // v3.4.69d：无条件重渲（三件配套已齐）
          setBusy(!!j.busy, j.busy_since);   // v2.26：计时起点带后端 busy_since（v3.4.71：旧序恢复，phResume 已带参先行）
        }
      } catch(_) {
        // A组G2：冷开 fetch 失败不再静默——提示+保持 histRebuilding（禁存
        // 快照，防上一会话残屏投毒本会话快照）；SSE 重连的 ack-snapshot 兜底
        try { showBanner('会话内容加载失败（网络/后端异常）——SSE 重连将自动重建', 5000, true); } catch(_) {}
        return;   // 不清 histRebuilding：失败期 saveCache 禁入
      }
      finally { if (_HG.histRebuilding === sid) _HG.histRebuilding = null; }
    }
    // v2.35.2（P0 加固）：transcript 分支有 await——期间用户可能已切去别的
    // 会话（快切/双击竞速）。此刻本调用已是过期调用：chrome（标题/目录/chip）
    // 与 openSSE 若照跑，会把「显示 A、事件流却挂 B、标题 C」的错位态焊死，
    // 且过期流的小 seq 事件全被防重放守卫吞掉，会话从此假死。归属不符即弃。
    if (_HG.sid !== sid) return;
    const s = _HG.sessions.find(x => x.sid === sid);
    // v2.7：项目优先——cwd 目录名在前（accent），claude 会话名在后
    _hgCwdEl.textContent = s ? (s.cwd || '').split(/[\\/]/).pop() || '~' : '';
    // v2.19：切回历史会话 → 「新会话将打开的目录」跟随该会话的项目，
    // 同项目连续开会话不用每轮重选（会话无 cwd 时不动用户手选的值）。
    if (s && s.cwd && _HG.cwd !== s.cwd) {
      _HG.cwd = s.cwd; _hgSaveCwd(s.cwd); projChipLabel();
    }
    // v2.20：权限/思考等级同理跟随会话恢复显示
    if (s) {
      if (s.permission && s.permission !== _HG.perm) { _HG.perm = s.permission; permChipLabel(); }
      const st = s.think || null;
      if (st !== _HG.thinkLv) { _HG.thinkLv = st; thinkChipLabel(); }
      // 模型跟随会话恢复（用户要求：打开历史会话直接显示之前用的模型）。
      // 元数据 model=None 的会话（从没显式选过）实际跑的是 settings 默认
      // 模型——显示默认名，别回退成空态「模型」让用户以为丢了。
      const sm = s.model || (_HG.models && _HG.models.default) || null;
      if (sm && sm !== _HG.model) {
        _HG.model = sm;
        _hgQ('[data-hg-model]').innerHTML = esc(sm) + ' ▾';
      }
    }
    _hgTitleEl.textContent = (s && s.title) || '会话';
    _hgConn.meta.label = _hgTitleEl.textContent;
    _hgConn.meta.cwd = (s && s.cwd) || '';
    _hgConn.tab.querySelector('.label').textContent = _hgTitleEl.textContent;
    openSSE(sid, _HG.seq);
    renderList();
    renderQueue();                   // v2.20：排队条按会话各自恢复
    refreshSidebar();
    if (!keepInput) _hgInput.focus();
  }
  // v3.4.52（致命双会话实锤「全部变成回放了但是实际是在工作的」）：切走时
  // 暂存的运行中子代理 live 档案回填当前会话——转写重渲只会产出回放档案
  // （task_started 不会重放），不回填=运行中子代理永久假回放。行卡同步回
  // 运行态；桶内已完成的条目顺带清理
  function _hgLiveAgentsRestore(sid) {
    const lv = (_HG.liveAgentsBy || {})[sid];
    if (!lv) return;
    for (const t in lv) {
      const a = lv[t];
      if (a.done) { delete lv[t]; continue; }
      _HG.agents = _HG.agents || {};
      _HG.agents[t] = a;
      // v3.5.143（用户批注「切会话(ABA)，过程显示就没了」）：档案回填扩到
      // **行回绑**——转写重渲的 agentline 行是伪 tid（07-hist 'ag'+hi）不进
      // rowById，旧码 rowById[t] 必 miss=秒表不复活、_subLivePaint 喂不到卡
      // （轮询数据源本就在，卡在「行的键对不上」）。认回重挂真键后，
      // 轮询喂卡/过程计数/点击回放/完成通知四路全通
      const r = (_HG.rowById || {})[t] || _hgAgentRowFindByDesc(a);
      if (r && r.classList.contains('agentline')) {
        r.dataset.tid = t;            // 伪键重挂真键（'ag' 前缀与真 tid 无碰撞）
        _HG.rowById[t] = r;
        // v3.5.145（全审F2）：仅空时落——防覆写既有回放锚
        if (a.taskId && /^[0-9a-zA-Z_-]{8,64}$/.test(a.taskId) && !r.dataset.hgSubr)
          r.dataset.hgSubr = a.taskId;
        // v3.4.55 旧径保留：徽章画运行态；v3.5.143 秒表复活（时长连续不
        // 归零，t0 用档案起跑时刻——切走多久都不重计）
        try { _hgAgentRowBindAid(t, r); } catch (_) {}
        _hgAgentRowTimerRestart(r, a.t0 || Date.now());
      }
    }
    // v3.4.55（轻审 P3）：回放档案去重——同名（desc 相等）回放条目与 live
    // 运行条目并存会让目录同时出现在「正在运行」和「已结束」
    const _lvDescs = new Set(Object.values(lv).filter(a => !a.done && a.desc).map(a => a.desc));
    if (_lvDescs.size && _HG.dyn && Array.isArray(_HG.dyn.agentsRpl))
      _HG.dyn.agentsRpl = _HG.dyn.agentsRpl.filter(x => !(x.replay && x.desc && _lvDescs.has(x.desc)));
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
        <div class="hg-welcome-desc">直接输入开始新对话，或从左侧选择历史会话继续。<br>支持 📎 附件、@ 文件引用、⚡ 技能、🧠 模型切换。</div>
      </div>`;
  }
  function _hgMm(m) {
    return !!(_HG.models && (_HG.models.mm || []).includes(m));
  }
  async function refreshSessions() {
    try {
      const j = await (await fetch('/api/harness/sessions')).json();
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
        `<button class="hg-q-act" data-qact="edit" data-i="${i}" title="放回输入框编辑">✎</button>` +
        `<button class="hg-q-act" data-qact="del" data-i="${i}" title="丢弃">🗑</button>` +
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
  const _AGENT_LABEL = { executor: '执行', coder: '编程', designer: '设计', dev: '开发', reviewer: '审核', 'general-purpose': '通用子代理' };
