/* v4bridge —— 投影 → V3 渲染管线适配层（路线修正版，替代 v4view）。
 *
 * 定位：V4 只是数据源，渲染 100% 由 V3 现有代码驱动（用户铁律：严格参照
 * 现有布局）。数据归一（投影单源/服务端裁决）在 store 层完成，本层只做
 * 「投影行 → V3 行/入口」的翻译：
 *
 *   snapshot 帧  → lines 翻译 → _histRender（V3 整窗：20 回合窗口/懒填/
 *                  归档条/组头定稿/导轨/时间条全套原件）
 *   row.appended → user/assistant/thinking：_hgRowAdd（V3 单账入口：入账
 *                  +游标泵+live 动画+phStart 占位+组头秒表全套）
 *                  tool running：renderToolUse（V3 live run 形态+_tlPlace
 *                  +rowById 注册，终态回写锚）
 *   row.upserted → tool 终态：renderOneToolResult（V3 回写链：徽章/agent
 *                  摘要/组头冒泡/折叠体）；turn_header 终态：grpFinalize
 *   row.delta    → appendThinking（V3 思考滚播）
 *   state.updated→ setBusy/askRender/askDone/renderQueue（V3 原函数）
 *
 * 禁止：本层不创建任何消息行 DOM（全部经 V3 渲染函数）、不读不写 V3 状态
 * 机之外的旁路状态。V3 账本（histAll/histCursor）即渲染账本，v4 不另设。
 */
(function (root) {
  'use strict';

  function _g(name) { return typeof root[name] !== 'undefined' ? root[name] : null; }

  function _iso(at) {
    try { return at ? new Date(at).toISOString() : ''; } catch (e) { return ''; }
  }

  // v4 投影行 → V3 transcript line（renderHistLine/renderHistTool 消费形态）
  function rowToLine(row) {
    if (!row) return null;
    var k = row.kind, L = {};
    if (k === 'user_input') {
      L.role = 'user'; L.text = row.text || '';
      L.files = row.files || [];
      L.images = Array.isArray(row.images) ? row.images : [];
    } else if (k === 'assistant_text') {
      L.role = 'assistant'; L.text = row.text || ''; L.model = row.model || '';
    } else if (k === 'reasoning') {
      L.role = 'thinking'; L.text = row.text || '';
    } else if (k === 'tool_call') {
      L.role = 'tool'; L.text = row.tool || ''; L.tid = row.tid || '';
      L.summary = row.summary || ''; L.input = row.input || {};
      L.result = row.output || '';
      if (row.status === 'error') L.err = true;
      if (row.dln) L.dln = row.dln;
    } else if (k === 'marker') {
      // 系统提示不占位（用户拍板 a39）：纯注入提示行不画（feed skind 标记
      // task-notification 除外——后台代理完成通知有摘要信息量）
      if (row.mkind === 'sysnote'
          && row.skind !== 'task-notification') return null;
      L.role = (row.mkind === 'exit' || row.mkind === 'interrupted') ? 'exit'
        : row.mkind;                        // renew/sysnote/audit
      L.text = row.text || '';
    } else if (k === 'peer_notify') {
      // 用户拍板（a17 二次裁决，推翻 423/424 的通知行约定）：协作回传胶囊
      // 「📥 协作回传·xx：」整体退役——主窗消息流不画（结论载体=Agent 工具
      // 行卡/对端转写，通知行是冗余通道）。一律不翻译
      return null;
    } else if (k === 'vision') {
      L.role = 'vision_relay'; L.prompt = row.prompt || ''; L.src = row.src || '';
      L.chan = row.chan || ''; L.tid = row.tid || ''; L.dur = row.dur || 0;
    } else {
      return null;                          // turn_header/subagent：由收口路处理
    }
    L.ts = _iso(row.at);
    return L;
  }

  function V4Bridge(store, flowEl, opt) {
    var self = this;
    this.store = store;
    this.flow = flowEl;
    this.opt = opt || {};
    this.conclEl = this.opt.conclEl || null;
    this.conclDone = false;
    this._lastBusy = undefined;
    this._lastRole = null;
    // a65 子 pane 专用态（渲染引擎见 _subRebuild 族）
    this._t = null;            // 当前轮时间线对象（subpane kit 形态）
    this._openTools = [];      // V3 兜底行的 FIFO 结果配对队列
    this._fbTried = false;     // /subagent_replay 兜底只试一次
    this._firstAt = 0;         // 首行时刻（轮时长口径）
    this._lastAt = 0;          // 末行时刻（统一在 _subAppend 记账）
    this._pend = [];           // a70：开口思考段（时长回填用，V3 pend 对位）
    this._conclLocked = false; // a74：真结论（state.final）锁定后结论区不再动
    this._notifyTimer = null;  // a74：subNotify 宽限定时器
    this._t0Note = false;      // a74：空态注记期 t0 是兜底值——首行到达重锚
    this._emptyAt = 0;         // a74：空态注记时刻（20s 零行保险带计时基）
    this._lastRowAt = 0;        // a77：最近一次行到达时刻（防定格看门狗计时基）
    this._subTick = null;      // 子 pane 秒表 interval（v4 无 V3 tick）
    this.unsub = store.subscribe(function (ev) { self._onEv(ev); });
  }

  V4Bridge.prototype.close = function () {
    if (this.unsub) { this.unsub(); this.unsub = null; }
    if (this._notifyTimer) { clearTimeout(this._notifyTimer); this._notifyTimer = null; }
    this._subWatchStop();
  };

  V4Bridge.prototype._onEv = function (ev) {
    var kind = ev && ev.kind;
    // a65（红线：子代理内容绝不进主窗）：子 pane 全部事件走独立渲染引擎
    // （V3 subpane kit，落点只在窗格容器），主窗函数一条不可达
    if (this.opt.sub) {
      if (kind === 'snapshot') this._subRebuild(ev.snap);
      else if (kind === 'deltas') {
        var ds = ev.deltas || [];
        for (var i = 0; i < ds.length; i++) this._subApplyOne(ds[i]);
      }
      return;
    }
    if (kind === 'snapshot') this._rebuild(ev.snap);
    else if (kind === 'deltas') {
      var ds2 = ev.deltas || [];
      for (var j = 0; j < ds2.length; j++) this._applyOne(ds2[j]);
    }
  };

  // ---- snapshot：V3 整窗原件一次调用（窗口/懒填/归档/定稿/导轨全套） -------

  V4Bridge.prototype._rebuild = function (snap) {
    var rows = (snap && snap.rows) || [];
    // a62（用户实测致命「子页开着主窗历史全消失/新消息 3s 消失」）：空
    // 快照防御——本会话已有内容而快照零行（feed 冷建 hydration 失败/
    // 重连竞速）时拒绝整窗重建，保住现有 DOM；服务端同步有不缓存空投影
    // 的对位防御，下帧权威快照到达自然覆盖
    if (!rows.length && !this.opt.sub
        && typeof _HG !== 'undefined'
        && Array.isArray(_HG.histAll) && _HG.histAll.length) {
      try { (root.console && console.warn) && console.warn(
        '[v4bridge] 空快照拒建（保留 ' + _HG.histAll.length + ' 行）'); } catch (e) {}
      return;
    }
    var lines = [];
    var _prevMk = null;
    for (var i = 0; i < rows.length; i++) {
      var rw = rows[i];
      // 存量投影防御（a33 前的双行）：紧跟 exit 行的 interrupted marker 跳过
      // ——回放侧 turn_interrupted 编排会 grpEnsure 建空组定稿=「已工作 0 秒」
      // 孤儿组（feed 已改为合并单行，此为旧投影兜底）
      if (rw && rw.kind === 'marker' && rw.mkind === 'interrupted'
          && _prevMk === 'exit') { _prevMk = rw.mkind; continue; }
      if (rw && rw.kind === 'marker') _prevMk = rw.mkind;
      else _prevMk = null;
      var L = rowToLine(rw);
      if (L) lines.push(L);
    }
    if (typeof _HG !== 'undefined' && !this.opt.sub) {
      // 全局账只由主窗 bridge 写（用户实测「归档条恒前1轮」根因：子 pane
      // rebuild 无差别覆盖 _HG.histAll/seq/epoch/histArchiveTurns——子投影
      // 值污染主窗，一批玄学渲染问题的共同源头）。子 bridge 只渲染自己容器
      _HG.histAll = lines;                  // V3 账本即渲染账本
      _HG.seq = snap ? snap.seq : 0;
      _HG.epoch = (snap && snap.epoch) || _HG.epoch;
      // 归档轮真源（服务端全量数）：归档条「前 N 轮」不再按尾窗 lines 瞎数
      _HG.histArchiveTurns = (snap && snap.turnsTotal) || 0;
    }
    // running 态子代理行补建档案（等价 V3 liveAgentsBy 桶恢复）：busy 会话
    // 切回后胶囊/目录才有「子代理执行中」。完成态不建——回放行卡由
    // renderHistTool 定格，目录走 registry 冷查询（与 V3 整窗路同口径）
    for (var j = 0; j < rows.length; j++) {
      if (rows[j] && rows[j].kind === 'subagent'
          && rows[j].status === 'running') this._agentFile(rows[j]);
    }
    // a62 诊断埋点：复现「主窗消失」时可读 window.__v4dbg 定位空/异常快照
    try {
      root.__v4dbg = root.__v4dbg || [];
      root.__v4dbg.push({ t: Date.now(), sub: !!this.opt.sub,
                          rows: rows.length, lines: lines.length,
                          turns: (snap && snap.turnsTotal) || 0 });
      if (root.__v4dbg.length > 30) root.__v4dbg.shift();
    } catch (e) {}
    var win = _g('_hgHistWinStart');        // V3 20 回合窗口起点
    var start = win ? win(lines, 0) : 0;
    var busy = !!(snap && snap.state && snap.state.busy);
    var render = _g('_histRender');
    if (render) {
      // busy 会话切回：noFinalize 留活组（对齐 V3 sessions.js:534）——写死
      // false 会把进行中的尾组定稿，后续 live delta 落入幽灵新组（用户实测
      // 「A切B切A 工作组错乱」）
      try { render(lines, start, { noFinalize: busy }); } catch (e) {
        (root.console && console.error) && console.error('[v4bridge] rebuild', e);
      }
    }
    if (busy) {
      // V3 快照路同款恢复（sessions.js:362）：占位气泡+组头秒表认回接续
      var pr = _g('phResume');
      if (pr) { try { pr(true); } catch (e) {} }
    }
    // 打开会话强制贴底（用户实测「打开会话不置底」）：渲染后布局仍会变
    // （懒体/折叠），rAF 双贴等布局稳定
    var box = this.flow;
    if (box) {
      try { box.scrollTop = box.scrollHeight; } catch (e) {}
      requestAnimationFrame(function () {
        try { box.scrollTop = box.scrollHeight; } catch (e) {}
      });
    }
    if (snap && snap.state) this._paintState(snap.state, true);
    // a55：子代理冷查询派生（ZCode registry 域）——镜像事件不落转写，重启/
    // 重建后投影的 agentline 行永远 running 且缺 hgSubr=假运行+点不开
    //（用户实测致命三症结）。磁盘唯一真源=/api/harness/agents（readmodel
    // 现算 agents 表+tidMap），回放卡的状态/hgSubr/档案计时全部从它回填
    if (!this.opt.sub) this._agentsColdSync();
  };

  // 冷查询派生：tidMap(tid→agentId)+agents 表 → 行卡 hgSubr/终态徽章+
  // _HG.agents 档案（目录/胶囊/点开全链复活）
  V4Bridge.prototype._agentsColdSync = function () {
    if (typeof _HG === 'undefined' || !_HG.sid) return;
    var _sid = _HG.sid;
    fetch('/api/harness/agents?sid=' + encodeURIComponent(_sid))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok || _HG.sid !== _sid) return;
        var tm = j.tidMap || {};
        var ags = j.agents || {};
        _HG.agents = _HG.agents || {};
        var _seenAid = {};
        for (var tid in tm) {
          var aid = tm[tid];
          // a57：同 agentId 多 tid（续派/镜像重发）只建一份档案——逐 tid 建
          // 会让目录出现重复条目（用户实测「每个子代理都有一个重名的」）
          if (_seenAid[aid]) continue;
          _seenAid[aid] = tid;
          var ent = ags[aid];
          if (!ent) continue;
          var a = _HG.agents[tid] || (_HG.agents[tid] = {});
          a.taskId = aid;
          a.type = a.type || ent.type || 'Task';
          if (ent.desc) a.desc = a.desc || ent.desc;
          var _running = ent.status === 'running';
          a.done = !_running;
          a.err = ent.status === 'err';
          // a65：结论摘要随档（readmodel brief）——子 pane 结论区回退源与
          // 目录行卡摘要在冷同步会话（重启/切回）同源补齐
          if (!a.result && ent.brief) a.result = String(ent.brief).slice(0, 400);
          var _t0 = Number(ent.t0) || 0;
          a.t0 = a.t0 || (_t0 > 1e12 ? _t0 : _t0 * 1000) || Date.now();
          a.doneAt = a.done ? ((Number(ent.doneAt) || 0) > 1e12
            ? Number(ent.doneAt) : (Number(ent.doneAt) || 0) * 1000) : 0;
          // 行卡回写：hgSubr（点开钥匙）+未终态行翻徽章
          var row = (_HG.rowById || {})[tid];
          if (row) {
            if (typeof _hgAgentRowBindAid === 'function')
              _hgAgentRowBindAid(tid, row);
            if (a.done && row.dataset.final !== '1'
                && typeof _hgAgentRowState === 'function')
              _hgAgentRowState(tid, a.err, ent.brief || '');
          }
          // a60：回放档（dyn.agentsRpl）agentId 回填——历史行派生时 aid 未
          // 知=条目 agentId 空，目录点击走 _subDirRowClick isRpl 分支必报
          // 「无 agentId 无法回放」（用户实测「还是点不开」的真正入口）；
          // 同任务（desc 前 40 字与档案一致）即回填钥匙
          var _rpl = ((_HG.dyn || {}).agentsRpl) || [];
          for (var ri = 0; ri < _rpl.length; ri++) {
            var rr = _rpl[ri];
            if (!rr.agentId && rr.type === a.type
                && String(rr.desc || '').slice(0, 40)
                  === String(a.desc || '').slice(0, 40)) {
              rr.agentId = aid;
              if (!rr.taskId) rr.taskId = aid;
            }
          }
        }
        if (typeof renderSideStatus === 'function') renderSideStatus();
      })
      .catch(function () {});
  };

  // ---- deltas：翻译成 V3 原生入口 ----------------------------------------

  // ---- V3 档案链（sse.js task_started 同款语义） ---------------------------
  // _HG.agents 是胶囊（_hgAgentsRunning）/子代理目录/行卡终态
  // （_hgAgentRowState）/窗格下钻（hgSubr 回写）四链共同真源。v4 下旧 SSE
  // 不跑，档案无人建档=用户实测四个致命问题（胶囊不显示子代理/目录空/
  // 行卡无名点不开/秒表永跑）的共同根因——bridge 必须补建
  V4Bridge.prototype._agentFile = function (row) {
    if (!row || this.opt.sub) return;
    var tid = row.tid || '';
    if (!tid || typeof _HG === 'undefined') return;
    var aid = String(row.childTopic || '').replace(/^sub:/, '');
    _HG.agents = _HG.agents || {};
    var a = _HG.agents[tid] || (_HG.agents[tid] = {});
    a.type = row.agentType || a.type || 'Task';
    if (row.summary) a.desc = row.summary;
    // a54：at 数字 ms 兼容（hub _ts_ms ISO 优先数字兜底——Date.parse(纯数字)
    // =NaN 致 t0 恒 Date.now()=目录/胶囊计时从重建时刻起算的「14s 异常」）
    var _rt = row.at;
    var _t0v = (typeof _rt === 'number') ? _rt
      : (_rt ? (Date.parse(_rt) || 0) : 0);
    a.t0 = a.t0 || (_t0v || Date.now());
    a.done = false; a.doneAt = 0;
    if (aid && /^[0-9a-zA-Z_-]{8,64}$/.test(aid)) {
      a.taskId = aid;
      // sse.js 冷查询批1 同款映射：_hgAg/_subTid 单点解析读它
      _HG.tidMap = _HG.tidMap || {}; _HG.tidMap[tid] = aid;
      _HG.aidKey = _HG.aidKey || {};
      if (!_HG.aidKey[aid]) _HG.aidKey[aid] = tid;
      // agentId 即刻回写行卡（审计F1：切会话后行自带 hgSubr 是回放唯一锚）
      if (typeof _hgAgentRowBindAid === 'function')
        _hgAgentRowBindAid(tid, (_HG.rowById || {})[tid]);
      // a75（用户要求「主窗口显示子代理实况」对齐 V3）：agentId 到手即开
      // 实况窗格——sse.js:186 同款（V3 语义：派发后窗格自动呈现思考/工具
      // 过程，不等用户点胶囊）；_subEnsure 幂等（rpN/3s 节流）
      var _se = _g('_subEnsure');
      if (_se) { try { _se(tid); } catch (e) {} }
    }
    var rss = _g('renderSideStatus');
    if (rss) { try { rss(); } catch (e) {} }
    // a75：胶囊事件级刷新（panel 有 tick 兜底，事件级让「派出→亮、结束→
    // 灭」即时同步主窗）
    var _cap = _g('_hgDynCapsulePaint');
    if (_cap) { try { _cap(); } catch (e) {} }
  };

  // 思考段收口（V3 sse.js:335/:339 语义：text 块与 tool_use 块到达前
  // endThinking）。bridge 曾只在正文行前收——工具行分支提前 return 不收口，
  // 连续「思考→工具→思考」的中间段全挂「思考中…」活标签（用户实测
  // 「思考不结束」，仅末段被正文收口）
  V4Bridge.prototype._closeThink = function () {
    if (this._lastRole !== 'thinking') return;
    // 收口段打 raw 懒标（V3 _histLazyDrop/Fill raw 路同款语义）：live
    // 段无标记时收起不敢丢=内容永驻，20 轮后全量 DOM 拖垮开合动画
    //（用户实测「点开/收起思考明显卡顿」——V3 靠 hist 重建懒化，v4
    // 全程 live 从不重建）。raw 全文直存段上，fill/drop 原件零改动
    if (typeof _HG !== 'undefined' && _HG.think && _HG.think.seg
        && Array.isArray(_HG.histAll)) {
      var _sg = _HG.think.seg;
      if (_sg && _sg.dataset.raw == null) {
        for (var ti = _HG.histAll.length - 1; ti >= 0; ti--) {
          var _tl = _HG.histAll[ti];
          if (_tl && _tl.role === 'thinking') {
            _sg.dataset.raw = String(_tl.text || '');
            break;
          }
        }
      }
    }
    var eT = _g('endThinking'), cR = _g('closeRun');
    if (eT) { try { eT(); } catch (e) {} }
    if (cR) { try { cR(); } catch (e) {} }
    this._lastRole = null;
  };

  // a46：a42 特判卡（_askCardBuild）已退役——ask_user 注册进 V3 配置表
  // （base.js _H_TOOL_CFG kind:'question'），live/回放全场景同一张配置卡，
  // 体=题目+选项 chip（_toolInputBodyHtml question 分支现成件），回答走
  // result 常规链。真正的归一

  V4Bridge.prototype._applyOne = function (d) {
    var op = d.op;
    if (op === 'row.appended') {
      var row = d.row, live = true;
      if (row.kind === 'subagent') { this._agentFile(row); return; }
      // 识图回传代播（V3 relay/store peer_return 原件链）：name 含「识图」
      // → dispatch peer_return——visionCalls[tid]/FIFO 配对 hit→卡定格+结论
      // md 入卡；miss→renderPeer（识图分支同配对，全 miss 静默）。非识图
      // peer 通知行退役（a17 用户拍板），不进消息流
      if (row.kind === 'peer_notify') {
        if (String(row.name || '').indexOf('识图') !== -1) {
          var _dp = _g('_hgDispatch');
          if (_dp) {
            try { _dp({ t: 'peer_return', name: row.name || '识图',
                        text: row.text || '', tid: '' }); } catch (e) {}
          }
        }
        return;
      }
      // 转写 vision_relay 回放行（hydration）：走 V3 回放同构卡；busy 会话
      // 未回传卡需复活 run 态+续表（histBusy 前置——live 期它是上次 rebuild
      // 的旧值恒 false，不置则「历史未完成」死案=秒表消失）
      if (row.kind === 'vision') {
        var _rvh = _g('renderVisionRelayHist');
        if (_rvh) {
          if (typeof _HG !== 'undefined' && !row.dur) _HG.histBusy = true;
          var _vl = rowToLine(row);
          if (_vl) { try { _rvh(_vl); } catch (e) {} }
        }
        return;
      }
      // exit/interrupted live 收尾（V3 sse.js:1124/1166 分支等价）：绝不能走
      // _hgRowAdd——renderHistLine 对 exit 行 dispatch 硬编码 hist:true，会
      // 在 live 时刻触发回放侧编排 grpEnsure(true)+grpFinalize
      //（store.js turn_interrupted 分支）凭空建空组定稿=「已工作 0 秒」
      // 孤儿组（用户实测截图实锤，372-380 区间 marker 行触发）
      if (row.kind === 'marker'
          && (row.mkind === 'exit' || row.mkind === 'interrupted')) {
        var _fin = _g('endThinking');
        if (_fin) { try { _fin(); } catch (e) {} }
        var _vs = _g('_hgVisionSweep');
        if (_vs) { try { _vs(true); } catch (e) {} }
        var _re = _g('renderExit');
        if (_re) { try { _re(row.text || ''); } catch (e) {} }
        // 无活组早退（grpFinalize 语义）——绝不 grpEnsure 建组
        var _gf = _g('grpFinalize');
        if (_gf) {
          try { _gf(true, { interrupted: row.mkind === 'interrupted',
                            turnEnd: true }); } catch (e) {}
        }
        var _ad = _g('_hgAskDismiss');
        if (_ad) {
          var _dk = (typeof _hgAskDockEl !== 'undefined') ? _hgAskDockEl : null;
          var _op = _dk && _dk.querySelector('.h-ask:not(.done)');
          if (_op) { try { _ad(_op, row.mkind === 'interrupted'
                            ? '已随会话中断失效' : '已随会话结束失效'); } catch (e) {} }
        }
        var _sw = _g('_hgAgentsSweep');
        if (_sw) { try { _sw(true); } catch (e) {} }
        var _sb2 = _g('setBusy');
        if (_sb2) { try { _sb2(false); } catch (e) {} }
        return;
      }
      // 切模型分割线（V3 sse.js:1184 等价）：renderHistLine 无 model_switched
      // 分支（V3 live 专有渲染，转写回放不画），走 _hgRowAdd 白入账不显示
      //（用户实测「切换模型没有在前端显示」）——live 到达直接调 renderSwitch
      if (row.kind === 'marker' && row.mkind === 'model_switched') {
        var _rsw = _g('renderSwitch');
        if (_rsw) { try { _rsw(row.text || ''); } catch (e) {} }
        this._lastRole = null;
        return;
      }
      var L = rowToLine(row);
      if (!L) return;
      if (row.kind === 'tool_call' && row.status === 'running') {
        this._closeThink();   // V3 sse.js:339：tool_use 前收思考段
        // a46：ask_user 不再特判——已在 V3 配置表注册（base.js _H_TOOL_CFG，
        // kind:'question'），renderToolUse 走配置卡，live/回放全场景归一
        // 识图双通道（V3 sse.js:382 同款分流）：识图工具不走普通工具卡——
        // 折叠卡（prompt 摘要+「识图中」徽章+运行秒表）+visionCalls 注册
        //（回传配对锚）+组头计数。秒表曾因此链断而消失（用户实测）
        var _vn = row.tool || '';
        if (_vn === 'mcp__vision__analyze_image'
            || _vn === 'mcp__4_5v_mcp__analyze_image') {
          var _cb = _g('_hgVisionCardBuild');
          if (_cb) {
            var _inp = {};
            var _src = row.input || {};
            for (var _k in _src) _inp[_k] = _src[_k];
            _inp.__tid = row.tid || '';
            _inp.__chan = (_vn === 'mcp__vision__analyze_image'
                           ? '兜底' : '主');
            try {
              var _card = _cb(_inp);
              var _tp = _g('_tlPlace');
              if (_tp) _tp(_card, _vn, _src);
              if (typeof _HG !== 'undefined' && row.tid) {
                _HG.visionCalls = _HG.visionCalls || {};
                _HG.visionCalls[row.tid] = _card;
                var _gg = _HG.grp;
                if (_gg) {
                  _gg.counts = _gg.counts || {};
                  _gg.counts.visionN = (_gg.counts.visionN || 0) + 1;
                  var _ths = _g('_turnHeadSubPaint');
                  if (_ths) { try { _ths(_gg); } catch (e) {} }
                }
              }
              var _pt = _g('_hgPeerTimerStart');
              if (_pt) _pt(_card, Date.now());
            } catch (e) {}
          }
          return;
        }
        // V3 live 工具行：run 形态建卡（终态回写锚=rowById[tid]）
        var rT = _g('renderToolUse');
        if (rT) { try { rT({ id: row.tid || '', name: row.tool || '',
                             input: row.input || {} }, false); } catch (e) {} }
        // 行内运行秒表（用户期望，ZCode toolCall 形态）：行尾「N s」，终态
        // upsert 时 renderOneToolResult 重写 slots 自然替换；interval 挂在
        // span 上、随 DOM 摘除自杀
        var el = (typeof _HG !== 'undefined' && _HG.rowById)
          ? _HG.rowById[row.tid || ''] : null;
        var sl = el && el.querySelector('.h-tslots');
        if (sl && !sl.querySelector('.hg-tdur-run')) {
          var _t0 = row.startedAt || Date.now();
          var sp = document.createElement('span');
          sp.className = 'hg-tdur-run';
          sp.style.cssText = 'opacity:.85;font-size:.85em;margin-left:6px';
          sl.appendChild(sp);
          var _tick = function () {
            if (!sp.isConnected) { clearInterval(sp._tmr); return; }
            sp.textContent = Math.max(0, Math.round((Date.now() - _t0) / 1000)) + 's';
          };
          sp._tmr = setInterval(_tick, 1000);
          _tick();
        }
        return;
      }
      if (live) L.live = 1;                 // V3 live 语义（动画/占位/组头）
      // 思考段收口对齐 V3 sse（:335）：正文行到达前收段
      if (L.role !== 'thinking') this._closeThink();
      this._lastRole = L.role;
      var add = _g('_hgRowAdd');
      if (add) { try { add(L); } catch (e) {} }
    } else if (op === 'row.upserted') {
      // a54：subagent 行 upsert 且仍 running=aid 后到补绑（feed 2s Sync 重发
      // 镜像）——补档案映射+BindAid 回写行卡 hgSubr（可点开的钥匙）
      if (d.row && d.row.kind === 'subagent' && d.row.status === 'running')
        this._agentFile(d.row);
      this._upsert(d.row);
    } else if (op === 'row.delta') {
      var aT = _g('appendThinking');
      if (aT && d.append) { try { aT(d.append); } catch (e) {} }
    } else if (op === 'row.removed') {
      // rewind 换代走 epoch（store 重订阅 snapshot），此处仅防御
    } else if (op === 'state.updated') {
      this._paintState(d.patch || {}, false);
    }
  };

  V4Bridge.prototype._upsert = function (row) {
    if (!row) return;
    if (row.kind === 'tool_call') {
      // 识图终态（V3 sse.js:598 同款）：visionCalls 配对 hit→卡定格+结论
      // 入卡（md 懒存 vres 点开渲染）；不走普通工具行收口
      if (typeof _HG !== 'undefined' && _HG.visionCalls && row.tid
          && _HG.visionCalls[row.tid]) {
        var _vc = _HG.visionCalls[row.tid];
        delete _HG.visionCalls[row.tid];
        var _vr2 = _g('_hgVisionResult');
        if (_vr2) { try { _vr2(_vc, row.output || '',
                               row.status === 'error'); } catch (e) {} }
        return;
      }
      var r1 = _g('renderOneToolResult');
      if (r1 && row.tid) {
        try { r1({ tool_use_id: row.tid, content: row.output || '',
                   is_error: row.status === 'error' }); } catch (e) {}
      }
      // 运行秒表收口（a25 泄漏修复）：renderOneToolResult 对 completed 刻意
      // 不写 slots（P0-1 防噪门）——秒表 span 无人替换=永跳。终态时主动
      // 换成「徽章+静态耗时」（无 interval）
      if (typeof _HG !== 'undefined' && _HG.rowById) {
        var el2 = _HG.rowById[row.tid];
        var sl2 = el2 && el2.querySelector('.h-tslots');
        var run = sl2 && sl2.querySelector('.hg-tdur-run');
        if (run) {
          var sb2 = _g('statusBadge');
          var _ms = (row.endedAt && row.startedAt && row.endedAt > row.startedAt)
            ? row.endedAt - row.startedAt : 0;
          var _dur = _ms ? (_ms < 10000 ? (_ms / 1000).toFixed(1) + 's'
                                        : Math.round(_ms / 1000) + 's')
                         : (run.textContent || '0s');
          sl2.innerHTML = (sb2 ? sb2(row.status === 'error' ? 'error' : 'completed') : '')
            + ' <span class="hg-tdur-run" style="opacity:.85;font-size:.85em">' + _dur + '</span>';
        }
      }
      // 失败标记归行（用户定调「不要换行，保持和思考同高度」）：V3 把
      // .h-tool-failmark 插行元素末尾——col 折叠卡（bash/PowerShell）里
      // head 是独立行，行尾插=掉到卡下方另起一行；移进 head 行内尾随
      if (typeof _HG !== 'undefined' && _HG.rowById) {
        var el3 = _HG.rowById[row.tid];
        var _fm = el3 && el3.querySelector(':scope > .h-tool-failmark');
        var _hd = el3 && el3.querySelector(':scope > .h-tool-head');
        if (_fm && _hd && _fm.parentNode !== _hd) _hd.appendChild(_fm);
      }
      // 账本同步：V3 账本内同 tid 行补终态（供后续整窗重放一致）
      if (typeof _HG !== 'undefined' && Array.isArray(_HG.histAll)) {
        for (var i = _HG.histAll.length - 1; i >= 0; i--) {
          var L = _HG.histAll[i];
          if (L && L.role === 'tool' && L.tid === row.tid) {
            L.result = row.output || '';
            if (row.status === 'error') L.err = true;
            break;
          }
        }
      }
      return;
    }
    if (row.kind === 'turn_header') {
      if (row.state && row.state !== 'running') {
        // 空壳守卫（用户实测 a21「已工作 0 秒」幽灵组）：组内无思考/工具/
        // 正文时摘除整组而非定稿——定稿空组=「已工作 0 秒」裸壳
        var g = (typeof _HG !== 'undefined') ? _HG.grp : null;
        var hasWork = !!(g && ((g.counts && (g.counts.think || g.counts.tool
          || g.counts.sub)) || (g.root
          && g.root.querySelector('.h-msg.asst:not(.ph), .h-tl > *'))));
        var fin = _g('grpFinalize');
        if (g && !hasWork && g.root && g.root.parentNode) {
          try { g.root.parentNode.removeChild(g.root); } catch (e) {}
          if (_HG.grp === g) _HG.grp = null;
        } else if (fin && hasWork) {
          try { fin(false, { turnEnd: true,
                             endTs: row.endedAt || Date.now() }); } catch (e) {}
        }
      }
      return;
    }
    if (row.kind === 'subagent') {
      // 档案收口（sse.js task_notification 同款）：done/err/result 落档——
      // 胶囊（_hgAgentsRunning 数运行中）与目录读档案，不收口=假运行
      if (!this.opt.sub && typeof _HG !== 'undefined' && _HG.agents
          && row.tid) {
        var a = _HG.agents[row.tid];
        if (!a && row.childTopic) {
          // a64：完成太快时 running 中间帧可能没触发建档（点不开+假运行
          // 实测根因）——终态帧就地建/补档案
          a = _HG.agents[row.tid] = {};
        }
        if (a && !a.done) {
          a.done = true; a.doneAt = Date.now();
          a.err = row.status === 'failed';
          a.result = String(row.summary || '').trim().slice(0, 400);
          // a64：钥匙终态补发——childTopic 直取 agentId（不依赖镜像重发），
          // 映射+hgSubr 回写行卡（点开窗格）
          var _aid2 = String(row.childTopic || '').replace(/^sub:/, '');
          if (_aid2 && /^[0-9a-zA-Z_-]{8,64}$/.test(_aid2)) {
            a.taskId = a.taskId || _aid2;
            _HG.tidMap = _HG.tidMap || {}; _HG.tidMap[row.tid] = _aid2;
            _HG.aidKey = _HG.aidKey || {};
            if (!_HG.aidKey[_aid2]) _HG.aidKey[_aid2] = row.tid;
            if (typeof _hgAgentRowBindAid === 'function')
              _hgAgentRowBindAid(row.tid, (_HG.rowById || {})[row.tid]);
            // a68（用户实测「子代理永远不结束」）：终态直达 v4 子 pane——
            // feed 尾段丢失/转写无 result 行时 store 永静默，pane 秒表永跑；
            // 子 pane 定稿+结论兜底（brief=真结论）
            if (root.V4Main && root.V4Main.subNotify) {
              try {
                root.V4Main.subNotify(_aid2, row.status === 'failed',
                                      String(row.summary || '').slice(0, 400));
              } catch (e) {}
            }
          }
          // a68/a76：tab 停转（v4 下 V3 的 _subClose 完成链不跑，tb.run
          // 无人清=tab 永挂运行态绿点）——就地清+重绘。tab 键是归一后
          // agentId（row.tid 是 call tid——a74 的 _agEntry 同款双键解析）
          var _subG = _g('_sub');
          var _aidTab = (typeof _HG !== 'undefined' && _HG.tidMap)
            ? _HG.tidMap[row.tid] : null;
          var _tbN = _subG && _subG.tabs
            ? (_subG.tabs[row.tid] || (_aidTab ? _subG.tabs[_aidTab] : null))
            : null;
          if (_tbN && _tbN.run) {
            _tbN.run = false;
            _tbN.err = row.status === 'failed';
            var _tp = _g('_subTabsPaint');
            if (_tp) { try { _tp(); } catch (e) {} }
          }
        }
      }
      // 行卡终态（V3 agent 单行卡：停表+徽章+摘要+agentId 回绑）
      var ars = _g('_hgAgentRowState');
      if (ars && row.tid) {
        try { ars(row.tid, row.status === 'failed', row.summary || ''); }
        catch (e) {}
      }
      var rss2 = _g('renderSideStatus');
      if (rss2) { try { rss2(); } catch (e) {} }
      // a75：终态胶囊即时熄灭（与派出时点亮对偶——主窗与子代理同步结束）
      var _cap2 = _g('_hgDynCapsulePaint');
      if (_cap2) { try { _cap2(); } catch (e) {} }
      return;
    }
    if (row.kind === 'vision') {
      // V3 签名 _hgVisionResult(卡元素, text, err)——a32 前误传 (tid,bool,
      // prompt) 三参全错位=识图终态链瘫痪（回传 md 消失根因之一）
      var _vcard = (typeof _HG !== 'undefined' && _HG.visionCalls
                    && row.tid) ? _HG.visionCalls[row.tid] : null;
      if (_vcard) {
        delete _HG.visionCalls[row.tid];
        var vr = _g('_hgVisionResult');
        if (vr) { try { vr(_vcard, row.output || row.text || '',
                           row.status === 'error'); } catch (e) {} }
      }
    }
  };

  // ---- A 区状态 → V3 原函数 -----------------------------------------------

  V4Bridge.prototype._paintState = function (patch, isSnapshot) {
    var st = (this.store && this.store.snap && this.store.snap.state) || {};
    // 子 pane 的 A 区只消费结论终稿——busy/ask/queue/model 全是主窗语义，
    // 子投影 patch 不得外溢（同 _rebuild 全局账守卫）
    if (this.opt.sub) {
      var _sd = (patch.done !== undefined) ? patch.done : st.done;
      var _sf = (patch.final !== undefined) ? patch.final : st.final;
      if (this.conclEl && !this.conclDone && _sd && _sf) {
        this.conclDone = true;
        this.conclEl.innerHTML = '';
        var _md = _g('mdBubble');
        var _dv = document.createElement('div');
        _dv.className = 'h-msg asst';
        if (_md) { try { _dv.appendChild(_md(_sf)); } catch (e) { _dv.textContent = _sf; } }
        else _dv.textContent = _sf;
        this.conclEl.appendChild(_dv);
      }
      return;
    }
    if (typeof patch.busy === 'boolean' || isSnapshot) {
      var b = typeof patch.busy === 'boolean' ? patch.busy : !!st.busy;
      if (b !== this._lastBusy) {
        this._lastBusy = b;
        var sb = _g('setBusy');
        if (sb) { try { sb(b); } catch (e) {} }
      }
    }
    if (patch.ask !== undefined) {
      var ar = _g('askRender');
      if (ar && patch.ask) { try { ar(patch.ask); } catch (e) {} }
    }
    if (patch.ask_done) {
      var ad = _g('askDone');
      if (ad) { try { ad(patch.ask_done); } catch (e) {} }
    }
    if (Array.isArray(patch.queue)) {
      // 队列条真源=_HG.queues[_hgQueueKey()]（按会话分桶，renderQueue 读它）
      // ——a19 写错字段 _HG.queue 从未生效（用户实测：promoted 后队列条不摘）
      if (typeof _HG !== 'undefined') {
        var qk = (typeof _hgQueueKey === 'function') ? _hgQueueKey()
          : (_HG.sid || '_new');
        _HG.queues[qk] = patch.queue;
      }
      var rq = _g('renderQueue');
      if (rq) { try { rq(); } catch (e) {} }
    }
    if (patch.model && typeof _HG !== 'undefined') {
      _HG.model = patch.model;
      var q = (typeof _hgQ !== 'undefined') ? _hgQ : null;
      var chip = q ? q('[data-hg-model]') : null;
      if (chip) chip.innerHTML = String(patch.model) + ' ▾';
    }
    // 压缩状态（a52 归一）：feed per-sid state 驱动 V3 压缩线原件
    // （renderCompaction 读 _HG.compactT0/compactSid——per-sid 投影天然
    // 隔离，他会话压缩不串台；compactUsed 沿用 V3 localStorage 口径）
    if (typeof patch.compacting === 'boolean' && typeof _HG !== 'undefined') {
      var _rc = _g('renderCompaction');
      if (patch.compacting) {
        _HG.compacting = true;
        _HG.compactSid = _HG.sid;
        _HG.compactT0 = patch.compactT0 || Date.now();
        try { _HG.compactUsed = (JSON.parse(
          localStorage.getItem((typeof _hgCtxKey === 'function' ? _hgCtxKey(_HG.sid) : '') || 'null')
          || 'null') || {}).used || 0; } catch (e) { _HG.compactUsed = 0; }
        if (_rc) { try { _rc(false); } catch (e) {} }
      } else if (_HG.compacting) {
        _HG.compacting = false;
        if (_rc) { try { _rc(true); } catch (e) {} }
      }
    }
    // 子 pane 结论终稿（一次成型）
    if (this.conclEl && !this.conclDone) {
      var done = (patch.done !== undefined) ? patch.done : st.done;
      var txt = (patch.final !== undefined) ? patch.final : st.final;
      if (done && txt) {
        this.conclDone = true;
        this.conclEl.innerHTML = '';
        var md = _g('mdBubble');
        var dv = document.createElement('div');
        dv.className = 'h-msg asst';
        if (md) { try { dv.appendChild(md(txt)); } catch (e) { dv.textContent = txt; } }
        else dv.textContent = txt;
        this.conclEl.appendChild(dv);
      }
    }
  };

  // ===========================================================================
  // a65 子 pane 渲染引擎（红线根治：数据=投影，渲染=V3 subpane kit）
  //
  // 背景（用户实测「子代理和主窗混了/子页一开主窗异常/子页打不开内容」的
  // 共同根因）：子 bridge 曾复用主窗渲染链（_histRender/_hgRowAdd/
  // renderToolUse）——子快照直接刷进主窗 flow 并覆盖 _HG.histAll（a62 只
  // 挡了显式赋值，_histRender 内部的 _HG.histAll=lines 与 _hgFlow 渲染没
  // 挡住），窗格本体反而永远空。本引擎：快照/delta 全部翻译成 subpane
  // kit 调用（scaffold/时间线/工具卡/结论区，与 V3 回放逐 class 同构），
  // 落点只在窗格自己的容器；空快照走 /subagent_replay 兜底（同一渲染器），
  // 再空给「未找到转写」+档案结论——打开必有内容（无条件显示）。
  // ===========================================================================

  function _toolHintOf(inp) {
    inp = inp || {};
    return inp.command || inp.file_path || inp.path || inp.pattern ||
           inp.query || inp.description || inp.subject || inp.prompt || '';
  }

  function _normWs(s) { return String(s || '').replace(/\s+/g, ''); }

  // 归一行：v4 投影行（fromV3=false）与 /subagent_replay 行（true）统一成
  // 一套渲染器输入——兜底不引入第二形态。ts=行时刻（思考段时长/轮时长
  // 的事实源；v4=row.at，V3 兜底=Date.parse(row.ts)）
  function _subNorm(row, fromV3) {
    if (!row) return null;
    if (fromV3) {
      var k = row.k;
      var ts0 = row.ts ? (Date.parse(row.ts) || 0) : 0;
      if (k === 'user') return { r: 'user', text: row.text || '', ts: ts0 };
      if (k === 'text') return { r: 'text', text: row.text || '', ts: ts0 };
      if (k === 'think') return { r: 'think', text: row.text || '', ts: ts0 };
      if (k === 'note') return { r: 'note', text: row.text || '', ts: ts0 };
      if (k === 'tool') return { r: 'tool', name: row.name || '',
                                 hint: row.hint || '', tid: row.tid || '',
                                 input: row.in || null, ts: ts0 };
      if (k === 'result') return { r: 'result', text: row.text || '',
                                   err: !!row.err };
      return null;
    }
    var kk = row.kind;
    var ts = row.at || 0;
    if (kk === 'user_input') return { r: 'user', text: row.text || '', ts: ts };
    if (kk === 'assistant_text') return { r: 'text', text: row.text || '', ts: ts };
    if (kk === 'reasoning') return { r: 'think', text: row.text || '', ts: ts };
    if (kk === 'tool_call') {
      var done = row.status && row.status !== 'running';
      return { r: 'tool', name: row.tool || '',
               hint: _toolHintOf(row.input), tid: row.tid || '',
               input: row.input || null, done: !!done,
               out: row.output || '', err: row.status === 'error', ts: ts };
    }
    return null;
  }

  V4Bridge.prototype._subTab = function () {
    var g = _g('_sub');
    if (!g || !g.tabs || !this.opt.tid) return null;
    return g.tabs[this.opt.tid] || null;
  };

  V4Bridge.prototype._subScrollBottom = function (stick) {
    var sc = (this._t && this._t.sc) || this.flow;
    if (!sc) return;
    if (stick === false) return;
    try { sc.scrollTop = sc.scrollHeight; } catch (e) {}
  };

  // 秒表（v4 pane 无 V3 tick——健康源=store 连接，1s 只画头）
  V4Bridge.prototype._subWatchStart = function () {
    var self = this;
    if (this._subTick) return;
    var hp = _g('_subTlHeadPaint');
    this._subTick = setInterval(function () {
      if (self._closed || !self._t) {
        if (self._subTick) { clearInterval(self._subTick); self._subTick = null; }
        return;
      }
      if (!self._t.done && hp) { try { hp(self._t); } catch (e) {} }
      // a77 防定格看门狗（用户实测「窗格定格在 45s，代理还在跑」）：运行中
      // 且 >15s 无新行（无论连接假死/帧丢失/渲染停滞哪种模式——ka 心跳
      // 只保连接不保数据）→ 强制携权威快照重订阅整窗重对齐。长思考静默期
      // 重复触发无害（快照同容零变化），自限 15s 一跳
      if (!self._t.done && self._lastRowAt
          && Date.now() - self._lastRowAt > 15000) {
        self._lastRowAt = Date.now();
        if (self.store && !self.store._closed) {
          self.store._forceSnapshot = true;
          self.store._scheduleReconnect();
        }
      }
      // a74 保险带：空态注记超 20s 仍零行（连接绑孤儿 feed/静默残滞）——
      // 强制携水位重订阅拿服务端权威（后端 5s 对账为主修，此处兜底）
      if (self._emptyAt && Date.now() - self._emptyAt > 20000
          && self._t.tl && !self._t.tl.children.length) {
        self._emptyAt = 0;
        if (self.store && !self.store._closed) {
          self.store._forceSnapshot = true;
          self.store._scheduleReconnect();
        }
      }
    }, 1000);
  };
  V4Bridge.prototype._subWatchStop = function () {
    if (this._subTick) { clearInterval(this._subTick); this._subTick = null; }
  };

  // 开口思考段的时长回填（V3 回放 pend 机制对位：段起点挂前一行 ts，
  // 后续更晚 ts 的行到达时按差值写「持续了 X」——同一 assistant 消息里的
  // thinking 与 tool_use 同 ts，挂自身 ts 恒 0 秒）
  V4Bridge.prototype._flushPend = function (tsTo) {
    if (!this._pend || !this._pend.length) return;
    var dt = _g('_hgTurnDurTxt');
    for (var i = 0; i < this._pend.length; i++) {
      var p = this._pend[i];
      var te = p.seg.isConnected ? p.seg.querySelector('.h-think-seg-t') : null;
      if (!te || !p.ts) continue;
      var dur = tsTo - p.ts;
      te.textContent = dur >= 3000
        ? '持续了 ' + (dt ? dt(dur) : Math.round(dur / 1000) + ' 秒')
        : '持续了一小会';
    }
    this._pend = [];
  };

  // 单行追加（含双源查重锚——快照/兜底/delta 三路喂入幂等）
  V4Bridge.prototype._subAppend = function (n) {
    var t = this._t;
    if (!t || !t.tl) return;
    this._lastRowAt = Date.now();   // a77：行到达记账（看门狗计时基）
    // 行时刻统一在此记账（思考段时长/轮时长共用）；更晚 ts 到达先回填
    // 开口思考段（V3 回放 :1156 同款）
    var ts = n.ts || 0;
    var prevTs = this._lastAt || 0;
    if (ts > 0) {
      this._flushPend(ts);
      this._lastAt = ts;
      if (!this._firstAt) {
        this._firstAt = ts;
        // a74：空态注记期的兜底 t0 重锚为首行时刻（真实轮时长）
        if (this._t0Note && t.t0) { t.t0 = ts; this._t0Note = false; }
        this._emptyAt = 0;
      }
    }
    var i, el;
    if (n.r === 'user') {
      var head = String(n.text || '').trim().slice(0, 60);
      var dupU = head && [...t.sc.querySelectorAll('.hg-sub-u')]
        .some(x => (x.textContent || '').trim().indexOf(head) === 0);
      if (dupU) return;
      // 多轮：当前轮有内容则定格开新轮（V3 回放 D6 同款）
      if (t.tl.children.length) {
        var finT = _g('_subTlFinalizeT'), tb0 = this._subTab();
        if (finT && tb0) {
          try { finT(tb0, t, { durMs: (this._lastAt && t.t0)
                               ? Math.max(0, this._lastAt - t.t0) : 0 }); } catch (e) {}
        }
        var nt = _g('_subTurnNew');
        if (nt && tb0) { t = this._t = nt(tb0, { t0: this._lastAt || 0 }); t.v4 = true; }
        if (!t || !t.tl) return;
      }
      var u = document.createElement('div');
      u.className = 'h-msg user hg-sub-u';
      var mdU = _g('mdBubble');
      if (mdU) { try { u.appendChild(mdU(String(n.text || '').slice(0, 1200))); } catch (e) { u.textContent = n.text; } }
      else u.textContent = n.text;
      u.dataset.hgRp = '1';
      var ws = t.tl.closest('.h-grp');
      if (ws && ws.parentElement) ws.parentElement.insertBefore(u, ws);
      else { var sfr = _g('_subTlSegFreeze'); if (sfr) sfr(t); t.tl.appendChild(u); }
      return;
    }
    if (n.r === 'text') {
      var want = _normWs(n.text);
      var dupT = want && [...(t.sc || t.tl).querySelectorAll('.h-msg.asst[data-raw]')]
        .some(x => { var g = _normWs(x.dataset.raw);
                     return !!g && (want.startsWith(g) || g.startsWith(want)); });
      if (dupT) return;
      var tr = _g('_subTlTextRow');
      el = tr ? tr(n.text, true) : null;
      if (!el) return;
      var anchor = el.querySelector('.hg-sub-fold-body') || el;
      anchor.dataset.hgRp = '1';
      anchor.dataset.raw = String(n.text || '');
      el.dataset.raw = String(n.text || '').slice(0, 8000);
      t._lastAsst = el;
      var ar2 = _g('_subTlAppendRow');
      if (ar2) { try { ar2(t, el); } catch (e) {} }
      return;
    }
    if (n.r === 'think') {
      var wantK = _normWs(n.text);
      var dupK = wantK && [...t.tl.querySelectorAll('.h-think-seg[data-raw]')]
        .some(x => { var g = _normWs(x.dataset.raw);
                     return !!g && (wantK.startsWith(g) || g.startsWith(wantK)); });
      if (dupK) return;
      var tk = _g('_subTlThinkRow');
      if (!tk) return;
      var seg = tk(n.text || '', '');
      seg.dataset.hgRp = '1';
      var ar3 = _g('_subTlAppendRow');
      if (ar3) { try { ar3(t, seg); } catch (e) { t.tl.appendChild(seg); } }
      else t.tl.appendChild(seg);
      t.stats.think++;
      // a70：开口段入 pend（起点=前一行 ts——同消息 thinking/tool_use 同 ts，
      // 挂自身恒 0 秒；V3 回放 :1220 同款），更晚 ts 行到达或定稿时回填时长
      if (ts > 0 || prevTs > 0) {
        this._pend.push({ seg: seg,
                          ts: (prevTs > 0 && (!ts || prevTs < ts)) ? prevTs : ts });
      }
      return;
    }
    if (n.r === 'note') {
      var d = document.createElement('div');
      d.className = 'hg-sub-replay-note';
      d.textContent = n.text || '';
      d.dataset.hgRp = '1';
      var ar4 = _g('_subTlAppendRow');
      if (ar4) { try { ar4(t, d); } catch (e) { t.tl.appendChild(d); } }
      else t.tl.appendChild(d);
      return;
    }
    if (n.r === 'tool') {
      if (n.tid) {
        try {
          if (t.tl.querySelector('.h-tool[data-tuid="' + CSS.escape(n.tid) + '"]')) return;
        } catch (e) {}
      }
      var at2 = _g('_subTlAppendTool');
      if (!at2) return;
      var stickEl = t.sc;
      var stick = stickEl ? _g('_subPaneStick') && _g('_subPaneStick')(stickEl) : true;
      try { at2(t, n.name, n.hint, n.tid, n.input); } catch (e) {}
      this._openTools.push(n);
      if (n.done) this._subToolDone(n.tid, n.out, n.err);
      else if (stick) this._subScrollBottom();
      return;
    }
    if (n.r === 'result') {   // V3 兜底行的 FIFO 配对
      var w = this._openTools.shift();
      if (w) this._subToolDone(w.tid, n.text, n.err);
    }
  };

  // 工具终态回点（tuid 精确优先；V3 兜底无 tid 行 FIFO；全 miss 静默——
  // 完整结果在工具卡折叠体，孤儿摘要不裸落时间线（V3 v3.4.65 同口径））
  V4Bridge.prototype._subToolDone = function (tid, out, err) {
    var t = this._t;
    if (!t || !t.tl) return;
    var row = null;
    if (tid) {
      try { row = t.tl.querySelector('.h-tool[data-tuid="' + CSS.escape(tid) + '"]'); }
      catch (e) {}
    }
    if (!row) {
      var all = [...t.tl.querySelectorAll('.h-tool')];
      for (var i = 0; i < all.length; i++) {
        if (all[i].dataset.done !== '1') { row = all[i]; break; }
      }
    }
    if (!row || row.dataset.done === '1') return;
    row.dataset.done = '1';
    row.classList.toggle('err', !!err);
    var slots = row.querySelector('.h-tslots');
    var sb = _g('statusBadge');
    if (slots && sb) slots.innerHTML = sb(err ? 'error' : 'completed');
    var full = String(out || '').trim();
    var coll = row.querySelector('.h-tool-coll');
    var quiet = !err && row.dataset.hgKind === 'diff' && !!row.querySelector('.h-diff');
    if (coll && full && full !== '(no content)' && !quiet) {
      var d = document.createElement('div');
      d.className = 'h-tool-out' + (err ? ' err-txt' : '');
      d.textContent = full.length > 2000 ? full.slice(0, 2000) + '…' : full;
      coll.appendChild(d);
    }
  };

  // 档案条目解析（a74）：tab 键=归一后 agentId，档案键=call tid——aidKey
  // 反查双键兜底（此前单键查空=档案兜底整链失效，_agentDone 对运行中代理
  // 误判「已结束」）
  V4Bridge.prototype._agEntry = function () {
    if (typeof _HG === 'undefined' || !_HG.agents) return null;
    return _HG.agents[this.opt.tid]
      || _HG.agents[((_HG.aidKey || {})[this.opt.tid])]
      || null;
  };

  // 结论区单次成型（a74）：真源优先级 st.final（锁定）> 终态 summary/档案
  // result（可被真源覆盖）> finalize 上移的末条正文。清场重画，绝不追加
  // 第二个气泡（此前三次收口追出 A15+元数据+真报告三段）
  V4Bridge.prototype._paintConcl = function (txt, lock) {
    var t = this._t;
    if (!t || !t.concl || !txt) return;
    if (this._conclLocked) return;
    if (lock) this._conclLocked = true;
    t.concl.innerHTML = '';
    var dv = document.createElement('div');
    dv.className = 'h-msg asst';
    dv.dataset.raw = String(txt).slice(0, 8000);
    var md = _g('mdBubble');
    if (md) { try { dv.appendChild(md(txt)); } catch (e) { dv.textContent = txt; } }
    else dv.textContent = txt;
    t.concl.appendChild(dv);
  };

  // 终态收口：done → 定稿+结论；running → 秒表起跑
  V4Bridge.prototype._subFinish = function (st) {
    var tb = this._subTab(), t = this._t;
    if (!tb || !t) return;
    st = st || {};
    var running = !st.done;
    var ag = this._agEntry();
    if (running && ag && ag.done) running = false;   // 档案终态优先（防投影滞后假跑）
    if (!running) {
      this._flushPend(this._lastAt || Date.now());   // a70：末段思考时长回填
      var fin = _g('_subTlFinalizeT');
      var durMs = (this._lastAt && t.t0 && this._lastAt > t.t0)
        ? this._lastAt - t.t0 : 0;
      // a74：定稿前留住末条正文——finalize 会把它上移结论区；有真结论
      // （st.final）时正文该留在时间线（结论区由 _paintConcl 独占），
      // 定稿后再归还（同文则维持上移=V3 形态）
      var lastEl = (t._lastAsst && t._lastAsst.isConnected) ? t._lastAsst : null;
      if (fin) { try { fin(tb, t, { durMs: durMs, err: !!st.err }); } catch (e) {} }
      else { t.done = true; }
      // 结论真源链：state.final（handback/report，锁定）→ 终态 summary
      // （a73 起为真结论正文）→ 档案 result——全空时维持 finalize 上移的正文
      var finTxt = String(st.final || '');
      if (!finTxt && ag && ag.result) finTxt = String(ag.result);
      if (finTxt && lastEl && t.concl && t.concl.contains(lastEl)
          && _normWs(lastEl.dataset.raw) !== _normWs(finTxt)) {
        try { t.tl.appendChild(lastEl); } catch (e) {}   // 正文归还时间线
      }
      if (finTxt) this._paintConcl(finTxt, !!st.final);
      this._subWatchStop();
    } else {
      t.done = false;
      t.t0 = t.t0 || this._firstAt || Date.now();
      var hp = _g('_subTlHeadPaint');
      if (hp) { try { hp(t); } catch (e) {} }
      this._subWatchStart();
    }
  };

  // a68（用户实测「子代理永远不结束」）：主窗终态直达子 pane——feed 尾段
  // 丢失（截尾时代冻结）/转写无 result 行时 store 永静默，秒表永跑。主
  // bridge 收到 subagent 终态帧时经 V4Main.subNotify 调到这里。
  // a74（实测「结论区混入首条正文+元数据」）：主窗终态常**先于**子 feed
  // 尾段增量到达——立即定稿会把当时仅有的中途正文上移结论区。改为宽限
  // 2.5s：等尾段增量（含 handback final）落地自然收口；宽限满仍无 feed
  // 终态才兜底定稿（summary 只作结论回退，真 final 一到即覆盖锁定）
  V4Bridge.prototype.subNotify = function (err, summary) {
    if (this._closed || !this._t || this._t.done) return;
    if (this._notifyTimer) return;
    var self = this;
    this._notifyTimer = setTimeout(function () {
      self._notifyTimer = null;
      if (self._closed || !self._t || self._t.done) return;
      var st = (self.store && self.store.snap
                && self.store.snap.state) || {};
      self._subFinish({ done: true, err: !!err,
                        final: st.final || String(summary || '') });
    }, 2500);
  };

  // 快照整建（子 pane 唯一整窗入口）
  V4Bridge.prototype._subRebuild = function (snap) {
    var tb = this._subTab();
    if (!tb) return;
    var sc = this.flow;
    var stick = _g('_subPaneStick') ? _g('_subPaneStick')(sc) : true;
    sc.innerHTML = '';
    tb.turns = [];
    this._openTools = [];
    this._firstAt = 0; this._lastAt = 0; this._pend = [];
    this._conclLocked = false; this._t0Note = false;
    this._emptyAt = 0; this._lastRowAt = Date.now();
    var scaffold = _g('_subPaneScaffold');
    var t = scaffold ? scaffold(tb, this.opt.type || 'Task', '', this.opt.desc || '')
                     : null;
    if (!t) return;
    t.v4 = true;
    this._t = t;
    tb.t = t;
    var rows = (snap && snap.rows) || [];
    var i, n;
    for (i = 0; i < rows.length; i++) {
      n = _subNorm(rows[i], false);
      if (n) this._subAppend(n);   // 行时刻/思考段 pend 在 append 内统一记账
    }
    if (rows.length) {
      var st = (snap && snap.state) || {};
      // 快照内工具行自带终态（upsert 语义）
      for (i = 0; i < rows.length; i++) {
        if (rows[i] && rows[i].kind === 'tool_call'
            && rows[i].status && rows[i].status !== 'running') {
          this._subToolDone(rows[i].tid, rows[i].output,
                            rows[i].status === 'error');
        }
      }
      // 首 t0=首行时刻（V3 回放 P3a 同口径）
      if (this._t && !this._t.t0) this._t.t0 = this._firstAt || 0;
      this._subFinish(st);
      tb.rpN = rows.length;   // 已铺底：shell 态的 4s ensure 循环构造性消失
      if (stick) this._subScrollBottom();
      return;
    }
    // 空快照：三级兜底（无条件显示）
    tb.rpN = 1;               // 即便兜底也视为已铺底（防 ensure 循环）
    this._subFallback(snap);
  };

  // 兜底：投影零行 → /subagent_replay（V3 已验证数据源，同一渲染器）→
  // 「未找到转写」+档案结论。运行中代理转写晚到由 watcher 按需 hydrate
  // 喂数（后端 a65），delta 到达自然续流。
  V4Bridge.prototype._subFallback = function (snap) {
    var self = this;
    var st = (snap && snap.state) || {};
    var agent = String(this.opt.agent || '');
    if (st.final) {   // 投影只有结论（行流缺）：结论照显，不空窗
      this._subFinish({ done: true, final: st.final });
      this._subEmptyNote(true, '行流不可用，已出示结论');
      return;
    }
    if (this._fbTried) { this._subEmptyNote(false, ''); return; }
    this._fbTried = true;
    var sid = this.store.sid;
    fetch('/api/harness/subagent_replay?sid=' + encodeURIComponent(sid) +
          '&agent=' + encodeURIComponent(agent))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (self._closed) return;
        var tb = self._subTab();
        if (!tb) return;
        if (j && j.ok && j.found && (j.rows || []).length) {
          var rows = j.rows;
          for (var i = 0; i < rows.length; i++) {
            var n = _subNorm(rows[i], true);
            if (n) self._subAppend(n);   // ts 记账在 append 内统一
          }
          if (self._t && !self._t.t0) self._t.t0 = self._firstAt || 0;
          tb.rpN = rows.length;
          self._subFinish({ done: self._agentDone() });
          self._subScrollBottom();
          // feed 后续有数据时以服务端快照整体接管（防兜底行与 delta 双源重复）
          if (self.store && !self.store._closed) {
            self.store._forceSnapshot = true;
            self.store._scheduleReconnect();
          }
          return;
        }
        self._subEmptyNote(!!(j && j.found), '');
      })
      .catch(function () { if (!self._closed) self._subEmptyNote(false, ''); });
  };

  V4Bridge.prototype._agentDone = function () {
    var ag = this._agEntry();
    return ag ? !!ag.done : true;   // 档案 miss 保守视为已结束（回放语义）
  };

  // 空态注记：运行中→「转写尚未生成——实况跟随中」；已结束→未找到 + 档案结论
  V4Bridge.prototype._subEmptyNote = function (found, prefix) {
    var t = this._t, tb = this._subTab();
    if (!t || !tb) return;
    var ag = this._agEntry();
    var running = ag ? !ag.done : false;
    var note = document.createElement('div');
    note.className = 'hg-sub-replay-note';
    if (running) {
      note.textContent = (prefix ? prefix + '——' : '') + '转写尚未生成——实况跟随中';
      t.tl.appendChild(note);
      // a74：t0 只作秒表兜底并打假标——首行到达时重锚首行时刻（此前不重锚
      // =「已工作」按开窗时刻算，实测 85 秒的轮显示 14 秒）
      t.t0 = (ag && ag.t0) || Date.now();
      this._t0Note = true;
      this._emptyAt = Date.now();
      this._subWatchStart();
    } else {
      note.textContent = (prefix ? prefix + '——' : '') +
        (found ? '转写存在但无可回放内容' : '未找到该子代理的转写记录');
      t.tl.appendChild(note);
      if (ag && ag.result) this._paintConcl(String(ag.result), false);
      this._subFinish({ done: true });
    }
  };

  // delta 增量（子 pane 实时刷新红线：SSE 直推，无轮询）
  V4Bridge.prototype._subApplyOne = function (d) {
    var t = this._t;
    if (!t) return;
    var stickEl = t.sc;
    var stick = stickEl && _g('_subPaneStick') ? _g('_subPaneStick')(stickEl) : true;
    if (d.op === 'row.appended') {
      var n = _subNorm(d.row, false);
      if (n) this._subAppend(n);   // ts 记账在 append 内统一
    } else if (d.op === 'row.upserted') {
      if (d.row && d.row.kind === 'tool_call') {
        this._subToolDone(d.row.tid, d.row.output, d.row.status === 'error');
      }
    } else if (d.op === 'state.updated') {
      var p = d.patch || {};
      if (p.done !== undefined || p.final !== undefined) {
        var st = (this.store && this.store.snap
                  && this.store.snap.state) || {};
        this._subFinish(st);
      }
    }
    if (stick) this._subScrollBottom();
  };

  root.V4Bridge = V4Bridge;
})(window);
