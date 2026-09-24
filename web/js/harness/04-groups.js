// harness groups.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function grpFromDom(root, thinkBox, execBox) {
    // v3.2：ZCode 式回合结构——.h-grp-proc{ .h-turn-head(已工作 Ns › 折叠头) +
    // .h-turn-body{ .h-drawer.think + .h-tl(内联工具时间线) } }。execBox 仅
    // 旧快照（v3.1 及以前的双抽屉结构）恢复用：g.tl=null 走 legacy 兼容渲染
    const tlBox = root.querySelector('.h-tl');
    const turnHead = root.querySelector('.h-turn-head');
    const turnBody = root.querySelector('.h-turn-body');
    const g = {
      root,
      proc: root.querySelector('.h-grp-proc'),
      think: { box: thinkBox, body: thinkBox.querySelector('.h-drawer-body'),
               title: thinkBox.querySelector('.h-drawer-title'),
               stats: thinkBox.querySelector('[data-hg-dslots]') },
      exec: execBox ? { box: execBox, body: execBox.querySelector('.h-drawer-body'),
              title: execBox.querySelector('.h-drawer-title'),
              stats: execBox.querySelector('[data-hg-dstats]'),
              slots: execBox.querySelector('[data-hg-dslots]') } : null,
      tl: tlBox || null,
      head: turnHead || null,
      headBody: turnBody || null,
      headLabel: turnHead ? turnHead.querySelector('.h-turn-label') : null,
      headSub: turnHead ? turnHead.querySelector('.h-turn-sub') : null,
      headTimer: null,
      exp: null,                  // v3.2：当前查阅聚组 {el, sum, rows}（renderToolUse 维护）
      t0: turnHead ? (+(turnHead.dataset.t0 || 0) || undefined) : undefined,   // v3.2：认回时从折叠头恢复回合起点
      ph: null, phTimer: null, phIdx: 0,
      counts: null,               // null = 未从 dataset 恢复
    };
    // v3.2：新结构把工具计数挂在 .h-tl dataset（旧结构在 exec.stats dataset）
    const cntHost = g.tl || (g.exec && g.exec.stats) || null;
    if (cntHost) {
      try { g.counts = JSON.parse(cntHost.dataset.counts || 'null'); } catch(_) { g.counts = null; }
    }
    // v2.20（2.png 空壳胶囊）：无内容的抽屉整体隐藏。新建组本来就 display:none
    // （见 grpEnsure），这里按 body 内容推导——快照恢复 inline style 会在、
    // 回扫接回走现场状态，但旧快照/边界路径没有标记，推导一劳永逸：
    // 空组什么都不显示（比「思考：无 / 执行：无」更干净）。
    const thKids = g.think.body ? g.think.body.children.length : 0;
    const exKids = (g.exec && g.exec.body) ? g.exec.body.children.length : 0;
    const exCnt = g.counts && Object.keys(g.counts).length ? 1 : 0;
    thinkBox.style.display = thKids ? '' : 'none';
    if (execBox) execBox.style.display = (exKids || exCnt) ? '' : 'none';
    // v3.2：空时间线不占位（组内只有思考/正文时 proc 区不留白条）
    if (g.tl) g.tl.style.display = (g.tl.children.length || exCnt) ? '' : 'none';
    return g;
  }
  function grpEnsure(live) {
    let g = _HG.grp;
    // v3.2.13：histBuilding——原子渲染期组根在游离缓冲里 isConnected 恒
    // false，原判据每行都重认回新 wrapper（g.exp 全丢、查阅组碎成单子行
    // 墙——用户实锤「没修复好」的根因）；缓冲期内缓冲内元素视为在场
    if (g && g.root && (g.root.isConnected || _HG.histBuilding)) return g;
    // 快照恢复（切会话切回）后 _HG.grp 失联 → 扫 flow 最后一个组接回来。
    // 占位动画不重启：正文该到已到才走得到恢复路径。
    // v2.18.1：已定稿的组（dataset.finalized）不接回——正文切组刚定稿旧组，
    // 回扫必须放它过去，让下面新建组承接新回复。
    const root = _hgFlow.querySelector('.h-grp:last-of-type:not([data-finalized])');
    if (root) {
      const thinkBox = root.querySelector('.h-drawer.think');
      const execBox = root.querySelector('.h-drawer.exec');
      // v3.2：新结构无 exec 抽屉——有 .h-tl 即可认回（execBox 仅旧快照在场）
      if (thinkBox && (execBox || root.querySelector('.h-tl'))) { _HG.grp = grpFromDom(root, thinkBox, execBox); return _HG.grp; }
    }
    // 新建组
    const nr = document.createElement('div');
    nr.className = 'h-grp';
    const proc = document.createElement('div');
    proc.className = 'h-grp-proc';
    const thinkBox = document.createElement('div');
    thinkBox.className = 'h-drawer think';
    thinkBox.innerHTML =
      `<button class="h-drawer-head"><span class="h-chev">▸</span>` +
      `<span class="h-drawer-title">🧠 思考</span>` +
      `<span class="h-tslots" data-hg-dslots></span></button>` +
      `<div class="h-drawer-body"></div>`;
    // v3.2：ZCode 式回合闭合结构——turn-head 是折叠触发行（工作中 Ns/已工作 X ›），
    // turn-body 包思考抽屉+工具时间线；正文气泡在组根（折叠区外永远可见）
    const turnHead = document.createElement('button');
    turnHead.className = 'h-turn-head';
    turnHead.dataset.hgTurnTgl = '1';
    turnHead.style.display = 'none';
    turnHead.innerHTML =
      `<span class="h-chev">▸</span>` +
      `<span class="h-turn-label">工作中 0s</span>` +
      `<span class="h-turn-sub"></span>`;
    const turnBody = document.createElement('div');
    turnBody.className = 'h-turn-body';
    const tlBox = document.createElement('div');
    tlBox.className = 'h-tl';
    turnBody.appendChild(thinkBox);
    turnBody.appendChild(tlBox);
    proc.appendChild(turnHead);
    proc.appendChild(turnBody);
    // v2.20（2.png 空壳胶囊）：新组抽屉先隐藏——纯文本回复的组（无思考无工具）
    // 不再渲染「🧠 思考 / 💻 执行」空壳胶囊+「完成」徽章；有内容时由
    // startThinking / drawerCount 翻回显示。
    thinkBox.style.display = 'none';
    nr.appendChild(proc);
    addRow(nr);
    g = grpFromDom(nr, thinkBox, null);
    g.counts = {};                 // 新组才清；恢复组从 dataset 读
    // v3.2R1(P0)：回合起点——回放用 user 行 ts（pendingTurnT0）；live 取当下；
    // 回放无 ts（旧转写缺失）保持 undefined——定稿落无数字「已工作」，
    // 绝不用当前时钟编造（否则工时随刷新增长）
    // v3.2.2（用户实测）：切分组（段内 think/tool 触发 grpEnsure）没有
    // pendingTurnT0——回放期取当前行 ts（_HG.histLineTs 由 renderHistLine
    // 逐行维护）作段起点，段工时=首末行 ts 差；live 仍取当下时钟
    const _pt0 = _HG.pendingTurnT0;
    _HG.pendingTurnT0 = null;
    g.t0 = (_pt0 > 0) ? _pt0
         : (_HG.openState ? (_HG.histLineTs || undefined) : Date.now());
    if (g.think.stats) g.think.stats.dataset.segCount = '0';
    // v3.2.1：撤位置键开合恢复（跨代际同键碰撞误开+误标 userToggled，详见
    // _tlPlace 注）；思考抽屉重建默认收起，开合态随快照 dataset 忠实序列化
    _HG.grp = g;
    // v2.25：压缩开始会把进行中的组定稿（grpFinalize→phRemove 连占位气泡
    // 一起摘掉），压缩后模型继续推理 → startThinking/renderToolUse 在这里
    // 起新组——本轮不是新用户消息，renderUser 的 phStart 不会再触发 →
    // 「自动压缩完成」分割线到首条正文之间一片空白（用户截图红箭头：
    // 自动压缩完成后的提示/气泡又没了）。本轮仍在跑且尚无正文时补回占位，
    // 正文到达 renderAsst 会 phRemove 让位。
    if (_HG.busy && !_HG.asstText) phStart(g);
    return g;
  }
  function thinkSegCount(g) {
    return +((g.think.stats && g.think.stats.dataset.segCount) || 0) || 0;
  }
  // v3.2.4：回合头副位——思考段计数随时间线化上头（胶囊退役后思考数唯一
  // 可见处）：「· N 思考 · M 工具」（无思考段只显工具）
  function _turnHeadSubPaint(g) {
    if (!g || !g.headSub) return;
    const segN = thinkSegCount(g);
    const toolN = (g.counts ? Object.values(g.counts).reduce((a, b) => a + b, 0) : 0);
    const parts = [];
    if (segN) parts.push(segN + ' 思考');
    if (toolN) parts.push(toolN + ' 工具');
    g.headSub.textContent = parts.length ? '· ' + parts.join(' · ') : '';
  }
  function thinkSegCountSet(g, n) {
    if (g.think.stats) g.think.stats.dataset.segCount = String(n);
  }
  const _PH_WORDS = ['AI 正在思考中…', 'AI 正在翻阅资料…', 'AI 正在敲代码…',
    'AI 正在整理思路…', 'AI 正在细细品你的话…', 'AI 正在路上狂奔…',
    'AI 正在灵光乍现…', 'AI 马上就好了…'];
  function phStart(g) {
    if (!g.ph) {
      // v2.20：先认领快照恢复留下的冻结占位（grpFromDom ph:null 丢了引用），
      // 认不到再新建——否则 phResume 后会叠出第二个占位气泡
      const frozen = g.root.querySelector(':scope > .h-msg.asst.ph');
      if (frozen) g.ph = frozen;
      else {
        const d = document.createElement('div');
        d.className = 'h-msg asst ph';
        d.innerHTML = `<div class="h-bubble"><span class="hg-ph-word" data-hg-phw>AI 正在思考中…</span><span class="hg-ph-dots"><i></i><i></i><i></i></span></div>`;
        g.root.appendChild(d);
        g.ph = d;
      }
    }
    phStopTimer(g);
    g.phIdx = 0;
    g.phTimer = setInterval(() => {
      if (!g.ph || !g.ph.isConnected) { phStopTimer(g); return; }
      g.phIdx = (g.phIdx + 1) % _PH_WORDS.length;
      const w = g.ph.querySelector('[data-hg-phw]');
      if (w) w.textContent = _PH_WORDS[g.phIdx];
    }, 3500);
  }
  function phStopTimer(g) {
    if (g && g.phTimer) { clearInterval(g.phTimer); g.phTimer = null; }
  }
  function phRemove(g) {
    phStopTimer(g);
    if (g && g.ph) { g.ph.remove(); g.ph = null; return; }
    // v2.20：快照恢复的组 ph 引用是 null（grpFromDom 丢引用），但 DOM 里
    // 可能残留冻结占位——SSE 补放的 assistant 正文渲染时要把物理元素一并清掉，
    // 否则冻结的「AI 正在思考中…」和真实答案同时挂屏。
    if (g && g.root) {
      const frozen = g.root.querySelector(':scope > .h-msg.asst.ph');
      if (frozen) frozen.remove();
    }
  }
  function phResume() {
    // 已有活的组对象且占位在屏（从未切走）→ 不用救，重开 timer 反而双计时
    const root = _hgFlow.querySelector('.h-grp:last-of-type:not([data-finalized])');
    if (_HG.grp && _HG.grp.root === root && _HG.grp.ph && _HG.grp.ph.isConnected) return;
    if (!root) {
      // 尾部没有活组 = transcript 重建的 busy 会话末行是 user（renderUser
      // (live=false) 不建组）——等价于「刚发完消息」：建组 + 占位。
      // 调用方必须已确认 busy，否则会凭空造出占位气泡。
      const g = grpEnsure(true);
      phStart(g);
      return;
    }
    const thinkBox = root.querySelector('.h-drawer.think');
    const execBox = root.querySelector('.h-drawer.exec');
    // v3.2R1(P2)：think 抽屉缺失直接放弃（grpFromDom 对 thinkBox 无条件
    // 解引用会抛）——认回条件与 grpEnsure 对齐：think 在场 + （旧 exec 或新 tl）
    if (!thinkBox) return;
    if (!execBox && !root.querySelector('.h-tl')) return;
    if (root.querySelector(':scope > .h-msg.asst:not(.ph)')) return;   // 正文已出，不占位
    const g = grpFromDom(root, thinkBox, execBox);
    _HG.grp = g;
    // v3.2：认回的活组若正跑（折叠头在场）→ 重启「工作中」秒表（timer 不随
    // innerHTML 快照携带，切回不补就是死表）
    if (g.head && g.head.style.display !== 'none' && _HG.busy) _turnHeadShow(g);
    phStart(g);     // 冻结占位由 phStart 认领复用（不新建第二个）
  }
  // v3.2：ZCode 式回合折叠头（AssistantHistoryStatus 同款）——首条工作行到位
  // 即亮「工作中 Ns」实时秒表；定稿改冻结文案「已工作 X」（工时优先取 CLI
  // result.duration_ms，缺省回退本地差值——历史工时绝不吃当前时钟，否则刷新
  // 后「已工作」会随时间继续增长，对照 workSegments activeMs 规则）。
  // 回放路径（hist=true）不定稿前不亮头（重建瞬间成百上千组，秒表空转纯浪费）
  function _turnHeadShow(g, opts) {
    if (!g || !g.head) return;
    opts = opts || {};
    if (g.head.style.display === 'none') {
      g.head.style.display = '';
      if (g.t0) g.head.dataset.t0 = String(g.t0);
    }
    // 秒表只走 live（流式期 openState=null）；回放重建期 openState 在场——
    // 成百上千组各挂定时器纯空转。认回复跑（phResume）headTimer 已在则不叠
    if (!opts.hist && !g.headTimer) {
      if (!g.t0) g.t0 = Date.now();
      g.headTimer = setInterval(() => {
        if (!g.headLabel || !g.head.isConnected) { clearInterval(g.headTimer); g.headTimer = null; return; }
        g.headLabel.textContent = '工作中 ' + _hgFmtDur((Date.now() - (g.t0 || Date.now())) / 1000);
      }, 1000);
      (_HG.turnTicks || (_HG.turnTicks = [])).push(g.headTimer);
    }
  }
  function _turnHeadStop() {                        // 清场钩子：切会话/SSE reset 时收掉全部秒表
    ((_HG.turnTicks) || []).forEach(clearInterval);
    _HG.turnTicks = [];
  }
  function drawerCount(toolName) {
    const g = grpEnsure(true);                  // 计数进当前组
    if (!g.counts) g.counts = {};
    const n = _hDrawerName(toolName);
    g.counts[n] = (g.counts[n] || 0) + 1;
    if (g.tl) {
      // v3.2：新结构——计数进折叠头副位（「· N 工具」），时间线随首行翻显。
      // 回放重建期（openState 在场）不亮头：秒表会显示假「工作中 0s」，
      // 头只在 grpFinalize 定稿时以冻结工时亮出
      g.tl.style.display = '';
      g.tl.dataset.counts = JSON.stringify(g.counts);   // 快照恢复用
      if (!_HG.openState) _turnHeadShow(g);
      _turnHeadSubPaint(g);                     // v3.2.4：副位带思考计数（· N 思考 · M 工具）
    } else if (g.exec) {
      // 旧快照恢复的组：chips 进旧执行抽屉头（字节级兼容 v3.1 前的快照）
      g.exec.box.style.display = '';
      const entries = Object.entries(g.counts);
      const shown = entries.slice(0, 8).map(([k, v]) => `<span class="h-drawer-chip">${esc(k)}×${v}</span>`).join('');
      g.exec.stats.innerHTML = shown + (entries.length > 8 ? '<span class="h-drawer-chip">…</span>' : '');
      g.exec.stats.dataset.counts = JSON.stringify(g.counts);
    }
    _hgScrollBottom();
  }
  function grpFinalize(auto, opt) {
    const g = _HG.grp;
    if (!g) return;
    phRemove(g);
    opt = opt || {};
    // v3.2R1(P0 审计)：回放态判据（opt.hist 或重建期 openState 在场）前置——
    // _tlExpFlush 与工时分级共用；尾组定稿发生在 _histRender 的 finally 之后
    // （openState 已清空），必须靠 hist:true 显式传递才不丢回放语义
    const _hist = opt.hist === true || !!_HG.openState;
    _tlExpFlush(_hist);                   // v3.2：定稿先冲查阅聚组（头部定格汇总+自动收）
    if (g.headTimer) {
      clearInterval(g.headTimer);
      // v3.2R1(P2)：同步从 turnTicks 摘除——只清 interval 不摘 id，数组随
      // 回合数无界增长（_turnHeadStop 对已清 id 的 clearInterval 无害但白挂）
      if (_HG.turnTicks) _HG.turnTicks = _HG.turnTicks.filter(t => t !== g.headTimer);
      g.headTimer = null;
    }
    // v2.20 修复：定稿把组头「思考 N 次」重写为纯文本——流式中带的脉动
    // 动画（hg-think-anim）此前无人摘，回复结束后还在闪。
    // 无思考段的组（空壳抽屉）不动，别把初始标题改写成「思考 0 次」。
    const _segN = thinkSegCount(g);
    if (g.think.title && _segN > 0)
      g.think.title.innerHTML = '🧠 思考 ' + _segN + ' 次';
    if (g.think.stats) g.think.stats.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    if (g.exec && g.exec.slots) g.exec.slots.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    // v3.2：回合折叠头定稿——文案三态（工作中→已工作/已停止），工时优先
    // 事件事实（CLI duration_ms / 回放 endTs 差值），无事实回退本地差值。
    // 只有真正发生过工作（思考段或工具）的组才亮头；纯正文组无头（对照
    // resolveConversationTurnWorkStatus 的 hasWork 判据）
    const _hasWork = (_segN > 0) || !!(g.counts && Object.keys(g.counts).length);
    if (g.head && _hasWork) {
      _turnHeadShow(g, { hist: true });         // 兜底：纯思考组此前没走 drawerCount
      // v3.2R1(P0 审计)：工时事实分级——durMs（CLI 冻结）> endTs−t0（回放
      // 边界差）> live 时钟差；回放态绝不吃当前时钟——缺事实时显示无数字
      // 的「已工作」（对照 ZCode chat.history.worked 的无时长形态），否则旧
      // 会话刷新后「已工作」会随墙上时钟继续增长
      let _dur;
      if (typeof opt.durMs === 'number' && opt.durMs > 0) _dur = opt.durMs;
      else if (typeof opt.endTs === 'number' && opt.endTs > 0 && g.t0) _dur = Math.max(0, opt.endTs - g.t0);
      else if (!_hist && g.t0) _dur = Math.max(0, Date.now() - g.t0);
      g.head.dataset.dur = String(_dur || 0);
      if (g.headLabel) {
        const _txt = _dur != null ? (opt.interrupted ? ' · ' : ' ') + _hgTurnDurTxt(_dur) : '';
        g.headLabel.textContent = (opt.interrupted ? '已停止' : '已工作') + _txt;
      }
    }
    // v3.2.1（用户实测问题1）：完成的回合默认收起——对照 ZCode 回合定稿即
    // 折叠（整段过程只剩「已工作 ›」一行）。不再按 isNearBottom/hist/_hasWork
    // 门控：旧判据在回滚重建（_histRender 期不在底部、split 定稿不带 hist）与
    // 快照恢复（原样回放开着的体）路径全部漏收，用户实锤「回滚后完成的会话
    // 没有收起来」；无工作组的空体同样收（保持「定稿=收起」不变式）。定稿
    // 收的是最新段（视口下方），不产生内容上抽的视觉突跳；用户点开的
    // （userToggled，随快照 dataset 序列化）永不强制收
    if (g.headBody && g.head.dataset.userToggled !== '1')
      g.headBody.classList.add('closed');
    // v3.2.20：实时入 tl 的正文——turnEnd 把最后一条提回根区（最终结论
    // 折叠态可见 + 回滚按钮授予），其余照留时间线保持与思考/工具的时序
    // 交错。须在下方折体块之前跑（提回者即 texts 末位=keep，天然不折）
    if (opt.turnEnd && g.tl) {
      const tlTexts = g.tl.querySelectorAll(':scope > .h-msg.asst');
      const lastT = tlTexts[tlTexts.length - 1];
      if (lastT) { lastT.classList.add('can-rewind'); g.root.appendChild(lastT); }
    }
    // v3.2.2（用户实测）+ v3.2.3（一回合一组）+ v3.2.4（时序）：正文折进
    // 折叠区——用户定调「除了最终结论其他全部收起」「一个回合整合统一计时」
    // 「思考和工具调用要有顺序」：回合收尾定稿（turnEnd）只留组内**最后一
    // 条**正文（=回合最终结论）在折叠头外，更早的中间正文按到达锚点
    // （renderAsst 记的 _tlAt）插回时间线，与思考段/工具行全程交替有序；
    // 中段边界定稿（压缩/协作/审计——回合还在继续）全部折进。旧结构组
    // （v3.1 无 turn-body）保持原样不折（快照兼容降级）
    // v3.2.4R(F1)：纯正文组（无思考无工具→_hasWork=false→头永不亮）不折——
    // 折进「无头+收体+空时间线」的三重隐藏里内容彻底不可达；纯正文本来就
    // 是该组的全部可见内容，照常留在根区
    if (g.headBody && _hasWork) {
      const texts = g.root.querySelectorAll(':scope > .h-msg.asst:not(.ph)');
      const keep = opt.turnEnd ? texts[texts.length - 1] : null;
      const tl = g.tl;
      let _shift = 0;   // 先插回的正文把后续锚点整体后移
      texts.forEach(m => {
        if (m === keep) return;           // 最终结论留根区，不参与插回
        const at = +(m._tlAt);
        if (tl && Number.isFinite(at) && at >= 0 && at <= tl.children.length) {
          if (tl.style.display === 'none') tl.style.display = '';   // F1 防御：空 tl 的内联 none 遗留
          tl.insertBefore(m, tl.children[Math.min(at + _shift, tl.children.length)] || null);
          _shift++;
        } else {
          g.headBody.appendChild(m);      // 无锚点（快照恢复态）回落体尾
        }
      });
    }
    // v2.21：纯思考/工具组（整组没有正文气泡）定稿时补一行弱提示——
    // 模型常连跑几十轮工具（text 全是 "\n\n" 占位被过滤），组头下面悬空
    // 看着像回复丢了（用户实测困惑点）。有正文/空壳组不补。
    // v2.43.1（R-次要①）：组内有子代理段也不补——段内气泡就是可见回复，
    // 再挂「无文字回复」自相矛盾。
    // v3.2.2：正文判定放宽到任意深度（中段定稿已把正文折进体，:scope 直查
    // 会误判「无正文」）；提示行随正文折进体（根区只留回合头+最终结论）
    if (!g.root.querySelector('.h-msg.asst:not(.ph)') && !g.root.querySelector(':scope > .h-grp-notext') &&
        !g.root.querySelector(':scope > .h-subblock') &&
        ((_segN > 0) || (g.counts && Object.keys(g.counts).length))) {
      const tip = document.createElement('div');
      tip.className = 'h-grp-notext';
      tip.textContent = '（本轮为思考/工具操作，无文字回复）';
      (g.headBody || g.root).appendChild(tip);
    }
    // 用户手动开过不强制收；自动收只在用户在底部跟读时（v2.12 判据，按组生效）
    if (auto) {
      if (g.think.box.dataset.userToggled !== '1' && isNearBottom()) g.think.box.classList.remove('open');
      if (g.exec && g.exec.box.dataset.userToggled !== '1' && isNearBottom()) g.exec.box.classList.remove('open');
    }
    g.root.dataset.finalized = '1';   // v2.18.1：已定稿——grpEnsure 回扫不得接回
    _HG.grp = null;      // 下轮 renderUser 开新组
  }
  // v3.2.1R2(R2-1)：终结类事件（result/interrupted/exit）的尾组认回——快照
  // 恢复后回合在切走期间结束，_HG.grp 为空会让 grpFinalize 早退、尾组永不
  // 定稿（冻结「工作中」秒表+开体+冻结占位）。判据与 phResume 同款（未定
  // 稿 + think 抽屉 + 时间线在场；纯文本尾组无工作区本就无需定稿）。返回
  // 是否认回——认回方据此传 hist:true（工时缺事实落无数字「已工作」，不用
  // 当前时钟虚增「回合结束到切回」的空闲段，R2-3）
  function _hgTailAdopt() {
    if (_HG.grp) return false;
    const root = [..._hgFlow.querySelectorAll('.h-grp')].pop();
    const tb = root && root.querySelector(':scope > .h-grp-proc > .h-turn-body > .h-drawer.think');
    if (root && !root.dataset.finalized && tb && root.querySelector('.h-tl')) {
      _HG.grp = grpFromDom(root, tb, null);
      return true;
    }
    return false;
  }
  // v3.2：回合工时文案（ZCode formatConversationWorkDuration 口径：N 秒/N 分 N 秒/N 时 N 分）
  function _hgTurnDurTxt(ms) {
    let s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return s + ' 秒';
    const m = Math.floor(s / 60); s %= 60;
    if (m < 60) return m + ' 分' + (s ? ' ' + s + ' 秒' : '');
    const h = Math.floor(m / 60);
    return h + ' 时 ' + (m % 60) + ' 分';
  }
  function drawerAppend(el, kind) {
    const g = grpEnsure(true);
    if (kind === 'think') g.think.body.appendChild(el);
    else if (g.tl) g.tl.appendChild(el);            // v3.2：工具行进内联时间线
    else if (g.exec) g.exec.body.appendChild(el);   // 旧快照组：回落旧执行抽屉
    _hgScrollBottom();
  }
  function hideWelcome() {
    const w = _hgFlow.querySelector('.hg-welcome');
    if (w) w.remove();
  }
  function addRow(el) {
    hideWelcome();
    _hgFlow.appendChild(el);
    _hgScrollBottom();
    return el;
  }
  function _timeFmt(ms) {
    const d = new Date(ms), n = new Date();
    const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    const sameDay = (a, b) => a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    if (sameDay(d, n)) return hm;
    const yst = new Date(n); yst.setDate(n.getDate() - 1);
    if (sameDay(d, yst)) return '昨天 ' + hm;
    const md = (d.getMonth() + 1) + '月' + d.getDate() + '日';
    return d.getFullYear() === n.getFullYear() ? md + ' ' + hm
      : d.getFullYear() + '年' + md + ' ' + hm;
  }
  function _maybeTimeBar(ms, host) {
    if (!ms) return;
    if (ms - (_HG.lastTs || 0) < 5 * 60 * 1000) return;
    _HG.lastTs = ms;
    const t = document.createElement('div');
    t.className = 'h-time';
    t.dataset.ms = String(ms);
    t.textContent = _timeFmt(ms);
    (host || _hgFlow).appendChild(t);
  }
  function renderUser(text, images, files, live, tsMs) {
    // v3.2：定稿带回合终点——回放用该回合最后一次活动的行 ts
    // （_HG.histActTs，renderHistLine 逐行维护；user 行自身不算活动）——
    // 工时=回合真实工作窗，不含「回合结束到用户下一条消息」的阅读空闲
    // （旧口径 endTs=下一条 user ts 会虚增，v3.2.2 用户实测「没显示工作
    // 时长」连带修正）；live 用当下时刻
    grpFinalize(false, {
      endTs: (live === false)
        ? ((_HG.histActTs > 0 ? _HG.histActTs : (tsMs > 0 ? tsMs : Date.now())))
        : Date.now(),
      hist: live === false,
      turnEnd: true,            // v3.2.2：回合边界——上回合最终正文留在折叠头外
    });
    _HG.pendingTurnT0 = (tsMs > 0 && live === false) ? tsMs : 0;   // v3.2R1：live 记 0（grpEnsure 取当下）；回放缺 ts 保持 0→undefined
    _maybeTimeBar(tsMs || Date.now());        // v2.24.5 微信式时间条（气泡前）
    endThinking(); closeRun();
    _tlExpFlush(!!_HG.openState);   // v3.2.13：回合边界定稿上回合查阅组——思考不再
                                    // 断组后，开放组的头部定格必须由用户行兜底
                                    // （头部定格为桶汇总 + 回放态自动收起）
    _HG.asstText = false;                     // 本轮 AI 尚未输出文本（占位/组头判据）
    const d = document.createElement('div');
    d.className = 'h-msg user';
    if (images?.length || files?.length) {
      const at = document.createElement('div');
      at.className = 'h-bubble-atts';
      at.innerHTML = attChipsHtml(images, files);   // 点击 Lightbox 由 flow 委托（v2.12）
      d.appendChild(at);
    }
    // v3.2.16（用户最后定调，复原 v2.20 原形）：只发图不带文字 → 气泡照出
    // 默认占位文案「*（图片/附件，见上方）*」——图片 chips 在气泡上方、可随
    // 时点开预览；历史里唯一不许出现的是 [Image: source: …] 链接行（转写侧
    // 丢弃 + 前端防线，与此处无关）
    const body = (text && text.trim()) || ((images?.length || files?.length) ? '*（图片/附件，见上方）*' : '');
    d.appendChild(mdBubble(body));
    // v2.22：一键重发 + 编辑后重发——原始内容存 dataset（属性可随
    // innerHTML 快照恢复），钮 hover 显示，点击走 flow 委托
    d.dataset.rtext = text || '';
    d.dataset.ratts = JSON.stringify({ images: images || [], files: files || [] });
    const acts = document.createElement('div');
    acts.className = 'h-macts';
    acts.innerHTML =
      '<button class="h-mact h-resend" title="重发这条消息">↻</button>' +
      '<button class="h-mact h-edit" title="编辑后重发（原文+附件填回输入框）">✎</button>';
    d.appendChild(acts);
    addRow(d);
    if (live !== false) {
      const g = grpEnsure(true);
      phStart(g);                              // AI 未输出前的活泼占位（每轮独立）
      _hgRailSync();   // v3.2.10：live 新回合入轨（历史路径在 _histRender 尾统一 sync）
    }
    return d;
  }
  function _hgEchoDup(it) {
    const us = _hgFlow.querySelectorAll('.h-msg.user');
    const last = us[us.length - 1];
    if (!last) return false;
    if ((last.dataset.rtext || '').trim() !== (it.text || '').trim()) return false;
    try {
      const ra = JSON.parse(last.dataset.ratts || '{}');
      if ((ra.images || []).join('\u0001') !== (it.images || []).join('\u0001')) return false;
      if ((ra.files || []).join('\u0001') !== (it.files || []).join('\u0001')) return false;
    } catch (_) { return false; }
    return true;
  }
  function _hgAvaCls(name) {
    const c = (String(name || '?').charCodeAt(0) || 63) % 5;
    return 'h-ava-' + c;
  }
  function renderAsst(text, model) {
    // v2.16：空白/纯换行的 text 块不渲染。模型每轮都会吐一个 "\n\n" 占位块，
    // 旧判据 `if (!text)` 挡不住 → 每条渲染成一个空白气泡（历史重建后满屏空白
    // 圆角条）。重建与流式两条路径都走这里，一并对齐。
    // v2.43：子代理文本不再走本函数——改入子代理段（_subText），主 flow 的
    // 灰色 sub 行与 isSub/subId 参数一并退役（归属标识上移到段头）。
    if (!text || !String(text).trim()) return;
    _tlExpFlush(!!_HG.openState);        // v3.2：正文打断查阅聚组（回放态必收）
    // v3.2.3（用户实测定调）：**一回合一组，不再按正文切组**。v2.18.1 的切组
    // （正文后再出思考/工具就定稿开新组）把一条用户消息拆成 N 条「已工作」
    // 行分段计时（用户实锤 4 连头：「应该全部整合在一起，统一在一起计时」）
    // ——对照 ZCode 回合模型：user 消息→result 之间所有思考/工具/中间正文
    // 都属同一回合，定稿只发生一次（result/下一 user/回放尾组），一个头带
    // 总工时总工具数，根区只留最终结论（其余正文在定稿时折进体，见
    // grpFinalize turnEnd 逻辑）。中间正文在流式期照常堆在组根可见
    _HG.asstText = true;                       // v2.11：AI 已输出文本
    // v2.18：正文进当前组（组不存在说明是组外场景——快照恢复等，兜底建组）
    const g = grpEnsure(true);
    phRemove(g);                               // 正文接管，占位动画退场
    const d = document.createElement('div');
    d.className = 'h-msg asst';
    d.appendChild(mdBubble(text));
    // v2.37（P1-C）+ v2.37R6（徽章间歇缺失）：任何路径的 AI 气泡都至少有
    // 头像——实跑 model 可得（实时事件自带 message.model，缺省回退会话模型）
    // 必带徽章；历史旧数据无 model 只画头像不画徽章（不编造归属）。
    // 徽章/头像均为纯 class+dataset，随 innerHTML 快照序列化
    const bare = model ? String(model).split('[')[0] : '';
    const meta = document.createElement('div');
    meta.className = 'h-mmeta';
    // v2.38 角色徽章：三角色开启时按形态标主会话角色（v2.50：strong=
    // 重主力直干/light=轻主力）。缓存未拉到不标——不编造归属。样式复用
    // h-mmodel，加右距与模型徽章隔开。
    const rj = _hgRolesCache;
    const roleB = (rj && rj.ok && rj.roles && rj.roles.enabled)
      ? `<span class="h-mmodel" style="margin-right:6px;" title="三角色形态下的主会话角色">${rj.mode === 'light' ? '轻主力' : '重主力'}</span>`
      : '';
    meta.innerHTML = `<span class="h-ava ${_hgAvaCls(bare || 'AI')}">${esc((bare || 'AI').charAt(0).toUpperCase())}</span>` +
      roleB +
      (bare ? `<span class="h-mmodel" title="本条回复的实跑模型">${esc(bare)}</span>` : '');
    d.appendChild(meta);
    // v2.28.16：回滚按钮（回合边界授予）
    const bar = document.createElement('div');
    bar.className = 'hg-msg-acts';
    bar.innerHTML =
      '<button class="hg-mact" data-hg-rewind title="回滚到本条所在回合结束：之后的全部丢弃（自动全量备份）">⏪ 回滚到这里</button>';
    d.appendChild(bar);
    // 锚点 = 正文前缀（随 dataset 序列化，实时/回放两路同源；后端按它
    // 定位「这条消息所在回合的 result」做截断）
    try { d.dataset.rwa = String(text).trim().slice(0, 60); } catch(_) {}
    _HG.lastAsstEl = d;                  // result 到达时授予 can-rewind
    // v3.2.4：记时间线锚点（到达时的 tl 行数）——定稿折体时按锚点插回，
    // 思考段↔工具行↔中间正文全程时序一致（expando 不随快照走，恢复态
    // 回落体尾，重建必重算）
    d._tlAt = g.tl ? g.tl.children.length : 0;
    // v3.2.20（用户实锤「执行过程中看不到顺序」）：中间正文**实时入时间
    // 线**——到达即落在当前思考段/工具行之后，思考→工具→消息全程交错
    // 可见（原实现堆组根、定稿才折回，运行期永远「过程块在上+正文墙在
    // 下」两截不交错）。定稿(turnEnd)把最后一条提回根区作最终结论；旧
    // 结构组（无 tl）照旧落根
    if (g.tl) {
      if (g.tl.style.display === 'none') g.tl.style.display = '';
      g.tl.appendChild(d);
    } else g.root.appendChild(d);
    _hgScrollBottom();
  }
