// ============================================================
// 数据目录管理：顶栏机器人 logo 即功能按钮，点开设置面板。
// 面板功能：查看当前数据目录 → 改目录（校验+预览）→ 迁移（进度+结果）。
// 首次启动（config 无 data_dir）弹引导，默认建议 D:\前端控制台。
// 迁移铁律：先复制后切换，失败不切换，旧目录保留——数据绝不丢。
// ============================================================

function _ddFmtSize(n) {
  if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

function _ddModal() {
  let m = $('dataDirModal');
  if (m) return m;
  m = document.createElement('div');
  m.className = 'modal';
  m.id = 'dataDirModal';
  m.innerHTML = `
    <div class="box dd-box">
      <div class="head">
        <strong>📁 数据目录</strong>
        <div class="head-actions"><button class="btn ghost icon-btn" id="ddClose">✕</button></div>
      </div>
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
          <button class="btn ghost" id="ddCancel">取消</button>
          <button class="btn primary" id="ddMigrate" disabled>迁移数据</button>
        </div>
        <div class="dd-note" id="ddNote">迁移规则：先完整复制并逐文件校验，全部通过才切换；失败不动原目录；旧目录保留，确认后可手动删。</div>
      </div>
    </div>`;
  document.body.appendChild(m);
  m.querySelector('#ddClose').onclick = m.querySelector('#ddCancel').onclick = () => m.classList.remove('show');
  m.querySelector('#ddOpenCur').onclick = async () => {
    try {
      const r = await fetch('/api/log_dir/open', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: m.dataset.cur})});
      const j = await r.json();
      if (!j.ok) showBanner('打开失败: ' + (j.err || ''), 3000, true);
    } catch(e) { showBanner('打开失败: ' + e, 3000, true); }
  };
  m.querySelector('#ddPick').onclick = async () => {
    try {
      const dir = await pywebview.api.pick_dir();
      if (dir) { m.querySelector('#ddNewPath').value = dir; m.querySelector('#ddNewPath').dispatchEvent(new Event('input')); }
    } catch(_) { showBanner('目录选择器暂不可用，可直接输入路径', 3000, true); }
  };
  // 输入即校验（check API：有效性+预览+告警）
  const inp = m.querySelector('#ddNewPath');
  let _ckT = null;
  inp.addEventListener('input', () => {
    clearTimeout(_ckT);
    const btn = m.querySelector('#ddMigrate');
    btn.disabled = true;
    _ckT = setTimeout(async () => {
      const v = inp.value.trim();
      const msgEl = m.querySelector('#ddCheckMsg');
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
  m.querySelector('#ddMigrate').onclick = async () => {
    const target = inp.value.trim();
    if (!target) return;
    const ok = await _ddConfirm('迁移数据目录',
      `把全部日志、笔记、命令库复制到：\n${target}\n\n复制并校验通过后自动切换，旧目录完整保留。继续？`);
    if (!ok) return;
    // 过程 UI：覆盖式进度面板（迁移在同步请求里跑，无法真流式报进度——
    // 阶段动画按预期节奏推进，请求返回即终态，数据量小时最后一闪而过属正常）
    const prog = _ddProgress();
    prog.show(`正在复制到 ${target}`);
    const btn = m.querySelector('#ddMigrate');
    btn.disabled = true;
    try {
      const r = await fetch('/api/data_dir/migrate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({dir: target})});
      const j = await r.json();
      prog.hide();
      btn.textContent = '迁移数据';
      if (j.ok) {
        m.classList.remove('show');
        const parts = (j.copied || []).map(c => `${c.name}×${c.files}`).join('、');
        showBanner(`迁移完成（${parts}）。旧目录已保留，确认正常后可手动删除：${j.old_dir}`, 8000);
        _ddRefreshPanel(m);   // 面板若再开显示新目录
      } else {
        showBanner('迁移失败（未切换，数据仍在原处）：' + (j.err || '未知'), 6000, true);
      }
    } catch(e) {
      prog.hide();
      btn.textContent = '迁移数据';
      showBanner('迁移请求失败: ' + e, 5000, true);
    }
  };
  return m;
}

async function _ddRefreshPanel(m) {
  try {
    const r = await fetch('/api/data_dir');
    const j = await r.json();
    if (!j.ok) return;
    m.dataset.cur = j.dir;
    m.querySelector('#ddCurPath').textContent = j.dir;
    const subs = Object.entries(j.subdirs || {})
      .map(([k, v]) => `${k} ${v.count} 项 / ${_ddFmtSize(v.size)}`).join(' · ');
    m.querySelector('#ddCurStat').textContent = subs + (j.total_size ? ` · 共 ${_ddFmtSize(j.total_size)}` : '');
    m.querySelector('#ddDefault').textContent = j.default || '';
  } catch(_) {}
}

function openDataDirPanel() {
  const m = _ddModal();
  _ddRefreshPanel(m);
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

// ---- 顶栏机器人 logo 即按钮：点击开数据目录面板 ----
(function initDataDirButton() {
  const logoIcon = document.querySelector('.logo .icon');
  if (logoIcon) {
    logoIcon.title = '数据目录设置（日志/笔记/缓存的位置与迁移）';
    logoIcon.style.cursor = 'pointer';
    logoIcon.addEventListener('click', openDataDirPanel);
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
    if (ok) openDataDirPanel();
  } catch(_) {}
})();
