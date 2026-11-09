// harness modal.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
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
      if (w && document.contains(w) && w.offsetParent !== null) return w;
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
      buttons.forEach((b) => {
        const btn = document.createElement('button');
        btn.className = 'btn' + (b.primary ? ' primary' : '');
        btn.textContent = b.label;
        btn.onclick = () => { const v = typeof b.value === 'function' ? b.value(inp0) : b.value; ov.remove(); resolve(v); };
        acts.appendChild(btn);
      });
      ov.addEventListener('click', (e) => { if (e.target === ov) { ov.remove(); resolve(null); } });
      _hgModalHost().appendChild(ov);
      const inp = inp0;
      if (inp) { inp.focus(); inp.select();
        inp.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { const b = buttons[buttons.length - 1]; const v = typeof b.value === 'function' ? b.value(inp) : b.value; ov.remove(); resolve(v); }
          if (e.key === 'Escape') { ov.remove(); resolve(null); }
        }); }
    });
  }
  function hgConfirm(title, msg) {
    return hgModal(title, `<div class="hg-modal-body">${esc(msg)}</div>`,
      [{label: '取消', value: false}, {label: '删除', primary: true, value: true}]);
  }
  function hgPrompt(title, label, val) {
    return hgModal(title, `<div class="hg-modal-body"><label>${esc(label)}</label><input data-hg-mi value="${esc(val || '')}" name="hg_mi"></div>`,
      [{label: '取消', value: null}, {label: '保存', primary: true, value: (inp) => (inp ? inp.value.trim() : '')}]);
  }
