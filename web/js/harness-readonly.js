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

  let D = null;                   // deps：esc/mdBubble/attChipsHtml/statusBadge/
                                  // toolIco/toolLabel/toolBodyHtml/lazyFill/lazyDrop/
                                  // timeFmt/fetchHist/_HG/wrap
  let ov = null, roFlow = null, roBar = null;

  // ---- 数据模型：histAll lines → 轮（turn）数组 ----
  // 一轮 = user 行开头 + 后续所有非 user 行（peer/renew 顶层独立渲染不入轮；
  // 轮未结束遇到下一个 user 则开新轮）。peer/renew 出现在轮内时间线位置直显。
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
    // durMs（轮首尾 ts 差）
    turns.forEach(t => {
      t.finalIdx = -1;
      t.idx.forEach(i => {
        const l = lines[i];
        if (l.role === 'assistant' && l.text && String(l.text).trim()) t.finalIdx = i;
      });
      const firstTs = t.user && t.user.ts ? Date.parse(t.user.ts) : 0;
      const lastTs = t.idx.length ? Date.parse(lines[t.idx[t.idx.length - 1]].ts || '') || 0 : 0;
      t.durMs = (firstTs && lastTs && lastTs > firstTs) ? lastTs - firstTs : 0;
      t.steps = t.idx.filter(i => i !== t.finalIdx);
    });
    return turns;
  }

  function tsAt(lines, i) { return Date.parse((lines[i] || {}).ts || '') || 0; }
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

  // 一轮（L1 总开关 + 轮体）
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

    const steps = t.steps.length;
    const durTxt = t.durMs ? D.fmtDur(t.durMs / 1000) : (steps ? steps + ' 个步骤' : '');
    // 总开关（ZCode「已工作 1 分 34 秒」）：无步骤/无结论的空轮不显示开关
    const hasProcess = steps > 0 || t.finalIdx >= 0;
    if (hasProcess) {
      const sw = document.createElement('button');
      sw.className = 'hg-ro-switch' + (expanded ? ' open' : '');
      sw.innerHTML = '<span class="hg-ro-switch-t">已工作 ' + D.esc(durTxt) + '</span>' +
        '<span class="hg-ro-switch-a">' + (expanded ? '∨' : '›') + '</span>';
      sw.title = expanded ? '收起过程，只看结论' : '展开完整过程（思考/工具/中间结论）';
      sw.onclick = () => {
        t._open = !t._open;
        // 只重渲染该轮（轮 DOM 包在容器里）
        const holder = sw.closest('[data-ro-turn]');
        const at = holder.getBoundingClientRect().top;
        renderTurnInto(holder, lines, t, t._open);
        roFlow.scrollTop += holder.getBoundingClientRect().top - at;
      };
      frag.appendChild(sw);
    }

    const holder = document.createElement('div');
    holder.className = 'hg-ro-turn' + (expanded ? ' open' : '');
    holder.dataset.roTurn = '1';
    frag.appendChild(holder);
    renderTurnInto(holder, lines, t, expanded);
    return frag;
  }

  // 轮体渲染：收起=仅最终结论；展开=时间线（L2 折叠行懒填）
  function renderTurnInto(holder, lines, t, expanded) {
    holder.className = 'hg-ro-turn' + (expanded ? ' open' : '');
    holder.innerHTML = '';
    if (!expanded) {
      if (t.finalIdx >= 0) holder.appendChild(renderAsstLine(lines[t.finalIdx].text));
      return;
    }
    t.idx.forEach(i => {
      const l = lines[i];
      if (i === t.finalIdx) holder.appendChild(renderAsstLine(l.text));
      else if (l.role === 'thinking') holder.appendChild(renderThinkRow(lines, i));
      else if (l.role === 'tool') holder.appendChild(renderToolRow(l, i));
      else if (l.role === 'assistant') { /* 空文本块跳过 */ }
      else if (l.role === 'peer') holder.appendChild(renderPeerLine(l));
      else if (l.role === 'renew') holder.appendChild(renderRenewLine(l));
    });
  }

  // ---- 分轮分页 ----
  function renderAll(turns, start) {
    roFlow._start = Math.max(0, start);
    roFlow._lastTs = 0;
    roFlow.innerHTML = '';
    if (roFlow._start > 0) {
      const bar = document.createElement('div');
      bar.className = 'hg-hist-more';
      bar.textContent = '⬆ 剩 ' + roFlow._start + ' 轮——继续上滑加载';
      roFlow.appendChild(bar);
    }
    turns.slice(roFlow._start).forEach(t => roFlow.appendChild(renderTurn(D._HG.histAll, t, !!t._open)));
    roFlow.scrollTop = roFlow.scrollHeight;
  }

  // ---- 二级折叠委托（思考/工具行，与主层同款懒填/懒丢） ----
  function onFlowClick(e) {
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
    // 上滑分页
    roFlow.addEventListener('scroll', () => {
      if (roFlow._busy || roFlow._start <= 0) return;
      if (roFlow.scrollTop <= 60) {
        roFlow._busy = true;
        const anchorH = roFlow.scrollHeight - roFlow.scrollTop;
        renderAll(turns, roFlow._start - TURNS_MORE);
        roFlow.scrollTop = roFlow.scrollHeight - anchorH;
        requestAnimationFrame(() => { roFlow._busy = false; });
      }
    }, { passive: true });
    renderAll(turns, Math.max(0, turns.length - TURNS_PAGE));
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
