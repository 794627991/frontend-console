// harness histcache.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function _histRender(lines, start, opt) {
    _HG.lastTs = 0;   // v2.24.5：重建期时间条从零起算（第一条 user 带时间）
    // v3.2.12（用户定调「只要往上滑就显示历史，分页加载不要了」）：恒全量
    // 渲染——整段会话一次原子换入，滚动条天然覆盖全部历史（ZCode 靠虚拟化
    // 管 DOM，我们靠：回合默认折叠（头+结论行极廉价）+ 代码/图片懒增强 +
    // 原子渲染一次成画）。扩段/收缩/「剩 N 条」机器整体退役
    start = 0;
    // v2.24 CAP：正常模式渲染起点不得越过 capStart（翻阅上限）——保住正常
    // 模式的 DOM 省流。v3.2.7：只读模式退役，上限 1200 行内全部上滑翻阅
    const capStart = Math.max(0, lines.length - _HG.HIST_CAP);
    start = Math.max(start, capStart);
    start = Math.min(start, lines.length);   // v2.37R2（复审4）：上界钳制——账目越界时 slice 为空只剩错误计数
    // v2.43：窗口起点落在子代理段中间时回退到段头——段行聚段渲染，拦腰起点
    // 会让段身行全部静默丢弃（回退上限=单段行数上限+头，不破 HIST_CAP 语义）
    while (start > capStart && lines[start] && lines[start].role
           && String(lines[start].role).indexOf('sub_') === 0 && lines[start].role !== 'sub_open')
      start--;
    _HG.histAll = lines;
    _HG.histStart = start;
    _HG.histLive = true;   // v2.35.2：窗口渲染完成——histAll/DOM 建立对应，滚动扩收自此放行
    _HG.histStale = false; // v2.43.2（R2-缺口A）：本次渲染 DOM/hi/hEnd 账目全新一致——降级态解除
    // v3.2.11（用户实锤「滚动条抽搐」）：原子渲染——全部行先落**游离缓冲**再
    // 一次性换入。旧实现逐行 append 活 DOM，几百行渲染期间滚动条逐帧长高
    // （抽搐）且锚定前的中间态可被绘制（上滑扩段打断滚动手势=「必须往下
    // 再往上」）。游离态渲染对子模块透明：addRow/grpEnsure/closeRun 全走
    // _hgFlow 引用；isNearBottom 在游离容器上恒 false（=回放收起语义，正确）
    const _realFlow = _hgFlow;
    const _buf = document.createElement('div');
    _hgFlow = _buf;
    // v3.2.13（用户实锤「没修复好」的根因）：游离缓冲期 grpEnsure 的
    // isConnected 快路径恒 false → 每行都重认回新 wrapper → g.exp 丢失 →
    // 每个 explore 工具各开一个单子行查阅组（碎片墙）。histBuilding 让
    // 连接性判据在缓冲期视缓冲内元素为「在场」（grpEnsure/_tlPlace/
    // _tlExpFlush 三处同判）
    _HG.histBuilding = true;
    _realFlow.innerHTML = '';
    if (start > 0) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      // v3.2.10（用户定调「绝对不允许封顶」）：无上限——任何时候都可上滑/
      // 点击扩段直到第一条；回合间快速定位走左缘回合导航轨（_hgRailSync）
      // v2.43.1（R-次要④）：计数按可见行——sub_* 行聚段后不单独占消息流位，
      // 计入会把「剩 N 条」虚高（账目 histStart 仍是行号，仅显示口径剔除）
      const visN = start - lines.slice(0, start).filter(
        l => l && l.role && String(l.role).indexOf('sub_') === 0).length;
      bar.innerHTML = '📖 剩 ' + visN + ' 条更早消息——<b>点击加载更早</b>（上滑自动加载 / 左侧刻度轨直达）';
      // 点击走 flow 级事件委托（下方绑定一次）：bar 在扩/收/重渲中反复重建，
      // 直绑 onclick 一旦在某次重建竞态中丢失就永久点不动（用户实锤「又不好使了」）
      _hgFlow.appendChild(bar);
    }
    if (!lines.length) {
      // v3.2.11：游离缓冲期早退必须先归还 _hgFlow 引用（否则全后续渲染
      // 都写进游离容器——主界面消失级事故）
      _hgFlow = _realFlow;
      _HG.histBuilding = false;   // v3.2.13：连接性判据还原（见顶部注释）
      // v3.1h(F4)：此处 innerHTML 已清空、恒无组，收起/清壳兜底无对象——
      // 唯一活版本在主回放 finally（replaceChildren 换入之后）
      _hgRailSync();
      return;
    }
    _HG.noScroll = true;                        // v2.16：逐行 append 不反复重排
    _HG.histLineTs = 0; _HG.histActTs = 0; _HG.thinkPend = null;   // v3.2.2 ts 账 + v3.2.5 思考段时长 pend 随渲染重置
    _HG.openState = _hgLoadOpen(_HG.sid);       // v3.2.1：开合仓（现仅 sub: 段折叠语义键）兼重建期标志位（t0 不编造/秒表不亮/查阅定稿必收）
    try {
      // v2.28.16：边渲染边标回合边界——assistant 行之后的下一条 user 行
      // 意味着该回合已收尾，最后一条 AI 消息授予回滚按钮；流末尾的回合
      // （后面没有 user 行）在循环外补授（它就是最新定下的回合）
      let lastAsst = null;
      lines.slice(start).forEach((l, i) => {
        // v3.4.52（致命双会话实锤连带）：行级隔离——此前任何一行抛错会中止
        // 整个重建（外层 catch 静默），症状=切回后只剩首行+spinner、其余
        // 「全没」。单行失败留痕放行，不拖垮整个 flow。
        // v3.4.55（轻审 P5）：失败行**跳过本行全部后续记账**（turnHi 章/
        // hEnd 戳/lastAsst 授予）——失败行的 DOM 不存在，把当前行号盖到
        // 上一行元素上=回合导航锚与收缩边界全部错位
        let _rok = true;
        try { renderHistLine(l, start + i); }
        catch (e) { _rok = false; try { console.error('[harness] hist line render failed @' + (start + i) + ' role=' + (l && l.role), e); } catch (_) {} }
        if (!_rok) return;
        // v3.2.10：user 行盖 turn-hi 章——回合导航轨的 DOM 跳转锚（未渲染
        // 回合按 histAll 行号扩窗后凭此定位）
        if (l.role === 'user' && String(l.text || '').trim()) {
          const _us = _hgFlow.querySelectorAll('.h-msg.user');
          const _lu = _us[_us.length - 1];
          if (_lu) _lu.dataset.turnHi = String(start + i);
        }
        // v2.37R4（DOM 收缩）：行尾戳——每行渲染完后在 flow 最后一个元素上
        // 记「到此为止已含第 hi 行」。增量收缩按戳定位头部边界（无戳孩子
        // 属于下一个带戳孩子=同一条线的先导元素），账目与 DOM 恒一致
        const _last = _hgFlow.lastElementChild;
        if (_last) _last.dataset.hEnd = String(start + i);
        // v2.30：回放恢复最新任务清单（TodoWrite 的 input 里有 todos）
        if (l.role === 'tool' && l.text === 'TodoWrite'
            && l.input && Array.isArray(l.input.todos)) _HG.todos = l.input.todos;
        // v2.32 面板：回放重建最近的子代理条目（无精确时刻→显示「历史」，
        // 不参与 sweep；只留最近 5 条防长会话堆积）
        if (l.role === 'tool' && (l.text === 'Task' || l.text === 'Agent')
            && l.input && (l.input.description || l.input.subagent_type || l.input.agent_type)) {
          const d = _hgDyn();
          d.agentsRpl = d.agentsRpl || [];
          // v2.59：同路审计去重——同 type+desc 的旧条目移除只留最新（用户实锤：
          // 同一条审计链的多轮复审逐条堆叠全是重复，回放确认即同一条路）
          const _typ = l.input.subagent_type || l.input.agent_type || 'Task';
          const _desc = l.input.description || '';
          d.agentsRpl = d.agentsRpl.filter(x => !(x.type === _typ && x.desc === _desc));
          // v2.38：从结果文本提取 agentId——历史条目的回放窗格靠它定位转写
          const _aid = (l.result && String(l.result).match(/(?<![a-zA-Z])agentId[:"':\s]+([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
          d.agentsRpl.push({
            type: _typ, desc: _desc, t0: 0, done: true, doneAt: 0, replay: true,
            agentId: _aid });
          if (d.agentsRpl.length > 5) d.agentsRpl.shift();
          // v3.2.6R2（用户实锤「点了说无 agentId」）：建档即回绑单行卡——
          // async 代理的 sub_open 注入依赖转写非空（0 字节占位/空转写时缺
          // 段），此处不依赖：行自带 hgSubType/hgSubDesc 预置键即可匹配
          if (_aid) {
            const _rows = _hgFlow.querySelectorAll('.h-tool.agentline:not([data-hg-subr])');
            _rows.forEach(r => {
              if ((r.dataset.hgSubType || '') === _typ
                  && (r.dataset.hgSubDesc || '').slice(0, 40) === _desc.slice(0, 40))
                r.dataset.hgSubr = _aid;
            });
          }
        }
        // v3.2.6R（审计F4）：SendMessage 续派也建目录条目——段卡已隐（CSS
        // display:none），此类代理无 Agent 派发行=无单行卡，目录是唯一入口。
        // 与后端 _inject_subagent_blocks 同源：result 文本带 resumedAgentId
        if (l.role === 'tool' && l.text === 'SendMessage') {
          const _ra = (String(l.result || '').match(/resumedAgentId[\"\':\s]+([0-9a-zA-Z_-]{8,64})/) || [])[1] || '';
          if (_ra) {
            const d = _hgDyn();
            d.agentsRpl = d.agentsRpl || [];
            if (!d.agentsRpl.some(x => x.agentId === _ra)) {
              const _msg = String((l.input || {}).message || '').trim().slice(0, 40);
              d.agentsRpl.push({
                type: 'SendMessage', desc: '续派' + (_msg ? ' → ' + _msg : ''),
                t0: 0, done: true, doneAt: 0, replay: true, agentId: _ra });
              if (d.agentsRpl.length > 5) d.agentsRpl.shift();
            }
          }
        }
        if (l.role === 'assistant') lastAsst = _HG.lastAsstEl;
        // v3.2.4R(F4)：排除已折进时间线的中间正文（中段边界定稿折体后
        // lastAsst 可能已在 .h-tl 内）——回滚钮只授予根区可见的回合尾正文
        else if (l.role === 'user' && lastAsst && lastAsst.dataset.rwa
                 && !lastAsst.closest('.h-tl')) {
          lastAsst.classList.add('can-rewind');
          lastAsst = null;
        }
      });
      if (lastAsst && lastAsst.dataset.rwa && !lastAsst.closest('.h-tl')) lastAsst.classList.add('can-rewind');   // v3.2.4R(F4)：同上排除 tl 内正文
      renderSideStatus();     // v2.30：回放后刷新侧栏动态（todos 已从工具行重建）
      // v3.2.1R(F1)：尾组定稿下沉到渲染器本体——此前只在 switchTo/
      // _hgSseRebuild/_hgReloadFlow 三入口补，扩段（_histRefresh）、快照指纹
      // 漂移、懒填点校验失败的重渲路径全部漏收：尾组回放期不亮头（无
      // 「已工作」行）+ 体全开，且坏形态随 saveCache 固化跨快照往返（对抗
      // 审计 F1 实锤路径）。busy 会话的尾组是进行中的活组（phResume 要认
      // 回续秒表），此类调用方传 opt.noFinalize 跳过。
      // v3.2.2：turnEnd（尾组正文=回合最终结论留在头外）+ endTs=末活动行 ts
      //（段工时事实——用户实测「没显示工作时长」）
      if (!(opt && opt.noFinalize))
        grpFinalize(true, { hist: true, turnEnd: true, endTs: _HG.histActTs || 0 });
    }
    finally {
      _HG.noScroll = false; _HG.openState = null;
      // v3.4.46：末段思考兜底——最后一段 thinking 后无更多带 ts 行，pend
      // 永挂=空白。渲染收尾一律落模糊文案（用户定调：宁可模糊不许空白）
      if (_HG.thinkPend) {
        const _tp2 = _HG.thinkPend; _HG.thinkPend = null;
        const _te2 = _tp2.seg.querySelector('[data-hg-think-t]');
        if (_te2 && !_te2.textContent) _te2.textContent = '持续了一小会';
      }
      // 原子换入：单次 DOM 变更单次布局——滚动条从旧态直达终态，无中间帧
      const _frag = document.createDocumentFragment();
      while (_buf.firstChild) _frag.appendChild(_buf.firstChild);
      _realFlow.replaceChildren(_frag);
      _hgFlow = _realFlow;
      // v3.1h（用户实锤「结束不收起+头部下空白壳」）：回放逐组定稿时 _HG.grp
      // 指针前移会漏收旧组；占位空壳随快照/重建残留。换入后统一兜底——
      // 非尾组 turn-body 全部收起 + 清占位残壳；busy 会话尾组是活组照常展开
      const _grps = _realFlow.querySelectorAll(':scope > .h-grp');
      _grps.forEach((gp, i) => {
        if (_HG.busy && i === _grps.length - 1) return;
        const tb = gp.querySelector(':scope > .h-grp-proc > .h-turn-body');
        if (tb) tb.classList.add("closed");
        const ph = gp.querySelector(":scope > .h-msg.asst.ph");
        if (ph) ph.remove();
      });
      // v3.1h（用户定调）：回滚只属最后一条 AI 消息——各回合尾条都带了
      // can-rewind，收敛为只留全局最后一条
      const _allAsst = _realFlow.querySelectorAll('.h-msg.asst.can-rewind');
      _allAsst.forEach((m, i) => { if (i < _allAsst.length - 1) m.classList.remove("can-rewind"); });
      _HG.histBuilding = false;   // v3.2.13：连接性判据还原（见顶部注释）
      _hgRailSync();
    }
  }
  // v3.2.22（用户实锤「切走再切回，子代理目录点不开」）：快照恢复路径不跑
  // 行渲染循环——agentsRpl 在切会话时被清、切回后永远不重建，目录成空壳。
  // 本函从 histAll 直接重建（与 _histRender 循环内逻辑同款：Task/Agent 行
  // + SendMessage 续派行；DOM 侧不用动——快照 dataset 已带 hg-subr 绑定）
  function _hgRplRebuild() {
    const lines = _HG.histAll || [];
    const d = _hgDyn();
    d.agentsRpl = [];
    for (const l of lines) {
      if (l.role === 'tool' && (l.text === 'Task' || l.text === 'Agent')
          && l.input && (l.input.description || l.input.subagent_type || l.input.agent_type)) {
        const _typ = l.input.subagent_type || l.input.agent_type || 'Task';
        const _desc = l.input.description || '';
        d.agentsRpl = d.agentsRpl.filter(x => !(x.type === _typ && x.desc === _desc));
        const _aid = (l.result && String(l.result).match(/(?<![a-zA-Z])agentId[:"':\s]+([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
        d.agentsRpl.push({
          type: _typ, desc: _desc, t0: 0, done: true, doneAt: 0, replay: true,
          agentId: _aid });
        if (d.agentsRpl.length > 5) d.agentsRpl.shift();
      } else if (l.role === 'tool' && l.text === 'SendMessage') {
        const _ra = (String(l.result || '').match(/resumedAgentId["'\s:]+([0-9a-zA-Z_-]{8,64})/) || [])[1] || '';
        if (_ra && !d.agentsRpl.some(x => x.agentId === _ra)) {
          const _msg = String((l.input || {}).message || '').trim().slice(0, 40);
          d.agentsRpl.push({
            type: 'SendMessage', desc: '续派' + (_msg ? ' → ' + _msg : ''),
            t0: 0, done: true, doneAt: 0, replay: true, agentId: _ra });
          if (d.agentsRpl.length > 5) d.agentsRpl.shift();
        }
      }
    }
    try { _subDirPaint(); } catch(_) {}
  }
  // v3.2.12：_hgShrinkHead（贴底收缩）随分页退役——恒全量渲染后无「窗口」可收
  async function _histFetch(sidAt) {
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return false;
      _HG.histAll = j.lines || [];
      return true;
    } catch(_) { return false; }
  }
  async function _histRefresh(sidAt, _startIgnored) {
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return;   // 会话已切走，弃
      if (_HG.busy) return;   // v3.2.1R2(R2-2)：fetch 在途时用户发送消息——重渲会抹掉活组/新消息泡（07-hist 懒填同款守卫）
      const lines = j.lines || [];
      _histRender(lines, 0);   // v3.2.12：恒全量（start 参数退役保留签名兼容）
    } catch(_) {}
  }
  // v3.2.7（用户定调「只读模式退役」）：_roDeps/_roEnter/_roExit 整体退役——
  // 更早历史一律上滑/点击扩段进现有 ZCode 渲染器（_histRefresh 大窗口重渲），
  // 到 HIST_CAP 硬顶后提示条指向左侧会话列表。22-readonly.js 模块保留在盘
  // （window.HgReadonly）但无任何入口，成为不可达代码
