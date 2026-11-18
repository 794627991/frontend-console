// harness subblk.js (批4·段体系整体退役后仅存共用工具行工厂：_subToolHeadHtml/_toolInputBodyHtml——窗格(subpane)与主链(hist/tools)共用；段工厂族(_subBlkGet/_subSec*/_subBlkState 等 18 函数)随 .h-subblock 退役删除)

  // ==================== 共用工具行工厂（段退役幸存）====================

  function _subToolHeadHtml(name, summary, slotsHtml, opts) {
    // v2.44R（复审3）：opts.sec（Grep/Glob 的 in path 等次级信息）并入 title
    // 悬浮——头行保持单行摘要不被挤爆；opts.copy（Bash/PowerShell）产出复制
    // 钮：head 本体是 <button>，嵌套 button 非法，用 span+role 复用既有
    // .h-tool-copy 样式与委托（委托里 copy 分支已提到 head 分支之前）
    const o = opts || {};
    const title = summary && o.sec ? summary + ' · ' + o.sec : (summary || o.sec || '');
    return `<button class="h-tool-head"><span class="h-chev">▸</span>` +
      `<span class="h-tool-name">${_hToolIco(name)} ${esc(_hToolLabel(name))}</span>` +
      (summary ? `<span class="h-tool-arg" title="${esc(title)}">${esc(summary)}</span>` : '') +
      (o.copy ? `<span class="h-tool-copy" role="button" title="复制命令">复制</span>` : '') +
      (slotsHtml != null ? `<span class="h-tslots">${slotsHtml}</span>` : '') +
      `</button>`;
  }
  function _toolInputBodyHtml(cfg, v) {
    // v3.5.336：v.dln（转写权威行号，ZCode 式）到位时 diff 行号从真实行起数
    if (cfg.kind === 'diff') return `<div class="h-diff">${diffHtml(v && v.old, v && v.neu,
      (v && typeof v.dln === 'number') ? v.dln : undefined)}</div>`;
    if (cfg.kind === 'todo') return todoHtml(v && v.todos || v);
    if (cfg.kind === 'question') return (v || []).map(_hgQ =>
      `<div class="t-item"><span>${ICO16.help}</span><span><b>${esc(_hgQ.header || '')}</b> ${esc(_hgQ.question || '')}${(_hgQ.options || []).map(o => `<span class="q-opt">${esc(typeof o === 'string' ? o : o.label)}</span>`).join('')}</span></div>`).join('');
    // a63（用户实锤「bash 复制的内容 __init__ 变 init」）：命令是代码不是
    // markdown——md 渲染把 __x__ 解析成粗体（textContent 丢下划线）、# 变
    // 标题、* 变斜体，展示与复制（取 DOM 文本）双坏。bash 族走纯文本 pre
    if (cfg.kind === 'bash')
      return `<pre class="h-tool-body h-tool-cmd">${esc(String(v || ''))}</pre>`;
    return `<div class="h-tool-body">${renderMd(String(v))}</div>`;
  }

// 模块化二期：转 ES module——跨文件消费名挂 window（AST Program 级声明归属）。
// let/var 走存取器（跨文件重赋值保语义）；const/function/class 普通挂载。
window._subToolHeadHtml = _subToolHeadHtml;
window._toolInputBodyHtml = _toolInputBodyHtml;
