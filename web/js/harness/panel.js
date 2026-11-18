// harness panel.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function _hgDyn() {
    return _HG.dyn || (_HG.dyn = { acts: [], turns: [], turnN: 0, turnTools: 0,
      todoSeen: {}, todoRowId: null, agentsRpl: [] });
  }
  function renderSideStatus() {          // 事件驱动刷新入口（旧名保留：事件流调用点零改动）
    // v3.3 分屏化：dynEl=动态页伪 tab 的 sc，懒建（_subDynOpen）前恒 null——
    // 守卫只做 rAF 去重，回调内对 dynEl 判空。_hgDynRender 可跳，但目录重绘/
    // 输入框占位/胶囊刷新必须照跑：动态页全程不开时它们是唯一活着的刷新面
    //（旧写法 !dynEl 早退会把占位文案冻结、胶囊事件级刷新退化成 1s tick）。
    if (_dynRaf) return;
    _dynRaf = requestAnimationFrame(() => {
      _dynRaf = 0;
      if (dynEl) _hgDynRender();
      // v3.2R1(P2)：目录重绘并入同一 rAF——原先每个事件同步全量重建目录
      // innerHTML，事件密集时 mousedown/mouseup 之间行按钮被替换、点击落空；
      // 异常记 console（不静默吞）
      try { _subDirPaint(); } catch (e) { console.error('[hg-sub-dir] 目录刷新异常', e); }
      try { _hgInputState(); } catch(_) {}       // v2.35：派生态变化连带输入框提示（v3.3 自 _hgDynRender 尾部上移：无条件执行）
      try { _hgDynCapsulePaint(); } catch(_) {}  // v3.2.31：胶囊与视图同源刷新（同上）
    });
  }
  function _hgDynDirty() { renderSideStatus(); }   // 别名（setBusy/_hgDrawCtxRing 调；function 声明无 TDZ）
  // ==================== v3.3：会话动态胶囊（分屏化）====================
  // 胶囊=分屏唯一开关（常驻 harness wrap 内，跨 tab 天然隐藏）：运行态色点 +
  // 状态词 + 计时 + 运行中子代理数/最新动作摘要 + 上下文%。点击行为四分支
  // （绑定在 20-main）：子代理运行中直达其实况 tab / 空闲开分屏激活「动态」
  // 伪 tab（__dyn__，14-subpane _subDynOpen 懒建）/ 动态页激活时再点收分屏 /
  // 分屏开着在他 tab 时点切回动态页。旧右侧面板换装形态（hg-mode/hg-dyn-min/
  // hg-dyn-caps 偏好）已整体废止。
  // 子代理运行中且分屏未开时胶囊加 .attn 高亮脉冲（bug5③ 绝不静默后台兜底
  // 之一）；.open（accent 染边）按「分屏开且动态页激活」派生。
  function _hgCapsuleEl() {
    return _hgWrap ? _hgWrap.querySelector('[data-hg-dyncaps]') : null;
  }
  function _hgDynCapsulePaint() {
    const c = _hgCapsuleEl();
    if (!c || !c.isConnected) return;
    const agRun = _hgAgentsRunning();
    const peerWait = !agRun && _hgPeerPending();
    const run = !!_HG.busy || agRun || peerWait;
    c.classList.toggle('run', run && !peerWait);
    c.classList.toggle('wait', peerWait && !_HG.busy);
    // 状态词+计时（与面板 A 区同口径派生）
    let stTxt;
    // a52：压缩归属门控（同 :516——只显示本会话的压缩）
    if (_HG.compacting && _HG.compactSid === _HG.sid) stTxt = '压缩中';
    else if (_HG.busy && agRun) stTxt = '子代理执行中';
    else if (_HG.busy) stTxt = '回复中';
    else if (agRun) stTxt = '子代理后台执行中';
    else if (peerWait) stTxt = '等待协作回传';
    else if (!_HG.sid) stTxt = '新会话';
    else if (_HG.alive) stTxt = '就绪';
    else stTxt = '待命';
    const stEl = c.querySelector('[data-hg-caps-st]');
    if (stEl) stEl.textContent = stTxt;
    const durEl = c.querySelector('[data-hg-caps-dur]');
    if (durEl) {
      let dur = '';
      if (_HG.busy) {
        // a92S（用户实锤「时间对不上」）：胶囊计时与回合组头**同源**——
        // g.t0=回合真实起点（组头「工作中 16m34s」就是它算的）。此前用
        // _HG.actStart：hold 续挂等路径的 setBusy(true) 不带 sinceMs 会把
        // 它重置成 now（胶囊 28s vs 组头 16m34s 实锤）；无组时才回落 actStart
        const _gt0 = (_HG.grp && _HG.grp.t0) || 0;
        const _t00 = _gt0 || _HG.actStart;
        if (_t00) dur = _hgFmtDur(Math.max(1, Math.round((Date.now() - _t00) / 1000)));
      } else if (agRun) {
        const t0 = Math.min(...Object.values(_HG.agents || {}).filter(a => !a.done).map(a => a.t0 || Date.now()));
        dur = _hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
      } else if (peerWait) {
        // v3.2.31R（复审3）：与 _hgPeerPending 同口径——unknown/stale 线不计
        // 入计时（否则面板已排除的残留线把胶囊等待秒表虚高）
        const t0 = Math.min(..._hgPeerLines().filter(el => !el.dataset.done
            && el.dataset.unknown !== '1' && el.dataset.stale !== '1')
          .map(el => +(el.dataset.t0 || 0) || Date.now()));
        dur = _hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
      }
      durEl.textContent = dur;
    }
    // 子代理：运行数 + 最新动作摘要（多代理并发时每 4s 轮换一条=滚动展示；
    // 描述缺失回退类型名；悬浮 title 列全量）
    const agEl = c.querySelector('[data-hg-caps-ag]');
    if (agEl) {
      if (agRun) {
        // a92S：运行链去重（_hgRunChains）——I3「一链一档」靠归链成立，但
        // 重启/冷同步键空间差异会产生派发键+续派键双档案（4 代理计 ✦8 实锤），
        // 计数与轮换摘要一律走链去重后的清单
        const list = _hgRunChains().sort((x, y) => (x.t0 || 0) - (y.t0 || 0));
        const last = list[Math.floor(Date.now() / 4000) % list.length] || {};
        const act = String(last.desc || '').replace(/\s+/g, ' ').trim().slice(0, 30)
          || (_AGENT_LABEL[last.type] || last.type || '');
        agEl.textContent = '✦' + list.length + (act ? ' ' + act : '');   // v3.4.68：机器人 emoji 全工程禁绝（用户定调），统一中性星符（02-base Task 图标同款）
        // a92S：限宽溢出自动往返滚动（挂在既有 1s 重绘节拍上，不加新
        // interval）——胶囊 max-width 裁不住的长描述 crawls 展示全量，
        // 悬浮 title 仍列全量清单
        requestAnimationFrame(() => {
          try {
            const max = agEl.scrollWidth - agEl.clientWidth;
            if (max > 2) {
              agEl.classList.add('scroll');
              const ph = Math.floor((Date.now() / 40) % (max * 2));
              agEl.scrollLeft = ph <= max ? ph : max * 2 - ph;
            } else {
              agEl.classList.remove('scroll');
              agEl.scrollLeft = 0;
            }
          } catch (_) {}
        });
        agEl.title = list.map(a =>
          '· ' + (_AGENT_LABEL[a.type] || a.type || '子代理') +
          (a.desc ? '：' + String(a.desc).replace(/\s+/g, ' ').trim().slice(0, 60) : ''))
          .join('\n') + '\n点击打开实况分屏';
      } else agEl.textContent = '';
    }
    // 上下文%（hg-ctx localStorage 是数据总线——_hgDrawCtxRing 触发 renderSideStatus）
    const cxEl = c.querySelector('[data-hg-caps-ctx]');
    if (cxEl) {
      let ctxTxt = '', ctxWarn = false;
      if (_HG.sid) {
        try {
          const v = JSON.parse(localStorage.getItem('hg-ctx:' + _HG.sid) || 'null');
          // busy 期改用 _HG.ctxRing 同源：实时链每拍写 ctxLive 真值，但只画
          // 环不落账（localStorage 最多落后一个轮询周期），只读记忆会与
          // 圆环/容量卡「环 18% / 胶囊 10%」不一致
          // 非 busy 走记忆时，分母必须可溯源（同 _hgCtxRestore 的 denomAuth）：
          // 旧版本存的按名字猜的 256K 没有 badMax，画出来就是错的百分比，
          // 而圆环此时是空窗——两处不能一个不画一个硬画
          const live = _HG.busy ? (_HG.ctxRing || null) : null;
          const memOk = live || _hgCtxDenomOk(v);
          const base = live ? live.used : (memOk ? (v && v.used) : 0);
          const mx = live ? live.max : (memOk ? (v && v.max) : 0);
          // 分母未知（max=0，applyModel 刚作废旧分母）时不出百分比：
          // 回落 256K 会把 settings 500K 会话的 400K 显示成 100% 红条，
          // 与圆环「等 /ctx」口径保持一致
          if (base > 0 && mx > 0) {
            // v4.1（用户定调）：胶囊只按真值 base 算，不叠生成中估值——
            // 口径与圆环/容量卡统一（估值要下一轮才成为 input）
            // a452（审计 P1）：显示用 floor、判色用 round，与 fx.js 圆环
            // 完全同档。原来先 round 再拿它判色，79.6% 会出现「胶囊橙 80%、
            // 圆环蓝 80%」同屏矛盾；display floor 也避免 99.5% 看起来满格。
            const _p = Math.min(100, base / mx * 100);
            ctxTxt = Math.floor(_p) + '%';
            ctxWarn = Math.round(_p) >= 80;
          }
        } catch(_) {}
      }
      cxEl.textContent = ctxTxt;
      // warn 必须无条件重算：清环写回 used=0 后若只在 if 内 toggle，
      // 空白文字会留着上一拍的橙/红警示配色
      cxEl.classList.toggle('warn', ctxWarn);
    }
    // bug5③ 兜底脉冲：子代理运行中且窗格未开（用户可能没注意到分屏已收）。
    // v3.2.31R（复审5）：判定收紧为 ==='flex'（_subShow 的唯一打开态）——
    // 旧 !=='none' 对未初始化窗格（style.display===''）误判为开，脉冲不亮
    let paneOpen = false;
    try { paneOpen = !!_subPaneEl && _subPaneEl.style.display === 'flex'; } catch(_) {}
    // v3.3 展开态视觉改派生（旧 _hgDynCapsApply 直控已废）：分屏开着且激活的
    // 是动态页=胶囊 accent 染边（提示「再点收起」）；他 tab 激活时不染
    c.classList.toggle('open', paneOpen && _sub.active === _SUB_DYN);
    c.classList.toggle('attn', agRun && !paneOpen);
  }
  const _ROLE_AGENTS = new Set(['executor', 'coder', 'dev', 'reviewer', 'designer']);
  function _isCollabWrap(type, bg) {
    return !!bg && !_ROLE_AGENTS.has(String(type || ''));
  }
  function _hgAgentsRunning() {          // 运行中子代理（Task 已起、未收到完成信号）
    return _hgRunChains().length > 0;
  }
  // a92S（用户实锤「胶囊又显示 8 个」）：运行链去重——同一代理的派发键与
  // 续派键（SendMessage 包装 tid）是两份档案，直数=4 代理算 8。按
  // taskId/agentId 链键去重，一链一计（与目录 _subDirRows 同口径）
  function _hgRunChains() {
    // a122（用户实锤「子代理明明结束了，胶囊还显示」）：同链多档时按
    // **最新生命周期事件**定运行态，不能先到先占。实测：live 残留档
    // call_xxx（done:false、doneAt:0、47h 前建）先于权威档 a57ea…
    // （done:true/interrupted）被遍历到，占住 cid 后把终态档挡在 seen 外
    // → 胶囊恒「子代理执行中」。
    // 判据：每条记录的「最近事件时刻」= max(doneAt||0, t0||0, sendAt||0)。
    // 必须含 sendAt —— 生产续派是**就地复活原档**（v4bridge.js:747-755：
    // done=false/doneAt=0，**不改 t0**，只写 sendAt=现在）。若只取
    // max(doneAt,t0)，首轮被 _hgAgentsSweep 落成 done 的档（doneAt=收尾时刻
    // 晚于 t0）会赢过刚复活的同一条记录，链被误判成已结束、胶囊不显示。
    // 平局时 done 优先（终态档 doneAt 可能为 0，见 subagent_projection
    // 「endedAt 缺失取 0」——此时不靠键序碰运气）。
    const best = new Map();
    for (const k in (_HG.agents || {})) {
      const a = _HG.agents[k];
      if (!a) continue;
      const cid = a.taskId || a.agentId || k;
      const at = Math.max(a.doneAt || 0, a.t0 || 0, a.sendAt || 0);
      const prev = best.get(cid);
      if (!prev || at > prev.at
          || (at === prev.at && !!a.done && !prev.a.done)) {
        best.set(cid, { a, at });
      }
    }
    const out = [];
    best.forEach((v) => { if (!v.a.done) out.push(v.a); });
    return out;
  }
  function _hgPeerLines() {              // 协作转交线（v3.4.88：识图卡 .h-vision 并入——面板/等待/胶囊同源）
    return [..._hgFlow.querySelectorAll('.h-switch[data-peer], .h-tool.h-vision[data-peer]')];
  }
  // v3.4.68（用户定调「这个也不应该存在吧？等待啥呢？」）：本会话子代理的
  // SendMessage 续派复核不是跨会话协作——它的转交线一律不上动态页「子代理/
  // 协作」区（「协作·等待结论回传」行对它就是假等待）。判定两级：live 用
  // agents 档案（agentId/taskId 字段，key 是包装 tool_use_id 不可直查）；
  // 历史重建后 live 档案为空，退化为 DOM 取证——本会话子代理 Task 行的
  // 折叠体里带「agentId: <id>」回执文本（v2.37 起的回填事实）
  function _hgLocalResendPeer(peer) {
    if (!peer) return false;
    if (Object.values(_HG.agents || {})
        .some(a => a && (a.agentId === peer || a.taskId === peer))) return true;
    try {
      // v3.4.68R（轻审实证）：历史重建路径 Task 行折叠体生而为空、agentId 只落
      // dataset.hgSubr（07-hist:198-199，不进 textContent）——textContent 扫描
      // 恒 miss。改属性直配（顺带免 textContent 物化）
      return [..._hgFlow.querySelectorAll('.h-tool.agentline[data-hg-subr]')]
        .some(r => r.dataset.hgSubr === peer);
    } catch (_) { return false; }
  }
  function _hgPeerPending() {            // 还有未回传的协作等待（任意一条未定格）
    // v2.37R6：unknown（回合终结复核未检出回传）不算等待——否则输入框/
    // 面板永久挂「等待协作回传」
    // v2.41R2：stale（>30min 疑似残留）同步排除——与面板 C 区过滤/pill 口径
    // 统一为「stale/unknown 都不算等待」，防输入框提示与 pill 对同一状态相反
    // v3.4.68（用户实锤「等待什么的回传？是不是有问题？」）：本会话子代理的
    // SendMessage 续派（to=自己的 reviewer/子代理 agentId）不是跨会话协作——
    // 回报走 SubagentHandback 帧数分钟内自回，不该把胶囊/输入框挂进「等待
    // 协作回传」全局态（实测常驻 26min+）。线照画、回报照定格（历史事实），
    // 只是不再驱动等待语义。agents 档案 key=包装 tool_use_id，真身在
    // agentId/taskId 字段，故按字段匹配；档案被清时退化回旧行为（不误杀）。
    return _hgPeerLines().some(el => {
      if (el.dataset.done || el.dataset.unknown === '1' || el.dataset.stale === '1') return false;
      return !_hgLocalResendPeer(el.dataset.peer);
    });
  }
  function _hgInputState() {             // 输入框占位文案：运行态/子代理/协作等待联动
    let ph;
    if (_HG.busy && _HG.hold)
      ph = '大回合执行中（后台子代理/审计在跑）——输入将排队，全部完成后自动发送';
    else if (_HG.busy && _hgAgentsRunning())
      ph = '子代理执行中——回复进行中，继续输入将排队，结束后自动发送';
    else if (_HG.busy)
      ph = '回复执行中——继续输入将排队，结束后自动发送';
    else if (_hgAgentsRunning())
      ph = '子代理后台执行中——现在输入将开启新回合（不影响子代理）';
    else if (_hgPeerPending())
      ph = '等待协作回传——现在输入将开启新回合（回传到达将归入其协作段）';
    else
      ph = '给 Claude 发消息，@ 引用文件，/ 选择技能 · 可直接粘贴图片';
    if (_hgInput.placeholder !== ph) _hgInput.placeholder = ph;
  }
  function _hgAgentModelsFetch() {
    if (_agentModelsTried) return;
    _agentModelsTried = true;
    fetch('/api/harness/agent_models').then(r => r.json())
      .then(j => {
        if (!j || !j.ok) return;
        _HG.agentModels = j.agents || {};
        // v2.35.1（F4）：缓存晚到时回填已开 tab——_subOpen 时缓存未就绪的
        // 条目 model 是空串，不回填则 frontmatter 预显示在 tab 永不出现
        // （实跑 model 到达的条目不动，仍以实跑为准）
        for (const t in _sub.tabs) {
          const tb = _sub.tabs[t];
          if (!tb.model) {
            const ty = tb.type || ((_HG.agents || {})[t] || {}).type || '';
            if (ty && _HG.agentModels[ty]) tb.model = _HG.agentModels[ty];
          }
        }
        renderSideStatus();              // 面板 C 区/详情卡的模型预显示跟随
        _subTabsPaint();                 // 已开 tab 的模型角标补显
      }).catch(() => { _agentModelsTried = false; });
  }
  function _hgAgentModelPre(type) {
    _hgAgentModelsFetch();
    return (_HG.agentModels && _HG.agentModels[type]) || '';
  }
  // v4.0.1（用户硬性要求「无条件能点开任意子代理」）：按 tid 解析出真实
  // agentId 再开窗。权威链「强制 regSync 重查（tid + tidMap[tid] 两键）→
  // 后端 subagent_resolve（扫转写，持久兜底）→ 目录兜底」，命中路径零延迟。
  // 三个调用方共用：①档案缺失 ②档案在场但 taskId/agentId 全空 ③幻影档案。
  function _subResolveOpen(tid, _type, _desc) {
    if (!tid) return;
    const _fallbackDir = (msg) => { _subDirOpen(); showBanner(msg, 4000); };
    if ((_HG.subResInflight || {})[tid]) return;
    (_HG.subResInflight = _HG.subResInflight || {})[tid] = true;
    // v4.0.1：定位途中**不**切到目录 tab——成功即直接开窗格，切了会先
    // 闪一下目录再跳回（用户看到「点了跳到目录又弹走」）。失败才开目录。
    showBanner('正在定位该子代理…', 2500);
    Promise.resolve(typeof _hgRegSync === 'function'
      ? _hgRegSync(_HG.sid, { quiet: true }) : null)
      .then(() => {
        const a2 = (typeof _hgAg === 'function' ? _hgAg(tid) : null);
        if (a2 && (a2.agentId || a2.taskId)) {
          _subReplay(tid, a2.type || _type || 'Task', a2.desc || _desc || '子代理',
                     a2.agentId || a2.taskId, true, !a2.done);
          return null;
        }
        return fetch('/api/harness/subagent_resolve?sid=' +
              encodeURIComponent(_HG.sid) + '&tid=' + encodeURIComponent(tid))
          .then(r => r.json());
      })
      .then(j => {
        if (j === null) return;
        if (!j || j.ok !== true) { _fallbackDir('子代理定位失败——已打开子智能体目录'); return; }
        if (j.kind === 'agent' && j.agentId) {
          _HG.agents = _HG.agents || {};
          _HG.agents[tid] = _HG.agents[tid] || {
            type: j.type || _type || 'Task', desc: j.desc || _desc || '',
            t0: Date.now(), done: false, doneAt: 0,
            agentId: j.agentId, taskId: j.agentId };
          _subReplay(tid, j.type || _type || 'Task', j.desc || _desc || '',
                     j.agentId, true, true);
        } else if (j.kind === 'task') {
          _fallbackDir('这是后台命令任务（Bash 后台执行），没有子代理转写——已打开子智能体目录');
        } else {
          _fallbackDir('找不到该子代理的转写记录（可能已被清理）——已打开子智能体目录');
        }
      })
      .catch(() => _fallbackDir('子代理定位请求失败——已打开子智能体目录'))
      .finally(() => { delete (_HG.subResInflight || {})[tid]; });
  }
  function _subReopen(tid) {
    if (!tid) return;
    tid = _subTid(tid);   // v3.4：续派包装 id 归一——永远接回原子代理的 tab
    if (!_sub.tabs[tid]) {
      const a = (_HG.agents || {})[tid];
      // v3.5.160（159 引入、160 修订）：幻影档案（task_started 兜底建档时 peerSent miss→taskId
      // 降级为包装 task_id，unresolved 标记）——拿降级 id 硬开回放会陷入
      // 「转写尚未生成」重试循环（_subDirRowClick 第二失败形态），统一走
      // 解析漏斗（S2）拿真实 agentId 重建真档案
      if (a && a.unresolved && !a.agentId) {
        const _uType = a.type || 'Task', _uDesc = a.desc || '';
        delete (_HG.agents || {})[tid];
        _subResolveOpen(tid, _uType, _uDesc);
        return;
      }
      // v3.2.31（bug5②）：档案丢失（切会话往返）不再只弹 banner——打开子
      // 智能体目录 tab，任何点击必有可见响应（目录列回放档可进入）
      if (!a) { _subResolveOpen(tid); return; }
      const aid = a.taskId || a.agentId || '';
      // v4.0.1（用户硬性要求「无条件能点开任意子代理」）：档案在场但
      // taskId/agentId 全空时，旧码落到末尾 `_subOpen(tid, ...)` 建一个
      // **无数据的空窗格**（用户看到白板）。空 id 说明只是「知道有这次
      // 派发」，真实 id 仍在转写里——和「档案缺失」是同一类问题，必须
      // 走同一条解析漏斗，不能开空壳。
      if (!aid) { _subResolveOpen(tid, a.type, a.desc); return; }
      // v3.4：SendMessage 档案 label 溯源（tab 不叫「SendMessage」）——taskId
      // 反查友好名（peerNames），查不到落 id 尾缀
      let _desc = a.desc || '';
      if ((a.type || '') === 'SendMessage' && !_desc) {
        _desc = (typeof _peerDesc === 'function' ? _peerDesc(aid, '') : '')
          || ((_HG.peerNames || {})[aid] || String(aid).slice(-6));
      }
      // 实测修复（用户实锤「结论不对板」）：done 路径也 force 重铺——tab 已在
      // 时旧码只切换不重建，窗格留的是旧版双通道喂数的乱序残留 DOM（铺底行
      // 与中途增量交错，最后一条 asst=中途文本冒充结论）；重开=全量重铺幂等
      if (a.done && aid) { _subReplay(tid, a.type, _desc, aid, true); return; }
      // v3.2.6R2（用户实锤「运行过程中不能点开看」）：运行中重开也走全量
      // 铺底——旧态只建空脚手架等增量，中途重开=白板（此前事件不重现）。
      // force 回放 + F3 运行态分支（不定稿/秒表起跑/镜像续流）= 铺底即实况
      if (!a.done && aid) { _subReplay(tid, a.type, _desc, aid, true); return; }
      _subOpen(tid, a.type, _desc);
    }
    _sub.manual = true;                  // P0-3：手动来源——回合终结不自动收起，✕ 才收
    _subShow(undefined, true);
    _subActivate(tid);
  }
  function _subDrop(tid) {
    const tb = _sub.tabs[tid];
    if (!tb) return;
    // a64（用户实锤「子代理页开关几次后全前端发不出请求」）：✕ 关 tab 必须
    // 同步关 v4 子 store——EventSource 不关就永久占一条同域连接（6 条上限），
    // 开关几个来回 POST/SSE 全排队。el 即将脱离 DOM，靠它匹配的唯一机会在此
    try {
      if (typeof V4Main !== 'undefined' && V4Main.on() && tb.sc)
        V4Main.subClose(tb.sc);
    } catch (_) {}
    // v3.2.6：停窗格秒表（tab 档案拆了 tick 闭包的自愈判据就没了——先停）
    if (tb.tick) { clearInterval(tb.tick); tb.tick = null; }   // v3.4：tick 挂 tab
    // v3.4R2：伪 tab 关闭清账——动态页断 dynEl（tick 自愈不复活，重开重建）、
    // 目录停 1s 秒表
    if (tid === _SUB_DYN) dynEl = null;
    if (tid === _SUB_DIR) _subDirTickStop();
    if (tb.sc && tb.sc.parentNode) tb.sc.remove();
    delete _sub.tabs[tid];
    _sub.order = _sub.order.filter(t => t !== tid);
    if (_sub.active === tid) {
      _sub.active = _sub.order[0] || null;
      // v3.4.38（用户实锤「子代理 tab 关了窗格不缩回」）：手动切 active 原先
      // 只翻 sc 显示，宽度停在子代理宽档——改走 _subActivate 统一处理
      // （sc 可见性 + tab 重绘 + 宽度按新激活 tab 重新分档：退回动态/目录窄档）
      if (_sub.active) _subActivate(_sub.active);
    }
    _subTabsPaint();
    if (!_sub.order.length && _subPaneEl) {
      _subPaneEl.style.display = 'none';
      // a638（用户实锤「子代理页我明确都关掉了，切会话还会弹」）：✕ 关到
      // 一个不剩 = 用户明确要它关着。记进按 sid 的意图表，切回来时
      // _subRestoreActive 只认这条，不再凭「历史 active」无条件弹窗。
      _subUserOpenMark(_HG.sid, false);
    }
  }
  function _hgAgentsSweep(markErr, forceBg) {     // 回合终结：在跑的子代理统一收尾（防假"运行中"）
    if (!_HG.agents) {
      // 批2（迁出主窗）：DOM 段扫兜底退役（段不存在）——窗格 tab 键即 id，
      // 按 tabs 兜底定稿+行卡收口（防永卡「工作中」/秒表不死跑）
      for (const t in _sub.tabs) {
        try { _subTlFinalize(t, { err: !!markErr }); } catch (_) {}
        try { _hgAgentRowState(t, !!markErr, ''); } catch (_) {}
      }
      return;
    }
    let swept = false;
    for (const id in _HG.agents) {
      const a = _HG.agents[id];
      // v2.35：后台代理（bg）在主回合 result 时不收——它还在跑，收尾信号是
      // task_notification；中断/退出（markErr）照收：进程没了，一切皆停
      // v3.5.143：forceBg——turn_complete（大回合真收尾，后端 bg 集已空/已
      // 硬顶释放）时强收 bg 残留为「已工作」非 err：notification 丢失或 30min
      // 硬顶后卡片不死跑（result 正常路径不传——hold 机制保证 bg 在飞时
      // 到不了那）
      if (!a.done && !(a.bg && !markErr && !forceBg)) {
        a.done = true; a.doneAt = Date.now();
        if (markErr) { a.err = true; a.interrupted = true; }
        // 批2：段头定格退役（段不存在）——两收口保留
        // v3.2.6：窗格时间线同路定稿（已工作 X + 结论上移）——单行任务卡
        // 的单行态靠档案，窗格头不能永卡「工作中」
        if (_sub.tabs[_subTid(id)]) _subTlFinalize(id, { err: !!a.err });   // 复审#10：tab 键归一（Sync 后 agents 键=agentId 而 tab 键=首见 tid）
        // v3.5.145（全审F1）：主会话流单行卡同步终态收口（停秒表+徽章）——
        // _hgAgentRowState 是终态唯一停表点，幂等（notification 已到时档案
        // done 本分支不进；正常路 renderOneToolResult 先到已收，重入无害）
        _hgAgentRowState(id, !!a.err, a.result || '', !!a.stopped);
        swept = true;
      }
    }
    if (swept) renderSideStatus();
    // 冷查询批5：sweep 是同步视觉收口（interrupted/exit/result/turn_complete
    // 四路即刻定格），冷查询是异步权威——fire-and-forget 一次 Sync 让权威态
    // 2s 内纠偏（bg 真跑被误收的场景由此翻正，A5 净改善；幂等拉取无副作用）
    if (swept && typeof _hgRegSyncSoon === 'function') _hgRegSyncSoon(_HG.sid);
  }
  function _hgTurnMend(durMs) {         // a147：并回回合二次收口——ring 末条改全量工时
    const d = _hgDyn();
    const last = d.turns[d.turns.length - 1];
    if (last && durMs > 0) last.dur = Math.round(durMs / 1000);
    d.turnTools = 0;                    // 段尾工具数清零（防顺延污染下一回合条目）
    renderSideStatus();
  }
  function _hgTurnEnd(st, durMs) {       // 回合记账 ring（≤10）；dur 优先事件值（网关常缺失→本地差值）
    const d = _hgDyn();
    const dur = (durMs > 0) ? durMs : Date.now() - (_HG.actStart || Date.now());
    d.turns.push({ n: ++d.turnN, dur: Math.max(0, Math.round(dur / 1000)), st, tools: d.turnTools });
    if (d.turns.length > 10) d.turns.shift();
    d.turnTools = 0;
    renderSideStatus();
  }
  function _hgActPush(it) {              // 活动流 ring（≤20）；回放路径在调用方排除
    const d = _hgDyn();
    d.acts.push(it);
    if (d.acts.length > 20) d.acts.shift();
    renderSideStatus();
  }
  function _hgActDone(tid, st) {
    const a = ((_HG.dyn && _HG.dyn.acts) || []).find(x => x.tid === tid && !x.done);
    if (!a) return;
    a.done = true; a.doneAt = Date.now();
    a.err = (st === 'error' || st === 'denied');
    renderSideStatus();
  }
  let _rolesFetchSeq = 0;   // v3.5.6：请求序号——启动 fetch(无 sid) 与 switchTo
                            // 补拉(带 sid) 并发时，旧响应后到会覆盖新值（徽章
                            // 随机回退旧形态），过期响应一律丢弃
  async function _hgRolesFetch() {       // roles 只读拉取（缓存+刷面板；失败静默）
    const mySeq = ++_rolesFetchSeq;
    try {
      // v3.5.3：带 sid——mode 按当前会话实跑模型判定（不带则回退方案默认，
      // 实跑与默认不同时徽章会错形态）
      const q = _HG.sid ? ('?sid=' + encodeURIComponent(_HG.sid)) : '';
      const j = await (await fetch('/api/harness/roles' + q)).json();
      if (mySeq !== _rolesFetchSeq) return j;   // 已有更新的请求在途——丢弃
      if (j && j.ok) { _hgRolesCache = j; renderSideStatus(); }
      return j;
    } catch(_) { return null; }
  }
  function _hgCopyText(t) {
    if (!t) return;
    const p = navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject();
    p.then(() => showBanner('已复制', 1600)).catch(() => showBanner('复制失败', 2000, true));
  }
  function _hgJumpRow(tid) {             // 跳消息流工具行（只读操作，不碰快照状态机）
    const row = _HG.rowById[tid];
    if (!row || !row.isConnected) return;   // 卸载态防御（busy 中切过 tab）
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    row.classList.remove('hg-dyn-jump');
    void row.offsetWidth;                // 重启动画
    row.classList.add('hg-dyn-jump');
    setTimeout(() => row.classList.remove('hg-dyn-jump'), 1600);
  }
  // a640（用户定调「动态中的子代理协作整个删除」）：详情卡与「回放该子代理
  // 过程」按钮一并移除——用户实测「从目录点开是正常状态，动态页点开不显示
  // 回放」。子代理一律从目录进入（_subDirOpen），不再有这条坏路径。
  function _hgDynRender() {
    if (!dynEl) return;
    for (const fn of [_dynStat, _dynTodos, _dynActs, _dynTurns, _dynFiles]) {
      try { fn(); }
      catch (e) {
        // v2.37R6（C 区整栏消失②）：渲染失败降级为可见占位（区分无数据/
        // 渲染失败），不再只留 console 标记让整栏凭空蒸发
        try {
          console.error('[hg-dyn] 分区渲染异常', fn.name, e);
          // v2.39：错误文本直接上屏——WebView2 用户开不了 console，降级占位
          // 只说「详见 console」等于没有诊断信息（用户实锤无法反馈根因）
          // a641：子代理区已删，原来针对它的降级分支一并移除。
        } catch(_) {}
      }
    }
    // v3.3：_hgInputState/_hgDynCapsulePaint 上移 renderSideStatus（dynEl 为 null
    // 时也要执行——原挂这里会被动态页未建短路）
  }
  function _sec(z) { return dynEl.querySelector(`[data-hg-sec="${z}"]`); }
  const _THINK_TXT = { low: '低', medium: '中', high: '高', max: '最高' };
  const _TURN_ICO = { ok: '✓', error: '✗', interrupt: '⏹', exit: '⏻' };
  const _FILE_TOOLS = ['Read', 'Edit', 'MultiEdit', 'Write', 'NotebookEdit'];
  const _hhmm = ts => new Date(ts).toTimeString().slice(0, 5);
  function _dynStat() {                  // A 会话状态：双来源口径——当前会话值(s.*)优先，无会话回退新会话参数(_HG.*)
    const sec = _sec('stat'); if (!sec) return;
    const s = _HG.sessions.find(x => x.sid === _HG.sid);
    const stEl = sec.querySelector('[data-hg-d-st]');
    const ttEl = sec.querySelector('[data-hg-d-stt]');
    // v2.35（P0-1②③）：非 busy 的「等待类」状态也算运行态——面板徽章与
    // 输入框提示同源派生（后台子代理在跑 / 协作回传未到，用户不再误判空闲）
    const agRun = _hgAgentsRunning(), peerWait = !agRun && _hgPeerPending();
    sec.classList.toggle('run', !!_HG.busy || agRun || peerWait);
    // v2.36：纯等待态（非 busy/无子代理、仅协作回传未到）状态点/秒表转「等待蓝」
    // ——与 C 区协作行/输入框提示同语义（仅类名调整，渲染逻辑零变化）
    sec.classList.toggle('wait', peerWait && !_HG.busy);
    let stTxt;
    // a52（用户实测「一个会话压缩其他会话胶囊也显示压缩」）：压缩归属门控
    if (_HG.compacting && _HG.compactSid === _HG.sid) stTxt = '正在压缩上下文';
    else if (_HG.busy && agRun) stTxt = '子代理执行中';
    else if (_HG.busy) stTxt = '回复中';
    else if (agRun) stTxt = '子代理后台执行中';
    else if (peerWait) stTxt = '等待协作回传';
    else if (!_HG.sid) stTxt = '新会话';
    else if (_HG.alive) stTxt = '就绪';
    else stTxt = '待命';
    stEl.textContent = stTxt;
    if (_HG.busy && _HG.actStart) {
      ttEl.dataset.t0 = _HG.actStart;
      ttEl.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - _HG.actStart) / 1000)));
    } else if (agRun) {
      // 非 busy 但子代理在跑（后台 Task）：计最早起跑的代理时长
      const t0 = Math.min(...Object.values(_HG.agents || {}).filter(a => !a.done).map(a => a.t0 || Date.now()));
      ttEl.dataset.t0 = t0;
      ttEl.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
    } else if (peerWait) {
      const t0 = Math.min(..._hgPeerLines().filter(el => !el.dataset.done)
        .map(el => +(el.dataset.t0 || 0) || Date.now()));
      ttEl.dataset.t0 = t0;
      ttEl.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - t0) / 1000)));
    } else {
      delete ttEl.dataset.t0;
      const lt = (_HG.dyn && _HG.dyn.turns || []).filter(t => t.st === 'ok').pop();
      ttEl.textContent = lt ? '最近回合 ' + _hgFmtDur(lt.dur) : '';
    }
    const model = (s && s.model) || _HG.model || '';
    const think = (s && s.think) || _HG.thinkLv || null;
    const perm = (s && s.permission) || _HG.perm || 'auto';
    const cwd = (s && s.cwd) || _HG.cwd || '';
    sec.querySelector('[data-hg-d-model]').textContent = model || '—';
    sec.querySelector('[data-hg-d-model]').title = model ? '当前会话模型（chip 改的是新会话）' : '';
    sec.querySelector('[data-hg-d-think]').textContent = think ? (_THINK_TXT[think] || think) : '默认';
    sec.querySelector('[data-hg-d-perm]').textContent = perm === 'confirm' ? '每次确认' : '自动执行';
    const cw = sec.querySelector('[data-hg-d-cwd]');
    cw.textContent = cwd ? cwd.split(/[\\/]/).pop() : '~';
    cw.title = cwd || '';
    let ctxTxt = '待统计', warn = false;
    if (_HG.sid) {
      try {
        const v = JSON.parse(localStorage.getItem('hg-ctx:' + _HG.sid) || 'null');
        // 同胶囊：busy 期取 _HG.ctxRing（实时链同源），空闲取记忆
        const live = _HG.busy ? (_HG.ctxRing || null) : null;
        // 同胶囊：非 busy 时分母也要可溯源，否则会显示圆环已经不再显示的旧百分比
        const memOk = live || _hgCtxDenomOk(v);
        const base = live ? live.used : (memOk ? (v && v.used) : 0);
        const mx0 = live ? live.max : (memOk ? (v && v.max) : 0);
        // 分母未知时不出百分比，口径同胶囊
        if (base > 0 && mx0 > 0) {
          const mx = mx0;
          // v4.1（用户定调）：侧栏详情同胶囊——只按真值 base，不叠估值
          // a453（第二轮审计 P2）：显示 floor、判色 round，与胶囊/圆环同档。
          // 原来 round 后拿它判色，79.6% 会出现「胶囊 79%、详情 80% 亮橙」。
          const _p2 = Math.min(100, base / mx * 100);
          ctxTxt = Math.floor(_p2) + '% · ' +
                   (base / 1000).toFixed(1) + 'K/' + (mx / 1000).toFixed(0) + 'K';
          warn = Math.round(_p2) >= 80;
        }
      } catch(_) {}
    }
    const cx = sec.querySelector('[data-hg-d-ctx]');
    cx.textContent = ctxTxt;
    cx.closest('.hg-dyn-kv').classList.toggle('warn', warn);
    const r = _hgRolesCache && _hgRolesCache.roles;
    const rEl = sec.querySelector('[data-hg-d-roles]');
    // 形态正确 + 模型名可读。/roles 响应自带 mode（v3.5.0 三态
    // light/mid/heavy）与 resolved（designer/reviewer 各自实模型），按形态
    // 出对应角色行；三形态主会话都直干——轻主力=设计+审核两代理，中主力
    // =只留审核兜底，重主力=派发自由零强制(v3.5.16+)
    const _mode = _hgRolesCache && _hgRolesCache.mode;
    const _res = (_hgRolesCache && _hgRolesCache.resolved) || {};
    if (r) {
      if (r.enabled) {
        // v3.5.0：旧 strong ≡ 新 mid；称谓轻主力/中主力/重主力
        rEl.textContent = _mode === 'light' ? '轻主力'
          : (_mode === 'heavy' ? '重主力' : '中主力');
        rEl.title = _mode === 'light'
          ? `轻主力模式（点击打开配置面板）\n设计：${_res.designer || _res.heavy || '…'}\n审核：${_res.reviewer || _res.heavy || '…'}`
          : _mode === 'heavy'
            ? '重主力（最信任档：直干+派发自由，免强制分级；点击打开配置面板）'
            : `中主力直干模式（点击打开配置面板）\n审核兜底：${_res.reviewer || _res.heavy || '…'}`;
      } else {
        rEl.textContent = '关闭·直连';
        rEl.title = '直连干活（点击打开配置面板可启用三角色）';
      }
    } else rEl.textContent = '…';
  }
  function _dynTodos() {                 // B 进程（v3.1 ZCode 式重做）：分组清单——进行中 → / 待处理 ○ / 已完成 ✓，两组可折叠
    const sec = _sec('todos');
    const todos = _HG.todos || [];
    // v3.1：数据面扩容——todo 清单缺席但投影有活（回合计数/子代理）也出区
    //（「进程」的语义从 TodoWrite 清单扩为回合过程总览）
    const P = _HG.proj;
    const tt = (P && (P.status === 'running' ? P.turnTools : P.lastTurnTools)) || null;
    sec.hidden = !todos.length && !tt;
    if (sec.hidden) return;
    const d = _hgDyn();
    let html = '';
    // ---- 本回合活动计数行（投影 turnTools：N 工具 · N 搜索 · N 文件 …）----
    if (tt && tt.calls) {
      const bits = [tt.calls + ' 工具'];
      if (tt.searches) bits.push(tt.searches + ' 搜索');
      if (tt.reads) bits.push(tt.reads + ' 文件');
      if (tt.edits) bits.push(tt.edits + ' 编辑');
      if (tt.agents) bits.push(tt.agents + ' 子代理');
      html += '<div class="hg-proc-turn" title="'
        + (P.status === 'running' ? '本回合实时计数' : '上一回合计数') + '">'
        + (P.status === 'running' ? '<span class="hg-proc-live"></span>' : '')
        + esc(bits.join(' · ')) + '</div>';
    }
    if (todos.length) {
      const done = todos.filter(t => t.status === 'completed');
      const prog = todos.filter(t => t.status === 'in_progress');
      const pend = todos.filter(t => t.status !== 'completed' && t.status !== 'in_progress');
      const seen = d.todoSeen || {};
      // 折叠态：默认「已完成」收（有未完项时）、「待处理」开；点分组头切换
      if (d.procDoneOpen === undefined)
        d.procDoneOpen = !(pend.length + prog.length);
      if (d.procPendOpen === undefined) d.procPendOpen = true;
      const row = (t, st) => {
        const txt = (st === 'in_progress' && t.activeForm) ? t.activeForm : t.content;
        const ts = seen[t.content || ''];
        return `<div class="hg-proc-row ${st}" data-hg-todo title="${esc(t.content || '')}">` +
          `<span class="hg-proc-ico">${st === 'completed' ? '✓' : st === 'in_progress' ? '→' : '○'}</span>` +
          `<span class="hg-proc-tt">${esc(txt || '')}</span>` +
          (ts ? `<span class="hg-proc-ts">${_hhmm(ts)}</span>` : '') + '</div>';
      };
      if (prog.length) html += prog.map(t => row(t, 'in_progress')).join('');
      if (pend.length) html +=
        `<button class="hg-proc-grp" data-hg-proc-tgl="pend"><span class="h-chev${d.procPendOpen ? ' open' : ''}">‹</span>` +
        `<span class="hg-proc-grp-name">待处理 ${pend.length} 项</span></button>` +
        (d.procPendOpen ? pend.map(t => row(t, 'pending')).join('') : '');
      if (done.length) html +=
        `<button class="hg-proc-grp" data-hg-proc-tgl="done"><span class="h-chev${d.procDoneOpen ? ' open' : ''}">‹</span>` +
        `<span class="hg-proc-grp-name">已完成 ${done.length} 项</span></button>` +
        (d.procDoneOpen ? done.map(t => row(t, 'completed')).join('') : '');
    }
    sec.querySelector('[data-hg-d-tdone]').textContent =
      todos.length ? todos.filter(t => t.status === 'completed').length + '/' + todos.length : '';
    sec.querySelector('[data-hg-d-tbar]').style.width =
      todos.length ? (todos.filter(t => t.status === 'completed').length / todos.length * 100) + '%' : '0%';
    sec.querySelector('[data-hg-d-tlist]').innerHTML = html;
  }
  // a641（用户定调「只保留胶囊点击打开一个途径」）：动态页的子代理区已整块
  // 移除（a640 删内容、本轮删掉剩下的那条目录入口）。子代理唯一入口 = 胶囊。
  function _dynActs() {                  // E 最近工具：ring 20 条倒序，点击跳消息流，Bash 可复制
    const sec = _sec('acts');
    const acts = (_HG.dyn && _HG.dyn.acts) || [];
    sec.hidden = !acts.length;
    if (!acts.length) return;
    sec.querySelector('[data-hg-d-acts]').innerHTML = acts.slice().reverse().map(a => {
      const cls = a.done ? (a.err ? 'fail' : 'done') : 'run';
      // v3.5.34（用户实锤「最近工具计时每 5s 归零」）：运行中条目重建时
      // 按 t0 直算当前值——旧码写死「0s」，等 1s tick 才纠正；事件密集时
      // renderSideStatus 高频重建，每次都闪回 0s（体感=周期性归零）
      const el = !a.done
        ? `<b class="hg-dyn-el" data-t0="${a.t0}">${a.t0 ? _hgFmtDur(Math.max(1, Math.round((Date.now() - a.t0) / 1000))) : '0s'}</b>`
        : `<b class="hg-dyn-el">${a.err ? '失败' : _hgFmtDur(Math.max(1, Math.round((a.doneAt - a.t0) / 1000)))}</b>`;
      const cp = a.kind === 'bash' && a.preview
        ? `<button class="hg-dyn-actcp" data-hg-actcp="${esc(a.tid)}" title="复制命令">⧉</button>` : '';
      return `<div class="hg-dyn-act ${cls}" data-hg-act="${esc(a.tid)}" title="${esc(a.preview || a.label || '')}">` +
        `<span class="hg-dyn-adot"></span>` +
        `<span class="hg-dyn-at">${esc(a.label || a.name)}</span>` +
        `<span class="hg-dyn-desc">${esc(String(a.preview || '').slice(0, 60))}</span>${cp}${el}</div>`;
    }).join('');
  }
  function _dynTurns() {                 // F 回合历史：ring 10 条倒序 + 累计
    const sec = _sec('turns');
    const turns = (_HG.dyn && _HG.dyn.turns) || [];
    sec.hidden = !turns.length;
    if (!turns.length) return;
    const sum = turns.reduce((s2, t) => s2 + t.dur, 0);
    sec.querySelector('[data-hg-d-tsum]').textContent = '累计 ' + _hgFmtDur(sum);
    sec.querySelector('[data-hg-d-tlist]').innerHTML = turns.slice().reverse().map(t =>
      `<div class="hg-dyn-turn ${t.st}"><span class="hg-dyn-tk">${_TURN_ICO[t.st] || '·'}</span>` +
      `<span class="hg-dyn-tn">#${t.n}</span><span class="hg-dyn-td">${_hgFmtDur(t.dur)}</span>` +
      (t.tools ? `<span class="hg-dyn-tt2">${t.tools} 工具</span>` : '') + '</div>').join('');
  }
  function _dynFiles() {                 // G 当前文件：活动流派生最近 3 个文件路径
    const sec = _sec('files');
    const acts = (_HG.dyn && _HG.dyn.acts) || [];
    const files = [];
    for (let i = acts.length - 1; i >= 0 && files.length < 3; i--) {
      const a = acts[i];
      if (_FILE_TOOLS.includes(a.name) && a.preview && !files.includes(a.preview)) files.push(a.preview);
    }
    sec.hidden = !files.length;
    if (!files.length) return;
    sec.querySelector('[data-hg-d-flist]').innerHTML = files.map(f =>
      `<div class="hg-dyn-file" title="${esc(f)}">${esc(f.split(/[\\/]/).pop())}</div>`).join('');
  }
  // ==================== v3.3：动态页点击委托（自 20-main 构建期绑定迁出）====
  // 旧形态骨架是 index.html 静态节点，构建期 dynEl.onclick 直绑；v3.3 骨架改
  // _subDynOpen 懒建——绑定随骨架走：建 sc 时 sc.onclick = _hgDynClick（onclick
  // 覆盖式：伪 tab 重建不叠加）。函数体自 20-main 原样搬移零改动，引用全是
  // 全局符号（各 harness 编号脚本同一全局命名空间）。
  function _hgDynClick(e) {
    const cp = e.target.closest('[data-hg-copy]');
    if (cp) { e.stopPropagation(); _hgCopyText(cp.dataset.hgCopy); return; }
    // v3.1：进程面板分组头折叠开关（已完成/待处理两组，状态存 _HG.dyn）
    const pt = e.target.closest('[data-hg-proc-tgl]');
    if (pt) {
      e.stopPropagation();
      const d = _hgDyn();
      d[pt.dataset.hgProcTgl === 'done' ? 'procDoneOpen' : 'procPendOpen']
        = !(d[pt.dataset.hgProcTgl === 'done' ? 'procDoneOpen' : 'procPendOpen']);
      renderSideStatus();
      return;
    }
    // a641：动态页子代理区已整块移除，`data-hg-agdir` 不再产生。这两条分支
    // 只为防御旧快照/缓存页里残存的节点——点了仍开目录，不会静默无反应。
    const db = e.target.closest('[data-hg-agdir]');
    if (db) { e.stopPropagation(); _subDirOpen(); return; }
    const rb = e.target.closest('[data-hg-replay]');
    if (rb) { e.stopPropagation(); _subDirOpen(); return; }
    const acp = e.target.closest('[data-hg-actcp]');
    if (acp) {
      e.stopPropagation();
      const a = ((_HG.dyn || {}).acts || []).find(x => x.tid === acp.dataset.hgActcp);
      if (a) _hgCopyText(a.preview || '');
      return;
    }
    if (e.target.closest('[data-hg-act]')) { _hgJumpRow(e.target.closest('[data-hg-act]').dataset.hgAct); return; }
    if (e.target.closest('[data-hg-todo]')) {
      const rid = (_HG.dyn || {}).todoRowId;
      if (rid) _hgJumpRow(rid);
      return;
    }
    // v2.35（P0-2/P1-5）：运行中子代理行点击=重开实时窗格并切 tab（窗格已开
    // =切 tab）；已完成行保持展开详情卡；协作代理行=跳消息流对应转交线
    const pr = e.target.closest('[data-hg-peer-row]');
    if (pr) {
      const lines = _hgPeerLines();
      const pend = lines.filter(el => !el.dataset.done);
      const target = (pend.length ? pend : lines).slice(-1)[0];
      // 批2（迁出主窗）：协作段跳转退役（段不存在）——线隐藏（SendMessage
      // 协作归一形态）时改开窗格围观（转写全量铺底；miss 走 _subReopen 漏斗）
      if (target && target.style.display === 'none') {
        _subReopen(target.dataset.peer);
        return;
      }
      if (target) {
        target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        target.classList.remove('hg-dyn-jump');
        void target.offsetWidth;
        target.classList.add('hg-dyn-jump');
        setTimeout(() => target.classList.remove('hg-dyn-jump'), 1600);
      } else {
        showBanner('该协作没有对应的转交线（无消息流记录）', 2400);
      }
      return;
    }
    // a640：动态页不再渲染子代理行（区块已删）。这条分支只为兼容主消息流
    // 上带同名属性的行卡——统一改走目录，不再有「详情卡 + 回放按钮」这套。
    const ag = e.target.closest('[data-hg-ag]');
    if (ag) { _subDirOpen(); return; }
    // v2.37（P1-D）：三角色行点击=打开配置面板（开关进面板管理，防误触；
    // 旧行为是点击直接切开关，用户明确不要）
    if (e.target.closest('[data-hg-d-roles]')) { openRolesCfg(); return; }
  }

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._hgActDone = _hgActDone;
window._hgActPush = _hgActPush;
window._hgAgentModelPre = _hgAgentModelPre;
window._hgAgentModelsFetch = _hgAgentModelsFetch;
window._hgAgentsRunning = _hgAgentsRunning;
window._hgAgentsSweep = _hgAgentsSweep;
window._hgDyn = _hgDyn;
window._hgDynCapsulePaint = _hgDynCapsulePaint;
window._hgDynClick = _hgDynClick;
window._hgDynDirty = _hgDynDirty;
window._hgInputState = _hgInputState;
window._hgLocalResendPeer = _hgLocalResendPeer;
window._hgPeerLines = _hgPeerLines;
window._hgRolesFetch = _hgRolesFetch;
window._hgTurnEnd = _hgTurnEnd;
window._hgTurnMend = _hgTurnMend;
window._subDrop = _subDrop;
window._subReopen = _subReopen;
window._subResolveOpen = _subResolveOpen;
window.renderSideStatus = renderSideStatus;
