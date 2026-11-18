// 客户端错误黑匣子（a654）：error / unhandledrejection → 后端内存日志。
//
// 设计（用户定调「不落盘，别浪费磁盘 IO 和寿命」）：
//   - 只发到 /api/clientlog，后端写入 backend_log 的**内存环形缓冲**
//     （src/backend_log.py deque，进程退出即失，不写盘）。
//   - 同签名（type+消息+文件+行）去重 60s；批量 2s 防抖 / 满 20 条即发。
//   - 只采 message / stack 首段 / 文件行号 / 版本 / 页面路径——不碰页面
//     内容、输入、DOM。
//   - 自身任何异常静默（绝不能因为黑匣子把页面搞坏）。
(function () {
  'use strict';
  if (window.__clientLogInit) return;
  window.__clientLogInit = true;

  var MAX_BATCH = 20;
  var DEDUP_MS = 60000;
  var buf = [];
  var lastSig = {};
  var timer = 0;
  var inFlight = 0;

  function sig(rec) {
    return (rec.t || '') + '|' + String(rec.m || '').slice(0, 120) + '|' +
      (rec.f || '') + ':' + (rec.l || 0);
  }

  function flush() {
    if (timer) { clearTimeout(timer); timer = 0; }
    if (!buf.length) return;
    if (inFlight >= 2) return;          // 后端不可用时别无限排队
    var items = buf.slice(0, MAX_BATCH);
    buf = buf.slice(MAX_BATCH);
    inFlight++;
    try {
      fetch('/api/clientlog', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        keepalive: true,
        body: JSON.stringify({
          ver: window._HG_VER || '',
          url: String(location.pathname || '').slice(0, 120),
          sid: (window._HG && window._HG.sid) || '',
          errors: items
        })
      }).then(function () { inFlight--; })
        .catch(function () { inFlight--; });
    } catch (e) { inFlight--; }
    if (buf.length) schedule();
  }

  function schedule() {
    if (timer) return;
    timer = setTimeout(flush, 2000);
  }

  function push(rec) {
    try {
      var s = sig(rec);
      var now = Date.now();
      if (lastSig[s] && now - lastSig[s] < DEDUP_MS) return;
      lastSig[s] = now;
      if (Object.keys(lastSig).length > 200) {   // 防签名表无界增长
        lastSig = {};
        lastSig[s] = now;
      }
      rec.ts = now;
      buf.push(rec);
      if (buf.length >= MAX_BATCH) flush();
      else schedule();
    } catch (e) {}
  }

  window.addEventListener('error', function (e) {
    if (!e) return;
    push({
      t: 'error',
      m: String((e && e.message) || ''),
      f: String((e && e.filename) || ''),
      l: (e && e.lineno) || 0,
      stack: String((e && e.error && e.error.stack) || '').slice(0, 2000)
    });
  }, true);

  window.addEventListener('unhandledrejection', function (e) {
    var r = e && e.reason;
    push({
      t: 'rejection',
      m: String((r && r.message) || r || ''),
      stack: String((r && r.stack) || '').slice(0, 2000)
    });
  });

  // 排障直调：window.__clientLogProbe('msg')
  window.__clientLogProbe = function (m) {
    push({ t: 'probe', m: String(m || 'probe') });
    flush();
  };
})();
