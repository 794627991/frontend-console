// ============================================================
// docview / hl —— 文本范围查找、高亮涂抹、滚动
//
// 译自 ZCode 的 OR/ui/dom.ts（文档 4.2.5 / 4.2.11）。三件事：
//   findTextRange(root, quote)   在一段 DOM 里找出引文对应的 Range
//   paintRanges(root, ranges)    给这些 Range 套 <mark class="dv-hl">
//   scrollRangeIntoView(range)   滚到该位置
//
// **为什么要自己写而不先用 window.find**：window.find 是用户可见的「浏览器
// 查找」状态，会跟面板内自带的查找互斥，而且它不改 DOM，无法让高亮留存。
//
// **跨元素匹配**：引文常跨行内元素（Word 里一段话被拆成十几个带样式的 span），
// 所以要先把元素里的文本节点排成一个扁平序列，在拼接后的整串上定位，再把
// 「字符偏移」映射回「节点 + 偏移」。这是唯一可靠的跨元素做法。
// ============================================================

import { normalize } from './text.js';

const SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1 };

/** 收集 root 下的可见文本节点（跳过脚本/样式）。 */
function textNodesOf(root) {
  const out = [];
  if (!root) return out;
  const walk = (n) => {
    if (n.nodeType === Node.TEXT_NODE) {
      if (n.nodeValue && /\S/.test(n.nodeValue)) out.push(n);
      return;
    }
    if (n.nodeType !== Node.ELEMENT_NODE) return;
    if (SKIP_TAGS[n.tagName]) return;
    for (let c = n.firstChild; c; c = c.nextSibling) walk(c);
  };
  walk(root);
  return out;
}

/** 把一组文本节点拼成一串，并记下每个节点在整串里的起点。 */
function buildIndex(nodes) {
  const parts = [];
  const starts = [];
  let len = 0;
  for (const n of nodes) {
    starts.push(len);
    parts.push(n.nodeValue);
    len += n.nodeValue.length;
  }
  return { text: parts.join(''), starts };
}

/** 整串偏移 → { node, offset }。越界时收敛到最近的边界。 */
function locate(nodes, starts, pos) {
  if (!nodes.length) return null;
  if (pos <= 0) return { node: nodes[0], offset: 0 };
  for (let i = nodes.length - 1; i >= 0; i -= 1) {
    if (pos >= starts[i]) {
      return { node: nodes[i], offset: Math.min(pos - starts[i], nodes[i].nodeValue.length) };
    }
  }
  return { node: nodes[0], offset: 0 };
}

/**
 * 在 root 里找 quote 的**第一处**出现，返回 Range。
 * @param {Node} root
 * @param {string} quote
 * @param {boolean} [fold] 是否忽略大小写与空白差异（查找框用 true）
 */
export function findTextRange(root, quote, fold) {
  const q = normalize(quote);
  if (!q) return null;
  const nodes = textNodesOf(root);
  if (!nodes.length) return null;
  const { text, starts } = buildIndex(nodes);

  // 直接找；找不到再试归一化后的比较。归一化会改变长度，所以第二遍不能用
  // 偏移回推——改用逐节点滑窗：只在单节点内做归一化匹配（跨节点时直接给
  // 整串的宽松匹配，命中后用「节点边界包含」近似落点）。
  let idx = fold ? text.toLowerCase().indexOf(q.toLowerCase()) : text.indexOf(q);
  if (idx >= 0) {
    const from = locate(nodes, starts, idx);
    const to = locate(nodes, starts, idx + q.length);
    if (!from || !to) return null;
    const r = document.createRange();
    r.setStart(from.node, from.offset);
    r.setEnd(to.node, to.offset);
    return r;
  }

  // 宽松匹配：两边都压掉所有空白，按字符序对齐回原文
  const flatChars = [];
  for (let i = 0; i < text.length; i += 1) if (!/\s/.test(text[i])) flatChars.push(i);
  const flatText = flatChars.map(i => text[i]).join('').toLowerCase();
  const flatQ = q.replace(/\s+/g, '').toLowerCase();
  if (!flatQ) return null;
  const fi = flatText.indexOf(flatQ);
  if (fi < 0) return null;
  const origFrom = flatChars[fi];
  const origTo = flatChars[fi + flatQ.length - 1] + 1;
  const from = locate(nodes, starts, origFrom);
  const to = locate(nodes, starts, origTo);
  if (!from || !to) return null;
  const r = document.createRange();
  r.setStart(from.node, from.offset);
  r.setEnd(to.node, to.offset);
  return r;
}

/**
 * 涂多个 Range。
 *
 * 用 **CSS Custom Highlight API**（`CSS.highlights` + `Range`），不改 DOM：
 * 直接包 <mark> 会改变节点结构，撞坏 docx 的块对齐（alignBlocks 靠文本前缀
 * 匹配元素，DOM 一变就错位），而且反复涂/清会让文本节点碎成一片。
 * Chromium 105+ 支持，本壳 Electron 45 = Chromium 132+。
 *
 * 设计文档 6.1.7 要求：接口不存在**不许静默失败**——回退成给所在块加高亮
 * 类，并记一条告警。
 *
 * @returns {{ kind: 'highlight'|'class', marks?: Highlight, els?: HTMLElement[] }}
 */
export function paintRanges(ranges, name) {
  const key = name || 'dv-reveal';
  const valid = [...ranges].filter(Boolean);
  if (!valid.length) return { kind: 'none' };

  const hasApi = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined';
  if (hasApi) {
    const h = new Highlight(...valid);
    CSS.highlights.set(key, h);
    return { kind: 'highlight', marks: h };
  }

  // 回退：给每个 Range 所在的最近块元素加类
  console.warn('[docview] CSS Custom Highlight API 不可用，高亮回退为块级类名');
  const els = [];
  for (const r of valid) {
    const el = blockOf(r);
    if (el && !el.classList.contains(key)) { el.classList.add(key); els.push(el); }
  }
  return { kind: 'class', els };
}

/** 清掉某一个高亮。两种形态都要清干净。 */
export function clearHighlight(name) {
  const key = name || 'dv-reveal';
  try {
    if (typeof CSS !== 'undefined' && CSS.highlights) CSS.highlights.delete(key);
  } catch (_) {}
  // 回退形态加的类一并清（文档里可能残留上一次运行的产物）
  try {
    document.querySelectorAll('.' + cssEsc(key)).forEach(el => el.classList.remove(key));
  } catch (_) {}
}

function cssEsc(s) {
  return String(s).replace(/[^A-Za-z0-9_-]/g, '');
}

/** Range 起点所在的「可高亮块」：往上找到最近的 section/article/p/li/td。 */
function blockOf(range) {
  let n = range.startContainer;
  if (n && n.nodeType !== Node.ELEMENT_NODE) n = n.parentElement;
  while (n && n !== document.body) {
    if (/^(P|LI|TD|TH|H[1-6]|ARTICLE|SECTION|DIV)$/.test(n.tagName)) return n;
    n = n.parentElement;
  }
  return null;
}

/** 滚到某个 Range 的位置。block: 'center' 让上下文可见（ZCode 用 center）。 */
export function scrollRangeIntoView(range, scroller) {
  if (!range) return;
  try {
    const rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) return;
    if (!scroller) {
      const el = range.startContainer.parentElement || range.startContainer;
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    const sr = scroller.getBoundingClientRect();
    const delta = rect.top - sr.top - (sr.height / 2 - rect.height / 2);
    scroller.scrollTo({ top: scroller.scrollTop + delta, behavior: 'smooth' });
  } catch (_) {}
}
