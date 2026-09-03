// ============================================================
// 换肤：data-theme 挂 <html>，覆盖 CSS 调色板变量实现整窗换色。
// 选择存 localStorage，下次启动自动应用。
// ============================================================
const THEMES = [
  { id: 'deepblue',  name: '深空蓝',   desc: '默认科技蓝 · 壳体深蓝 + 纸感阅读面' },
  { id: 'warmgray',   name: '暖夜灰',   desc: '暖紫灰壳体 · 更柔和 · 阅读面深一档' },
  { id: 'darkgreen',  name: '暗调绿',   desc: '经典 CRT 深绿灰 · 老派护眼风' },
  { id: 'paper',      name: '午夜纸',   desc: '全浅色窗体 · 与笔记/日志完全统一' },
];

function applyTheme(id) {
  if (!THEMES.some(t => t.id === id)) id = 'deepblue';
  document.documentElement.setAttribute('data-theme', id);
  try { localStorage.setItem('console_theme', id); } catch(_) {}
  // 已打开的终端实时换色：按新主题变量重建 xterm 16 色（与 buildTerminal 同源逻辑）
  const cs = getComputedStyle(document.documentElement);
  const termBg = (cs.getPropertyValue('--term-bg') || '#1a1f2e').trim() || '#1a1f2e';
  const termFg = (cs.getPropertyValue('--term-fg') || '#d7d7d7').trim() || '#d7d7d7';
  const light = id === 'paper';
  const theme = {
    background: termBg, foreground: termFg,
    cursor: light ? '#2a7a9e' : '#528bff', cursorAccent: termBg,
    selectionBackground: 'rgba(82,139,255,0.25)',
    ...(light
      ? { black: '#3a3d40', red: '#b3474f', green: '#4a7c3f', yellow: '#9c6a1f',
          blue: '#2a6a8f', magenta: '#8a4a9e', cyan: '#2a7a8f', white: '#5a5d60',
          brightBlack: '#807b6d', brightRed: '#9e3038', brightGreen: '#356a2c',
          brightYellow: '#7c5215', brightBlue: '#1f5f7c', brightMagenta: '#6a3680',
          brightCyan: '#1f627c', brightWhite: '#26292c' }
      : { black: termBg, red: '#e06c75', green: '#98c379', yellow: '#e5c07b',
          blue: '#61afef', magenta: '#c678dd', cyan: '#56b6c2', white: '#abb2bf',
          brightBlack: '#5c6370', brightRed: '#d19a66', brightGreen: '#b5e890',
          brightYellow: '#e5c07b', brightBlue: '#82b8ff', brightMagenta: '#d19a66',
          brightCyan: '#66cccc', brightWhite: '#ffffff' }),
  };
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.term) { try { c.term.options.theme = theme; } catch(_) {} }
  }
}

(function initTheme() {
  let saved = 'deepblue';
  try { saved = localStorage.getItem('console_theme') || 'deepblue'; } catch(_) {}
  applyTheme(saved);

  const menu = $('themeMenu');
  function renderMenu() {
    const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
    menu.innerHTML = '';
    THEMES.forEach(t => {
      const item = document.createElement('div');
      item.className = 'theme-item' + (t.id === cur ? ' active' : '');
      item.innerHTML = `<div class="theme-swatch" data-theme="${t.id}"></div>
        <div class="theme-info"><div class="name">${t.name}</div><div class="desc">${t.desc}</div></div>
        ${t.id === cur ? '<span class="theme-check">✓</span>' : ''}`;
      item.onclick = () => { applyTheme(t.id); renderMenu(); showBanner('已切换主题：' + t.name); };
      menu.appendChild(item);
    });
  }
  $('btnTheme').onclick = (e) => {
    e.stopPropagation();
    const show = menu.classList.toggle('show');
    if (show) renderMenu();
  };
  document.addEventListener('click', e => {
    if (!menu.contains(e.target) && e.target !== $('btnTheme')) menu.classList.remove('show');
  });
})();
