// harness histcache.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function _histRender(lines, start, opt) {
    _HG.lastTs = 0;   // v2.24.5：重建期时间条从零起算（第一条 user 带时间）
    // v2.24 CAP：正常模式渲染起点不得越过 capStart（翻阅上限）——更早的
    // 历史只能进「只读禅模式」看（_roEnter），保住正常模式的 DOM 省流
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
    _hgFlow.innerHTML = '';
    if (start > 0) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      // v2.24.2：上滑到顶一律进只读禅模式（busy 时不能重渲主 flow——会炸掉
      // 流式中的活组；CAP 上限同理）——文案统一，行为一致
      // v2.43.1（R-次要④）：计数按可见行——sub_* 行聚段后不单独占消息流位，
      // 计入会把「剩 N 条」虚高（账目 histStart 仍是行号，仅显示口径剔除）
      const visN = start - lines.slice(0, start).filter(
        l => l && l.role && String(l.role).indexOf('sub_') === 0).length;
      bar.innerHTML = '📖 剩 ' + visN + ' 条更早消息——<b>点击进入只读模式</b>查看';
      // 点击走 flow 级事件委托（下方绑定一次）：bar 在扩/收/重渲中反复重建，
      // 直绑 onclick 一旦在某次重建竞态中丢失就永久点不动（用户实锤「又不好使了」）
      _hgFlow.appendChild(bar);
    }
    if (!lines.length) return;
    _HG.noScroll = true;                        // v2.16：逐行 append 不反复重排
    _HG.histLineTs = 0; _HG.histActTs = 0; _HG.thinkPend = null;   // v3.2.2 ts 账 + v3.2.5 思考段时长 pend 随渲染重置
    _HG.openState = _hgLoadOpen(_HG.sid);       // v3.2.1：开合仓（现仅 sub: 段折叠语义键）兼重建期标志位（t0 不编造/秒表不亮/查阅定稿必收）
    try {
      // v2.28.16：边渲染边标回合边界——assistant 行之后的下一条 user 行
      // 意味着该回合已收尾，最后一条 AI 消息授予回滚按钮；流末尾的回合
      // （后面没有 user 行）在循环外补授（它就是最新定下的回合）
      let lastAsst = null;
      lines.slice(start).forEach((l, i) => {
        renderHistLine(l, start + i);
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
    finally { _HG.noScroll = false; _HG.openState = null; }
  }
  function _hgShrinkHead() {
    if (!_HG.histAll || !_HG.histAll.length) return;
    const keepStart = _HG.histAll.length - _HG.HIST_PAGE;
    const children = [..._hgFlow.children];
    const before = _hgFlow.scrollHeight;
    const top0 = _hgFlow.scrollTop;      // v2.46：摘除前的 scrollTop（锚定基准）
    let newStart = -1;
    let i = 0;
    // v2.37R5（终审·严重）：内层扫戳触底=尾部无戳（实时追加的活动内容），
    // 视作保留区——带标签 break 出外层，统一落到函数尾收尾。旧实现此处
    // return 硬退：已摘的组不回滚，而 histStart/入口条/scrollTop 回锚全被
    // 跳过 → 消息流只剩活动尾、历史无入口、断裂态被 saveCache 存档。
    // 纯无戳旧快照（一次都没摘，newStart<0）仍走静默放弃。
    outer: while (i < children.length) {
      const group = [children[i]];
      let hEnd = (children[i].dataset && children[i].dataset.hEnd != null)
        ? +children[i].dataset.hEnd : null;
      let j = i;
      while (hEnd == null) {
        j++;
        if (j >= children.length) break outer;   // 尾部无戳=保留，收尾
        group.push(children[j]);
        if (children[j].dataset && children[j].dataset.hEnd != null) {
          hEnd = +children[j].dataset.hEnd;
        }
      }
      if (hEnd >= keepStart) break;              // 触到保留区，摘头结束
      for (const g of group) g.remove();
      newStart = hEnd + 1;
      i = j + 1;
    }
    if (newStart < 0) return;                    // 纯无戳：零摘除，安全放弃
    _HG.histStart = newStart;
    // 视口锚定（v2.46 修「翻不下来」回归——CDP+Playwright 真实布局实证）：
    // 摘除头部内容后 scrollHeight 缩小，浏览器会对越界的 scrollTop 做钳制
    // （读取 scrollHeight 强制布局时生效）——钳制本身就是正确的视觉锚定
    // （视口落在同一批内容上）。旧实现不区分钳制与否，一律再减
    // 「摘除量」：贴底收缩时 scrollTop 已被钳到新上限，再减一次=双重补偿
    // → 视口飞到顶部 → 触发 nearTop 扩段把刚收掉的行重渲回来 → 锚定又
    // 落在中途（distBottom 卡 2000+px），用户再滚到底再触发——无限拉锯，
    // 即「滚动条翻不下来」。v2.43 对照实测同款翻车（v2.37R4 起潜伏，
    // R6 只收了触发条件没修锚定；v2.43 子代理行注入膨胀行数使其高频可达）。
    // 修法：摘除后再读一次 scrollTop，比 top0 小=浏览器已钳制（不动）；
    // 未钳制（用户在保留区中部，摘除不越过视口）才手动减摘除量。
    const removed = before - _hgFlow.scrollHeight;
    const top1 = _hgFlow.scrollTop;
    if (top1 >= top0) _hgFlow.scrollTop = Math.max(0, top1 - removed);
    // 头部若仍有更早历史，重建只读入口条（原条已随头部组摘除）
    // v2.43.2（R2-N2）：计数与渲染路径同口径（visN，剔除 sub_* 行）——
    // 否则收缩后条上数字比渲染路径虚高回跳
    if (newStart > 0 && !_hgFlow.querySelector('.hg-hist-more')) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      const _visN = newStart - ((_HG.histAll || []).slice(0, newStart).filter(
        l => l && l.role && String(l.role).indexOf('sub_') === 0).length);
      bar.innerHTML = '📖 剩 ' + _visN + ' 条更早消息——<b>点击进入只读模式</b>查看';
      _hgFlow.insertBefore(bar, _hgFlow.firstChild);
      _hgFlow.scrollTop += bar.offsetHeight;        // 条插入头部 → 视口同步下移补偿
    }
  }
  async function _histFetch(sidAt) {
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return false;
      _HG.histAll = j.lines || [];
      return true;
    } catch(_) { return false; }
  }
  async function _histRefresh(sidAt, start) {
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return;   // 会话已切走，弃
      if (_HG.busy) return;   // v3.2.1R2(R2-2)：fetch 在途时用户发送消息——重渲会抹掉活组/新消息泡，弃扩段（07-hist 懒填同款守卫）
      const lines = j.lines || [];
      _histRender(lines, start == null ? lines.length - _HG.HIST_PAGE : start);
    } catch(_) {}
  }
  function _roDeps() {
    return {
      _HG, wrap: _hgWrap,
      esc, mdBubble, renderMd, attChipsHtml, statusBadge,
      toolIco: _hToolIco, toolLabel: _hToolLabel, toolBodyHtml: _histToolBodyHtml,
      lazyFill: _histLazyFill, lazyDrop: _histLazyDrop,
      openLightbox,          // v2.3.12：只读层附件 chip 点开预览（委托经 deps 注入）
      timeFmt: _timeFmt, fmtDur: _hgFmtDur, imgExt: _HARNESS_IMG_EXT,
      onEmpty: () => { const bar = _hgFlow.querySelector('.hg-hist-more');
                       if (bar) bar.innerHTML = '⚠ 没有可查阅的历史'; }
    };
  }
  function _roEnter() {
    // 主层「进入只读」提示条入口（事件委托绑在 flow click）。失败必须上屏——
    // 静默会让用户以为按钮坏了。快照恢复路径 histAll 为空时先拉再进（v2.25）。
    try {
      if (!window.HgReadonly) throw new Error('只读模块未加载（harness/22-readonly.js 缺失）');
      if (!_HG.histAll || !_HG.histAll.length) {
        const sidAt = _HG.sid;
        if (!sidAt || _HG._roFetching) return;
        _HG._roFetching = true;
        _histFetch(sidAt).then(ok => {
          _HG._roFetching = false;
          if (_HG.sid !== sidAt) return;
          if (ok) _roEnter();
          else {
            const bar = _hgFlow.querySelector('.hg-hist-more');
            if (bar) bar.innerHTML = '⚠ 历史拉取失败——<b>点击重试</b>';
          }
        });
        return;
      }
      window.HgReadonly.enter(_roDeps());
    } catch (e) {
      console.error('[只读模式]', e);
      const bar = _hgFlow.querySelector('.hg-hist-more');
      if (bar) bar.innerHTML = '⚠ 只读模式打开失败: ' + esc(String(e)) + '（点击重试）';
    }
  }
  function _roExit() {
    if (window.HgReadonly) window.HgReadonly.exit();
  }
