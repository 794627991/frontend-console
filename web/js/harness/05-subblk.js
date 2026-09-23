// harness subblk.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function _subBlkInfoLive(pid) {
    const a = (_HG.agents || {})[pid] || {};
    // v2.47（需求2）：collab 段头带「协作 ·」前缀（与真实子代理段视觉区分
    // ——独立会话，过程靠转写轮询/回放而非实况流）
    return { live: true, collab: !!a.collab,
             label: a.collab ? '协作 · ' + (_AGENT_LABEL[a.type] || a.type || '代理')
                             : (_AGENT_LABEL[a.type] || a.type || '子代理'),
             model: a.model || '', type: a.type, desc: a.desc || '',
             done: !!a.done, err: !!a.err, bg: !!a.bg };
  }
  function _subBlkAdopt(pid) {
    if (!pid) return null;
    let b = _HG.subBlk && _HG.subBlk[pid];
    if (b && b.root && b.root.isConnected) return b;
    const exist = _hgFlow.querySelector('.h-subblock[data-hg-subblock="' + CSS.escape(pid) + '"]');
    if (!exist) return null;
    b = _HG.subBlk[pid] = { root: exist,
      head: exist.querySelector('.h-subblock-head'),
      body: exist.querySelector('.h-subblock-body'), seg: null, timer: null, t0: 0 };
    exist.querySelectorAll('.h-tool[data-tid]').forEach(r => {
      ((_HG.subRows[pid]) || (_HG.subRows[pid] = {}))[r.dataset.tid] = r;
    });
    // v2.48：快照体节化归一——旧 v2.45 两抽屉布局/平铺布局按行序重排为节
    // 结构（幂等：节化体空转）。认回后实时追加/回填都认节结构，不归一则
    // 追加会错位（当前节判定=body 尾 .h-subsec）
    _subSecNormalize(b);
    // v2.47（需求1）：旧快照段缺动作钮容器（v2.45 前结构）或容器在而空壳
    // （v2.45/46 快照的运行段——_subBlkActsPaint 当年只对 done 段绘制）——
    // 认回即补齐/绘制。运行段段头点击已从「开实况窗格」改为 toggle 折叠，
    // 窗格唯一入口=「⧉ 窗格」钮；容器空壳=钮永远不出现=实况入口断路。
    // 判据「缺容器或容器无子节点」，_subBlkActsPaint 幂等（认回每条事件都过
    // 这里，有钮即不重画）
    if (b.head) {
      const _acts = b.head.querySelector(':scope > .h-subblock-acts');
      if (!_acts) {
        const a = document.createElement('span');
        a.className = 'h-subblock-acts';
        b.head.appendChild(a);
        _subBlkActsPaint(b);
      } else if (!_acts.children.length) {
        _subBlkActsPaint(b);
      }
    }
    return b;
  }
  function _subBlkGet(pid, info) {
    if (!pid) return null;
    const known = _HG.subBlk && _HG.subBlk[pid];
    const adopted = _subBlkAdopt(pid);
    if (adopted) {
      // 仅「本次才认回」（快照恢复/历史重放后首见）才恢复计时——已在档的段
      // 每条事件都过这里，重复 resume 会把秒表文本重置成裸「运行中」且把 t0
      // 归零（实测抓到）。恢复时 t0 从段头现存「运行中 Ns」还原（旧时长不
      // 归零——R-次要③）。档案缺失（切会话往返 agents 已清）不编造完成态：
      // 保持运行状，完成信号到达由 R-FAIL1 兜底路径定格
      if (known !== adopted && !adopted.root.classList.contains('done')) {
        const inf = _subBlkInfoLive(pid);
        if (inf.live && !inf.done) {
          const st = adopted.head && adopted.head.querySelector('.h-subblock-state');
          const m = st && String(st.textContent || '').match(/运行中\s*(\d+)s/);
          adopted.t0 = (m && +m[1] > 0) ? Date.now() - (+m[1]) * 1000 : Date.now();
          _subBlkRun(pid);
        }
      }
      return adopted;
    }
    info = info || _subBlkInfoLive(pid);
    // v2.47（需求2）：collab 派生补全——省略 info 的调用（轮询喂入/兜底认回
    // 后的重建）也要拿到 collab 标记，否则协作段头误挂 hgSub（窗格钮开了必
    // 空白——独立会话无实况事件流）
    if (info.collab === undefined)
      info.collab = !!(((_HG.agents || {})[pid] || {}).collab);
    const root = document.createElement('div');
    root.className = 'h-subblock';
    root.dataset.hgSubblock = pid;
    const head = document.createElement('button');
    head.className = 'h-subblock-head';
    if (info.live) {
      // v2.47（需求1/2）：实况窗格入口自段头点击挪到「⧉ 窗格」钮——hgSub
      // 只作钮的数据源；协作段（collab）无实况流不挂 hgSub（钮不画），改挂
      // data-hg-collab 供 DOM 兜底轮询/无转写占位识别（随快照携带）
      if (info.collab) root.dataset.hgCollab = '1';
      else head.dataset.hgSub = pid;
      if (info.bg) root.dataset.hgBg = '1';   // 后台段标记——sweep DOM 兜底的非中断不收判据
    }
    else if (info.agent) {                            // 历史段：点击开回放窗格
      head.dataset.hgSubr = info.agent;
      head.dataset.hgSubType = info.type || 'Task';
      head.dataset.hgSubDesc = String(info.desc || '').slice(0, 120);
    }
    // v2.45：行首折叠箭头（完成段显示，CSS 按 .done/.collapsed 驱动开合指向）
    // + 行尾动作钮容器（_subBlkActsPaint 填「▣ 回放」「⧉ 窗格」，span+role
    // 防 button 嵌套——与 .h-tool-copy 同法）
    head.innerHTML = '<span class="h-chev h-sub-chev" aria-hidden="true">▸</span>' +
      '<span class="h-subblock-ava h-ava"></span>' +
      '<span class="h-subblock-name"></span>' +
      '<span class="h-subblock-state"></span>' +
      '<span class="h-subblock-acts"></span>';
    const body = document.createElement('div');
    body.className = 'h-subblock-body';
    // v2.45 结论行：建段即在位（空=零高度不可见）——运行期 _subText 到达即
    // 覆写（终值=最后一条 text），不能等完成聚合才建（运行期文本会丢结论）
    const sum = document.createElement('div');
    sum.className = 'h-subblock-sum';
    root.appendChild(head); root.appendChild(sum); root.appendChild(body);
    grpEnsure(true).root.appendChild(root);
    // v2.44：hist 标记历史段（renderHistSub 传入）——历史段无真实起跑时刻，
    // t0 置 0 防止 _subBlkState 拿「重建时刻」算出假 0s 用时。
    // v2.44R（复审2）：t0 优先取 agents 档案起跑时刻（Task 派发时刻）——段建
    // 时刻=首个子代理事件到达，而 CLI 不转发子代理 thinking → 初始思考期
    // （常达数十秒）零事件段不存在，think-heavy 子代理「用时」常态偏小，且
    // 与主链 Agent 派发卡秒表（派发起算）同屏打架；档案缺失回退当下
    const _t0a = info.hist ? 0 : (((_HG.agents || {})[pid] || {}).t0 || Date.now());
    const b = _HG.subBlk[pid] = { root, head, body, seg: null, timer: null,
                                  t0: _t0a, hist: !!info.hist };
    _subBlkPaint(pid, info);
    _subBlkActsPaint(b);   // v2.47（需求1）：建段即画动作钮——运行段「⧉ 窗格」（段头点击已改折叠）；协作段此时 hgSubr 未落则空，落档后调方重画
    if (info.done) _subBlkState(pid, info.err);
    else if (info.live) _subBlkRun(pid);
    // v2.57：运行态建段一律默认折叠（用户实锤「主窗的没有默认收起来」——
    // 上版只给协作段 fold，前台 Agent 派发段由首个子代理事件兜底建段、无
    // fold 参数，漏网）。主窗只露段头+结论行，内容优先看侧窗；点段头展开，
    // 展开态记忆（openState）优先于本折叠
    if (info.fold || (!info.done && !info.hist)) root.classList.add('collapsed');
    _hgScrollBottom();
    return b;
  }
  function _subBlkPaint(pid, info) {
    const b = _HG.subBlk && _HG.subBlk[pid];
    if (!b || !b.head) return;
    const label = (info && info.label) || '子代理';
    const bare = info && info.model ? String(info.model).split('[')[0].trim() : '';
    const ac = (info && info.type) || bare || label;
    const ava = b.head.querySelector('.h-subblock-ava');
    if (ava) {
      ava.className = 'h-subblock-ava h-ava ' + _hgAvaCls(ac);
      ava.style.width = '14px'; ava.style.height = '14px'; ava.style.fontSize = '9px';
      ava.textContent = String(ac || '?').charAt(0).toUpperCase();
    }
    const nm = b.head.querySelector('.h-subblock-name');
    if (nm) {
      // textContent 重赋即清旧节点，天然幂等（v2.53：「重」角标已删）
      nm.textContent = bare ? label + ' · ' + bare : label;
    }
    b.head.title = '子代理：' + label + (bare ? '，实跑模型 ' + bare : '')
      + ((info && info.desc) ? '\n' + String(info.desc).slice(0, 160) : '')
      + '\n点击段头=展开/收起（运行中也可收起，后台继续跑）；段头按钮：⧉ 窗格=实况，▣ 回放=完整过程';
  }
  function _subSecDrawer(sec, cls) {
    let d = sec.querySelector(':scope > .h-drawer.sub.' + cls);
    if (!d) {
      d = document.createElement('div');
      d.className = 'h-drawer sub ' + cls;
      d.innerHTML = '<button class="h-drawer-head"><span class="h-chev">▸</span>' +
        `<span class="h-drawer-title">${cls === 'think' ? '💭 思考' : '⚡ 工具'}</span></button>` +
        '<div class="h-drawer-body"></div>';
      if (cls === 'think') {
        const ed = sec.querySelector(':scope > .h-drawer.sub.exec');
        sec.insertBefore(d, ed || null);
      } else sec.appendChild(d);
    }
    return d;
  }
  function _subSecCount(sec) {
    if (!sec) return;
    const dT = sec.querySelector(':scope > .h-drawer.sub.think');
    const dE = sec.querySelector(':scope > .h-drawer.sub.exec');
    const nT = dT ? dT.querySelector('.h-drawer-body').children.length : 0;
    const nE = dE ? dE.querySelector('.h-drawer-body').children.length : 0;
    const tT = dT && dT.querySelector('.h-drawer-title');
    const tE = dE && dE.querySelector('.h-drawer-title');
    if (tT) tT.textContent = nT ? `💭 思考 ${nT} 次` : '💭 思考';
    if (tE) tE.textContent = nE ? `⚡ 工具 ${nE} 次` : '⚡ 工具';
    if (dT) dT.style.display = nT ? '' : 'none';
    if (dE) dE.style.display = nE ? '' : 'none';
  }
  function _subSecCur(b) {
    const last = b.body.lastElementChild;
    if (last && last.classList.contains('h-subsec')) return last;
    const sec = document.createElement('div');
    sec.className = 'h-subsec';
    b.body.appendChild(sec);
    return sec;
  }
  function _subBlkActsPaint(b) {
    if (!b || !b.head) return;
    const acts = b.head.querySelector('.h-subblock-acts');
    if (!acts) return;
    let html = '';
    if (b.head.dataset.hgSubr)
      html += '<span class="h-sub-act" role="button" data-hg-act="replay" ' +
        'title="回放该子代理完整过程（独立窗格）">▣ 回放</span>';
    // v2.55：协作段也画实况窗格钮——轮询全喂后有事可看（旧判据 hgSub 恒缺
    // =协作段永远没有「⧉ 窗格」入口，用户实锤「点不开」）。nopane=合成段
    // （renderPeer 新建，无 agents 档案）不画——点击只会弹 banner 的死按钮
    if (b.head.dataset.hgSub ||
        (!b.nopane && b.root && b.root.dataset.hgCollab === '1' && b.head.dataset.hgSubr))
      html += '<span class="h-sub-act" role="button" data-hg-act="pane" ' +
        'title="查看实时过程窗格（段头点击=折叠/展开）">⧉ 窗格</span>';
    acts.innerHTML = html;
  }
  function _subBodyPut(b, el, kind) {
    if (kind === 'think' || kind === 'tool') {
      const sec = _subSecCur(b);
      const dr = _subSecDrawer(sec, kind === 'think' ? 'think' : 'exec');
      dr.querySelector('.h-drawer-body').appendChild(el);
      _subSecCount(sec);
    } else b.body.appendChild(el);
  }
  function _subSecNormalize(b) {
    if (!b || !b.body) return;
    const legacy = [...b.body.children].filter(el =>
      el.classList.contains('h-drawer') && el.classList.contains('sub'));
    if (legacy.length) {
      const rows = [];
      legacy.sort((a, x) => (x.classList.contains('think') ? 1 : 0)
                          - (a.classList.contains('think') ? 1 : 0));   // 思考抽屉的行在前
      legacy.forEach(d => {
        const body = d.querySelector('.h-drawer-body');
        if (body) rows.push(...body.children);
        d.remove();
      });
      let anchor = b.body.firstChild;
      rows.forEach(el => b.body.insertBefore(el, anchor));
    }
    const kids = [...b.body.children];
    if (!kids.some(el => el.classList.contains('h-think-seg')
        || el.classList.contains('h-tool') || el.classList.contains('h-tool-res'))) return;
    let cur = null;
    kids.forEach(el => {
      const isT = el.classList.contains('h-think-seg');
      const isE = el.classList.contains('h-tool') || el.classList.contains('h-tool-res');
      if (!isT && !isE) { cur = null; return; }   // 气泡/note：断节（留在原地）
      if (!cur || !cur.isConnected || cur.parentNode !== b.body) {
        const sec = document.createElement('div');
        sec.className = 'h-subsec';
        b.body.insertBefore(sec, el);
        cur = sec;
      }
      const dr = _subSecDrawer(cur, isT ? 'think' : 'exec');
      dr.querySelector('.h-drawer-body').appendChild(el);
      _subSecCount(cur);
    });
  }
  function _subBlkAggregate(b) {
    if (!b || !b.body || !b.head) return;
    if (!b.root.querySelector(':scope > .h-subblock-sum')) {
      const sum = document.createElement('div');
      sum.className = 'h-subblock-sum';
      b.root.insertBefore(sum, b.body);
    }
    // 旧快照（v2.44 前的段结构）恢复后完成：段头缺箭头/动作钮容器——就地
    // 补齐（缺件补件，不假设结构完整）
    if (!b.head.querySelector(':scope > .h-sub-chev'))
      b.head.insertAdjacentHTML('afterbegin',
        '<span class="h-chev h-sub-chev" aria-hidden="true">▸</span>');
    if (!b.head.querySelector(':scope > .h-subblock-acts')) {
      const a = document.createElement('span');
      a.className = 'h-subblock-acts';
      b.head.appendChild(a);
    }
    _subSecNormalize(b);
    _subBlkActsPaint(b);
  }
  function _subBlkRun(pid) {
    const b = _HG.subBlk && _HG.subBlk[pid];
    if (!b || !b.head) return;
    if (!b.t0) b.t0 = Date.now();
    const st = b.head.querySelector('.h-subblock-state');
    if (st) {
      st.className = 'h-subblock-state run';
      // v2.43.1（R-次要③）：t0 已知（含认回恢复的旧值）即时算秒数——恢复后
      // 不闪回裸「运行中」再等 1s 首跳
      st.textContent = '运行中 ' + Math.max(0, Math.round((Date.now() - b.t0) / 1000)) + 's';
    }
    clearInterval(b.timer);
    b.timer = setInterval(() => {
      const bb = _HG.subBlk && _HG.subBlk[pid];
      if (!bb || !bb.timer || !bb.head || !bb.head.isConnected) {
        if (bb) { clearInterval(bb.timer); bb.timer = null; }
        return;
      }
      const s2 = bb.head.querySelector('.h-subblock-state');
      if (s2 && s2.classList.contains('run'))
        s2.textContent = '运行中 ' + Math.round((Date.now() - (bb.t0 || Date.now())) / 1000) + 's';
    }, 1000);
  }
  function _subBlkState(pid, err) {
    const b = _HG.subBlk && _HG.subBlk[pid];
    if (!b || !b.head) return;
    if (b.timer) { clearInterval(b.timer); b.timer = null; }
    _subSegEnd(b);
    b.root.classList.add('done');
    if (err) b.root.classList.add('err');
    const st = b.head.querySelector('.h-subblock-state');
    if (st) {
      st.className = 'h-subblock-state' + (err ? ' err' : ' ok');
      let txt = err ? '✗ 失败' : '✓ 完成';
      if (b.hist) txt += ' · 历史';
      else if (b.t0) txt += ' · 用时 ' + _hgFmtDur((Date.now() - b.t0) / 1000);
      st.textContent = txt;
    }
    // v2.45 两层收纳（v2.48 节化）：完成定格确保段体铁件+节化归一（运行期
    // 已逐节成形，此处对节化体幂等空转）+ 默认折叠。历史段同路——
    // _subBlkGet 对 done 信息也走这里，行随后按 _subBodyPut 路由落节；
    // 回填思考（_subBlkMergeThinks）发生在折叠后，DOM 操作不受 display:none
    // 影响
    _subBlkAggregate(b);
    b.root.classList.add('collapsed');
    // v2.45R（reviewer）：折叠使段体（可能数百行）瞬间收缩——用户在底部
    // 跟读时位置跳变，与点击收起路径（:927 区）同款贴底补偿对齐
    if (isNearBottom()) _hgScrollBottom();
  }
  function _subSegEnd(b) {
    if (b && b.seg && b.seg.isConnected) {
      const te = b.seg.querySelector('[data-hg-think-t]');
      const t0 = +(b.seg.dataset.t0 || 0);
      if (te && t0) te.textContent = _hgFmtDur((Date.now() - t0) / 1000);
    }
    if (b) b.seg = null;
  }
  function _subToolHeadHtml(name, summary, slotsHtml, opts) {
    // v2.44R（复审3）：opts.sec（Grep/Glob 的 in path 等次级信息）并入 title
    // 悬浮——头行保持单行摘要不被挤爆；opts.copy（Bash/PowerShell）产出复制
    // 钮：head 本体是 <button>，嵌套 button 非法，用 span+role 复用既有
    // .h-tool-copy 样式与委托（委托里 copy 分支已提到 head 分支之前）
    const o = opts || {};
    const title = summary && o.sec ? summary + ' · ' + o.sec : (summary || o.sec || '');
    return `<button class="h-tool-head"><span class="h-chev">▸</span>` +
      `<span class="h-tool-name">${_hToolIco(name)} ${esc(_hToolLabel(name))}</span>` +
      (summary ? `<span class="h-tool-arg" title="${esc(title)}">${esc(summary)}</span>` : '') +
      (o.copy ? `<span class="h-tool-copy" role="button" title="复制命令">复制</span>` : '') +
      (slotsHtml != null ? `<span class="h-tslots">${slotsHtml}</span>` : '') +
      `</button>`;
  }
  function _subToolDrawerRow(cfg, name, label, _hgInput) {
    const row = document.createElement('div');
    row.className = 'h-tool col sub';
    row.style.setProperty('--h-accent', _H_KIND_COLOR[cfg.kind] || 'var(--border)');
    const v = cfg.get ? cfg.get(_hgInput) : '';
    let summary, bodyHtml = '';
    if (cfg.mode === 'one-line') {
      // Read/Grep 等：摘要=路径/命令/模式；body 留给结果全文（输入没有更多细节）
      summary = String(v || '');
    } else {
      summary = typeof cfg.title === 'function' ? cfg.title(_hgInput) : (cfg.title || label);
      bodyHtml = _toolInputBodyHtml(cfg, v);
    }
    // v2.44R（复审3）：旧 one-line 分支对 sub 行同样给 Bash/PowerShell 复制钮
    // 与 Grep/Glob 的 sec 次级信息，抽屉化时丢了——补齐（sec 进 title、copy
    // 进头行，与主链行为对齐）
    const sec = cfg.sec ? String(cfg.sec(_hgInput) || '') : '';
    const copy = cfg.kind === 'bash';
    row.innerHTML = _subToolHeadHtml(name, summary, '', { sec, copy }) +
      `<div class="h-tool-coll">${bodyHtml}</div>`;
    row._preview = String(summary || '');
    row._t0 = Date.now();   // v2.44：行级耗时（结果到达时定格进头部）
    return row;
  }
  function _toolInputBodyHtml(cfg, v) {
    if (cfg.kind === 'diff') return `<div class="h-diff">${diffHtml(v && v.old, v && v.neu)}</div>`;
    if (cfg.kind === 'todo') return todoHtml(v && v.todos || v);
    if (cfg.kind === 'question') return (v || []).map(_hgQ =>
      `<div class="t-item"><span>❓</span><span><b>${esc(_hgQ.header || '')}</b> ${esc(_hgQ.question || '')}${(_hgQ.options || []).map(o => `<span class="q-opt">${esc(typeof o === 'string' ? o : o.label)}</span>`).join('')}</span></div>`).join('');
    return `<div class="h-tool-body">${renderMd(String(v))}</div>`;
  }
  function _subThinkShell(withTimer) {
    const seg = document.createElement('div');
    seg.className = 'h-think-seg sub';
    seg.innerHTML =
      '<button class="h-think-seg-head"><span class="h-chev">▸</span>' +
      '<span class="h-think-seg-name">💭 思考</span>' +
      `<span class="h-think-seg-t"${withTimer ? ' data-hg-think-t' : ''}>${withTimer ? '0s' : ''}</span></button>` +
      '<div class="h-think-seg-body"></div>' +
      '<i class="h-think-seg-fold" title="收起本段">收起 ⌄</i>';
    return seg;
  }
  function _subPaneThinkRow(text) {
    const th = document.createElement('div');
    th.className = 'hg-sub-think';
    th.dataset.raw = text;
    th.innerHTML = '<button class="hg-sub-think-head" title="点击展开/收起思考过程">' +
      '<span>💭 思考</span><span class="hg-sub-think-chev">›</span></button>' +
      '<div class="hg-sub-think-body"></div>';
    return th;
  }
  function _subPaneToolRow(name, hint, tuid, done) {
    const d = document.createElement('div');
    d.className = 'hg-sub-tool' + (done ? ' done' : '');
    if (tuid) d.dataset.tuid = tuid;
    d.innerHTML = '<button class="hg-sub-tool-head" title="点击展开/收起详情">' +
      '<span class="hg-sub-tdot"></span>' +
      '<span class="hg-sub-tool-name">' + esc(_hDrawerName(name || '')) + '</span>' +
      (hint ? '<span class="hg-sub-tool-hint">' + esc(String(hint).slice(0, 80)) + '</span>' : '') +
      '<span class="hg-sub-tool-chev">›</span></button>' +
      '<div class="hg-sub-tool-body"></div>';
    return d;
  }
  function _subPaneMirror(pid, kind, text) {
    const t = _sub.tabs[pid];
    if (!t || !text || !String(text).trim()) return;
    if (t.replay) return;   // v2.55R：回放 tab 由 fetch 全量自建，镜像增量不得污染
    const sc = t.sc;
    const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;
    // v2.57R：过渡查重——全量回放 fetch 读到 T1、轮询游标落后在 C，放行后
    // (C,T1] 的行会被下一轮 tick 重投镜像。只比对**铺底行**（fetch 铺底打
    // data-hg-rp 标记）尾 8 行——免疫镜像行挤窗的级联失效（8 行=2s tick 约
    // 4 个周期的重叠量，超出部分残余重复可忽略）。rp.raw / rp.textContent 均
    // 是后端 2000 字截断前缀（claude_harness.py 护栏值，需同步维护），统一
    // 前缀对齐比对；相邻真实内容逐字同文概率极低，误伤可忽略。
    const rp = [...sc.children].filter(el => el.dataset.hgRp === '1').slice(-8);
    const norm = s => String(s || '').replace(/\s+/g, '');
    if (kind === 'think') {
      // 单向前缀比对（镜像=全文、rp=截断前缀）：反向 startsWith 无真阳性收益
      // 只扩大误杀面。md 截断边界落在行内标记时前缀性质可破——启发式容差。
      if (rp.some(el => {
        const a = norm(el.dataset.raw || '');
        return !!a && norm(text).startsWith(a);
      }))
        return;
      _subAppendEl(sc, _subPaneThinkRow(text));
    } else {
      const row = _subMdRow(text);
      const want = norm(row.textContent);
      if (want && rp.some(el => {
        const got = norm(el.textContent);
        return !!got && want.startsWith(got);   // 同上：单向、启发式容差
      }))
        return;
      _subAppendEl(sc, row);
    }
    if (stick) _subScroll(pid);
  }
  function _subThink(pid, text, fromPoll) {
    const b = _subBlkGet(pid); if (!b) return;
    if (!(b.seg && b.seg.isConnected)) {
      const seg = _subThinkShell(true);
      seg.dataset.t0 = String(Date.now());
      _subBodyPut(b, seg, 'think');   // v2.48：进当前节的思考抽屉（节随行成形）
      b.seg = seg;
    }
    b.seg.querySelector('.h-think-seg-body').insertAdjacentHTML('beforeend', renderMd(text));
    // v2.43.1（R-次要②）：段内思考流式时长——每批增量到达即刷新（主链由
    // thinkHeadUpdate 驱动，段内无对偶；_subSegEnd 收口再定格一次）
    const _te = b.seg.querySelector('[data-hg-think-t]');
    const _tt0 = +(b.seg.dataset.t0 || 0);
    if (_te && _tt0) _te.textContent = _hgFmtDur((Date.now() - _tt0) / 1000);
    // v2.57：仅轮询源镜像窗格——SSE 自带 _subFeed、重渲历史行不得重复进
    // （fromPoll 区分数据来源，防回放 tab 完成后被重渲污染）
    if (fromPoll) _subPaneMirror(pid, 'think', text);
    _hgScrollBottom();
  }
  function _subText(pid, text, fromPoll) {
    if (!text || !String(text).trim()) return;
    const b = _subBlkGet(pid); if (!b) return;
    _subSegEnd(b);
    // v2.53：段内同文去重——轮询与 SSE 理论上可能双源喂同一条 text（CLI
    // 行为随版本变），渲染文本归一后与段内**任一**既有气泡等价即不重复
    // 追加（v2.54R 从「仅段尾」扩为全段——多 text 段中段重读双份的口子）
    const probe = document.createElement('div');
    probe.innerHTML = renderMd(text);
    const _norm = s => String(s || '').replace(/\s+/g, '');
    const _want = _norm(probe.textContent);
    if (_want && [...b.body.querySelectorAll('.h-msg.sub')]
        .some(el => _norm(el.textContent) === _want))
      return;
    const d = document.createElement('div');
    d.className = 'h-msg asst sub';
    d.appendChild(mdBubble(text));
    b.body.appendChild(d);
    // v2.45 结论行：折叠态段体不可见，最后一条 text 的前 120 字作为灰小结
    // 露在段头下——每条 text 到达即覆写（终值=最后一条；全文进 title 悬浮）
    const sum = b.root.querySelector(':scope > .h-subblock-sum');
    if (sum) {
      const t = String(text).replace(/\s+/g, ' ').trim();
      if (t) {
        sum.textContent = t.slice(0, 120) + (t.length > 120 ? '…' : '');
        sum.title = t.slice(0, 400);
      }
    }
    if (fromPoll) _subPaneMirror(pid, 'text', text);
    _hgScrollBottom();
  }
  function _subBlkAppendTool(pid, row) {
    const b = _subBlkGet(pid); if (!b) return;
    _subSegEnd(b);
    _subBodyPut(b, row, 'tool');   // v2.48：进当前节的工具抽屉（节随行成形）
    // v2.55R：窗格镜像——本函数是 SSE 与 fullFeed 轮询的共同通路，镜像前按
    // data-tuid 查重（SSE 路径 _subFeed 也会插同名行，双源不查重=每条工具
    // 双份、第二份永远灰点）。v2.57R：折叠气泡工厂 + 重叠窗口指纹查重——
    // 回放铺底的工具行（rp 标、无 tuid）与重投镜像按「渲染名+摘要」指纹比对
    //（局限：同文件同摘要的连续调用可能漏显一条，概率极低）
    const t = _sub.tabs[pid];
    if (t && row && row.dataset.tid &&
        !t.sc.querySelector(`.hg-sub-tool[data-tuid="${CSS.escape(row.dataset.tid)}"]`)) {
      const sc = t.sc;
      const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 80;
      const fpName = _hDrawerName(row._name || '');
      const fpHint = String(row._rawHint || '').slice(0, 80);
      const rpTools = [...sc.children]
        .filter(el => el.dataset.hgRp === '1' && el.classList.contains('hg-sub-tool'))
        .slice(-8);
      const dup = rpTools.some(el => {
        const n = el.querySelector('.hg-sub-tool-name');
        const h = el.querySelector('.hg-sub-tool-hint');
        return (n ? n.textContent : '') === fpName &&
               (h ? h.textContent : '') === fpHint;
      });
      if (!dup) {
        _subAppendEl(sc, _subPaneToolRow(row._name || '', row._preview || '',
                                         row.dataset.tid, false));
        if (stick) _subScroll(pid);
      }
    }
    _hgScrollBottom();
  }
  function _subToolResult(pid, tr) {
    // v2.55R：窗格回点先于段内早退（快照恢复后 subRows 映射丢失时，窗格
    // 镜像行仍要回点变绿+落结果）
    _subResult(pid, tr);
    const m = (_HG.subRows || {})[pid];
    const row = m && m[tr.tool_use_id];
    if (!row || !row.isConnected) return;
    const st = deriveStatus(tr);
    const bad = st === 'error' || st === 'denied';
    const slots = row.querySelector('.h-tslots');
    if (slots) {
      const dur = row._t0 ? _hgFmtDur((Date.now() - row._t0) / 1000) : '';
      slots.innerHTML = statusBadge(st) + (dur ? ` <span class="h-tsec">${dur}</span>` : '');
    }
    row.classList.toggle('err', bad);
    const txt = resultText(tr).trim();
    const coll = row.querySelector('.h-tool-coll');
    if (coll && txt && txt !== '(no content)') {
      // 截 2000 字防超长结果（Read 全文等）撑爆 DOM/快照；折叠体限高由 CSS 管
      const d = document.createElement('div');
      d.className = 'h-tool-out' + (bad ? ' err-txt' : '');
      d.textContent = txt.length > 2000 ? txt.slice(0, 2000) + '…' : txt;
      coll.appendChild(d);
    }
    if (bad) row.classList.add('open');   // 错误不藏：与主链/历史「错误永远显」对齐
  }
