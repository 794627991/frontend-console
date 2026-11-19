// lanzi/loads-tip.js — 模型负载悬浮卡（a673 模块化拆分；a672 自 harness/shell.js 平移）
//
// 触发点（用户定调）：顶部 Lanzi 标签 + harness 侧栏「机器人」按钮，任一处
// 悬停都出卡——不开面板也能一眼看到负载。
//
// 数据源：/api/lanzi/status 的 model_loads（后端只在上游是 lanz 时下发）。
// 生命周期：
//   · 悬停 → 建卡 + 拉一次 + 起 20s tick（悬停期间数据不冻住）
//   · 移出 → 收卡 + 停 tick
//   · tab 关闭 → 宿主的 _lzTeardown 调 hide()（指针停在标签上点 ✕ 时
//     Chromium 不补发 mouseout，不主动收会留一张钉在左上角的僵尸卡）
import { esc } from './util.js';

const TIP_TICK_MS = 20000;

let tipEl = null;
let tick = null;
let loads = null;
let loadsErr = '';
// 上游是否支持负载。初值 true：冷启动时未知，先允许悬停（首拉会立刻纠正）；
// 已知不支持后不再出卡，避免每次悬停先闪一张空卡。
let supported = true;

function tipNode() {
  if (tipEl && document.contains(tipEl)) return tipEl;
  tipEl = document.createElement('div');
  tipEl.className = 'hg-loads-tip';
  tipEl.style.display = 'none';
  document.body.appendChild(tipEl);
  return tipEl;
}

function paint(anchor) {
  const el = tipNode();
  if (!loads || !loads.length) {
    el.innerHTML = '<div class="hg-loads-row"><span class="hg-loads-name" ' +
      'style="color:var(--muted)">' +
      (loadsErr ? esc(loadsErr) : '负载加载中…') + '</span></div>';
  } else {
    el.innerHTML = loads.map(m => {
      const pct = (m.pct == null) ? null : m.pct;
      const cls = m.level ? ' px-load--' + m.level : '';
      return '<div class="hg-loads-row"><span class="hg-loads-name">' + esc(m.name) + '</span>' +
        '<span class="hg-loads-bar' + cls + '"><i style="width:' + (pct == null ? 0 : pct) + '%"></i></span>' +
        '<span class="hg-loads-pct' + cls + '">' + (pct == null ? '--' : pct + '%') + '</span></div>';
    }).join('');
  }
  el.style.display = 'block';
  // 定位：优先在锚点下方；下方放不下改上方；都放不下贴顶并允许滚动
  const r = anchor.getBoundingClientRect();
  const tw = el.offsetWidth, th = el.offsetHeight;
  let top = r.bottom + 6;
  if (top + th > window.innerHeight - 8) top = Math.max(8, r.top - th - 6);
  const avail = window.innerHeight - 16;
  if (th > avail) {
    el.style.maxHeight = avail + 'px';
    el.style.overflowY = 'auto';
    top = 8;
  } else {
    el.style.maxHeight = '';
    el.style.overflowY = '';
  }
  el.style.top = Math.round(Math.max(8, Math.min(top, window.innerHeight - th - 8))) + 'px';
  let left = r.left;
  if (left + tw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - tw - 8);
  el.style.left = Math.round(left) + 'px';
}

export function hide() {
  if (tipEl) tipEl.style.display = 'none';
  stopTick();
}

function stopTick() {
  if (tick) { clearInterval(tick); tick = null; }
}

async function fetchLoads(anchor) {
  try {
    const j = await fetch('/api/lanzi/status').then(r => r.json());
    if (!j || !j.ok) return;
    loads = (j.model_loads && j.model_loads.length) ? j.model_loads : null;
    loadsErr = j.model_loads_err || '';
    supported = j.model_loads_supported !== false;
    if (!supported) {
      loadsErr = '';
      hide();
      return;
    }
    if (anchor && tipEl && tipEl.style.display !== 'none') paint(anchor);
  } catch (_) {}
}

function startTick(anchor) {
  stopTick();
  tick = setInterval(() => {
    if (!tipEl || tipEl.style.display === 'none') { stopTick(); return; }
    fetchLoads(anchor);
  }, TIP_TICK_MS);
}

// 两个悬停锚点：顶部 Lanzi 标签 + harness 侧栏「机器人」按钮
function hoverAnchor(target) {
  if (!target || !target.closest) return null;
  return target.closest('.tab[data-port-id="lanzi:main"]')
    || target.closest('[data-hg-login-toggle]');
}

// 委托挂在 document：标签与侧栏按钮都可能晚于本模块创建，委托天然跟随
// DOM，tab 关闭重开也不会重复挂监听。
export function bindHover() {
  document.addEventListener('mouseover', ev => {
    const anchor = hoverAnchor(ev.target);
    if (!anchor) return;
    if (anchor.contains(ev.relatedTarget)) return;   // 子元素间移动不算重入
    if (!supported) { hide(); return; }
    fetchLoads(anchor);
    paint(anchor);
    startTick(anchor);
  });
  document.addEventListener('mouseout', ev => {
    const anchor = hoverAnchor(ev.target);
    if (!anchor) return;
    if (anchor.contains(ev.relatedTarget)) return;
    loadsErr = '';
    hide();
  });
}
