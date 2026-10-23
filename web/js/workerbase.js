/* Claude 子系统 worker 直连层（进程隔离，v4.0.0 串口卡顿根治）。
 *
 * 背景：harness v4 feed 投影/子代理 watcher/会话 ingest 与串口终端同进程
 * 抢 GIL + pywebview 全 URL 拦截走 UI 线程——Claude 一跑，串口敲键回显
 * 实测冻结 10~20s（trace/串口日志双实锤）。已把 harness 与 HikLink 移驻
 * 独立 worker 进程（src/worker_app.py），本脚本把这两族 API 直连 worker：
 * Claude 后端再忙也烧不到主进程（用户铁律：流畅第一）。
 *
 * 行为：index.html 头部先置 window.__HG_WORKER__（服务端注入 worker 基址；
 * 空串=未分离[CLAUDE_INLINE]或 worker 未就绪→本层完全透明零改动）。
 * 只改写「相对路径」且前缀命中 /api/harness、/api/hiklink 的 fetch 与
 * EventSource；其余请求（串口 send_raw/终端 SSE/静态资源）原样走主进程。
 * 必须在任何业务脚本之前加载（index.html 头部第二个 script）。*/
(function () {
  // P1-4 修复（a116）：基址必须是合法 loopback URL。dev 模式（前端从磁盘
  // 直读）+ 旧后端时，__HG_WORKER__ 残留占位符字面量 '__HG_WBASE__'
  // （非空字符串 → 旧判真），改写后 fetch('<占位符>/api/harness/sessions')
  // 被浏览器解析成 /__HG_WBASE__/api/... → 静态兜底 404，整条 harness 链挂。
  var _W = window.__HG_WORKER__ || '';
  var B = /^https?:\/\/127\.0\.0\.1:\d+$/.test(_W) ? _W : '';
  if (!B) return;                        // 未分离/占位符残留：零开销透明层
  // 能力门（对抗版本错位）：proxy/usage/claude_default 族只在新后端
  // （__HG_WFAM__ 注入 'proxy'）才改写。dev 模式前端从磁盘直读、后端可能
  // 还是旧进程——旧后端不替换此占位符（残留字面量）≠'proxy'，自动退回
  // 只改写 harness/hiklink（与旧后端 worker 实际承载精确对齐，不会 404）
  var FULL = window.__HG_WFAM__ === 'proxy';
  // 整段命名空间直连 worker；/api/claude/* 因与 claude_setup（主进程）共享
  // 前缀，只能精确枚举 claude_default 的端点（与 server.py 的 _CW_CLAUDE_PATHS
  // + profiles 子前缀同清单，两处必须同步改）
  var PRE = ['/api/harness', '/api/hiklink'];
  var EXACT = [];
  if (FULL) {
    PRE = PRE.concat(['/api/proxy', '/api/usage', '/api/claude/profiles']);
    EXACT = ['/api/claude/api_config', '/api/claude/models_probe',
             '/api/claude/settings_open', '/api/claude/provision'];
  }

  function hit(u) {
    if (typeof u !== 'string' || u.charAt(0) !== '/') return false;
    // 对抗审修：EXACT 先剥查询串再比对（'/api/claude/api_config?full=1'
    // 曾漏匹配→退回主进程 307 兜底——功能不坏但白绕一跳，未来加参数即踩中）
    if (EXACT.indexOf(u.split('?')[0]) !== -1) return true;
    for (var i = 0; i < PRE.length; i++) {
      var p = PRE[i];
      if (u === p) return true;
      var head = u.slice(0, p.length + 1);
      if (head === p + '/' || head === p + '?') return true;
    }
    return false;
  }

  var _fetch = window.fetch;
  if (_fetch) {
    window.fetch = function (input, init) {
      try {
        if (hit(input)) input = B + input;                 // fetch(url, ...)
        else if (input && typeof input === 'object' && hit(input.url))
          input = new Request(B + input.url, input);       // fetch(Request, ...)
      } catch (e) { /* 改写失败按原样发，让上层按旧路径报错 */ }
      return _fetch.call(window, input, init);
    };
  }

  var _ES = window.EventSource;
  if (_ES) {
    var HGEventSource = function (url, cfg) {
      return new _ES(hit(url) ? B + url : url, cfg);
    };
    HGEventSource.prototype = _ES.prototype;
    window.EventSource = HGEventSource;
  }
})();
