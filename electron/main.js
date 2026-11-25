'use strict';
// 前端控制台 Electron 壳（P0~P4 已完成，P4 起唯一形态）
// 方案：docs/electron迁移方案_2026-11-20.md
// 职责：单实例锁 → spawn Python 后端（--headless）→ 轮询 endpoint.json +
// /api/status 就绪 → BrowserWindow.loadURL → 双向生命周期（后端退→壳退，
// 壳退→树杀后端）。P2 无边框/窗控/托盘、P3 网页 tab + 密码、P4 截图覆盖窗。
//
// 已知边界：
// - 后端 stdout 被 backend_log 截进内存环形缓冲，壳的 pipe 收不到——后端
//   日志看诊断面板（/api/backend_log），壳自身日志落 electron-shell.log
// - 窗口控制/截图/对话框全部走本进程 IPC；后端不再注册 /api/window/*
const { app, BrowserWindow, dialog, ipcMain, Tray, Menu, nativeImage, shell,
        clipboard, webContents, screen, session: eSession } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const util = require('util');

// 后端冷启动超时：packaged=60s（exe 解压+Flask+worker 余量）；源码形态
// 放宽到 180s。2026-11-23 总审计 a683-A8：原注释理由是「首启先跑 pip 补装
// （内网镜像慢）」——deps_bootstrap 早已改为只打印 pip 指引并让后端退出、
// 不自动装，该理由失效。数值保留：源码形态是纯 .py 导入（无 pyd）+ 首次
// .pyc 编译 + 杀软扫描源码树，比打包形态慢得多；超时的代价是误杀一个
// 其实能起来的后端，多等的代价只是慢机器上弹框晚一点——宁慢勿误杀。
const BOOT_TIMEOUT_MS = 60 * 1000;   // 默认（packaged）
const BOOT_TIMEOUT_DEV_MS = 180 * 1000;
const POLL_MS = 250;

// CDP（调试能力常开，用户令 a624 同款）：沿用历史端口 9222，MCP 的
// devtools_* 工具链零改动继续可用（本机单用户工具，信任模型不变）
app.commandLine.appendSwitch('remote-debugging-port', '9222');
// 后台可用（2026-11-25 用户令：AI 浏览器必须能后台/最小化/失焦下继续操作）。
// Chromium 默认会「节流/冻结」不可见渲染进程：被遮挡就暂停 rAF 与出帧，
// 最小化更彻底——AI 的点击/输入被丢弃、截图挂死。两个开关：
//   disable-backgrounding-occluded-windows  被其他窗口完全遮挡时不降优先级
//   disable-renderer-backgrounding           渲染进程转后台时不被降级
// **故意不开 disable-background-timer-throttling**（受控实验，见 AGENTS.md）：
// 它是全局的，会把工具自己主界面的 2s/5s/10s/30s 轮询在窗口最小化时也全速
// 跑起来（白烧 CPU）。而 AI 浏览器视图在 will-attach-webview 里单独设了
// backgroundThrottling=false——只这一条就够：实测「只关 guest 节流」时最小化
// 后定时器 30 次/3s（正常），页面还保持 visibilityState=visible，比全局开关
// 效果更好。两者都不关的对照组是 3 次/3s（被节流），证明这条测量有效。
// 注意：这两个开关解决「被遮挡 / 失焦 / 后台标签页」，**最小化仍会被 Chromium
// 判为隐藏**（那是 Windows 层语义，guest 的 backgroundThrottling=false 能把它
// 拉回 visible，但不保证所有环境）。最小化的兜底见 ai_browser.py 的
// _check_visible——那里对 hidden 页面改走 Emulation + Input 派发。
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
app.commandLine.appendSwitch('disable-renderer-backgrounding');
// Chromium 在 Windows 上有一套「原生窗口遮挡计算」（CalculateNativeWinOcclusion）：
// 窗口被别的窗口盖住就判定为 occluded → webContents 转 hidden → 停帧停输入。
// 这正是「用户看着别的软件、AI 在后台点不动」的直接原因（ZCode 无头模式天然
// 没有这个问题）。关掉它，《被遮挡》就不再等于《隐藏》。最小化时 guest 靠
// will-attach-webview 里的 backgroundThrottling=false 保持 visible（实测），
// ai_browser.py 的 Emulation 唤醒链只是读不到状态/页面被冻结时的兜底。
// 注意：Electron 启动早期只能 appendSwitch 一次同名开关，否则后者覆盖前者——
// 将来若别处也要 disable-features，必须合并成一个逗号分隔的列表。
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion');
// Chromium 日志只留 FATAL（log-level 3）：网页内容自身的网络噪音
// （如 B站 P2P tracker DNS 失败 errorcode -105）不该刷壳 stdout，
// 用户令壳启动后即安静，内容侧问题走统一日志，DevTools


// 2026-11-23 退役改造：~/.serialconsole_pro 退役——锚点=固定公式（与后端
// app_state._anchor_dir 同步）：appData 下 frontend-console-shell\backend。
// 对抗审计修正：不用 app.getPath('userData')——文件尾部有 userData 统一
// setPath（前端控制台），依赖求值顺序才能对齐太脆；显式公式两形态恒同址。
// 复审 N7①：FC_STATE_DIR 覆盖口——测试/隔离给壳与后端同设同一值，消除
// 「known-folder 不认 APPDATA 环境变量覆盖」的分叉面（生产环境不设即走公式）。
const STATE_DIR = process.env.FC_STATE_DIR ||
  path.join(app.getPath('appData'), 'frontend-console-shell', 'backend');
const SHELL_LOG = path.join(STATE_DIR, 'electron-shell.log');
// 与后端 main.py ENDPOINT_FILE 同源（默认同路径；测试可两边同设 FC_ENDPOINT_FILE）
const ENDPOINT_FILE = process.env.FC_ENDPOINT_FILE ||
  path.join(STATE_DIR, 'endpoint.json');
// 窗口记忆落盘（userData 随 productName，与双实例互斥同一套语义）
const SHELL_STATE = () => path.join(app.getPath('userData'), 'shell-state.json');
// 后端 config 的位置（close_to_tray 等用户设置——用户在设置页改的值两边都认）。
// 2026-11-23（用户令，最终版）：config.json **永远在 工具目录\data**，不跟着
// 数据目录迁移走——它是「数据迁到了哪」的唯一记录者。
// 工具目录（与后端 app_state._app_dir 同口径）：
//   打包形态  resources\backend（后端 exe 所在处）
//   开发形态  项目根（本文件的上一级）
// 没有指针文件、不看任何别的位置。测试可用 FC_TOOL_DATA_DIR 覆盖。
const TOOL_DATA_DIR = process.env.FC_TOOL_DATA_DIR || (app.isPackaged
  ? path.join(process.resourcesPath, 'backend', 'data')
  : path.join(__dirname, '..', 'data'));
const CONFIG_FILE = path.join(TOOL_DATA_DIR, 'config.json');
// P3 密码库（用户令：壳内保存/自动填充）：主进程 safeStorage 加密存储 +
// guest 极简 preload（隔离世界、不向页面暴露 API）。guest 由
// will-attach-webview 强制挂载，renderer 传入的 preload 一律被覆盖。
const pwStore = require('./passwords');
const GUEST_PRELOAD = path.join(__dirname, 'guest-preload.js');

// 统一日志（用户令 2026-11-23：调试日志非必要不写盘，全走工具自带内存
// 日志系统）。去向三条：
//   1) stdout（dev 控制台观察用；GUI 启动无人看，零成本）
//   2) 内存环形缓冲 → 批量转发后端 /api/shell_log → 诊断面板 tag=shell
//      （正常期的唯一持久通道——面板即日志，不落盘）
//   3) **仅致命路径**（fatal/未捕获异常，此刻后端多半已死、面板不存在）
//      才把缓冲尾一次性 append 进 electron-shell.log——唯一「必要」写盘
const _LOG_CAP = 400;      // 崩溃转储只需要近尾，400 行足够
const _logBuf = [];
let _logSent = 0;          // 已成功转发到后端的游标（失败保序下轮重试）
function log(...args) {
  const line = '[' + new Date().toISOString() + '] ' + args.join(' ');
  process.stdout.write(line + '\n');
  _logBuf.push(line);
  if (_logBuf.length > _LOG_CAP) {
    const drop = _logBuf.length - _LOG_CAP;
    _logBuf.splice(0, drop);
    _logSent = Math.max(0, _logSent - drop);
  }
  if (_logBuf.length - _logSent >= 5) _logFlush();
}
const _LOG_BATCH = 20;    // 与后端 api_shell_log 的 lines[:20] 严格对齐
let _logInFlight = false; // 单飞：后端忙/死时日志突发不再打请求风暴
let _logRetryT = null;    // 失败重试定时（注释曾写「3s 后重试」但旧实现
                          // 并没有定时器——对抗审 2026-11-23 实锤）
function _logFlush() {
  if (_logInFlight || !endpointUrl || _logSent >= _logBuf.length) return;
  _logInFlight = true;
  const lines = _logBuf.slice(_logSent, _logSent + _LOG_BATCH);
  try {
    fetch(endpointUrl + '/api/shell_log', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lines }),
      signal: AbortSignal.timeout(2000),
    }).then((r) => r.json().then((j) => {
      // 按后端**实际处理数**推进游标（旧版按发送数推进，批次超 20 时
      // 静丢尾巴——日志突发期恰是最需要留证的时候）
      const n = (j && typeof j.n === 'number')
        ? Math.max(0, Math.min(j.n, lines.length)) : lines.length;
      _logSent += n;
      if (_logRetryT) { clearTimeout(_logRetryT); _logRetryT = null; }
    })).catch(() => {
      // 后端忙/死：游标不动；3s 后原样重试（单定时器，不叠加）
      if (!_logRetryT) {
        _logRetryT = setTimeout(() => { _logRetryT = null; _logFlush(); }, 3000);
      }
    }).finally(() => {
      _logInFlight = false;
      if (_logSent < _logBuf.length) setImmediate(_logFlush);  // 仍有积压接着发
    });
  } catch (_) { _logInFlight = false; }
}
function _logDump() {
  // 致命路径专用：缓冲尾一次性落盘（崩溃期唯一线索）。全文件唯一的
  // 同步追加写盘点——tests/test_p4_cleanup.py 钉死这条防线
  try {
    fs.appendFileSync(SHELL_LOG, _logBuf.slice(-200).join('\n') + '\n');
  } catch (_) {}
}
setInterval(_logFlush, 3000);
process.on('uncaughtException', (e) => {
  try { process.stdout.write('[uncaughtException] ' + (e && e.stack || e) + '\n'); } catch (_) {}
  _logBuf.push('[' + new Date().toISOString() + '] [uncaughtException] ' + (e && e.stack || e));
  _logDump();
  app.exit(1);
});

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
    } catch (e) { log('FC_BACKEND_CMD 解析失败，回落默认探测'); }
  }
  // 单值覆盖（D/调试包用）：bat 里拼 JSON 数组是转义地狱——直接给后端
  // exe 路径即可，--headless 由壳补上
  if (process.env.FC_BACKEND_EXE) {
    const p = String(process.env.FC_BACKEND_EXE);
    try {
      if (p && fs.existsSync(p)) return [p, '--headless'];
    } catch (_) {}
    log('FC_BACKEND_EXE 无效，回落默认探测：', p);
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
  _logDump();   // 致命路径：此刻后端多半已死（面板无记录）——缓冲尾落盘
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
  // 单实例双保险（用户定调「只能有一个」）：除 requestSingleInstanceLock
  // 外，再探活 endpoint 上的后端——dev/装机版本混跑或陈旧锁失效时，避免
  // 双后端互删 endpoint、抢 9222
  const _old = readEndpoint();
  if (_old && _old.url && await probeStatus(_old.url)) {
    fatal('已有实例在运行',
      '检测到另一实例（' + _old.url + '，pid=' + (_old.pid || '?') + '）尚在运行。\n' +
      '同一时间只能运行一个实例：请先退出它（托盘右键退出）再启动。\n' +
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

  BOOT_TOKEN = crypto.randomUUID ? crypto.randomUUID()
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
      // 文件关联注册用：Shell exe + 源码形态的 app 目录（packaged 为空）。
      // 后端 file_assoc 不能再用 sys.executable——那是 sidecar 后端，不是壳
      FC_SHELL_EXE: process.execPath,
      FC_SHELL_APP: app.isPackaged ? '' : path.resolve(__dirname),
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
  // spawn 报错后 'exit' 不保证再来、exitCode 仍为 null——就绪轮询靠它提前收手，
  // 否则 fatal 弹框之后还要空转到 deadline
  let spawnFailed = false;
  // 2026-11-23 总审计 a683-A5：可执行不存在/无权限时 spawn 报的是 'error'
  // 而不是 'exit'——原先没挂监听，异常冒成 uncaughtException，壳无声消失、
  // 没有任何弹框。这里接管并走 fatal（与 exit 分支同一条告知链）。
  backend.on('error', (err) => {
    spawnFailed = true;
    log(util.format('后端 spawn 失败：%s', err && err.message));
    if (exiting || reallyQuitting) return;
    fatal('后端启动失败',
      '无法启动后端进程：' + String((err && err.message) || err) + '\n\n' +
      '后端命令：' + cmd.join(' ') + '\n' +
      '排查：' + SHELL_LOG);
  });
  backend.on('exit', (code, signal) => {
    // 2026-11-23 总审计 a683-A4：log() 是 args.join(' ')，不解析占位符——
    // 原先写 %s 的这行会把占位符原样留在日志里、数值甩到行尾
    log(util.format('后端退出 code=%s signal=%s（booted=%s）', code, signal, booted));
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
  const deadline = Date.now()
    + (app.isPackaged ? BOOT_TIMEOUT_MS : BOOT_TIMEOUT_DEV_MS);
  let epTokenWarned = false;
  while (Date.now() < deadline) {
    if (spawnFailed || backend.exitCode !== null) return; // error/exit 回调已接管报错
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
  if (spawnFailed || backend.exitCode !== null) return;
  fatal('后端启动超时',
    (app.isPackaged ? BOOT_TIMEOUT_MS : BOOT_TIMEOUT_DEV_MS) / 1000
    + ' 秒内后端未就绪。\n\n' +
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

// 本次 spawn 注入后端的启动亲和令牌（boot() 里赋值）。模块级是因为两处
// 消费：就绪轮询（只认回写了同一 token 的 endpoint）与 readConfigBool。
let BOOT_TOKEN = '';

function readConfigBool(key, dft) {
  // 尊重 dft：key 缺失用默认（原先 !== false 写法忽略 dft 参数）
  // 容忍 UTF-8 BOM（本仓库编辑链会产出带 BOM 的文件）
  // config 的位置：优先用后端写在 endpoint.json 里的 tool_data_dir（两边永远
  // 同址）；拿不到才回落到上面自己推的 TOOL_DATA_DIR（第八轮审计 R8-6：嵌套形
  // 调试包里壳与后端不在同一层，各推各的会错位）。点 ✕ 一定在后端启动之后。
  let cfgFile = CONFIG_FILE;
  try {
    const ep = JSON.parse(fs.readFileSync(ENDPOINT_FILE, 'utf-8'));
    // 2026-11-23 总审计（a688 审计 A-3）：只采信**本次启动**的后端写的
    // endpoint——工具目录挪位后启动失败时，残留文件里的 tool_data_dir
    // 指向旧位置，不比对就会去读旧位置的 config.json。token 不符一律回落。
    // （窗口只在就绪轮询认下同一 token 之后才开，所以这里不必再放宽）
    if (ep && ep.boot_token === BOOT_TOKEN
        && typeof ep.tool_data_dir === 'string'
        && path.isAbsolute(ep.tool_data_dir)) {
      cfgFile = path.join(ep.tool_data_dir, 'config.json');
    }
  } catch (_) { /* 无 endpoint → 回落 */ }
  try {
    const raw = fs.readFileSync(cfgFile, 'utf-8').replace(/^\uFEFF/, '');
    const v = JSON.parse(raw)[key];
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

// ---- 文件关联（--open-file <path>，旧 pywebview 入口语义平移）----
// file_assoc.py 写的命令 = "<exe>" --open-file "%1"。壳解析后经 preload
// IPC 转给前端 openFileSmart；第二实例由 second-instance 的 argv 再送一次。
let pendingOpenFile = parseOpenFileArg(process.argv);

// 2026-11-24 用户实锤（源码形态：取消接管→重新接管→双击 txt 没反应）：窗口
// 被唤起、文件不开。根因——Windows 上 second-instance 的 argv **不是**第二
// 实例的原序命令行：Chromium 重新拼接时开关全排在前、位置参数排在后
// （Electron 45.4.1 隔离实测）：
//   [exe, --open-file, --allow-file-access-from-files, --remote-debugging-port=…,
//    <app 目录>, <文件>]
// 原实现取「--open-file 的下一个元素」= --allow-file-access-from-files，以 --
// 开头即判空。首启（process.argv 原序，--open-file 后紧跟路径）没这个问题，
// 所以「壳没开时双击」是好的、「壳已开时双击」是坏的。
// 修：--open-file 开关存在为前提，路径到位置参数里找「是已存在文件的」，从后
// 往前取第一个（源码形态的 app 目录是目录，自然跳过）；首启/第二实例两种
// 顺序同一函数通吃。以 -- 开头的路径不认（资源管理器给的是绝对路径）。
function parseOpenFileArg(argv) {
  const a = argv || [];
  if (a.indexOf('--open-file') < 0) return null;
  for (let i = a.length - 1; i >= 1; i--) {
    const s = a[i];
    if (!s || s.startsWith('--')) continue;
    const p = path.resolve(s);
    try {
      if (fs.statSync(p).isFile()) return p;
    } catch (_) { /* 不是文件/不存在/无权限 → 继续往前找 */ }
  }
  return null;
}

function notifyOpenFile(p) {
  if (!p) return;
  if (!win || win.isDestroyed() || win.webContents.isLoadingMainFrame()) {
    pendingOpenFile = p;   // 窗口还没就绪：did-finish-load 时补发
    return;
  }
  showWindowFromTray();
  win.webContents.send('fc:open-file', p);
}

function backendQuitGraceful() {
  // 通知后端跑清理链（串口/SSH 落盘收口 → worker 优雅停 → base_url 回滚
  // → os._exit）。后端**秒回 200、清理在后台线程**（a680 设计）——收到
  // 200 ≠ 清理完成。对抗审 A 实锤：原实现 200 即 resolve → destroy +
  // app.quit → will-quit 立即树杀，清理链被截在 ~0ms。
  // 修：200 后轮询 /api/status 直到连不上（=清理完自灭）再放行退出；
  // 上限 3.5s（manage_stop 预算 3.5s + 与 a680「有界等待，超时树杀兜底」
  // 同哲学）。
  if (!endpointUrl) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => resolve();
    const req = http.request(endpointUrl + '/api/quit',
      { method: 'POST', timeout: 4000 }, (res) => {
        res.resume();
        const t0 = Date.now();
        const poll = () => {
          if (Date.now() - t0 > 3500) return done();   // 有界等待兜底
          probeStatus(endpointUrl).then((alive) => {
            if (alive) setTimeout(poll, 150);
            else done();   // 后端已自灭 = 清理链跑完
          }).catch(done);
        };
        setTimeout(poll, 150);
      });
    req.on('timeout', () => { req.destroy(); done(); });
    req.on('error', done);
    req.end();
  });
}

function quitApp() {
  if (reallyQuitting) return;
  reallyQuitting = true;
  // 先等后端优雅收尾（有界 4s），再关窗退出——will-quit 的树杀是兜底
  backendQuitGraceful().finally(() => {
    if (win) { try { win.destroy(); } catch (_) {} }
    try { _snipDestroy(); } catch (_) {}   // 常驻截图窗一并收掉
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

// 最大化工作区重钉（启动期 maximize-before-show 路径的保险）：
// fullscreenable:false 已治交互最大化，但启动即 maximize 的路径实测
// 仍会以全屏尺寸越界盖住任务栏（用户首截图实锤；之后被激活/重排
// 「自愈」所以后续正常）。最大化态下 setBounds 不会清 WS_MAXIMIZE
// （IsZoomed 仍真，restore 语义不受影响）。
function pinMaximizeToWorkArea() {
  if (!win || win.isDestroyed() || !win.isMaximized()) return;
  try {
    const wa = screen.getDisplayMatching(win.getBounds()).workArea;
    const b = win.getBounds();
    if (b.x !== wa.x || b.y !== wa.y
        || Math.abs(b.width - wa.width) > 1
        || Math.abs(b.height - wa.height) > 1) {
      win.setBounds({ x: wa.x, y: wa.y, width: wa.width, height: wa.height });
    }
  } catch (_) { /* screen API 竞态：下次事件再钉 */ }
}

function openWindow(url) {
  booted = true;
  endpointUrl = url;
  // 后端地址有了：先取一次下载目录（见下方「下载接管」）——不等第一笔下载
  dlFetchDir();
  const saved = loadShellState();
  const opts = {
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    title: '前端控制台',
    frame: false,   // P2 无边框（页面 topbar 自绘 + drag 区接管）
    // Windows 无边框窗已知坑：默认 fullscreenable 下 maximize() 会按「全屏
    // 式」铺满整屏（连任务栏一起盖掉，用户实锤「本应该是任务栏的」）而非
    // 收敛到工作区。关掉它最大化才正常。工具不用真全屏（旧
    // /api/window/fullscreen 已随 P4 退役），无损失。
    fullscreenable: false,
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
  win.webContents.on('will-attach-webview', (_e, webPreferences, params) => {
    // 2026-11-24 AI 浏览器视图不挂密码填充 guest-preload（AI 自动操作登录页
    // 不该弹「保存密码」/候选填充）；其余加固项照旧。分区名只在这个事件里
    // 有（did-attach-webview 的 params 里没有，实测）——所以在这里凭它决定
    // 挂不挂 preload，并记下标记给 did-attach-webview 兜底（那里的首选判据
    // 是直接看 guest 的分区，不依赖两个事件的先后）
    aibrPending = !!(params && params.partition === AIBR_PARTITION);
    if (aibrPending) {
      delete webPreferences.preload;
    } else {
      webPreferences.preload = GUEST_PRELOAD;
    }
    webPreferences.nodeIntegration = false;
    webPreferences.nodeIntegrationInSubFrames = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
    webPreferences.webSecurity = true;
    webPreferences.allowRunningInsecureContent = false;
    // 后台可用（2026-11-25 用户令：AI 浏览器后台/最小化/失焦下继续操作）。
    // **只给 AI 浏览器视图设**，普通网页标签页（persist:webtabs）保持默认。
    // 官方类型声明（electron.d.ts 的 backgroundThrottling）说的是「同窗口里只要有
    // 一个 webContents 关了这个，**整窗的帧合成**都不再节流」——但受控实验实测
    // （见 AGENTS.md）：定时器**不**跟着传播，主界面 setInterval 仍只有 3 次/3s、
    // rAF 0 次，只有 AI 浏览器 guest 自己是 30 次/3s。所以这个设置不会让主界面和
    // 普通网页标签在后台全速烧 CPU；反过来，它换来的是 guest 最小化后
    // visibilityState 仍为 visible（输入与截图都不需要额外唤醒，实测 25 秒深
    // 冻结后点击仍 1ms 送达）。别因为那句官方描述就撤掉它——先复测。
    if (aibrPending) webPreferences.backgroundThrottling = false;
  });
  // 认领进集合：首选不依赖事件顺序的分区判据，aibrPending（will-attach 认出来
  // 的标记）只在分区判不出来时兜底。挂载即登记——它的第一批弹窗（页面初始
  // 脚本就能 window.open）也会被改道，不必等到 attach 取到 CDP 标识之后
  win.webContents.on('did-attach-webview', (_e, gwc) => {
    const byPartition = aibrIsAiGuest(gwc);
    if (byPartition === true || (byPartition === null && aibrPending)) aibrRegister(gwc);
    aibrPending = false;
  });
  if (saved && saved.max) {
    win.maximize();
    pinMaximizeToWorkArea();   // maximize 事件未必覆盖 show 前的越界态，启动即钉
  }
  let winShownOnce = false;   // ready-to-show 到过（首启窗口刻意晚显，见下）
  win.once('ready-to-show', () => { if (win) { winShownOnce = true; win.show(); } });
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
  // a624 语义平移（P4）：屏蔽浏览器级快捷键（F5/F12/Ctrl+R/Ctrl+Shift+I/J）
  // ——刷新走页面「强制刷新」按钮，DevTools 走日志窗按钮（fc:devtools）。
  // 网页 tab 是独立 guest，不受本 handler 影响（F5/Ctrl+F 在那边是本职）。
  win.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    const k = String(input.key || '').toLowerCase();
    const mod = !!(input.control || input.meta);
    if (k === 'f5' || k === 'f12'
        || (mod && !input.alt && (k === 'r' || (input.shift && (k === 'i' || k === 'j'))))) {
      e.preventDefault();
    }
  });
  // 窗态推送：maximize/unmaximize 事件 + 页面就绪初推（DOMContentLoaded
  // 时 preload 已挂，onState 订阅先于本帧到达也安全——send 是排队消息）
  win.on('maximize', () => { pinMaximizeToWorkArea(); pushWinState(); });
  win.on('unmaximize', pushWinState);
  win.webContents.on('did-finish-load', () => {
    pushWinState();
    // 文件关联首启：等前端模块就绪后再送（load 完成时 type=module 已求值）
    if (pendingOpenFile && win && !win.isDestroyed()) {
      const p = pendingOpenFile;
      pendingOpenFile = null;
      // 2026-11-23 总审计 a683-A6：补发路径原只 send 不唤起——窗口藏在
      // 托盘、恰逢页面重载时双击文件，用户看不到任何反应。与
      // notifyOpenFile 的即时路径同款唤起。首启除外：ready-to-show 未到
      // 之前窗口是故意不显的（白屏闪避），不抢这个时机。
      if (winShownOnce && !win.isVisible()) showWindowFromTray();
      win.webContents.send('fc:open-file', p);
    }
  });
  // 窗口记忆：move/resize 防抖落盘（最小化/最大化瞬间的垃圾 bounds 由
  // getNormalBounds 天然免疫——它恒返回 Normal 态矩形）
  let saveTimer = null;
  const saveDebounced = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveShellState, 500);
  };
  // resize 兜底：启动越界态常在后续重排时才被纠正——只要处于最大化，
  // 任何 resize 都顺手重钉工作区（幂等，bounds 已正则空转）
  win.on('resize', () => { pinMaximizeToWorkArea(); saveDebounced(); });
  win.on('move', saveDebounced);
  // 关闭语义：close_to_tray（后端 config，与历史版本共用）开着 → 驻托盘；
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
  // 截图常驻窗预热（旧 snip.prewarm 同款）：避开主窗创建高峰，3s 后拉起
  // 隐藏 renderer——第一次热键/📷 即 <1s 且零黑屏
  setTimeout(() => { try { prewarmSnip(); } catch (_) {} }, 3000);
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
      // 2026-11-24 AI 浏览器视图的弹窗留在它自己里（用户正看着它被 AI 操作，
      // 不该跳去别的 tab）；其余 webview 照旧推到主 tab 栏开网页 tab
      if (aibrIds.has(contents.id)) {
        win.webContents.send('fc:aibr-open-url', url);
      } else {
        win.webContents.send('fc:webtab-open', url);
      }
    }
    return { action: 'deny' };
  });
  // ---- guest 网页右键菜单（用户需求：刷新等浏览器必备项；**只对网页生效**）----
  // Electron 默认不给任何 webContents 弹右键菜单（主 UI 自绘 ctx-menu.js 不受
  // 影响——这里只挂 webview guest，主窗 type 是 window，永远走不到）。
  // 菜单项对齐 Chrome 常用集：导航 / 链接 / 图片 / 编辑 / 检查。所有动作直
  // 接作用在 guest 的 webContents 上——不经页面 JS，网页无法感知/劫持。
  contents.on('context-menu', (_ev, p) => {
    // 导航状态/动作都必须在 guest **页面内**完成（实测 Electron 45：
    // webview guest 的 navigationHistory.canGoBack 恒 false、goBack() 无
    // 效果，旧版 canGoBack()/goBack() 同样失效——历史由页面侧 <webview>
    // 维护，主进程 WebContents 代理拿不到）。guest 内 Navigation API 判态
    // + history.back/forward 实测可靠。判态是异步的：菜单延迟几毫秒弹出
    //（用户无感）；取态失败时兜底两项可点（无历史时点击无副作用）。
    const _navJs = '({b: !!(window.navigation && navigation.canGoBack),' +
                   ' f: !!(window.navigation && navigation.canGoForward)})';
    contents.executeJavaScript(_navJs).then(
      (s) => popupGuestMenu(contents, p, !!(s && s.b), !!(s && s.f)),
      () => popupGuestMenu(contents, p, true, true)
    );
  });
});

// ---- AI 浏览器（2026-11-24 用户需求：AI 用 CDP 操作网页时，页面显示在 AI
// 会话右侧分屏，用户看着 AI 操作）----
// 前端（web/js/harness/ai-browser.js）在分屏里建
// <webview partition="persist:fc-ai-browser">；本进程三件事：
//   ① will-attach-webview 凭分区名认出它，不挂密码填充 guest-preload（见 openWindow）；
//   ② 前端 dom-ready 后交来 webContentsId → 用 webContents.debugger 取该
//      guest 的 CDP targetId，POST 给后端登记（后端 src/ai_browser.py 按它
//      直连发导航/点击/输入）。不走「/json/list 取第一个 webview」——多个
//      网页视图时有歧义；主进程映射法实测与列表一一对应。取完即 detach；
//   ③ 它的弹窗改道回它自己（见 web-contents-created），guest 销毁时通知
//      后端清登记。
const AIBR_PARTITION = 'persist:fc-ai-browser';
const aibrIds = new Set();     // 已认定的 AI 浏览器 guest（webContents.id）
// will-attach-webview 凭分区名认出 AI 浏览器视图后置位，紧随其后的
// did-attach-webview 据此把 guest 认领进上面的集合（见 openWindow）
let aibrPending = false;

function aibrIsAiGuest(gwc) {
  // 不依赖 will-attach / did-attach 先后交替的判据：直接看这个 guest 用的是不是
  // AI 浏览器的分区。判不出来给 null（交给 aibrPending 兜底）。
  // （原先只靠「will-attach 认出来 → 紧随其后的 did-attach 认领」，两个 webview
  //   的挂载事件一旦交错就会漏认或认错——对抗复审指出，顺序没有保证）
  try { return gwc.session === eSession.fromPartition(AIBR_PARTITION); }
  catch (_) { return null; }
}

const aibrFramed = new Set();         // 已挂过帧订阅的 guest（按 webContents.id 记）

function aibrRegister(gwc) {
  // 挂载即登记：弹窗改道与 attach 校验都从这一刻起生效。guest 销毁时通知
  // 后端清登记（页面刷新 / 舞台被回收都会走到这里）
  aibrIds.add(gwc.id);
  // 挂载即挂帧订阅（缘由见下）：随 guest 销毁一起结束，不用摘。
  // **同一个 guest 只挂一次**：did-attach-webview 对同一个 guest 会触发不止一次——
  // 视图刚建出来时一次（此时还是空白初始文档），首次导航提交、换到网页自己的进程后
  // 又一次（实测两次相隔约 1.8 秒，id 相同、但两次给的 webContents 是不同的 JS 包装，
  // 所以只能按 id 记，WeakSet 按对象记拦不住）
  if (!aibrFramed.has(gwc.id)) {
    aibrFramed.add(gwc.id);
    try {
      gwc.beginFrameSubscription(false, () => {});
    } catch (e) {
      log('AI 浏览器：挂帧订阅失败（窗口最小化期间截图会挂起）— ' + (e && e.message));
    }
  }
  gwc.once('destroyed', () => {
    aibrIds.delete(gwc.id);
    aibrFramed.delete(gwc.id);
    aibrPost('/api/ai_browser/detach', { wc_id: gwc.id });
  });
}

// AI 浏览器 guest 常驻帧订阅（2026-11-25 审查 a699 时实测补的；用户令「后台 / 最小化 /
// 失焦也能用」在截图上的缺口）。
// 受控实验（真实最小化 + WebView guest，Electron 45.4.1 / Chromium 156；隔离环境）：
//   ① 最小化后页面是活着的：Runtime.evaluate 2~4ms、rAF 回调照常、点击送达。但帧呈现不出来
//     ——窗口最小化后显示合成器不绘制，Page.captureScreenshot 等的那次呈现永远不来；窗口一被
//     还原，挂着的截图立刻返回（实测一张挂了 28 秒的就是这样「成功」的）。
//   ② a699 的唤醒链三步（焦点模拟 / 生命周期激活 / setVisibleSize）都不产生帧：最小化 5 秒后
//     只发其中任意几步再截图，5 种组合全部 6 秒无回应。
//   ③ 兜底里的 Emulation.setDeviceMetricsOverride 能让「还没点过」的页面出图（但每张先白等
//     3 秒超时）。一旦点过页面就不行：最小化 30 秒后「点击 → 截图」三条路全挂、共 31 秒，
//     2 次复现 2 次失败——而「点击 → 看结果」正是 AI 最基本的循环。
//   ④ 挂上帧订阅之后，最小化时截图 50~146ms；渲染进程崩溃两次、舞台回收后重建、还原后再
//     最小化（3 秒 / 30 秒）都复测通过。但**订阅必须在那次隐藏之前就已经在**：窗口藏下去之后
//     才挂（minimize 事件当下 / +500ms；只订 AI 视图、订全部网页视图、连宿主页一起订）约 60 轮
//     统计只有三成活——所以不能「跟着最小化状态挂 / 摘」，只能常驻。
//   ⑤ **已知限制（没找到解法，别再重复试）**：窗口不可见期间 guest 一旦发生导航，截图就挂到
//     窗口可见一次为止——最小化状态下导航后「点击 → 截图」31 秒失败；窗口还原之后再最小化
//     即恢复（99~161ms），中间做过可见态的导航 / 点击 / 截图都不要紧，用户还原后看到的页面
//     也是正常的（不是白屏）。救不回来的办法都试过：重挂订阅 8 次 0 帧；壳侧
//     capturePage 立刻 UnknownVizError（默认参数则不返回）；改订宿主页一样挂。
//     点击 / 输入 / 读页面 / 导航本身不受影响，只是那一页要等窗口可见一次才截得到。
//   ⑥ incrementCapturerCount 在这个版本已经不存在（is not a function）；onlyDirty=true 不省
//     什么（实测整帧 +3.1% / 只取脏区 +4.7% 单核，差在噪声里），照用 false。
// 代价（实测，被控页 570x342、以约 62 帧/秒动画时各进程的单核占用）：主进程 +2~4%、GPU 与
// 渲染进程 +1~3%（噪声量级）；静止页面不出帧、不花 CPU。全高清窗格按像素量大约放大十倍。
// 只给 **AI 浏览器 guest**（aibrIds 里的）挂，普通网页标签页不动。

function aibrPost(path, body) {
  // 与后端 AI 浏览器登记表通信。失败返回 null（下次 attach 会重新登记）
  if (!endpointUrl) return Promise.resolve(null);
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 8000);
  return fetch(endpointUrl + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}), signal: ctl.signal,
  }).then((r) => r.json()).catch(() => null).finally(() => clearTimeout(t));
}

// ---- 下载接管（2026-11-24 用户令）----
// 此前壳完全不管下载：Electron 对没接管的下载弹系统保存框，存哪、存没存成只有
// 用户自己知道——工具内的 AI 点完下载只能照页面文案说「浏览器下载列表可见」，
// 用户自己在网页标签页里下载，更是点了保存就没下文。
// 用户令：普通网页标签页的下载也对接到同一套——不弹保存框，直接存进下载目录，
// 有进度显示和完成提示；下载目录默认 数据目录\download，可在设置里手动指定。
//   · 目录只认下载中心给的（GET /api/downloads/config，src/downloads.py）：数据
//     目录在哪、用户把它改成了哪里、隔离态落在沙箱哪里只有后端知道，壳不自算。
//     后端给不出可用目录时这里是 null：不接管，退回 Electron 默认行为（弹保存
//     框）——宁可多问一次，也不偷偷落到别处。
//   · 挂在两个分区的 session 上：AI 浏览器与网页标签页（persist:webtabs）。工具
//     自己的主界面用默认 session，不在此列——它的导出 / 另存为照旧。
const DL_SOURCES = {};               // 分区名 → 来源标记（后端记录、界面提示用）
DL_SOURCES[AIBR_PARTITION] = 'ai_browser';
DL_SOURCES['persist:webtabs'] = 'webtab';
const DL_UPDATE_MS = 450;            // 进度上报的最小间隔。Electron 的更新事件约 500ms 一次，
                                     // 取 450 = 每个事件都报（面板上的进度条半秒走一格）
let dlDir = null;                    // 当前下载目录（下载中心给的）；null = 不接管
let dlSeq = 0;
const dlItems = new Map();           // 进行中的下载 id → DownloadItem（取消用）
const aibrDlReserved = new Set();    // 进行中的下载占用的目标路径（并发同名时不撞车）
const AIBR_WIN_RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i;

function aibrSafeName(name) {
  // 文件名来自服务器 / 页面，不可信：去掉路径分隔符与 Windows 非法字符（防
  // `..\x` 写出下载目录）、去尾随的点/空格（Windows 不许）、避开保留设备名
  // （`CON.fcpk`、`NUL` 这类在 Windows 上建不出来）、限长
  let s = String(name || '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim();
  s = s.slice(0, 180).replace(/[. ]+$/, '');
  if (!s) s = 'download';
  if (AIBR_WIN_RESERVED.test(s)) s = '_' + s;
  return s;
}

function aibrDlPath(dir, name) {
  // 同名不覆盖：目录里已有（或另一个进行中的下载已占用）同名文件就加 (1)、(2)…
  const ext = path.extname(name), base = path.basename(name, ext);
  let p = path.join(dir, name);
  for (let n = 1; n < 10000; n++) {
    let taken;
    try { taken = fs.existsSync(p); } catch (_) { taken = true; }
    if (!taken && !aibrDlReserved.has(p)) break;
    p = path.join(dir, base + ' (' + n + ')' + ext);
  }
  return p;
}

function dlTakeOver(item, source) {
  if (!dlDir) return;   // 下载中心没给出可用目录：Electron 默认行为（弹保存框）
  try {
    const name = aibrSafeName(item.getFilename());
    const target = aibrDlPath(dlDir, name);
    aibrDlReserved.add(target);
    // 设了保存路径 Electron 就不弹保存框，直接写到这里（先写 .crdownload 再改名）
    item.setSavePath(target);
    const id = 'dl_' + Date.now().toString(36) + '_' + (++dlSeq);
    // blob: 下载（页面 fetch→Blob→a.download）的来源地址又长又没用，不报。
    // 记录用**实际落盘**的文件名（可能已加序号），看到的名字要和磁盘上的一致
    const url = String(item.getURL() || '');
    const base = { id, source, filename: path.basename(target),
                   url: /^blob:/.test(url) ? '' : url.slice(0, 300) };
    const report = (o) => aibrPost('/api/downloads/report', Object.assign({}, base, o));
    let last = 0;
    dlItems.set(id, item);
    report({ event: 'started', total: item.getTotalBytes() });
    item.on('updated', () => {
      // 别按事件带的 state 字符串过滤：实测（Electron 45，端到端里旁听）这个值是
      // 'progressing'，不是文档写的 'in_progress'——按后者写会把所有进度帧都吃掉，
      // 面板上的进度条从头到尾是 0，直到结束才跳满（2026-11-24 实跑踩到）。
      // 「还没结束」以 dlItems 为准：done 里会删掉它
      if (!dlItems.has(id)) return;
      const now = Date.now();
      if (now - last < DL_UPDATE_MS) return;
      last = now;
      report({ event: 'updated', received: item.getReceivedBytes(), total: item.getTotalBytes() });
    });
    item.on('done', (_ev, state) => {
      aibrDlReserved.delete(target);
      dlItems.delete(id);
      report({ event: 'done', state, path: target,
               received: item.getReceivedBytes(), total: item.getTotalBytes() });
      dlFetchDir();      // 用户可能改了下载目录：顺手刷新，下一条下载就用新的
    });
  } catch (e) {
    log('[downloads] 接管下载失败：' + (e && e.message));
  }
}

function dlSetup() {
  for (const part of Object.keys(DL_SOURCES)) {
    eSession.fromPartition(part).on('will-download',
      (_e, item) => dlTakeOver(item, DL_SOURCES[part]));
  }
}

function dlFetchDir() {
  // 向下载中心要当前下载目录。只有后端明确说「可用」才接管
  if (!endpointUrl) return Promise.resolve(null);
  return fetch(endpointUrl + '/api/downloads/config')
    .then((r) => r.json())
    .then((j) => {
      dlDir = (j && j.ok === true && j.usable === true
               && typeof j.dir === 'string' && j.dir) ? j.dir : null;
      return dlDir;
    })
    .catch(() => null);
}

app.whenReady().then(() => {
  try { dlSetup(); }
  catch (e) { log('[downloads] 下载监听挂载失败：' + (e && e.message)); }
  // 用户在设置里改了下载目录：界面会经 IPC 让这里立刻重取；另加低频轮询兜底
  setInterval(() => { dlFetchDir(); }, 30000);
});

ipcMain.on('fc:dl-refresh', (e) => {
  // 只认主界面发来的（guest 没有 preload，拿不到 ipcRenderer——双保险）
  if (win && !win.isDestroyed() && e.sender === win.webContents) dlFetchDir();
});

ipcMain.handle('fc:dl-cancel', (e, id) => {
  // 取消一个进行中的下载。同样只认主界面
  if (!win || win.isDestroyed() || e.sender !== win.webContents) return false;
  const it = dlItems.get(String(id));
  if (!it) return false;
  try { it.cancel(); return true; } catch (_) { return false; }
});

async function aibrAttach(wcId) {
  const n = Number(wcId);
  const wc = webContents.fromId(n);
  // 只认分区名认定过的 AI 浏览器视图：主界面就算传来别的 webview（比如用户
  // 自己的网页 tab）也不给它登记——登记什么，devtools_* 的默认目标就是什么
  if (!wc || wc.isDestroyed() || wc.getType() !== 'webview' || !aibrIds.has(n)) {
    return { ok: false, err: '不是 AI 浏览器的网页视图（wcId=' + wcId + '）' };
  }
  let targetId = null;
  let lastErr = '';
  for (let attempt = 0; attempt < 6 && !targetId; attempt++) {
    // guest 刚挂上时 target 可能还没就绪：短重试（实测 dom-ready 后一次即中）
    try {
      wc.debugger.attach('1.3');
      const r = await wc.debugger.sendCommand('Target.getTargetInfo');
      targetId = (r && r.targetInfo && r.targetInfo.targetId) || null;
    } catch (e) {
      lastErr = (e && e.message) || String(e);
    }
    try { if (wc.debugger.isAttached()) wc.debugger.detach(); } catch (_) {}
    if (!targetId) await new Promise((r) => setTimeout(r, 300));
  }
  if (!targetId) return { ok: false, err: '取不到该网页视图的 CDP 标识：' + lastErr };
  const r = await aibrPost('/api/ai_browser/attach',
    { wc_id: n, target_id: targetId, partition: AIBR_PARTITION });
  // 后端没明确回 ok 就算失败：aibrPost 在后端不通 / 回非 JSON 时给 null，原先
  // 照样回「成功」——前端徽标谎报「已连接」，每次操作空等满超时（对抗审计实锤）
  if (!r || r.ok !== true) {
    return { ok: false, err: (r && r.err) || '后端没有确认登记（后端未启动或不通）' };
  }
  return { ok: true };
}

ipcMain.handle('fc:aibr-attach', (e, wcId) => {
  // 只认主界面发来的（外站 guest 没有 preload，拿不到 ipcRenderer——双保险）
  if (!win || win.isDestroyed() || e.sender !== win.webContents) {
    return { ok: false, err: '只允许主界面调用' };
  }
  return aibrAttach(wcId);
});

// guest 网页右键菜单（模块级：context-menu 回调异步取态后调用）
function popupGuestMenu(contents, p, canBack, canFwd) {
  // 轻量导航封装：history.back/forward 在 guest 页面内执行，返回 Promise
  const _nav = (js) => { try { contents.executeJavaScript(js).catch(() => {}); } catch (_) {} };
  const tpl = [
    { label: '后退', enabled: canBack, click: () => _nav('history.back()') },
    { label: '前进', enabled: canFwd, click: () => _nav('history.forward()') },
    { label: '刷新', click: () => _nav('location.reload()') },
  ];
  tpl.push({ type: 'separator' });
  if (p.linkURL) {
    tpl.push({
      label: '在新标签页打开链接',
      click: () => {
        if (win && !win.isDestroyed()) win.webContents.send('fc:webtab-open', p.linkURL);
      },
    });
    tpl.push({
      label: '复制链接地址',
      click: () => clipboard.writeText(p.linkURL),
    });
  }
  if (p.mediaType === 'image' && p.srcURL) {
    tpl.push({ label: '复制图片地址', click: () => clipboard.writeText(p.srcURL) });
  }
  if (p.isEditable) {
    tpl.push({ type: 'separator' });
    tpl.push({ label: '剪切', enabled: !!(p.editFlags && p.editFlags.canCut), click: () => contents.cut() });
    tpl.push({ label: '复制', enabled: !!(p.editFlags && p.editFlags.canCopy), click: () => contents.copy() });
    tpl.push({ label: '粘贴', enabled: !!(p.editFlags && p.editFlags.canPaste), click: () => contents.paste() });
    tpl.push({ label: '全选', enabled: !!(p.editFlags && p.editFlags.canSelectAll), click: () => contents.selectAll() });
  } else if (p.selectionText) {
    tpl.push({ type: 'separator' });
    tpl.push({ label: '复制', click: () => contents.copy() });
    tpl.push({ label: '全选', click: () => contents.selectAll() });
  }
  tpl.push({ type: 'separator' });
  tpl.push({ label: '检查元素', click: () => {
    try { contents.inspectElement(p.x, p.y); } catch (e) { log('检查元素失败：', e.message); }
  } });
  try {
    Menu.buildFromTemplate(tpl).popup({
      window: (win && !win.isDestroyed()) ? win : undefined,
    });
  } catch (e) { log('网页右键菜单失败：', e.message); }
}

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
// 通用「另存为」：导出类功能用（后端日志导出 / 代码索引范围配置导出）。
// 旧 pywebview 形态靠 main.py 的 _save_file_dialog，P4 把它删了却没补等价物
// ——两处导出从此弹不出保存框、静默落桌面。现在前端先经此拿到路径，再回传
// 后端落盘。返回 '' = 用户取消；对话框本身出错则 reject（调用方据此报失败，
// 不要回落成「悄悄写到桌面」）。只认主窗。
ipcMain.handle('fc:save-as', async (event, opts) => {
  // 2026-11-23 总审计 W-7：非主 UI 调用原先返回 ''——与「用户取消」无法
  // 区分，多窗/非主 UI 场景静默当取消。拒绝就抛错：调用方的 catch 据此
  // 报「无法打开保存框」，拒写语义不变。
  if (!_isMainUi(event)) throw new Error('forbidden: save-as 只允许主界面调用');
  const o = opts || {};
  const safe = String(o.defaultName || '')
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim().slice(0, 120) || 'export.txt';
  let baseDir;
  try { baseDir = app.getPath('desktop'); } catch (_) {
    try { baseDir = app.getPath('home'); } catch (_) { baseDir = undefined; }
  }
  try {
    const r = await dialog.showSaveDialog(win, {
      title: String(o.title || '另存为'),
      defaultPath: baseDir ? path.join(baseDir, safe) : safe,
      filters: Array.isArray(o.filters) && o.filters.length ? o.filters : undefined,
    });
    return (r.canceled || !r.filePath) ? '' : r.filePath;
  } catch (e) {
    log('另存为对话框失败：', e.message);
    throw e;
  }
});
// 剪贴板（pywebview 兼容层等价实现，FileBridge 全量 7 方法就此齐平）
ipcMain.handle('fc:clipboard-read', () => clipboard.readText());
ipcMain.handle('fc:clipboard-write-image', (_e, p) => {
  try {
    clipboard.writeImage(nativeImage.createFromPath(String(p || '')));
    return true;
  } catch (_) { return false; }
});

// ---- P4 截图覆盖窗（旧 pywebview 常驻窗语义平移）----
// Python 负责 DPI 抓屏（--snip-grab → TEMP BMP）；壳维护一个**常驻隐藏**
// BrowserWindow 承载 web/screenshot.html（旧形态同款：常驻 renderer 免每次
// 冷启，隐藏期不销毁）。触发 → 发 fc:snip-arm（带底图物理偏移）→ 页面
// 按自身实测视口取裁剪底图、**画完才回 fc:snip-ready** → 这里才 show。
// 绝不在 ready-to-show 就 show——那一刻页面还是黑的，用户会看到全屏黑罩
// （首版实锤）。完成/另存/取消 → 隐藏待命；空闲 10 分钟销毁回收 renderer。
let snipWin = null;
let snipPageReady = false;   // 页面已加载并注册 onSnipArm（fc:snip-hello 已到）
let snipPendingArm = null;   // 待下发的裁剪偏移 {x,y}（触发早于页面就绪时暂存）
let snipShowTimer = null;    // ready 兜底：超时强制显形，防页面卡死致永远无窗
let snipIdleTimer = null;    // 隐藏待命 10 分钟后销毁（旧形态同款取舍）
let snipLastArmTs = 0;       // 最近一次 arm 时刻（SSE 与 📷 按钮双触发的去重窗）
let snipArming = false;      // arm 在途硬锁（探针实锤：双路径并发每次双 arm，
                             // 旧去重锁的 !isVisible 条件在透明预显示后恒失效）
let snipArmActive = false;   // arm 之后、隐藏/销毁之前：一次截图流程进行中
// 同一触发的双路径去重窗：前端点 📷 后既等 /api/snip/start 的响应直调
// openSnip，又收后端在同一个接口里广播的 SSE snip_open——两份是同一次
// 用户动作的回声。2026-11-23 总审计 P0-3：原先只有 snipArming 在途锁，函数
// 一返回就松；SSE 回声排在大量 AI 流消息后面、晚到数百 ms 时（对话高峰期
// 截图）会再 arm 一次，页面重新取图/重建插件——用户拖到一半的选区被重置。
// 现以「流程进行中 + 落在窗口内」判为回声并流。窗口外的再次触发是用户在
// 截图界面里重新按键（重新开始），行为照旧。
const SNIP_DUP_WINDOW_MS = 2500;
let snipBounds = null;       // 目标物理布局（DIP）——ready 时重钉尺寸/置顶用

// 显示三连（ready 与 8s 兜底共用）：
// 1) 重新断言 topmost——Electron 实锤坑：alwaysOnTop 在 hide()/show() 一轮
//    后会静默丢失，常驻窗复用模式必然踩中 → 任务栏压在覆盖层上（用户实锤
//    「不是全屏、任务栏截不到」）。screen-saver 级在任务栏之上。
// 2) 全尺寸重钉——非 topmost 期间可能被工作区逻辑动过；resizable:false 下
//    setBounds 会被 Windows 拒绝，临时放开再锁回（经典 workaround）。
// 3) opacity 0→1 瞬时显形——show() 的 DWM 开窗动画在完全透明时已播完，
//    用户看到的是「屏幕瞬间定住」，没有弹窗感（用户实锤「有弹窗行为」）。
function _snipReveal() {
  const w = snipWin;
  if (!w || w.isDestroyed()) return;
  try {
    if (!w.isVisible()) w.show();
    w.setAlwaysOnTop(true, 'screen-saver');
    if (snipBounds) {
      const b = w.getBounds();
      if (Math.abs(b.x - snipBounds.x) > 1 || Math.abs(b.y - snipBounds.y) > 1
          || Math.abs(b.width - snipBounds.width) > 1
          || Math.abs(b.height - snipBounds.height) > 1) {
        w.setResizable(true);
        w.setBounds(snipBounds);
        w.setResizable(false);
        // Windows 上 resizable 开关与最大化开关联动：setResizable(true) 会
        // 把最大化能力一并恢复——必须重锁，否则一个 Win+Up 就能把覆盖窗
        // 最大化（实测实锤 -7,0,2068×1242）
        w.setMaximizable(false);
      }
    }
    w.setOpacity(1);
    w.focus();
  } catch (_) { /* 窗口刚销毁等竞态：静默（下次触发重建） */
  }
}

function _isSnip(event) {
  return !!snipWin && !snipWin.isDestroyed() && event.sender === snipWin.webContents;
}

function _snipDeliverArm() {
  if (snipWin && !snipWin.isDestroyed() && snipPageReady && snipPendingArm) {
    try { snipWin.webContents.send('fc:snip-arm', snipPendingArm); }
    catch (_) { /* 渲染进程刚崩 → 下次触发重建 */ }
  }
}

function _snipArmStart(phys) {
  snipLastArmTs = Date.now();
  snipArmActive = true;
  snipPendingArm = phys;
  _snipDeliverArm();
  // 提前以全透明状态显示：DWM 开窗动画此刻播完（不可见），ready 后
  // _snipReveal 直接 opacity→1 瞬时显形——零弹窗感。透明窗会短暂接收
  // 鼠标输入（~0.3s 到 ready），与 Snipaste 触发瞬间的无响应期等价
  if (snipWin && !snipWin.isDestroyed() && !snipWin.isVisible()) {
    try { snipWin.show(); } catch (_) {}
  }
  if (snipShowTimer) clearTimeout(snipShowTimer);
  // 兜底：正常路径 ~0.5s 内 ready；到这还没 ready 说明页面异常。**销毁
  // 而不是强制显示**——死页面上屏=一块 Esc 都关不掉的纯黑罩，且会被下次
  // 抓屏抓到形成黑屏死循环（用户实锤）；销毁后下次触发冷启重建
  snipShowTimer = setTimeout(() => {
    log('截图窗 8s 未 ready，销毁待下次触发重建');
    _snipDestroy();
  }, 8000);
  if (snipIdleTimer) { clearTimeout(snipIdleTimer); snipIdleTimer = null; }
}

function _snipHide() {
  snipArmActive = false;    // 流程结束（完成/另存/取消/取图失败）：去重窗关门
  if (snipShowTimer) { clearTimeout(snipShowTimer); snipShowTimer = null; }
  if (snipWin && !snipWin.isDestroyed()) {
    try { snipWin.hide(); } catch (_) {}
    // 透明度归零：下轮 show() 的开窗动画依旧在不可见状态播放
    try { snipWin.setOpacity(0.01); } catch (_) {}
    // 0.01 而非 0：全透明分层窗会让 GPU 合成的 canvas 不上屏（DOM 正常、
    // 导出正常、选区逻辑正常、就是看不见——用户实锤+探针佐证）。保留
    // 1% 透明度让合成器持续产帧，视觉上与全透明无异
  }
  // 空闲回收：常驻 renderer ~100-150MB，10 分钟不用就销毁（旧形态 1800s
  // 同款取舍；下次触发走冷启动，慢一点但无黑屏）
  if (snipIdleTimer) clearTimeout(snipIdleTimer);
  snipIdleTimer = setTimeout(() => {
    if (snipWin && !snipWin.isDestroyed() && !snipWin.isVisible()) {
      try { snipWin.destroy(); } catch (_) {}
      if (snipWin && snipWin.isDestroyed()) { snipWin = null; snipPageReady = false; }
    }
  }, 10 * 60 * 1000);
}

function _snipDestroy() {
  snipArmActive = false;
  if (snipShowTimer) { clearTimeout(snipShowTimer); snipShowTimer = null; }
  if (snipIdleTimer) { clearTimeout(snipIdleTimer); snipIdleTimer = null; }
  if (snipWin && !snipWin.isDestroyed()) {
    try { snipWin.destroy(); } catch (_) {}
  }
  snipWin = null;
  snipPageReady = false;
  snipPendingArm = null;
}

async function _snipGeo() {
  const r = await fetch(endpointUrl + '/api/snip/geo',
                        { signal: AbortSignal.timeout(3000) });
  const j = await r.json();
  const g = j && j.geo;
  if (!g || !(g.w > 0) || !(g.h > 0)) throw new Error('底图几何缺失');
  return g;
}

function _snipTarget() {
  // 目标屏幕（DIP bounds + 缩放）。同缩放=虚拟桌面并集（跨屏框选）；
  // 混合 DPI=光标所在屏（Chromium 单窗无法跨不同 DPI 保持物理 1:1）
  const displays = screen.getAllDisplays();
  if (!displays.length) throw new Error('没有可用显示器');
  const scales = new Set(displays.map((d) => Math.round(d.scaleFactor * 1000)));
  if (scales.size === 1) {
    const x0 = Math.min(...displays.map((d) => d.bounds.x));
    const y0 = Math.min(...displays.map((d) => d.bounds.y));
    const x1 = Math.max(...displays.map((d) => d.bounds.x + d.bounds.width));
    const y1 = Math.max(...displays.map((d) => d.bounds.y + d.bounds.height));
    return {
      bounds: { x: Math.round(x0), y: Math.round(y0),
                width: Math.round(x1 - x0), height: Math.round(y1 - y0) },
      scale: displays[0].scaleFactor,
    };
  }
  const d = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  return {
    bounds: { x: Math.round(d.bounds.x), y: Math.round(d.bounds.y),
              width: Math.round(d.bounds.width), height: Math.round(d.bounds.height) },
    scale: d.scaleFactor,
  };
}

function _snipPhysOffset(target, geo) {
  // 底图裁剪偏移：窗口原点的物理坐标 − 底图虚拟桌面原点。宽高不在这里算
  // ——页面按自身实测视口取（innerWidth×dpr），DPI 取整差 1px 也不会错位
  let p0;
  try {
    p0 = screen.dipToScreenPoint({ x: target.bounds.x, y: target.bounds.y });
  } catch (_) {
    p0 = { x: Math.round(target.bounds.x * target.scale),
           y: Math.round(target.bounds.y * target.scale) };
  }
  const x = Math.max(0, Math.round(p0.x - geo.x));
  const y = Math.max(0, Math.round(p0.y - geo.y));
  if (x >= geo.w || y >= geo.h) throw new Error('截图区域越界');
  return { x, y };
}

function _snipSameBounds(a, b) {
  return a && b && Math.abs(a.x - b.x) < 1 && Math.abs(a.y - b.y) < 1
      && Math.abs(a.width - b.width) < 1 && Math.abs(a.height - b.height) < 1;
}

function _snipCreate(bounds) {
  const w = new BrowserWindow({
    x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
    frame: false, show: false, resizable: false, movable: false,
    minimizable: false, maximizable: false, fullscreenable: false,
    skipTaskbar: true, alwaysOnTop: true, hasShadow: false,
    backgroundColor: '#000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // 隐藏待命期禁节流：页面在隐藏窗里预取底图/重建插件，节流会让
      // rAF/定时器停摆 → ready 迟迟不来 → 触发 8s 兜底黑窗
      backgroundThrottling: false,
    },
  });
  snipWin = w;
  snipPageReady = false;
  snipPendingArm = null;
  snipBounds = { x: bounds.x, y: bounds.y,
                 width: bounds.width, height: bounds.height };
  w.setAlwaysOnTop(true, 'screen-saver');
  w.setMenu(null);
  // 近全透明待命：后续任何 show() 的 DWM 开窗动画都在不可见状态播放，
  // ready 后 _snipReveal 以 opacity→1 瞬时显形（零弹窗感）。**0.01 而非
  // 0**——全透明=分层窗口，GPU 合成的 canvas 会上屏失败（DOM 正常/导出
  // 正常/交互正常、唯独画布看不见——用户实锤）；1% 透明度视觉等同全透
  // 明，但合成器持续产帧，canvas 不丢
  try { w.setOpacity(0.01); } catch (_) {}
  // 建窗即重钉目标 bounds：Windows 会把非激活窗钳到工作区（探针实锤：
  // 预热窗首 arm 视口 2052×1235=被钳，后续 2048×1280 才是全屏）——
  // resizable 临时放开→setBounds→锁回，附重锁最大化开关（联动坑）
  try {
    w.setResizable(true);
    w.setBounds({ x: bounds.x, y: bounds.y,
                  width: bounds.width, height: bounds.height });
    w.setResizable(false);
    w.setMaximizable(false);
  } catch (_) {}
  w.on('closed', () => {
    // snipArmActive 一并清：Alt+F4 等绕过 _snipHide/_snipDestroy 的关窗不留
    // 「流程进行中」的假象（去重窗靠它判回声）
    if (snipWin === w) { snipWin = null; snipPageReady = false; snipArmActive = false; }
  });
  // 意外最大化护栏（实测实锤）：reveal 里 setResizable(true) 临时放开边框
  // 会连带恢复 Windows 最大化开关（两开关联动），Win+Up/拖顶都能把透明
  // 覆盖窗最大化（实测 bounds 变 -7,0,2068×1242）。一旦发生立即还原。
  w.on('maximize', () => {
    log('截图窗被意外最大化，立即还原');
    try {
      w.unmaximize();
      if (snipWin === w && snipBounds) {
        w.setResizable(true);
        w.setBounds(snipBounds);
        w.setResizable(false);
        w.setMaximizable(false);
      }
    } catch (_) {}
  });
  w.webContents.on('render-process-gone', (_e, details) => {
    log('截图渲染进程退出：', details && details.reason);
    if (snipWin === w) _snipDestroy();
  });
  // 加载失败=页面死透：直接销毁（实测实锤：留着会变成「显示但全透明」的
  // 僵尸窗压在屏幕上吃鼠标，ready 永不到来也不隐藏）；下次触发冷启重建
  w.webContents.on('did-fail-load', (_e, code, desc, url2, isMainFrame) => {
    if (!isMainFrame) return;
    log('截图页加载失败：', code, desc);
    if (snipWin === w) _snipDestroy();
  });
  // 不挂 ready-to-show 显示——显示时机唯一：页面画完底图回 fc:snip-ready
  w.loadURL(endpointUrl + '/web/screenshot.html?v=' + Date.now())
    .catch((e) => {
      log('截图页加载异常：', e.message);
      if (snipWin === w) _snipDestroy();
    });
  return w;
}

async function openSnipWindow() {
  if (!endpointUrl) return { ok: false, err: '后端未就绪' };
  // 双路径并发硬锁（探针实锤每次双 arm）：按钮直调与 SSE 各来一次，旧
  // 时间窗+isVisible 判据在透明预显示后恒放行 → 插件实例连环建/毁。
  // 在途锁内第二调用直接并流；在途锁之外再看去重窗（P0-3，见常量处注释）
  if (snipArming) return { ok: true };
  if (snipArmActive && Date.now() - snipLastArmTs < SNIP_DUP_WINDOW_MS) {
    return { ok: true };
  }
  snipArming = true;
  try {
    const geo = await _snipGeo();
    const target = _snipTarget();
    const phys = _snipPhysOffset(target, geo);
    // 复用判定比「申请过的 bounds」（snipBounds）而不是 getBounds()——OS
    // 会对窗口做工作区钳制/最大化越界等调整，比实际值必然不匹配 → 每次
    // 触发都销毁重建的死循环（ERR_FAILED 刷屏的根因，实测实锤）
    if (snipWin && !snipWin.isDestroyed()
        && !_snipSameBounds(snipBounds, target.bounds)) {
      _snipDestroy();
    }
    if (!snipWin || snipWin.isDestroyed()) {
      _snipCreate(target.bounds);
    } else {
      // 常驻窗复用时同样先重钉（期间可能又被工作区逻辑钳过），等一帧
      // 让 renderer 视口跟上——否则 arm 里量的还是旧尺寸（首次任务栏
      // 盖不住的另一半根因）
      try {
        const b = snipWin.getBounds();
        if (!_snipSameBounds(b, target.bounds)) {
          snipWin.setResizable(true);
          snipWin.setBounds(target.bounds);
          snipWin.setResizable(false);
          snipWin.setMaximizable(false);
          await new Promise((r) => setTimeout(r, 80));
        }
      } catch (_) {}
    }
    _snipArmStart(phys);     // 内部记 snipLastArmTs / 置 snipArmActive
    return { ok: true };
  } catch (e) {
    log('截图覆盖窗打开失败：', e.message);
    return { ok: false, err: e.message };
  } finally {
    snipArming = false;
  }
}

function prewarmSnip() {
  // 旧形态 snip.prewarm 同款：主窗开 3s 后拉起隐藏常驻窗（首载不弹窗），
  // 第一次热键即 <1s。预热不需要底图——页面 hello 后等 fc:snip-arm。
  if (snipWin && !snipWin.isDestroyed()) return;
  try {
    _snipCreate(_snipTarget().bounds);
    log('截图常驻窗已预热（隐藏待命）');
  } catch (e) { log('截图窗预热失败（下次触发冷启动）：', e.message); }
}

ipcMain.handle('fc:snip-open', (event) => {
  if (!_isMainUi(event)) return { ok: false, err: 'forbidden' };
  return openSnipWindow();
});
// 截图覆盖窗自身句柄（窗口识别要排除它——不排除则 hover 永远命中
// 盖全屏的自己）。以十进制字符串回传（HWND 指针宽度可能超 JS 安全整数）
ipcMain.handle('fc:snip-hwnds', (event) => {
  if (!_isSnip(event)) return [];
  try {
    const b = snipWin.getNativeWindowHandle();
    if (!b || !b.length) return [];
    const v = b.length === 8 ? b.readBigUInt64LE(0) : b.readUIntLE(0, b.length);
    return [v.toString()];
  } catch (_) { return []; }
});
// 页面握手：listener 已注册（此刻起 fc:snip-arm 可达）
ipcMain.on('fc:snip-hello', (event) => {
  if (!_isSnip(event)) return;
  snipPageReady = true;
  _snipDeliverArm();
});
// 页面就绪：底图已解码、插件已建——重钉置顶/尺寸后瞬时显形（唯一显形时机）
ipcMain.on('fc:snip-ready', (event) => {
  if (!_isSnip(event)) return;
  if (snipShowTimer) { clearTimeout(snipShowTimer); snipShowTimer = null; }
  _snipReveal();
});
// 底图取失败：立即隐藏（绝不露黑——黑覆盖层一旦上屏，下次抓屏抓到的
// 就是它自己，黑屏死循环，用户实锤）。用户体感=按了没反应，重按即可
ipcMain.on('fc:snip-fail', (event, reason) => {
  if (!_isSnip(event)) return;
  log('截图底图获取失败，覆盖窗已隐藏：', reason);
  _snipHide();
});
ipcMain.handle('fc:snip-done', async (event, b64) => {
  if (!_isSnip(event)) return { ok: false, err: 'forbidden' };
  try {
    const raw = String(b64 || '');
    const dataUrl = raw.startsWith('data:') ? raw : 'data:image/png;base64,' + raw;
    const r = await fetch(endpointUrl + '/api/snip/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_url: dataUrl }),
      signal: AbortSignal.timeout(15000),
    });
    const j = await r.json().catch(() => ({}));
    log('[snip] save-result ' + JSON.stringify(j).slice(0, 200));
    _snipHide();
    return j;
  } catch (e) {
    _snipHide();
    return { ok: false, err: String((e && e.message) || e) };
  }
});
ipcMain.handle('fc:snip-save-as', async (event, dataUrl) => {
  if (!_isSnip(event)) return { ok: false, err: 'forbidden' };
  const raw = String(dataUrl || '').replace(/^data:[^,]*,/, '');
  try {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const name = 'snip_' + d.getFullYear() + pad(d.getMonth() + 1)
               + pad(d.getDate()) + '_' + pad(d.getHours())
               + pad(d.getMinutes()) + pad(d.getSeconds()) + '.png';
    const r = await dialog.showSaveDialog(snipWin, {
      title: '截图另存为',
      defaultPath: path.join(app.getPath('pictures'), name),
      filters: [{ name: 'PNG 图片', extensions: ['png'] }],
    });
    if (!r.canceled && r.filePath) {
      fs.writeFileSync(r.filePath, Buffer.from(raw, 'base64'));
    }
    _snipHide();
    return { ok: !r.canceled, path: r.filePath || null };
  } catch (e) {
    _snipHide();
    return { ok: false, err: String((e && e.message) || e) };
  }
});
ipcMain.handle('fc:snip-cancel', (event) => {
  if (_isSnip(event)) _snipHide();
  return { ok: true };
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
// userData 统一到 productName 目录（前端控制台）。复审 N8 修正旧说法：
// asar 内 package.json 保留 name 字段（electron-builder 不注入 productName），
// dev/装机两形态 getName() 都是 frontend-console-shell → 本 setPath 两形态
// 都会执行。不统一则 dev 壳与装机版 userData 不同目录，单实例锁互不感知
// = 可同时双开、两个后端互踩 endpoint.json（实测实锤）。统一后锁跨形态
// 互斥，兑现用户定调「只能有一个」。锚点不受影响（上方显式公式与此解耦）
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
  app.on('second-instance', (_e, argv) => {
    showWindowFromTray();
    const p = parseOpenFileArg(argv);
    if (p) notifyOpenFile(p);
  });
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
