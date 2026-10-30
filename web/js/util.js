// ============================================================
// 全局状态
// ============================================================
const $ = id => document.getElementById(id);
const banner = $('banner');
const portList = $('portList');
const tabs = $('tabs');
const termArea = $('termArea');

let connections = {};   // port_id -> conn（含 term/fit/search/xtermWrap/sse 等）
let activePortId = null;
let aiSse = null;

// banner 已改右下角悬浮冒泡，不占布局空间，无需再重 fit 终端。
// （保留函数引用兼容旧调用点。）
function refitAllTerms() {}

// ============================================================
// 通知栈（v1.1.2）：右下角向上堆叠的多条冒泡，支持并发长任务各自一条。
// 旧 showBanner(msg,ms,isErr) 是单例 DOM，多个并发操作互相覆盖——多个 SSH
// 同时快捷打开时只剩最后一条。任务型 API：
//   const nid = notifyTask({icon, title, detail})      → 进行中（转圈）
//   notifyTaskDone(nid, {ok, title, detail, ms})       → ✓/✗ 后自动消失
//   notifyPop(msg, ms, isErr)                          → 普通一次性冒泡（等价旧 showBanner）
// 样式见 style.css .notify-* 区块；栈容器 #notifyStack 动态创建不占布局。
// ============================================================
function _notifyStack() {
  let el = document.getElementById('notifyStack');
  if (!el) {
    el = document.createElement('div');
    el.id = 'notifyStack';
    document.body.appendChild(el);
  }
  return el;
}
// claude 用自绘星形图标（.claude-ico 内联 SVG，与顶栏按钮/tab 同款），不用 emoji——
// emoji 在不同系统字体下渲染不一致（Win10 是黑白轮廓），自绘 SVG 才能保品牌色 D97757。
const _NOTIFY_ICON = { ssh: '🔗', serial: '🔌', telnet: '🖥', file: '📄', diff: '⚖', hex: '🧮', log: '📜', claude: '<span class="claude-ico"></span>', generic: '⚙' };

function _notifyBuild(o) {
  const d = document.createElement('div');
  d.className = 'notify' + (o.isErr ? ' err' : '');
  const icon = o.icon || _NOTIFY_ICON[o.type] || _NOTIFY_ICON.generic;
  d.innerHTML = `
    <span class="n-ico">${icon}</span>
    <div class="n-body">
      <div class="n-title">${esc(o.title || '')}</div>
      ${o.detail ? `<div class="n-detail">${esc(o.detail)}</div>` : ''}
    </div>
    <span class="n-state"></span>
    <span class="n-close" title="关闭">✕</span>
  `;
  return d;
}
function _notifyMount(d, ms) {
  const stack = _notifyStack();
  // 栈封顶 6 条：超出丢最旧（FIFO）——连环点 20 个快捷打开时不能让转圈
  // 通知盖满半屏（铁律①流畅/可用性）。被丢的条若是常驻任务(无 timer)，
  // 后续 notifyTaskDone 会静默 no-op（DOM 已 remove，_closed 检查兜住）
  while (stack.children.length >= 6) {
    const oldest = stack.children[stack.children.length - 1];   // column-reverse: 最旧在最后
    _notifyDismiss(oldest);
    if (stack.children.length >= 8) oldest.remove();   // 防御:dismiss 是动画退出,极端时强移
  }
  stack.appendChild(d);
  // 入场动画（CSS .notify 定义）后自动消失（ms=0 常驻，由任务完成时关闭）
  if (ms) {
    d._timer = setTimeout(() => _notifyDismiss(d), ms);
  }
  return d;
}
function _notifyDismiss(d) {
  if (d._timer) { clearTimeout(d._timer); d._timer = null; }
  if (d._closed) return;
  d._closed = true;
  d.classList.add('out');
  setTimeout(() => d.remove(), 200);   // 等 slide-out 动画
}

// 任务型：发起（进行中，转圈）→ 返回 nid
function notifyTask({type, icon, title, detail}) {
  const d = _notifyBuild({icon, type, title, detail});
  d.querySelector('.n-state').innerHTML = '<span class="n-spin"></span>';
  d.querySelector('.n-close').onclick = () => _notifyDismiss(d);
  _notifyMount(d, 0);   // 常驻直到 done
  return d;
}
// 任务型：结束（ok=true ✓ 绿 / false ✗ 红），改状态后自动消失
function notifyTaskDone(nid, {ok, title, detail, ms=5000}) {
  const d = nid;
  if (!d || d._closed) return;
  if (title) d.querySelector('.n-title').textContent = title;
  if (detail !== undefined) {
    const det = d.querySelector('.n-detail');
    if (detail) { if (!det) { const nd = document.createElement('div'); nd.className = 'n-detail'; nd.textContent = detail; d.querySelector('.n-body').appendChild(nd); } else det.textContent = detail; }
    else if (det) det.remove();
  }
  const st = d.querySelector('.n-state');
  st.innerHTML = ok ? '✓' : '✗';
  d.classList.toggle('err', !ok);
  d._timer = setTimeout(() => _notifyDismiss(d), ok ? Math.min(ms, 4000) : ms);
}

// 一次性冒泡（旧 showBanner 等价，但走堆叠栈不覆盖其他通知）
function notifyPop(msg, ms=4000, isErr=false, type) {
  // v3.2.20（用户实锤同文案提示连刷 7~8 条）：同文去重——栈内在场的相同
  // 文案+相同级别不再重复弹，仅重置其驻留计时（重要信息不被刷屏淹没）
  try {
    const dup = [..._notifyStack().children].find(n =>
      !n._closed && n.classList.contains('err') === !!isErr &&
      (n.querySelector('.n-title') || {}).textContent === String(msg));
    if (dup) {
      if (dup._timer) clearTimeout(dup._timer);
      dup._timer = setTimeout(() => _notifyDismiss(dup), ms || 4000);
      return dup;
    }
  } catch(_) {}
  const d = _notifyBuild({title: msg, isErr, type});
  d.querySelector('.n-state').innerHTML = isErr ? '✗' : '✓';
  d.querySelector('.n-close').onclick = () => _notifyDismiss(d);
  _notifyMount(d, ms || 4000);
  return d;
}

// 旧 API 兼容层：全部转发到通知栈（153 个既有调用点不动）
function showBanner(msg, ms=4000, isErr=false) {
  notifyPop(msg, ms, isErr);
}

// ---- 工具面板渐隐滚动条（用户需求：常显小丑→悬浮工作区渐显）------------
// 通用自绘：原生滚动条视觉已由 CSS 隐藏（Fluent 绘制层宽度不可控+伪元素
// 不吃 transition,渐隐只能自绘 DOM 才能做）。面板需 position:relative
// （CSS 已给六容器配好）。内容不溢出自动隐藏；拖拽锁 sb-drag 防拖出面板
// 时条闪没；400ms 周期兜底（列表增删不触发 scroll 事件）。返回清理函数
function _hgFadeSb(el) {
  if (!el || el._hgFadeSb) return () => {};
  // 轨道定位自给自足：.hg-fade-sb 的 top/bottom 绝对定位依赖宿主
  // position:relative（CSS 提供）。CSS 缓存半新半旧时宿主没有 relative
  // → 轨道高度 0 → paint 短路 → thumb 钉在顶端（用户实锤「滚动不跟随,
  // 条被固定在最顶」）。inline 直写,不再依赖任何 CSS 到位
  if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
  const sb = document.createElement('div');
  sb.className = 'hg-fade-sb';
  const th = document.createElement('div');
  th.className = 'hg-fade-sb-th';
  sb.appendChild(th);
  // paint 自愈：宿主 innerHTML 整体重写（renderRecentList 等）会把条连根
  // 抹掉（用户实锤「条没了无论如何看不到」）——每拍检查不在 DOM 就重插。
  // sb/th 引用保持不变（监听/样式全在,重插零成本）
  el.appendChild(sb);
  const ensureInDom = () => {
    if (sb.parentNode !== el) el.appendChild(sb);
  };
  const paint = () => {
    if (!el.isConnected) return;
    ensureInDom();
    const sh = el.scrollHeight, ch = el.clientHeight;
    if (sh <= ch + 4) { sb.style.display = 'none'; return; }
    sb.style.display = '';
    const trackH = sb.clientHeight;
    if (trackH <= 0) {
      // 轨道仍 0 高（定位异常兜底）：改用宿主可视高直接算,条不再失联
      const fallback = Math.max(40, ch - 8);
      if (sb.style.top === '' && sb.style.bottom === '') {
        sb.style.top = '4px'; sb.style.bottom = '4px';
      }
      if (fallback <= 0) return;
      const thH = Math.max(32, Math.round(ch / sh * fallback));
      const maxTop = fallback - thH;
      th.style.height = thH + 'px';
      th.style.top = (maxTop > 0 ? el.scrollTop / (sh - ch) * maxTop : 0) + 'px';
      sb.style.height = fallback + 'px';
      return;
    }
    const thH = Math.max(32, Math.round(ch / sh * trackH));
    const maxTop = trackH - thH;
    th.style.height = thH + 'px';
    th.style.top = (maxTop > 0 ? el.scrollTop / (sh - ch) * maxTop : 0) + 'px';
  };
  sb.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const trackH = sb.clientHeight, thH = th.offsetHeight;
    const maxTop = trackH - thH;
    if (e.target === th) {
      sb.classList.add('sb-drag');
      const startY = e.clientY, startScroll = el.scrollTop;
      const move = (ev) => {
        if (maxTop <= 0) return;
        el.scrollTop = startScroll +
          (ev.clientY - startY) / maxTop * (el.scrollHeight - el.clientHeight);
      };
      const up = () => {
        sb.classList.remove('sb-drag');
        removeEventListener('mousemove', move);
        removeEventListener('mouseup', up);
      };
      addEventListener('mousemove', move);
      addEventListener('mouseup', up);
    } else {
      const y = e.clientY - sb.getBoundingClientRect().top;
      const cur = parseFloat(th.style.top) || 0;
      el.scrollTop += (y < cur ? -1 : 1) * el.clientHeight * 0.9;
    }
  });
  el.addEventListener('scroll', paint, { passive: true });
  const timer = setInterval(paint, 400);
  paint();
  el._hgFadeSb = { sb, timer };
  return () => { clearInterval(timer); sb.remove(); delete el._hgFadeSb; };
}
function fmtTs(ms) {
  const d = new Date(ms);
  return d.toLocaleTimeString('zh-CN', {hour12:false}) + '.' + String(ms % 1000).padStart(3,'0');
}
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

// v3.5.109（designer 方案 O1）：写操作统一包装——义务化响应校验，替代各
// 调用点裸 .catch(()=>{})（order 400 静默 3 年的教训：写操作不看响应码，
// 失败无声丢失）。非 2xx 也尝试解析 JSON；j.ok 不真/解析失败/网络错一律
// 失败路径并 banner（label 前缀调用方定文案）。返回 {ok, j} 供调用方做
// 回滚/后续逻辑；成功静默不弹（调用方需要成功提示的自己发）。
async function apiPost(path, body, opt) {
  opt = opt || {};
  try {
    const r = await fetch(path, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}) });
    let j = null;
    try { j = await r.json(); } catch (_) {}          // 5xx HTML 错误页等
    if (!j || !j.ok) {
      const why = (j && j.err) ? ('：' + j.err) : ('（HTTP ' + r.status + '）');
      showBanner((opt.label || '操作失败') + why, 4000, true);
      return { ok: false, j };
    }
    return { ok: true, j };
  } catch (e) {
    showBanner((opt.label || '操作失败') + '：网络或服务错误', 4000, true);
    return { ok: false, j: null };
  }
}
// 连接排序：串口[0] < SSH[1] < 日志[2] < 编辑器[3] < claude[4]，同类内按自然序
function sortKeyFn(pid) {
  const m = /^COM(\d+)$/i.exec(pid);
  if (m) return [0, parseInt(m[1], 10)];  // 串口：COM 号数字序
  if (pid.startsWith('log:')) return [2, pid];  // 日志：字典序
  if (pid.startsWith('diff:')) return [3, 'd' + pid];  // 对比：编辑器组，字典序排最前（log/编辑器都是数字段后缀）
  if (pid.startsWith('edit:')) return [3, pid];  // 编辑器：字典序（排在日志后）
  if (pid.startsWith('claude:')) return [4, pid];  // claude 终端：字典序（排在编辑器后）
  if (pid.startsWith('harness:')) return [5, pid];  // claude harness 对话：字典序（排在 claude 终端后）
  return [1, pid];  // SSH：字典序
}

// ============================================================
// 关键字高亮（error/warning/info 等）
// v0.3.0：改用 xterm decoration 实现（见下方 highlightNewKw），
// 旧的 DOM textNode 高亮函数 highlightKeywords 已废弃移除。
// ============================================================
// （KW_RULES / KW_COLOR 已移至下方 xterm decoration 区块统一定义）

// ============================================================
// 终端标签页 & 输出区管理
// ============================================================
// 注：实际终端元素由 buildTerminal() 创建，此处不再保留死代码。

// 重新设计：每个连接有自己的 xterm 终端容器

// ============================================================
// v3.5.310 可配置快捷键（设置页录制式）：文档内搜索（原 Ctrl+F）/ 全库
// 笔记搜索（原 Ctrl+Alt+F）。_HK 由启动 GET /api/theme 填充，设置页改键
// 后热更新 window._HK。
// hkMatch(e, combo, loose)：loose=true（文档内搜索——原 sidebar/editor 条件
// 不排 Shift/Alt，宽松保持）；loose 缺省=严格（三修饰键精确匹配，全库搜索
// 原语义）。轻审 F2：strict 语义不可放宽到 docSearch，否则 ctrl+f 吞掉
// ctrl+alt+f。
// ============================================================
function hkMatch(e, combo, loose) {
  if (!combo) return false;
  const parts = String(combo).toLowerCase().split('+').filter(Boolean);
  if (!parts.length) return false;
  const key = parts[parts.length - 1];
  if ((e.key || '').toLowerCase() !== key) return false;
  // 纵深防御（复审 R2）：直连 POST 塞 'win+f' 类脏配置时，未知修饰段使按键
  // 永不命中——比「退化成裸键触发」安全（UI 录制器产不出此类值）
  if (parts.slice(0, -1).some(mm => !['ctrl', 'alt', 'shift'].includes(mm))) return false;
  const chk = (want, got) => (loose ? (!want || got) : want === got);
  if (!chk(parts.includes('ctrl'), !!e.ctrlKey)) return false;
  if (!chk(parts.includes('alt'), !!e.altKey)) return false;
  if (!chk(parts.includes('shift'), !!e.shiftKey)) return false;
  return true;
}
window._HK = { docSearch: 'ctrl+f', notesSearch: 'ctrl+alt+f' };
(function () {
  fetch('/api/theme').then(r => r.json()).then(j => {
    if (!j || !j.ok) return;
    if (typeof j.doc_search_hotkey === 'string' && j.doc_search_hotkey)
      window._HK.docSearch = j.doc_search_hotkey;
    if (typeof j.notes_search_hotkey === 'string' && j.notes_search_hotkey)
      window._HK.notesSearch = j.notes_search_hotkey;
  }).catch(() => {});
})();
