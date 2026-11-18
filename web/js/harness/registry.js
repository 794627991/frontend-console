// harness registry.js (refactor/subagent-registry 阶段2：注册表统一消费层)
  // ==================== 子代理注册表消费层（agentId 主键）====================
  // 设计定调：后端 /api/harness/agents（冷查询投影）是子代理状态/名称/续派
  // 链的**唯一权威**（三套 id 的归一在后端一处完成）。本层职责：
  //   ① _hgRegToLocal：投影条目 → 前端档案形态（消费方零改动）
  //   ② _hgRegSync：拉投影重建 _HG.agents（键=agentId）+ _HG.tidMap/_HG.aidKey；
  //      live 期 SSE 按 tid 建档（即时显示），Sync 时经 tidMap 归并
  //   ③ _hgRegSyncSoon：事件驱动 debounce（SSE 子代理事件后 2s 收敛）
  // 单点解析纪律（防归一层屎山再生）：键桥接只许走 _hgAg/_subTid/tidMap
  // 三件套——禁止在任何消费点新增 dual-lookup（链扫描/三向反查）。
  // a125（用户实锤「我已重开，刚开什么都没干，胶囊还有 52h38m」）：
  // `interrupted` 是转写 mtime 启发式（a91），只能落定、不能翻案——但
  // **长思考有物理上界**。超过 30min 无任何事件时「不落盘」不可能还是长
  // 思考，按失联落定（阈值与 relay._PEER_STALE_MS / panel stale 一致）。
  // registry Sync 与 v4bridge._agentsColdSync 共用本判据（后者经 _g 取），
  // 否则两条链拉同一接口、谁后到谁赢：Sync 无闸会把 5 分钟长思考直接落
  // done（a91「后台在跑无条件同步」被破）。
  var _REG_STALE_MS = 30 * 60 * 1000;
  // sAt（可选）= 本轮续派发出的时刻。给了就带轮次栅栏：服务端时间早于它
  // = 看到的是**上一轮**的终态（续派新轮刚起、投影没追上），不得落定。
  // 三处写点（_hgRegToLocal 主路 / pending 分支 / v4bridge 冷同步）共用
  // 同一个实现，否则「谁后到谁赢」——Sync 无栅栏会把刚复活的链落定，
  // 而冷同步的栅栏因 `if (!a.done)` 永远没机会纠正。
  function _regInterruptedStale(e, sAt) {
    if (!e || String(e.status || '') !== 'interrupted') return false;
    // 必须取**服务端**时间：本地 a.t0 常是补建时刻（_agentFile 的
    // `|| Date.now()` 兜底、SendMessage 档 t0:Date.now()），年龄恒≈0
    var t = Number(e.lastActive || e.t0 || e.doneAt) || 0;
    if (t > 0 && t < 1e12) t = t * 1000;
    if (!t) return false;
    var _sat = Number(sAt) || 0;
    if (_sat && t < _sat) return false;      // 上一轮的终态
    return (Date.now() - t) > _REG_STALE_MS;
  }
  function _hgRegToLocal(e, sid, sAt) {
    // 注册表条目 → 前端档案形态。status 四态映射 done/err/interrupted；
    // taskId/agentId 统一=agentId（归一在后端已完成，前端不再反查）
    // a124：interrupted **只有过了 30min 失联闸**才算 done——原实现
    // `e.status !== 'running'` 无条件落 done，把长思考中的代理判成完成
    // （a91 用户铁律「后台还在运行无条件同步」被破）。
    // sAt 给了就一并带轮次栅栏（见 _regInterruptedStale 注释）。
    var _intr = e.status === 'interrupted';
    // a397：interrupted 落定需确定性死证（deadEvi——本代进程活的静默代理
    // 后端已不判死；老链路无字段时 !false 维持原 30min 失联闸行为）
    var _intrStale = _intr && e.deadEvi !== false && _regInterruptedStale(e, sAt);
    var _done = (e.status === 'running') ? false
      : (_intr ? _intrStale : true);
    return {
      type: e.type || 'Task',
      desc: e.desc || '',
      t0: e.t0 || 0,
      done: _done,
      deadEvi: !!e.deadEvi,
      err: e.status === 'err',
      // v4.0.5（复审实锤）：注册表条目必须能表达「用户主动停掉」这一
      // **确定性事实**（后端 _status_from_notify 已单列 stopped）。原先只认
      // interrupted，导致每次 2s Sync / F5 后 a.stopped 被整体替换丢失，
      // 「已停止」被抹成「完成」。
      stopped: e.status === 'stopped',
      interrupted: _intr,
      doneAt: _done ? (e.doneAt || 0) : 0,
      bg: !!e.bg, rounds: e.rounds || 1,
      taskId: e.agentId || '', agentId: e.agentId || '',
      tids: (e.tids && e.tids.slice) ? e.tids.slice() : [],
      tokens: e.tokens || 0, toolN: e.toolN || 0,
      result: e.brief || '', found: e.found !== false,
      sid: sid || _HG.sid, reg: true };
  }
  function _hgAg(key) {
    // 冷查询批2：单点档案解析器——key（tid/agentId/档案键任一形态）→ 档案。
    // 顺序：直配 → aidKey 反查 → tidMap 归链。全库键桥接只许走本函数/
    // _subTid/tidMap 三件套（25-registry 头部纪律），旧三向反查/链扫描退役
    const k = String(key || '');
    if (!k) return null;
    const ag = _HG.agents || {};
    if (ag[k]) return ag[k];
    const ak = (_HG.aidKey || {})[k];
    if (ak && ag[ak]) return ag[ak];
    const aid = (_HG.tidMap || {})[k];
    if (aid && ag[aid]) return ag[aid];
    return null;
  }
  let _regSyncSeq = 0;
  // a122：轮次栅栏判定（纯函数，便于行为级回归）。
  // 返回 true = 投影的终态属于**上一轮**，不得落定、要翻回运行中。
  // 三道保险：
  //   ① 只认确定性终态（done/err/stopped）。interrupted 是转写 mtime
  //      启发式（a91），拿它当栅栏会把「续派后静默死亡」的链每轮翻回。
  //   ② 本地已有终态事实时不翻回——否则 v4.0.6「本地 stopped 不得被 Sync
  //      抹掉」被推翻，回合收尾 _hgAgentsSweep 落的 done 也会在下次 2s
  //      Sync 消失。判据含「时间证据缺失」：doneAt 为 0 的老档案（有损
  //      重建/histcache）没有任何时间凭证说明它是上一轮的，一律按「不得
  //      被翻回」处理（保守方向）。续派复活会显式写 done=false+sendAt，
  //      不会走到这道保险，因此不会卡住本该落定的链。
  //   ③ 必须有 sendAt（没续派过就无栅栏可言）。
  function _regFence(st, eAt, sAt, lv) {
    const s = String(st || '');
    if (!sAt) return false;
    if (!(s === 'done' || s === 'err' || s === 'stopped')) return false;
    if (!eAt || eAt >= sAt) return false;
    if (lv && lv.done) {
      const _d = Number(lv.doneAt) || 0;
      if (!_d || _d >= sAt) return false;
    }
    return true;
  }
  function _regCid(k, a) {
    let key = String(k || '');
    if (key.indexOf('pending:') === 0) key = key.slice(8);
    const tm = (_HG.tidMap || {})[key];
    return String((a && (a.taskId || a.agentId)) || tm || key || '');
  }
  // a122（四修）：按任意键形态（agentId / tid / pending:<tid> / 包装 tid）
  // 在 live 表里定位档案。live 期档案是 **tid 键**建的，而投影键是
  // agentId——只 `live[k]` 会在首个 Sync 之前恒 undefined，让 v4.0.6
  // （本地 stopped 不得被抹）与保险② 同时失效。解析顺序：
  //   直配 → tidMap 归链（tid→aid 得 aid 键，aid→?) → aidKey 反查（aid→首次 tid）
  // → 反向扫 cid（包装 tid / 无映射的稀疏档）。
  // a122（五修）：同链多档择一。原实现「第一条命中即返回」，而 aidKey 记的
  // 是**首次** tid（sse.js:100 `if (!aidKey[_real])` 只写一次）、反向扫取
  // 插入序最早 → 系统性偏向最旧残留档。实测：call_1{done:true,doneAt:0} +
  // call_2{done:false,sendAt:S}，aidKey={A:'call_1'} → 返回 call_1，保险②
  // 反过来把本轮真在跑的链判成已结束（缺陷的反向回归）。
  // 判据与本文件幽灵档清理 / panel._hgRunChains 统一：
  //   at = max(doneAt, t0, **sendAt**)，平局 done 优先。
  function _regPick(prev, cand) {
    if (!cand) return prev;
    const at = Math.max(cand.doneAt || 0, cand.t0 || 0, cand.sendAt || 0);
    if (!prev) return { a: cand, at: at };
    if (at > prev.at || (at === prev.at && cand.done && !prev.a.done)) {
      return { a: cand, at: at };
    }
    return prev;
  }
  function _regLiveOf(k, live) {
    if (!live) return null;
    let key = String(k || '');
    if (key.indexOf('pending:') === 0) key = key.slice(8);
    const tm = (_HG.tidMap || {});
    const aid = tm[key];
    const ak = (_HG.aidKey || {})[key];
    // **必须全量收集后择一**：只按 aidKey 命中就提前 return 会漏掉同链的
    // 新活档（aidKey 只记首次 tid），正是本次要修的反向回归。
    let best = null;
    best = _regPick(best, live[key]);
    if (aid) best = _regPick(best, live[aid]);
    if (ak) best = _regPick(best, live[ak]);
    for (const lk in live) {
      const a = live[lk];
      if (a && _regCid(lk, a) === key) best = _regPick(best, a);
    }
    return best ? best.a : null;
  }
  async function _hgRegSync(sid, opts) {
    if (!sid) return;
    const seq = ++_regSyncSeq;
    try {
      const r = await fetch('/api/harness/agents?sid=' + encodeURIComponent(sid));
      const j = await r.json();
      if (!j || !j.ok || _HG.sid !== sid || seq !== _regSyncSeq) return;
      _HG.tidMap = j.tidMap || {};
      // 冷查询批1（I2）：aidKey 反查索引随 Sync 重建——Sync 后档案键=
      // agentId（自指），live 期键=首见 tid（tidMap/aidKey 写点在 10-sse）
      const ak = {};
      for (const t in _HG.tidMap) {
        const aid2 = _HG.tidMap[t];
        if (aid2 && !ak[aid2]) ak[aid2] = t;
      }
      for (const k in (j.agents || {})) {
        if (k.indexOf('pending:') !== 0 && !ak[k]) ak[k] = k;
      }
      _HG.aidKey = ak;
      // 双轨归并：live 期 SSE 按 tid 建的档案经 tidMap 映射到 agentId 键；
      // 投影条目为权威（status/desc/rounds），live 档案的富字段（model——
      // 后端条目无此字段，live/agent_models 是唯一来源）保留。live 独有
      //（冷查询尚未收录的瞬时）原样保留——下一轮 Sync 收编。
      // 冷查询批4：_liveA 整机制缩为纯 model 累积（字段补全非归一层）
      const live = _HG.agents || {};
      const modelBy = {};
      for (const k in live) {
        const a = live[k];
        if (!a || !a.model) continue;
        const aid = (_HG.tidMap[k] || a.taskId || a.agentId || k) || '';
        if (aid && !modelBy[aid]) modelBy[aid] = a.model;
      }
      // a122（复审）：按 agentId 回填续派的轮次栅栏时间戳。判据
      // （panel._hgRunChains / 下方清理块）用 max(doneAt,t0,sendAt)，
      // 而 _hgRegToLocal 从投影重建时不带 sendAt——一次 Sync 就会把刚
      // 复活的链的栅栏抹掉，随后立刻被上一轮的 done 判成已结束。
      const sendBy = {};
      for (const k in live) {
        const a = live[k];
        if (!a || !a.sendAt) continue;
        const aid = _regCid(k, a);
        if (aid && !(sendBy[aid] > a.sendAt)) sendBy[aid] = a.sendAt;
      }
      // 投影键 → sendAt 的同一套归一：pending:<tid> 剥前缀再经 tidMap，
      // 裸 tid 经 tidMap，agentId 自指。key 归一不一致 = 栅栏对那一类条目
      // 永不生效（实锤：pending 条目直接落键、sendAt 丢失）。
      // 注意：不能依赖 loc（它就是 _hgRegToLocal 的产物），直接用投影条目
      // 的 agentId/归一键算。
      // a124 复审残留：稀疏 pending 条目无 agentId（后端未回填），`_regCid`
      // 退回裸 tid 而 sendBy 是按 live 档 agentId 存的 → 键对不上、栅栏静默
      // 失效（实测 done=true，期望 false）。补反向查：用 live 档的 cid 反扫。
      const _sendAtFor = (k, e) => {
        const byAid = String((e && e.agentId) || '') || _regCid(k, null);
        if (sendBy[byAid]) return sendBy[byAid];
        const lv = _regLiveOf(k, live);          // live 表（Sync 前的本地档）
        const cid = lv ? _regCid('', lv) : '';
        return (cid && sendBy[cid]) || 0;
      };
      const agents = {};
      const jAg = j.agents || {};
      for (const k in jAg) {
        if (k.indexOf('pending:') === 0) {
          // 后端未回填 agentId 的临时条目（CLI 异常形态）——保留 tid 键
          // 兼容 live 流，found=false 不回放。
          // F2 修复（全审）：tid 已被 tidMap 归链且 aid 条目在场时**跳过
          // 落键**——稀疏档（无 taskId/tids/rounds）覆写 live 富档会丢
          // 字段+鬼影双计
          const _pk = k.slice(8);
          const _pAid = (_HG.tidMap || {})[_pk];
          if (_pAid && jAg[_pAid]) continue;
          // a122（三修）：pending 条目同样要带 sendAt 与栅栏——本项目按
          // `_pk` 落键，sendBy 也按归一后的 cid 存，键必须一致
          const _pSAt = _sendAtFor(k, jAg[k]);
          const _pMiss = _regFence(jAg[k].status,
                                   Number(jAg[k].doneAt || 0) || 0,
                                   _pSAt, _regLiveOf(k, live));
          // a124 复审（严重）：pending 分支原写 `jAg[k].status !== 'running'`
          // 无条件落 done —— 绕过了 interrupted 的 30min 失联闸，a91 长思考
          // 误伤在 Sync 链的**第三个写点**复发（_regFence 不认 interrupted，
          // 兜不回来）。改走与主路同一判据。
          const _pIntr = jAg[k].status === 'interrupted';
          const _pDone0 = (jAg[k].status === 'running') ? false
            : (_pIntr ? _regInterruptedStale(jAg[k], _pSAt) : true);
          agents[_pk] = Object.assign(
            { type: jAg[k].type, desc: jAg[k].desc, t0: jAg[k].t0,
              done: _pMiss ? false : _pDone0,
              err: _pMiss ? false : (jAg[k].status === 'err'),
              stopped: _pMiss ? false : (jAg[k].status === 'stopped'),
              interrupted: _pMiss ? false : _pIntr,
              sendAt: _pSAt || 0,
              doneAt: (_pMiss || !_pDone0) ? 0 : jAg[k].doneAt,
              bg: !!jAg[k].bg, sid: sid, reg: true },
            { found: false });
          continue;
        }
        // a124：sendAt 提前算好并传给 _hgRegToLocal——interrupted 的 30min
        // 失联闸必须带轮次栅栏，否则 Sync 侧会把刚续派的链落定（而冷同步
        // 侧因 `if (!a.done)` 跳过，栅栏永无机会纠正＝「谁后到谁赢」）。
        const _sAt0 = _sendAtFor(k, jAg[k]);
        const loc = _hgRegToLocal(jAg[k], sid, _sAt0);
        if (modelBy[k]) loc.model = modelBy[k];
        // v4.0.6（复审实锤）：本地已有的「已停止」事实不得被 Sync 抹掉
        // ——通知未 flush 时后端条目仍报 running，整条替换会把
        // stopped 清成 false，目录/行卡重回「运行中」或「完成」。
        // 单向：本地 true 恒保留；后端 stopped 由 _hgRegToLocal 自己带。
        // a122（四修）：**多键解析**。live 期档案以 tid 为键（v4bridge/sse
        // 建档），投影键是 agentId——只有「上一次 Sync 已重建成 agentId 键」
        // 后才对齐。首个 Sync 前只用 live[k] 恒 undefined，本地 stopped 与
        // 保险② 双双失效（实测：用户主动停止的档被翻回运行中）。
        const _lv = _regLiveOf(k, live);
        if (_lv && _lv.stopped && !loc.stopped) {
          loc.stopped = true;
          loc.done = true;
          loc.err = false;
        }
        // a122（复审·三修）：轮次栅栏——投影报终态但时刻早于本轮续派发出
        // 时刻 = 拿到的是**上一轮**的终态（投影滞后一轮），不得落定。
        //
        // 三道保险（缺任一条都会制造比原缺陷更糟的回归）：
        // ① 只对**确定性**终态生效。interrupted 是转写 mtime 启发式（a91），
        //    拿它作栅栏依据会把「续派后静默死亡」的链每轮翻回运行中。
        // ② 本地已有更晚的终态事实（done 且 doneAt >= sendAt）时不得翻回
        //    —— 否则 v4.0.6「本地 stopped 不得被 Sync 抹掉」被整条推翻，
        //    且回合收尾 _hgAgentsSweep 落的 done 会在下一次 2s Sync 消失。
        // ③ sendAt 取值必须与 sendBy 写入用**同一套键归一**：投影键可能是
        //    agentId / pending:<tid> / 裸 tid，只查 sendBy[k] 会让 pending
        //    条目永不命中（实测），等于栅栏对它们不存在。
        const _sAt = _sAt0;
        if (_sAt) {
          loc.sendAt = _sAt;
          const _fence = _regFence(jAg[k].status,
                                   Number(jAg[k].doneAt || 0) || 0,
                                   _sAt, _lv);
          if (_fence) {
            loc.done = false;
            loc.doneAt = 0;
            loc.err = false;
            loc.stopped = false;
            loc.interrupted = false;
          }
        }
        agents[k] = loc;
      }
      // live 独有条目（注册表快照未含——瞬时在途）：保留原键原样
      for (const k in live) {
        if (agents[k]) continue;
        const a = live[k];
        const aid = (_HG.tidMap[k] || (a && (a.taskId || a.agentId)) || '');
        if (a && aid && agents[aid]) continue;   // 已归并进 agentId 键
        agents[k] = a;
      }
      // a122（用户实锤「子代理明明结束了，胶囊还显示」）：同链幽灵档清理。
      // 实体：live 期残留档（键=tool_use_id、done:false、doneAt:0）与权威档
      // （键=agentId、done:true）共链，两者都在 agents 里 → 胶囊/目录把已结束
      // 的链当运行中。判据与 _hgRunChains 同源：一链内「最近事件时刻」
      // max(doneAt, t0, **sendAt**) 最大的那条是真实状态；它已 done 就删掉
      // 同链其余未完成档。sendAt 必须计入——续派就地复活原档不改 t0，只写
      // sendAt；漏了它会把刚复活的链当上一轮残留删掉。平局 done 优先。
      (function () {
        const bestBy = {};
        for (const k in agents) {
          const a = agents[k];
          if (!a) continue;
          const cid = a.taskId || a.agentId || k;
          const at = Math.max(a.doneAt || 0, a.t0 || 0, a.sendAt || 0);
          const cur = bestBy[cid];
          if (!cur || at > cur.at
              || (at === cur.at && !!a.done && !cur.done)) {
            bestBy[cid] = { k: k, at: at, done: !!a.done };
          }
        }
        for (const k in agents) {
          const a = agents[k];
          if (!a || a.done) continue;
          const b = bestBy[a.taskId || a.agentId || k];
          if (b && b.done && b.k !== k) delete agents[k];
        }
      })();
      _HG.agents = agents;
      // 视图联动：行卡回绑（agentline 秒表复活/运行徽章覆写假完成）——
      // 注册表 running 条目按 taskId 找行
      for (const aid in agents) {
        const a = agents[aid];
        if (a.done || !a.taskId) continue;
        const row = (_HG.rowById || {})[aid] || _hgAgentRowFindByDesc(a);
        if (row && row.classList.contains('agentline')) {
          row.dataset.tid = aid;
          _HG.rowById[aid] = row;
          if (!row.dataset.hgSubr) row.dataset.hgSubr = a.taskId;
          try { _hgAgentRowBindAid(aid, row); } catch (_) {}
          // a88：只传档案 t0，fresh now 兜底撤（行上 memo 在 restart 侧
          // 兜底，秒表不被同步链重置）
          _hgAgentRowTimerRestart(row, a.t0);
        }
      }
      if (!(opts && opts.quiet)) renderSideStatus();
    } catch (_) {}
  }
  let _regSyncTimer = null;
  function _hgRegSyncSoon(sid) {
    // 事件驱动 debounce：SSE 子代理事件（task_started/notification/派发/
    // 续派）后 2s 收敛一次——live 档案（tid 键）即时可用保流畅，注册表
    //（agentId 键）随 Sync 收编保一致
    if (_HG.sid !== sid) return;
    if (_regSyncTimer) clearTimeout(_regSyncTimer);
    _regSyncTimer = setTimeout(() => {
      _regSyncTimer = null;
      if (_HG.sid === sid) _hgRegSync(sid);
    }, 2000);
  }

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._hgAg = _hgAg;
window._hgRegSync = _hgRegSync;
window._hgRegSyncSoon = _hgRegSyncSoon;
