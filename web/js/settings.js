// ============================================================
// 设置：顶栏机器人 logo 即功能按钮，点开设置弹窗。
// 左侧导航分区：数据目录（查看/校验/迁移）、外观主题（配色切换）。
// 首次启动（config 无 data_dir_prompted）弹引导，默认建议 D:\前端控制台。
// 迁移铁律：先复制后切换，失败不切换——数据绝不丢。
// ============================================================

function _ddFmtSize(n) {
  if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

// ---- 设置弹窗骨架：左导航 + 右内容区（分区懒渲染）----
const _SET_SECTIONS = [
  { id: 'term',  icon: ICO16.keyboard, name: '终端设置', desc: '字号 / 快捷键映射 / 自动复制' },
  { id: 'appearance', icon: ICO16.palette, name: '外观', desc: '换肤 / 界面缩放' },
  { id: 'api',   icon: ICO16.key, name: 'API 配置', desc: 'Claude API Token / settings.json' },
  { id: 'update', icon: ICO16.upload, name: '关于与升级', desc: '版本 / 检查更新 / 升级分发服务' },
  { id: 'resources', icon: ICO16.puzzle, name: '外部依赖安装', desc: '检测 / 用离线资源包重装六项依赖' },
  { id: 'data',  icon: ICO16.folder, name: '数据目录', desc: '日志 / 笔记 / 缓存的位置与迁移' },
  { id: 'assoc', icon: ICO16.link, name: '文件关联', desc: '接管/还原 txt 等文本文件的双击打开方式' },
  { id: 'help',  icon: ICO16.help, name: '帮助', desc: 'README 使用手册 / 常见问题' },
];

function _stModal() {
  let m = $('settingsModal');
  if (m) return m;
  m = document.createElement('div');
  m.className = 'modal';
  m.id = 'settingsModal';
  m.innerHTML = `
    <div class="box set-box">
      <div class="head">
        <strong><span style="vertical-align:-2.5px">${ICO16.gear}</span> 设置</strong>
        <div class="head-actions"><button class="btn ghost icon-btn" id="stClose">✕</button></div>
      </div>
      <div class="set-body">
        <div class="set-nav" id="stNav"></div>
        <div class="set-pane" id="stPane"></div>
      </div>
    </div>`;
  document.body.appendChild(m);
  m.querySelector('#stClose').onclick = () => m.classList.remove('show');
  // 左导航：分区按钮（data-dir 面板不再独立存在，全部收纳于此）
  const nav = m.querySelector('#stNav');
  _SET_SECTIONS.forEach(sec => {
    const b = document.createElement('div');
    b.className = 'set-nav-item';
    b.dataset.sec = sec.id;
    b.innerHTML = `<span class="set-nav-icon">${sec.icon}</span>
      <div class="set-nav-txt"><div class="name">${sec.name}</div><div class="desc">${sec.desc}</div></div>`;
    b.onclick = () => _stShowSection(m, sec.id);
    nav.appendChild(b);
  });
  return m;
}

function _stShowSection(m, sec) {
  // 记住分区：重开设置弹窗时回到上次所在处（曾每次重开都落到终端设置，
  // 用户在 API 面板配到一半被打断，回来要重新找入口，实锤「莫名跳转」）
  try { localStorage.setItem('fc_st_sec', sec); } catch(_) {}
  m.querySelectorAll('.set-nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.sec === sec));
  const pane = m.querySelector('#stPane');
  if (sec === 'appearance') _stRenderAppearancePane(pane);
  else if (sec === 'api') _stRenderApiPane(pane);
  else if (sec === 'update') _stRenderUpdatePane(pane);
  // 'reinstall' 是旧分区 id 的别名——localStorage.fc_st_sec 里存着老值，
  // 不做映射的话老用户重开设置会落到兜底的外观页，找不到原来的入口
  else if (sec === 'resources' || sec === 'reinstall') _stRenderResourcesPane(pane);
  else if (sec === 'term') _stRenderTermKeysPane(pane);
  else if (sec === 'data') _stRenderDataPane(pane);
  else if (sec === 'assoc') _stRenderAssocPane(pane);
  else if (sec === 'help') _stRenderHelpPane(pane);
  else _stRenderAppearancePane(pane);   // 未知 id 兜底到外观
}

// ---- 帮助子页（顶栏 ？ 按钮挪来；最底部分区）----
function _stRenderHelpPane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-label">帮助文档</div>
      <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;">
        <button class="btn primary" id="hpOpenReadme"><span style="vertical-align:-2.5px">${ICO16.book}</span> 打开 README 使用手册</button>
      </div>
      <div class="dd-sub">工具内直接打开（markdown 渲染），含快速上手 / 全功能说明 / 常见问题。</div>
      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">常见问题速查</div>
        <div class="dd-sub" style="margin-top:6px;line-height:2;">
          • 点 ✕ 程序没退出？——默认「关闭到托盘」，单击托盘图标唤出，右键托盘选退出才是真退（设置→终端设置可关）<br>
          • 粘贴没反应？——任何程序复制的内容都能贴；多行会先弹确认框<br>
          • 终端字号调不了？——焦点要在终端里，Ctrl + = / Ctrl + -<br>
          • Telnet 别人连不上？——多数设备 telnet 只支持一个会话，设备固件限制<br>
          • 日志在哪？——工具目录 serial_logs/（设置→数据目录可查/迁移）
        </div>
      </div>
    </div>`;
  pane.querySelector('#hpOpenReadme').onclick = () => {
    fetch('/api/help_readme').then(r => r.json()).then(j => {
      if (j.ok && j.path) openFileSmart(j.path, 'auto');
      else showBanner('未找到 README.md', 3000, true);
    }).catch(() => showBanner('帮助打开失败', 3000, true));
  };
}

// ---- 外观子页：风格（v4.1 桥接维度）+ 换肤（原 theme 页整块搬入）+ 界面缩放 ----
function _stRenderAppearancePane(pane) {
  pane.innerHTML = `<div class="dd-body"><div class="dd-label">界面风格</div>
    <div class="set-style-row" id="stStyleRow"></div>
    <div class="dd-note">形态/质感维度（圆角·阴影·字体·装饰），叠加在配色之上即时生效；切风格自动带配套配色，之后仍可单独换色。</div>
    <div class="dd-label" style="margin-top:10px">配色主题</div><div class="set-theme-grid" id="stThemeGrid"></div>
    <div class="dd-note">整窗即时换色（终端/编辑器/阅读面同步）；顶栏「🎨 换肤」按钮同样可用。</div>
    <div class="dd-cur" style="margin-top:8px;">
      <div class="dd-label">界面缩放</div>
      <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
        <button class="btn ghost" id="apZoomOut" title="缩小">－</button>
        <span id="apZoomVal" style="font-family:var(--font-mono);min-width:56px;text-align:center;">100%</span>
        <button class="btn ghost" id="apZoomIn" title="放大">＋</button>
        <button class="btn ghost" id="apZoomReset" title="恢复 100%">↺ 重置</button>
      </div>
      <div class="dd-sub">整个界面等比缩放（80%–130%）。也可用 Ctrl+= / Ctrl+- 调终端字号，Ctrl+0 全部恢复默认。</div>
    </div>
    <div class="dd-cur" style="margin-top:8px;">
      <div class="dd-label">性能模式</div>
      <div class="dd-row" style="margin-top:6px;">
        <button class="btn ghost" id="apPerfToggle" style="width:100%;text-align:left;padding:8px 12px;"></button>
      </div>
      <div class="dd-sub">关闭极光玻璃的毛玻璃/光斑动画（虚机 GPU 推荐）——显著降低每帧 GPU 合成开销。</div>
    </div>
    <div class="dd-cur" style="margin-top:8px;">
      <div class="dd-label">Tab 模式</div>
      <div class="dd-row" style="display:flex;gap:6px;margin-top:6px;">
        <button class="btn ghost" id="apTabFlat" style="flex:1;"></button>
        <button class="btn ghost" id="apTabDrawer" style="flex:1;"></button>
      </div>
      <div class="dd-sub">平铺=Chrome 式自动收缩+溢出分组下拉；抽屉=同类 tab 收进一个抽屉（点开选择），常用 tab 可右键固定常驻。</div>
    </div>
    <div class="dd-cur" style="margin-top:8px;">
      <div class="dd-label">MD 预览主题</div>
      <div class="dd-row" style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;" id="stMdPvRow"></div>
      <div class="dd-sub">Markdown 预览面板的配色（独立于全局主题，随时可改）。</div>
    </div></div>`;
  const grid = pane.querySelector('#stThemeGrid');
  // 风格行（v4.1 桥接层 skin.js）：逐个胶囊，点选即切（联动配套配色）
  const styleRow = pane.querySelector('#stStyleRow');
  if (styleRow && typeof STYLES !== 'undefined') {
    const curStyle = document.documentElement.getAttribute('data-style') || 'default';
    STYLES.forEach(s => {
      const b = document.createElement('button');
      b.className = 'btn ghost style-chip' + (s.id === curStyle ? ' active' : '');
      b.textContent = s.name;
      b.title = s.desc;
      b.onclick = () => {
        if (typeof applyStyle !== 'function') return;
        applyStyle(s.id, true);
        showBanner(s.id === 'default' ? '已切回默认风格' : '已切换风格：' + s.name);
        _stRenderAppearancePane(pane);   // 重渲染刷新选中态与配套配色高亮
      };
      styleRow.appendChild(b);
    });
  }
  // a279 批1：MD 预览主题选择器（auto/dark/light/paper）
  const mdPvRow = pane.querySelector('#stMdPvRow');
  if (mdPvRow && typeof _mdPvSetTheme === 'function') {
    const opts = [
      { id: 'auto',  name: '跟随全局' },
      { id: 'dark',  name: '暗色' },
      { id: 'light', name: '亮色' },
      { id: 'paper', name: '护眼纸色' },
    ];
    // 当前值：从 editor.js 的全局变量读（比 DOM 查类更准——可能还没打开过 .md）
    const cur = opts.find(o => o.id === (_mdPvTheme || 'auto')) ? (_mdPvTheme || 'auto') : 'auto';
    opts.forEach(o => {
      const b = document.createElement('button');
      b.className = 'btn ghost style-chip' + (o.id === cur ? ' active' : '');
      b.textContent = o.name;
      b.onclick = () => {
        _mdPvSetTheme(o.id);
        try { fetch('/api/theme', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ md_preview_theme: o.id }) }); } catch (_) {}
        showBanner('MD 预览主题：' + o.name);
        _stRenderAppearancePane(pane);
      };
      mdPvRow.appendChild(b);
    });
  }
  const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
  // a278 性能模式开关（极光玻璃 GPU 合成优化）
  const perfBtn = pane.querySelector('#apPerfToggle');
  if (perfBtn && typeof togglePerfMode === 'function') {
    const syncPerf = () => {
      const on = document.documentElement.hasAttribute('data-perf');
      perfBtn.innerHTML = (window.ICO16 ? (on ? ICO16.zap : ICO16.eyeOff) + ' ' : '')
        + (on ? '<b style="color:var(--accent)">已开启</b>' : '已关闭')
        + '<small style="color:var(--muted);font-weight:400;">　' + (on ? '毛玻璃/光斑已关闭' : '点击关闭 GPU 密集特效') + '</small>';
    };
    perfBtn.onclick = () => { togglePerfMode(); syncPerf(); };
    syncPerf();
  }
  // a286 Tab 模式切换（平铺收缩 / 分组抽屉）
  const flatBtn = pane.querySelector('#apTabFlat'), drawerBtn = pane.querySelector('#apTabDrawer');
  if (flatBtn && drawerBtn && typeof window._tabSetMode === 'function') {
    const syncTabMode = () => {
      const m = window._tabGetMode ? window._tabGetMode() : 'flat';
      flatBtn.className = 'btn ghost' + (m === 'flat' ? ' active' : '');
      drawerBtn.className = 'btn ghost' + (m === 'drawer' ? ' active' : '');
      flatBtn.textContent = '平铺';
      drawerBtn.textContent = '分组抽屉';
    };
    flatBtn.onclick = () => { window._tabSetMode('flat'); syncTabMode(); };
    drawerBtn.onclick = () => { window._tabSetMode('drawer'); syncTabMode(); };
    syncTabMode();
  }
  const zoomVal = pane.querySelector('#apZoomVal');
  const syncZoom = () => { zoomVal.textContent = (typeof uiZoom === 'number' ? uiZoom : 100) + '%'; };
  syncZoom();
  const doZoom = (d) => {
    const z = Math.max(80, Math.min(130, (uiZoom || 100) + d));
    if (z === uiZoom) return;
    applyFontSettings(termFontSize, z, true);
    syncZoom();
  };
  pane.querySelector('#apZoomOut').onclick = () => doZoom(-5);
  pane.querySelector('#apZoomIn').onclick = () => doZoom(5);
  pane.querySelector('#apZoomReset').onclick = () => { applyFontSettings(13, 100, true); syncZoom(); };
  if (typeof THEMES === 'undefined') {
    grid.innerHTML = '<div class="dd-sub">主题模块未加载</div>';
    return;
  }
  // v2.25：两系并列 + 逐行对齐（grid 显式行定位，与换肤弹层同布局）
  const cols = document.createElement('div');
  cols.className = 'set-theme-cols';
  grid.appendChild(cols);
  const put = (el, row, colIdx) => {
    el.style.gridRow = String(row);
    el.style.gridColumn = colIdx === 0 ? '1' : '2';
    cols.appendChild(el);
  };
  // 自定义两入口沉底并肩：两列项数不同（暗 8 / 亮 9），按各自序号排会把
  // 暗色自定义留在倒数第二行、底部空一格（用户误读「暗色自定义没了」）
  const customRow = Math.max(
    THEMES.filter(t => t.group === 'dark').length,
    THEMES.filter(t => t.group === 'light').length) + 2;
  for (const [g, label] of [['dark', '暗色系'], ['light', '亮色系']]) {
    const colIdx = g === 'dark' ? 0 : 1;
    const head = document.createElement('div');
    head.className = 'set-theme-group';
    head.textContent = label;
    put(head, 1, colIdx);
    // active 判定：custom 家族按 light 标志归列（与换肤弹层同逻辑）
    const isCur = (t) => {
      if (cur === 'custom') {
        const lt = typeof _isLight === 'function' && _isLight('custom');
        return t.id === 'custom' ? !lt : t.id === 'custom-light' && lt;
      }
      return t.id === cur;
    };
    THEMES.filter(t => t.group === g).forEach((t, i) => {
      const isCustomEntry = t.id === 'custom' || t.id === 'custom-light';
      const item = document.createElement('div');
      item.className = 'theme-item' + (isCur(t) ? ' active' : '');
      item.innerHTML = `<div class="theme-swatch" data-theme="${t.id}"></div>
        <div class="theme-info"><div class="name">${t.name}</div><div class="desc">${t.desc}</div></div>
        ${isCur(t) ? '<span class="theme-check">✓</span>' : ''}`;
      item.onclick = () => {
        if (isCustomEntry) {
          applyTheme('custom', true);
          if (typeof _openCustomPanel === 'function') _openCustomPanel(t.id === 'custom-light');
          _stRenderAppearancePane(pane);
          return;
        }
        applyTheme(t.id, true);
        showBanner('已切换主题：' + t.name);
        _stRenderAppearancePane(pane);   // 重渲染刷新选中态
      };
      put(item, isCustomEntry ? customRow : i + 2, colIdx);
    });
  }
}

// ---- 终端设置子页：字号 + 右键行为 + 自动复制（config.json term_keys）----
const _TK_OPTIONS = [
  { v: 'ctrl_menu',  n: 'Ctrl + 右键 → 弹菜单', d: '默认。普通右键为 xterm 原生行为' },
  { v: 'right_menu', n: '右键 → 直接弹菜单', d: '不需按 Ctrl，单右键即出菜单' },
  { v: 'right_paste', n: '右键 → 直接粘贴', d: '单右键立即粘贴剪贴板（PuTTY 默认风格）' },
];
async function _stRenderTermKeysPane(pane) {
  let tk = { right_action: 'ctrl_menu', auto_copy: false, term_font_size: 13, ui_zoom: 100 };
  let closeToTray = true;
  let claudeUiMode = 'harness';
  let snipHk = 'ctrl+alt+a';
  // v3.5.310 可配置搜索快捷键（页面内 keydown，非系统热键）
  let docHk = 'ctrl+f';
  let notesHk = 'ctrl+alt+f';

  // a239 B3-P2: 探活令牌——await 期间用户切到别的分区时，本渲染的迟到
  // innerHTML 会整体覆盖新分区内容（左导航与右侧内容分裂）
  const _mySec = Symbol('termKeys');
  pane._stSec = _mySec;
  try {
    const j = await (await fetch('/api/theme')).json();
    if (pane._stSec !== _mySec) return;   // 已被别的分区渲染接管
    if (j.ok && j.term_keys) tk = j.term_keys;
    if (j.ok) closeToTray = j.close_to_tray !== false;   // 缺省=开（config 旧版无此键）
    if (j.ok && j.claude_ui_mode) claudeUiMode = j.claude_ui_mode;   // Claude 入口分派：harness=界面化 / cli=终端
    if (j.ok && typeof j.snip_hotkey === 'string') snipHk = j.snip_hotkey || '';
    if (j.ok && typeof j.doc_search_hotkey === 'string') docHk = j.doc_search_hotkey || 'ctrl+f';
    if (j.ok && typeof j.notes_search_hotkey === 'string') notesHk = j.notes_search_hotkey || 'ctrl+alt+f';
  } catch(_) {}
  if (pane._stSec !== _mySec) return;
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-label">终端设置</div>
      <div class="dd-sub">字号与快捷键行为。改动立即生效并持久保存。</div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">终端字号</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <button class="btn ghost" id="tkFontOut" title="缩小">－</button>
          <span id="tkFontVal" style="font-family:var(--font-mono);min-width:56px;text-align:center;">${Number(typeof termFontSize === 'number' ? termFontSize : tk.term_font_size) || 13} px</span>
          <button class="btn ghost" id="tkFontIn" title="放大">＋</button>
          <button class="btn ghost" id="tkFontReset" title="恢复 13px">↺ 重置</button>
        </div>
        <div class="dd-sub">10–24px，已开终端实时生效。快捷键：Ctrl+= 放大 / Ctrl+- 缩小 / Ctrl+0 恢复默认。</div>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">右键行为</div>
        <div class="dd-row" style="margin-top:6px;display:flex;flex-direction:column;gap:8px;">
          ${_TK_OPTIONS.map(o => `
            <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;">
              <input type="radio" name="tkRight" value="${o.v}" ${tk.right_action === o.v ? 'checked' : ''} style="margin-top:3px;">
              <span><span style="font-weight:600;">${o.n}</span><br><span style="color:var(--muted);font-size:12px;">${o.d}</span></span>
            </label>`).join('')}
        </div>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">选中自动复制</div>
        <label style="display:flex;align-items:center;gap:8px;margin-top:6px;cursor:pointer;">
          <input type="checkbox" id="tkAutoCopy" ${tk.auto_copy ? 'checked' : ''}>
          <span>鼠标选中终端文本后松开即自动复制（PuTTY 风格）</span>
        </label>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">固定快捷键（恒可用，不受上面配置影响）</div>
        <div class="dd-sub" style="margin-top:4px;">
          Ctrl+C 复制选中 / 发 ^C 中断　·　Ctrl+V 粘贴<br>
          Shift+右键 粘贴　·　Ctrl+右键 弹菜单（右键行为=ctrl_menu 时）　·　Ctrl+S 保存（编辑器）
        </div>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">截图快捷键（全局）</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <input type="text" id="snipHk" value="${esc(snipHk)}" spellcheck="false" readonly
                 placeholder="点击录制按键…"
                 style="flex:1;font-family:var(--font-mono);padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--fg);cursor:pointer;">
          <button class="btn ghost" id="snipHkClear" title="清空=禁用全局快捷键">清除</button>
        </div>
        <div class="dd-sub" style="margin-top:4px;">点击输入框后直接按想要的组合键即录制并生效（Esc 取消）。功能键 F1–F12 可单键；字母/数字键需带修饰（Ctrl/Alt/Shift/Win）。点「清除」禁用。</div>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">搜索快捷键</div>
        <div class="dd-sub" style="margin-top:4px;">改键立即生效（热更新，无需重启）。文档内搜索=当前日志/编辑器/终端/十六进制查看的查找；全库笔记搜索=跨全部笔记与文本文件检索（Ctrl+点击双链不受影响）。</div>
        <div class="dd-label" style="margin-top:10px;">文档内搜索（${esc(docHk)}）</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <input type="text" id="docHkInput" value="${esc(docHk)}" spellcheck="false" readonly
                 placeholder="点击录制按键…"
                 style="flex:1;font-family:var(--font-mono);padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--fg);cursor:pointer;">
        </div>
        <div class="dd-label" style="margin-top:10px;">全库笔记搜索（${esc(notesHk)}）</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <input type="text" id="notesHkInput" value="${esc(notesHk)}" spellcheck="false" readonly
                 placeholder="点击录制按键…"
                 style="flex:1;font-family:var(--font-mono);padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-input);color:var(--fg);cursor:pointer;">
        </div>
        <div class="dd-sub" style="margin-top:4px;">录制与截图快捷键同款（Esc 取消）。两键请勿设成相同组合——撞车时全库搜索（页面捕获层）优先。</div>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">Claude 打开方式</div>
        <div class="dd-row" style="margin-top:6px;display:flex;gap:16px;flex-wrap:wrap;">
          <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;">
            <input type="radio" name="cuMode" value="harness" ${claudeUiMode === 'harness' ? 'checked' : ''} style="margin-top:3px;">
            <span><span style="font-weight:600;">界面化对话</span><br><span style="color:var(--muted);font-size:12px;">点顶栏 Claude 开聊天界面：消息流 + 工具调用可视化（推荐）</span></span>
          </label>
          <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;">
            <input type="radio" name="cuMode" value="cli" ${claudeUiMode === 'cli' ? 'checked' : ''} style="margin-top:3px;">
            <span><span style="font-weight:600;">内嵌终端</span><br><span style="color:var(--muted);font-size:12px;">原方式：xterm 保真跑真实 CLI（Claude 面板恢复会话仍走终端）</span></span>
          </label>
        </div>
        <div class="dd-sub" style="margin-top:4px;">两种方式可随时切换；Claude 面板「恢复会话」始终走内嵌终端。</div>
      </div>
      <div class="dd-cur" style="margin-top:8px;">
        <div class="dd-label">关闭行为</div>
        <label style="display:flex;align-items:center;gap:8px;margin-top:6px;cursor:pointer;">
          <input type="checkbox" id="tkCloseToTray" ${closeToTray ? 'checked' : ''}>
          <span>点击窗口 ✕ 时最小化到系统托盘（单击托盘图标唤出，右键托盘可退出）</span>
        </label>
        <div class="dd-sub" style="margin-top:4px;">取消勾选则点 ✕ 直接退出程序。</div>
      </div>
      <div style="margin-top:8px;">
        <button class="btn primary" id="tkSave">保存</button>
      </div>
    </div>`;
  const fontVal = pane.querySelector('#tkFontVal');
  const syncFont = () => { fontVal.textContent = (termFontSize || 13) + ' px'; };
  syncFont();
  const doFont = (d) => {
    const fs = Math.max(10, Math.min(24, (termFontSize || 13) + d));
    if (fs === termFontSize) return;
    applyFontSettings(fs, uiZoom, false);   // 先热调预览（保存时才持久化）
    syncFont();
  };
  pane.querySelector('#tkFontOut').onclick = () => doFont(-1);
  pane.querySelector('#tkFontIn').onclick = () => doFont(1);
  pane.querySelector('#tkFontReset').onclick = () => { applyFontSettings(13, uiZoom, false); syncFont(); };
  pane.querySelector('#tkSave').onclick = async () => {
    const ra = pane.querySelector('input[name="tkRight"]:checked');
    const ac = pane.querySelector('#tkAutoCopy').checked;
    const ct = pane.querySelector('#tkCloseToTray').checked;
    const cu = pane.querySelector('input[name="cuMode"]:checked');
    try {
      const body = {term_keys: {right_action: ra ? ra.value : 'ctrl_menu', auto_copy: ac,
                                term_font_size: termFontSize, ui_zoom: uiZoom},
                    close_to_tray: ct};
      if (cu) body.claude_ui_mode = cu.value;   // Claude 入口分派（harness/cli）
      await fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body)});
      if (cu && typeof setClaudeUiMode === 'function') setClaudeUiMode(cu.value);   // 内存缓存同步，立即生效
      // 已开终端连接的配置热更新（下次 contextmenu 读 conn.termKeys）
      Object.values(connections).forEach(c => {
        if (c.termKeys) {
          c.termKeys.right_action = ra ? ra.value : 'ctrl_menu';
          c.termKeys.auto_copy = ac;
        }
      });
      showBanner('终端设置已保存');
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
  // v2.3.12 截图快捷键：录制式（点输入框 → 按组合键 → 即刻热替换注册，
  // 成功才落盘）。旧版手输 text 改 readonly——键名拼错/顺序不对全靠人肉，
  // 用户要求直接录按键。
  const _hkInput = pane.querySelector('#snipHk');
  const _hkApply = async (val) => {
    try {
      const r = await fetch('/api/theme', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({snip_hotkey: val})});
      const j = await r.json();
      if (j.ok) { snipHk = val; showBanner(val ? `截图快捷键已应用：${val}` : '截图快捷键已禁用'); }
      else { showBanner(j.err || '快捷键无效', 3000, true); _hkInput.value = snipHk; }
    } catch (e) { showBanner('应用失败：' + e, 3000, true); _hkInput.value = snipHk; }
  };
  if (_hkInput) {
    let _rec = false;
    const _setRec = (on) => {
      _rec = on;
      _hkInput.placeholder = on ? '按下组合键…（Esc 取消）' : '点击录制按键…';
      _hkInput.style.borderColor = on ? 'var(--accent, #4a9eff)' : 'var(--border)';
    };
    _hkInput.addEventListener('click', () => {
      if (_rec) return;
      _hkInput.value = '';
      _setRec(true);
      _hkInput.focus();
    });
    _hkInput.addEventListener('keydown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'Escape') { _hkInput.value = snipHk; _setRec(false); return; }
      const mod = [];
      if (e.ctrlKey) mod.push('ctrl');
      if (e.altKey) mod.push('alt');
      if (e.shiftKey) mod.push('shift');
      if (e.metaKey) mod.push('win');
      const k = (e.key || '').toLowerCase();
      const isFn = /^f([1-9]|1[0-2])$/.test(k);
      const isAlnum = /^[a-z0-9]$/.test(k);
      if (!isFn && !isAlnum) return;          // 只按修饰键/其他键：继续等
      if (isAlnum && !mod.length) {           // 裸字母/数字：提示后继续录
        _hkInput.value = '';
        _hkInput.placeholder = '字母/数字需搭配 Ctrl/Alt/Shift/Win…';
        return;
      }
      const combo = mod.concat([k]).join('+');
      _hkInput.value = combo;
      _setRec(false);
      _hkApply(combo);                        // 录到即用，无需再点按钮
    });
    _hkInput.addEventListener('blur', () => {
      if (_rec) { _hkInput.value = snipHk; _setRec(false); }
    });
    const _hkClear = pane.querySelector('#snipHkClear');
    if (_hkClear) _hkClear.onclick = () => {
      _hkInput.value = '';
      snipHk = '';
      _setRec(false);
      _hkApply('');                           // 空串=禁用
    };
  }

  // v3.5.310 可配置搜索快捷键：录制式（同截图快捷键交互），POST /api/theme
  // 落 config + 热更新 window._HK（消费端 hkMatch 即时生效，无需重启）。
  const _bindSearchHk = (inputId, curRef, field) => {
    const inp = pane.querySelector('#' + inputId);
    if (!inp) return;
    let rec = false;
    const setRec = on => {
      rec = on;
      inp.placeholder = on ? '按下组合键…（Esc 取消）' : '点击录制按键…';
      inp.style.borderColor = on ? 'var(--accent, #4a9eff)' : 'var(--border)';
    };
    inp.addEventListener('click', () => { if (rec) return; inp.value = ''; setRec(true); inp.focus(); });
    inp.addEventListener('keydown', e => {
      e.preventDefault(); e.stopPropagation();
      if (e.key === 'Escape') { inp.value = curRef.get(); setRec(false); return; }
      const mod = [];
      if (e.ctrlKey) mod.push('ctrl');
      if (e.altKey) mod.push('alt');
      if (e.shiftKey) mod.push('shift');
      const k = (e.key || '').toLowerCase();
      const isFn = /^f([1-9]|1[0-2])$/.test(k);
      if (!/^[a-z0-9]$/.test(k) && !isFn) return;   // 只收字母/数字/F1-F12
      if (!mod.length && !isFn) { inp.value = ''; inp.placeholder = '字母/数字需搭配 Ctrl/Alt/Shift（功能键可单键）…'; return; }
      inp.value = mod.concat([k]).join('+');
      setRec(false);
      (async () => {
        try {
          const r = await fetch('/api/theme', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: inp.value }) });
          const j = await r.json();
          if (j.ok) {
            curRef.set(inp.value);
            if (window._HK) window._HK[field === 'doc_search_hotkey' ? 'docSearch' : 'notesSearch'] = inp.value;
            showBanner('搜索快捷键已应用：' + inp.value + '（立即生效）');
          } else { showBanner(j.err || '保存失败', 3000, true); inp.value = curRef.get(); }
        } catch (e) { showBanner('保存失败: ' + e, 3000, true); inp.value = curRef.get(); }
      })();
    });
    inp.addEventListener('blur', () => { if (rec) { inp.value = curRef.get(); setRec(false); } });
  };
  const _docRef = { get: () => docHk, set: v => { docHk = v; } };
  const _notesRef = { get: () => notesHk, set: v => { notesHk = v; } };
  _bindSearchHk('docHkInput', _docRef, 'doc_search_hotkey');
  _bindSearchHk('notesHkInput', _notesRef, 'notes_search_hotkey');
}

// ---- 外部依赖安装（v4.1）：六项检测 + 离线资源包一键装 ----
// 数据源只有 /api/resources/status（manifest 由后端 MANIFEST 注入，前端
// 不硬编码六项名——res_boot.MANIFEST 是唯一真源）。
// 勾选语义 = 「这一项本次要处理」，不是「跳过」：默认勾选的只有没装好的，
// 免得一次点击把六项全量覆盖（.NET 要 UAC，Claude 是 270MB 拷贝）。
async function _stRenderResourcesPane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-label">外部依赖安装</div>
      <div class="dd-sub">用离线资源包（.fcpk）一键安装/重装运行环境。已有 Claude 配置（Token/settings）不受影响。</div>

      <div class="dd-cur" style="margin-top:12px;">
        <div class="dd-label">资源包</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <input type="text" id="rsPkgPath" class="dd-input" spellcheck="false"
                 placeholder="选择或粘贴 .fcpk 资源包路径" style="flex:1;">
          <button class="btn ghost" id="rsPkgPick"><span style="vertical-align:-2.5px">${ICO16.folderOpen}</span> 选择…</button>
          <button class="btn ghost icon-btn" id="rsRefresh" title="重新检测">⟳</button>
        </div>
        <div class="dd-sub" id="rsPkgInfo" style="margin-top:6px;">未选择资源包</div>
      </div>

      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label" style="display:flex;justify-content:space-between;align-items:center;">
          <span>依赖清单（勾选 = 本次要安装/重装）</span>
          <span style="display:flex;gap:6px;">
            <button class="btn ghost" id="rsPickMiss" style="padding:2px 9px;font-size:11px;">全选缺项</button>
            <button class="btn ghost" id="rsPickNone" style="padding:2px 9px;font-size:11px;">全不选</button>
          </span>
        </div>
        <div id="rsList" style="margin-top:8px;font-size:12.5px;line-height:2.0;">检测中…</div>
      </div>

      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">安装</div>
        <label style="display:flex;gap:8px;align-items:flex-start;margin-top:8px;font-size:12px;cursor:pointer;">
          <input type="checkbox" id="rsForce" style="margin-top:3px;">
          <span>强制重装（覆盖现有安装）
            <span class="dd-sub" style="display:block;margin-top:2px;">.NET 始终按缺失安装（需管理员且可能要重启）；
              Node/Git 重装可能弹管理员提示。</span></span>
        </label>
        <div class="dd-actions" style="margin-top:10px;display:flex;gap:8px;">
          <button class="btn primary" id="rsGo" disabled><span style="vertical-align:-2.5px">${ICO16.wrench}</span> 安装所选</button>
          <button class="btn ghost" id="rsCancel" style="display:none;">■ 取消</button>
        </div>
        <div id="rsProg" style="display:none;margin-top:10px;">
          <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
            <div id="rsProgBar" style="height:100%;width:0;background:var(--accent);transition:width .3s;"></div>
          </div>
          <div class="dd-sub" id="rsProgTxt" style="margin-top:4px;">—</div>
        </div>
        <div class="dd-sub" id="rsErr" style="display:none;margin-top:6px;color:var(--neon-red);"></div>
        <div class="cs-log" id="rsLog" style="display:none;max-height:170px;overflow:auto;
             font-size:11px;margin-top:8px;"></div>
      </div>

      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">Claude 专项修复</div>
        <div class="dd-actions" style="margin-top:6px;">
          <button class="btn ghost" id="rsFixStatusline">↺ 重配 statusLine</button>
        </div>
        <div class="dd-sub" style="margin-top:4px;">状态栏不显示（如 command 指向了无效解释器）时点此：清除坏配置并按本机实际 python 重配；本机无 python 则不配置（无害）。</div>
      </div>

      <details class="dd-cur" style="margin-top:14px;">
        <summary style="cursor:pointer;font-size:12px;">旧版离线包（zip）通道</summary>
        <div class="dd-actions" style="margin-top:8px;">
          <button class="btn ghost" id="rsOpenSetup">⊞ 打开旧的安装引导</button>
        </div>
        <div class="dd-sub" style="margin-top:4px;">联网安装 / claude-offline.zip 安装 / 制作旧格式离线包。新流程请用上方的 .fcpk 资源包。</div>
        <div class="dd-label" style="margin-top:12px;">离线安装包目录</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <div class="dd-path" id="apiPkgDir" style="flex:1;user-select:text;">—</div>
          <button class="btn ghost icon-btn" id="apiPkgPick" title="浏览选择目录">${ICO16.folderOpen}</button>
          <button class="btn ghost icon-btn" id="apiPkgReset" title="清除自定义，恢复默认">↺</button>
        </div>
        <div class="dd-sub" style="margin-top:4px;">旧通道（zip）的搜索目录。新流程用 .fcpk 资源包，不读这个。</div>
      </details>

      <div class="dd-note" id="rsNote"></div>
    </div>`;

  const $q = (sel) => pane.querySelector(sel);
  let _st = null;                 // 最近一次 status
  let _pkg = null;                // 最近一次包预检
  const _picked = new Set();      // 用户勾选的 kind（跨重渲染保留）

  // ---- 资源包选择 ----
  const pathBox = $q('#rsPkgPath');
  try {
    const saved = localStorage.getItem('fc_res_pkg');
    if (saved) pathBox.value = saved;
  } catch (_) {}

  async function loadPkg() {
    const p = pathBox.value.trim();
    const info = $q('#rsPkgInfo');
    if (!p) { _pkg = null; info.textContent = '未选择资源包'; paintList(); return; }
    info.textContent = '读取包信息…';
    try {
      const j = await (await fetch('/api/resources/package?path=' +
        encodeURIComponent(p))).json();
      if (!j.ok) { _pkg = null; info.textContent = '包不可用：' + (j.err || ''); paintList(); return; }
      _pkg = j;
      const kb = Object.keys(j.kinds || {});
      info.textContent = j.name + ' · ' + _ddFmtSize(j.size) +
        (j.created ? ' · ' + j.created : '') +
        ' · 含 ' + (kb.length ? kb.join('/') : '无') +
        (j.plain_len ? ' · 解压后 ' + _ddFmtSize(j.plain_len) : '');
      try { localStorage.setItem('fc_res_pkg', p); } catch (_) {}
      paintList();
    } catch (e) {
      _pkg = null; info.textContent = '读取失败：' + e; paintList();
    }
  }

  // ---- 依赖清单 ----
  function inPkg(kind) {
    if (!_pkg) return true;                 // 没选包时不置灰（点安装会提示）
    return !!( _pkg.kinds && _pkg.kinds[kind]);
  }

  function paintList() {
    const el = $q('#rsList');
    if (!_st) { el.textContent = '检测中…'; return; }
    const items = _st.items || [];
    el.innerHTML = items.map(function (it) {
      const ok = inPkg(it.kind);
      const chk = _picked.has(it.kind) ? ' checked' : '';
      const badge = it.ok
        ? '<span style="color:var(--accent)">✓ 已就绪</span>' +
          (it.ver ? ' <span style="color:var(--muted)">' + esc(it.ver) + '</span>' : '')
        : '<span style="color:var(--neon-red)">✗ ' +
          esc(it.state === 'outdated' ? '版本过低' : '缺失') + '</span>';
      const detail = it.ok ? '' :
        ' <span style="color:var(--muted);font-size:11px;">' + esc(it.detail || it.fix || '') + '</span>';
      const hard = it.hard
        ? ' <span style="font-size:10px;border:1px solid var(--muted);padding:0 3px;' +
          'border-radius:3px;color:var(--muted);">必需</span>' : '';
      const nosrc = ok ? '' :
        ' <span style="color:var(--warn,#c90);font-size:11px;">包内不含</span>';
      const dotnetHint = (it.kind === 'dotnet' && it.ok)
        ? ' <span style="color:var(--muted);font-size:11px;">（强制重装不适用）</span>' : '';
      return '<label style="display:flex;gap:8px;align-items:flex-start;' +
        (ok ? 'cursor:pointer;' : 'opacity:.5;cursor:not-allowed;') + '">' +
        '<input type="checkbox" data-kind="' + esc(it.kind) + '"' + chk +
        (ok ? '' : ' disabled') + ' style="margin-top:6px;flex-shrink:0;">' +
        '<span>' + esc(it.name) + hard + ' — ' + badge + dotnetHint + detail + nosrc +
        '</span></label>';
    }).join('');
    el.querySelectorAll('input[data-kind]').forEach(function (cb) {
      cb.onchange = function () {
        if (cb.checked) _picked.add(cb.dataset.kind);
        else _picked.delete(cb.dataset.kind);
        syncGo();
      };
    });
    syncGo();
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function syncGo() {
    const busy = $q('#rsGo').dataset.busy === '1';
    $q('#rsGo').disabled = busy || _picked.size === 0;
  }

  // ---- 检测 ----
  async function loadStatus(pickDefaults) {
    try {
      const j = await (await fetch('/api/resources/status')).json();
      _st = j;
      if (pickDefaults) {
        _picked.clear();
        (j.items || []).forEach(function (it) { if (!it.ok) _picked.add(it.kind); });
      } else {
        // 保留已有勾选，但剔除已不再可用的（换包后包内没有的）
        Array.from(_picked).forEach(function (k) { if (!inPkg(k)) _picked.delete(k); });
      }
      paintList();
    } catch (e) {
      $q('#rsList').textContent = '检测失败：' + e;
    }
  }

  // ---- 安装 ----
  async function doInstall() {
    const path = pathBox.value.trim();
    if (!path) { showBanner('请先选择 .fcpk 资源包', 4000, true); return; }
    const kinds = Array.from(_picked);
    if (!kinds.length) return;
    const force = $q('#rsForce').checked;
    // 强制重装 + 勾了已就绪项 → 二次确认（这是要覆盖人家能用的安装）
    if (force) {
      const ready = kinds.filter(function (k) {
        const it = (_st.items || []).filter(function (x) { return x.kind === k; })[0];
        return it && it.ok;
      });
      if (ready.length) {
        const ok = await _ddConfirm('强制重装',
          '将覆盖以下已就绪的项：' + ready.join('、') +
          '\n\n.Node/Git 可能弹管理员提示；Claude 会先备份再替换（失败自动回滚）。继续？');
        if (!ok) return;
      }
    }
    const logEl = $q('#rsLog'), errEl = $q('#rsErr'), prog = $q('#rsProg');
    logEl.style.display = ''; logEl.innerHTML = '';
    errEl.style.display = 'none';
    prog.style.display = '';
    $q('#rsProgBar').style.width = '0';
    $q('#rsProgTxt').textContent = '准备…';
    $q('#rsGo').dataset.busy = '1'; syncGo();
    $q('#rsCancel').style.display = '';
    if (typeof window.ResPanel === 'undefined' || !window.ResPanel.install) {
      errEl.style.display = ''; errEl.textContent = '前端未加载 resources.js';
      return;
    }
    // 全审 N2 实锤（严重）：安装中切到别的设置分区时，#stPane 被整体替换，
    // 这些元素消失 → 回调里 $q('#rsProgBar').style 抛 TypeError → 该轮 .then
    // 中断、`if (!s.done) return` 与 onDone 全被跳过 → 轮询继续跑但永不收尾，
    // 切回来时按钮永久禁用。每个回调先探活，DOM 更新一律可选。
    const alive = () => !!$q('#rsGo');
    window.ResPanel.install({
      path: path, kinds: kinds, force: force,
      onLog: function (msg) {
        if (!alive()) return;
        const d = document.createElement('div');
        d.textContent = msg;
        logEl.appendChild(d);
        logEl.scrollTop = logEl.scrollHeight;
      },
      onTick: function (s) {
        if (!alive()) return;
        const bar = $q('#rsProgBar'), txt = $q('#rsProgTxt');
        const tot = s.total || 0, cur = s.bytes || 0;
        const pct = tot ? Math.min(100, Math.round(cur * 100 / tot)) : 0;
        if (bar) bar.style.width = pct + '%';
        if (txt) txt.textContent = (s.phase || '') +
          (tot ? ' · ' + _ddFmtSize(cur) + ' / ' + _ddFmtSize(tot) + ' (' + pct + '%)' : '') +
          (s.cancelling ? ' · 正在取消…' : '');
      },
      onDone: function (r) {
        // 结算先做（不管 DOM 还在不在），再尽力更新界面
        if (alive()) {
          $q('#rsGo').dataset.busy = '';
          $q('#rsCancel').style.display = 'none';
          syncGo();
          prog.style.display = 'none';
          if (!r.ok) {
            errEl.style.display = '';
            errEl.textContent = r.err || '安装失败';
          }
        }
        if (r.ok) {
          showBanner('资源安装完成');
          if (alive()) loadStatus(false);
        } else {
          if (r.cancelled) showBanner('已取消安装', 4000);
          if (alive()) loadStatus(false);
        }
      }
    });
  }

  // ---- 事件 ----
  $q('#rsPkgPick').onclick = async function () {
    let p = '';
    try {
      if (window.pywebview && pywebview.api && pywebview.api.pick_any) {
        const r = await pywebview.api.pick_any();
        p = (typeof r === 'string') ? r : ((r && r.path) || '');
      }
    } catch (_) {}
    if (!p) p = window.prompt('资源包完整路径（*.fcpk）：', pathBox.value || '') || '';
    if (!p) return;
    pathBox.value = p.trim();
    loadPkg();
  };
  pathBox.onchange = loadPkg;
  $q('#rsRefresh').onclick = async function () {
    await loadStatus(false);
    if (pathBox.value.trim()) loadPkg();
  };
  $q('#rsPickMiss').onclick = function () {
    _picked.clear();
    ((_st && _st.items) || []).forEach(function (it) {
      if (!it.ok && inPkg(it.kind)) _picked.add(it.kind);
    });
    paintList();
  };
  $q('#rsPickNone').onclick = function () { _picked.clear(); paintList(); };
  $q('#rsGo').onclick = doInstall;
  $q('#rsCancel').onclick = function () {
    if (window.ResPanel && window.ResPanel.cancel) window.ResPanel.cancel();
    $q('#rsProgTxt').textContent = '正在取消…';
  };

  // 旧通道（保留原逻辑，只是折叠起来）
  const refreshPkgDir = async () => {
    try {
      const st = await (await fetch('/api/claude/setup_status')).json();
      $q('#apiPkgDir').textContent = st.offline_pkg_dir || '默认（工具目录 offline_pkg）';
    } catch (_) {}
  };
  refreshPkgDir();
  $q('#rsOpenSetup').onclick = () => {
    $('settingsModal').classList.remove('show');
    openClaudeSetup();
  };
  $q('#rsFixStatusline').onclick = async () => {
    const ok = await _ddConfirm('重配 statusLine',
      '清除 settings.json 中现有 statusLine 配置并按本机 python 重配？找不到 python 时不配置（状态栏不显示，无害）。');
    if (!ok) return;
    try {
      const r = await fetch('/api/claude/provision', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({force_statusline: true, reset_statusline: true})});
      const j = await r.json();
      showBanner(j.ok ? ('已完成：' + (j.notes || []).join('、')) : '重配失败', 6000, !j.ok);
    } catch(e) { showBanner('重配失败: ' + e, 4000, true); }
  };
  $q('#apiPkgPick').onclick = async () => {
    try {
      const dir = await pywebview.api.pick_dir();
      if (!dir) return;
      const r = await fetch('/api/claude/setup_pkg_dir', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir})});
      const j = await r.json();
      if (!j.ok) { showBanner('设置失败: ' + (j.err || ''), 4000, true); return; }
      showBanner('离线安装包目录已更新');
      refreshPkgDir();
    } catch(e) { showBanner('目录选择器不可用，或请求失败: ' + e, 4000, true); }
  };
  $q('#apiPkgReset').onclick = async () => {
    try {
      await fetch('/api/claude/setup_pkg_dir', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: ''})});
      showBanner('已恢复默认离线包目录');
      refreshPkgDir();
    } catch(_) {}
  };

  // 首次：检测 + 按默认规则勾选；有已保存的包路径则顺带预检
  await loadStatus(true);
  if (pathBox.value.trim()) loadPkg();
}

// ---- API 配置子页（v2.25 重排）：配置方案最前（最常用）→ API 配置表单 → 底部操作 ----
// 新建配置模式：表单全空白，保存=写 settings.json + 存为新方案一步完成。
// 获取模型：按 base_url+token 探测网关模型列表，成功后模型映射各档变可下拉。
let _stApiNewMode = false;
let _stApiModels = null;      // 探测到的模型 id 列表（datalist 下拉源）
async function _stRenderApiPane(pane) {
  // 模型映射档位（v2.25 对齐 cc_switch：5 角色档 + 默认兜底，砍 Flash 档）。
  // 档位是「模型别名」：Claude Code 按档位名请求模型，这里填的是该档位在本
  // 网关下真正对应的模型名。名字与型号无关（网关没有 Opus，就把最强模型填
  // 在 Opus 档），所以每一档都要写清「什么时候会用到它」，否则配置者填不对。
  // Flash 键（ANTHROPIC_DEFAULT_FLASH_MODEL）不再在 UI 出现，但后端兼容保留
  // ——settings/旧方案快照里已有的值照常生效，UI 不显示不修改。
  const M_SLOTS = [
    ['sonnet','Sonnet','日常主力档。点名 sonnet 时映射到这里，适合大部分普通任务。'],
    ['opus','Opus','最强推理档。任务点名 opus 时（/model 选 Opus、子代理指定 opus）实际调到这里填的模型。'],
    ['fable','Fable','网关侧档位。点名 fable 时映射到这里；不清楚填什么就留空。'],
    ['haiku','Haiku','快速轻量档。生成标题、摘要等后台小任务常走这档，填个便宜快的模型即可。'],
    ['subagent','子代理','Task 子代理会话默认使用的模型（子代理不单独指定档位时用这个）。']];
  const NEW = !!_stApiNewMode;
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-cur">
        <div class="dd-label" style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <span>配置方案（整套 settings.json 快照一键切换）</span>
          <button class="btn ghost" id="profNew" title="新建一套配置：下方表单清空，填好保存即成新方案"
                  style="padding:3px 10px;font-size:11px;flex-shrink:0;${NEW ? 'display:none;' : ''}">＋ 新建配置</button>
        </div>
        <div id="profList" style="margin-top:10px;margin-bottom:4px;display:flex;flex-direction:column;gap:8px;"></div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:14px;">
          <input type="text" id="profName" class="dd-input" spellcheck="false"
                 placeholder="${NEW ? '必填——新配置将保存为这个方案名' : '方案名，如：配置1 / 智谱 / 中转站'}" style="flex:1;${NEW ? 'border-color:var(--accent);' : ''}">
          <button class="btn ghost" id="profSaveCur" title="把当前 settings.json 整份（含 Token、网关、模型映射等）存为方案"
                  style="${NEW ? 'display:none;' : ''}"><span style="vertical-align:-2.5px">${ICO16.save}</span> 存当前为方案</button>
        </div>
        <div class="dd-sub" style="margin-top:8px;">每个方案是 settings.json 的完整快照（网关不同，模型映射也不同）。切换整份替换——已开着的 Claude 会话进程不变，新会话起效。</div>
      </div>
      <div class="dd-cur" style="padding-top:14px;border-top:1px solid var(--border);">
        <div class="dd-label">Claude API 配置${NEW ? '<span style="color:var(--accent);">（新建中——下方已清空，填好后点「保存为新方案」）</span>' : ''}</div>
        <div class="dd-sub">写入 ~/.claude/settings.json 的 env——留空的项不改动。改动对新开的 Claude 会话生效。</div>
        <div class="dd-label" style="margin-top:12px;">API Token（ANTHROPIC_AUTH_TOKEN）</div>
        <div class="dd-row" style="display:flex;gap:6px;margin-top:6px;">
          <input type="text" id="apiTokenInput" class="dd-input" spellcheck="false" autocomplete="off"
                 placeholder="${NEW ? 'sk-…（新方案的 Token）' : 'sk-…（留空保持不变）'}" style="flex:1;">
          <button class="pass-eye" id="apiTokenEye" type="button" title="显示/隐藏完整 Token"
                  style="width:32px;height:32px;flex-shrink:0;">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
              <circle cx="12" cy="12" r="3"></circle>
            </svg>
          </button>
        </div>
        <div class="dd-label" style="margin-top:12px;">BASE_URL（网关地址，随方案切换）</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;">
          <input type="text" id="apiBaseUrl" class="dd-input" spellcheck="false"
                 placeholder="http://…（留空保持不变）" style="flex:1;">
          <button class="btn ghost" id="apiProbe" title="按上面的 BASE_URL + Token 向网关拉取可用模型列表"
                  style="flex-shrink:0;white-space:nowrap;"><span style="vertical-align:-2.5px">${ICO16.search}</span> 获取模型</button>
        </div>
        <div class="dd-sub" id="apiProbeOut" style="margin-top:6px;">${_stApiModels ? '已获取 ' + _stApiModels.length + ' 个模型——模型映射框可下拉选择' : '获取模型后，模型映射框可直接下拉选择'}</div>
        <div class="dd-label" style="margin-top:12px;">模型映射（MODEL 与 _NAME 成对写入，留空不改）</div>
        <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-top:8px;">
          ${M_SLOTS.map(([k, n, tip]) => `
            <label title="${tip}" style="display:flex;align-items:center;gap:6px;min-width:0;cursor:help;">
              <span style="flex-shrink:0;width:50px;font-size:11px;color:var(--muted);">${n}</span>
              <input type="text" name="dd_mk_${k}" class="dd-input" data-mk="${k}" spellcheck="false"
                     placeholder="不改" style="flex:1;min-width:0;">
              <button type="button" class="btn ghost" data-mk1m="${k}" title="声明支持 1M：给模型名加/去 [1M] 后缀（网关按此后缀提供百万级上下文）"
                      style="flex-shrink:0;padding:2px 7px;font-size:10px;">1M</button>
            </label>`).join('')}
          <label title="默认兜底模型（ANTHROPIC_MODEL）：未明确落到上面 5 个角色档的请求都用它。新开的会话默认用它，也是本工具模型下拉里显示的那一项。" style="display:flex;align-items:center;gap:6px;min-width:0;cursor:help;">
            <span style="flex-shrink:0;width:50px;font-size:11px;color:var(--muted);">兜底</span>
            <input type="text" name="dd_mk_main" class="dd-input" data-mk="main" spellcheck="false"
                   placeholder="不改" style="flex:1;min-width:0;">
            <button type="button" class="btn ghost" data-mk1m="main" title="声明支持 1M：给模型名加/去 [1M] 后缀"
                    style="flex-shrink:0;padding:2px 7px;font-size:10px;">1M</button>
          </label>
        </div>
        <div class="dd-sub" style="margin-top:8px;">档位是「模型别名」：名字不代表型号（网关没有 Opus，就把最强模型填进 Opus 档）。鼠标悬停每档看它什么时候被用到。<b>1M</b> 按钮 = 声明该档用百万级上下文版本（模型名加/去 <b>[1M]</b> 后缀）。</div>
        <div class="dd-label" style="margin-top:14px;">上下文窗口与自动压缩</div>
        <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-top:8px;">
          <label style="display:flex;align-items:center;gap:6px;min-width:0;">
            <span style="flex-shrink:0;width:64px;font-size:11px;color:var(--muted);">压缩窗口</span>
            <input type="text" id="apiCtxWindow" class="dd-input" spellcheck="false" placeholder="不改" style="flex:1;min-width:0;">
          </label>
          <label style="display:flex;align-items:center;gap:6px;min-width:0;">
            <span style="flex-shrink:0;width:64px;font-size:11px;color:var(--muted);">最大上下文</span>
            <input type="text" id="apiMaxCtx" class="dd-input" spellcheck="false" placeholder="不改" style="flex:1;min-width:0;">
          </label>
          <label style="display:flex;align-items:center;gap:6px;min-width:0;">
            <span style="flex-shrink:0;width:64px;font-size:11px;color:var(--muted);">压缩阈值%</span>
            <input type="text" id="apiCompactPct" class="dd-input" spellcheck="false" placeholder="不改" style="flex:1;min-width:0;">
          </label>
        </div>
        <div class="dd-sub" style="margin-top:6px;">压缩窗口/最大上下文 = tokens（如 200000）；压缩阈值 = 用量百分比（如 85）。这三项决定「用到多少 tokens 才自动压缩」。</div>
      </div>
      <div class="dd-row" style="display:flex;align-items:center;gap:10px;margin-top:14px;">
        <button class="btn primary" id="apiSaveAll">${NEW ? '<span style="vertical-align:-2.5px">' + ICO16.save + '</span> 保存为新方案' : '<span style="vertical-align:-2.5px">' + ICO16.save + '</span> 保存配置'}</button>
        ${NEW ? '<button class="btn ghost" id="apiNewCancel">取消新建</button>' : ''}
        <span class="dd-sub" style="margin:0;">保存后新开的 Claude 会话生效（运行中的会话不变）。</span>
      </div>
      <div class="dd-actions" style="margin-top:16px;">
        <button class="btn ghost" id="apiOpenSettings" title="在工具内打开 settings.json（Monaco 编辑）"><span style="vertical-align:-2.5px">${ICO16.folderOpen}</span> 打开 settings.json</button>
        <button class="btn ghost" id="apiProvision" title="恢复 Claude 默认配置（settings 缺省项补全 + statusline 重铺；已有配置不动，statusline 强制覆盖）">↺ 恢复 Claude 默认配置</button>
      </div>
      <div class="dd-note" id="apiNote"></div>
    </div>`;
  const tokEl = pane.querySelector('#apiTokenInput');
  const eyeEl = pane.querySelector('#apiTokenEye');
  // 眼睛图标随状态切换（SSH 密码框同款语义：明文可见=开眼，掩码/隐藏=划线眼）
  const EYE_OPEN_SVG = eyeEl.innerHTML;
  const EYE_OFF_SVG = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
      <line x1="1" y1="1" x2="23" y2="23"></line>
    </svg>`;
  const syncEye = () => {
    const showing = tokEl.dataset.mode === 'full' || tokEl.dataset.mode === 'edit';
    eyeEl.innerHTML = showing ? EYE_OPEN_SVG : EYE_OFF_SVG;
    eyeEl.title = showing ? 'Token 可见中，点击隐藏' : 'Token 已隐藏，点击显示';
  };
  let tokenFull = '';        // 完整 token（GET 拿到；眼睛显示 / 获取模型用）
  const setTokMasked = () => {
    if (!tokenFull) { tokEl.value = ''; tokEl.dataset.mode = 'empty'; syncEye(); return; }
    const masked = tokenFull.length > 16 ? tokenFull.slice(0, 8) + '…' + tokenFull.slice(-4) : '已设置';
    tokEl.value = masked; tokEl.dataset.mode = 'masked'; tokEl.style.color = 'var(--muted)';
    syncEye();
  };
  const setTokFull = () => {
    tokEl.value = tokenFull; tokEl.dataset.mode = 'full'; tokEl.style.color = '';
    syncEye();
  };
  const refresh = async () => {
    try {
      const j = await (await fetch('/api/claude/api_config')).json();
      tokenFull = j.token || '';
      if (!NEW) {
        if (j.has_token) setTokMasked();
        else { tokEl.value = ''; tokEl.dataset.mode = 'empty'; tokEl.style.color = ''; }
      } else { tokEl.dataset.mode = 'edit'; }
      pane.querySelector('#apiBaseUrl').value = NEW ? '' : (j.base_url || '');
      pane.querySelector('#apiBaseUrl').placeholder = NEW ? 'http://…（新方案的网关地址）'
        : ((j.base_url || j.default_base_url) + '（当前）');
      const models = NEW ? {} : (j.models || {});
      pane.querySelectorAll('[data-mk]').forEach(i => {
        i.value = models[i.dataset.mk] || '';
        i.placeholder = NEW ? '新方案的模型' : (models[i.dataset.mk] ? '当前 ' + models[i.dataset.mk] : '未设置');
      });
      const fill = (sel, v) => {
        const el = pane.querySelector(sel);
        el.value = NEW ? '' : (v || '');
        el.placeholder = NEW ? '新方案的值' : (v ? '当前 ' + v : '未设置');
      };
      fill('#apiCtxWindow', j.ctx_window); fill('#apiMaxCtx', j.max_ctx); fill('#apiCompactPct', j.compact_pct);
      pane.querySelector('#apiNote').textContent = 'settings.json 路径：' + j.settings_path;
    } catch(e) { tokEl.placeholder = '读取失败: ' + e; }
    invalidateModels();   // 重渲/切方案后 base_url 已换人，旧列表一律作废，须重新获取
  };
  // ---- 模型下拉浮层（v2.25）：原生 datalist 交互太弱（箭头悬停才出现、
  // 匹配行为怪，用户实测「下拉不生效」）——自绘浮层，点击输入框即弹列表 ----
  let mdlPop = null;
  const closeMdlPop = () => { if (mdlPop) { mdlPop.remove(); mdlPop = null; } };
  // 列表有效性只归「获取模型」按钮管：成功才有列表，失败/改地址即作废（浮层
  // 每次弹出时现读 _stApiModels，所以作废只需清变量 + 收浮层 + 刷提示文案）
  const invalidateModels = () => {
    if (!_stApiModels) return;
    _stApiModels = null;
    closeMdlPop();
    const out = pane.querySelector('#apiProbeOut');
    if (out) out.textContent = '获取模型后，模型映射框可直接下拉选择';
  };
  const openMdlPop = (inp) => {
    closeMdlPop();
    if (!_stApiModels || !_stApiModels.length) return;
    mdlPop = document.createElement('div');
    mdlPop.className = 'mdl-pop';
    const r = inp.getBoundingClientRect();
    mdlPop.style.left = r.left + 'px';
    mdlPop.style.top = (r.bottom + 4) + 'px';
    mdlPop.style.minWidth = Math.max(r.width, 230) + 'px';
    mdlPop.innerHTML = _stApiModels.map(m =>
      `<div class="mdl-pop-item" data-v="${esc(m)}">${esc(m)}</div>`).join('');
    document.body.appendChild(mdlPop);
    mdlPop.querySelectorAll('.mdl-pop-item').forEach(it => {
      it.onclick = () => {
        inp.value = it.dataset.v;
        sync1mState();
        closeMdlPop();
      };
    });
  };
  pane.querySelectorAll('[data-mk]').forEach(inp => {
    inp.addEventListener('focus', () => openMdlPop(inp));
    inp.addEventListener('input', sync1mState);
  });
  // 改了 BASE_URL 或 Token，上次拉到的列表就是别的网关的了——立即作废
  pane.querySelector('#apiBaseUrl').addEventListener('input', invalidateModels);
  tokEl.addEventListener('input', invalidateModels);
  // a239 B3-P3: 关闭监听单例化——原每次渲染都 addEventListener 一枚到 document，
  // 旧闭包永不摘（长会话无限累积）；用共享标记 + 重绑前先移除
  if (pane._mdlPopCloser) document.removeEventListener('click', pane._mdlPopCloser);
  pane._mdlPopCloser = (e) => {
    if (!mdlPop) return;
    if (mdlPop.contains(e.target)) return;                              // 点列表项：选择逻辑自己处理
    if (e.target.closest && e.target.closest('[data-mk]')) return;      // 点另一个框：focus 已重开浮层
    closeMdlPop();
  };
  document.addEventListener('click', pane._mdlPopCloser);
  // ---- [1M] 开关：给该档模型名加/去 [1M] 后缀（网关按此后缀给百万级上下文）----
  function sync1mState() {
    pane.querySelectorAll('[data-mk1m]').forEach(btn => {
      const inp = pane.querySelector(`[data-mk="${btn.dataset.mk1m}"]`);
      const on = /\[1M\]\s*$/i.test(inp.value || '');
      btn.style.color = on ? 'var(--accent)' : '';
      btn.style.borderColor = on ? 'var(--accent)' : '';
    });
  }
  pane.querySelectorAll('[data-mk1m]').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault();
      const inp = pane.querySelector(`[data-mk="${btn.dataset.mk1m}"]`);
      const has = /\[1M\]\s*$/i.test(inp.value || '');
      const base = (inp.value || '').replace(/\s*\[1M\]\s*$/i, '');
      inp.value = has ? base : base + '[1M]';
      sync1mState();
    };
  });
  sync1mState();
  // Token 眼睛：掩码 ↔ 完整值切换（用户手输新 token 时不动值，只提示）
  eyeEl.onclick = () => {
    const m = tokEl.dataset.mode;
    if (m === 'masked') setTokFull();
    else if (m === 'full') setTokMasked();
    else showBanner(m === 'edit' ? '正在输入新 Token——保存时以此为准' : '当前没有已配置的 Token', 2600);
  };
  tokEl.addEventListener('input', () => { tokEl.dataset.mode = 'edit'; tokEl.style.color = ''; syncEye(); });
  syncEye();   // 初始态图标（掩码=划线眼）
  // 获取模型：base_url + token 拉网关模型列表 → datalist 下拉
  pane.querySelector('#apiProbe').onclick = async () => {
    const probeBtn = pane.querySelector('#apiProbe');
    const out = pane.querySelector('#apiProbeOut');
    const base = pane.querySelector('#apiBaseUrl').value.trim();
    const tok = tokEl.dataset.mode === 'edit' ? tokEl.value.trim() : tokenFull;
    if (!base || !tok) { showBanner('获取模型需要 BASE_URL 和 Token 都已填写', 3500, true); return; }
    probeBtn.disabled = true;
    out.textContent = '探测中——正在向网关拉取模型列表…';
    try {
      const r = await fetch('/api/claude/models_probe', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({base_url: base, token: tok})});
      const j = await r.json();
      if (j.ok && (j.models || []).length) {
        _stApiModels = j.models;
        out.textContent = '✓ 获取到 ' + j.models.length + ' 个模型——模型映射框已可下拉选择';
      } else {
        invalidateModels();
        out.textContent = '✗ 获取失败：' + (j.err || '网关未返回模型列表') + '——模型映射框不可下拉';
      }
    } catch(e) { invalidateModels(); out.textContent = '✗ 获取失败：' + e + '——模型映射框不可下拉'; }
    probeBtn.disabled = false;
  };
  refresh();
  // v2.22：整卡保存——token/base_url/模型映射/上下文窗口一次提交（空串=不改）
  // v2.25 新建模式：保存=写 settings.json + 按方案名存为新方案，一步完成
  pane.querySelector('#apiSaveAll').onclick = async () => {
    const models = {};
    pane.querySelectorAll('[data-mk]').forEach(i => { models[i.dataset.mk] = i.value.trim(); });
    const body = {
      token: tokEl.dataset.mode === 'edit' ? tokEl.value.trim() : '',
      base_url: pane.querySelector('#apiBaseUrl').value.trim(),
      models,
      ctx_window: pane.querySelector('#apiCtxWindow').value.trim(),
      max_ctx: pane.querySelector('#apiMaxCtx').value.trim(),
      compact_pct: pane.querySelector('#apiCompactPct').value.trim(),
    };
    if (NEW) {
      const name = pane.querySelector('#profName').value.trim();
      if (!name) { showBanner('请先填写方案名——新配置将保存为该方案', 4000, true); return; }
      if (!body.token && !tokenFull) { showBanner('新方案需要填写 Token', 4000, true); return; }
      if (!body.base_url) { showBanner('新方案需要填写 BASE_URL', 4000, true); return; }
      try {
        const r = await fetch('/api/claude/api_config', {method:'POST',
          headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        const j = await r.json();
        if (!j.ok) { showBanner('保存失败: ' + (j.err || ''), 4000, true); return; }
        const r2 = await fetch('/api/claude/profiles/save', {method:'POST',
          headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
        const j2 = await r2.json();
        if (!j2.ok) { showBanner('配置已写入 settings.json，但存方案失败: ' + (j2.err || ''), 6000, true); return; }
        // v3.5.102（轻审严重1）：保存新方案后立即「应用」它——此前 active
        // 仍指旧方案而 settings 已是新方案内容，用户接着点普通「保存配置」
        // 会把新方案内容同步进旧方案快照（污染）。切换让 active 与 settings
        // 重新对齐，后续保存/同步全部落在新方案名下。切不动（409 未稳定
        // 等）只提示手动应用，不算保存失败。
        const r3 = await fetch('/api/claude/profiles/apply', {method:'POST',
          headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
        let j3 = null;
        try { j3 = await r3.json(); } catch(_) {}
        _stApiNewMode = false;
        if (!j3 || !j3.ok) {
          showBanner('新方案「' + name + '」已保存，但未能自动切换（' + ((j3 && j3.err) || '网络错误') + '）——请到方案列表手动「应用」后再做其它修改', 8000, true);
        } else {
          if (j3.warning) showBanner('⚠ ' + j3.warning, 9000, true);
          showBanner('新方案「' + name + '」已保存并切换——后续保存都会同步到它', 5000);
        }
        _stRenderApiPane(pane);
      } catch(e) { showBanner('保存失败: ' + e, 4000, true); }
      return;
    }
    try {
      // v3.5.99：sync_active 只在普通保存分支传（新建分支共用 body——那边
      // active 还指着旧方案，同步会把旧方案快照污染成新方案的配置）。
      const r = await fetch('/api/claude/api_config', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({...body, sync_active: true})});
      const j = await r.json();
      if (!j.ok) { showBanner('保存失败: ' + (j.err || ''), 4000, true); return; }
      // v3.5.99：后端已把激活方案快照同步为本次保存的内容——来回切方案
      // 不再还原；同步失败显式告警（settings 本身已保存成功）。
      showBanner(j.synced ? ('API 配置已保存，方案「' + j.synced + '」快照已同步——来回切方案不再还原')
        : 'API 配置已保存——新开的 Claude 会话生效', j.synced ? 4500 : 4000);
      if (j.sync_err) showBanner('⚠ ' + j.sync_err, 7000, true);
      setTokMasked();
      refresh();
    } catch(e) { showBanner('保存失败: ' + e, 4000, true); }
  };
  if (NEW) pane.querySelector('#apiNewCancel').onclick = () => {
    _stApiNewMode = false; _stRenderApiPane(pane);
  };
  // ---- 配置方案：多套 TOKEN/BASE_URL 存档一键切换（v2.21）----
  const profListEl = pane.querySelector('#profList');
  const renderProfiles = async () => {
    try {
      const j = await (await fetch('/api/claude/profiles')).json();
      if (!j.ok) throw new Error(j.err || '');
      profListEl.innerHTML = (j.profiles || []).map(p => `
        <div title="${esc((p.token_masked || '未设 Token') + ' · ' + (p.base_url || '默认网关'))}" style="display:flex;align-items:center;gap:12px;padding:9px 12px;border:1px solid ${p.legacy ? 'var(--neon-yellow, orange);' : 'var(--border);'}border-radius:8px;${p.name === j.active ? 'border-color:var(--neon-green);' : ''}">
          <b style="flex-shrink:0;max-width:40%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(p.name)}</b>
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:11px;">${esc(p.base_url || '默认网关')}${p.token_masked ? ' · ' + esc(p.token_masked) : ''}</span>
          ${p.legacy ? '<span style="color:orange;font-size:11px;flex-shrink:0;" title="只存了 Token/网关——切换不会带模型映射，配好后重新『存当前为方案』升级"><span style="vertical-align:-2.5px">' + ICO16.warn + '</span> 旧格式</span>' : ''}
          ${p.name === j.active
            ? '<span style="color:var(--neon-green);font-size:11px;flex-shrink:0;">● 当前</span>'
            : `<button class="btn ghost" data-prof="${esc(p.name)}" style="flex-shrink:0;${j.switching ? 'opacity:.5;cursor:not-allowed;' : ''}"${j.switching ? ' disabled' : ''}>${j.switching ? '切换中…' : '应用'}</button>`}
          <button class="btn ghost" data-profdel="${esc(p.name)}" title="删除方案（不影响当前 settings.json）" style="flex-shrink:0;">✕</button>
        </div>`).join('')
        || '<div class="dd-sub">暂无方案——填好 Token 保存后，点「存当前为方案」留存第一套。</div>';
      profListEl.querySelectorAll('[data-prof]').forEach(b => {
        b.onclick = async () => {
          if (b.disabled) return;
          try {
            const r = await fetch('/api/claude/profiles/apply', {method:'POST',
              headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: b.dataset.prof})});
            const j2 = await r.json();
            if (!j2.ok) { showBanner('切换失败: ' + (j2.err || ''), 4000, true); renderProfiles(); return; }
            if (j2.warning) { showBanner('⚠ ' + j2.warning, 9000, true); }
            else showBanner('已切换到「' + b.dataset.prof + '」——新开的 Claude 会话生效', 4500);
            _stApiNewMode = false;   // 应用方案 = 退出新建模式
            refresh(); renderProfiles();
          } catch(e) { showBanner('切换失败: ' + e, 4000, true); }
        };
      });
      // 切换未稳定：按钮全禁用，1s 后自动重查——稳定即自动恢复可点
      // （后端 409 是最终真相源，这里只是让按钮状态肉眼可见）
      if (j.switching) {
        clearTimeout(profListEl._swT);
        profListEl._swT = setTimeout(renderProfiles, 1000);
      }
      profListEl.querySelectorAll('[data-profdel]').forEach(b => {
        b.onclick = async () => {
          const ok = await _ddConfirm('删除配置方案', '删除方案「' + b.dataset.profdel + '」？（不影响当前 settings.json）');
          if (!ok) return;
          await fetch('/api/claude/profiles/del', {method:'POST',
            headers:{'Content-Type':'application/json'}, body: JSON.stringify({name: b.dataset.profdel})});
          renderProfiles();
        };
      });
    } catch(e) { profListEl.textContent = '方案读取失败: ' + e; }
  };
  renderProfiles();
  pane.querySelector('#profNew').onclick = () => {
    _stApiNewMode = true;
    _stRenderApiPane(pane);   // 重渲：表单清空进入新建模式
    const nav = document.getElementById('stPane');
    if (nav) nav.scrollTop = 0;
    showBanner('新建配置：下方表单已清空，填好后点「保存为新方案」', 4200);
  };
  pane.querySelector('#profSaveCur').onclick = async () => {
    const name = pane.querySelector('#profName').value.trim();
    if (!name) { showBanner('请输入方案名', 3000, true); return; }
    try {
      const r = await fetch('/api/claude/profiles/save', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
      const j = await r.json();
      if (!j.ok) { showBanner('保存失败: ' + (j.err || ''), 4000, true); return; }
      showBanner('已存为方案「' + name + '」');
      pane.querySelector('#profName').value = '';
      renderProfiles();
    } catch(e) { showBanner('保存失败: ' + e, 4000, true); }
  };
  pane.querySelector('#apiOpenSettings').onclick = async () => {
    // 工具内打开（Monaco 编辑器），不是资源管理器——用户要直接改
    try {
      const j = await (await fetch('/api/claude/api_config')).json();
      if (j.settings_path) openFileSmart(j.settings_path, 'auto');
      else showBanner('未获取到 settings.json 路径', 3000, true);
    } catch(_) { showBanner('打开失败', 3000, true); }
  };
  pane.querySelector('#apiProvision').onclick = async () => {
    const ok = await _ddConfirm('恢复 Claude 默认配置',
      '补全 settings.json 缺省项（已有配置不动）并重铺 statusline.py？');
    if (!ok) return;
    try {
      const r = await fetch('/api/claude/provision', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({force_statusline: true})});
      const j = await r.json();
      showBanner(j.ok ? ('已完成：' + (j.notes || []).join('、')) : '恢复失败', 5000, !j.ok);
    } catch(e) { showBanner('恢复失败: ' + e, 4000, true); }
  };
}

// ---- 关于与升级子页（v2.1.0）：版本显示 / 检查更新 / 一键升级 / 发布机分发服务 ----
async function _stRenderUpdatePane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-cur">
        <div class="dd-label">当前版本</div>
        <div class="dd-path" id="upCur">—</div>
        <div class="dd-sub" id="upSrvState"></div>
      </div>
      <div class="dd-form">
        <div class="dd-label">升级服务器地址（发布者提供）</div>
        <div class="dd-row">
          <input type="text" id="upUrl" class="dd-input" spellcheck="false" placeholder="http://发布者内网IP:8765/">
          <button class="btn ghost" id="upSaveUrl">保存</button>
          <button class="btn primary" id="upCheck">检查更新</button>
        </div>
        <div id="upResult" class="dd-msg"></div>
      </div>
      <div class="dd-form" data-fx-srv>
        <div class="dd-label">升级分发服务（仅发布者机器开启）</div>
        <div class="dd-sub" id="upSrvInfo">状态获取中…</div>
        <div class="dd-actions" style="margin-top:8px;">
          <button class="btn ghost" id="upSrvToggle">—</button>
        </div>
        <div class="dd-sub">开启后本机 8765 端口只读分发 dist/releases/ 下的版本包；首次开启 Windows 防火墙弹窗请允许（勾选专用网络）。把「同事升级地址」发给同事填到他们的这个输入框即可。</div>
        <div class="dd-row" style="margin-top:10px;">
          <input type="text" id="upPwd" class="dd-input" spellcheck="false" placeholder="Web 门户登录密码（空=默认 888888）" style="flex:1;">
          <button class="btn ghost" id="upPwdSave">改密码</button>
        </div>
      </div>
    </div>`;
  const $p = (id) => pane.querySelector('#' + id);

  // 当前版本 + 地址预填
  try {
    const j = await (await fetch('/api/update/state')).json();
    if (j.ok) { $p('upCur').textContent = 'v' + j.current; $p('upUrl').value = j.url || ''; }
    // v2.3.4：打包版（同事机）隐藏分发服务区块（用户定调：发布版本不能有
    // 这部分 UI）——发布者跑源码版才显示
    if (j.frozen) {
      const srv = pane.querySelector('[data-fx-srv]');
      if (srv) srv.style.display = 'none';
    }
  } catch(_) {}
  $p('upSrvState').textContent = '版本号单一来源 src/version.py；升级包经 sha1 校验后自动替换，旧版备份为 .bak 可手动回退。';

  $p('upSaveUrl').onclick = async () => {
    try {
      const r = await fetch('/api/update/url', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: $p('upUrl').value})});
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '保存失败', 3000, true); return; }
      $p('upUrl').value = j.url;   // 后端规范化（补尾 /）
      showBanner('升级地址已保存', 2500);
    } catch(e) { showBanner('保存失败: ' + e, 3000, true); }
  };

  $p('upCheck').onclick = async () => {
    const btn = $p('upCheck'), res = $p('upResult');
    btn.disabled = true; btn.textContent = '检查中…'; res.textContent = '';
    try {
      const j = await (await fetch('/api/update/check', {method: 'POST'})).json();
      if (j.unreachable) {
        res.innerHTML = '<span style="color:var(--neon-orange);">⚠ 连不上升级服务器（发布者机器可能没开机）</span>';
      } else if (j.has_update) {
        const mb = j.size ? ' · ' + (j.size / 1048576).toFixed(1) + ' MB' : '';
        res.innerHTML = `<div style="margin-bottom:6px;">✨ 发现新版本 <b>v${esc(j.latest)}</b>${mb}${j.date ? ' · ' + esc(j.date) : ''}</div>` +
          (j.notes ? `<div class="dd-sub" style="max-height:120px;overflow:auto;white-space:pre-wrap;">${esc(j.notes)}</div>` : '') +
          `<button class="btn primary" id="upApply" style="margin-top:8px;"><span style="vertical-align:-2.5px">${ICO16.upload}</span> 立即升级</button>`;
        res.querySelector('#upApply').onclick = () => _stDoApply(res);
      } else if (j.configured) {
        res.innerHTML = `✅ 已是最新版本（v${esc(j.current)}${j.latest ? '，服务器最新 v' + esc(j.latest) : ''}）`;
      } else {
        res.innerHTML = '<span style="color:var(--neon-orange);">⚠ 先填写升级服务器地址</span>';
      }
    } catch(e) { res.textContent = '检查失败: ' + e; }
    btn.disabled = false; btn.textContent = '检查更新';
  };

  async function _stDoApply(res) {
    const ok = await _ddConfirm('升级确认', '下载并校验通过后，工具将自动重启完成升级（黑窗一闪属正常）。\n继续？');
    if (!ok) return;
    res.innerHTML = '<div class="dd-sub">⬇ 下载并校验中…（内网一般几秒，完成后自动重启）</div>';
    try {
      const j = await (await fetch('/api/update/apply', {method: 'POST'})).json();
      if (!j.ok) { res.innerHTML = '<span style="color:var(--neon-red,var(--neon-orange));">✖ ' + esc(j.err || '升级准备失败') + '</span>'; return; }
      const j2 = await (await fetch('/api/update/run', {method: 'POST'})).json();
      if (!j2.ok) res.innerHTML = '<span style="color:var(--neon-red,var(--neon-orange));">✖ ' + esc(j2.err || '启动升级失败') + '</span>';
      // 成功：本进程即将退出，无需再渲染
    } catch(e) { res.textContent = '升级失败: ' + e; }
  }

  // 发布机分发服务状态 + 开关
  async function _srvRefresh() {
    try {
      const j = await (await fetch('/api/update_server/status')).json();
      if (!j.ok) { $p('upSrvInfo').textContent = '状态获取失败'; return; }
      const tgl = $p('upSrvToggle');
      tgl.textContent = j.running ? '■ 停止分发服务' : '▶ 开启分发服务';
      const ver = j.code_ver ? ` · 代码 v${esc(j.code_ver)}` : '';
      $p('upSrvInfo').innerHTML = j.running
        ? `🟢 运行中 · 已发布 <b>${esc(j.published || '（无版本——先跑打包.bat）')}</b>${ver}<br>` +
          `同事升级地址（发给同事）：<span style="font-family:var(--font-monospace,monospace);user-select:all;">${esc(j.url)}</span>`
        : `⚪ 未运行 · 分发目录 ${esc(j.dir)}${ver}`;
    } catch(_) { $p('upSrvInfo').textContent = '状态获取失败'; }
  }
  $p('upSrvToggle').onclick = async () => {
    const tgl = $p('upSrvToggle');
    tgl.disabled = true;
    try {
      const st = await (await fetch('/api/update_server/status')).json();
      const r = await fetch('/api/update_server/toggle', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: !st.running})});
      const j = await r.json();
      if (!j.ok) showBanner(j.err || '操作失败', 4000, true);
    } catch(e) { showBanner('操作失败: ' + e, 3000, true); }
    tgl.disabled = false;
    _srvRefresh();
  };
  $p('upPwdSave').onclick = async () => {
    try {
      const r = await fetch('/api/update_server/password', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: $p('upPwd').value})});
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '保存失败', 3000, true); return; }
      $p('upPwd').value = '';
      showBanner('门户密码已保存（已登录的浏览器不受影响，新登录用新密码）', 3500);
    } catch(e) { showBanner('保存失败: ' + e, 3000, true); }
  };
  _srvRefresh();
}

// ---- 数据目录子页：查看当前 → 改目录（校验+预览）→ 迁移（进度+结果）----
function _stRenderDataPane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-cur">
        <div class="dd-label">当前数据目录（日志 / 笔记 / 缓存）</div>
        <div class="dd-path" id="ddCurPath">—</div>
        <div class="dd-sub" id="ddCurStat"></div>
      </div>
      <div class="dd-cur" id="ddUsage">
        <div class="dd-label">存储占用</div>
        <div class="dd-sub" id="ddUsageBody">统计中…</div>
      </div>
      <div class="dd-form">
        <div class="dd-label">修改到</div>
        <div class="dd-row">
          <input type="text" id="ddNewPath" class="dd-input" spellcheck="false" placeholder="如 D:\\前端控制台">
          <button class="btn ghost icon-btn" id="ddPick" title="浏览选择目录">${ICO16.folderOpen}</button>
        </div>
        <div class="dd-sub">默认建议：<span id="ddDefault" style="font-family:var(--font-mono);"></span>（数据跟工具目录走，备份工具目录即备份全部；endpoint/config 留 home）</div>
        <div id="ddCheckMsg" class="dd-msg"></div>
      </div>
      <div class="dd-actions">
        <button class="btn ghost" id="ddOpenCur"><span style="vertical-align:-2.5px">${ICO16.folderOpen}</span> 打开当前目录</button>
        <span style="flex:1"></span>
        <button class="btn primary" id="ddMigrate" disabled>迁移数据</button>
      </div>
      <div class="dd-note" id="ddNote">迁移规则：命令库与笔记逐文件严格校验（不完整即失败不切换）；日志尽力复制；缓存自动重建。完成后自动删除旧目录。</div>
    </div>`;
  pane.querySelector('#ddOpenCur').onclick = async () => {
    try {
      const r = await fetch('/api/log_dir/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: pane.dataset.cur})});
      const j = await r.json();
      if (!j.ok) showBanner('打开失败: ' + (j.err || ''), 3000, true);
    } catch(e) { showBanner('打开失败: ' + e, 3000, true); }
  };
  pane.querySelector('#ddPick').onclick = async () => {
    try {
      const dir = await pywebview.api.pick_dir();
      if (dir) { pane.querySelector('#ddNewPath').value = dir; pane.querySelector('#ddNewPath').dispatchEvent(new Event('input')); }
    } catch(_) { showBanner('目录选择器暂不可用，可直接输入路径', 3000, true); }
  };
  // 输入即校验（check API：有效性+预览+告警）
  const inp = pane.querySelector('#ddNewPath');
  let _ckT = null;
  inp.addEventListener('input', () => {
    clearTimeout(_ckT);
    const btn = pane.querySelector('#ddMigrate');
    btn.disabled = true;
    _ckT = setTimeout(async () => {
      const v = inp.value.trim();
      const msgEl = pane.querySelector('#ddCheckMsg');
      if (!v) { msgEl.innerHTML = ''; return; }
      try {
        const r = await fetch('/api/data_dir/check', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: v})});
        const j = await r.json();
        if (!j.ok) { msgEl.innerHTML = `<span class="dd-err">✕ ${esc(j.err)}</span>`; return; }
        const prev = (j.preview || []).map(p => `${p.name} ${p.count} 项`).join(' · ');
        const warn = (j.warnings || []).length ? `<div class="dd-warn">⚠ ${esc(j.warnings[0])}</div>` : '';
        msgEl.innerHTML = `<span class="dd-ok">✓ 目录可用</span> 将迁移：${esc(prev)}${warn}`;
        btn.disabled = false;
      } catch(e) { msgEl.innerHTML = `<span class="dd-err">✕ 校验失败: ${esc(String(e))}</span>`; }
    }, 400);
  });
  // 迁移：确认弹窗 → 进度面板（阶段动画）→ 结果
  pane.querySelector('#ddMigrate').onclick = async () => {
    const target = inp.value.trim();
    if (!target) return;
    const ok = await _ddConfirm('迁移数据目录',
      `把命令库、笔记、日志复制到：\n${target}\n\n命令库与笔记严格校验（必须完整），日志尽力复制；完成后自动切换并删除旧目录。继续？`);
    if (!ok) return;
    // 过程 UI：覆盖式进度面板（迁移在同步请求里跑，无法真流式报进度——
    // 阶段动画按预期节奏推进，请求返回即终态，数据量小时最后一闪而过属正常）
    const prog = _ddProgress();
    prog.show(`正在复制到 ${target}`);
    const btn = pane.querySelector('#ddMigrate');
    btn.disabled = true;
    try {
      const r = await fetch('/api/data_dir/migrate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: target})});
      const j = await r.json();
      prog.hide();
      if (j.ok) {
        $('settingsModal').classList.remove('show');
        const parts = (j.copied || []).map(c => `${c.name}×${c.files}${c.skipped ? `（跳过${c.skipped}）` : ''}`).join('、');
        showBanner(`迁移完成（${parts}），旧目录已自动删除`, 6000);
        _ddRefreshDataPane(pane);   // 面板若再开显示新目录
      } else {
        showBanner('迁移失败（未切换，数据仍在原处）：' + (j.err || '未知'), 6000, true);
      }
    } catch(e) {
      prog.hide();
      showBanner('迁移请求失败: ' + e, 5000, true);
    }
  };
  _ddRefreshDataPane(pane);
}

async function _ddRefreshDataPane(pane) {
  try {
    const r = await fetch('/api/data_dir');
    const j = await r.json();
    if (!j.ok) return;
    pane.dataset.cur = j.dir;
    const pathEl = pane.querySelector('#ddCurPath');
    if (!pathEl) return;  // 期间已切到别的分区（pane 被重渲染）
    pathEl.textContent = j.dir;
    const subs = Object.entries(j.subdirs || {})
      .map(([k, v]) => `${k} ${v.count} 项 / ${_ddFmtSize(v.size)}`).join(' · ');
    pane.querySelector('#ddCurStat').textContent = subs + (j.total_size ? ` · 共 ${_ddFmtSize(j.total_size)}` : '');
    pane.querySelector('#ddDefault').textContent = j.default || '';
  } catch(_) {}
  // v3.5.92：存储感知——用户数据空间（可迁移）/工具数据空间（固定）/
  // 附件目录占用与自动清理策略（异步拉，不阻塞本页首屏）
  _ddRefreshUsage(pane);
}

async function _ddRefreshUsage(pane) {
  const el = pane.querySelector('#ddUsageBody');
  if (!el) return;
  try {
    const r = await fetch('/api/data_dir/usage');
    const j = await r.json();
    // 轻审R1-3：接口 ok=false 不能装「统计中…」——显式失败态
    if (!j.ok) { el.textContent = '统计不可用'; return; }
    if (!pane.querySelector('#ddUsageBody')) return;
    // v3.5.112（用户实锤「排布太丑」）：两行式行卡取代单行 flex-wrap——
    // 旧行长路径换行后大小/按钮掉行错位、条目间无分隔。新结构：第一行
    // 名称+说明(ellipsis)+大小右对齐(+清理钮)，第二行完整路径可断行，
    // 条目间 border-bottom 分隔
    const row = (t, u, extra) =>
      `<div style="padding:8px 0;border-bottom:1px solid var(--border);">` +
      `<div style="display:flex;gap:8px;align-items:center;">` +
      `<b style="font-weight:600;flex-shrink:0;">${t}</b>` +
      (extra ? `<span style="font-size:11px;color:var(--muted);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${extra}</span>` : '<span style="flex:1"></span>') +
      `<span style="font-variant-numeric:tabular-nums;color:var(--accent);font-weight:600;flex-shrink:0;">${_ddFmtSize(u.bytes)}</span>` +
      `</div>` +
      `<div style="font-family:var(--font-mono);font-size:11px;color:var(--muted);margin-top:3px;word-break:break-all;">${esc(u.path)}</div>` +
      `</div>`;
    // v3.5.93：可清理目标（衍生数据）——每行 🧹 手动清理，范围二选一
    //（按策略 / 全部清空）。笔记/命令库/配置不在此列，永远不可触达
    const POLICY = {
      uploads: '按策略：删超半年 + 超量缩至 80%',
      logs: '按策略：删 7 天前的串口日志',
      idx: '按策略：删 3 天未用的索引',
      cache: '清理可重建缓存（运行中被占用的文件自动跳过）',
      ask: '按策略：保留最近 500 个',
    };
    const DANGER = {
      uploads: '全部清空后，历史会话里引用的图片将失效',
      logs: '', idx: '', cache: '', ask: '',
    };
    const trows = Object.entries(j.targets || {}).map(([k, u]) =>
      `<div style="padding:8px 0;border-bottom:1px solid var(--border);">` +
      `<div style="display:flex;gap:8px;align-items:center;">` +
      `<b style="font-weight:500;flex-shrink:0;">${esc(u.name || k)}</b>` +
      `<span style="font-size:11px;color:var(--muted);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${POLICY[k] || ''}">${POLICY[k] || ''}</span>` +
      `<span style="font-variant-numeric:tabular-nums;color:var(--fg);flex-shrink:0;">${_ddFmtSize(u.bytes)}</span>` +
      `<button class="btn ghost icon-btn" data-ddclean="${k}" title="手动清理 ${esc(u.name || k)}" style="font-size:12px;flex-shrink:0;">${ICO16.trash}</button>` +
      `</div>` +
      `<div style="font-family:var(--font-mono);font-size:11px;color:var(--muted);margin-top:3px;word-break:break-all;">${esc(u.path)}</div>` +
      `</div>`).join('');
    el.innerHTML =
      row('用户数据空间（可迁移）', j.user || {}, '日志 / 笔记 / 缓存——随上方迁移走') +
      row('工具数据空间（固定）', j.tool || {}, '配置 / 附件 / 子进程状态——位置定死不随迁移') +
      `<div class="dd-label" style="margin-top:14px;">可清理项（衍生数据 · 笔记/命令库/配置不可触达）</div>` +
      trows +
      `<div id="ddCleanBar" style="display:none;gap:8px;align-items:center;flex-wrap:wrap;` +
        `margin-top:8px;padding:8px 10px;border:1px dashed var(--border);border-radius:8px;">` +
        `<span id="ddCleanTip" style="font-size:11px;color:var(--muted);flex:1;min-width:200px;"></span>` +
        `<button class="btn ghost" id="ddCleanPolicy">按策略清理</button>` +
        `<button class="btn ghost" id="ddCleanAll" style="color:#e5484d;">全部清空</button>` +
        `<button class="btn ghost" id="ddCleanCancel">取消</button></div>`;
    const bar = el.querySelector('#ddCleanBar');
    let pending = '';
    el.querySelectorAll('[data-ddclean]').forEach(b => {
      b.onclick = () => {
        pending = b.dataset.ddclean;
        bar.style.display = 'flex';
        bar.querySelector('#ddCleanTip').innerHTML =
          `清理「${esc((j.targets[pending] || {}).name || pending)}」：${POLICY[pending] || ''}` +
          (DANGER[pending] ? `<br>⚠ ${DANGER[pending]}` : '');
      };
    });
    bar.querySelector('#ddCleanCancel').onclick = () => { pending = ''; bar.style.display = 'none'; };
    const _do = async (mode) => {
      if (!pending) return;
      const tip = bar.querySelector('#ddCleanTip');
      tip.textContent = '清理中…';
      // 轻审R2-7：请求在途禁用全部清理入口（🧹 与确认条），防双击并发
      const btns = el.querySelectorAll('[data-ddclean], #ddCleanPolicy, #ddCleanAll');
      btns.forEach(b => b.disabled = true);
      try {
        const r = await fetch('/api/data_dir/clean', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({target: pending, mode})});
        const j2 = await r.json();
        if (!j2.ok) { showBanner('清理失败: ' + (j2.err || ''), 3000, true); }
        else showBanner(`已清理 ${j2.removed} 项，释放 ${_ddFmtSize(j2.freed || 0)}`, 3200);
      } catch(e) { showBanner('清理失败: ' + e, 3000, true); }
      pending = '';
      bar.style.display = 'none';
      _ddRefreshUsage(pane);
    };
    bar.querySelector('#ddCleanPolicy').onclick = () => _do('policy');
    bar.querySelector('#ddCleanAll').onclick = () => _do('all');
  } catch(_) { el.textContent = '统计不可用'; }
}

// ---- 文件关联子页：各后缀 接管/还原 状态 + 全选/批量操作 ----
async function _stRenderAssocPane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-label">文件关联接管</div>
      <div class="dd-sub">「接管」后，双击所选类型文件用本工具打开（编辑器/阅读器自动分发）；「还原」恢复系统原默认（如 txt 还原回记事本）。只改当前用户注册表（HKCU），完全可逆。</div>
      <div class="assoc-list" id="assocList">加载中…</div>
      <div class="dd-actions" style="margin-top:14px;">
        <button class="btn ghost" id="assocAll" disabled>全部接管</button>
        <button class="btn ghost" id="assocRestoreAll" disabled>全部还原</button>
        <span class="dd-sub" id="assocHint" style="margin-left:auto;">若双击仍走旧程序：系统「打开方式→选择另一应用→始终」选一次本工具</span>
      </div>
      <div class="dd-note">接管时备份各后缀原默认值，还原即恢复；全部还原后自动清理注册的 ProgId（不留残余）。工具升级/移动位置后再次接管即可刷新命令路径。</div>
    </div>`;
  const list = pane.querySelector('#assocList');
  const render = items => {
    list.innerHTML = items.map(it => `
      <div class="assoc-item">
        <span class="ext">${esc(it.ext)}</span>
        <span class="st ${it.taken ? 'on' : ''}">${it.taken ? '✓ 已接管' : '— 系统默认'}</span>
        <button class="btn ghost assoc-btn" data-ext="${esc(it.ext)}" data-act="${it.taken ? 'restore' : 'takeover'}">${it.taken ? '还原' : '接管'}</button>
      </div>`).join('');
    list.querySelectorAll('.assoc-btn').forEach(btn => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const r = await fetch('/api/assoc/' + btn.dataset.act, {method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({exts: [btn.dataset.ext]})});
          const j = await r.json();
          if (!j.ok) showBanner((btn.dataset.act === 'takeover' ? '接管' : '还原') + '失败：' + (j.err || ''), 4000, true);
          else showBanner((btn.dataset.act === 'takeover' ? '已接管 ' : '已还原 ') + btn.dataset.ext, 2500);
        } catch(e) { showBanner('请求失败: ' + e, 4000, true); }
        _stRefreshAssoc(pane);
      };
    });
    const anyOn = items.some(i => i.taken), anyOff = items.some(i => !i.taken);
    pane.querySelector('#assocAll').disabled = !anyOff;
    pane.querySelector('#assocRestoreAll').disabled = !anyOn;
  };
  pane._assocRender = render;   // 刷新函数挂 pane（_stRefreshAssoc 复用）
  _stRefreshAssoc(pane);
  pane.querySelector('#assocAll').onclick = () => _assocBulk(pane, 'takeover');
  pane.querySelector('#assocRestoreAll').onclick = () => _assocBulk(pane, 'restore');
}

async function _stRefreshAssoc(pane) {
  const list = pane.querySelector('#assocList');
  if (!list) return;   // 已切到别的分区
  try {
    const r = await fetch('/api/assoc/status');
    const j = await r.json();
    if (j.ok && pane._assocRender) pane._assocRender(j.items);
  } catch(_) { list.innerHTML = '<div class="dd-sub">状态读取失败</div>'; }
}

async function _assocBulk(pane, act) {
  try {
    const st = await (await fetch('/api/assoc/status')).json();
    const exts = (st.items || []).filter(i => act === 'takeover' ? !i.taken : i.taken).map(i => i.ext);
    if (!exts.length) return;
    const r = await fetch('/api/assoc/' + act, {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({exts})});
    const j = await r.json();
    if (!j.ok) showBanner((act === 'takeover' ? '接管' : '还原') + '失败：' + (j.err || ''), 4000, true);
    else showBanner((act === 'takeover' ? '已接管 ' : '已还原 ') + exts.join(' '), 3000);
  } catch(e) { showBanner('请求失败: ' + e, 4000, true); }
  _stRefreshAssoc(pane);
}

function openSettingsPanel(section) {
  const m = _stModal();
  // 不指定分区 → 回到上次所在处（首次打开落终端设置，原默认不变）
  _stShowSection(m, section || localStorage.getItem('fc_st_sec') || 'term');
  m.classList.add('show');
}

// 迁移过程进度面板：环形动画 + 阶段文案（复制→校验→切换），请求返回即终态
function _ddProgress() {
  let m = $('ddProgressModal');
  if (!m) {
    m = document.createElement('div');
    m.className = 'modal dd-prog';
    m.id = 'ddProgressModal';
    m.innerHTML = `
      <div class="box" style="max-width:380px;">
        <div class="dd-prog-body">
          <div class="dd-prog-ring"><div class="dd-prog-dot"></div></div>
          <div class="dd-prog-title" id="ddProgTitle">正在迁移</div>
          <div class="dd-prog-stage" id="ddProgStage">复制文件中</div>
          <div class="dd-prog-sub">复制并校验通过后自动切换，旧目录保留。请勿关闭窗口。</div>
        </div>
      </div>`;
    document.body.appendChild(m);
  }
  const stages = ['复制文件中', '逐文件校验中', '切换数据目录'];
  let si = 0, timer = null;
  return {
    show(title) {
      m.querySelector('#ddProgTitle').textContent = title || '正在迁移';
      m.querySelector('#ddProgStage').textContent = stages[0];
      si = 0;
      m.classList.add('show');
      // 阶段文案按典型节奏推进（复制最久、校验次之、切换瞬时）；
      // 请求返回后 hide() 终止计时器，不依赖动画走完
      clearInterval(timer);
      timer = setInterval(() => {
        si = Math.min(si + 1, stages.length - 1);
        m.querySelector('#ddProgStage').textContent = stages[si];
      }, 4000);
    },
    hide() {
      clearInterval(timer);
      m.classList.remove('show');
    },
  };
}

// 应用风格确认弹窗（与 hex/editor 的 confirm 同款，不用原生 confirm）
// 坑（曾点确定无反应）：onclick 只在首次创建时绑定——第二次调用复用旧闭包里的
// resolve，旧 Promise 已 settled，新 Promise 永远 pending。照 _hxConfirm 抄：
// 每次调用都重绑，resolve 消费当前这一次的。
function _ddConfirm(title, msg) {  return new Promise(resolve => {
    let m = $('ddConfirmModal');
    if (!m) {
      m = document.createElement('div');
      m.className = 'modal';
      m.id = 'ddConfirmModal';
      m.innerHTML = `
        <div class="box" style="max-width:400px;">
          <div class="head"><strong id="ddcTitle"></strong>
            <div class="head-actions"><button class="btn ghost icon-btn" id="ddcClose">✕</button></div></div>
          <div style="padding:16px 20px;white-space:pre-wrap;font-size:12px;line-height:1.7;color:var(--fg);" id="ddcMsg"></div>
          <div style="display:flex;gap:10px;justify-content:flex-end;padding:0 20px 18px;">
            <button class="btn ghost" id="ddcNo">取消</button>
            <button class="btn primary" id="ddcYes">确定</button>
          </div>
        </div>`;
      document.body.appendChild(m);
    }
    m.querySelector('#ddcTitle').textContent = title;
    m.querySelector('#ddcMsg').textContent = msg;
    const finish = v => { m.classList.remove('show'); resolve(v); };
    m.querySelector('#ddcYes').onclick = () => finish(true);
    m.querySelector('#ddcNo').onclick = () => finish(false);
    m.querySelector('#ddcClose').onclick = () => finish(false);
    m.classList.add('show');
  });
}

// ---- 顶栏机器人 logo 即按钮：点击开设置弹窗 ----
(function initSettingsButton() {
  const logoIcon = document.querySelector('.logo .icon');
  if (logoIcon) {
    logoIcon.title = '设置（数据目录 / 外观主题）';
    logoIcon.style.cursor = 'pointer';
    // 不传分区：回到上次所在分区（曾硬编码 'term'——每次点开设置都被
    // 拉回终端设置，在 API 面板配置的用户实测「莫名跳转」）
    logoIcon.addEventListener('click', () => openSettingsPanel());
  }
})();

// ---- 首启引导：config 无 data_dir_prompted 时弹一次（用户选择数据目录）----
// 坑（曾每次启动都弹）：早期拿「data_dir 是否存在」当首启依据——用户点取消/不迁移
// 就永远不写 data_dir → 每次启动重弹。改用独立标记 data_dir_prompted：
// 引导展示过一次即写入，与用户是否迁移解耦。
(async function initDataDirGuide() {
  try {
    const r = await fetch('/api/data_dir');
    const j = await r.json();
    if (!j.ok) return;
    const r2 = await fetch('/api/theme');
    const cfg = await r2.json();
    if (cfg.data_dir_prompted) return;   // 引导已展示过，不再弹
    // 立即标记（在弹窗前写：进程崩溃/用户强关也不会下次重弹）
    fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({data_dir_prompted: true})});
    const ok = await _ddConfirm('首次启动 · 选择数据目录',
      `日志、笔记、缓存等数据默认保存到：\n${j.default}\n\n数据跟工具目录走（备份工具目录即备份全部）。现在就查看或修改吗？`);
    if (ok) openSettingsPanel('data');
  } catch(_) {}
})();
