// harness hist.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function renderHistTool(l, hi) {
    // v3.2.6（ZCode 子智能体模式）：历史 Agent/Task 派发行走单行任务卡工厂
    //（与 live 同解剖：🤖 子智能体 + 类型 chip + 描述 + ▣/点击开窗格），无
    // 展开体；登记 lastAgRow 供紧随其后的 sub_open 行回绑 agentId（转写注入
    // 保证 sub_open 紧贴派发行，隔行即失效——见 renderHistLine 顶部清账）
    if (((_H_TOOL_CFG[l.text] || {}).kind) === 'agent') {
      const _inp = l.input || {};
      const _err = !!l.err;
      const d = _hgAgentRowBuild('ag' + (hi != null ? hi : 'r' + (++_HG.uidN)),
        _inp.subagent_type || _inp.agent_type || l.text,
        _inp.description || '');
      if (_err) d.classList.add('err');
      const st = d.querySelector('.h-tslots');
      if (st) st.innerHTML = statusBadge(_err ? 'error' : 'completed');
      d.dataset.hgAgline = '1';
      _HG.lastAgRow = d;
      drawerCount(l.text);
      _tlPlace(d, l.text, _inp);
      return d;
    }
    // v2.15：与 renderToolUse 的 collapsible 分支同构的结构
    // （.h-tool.col > .h-tool-head[.h-tslots] + .h-tool-coll）。
    // v2.24 懒抽屉：正常行 body 不渲染（dataset.hi 记行号，点开 _histLazyFill
    // 现填）；错误行保持立即渲染+默认展开（错误信息不该藏）。
    const d = document.createElement('div');
    const err = !!l.err;
    // v3.2.26（用户实锤「要展开才能看，凭什么？」）：defaultOpen 类工具
    // （Edit/Write/MultiEdit——改动本体）历史回放生而展开+同步填体——
    // 改动不许藏在折叠里；错误行维持立即渲染（错误信息不该藏）
    const _dOp = !!((!err && _H_TOOL_CFG[l.text] || {}).defaultOpen);
    d.className = 'h-tool col' + (err ? ' err' : '') + (_dOp ? ' open' : '');
    // v2.21：历史回放同样带工具徽章（子代理等），与流式路径一致
    const hbc = _H_TOOL_CFG[l.text] || {};
    // v3.2.1（用户实测问题2）：bash 行头补命令文本——live 行有 arg（cfg.get），
    // 回放行只剩「Bash」秃头，无命令像坏行。对齐 live 取 command 前 80 字，
    // title 悬浮放全文（80 字外被 CSS 省略号截断，段内工厂 _subToolHeadHtml
    // 同款口径——对抗审计 F3）
    const _cmdFull = String((l.input || {}).command || (l.input || {}).cmd || '');
    const argH = (hbc.kind === 'bash') ? esc(_cmdFull.slice(0, 80)) : '';
    const argTitle = (hbc.kind === 'bash' && _cmdFull) ? esc(_cmdFull) : '';
    d.innerHTML =
      `<button class="h-tool-head"><span class="h-chev">▸</span>` +
      `<span class="h-tool-name">${_hToolIco(l.text)} ${esc(_hToolLabel(l.text))}</span>` +
      (hbc.badge ? `<span class="h-tool-badge">${esc(hbc.badge)}</span>` : '') +
      (argH ? `<span class="h-tool-arg"${argTitle ? ` title="${argTitle}"` : ''}>${argH}</span>` : '') +
      `<span class="h-tslots">${statusBadge(err ? 'error' : 'completed')}</span></button>` +
      `<div class="h-tool-coll">${(err || _dOp) ? _histToolBodyHtml(l) : ''}</div>`;
    if (hi != null) {
      d.dataset.hi = String(hi);
      d.dataset.hgLazy = (err || _dOp) ? '' : '1';   // 错误行/defaultOpen 行已填（hgLazy 空）；收起丢弃后由 Drop 重置
    }
    if (((_H_TOOL_CFG[l.text] || {}).kind) === 'bash') d.classList.add('oneclick');
    drawerCount(l.text);
    _tlPlace(d, l.text, l.input || {});   // v3.2：回放同走内联时间线（查阅聚组与实时一致）
    // v3.2.1：撤 _hgApplyOpen 位置键恢复——错误行默认开已由 className 的
    // 'err open' 承担；位置键跨代际碰撞会误开正常行+误标 userToggled（用户
    // 实锤「终端默认全部不收起」），统一默认收起（用户定调）
  }
  function renderHistLine(l, hi) {
    // v3.2.2（用户实测「没显示工作时长」）：行级 ts 账——histLineTs=当前行
    // （grpEnsure 给切分组取段起点）；histActTs=最近一次非 user 活动（定稿
    // 取段终点：中段切组在渲染中途读 histActTs 恰为被定稿组末活动行；回放
    // 尾组定稿在循环外读=全段末活动）。旧转写缺 ts 保持 0——落无数字形态
    const _ts = l && l.ts ? Date.parse(l.ts) : 0;
    if (_ts > 0) _HG.histLineTs = _ts;
    // v3.2.5（用户定调「思考持续了几秒，和 ZCode 同款」）：回放思考段时长
    // ——思考行的 ts 为起点，下一条带 ts 的行到达时定格差值（转写无段级
    // 终点事实，邻行 ts 差是唯一诚实口径；后置入账同款时序：本行渲染前
    // 先收上一段的账）
    if (_HG.thinkPend && _ts > 0 && _ts > _HG.thinkPend.t0) {
      const _tp = _HG.thinkPend;
      const _te = _tp.seg.isConnected ? _tp.seg.querySelector('[data-hg-think-t]') : null;
      if (_te) _te.textContent = '持续了 ' + _hgTurnDurTxt(_ts - _tp.t0);
      _HG.thinkPend = null;
    }
    // v3.2.6：lastAgRow 只活一行——sub_open 紧贴 Agent 派发行（transcript 注
    // 入序铁律），其余任何行到达即清（防隔行错绑到更早的 Agent 行）
    if (l.role !== 'sub_open') _HG.lastAgRow = null;
    if (l.role === 'peer') {          // v2.27.3：跨会话回传（识图结论）历史回看
      // v2.53：第 5 参 hist——历史回放绝不开新段（防假「协作·运行中」段吞正文）
      renderPeer(l.name, l.text, null, true, true);
    }
    else if (l.role === 'vision_relay') {  // v2.28：识图 MCP 转交线（历史回看）
      renderVisionRelayHist(l);
    }
    else if (l.role === 'renew') {    // v2.27.23：超窗续命注入折叠为一行分割线
      // v3.2.4R(F3)：对齐 live（10-sse renew 分支先定稿）——不定稿则分割线落
      // flow 尾、同回合续内容仍进组根，回放时序倒挂
      grpFinalize(true, { hist: true, endTs: _HG.histActTs || 0 });
      renderRenew(l.text);
    }
    else if (l.role === 'audit') {    // v2.34：审计警示卡回放（v2.34.1 与实时同文本，
      grpFinalize(true, { hist: true, endTs: _HG.histActTs || 0 });   // 由 audit log 并入；对齐实时分支先定稿上一组（v3.2R1(P0)：回放不吃时钟；v3.2.2 段末 ts）
      renderAudit(l.text);            // 否则纯工具收尾回合的补审卡会挂错进前组）
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
        renderUser(l.text, imgs, files, false, l.ts ? new Date(l.ts).getTime() : 0);
      }
    }
    else if (l.role === 'assistant') renderAsst(l.text, l.model || _HG.model || '');
    else if (l.role === 'thinking') {
      // v2.24 懒抽屉：历史思考段只建壳（默认收起），点开才渲染 markdown——
      // 大会话重建的大头就是几十 K 字符的 thinking 渲染
      startThinking(true);                 // 重建路径：段结构同流式，无计时动画
      const _segEl = _HG.think && _HG.think.seg;
      if (_segEl && hi != null) {
        _segEl.dataset.hi = String(hi);
        _segEl.dataset.hgLazy = '1';
      } else appendThinking(l.text);       // 兜底：无行号（理论不达）
      endThinking(true);                   // hist 模式：不自动收；时长见下方 pend
      if (_segEl && _ts > 0) _HG.thinkPend = { seg: _segEl, t0: _ts };
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
    const pid = l.agent;
    if (l.role === 'sub_open') {
      const b = _subBlkGet(pid, { agent: pid, type: l.type, desc: l.desc || '',
        label: _AGENT_LABEL[l.type] || l.type || '子代理', model: l.model || '',
        done: true, err: !!l.err, hist: true });   // v2.44：hist——段头显「历史」不算假用时
      // v3.2.6：单行任务卡回绑——agentId/类型/描述落派发行（点击/▣ 开窗格
      // 回放；lastAgRow 由 renderHistTool 登记且只活到本行）
      const _ar = _HG.lastAgRow;
      if (_ar && !_ar.dataset.hgSubr) {
        _ar.dataset.hgSubr = pid;
        _ar.dataset.hgSubType = l.type || 'Task';
        _ar.dataset.hgSubDesc = String(l.desc || '').slice(0, 120);
      }
      _HG.lastAgRow = null;
      if (b) {
        // v2.46：折叠态按记忆恢复（重建期 openState 在场；无记录=默认折叠不
        // 动）——用户展开过的段不随扩段/收缩重渲收回（高度突变破坏锚定）
        const _ost = _HG.openState;
        if (_ost && _ost['sub:' + pid] === 1) b.root.classList.remove('collapsed');
      }
      if (b && l.stub) {
        const n = document.createElement('div');
        n.className = 'h-subblock-note';
        n.textContent = '（较早期的子代理段——过程行已折叠；完整过程点段头右侧「▣ 回放」）';
        b.body.appendChild(n);
      }
      return;
    }
    const b = _HG.subBlk && _HG.subBlk[pid];
    if (!b || !b.body || !b.root.isConnected) return;   // 无段头先导（异常序列）——静默丢行不出错
    if (l.role === 'sub_text') {
      _subText(pid, l.text || '');
    } else if (l.role === 'sub_note') {
      const n = document.createElement('div');
      n.className = 'h-subblock-note';
      n.textContent = l.text || '';
      b.body.appendChild(n);
    } else if (l.role === 'sub_think') {
      // 同主链历史思考段：壳+懒渲染（点开才 renderMd，大会话重建不吃满）
      _subSegEnd(b);
      const seg = _subThinkShell(false);
      if (hi != null) { seg.dataset.hi = String(hi); seg.dataset.hgLazy = '1'; }
      _subBodyPut(b, seg, 'think');   // v2.45：历史段建段即聚合——落思考抽屉
    } else if (l.role === 'sub_tool') {
      // 与 renderHistTool 同构（懒抽屉/错误行即时渲染），但落点=段体且不进
      // 主链抽屉计数（drawerCount/drawerAppend 都不走）。v2.44 头部走段内
      // 工厂 _subToolHeadHtml——与实时抽屉行（_subToolDrawerRow）字节级同构
      _subSegEnd(b);
      const d = document.createElement('div');
      const err = !!l.err;
      d.className = 'h-tool col sub' + (err ? ' err' : '');   // v3.2.5：同主链——只标红
      // v2.44R（复审建议）：类别着色与实时抽屉一致（旧版历史段行无
      // --h-accent，左边框全灰与实时段内彩色左边框两套观感）
      d.style.setProperty('--h-accent',
        _H_KIND_COLOR[(_H_TOOL_CFG[l.text] || {}).kind] || 'var(--border)');
      d.innerHTML =
        _subToolHeadHtml(l.text, l.summary, statusBadge(err ? 'error' : 'completed')) +
        `<div class="h-tool-coll">${err ? _histToolBodyHtml(l) : ''}</div>`;
      if (hi != null) {
        d.dataset.hi = String(hi);
        d.dataset.hgLazy = err ? '' : '1';   // 错误行已填；收起丢弃后由 Drop 重置
      }
      _subBodyPut(b, d, 'tool');   // v2.45：历史段建段即聚合——落工具抽屉
      // v3.2.1：撤位置键开合恢复（同 renderHistTool——错误行默认开已由
      // className 'err open' 承担；位置键跨代际碰撞误开+误标 userToggled）
    } else if (l.role === 'sub_result') {
      // 孤儿结果（无配对工具行——转写截断窗口的边界）独立成行
      _subSegEnd(b);
      const d = document.createElement('div');
      d.className = 'h-tool-res' + (l.err ? ' err-txt' : '');
      d.textContent = '↳ ' + String(l.text || '').replace(/\s+/g, ' ').trim().slice(0, 200);
      _subBodyPut(b, d, 'tool');   // v2.45：孤儿结果同入工具抽屉（计数口径一致）
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
        if (nb) nb.innerHTML = '<div class="h-subblock-note">（本条内容已失效——历史结构已变化）</div>';
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
  function startThinking(hist) {
    if (_HG.think && _HG.think.seg && _HG.think.seg.isConnected) return;
    // v3.2.13（用户实锤「没修复好」）：思考行不再断查阅组——思考间隔前后的
    // 查阅并入同一组（对照 ZCode 组跨思考累积；断组只留写类工具/正文）。
    // 思考段照常按发生顺序挂在组之后，后续查阅回填进组体
    const g = grpEnsure(true);
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
      seg.dataset.t0 = String(Date.now());   // hist：无真实起始时间，不存不编造
      seg.dataset.n = String(n);
    }
    seg.innerHTML =
      `<button class="h-think-seg-head"><span class="h-chev">▸</span>` +
      `<span class="h-think-seg-name">🧠 思考</span>` +
      `<span class="h-think-seg-t" data-hg-seg-t data-hg-think-t>0s</span></button>` +
      `<div class="h-think-seg-body"></div>` +
      // v2.21：段尾右下角收起钮——长思考读到尾顺手收，不用滚回顶部点头
      `<i class="h-think-seg-fold" title="收起本段">收起 ⌄</i>`;
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
      if (te) te.textContent = '持续了 ' + _hgTurnDurTxt(Date.now() - t0);   // v3.2.5：中文时长口径（N 秒/N 分 N 秒）
      // 仅当用户没碰过且在底部跟读时自动收段（正文已在段里，收起只留段头）
      if (seg.dataset.userToggled !== '1' && isNearBottom()) seg.classList.remove('open');
    }
  }
