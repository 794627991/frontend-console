// ============================================================
// 内置截图标注 v2.3.12（工具级，不绑 Claude）：
// vendor js-web-screen-shot（MIT）主窗内嵌形态 + DPI 子进程抓屏。
// 确认后：复制剪贴板（必有）+ Claude 对话在场时顺带挂附件（harnessAdd
// FilesByPath 不存在则自然跳过）。两条入口：
//   📷 按钮（claude-harness.js 绑定）→ harnessSnipStart(false)：不切窗口，
//     canvas 等比适配视口（零闪烁零变形）
//   全局热键（后端 RegisterHotKey → SSE snip_hotkey → sense.js）→
//     harnessSnipStart(true)：主窗切全屏，视口=屏幕=底图尺寸，1:1 原生分辨率
// ============================================================
(function () {
  'use strict';
  window.harnessSnipStart = async function (fs) {
    let j;
    try { j = await (await fetch('/api/snip/grab', {method: 'POST'})).json(); }
    catch (e) { showBanner('抓屏失败：' + e, 3000, true); return; }
    if (!j.ok) { showBanner('抓屏失败（子进程未产出截图）', 3000, true); return; }
    if (typeof window.screenShotPlugin !== 'function') { showBanner('截图组件未加载', 3000, true); return; }
    if (window.__snip && window.__snip.destroyComponents) {
      try { window.__snip.destroyComponents(); } catch (_) {}
      window.__snip = null;
    }
    if (fs) {
      try {
        await fetch('/api/window/fullscreen', {method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'enter'})});
      } catch (_) {}
      await new Promise(r => setTimeout(r, 350));   // 等全屏切换布局完成再量视口
    }
    // 防变形：canvasWidth/Height = 底图等比适配视口（无头实测导出与拖框
    // 同尺寸同比例 = 零变形）；全屏路径 k=1 即原生 1:1。
    let iw = 1920, ih = 1080;
    const imgURL = '/api/snip/img?v=' + Date.now();
    try {
      const probe = await new Promise((res) => {
        const im = new Image();
        im.onload = () => res(im); im.onerror = () => res(null);
        im.src = imgURL;
      });
      if (probe) { iw = probe.naturalWidth || iw; ih = probe.naturalHeight || ih; }
    } catch (_) {}
    const vw = document.documentElement.clientWidth || 1280;
    const vh = document.documentElement.clientHeight || 800;
    const k = Math.min(vw / iw, vh / ih);
    const cw = Math.max(1, Math.round(iw * k)), ch = Math.max(1, Math.round(ih * k));
    // 等比后 canvas 可能小于视口（宽屏图在窄窗）：露缝区加临时黑罩兜底视觉
    const veil = document.createElement('div');
    veil.style.cssText = 'position:fixed;inset:0;background:#000;z-index:99998';
    document.body.appendChild(veil);
    const _snipExit = () => {
      try { veil.remove(); } catch (_) {}
      if (fs) {
        try {
          fetch('/api/window/fullscreen', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'exit'})});
        } catch (_) {}
      }
    };
    window.__snip = new screenShotPlugin({
      capture: { source: 'image', imageSrc: imgURL },
      writeBase64: false,        // 剪贴板统一走后端 CF_DIB（更稳）
      showScreenData: true,      // 必开：底图绘制被它把门，默认关=黑屏
      canvasWidth: cw, canvasHeight: ch,
      clickCutFullScreen: true,
      maxUndoNum: 30,
      level: 99999,              // 盖住主 UI 全部层（黑罩 99998 在其下）
      completeCallback: async (info) => {
        const inst = window.__snip;
        window.__snip = null;
        try { inst && inst.destroyComponents && inst.destroyComponents(); } catch (_) {}
        _snipExit();
        try {
          const sv = await (await fetch('/api/snip/save', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data_url: info.base64 })
          })).json();
          if (!sv.ok) { showBanner(sv.err || '截图保存失败', 3000, true); return; }
          // 工具级行为：剪贴板必有（后端已做）；Claude 对话在场才挂附件
          if (typeof window.harnessAddFilesByPath === 'function') {
            window.harnessAddFilesByPath([sv.path]);
          } else {
            showBanner('截图已复制到剪贴板（打开 Claude 对话可自动挂为附件）', 2500);
          }
        } catch (e) { showBanner('截图保存失败：' + e, 3000, true); }
      },
      closeCallback: () => {
        const inst = window.__snip;
        window.__snip = null;
        try { inst && inst.destroyComponents && inst.destroyComponents(); } catch (_) {}
        _snipExit();
      }
    });
  };
})();
