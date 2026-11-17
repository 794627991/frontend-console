// a59x 自绘窗控（zcode DesktopWindowControls 复刻）+ 顶栏拖拽托管。
// 原生标题栏已由后端摘除（main.py _strip_window_caption）：顶栏即窗顶。
// 拖拽 = pywebview 官方 move 机制（HTCAPTION 被 WebView2/Chromium 鼠标
// 捕获吞掉，v1 实锤；easy_drag 同款）：mousemove 逐帧
// window.pywebview._jsApiCallback('pywebviewMoveWindow', [x,y], 'move')
// （util.py:276 特例 → window.move）。双击最大化手动 toggle_max。
// 状态回推：后端 maximized/restored 事件 → window._hgWinState({max,overhang})；
// 启动时再 GET /api/window/state 拉初态兜底（zcode GetDesktopWindowChromeState
// 同构——冷启最大化时事件早于页面就绪，推不住）。
(function () {
  'use strict';

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

    bMin.addEventListener('click', function () { _post('/api/window/minimize'); });
    bMax.addEventListener('click', function () {
      // toggle 返回终态，立即切字形（事件回推随后同值到达，幂等）
      _post('/api/window/toggle_max', true).then(function (j) {
        if (j && j.ok) _apply(j.max, j.overhang);
      });
    });
    // 与原生 ✕ 同语义（close_to_tray 默认驻托盘，后端 destroy 走 closing 链）
    bClose.addEventListener('click', function () { _post('/api/window/close'); });

    // 顶栏 = 拖拽区（zcode 的整条 [app-region:drag] 等位）。
    // v2 根因修正（用户实锤「窗口状态无法拖动」）：HTCAPTION 方案在
    // WebView2 里被 Chromium 的鼠标捕获吞掉（pywebview 自己的 easy_drag
    // 都不走它）——改用 pywebview 官方 move 机制：mousemove 逐帧调
    // window.pywebview._jsApiCallback('pywebviewMoveWindow', [x,y], 'move')
    // （util.py:276 特例 → window.move，GUI 线程 SetWindowPos，DPI 内部
    // 处理）。Chromium 持有捕获恰好保证 mousemove 持续送达页面。
    // screenX-clientX 自校正公式逐字抄 customize.js onMouseMove。
    // 最大化态不拖（无题窗拖不还原，Electron 同款约定；还原用 ❐/Win+↓）。
    // 双击最大化 HTCAPTION 免费不了了 → 手动 dblclick。
    var bar = document.querySelector('.topbar');
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
      try {
        // 取侧栏渲染色（--bg-panel，与顶栏/侧栏同色）——边缘带贴着顶栏/侧栏，
        // 用它们同色才无缝；body 底色（--bg-deep）比面板色深会显细框
        var el = document.querySelector('.sidebar') || document.body;
        var c = getComputedStyle(el).backgroundColor;
        if (c === _lastBg) return;   // focus/resize 风暴去抖：同色不重复 POST
        _lastBg = c;
        fetch('/api/window/bg', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ color: c }) }).catch(function () {});
      } catch (_) {}
    }
    _syncBg();
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
    try {
      fetch('/api/window/state').then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j && j.ok) _apply(j.max, j.overhang); })
        .catch(function () {});
    } catch (_) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
