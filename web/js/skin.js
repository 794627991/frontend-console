// ============================================================
// 风格维度（v4.1 批次1）：与 data-theme（配色）正交的第二维度。
// 桥接方案（用户拍板）：style.css 主体零改动，全部形态/装饰样式在
// skins.css 以 html[data-style] 覆盖实现，本文件只做机制——挂属性、
// 联动配色、持久化。
//
// 联动策略（教训修正版）：联动只发生在「点击切风格」那一刻（一次性
// 动作）——切入非 default 风格时带配套配色（applyTheme 现成通道白嫖
// 三件事：xterm 16 色亮暗、Monaco 深浅、claude 会话热重载），此后
// 换色完全自由；启动恢复不做联动（config 里 theme 已是联动后或用户
// 后来手选的值，强拉配套色会把用户的选择覆盖掉——首版实锤）。
// 切回 default 恢复「切入前配色」，但用户在风格期间手动换过色则不
// 恢复（尊重最新选择，靠包装 applyTheme 感知手动操作）。
// 持久化搭 /api/theme 顺车（config.json style 键；localStorage 按
// origin 隔离不可用——Flask 随机端口，theme.js 注释有实锤）。
// ============================================================
const STYLES = [
  { id: 'default', name: '默认',   desc: '现有科技风（基准形态）', theme: '' },
  { id: 'swiss',   name: '瑞士排版', desc: '白底黑字 · 全直角 · 粗黑结构线 · 红点缀', theme: 'paper' },
  { id: 'aurora',  name: '极光玻璃', desc: '深空底 · 流动极光 · 玻璃卡片半透明', theme: 'onedark' },
  { id: 'crt',     name: '磷光终端', desc: '扫描线 · 暗角 · 等宽 · 磷光辉光', theme: 'darkgreen' },
  { id: 'synth',   name: '合成波',  desc: '暗夜紫 · 底缘渐隐网格 · 霓虹辉光', theme: 'onedark' },
  { id: 'hud',     name: '航电 HUD', desc: '琥珀单色 · 等宽全 UI · 刻度尺 · 扫描带', theme: 'amber' },
  { id: 'brutal',  name: '新粗野',  desc: '全直角 · 粗黑边 · 硬位移阴影 · 黄底黑字钮', theme: 'apricot' },
  { id: 'instrument', name: '仪器面板', desc: '金属渐变 · LED 呼吸 · 物理按压 · 丝印字', theme: 'warmgray' },
  { id: 'ink',     name: '墨韵',   desc: '淡墨边 · 朱印 logo · 按钮宽字距', theme: 'paper' },
];
let _curStyle = 'default';
let _prevTheme = null;      // 切入风格那一刻的配色；切回 default 恢复（见包装）
let _skinLinking = false;   // 联动切色标志——区分本模块的联动与用户手动换色

// 包装 applyTheme：用户手动换色（非本模块联动）即解除旧配色记忆，
// 「切回 default 恢复切入前配色」只对没动过配色的会话成立。
// theme.js 顶层 function 声明挂在全局对象上，后加载的本文件重赋值
// 后，theme.js/settings.js 内部裸调用同样走到包装（词法解析到全局）。
const _applyThemeCore = window.applyTheme;
window.applyTheme = function (id, persist) {
  if (!_skinLinking) _prevTheme = null;
  return _applyThemeCore(id, persist);
};

function applyStyle(id, persist) {
  if (!STYLES.some(s => s.id === id)) id = 'default';
  _curStyle = id;
  const st = STYLES.find(s => s.id === id);
  if (id === 'default') {
    document.documentElement.removeAttribute('data-style');
    if (_prevTheme) {
      _skinLinking = true;
      _applyThemeCore(_prevTheme, true);
      _skinLinking = false;
      _prevTheme = null;
    }
  } else {
    document.documentElement.setAttribute('data-style', id);
    if (st.theme) {
      const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
      if (cur !== st.theme) {
        if (!_prevTheme) _prevTheme = cur;
        _skinLinking = true;
        _applyThemeCore(st.theme, true);   // 联动即持久化，重启 theme/style 一致
        _skinLinking = false;
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

// 启动恢复：只挂风格属性，不联动配色（见联动策略）。
(async function initStyle() {
  let style = '';
  try {
    const r = await fetch('/api/theme');
    const j = await r.json();
    if (j.ok && j.style) style = j.style;
  } catch (_) {}
  if (!style || style === 'default') return;
  // 等 theme.js initTheme 先挂好 data-theme 再挂风格：两份 async fetch
  // 竞速，skin 先挂会让「切入前配色」误记为存档前的默认值
  for (let i = 0; i < 60; i++) {
    if (document.documentElement.hasAttribute('data-theme')) break;
    await new Promise(res => setTimeout(res, 50));
  }
  applyStyle(style, false);
})();
