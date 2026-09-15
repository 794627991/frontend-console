// ============================================================
// 代理用量统计积木（前端）——独立文件，proxy-panel.js 只留挂载点
//  - 后端 src/proxy_usage.py（GET /api/usage/summary?range=hour|7d|30d）
//  - 堆叠柱状图纯 CSS 实现，无外部库；依赖 proxy-panel.js 的全局
//    _pxFnum/_pxTok/esc（index.html 中本文件在 proxy-panel.js 之后加载）
// 挂载接口：
//  - pxUsageInit(wrap)   绑定范围切换按钮（面板创建时调一次）
//  - pxUsageLoad(wrap)   切到用量页时拉数据渲染
// ============================================================
(function () {
  'use strict';
  let wrap = null;
  let uRange = 'hour';

  const U_COLORS = ['#4e8fd0', '#43a06e', '#c9873a', '#c75d68', '#7a68c9', '#4fa8b8', '#b0689e', '#8a9a3e'];

  function _uColor(models) {
    // 模型名稳定排序后按序分配颜色（同一模型在所有视图同色）
    return Object.keys(models).sort().map((m, i) => [m, U_COLORS[i % U_COLORS.length]]);
  }

  async function loadUsage() {
    if (!wrap) return;
    const uTotalEl = wrap.querySelector('[data-px-u-total]');
    const uChartEl = wrap.querySelector('[data-px-u-chart]');
    try {
      const r = await fetch('/api/usage/summary?range=' + uRange);
      const j = await r.json();
      if (j.ok) _renderUsage(j);
    } catch (e) {
      uChartEl.innerHTML = '<div class="px-hint">加载失败: ' + esc(String(e)) + '</div>';
    }
  }

  function _renderUsage(j) {
    const q = (sel) => wrap.querySelector(sel);
    const uTotalEl = q('[data-px-u-total]');
    const uChartEl = q('[data-px-u-chart]');
    const uXEl = q('[data-px-u-x]');
    const uLegendEl = q('[data-px-u-legend]');
    const uTableEl = q('[data-px-u-table]');
    const uTitleEl = q('[data-px-u-title]');
    const uKeepEl = q('[data-px-u-keep]');
    uKeepEl.textContent = j.keep_days;
    const items = j.items || [];
    // 汇总三卡
    const tot = j.total || {};
    let tReq = 0, tIn = 0, tOut = 0;
    for (const v of Object.values(tot)) { tReq += v[0]; tIn += v[1]; tOut += v[2]; }
    uTotalEl.innerHTML = [['请求数', _pxFnum(tReq)], ['输入 tokens', _pxTok(tIn)], ['输出 tokens', _pxTok(tOut)]]
      .map(([k, v]) => `<div class="px-card"><div class="px-card-k">${k}</div><div class="px-card-v">${v}</div></div>`).join('');
    // 柱状图：堆叠柱，每柱=item（小时/日），段=模型 tokens(in+out)
    const palette = Object.fromEntries(_uColor(tot));
    uLegendEl.innerHTML = _uColor(tot).map(([m, c]) =>
      `<span class="px-lg-item"><i style="background:${c}"></i>${esc(m)}</span>`).join('') || '<span class="px-hint">暂无数据</span>';
    uTitleEl.textContent = uRange === 'hour' ? '当日 Token 用量（输入+输出，按小时）'
      : ('Token 用量（输入+输出，近 ' + (uRange === '7d' ? '7' : '30') + ' 日）');
    let max = 0;
    for (const it of items) {
      it._tot = 0;
      for (const v of Object.values(it.models)) it._tot += v[1] + v[2];
      if (it._tot > max) max = it._tot;
    }
    const labelEvery = uRange === 'hour' ? 2 : (uRange === '30d' ? 5 : 1);
    let cols = '', xs = '';
    items.forEach((it, idx) => {
      let segs = '';
      for (const [m, c] of _uColor(it.models)) {
        const v = it.models[m];
        const tk = v[1] + v[2];
        if (!tk) continue;
        const h = max ? Math.max(2, Math.round(tk / max * 100)) : 0;
        segs += `<div class="px-u-seg" style="height:${h}%;background:${c};"></div>`;
      }
      const reqN = it._tot ? Object.values(it.models).reduce((a, v) => a + v[0], 0) : 0;
      cols += `<div class="px-u-col" title="${esc(it.key)}　请求 ${reqN} 次">` +
        (it._tot ? segs : '<div class="px-u-empty"></div>') + '</div>';
      xs += `<div class="px-u-lb">${idx % labelEvery === 0 ? esc(it.label) : ''}</div>`;
    });
    uChartEl.innerHTML = cols || '<div class="px-hint">暂无数据——代理转发请求后这里开始累积</div>';
    uXEl.innerHTML = xs;
    uXEl.style.display = cols ? '' : 'none';
    // 模型明细表
    const rows = _uColor(tot).map(([m]) => {
      const v = tot[m];
      return `<tr><td><i class="px-lg-dot" style="background:${palette[m]}"></i>${esc(m)}</td>` +
        `<td>${_pxFnum(v[0])}</td><td>${_pxTok(v[1])}</td><td>${_pxTok(v[2])}</td><td>${_pxTok(v[1] + v[2])}</td></tr>`;
    }).join('');
    uTableEl.innerHTML = rows
      ? `<table class="px-u-table"><tr><th>模型</th><th>请求</th><th>输入</th><th>输出</th><th>合计</th></tr>${rows}</table>`
      : '<div class="px-hint">暂无数据</div>';
  }

  // ---- 挂载接口 ----
  window.pxUsageInit = function (w) {
    wrap = w;
    wrap.querySelectorAll('[data-px-u-range]').forEach(btn => {
      btn.onclick = () => {
        uRange = btn.dataset.pxURange;
        wrap.querySelectorAll('[data-px-u-range]').forEach(b => b.classList.toggle('px-tab-act', b === btn));
        loadUsage();
      };
    });
  };
  window.pxUsageLoad = function () { loadUsage(); };
})();
