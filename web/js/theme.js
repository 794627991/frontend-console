// ============================================================
// 换肤：data-theme 挂 <html>，覆盖 CSS 调色板变量实现整窗换色。
// 持久化走后端 /api/theme（config.json）——localStorage 按 origin
// （127.0.0.1:端口）隔离，Flask 每次启动端口随机，永远读不到旧值。
// ============================================================
const THEMES = [
  // ---- 暗色系 ----
  { id: 'deepblue',  name: '深空蓝',   desc: '默认科技蓝 · 壳体深蓝 + 纸感阅读面', group: 'dark' },
  { id: 'onedark',    name: '夜暮紫',   desc: 'One Dark Pro 风深紫壳 · 蓝紫 accent', group: 'dark' },
  { id: 'warmgray',   name: '暖夜灰',   desc: '暖紫灰壳体 · 更柔和 · 阅读面深一档', group: 'dark' },
  { id: 'darkgreen',  name: '暗调绿',   desc: '经典 CRT 深绿灰 · 老派护眼风', group: 'dark' },
  { id: 'amber',      name: '琥珀暖',   desc: '深棕咖啡壳 + 金橙 · 冬夜暖光感', group: 'dark' },
  { id: 'celadon',    name: '青瓷蓝',   desc: '低饱和海蓝灰 · 柔和商务风', group: 'dark' },
  { id: 'rose',       name: '玫瑰暮',   desc: '深粉紫暮色壳 · 低饱和不腻', group: 'dark' },
  // ---- 亮色系 ----
  { id: 'paper',      name: '午夜纸',   desc: '暖白纸感壳 · 与笔记/日志完全统一', group: 'light' },
  { id: 'dawn',       name: '晨雾蓝',   desc: '冷调浅蓝灰 · 清爽办公风', group: 'light' },
  { id: 'mint',       name: '薄荷青',   desc: '浅青绿 · 淡雅护眼', group: 'light' },
  { id: 'apricot',    name: '暖杏',     desc: '暖米黄 · 柔和不刺眼', group: 'light' },
];
// 亮色主题表：终端 xterm 换浅底深字 16 色、UI 深字按钮等逻辑共用
const LIGHT_THEMES = ['paper', 'dawn', 'mint', 'apricot'];

function _termThemeFor(id) {
  // 按主题变量重建 xterm 16 色（buildTerminal 与 applyTheme 共用）
  const cs = getComputedStyle(document.documentElement);
  const termBg = (cs.getPropertyValue('--term-bg') || '#1a1f2e').trim() || '#1a1f2e';
  const termFg = (cs.getPropertyValue('--term-fg') || '#d7d7d7').trim() || '#d7d7d7';
  const light = LIGHT_THEMES.includes(id);
  return {
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
}

function applyTheme(id, persist) {
  if (!THEMES.some(t => t.id === id)) id = 'deepblue';
  document.documentElement.setAttribute('data-theme', id);
  // 持久化走后端（跨端口稳定）；persist=false 用于启动读回，不回写
  if (persist) {
    try { fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({theme: id})}); } catch(_) {}
  }
  // 已打开的终端实时换色
  const theme = _termThemeFor(id);
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.term) { try { c.term.options.theme = theme; } catch(_) {} }
  }
  // Monaco 编辑器同步换深浅主题（未加载时静默，monaco-bridge 自行跳过）
  if (typeof monacoSyncTheme === 'function') monacoSyncTheme();
  // MD 预览面同步换肤（markdown-it 渲染走 CSS 变量，无需处理；此钩子留扩展位）
}

(async function initTheme() {
  // 启动：先默认（避免无样式闪烁），再从后端读上次主题
  let saved = 'deepblue';
  try {
    const r = await fetch('/api/theme');
    const j = await r.json();
    if (j.ok && j.theme) saved = j.theme;
  } catch(_) {}
  applyTheme(saved, false);

  const menu = $('themeMenu');
  function renderMenu() {
    const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
    menu.innerHTML = '';
    for (const [g, label] of [['dark', '暗色系'], ['light', '亮色系']]) {
      const head = document.createElement('div');
      head.className = 'theme-group-head';
      head.textContent = label;
      menu.appendChild(head);
      THEMES.filter(t => t.group === g).forEach(t => {
        const item = document.createElement('div');
        item.className = 'theme-item' + (t.id === cur ? ' active' : '');
        item.innerHTML = `<div class="theme-swatch" data-theme="${t.id}"></div>
          <div class="theme-info"><div class="name">${t.name}</div><div class="desc">${t.desc}</div></div>
          ${t.id === cur ? '<span class="theme-check">✓</span>' : ''}`;
        item.onclick = () => { applyTheme(t.id, true); renderMenu(); showBanner('已切换主题：' + t.name); };
        menu.appendChild(item);
      });
    }
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
