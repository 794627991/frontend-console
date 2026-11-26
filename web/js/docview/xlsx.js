// ============================================================
// docview / xlsx —— 表格渲染器（包装 @extend-ai/react-xlsx）
//
// 引擎本身在 office-engine.js 里已经接好了（Step 1）。这里只做 docview 需要
// 的那几件：大纲（每表一条）、表名/范围的定位、单元格锚点、位置提示。
//
// 重要（6.1.5、4.2.4）：**网格是 canvas，做不了 quote 高亮**，ZCode 也做不了。
// search_document 在 xlsx 上返回 Sheet!A1，定位到那个单元格就算完成。
// ============================================================

import { esc } from './esc.js';
import { xlsxOutline, xlsxUnits } from './outline.js';
import { formatCell } from './anchor.js';

export function createXlsxInstance(inst) {
  let viewer = null, host = null, sheets = [];
  let activeSheet = '';

  const ctrl = () => viewer && viewer.controller;

  /** 当前表信息：名称 + 使用范围。控制器只给单格接口，范围得自己推。 */
  const sheetInfo = () => {
    const c = ctrl();
    if (!c) return sheets;
    try {
      const list = c.sheets || c.workbookSheets || [];
      const out = list.map((s) => {
        const name = s.name || s.sheetName || '';
        const nj = s.name || '';
        return { name: nj || name, hidden: !!s.hidden, empty: false };
      });
      if (out.length) return out;
    } catch (_) {}
    return sheets;
  };

  return {
    async parse(bytes) {
      // 引擎解析要等 viewer 起来；大纲在 render 之后再补（见 _syncOutline）
      sheets = [];
      return { outline: [], units: [] };
    },

    async render(root, i) {
      const eng = window.OfficeEngine;
      if (!eng || typeof eng.openXlsx !== 'function') throw new Error('渲染引擎未加载（office-engine.js）');
      host = document.createElement('div');
      host.className = 'dv-xlsx-host';
      root.appendChild(host);
      viewer = await eng.openXlsx(host, i.buf, {});
      if (document.body.classList.contains('light')) {
        try { viewer.setOptions && viewer.setOptions({ isDark: false }); } catch (_) {}
      }
      this._syncOutline(i);
    },

    /** 大纲从控制器取（引擎就绪后才有）。 */
    _syncOutline(i) {
      const list = sheetInfo();
      if (!list.length) return;
      const cellText = { from: formatCell, to: formatCell };
      const outline = xlsxOutline(list, cellText);
      i.info.outline = outline;
      i.info.units = xlsxUnits(list.map(s => ({ name: s.name, text: '' })));
      // 通知宿主大纲变了（分屏面板据此更新）
      i._emit && i._emit('outline', outline);
    },

    goTo(loc) {
      const c = ctrl();
      if (!c || !loc.sheet) return false;
      const list = sheetInfo();
      // 表名先精确再忽略大小写（6.1.5）
      let idx = list.findIndex(s => s.name === loc.sheet);
      if (idx < 0) {
        const low = String(loc.sheet).toLowerCase();
        idx = list.findIndex(s => String(s.name).toLowerCase() === low);
      }
      if (idx < 0) return false;
      try {
        if (c.setActiveSheet) c.setActiveSheet(idx);
        else if (c.activateSheet) c.activateSheet(list[idx].name);
      } catch (_) { return false; }
      activeSheet = list[idx].name;
      if (loc.range) {
        const rng = formatCell(loc.range.from) + ':' + formatCell(loc.range.to);
        try {
          if (viewer.setOptions) viewer.setOptions({ highlightedRanges: [rng], autoScrollToHighlightedRanges: true });
        } catch (_) {}
      }
      return true;
    },

    revealTarget(loc) {
      // 网格无 quote 高亮；单元格级定位到那一格
      const el = host;
      if (!this.goTo(loc)) return null;
      return { el };
    },

    /** 只判定表名是否存在（不切表、不高亮）。 */
    probe(loc) {
      if (!loc.sheet) return false;
      const list = sheetInfo();
      const low = String(loc.sheet).toLowerCase();
      return list.some(s => String(s.name) === loc.sheet || String(s.name).toLowerCase() === low);
    },

    findByCell(ref) {
      const c = ctrl();
      if (!c || !c.getCellSnapshotAsync) return null;
      return c.getCellSnapshotAsync(0, ref.row, ref.col);
    },

    findAll() { return []; },   // canvas 网格，无 DOM 文本可搜

    position() {
      const c = ctrl();
      if (!c) return '';
      try {
        const s = c.activeSheet;
        const name = (s && s.name) || activeSheet;
        return name ? ('表：' + name) : '';
      } catch (_) { return ''; }
    },

    resize() {
      try { if (viewer && viewer.reload) { /* 宽度自适应由库自己观察 */ } } catch (_) {}
    },

    /** Ctrl+滚轮缩放。delta=0 查询当前百分比。
     *  引擎的真实接口是 **`controller.setZoomScale(倍率)`**（不是 setZoom）——
     *  实测 index.js 的控制器暴露 `setZoomScale / zoomIn / zoomOut / resetZoom /
     *  zoomScale`，旧的 `c.setZoom(...)` 分支永远走不到，所以 Ctrl+滚轮在
     *  Excel 上完全没反应（2026-11-26 用户实测）。 */
    zoom(delta) {
      const c = ctrl();
      if (!c) return this._z || 100;
      if (!delta) return this._z || (c.zoomScale ? c.zoomScale * 100 : 100);
      this._z = Math.min(300, Math.max(50, (this._z || 100) + delta * 10));
      try {
        if (typeof c.setZoomScale === 'function') c.setZoomScale(this._z / 100);
        else if (typeof c.zoomIn === 'function') (delta > 0 ? c.zoomIn() : c.zoomOut());
      } catch (_) {}
      return this._z;
    },

    destroy() {
      try { if (viewer && viewer.destroy) viewer.destroy(); } catch (_) {}
      try { if (host) host.innerHTML = ''; } catch (_) {}
      viewer = null; host = null; sheets = [];
    },
  };
}
