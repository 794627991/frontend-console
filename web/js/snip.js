// ============================================================
// 内置截图（P4 Electron 覆层形态）：
// 📷 按钮/全局热键 → 后端 DPI 子进程抓屏 → SSE snip_open → Electron 壳
// 建无边框置顶 BrowserWindow（vendor js-web-screen-shot 框选/标注，
// 底图 1:1 原生分辨率）→ 完成 → 主进程收图（uploads+剪贴板）→
// SSE snip_done → 挂附件。工具窗口只当触发器，不参与显示。
// ============================================================
// 模块化一期（js-modularization 分支）：已转 ES module——IIFE 壳已剥。
// 对外表面仅 window.harnessSnipStart（harness/main.js:1800 的 onclick
// 守卫调用，运行时）；showBanner 是 util.js 全局，fetch 回调期解析，
// 模块执行时经典脚本已全部就位。
'use strict';
  window.harnessSnipStart = async function () {
    try {
      const j = await (await fetch('/api/snip/start', {method: 'POST'})).json();
      if (!j.ok) showBanner(j.info || '截图窗启动失败', 3000, true);
      // SSE 可能先到/后到；壳侧对同窗去重，这里直调保证按钮路径不依赖
      // SSE 连接状态。仅壳形态有 openSnip，浏览器直开时静默跳过。
      else if (window.fcShell && typeof window.fcShell.openSnip === 'function') {
        window.fcShell.openSnip();
      }
    } catch (e) { showBanner('截图窗启动失败：' + e, 3000, true); }
  };
