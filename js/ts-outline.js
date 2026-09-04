// ============================================================
// web-tree-sitter 代码大纲解析器（GitHub tree-sitter，20k+ star，MIT）
// VSCode/GitHub 代码导航同款底层：增量解析系统，WASM 运行时浏览器跑。
// vendor 化离线：vendor/tree-sitter/package/（运行时）+ lang-*/（grammar wasm）
// 集成范围（用户明确）：C 系（.c/.h/.cpp/.hpp…）、bash/sh、json、python——
// 其余语言大纲回落正则/井号规则，不装 grammar（体积与维护都不值）。
// 用法：打开代码文件后大纲面板调 tsOutline(src, ext) → 定义列表。
// ============================================================

// 后缀 → 语言名（仅四类，其余返回 null 走正则/井号）
const TS_LANG_EXT = {
  '.py': 'python', '.pyw': 'python', '.pyi': 'python',
  '.c': 'c', '.h': 'c',
  '.cpp': 'cpp', '.hpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hh': 'cpp', '.hxx': 'cpp', '.mm': 'cpp',
  '.sh': 'bash', '.bash': 'bash',
  '.json': 'json',
};
const _TS_WASM = {
  python: '/vendor/tree-sitter/lang-python/tree-sitter-python.wasm',
  c: '/vendor/tree-sitter/lang-c/tree-sitter-c.wasm',
  cpp: '/vendor/tree-sitter/lang-cpp/tree-sitter-cpp.wasm',
  bash: '/vendor/tree-sitter/lang-bash/tree-sitter-bash.wasm',
  json: '/vendor/tree-sitter/lang-json/tree-sitter-json.wasm',
};
// editor.js 用：后缀是否在 tree-sitter 支持范围（决定走异步语法树还是同步正则）
function TS_LANG_EXT_HAS(ext) {
  return Object.prototype.hasOwnProperty.call(TS_LANG_EXT, (ext || '').toLowerCase());
}

let _tsParser = null;          // Parser 单例
const _tsLangs = {};           // 已加载语言
const _tsLoading = {};         // 加载中 promise（防并发重复加载）

// web-tree-sitter 浏览器全局名确认：package.json main 是 tree-sitter.cjs（UMI 不行），
// tree-sitter.js 是 ESM——script 加载后全局是 Parser？先动态 import ESM 更干净。
let _tsMod = null;             // tree-sitter ESM 模块（命名导出 Parser/Language，无 default）
async function tsInit() {
  if (_tsParser) return _tsParser;
  if (!_tsMod) {
    _tsMod = await import('/vendor/tree-sitter/package/tree-sitter.js');
  }
  const Parser = _tsMod.Parser;
  if (!Parser) throw new Error('tree-sitter ESM 未导出 Parser');
  await Parser.init({
    locateFile: () => '/vendor/tree-sitter/package/tree-sitter.wasm',
  });
  _tsParser = new Parser();
  return _tsParser;
}

async function tsLoadLang(name) {
  if (_tsLangs[name]) return _tsLangs[name];
  if (_tsLoading[name]) return _tsLoading[name];
  const wasmPath = _TS_WASM[name];
  if (!wasmPath) return null;
  _tsLoading[name] = (async () => {
    await tsInit();
    // Language 是模块的独立命名导出——不是 Parser 的静态属性
    // （曾写 Parser.Language.load，undefined.load 抛错被吞 → 永远走正则兜底）
    const Language = _tsMod.Language;
    if (!Language) throw new Error('tree-sitter ESM 未导出 Language');
    const lang = await Language.load(wasmPath);
    return lang;
  })();
  const lang = await _tsLoading[name];
  _tsLangs[name] = lang;
  return lang;
}

// 语言 → 语法树定义节点类型（大纲关心的节点）+ 取名函数
// className 管类/类型节点，funcName 管函数节点（C 系两者结构不同，分开取）
const _TS_SYM_RULES = {
  python: {
    classes: ['class_definition'], functions: ['function_definition'],
    className: n => _tsTextOf(n, 'identifier'), funcName: n => _tsTextOf(n, 'identifier'),
  },
  c: {
    classes: ['struct_specifier', 'union_specifier', 'enum_specifier', 'type_definition'],
    functions: ['function_definition'],
    // 类型名：type_identifier 优先（enum 内 enumerator 也是 identifier，递归找会误取）
    className: n => _tsTextOf(n, 'type_identifier') || _tsTextOf(n, 'field_identifier') || _tsTextOf(n, 'identifier'),
    // 函数名：declarator 嵌套层级不定，递归找最深 identifier
    funcName: n => _tsCFuncName(n),
  },
  cpp: {
    classes: ['class_specifier', 'struct_specifier', 'union_specifier', 'enum_specifier'],
    functions: ['function_definition'],
    className: n => _tsTextOf(n, 'name') || _tsTextOf(n, 'type_identifier'),
    funcName: n => _tsCFuncName(n),
  },
  bash: {
    classes: [], functions: ['function_definition'],
    className: n => null, funcName: n => _tsTextOf(n, 'name') || _tsTextOf(n, 'word'),
  },
  json: {
    classes: [], functions: [],
    className: n => null, funcName: n => null,
  },
};

function _tsTextOf(node, childType) {
  // 命名子节点取文本；找不到返回 null
  let c = node.firstChild;
  while (c) {
    if (c.type === childType) return c.text;
    c = c.nextSibling;
  }
  return null;
}
// C 系函数定义取名：function_definition → declarator → function_declarator → declarator → identifier
// （嵌套 declarator 层级不定，递归找最深 identifier）
function _tsCFuncName(node) {
  const findIdent = n => {
    let c = n.firstChild;
    while (c) {
      if (c.type === 'identifier') return c.text;
      const r = findIdent(c);
      if (r) return r;
      c = c.nextSibling;
    }
    return null;
  };
  return findIdent(node);
}

// ---- 大纲入口：返回 [{level, text, line, kind}] 或 null（语言不支持/解析失败）----
// level: 1=类/类型，2=函数/方法。失败时调用方回落正则或井号规则。
async function tsOutline(src, ext) {
  const langName = TS_LANG_EXT[(ext || '').toLowerCase()];
  if (!langName) return null;
  const rules = _TS_SYM_RULES[langName];
  if (!rules) return null;
  let lang, parser;
  try {
    lang = await tsLoadLang(langName);
    parser = await tsInit();
  } catch(e) {
    // 不再静默：加载失败时控制台留痕 + 大纲显示原因（否则永远无声回落正则，无从排查）
    console.error('[大纲] tree-sitter 初始化失败:', e);
    return { err: String(e && e.message || e) };
  }
  if (!lang) return null;
  try {
    parser.setLanguage(lang);
    const tree = parser.parse(src);
    const out = [];
    // json 特化：顶层键列表（最外层 object 的直接 pair 子节点）
    if (langName === 'json') {
      const walkJson = node => {
        for (const k of node.namedChildren) {
          if (k.type === 'pair') {
            const key = k.firstChild && k.firstChild.text;
            if (key) out.push({ level: 1, text: key.replace(/^"|"$/g, ''), line: k.startPosition.row + 1, kind: '键' });
          } else if (k.type === 'object' || k.type === 'array') {
            walkJson(k);
          }
        }
      };
      walkJson(tree.rootNode);
      return out;
    }
    const walk = (node, depth) => {
      if (depth > 30) return;   // 深度限幅防病态嵌套
      if (rules.classes.includes(node.type)) {
        const name = rules.className(node);
        if (name) out.push({ level: 1, text: name, line: node.startPosition.row + 1, kind: '类' });
      } else if (rules.functions.includes(node.type)) {
        const name = rules.funcName(node);
        if (name) out.push({ level: 2, text: name, line: node.startPosition.row + 1, kind: '函数' });
      }
      let c = node.firstChild;
      while (c) { walk(c, depth + 1); c = c.nextSibling; }
    };
    walk(tree.rootNode, 0);
    return out;
  } catch(e) {
    console.error('[大纲] tree-sitter 解析失败:', e);
    return { err: String(e && e.message || e) };
  }
}
