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
  { id: 'dracula',    name: '德科拉',   desc: 'Dracula 官方配色 · 紫粉强调 · 经典暗色', group: 'dark' },
  // ---- 亮色系 ----
  { id: 'paper',      name: '午夜纸',   desc: '暖白纸感壳 · 与笔记/日志完全统一', group: 'light' },
  { id: 'dawn',       name: '晨雾蓝',   desc: '冷调浅蓝灰 · 清爽办公风', group: 'light' },
  { id: 'mint',       name: '薄荷青',   desc: '浅青绿 · 淡雅护眼', group: 'light' },
  { id: 'apricot',    name: '暖杏',     desc: '暖米黄 · 柔和不刺眼', group: 'light' },
  { id: 'lilac',      name: '藤萝紫',   desc: '浅紫灰壳 · 夜暮紫的亮色面', group: 'light' },
  { id: 'sakura',     name: '樱粉',     desc: '浅粉暖壳 · 玫瑰暮的亮色面', group: 'light' },
  { id: 'sage',       name: '鼠尾草',   desc: '灰绿纸感壳 · 暗调绿的亮色面', group: 'light' },
  { id: 'sky',        name: '晴空蓝',   desc: '浅晴空壳 · 青瓷蓝的亮色面', group: 'light' },
  // ---- 自定义 ----
  { id: 'custom',       name: '自定义',   desc: '暗色模式自由配 · 实时预览', group: 'dark' },
  { id: 'custom-light', name: '自定义',   desc: '亮色模式自由配 · 实时预览', group: 'light' },
];
// 亮色主题表：终端 xterm 换浅底深字 16 色、UI 深字按钮等逻辑共用
const LIGHT_THEMES = ['paper', 'dawn', 'mint', 'apricot', 'lilac', 'sakura', 'sage', 'sky'];

// ---- 自定义主题（v2.25）----
// 调色数据（核心 CSS 变量 + 亮暗标志）存 config.json（/api/theme 的
// custom_theme 键，跨端口稳定）。应用 = 注入 <style> 覆盖
// html[data-theme="custom"] 的变量；未设置的变量自然继承 :root 兜底。
let _customData = null;   // {bg-deep:'#..', ..., light:bool}；null=未加载
const CT_FIELDS = [
  ['bg-deep', '壳体最深底'], ['bg', '主底'], ['bg-panel', '面板底'],
  ['bg-card', '卡片底'], ['bg-input', '输入框底'], ['border', '边框'],
  ['fg', '正文文字'], ['fg-bright', '高亮文字'], ['muted', '弱化文字'],
  ['accent', '强调色'], ['accent-2', '强调色 2'],
  ['term-bg', '终端底色'], ['term-fg', '终端文字'],
];
function _isLight(id) {
  if (id === 'custom') return !!((_customData || {}).light);
  return LIGHT_THEMES.includes(id);
}
function _customApply() {
  let st = document.getElementById('customThemeStyle');
  if (!st) { st = document.createElement('style'); st.id = 'customThemeStyle'; document.head.appendChild(st); }
  const d = _customData || {};
  // harness 语义色（工具行类型/状态徽章/diff）跟随亮暗：亮色自定义注入压暗版，
  // 否则落回暗色系默认——与内置亮色主题（GitHub Light 调色板）保持一致
  const hLight = d.light ? ('--h-sky:#0550ae;--h-green:#1a7f37;--h-amber:#9a6700;' +
    '--h-violet:#8250df;--h-indigo:#6639ba;--h-purple:#9146c9;' +
    '--h-run:#0969da;--h-ok:#1a7f37;--h-err:#cf222e;--h-warn:#9a6700;') : '';
  st.textContent = 'html[data-theme="custom"]{' +
    CT_FIELDS.map(([k]) => d[k] ? `--${k}:${d[k]};` : '').join('') + hLight + '}';
}
function _customSaveRemote() {
  try { fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({custom_theme: _customData || {}})}); } catch(_) {}
}

function _termThemeFor(id) {
  // 按主题变量重建 xterm 16 色（buildTerminal 与 applyTheme 共用）
  const cs = getComputedStyle(document.documentElement);
  const termBg = (cs.getPropertyValue('--term-bg') || '#1a1f2e').trim() || '#1a1f2e';
  const termFg = (cs.getPropertyValue('--term-fg') || '#d7d7d7').trim() || '#d7d7d7';
  const light = _isLight(id);
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

let _themeFxTimer = 0;
function applyTheme(id, persist) {
  // v2.25：亮色自定义入口归一到 custom（同一份调色数据，light 标志决定行为）
  if (id === 'custom-light') id = 'custom';
  if (!THEMES.some(t => t.id === id)) id = 'deepblue';
  if (id === 'custom') _customApply();   // 先注入变量再挂属性，xterm 读取即生效
  document.documentElement.setAttribute('data-theme', id);   // 立即切（视觉即时）
  // 持久化走后端（跨端口稳定）；persist=false 用于启动读回，不回写
  if (persist) {
    try { fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({theme: id})}); } catch(_) {}
  }
  // v2.25：重活去抖——整窗 CSS 变量重算 + 全部已开终端重绘 + Monaco 换肤，
  // 大 DOM 下单次几百 ms，连续切换必把主线程打满（用户实测「连续切换卡死，
  // 必现」）。150ms 内只执行最后一次的整套重活。
  clearTimeout(_themeFxTimer);
  _themeFxTimer = setTimeout(() => {
    const theme = _termThemeFor(id);
    // 已打开的终端实时换色
    for (const pid in connections) {
      const c = connections[pid];
      if (c && c.term) {
        try { c.term.options.theme = theme; } catch(_) {}
        // 关键词高亮 decoration 是注册时定死的色——换主题后旧色不再对比
        // 足够（亮绿/亮青在浅底瞎），全清 + 重扫按新主题变量重新着色
        try {
          (c.kwDecorations || []).forEach(d => { try { d.dispose(); } catch(e){} });
          c.kwDecorations = [];
          c.kwDecorLastRow = 0;
          if (typeof highlightNewKw === 'function') highlightNewKw(c);
        } catch(_) {}
      }
    }
    // 活跃 claude 会话跟随换肤：改写其 --settings 临时文件，Claude 热重载立即重绘
    if (typeof connections !== 'undefined') {
      const hasClaude = Object.values(connections).some(c => c && c.meta && c.meta.kind === 'claude');
      if (hasClaude) {
        try {
          fetch('/api/claude_theme', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({light: _isLight(id)})}).catch(() => {});
        } catch(_) {}
      }
    }
    // Monaco 编辑器同步换深浅主题（未加载时静默，monaco-bridge 自行跳过）
    if (typeof monacoSyncTheme === 'function') monacoSyncTheme();
  }, 150);
  // MD 预览面同步换肤（markdown-it 渲染走 CSS 变量，无需处理；此钩子留扩展位）
}

// ---- 字号/缩放（config term_keys）----
// termFontSize：xterm 终端字号（新开终端用它实例化；已开终端实时热调）
// uiZoom：界面整体缩放百分比（body.zoom——布局级缩放，px 等比折算零破坏）
let termFontSize = 13;
let uiZoom = 100;
function applyFontSettings(termFs, zoom, persist) {
  termFontSize = termFs; uiZoom = zoom;
  try { document.body.style.zoom = zoom + '%'; } catch(_) {}
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.term) { try { c.term.options.fontSize = termFs; } catch(_) {} }
    if (c && c.term && typeof c._fitTerm === 'function') { try { c._fitTerm(); } catch(_) {} }
  }
  if (persist) {
    try { fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({term_keys: {
        right_action: (window._tkRightAction || 'ctrl_menu'),
        auto_copy: !!window._tkAutoCopy,
        term_font_size: termFs, ui_zoom: zoom}})}); } catch(_) {}
  }
}

(async function initTheme() {
  // 启动：先默认（避免无样式闪烁），再从后端读上次主题
  let saved = 'deepblue';
  try {
    const r = await fetch('/api/theme');
    const j = await r.json();
    if (j.ok && j.theme) saved = j.theme;
    if (j.ok && j.custom_theme && typeof j.custom_theme === 'object') _customData = j.custom_theme;
    if (j.ok && j.term_keys) {
      window._tkRightAction = j.term_keys.right_action || 'ctrl_menu';
      window._tkAutoCopy = !!j.term_keys.auto_copy;
      // 字号/缩放启动应用（不回写）
      applyFontSettings(j.term_keys.term_font_size || 13, j.term_keys.ui_zoom || 100, false);
    }
  } catch(_) {}
  applyTheme(saved, false);

  // Ctrl+= / Ctrl+- （Ctrl+'+'/'-'）调终端字号；Ctrl+0 恢复默认。
  // 只在无输入焦点劫持（input/textarea/contenteditable）时生效，普通终端/页面通用。
  document.addEventListener('keydown', e => {
    if (!e.ctrlKey || e.altKey || e.shiftKey || e.metaKey) return;
    const ae = document.activeElement;
    const typing = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' ||
                          (ae.tagName === 'DIV' && ae.isContentEditable));
    if (typing) return;   // 输入框里 Ctrl+=/- 可能是编辑意图（且 Monaco/xterm 捕获不到这里）
    let d = 0;
    if (e.key === '+' || e.key === '=') d = 1;
    else if (e.key === '-' || e.key === '_') d = -1;
    else if (e.key === '0') { applyFontSettings(13, 100, true); e.preventDefault(); return; }
    else return;
    const fs = Math.max(10, Math.min(24, termFontSize + d));
    if (fs === termFontSize) return;
    applyFontSettings(fs, uiZoom, true);
    e.preventDefault();
  });

  // a278R（用户实锤：旧换肤弹窗死代码清掉）：renderMenu/themeMenu/btnTheme
  // 整块退役——主题入口已迁设置面板「外观」子页（settings.js），顶栏按钮
  // 早已移除，零外部消费者（grep 实证）。性能模式开关也已迁设置面板。
})();

// ---- 自定义主题调色面板（v2.25）----
// 实时预览：任何颜色改动立即注入变量（data-theme=custom 时所见即所得）；
// 「保存」才持久化到 config.json。取色三入口：当前主题 / Dracula 示例 / 深空蓝默认。
const _CT_DRACULA = {   // 用户给的 MobaXterm.ini [Colors] 就是 Dracula：
  'bg-deep': '#191a21', 'bg': '#21222c', 'bg-panel': '#24252f', 'bg-card': '#282a36',
  'bg-input': '#21222c', 'border': '#44475a',
  'fg': '#f8f8f2', 'fg-bright': '#ffffff', 'muted': '#6272a4',
  'accent': '#bd93f9', 'accent-2': '#ff79c6',
  'term-bg': '#282a36', 'term-fg': '#f8f8f2', light: false };
function _openCustomPanel(forceLight) {
  // v2.25 修复：入口以「当前生效主题」为底板重新取色——之前只切 light 标志，
  // 颜色值还是上一套暗色调色，点「亮色自定义」界面依旧全暗（用户实测 bug）。
  // 入口亮暗意图与当前主题不符时，用对侧基底主题取色（亮=paper / 暗=deepblue）。
  const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
  const wantLight = forceLight === true;
  if (wantLight !== _isLight(cur)) {
    document.documentElement.setAttribute('data-theme', wantLight ? 'paper' : 'deepblue');
    _customPickCurrent();
    document.documentElement.setAttribute('data-theme', 'custom');
  } else {
    _customPickCurrent();
  }
  _customData.light = wantLight;
  _customApply();
  applyTheme('custom', true);
  const ov = document.createElement('div');
  ov.className = 'ct-overlay';
  const rows = CT_FIELDS.map(([k, name]) => `
    <div class="ct-row"><input type="color" name="ct_ck_${k}" data-ck="${k}" value="${esc(_customData[k] || '#000000')}">
      <input type="text" name="ct_ck_t_${k}" data-ck-t="${k}" spellcheck="false" value="${esc(_customData[k] || '')}" placeholder="--${k}">
      <span>${name}</span></div>`).join('');
  ov.innerHTML = `<div class="ct-panel">
    <div class="ct-title"><span>${ICO16.palette}</span> 自定义主题 <span style="font-size:11px;color:var(--muted);font-weight:400;">改动即时预览，保存后跨启动生效</span></div>
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin-bottom:6px;">
      <input type="checkbox" name="ct_light" data-ct-light${_customData.light ? ' checked' : ''}> 亮色模式（终端换浅底深字）
    </label>
    <div class="ct-grid">${rows}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
      <button class="btn ghost" data-ct-pick>取当前主题色</button>
      <button class="btn ghost" data-ct-dracula>Dracula 示例</button>
      <button class="btn ghost" data-ct-reset>恢复深空蓝默认</button>
      <button class="btn ghost" data-ct-ini><span>${ICO16.download}</span> 导入 MobaXterm ini</button>
    </div>
    <div data-ct-ini-box style="display:none;margin-top:8px;">
      <textarea name="ct_ini_txt" data-ct-ini-txt class="hg-vision-prompt" spellcheck="false" style="min-height:110px;"
        placeholder="把 MobaXterm.ini 的 [Colors] 段（或整份 ini）粘贴到这里，点「解析并应用」。至少要有 BackgroundColour 和 ForegroundColour 两行。"></textarea>
      <div style="display:flex;gap:8px;margin-top:6px;align-items:center;">
        <button class="btn ghost" data-ct-ini-go style="font-size:11px;">解析并应用</button>
        <span data-ct-ini-msg style="font-size:11px;color:var(--muted);"></span>
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-top:14px;align-items:center;">
      <button class="btn primary" data-ct-save><span>${ICO16.save}</span> 保存主题</button>
      <span class="ct-msg" style="font-size:11px;color:var(--muted);"></span>
    </div>
  </div>`;
  document.body.appendChild(ov);
  ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
  const msg = ov.querySelector('.ct-msg');
  const applyLive = () => {
    _customApply();
    if ((document.documentElement.getAttribute('data-theme') || '') === 'custom') {
      const t = _termThemeFor('custom');
      for (const pid in connections) {
        const c = connections[pid];
        if (c && c.term) { try { c.term.options.theme = t; } catch(_) {} }
      }
    }
  };
  ov.querySelectorAll('[data-ck]').forEach(inp => {
    inp.addEventListener('input', () => {
      _customData[inp.dataset.ck] = inp.value;
      const t = ov.querySelector(`[data-ck-t="${inp.dataset.ck}"]`);
      if (t) t.value = inp.value;
      applyLive();
    });
  });
  ov.querySelectorAll('[data-ck-t]').forEach(t => {
    t.addEventListener('change', () => {
      const v = t.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(v)) {
        _customData[t.dataset.ckT] = v;
        const c = ov.querySelector(`[data-ck="${t.dataset.ckT}"]`);
        if (c) c.value = v;
        applyLive();
      }
    });
  });
  ov.querySelector('[data-ct-light]').addEventListener('change', e => {
    _customData.light = e.target.checked; applyLive();
  });
  const fill = d => {
    _customData = { ...d };
    ov.querySelectorAll('[data-ck]').forEach(inp => {
      inp.value = _customData[inp.dataset.ck] || '#000000';
      const t = ov.querySelector(`[data-ck-t="${inp.dataset.ck}"]`);
      if (t) t.value = _customData[inp.dataset.ck] || '';
    });
    ov.querySelector('[data-ct-light]').checked = !!_customData.light;
    applyLive();
  };
  ov.querySelector('[data-ct-pick]').onclick = () => { _customPickCurrent(); fill(_customData); };
  ov.querySelector('[data-ct-dracula]').onclick = () => fill(_CT_DRACULA);
  // ---- MobaXterm ini 导入：解析 [Colors] 段，底/字直取，其余壳体变量按底色派生 ----
  const iniBox = ov.querySelector('[data-ct-ini-box]');
  ov.querySelector('[data-ct-ini]').onclick = () => {
    iniBox.style.display = iniBox.style.display === 'none' ? '' : 'none';
  };
  ov.querySelector('[data-ct-ini-go]').onclick = () => {
    const msg = ov.querySelector('[data-ct-ini-msg]');
    const kv = {};
    (ov.querySelector('[data-ct-ini-txt]').value || '').split(/\r?\n/).forEach(line => {
      const mm = line.match(/^\s*([A-Za-z]+)\s*=\s*([0-9,\s]+|#[0-9a-fA-F]{6})\s*$/);
      if (mm) kv[mm[1]] = mm[2].trim();
    });
    const rgb = (s) => {
      if (!s) return null;
      if (s[0] === '#') return s.toLowerCase();
      const p = s.split(',').map(x => parseInt(x.trim(), 10));
      if (p.length !== 3 || p.some(isNaN)) return null;
      return '#' + p.map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('');
    };
    const shade = (hex, f) => {
      const n = parseInt(hex.slice(1), 16);
      const ch = v => Math.max(0, Math.min(255, Math.round(v * f))).toString(16).padStart(2, '0');
      return '#' + [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(ch).join('');
    };
    const mix = (a, b, t) => {
      const na = parseInt(a.slice(1), 16), nb = parseInt(b.slice(1), 16);
      const ch = (va, vb) => Math.round(va + (vb - va) * t).toString(16).padStart(2, '0');
      return '#' + [0, 1, 2].map(i => ch((na >> (8 * (2 - i))) & 255, (nb >> (8 * (2 - i))) & 255)).join('');
    };
    const bg = rgb(kv.BackgroundColour), fg = rgb(kv.ForegroundColour);
    if (!bg || !fg) { msg.textContent = '✗ 没找到 BackgroundColour / ForegroundColour 两行'; return; }
    const mag = rgb(kv.Magenta) || rgb(kv.BoldMagenta) || '#bd93f9';
    const pur = rgb(kv.BoldBlue) || rgb(kv.Blue) || mag;
    const d = _customData;
    d['term-bg'] = bg; d['term-fg'] = fg;
    d['bg-card'] = bg; d['bg'] = mix(bg, '#000000', 0.12); d['bg-deep'] = mix(bg, '#000000', 0.35);
    d['bg-panel'] = mix(bg, '#000000', 0.06); d['bg-input'] = mix(bg, '#000000', 0.04);
    d['border'] = mix(bg, fg, 0.22);
    d['fg'] = fg; d['fg-bright'] = fg;
    d['muted'] = mix(fg, bg, 0.45);
    d['accent'] = mag; d['accent-2'] = pur;
    d.light = false;
    fill(d);
    msg.textContent = '✓ 已按 ini 配色应用——满意后点「保存主题」持久化';
  };
  ov.querySelector('[data-ct-reset]').onclick = () => {
    document.documentElement.setAttribute('data-theme', 'deepblue');
    _customPickCurrent();
    document.documentElement.setAttribute('data-theme', 'custom');
    fill(_customData);
  };
  ov.querySelector('[data-ct-save]').onclick = () => {
    _customSaveRemote();
    msg.textContent = '已保存——下次启动自动应用';
    showBanner('自定义主题已保存', 2500);
  };
}
function _customPickCurrent() {
  // 从当前生效主题读核心变量作起点（用户在喜欢的主题上微调，不从零开始）
  const cs = getComputedStyle(document.documentElement);
  const d = { light: _isLight(document.documentElement.getAttribute('data-theme') || 'deepblue') };
  CT_FIELDS.forEach(([k]) => {
    const v = (cs.getPropertyValue('--' + k) || '').trim();
    if (/^#[0-9a-fA-F]{6}$/i.test(v)) d[k] = v.toLowerCase();
  });
  _customData = d;
}
