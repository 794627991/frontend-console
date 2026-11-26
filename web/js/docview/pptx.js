// ============================================================
// docview / pptx —— 演示文稿渲染器（包装 @aiden0z/pptx-renderer）
//
// 引擎在 office-engine.js 里已接好（Step 1，用 PptxViewer 的列表模式）。
// 这里补 docview 需要的东西：每张幻灯片 data-at、幻灯片/形状定位、大纲。
//
// 6.1.6 说的是用底层接口（parseZipLazyMedia + renderSlide）以便在每张上挂
// 覆盖层、做形状高亮。Step 1 已经用 PptxViewer 跑通了列表渲染，先把能用的
// 那条留住；形状级高亮属于增强项，用「幻灯片级定位 + 形状文本定位」近似。
// ============================================================

import { pptxOutline, pptxUnits } from './outline.js';
import { findTextRange } from './hl.js';

export function createPptxInstance(inst) {
  let viewer = null, host = null, slides = [];
  let _zoomPct = 100, _zoomTimer = 0;

  /** 找到第 n 张幻灯片的 DOM 容器。库的列表模式按序渲染 .slide-frame 类节点。 */
  const slideEl = (n) => {
    if (!host) return null;
    const els = host.querySelectorAll('.pptx-slide, .slide-frame, [data-slide-index]');
    if (els.length >= n) return els[n - 1];
    return host.querySelectorAll('.pptx-slide, .slide-frame')[n - 1] || null;
  };

  return {
    async parse(bytes) {
      // PPT 的文本要解析后才拿得到；引擎渲染完在 render 里补
      slides = [];
      return { outline: [], units: [] };
    },

    async render(root, i) {
      const eng = window.OfficeEngine;
      if (!eng || typeof eng.openPptx !== 'function') throw new Error('渲染引擎未加载（office-engine.js）');
      host = document.createElement('div');
      host.className = 'dv-pptx-host';
      root.appendChild(host);
      viewer = await eng.openPptx(host, i.buf, {
        onDone: () => this._tagSlides(i),
      });
      this._tagSlides(i);
    },

    /** 给每张幻灯片挂 data-at，并从中提取大纲/units。 */
    _tagSlides(i) {
      if (!host) return;
      const els = [...host.querySelectorAll('.pptx-slide, .slide-frame, .pptx-viewer-slide')];
      if (!els.length) {
        // 结构不认识的版本：只给整体挂一个
        return;
      }
      const list = els.map((el, n) => {
        el.setAttribute('data-at', 'slide:' + (n + 1));
        const text = (el.innerText || el.textContent || '').replace(/\n{2,}/g, '\n').trim();
        return { text };
      });
      slides = list;
      i.info.outline = pptxOutline(list);
      i.info.units = pptxUnits(list);
      if (i._emit) i._emit('outline', i.info.outline);
    },

    goTo(loc) {
      const n = loc.slide || (loc.slides && loc.slides.from);
      if (!n) return false;
      this._clearRange();
      if (loc.slides) {
        for (let k = loc.slides.from; k <= loc.slides.to; k += 1) {
          const el = slideEl(k);
          if (el) el.classList.add('dv-range');
        }
      }
      const el = slideEl(n);
      if (!el) return false;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return true;
    },

    revealTarget(loc, quote) {
      const n = loc.slide || (loc.slides && loc.slides.from);
      if (!n) return null;
      const el = slideEl(n);
      if (!el) return null;
      if (quote) {
        const r = findTextRange(el, quote, false);
        if (r) return { el, range: r };
      }
      return { el };
    },

    /** 只判定锚点对应的幻灯片是否在场（不滚动、不高亮）。 */
    probe(loc) {
      const n = loc.slide || (loc.slides && loc.slides.from);
      return !!n && !!slideEl(n);
    },

    findAll(quote) {
      const q = String(quote || '').trim();
      if (!q) return [];
      const out = [];
      for (const el of host ? host.querySelectorAll('[data-at^="slide:"]') : []) {
        const r = findTextRange(el, q, true);
        if (r) out.push(r);
      }
      return out;
    },

    position() {
      if (!host) return '';
      const els = [...host.querySelectorAll('[data-at^="slide:"]')];
      if (!els.length) return '';
      const hr = host.getBoundingClientRect();
      const mid = hr.top + hr.height / 2;
      for (let k = 0; k < els.length; k += 1) {
        const r = els[k].getBoundingClientRect();
        if (mid >= r.top && mid < r.bottom) return '第 ' + (k + 1) + ' 张，共 ' + els.length + ' 张';
      }
      return '';
    },

    resize() { },

    /** Ctrl+滚轮缩放（2026-11-26 用户令：「正常 word、pdf 都应该有 ctrl+滚轮放大」）。
     *  库的 setZoom 接受百分比，且是叠在 fitMode='contain' 的适宽比例之上
     *  （源码：`(containerWidth / presentation.width) * zoomFactor`），所以语义
     *  与 docx 的「相对适宽倍率」一致。
     *  **必须节流**：setZoom 内部走 queueRender，每格滚轮都触发一次整份重渲染，
     *  连续滚动会排成长队。 */
    zoom(delta) {
      if (!delta) return _zoomPct;
      _zoomPct = Math.min(300, Math.max(50, _zoomPct + delta * 10));
      clearTimeout(_zoomTimer);
      _zoomTimer = setTimeout(() => {
        if (viewer && typeof viewer.setZoom === 'function') {
          try { viewer.setZoom(_zoomPct); } catch (_) {}
        }
      }, 120);
      return _zoomPct;
    },

    _clearRange() {
      if (host) host.querySelectorAll('.dv-range').forEach(el => el.classList.remove('dv-range'));
    },

    destroy() {
      clearTimeout(_zoomTimer);
      try { if (viewer && viewer.dispose) viewer.dispose(); } catch (_) {}
      try { if (host) host.innerHTML = ''; } catch (_) {}
      viewer = null; host = null; slides = []; _zoomPct = 100; _zoomTimer = 0;
    },
  };
}
