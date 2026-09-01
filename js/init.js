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
_reportPerf();  // 初始化完成，上报计时
// 轮询降载：连接增删时 refreshSidebar/refreshGlobalStatus 已被事件调用处触发，
// 周期轮询只作兜底，全部放宽（3s→15s / 5s→30s），减少常态 HTTP + 重排叠加（输入卡顿 Contributor）
setInterval(refreshGlobalStatus, 15000);
setInterval(refreshMcpInfo, 30000);  // MCP 状态面板：后端地址/工具/最近调用
setInterval(() => { if (activePortId) refreshSidebar(); }, 30000);
setInterval(() => {
  // 感知面板可见时刷新分析（用户停在分析标签）
  const activePane = document.querySelector('.panel-tab.active');
  if (activePane && activePane.dataset.pane === 'analyze') renderAnalyze();
}, 5000);
