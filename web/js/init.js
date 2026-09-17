// 性能计时：页面加载各阶段上报后端（诊断启动慢）
const _perf = { domStart: performance.now(), initStart: 0, initDone: 0 };
document.addEventListener('DOMContentLoaded', () => { _perf.domReady = performance.now(); });
function _reportPerf() {
  _perf.initDone = performance.now();
  try {
    fetch('/api/ai/perf', {method:'POST',headers:{'Content-Type':'application/json'},body: JSON.stringify({
      dom_start: Math.round(_perf.domStart),
      dom_ready: Math.round(_perf.domReady || 0),
      init_done: Math.round(_perf.initDone),
      load: Math.round(_perf.initDone - _perf.domStart),
    })});
  } catch(e) {}
}
loadPorts();
refreshGlobalStatus();
connectAiSSE();
refreshMcpInfo();
loadRecentList();  // 最近打开列表（SSH/串口/文件 快捷重开）

// 自依赖提醒（每启动一次，直到用户用离线包补装）：缺哪个库 → 哪些功能不可用。
// 后端标记写过后 /api/deps_status 直接 ok——正常机器零打扰。
(async function depsStartupNotice() {
  try {
    const j = await (await fetch('/api/deps_status')).json();
    if (j.ok) return;
    const missing = [...(j.missing_req || []), ...(j.missing_opt || [])];
    if (!missing.length) return;
    const lines = missing.map(m => `  ✕ ${m[0]} —— ${m[1]}不可用`).join('\n');
    const ok = await _ddConfirm('部分功能不可用',
      `检测到缺少运行库：\n${lines}\n\n` +
      `需${(j.missing_req||[]).length ? '必需' : ''}库缺失会导致对应功能无法使用。\n` +
      `有离线包（claude-offline.zip）？点「确定」选择离线包补装（含工具依赖）；\n` +
      `点「取消」本次跳过（下次启动仍会提醒）。`);
    if (ok) openClaudeSetup();
  } catch(_) {}
})();

if (typeof refreshClaudePanel === 'function') refreshClaudePanel();
// ↑ 启动即拉一次会话数据：_claudeTitleMap（session_id→备注/aiTitle）建好后
// renderRecentList 才能把「最近」claude 条目显示成备注名——否则启动时 map 为空，
// 全部回退固化 label「Claude · 目录名」，分不清开的是哪个会话（面板可见时的
// 5s 轮询只在面板开着时兜底刷新）
renderCmdPane();  // 命令 tab 是默认激活面板，启动即渲染（否则空面板要切走再切回才刷新）
// v2.2.0：页头版本徽标/页面标题动态取自后端单一源（src/version.py）——
// 以前硬编码在 index.html，改版必漏（用户实锤页头还是 v2.0.0）
fetch('/api/update/state').then(r => r.json()).then(j => {
  if (!j || !j.ok || !j.current) return;
  document.title = '前端控制台 v' + j.current;
  document.querySelectorAll('[data-ver-badge]').forEach(el => {
    el.textContent = 'v' + j.current;
  });
}).catch(() => {});
// ---- v2.27.22 全局链接导航拦截（最后防线，捕获阶段）----
// WebView 就地导航一旦发生，整个工具被错误页替换且无返回入口（用户实锤：
// 消息流里 linkify 出的 http://proxy.py 一点就 ERR_NAME_NOT_RESOLVED 占满
// 窗口）。无论链接来自哪个模块的渲染，document 捕获阶段一律拦截：
// http(s) → 后端 /api/open_url 调系统默认浏览器；其余 → 只吞点击。
document.addEventListener('click', (e) => {
  const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
  if (!a) return;
  const href = a.getAttribute('href') || '';
  e.preventDefault();
  e.stopPropagation();
  if (/^https?:/i.test(href)) {
    fetch('/api/open_url', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: href})}).catch(() => {});
  }
}, true);
$('btnNewFile').onclick = (e) => newFileMenuShow(e.currentTarget);  // v2.27「新建文件」下拉：笔记/.txt/.md/自定义后缀（原一键新建笔记）
// v2.1.0：启动静默检查更新（配置过升级地址才查；失败/无更新零打扰——
// 发布机不开机是常态）。有新版只 banner 提示，升级动作进设置页确认。
setTimeout(() => {
  fetch('/api/update/state').then(r => r.json()).then(st => {
    if (!st.ok || !st.url) return;
    return fetch('/api/update/check', {method: 'POST'}).then(r => r.json());
  }).then(j => {
    if (j && j.has_update)
      showBanner(`✨ 发现新版本 v${j.latest}——设置 → 关于与升级，立即升级`, 8000);
  }).catch(() => {});
}, 8000);
$('btnDiff').onclick = openDiffPicker;  // 文件对比（原生选两份 → DiffEditor tab）
$('btnBitCalc').onclick = buildBitCalcTab;  // 程序员计算器（寄存器位编辑+位运算+表达式）
$('btnFiles').onclick = showFilesModal;  // 文件列表弹窗（打开已有文件）
$('btnClaude').onclick = claudeButtonAction;  // Claude 入口：按设置分派——默认界面化 harness tab（claude-harness.js），设置可切回 CLI 终端
// v2.27：Claude 按钮 hover 显示实时 CLI 版本（用户要求）——后端真跑
// claude --version（60s 缓存），拿到就替换 index.html 里的静态描述
fetch('/api/claude/version').then(r => r.json()).then(j => {
  // claude --version 原文是「2.1.267 (Claude Code)」——只取版本号，
  // 避免和按钮文案拼成「Claude Code 2.1.267 (Claude Code)」的重复。
  // v2.27.1：用户定调只留版本，去掉「（真实 CLI，xterm 保真）」尾巴
  if (j && j.ok && j.version) {
    const v = (j.version.match(/\d+\.\d+\.\d+(?:\.\d+)?/) || [j.version.trim()])[0];
    $('btnClaude').title = `Claude Code v${v}`;
  }
}).catch(() => {});
// Claude 代理面板（原 D:\AI\proxy 独立工具合入：重试代理+headroom 压缩+额度监控）
// 帮助已挪设置面板最底部分区（settings.js _stRenderHelpPane）
// Proxy 顶部按钮已移入 Claude 对话页输入卡上方（hg-proxy-btn，带运行状态）；
// buildProxyTab 由 claude-harness.js 的事件委托触发，此处不再绑定。
// ---- 关闭到托盘首次提示：后端隐藏窗口前调 window._trayNotice() ----
// 暗色模态框（铁律②不用原生弹窗），带「下次不再显示」勾选（写 config tray_prompt_shown）。
// 注意：窗口即将 hide，弹窗在隐藏前一瞬展示——唤出时仍在（非阻塞展示，用户回来看得见）。
window._trayNotice = async () => {
  let m = $('trayNoticeModal');
  if (!m) {
    m = document.createElement('div');
    m.className = 'modal';
    m.id = 'trayNoticeModal';
    m.innerHTML = `
      <div class="box" style="max-width:400px;">
        <div class="head"><strong>最小化到托盘</strong>
          <div class="head-actions"><button class="btn ghost icon-btn" id="tnClose">✕</button></div></div>
        <div style="padding:16px 20px;font-size:12px;line-height:1.7;color:var(--fg);">
          点「知道了」后程序将最小化到系统托盘（不会退出——终端连接 / TFTP / Claude 会话都保持）。
          <br>单击托盘区的 <img src="/ico/app.png" alt="logo" style="width:14px;height:14px;vertical-align:-2px;"> <b>图标</b> 可重新打开窗口，右键托盘图标可彻底退出。
        </div>
        <label style="display:flex;align-items:center;gap:8px;padding:0 20px 4px;cursor:pointer;font-size:12px;color:var(--muted);">
          <input type="checkbox" id="tnDontShow"> 下次不再显示此提示（直接最小化）
        </label>
        <div style="display:flex;gap:10px;justify-content:flex-end;padding:10px 20px 16px;">
          <button class="btn primary" id="tnOk">知道了，最小化</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    // ✕ 也走确认链（只关弹窗不隐藏会让用户以为取消了最小化，窗口关不掉）
    m.querySelector('#tnClose').onclick = () => m.querySelector('#tnOk').onclick();
    m.querySelector('#tnOk').onclick = async () => {
      m.classList.remove('show');
      if (m.querySelector('#tnDontShow').checked) {
        try { await fetch('/api/theme', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({tray_prompt_shown: true})}); } catch(_) {}
      }
      try { await pywebview.api.tray_confirm_hide(); } catch(_) {}
    };
  }
  m.classList.add('show');
};

_reportPerf();  // 初始化完成，上报计时
// 轮询降载：连接增删时 refreshSidebar/refreshGlobalStatus 已被事件调用处触发，
// 周期轮询只作兜底，全部放宽（3s→15s / 5s→30s），减少常态 HTTP + 重排叠加（输入卡顿 Contributor）
setInterval(refreshGlobalStatus, 15000);
setInterval(refreshMcpInfo, 30000);  // MCP 后端地址/工具/最近调用（已并入 Claude 面板子 sheet，仍独立降载轮询）
setInterval(() => { if (activePortId) refreshSidebar(); }, 30000);
setInterval(() => {
  // 感知面板可见时刷新分析（用户停在分析标签）
  const activePane = document.querySelector('.panel-tab.active');
  if (activePane && activePane.dataset.pane === 'analyze') renderAnalyze();
  // Claude 面板可见时刷新（运行中/历史会话/技能 + MCP 子 sheet，照 analyze 模式降载）
  if (activePane && activePane.dataset.pane === 'claude') { refreshClaudePanel(); refreshMcpInfo(); }
}, 5000);
