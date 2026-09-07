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
if (typeof refreshClaudePanel === 'function') refreshClaudePanel();
// ↑ 启动即拉一次会话数据：_claudeTitleMap（session_id→备注/aiTitle）建好后
// renderRecentList 才能把「最近」claude 条目显示成备注名——否则启动时 map 为空，
// 全部回退固化 label「Claude · 目录名」，分不清开的是哪个会话（面板可见时的
// 5s 轮询只在面板开着时兜底刷新）
renderCmdPane();  // 命令 tab 是默认激活面板，启动即渲染（否则空面板要切走再切回才刷新）
$('btnNewFile').onclick = newEditorFile;  // 新建文本文件（编辑器 tab）
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
  // Claude 面板可见时刷新（运行中/历史会话/技能，照 analyze 模式降载）
  if (activePane && activePane.dataset.pane === 'claude') refreshClaudePanel();
  // MCP 面板可见时刷新（工具/后端 + 最近调用两个子 sheet）
  if (activePane && activePane.dataset.pane === 'mcp') refreshMcpInfo();
}, 5000);
