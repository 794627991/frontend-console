// harness histcache.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  // ===== 单账游标制（394 终态）：唯一写入+唯一渲染 =====
  // live 消息行不再直改 DOM——构造行 append 进唯一账 histAll，游标泵渲染
  //（renderHistLine→dispatch→renderEntries，与 hist 同一管线 R1 成果）。
  // DOM=账的 [histStart, cursor) 呈现；fetch 重建账后 pump 只渲染差量
  //（前缀一致性：后端落盘序=事件序，live 行被 fetch 版同位吸收）
  function _hgRowAdd(row) {
    if (!row || !row.role) return;
    if (!Array.isArray(_HG.histAll)) _HG.histAll = [];
    row._sq = _HG.seq || 0;   // 398-P5：入账事件 seq（fetch 重建时未落盘行拼接判据）
    _HG.histAll.push(row);
    _HG.histDirty = true;   // 398-P3：live 账期标脏——工具行不入账（设计3）使 live 账
                            // 下标与转写版结构性错位，长度比较不可作对齐判据；
                            // 脏账期间的 fetch 走整窗校正（_histRefresh 守卫消费）
    _histPump();
  }
  function _histPump() {
    if (!_HG.histAll || _HG.histBuilding || _HG.readonly) return;
    if (!_HG.histLive) _HG.histLive = true;   // live 建账即建立 DOM/账对应（扩收放行）
    const from = Math.max(_HG.histCursor || 0, _HG.histStart || 0);
    for (let i = from; i < _HG.histAll.length; i++) {
      try { renderHistLine(_HG.histAll[i], i); }
      catch (e) { try { console.error('[harness] pump line failed @' + i, e); } catch (_) {} }
    }
    _HG.histCursor = _HG.histAll.length;
  }
  // 399-R3 抽函数：fetch 版与旧账合并——保住「已入账未落盘」的 live 行
  //（SSE 事件先于 jsonl flush 的毫秒窗）；user 行按文本精确去重防双拼
  function _hgMergeLive(lines, old, fs) {
    if (!Array.isArray(lines) || !Array.isArray(old) || lines === old) return lines;
    fs = fs || _HG.fetchedSeq || 0;
    const seenUser = new Set(lines.filter(l => l && l.role === 'user')
      .map(l => String(l.text || '')));
    for (const l of old) {
      if (!l || !l._sq || l._sq <= fs) continue;
      if (l.role === 'user' && seenUser.has(String(l.text || ''))) continue;
      lines.push(l);
    }
    return lines;
  }
  function _histRender(lines, start, opt) {
    // 398-P5a→399-R3：未落盘行保尾（抽 _hgMergeLive，fetch 赋值处同用）
    lines = _hgMergeLive(lines, _HG.histAll, _HG.fetchedSeq);
    // v3.5.8（用户实锤「A 切 B 再切 A，识图中显示历史未完成」）：渲染期
    // busy 标志——noFinalize 正是调用方的 !!j.busy（busy 活会话）。识图卡
    // 回放据此把未回传卡复活为「识图中」（run 态+续表），不再误判死案
    _HG.histBusy = !!(opt && opt.noFinalize);
    _HG.lastTs = 0;   // v2.24.5：重建期时间条从零起算（第一条 user 带时间）
    // R1（流式/重渲统一）：重放前投影行级模型清零——hist 的 renew/audit 等
    // 行走 dispatch 进 entries，游标重置后随渲染循环重画（不清=F5 后游标
    // 已在尾、杂项行全部消失）
    if (_HG.proj) { _HG.proj.entries = []; }
    if (typeof _hgEntryCursorReset === 'function') _hgEntryCursorReset();
    // v3.5.193（用户定调「主窗口本身就限制 20 回合，至于全量渲染吗；重渲染
    // 效果比流式好」）：渲染窗口=最近 TURN_N=20 回合（从尾回扫数 user 行，
    // 第 21 个 user 行=窗口起点天然对齐回合头；不足 20 回合全渲）——与
    // _trimOldTurns 的 20 轮语义对齐：DOM 输出与「全量渲染后裁到 20 轮」
    // 完全一致（归档条+尾部 20 轮），渲染量降 ~96%（千行会话 2.1 万次
    // ParseHTML→约 800 次，DevTools Profiler 实锤切回重渲为卡顿大头）。
    // 超出部分走既有只读归档（归档条 hg-ro-enter）；v3.5.178 首试败于
    // capStart 误删，本次保留 capStart 语义规避
    if (_HG.readonly || (opt && opt.full)) {
      // v3.5.206b（用户实锤「只读模式出问题了」）：RO 全量渲染语义保留——
      // 窗口化（v3.5.191 TURN_N=20）误伤只读：RO_view 传的 start=0 被窗口
      // 计算覆盖成尾部 20 回合+自插归档条（RO 里点归档条又进 RO=死循环观感，
      // 且 193 轮历史看不见）。RO 恒 start=0 全渲（v3.5.62 只读=看全量的
      // 既有定调），归档条自插仅 start>0 时天然不触发
      start = 0;
    } else {
      const TURN_N = 20;
      start = lines.length;
      let _tn = 0;
      for (let i = lines.length - 1; i >= 0; i--) {
        start = i;
        const l = lines[i];
        if (l && l.role === 'user' && String(l.text || '').trim()) {
          _tn++;
          if (_tn > TURN_N) break;   // 第 21 个 user 行 = 窗口起点（含该回合）
        }
      }
      start = Math.max(0, start);              // 全扫不满 20 回合 → 全渲
      start = Math.min(start, lines.length);   // v2.37R2（复审4）：上界钳制——账目越界时 slice 为空只剩错误计数
    }
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
    // v3.5.196：不再预清 flow——buf 渲染期旧 DOM 保留在屏（消除白屏），
    // replaceChildren 原子换入即整替（预清与换入语义重复且制造空窗）
    // 归档提示条：窗口化渲染（v3.5.193）时由本渲染器自插（start>0=有归档轮，
    // 见窗口起点计算）；trim 兜底 live 追加路径
    if (!lines.length) {
      // v3.2.11：游离缓冲期早退必须先归还 _hgFlow 引用（否则全后续渲染
      // 都写进游离容器——主界面消失级事故）
      _HG.histCursor = 0;   // 399-加固（审 N1 备注）：空账早退游标归零（残留值>账长=下次 rowAdd 行不渲）
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
if (l && l.live) l.live = 0;   // 398-P5b：重放归一（live 动画/流式语义只在泵路径，整窗重放=回放形态）
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
        // v2.32 面板：回放重建最近的子代理条目（doneAt 带行 ts，目录显相对
        // 时间；不参与 sweep；留最近 50 条防长会话堆积）
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
            type: _typ, desc: _desc, t0: 0, done: true,
            doneAt: l.ts ? (Date.parse(l.ts) || 0) : 0, replay: true,
            agentId: _aid });
          if (d.agentsRpl.length > 50) d.agentsRpl.shift();
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
                type: 'SendMessage', desc: (typeof _peerDesc === 'function' ? _peerDesc((l.input || {}).to, _msg) : (_msg || '')),
                t0: 0, done: true, doneAt: l.ts ? (Date.parse(l.ts) || 0) : 0,
                replay: true, agentId: _ra });
              if (d.agentsRpl.length > 50) d.agentsRpl.shift();
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
        // C组G3：busy 判据统一——noFinalize（fetchedBusy 真值）优先，_HG.busy
        // 兜底（events poll 未回填的竞态窗内陈旧 false 曾让活组被误收体+删占位）
        if (((opt && opt.noFinalize) || _HG.busy) && i === _grps.length - 1) return;
        const tb = gp.querySelector(':scope > .h-grp-proc > .h-turn-body');
        if (tb) tb.classList.add("closed");
        const ph = gp.querySelector(":scope > .h-msg.asst.ph");
        if (ph) ph.remove();
      });
      // v3.5.226（用户最后通牒「头没了立刻根治」）：活组头**渲染器当场亮**——
      // 不再依赖 phResume 事后补（其 thinkBox 早退分支让无思考段的活组头
      // 永不亮=15:03 复现形态）。busy 真值=noFinalize（调用方传 fetchedBusy
      // 后端真值）；t0 取 head.dataset.t0（renderUser 已写行 ts）；秒表
      // interval 自杀守卫+挂 turnTicks 清场链
      if (opt && opt.noFinalize && _grps.length) {
        const _lg = _grps[_grps.length - 1];
        const _lh = _lg.querySelector(':scope > .h-grp-proc > .h-turn-head');
        if (_lh && _lh.style.display === 'none') {
          _lh.style.display = '';
          const _lbl = _lh.querySelector('.h-turn-label');
          const _t0 = +(_lh.dataset.t0 || 0);
          if (_lbl && _t0) {
            _lbl.textContent = '工作中 ' + _hgFmtDur((Date.now() - _t0) / 1000);
            // v3.5.228（用户实锤「工作中不结束了」）：interval 每跳自查组
            // 定稿态——定稿即停表退出（游离 interval 每秒覆写 label=已定稿
            // 回合永远挂「工作中」）。定稿由 grpFinalize 落 dataset.finalized
            const _tm = setInterval(() => {
              const _gp = _lh.closest('.h-grp');
              if (!_lh.isConnected || !_gp || _gp.dataset.finalized) {
                clearInterval(_tm); return;
              }
              _lbl.textContent = '工作中 ' + _hgFmtDur((Date.now() - _t0) / 1000);
            }, 1000);
            (_HG.turnTicks || (_HG.turnTicks = [])).push(_tm);
          }
        }
      }
      // v3.1h（用户定调）：回滚只属最后一条 AI 消息——各回合尾条都带了
      // can-rewind，收敛为只留全局最后一条
      const _allAsst = _realFlow.querySelectorAll('.h-msg.asst.can-rewind');
      _allAsst.forEach((m, i) => { if (i < _allAsst.length - 1) m.classList.remove("can-rewind"); });
      _HG.histBuilding = false;   // v3.2.13：连接性判据还原（见顶部注释）
      _HG.histBusy = null;        // v3.5.8：busy 标志随渲染收尾还原
      // v3.5.175（用户实锤「只读模式点击进不去了」）：渲染路径也走一次回合
      // 裁剪——恒全量渲染把全部 .h-grp 画进 flow，而 _trimOldTurns（>20 轮
      // 删旧组+插「前 N 轮已归档」条）此前只在 live 发消息路径（renderUser
      // 回合边界）跑，切会话/重渲渲染后归档条缺席=无条可点。trim 在游离
      // 缓冲换入完成之后跑（操作活 flow DOM）；删头组影响回合导航轨，补
      // 一次 sync
      // v3.5.193：窗口化渲染（start>0=窗口外有归档轮）时顶部插归档条——
      // 与 04-groups _trimOldTurns 的归档条同款同事件（hg-ro-enter 进只读）；
      // 窗口内 ≤20 轮，trim 已无活干，条由渲染器负责
      if (start > 0) {
        let totalTurns = 0, winTurns = 0;
        for (const l of lines)
          if (l && l.role === 'user' && String(l.text || '').trim()) totalTurns++;
        for (let i = start; i < lines.length; i++)
          if (lines[i] && lines[i].role === 'user' && String(lines[i].text || '').trim()) winTurns++;
        const archived = totalTurns - winTurns;
        if (archived > 0) {
          const hint = document.createElement('div');
          hint.className = 'h-archive-hint';
          hint.innerHTML = '⬆ 前 ' + archived + ' 轮已归档——点击进入只读模式查看';
          hint.style.cursor = 'pointer';
          hint.onclick = () => document.dispatchEvent(new CustomEvent('hg-ro-enter'));
          _realFlow.insertBefore(hint, _realFlow.firstChild);
        }
      }
      // 399-R1（复审实锤：398 删对齐行=整窗后尾泵把 [start,len) 双渲追加，
      // 冷开/切会话/自愈全窗口两份——原对齐语义本就正确，P4 的正解是改注释）：
      // 先对齐（重建循环已渲到账尾）再泵——泵零迭代；渲染期同步无入账窗口，
      // 此泵仅形式兜底（防御未来异步化）
      _HG.histCursor = _HG.histAll ? _HG.histAll.length : 0;
      _HG.histDirty = false;   // 整窗重放后账净（live 行已并入——见入口拼接）
      try { _histPump(); _trimOldTurns();
_hgRailSync(); } catch (_) {}
      // 409：整窗换入把 .hg-spin-row（flow 直子）清掉了——重渲后幂等恢复
      // 「正在执行…」转圈（用户实锤「正在执行的转圈图标没有了」；此前只有
      // 快照路径 sessions:412 补，主渲染路径漏；幂等：busy=false 时为 no-op）
      try { if (typeof _hgSpinShow === 'function') _hgSpinShow(!!_HG.busy); } catch (_) {}
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
      // 冷查询批4：subTidRes 正向映射退役——_subReopen miss 走强制
      // regSync（后端冷查询全量权威）而非本地缓存
      if (l.role === 'tool' && (l.text === 'Task' || l.text === 'Agent')
          && l.input && (l.input.description || l.input.subagent_type || l.input.agent_type)) {
        const _typ = l.input.subagent_type || l.input.agent_type || 'Task';
        const _desc = l.input.description || '';
        d.agentsRpl = d.agentsRpl.filter(x => !(x.type === _typ && x.desc === _desc));
        const _aid = (l.result && String(l.result).match(/(?<![a-zA-Z])agentId[:"':\s]+([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
        d.agentsRpl.push({
          type: _typ, desc: _desc, t0: 0, done: true,
          doneAt: l.ts ? (Date.parse(l.ts) || 0) : 0, replay: true,
          agentId: _aid });
        if (d.agentsRpl.length > 50) d.agentsRpl.shift();
      } else if (l.role === 'tool' && l.text === 'SendMessage') {
        const _ra = (String(l.result || '').match(/resumedAgentId["'\s:]+([0-9a-zA-Z_-]{8,64})/) || [])[1] || '';
        if (_ra && !d.agentsRpl.some(x => x.agentId === _ra)) {
          const _msg = String((l.input || {}).message || '').trim().slice(0, 40);
          d.agentsRpl.push({
            type: 'SendMessage', desc: (typeof _peerDesc === 'function' ? _peerDesc((l.input || {}).to, _msg) : (_msg || '')),
            t0: 0, done: true, doneAt: l.ts ? (Date.parse(l.ts) || 0) : 0,
            replay: true, agentId: _ra });
          if (d.agentsRpl.length > 50) d.agentsRpl.shift();
        }
      }
    }
    try { _subDirPaint(); } catch(_) {}
  }
  // v3.2.12：_hgShrinkHead（贴底收缩）随分页退役——恒全量渲染后无「窗口」可收
  async function _histFetch(sidAt) {
    // v4（a23）：投影模式 histAll 只由 v4bridge 写——V3 fetch 链覆盖 histAll
    // 会把 transcript 语义（images=计数数字）混进投影语义（images=路径数组），
    // 两套语义打架产「📄 1」假文件 chip（用户实测 a22）
    if (typeof _HG !== 'undefined' && _HG.v4Cur) return null;
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return false;
      _HG.histAll = _hgMergeLive(j.lines || [], _HG.histAll, j.lines_seq || 0);   // 399-N1：水位=读窗前快照（j.seq 是应答时刻，读→应答窗内事件行会被误判已含而丢弃）
      // 399-R3（复审实锤：fetch 窗口期 SSE 先到入账的行被整替毁掉——old 已
      // 换新，入口拼接救不了；保尾在赋值处就地做）+ v3.5.225 busy 真值随拉取存档
      // v3.5.225：后端 busy 真值随拉取存档——切回重渲的 noFinalize/phResume
      // 判据用它（_HG.busy 在 events poll 回填前有竞态窗，误 false 会让尾组
      // 被定稿+phResume(true) 新建悬挂活组=「一个回合两个块」分割实锤）
      _HG.fetchedBusy = !!j.busy;
      _HG.fetchedSeq = j.seq || 0;   // B组P1：seq 随拉取存档（RO 退出断点续传用）
      _HG.fetchedSeq = j.lines_seq || _HG.fetchedSeq || 0;   // 399-N1：合并水位=读窗前快照（fetchedSeq 语义=「转写已含到哪」；RO 断点用 j.seq 不变）
      return true;
    } catch(_) { return false; }
  }
  async function _histRefresh(sidAt, _startIgnored) {
    if (typeof _HG !== 'undefined' && _HG.v4Cur) return null;   // v4：同 _histFetch 守卫
    try {
      const r = await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sidAt)}`);
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return;   // 会话已切走，弃
      if (_HG.busy) return;   // v3.2.1R2(R2-2)：fetch 在途时用户发送消息——重渲会抹掉活组/新消息泡（07-hist 懒填同款守卫）
      _HG.fetchedSeq = j.lines_seq || 0;   // 399-N1：水位=读窗前快照（_histFetch 同步；R2 的 j.seq 版本在读→应答窗内反向）
      const lines = j.lines || [];
      // 394 单账游标制：DOM/游标有效时只泵账尾差量（前缀一致性）；游标无效
      //（冷启动/降级/失配）→ 整窗（原行为，_histRender 内部对齐游标）
      if (_HG.histLive && !_HG.histStale && !_HG.histDirty && (_HG.histCursor || 0) > 0
          && (_HG.histCursor || 0) <= lines.length) {   // 398-P3：脏账（有未回流 fetch 的 live 行）禁泵——长度≠对齐（审 P3 工具行错位演算）
        _HG.histAll = lines;
        _histPump();
      } else _histRender(lines, 0);
    } catch(_) {}
  }
  // v3.2.7（用户定调「只读模式退役」）：_roDeps/_roEnter/_roExit 整体退役——
  // 更早历史一律上滑/点击扩段进现有 ZCode 渲染器（_histRefresh 大窗口重渲），
  // 到 HIST_CAP 硬顶后提示条指向左侧会话列表。22-readonly.js 模块保留在盘
  // （window.HgReadonly）但无任何入口，成为不可达代码
