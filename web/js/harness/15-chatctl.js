// harness chatctl.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function renderList() {
    const kw = (_hgSearchEl.value || '').trim().toLowerCase();
    const items = _HG.sessions.filter(s => !kw || (s.title || '').toLowerCase().includes(kw)
      || (s.cwd || '').toLowerCase().includes(kw));
    // v2.3.9 项目分组视图（用户需求：一个项目多个会话归一组查找）：
    // 按 cwd basename 分组、组按组内最近活跃排序、组内会话按活跃排序。
    // v2.3.13 单会话组同样可折叠（用户实锤「单会话不能收缩」）——组头带
    // chev、点击开合，多会话组额外有计数徽章；开合 localStorage 持久化。
    const groups = new Map();   // proj -> {items: [], latest: 0, cwd: ''}
    for (const s of items) {
      const proj = (s.cwd || '').split(/[\\/]/).pop() || '~';
      let g = groups.get(proj);
      if (!g) { g = { items: [], latest: 0, cwd: s.cwd || '' }; groups.set(proj, g); }
      g.items.push(s);
      if ((s.last_active || 0) > g.latest) g.latest = s.last_active;
    }
    const ordered = [...groups.entries()].sort((a, b) => (b[1].latest || 0) - (a[1].latest || 0));
    // 折叠态：localStorage hg-grp:<proj>:closed（单会话组同权可折）
    const html = ordered.map(([proj, g]) => {
      g.items.sort((a, b) => (b.last_active || 0) - (a.last_active || 0));
      const multi = g.items.length > 1;
      const closed = (() => { try { return localStorage.getItem('hg-grp:' + proj + ':closed') === '1'; } catch(_) { return false; } })();
      const anyBusy = g.items.some(s => s.busy);
      const hasActive = g.items.some(s => s.sid === _HG.sid);
      let h = '';
      // 组头（所有组可折叠；多会话组带计数徽章）
      h += `<div class="hg-grp${closed ? ' closed' : ''}${hasActive ? ' active-grp' : ''}"
             data-grp="${esc(proj)}"
             title="${esc(g.cwd)}">
              <span class="hg-grp-chev">▸</span>
              <span class="hg-grp-name">${esc(proj)}</span>
              <span class="hg-grp-count">${multi ? g.items.length : ''}</span>
              ${anyBusy ? '<span class="hg-item-busy" title="回复中">●</span>' : ''}
              <span class="hg-grp-time">${_harnessRelTime(g.latest)}</span>
            </div>`;
      if (!closed) {
        // v2.3.13 子项统一 grp-child 分层（缩进+左侧竖线）——单会话组也要
        // 同款层次（用户实锤「单会话没有像多会话有分层效果」）；时间只在
        // 组头显示（单会话组头时间即该会话活跃时间，不重复出独立时间行）
        h += g.items.map(s => `
          <div class="hg-item${s.sid === _HG.sid ? ' active' : ''} grp-child" data-sid="${esc(s.sid)}" title="${esc(s.cwd || '')} · ${esc(s.title || '')}">
            <div class="hg-item-row">
              <span class="hg-item-title">${esc(s.title || '新会话')}</span>
              <span class="hg-item-acts">
                ${s.busy ? '<span class="hg-item-busy" title="回复中">●</span>' : ''}
                <button class="hg-item-act" data-act="rename" data-sid="${esc(s.sid)}" title="重命名">✎</button>
                <button class="hg-item-act del" data-act="del" data-sid="${esc(s.sid)}" title="删除会话">✕</button>
              </span>
            </div>
            <div class="hg-item-row">
              <span class="hg-item-sub">${s.model ? esc(s.model) + (_hgMm(s.model) ? ' ' + _HG_EYE : '') : ''}</span>
            </div>
          </div>`).join('');
      }
      return h;
    }).join('');
    _hgListEl.innerHTML = html || '<div class="hg-list-empty">暂无会话</div>';
  }
  function newChat() {
    saveCache(); switchTo(null);
    // v2.25：新建 = 无工程默认状态——上个会话的项目目录不再继承（用户实测
    // 「点新建会话，打开的还是串口控制台Pro，不对」）。发消息时 cwd 为空
    // 即开在默认 ~；chip 回显「选择项目」。切回历史会话仍跟随恢复该会话的
    // 项目（v2.19）；localStorage 的 hg-last-cwd 不动，留给下次启动恢复。
    if (_HG.cwd) { _HG.cwd = null; projChipLabel(); }
  }
  async function ensureSession() {
    if (_HG.sid) return _HG.sid;
    const r = await fetch('/api/harness/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model: _HG.model || '', cwd: _HG.cwd || '',
                            permission: _HG.perm || 'auto', think: _HG.thinkLv || ''})});
    const j = await r.json();
    if (!j.ok) {
      // v2.19：恢复的「上次项目目录」已被删/移动 → 清记录回退 ~ 重试一次，
      // 而不是卡在报错里让用户手动重选。
      if (j.err && j.err.includes('目录不存在') && _HG.cwd) {
        showBanner('上次的项目目录已不存在：' + _HG.cwd, 3500, true);
        _HG.cwd = null; _hgSaveCwd(null); projChipLabel();
        return ensureSession();
      }
      if (j.err && j.err.includes('未检测到 claude')) { openClaudeSetup(); }
      showBanner(j.err || '会话创建失败', 3500, true);
      return null;
    }
    _HG.sid = j.sid; _HG.seq = 0; _HG.alive = true;
    _hgTitleEl.textContent = '新会话';
    _hgCwdEl.textContent = (j.cwd || '').split(/[\\/]/).pop() || '~';
    openSSE(j.sid, 0);
    refreshSessions();
    return j.sid;
  }
  async function dispatch(text, images, files, restoreInput) {
    const sid = await ensureSession();
    if (!sid) return false;
    // v2.27：引用拼装——取出即清（排队泵逐条 dispatch 时只有第一条带引用，
    // 后续排队项是新输入的独立消息）
    let out = text || '';
    if (_HG.quote && out.trim()) {
      const qt = _HG.quote.text.length > 2000
        ? _HG.quote.text.slice(0, 2000) + '…（引用已截断）' : _HG.quote.text;
      out = `[引用 ${_HG.quote.who} 的消息]\n${qt}\n\n[我的问题]\n${text}`;
      setQuote(null);
    }
    text = out;
    _hgHistAppend(sid, text);          // 输入历史（记录到真实会话 scope）
    _HG.histNav = null;
    // v2.20：乐观渲染——connect 一回来就画出自己的气泡。原实现要等 SSE 的
    // user_echo 绕一圈才显示，新会话冷启动时「发出去半天上面没动静」（用户
    // 实测）。echoFast 让随后到达的 SSE 同文本 echo 跳过，不双渲染。
    const el = renderUser(text, images, files);
    _HG.echoFast = { text: text || '' };
    _hgScrollBottom(true);                 // 自己发的消息无条件回底
    setBusy(true);
    try {
      const r = await fetch('/api/harness/send', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid, text, images, files})});
      const j = await r.json();
      if (!j.ok) {
        try { el.remove(); } catch(_) {}       // 回滚乐观气泡
        endThinking(); grpFinalize(false, { turnEnd: true });   // v3.2.2：发送失败=回合中止，正文留头外
        dispatch.rej = String(j.err || '');    // v2.35.1（F6）：失败原因外显（queuePump 据此判可回队）
        // v2.35.1（F6）：后端「正在回复」= 后端真忙（前端误判空闲的竞态）——
        // 同步置 busy 而非清空闲：清空闲会连锁触发泵链把整队消息逐条打进
        // 拒收丢弃；置 busy 则泵链挂起、排队条目由 queuePump 回队首，真回合
        // 结束再发。直发（非泵）命中则按排队语义入队，消息不丢。其余失败
        // 维持原行为（清空闲 + 文本回输入框）
        if (/正在回复/.test(dispatch.rej)) {
          setBusy(true);
          if (restoreInput) queuePush({ text: text || '', images: images || [], files: files || [] });
        }
        else {
          setBusy(false);
          if (restoreInput) _hgInput.value = text;
        }
        showBanner(j.err || '发送失败', 3000, true);
        return false;
      }
      dispatch.rej = '';
      _HG.dirty = true;
      refreshSessions();
      return true;
    } catch(e) {
      dispatch.rej = 'network';
      try { el.remove(); } catch(_) {}
      endThinking(); grpFinalize(false, { turnEnd: true }); setBusy(false);   // v3.2.2 同上
      if (restoreInput) _hgInput.value = text;
      showBanner('发送失败：' + e, 3000, true);
      return false;
    }
  }
  const HG_SLASH = [
    ['/help', '内建命令一览'],
    ['/resume', '切换会话（左侧列表高亮）'],
    ['/clear', '新建会话（原会话保留可切回）'],
    ['/model', '打开模型菜单；/model 名 直接切换（模糊匹配）'],
    ['/status', '会话状态与上下文用量'],
    ['/compact', '手动压缩上下文（可附保留要点：/compact 保留串口配置等）'],
    ['/rewind', '回退最近 N 个完整回合，默认 1（爆窗/坏回合逃生门；历史自动备份）'],
    ['/roles', '角色设计说明（双形态主会话直干/设计+审核代理与当前配置）'],
    ['/mcp', 'MCP 服务器列表与连接状态（代跑 claude mcp list）'],
    ['/exit', '退出 claude 进程（会话保留，发送自动恢复）'],
  ];
  const HG_SLASH_DEAD = [
    ['/ide', '连接 IDE（headless 无此通道，用终端交互模式操作）'],
    ['/vim', 'vim 编辑模式（交互 TUI 专属）'],
    ['/terminal-setup', '终端按键配置（交互 TUI 专属）'],
    ['/statusline', '状态栏定制（交互 TUI 专属）'],
    ['/login', '账号登录（交互流程，headless 无法弹授权页）'],
    ['/logout', '账号登出（同上，在终端交互模式里操作）'],
    ['/doctor', '安装诊断（交互 TUI 专属）'],
    ['/install-github-app', 'GitHub App 引导（需浏览器授权流程）'],
    ['/migrate-installer', '安装迁移（交互 TUI 专属）'],
    ['/release-notes', '版本说明（交互 TUI 专属）'],
    ['/privacy-settings', '隐私设置（交互 TUI 专属）'],
    ['/config', '设置面板（headless 下改配置用本工具 设置 → API 配置）'],
    ['/permissions', '权限面板（会话级权限在工具栏「权限」切换）'],
    ['/hooks', 'Hooks 管理（直接改 ~/.claude/settings.json）'],
    ['/memory', '记忆文件（直接编辑 CLAUDE.md / 项目 memory）'],
    ['/add-dir', '追加工作目录（本工具按会话指定 cwd，无需追加）'],
    ['/context', '上下文明细（/status 已展示用量环）'],
    ['/cost', '费用统计（v2.3 起不显示金额，用量见 /status）'],
    ['/agents', '子代理面板（对话流里可看子代理过程抽屉）'],
    ['/plugins', '插件管理（直接改 ~/.claude 配置）'],
    ['/rewind', '回退检查点（交互 TUI 专属）'],
    ['/todos', '任务列表（模型回复中会展示任务进度）'],
    ['/export', '导出对话（暂不支持，可在 ~/.claude/projects 找转写）'],
  ];
  function renderSysCard(title, rows) {
    const d = document.createElement('div');
    d.className = 'h-syscard';
    d.innerHTML = '<div class="h-syscard-t">' + esc(title) + '</div>' +
      rows.map(r => '<div class="h-syscard-r"><b>' + esc(r[0]) + '</b><span>' + esc(r[1]) + '</span></div>').join('');
    addRow(d);
    _hgScrollBottom();
  }
  function applyModel(m) {
    // v2.27.10：乐观更新失败必须回滚芯片——切模型被拒（回复中 409）时
    // 芯片已显示新模型而会话实际还是旧模型（用户实锤：以为切到多模态
    // flash，实际一直跑非多模态 glm-5.3，发图全变 CDN 链接还以为坏了）
    const prev = _HG.model;
    const chip = _hgQ('[data-hg-model]');
    const setChip = (mm) => { chip.innerHTML = '🧠 ' + esc(mm || '默认') + ' ▾'; };
    _HG.model = m;
    setChip(m);
    if (_HG.sid) {
      fetch('/api/harness/set_model', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid, model: m})})
        .then(r => r.json())
        .then(j => {
          if (!j.ok) {
            _HG.model = prev; setChip(prev);   // 回滚：芯片如实反映会话模型
            showBanner((j.err || '切换模型失败') + '（仍用 ' + (prev || '默认') + '）', 3500, true);
          }
        })
        .catch(() => { _HG.model = prev; setChip(prev); showBanner('切换模型失败', 3000, true); });
      refreshSessions();
    } else showBanner('模型 ' + m + ' 将用于新会话', 2200);
  }
  async function execSlash(raw) {
    const m = raw.match(/^\/([a-z0-9_-]+)(?:\s+([\s\S]*))?$/i);
    if (!m) return false;
    const cmd = m[1].toLowerCase(), arg = (m[2] || '').trim();
    if (!HG_SLASH.some(x => x[0] === '/' + cmd) && !HG_SLASH_DEAD.some(x => x[0] === '/' + cmd)) return false;
    // v2.25：CLI 纯交互命令——本地拦下说明去向，不进对话
    const dead = HG_SLASH_DEAD.find(x => x[0] === '/' + cmd);
    if (dead && cmd !== 'help') {
      renderSysCard('CLI 交互命令（headless 不可用）', [[dead[0], dead[1]]]);
      return true;
    }
    if (cmd === 'help') {
      renderSysCard('内建命令（本地执行，不进入对话）', HG_SLASH);
      renderSysCard('CLI 交互命令（headless 不可用，已本地拦截）', HG_SLASH_DEAD);
    } else if (cmd === 'mcp') {
      // v2.25：headless 没有 CLI 的 MCP 面板——后端代跑 claude mcp list，
      // 原文按行渲染（server 名拆到左列，其余含连接状态在右列）
      (async () => {
        let j = null;
        try { j = await (await fetch('/api/harness/mcp_list')).json(); } catch(_) {}
        if (!j || !j.ok) {
          renderSysCard('MCP 服务器', [['查询失败', (j && j.err) || '网络错误']]);
          return;
        }
        const rows = String(j.output || '').split(/\r?\n/).filter(s => s.trim()).map(s => {
          const i = s.indexOf(':');
          return (i > 0 && i < 40) ? [s.slice(0, i).trim(), s.slice(i + 1).trim()] : ['', s.trim()];
        });
        renderSysCard('MCP 服务器（claude mcp list 实时状态）', rows.length ? rows : [['（空）', '没有配置任何 MCP 服务器']]);
      })();
    } else if (cmd === 'resume') {
      const side = _hgWrap.querySelector('.hg-side');
      if (side) { side.classList.remove('flash'); void side.offsetWidth; side.classList.add('flash'); }
      _hgSearchEl.focus();
      showBanner('点击左侧会话即可切换', 2200);
    } else if (cmd === 'clear') {
      newChat();
      showBanner('已新建会话', 2000);
    } else if (cmd === 'model') {
      if (!arg) { _hgQ('[data-hg-model]').click(); return true; }
      await fetchModels();      // v2.25：每次重新拉（配置方案切换后模型映射变了）
      const kw = arg.toLowerCase();
      const hits = (_HG.models.models || []).filter(x => x.toLowerCase().includes(kw));
      if (hits.length === 1) { applyModel(hits[0]); showBanner('已切换模型 · ' + hits[0], 2400); }
      else if (!hits.length) showBanner('没有匹配「' + arg + '」的模型', 3000, true);
      else showBanner('匹配到多个：' + hits.join(' / '), 3400, true);
    } else if (cmd === 'status') {
      let ctx = null;
      if (_HG.sid) {
        try { ctx = await (await fetch('/api/harness/ctx?sid=' + encodeURIComponent(_HG.sid))).json(); } catch(_) {}
      }
      const rows = [
        ['会话', _HG.sid ? _HG.sid.slice(0, 8) + '…' : '未创建'],
        ['模型', _HG.model || (_HG.models && _HG.models.default) || '默认'],
        ['项目', _HG.cwd || '未选择'],
        ['进程', _HG.alive ? (_HG.busy ? '运行中 · 正在生成回复' : '空闲待命') : '未运行（发送消息自动恢复）'],
        ['权限', _HG_PERMS[_HG.perm] || '自动执行'],
        ['思考', _HG.thinkLv ? (_HG_THINKS[_HG.thinkLv] || _HG.thinkLv) : '默认'],
      ];
      if (ctx && ctx.ok && ctx.window) {
        const pct = ctx.used ? Math.round(ctx.used / ctx.window * 100) + '%' : '—';
        const u = ctx.used ? (ctx.used / 1000).toFixed(1) + 'K / ' + (ctx.window / 1000).toFixed(0) + 'K (' + pct + ')' : '';
        rows.push(['上下文', ctx.compacted ? (u ? u + ' · ' : '') + '压缩后待首轮回复' : (u || '首轮回复后统计')]);
      }
      renderSysCard('会话状态', rows);
    } else if (cmd === 'compact') {
      // v2.28.4：实测 CLI 2.1.267 headless（stream-json stdin）下，用户消息
      // 里的斜杠命令会被真实执行——发 /compact 触发 compacting 状态事件
      // →压缩→重新 init（事件流 v2.20 已有分割线渲染）。走正常发送管线，
      // 压缩过程与耗时照常显示；arg 作为保留要点附给 CLI。
      // v2.28.10：后端超窗守卫已放行 /compact（拒发锁死出口的实锤修复）。
      await dispatch('/compact' + (arg ? ' ' + arg : ''), null, null, false);
    } else if (cmd === 'rewind') {
      // v2.28.11：会话回退——截断转写到最后第 N 个完整回合（备份保全量），
      // 杀进程，下次发消息 --resume 续上回退后的上下文。爆死态（/compact
      // 都压不动）与「上一轮搞砸了」的统一逃生门。
      if (!_HG.sid) { showBanner('当前没有活动会话', 2200); return true; }
      const n = Math.max(1, Math.min(50, parseInt(arg, 10) || 1));
      try {
        const r = await fetch('/api/harness/rewind', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({sid: _HG.sid, turns: n})});
        const j = await r.json();
        showBanner(j.ok ? ('⏪ ' + j.msg + '——发送消息即续上')
                        : ('回退失败：' + (j.err || '未知')), 4600, !j.ok);
      } catch(e) { showBanner('回退失败：' + e, 3000, true); }
    } else if (cmd === 'roles') {
      // 角色设计说明——含按当前 API 方案解析出的实际模型（v2.53：设计者/
      // 审计者各自 resolved）。双形态主会话都直干所有活；子代理只留
      // designer（只设计）+ reviewer（只读审核）两个代理
      (async () => {
        let j = null;
        try { j = await (await fetch('/api/harness/roles')).json(); } catch(_) {}
        const r = (j && j.roles) || {};
        const rs = (j && j.resolved) || {};
        const light = j && j.mode === 'light';
        const dm = rs.designer || '按当前方案自动识别';
        const rm = rs.reviewer || '按当前方案自动识别';
        const numOr = (k, d) => { const n = parseInt(r[k], 10);
          return Number.isFinite(n) ? Math.max(0, n) : d; };
        const modeRows = light ? [
          ['当前形态', '轻主力（主会话是轻模型）——直干所有活：编码/执行/调试都自己做，不派干活子代理'],
          ['设计', `designer 代理（${dm}）——只设计绝不干活：架构/模块划分/关键决策/风险/依赖顺序；不写代码不改文件不跑实现。派发必须带全上下文（目标/背景约束/已试方案/文件+行号/验收标准）`],
          ['审核', `reviewer 代理（${rm}）——只读对抗审核：假定代码有错专门挑毛病（需求符合性/逻辑/健壮性/安全/一致性），不允许修改代码/测试用例，PASS/FAIL 二选一`],
          ['标准流程', '中改主会话改完 → reviewer 轻审；大改先 designer 出方案 → 主会话实施 → reviewer 全审 → FAIL 回炉 → 致命/严重问题清零才收 → 主会话汇总答复'],
        ] : [
          ['当前形态', '重主力直干（主会话是重模型）——需求承接/方案/编码/debug/杂活全部自己干，不派干活子代理'],
          ['审核兜底', `reviewer 代理（${rm}）——单次直改超线由结算审核兜底（自动续发要求派 reviewer 补审，PASS/FAIL；FAIL 自己修复后复审）`],
        ];
        renderSysCard('角色设计（双形态直干）', [
          ...modeRows,
          ['状态', r.enabled === false ? '已关闭（config.json harness_roles.enabled）' : '已启用'],
          // 审计信息进 /roles 输出（用户定调：判定用客观事实，配置要看得见）
          ['审核模式', !r.enabled ? '—（三角色未启用）'
            : light ? (r.audit_mode === 'off' ? '关闭（audit_mode=off）'
              : r.audit_mode === 'warn' ? '仅警示（audit_mode=warn）——回合结束盘点工具调用，违规出红色警示不自动续发'
              : '自动补审（audit_mode=auto，默认）——回合结束盘点工具调用记录，直改超线未送审自动续发要求派 reviewer 补审；连续 3 回合违规降级为仅警示')
            : (r.audit_mode === 'off' ? '关闭（audit_mode=off）'
              : r.audit_mode === 'warn' ? '仅警示（audit_mode=warn）——回合结束盘点直改量，超线出红色警示不自动续发'
              : '自动补审（audit_mode=auto，默认）——回合结束盘点直改量，超线自动续发要求派 reviewer 补审；连续 3 回合违规降级为仅警示')],
          ['分级线', !r.enabled ? '—' : light
            ? `免审：单次直改 ≤ ${numOr('l1_max_lines', 100)} 行；轻审：单次直改 ≤ ${numOr('l2_max_lines', 200)} 行（主会话直改 + reviewer 轻审）；超线属大改——须 reviewer 取证级全审；设计线：单次直改 ≥ ${numOr('design_max_lines', 200)} 行动手前须先派 designer 出方案（0=不强制；不计文件数、不做回合累计）`
            : `审核线：单次直改 ≤ ${numOr('l2_max_lines', 200)} 行——超线触发结算审核（派 reviewer 补审；不计文件数、不做回合累计；0=最严档）`],
          ['推荐配置', '主会话配轻模型（如 glm-5.3-flash）——直干省 token，方案/审核走设计/审核代理，即轻主力形态'],
          ['模型解析', `设计 ${rs.designer || '自动识别'} / 审核 ${rs.reviewer || '自动识别'}——各槽显式配置（designer_model/reviewer_model）优先，留空回退代理池（heavy_model）→ 方案模型表自动分类（名字含 opus=代理池，其余=主会话池）→ 默认；端点映射（model_map）可按 base_url 覆盖；换 API 方案自动适配`],
          ['形态判定', r.main_model ? `主会话模型槽已显式配置（harness_roles.main_model=${r.main_model}）——按此名识别形态` : '主会话模型槽未配置——按实跑模型名自动识别（名字含 opus=重主力，其余=轻主力）；切模型/改配置下条消息自动换形态'],
        ]);
      })();
    } else if (cmd === 'exit') {
      if (!_HG.sid) { showBanner('当前没有活动会话', 2200); return true; }
      fetch('/api/harness/kill', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
      showBanner('进程退出中，发送消息自动恢复', 2600);
    }
    return true;
  }
  const SKILL_ZH = {
    'data-analysis': '数据分析与可视化：查库、报表、表格自动化',
    'database-operations': '数据库设计/迁移/SQL优化/索引/N+1 治理',
    'doc-coauthoring': '结构化文档协作撰写（方案/规格/决策文档）',
    'find-skills': '发现并安装新技能',
    'hiklink-claw-cli': 'HikLink 企业通讯 CLI：发消息/云文档/日程/会议',
    'hiklink-cloud-doc-toolkit': '在线云文档（表格编辑器）单元格自动化 CLI',
    'hikvision-enc-query': '查海康产品加密配置（按物料代码）',
    'hikvision-spec-query': '查海康产品 SPEC 规格说明书/产品参数',
    'kernel-weekly': '抓 LWN 周刊生成中文内核周报档案',
    'log-analyzer': '日志解析/检索/错误模式/堆栈分析',
    'maas-kb-management': 'MaaS 知识库与文档一站式管理',
    'mermaid-diagram': '生成 Mermaid 图（流程/架构/时序/脑图）',
    'office': 'Excel/Word/PPT/Google 文档处理与自动化',
    'pdf-text-extractor': 'PDF 文本提取（支持 OCR）',
    'playwright-scraper-skill': 'Playwright 网页抓取（带反爬处理）',
    'self-improving-agent': '沉淀纠错与经验，持续自我改进',
    'software-platform-ops': '海康软件平台组件配置表/换包/构建打包',
    'sso-login': '自动化 SSO 登录，取可复用的会话 cookie',
    'stop-slop-zh': '去除中文 AI 腔，让文字更自然',
    'windows-ui-automation': 'Windows GUI 自动化（鼠标/键盘/窗口）',
    'dataviz': '图表/仪表盘设计系统（配色/可访问性）',
    'claude-api': 'Claude API/SDK 参考（模型/定价/流式）',
    'planning-with-files': '文件式任务计划（task_plan/findings/progress）',
    'code-review': '审查当前 diff/PR 的正确性与可简化点',
    'simplify': '对当前改动做复用/简化/效率清理并应用',
    'security-review': '对当前分支改动做安全审查',
    'init': '生成 CLAUDE.md 项目说明文件',
    'run': '启动项目应用并驱动验证改动',
    'loop': '按周期重复运行某个提示词/命令',
  };
  function _skillDesc(s) {
    // 键归一化：技能 name 可能是「Data Analysis」（大写+空格）而映射键是
    // data-analysis（小写连字符）——统一 lower+空格/下划线转连字符再查
    const n = (s.name || '').toLowerCase().replace(/[\s_]+/g, '-');
    const d = s.desc || s.description || '';
    return SKILL_ZH[n] || (_HG.skillZh || {})[n] || (_HG.skillZh || {})[d] || d;
  }
  function _skillZhSync() {
    const norm = (n) => (n || '').toLowerCase().replace(/[\s_]+/g, '-');
    const need = (_HG.skills || []).filter(s => {
      const d = (s.desc || '').trim();
      return d && !/[一-鿿]/.test(d) && !SKILL_ZH[norm(s.name)];
    });
    if (!need.length) return;
    fetch('/api/harness/skill_zh/translate', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({items: need.map(s => ({name: s.name, desc: s.desc}))})})
      .then(r => r.json()).then(j => {
        if (!j.ok || !j.map) return;
        _HG.skillZh = Object.assign({}, _HG.skillZh, j.map);
        // 菜单若开着：热替换各项描述，不用关了重开（v2.27.1 修：openPop
        // 此前不带 kind 类，.hg-pop.skill 永远查不到，热替换从未生效）
        const pop = _hgWrap.querySelector('.hg-pop.skill');
        if (pop) pop.querySelectorAll('[data-skill]').forEach(el => {
          const s = (_HG.skills || []).find(x => x.name === el.dataset.skill);
          if (!s) return;
          const span = el.querySelector('span');
          if (span) span.textContent = _skillDesc(s).slice(0, 60);
        });
        if (_HG.pop === 'slash') slashMenuUpdate();
      }).catch(() => {});
  }
  function slashMenuUpdate() {
    const mm = _hgInput.value.match(/^\/([a-z0-9_-]*)$/i);
    if (!mm) { if (_HG.pop === 'slash') closePop(); return; }
    const kw = mm[1].toLowerCase();
    const built = HG_SLASH.filter(x => x[0].slice(1).startsWith(kw))
      .map(x => ({ slash: x[0].slice(1), desc: x[1] }));
    const sk = (_HG.skills || []).filter(s => (s.name || '').toLowerCase().startsWith(kw))
      .map(s => ({ skill: s.name, desc: _skillDesc(s).slice(0, 70) }));
    const list = built.concat(sk);
    if (!list.length) { if (_HG.pop === 'slash') closePop(); return; }
    _HG.slashList = list; _HG.slashSel = 0;
    const html = '<div class="hg-pop-list">' + list.map((x, i) =>
      `<div class="hg-pop-item${i === 0 ? ' on' : ''}" data-i="${i}"><b>/${esc(x.slash || x.skill)}</b><span>${esc(x.desc || '')}</span></div>`).join('') +
      '</div><div class="hg-pop-foot">ⓘ 输入内容以搜索命令、技能</div>';
    const p = openPop('slash', _hgInput, html);
    // openPop 的 left/bottom 按 card-wrap 坐标系算，而挂载点 .hg-input-stack
    // 自身是定位元素——照搬会错位（菜单飘进消息区）。这里按 stack 原位
    // 重定位：与 textarea 同宽、贴其上缘 6px（参考 CLI 的命令面板位置）
    if (p) {
      p.style.left = '0';
      p.style.right = '0';
      p.style.width = 'auto';
      p.style.bottom = 'calc(100% + 6px)';
    }
    // 技能懒加载：首次敲 / 后台拉一次，到了重弹把技能补进菜单
    if (!_HG.skills) {
      _HG.skills = [];
      fetch('/api/harness/skills').then(r => r.json()).then(j => {
        _HG.skills = (j.ok && j.skills) || [];
        _HG.skillZh = (j.ok && j.zh) || {};
        _skillZhSync();
        if (_HG.pop === 'slash') slashMenuUpdate();
      }).catch(() => {});
    }
  }
  function slashHighlight() {
    const p = _hgWrap.querySelector('.hg-pop.slash');
    if (!p) return;
    const items = p.querySelectorAll('.hg-pop-item');
    items.forEach((el, i) => el.classList.toggle('on', i === _HG.slashSel));
    const cur = items[_HG.slashSel];
    if (cur) cur.scrollIntoView({ block: 'nearest' });
  }
  function handleSlashKey(e) {
    if (_HG.pop !== 'slash') return false;
    const list = _HG.slashList || [];
    if (!list.length) return false;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = list.length;
      _HG.slashSel = e.key === 'ArrowDown' ? (_HG.slashSel + 1) % n : (_HG.slashSel - 1 + n) % n;
      slashHighlight();
      return true;
    }
    if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) {
      e.preventDefault();
      slashPick(list[_HG.slashSel >= 0 ? _HG.slashSel : 0]);
      return true;
    }
    if (e.key === 'Escape') { e.preventDefault(); closePop(); return true; }
    return false;
  }
  function slashPick(x) {
    if (!x) return;
    closePop();
    _hgInput.value = ''; _hgInput.style.height = 'auto'; renderOverlay('');
    if (x.slash) {
      if (x.slash === 'model') _hgQ('[data-hg-model]').click();
      else execSlash('/' + x.slash);
    } else {
      _hgInput.value = '/' + x.skill + ' ';           // 技能：插入待补参（同⚡按钮行为）
      renderOverlay(_hgInput.value);
      _hgInput.focus();
    }
  }
  async function send() {
    const text = _hgInput.value.trim();
    if (!text && !_HG.atts.length) return;
    // v2.21：内建斜杠命令本地执行（附件与命令互斥，命令不需要附件）
    if (!_HG.atts.length && text.startsWith('/')) {
      const c0 = text.split(/\s/, 1)[0].toLowerCase();
      // v2.25：DEAD 表命中也本地执行（拦下 CLI 交互命令，不发后端白耗一轮）
      if (HG_SLASH.some(x => x[0] === c0) || HG_SLASH_DEAD.some(x => x[0] === c0)) {
        _hgInput.value = ''; _hgInput.style.height = 'auto'; renderOverlay('');
        execSlash(text);
        return;
      }
    }
    const images = _HG.atts.filter(a => a.isImg).map(a => a.path);
    const files = _HG.atts.filter(a => !a.isImg).map(a => a.path);
    // v2.20：回复执行中不再拦「正在回复中」——排进队列（ZCode 式），
    // 结束后自动发送；排队条上可 ↑立即 / ✎编辑 / 🗑丢弃
    if (_HG.busy) {
      queuePush({ text, images, files });
      _hgInput.value = ''; _hgInput.style.height = 'auto'; renderOverlay('');
      clearAtts();
      if (_HG.sid) delete _HG.attsBy[_HG.sid];   // 已随消息带走，暂存别再还回来
      return;
    }
    _hgInput.value = ''; _hgInput.style.height = 'auto'; renderOverlay('');
    clearAtts();
    if (_HG.sid) delete _HG.attsBy[_HG.sid];
    dispatch(text, images, files, true);
  }
  async function stopGen() {
    if (!_HG.sid) return;
    const sid = _HG.sid;
    // v2.15：停止必须自带兜底。复位的唯一来源是后端回一条 `interrupted`
    // 事件，而后端 interrupt() 在「自身 busy 已是 false」时直接返回错误、
    // 不发任何事件（进程刚退出、事件丢失、会话查无此 sid 都会走到这条）。
    // 旧实现不看响应也不兜底 → 前端永远停在生成态，输入框被 busy 拦住，
    // 点 ■ 再走一遍同样的路径，形成死循环。
    let gotEvent = false;
    const onInt = (e) => { if (e.detail === sid) gotEvent = true; };
    try {
      document.addEventListener('hg-interrupted', onInt);
      const r = await fetch('/api/harness/interrupt', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid})});
      const j = await r.json().catch(() => null);
      if (!j || !j.ok) {
        // 后端明确拒绝（没有进行中的回复）→ 前端本就该收工
        if (_HG.sid === sid) setBusy(false);
        if (j && j.err) showBanner(j.err, 2500);
        return;
      }
      // 后端已受理：等 interrupted 事件；超时没等到就自行收尾
      await new Promise(res => setTimeout(res, 1500));
      if (!gotEvent && _HG.sid === sid) setBusy(false);
    } catch(_) {
      if (_HG.sid === sid) setBusy(false);
    } finally {
      document.removeEventListener('hg-interrupted', onInt);
    }
  }
  function handleHistoryKey(e) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return false;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return false;
    const value = _hgInput.value;
    const nav = _HG.histNav;
    const untouched = nav && value === nav.recalled;
    if (e.key === 'ArrowUp') {
      if (value !== '' && !untouched) return false;
      const history = untouched ? nav.history : _hgHistRead(_HG.sid || 'draft');
      if (!history.length) return false;
      e.preventDefault();
      if (untouched && nav.index === 0) return true;
      const idx = untouched ? nav.index - 1 : history.length - 1;
      const draft = untouched ? nav.draft : value;
      _HG.histNav = { history, index: idx, draft, recalled: history[idx] };
      _hgInput.value = history[idx];
      _hgInput.style.height = 'auto'; _hgInput.style.height = Math.min(_hgInput.scrollHeight, 200) + 'px';
      renderOverlay(_hgInput.value);
      requestAnimationFrame(() => _hgInput.setSelectionRange(_hgInput.value.length, _hgInput.value.length));
      return true;
    }
    if (!untouched) return false;
    e.preventDefault();
    if (nav.index >= nav.history.length - 1) {
      _hgInput.value = nav.draft; _HG.histNav = null;
      renderOverlay(_hgInput.value);
    } else {
      _HG.histNav = { history: nav.history, index: nav.index + 1, draft: nav.draft, recalled: nav.history[nav.index + 1] };
      _hgInput.value = _HG.histNav.recalled;
      renderOverlay(_hgInput.value);
    }
    return true;
  }
