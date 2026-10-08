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
    // v3.4.81（用户实锤「SendMessage 失败挂完成徽标」）：SendMessage 发送失败
    // 的回执 is_error=false、content={"success":false,...}（Agent 不可恢复等）
    // ——按错误态标红，不再绿「完成」
    if (/^\s*\{\s*"success"\s*:\s*false/.test(resultText(res))) return 'error';
    return 'completed';
  }
  function resultText(res) {
    const c = res && res.content;
    if (typeof c === 'string') return c;
    if (Array.isArray(c)) return c.filter(b => b && b.type === 'text').map(b => b.text).join('\n');
    try { return JSON.stringify(c); } catch(_) { return String(c || ''); }
  }
  // v3.4.62（用户需求「diff 看不到真实改动行号」）：diffHtml 的行号列从 1
  // 相对计数（old/new_string 是子串，渲染时不知文件位置）——本函数在
  // tool_result（文件已写盘）后读改后文件定位 new_string 起始行，把行号列
  // 回填为真实文件行号。Edit=原位替换，旧/新起始同位，两侧同偏移严格成立；
  // MultiEdit 多处编辑行号非线性（join 后的 diff 行序与文件不映射），列不
  // 造假，只在卡头标「L<n> 起」定位首处。定位失败（该处后续又被改/文件
  // 不存在）静默保持相对行号。_dnews/_dfp 是内存属性（不随快照序列化）——
  // 快照恢复的 DOM 行号已真实无需重拉；回放/重建路径 input 在手重新存档
  // 走本函数。dataset.hgDln 幂等：主链/窗格镜像/回放配对多路触发只拉一次
  function _hgDiffLineFix(row) {
    if (!row || !row.isConnected || row.dataset.hgDln === '1') return;
    const news = row._dnews, fp = row._dfp;
    if (!news || !news.length || !fp) return;
    row.dataset.hgDln = '1';
    fetch('/api/harness/diff_lines', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sid: _HG.sid || '', path: fp, news })
    }).then(r => r.json()).then(j => {
      if (!j || !j.ok || !row.isConnected) return;   // 在途行被清场（切会话等）直接弃
      const ln0 = (j.lines || [])[0];
      if (!ln0) return;
      const head = row.querySelector('.h-tool-head');
      if (news.length > 1) {
        // MultiEdit：卡头定位 chip（各处行号非线性，diff 列保持相对不造假）
        if (head && !row.querySelector('.h-tool-sec.hg-dln-chip'))
          head.insertAdjacentHTML('beforeend',
            `<span class="h-tool-sec hg-dln-chip" title="首处改动位于文件第 ${ln0} 行（各处 diff 为改动内相对行号）">L${ln0} 起</span>`);
        return;
      }
      const diff = row.querySelector('.h-diff');
      if (!diff) return;
      const off = ln0 - 1;
      let nn = 0, on = 0;   // 新/旧行号族游标（与 diffHtml 生成规则同构）
      diff.querySelectorAll('.d-ctx,.d-add,.d-del,.d-info').forEach(d => {
        const lnel = d.querySelector('.d-ln');
        if (d.classList.contains('d-info')) {
          const m = (d.textContent || '').match(/(\d+) 行不变/);
          const n = m ? +m[1] : 0;
          nn += n; on += n;   // 折叠段计数器照推（同 diffHtml）
        } else if (d.classList.contains('d-del')) {
          on++;
          if (lnel) lnel.textContent = String(on + off);
        } else if (d.classList.contains('d-ctx')) {
          nn++; on++;   // 轻审P1：ctx 同属新旧两文件——双推进（与 diffHtml mark('=') 同构），否则后方 del 列偏小
          if (lnel) lnel.textContent = String(nn + off);
        } else {
          nn++;
          if (lnel) lnel.textContent = String(nn + off);
        }
      });
    }).catch(() => {});
  }
  // v3.4.62：diff 真实行号定位数据存档（Edit/MultiEdit 渲染点统一入口）——
  // 内存属性随行存活，结果到达点（renderOneToolResult/_fillRes/_subResult）
  // 触发 _hgDiffLineFix
  function _hgDiffLineMemo(row, name, input) {
    if (!row || !input) return;
    if (name !== 'Edit' && name !== 'MultiEdit') return;
    const _news = name === 'MultiEdit'
      ? (Array.isArray(input.edits) ? input.edits : []).map(e => e && e.new_string || '')
      : [input.new_string || ''];
    // 轻审P1 附带：>4000² 的 diff 走 diffHtml fallback 交集法（行号按原串
    // 位置编号、无 ctx 折叠），回填遍历与其产物不同构——不存档不回填。
    // 复核残留：MultiEdit 无 old_string 字段（恒 1 行），须用 edits 的 joined
    // old 对齐 diffHtml 的 n*m 判据（单编辑 MultiEdit 走全列回填才吃得着）
    const _ol = (name === 'MultiEdit'
      ? (Array.isArray(input.edits) ? input.edits : []).map(e => e && e.old_string || '').join('\n')
      : String(input.old_string || '')).split('\n').length;
    const _nl = _news.join('\n').split('\n').length;
    if (_ol * _nl > 4000 * 4000) return;
    row._dfp = String(input.file_path || '');
    row._dnews = _news;
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
  // v3.3.7（P5 自愈）：回合终结时空 input 的 bash 行从转写回填真实命令——
  // live 丢 input 是 CLI/网关流异常（转写恒完整），行存令失不再靠「重开会话
  // 自愈」。一次 fetch 修补当回合全部缺令行；行已不在（切会话/被 cap）静默跳过
  async function _hgPatchMissingCmds() {
    if (!_HG.noInputTids || !_HG.noInputTids.size || !_HG.sid) return;
    const tids = [..._HG.noInputTids];
    _HG.noInputTids = new Set();
    const sidAt = _HG.sid;
    try {
      const j = await (await fetch('/api/harness/transcript?sid=' + encodeURIComponent(sidAt))).json();
      if (!j || !j.ok || !Array.isArray(j.lines) || _HG.sid !== sidAt) return;
      const byId = {};
      for (const l of j.lines)
        if (l && l.role === 'tool' && (l.tid || l.id)) byId[l.tid || l.id] = l;   // v3.3.7R（轻审致命）：转写行 id 落 tid 键
      const miss = [];
      for (const tid of tids) {
        const row = _HG.rowById[tid];
        const ln = byId[tid];
        if (!row || !row.isConnected || !ln) { miss.push(tid); continue; }
        const cmd = String((ln.input || {}).command || (ln.input || {}).cmd || '');
        if (!cmd) continue;
        row._rin = ln.input || null;
        row._rawHint = cmd;
        // v3.3.7R（轻审一般）：空 arg span（input 丢时 renderToolUse 恒输出）原位填
        const arg = row.querySelector(':scope > .h-tool-arg');
        if (arg && !(arg.textContent || '').trim()) {
          arg.title = cmd;
          arg.textContent = cmd.slice(0, 80);
        } else if (!arg) {
          const narg = document.createElement('span');
          narg.className = 'h-tool-arg';
          narg.title = cmd;
          narg.textContent = cmd.slice(0, 80);
          const name = row.querySelector(':scope > .h-tool-name');
          if (name) name.insertAdjacentElement('afterend', narg);
          else row.insertBefore(narg, row.firstChild);
        }
        // 查阅组判定补账：只读命令（此前 input 空判定断组直挂的）不再追改分组
        //（行位不动，仅信息补全——挪行会造成时序跳动）
      }
      // v3.3.14R（轻审问题1）：miss 重试（CLI 刷盘延迟/网络抖动）——连续 miss
      // 才累计（成功批归零），上限 3 防循环；切会话时账随 _HG 清（12-sessions）
      if (miss.length) {
        _HG.noInputMiss = (_HG.noInputMiss || 0) + 1;
        const sidAt = _HG.sid;
        if (_HG.noInputMiss <= 3) setTimeout(() => {
          if (_HG.sid !== sidAt) return;   // v3.3.14R2（轻审可选加固）：跨切会话放弃重灌
          _HG.noInputTids = _HG.noInputTids || new Set();
          miss.forEach(t => _HG.noInputTids.add(t));
          _hgPatchMissingCmds();
        }, 5000);
      } else _HG.noInputMiss = 0;
    } catch(_) {}
  }
  function _tlOneclickify(row) {
    // v3.2：one-line 工具行（Bash 等）升级为可展开卡——加 col+oneclick 类，
    // 行首插 chevron；整行点击由 flow 委托（.h-tool.oneclick 分支）切换 open
    if (!row || row.classList.contains('oneclick') || row.querySelector(':scope > .h-tool-head')) return;
    row.classList.add('col', 'oneclick');
    row.insertAdjacentHTML('afterbegin', '<span class="h-chev h-tool-chev">▸</span>');
    // v3.3.14（用户实锤「历史记录 bash 的命令能显示，当前工作中的看不到」，
    // 推翻 v3.1h「只保留标志」）：头部命令摘要保留——live 卡与历史卡统一形态
    // （单行省略+title 全文，样式 .h-tool.oneclick > .h-tool-arg 已有）。
    // 空 arg（input 随流丢失）补记自愈账——_hgPatchMissingCmds 回合终结回填
    const _ocArg = row.querySelector(':scope > .h-tool-arg');
    const _tid = row.dataset.tid || '';
    // v3.3.14R（轻审问题2）：补记口径对齐 renderToolUse——仅 bash 且真 tid
    // （anon 匿名行转写永无此键，入账必 miss）
    if (_tid && _tid.indexOf('anon') !== 0 && row._cfg && row._cfg.kind === 'bash'
        && (!_ocArg || !(_ocArg.textContent || '').trim()))
      (_HG.noInputTids || (_HG.noInputTids = new Set())).add(_tid);
    // v3.3.3（用户实锤「bash 未对齐」）：终端卡必须与时间线同轴——行游离在
    // .h-tl 之外（任何路径的异常落位，卡在组根=凸出左缘一个缩进）时归位当前
    // 组时间线尾。.h-tl 内的行 closest 命中即原样不动
    if (!row.closest('.h-tl')) {
      try {
        const g = grpEnsure(true);
        if (g && g.tl && row.isConnected) g.tl.appendChild(row);
      } catch(_) {}
    }
  }
  function closeRun() { _HG.run = null; }
  // ==================== v3.2：ZCode 式「查阅」聚组（exploreToolCall.ts 移植）====================
  // Read/Glob/Grep/WebSearch/WebFetch + 只读 Bash（rg/ls/cat/git status…）+ MCP
  // 只读探索（codegraph_explore）聚成一个折叠组「🔍 查阅 · N 搜索 · M 文件」，
  // 展开=左竖线+子行树；写类工具/正文出现即断组（flush）。
  // v3.2.13（用户实锤「没修复好」）：思考行不再断组——同一回合里思考间隔
  // 前后的查阅继续并入同一组（对照 ZCode 组跨思考累积），同目标重复子行
  // （如两次 Read 同文件）折叠为一条，组头计数只计去重后条目。
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
  // v3.2.13：MCP 只读探索白名单——仅收无副作用的检索类（codegraph_explore）；
  // 识图/浏览器等其余 MCP 一律不聚组
  const _HG_EXP_MCP_RE = /(^|_)codegraph_explore$/;
  function _hgIsExplore(name, input) {
    const n = name || '';
    if (['Read', 'Glob', 'Grep', 'WebSearch', 'WebFetch', 'TodoRead', 'LS'].includes(n)) return true;
    if (_HG_EXP_MCP_RE.test(n)) return true;
    if (n !== 'Bash' && n !== 'PowerShell') return false;
    const cmd = String((input || {}).command || (input || {}).cmd || '');
    if (!cmd.trim()) return false;
    if (_HG_EXP_WRITE_RE.test(cmd)) return false;
    return _HG_EXP_READ_RE.test(cmd);
  }
  // 桶分类（对照 ZCode explore bucket：search/list/file——汇总文案「N 搜索 · M 文件」）
  function _hgExpBucket(name, input) {
    const n = name || '';
    if (n === 'Grep' || n === 'WebSearch' || _HG_EXP_MCP_RE.test(n)) return 'search';
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
    if (_HG_EXP_MCP_RE.test(n))
      return '探索 ' + String((input || {}).query || (input || {}).prompt || '').slice(0, 30);
    if (n === 'Bash' || n === 'PowerShell')
      return String((input || {}).command || '').trim().slice(0, 40);
    return '';
  }
  // v3.2.13：同目标去重键——同组内 (工具+目标) 重复的子行折叠为一条
  // （读取同文件×2 / 同 pattern 搜索×2；跨组不比——写类断组后属新语境）
  function _hgExpKey(name, input) {
    const n = name || '';
    const i = input || {};
    if (n === 'Read') return 'R:' + String(i.file_path || '');
    if (n === 'Grep') return 'G:' + String(i.pattern || '');
    if (n === 'Glob') return 'O:' + String(i.pattern || '');
    if (n === 'WebSearch') return 'S:' + String(i.query || '');
    if (n === 'WebFetch') return 'F:' + String(i.url || '');
    if (_HG_EXP_MCP_RE.test(n)) return 'E:' + String(i.query || i.prompt || '');
    if (n === 'Bash' || n === 'PowerShell') return 'C:' + String(i.command || i.cmd || '');
    return '';
  }
  function _tlExpFlush(histMode) {
    const g = _HG.grp;
    if (!g || !g.exp) return;
    const e = g.exp;
    g.exp = null;
    // 定稿：头部定格为桶汇总（去掉运行态活字），未被动过则自动收起
    // v3.2.13：histBuilding——原子渲染期组在游离缓冲内 isConnected 恒
    // false，原早退会让定稿头部永远停在运行态活字；缓冲期内照常定格
    if (!e.el.isConnected && !_HG.histBuilding) return;
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
    phRemove(g);   // v3.2.29（用户定调）：工作区一有内容占位气泡即退场——
                   // 「AI 正在思考中…」只许出现在空工作区，状态交左下角活动条
    if (!g.tl) { _tlExpFlush(!!_HG.openState); drawerAppend(row, 'exec'); return; }   // 旧快照组：回落旧抽屉
    if (_hgIsExplore(name, input)) {
      if (!g.exp || (!g.exp.el.isConnected && !_HG.histBuilding)) {   // v3.2.13：缓冲期视缓冲内组为在场（grpEnsure 同判）
        const grpEl = document.createElement('div');
        grpEl.className = 'h-tl-grp';   // v3.2.19（用户定调「执行过程中默认不展开」）：生而收起——运行态活字照上组头，点击展开
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
        g.exp = { el: grpEl, sum: { search: 0, list: 0, file: 0 }, keys: {} };
      }
      // v3.2.13：同目标重复子行折叠为一条（两次读同文件/同 pattern 搜索）——
      // 不重复入 DOM、组头计数不重复计
      const _ek = _hgExpKey(name, input);
      if (_ek && g.exp.keys[_ek]) return;
      if (_ek) g.exp.keys[_ek] = 1;
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
      // v3.4.90（用户实锤「识图过程没显示」）：空组的 tl 是内联 display:none
      //（grpFromDom 对 children=0 落的）——首行入列必须翻显，否则识图卡/
      // 工具行困在隐藏容器（_sysRowIntoGroup v3.4.80 同修法的上游收口）
      if (g.tl.style.display === 'none') g.tl.style.display = '';
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
  // v3.2.6（ZCode 子智能体模式）：主流 Agent/Task 派发行 = 单行任务卡——
  // 对照 ZCode agent.tsx 产品边界「父对话只保留单行摘要，完整 child timeline
  // 统一从右侧 tab 查看」：✦ + 「子智能体」类别词 + 类型高亮 chip + 描述 +
  // （运行中）最新子活动流 + 状态徽章/秒表 + ▣ 打开窗格。展开体恒空——
  // 过程细节一律进窗格时间线（14-subpane），本行不再折叠展开
  function _hgAgentRowBuild(tid, type, desc) {
    const row = document.createElement('div');
    row.className = 'h-tool col agentline';
    row.dataset.tid = tid;
    // v3.2.6R2（用户实锤「点了说无 agentId」）：类型/描述随行预置——agentId
    // 后到（task_started/sub_open/agentsRpl 三路任一）时凭这对键回绑/回查
    row.dataset.hgSubType = String(type || '').trim() || 'Agent';
    row.dataset.hgSubDesc = String(desc || '').slice(0, 120);
    row.style.setProperty('--h-accent', _H_KIND_COLOR.agent || 'var(--border)');
    const ty = String(type || '').trim() || 'Agent';
    // v3.3.12（用户实锤「蓝色长条」）：chip 显示中文短名（_AGENT_LABEL）而非
    // 原始 type 串——general-purpose 这类长英文名小字号渲成一坨蓝条
    const tyDisp = _AGENT_LABEL[ty] || ty;
    const dsc = String(desc || '').trim();
    row.innerHTML =
      `<button class="h-tool-head"><span class="h-tool-name">${_hToolIco('Task')} 子智能体</span>` +
      `<span class="h-ag-type ${_hgAvaCls(ty)}" title="${esc(ty)}">${esc(tyDisp)}</span>` +
      `<span class="h-tool-arg"${dsc ? ` title="${esc(dsc)}"` : ''}>${esc(dsc)}</span>` +
      `<span class="h-ag-live"></span>` +
      `<span class="h-tslots"></span></button>` +
      `<div class="h-tool-coll"></div>`;
    return row;
  }
  // v3.2.6：行内实时活动流——子代理 think/text/tool 事件到达即刷新（05-subblk
  // 三钩调用；ZCode animateSummaryContent 的静态等价物：最新子动作单行摘要）
  function _subLivePaint(pid, txt) {
    const row = (_HG.rowById || {})[pid];
    const lv = row && row.classList.contains('agentline')
      ? row.querySelector('.h-ag-live') : null;
    if (lv) lv.textContent = String(txt || '').trim().slice(0, 90);
  }
  // v3.2.31（bug5① 根因修复）：完成摘要与派发描述同文去重——CLI 的
  // task_notification.summary / Task tool_result 常原样复述 input.description
  //（子代理最终报告=任务描述），单行卡渲染成「描述 …完成 描述」两遍。判定：
  // 归一空白后相等或互为前缀即视为同文，摘要位让位（描述已在场，信息零丢失）。
  // v3.2.31R（复审6）：入参改显式两串（desc, brief），主行卡两落点与目录行
  //（14-subpane _subDirRowHtml）共用，不再各持一份实现
  function _hgBriefDupDesc(desc, brief) {
    const ds = String(desc || '').replace(/\s+/g, ' ').trim();
    const bs = String(brief || '').replace(/\s+/g, ' ').trim();
    if (!bs || !ds) return false;
    return bs === ds || ds.indexOf(bs) === 0 || bs.indexOf(ds) === 0;
  }
  // v3.2.6：单行任务卡定格（task_notification 路径——tool_result 丢失时的
  // 状态收口；与 renderOneToolResult 正常路径幂等互备）
  function _hgAgentRowState(tid, err, brief) {
    const row = (_HG.rowById || {})[tid];
    if (!row || !row.classList.contains('agentline')) return;
    const lv = row.querySelector('.h-ag-live');
    if (lv) lv.textContent = '';
    const st = row.querySelector('.h-tslots');
    if (st) {
      if (err) st.innerHTML = statusBadge('error');
      else {
        const b = String(brief || '').trim();
        st.innerHTML = statusBadge('completed') + (b && !_hgBriefDupDesc(row.dataset.hgSubDesc, b)
          ? ` <span class="h-tagent-brief" title="${esc(b.slice(0, 400))}">${esc(b.slice(0, 60))}${b.length > 60 ? '…' : ''}</span>` : '');
      }
    }
    row.classList.toggle('err', !!err);
    // v3.2.6R（审计F1）：agentId 回写行——切会话往返后 agents 档案已清，行
    // 自带的 hgSubr 是回放入口的唯一数据锚（v3.2.5 段头 ▣ 回放的同款语义）
    _hgAgentRowBindAid(tid, row);
  }
  // v3.2.6R（审计F1）：从 agents 档案把 agentId/类型/描述落到单行卡
  // （renderOneToolResult 与 _hgAgentRowState 两路共用的幂等回写）
  function _hgAgentRowBindAid(tid, row) {
    if (!row || row.dataset.hgSubr) return;
    const a = (_HG.agents || {})[tid] || {};
    const aid = a.taskId || a.agentId || '';
    if (!aid || !/^[0-9a-zA-Z_-]{8,64}$/.test(aid)) return;
    row.dataset.hgSubr = aid;
    row.dataset.hgSubType = a.type || 'Task';
    row.dataset.hgSubDesc = String(a.desc || '').slice(0, 120);
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
    } else if (cfg.kind === 'agent') {
      // v3.2.6：Agent/Task 派发走单行任务卡工厂（无展开体——过程进窗格）
      row = _hgAgentRowBuild(id, _rinp.subagent_type || _rinp.agent_type || name,
        _rinp.description || '');
      // v3.2.30（用户实锤「运行中的代理看不到发给它的消息」）：派发 prompt
      // 入 live 来向队列——窗格已开立即插、未开等 _subOpen/task_started 冲
      // （回放侧 v3.2.21 已有 user 行，回放插行处带同文去重）
      _subUserQueue(id, _rinp.prompt || _rinp.description || '');
    } else if (cfg.mode === 'one-line') {
      row = document.createElement('div');
      row.className = 'h-tool';
      const sec = cfg.sec ? cfg.sec(b.input) : '';
      // v3.1：ZCode 式行内徽标（文件类型色块 + `+N -N` 增删计数）
      const badges = _hgToolBadges(name, b.input);
      const argTxt = esc(cfg.get(b.input) || '');
      row.innerHTML =
        `<span class="h-tool-name">${_hToolIco(name)} ${esc(label)}</span>` +
        badges +
        // v3.2.5R：bash 命令带 title 全文悬浮（对齐回放卡 argTitle 口径——
        // 单行省略后窄面板/长命令的唯一全文入口）
        `<span class="h-tool-arg"${cfg.kind === 'bash' && argTxt ? ` title="${argTxt}"` : ''}>${argTxt}</span>` +
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
      _hgDiffLineMemo(row, name, b.input);   // v3.4.62：diff 真实行号定位存档（结果到达后触发）
    }
    row._preview = row._preview !== undefined ? row._preview
      : (cfg.mode === 'one-line' ? cfg.get(b.input) : (typeof cfg.title === 'function' ? cfg.title(b.input) : label)) || '';
    row._rawHint = _rawHint;   // v2.57R：后端同序原始摘要（窗格指纹查重用）
    row._rin = b.input || null;   // v3.2.6R2（审计N2）：原始 input 随行——窗格镜像的 explore 聚组判定（Bash 只读命令靠 input.command）
    row._name = name;
    // v3.3.7（P5 自愈）：live 事件偶发丢 tool_use input（CLI/网关流异常，实测
    // 多命令/heredoc 聚集）——记号入账，回合一结束 _hgPatchMissingCmds 从
    // 转写回填真命令（转写恒完整：jsonl 落盘前 CLI 已组装完 input）
    if (!isSub && cfg.kind === 'bash' && !Object.keys(_rinp).length && b.id)
      (_HG.noInputTids || (_HG.noInputTids = new Set())).add(b.id);
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
        // 行已游离（切会话清场/回退重建后迟到的 tool_result 走 orphan 分支
        // 永远清不到表）——首行自杀，防 interval+DOM 子树无界累积
        if (!row.isConnected) { clearInterval(row._agentTimer); row._agentTimer = null; return; }
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
      // v3.2.31（bug5①）：摘要复述描述时不重复渲染（_hgBriefDupDesc 同口径）
      if (full && !_hgBriefDupDesc(row.dataset.hgSubDesc, full))
        slots.innerHTML = statusBadge(st) +
        ` <span class="h-tagent-brief" title="${esc(full.slice(0, 400))}">${esc(full.slice(0, 60))}${full.length > 60 ? '…' : ''}</span>`;
    }
    // v3.2.6：agentline 单行卡完成即撤实时活动流（状态/摘要接管行尾语义）
    if (cfg.kind === 'agent') {
      const lv = row.querySelector('.h-ag-live');
      if (lv) lv.textContent = '';
      _hgAgentRowBindAid(tr.tool_use_id, row);   // v3.2.6R（审计F1）：agentId 回写
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
    if (cfg.kind === 'diff' && st === 'completed') _hgDiffLineFix(row);   // v3.4.62：成功改盘才定位（轻审P2：失败 Edit 文件未写，误配出假行号）
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
      // v3.2.5（用户定调）：错误不自动展开——标红（err 类+行尾「执行失败」
      // failmark）即可，正文收进折叠体点开再看
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

// ==================== v3.5.22：后台任务卡（Task 与子代理区分可视化）====================
// 用户需求：task create/done/取消 等后台任务生命周期独立可见，不与子代理混淆。
// 数据面档案 _HG.tasks（与 _HG.agents 彻底分离——后台 shell 无转写无实况，
// 进子代理体系必「未找到转写」）；消息流形态=任务行卡（⧗ 后台任务·desc·状态
// 徽章·秒表），入当前组时间线与工具行同语言但视觉独立（样式/图标/徽章色）。
// 状态机：运行中 → 已完成/已失败（task_notification，is_err）；已中断（exit
// sweep）；主回合 interrupted 不动它（后台任务跨回合存活，v2.35 哲学）。
// 历史侧：CLI 不把 task_* 生命周期落转写（本会话实证），任务卡不回放——
// 后台 Bash 的工具行历史形态照旧。
function _taskCardBuild(tid, desc) {
  const card = document.createElement('div');
  card.className = 'h-tool h-taskcard';
  card.dataset.tid = tid;
  const sum = String(desc || '').replace(/\s+/g, ' ').trim().slice(0, 90);
  card.innerHTML =
    '<span class="h-task-ico">⧗</span>' +
    '<span class="h-task-name">后台任务' + (sum ? ' · ' + esc(sum) : '') + '</span>' +
    '<span class="h-task-state"></span>' +
    '<b class="h-task-t">0s</b>';
  _taskCardPaint(card, 'run');
  return card;
}
function _taskCardPaint(card, state, durTxt) {
  if (!card) return;
  const st = card.querySelector('.h-task-state');
  const tb = card.querySelector('.h-task-t');
  if (tb) tb.style.display = (state === 'run') ? '' : 'none';
  const m = {
    run: '<span class="h-tbadge b-run">运行中</span>',
    done: '<span class="h-tbadge b-done">已完成' + (durTxt ? ' · 用时 ' + esc(durTxt) : '') + '</span>',
    err: '<span class="h-tbadge b-err">已失败' + (durTxt ? ' · 用时 ' + esc(durTxt) : '') + '</span>',
    stop: '<span class="h-tbadge b-warn">已中断</span>'
  };
  if (st) st.innerHTML = m[state] || '';
}
function _taskCardTick(card) {
  if (!card || card._taskTimer) return card._taskTimer;
  const tb = card.querySelector('.h-task-t');
  const t0 = +(card.dataset.t0 || 0) || Date.now();
  card._taskTimer = setInterval(() => {
    if (!tb.isConnected) { clearInterval(card._taskTimer); card._taskTimer = null; return; }
    tb.textContent = _hgFmtDur((Date.now() - t0) / 1000);
  }, 1000);
  return card._taskTimer;
}
function _taskStop(card) {
  if (card && card._taskTimer) { clearInterval(card._taskTimer); card._taskTimer = null; }
}
// task_started（后台 shell 判定命中）：建档+建卡（消息流与目录数据源）
function _taskStart(tid, desc) {
  if (!tid) return null;
  const t = (_HG.tasks || (_HG.tasks = {}))[tid] || {
    desc: String(desc || ''), t0: Date.now(), done: false, doneAt: 0,
    err: false, cancelled: false };
  _HG.tasks[tid] = t;
  t.done = false;
  const card = _taskCardBuild(tid, desc);
  card.dataset.t0 = String(t.t0);
  t.el = card;
  drawerAppend(card);
  _taskCardTick(card);
  _subDirPaint && _HG.active === '__dir__' && _subDirPaint();   // 目录开着即时刷
  return card;
}
// task_notification / exit sweep：定格（state: done/err/stop）
function _taskFinish(tid, state, summary) {
  const t = (_HG.tasks || {})[tid];
  const card = t && t.el;
  if (t) {
    t.done = true; t.doneAt = Date.now();
    t.err = (state === 'err'); t.cancelled = (state === 'stop');
    t.result = String(summary || '').slice(0, 400);
  }
  if (card) {
    _taskStop(card);
    if (summary) card.title = String(summary).slice(0, 2000);   // 悬浮全文（轻量：无展开体）
    // 用户实锤「时间不对」：_hgFmtDur 入参是秒——差值毫秒须 /1000（旧码
    // 把 11682ms 当 11682s 渲染成 3h14m42s）
    const dur = _hgFmtDur((((t && t.doneAt) || Date.now())
      - (+(card.dataset.t0 || 0) || Date.now())) / 1000) || '';
    _taskCardPaint(card, state, dur);
  }
  _subDirPaint && _HG.active === '__dir__' && _subDirPaint();
}
