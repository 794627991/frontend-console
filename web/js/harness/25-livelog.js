// harness livelog.js —— v3.5.219 流式显示与重渲归一化（designer 方案 Phase B）
// ============================================================
// 架构（用户定调「流式的显示内容我要，规整我也要，1s 一刷新我接受」）：
// SSE 事件**不直渲染主链**——归约为 transcript 同构行追加进 _HG.histAll
// 尾部（live 账本），1s tick 用 renderHistLine 族增量刷屏。屏幕从此只有
// hist 渲染器一种形态（回合折叠头+竖线工作区+思考行+工具行带徽章）。
//
// 三个核心机制：
// 1. 懒壳消解重渲：hist 形态思考段/工具行默认收起+懒抽屉（点开才从
//    histAll[hi] 现填）——账本行就是 histAll 活对象，内容增长不需重渲，
//    点开自然读到最新。tick 只做「append 新行 + patch 工具行徽章 +
//    refresh 活动正文气泡」，预算 <5ms。
// 2. hEnd 戳护栏：_histRender 给每行产物盖 data-h-end；live-only 元素
//    （任务卡/子代理段/识图卡/转交线/ph 气泡）全都没戳——tick 只动带戳
//    元素，live-only 按构造存活。
// 3. 真源对账：transcript 恒为真源；回合终 fetch 整体替换 histAll +
//    主链签名比对，不符才补一次窗口重渲（常态跳过=零闪烁）。
//
// kill-switch：_HG.liveHist=false（localStorage hg-livehist）走旧直渲路径。
// ============================================================
'use strict';

// _HG.liveLedger：{ provStart: histAll 中转写真源的截止长度, dirty: bool,
//   rows: 本回合已 append 的行号集合（patch 定位用）, lastMsgKey: 当前
//   assistant 消息归属（thinking/text 行归约的闭合判据）, tickMs: 当前
//   tick 间隔（自适应） }
(function () {
  // ---- 归约器：事件块 → transcript 同构行 ----

  // thinking/text 块（同消息多块 '\n' 拼接进同一行——对齐 transcript.py:440
  // join 语义，修「每块一个气泡」的异常形态）
  function _llText(role, txt, model) {
    const L = _HG.liveLedger;
    if (!_HG.histAll || !L) return;
    const last = _HG.histAll[_HG.histAll.length - 1];
    const open = last && last.role === role && last.__live;
    if (open) {
      last.text = (last.text || '') + '\n' + txt;
    } else {
      _HG.histAll.push({ role: role, text: txt, ts: new Date().toISOString(),
        __live: true, __dirty: true });
    }
    L.dirty = true;
  }

  // tool_use 块：按 tid 幂等（同 tid 再到合并 input——流式分块 input）
  function _llToolUse(b) {
    const L = _HG.liveLedger;
    if (!_HG.histAll || !L || !b.id) return;
    for (let i = _HG.histAll.length - 1; i >= Math.max(0, _HG.histAll.length - 60); i--) {
      const r = _HG.histAll[i];
      if (r && r.tid === b.id && r.role === 'tool') {
        r.input = Object.assign({}, r.input || {}, b.input || {});
        r.__dirty = true; L.dirty = true;
        return;
      }
    }
    _HG.histAll.push({ role: 'tool', text: b.name || '',
      input: Object.assign({}, b.input || {}), result: null,
      tid: b.id, ts: new Date().toISOString(), __live: true, __dirty: true });
    L.dirty = true;
  }

  // tool_result（isSynthetic user 侧）：按 tool_use_id 回填 result/err
  function _llToolResult(res) {
    const L = _HG.liveLedger;
    if (!_HG.histAll || !L) return;
    for (let i = _HG.histAll.length - 1; i >= Math.max(0, _HG.histAll.length - 200); i--) {
      const r = _HG.histAll[i];
      if (r && r.role === 'tool' && r.tid === res.tool_use_id) {
        const c = res.content;
        r.result = typeof c === 'string' ? c
          : Array.isArray(c) ? c.map(x => (x && x.text) || '').join('\n') : '';
        if (res.is_error) r.err = true;
        r.__dirty = true; r.__settled = true;
        L.dirty = true;
        return;
      }
    }
    // 未知 tid（重放窗口外/竞态）——不入账，回合终对账兜底
  }

  // user_echo：回合边界——追加 user 行
  function _llUser(text) {
    const L = _HG.liveLedger;
    if (!_HG.histAll || !L) return;
    _HG.histAll.push({ role: 'user', text: String(text || ''),
      ts: new Date().toISOString(), __live: true, __settled: true });
    L.dirty = true;
  }

  // ---- tick 引擎：append / patch / refresh ----

  let _llTimer = null;

  function _hEndMax() {
    let m = 0;
    _hgFlow.querySelectorAll('[data-h-end]').forEach(el => {
      m = Math.max(m, +(el.dataset.hEnd || 0));
    });
    return m;
  }

  // 活动正文行（__live assistant 未闭合）→ 移除旧 DOM 原位重加（renderAsst
  // 共享工厂产出，几乎恒在时间线尾部）
  function _llRefreshAsst() {
    const ha = _HG.histAll;
    for (let i = ha.length - 1; i >= 0; i--) {
      const r = ha[i];
      if (!r.__live) break;
      if (r.role === 'assistant' && r.__dirty) {
        // 旧 DOM（同 hEnd 戳的 asst 元素）移除；renderHistLine 重画
        _hgFlow.querySelectorAll('.h-msg.asst[data-h-end="' + i + '"]').forEach(e => e.remove());
        try { renderHistLine(r, i); } catch (_) {}
        r.__dirty = false;
        return;
      }
      if (r.role === 'user') break;
    }
  }

  function _hgLiveTick() {
    const L = _HG.liveLedger;
    if (!L || !_HG.histAll) return;
    if (!_HG.busy && !L.dirty) { _llStop(); return; }
    if (!L.dirty) return;
    const t0 = performance.now();
    L.dirty = false;
    // ① append：hEnd 之后的新 settled 行（user/完整 assistant 之外的行
    //    即时 append；assistant 活动行走 ③ refresh——但回合内 text 块就
    //    是 assistant 行，首块 append 建壳，增量走 refresh）
    let hEnd = _hEndMax();
    const ha = _HG.histAll;
    const noScrollPrev = _HG.noScroll;
    _HG.noScroll = true;
    try {
      for (let i = hEnd + 1; i < ha.length; i++) {
        const r = ha[i];
        if (!r) continue;
        try { renderHistLine(r, i); } catch (e) {
          try { console.error('[harness] livelog append fail @' + i, e); } catch (_) {}
          L.dirty = true;   // 下 tick 重试
          break;
        }
        if (r.role !== 'assistant') r.__settled = true;
      }
      // ② patch：已渲 tool 行有新 result（__settled 未上屏）——原位补徽章
      _hgFlow.querySelectorAll('.h-tool[data-tid]').forEach(row => {
        const tid = row.dataset.tid;
        const r = ha.find(x => x && x.tid === tid && x.__live);
        if (r && r.result != null && !row.dataset.llDone) {
          row.dataset.llDone = '1';
          try { renderOneToolResult(r, row); } catch (_) { row.dataset.llDone = ''; }
        }
      });
      // ③ refresh：活动正文气泡（增量文本原位更新）
      _llRefreshAsst();
    } finally { _HG.noScroll = noScrollPrev; }
    // ④ 滚动跟随（stickBtm=false 时不打扰）
    try { if (_HG.stickBtm !== false) _hgScrollBottom(); } catch (_) {}
    // ⑤ 一致性自检 + 预算自适应
    const cost = performance.now() - t0;
    if (cost > 50) L.tickMs = 2000;
    else if (L.tickMs === 2000 && cost < 30) L.tickMs = 1000;
  }

  function _llStart() {
    const L = _HG.liveLedger;
    if (_llTimer || !L) return;
    _llTimer = setInterval(() => {
      if (!L || !_HG.histAll || _HG.readonly) return;
      _hgLiveTick();
    }, L.tickMs || 1000);
  }
  function _llStop() {
    if (_llTimer) { clearInterval(_llTimer); _llTimer = null; }
  }

  // 强制刷屏（lifecycle 信封前调用——收尾操作面对最新 DOM）
  function _hgLiveFlush() {
    const L = _HG.liveLedger;
    if (!L || !L.dirty) return;
    _hgLiveTick();
  }

  // 回合终对账：签名比对，不符窗口重渲一次做对（常态跳过）
  function _hgLiveReconcile(sid) {
    const L = _HG.liveLedger;
    if (!L || !_HG.histAll) return;
    fetch('/api/harness/transcript?sid=' + encodeURIComponent(sid))
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok || _HG.sid !== sid) return;
        const fetched = j.lines || [];
        // 主链签名：role+tid+text 长度序列（忽略 sub_* 注入行）
        const sig = arr => arr.filter(l => l && !String(l.role).startsWith('sub_'))
          .map(l => l.role + ':' + (l.tid || '') + ':' + String(l.text || '').length).join('|');
        const a = sig(_HG.histAll.slice(L.provStart));
        const b = sig(fetched.slice(L.provStart));
        if (a !== b) {
          _hgDiag('livelog', 'reconcile mismatch → 窗口重渲（行 ' + L.provStart + '，账本 ' + _HG.histAll.length + ' vs 转写 ' + fetched.length + '）');
          _HG.histAll = fetched;
          _histRender(fetched, _HG.histStart | 0, { noFinalize: !!_HG.busy });
          if (_HG.busy && typeof phResume === 'function') phResume(true);
          if (typeof _hgSpinShow === 'function') { try { _hgSpinShow(!!_HG.busy); } catch (_) {} }
          try { _hgScrollBottom(true); } catch (_) {}
        } else {
          _HG.histAll = fetched;   // 签名相符：静默换真源，零闪烁
        }
        // 账本清零（新回合起 provStart=真源长度）
        L.provStart = fetched.length;
        L.dirty = false;
      }).catch(() => {});
  }

  // 清账本（切会话/SSE 清场/换代）
  function _hgLiveReset() {
    const L = _HG.liveLedger;
    if (L) { L.dirty = false; L.provStart = (_HG.histAll || []).length; }
  }

  window._hgLL = { text: _llText, toolUse: _llToolUse, toolResult: _llToolResult,
    user: _llUser, flush: _hgLiveFlush, reconcile: _hgLiveReconcile,
    reset: _hgLiveReset, start: _llStart, stop: _llStop };
})();
