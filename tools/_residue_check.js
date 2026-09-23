// 一次性检查器:词法感知扫描 21 文件,报告 HOIST2 旧名的「代码态」残留出现。
// 字符串/模板文本/注释/正则内不报;${} 内代码递归报。
'use strict';
const fs = require('fs');
const path = require('path');
const DIR = process.argv[2];
const OLD = ['conn', 'q', 'wrap', 'flow', 'input', 'scrollBottom', 'stateEl', 'costEl',
  'sendBtn', 'titleEl', 'cwdEl', 'attsEl', 'listEl', 'searchEl', 'fileEl', 'overlayEl',
  'mentionEl', 'actEl', 'fmtDur'];
const SET = new Set(OLD);

let bad = 0;
for (const f of fs.readdirSync(DIR).filter(x => x.endsWith('.js')).sort()) {
  const src = fs.readFileSync(path.join(DIR, f), 'utf8');
  const hits = [];
  let i = 0, prev = '';
  const n = src.length;
  while (i < n) {
    const c = src[i], c2 = src.substr(i, 2);
    if (c2 === '//') { const e = src.indexOf('\n', i); i = e === -1 ? n : e; continue; }
    if (c2 === '/*') { const e = src.indexOf('*/', i + 2); i = e === -1 ? n : e + 2; continue; }
    if (c === "'" || c === '"') {
      i++;
      while (i < n && src[i] !== c) { if (src[i] === '\\') i++; i++; }
      i++; prev = 'x'; continue;
    }
    if (c === '`') {
      i++;
      while (i < n) {
        if (src[i] === '\\') { i += 2; continue; }
        if (src[i] === '`') { i++; break; }
        if (src.substr(i, 2) === '${') {
          // ${} 内是代码:递归扫描子串(简单起见单独跑一次子扫描)
          let d = 1, k = i + 2;
          while (k < n && d > 0) {
            if (src[k] === '{' || src[k] === '(' || src[k] === '[') d++;
            else if (src[k] === '}' || src[k] === ')' || src[k] === ']') { d--; if (d === 0) break; }
            else if (src[k] === "'" || src[k] === '"' || src[k] === '`') {
              const q2 = src[k]; k++;
              while (k < n && src[k] !== q2) { if (src[k] === '\\') k++; if (src[k] === '\n') break; k++; }
            }
            k++;
          }
          const inner = src.slice(i + 2, k);
          // 复用主循环逻辑扫 inner:直接递归调用本文件的扫描(函数化不足,这里内联简化:
          // inner 内的字符串/注释同样要排除——递归整段)
          hits.push(...scanCode(inner, '  ${}'));
          i = k + 1; continue;
        }
        i++;
      }
      prev = 'x'; continue;
    }
    if (c === '/') {
      const isDiv = /[0-9a-zA-Z_$)\]"']/.test(prev);
      if (!isDiv) {
        i++; let inCls = false;
        while (i < n) {
          if (src[i] === '\\') { i += 2; continue; }
          if (src[i] === '[') inCls = true;
          else if (src[i] === ']') inCls = false;
          else if (src[i] === '/' && !inCls) break;
          if (src[i] === '\n') break;
          i++;
        }
        i++; prev = 'x'; continue;
      }
      prev = '/'; i++; continue;
    }
    if (/[A-Za-z_$]/.test(c)) {
      let j = i;
      while (j < n && /[\w$]/.test(src[j])) j++;
      const word = src.slice(i, j);
      // 左界:单 '.' 是属性访问;但 '...' 是展开运算符,不是属性
      const isProp = /[.\w$]/.test(prev) && !(prev === '.' && outPrev3(src, i) === '..');
      if (SET.has(word) && !isProp) {
        const line = src.slice(0, i).split('\n').length;
        hits.push(`    line ${line}: ${word} | ${src.split('\n')[line - 1].trim().slice(0, 80)}`);
      }
      i = j; prev = 'x'; continue;
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  if (hits.length) { bad++; console.log(f + '\n' + hits.join('\n')); }
}
if (!bad) console.log('CLEAN: 无代码态残留');

// 内联子扫描(${} 内):与主逻辑同规则
function scanCode(src, tag) {
  const hits = [];
  let i = 0, prev = '';
  const n = src.length;
  while (i < n) {
    const c = src[i], c2 = src.substr(i, 2);
    if (c2 === '//') { const e = src.indexOf('\n', i); i = e === -1 ? n : e; continue; }
    if (c2 === '/*') { const e = src.indexOf('*/', i + 2); i = e === -1 ? n : e + 2; continue; }
    if (c === "'" || c === '"') {
      i++;
      while (i < n && src[i] !== c) { if (src[i] === '\\') i++; i++; }
      i++; prev = 'x'; continue;
    }
    if (c === '`') { i++; while (i < n && src[i] !== '`') { if (src[i] === '\\') i++; i++; } i++; prev = 'x'; continue; }
    if (c === '/') {
      const isDiv = /[0-9a-zA-Z_$)\]"']/.test(prev);
      if (!isDiv) { i++; while (i < n && src[i] !== '\n' && src[i] !== '/') { if (src[i] === '\\') i++; i++; } i++; prev = 'x'; continue; }
      prev = '/'; i++; continue;
    }
    if (/[A-Za-z_$]/.test(c)) {
      let j = i;
      while (j < n && /[\w$]/.test(src[j])) j++;
      const word = src.slice(i, j);
      if (SET.has(word) && !/[.\w$]/.test(prev)) hits.push('    ${}内: ' + word + ' | ' + src.trim().slice(0, 80));
      i = j; prev = 'x'; continue;
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  return hits;
}

// 判 src[i-1] 前两个字符是否构成 '..'(即 '...' 展开的一部分)
function outPrev3(src, i) {
  return i >= 3 ? src.slice(i - 3, i - 1) : '';
}
