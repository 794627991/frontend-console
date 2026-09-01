// ============================================================
// 全局状态
// ============================================================
const $ = id => document.getElementById(id);
const banner = $('banner');
const portList = $('portList');
const tabs = $('tabs');
const termArea = $('termArea');

let connections = {};   // port_id -> conn（含 term/fit/search/xtermWrap/sse 等）
let activePortId = null;
let aiSse = null;

// banner 显示/消失会改变 .main 高度 → xterm 容器尺寸变化，但 xterm 不自带
// ResizeObserver，fit 不会自动跑。banner 消失后终端下方必现 ~2 行空白
//（rows 还是按矮容器算的），故 banner 每次 class 变化后统一重 fit 所有终端。
function refitAllTerms() {
  requestAnimationFrame(() => {
    for (const id in connections) {
      const c = connections[id];
      if (c && c.term && c.fit && c.wrap.style.display !== 'none') {
        try { c.fit.fit(); } catch(e){}
        // rows 变化后视口相对位置改变，跟随模式补一次贴底
        if (c.autoScroll && !c.inScreen) { try { c.term.scrollToBottom(); } catch(e){} }
      }
    }
  });
}
function showBanner(msg, ms=4000, isErr=false) {
  banner.textContent = msg;
  banner.className = 'banner show' + (isErr ? ' err' : '');
  refitAllTerms();
  if (ms) setTimeout(()=>{ if (banner.textContent === msg) { banner.className = 'banner'; refitAllTerms(); } }, ms);
}
function fmtTs(ms) {
  const d = new Date(ms);
  return d.toLocaleTimeString('zh-CN', {hour12:false}) + '.' + String(ms % 1000).padStart(3,'0');
}
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
// 连接排序：串口[0] < SSH[1] < 日志[2]，同类内按自然序
function sortKeyFn(pid) {
  const m = /^COM(\d+)$/i.exec(pid);
  if (m) return [0, parseInt(m[1], 10)];  // 串口：COM 号数字序
  if (pid.startsWith('log:')) return [2, pid];  // 日志：字典序
  return [1, pid];  // SSH：字典序
}

// ============================================================
// 关键字高亮（error/warning/info 等）
// v0.3.0：改用 xterm decoration 实现（见下方 highlightNewKw），
// 旧的 DOM textNode 高亮函数 highlightKeywords 已废弃移除。
// ============================================================
// （KW_RULES / KW_COLOR 已移至下方 xterm decoration 区块统一定义）

// ============================================================
// 终端标签页 & 输出区管理
// ============================================================
// 注：实际终端元素由 buildTerminal() 创建，此处不再保留死代码。

// 重新设计：每个连接有自己的 xterm 终端容器
