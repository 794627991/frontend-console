// 前端主链 stub 冒烟 v2:buildTab → refreshSessions → switchTo(历史渲染全链)
// → handleEvent 事件流(文本/工具/子代理/回传/结果)。任何 ReferenceError/TypeError 即 FAIL。
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function mkEl(tag) {
  const el = {
    tag: tag || 'div', style: new Proxy({}, { get: () => '', set: () => true }),
    dataset: {}, classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    children: [], innerHTML: '', textContent: '', value: '', files: [],
    appendChild(c) { this.children.push(c); return c; },
    insertBefore(c) { return c; }, removeChild(c) { return c; }, remove() {},
    querySelector: () => mkEl(), querySelectorAll: () => [],
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    hasAttribute: () => false, toggleAttribute() {}, getAttributeNames: () => [],
    insertAdjacentHTML() {}, insertAdjacentElement(c) { return c; }, insertAdjacentText() {},
    after() {}, before() {}, replaceWith() {}, append() {}, prepend() {},
    matches: () => false,
    scrollIntoView() {},
    setSelectionRange() {},
    getRootNode: () => ({}), normalize() {}, cloneNode: () => mkEl(),
    hasAttribute: () => false, toggleAttribute() {}, getAttributeNames: () => [],
    insertAdjacentHTML() {}, insertAdjacentElement(c) { return c; }, insertAdjacentText() {},
    after() {}, before() {}, replaceWith() {}, append() {}, prepend() {},
    matches: () => false, webkitMatchesSelector: () => false,
    scrollIntoView() {}, getAnimations: () => [],
    setSelectionRange() {}, getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
    requestSubmit() {}, reportValidity: () => true, checkValidity: () => true,
    getRootNode: () => ({}), normalize() {}, cloneNode: () => mkEl(),
    focus() {}, blur() {}, click() {}, select() {}, scroll() {}, scrollTo() {},
    closest: () => ({ classList: { add() {}, remove() {}, toggle() {}, contains: () => false }, dataset: {}, style: {}, textContent: '' }), contains: () => false,
    getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 100, height: 100 }),
    scrollTop: 0, scrollHeight: 1000, clientHeight: 500, offsetWidth: 100, offsetHeight: 100,
    parentNode: null, parentElement: null, firstChild: null, lastChild: null,
    onclick: null, oninput: null, onchange: null, onscroll: null, onkeydown: null,
    compareDocumentPosition: () => 0,
  };
  const parent = { appendChild() {}, removeChild() {}, querySelector: () => mkEl(), querySelectorAll: () => [], contains: () => false, classList: { add() {}, remove() {}, toggle() {}, contains: () => false }, dataset: {} };
  el.parentNode = parent; el.parentElement = parent;
  return el;
}

const j = (o) => ({ ok: true, status: 200, json: async () => o });

// ---- 假数据 ----
const SESSIONS = { ok: true, sessions: [
  { sid: 's1', title: '重构任务', model: 'm', cwd: 'C:/x', ts: Date.now(), has_history: true, kind: 'harness' },
] };
const CONNECT = { ok: true, sid: 's1', port_id: 'harness:gui', kind: 'harness', cwd: 'C:/x', model: 'm', title: '重构任务' };
const LINES = [
  { type: 'user', text: '你好,帮我看看这个文件', ts: Date.now() },
  { type: 'assistant', text: '好的,我先读文件。', model: 'glm', ts: Date.now() },
  { type: 'tool_use', name: 'Read', input: { file_path: 'C:/x/a.py' }, ts: Date.now() },
  { type: 'tool_result', name: 'Read', content: 'x=1', ts: Date.now() },
  { type: 'assistant', text: '文件内容是 x=1。', model: 'glm', ts: Date.now() },
  { type: 'result', dur_ms: 1234, ts: Date.now() },
];
const RESPONSES = {
  '/api/harness/sessions': SESSIONS,
  '/api/harness/connect': CONNECT,
  '/api/harness/transcript': { ok: true, lines: LINES, total: LINES.length },
  '/api/harness/events': { ok: true, events: [], seq: 100 },
  '/api/harness/ctx': { ok: true, used: 12345, ctx_max: 256000 },
  '/api/harness/roles': { ok: false },
  '/api/harness/agent_models': { ok: false },
  '/api/harness/models': { ok: true, models: ['glm'], default: 'glm' },
  '/api/harness/vision_status': { ok: true, enabled: false },
  '/api/harness/mcp_list': { ok: true, mcp: [] },
  '/api/harness/system_prompt': { ok: true, prompt: '' },
  '/api/harness/recoverable': { ok: true, items: [] },
  '/api/harness/skills': { ok: true, skills: [] },
  '/api/harness/send': { ok: true },
  '/api/file_info': { ok: true, size: 1 },
};
function pick(url) {
  const base = url.split('?')[0];
  if (RESPONSES[base]) return RESPONSES[base];
  if (base.includes('/api/harness/')) return { ok: true };
  return { ok: false };
}

const documentStub = {
  createElement: (t) => mkEl(t), createTextNode: (t) => ({ textContent: t }),
  querySelector: () => mkEl(), querySelectorAll: () => [],
  getElementById: () => mkEl(), addEventListener() {}, removeEventListener() {},
  body: mkEl('body'), documentElement: mkEl(), head: mkEl(), hidden: false,
  activeElement: null, createEvent: () => ({ initEvent() {} }),
};
const sandbox = {
  console, setTimeout, clearTimeout,
  setInterval: () => 1, clearInterval() {},
  requestAnimationFrame: (f) => { try { f(); } catch (e) {} return 1; },
  cancelAnimationFrame() {},
  document: documentStub,
  navigator: { userAgent: 'node', clipboard: { writeText: async () => {} } },
  location: { href: 'http://x/', protocol: 'http:', pathname: '/' },
  localStorage: { _d: {}, getItem(k) { return this._d[k] ?? null; }, setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  fetch: async (url, opts) => {
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    const base = pick(String(url));
    // connect 带回 sid;send 回 ok
    if (String(url).startsWith('/api/harness/connect')) return j({ ...base, ...body, sid: body.sid || 's1', ok: true });
    return j(base);
  },
  CSS: { escape: (s) => s },
  alert() {}, confirm: () => false, prompt: () => null,
  URL: { createObjectURL: () => '' }, Blob: class {}, File: class {},
  EventSource: class { addEventListener() {} close() {} },
  MutationObserver: class { observe() {} disconnect() {} },
  ResizeObserver: class { observe() {} disconnect() {} },
  CustomEvent: class {}, Event: class {},
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  performance: { now: () => Date.now() },
  hljs: { highlight: () => ({ value: '' }), highlightElement() {}, configure() {} },
  markdownit: () => ({ render: () => '', inline: () => ({ content: '' }) }),
  _initTabDrag() {}, switchTab() {}, showBanner() {}, esc: (s) => String(s),
  activePortId: 'x', ports: {},
  connections: {}, tabs: mkEl(), termArea: mkEl(),
  q: () => mkEl(), showWelcome() {},
  connectClaude() {}, openClaudeSetup() {}, refreshSidebar() {}, buildProxyTab() {},
};
sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
vm.createContext(sandbox);

const files = fs.readdirSync(process.argv[2]).filter(f => f.endsWith('.js')).sort();
for (const f of files) {
  vm.runInContext(fs.readFileSync(path.join(process.argv[2], f), 'utf8'), sandbox, { filename: f });
}
console.log('— 21 文件加载 OK —');

(async () => {
  const run = async (code, tag) => {
    try { await vm.runInContext(code, sandbox, { filename: tag, timeout: 8000 }); console.log('OK ', tag); return true; }
    catch (e) {
      console.log('ERR', tag, '→', e.constructor.name + ':', e.message);
      const st = (e.stack || '').split('\n').slice(0, 4).join('\n     ');
      console.log('     ' + st);
      return false;
    }
  };
  let ok = true;
  ok = await run('buildClaudeHarnessTab({})', 'buildTab');
  ok = await run('refreshSessions()', 'refreshSessions') && ok;
  ok = await run('switchTo("s1")', 'switchTo→connect+历史渲染') && ok;
  ok = await run(`
    handleEvent({type:'system', subtype:'init', sid:'s1', session_id:'cs1', model:'glm', cwd:'C:/x'});
    handleEvent({type:'assistant', message:{content:[{type:'text',text:'回复文本'}]}, session_id:'cs1'});
    handleEvent({type:'assistant', message:{content:[{type:'tool_use',id:'t1',name:'Bash',input:{command:'ls'}}]}, session_id:'cs1'});
    handleEvent({type:'user', message:{content:[{type:'tool_result',tool_use_id:'t1',content:'out'}]}, session_id:'cs1'});
    handleEvent({type:'result', dur_ms:99, session_id:'cs1'});
    handleEvent({kind:'ask', req_id:'rq1', title:'选择实现方案', questions:[{question:'用A还是B', options:[{label:'A'},{label:'B'}]}]});
    handleEvent({kind:'ask_done', req_id:'rq1', answer:{'用A还是B':'A'}});
  `, 'handleEvent 事件流(文本/工具/结果)') && ok;
  ok = await run('send()', 'send(排队→dispatch)') && ok;
  console.log(ok ? '\n=== 主链冒烟全部通过 ===' : '\n=== 有失败,见上 ===');
  process.exit(ok ? 0 : 1);
})();
