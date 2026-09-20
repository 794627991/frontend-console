// ============================================================
// 内置截图标注 v2.3.12 自研轻量版（用户最终定调，三硬指标）：
//   ① 当前窗口内完成，绝不切窗口/全屏（无分辨率跳变）
//   ② 无暗色遮罩——底图原亮度显示，选区用亮色边框标识
//   ③ 导出恒为原生分辨率（canvas 内部=底图像素，CSS 等比缩放显示，
//      指针坐标自换算回内部坐标系——所见即所得且像素无损）
// 数据模型蓝本：js-screen-shot（MIT）——标注=对象数组全量重放，撤销=pop。
// 工具：框选（8 向柄/拖动）/矩形/箭头/画笔/文字/撤销/颜色/粗细。
// ============================================================
(function () {
  'use strict';

  let S = null;   // 当前截图会话状态

  function _esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  function _dispose() {
    if (!S) return;
    try { S.root.remove(); } catch (_) {}
    try { document.removeEventListener('keydown', S.keyCap, true); } catch (_) {}
    document.documentElement.style.background = '';
    S = null;
  }

  function _finish(dataURL) {
    _dispose();
    if (!dataURL) return;
    fetch('/api/snip/save', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({data_url: dataURL})})
      .then(r => r.json()).then(sv => {
        if (!sv.ok) { showBanner(sv.err || '截图保存失败', 3000, true); return; }
        if (typeof window.harnessAddFilesByPath === 'function') window.harnessAddFilesByPath([sv.path]);
        else showBanner('截图已复制到剪贴板（打开 Claude 对话可自动挂为附件）', 2500);
      }).catch(e => showBanner('截图保存失败：' + e, 3000, true));
  }

  // 导出：选区原生像素 = 底图对应区域 + 标注层对应区域
  function _export() {
    const r = S.sel;   // 内部坐标
    const w = Math.round(r.w), h = Math.round(r.h);
    if (w < 2 || h < 2) { _finish(null); return; }
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    const cx = cv.getContext('2d');
    cx.drawImage(S.img, r.x, r.y, w, h, 0, 0, w, h);
    cx.drawImage(S.canvas, r.x, r.y, w, h, 0, 0, w, h);
    _finish(cv.toDataURL('image/png'));
  }

  function _redraw() {
    const cx = S.canvas.getContext('2d');
    cx.clearRect(0, 0, S.canvas.width, S.canvas.height);
    for (const o of S.objs) _drawObj(cx, o);
    if (S.live) _drawObj(cx, S.live);
  }

  function _drawObj(cx, o) {
    cx.save();
    cx.strokeStyle = o.color; cx.fillStyle = o.color;
    cx.lineWidth = o.width;
    cx.lineCap = 'round'; cx.lineJoin = 'round';
    const x = Math.min(o.x1, o.x2), y = Math.min(o.y1, o.y2);
    const w = Math.abs(o.x2 - o.x1), h = Math.abs(o.y2 - o.y1);
    if (o.t === 'rect') { cx.strokeRect(x, y, w, h); }
    else if (o.t === 'arrow') {
      const ang = Math.atan2(o.y2 - o.y1, o.x2 - o.x1);
      const len = Math.hypot(o.x2 - o.x1, o.y2 - o.y1);
      const hw = Math.max(10, o.width * 3.2), hl = Math.max(12, o.width * 3.8);
      cx.beginPath(); cx.moveTo(o.x1, o.y1);
      cx.lineTo(o.x2 - Math.cos(ang) * hl * 0.8, o.y2 - Math.sin(ang) * hl * 0.8);
      cx.stroke();
      cx.beginPath();
      cx.moveTo(o.x2, o.y2);
      cx.lineTo(o.x2 - Math.cos(ang - 0.42) * hl, o.y2 - Math.sin(ang - 0.42) * hl);
      cx.lineTo(o.x2 - Math.cos(ang + 0.42) * hl, o.y2 - Math.sin(ang + 0.42) * hl);
      cx.closePath(); cx.fill();
    }
    else if (o.t === 'pen') {
      cx.beginPath();
      cx.moveTo(o.pts[0][0], o.pts[0][1]);
      for (let i = 1; i < o.pts.length; i++) cx.lineTo(o.pts[i][0], o.pts[i][1]);
      cx.stroke();
    }
    else if (o.t === 'text') {
      cx.font = `${o.fs}px sans-serif`;
      cx.textBaseline = 'top';
      const lines = String(o.txt || '').split('\n');
      lines.forEach((ln, i) => cx.fillText(ln, o.x1, o.y1 + i * o.fs * 1.25));
    }
    cx.restore();
  }

  // ---- 选区 DOM（亮色边框 + 四角柄 + 尺寸标签 + 工具栏）----
  function _syncSelBox() {
    const r = S.sel;
    const d = S.dispRect();   // 内部→显示坐标
    const b = S.selBox;
    b.style.display = '';
    b.style.left = d.x + 'px'; b.style.top = d.y + 'px';
    b.style.width = d.w + 'px'; b.style.height = d.h + 'px';
    S.sizeTag.textContent = Math.round(r.w) + '×' + Math.round(r.h);
    S.sizeTag.style.left = d.x + 'px';
    S.sizeTag.style.top = Math.max(0, d.y - 22) + 'px';
    // 工具栏贴选区下方（越界上翻）
    const tb = S.toolbar;
    tb.style.display = 'flex';
    tb.style.left = Math.max(4, Math.min(d.x, S.vw - tb.offsetWidth - 4)) + 'px';
    tb.style.top = (d.y + d.h + 8 + tb.offsetHeight > S.vh
      ? Math.max(4, d.y - tb.offsetHeight - 8) : d.y + d.h + 8) + 'px';
  }

  const _TOOLS = [['rect', '▭ 矩形'], ['arrow', '➚ 箭头'], ['pen', '✏ 画笔'],
                  ['text', 'A 文字'], ['undo', '↶ 撤销'], ['ok', '✓ 确认'], ['cancel', '✕ 取消']];
  const _COLORS = ['#e34c4c', '#f5c518', '#2c8cff', '#3fb950', '#ffffff', '#000000'];

  window.harnessSnipStart = async function () {
    if (S) return;   // 已在截图态
    let j;
    try { j = await (await fetch('/api/snip/grab', {method: 'POST'})).json(); }
    catch (e) { showBanner('抓屏失败：' + e, 3000, true); return; }
    if (!j.ok) { showBanner('抓屏失败（子进程未产出截图）', 3000, true); return; }
    const img = new Image();
    img.src = '/api/snip/img?v=' + Date.now();
    // onload 标准路径（decode() 在部分环境/无头下 pending 卡死）；3s 兜底
    await new Promise((res) => {
      if (img.complete && img.naturalWidth) return res();
      img.onload = res; img.onerror = res;
      setTimeout(res, 3000);
    });
    if (!img.naturalWidth) { showBanner('底图加载失败', 3000, true); return; }

    const iw = img.naturalWidth || 1920, ih = img.naturalHeight || 1080;
    const vw = document.documentElement.clientWidth || 1280;
    const vh = document.documentElement.clientHeight || 800;
    const k = Math.min(vw / iw, vh / ih);
    const dw = iw * k, dh = ih * k;   // 显示尺寸（等比，居中）
    const ox = (vw - dw) / 2, oy = (vh - dh) / 2;

    S = { img, iw, ih, k, vw, vh, objs: [], live: null, tool: 'rect',
          color: '#e34c4c', width: Math.max(2, Math.round(3 / k)), sel: null,
          dispRect: (rr) => rr ? {x: ox + rr.x * k, y: oy + rr.y * k, w: rr.w * k, h: rr.h * k}
                               : {x: 0, y: 0, w: 0, h: 0} };

    const root = document.createElement('div');
    root.style.cssText = 'position:fixed;inset:0;z-index:99999;cursor:crosshair';
    root.innerHTML =
      `<img src="${img.src}" style="position:absolute;left:${ox}px;top:${oy}px;width:${dw}px;height:${dh}px;user-select:none">` +
      `<canvas width="${iw}" height="${ih}" style="position:absolute;left:${ox}px;top:${oy}px;width:${dw}px;height:${dh}px">` +
      `<div data-selbox style="display:none;position:absolute;border:2px solid #2c8cff;box-shadow:0 0 0 1px rgba(255,255,255,.55);pointer-events:none">` +
        `<i data-h="nw" style="position:absolute;left:-5px;top:-5px;width:9px;height:9px;background:#2c8cff;border:1px solid #fff;cursor:nwse-resize"></i>` +
        `<i data-h="ne" style="position:absolute;right:-5px;top:-5px;width:9px;height:9px;background:#2c8cff;border:1px solid #fff;cursor:nesw-resize"></i>` +
        `<i data-h="sw" style="position:absolute;left:-5px;bottom:-5px;width:9px;height:9px;background:#2c8cff;border:1px solid #fff;cursor:nesw-resize"></i>` +
        `<i data-h="se" style="position:absolute;right:-5px;bottom:-5px;width:9px;height:9px;background:#2c8cff;border:1px solid #fff;cursor:nwse-resize"></i>` +
      `</div>` +
      `<div data-sizetag style="display:none;position:absolute;background:#2c8cff;color:#fff;font:12px var(--font-mono);padding:1px 6px;border-radius:4px;pointer-events:none"></div>` +
      `<div data-toolbar style="display:none;position:absolute;gap:2px;padding:4px 6px;border-radius:8px;` +
        `background:var(--bg-card,#222);border:1px solid var(--border,#444);box-shadow:0 4px 16px rgba(0,0,0,.4);align-items:center;z-index:1">` +
        _COLORS.map(c => `<i data-color="${c}" style="width:15px;height:15px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.35);margin:0 2px"></i>`).join('') +
        `<span data-w2 style="margin:0 6px 0 4px;cursor:pointer;font:12px sans-serif;color:var(--fg,#eee)">▬</span>` +
        _TOOLS.map(t => `<b data-tool="${t[0]}" style="margin:0 5px;cursor:pointer;font:12px sans-serif;color:var(--fg,#eee);white-space:nowrap">${t[1]}</b>`).join('') +
      `</div>`;
    document.body.appendChild(root);
    S.root = root;
    S.canvas = root.querySelector('canvas');
    S.selBox = root.querySelector('[data-selbox]');
    S.sizeTag = root.querySelector('[data-sizetag]');
    S.toolbar = root.querySelector('[data-toolbar]');
    document.documentElement.style.background = '#000';

    const toInner = (e) => ({   // 指针 → 底图内部原生坐标
      x: Math.max(0, Math.min(iw, (e.clientX - ox) / k)),
      y: Math.max(0, Math.min(ih, (e.clientY - oy) / k)) });

    let drag = null;   // {mode:'new'|'move'|'nw'.., sx,sy, orig}
    root.addEventListener('pointerdown', (e) => {
      if (e.button === 2) { _finish(null); return; }              // 右键取消
      const t = e.target;
      const ip = toInner(e);
      if (t.dataset && t.dataset.tool) {                           // 工具栏点击
        const tl = t.dataset.tool;
        if (tl === 'ok') { _export(); return; }
        if (tl === 'cancel') { _finish(null); return; }
        if (tl === 'undo') { S.objs.pop(); _redraw(); return; }
        S.tool = tl;
        root.querySelectorAll('[data-tool]').forEach(b => b.style.color = '');
        t.style.color = '#2c8cff';
        if (tl === 'text') {
          const txt = prompt('输入标注文字：');
          if (txt) {
            const fs = Math.max(18, Math.round(26 / k));
            S.objs.push({t: 'text', x1: ip.x, y1: ip.y, x2: ip.x, y2: ip.y, txt, fs, color: S.color});
            _redraw();
          }
          return;
        }
        return;
      }
      if (t.dataset && t.dataset.color) {
        S.color = t.dataset.color;
        root.querySelectorAll('[data-color]').forEach(c => c.style.outline = '');
        t.style.outline = '2px solid #2c8cff';
        return;
      }
      if (t.dataset && t.dataset.w2 !== undefined) {
        S.width = S.width > 3 / k ? Math.max(2, Math.round(3 / k)) : Math.max(2, Math.round(7 / k));
        return;
      }
      if (S.sel && ['rect', 'arrow', 'pen'].includes(S.tool)) {    // 选区内落笔
        drag = {mode: 'draw', sx: ip.x, sy: ip.y};
        if (S.tool === 'pen') S.live = {t: 'pen', pts: [[ip.x, ip.y]], color: S.color, width: S.width};
        else S.live = {t: S.tool, x1: ip.x, y1: ip.y, x2: ip.x, y2: ip.y, color: S.color, width: S.width};
        return;
      }
      const h = t.dataset && t.dataset.h;
      if (h && S.sel) {
        drag = {mode: h, sx: ip.x, sy: ip.y, orig: {...S.sel}};
      } else if (S.sel && _inSel(ip)) {
        drag = {mode: 'move', sx: ip.x, sy: ip.y, orig: {...S.sel}};
      } else {
        drag = {mode: 'new', sx: ip.x, sy: ip.y};
        S.sel = {x: ip.x, y: ip.y, w: 0, h: 0};
        S.selBox.style.display = 'none'; S.sizeTag.style.display = 'none'; S.toolbar.style.display = 'none';
      }
      try { root.setPointerCapture && root.setPointerCapture(e.pointerId); } catch (_) {}
    });
    root.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const ip = toInner(e);
      if (drag.mode === 'new') {
        S.sel.x = Math.min(drag.sx, ip.x); S.sel.y = Math.min(drag.sy, ip.y);
        S.sel.w = Math.abs(ip.x - drag.sx); S.sel.h = Math.abs(ip.y - drag.sy);
        _syncSelBox();
      } else if (drag.mode === 'move') {
        S.sel.x = Math.max(0, Math.min(iw - drag.orig.w, drag.orig.x + ip.x - drag.sx));
        S.sel.y = Math.max(0, Math.min(ih - drag.orig.h, drag.orig.y + ip.y - drag.sy));
        _syncSelBox();
      } else if (drag.mode === 'draw') {
        if (S.tool === 'pen') S.live.pts.push([ip.x, ip.y]);
        else { S.live.x2 = ip.x; S.live.y2 = ip.y; }
        _redraw();
      } else {   // 8 向柄之一（四角）
        const o = drag.orig;
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (drag.mode.includes('n')) y1 = ip.y;
        if (drag.mode.includes('s')) y2 = ip.y;
        if (drag.mode.includes('w')) x1 = ip.x;
        if (drag.mode.includes('e')) x2 = ip.x;
        S.sel = {x: Math.min(x1, x2), y: Math.min(y1, y2),
                 w: Math.abs(x2 - x1), h: Math.abs(y2 - y1)};
        _syncSelBox();
      }
    });
    root.addEventListener('pointerup', () => {
      if (!drag) return;
      if (drag.mode === 'draw' && S.live) { S.objs.push(S.live); S.live = null; _redraw(); }
      if (drag.mode !== 'draw' && S.sel) {
        if (S.sel.w < 6 || S.sel.h < 6) {   // 过小视为误触：清选区重来
          S.sel = null;
          S.selBox.style.display = 'none'; S.sizeTag.style.display = 'none';
          S.toolbar.style.display = 'none';
        } else {
          S.sizeTag.style.display = '';
          _syncSelBox();
        }
      }
      drag = null;
    });
    function _inSel(p) {
      const r = S.sel; return r && p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
    }
    S.keyCap = (e) => {
      if (e.code === 'Escape') { e.preventDefault(); e.stopPropagation(); _finish(null); }
      else if (e.code === 'Enter') { e.preventDefault(); e.stopPropagation(); if (S && S.sel) _export(); }
    };
    document.addEventListener('keydown', S.keyCap, true);
  };
})();
