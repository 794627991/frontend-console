// harness registry.js (refactor/subagent-registry 阶段2：注册表统一消费层)
  // ==================== 子代理注册表消费层（agentId 主键）====================
  // 设计定调：后端 /api/harness/agents 是子代理状态/名称/续派链的**唯一权威**
  // （三套 id 的归一在后端 registry.py 一处完成）。本层职责：
  //   ① _hgRegToLocal：注册表条目 → 前端档案形态（消费方零改动）
  //   ② _hgRegSync：拉注册表重建 _HG.agents（键=agentId）+ _HG.tidMap；
  //      live 期 SSE 仍按 tid 建档（阶段3 迁移），Sync 时经 tidMap 归并
  //   ③ _hgRegSyncSoon：事件驱动 debounce（SSE 子代理事件后 2s 收敛）
  // 历次实锤（续派两个子代理/假完成/名字不对/不跟随）的归一层补丁
  // （_subTid 三向反查/peerSent/subTidRes/链式判定）随阶段3 退役。
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
  let _regSyncSeq = 0;
  async function _hgRegSync(sid, opts) {
    if (!sid) return;
    const seq = ++_regSyncSeq;
    try {
      const r = await fetch('/api/harness/agents?sid=' + encodeURIComponent(sid));
      const j = await r.json();
      if (!j || !j.ok || _HG.sid !== sid || seq !== _regSyncSeq) return;
      _HG.tidMap = j.tidMap || {};
      // 双轨归并：live 期 SSE 按 tid 建的档案（键=tool_use id）经 tidMap
      // 映射到 agentId 键；注册表条目为权威（status/desc/rounds），live
      // 档案的富字段（model）保留。live 独有（注册表尚未收录的瞬时）原样
      // 保留——下一轮 Sync 收编
      const live = _HG.agents || {};
      const byAid = {};
      for (const k in live) {
        const a = live[k];
        const aid = (_HG.tidMap[k] || (a && (a.taskId || a.agentId)) || '');
        if (a && aid && /^[0-9a-zA-Z_-]{8,64}$/.test(aid)) {
          const cur = byAid[aid] = byAid[aid] || {};
          // 富字段合入（model 等注册表没有的）
          if (a.model && !cur.model) cur.model = a.model;
          if (!cur._liveA || !cur._liveA.t0 || (a.t0 && a.t0 < cur._liveA.t0))
            cur._liveA = a;
        }
      }
      const agents = {};
      const jAg = j.agents || {};
      for (const k in jAg) {
        if (k.indexOf('pending:') === 0) {
          // 后端未回填 agentId 的临时条目（CLI 异常形态）——保留 tid 键
          // 兼容 live 流，found=false 不回放
          agents[k.slice(8)] = Object.assign(
            { type: jAg[k].type, desc: jAg[k].desc, t0: jAg[k].t0,
              done: jAg[k].status !== 'running',
              err: jAg[k].status === 'err',
              interrupted: jAg[k].status === 'interrupted',
              doneAt: jAg[k].doneAt, bg: !!jAg[k].bg, sid: sid, reg: true },
            { found: false });
          continue;
        }
        const loc = _hgRegToLocal(jAg[k], sid);
        const rich = byAid[k];
        if (rich) {
          if (rich.model) loc.model = rich.model;
          if (rich._liveA && rich._liveA.model) loc.model = loc.model || rich._liveA.model;
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
          _hgAgentRowTimerRestart(row, a.t0 || Date.now());
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
