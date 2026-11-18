let _cmdLibCache = null;
let _cmdDragFrom = -1;   // a239 B3-P2: 拖拽源索引（模块级——旧闭包残留会按陈旧索引错序保存）
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
  const prev = _cmdLibCache;
  _cmdLibCache = lib;          // 乐观更新（界面立即反映）
  try {
    const r = await fetch('/api/cmd_lib', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lib })
    });
    const j = await r.json().catch(() => ({}));
    // a645：后端对「清空/大幅删减」会 409 拒绝。必须如实报出来并把本地
    // 缓存回滚——否则界面显示删干净了、磁盘上其实没动，下次刷新又冒回来
    // （正是命令库被洗那次的前端表现：乐观更新 + 静默失败）。
    if (!r.ok || j.ok === false) {
      _cmdLibCache = prev;
      if (typeof showBanner === 'function') {
        showBanner(j.err || '命令库保存失败', 5000, true);
      }
      return false;
    }
    if (Array.isArray(j.lib)) _cmdLibCache = j.lib;
    return true;
  } catch (e) {
    _cmdLibCache = prev;
    if (typeof showBanner === 'function') showBanner('命令库保存失败（网络）', 4000, true);
    return false;
  }
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
        <button class="edit" data-i="${i}" title="编辑">${ICO.pencil}</button>
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
    // ---- 拖拽排序 ----
    // 之前在 dragover 里实时移动 DOM：dragover 高频触发 + 移动被拖元素本身又
    // 改变鼠标下元素 → 移动-触发-再移动循环，UI 疯狂抖动且最终落点错位。
    // 正确做法：拖动过程中完全不动 DOM，只高亮当前悬停条目标记落点方向；
    // drop 时按鼠标位置（条目中线判断前/后）一次性重排数组并保存。
    // a239 B3-P2: 拖拽状态提为模块级 + 容器监听单例化——原每次渲染都往持久
    // 容器 libEl 追加一套 dragover/drop/dragleave（10 次渲染=每帧 10 份全列表
    // 布局查询），且旧闭包 dragFrom 残留会在重渲染后按陈旧索引二次 splice
    libEl.querySelectorAll('.cmd-item').forEach((item, i) => {
      item.draggable = true;
      item.addEventListener('dragstart', e => {
        _cmdDragFrom = i;
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        try { e.dataTransfer.setData('text/plain', String(i)); } catch (_) {}  // Firefox 必需
      });
      item.addEventListener('dragend', () => {
        item.classList.remove('dragging');
        libEl.querySelectorAll('.cmd-item').forEach(el => el.classList.remove('drop-before', 'drop-after'));
        _cmdDragFrom = -1;
      });
    });
    // a239 B3-P2：先卸上一套容器监听再绑（引用存 libEl._cmdDragHandlers）——
    // 状态已提为模块级 _cmdDragFrom，新一套闭包无过时引用
    if (libEl._cmdDragHandlers) {
      libEl._cmdDragHandlers.forEach(([ev, fn]) => libEl.removeEventListener(ev, fn));
    }
    libEl._cmdDragHandlers = [];
    const _onDragOver = e => {
      e.preventDefault();  // 允许 drop
      e.dataTransfer.dropEffect = 'move';
      const items = Array.from(libEl.querySelectorAll('.cmd-item:not(.dragging)'));
      const target = items.find(el => {
        const r = el.getBoundingClientRect();
        return e.clientY >= r.top && e.clientY <= r.bottom;
      });
      // 清旧标记，给当前悬停条目按鼠标在其上半/下半标前/后
      libEl.querySelectorAll('.cmd-item').forEach(el => el.classList.remove('drop-before', 'drop-after'));
      if (!target) return;
      const r = target.getBoundingClientRect();
      target.classList.add(e.clientY < r.top + r.height / 2 ? 'drop-before' : 'drop-after');
    };
    const _onDrop = async e => {
      e.preventDefault();
      if (_cmdDragFrom < 0) return;
      const items = Array.from(libEl.querySelectorAll('.cmd-item'));
      const dragEl = items[_cmdDragFrom];
      if (!dragEl) { _cmdDragFrom = -1; return; }
      // 找鼠标悬停的目标条目及前/后
      let toIdx = -1, before = false;
      for (let i = 0; i < items.length; i++) {
        if (items[i] === dragEl) continue;
        const r = items[i].getBoundingClientRect();
        if (e.clientY >= r.top && e.clientY <= r.bottom) {
          toIdx = i; before = e.clientY < r.top + r.height / 2; break;
        }
      }
      if (toIdx < 0) { _cmdDragFrom = -1; return; }  // 没落在任何条目上：不换
      // 数组重排：splice 拿出起点，再按目标索引（扣除起点被移除的影响）插回
      const old = await loadCmdLib();
      const [moved] = old.splice(_cmdDragFrom, 1);
      if (!moved) { _cmdDragFrom = -1; renderCmdPane(); return; }
      // 计算插入位：目标是 drop 前半 → 插它前；后半 → 插它后。
      // dragFrom < toIdx 时目标条目在移除后前移了一位，需修正。
      let insertAt = toIdx + (before ? 0 : 1);
      if (_cmdDragFrom < toIdx) insertAt -= 1;
      old.splice(insertAt, 0, moved);
      await saveCmdLib(old);
      _cmdDragFrom = -1;
      renderCmdPane();
    };
    const _onDragLeave = e => {
      // 拖出列表区域：清落点标记（dragleave 会冒泡子元素，仅当真正离开列表时清）
      if (!libEl.contains(e.relatedTarget)) {
        libEl.querySelectorAll('.cmd-item').forEach(el => el.classList.remove('drop-before', 'drop-after'));
      }
    };
    libEl.addEventListener('dragover', _onDragOver);
    libEl.addEventListener('drop', _onDrop);
    libEl.addEventListener('dragleave', _onDragLeave);
    libEl._cmdDragHandlers.push(['dragover', _onDragOver], ['drop', _onDrop], ['dragleave', _onDragLeave]);
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
  // v3.5.116（用户实锤「点命令库发送后焦点被右侧面板占据，必须手点回
  // 终端才能输入」）：发送完把焦点还给活动终端的 xterm——继续敲命令不用
  // 再点一次窗口。非终端 tab（harness 等）无 term，静默跳过
  const conn = connections[activePortId];
  if (conn && conn.term) { try { conn.term.focus(); } catch (_) {} }
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

// 模块化一期：转 ES module——跨文件裸引用消费名挂 window（eslint 神谕）。
window.renderCmdPane = renderCmdPane;
window.sendCmd = sendCmd;
