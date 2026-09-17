// ============================================================
// Monaco Editor 桥接层（GitHub 微软开源，VSCode 同款内核）
// 本地 vendor 化（同 xterm/Editor.js 模式，离线可用）：
//   vendor/monaco/min/vs/ —— AMD loader（loader.js）按需加载语言/worker
// 后端路由 /vendor/*（server.py vendor_files）。
// 按需初始化：第一次打开 txt/md/code 文件才 require（启动零开销）。
// 主题跟随：换肤事件触发 _monacoApplyTheme，深浅底自动匹配全部 12 套皮肤。
// ============================================================

let _monacoReady = null;   // Promise<monaco>（单例，require 一次）

// 后缀 → Monaco 语言 ID 映射（覆盖工具支持的全部文本后缀）
const MONACO_LANG = {
  '.txt': 'plaintext', '.note': 'plaintext', '.log': 'plaintext', '.md': 'markdown',
  '.json': 'json', '.csv': 'plaintext', '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini',
  '.yaml': 'yaml', '.yml': 'yaml',
  '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.hpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp',
  '.py': 'python', '.pyw': 'python', '.pyi': 'python',
  '.bat': 'bat', '.cmd': 'bat', '.sh': 'shell', '.ps1': 'powershell',
  '.js': 'javascript', '.ts': 'typescript', '.html': 'html', '.css': 'css',
  '.xml': 'xml', '.sql': 'sql', '.dts': 'plaintext', '.dtsi': 'plaintext',
  '.mak': 'makefile', '.mk': 'makefile', '.s': 'plaintext', '.lds': 'plaintext',
  '.te': 'plaintext', '.fc': 'plaintext',
  // 补齐的后缀：Monaco basic-languages 有对应语言才真高亮，其余 plaintext 也可编辑
  '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin', '.rs': 'rust', '.go': 'go',
  '.rb': 'ruby', '.php': 'php', '.pl': 'perl', '.lua': 'lua', '.swift': 'swift',
  '.cs': 'csharp', '.vb': 'vb', '.fs': 'fsharp', '.fsx': 'fsharp', '.scala': 'scala',
  '.m': 'objective-c', '.mm': 'cpp', '.tcl': 'plaintext', '.r': 'r', '.jl': 'plaintext',
  '.nim': 'plaintext', '.zig': 'plaintext', '.v': 'plaintext', '.sv': 'plaintext',
  '.svh': 'plaintext', '.vhd': 'plaintext', '.vhdl': 'plaintext', '.asm': 'plaintext',
  '.sln': 'plaintext', '.props': 'xml', '.targets': 'xml', '.gradle': 'plaintext',
  '.properties': 'ini', '.toml': 'ini', '.proto': 'plaintext', '.tf': 'hcl',
  '.graphql': 'graphql', '.gql': 'graphql', '.ipynb': 'json', '.nix': 'plaintext',
};

function monacoLangFor(name) {
  const n = (name || '').toLowerCase();
  if (n === 'makefile' || n === 'readme') return 'makefile';
  const i = n.lastIndexOf('.');
  return MONACO_LANG[i > 0 ? n.slice(i) : ''] || 'plaintext';
}

// AMD loader：路径指向本地 /vendor/monaco/min/vs（与 npm 包目录结构一致）
// worker 走 MainThread chunk（Cross-origin 隔离 off 下唯一可行方案）
// 汉化：官方 zh-cn 语言包（包内自带 vs/nls.messages.zh-cn.js）必须在
// editor.main 之前加载——它写 globalThis._VSCODE_NLS_MESSAGES/_LANGUAGE，
// editor.main 初始化时读取并替换全部 UI 字符串（命令面板/查找/右键菜单全量汉化）
function monacoInit() {
  if (_monacoReady) return _monacoReady;
  _monacoReady = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/vendor/monaco/min/vs/loader.js';
    s.onload = () => {
      try {
        require.config({ paths: { vs: '/vendor/monaco/min/vs' } });
        // worker 走 data: URL + 注入绝对 baseUrl：
        // data: URL 的 worker 里 importScripts('相对路径') 无法解析（非层级 base），
        // workerMain.js 读 globalThis.MonacoEnvironment.baseUrl（读不到会回落 "../../../"
        // 相对路径 → loader 加载失败 → diff 计算/editorWorker 永远不就绪——
        // 曾因此 DiffEditor 一直卡「对比中…」无红绿高亮，普通编辑器不受影响
        // （着色在主线程，不用 worker）所以一直没暴露）。
        // 修法：data: 脚本里先写死 MonacoEnvironment.baseUrl 为绝对路径再 importScripts。
        const WORKER_BOOT = `
          globalThis.MonacoEnvironment = { baseUrl: '${location.origin}/vendor/monaco/min/' };
          importScripts('${location.origin}/vendor/monaco/min/vs/base/worker/workerMain.js');
        `;
        window.MonacoEnvironment = {
          getWorkerUrl: function() {
            return `data:text/javascript;charset=utf-8,${encodeURIComponent(WORKER_BOOT)}`;
          }
        };
        require(['vs/nls.messages.zh-cn', 'vs/editor/editor.main'], () => {
          const monaco = window.monaco;
          _monacoApplyTheme(monaco);
          resolve(monaco);
        }, err => reject(err));
      } catch (e) { reject(e); }
    };
    s.onerror = () => reject(new Error('loader.js 加载失败（vendor/monaco 缺失？）'));
    document.head.appendChild(s);
  });
  return _monacoReady;
}

// ---- 主题跟随：浅色 4 套（paper/dawn/mint/apricot）→ vs，其余 8 套深色 → vs-dark ----
const MONACO_LIGHT_THEMES = new Set(['paper', 'dawn', 'mint', 'apricot']);
function _monacoThemeName() {
  const t = document.documentElement.getAttribute('data-theme') || 'deepblue';
  // v2.25：custom 跟随自定义主题的亮暗标志（theme.js _isLight 同源数据）
  if (t === 'custom') {
    const d = (typeof _customData !== 'undefined' && _customData) || {};
    return d.light ? 'vs' : 'vs-dark';
  }
  return MONACO_LIGHT_THEMES.has(t) ? 'vs' : 'vs-dark';
}
function _monacoApplyTheme(monaco) {
  monaco.editor.setTheme(_monacoThemeName());
}
// 换肤钩子（theme.js applyTheme 后调用；Monaco 未加载时静默跳过，下次 init 再同步）
function monacoSyncTheme() {
  if (window.monaco) _monacoApplyTheme(window.monaco);
}

// ---- 创建编辑器实例（editor.js 调用入口）----
// holder: 容器 div；返回 monaco editor 实例（调用方存 conn.monaco）
async function monacoCreate(holder, value, langName) {
  // v2.2.2：引擎未就绪时的加载占位——exe(onefile) 下资源从 TEMP 解压目录
  // 读，慢机器首开引擎要数秒，空容器看着像白屏（同事机实锤「白屏、切一下
  // 别处才刷出来」）。占位条明示加载中，加载完自动移除
  let ph = null;
  if (!window.monaco) {
    ph = document.createElement('div');
    ph.className = 'monaco-loading';
    ph.textContent = '编辑器引擎加载中…（首次打开稍慢）';
    holder.appendChild(ph);
  }
  try {
    const monaco = await monacoInit();
    const ed = monaco.editor.create(holder, {
    value: typeof value === 'string' ? value : '',
    language: monacoLangFor(langName),
    theme: _monacoThemeName(),
    automaticLayout: true,        // 容器尺寸变化自动重排（分栏/折叠免手动 layout）
    fontSize: 13,
    lineNumbers: 'on',
    minimap: { enabled: true, size: 'proportional' },
    scrollBeyondLastLine: false,
    wordWrap: 'on',               // 超长行自动换行（同旧 textarea 行为）
    renderWhitespace: 'selection',
    tabSize: 4,
    // 20MB 上限文件防卡：大文件关 minimap/花哨渲染
    largeFileSize: 5 * 1024 * 1024,
    mouseWheelScrollSensitivity: 1,
    smoothScrolling: true,
    unicodeHighlight: { ambiguousCharacters: false },  // 中文标点不标黄
    scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
    padding: { top: 8, bottom: 60 },
  });
    return ed;
  } finally {
    if (ph) ph.remove();
  }
}

// v2.2.2：空闲预热——启动稳定后后台把引擎拉好，用户首次打开文件秒出
// （不做启动即拉：不抢首屏资源；exe 下 loader+editor.main 合计几 MB，
// 一次预热后浏览器缓存/内存常驻，后续会话零等待）
function monacoWarmup() {
  const idle = window.requestIdleCallback || (cb => setTimeout(cb, 4000));
  idle(() => { try { monacoInit().catch(() => {}); } catch (_) {} }, { timeout: 15000 });
}
