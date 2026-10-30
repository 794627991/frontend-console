/* v4main —— v4 归一管线主接线器（批E/F）。
 *
 * 接线点（v4On() 时生效，旧管线原样保留）：
 *   sessions.js switchTo  → 清场块后 v4Switch(sid) 全权接管（snapshot 整建
 *                           + delta 增量；不再 openSSE/histFetch/_histRender）
 *   chatctl.js dispatch   → body 带 cmd（uuid）+ store.markPending（2s 投影
 *                           静默自动重订阅恢复——绝不重放/伪造消息行）
 *   subpane 子窗格        → v4SubOpen(el, agentKey)：子会话独立 store（同管线
 *                           delta 直推，替代 _subReplay 轮询全量重建）
 *
 * 开关：a138（用户拍板「V4 唯一基准，不允许存在开关」）起 v4On 恒 true——
 * ?v4=0 / localStorage hg_v4 / 服务端 __HG_V4__ 注入等回退通道已全量退役。
 */
(function (root) {
  'use strict';

  function v4On() {
    // a138：V4 唯一基准。函数保留只为兼容存量调用点的 typeof 守卫，恒真。
    return true;
  }


  // ---- 主窗 store/render 单例 ----------------------------------------------

  var _cur = null;      // {sid, store, render}

  function v4Switch(sid, keepInput, cwdHint) {
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
    // 内网报告修复（P2）：connect 前先失效旧导轨——旧刻度+旧 railItems 在
    // 重建完成前是「可见但点了必失联」的窗口期，先撤下避免误导点击
    _HG.railItems = null;
    if (typeof _hgRailEl !== 'undefined' && _hgRailEl) {
      _hgRailEl.classList.remove('show');
      _hgRailEl.innerHTML = '';
    }
    var store = new root.V4Store(sid, 'main');
    var render = new root.V4Bridge(store, flow, { live: true });
    _cur = { sid: sid, store: store, render: render };
    _HG.v4Cur = _cur;
    store.connect();
    // 兼容旧链路的状态账（部分基元读这些字段）
    _HG.sid = sid;
    // switchTo 公共尾巴（标头/模型/cwd/列表）被 v4 分流短路——此处补齐
    v4PaintHeader(sid, keepInput, cwdHint);
  }

  function v4PaintHeader(sid, keepInput, cwdHint) {
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
      // a132（用户实锤「会话首条，不切会话的话工程路径显示不出来」）：
      // 新会话刚建时 _HG.sessions 里还没有这一条（refreshSessions 的异步
      // 往返没回来），meta=null → cwd 被画成空串，必须切走再切回才恢复。
      // ensureSession 手里有后端回的 j.cwd，用 cwdHint 兜住首帧。
      var mcwd = (meta && meta.cwd) || cwdHint || '';
      if (typeof _hgCwdEl !== 'undefined' && _hgCwdEl)
        _hgCwdEl.textContent = mcwd;
      // 项目 chip 跟随会话 cwd（对齐 V3 sessions.js:581——切回历史会话恢复
      // 该会话目录；v4 分流短路了冷开路此段，chip 停在默认项目）
      if (mcwd) {
        _HG.cwd = mcwd;
        if (typeof _hgSaveCwd === 'function') { try { _hgSaveCwd(mcwd); } catch (e) {} }
        if (typeof projChipLabel === 'function') { try { projChipLabel(); } catch (e) {} }
      }
      // 对抗审 P2-4（a142）：权限/思考档芯片随会话恢复（对齐 V3 尾段
      // sessions.js:600-604，v4 分流曾丢——显示上一会话的档位值）
      if (meta) {
        if (meta.permission && meta.permission !== _HG.perm) {
          _HG.perm = meta.permission;
          if (typeof permChipLabel === 'function') { try { permChipLabel(); } catch (e) {} }
        }
        var _st = meta.think || null;
        if (_st !== _HG.thinkLv) {
          _HG.thinkLv = _st;
          if (typeof thinkChipLabel === 'function') { try { thinkChipLabel(); } catch (e) {} }
        }
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
    if (typeof _HG !== 'undefined') {
      _HG.v4Cur = null;
      // a123（审计）：v4 不连旧流 → store.js 的 _hgCompactionEnd 兜底
      // （压缩结束事件丢失时收口）在此路不可达。切会话/关库时若仍在压缩态，
      // 1s 秒表会跨会话常驻自转，且回原会话恒显「正在压缩上下文 · 已 Nm」。
      // 这里直接复位三字段+清表——**不调** _hgCompactionEnd：它会置
      // compactResume（「压缩完回该会话要 reopen 回合组」的标记），而此刻
      // 压缩并未结束，置了会让回原会话时误 reopen。
      if (_HG.compactTimer) {
        try { clearInterval(_HG.compactTimer); } catch (e) {}
        _HG.compactTimer = null;
      }
      _HG.compacting = false;
      _HG.compactSid = null;
    }
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

  // a122（用户实锤「窗格一直开着，续派后新内容不显示」根因：连接饿死）：
  // WebView2/Chromium 同源 HTTP/1.1 连接上限 6 条——proxy 状态流+主窗 v4 流
  // 已占 2，每个打开的子代理 tab 再各占 1 条 EventSource，用户「同时 ≤3 个
  // 子代理」惯例下正好满额；续派时代理的（重）连接在浏览器排队队尾静默
  // 等slot——无数据无报错，窗格冻结在旧内容（实机复现：关掉两个无关 tab
  // 后窗格立刻恢复）。结构修：**只有激活 tab 保持流**，后台 tab pause 断流
  // （DOM/游标保留，激活即携水位续传）。最坏连接数 = proxy+main+1 子 = 3。
  var _subFocusKey = null;

  function v4SubFocus(agentKey) {
    if (!agentKey) return;
    _subFocusKey = agentKey;
    for (var k in _subs) {
      var e = _subs[k];
      if (!e || !e.store) continue;
      if (k === agentKey) { try { e.store.resume(); } catch (err) {} }
      else { try { e.store.pause(); } catch (err) {} }
    }
  }

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
    // a122：开 tab 即聚焦——本 tab 起流、其余后台 tab pause（连接预算见上）
    v4SubFocus(agentKey);
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

  // a68：主窗终态直达子 pane（feed 冻结/转写无 result 行时 store 永静默
  // ——秒表永跑「永远不结束」的兜底收口通道；bridge 内幂等）
  function v4SubNotify(agentKey, err, summary) {
    var e = _subs[agentKey];
    if (e && e.render && typeof e.render.subNotify === 'function') {
      try { e.render.subNotify(!!err, summary || ''); } catch (err2) {}
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
    subCloseAll: v4SubCloseAll,
    subNotify: v4SubNotify,
    subFocus: v4SubFocus
  };
})(window);
