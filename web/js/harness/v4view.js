/* v4view —— 投影行 → DOM 的唯一渲染层（ZCode ConversationTimeline 对位）。
 *
 * 设计铁律（对照 ZCode packages/ui/src/v4/{ConversationTimeline,ConversationRowView}）：
 *   1. **DOM 是投影的纯函数**：同一 snapshot 渲染两次必须逐字节一致；
 *      本文件不持有任何会话事实，只持有「rowId → DOM」索引。
 *   2. **无全局状态机**：没有 _HG.grp 单活组、没有 phStart 占位、没有
 *      _histLineTs 行级 ts 账——组由行的 turnId 标签派生，多组天然并存。
 *   3. **两种帧来源、一条管线**：snapshot → rebuild()；deltas → applyDelta()。
 *      历史与 live 走同一 placeRow/upsertRow，没有第二套渲染动作。
 *   4. **行自包含**：upsert 换整行（结构变化），delta 只 append 文本，
 *      表达不了的结构变化由服务端发 snapshot（协议封闭五操作）。
 *
 * UI 不变：产出的 class 结构与旧 harness 逐 class 对齐（.h-grp/.h-grp-proc/
 * .h-turn-head/.h-turn-body/.h-tl/.h-msg.user/.h-msg.asst/.h-mmeta/...），
 * CSS 一条不改；交互委托仍由 main.js 的 _hgFlowClick 处理（本层不加事件）。
 *
 * 依赖的纯叶子（无状态，可安全复用）：
 *   mdBubble/plainBubble/attChipsHtml/esc/openLightbox（ask-md/base）
 *   hgToolCard（tools，phase='done' 一次成型；已抽为纯构造）
 *   statusBadge/diffHtml/_hgToolBadges/_hgIsExplore/...（tools/reducer）
 *   renderMd/codeBlockEnhance
 * 不依赖：_HG.grp / grpEnsure / renderUser / renderAsst / _hgDispatch /
 *   _histRender / _tlPlace / phStart / grpFinalize / appendThinking。
 */
(function (root) {
  'use strict';

  var TICK_MS = 500;           // 活动组头秒表刷新（唯一全局定时器）
  var TAIL_MSG = 200;          // 单组正文上限提示（不硬截，仅用于折叠策略）

  function _g(name) { return typeof root[name] === 'function' ? root[name] : null; }

  function V4View(store, flowEl, opt) {
    var self = this;
    this.store = store;
    this.flow = flowEl;
    this.opt = opt || {};
    this.isSub = !!this.opt.sub;
    this.rowEls = {};          // rowId → 行根元素
    this.grpEls = {};          // turnId → {root, proc, head, body, tl, think, label, sub}
    this.turnOrder = [];       // turnId 顺序（末组判 live）
    this.thinkSeg = null;      // 当前活动思考段（{el, t0}）
    this.tick = null;
    this.conclEl = this.opt.conclEl || null;
    this.conclDone = false;
    this.unsub = store.subscribe(function (ev) { self._onEv(ev); });
    this._startTick();
  }

  V4View.prototype.close = function () {
    if (this.unsub) { this.unsub(); this.unsub = null; }
    this._stopTick();
  };

  // ======================================================================
  // 帧入口（唯一推进路径）
  // ======================================================================

  V4View.prototype._onEv = function (ev) {
    var kind = ev && ev.kind;
    if (kind === 'snapshot') {
      this.rebuild(ev.snap);
    } else if (kind === 'deltas') {
      var ds = ev.deltas || [];
      for (var i = 0; i < ds.length; i++) {
        try { this.applyDelta(ds[i]); } catch (e) { console.error('[v4view] delta', ds[i], e); }
      }
      this._afterFrame();
    }
  };

  // ======================================================================
  // snapshot 整窗（服务端单方裁决；整体替换绝不 merge）
  // ======================================================================

  V4View.prototype.rebuild = function (snap) {
    var f = this.flow;
    this.rowEls = {};
    this.grpEls = {};
    this.turnOrder = [];
    this.thinkSeg = null;
    // 结论区可能位于 flow 内（子 pane）——整窗清场不能把它删掉
    var cel = this.conclEl;
    if (cel && cel.parentNode === f) f.removeChild(cel);
    while (f && f.firstChild) f.removeChild(f.firstChild);
    if (cel) { f.appendChild(cel); cel.innerHTML = ''; }
    this.conclDone = false;
    var rows = (snap && snap.rows) || [];
    for (var i = 0; i < rows.length; i++) {
      try { this.placeRow(rows[i], false); }
      catch (e) { console.error('[v4view] row', rows[i], e); }
    }
    this.paintState((snap && snap.state) || {});
    this._afterFrame();
  };

  // ======================================================================
  // delta 增量（封闭五操作）
  // ======================================================================

  V4View.prototype.applyDelta = function (d) {
    var op = d && d.op;
    if (op === 'row.appended') {
      if (this.rowEls[d.row.rowId]) return;      // 幂等
      this.placeRow(d.row, true);
    } else if (op === 'row.upserted') {
      this.upsertRow(d.row);
    } else if (op === 'row.delta') {
      this.appendRow(d.rowId, d.path, d.append);
    } else if (op === 'row.removed') {
      this.removeSuffix(d.fromRowId);
    } else if (op === 'state.updated') {
      this.paintState(d.patch || {});
    }
  };

  // ======================================================================
  // 行放置（唯一行出口）：按 kind 分发
  // ======================================================================

  V4View.prototype.placeRow = function (row, live) {
    var k = row.kind;
    var el = null;
    if (k === 'turn_header') {
      var g = this._grpEnsure(row.turnId || ('t' + row.rowId), row);
      this.paintHead(row.turnId || ('t' + row.rowId));
      el = g.root;
    } else if (k === 'user_input') {
      el = this._userRow(row, live);
    } else if (k === 'assistant_text') {
      el = this._asstRow(row, live);
    } else if (k === 'reasoning') {
      el = this._thinkRow(row, live);
    } else if (k === 'tool_call') {
      el = this._toolRow(row, live);
    } else if (k === 'subagent') {
      el = this._agentRow(row, live);
    } else if (k === 'vision') {
      el = this._visionRow(row, live);
    } else if (k === 'peer_notify') {
      el = this._peerRow(row, live);
    } else if (k === 'marker') {
      el = this._markerRow(row, live);
    }
    if (el && row.rowId != null) this.rowEls[row.rowId] = el;
    return el;
  };

  // ======================================================================
  // 组（turn）——由 turnId 派生，多组并存，无认回逻辑
  // ======================================================================

  V4View.prototype._grpEnsure = function (turnId, hdr) {
    var g = this.grpEls[turnId];
    if (g) return g;
    var root = document.createElement('div');
    root.className = 'h-grp';
    root.dataset.turn = turnId;
    var proc = document.createElement('div');
    proc.className = 'h-grp-proc';
    var head = document.createElement('button');
    head.className = 'h-turn-head';
    head.dataset.hgTurnTgl = '1';
    head.style.display = 'none';
    head.innerHTML =
      '<span class="h-chev">▸</span>' +
      '<span class="h-turn-label">工作中 0s</span>' +
      '<span class="h-turn-sub"></span>';
    var body = document.createElement('div');
    body.className = 'h-turn-body';
    var think = document.createElement('div');
    think.className = 'h-drawer think';
    think.style.display = 'none';
    think.innerHTML =
      '<button class="h-drawer-head"><span class="h-chev">▸</span>' +
      '<span class="h-drawer-title">🧠 思考</span>' +
      '<span class="h-tslots" data-hg-dslots></span></button>' +
      '<div class="h-drawer-body"></div>';
    var tl = document.createElement('div');
    tl.className = 'h-tl';
    body.appendChild(think);
    body.appendChild(tl);
    proc.appendChild(head);
    proc.appendChild(body);
    root.appendChild(proc);
    this._append(root);
    g = {
      turnId: turnId, root: root, proc: proc, head: head, body: body,
      think: think, thinkBody: think.querySelector('.h-drawer-body'),
      thinkTitle: think.querySelector('.h-drawer-title'),
      tl: tl, label: head.querySelector('.h-turn-label'),
      sub: head.querySelector('.h-turn-sub'),
      hdr: hdr || null, startedAt: (hdr && hdr.at) || 0,
      counts: { think: 0, tool: 0, sub: 0 }
    };
    this.grpEls[turnId] = g;
    this.turnOrder.push(turnId);
    return g;
  };

  // 组头绘制（纯函数派生：state + 行计数）
  V4View.prototype.paintHead = function (turnId) {
    var g = this.grpEls[turnId];
    if (!g) return;
    var hdr = g.hdr;
    if (!hdr) {
      // 无 turn_header 的组（兜底/迟到）：绝不默认 running——否则假秒表
      // 「工作中 6时2分」（实测 a12：now-最早行at）。按终态渲染防之
      hdr = { state: 'success' };
    }
    var st = hdr.state || 'running';
    if (hdr.at && !g.startedAt) g.startedAt = hdr.at;
    if (st === 'running') {
      g.head.style.display = '';
      g.label.textContent = '工作中 ' + fmtDur(Math.max(0, Date.now() - (g.startedAt || Date.now())));
      g.head.classList.remove('err');
      g.root.dataset.state = 'running';
    } else {
      var ms = (typeof hdr.activeMs === 'number' && hdr.activeMs > 0)
        ? hdr.activeMs
        : (hdr.endedAt && g.startedAt ? Math.max(0, hdr.endedAt - g.startedAt) : 0);
      // 有工作痕迹才亮头（纯正文组无头——对照 ZCode hasWork）
      var hasWork = g.counts.think || g.counts.tool || g.counts.sub
        || g.head.style.display !== 'none';
      g.head.style.display = hasWork ? '' : 'none';
      if (st === 'cancelled') {
        g.label.textContent = '已停止' + (ms ? ' ' + fmtDur(ms) : '');
      } else if (st === 'error') {
        g.label.textContent = '已出错' + (ms ? ' ' + fmtDur(ms) : '');
        g.head.classList.add('err');
      } else {
        g.label.textContent = '已工作' + (ms ? ' ' + fmtDur(ms) : '');
      }
      g.root.dataset.state = st;
      // 定稿即收起（用户点开过的永不强制收）
      if (g.head.dataset.userToggled !== '1') g.body.classList.add('closed');
    }
    var parts = [];
    if (g.counts.think) parts.push('· ' + g.counts.think + ' 思考');
    if (g.counts.tool) parts.push('· ' + g.counts.tool + ' 工具');
    if (g.counts.sub) parts.push('· ' + g.counts.sub + ' 子代理');
    g.sub.textContent = parts.join(' ');
    g.thinkTitle.innerHTML = g.counts.think
      ? '🧠 思考 ' + g.counts.think + ' 次' : '🧠 思考';
  };

  // 行归属：有 turnId 且组存在 → 组内；否则 flow 直挂（marker 等）
  V4View.prototype._host = function (row) {
    var turnId = row.turnId || '';
    if (!turnId) return null;
    var g = this.grpEls[turnId];
    if (!g) {
      // 组未建（turn_header 丢失）→ 懒建，保证行不孤立
      g = this._grpEnsure(turnId, { state: 'running', at: row.at || 0 });
      this.paintHead(turnId);
    }
    return g;
  };

  // ======================================================================
  // 行渲染器（与旧 UI 逐 class 对齐）
  // ======================================================================

  V4View.prototype._userRow = function (row, live) {
    var g = this._host(row);
    var d = document.createElement('div');
    d.className = 'h-msg user';
    var imgs = Array.isArray(row.images) ? row.images : [];
    var files = row.files || [];
    if (imgs.length || files.length) {
      var at = document.createElement('div');
      at.className = 'h-bubble-atts';
      var chips = _g('attChipsHtml');
      at.innerHTML = chips ? chips(imgs, files) : '';
      d.appendChild(at);
    }
    var text = row.text || '';
    var body = (text && text.trim()) || ((imgs.length || files.length)
      ? '（图片/附件，见上方）' : '');
    var pb = _g('plainBubble');
    if (pb) d.appendChild(pb(body));
    else {
      var bb = document.createElement('div');
      bb.className = 'h-bubble';
      bb.textContent = body;
      d.appendChild(bb);
    }
    if (String(text).trim().length > 300) {
      d.classList.add('longfold');
      var fb = document.createElement('button');
      fb.className = 'h-fold-btn';
      fb.dataset.hgFold = '1';
      fb.innerHTML = '展开全文 ▾';
      d.appendChild(fb);
    }
    d.dataset.rtext = text;
    d.dataset.ratts = JSON.stringify({ images: imgs, files: files });
    var acts = document.createElement('div');
    acts.className = 'h-macts';
    acts.innerHTML =
      '<button class="h-mico h-ucopy" title="复制这条消息">📋</button>' +
      '<button class="h-mact h-resend" title="重发这条消息">↻</button>' +
      '<button class="h-mact h-edit" title="编辑后重发（原文+附件填回输入框）">✎</button>';
    d.appendChild(acts);
    if (live) d.classList.add('hg-enter');
    if (g) g.root.appendChild(d); else this._append(d);
    // 新用户消息 = 回合边界：此前已定稿组保持收起（已在 paintHead 定稿时收）
    return d;
  };

  V4View.prototype._asstRow = function (row, live) {
    var text = row.text || '';
    if (!text.trim()) return null;      // 空块不建行（防空白气泡）
    var g = this._host(row);
    var d = document.createElement('div');
    d.className = 'h-msg asst';
    var mb = _g('mdBubble');
    if (mb) d.appendChild(mb(text));
    else { var b = document.createElement('div'); b.className = 'h-bubble';
           b.textContent = text; d.appendChild(b); }
    var bare = row.model ? String(row.model).split('[')[0] : '';
    var rowFt = document.createElement('div');
    rowFt.className = 'h-msg-foot';
    var meta = document.createElement('div');
    meta.className = 'h-mmeta';
    var ava = _g('_hgAvaCls') || function () { return 'h-ava-0'; };
    meta.innerHTML =
      '<span class="h-ava ' + ava(bare || 'AI') + '">' +
      esc((bare || 'AI').charAt(0).toUpperCase()) + '</span>' +
      (bare ? '<span class="h-mmodel" title="本条回复的实跑模型">' + esc(bare) + '</span>' : '');
    var bar = document.createElement('div');
    bar.className = 'hg-msg-acts';
    bar.innerHTML =
      '<button class="hg-mico h-acopy" title="复制这条回复">📋</button>' +
      '<button class="hg-mico" data-hg-collapse title="收起全部工作区">' +
      '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M17 11l-5-5-5 5"/><path d="M17 18l-5-5-5 5"/></svg></button>' +
      '<button class="hg-mact" data-hg-rewind title="回滚到本条所在回合结束：之后的全部丢弃">' +
      '⏪ 回滚到这里</button>';
    rowFt.appendChild(meta);
    rowFt.appendChild(bar);
    d.appendChild(rowFt);
    d.dataset.rtext = text;
    try { d.dataset.rwa = String(text).trim().slice(0, 60); } catch (e) {}
    if (live) d.classList.add('hg-enter');
    // 正文进时间线（与思考/工具时序交错）；无组则直挂
    if (g) {
      if (g.tl.style.display === 'none') g.tl.style.display = '';
      g.tl.appendChild(d);
    } else this._append(d);
    return d;
  };

  // 思考段：一个 reasoning 行 = 一个 .h-think-seg（挂在组时间线）
  V4View.prototype._thinkRow = function (row, live) {
    var g = this._host(row);
    if (!g) return null;
    g.counts.think += 1;
    g.think.style.display = '';
    var seg = document.createElement('div');
    seg.className = 'h-think-seg';
    seg.dataset.raw = row.text || '';
    if (row.at) seg.dataset.t0 = String(row.at);
    var durTxt = '';
    if (row.at && row.spanMs) durTxt = fmtDur(row.spanMs);
    seg.innerHTML =
      '<button class="h-think-seg-head"><span class="h-chev">▸</span>' +
      '<span class="h-think-seg-name">🧠 思考</span>' +
      '<span class="h-think-seg-t">' + esc(durTxt) + '</span>' +
      '</button>' +
      '<div class="h-think-seg-body"></div>' +
      '<i class="h-think-seg-fold" title="收起本段">收起 ⌃</i>';
    // 段正文：非 live（历史）懒填，点开才渲染（性能）；live 直接填
    var body = seg.querySelector('.h-think-seg-body');
    if (live) {
      body.appendChild(mdBubbleSafe(row.text));
      seg.classList.add('hg-enter');
    } else {
      seg.dataset.hgLazy = '1';
    }
    if (live) g.tl.style.display = '';
    g.tl.appendChild(seg);
    if (live) this.thinkSeg = { el: seg, t0: row.at || Date.now() };
    this.paintHead(g.turnId);
    return seg;
  };

  V4View.prototype._toolRow = function (row, live) {
    var g = this._host(row);
    var done = row.status && row.status !== 'running'
      && row.status !== 'streaming_input';
    var card = _g('hgToolCard');
    var el;
    if (!card) {
      el = document.createElement('div');
      el.className = 'h-tool col';
      el.textContent = (row.tool || '工具') + ' · ' + (row.status || '');
    } else {
      el = card({
        id: row.tid || ('v4r' + row.rowId),
        name: row.tool || '',
        input: row.input || {},
        phase: done ? 'done' : 'run',
        err: row.status === 'error' || row.status === 'cancelled',
        result: row.output,
        summary: row.summary,
        dln: row.dln
      }) || document.createElement('div');
    }
    if (row.status === 'error') el.classList.add('err');
    if (row.status === 'cancelled') el.classList.add('cancelled');
    // 终态徽章：卡头 tslots（done 形态已由 hgToolCard 写入；此处补耗时）
    if (done) {
      var slots = el.querySelector('.h-tslots');
      if (slots) {
        var sb = _g('statusBadge');
        var st = row.status === 'error' ? 'error'
          : (row.status === 'cancelled' ? 'denied' : 'completed');
        var dur = '';
        if (row.endedAt && row.startedAt && row.endedAt > row.startedAt)
          dur = ' <span class="h-tdur">' + fmtSec(row.endedAt - row.startedAt) + '</span>';
        slots.innerHTML = (sb ? sb(st) : st) + dur;
      }
    } else {
      var sl = el.querySelector('.h-tslots');
      if (sl && !sl.innerHTML) {
        var sb2 = _g('statusBadge');
        sl.innerHTML = sb2 ? sb2('running') : '';
      }
      // 运行秒表（每行）：由 _tick 统一重绘
      if (row.startedAt) el.dataset.t0 = String(row.startedAt);
    }
    // 放入时间线（查阅类聚组由 _tlPlace 的纯逻辑复制于此，保持 UI 一致）
    if (g) {
      var groupEl = this._tlGroupFor(g, row);
      if (groupEl) groupEl.appendChild(el); else g.tl.appendChild(el);
      if (g.tl.style.display === 'none') g.tl.style.display = '';
      // 计数只在此（append）累加；upsert 换行不再计（防翻倍）
      this._countTool(g, row, 1);
    } else this._append(el);
    if (live) el.classList.add('hg-enter');
    if (g) this.paintHead(g.turnId);
    return el;
  };

  // 查阅聚组（对齐旧 _tlPlace：explore 类工具按组折叠）
  // 计数幂等：同一 rowId 只计一次（upsert 换行不重复计）
  V4View.prototype._countTool = function (g, row, _delta) {
    g._toolIds = g._toolIds || {};
    var key = String(row.rowId);
    if (g._toolIds[key]) return;
    g._toolIds[key] = 1;
    g.counts.tool += 1;
  };
  V4View.prototype._countSub = function (g, row) {
    g._subIds = g._subIds || {};
    var key = String(row.rowId);
    if (g._subIds[key]) return;
    g._subIds[key] = 1;
    g.counts.sub += 1;
  };

  V4View.prototype._tlGroupFor = function (g, row) {
    var isExp = _g('_hgIsExplore');
    if (!isExp) return null;
    var inp = row.input || {};
    if (!isExp(row.tool || '', inp)) return null;
    if (!g.exp) {
      var grpEl = document.createElement('div');
      grpEl.className = 'h-tl-grp';
      grpEl.innerHTML =
        '<button class="h-tl-grp-head"><span class="h-chev">▸</span>' +
        '<span class="h-tl-grp-name">🔍 查阅</span>' +
        '<span class="h-tl-grp-sum"></span></button>' +
        '<div class="h-tl-grp-body"></div>';
      g.tl.appendChild(grpEl);
      g.exp = { el: grpEl, sum: { search: 0, list: 0, file: 0 }, keys: {} };
    }
    var bk = _g('_hgExpBucket'), ek = _g('_hgExpKey'), st = _g('_hgExpSumTxt');
    var key = ek ? ek(row.tool || '', inp) : '';
    if (key && g.exp.keys[key]) return null;      // 同目标去重
    if (key) g.exp.keys[key] = 1;
    if (bk) g.exp.sum[bk(row.tool || '', inp)] += 1;
    var sum = g.exp.el.querySelector('.h-tl-grp-sum');
    if (sum && st) sum.textContent = '· ' + st(g.exp.sum);
    return g.exp.el.querySelector('.h-tl-grp-body');
  };

  // 子代理行：单行任务卡（无正文——红线：子内容进子 pane）
  V4View.prototype._agentRow = function (row, live) {
    var g = this._host(row);
    var build = _g('_hgAgentRowBuild');
    var el;
    if (build) el = build(row.tid || ('v4s' + row.rowId), row.agentType || 'Agent',
                          row.summary || '');
    else {
      el = document.createElement('div');
      el.className = 'h-tool col agentline';
      el.innerHTML = '<button class="h-tool-head"><span class="h-tool-name">✦</span>' +
        '<span class="h-tool-arg">' + esc(row.summary || '') + '</span>' +
        '<span class="h-tslots"></span></button><div class="h-tool-coll"></div>';
    }
    el.dataset.hgAgline = '1';
    if (row.childTopic) el.dataset.v4Child = row.childTopic;
    if (row.tid) el.dataset.tid = row.tid;
    if (row.status && row.status !== 'running') {
      el.dataset.final = '1';
      el.dataset.hgSubr = (row.childTopic || '').replace(/^sub:/, '');
      el.dataset.hgSubType = row.agentType || 'Agent';
      el.dataset.hgSubDesc = String(row.summary || '').slice(0, 120);
      var slots = el.querySelector('.h-tslots');
      var sb = _g('statusBadge');
      if (slots) slots.innerHTML = sb
        ? sb(row.status === 'failed' ? 'error' : 'completed') : '';
      if (row.status === 'failed') el.classList.add('err');
    } else if (row.startedAt) {
      el.dataset.t0 = String(row.startedAt);
    }
    if (g) {
      g.tl.appendChild(el);
      if (g.tl.style.display === 'none') g.tl.style.display = '';
      this._countSub(g, row);
      this.paintHead(g.turnId);
    } else this._append(el);
    if (live) el.classList.add('hg-enter');
    return el;
  };

  // 识图卡：复用旧构造器（class/折叠/懒填全部对齐 _hgVisionCardBuild）
  V4View.prototype._visionRow = function (row, live) {
    var g = this._host(row);
    var build = _g('_hgVisionCardBuild');
    var d;
    if (build) {
      d = build({ prompt: row.prompt || '', imageSource: row.src || '',
                  __chan: row.chan || '', __tid: row.tid || '' });
      d.dataset.v4row = String(row.rowId);
      if (row.status === 'done' || row.status === 'error') {
        var fin = _g('_hgVisionResult');
        if (fin) { try { fin(d, row.result || '', row.status === 'error'); } catch (e) {} }
      }
    } else {
      d = document.createElement('div');
      d.className = 'h-tool col oneclick h-vision';
    }
    if (g) g.tl.appendChild(d); else this._append(d);
    if (live) d.classList.add('hg-enter');
    return d;
  };

  // 协作回传通知行（结构对齐 relay.renderPeer：可点击开对端）
  V4View.prototype._peerRow = function (row, live) {
    var d = document.createElement('div');
    d.className = 'h-sub-notify';
    d.dataset.hgPeer = '1';
    d.title = String(row.brief || row.title || '').slice(0, 400);
    d.innerHTML = '📤 ' + esc(row.title || '协作回传') +
      (row.brief ? '：<span class="h-sub-notify-txt">' +
        esc(String(row.brief).slice(0, 120)) + '</span>' : '');
    this._append(d);
    if (live) d.classList.add('hg-enter');
    return d;
  };

  V4View.prototype._markerRow = function (row, live) {
    var d = document.createElement('div');
    var mk = row.mkind || '';
    d.className = 'h-sysnote';
    d.dataset.hgMkind = mk;
    var ico = { renew: '♻', audit: '⚠', exit: '⏻', interrupted: '⛔',
                sysnote: 'ℹ', model_switched: '⇄' }[mk] || '·';
    d.innerHTML = ico + ' ' + esc(row.text || mk);
    d.title = String(row.text || '').slice(0, 400);
    this._append(d);
    if (live) d.classList.add('hg-enter');
    return d;
  };

  // ======================================================================
  // upsert / append / remove
  // ======================================================================

  V4View.prototype.upsertRow = function (row) {
    var old = this.rowEls[row.rowId];
    if (row.kind === 'turn_header') {
      var g = this.grpEls[row.turnId || ('t' + row.rowId)];
      if (g) { g.hdr = row; if (row.at && !g.startedAt) g.startedAt = row.at; }
      this.paintHead(row.turnId || ('t' + row.rowId));
      return;
    }
    if (row.kind === 'tool_call') {
      var el = old;
      if (el) {
        var parent = el.parentNode;
        var next = this._toolRow(row, false);
        if (next && parent && next !== el) parent.replaceChild(next, el);
        if (next) this.rowEls[row.rowId] = next;
        else if (parent) { parent.removeChild(el); delete this.rowEls[row.rowId]; }
      } else {
        this.placeRow(row, false);
      }
      return;
    }
    if (row.kind === 'subagent') {
      if (old && old.parentNode) {
        var p2 = old.parentNode;
        var n2 = this._agentRow(row, false);
        if (n2 && n2 !== old) p2.replaceChild(n2, old);
        if (n2) this.rowEls[row.rowId] = n2;
      } else this.placeRow(row, false);
      return;
    }
    if (row.kind === 'vision') {
      if (old) {
        // 复用旧定格器（徽章/耗时/懒填 dataset 全对齐）
        var fin = _g('_hgVisionResult');
        if (fin) { try { fin(old, row.result || '', row.status === 'error'); } catch (e) {} }
        return;
      }
      this.placeRow(row, false);
      return;
    }
    // 其余 kind：结构变化换整行（删旧建新）
    if (old && old.parentNode && old !== this.flow) {
      var host = old.parentNode;
      host.removeChild(old);
      delete this.rowEls[row.rowId];
      this.placeRow(row, false);
    } else if (!old) {
      this.placeRow(row, false);
    }
  };

  // row.delta：文本追加（当前 CLI 不开 partial，预留；主要消费 coalesce 后批量）
  V4View.prototype.appendRow = function (rowId, path, append) {
    var el = this.rowEls[rowId];
    if (!el || !append || path !== 'text') return;
    // 正文/思考行：改 bubble 文本（保留 markdown 渲染开销控制——直接 textContent 追加）
    var b = el.querySelector('.h-bubble');
    if (b) b.appendChild(document.createTextNode(append));
    else {
      var seg = el.querySelector('.h-think-seg-body');
      if (seg) seg.appendChild(document.createTextNode(append));
    }
  };

  V4View.prototype.removeSuffix = function (fromRowId) {
    var kill = [];
    for (var rid in this.rowEls) {
      if (Number(rid) >= fromRowId) kill.push(rid);
    }
    for (var i = 0; i < kill.length; i++) {
      var el = this.rowEls[kill[i]];
      if (el && el.parentNode) el.parentNode.removeChild(el);
      delete this.rowEls[kill[i]];
    }
    // 组整体越界：组内已无行的组一并摘除
    for (var tid in this.grpEls) {
      var g = this.grpEls[tid];
      if (!g.root.isConnected || !g.root.parentNode) {
        delete this.grpEls[tid];
        this.turnOrder = this.turnOrder.filter(function (x) { return x !== tid; });
      }
    }
  };

  // ======================================================================
  // A 区状态（busy / queue / final）
  // ======================================================================

  V4View.prototype.paintState = function (patch) {
    var self = this;
    var st = (this.store && this.store.snap && this.store.snap.state) || {};
    // busy：spinner + 输入框态（复用 setBusy 的 UI 语义——纯展示）
    if (typeof patch.busy === 'boolean' || this._lastBusy === undefined) {
      var b = typeof patch.busy === 'boolean' ? patch.busy : !!st.busy;
      if (b !== this._lastBusy) {
        this._lastBusy = b;
        var sb = _g('setBusy');
        if (sb) { try { sb(b); } catch (e) {} }
        else this._spinner(b);
      }
    }
    if (patch.model && typeof _HG !== 'undefined') {
      _HG.model = patch.model;
      var q = (typeof _hgQ !== 'undefined') ? _hgQ : null;
      var chip = q ? q('[data-hg-model]') : null;
      if (chip) chip.innerHTML = esc(patch.model) + ' ▾';
    }
    // 子 pane 结论终稿（state.done + final）：一次成型，绝不重复
    if (this.isSub && this.conclEl && !this.conclDone) {
      var done = (patch.done !== undefined) ? patch.done : !!st.done;
      var txt = (patch.final !== undefined) ? patch.final : st.final;
      if (done && txt) {
        this.conclDone = true;
        this._paintConcl(txt);
      }
    }
    if (this.isSub) this._paintSubHead(st, patch);
  };

  V4View.prototype._paintConcl = function (txt) {
    var cel = this.conclEl;
    if (!cel) return;
    cel.innerHTML = '';
    var d = document.createElement('div');
    d.className = 'h-msg asst';
    var mb = _g('mdBubble');
    if (mb) d.appendChild(mb(txt));
    else d.textContent = txt;
    cel.appendChild(d);
    // 结论出现即撤「工作中」并定稿头
    for (var tid in this.grpEls) {
      var g = this.grpEls[tid];
      if (g.hdr && (!g.hdr.state || g.hdr.state === 'running')) {
        g.hdr.state = 'success';
        this.paintHead(tid);
      }
    }
  };

  // 子 pane 头：终态由 state.done 派生（不靠本地秒表猜）
  V4View.prototype._paintSubHead = function (st, patch) {
    for (var tid in this.grpEls) {
      var g = this.grpEls[tid];
      if (!g.hdr) continue;
      if ((st.done || patch.done) && g.hdr.state === 'running') {
        g.hdr.state = 'success';
        g.hdr.endedAt = g.hdr.endedAt || Date.now();
      }
      this.paintHead(tid);
    }
  };

  V4View.prototype._spinner = function (b) {
    var el = this.flow && this.flow.parentElement
      ? this.flow.parentElement.querySelector('.hg-spin-row') : null;
    if (b && !el) {
      el = document.createElement('div');
      el.className = 'hg-spin-row';
      el.innerHTML = '<span class="hg-spin"></span><span>正在执行…</span>';
      if (this.flow && this.flow.parentNode) this.flow.parentNode.appendChild(el);
    } else if (!b && el) el.remove();
  };

  // ======================================================================
  // 秒表 tick（唯一全局定时器；只重绘运行中的头/行徽章）
  // ======================================================================

  V4View.prototype._startTick = function () {
    var self = this;
    this.tick = setInterval(function () { self._tickPaint(); }, TICK_MS);
  };
  V4View.prototype._stopTick = function () {
    if (this.tick) { clearInterval(this.tick); this.tick = null; }
  };
  V4View.prototype._tickPaint = function () {
    var now = Date.now();
    for (var tid in this.grpEls) {
      var g = this.grpEls[tid];
      if (!g.hdr || g.hdr.state !== 'running') continue;
      if (g.startedAt) g.label.textContent = '工作中 ' +
        fmtDur(Math.max(0, now - g.startedAt));
    }
    // 运行中的工具卡/子代理卡秒表
    var sels = ['.h-tool[data-t0] .h-tslots', '.h-tool.agentline[data-t0] .h-tslots'];
    for (var si = 0; si < sels.length; si++) {
      var list = this.flow ? this.flow.querySelectorAll(sels[si]) : [];
      for (var i = 0; i < list.length; i++) {
        var slot = list[i];
        var row = slot.closest('.h-tool');
        if (!row || row.dataset.final === '1') continue;
        var t0 = +row.dataset.t0 || 0;
        if (!t0) continue;
        var sb = _g('statusBadge');
        slot.innerHTML = (sb ? sb('running') : '') +
          ' <span class="h-tsec">' + Math.round((now - t0) / 1000) + 's</span>';
      }
    }
  };

  // ======================================================================
  // 工具函数
  // ======================================================================

  V4View.prototype._append = function (el) {
    var w = this.flow.querySelector('.hg-welcome');
    if (w) w.remove();
    this.flow.appendChild(el);
  };

  V4View.prototype._afterFrame = function () {
    this._scrollFollow();
  };

  // 滚动跟随后置（用户手动上翻时贴底由 main.js 的 stickBtm 语义兜住）
  V4View.prototype._scrollFollow = function () {
    if (typeof _HG !== 'undefined' && _HG.readonly) return;
    if (typeof _HG !== 'undefined' && _HG.stickBtm === false) return;
    var box = this.flow;
    if (!box) return;
    try { box.scrollTop = box.scrollHeight; } catch (e) {}
  };

  function esc(s) {
    var f = _g('esc');
    if (f) return f(String(s == null ? '' : s));
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function mdBubbleSafe(text) {
    var mb = _g('mdBubble');
    if (mb) { try { return mb(text); } catch (e) {} }
    var d = document.createElement('div');
    d.className = 'h-bubble';
    d.textContent = text;
    return d;
  }
  // 工时文案（与 groups._hgTurnDurTxt 同口径）
  function fmtDur(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return s + ' 秒';
    var m = Math.floor(s / 60); s %= 60;
    if (m < 60) return m + ' 分' + (s ? ' ' + s + ' 秒' : '');
    var h = Math.floor(m / 60);
    return h + ' 时 ' + (m % 60) + ' 分';
  }
  function fmtSec(ms) {
    var s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    return Math.round(s / 60) + 'm' + Math.round(s % 60) + 's';
  }

  root.V4View = V4View;
  root.V4ViewUt = { fmtDur: fmtDur, fmtSec: fmtSec };
})(window);
