// 41-resources.js —— 离线资源状态与安装（v4.1，用户拍板）
//
// 分工：
//   硬资源（WebView2 / .NET）缺失时界面根本起不来，由启动闸门
//   （src/res_boot.py）用 Win32 原生对话框处理，与前端无关。
//   软资源（Node/Git/claude/pydeps）缺失只影响相关功能，不锁死工具——
//   这里负责在界面顶部挂一条常驻红条 + 一个安装面板。
//
// 「常驻」是刻意的：不用 showBanner（3 秒淡出），用户可以点「忽略」，
// 忽略后写 config，不再打扰，但设置里仍可查看。

(function () {
  'use strict';

  var _resState = null;      // 最近一次 /api/resources/status
  var _resPollTimer = null;
  var _resBarId = 'resBar';

  function _resEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function _resFetch(url, opt) {
    return fetch(url, opt).then(function (r) { return r.json(); });
  }

  // ---- 状态 ----

  function resRefresh() {
    return _resFetch('/api/resources/status').then(function (j) {
      // C7（全审）：接口返回的 ok 是 not hard_missing——早前 `if (!j.ok) return`
      // 会让「硬资源缺失」这个最该提示的场景反而不画条（旁路启动时用户看到
      // 空页面毫无线索）。只要 items 在就画，按 hard 区分文案。
      if (!j || !j.items) return j;
      _resState = j;
      resPaint();
      return j;
    }).catch(function () { return null; });
  }

  function _resMissing() {
    if (!_resState) return [];
    var ignored = _resState.ignored || [];
    return (_resState.items || []).filter(function (it) {
      return !it.ok && ignored.indexOf(it.kind) < 0;
    });
  }

  // ---- 常驻红条 ----

  function resPaint() {
    var bar = document.getElementById(_resBarId);
    var miss = _resMissing();
    if (!miss.length) {
      if (bar) bar.remove();
      // 对抗审 P2：红条撤了要把让出的顶部空间还回去（36px 白缝）
      document.body.style.paddingTop = '';
      return;
    }
    var hard = miss.filter(function (m) { return m.hard; });
    var names = miss.map(function (m) { return m.name; }).join(' / ');
    var text = (miss.length === 1 ? '缺少 ' : '缺少 ') + names +
      (hard.length ? ' —— 工具无法正常运行' : ' —— 相关功能不可用');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = _resBarId;
      bar.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:9990;' +
        'display:flex;align-items:center;gap:12px;padding:7px 14px;' +
        'background:#8a1f1f;color:#fff;font-size:12.5px;' +
        'box-shadow:0 2px 8px rgba(0,0,0,.35);';
      document.body.appendChild(bar);
      // 让出顶部空间（主容器下移，避免挡住标题栏）
      document.body.style.paddingTop = '36px';
    }
    bar.innerHTML =
      '<span style="flex:1">⚠ ' + _resEsc(text) + '</span>' +
      '<button class="btn sm" data-res-install style="background:#fff;' +
      'color:#8a1f1f;border:none;padding:3px 12px;border-radius:4px;' +
      'cursor:pointer;font-size:12px;">安装资源包</button>' +
      '<button class="btn sm" data-res-ignore style="background:transparent;' +
      'color:#fdd;border:1px solid #fdd;padding:3px 10px;border-radius:4px;' +
      'cursor:pointer;font-size:12px;">忽略</button>';
    bar.querySelector('[data-res-install]').onclick = resOpenPanel;
    bar.querySelector('[data-res-ignore]').onclick = function () {
      var kinds = miss.map(function (m) { return m.kind; });
      _resFetch('/api/resources/ignore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kinds: kinds })
      }).then(function () {
        if (_resState) _resState.ignored = (_resState.ignored || []).concat(kinds);
        resPaint();
      });
    };
  }

  // ---- 安装面板 ----

  function _resPickFile() {
    // 优先用工具的文件选择（原生对话框）；不可用则让用户手填路径
    if (window.pywebview && pywebview.api && pywebview.api.pick_any) {
      return pywebview.api.pick_any().then(function (r) {
        if (!r) return '';
        return (typeof r === 'string') ? r : (r.path || '');
      }).catch(function () { return ''; });
    }
    return Promise.resolve('');
  }

  function resOpenPanel() {
    var id = 'resPanel';
    var old = document.getElementById(id);
    if (old) old.remove();
    var m = document.createElement('div');
    m.id = id;
    m.className = 'modal show';
    m.innerHTML =
      '<div class="box" style="width:620px;">' +
      '<div class="head"><strong>运行环境资源</strong>' +
      '<div class="head-actions"><button class="btn ghost icon-btn" ' +
      'data-res-close>✕</button></div></div>' +
      '<div data-res-body style="padding:16px 20px;display:flex;flex-direction:column;gap:12px;">' +
      '<div data-res-list style="font-size:12px;line-height:1.9;">检测中…</div>' +
      '<div data-res-log class="cs-log" style="display:none;max-height:160px;' +
      'overflow:auto;font-size:11px;"></div>' +
      '<div data-res-err style="color:var(--neon-red);font-size:11px;' +
      'display:none;"></div>' +
      '</div>' +
      '<div class="actions" style="padding:0 20px 16px;display:flex;' +
      'justify-content:flex-end;gap:8px;flex-wrap:wrap;">' +
      '<button class="btn ghost" data-res-refresh>⟳ 重新检测</button>' +
      '<button class="btn ghost" data-res-path>手动输入路径…</button>' +
      '<button class="btn primary" data-res-go><span style="vertical-align:-2.5px">' + ICO16.folderOpen + '</span> 选择资源包安装</button>' +
      '</div></div>';
    document.body.appendChild(m);
    var close = function () { m.remove(); };
    m.querySelector('[data-res-close]').onclick = close;
    m.addEventListener('click', function (e) { if (e.target === m) close(); });
    m.querySelector('[data-res-refresh]').onclick = function () {
      renderList(m, null);
      resRefresh().then(function (st) { renderList(m, st); });
    };
    // 对抗审 P3：window.prompt 在 WebView2 下可能被禁用（file-tree.js:36 /
    // tftp.js:220 自家先例明说不能用）——改内联输入框兜底
    var manualPath = function (cb) {
      var prev = m.querySelector('.res-manual');
      if (prev) { prev.remove(); return; }
      var row = document.createElement('div');
      row.className = 'res-manual';
      row.style.cssText = 'display:flex;gap:8px;margin:8px 0;';
      row.innerHTML = '<input data-res-inp placeholder="资源包完整路径（*.fcpk）" ' +
        'style="flex:1;padding:6px 8px;border:1px solid #ccc;border-radius:4px">' +
        '<button class="btn sm" data-res-ok>安装</button>';
      m.querySelector('[data-res-body]').appendChild(row);
      var inp = row.querySelector('[data-res-inp]');
      inp.focus();
      row.querySelector('[data-res-ok]').onclick = function () {
        var v = (inp.value || '').trim();
        if (v) { row.remove(); cb(v); }
      };
      inp.onkeydown = function (e) {
        if (e.key === 'Enter') { e.preventDefault(); row.querySelector('[data-res-ok]').click(); }
      };
    };
    m.querySelector('[data-res-path]').onclick = function () {
      manualPath(function (p) { startInstall(m, p); });
    };
    m.querySelector('[data-res-go]').onclick = function () {
      _resPickFile().then(function (p) {
        if (p) { startInstall(m, p); return; }
        manualPath(function (v) { startInstall(m, v); });
      });
    };
    renderList(m, _resState);
    resRefresh().then(function (st) { renderList(m, st); });
  }

  function renderList(root, st) {
    var el = root.querySelector('[data-res-list]');
    if (!st) { el.textContent = '检测中…'; return; }
    var rows = (st.items || []).map(function (it) {
      var icon = it.ok ? '<span style="color:var(--accent)">✓</span>'
        : '<span style="color:var(--neon-red)">✗</span>';
      var extra = it.ok
        ? (it.ver ? ' <span style="color:var(--muted)">' + _resEsc(it.ver) + '</span>' : '')
        : ' <span style="color:var(--muted);font-size:11px;">' +
          _resEsc(it.detail || it.fix || '') + '</span>';
      return '<div>' + icon + ' ' + _resEsc(it.name) +
        (it.hard ? ' <u style="font-style:normal;font-size:10px;' +
          'border:1px solid var(--muted);padding:0 3px;border-radius:3px;' +
          'color:var(--muted)">必需</u>' : '') + extra + '</div>';
    }).join('');
    el.innerHTML = rows ||
      '<span style="color:var(--muted)">（无资源清单）</span>';
  }

  // 全应用只该有一个安装任务（后端 _state 单例，第二个 POST 得 409）。
  // 红条面板与设置页共用同一轮询器——opts 里注入各自的 DOM 回调。
  // 回调一律包住：调用方（设置页）在安装中切分区会让它的 DOM 引用失效，
  // 抛出的 TypeError 会中断这一轮 .then，导致 done 结算与 onDone 永不执行、
  // 轮询定时器空转（全审 N2）。这里兜住，保证结算链不被 UI 异常打断。
  function _safe(fn, arg) {
    try { fn(arg); } catch (e) {
      if (window.console) console.warn('res callback:', e);
    }
  }

  function _resRun(opts) {
    var o = opts || {};
    var onLog = o.onLog || function () {};
    var onTick = o.onTick || function () {};
    var onDone = o.onDone || function () {};
    if (_resPollTimer) { clearInterval(_resPollTimer); _resPollTimer = null; }
    return _resFetch('/api/resources/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: o.path, kinds: o.kinds || null, force: !!o.force
      })
    }).then(function (j) {
      if (!j.ok) { _safe(onDone, { ok: false, err: j.err || '启动失败' }); return j; }
      // 后端 log 是累积数组，每轮都全量返回——用游标只投递新增行，
      // 否则日志会一轮比一轮多（N 行被重放 N 次）
      var seen = 0;
      _resPollTimer = setInterval(function () {
        _resFetch('/api/resources/poll').then(function (s) {
          _safe(onTick, s);
          var lg = s.log || [];
          for (; seen < lg.length; seen++) _safe(onLog, lg[seen].msg);
          if (!s.done) return;
          clearInterval(_resPollTimer); _resPollTimer = null;
          // 取消用后端显式字段判定——早前 /取消/.test(s.err) 会把任何
          // 含「取消」二字的真实失败误报成「已取消安装」（全审 N3）
          _safe(onDone, { ok: !!s.ok_done, err: s.err || '', result: s.result,
                          cancelled: !!s.cancelled });
          if (s.ok_done) resRefresh();
        }).catch(function (e) {
          // 轮询本身失败（后端重启等）也要收尾，否则定时器永不停
          clearInterval(_resPollTimer); _resPollTimer = null;
          _safe(onDone, { ok: false, err: '轮询失败：' + e });
        });
      }, 700);
      return j;
    }).catch(function (e) {
      _safe(onDone, { ok: false, err: String(e) });
      return { ok: false, err: String(e) };
    });
  }

  function resCancel() {
    return _resFetch('/api/resources/cancel', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }
    });
  }

  function startInstall(root, path) {
    var logEl = root.querySelector('[data-res-log]');
    var errEl = root.querySelector('[data-res-err]');
    var go = root.querySelector('[data-res-go]');
    var manual = root.querySelector('[data-res-path]');
    logEl.style.display = '';
    logEl.innerHTML = '';
    errEl.style.display = 'none';
    go.disabled = manual.disabled = true;
    _resRun({
      path: path,
      onLog: function (msg) {
        var d = document.createElement('div');
        d.textContent = msg;
        logEl.appendChild(d);
        logEl.scrollTop = logEl.scrollHeight;
      },
      onDone: function (r) {
        go.disabled = manual.disabled = false;
        if (r.ok) {
          if (typeof notifyPop === 'function') notifyPop('资源包安装完成', 3000);
          resRefresh().then(function (st) { renderList(root, st); });
        } else {
          errEl.style.display = '';
          errEl.textContent = r.err || '安装失败';
        }
      }
    });
  }

  // ---- 启动钩子 ----
  // 首屏后延迟 1.2s 再检测（不抢启动性能；探测会起 3 个子进程，已 60s 缓存）
  function boot() {
    setTimeout(function () {
      resRefresh().then(function (st) {
        if (!st) return;
        // 装完后可能恢复——每 3 分钟复查一次（用户装了系统级 Git 也能消红条）
        setInterval(resRefresh, 180000);
      });
    }, 1200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.ResPanel = { open: resOpenPanel, refresh: resRefresh,
                      install: _resRun, cancel: resCancel };
})();
