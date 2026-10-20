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
    // v4 归一管线默认常开（用户拍板：run_debug 打开即 v4，直接替换旧管线）。
    // ?v4=0 保留为紧急回退口（排查问题时单次降级，不影响下次启动）。
    var off = /[?&]v4=0/.test(location.search);
    _HG.v4 = !off;
    return _HG.v4;
  }

  // ---- 主窗 store/render 单例 ----------------------------------------------

  var _cur = null;      // {sid, store, render}

  function v4Switch(sid, keepInput) {
    v4Close();
    if (!sid) return;
    var flow = (typeof _hgFlow !== 'undefined') ? _hgFlow : null;   // let 全局
    if (!flow) return;
    var store = new root.V4Store(sid, 'main');
    var render = new root.V4Render(store, flow, { live: true });
    _cur = { sid: sid, store: store, render: render };
    _HG.v4Cur = _cur;
    store.connect();
    // 兼容旧链路的状态账（部分基元读这些字段）
    _HG.sid = sid;
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

  function v4SubOpen(el, agentKey, conclEl) {
    if (!el || !agentKey) return false;
    v4SubClose(el);
    var sid = _HG.sid;
    if (!sid) return false;
    var store = new root.V4Store(sid, 'sub:' + agentKey);
    var render = new root.V4Render(store, el,
      { live: true, sub: true, conclEl: conclEl || null });
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
