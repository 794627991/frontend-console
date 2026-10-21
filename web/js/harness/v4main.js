/* v4main —— v4 归一管线主接线器（批E/F；开关灰度：验收后开关拆除）。
 *
 * 接线点（v4On() 时生效，旧管线原样保留）：
 *   sessions.js switchTo  → 清场块后 v4Switch(sid) 全权接管（snapshot 整建
 *                           + delta 增量；不再 openSSE/histFetch/_histRender）
 *   chatctl.js dispatch   → body 带 cmd（uuid）+ store.markPending（2s 投影
 *                           静默自动重订阅恢复——绝不重放/伪造消息行）
 *   subpane 子窗格        → v4SubOpen(el, agentKey)：子会话独立 store（同管线
 *                           delta 直推，替代 _subReplay 轮询全量重建）
 *
 * 开关：?v4 或 localStorage.hg_v4='1'（默认关——灰度实测，批G 验收后常开）。
 */
(function (root) {
  'use strict';

  function v4On() {
    // _HG 是 state.js 的 let 全局（不挂 window）——裸标识符沿作用域链解析
    if (typeof _HG === 'undefined') return false;
    if (_HG.v4 !== undefined) return !!_HG.v4;
    // v4 回退（用户拍板 2026-10-20：实测 UI 问题多，先回旧管线）——默认关，
    // ?v4=1 或 localStorage.hg_v4='1' 显式开启（灰度实测用，验收后再常开）
    var on = /[?&]v4=1(?:&|$)/.test(location.search)
      || root.__HG_V4__ === true
      || (function () { try { return localStorage.getItem('hg_v4') === '1'; }
          catch (e) { return false; } })();
    _HG.v4 = on;
    return on;
  }

  // ---- 主窗 store/render 单例 ----------------------------------------------

  var _cur = null;      // {sid, store, render}

  function v4Switch(sid, keepInput) {
    v4Close();
    if (!sid) {
      // a53（用户实测致命「新建会话点不开了」）：switchTo(null) 的 v4 分流
      // 在此早退，V3 的新建 UI 块（sessions.js:194 清 flow/welcome/标题/
      // 聚焦）全被跳过=点了没反应。新建场景 v4 无 store 可建，把该 UI 块
      // 补齐（函数为跨 script 顶层声明，typeof 守卫沿全局链可达）
      if (typeof _hgFlow !== 'undefined' && _hgFlow) {
        try { _hgFlow.innerHTML = ''; } catch (e) {}
        if (typeof _hgAskDockRestore === 'function') { try { _hgAskDockRestore(''); } catch (e) {} }
        if (typeof showWelcome === 'function') { try { showWelcome(); } catch (e) {} }
      }
      if (typeof _hgTitleEl !== 'undefined' && _hgTitleEl) _hgTitleEl.textContent = '新会话';
      if (typeof _hgCwdEl !== 'undefined' && _hgCwdEl) _hgCwdEl.textContent = '';
      if (typeof renderList === 'function') { try { renderList(); } catch (e) {} }
      if (typeof renderQueue === 'function') { try { renderQueue(); } catch (e) {} }
      if (typeof _hgRailSync === 'function') { try { _hgRailSync(); } catch (e) {} }
      if (typeof _hgInput !== 'undefined' && _hgInput) _hgInput.focus();
      return;
    }
    var flow = (typeof _hgFlow !== 'undefined') ? _hgFlow : null;   // let 全局
    if (!flow) return;
    var store = new root.V4Store(sid, 'main');
    var render = new root.V4Bridge(store, flow, { live: true });
    _cur = { sid: sid, store: store, render: render };
    _HG.v4Cur = _cur;
    store.connect();
    // 兼容旧链路的状态账（部分基元读这些字段）
    _HG.sid = sid;
    // switchTo 公共尾巴（标头/模型/cwd/列表）被 v4 分流短路——此处补齐
    v4PaintHeader(sid, keepInput);
  }

  function v4PaintHeader(sid, keepInput) {
    var meta = null;
    for (var i = 0; i < (_HG.sessions || []).length; i++)
      if (_HG.sessions[i] && _HG.sessions[i].sid === sid) { meta = _HG.sessions[i]; break; }
    var title = (meta && meta.title) || '会话';
    try {
      if (typeof _hgTitleEl !== 'undefined' && _hgTitleEl) _hgTitleEl.textContent = title;
      if (typeof _hgConn !== 'undefined' && _hgConn) {
        _hgConn.meta.label = title;
        _hgConn.meta.cwd = (meta && meta.cwd) || '';
        var lb = _hgConn.tab && _hgConn.tab.querySelector('.label');
        if (lb) lb.textContent = title;
      }
      var sm = (meta && meta.model) || (_HG.models && _HG.models.default) || null;
      if (sm && sm !== _HG.model) {
        _HG.model = sm;
        if (typeof _hgQ !== 'undefined' && _hgQ) {
          var mEl = _hgQ('[data-hg-model]');
          if (mEl) mEl.innerHTML = (typeof esc === 'function' ? esc(sm) : sm) + ' ▾';
        }
      }
      if (typeof _hgCwdEl !== 'undefined' && _hgCwdEl)
        _hgCwdEl.textContent = (meta && meta.cwd) || '';
      // 项目 chip 跟随会话 cwd（对齐 V3 sessions.js:581——切回历史会话恢复
      // 该会话目录；v4 分流短路了冷开路此段，chip 停在默认项目）
      var mcwd = (meta && meta.cwd) || '';
      if (mcwd) {
        _HG.cwd = mcwd;
        if (typeof _hgSaveCwd === 'function') { try { _hgSaveCwd(mcwd); } catch (e) {} }
        if (typeof projChipLabel === 'function') { try { projChipLabel(); } catch (e) {} }
      }
      if (typeof renderList === 'function') renderList();
      if (typeof renderQueue === 'function') renderQueue();
      if (typeof refreshSidebar === 'function') refreshSidebar();
      if (!keepInput && typeof _hgInput !== 'undefined' && _hgInput) _hgInput.focus();
    } catch (e) { /* 头部装饰失败不伤管线 */ }
  }

  function v4Close() {
    if (_cur) {
      try { _cur.render.close(); } catch (e) {}
      try { _cur.store.close(); } catch (e) {}
    }
    _cur = null;
    if (typeof _HG !== 'undefined') _HG.v4Cur = null;
  }

  // ---- 发送对账（overlay：不含文本、不渲染，只喂 watchdog） -----------------

  var _cmdN = 0;
  function v4NewCmd() {
    _cmdN++;
    return 'c' + Date.now().toString(36) + '-' + _cmdN;
  }

  function v4MarkPending(cmdId) {
    if (_cur && _cur.sid === _HG.sid) _cur.store.markPending(cmdId);
  }

  // ---- 子代理窗格（同管线：独立 store 订阅 sub topic） -----------------------

  var _subs = {};       // container → {store, render}

  function v4SubOpen(el, agentKey, opt) {
    opt = opt || {};
    if (!el || !agentKey) return false;
    v4SubClose(el);
    // a64（用户实锤「子代理页开关几次后消息发不出去、后端像挂了」）：再按
    // agentKey 清一次旧条目——tab 重建后 sc 是新元素，v4SubClose(el) 按 el
    // 永远匹配不到旧条目，_subs[agentKey] 被直接覆盖=旧 store 的 EventSource
    // 无人关闭永久存活。开关几个来回吃满浏览器同域 6 连接上限：发消息 POST、
    // 主窗/子页 SSE 全部排队发不出去（后端无辜，/api/status 短请求还能挤过
    // ——「只刷 status」的假象来源）
    v4SubClose(agentKey);
    var sid = _HG.sid;
    if (!sid) return false;
    // a65：渲染走 bridge 子引擎（V3 subpane kit，只落窗格容器）；opt 带
    // tid/type/desc 供脚手架与档案联动。空快照兜底在 bridge 内闭环
    var store = new root.V4Store(sid, 'sub:' + agentKey);
    var render = new root.V4Bridge(store, el, {
      live: true, sub: true,
      tid: opt.tid || '', agent: agentKey,
      type: opt.type || 'Task', desc: opt.desc || '',
      conclEl: opt.conclEl || null
    });
    _subs[(el.dataset && el.dataset.v4Key) || agentKey] = _subs[agentKey] =
      { store: store, render: render, el: el };
    store.connect();
    return true;
  }

  function v4SubClose(el) {
    for (var k in _subs) {
      var e = _subs[k];
      if (e && (e.el === el || k === el)) {
        try { e.render.close(); } catch (err) {}
        try { e.store.close(); } catch (err) {}
        delete _subs[k];
      }
    }
  }

  function v4SubCloseAll() {
    for (var k in _subs) {
      try { _subs[k].render.close(); } catch (e) {}
      try { _subs[k].store.close(); } catch (e) {}
      delete _subs[k];
    }
  }

  root.V4Main = {
    on: v4On,
    switch: v4Switch,
    close: v4Close,
    newCmd: v4NewCmd,
    markPending: v4MarkPending,
    subOpen: v4SubOpen,
    subClose: v4SubClose,
    subCloseAll: v4SubCloseAll
  };
})(window);
