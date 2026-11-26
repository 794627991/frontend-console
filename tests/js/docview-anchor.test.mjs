// docview/anchor 与 text 的纯函数单测（AC-3.10 的 JS 侧，Python 侧另有同语义用例）
//
// 为什么测：锚点语法是 AI、后端、面板三方共用的契约。写错一位（下标从 0 起、
// 范围反向、表名转义）不会报错，只会让「AI 说第 5 段，面板跳到第 4 段」这种
// 静默错位——人工测几乎发现不了。这里把 ZCode 的用例逐条钉住。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const load = rel => import(pathToFileURL(path.join(HERE, '..', '..', 'web', 'js', 'docview', rel)).href);

const A = await load('anchor.js');
const T = await load('text.js');

test('docx 锚点：单段、范围、表格、单元格', () => {
  assert.deepEqual(A.parseLocator('docx', 'p:14'), { kind: 'docx', paragraph: 14 });
  assert.deepEqual(A.parseLocator('docx', 'p:3-9'), { kind: 'docx', paragraphs: { from: 3, to: 9 } });
  assert.deepEqual(A.parseLocator('docx', 't:2'), { kind: 'docx', table: 2 });
  assert.deepEqual(A.parseLocator('docx', 't:2/r3c1'), { kind: 'docx', table: 2, cell: { row: 3, col: 1 } });
  // 大小写与空白容忍
  assert.deepEqual(A.parseLocator('docx', '  P : 7 '), { kind: 'docx', paragraph: 7 });
});

test('docx 锚点：写错的一律 null（AC-3.5）', () => {
  for (const bad of ['', 'p:', 'p:0', 'p:9-3', 'p:abc', 't:2/r3', 't:0', 'x:3', 'p:1-', 'p:1000001']) {
    assert.equal(A.parseLocator('docx', bad), null, `应拒绝 ${JSON.stringify(bad)}`);
  }
});

test('pdf 锚点', () => {
  assert.deepEqual(A.parseLocator('pdf', 'page:5'), { kind: 'pdf', page: 5 });
  assert.deepEqual(A.parseLocator('pdf', 'page:2-4'), { kind: 'pdf', pages: { from: 2, to: 4 } });
  assert.equal(A.parseLocator('pdf', 'page:0'), null);
  assert.equal(A.parseLocator('pdf', 'p:5'), null);   // 前缀必须是 page
});

test('pptx 锚点，含形状', () => {
  assert.deepEqual(A.parseLocator('pptx', 'slide:3'), { kind: 'pptx', slide: 3 });
  assert.deepEqual(A.parseLocator('pptx', 'slide:2-4'), { kind: 'pptx', slides: { from: 2, to: 4 } });
  assert.deepEqual(A.parseLocator('pptx', 'slide:3/shape:7'), { kind: 'pptx', slide: 3, shape: 7 });
  // 形状只能落在单张上
  assert.equal(A.parseLocator('pptx', 'slide:2-4/shape:7'), null);
});

test('xlsx 锚点：表名、单元格、区域、带空格表名', () => {
  assert.deepEqual(A.parseLocator('xlsx', 'Revenue'), { kind: 'xlsx', sheet: 'Revenue' });
  assert.deepEqual(A.parseLocator('xlsx', 'Revenue!B2'),
    { kind: 'xlsx', sheet: 'Revenue', range: { from: { row: 2, col: 2 }, to: { row: 2, col: 2 } } });
  assert.deepEqual(A.parseLocator('xlsx', 'Revenue!B2:F9'),
    { kind: 'xlsx', sheet: 'Revenue', range: { from: { row: 2, col: 2 }, to: { row: 9, col: 6 } } });
  // 反向范围归一成左上到右下
  assert.deepEqual(A.parseLocator('xlsx', 'Revenue!F9:B2'),
    { kind: 'xlsx', sheet: 'Revenue', range: { from: { row: 2, col: 2 }, to: { row: 9, col: 6 } } });
  // 表名带空格要单引号；内部单引号写两个
  assert.equal(A.parseLocator('xlsx', "'Q3 data'!A1").sheet, 'Q3 data');
  assert.equal(A.parseLocator('xlsx', "'It''s'!A1").sheet, "It's");
  // 绝对引用 $ 允许
  assert.deepEqual(A.parseLocator('xlsx', 'S!$B$2').range.from, { row: 2, col: 2 });
  // 引号没闭合 / 列超限
  assert.equal(A.parseLocator('xlsx', "'Q3 data!A1"), null);
  assert.equal(A.parseLocator('xlsx', 'S!XFE1'), null);    // 16385 列，超出 16384
});

test('formatLocator 规范化输出，范围省略第二个前缀', () => {
  assert.equal(A.formatLocator({ kind: 'docx', paragraphs: { from: 3, to: 9 } }), 'p:3-9');
  assert.equal(A.formatLocator({ kind: 'pdf', pages: { from: 2, to: 4 } }), 'page:2-4');
  assert.equal(A.formatLocator({ kind: 'pptx', slides: { from: 2, to: 4 } }), 'slide:2-4');
  assert.equal(A.formatLocator({ kind: 'pptx', slide: 3, shape: 7 }), 'slide:3/shape:7');
  assert.equal(A.formatLocator({ kind: 'docx', table: 2, cell: { row: 3, col: 1 } }), 't:2/r3c1');
  assert.equal(A.formatLocator({ kind: 'xlsx', sheet: 'Q3 data' }), "'Q3 data'");
  assert.equal(A.formatLocator({ kind: 'xlsx', sheet: 'S', range: { from: { row: 2, col: 2 }, to: { row: 9, col: 6 } } }), 'S!B2:F9');
  // 单格区域输出简写
  assert.equal(A.formatLocator({ kind: 'xlsx', sheet: 'S', range: { from: { row: 2, col: 2 }, to: { row: 2, col: 2 } } }), 'S!B2');
});

test('解析→格式化往返稳定', () => {
  const cases = ['docx|p:14', 'docx|p:3-9', 'docx|t:2', 'docx|t:2/r3c1', 'pdf|page:5', 'pdf|page:2-4',
    'pptx|slide:3', 'pptx|slide:2-4', 'pptx|slide:3/shape:7', 'xlsx|Revenue', 'xlsx|Revenue!B2',
    'xlsx|Revenue!B2:F9', "xlsx|'Q3 data'!A1"];
  for (const c of cases) {
    const [k, raw] = c.split('|');
    assert.equal(A.formatLocator(A.parseLocator(k, raw)), raw, `往返失败：${c}`);
  }
});

test('列号与单元格换算', () => {
  assert.equal(A.columnName(1), 'A');
  assert.equal(A.columnName(26), 'Z');
  assert.equal(A.columnName(27), 'AA');
  assert.equal(A.columnName(16384), 'XFD');
  assert.deepEqual(A.parseCell('AA10'), { row: 10, col: 27 });
  assert.equal(A.formatCell({ row: 10, col: 27 }), 'AA10');
});

test('splitAnchor 在第一个受支持扩展名 + # 处切', () => {
  assert.deepEqual(A.splitAnchor('D:\\docs\\报告.docx#p:3'), { path: 'D:\\docs\\报告.docx', at: 'p:3' });
  assert.deepEqual(A.splitAnchor('/a/b.pdf'), { path: '/a/b.pdf', at: '' });
  // .bak 不在扩展名表里，不能被当成切点
  assert.deepEqual(A.splitAnchor('D:\\a\\my.docx.bak'), { path: 'D:\\a\\my.docx.bak', at: '' });
  assert.deepEqual(A.splitAnchor('D:\\a\\x.PPTX#slide:2'), { path: 'D:\\a\\x.PPTX', at: 'slide:2' });
});

test('parseAnchor 同时给出 kind 与 loc', () => {
  const r = A.parseAnchor('D:\\docs\\报告.docx#p:3-9');
  assert.equal(r.kind, 'docx');
  assert.equal(r.path, 'D:\\docs\\报告.docx');
  assert.deepEqual(r.loc, { kind: 'docx', paragraphs: { from: 3, to: 9 } });
  // 锚点写错：loc 为 null，但路径与 kind 仍给出（好让调用方报准确提示）
  const bad = A.parseAnchor('a.pdf#page:0');
  assert.equal(bad.kind, 'pdf');
  assert.equal(bad.loc, null);
});

test('kindOfPath 认扩展名，剥锚点与行号', () => {
  assert.equal(A.kindOfPath('a/b.docx'), 'docx');
  assert.equal(A.kindOfPath('a/b.DOCX'), 'docx');
  assert.equal(A.kindOfPath('a/b.docx#p:3'), 'docx');
  assert.equal(A.kindOfPath('a/b.png'), 'image');
  assert.equal(A.kindOfPath('a/b.txt'), null);
  assert.equal(A.kindOfPath('a/b'), null);
  // 行号后缀
  assert.equal(A.kindOfPath('a/b.docx:12'), 'docx');
});

test('text：归一化统一空白与换行', () => {
  assert.equal(T.normalize('  a\r\n\tb\u3000c  '), 'a b c');
  assert.equal(T.normalizeKeepLines(' a  b \n c '), 'a b\nc');
  assert.equal(T.foldText('  Hello  World '), 'hello world');
});

test('text：截断不切开代理对（AC-3.12）', () => {
  const s = 'ab😀cd';   // 😀 占两个码元，位于索引 2..3
  assert.equal(T.truncate(s, 10), s);
  assert.equal(T.truncate(s, 3), 'ab');       // 切点落在代理对中间 → 退一格
  assert.equal(T.truncate(s, 4), 'ab😀');     // 正好整对
  assert.equal(T.truncate(s, 2), 'ab');
  // 截断结果里不能有孤立代理项
  for (let n = 0; n <= s.length; n += 1) {
    const out = T.truncate(s, n);
    for (let i = 0; i < out.length; i += 1) {
      const c = out.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff) {
        const d = out.charCodeAt(i + 1);
        assert.ok(d >= 0xdc00 && d <= 0xdfff, `截断到 ${n} 时产生了孤立高位代理`);
      }
    }
  }
  assert.equal(T.codePointLength('ab😀cd'), 5);
});
