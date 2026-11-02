// ============================================================
// 共享右键菜单 builder（a209 批1：文件树 IDE 化地基）
// ------------------------------------------------------------
// 抽自 search.js showCtxMenu 与 file-tree.js contextmenu 的重复模式
// （两方各自 innerHTML + 定位 + 绑 onclick）。命令表驱动：
//   buildCtxMenu(x, y, [
//     { icon: '📋', label: '复制选中', shortcut: 'Ctrl+C', disabled, action() {} },
//     { sep: true },
//     ...
//   ])
// 全局关闭监听（点击外部/滚动/Escape）留在 search.js（唯一注册方，
// 双注册会关两次——无害但没必要）。
// ============================================================
function buildCtxMenu(x, y, items) {
  const m = typeof $ === 'function' && $('ctxMenu');
  if (!m) return;
  m.innerHTML = items.map(it => it.sep
    ? '<div class="ctx-sep"></div>'
    : `<div class="ctx-item${it.disabled ? ' disabled' : ''}" data-act="${esc(it.act || it.label)}">` +
      (it.icon ? `${it.icon} ` : '') + esc(it.label) +
      (it.shortcut ? ` <span class="ctx-kbd">${esc(it.shortcut)}</span>` : '') +
      '</div>').join('');
  m.style.display = 'block';
  const mw = m.offsetWidth, mh = m.offsetHeight;
  m.style.left = Math.max(2, Math.min(x, window.innerWidth - mw - 4)) + 'px';
  m.style.top = Math.max(2, Math.min(y, window.innerHeight - mh - 4)) + 'px';
  m.querySelectorAll('.ctx-item').forEach(el => {
    el.onclick = () => {
      const act = el.dataset.act;
      if (el.classList.contains('disabled')) return;
      hideCtxMenu();
      const it = items.find(i => !i.sep && (i.act || i.label) === act);
      if (it && typeof it.action === 'function') {
        try { it.action(); } catch (e) { showBanner('操作失败: ' + e, 4000, true); }
      }
    };
  });
}
