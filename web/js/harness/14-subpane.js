// harness subpane.js (v3.0 自 buildClaudeHarnessTab 拆出;v3.2.6 窗格时间线重写——ZCode 子智能体模式)
  const _sub = { tabs: {}, order: [], active: null, manual: false };
  // ==================== v3.2：子智能体目录（ZCode SubagentDirectorySidePane 移植）====================
  // 目录是一个常驻伪 tab（__dir__）：正在运行/已结束两组列表，行卡=状态图标+
  // 标题+状态词+摘要+相对时间；点行开该代理视图 tab（live 直开 / 已结束走回放）。
  // 数据源=live 档案 _HG.agents + 回放档案 dyn.agentsRpl（对照 useSessionSubagents
  // 的 running/ended 两段口径，我们无分页——量级远小于 ZCode 云端）
  const _SUB_DIR = '__dir__';
  function _subDirRows() {
    const rows = [];
    for (const tid in (_HG.agents || {})) {
      const a = _HG.agents[tid];
      if (!a || a.replay) continue;
      rows.push(Object.assign({ tid }, a));
    }
    for (const a of ((_HG.dyn && _HG.dyn.agentsRpl) || [])) {
      // rid 补发（与 _dynAgents 同款持久发号——条目点击按 rid 回查存档）
      if (!a.rid) a.rid = 'rpl' + ((_HG.rplSeq = (_HG.rplSeq || 0) + 1));
      rows.push(Object.assign({ tid: a.rid, rpl: true }, a));
    }
    const running = rows.filter(r => !r.done).sort((x, y) => (x.t0 || 0) - (y.t0 || 0));
    const ended = rows.filter(r => r.done)
      .sort((x, y) => (y.doneAt || 0) - (x.doneAt || 0)).slice(0, 30);
    return { running, ended };
  }
  function _subDirRowHtml(r) {
    // 状态三态（对照 StatusIcon）：运行 spinner / 成功 ✓ / 失败 ✗ / 中断 ⏹
    const st = !r.done ? 'run' : (r.interrupted ? 'stop' : (r.err ? 'err' : 'ok'));
    const stIco = { run: '◐', ok: '✓', err: '✗', stop: '⏹' }[st];
    const stTxt = { run: '运行中', ok: '已完成', err: '已失败', stop: '已中断' }[st];
    const title = ((_AGENT_LABEL[r.type] || r.type || '子代理') +
      (r.desc ? ' · ' + r.desc : '')).slice(0, 80);
    const sum = String(r.result || '').replace(/\s+/g, ' ').trim().slice(0, 120);
    // v3.2.6（ZCode 模式）：运行行时间位改秒表（对照 ConversationStatusPanel
    // 的 elapsed 计数——1s 重绘由 _subDirTick 驱动）；已结束保持相对时间
    const t = r.done ? (r.doneAt || 0) : (r.t0 || 0);
    const timeTxt = r.done ? _harnessRelTime(t)
      : (t ? _hgFmtDur(Math.max(0, (Date.now() - t) / 1000)) : '');
    return `<button class="hg-sub-dir-row ${st}" data-hg-dir="${esc(r.tid)}"` +
      ` data-hg-dir-rpl="${r.rpl ? '1' : ''}" title="${esc(title)}">` +
      `<span class="hg-sub-dir-ico">${stIco}</span>` +
      `<span class="hg-sub-dir-main"><span class="hg-sub-dir-t1">` +
      `<span class="hg-sub-dir-title">${esc(title)}</span>` +
      `<span class="hg-sub-dir-st">${stTxt}${r.bg ? ' · 后台' : ''}${r.collab ? ' · 协作' : ''}</span></span>` +
      (sum ? `<span class="hg-sub-dir-sum">${esc(sum)}${String(r.result || '').trim().length > 120 ? '…' : ''}</span>` : '') +
      `</span>` +
      (timeTxt ? `<span class="hg-sub-dir-time">${esc(timeTxt)}</span>` : '') +
      `</button>`;
  }
  let _subDirTick = null;
  function _subDirTickStop() {
    if (_subDirTick) { clearInterval(_subDirTick); _subDirTick = null; }
  }
  function _subDirPaint() {
    const tb = _sub.tabs[_SUB_DIR];
    if (!tb || _sub.active !== _SUB_DIR || !tb.sc) return;
    const { running, ended } = _subDirRows();
    tb.sc.innerHTML =
      `<div class="hg-sub-dir-head">子智能体目录</div>` +
      `<div class="hg-sub-dir-sec">正在运行 · ${running.length}</div>` +
      (running.length ? running.map(_subDirRowHtml).join('')
        : `<div class="hg-sub-dir-empty">没有正在运行的子智能体</div>`) +
      `<div class="hg-sub-dir-sec">已结束 · ${ended.length}</div>` +
      (ended.length ? ended.map(_subDirRowHtml).join('')
        : `<div class="hg-sub-dir-empty">暂无已结束的子智能体</div>`);
    // v3.2.6：有运行行才起 1s 重绘（秒表走字）；目录失活/运行清空自停
    if (running.length && !_subDirTick) {
      _subDirTick = setInterval(() => {
        if (_sub.active !== _SUB_DIR) { _subDirTickStop(); return; }
        if (!_subDirRows().running.length) { _subDirTickStop(); return; }
        _subDirPaint();
      }, 1000);
    }
  }
  function _subDirOpen() {
    if (!_subPaneEl) return;
    if (!_sub.tabs[_SUB_DIR]) {
      const sc = document.createElement('div');
      sc.className = 'hg-sub-msgs hg-sub-dir'; sc.dataset.tid = _SUB_DIR;
      _sub.tabs[_SUB_DIR] = { label: '目录', type: '__dir__', desc: '子智能体目录', sc,
                              run: false, err: false, replay: false, model: '' };
      _sub.order.push(_SUB_DIR);
      _subBodyEl.appendChild(sc);
    }
    _subShow(); _subTabsPaint(); _subActivate(_SUB_DIR);
    _subDirPaint();
    _sub.manual = true;   // v3.2：目录是用户主动打开的视图——回合结束不自动收（同 _subReplay 口径）
  }
  function _subDirRowClick(tid, isRpl) {
    if (isRpl) {
      // 回放档案条目（历史 Task 行派生）：rid 定位存档，agentId 开回放 tab
      const a = ((_HG.dyn && _HG.dyn.agentsRpl) || []).find(x => (x.rid || '') === tid);
      if (!a) return;
      // v3.2R1(P2)：无 agentId 本地单 toast 即止——_subReplay('') 内部还会
      // 弹一条，双 banner 2.6s 内相继覆盖
      if (!a.agentId) { showBanner('该历史子代理无 agentId 记录，无法回放', 2600); return; }
      _subReplay('rpl:' + tid, a.type, a.desc, a.agentId);
      return;
    }
    const a = (_HG.agents || {})[tid];
    if (!a) return;
    if (!a.done) {
      // v3.2.6（ZCode 模式）：协作代理运行中——段卡已隐、过程唯一可看面=窗格，
      // 有真实 taskId 即开全量回放+轮询镜像续流（force 重拉）；无 id 回落跳
      // 主流段锚点（数据缺失的老形态）
      if (a.collab) {
        const aid = a.taskId || a.agentId || '';
        if (aid) { _subReplay(tid, a.type, a.desc, aid, true); return; }
        // v3.2.6R（审计F4）：无真实 id——段卡已隐，跳段是 display:none 上的
        // no-op；明确告知（与 agentline 死点击 banner 同口径）
        showBanner('该协作代理无 agentId 记录，过程暂不可回看', 2600);
        return;
      }
      _subOpen(tid, a.type, a.desc);               // 运行中 → live 实况 tab
      return;
    }
    _subReplay(tid, a.type, a.desc, a.taskId || a.agentId || '');   // 已结束 → 回放 tab（collab 分支内部自理）
  }
  function _subReset() {
    // v3.2.6：先停全部窗格秒表/目录秒表再拆档（防孤儿 interval）
    _subDirTickStop();
    for (const k in _sub.tabs) {
      const tb = _sub.tabs[k];
      if (tb && tb.t && tb.t.tick) { clearInterval(tb.t.tick); tb.t.tick = null; }
    }
    _sub.tabs = {}; _sub.order = []; _sub.active = null; _sub.manual = false;
    if (_subPaneEl) { _subPaneEl.style.display = 'none'; _subTabsEl.innerHTML = ''; _subBodyEl.innerHTML = ''; }
  }
  function _subShow() {
    if (!_subPaneEl || _subPaneEl.style.display !== 'none') return;
    let w = 0;
    try { w = +(localStorage.getItem('hg-subpane-w') || 0); } catch(_) {}
    _subPaneEl.style.width = (w >= 220 && w <= 640 ? w : 320) + 'px';
    _subPaneEl.style.display = 'flex';
  }
  // ==================== v3.2.6：窗格时间线（ZCode 子智能体会话模式）====================
  // 对照 ZCode SubagentSessionSidePane = 完整 SessionPane（readOnly）的产品事实：
  // 子代理自己的会话用与主会话同款的回合结构呈现——turn-head（工作中 Ns /
  // 已工作 X · N 思考 · M 工具）+ 时间线（🧠 思考持续了 N 秒 / 工具行 / 查阅
  // 聚组 / 中间正文气泡按序穿插）+ 根区最终结论。live（SSE/轮询镜像增量）与
  // replay（转写 fetch 全量）同走一套行工厂，仅定稿时长来源不同（live=档案
  // t0 秒表；replay=rows 首末行 ts 差——transcript.py v3.2.6 起行行带 ts）
  function _subTabLabel(type, desc) {
    const d = String(desc || '').trim();
    if (d) return d.slice(0, 14) + (d.length > 14 ? '…' : '');
    return _AGENT_LABEL[type] || type || '子代理';
  }
  function _subPaneScaffold(sc, type, model, desc) {
    const mdl = String(model || '').split('[')[0].trim();
    const ty = _AGENT_LABEL[type] || type || '子代理';
    const wrap = document.createElement('div');
    wrap.className = 'hg-sub-grp';
    wrap.innerHTML =
      `<div class="hg-sub-idline">` +
      `<span class="h-ava ${_hgAvaCls(ty)}">${esc(String(ty).charAt(0).toUpperCase())}</span>` +
      `<span class="hg-sub-idline-ty">${esc(ty)}</span>` +
      (mdl ? `<span class="h-mmodel">${esc(mdl)}</span>` : '') +
      `</div>` +
      `<div class="h-grp"><div class="h-grp-proc">` +
      `<button class="h-turn-head" data-hg-subtgl="1"><span class="h-chev">▸</span>` +
      `<span class="h-turn-label">工作中 0s</span><span class="h-turn-sub"></span></button>` +
      `<div class="h-turn-body"><div class="h-tl"></div></div>` +
      `</div><div class="hg-sub-concl"></div></div>`;
    sc.appendChild(wrap);
    const t = { sc,
      head: wrap.querySelector('.h-turn-head'),
      label: wrap.querySelector('.h-turn-label'),
      subEl: wrap.querySelector('.h-turn-sub'),
      body: wrap.querySelector('.h-turn-body'),
      tl: wrap.querySelector('.h-tl'),
      concl: wrap.querySelector('.hg-sub-concl'),
      exp: null, stats: { think: 0, tool: 0 },
      t0: 0, tick: null, done: false, err: false, durTxt: '' };
    if (desc) t.head.title = String(desc).slice(0, 200);
    return t;
  }
  function _subTlThinkRow(raw, durTxt) {
    const seg = document.createElement('div');
    seg.className = 'h-think-seg';
    seg.dataset.raw = String(raw || '');
    // 懒渲染三件套与主链同款（pane 委托 _histLazyFill/_histLazyDrop 处置）
    seg.dataset.hgLazy = '1';
    seg.innerHTML = '<button class="h-think-seg-head"><span class="h-chev">▸</span>' +
      '<span class="h-think-seg-name">🧠 思考</span>' +
      `<span class="h-think-seg-t">${esc(durTxt || '')}</span></button>` +
      '<div class="h-think-seg-body"></div>';
    return seg;
  }
  function _subTlTextRow(text) {
    const d = document.createElement('div');
    d.className = 'h-msg asst';
    d.appendChild(mdBubble(text));
    return d;
  }
  function _subTlToolRow(name, hint, tuid) {
    const row = document.createElement('div');
    row.className = 'h-tool col';
    if (tuid) row.dataset.tuid = tuid;
    row.style.setProperty('--h-accent',
      _H_KIND_COLOR[(_H_TOOL_CFG[name] || {}).kind] || 'var(--border)');
    row.innerHTML = _subToolHeadHtml(name, String(hint || '').slice(0, 90), '', {}) +
      `<div class="h-tool-coll"></div>`;
    return row;
  }
  function _subPaneStick(sc) {
    return sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;
  }
  // 时间线落位（窗格版 _tlPlace）：explore 类 → 当前查阅组；其余 → 断组直挂
  function _subTlPlace(t, row, name, input) {
    if (!t || !t.tl) return;
    if (_hgIsExplore(name, input)) {
      if (!t.exp || !t.exp.el.isConnected) {
        _subTlExpBreak(t);
        const grpEl = document.createElement('div');
        grpEl.className = 'h-tl-grp';   // v3.2.19：生而收起（主链 _tlPlace 同款）
        grpEl.innerHTML =
          `<button class="h-tl-grp-head"><span class="h-chev">▸</span>` +
          `<span class="h-tl-grp-name">🔍 查阅</span>` +
          `<span class="h-tl-grp-sum"></span></button>` +
          `<div class="h-tl-grp-body"></div>`;
        t.tl.appendChild(grpEl);
        t.exp = { el: grpEl, sum: { search: 0, list: 0, file: 0 }, keys: {} };
      }
      // v3.2.13：同目标重复子行折叠（主链 _tlPlace 同款去重键）
      const _ek = _hgExpKey(name, input);
      if (_ek && t.exp.keys[_ek]) return;
      if (_ek) t.exp.keys[_ek] = 1;
      const body = t.exp.el.querySelector('.h-tl-grp-body');
      if (body) body.appendChild(row);
      t.exp.sum[_hgExpBucket(name, input)]++;
      const sumEl = t.exp.el.querySelector('.h-tl-grp-sum');
      if (sumEl) {
        const live = _hgExpLiveTxt(name, input);
        sumEl.textContent = live ? '· ' + live : _hgExpSumTxt(t.exp.sum);
      }
    } else {
      _subTlExpBreak(t);
      t.tl.appendChild(row);
    }
  }
  // 查阅组断组：头部定格桶汇总；未被动过则收起（主链 _tlExpFlush 同语义）
  function _subTlExpBreak(t) {
    const e = t && t.exp;
    if (!e) { if (t) t.exp = null; return; }
    t.exp = null;
    if (!e.el || !e.el.isConnected) return;
    const sumEl = e.el.querySelector('.h-tl-grp-sum');
    if (sumEl) sumEl.textContent = _hgExpSumTxt(e.sum);
    if (e.el.dataset.userToggled !== '1') e.el.classList.remove('open');
  }
  // 冻结当前开口思考段（live 时长=now−t0；主链 endThinking 的窗格对偶）
  function _subTlSegFreeze(t) {
    if (!t || !t.tl) return;
    const open = t.tl.querySelector('.h-think-seg:not([data-hg-done])');
    if (!open) return;
    open.dataset.hgDone = '1';
    const te = open.querySelector('.h-think-seg-t');
    const t0 = +(open.dataset.t0 || 0);
    if (te && t0) te.textContent = '持续了 ' + _hgTurnDurTxt(Date.now() - t0);
  }
  function _subTlAppendThink(t, raw) {
    if (!t || !t.tl) return;
    _subTlSegFreeze(t);
    // v3.2.13：思考行不再断查阅组（主链 startThinking 同款；对照 ZCode 组跨
    // 思考累积）——思考段挂组后，后续查阅继续回填进组体
    const seg = _subTlThinkRow(raw, '');
    seg.dataset.t0 = String(Date.now());
    t.tl.appendChild(seg);
    t.stats.think++;
    _subTlCap(t);
  }
  function _subTlAppendRow(t, el) {
    if (!t || !t.tl) return;
    _subTlSegFreeze(t);
    _subTlExpBreak(t);
    t.tl.appendChild(el);
    _subTlCap(t);
  }
  function _subTlAppendTool(t, name, hint, tuid, input) {
    if (!t || !t.tl) return;
    _subTlSegFreeze(t);
    const row = _subTlToolRow(name, hint, tuid);
    _subTlPlace(t, row, name, input || null);
    t.stats.tool++;
    _subTlCap(t);
  }
  // v3.2.6R（审计F5）：窗格时间线上限 220 行（旧 _subCap 的 tl 版）——live
  // 长跑子代理（SSE+轮询双源镜像）无界增长会拖垮 DOM/快照。溢出从头删并
  // 置「⬆ 已省略 N 行」提示条；explore 组整组删除时 t.exp 失联由
  // _subTlPlace 的 isConnected 判据自愈重建
  function _subTlCap(t) {
    if (!t || !t.tl) return;
    while (t.tl.children.length > 220) {
      const first = t.tl.firstElementChild;
      if (!first) break;
      if (first.classList.contains('hg-sub-omit')) {
        first.dataset.omitted = String((+first.dataset.omitted || 0) + 1);
        first.textContent = `⬆ 已省略 ${first.dataset.omitted} 行`;
        const victim = first.nextElementSibling;
        if (victim) victim.remove(); else first.remove();
      } else {
        const om = document.createElement('div');
        om.className = 'hg-sub-omit';
        om.dataset.omitted = '1';
        om.textContent = '⬆ 已省略 1 行';
        t.tl.insertBefore(om, first);
        first.remove();
      }
    }
  }
  function _subTlHeadPaint(t) {
    if (!t || !t.label) return;
    if (t.done) {
      t.label.textContent = (t.err ? '已停止' : '已工作') + (t.durTxt ? ' ' + t.durTxt : '');
    } else {
      t.label.textContent = '工作中 ' + _hgFmtDur((Date.now() - (t.t0 || Date.now())) / 1000);
    }
    if (t.subEl) {
      const s = t.stats;
      t.subEl.textContent = (s.think ? `· ${s.think} 思考 ` : '') +
                           (s.tool ? `· ${s.tool} 工具` : '');
    }
  }
  function _subTlTickStart(tid) {
    const tb = _sub.tabs[tid];
    if (!tb || !tb.t || tb.t.tick || tb.t.done) return;
    const t = tb.t;
    t.tick = setInterval(() => {
      const cur = _sub.tabs[tid];
      if (!cur || cur.t !== t || t.done) { clearInterval(t.tick); t.tick = null; return; }
      _subTlHeadPaint(t);
      // 开口思考段活字时长（完成定格由 _subTlSegFreeze 收「持续了 N」）
      const open = t.tl && t.tl.querySelector('.h-think-seg:not([data-hg-done])');
      if (open) {
        const te = open.querySelector('.h-think-seg-t');
        const t0 = +(open.dataset.t0 || 0);
        if (te && t0) te.textContent = _hgTurnDurTxt(Date.now() - t0);
      }
    }, 1000);
  }
  // 定稿：头「已工作 X」、结论气泡上移根区、体默认收起（尊重手动开合）
  function _subTlFinalize(tid, opt) {
    const tb = _sub.tabs[tid];
    const t = tb && tb.t;
    if (!t || t.done) return;
    opt = opt || {};
    if (t.tick) { clearInterval(t.tick); t.tick = null; }
    _subTlSegFreeze(t);
    _subTlExpBreak(t);
    t.done = true;
    t.err = !!opt.err;
    const _a = (_HG.agents || {})[tid] || {};
    const durMs = (opt.durMs > 0) ? opt.durMs
      : ((_a.doneAt || Date.now()) - (_a.t0 || 0));
    t.durTxt = durMs > 0 ? _hgTurnDurTxt(durMs) : '';
    _subTlHeadPaint(t);
    const texts = t.tl ? [...t.tl.querySelectorAll(':scope > .h-msg.asst')] : [];
    const last = texts[texts.length - 1];
    if (last && t.concl) t.concl.appendChild(last);
    if (t.body && t.head && t.head.dataset.userToggled !== '1') t.body.classList.add('closed');
  }
  function _subOpen(tid, type, desc, replay) {
    if (!_subPaneEl) return;
    if (!_sub.tabs[tid]) {
      const sc = document.createElement('div');
      sc.className = 'hg-sub-msgs'; sc.dataset.tid = tid;
      // v2.35（P1-4）：tab 带模型角标（frontmatter 预显示；实跑 model 由
      // 子代理 assistant 事件到达时覆盖并重绘）
      // v2.35.1（F2）：运行态从档案派生——已完成代理被 tab 上限逐出后经
      // _subReopen 重建，不得回到「运行中」绿点（档案缺失的兜底才视为运行）
      // v2.38：replay=true=历史回放 tab（无绿点、置灰、带「回放」徽章）
      // v3.2.6：tab 标题优先用描述（ZCode 右侧 tab 用任务短题，类型进窗格头）
      const _ag = (_HG.agents || {})[tid] || {};
      _sub.tabs[tid] = { label: _subTabLabel(type, desc), type, desc, sc,
                         run: replay ? false : (!('done' in _ag) || !_ag.done),
                         err: !!_ag.err, replay: !!replay,
                         model: _ag.model || '', t: null };
      _sub.order.push(tid);
      // v3.2：上限 6 个 tab，最旧让位（目录伪 tab 常驻不让位）
      if (_sub.order.filter(x => x !== _SUB_DIR).length > 6) {
        const old = _sub.order.find(x => x !== _SUB_DIR);
        if (old != null) {
          const otb = _sub.tabs[old];
          if (otb && otb.t && otb.t.tick) { clearInterval(otb.t.tick); otb.t.tick = null; }
          _sub.order = _sub.order.filter(x => x !== old);
          if (otb && otb.sc.parentNode) otb.sc.remove();
          delete _sub.tabs[old];
        }
      }
      _subBodyEl.appendChild(sc);
      // v3.2.6：ZCode 时间线脚手架（回放 fetch 会重建；live 即刻起跑秒表）
      _sub.tabs[tid].t = _subPaneScaffold(sc, type, _ag.model || '', desc);
      if (_sub.tabs[tid].run) {
        _sub.tabs[tid].t.t0 = _ag.t0 || Date.now();
        _subTlHeadPaint(_sub.tabs[tid].t);
        _subTlTickStart(tid);
      }
    }
    _subShow(); _subTabsPaint(); _subActivate(tid);
  }
  const _subNoreplay = new Set();
  const _subNoReplayNote = () =>
    '<div class="hg-sub-replay-note">未找到该子代理的转写记录，历史过程不可回放</div>';
  // v3.2.6R2：运行中代理的回放重试（CLI 刷盘有延迟——fetch 早于落盘时铺底
  // 空，5s 后再拉一次；限 3 次防循环，tab 已换/已定稿/已有行即不再试）。
  // R6（审计）：计数挂 **tab 档案**（tb._retry）——retry 触发的 force 重拉会
  // 整体重建 scaffold（tb.t 换新对象），挂 t 上每轮归零、上限恒不可达
  function _subReplayRetry(tid, type, desc, agentId) {
    const tb = _sub.tabs[tid];
    if (!tb) return;
    tb._retry = (tb._retry || 0) + 1;
    if (tb._retry > 3) return;
    setTimeout(() => {
      const cur = _sub.tabs[tid];
      const sc = cur && cur.sc;
      if (!sc || !cur.t || cur.t.done || (cur.t.tl && cur.t.tl.children.length)) return;
      const a = (_HG.agents || {})[tid];
      if (!a || a.done) return;
      delete sc.dataset.replayed;
      _subReplay(tid, type, desc, agentId, true);
    }, 5000);
  }
  function _subReplay(tid, type, desc, agentId, force) {
    if (!_subPaneEl) return;
    const a = (_HG.agents || {})[tid] || {};
    // v2.57：协作档案有 taskId（=真实 agentId，v2.52 修复转写源后可拉全量）
    // ——不再走「过程不可回看」占位（过时判定，用户实锤途中关闭再开啥也没有）；
    // 无 taskId（连真实 id 都没反查到）才维持占位
    if (a.collab && !a.taskId && !agentId) {
      _subOpen(tid, type, desc, true);
      const tb0 = _sub.tabs[tid];
      if (tb0 && tb0.t && !tb0.t.sc.dataset.collabNote) {
        tb0.t.sc.dataset.collabNote = '1';
        const n0 = document.createElement('div');
        n0.className = 'hg-sub-replay-note';
        n0.textContent = '独立会话协作代理——过程不可回看，仅结论可回看';
        tb0.t.sc.appendChild(n0);
        if (a.result) {
          const c0 = document.createElement('div');
          c0.className = 'h-msg asst';
          c0.appendChild(mdBubble(a.result));
          tb0.t.concl.appendChild(c0);
        }
        tb0.t.done = true; tb0.t.durTxt = '';
        _subTlHeadPaint(tb0.t);
      }
      _sub.manual = true;
      return;
    }
    agentId = agentId || a.taskId || a.agentId || '';
    if (!agentId) { showBanner('该子代理没有 agentId 记录，无法回放', 2600); return; }
    _subOpen(tid, type, desc, true);
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (!sc) return;
    if (sc.dataset.replayed === agentId && !force) { _sub.manual = true; return; }   // 已拉过
    // v3.2.6：拉取期头行给加载态（脚手架默认「工作中」对回放 tab 是误导）
    {
      const tbL = _sub.tabs[tid];
      if (tbL && tbL.t && tbL.t.label) tbL.t.label.textContent = '回放加载中…';
    }
    if (_subNoreplay.has(agentId)) {      // v2.41：已判定不可回放——直接出示结论，不再发请求
      sc.innerHTML = '';
      sc.dataset.replayed = agentId;
      _subAppend(sc, _subNoReplayNote(), true);
      _sub.manual = true;
      return;
    }
    sc.dataset.replayed = agentId;
    _sub.manual = true;
    if (_sub.tabs[tid]) _sub.tabs[tid].replay = true;   // v2.57：fetch 期间挡镜像增量（防污染），完成后放行
    const sidAt = _HG.sid;
    fetch(`/api/harness/subagent_replay?sid=${encodeURIComponent(sidAt || '')}&agent=${encodeURIComponent(agentId)}`)
      .then(r => r.json())
      .then(j => {
        // v2.37R2（复审1）：失败路径必须清 replayed 标记并给错误文案——标记
        // 不清则重点按钮永远早退，唯一恢复=切走重切
        const _tf = _sub.tabs[tid];
        if (_tf) _tf.replay = false;   // v2.57：fetch 已收敛——放行镜像增量
        if (!j || !j.ok || _HG.sid !== sidAt) {
          const scf = _sub.tabs[tid] && _sub.tabs[tid].sc;
          if (scf) {
            delete scf.dataset.replayed;
            if (_HG.sid === sidAt) {   // 会话已切走的不动现flow（可能已属别会话窗格）
              scf.innerHTML = '';
              _subAppend(scf, `<div class="hg-sub-replay-note">${(j && j.err) ? esc('回放读取失败：' + j.err) : '回放读取失败——重新点击可重试'}</div>`, true);
            }
          }
          return;
        }
        const tb2 = _sub.tabs[tid];
        const sc2 = tb2 && tb2.sc;
        if (!sc2) return;
        // v3.2.6：重建时间线脚手架（清「回放加载中」占位）
        sc2.innerHTML = '';
        const t = tb2.t = _subPaneScaffold(sc2, type, tb2.model || a.model || '', desc);
        const note = (txt) => {
          const n = document.createElement('div');
          n.className = 'hg-sub-replay-note';
          n.textContent = txt;
          sc2.insertBefore(n, sc2.firstChild);
        };
        if (!j.found) {
          // v2.42：后端双源（projects 旧源+新版 CLI tasks 兜底）均未命中——
          // 文件不存在是持久事实，重拉永远同结果；记住结论，重点/重开不再发请求
          // v3.2.6R2：运行中代理的转写可能只是尚未生成——不进 noreplay 锁
          // （完成后的重开要能重试），保持运行态等镜像续流
          const _runA = (_HG.agents || {})[tid];
          if (_runA && !_runA.done) {
            t.t0 = _runA.t0 || Date.now();
            _subTlHeadPaint(t);
            _subTlTickStart(tid);
            note('转写尚未生成——实况继续');
            _subReplayRetry(tid, type, desc, agentId);
            return;
          }
          _subNoreplay.add(agentId);
          t.done = true; t.durTxt = '';
          _subTlHeadPaint(t);   // v3.2.6R（审计F2）：失败分支也定稿头——不卡「工作中 0s」假态
          note('未找到该子代理的转写记录');
          return;
        }
        if (!(j.rows || []).length) {
          // v2.41R2：转写存在但无可渲染行——与「没有独立转写」是两回事，给中性
          // 文案且不进 noreplay 集（tab 重开后可重试，防误判永久锁死回放入口）
          // v3.2.6R2：运行中同理不锁不封顶——CLI 刷盘有延迟，保持运行态续流
          const _runB = (_HG.agents || {})[tid];
          if (_runB && !_runB.done) {
            t.t0 = _runB.t0 || Date.now();
            _subTlHeadPaint(t);
            _subTlTickStart(tid);
            note('转写暂无可回放内容——实况继续');
            _subReplayRetry(tid, type, desc, agentId);
            return;
          }
          t.done = true; t.durTxt = '';
          _subTlHeadPaint(t);   // v3.2.6R（审计F2）：同上
          note('转写存在但无可回放内容');
          return;
        }
        if (_sub.tabs[tid]) _sub.tabs[tid]._retry = 0;   // v3.2.6R6：铺底成功重置重试额度
        note(`回放 · ${_AGENT_LABEL[type] || type} · ${j.rows.length} 条记录`);
        // ---- v3.2.6：rows → 时间线（与 live 同厂行；ts 事实分级）----
        const _tsGet = r0 => (r0 && r0.ts) ? Date.parse(r0.ts) : 0;
        const pend = [];       // 开口思考段（时长=下一带 ts 行差）
        let lastTs = 0;
        let lastTool = null;   // result 就近挂回的当前工具行
        const _fillRes = (toolRow, text, err) => {
          toolRow.dataset.done = '1';
          toolRow.classList.toggle('err', !!err);
          const slots = toolRow.querySelector('.h-tslots');
          if (slots) slots.innerHTML = statusBadge(err ? 'error' : 'completed');
          const full = String(text || '').trim();
          const coll = toolRow.querySelector('.h-tool-coll');
          if (coll && full && full !== '(no content)') {
            const d = document.createElement('div');
            d.className = 'h-tool-out' + (err ? ' err-txt' : '');
            d.textContent = full.length > 2000 ? full.slice(0, 2000) + '…' : full;
            coll.appendChild(d);
          }
        };
        for (const row of (j.rows || [])) {
          const ts = _tsGet(row);
          if (ts > 0) {
            for (const p of pend) {
              const te = p.seg.isConnected ? p.seg.querySelector('.h-think-seg-t') : null;
              if (te && ts > p.ts) te.textContent = '持续了 ' + _hgTurnDurTxt(ts - p.ts);
            }
            pend.length = 0;
            lastTs = ts;
          }
          if (row.k === 'text') {
            const el = _subTlTextRow(row.text);
            el.dataset.hgRp = '1';   // 铺底标——镜像增量查重锚
            _subTlAppendRow(t, el);
          } else if (row.k === 'note') {
            const n = document.createElement('div');
            n.className = 'hg-sub-replay-note';
            n.textContent = row.text || '';
            n.dataset.hgRp = '1';
            _subTlAppendRow(t, n);
          } else if (row.k === 'think') {
            const seg = _subTlThinkRow(row.text || '', '');
            seg.dataset.hgRp = '1';
            _subTlAppendRow(t, seg);
            t.stats.think++;
            if (ts > 0) pend.push({ seg, ts });
          } else if (row.k === 'tool') {
            _subTlSegFreeze(t);
            const tw = _subTlToolRow(row.name || '', row.hint || '', '');
            tw.dataset.hgRp = '1';   // 铺底标——镜像增量查重锚
            tw.dataset.fp = (row.name || '') + ' ' + String(row.hint || '').slice(0, 80);
            // v3.2.6R2（审计N2）：Bash/PowerShell 的只读命令用 hint（=command
            // 摘要）合成伪 input——rows 结构无 input，聚组判定才不退化。
            // v3.2.6R3（审计残留）：row.w=后端按全量命令证明的写盘标记
            //（重定向常在尾部，120 字截断漏检）——w 行不合成伪 input，
            // _hgIsExplore(null input) 即直挂，绝不把写命令聚进查阅组
            const _pin = (row.name === 'Bash' || row.name === 'PowerShell') && !row.w
              ? { command: String(row.hint || '') } : null;
            _subTlPlace(t, tw, row.name || '', _pin);
            t.stats.tool++;
            lastTool = tw;
          } else if (row.k === 'result') {
            if (lastTool && lastTool.isConnected && lastTool.dataset.done !== '1') {
              _fillRes(lastTool, row.text, row.err);
            } else {
              const d = document.createElement('div');
              d.className = 'h-tool-res' + (row.err ? ' err-txt' : '');
              d.textContent = '↳ ' + String(row.text || '').replace(/\s+/g, ' ').trim().slice(0, 120);
              d.dataset.hgRp = '1';
              _subTlAppendRow(t, d);
            }
          }
        }
        for (const p of pend) {
          const te = p.seg.isConnected ? p.seg.querySelector('.h-think-seg-t') : null;
          if (te && lastTs > p.ts) te.textContent = '持续了 ' + _hgTurnDurTxt(lastTs - p.ts);
        }
        // 定稿：dur=首末行 ts 差（缺 ts 落无数字「已工作」——不编造）。
        // v3.2.6R（审计F3）：collab 运行行 force 回放=「铺底即续流」——代理
        // 未 done 不定稿（定稿会封死 _subTlFinalize 的 done 守卫：续流增量
        // 落进已收起体、秒表不复活、最终时长不含续跑段）。保持运行态：秒表
        // 即刻起跑、体保持开、task_notification 到达再正式定稿
        const _agNow = (_HG.agents || {})[tid];
        if (_agNow && !_agNow.done) {
          t.t0 = _agNow.t0 || Date.now();
          _subTlHeadPaint(t);
          _subTlTickStart(tid);
        } else {
          const tsAll = (j.rows || []).map(_tsGet).filter(x => x > 0);
          const durMs = tsAll.length > 1 ? (tsAll[tsAll.length - 1] - tsAll[0]) : 0;
          t.done = true;
          t.durTxt = durMs > 0 ? _hgTurnDurTxt(durMs) : '';
          _subTlHeadPaint(t);
          const texts = [...t.tl.querySelectorAll(':scope > .h-msg.asst')];
          const last = texts[texts.length - 1];
          if (last && t.concl) t.concl.appendChild(last);
          t.body.classList.add('closed');
        }
        _subScroll(tid);
      })
      .catch(() => {
        const _tc = _sub.tabs[tid];
        if (_tc) _tc.replay = false;   // v2.57R：网络失败路径也放行镜像（与 .then 同口径）
        const sc3 = _sub.tabs[tid] && _sub.tabs[tid].sc;
        if (sc3) {
          delete sc3.dataset.replayed;   // v2.37R2（复审1）：清标记，重点即重拉
          sc3.innerHTML = ''; _subAppend(sc3, `<div class="hg-sub-replay-note">回放拉取失败（网络）——重新点击可重试</div>`, true);
        }
      });
    _subScroll(tid);
  }
  function _subActivate(tid) {
    if (!_sub.tabs[tid]) return;
    _sub.active = tid;
    _subBodyEl.querySelectorAll('.hg-sub-msgs').forEach(x =>
      x.style.display = x.dataset.tid === tid ? '' : 'none');
    _subTabsPaint();
    // v3.2R1(P2)：目录不贴底滚动——_subScroll 为聊天流贴底设计，目录的主
    // 内容（正在运行）在顶部，贴底会直接落到已结束长列表尾
    if (tid !== _SUB_DIR) _subScroll(tid);
    if (tid === _SUB_DIR) _subDirPaint();   // v3.2：目录激活即重绘（数据最新）
  }
  function _subTabsPaint() {
    if (!_subTabsEl) return;
    _subTabsEl.innerHTML = _sub.order.filter(t => _sub.tabs[t]).map(t => {
      const tb = _sub.tabs[t];
      // v2.35（P1-4）：模型进 tab（短名+悬浮全名）；tokens 进悬浮（CLI 侧计数）
      const ag = (_HG.agents || {})[t] || {};
      const mdlFull = tb.model || '';
      const mdlShort = mdlFull.length > 14 ? mdlFull.slice(0, 13) + '…' : mdlFull;
      const ttip = [tb.desc || tb.label,
                    mdlFull ? '模型：' + mdlFull : '模型：主链模型（内置/无定义文件）',
                    ag.tokens ? `用量：${ag.tokens} tokens · ${ag.toolN || 0} 次工具` : '']
        .filter(Boolean).join('\n');
      return `<div class="hg-sub-tab${t === _sub.active ? ' active' : ''}${tb.run ? ' run' : tb.err ? ' err' : ''}${tb.replay ? ' replay' : ''}${t === _SUB_DIR ? ' dir' : ''}"` +
        ` data-hg-subtab="${esc(t)}" title="${esc(ttip)}">` +
        (t === _SUB_DIR ? '<span class="hg-sub-dir-tabico">☰</span>' : '<span class="hg-sub-dot"></span>') + esc(tb.label) +
        (tb.replay ? `<span class="hg-sub-rp">回放</span>` : '') +
        (mdlShort ? `<span class="hg-sub-mdl">${esc(mdlShort)}</span>` : '') +
        // 窗格重设计 P1-1：单-tab ✕——hover 才浮现（CSS 控制），运行中的 tab
        // 提示「任务继续后台跑」防误触焦虑；点击走 _subDrop（tab 条委托分支）
        // v3.2：目录伪 tab 常驻无 ✕
        (t === _SUB_DIR ? '' :
        `<span class="hg-sub-x2" data-hg-subclose="${esc(t)}" title="${esc(tb.run ? '关闭视图（任务继续在后台跑）' : '关闭该 tab')}">✕</span>`) + `</div>`;
    }).join('');
  }
  function _subScroll(tid) {
    const sc = _sub.tabs[tid] && _sub.tabs[tid].sc;
    if (sc) sc.scrollTop = sc.scrollHeight;
  }
  function _subCap(sc) { while (sc.children.length > 200) sc.removeChild(sc.firstElementChild); }
  function _subAppend(sc, html, noCap) {   // 兜底占位路径仍在用（v3.2.6 回放主体已改时间线）
    const d = document.createElement('div');
    d.innerHTML = html;
    sc.appendChild(d.firstElementChild || d);
    if (!noCap) _subCap(sc);
  }
  // v3.2.6：轮询镜像增量（think/text）→ 窗格时间线行（v2.57R 的 rp 铺底
  // 前缀查重保留——回放 tab fetch 收敛放行后的重叠窗口防双份）
  function _subPaneMirror(pid, kind, text) {
    const tb = _sub.tabs[pid];
    if (!tb || !tb.t || !text || !String(text).trim()) return;
    if (tb.replay) return;   // v2.55R：回放 tab 由 fetch 全量自建，镜像增量不得污染
    const t = tb.t;
    const stick = _subPaneStick(t.sc);
    const rp = [...t.tl.querySelectorAll('[data-hg-rp="1"]')].slice(-8);
    const norm = s => String(s || '').replace(/\s+/g, '');
    if (kind === 'think') {
      // 单向前缀比对（镜像=全文、rp=截断前缀）：md 截断边界落在行内标记时
      // 前缀性质可破——启发式容差
      if (rp.some(el => {
        const a = norm(el.dataset.raw || '');
        return !!a && norm(text).startsWith(a);
      }))
        return;
      _subTlAppendThink(t, text);
    } else {
      const row = _subTlTextRow(text);
      const want = norm(row.textContent);
      if (want && rp.some(el => {
        const got = norm(el.textContent);
        return !!got && want.startsWith(got);
      }))
        return;
      _subTlAppendRow(t, row);
    }
    if (stick) _subScroll(pid);
  }
  // v3.2.6：live 窗格喂入（SSE 子代理块：thinking/text/tool_use）——全部走
  // 时间线行工厂；think 开口段活字/断组/贴底与主链同口径
  function _subFeed(parentId, blocks) {
    const tb = _sub.tabs[parentId];
    if (!tb || !tb.t) return;
    const t = tb.t;
    const stick = _subPaneStick(t.sc);
    // v2.35：回合终结定格过的 tab，若对应代理其实还在跑（后台 Task 跨回合
    // 续跑），事件继续流入时恢复绿点脉冲——别让冻结态骗人；秒表一并复活
    const _ag = (_HG.agents || {})[parentId];
    if (tb.run !== true && _ag && !_ag.done) {
      tb.run = true;
      _subTabsPaint();
    }
    if (tb.run && !t.done && !t.tick) { t.t0 = t.t0 || (_ag && _ag.t0) || Date.now(); _subTlTickStart(parentId); }
    for (const b of blocks) {
      if (!b) continue;
      if (b.type === 'thinking' && String(b.thinking || '').trim()) {
        _subTlAppendThink(t, b.thinking);
      } else if (b.type === 'text' && String(b.text || '').trim()) {
        _subTlAppendRow(t, _subTlTextRow(b.text));
      } else if (b.type === 'tool_use' && b.name) {
        // v2.55R：对称查重——同一事件里镜像（_subBlkAppendTool）先插、本分支
        // 后插，只查一侧必双份；两侧都查后无论谁先谁后均只落一行
        if (b.id && t.tl.querySelector(`.h-tool[data-tuid="${CSS.escape(b.id)}"]`))
          continue;
        const inp = b.input || {};
        const hint = inp.command || inp.file_path || inp.path || inp.pattern ||
                     inp.query || inp.description || inp.subject || inp.prompt || '';
        _subTlAppendTool(t, b.name, hint, b.id || '', inp);
      }
    }
    _subTlHeadPaint(t);
    if (stick) _subScroll(parentId);
  }
  // v3.2.6：工具结果回点窗格时间线（tuid 精确配对优先；miss 回退最后一个未
  // 定格行；全 miss 落孤立 ↳ 行——结果不丢）
  function _subResult(parentId, tr) {
    const tb = _sub.tabs[parentId];
    if (!tb || !tb.t) return;
    const t = tb.t;
    const stick = _subPaneStick(t.sc);
    const full = resultText(tr).trim();
    let toolRow = tr.tool_use_id
      ? t.tl.querySelector(`.h-tool[data-tuid="${CSS.escape(tr.tool_use_id)}"]`) : null;
    if (!toolRow) {
      const all = [...t.tl.querySelectorAll('.h-tool')];
      for (let i = all.length - 1; i >= 0; i--) {
        if (all[i].dataset.done !== '1') { toolRow = all[i]; break; }
      }
    }
    if (!toolRow) {
      const d = document.createElement('div');
      d.className = 'h-tool-res' + (tr.is_error ? ' err-txt' : '');
      if (tr.tool_use_id) d.dataset.rtuid = tr.tool_use_id;
      d.textContent = '↳ ' + (full.replace(/\s+/g, ' ').slice(0, 120) || '完成');
      _subTlAppendRow(t, d);
      if (stick) _subScroll(parentId);
      return;
    }
    if (toolRow.dataset.done === '1') return;
    const bad = !!tr.is_error;
    toolRow.dataset.done = '1';
    toolRow.classList.toggle('err', bad);   // v3.2.5 口径：错误只标红不自动展开
    const slots = toolRow.querySelector('.h-tslots');
    if (slots) slots.innerHTML = statusBadge(bad ? 'error' : 'completed');
    if (full && full !== '(no content)') {
      const coll = toolRow.querySelector('.h-tool-coll');
      if (coll) {
        const d = document.createElement('div');
        d.className = 'h-tool-out' + (bad ? ' err-txt' : '');
        d.textContent = full.length > 2000 ? full.slice(0, 2000) + '…' : full;
        coll.appendChild(d);
      }
    }
    if (stick) _subScroll(parentId);
  }
  function _subClose(tid, err) {
    _subBlkFinish(tid, err);  // v2.43：主 flow 段头定格（不依赖窗格 tab 存活）
    const tb = _sub.tabs[tid];
    if (!tb) return;
    tb.run = false; tb.err = !!err;
    _subTlFinalize(tid, { err });   // v3.2.6：窗格时间线定稿（已工作 X + 结论上移）
    _subTabsPaint();
  }
  function _subBlkFinish(tid, err, aidForce) {
    if (!_subBlkAdopt(tid)) return;    // 段不在（无过程行的代理/协作包装）——无事可做
    _subBlkState(tid, err);
    const _a = (_HG.agents || {})[tid] || {};
    // v2.46R（P4）：档案 taskId 优先——续派形态下它是 peerSent 反查的真实
    // agentId，aidForce（notification.task_id）是 CLI 包装新 id；常规 Agent
    // 两者同值（v2.44 实证同源），顺序翻转零影响
    const _aid = _a.taskId || aidForce || _a.agentId || '';
    const _b = _HG.subBlk && _HG.subBlk[tid];
    if (_b && _b.head && _aid && !_b.head.dataset.hgSubr) {
      _b.head.dataset.hgSubr = _aid;
      _b.head.dataset.hgSubType = _a.type || 'Task';
      _b.head.dataset.hgSubDesc = String(_a.desc || '').slice(0, 120);
      _subBlkActsPaint(_b);   // v2.45：hgSubr 后到——「▣ 回放」钮此时才具备数据
    }
    // v2.44：思考回填——CLI 不向 stream-json 转发子代理（sidechain）thinking
    // 块（实测铁证：本会话事件缓冲主链 thinking 10/10 到达、子代理 0/146，
    // 全量躺在子代理转写 jsonl 里），实时段内永远等不到思考事件。定格且
    // agentId 在手时按转写把思考行补进段内——与历史路径同数据源（回放接口
    // _subagent_rows_for 双源），完成即完整。hgBackfill 标记防重入（多次
    // 完成信号/收尾 sweep 不会重复拉取）；段不在/无 aid 静默跳过
    // v2.46R（P2）：定格先 drain 尾部再回填——轮询已停（tick 跳过 done 段），
    // 最后一次轮询与完成信号之间新落盘的 thinking 若不补读，「段内有思考
    // 即整体跳过」的回填守卫会把它永久丢了（最后一轮 thinking 落在完成前
    // 0-2s 概率极高）。drain 到无推进后回填：轮询插过→守卫拦重复；没插过
    // →回填全量，两不误
    if (_b && _b.root && _b.body && _aid && !_b.root.dataset.hgBackfill) {
      // v2.58：续派切段——该 agentId 的活跃段已切到他段时，本段（旧轮）不得
      // 再发起 drain（共享账本的增量字节属于新段，灌进来=串段）
      if ((_HG.subTailSeg || {})[_aid] && (_HG.subTailSeg || {})[_aid] !== tid) {
        _b.root.dataset.hgBackfill = '1';   // 占位防重复判定，不发起
      } else {
        _b.root.dataset.hgBackfill = '1';
        _subTailDrainThenBackfill(tid, _aid);
      }
    }
    // v2.47（需求2）：协作段连包装 id 都没有（task_started 事件缺 task_id 且
    // peerSent 未命中）——回填无从发起，直接占位，不空壳
    else if (_b && _b.root && !_aid && _b.root.dataset.hgCollab === '1')
      _subCollabNoTranscriptNote(tid);
  }
  async function _subBlkBackfill(tid, aid) {
    const sidAt = _HG.sid;
    try {
      const r = await fetch('/api/harness/subagent_replay?sid=' + encodeURIComponent(sidAt)
        + '&agent=' + encodeURIComponent(aid));
      const j = await r.json();
      if (!j.ok || _HG.sid !== sidAt) return;
      // v2.47（需求2）：协作段三源全 miss（确实无独立落盘）——段体放
      // 「该协作无独立转写」占位，不空壳卡死；真实子代理 miss（旧会话/已
      // 清理）维持原静默（有段内实时行撑着，不冒充断档）
      if (!j.found) { _subCollabNoTranscriptNote(tid); return; }
      _subBlkMergeThinks(tid, j.rows || []);
    } catch(_) {}
  }
  function _subCollabNoTranscriptNote(tid) {
    const b = _HG.subBlk && _HG.subBlk[tid];
    if (!b || !b.root || !b.body || b.root.dataset.hgCollab !== '1'
        || b.root.dataset.hgCollabNote === '1') return;
    b.root.dataset.hgCollabNote = '1';
    if (b.body.querySelectorAll('.h-think-seg, .h-tool, .h-tool-res, .h-msg, .h-subblock-note').length)
      return;   // 轮询喂过/占位已在——不叠
    const n = document.createElement('div');
    n.className = 'h-subblock-note';
    n.textContent = '（该协作无独立转写——CLI 未落盘其会话，过程不可围观；完成状态以段头为准）';
    b.body.appendChild(n);
  }
  function _subBlkMergeThinks(tid, rows) {
    const b = _HG.subBlk && _HG.subBlk[tid];
    if (!b || !b.body || !b.root.isConnected) return;
    // v2.53：text 气泡同回填（用户定调段内与主会话一致——思考+工具+消息）
    if (!rows.some(r => r && (r.k === 'think' || r.k === 'text') && String(r.text || '').trim())) return;
    if (b.body.querySelectorAll('.h-think-seg').length) return;
    _subSecNormalize(b);   // 旧快照遗留布局先归节（回填只认节结构）
    // 边界映射预备：段内气泡序 / replay text 序（头区|尾区）
    const bubbles = [...b.body.children].filter(el => el.classList.contains('h-msg'));
    const B = bubbles.length;
    const noteAt = rows.findIndex(r => r && r.k === 'note');
    const isTailRow = i => noteAt >= 0 && i > noteAt;
    const textIdx = rows.map((r, i) => (r && r.k === 'text' && !isTailRow(i)) ? 0
      : (r && r.k === 'text' ? 1 : -1));   // 0=头区 text 1=尾区 text
    const headTextN = textIdx.filter(x => x === 0).length;
    const tailTextN = textIdx.filter(x => x === 1).length;
    // replay text 序号（全区连续编号）→ 段内气泡下标
    const ordToBubble = o => {
      if (o < 0) return -1;
      if (o < headTextN) return Math.min(o, Math.max(0, B - 1));          // 头区恒等
      return Math.max(0, B - tailTextN + (o - headTextN));                // 尾区对齐尾部
    };
    // 每行右侧最近 text 的全区序号（-1=右侧再无 text）
    const nextOrd = new Array(rows.length).fill(-1);
    {
      let acc = -1;
      let seen = headTextN + tailTextN;
      for (let i = rows.length - 1; i >= 0; i--) {
        nextOrd[i] = acc;
        if (textIdx[i] >= 0) { seen--; acc = seen; }
      }
    }
    // 目标节：边界气泡之前的最近节。v2.48R（复审 P1）：回走必须以 text 气泡
    // （及段内 note——同类的位置边界）为停点——旧实现一路回穿中间气泡落到
    // 任意更早的节，中段纯思考区间（两气泡间无节）的回填思考会呈现到前一张
    // 气泡之前=时序颠倒（reviewer shim 三形态实锤）。撞气泡/到头=该气泡前
    // 就地新建节；紧邻前节（气泡前一个就是节）照常命中，不多建
    const secBefore = bubble => {
      let el = bubble.previousElementSibling;
      while (el && !el.classList.contains('h-subsec')
             && !el.classList.contains('h-msg')
             && !el.classList.contains('h-subblock-note')) el = el.previousElementSibling;
      if (el && el.classList.contains('h-subsec')) return el;
      const sec = document.createElement('div');
      sec.className = 'h-subsec';
      b.body.insertBefore(sec, bubble);
      return sec;
    };
    // 末节=body 尾部的节。v2.48R：旧实现取「最后一个节」——段尾是气泡时
    // （常态：最终报告收尾）尾随思考会被塞进气泡前的节=呈现先于最终文本
    // （时序颠倒的第三形态）。尾非节则尾建（尾随思考的时序在最后一条
    // text 之后，本就该有独立尾节）
    const lastSec = () => {
      const last = b.body.lastElementChild;
      if (last && last.classList.contains('h-subsec')) return last;
      const sec = document.createElement('div');
      sec.className = 'h-subsec';
      b.body.appendChild(sec);
      return sec;
    };
    rows.forEach((r, i) => {
      if (!r || !String(r.text || '').trim()) return;
      const bi = ordToBubble(nextOrd[i]);
      // v2.53：text 行回填成气泡（与实时 _subText 同构），插在其右侧边界
      // 气泡前（时序位）；与轮询双源防重——归一文本已在段内任一气泡即跳过
      if (r.k === 'text') {
        const norm = s => String(s || '').replace(/\s+/g, '');
        const want = norm(r.text);
        if (!want) return;
        if ([...b.body.querySelectorAll('.h-msg.sub')]
            .some(el => norm(el.textContent) === want)) return;
        const d = document.createElement('div');
        d.className = 'h-msg asst sub';
        d.appendChild(mdBubble(r.text));
        if (bi >= 0 && bi < B && bubbles[bi]) b.body.insertBefore(d, bubbles[bi]);
        else b.body.appendChild(d);
        return;
      }
      if (r.k !== 'think') return;
      const sec = (bi >= 0 && bi < B && bubbles[bi]) ? secBefore(bubbles[bi]) : lastSec();
      const dr = _subSecDrawer(sec, 'think');
      const seg = _subThinkShell(false);
      seg.dataset.raw = String(r.text);
      seg.dataset.hgLazy = '1';
      dr.querySelector('.h-drawer-body').appendChild(seg);
      _subSecCount(sec);
    });
    // note 省略行随回填落段尾（与回放窗格口径一致）
    if (noteAt >= 0 && rows[noteAt] && rows[noteAt].text) {
      const nEl = document.createElement('div');
      nEl.className = 'h-subblock-note';
      nEl.textContent = String(rows[noteAt].text);
      b.body.appendChild(nEl);
    }
  }
  const _subTailBusy = {}; // agentId → 拉取在途标记（防 2s 内重入叠请求）
  const _subTailDead = {}; // agentId → 停喂标记（无账本且重插风险行已在段体——
  function _subFullFeedTid(tid) {
    const a = (_HG.agents || {})[tid];
    if (a) return !!(a.collab && (_HG.peerSent || {})[tid]);
    const b = _HG.subBlk && _HG.subBlk[tid];
    return !!(b && b.root && b.root.dataset.hgFullfeed === '1');
  }
  function _subThinkPollTick() {
    if (!_HG.sid) return;
    // v2.47（需求2）：协作段 DOM 兜底扫描先于 busy 门槛——切会话往返后
    // agents 档案已清（task_started 不重放）而协作代理还在后台跑，且那正是
    // 主流空闲（!busy）的常态时段，放门槛后面会被饿死；扫描本身只是一次
    // querySelectorAll（无协作段=零成本）
    _subCollabDomPoll();
    // v2.47（需求2）：busy 门槛放宽为「busy 或任一代理在跑」——协作包装
    // 后台执行，主回合 result 后 busy 已 false 而任务仍在跑；纯空闲（无在跑
    // 代理）仍零请求
    if (!_HG.busy && !_hgAgentsRunning()) return;
    const ag = _HG.agents || {};
    for (const tid in ag) {
      const a = ag[tid];
      // v2.47：collab 不再一票跳过——段已建（需求2）、taskId=peerSent 反查
      // 的真实 id（P4），转写三源可增量读
      if (!a || a.done || !a.taskId) continue;
      // v2.58：续派切段——该 agentId 的增量喂给**当前活跃段**（subTailSeg
      // 映射在 SendMessage 派发时切到新段），旧段即使档案未 done 也不再吃
      // 内容（用户实锤「续审内容跑回第一个审计段」）
      const tgt = (_HG.subTailSeg || {})[a.taskId] || tid;
      const b = _HG.subBlk && _HG.subBlk[tgt];
      if (!b || !b.root || !b.root.isConnected || b.root.classList.contains('done')) continue;
      _subTailFetch(tgt, a.taskId, _subFullFeedTid(tgt));
    }
  }
  function _subCollabDomPoll() {
    _hgFlow.querySelectorAll('.h-subblock[data-hg-collab]:not(.done)').forEach(el => {
      const pid = el.dataset.hgSubblock;
      const hd = el.querySelector('.h-subblock-head');
      const aid = hd && hd.dataset.hgSubr;
      if (!pid || !aid || !el.isConnected) return;
      // v2.58：续派切段——映射指向他段时本段已让位，不得再吃共享账本增量
      //（否则同一 agentId 的内容被拆进新旧两段）
      if ((_HG.subTailSeg || {})[aid] && (_HG.subTailSeg || {})[aid] !== pid) return;
      // 走 _subBlkGet（非 _subBlkAdopt）——认回分支连秒表一起复活（t0 从段头
      // 「运行中 Ns」还原）；段在本循环刚查到且仍在流（isConnected 双保险），
      // adopt 必中、不会走到新建分支
      const b = _subBlkGet(pid);
      if (!b) return;
      _subTailFetch(pid, aid, true);
    });
  }
  async function _subTailFetch(tid, aid, fullFeed) {
    if (_subTailBusy[aid]) return;
    if (_subTailDead[aid]) return;   // 已判定消费位不可知——不重读（见下）
    _subTailBusy[aid] = true;
    const sidAt = _HG.sid;
    try {
      // v2.47R（复审1）：offset 账本自愈下沉到消费点——切会话往返 subTail 清账
      // 后，完成信号（通知重放）可能先于下一轮 tick 的兜底扫描直达 drain，
      // 从 0 全量重读会把段内已插行整体双份插入。就地按段 dataset 的快照续
      // 读位（hgTailOff）种账，不依赖轮询节拍。无续读位时的停喂判据按消费形
      // 态收口（防误伤新段——SSE 先喂了行、轮询尚未起跑是常态）：
      // · think+text（真实/误杀代理，v2.54R）：段内已有思考行或消息气泡
      //   即停——两者只可能来自轮询/回填（SSE 不转发子代理 thinking/text），
      //   有行无账=旧版喂过账丢了，重读必重插；tool 行不经本路重插，不拦
      // · fullFeed（真 SendMessage 协作）：段内有任意过程行即停——独立会话
      //   行只能来自本轮询自喂，有行无账=旧版喂过，全量重读必整体重插
      if (!(aid in _HG.subTail)) {
        const _sb = _HG.subBlk && _HG.subBlk[tid];
        const _offDs = _sb && _sb.root && +_sb.root.dataset.hgTailOff;
        if (_offDs > 0) _HG.subTail[aid] = _offDs;
        else {
          const _bd = _sb && _sb.body;
          const fedAlready = fullFeed
            ? (_bd && _bd.querySelectorAll('.h-think-seg, .h-tool, .h-tool-res, .h-msg, .h-subblock-note').length)
            : (_bd && _bd.querySelectorAll('.h-think-seg, .h-msg.sub').length);
            // v2.54R：非 fullFeed 现在也喂 text（.h-msg.sub）——「有行无账」
            // 守卫必须把它算进去，否则 offset 账丢后从 0 重读会整体双份
          if (fedAlready) { _subTailDead[aid] = true; return; }
          _HG.subTail[aid] = 0;
        }
      }
      const off = _HG.subTail[aid] || 0;
      const r = await fetch('/api/harness/subagent_tail?sid=' + encodeURIComponent(sidAt)
        + '&agent=' + encodeURIComponent(aid) + '&offset=' + off);
      const j = await r.json();
      if (_HG.sid !== sidAt || !j.ok || !j.found) return;   // 切走/无转写：下轮再试
      if (typeof j.offset === 'number') {
        _HG.subTail[aid] = j.offset;
        // v2.47：已消费 offset 落段 dataset——随 innerHTML 快照携带，切会话
        // 往返 subTail 重置后 DOM 兜底扫描按它续读（从 0 重读=已插内容双份）
        const _b = _HG.subBlk && _HG.subBlk[tid];
        if (_b && _b.root && _b.root.isConnected) _b.root.dataset.hgTailOff = String(j.offset);
      }
      const txt = j.text || '';
      if (!txt) return;
      // 解析新增完整行：真实子代理取 thinking + text（v2.53 用户定调：段内
      // 必须与主会话一致有消息气泡——实测现行 CLI 的 SSE 已不转发子代理
      // text 事件，轮询是文本唯一来源；_subText 自带段尾同文去重防双份）；
      // 协作段 fullFeed 全喂（独立会话无事件流，轮询是唯一源）
      const lines = txt.split('\n');
      for (const ln of lines) {
        const s = ln.trim();
        if (!s) continue;
        let o; try { o = JSON.parse(s); } catch(_) { continue; }
        const blocks = o && o.message && o.message.content;
        if (!Array.isArray(blocks)) continue;
        for (const blk of blocks) {
          if (!blk) continue;
          if (blk.type === 'thinking' && String(blk.thinking || '').trim())
            _subThink(tid, blk.thinking, true);
          else if (blk.type === 'text' && String(blk.text || '').trim())
            _subText(tid, blk.text, true);
          else if (fullFeed && blk.type === 'tool_use' && blk.name)
            renderToolUse(blk, true, tid);
          else if (fullFeed && blk.type === 'tool_result' && blk.tool_use_id)
            _subToolResult(tid, blk);
        }
      }
    } catch(_) {}
    finally { _subTailBusy[aid] = false; }
  }
  async function _subTailDrainThenBackfill(tid, aid) {
    const sidAt = _HG.sid;
    // v2.47（需求2）：协作段 drain 也全喂——最后一次轮询与完成信号之间新
    // 落盘的 text/tool 行不补读就永久丢（与 P2 思考 drain 同理）
    const _ff = _subFullFeedTid(tid);
    try {
      for (let k = 0; k < 6; k++) {
        let wait = 0;
        while (_subTailBusy[aid] && wait < 3000) {
          await new Promise(r => setTimeout(r, 120)); wait += 120;
        }
        if (_HG.sid !== sidAt) return;   // 会话已切走：段随快照冻结，回填也弃
        const off0 = _HG.subTail[aid] || 0;
        await _subTailFetch(tid, aid, _ff);
        if ((_HG.subTail[aid] || 0) <= off0) break;   // 无推进=已到文件尾
      }
    } catch(_) {}
    _subBlkBackfill(tid, aid);
  }
  function _subEnd() {                     // 回合终结：全部定格；自动来源收起窗格
    let any = false;
    for (const t in _sub.tabs) {
      const tb = _sub.tabs[t];
      tb.run = false; any = true;
      // v3.2.6：停秒表（代理后台续跑时 _subFeed 会复活）；时间线定稿留给
      // 完成信号（task_notification→_subClose）——回合 result 不等于代理完
      // v3.2.6R2（审计N1）：collab 豁免——独立会话事件流不经本会话，
      // _subFeed 复活链对它不可达（唯一续流源=轮询镜像，无 tick 复活逻辑），
      // 停了就在 result→notification 窗口内秒表冻结（可达数分钟）
      if (tb.t && tb.t.tick) {
        const _a = (_HG.agents || {})[t];
        if (_a && !_a.done && _a.collab) continue;
        clearInterval(tb.t.tick); tb.t.tick = null;
      }
    }
    if (any) _subTabsPaint();
    // v2.35（P0-3）：用户手动打开的窗格不自动收——用户正在围观，收走就是
    // 「弹了出来一会又收回去了」；只有 ✕ 手动关。切会话/关 tab 清空不变。
    if (_subPaneEl && !_sub.manual) _subPaneEl.style.display = 'none';
  }
