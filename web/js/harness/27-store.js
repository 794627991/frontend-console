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
      default:
        return;
    }
  }

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
