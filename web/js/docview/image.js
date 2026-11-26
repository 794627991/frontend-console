// ============================================================
// docview / image —— 图片渲染器
//
// 六种位图加 svg 都用 <img>（svg 用 <img> 加载，里面的脚本不会执行，
// 6.1.10）。锚点、定位、搜索都不支持。
// ============================================================

import { imageOutline } from './outline.js';

export function createImageInstance(inst) {
  let url = null, img = null;

  return {
    async parse(bytes) {
      return { outline: imageOutline(inst.path), units: [] };
    },

    async render(root, i) {
      root.classList.add('dv-image-body');
      const wrap = document.createElement('div');
      wrap.className = 'dv-image-wrap';
      img = new Image();
      img.className = 'dv-image';
      img.alt = i.title;
      url = URL.createObjectURL(new Blob([i.buf]));
      const p = new Promise((res) => {
        img.onload = () => res(true);
        img.onerror = () => res(false);
      });
      img.src = url;
      wrap.appendChild(img);
      root.appendChild(wrap);
      const ok = await p;
      if (!ok) throw new Error('图片解码失败（格式不受支持或文件损坏）');
      this._zoomPct = 100;   // 初始适应窗口（CSS max-width/height:100%）
    },

    goTo() { return false; },   // 图片没有锚点
    revealTarget() { return null; },
    position() { return img ? (img.naturalWidth + '×' + img.naturalHeight) : ''; },
    resize() { },

    /**
     * 缩放。delta=0 表示「查询当前值」（core 的 Ctrl+滚轮用它取初值）。
     * 返回百分比：适应窗口态给 100。
     */
    zoom(delta) {
      if (!img) return 100;
      if (!delta) return this._zoomPct || 100;
      this._zoomPct = Math.min(400, Math.max(10, (this._zoomPct || 100) + delta * 25));
      img.classList.add('dv-image-actual');
      img.style.width = this._zoomPct + '%';
      return this._zoomPct;
    },

    destroy() {
      try { if (url) URL.revokeObjectURL(url); } catch (_) {}
      url = null; img = null;
    },
  };
}
