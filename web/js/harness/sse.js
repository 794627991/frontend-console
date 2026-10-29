// harness sse.js —— 批G 退役后仅存旧链共用件（v4 唯一数据链 /v4/stream）。
// 原 handleEvent/openSSE/_hgSseRebuild/ka 看门狗/快照写体/_hgEventsPoll 等
// V3 数据链已删（a138，用户拍板「V4 唯一基准」）；本文件只剩三件仍被
// v4 活路径消费的清场/判史/排空工具（历史实现见 git）。
  function _hgSseResetLocal(keepDom) {
    _HG.fetchedBusy = null;   // C组T5：随清场清（防陈旧值误用）
    // 清场：内存态与 DOM 全部作废（switchTo 的重置块同款，供 snapshot/reset 用）
    // v3.5.196：keepDom=true 时跳过 flow 清空（reload 重建用）——旧 DOM 保留
    // 到渲染器原子换入，消除「清场→新内容换入」之间的白屏空窗（用户实锤
    // 「连着两个 300ms 空闲帧=体感卡顿」：原清场先清 DOM 再等 fetch+渲染）
    // v3.5.123：hold 旗随清场（切走的会话若在 hold，回切由 replay 的 turn_hold 重建）
    _HG.hold = false;
    endThinking(); closeRun();
    // v3.4.55（轻审 P4）：清 agents 前运行档案入桶——reset/快照重建路
    // 同样暂存（switchTo 同款判据），重建完成后 _hgLiveAgentsRestore 回填
    if (_HG.agents && _HG.sid) {
      _HG.liveAgentsBy = _HG.liveAgentsBy || {};
      const _tgt = (_HG.liveAgentsBy[_HG.sid] = _HG.liveAgentsBy[_HG.sid] || {});
      for (const t in _HG.agents) {
        const a = _HG.agents[t];
        if (a && !a.done && (!a.sid || a.sid === _HG.sid)) _tgt[t] = a;
      }
    }
    if (_HG.grp) phStopTimer(_HG.grp);
    _turnHeadStop();   // v3.2：回合秒表随清场全收（timer 不随 innerHTML 快照走，不收就漏）
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;
    _HG.subTail = {};   // 批4：subRows/subBlk/subTailSeg 随段退役删；subTail 账本保留
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false; _HG.histStale = false; _HG.histCursor = 0;
    _HG.archivedTurns = 0;   // v3.5.61：归档轮数随清场归零（切会话由 hist 重算）
    _HG.todos = null; _HG.agents = null; _HG.dyn = null;
    // v3.4.54：识图 pending 线随清场收（switchTo 重置块同款——两处必须同步）
    Object.values(_HG.visionCalls || {}).forEach(_hgPeerLineStop);
    _HG.visionCalls = null;
    _HG.proj = null;   // v3.1：投影随清场作废（snapshot 重放将重建）
    _subReset();
    _HG.think = null; _HG.noScroll = false; _HG.openState = null;
    _HG.stickBtm = true;   // v3.4.67：粘底跟读态随清场复位（重建后默认贴底）
    _HG.histLineTs = 0; _HG.histActTs = 0; _HG.thinkPend = null;   // v3.2.2 ts 账 + v3.2.5 pend 随清场作废
    _HG.prevRowAt = 0; _HG.lastRowAt = 0;   // v3.3.1(F5)：事件时刻账随清场作废
    _HG.echoFast = null; _HG.seq = 0;
    if (!keepDom) _hgFlow.innerHTML = '';
    _hgRailSync();   // v3.2.10：本地清场后收轨（keepDom 时轨随渲染器换入后同步）
  }
  function _hgHasHistory(sid) {
    const s = _HG.sessions.find(x => x.sid === sid);
    return !!(s && s.has_history);
  }
  function saveCache() {
    // v3.5.51（designer B2）：只读模式防毒化——RO 渲染的是目标会话 DOM，
    // 此刻入库会把 B 的内容写进 A(_HG.sid) 的快照；RO 中关页/切换路径防御
    if (_HG.readonly) return;
    if (!_HG.sid) return;
    // v4 唯一管线：旧 innerHTML 快照零读点，只负责把存量（V3 时代遗留）
    // 排进 30s 保温销毁——不再写新快照（内存批定调，数十 MB ×10 份纯浪费）
    const warm = _HG.cacheWarm || (_HG.cacheWarm = {});
    for (const k of Object.keys(_HG.cache)) {
      if (warm[k]) continue;
      warm[k] = setTimeout(() => {
        delete warm[k];
        delete _HG.cache[k];
      }, 30000);
    }
  }
