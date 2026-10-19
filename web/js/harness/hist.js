// harness hist.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function renderHistTool(l, hi) {
    // v3.5.246（用户实锤「运行中正常，刷新又没了」）：hist 路径（刷新/重渲）
    // ask 行同样计数 counts.askN
    if (l.text === 'AskUserQuestion' || l.text === 'mcp__harness__ask_user') {
      try {
        const _ga = _HG.grp || (typeof grpEnsure === 'function' && grpEnsure(true));
        if (_ga) {
          _ga.counts = _ga.counts || {};
          _ga.counts.askN = (_ga.counts.askN || 0) + 1;
          if (typeof _turnHeadSubPaint === 'function') _turnHeadSubPaint(_ga);
        }
      } catch (_) {}
    }
    // R2c：走合一构造 hgToolCard（done 形态一次成型；hi 懒标记/dln 直传；
    // agent 行运行徽章）。ask 计数/lastAgRow/drawerCount/_tlPlace/rowById
    // 为 hist 侧放置账，留在 caller
    const _agKind = ((_H_TOOL_CFG[l.text] || {}).kind) === 'agent';
    const d = hgToolCard({
      id: l.tid || ('ag' + (hi != null ? hi : 'r' + (++_HG.uidN))),
      name: l.text, input: l.input || {}, phase: 'done',
      err: !!l.err, hi: hi,
      dln: (l.dln && Array.isArray(l.dln) && l.dln[0]) ? l.dln[0] : undefined,
      summary: l.summary, result: (l.err || ((_H_TOOL_CFG[l.text] || {}).defaultOpen)) ? l.result : undefined,
      running: _agKind ? _hgLiveAgentRunning((l.input || {}).description) : false,
    });
    if (_agKind) _HG.lastAgRow = d;
    drawerCount(l.text);
    _tlPlace(d, l.text, l.input || {});
    if (l.tid) {
      _HG.rowById = _HG.rowById || {};
      _HG.rowById[l.tid] = d;
    }
    return d;
  }
  function renderHistLine(l, hi) {
    // v3.2.2（用户实测「没显示工作时长」）：行级 ts 账——histLineTs=当前行
    // （grpEnsure 给切分组取段起点）；histActTs=最近一次非 user 活动（定稿
    // 取段终点：中段切组在渲染中途读 histActTs 恰为被定稿组末活动行；回放
    // 尾组定稿在循环外读=全段末活动）。旧转写缺 ts 保持 0——落无数字形态
    const _ts = l && l.ts ? Date.parse(l.ts) : 0;
    // v3.3.1：上一行 ts——思考段起点改挂前一行（同一条 assistant 消息里
    // thinking 与 tool_use 同 ts，按自身 ts 计时长恒 0 秒）
    const _prevTs = (_ts > 0) ? (_HG.histLineTs || 0) : 0;
    if (_ts > 0) _HG.histLineTs = _ts;
    // v3.2.5（用户定调「思考持续了一小会，和 ZCode 同款」）：回放思考段时长
    // ——起点=上一带 ts 行，下一条带 ts 的行到达时定格差值（转写无段级
    // 终点事实，邻行 ts 差是唯一诚实口径；后置入账同款时序：本行渲染前
    // 先收上一段的账）。v3.3.1：<3s 不显示（切片噪声非事实）
    // v3.4.46（用户实锤「思考持续时间全没了」）：结算条件 `_ts > t0` 在同批
    // 行（thinking 与 tool 同 ts）上恒 false——pend 永不结算=时长永久空白。
    // 放宽为 `>=`：同 ts 差值 0 按 v3.4.44 定调落模糊文案「持续了一小会」，
    // 绝不留空白（宁可模糊不虚增、更不许空白）
    if (_HG.thinkPend && _ts > 0 && _ts >= _HG.thinkPend.t0) {
      const _tp = _HG.thinkPend;
      // v3.4.46 真因（用户实锤「思考持续时间全没了」）：回放期 seg 挂游离
      // 缓冲 isConnected 恒 false（v3.2.13 已知事实），旧判据在此把 _te 判
      // null=文案永不写入——快照命中时有（innerHTML 随存），转写回放全空。
      // seg 引用必在，直接写，随缓冲一起换入
      const _te = _tp.seg.querySelector('[data-hg-think-t]');
      const _dur = _ts - _tp.t0;
      if (_te) _te.textContent = _dur >= 3000 ? '持续了 ' + _hgTurnDurTxt(_dur) : '持续了一小会';
      _HG.thinkPend = null;
    }
    // v3.2.6：lastAgRow 只活一行——sub_open 紧贴 Agent 派发行（transcript 注
    // 入序铁律），其余任何行到达即清（防隔行错绑到更早的 Agent 行）
    if (l.role !== 'sub_open') _HG.lastAgRow = null;
    if (l.role === 'peer') {          // v2.27.3：跨会话回传（识图结论）历史回看
      // R4：走 dispatch（live/hist 同一 handlers 同一渲染订阅）——识图卡
      // 配对/回落逻辑整迁订阅 case（对齐补丁退役）
      _hgDispatch({ t: 'peer_return', name: l.name, text: l.text,
                    to: l.to, tid: l.tid, hist: true });
    }
    else if (l.role === 'sysnote') {  // v3.3.2(D6)：机器注入弱化行历史回看
      // 不定稿不 renderUser——历史侧回合合并自动成立（历史组只在 user 行定稿）
      // F7（全审）：接线 dispatch——R1「七类进 entries」至此真七类（此前
      // sysnote handler 零构造点=死 handler）
      _hgDispatch({ t: 'sysnote', kind: l.kind || '', text: l.text });
    }
    else if (l.role === 'vision_relay') {  // v2.28：识图 MCP 转交线（历史回看）
      renderVisionRelayHist(l);
    }
    else if (l.role === 'exit') {    // v3.4.85：中断/退出痕迹回放（事件账本补行）
      // R6a：走 dispatch——出 exit 行+interrupted 建组定稿翻头的编排整迁
      // 订阅 case（v3.4.86 口径保留，两轨对齐补丁退役）
      _hgDispatch(String(l.text || '').indexOf('已中断回复') === 0
        ? { t: 'turn_interrupted', text: l.text, hist: true }
        : { t: 'turn_exit', text: l.text, hist: true });
    }
    else if (l.role === 'renew') {    // v2.27.23：超窗续命注入折叠为一行分割线
      // R1（流式/重渲统一）：走同一 FEV dispatch——live/hist 同一 handlers
      // →同一渲染函数，对齐补丁（v3.2.4R F3）退役为 dispatch 的统一编排
      grpFinalize(true, { hist: true, endTs: _HG.histActTs || 0 });
      _hgDispatch({ t: 'renew', text: l.text });
    }
    else if (l.role === 'audit') {    // v2.34：审计警示卡回放（v2.34.1 与实时同文本，
      // v3.2.27（用户定调「警告记录到工作区内，不许分割」）：撤定稿——警示
      // 挂进当前回合时间线（renderAudit 内判组），同一条会话的工作区不再
      // 被审计卡割成多段；由 audit log 并入
      _hgDispatch({ t: 'audit', text: l.text });
    }
    else if (l.role === 'user') {
      // v3.2.16 前端防线：旧后端（未重启进程）仍会发 [Image: source] 回显行
      // ——特征：无文字且附件全是 CLI Temp images 路径。整条跳过，消息列内
      // 不出现图片链接行/死链 chip（新后端转写侧已丢，这里是双保险）
      const _tmpEcho = !(l.files || []).some(
        p => !/Temp[\\/]claude[\\/].*[\\/]images[\\/]/i.test(String(p)))
        && (l.files || []).length > 0;
      if (!String(l.text || '').trim() && _tmpEcho) {
        // 回显行不画，但组管线边界语义保留（上一组定稿照走）
        endThinking(); closeRun(); _tlExpFlush(!!_HG.openState);
        _HG.asstText = false;
      } else {
        const imgs = (l.files || []).filter(p => _HARNESS_IMG_EXT.test(p));
        const files = (l.files || []).filter(p => !_HARNESS_IMG_EXT.test(p));
        // v2.24.1 回退气泡壳化：renderUser 承担组管线边界（上一组定稿/开新组），
        // 壳化绕过管线导致思考/工具挂错组（排序乱，用户实测不可接受）——
        // 正确性优先，历史气泡恢复全渲染（懒抽屉+懒高亮已覆盖大头开销）。
        // R2b：走 dispatch（live/hist 唯一渲染入口）
        _hgDispatch({ t: 'user_message', text: l.text,
                      images: imgs, files: files, ts: _ts });
      }
    }
    // R2a（气泡域归一）：assistant/thinking 走 FEV dispatch——live/hist 同一
    // handlers 同一渲染订阅（27-store _hgRenderEntries），懒抽屉/pend 上下文
    // 随事件携带（hi/ts/prevTs）。对齐补丁退役起点
    else if (l.role === 'assistant') _hgDispatch({ t: 'assistant_text', text: l.text, model: l.model || '' });
    else if (l.role === 'thinking') {
      // 图5 修复（ZCode reasoning_start 每块新行复刻）：历史行流中每条
      // thinking 都是独立块——中间夹的查阅组/工具行不阻断时旧码续用同一
      // seg（_HG.think 存活续接）=「查阅多了思考全连起来」。行前断开，
      // 每块开新段（live 路不受影响：SSE tool_use 分支已 endThinking）
      _HG.think = null;
      // v2.24 懒抽屉：历史思考段只建壳（默认收起），点开才渲染 markdown——
      // 大会话重建的大头就是几十 K 字符的 thinking 渲染（渲染体在订阅 case）
      _hgDispatch({ t: 'assistant_thinking', text: l.text,
                    hi: hi, ts: _ts, prevTs: _prevTs });
    }
    else if (l.role === 'tool') {
      // v2.3.2：历史重建补画转交等待线——transcript 的工具行此前只画抽屉，
      // 切回/刷新后转交线凭空消失（用户实锤「绝大多数看不到读秒」）。线的
      // 起点用行内 ts（后端 v2.3.2 审计 P1 已补）；收件人取 input.to（summary
      // 对 SendMessage 恒空——审计 P1b）；若后续有 peer 行，renderPeer 定格
      if (l.text === 'SendMessage' || (l.text || '').startsWith('⚙ SendMessage')) {
        // v2.49：历史重建同样隐藏 SendMessage 转交线（快照恢复走本分支——
        // 不藏则刷新/切回后线复活）。to 缺席的回退名「识图会话」=旧版识图
        // 链路，保持可见（识图例外）；to 在场但含「识图」同样保留
        // v2.49R1（复审1）：按行序回填 peerSent[真实agentId→to]——名字形态
        //（to='dev' 等）回传定位在历史重建态四锚 otherwise 全 miss：peerSent
        // 仅实时 tool_use 事件写入、历史段 hgSubr/pid 恒真实 agentId、无
        // data-hg-collab。键=行 result 提取的 resumedAgentId（与后端
        // _inject_subagent_blocks 注入 sub_open 段的 pid 同源同值）——回传
        // renderPeer 时锚②反查 to===name 即命中该段；id 形态（to 即
        // agentId）本有锚③兜，回填无害
        const _raid = String(l.result || '')
          .match(/resumedAgentId["':\s]+([0-9a-zA-Z_-]{8,64})/);
        if (_raid && l.input && l.input.to)
          (_HG.peerSent || (_HG.peerSent = {}))[_raid[1]] = l.input.to;
        const _rElH = renderPeerRelay((l.input && l.input.to) || '识图会话',
                        l.ts ? new Date(l.ts).getTime() : 0);
        if (_rElH && l.input && l.input.to && !String(l.input.to).includes('识图'))
          _rElH.style.display = 'none';
      }
      renderHistTool(l, hi);
    }
    // v2.43：子代理段行（transcript_for 注入的 sub_* 序列）——聚进段容器，
    // 段构建与实时路径同源（_subBlkGet 认回/新建，行级构建复用 _subText 等）
    else if (l.role === 'sub_open' || l.role === 'sub_text' || l.role === 'sub_think'
             || l.role === 'sub_tool' || l.role === 'sub_result' || l.role === 'sub_note') {
      renderHistSub(l, hi);
    }
    // v3.2.2：活动行 ts 后置入账——渲染中途的定稿（切组/审计）读到的是上一
    // 次活动（=被定稿组的末活动行），本行渲染完才成为新的「最近活动」
    if (_ts > 0 && l.role && l.role !== 'user') _HG.histActTs = _ts;
  }
  function renderHistSub(l, hi) {
    // 批3（迁出主窗）：renderHistSub 缩减——段建/行渲染退役（主窗零
    // .h-subblock），sub_* 过程行只消费 sub_open 做单行卡回绑；过程回看
    // =点单行卡走 subagent_replay（与 live 同路，天然一致）。后端注入不动
    //（数据保留，头150+尾50 窗口护栏已有）
    if (l.role === 'sub_open') {
      // v3.2.6：单行任务卡回绑——agentId/类型/描述落派发行（点击开窗格
      // 回放；lastAgRow 由 renderHistTool 登记且只活到本行）
      const _ar = _HG.lastAgRow;
      if (_ar && !_ar.dataset.hgSubr) {
        _ar.dataset.hgSubr = l.agent;
        _ar.dataset.hgSubType = l.type || 'Task';
        _ar.dataset.hgSubDesc = String(l.desc || '').slice(0, 120);
      }
      _HG.lastAgRow = null;
    }
  }
  function _histLazyLineOk(el, l) {
    if (!l) return false;
    const blk = el.closest('.h-subblock');
    if (el.classList.contains('h-think-seg'))
      return blk ? (l.role === 'sub_think' && l.agent === blk.dataset.hgSubblock)
                 : l.role === 'thinking';
    if (el.classList.contains('h-tool'))
      return blk ? (l.role === 'sub_tool' && l.agent === blk.dataset.hgSubblock)
                 : l.role === 'tool';
    return false;
  }
  function _histLazyFill(el) {
    if (!el) return;
    // v2.44：回填思考行（思考回填 _subBlkMergeThinks 产的壳）——正文在
    // dataset.raw，不在 histAll 账目里（无行号）。首展 renderMd、收起由
    // _histLazyDrop 清 body 重挂懒标，与 hi 路径同一对开合出口
    if (el.dataset.hgLazy === '1' && el.dataset.raw != null) {
      const body = el.querySelector('.h-think-seg-body');
      if (body && !body.children.length) {
        body.innerHTML = renderMd(el.dataset.raw);
        _codeLazyEnhance(body);
      }
      el.dataset.hgLazy = '';
      return;
    }
    if (el.dataset.hgLazy !== '1' || el.dataset.hi == null) return;
    const fill = () => {
      const l = _HG.histAll && _HG.histAll[+el.dataset.hi];
      if (!l) return;
      // v2.43.2（限制B）：点校验不符=该行 hi 已错位——弃填（清懒标防重试
      // 轰炸）+ 中性失效文案 + 非忙碌时整体重渲对账（唯一能重新对齐 hi 的路）
      if (!_histLazyLineOk(el, l)) {
        el.dataset.hgLazy = '';
        const nb = el.querySelector('.h-think-seg-body, .h-tool-coll');
        if (nb) nb.innerHTML = '<div class="hg-sub-replay-note">（本条内容已失效——历史结构已变化）</div>';
        if (!_HG.busy && _HG.histAll)
          _histRender(_HG.histAll, Math.max(0, Math.min(_HG.histStart | 0, _HG.histAll.length)));
        return;
      }
      try {
        if (el.classList.contains('h-think-seg')) {
          const body = el.querySelector('.h-think-seg-body');
          if (body && !body.children.length) {
            body.innerHTML = renderMd(l.text || '');
            _codeLazyEnhance(body);            // v2.24 懒高亮（点开即在视口，即刻触发）
          }
        } else if (el.classList.contains('h-tool')) {
          const coll = el.querySelector('.h-tool-coll');
          if (coll && !coll.children.length) coll.innerHTML = _histToolBodyHtml(l);
        }
        el.dataset.hgLazy = '';
      } catch(_) {}
    };
    if (!_HG.histAll) {
      // v2.25：快照恢复路径 histAll 为空（switchTo 切会话时清掉防串会话，
      // 而快照恢复不拉 transcript）——先拉数据再填。否则「已点开的段」切回
      // 来展开永远空白，点了也填不上（用户实测：早起会话的历史思考点不开）
      // v2.43.2（R2-缺口A）：拉取后先过前缀指纹/stale 哨兵——降级态（已确认
      // 漂移）或前缀不符时旧 DOM 的 hi 必错位，直接 fill 就是填错内容（与
      // 「绝不喂错位账目」口径一致）；不符→非忙碌重渲自愈，忙碌维持降级
      const sidAt = _HG.sid;
      _histFetch(sidAt).then(ok => {
        if (!ok || _HG.sid !== sidAt) return;
        const c = _HG.cache[sidAt] || {};
        if (c.histFp === 'stale'
            || (c.histFp != null && _histPrefixFp(_HG.histAll, _HG.histStart | 0) !== c.histFp)) {
          if (!_HG.busy) _histRender(_HG.histAll, Math.max(0, Math.min(_HG.histStart | 0, _HG.histAll.length)));
          else { _HG.histAll = null; _HG.histStale = true; }
          return;
        }
        fill();
      });
      return;
    }
    fill();
  }
  function _histLazyDrop(el) {
    // v2.44：dataset.raw（回填思考行）与 dataset.hi（历史行）都可丢可复原；
    // 两者皆无=流式内容，丢了无法恢复，不丢
    if (!el || (el.dataset.hi == null && el.dataset.raw == null)) return;
    try {
      if (el.classList.contains('h-think-seg')) {
        const body = el.querySelector('.h-think-seg-body');
        if (body) body.innerHTML = '';
      } else if (el.classList.contains('h-tool')) {
        const coll = el.querySelector('.h-tool-coll');
        if (coll) coll.innerHTML = '';
      }
      el.dataset.hgLazy = '1';
    } catch(_) {}
  }
  function _histToolBodyHtml(l) {
    // v3.2.25（用户实锤「历史回放看不到改动」）：折叠工具行的输入体与
    // live 同构（Edit 的 old→new diff / Write 的写入内容 / Todo 等，
    // _toolInputBodyHtml + cfg.get 同一路）——此前只画「成功」结果行，
    // Write/Edit 回放全是 File created/updated successfully 一行字
    let inputHtml = '';
    try {
      const cfg = _hCfg(l.text);
      const v = cfg.get ? cfg.get(l.input || {}) : '';
      // v3.5.336：转写行权威行号直传（Edit 单处）——重建路径零回填零竞态
      if (l.dln && Array.isArray(l.dln) && l.dln[0] && v && typeof v === 'object'
          && l.text === 'Edit') v.dln = l.dln[0];
      inputHtml = _toolInputBodyHtml(cfg, v);
    } catch(_) {}
    const out = l.result ? String(l.result) : '';
    return (l.summary ? `<div class="h-tool-arg">${esc(l.summary)}</div>` : '') +
      inputHtml +
      (out ? `<div class="h-tool-out${l.err ? ' err-txt' : ''}">${esc(out.length > 4000 ? out.slice(0, 4000) + '…' : out)}</div>` : '');
  }
  function isNearBottom() {
    return _hgFlow.scrollHeight - _hgFlow.scrollTop - _hgFlow.clientHeight < 120;
  }
  function _hgHistWinStart(lines) {
    // v3.4.59（用户实锤「A切B切A，A 的工作全不显示，不刷出新消息就一直不显示」）：
    // 尾部窗口起点必须含**最后一个 user 行**（回合边界）——大回合（审计类一轮
    // 数百行）按 HIST_PAGE 取尾会把 user 行切在窗口外：窗口内只剩无归属的工作
    // 行（sub 行段头在窗口外）=页面近乎空白，直到新事件刷出才恢复
    const n = lines.length;
    let start = Math.max(0, n - _HG.HIST_PAGE);
    // 全量回扫：最后一个 user 行可能是数百行之前（大回合），窗口内没有
    // user 行时必须继续往前——回合完整性优先于窗口大小
    for (let i = n - 1; i >= 0; i--) {
      if (lines[i] && lines[i].role === 'user' && String(lines[i].text || '').trim()) { start = i; break; }
    }
    return Math.max(0, start);
  }
  function _hgPrevRowAt() {
    // v3.3.1：上一 SSE 事件到达时刻（10-sse onmessage 入账）——思考段起点
    // 的挂钟基准。30s 新鲜度护栏：太久（空闲后偶发段）回退当下时刻，
    // 宁可缺数也不虚增时长
    const _p = +(_HG.prevRowAt || 0);
    return (_p && Date.now() - _p < 30000) ? _p : Date.now();
  }
  function startThinking(hist) {
    if (_HG.think && _HG.think.seg && _HG.think.seg.isConnected) return;
    // v3.2.13（用户实锤「没修复好」）：思考行不再断查阅组——思考间隔前后的
    // 查阅并入同一组（对照 ZCode 组跨思考累积；断组只留写类工具/正文）。
    // 思考段照常按发生顺序挂在组之后，后续查阅回填进组体
    const g = grpEnsure(true);
    // v3.5.190（用户实锤「AI工作中的气泡没了」推翻 v3.2.29）：思考行不让位——
    // 「AI 正在思考中…」气泡保留到正文到达（renderAssistant phRemove），
    // 过程行期间气泡与时间线并存（对照 ZCode 形态）

    // v3.2.4（用户实锤「以前有思考和工具调用顺序的，现在没顺序了」）：思考段
    // 作为**行**挂进工具时间线——思考段↔工具行按发生顺序交替排列（对照
    // ZCode 回合过程区的时序流）。汇总胶囊（🧠 思考 N 次）退役为隐藏容器
    // （segCount 统计与 grpFromDom 认回判据仍依赖它）；旧结构组（v3.1 快照
    // 无 .h-tl）回落旧抽屉形态
    const _toTl = !!g.tl;
    if (!_toTl) g.think.box.style.display = '';   // 旧组：第一段思考到位，思考抽屉翻回显示
    if (!hist) _turnHeadShow(g);                // v3.2：纯思考回合也亮「工作中」秒表（回放不亮——定稿时直接冻结文案）
    const n = thinkSegCount(g) + 1;
    thinkSegCountSet(g, n);
    // 组头：「思考 N 次」；流式中带脉动动画，历史重建（hist）静态——
    // v2.20 修复：旧代码无条件加 anim，而定稿/重建后没人摘，已完成的会话
    // 组头还在闪（用户实测）。定稿侧 grpFinalize 也会重写为纯文本兜底。
    if (g.think.title) g.think.title.innerHTML = hist
      ? '🧠 思考 ' + n + ' 次'
      : '🧠 思考 <span class="hg-think-anim">' + n + ' 次</span>';
    const seg = document.createElement('div');
    // v2.24 懒抽屉：历史段默认收起（点开才渲染正文）；流式段保持展开
    // v3.2.19（用户定调「执行过程中默认不展开」）：实况思考段也默认收起
    // （原 live 生而 open，长思考流式撑满屏；头上的秒表/「思考中」照跑，
    // 点击照常展开，回放态本就收起）
    seg.className = 'h-think-seg';
    if (!hist) {
      // v3.1h（用户实锤「发出后半天没消息也应算思考」）：第一段思考起点回溯
      // 到回合起点（=消息发出时刻），静默等待期计入思考时长；后续段仍取当下
      seg.dataset.t0 = String((n === 1 && g.t0) ? g.t0 : _hgPrevRowAt());
      seg.dataset.n = String(n);
    }
    seg.innerHTML =
      `<button class="h-think-seg-head"><span class="h-chev">▸</span>` +
      `<span class="h-think-seg-name">🧠 思考</span>` +
      `<span class="h-think-seg-t" data-hg-seg-t data-hg-think-t></span>` +
      `<span class="h-think-dot">·</span>` +
      `<span class="h-think-prev" data-hg-think-prev></span></button>` +
      `<div class="h-think-seg-body"></div>` +
      // v2.21：段尾右下角收起钮——长思考读到尾顺手收，不用滚回顶部点头
      `<i class="h-think-seg-fold" title="收起本段">收起 ⌃</i>`;
    if (_toTl) {
      g.tl.appendChild(seg);                 // v3.2.4：时间线行——与工具行同序
      g.tl.style.display = '';
    } else {
      g.think.body.appendChild(seg);
    }
    _HG.think = { seg, grp: g };
    _turnHeadSubPaint(g);                    // v3.2.4：头副位补思考计数（· N 思考 · M 工具）
    if (!_toTl) {
      // 旧组抽屉形态：本组还没正文 → 抽屉保持展开 + 段计时动画
      if (!_grpHasAsst()) {
        if (!hist && g.think.box.dataset.userToggled !== '1') g.think.box.classList.add('open');
        if (!hist) thinkHeadUpdate();
      } else if (!hist) {
        segHeadUpdate(seg);
      }
    } else if (!hist) {
      thinkHeadUpdate();                     // 时间线形态：段计时照走（「思考中…」/时长）
    }
  }
  function _grpHasAsst() {
    const g = _HG.grp;
    return !!(g && g.root && g.root.querySelector(':scope > .h-msg.asst'));
  }
  function thinkHeadUpdate() {
    const t = _HG.think;
    if (!t || !t.seg.isConnected) return;
    if (!_grpHasAsst()) {
      const te = t.seg.querySelector('[data-hg-think-t]');
      if (te) { te.innerHTML = '<span class="hg-think-anim">思考中…</span>'; }
    } else segHeadUpdate(t.seg);
  }
  function segHeadUpdate(seg) {
    const te = seg && seg.querySelector('[data-hg-think-t]');
    if (!te) return;
    const t0 = +(seg.dataset.t0 || 0);
    te.textContent = t0 ? _hgFmtDur((Date.now() - t0) / 1000) : '';
  }
  function appendThinking(text) {
    if (!_HG.think || !_HG.think.seg.isConnected) startThinking();
    const seg = _HG.think.seg;
    const holder = seg.querySelector('.h-think-seg-body');
    // v3.0 双渲染路径（对照 ZCode reasoning.tsx:555 注释——thought 流式追加
    // 时每块跑 Markdown 解析会随字数越来越卡）：流式期间纯文本 textNode
    // O(1) 追加（.hg-think-plain 的 pre-wrap 保换行），endThinking 定稿时
    // 一次性 renderMd 升级替换（升级失败 catch 保留纯文本，展示不中断）。
    holder.classList.add('hg-think-plain');
    holder.appendChild(document.createTextNode(text));
    // 思考流③（ZCode reasoning.tsx 复刻·流水式）：摘要视口=最后非空行
    // **完整文本**（内 span min-w-max 不压缩），内容超宽后 scrollLeft=
    // scrollWidth 推到末尾——旧内容向左移、最新 token 恒可见（流水感），
    // 两侧 16px 渐隐 mask（:242-283 scrollReasoningSummaryToEnd 同款）；
    // 完成态摘要清空（endThinking）只留「🧠 思考 持续了 N 秒」贴排
    {
      const prev = seg.querySelector('[data-hg-think-prev]');
      if (prev) {
        const ls = holder.textContent.split('\n');
        let last = '';
        for (let i = ls.length - 1; i >= 0; i--)
          if (ls[i].trim()) { last = ls[i].trim(); break; }
        if (last) {
          prev.innerHTML = '';
          const sp = document.createElement('span');
          sp.textContent = last;
          prev.appendChild(sp);
          prev.scrollLeft = prev.scrollWidth;   // 流水推尾（ZCode 滚动机制）
        }
      }
    }
    thinkHeadUpdate();
    _hgScrollBottom();
  }
  function _hgFmtDur(sec) {
    // v2.3 问题3：h/m/s 分级显示（>1h 用 h m，>1min 用 m s，否则 s）
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm' + (sec % 60 ? sec % 60 + 's' : '');
    return Math.floor(sec / 3600) + 'h' + Math.floor((sec % 3600) / 60) + 'm' + (sec % 60 ? sec % 60 + 's' : '');
  }
  function endThinking(hist) {
    const t = _HG.think;
    if (!t) return;
    _HG.think = null;
    const seg = t.seg;
    // 思考流③（ZCode 完成态）：摘要视口清空——:empty 隐藏后时长回贴
    //「🧠 思考 持续了 N 秒」整串贴排（reasoning.tsx:335-360 完成态无摘要行）
    const prev0 = seg.querySelector('[data-hg-think-prev]');
    if (prev0) prev0.textContent = '';
    // v3.0：定稿升级——流式期间攒的纯文本段一次性渲染成 Markdown（历史
    // 路径 body 本就是 md，无 plain 类零开销直通；升级失败保留纯文本）
    const body = seg.querySelector('.h-think-seg-body');
    if (body && body.classList.contains('hg-think-plain')) {
      try {
        const raw = body.textContent;
        body.classList.remove('hg-think-plain');
        body.innerHTML = renderMd(raw);
        if (_HG.histAll) _codeLazyEnhance(body); else codeBlockEnhance(body);
      } catch(_) {}
    }
    const te = seg.querySelector('[data-hg-think-t]');
    const t0 = +(seg.dataset.t0 || 0);
    if (hist || !t0) {
      // 历史重建：无真实起始时间，不编造时长
      if (te) te.textContent = hist ? '' : te.textContent;
    } else {
      // v3.1：定稿文案对齐 ZCode（「思考 · 持续了 7 秒」）——计数态 Ns → 持续了 Ns
      // v3.3.1：<3s 原本不显示（切片噪声护栏）；v3.4.44（用户定调）：太短的
      // 段落一片空白更怪——兜底 ZCode 同款模糊文案「持续了一小会」
      const _ms = Date.now() - t0;
      if (te) te.textContent = _ms >= 3000 ? '持续了 ' + _hgTurnDurTxt(_ms) : '持续了一小会';
      // 仅当用户没碰过且在底部跟读时自动收段（正文已在段里，收起只留段头）
      if (seg.dataset.userToggled !== '1' && isNearBottom()) seg.classList.remove('open');
    }
  }
