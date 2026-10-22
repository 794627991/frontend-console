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
  function _hgRegToLocal(e, sid) {
    // 注册表条目 → 前端档案形态。status 四态映射 done/err/interrupted；
    // taskId/agentId 统一=agentId（归一在后端已完成，前端不再反查）
    return {
      type: e.type || 'Task',
      desc: e.desc || '',
      t0: e.t0 || 0,
      done: e.status !== 'running',
      err: e.status === 'err',
      interrupted: e.status === 'interrupted',
      doneAt: e.doneAt || 0,
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
          agents[_pk] = Object.assign(
            { type: jAg[k].type, desc: jAg[k].desc, t0: jAg[k].t0,
              done: jAg[k].status !== 'running',
              err: jAg[k].status === 'err',
              interrupted: jAg[k].status === 'interrupted',
              doneAt: jAg[k].doneAt, bg: !!jAg[k].bg, sid: sid, reg: true },
            { found: false });
          continue;
        }
        const loc = _hgRegToLocal(jAg[k], sid);
        if (modelBy[k]) loc.model = modelBy[k];
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
