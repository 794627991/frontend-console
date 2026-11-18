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
      // a259：图标装进固定 16×16 居中盒（.ctx-ico）——SVG/emoji 统一光学
      // 对齐（不再与文本基线错位）；icon 原样插入（SVG 字符串），label 转义
      (it.icon ? `<span class="ctx-ico">${it.icon}</span>` : '') + esc(it.label) +
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

// 模块化一期：转 ES module——跨文件/Python 裸引用消费名挂 window。
// 清单由 eslint no-undef 神谕反推（零启发式）：本文件转模块后，其余
// 文件/Python 推送的裸标识符引用全部经 window 解析。
window.buildCtxMenu = buildCtxMenu;
