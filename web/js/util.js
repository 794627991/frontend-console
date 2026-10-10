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
