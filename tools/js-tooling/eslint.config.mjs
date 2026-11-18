// ESLint 配置（a644 / a647 迁入 tools/js-tooling/）
//
// 目标：**只开低争议的「真缺陷」规则**，不碰格式类规则（引号/缩进/分号），
// 那会把 4 万行代码淹没成几万条噪音，真问题反而看不见。
//
// 模块化一期/二期后（js-modularization 分支）：76 个前端 js 中 69 个已转
// type="module"（模块作用域 + window 挂载/存取器互调，零 import/export）。
// 留守经典 7 个（含 screenshot 独立页）：workerbase（fetch 补丁必须最先）、
// icons/util（底层地基）、theme（首帧时机敏感——快照挂载 split-brain 审计
// 后回滚，见审计修复提交）、ts-outline（动态 import tree-sitter 的宿主）、
// vcs-panel/vcs-git-ops（并行会话开发中）、screenshot.html。跨文件互调
// 依旧靠共享命名空间（模块侧经 window 挂载/存取器显式化）——
// app-globals.json 由 tools/js_collect_globals.py 扫描生成（模块文件只收
// window 挂载与 defineProperty 存取器，不收内部声明）。
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

// 模块化一期：index.html 里 type="module" 加载的文件（单一真源
// tests/js/modules.txt，由 tools/js_script_manifest.py 派生）。这些文件按
// ESM 解析——import/export 语法合法、顶层 this 为 undefined、自动 strict。
let moduleFiles = [];
try {
  // modules.txt 里的路径相对 web/（js/a11y.js），eslint 的 files 匹配相对
  // 仓库根——必须加 web/ 前缀，否则这块静默不生效（模块文件仍按 script
  // 解析，import/export 直接报语法错，且自动 strict 口径全丢）。
  moduleFiles = fs.readFileSync(path.join(ROOT, 'tests/js/modules.txt'), 'utf8')
    .split('\n').map((s) => s.trim()).filter(Boolean)
    .map((s) => 'web/' + s);
} catch { /* modules.txt 不存在 = 尚无模块文件 */ }

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
    // 模块化一期：已转 ES module 的前端文件（清单来自 modules.txt）。
    // 仍是传统全局互调——globals 全量保留（模块读全局照常解析）；这里只把
    // 解析模式切成 module：import/export 合法化 + 自动 strict 的语法口径。
    files: moduleFiles.length ? moduleFiles : ['tools/__never__.js'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...Object.fromEntries(appGlobals.map((g) => [g, 'writable'])),
      },
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
