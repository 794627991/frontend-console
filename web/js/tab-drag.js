// ============================================================
// tab 拖拽排序 v2（用户实锤：v1 手感极差——事件绑在每个 tab 上，必须贴着
// 目标才能拖，间隙/胶囊区无反馈，指示线也没有）。
// v2 = 浏览器级手感：
//   - 容器级委托（#tabs 一次绑定）：拖动经过整个 tab 栏任何位置都有反馈；
//   - 最近间隙吸附：按鼠标 x 找最近的"可落点元素边缘"（tab + 抽屉胶囊都算），
//     不需要精确贴着某个元素——拖到两个 tab 之间的空隙照样吸附落点；
//   - 指示线常显 + 发光脉冲动画（所见即所得的落点）；
//   - 固定区挡板保留（未固定源拖进固定簇 → 自动挡到固定组后，指示线也
//     显示真实落点，不骗用户）；
//   - 胶囊作为一等落点（tab 可拖到任意胶囊前/后，与 a286R20 行为一致）。
// ============================================================
const _tabDrag = { el: null, marker: null };   // marker = 当前指示线挂在哪个元素+哪侧

// 可落点元素：可见的 tab + 抽屉胶囊（pinned tab 位置由挡板接管，仍可作为
// 视觉锚点——真实落点会被挡板修正并同步指示线）
function _dragDroppables() {
  return [...tabs.querySelectorAll('.tab, .tab-drawer')].filter(el => {
    if (el === _tabDrag.el) return false;
    const r = el.getBoundingClientRect();
    return el.style.display !== 'none' && r.width > 0;
  });
}

// 吸附判定：鼠标 x → 最近的元素边缘（返回 {el, before}）
function _dragSnap(clientX) {
  const els = _dragDroppables();
  if (!els.length) return null;
  let best = null, bestDist = Infinity;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    // 每个元素两个候选边缘：左（before）/右（after），取全栏最近
    for (const [x, before] of [[r.left, true], [r.right, false]]) {
      const d = Math.abs(clientX - x);
      if (d < bestDist) { bestDist = d; best = { el, before }; }
    }
  }
  return best;
}

// 挡板修正：未固定源要落进固定簇 → 真实落点 = 最后一个固定 tab 之后
function _dragGuard(src, snap) {
  if (!snap) return snap;
  // L2（a309R3 第2轮审查）：胶囊源只认抽屉栏内锚点——拖到主栏 tab 前后时
  // 指示线宣称可落，drop 实际却归位到栏首（误导）。锚不在栏内 → 无落点，
  // 指示线隐藏 + drop 无操作
  if (src.classList.contains('tab-drawer') && !(snap.el.closest && snap.el.closest('.tab-drawer-bar'))) return null;
  if (src.classList.contains('pinned') || !snap.el.classList.contains('tab')) return snap;
  // 目标是固定 tab（无论前/后半）→ 挡到最后固定后。
  // 注意：src 自己可能带 pinned 类（拖动中 unpin 竞态）——只挡真 pinned 目标
  if (snap.el.classList.contains('pinned') && snap.el !== src) {
    const pinned = [...tabs.querySelectorAll('.tab.pinned')].filter(p => p !== src);
    const last = pinned[pinned.length - 1];
    if (last) return { el: last, before: false, guarded: true };
  }
  return snap;
}

// 指示线渲染（清除旧的，挂新的；容器级重画代替 v1 的 per-tab 切换）
function _dragMarker(snap) {
  document.querySelectorAll('.drop-before, .drop-after').forEach(t =>
    t.classList.remove('drop-before', 'drop-after'));
  _tabDrag.marker = null;
  if (!snap) return;
  snap.el.classList.add(snap.before ? 'drop-before' : 'drop-after');
  _tabDrag.marker = snap;
}

// 执行落位。用户实锤三炸点：
//   ① snap.el 是抽屉胶囊（drawerBar 的子节点，不是 tabs 直接子级）——
//     tabs.insertBefore(src, 胶囊) 直接 NotFoundError → 拖进抽屉中间永远失败；
//   ② snap.el.nextSibling 为 null（末尾胶囊后半）→ insertBefore(src, null)
//     = appendChild，tab 被追加到 tabs 末尾——排到 ⋮ 按钮后面去了；
//   ③ 锚点是【已在抽屉栏内部的 tab】（如 claude 拖进栏后，计算器再拖到它前后）
//     —— a293 只判了胶囊，栏内 tab 走 tabs 分支被 ref 归一弹回 actions 前，
//     表现为"拖到串口后面不行"。
// 修：锚在 drawerBar 内（无论胶囊还是 tab）→ 一律落进栏内 + userPlaced 标
function _dragCommit(src, snap) {
  if (!snap) return false;
  const anchorEl = snap.el;
  const anchorBar = anchorEl.closest ? anchorEl.closest('.tab-drawer-bar') : null;
  if (anchorBar) {
    // 胶囊或栏内 tab 锚点：在锚所在容器内落位（顺序与指示线所见一致）
    anchorBar.insertBefore(src, snap.before ? anchorEl : anchorEl.nextSibling);
    src.dataset.userPlaced = '1';   // rebuild 的单例归位循环绕行（位置只认用户的手）
    _tabManualOrder();
    return true;
  }
  // tabs 直接子级锚点：ref 归一（null/异层级 → tab-bar-actions 之前，绝不 appendChild）
  let ref = snap.before ? anchorEl : anchorEl.nextSibling;
  if (!ref || ref.parentNode !== tabs) ref = tabs.querySelector('.tab-bar-actions');
  if (!ref) return false;   // 连 actions 都没有（异常布局）——放弃落位不炸
  tabs.insertBefore(src, ref);
  _tabManualOrder();
  return true;
}

let _dragInited = false;
function _initTabDrag(tab) {
  // 各模块创建 tab 时调用（传参）——draggable 必须预置才能发起拖拽
  if (tab) tab.draggable = true;
  if (_dragInited) return;
  _dragInited = true;
  const cont = document.getElementById('tabs');
  if (!cont) return;

  cont.addEventListener('dragstart', e => {
    const el = e.target.closest('.tab, .tab-drawer');
    if (!el) return;
    _tabDrag.el = el;
    window.__tabDragSrc = el.classList.contains('tab') ? el : null;   // 仅 tab（util 兼容）
    el.classList.add('dragging');
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', el.dataset.portId || el.dataset.group || ''); } catch(_) {}
    }
  });

  cont.addEventListener('dragend', e => {
    window.__tabDragSrc = null;
    // a296 真凶修复：drop 处理器已把 _tabDrag.el 置 null——若只依赖它清 dragging，
    // 类永远残留（opacity:0.4 半透明压住 active 高亮 = 用户实锤"claude 高亮有问题"）。
    // 双保险：_tabDrag.el + 事件目标链 + 全栏兜底扫拖拽类
    const t = (e.target && e.target.closest ? e.target.closest('.tab, .tab-drawer') : null);
    if (_tabDrag.el) _tabDrag.el.classList.remove('dragging');
    if (t) t.classList.remove('dragging');
    document.querySelectorAll('.dragging').forEach(x => x.classList.remove('dragging'));
    _dragMarker(null);
    _tabDrag.el = null;
  });

  // 容器级 dragover：任何位置都可放——吸附 + 指示线实时跟随
  cont.addEventListener('dragover', e => {
    // a237 P3：拖拽中源被关（dragend 不触发）——脱离文档即清态
    if (_tabDrag.el && !_tabDrag.el.isConnected) {
      _tabDrag.el = null; _dragMarker(null);
    }
    if (!_tabDrag.el) return;
    e.preventDefault();               // 持续 preventDefault → drop 可触发
    // 合成 DragEvent 无 dataTransfer（自动化测试）——真实拖拽必有，防御即可
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    const snap = _dragGuard(_tabDrag.el, _dragSnap(e.clientX));
    // 只在落点变化时重画（避免每帧 DOM 抖动）
    if (!_tabDrag.marker ||
        _tabDrag.marker.el !== (snap && snap.el) ||
        _tabDrag.marker.before !== (snap && snap.before)) {
      _dragMarker(snap);
    }
  });

  cont.addEventListener('drop', e => {
    e.preventDefault();
    if (!_tabDrag.el) return;
    const src = _tabDrag.el;
    const snap = _dragGuard(src, _dragSnap(e.clientX));
    let ok = false;
    if (src.classList.contains('tab-drawer')) {
      // 胶囊换序：限制在抽屉栏内（防 rebuild 冲掉），落位后同步用户组序
      const bar = document.querySelector('.tab-drawer-bar');
      if (snap && bar && snap.el !== src) {
        bar.insertBefore(src, bar.contains(snap.el) ? (snap.before ? snap.el : snap.el.nextSibling) : bar.firstChild);
        if (typeof window._ovSyncGroupOrder === 'function') window._ovSyncGroupOrder();
        ok = true;
      }
    } else {
      ok = _dragCommit(src, snap);
      // tab 落进抽屉栏内（胶囊间）→ 打用户放置标（a286R20 语义：rebuild 归位绕行）
      if (ok && snap && snap.el.classList.contains('tab-drawer')) src.dataset.userPlaced = '1';
    }
    _dragMarker(null);
    if (_tabDrag.el) _tabDrag.el.classList.remove('dragging');   // dragend 可能不来（drop 到自定义目标），此处先清
    _tabDrag.el = null;
    window.__tabDragSrc = null;
  });
}

let _tabOrderManual = false;   // 用户拖过一次后 true（refreshSidebar 已退役但保留语义）
function _tabManualOrder() { _tabOrderManual = true; }
function _maybeResetTabOrder() {
  if (!document.querySelector('#tabs .tab')) _tabOrderManual = false;
}

// 模块化一期：转 ES module——跨文件/Python 裸引用消费名挂 window。
// 清单由 eslint no-undef 神谕反推（零启发式）：本文件转模块后，其余
// 文件/Python 推送的裸标识符引用全部经 window 解析。
window._initTabDrag = _initTabDrag;
window._tabManualOrder = _tabManualOrder;
