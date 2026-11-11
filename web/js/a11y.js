// ============================================================
// a307：表单无障碍自动兜底（用户实锤 DevTools Issues 99+ 条
// "No label associated with a form field" / 3 条缺 id/name）
// ------------------------------------------------------------
// 规则：所有 input/select/textarea 若无 label 关联（label[for] /
// aria-label / aria-labelledby / title / 隐式 label 父），自动补
// aria-label——取值优先级：placeholder > 语义 class 映射 > type 默认。
// 缺 id/name 的补 name（用 class 或序号）。MutationObserver 兜底动态
// 新增（每 tab 的搜索框、xlsx 单元格输入、Monaco/xterm 内部 input——
// 后者是 99+ 累积的大头）。
// ============================================================
(function () {
  const CLS_HINT = [
    [/ts-q|search-q|term-search/, '搜索'],
    [/cmd-add-name/, '备注名'],
    [/cmd-add-cmd|cmdInput/, '命令'],
    [/log-dir/, '日志目录'],
    [/replay-seek|replaySeek/, '回放进度'],
    [/replay-speed|replaySpeed/, '回放速度'],
    [/ed-enc/, '文件编码'],
    [/mdtheme/, '预览主题'],
    [/mdmode/, '预览布局'],
    [/hg-search/, '会话搜索'],
    [/file-rename|ed-rename/, '重命名'],
  ];

  let _a11ySeq = 0;   // a453：补 id 时的唯一序号（见下方 fix 注释）
  function fix(el) {
    // a441（用户实锤两处截图）：浏览器自动填充建议层（Edge 深色「保存的信息」
    // 面板）会挂到被它认作表单字段的文本框上。统一加 autocomplete=off；
    // 弹窗（hgModal）与提问卡另外用 type=search 彻底隔离（那两处样式自持，
    // 改 type 不影响其它模块）。全局不改 type——会打断 input[type=text]
    // 选择器与密码显隐的二态判断。
    if (el.tagName === 'INPUT' && !el.getAttribute('autocomplete')) {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'text' || t === 'search' || t === 'password' || t === 'email' || t === 'url' || t === 'tel') {
        el.setAttribute('autocomplete', 'off');
      }
    }
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') ||
        el.getAttribute('title') || el.closest('label') ||
        (el.id && document.querySelector('label[for="' + el.id + '"]'))) {
      // 已有关联——只补缺失的 name/id
    } else {
      const cls = el.className || '';
      let label = el.placeholder || '';
      if (!label) {
        for (const [re, txt] of CLS_HINT) { if (re.test(cls)) { label = txt; break; } }
      }
      if (!label) {
        const t = (el.tagName === 'SELECT') ? '下拉选择' : (el.type === 'checkbox' ? '勾选框' : el.type === 'number' ? '数字输入' : '文本输入');
        label = t;
      }
      el.setAttribute('aria-label', label);
    }
    // DevTools 另一条：A form field element should have an id or name
    // a441：type=search 的输入框是「为了躲浏览器自动填充黑窗」才改成 search
    // 的。给它们补回 name 会把字段重新变成浏览器可记忆的表单字段，自动填充
    // 建议层又冒出来——跳过。
    // a452（审计 P0：主因没除）：只豁免 search 不够——设置页/连接弹窗/识图/
    // 提示词等大量文本框只是加了 autocomplete="off"、仍是 type=text，observer
    // 照样补回 name（而且是从 className 派生的重复名 dd-input/field），
    // Edge 一旦判成用户名/地址启发式就直接忽略 off、黑窗照弹。凡是**显式
    // 声明了 autocomplete="off" 的控件**都不补 name：那是「我不参与表单
    // 记忆」的明确意图，补名等于把它打回可记忆字段。
    const _ac = (el.getAttribute('autocomplete') || '').trim().toLowerCase();
    // a453（第二轮审计 P2）：补 **id** 而不是 name。DevTools 那条告警
    // （A form field element should have an id or name）id 也算满足，而
    // name 会重新让控件进入浏览器的字段记忆启发式——正是本规则想除的根因。
    // 另外用「class + 全局序号」保证唯一：原实现同 class 的多个无名字段会
    // 拿到同一个 name（office-viewer 的 data-ov-page 就是 name="field"）。
    if (el.type !== 'search' && _ac !== 'off'
        && !el.id && !el.getAttribute('name')) {
      const base = (el.className || '').split(/\s+/)[0] || 'field';
      el.id = 'a11y-' + base.replace(/[^\w-]/g, '') + '-' + (_a11ySeq++);
    }
  }

  function scan(root) {
    (root || document).querySelectorAll('input, select, textarea').forEach(fix);
  }

  // 初始 + 动态兜底（subtree 批量，只在新增节点里找表单控件——性能安全）
  scan();
  new MutationObserver(muts => {
    for (const m of muts) {
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.matches && n.matches('input, select, textarea')) fix(n);
        else if (n.querySelectorAll) scan(n);
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
})();
