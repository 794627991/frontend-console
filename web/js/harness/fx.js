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
  // 记忆落账唯一出口。侧栏胶囊（panel.js）与容量卡详情直接读 hg-ctx，只重画
  // 圆环不落账会出现「圆环 0% / 侧栏旧值」同屏矛盾，且坏值刷新即复活
  function _hgCtxSave(sid, used, max, badMax, model) {
    if (!sid) return;
    const rec = {used: used, max: max};
    // 无权威阈值时沿用记忆里已有的 badMax，绝不降级成 undefined——
    // 降级会让下次恢复的 authBadKnown 变 false，退回「用猜测值判坏」
    let bm = badMax;
    if (!(bm > 0)) {
      try {
        const old = JSON.parse(localStorage.getItem(_hgCtxKey(sid)) || 'null');
        if (old && old.badMax > 0) bm = old.badMax;
      } catch(_) {}
    }
    if (bm > 0) rec.badMax = bm;
    // model 同理：传空时保留旧归属，否则归属信息被抹掉、下次判不出切过模型
    let md = model;
    if (!md) {
      try {
        const old = JSON.parse(localStorage.getItem(_hgCtxKey(sid)) || 'null');
        if (old && old.model) md = old.model;
      } catch(_) {}
    }
    rec.model = md || '';
    try { localStorage.setItem(_hgCtxKey(sid), JSON.stringify(rec)); } catch(_) {}
  }
  // 本会话的后端权威窗口（未收到过 = 0，交由实报/记忆/名字兜底）
  function _hgCtxWinGet() {
    const m = _HG.ctxWinBy;
    return (m && _HG.sid && m[_HG.sid]) || 0;
  }
  function _hgCtxRestore(sid) {
    _HG.ctxParts = null;   // a154：分类估算随会话走，旧会话的 sys/mcp 估值不残留
    let v = null;
    if (sid) { try { v = JSON.parse(localStorage.getItem(_hgCtxKey(sid)) || 'null'); } catch(_) {} }
    const s = _HG.sessions.find(x => x.sid === sid);
    const mname = (s && s.model) || (_HG.models && _HG.models.default) || '';
    // v2.27.16：记忆窗口带模型归属校验（renderCtxRing 同款）——旧记录无
    // model 字段或与当前模型不符 → 丢弃窗口值，按模型名重推，防 [1M] 会话
    // 残留的 1M 分母跟着小窗口模型走（Lanz-Auto 虚报 /1000.0K）。
    // a429：只有「双方都有名字且不相等」才算不符。mname 为空是常态
    // （settings.json 没配模型映射 + 会话 meta.model 为 null，纯默认 CLI
    // 环境即如此），此时归属**未知**，不能当不符——否则合法读数被判坏
    // 清 0 并落账，真值被持久化销毁（旧码只画 0 不落账，反而没丢数据）
    const mismatch = !!(v && mname && v.model &&
      (v.model || '').toLowerCase() !== mname.toLowerCase());
    // 有本会话的后端权威窗口（含 settings）就用它，别按模型名猜——切过
    // API 后名字里的 [1m] 残留会把 500K 会话画成 1M 分母。窗口按 sid 存，
    // 绝不复用别的会话的值
    const authWin = (sid && _HG.ctxWinBy && _HG.ctxWinBy[sid]) || 0;
    const authBad = (sid && _HG.ctxBadMaxBy && _HG.ctxBadMaxBy[sid]) || 0;
    const bootWin = authWin > 0 ? authWin
      : (/1m/i.test(mname) ? 1000000 : _HG_CTX_FALLBACK);
    // 恢复判据同样按 badMax（模型真实能力），不能用显示分母——否则
    // (settings, 实报] 的合法用量切回会话时会被整段画 0，出现「先清零再涨」。
    // 无任何权威 badMax（冷启动、a423 之前的老记忆）时不用旧显示分母判坏：
    // 两个方向都会错（误清合法值 / 放行坏值）。改为只设物理上界 2×1M
    // （已知模型最大窗 1M），超过必是「全会话累计口径」坏值，直接判 0；
    // 边界内先按记忆原样显示，精确判坏交给必到的 5s /ctx
    const authBadKnown = authBad > 0 || (v && v.badMax);
    const effBad = authBad > 0 ? authBad : ((v && v.badMax) || 0);
    const _CTX_PHYS_MAX = 2097152;
    const restoreBad = authBadKnown ? effBad
      : ((v && v.used > _CTX_PHYS_MAX) ? 0 : Infinity);
    // 记忆可用 = 值在阈值内 + 模型未变（归属未知按可用，见上）
    const canUse = !!(v && v.used > 0 && v.used <= restoreBad && !mismatch);
    const showUsed = canUse ? v.used : 0;
    const showMax = canUse ? (v.max || bootWin) : bootWin;
    _hgDrawCtxRing(showUsed, showMax);
    // 画 0 同样必须落账：只重画不回写，记忆里留着旧 used → 侧栏胶囊/详情
    // 继续显示旧百分比（同屏矛盾），且 5s /ctx 的清环判据 cur 已被置 0
    // → 永不触发，矛盾冻结到下一轮真实 usage
    if (v && v.used > 0 && !canUse) _hgCtxSave(sid, 0, bootWin, effBad, mname);
    // v2.20：记忆里的 max 可能是旧代码存的 256K 兜底值（1M 模型被压成
    // /256K、84% 虚报，用户实测）——恢复路径同样按权威窗口校正并写回。
    // 归属不符（切过模型）不写回：否则会把该会话原本正确的记忆也污染。
    // used 必须复用上面的判据：信任已判坏的旧值会「先画 0 再满环」并
    // 把坏值重新持久化
    if (authWin > 0 && !mismatch && ((v && v.max) || 0) !== authWin) {
      _hgDrawCtxRing(showUsed, authWin);
      // model 只在有名字时写，否则保留记忆里的旧归属，避免把归属
      // 信息抹成空串、下次再也判不出「切过模型」
      _hgCtxSave(sid, showUsed, authWin, effBad, mname || (v && v.model) || '');
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
    // 分母判定链（用户实锤：切过 API 后旧 result 事件里仍留着
    // glm-5.3-flash[1m]，按名字推 1M，而 settings 实际 500K → 环在
    // 1M/500K 之间跳）。**用户 settings 优先**——CLI 就按它压缩，显示必须
    // 对齐，否则 50% 的环已经是压缩线了：
    //   1. /ctx 的 window（后端 _session_ctx_window：settings → 网关实报
    //      → 名字，本会话专属，按 sid 缓存）
    //   2. 网关实报 modelUsage[].contextWindow（取最大）
    //   3. 本会话上次记录（模型归属一致才沿用）
    //   4. 模型名 [1m] → 1M，兜底 256K
    const sidWin = _hgCtxWinGet();
    let ctxMax = 0, realWin = 0;
    const mu = o.modelUsage || {};
    for (const k in mu) {
      // 网关可能把子代理/识图等小窗模型与主模型一起报上来，取最大
      if (mu[k] && typeof mu[k].contextWindow === 'number'
          && mu[k].contextWindow > realWin) realWin = mu[k].contextWindow;
    }
    if (sidWin > 0) {
      ctxMax = sidWin;
    } else if (realWin > 0) {
      ctxMax = realWin;
    } else if (_HG.sid) {
      let rec = null;
      try { rec = JSON.parse(localStorage.getItem(_hgCtxKey(_HG.sid)) || 'null') || {}; } catch(_) { rec = {}; }
      const cur = (o.model || _HG.model || '').toLowerCase();
      if (rec.max && cur && (rec.model || '').toLowerCase() === cur) {
        ctxMax = rec.max;
      } else {
        ctxMax = /1m/.test(cur) ? 1000000 : _HG_CTX_FALLBACK;
      }
    } else {
      ctxMax = _HG_CTX_FALLBACK;
    }
    // v2.20（3.png 假 100%）：used 远超窗 = 网关把全会话累计口径塞进了
    // 单轮 usage（实测 ~20 轮 × ~70K ≈ 1.4M，clamp 后恒显 100%）。单轮真实
    // 用量物理不可能超窗（超了 API 直接报错，不会有 success result）。
    // 判据阈值必须用「模型真实能力」（o.badMax，缺省回落到 ctxMax）而不是
    // 显示分母：settings 配 500K 而模型实为 1M 时，500K~1M 的合法用量
    // 若按 500K 判会被整帧丢弃 → 环冻结在旧读数
    const guardMax = (typeof o.badMax === 'number' && o.badMax > 0)
      ? o.badMax : ctxMax;
    if (used > guardMax) return;
    _hgDrawCtxRing(used, ctxMax);
    // 只把真权威 o.badMax 落进记忆：guardMax 在缺 o.badMax 时回落到显示
    // 分母（可能是兜底 256K 或按名字猜的 1M），写进去会被下次恢复当权威
    // 阈值判坏，绕回 a426/a427 修掉的问题。缺失时传 0 → _hgCtxSave 沿用
    // 记忆里的旧 badMax，没有就不写该键
    _hgCtxSave(_HG.sid, used, ctxMax,
               (typeof o.badMax === 'number' && o.badMax > 0 ? o.badMax : 0),
               o.model || _HG.model || '');
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
        // 供 renderCtxRing 复用：settings 显式窗口 > 模型名推断（用户实锤：
        // 切过 API 后模型名残留 [1m]，但实际只有 500K）。按 sid 存——
        // 窗口是会话属性，全局单值会把 A 会话的 1M 带给 B 会话
        if (j.window > 0 && sid) {
          (_HG.ctxWinBy || (_HG.ctxWinBy = {}))[sid] = j.window;
        }
        // 坏数据阈值同样按会话存（v4bridge 的 ctxLive 判坏要用）
        if (j.badMax > 0 && sid) {
          (_HG.ctxBadMaxBy || (_HG.ctxBadMaxBy = {}))[sid] = j.badMax;
        }
        // 分母优先本会话已校准的权威窗口：空响应（如超窗续命 session_id
        // 暂缺）时 win=0，会按全局模型名猜 1M 或退 256K，把 settings 校准
        // 过的分母重置掉
        const cw = _hgCtxWinGet() || win || _HG_CTX_FALLBACK;
        // v2.21：压缩后尚未有新轮次 → jsonl 主链读数已归零，环也归零，
        // 不能继续画压缩前的旧值（用户实测 708K 残留）
        if (!(j.used > 0)) {
          if (j.compacted) {
            _hgDrawCtxRing(0, cw, '上下文已压缩 · 首轮回复后统计');
            // 落账：否则侧栏胶囊/详情仍按记忆显示压缩前的百分比
            _hgCtxSave(sid, 0, cw, j.badMax, j.model || _HG.model || '');
          } else {
            // 清环阈值只认后端权威 j.badMax：win 可能是「!win 且模型名含
            // 1m」按**全局** _HG.model 猜出来的，不当判据
            // 环值取「当前环」与「记忆」的较大者：恢复阶段判坏会先把
            // ctxRing.used 置 0，只比环值永远不成立 → 记忆旧值永不清理
            let memUsed = 0;
            try {
              const rec = JSON.parse(localStorage.getItem(_hgCtxKey(sid)) || 'null');
              if (rec && rec.used > 0) memUsed = rec.used;
            } catch(_) {}
            const cur = Math.max((_HG.ctxRing && _HG.ctxRing.used) || 0, memUsed);
            if (j.badMax > 0 && cur > j.badMax) {
              _hgDrawCtxRing(0, cw);
              _hgCtxSave(sid, 0, cw, j.badMax, j.model || _HG.model || '');
            }
          }
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
          // 坏数据判据用 badMax（模型真实能力），与显示分母解耦——否则
          // settings 500K + 合法 600K 会被写成 120% 并落进记忆。
          // 判断链路仍需要兜底值，但落账只传真权威 j.badMax（0 = 沿用记忆）
          const bad = (j.badMax > 0) ? j.badMax : (win || _HG_CTX_FALLBACK);
          if (j.used <= bad && j.used > (_HG.ctxRing.used || 0)) {
            _HG.ctxRing.used = j.used;
          }
          _hgCtxSave(sid, _HG.ctxRing.used, win || _HG.ctxRing.max,
                     j.badMax > 0 ? j.badMax : 0, j.model || _HG.model || '');
          return;
        }
        renderCtxRing({ usage: { input_tokens: j.used },
                        badMax: j.badMax,
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
    // a264（用户定调）：窗口选择器移除——窗口只走自动链（网关实报→
    // settings.json→[1M]→兜底），不提供用户选项
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
