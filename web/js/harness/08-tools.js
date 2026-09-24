// harness tools.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function statusBadge(st) {
    // running 蓝 / completed 绿 / error 红 / denied 橙
    const map = { running: ['运行中', 'b-run'], completed: ['完成', 'b-done'],
                  error: ['出错', 'b-err'], denied: ['拒绝', 'b-deny'] };
    const [txt, cls] = map[st] || ['', ''];
    return `<span class="h-tbadge ${cls}">${txt}</span>`;
  }
  function deriveStatus(res) {
    if (!res) return 'running';
    // v2.15：字段名修正。这是 SDK 的 tool_result 块，用 snake_case `is_error`
    // （后端 claude_harness.py 读的也是 is_error，本机 jsonl 里 is_error 出现
    // 3415 次、isError 0 次）。旧写法读 res.isError 恒为 undefined，deriveStatus
    // 永远返回 'completed' —— 红色「出错」徽章、row 的 err class、错误输出自动
    // 展开三条路径全部不可达，工具报错在界面上一直显示为绿色「完成」。
    if (res.is_error || res.isError) {
      const c = String(res.content || '').toLowerCase().trim();
      return _H_DENIAL.some(m => c.includes(m)) ? 'denied' : 'error';
    }
    return 'completed';
  }
  function resultText(res) {
    const c = res && res.content;
    if (typeof c === 'string') return c;
    if (Array.isArray(c)) return c.filter(b => b && b.type === 'text').map(b => b.text).join('\n');
    try { return JSON.stringify(c); } catch(_) { return String(c || ''); }
  }
  function diffHtml(oldS, newS) {
    // v2.8：真 LCS 行 diff（此前"交集着色"把未变行整段吞掉，大编辑只剩
    // 一两行——用户实测「咋可能只改了这点」。现在未变行作为上下文暗显，
    // 折叠展示改动段全貌；改动段外超 3 行的未变区间折叠成「… N 行不变」）
    const ol = String(oldS || '').split('\n'), nl = String(newS || '').split('\n');
    const n = ol.length, m = nl.length;
    // v3.2R1(P1)：行号计数器与列模板前置（fallback 分支也要用——原实现行号
    // 声明在 fallback 之后，挪用会 TDZ；折叠未变区间也必须推进计数器，否则
    // 折叠段之后的行号整体偏小「折叠行数」）
    let lnOld = 0;
    let lnNew = 0;
    const ln = num => `<span class="d-ln">${num || ''}</span>`;
    // LCS 动态规划（O(n*m) 内存；Edit 的 old/new 一般几十行，可承受，
    // 超大输入（>4000 行）退回旧交集法防卡顿）
    if (n * m > 4000 * 4000) {
      let h = '';
      nl.forEach(l => {
        if (!ol.includes(l)) { lnNew++; h += `<div class="d-add">${ln(lnNew)}<span class="d-tx">+ ${esc(l)}</span></div>`; }
        else lnNew++;
      });
      ol.forEach(l => {
        if (!nl.includes(l)) { lnOld++; h += `<div class="d-del">${ln(lnOld)}<span class="d-tx">- ${esc(l)}</span></div>`; }
        else lnOld++;
      });
      return h || '<div class="d-info">(无文本差异)</div>';
    }
    const dp = Array.from({length: n + 1}, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--)
      for (let j = m - 1; j >= 0; j--)
        dp[i][j] = ol[i] === nl[j] ? dp[i+1][j+1] + 1 : Math.max(dp[i+1][j], dp[i][j+1]);
    // 回溯产出 op 序列：'=' 上下文 / '+' 增 / '-' 删
    const ops = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (ol[i] === nl[j]) { ops.push(['=', ol[i]]); i++; j++; }
      else if (dp[i+1][j] >= dp[i][j+1]) { ops.push(['-', ol[i]]); i++; }
      else { ops.push(['+', nl[j]]); j++; }
    }
    while (i < n) { ops.push(['-', ol[i++]]); }
    while (j < m) { ops.push(['+', nl[j++]]); }
    // 改动段外的长未变区间折叠（≤3 行直显，>3 行收成一行摘要）
    // v3.2：行号列（ZCode 截图1 编辑卡同款）——统一 diff 口径：+/= 显示新文件
    // 行号，- 显示旧文件行号（GitHub unified 惯例）；折叠段不 emit 行但
    // 计数器照推（v3.2R1 修复：否则折叠段之后行号整体偏小）
    let h = '';
    const CTX = 3;
    let k = 0;
    const mark = (op, line) => {
      if (op === '=') { lnOld++; lnNew++;
        h += `<div class="d-ctx">${ln(lnNew)}<span class="d-tx">${esc(line)}</span></div>`;
      } else if (op === '+') { lnNew++;
        h += `<div class="d-add">${ln(lnNew)}<span class="d-tx">+ ${esc(line)}</span></div>`;
      } else { lnOld++;
        h += `<div class="d-del">${ln(lnOld)}<span class="d-tx">- ${esc(line)}</span></div>`;
      }
    };
    while (k < ops.length) {
      // 当前位置往前/后各留 CTX 行上下文；中间的长等值段折叠
      if (ops[k][0] === '=') {
        // 量出这段等值长度
        let e = k;
        while (e < ops.length && ops[e][0] === '=') e++;
        const len = e - k;
        const prevIsChange = k > 0;                      // 前面是改动段 → 头部留 CTX
        const nextIsChange = e < ops.length;             // 后面是改动段 → 尾部留 CTX
        let from = k, to = e;
        if (prevIsChange && nextIsChange && len > CTX * 2) {
          for (let x = k; x < k + CTX; x++) mark('=', ops[x][1]);
          h += `<div class="d-info">… ${len - CTX * 2} 行不变 …</div>`;
          lnOld += len - CTX * 2; lnNew += len - CTX * 2;   // v3.2R1：折叠段计数器照推
          for (let x = e - CTX; x < e; x++) mark('=', ops[x][1]);
        } else if (prevIsChange && !nextIsChange && len > CTX) {
          for (let x = k; x < k + CTX; x++) mark('=', ops[x][1]);
          h += `<div class="d-info">… ${len - CTX} 行不变 …</div>`;
          lnOld += len - CTX; lnNew += len - CTX;
        } else if (!prevIsChange && nextIsChange && len > CTX) {
          h += `<div class="d-info">… ${len - CTX} 行不变 …</div>`;
          lnOld += len - CTX; lnNew += len - CTX;
          for (let x = e - CTX; x < e; x++) mark('=', ops[x][1]);
        } else {
          for (let x = k; x < e; x++) mark('=', ops[x][1]);
        }
        k = e;
      } else { mark(ops[k][0], ops[k][1]); k++; }
    }
    return h || '<div class="d-info">(无文本差异)</div>';
  }
  function todoHtml(todos) {
    const ICO = { completed: '✅', in_progress: '🔄', pending: '⬜' };
    return (todos || []).map(t =>
      `<div class="t-item"><span>${ICO[t.status] || '⬜'}</span><span>${esc(t.activeForm || t.content || t.subject || '')}</span></div>`).join('');
  }
  function _tlOneclickify(row) {
    // v3.2：one-line 工具行（Bash 等）升级为可展开卡——加 col+oneclick 类，
    // 行首插 chevron；整行点击由 flow 委托（.h-tool.oneclick 分支）切换 open
    if (!row || row.classList.contains('oneclick') || row.querySelector(':scope > .h-tool-head')) return;
    row.classList.add('col', 'oneclick');
    row.insertAdjacentHTML('afterbegin', '<span class="h-chev h-tool-chev">▸</span>');
  }
  function closeRun() { _HG.run = null; }
  // ==================== v3.2：ZCode 式「查阅」聚组（exploreToolCall.ts 移植）====================
  // Read/Glob/Grep/WebSearch/WebFetch + 只读 Bash（rg/ls/cat/git status…）聚成
  // 一个折叠组「🔍 查阅 · N 搜索 · M 文件」，展开=左竖线+子行树；写类工具/
  // 思考/正文出现即断组（flush）。
  // v3.2R1(P1 审计)：写能力排除补全——`find -delete`、输出重定向（>/>>/2>/&>）、
  // 解释器执行（python -c/node -e 等）、PS 写 cmdlet（对照 ZCode
  // SHELL_REDIRECT_WRITE_RE/EXECUTE_WRITE_COMMAND_RE 全集）；只读判定补 PS
  // 读 cmdlet 与复合命令中的 git 只读（`cd x && git status`——^git 锚不到）
  const _HG_EXP_READ_RE =
    /\b(rg|grep|find|ls|cat|head|tail|wc|stat|pwd|which|readlink|tree|sed\s+-n|dir|type|select-string|get-content|get-childitem|get-location|get-item|gc|gci|sls)\b|(^|[;&]\s*)git\s+(status|log|show|diff)\b/i;
  const _HG_EXP_WRITE_RE =
    /\b(sed\s+-i|tee|mv|cp|rm|mkdir|touch|chmod|del|erase|out-file|move-item|copy-item|remove-item|set-content|add-content|clear-content|new-item|rename-item)\b|(^|[;&]\s*)git\s+(add|commit|rm|mv|checkout|switch|restore|reset|clean|revert|cherry-pick|merge|rebase)\b|\s-delete\b|(^|\s|;|&|\|)\s*(?:&?>|2?>|>{1,2})\s*\S|\b(python|py|node|perl|ruby|awk)\s+(-c|-e)\b/i;
  // v3.2R2 审计存档：重定向子句对引号内含 ">" 的搜索词（如 rg "a > b"）会
  // 误排除出聚组——保守方向（断组为普通行，绝不把写命令聚进查阅组），
  // 两态不一致可接受；后续如需精确化，把 ">" 前缀限定为左值非引号包裹
  function _hgIsExplore(name, input) {
    const n = name || '';
    if (['Read', 'Glob', 'Grep', 'WebSearch', 'WebFetch', 'TodoRead', 'LS'].includes(n)) return true;
    if (n !== 'Bash' && n !== 'PowerShell') return false;
    const cmd = String((input || {}).command || (input || {}).cmd || '');
    if (!cmd.trim()) return false;
    if (_HG_EXP_WRITE_RE.test(cmd)) return false;
    return _HG_EXP_READ_RE.test(cmd);
  }
  // 桶分类（对照 ZCode explore bucket：search/list/file——汇总文案「N 搜索 · M 文件」）
  function _hgExpBucket(name, input) {
    const n = name || '';
    if (n === 'Grep' || n === 'WebSearch') return 'search';
    if (n === 'Glob' || n === 'LS') return 'list';
    if (n === 'Read' || n === 'WebFetch' || n === 'TodoRead') return 'file';
    const cmd = String((input || {}).command || (input || {}).cmd || '').toLowerCase();
    if (/(^|\s)(rg|grep|ripgrep|git\s+grep)(\s|$)/.test(cmd)) return 'search';
    if (/(^|\s)(ls|find|tree|dir)(\s|$)/.test(cmd)) return 'list';
    return 'file';
  }
  // 组头副文案：完成态桶汇总；运行态追加最新子行动（「读取 xx.js」——对照
  // ZCode 运行中 collapsedChildSummary 的活字效果）
  function _hgExpLiveTxt(name, input) {
    const n = name || '';
    if (n === 'Read') {
      const f = String((input || {}).file_path || '').split(/[\\/]/).pop();
      return f ? '读取 ' + f : '读取文件';
    }
    if (n === 'Grep') return '搜索 ' + String((input || {}).pattern || '').slice(0, 30);
    if (n === 'Glob') return '匹配 ' + String((input || {}).pattern || '').slice(0, 30);
    if (n === 'WebSearch') return '网搜 ' + String((input || {}).query || '').slice(0, 30);
    if (n === 'WebFetch') return '抓取 ' + String((input || {}).url || '').slice(0, 30);
    if (n === 'Bash' || n === 'PowerShell')
      return String((input || {}).command || '').trim().slice(0, 40);
    return '';
  }
  function _tlExpFlush(histMode) {
    const g = _HG.grp;
    if (!g || !g.exp) return;
    const e = g.exp;
    g.exp = null;
    // 定稿：头部定格为桶汇总（去掉运行态活字），未被动过则自动收起
    if (!e.el.isConnected) return;
    const sumEl = e.el.querySelector('.h-tl-grp-sum');
    if (sumEl) sumEl.textContent = _hgExpSumTxt(e.sum);
    // v3.2.1（用户实测问题2）：回放定稿必收——重建期 scrollTop 在顶，
    // isNearBottom() 恒 false → 查阅组在回滚/切回后永远开着；histMode 由
    // 调用方传（grpFinalize 用 _hist 事实分级——尾组定稿发生在 openState
    // 清空之后，只看 openState 会丢回放语义）；live 保持 v2.12 底部跟读判据
    if (e.el.dataset.userToggled !== '1' && (histMode || isNearBottom())) e.el.classList.remove('open');
  }
  function _hgExpSumTxt(sum) {
    const parts = [];
    if (sum.search) parts.push(sum.search + ' 搜索');
    if (sum.list) parts.push(sum.list + ' 列表');
    if (sum.file) parts.push(sum.file + ' 文件');
    return '· ' + (parts.join(' · ') || '0 项');
  }
  // 时间线落位：explore 类 → 当前查阅组（无则建）；其余 → 先断组再挂时间线。
  // renderToolUse 与 renderHistTool（回放）同走本函数——live/回放聚组一致
  function _tlPlace(row, name, input) {
    const g = grpEnsure(true);
    if (!g.tl) { _tlExpFlush(!!_HG.openState); drawerAppend(row, 'exec'); return; }   // 旧快照组：回落旧抽屉
    if (_hgIsExplore(name, input)) {
      if (!g.exp || !g.exp.el.isConnected) {
        const grpEl = document.createElement('div');
        grpEl.className = 'h-tl-grp open';
        grpEl.innerHTML =
          `<button class="h-tl-grp-head"><span class="h-chev">▸</span>` +
          `<span class="h-tl-grp-name">🔍 查阅</span>` +
          `<span class="h-tl-grp-sum"></span></button>` +
          `<div class="h-tl-grp-body"></div>`;
        g.tl.appendChild(grpEl);
        // v3.2.1（用户实测问题2）：撤位置键开合恢复——_hgPathKey 按 DOM 位置
        // 索引链编键，跨 DOM 代际（v3.1 抽屉↔v3.2 时间线、回滚截断、扩段窗移）
        // 同键指向不同行，旧记录误开新行还误标 userToggled（用户实锤「终端默
        // 认全部不收起」）。查阅组与终端卡统一默认收起，点击开合只在当前
        // DOM 生命周期内有效（用户定调：必须默认都是收起状态）
        g.exp = { el: grpEl, sum: { search: 0, list: 0, file: 0 } };
      }
      const body = g.exp.el.querySelector('.h-tl-grp-body');
      if (body) body.appendChild(row);
      g.exp.sum[_hgExpBucket(name, input)]++;
      const sumEl = g.exp.el.querySelector('.h-tl-grp-sum');
      if (sumEl) {
        const live = _hgExpLiveTxt(name, input);
        sumEl.textContent = live ? '· ' + live : _hgExpSumTxt(g.exp.sum);
      }
    } else {
      _tlExpFlush(!!_HG.openState);   // v3.2.1：回放态断组必收
      g.tl.appendChild(row);
    }
    _hgScrollBottom();
  }
  function toolRunPush(name, row) {
    const r = _HG.run;
    if (r && r.name === name) {
      r.rows.push(row);
      row._grouped = true; row._groupHead = r.head;
      const named = r.rows.slice(0, 2).map(x => x._preview).filter(Boolean);
      const extra = r.rows.length - named.length;   // 按实际拼出条数计（源 buildGroupPreview）
      const arg = r.head.querySelector('.h-tool-arg');
      if (arg) arg.textContent = `×${r.rows.length}  ${named.join(', ')}${extra > 0 ? `, +${extra} more` : ''}`;
      return true;   // 已并入组，不单独显示
    }
    _HG.run = { name, head: row, rows: [row] };
    return false;
  }
  function renderToolUse(b, isSub, subId) {
    const name = b.name || '';
    const id = b.id || ('anon' + (++_HG.uidN));
    const cfg = _hCfg(name);
    const label = _hToolLabel(name);
    if (cfg.mode === 'hidden') return;
    // v2.57R：后端同序原始摘要（command→file_path→path→pattern→query→…，与
    // _subFeed 提取式一致）——窗格工具指纹查重的镜像侧数据源（row._preview
    // 是前端 cfg 格式化值，与回放侧原始字段系统性不相等，不能做指纹）
    const _rinp = b.input || {};
    const _rawHint = String(_rinp.command || _rinp.file_path || _rinp.path ||
                            _rinp.pattern || _rinp.query || _rinp.description ||
                            _rinp.subject || _rinp.prompt || '');

    // 注意：这里不 closeRun——run 的边界是文本/thinking/用户消息/result；
    // tool_use 本身若是同名工具正是 run 的延续，由 toolRunPush 判定并入组。
    let row;
    if (isSub) {
      // v2.44：段内工具行统一走抽屉工厂——one-line（Read/Grep 无展开体）与
      // collapsible（Bash 展开带全文）两形态在段内割裂，用户定调全部折叠统一
      row = _subToolDrawerRow(cfg, name, label, b.input);
    } else if (cfg.mode === 'one-line') {
      row = document.createElement('div');
      row.className = 'h-tool';
      const sec = cfg.sec ? cfg.sec(b.input) : '';
      // v3.1：ZCode 式行内徽标（文件类型色块 + `+N -N` 增删计数）
      const badges = _hgToolBadges(name, b.input);
      row.innerHTML =
        `<span class="h-tool-name">${_hToolIco(name)} ${esc(label)}</span>` +
        badges +
        `<span class="h-tool-arg">${esc(cfg.get(b.input) || '')}</span>` +
        (sec ? `<span class="h-tool-sec">${esc(sec)}</span>` : '') +
        `<span class="h-tslots"></span>`;
      // Bash 类：命令可复制（源 action:'copy'；点击由 flow 委托处理，v2.12）
      if (cfg.kind === 'bash') {
        const cp = document.createElement('button');
        cp.className = 'h-tool-copy'; cp.textContent = '复制'; cp.title = '复制命令';
        row.appendChild(cp);
      }
    } else {
      // collapsible：折叠组（左边框按类别着色，源 CollapsibleDisplay）
      row = document.createElement('div');
      row.className = 'h-tool col' + (cfg.defaultOpen ? ' open' : '');
      row.style.setProperty('--h-accent', _H_KIND_COLOR[cfg.kind] || 'var(--border)');
      const title = typeof cfg.title === 'function' ? cfg.title(b.input) : (cfg.title || label);
      const v = cfg.get ? cfg.get(b.input) : '';
      // v3.1：折叠组头同挂徽标（Edit 族的 diff 计数在收起态也要可见）
      const badges = _hgToolBadges(name, b.input);
      row.innerHTML =
        `<button class="h-tool-head"><span class="h-chev">▸</span>` +
        `<span class="h-tool-name">${_hToolIco(name)} ${esc(title)}</span>` +
        badges +
        (cfg.badge ? `<span class="h-tool-badge">${esc(cfg.badge)}</span>` : '') +
        `<span class="h-tslots"></span></button><div class="h-tool-coll">${_toolInputBodyHtml(cfg, v)}</div>`;
    }
    row._preview = row._preview !== undefined ? row._preview
      : (cfg.mode === 'one-line' ? cfg.get(b.input) : (typeof cfg.title === 'function' ? cfg.title(b.input) : label)) || '';
    row._rawHint = _rawHint;   // v2.57R：后端同序原始摘要（窗格指纹查重用）
    row._name = name;
    row._cfg = cfg;
    row._id = id;
    row.dataset.tid = id;                 // 快照/段认回后重扫挂映射用
    // v2.43：子代理内部工具行归段——不入主链 rowById（主链 tool_result 不可能
    // 引用它们），进段内映射（_subToolResult 挂徽章用）；行级 hgSub 点击入口
    // 退役（段头是重开窗格的唯一入口，行内交互不再被劫持）
    if (isSub && subId) {
      ((_HG.subRows[subId]) || (_HG.subRows[subId] = {}))[id] = row;
    } else {
      _HG.rowById[id] = row;
    }
    // v2.21：子代理行运行秒表——子代理一跑几分钟，主流毫无动静，没有
    // 秒表就像卡死。完成时由 renderOneToolResult 清表。
    if (cfg.kind === 'agent' && !isSub) {
      const slot = row.querySelector('.h-tslots');
      const t0 = Date.now();
      row._agentTimer = setInterval(() => {
        if (slot) slot.innerHTML = statusBadge('running') +
          ' <span class="h-tsec">' + Math.round((Date.now() - t0) / 1000) + 's</span>';
      }, 1000);
    }
    // v2.43：组统计去混——子代理内部调用不进主链组头胶囊（用户实锤「子代理×1
    // Bash×21…」把子代理活动压成数字）。Agent 派发本身（!isSub 的 agent 卡）
    // 仍计数——它是主会话的动作。
    if (!isSub) {
      drawerCount(name);                  // v2.7：计数进组（v3.2：折叠头副位「· N 工具」）
      // v2.8：抽屉时代不再合并同名 run——每条 Bash/Read/Grep 调用都是独立过程行
      // （用户明确要能看到每一次执行；组头徽章已承担"×N 汇总"职责）
      _HG.run = { name, head: row, rows: [row] };
      _tlPlace(row, name, b.input);       // v3.2：ZCode 式内联时间线（查阅聚组）
    } else {
      _subBlkAppendTool(subId, row);      // v2.43：子代理工具行入段体
    }
    // v2.32 面板：活动流记录（ring buffer 20 条；历史回放不记只看实时；
    // v2.43：主链专属——子代理内部调用不入主会话活动流）
    if (!_HG.openState && !isSub)
      _hgActPush({ tid: id, name, label, preview: row._preview || '', kind: cfg.kind, t0: Date.now() });
  }
  function renderToolResult(o) {
    const c = o.message && o.message.content;
    const blocks = Array.isArray(c) ? c : [];
    // v2.15：一条 user 消息可携带多个 tool_result（并行工具调用一次全回）。
    // 旧实现用 find() 只取首个 → 其余工具行永远停在「运行中」，结果与错误
    // 都不显示。后端 transcript_for 也是按 trs 全量遍历的，这里对齐。
    const trs = blocks.filter(b => b && b.type === 'tool_result');
    if (!trs.length) return;
    for (const tr of trs) renderOneToolResult(tr);
  }
  function renderOneToolResult(tr) {
    const row = _HG.rowById[tr.tool_use_id];
    if (!row) {
      // 无对应行（transcript 重建的孤立结果）→ 单行摘要（v2.7：也进抽屉）
      const txt = resultText(tr).slice(0, 120);
      const d = document.createElement('div');
      d.className = 'h-tool-res';
      d.textContent = txt ? '↳ ' + txt.replace(/\s+/g, ' ') : '↳ (完成)';
      _tlPlace(d, '_orphan', null);   // v3.2：孤立结果行同入时间线（非 explore → 直挂）
      return;
    }
    const cfg = row._cfg || {};
    const st = deriveStatus(tr);
    if (!_HG.openState) _hgActDone(tr.tool_use_id, st);   // v2.32 面板：活动流定格
    // v2.21：子代理秒表收表（历史重建/分组恢复无 timer，置空无妨）
    if (row._agentTimer) { clearInterval(row._agentTimer); row._agentTimer = null; }
    // 分组成员：结果状态聚合到组头（成功不刷组头徽章避免闪烁，错误标红）
    const showRow = row._grouped ? row._groupHead : row;
    const slots = showRow.querySelector('.h-tslots');
    if (slots && st !== 'completed') slots.innerHTML = statusBadge(st);
    else if (slots && !row._grouped) slots.innerHTML = statusBadge(st);
    // v2.21：子代理完成摘要——点开折叠体才见报告太隐身，徽章旁给
    // 报告首行 60 字（悬浮看前 400 字）；全文仍在折叠体
    if (cfg.kind === 'agent' && st === 'completed' && !row._grouped && slots) {
      const full = resultText(tr).replace(/\s+/g, ' ').trim();
      if (full) slots.innerHTML = statusBadge(st) +
        ` <span class="h-tagent-brief" title="${esc(full.slice(0, 400))}">${esc(full.slice(0, 60))}${full.length > 60 ? '…' : ''}</span>`;
    }
    showRow.classList.toggle('err', st === 'error' || st === 'denied');
    // v3.1：ZCode 式失败标记——行尾红色点状下划线小字（错误=执行失败/拒绝=已拒绝），
    // one-line 行无状态徽章可挂（成功不亮徽章防噪），失败必须显式可见
    if (st === 'error' || st === 'denied') {
      if (!showRow.querySelector('.h-tool-failmark'))
        showRow.insertAdjacentHTML('beforeend',
          `<span class="h-tool-failmark">${st === 'denied' ? '已拒绝' : '执行失败'}</span>`);
      // v3.2：查阅聚组内失败冒泡到组头（ZCode explore 父卡 showFailureStatus
      // 同款——组收起时错误仍可见，不藏在折叠树里）
      const eg = row.closest('.h-tl-grp');
      if (eg && !eg.classList.contains('err')) {
        eg.classList.add('err');
        const stEl = eg.querySelector('.h-tl-grp-sum');
        if (stEl) stEl.insertAdjacentHTML('afterend',
          `<span class="h-tool-failmark">${st === 'denied' ? '已拒绝' : '执行失败'}</span>`);
      }
    }
    // 结果折叠体（成功默认藏，错误永远显）
    const hideOk = cfg.result === 'hide' || cfg.kind === 'bash' || cfg.kind === 'diff';
    const txt = resultText(tr);
    if (row._grouped) {
      // 分组成员：状态已聚合到组头，输出不单独展示（组头 err 红底足够辨识）
      return;
    }
    if (st !== 'completed' && txt) {
      // 错误：展开显示（v3.2：one-line 行无头可点——升级为整行可点的终端卡形态）
      const body = row.querySelector('.h-tool-coll') || (() => {
        _tlOneclickify(row);
        const co = document.createElement('div'); co.className = 'h-tool-coll';
        row.appendChild(co);
        row.style.setProperty('--h-accent', 'var(--neon-red, #e06c75)');
        return co;
      })();
      row.classList.add('open');
      const pre = document.createElement('div');
      pre.className = 'h-tool-out err-txt';
      pre.textContent = txt.slice(0, 4000);
      body.appendChild(pre);
    } else if (!hideOk && txt && txt !== '(no content)') {
      // 成功但有内容（WebFetch/Grep 等配置允许展示）→ 收进折叠体（默认收起）
      const body = row.querySelector('.h-tool-coll');
      if (body) {
        const pre = document.createElement('div');
        pre.className = 'h-tool-out';
        const lines = txt.split('\n').length;
        pre.textContent = txt.length > 8000 ? txt.slice(0, 8000) + '…' : txt;
        body.appendChild(pre);
        if (cfg.kind === 'bash') {
          // 行数提示（源 BashCommandDisplay）
          row.querySelector('.h-tool-sec') || row.insertAdjacentHTML('beforeend', `<span class="h-tool-sec">${lines} 行输出</span>`);
        }
      }
    } else if (cfg.kind === 'bash' && txt) {
      // bash 成功输出：折叠体默认收起 + 行数提示（v3.2：one-line 行升级为
      // 整行可点展开——ZCode「终端 command ˅」卡片形态）
      const body = row.querySelector('.h-tool-coll') || (() => {
        _tlOneclickify(row);
        const co = document.createElement('div'); co.className = 'h-tool-coll';
        row.appendChild(co);
        return co;
      })();
      const pre = document.createElement('div');
      pre.className = 'h-tool-out';
      pre.textContent = txt.length > 8000 ? txt.slice(0, 8000) + '…' : txt;
      body.appendChild(pre);
      row.insertAdjacentHTML('beforeend', `<span class="h-tool-sec">${txt.split('\n').length} 行</span>`);
    }
    // tool_result 只挂状态不新增行——不终结 run（源 rendersNothing 不打断连续 run）
  }
