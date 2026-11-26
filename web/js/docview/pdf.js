// ============================================================
// docview / pdf —— PDF 渲染器
//
// 设计文档 6.1.4：**不重写**，把 office-viewer.js 的 PDF Pro 逻辑迁过来，
// 只做两类改动——状态从 conn 搬到实例；补上定位与高亮（data-at / goTo /
// quote 文字层）。A01：pdf.js 链保持现有库不动，不升级、不搬沙箱。
//
// 关键行为照 4.2.2：
//   · 每页一个占位 .dv-page[data-at="page:N"]
//   · 懒渲染 IntersectionObserver，rootMargin 600px
//   · 缩放时清空所有页重画，旧结果丢弃
//   · quote：等目标页文字层就绪，最多重试 5 次，再 findTextRange
//   · **文字层用 normalizeCjkCompat**（pdf.js 的 CJK 兼容字符还原），否则
//     中文引文匹配不上
// ============================================================

import { esc } from './esc.js';
import { pdfOutline, pdfUnits } from './outline.js';
import { findTextRange } from './hl.js';

const LAZY_MARGIN = '600px 0px';

export function createPdfInstance(inst) {
  let doc = null, pagesEl = null;
  let zoomScale = 1.0;
  let pageEls = [], rendered = new Set(), textLayers = new Map();
  /** 每页纯文本（parse 时一次取好）。查找靠它定位命中页——
   *  文字层是懒建的，没渲染的页根本没有 DOM 可搜（2026-11-26 用户实测：
   *  「点查找也不能跳转」）。 */
  let pageTexts = [];
  let io = null, destroyed = false;

  const gotoPage = (n) => {
    const el = pageEls[n - 1];
    if (!el) return false;
    const pr = pagesEl.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    pagesEl.scrollTop += er.top - pr.top - 6;
    return true;
  };

  const renderPage = async (n) => {
    if (destroyed || rendered.has(n) || !doc) return;
    rendered.add(n);
    const el = pageEls[n - 1];
    if (!el) return;
    try {
      const page = await doc.getPage(n);
      const vp = page.getViewport({ scale: zoomScale });
      const canvas = document.createElement('canvas');
      canvas.className = 'dv-pdf-canvas';
      canvas.width = Math.floor(vp.width);
      canvas.height = Math.floor(vp.height);
      canvas.style.maxWidth = '100%';
      // 先挂 DOM 再 render（VMware 虚拟桌面上 detached canvas 的 2D context 会挂起）
      el.innerHTML = '';
      el.appendChild(canvas);
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('无法获取 canvas 2D 上下文');
      await page.render({ canvasContext: ctx, viewport: vp }).promise;
      if (!canvas.isConnected) return;   // 期间缩放过，本任务已过期
      // 文字层（给 quote 与搜索用，透明覆盖）
      await buildTextLayer(page, vp, el, n);
      const label = document.createElement('div');
      label.className = 'dv-pdf-label';
      label.textContent = n + ' / ' + doc.numPages;
      el.appendChild(label);
      el.style.minHeight = Math.round(vp.height) + 'px';
    } catch (e) {
      if (!el.querySelector('canvas')) {
        el.innerHTML = '<div class="office-err">第 ' + n + ' 页渲染失败</div>';
        rendered.delete(n);
      }
    }
  };

  const buildTextLayer = async (page, vp, el, n) => {
    try {
      const tc = await page.getTextContent();
      const layer = document.createElement('div');
      layer.className = 'dv-pdf-text';
      const spans = [];
      for (const item of tc.items) {
        const str = normalizeCompat(String(item.str || ''));
        if (!str.trim()) continue;
        const m = pdfjsLib.Util.transform(vp.transform, item.transform);
        const left = m[4], top = m[5] - (item.height || 0) * zoomScale * 0.8;
        const sp = document.createElement('span');
        sp.textContent = str + ' ';
        sp.style.left = left + 'px';
        sp.style.top = top + 'px';
        sp.style.fontSize = ((item.height || 10) * zoomScale) + 'px';
        layer.appendChild(sp);
        spans.push(str);
      }
      layer.style.width = Math.round(vp.width) + 'px';
      layer.style.height = Math.round(vp.height) + 'px';
      el.appendChild(layer);
      textLayers.set(n, { el: layer, text: spans.join('') });
    } catch (_) { /* 文字层失败不挡渲染 */ }
  };

  return {
    async parse(bytes) {
      if (typeof pdfjsLib === 'undefined') throw new Error('pdf.js 未加载');
      doc = await pdfjsLib.getDocument({ data: bytes }).promise;
      const total = doc.numPages;
      let toc = null;
      try { toc = await doc.getOutline(); } catch (_) {}
      const outline = pdfOutline(toc, total);

      // units：全文（按页）——read_document 用。逐页懒取，这里全取一次并缓存
      const pages = [];
      for (let n = 1; n <= total; n += 1) {
        try {
          const p = await doc.getPage(n);
          const tc = await p.getTextContent();
          const txt = tc.items.map(it => normalizeCompat(String(it.str || ''))).join(' ')
            .replace(/\s+/g, ' ').trim();
          pages.push({ page: n, text: txt });
        } catch (_) { pages.push({ page: n, text: '' }); }
      }
      pageTexts = pages;
      return { outline, units: pdfUnits(pages), total };
    },

    async render(root, i) {
      pagesEl = document.createElement('div');
      pagesEl.className = 'dv-pdf-pages';
      root.appendChild(pagesEl);
      const total = doc.numPages;
      // 预估页高防滚动跳动
      let h = 800, w = 600;
      try {
        const vp = (await doc.getPage(1)).getViewport({ scale: 1 });
        h = vp.height; w = vp.width;
      } catch (_) {}
      for (let n = 1; n <= total; n += 1) {
        const div = document.createElement('div');
        div.className = 'dv-page';
        div.setAttribute('data-at', 'page:' + n);
        div.style.minHeight = Math.round(h * zoomScale) + 'px';
        pagesEl.appendChild(div);
        pageEls.push(div);
      }
      if (typeof IntersectionObserver !== 'undefined') {
        io = new IntersectionObserver((entries) => {
          for (const e of entries) if (e.isIntersecting) renderPage(+e.target.dataset.at.split(':')[1]);
        }, { root: pagesEl, rootMargin: LAZY_MARGIN });
        pageEls.forEach(el => io.observe(el));
      }
      await renderPage(1);
      this._w = w; this._h = h;
    },

    goTo(loc) {
      if (loc.page) return gotoPage(loc.page);
      if (loc.pages) { this._clearRange(); for (let n = loc.pages.from; n <= loc.pages.to; n += 1) {
        const el = pageEls[n - 1]; if (el) el.classList.add('dv-range'); } return gotoPage(loc.pages.from); }
      return false;
    },

    revealTarget(loc, quote) {
      const n = loc.page || (loc.pages && loc.pages.from);
      if (!n) return null;
      const el = pageEls[n - 1];
      if (!el) return null;
      if (quote) {
        // 等文字层就绪，最多 5 次（4.2.2）
        const tryFind = (tries) => {
          const tl = textLayers.get(n);
          if (tl) {
            const r = findTextRange(tl.el, quote, false);
            return r ? { el, range: r } : { el };
          }
          if (tries > 0) { setTimeout(() => tryFind(tries - 1), 200); }
          return { el };
        };
        return tryFind(5);
      }
      return { el };
    },

    /** 只判定锚点有没有对应页（不滚动、不高亮）。 */
    probe(loc) {
      const n = loc.page || (loc.pages && loc.pages.from);
      if (!n) return false;
      return n >= 1 && n <= pageEls.length;
    },

    /** 查找（异步）：靠每页纯文本找命中页 → 渲染该页 → 从文字层取 Range。
     *  同步的 findAll 在懒渲染的 PDF 上几乎必然空手而归（页面还没画，
     *  没有文字层可搜），core 优先调本方法。 */
    async findAsync(quote) {
      const q = String(quote || '').trim();
      if (!q || !doc) return [];
      const low = q.toLowerCase();
      const hitPages = [];
      for (const p of pageTexts) {
        if (p.text && p.text.toLowerCase().includes(low)) hitPages.push(p.page);
      }
      if (!hitPages.length) return [];
      // 只保证第一处命中的页渲染出来（其余页按需，用户按「下」时再依次拉）
      for (const n of hitPages) {
        if (!rendered.has(n)) await renderPage(n);
      }
      const out = [];
      for (const n of hitPages) {
        const tl = textLayers.get(n);
        if (!tl) continue;
        const r = findTextRange(tl.el, quote, true);
        if (r) out.push(r);
      }
      return out;
    },

    /** 查找：先查文字层（精确），再退到整页文本。 */
    findAll(quote) {
      const q = String(quote || '').trim();
      if (!q) return [];
      const out = [];
      // 文字层可能还没建（懒渲染）——先按页扫整页文本，命中的页取文字层 Range；
      // 没有文字层就退到至少把用户送到那一页
      for (const [n, tl] of textLayers) {
        const r = findTextRange(tl.el, quote, true);
        if (r) out.push(r);
      }
      if (!out.length) {
        for (let n = 1; n <= pageEls.length; n += 1) {
          // 触发该页渲染，下次查找就能命中
          renderPage(n);
        }
      }
      return out;
    },

    position() {
      if (!pagesEl || !pageEls.length) return '';
      const mid = pagesEl.scrollTop + pagesEl.clientHeight / 2;
      for (let i = 0; i < pageEls.length; i += 1) {
        const el = pageEls[i];
        const top = el.offsetTop, bot = top + el.offsetHeight;
        if (mid >= top && mid < bot) return '第 ' + (i + 1) + ' 页，共 ' + pageEls.length + ' 页';
      }
      return '';
    },

    /** 缩放。delta=0 查询。返回百分比。 */
    zoom(delta) {
      if (!delta) return zoomScale * 100;
      const next = Math.min(3, Math.max(0.25, zoomScale + delta * 0.15));
      if (Math.abs(next - zoomScale) < 0.001) return zoomScale * 100;
      zoomScale = next;
      // 清空所有页重画，旧结果丢弃（4.2.2）
      rendered.clear();
      textLayers.clear();
      for (const el of pageEls) { el.innerHTML = ''; el.style.minHeight = ''; }
      for (let n = 1; n <= pageEls.length; n += 1) {
        const visible = n <= 2;   // 立刻重画前两页，其余交给观察器
        if (visible) renderPage(n);
        else if (io) { io.unobserve(pageEls[n - 1]); io.observe(pageEls[n - 1]); }
      }
      return zoomScale * 100;
    },

    resize() { },

    _clearRange() { for (const el of pageEls) el.classList.remove('dv-range'); },

    destroy() {
      destroyed = true;
      try { if (io) io.disconnect(); } catch (_) {}
      io = null;
      try { if (doc && doc.destroy) doc.destroy(); } catch (_) {}
      doc = null; pagesEl = null; pageEls = []; rendered.clear(); textLayers.clear();
    },
  };
}

// ------------------------------------------------------------------
// pdf.js 的 CJK 兼容字符还原（ZCode 的 normalizeCjkCompat，domain/cjk.ts:30-32）
//
// 为什么必须做：pdf.js 从某些 PDF 里取出的字符是「CJK 兼容形式」（U+F900–U+FAFF）
// 或全角字符，视觉上与常规汉字/ASCII 一样，但码点不同——直接拿去和 AI 写的
// 引文比对永远匹配不上。NFKC 正是干这个的标准归一化，浏览器原生支持，
// 比手工映射表可靠（手工表永远漏字）。
// ------------------------------------------------------------------

export function normalizeCompat(s) {
  if (!s) return '';
  try {
    return String.prototype.normalize ? s.normalize('NFKC') : s;
  } catch (_) {
    return s;
  }
}
