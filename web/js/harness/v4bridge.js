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
// 模块化一期：已转 ES module——IIFE 壳换成 const root = window。
const root = window;
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
    this._conclSel = this.opt.conclEl
      ? ((this.opt.conclEl.id && '#' + this.opt.conclEl.id)
         || (this.opt.conclEl.className
             && '.' + String(this.opt.conclEl.className).trim().split(/\s+/)[0]))
      : null;
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
    // a116（用户实锤「超长会话滚动时来新消息卡一下」）：滚动保持期渲染缓冲
    // ——新行渲染（markdown 解析+建 DOM+布局）实测 80-290ms/条，直接插进
    // 滚动帧=可感知顿挫。用户正在滚动且不在底部时，行级增量先排队，滚动
    // 停 200ms（或队列超龄 1.2s 兜底）统一补——贴底跟随不受影响（在底部
    // 立即渲染）；A 区 state（busy/胶囊）不缓冲照常即时
    this._pumpQ = [];
    this._pumpT = 0;
    this._pumpQAt = 0;
    this._lastScrollAt = 0;
    this._scrollNearBottom = true;   // 滚动帧内算好缓存（增量闸只读缓存零布局）
    if (flowEl && flowEl.addEventListener) {
      try {
        flowEl.addEventListener('scroll', function () {
          self._lastScrollAt = Date.now();
          try {
            self._scrollNearBottom = flowEl.scrollHeight - flowEl.scrollTop
              - flowEl.clientHeight < 140;
          } catch (e) {}
        }, { passive: true });
      } catch (e) {}
    }
    this.unsub = store.subscribe(function (ev) { self._onEv(ev); });
  }

  // 一般12 修正（a116 全审）：conclEl 在 `_subRebuild`（含 sc.innerHTML=''）
  // 之后会变成游离节点——写进去用户看不见，注释里「两条通路同口径」不成立。
  // 写入前按选择器重取，取不到再回落构造时的节点。
  // MINOR-1（a116 二次全审）：查询必须**限于当前轮**（this._t.el），否则多轮
  // 子 pane 会命中第一轮的旧结论区（新结论写进看不见的旧节点）。
  V4Bridge.prototype._conclNode = function () {
    if (!this.conclEl) return null;
    if (this._conclSel) {
      var _scopes = [];
      if (this._t && this._t.el) _scopes.push(this._t.el);
      if (this.flow) _scopes.push(this.flow);
      for (var _i = 0; _i < _scopes.length; _i++) {
        try {
          var el = _scopes[_i].querySelector(this._conclSel);
          if (el) { this.conclEl = el; return el; }
        } catch (e) {}
      }
    }
    return (this.conclEl.isConnected === false) ? null : this.conclEl;
  };

  V4Bridge.prototype.close = function () {
    // 全审 P1（a116）：必须置位——下游 5 处（_subApplyOne/_subFinish/
    // 重连回调等）全部以 _closed 早退，不置位等于守卫全是死条件：切会话
    // 时在飞的 /subagent_replay 回调仍会写新会话的档案与行卡。
    this._closed = true;
    if (this.unsub) { this.unsub(); this.unsub = null; }
    if (this._notifyTimer) { clearTimeout(this._notifyTimer); this._notifyTimer = null; }
    // a116：滚动缓冲队列随关清空（定时器在 _pumpArm 内自清）
    this._pumpQ = []; this._pumpQAt = 0;
    if (this._pumpT) { clearTimeout(this._pumpT); this._pumpT = 0; }
    this._subWatchStop();
  };

  // 内网缺陷报告修复（回合导航导轨切终端后失效）：v4 是唯一渲染管线但
  // 全程不调 _hgRailSync——DOM 重建后 railItems 里的元素引用全部失联
  // （isConnected=false），点击静默 return=「刻度还在点了没反应」。本函数
  // 是 v4 渲染完成后的导轨同步入口：快照整建同步调、delta 收尾 debounce
  // （流式 delta 高频，全量扫 user 气泡 + 重建刻度 DOM 一次足够）
  var _railSoonT = 0;
  function _railAfterRender() {
    if (_railSoonT) return;
    _railSoonT = setTimeout(function () {
      _railSoonT = 0;
      var f = _g('_hgRailSync');
      if (f) { try { f(); } catch (e) {} }
    }, 250);
  }

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
    if (kind === 'snapshot') {
      this._rebuild(ev.snap);
      // 首个快照到达即对齐一次（幂等：Sync 内部整建 agents，重复调用只重算）。
      // a124 复审：标志位必须**成功后才置**——原写法先 `=true` 再发请求，
      // 一次网络失败就本会话永久失准。这里改成计数式重试（最多 3 次快照），
      // 且每次都调（Sync 自身有 seq 竞态保护，重复无害）。
      if ((this._regSyncN || 0) < 3 && typeof _hgRegSync === 'function') {
        this._regSyncN = (this._regSyncN || 0) + 1;
        Promise.resolve()
          .then(function () { return _hgRegSync(_HG.sid); })
          .catch(function () {});
      }
    }
    else if (kind === 'deltas') {
      var ds2 = ev.deltas || [];
      for (var j = 0; j < ds2.length; j++) this._applyOne(ds2[j]);
      _railAfterRender();   // 内网报告修复：delta 渲染收尾同步导轨（debounce）
    }
  };

  // ---- snapshot：V3 整窗原件一次调用（窗口/懒填/归档/定稿/导轨全套） -------

  V4Bridge.prototype._rebuild = function (snap) {
    var rows = (snap && snap.rows) || [];
    // a116：整窗权威快照到达——滚动缓冲队列里的增量全部作废（快照已含）
    if (this._pumpQ.length) { this._pumpQ = []; this._pumpQAt = 0; }
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
    // G4 修复（a116）：拒建判据依赖 _HG.histAll，而切会话时它已被清成
    // null（sessions.js）→ 守卫失效，接着 _histRender([]) 在 histcache.js
    // 早退**不清 DOM**（v3.5.196 撤了预清）→ 用户停在上个会话的内容上、
    // 头部却是新会话，且只有 console.warn 无任何提示。零行且非 sub 时
    // 显式清空 flow 并给出可见提示。
    if (!rows.length && !this.opt.sub) {
      try {
        var _flowEl = (typeof _HG !== 'undefined' && _HG && _HG.flowEl)
          || document.querySelector('[data-hg-flow]');
        if (_flowEl && _flowEl.replaceChildren) _flowEl.replaceChildren();
        if (typeof _HG !== 'undefined' && _HG) { _HG.histAll = []; _HG.histCursor = 0; }
        var _note = document.createElement('div');
        _note.className = 'h-sysnote h-v4empty';
        this._g4Gone = false;   // 二轮 P2-1：置旗后 appended 路免重复扫描
        _note.textContent = '该会话暂无可显示内容（投影为空，正在同步…）';
        if (_flowEl) _flowEl.appendChild(_note);
      } catch (e) {}
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
      if (!L) continue;
      // a85/a85b（用户实锤「思考怎么能这么连续的，一行条太难看」「刷新还这样」）：
      // 相邻 thinking 行账本归并——快照里思考行之间隔着**查阅类工具行**
      // （Read/Grep/只读 Bash，渲染时被吸收进「🔍 查阅」组不显行），视觉上
      // 思考连排。合并条件放宽为「仅隔查阅类工具」：跨过尾部连续查阅行找
      // 思考，命中即把旧思考行摘除、合成行放在当前位置（查阅组之后）——
      // 顺序（查阅组→思考→下个真工具）与时长（到下个非查阅行的 ts 差）
      // 都自然正确
      if (L.role === 'thinking' && lines.length) {
        var _exp = _g('_hgIsExplore');
        var _j = lines.length - 1;
        while (_j >= 0 && lines[_j].role === 'tool'
               && _exp && _exp(lines[_j].text, lines[_j].input)) _j--;
        if (_j >= 0 && lines[_j].role === 'thinking') {
          // 原位并入（保留首段行位置）：抽屉渲染在段头，时长锚=段前真实行，
          // 结算点=段后首个非查阅行（hist.js 已让查阅行不结算）——整段覆盖
          var _pa = lines[_j];
          _pa.text = (_pa.text || '') + '\n\n' + (L.text || '');
          continue;
        }
      }
      lines.push(L);
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
      // 内存批（对抗审 C-P0）：v4 模式 saveCache 不再写快照缓存（webview
      // 内存批），sessions.js 的 dirty 判据失去 cache 项——「首条消息已发、
      // jsonl 尚未 flush」的窄窗内 has_history 仍 false，chip 点击会走
      // 误删分支。快照有行=会话有内容是数据到达时刻的铁证，就地补置
      if (lines.length) _HG.dirty = true;
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
    // a82 前端对位防御：state.busy 丢失（存量快照/竞态）时，尾组头 running
    // 同样是「在飞回合」铁证——noFinalize/phResume 判据取并集。宁可多留
    // 活组（下帧权威帧覆盖）不可误定稿折叠（用户实测：后台代理还在跑，
    // 19 张工具卡被藏进「已工作 22 分 13 秒」定稿折叠组）
    if (!busy) {
      for (var bi = rows.length - 1; bi >= 0; bi--) {
        if (rows[bi] && rows[bi].kind === 'turn_header') {
          busy = rows[bi].state === 'running';
          break;
        }
      }
    }
    var render = _g('_histRender');
    if (render) {
      // busy 会话切回：noFinalize 留活组（对齐 V3 sessions.js:534）——写死
      // false 会把进行中的尾组定稿，后续 live delta 落入幽灵新组（用户实测
      // 「A切B切A 工作组错乱」）
      try { render(lines, start, { noFinalize: busy }); } catch (e) {
        (root.console && console.error) && console.error('[v4bridge] rebuild', e);
      }
    }
    // running 态子代理行补建档案（等价 V3 liveAgentsBy 桶恢复）：busy 会话
    // 切回后胶囊/目录才有「子代理执行中」。完成态不建——回放行卡由
    // renderHistTool 定格，目录走 registry 冷查询（与 V3 整窗路同口径）
    // a112S/a113R（用户实锤「刷新后运行中代理不同步」+「刷新后组裂成两
    // 段」）：循环必须在渲染**之后**（此前在渲染前——rowById 空、卡不存
    // 在，rowById[aid]/hgSubr/摘标/秒表全落空）；a113 首版把渲染调用一并
    // 前挪致 start/busy（var 提升=undefined）在调用点未赋值——noFinalize
    // falsy 误定稿+phResume 建新组=「已工作+空工作中」两段（用户实锤）。
    // 本版：先算 start/busy → 渲染 → 档案循环，顺序一次到位
    for (var jr = 0; jr < rows.length; jr++) {
      if (rows[jr] && rows[jr].kind === 'subagent'
          && rows[jr].status === 'running') this._agentFile(rows[jr]);
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
    // 内网报告修复（P0）：快照整建后同步导轨。对抗审实测修正——报告称
    // 「v4 全程不调 _hgRailSync」不确（_histRender 尾部本有调用）；但在
    // 旧实例复现判据实测：railItems 11/11 全失联且与切终端无关（基线即
    // 失联）,真实根因=某未定位的漏同步路径（DOM 被换而 sync 未跟）。
    // 本调用 + delta 收尾 debounce + main.js 点击兜底重同步（P1）三层
    // 防线覆盖该未知路径：漏了这里,点击时也会被重同步救活
    var _rs = _g('_hgRailSync');
    if (_rs) { try { _rs(); } catch (e) {} }
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
          // a88b：键桥随冷同步补齐——tidMap/aidKey 此前只在 live 链
          // （_agentFile/终态帧）写，刷新后没有任何 live 事件前 _hgAg 的
          // aidKey 反查恒失败 → _subLivePaint 档案解析 null → 过程文本
          // 自愈链整条断（切会话回来不同步的最后一环）
          _HG.tidMap = _HG.tidMap || {}; _HG.tidMap[tid] = aid;
          _HG.aidKey = _HG.aidKey || {};
          if (!_HG.aidKey[aid]) _HG.aidKey[aid] = tid;
          a.taskId = aid;
          a.type = a.type || ent.type || 'Task';
          if (ent.desc) a.desc = a.desc || ent.desc;
          var _running = ent.status === 'running';
          // a91/a112（用户铁律「后台还在运行无条件同步」+「出错代理刷新不能
          // 复活」）：readmodel 的 running/interrupted 都是 mtime 启发式（转写
          // 新鲜=在跑/停更=中断）——启发式**只能落定、不能翻案**：
          // ①档案 running + readmodel done/err（通知/结果事实）→ 落定终态
          // ②档案 running + interrupted（启发式）→ 保持 running（a91：长思考
          //   不落盘误伤）
          // ③档案 done/err（feed 终态帧/子 feed 传播的事件真相）+ readmodel
          //   running（刚死代理转写 mtime 还新鲜，上下文爆类死亡分钟级误判）
          //   → **保持终态不复活**（曾 a.done=!running 直接翻掉=用户实锤
          //   「出错的子代理刷新后复活成运行中」）
          if (!a.done) {
            // P1-5（a116）轮次栅栏：readmodel 的 done/err 必须先越过「本轮
            // 续派发出的时刻」才可信——否则拿到的是上一轮的终态，会把刚
            // 复活的链误落定。判据：ent 的 doneAt（或 lastActive）晚于
            // sendAt 才采纳；无 sendAt（首轮）不受限。
            var _sat = Number(a.sendAt) || 0;
            var _eAt = Number(ent.doneAt || ent.lastActive || 0) || 0;
            _eAt = _eAt > 1e12 ? _eAt : _eAt * 1000;
            var _staleRound = _sat && _eAt && _eAt < _sat;
            if (!_staleRound
                && (ent.status === 'done' || ent.status === 'err'
                    || ent.status === 'stopped')) {
              a.done = true;
              a.err = ent.status === 'err';
              // v4.0.4（复审实锤）：stopped 是**确定性事实**（用户主动停），
              // 与 interrupted（mtime 启发式猜测）不同——必须落定，否则
              // 刷新/切会话后又回退成「运行中」。
              a.stopped = ent.status === 'stopped';
              a.interrupted = false;
            }
            // interrupted/running：不落定（事件真相保持 running）
            //
            // a124：例外——超过 30min 失联按落定处理。判据与注册表 Sync
            // **共用** `_regInterruptedStale`（registry.js）：两条链拉同一
            // 接口，判据不一致就会「谁后到谁赢」——Sync 若无闸会把 5 分钟
            // 长思考直接落 done（a91「后台在跑无条件同步」被破）。
            // 另加 sendAt 栅栏：续派后后端还报 interrupted（新轮刚起、
            // 投影没追上），此时链是真在跑，不得落定（实测 resumed_1m
            // 被误杀）。
            var _iStaleFn = _g('_regInterruptedStale');
            // a397：interrupted 采纳落定必须带 deadEvi（确定性死证：进程死/
            // 前代残影/回合越界/CLI 自报）。本代进程活的静默代理（守望/长
            // 静默工具型）后端已不判死；此处 !false 兜底：老链路无字段时
            // 维持 a124 原行为（30min 失联闸）
            if (!a.done && _iStaleFn && _iStaleFn(ent)
                && ent.deadEvi !== false) {
              var _sat24 = Number(a.sendAt) || 0;
              var _iAt = Number(ent.lastActive || ent.t0 || ent.doneAt) || 0;
              if (_iAt > 0 && _iAt < 1e12) _iAt = _iAt * 1000;
              if (!(_sat24 && _iAt && _iAt < _sat24)) {
                a.done = true;
                a.doneAt = _iAt || Date.now();
                a.interrupted = true;
                a.stopped = false;
                a.deadEvi = true;   // a397：死证随档（窗格定稿诊断可辨）
              }
            }
          } else if (!a.err && ent.status === 'err') {
            // a112R：err 只升不降——已 done(无 err) 的档案，readmodel 的 err
            // （notification「failed」事实）**采纳升级**并重画行卡（旧后端
            // 送达回执把行定成 success=脏 done，刷新锁死「完成」实锤；反向
            // err→done 的降级仍禁止——事件终态不可弱化）
            a.err = true;
            var _rowE = (_HG.rowById || {})[tid];
            if (_rowE && typeof _hgAgentRowState === 'function') {
              try { _hgAgentRowState(tid, true, ent.brief || ''); } catch (e) {}
            }
          }
          // 已 done+err：readmodel 无权翻回（连降级也不行——feed 事件已定）
          // a65：结论摘要随档（readmodel brief）——子 pane 结论区回退源与
          // 目录行卡摘要在冷同步会话（重启/切回）同源补齐
          if (!a.result && ent.brief) a.result = String(ent.brief).slice(0, 400);
          var _t0 = Number(ent.t0) || 0;
          a.t0 = a.t0 || (_t0 > 1e12 ? _t0 : _t0 * 1000) || Date.now();
          // a112：doneAt 只补不清——事件终态的 doneAt 不被 readmodel 空值覆写
          var _dAt = (Number(ent.doneAt) || 0);
          _dAt = _dAt > 1e12 ? _dAt : _dAt * 1000;
          if (a.done) a.doneAt = a.doneAt || _dAt;
          else a.doneAt = 0;
          // 行卡回写：hgSubr（点开钥匙）+未终态行翻徽章
          var row = (_HG.rowById || {})[tid];
          if (row) {
            if (typeof _hgAgentRowBindAid === 'function')
              _hgAgentRowBindAid(tid, row);
            if (a.done && row.dataset.final !== '1'
                && typeof _hgAgentRowState === 'function')
              _hgAgentRowState(tid, a.err, ent.brief || '', !!a.stopped);
            // a91（用户铁律「子代理后台还在运行，无条件要能够同步」）：注册表
            // （readmodel）是运行态参考，但 interrupted 是 mtime 启发式（代理
            // 长思考不落盘必误伤）——档案真相=事件（feed subagent 行 running
            // 已置 done=false）+ 上方 keep 逻辑的合成结果。档案 running 的
            // 链：行上陈旧终态让位（摘标+运行槽重画），刷新/切回即恢复同步；
            // 真 done/err（事件终态）不受影响
            if (!a.done) {
              if (row.dataset.final === '1') delete row.dataset.final;
              var _cTr = _g('_hgAgentRowTimerRestart');
              if (_cTr) { try { _cTr(row, a.t0); } catch (e) {} }
            }
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
    // G2 修复（a116）：只能落定，不能翻案——原实现无条件 a.done=false，
    // 主 feed 的 SUB 行仍 running（notification 镜像丢失）而子 feed/readmodel
    // 已把档案落 done 时，任何重连快照/upserted 都会把「完成」翻回「运行中」
    // （胶囊/目录闪回 + doneAt 清零）。修法就是**不再写这两个字段**——
    // 原有终态（a.done/a.doneAt）原样保留，无终态证据时天然是 undefined/falsy
    // =「运行中」。一般11（a116 全审）：原先这里的
    // `if (!a.done && !a.doneAt) { a.done = false; a.doneAt = 0; }`
    // 是空操作（前置条件已保证赋值后值不变），删掉以免被误读为真守卫。
    if (aid && /^[0-9a-zA-Z_-]{8,64}$/.test(aid)) {
      a.taskId = aid;
      // sse.js 冷查询批1 同款映射：_hgAg/_subTid 单点解析读它
      _HG.tidMap = _HG.tidMap || {}; _HG.tidMap[tid] = aid;
      _HG.aidKey = _HG.aidKey || {};
      if (!_HG.aidKey[aid]) _HG.aidKey[aid] = tid;
      // agentId 即刻回写行卡（审计F1：切会话后行自带 hgSubr 是回放唯一锚）
      if (typeof _hgAgentRowBindAid === 'function')
        _hgAgentRowBindAid(tid, (_HG.rowById || {})[tid]);
      // a79：行卡 agentId 键补写——registry.js:118/sse.js:158（V3 的两处
      // 写键点）在 v4 下都不跑，rowById 只有 call tid 键；_subLivePaint 按
      // rowById[agentId] 寻卡，缺键=主窗卡实时摘要永不更新（定格在初始
      // 描述，子窗格却正常）。_agentFile 随镜像 2s 重发反复执行=乱序自愈
      var _rowA = (_HG.rowById || {})[tid];
      if (_rowA && _rowA.classList.contains('agentline')) {
        _HG.rowById[aid] = _rowA;
        if (!_rowA.dataset.hgSubr) _rowA.dataset.hgSubr = aid;
        // a91：事件真相就地摘陈旧终态——feed SUB 行 running=代理未完，
        // 工具卡上的终态（旧 feed 把后台派出回执当结果 / 回放 done 形态）
        // 让位。不依赖冷同步（其首次 fetch 有 readmodel 空表竞速窗）
        if (_rowA.dataset.final === '1') delete _rowA.dataset.final;
        // a92：实时摘要 memo 回放——整窗重建（重连快照等）抹掉 ephemeral
        // live 文本时在此恢复（aid 键跨重建稳定），槽位下个 tick 回「同步中」
        var _memo = _HG.agLiveMemo;
        var _lvR = _memo && _memo[aid]
          ? _rowA.querySelector('.h-ag-live') : null;
        if (_lvR && !String(_lvR.textContent || '').trim())
          _lvR.textContent = _memo[aid];
        var _tr = _g('_hgAgentRowTimerRestart');
        // a88：只传档案 t0（上方已 memo），fresh now 兜底撤——重启链
        // 每次事件携 now 重置秒表的根因；无 t0 时由 restart 侧行上 memo
        if (_tr) { try { _tr(_rowA, a.t0); } catch (e) {} }
      }
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
        // a85b：raw 收段内**全部**思考行（段跨多行：查阅类工具不收段后，
        // 一次思考段=账本尾部连续多条 thinking 行，只取末条丢前文）
        var _parts = [];
        for (var ti = _HG.histAll.length - 1; ti >= 0; ti--) {
          var _tl = _HG.histAll[ti];
          if (_tl && _tl.role === 'thinking') {
            _parts.unshift(String(_tl.text || ''));
          } else if (_parts.length) {
            break;   // 已收集到段内容、遇非思考行=段头，收工
          }
        }
        if (_parts.length) _sg.dataset.raw = _parts.join('\n\n');
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

  // a116：滚动保持期渲染缓冲的冲刷定时器（构造器注释）——滚动停 200ms 或
  // 队列超龄 1.2s 统一按序补；快照整窗重建时队列作废（_rebuild 清）
  V4Bridge.prototype._pumpArm = function () {
    if (this._pumpT) return;
    var self = this;
    this._pumpT = setTimeout(function () {
      self._pumpT = 0;
      if (self._closed || !self._pumpQ.length) { self._pumpQ = []; self._pumpQAt = 0; return; }
      var idle = Date.now() - self._lastScrollAt >= 200;
      var aged = self._pumpQAt && Date.now() - self._pumpQAt >= 1200;
      if (!idle && !aged) { self._pumpArm(); return; }
      var q = self._pumpQ; self._pumpQ = []; self._pumpQAt = 0;
      for (var i = 0; i < q.length; i++) {
        try { self._applyOne(q[i], true); } catch (e) {}
      }
    }, 200);
  };

  V4Bridge.prototype._applyOne = function (d, _bypass) {
    var op = d.op;
    // a116：滚动保持期闸——用户正在滚动且不在底部：行级增量排队缓渲染
    //（贴底跟随与 state 即时不受影响；_bypass=冲流回放直通）
    if (!_bypass && (op === 'row.appended' || op === 'row.upserted')
        && this._lastScrollAt && Date.now() - this._lastScrollAt < 200
        && !this._scrollNearBottom) {
      if (!this._pumpQ.length) this._pumpQAt = Date.now();
      this._pumpQ.push(d);
      this._pumpArm();
      return;
    }
    if (op === 'row.appended') {
      // 对抗审 P2-1（a142）：G4 空投影注记在有真实内容到达即摘除——
      // 原先只有 hideWelcome 兜 .hg-welcome，注记会挂到下次整窗重建
      if (this._g4Gone !== true) {   // 一次性摘除，此后 O(1) 直通
        var _g4 = this.flow.querySelector(':scope > .h-v4empty');
        if (_g4) { try { _g4.remove(); } catch (e) {} }
        this._g4Gone = true;
      }
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
        // 对抗审 P1-2（a141）：interrupted marker 到达即通知 stopGen「事件到了」
        // ——旧 sse.js:1227 的派发点随批G 迁移至此，缺失则每次 ■ 停止 2.3s 后
        // 必弹假「中断事件超时」banner（chatctl stopGen 的 gotEvent 恒 false）
        if (row.mkind === 'interrupted') {
          try { document.dispatchEvent(
            new CustomEvent('hg-interrupted', {detail: _HG.sid})); } catch (e) {}
        }
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
        // a85b：查阅类工具不收思考段——它们被吸收进「🔍 查阅」组不渲染可
        // 见行，收段会把「思考→查阅→思考」切成一排裸条（对齐重建路合并语义）
        var _expK = _g('_hgIsExplore');
        if (!(_expK && _expK(row.tool || '', row.input || {})))
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
        // a84（用户实锤「sendmessage 后变成 6 个子代理」）：SendMessage 续派
        // 先行记账（V3 sse.js:450-478 同构）——①包装 tid→真实 agentId 写映射
        //（_subTid 归一回原子代理 tab/档案）；②一链一档：并入原档（rounds++
        // 复活/desc=消息首行/tids+=包装 tid），无原档才建独立 collab 档——
        // 目录从此一链一行，续派不再 ×2；③消息入窗格来向队列（运行中即刻
        // 可见）。然后再走通用建卡（SendMessage 配置=agentline 同款）
        if (row.tool === 'SendMessage' && row.input && row.input.to
            && typeof _HG !== 'undefined') {
          var _to = String(row.input.to);
          if (/^[0-9a-zA-Z_-]{4,128}$/.test(_to)) {
            _HG.tidMap = _HG.tidMap || {};
            _HG.tidMap[row.tid || ''] = _to;
            _HG.aidKey = _HG.aidKey || {};
            if (!_HG.aidKey[_to]) _HG.aidKey[_to] = row.tid || '';
            // a92S：归并查找走 _hgAg 单点解析（aidKey/tidMap 桥——冷同步
            // 起即建）+taskId 直查。曾直查 agents[_to]（agentId 键），重启后
            // 冷同步档案键是 call tid → 必 miss → 每个续派新建一份档案=
            // 胶囊「✦8」（4 代理 × 派发/续派两键）的重复档案根源
            var _hgAgr = _g('_hgAg');
            var _orig = _hgAgr ? _hgAgr(_to) : ((_HG.agents || {})[_to] || null);
            if (!_orig) {
              for (var _k in (_HG.agents || {})) {
                var _a0 = _HG.agents[_k];
                if (_a0 && (_a0.agentId === _to || _a0.taskId === _to
                    || (_a0.tids || []).indexOf(row.tid || '') >= 0)) {
                  _orig = _a0; break;
                }
              }
            }
            var _m1 = String(row.input.message || '').trim().split('\n')[0]
              .replace(/\s+/g, ' ').slice(0, 60);
            if (_orig) {
              _orig.rounds = (_orig.rounds || 1) + 1;
              _orig.done = false; _orig.doneAt = 0; _orig.err = false;
              _orig.interrupted = false; _orig.lost = false;
              _orig.deadEvi = false;   // a397：复活清死证
              // P1-5 修复（a116）：续派开新轮的本地时间戳。冷同步规则①
              // （running + readmodel done/err → 落定）在 readmodel 增量刷新
              // 追上本次 send 之前拿到的是**上一轮**的 done/err，会把刚复活
              // 的链直接落定（用户可见：续派后切走再切回，链在跑却显示完成）。
              // 落定前用它做轮次栅栏。
              _orig.sendAt = Date.now();
              // a93S（用户定调「就应该是原封不动的子代理名」）：续派**不改
              // 名**——原档 desc（真实任务名）保留，消息首行只在原档无名时
              // 兜底（曾覆写为消息首行=超长名顶爆胶囊+目录全变消息名）
              if (!_orig.desc && _m1) _orig.desc = _m1;
              _orig.tids = _orig.tids || [];
              if ((_orig.tids || []).indexOf(row.tid || '') < 0)
                _orig.tids.push(row.tid || '');
            } else {
              _HG.agents = _HG.agents || {};
              _HG.agents[row.tid || ''] = {
                type: 'SendMessage', desc: _m1, t0: Date.now(),
                done: false, doneAt: 0, collab: true, bg: true, taskId: _to };
            }
            var _sq = _g('_subUserQueue');
            if (_sq) { try { _sq(_to, String(row.input.message || '')); } catch (e) {} }
          }
        }
        var rT = _g('renderToolUse');
        if (rT) { try { rT({ id: row.tid || '', name: row.tool || '',
                             input: row.input || {} }, false); } catch (e) {} }
        // a84：SendMessage 行=agentline 卡——tidMap 已写，即刻回绑行卡
        // hgSubr（可点开原子代理窗格；不必等终态）
        if (row.tool === 'SendMessage' && typeof _HG !== 'undefined'
            && _HG.rowById && typeof _hgAgentRowBindAid === 'function') {
          var _sEl = _HG.rowById[row.tid || ''];
          if (_sEl) { try { _hgAgentRowBindAid(row.tid, _sEl); } catch (e) {} }
        }
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
      // 思考段收口对齐 V3 sse（:335）：正文行到达前收段；a85b：查阅类工具
      // 行同样不收（吸收进查阅组不显行，收段=连续思考被切碎）
      if (L.role !== 'thinking') {
        var _expG = _g('_hgIsExplore');
        if (L.role !== 'tool'
            || !(_expG && _expG(L.text, L.input)))
          this._closeThink();
      }
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
      // P2 修复（a116）：必须按 path 分流。原实现不看 path/rowId 一律
      // appendThinking——契约允许 text/inputText/summary 三路，服务端一旦
      // 启用流式（CLI 开 partial）会把工具流/正文流画进思考抽屉。
      // 当前 src 内无 d_row_delta 发点，故为潜在缺陷的提前封堵。
      if (d.path === 'text') {
        var aT = _g('appendThinking');
        if (aT && d.append) { try { aT(d.append); } catch (e) {} }
      } else {
        // inputText/summary：按 rowId 就地更新账本并重绘该行
        var _r = null;
        try {
          var _rows = (this.store && this.store.snap && this.store.snap.rows) || [];
          for (var _ri = 0; _ri < _rows.length; _ri++) {
            if (_rows[_ri].rowId === d.rowId) { _r = _rows[_ri]; break; }
          }
        } catch (e) {}
        if (_r && d.append) {
          // 一般10 修正（a116 全审）：store 已由 V4P.applyDeltas 应用过一次，
          // 这里再拼会双写（node 复现 'ls -la' → 'ls -la-la'）。只重绘不累加。
          // 当前无 d_row_delta 发点（属埋雷），保留重绘语义即可。
        }
      }
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
      // a90：投影侧已根修（v4feed 后台回执不再终结 Agent 行）——前端消费
      // 终态帧即真终态，无需再对回执做甄别（DOM 永远是投影的纯函数）
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
          sl2.innerHTML = (sb2 ? sb2(row.status === 'error' ? 'error'
                                     : (row.status === 'cancelled' ? 'stopped'
                                        : 'completed')) : '')
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
      if (row.state === 'running'
          && !(typeof _HG !== 'undefined' && _HG && _HG.grp)) {
        // a147：reopened=后端并回背书（machine_turn 机器续接的 un-finalize，
        // 重开刚定稿的组=v3.3.2 reopen 语义，秒表按累计链续走）。有身份记忆
        // （_lastFinRoot）则校验 DOM 末组防误开他人组；无记忆（间隙重建/
        // 切回后的新 bridge——深攻 P1 曾因此拆分）信任后端直接重开
        var _fr = this._lastFinRoot || null;
        var _dl = null;
        try {
          var _gs2 = this.flow.querySelectorAll(':scope > .h-grp');
          _dl = _gs2.length ? _gs2[_gs2.length - 1] : null;
        } catch (e) {}
        if (row.reopened && (_fr ? _dl === _fr : true)) {
          var _ro = _g('_hgTurnReopen');
          if (_ro) { try { _ro(true); } catch (e) {} }
          this._mergedRid = row.rowId;   // 并回回合二次收口不双记（P2-4）
        }
      }
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
          this._lastFinRoot = null;   // a147：摘组即失身份记忆（防陈旧匹配）
        } else if (fin && hasWork) {
          this._lastFinRoot = (g && g.root) || null;   // 供并回身份校验
          try { fin(false, { turnEnd: true,
                             endTs: row.endedAt || Date.now() }); } catch (e) {}
          // 对抗审 P2-3/P2-5（a142）：正常回合收口补回合记账与识图清算
          // （V3 _hgTurnWrapup 的职责，随其删除丢失）——dur 优先事件值，
          // 网关缺失时 _hgTurnEnd 内部回落本地差值。并回回合（a147·E）：
          // 不再整体跳过（回合史只记首段+turnTools 顺延污染）——改为修正
          // ring 末条的全量工时并清段尾工具数
          if (row.rowId === this._mergedRid) {
            var _tm = _g('_hgTurnMend');
            if (_tm) { try { _tm(row.activeMs || 0); } catch (e) {} }
          } else {
            var _te = _g('_hgTurnEnd');
            if (_te) { try { _te(row.state === 'error' ? 'error'
                              : (row.state === 'cancelled' ? 'interrupt' : 'ok'),
                                row.activeMs || 0); } catch (e) {} }
          }
          var _vs2 = _g('_hgVisionSweep');
          if (_vs2) { try { _vs2(true); } catch (e) {} }
        }
      }
      return;
    }
    if (row.kind === 'subagent') {
      // a91（真凶·用户铁律「子代理后台还在运行，无条件要能够同步」）：本
      // 分支是**终态收口**，但曾无 status 门——readmodel 2s Sync 重发的
      // running 镜像帧也走这里，镜像一到就把档案/行卡定死「完成」（清
      // .h-ag-live+停尾流=「刷新/切会话就不同步」的单点根因；此前的摘标
      // 补丁全在与它打架）。running 帧的档案刷新由 upserted 分支 _agentFile
      // 承担，此处只认终态
      if (row.status === 'running') return;
      // 档案收口（sse.js task_notification 同款）：done/err/result 落档——
      // 胶囊（_hgAgentsRunning 数运行中）与目录读档案，不收口=假运行
      if (!this.opt.sub && typeof _HG !== 'undefined' && _HG.agents
          && row.tid) {
        // v4.0.3（用户实锤「已停止的子代理胶囊还显示运行中」）：原实现
        // 只直查 _HG.agents[row.tid]。注册表 Sync 之后档案键是 **agentId**
        // 而 SUB 行的 tid 是 call tid → 直查恒 miss → 新建一个空档案标
        // done，真正挂着的旧档案（agentId 键）永远 done=false = 胶囊假
        // 运行（实测 SUB 行已翻 success，胶囊仍显示 2 个在跑）。
        // 修：先走单点解析 _hgAg（tid/aidKey/tidMap 三件套），miss 再按
        // childTopic(agentId) 直配，最后才就地建档。
        var a = (typeof _hgAg === 'function' ? _hgAg(row.tid) : null)
                || _HG.agents[row.tid];
        if (!a && row.childTopic) {
          var _aidC = String(row.childTopic).replace(/^sub:/, '');
          if (_aidC && _HG.agents[_aidC]) a = _HG.agents[_aidC];
        }
        if (!a && row.childTopic) {
          // a64：完成太快时 running 中间帧可能没触发建档（点不开+假运行
          // 实测根因）——终态帧就地建/补档案
          a = _HG.agents[row.tid] = {};
        }
        if (a && !a.done) {
          a.done = true; a.doneAt = Date.now();
          a.err = row.status === 'failed';
          // v4.0.3/v4.0.6：停止态落档——stopped 是一等字段（目录/行卡/
          // 胶囊都读它）；interrupted 只留给「失联」语义。原实现只写
          // interrupted，v4 主链上新引入的 a.stopped 从未落档。
          a.stopped = !!row.stopped || row.status === 'cancelled';
          a.interrupted = !!row.stopped;
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
      // v4.0.5（复审实锤）：这是 v4 下 SUB 行**唯一**的终态行卡收口点，
      // 原只传 err → 停止的 SUB 行（status=cancelled / row.stopped=true）
      // 被画成绿「完成」，与目录的「已中断」自相矛盾。第四参补 stopped。
      var ars = _g('_hgAgentRowState');
      if (ars && row.tid) {
        try {
          ars(row.tid, row.status === 'failed', row.summary || '',
              !!row.stopped || row.status === 'cancelled');
        } catch (e) {}
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
    // a152/a153：TPS/实时上下文 state → _HG.tps + 重画圆环。环值 = ctxLive
    // （assistant usage 真值基准），result 到达落真值。v4.1（用户定调）：
    // 不再叠加 liveToks 生成中估值——估值要下一轮才成为 input，叠上去会
    // 虚高（427K 显示成 96%），估值仅在容量卡下方以旁注显示。
      if (patch.tps !== undefined && !this.opt.sub) {
      _HG.tps = patch.tps;
      var t = _HG.tps || {};
      var live = t.ctxLive || 0;
      // a255（用户实锤 1.3M/500.0K 假 100%）：CLI result 帧的 usage 可能是
      // 全回合/全会话累计口径（v2.20 实测 ~20轮×70K≈1.4M，与本次 1.3M 同
      // 签名）——单轮真实用量物理不可能超窗。renderCtxRing 早有此守卫
      // （v2.20），ctxLive 这条路漏了：累计值直写环=恒 100% 红条。超窗即
      // 判坏数据丢弃，环保留 jsonl 真值（5s 轮询链）。
      // 判据优先级：会话级权威 badMax（/ctx 写）→ 持久化记忆里的阈值/分母
      // → 当前环分母。都不要用固定 2M：实测累计口径约 1.4M（20 轮×70K），
      // 2M 拦不住等于放行（a255 假 100% 回归面）。
      // 注意 ctxWinBy 与 ctxBadMaxBy 由同一 /ctx 响应写入，前者有值后者必有值，
      // 拿窗口当第二源是死分支（a423 的错误修法）
      var _bmBy = _HG.ctxBadMaxBy || {};
      var _bm = (_HG.sid && _bmBy[_HG.sid]) || 0;
      if (!(_bm > 0)) {
        try {
          // 只认 badMax：记忆里的 max 可能是旧代码按名字猜的兜底值
          // （1M 会话存 256K → 420K 被当坏数据丢弃），有权威 badMax
          // 才有 max，反之不成立
          var _rec = JSON.parse(localStorage.getItem('hg-ctx:' + _HG.sid) || 'null');
          if (_rec && _rec.badMax > 0) _bm = _rec.badMax;
        } catch (e) {}
      }
      // 末级用当前显示分母：fx.js 只在分母权威时才会写进 ctxRing
      if (!(_bm > 0) && _HG.ctxRing && _HG.ctxRing.max > 0) _bm = _HG.ctxRing.max;
      // _bm 为 0 = 还没有任何权威阈值（冷启动 + 遗留记忆）：此时只跳过绘制，
      // 不写 t.ctxLive=0——否则会把共享的 _HG.tps 真值抹掉，/ctx 到达后
      // 也拿不回来，白白多空窗一拍
      var _bmKnown = _bm > 0;
      if (_bmKnown && live > 0 && live > _bm) {
        live = 0;
        t.ctxLive = 0;
      }
      var _rr = _g('_hgDrawCtxRing');
      if (_rr && _HG.ctxRing) {
        // a154R（对抗审 P0）：真值锚先于 _rr 取——_hgDrawCtxRing 会把入参
        // used 无条件写回 _HG.ctxRing，故先取真值再画，备忘只记真值。
        // ctxLive=0（网关不给 assistant usage）时回落上一帧环值
        var _tru = live > 0 ? live : _HG.ctxRing.used;
        // 真值锚同样要过同一阈值：live=0 时取的是上一帧的环值，若那帧已被
        // 累计口径污染过，这里会把坏值一直当锚传下去
        if (!(_tru > 0) || (_bm > 0 && _tru > _bm)) _tru = 0;
        var base = _tru;
        // v4.1（用户定调）：圆环只画真值 base，不叠 est——估值要下一轮才
        // 成为 input，CLI 压缩判定也只看真实 input，叠上去会虚高（427K 显示
        // 成 96%）。est 只在容量卡下方以旁注显示。
        try { _rr(base, _HG.ctxRing.max); } catch (e) {}
        // 分母未知时 _rr 走清环分支（ctxRing 变 {0,0}），此时**不能**把真值
        // 留在 used 里：会形成「圆环空 / 备忘录有值」的分叉，容量卡、下一拍
        // 真值锚都会拿这个没有分母的值去算，画出假的 100% 红条
        _HG.ctxRing.used = (_HG.ctxRing.max > 0) ? _tru : 0;
      }
    }
    // 子 pane 的 A 区只消费结论终稿——busy/ask/queue/model 全是主窗语义，
    // 子投影 patch 不得外溢（同 _rebuild 全局账守卫）
    if (this.opt.sub) {
      var _sd = (patch.done !== undefined) ? patch.done : st.done;
      var _sf = (patch.final !== undefined) ? patch.final : st.final;
      var _ce = this._conclNode();
      if (_ce && !this.conclDone && _sd && _sf) {
        this.conclDone = true;
        _ce.innerHTML = '';
        var _md = _g('mdBubble');
        var _dv = document.createElement('div');
        _dv.className = 'h-msg asst';
        if (_md) { try { _dv.appendChild(_md(_sf)); } catch (e) { _dv.textContent = _sf; } }
        else _dv.textContent = _sf;
        _ce.appendChild(_dv);
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
      // G5/S9 修复（a116）：模型名来自投影/转写派生文本，必须转义
      // （同字段 v4main.js:85 与 chatctl.js 都走 esc，此处原为全仓唯一
      // 未转义的投影文本 innerHTML 写入点）。
      if (chip) chip.innerHTML = (typeof esc === 'function'
        ? esc(String(patch.model)) : String(patch.model)
      ) + ' ▾';
    }
    // 压缩状态（a52 归一）：feed per-sid state 驱动 V3 压缩线原件
    // （renderCompaction 读 _HG.compactT0/compactSid——per-sid 投影天然
    // 隔离，他会话压缩不串台；compactUsed 沿用 V3 localStorage 口径）
    if (typeof patch.compacting === 'boolean' && typeof _HG !== 'undefined') {
      var _rc = _g('renderCompaction');
      if (patch.compacting) {
        _HG.compacting = true;
        _HG.compactSid = _HG.sid;
        // a122（用户实锤「压缩不读秒，一直 0s」）：v4 路由下 1s 秒表此前
        // 只由 V3 sse.js 的 status 分支建立，v4bridge 只渲染一次 → 秒数
        // 冻在 0。这里补同款定时器（幂等：已在跑则不重建；_compactionEnd /
        // 离开压缩态统一 clearInterval）。
        // 只从「非压缩态→压缩态」边沿进入（v4feed 侧有 not compacting 守卫），
        // 每次进入都是新一次压缩，起点无条件刷新
        _HG.compactT0 = patch.compactT0 || Date.now();
        try { _HG.compactUsed = (JSON.parse(
          localStorage.getItem((typeof _hgCtxKey === 'function' ? _hgCtxKey(_HG.sid) : '') || 'null')
          || 'null') || {}).used || 0; } catch (e) { _HG.compactUsed = 0; }
        if (_rc) { try { _rc(false); } catch (e) {} }
        // 无条件重建（不靠 _HG.compactTimer 真值防重入）：本函数可能被
        // 重放态反复调用，先清后建保证任何时刻只有一个在跑。三处退出路径
        // （下方 else 分支、定时器体内自清、relay._hgCompactionEnd）都已
        // 顺手把 compactTimer 置 null，此处不依赖它们的行为。
        // 重复到达同一压缩态只会重置「当前时刻→下次 tick」，秒数不倒退
        // （compactT0 保持不变）。
        if (typeof setInterval === 'function') {
          if (_HG.compactTimer) { try { clearInterval(_HG.compactTimer); } catch (e) {} }
          _HG.compactTimer = setInterval(function () {
            if (!_HG.compacting) {
              clearInterval(_HG.compactTimer); _HG.compactTimer = null; return;
            }
            if (_rc) { try { _rc(false); } catch (e) {} }
          }, 1000);
        }
      } else if (_HG.compacting) {
        // 对抗审 P3-4（a142）：统一走 _hgCompactionEnd——原内联清理漏了
        // compactResume 归属传递与 actWord 退出；该函数自带幂等门
        var _ce = _g('_hgCompactionEnd');
        if (_ce) { try { _ce(); } catch (e) {} }
      }
    }
    // 子 pane 结论终稿（一次成型）
    var _cce = this._conclNode();
    if (_cce && !this.conclDone) {
      var done = (patch.done !== undefined) ? patch.done : st.done;
      var txt = (patch.final !== undefined) ? patch.final : st.final;
      if (done && txt) {
        this.conclDone = true;
        _cce.innerHTML = '';
        var md = _g('mdBubble');
        var dv = document.createElement('div');
        dv.className = 'h-msg asst';
        if (md) { try { dv.appendChild(md(txt)); } catch (e) { dv.textContent = txt; } }
        else dv.textContent = txt;
        _cce.appendChild(dv);
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
  // a122（用户拍板「必须全有，性能优化参考主窗口」）：子窗格裁剪改**回合窗**
  // ——与主窗/服务端 wire_snapshot 同口径：保最后 21 个完整轮（第 22 个
  // user 行为窗起点，多带 1 轮），轮内永不切（首派消息=轮锚点天然在场）；
  // 窗外仍全量保留 user 锚点（一轮一锚，上界 60 与服务端同值）——多轮代理
  // 每一轮的消息都可见，性能由 content-visibility（a114 子窗格轮组同享）
  // + 懒体承担，与主窗同一成本模型。兼容两形态：v4 快照行 kind=
  // 'user_input'；V3 回放行 k='user'。
  function _subTailTurns(rows, maxTurns) {
    var isAnc = function (r) {
      return !!r && ((r.kind === 'user_input')
        || (r.kind === undefined && r.k === 'user'
            && String(r.text || '').trim()));
    };
    var start = 0, cnt = 0;
    for (var i = rows.length - 1; i > 0; i--) {
      if (isAnc(rows[i])) {
        cnt++;
        if (cnt > maxTurns) { start = i; break; }
      }
    }
    if (start === 0) return rows;          // 全量在窗内：零裁剪
    var anc = [];
    for (var j = 0; j < start; j++) if (isAnc(rows[j])) anc.push(rows[j]);
    if (anc.length > 60) anc = anc.slice(-60);
    return anc.concat(rows.slice(start));
  }

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
    if (kk === 'assistant_text') return { r: 'text', text: row.text || '',
                                          model: row.model || '', ts: ts };
    if (kk === 'reasoning') return { r: 'think', text: row.text || '',
                                     model: row.model || '', ts: ts };
    if (kk === 'tool_call') {
      var done = row.status && row.status !== 'running';
      return { r: 'tool', name: row.tool || '',
               hint: _toolHintOf(row.input), tid: row.tid || '',
               input: row.input || null, done: !!done,
               out: row.output || '',
               err: row.status === 'error',
               // v4.0.5：cancelled 不能在重建后画成「完成」
               stopped: row.status === 'cancelled' || !!row.stopped, ts: ts };
    }
    return null;
  }

  V4Bridge.prototype._subTab = function () {
    var g = _g('_sub');
    if (!g || !g.tabs || !this.opt.tid) return null;
    return g.tabs[this.opt.tid] || null;
  };

  V4Bridge.prototype._subScrollBottom = function (stick, settle) {
    var sc = (this._t && this._t.sc) || this.flow;
    if (!sc) return;
    if (stick === false) return;
    var self = this;
    try { sc.scrollTop = sc.scrollHeight; } catch (e) {}
    // a119R（用户实锤「重建后视口停在当前轮工作中标头附近」）：整窗重建
    // 恢复贴底时全部卡体是 content-visibility 估高（240px/卡），真高要靠
    // 视口相交逐帧物化——一次 scrollTop=scrollHeight 落在**估高的底部**，
    // 物化后视口被顶到当前轮标头附近。连续 4 帧重钉（约 64ms，用户来不及
    // 手动滚动）随物化追真底；仅重建恢复路径开启
    if (settle) {
      var n = 0;
      var step = function () {
        if (self._closed || !sc.isConnected) return;
        try { sc.scrollTop = sc.scrollHeight; } catch (e) {}
        if (++n < 4) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }
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
      // 且 >15s 无新行 → 强制携权威快照重订阅整窗重对齐。
      // a119R（用户实锤「拉到底部，子代理一来消息滚动跳回工作中标头，
      // 必现」根修）：加**连接健康闸**——ka/帧还在流（store._lastFrameAt
      // 持续刷新）就证明服务端推送循环活着、游标取帧零丢失（a116 九次全审
      // 后 poll 原子语义），行静默=子代理在跑长工具（143 全审实测 198/226
      // 份子转写有 >15s 静默段），此时强拆只会整窗重建：innerHTML='' 抹掉
      // 滚动位置与用户展开态（a116 注释原话「每 15s 触发一次整窗重建，滚动
      // 位置与已展开思考段反复丢失」——当时只修了「增量在流误判」一半，
      // 工具静默这半没关）。连接真死（ka 12s 未至）才强制重对齐
      if (!self._t.done && self._lastRowAt
          && Date.now() - self._lastRowAt > 15000) {
        self._lastRowAt = Date.now();
        if (self.store && !self.store._closed
            && Date.now() - (self.store._lastFrameAt || 0) > 12000) {
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

  // a119（用户实锤「拉到底后子代理一来新消息，滚动条就变位置不贴底」）：
  // v4 增量通道里只有 tool 行自带贴底（追前量 stick/追后回贴），think/text/
  // user/note 走 _subTlAppendRow 零跟随——审计类子代理九成是 think/text 行，
  // 每来一条视口就漂一次，漂超 80px 判距后彻底停跟。统一在通道口收口：
  // 追前量贴底、追后回贴；水合期跳过（逐行 scroll=布局抖动，_subRebuild
  // 尾部自有一份收口）；重复行到达时回贴是幂等空操作
  V4Bridge.prototype._subAppend = function (n) {
    var t0 = this._t;
    var stick0 = (!this._hydrating && t0 && t0.sc && _g('_subPaneStick'))
      ? _g('_subPaneStick')(t0.sc) : false;
    this._subAppendRow(n);
    if (stick0) this._subScrollBottom();
  };
  // 单行追加（含双源查重锚——快照/兜底/delta 三路喂入幂等）
  V4Bridge.prototype._subAppendRow = function (n) {
    var t = this._t;
    if (!t || !t.tl) return;
    this._lastRowAt = Date.now();   // a77：行到达记账（看门狗计时基）
    // a91（用户铁律「子代理后台还在运行，无条件要能够同步」）：主窗行卡
    // 实时摘要改吃子 pane 同一条增量流（V3 sse.js:409 isSub 分支对位）——
    // 此前唯一喂入是 V3 HTTP 尾流轮询（_subTailFeed），首轮全量拉的竞速窗
    // 一旦错过（offset 直达文件尾、无新字节不再重画）live 永不点亮。窗格
    // 增量/回放水合到达即摘要同步：与窗格内容同源同时刻，天然无条件
    if (n.r === 'think' || n.r === 'text' || n.r === 'tool') {
      var _slp = _g('_subLivePaint');
      if (_slp) {
        var _sum = null;
        if (n.r === 'think') _sum = '思考中…';
        else if (n.r === 'text') _sum = '正文 · ' +
          String(n.text || '').replace(/\s+/g, ' ').trim().slice(0, 60);
        else {
          var _hl = _g('_hToolLabel');
          _sum = (_hl ? _hl(n.name) : (n.name || '工具')) + ' · ' +
            String(n.hint || '').slice(0, 64);
        }
        try { _slp(this.opt.agent, _sum); } catch (e) {}
      }
    }
    // a93R（用户实锤「4 个子代理只显示了一个模型」）：model 消费扩到 think
    // 行——零正文纯思考+工具的代理（审计类常态）只靠 text 行永远等不到；
    // 服务端 reasoning 行已随 model（v4feed a93R）
    if (n.model) {
      var _agM = _g('_hgAg') ? _hgAg(this.opt.agent) : null;
      if (_agM && _agM.model !== n.model) {
        _agM.model = n.model;
        var _mm = t.sc ? t.sc.querySelector('.h-mmodel') : null;
        if (_mm) _mm.textContent = String(n.model).split('[')[0].trim();
      }
    }
    // 行时刻统一在此记账（思考段时长/轮时长共用）；更晚 ts 到达先回填
    // 开口思考段（V3 回放 :1156 同款）
    var ts = n.ts || 0;
    var prevTs = this._lastAt || 0;
    if (ts > 0) {
      this._flushPend(ts);
      this._lastAt = ts;
      // a122：当前轮 t0 未锚定的（队列侧建轮/_subTurnNew 无参）以本行时刻
      // 锚定——否则秒表恒「工作中 0s」
      if (!t.t0) t.t0 = ts;
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
      // a122（用户实锤「续派后没有新思考过程/消息重复/幽灵空轮」）：来向
      // 消息双源合一。主窗 SendMessage 行先到 → _subUserQueue 已把**原文**
      // 气泡插入并切轮（kit 侧 tb.t 换新，桥的 this._t 未跟）；子 feed 的
      // user 增量后到，文本是 CLI 包装形（"The coordinator sent a message
      // while you were working: <原文>"）——旧查重拿包装前缀对原文气泡
      // 永不命中 → 二次切轮+再插一条气泡=幽灵空轮（「工作中 0s」冻结）
      // +消息重复。剥包装后比对：命中=采用 kit 已开的轮（this._t=tb.t，
      // 不建轮不插泡），后续思考/工具行自然落进该轮。
      var _mw = String(n.text || '').match(
        /^The coordinator sent a message while you were working:\s*([\s\S]*)$/);
      var headRaw = _mw ? _mw[1].trim().slice(0, 60) : '';
      // a115：水合期 Set 查重（O(1)）；live 保留前缀扫描（流式安全）
      var _rp = this._rp;
      var dupU = false;
      if (this._hydrating && _rp) {
        dupU = !!head && Object.prototype.hasOwnProperty.call(_rp.u, 'u:' + head);
        if (!dupU && headRaw)
          dupU = Object.prototype.hasOwnProperty.call(_rp.u, 'u:' + headRaw);
      } else {
        dupU = head && [...t.sc.querySelectorAll('.hg-sub-u')]
          .some(x => (x.textContent || '').trim().indexOf(head) === 0);
        if (!dupU && headRaw) {
          var _ubs = t.sc.querySelectorAll('.hg-sub-u');
          for (var _ui = 0; _ui < _ubs.length; _ui++) {
            var _ex = (_ubs[_ui].textContent || '').trim();
            if (_ex && _ex.indexOf(headRaw) === 0) { dupU = true; break; }
          }
        }
      }
      if (dupU) {
        var _tbD = this._subTab();
        if (_tbD && _tbD.t && _tbD.t !== t) {
          this._t = _tbD.t;   // 采用队列路径已开的轮
          this._t.v4 = true;  // a122：v4 轮标记（_subTlCap 放宽等的判据）
          // a122：队列侧 _subTurnNew 无参 → t0=0，无人锚定=秒表恒「0s」。
          // 采用时以最近行时刻兜底锚定（后续行到达在 ts 记账处覆写）
          if (!this._t.t0) this._t.t0 = this._lastAt || Date.now();
        }
        return;
      }
      if (_rp && head) _rp.u['u:' + head] = 1;
      if (_rp && headRaw) _rp.u['u:' + headRaw] = 1;
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
      // a115：水合期 Set 精确查重；live 保留双向前缀扫描
      var dupT = false;
      if (this._hydrating && this._rp) {
        dupT = !!want && Object.prototype.hasOwnProperty.call(this._rp.t, want);
      } else {
        dupT = want && [...(t.sc || t.tl).querySelectorAll('.h-msg.asst[data-raw]')]
          .some(x => { var g = _normWs(x.dataset.raw);
                       return !!g && (want.startsWith(g) || g.startsWith(want)); });
      }
      if (dupT) return;
      if (this._rp && want) this._rp.t[want] = 1;
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
      // a115：水合期 Set 精确查重；live 保留前缀扫描
      var dupK = false;
      if (this._hydrating && this._rp) {
        dupK = !!wantK && Object.prototype.hasOwnProperty.call(this._rp.k, wantK);
      } else {
        dupK = wantK && [...t.tl.querySelectorAll('.h-think-seg[data-raw]')]
          .some(x => { var g = _normWs(x.dataset.raw);
                       return !!g && (wantK.startsWith(g) || g.startsWith(wantK)); });
      }
      if (dupK) return;
      if (this._rp && wantK) this._rp.k[wantK] = 1;
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
      // a115：水合期 Set 查重（曾 querySelector 属性选择器 O(n)/行=O(n²)）
      if (this._hydrating && this._rp) {
        if (n.tid) {
          if (Object.prototype.hasOwnProperty.call(this._rp.tool, n.tid)) return;
          this._rp.tool[n.tid] = 1;
        }
      } else if (n.tid) {
        try {
          if (t.tl.querySelector('.h-tool[data-tuid="' + CSS.escape(n.tid) + '"]')) return;
        } catch (e) {}
        if (this._rp) this._rp.tool[n.tid] = 1;
      }
      var at2 = _g('_subTlAppendTool');
      if (!at2) return;
      var stickEl = t.sc;
      var stick = stickEl ? _g('_subPaneStick') && _g('_subPaneStick')(stickEl) : true;
      try { at2(t, n.name, n.hint, n.tid, n.input); } catch (e) {}
      this._openTools.push(n);
      if (n.done) this._subToolDone(n.tid, n.out, n.err, n.stopped);
      else if (stick) this._subScrollBottom();
      return;
    }
    if (n.r === 'result') {   // V3 兜底行的 FIFO 配对
      var w = this._openTools.shift();
      if (w) this._subToolDone(w.tid, n.text, n.err, n.stopped);
    }
  };

  // 工具终态回点（tuid 精确优先；V3 兜底无 tid 行 FIFO；全 miss 静默——
  // 完整结果在工具卡折叠体，孤儿摘要不裸落时间线（V3 v3.4.65 同口径））
  V4Bridge.prototype._subToolDone = function (tid, out, err, stopped) {
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
    // v4.0.6（复审实锤）：子窗格工具行原恒画 completed——被停的工具
    // （status=cancelled）显示绿「完成」。stopped 优先于完成、低于出错。
    if (slots && sb) {
      slots.innerHTML = sb(err ? 'error' : (stopped ? 'stopped' : 'completed'));
    }
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
    if (running && ag && ag.done) {
      // a155R2 观测点位2：子 feed 还在流（st.done=false）但档案说 done——
      // 窗格即将定稿。此即用户症状的发生点，记 ⓘ 诊断日志。零行为变化
      try {
        if (typeof _hgSyncAudit === 'function')
          _hgSyncAudit('窗格定稿', this.opt.agent,
            'feed流中档案done doneAt=' + (ag.doneAt || 0)
            + ' sendAt=' + (ag.sendAt || 0) + ' err=' + !!ag.err
            + ' stopped=' + !!ag.stopped + ' interrupted=' + !!ag.interrupted
            + ' deadEvi=' + (ag.deadEvi === undefined ? '?' : !!ag.deadEvi));
      } catch (_) {}
      running = false;   // 档案终态优先（防投影滞后假跑）
    }
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
      // a93S（用户实锤「子代理已经返回结论了，怎么还在工作中」）：子 feed
      // 的 state.done/final=该代理完成的最权威信号（自己转写的 result 行），
      // 此处向主窗回传——档案收口+行卡定格+胶囊刷新。此前完成信号只有
      // 主 feed 的 notification 镜像单通道，续派包装 tid 映射断链时主窗
      // 永远收不到（胶囊多计、tab 恒 run）
      var _mf = _g('_hgAg') ? _hgAg(this.opt.agent) : null;
      if (_mf && !_mf.done) {
        _mf.done = true; _mf.doneAt = Date.now();
        _mf.err = !!st.err;
        if (finTxt) _mf.result = String(finTxt).trim().slice(0, 400);
        var _cap = _g('_hgDynCapsulePaint');
        if (_cap) { try { _cap(); } catch (e) {} }
        var _srs = _g('renderSideStatus');
        if (_srs) { try { _srs(); } catch (e) {} }
      }
      var _tidM = (typeof _HG !== 'undefined' && _HG.tidMap) ? _HG.tidMap[this.opt.agent] : null;
      var _rowSt = (typeof _HG !== 'undefined' && _HG.rowById)
        ? (_HG.rowById[this.opt.agent] || _HG.rowById[_tidM]) : null;
      var _ars2 = _g('_hgAgentRowState');
      if (_ars2 && _rowSt) {
        // v4.0.6（复审实锤）：子窗格终态收口原不传 stopped——而 _subFinish
        // 的 st.err 对被停恒 false，2.5s 后重画会把主 feed 刚画好的「已停止」
        // 翻回绿「完成」。档案或行上带 stopped 时必须透传。
        try {
          var _aSt = (typeof _hgAg === 'function' ? _hgAg(this.opt.agent) : null)
                     || ((_HG.agents || {})[this.opt.agent]) || {};
          _ars2(_rowSt.dataset.tid || _tidM, !!st.err,
                String(finTxt || '').trim().slice(0, 200),
                !!(_aSt && (_aSt.stopped || _aSt.interrupted)));
        } catch (e) {}
      }
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
    // P2 修复（a116）：清掉 V3 tick——_subOpen 在 run 态启动的秒表 interval
    // 每秒执行「档案未 done 则把 t.done 翻回 false」，与子 feed 的定稿
    // （a99：state.final 收口）打架=窗格头被翻回「工作中」。
    if (tb.tick) { try { clearInterval(tb.tick); } catch (e) {} tb.tick = null; }
    tb.turns = [];
    this._openTools = [];
    this._firstAt = 0; this._lastAt = 0; this._pend = [];
    this._conclLocked = false; this._t0Note = false;
    this._emptyAt = 0; this._lastRowAt = Date.now();
    var scaffold = _g('_subPaneScaffold');
    // a93/a93R：头部模型两段式——初值=该代理类型的**预显配置模型**（V3
    // sse.js:371 同语义，_hgAgentModelPre 读 ~/.claude/agents frontmatter；
    // 曾恒传空串=零正文纯思考代理头部模型永远空白）；实跑模型由 _subAppend
    // 增量覆盖（a95R 起 think 行即带，重启后端后纯思考代理也秒得实值）
    var _ag0 = _g('_hgAg') ? _hgAg(this.opt.agent) : null;
    var _preM = _g('_hgAgentModelPre');
    var t = scaffold ? scaffold(tb, this.opt.type || 'Task',
                                (_ag0 && _ag0.model)
                                  || (_preM ? _preM(this.opt.type || 'Agent') : ''),
                                this.opt.desc || '')
                     : null;
    if (!t) return;
    t.v4 = true;
    this._t = t;
    tb.t = t;
    var rows = (snap && snap.rows) || [];
    var i, n;
    // a119P（用户实测「打开子代理卡顿」）：渲染前先裁到时间线上限——曾
    // 全量渲染几千行（每行 markdown/diff）再让 _subTlCap 从头删回 220，
    // 渲染即丢弃＝主线程秒级冻结。服务端快照已携尾窗（routes 子 topic
    // tail=220），此处对旧后端全量下发的兜底同裁。省略数用快照 total
    // （全量行数）与实收行数的差——服务端裁过与旧后端全量都能算真值。
    // 省略条与 _subTlCap 同构（class/dataset 一致），后续 live 增长由
    // cap 顺着同一条递增，两机制无缝衔接
    var _cap = 220;
    var _tot = Math.max((snap && snap.total) || 0, rows.length);
    // a122：行数裁剪退役，改回合窗（旧后端全量下发的兜底也同口径）
    if (rows.length > _cap) rows = _subTailTurns(rows, 21);
    var _omit = Math.max(0, _tot - rows.length);
    // a115（用户实锤「新消息刷出卡 2s/开大窗格卡 4.8s」）：水合查重改 Set——
    // 曾每行 querySelectorAll 全窗格扫（user/text/think/tool 四路）＝O(n²)，
    // 431 行水合 9 万次元素访问+数组分配 churn＝秒级主线程冻结。水合行是
    // 终态数据（feed 全行投递非流式碎片），精确键查重语义等价；live 路
    // 保持原前缀扫描（流式安全），两路都入 Set
    this._rp = { u: {}, t: {}, k: {}, tool: {} };
    this._hydrating = true;
    // a119P：裁尾窗后首行时刻改吃快照携带的全量 firstAt（服务端裁剪前
    // 的真值）——否则大子会话轮时长按尾窗首行算短
    if (snap && snap.firstAt) this._firstAt = snap.firstAt;
    for (i = 0; i < rows.length; i++) {
      n = _subNorm(rows[i], false);
      if (n) this._subAppend(n);   // 行时刻/思考段 pend 在 append 内统一记账
    }
    this._hydrating = false;
    if (_omit > 0 && t.tl && t.tl.children.length) {
      var om = document.createElement('div');
      om.className = 'hg-sub-omit';
      om.dataset.omitted = String(_omit);
      // a261：图标位换 SVG——动态计数走 DOM 构建（textContent 不吃 HTML）
      om.textContent = '';
      var _omIco = document.createElement('span');
      _omIco.style.verticalAlign = '-2.5px';
      _omIco.innerHTML = ICO16.upload;
      om.appendChild(_omIco);
      om.appendChild(document.createTextNode(' 已省略 ' + _omit + ' 行'));
      t.tl.insertBefore(om, t.tl.firstChild);
    }
    if (rows.length) {
      var st = (snap && snap.state) || {};
      // 快照内工具行自带终态（upsert 语义）
      for (i = 0; i < rows.length; i++) {
        if (rows[i] && rows[i].kind === 'tool_call'
            && rows[i].status && rows[i].status !== 'running') {
          this._subToolDone(rows[i].tid, rows[i].output,
                            rows[i].status === 'error',
                            rows[i].status === 'cancelled'
                              || !!rows[i].stopped);
        }
      }
      // 首 t0=首行时刻（V3 回放 P3a 同口径）
      if (this._t && !this._t.t0) this._t.t0 = this._firstAt || 0;
      this._subFinish(st);
      tb.rpN = rows.length;   // 已铺底：shell 态的 4s ensure 循环构造性消失
      if (stick) this._subScrollBottom(null, true);   // a119R：多帧重钉追真底
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
          // a119P：兜底路径同裁——回放转写全量行（几千行级），渲染完再被
          // _subTlCap 删回 220 ＝白干；直接渲染尾窗+省略条（同 _subRebuild）
          var _fa2 = rows[0] && rows[0].ts ? (Date.parse(rows[0].ts) || 0) : 0;
          // a122：兜底回放同改回合窗（全量行裁最后 21 轮，锚点全保留）
          var _tot2 = rows.length;
          if (rows.length > 220) rows = _subTailTurns(rows, 21);
          var _om2 = Math.max(0, _tot2 - rows.length);
          if (_fa2 && !self._firstAt) self._firstAt = _fa2;   // 全量首行时刻保真
          // a128（用户实测 perf 档案实锤「长会话胶囊点开卡顿 600ms」）：兜底
          // 渲染必须挂 _hydrating 旗——旧路径按 live 语义逐行跑：行行
          // querySelectorAll 查重（O(n²)）+ _subPaneStick 逐行读滚动几何
          // （次次强排全文档布局，长会话主窗 90k 节点=每行几十 ms）＝单帧
          // 600ms 长任务。挂旗后走 Set 精确查重 + 跳过逐行贴底（与快照
          // 水合同一条快速路）。
          self._hydrating = true;
          try {
            for (var i = 0; i < rows.length; i++) {
              var n = _subNorm(rows[i], true);
              if (n) self._subAppend(n);   // ts 记账在 append 内统一
            }
          } finally {
            self._hydrating = false;
          }
          if (_om2 > 0 && self._t && self._t.tl && self._t.tl.children.length) {
            var om2 = document.createElement('div');
            om2.className = 'hg-sub-omit';
            om2.dataset.omitted = String(_om2);
            // a261：图标位换 SVG——动态计数走 DOM 构建（textContent 不吃 HTML）
            om2.textContent = '';
            var _omIco2 = document.createElement('span');
            _omIco2.style.verticalAlign = '-2.5px';
            _omIco2.innerHTML = ICO16.upload;
            om2.appendChild(_omIco2);
            om2.appendChild(document.createTextNode(' 已省略 ' + _om2 + ' 行'));
            self._t.tl.insertBefore(om2, self._t.tl.firstChild);
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
    // G3 修复（a116）：任何 delta 到达都算「数据在流」——看门狗计时基必须
    // 记账。原实现只在 _subAppend/_subRebuild 记账，于是 row.upserted
    // （工具收口）/state.updated 期间不刷新 → 真实数据 4.0% 的工具调用
    // >15s、198/226 份子转写存在 >15s 静默段 → 长工具期每 15s 触发一次
    // 整窗重建，滚动位置与已展开思考段反复丢失。
    this._lastRowAt = Date.now();
    var stickEl = t.sc;
    var stick = stickEl && _g('_subPaneStick') ? _g('_subPaneStick')(stickEl) : true;
    if (d.op === 'row.appended') {
      var n = _subNorm(d.row, false);
      if (n) this._subAppend(n);   // ts 记账在 append 内统一
    } else if (d.op === 'row.upserted') {
      if (d.row && d.row.kind === 'tool_call') {
        this._subToolDone(d.row.tid, d.row.output, d.row.status === 'error',
                          d.row.status === 'cancelled' || !!d.row.stopped);
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
