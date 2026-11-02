// harness fx.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  const _ACT_WORDS = ['思考中', '处理中', '分析中', '执行中', '检索中', '推理中'];
  function actStart(sinceMs) {
    if (_HG.activity) {
      // v3.5.28（用户实锤「bash 执行中计时每 5s 归零」）：活动条已在场时
      // 只接受「更早的事实起点」纠偏（切会话恢复/自愈带 busy_since），
      // 不带起点的重复 setBusy(true)（事件流竞态补亮等）绝不重置计时——
      // 旧码 innerHTML 重建+actStart=now，5s 自愈轮询一碰就归零
      if (sinceMs && sinceMs < _HG.actStart) _HG.actStart = sinceMs;
      return;
    }
    // v2.26：计时起点优先用后端的 busy_since——切会话回来/自愈纠偏时
    // 不能从「现在」重新计时（用户实锤：执行中切走再切回，计时被清 0）
    _HG.actStart = sinceMs || Date.now();
    _actWordIdx = 0;
    _hgActEl.style.display = 'inline-flex';
    _hgActEl.innerHTML = `<span class="hg-act-dot"></span><span class="hg-act-word" data-hg-aw>思考中</span><span class="hg-act-t" data-hg-act-t>0s</span>`;
    _HG.activity = {
      verb: setInterval(() => {
        // v2.27.4：压缩等特殊状态（actWord 设的 hg-act-special）词固定不轮换
        // ——原实现 4s 必换词，把「正在压缩上下文…」顶掉，用户实测只显示一瞬。
        const w = _hgActEl.querySelector('[data-hg-aw]');
        if (!w || w.classList.contains('hg-act-special')) return;
        _actWordIdx = (_actWordIdx + 1) % _ACT_WORDS.length;
        w.textContent = _ACT_WORDS[_actWordIdx];
      }, 4000),
      tick: setInterval(() => {
        const t = _hgActEl.querySelector('[data-hg-act-t]');
        if (t) t.textContent = _hgFmtDur((Date.now() - _HG.actStart) / 1000);
      }, 1000),
    };
  }
  function actStop() {
    if (!_HG.activity) return;
    clearInterval(_HG.activity.verb); clearInterval(_HG.activity.tick);
    _HG.activity = null;
    _hgActEl.style.display = 'none';
  }
  function actWord(word) {
    if (!_hgActEl || _hgActEl.style.display === 'none') return;
    const w = _hgActEl.querySelector('[data-hg-aw]');
    if (!w) return;
    if (word) { w.textContent = word; w.classList.add('hg-act-special'); }
    else { w.textContent = _ACT_WORDS[_actWordIdx]; w.classList.remove('hg-act-special'); }
  }
  const _HG_CTX_FALLBACK = 256000;
  function _hgCtxKey(sid) { return 'hg-ctx:' + sid; }
  function _hgCtxRestore(sid) {
    _HG.ctxParts = null;   // a154：分类估算随会话走，旧会话的 sys/mcp 估值不残留
    let v = null;
    if (sid) { try { v = JSON.parse(localStorage.getItem(_hgCtxKey(sid)) || 'null'); } catch(_) {} }
    const s = _HG.sessions.find(x => x.sid === sid);
    const mname = (s && s.model) || (_HG.models && _HG.models.default) || '';
    // v2.27.16：记忆窗口带模型归属校验（renderCtxRing 同款）——旧记录无
    // model 字段或与当前模型不符 → 丢弃窗口值，按模型名重推，防 [1M] 会话
    // 残留的 1M 分母跟着小窗口模型走（Lanz-Auto 虚报 /1000.0K）。
    const sameModel = v && mname &&
      (v.model || '').toLowerCase() === mname.toLowerCase();
    if (v && v.used > 0 && v.used <= (v.max || _HG_CTX_FALLBACK) && sameModel)
      _hgDrawCtxRing(v.used, v.max || _HG_CTX_FALLBACK);
    else _hgDrawCtxRing(0, /1m/i.test(mname) ? 1000000 : _HG_CTX_FALLBACK);
    // v2.20：记忆里的 max 可能是旧代码存的 256K 兜底值（1M 模型被压成
    // /256K、84% 虚报，用户实测）——恢复路径同样按模型名校正窗口并写回，
    // 别只靠每轮结束的 _hgCtxPoll 纠偏。
    if (/1m/i.test(mname) && ((v && v.max) || 0) < 1000000) {
      const used = (v && v.used > 0) ? v.used : 0;
      _hgDrawCtxRing(used, 1000000);
      try { localStorage.setItem(_hgCtxKey(sid), JSON.stringify({used, max: 1000000, model: mname})); } catch(_) {}
    }
  }
  function _hgDrawCtxRing(used, ctxMax, note) {
    const pct = Math.min(100, used / ctxMax * 100);
    // v2.6：viewBox 与 CSS 显示尺寸一致（24），r=10 + stroke 3 → 直径 23 < 24 不裁边；
    // 此前 r=9 贴 viewBox 边缘，缩放裁切导致"圆环爆掉"
    const VB = 24, R = 10, C = 2 * Math.PI * R;
    const col = pct >= 95 ? 'var(--neon-red, #e06c75)'
              : pct >= 80 ? 'var(--neon-orange, #d29922)' : 'var(--accent)';
    _hgCostEl.innerHTML =
      `<svg class="hg-ctx-ring" viewBox="0 0 ${VB} ${VB}">` +
      `<circle cx="${VB / 2}" cy="${VB / 2}" r="${R}" fill="none" stroke="var(--border)" stroke-width="3"/>` +
      `<circle cx="${VB / 2}" cy="${VB / 2}" r="${R}" fill="none" stroke="${col}" stroke-width="3"` +
      ` stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - pct / 100)}"` +
      ` stroke-linecap="round" transform="rotate(-90 ${VB / 2} ${VB / 2})"/></svg>` +
      `<span class="hg-ctx-pct">${Math.round(pct)}%</span>`;
    // a1375（用户拍板）：纯文本 title 废止——悬浮直接弹容量卡（下方 hover
    // 绑定），卡片内容是 title 的超集（TPS/子代理/估值明细都在卡内）；
    // 「已压缩待首轮」类状态由卡片头部「首轮回复后统计」分支承担
    _hgCostEl.classList.toggle('warn', pct >= 80);
    _HG.ctxRing = { used: used, max: ctxMax };
    _hgDynDirty();   // v2.32 面板：上下文行跟随（localStorage 即数据总线，零新轮询）
    // a1375：悬浮即显容量卡（用户拍板：替代点击弹出）。进出双向短延迟：
    // 快速扫过不闪卡（入 180ms）、滑向卡片途中不误关（出 260ms——卡片贴
    // 圆环上方，间隙极小）；innerHTML 重画只换子节点不杀父监听，绑一次即可
    if (!_hgCostEl._hgCtxCardBound) {
      _hgCostEl._hgCtxCardBound = true;
      _hgCostEl.addEventListener('mouseenter', function () {
        clearTimeout(_hgCtxHoverT);
        _hgCtxHoverT = setTimeout(_hgCtxCardOpen, 180);
      });
      _hgCostEl.addEventListener('mouseleave', function () {
        clearTimeout(_hgCtxHoverT);
        _hgCtxHoverT = setTimeout(_hgCtxCardClose, 260);
      });
    }
  }
  function renderCtxRing(o) {
    const u = o.usage || {};
    const used = (u.input_tokens || 0) + (u.cache_read_input_tokens || 0) +
                 (u.cache_creation_input_tokens || 0);
    if (typeof used !== 'number' || used <= 0) return;
    let ctxMax = _HG_CTX_FALLBACK;
    const mu = o.modelUsage || {};
    for (const k in mu) {
      // v2.20（3.png 假 100%）：取全部 entry 的最大窗口，不再见好就收——
      // 网关可能把子代理/识图等小窗口模型与主模型一起报上来，首个 entry
      // 若是小窗（如 256K），真实用量被小分母放大成假满环。
      if (mu[k] && typeof mu[k].contextWindow === 'number' && mu[k].contextWindow > ctxMax) {
        ctxMax = mu[k].contextWindow;
      }
    }
    // v2.20（3.png 假 100%）：used > ctxMax = 网关把全会话累计口径塞进了
    // 单轮 usage（实测 ~20 轮 × ~70K ≈ 1.4M，clamp 后恒显 100%）。单轮真实
    // 用量物理不可能超窗（超了 API 直接报错，不会有 success result）——
    // 必是坏数据：丢弃本轮，环保留上一轮合法值。
    if (used > ctxMax) return;
    // v2.20：本事件没带 modelUsage（assistant 事件就不带）→ 沿用该会话上次
    // 记到的窗口，避免没 result 校准时就退 256K 假分母
    // v2.27.16：记忆窗口带模型归属。切方案/切模型后旧 max 不可继承——
    // [1M] 会话残留的 1000000 分母让 Lanz-Auto 虚报 /1000.0K（用户实锤
    // 85.3K 显示 9%）。归属不符或旧记录无 model 字段 → 按当前模型名重推
    // （带 [1M]/[1m] → 1M，其余 256K 兜底），下次写入带上模型名自愈。
    if (ctxMax === _HG_CTX_FALLBACK && _HG.sid) {
      let rec = null;
      try { rec = JSON.parse(localStorage.getItem(_hgCtxKey(_HG.sid)) || 'null') || {}; } catch(_) { rec = {}; }
      const cur = (o.model || _HG.model || '').toLowerCase();
      if (rec.max && cur && (rec.model || '').toLowerCase() === cur) {
        ctxMax = rec.max;
      } else {
        ctxMax = /1m/.test(cur) ? 1000000 : _HG_CTX_FALLBACK;
      }
    }
    _hgDrawCtxRing(used, ctxMax);
    if (_HG.sid) { try { localStorage.setItem(_hgCtxKey(_HG.sid), JSON.stringify({used, max: ctxMax, model: o.model || _HG.model || ''})); } catch(_) {} }
  }
  function _hgCtxPoll() {
    if (!_HG.sid || _hgCtxInFlight) return;
    const sid = _HG.sid;
    _hgCtxInFlight = true;
    fetch('/api/harness/ctx?sid=' + encodeURIComponent(sid))
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok || j.sid !== _HG.sid) return;
        // a154：容量卡分类估算（系统提示词/MCP 工具，后端 /ctx 附带）——
        // 搭既有 5s 轮询车，零新增请求
        if (j.sysTok !== undefined || j.mcpTok !== undefined)
          _HG.ctxParts = { sys: j.sysTok || 0, mcp: j.mcpTok || 0 };
        // v2.20：中断轮次没有 result → 接口 window=0 → 前端曾退 256K 假分母
        // （1M 模型显示成 /256K，84% 虚高）。模型名带窗口线索（glm-5.3[1M]）
        // 时按名推断，兜住没有任何 result 校准过的会话。
        let win = j.window || 0;
        if (!win && /1m/i.test(j.model || (_HG.model || ''))) win = 1000000;
        // v2.21：压缩后尚未有新轮次 → jsonl 主链读数已归零，环也归零，
        // 不能继续画压缩前的旧值（用户实测 708K 残留）
        if (!(j.used > 0)) {
          if (j.compacted) _hgDrawCtxRing(0, win || _HG_CTX_FALLBACK, '上下文已压缩 · 首轮回复后统计');
          return;
        }
        // v4.1（用户实锤「上下文途中跳变」）：busy 期间轮询让位实时链——
        // tps 帧画「真值+生成中估值」（ctxLive+liveToks，随流增长），轮询
        // 此前每 5s 用纯 jsonl 真值（无估值）重画，两条链口径交替，读数规
        // 律性回落再涨（跳变观感）。busy 只做数据面更新不动画：分母校正
        // （含 settings 级 window）+ 真值锚单调刷新（jsonl usage 可能比
        // ctxLive 新）+ 记忆；空闲期照旧 renderCtxRing 画环落准。
        if (_HG.busy) {
          if (!_HG.ctxRing) _HG.ctxRing = { used: 0, max: win || _HG_CTX_FALLBACK };
          if (win && win !== _HG.ctxRing.max) _HG.ctxRing.max = win;
          if (j.used > (_HG.ctxRing.used || 0)) _HG.ctxRing.used = j.used;
          try { localStorage.setItem(_hgCtxKey(sid), JSON.stringify(
            { used: j.used, max: win || _HG.ctxRing.max,
              model: j.model || _HG.model || '' })); } catch (_) {}
          return;
        }
        renderCtxRing({ usage: { input_tokens: j.used },
                        modelUsage: win ? { _w: { contextWindow: win } } : null });
      }).catch(() => {})
      .finally(() => { _hgCtxInFlight = false; });
  }
  // ---- a154：上下文容量卡（仿 ZCode，用户需求）----------------------------
  // 数据零新增：用量=ctxRing+liveToks（a153 实时链）、缓存命中率=v4feed
  // tps.hit（result 帧三输入分量累计）、分类=系统提示词/MCP 工具后端估算
  // （/ctx sysTok/mcpTok）+ 消息=余量。我们是 CLI 的壳——CLI 内部的基础
  // 系统提示与内置工具 schema 拿不到，故分类标「估」不装精确（ZCode 自组
  // prompt 所以精确；额度区是其订阅限制，自托管网关无此概念，不仿）
  let _hgCtxCardEl = null, _hgCtxCardTimer = null, _hgCtxHoverT = 0;
  function _hgCtxCardFmt(n) {
    return n >= 1000000 ? (n / 1000000).toFixed(1) + 'M'
         : n >= 1000 ? (n / 1000).toFixed(1) + 'K' : String(Math.round(n));
  }
  function _hgCtxCardTpl() {
    const r = _HG.ctxRing || {}, t = _HG.tps || {};
    const est = (_HG.busy && t.liveToks) || 0;
    const used = Math.max(0, r.used || 0);
    const shown = used + est;              // 与环同口径：busy 时含生成中估值
    const max = r.max || _HG_CTX_FALLBACK;
    const pct = Math.min(100, shown / max * 100);
    const barCol = pct >= 95 ? 'var(--neon-red, #e06c75)'
                 : pct >= 80 ? 'var(--neon-orange, #d29922)' : 'var(--accent)';
    const parts = _HG.ctxParts || { sys: 0, mcp: 0 };
    const msg = Math.max(0, shown - parts.sys - parts.mcp);
    const row = (name, tok, est_) => {
      const p = shown > 0 ? (tok / shown * 100).toFixed(1) : '0.0';
      return `<div class="hg-ctx-row"><i class="hg-ctx-dot${est_ ? ' est' : ''}"></i>` +
        `<span class="hg-ctx-name">${name}</span>` +
        `<span class="hg-ctx-val">${_hgCtxCardFmt(tok)} · ${p}%${est_ ? '*' : ''}</span></div>`;
    };
    const tpsBits = [];
    if (t.last) tpsBits.push(`最近 ${t.last} tok/s`);
    if (t.all) tpsBits.push(`累计输出 ${_hgCtxCardFmt(t.all)}`);
    if (t.sub) tpsBits.push(`子代理 ${_hgCtxCardFmt(t.sub)}`);
    return `<div class="hg-ctx-head"><b>上下文容量</b><span>${(used > 0 || est > 0) ?
        `${_hgCtxCardFmt(shown)}/${_hgCtxCardFmt(max)}（${Math.round(pct)}%）` :
        '首轮回复后统计'}</span></div>` +
      `<div class="hg-ctx-bar"><i style="width:${pct}%;background:${barCol}"></i></div>` +
      `<div class="hg-ctx-rows">` +
        row('消息', msg, false) +
        row('系统提示词', parts.sys, true) +
        row('MCP 工具', parts.mcp, true) +
      `</div>` +
      `<div class="hg-ctx-line">缓存命中率 ${t.hit > 0 ? t.hit + '%' : '—'}` +
        `<span class="hg-ctx-dim">（本会话累计）</span></div>` +
      (tpsBits.length ? `<div class="hg-ctx-line">${tpsBits.join(' · ')}</div>` : '') +
      (est > 0 ? `<div class="hg-ctx-dim">含生成中 ~${_hgCtxCardFmt(est)}（估值，回合结束落准）</div>` : '') +
      `<div class="hg-ctx-foot">* 分类为估算：系统提示词/MCP 工具按注入内容量得，` +
      `消息 = 总量 − 前两项（CLI 内部构成不暴露）</div>`;
  }
  function _hgCtxCardPlace() {
    if (!_hgCtxCardEl) return;
    const rc = _hgCostEl.getBoundingClientRect();
    const st = _hgCtxCardEl.style;
    // 锚定：右缘对齐圆环、卡底在圆环上方（ZCode 同款上浮）；极窄窗右缘钳 8px。
    // a154R（对抗审）：1s tick 里也重锚——窗口 resize 后圆环挪位，卡片不再悬空
    st.right = Math.max(8, Math.round(window.innerWidth - rc.right)) + 'px';
    st.bottom = Math.round(window.innerHeight - rc.top + 10) + 'px';
  }
  function _hgCtxCardRender() {
    if (!_hgCtxCardEl) return;
    _hgCtxCardEl.innerHTML = _hgCtxCardTpl();
    _hgCtxCardPlace();
  }
  function _hgCtxCardAway(ev) {
    if (_hgCtxCardEl && !_hgCtxCardEl.contains(ev.target) &&
        !_hgCostEl.contains(ev.target)) _hgCtxCardClose();
  }
  function _hgCtxCardKey(ev) {
    if (ev.key === 'Escape') _hgCtxCardClose();
  }
  function _hgCtxCardClose() {
    clearTimeout(_hgCtxHoverT);
    if (_hgCtxCardTimer) { clearInterval(_hgCtxCardTimer); _hgCtxCardTimer = null; }
    document.removeEventListener('mousedown', _hgCtxCardAway);
    document.removeEventListener('keydown', _hgCtxCardKey);
    if (_hgCtxCardEl) { _hgCtxCardEl.remove(); _hgCtxCardEl = null; }
  }
  function _hgCtxCardOpen() {
    if (_hgCtxCardEl) return;
    const el = document.createElement('div');
    el.className = 'hg-ctx-card';
    el.innerHTML = _hgCtxCardTpl();
    document.body.appendChild(el);
    _hgCtxCardEl = el;
    _hgCtxCardPlace();
    // a1375：卡体也是 hover 域——从圆环滑入卡不关（取消关闭延迟），
    // 离开卡才收（点击别处/Escape 依旧可关，_hgCtxCardAway/_hgCtxCardKey）
    el.addEventListener('mouseenter', function () { clearTimeout(_hgCtxHoverT); });
    el.addEventListener('mouseleave', function () {
      clearTimeout(_hgCtxHoverT);
      _hgCtxHoverT = setTimeout(_hgCtxCardClose, 200);
    });
    _hgCtxCardTimer = setInterval(_hgCtxCardRender, 1000);  // 开着就活着（a153 实时链）
    document.addEventListener('mousedown', _hgCtxCardAway);
    document.addEventListener('keydown', _hgCtxCardKey);
  }
  function setBusy(b, sinceMs) {
    // v3.5.50：只读模式守卫——RO 期间主会话事件流已断（SSE close），主视图
    // 藏于 flowwrap，任何 busy 态变更（5s 自愈轮询等）都不动活动条/输入卡
    if (_HG.readonly) return;
    _HG.busy = b;
    _hgConn.tab.querySelector('.led').classList.toggle('on', b);
    _hgSendBtn.classList.toggle('stop', b);
    _hgSendBtn.title = b ? '停止生成' : '发送（Enter）';
    _hgSendBtn.setAttribute('aria-label', b ? '停止生成' : '发送');
    _hgStateEl.textContent = b ? '' : (_HG.alive ? '就绪' : '');
    _hgInputState();   // v2.35：输入框提示按运行态/子代理/协作等待派生（P0-1②③；空闲文案同 v2.20）
    _hgSpinShow(b);    // v3.1：消息流底 ZCode 式 spinner 行（正在执行…）
    if (b) actStart(sinceMs);
    else { actStop(); queuePump(); _hgCtxPoll();
      try { _hgQueueSync(); } catch (_) {}   // v3.4.77：回合终结对账队列（promoted/回插事件断档兜底）
      try { _hgPatchMissingCmds(); } catch(_) {} }   // v3.3.14：空闲即补缺令行（result 触发外的二道）

    _hgDynDirty();   // v2.32 面板：状态区运行态徽章/计时跟随
  }
