// ESLint 配置（a644 / a647 迁入 tools/js-tooling/）
//
// 目标：**只开低争议的「真缺陷」规则**，不碰格式类规则（引号/缩进/分号），
// 那会把 4 万行代码淹没成几万条噪音，真问题反而看不见。
//
// 这是"传统 script"项目：web/index.html 有 100 个 <script> 标签按顺序加载，
// 零 ES module，所以每个文件的顶层声明都是全局。跨文件互调全靠这个共享
// 命名空间 —— app-globals.json 由 tools/js_collect_globals.py 扫描生成。
//
// 用法（在项目根执行）：
//   python tools/js_collect_globals.py           # 先刷新全局清单
//   node tools/js-tooling/run.mjs lint           # 扫前端
//   node tools/js-tooling/run.mjs lint:baseline  # 落 JSON 基线
//   node tools/js-tooling/run.mjs test           # node 单元测试
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import globals from 'globals';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');

const appGlobals = JSON.parse(
  fs.readFileSync(path.join(ROOT, 'tests/js/app-globals.json'), 'utf8'));

export default [
  {
    files: ['web/js/**/*.js'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'script',           // 传统 script，不是 module
      globals: {
        ...globals.browser,           // window/document/fetch/...
        ...Object.fromEntries(appGlobals.map((g) => [g, 'writable'])),
      },
    },
    rules: {
      // ---- 真缺陷类（默认 error）----
      'no-undef': 'error',            // 引用了不存在的名字（拼错/漏加载）
      'no-dupe-keys': 'error',        // 对象字面量重复键（后者静默覆盖前者）
      'no-dupe-args': 'error',        // 函数重复形参
      'no-dupe-class-members': 'error',
      'no-duplicate-case': 'error',
      'no-unreachable': 'error',      // return/throw 之后永远执行不到的代码
      'no-cond-assign': ['error', 'except-parens'],  // if (x = y) 手误
      'no-self-compare': 'error',     // x === x
      'no-constant-condition': ['error', { checkLoops: false }],
      'no-func-assign': 'error',      // 有意 monkey-patch 用行内注释豁免
      'no-obj-calls': 'error',        // Math() / JSON() 当函数调
      'no-sparse-arrays': 'error',
      'no-unsafe-negation': 'error',  // !key in obj
      'valid-typeof': 'error',
      'use-isnan': 'error',

      // ---- 未用变量（默认 warn：存量必然多，先观察）----
      'no-unused-vars': ['warn', {
        args: 'after-used',           // 只报最后一个使用之后的未用形参
        varsIgnorePattern: '^_',
        argsIgnorePattern: '^_',
        caughtErrors: 'none',         // catch(e) 不用很常见，不报
      }],
    },
  },
  {
    // node 侧脚本与测试
    files: ['tests/js/**/*.{js,mjs}', 'tools/**/*.mjs'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: { ...globals.node },
    },
  },
];
