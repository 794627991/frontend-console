// harness modal.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  // a444（审计 P1）：挂 body 的弹窗没有宿主容器可跟随销毁。登记一张收口表，
  // 由宿主模块（版本面板）teardown 时调 closeAll() 统一 close——close 会走
  // 正常 resolve(null)，调用方的 .then 拿到「取消」，不会误发写请求。
  window._hgModalReg = (function () {
    const m = new Map();   // ov -> close(v)
    return {
      add(ov, close) { m.set(ov, close); },
      del(ov) { m.delete(ov); },
      closeAll() {
        const items = [...m.entries()];
        m.clear();
        items.forEach(([ov, close]) => { try { close(null); } catch (_) {} });
      }
    };
  })();
  // 挂载点：harness 已建时挂 _hgWrap（跟随 Claude tab 隐藏/销毁），未建时挂
  // body——版本面板已独立成主区 tab，它也要用这个弹窗，而 _hgWrap 只有打开
  // Claude 界面才有值
  // a443（审计实锤，两条）：① _hgWrap 在 Claude tab 关闭后仍是变量里的死
  // 引用（已脱离文档），继续挂进去弹窗永远不可见；② .hg-modal-ov 是
  // position:absolute + inset:0，包含块取最近的 positioned 祖先——挂进
  // display:none 的 _hgWrap（Claude tab 非当前时）实测尺寸 0×0，用户点
  // 「Pull」「纳入版本控制」毫无反应。判据必须是「在文档里且真的可见」。
  function _hgModalHost() {
    try {
      const w = (typeof _hgWrap !== 'undefined') ? _hgWrap : null;
      if (!w || !document.contains(w)) return document.body;
      // a466（审计 P2）：不能只用 offsetParent !== null 判「可见」——
      // position:fixed 元素的 offsetParent 恒为 null，宿主一旦改成 fixed
      // 悬浮形态，harness 内弹窗就会永远退回 body、遮罩盖全窗。
      // 显式放行 fixed/sticky，其余仍用 offsetParent 判隐藏祖先。
      let pos = '';
      try { pos = (getComputedStyle(w).position || ''); } catch (_) {}
      if (pos === 'fixed' || pos === 'sticky' || w.offsetParent !== null) return w;
    } catch (_) {}
    return document.body;
  }
  function hgModal(title, bodyHtml, buttons) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      ov.innerHTML = `<div class="hg-modal"><div class="hg-modal-title">${esc(title)}</div>${bodyHtml}<div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const inp0 = ov.querySelector('input');
      // a444（审计 P1）：弹窗落 body 时不再随任何 tab 销毁，必须显式收口。
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
      // a447（用户实锤截图「重命名会话」也弹黑窗）：浏览器自动填充建议层
      // 是 Edge 自绘的深色面板，样式完全不受我们控制。弹窗里所有文本类
      // 输入框统一改 type=search + autocomplete=off 并去掉 name——Chromium
      // 对「疑似表单字段」会忽略 autocomplete=off，但搜索框不入库。
      // 视觉差异由 style.css 的 .hg-modal input 规则抹平。
      try {
        ov.querySelectorAll('input').forEach((inp) => {
          const t = (inp.getAttribute('type') || 'text').toLowerCase();
          if (t === 'checkbox' || t === 'radio' || t === 'file' || t === 'number'
              || t === 'date' || t === 'time' || t === 'color' || t === 'range'
              // a466（审计 P2）：password 必须排除——改成 search 会明文显示
              // （代理凭据/Token 输入一旦走 hgModal 就泄露）。hidden 同理
              // （改成 search 会变成可见搜索框）。
              || t === 'password' || t === 'hidden') return;
          inp.setAttribute('type', 'search');
          inp.setAttribute('autocomplete', 'off');
          inp.setAttribute('aria-autocomplete', 'none');
          inp.removeAttribute('name');
        });
      } catch (_) {}
      // 弹窗登记到收口表；宿主被拆（tab 关闭）时统一 close——否则弹窗会
      // 盖在全窗上，误点主按钮还会对已销毁的面板发真实写请求（实测
      // POST /api/vcs/add）。
      // a466（审计 P2）：宿主是 _hgWrap 时也要登记。原来只登记 body 的，
      // 挂 wrap 的弹窗 DOM 会随 wrap 移除，但 Promise 永不 resolve——
      // `await hgModal(...)` 的调用链（如技能卸载确认）永久挂起，闭包与
      // 调用方状态都不释放。
      try {
        if (window._hgModalReg
            && typeof window._hgModalReg.add === 'function') {
          reg = window._hgModalReg;
          reg.add(ov, close);
        }
      } catch (_) {}
      const inp = inp0;
      if (inp) { inp.focus(); inp.select();
        inp.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { const b = buttons[buttons.length - 1]; const v = typeof b.value === 'function' ? b.value(inp) : b.value; close(v); }
          if (e.key === 'Escape') close(null);
        }); }
    });
  }
  // 自建弹窗（不走 hgModal）的收口入口：ov 为遮罩节点，closeFn 负责摘 DOM
  // 与必需的 resolve。调用方在 appendChild 之后调一次即可。
  function hgModalTrack(ov, closeFn) {
    try {
      if (window._hgModalReg && typeof window._hgModalReg.add === 'function')
        window._hgModalReg.add(ov, closeFn);
    } catch (_) {}
  }
  function hgConfirm(title, msg) {
    return hgModal(title, `<div class="hg-modal-body">${esc(msg)}</div>`,
      [{label: '取消', value: false}, {label: '删除', primary: true, value: true}]);
  }
  function hgPrompt(title, label, val) {
    return hgModal(title, `<div class="hg-modal-body"><label>${esc(label)}</label><input autocomplete="off" data-hg-mi value="${esc(val || '')}" name="hg_mi"></div>`,
      [{label: '取消', value: null}, {label: '保存', primary: true, value: (inp) => (inp ? inp.value.trim() : '')}]);
  }
