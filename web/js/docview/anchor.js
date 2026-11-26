// ============================================================
// docview / anchor —— 锚点语法
//
// 译自 ZCode 的 OR/src/domain/anchor.ts（195 行，文档 4.1 有逐行索引）。
// 锚点是「路径#位置」里 # 后面那段，AI、后端、面板三方共用同一个语法：
//
//   docx   p:14   p:3-9       t:2   t:2/r3c1
//   pptx   slide:3   slide:2-4   slide:3/shape:7
//   pdf    page:5   page:2-4
//   xlsx   Revenue   Revenue!B2   Revenue!B2:F9   'Q3 data'!A1
//
// 边界全是下标**从 1 起**（不是 0）——ZCode 如此，AI 生成的锚点也如此，
// 改成 0 起会让所有既有工具输出错一位。上界取 Excel 的极限：
// 行 1048576、列 16384。长度上限 300。
//
// Python 侧的 doc_api 会有一份同语义的实现（AC-3.10 要求两边跑同一组用例
// 结果相同），改这里必须同步改那里。
// ============================================================

import { normalize } from './text.js';

export const KIND_DOCX = 'docx';
export const KIND_PPTX = 'pptx';
export const KIND_PDF = 'pdf';
export const KIND_XLSX = 'xlsx';
export const KIND_IMAGE = 'image';

export const MAX_ANCHOR_LEN = 300;
export const MAX_ROW = 1048576;   // Excel 行上限
export const MAX_COL = 16384;     // Excel 列上限
const MAX_INDEX = 1000000;        // 段落/页/幻灯片序号上限（ZCode 同值）

/** 每种文档的出错提示（ZCode anchor.ts:27-32 的 HINTS，改写成中文）。 */
export const HINTS = {
  [KIND_DOCX]: 'Word 文档的锚点写法：p:14（第 14 段）、p:3-9（第 3 到 9 段）、t:2（第 2 个表格）、t:2/r3c1（第 2 个表格第 3 行第 1 列）',
  [KIND_PPTX]: '演示文稿的锚点写法：slide:3（第 3 张）、slide:2-4（第 2 到 4 张）、slide:3/shape:7（第 3 张的第 7 个形状）',
  [KIND_PDF]: 'PDF 的锚点写法：page:5（第 5 页）、page:2-4（第 2 到 4 页）',
  [KIND_XLSX]: '工作表的锚点写法：Revenue（整张）、Revenue!B2（单元格）、Revenue!B2:F9（区域）、\'Q3 data\'!A1（表名含空格时加单引号）',
  [KIND_IMAGE]: '图片没有锚点',
};

/** 扩展名 → kind。大小写不敏感。图片六种按 A10。 */
const EXT_KIND = {
  docx: KIND_DOCX, doc: KIND_DOCX,
  pdf: KIND_PDF,
  xlsx: KIND_XLSX, xls: KIND_XLSX, csv: KIND_XLSX,
  pptx: KIND_PPTX, ppt: KIND_PPTX,
  png: KIND_IMAGE, jpg: KIND_IMAGE, jpeg: KIND_IMAGE,
  gif: KIND_IMAGE, webp: KIND_IMAGE, bmp: KIND_IMAGE,
  ico: KIND_IMAGE, svg: KIND_IMAGE,
};

/** 可点/可打开的扩展名集合（6.3.2：四种文档加图片六种）。 */
export const DOC_EXTS = Object.keys(EXT_KIND);

/** 路径 → kind，认不出返回 null。 */
export function kindOfPath(path) {
  const p = String(path || '');
  // 先剥锚点与行号后缀再取扩展名（AI 常写 report.docx#p:3）
  const bare = p.replace(/[#?].*$/, '').replace(/:\d+(:\d+)?$/, '');
  const m = /\.([a-z0-9]+)$/i.exec(bare);
  if (!m) return null;
  return EXT_KIND[m[1].toLowerCase()] || null;
}

/** 是否是可打开的文档路径（含图片）。 */
export function isDocPath(path) {
  return !!kindOfPath(path);
}

// ---------- Excel 列号 ↔ 字母（anchor.ts:42-47） ----------

export function columnName(col) {
  let n = col | 0;
  if (n < 1) return '';
  let s = '';
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function columnIndex(name) {
  const s = String(name || '').toUpperCase();
  if (!/^[A-Z]{1,3}$/.test(s)) return 0;
  let n = 0;
  for (const ch of s) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

/** 解析单元格 "B2"（允许 $ 绝对引用）。返回 { row, col } 或 null。 */
export function parseCell(text) {
  const m = /^\$?([A-Za-z]{1,3})\$?(\d{1,7})$/.exec(String(text || '').trim());
  if (!m) return null;
  const col = columnIndex(m[1]);
  const row = parseInt(m[2], 10);
  if (col < 1 || col > MAX_COL) return null;
  if (row < 1 || row > MAX_ROW) return null;
  return { row, col };
}

export function formatCell(cell) {
  if (!cell) return '';
  const c = Number(cell.col) | 0;
  const r = Number(cell.row) | 0;
  if (c < 1 || r < 1) return '';
  return columnName(c) + r;
}

/** 表名格式化：不是普通标识符时按 Excel 的方式加单引号（内部单引号写两个）。 */
export function formatSheet(name) {
  const s = String(name == null ? '' : name);
  if (!s) return '';
  if (/^[A-Za-z_][A-Za-z0-9_.]*$/.test(s)) return s;
  return "'" + s.replace(/'/g, "''") + "'";
}

function parseSheetName(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  if (s.charAt(0) !== "'") return s;
  let out = '', i = 1;
  for (; i < s.length; i += 1) {
    if (s[i] === "'") {
      if (s[i + 1] === "'") { out += "'"; i += 1; }   // 两个单引号 = 一个字面单引号
      else { i += 1; break; }
    } else out += s[i];
  }
  if (i >= s.length && s.charAt(s.length - 1) !== "'") return '';   // 引号没闭合
  return out;
}

/** xlsx 锚点：表名 + 可选 !A1 / !A1:B2。范围归一成左上到右下。 */
export function parseXlsx(text) {
  const s = String(text || '').trim();
  if (!s) return null;
  const bang = s.lastIndexOf('!');
  let sheetRaw, rangeRaw;
  if (bang < 0) { sheetRaw = s; rangeRaw = ''; }
  else { sheetRaw = s.slice(0, bang); rangeRaw = s.slice(bang + 1).trim(); }
  const sheet = parseSheetName(sheetRaw);
  if (!sheet) return null;
  if (!rangeRaw) return { kind: KIND_XLSX, sheet };
  const parts = rangeRaw.split(':');
  if (parts.length > 2) return null;
  const a = parseCell(parts[0]);
  if (!a) return null;
  if (parts.length === 1) return { kind: KIND_XLSX, sheet, range: { from: a, to: a } };
  const b = parseCell(parts[1]);
  if (!b) return null;
  // 归一：左上 → 右下
  const from = { row: Math.min(a.row, b.row), col: Math.min(a.col, b.col) };
  const to = { row: Math.max(a.row, b.row), col: Math.max(a.col, b.col) };
  return { kind: KIND_XLSX, sheet, range: { from, to } };
}

// ---------- 通用索引与范围 ----------

function numOf(s) {
  if (!/^\d{1,7}$/.test(String(s || ''))) return 0;
  const n = parseInt(s, 10);
  if (n < 1 || n > MAX_INDEX) return 0;
  return n;
}

/** "3" 或 "3-9" → { from, to }；无法解析返回 null。 */
function rangeOf(raw) {
  const s = String(raw || '').trim();
  const m = /^(\d{1,7})(?:\s*-\s*(\d{1,7}))?$/.exec(s);
  if (!m) return null;
  const from = numOf(m[1]);
  if (!from) return null;
  const to = m[2] == null ? from : numOf(m[2]);
  if (!to) return null;
  if (to < from) return null;   // 反向范围视为写错（AC-3.5 要明确提示）
  return { from, to };
}

/** 解析锚点文本。kind 决定语法。返回 Locator 或 null。 */
export function parseLocator(kind, raw) {
  const s = normalize(raw);
  if (!s || s.length > MAX_ANCHOR_LEN) return null;

  if (kind === KIND_XLSX) return parseXlsx(s);

  if (kind === KIND_DOCX) {
    // p:14 / p:3-9
    let m = /^p\s*:\s*(\d{1,7}(?:\s*-\s*\d{1,7})?)$/i.exec(s);
    if (m) {
      const r = rangeOf(m[1]);
      if (!r) return null;
      return r.from === r.to ? { kind, paragraph: r.from } : { kind, paragraphs: r };
    }
    // t:2 / t:2/r3c1
    m = /^t\s*:\s*(\d{1,7})(?:\s*\/\s*r(\d{1,7})c(\d{1,7}))?$/i.exec(s);
    if (m) {
      const t = numOf(m[1]);
      if (!t) return null;
      if (m[2] == null) return { kind, table: t };
      const row = numOf(m[2]), col = numOf(m[3]);
      if (!row || !col) return null;
      return { kind, table: t, cell: { row, col } };
    }
    return null;
  }

  if (kind === KIND_PPTX) {
    // slide:3/shape:7 —— 形状可选，必须整串吃掉
    let m = /^slide\s*:\s*(\d{1,7}(?:\s*-\s*\d{1,7})?)(?:\s*\/\s*shape\s*:\s*(\d{1,7}))?$/i.exec(s);
    if (!m) return null;
    const r = rangeOf(m[1]);
    if (!r) return null;
    if (m[2] != null) {
      const shape = numOf(m[2]);
      if (!shape) return null;
      if (r.from !== r.to) return null;   // 形状只能在单张幻灯片上
      return { kind, slide: r.from, shape };
    }
    return r.from === r.to ? { kind, slide: r.from } : { kind, slides: r };
  }

  if (kind === KIND_PDF) {
    const m = /^page\s*:\s*(\d{1,7}(?:\s*-\s*\d{1,7})?)$/i.exec(s);
    if (!m) return null;
    const r = rangeOf(m[1]);
    if (!r) return null;
    return r.from === r.to ? { kind, page: r.from } : { kind, pages: r };
  }

  return null;
}

/**
 * 规范化输出。范围写法是 `p:3-9`——**省略第二个前缀**（anchor.ts:143-167）。
 * 解析失败返回空串（调用方据此判断「锚点写错」）。
 */
export function formatLocator(loc) {
  if (!loc || !loc.kind) return '';
  const k = loc.kind;
  if (k === KIND_XLSX) {
    const sheet = formatSheet(loc.sheet);
    if (!sheet) return '';
    if (!loc.range) return sheet;
    const a = loc.range.from, b = loc.range.to;
    if (!a) return sheet;
    const fa = formatCell(a);
    if (!b || (b.row === a.row && b.col === a.col)) return sheet + '!' + fa;
    return sheet + '!' + fa + ':' + formatCell(b);
  }
  if (k === KIND_DOCX) {
    if (loc.paragraph) return 'p:' + loc.paragraph;
    if (loc.paragraphs) return 'p:' + loc.paragraphs.from + '-' + loc.paragraphs.to;
    if (loc.table) {
      if (!loc.cell) return 't:' + loc.table;
      return 't:' + loc.table + '/r' + loc.cell.row + 'c' + loc.cell.col;
    }
    return '';
  }
  if (k === KIND_PPTX) {
    if (loc.slide) return 'slide:' + loc.slide + (loc.shape ? '/shape:' + loc.shape : '');
    if (loc.slides) return 'slide:' + loc.slides.from + '-' + loc.slides.to;
    return '';
  }
  if (k === KIND_PDF) {
    if (loc.page) return 'page:' + loc.page;
    if (loc.pages) return 'page:' + loc.pages.from + '-' + loc.pages.to;
    return '';
  }
  return '';
}

/**
 * 从「路径#锚点」里切出路径。路径在**第一个受支持扩展名**加 # 或行尾处结束
 * （anchor.ts:170-179）——所以 `D:\a\b.docx#p:3` 的路径是 `D:\a\b.docx`，
 * 而 `D:\a\b` 里若含 .docx 字样（如 `my.docx.bak`）不会被误切。
 * 返回 { path, at }；没有 # 时 at 为空串。
 */
export function splitAnchor(anchor) {
  const s = String(anchor == null ? '' : anchor);
  const ext = '(?:docx|doc|pdf|xlsx|xls|csv|pptx|ppt|png|jpe?g|gif|webp|bmp|ico|svg)';
  // 找第一个「扩展名 + 后面是 # 或行尾」的位置
  const re = new RegExp('\\.' + ext + '(?=#|$)', 'ig');
  let m, last = -1;
  while ((m = re.exec(s)) !== null) { last = m.index + m[0].length; break; }
  if (last < 0) {
    // 认不出扩展名：仍然按第一个 # 切（后端会用自己的白名单再校验）
    const i = s.indexOf('#');
    return i < 0 ? { path: s, at: '' } : { path: s.slice(0, i), at: s.slice(i + 1) };
  }
  if (s.charAt(last) === '#') return { path: s.slice(0, last), at: s.slice(last + 1) };
  return { path: s, at: '' };   // 扩展名后面直接是行尾，没有锚点
}

export function formatAnchor(path, loc) {
  const a = formatLocator(loc);
  return a ? String(path) + '#' + a : String(path);
}

/** 解析「路径#锚点」为 { kind, path, loc, at }。loc 为 null 表示锚点写错或无锚点。 */
export function parseAnchor(anchor) {
  const { path, at } = splitAnchor(anchor);
  const kind = kindOfPath(path);
  let loc = null;
  if (at && kind && at.length <= MAX_ANCHOR_LEN) loc = parseLocator(kind, at);
  return { kind, path, at, loc };
}
