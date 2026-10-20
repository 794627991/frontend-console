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
    for (var i = 0; i < rows.length; i++) {
      var L = rowToLine(rows[i]);
      if (L) lines.push(L);
    }
    if (typeof _HG !== 'undefined') {
      _HG.histAll = lines;                  // V3 账本即渲染账本
      _HG.seq = snap ? snap.seq : 0;
      _HG.epoch = (snap && snap.epoch) || _HG.epoch;
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
    if (snap && snap.state) this._paintState(snap.state, true);
  };

  // ---- deltas：翻译成 V3 原生入口 ----------------------------------------

  V4Bridge.prototype._applyOne = function (d) {
    var op = d.op;
    if (op === 'row.appended') {
      var row = d.row, live = true;
      var L = rowToLine(row);
      if (!L) return;
      if (row.kind === 'tool_call' && row.status === 'running') {
        // V3 live 工具行：run 形态建卡（终态回写锚=rowById[tid]）
        var rT = _g('renderToolUse');
        if (rT) { try { rT({ id: row.tid || '', name: row.tool || '',
                             input: row.input || {} }, false); } catch (e) {} }
        return;
      }
      if (live) L.live = 1;                 // V3 live 语义（动画/占位/组头）
      // 思考段收口对齐 V3 sse（:335/:339）：任何非 thinking 行到达前
      // endThinking——否则段头残留流式滚播尾巴（用户实测「思考结束还残留
      // 思考内容，不统一」）
      if (L.role !== 'thinking' && this._lastRole === 'thinking') {
        var eT = _g('endThinking'), cR = _g('closeRun');
        if (eT) { try { eT(); } catch (e) {} }
        if (cR) { try { cR(); } catch (e) {} }
      }
      this._lastRole = L.role;
      var add = _g('_hgRowAdd');
      if (add) { try { add(L); } catch (e) {} }
    } else if (op === 'row.upserted') {
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
      var r1 = _g('renderOneToolResult');
      if (r1 && row.tid) {
        try { r1({ tool_use_id: row.tid, content: row.output || '',
                   is_error: row.status === 'error' }); } catch (e) {}
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
      // 档案收口（V3 agent 行卡终态）：_hgAgentRowState 存在则委托
      var ars = _g('_hgAgentRowState');
      if (ars && row.tid) {
        try { ars(row.tid, row.status === 'failed', row.summary || ''); }
        catch (e) {}
      }
      return;
    }
    if (row.kind === 'vision') {
      var vr = _g('_hgVisionResult');
      if (vr && row.tid) { try { vr(row.tid, row.status !== 'error',
                                   row.prompt || ''); } catch (e) {} }
    }
  };

  // ---- A 区状态 → V3 原函数 -----------------------------------------------

  V4Bridge.prototype._paintState = function (patch, isSnapshot) {
    var st = (this.store && this.store.snap && this.store.snap.state) || {};
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
      if (typeof _HG !== 'undefined') _HG.queue = patch.queue;
      var rq = _g('renderQueue');
      if (rq) { try { rq(); } catch (e) {} }
    }
    if (patch.model && typeof _HG !== 'undefined') {
      _HG.model = patch.model;
      var q = (typeof _hgQ !== 'undefined') ? _hgQ : null;
      var chip = q ? q('[data-hg-model]') : null;
      if (chip) chip.innerHTML = String(patch.model) + ' ▾';
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
