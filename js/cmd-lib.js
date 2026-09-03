let _cmdLibCache = null;
async function loadCmdLib() {
  if (_cmdLibCache) return _cmdLibCache;
  try {
    const r = await fetch('/api/cmd_lib');
    const j = await r.json();
    _cmdLibCache = j.lib || [];
  } catch (e) { _cmdLibCache = []; }
  return _cmdLibCache;
}
async function saveCmdLib(lib) {
  _cmdLibCache = lib;
  try {
    await fetch('/api/cmd_lib', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lib })
    });
  } catch (e) {}
}
async function renderCmdPane() {
  // 命令库
  const lib = await loadCmdLib();
  const libEl = $('cmdLibrary');
  if (!lib.length) {
    libEl.innerHTML = '<div class="cmd-empty">点击上方添加常用命令（支持备注名）</div>';
  } else {
    libEl.innerHTML = lib.map((c, i) => {
      const showName = c.name && c.name.trim();
      const title = (showName ? `【${esc(c.name)}】\n` : '') + esc(c.cmd);
      // 名称/命令都可点击编辑（弹出模态框）；命令内容只读展示
      return `<div class="cmd-item" title="${title}">
        <span class="text cmd-edit-trigger" data-i="${i}" title="点击编辑" style="display:flex;flex-direction:column;line-height:1.3;min-width:0;flex:1;cursor:pointer">
          ${showName ? `<span class="name">${esc(c.name)}</span><span class="cmd-sub">${esc(c.cmd)}</span>` : `<span class="cmd-no-name">＋ 备注</span><span class="cmd-sub">${esc(c.cmd)}</span>`}
        </span>
        <button class="run" data-i="${i}">发送</button>
        <button class="edit" data-i="${i}" title="编辑">✎</button>
        <button class="del" data-i="${i}" title="删除">✕</button>
      </div>`;
    }).join('');
    libEl.querySelectorAll('.run').forEach(b => b.onclick = () => runCmdFromLib(parseInt(b.dataset.i)));
    libEl.querySelectorAll('.del').forEach(b => b.onclick = async () => {
      const lib2 = await loadCmdLib(); lib2.splice(parseInt(b.dataset.i), 1); await saveCmdLib(lib2); renderCmdPane();
    });
    // 点击名称区或编辑按钮 → 弹出编辑模态框（名称+命令都可改）
    const openEdit = async (i) => {
      const lib2 = await loadCmdLib();
      if (!lib2[i]) return;
      openCmdEditModal(i, lib2[i].name || '', lib2[i].cmd);
    };
    libEl.querySelectorAll('.cmd-edit-trigger').forEach(el => el.onclick = () => openEdit(parseInt(el.dataset.i)));
    libEl.querySelectorAll('.edit').forEach(b => b.onclick = () => openEdit(parseInt(b.dataset.i)));
    // ---- 拖拽排序：长按条目拖到目标位置，松手保存新顺序 ----
    // HTML5 drag：dragstart 记起点，dragover 判落点并实时移动 DOM（所见即所得），
    // drop 后按 DOM 顺序重建 lib 数组一次保存。拖拽中禁止编辑点击误触。
    let dragFrom = -1;
    libEl.querySelectorAll('.cmd-item').forEach((item, i) => {
      item.draggable = true;
      item.addEventListener('dragstart', e => {
        dragFrom = i;
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        try { e.dataTransfer.setData('text/plain', String(i)); } catch (_) {}  // Firefox 必需
      });
      item.addEventListener('dragend', () => {
        item.classList.remove('dragging');
        libEl.querySelectorAll('.cmd-item').forEach(el => el.classList.remove('drag-over'));
        dragFrom = -1;
      });
      item.addEventListener('dragover', e => {
        e.preventDefault();  // 允许 drop
        e.dataTransfer.dropEffect = 'move';
        if (dragFrom < 0 || dragFrom === i) return;
        // 实时移动：向下拖插到目标后，向上拖插到目标前（贴合拖动方向直觉）
        const items = Array.from(libEl.querySelectorAll('.cmd-item'));
        const fromEl = items[dragFrom], toEl = items[i];
        if (!fromEl || !toEl || fromEl === toEl) return;
        libEl.insertBefore(fromEl, dragFrom < i ? toEl.nextSibling : toEl);
        dragFrom = i;  // 移动后起点索引更新为当前位置
      });
    });
    libEl.addEventListener('drop', async e => {
      e.preventDefault();
      if (dragFrom < 0 && e.dataTransfer) {
        // 外部拖入不处理（只支持库内排序）
        return;
    }
      // 按 DOM 顺序重建 lib：map 原 data-i → 新位置
      const old = await loadCmdLib();
      const newLib = Array.from(libEl.querySelectorAll('.cmd-item'))
        .map(el => old[parseInt(el.dataset.i)])
        .filter(Boolean);
      if (newLib.length !== old.length) { renderCmdPane(); return; }  // 异常兜底：重渲染还原
      await saveCmdLib(newLib);
      renderCmdPane();
    });
    libEl.addEventListener('dragover', e => e.preventDefault());  // 允许 drop 事件触发
  }
  // 最近命令
  if (activePortId) {
    fetch('/api/history?port_id=' + encodeURIComponent(activePortId))
      .then(r => r.json()).then(j => {
        const hist = j.history || [];
        const rec = $('cmdRecent');
        if (!hist.length) { rec.innerHTML = '<div class="cmd-empty">暂无历史</div>'; return; }
        rec.innerHTML = hist.slice(-15).reverse().map(c =>
          `<div class="cmd-item"><span class="text" title="${esc(c)}">${esc(c)}</span><button class="run" data-cmd="${esc(c)}">重发</button></div>`
        ).join('');
        rec.querySelectorAll('.run').forEach(b => b.onclick = () => sendCmd(b.dataset.cmd));
      }).catch(() => {});
  } else {
    $('cmdRecent').innerHTML = '<div class="cmd-empty">无活动连接</div>';
  }
}
async function runCmdFromLib(i) {
  const lib = await loadCmdLib();
  if (lib[i]) sendCmd(lib[i].cmd);
}
// 命令编辑模态框：名称+命令都可改
let _cmdEditIndex = -1;
function openCmdEditModal(i, name, cmd) {
  _cmdEditIndex = i;
  $('cmdEditName').value = name || '';
  $('cmdEditCmd').value = cmd || '';
  $('cmdEditModal').classList.add('show');
  setTimeout(() => $('cmdEditName').focus(), 50);
}
function closeCmdEditModal() { $('cmdEditModal').classList.remove('show'); _cmdEditIndex = -1; }
$('cmdEditClose').onclick = closeCmdEditModal;
$('cmdEditCancel').onclick = closeCmdEditModal;
$('cmdEditModal').onclick = (e) => { if (e.target === $('cmdEditModal')) closeCmdEditModal(); };
$('cmdEditSave').onclick = async () => {
  const name = $('cmdEditName').value.trim();
  const cmd = $('cmdEditCmd').value.trim();
  if (!cmd) { closeCmdEditModal(); return; }  // 命令不能为空
  const lib = await loadCmdLib();
  if (_cmdEditIndex < 0 || !lib[_cmdEditIndex]) { closeCmdEditModal(); return; }
  lib[_cmdEditIndex].name = name;
  lib[_cmdEditIndex].cmd = cmd;
  await saveCmdLib(lib);
  closeCmdEditModal();
  renderCmdPane();
};
$('cmdEditCmd').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('cmdEditSave').click(); });
$('cmdEditName').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('cmdEditCmd').focus(); });
function sendCmd(cmd) {
  if (!activePortId) { showBanner('无活动连接', 3000, true); return; }
  fetch('/api/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ port_id: activePortId, cmd }) });
  showBanner('已发送：' + cmd);
}
$('cmdAddBtn').onclick = async () => {
  const name = $('cmdAddName').value.trim();
  const cmd = $('cmdAddInput').value.trim();
  if (!cmd) return;
  const lib = await loadCmdLib();
  // 去重：命令内容相同则更新名称（不重复添加）
  const exist = lib.findIndex(c => c.cmd === cmd);
  if (exist >= 0) { lib[exist].name = name || lib[exist].name; }
  else { lib.push({ name, cmd }); }
  await saveCmdLib(lib);
  $('cmdAddName').value = '';
  $('cmdAddInput').value = '';
  renderCmdPane();
};
$('cmdAddInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('cmdAddBtn').click(); });
$('cmdAddName').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('cmdAddInput').focus(); });

// 命令库 sheet 切换
document.querySelectorAll('.cmd-sheet-tab').forEach(tab => {
  tab.onclick = () => {
    const sheet = tab.dataset.sheet;
    document.querySelectorAll('.cmd-sheet-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.cmd-sheet-pane').forEach(p => p.classList.toggle('active', p.dataset.sheet === sheet));
    if (sheet === 'recent') renderCmdPane();  // 切到最近命令时刷新
  };
});

// ============================================================
// 日志查看 tab（G 级虚拟列表 + 底部查找分栏）
// ============================================================
// 复用 connections[port_id] 模型，kind='log'。每个日志 tab 独立 logState（替代旧全局 histState）。
// 虚拟列表算法不变：inner 钳制 MAX_SCROLL_H 突破 Chrome 33.5M 上限，viewport 跟随 scrollTop 平移。
