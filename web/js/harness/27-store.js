// harness store.js (R0 流式/重渲统一管线：dispatch/订阅/rAF 合并 + 副作用执行器)
  // ==================== store（ZCode useSyncExternalStore 的 vanilla 对位）====================
  // 纪律（designer 方案）：reducer 纯函数化——归约过程中**只产 effect 描述**
  // （fx 数组），dispatch 尾部统一执行（renderQueue/apiPost/showBanner 等
  // 全部是 effect，不进 reducer）。订阅回调 rAF 合并（13-panel renderSideStatus
  // 同款先例）。live 与冷读（coldAdapter 产同一 FEV）共用 dispatch——
  // 「流式和重渲完全统一」的落点。
  const _HG_STORE = {
    subs: [],            // 订阅回调列表 fn(dirtyKeys[])
    _raf: 0,
    _dirty: new Set(),
    subscribe(fn) {
      if (typeof fn === 'function' && this.subs.indexOf(fn) < 0) this.subs.push(fn);
    },
    unsubscribe(fn) {
      const i = this.subs.indexOf(fn);
      if (i >= 0) this.subs.splice(i, 1);
    },
    mark() {   // 标脏（键名自由约定，订阅方按需过滤）；rAF 合并触发
      for (let i = 0; i < arguments.length; i++) this._dirty.add(arguments[i]);
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = 0;
        const d = Array.from(this._dirty);
        this._dirty.clear();
        for (const fn of this.subs) { try { fn(d); } catch (_) {} }
      });
    },
    flush() {   // 立即触发（冷读全量渲染等场景；合并语义同 mark）
      if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
      if (!this._dirty.size) return;
      const d = Array.from(this._dirty);
      this._dirty.clear();
      for (const fn of this.subs) { try { fn(d); } catch (_) {} }
    },
  };

  // ---- 副作用执行器（reducer 产的 fx 描述 → 现有全局函数；集中一处便于
  //      R1+ 渲染函数收编时逐步替换实现而不动 reducer）----
  function _hgRunFx(f) {
    if (!f || !f.op) return;
    switch (f.op) {
      case 'render_side':
        try { renderSideStatus(); } catch (_) {}
        return;
      case 'render_queue':
        try { renderQueue(); } catch (_) {}
        return;
      case 'render_entries':
        try { _hgRenderEntries(); } catch (_) {}
        return;
      case 'banner':
        try { showBanner(String(f.text || ''), f.ms || 3000, !!f.warn); } catch (_) {}
        return;
      case 'api_queue_del':
        try {
          if (f.id) apiPost('/api/harness/queue_act',
            { sid: _HG.sid, id: f.id, act: 'del' },
            { label: '拦截补杀失败——该消息可能复活，请手动删除' });
        } catch (_) {}
        return;
      case 'ask_render':
        try { askRender(f.it); } catch (_) {}
        return;
      case 'ask_done':
        try { askDone(f.it); } catch (_) {}
        return;
      default:
        return;
    }
  }

  // ---- R1 渲染消费：entries 增量 → 现有渲染函数（UI 风格不变——渲染
  //      函数本体零改动，live/冷读经此合一）。游标防重：SSE snapshot 重放/
  // 事件双路到达时已渲染过的 entry 不重画（ZCode 幂等投影的渲染面）----
  let _hgEntryCursor = 0;
  function _hgRenderEntries() {
    const p = _HG.proj;
    const es = (p && p.entries) || [];
    if (_hgEntryCursor > es.length) _hgEntryCursor = 0;   // 投影重置（切会话）
    for (; _hgEntryCursor < es.length; _hgEntryCursor++) {
      const e = es[_hgEntryCursor];
      if (!e || !e.t) continue;
      switch (e.t) {
        case 'renew': renderRenew(e.text); break;
        case 'audit': renderAudit(e.text); break;
        case 'raw': renderRaw(e.text); break;
        case 'sysnote': renderSysNote(e.kind, e.text); break;
        case 'model_switched': renderSwitch(e.text || '默认模型'); break;
        case 'turn_exit': renderExit(e.text); break;
        case 'turn_interrupted': renderExit(e.text); break;
        // R2a（气泡域归一）：assistant/thinking 两类——渲染原语两轨本就
        // 共享（renderAsst/startThinking/appendThinking），此处接成唯一入口；
        // live 流式（计时动画）与 hist 重建（壳+懒抽屉+无动画）按 entry.live
        // 分形态（产品形态差异，ZCode 无此对位物——环境适配存档）
        case 'assistant_text':
          renderAsst(e.text || '', e.model || _HG.model || '');
          break;
        // R2b：user 气泡——live/hist 同一入口（renderUser 承担组管线边界）；
        // ts 时间条 hist 形态带（live 流式无）
        case 'user_message':
          renderUser(e.text || '', e.images || [], e.files || [], false,
                     e.ts ? new Date(e.ts).getTime() : 0);
          break;
        // R4：跨会话回传——识图 peer 行优先配对 .h-vision 卡（v3.4.88 口径：
        // tid 精确/无 tid 回落最早未定格卡 FIFO），miss 走平铺气泡（v2.53
        // hist 参数防开新段）；live/hist 同一 case
        case 'peer_return': {
          const _nm = String(e.name || '');
          if (_nm.indexOf('识图') !== -1) {
            let _vc = (e.tid && _HG.visionCalls && _HG.visionCalls[e.tid]) || null;
            if (!_vc) {
              const _open = [..._hgFlow.querySelectorAll('.h-tool.h-vision:not([data-vres])')];
              _vc = _open[0] || null;   // 全审 P5：FIFO 取最早未定格
            }
            if (_vc) {
              _hgVisionResult(_vc, e.text || '', false);
              if (e.tid && _HG.visionCalls) delete _HG.visionCalls[e.tid];
              break;
            }
          }
          renderPeer(e.name, e.text, null, true, true);
          break;
        }
        case 'assistant_thinking':
          if (e.live) {
            closeRun(); appendThinking(e.text || '');
          } else {
            startThinking(true);
            const _segEl = _HG.think && _HG.think.seg;
            if (_segEl && e.hi != null) {
              _segEl.dataset.hi = String(e.hi);
              _segEl.dataset.hgLazy = '1';
            } else appendThinking(e.text || '');   // 兜底：无行号（理论不达）
            endThinking(true);
            if (_segEl && e.ts > 0)
              _HG.thinkPend = { seg: _segEl,
                t0: (e.prevTs > 0 && e.prevTs < e.ts) ? e.prevTs : e.ts };
          }
          break;
        default: break;
      }
    }
  }
  function _hgEntryCursorReset() { _hgEntryCursor = 0; }

  // ---- dispatch：FEV → 纯归约 → 副作用/通知（live 与冷读唯一入口）----
  // R0：_hgProjEvent 的现有归约逻辑已迁入 _hgReduce（纯函数，fx 出参）；
  // dispatch = _hgReduce + fx 执行 + store.mark。10-sse 的 onmessage 先过
  // dispatch 再走 legacy 分派（分批收编，R1+ 逐域退役 legacy）。
  function _hgDispatch(ev) {
    if (!ev || !ev.t) return;
    if (!_HG.proj) _HG.proj = _hgProjInit(_HG.sid);
    const fx = [];
    try { _hgReduce(_HG.proj, ev, fx); } catch (_) {}
    for (let i = 0; i < fx.length; i++) _hgRunFx(fx[i]);
    if (fx.length) _HG_STORE.mark('proj');
  }

  // ---- 冷读入口（R1+ 逐域接线）：transcript 行数组 → FEV → dispatch ----
  function _hgDispatchHist(lines) {
    for (const l of (lines || [])) {
      for (const ev of _fevFromHistLine(l)) _hgDispatch(ev);
    }
    _HG_STORE.flush();
  }
