// ============================================================
// docview / docx-parse —— 从 word/document.xml 抽块与标题
//
// 译自 ZCode 的 OR/src/adapters/parse/docx.ts:94-234。设计文档 4.2.1 说这是
// 「整个功能里最容易做错的一块」，规则逐条摘在下面。**不要改这些规则**：
// AI 读到的 p:N 与用户看到的第 N 段必须是同一段，差一个空段就全错。
//
// 规则：
//   · 只遍历 w:body 的**直接子级**（不递归进表格里的段落）
//   · w:p        → p:N（N 从 1 起；空段落也占号，输出 "(empty)"）
//   · w:tbl      → t:N（只取 w:tr/w:tc 文本，单元格内多段用换行拼）
//   · w:sdt      → 走进 w:sdtContent 继续遍历（相当于透明）
//   · w:customXml / w:smartTag → 走进子节点继续遍历
//   · 修订：跳过 w:del / w:delText / w:instrText；w:ins 里的文本**算**
//   · 文本框（w:txbxContent）的文字并入宿主段落，不单独编号
//   · 列表项就是普通 w:p，有 w:numPr 或样式名以 list 开头时前缀 "- "
//
// 本模块只吃 XML 字符串、产出纯数据，不碰 DOM API 之外的东西，方便单测
//（单测里用 Node 的 DOMParser 替身跑同一套规则）。
// ============================================================

const W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
// 跳过这些容器里的东西。**pict/drawing 不能整个跳**——文本框（w:txbxContent）
// 通常就挂在它们里面，跳掉会丢宿主段落里的文字（4.2.1 明确要求并入）。
const SKIP_RUN_CHILDREN = { del: 1, delText: 1, instrText: 1, rPr: 1, fldChar: 1 };

/** 取元素上带 w: 命名空间的属性（兼容有/无前缀两种序列化）。 */
function wattr(el, name) {
  return el.getAttribute('w:' + name) || el.getAttribute(name) || '';
}

/** 元素本地名（去掉命名空间前缀）。 */
function lname(el) {
  const n = el.localName || el.nodeName || '';
  const i = n.indexOf(':');
  return i < 0 ? n : n.slice(i + 1);
}

/**
 * 收集一个节点下的文本，跳过删除的修订与域代码。
 * 递归进 w:txbxContent（文本框文字并入宿主段落）。
 */
function runText(node, out) {
  if (!node) return out;
  for (let c = node.firstChild; c; c = c.nextSibling) {
    if (c.nodeType !== 1) continue;   // 只处理元素；文本在 w:t 里
    const ln = lname(c);
    if (SKIP_RUN_CHILDREN[ln]) continue;
    if (ln === 't') { out.push(c.textContent || ''); continue; }
    if (ln === 'tab') { out.push('\t'); continue; }
    if (ln === 'br' || ln === 'cr') { out.push('\n'); continue; }
    if (ln === 'noBreakHyphen') { out.push('-'); continue; }
    if (ln === 'txbxContent') { runText(c, out); continue; }
    runText(c, out);
  }
  return out;
}

/** 段落文本（含文本框、不含删除修订）。 */
function paragraphText(p) {
  return runText(p, []).join('');
}

/** 段落是不是列表项：有 w:numPr，或 pStyle 名以 list 开头。 */
function isListItem(p) {
  const pPr = [...p.children].find(c => lname(c) === 'pPr');
  if (!pPr) return false;
  const numPr = [...pPr.children].find(c => lname(c) === 'numPr');
  if (numPr) return true;
  const pStyle = [...pPr.children].find(c => lname(c) === 'pStyle');
  if (pStyle) {
    const v = (wattr(pStyle, 'val') || '').toLowerCase();
    if (v.indexOf('list') === 0) return true;
  }
  return false;
}

/** 段落的样式 ID（用于查 outlineLvl）。 */
function paragraphStyleId(p) {
  const pPr = [...p.children].find(c => lname(c) === 'pPr');
  if (!pPr) return '';
  const pStyle = [...pPr.children].find(c => lname(c) === 'pStyle');
  return pStyle ? (wattr(pStyle, 'val') || '') : '';
}

/** 表格文本：只取 w:tr/w:tc，单元格内多段用换行拼。 */
function tableText(tbl) {
  const rows = [];
  for (const tr of tbl.querySelectorAll('w\\:tr, tr')) {
    const cells = [];
    for (const tc of tr.querySelectorAll('w\\:tc, tc')) {
      const paras = [...tc.querySelectorAll('w\\:p, p')].map(paragraphText);
      cells.push(paras.join('\n').trim());
    }
    if (cells.length) rows.push(cells.join('\t'));
  }
  return rows.join('\n');
}

/**
 * 解析 styles.xml，产出 styleId → 大纲级别（1~6）。与 office-viewer 的
 * _ovDocxStyleLevels 同语义——两处必须一致，否则同文档两个地方给出不同大纲。
 * 0~8 → 1~9 级；9 在 Word 里是「正文文本」级别（TOC Heading 用它），排除。
 */
export function styleLevels(xmlDoc) {
  const m = new Map();
  if (!xmlDoc) return m;
  for (const st of xmlDoc.querySelectorAll('w\\:style, style')) {
    const id = wattr(st, 'styleId') || st.getAttribute('styleId') || '';
    if (!id) continue;
    const ol = [...st.children].find(c => lname(c) === 'pPr');
    let lvlEl = null;
    if (ol) lvlEl = [...ol.children].find(c => lname(c) === 'outlineLvl');
    if (!lvlEl) lvlEl = [...st.querySelectorAll('w\\:outlineLvl, outlineLvl')][0] || null;
    if (!lvlEl) continue;
    const v = parseInt(wattr(lvlEl, 'val') || 'NaN', 10);
    if (!(v >= 0 && v <= 8)) continue;
    m.set(id, Math.min(6, v + 1));
  }
  return m;
}

/**
 * 从 word/document.xml 的根节点抽出块。
 * @param {Document} doc 已解析的 document.xml
 * @param {Map<string,number>} levels styleId → 级别（可为空 Map）
 * @returns {{ blocks: {at,text,full,styleId,level,isList}[], paragraphs: number, tables: number }}
 */
export function parseBody(doc, levels) {
  const blocks = [];
  const lv = levels || new Map();
  let pCount = 0, tCount = 0;
  if (!doc) return { blocks, paragraphs: 0, tables: 0 };

  const body = doc.querySelector('w\\:body, body');
  if (!body) return { blocks, paragraphs: 0, tables: 0 };

  const walk = (node) => {
    for (let c = node.firstChild; c; c = c.nextSibling) {
      if (c.nodeType !== 1) continue;
      const ln = lname(c);
      if (ln === 'p') {
        pCount += 1;
        let text = paragraphText(c);
        const isList = isListItem(c);
        if (isList) text = '- ' + text;
        const styleId = paragraphStyleId(c);
        blocks.push({
          at: 'p:' + pCount,
          text: text,
          full: text,
          styleId,
          level: lv.get(styleId) || 0,
          isList,
        });
      } else if (ln === 'tbl') {
        tCount += 1;
        const text = tableText(c);
        blocks.push({ at: 't:' + tCount, text, full: text, styleId: '', level: 0, isList: false });
      } else if (ln === 'sdt') {
        const content = [...c.children].find(x => lname(x) === 'sdtContent');
        if (content) walk(content);
      } else if (ln === 'customXml' || ln === 'smartTag') {
        walk(c);
      }
      // 其余（sectPr、bookmarkStart 等）忽略
    }
  };
  walk(body);
  return { blocks, paragraphs: pCount, tables: tCount };
}

/** 空段落标记（docx.ts:129）。 */
export function isBlankBlock(b) {
  return !String(b && b.text || '').replace(/^-\s/, '').trim();
}
