// ============================================================
// a219：侧栏宽度拖拽（用户需求：允许改，上限 = 屏幕宽 1/3）
// 条：JS 动态插入 sidebar 右缘（不动 index.html 结构——div 配平铁律）
// 持久化：/api/theme 顺车 sidebar_w（localStorage 按端口隔离不可用）
// ============================================================
// 模块化一期（js-modularization 分支）：已转 ES module。
// 零对外表面（无挂载、无引用方）；自带 _wzInit 幂等守卫。defer 语义下
// #sidebar 必然已存在（原经典时序还依赖 :605 时 DOM 就绪，模块化更稳）。
'use strict';
  const sb = document.getElementById('sidebar');
  // 模块化注：顶层裸 return 在 ESM 里非法（eslint 门禁当场抓获 Parsing
  // error），用守卫块包裹，行为等价。
  if (sb && !sb._wzInit) {
  sb._wzInit = true;
  const bar = document.createElement('div');
  bar.className = 'sidebar-resizer';
  bar.title = '拖动调节侧栏宽度（最宽为屏幕 1/3）';
  sb.parentElement.insertBefore(bar, sb.nextSibling);

  // a59x 侧栏收放手柄（用户定调位置：侧栏右缘垂直居中，VSCode 折叠手柄
  // 同位；v1 底部条占一排 / v2 顶栏钮不和谐，均用户实锤撤除）。挂 resizer
  // 内天然跟随时变宽度与 mini 44px。click 走 CustomEvent 解耦到 sidebar.js
  // 的收放逻辑；mousedown stopPropagation 防触发宽度拖拽。
  const edge = document.createElement('button');
  edge.className = 'sb-edge';
  edge.type = 'button';
  edge.title = '收起侧栏';
  edge.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4.5L6.5 8l3.5 3.5"/></svg>';
  bar.appendChild(edge);
  edge.addEventListener('click', () => {
    document.dispatchEvent(new CustomEvent('fc:sidebar-toggle'));
  });
  edge.addEventListener('mousedown', e => e.stopPropagation());

  const MIN = 200;   // a59x：180 是 3-tab 旧值，4 tab（+搜索）下 200 才不换行（用户实锤）
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
  // R1 审计 W11：a524 的 iframe 指针禁用已删（a544 后页面无 iframe，
  // iframes() 恒空集；WebView2 为原生 HWND 不受 pointerEvents 影响）
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
    // 审计 P3：mini 态（44px !important）拖不出视觉变化但 offsetWidth=44 会被
    // 持久化污染 config（下次展开被 MIN 钳制自愈，仍不存脏值）——直接跳过
    if (document.body.classList.contains('sb-mini')) return;
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
    // a59x：窄窗时按视口钳回（原先只钳屏宽 1/3 上限，innerWidth 缩小时
    // 侧栏可能大于可用空间把 center 挤没）
    const cap = Math.min(maxW(), window.innerWidth - 120);
    if (sb.offsetWidth > cap) apply(cap);
  });
  }   // 守卫块收口（模块顶层不允许裸 return，见上注）
