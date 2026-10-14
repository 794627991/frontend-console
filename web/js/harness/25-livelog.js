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
        model: model || _HG.model || '',   // r1 P9：model 随行（中途切模型归属正确）
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
  let _llTimerMs = 0;   // r1 P7：自适应间隔重建判据

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
        // r2 N1：删除锚=data-hi（asst 气泡随 renderAsst(hi) 带 hi）；
        // 重画后同址盖 hEnd——原 data-h-end 删除锚对无戳气泡永 miss=只增不删
        _hgFlow.querySelectorAll('.h-msg.asst[data-hi="' + i + '"]').forEach(e => e.remove());
        try { renderHistLine(r, i); } catch (_) {}
        const _el = _hgFlow.querySelector('.h-msg.asst[data-hi="' + i + '"]');
        if (_el) _el.dataset.hEnd = String(i);
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
        // r1 P4：user 行不入屏（renderUser 乐观链已渲，账本只做回合边界账）
        if (r.role === 'user') { r.__settled = true; continue; }
        try { renderHistLine(r, i); } catch (e) {
          try { console.error('[harness] livelog append fail @' + i, e); } catch (_) {}
          L.dirty = true;   // 下 tick 重试
          break;
        }
        // r2 N1：hEnd 记账闭环——按 data-hi 寻址行元素本体盖戳（tool/thinking
        // 行 renderHistTool/思考段自带 dataset.hi；assistant 行 r2 起随
        // renderAsst(hi) 落 hi）。原 lastElementChild 判据被 DOM 嵌套架空
        // （行落在组 tl/查阅组内，永非 flow 直接子级）——每 tick 全量重渲
        const _el = _hgFlow.querySelector('[data-hi="' + i + '"]');
        if (_el) _el.dataset.hEnd = String(i);
        r.__settled = true;
      }
      // ② patch：已渲 tool 行有新 result——原位补徽章（r1 P3：renderOneToolResult
      // 吃 tool_result 信封且经 rowById 寻行（账本行不在册）——自写就地更新：
      // 徽章 done/error + 折叠体结果摘要，不动 DOM 结构（幂等天然成立）
      _hgFlow.querySelectorAll('.h-tool[data-tid]').forEach(row => {
        if (row.dataset.llDone) return;
        const tid = row.dataset.tid;
        const r = ha.find(x => x && x.tid === tid && x.__live && x.result != null);
        if (!r) return;
        row.dataset.llDone = '1';
        try {
          const st = row.querySelector('.h-tslots');
          if (st) st.innerHTML = statusBadge(r.err ? 'error' : 'completed');
          row.classList.toggle('err', !!r.err);
          const coll = row.querySelector('.h-tool-coll');
          if (coll && !coll.innerHTML.trim()) {
            const pre = document.createElement('div');
            pre.className = 'h-tool-body';
            pre.appendChild(document.createTextNode(String(r.result || '').slice(0, 2000)));
            coll.appendChild(pre);
          }
        } catch (_) { row.dataset.llDone = ''; }
      });
      // ③ refresh：活动正文气泡（增量文本原位更新）
      _llRefreshAsst();
    } finally { _HG.noScroll = noScrollPrev; }
    // ④ 滚动跟随（stickBtm=false 时不打扰）
    try { if (_HG.stickBtm !== false) _hgScrollBottom(); } catch (_) {}
    // ⑤ 一致性自检 + 预算自适应（r2 P7：tick 内检测变更即重建 interval——
    // busy 期间无人再调 start()，原「跨回合生效」降频在最需要时失效）
    const cost = performance.now() - t0;
    if (cost > 50) L.tickMs = 2000;
    else if (L.tickMs === 2000 && cost < 30) L.tickMs = 1000;
    if (L.tickMs !== _llTimerMs) _llStart();   // _llStart 幂等（_llTimerMs 判据）
  }

  function _llStart() {
    const L = _HG.liveLedger;
    if (!L) return;
    const ms = L.tickMs || 1000;
    if (_llTimer) {                    // r1 P7：tickMs 变更时重建 interval
      if (_llTimerMs === ms) return;
      clearInterval(_llTimer);
    }
    _llTimerMs = ms;
    _llTimer = setInterval(() => {
      if (!L || !_HG.histAll || _HG.readonly) return;
      _hgLiveTick();
    }, ms);
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
          .map(l => l.role + ':' + (l.tid || '') + ':' + String(l.text || '').length
            + ':' + (l.err ? 'E' : '') + ':' + (l.result != null ? 'R' : '')).join('|');
        // r2 N2b：签名含 err/result 位——徽章漂移（err 翻转/result 回填）
        // 也触发重渲兜底，错工具不再永久留绿 completed
        const a = sig(_HG.histAll.slice(L.provStart));
        const b = sig(fetched.slice(L.provStart));
        // r1 P5：sub_* 中位注入使 fetched 更长但主链签名仍相符——索引
        // 漂移后 DOM 的 hEnd/hi 全部指错行。相符判据收紧：主链签名一致
        // 且总长度一致（中位注入=长度差→走重渲分支盖新戳）
        const _match = (a === b) && (fetched.length === _HG.histAll.length);
        if (!_match) {
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
    // r1 P6：清场时 histAll 即将被清/重建——provStart 置 0（不取将失效的
    // length），重建完成后由回合终 reconcile 校准为真源长度
    const L = _HG.liveLedger;
    if (L) { L.dirty = false; L.provStart = 0; }
  }

  window._hgLL = { text: _llText, toolUse: _llToolUse, toolResult: _llToolResult,
    user: _llUser, flush: _hgLiveFlush, reconcile: _hgLiveReconcile,
    reset: _hgLiveReset, start: _llStart, stop: _llStop };
})();
