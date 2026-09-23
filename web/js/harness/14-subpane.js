// harness subpane.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
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
    const t = r.done ? (r.doneAt || 0) : (r.t0 || 0);
    return `<button class="hg-sub-dir-row ${st}" data-hg-dir="${esc(r.tid)}"` +
      ` data-hg-dir-rpl="${r.rpl ? '1' : ''}" title="${esc(title)}">` +
      `<span class="hg-sub-dir-ico">${stIco}</span>` +
      `<span class="hg-sub-dir-main"><span class="hg-sub-dir-t1">` +
      `<span class="hg-sub-dir-title">${esc(title)}</span>` +
      `<span class="hg-sub-dir-st">${stTxt}${r.bg ? ' · 后台' : ''}${r.collab ? ' · 协作' : ''}</span></span>` +
      (sum ? `<span class="hg-sub-dir-sum">${esc(sum)}${String(r.result || '').trim().length > 120 ? '…' : ''}</span>` : '') +
      `</span>` +
      (t ? `<span class="hg-sub-dir-time">${esc(_harnessRelTime(t))}</span>` : '') +
      `</button>`;
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
      // v3.2R1(P1)+R2(N3)：协作代理无实况窗格（独立会话事件流不经本会话，
      // 开了必空白——10-sse task_started 对 collab 就是 _subDrop 的）——运行中
      // 点行跳主 flow 协作段：先按段键（data-hg-subblock=tid，wrapper-only
      // 形态 hgSubr 未写也能命中）直查自身段；miss 再按 hgSubr（续派同名多段
      // 取 DOM 最晚=最新轮段，对齐 _hgCollabSegFind 语义）；已结束走下方回放
      if (a.collab) {
        const aid = a.taskId || a.agentId || '';
        let seg = _hgFlow.querySelector(`.h-subblock[data-hg-subblock="${CSS.escape(tid)}"]`);
        if (!seg && aid) {
          const hits = [..._hgFlow.querySelectorAll('.h-subblock[data-hg-collab]')]
            .filter(el => { const hd = el.querySelector('.h-subblock-head'); return hd && hd.dataset.hgSubr === aid; });
          seg = hits[hits.length - 1] || null;   // DOM 最晚 = 最新轮段（v2.58 切段语义）
        }
        if (seg) {
          seg.classList.remove('collapsed');
          _hgSubSaveOpen(seg, true);               // 展开记忆（与既有段点击口径一致）
          seg.scrollIntoView({ block: 'center', behavior: 'smooth' });
          seg.classList.remove('hg-dyn-jump');
          void seg.offsetWidth;
          seg.classList.add('hg-dyn-jump');
          setTimeout(() => seg.classList.remove('hg-dyn-jump'), 1600);
        } else showBanner('协作代理过程在主消息流段内展示（暂无可跳转的段）', 2600);
        return;
      }
      _subOpen(tid, a.type, a.desc);               // 运行中 → live 实况 tab
      return;
    }
    _subReplay(tid, a.type, a.desc, a.taskId || a.agentId || '');   // 已结束 → 回放 tab（collab 分支内部自理）
  }
  function _subReset() {
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
      const _ag = (_HG.agents || {})[tid] || {};
      _sub.tabs[tid] = { label: _AGENT_LABEL[type] || type, type, desc, sc,
                         run: replay ? false : (!('done' in _ag) || !_ag.done),
                         err: !!_ag.err, replay: !!replay,
                         model: _ag.model || '' };
      _sub.order.push(tid);
      // v3.2：上限 6 个 tab，最旧让位（目录伪 tab 常驻不让位）
      if (_sub.order.filter(t => t !== _SUB_DIR).length > 6) {
        const old = _sub.order.find(t => t !== _SUB_DIR);
        if (old != null) {
          _sub.order = _sub.order.filter(t => t !== old);
          if (_sub.tabs[old] && _sub.tabs[old].sc.parentNode) _sub.tabs[old].sc.remove();
          delete _sub.tabs[old];
        }
      }
      _subBodyEl.appendChild(sc);
    }
    _subShow(); _subTabsPaint(); _subActivate(tid);
  }
  const _subNoreplay = new Set();
  const _subNoReplayNote = () =>
    '<div class="hg-sub-replay-note">未找到该子代理的转写记录，历史过程不可回放</div>';
  function _subReplay(tid, type, desc, agentId, force) {
    if (!_subPaneEl) return;
    const a = (_HG.agents || {})[tid] || {};
    // v2.57：协作档案有 taskId（=真实 agentId，v2.52 修复转写源后可拉全量）
    // ——不再走「过程不可回看」占位（过时判定，用户实锤途中关闭再开啥也没有）；
    // 无 taskId（连真实 id 都没反查到）才维持占位
    if (a.collab && !a.taskId && !agentId) {
      _subOpen(tid, type, desc, true);
      const sc0 = _sub.tabs[tid] && _sub.tabs[tid].sc;
      if (sc0 && !sc0.dataset.collabNote) {
        sc0.dataset.collabNote = '1';
        // v2.37R4（终审1）：拆两次 _subAppend——单根 append 语义下双根模板
        // 的第二个 div（结论正文）会被整体丢弃
        _subAppend(sc0, `<div class="hg-sub-replay-note">独立会话协作代理——过程不可回看，仅结论可回看</div>`, true);
        _subAppend(sc0, `<div class="hg-sub-msg">${esc(a.result || '（无结论记录）')}</div>`, true);
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
    if (_subNoreplay.has(agentId)) {      // v2.41：已判定不可回放——直接出示结论，不再发请求
      sc.innerHTML = '';
      sc.dataset.replayed = agentId;
      _subAppend(sc, _subNoReplayNote(), true);
      _sub.manual = true;
      return;
    }
    sc.innerHTML = '';
    sc.dataset.replayed = agentId;
    _subAppend(sc, `<div class="hg-sub-replay-note">回放加载中…</div>`, true);
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
              _subAppend(scf, `<div class="hg-sub-replay-note">${(j && j.err) ? esc('回放读取失败：' + j.err) : '回放读取失败——重新点击「回放该子代理过程」可重试'}</div>`, true);
            }
          }
          return;
        }
        const sc2 = _sub.tabs[tid] && _sub.tabs[tid].sc;
        if (!sc2) return;
        sc2.innerHTML = '';
        if (!j.found) {
          // v2.42：后端双源（projects 旧源+新版 CLI tasks 兜底）均未命中——
          // 文件不存在是持久事实，重拉永远同结果；记住结论，重点/重开不再发请求
          _subNoreplay.add(agentId);
          _subAppend(sc2, _subNoReplayNote(), true);
          return;
        }
        if (!(j.rows || []).length) {
          // v2.41R2：转写存在但无可渲染行——与「没有独立转写」是两回事，给中性
          // 文案且不进 noreplay 集（tab 重开后可重试，防误判永久锁死回放入口）
          _subAppend(sc2, '<div class="hg-sub-replay-note">转写存在但无可回放内容</div>', true);
          return;
        }
        _subAppend(sc2, `<div class="hg-sub-replay-note">回放 · ${esc(_AGENT_LABEL[type] || type)} · ${j.rows.length} 条记录</div>`, true);
        let lastToolBody = null;   // v2.57R：回放 result 并入最近工具行 body
        for (const row of j.rows) {
          if (row.k === 'text') {
            // 每行带头像+模型徽章（P1-C 体系复用）——标明这句话是谁发的
            // v2.37R4（终审1）：拆两次 _subAppend——单根 append 下双根模板
            // 的第二个 div（row.text 正文）会被整体丢弃
            const bare = String(row.model || '').split('[')[0] || row.model || '未知';
            _subAppend(sc2, `<div class="hg-sub-msg"><span class="h-ava ${_hgAvaCls(bare)}">${esc(bare.charAt(0).toUpperCase())}</span>` +
              `<span class="h-mmodel">${esc(bare)}</span></div>`, true);
            // 窗格重设计 P1-3：正文升级 md 渲染（懒高亮）。v2.57R：打 rp 铺底
            // 标记——镜像过渡查重的比对锚（防 fetch/轮询重叠窗口双份）
            const mrow = _subMdRow(row.text);
            mrow.dataset.hgRp = '1';
            _subAppendEl(sc2, mrow, true);
          } else if (row.k === 'note') {
            _subAppend(sc2, `<div class="hg-sub-replay-note">${esc(row.text)}</div>`, true);
          } else if (row.k === 'think') {
            // v2.43：思考行入回放（工厂复用 v2.57R；rp 标记同 text——查重锚）
            const th = _subPaneThinkRow(row.text || '');
            th.dataset.hgRp = '1';
            _subAppendEl(sc2, th, true);
          } else if (row.k === 'tool') {
            // v2.57R：折叠气泡工厂（点开展开详情）；回放直接定格 done；转写无
            // tool_use_id 不做配对。result 行并入最近工具行 body。rp 标记=镜像
            // 指纹查重锚（重叠窗口防双份工具行）
            const tw = _subPaneToolRow(row.name || '', row.hint || '', '', true);
            tw.dataset.hgRp = '1';
            lastToolBody = tw.querySelector('.hg-sub-tool-body');
            _subAppendEl(sc2, tw, true);
          } else if (row.k === 'result') {
            // v2.57R：结果并入最近工具行 body（折叠可见性同详情）；无前置工
            // 具行（转写截断窗口边界）才独立成行
            const rfull = String(row.text || '');
            if (lastToolBody && !lastToolBody.dataset.filled) {
              lastToolBody.dataset.filled = '1';
              const d = document.createElement('div');
              d.className = 'hg-sub-tool-out' + (row.err ? ' err' : '');
              d.textContent = rfull || '完成';
              lastToolBody.appendChild(d);
              continue;
            }
            const rtxt = rfull.replace(/\s+/g, ' ').trim().slice(0, 120);
            _subAppend(sc2, `<div class="hg-sub-res${row.err ? ' err' : ''}"` +
              (rfull.trim().length > 120 ? ` data-hg-subfull="${esc(rfull)}" title="点击展开全文"` : '') +
              `>↳ ${esc(rtxt || '完成')}</div>`, true);
          }
        }
        _subScroll(tid);
      })
      .catch(() => {
        const _tc = _sub.tabs[tid];
        if (_tc) _tc.replay = false;   // v2.57R：网络失败路径也放行镜像（与 .then 同口径）
        const sc3 = _sub.tabs[tid] && _sub.tabs[tid].sc;
        if (sc3) {
          delete sc3.dataset.replayed;   // v2.37R2（复审1）：清标记，重点即重拉
          sc3.innerHTML = ''; _subAppend(sc3, `<div class="hg-sub-replay-note">回放拉取失败（网络）——重新点击「回放该子代理过程」可重试</div>`, true);
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
  function _subCap(sc) {
    while (sc.children.length > 200) {
      const first = sc.firstElementChild;
      if (!first) break;
      if (first.classList.contains('hg-sub-omit')) {
        first.dataset.omitted = String((+first.dataset.omitted || 0) + 1);
        first.textContent = `⬆ 已省略 ${first.dataset.omitted} 行`;
        // 提示条已是首条：真正该删的是它后面那条内容行
        const victim = first.nextElementSibling;
        if (victim) victim.remove(); else first.remove();
      } else {
        const om = document.createElement('div');
        om.className = 'hg-sub-omit';
        om.dataset.omitted = '1';
        om.textContent = '⬆ 已省略 1 行';
        sc.insertBefore(om, first);
        first.remove();
      }
    }
  }
  function _subAppend(sc, html, noCap) {   // 上限 200 条/子代理，溢出删首条
    const d = document.createElement('div');
    d.innerHTML = html;
    sc.appendChild(d.firstElementChild || d);
    // v2.37R3（复审A）：noCap=true=回放路径——回放 201~202 行（含头部 note）
    // 会被 200 上限削掉头部 note 和领命首行、「已截断」告知自身也保不住，
    // 故整段绕过 cap；实时 tab 的 200 上限语义不变
    if (!noCap) _subCap(sc);
  }
  function _subAppendEl(sc, el, noCap) {
    sc.appendChild(el);
    if (!noCap) _subCap(sc);
  }
  function _subMdRow(text) {
    const d = document.createElement('div');
    d.className = 'h-bubble hg-sub-msgmd';
    d.innerHTML = renderMd(text);
    _codeLazyEnhance(d);
    return d;
  }
  function _subFeed(parentId, blocks) {
    if (!_sub.tabs[parentId]) return;
    const sc = _sub.tabs[parentId].sc;
    // 窗格重设计 P1-5：贴底跟随判定——必须在 append 之前测距底（append 后
    // scrollHeight 被新内容撑大，测出来恒不贴底）；≤80px=用户正跟读最新输出，
    // 才跟随滚动，上翻查看历史时不拽人
    const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;
    // v2.35：回合终结定格过的 tab，若对应代理其实还在跑（后台 Task 跨回合
    // 续跑），事件继续流入时恢复绿点脉冲——别让冻结态骗人
    const _ag = (_HG.agents || {})[parentId];
    if (_sub.tabs[parentId].run !== true && _ag && !_ag.done) {
      _sub.tabs[parentId].run = true;
      _subTabsPaint();
    }
    // 窗格重设计 P2-9：实况补头像+模型徽章行（对齐回放形态，消除两套不一致）。
    // 仅插一次（dataset 标记）；模型取实跑值（档案最新）优先、tab 建档快照兜底，
    // 都无（内置代理跑主链模型）用 tab 名——不编造，至少有头像色标
    if (!sc.dataset.avabadge) {
      sc.dataset.avabadge = '1';
      const mdl = (_ag && _ag.model) || _sub.tabs[parentId].model || _sub.tabs[parentId].label || '';
      const bare = String(mdl).split('[')[0] || mdl;
      const av = document.createElement('div');
      av.className = 'hg-sub-msg';
      av.innerHTML = `<span class="h-ava ${_hgAvaCls(bare)}">${esc(bare.charAt(0).toUpperCase())}</span>` +
        `<span class="h-mmodel">${esc(bare)}</span>`;
      sc.insertBefore(av, sc.firstElementChild);
    }
    for (const b of blocks) {
      // 窗格重设计 P1-3：文本行从裸 esc 升级 md 渲染（markdown-it + 懒高亮；
      // 元素直挂保懒高亮 IO 绑定，链接拦截由 init.js 全局捕获兜底）——
      // 子代理中间结论是 markdown，渲染质量对齐主 flow
      if (b.type === 'text' && b.text && b.text.trim())
        _subAppendEl(sc, _subMdRow(b.text));
      else if (b.type === 'thinking' && b.thinking) {
        // 窗格重设计 P2-6：thinking 进窗格——块粒度一行（不合并段），默认
        // 收起防淹；全文存 dataset，首次展开才 renderMd（懒渲染，量大不卡）。
        // 行内交互全走窗格体级委托（_subBodyEl onclick）
        _subAppendEl(sc, _subPaneThinkRow(b.thinking));
      }
      else if (b.type === 'tool_use') {
        // v2.55R：对称查重——SSE 同一事件里镜像（_subBlkAppendTool）先插、
        // 本分支后插，只查一侧必双份；两侧都查后无论谁先谁后均只落一行
        if (b.id && sc.querySelector(`.hg-sub-tool[data-tuid="${CSS.escape(b.id)}"]`))
          continue;
        const inp = b.input || {};
        const hint = inp.command || inp.file_path || inp.path || inp.pattern ||
                     inp.query || inp.description || inp.subject || inp.prompt || '';
        // 窗格重设计 P2-7：折叠气泡工厂（状态点灰=进行中，data-tuid 供结果
        // 回点；SSE 里 tool_use.id 与 tool_result.tool_use_id 同源恒可配对）
        _subAppendEl(sc, _subPaneToolRow(b.name || '', hint, b.id || '', false));
      }
    }
    if (stick) _subScroll(parentId);
  }
  function _subResult(parentId, tr) {
    if (!_sub.tabs[parentId]) return;
    const sc = _sub.tabs[parentId].sc;
    const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;   // P1-5：append 前测（同 _subFeed）
    const full = resultText(tr).trim();
    // 窗格重设计 P2-7：结果到达回点对应工具行——data-tuid 精确配对优先；
    // miss（id 缺失/行已被 cap 裁掉）回退从尾往前找第一条未定格的工具行
    // （SSE 流序下 tool_result 紧跟 tool_use；已 done 的行说明配对过别的
    // 结果，跳过——并行交错时也能落到真正没收到结果的那条上）
    let toolRow = tr.tool_use_id
      ? sc.querySelector(`.hg-sub-tool[data-tuid="${CSS.escape(tr.tool_use_id)}"]`) : null;
    if (!toolRow)
      for (let el = sc.lastElementChild; el; el = el.previousElementSibling) {
        if (el.classList.contains('hg-sub-tool') && !el.classList.contains('done')) { toolRow = el; break; }
      }
    if (!toolRow) {
      // v2.57R：全 miss（回放铺底行全 done 且 tuid 不匹配）——回退独立 ↳ 行
      //（与回放路径「无前置工具行」兜底对称），结果不丢；rtuid/subfull 属性
      // 与旧版独立行同款（防未来双源双份 + 超长点击展开）
      const d = document.createElement('div');
      d.className = 'hg-sub-res' + (tr.is_error ? ' err' : '');
      if (tr.tool_use_id) d.dataset.rtuid = tr.tool_use_id;
      if (full.length > 120) {
        d.dataset.hgSubfull = full;
        d.title = '点击展开全文';
      }
      d.textContent = '↳ ' + (full.replace(/\s+/g, ' ').slice(0, 120) || '完成');
      sc.appendChild(d);
      if (stick) _subScroll(parentId);
      return;
    }
    // v2.57R：防重+结果进工具行 body（折叠气泡——点开才显示，不再平铺 ↳ 行）
    if (toolRow.classList.contains('done')) return;
    toolRow.classList.add('done');
    if (tr.is_error) toolRow.classList.add('err', 'open');   // 错误自动展开
    const body = toolRow.querySelector('.hg-sub-tool-body');
    if (body && !body.dataset.filled) {
      body.dataset.filled = '1';
      const d = document.createElement('div');
      d.className = 'hg-sub-tool-out' + (tr.is_error ? ' err' : '');
      d.textContent = full || '完成';
      body.appendChild(d);
    }
    if (stick) _subScroll(parentId);
  }
  function _subClose(tid, err) {
    _subBlkFinish(tid, err);  // v2.43：主 flow 段头定格（✓/✗，不依赖窗格 tab 存活）
    const tb = _sub.tabs[tid];
    if (!tb) return;
    tb.run = false; tb.err = !!err;
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
    for (const t in _sub.tabs) { _sub.tabs[t].run = false; any = true; }
    if (any) _subTabsPaint();
    // v2.35（P0-3）：用户手动打开的窗格不自动收——用户正在围观，收走就是
    // 「弹了出来一会又收回去了」；只有 ✕ 手动关。切会话/关 tab 清空不变。
    if (_subPaneEl && !_sub.manual) _subPaneEl.style.display = 'none';
  }
