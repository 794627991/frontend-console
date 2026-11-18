// log-viewer 滚动映射纯函数单测（a644 首批 node 测试）
//
// 为什么测这两个：超大日志的搜索结果列表走「线性缩放映射」分支——命中几万
// 条时滚动条高度会被浏览器钳制，代码用比例映射绕开。这是纯数学，改错了
// 表现是「跳转落错位 / 尾部滚不到」，而且日志一大才复现，人工测极难覆盖。
//
// 抽函数的方式：log-viewer.js 是传统 script，直接 import 会执行 DOM 代码。
// 这里用 vm 在隔离上下文里只求值这两个函数定义——不改生产代码，也不引入
// 打包/模块化改造。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', '..', 'web', 'js', 'log-viewer.js');

/** 从源文件里抠出指定函数的源码（顶层函数，靠配对花括号截取）。 */
function extractFn(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `源文件里找不到 ${name}`);
  let depth = 0;
  let i = source.indexOf('{', start);
  const from = i;
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`${name} 花括号不配对（起点 ${from}）`);
}

const src = fs.readFileSync(SRC, 'utf8');
const consts = src.slice(0, src.indexOf('function resScrollToHit'));
const sandbox = {};
const code = consts
  + extractFn(src, 'resScrollToHit')
  + extractFn(src, 'resHitToScroll')
  + '\nthis.resScrollToHit = resScrollToHit;'
  + '\nthis.resHitToScroll = resHitToScroll;';
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const { resScrollToHit, resHitToScroll } = sandbox;

/** 造一个 conn：只带这两个函数需要的东西。 */
function conn(total, viewH) {
  return {
    logState: { searchTotal: total },
    searchResults: { clientHeight: viewH },
  };
}

test('未超限：scrollTop 直接按行高换算', () => {
  const c = conn(100, 400);
  assert.equal(resScrollToHit(c, 0), 0);
  assert.equal(resScrollToHit(c, 40), 2);
  assert.equal(resScrollToHit(c, 399), 19);
  assert.equal(resHitToScroll(c, 2), 40);
});

test('未超限：命中序号换算与行高一致（往返自洽）', () => {
  const c = conn(1000, 400);
  for (const hit of [0, 1, 7, 99, 500]) {
    const top = resHitToScroll(c, hit);
    assert.equal(resScrollToHit(c, top), hit, `hit=${hit} 往返不一致`);
  }
});

test('超限分支：映射到 [0, maxHit] 且不越界', () => {
  // 让 naturalH > RES_MAX_H(10_000_000)：total * 20 > 1e7 → total > 500_000
  const total = 600_000;
  const viewH = 400;
  const c = conn(total, viewH);
  const maxHit = total - Math.ceil(viewH / 20);
  assert.equal(resScrollToHit(c, 0), 0);
  // 滚动条最底部 → 末屏首行
  const maxScroll = 10_000_000 - viewH;
  assert.equal(resScrollToHit(c, maxScroll), maxHit);
  // 越界输入钳到 maxHit，不返回大于总数的值
  assert.equal(resScrollToHit(c, maxScroll * 2), maxHit);
});

test('超限分支：反向映射把 hit 钳到 maxHit', () => {
  const total = 600_000;
  const viewH = 400;
  const c = conn(total, viewH);
  const maxScroll = 10_000_000 - viewH;
  assert.equal(resHitToScroll(c, 0), 0);
  assert.equal(resHitToScroll(c, total), maxScroll);   // 末尾钳住
});

test('边界：零命中 / 零视口高度不炸', () => {
  assert.equal(resScrollToHit(conn(0, 400), 0), 0);
  assert.equal(resHitToScroll(conn(0, 400), 0), 0);
  const c = conn(10, 0);
  assert.ok(Number.isFinite(resScrollToHit(c, 100)));
  assert.ok(Number.isFinite(resHitToScroll(c, 5)));
});

test('超限分支往返：命中序号经双向映射后落在原命中附近', () => {
  const total = 600_000;
  const viewH = 400;
  const c = conn(total, viewH);
  const maxHit = total - Math.ceil(viewH / 20);
  // 缩放下非一一对应（多对一），只要求单调不倒退
  let prev = -1;
  for (const ratio of [0, 0.25, 0.5, 0.75, 1]) {
    const hit = Math.floor(ratio * maxHit);
    const top = resHitToScroll(c, hit);
    const back = resScrollToHit(c, top);
    assert.ok(back >= prev, '映射必须单调');
    assert.ok(Math.abs(back - hit) <= 1, `hit=${hit} 回到 ${back}，偏差过大`);
    prev = back;
  }
});
