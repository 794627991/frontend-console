// AST 级静态检查（espree + eslint-scope，来自 tools/js-tooling 依赖）
// 输出 JSON: { implicitWrites: [[file,name]], freeRefs: [[file,name]] }
import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import fs from 'fs';
import path from 'path';

const require = createRequire(new URL('../../tools/js-tooling/package.json', import.meta.url));
const espree = require('espree');
const eslintScope = require('eslint-scope');
const globalsPkg = require('globals');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const modules = fs.readFileSync(path.join(root, 'tests/js/modules.txt'), 'utf8')
  .split('\n').map(s => s.trim()).filter(Boolean).map(s => 'web/' + s);

// 全站 window 挂载 + classic 顶层声明 → known
const allJs = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = d + '/' + e.name;
    if (e.isDirectory()) walk(p); else if (e.name.endsWith('.js')) allJs.push(p);
  }
})(path.join(root, 'web/js'));
const mounted = new Set();
const classicTop = new Set();
for (const p of allJs) {
  const src = fs.readFileSync(p, 'utf8');
  for (const m of src.matchAll(/(?:window|root|self|globalThis)\.([A-Za-z_$][\w$]*)\s*=[^=]/g)) mounted.add(m[1]);
  for (const m of src.matchAll(/defineProperty\(\s*(?:window|root|self|globalThis)\s*,\s*['"]([A-Za-z_$][\w$]*)['"]/g)) mounted.add(m[1]);
}
const modSet = new Set(modules.map(s => path.join(root, s)));
for (const p of allJs) {
  const rel = 'web/' + path.relative(path.join(root, 'web'), p).replaceAll('\\', '/');
  if (modSet.has(p)) continue;
  try {
    const ast = espree.parse(fs.readFileSync(p, 'utf8'), { ecmaVersion: 2022, sourceType: 'script', range: true });
    for (const s of ast.body) {
      if (s.type === 'FunctionDeclaration' && s.id) classicTop.add(s.id.name);
      if (s.type === 'VariableDeclaration') for (const d of s.declarations) if (d.id.type === 'Identifier') classicTop.add(d.id.name);
    }
  } catch (e) {}
}
const known = new Set([...Object.keys(globalsPkg.browser), ...Object.keys(globalsPkg.es2021),
  ...mounted, ...classicTop,
  'monaco', 'XLSX', 'hljs', 'marked', 'EditorJS', 'CodeMirror', 'mammoth', 'JSZip',
  'pdfjsLib', 'Terminal', 'FitAddon', 'SearchAddon', 'WebLinksAddon', 'WebglAddon',
  'intelHexParse', 'DocsAPI', 'pywebview', 'require']);

const out = { implicitWrites: [], freeRefs: [] };
for (const f of modules) {
  const abs = path.join(root, f);
  let src, ast, sm;
  try {
    src = fs.readFileSync(abs, 'utf8');
    ast = espree.parse(src, { ecmaVersion: 2022, sourceType: 'module', range: true });
    sm = eslintScope.analyze(ast, { ecmaVersion: 2022, sourceType: 'module' });
  } catch (e) { out.implicitWrites.push([f, 'PARSE:' + e.message]); continue; }
  // 顶层 through 引用中，写入且非声明/挂载目标的名字
  for (const ref of sm.scopes[0].through) {
    if (!ref.isWrite()) continue;
    const n = ref.identifier.name;
    if (n === 'module' || n === 'exports') continue;
    // classic 脚本的全局词法声明（let/const/var 顶层）在 module 中可读写——
    // 这是合法的跨脚本共享（ES 全局环境记录含声明式记录），不算未声明写入
    if (classicTop.has(n) || mounted.has(n)) continue;
    out.implicitWrites.push([f, n]);
  }
  const free = [...new Set(sm.scopes[0].through.map(r => r.identifier.name))].filter(n => !known.has(n));
  if (free.length) out.freeRefs.push([f, free]);
}
console.log(JSON.stringify(out));
