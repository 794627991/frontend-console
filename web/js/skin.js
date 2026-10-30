// ============================================================
// 风格维度（v4.1 批次1）：与 data-theme（配色）正交的第二维度。
// 桥接方案（用户拍板）：style.css 主体零改动，全部形态/装饰样式在
// skins.css 以 html[data-style] 覆盖实现，本文件只做机制——挂属性、
// 联动配色、持久化。
//
// 联动策略（一石三鸟）：非 default 风格切换时自动切配套配色主题
// （applyTheme 现成通道白嫖三件事：xterm 16 色亮暗由 _isLight 判定、
// Monaco 深浅、claude 会话 --settings 热重载全部随之）。终端配色
// 读 computed --term-bg/--term-fg（skins.css 变量覆盖即生效），本
// 文件不碰终端。用户切风格后仍可单独换配色（换色不动风格）。
// 持久化搭 /api/theme 顺车（config.json style 键；localStorage 按
// origin 隔离不可用——Flask 随机端口，theme.js 注释有实锤）。
// ============================================================
const STYLES = [
  { id: 'default', name: '默认',   desc: '现有科技风（基准形态）', theme: '' },
  { id: 'swiss',   name: '瑞士排版', desc: '白底黑字 · 全直角 · 粗黑结构线 · 红点缀', theme: 'paper' },
  // 批次2：aurora 极光玻璃 / crt 磷光终端 / synth 合成波 / hud 航电
  // 批次3：brutal 新粗野 / instrument 仪器面板 / ink 墨韵（逐套追加）
];
let _curStyle = 'default';
let _prevTheme = null;   // 切入风格那一刻的配色；切回 default 恢复（回到切入前状态）

function applyStyle(id, persist) {
  if (!STYLES.some(s => s.id === id)) id = 'default';
  _curStyle = id;
  const st = STYLES.find(s => s.id === id);
  if (id === 'default') {
    document.documentElement.removeAttribute('data-style');
    if (_prevTheme && typeof applyTheme === 'function') {
      applyTheme(_prevTheme, true);
      _prevTheme = null;
    }
  } else {
    document.documentElement.setAttribute('data-style', id);
    if (st.theme && typeof applyTheme === 'function') {
      const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
      if (cur !== st.theme) {
        if (!_prevTheme) _prevTheme = cur;
        applyTheme(st.theme, true);
      }
    }
  }
  if (persist) {
    try {
      fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ style: id }) });
    } catch (_) {}
  }
}

// 启动恢复：与 theme.js initTheme 并发（两份 async fetch 同源竞速）——
// 必须等 initTheme 把 data-theme 挂上之后再联动，否则本侧先挂
// data-style=swiss 联动切 paper，theme 后到会把配色覆盖回深色存档
// （瑞士形态 + 深空蓝配色的崩坏组合）。轮询等属性出现，上限 3s。
(async function initStyle() {
  let style = '';
  try {
    const r = await fetch('/api/theme');
    const j = await r.json();
    if (j.ok && j.style) style = j.style;
  } catch (_) {}
  if (!style || style === 'default') return;
  for (let i = 0; i < 60; i++) {
    if (document.documentElement.hasAttribute('data-theme')) break;
    await new Promise(res => setTimeout(res, 50));
  }
  applyStyle(style, false);
})();
