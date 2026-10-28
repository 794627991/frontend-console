// harness relay.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function _hgGrantRewind() {
    // v3.5.78（用户需求「所有回合的结论都可回滚」）：逐组授予——每回合组的
    // 根区最后一条正文=该回合结论（中间正文定稿时已折进 tl 或被组内收回，
    // v3.2.4R(F4) 的 tl 不授约束由此天然成立）。旧实现只授全局末条=回滚重建
    // /续跑后只剩最后一个回合能回滚
    _hgFlow.querySelectorAll('.h-grp').forEach(g => {
      const ts = g.querySelectorAll(':scope > .h-msg.asst');
      const lastT = ts[ts.length - 1];
      if (lastT && lastT.dataset.rwa) lastT.classList.add('can-rewind');
    });
    // 组外散落正文（快照恢复等无组兜底路径）：维持原「全局末条」授予
    const last = _HG.lastAsstEl
      || [..._hgFlow.querySelectorAll('.h-msg.asst')].filter(el => !el.classList.contains('sub')).pop();
    if (last && last.isConnected && last.dataset.rwa && !last.closest('.h-grp') && !last.closest('.h-tl')) last.classList.add('can-rewind');
  }
  async function _hgReloadFlow() {
    const sid = _HG.sid;
    if (!sid) return;
    try {
      const j = await (await fetch('/api/harness/transcript?sid=' + encodeURIComponent(sid))).json();
      if (!j.ok || _HG.sid !== sid) return;
      // v3.4.70（复核 P1）：水位守卫捕获点必须在 **await 之后、resetLocal
      // 之前**——await 窗口内到达的 SSE 帧会抬高 _HG.seq（帧内容已入旧
      // DOM），resetLocal 清 0 后若水位回退到响应构建时的 j.seq，该帧不重
      // 发=单行暂缺。此处捕获含最新帧；resetLocal 后取 max（同 epoch）；
      // 换代（epoch 不同）旧空间作废从 j.seq 重起
      const _preSeq = _HG.seq, _preEp = _HG.epoch;
      // v3.2.1R(F6）：对齐 _hgSseRebuild 的清场——旧行映射（rowById/subBlk/
      // subRows/turnTicks）指向 innerHTML 替换后的游离节点，迟到事件会往游
      // 离行写徽章；epoch 同步换代水位（回滚必换代，带着旧 epoch 重开流会
      // 多吃一轮 ack reset 重建）。回滚后旧快照作废（存的是回滚前 DOM）
      // v3.5.198：清场不再删快照——删了之后 fetch/parse 窗口期切走时
      // saveCache 被 histRebuilding 守卫跳过=快照永久丢失，下次切回只能
      // 无快照冷开（清场白屏等 13MB fetch，用户 trace 实锤 15 次全量拉取
      // 连环白屏）。旧快照保留：恢复显示旧内容（总比白屏好）+ histStale
      // 机制强制重渲保正确性；新快照就绪时自然覆盖
      _hgSseResetLocal(true);      // v3.5.196：keepDom——旧内容保留到渲染器
                                   // 原子换入，消除清场白屏空窗
      _HG.histRebuilding = sid;    // 轻审 P2+复审 P3：sid 化按归属自清
      try {
      // v3.4.69d（轻审观察1收口）+ v3.4.70 P1 修正：同代水位不回退——await
      // 窗口内到达的 SSE 帧已入旧 DOM 并抬高水位，清场后若回退到响应构建时
      // 的 j.seq，该帧不重发=单行暂缺。用清场前捕获的 _preSeq 取 max（同
      // epoch）；换代（epoch 不同）旧空间作废从 j.seq 重起
      _HG.seq = (String(j.epoch || '') === String(_preEp || ''))
        ? Math.max(j.seq || 0, +_preSeq || 0) : (j.seq || 0);
      _HG.epoch = j.epoch || null; _HG.alive = !!j.alive;
      _HG.visionCalls = null; _HG.peerWait = null;
      if (!j.lines.length) showWelcome();
      else _histRender(j.lines, _hgHistWinStart(j.lines),
                       { noFinalize: _HG.busy });
        // v3.2.1R(F1)：尾组定稿在 _histRender 渲染器内（用户实测问题1）；
        // R2-2：await 在途抢发变 busy——尾组留给 grpEnsure 认回续跑（重渲
        // 抹活组是预存在问题，不放大成裂两组）
      if (!_HG.busy) setBusy(false);   // R2-2：await 在途变 busy 不清指示（事件流自会维护）
      // v3.4.69（用户实测 resync 后「回合头丢了」）：对齐 12-sessions:279 与
      // _hgSseRebuild:659 的既有模式——busy 会话渲染完必须 phResume 认回活组
      // （亮「工作中」头+续秒表），否则 resync 重渲后头永久隐藏（回放模式
      // _turnHeadShow 不亮头，见 07-hist:243 注释）
      if (_HG.busy) phResume(true); else grpFinalize(true, { hist: true, turnEnd: true });
      // v3.4.72（用户实锤「正在执行没有了」）：resetLocal 的 innerHTML='' 把
      // 流级 spinner 行（正在执行…）一起清掉，而本函数 busy 分支不重调
      // setBusy（actStart 不能重置）——直接 _hgSpinShow 幂等重建（在场即不
      // 重加；追加在组后，认回选择器已加固不受影响）
      _hgSpinShow(!!_HG.busy);
      // v3.4.69d（用户实锤「执行中的动态没有了」）：对齐 12-sessions:281/
      // _hgSseRebuild:660 的第三件配套——重渲后回填运行中子代理 live 档案
      // （_hgSseResetLocal 清了 agents，不回填=动态页/胶囊/秒表全静默）
      _hgLiveAgentsRestore(sid);
      renderSideStatus();
      _hgAskSync(sid);   // v3.4.61：回滚换代重建路——旧 ask 大概率失效，按后端快照校验（收面板/拉回）
      refreshSessions();
      _hgScrollBottom(true);
      _hgDiag('reload', '重渲完成 lines=' + j.lines.length + ' busy=' + !!_HG.busy + ' phResume/live 档案已回填');
      // v3.4.69：对齐 12-sessions 回底模式——渲染后图片懒加载/占位补画仍会
      // 撑高 flow，两帧 + 600ms 终兜确保重渲后贴底
      requestAnimationFrame(() => requestAnimationFrame(() => _hgScrollBottom(true)));
      setTimeout(() => { if (_HG.sid === sid) _hgScrollBottom(true); }, 600);
      // v3.4.68R3：重渲出口同挂覆盖度自检（自愈的渲染也自检——清场竞速若吞
      // 重渲成果，此处是最后一道网）
      setTimeout(() => _hgCoverageAudit(sid, j.lines.length, 'reload-flow'), 1200);
      } finally { if (_HG.histRebuilding === sid) _HG.histRebuilding = null; }
    } catch(e) {
      // v3.4.69e（用户实锤「切回后真的什么都没有了」）：重渲失败不得静默——
      // 此刻 flow 已被 resetLocal 清空，吞错=永久空白。页面可见+控制台留痕，
      // 并回退拉一次转写重试渲染（再失败至少 banner 指路手动刷新）
      try { console.error('[harness] reload-flow failed:', e); } catch(_) {}
      try { showBanner('消息流重建失败（' + (e && e.message || e) + '），正在重试…', 4000, true); } catch(_) {}
      try {
        const j2 = await (await fetch('/api/harness/transcript?sid=' + encodeURIComponent(sid))).json();
        if (j2.ok && _HG.sid === sid && j2.lines.length)
          _histRender(j2.lines, _hgHistWinStart(j2.lines), { noFinalize: _HG.busy });
        if (_HG.busy) { phResume(true); _hgDiag('reload', '重试渲染完成，busy 头已补亮'); }
      } catch(_) { try { showBanner('重建仍失败，请手动刷新页面', 6000, true); } catch(_) {} }
    }
  }
  // v3.4.79（用户定调「中断/退出散行全部整合进回合」）：raw/exit 行不再散落
  // 消息流顶层（组外），挂进当前组时间线（renderAudit 同款）——点开回合头
  // 就能看到「实际是被中断的」。
  // v3.4.79R（复核 P1/P4）：去重锚**按组**存（root.dataset.lastSys）——模块级
  // 锚会跨组残留吞掉下一回合同文案行（第二次中断/退出整行消失）；无组上下
  // 文（散行）不去重，动态错误行（renderRaw 的 subtype/result 变体）不误伤
  function _sysRowIntoGroup(d) {
    const g = (_HG.grp && _HG.grp.root
               && (_HG.grp.root.isConnected || _HG.histBuilding)) ? _HG.grp : null;
    if (g && g.tl) {
      const fp = (d.textContent || '').slice(0, 24);
      // v3.4.83（复核 P4 残留收口）：sysnote 豁免去重——skill-doc 行文案恒同
      //（摘要只在 title），同组第二条会被 24 字前缀锚整行吞掉（含全文 title）
      if (fp && g.root.dataset.lastSys === fp && !d.classList.contains('h-sysnote')) return false;
      g.root.dataset.lastSys = fp;
      _tlExpFlush(!!_HG.openState);
      // v3.4.80（复核 P1）：空组的 tl 是内联 display:none（grpFromDom 对
      // children=0 落的）——append 后不翻转则行困在里面，点开折叠体依旧
      // 空壳（头「已停止」但看不见中断行）
      if (g.tl.style.display === 'none') g.tl.style.display = '';
      g.tl.appendChild(d);
      return true;
    }
    // v3.4.79R（复核 R1）：终结复合帧（interrupted+exit 双帧）第二帧到达时
    // 活组已被前一帧定稿收回（_HG.grp=null）——三级回落：直接落**尾组**
    // 时间线（不改 finalized 语义，仅插行；「会话进程已结束」等散行就此
    // 归位回合折叠体），无组才 addRow 根区
    const lastGrp = [..._hgFlow.querySelectorAll('.h-grp')].pop() || null;   // 复核 F-B：项目惯用法（last-of-type 选择器族脆弱）
    const lastTl = lastGrp && lastGrp.querySelector('.h-tl');
    if (lastTl) {
      const fp = (d.textContent || '').slice(0, 24);
      if (fp && lastGrp.dataset.lastSys === fp && !d.classList.contains('h-sysnote')) return false;
      lastGrp.dataset.lastSys = fp;
      if (lastTl.style.display === 'none') lastTl.style.display = '';   // v3.4.80 P1 同款
      lastTl.appendChild(d);
      return true;
    }
    addRow(d);
    return true;
  }
  function renderRaw(text) {
    const d = document.createElement('div'); d.className = 'h-raw'; d.textContent = text;
    if (!_sysRowIntoGroup(d)) return;
    _hgScrollBottom();
  }
  function renderExit(text) {
    const d = document.createElement('div'); d.className = 'h-exit'; d.textContent = text;
    if (!_sysRowIntoGroup(d)) return;
    _hgScrollBottom();
  }
  function renderSwitch(model) {
    const d = document.createElement('div'); d.className = 'h-switch';
    d.innerHTML = '<span></span><i>已切换模型 · ' + esc(model) + '</i><span></span>';
    addRow(d);
    _hgScrollBottom();
  }
  function renderRenew(text) {
    // a118（用户定调「压缩不许分割回合」）：组在场挂组时间线（时序与思考/
    // 工具同列，v3.2.27 renderAudit 同款）；组外（compact 先于任何用户消息
    // 的罕见形态）维持旧根部居中分割线
    const d = document.createElement('div'); d.className = 'h-switch hg-renew';
    d.innerHTML = '<span></span><i>♻️ ' + esc(text) + '</i><span></span>';
    // v4.0.6（复审实锤）：不再信任 histBuilding——重建期 _HG.grp 可能指向
    // 即将被 replaceChildren 丢弃的旧 DOM，append 进去等于丢失。只认已连接。
    const g = (_HG.grp && _HG.grp.root && _HG.grp.root.isConnected) ? _HG.grp : null;
    if (g && g.tl) {
      _tlExpFlush(!!_HG.openState);
      // 同上：空组/纯思考组的 tl 是内联 display:none——直接 append 会困在
      // 不可见容器里（旧 addRow 恒可见）。同 _sysRowIntoGroup 的翻显处理。
      if (g.tl.style.display === 'none') g.tl.style.display = '';
      g.tl.appendChild(d);
      _hgScrollBottom();   // 组内分支不再走 addRow，需自补贴底
    } else {
      addRow(d);
    }
  }
  function renderAudit(text) {
    // v3.2.27（用户定调「警告记录到工作区内，不许分割消息流」）：审计警示
    // 不再独立占位于消息流根部（旧形态在用户气泡与回合间插卡 + 先行定稿，
    // 把同一条会话的工作区割成多段）——挂进当前回合时间线，按发生时序落
    // 在思考/工具之间；回合外（罕见：回合间补审）维持旧根部形态
    const d = document.createElement('div');
    d.className = 'h-audit';
    d.textContent = text;
    const g = (_HG.grp && _HG.grp.root
               && (_HG.grp.root.isConnected || _HG.histBuilding)) ? _HG.grp : null;
    if (g && g.tl) {
      _tlExpFlush(!!_HG.openState);
      g.tl.appendChild(d);
    } else {
      addRow(d);
    }
  }
  // v3.3.2(D6/D7)：机器注入（task-notification/system-reminder）弱化行——
  // 单行 dim 入组时间线（不切割回合）；摘要取 <summary>/<result> 首行截
  // 80 字（主流唯一锚点，详情由协作段/动态页承接）；悬浮 title=全文。
  // 完整开闭标签对由调用方判定。历史回放（07-hist sysnote 分支）同走此处
  function renderSysNote(kind, text) {
    const t = String(text || '');
    const _m = t.match(/<summary>([\s\S]*?)<\/summary>/i)
      || t.match(/<result>([\s\S]*?)<\/result>/i);
    let sum = (_m ? _m[1] : '').replace(/\s+/g, ' ').trim();
    if (sum.length > 80) sum = sum.slice(0, 80) + '…';
    const d = document.createElement('div');
    d.className = 'h-sysnote';
    d.textContent = (kind === 'task-notification' ? '任务通知' : '系统提示')
      + (sum ? ' · ' + sum : ' · 已注入当前回合上下文');
    d.title = t.slice(0, 2000);
    // v3.4.82R（复核 P4）：归组统一走 _sysRowIntoGroup——空组 display:none
    // 翻转/尾组回落同享，不再各持一份 append 逻辑
    _sysRowIntoGroup(d);
  }
  // ==================== v3.4.88：识图 MCP 调用折叠卡（统一工作组风格）====================
  // 用户定调：识图对（转交+回传）与 Bash/思考同语言——emoji+名+摘要+状态徽章
  // 折叠卡，入回合时间线，点开见完整 prompt 与回传全文。旧线（.h-switch）与
  // 气泡对识图退役；renderPeerRelay/renderPeer 保留（非识图隐藏线+旧会话遗留
  // 识图广播兜底）。卡承接旧线全部 dataset 契约（peer/t0/done/psum/vsid）+
  // .hg-peer-t 计时钩子——_hgPeerTimerStart/面板/等待语义零改
  function _hgVisionSeq() {
    return _hgFlow.querySelectorAll('.h-tool.h-vision').length + 1;   // DOM 派生序（视窗内相对序）
  }
  function _hgVisionPaint(el, state, durTxt) {
    const st = el && el.querySelector('.h-vision-state');
    if (!st) return;
    // 图 42 修（「两个时间」）：定格态隐藏 .hg-peer-t 秒表钩子——用时已
    // 并入徽章，双表并存叠压
    const _tb = el.querySelector('.hg-peer-t');
    if (_tb) _tb.style.display = (state === 'run') ? '' : 'none';
    const _m = {
      run: '<span class="h-tbadge b-run">识图中</span>',
      done: '<span class="h-tbadge b-done">已回传' + (durTxt ? ' · 用时 ' + esc(durTxt) : '') + '</span>',
      err: '<span class="h-tbadge b-err">识图失败' + (durTxt ? ' · 用时 ' + esc(durTxt) : '') + '</span>',
      dead: '<span class="h-tbadge b-warn">未回传（回合已结束）</span>',
      unfinished: '<span class="h-tbadge b-warn">历史未完成</span>',
      stale: '<span class="h-tbadge b-warn">疑似残留</span>'
    };
    st.innerHTML = _m[state] || '';
  }
  function _hgVisionCardBuild(input) {
    input = input || {};
    const card = document.createElement('div');
    card.className = 'h-tool col oneclick h-vision';
    card.dataset.hgKind = 'vision';
    card.dataset.peer = '识图';
    card.dataset.vsid = _HG.sid || '';
    card.dataset.t0 = String(Date.now());
    const tid = input.__tid || '';
    if (tid) card.dataset.tid = tid;
    card.dataset.vseq = String(_hgVisionSeq());
    card.dataset.vprompt = String(input.prompt || '').slice(0, 4000);
    card.dataset.vsrc = String(input.imageSource || '').slice(0, 600);
    card.dataset.vchan = input.__chan || '主';
    const _pSum = String(input.prompt || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    card.innerHTML =
      '<button class="h-tool-head"><span class="h-chev h-tool-chev">▸</span>' +
      '<span class="h-tool-name">识图 #' + esc(card.dataset.vseq) + '</span>' +
      `<span class="h-tool-arg" title="${esc(card.dataset.vprompt)}">${esc(_pSum || '识图中…')}</span>` +
      '<span class="h-vision-state"></span>' +
      '<b class="hg-peer-t">0s</b></button>' +
      '<div class="h-tool-coll"></div>';
    _hgVisionPaint(card, 'run');
    return card;
  }
  // 定格（吸收旧 _hgVisionFreeze 的转交线语义）：回传到达/失败/回放配对——
  // 停表+徽章+全文懒存 dataset.vres（点开渲染，省快照体积）
  function _hgVisionResult(el, text, err) {
    // 全审 P0：回放渲染期卡在游离缓冲（isConnected=false）——histBuilding
    // 双判放行（08-tools.js:361 既有同款解法）
    if (!el || (!el.isConnected && !_HG.histBuilding)) return;
    _hgPeerLineStop(el);
    // 全审 P7：dur 优先卡上已有的精确 done-t0（回放 relay 行的 l.dur 定格
    // 值），墙钟差值仅 live 兜底；err 带过（relay 行 err 已落 dataset.verr）
    const _d0 = +(el.dataset.t0 || 0), _d1 = +(el.dataset.done || 0);
    const dur = (_d1 > _d0)
      ? _hgFmtDur((_d1 - _d0) / 1000)
      : _hgFmtDur((Date.now() - (_d0 || Date.now())) / 1000);
    if (!(_d1 > _d0)) el.dataset.done = String(Date.now());
    delete el.dataset.unknown;
    delete el.dataset.stale;
    el.dataset.vres = String(text || '');
    if (err || el.dataset.verr === '1') el.dataset.verr = '1';
    el.dataset.psum = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 120);
    _hgVisionPaint(el, (err || el.dataset.verr === '1') ? 'err' : 'done', dur);
    // 全审 P2：pending 期点开过的卡已落 filled='1'（「未回传」占位）——
    // 回传到达必须破除守卫重填，否则正文永久停留占位与徽章矛盾
    const _coll = el.querySelector('.h-tool-coll');
    if (_coll) delete _coll.dataset.filled;
    if (el.classList.contains('open')) _hgVisionFillBody(el);   // 已展开即刻填
    renderSideStatus();
  }
  // 折叠体填充（懒渲染：prompt esc 直渲 + 回传 renderMd）
  function _hgVisionFillBody(el) {
    const coll = el.querySelector('.h-tool-coll');
    if (!coll || coll.dataset.filled === '1') return;
    coll.dataset.filled = '1';
    const src = el.dataset.vsrc || '';
    let srcChip = '';
    if (src) {
      let disp = src;
      try { disp = decodeURIComponent(String(src).split('?')[0].split('/').pop() || src); } catch (_) {}
      srcChip = `<div class="h-vision-src" title="${esc(src)}">📎 ${esc(String(disp).slice(0, 60))}` +
        ` <span class="h-vision-chan">${esc(el.dataset.vchan || '主')}</span></div>`;
    }
    const res = el.dataset.vres;
    coll.innerHTML =
      '<div class="h-vision-req"><div class="h-vision-lb">📤 发给 MCP 的提示词</div>' +
      `<pre class="h-vision-pre">${esc(el.dataset.vprompt || '（旧转写未记录提示词）')}</pre>` + srcChip + '</div>' +
      '<div class="h-vision-res"><div class="h-vision-lb">📥 回传结论</div>' +
      '<div class="h-vision-md"></div></div>';
    const md = coll.querySelector('.h-vision-md');
    if (md) {
      if (res != null && res !== '') { try { md.innerHTML = renderMd(res); } catch (_) { md.textContent = res; } }
      else md.innerHTML = '<span class="h-vision-empty">' +
        (el.dataset.verr === '1' ? '⚠ 识图失败' : '（未回传）') + '</span>';
    }
  }
  function _hgVisionSweep(dead) {
    const vc = _HG.visionCalls;
    if (!vc) return;
    // v3.4.54：sid 归属校验——B 会话的 result/interrupted/exit 不再算清
    // A 的 pending 识图线（切回 A 靠事件重放重建追踪，snapshot 路径
    // 10-sse 建线同样执行）
    for (const id in vc) {
      const el = vc[id];
      if (el && el.dataset.vsid !== (_HG.sid || '')) continue;
      if (el) {
        el.dataset.done = String(Date.now());   // v2.35：未回传也定格（面板协作行收口）
        _hgVisionPaint(el, dead ? 'dead' : 'unfinished');
        _hgPeerLineStop(el);              // v2.35.2（P1 多槽）：各线停各的计时器
      }
    }
    _HG.visionCalls = null;
  }
  function renderVisionRelayHist(l) {
    // v3.5.244（用户实锤「明确识图过的回合头部无识图计数」）：hist 路径
    // （方案B回合终重渲/切回重渲）同样计数 counts.visionN 并刷副位——
    // v3.5.237 只挂了 live 路径（10-sse 建档处），重渲后组 counts 重建
    // 时识图归零（转写 vision_relay=62 行实证 hist 是重渲后唯一来源）
    try {
      const _gv = _HG.grp || (typeof grpEnsure === 'function' && grpEnsure(true));
      if (_gv) {
        _gv.counts = _gv.counts || {};
        _gv.counts.visionN = (_gv.counts.visionN || 0) + 1;
        if (typeof _turnHeadSubPaint === 'function') _turnHeadSubPaint(_gv);
      }
    } catch (_) {}
    // v3.4.88：回放同构卡（v2.28 线退役）——dur 在手直接定格；tid 注册进
    // visionCalls 供后续 peer 行精确配对（无 tid=旧转写，回落时间邻接配对）
    const card = _hgVisionCardBuild({
      prompt: l.prompt || '', imageSource: l.src || '', __tid: l.tid || '', __chan: l.chan || ''
    });
    const t0 = l.ts ? (Date.parse(l.ts) || 0) : 0;
    if (t0) card.dataset.t0 = String(t0);
    if (l.tid) _HG.visionCalls = _HG.visionCalls || {},
      _HG.visionCalls[l.tid] = card;
    if (l.dur != null) {
      card.dataset.done = String(t0 + Math.max(0, l.dur) * 1000);
      card.dataset.psum = l.err ? '识图失败' : '已回传';
      if (l.err) card.dataset.verr = '1';
      _hgVisionPaint(card, l.err ? 'err' : 'done', _hgFmtDur(l.dur));
    } else if (_HG.histBusy && l.tid) {
      // v3.5.8（用户实锤「A 切 B 再切 A 显示历史未完成，实际还在识图」）：
      // busy 活会话的未回传卡=识图仍在跑——复活 run 态+续表（tid 已注册
      // visionCalls，回传经 SSE 到达即正路定格；不设 done/psum 防误判死案）
      _hgPeerTimerStart(card, t0 || Date.now());
    } else {
      card.dataset.done = String(t0 || Date.now());
      card.dataset.psum = '历史未完成（未回传）';
      _hgVisionPaint(card, 'unfinished');
    }
    // 全审 P1：与 live 同挂组时间线（非 explore 名直挂）——形态统一
    _tlPlace(card, '_vision', null);
  }
  function renderPeerRelay(to, t0ms) {    // 📤 已转交分割线（带等待计时）
    // v2.35.2（P1 多槽）：不再「新转交接管旧等待」——每条线自己的计时器自己
    // 走（此前新线会停掉旧线的表，旧线读秒冻死在半途；并发转交各对各的线）
    const d = document.createElement('div'); d.className = 'h-switch';
    d.innerHTML = '<span></span><i>📤 已转交 ' + esc(to || '其他会话') +
      ' · 等待结论回传 · <b class="hg-peer-t">0s</b></i><span></span>';
    addRow(d);
    const t0 = t0ms || Date.now();        // v2.3.2：历史重建传行内 ts（真实起点）
    d.dataset.t0 = String(t0);            // 快照恢复后重启计时用
    d.dataset.peer = to || '其他会话';     // v2.35：协作方名进 dataset——面板协作行/等待态派生 + 快照序列化
    renderSideStatus();                   // v2.35：面板协作行 + 输入框等待态跟随
    _hgPeerTimerStart(d, t0);
    _hgScrollBottom();
    return d;                             // v2.28.3：识图多调用并发时按 id 对线
  }
  function _hgPeerTimerStart(d, t0) {
    const tb = d.querySelector('.hg-peer-t');
    if (!tb) return;
    if (d._peerTimer) clearInterval(d._peerTimer);
    const timer = setInterval(() => {
      if (!tb.isConnected) { clearInterval(timer); return; }
      tb.textContent = _hgFmtDur((Date.now() - t0) / 1000);
    }, 1000);
    d._peerTimer = timer;
    _HG.peerWait = { el: d, t0, timer };
  }
  function _hgPeerLineStop(el) {
    if (el && el._peerTimer) { clearInterval(el._peerTimer); el._peerTimer = null; }
    if (_HG.peerWait && _HG.peerWait.el === el) _HG.peerWait = null;
  }
  function _hgPeerLineFreeze(el, psum) {
    if (!el || !el.isConnected) return;
    _hgPeerLineStop(el);
    const i = el.querySelector('i');
    const dur = _hgFmtDur((Date.now() - (+(el.dataset.t0 || 0) || Date.now())) / 1000);
    if (i) i.innerHTML = '📤 已转交 · 📥 已回传 · 用时 ' + dur;
    el.dataset.done = String(Date.now());
    // v2.41：定格即已回传——清 unknown/stale 残留标记。不清则迟到的真实
    // 回传打在 unknown 线上后标记滞留：面板 C 区过滤（不显 unknown/stale 线）
    // 会把「已回传」误埋掉，协作行行尾也错显「状态未知」而非用时
    delete el.dataset.unknown;
    delete el.dataset.stale;
    if (psum) el.dataset.psum = String(psum).replace(/\s+/g, ' ').trim().slice(0, 120);
    renderSideStatus();
  }
  function _hgPeerFreezeByName(name, text, strict) {
    // v2.35.2（R1）：排除仍被识图链路跟踪的线——并行多图各线 data-peer 同为
    // 「识图」，按名配对会误冻还在跑的兄弟线；本线 result 到达时已从
    // visionCalls delete（:2353），自身定格不受影响
    const lines = _hgPeerLines().filter(el => !el.dataset.done
        && !(_HG.visionCalls && Object.values(_HG.visionCalls).includes(el)));
    if (!lines.length) return null;
    const hit = name && lines.find(el => (el.dataset.peer || '') === name);
    if (!hit) {
      // v2.37（P1-F②）：strict 只许按名精确配对——协作包装的 task_notification
      // 用；不命中不许误冻无关在途线
      if (strict) return null;
      _hgPeerLineFreeze(lines[0], text);
      return lines[0];
    }
    _hgPeerLineFreeze(hit, text);
    return hit;
  }
  function _hgPeerVerifyPending() {
    const pend = _hgPeerLines().filter(el => !el.dataset.done);
    if (!pend.length || !_HG.sid) return;
    // R6 复审 C：核实上限 10 条显式化——超出部分标「未核实」（≠「状态未知」，
    // 没查过不许冒充查过）
    const checked = pend.slice(0, 10);
    const rest = pend.slice(10);
    const sidAt = _HG.sid;
    const sinces = checked.map(el => el.dataset.t0 || 0);
    fetch(`/api/harness/peer_result_check?sid=${encodeURIComponent(sidAt)}&peers=${encodeURIComponent(checked.map(el => el.dataset.peer).join(','))}&sinces=${encodeURIComponent(sinces.join(','))}`)
      .then(r => r.json())
      .then(j => {
        if (!j || !j.ok || _HG.sid !== sidAt) return;
        let changed = false;
        // R6 复审 B：端点只认 timestamp ≥ 线起点的 result（旧回合不算）——
        // found=True 才定格「已回传（转写核实补记）」；其余标「状态未知」，
        // unknown 一并清 stale（G：先 stale 后 verify 两处口径统一）
        for (const el of checked) {
          if (el.dataset.done || !el.isConnected) continue;
          if (j.results && j.results[el.dataset.peer]) {
            el.dataset.done = String(Date.now());
            // v2.41R2：unknown 必须一并清——上一回合标过 unknown 的线本次核
            // 实命中补记 done 时，若残留 unknown 会被面板 C 区过滤（不显
            // unknown/stale 线）误埋，「已回传（转写核实补记）」行消失。与
            // _hgPeerLineFreeze 的清标记保持同一不变量：定格即清残留标记
            delete el.dataset.unknown;
            delete el.dataset.stale;
            _hgPeerLineStop(el);
            const i0 = el.querySelector('i');
            if (i0) i0.innerHTML = '📤 已转交 · 📥 已回传（转写核实补记）';
            el.dataset.psum = '（转写核实补记：回传已发生）';
          } else {
            el.dataset.unknown = '1';
            delete el.dataset.stale;
            _hgPeerLineStop(el);
            const i1 = el.querySelector('i');
            if (i1) i1.innerHTML = '📤 已转交 · 状态未知（回合已结束，回传未在转写中确认）';
          }
          changed = true;
        }
        for (const el of rest) {
          if (el.dataset.done || !el.isConnected) continue;
          el.dataset.unverified = '1';   // 没查过：独立标记，不冒充状态未知
          changed = true;
        }
        if (changed) renderSideStatus();
      }).catch(() => {});
  }
  const _PEER_STALE_MS = 30 * 60 * 1000;   // 30 分钟显示上限
  function _hgPeerStaleSweep() {           // 秒表 tick 内逐秒巡检（cheap）
    _hgFlow.querySelectorAll('.h-switch[data-peer]:not([data-done]):not([data-stale]), .h-tool.h-vision[data-peer]:not([data-done]):not([data-stale])').forEach(el => {
      const t0 = +(el.dataset.t0 || 0);
      if (t0 && Date.now() - t0 > _PEER_STALE_MS) {
        el.dataset.stale = '1';
        if (el._peerTimer) { clearInterval(el._peerTimer); el._peerTimer = null; }
        if (el.classList.contains('h-vision')) _hgVisionPaint(el, 'stale');
        else {
          const i = el.querySelector('i');
          if (i) {
            const nm = el.dataset.peer || '其他会话';
            i.innerHTML = '📤 已转交 ' + esc(nm) + ' · 疑似残留，点击核实（等待超 30 分钟）';
          }
        }
      }
    });
  }
  function _hgPeerWaitStop(done) {        // 回传到达=定格用时；切会话=静默清理
    const w = _HG.peerWait; _HG.peerWait = null;
    if (!w) return;
    clearInterval(w.timer);
    if (w.el) w.el._peerTimer = null;
    if (done && w.el && w.el.isConnected)
      _hgPeerLineFreeze(w.el);            // 单槽兼容路径（不携带摘要——摘要走按名配对）
  }
  function renderPeer(name, text, to, noDedup, hist) {  // 📥 回传气泡（区别于 user/AI）
    // 401 兜底：SubagentHandback 信封不进任何回传可视化（四重防线之末）
    if (String(text || '').indexOf('[Subagent hand-back]') >= 0
        || String(name || '').indexOf('[Subagent hand-back]') >= 0) return;
    // hist=true：历史回放路径（renderHistLine）——绝不开新段（v2.53 教训：
    // 重启重建历史时每条回传都新建「协作·xx 运行中」假段，正文吞进折叠壳，
    // 主链看似丢消息），回传归入对应已完成段；miss 则平铺气泡（原回退）
    // v2.3.2：代播回传带 to（收件人 peer 名）——防串台污染。
    // v2.3.10 修致命错位（用户实锤"回传到了界面没有"）：to 是回信方写的
    // 收件人名（本会话 CLI 名如 pro-62），而转交线上写的是发信时的收件人
    // （识图会话）——两个名字方向相反，旧门控拿 to 匹配转交线必失败，
    // 代播回传被静默丢弃。改为：有任一未定格转交线即收（会话只在自己
    // 等结论时才会收到代播，且去重已兜双份；名不匹配的极端串台由
    // name 头标自说明，不再静默吞）。
    // R6 复审 H：门控补 unknown 线——「状态未知」文案替换掉「等待结论回传」
    // 后，to 门控按文本找会丢；迟到的真实回传仍要能被接收渲染。
    if (to) {
      // v3.4.88：选择器并入识图卡 + 判据 dataset 化（原 textContent 文本判据脆弱）
      const waiting = [..._hgFlow.querySelectorAll('.h-switch[data-peer], .h-tool.h-vision[data-peer]')]
        .some(el => !el.dataset.done
          && (el.dataset.unknown === '1' || el.dataset.stale === '1'
            || el.classList.contains('h-switch')));   // 旧线无 unknown 标=仍在等待文案
      if (!waiting) return;
    }
    // 去重：主会话自身 jsonl 检测与代播可能双份（空闲期回传两条链都通）。
    // R6 复审 F：历史回放路径跳过 60s 窗判重——连续多条历史回传内容相近时
    // 会被误吞（转写里每一行都是独立事实，不存双发歧义）
    if (!noDedup) {
      const sig = (text || '').slice(0, 120);
      if (renderPeer._seen && renderPeer._seen.t === sig &&
          Date.now() - renderPeer._seen.at < 60000) return;
      renderPeer._seen = { t: sig, at: Date.now() };
    }
    // v2.35.2（P1 多槽）：回传按协作方名配对定格对应转交线——并发转交/
    // 交错回传（relay1,relay2,peer1,peer2）各对各的线不串；摘要随定格写入
    // dataset（面板协作行「已回传」展示用，随快照序列化切会话可派生）
    _hgPeerFreezeByName(name, text);
    // v3.2.15（用户实锤「为什么没有归纳在一个会话内」）：协作回传不再定稿
    // 主回合组——SendMessage 等回传属同一用户回合的中途接力（模型回合没
    // 结束），旧 grpFinalize 把一条用户消息拆成 N 个「已工作」头；回传本体
    // 走 v2.49 归一进子代理段，无需回合边界。真回合边界照旧：result/下一
    // user 行的定稿路径不受影响
    endThinking(); closeRun();
    // v2.49：协作归一——SendMessage 协作回传全文入对应子代理段（替代独立
    // 回传气泡）。v2.53（用户定调）：非识图回传**禁止平铺气泡**——定位不到
    // 批2（迁出主窗）：协作回传入段/建段退役——段不存在（live 全程零
    // .h-subblock）；回传走下方平铺气泡（完整正文，信息零丢失），批3 改
    // 单行通知行；识图转交/回传例外原样
    const _nm = String(name || '其他会话');
    // v3.4.68R4（用户实锤「切B切回A 工作中的显示全没了」致命复发根因）：本地
    // 子代理续派的回报（from=自家 reviewer agentId）在历史重建里配对 miss
    // （v3.4.68 起续派不建线）——旧路径「miss 一律建段」会在**游离缓冲渲染期**
    // 走 _subBlkGet 建段，段头动作钮/秒表 Painter 引用游离态不存在的元素抛
    // 异常，行级隔离放行后共享渲染状态被污染，**当前轮后续行连续失败**（实测
    // 恰 4 行：thinking/assistant/tool/tool），覆盖度审计 gap=4≤5 漏触发——
    // 双重失守=「全没了且无 banner」。本地回报直接忽略（主回合已消费该报告）
    if (!_nm.includes('识图') && _hgLocalResendPeer(_nm)) return;
    // 批3→a17（用户拍板「彻底删除这种胶囊！这是屎山」）：协作回传通知行
    // （.h-sub-notify「📥 协作回传·xx：」）整体退役——主窗消息流不画任何
    // 回传胶囊；结论完整态的载体=Agent 工具行卡（subagent_result 回写）与
    // 对端转写（点卡 _subReplay），通知行是冗余第二通道。转交线定格
    // （_hgPeerFreezeByName，上方已执行）照旧——「已转交」线收到结论即
    // 定格收口，视觉链完整
    if (!_nm.includes('识图')) return null;
    // 422b（用户实锤「识图回传怎么又变成这样了——最早的平铺方案早废弃」）：
    // 识图回传不走平铺气泡（.h-peer 头像+标题+正文=旧 v2.x 形态）——v3.4.88
    // 定调回传整合进识图卡（_hgVisionResult 定格+卡内结论）。本函数是 relay
    // 直调路径（live peer 事件），此前漏掉识图分流（dispatch 路径的
    // peer_return case 有 visionCalls 配对，本路径没有）→ 识图名落此=旧形态
    // 复现。分流：pending 识图卡逐个配对（tuid/FIFO 与 case 同口径），全
    // miss 落通知行（.h-sub-notify，非平铺）
    if (String(name || '').indexOf('识图') !== -1) {
      let _vc = null;
      const _open = [..._hgFlow.querySelectorAll('.h-tool.h-vision:not([data-vres])')];
      if (text && text.tid && _HG.visionCalls && _HG.visionCalls[text.tid]) _vc = _HG.visionCalls[text.tid];
      else _vc = _open[0] || null;
      if (_vc) {
        try { _hgVisionResult(_vc, String(text && text.text || text || ''), false); } catch (_) {}
        if (text && text.tid && _HG.visionCalls) delete _HG.visionCalls[text.tid];
        return null;
      }
    }
    // 424（用户拍板「平铺气泡路子彻底删掉」）+ a17（用户拍板「协作回传胶囊
    // 彻底删除！这是屎山」）：.h-peer 平铺与 .h-sub-notify 通知行双双退役。
    // 识图 miss（卡已不在场）同样静默——结论完整态在对端转写/工具行卡
    return null;
  }
  function renderCompaction(done) {
    // v3.5.51（designer B2）：只读模式防污染——压缩计时器 tick 会把「正在
    // 压缩」线 addRow 进当前 flow；RO 期间写入即跨视图污染，退出 rebuild
    // 后 timer 下一 tick 自愈重建该线，状态零损
    if (_HG.readonly) return;
    let el = _hgFlow.querySelector('.h-switch[data-hg-compact]');
    if (!done && !el) {
      // v2.3.13：压缩分割线只归发起压缩的会话。压缩中切到别的会话，1s 计时器
      // 仍在跑，会在「当前打开的 flow」（=别的会话消息流）里新建「正在压缩」
      // 线并冻进它的快照（用户实锤「当前会话压缩，另一个会话也出现压缩显示」）。
      if (_HG.compactSid && _HG.compactSid !== _HG.sid) return;
      el = document.createElement('div');
      el.className = 'h-switch';
      el.dataset.hgCompact = '1';
      el.innerHTML = '<span></span><i></i><span></span>';
      addRow(el);
    }
    if (!el) return;
    const secs = _HG.compactT0 ? _hgFmtDur((Date.now() - _HG.compactT0) / 1000) : '';
    // v2.28.4：压缩来源两途——窗口临近自动触发，或 /compact 手动触发
    // （CLI 2.1.267 实测 headless 下斜杠命令真实执行），分割线统一渲染，
    // 带上压缩前规模（用户问过「为啥 150K 就压」，信息透明少猜谜）
    const scale = _HG.compactUsed ? ' · 压缩前约 ' + (_HG.compactUsed / 1000).toFixed(0) + 'K tokens' : '';
    el.querySelector('i').textContent = done
      ? '上下文压缩完成' + scale + ' · 用时 ' + secs
      : '正在压缩上下文 · 已 ' + secs + scale;
    _hgScrollBottom();
  }
  function _hgCompactionEnd() {
    if (!_HG.compacting) return;
    // v3.4.52（致命双会话实锤）：compactResume 改存**归属会话 sid**——
    // 全局 true 会被其它会话的工作事件误消费（B 乱 reopen 自己的组=A/B
    // 双开会话互切后 B 结构错乱/A 组丢失的污染链）。置位在 compactSid
    // 清空之前取归属
    _HG.compactResume = _HG.compactSid || null;
    _HG.compacting = false;
    _HG.compactSid = null;
    clearInterval(_HG.compactTimer);
    renderCompaction(true);
    // v2.27.4：status 恢复事件若丢（result 兜底到这里），活动词一并退出特殊态
    actWord(null);
  }
