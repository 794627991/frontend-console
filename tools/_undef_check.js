// 全标识符「未定义引用」检查器 v2(教训:上版只查调用形态,flow.value 全漏)。
// 词法感知提取代码态全部标识符(含 .value 前段),减去:
//   本文件 const/let/var/function/参数/捕获变量 + 全部 21 文件顶层名
//   + JS 内置 + 已知外部全局 + 常见局部惯用名
// 报告「代码态引用但全项目无定义」的名字(即潜在 ReferenceError)。
'use strict';
const fs = require('fs');
const path = require('path');
const DIR = process.argv[2];

// ---- 收集全部文件顶层定义名 ----
const files = fs.readdirSync(DIR).filter(x => x.endsWith('.js')).sort();
const defined = new Set();
for (const f of files) {
  const src = fs.readFileSync(path.join(DIR, f), 'utf8');
  for (const m of src.matchAll(/^[ \t]*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/gm)) defined.add(m[1]);
  for (const m of src.matchAll(/^[ \t]*(?:const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) defined.add(m[1]);
}

const BUILTIN = new Set(('window document localStorage sessionStorage fetch JSON Math Object Array String ' +
  'Number Boolean Date RegExp Error TypeError RangeError Promise Map Set WeakMap WeakSet Symbol Proxy Reflect ' +
  'parseInt parseFloat isNaN isFinite setTimeout setInterval clearTimeout clearInterval requestAnimationFrame ' +
  'cancelAnimationFrame alert confirm prompt console location history navigator screen crypto CSS HTMLElement ' +
  'MutationObserver ResizeObserver IntersectionObserver CustomEvent Event EventTarget URL URLSearchParams ' +
  'Blob File FileReader FormData XMLHttpRequest WebSocket Worker Image Audio Video FontFace ' +
  'encodeURIComponent decodeURIComponent encodeURI decodeURI atob btoa structuredClone queueMicrotask ' +
  'performance Intl BigInt undefined NaN Infinity arguments this super import meta module exports require ' +
  'process globalThis __dirname __filenameof null true false void delete typeof instanceof in of new var let const function class return if else for while do switch case break continue try catch finally throw async await yield static get set').split(/\s+/));
const EXTERNAL = new Set(('esc q showBanner showBannerErr tabs termArea connections switchTab _initTabDrag ' +
  'hljs md markdownit renderMarkdown showToast xterm FitAddon SearchAddon WebLinksAddon WebGLAddon monaco ' +
  'EditorJS Header List Checklist Table Image Quote Code Delimiter Marker InlineCode editor ' +
  'connectClaude claudeSessions harnessSnipStart openClaudeSetup refreshSidebar buildProxyTab HgReadonly ' +
  'claudeButtonAction setClaudeUiMode buildClaudeHarnessTab _hgPanelEnterHook _hgFlowUnloadInit ' +
  'harnessAddFilesByPath _hgDynTick _hgSubTailTick activePortId ports cssText').split(/\s+/));
// 局部惯用短名(回调参数/循环变量,人工排除噪音太贵,粗滤 1-2 字符+常见词)
const COMMON_LOCAL = new Set(('e el ev err error cb fn res resp resp2 r s t k v x y z i j n len idx item items ' +
  'data cfg opts o b a c d f g h l m p u w row rows col cols line lines text txt html str key keys val vals ' +
  'name label title id ids type kind state st flag on off node nodes list map set obj arr children child parent ' +
  'dom el2 raw cur prev next first last total count num size width height top left right bottom min max sum ms ' +
  'ts t0 t1 dur start end delta buf out src dst ret tmp tmp2 found hit all any ok msg info body head tail root ' +
  'btn box card chip bar pill tag seg block grp grid pane panel tab tabs win doc frag range segs blocks parts ' +
  'words word ch char pos index matcher match matches rest extra args params argv env cwd sid seq tsms ms2 ' +
  'done busy alive live dead open closed visible hidden active run running').split(/\s+/));

function scanFile(f, src) {
  const localDefs = new Set();
  for (const m of src.matchAll(/\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)/g)) localDefs.add(m[1]);
  for (const m of src.matchAll(/\b(?:of|in)\s+([A-Za-z_$][\w$]*)/g)) localDefs.add(m[1]);
  for (const m of src.matchAll(/\(\s*([A-Za-z_$][\w$]*(?:\s*,\s*[A-Za-z_$][\w$]*)*)\s*\)\s*=>/g))
    for (const p of m[1].split(',')) localDefs.add(p.trim());
  for (const m of src.matchAll(/\bfunction\s*[\w$]*\s*\(([^)]*)\)/g))
    for (const p of m[1].split(',')) { const t = p.trim().split(/[=\s]/)[0]; if (/^[A-Za-z_$][\w$]*$/.test(t)) localDefs.add(t); }
  for (const m of src.matchAll(/\bcatch\s*\(\s*([A-Za-z_$][\w$]*)/g)) localDefs.add(m[1]);
  for (const m of src.matchAll(/\.(?:forEach|map|filter|some|every|reduce|sort)\(\s*(?:function\s*(?:[\w$]*)?\s*\()?\s*([A-Za-z_$][\w$]*)/g)) localDefs.add(m[1]);
  for (const m of src.matchAll(/\b([a-z][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()/g)) localDefs.add(m[1]);

  const hits = [];
  let i = 0, prev = '';
  const n = src.length;
  const isPropAt = (idx) => {
    if (idx === 0) return false;
    const pc = src[idx - 1];
    if (!/[.\w$]/.test(pc)) return false;
    if (pc === '.') {
      // ...x 展开豁免:前两字符是 '..'
      if (idx >= 3 && src[idx - 3] === '.' && src[idx - 2] === '.') return false;
      // ?.x 可选链也是属性
      return true;
    }
    return true; // 前面是 \w $:是更长标识符的内部
  };
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
          hits.push(...scanFile(f + ':${}', src.slice(i + 2, k)));
          i = k + 1; continue;
        }
        i++;
      }
      prev = 'x'; continue;
    }
    if (c === '/') {
      const isDiv = /[0-9a-zA-Z_$)\]"'`.]/.test(prev);
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
      // 键位置豁免:word 后紧跟 ':'(对象键/标签),且左界是 { 或 , 或行首缩进
      let isKey = false;
      if (!isPropAt(i) && /[{,]\s*$/.test(src.slice(Math.max(0, i - 40), i).replace(/[^\n]/g, m => m))) {
        let k = j;
        while (k < n && /\s/.test(src[k])) k++;
        if (src[k] === ':') isKey = true;
      }
      if (word.length >= 3 && !isKey && !isPropAt(i) && !localDefs.has(word) && !defined.has(word)
          && !BUILTIN.has(word) && !EXTERNAL.has(word) && !COMMON_LOCAL.has(word)) {
        const line = src.slice(0, i).split('\n').length;
        hits.push(`    line ${line}: ${word} | ${src.split('\n')[line - 1].trim().slice(0, 90)}`);
      }
      i = j; prev = 'x'; continue;
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  return hits;
}

let bad = 0;
for (const f of files) {
  const hits = scanFile(f, fs.readFileSync(path.join(DIR, f), 'utf8'));
  if (hits.length) { bad++; console.log(f + '\n' + hits.join('\n')); }
}
console.log(bad ? `\n${bad} 文件有疑似未定义引用(人工核对)` : 'CLEAN');
