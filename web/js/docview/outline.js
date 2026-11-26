// ============================================================
// docview / outline —— 各格式的块文本、大纲、分页文本产出规则
//
// 译自 ZCode 的 OR/src/adapters/parse/*.ts。这里只放**不依赖 DOM 渲染**的
// 纯逻辑：从解析出来的结构算大纲条目和 units（分页文本单元）。
// 渲染器各自负责 DOM，本文件负责「给 AI 读的那份文本」和「给面板的大纲」。
//
// units 的格式见 4.2.7：每个单元一组「带锚点前缀的行」。read_document 逐块
// 回传，块与块之间的边界就是 unit。
// ============================================================

import { normalize, normalizeKeepLines, truncate } from './text.js';

const BLOCK_TEXT_CAP = 400;   // docx.ts:231-234：对齐用的块文本截到这个长度

/**
 * 从段落/表格的原始文本产出 blocks：[{ at, text }]。
 * text 归一化后截到 400 字符——**只给对齐用**，不给人看。
 */
export function blocksOf(entries) {
  return entries.map(e => ({
    at: e.at,
    text: truncate(normalize(e.text), BLOCK_TEXT_CAP),
    // 保留未截断版本给 units（read_document 输出全量）
    full: normalizeKeepLines(e.text),
  }));
}

/** 大纲条目：{ label, at }；label 为空时用 fallback。 */
function outlineItem(label, at, fallback) {
  const l = String(label == null ? '' : label).trim();
  return { label: l || fallback, at };
}

// ---------- docx ----------

/**
 * docx 大纲。**用 styles.xml 的 outlineLvl**——与面板大纲（office-viewer 的
 * _ovDocxStyleLevels）同一判据，两处必须一致，否则同文档在主页签和分屏里
 * 给出不同的大纲。level 1~6。
 * @param {{at, text, level}[]} headEntries 已按文档序排好的标题块
 */
export function docxOutline(headEntries) {
  return headEntries
    .filter(h => h && h.level >= 1 && h.level <= 6)
    .map(h => ({ label: String(h.text || '').trim().slice(0, 80), at: h.at, level: h.level }));
}

/** docx units：每块一个单元，前缀是它的锚点（4.2.7）。 */
export function docxUnits(blocks) {
  return blocks.map(b => ({
    at: b.at,
    text: b.full != null ? b.full : b.text,
  }));
}

// ---------- pdf ----------

/** pdf 大纲：{ label, at }，label 来自 PDF 的目录（拿不到就用页码）。 */
export function pdfOutline(tocItems, pageCount) {
  const out = [];
  const walk = (items, depth) => {
    for (const it of items || []) {
      const label = String((it && it.title) || '').trim();
      const page = Number(it && it.pageNumber) || 0;
      if (page >= 1 && page <= pageCount) {
        out.push({ label: label || ('第 ' + page + ' 页'), at: 'page:' + page, level: Math.min(6, depth + 1) });
      }
      if (it && it.items && it.items.length) walk(it.items, depth + 1);
    }
  };
  walk(tocItems, 0);
  return out;
}

/** pdf units：每页一个。pages 是 [{ page, text }]。 */
export function pdfUnits(pages) {
  return (pages || []).map(p => ({ at: 'page:' + p.page, text: p.text || '' }));
}

// ---------- pptx ----------

/** pptx 大纲：每张一条，标题取自该页文本的首行。 */
export function pptxOutline(slides) {
  return (slides || []).map((s, i) => {
    const first = normalize(s && s.text).split('\n')[0].trim();
    return { label: first.slice(0, 60) || ('第 ' + (i + 1) + ' 张'), at: 'slide:' + (i + 1), level: 1 };
  });
}

export function pptxUnits(slides) {
  return (slides || []).map((s, i) => ({ at: 'slide:' + (i + 1), text: s.text || '' }));
}

// ---------- xlsx ----------

/**
 * xlsx 大纲：每个工作表一条。label 是 `名称 (A1:F30)`，空表是 `名称 (empty)`，
 * 隐藏表另加标注。
 * @param {{name, usedRange?: {from:{row,col}, to:{row,col}}, hidden?: boolean, empty?: boolean}[]} sheets
 */
export function xlsxOutline(sheets, cellText) {
  const fmt = r => (r ? cellText.from(r.from) + ':' + cellText.to(r.to) : '');
  return (sheets || []).map(s => {
    const parts = [s.name];
    if (s.empty) parts.push('(empty)');
    else if (s.usedRange) parts.push('(' + fmt(s.usedRange) + ')');
    if (s.hidden) parts.push('(隐藏)');
    return { label: parts.join(' '), at: s.name, level: 1 };
  });
}

export function xlsxUnits(sheets) {
  return (sheets || []).map(s => ({ at: s.name, text: s.text || '' }));
}

// ---------- image ----------

export function imageOutline(path) {
  const name = String(path || '').split(/[\\/]/).pop();
  return [{ label: name || '图片', at: '', level: 1 }];
}
