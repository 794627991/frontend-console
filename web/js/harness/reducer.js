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
      _hgEntryPush(p, { t: 'turn_interrupted', text: it.text,
                         hist: !!it.hist }, fx);
      fx.push({ op: 'render_side' });
    },
    turn_exit(p, it, fx) {
      _hgEntryPush(p, { t: 'turn_exit', text: it.text, hist: !!it.hist }, fx);
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
    ask(p, it, fx) {
      // R5：交互提问（ZCode PermissionRequested 对位——瞬态 dock，hist 只
      // 计数不重建面板，快照恢复走 03-ask-md 服务端拉取路径）
      p.ask = { req_id: it.req_id || '', title: it.title || '',
                questions: it.questions || [] };
      fx.push({ op: 'ask_render', it: it });
    },
    ask_done(p, it, fx) {
      p.ask = null;
      fx.push({ op: 'ask_done', it: it });
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
      // v4.0.4：被停≠失败——err 只在「非 ok 且非 stopped」时置位，
      // 否则目录/行卡会把用户主动停止画成红叉。
      if (a) Object.assign(a, { done: true,
                                stopped: !!it.stopped,
                                err: !it.ok && !it.stopped,
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

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._hgProjInit = _hgProjInit;
window._hgQueueSeed = _hgQueueSeed;
window._hgReduce = _hgReduce;
window._hgSpinShow = _hgSpinShow;
window._hgToolBadges = _hgToolBadges;
