// harness groups.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function grpFromDom(root, thinkBox, execBox) {
    const g = {
      root,
      proc: root.querySelector('.h-grp-proc'),
      think: { box: thinkBox, body: thinkBox.querySelector('.h-drawer-body'),
               title: thinkBox.querySelector('.h-drawer-title'),
               stats: thinkBox.querySelector('[data-hg-dslots]') },
      exec: { box: execBox, body: execBox.querySelector('.h-drawer-body'),
              title: execBox.querySelector('.h-drawer-title'),
              stats: execBox.querySelector('[data-hg-dstats]'),
              slots: execBox.querySelector('[data-hg-dslots]') },
      ph: null, phTimer: null, phIdx: 0,
      counts: null,               // null = 未从 dataset 恢复
    };
    if (g.exec.stats) {
      try { g.counts = JSON.parse(g.exec.stats.dataset.counts || 'null'); } catch(_) { g.counts = null; }
    }
    // v2.20（2.png 空壳胶囊）：无内容的抽屉整体隐藏。新建组本来就 display:none
    // （见 grpEnsure），这里按 body 内容推导——快照恢复 inline style 会在、
    // 回扫接回走现场状态，但旧快照/边界路径没有标记，推导一劳永逸：
    // 空组什么都不显示（比「思考：无 / 执行：无」更干净）。
    const thKids = g.think.body ? g.think.body.children.length : 0;
    const exKids = g.exec.body ? g.exec.body.children.length : 0;
    const exCnt = g.counts && Object.keys(g.counts).length ? 1 : 0;
    thinkBox.style.display = thKids ? '' : 'none';
    execBox.style.display = (exKids || exCnt) ? '' : 'none';
    return g;
  }
  function grpEnsure(live) {
    let g = _HG.grp;
    if (g && g.root && g.root.isConnected) return g;
    // 快照恢复（切会话切回）后 _HG.grp 失联 → 扫 flow 最后一个组接回来。
    // 占位动画不重启：正文该到已到才走得到恢复路径。
    // v2.18.1：已定稿的组（dataset.finalized）不接回——正文切组刚定稿旧组，
    // 回扫必须放它过去，让下面新建组承接新回复。
    const root = _hgFlow.querySelector('.h-grp:last-of-type:not([data-finalized])');
    if (root) {
      const thinkBox = root.querySelector('.h-drawer.think');
      const execBox = root.querySelector('.h-drawer.exec');
      if (thinkBox && execBox) { _HG.grp = grpFromDom(root, thinkBox, execBox); return _HG.grp; }
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
    const execBox = document.createElement('div');
    execBox.className = 'h-drawer exec';
    execBox.innerHTML =
      `<button class="h-drawer-head"><span class="h-chev">▸</span>` +
      `<span class="h-drawer-title">💻 执行</span>` +
      `<span class="h-drawer-stats" data-hg-dstats></span>` +
      `<span class="h-tslots" data-hg-dslots></span></button>` +
      `<div class="h-drawer-body"></div>`;
    proc.appendChild(thinkBox);
    proc.appendChild(execBox);
    // v2.20（2.png 空壳胶囊）：新组抽屉先隐藏——纯文本回复的组（无思考无工具）
    // 不再渲染「🧠 思考 / 💻 执行」空壳胶囊+「完成」徽章；有内容时由
    // startThinking / drawerCount 翻回显示。
    thinkBox.style.display = 'none';
    execBox.style.display = 'none';
    nr.appendChild(proc);
    addRow(nr);
    g = grpFromDom(nr, thinkBox, execBox);
    g.counts = {};                 // 新组才清；恢复组从 dataset 读
    if (g.think.stats) g.think.stats.dataset.segCount = '0';
    // 重建期：按记录恢复开合；无记录则默认收起（流式期 openState=null 不干预）
    _hgApplyOpen(thinkBox, false);
    _hgApplyOpen(execBox, false);
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
    if (!thinkBox || !execBox) return;
    if (root.querySelector(':scope > .h-msg.asst:not(.ph)')) return;   // 正文已出，不占位
    const g = grpFromDom(root, thinkBox, execBox);
    _HG.grp = g;
    phStart(g);     // 冻结占位由 phStart 认领复用（不新建第二个）
  }
  function drawerCount(toolName) {
    const g = grpEnsure(true);                  // 计数进当前组执行抽屉
    g.exec.box.style.display = '';              // v2.20：第一个工具到位，执行抽屉翻回显示
    if (!g.counts) g.counts = {};
    const n = _hDrawerName(toolName);
    g.counts[n] = (g.counts[n] || 0) + 1;
    // chips ≤8 个，超出折叠成「…」——组头收起态必须小（用户：总体只占一小部分）
    const entries = Object.entries(g.counts);
    const shown = entries.slice(0, 8).map(([k, v]) => `<span class="h-drawer-chip">${esc(k)}×${v}</span>`).join('');
    g.exec.stats.innerHTML = shown + (entries.length > 8 ? '<span class="h-drawer-chip">…</span>' : '');
    g.exec.stats.dataset.counts = JSON.stringify(g.counts);   // 快照恢复用
    _hgScrollBottom();
  }
  function grpFinalize(auto) {
    const g = _HG.grp;
    if (!g) return;
    phRemove(g);
    // v2.20 修复：定稿把组头「思考 N 次」重写为纯文本——流式中带的脉动
    // 动画（hg-think-anim）此前无人摘，回复结束后还在闪。
    // 无思考段的组（空壳抽屉）不动，别把初始标题改写成「思考 0 次」。
    const _segN = thinkSegCount(g);
    if (g.think.title && _segN > 0)
      g.think.title.innerHTML = '🧠 思考 ' + _segN + ' 次';
    if (g.think.stats) g.think.stats.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    if (g.exec.slots) g.exec.slots.innerHTML = '<span class="h-tbadge b-done">完成</span>';
    // v2.21：纯思考/工具组（整组没有正文气泡）定稿时补一行弱提示——
    // 模型常连跑几十轮工具（text 全是 "\n\n" 占位被过滤），组头下面悬空
    // 看着像回复丢了（用户实测困惑点）。有正文/空壳组不补。
    // v2.43.1（R-次要①）：组内有子代理段也不补——段内气泡就是可见回复，
    // 再挂「无文字回复」自相矛盾。
    if (!g.root.querySelector(':scope > .h-msg.asst') && !g.root.querySelector(':scope > .h-grp-notext') &&
        !g.root.querySelector(':scope > .h-subblock') &&
        ((_segN > 0) || (g.counts && Object.keys(g.counts).length))) {
      const tip = document.createElement('div');
      tip.className = 'h-grp-notext';
      tip.textContent = '（本轮为思考/工具操作，无文字回复）';
      g.root.appendChild(tip);
    }
    // 用户手动开过不强制收；自动收只在用户在底部跟读时（v2.12 判据，按组生效）
    if (auto) {
      if (g.think.box.dataset.userToggled !== '1' && isNearBottom()) g.think.box.classList.remove('open');
      if (g.exec.box.dataset.userToggled !== '1' && isNearBottom()) g.exec.box.classList.remove('open');
    }
    g.root.dataset.finalized = '1';   // v2.18.1：已定稿——grpEnsure 回扫不得接回
    _HG.grp = null;      // 下轮 renderUser 开新组
  }
  function drawerAppend(el, kind) {
    const g = grpEnsure(true);
    (kind === 'think' ? g.think.body : g.exec.body).appendChild(el);
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
    grpFinalize(false);                       // v2.18：上一组定稿，本组接棒
    _maybeTimeBar(tsMs || Date.now());        // v2.24.5 微信式时间条（气泡前）
    endThinking(); closeRun();
    _HG.asstText = false;                     // 本轮 AI 尚未输出文本（占位/组头判据）
    const d = document.createElement('div');
    d.className = 'h-msg user';
    if (images?.length || files?.length) {
      const at = document.createElement('div');
      at.className = 'h-bubble-atts';
      at.innerHTML = attChipsHtml(images, files);   // 点击 Lightbox 由 flow 委托（v2.12）
      d.appendChild(at);
    }
    // v2.20：只发图不带文字 → mdBubble('') 是个空白气泡（用户嫌丑）；
    // 有附件且无文字时给一行占位文案，气泡不再空壳
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
    // v2.18.1（3.png）：组合制 = 思考+工具+回复，按正文切分。当前组已出过正文
    // → 后续正文属下一条回复：先定稿，让新组头（思考/工具）落在新正文上方。
    const cur = _HG.grp;
    if (_HG.asstText && cur && cur.root && cur.root.querySelector(':scope > .h-msg.asst')) {
      grpFinalize(true);
    }
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
    g.root.appendChild(d);
    _hgScrollBottom();
  }
