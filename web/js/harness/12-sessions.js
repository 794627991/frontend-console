// harness sessions.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  async function switchTo(sid, keepInput) {
    if (sid === _HG.sid && _hgFlow.querySelector('.h-msg, .hg-welcome')) {
      // v2.15：点的是当前会话 → 早返回。但 busy 卡死时用户正是靠「重点一下
      // 当前会话」自救，这里不能什么都不做：至少按后端真实值纠偏一次。
      if (sid) {
        // v2.35.2（P0 加固）：SSE 归属校验——历史竞态（切换竞速/早返回）可能
        // 让 _HG.sse 停在别的会话的流上：内容看着正常、事件永远不来。归属
        // 不符即重开本会话流（after_seq 用当前 seq，不重放已渲染事件）。
        try {
          const own = _HG.sse && _HG.sse.url
            && _HG.sse.url.includes('sid=' + encodeURIComponent(sid));
          if (!own) openSSE(sid, _HG.seq);
        } catch(_) {}
        _hgEventsPoll(sid);
      }
      return;
    }
    saveCache();
    const prevSid = _HG.sid;            // v2.3.0：旧会话 id（未发送附件暂存归属）
    closePop(); closeMention();
    setQuote(null);                     // v2.27：引用属于当前输入草稿，切会话不跨带
    _hgPeerWaitStop();                  // v2.27.5：转交等待计时器不跨会话残留
    endThinking(); closeRun();
    if (_HG.grp) phStopTimer(_HG.grp);   // v2.18：防御性清占位 timer（isConnected 自杀是兜底）
    _turnHeadStop();   // v3.2：回合秒表随切会话全收
    _hgMentionReset();          // v2.15：@ 引用高亮不跨会话残留
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;   // v2.18：组级抽屉
    // v2.43：子代理段随会话切换重置（段计时器停掉；段 DOM 随 flow 重建，内存档不跨会话残留）
    Object.values(_HG.subBlk || {}).forEach(b => { if (b && b.timer) clearInterval(b.timer); });
    _HG.subRows = {}; _HG.subBlk = {};
    _HG.subTail = {};   // v2.46：实时思考轮询 offset 随会话切换重置（防串会话读错文件位）
    _HG.subTailSeg = {};   // v2.58：续派切段映射随会话重置
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false;   // v2.24：多段历史渲染源不复用（防串会话）；v2.35.2：histLive 随切重置（快照恢复态不进滚动扩收）
    _HG.histStale = false;   // v2.43.2（R2-缺口A）：降级标记随切会话重置（恢复时按快照 histFp 重新判定）
    _HG.todos = null; _HG.agents = null;     // v2.30：会话动态随会话切换重置（todos 由回放重建）
    _HG.dyn = null;                          // v2.32 面板派生态不跨会话（活动流/回合史/打标全重建）
    _HG.proj = null;                         // v3.1：前端投影不跨会话（/events 种子重建）
    _subReset();                             // v2.33：子代理实时窗格不跨会话
    _HG.think = null; _HG.noScroll = false; _HG.openState = null;   // v2.16：重建态不跨会话残留
    _HG.sid = sid; _HG.seq = 0; _HG.epoch = null; _HG.alive = false;
    // v2.15：dirty 语义修正。旧实现只在「发送成功」置 true、只在
    // switchTo(null) 置 false —— 冷启动自动进的是历史会话（has_history），
    // dirty 仍是 false，于是点一下模型/项目 chip 就会走 `if (!_HG.dirty)`
    // 分支把这条历史会话 DELETE 掉并杀掉其进程（实测可复现：打开历史会话、
    // 不发消息、点模型 → 会话从列表消失）。这里改为按「目标会话是否已落盘」
    // 判定：缓存里有 or 服务端标记 has_history 的会话，都不是可丢弃的新会话。
    _HG.dirty = !!(sid && (_HG.cache[sid] || _hgHasHistory(sid)));
    // v2.15：busy 不能跨会话沿用。旧实现只重置 _HG.alive，busy 靠下面那次
    // events 请求的 .then(setBusy) 纠偏，而 catch 把失败整个吞掉 —— 请求
    // 失败/非 ok 时 busy 停在 true，发送键恒为 ■、活动条恒计时、send() 被
    // 拦下，点 ■ 又回到这条死循环。这里先无条件清掉，真实值由 events 回填。
    setBusy(false);
    _hgCostEl.classList.remove('warn');   // 清文本不清 class 会让空用量环留着橙色警示
    // v2.3.0：未发送的附件随会话暂存/恢复——切走时把当前 atts 归档到旧会话
    // 名下，切回时取回该会话的暂存（原来无条件清空，用户贴的图切一圈回来
    // 就没了）。发送成功的清空在 send 尾部（清 attsBy），互不干扰。
    if (prevSid) _HG.attsBy[prevSid] = _HG.atts;
    _HG.atts = (sid && _HG.attsBy[sid]) || [];
    renderAtts();
    _HG.echoFast = null;               // v2.20：切会话清乐观渲染去重窗口（防串会话吞 echo）
    _hgCtxRestore(sid);                // 切回旧会话：恢复该会话上次的上下文用量（result 不重放）
    _hgQueueSeed(sid);                 // v3.1：durable 队列从服务端账本初始化（#10）
    if (!sid) {
      _hgFlow.innerHTML = '';
      showWelcome();
      openSSE(null); setBusy(false);
      _hgTitleEl.textContent = '新会话'; _hgCwdEl.textContent = '';
      renderList(); renderQueue();
      _hgInput.focus();
      return;
    }
    const c = _HG.cache[sid];
    if (c) {
      // v3.1：keep-warm 命中——取消该快照的延迟销毁（saveCache 排程的 30s
      // 定时器），热快照继续作为 LRU 一员存活
      if (_HG.cacheWarm && _HG.cacheWarm[sid]) {
        clearTimeout(_HG.cacheWarm[sid]);
        delete _HG.cacheWarm[sid];
      }
      _hgFlow.innerHTML = c.html; _HG.seq = c.seq;
      _HG.epoch = c.epoch || null;     // v3.0：代际水位随快照存取（与 seq 同进退）
      _HG.echoFast = c.echoFast || null;   // v2.28.13：去重窗口随快照恢复（防重放双画）
      // v2.37（P0-A）：窗口账目重建——快照 DOM 是上一次 _histRender 的窗口
      // （histStart 起的尾部段），账目随快照存取（见 saveCache）。histLive
      // 置 true 需 histAll 数据在场：拉一次 transcript 只填数据不重渲
      // （转写只追加，[0..histStart) 前缀稳定，DOM 尾段与 histAll 对应成立，
      // 上滑扩段自此可用；旧缓存无账目字段 → 维持 v2.35.2 安全态走只读条）。
      // 还原后 400ms 内不进收缩分支——程序化 scrollBottom 会触发 scroll 事件，
      // >2 页的快照会被立刻「收段」重渲（观感=又刷了一遍）
      _HG.histStart = (typeof c.histStart === 'number') ? c.histStart : 0;
      _HG.histRestoredAt = Date.now();
      // v2.25：快照里「已点开」的懒段/懒工具，切回来必须显示内容——histAll
      // 已被切会话清空，拉 transcript 后补填（否则展开=空白壳，用户实测
      // 「早起会话的历史思考点不开」）。v2.43.2：选择器补 .open（原漏——
      // 把关闭行也预填，废了懒加载）；补填并入下面主路（单次拉取）
      const lazyOpen = _hgFlow.querySelectorAll('.h-think-seg.open[data-hg-lazy="1"], .h-tool.open[data-hg-lazy="1"]');
      if (c.histLive && !_HG.histAll) {
        _histFetch(sid).then(ok => {
          if (ok && _HG.sid === sid) {
            // v2.37R2（复审4）：账目越界钳制——快照存账后该会话在别窗做过
            // 回滚（转写被截断），histStart 可能越过现在的行数
            if (_HG.histStart > _HG.histAll.length) _HG.histStart = _HG.histAll.length;
            // v2.43.1（R-FAIL3）+ v2.43.2（R2-缺口A）：前缀指纹不符/stale
            // 哨兵=中插变更——旧 DOM 账目整体作废，重渲自愈；忙碌（后台回
            // 合进行中，重渲会炸掉活组）降级：弃 histAll、扩收门保持关、置
            // histStale 让下次快照带 'stale'（恢复强制重渲，漂移保护不丢失）
            if (c.histFp === 'stale'
                || (c.histFp != null && _histPrefixFp(_HG.histAll, _HG.histStart | 0) !== c.histFp)) {
              if (!_HG.busy) _histRender(_HG.histAll, _HG.histStart | 0);
              else { _HG.histAll = null; _HG.histStale = true; }
              return;
            }
            _HG.histLive = true;
            renderSideStatus();   // 面板 B/C 回放数据此路也会补齐（todos 等）
            // v2.43.2（R2-缺口A）：懒行补填并入主路——旧实现另起 fetch 先于
            // events 到达，busy 判定失真，漂移分支抢跑重渲炸掉快照（实测）
            lazyOpen.forEach(el => _histLazyFill(el));
          }
        });
      } else if (lazyOpen.length && !_HG.histAll) {
        // 旧账目快照（无 histLive/histFp，v2.37 前的缓存）：维持 v2.25 直填
        // （无指纹可校验；中插变更由补填内的点校验/下次全量渲染兜底）
        _histFetch(sid).then(ok => {
          if (ok && _HG.sid === sid) lazyOpen.forEach(el => _histLazyFill(el));
        });
      }
      // v3.0 滚动记忆恢复（对照 ZCode chatSessionScrollMemory）：离开时贴底
      // → 回底（继续跟读）；否则恢复钳制后的 scrollTop（clamp 到当前可滚
      // 范围——DOM 未到齐时恢复值被压小，内容补齐后自然落位）。rAF 等
      // innerHTML 回填后的布局结算再写 scrollTop（同步写会被旧布局吞掉）。
      if (c.scroll && !c.scroll.atBottom) {
        _HG.noScroll = true;           // 恢复写 scrollTop 触发的 scroll 事件不得进扩收分支
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const max = _hgFlow.scrollHeight - _hgFlow.clientHeight;
            if (max > 0) _hgFlow.scrollTop = Math.min(Math.max(c.scroll.top, 0), max);
            _HG.noScroll = false;
          });
        });
      } else _hgScrollBottom(true);
      // v2.3.13：快照里冻结的压缩分割线——本会话没有仍在进行的压缩就定格成
      // 完成态（压缩结束事件只在原会话 SSE 里到达，切走期间错过时这里兜底），
      // 不让「正在压缩 · 已 X」冻死在消息流里
      const cdiv = _hgFlow.querySelector('.h-switch[data-hg-compact]');
      if (cdiv && !(_HG.compacting && _HG.compactSid === sid)) {
        const ci = cdiv.querySelector('i');
        if (ci && !ci.textContent.includes('完成')) ci.textContent = '上下文压缩完成';
      }
      // v2.24.5：时间条状态从 DOM 恢复（最后一条 .h-time 的 ms）
      _HG.lastTs = +((([..._hgFlow.querySelectorAll('.h-time')].pop() || {}).dataset || {}).ms || 0);
      // v2.3.2：未定格的转交等待线重启计时——快照（innerHTML 字符串）不
      // 带 interval，恢复后计时冻结在快照时刻（用户实锤「读秒不走」）。
      // v2.35.2（P1 多槽）：全部未定格线各重挂各的计时器（此前只挂最后
      // 一条，更早的线读秒冻死）；peerWait 指向最后一条（兼容识图 sweep）。
      // 旧快照的线没有 data-peer——按文本兜底识别，一并重挂
      const relayEls = new Set(_hgFlow.querySelectorAll('.h-switch[data-peer]:not([data-done])'));
      _hgFlow.querySelectorAll('.h-switch .hg-peer-t').forEach(tb => {
        const sw = tb.closest('.h-switch');
        if (sw && !sw.dataset.peer && !sw.dataset.done
            && sw.textContent.includes('等待结论回传')) relayEls.add(sw);
      });
      relayEls.forEach(rl => _hgPeerTimerStart(rl, +(rl.dataset.t0 || 0) || Date.now()));
      // 快照恢复后重建 rowById（busy 会话切回时 tool_result 事件要挂回行）
      // v2.43.1（R-FAIL2）：段内工具行按所在段归 subRows（不入主链 rowById）
      // ——恢复瞬间（下一子代理事件未到、subBlk/subRows 尚空）到达的子代理
      // tool_result 不再被 :2846 守卫丢弃，段内徽章照常定格
      _hgFlow.querySelectorAll('[data-tid]').forEach(el => {
        const blk = el.closest('.h-subblock');
        if (blk && blk.dataset.hgSubblock) {
          const _sp = blk.dataset.hgSubblock;
          ((_HG.subRows[_sp]) || (_HG.subRows[_sp] = {}))[el.dataset.tid] = el;
        } else {
          _HG.rowById[el.dataset.tid] = el;
        }
      });
      // v2.9：缓存恢复不能盲目清 busy——切走时正在回复的会话，切回后
      // 事件继续流入但 user_echo 已在 seq 之前（不重放），活动条/停止钮
      // 再也不弹（用户实测「有实际对话但无计时条、发送键不变■」）。
      // 后端 events 接口顺带返回真实 busy，按它恢复（v3.0 兼带 epoch 校验）
      _hgEventsPoll(sid);
    } else {
      _hgFlow.innerHTML = '';
      try {
        const j = await (await fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)).json();
        if (j.ok && _HG.sid === sid) {
          _HG.seq = j.seq || 0; _HG.epoch = j.epoch || null; _HG.alive = !!j.alive;
          if (!j.lines.length) showWelcome();
          else _histRender(j.lines, Math.max(0, j.lines.length - _HG.HIST_PAGE));
          // v2.20（3.png）：busy 会话尾部组是「进行中」的组——transcript 只到
          // 已落盘部分，无条件定稿会把组关死还漏占位气泡。留活 + 补占位，
          // SSE 续传事件经 grpEnsure 回扫正常接回。
          if (j.busy) phResume();
          else grpFinalize(true, { hist: true });   // transcript 末尾若挂着未收的组 → 定稿（v3.2R1(P0)：回放不吃时钟，缺事实落无数字「已工作」）
          _hgScrollBottom(true);              // 切会话回底（不受翻历史保护限制）
          setBusy(!!j.busy, j.busy_since);   // v2.26：计时起点带后端 busy_since（切回来不清零）
        }
      } catch(_) {}
    }
    // v2.35.2（P0 加固）：transcript 分支有 await——期间用户可能已切去别的
    // 会话（快切/双击竞速）。此刻本调用已是过期调用：chrome（标题/目录/chip）
    // 与 openSSE 若照跑，会把「显示 A、事件流却挂 B、标题 C」的错位态焊死，
    // 且过期流的小 seq 事件全被防重放守卫吞掉，会话从此假死。归属不符即弃。
    if (_HG.sid !== sid) return;
    const s = _HG.sessions.find(x => x.sid === sid);
    // v2.7：项目优先——cwd 目录名在前（accent），claude 会话名在后
    _hgCwdEl.textContent = s ? (s.cwd || '').split(/[\\/]/).pop() || '~' : '';
    // v2.19：切回历史会话 → 「新会话将打开的目录」跟随该会话的项目，
    // 同项目连续开会话不用每轮重选（会话无 cwd 时不动用户手选的值）。
    if (s && s.cwd && _HG.cwd !== s.cwd) {
      _HG.cwd = s.cwd; _hgSaveCwd(s.cwd); projChipLabel();
    }
    // v2.20：权限/思考等级同理跟随会话恢复显示
    if (s) {
      if (s.permission && s.permission !== _HG.perm) { _HG.perm = s.permission; permChipLabel(); }
      const st = s.think || null;
      if (st !== _HG.thinkLv) { _HG.thinkLv = st; thinkChipLabel(); }
      // 模型跟随会话恢复（用户要求：打开历史会话直接显示之前用的模型）。
      // 元数据 model=None 的会话（从没显式选过）实际跑的是 settings 默认
      // 模型——显示默认名，别回退成空态「模型」让用户以为丢了。
      const sm = s.model || (_HG.models && _HG.models.default) || null;
      if (sm && sm !== _HG.model) {
        _HG.model = sm;
        _hgQ('[data-hg-model]').innerHTML = '🧠 ' + esc(sm) + ' ▾';
      }
    }
    _hgTitleEl.textContent = (s && s.title) || '会话';
    _hgConn.meta.label = _hgTitleEl.textContent;
    _hgConn.meta.cwd = (s && s.cwd) || '';
    _hgConn.tab.querySelector('.label').textContent = _hgTitleEl.textContent;
    openSSE(sid, _HG.seq);
    renderList();
    renderQueue();                   // v2.20：排队条按会话各自恢复
    refreshSidebar();
    if (!keepInput) _hgInput.focus();
  }
  function showWelcome() {
    _hgFlow.innerHTML = `
      <div class="hg-welcome">
        <div class="hg-welcome-ico"><span class="claude-ico big"></span></div>
        <div class="hg-welcome-title">你好，我是 Claude</div>
        <div class="hg-welcome-desc">直接输入开始新对话，或从左侧选择历史会话继续。<br>支持 📎 附件、@ 文件引用、⚡ 技能、🧠 模型切换。</div>
      </div>`;
  }
  function _hgMm(m) {
    return !!(_HG.models && (_HG.models.mm || []).includes(m));
  }
  async function refreshSessions() {
    try {
      const j = await (await fetch('/api/harness/sessions')).json();
      if (j.ok) { _HG.sessions = j.sessions || []; renderList(); }
    } catch(_) {}
  }
  function setQuote(_hgQ) {
    _HG.quote = _hgQ || null;
    if (!_HG.quote) { quoteEl.style.display = 'none'; return; }
    const brief = _HG.quote.text.replace(/\s+/g, ' ').trim();
    quoteBodyEl.textContent = `${_HG.quote.who}：${brief.length > 60 ? brief.slice(0, 59) + '…' : brief}`;
    quoteBodyEl.title = _HG.quote.text;          // 悬浮看全文
    quoteEl.style.display = 'flex';
    _hgInput.focus();
  }
  function _hgQueueKey() { return _HG.sid || '_new'; }
  function renderQueue() {
    if (qDrag) return;            // 拖拽中不重建，松手后统一重渲
    const list = _HG.queues[_hgQueueKey()] || [];
    const lenChanged = queueEl._lastLen !== list.length;
    queueEl.style.display = list.length ? 'flex' : 'none';
    queueEl._lastLen = list.length;
    // v2.25：排队条顶高/收起会改变消息流视口高——原本在底部跟读时自动回底，
    // 不用用户手动翻页（用户需求）。翻阅历史中（不在底部）不打扰。
    if (lenChanged && typeof isNearBottom === 'function' && isNearBottom()) {
      requestAnimationFrame(() => _hgScrollBottom());
    }
    queueEl.innerHTML = list.map((it, i) => {
      let t = String(it.text || '').replace(/\s+/g, ' ').trim();
      // v3.1：事件路径入列的条目只有 att 附件计数（POST 乐观条目有完整数组）
      const nAt = ((it.images || []).length + (it.files || []).length) || (it.att || 0);
      if (nAt) t = (t ? t + ' ' : '') + '📎×' + nAt;
      if (t.length > 60) t = t.slice(0, 59) + '…';
      return `<div class="hg-q-item" data-i="${i}" title="${esc(it.text || '')}">` +
        `<span class="hg-q-grip" data-i="${i}" title="拖动排序（按住抓手上下拖）">⠿</span>` +
        `<span class="hg-q-text">${esc(t || '（空）')}</span>` +
        `<button class="hg-q-act" data-qact="now" data-i="${i}" title="中断当前回复，立即发送这条">↑ 立即</button>` +
        `<button class="hg-q-act" data-qact="edit" data-i="${i}" title="放回输入框编辑">✎</button>` +
        `<button class="hg-q-act" data-qact="del" data-i="${i}" title="丢弃">🗑</button>` +
        `</div>`;
    }).join('');
  }
  function queuePush(it) {
    // v3.1（#10）：排队输入升级为服务端 durable 账本——POST /queue 入队
    //（跨设备/跨重启可见，回合终结由后端自动泵真发）。id 客户端预生成并
    // 随 POST 提交（服务端直接采用）——SSE input_admitted 事件常先于 POST
    // 响应到达，同 id 去重是防双画的锚点；本地数组只是渲染缓存
    if (!it.id) it.id = 'q' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const key = _hgQueueKey();
    const arr = _HG.queues[key] = _HG.queues[key] || [];
    arr.push(it);
    renderQueue();
    showBanner('已排队：当前回复结束后自动发送', 2200);
    fetch('/api/harness/queue', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sid: _HG.sid, id: it.id, text: it.text || '',
                             images: it.images || [], files: it.files || [] })
    }).then(r => r.json()).then(j => {
      if (j && j.ok) {
        renderQueue();
      } else {
        // 入队失败（会话不在等）：回滚本地条目
        const cur = _HG.queues[key] || [];
        const i = cur.indexOf(it);
        if (i >= 0) cur.splice(i, 1);
        renderQueue();
        showBanner('排队失败：' + ((j && j.err) || '未知错误'), 2600, true);
      }
    }).catch(() => {
      const cur = _HG.queues[key] || [];
      const i = cur.indexOf(it);
      if (i >= 0) cur.splice(i, 1);
      renderQueue();
      showBanner('排队失败：网络错误', 2400, true);
    });
  }
  function queuePump() {
    // v3.1（#10）：泵已上移服务端（回合终结 _queue_pump 真发 + input_promoted
    // 事件通知）——前端只负责把队列条目按服务端事件同步渲染。此函数保留
    // 是 setBusy(false) 的既有调用点，职责退化为纯重渲
    renderQueue();
  }
  function qEndDrag(commit) {
    if (!qDrag) return;
    const d = qDrag;
    qDrag = null;
    d.item.classList.remove('dragging');
    queueEl.querySelectorAll('.drop-before,.drop-after')
      .forEach(x => x.classList.remove('drop-before', 'drop-after'));
    const key = _hgQueueKey();
    const list = (_HG.queues[key] || []).slice();
    if (commit && d.target != null && list.length > 1 && d.i < list.length) {
      const it = list.splice(d.i, 1)[0];
      let to = d.target - (d.target > d.i ? 1 : 0);   // 移除后目标下标左移
      to = Math.max(0, Math.min(list.length, to));
      list.splice(to, 0, it);
      _HG.queues[key] = list;
      // v3.1（#10）：新顺序上报服务端账本（后端泵按账本顺序出队；无 id
      // 的乐观条目——POST 未返回——由后续事件对齐，这里只发已有 id 的）
      const ids = list.map(x => x.id).filter(Boolean);
      if (ids.length)
        fetch('/api/harness/queue_act', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sid: _HG.sid, act: 'order', ids })
        }).catch(() => {});
    }
    renderQueue();
  }
  const _AGENT_LABEL = { executor: '执行者', coder: '编程者', designer: '设计者', dev: '开发', reviewer: '审核', 'general-purpose': '通用子代理' };
