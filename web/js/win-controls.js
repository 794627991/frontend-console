// a59x 自绘窗控（zcode DesktopWindowControls 复刻）+ 顶栏拖拽托管。
// 原生标题栏已由后端摘除（main.py _strip_window_caption）：顶栏即窗顶。
// 拖拽 = pywebview 官方 move 机制（HTCAPTION 被 WebView2/Chromium 鼠标
// 捕获吞掉，v1 实锤；easy_drag 同款）：mousemove 逐帧
// window.pywebview._jsApiCallback('pywebviewMoveWindow', [x,y], 'move')
// （util.py:276 特例 → window.move）。双击最大化手动 toggle_max。
// 状态回推：后端 maximized/restored 事件 → window._hgWinState({max,overhang})；
// 启动时再 GET /api/window/state 拉初态兜底（zcode GetDesktopWindowChromeState
// 同构——冷启最大化时事件早于页面就绪，推不住）。
// 模块化一期（js-modularization 分支）：本文件已转 ES module
// （index.html type="module"）——IIFE 壳已剥（模块自身隔离），缩进保持
// 原样使 diff 最小。执行时机由「解析到 :668 处」变为「解析完成后」（defer
// 语义），对本文件只会更稳（DOM 必然就绪）；对外表面 window._hgWinState
// 挂载不变，Python 推送（main.py:2534/2554）不受影响。
'use strict';

  // Electron 壳形态：窗控三钮走 fcShell IPC（preload contextBridge），
  // 拖拽/双击最大化交给原生 -webkit-app-region 区（body.hg-shell 样式钩子，
  // 见 style.css），窗态由壳 maximize/unmaximize 事件推送。旧 pywebview 链
  // （_post 窗控路由/JS 拖拽桥/背景上报/窗态轮询）仅在非壳形态运行。
  // 形态判定以 preload 桥为准（window.fcShell）——__HG_HEADLESS__ 只是后端
  // 注入旗标，二者可能不一致（壳连到非 headless 后端/旧页缓存时，按旗标
  // 会把窗控绑到不存在的 pywebview 路由 = 三钮全死）
  var fcShell = window.fcShell || null;
  var _HG_HEADLESS = !!fcShell;
  if (_HG_HEADLESS) document.body.classList.add('hg-shell');

  // 窗控是 fire-and-forget：窗口本体即反馈，失败静默——apiPost 的义务化
  // banner（util.js v3.5.109）在这里只会刷屏（teardown 期拖拽失败弹红条
  // 纯噪音），有意偏离统一包装。
  function _post(path, wantJson) {
    try {
      var p = fetch(path, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(function (r) { return (wantJson && r.ok) ? r.json() : null; })
        .catch(function () { return null; });
      return p;
    } catch (_) { return Promise.resolve(null); }
  }

  function _apply(max, overhang) {
    var btn = document.getElementById('wcMax');
    if (btn) {
      btn.dataset.max = max ? 'true' : 'false';
      btn.title = max ? '向下还原' : '最大化';
      btn.setAttribute('aria-label', btn.title);
    }
    document.body.classList.toggle('is-max', !!max);
    // padding 补偿独立类：max 或 snap 等越界态（over>0）都套；MaximizedBounds
    // 钉 workarea 后 max 态 over 恒 0（补偿空转作保险）
    // 前端合理性钳制（双保险第二道，2026-11-18 用户实锤）：正常越界补偿
    // 只有几个 px（最大化边框）——超过 100px 必是异常值（最小化 rect
    // -32000 求差的 25000px 会把全部内容推出屏幕外只剩 body 背景）
    var ov = (typeof overhang === 'number' && overhang > 0 && overhang <= 100) ? overhang : 0;
    document.body.classList.toggle('hg-overhang', ov > 0);
    document.body.style.setProperty('--wv-overhang', ov + 'px');
  }

  // 状态回推入口（main.py maximized/restored 事件 evaluate_js 调）
  window._hgWinState = function (st) {
    _apply(st && st.max, st && st.overhang);
  };

  function init() {
    var bMin = document.getElementById('wcMin');
    var bMax = document.getElementById('wcMax');
    var bClose = document.getElementById('wcClose');
    if (!bMin || !bMax || !bClose) return;

    if (fcShell) {
      // 壳形态：三钮走 IPC。终态不猜——max 的字形/样式由 onState 推回驱动
      bMin.addEventListener('click', function () { fcShell.winCtl('min'); });
      bMax.addEventListener('click', function () { fcShell.winCtl('max'); });
      // close 语义同旧链（close_to_tray 默认驻托盘，壳 close 事件分流）
      bClose.addEventListener('click', function () { fcShell.winCtl('close'); });
    } else {
      bMin.addEventListener('click', function () { _post('/api/window/minimize'); });
      bMax.addEventListener('click', function () {
        // toggle 返回终态，立即切字形（事件回推随后同值到达，幂等）
        _post('/api/window/toggle_max', true).then(function (j) {
          if (j && j.ok) _apply(j.max, j.overhang);
        });
      });
      // 与原生 ✕ 同语义（close_to_tray 默认驻托盘，后端 destroy 走 closing 链）
      bClose.addEventListener('click', function () { _post('/api/window/close'); });
    }
    // 顶栏 = 拖拽区（zcode 的整条 [app-region:drag] 等位）。壳形态整段跳过
    // ——原生 -webkit-app-region 区（body.hg-shell 样式）自带拖拽与双击
    // 最大化（Windows NCLBUTTONDBLCLK 语义），JS 桥只在 pywebview 形态需要。
    // v2 根因修正（用户实锤「窗口状态无法拖动」）：HTCAPTION 方案在
    // WebView2 里被 Chromium 的鼠标捕获吞掉（pywebview 自己的 easy_drag
    // 都不走它）——改用 pywebview 官方 move 机制：mousemove 逐帧调
    // window.pywebview._jsApiCallback('pywebviewMoveWindow', [x,y], 'move')
    // （util.py:276 特例 → window.move，GUI 线程 SetWindowPos，DPI 内部
    // 处理）。Chromium 持有捕获恰好保证 mousemove 持续送达页面。
    // screenX-clientX 自校正公式逐字抄 customize.js onMouseMove。
    // 最大化态不拖（无题窗拖不还原，Electron 同款约定；还原用 ❐/Win+↓）。
    // 双击最大化 HTCAPTION 免费不了了 → 手动 dblclick。
    var bar = fcShell ? null : document.querySelector('.topbar');
    if (bar) {
      var SKIP = 'button,input,textarea,select,a,[contenteditable],[data-no-drag]';
      var dragOn = false;
      var ix = 0, iy = 0, moved2 = 0, skipDbl = false;
      function onMove(ev) {
        moved2 += Math.abs(ev.movementX || 0) + Math.abs(ev.movementY || 0);
        try {
          window.pywebview._jsApiCallback('pywebviewMoveWindow',
            [ev.screenX - ix, ev.screenY - iy], 'move');
        } catch (_) {}
      }
      function onUp() {
        dragOn = false;
        // 审计 P3：两击间 1-2px 抖动会先挪窗再触发 dblclick（原生 HTCAPTION
        // 超 SM_CXDOUBLECLK 会取消双击，DOM dblclick 照发）——位移超 4px 的
        // 「拖拽」不认作双击，下一拍忽略一次 dblclick
        if (moved2 > 4) {
          skipDbl = true;
          setTimeout(function () { skipDbl = false; }, 350);
        }
        moved2 = 0;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      }
      bar.addEventListener('mousedown', function (e) {
        if (e.button !== 0 || dragOn) return;
        if (document.body.classList.contains('is-max')) return;
        var t = e.target;
        if (t && t.closest && t.closest(SKIP)) return;
        dragOn = true;
        ix = e.clientX;
        iy = e.clientY;
        moved2 = 0;
        e.preventDefault();
        e.stopPropagation();
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      });
      bar.addEventListener('dblclick', function (e) {
        if (skipDbl) return;
        var t = e.target;
        if (t && t.closest && t.closest(SKIP)) return;
        // a59x 定调（用户实测）：双击顶栏双向 toggle——最大化态双击还原
        _post('/api/window/toggle_max', true).then(function (j) {
          if (j && j.ok) _apply(j.max, j.overhang);
        });
      });
    }

    // 窗缘露出的 Form 区域底色跟随主题（后端 Padding 让 WebView2 缩进 resize
    // 带，露出的 Form.BackColor 用页面 body 同色 → 视觉无缝；NCCALCSIZE 清
    // 非客户区后亮暗主题都不露黑边）
    var _lastBg = '';
    function _syncBg() {
      if (_HG_HEADLESS) return;
      try {
        // 取侧栏渲染色（--bg-panel，与顶栏/侧栏同色）——边缘带贴着顶栏/侧栏，
        // 用它们同色才无缝；body 底色（--bg-deep）比面板色深会显细框
        var el = document.querySelector('.sidebar') || document.body;
        var c = getComputedStyle(el).backgroundColor;
        // a669（另一会话排查报告变体 A）：首拍可能在样式还没算好时执行，
        // 此时 compute 结果是 rgba(0,0,0,0)（透明）。后端正则只取前三个数，
        // 会把它当成纯黑写进 Form.BackColor → 边缘带变黑框；而下面的同色
        // 去抖会把透明色缓存住，之后同值不再上报。透明/空一律跳过，等
        // MutationObserver 或下次 resize 再报真实颜色。
        if (!c || c === 'transparent') return;
        var m = /rgba?\(([^)]*)\)/.exec(c);
        if (m) {
          var parts = m[1].split(',');
          if (parts.length >= 4 && parseFloat(parts[3]) === 0) return;  // alpha=0
        }
        if (c === _lastBg) return;   // focus/resize 风暴去抖：同色不重复 POST
        _lastBg = c;
        fetch('/api/window/bg', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ color: c }) }).catch(function () {});
      } catch (_) {}
    }
    // a669：首拍若因透明被跳过，_syncBg 要自己再试——只靠主题 MutationObserver
    // 可能永远等不到（主题没变），边缘带就停在默认色。
    _syncBg();
    (function _bgRetry(n) {
      if (n > 10 || _lastBg) return;
      setTimeout(function () { _syncBg(); _bgRetry(n + 1); }, 200);
    })(0);
    try {
      new MutationObserver(_syncBg).observe(document.documentElement,
        { attributes: true, attributeFilter: ['data-theme'] });
    } catch (_) {}
    // 最小化恢复等窗体事件后重刷边缘色（用户实锤：恢复后带变色——
    // 主题色上报一次后不再更新，窗体重绘时用旧色）
    try {
      window.addEventListener('resize', function () { setTimeout(_syncBg, 120); });
      window.addEventListener('focus', function () { _syncBg(); _pullState(); });
    } catch (_) {}

    // 窗态拉取（后端 resized/moved 推送已摘除——py-spy 实锤 evaluate_js 卡死
    // 堆积）：前端 resize 防抖拉 /api/window/state，snap/移动等无事件场景兜底
    var _pullT = null;
    function _pullState() {
      if (_HG_HEADLESS) return;
      try {
        fetch('/api/window/state').then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) { if (j && j.ok) _apply(j.max, j.overhang); })
          .catch(function () {});
      } catch (_) {}
    }
    try {
      window.addEventListener('resize', function () {
        if (_pullT) clearTimeout(_pullT);
        _pullT = setTimeout(_pullState, 300);
      });
    } catch (_) {}

    // 边缘热区拖拽 resize（inset=0 白框终局方案的命中通道）：mousedown 报
    // 方向+起点，mousemove 节流报绝对坐标（后端按起点 bounds+delta 幂等
    // SetWindowPos，丢帧无累积误差），mouseup 收口。fire-and-forget 静默。
    var _rsLast = 0;
    document.querySelectorAll('.edge-hot').forEach(function (el) {
      el.addEventListener('mousedown', function (e) {
        if (e.button !== 0) return;
        if (document.body.classList.contains('is-max')) return;
        e.preventDefault();
        e.stopPropagation();
        var edge = el.dataset.edge;
        fetch('/api/window/resize_begin', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ edge: edge, x: e.screenX, y: e.screenY }) })
          .catch(function () {});
        var onMove = function (ev) {
          var now = Date.now();
          if (now - _rsLast < 16) return;   // ~60fps 节流
          _rsLast = now;
          fetch('/api/window/resize_move', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x: ev.screenX, y: ev.screenY }) })
            .catch(function () {});
        };
        var onUp = function () {
          window.removeEventListener('mousemove', onMove);
          window.removeEventListener('mouseup', onUp);
          fetch('/api/window/resize_end', { method: 'POST',
            headers: { 'Content-Type': 'application/json' }, body: '{}' })
            .catch(function () {});
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
      });
    });

    // 初态兜底（冷启直接最大化：shown 前的 maximized 事件推不到未加载的页面）
    if (fcShell) {
      // 壳形态：初态 IPC 拉 + 事件订阅（无轮询、无 overhang 概念）
      try {
        fcShell.onState(function (st) { _apply(st && st.max, 0); });
        fcShell.getState().then(function (st) { if (st) _apply(st.max, 0); })
          .catch(function () {});
      } catch (_) {}
    } else {
      try {
        fetch('/api/window/state').then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) { if (j && j.ok) _apply(j.max, j.overhang); })
          .catch(function () {});
      } catch (_) {}
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
