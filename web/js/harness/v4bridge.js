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
    this.unsub = store.subscribe(function (ev) { self._onEv(ev); });
  }

  V4Bridge.prototype.close = function () {
    if (this.unsub) { this.unsub(); this.unsub = null; }
  };

  V4Bridge.prototype._onEv = function (ev) {
    var kind = ev && ev.kind;
    if (kind === 'snapshot') this._rebuild(ev.snap);
    else if (kind === 'deltas') {
      var ds = ev.deltas || [];
      for (var i = 0; i < ds.length; i++) this._applyOne(ds[i]);
    }
  };

  // ---- snapshot：V3 整窗原件一次调用（窗口/懒填/归档/定稿/导轨全套） -------

  V4Bridge.prototype._rebuild = function (snap) {
    var rows = (snap && snap.rows) || [];
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
    }
    var rss = _g('renderSideStatus');
    if (rss) { try { rss(); } catch (e) {} }
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
        if (a && !a.done) {
          a.done = true; a.doneAt = Date.now();
          a.err = row.status === 'failed';
          a.result = String(row.summary || '').trim().slice(0, 400);
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

  root.V4Bridge = V4Bridge;
})(window);
