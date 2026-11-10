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

  function fix(el) {
    // a447（用户实锤两处截图）：浏览器自动填充建议层（Edge 深色「保存的信息」
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
    // a447：type=search 的输入框是「为了躲浏览器自动填充黑窗」才改成 search
    // 的。给它们补回 name 会把字段重新变成浏览器可记忆的表单字段，自动填充
    // 建议层又冒出来——跳过。
    if (el.type !== 'search' && !el.id && !el.getAttribute('name')) {
      const base = (el.className || '').split(/\s+/)[0] || 'field';
      el.setAttribute('name', base);
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
