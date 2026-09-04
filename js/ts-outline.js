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
    functions: ['function_definition', 'preproc_function_def'],
    // 宏/全局变量：大纲导航的次要目标（VSCode C 大纲同款粒度）
    macros: ['preproc_def', 'preproc_call'],
    globals: ['declaration'],
    // 类型名：type_identifier 优先（enum 内 enumerator 也是 identifier，递归找会误取）
    className: n => _tsTextOf(n, 'type_identifier') || _tsTextOf(n, 'field_identifier') || _tsTextOf(n, 'identifier'),
    // 函数名：declarator 嵌套层级不定，递归找最深 identifier
    funcName: n => _tsCFuncName(n),
  },
  cpp: {
    classes: ['class_specifier', 'struct_specifier', 'union_specifier', 'enum_specifier'],
    functions: ['function_definition', 'preproc_function_def'],
    macros: ['preproc_def', 'preproc_call'],
    globals: ['declaration'],
    className: n => _tsTextOf(n, 'name') || _tsTextOf(n, 'type_identifier'),
    funcName: n => _tsCFuncName(n),
  },
  bash: {
    classes: [], functions: ['function_definition'],
    globals: ['variable_assignment'],   // 顶层 VAR=value 赋值（不在函数内才列）
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
    // json 特化：递归列出全部键（层级=嵌套深度）。大 json 限深度 8/条目 2000 防爆
    if (langName === 'json') {
      const keyOf = pair => {
        const key = pair.firstChild && pair.firstChild.text;
        return key ? key.replace(/^"|"$/g, '') : null;
      };
      const walkJson = (node, depth) => {
        if (depth > 8 || out.length > 2000) return;
        for (const k of node.namedChildren) {
          if (k.type === 'pair') {
            const key = keyOf(k);
            // kids：pair 的 value 含非空 object/array 且未超深度限——折叠箭头判定用
            const kids = depth < 8 && k.namedChildren.some(v =>
              (v.type === 'object' || v.type === 'array') && v.namedChildren.some(x => x.type === 'pair'));
            if (key) out.push({ level: Math.min(depth, 3), depth, text: key, line: k.startPosition.row + 1, kind: depth === 1 ? '键' : '子键', kids });
            // pair 的 value 是嵌套 object/array——必须进 pair 内部找（曾只扫顶层直接子，嵌套全丢）
            for (const v of k.namedChildren) {
              if (v.type === 'object' || v.type === 'array') walkJson(v, depth + 1);
            }
          } else if (k.type === 'object' || k.type === 'array') {
            walkJson(k, depth + 1);
          }
        }
      };
      walkJson(tree.rootNode, 1);
      return out;
    }
    const walk = (node, depth, inFunc) => {
      if (depth > 30) return;   // 深度限幅防病态嵌套
      if (rules.classes.includes(node.type)) {
        // struct/enum 引用（无定义体 field_declaration_list）不列——只列真定义。
        // 原型 int probe(struct device_ctx *c); 里的类型引用会重复出现
        const hasBody = node.namedChildren.some(c => c.type === 'field_declaration_list' || c.type === 'enumerator_list' || c.type === 'body');
        const name = hasBody ? rules.className(node) : null;
        if (name) out.push({ level: 1, text: name, line: node.startPosition.row + 1, kind: '类' });
      } else if (rules.functions.includes(node.type)) {
        const name = rules.funcName(node);
        if (name) out.push({ level: 2, text: name, line: node.startPosition.row + 1, kind: '函数' });
        inFunc = true;   // 函数体内不再列变量/宏（大纲只管导航粒度，VSCode 同款）
      } else if (!inFunc) {
        // 宏定义/全局变量：只在顶层（非函数体内）列出
        if (rules.macros && rules.macros.includes(node.type)) {
          // preproc_def → identifier（dump 实测，不是 directive）
          const name = _tsTextOf(node, 'identifier') || _tsTextOf(node, 'directive');
          if (name) out.push({ level: 3, text: name, line: node.startPosition.row + 1, kind: '宏' });
        } else if (rules.globals && rules.globals.includes(node.type)) {
          if (langName === 'bash') {
            const name = _tsTextOf(node, 'variable_name');
            if (name) out.push({ level: 3, text: name, line: node.startPosition.row + 1, kind: '变量' });
          } else {
            // C 系 declaration：函数原型（declarator→function_declarator）跳过——
            // 与函数定义重复导航没意义；包 struct/enum 定义体的也跳过（结构体已单独列）
            const hasStruct = (() => { let c = node.firstChild; while (c) { if (c.type === 'struct_specifier' || c.type === 'union_specifier' || c.type === 'enum_specifier') return true; c = c.nextSibling; } return false; })();
            const isProto = (() => { let c = node.firstChild; while (c) { if (c.type === 'function_declarator') return true; c = c.nextSibling; } return false; })();
            if (!hasStruct && !isProto) {
              const name = _tsCFuncName(node);
              if (name) out.push({ level: 3, text: name, line: node.startPosition.row + 1, kind: '变量' });
            }
          }
        }
      }
      let c = node.firstChild;
      while (c) { walk(c, depth + 1, inFunc); c = c.nextSibling; }
    };
    walk(tree.rootNode, 0, false);
    if (out.length > 5000) out.length = 5000;   // 大文件防爆
    return out;
  } catch(e) {
    console.error('[大纲] tree-sitter 解析失败:', e);
    return { err: String(e && e.message || e) };
  }
}
