// docview/linkify 的识别规则单测（AC-2.1、AC-2.4）
//
// 为什么测：这条规则表有 8 种形态，判错的表现是「该点的地方点不了」或
// 「代码块里的路径被改成了链接」（后者会把 diff/脚本内容搞坏，用户看代码
// 时点一下就跳走）。6.3.2 的表逐行钉住。
//
// linkifyNode 要 DOM，这里只测纯函数 asDocPath / findBarePaths——改写逻辑
// 本身在浏览器里验（AI 浏览器）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const L = await import(pathToFileURL(path.join(HERE, '..', '..', 'web', 'js', 'docview', 'linkify.js')).href);

test('asDocPath：带目录的路径才算，裸文件名不算', () => {
  assert.equal(L.asDocPath('D:\\docs\\报告.docx').ok, true);
  assert.equal(L.asDocPath('/home/a/b.pdf').ok, true);
  assert.equal(L.asDocPath('./rel/x.xlsx').ok, true);
  assert.equal(L.asDocPath('报告.docx').ok, false);      // 裸文件名 → 否
  assert.equal(L.asDocPath('readme.txt').ok, false);     // 非白名单
  assert.equal(L.asDocPath('').ok, false);
});

test('asDocPath：剥掉行号后缀', () => {
  assert.equal(L.asDocPath('D:\\a\\b.docx:12').path, 'D:\\a\\b.docx');
  assert.equal(L.asDocPath('/a/b.pdf:12:5').path, '/a/b.pdf');
});

test('asDocPath：锚点保留（先剥 # 再判扩展名）', () => {
  const r = L.asDocPath('docs/plan.docx#p:12');
  assert.equal(r.ok, true);
  assert.equal(r.path, 'docs/plan.docx');
  assert.equal(r.at, 'p:12');
});

test('asDocPath：去掉包裹的引号 / 反引号', () => {
  assert.equal(L.asDocPath('"D:\\a b\\c.docx"').path, 'D:\\a b\\c.docx');
  assert.equal(L.asDocPath('`D:\\a\\c.docx`').path, 'D:\\a\\c.docx');
});

test('asDocPath：UNC 路径（只在引号/行内代码形态出现）', () => {
  assert.equal(L.asDocPath('\\\\server\\share\\a.docx').ok, true);
});

test('asDocPath：非文档扩展名一律拒绝', () => {
  for (const s of ['a/b.txt', 'a/b.py', 'a/b.exe', 'a/b', 'C:\\x\\y.log']) {
    assert.equal(L.asDocPath(s).ok, false, '应拒绝 ' + s);
  }
});

test('asDocPath：http(s) / file: 等带协议的绝不当本地路径', () => {
  // 实测踩过：https://example.com/x.docx 的扩展名命中白名单 → 网页链接被
  // 改成本地文档链接、href 还被删了（6.3.2「已有的 <a href> 不动」）
  for (const s of ['https://example.com/x.docx', 'http://a/b.pdf',
                   'javascript:alert(1)/x.docx', 'ftp://h/a.xlsx', 'mailto:a@b/x.docx']) {
    assert.equal(L.asDocPath(s).ok, false, '应拒绝 ' + s);
  }
  // 但盘符形态的 `D:\` 不是协议
  assert.equal(L.asDocPath('D:\\a\\b.docx').ok, true);
});

test('findBarePaths：反斜杠盘符路径必须认（ZCode 不认，我方必须认）', () => {
  const hits = L.findBarePaths('见 D:\\docs\\报告.docx 里的说明');
  assert.equal(hits.length, 1);
  assert.equal(hits[0].path, 'D:\\docs\\报告.docx');
});

test('findBarePaths：正斜杠路径', () => {
  const hits = L.findBarePaths('打开 /home/u/a.pdf 即可');
  assert.equal(hits.length, 1);
  assert.equal(hits[0].path, '/home/u/a.pdf');
});

test('findBarePaths：相对路径 ./ 与 ../', () => {
  assert.equal(L.findBarePaths('看 ./out/x.xlsx')[0].path, './out/x.xlsx');
  assert.equal(L.findBarePaths('看 ../up/y.pptx')[0].path, '../up/y.pptx');
});

test('findBarePaths：裸文件名不认（误报太多）', () => {
  assert.equal(L.findBarePaths('报告在 a.docx 里').length, 0);
});

test('findBarePaths：一行里多个路径都能找到', () => {
  const hits = L.findBarePaths('先 D:\\a\\1.docx 再 D:\\b\\2.pdf 最后 /c/3.xlsx');
  assert.equal(hits.length, 3);
  assert.deepEqual(hits.map(h => h.path), ['D:\\a\\1.docx', 'D:\\b\\2.pdf', '/c/3.xlsx']);
});

test('findBarePaths：句末标点不被吃进路径', () => {
  const hits = L.findBarePaths('见 D:\\a\\b.docx。');
  assert.equal(hits.length, 1);
  assert.equal(hits[0].path, 'D:\\a\\b.docx');
});

test('findBarePaths：带锚点的路径连锚点一起给出', () => {
  const hits = L.findBarePaths('看 D:\\a\\b.docx#p:3 那段');
  assert.equal(hits.length, 1);
  assert.equal(hits[0].path, 'D:\\a\\b.docx');
  assert.equal(hits[0].at, 'p:3');
});

test('findBarePaths：非白名单扩展名不产生命中', () => {
  assert.equal(L.findBarePaths('见 D:\\a\\b.txt 与 /x/y.py').length, 0);
});

test('findBarePaths：重复调用不因正则 lastIndex 漂移', () => {
  const s = 'D:\\a\\1.docx';
  for (let i = 0; i < 3; i += 1) assert.equal(L.findBarePaths(s).length, 1, '第 ' + (i + 1) + ' 次');
});
