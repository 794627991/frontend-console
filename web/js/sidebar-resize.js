// ============================================================
// a219：侧栏宽度拖拽（用户需求：允许改，上限 = 屏幕宽 1/3）
// 条：JS 动态插入 sidebar 右缘（不动 index.html 结构——div 配平铁律）
// 持久化：/api/theme 顺车 sidebar_w（localStorage 按端口隔离不可用）
// ============================================================
(function () {
  'use strict';
  const sb = document.getElementById('sidebar');
  if (!sb || sb._wzInit) return;
  sb._wzInit = true;
  const bar = document.createElement('div');
  bar.className = 'sidebar-resizer';
  bar.title = '拖动调节侧栏宽度（最宽为屏幕 1/3）';
  sb.parentElement.insertBefore(bar, sb.nextSibling);

  const MIN = 180;
  const maxW = () => Math.floor(window.screen.width / 3);
  const apply = (w) => {
    // a233 P2-5: 视口钳（原只看主屏 1/3，小窗/分屏 main 被挤没）
    const v = Math.max(MIN, Math.min(w, maxW(), window.innerWidth - 120));
    sb.style.width = v + 'px';
    return v;
  };
  // 启动恢复（后端 config）
  fetch('/api/theme').then(r => r.json()).then(j => {
    if (j && j.sidebar_w) apply(+j.sidebar_w);
  }).catch(() => {});

  let dragging = false, startX = 0, startW = 0;
  bar.addEventListener('mousedown', e => {
    dragging = true; startX = e.clientX; startW = sb.offsetWidth;
    bar.classList.add('dragging');
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    apply(startW + (e.clientX - startX));
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    bar.classList.remove('dragging');
    document.body.style.userSelect = '';
    try {
      fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sidebar_w: sb.offsetWidth }) });
    } catch (_) {}
  };
  document.addEventListener('mouseup', endDrag);
  // a233 P2-3: mouseup 被吞（Alt+Tab）→ dragging 永真+userSelect 锁死——Escape/失焦双兜底
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && dragging) endDrag(); });
  window.addEventListener('blur', () => { if (dragging) endDrag(); });
  // 窗口 resize 时钳回上限内
  window.addEventListener('resize', () => {
    if (sb.offsetWidth > maxW()) apply(maxW());
  });
})();
