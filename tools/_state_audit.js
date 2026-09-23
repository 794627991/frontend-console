// state 名对账:01-state.js 的每个 let 名,必须在 20-main.js 的 builder 内有赋值。
'use strict';
const fs = require('fs'), path = require('path');
const DIR = 'web/js/harness';
const stateSrc = fs.readFileSync(path.join(DIR, '01-state.js'), 'utf8');
const mainSrc = fs.readFileSync(path.join(DIR, '20-main.js'), 'utf8');
const names = [...stateSrc.matchAll(/^let\s+([A-Za-z_$][\w$]*)/gm)].map(m => m[1]);
console.log('state 声明:', names.length);
const problems = [];
for (const n of names) {
  const re = new RegExp('(?<![.\\w$])' + n.replace(/\$/g, '\\$') + '\\s*=(?!=)', 'm');
  if (!re.test(mainSrc)) problems.push(n);
}
if (problems.length) {
  console.log('⚠ main 无赋值:', problems.join(' '));
  process.exit(1);
}
console.log('全部 38 名在 main.js builder 内有赋值 ✓');
