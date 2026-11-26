// docview/docx-parse 的规则单测
//
// 设计文档 4.2.1 说这是最容易做错的一块，规则漏一条就会「AI 说第 5 段、
// 用户看到的却是第 4 段」。这里把每条规则钉一个用例。
//
// 用运行时自带的 DOMParser 跑规则（Node 22+ 无全局 DOMParser，所以给一个
// 最小替身：只做 xml 解析 + querySelectorAll 需要的子集不够可靠——改用
// linkedom？没有依赖。**用 node 自带的 node:util 不行**，这里改用自写的
// 极简 XML 解析器喂同一套规则，证明规则本身对，不测浏览器解析器。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const load = rel => import(pathToFileURL(path.join(HERE, '..', '..', 'web', 'js', 'docview', rel)).href);

// ---- 极简 XML 树：够跑 docx-parse 的规则，行为对齐 DOMParser 的关键面 ----
// 必须实现 firstChild/nextSibling 链——生产代码按标准 DOM 用这两个属性遍历，
// 只给 childNodes 数组的话兄弟遍历只走一个子元素（本测曾因此误报）。
class El {
  constructor(name) {
    this.nodeName = name;
    this.localName = name.indexOf(':') < 0 ? name : name.slice(name.indexOf(':') + 1);
    this.nodeType = 1;
    this.attrs = {};
    this.childNodes = [];
    this.textContent = '';
    this.nextSibling = null;
    this.firstChild = null;
  }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  append(n) {
    const prev = this.childNodes[this.childNodes.length - 1];
    if (prev) prev.nextSibling = n;
    else this.firstChild = n;
    this.childNodes.push(n);
  }
  querySelectorAll(sel) {
    const names = sel.split(',').map(s => s.trim().replace(/\\/g, '').replace(/^.*:/, ''));
    const out = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (c.nodeType !== 1) continue;
        if (names.includes(c.localName)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) {
    const names = sel.split(',').map(s => s.trim().replace(/\\/g, '').replace(/^.*:/, ''));
    let hit = null;
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (hit) return;
        if (c.nodeType !== 1) continue;
        if (names.includes(c.localName)) { hit = c; return; }
        walk(c);
      }
    };
    walk(this);
    return hit;
  }
}

/** 极简 XML → El 树。只支持本测用到的形态（无自闭合属性里的尖括号）。 */
function parseXml(src) {
  const root = new El('#doc');
  const stack = [root];
  const re = /<(\/?)([A-Za-z0-9_:.-]+)((?:\s+[A-Za-z0-9_:.-]+\s*=\s*"[^"]*")*)\s*(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(src)) !== null) {
    const [, closing, name, attrs, selfClose, text] = m;
    if (text != null) {
      const t = text;
      if (t.trim()) {
        const cur = stack[stack.length - 1];
        cur.append({ nodeType: 3, nodeValue: t, textContent: t, nextSibling: null });
        cur.textContent += t;
      }
      continue;
    }
    if (closing) { if (stack.length > 1) stack.pop(); continue; }
    const el = new El(name);
    if (attrs) {
      const ar = /([A-Za-z0-9_:.-]+)\s*=\s*"([^"]*)"/g;
      let a;
      while ((a = ar.exec(attrs)) !== null) el.attrs[a[1]] = a[2];
    }
    stack[stack.length - 1].append(el);
    if (!selfClose) stack.push(el);
  }
  return root;
}

const P = await load('docx-parse.js');

const BODY = (inner) => '<w:document><w:body>' + inner + '</w:body></w:document>';

test('段落编号从 1 起，空段落也占号', () => {
  const doc = parseXml(BODY('<w:p><w:r><w:t>一</w:t></w:r></w:p><w:p/><w:p><w:r><w:t>三</w:t></w:r></w:p>'));
  const { blocks, paragraphs } = P.parseBody(doc);
  assert.equal(paragraphs, 3);
  assert.deepEqual(blocks.map(b => b.at), ['p:1', 'p:2', 'p:3']);
});

test('表格整体是 t:N，不计入 p 序号，单元格多段用换行拼接', () => {
  const doc = parseXml(BODY(
    '<w:p><w:r><w:t>前</w:t></w:r></w:p>' +
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A1</w:t></w:r></w:p><w:p><w:r><w:t>A2</w:t></w:r></w:p></w:tc>' +
    '<w:tc><w:p><w:r><w:t>B1</w:t></w:r></w:p></w:tc></w:tr></w:tbl>' +
    '<w:p><w:r><w:t>后</w:t></w:r></w:p>'));
  const { blocks, paragraphs, tables } = P.parseBody(doc);
  assert.equal(paragraphs, 2);   // 表格里的段不算
  assert.equal(tables, 1);
  assert.deepEqual(blocks.map(b => b.at), ['p:1', 't:1', 'p:2']);
  assert.equal(blocks[1].text, 'A1\nA2\tB1');
});

test('w:sdt 透明：走进 sdtContent 继续编号', () => {
  const doc = parseXml(BODY(
    '<w:sdt><w:sdtContent><w:p><w:r><w:t>A</w:t></w:r></w:p></w:sdtContent></w:sdt>' +
    '<w:p><w:r><w:t>B</w:t></w:r></w:p>'));
  const { blocks, paragraphs } = P.parseBody(doc);
  assert.equal(paragraphs, 2);
  assert.deepEqual(blocks.map(b => b.at), ['p:1', 'p:2']);
});

test('customXml / smartTag 也透明', () => {
  const doc = parseXml(BODY(
    '<w:customXml><w:p><w:r><w:t>A</w:t></w:r></w:p></w:customXml>' +
    '<w:smartTag><w:p><w:r><w:t>B</w:t></w:r></w:p></w:smartTag>'));
  const { blocks } = P.parseBody(doc);
  assert.deepEqual(blocks.map(b => b.at), ['p:1', 'p:2']);
});

test('修订：w:del/w:delText 跳过，w:ins 的文本算', () => {
  const doc = parseXml(BODY(
    '<w:p><w:r><w:t>保留</w:t></w:r>' +
    '<w:del><w:r><w:delText>删掉</w:delText></w:r></w:del>' +
    '<w:ins><w:r><w:t>插入</w:t></w:r></w:ins></w:p>'));
  const { blocks } = P.parseBody(doc);
  assert.equal(blocks[0].text, '保留插入');
});

test('域代码 w:instrText 不计入文本', () => {
  const doc = parseXml(BODY('<w:p><w:r><w:t>页码</w:t></w:r><w:r><w:instrText>PAGE</w:instrText></w:r></w:p>'));
  assert.equal(P.parseBody(doc).blocks[0].text, '页码');
});

test('文本框文字并入宿主段落，不单独编号', () => {
  const doc = parseXml(BODY(
    '<w:p><w:r><w:t>宿主</w:t></w:r><w:r><w:pict><w:txbxContent>' +
    '<w:p><w:r><w:t>框内</w:t></w:r></w:p></w:txbxContent></w:pict></w:r></w:p>'));
  const { blocks, paragraphs } = P.parseBody(doc);
  assert.equal(paragraphs, 1);
  assert.ok(blocks[0].text.indexOf('宿主') >= 0);
  assert.ok(blocks[0].text.indexOf('框内') >= 0);
});

test('列表项前缀 - ', () => {
  const doc = parseXml(BODY(
    '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>' +
    '<w:r><w:t>第一项</w:t></w:r></w:p>' +
    '<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr><w:r><w:t>第二项</w:t></w:r></w:p>'));
  const { blocks } = P.parseBody(doc);
  assert.equal(blocks[0].text, '- 第一项');
  assert.equal(blocks[1].text, '- 第二项');
  assert.ok(blocks[0].isList);
});

test('样式 → 大纲级别来自 outlineLvl，9 排除（正文级）', () => {
  const styles = parseXml(
    '<w:styles>' +
    '<w:style w:styleId="1"><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>' +
    '<w:style w:styleId="2"><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>' +
    '<w:style w:styleId="TOC"><w:pPr><w:outlineLvl w:val="9"/></w:pPr></w:style>' +
    '<w:style w:styleId="Normal"></w:style>' +
    '</w:styles>');
  const lv = P.styleLevels(styles);
  assert.equal(lv.get('1'), 1);
  assert.equal(lv.get('2'), 2);
  assert.equal(lv.get('TOC'), undefined);
  assert.equal(lv.get('Normal'), undefined);
});

test('带样式的段落拿到 level，正文段 level 为 0', () => {
  const styles = parseXml('<w:styles><w:style w:styleId="1"><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>');
  const lv = P.styleLevels(styles);
  const doc = parseXml(BODY(
    '<w:p><w:pPr><w:pStyle w:val="1"/></w:pPr><w:r><w:t>标题</w:t></w:r></w:p>' +
    '<w:p><w:r><w:t>正文</w:t></w:r></w:p>'));
  const { blocks } = P.parseBody(doc, lv);
  assert.equal(blocks[0].level, 1);
  assert.equal(blocks[0].styleId, '1');
  assert.equal(blocks[1].level, 0);
});
