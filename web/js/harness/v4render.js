/* v4render —— 投影行 → 渲染基元适配层（ZCode 归一管线，批D）。
 *
 * 职责边界：v4store 只产 snapshot/deltas；本层把行适配到**现有渲染基元**
 * （renderUser/renderAsst/renderToolUse/renderOneToolResult/思考段/FEV
 * dispatch）——叶子复用、驱动归一：live 与回放同一入口（本层的 rowRender），
 * 「工具行不入账」「live 直改 DOM」「方案B 整窗」三病灶根治于此。
 *
 * 对位 ZCode ConversationRowView（按 kind 分发行渲染器）+ turnRenderUnits
 * （组聚合交给现有组管线——renderUser 定稿上组/grpEnsure 开组已自管理）。
 *
 * 挂载：window.V4Render(store, flowEl, opt)。opt: {live:true 主窗|false 子pane}。
 */
(function (root) {
  'use strict';

  function _g(name) { return typeof root[name] === 'function' ? root[name] : null; }
  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function V4Render(store, flowEl, opt) {
    var self = this;
    this.store = store;
    this.flow = flowEl;
    this.opt = opt || {};
    this.rowEls = {};            // rowId → DOM（upsert 定位）
    this.unsub = store.subscribe(function (ev) { self._onEv(ev); });
  }

  V4Render.prototype.close = function () {
    if (this.unsub) { this.unsub(); this.unsub = null; }
  };

  // ---- 事件入口（store 通知 → 渲染） ------------------------------------

  V4Render.prototype._onEv = function (ev) {
    var kind = ev && ev.kind;
    if (kind === 'snapshot') {
      this._rebuild(ev.snap);
    } else if (kind === 'deltas') {
      var ds = ev.deltas || [];
      for (var i = 0; i < ds.length; i++) this._applyOne(ds[i]);
      this._afterLive();
    }
  };

  // ---- snapshot 整建（唯一整窗路径：服务端裁决帧） -------------------------

  V4Render.prototype._rebuild = function (snap) {
    this.rowEls = {};
    var flow = this.flow;
    while (flow.firstChild) flow.removeChild(flow.firstChild);
    var rows = (snap && snap.rows) || [];
    var prevAt = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      try {
        if (r.kind === 'reasoning' && typeof _HG !== 'undefined') {
          // 思考段时长口径（hist 同款）：起点=上一带 ts 行、下一条带 ts 行定格
          this._rowRender(r, false, prevAt);
        } else {
          this._rowRender(r, false, 0);
        }
      }
      catch (e) { /* 行级隔离：单行异常不伤整窗 */ }
      // 行级 ts 账（renderUser 定稿工时与思考段时长的数据源——对齐 renderHistLine）
      if (r.at && r.kind !== 'user_input' && r.kind !== 'turn_header'
          && typeof _HG !== 'undefined') {
        _HG.histLineTs = r.at;
        _HG.histActTs = r.at;
      }
      if (r.at) prevAt = r.at;
    }
    // 终态清理（回放态）：收思考段/关运行行/定稿尾组
    var fns = [_g('endThinking'), _g('closeRun')];
    for (var j = 0; j < fns.length; j++) { try { fns[j] && fns[j](); } catch (e) {} }
    var fin = _g('grpFinalize');
    if (fin) { try { fin(true, { hist: true, endTs: Date.now() }); } catch (e) {} }
    // 子 pane：snapshot 即含终态（state.final）时结论区一次成型
    if (snap && snap.state && snap.state.final) this._statePatch(snap.state);
    this._scrollFollow(true);
  };

  // ---- deltas 增量（封闭五操作） ------------------------------------------

  V4Render.prototype._applyOne = function (d) {
    var op = d.op;
    if (op === 'row.appended') {
      try { this._rowRender(d.row, true); } catch (e) {}
    } else if (op === 'row.upserted') {
      this._rowUpsert(d.row);
    } else if (op === 'row.delta') {
      this._rowAppend(d.rowId, d.path, d.append);
    } else if (op === 'row.removed') {
      this._suffixRemove(d.fromRowId);
    } else if (op === 'state.updated') {
      this._statePatch(d.patch || {});
    }
  };

  V4Render.prototype._afterLive = function () {
    this._scrollFollow(false);
  };

  // ---- 行渲染（kind 分发 → 现有基元） -------------------------------------

  V4Render.prototype._rowRender = function (row, live, prevTs) {
    var k = row.kind;
    var el = null;
    if (k === 'user_input') {
      var imgs = Array.isArray(row.images) ? row.images : [];
      var files = row.files || [];
      var rU = _g('renderUser');
      if (rU) {
        // live user_echo 的 images=路径数组；hydration 的 images=计数（无路径，
        // 附件详情在 files）
        el = rU(row.text || '', imgs, files, live, row.at || 0);
      }
    } else if (k === 'assistant_text') {
      var rA = _g('renderAsst');
      if (rA && (row.text || '').trim()) el = rA(row.text, row.model || '');
    } else if (k === 'reasoning') {
      var disp = _g('_hgDispatch');
      if (disp) {
        // 394 口径：live/hist 同一 FEV handlers（思考段/滚播/懒抽屉全复用）
        disp({ t: 'assistant_thinking', text: row.text || '',
               hi: null, ts: live ? 0 : (row.at || 0),
               prevTs: live ? 0 : (prevTs || 0), live: !!live });
      }
    } else if (k === 'tool_call') {
      el = this._toolRow(row, live);
    } else if (k === 'marker') {
      this._markerRow(row);
    } else if (k === 'peer_notify') {
      el = this._peerRow(row);
    } else if (k === 'vision') {
      el = this._visionRow(row, live);
    } else if (k === 'subagent') {
      el = this._subagentRow(row, live);
    } else if (k === 'turn_header') {
      if (!live && row.state && row.state !== 'running') {
        // 回放态组定稿由 renderUser 管线走；live 终态在 _rowUpsert 收口
      }
    }
    if (el && row.rowId) this.rowEls[row.rowId] = el;
    return el;
  };

  // 工具行：回放终态=done 形态一次成型（对齐 renderHistTool）；live 增量=
  // run 形态建卡（后续 upsert 终态回写）。run→done 双构造是会话加载巨卡
  // 的主因之一（百余工具卡翻倍开销）。
  V4Render.prototype._toolRow = function (row, live) {
    var el = null;
    var done = row.status && row.status !== 'running'
      && row.status !== 'streaming_input';
    var id = row.tid || ('v4r' + row.rowId);
    if (done && !live) {
      var card = _g('hgToolCard');
      if (!card) return null;
      card({ id: id, name: row.tool || '', input: row.input || {},
             phase: 'done', err: row.status === 'error',
             summary: row.summary,
             result: (row.status === 'error' || row.output) ? (row.output || '') : undefined });
      el = _pickToolEl(id);
      var dc = _g('drawerCount'), place = _g('_tlPlace');
      if (el && dc) { try { dc(row.tool || ''); } catch (e) {} }
      if (el && place) { try { place(el, row.tool || '', row.input || {}); } catch (e) {} }
    } else {
      var rT = _g('renderToolUse');
      if (!rT) return null;
      rT({ id: id, name: row.tool || '', input: row.input || {} }, false);
      el = _pickToolEl(id);
      if (el && live) el.classList.add('hg-enter');
      // 迟到终态（live 期间行已建、upsert 未到前 snapshot 重放）：直收
      if (el && done) this._toolDone(row, el);
    }
    if (el && row.tid && typeof _HG !== 'undefined' && _HG.rowById) {
      _HG.rowById[row.tid] = el;
    }
    return el;
  };

  function _pickToolEl(id) {
    if (typeof _HG !== 'undefined' && _HG.rowById) return _HG.rowById[id] || null;
    return null;
  }

  // 工具终态：复用 renderOneToolResult（错误/折叠体/组头冒泡全复用）
  // + 终态徽章必写（P0-1 根治：completed 也写状态+耗时——徽章是行状态纯函数）
  V4Render.prototype._toolDone = function (row, el) {
    var tr = { tool_use_id: row.tid || ('v4r' + row.rowId),
               content: row.output || '', is_error: row.status === 'error' };
    var r1 = _g('renderOneToolResult');
    if (r1) { try { r1(tr); } catch (e) {} }
    var head = el && (el._grouped ? el._groupHead : el);
    var slots = head && head.querySelector('.h-tslots');
    if (slots && row.status !== 'error') {
      var badge = _g('statusBadge');
      var st = row.status === 'success' ? 'completed' : row.status;
      var dur = '';
      if (row.endedAt && row.startedAt && row.endedAt > row.startedAt) {
        var ms = row.endedAt - row.startedAt;
        dur = ms >= 60000 ? Math.round(ms / 60000) + 'm' + Math.round(ms % 60000 / 1000) + 's'
                          : (ms / 1000).toFixed(1) + 's';
      }
      slots.innerHTML = (badge ? badge(st) : st) + (dur ? ' <span class="h-tdur">' + dur + '</span>' : '');
      var flip = _g('_hgBadgeFlip');
      if (flip) { try { flip(slots); } catch (e) {} }
    }
    if (el) el.classList.toggle('err', row.status === 'error');
  };

  // upsert：按 rowId 定位更新（终态收口/行换整）
  V4Render.prototype._rowUpsert = function (row) {
    var el = this.rowEls[row.rowId];
    if (row.kind === 'tool_call') {
      if (!el && typeof _HG !== 'undefined' && _HG.rowById) el = _HG.rowById[row.tid];
      if (el) { this.rowEls[row.rowId] = el; this._toolDone(row, el); }
      return;
    }
    if (row.kind === 'turn_header') {
      if (row.state && row.state !== 'running') {
        var fin = _g('grpFinalize');
        if (fin) { try { fin(false, { turnEnd: true, endTs: row.endedAt || Date.now() }); } catch (e) {} }
      }
      return;
    }
    if (row.kind === 'subagent') { this._subagentDone(row, el); return; }
    if (row.kind === 'vision') { this._visionDone(row, el); return; }
    // 其余 kind 的结构变化：换整行（删旧建新，动画按 rowId 防重播）
    if (el && el.parentNode) {
      var next = document.createElement('div');
      el.parentNode.replaceChild(next, el);
      delete this.rowEls[row.rowId];
      this._rowRender(row, false);
    }
  };

  // row.delta：流式文本追加（滚播/正文 append——CLI partial 未开，预留）
  V4Render.prototype._rowAppend = function (rowId, path, append) {
    var el = this.rowEls[rowId];
    if (!el || !append) return;
    var aT = _g('appendThinking');
    if (aT) { try { aT(append); } catch (e) {} }
  };

  V4Render.prototype._suffixRemove = function (fromRowId) {
    for (var rid in this.rowEls) {
      if (Number(rid) >= fromRowId) {
        var el = this.rowEls[rid];
        if (el && el.parentNode) el.parentNode.removeChild(el);
        delete this.rowEls[rid];
      }
    }
  };

  // ---- 杂项行（复用 FEV dispatch / 最小 DOM） ------------------------------

  V4Render.prototype._markerRow = function (row) {
    var disp = _g('_hgDispatch');
    var mk = row.mkind || '';
    if (disp) {
      if (mk === 'renew') disp({ t: 'renew', text: row.text || '' });
      else if (mk === 'audit') disp({ t: 'audit', text: row.text || '' });
      else if (mk === 'sysnote') disp({ t: 'sysnote', kind: '', text: row.text || '' });
      else if (mk === 'interrupted') disp({ t: 'turn_interrupted', text: row.text || '', hist: false });
      else if (mk === 'exit') disp({ t: 'turn_exit', text: row.text || '', hist: false });
      else if (mk === 'model_switched') disp({ t: 'model_switched', text: row.text || '' });
      return;
    }
    var d = document.createElement('div');
    d.className = 'h-sysnote';
    d.textContent = row.text || mk;
    this.flow.appendChild(d);
  };

  // 协作回传通知行（424 形态约定：.h-sub-notify 单行摘要，禁 .h-peer 平铺）
  V4Render.prototype._peerRow = function (row) {
    var d = document.createElement('div');
    d.className = 'h-sub-notify';
    d.title = (row.brief || row.title || '').slice(0, 400);
    d.innerHTML = '<span class="h-sub-notify-ico">📤</span> ' +
      '<span class="h-sub-notify-t">' + _esc(row.title || '协作回传') + '</span>' +
      (row.brief ? ' <span class="h-sub-notify-b">' + _esc(String(row.brief).slice(0, 120)) + '</span>' : '');
    this.flow.appendChild(d);
    d.classList.add('hg-enter');
    return d;
  };

  // ---- 批E 占位（子代理/识图细化随后续批补齐，先给最小形态） ----------------

  V4Render.prototype._subagentRow = function (row, live) {
    var d = document.createElement('div');
    d.className = 'h-sub-notify h-v4-agent';
    d.dataset.v4Child = row.childTopic || '';
    d.innerHTML = '<span class="h-sub-notify-ico">🤖</span> ' +
      '<span class="h-sub-notify-t">' + _esc(row.agentType || 'Agent') + '</span> ' +
      '<span class="h-sub-notify-b">' + _esc((row.summary || '').slice(0, 100)) + '</span>';
    this.flow.appendChild(d);
    if (live) d.classList.add('hg-enter');
    return d;
  };

  V4Render.prototype._subagentDone = function (row, el) {
    var head = el || this.rowEls[row.rowId];
    if (!head) return;
    var b = head.querySelector('.h-sub-notify-b');
    if (b) b.textContent = (row.summary || '').slice(0, 100);
    head.classList.toggle('err', row.status === 'failed');
  };

  V4Render.prototype._visionRow = function (row, live) {
    var d = document.createElement('div');
    d.className = 'h-vision-card';
    d.innerHTML = '<div class="h-vc-head">📸 识图 <span class="h-vc-st">' +
      (row.status === 'done' ? '完成' : '识别中…') + '</span></div>' +
      '<div class="h-vc-body">' + _esc((row.prompt || '').slice(0, 200)) + '</div>';
    this.flow.appendChild(d);
    if (live) d.classList.add('hg-enter');
    return d;
  };

  V4Render.prototype._visionDone = function (row, el) {
    var head = el || this.rowEls[row.rowId];
    if (!head) return;
    var st = head.querySelector('.h-vc-st');
    if (st) st.textContent = row.status === 'error' ? '失败' : '完成';
  };

  // ---- A 区状态（busy/queue/done+final——spinner/排队条/子代理结论区） -----

  V4Render.prototype._statePatch = function (patch) {
    if (typeof patch.busy === 'boolean') {
      var busy = _g('setBusy') || _g('_hgSetBusy');
      if (busy) { try { busy(patch.busy); } catch (e) {} }
    }
    // 子 pane 结论终稿必达：state.done + final → 结论区一次成型
    if (this.opt.conclEl && (patch.done || patch.final !== undefined)) {
      var txt = patch.final;
      if (txt === undefined && this.store && this.store.snap)
        txt = (this.store.snap.state || {}).final;
      if (txt) {
        var cel = this.opt.conclEl;
        if (!cel.dataset.v4FinalDone) {
          cel.dataset.v4FinalDone = '1';
          var md = _g('mdBubble');
          var d = document.createElement('div');
          d.className = 'h-msg asst';
          if (md) { try { d.appendChild(md(txt)); } catch (e) { d.textContent = txt; } }
          else d.textContent = txt;
          cel.appendChild(d);
        }
      }
    }
  };

  // ---- 滚动跟随（简版：用户在底则贴底；上翻不拽回） -------------------------

  V4Render.prototype._scrollFollow = function (force) {
    var box = this.flow && this.flow.parentElement;
    if (!box) return;
    var nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    if (force || nearBottom) box.scrollTop = box.scrollHeight;
  };

  root.V4Render = V4Render;
})(window);
