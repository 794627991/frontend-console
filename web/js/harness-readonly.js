// ============================================================
// 只读禅模式 v2.3.11 —— ZCode 方案完整重构（独立积木文件）
// 参考（用户截图逐像素还原）：默认只显「用户消息 + 已工作 Xs › + 最终结论」；
// 点总开关展开时间线（思考行/工具行默认收起、各自二级展开；中间结论直显）。
// 两级折叠：L1=轮总开关（每轮独立）；L2=思考行/工具行。
// 分轮分页：初始渲染最近 TURNS_PAGE 轮，上滑加载更早。
// 依赖经 enter(deps) 注入（claude-harness.js 的闭包助手），零全局耦合。
// ============================================================
(function () {
  'use strict';

  const TURNS_PAGE = 12;          // 初始渲染轮数；上滑 +8
  const TURNS_MORE = 8;
  // v2.39 对称窗口上限：DOM 里同时存在的轮数恒有界。旧实现上滑只增不减——
  // Chromium scrollHeight 硬上限 33,554,432px，触顶后高度被钳制，最新消息
  // 落在可滚区之外=「翻完历史往下永远滚不回底」（另一台设备修过没修成：
  // 旧方案只控初始渲染量，没控上滑累积总量）。
  const WIN_MAX = TURNS_PAGE + TURNS_MORE * 2;

  let D = null;                   // deps：esc/mdBubble/attChipsHtml/statusBadge/
                                  // toolIco/toolLabel/toolBodyHtml/lazyFill/lazyDrop/
                                  // timeFmt/fetchHist/_HG/wrap
  let ov = null, roFlow = null, roBar = null;

  // ---- 数据模型：histAll lines → 轮（turn）数组 ----
  // 一轮 = user 行开头 + 后续所有非 user 行（peer/renew 顶层独立渲染不入轮；
  // 轮未结束遇到下一个 user 则开新轮）。peer/renew 出现在轮内时间线位置直显。
  // v2.46：子代理段行（sub_*）入轮——只读层是 busy 会话重开后唯一的历史入口
  // （主 flow 扩段被 busy 门拦死），此前硬跳过=「看不到 agent 历史数据」的
  // 一路根因。渲染轻量化：段头一行（角色/说明/状态/计数）+ 文本气泡，过程行
  // （sub_tool/sub_think/sub_result）并入段头计数不逐行渲——只读层面对的是
  // 海量会话，逐行会破坏「DOM 恒有界」。
  function buildTurns(lines) {
    const turns = [];
    let cur = null;
    lines.forEach((l, i) => {
      const role = l.role;
      if (role === 'user') {
        cur = { idx: [], user: l, ui: i };
        turns.push(cur);
        return;
      }
      if (!cur) {                  // 轮外行（会话开头的历史残留）
        cur = { idx: [], user: null, ui: -1 };
        turns.push(cur);
      }
      cur.idx.push(i);
    });
    // 每轮派生：steps（思考/工具/中间文本行号）、finalIdx（最后一段非空 AI 文本）、
    // durMs（轮首尾 ts 差）。steps 剔除 sub_* 行——段在渲染层自成一块，
    // 计入会把「N 步」虚高（v2.43.1 的口径保留）
    turns.forEach(t => {
      t.finalIdx = -1;
      t.idx.forEach(i => {
        const l = lines[i];
        if (l.role === 'assistant' && l.text && String(l.text).trim()) t.finalIdx = i;
      });
      const firstTs = t.user && t.user.ts ? Date.parse(t.user.ts) : 0;
      const lastTs = t.idx.length ? Date.parse(lines[t.idx[t.idx.length - 1]].ts || '') || 0 : 0;
      t.durMs = (firstTs && lastTs && lastTs > firstTs) ? lastTs - firstTs : 0;
      t.steps = t.idx.filter(i => i !== t.finalIdx
        && !String((lines[i] || {}).role || '').startsWith('sub_'));
    });
    return turns;
  }

  function tsAt(lines, i) { return Date.parse((lines[i] || {}).ts || '') || 0; }
  // 轮末行 ts（idx 空时回退轮首 user 行）：loadOlder 头部扩前预置时间条基准用
  function turnEndTs(lines, t) {
    return tsAt(lines, t.idx.length ? t.idx[t.idx.length - 1] : t.ui);
  }
  // 行时长：该行 ts → 同轮下一行 ts 的差（缺失返回 0）
  function stepDurMs(lines, i) {
    const a = tsAt(lines, i);
    if (!a) return 0;
    for (let j = i + 1; j < lines.length; j++) {
      const b = tsAt(lines, j);
      if (b >= a) return b - a;
    }
    return 0;
  }
  // ZCode 口径：单段思考模糊「持续了几秒」（<60s）；长思考给精确值
  function thinkDurLabel(ms) {
    if (!ms) return '持续了几秒';
    if (ms < 60 * 1000) return '持续了几秒';
    return '约 ' + D.fmtDur(ms / 1000);
  }

  // ---- 渲染 ----
  function renderUserLine(l) {
    const d = document.createElement('div');
    d.className = 'h-msg user';
    const imgs = (l.files || []).filter(p => D.imgExt.test(p));
    const files = (l.files || []).filter(p => !D.imgExt.test(p));
    if (imgs.length || files.length) {
      const at = document.createElement('div');
      at.className = 'h-bubble-atts';
      at.innerHTML = D.attChipsHtml(imgs, files);
      d.appendChild(at);
    }
    const body = (l.text && l.text.trim()) || ((imgs.length || files.length) ? '*（图片/附件）*' : '');
    d.appendChild(D.mdBubble(body));
    return d;
  }

  function renderAsstLine(text) {
    const d = document.createElement('div');
    d.className = 'h-msg asst';
    d.appendChild(D.mdBubble(text));
    return d;
  }

  // 思考行（二级折叠）：💭 思考 · 持续了几秒 ›
  function renderThinkRow(lines, hi) {
    const seg = document.createElement('div');
    seg.className = 'h-think-seg';
    seg.dataset.hi = String(hi);
    seg.dataset.hgLazy = '1';
    seg.innerHTML =
      '<button class="h-think-seg-head"><span class="h-chev">▸</span>' +
      '<span class="h-think-seg-name">思考</span>' +
      '<span class="h-think-seg-t">· ' + thinkDurLabel(stepDurMs(lines, hi)) + '</span></button>' +
      '<div class="h-think-seg-body"></div>' +
      '<i class="h-think-seg-fold" title="收起本段">收起 ⌄</i>';
    return seg;
  }

  // 工具行（二级折叠）：icon 名 命令摘要 …（等宽、超长截断）
  function renderToolRow(l, hi) {
    const d = document.createElement('div');
    const err = !!l.err;
    d.className = 'h-tool col' + (err ? ' err open' : '');
    const hint = (l.summary || (l.input && (l.input.command || l.input.file_path || l.input.pattern || '')) || '').trim();
    const hintHtml = hint && !err ? '<span class="h-tool-hint">' + D.esc(hint.slice(0, 72)) + (hint.length > 72 ? '…' : '') + '</span>' : '';
    d.innerHTML =
      '<button class="h-tool-head"><span class="h-chev">▸</span>' +
      '<span class="h-tool-name">' + D.toolIco(l.text) + ' ' + D.esc(D.toolLabel(l.text)) + '</span>' +
      hintHtml +
      '<span class="h-tslots">' + D.statusBadge(err ? 'error' : 'completed') + '</span></button>' +
      '<div class="h-tool-coll">' + (err ? D.toolBodyHtml(l) : '') + '</div>';
    d.dataset.hi = String(hi);
    d.dataset.hgLazy = err ? '' : '1';
    return d;
  }

  function renderPeerLine(l) {
    const d = document.createElement('div');
    d.className = 'h-peer';
    const head = document.createElement('div');
    head.className = 'h-peer-head';
    head.textContent = '📥 ' + (l.name || '其他会话') + ' 回传';
    d.appendChild(head);
    const b = document.createElement('div');
    b.className = 'h-bubble';
    b.innerHTML = D.renderMd ? D.renderMd(l.text || '') : D.esc(l.text || '');
    d.appendChild(b);
    return d;
  }

  function renderRenewLine(l) {
    const d = document.createElement('div');
    d.className = 'h-switch';
    d.innerHTML = '<span></span><i>♻️ ' + D.esc(l.text || '上下文超窗，已自动重开会话') + '</i><span></span>';
    return d;
  }

  // 识图 MCP 转交线（简版）：📤 转交识图 · 用时 Xs
  function renderRelayLine(l) {
    const d = document.createElement('div');
    d.className = 'h-switch';
    const dur = (l.dur || 0) > 0 ? ' · 用时 ' + D.fmtDur(l.dur) : '';
    d.innerHTML = '<span></span><i>📤 转交识图' + D.esc(dur) + '</i><span></span>';
    return d;
  }

  // v2.46：子代理段头（只读层轻量形态）——分割线一行带角色/说明/状态/计数。
  // 计数从 sub_open 行向后扫同 agent 的连续 sub_* 行（O(段长)，段 ≤200 行）
  function renderSubHead(lines, hi) {
    const l = lines[hi];
    let think = 0, tool = 0, text = 0;
    for (let j = hi + 1; j < lines.length; j++) {
      const r = lines[j];
      if (!r || String(r.role || '').indexOf('sub_') !== 0 || r.agent !== l.agent) break;
      if (r.role === 'sub_think') think++;
      else if (r.role === 'sub_tool' || r.role === 'sub_result') tool++;
      else if (r.role === 'sub_text') text++;
    }
    const d = document.createElement('div');
    d.className = 'hg-ro-sub' + (l.err ? ' err' : '');
    const desc = String(l.desc || '').trim();
    const st = l.err ? '✗ 失败' : '✓';
    d.innerHTML = '<span class="hg-ro-sub-ava">' + D.esc(String(l.type || '?').charAt(0).toUpperCase()) + '</span>' +
      '<b>' + D.esc(l.type || 'Task') + '</b>' +
      (desc ? '<span class="hg-ro-sub-desc" title="' + D.esc(desc.slice(0, 160)) + '">' + D.esc(desc.slice(0, 60)) + (desc.length > 60 ? '…' : '') + '</span>' : '') +
      '<span class="hg-ro-sub-stat">' + st +
      (tool || think ? ' · ' + tool + ' 工具' + (think ? ' · ' + think + ' 思考' : '') : '') + '</span>';
    return d;
  }
  // v2.46：子代理正文气泡（结论直显——只读层口径「默认只看结论」）
  function renderSubTextLine(l) {
    const d = document.createElement('div');
    d.className = 'h-msg asst sub';
    d.appendChild(D.mdBubble(l.text || ''));
    return d;
  }

  // 一轮（L1 总开关 + 轮体）
  // v2.3.12 修复：总开关点击无效——旧实现 sw.closest('[data-ro-turn]') 找轮
  // 容器，但 sw 与容器是兄弟节点（同挂 roFlow 下），closest 恒 null → 点击即
  // TypeError 静默失败（用户实锤「点不开，不能展开」）。改为 holder 提前创建、
  // onclick 闭包直接捕获。
  function renderTurn(lines, t, expanded) {
    const frag = document.createDocumentFragment();
    // 时间条（跨轮 >5min）
    const ms = t.user && t.user.ts ? Date.parse(t.user.ts) : 0;
    if (ms && ms - (roFlow._lastTs || 0) >= 5 * 60 * 1000) {
      roFlow._lastTs = ms;
      const bar = document.createElement('div');
      bar.className = 'h-time';
      bar.textContent = D.timeFmt(ms);
      frag.appendChild(bar);
    }
    if (t.user) frag.appendChild(renderUserLine(t.user));

    const holder = document.createElement('div');
    holder.className = 'hg-ro-turn' + (expanded ? ' open' : '');
    holder.dataset.roTurn = '1';

    const steps = t.steps.length;
    // v2.46：段在轮内（steps 已剔 sub_*）——纯子代理轮也给展开开关
    const hasSub = t.idx.some(i => (lines[i] || {}).role === 'sub_open');
    // v2.3.12：时长 + 步数一起给（此前缺 ts 恒 fallback「N 个步骤」，根因在
    // transcript_for 的 assistant/thinking 行漏带 ts，已修）
    const durTxt = t.durMs
      ? D.fmtDur(t.durMs / 1000) + (steps ? ' · ' + steps + ' 步' : '')
      : (steps ? steps + ' 个步骤' : '');
    // 总开关（ZCode「已工作 1 分 34 秒」）：无步骤/无结论的空轮不显示开关
    const hasProcess = steps > 0 || t.finalIdx >= 0 || hasSub;
    if (hasProcess) {
      const sw = document.createElement('button');
      sw.className = 'hg-ro-switch' + (expanded ? ' open' : '');
      sw.innerHTML = '<span class="hg-ro-switch-t">已工作 ' + D.esc(durTxt) + '</span>' +
        '<span class="hg-ro-switch-a">' + (expanded ? '∨' : '›') + '</span>';
      sw.title = expanded ? '收起过程，只看结论' : '展开完整过程（思考/工具/中间结论）';
      sw.onclick = () => {
        t._open = !t._open;
        // 只重渲染该轮，并保持视口锚定（展开/收起不跳屏）
        const at = holder.getBoundingClientRect().top;
        renderTurnInto(holder, lines, t, t._open);
        roFlow.scrollTop += holder.getBoundingClientRect().top - at;
      };
      frag.appendChild(sw);
    }

    frag.appendChild(holder);
    renderTurnInto(holder, lines, t, expanded);
    return frag;
  }

  // 轮体渲染：收起=结论（+子代理段头行——v2.46：段头是一行轻量元素，
  // 收起态也露出——否则「这轮派了哪些代理」要展开才知道，重开后只读层
  // 看不出 agent 痕迹）；展开=时间线（L2 折叠行懒填）
  function renderTurnInto(holder, lines, t, expanded) {
    holder.className = 'hg-ro-turn' + (expanded ? ' open' : '');
    holder.innerHTML = '';
    if (!expanded) {
      t.idx.forEach(i => {
        if ((lines[i] || {}).role === 'sub_open') holder.appendChild(renderSubHead(lines, i));
      });
      if (t.finalIdx >= 0) holder.appendChild(renderAsstLine(lines[t.finalIdx].text));
      return;
    }
    t.idx.forEach(i => {
      const l = lines[i];
      // v2.3.12：中间 assistant 文本不再是空块跳过——穿插在思考/工具间的
      // 中间结论照常渲染（用户实锤「中间应答输出没了，是穿插在思考和工具
      // 之间的」）。后端已滤空白占位，这里非空即显；finalIdx 同路径。
      if (l.role === 'thinking') holder.appendChild(renderThinkRow(lines, i));
      else if (l.role === 'tool') holder.appendChild(renderToolRow(l, i));
      else if (l.role === 'assistant') {
        if (l.text && String(l.text).trim()) holder.appendChild(renderAsstLine(l.text));
      }
      else if (l.role === 'peer') holder.appendChild(renderPeerLine(l));
      else if (l.role === 'renew') holder.appendChild(renderRenewLine(l));
      else if (l.role === 'vision_relay') holder.appendChild(renderRelayLine(l));
      // v2.46：子代理段——段头一行 + 文本气泡；过程行并入段头计数不逐行渲
      else if (l.role === 'sub_open') holder.appendChild(renderSubHead(lines, i));
      else if (l.role === 'sub_text') {
        if (l.text && String(l.text).trim()) holder.appendChild(renderSubTextLine(l));
      }
    });
  }

  // ---- 分轮分页（v2.39 对称窗口）----
  // 窗口状态 [roWinS, roWinE)：DOM 只保有这段轮次。上滑加载更早=头部扩充+
  // 摘尾部；下滑加载更新=尾部扩充+摘头部。scrollHeight 恒有界，永不触
  // Chromium 33.5M 钳制。turn 的 _open 展开态存 turns 对象上，摘除重挂不丢。
  let roWinS = 0, roWinE = 0;

  // 挂载助手（P1 修复）：renderTurn 返回 DocumentFragment，而 fragment 挂载时
  // 子节点散开、自身不进 DOM——旧实现把 fragment 存进 _el，摘除循环对它调
  // .remove() 直接 TypeError（remove 定义在 ChildNode mixin，只混入 Element/
  // CharacterData/DocumentType，fragment 没有），窗口摘除全废=「DOM 恒有界」
  // 核心机制没生效，且异常中断留下半更新状态（scroll 处理器里 _busy 永远
  // 复位不了，后续翻页全卡死）。挂载前快照 fragment 的真实子节点数组存 _el，
  // 摘除按数组逐个 remove。
  function mountTurn(turns, i, before) {
    const f = renderTurn(D._HG.histAll, turns[i], !!turns[i]._open);
    // 必须挂载前抓：挂载后子节点散开，fragment.children 立即变空
    const els = Array.prototype.slice.call(f.children);
    if (before) roFlow.insertBefore(f, before); else roFlow.appendChild(f);
    turns[i]._el = els;          // 统一存真实 DOM 元素数组（三个挂载点类型一致）
  }

  function renderBars(turns) {
    roFlow.querySelectorAll(':scope > .hg-hist-more').forEach(b => b.remove());
    if (roWinS > 0) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      bar.textContent = '⬆ 剩 ' + roWinS + ' 轮——继续上滑加载';
      roFlow.insertBefore(bar, roFlow.firstChild);
    }
    if (roWinE < turns.length) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more hg-hist-more-btm';
      bar.textContent = '⬇ 剩 ' + (turns.length - roWinE) + ' 轮——下滑加载';
      roFlow.appendChild(bar);
    }
  }

  function renderWindow(turns, s, e) {
    roWinS = Math.max(0, s);
    roWinE = Math.min(turns.length, e);
    roFlow._lastTs = 0;
    roFlow.innerHTML = '';
    for (let i = roWinS; i < roWinE; i++) mountTurn(turns, i, null);
    renderBars(turns);
    roFlow.scrollTop = roFlow.scrollHeight;
  }

  // 上滑到顶：头部补 TURNS_MORE 轮（锚定视口），窗口超限摘尾部（视口在
  // 顶部，摘视口下方内容不动视口，无需锚定补偿）
  function loadOlder(turns) {
    if (roWinS <= 0) return;
    const s2 = Math.max(0, roWinS - TURNS_MORE);
    const anchorH = roFlow.scrollHeight - roFlow.scrollTop;
    // 时间条基准预置（P2 修复）：_lastTs 保留的是窗口内较新轮的时间戳，
    // 头部扩的轮次 ms - _lastTs 恒为负 → 上滑加载的轮次时间条恒不显示。
    // 预置为窗口外前一轮的末行 ts（s2==0 时归 0，与 renderWindow 全量渲染
    // 起点同口径），渲染循环内随时间条出现自动前推，判定与顺着时间线渲染
    // 完全一致。
    roFlow._lastTs = s2 > 0 ? turnEndTs(D._HG.histAll, turns[s2 - 1]) : 0;
    const topBar = roFlow.querySelector('.hg-hist-more');  // 顶部「继续上滑」条，逐轮插它前面保持顺序
    for (let i = s2; i < roWinS; i++) mountTurn(turns, i, topBar);
    roWinS = s2;
    roFlow.scrollTop = roFlow.scrollHeight - anchorH;
    const maxE = roWinS + WIN_MAX;
    for (let i = maxE; i < roWinE; i++) {
      const els = turns[i]._el;
      if (els) els.forEach(el => { if (el.isConnected) el.remove(); });
    }
    if (roWinE > maxE) roWinE = maxE;
    renderBars(turns);
  }

  // 下滑到底：尾部补 TURNS_MORE 轮，窗口超限摘头部（锚定视口不跳屏）。
  // 旧版没有这条路径——翻完历史后只能靠滚轮硬爬，触顶即永久回不了底。
  function loadNewer(turns) {
    if (roWinE >= turns.length) return;
    const e2 = Math.min(turns.length, roWinE + TURNS_MORE);
    const s2 = Math.max(0, e2 - WIN_MAX);
    for (let i = roWinS; i < s2; i++) {
      const els = turns[i]._el;
      if (els) els.forEach(el => { if (el.isConnected) el.remove(); });
    }
    const afterHead = roFlow.scrollHeight;      // 摘头后测（s2==roWinS 时不变）
    const anchorH = afterHead - roFlow.scrollTop;
    const btmBar = roFlow.querySelector('.hg-hist-more-btm');
    for (let i = roWinE; i < e2; i++) mountTurn(turns, i, btmBar);
    roWinS = s2; roWinE = e2;
    roFlow.scrollTop = roFlow.scrollHeight - anchorH;
    renderBars(turns);
  }

  // ---- 二级折叠委托（思考/工具行，与主层同款懒填/懒丢） ----
  function onFlowClick(e) {
    // v2.3.12：附件图片 chip → Lightbox（主层 flow 有同款委托，只读层此前
    // 漏接——chip 点击无任何反应，用户实锤「图片点了也没预览」）
    const img = e.target.closest('[data-img]');
    if (img) { D.openLightbox && D.openLightbox(img.dataset.img); return; }
    const sHead = e.target.closest('.h-think-seg-head');
    if (sHead) {
      const seg = sHead.closest('.h-think-seg');
      if (seg) {
        const opening = !seg.classList.contains('open');
        if (opening) D.lazyFill(seg); else D.lazyDrop(seg);
        seg.classList.toggle('open');
      }
      return;
    }
    const sFold = e.target.closest('.h-think-seg-fold');
    if (sFold) {
      const seg = sFold.closest('.h-think-seg');
      if (seg) { D.lazyDrop(seg); seg.classList.remove('open'); }
      return;
    }
    const tHead = e.target.closest('.h-tool-head');
    if (tHead) {
      const row = tHead.closest('.h-tool');
      if (row) {
        const opening = !row.classList.contains('open');
        if (opening) D.lazyFill(row); else D.lazyDrop(row);
        row.classList.toggle('open');
      }
    }
  }

  // ---- 入口 ----
  function enter(deps) {
    D = deps;
    exit();
    const lines = D._HG.histAll || [];
    if (!lines.length) { D.onEmpty && D.onEmpty(); return; }
    const turns = buildTurns(lines);
    ov = document.createElement('div');
    ov.className = 'hg-readonly';
    ov.innerHTML =
      '<div class="hg-ro-bar">' +
      '<span class="hg-ro-title">📖 只读 · ' + turns.length + ' 轮对话</span>' +
      '<span class="hg-ro-busy" data-ro-busy style="display:none">● 回复后台进行中…（退出后可见）</span>' +
      '<span class="hg-ro-hint">默认只看结论 · 点「已工作」展开过程 · 思考/工具再点开细节</span>' +
      '<button class="hg-ro-exit" title="退出并清空全部渲染">✕ 退出</button></div>' +
      '<div class="hg-ro-flow"></div>';
    D.wrap.appendChild(ov);
    roBar = ov.querySelector('.hg-ro-bar');
    roFlow = ov.querySelector('.hg-ro-flow');
    ov.querySelector('.hg-ro-exit').onclick = exit;
    roFlow.addEventListener('click', onFlowClick);
    // 双向分页（v2.39 对称窗口）：上滑加载更早 / 下滑加载更新
    roFlow.addEventListener('scroll', () => {
      if (roFlow._busy) return;
      if (roFlow.scrollTop <= 60 && roWinS > 0) {
        roFlow._busy = true;
        loadOlder(turns);
        requestAnimationFrame(() => { roFlow._busy = false; });
      } else if (roFlow.scrollHeight - roFlow.scrollTop - roFlow.clientHeight <= 60
                 && roWinE < turns.length) {
        roFlow._busy = true;
        loadNewer(turns);
        requestAnimationFrame(() => { roFlow._busy = false; });
      }
    }, { passive: true });
    renderWindow(turns, Math.max(0, turns.length - TURNS_PAGE), turns.length);
    // 后台回复指示（禅层盖住主 flow，SSE 进度看不到——顶栏亮指示防误判卡死）
    const busyEl = ov.querySelector('[data-ro-busy]');
    const busyTimer = setInterval(() => {
      if (!ov || !ov.isConnected) { clearInterval(busyTimer); return; }
      busyEl.style.display = D._HG.busy ? '' : 'none';
    }, 1000);
  }

  function exit() {
    if (ov && ov.isConnected) ov.remove();   // 整层销毁——渲染记录全清（GC）
    ov = null; roFlow = null; roBar = null;
  }

  window.HgReadonly = { enter, exit };
})();
