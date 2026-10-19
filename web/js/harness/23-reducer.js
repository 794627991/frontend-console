// harness reducer.js (v3.1 新增：前端事件投影——live/重放共用，对照 ZCode event-reducer)
  // ==================== v3.1 前端投影（进程面板/回合摘要的单一状态源）====================
  // 纪律与后端 src/eventlog/reducer.py 同款：_HG.proj 只由事件信封归约得到，
  // SSE live 流与 /events proj 种子走同一入口；本文件不碰 DOM 状态机（面板
  // 渲染仍归 13-panel 的 rAF 合并器，这里只管状态+触发 renderSideStatus）。
  function _hgEmptyTools() {
    return { calls: 0, reads: 0, searches: 0, edits: 0, bash: 0, agents: 0 };
  }
  const _HG_T_READ = new Set(['Read', 'NotebookEdit']);
  const _HG_T_SEARCH = new Set(['Grep', 'Glob', 'WebSearch', 'WebFetch', 'TodoRead']);
  const _HG_T_EDIT = new Set(['Edit', 'MultiEdit', 'Write', 'NotebookEdit']);
  function _hgTally(bucket, name) {
    bucket.calls++;
    if (_HG_T_READ.has(name)) bucket.reads++;
    if (_HG_T_SEARCH.has(name)) bucket.searches++;
    if (_HG_T_EDIT.has(name)) bucket.edits++;
    if (name === 'Bash') bucket.bash++;
    if (name === 'Task' || name === 'Agent') bucket.agents++;
  }
  function _hgProjInit(sid) {
    return { sid: sid || _HG.sid || '', status: 'idle', turnCount: 0,
             agents: {}, inbox: [], turnTools: _hgEmptyTools(),
             toolsTotal: _hgEmptyTools(), lastTurnTools: null, lastErr: null };
  }
  function _hgReduce(p, it, fx) {
    // R1（ZCode 对齐）：if-else 链改 handlers map（对位 event-reducer.ts
    // 的 this.handlers[event.type] 分派）。环境适配两处（注释存档）：
    // · ZCode immutable spread（{...p} 每 handler）——我们大状态 mutate
    //   +dirty 标记（WebView2 性能优先，语义仍「视图只从投影派生」）
    // · ZCode reducer 零副作用——我们副作用走 fx 出参描述（_hgRunFx 执行）
    const t = it.type || it.kind || it.t;
    const h = _HG_REDUCERS[t];
    if (h) {
      h(p, it, fx);
    } else if (t === 'cli_stream') {
      const d = it.data || {};
      if (d.type === 'assistant' && !d.parent_tool_use_id) {
        const c = (d.message || {}).content;
        if (Array.isArray(c)) {
          for (const b of c)
            if (b && b.type === 'tool_use') {
              _hgTally(p.turnTools, String(b.name || ''));
              _hgTally(p.toolsTotal, String(b.name || ''));
              fx.push({ op: 'render_side' });
            }
        }
      }
    }
  }
  const _HG_REDUCERS = {
    turn_started(p, it, fx) {
      // ZCode TurnStarted 同款：新一轮接受即清旧错（旧错误不再是当前任务
      // 事实，反反复复恢复旧横幅）
      p.status = 'running'; p.turnCount++; p.turnTools = _hgEmptyTools();
      p.lastErr = null;
      fx.push({ op: 'render_side' });
    },
    turn_complete(p, it, fx) {
      p.status = 'idle'; p.lastTurnTools = Object.assign({}, p.turnTools);
      fx.push({ op: 'render_side' });
    },
    turn_error(p, it, fx) {
      p.status = 'idle'; p.lastErr = it.text || 'turn aborted';
      fx.push({ op: 'render_side' });
    },
    turn_interrupted(p, it, fx) {
      p.status = 'idle';
      _hgEntryPush(p, { t: 'turn_interrupted', text: it.text }, fx);
      fx.push({ op: 'render_side' });
    },
    turn_exit(p, it, fx) {
      _hgEntryPush(p, { t: 'turn_exit', text: it.text }, fx);
    },
    model_switched(p, it, fx) {
      _hgEntryPush(p, { t: 'model_switched', text: it.text || '' }, fx);
    },
    renew(p, it, fx) {
      _hgEntryPush(p, { t: 'renew', text: it.text }, fx);
    },
    audit(p, it, fx) {
      _hgEntryPush(p, { t: 'audit', text: it.text }, fx);
    },
    raw(p, it, fx) {
      _hgEntryPush(p, { t: 'raw', text: it.text }, fx);
    },
    sysnote(p, it, fx) {
      _hgEntryPush(p, { t: 'sysnote', kind: it.kind || '', text: it.text }, fx);
    },
    assistant_text(p, it, fx) {
      _hgEntryPush(p, { t: 'assistant_text', text: it.text || '',
                         model: it.model || '', live: !!it.live }, fx);
    },
    assistant_thinking(p, it, fx) {
      _hgEntryPush(p, { t: 'assistant_thinking', text: it.text || '',
                         hi: it.hi, ts: it.ts || 0, prevTs: it.prevTs || 0,
                         live: !!it.live }, fx);
    },
    user_message(p, it, fx) {
      // R2b：user 气泡（组管线边界由 renderUser 内部承担——v2.24.1 定调）
      _hgEntryPush(p, { t: 'user_message', text: it.text || '',
                         images: it.images || [], files: it.files || [],
                         ts: it.ts || 0, live: !!it.live }, fx);
    },
    peer_return(p, it, fx) {
      // R4：跨会话回传（识图结论/协作回传）——渲染订阅 case 消费；ZCode 无
      // 转交对位（识图转交为本产品特有形态——环境适配存档）
      _hgEntryPush(p, { t: 'peer_return', name: it.name || '', text: it.text || '',
                         to: it.to, tid: it.tid,
                         hist: !!it.hist, live: !!it.live }, fx);
    },
    subagent_started(p, it, fx) {
      p.agents[it.tid] = { type: it.agent_type || 'Task', desc: it.desc || '',
                           bg: !!it.bg, taskId: it.task_id || '',
                           t0: it.ts || 0, done: false,
                           err: false, tokens: 0, toolN: 0 };
      // subagent-registry F6（全审）：镜像事件附 aid——即收即更 tidMap
      //（_subTid 归一零延迟；25-registry 单点纪律域）
      if (it.aid && it.tid) { _HG.tidMap = _HG.tidMap || {}; _HG.tidMap[it.tid] = it.aid; }
      fx.push({ op: 'render_side' });
    },
    subagent_result(p, it, fx) {
      if (it.aid && it.tid) { _HG.tidMap = _HG.tidMap || {}; _HG.tidMap[it.tid] = it.aid; }
      const a = p.agents[it.tid];
      if (a) Object.assign(a, { done: true, err: !it.ok,
                                tokens: it.tokens || a.tokens || 0,
                                toolN: it.tool_n || a.toolN || 0,
                                brief: String(it.brief || '').slice(0, 200) });
      fx.push({ op: 'render_side' });
    },
    input_admitted(p, it, fx) {
      // 服务端账本入队（本窗乐观 push 过同 id 则跳过——POST 响应与 SSE 事件
      // 双路到达是常态，id 客户端预生成保证两路同号）
      // v3.4.78（指纹追杀·按 sid 分域）：本地已摘除（edit/del）但作废未达的
      // 条目——admit 事件此刻才到（迟到回号），命中指纹即补发 del，不入 UI
      // （命中给 banner 可见——用户 30s 内有意重发同文被拦时能看到原因）
      const _qk = (_HG.qKill || {})[_HG.sid];
      if (_qk && _qk.length) {
        const fp = String(it.text || '').slice(0, 200)
          .replace(/\s+/g, ' ').trim().slice(0, 80);
        const now = Date.now();
        const live = _qk.filter(k => now - k.at < 30000);
        _HG.qKill[_HG.sid] = live;
        const hit = fp ? live.findIndex(k => k.fp === fp) : -1;
        if (hit >= 0) {
          live.splice(hit, 1);
          // v3.5.109：补杀失败必须可见（O2），否则用户以为拦住了、消息
          // 实际还会复活发出——经 fx 描述（api_queue_del）
          if (it.id) fx.push({ op: 'api_queue_del', id: it.id });
          p.inbox = (p.inbox || []).filter(x => x.id !== it.id);
          fx.push({ op: 'banner',
                    text: '已拦截一条误复活的排队消息（此前编辑/删除未生效），如需发送请重新输入',
                    ms: 4000, warn: true });
          fx.push({ op: 'render_side' });
          return;
        }
      }
      const key = _hgQueueKey();
      const arr = _HG.queues[key] = _HG.queues[key] || [];
      if (it.id && !arr.some(x => x.id === it.id))
        arr.push({ id: it.id, text: it.text || '', images: [], files: [],
                   att: it.att || 0 });
      p.inbox = arr.map(x => ({ id: x.id, text: x.text || '' }));
      fx.push({ op: 'render_queue' });
      fx.push({ op: 'render_side' });
    },
    input_promoted(p, it, fx) { _hgQueueRemove(p, it, fx, false); },
    input_discarded(p, it, fx) { _hgQueueRemove(p, it, fx, true); },
  };
  function _hgQueueRemove(p, it, fx, discarded) {
    // promoted：后端已真发（user_echo 随后到达画气泡）；discarded：作废
    //（rewind 换代/用户删/发送失败）。两态都从队列摘除
    const key = _hgQueueKey();
    const arr = _HG.queues[key] || [];
    const i = arr.findIndex(x => x.id === it.id);
    if (i >= 0) { arr.splice(i, 1); fx.push({ op: 'render_queue' }); }
    p.inbox = p.inbox.filter(x => x.id !== it.id);
    if (discarded && it.reason === 'rewind')
      fx.push({ op: 'banner',
                text: '回退已作废 ' + (p.inbox.length + 1) + ' 条排队输入（旧世代）',
                ms: 2600 });
    fx.push({ op: 'render_side' });
  }
  function _hgEntryPush(p, entry, fx) {
    // R1：entries=行级读模型（ZCode entries 对位）——杂项行起步，气泡/
    // 工具行随 R2/R3 进。渲染由 _HG_STORE 订阅消费（renderEntries）
    p.entries = p.entries || [];
    entry.i = p.entries.length;
    p.entries.push(entry);
    fx.push({ op: 'render_entries' });
  }
  function _hgProjEvent(it) {
    // SSE 信封入口（onmessage 每帧先过这里再走 legacy 分派）——R0 起为
    // _hgReduce（纯）+ fx 执行的兼容壳；_hgDispatch（27-store）是统一
    // 管线的正式入口（FEV 直达 _hgReduce 同一函数）
    if (!_HG.proj) _HG.proj = _hgProjInit(it && it.sid);
    const fx = [];
    _hgReduce(_HG.proj, it, fx);
    for (let i = 0; i < fx.length; i++) _hgRunFx(fx[i]);
  }
  function _hgProjSeed(j) {
    // /events 响应的 proj+queue 种子（切会话/轮询兜底路径）
    if (!j) return;
    if (j.proj) {
      const base = _hgProjInit(j.proj.sid);
      _HG.proj = Object.assign(base, j.proj);
      _HG.proj.turnTools = Object.assign(_hgEmptyTools(), j.proj.turn_tools || {});
      _HG.proj.toolsTotal = Object.assign(_hgEmptyTools(), j.proj.tools_total || {});
      _hgProjAgentsSeed(j.proj);
      renderSideStatus();
    }
  }
  // v3.5.317：服务端真源接线——proj.agents 里仍在跑（done:false）的子代理
  // 补种进 _HG.liveAgentsBy[sid] 桶。此前刷新（F5）/关 tab 后内存桶全灭，
  // _hgLiveAgentsRestore 空转 no-op，运行中子代理被 hist 工厂盖「completed」
  // 假完成徽章、subagent_tail 轮询也因无档案停喂——后端投影（事件流归约
  // 的服务端真相）一直随 /events 下发却零消费。补种后既有 restore 全链
  // （行回绑/秒表复活/目录/胶囊）自动工作。桶内已有更富的前端档案时不覆盖
  // （只有 done 翻转由既有通知路径负责）。
  function _hgProjAgentsSeed(proj) {
    const sid = proj && proj.sid;
    const pa = proj && proj.agents;
    if (!sid || !pa) return;
    let seeded = 0;
    _HG.liveAgentsBy = _HG.liveAgentsBy || {};
    const tgt = _HG.liveAgentsBy[sid] = _HG.liveAgentsBy[sid] || {};
    for (const tid in pa) {
      const a = pa[tid];
      // v3.5.322（复审#3）：live 档案已在场即跳过——/events 在途响应的 proj
      // 快照可能早于刚到达的完成信号（task_notification/SSE ack 重放建档），
      // 贫快照种入并经 restore 覆写会把刚 done 的代理复活成假运行
      if (!a || a.done || tgt[tid]
          || ((_HG.agents || {})[tid])) continue;
      tgt[tid] = {
        type: a.type || 'Task', desc: a.desc || '',
        t0: a.t0 || 0, done: false, doneAt: 0,
        bg: !!a.bg, taskId: a.task_id || a.taskId || '',
        err: false, sid: sid, projSeed: true };
      seeded++;
    }
    if (seeded) {
      // 当前就是本会话 → 立即回填（restore 内部自建 _HG.agents 并行回绑/
      // 秒表复活；F5 冷开路 hist 工厂已先跑完盖了假完成徽章，此处是覆写
      // 运行态的唯一时机。行卡 miss 无害——档案先进目录/胶囊，行回绑幂等）
      if (_HG.sid === sid) _hgLiveAgentsRestore(sid);
    }
  }
  async function _hgQueueSeed(sid) {
    // 切会话：拉服务端账本初始化本地队列（durable 队列的真源在后端，
    // 本地数组只是渲染缓存——事件驱动保持同步）
    if (!sid) { renderQueue(); return; }
    try {
      const j = await (await fetch('/api/harness/queue?sid=' + encodeURIComponent(sid))).json();
      if (!j || !j.ok || _HG.sid !== sid) return;
      const key = _hgQueueKey();
      _HG.queues[key] = (j.queue || []).map(e =>
        ({ id: e.id, text: e.text || '', images: e.images || [], files: e.files || [] }));
      renderQueue();
    } catch(_) {}
  }

  // ==================== v3.1 ZCode 式回合摘要行（「查阅 · N 搜索 · N 文件」）====================
  function _hgTurnSumRow() {
    // result 到达时插入：本回合工具构成摘要（数据源=投影 turnTools，live
    // 事件归约；回放路径无事件流不补——历史行没有，新回合有，逐步稠密）
    const tt = (_HG.proj && _HG.proj.turnTools) || null;
    if (!tt || !tt.calls) return;
    const parts = [];
    if (tt.searches) parts.push(tt.searches + ' 搜索');
    if (tt.reads) parts.push(tt.reads + ' 文件');
    if (tt.edits) parts.push(tt.edits + ' 编辑');
    if (tt.bash) parts.push(tt.bash + ' 命令');
    if (tt.agents) parts.push(tt.agents + ' 子代理');
    if (!parts.length) return;
    // v3.5.203b（用户实锤「查阅·1编辑·8命令 重复 3 次」）：幂等——result
    // 帧在 SSE snapshot 重放/切回回放重建时会被再次处理（10-sse:645/899
    // 两处调用），原无条件 insertBefore 每次叠一条。组内已有摘要行则原位
    // 更新文本，绝不重插
    const g = _HG.grp || [..._hgFlow.querySelectorAll('.h-grp')].pop();
    const hb = g && (g.headBody || (g.querySelector && g.querySelector('.h-turn-body')));
    if (!hb) return;
    const txt = '🔍 查阅 · ' + parts.map(esc).join(' · ');
    const old = hb.querySelector(':scope > .h-turnsum .h-turnsum-pill');
    if (old) { old.textContent = txt; return; }
    const d = document.createElement('div');
    d.className = 'h-turnsum';
    d.innerHTML = '<span class="h-turnsum-pill">' + txt + '</span>';
    // v3.2.20（用户实锤回合末「莫名其妙的残留胶囊」）：不再挂消息流根
    // （悬在最终结论/回滚钮之后像残留）——挂回合体内顶部，展开过程即见，
    // 收起态根区干净
    hb.insertBefore(d, hb.firstChild);
  }

  // ==================== v3.1 流底 spinner（ZCode 式运行指示行）====================
  function _hgSpinShow(b) {
    let el = _hgFlow.querySelector(':scope > .hg-spin-row');
    if (b) {
      if (!el) {
        el = document.createElement('div');
        el.className = 'hg-spin-row';
        el.innerHTML = '<span class="hg-spin"></span><span>正在执行…</span>';
        _hgFlow.appendChild(el);
      }
      _hgScrollBottom();
    } else if (el) el.remove();
  }

  // ==================== v3.1 工具行徽标（文件类型块 + diff 增删计数）====================
  function _hgFileExt(p) {
    const m = String(p || '').match(/\.([a-zA-Z0-9_]+)$/);
    return m ? m[1].slice(0, 4).toLowerCase() : '';
  }
  const _HG_EXT_CLS = { js: 'ext-js', ts: 'ext-ts', jsx: 'ext-js', tsx: 'ext-ts',
    py: 'ext-py', md: 'ext-md', json: 'ext-json', css: 'ext-css', html: 'ext-html',
    yml: 'ext-yml', yaml: 'ext-yml', c: 'ext-c', h: 'ext-c', cpp: 'ext-c',
    sh: 'ext-sh', bat: 'ext-sh', go: 'ext-go', rs: 'ext-rs', java: 'ext-java' };
  function _hgPlusMinus(a, b) {
    // 前后缀等值裁剪后的行数差（O(n) 逼近，行级 LCS 留给抽屉全文 diff）
    const ol = String(a || '').split('\n'), nl = String(b || '').split('\n');
    let i = 0;
    while (i < ol.length && i < nl.length && ol[i] === nl[i]) i++;
    let j = 0;
    while (j < ol.length - i && j < nl.length - i
           && ol[ol.length - 1 - j] === nl[nl.length - 1 - j]) j++;
    return { add: nl.length - i - j, del: ol.length - i - j };
  }
  function _hgDiffStat(name, input) {
    if (!input) return null;
    if (name === 'Edit' && typeof input.old_string === 'string'
        && typeof input.new_string === 'string')
      return _hgPlusMinus(input.old_string, input.new_string);
    if (name === 'MultiEdit' && Array.isArray(input.edits)) {
      let add = 0;
      let rmv = 0;
      for (const e of input.edits) {
        if (!e) continue;
        const r = _hgPlusMinus(e.old_string, e.new_string);
        add += r.add;
        rmv += r.del;
      }
      return { add, del: rmv };
    }
    if (name === 'Write' && typeof input.content === 'string')
      return { add: input.content.split('\n').length, del: 0 };
    return null;
  }
  function _hgToolBadges(name, input) {
    // ZCode 式行内徽标：文件类型色块（Edit/Write/Read 族）+ `+N -N` 增删
    const out = [];
    const fp = input && String(input.file_path || input.path || input.notebook_path || '');
    if (fp) {
      const ext = _hgFileExt(fp);
      out.push('<span class="hg-file-badge ' + (_HG_EXT_CLS[ext] || '') + '" title="'
        + esc(fp) + '">' + esc(ext || 'TXT') + '</span>');
    }
    const ds = _hgDiffStat(name, input);
    if (ds && (ds.add || ds.del))
      out.push('<span class="hg-diffstat"><i class="add">+' + ds.add
        + '</i> <i class="del">-' + ds.del + '</i></span>');
    return out.join('');
  }
