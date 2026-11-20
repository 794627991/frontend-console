'use strict';
// 前端控制台 Electron 壳 · P0 换壳 PoC
// 方案：docs/electron迁移方案_2026-11-20.md §2 P0
// 职责：单实例锁 → spawn Python 后端（--headless）→ 轮询 endpoint.json +
// /api/status 就绪 → BrowserWindow.loadURL → 双向生命周期（后端退→壳退，
// 壳退→树杀后端）。无边框/窗控三钮/托盘是 P2；网页 tab 是 P3。
//
// 已知边界（P0 接受）：
// - 后端 stdout 被 backend_log 截进内存环形缓冲，壳的 pipe 收不到——后端
//   日志看诊断面板（/api/backend_log），壳自身日志落 electron-shell.log
// - 页面自绘窗控三钮调 /api/window/*（headless 不注册）→ 404 无效，用默认
//   标题栏关闭/最小化/最大化
const { app, BrowserWindow, dialog, ipcMain, Tray, Menu, nativeImage, shell,
        clipboard, webContents } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const BOOT_TIMEOUT_MS = 60 * 1000; // 后端冷启动（exe 解压 + Flask + worker）余量
const POLL_MS = 250;

// CDP（调试能力常开，用户令 a624 同款）：与旧 WebView2 形态同端口 9222，
// MCP 的 devtools_* 工具链零改动继续可用（本机单用户工具，信任模型不变；
// 过渡期与旧形态同时跑会撞端口——后启动方 CDP 失效，属可接受过渡态）
app.commandLine.appendSwitch('remote-debugging-port', '9222');
// Chromium 日志只留 FATAL（log-level 3）：网页内容自身的网络噪音
// （如 B站 P2P tracker DNS 失败 errorcode -105）不该刷壳 stdout，
// 用户令壳启动后即安静，内容侧问题走统一日志，DevTools


const STATE_DIR = path.join(os.homedir(), '.serialconsole_pro');
const SHELL_LOG = path.join(STATE_DIR, 'electron-shell.log');
// 与后端 main.py ENDPOINT_FILE 同源（默认同路径；测试可两边同设 FC_ENDPOINT_FILE）
const ENDPOINT_FILE = process.env.FC_ENDPOINT_FILE ||
  path.join(STATE_DIR, 'endpoint.json');
// 窗口记忆落盘（userData 随 productName，与双实例互斥同一套语义）
const SHELL_STATE = () => path.join(app.getPath('userData'), 'shell-state.json');
// 后端 config（close_to_tray 等用户设置——与旧 pywebview 形态共用同一份，
// 用户在设置页改的值两边都认）
const CONFIG_FILE = path.join(STATE_DIR, 'config.json');
// P3 密码库（用户令：壳内保存/自动填充）：主进程 safeStorage 加密存储 +
// guest 极简 preload（隔离世界、不向页面暴露 API）。guest 由
// will-attach-webview 强制挂载，renderer 传入的 preload 一律被覆盖。
const pwStore = require('./passwords');
const GUEST_PRELOAD = path.join(__dirname, 'guest-preload.js');

// 统一日志（用户令：壳只做启动用，一切问题进后端日志面板 tag=shell）。
// 文件写保留=崩溄期（后端起不来）唯一线索；正常期主通道=批量转发后端
// stdout 只在 dev 跑有观察价值，保留但不再是唯一出口
const _logBuf = [];
function log(...args) {
  const line = '[' + new Date().toISOString() + '] ' + args.join(' ');
  process.stdout.write(line + '\n');
  try { fs.appendFileSync(SHELL_LOG, line + '\n'); } catch (_) {}
  _logBuf.push(line);
  if (_logBuf.length >= 5) _logFlush();
}
function _logFlush() {
  if (!_logBuf.length || !endpointUrl) return;
  const lines = _logBuf.splice(0, 20);
  try {
    fetch(endpointUrl + '/api/shell_log', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines }),
      signal: AbortSignal.timeout(2000),
    }).catch(() => {});   // 后端忙，己死：丢不志不重试（文件已有底）
  } catch (_) {}
}
setInterval(_logFlush, 3000);

// ---- 后端命令解析：FC_BACKEND_CMD（JSON 数组）> 打包探测 > 开发默认 ----
function resolveRealPython() {
  // PATH 首位可能是 WindowsApps 商店 shim：spawn 它会隔出一层转发进程
  //（壳看到的 child 是 shim，真后端是孙进程——pid 校验/树杀全错位，
  // 实测实锤）。挑 where 列表里第一个非 shim 的真身
  if (process.env.FC_PYTHON) return process.env.FC_PYTHON;
  try {
    const out = require('child_process').execSync('where python',
                                                  { encoding: 'utf-8', timeout: 3000 });
    const real = out.split(/\r?\n/).map((s) => s.trim())
      .find((p) => p.toLowerCase().endsWith('.exe') &&
            !p.toLowerCase().includes('\\windowsapps\\'));
    if (real) return real;
  } catch (_) { /* where 不可用 → 回退 */ }
  return 'python';
}

function resolveBackend() {
  if (process.env.FC_BACKEND_CMD) {
    try {
      const arr = JSON.parse(process.env.FC_BACKEND_CMD);
      if (Array.isArray(arr) && arr.length) return arr;
    } catch (_) { log('FC_BACKEND_CMD 解析失败，回落默认探测'); }
  }
  if (app.isPackaged) {
    // P1 定安装布局；P0 约定 resources/backend/ 下的后端 exe
    const dir = path.join(process.resourcesPath, 'backend');
    try {
      const exe = fs.readdirSync(dir).find(
        (f) => f.toLowerCase().endsWith('.exe'));
      if (exe) return [path.join(dir, exe), '--headless'];
    } catch (_) { /* 目录不存在 → 报错框 */ }
    return null;
  }
  // 开发形态：工程根（electron/..）跑源码后端
  return [resolveRealPython(), 'src/main.py', '--headless'];
}

// ---- 就绪探测 ----
function readEndpoint() {
  try {
    const ep = JSON.parse(fs.readFileSync(ENDPOINT_FILE, 'utf-8'));
    if (ep && ep.port && ep.url) return ep;
  } catch (_) { /* 文件未出现/写一半/陈旧残留 */ }
  return null;
}

function probeStatus(url) {
  return new Promise((resolve) => {
    const req = http.get(url + '/api/status', { timeout: 2000 }, (res) => {
      res.resume(); // 只看状态码
      resolve(res.statusCode === 200);
    });
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.on('error', () => resolve(false));
  });
}

function killTree(pids) {
  // 去重后逐个杀。后端自身 Job Object 是内核级兜底（强杀也覆盖其全部
  // 子进程），taskkill /T /F 是即时清。壳杀自己看到的 child；后端自杀
  //（FC_SHELL_PID 探活）覆盖自身子树
  for (const pid of [...new Set([].concat(pids).filter(Boolean))]) {
    try {
      spawn('taskkill', ['/PID', String(pid), '/T', '/F'],
            { windowsHide: true, stdio: 'ignore' });
      log('树杀 pid=' + pid);
    } catch (e) { log('树杀失败 pid=' + pid, e.message); }
  }
}

let backend = null;      // child_process 句柄
let endpointPid = null;  // 后端自报 pid（endpoint.json；隔 launcher shim 时 ≠ backend.pid）
let win = null;          // BrowserWindow
let booted = false;      // 后端就绪、窗口已开
let exiting = false;     // 收尾中（防重复弹框/重复杀）

function fatal(title, msg) {
  if (exiting) return;
  exiting = true;
  log('FATAL', title, '-', msg);
  // 异步版弹框：showErrorBox 是原生模态、阻塞主进程直到用户点掉
  //（实测：超时弹框挂着没人点，后续退出全被卡住）
  dialog.showMessageBox({
    type: 'error', title, message: title, detail: msg, buttons: ['确定'],
  }).finally(() => app.exit(1));
}

async function boot() {
  const cmd = resolveBackend();
  if (!cmd) {
    fatal('后端未找到',
      '未找到后端程序。\n\n打包布局约定：resources/backend/ 下应有后端 exe。');
    return;
  }
  // P1 跨形态单实例（用户定调「只能有一个」）：两套锁（Win32 mutex vs
  // requestSingleInstanceLock）互不相识——旧 GUI 在托盘活着时启动壳会双
  // 后端+互删 endpoint+抢 9222。启动先探活 endpoint 上的旧实例，活着即拒启
  const _old = readEndpoint();
  if (_old && _old.url && await probeStatus(_old.url)) {
    fatal('已有实例在运行',
      '检测到另一实例（' + _old.url + '，pid=' + (_old.pid || '?') + '）尚在运行。\n' +
      '过渡期新旧形态只能跑一个：请先退出旧实例（托盘右键退出）再启动。\n' +
      '排查：' + SHELL_LOG);
    return;
  }
  // 陈旧 endpoint.json 先清（上一实例残留会被轮询先读到=连到旧端口）。
  // 就绪判据：endpoint.boot_token == 本次 spawn 注入的 FC_BOOT_TOKEN，且
  // /api/status 200。不校验 pid 相等——PATH 前置 WindowsApps 商店 shim 时
  // 壳的 child 是转发层、真后端是孙进程，pid 必然错位（实测实锤）；token
  // 由后端从 env 原样回写，跨 shim 也不会认错实例（boot_ms 时间窗在时钟
  // 回拨/快慢机上不可靠，已由 token 取代）
  try { fs.unlinkSync(ENDPOINT_FILE); } catch (_) { /* 本就不存在 */ }

  const BOOT_TOKEN = crypto.randomUUID ? crypto.randomUUID()
    : String(Date.now()) + Math.random().toString(36).slice(2);
  const spawnMs = Date.now();
  log('spawn 后端：', JSON.stringify(cmd));
  const [exe, ...args] = cmd;
  backend = spawn(exe, args, {
    cwd: app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..'),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: Object.assign({}, process.env, {
      // 后端 parent-watch 盯壳用（隔 launcher shim 也看得见壳）
      FC_SHELL_PID: String(process.pid),
      // P3 网页 tab：壳形态标记 + Electron 分区目录（web_tabs.py 认
      // FC_WEBTAB_SHELL 即返回兼容 stub——视图归前端 DOM，后端只留密码库）
      FC_WEBTAB_SHELL: '1',
      // 启动亲和令牌：后端写进 endpoint.json——壳就绪判据认 token 不认
      // 时间窗（boot_ms-1500 在系统时钟回拨/快慢机上有认错后端的可能）
      FC_BOOT_TOKEN: BOOT_TOKEN,
      FC_WEBTAB_PROFILE: path.join(app.getPath('userData'),
                                   'Partitions', 'webtabs'),
    }),
  });
  pipeTag(backend.stdout, 'out');
  pipeTag(backend.stderr, 'err');
  backend.on('exit', (code, signal) => {
    log('后端退出 code=%s signal=%s（booted=%s）', code, signal, booted);
    // 优雅退出链中后端先退是预期（quitApp→/api/quit→清理→自灭），静默
    if (exiting || reallyQuitting) return;
    if (!booted) {
      fatal('后端启动失败',
        '后端进程提前退出（code=' + code + ' ' + (signal || '') + '）。\n\n' +
        '后端命令：' + cmd.join(' ') + '\n' +
        '排查：' + SHELL_LOG + ' 与\n' +
        path.join(STATE_DIR, 'server_errors.log'));
    } else {
      // 运行中后端死亡：壳没有可服务的内容，告知并退出
      fatal('后端已退出',
        '后端进程意外退出（code=' + code + '），工具即将关闭。\n' +
        '排查：' + SHELL_LOG);
    }
  });

  // 轮询就绪
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  let epTokenWarned = false;
  while (Date.now() < deadline) {
    if (backend.exitCode !== null) return; // exit 回调已接管报错
    const ep = readEndpoint();
    if (ep && !epTokenWarned && ep.boot_token !== BOOT_TOKEN) {
      epTokenWarned = true;
      // 单侧补丁的典型症状：壳在等 token，后端没回写/版本过旧——先留痕，
      // 免得只看到 60s 后的「启动超时」而无从下手
      log('endpoint boot_token 不匹配（后端未回写 FC_BOOT_TOKEN？）port='
          + ep.port);
    }
    if (ep && ep.boot_token === BOOT_TOKEN && await probeStatus(ep.url)) {
      endpointPid = ep.pid || null;
      openWindow(ep.url);
      return;
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  if (backend.exitCode !== null) return;
  fatal('后端启动超时',
    BOOT_TIMEOUT_MS / 1000 + ' 秒内后端未就绪。\n\n' +
    '后端命令：' + cmd.join(' ') + '\n' +
    'endpoint：' + ENDPOINT_FILE + '\n' +
    '排查：' + SHELL_LOG + '；若界面能打开，诊断面板可导出后端日志。');
  killTree([backend.pid, endpointPid]);
}

function pipeTag(stream, tag) {
  if (!stream) return;
  // 后端 stdout 通常已被 backend_log 截走，这里只收异常早退期的零星输出
  stream.setEncoding('utf-8');
  stream.on('data', (d) => {
    for (const ln of String(d).split(/\r?\n/)) {
      if (ln.trim()) log('[backend:' + tag + ']', ln.slice(0, 500));
    }
  });
}

// ---- P2 窗体收尾：窗口记忆 / IPC 窗控 / 托盘 / 优雅退出 ----

function readConfigBool(key, dft) {
  // 尊重 dft：key 缺失用默认（原先 !== false 写法忽略 dft 参数）
  try {
    const v = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'))[key];
    return v === undefined ? dft : v !== false;
  } catch (_) { return dft; }
}

function loadShellState() {
  try {
    const st = JSON.parse(fs.readFileSync(SHELL_STATE(), 'utf-8'));
    if (st && st.bounds && Number.isFinite(st.bounds.x)) return st;
  } catch (_) { /* 首启/坏文件 → 默认 */ }
  return null;
}

// 记忆窗格语义（用户定调，pywebview 形态同款平移）：最大化→关→回最大化；
// 窗口化→关→回窗口化。max 独记 flag，bounds 只存 Normal 态（getNormalBounds）
function saveShellState() {
  if (!win) return;
  try {
    fs.writeFileSync(SHELL_STATE(), JSON.stringify({
      max: win.isMaximized(),
      bounds: win.getNormalBounds(),
    }));
  } catch (_) { /* userData 不可写 → 放弃记忆 */ }
}

let endpointUrl = null;  // 优雅退出要 POST /api/quit
let reallyQuitting = false;
let tray = null;
let balloonShown = false; // 每进程一次「已驻留托盘」气泡（不碰后端 config）

function backendQuitGraceful() {
  // 通知后端跑清理链（串口/SSH 落盘收口 + worker 优雅停，秒回后台执行）；
  // 等 4s（manage_stop 预算 3.5s + 余量）后由本进程退出链兜底树杀
  if (!endpointUrl) return Promise.resolve();
  return new Promise((resolve) => {
    const req = http.request(endpointUrl + '/api/quit',
      { method: 'POST', timeout: 4000 }, (res) => { res.resume(); resolve(); });
    req.on('timeout', () => { req.destroy(); resolve(); });
    req.on('error', () => resolve());
    req.end();
  });
}

function quitApp() {
  if (reallyQuitting) return;
  reallyQuitting = true;
  // 先等后端优雅收尾（有界 4s），再关窗退出——will-quit 的树杀是兜底
  backendQuitGraceful().finally(() => {
    if (win) { try { win.destroy(); } catch (_) {} }
    app.quit();
  });
}

function showWindowFromTray() {
  if (!win) return;
  // 记忆窗格：最小化态先 restore（回 pre-minimize 形态，含最大化），
  // 其余直接 show——与 pywebview 形态 _tray_show 同语义
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

// ---- 托盘菜单（原 pywebview 自绘菜单内容全量平移，Electron 原生呈现）----
// 原实现 src/tray.py _make_menu_provider：Proxy 段（状态/启停/模式/压缩
// 子菜单）+ Lanzi 段（额度行/立即刷新，未登录整段隐藏）+ 打开设置/关于/
// 退出。数据面在 worker（headless 恒 offload），经主后端 307 中继，fetch
// 自动跟随。状态 2s 缓存同原实现；右键用缓存瞬时弹出，后台刷新下次生效
const trayCache = { proxy: null, proxyTs: 0, lanzi: null, lanziTs: 0, ver: null };

function fetchJson(url, timeoutMs) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  return fetch(url, { signal: ctl.signal })
    .then((r) => r.json())
    .finally(() => clearTimeout(t));
}

function fetchTextPost(url, body, timeoutMs) {
  // 托盘操作 fire-and-forget（原实现同款语义：面板是完整入口，菜单只是
  // 快捷方式，失败静默）；完成后刷新缓存让下次右键见新态
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  return fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}), signal: ctl.signal,
  }).finally(() => { clearTimeout(t); trayFetch(true); });
}

async function trayFetch(refresh) {
  if (!endpointUrl) return;
  const now = Date.now();
  const jobs = [];
  if (refresh || !trayCache.proxy || now - trayCache.proxyTs > 2000) {
    jobs.push(fetchJson(endpointUrl + '/api/proxy/status', 1500)
      .then((d) => { trayCache.proxy = d || {}; trayCache.proxyTs = now; })
      .catch(() => { trayCache.proxy = trayCache.proxy || {}; }));
  }
  if (refresh || !trayCache.lanzi || now - trayCache.lanziTs > 2000) {
    jobs.push(fetchJson(endpointUrl + '/api/lanzi/status', 1500)
      .then((d) => { trayCache.lanzi = d || {}; trayCache.lanziTs = now; })
      .catch(() => { trayCache.lanzi = trayCache.lanzi || {}; }));
  }
  if (!trayCache.ver) {
    jobs.push(fetchJson(endpointUrl + '/api/harness/version', 1500)
      .then((d) => { if (d && d.ok) trayCache.ver = d; })
      .catch(() => {}));
  }
  await Promise.all(jobs).catch(() => {});
  updateTrayTip();
}

function fnum(n) {
  // 与 src/lanzi/api.py fnum 同口径（W/k 缩写），勿改格式
  n = Number(n) || 0;
  if (n >= 1e8) return String(Math.round(n));
  if (n >= 1e4) return (n / 1e4).toFixed(1) + 'W';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return Number.isInteger(n) ? String(n) : String(n);
}

function lanziQuotaRow(L) {
  const ov = L.quota_overview, u = L.quota_user;
  if (!ov) return '额度: ' + (u ? ('已登录 ' + u) : '未登录/暂无数据');
  return '今日 外 ' + fnum(ov.externalDailyUsed || 0) + '/' +
         fnum(ov.externalDailyLimit || 0) + '  内 ' +
         fnum(ov.internalDailyUsed || 0) + '/' + fnum(ov.internalDailyLimit || 0);
}

function updateTrayTip() {
  if (!tray) return;
  try {
    const L = trayCache.lanzi || {};
    tray.setToolTip(L.quota_overview
      ? ('前端控制台 · ' + lanziQuotaRow(L)) : '前端控制台');
  } catch (_) { /* tooltip 失败无害 */ }
}

function openSettingsFromTray() {
  showWindowFromTray();
  if (win) {
    try {
      win.webContents.executeJavaScript(
        'window.openSettingsPanel && window.openSettingsPanel()');
    } catch (_) { /* 页面未就绪时静默 */ }
  }
}

function buildTrayTemplate() {
  const t = [{ label: '显示主窗口', click: showWindowFromTray }];
  if (endpointUrl) {
    const P = trayCache.proxy || {};
    t.push({ type: 'separator' },
      { label: P.running ? ('Claude Proxy [' + P.status + ']')
                         : 'Claude Proxy（未启动）', enabled: false },
      { label: P.running ? '■ 停止 Claude 代理' : '▶ 启动 Claude 代理',
        click: () => fetchTextPost(endpointUrl +
          (P.running ? '/api/proxy/stop' : '/api/proxy/start'), {}, 3000) },
      { label: '切换为代理模式',
        click: () => fetchTextPost(endpointUrl + '/api/proxy/mode',
                                   { mode: 'proxy' }, 3000) },
      { label: '切换为直连模式',
        click: () => fetchTextPost(endpointUrl + '/api/proxy/mode',
                                   { mode: 'direct' }, 3000) },
      { label: '压缩模式', submenu: [
        { label: '开启压缩', type: 'radio', checked: P.bili_mode === 'on',
          enabled: !!P.bili_ready,
          click: () => fetchTextPost(endpointUrl + '/api/proxy/compression',
                                     { mode: 'on' }, 3000) },
        { label: '关闭压缩', type: 'radio', checked: P.bili_mode !== 'on',
          click: () => fetchTextPost(endpointUrl + '/api/proxy/compression',
                                     { mode: 'off' }, 3000) },
      ] });
    // Lanzi 段：未登录/无数据整段隐藏（用户定调，不打扰非内网用户）
    const L = trayCache.lanzi || {};
    if (L.quota_overview || L.quota_user) {
      t.push({ type: 'separator' },
        { label: 'Lanzi', enabled: false },
        { label: lanziQuotaRow(L), enabled: false },
        { label: '额度立即刷新',
          click: () => fetchTextPost(endpointUrl + '/api/lanzi/refresh', {}, 3000) });
    }
  }
  const v = trayCache.ver;
  const hv = v && v.harness ? (String(v.harness).match(/a\d+/) || [v.harness])[0] : '?';
  t.push({ type: 'separator' },
    { label: '打开设置', click: openSettingsFromTray },
    { label: '关于  v' + (v ? v.app : '?') + ' · harness ' + hv, enabled: false },
    { type: 'separator' },
    { label: '退出', click: quitApp });
  return t;
}

function setupTray() {
  // 图标：打包形态随 backend 带（spec datas ('ico','ico')）；dev 用源码 ico
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', '_internal', 'ico', 'app.ico')
    : path.join(__dirname, '..', 'ico', 'app.ico');
  try {
    tray = new Tray(nativeImage.createFromPath(iconPath));
    tray.setToolTip('前端控制台');
    // 左键 = 显示/隐藏（点开记忆窗格大小）；右键 = 菜单（不用 setContextMenu
    // ——每次右键现建模板，动态段（Proxy 状态/额度）天然新鲜）
    tray.on('click', () => {
      if (win && win.isVisible() && !win.isMinimized()) win.hide();
      else showWindowFromTray();
    });
    tray.on('right-click', () => {
      try { tray.popUpContextMenu(Menu.buildFromTemplate(buildTrayTemplate())); }
      catch (e) { log('托盘菜单弹出失败：', e.message); }
      trayFetch();   // 后台刷新缓存+tooltip，下次右键见新态
    });
    // 周期刷新（tooltip 额度行新鲜度；原实现有 5s tooltip daemon，壳侧 30s
    // 足够——菜单打开时还有 2s 缓存兜着）
    setInterval(() => { trayFetch().catch(() => {}); }, 30 * 1000);
  } catch (e) {
    log('托盘创建失败（close_to_tray 将不可用，✕ 直接退出）：', e.message);
    tray = null;
  }
}

function pushWinState() {
  if (win && !win.isDestroyed()) {
    win.webContents.send('fc:win-state', { max: win.isMaximized() });
  }
}

function openWindow(url) {
  booted = true;
  endpointUrl = url;
  const saved = loadShellState();
  const opts = {
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    title: '前端控制台',
    frame: false,   // P2 无边框（页面 topbar 自绘 + drag 区接管）
    show: false,    // 首绘后再显（白屏闪避）
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      // P3 网页 tab：<webview> 标签（DOM 元素——UI 悬浮可直接盖住，静止帧
      // 方案退役的根基）；guest 自身 sandbox、无 preload
      webviewTag: true,
    },
  };
  if (saved && saved.bounds) {
    // 只取宽高+位置的可信值（屏幕变更后旧坐标可能出屏——Electron 会钳制）
    opts.x = saved.bounds.x; opts.y = saved.bounds.y;
    opts.width = Math.max(900, saved.bounds.width | 0);
    opts.height = Math.max(600, saved.bounds.height | 0);
  }
  win = new BrowserWindow(opts);
  win.webContents.on('will-attach-webview', (_e, webPreferences) => {
    webPreferences.preload = GUEST_PRELOAD;
    webPreferences.nodeIntegration = false;
    webPreferences.nodeIntegrationInSubFrames = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
    webPreferences.webSecurity = true;
    webPreferences.allowRunningInsecureContent = false;
  });
  if (saved && saved.max) win.maximize();
  win.once('ready-to-show', () => { if (win) win.show(); });
  win.webContents.on('did-fail-load', (_e, code, desc, url2, isMainFrame) => {
    // 实测子帧失败也触发（isMainFrame=false）——只对主帧 fatal，
    // 否则主 UI 里任何一个 iframe 加载失败都会把整个工具杀掉
    if (!isMainFrame || exiting) return;
    exiting = true;
    fatal('页面加载失败',
      'loadURL 失败：' + code + ' ' + desc + '\n' + url2 + '\n\n' +
      '后端 endpoint：' + ENDPOINT_FILE);
  });
  // 外链一律系统浏览器（P3 网页 tab 落地前的定调降级，方案风险表兜底）。
  // 不放行 Electron 子窗：自动 window.open 的子窗会**继承本 preload**——
  // 外站拿到 pywebview shim（文件对话框能力）= 安全红线
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  // 主窗只准自家后端 origin——防误点把工具窗整页导航到外站
  win.webContents.on('will-navigate', (e, url) => {
    try {
      if (new URL(url).origin !== new URL(endpointUrl).origin) {
        e.preventDefault();
        if (/^https?:/i.test(url)) shell.openExternal(url);
      }
    } catch (_) { e.preventDefault(); }
  });
  // 窗态推送：maximize/unmaximize 事件 + 页面就绪初推（DOMContentLoaded
  // 时 preload 已挂，onState 订阅先于本帧到达也安全——send 是排队消息）
  win.on('maximize', pushWinState);
  win.on('unmaximize', pushWinState);
  win.webContents.on('did-finish-load', pushWinState);
  // 窗口记忆：move/resize 防抖落盘（最小化/最大化瞬间的垃圾 bounds 由
  // getNormalBounds 天然免疫——它恒返回 Normal 态矩形）
  let saveTimer = null;
  const saveDebounced = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveShellState, 500);
  };
  win.on('resize', saveDebounced);
  win.on('move', saveDebounced);
  // 关闭语义：close_to_tray（后端 config，与旧形态共用）开着 → 驻托盘；
  // 否则真退出（先让后端优雅收尾）。托盘「退出」/ 后端死亡走 quitApp
  win.on('close', (e) => {
    if (reallyQuitting) return;           // 放行销毁
    saveShellState();
    if (tray && readConfigBool('close_to_tray', true)) {
      e.preventDefault();
      win.hide();
      if (!balloonShown) {
        balloonShown = true;
        try {
          tray.displayBalloon({
            iconType: 'info', title: '前端控制台',
            content: '已最小化到托盘，点击托盘图标恢复',
          });
        } catch (_) { /* 气泡失败不影响驻留 */ }
      }
    } else {
      e.preventDefault();
      quitApp();
    }
  });
  win.on('closed', () => { win = null; });
  win.loadURL(url);
  setupTray();
  log('窗口已开 loadURL=' + url);
}

// ---- guest 开窗路由（P0 审计修）：<webview> 元素上没有 setWindowOpenHandler
//（45.4.1 实测 undefined）、new-window 事件不触发、主窗 handler 管不到
// guest——guest 的 window.open 会直接开裸 Electron 窗。主进程按
// webContents 类型收口：webview guest 一律 deny + 通知主窗页面开新网页 tab
//（经 preload 的 onWebTabOpen 订阅 → __newWindow）。allowpopups 必须存在
//（空值即可）：它是 window.open 请求能到达本 handler 的开关——删掉它
// =请求整条断路；布尔属性写什么值都是 true，真闸门是下面的 deny
app.on('web-contents-created', (_e, contents) => {
  if (contents.getType() !== 'webview') return;
  contents.setWindowOpenHandler(({ url }) => {
    // 只放行 http(s) 推送开 tab；about:blank/其他 scheme 纯 deny
    //（防空白 tab 与无效推送——二轮复审建议）
    if (/^https?:/i.test(url) && win && !win.isDestroyed()) {
      win.webContents.send('fc:webtab-open', url);
    }
    return { action: 'deny' };
  });
});

// ---- IPC：页面窗控（preload contextBridge 受控面）----
ipcMain.on('fc:win-ctl', (_e, act) => {
  if (!win || win.isDestroyed()) return;
  if (act === 'min') win.minimize();
  else if (act === 'max') {
    if (win.isMaximized()) win.unmaximize(); else win.maximize();
    pushWinState();
  } else if (act === 'close') win.close(); // 走 close 事件语义（托盘/退出分流）
});
ipcMain.handle('fc:win-state-get', () =>
  ({ max: !!(win && !win.isDestroyed() && win.isMaximized()) }));
// 后端日志窗「打开开发者工具」按钮（原 F12 承接，a624）：壳形态 headless
// 无 /api/window/devtools 路由，走 IPC。detach=独立 DevTools 窗（frameless
// 主窗内 dock 会挤布局）
ipcMain.on('fc:devtools', () => {
  if (!win || win.isDestroyed()) return;
  try { win.webContents.openDevTools({ mode: 'detach' }); }
  catch (e) { log('DevTools 打开失败：', e.message); }
});
// 原生文件/目录选择（preload 的 pywebview 兼容层消费，对齐 FileBridge 签名）
ipcMain.handle('fc:pick', async (_e, opts) => {
  if (!win || win.isDestroyed()) return [];
  const props = ['openFile'];
  if (opts && opts.multi) props.push('multiSelections');
  const r = await dialog.showOpenDialog(win, {
    properties: props,
    filters: (opts && opts.filters) || undefined,
  });
  return r.canceled ? [] : r.filePaths;
});
ipcMain.handle('fc:pick-dir', async () => {
  if (!win || win.isDestroyed()) return '';
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
  return r.canceled ? '' : (r.filePaths[0] || '');
});
// 剪贴板（pywebview 兼容层等价实现，FileBridge 全量 7 方法就此齐平）
ipcMain.handle('fc:clipboard-read', () => clipboard.readText());
ipcMain.handle('fc:clipboard-write-image', (_e, p) => {
  try {
    clipboard.writeImage(nativeImage.createFromPath(String(p || '')));
    return true;
  } catch (_) { return false; }
});

// P3 密码库 IPC（guest ↔ 主进程 ↔ 主 UI）：独立模块，harness 复用同一份
require('./pw-ipc').register({ ipcMain, getWin: () => win, store: pwStore });

// ---- 站点级密码菜单（🔑）：当前 origin 的列表/显示/删除/填充 ----
function _isMainUi(event) {
  return !!win && !win.isDestroyed() && event.sender === win.webContents;
}
ipcMain.handle('fc-pw:site-list', (event, origin) => {
  if (!_isMainUi(event)) return { ok: false, err: 'forbidden' };
  try {
    const o = pwStore.originOf(origin);
    return o ? { ok: true, origin: o, items: pwStore.listForOrigin(o) }
             : { ok: false, err: '非法 origin' };
  } catch (e) { return { ok: false, err: String((e && e.message) || e) }; }
});
ipcMain.handle('fc-pw:site-reveal', (event, body) => {
  if (!_isMainUi(event)) return { ok: false, err: 'forbidden' };
  try {
    const o = pwStore.originOf(body && body.origin);
    if (!o) return { ok: false, err: '非法 origin' };
    return pwStore.reveal(o, String((body && body.user) || ''));
  } catch (e) { return { ok: false, err: String((e && e.message) || e) }; }
});
ipcMain.handle('fc-pw:site-delete', (event, body) => {
  if (!_isMainUi(event)) return { ok: false, err: 'forbidden' };
  try {
    const o = pwStore.originOf(body && body.origin);
    if (!o) return { ok: false, err: '非法 origin' };
    return pwStore.remove(o, String((body && body.user) || ''));
  } catch (e) { return { ok: false, err: String((e && e.message) || e) }; }
});
ipcMain.handle('fc-pw:site-fill', (event, body) => {
  if (!_isMainUi(event)) return { ok: false, err: 'forbidden' };
  try {
    const wc = webContents.fromId(Number(body && body.wcId));
    if (!wc || wc.isDestroyed() || wc.getType() !== 'webview') {
      return { ok: false, err: '页面不可用' };
    }
    const o = pwStore.originOf(wc.getURL());
    if (!o || o !== pwStore.originOf(body && body.origin)) {
      return { ok: false, err: 'origin 不匹配' };
    }
    const r = pwStore.reveal(o, String((body && body.user) || ''));
    if (!r || !r.ok || !r.pw) return { ok: false, err: (r && r.err) || '读取失败' };
    wc.send('fc-pw:fill-now', { user: String((body && body.user) || ''), password: r.pw });
    return { ok: true };
  } catch (e) { return { ok: false, err: String((e && e.message) || e) }; }
});

// ---- 生命周期 ----
// userData 统一到 productName 目录：dev 形态 Electron 用 package.json 的
// name 字段（frontend-console-shell）、装机版用 productName（前端控制台）
// ——不统一则两者 userData 不同目录，单实例锁互不感知 = dev 壳与装机版
// 可同时双开、两个后端互踩 endpoint.json（实测实锤）。统一后锁跨形态
// 互斥，兑现用户定调「只能有一个」
if (app.getName() !== '前端控制台') {
  try {
    app.setPath('userData',
      path.join(app.getPath('appData'), '前端控制台'));
  } catch (_) { /* setPath 失败回落默认（锁退化为同形态互斥） */ }
}
// 单实例语义（用户定调 2026-11-20）：只允许一个壳实例（不开隔离口）
if (!app.requestSingleInstanceLock()) {
  // 第二实例：锁已被占，直接退（旧实例经 second-instance 自弹）
  app.quit();
} else {
  app.on('second-instance', () => showWindowFromTray());
  app.whenReady().then(boot);
  // P2：托盘常驻，关窗不退（真退 = 托盘「退出」或 close_to_tray=false 的 ✕）
  app.on('window-all-closed', () => {});
  app.on('before-quit', (e) => {
    // 只允许 quitApp 发起的退出走优雅链；其余（如系统关机）直接放行树杀
    if (!reallyQuitting && booted && backend) {
      e.preventDefault();
      quitApp();
    }
  });
  app.on('will-quit', () => {
    if (tray) { try { tray.destroy(); } catch (_) {} }
    killTree([backend && backend.pid, endpointPid]);
  });
  process.on('exit', () => { killTree([backend && backend.pid, endpointPid]); });
}
