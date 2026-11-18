// harness 共享可变状态 + 状态生命周期工具（v3.0 自 buildClaudeHarnessTab 闭包绑定
// 提升为脚本全局; DOM/查询类初始化赋值仍在 main.js 的 buildClaudeHarnessTab
// 内原位执行,时机不变）
// a151：原 sse.js 批G 退役后仅存的三件状态工具（清场/判史/排空）并入本文件
// ——sse.js 已删（其名源于 V3 旧 SSE 数据链，名不副实；历史实现见 git）

let _hgWrap;   // wrap → _hgWrap
let _hgConn;   // conn → _hgConn
let _hgQ;   // q → _hgQ
let _hgFlow;   // flow → _hgFlow
let _hgJumpBtm;   // jumpBtm → _hgJumpBtm（v3.2.8 一键跳底浮动钮）
let _hgRailEl;   // railEl → _hgRailEl（v3.2.10 回合导航轨）
let _railRaf = 0;   // rail active 刷新的 rAF 节流牌
let _hgInput;   // input → _hgInput
let _hgAskDockEl;   // askDock → _hgAskDockEl（v3.4.61 ask 面板 dock 容器）
let _hgStateEl;   // stateEl → _hgStateEl
let _hgCostEl;   // costEl → _hgCostEl
let _hgSendBtn;   // sendBtn → _hgSendBtn
let _hgTitleEl;   // titleEl → _hgTitleEl
let _hgCwdEl;   // cwdEl → _hgCwdEl
let _hgAttsEl;   // attsEl → _hgAttsEl
let _hgListEl;   // listEl → _hgListEl
let _hgSearchEl;   // searchEl → _hgSearchEl
let _hgFileEl;   // fileEl → _hgFileEl
let _hgOverlayEl;   // overlayEl → _hgOverlayEl
let _hgMentionEl;   // mentionEl → _hgMentionEl
let _hgActEl;   // actEl → _hgActEl
let _hgScrollBottom;   // scrollBottom → _hgScrollBottom
let _codeIO;
let _hgLeftNearBottom;
let _hgCtxInFlight;
let _hgCtxPollPending;   // 在途期间被请求的补跑（applyModel 立即拉取不被吞）
let _histBusy;
let queueEl;
let quoteEl;
let quoteBodyEl;
let qDrag;
let dynEl;              // v3.3：动态页伪 tab sc（_subDynOpen 懒建赋值；未建=null）
let _dynRaf;
let _subPaneEl;
let _subTabsEl;
let _subBodyEl;
let _subRes;
let _subX;
let visIndEl;
let visBtnEl;

  // a155R2（用户指路：走既有 ⓘ 诊断弹窗——顶栏小圆钮，点击显示版本+
  // 诊断日志流水）：子代理切会话同步观测写进 _hgDiag 环形日志，触发时
  // 静默记录，点 ⓘ 即看。_syncSeen 同状态去重（子引擎每帧状态推进都会
  // 重入点位，不去重会把 60 条诊断刷成同一句）。零行为变化：只记日志
  function _hgSyncAudit(kind, tid, msg) {
    try {
      var fp = kind + '|' + msg;
      _HG._syncSeen = _HG._syncSeen || {};
      if (_HG._syncSeen[tid] === fp) return;
      _HG._syncSeen[tid] = fp;
      _hgDiag('子代理同步·' + kind, msg + '（tid=' + tid + '）');
    } catch (_) {}
  }

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
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false; _HG.histCursor = 0;
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

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._hgHasHistory = _hgHasHistory;
window._hgSseResetLocal = _hgSseResetLocal;
window._hgSyncAudit = _hgSyncAudit;
window.saveCache = saveCache;
Object.defineProperty(window, '_codeIO', { configurable: true,
  get() { return _codeIO; }, set(v) { _codeIO = v; } });
Object.defineProperty(window, '_dynRaf', { configurable: true,
  get() { return _dynRaf; }, set(v) { _dynRaf = v; } });
Object.defineProperty(window, '_hgActEl', { configurable: true,
  get() { return _hgActEl; }, set(v) { _hgActEl = v; } });
Object.defineProperty(window, '_hgAskDockEl', { configurable: true,
  get() { return _hgAskDockEl; }, set(v) { _hgAskDockEl = v; } });
Object.defineProperty(window, '_hgAttsEl', { configurable: true,
  get() { return _hgAttsEl; }, set(v) { _hgAttsEl = v; } });
Object.defineProperty(window, '_hgConn', { configurable: true,
  get() { return _hgConn; }, set(v) { _hgConn = v; } });
Object.defineProperty(window, '_hgCostEl', { configurable: true,
  get() { return _hgCostEl; }, set(v) { _hgCostEl = v; } });
Object.defineProperty(window, '_hgCtxInFlight', { configurable: true,
  get() { return _hgCtxInFlight; }, set(v) { _hgCtxInFlight = v; } });
Object.defineProperty(window, '_hgCtxPollPending', { configurable: true,
  get() { return _hgCtxPollPending; }, set(v) { _hgCtxPollPending = v; } });
Object.defineProperty(window, '_hgCwdEl', { configurable: true,
  get() { return _hgCwdEl; }, set(v) { _hgCwdEl = v; } });
Object.defineProperty(window, '_hgFileEl', { configurable: true,
  get() { return _hgFileEl; }, set(v) { _hgFileEl = v; } });
Object.defineProperty(window, '_hgFlow', { configurable: true,
  get() { return _hgFlow; }, set(v) { _hgFlow = v; } });
Object.defineProperty(window, '_hgInput', { configurable: true,
  get() { return _hgInput; }, set(v) { _hgInput = v; } });
Object.defineProperty(window, '_hgJumpBtm', { configurable: true,
  get() { return _hgJumpBtm; }, set(v) { _hgJumpBtm = v; } });
Object.defineProperty(window, '_hgLeftNearBottom', { configurable: true,
  get() { return _hgLeftNearBottom; }, set(v) { _hgLeftNearBottom = v; } });
Object.defineProperty(window, '_hgListEl', { configurable: true,
  get() { return _hgListEl; }, set(v) { _hgListEl = v; } });
Object.defineProperty(window, '_hgMentionEl', { configurable: true,
  get() { return _hgMentionEl; }, set(v) { _hgMentionEl = v; } });
Object.defineProperty(window, '_hgOverlayEl', { configurable: true,
  get() { return _hgOverlayEl; }, set(v) { _hgOverlayEl = v; } });
Object.defineProperty(window, '_hgQ', { configurable: true,
  get() { return _hgQ; }, set(v) { _hgQ = v; } });
Object.defineProperty(window, '_hgRailEl', { configurable: true,
  get() { return _hgRailEl; }, set(v) { _hgRailEl = v; } });
Object.defineProperty(window, '_hgScrollBottom', { configurable: true,
  get() { return _hgScrollBottom; }, set(v) { _hgScrollBottom = v; } });
Object.defineProperty(window, '_hgSearchEl', { configurable: true,
  get() { return _hgSearchEl; }, set(v) { _hgSearchEl = v; } });
Object.defineProperty(window, '_hgSendBtn', { configurable: true,
  get() { return _hgSendBtn; }, set(v) { _hgSendBtn = v; } });
Object.defineProperty(window, '_hgStateEl', { configurable: true,
  get() { return _hgStateEl; }, set(v) { _hgStateEl = v; } });
Object.defineProperty(window, '_hgTitleEl', { configurable: true,
  get() { return _hgTitleEl; }, set(v) { _hgTitleEl = v; } });
Object.defineProperty(window, '_hgWrap', { configurable: true,
  get() { return _hgWrap; }, set(v) { _hgWrap = v; } });
Object.defineProperty(window, '_histBusy', { configurable: true,
  get() { return _histBusy; }, set(v) { _histBusy = v; } });
Object.defineProperty(window, '_railRaf', { configurable: true,
  get() { return _railRaf; }, set(v) { _railRaf = v; } });
Object.defineProperty(window, '_subBodyEl', { configurable: true,
  get() { return _subBodyEl; }, set(v) { _subBodyEl = v; } });
Object.defineProperty(window, '_subPaneEl', { configurable: true,
  get() { return _subPaneEl; }, set(v) { _subPaneEl = v; } });
Object.defineProperty(window, '_subRes', { configurable: true,
  get() { return _subRes; }, set(v) { _subRes = v; } });
Object.defineProperty(window, '_subTabsEl', { configurable: true,
  get() { return _subTabsEl; }, set(v) { _subTabsEl = v; } });
Object.defineProperty(window, '_subX', { configurable: true,
  get() { return _subX; }, set(v) { _subX = v; } });
Object.defineProperty(window, 'dynEl', { configurable: true,
  get() { return dynEl; }, set(v) { dynEl = v; } });
Object.defineProperty(window, 'qDrag', { configurable: true,
  get() { return qDrag; }, set(v) { qDrag = v; } });
Object.defineProperty(window, 'queueEl', { configurable: true,
  get() { return queueEl; }, set(v) { queueEl = v; } });
Object.defineProperty(window, 'quoteBodyEl', { configurable: true,
  get() { return quoteBodyEl; }, set(v) { quoteBodyEl = v; } });
Object.defineProperty(window, 'quoteEl', { configurable: true,
  get() { return quoteEl; }, set(v) { quoteEl = v; } });
Object.defineProperty(window, 'visBtnEl', { configurable: true,
  get() { return visBtnEl; }, set(v) { visBtnEl = v; } });
Object.defineProperty(window, 'visIndEl', { configurable: true,
  get() { return visIndEl; }, set(v) { visIndEl = v; } });
