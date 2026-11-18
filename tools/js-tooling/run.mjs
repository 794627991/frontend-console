#!/usr/bin/env node
// JS 工具链统一入口（a647：从项目根迁到 tools/js-tooling/）
//
// 为什么要有这个包装：ESLint 的配置查找从 **cwd** 往上找，而配置里写的
// 匹配路径是相对项目根的（web/js/**）。在 tools/js-tooling/ 里直接跑
// eslint 会找不到配置或匹配不到文件。这里统一 cd 到项目根再执行，让
// 「在哪儿调用都一样」。
//
// 用法（任意目录）：
//   node tools/js-tooling/run.mjs lint
//   node tools/js-tooling/run.mjs lint:baseline
//   node tools/js-tooling/run.mjs test
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const eslint = path.join(HERE, 'node_modules', 'eslint', 'bin', 'eslint.js');
// 配置在 tools/js-tooling/ 里，但 cwd 必须是项目根（配置的 files 匹配
// 路径相对项目根）。ESLint 只从 cwd 向上找配置，所以显式 --config 指定。
const config = path.join(HERE, 'eslint.config.mjs');

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { cwd: ROOT, stdio: 'inherit', shell: false, ...opts });
    p.on('close', (code) => resolve(code ?? 1));
    p.on('error', (e) => { console.error(e.message); resolve(1); });
  });
}

const task = process.argv[2] || 'lint';

if (task === 'lint') {
  const code = await run(process.execPath, [eslint, '--config', config, 'web/js'], {});
  process.exit(code);
} else if (task === 'lint:baseline') {
  const fs = await import('node:fs');
  const outPath = path.join(ROOT, 'tests', 'js', 'eslint-raw.json');
  const p = spawn(process.execPath, [eslint, '--config', config, 'web/js', '-f', 'json'],
                  { cwd: ROOT, stdio: ['ignore', 'pipe', 'inherit'] });
  const chunks = [];
  p.stdout.on('data', (c) => chunks.push(c));
  p.on('close', () => {
    fs.writeFileSync(outPath, Buffer.concat(chunks));
    console.log('基线快照 →', path.relative(ROOT, outPath));
  });
} else if (task === 'test') {
  const code = await run(process.execPath,
    ['--test', 'tests/js/log-viewer-scroll.test.mjs'], {});
  process.exit(code);
} else {
  console.error('未知任务：' + task + '（可用：lint / lint:baseline / test）');
  process.exit(2);
}
