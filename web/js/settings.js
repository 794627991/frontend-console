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
  { id: 'api',   icon: '🔑', name: 'API 配置', desc: 'Claude API Token / settings.json' },
  { id: 'termkeys', icon: '⌨', name: '终端快捷键', desc: '右键行为 / 自动复制' },
  { id: 'data',  icon: '📁', name: '数据目录', desc: '日志 / 笔记 / 缓存的位置与迁移' },
  { id: 'assoc', icon: '🔗', name: '文件关联', desc: '接管/还原 txt 等文本文件的双击打开方式' },
  { id: 'theme', icon: '🎨', name: '外观主题', desc: '整窗配色切换' },
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
        <strong>⚙ 设置</strong>
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
  m.querySelectorAll('.set-nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.sec === sec));
  const pane = m.querySelector('#stPane');
  if (sec === 'api') _stRenderApiPane(pane);
  else if (sec === 'termkeys') _stRenderTermKeysPane(pane);
  else if (sec === 'data') _stRenderDataPane(pane);
  else if (sec === 'assoc') _stRenderAssocPane(pane);
  else if (sec === 'theme') _stRenderThemePane(pane);
}

// ---- 终端快捷键子页：右键行为 + 自动复制（config.json term_keys）----
const _TK_OPTIONS = [
  { v: 'ctrl_menu',  n: 'Ctrl + 右键 → 弹菜单', d: '默认。普通右键为 xterm 原生行为' },
  { v: 'right_menu', n: '右键 → 直接弹菜单', d: '不需按 Ctrl，单右键即出菜单' },
  { v: 'right_paste', n: '右键 → 直接粘贴', d: '单右键立即粘贴剪贴板（PuTTY 默认风格）' },
];
async function _stRenderTermKeysPane(pane) {
  let tk = { right_action: 'ctrl_menu', auto_copy: false };
  try {
    const j = await (await fetch('/api/theme')).json();
    if (j.ok && j.term_keys) tk = j.term_keys;
  } catch(_) {}
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-label">终端快捷键映射</div>
      <div class="dd-sub">终端内复制/粘贴/右键行为定制。改动立即生效并持久保存。</div>
      <div class="dd-cur" style="margin-top:12px;">
        <div class="dd-label">右键行为</div>
        <div class="dd-row" style="margin-top:6px;display:flex;flex-direction:column;gap:8px;">
          ${_TK_OPTIONS.map(o => `
            <label style="display:flex;align-items:flex-start;gap:8px;cursor:pointer;">
              <input type="radio" name="tkRight" value="${o.v}" ${tk.right_action === o.v ? 'checked' : ''} style="margin-top:3px;">
              <span><span style="font-weight:600;">${o.n}</span><br><span style="color:var(--muted);font-size:12px;">${o.d}</span></span>
            </label>`).join('')}
        </div>
      </div>
      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">选中自动复制</div>
        <label style="display:flex;align-items:center;gap:8px;margin-top:6px;cursor:pointer;">
          <input type="checkbox" id="tkAutoCopy" ${tk.auto_copy ? 'checked' : ''}>
          <span>鼠标选中终端文本后松开即自动复制（PuTTY 风格）</span>
        </label>
      </div>
      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">固定快捷键（恒可用，不受上面配置影响）</div>
        <div class="dd-sub" style="margin-top:4px;">
          Ctrl+C 复制选中 / 发 ^C 中断　·　Ctrl+V 粘贴　·　Ctrl+F 查找<br>
          Shift+右键 粘贴　·　Ctrl+右键 弹菜单（右键行为=ctrl_menu 时）
        </div>
      </div>
      <div style="margin-top:16px;">
        <button class="btn primary" id="tkSave">保存</button>
      </div>
    </div>`;
  pane.querySelector('#tkSave').onclick = async () => {
    const ra = pane.querySelector('input[name="tkRight"]:checked');
    const ac = pane.querySelector('#tkAutoCopy').checked;
    try {
      await fetch('/api/theme', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({term_keys: {right_action: ra ? ra.value : 'ctrl_menu', auto_copy: ac}})});
      // 已开终端连接的配置热更新（下次 contextmenu 读 conn.termKeys）
      Object.values(connections).forEach(c => {
        if (c.termKeys) {
          c.termKeys.right_action = ra ? ra.value : 'ctrl_menu';
          c.termKeys.auto_copy = ac;
        }
      });
      showBanner('终端快捷键已保存');
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
}

// ---- API 配置子页：Token 唯一可改；BASE_URL 只读显示；快捷打开 settings.json ----
async function _stRenderApiPane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-label">Claude API 配置</div>
      <div class="dd-sub">首次安装 Claude 后必须填入 API Token 才能使用。写入 ~/.claude/settings.json。</div>
      <div class="dd-cur" style="margin-top:12px;">
        <div class="dd-label">API Token（ANTHROPIC_AUTH_TOKEN）</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;">
          <input type="text" id="apiTokenInput" class="dd-input" spellcheck="false"
                 placeholder="sk-…" style="flex:1;">
          <button class="btn primary" id="apiTokenSave">保存</button>
        </div>
        <div class="dd-sub" id="apiTokenState" style="margin-top:6px;"></div>
      </div>
      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">BASE_URL（内网网关，固定不可改）</div>
        <div class="dd-path" id="apiBaseUrl" style="user-select:text;">—</div>
      </div>
      <div class="dd-cur" style="margin-top:14px;">
        <div class="dd-label">离线安装包目录</div>
        <div class="dd-row" style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <div class="dd-path" id="apiPkgDir" style="flex:1;user-select:text;">—</div>
          <button class="btn ghost icon-btn" id="apiPkgPick" title="浏览选择目录">📂</button>
          <button class="btn ghost icon-btn" id="apiPkgReset" title="清除自定义，恢复默认（工具目录 offline_pkg）">↺</button>
        </div>
        <div class="dd-sub" style="margin-top:4px;">Claude 离线安装资源（Git 安装器 / Node MSI / claude-code 包）的搜索目录。默认随工具分发的 offline_pkg；可改指向自己的资源目录（zip 包需先解压，或用安装窗「制作离线包」生成的目录）。</div>
      </div>
      <div class="dd-actions" style="margin-top:16px;">
        <button class="btn ghost" id="apiOpenSettings" title="在资源管理器中定位 settings.json">📂 打开 settings.json</button>
        <button class="btn ghost" id="apiProvision" title="恢复 Claude 默认配置（settings 缺省项补全 + statusline 重铺；已有配置不动，statusline 强制覆盖）">↺ 恢复 Claude 默认配置</button>
      </div>
      <div class="dd-note" id="apiNote"></div>
    </div>`;
  const stateEl = pane.querySelector('#apiTokenState');
  const refresh = async () => {
    try {
      const j = await (await fetch('/api/claude/api_config')).json();
      stateEl.innerHTML = j.has_token
        ? `<span style="color:var(--neon-green);">✓ 已配置</span> <span style="font-family:var(--font-mono);">${esc(j.token_masked)}</span>`
        : '<span style="color:var(--neon-red);">✕ 未配置——首次安装后必须填入</span>';
      pane.querySelector('#apiBaseUrl').textContent = j.base_url || j.default_base_url;
      pane.querySelector('#apiNote').textContent = 'settings.json 路径：' + j.settings_path;
    } catch(e) { stateEl.textContent = '读取失败: ' + e; }
    try {
      const st = await (await fetch('/api/claude/setup_status')).json();
      pane.querySelector('#apiPkgDir').textContent = st.offline_pkg_dir || '默认（工具目录 offline_pkg）';
    } catch(_) {}
  };
  refresh();
  // 离线安装包目录：浏览选择 / 清除自定义
  pane.querySelector('#apiPkgPick').onclick = async () => {
    try {
      const dir = await pywebview.api.pick_dir();
      if (!dir) return;
      const r = await fetch('/api/claude/setup_pkg_dir', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir})});
      const j = await r.json();
      if (!j.ok) { showBanner('设置失败: ' + (j.err || ''), 4000, true); return; }
      showBanner('离线安装包目录已更新');
      refresh();
    } catch(e) { showBanner('目录选择器不可用，或请求失败: ' + e, 4000, true); }
  };
  pane.querySelector('#apiPkgReset').onclick = async () => {
    try {
      await fetch('/api/claude/setup_pkg_dir', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: ''})});
      showBanner('已恢复默认离线包目录');
      refresh();
    } catch(_) {}
  };
  pane.querySelector('#apiTokenSave').onclick = async () => {
    const t = pane.querySelector('#apiTokenInput').value.trim();
    if (!t) { showBanner('请输入 API Token', 3000, true); return; }
    try {
      const r = await fetch('/api/claude/api_config', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({token: t})});
      const j = await r.json();
      if (!j.ok) { showBanner('保存失败: ' + (j.err || ''), 4000, true); return; }
      showBanner('API Token 已保存');
      pane.querySelector('#apiTokenInput').value = '';
      refresh();
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

// ---- 数据目录子页：查看当前 → 改目录（校验+预览）→ 迁移（进度+结果）----
function _stRenderDataPane(pane) {
  pane.innerHTML = `
    <div class="dd-body">
      <div class="dd-cur">
        <div class="dd-label">当前数据目录（日志 / 笔记 / 缓存）</div>
        <div class="dd-path" id="ddCurPath">—</div>
        <div class="dd-sub" id="ddCurStat"></div>
      </div>
      <div class="dd-form">
        <div class="dd-label">修改到</div>
        <div class="dd-row">
          <input type="text" id="ddNewPath" class="dd-input" spellcheck="false" placeholder="如 D:\\前端控制台">
          <button class="btn ghost icon-btn" id="ddPick" title="浏览选择目录">📂</button>
        </div>
        <div class="dd-sub">默认建议：<span id="ddDefault" style="font-family:var(--font-mono);"></span>（数据跟工具目录走，备份工具目录即备份全部；endpoint/config 留 home）</div>
        <div id="ddCheckMsg" class="dd-msg"></div>
      </div>
      <div class="dd-actions">
        <button class="btn ghost" id="ddOpenCur">📂 打开当前目录</button>
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

// ---- 外观主题子页：与顶栏换肤下拉同源（THEMES/applyTheme 由 theme.js 提供）----
function _stRenderThemePane(pane) {
  pane.innerHTML = `<div class="dd-body"><div class="dd-label">配色主题</div><div class="set-theme-grid" id="stThemeGrid"></div>
    <div class="dd-note">整窗即时换色（终端/编辑器/阅读面同步）；顶栏「🎨 换肤」按钮同样可用。</div></div>`;
  const grid = pane.querySelector('#stThemeGrid');
  const cur = document.documentElement.getAttribute('data-theme') || 'deepblue';
  if (typeof THEMES === 'undefined') {
    grid.innerHTML = '<div class="dd-sub">主题模块未加载</div>';
    return;
  }
  for (const [g, label] of [['dark', '暗色系'], ['light', '亮色系']]) {
    const head = document.createElement('div');
    head.className = 'set-theme-group';
    head.textContent = label;
    grid.appendChild(head);
    THEMES.filter(t => t.group === g).forEach(t => {
      const item = document.createElement('div');
      item.className = 'theme-item' + (t.id === cur ? ' active' : '');
      item.innerHTML = `<div class="theme-swatch" data-theme="${t.id}"></div>
        <div class="theme-info"><div class="name">${t.name}</div><div class="desc">${t.desc}</div></div>
        ${t.id === cur ? '<span class="theme-check">✓</span>' : ''}`;
      item.onclick = () => {
        applyTheme(t.id, true);
        showBanner('已切换主题：' + t.name);
        _stRenderThemePane(pane);   // 重渲染刷新选中态
      };
      grid.appendChild(item);
    });
  }
}

function openSettingsPanel(section) {
  const m = _stModal();
  _stShowSection(m, section || 'data');
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
    logoIcon.addEventListener('click', () => openSettingsPanel('data'));
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
