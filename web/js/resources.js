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
    if (!miss.length) { if (bar) bar.remove(); return; }
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
      '<div style="padding:16px 20px;display:flex;flex-direction:column;gap:12px;">' +
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
      '<button class="btn primary" data-res-go>📂 选择资源包安装</button>' +
      '</div></div>';
    document.body.appendChild(m);
    var close = function () { m.remove(); };
    m.querySelector('[data-res-close]').onclick = close;
    m.addEventListener('click', function (e) { if (e.target === m) close(); });
    m.querySelector('[data-res-refresh]').onclick = function () {
      renderList(m, null);
      resRefresh().then(function (st) { renderList(m, st); });
    };
    m.querySelector('[data-res-path]').onclick = function () {
      var p = window.prompt('资源包完整路径（*.fcpk）：', '');
      if (p) startInstall(m, p.trim());
    };
    m.querySelector('[data-res-go]').onclick = function () {
      _resPickFile().then(function (p) {
        if (!p) {
          var manual = window.prompt('未取到文件选择器。请粘贴资源包完整路径：', '');
          if (!manual) return;
          p = manual.trim();
        }
        startInstall(m, p);
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

  function startInstall(root, path) {
    var logEl = root.querySelector('[data-res-log]');
    var errEl = root.querySelector('[data-res-err]');
    var go = root.querySelector('[data-res-go]');
    var manual = root.querySelector('[data-res-path]');
    logEl.style.display = '';
    logEl.innerHTML = '';
    errEl.style.display = 'none';
    go.disabled = manual.disabled = true;
    _resFetch('/api/resources/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path })
    }).then(function (j) {
      if (!j.ok) {
        go.disabled = manual.disabled = false;
        errEl.style.display = '';
        errEl.textContent = j.err || '启动失败';
        return;
      }
      if (_resPollTimer) clearInterval(_resPollTimer);
      _resPollTimer = setInterval(function () {
        _resFetch('/api/resources/poll').then(function (s) {
          logEl.innerHTML = (s.log || []).map(function (l) {
            return '<div>' + _resEsc(l.msg) + '</div>';
          }).join('');
          logEl.scrollTop = logEl.scrollHeight;
          if (!s.done) return;
          clearInterval(_resPollTimer); _resPollTimer = null;
          go.disabled = manual.disabled = false;
          if (s.ok_done) {
            if (typeof notifyPop === 'function') notifyPop('资源包安装完成', 3000);
            resRefresh().then(function (st) { renderList(root, st); });
          } else {
            errEl.style.display = '';
            errEl.textContent = s.err || '安装失败';
          }
        });
      }, 700);
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

  window.ResPanel = { open: resOpenPanel, refresh: resRefresh };
})();
