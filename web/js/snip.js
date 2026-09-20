// ============================================================
// 内置截图 v2.3.12 最终形态（用户定调：截图就是截图——不缩在工具窗口里）：
// 📷 按钮/全局热键 → POST /api/snip/start → 独立 DPI 子进程全屏窗
// （=物理屏幕，vendor js-web-screen-shot 框选/标注，底图 1:1 原生分辨率）
// → 完成 → 主进程收图（uploads+剪贴板）→ SSE snip_done → 挂附件。
// 工具窗口只当触发器，不参与显示。
// ============================================================
(function () {
  'use strict';
  window.harnessSnipStart = async function () {
    try {
      const j = await (await fetch('/api/snip/start', {method: 'POST'})).json();
      if (!j.ok) showBanner(j.info || '截图窗启动失败', 3000, true);
    } catch (e) { showBanner('截图窗启动失败：' + e, 3000, true); }
  };
})();
