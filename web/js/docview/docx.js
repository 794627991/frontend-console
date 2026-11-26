// ============================================================
// docview / docx —— Word 渲染器
//
// 渲染沿用 docx-preview（A01：docx 链不换库），增量是**定位对齐**：
//   · parse：解 word/document.xml 抽块（docx-parse.js），顺带抽 styles.xml
//            的 outlineLvl 出大纲
//   · render：docx-preview 渲染，然后按文本把 p:N / t:N 写到元素上
//   · goTo：查 [data-at="p:N"]，滚动算容器 scrollTop；范围加高亮类
//   · quote：在目标块内 findTextRange
//
// **p:N 不是靠数元素得到的，是靠文本对齐**（4.2.1 第 3 步）。docx-preview
// 渲染出来的元素数不等于段落数（页眉页脚、分页产生的空壳、目录域都会多出来），
// 所以必须拿解析侧的块文本去前缀匹配渲染侧的文本。
// ============================================================

import { normalize, truncate } from './text.js';
import { parseBody, styleLevels, isBlankBlock } from './docx-parse.js';
import { docxOutline, docxUnits } from './outline.js';
import { findTextRange } from './hl.js';

const RENDER_OPTS = {
  className: 'dv-docx',
  inWrapper: true,
  breakPages: true,
  ignoreLastRenderedPageBreak: true,
  experimental: true,
  renderHeaders: true,
  renderFooters: true,
  renderFootnotes: true,
  renderEndnotes: true,
  renderComments: false,
  renderChanges: false,
  renderAltChunks: false,
  useBase64URL: false,   // a449：blob URL，否则 52 图内联 base64 多 33% 且主线程解码
};

const MAX_UNZIPPED = 512 * 1024 * 1024;   // 4.1：解压后 512MiB 上限

/** 解 zip 并读两处 XML。返回 { docXml, stylesXml, bytes }。 */
async function unzip(buf) {
  if (typeof JSZip === 'undefined') throw new Error('缺少 JSZip（jszip.min.js 未加载）');
  const zip = await JSZip.loadAsync(buf);
  // 解压后体积检查（对照 ooxml.ts:91-111）
  let total = 0;
  zip.forEach((_, f) => { total += (f && f._data && f._data.uncompressedSize) || 0; });
  if (total > MAX_UNZIPPED) throw new Error('文档解压后超过 512MB，拒绝打开');
  const docFile = zip.file('word/document.xml');
  if (!docFile) throw new Error('不是有效的 .docx（缺 word/document.xml）');
  const docXml = await docFile.async('string');
  const stFile = zip.file('word/styles.xml');
  const stylesXml = stFile ? await stFile.async('string') : '';
  return { docXml, stylesXml };
}

export function createDocxInstance(inst) {
  let containerEl = null, scrollerEl = null;
  // 用户缩放倍率（相对「适宽」，1 = 正好铺满容器）。Ctrl+滚轮改这个值，
  // 与适宽比例相乘后写进 transform——两者互不覆盖，窗口变了仍保持用户意图。
  let _userZoom = 1;

  /** 把目标描述解析成实际元素。**闭包读 containerEl**——不能靠 this
   *（渲染器对象是字面量，this 在这里不可靠，且 core 调用 goTo 时 this 是渲染器
   * 对象、不是实例，容易两处不一致）。 */
  const targetEls = (targets) => {
    const out = [];
    if (!containerEl) return out;
    for (const t of targets) {
      if (t.kind === 'p') {
        const el = containerEl.querySelector('[data-at="p:' + t.n + '"]');
        if (el) out.push(el);
      } else if (t.kind === 't') {
        const el = containerEl.querySelector('[data-at="t:' + t.n + '"]');
        if (!el) continue;
        if (t.cell) {
          const tr = el.rows[t.cell.row - 1];
          const td = tr && tr.cells[t.cell.col - 1];
          out.push(td || el);
        } else out.push(el);
      }
    }
    return out;
  };

  return {
    async parse(bytes) {
      const { docXml, stylesXml } = await unzip(bytes);
      const parser = new DOMParser();
      const doc = parser.parseFromString(docXml, 'application/xml');
      if (doc.querySelector('parsererror')) throw new Error('document.xml 解析失败（文件可能已损坏）');
      const styles = stylesXml ? parser.parseFromString(stylesXml, 'application/xml') : null;
      const levels = styles ? styleLevels(styles) : new Map();
      const { blocks, paragraphs, tables } = parseBody(doc, levels);

      // 大纲：有 outlineLvl 的块
      const heads = blocks.filter(b => b.level >= 1 && b.level <= 6)
        .map(b => ({ at: b.at, text: b.text, level: b.level }));
      const outline = docxOutline(heads);

      // units：p: 块进正文，t: 块也进（AI 要能读到表格内容）
      const units = docxUnits(blocks.map(b => ({
        at: b.at,
        full: isBlankBlock(b) ? '(empty)' : b.full,
      })));

      return { outline, units, blocks, paragraphs, tables };
    },

    async render(root, i) {
      if (typeof docx === 'undefined') throw new Error('docx-preview 库未加载');
      scrollerEl = root;
      // 渲染区：docx-preview 会自己塞 .docx-wrapper > section.docx
      containerEl = document.createElement('div');
      containerEl.className = 'dv-docx-host';
      root.appendChild(containerEl);
      await docx.renderAsync(i.buf, containerEl, null, RENDER_OPTS);
      this._align(document, i.info.blocks || []);
      // 首帧就按可用宽度缩放一次（等库把 section 插进 DOM 后量才有值）
      this.resize();
    },

    /**
     * 文本对齐：把 blocks 与渲染出的元素按前缀匹配，命中的写 data-at。
     * 规则照 align.ts:10-80（在本层实现，见方法内注释）。
     */
    _align(doc, blocks) {
      if (!containerEl || !blocks.length) return;
      // 收集渲染侧的可对齐元素：section.docx > article 下的 P/H1-6/TABLE
      const sections = containerEl.querySelectorAll('section.dv-docx, section.docx');
      const scope = sections.length ? sections : [containerEl];
      const els = [];
      for (const s of scope) {
        for (const a of s.querySelectorAll('article')) {
          for (const el of a.querySelectorAll('p, h1, h2, h3, h4, h5, h6, table')) els.push(el);
        }
        // 没有 article 包裹的版本（库版本差异）
        if (!s.querySelector('article')) {
          for (const el of s.querySelectorAll('p, h1, h2, h3, h4, h5, h6, table')) els.push(el);
        }
      }
      if (!els.length) return;

      const keyOf = (el) => {
        // 表格的文本按 cell 拼，段落用 textContent
        if (el.tagName === 'TABLE') {
          return normalize([...el.rows].map(r => [...r.cells].map(c => c.textContent).join('\t')).join('\n'))
            .toLowerCase();
        }
        return normalize(el.textContent).toLowerCase();
      };
      const elText = els.map(keyOf);

      let k = 0;   // 当前对齐到 blocks 的哪个下标
      for (let i = 0; i < els.length && k < blocks.length; i += 1) {
        const text = elText[i];
        // 在前向 6 个块内找（渲染器会多出元素，靠这个重新同步）
        let matched = null, mIdx = -1;
        const lim = Math.min(blocks.length, k + 6);
        for (let j = k; j < lim; j += 1) {
          const key = normalize(blocks[j].text).toLowerCase();
          if (!key && !text) { matched = blocks[j]; mIdx = j; break; }
          if (!key) continue;
          const probe = truncate(text, key.length);
          if (key === text || (text && key.startsWith(text)) || (key.length >= 300 && probe === key)) {
            matched = blocks[j]; mIdx = j; break;
          }
        }
        if (matched) {
          els[i].setAttribute('data-at', matched.at);
          k = mIdx + 1;
        }
      }
    },

    goTo(loc, i) {
      const targets = this._targetsOf(loc);
      if (!targets.length) return false;
      // 范围高亮
      this._clearRange();
      const els = targetEls(targets);
      if (!els.length) return false;
      if (els.length > 1) els.forEach(el => el.classList.add('dv-range'));
      const first = els[0];
      const body = i.bodyEl;
      const br = body.getBoundingClientRect();
      const er = first.getBoundingClientRect();
      body.scrollTop += er.top - br.top - 8;
      return true;
    },

    revealTarget(loc, quote) {
      const targets = this._targetsOf(loc);
      if (!targets.length) return null;
      const el = targetEls(targets)[0];
      if (!el) return null;
      if (quote) {
        const r = findTextRange(el, quote, false);
        if (r) return { el, range: r };
      }
      // quote 没命中就整块加高亮（4.2.1 最后一条）
      return { el };
    },

    /** 只判定锚点有没有对应元素（不滚动、不高亮）。 */
    probe(loc) {
      const targets = this._targetsOf(loc);
      if (!targets.length) return false;
      return targetEls(targets).length > 0;
    },

    /** loc → 目标选择器描述数组（p:N 或 t:N 或 t:N/rRcC）。 */
    _targetsOf(loc) {
      if (loc.paragraph) return [{ kind: 'p', n: loc.paragraph }];
      if (loc.paragraphs) {
        const out = [];
        for (let n = loc.paragraphs.from; n <= loc.paragraphs.to; n += 1) out.push({ kind: 'p', n });
        return out;
      }
      if (loc.table) return [{ kind: 't', n: loc.table, cell: loc.cell || null }];
      return [];
    },

    _clearRange() {
      if (!containerEl) return;
      containerEl.querySelectorAll('.dv-range').forEach(el => el.classList.remove('dv-range'));
    },

    findAll() { return []; },   // docx 的查找走 core 的 DOM 通用路径

    position() { return ''; },   // 6.2.7：docx 不显示位置

    /**
     * 容器宽度变化 / 首次渲染后，把白页按可用宽度整体缩放。
     * docx-preview 输出的 section 固定 A4 物理宽度（≈794px）——
     * 分屏只有三四百像素宽时，不缩放就是「只见右半边」或「左侧一片空白」。
     *
     * **必须先量后写**：`offsetWidth` 在 transform 之后**不变**（transform 不
     * 改布局盒），所以重复调用 install 不会累乘。但如果拿
     * getBoundingClientRect 去量就会越缩越小——这里刻意用 offsetHeight/Width。
     */
    /** 适宽与用户缩放叠加。`_userZoom` 是相对「适宽」的倍率（1 = 正好铺满）。
     *  Ctrl+滚轮改的就是它（见 zoom）。 */
    resize() {
      if (!containerEl) return;
      const secs = containerEl.querySelectorAll('.dv-docx-wrapper > section');
      if (!secs.length) return;
      const avail = containerEl.clientWidth;
      if (avail <= 0) return;
      const fitScale = Math.min(1, (avail - 24) / 794);
      const scale = fitScale * _userZoom;
      // 只有「比原尺寸小」才需要缩：fit 类负责左对齐 + 收掉留白。
      // 放大（scale > 1）时**不能**套 fit 类——那条 CSS 是 overflow-x: hidden，
      // 放大后的右半边会被裁掉且滚不到。
      const shrink = scale < 0.999;
      const grow = scale > 1.001;
      containerEl.classList.toggle('dv-docx-fit', shrink);
      containerEl.classList.toggle('dv-docx-grow', grow);
      // transform 不改布局盒：放大后视觉变宽，但父元素仍按 794 排，横向滚不动。
      // 给 wrapper 显式撑出缩放后的宽度，滚动条才有意义。
      const wrap = containerEl.querySelector('.dv-docx-wrapper');
      if (wrap) wrap.style.minWidth = grow ? Math.ceil(794 * scale + 24) + 'px' : '';
      secs.forEach(s => {
        if (!shrink && !grow) {
          s.style.transform = '';
          s.style.marginBottom = '';
          return;
        }
        // offsetHeight 同样不受 transform 影响 → 每次算同一份值，幂等
        const h = s.offsetHeight || 1123;
        s.style.transform = 'scale(' + scale + ')';
        s.style.marginBottom = Math.round(12 - h * (1 - scale)) + 'px';
      });
    },

    /** Ctrl+滚轮：delta 为 ±1，0 表示查询。返回相对「适宽」的百分比。
     *  **步进用加法（±10%/格）不用乘法**：2026-11-26 实测过一版「按真实倍率
     *  等比缩放」（100 = A4 原尺寸、每格 ×1.15），用户体感不如这一版平滑——
     *  「这个回退，我体感不如最开始平铺开好」。等比在窄分屏里起步太小、加速
     *  太猛；加法每格增量一致，滚起来才是稳的。 */
    zoom(delta) {
      if (delta) {
        _userZoom = Math.min(3, Math.max(0.5, _userZoom + delta * 0.1));
        this.resize();
      }
      return _userZoom * 100;
    },

    destroy() {
      // docx-preview 会挂若干事件；清空容器并断开引用即可（不碰库私有成员）
      try { if (containerEl) containerEl.innerHTML = ''; } catch (_) {}
      containerEl = null; scrollerEl = null;
    },
  };
}
