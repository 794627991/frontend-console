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
$('btnNewFile').onclick = newEditorFile;  // 新建文本文件（编辑器 tab）
$('btnDiff').onclick = openDiffPicker;  // 文件对比（原生选两份 → DiffEditor tab）
$('btnBitCalc').onclick = buildBitCalcTab;  // 程序员计算器（寄存器位编辑+位运算+表达式）
$('btnFiles').onclick = showFilesModal;  // 文件列表弹窗（打开已有文件）
$('btnClaude').onclick = () => connectClaude();  // 内嵌终端启动 Claude Code（ConPTY 真实 CLI）
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
