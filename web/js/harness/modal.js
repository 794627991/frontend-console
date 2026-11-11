// harness modal.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  // a438（审计 P1）：挂 body 的弹窗没有宿主容器可跟随销毁。登记一张收口表，
  // 由宿主模块（版本面板）teardown 时调 closeAll() 统一 close——close 会走
  // 正常 resolve(null)，调用方的 .then 拿到「取消」，不会误发写请求。
  window._hgModalReg = (function () {
    const m = new Map();   // ov -> {close, host}
    return {
      add(ov, close, host) { m.set(ov, { close, host: host || null }); },
      del(ov) { m.delete(ov); },
      // a453（第二轮审计 P2）：支持按宿主收口。原来是全局单例无宿主维度——
      // 关 Claude tab 会把版本面板（挂 body）正在用的确认框一起 close 掉，
      // 用户操作被打断。host 缺省时只关 body（即无人认领）那批。
      // a459（审计遗留）：原实现 `host === undefined || rec.host === host`
      // 与本条注释相反——无参调用实际命中**全部**条目（a456 修掉的「vcs
      // 面板 teardown 关掉所有弹窗」踩的就是这个语义）。按注释兑现：缺省
      // 只关 host='body'（无人认领）那批。
      closeAll(host) {
        const want = (host === undefined) ? 'body' : host;
        const hit = [];
        for (const [ov, rec] of m) {
          if (rec.host === want) hit.push([ov, rec]);
        }
        hit.forEach(([ov]) => m.delete(ov));
        hit.forEach(([, rec]) => { try { rec.close(null); } catch (_) {} });
      }
    };
  })();
  // 挂载点：harness 已建时挂 _hgWrap（跟随 Claude tab 隐藏/销毁），未建时挂
  // body——版本面板已独立成主区 tab，它也要用这个弹窗，而 _hgWrap 只有打开
  // Claude 界面才有值
  // a437（审计实锤，两条）：① _hgWrap 在 Claude tab 关闭后仍是变量里的死
  // 引用（已脱离文档），继续挂进去弹窗永远不可见；② .hg-modal-ov 是
  // position:absolute + inset:0，包含块取最近的 positioned 祖先——挂进
  // display:none 的 _hgWrap（Claude tab 非当前时）实测尺寸 0×0，用户点
  // 「Pull」「纳入版本控制」毫无反应。判据必须是「在文档里且真的可见」。
  function _hgModalHost() {
    try {
      const w = (typeof _hgWrap !== 'undefined') ? _hgWrap : null;
      if (!w || !document.contains(w)) return document.body;
      // a452（审计 P2）：不能只用 offsetParent !== null 判「可见」——
      // position:fixed 元素的 offsetParent 恒为 null，宿主一旦改成 fixed
      // 悬浮形态，harness 内弹窗就会永远退回 body、遮罩盖全窗。
      // 显式放行 fixed/sticky，其余仍用 offsetParent 判隐藏祖先。
      let pos = '';
      try { pos = (getComputedStyle(w).position || ''); } catch (_) {}
      if (pos === 'fixed' || pos === 'sticky' || w.offsetParent !== null) return w;
    } catch (_) {}
    return document.body;
  }
  // 弹窗归属：用「创建时的活动 tab」而不是宿主节点。宿主节点在 harness tab
  // 非当前时恒为 body（_hgWrap 不可见），与版本面板的弹窗撞在一起，关 Claude
  // tab 会把别人的确认框一起收掉（a453 审计 P2）。
  function _hgModalOwner() {
    try {
      if (typeof activePortId !== 'undefined' && activePortId) return activePortId;
    } catch (_) {}
    return 'body';
  }
  function hgModal(title, bodyHtml, buttons) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      ov.innerHTML = `<div class="hg-modal"><div class="hg-modal-title">${esc(title)}</div>${bodyHtml}<div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const inp0 = ov.querySelector('input');
      // a438（审计 P1）：弹窗落 body 时不再随任何 tab 销毁，必须显式收口。
      // 统一 close()：摘 DOM + 登记处退册 + resolve(null)（幂等）。
      let done = false;
      let reg = null;
      const close = (v) => {
        if (done) return;
        done = true;
        try { ov.remove(); } catch (_) {}
        if (reg) { try { reg.del(ov); } catch (_) {} }
        resolve(v);
      };
      buttons.forEach((b) => {
        const btn = document.createElement('button');
        btn.className = 'btn' + (b.primary ? ' primary' : '');
        btn.textContent = b.label;
        btn.onclick = () => { const v = typeof b.value === 'function' ? b.value(inp0) : b.value; close(v); };
        acts.appendChild(btn);
      });
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      const host = _hgModalHost();
      host.appendChild(ov);
      // a441（用户实锤截图「重命名会话」也弹黑窗）：浏览器自动填充建议层
      // 是 Edge 自绘的深色面板，样式完全不受我们控制。弹窗里所有文本类
      // 输入框统一改 type=search + autocomplete=off 并去掉 name——Chromium
      // 对「疑似表单字段」会忽略 autocomplete=off，但搜索框不入库。
      // 视觉差异由 style.css 的 .hg-modal input 规则抹平。
      try {
        ov.querySelectorAll('input').forEach((inp) => {
          // a453（第二轮审计 P2）：改为**白名单**。原黑名单漏了
          // button/submit/reset/image（改成 search 会变成可见文本框、点击
          // 行为失效）和 datetime-local/month/week（改型后 value 格式与取值
          // 语义都变）。只改纯文本类，其余一律原样。
          const t = (inp.getAttribute('type') || 'text').toLowerCase();
          if (t !== 'text' && t !== 'search' && t !== 'email'
              && t !== 'tel' && t !== 'url') return;
          inp.setAttribute('type', 'search');
          inp.setAttribute('autocomplete', 'off');
          inp.setAttribute('aria-autocomplete', 'none');
          inp.removeAttribute('name');
        });
      } catch (_) {}
      // 弹窗登记到收口表；宿主被拆（tab 关闭）时统一 close——否则弹窗会
      // 盖在全窗上，误点主按钮还会对已销毁的面板发真实写请求（实测
      // POST /api/vcs/add）。
      // a452（审计 P2）：宿主是 _hgWrap 时也要登记。原来只登记 body 的，
      // 挂 wrap 的弹窗 DOM 会随 wrap 移除，但 Promise 永不 resolve——
      // `await hgModal(...)` 的调用链（如技能卸载确认）永久挂起，闭包与
      // 调用方状态都不释放。
      try {
        if (window._hgModalReg
            && typeof window._hgModalReg.add === 'function') {
          reg = window._hgModalReg;
          reg.add(ov, close, _hgModalOwner());
        }
      } catch (_) {}
      const inp = inp0;
      // a453（第二轮审计 P2）：Esc 原来只绑在 inp 上——hgConfirm（删除会话/
      // 纳入版本控制/Pull/卸载技能）这类无输入框的弹窗整段监听不注册，
      // 按 Esc 毫无反应。改为同时绑 ov（tabindex 让它能收键盘事件）。
      ov.setAttribute('tabindex', '-1');
      ov.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); close(null); }
      });
      if (inp) { inp.focus(); inp.select();
        inp.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { const b = buttons[buttons.length - 1]; const v = typeof b.value === 'function' ? b.value(inp) : b.value; close(v); }
          if (e.key === 'Escape') close(null);
        }); }
    });
  }
  // 自建弹窗（不走 hgModal）的收口入口：ov 为遮罩节点，closeFn 负责摘 DOM
  // 与必需的 resolve。调用方在 appendChild 之后调一次即可。
  // a453（第二轮审计 P1）：登记时必须包一层——自建弹窗的 closeFn 只摘 DOM
  // 不退册，收口表里的条目连同整棵弹窗 DOM 永久保留（反复开关 N 次就攒 N 棵）。
  // a459（审计遗留）：光包 wrapper 只覆盖「closeAll 收口」这条路——调用方
  // 自己的关闭按钮若绑的还是裸 closeFn，手动关一次仍漏一条登记（Map 拿着
  // 整棵 detached DOM 到 tab 销毁才清）。返回包好的 close 让调用方绑定。
  function hgModalTrack(ov, closeFn) {
    try {
      if (window._hgModalReg && typeof window._hgModalReg.add === 'function') {
        const wrapped = (v) => {
          try { window._hgModalReg.del(ov); } catch (_) {}
          try { closeFn(v); } catch (_) {}
        };
        window._hgModalReg.add(ov, wrapped, _hgModalOwner());
        return wrapped;
      }
    } catch (_) {}
    return closeFn;
  }
  function hgConfirm(title, msg) {
    return hgModal(title, `<div class="hg-modal-body">${esc(msg)}</div>`,
      [{label: '取消', value: false}, {label: '删除', primary: true, value: true}]);
  }
  function hgPrompt(title, label, val) {
    return hgModal(title, `<div class="hg-modal-body"><label>${esc(label)}</label><input autocomplete="off" data-hg-mi value="${esc(val || '')}" name="hg_mi"></div>`,
      [{label: '取消', value: null}, {label: '保存', primary: true, value: (inp) => (inp ? inp.value.trim() : '')}]);
  }
