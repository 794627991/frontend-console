// ============================================================
// 内置截图标注 v2.3.12（工具级，不绑 Claude）：
// vendor js-web-screen-shot（MIT）主窗内嵌形态 + DPI 子进程抓屏。
// 确认后：复制剪贴板（必有）+ Claude 对话在场时顺带挂附件。
//
// v2.3.12 第三版定案（前两版实锤教训）：
// - 全屏切换必须配「视口就绪轮询」：固定盲等 350ms 有时序竞态，canvas
//   按中间态尺寸建 → 遮罩只盖左上、右下露原界面（用户实锤）。现在
//   enter 后轮询视口尺寸稳定且≈底图尺寸再实例化，遮罩必满。
// - 黑罩不用独立 veil DOM：大 z-index 黑层销毁后 WebView2 偶发不重绘
//   （黑屏残影，用户实锤）。改 html 背景染黑/还原——无新增合成层。
// - Esc/Enter 被 xterm/输入框吃掉不冒泡 → 插件收不到（取消失灵卡黑屏）。
//   capture 阶段先拦（先于一切内部 handler），手动点插件的 close/confirm
//   图标——与插件自身 Esc 处理同款路径（triggerEvent 模拟 click）。
// ============================================================
(function () {
  'use strict';

  function _snipKeys(install) {
    // capture 拦 Escape/Enter：截图态唯一键盘出口，防被主 UI 元素截胡
    if (!install) {
      document.removeEventListener('keydown', window.__snipKeyCap, true);
      window.__snipKeyCap = null;
      return;
    }
    window.__snipKeyCap = (e) => {
      if (e.code !== 'Escape' && e.code !== 'Enter') return;
      e.preventDefault();
      e.stopPropagation();               // 插件 body 冒泡监听也收不到——手动代发
      const sel = e.code === 'Escape' ? '#toolPanel .close' : '#toolPanel .confirm';
      const btn = document.querySelector(sel);
      if (btn) btn.click();              // 与插件 Esc/Enter 内部实现同款（模拟 click）
    };
    document.addEventListener('keydown', window.__snipKeyCap, true);
  }

  function _snipBg(dark) {
    document.documentElement.style.background = dark ? '#000' : '';
  }

  window.harnessSnipStart = async function () {
    let j;
    try { j = await (await fetch('/api/snip/grab', {method: 'POST'})).json(); }
    catch (e) { showBanner('抓屏失败：' + e, 3000, true); return; }
    if (!j.ok) { showBanner('抓屏失败（子进程未产出截图）', 3000, true); return; }
    if (typeof window.screenShotPlugin !== 'function') { showBanner('截图组件未加载', 3000, true); return; }
    if (window.__snip && window.__snip.destroyComponents) {
      try { window.__snip.destroyComponents(); } catch (_) {}
      window.__snip = null;
      _snipBg(false); _snipKeys(false);
    }
    // 底图原生尺寸（导出分辨率的基准）
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
    // 全屏 + 视口就绪轮询：视口=屏幕=底图尺寸 → canvas 1:1 原生分辨率导出
    // （轮询替代固定盲等：尺寸稳定且 ≈ 底图才算就绪，总超时 3s 兜底）
    _snipBg(true);
    try {
      await fetch('/api/window/fullscreen', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'enter'})});
    } catch (_) {}
    const t0 = Date.now();
    while (Date.now() - t0 < 3000) {
      const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
      const ok = vw >= iw * 0.98 && vh >= ih * 0.92;   // 全屏去边框后高度略小可接受
      if (ok && Date.now() - t0 > 250) break;
      await new Promise(r => setTimeout(r, 60));
    }
    const vw = document.documentElement.clientWidth || 1280;
    const vh = document.documentElement.clientHeight || 800;
    const k = Math.min(vw / iw, vh / ih);
    const cw = Math.max(1, Math.round(iw * k)), ch = Math.max(1, Math.round(ih * k));
    const _snipExit = () => {
      try {
        fetch('/api/window/fullscreen', {method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'exit'})});
      } catch (_) {}
      _snipBg(false);
      _snipKeys(false);
    };
    _snipKeys(true);
    window.__snip = new screenShotPlugin({
      capture: { source: 'image', imageSrc: imgURL },
      writeBase64: false,        // 剪贴板统一走后端 CF_DIB（更稳）
      showScreenData: true,      // 必开：底图绘制被它把门，默认关=黑屏
      canvasWidth: cw, canvasHeight: ch,   // 就绪后视口≈底图 → 1:1 原生
      clickCutFullScreen: true,
      maxUndoNum: 30,
      level: 99999,
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
