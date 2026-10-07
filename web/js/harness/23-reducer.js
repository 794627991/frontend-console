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
  function _hgProjEvent(it) {
    // SSE 信封入口（onmessage 每帧先过这里再走 legacy 分派）
    if (!_HG.proj) _HG.proj = _hgProjInit(it && it.sid);
    const p = _HG.proj;
    const t = it.type || it.kind;
    let dirty = false;
    if (t === 'turn_started') {
      p.status = 'running'; p.turnCount++; p.turnTools = _hgEmptyTools();
      dirty = true;
    } else if (t === 'turn_complete') {
      p.status = 'idle'; p.lastTurnTools = Object.assign({}, p.turnTools);
      dirty = true;
    } else if (t === 'turn_error') {
      p.status = 'idle'; p.lastErr = it.text || 'turn aborted';
      dirty = true;
    } else if (t === 'cli_stream') {
      const d = it.data || {};
      if (d.type === 'assistant' && !d.parent_tool_use_id) {
        const c = (d.message || {}).content;
        if (Array.isArray(c)) {
          for (const b of c)
            if (b && b.type === 'tool_use') {
              _hgTally(p.turnTools, String(b.name || ''));
              _hgTally(p.toolsTotal, String(b.name || ''));
              dirty = true;
            }
        }
      }
    } else if (t === 'subagent_started') {
      p.agents[it.tid] = { type: it.agent_type || 'Task', desc: it.desc || '',
                           bg: !!it.bg, taskId: it.task_id || '', done: false,
                           err: false, tokens: 0, toolN: 0 };
      dirty = true;
    } else if (t === 'subagent_result') {
      const a = p.agents[it.tid];
      if (a) Object.assign(a, { done: true, err: !it.ok,
                                tokens: it.tokens || a.tokens || 0,
                                toolN: it.tool_n || a.toolN || 0,
                                brief: String(it.brief || '').slice(0, 200) });
      dirty = true;
    } else if (t === 'input_admitted') {
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
          if (it.id) fetch('/api/harness/queue_act', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sid: _HG.sid, id: it.id, act: 'del' })
          }).catch(() => {});
          p.inbox = (p.inbox || []).filter(x => x.id !== it.id);
          try { showBanner('已拦截一条误复活的排队消息（此前编辑/删除未生效），如需发送请重新输入', 4000, true); } catch (_) {}
          renderSideStatus();
          return;
        }
      }
      const key = _hgQueueKey();
      const arr = _HG.queues[key] = _HG.queues[key] || [];
      if (it.id && !arr.some(x => x.id === it.id))
        arr.push({ id: it.id, text: it.text || '', images: [], files: [],
                   att: it.att || 0 });
      p.inbox = arr.map(x => ({ id: x.id, text: x.text || '' }));
      renderQueue();
      dirty = true;
    } else if (t === 'input_promoted' || t === 'input_discarded') {
      // promoted：后端已真发（user_echo 随后到达画气泡）；discarded：作废
      //（rewind 换代/用户删/发送失败）。两态都从队列摘除
      const key = _hgQueueKey();
      const arr = _HG.queues[key] || [];
      const i = arr.findIndex(x => x.id === it.id);
      if (i >= 0) { arr.splice(i, 1); renderQueue(); }
      p.inbox = p.inbox.filter(x => x.id !== it.id);
      if (t === 'input_discarded' && it.reason === 'rewind')
        showBanner('回退已作废 ' + (p.inbox.length + 1) + ' 条排队输入（旧世代）', 2600);
      dirty = true;
    }
    if (dirty) renderSideStatus();
  }
  function _hgProjSeed(j) {
    // /events 响应的 proj+queue 种子（切会话/轮询兜底路径）
    if (!j) return;
    if (j.proj) {
      const base = _hgProjInit(j.proj.sid);
      _HG.proj = Object.assign(base, j.proj);
      _HG.proj.turnTools = Object.assign(_hgEmptyTools(), j.proj.turn_tools || {});
      _HG.proj.toolsTotal = Object.assign(_hgEmptyTools(), j.proj.tools_total || {});
      renderSideStatus();
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
    const d = document.createElement('div');
    d.className = 'h-turnsum';
    d.innerHTML = '<span class="h-turnsum-pill">🔍 查阅 · ' + parts.map(esc).join(' · ') + '</span>';
    // v3.2.20（用户实锤回合末「莫名其妙的残留胶囊」）：不再挂消息流根
    // （悬在最终结论/回滚钮之后像残留）——挂回合体内顶部，展开过程即见，
    // 收起态根区干净
    const g = _HG.grp || [..._hgFlow.querySelectorAll('.h-grp')].pop();
    const hb = g && (g.headBody || (g.querySelector && g.querySelector('.h-turn-body')));
    if (hb) hb.insertBefore(d, hb.firstChild);
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
