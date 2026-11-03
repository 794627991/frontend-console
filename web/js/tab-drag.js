// ============================================================
// tab 拖拽排序：拖动 tab 到目标位置（所有类型通用）。
// 用户手动拖过之后，refreshSidebar 的自动重排（sortKeyFn）让位——
// 不再自动重排，尊重用户顺序（新 tab 仍默认排末尾）。
// HTML5 drag API：dragstart 记源，dragover 定位落点（前/后半判断），drop 移 DOM。
// ============================================================
const _tabDrag = { el: null, over: null };

function _initTabDrag(tab) {
  tab.draggable = true;
  tab.addEventListener('dragstart', e => {
    _tabDrag.el = tab;
    tab.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', tab.dataset.portId); } catch(_) {}
  });
  tab.addEventListener('dragend', () => {
    tab.classList.remove('dragging');
    document.querySelectorAll('.tab.drop-before, .tab.drop-after').forEach(t =>
      t.classList.remove('drop-before', 'drop-after'));
    _tabDrag.el = null; _tabDrag.over = null;
  });
  tab.addEventListener('dragover', e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    // a237 P3：拖拽中源 tab 被关闭（dragend 不触发）——元素已脱离文档即
    // 清拖拽态，防旧元素被钉到下次拖拽
    if (_tabDrag.el && !_tabDrag.el.isConnected) { _tabDrag.el = null; _tabDrag.over = null; }
    if (!_tabDrag.el || _tabDrag.el === tab) return;
    _tabDrag.over = tab;
    const r = tab.getBoundingClientRect();
    const before = e.clientX < r.left + r.width / 2;
    document.querySelectorAll('.tab.drop-before, .tab.drop-after').forEach(t => {
      if (t !== tab) t.classList.remove('drop-before', 'drop-after');
    });
    tab.classList.toggle('drop-before', before);
    tab.classList.toggle('drop-after', !before);
  });
  tab.addEventListener('drop', e => {
    e.preventDefault();
    if (!_tabDrag.el || _tabDrag.el === tab) return;
    const r = tab.getBoundingClientRect();
    const before = e.clientX < r.left + r.width / 2;
    const src = _tabDrag.el;
    // 第9轮盲测缺陷3（中）：未固定 tab 拖到固定 tab 之前会破坏"固定组最左"
    // 不变量（且不被纠正）。防护：未固定源落进固定区（目标固定且落前半）时，
    // 改插到最后一个固定 tab 之后——保持固定区完整。第10轮缺陷3：后半
    // （落在固定 tab 右半）同样插进固定簇中间——去掉 before 条件统一挡板
    const srcPinned = src.classList.contains('pinned');
    const tgtPinned = tab.classList.contains('pinned');
    if (!srcPinned && tgtPinned) {
      const pinnedEls = [...tabs.querySelectorAll('.tab.pinned')];
      const ref = pinnedEls.length ? pinnedEls[pinnedEls.length - 1].nextSibling : tab;
      tabs.insertBefore(src, ref);
    } else if (before) tabs.insertBefore(src, tab);
    else tabs.insertBefore(src, tab.nextSibling);
    tab.classList.remove('drop-before', 'drop-after');
    _tabManualOrder();   // 标记手动排序，自动重排让位
  });
}

let _tabOrderManual = false;   // 用户拖过一次后 true，refreshSidebar 不再自动重排
function _tabManualOrder() { _tabOrderManual = true; }
// 关掉最后一个 tab（回到空态）后重置——下次打开恢复默认排序
function _maybeResetTabOrder() {
  if (!document.querySelector('#tabs .tab')) _tabOrderManual = false;
}
