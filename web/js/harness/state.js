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
let _histBusy;
let queueEl;
let quoteEl;
let quoteBodyEl;
let qDrag;
let dynEl;              // v3.3：动态页伪 tab sc（_subDynOpen 懒建赋值；未建=null）
let _hgRolesCache;
let _dynRaf;
let _agentModelsTried;
let _subPaneEl;
let _subTabsEl;
let _subBodyEl;
let _subRes;
let _subX;
let visIndEl;
let visBtnEl;

  // a155：子代理切会话同步观测（用户拍板：先埋点不动逻辑）。
  // 症状=低概率「切走再切回，还在跑的子代理窗格显示完成/已停止」。
  // 诊断定位的三叉根因（见会话档案）：①桶 running 档被冷查询 done 条目
  // 顶掉（sendAt 随之丢）②sendAt 栅栏丢失后 readmodel 陈旧 done 畅通
  // ③readmodel 持续误判。两个点位（sessions 桶清理 / v4bridge 窗格定稿）
  // 拼起来可分辨：点位2 触发且 sendAt 缺失=①或②，点位1 是否先行区分之；
  // sendAt 在场且 > doneAt 仍定稿=③（栅栏判据没覆盖的写点）。
  // 零行为变化：只记账。环形 50 条 + console.warn 双出口，同键指纹去重
  // （2s 周期 Sync 不刷屏）；复现时控制台截图或 _HG._syncAudit 导出即铁证
  function _hgSyncAudit(kind, tid, fp, info) {
    try {
      _HG._syncAudit = _HG._syncAudit || { log: [], seen: {} };
      const key = kind + '|' + tid;
      if (_HG._syncAudit.seen[key] === fp) return;
      _HG._syncAudit.seen[key] = fp;
      const rec = Object.assign(
        { at: new Date().toISOString().slice(11, 23), kind: kind, tid: String(tid) },
        info || {});
      _HG._syncAudit.log.push(rec);
      if (_HG._syncAudit.log.length > 50) _HG._syncAudit.log.shift();
      console.warn('[子代理同步观测]', rec);
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
