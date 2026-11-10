// harness 外壳(v3.0 自 claude-harness.js 顶层段原样搬移)

// ---- 关闭 tab ----
// ==================== v2.24 大会话 DOM 卸载（拖动卡顿根治）====================
// 现象链（用户对照实验定位）：harness 开大会话 → 所有拖动（文件拖入/命令库
// 排序/tab 换位，HTML5 与 OLE 两套机制）全卡 ~12s；空会话不卡；关 tab 恢复；
// /exit 杀进程仍卡；停 ctx/vision 轮询仍卡 → 元凶是大会话消息流的巨大 DOM
// （数千条消息/数万节点，display:none 仍占内存并拖累渲染进程 GC）。
// 修复：切走 harness tab 时把 flow innerHTML 快照到内存并清空 DOM，切回
// 恢复。busy 时不卸载（后台流式 append 依赖 flow 在场，快照覆盖会丢消息）。
;(function _hgFlowUnloadInit() {
  const _orig = switchTab;
  switchTab = function(portId) {
    // isHg/wasHg 必须在 try 块外声明（const 块级作用域——曾定义在 try 内、
    // 块外引用，每次切 tab 必抛 ReferenceError 且真正的切换动作永远不执行，
    // v2.31 未浏览器实测漏网：用户实锤「Claude 对话没反应/打开 settings 失败」）
    const isHg = portId === 'harness:gui';
    const wasHg = activePortId === 'harness:gui';
    try {
      if (wasHg && !isHg && !_HG.busy && _HG.flowEl && _HG.flowEl.innerHTML) {
        _HG.flowSnap = _HG.flowEl.innerHTML;
        _HG.flowEl.innerHTML = '';
      } else if (isHg && !wasHg && _HG.flowSnap && _HG.flowEl) {
        _HG.flowEl.innerHTML = _HG.flowSnap;
        _HG.flowSnap = '';
        _HG.flowEl.scrollTop = _HG.flowEl.scrollHeight;
        // v3.4.67：本路写入意图=回底，但 wrap 仍 display:none 时 scrollTop
        // 写入是 no-op 不触发 scroll 事件→粘底标志不会经事件回灌，显式置真
        // （轻审实锤的脱钩拽底变体）
        _HG.stickBtm = true;
      }
    } catch(_) {}
    // v2.31：harness tab 激活时右侧「终端助手」面板整体隐藏（v3.3 起会话
    // 动态在 harness 内部分屏——旧换装形态废止，面板对 harness 零用处）
    if (isHg !== wasHg) _hgPanelMode(isHg);
    return _orig(portId);
  };
})();

// ---- v3.3 右侧面板隐藏开关（顶层定义：switchTab 包装器与 _harnessClose
// 都在闭包外调用它；只依赖 index.html 静态节点 #aiPanel，无闭包状态）----
// 旧 _hgPanelMode 是「换装」（hg-mode 藏页签+改标题为会话动态）；会话动态
// 迁入分屏伪 tab 后换装废止——harness tab 激活期间面板整体 display:none，
// 切走/关 tab 即恢复原样（标题从未被改，折叠态由 aiToggle 自持不受影响）。
function _hgPanelMode(on) {
  const p = document.getElementById('aiPanel');
  if (!p) return;
  p.classList.toggle('hg-hide', !!on);
}

function _harnessClose(portId) {
  const _hgConn = connections[portId];
  if (!_hgConn) return;
  // v3.5.51（designer P0-7）：只读模式中关 tab——清 readonly/roViewSid 僵尸态
  //（否则重开 tab 后 setBusy 守卫永久早退）+ 拆 RO 层（force=濒死不 rebuild）
  if (_HG.readonly) {
    _HG.readonly = null; _HG.roViewSid = null;
    try { window.HgRO && window.HgRO.exit(true); } catch(_) {}
  }
  // 二轮 P1-1：主 v4 store 随 tab 销毁关闭（EventSource/silentTimer 泄漏 +
  // RO force 路径曾给垂死 tab 反向新开流——readonly.exit 已加 !force 门）
  if (typeof V4Main !== 'undefined' && V4Main.close) {
    try { V4Main.close(); } catch(_) {}
  }
  _HG.conn = null; _HG.sid = null; _HG.cache = {};
  _HG.rowById = {}; _HG.run = null;   // 批4：subRows/subBlk 段档随段退役删除
  // v2.15：补齐残留态复位。旧实现只清了上面这几个，重开 tab 后 dirty/busy/
  // activity 等沿用上一轮的值——dirty 漏复位会与「点 chip 删会话」叠加，
  // 重开后第一次点模型 chip 就可能删掉一条会话。tab 即将销毁，这里只需清
  // 状态，不用走 setBusy 更新界面。
  _HG.dirty = false; _HG.busy = false;
  _HG.initN = 0; _HG.agentModels = null;   // v2.35：init 计数/模型缓存随 tab 销毁（重开 tab 重新拉）
  _HG.dyn = null; _HG.todos = null; _HG.agents = null;   // v2.32：面板派生态随 tab 销毁
  // v2.46R（P5 测试挖出的潜伏 bug）：phStopTimer 是闭包私有函数，顶层
  // _harnessClose 引用它 → 组在场（回合进行中）关 tab 必抛 ReferenceError，
  // close 中途夭折：tab/wrap 不摘、connections 残留 → 再点按钮走「已存在即
  // switchTab」早退，留下 SSE 已死的僵尸 tab。改为内联同款清理（clearInterval
  // + 置空），不依赖闭包名
  if (_HG.grp && _HG.grp.phTimer) {
    try { clearInterval(_HG.grp.phTimer); } catch(_) {}
    _HG.grp.phTimer = null;
  }
  _HG.grp = null; _HG.activity = null;   // v2.18：组级抽屉（旧 drawer 单例已删）
  // v3.2R1(P2)：回合秒表随 tab 销毁全收（_turnHeadStop 是闭包私有，inline 同款清理）
  (_HG.turnTicks || []).forEach(t => { try { clearInterval(t); } catch(_) {} });
  _HG.turnTicks = [];
  _HG.think = null; _HG.noScroll = false; _HG.openState = null;
  _HG.skills = null; _HG.models = null;   // 技能/模型映射下次进 tab 重新拉
  // v3.3R（全审 P1/P2）：分屏窗格档随 tab 销毁全清（_subReset 全局函数）——
  // 旧只靠切会话/SSE reset 路径顺带清；关 tab 直接销毁时 _sub.tabs/dynEl 残留
  // 游离 DOM，重开 tab 若无历史会话自动 switchTo（全新用户/列表拉取失败）就
  // 没有自愈入口，胶囊点击会被 stale 档案短路开出空分屏（__dyn__/__dir__ 同款）
  try { _subReset(); } catch(_) {}
  _hgConn.tab.remove();
  _hgConn.wrap.remove();
  delete connections[portId];
  _hgPanelMode(false);   // v2.31：关 harness tab 还原右侧工具面板（剩余 tab 的 switchTab 会再兜一次）
  const remaining = Object.keys(connections).sort((a, b) => {
    const ka = sortKeyFn(a), kb = sortKeyFn(b);
    return ka[0] !== kb[0] ? ka[0] - kb[0] : (ka[1] < kb[1] ? -1 : ka[1] > kb[1] ? 1 : 0);
  });
  if (remaining.length) switchTab(remaining[0]);
  else {
    activePortId = null;
    termArea.innerHTML = '<div class="empty-state"><div class="big-icon"><svg width="30" height="30" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="12.2" r="1.1"/><path d="M5 9.2a4.2 4.2 0 0 1 6 0"/><path d="M2.7 6.9a7.5 7.5 0 0 1 10.6 0"/></svg></div><div class="title">暂无连接</div><div class="desc">点击顶部「新建连接」选择串口或 SSH，支持同时监控多个连接。每个连接独立标签页，互不干扰。</div></div>';   // a261：信号 path 同库 signal 字形（30px 空态大图标）
  }
  refreshSidebar();
}

// ---- 顶栏 Claude 按钮分派 ----
let _claudeUiMode = null;
async function _getClaudeUiMode() {
  if (_claudeUiMode === null) {
    try {
      const j = await (await fetch('/api/theme')).json();
      _claudeUiMode = (j.ok && j.claude_ui_mode) ? j.claude_ui_mode : 'harness';
    } catch(_) { _claudeUiMode = 'harness'; }
  }
  return _claudeUiMode;
}
function setClaudeUiMode(m) { _claudeUiMode = m; }

async function claudeButtonAction() {
  const mode = await _getClaudeUiMode();
  if (mode === 'cli') connectClaude();
  else buildClaudeHarnessTab({});
}

// ---- 统一登录胶囊（侧栏底部）：代理/额度/机器人一次登录全通 ----
// 登录走共用接口 /api/proxy/credentials（单一事实源 lanz_credentials.json）；
// 凭据就位后端自动激活机器人（幂等），登出自动停用。未登录机器人不激活。
// 胶囊点击 → 冒泡弹窗（未登录=登录表单；已登录=状态+登出确认）。
// 机器人 LED：唯一表达在线/离线的载体（文案里不再重复「在线」）
function hgBotLed(st) {
  if (!st.manual) return 'hg-login-dot off';                  // 未配置凭据
  if (st.auth_failed) return 'hg-login-dot err';             // 凭据被拒
  if (!st.running) return 'hg-login-dot idle';               // 已配置未运行
  return st.connected ? 'hg-login-dot on' : 'hg-login-dot wait';   // 在线/连接中
}
// 弹窗内的机器人状态文字（不支持指示灯语义时的一行说明）
function hgBotPhase(st) {
  if (!st.manual) return '未配置凭据';
  if (st.auth_failed) return '凭据被拒，请检查 App ID/Secret';
  if (!st.running) return '已保存，未运行';
  return st.connected ? '在线' : '连接中…';
}
let _hgLastSt = {};
// 带超时的 JSON fetch（无超时时 worker 未就绪会永久挂住登录按钮）
async function _hgFetchJson(url, body, ms) {
  const ctl = new AbortController();
  const tid = setTimeout(() => ctl.abort(), ms || 5000);
  try {
    const r = await fetch(url, body ? {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: ctl.signal
    } : { signal: ctl.signal });
    return await r.json();
  } finally { clearTimeout(tid); }
}
// keepBaseline=true：乐观渲染不得写回基线，否则 running:true/connected:false
// 这类假值会被下一次合并沿用（手填胶囊一直显示「连接中…」）
function hgLoginRender(st, keepBaseline) {
  if (!keepBaseline) _hgLastSt = st || {};
  document.querySelectorAll('[data-hg-login-toggle]').forEach(tg => {
    const dot = tg.querySelector('[data-hg-login-dot]');
    const txt = tg.querySelector('[data-hg-login-text]');
    if (!txt) return;
    // 指示灯只表达机器人状态；用户名用颜色表达登录状态（铁律：不靠文案
    // 重复「在线/离线」）
    if (dot) dot.className = hgBotLed(st);
    if (st.username) {
      txt.textContent = st.username;
      txt.className = 'hg-login-userlabel on';
    } else {
      txt.textContent = '未登录';
      txt.className = 'hg-login-userlabel off';
    }
  });
  document.querySelectorAll('[data-hg-login-pop]').forEach(pop => {
    const off = pop.querySelector('[data-hg-login-off]');
    const on = pop.querySelector('[data-hg-login-on]');
    const nameEl = pop.querySelector('[data-hg-login-name]');
    if (!off || !on) return;
    if (st.username) {
      off.style.display = 'none'; on.style.display = '';
      if (nameEl) {
        nameEl.textContent = st.username;
        nameEl.className = 'hg-login-userlabel on';
      }
    } else {
      off.style.display = ''; on.style.display = 'none';
      if (nameEl) { nameEl.textContent = ''; nameEl.className = 'hg-login-userlabel'; }
    }
    // 机器人独立凭据（App ID/Secret）：已填则回显 App ID、secret 留空待改
    const rid = pop.querySelector('[data-hg-robot-id]');
    const rstate = pop.querySelector('[data-hg-robot-state]');
    if (rid) {
      // 输入即置 dirty；只有用户没动过才回填——否则 30s 轮询会把用户
      // 刚清空的 App ID 填回旧值，「两项皆空=清除」永远点不到
      hgRobotWire(rid);
      if (st.app_id && !rid.dataset.dirty && !rid.value) rid.value = st.app_id;
      // 服务端值与框内一致（用户改完/保存成功）才复位闸；框内为空而
      // 服务端有值 = 用户正在清空，「两项皆空=清除」不能被打断
      if (rid.dataset.dirty && st.app_id && rid.value === st.app_id) {
        rid.dataset.dirty = '';
      }
    }
    // 状态全由指示灯表达；文字只在不正常时给一句原因（在线不写字）。
    // 「未配置凭据」必须给文字——灰灯 off/idle 肉眼几乎无差别，用户分不清
    // 是没配还是配了没跑
    const rdot = pop.querySelector('[data-hg-robot-dot]');
    if (rdot) rdot.className = hgBotLed(st);
    if (rstate) {
      rstate.textContent = (!st.manual || st.auth_failed || !st.running)
        ? hgBotPhase(st) : '';
    }
    // 密钥真回显：有已存密钥就填进框（type=password 显示为 ******），
    // 点眼睛立刻能看到明文——不是占位符，用户能确认到底存没存
    const rsec = pop.querySelector('[data-hg-robot-secret]');
    if (rsec) {
      hgSecretWire(rsec);
      if (st.app_secret && !rsec.dataset.dirty && !rsec.value) {
        rsec.value = st.app_secret;
      }
      if (rsec.dataset.dirty && st.app_secret && rsec.value === st.app_secret) {
        rsec.dataset.dirty = '';
      }
    }
  });
}
// 密码类输入的显隐切换（SSH 同款）
function hgEyeWire(btn) {
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', ev => {
    ev.preventDefault();
    ev.stopPropagation();
    const inp = btn.parentElement.querySelector('input');
    if (!inp) return;
    const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    btn.innerHTML = show ? ICO16.eyeOff : ICO16.eye;
    btn.title = show ? '隐藏' : '显示';
  });
}
document.querySelectorAll('[data-hg-eye]').forEach(hgEyeWire);
// App ID 输入的 dirty 监听：必须在首次 render 之前就挂上——首屏 status
// 拉取失败时 render 从未执行，若监听只在 render 里挂，用户清空 App ID
// 的「清除」意图会被后续回填静默抹掉
function hgRobotWire(rid) {
  if (!rid || rid.dataset.wired) return;
  rid.dataset.wired = '1';
  rid.addEventListener('input', () => { rid.dataset.dirty = '1'; });
}
document.querySelectorAll('[data-hg-robot-id]').forEach(hgRobotWire);
// 密钥框的 dirty 监听（同款：用户改过就不再被轮询回填覆盖）
function hgSecretWire(sec) {
  if (!sec || sec.dataset.wired) return;
  sec.dataset.wired = '1';
  sec.addEventListener('input', () => { sec.dataset.dirty = '1'; });
}
function hgLoginTogglePop(force) {
  document.querySelectorAll('[data-hg-login-pop]').forEach(pop => {
    const opening = (force !== undefined ? force : pop.style.display === 'none');
    // 每次展开重置回填闸并立即回填：dirty 粘住会让框一直空着；而只清
    // dirty 不回填则「框空 + 点保存」等价于清除凭据，一次误点就掉线
    if (opening) {
      const rid = pop.querySelector('[data-hg-robot-id]');
      // 状态未知时先补拉一次：否则框空着、用户以为没配置过，误点保存
      // 就是「清除凭据」
      if (!Object.keys(_hgLastSt).length) hgLoginRefresh();
      if (rid) {
        rid.dataset.dirty = '';
        if (!rid.value && _hgLastSt.app_id) rid.value = _hgLastSt.app_id;
      }
      // 密钥同款：只复位 App ID 会让「清空密钥并保存」后密钥框永久为空，
      // 与后端实际值（留空即沿用旧密钥）不符
      const rsec = pop.querySelector('[data-hg-robot-secret]');
      if (rsec) {
        rsec.dataset.dirty = '';
        if (!rsec.value && _hgLastSt.app_secret) rsec.value = _hgLastSt.app_secret;
      }
    }
    pop.style.display = opening ? '' : 'none';
  });
}
async function hgLoginRefresh() {
  try {
    // 必须带超时：worker 半死时裸 fetch 永不 settle，30s 定时器会不断
    // 累积 pending 请求占满连接池，连「保存机器人」也会被排队拖超时
    const j = await _hgFetchJson('/api/hiklink/status', null, 4000);
    if (j && j.ok) hgLoginRender(j);
  } catch (_) {}
}
document.addEventListener('click', async ev => {
  // 冒泡弹窗开合：点胶囊切换；点弹窗内部不关；点其他区域关闭
  const toggle = ev.target.closest('[data-hg-login-toggle]');
  if (toggle) { hgLoginTogglePop(); return; }
  if (!ev.target.closest('[data-hg-login-pop]')) hgLoginTogglePop(false);
  const loginBtn = ev.target.closest('[data-hg-login-btn]');
  if (loginBtn) {
    const pop = loginBtn.closest('[data-hg-login-pop]');
    const uEl = pop.querySelector('[data-hg-login-user]');
    const pEl = pop.querySelector('[data-hg-login-pwd]');
    const u = (uEl.value || '').trim(), p = pEl.value || '';
    if (!u || !p) { (u ? pEl : uEl).focus(); return; }
    loginBtn.disabled = true; const old = loginBtn.textContent;
    loginBtn.textContent = '登录中…';
    try {
      const sj = await _hgFetchJson('/api/proxy/credentials',
        { action: 'save', username: u, password: p }, 8000);
      // v2.2.2：写盘失败如实报错——旧版静默吞 + 乐观渲染「已登录」，
      // 凭据实际没落盘，重启就得重登（同事机实锤）
      if (!sj.ok) { showBanner(sj.msg || '登录保存失败', 4000, true); return; }
      // 后端会如实回报机器人是否启用（凭证模式下账号登录不激活机器人），
      // 成功分支也要显示——否则「机器人未启用（…）」这条提示用户看不到
      if (sj.msg) showBanner(sj.msg, 4000, false);
      // 凭据就位后端已尝试激活；再显式触发一次（幂等），结果如实使用
      // （无凭证时不要乐观显示 running:true）
      const aj = await _hgFetchJson('/api/hiklink/activate', {}, 5000)
        .catch(() => null);
      // 乐观渲染只补登录态字段，合并上一次真实状态——整块替换会把
      // manual/app_id/auth_failed 抹掉。基线为空（首屏状态拉取失败）时
      // 先补拉一次，否则手填模式这一帧文案整体退回「已登录」。
      // 两处 fetch 都带超时：worker 未就绪时无超时会永久挂住按钮
      if (!Object.keys(_hgLastSt).length) {
        try {
          const jsStatus = await _hgFetchJson('/api/hiklink/status', null, 4000);
          if (jsStatus && jsStatus.ok) _hgLastSt = jsStatus;
        } catch (_) {}
      }
      // 乐观渲染只补登录态；机器人 running 只在后端确认激活成功时才置真
      // （无凭证时置真会让胶囊显示「连接中…」，1.5s 后才被纠偏）
      const botOn = !!(aj && aj.ok);
      hgLoginRender(Object.assign({}, _hgLastSt,
        { username: u, running: botOn, connected: false }), true);
      pEl.value = '';
      setTimeout(hgLoginRefresh, 1500);
    } catch (_) {}
    loginBtn.disabled = false; loginBtn.textContent = old;
    return;
  }
  const outBtn = ev.target.closest('[data-hg-logout-btn]');
  if (outBtn) {
    // 带超时：worker 半死时裸 fetch 会让登出按钮毫无反馈
    try { await _hgFetchJson('/api/proxy/credentials',
      { action: 'clear' }, 6000); } catch (_) {}
    hgLoginRefresh();
  }
  // 保存机器人凭据：两项都空=清除（机器人离线），否则保存并重连
  const rSave = ev.target.closest('[data-hg-robot-save]');
  if (rSave) {
    const pop = rSave.closest('[data-hg-login-pop]');
    const id = (pop.querySelector('[data-hg-robot-id]').value || '').trim();
    let secret = (pop.querySelector('[data-hg-robot-secret]').value || '').trim();
    // 密钥框留空 = 沿用已存密钥（仅 App ID 未变时；换 ID 必须重填）
    const keepSecret = !secret && id && _hgLastSt.manual
      && _hgLastSt.app_id === id;
    if (id && !secret && !keepSecret) {
      showBanner('请填写 App Secret', 3000, true); return;
    }
    if (!id && secret) { showBanner('请填写 App ID', 3000, true); return; }
    // 两项皆空 = 清除凭据并导致机器人掉线。状态未知（首屏 status 没拉到、
    // _hgLastSt 为空）时按「有风险」处理——undefined 不能当 false 放行
    if (!id && !secret && _hgLastSt.manual !== false
        && !confirm('将清除已保存的机器人凭据并断开当前机器人连接，确定吗？')) {
      return;
    }
    rSave.disabled = true; const old = rSave.textContent;
    rSave.textContent = '保存中…';
    try {
      // 用带超时的封装：worker 半死（端口 accept 但不响应）时裸 fetch
      // 永不 settle，按钮会永久卡在「保存中…」
      const j = await _hgFetchJson('/api/hiklink/credentials',
        { app_id: id, app_secret: secret }, 15000);
      showBanner(j.msg || (j.ok ? '已保存' : '保存失败'), 4000, !j.ok);
      setTimeout(hgLoginRefresh, 1500);
    } catch (_) { showBanner('保存请求失败', 3000, true); }
    rSave.disabled = false; rSave.textContent = old;
    return;
  }
});
setInterval(hgLoginRefresh, 30000);   // 低频保活（登录态/机器人在线显示）
hgLoginRefresh();

// ---- Proxy 状态按钮（输入卡上方，原顶部按钮迁入）：显示运行态+端口，点击开代理面板 ----
// a448（用户需求）：悬浮显示模型负载。后端 status 只在「上游是 lanz」且已登录
// 时下发 model_loads；有数据才出悬浮卡，不是 lanz 网关时保持原样。
let _hgProxyLoads = null;     // 最近一次 status 的 model_loads（悬浮时直接用）
let _hgLoadsTip = null;

function _hgLoadsTipEl() {
  if (_hgLoadsTip && document.contains(_hgLoadsTip)) return _hgLoadsTip;
  const el = document.createElement('div');
  el.className = 'hg-loads-tip';
  el.style.display = 'none';
  document.body.appendChild(el);
  _hgLoadsTip = el;
  return el;
}
function _hgLoadsPaint(anchor) {
  const loads = _hgProxyLoads;
  if (!loads || !loads.length) return;
  const tip = _hgLoadsTipEl();
  // a449（用户实锤）：去掉标题行——它在深色背景上是一条突兀的黑条，且
  // 「6 个模型」这种计数对用户没信息量；卡片直接就是负载列表。
  tip.innerHTML = loads.map(m => {
      const pct = (m.pct == null) ? null : m.pct;
      const cls = m.level ? ' px-load--' + m.level : '';
      return '<div class="hg-loads-row"><span class="hg-loads-name">' + esc(m.name) + '</span>' +
        '<span class="hg-loads-bar' + cls + '"><i style="width:' + (pct == null ? 0 : pct) + '%"></i></span>' +
        '<span class="hg-loads-pct' + cls + '">' + (pct == null ? '--' : pct + '%') + '</span></div>';
    }).join('');
  tip.style.display = 'block';
  const r = anchor.getBoundingClientRect();
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  // a449（用户实锤「窗口向下被截断」）：Proxy 按钮贴窗口下沿，向下弹必然
  // 被裁。优先向上弹（卡片底部对齐按钮顶部上方 6px）；上方也放不下时
  // 退化为「贴视口顶部、向下弹」。
  let top = r.top - th - 6;
  if (top < 8) top = Math.min(r.bottom + 6, Math.max(8, window.innerHeight - th - 8));
  tip.style.top = Math.round(top) + 'px';
  tip.style.left = Math.round(r.left) + 'px';
  // 右缘防溢出
  if (r.left + tw > window.innerWidth - 8) {
    tip.style.left = Math.max(8, window.innerWidth - tw - 8) + 'px';
  }
}
function _hgLoadsHide() {
  if (_hgLoadsTip) _hgLoadsTip.style.display = 'none';
  _hgLoadsStopTick();
}
// a450（用户实锤「一直悬浮就不更新」）：原来只在 mouseover 拉一次，悬停期间
// 数值冻住，挪开再回来才变。悬停期间按 20s（后端缓存 TTL）定时重拉，卡片
// 可见时跟着重绘；鼠标离开即停。
let _hgLoadsTick = null;
function _hgLoadsStopTick() {
  if (_hgLoadsTick) { clearInterval(_hgLoadsTick); _hgLoadsTick = null; }
}
function _hgLoadsTickStart(anchor) {
  _hgLoadsStopTick();
  _hgLoadsTick = setInterval(() => {
    if (!_hgLoadsTip || _hgLoadsTip.style.display === 'none') { _hgLoadsStopTick(); return; }
    _hgProxyHoverAnchor = anchor;
    hgProxyRefreshState();     // 拉到新数据后由下方 .then 重绘
  }, 20000);
}
let _hgProxyHoverAnchor = null;
document.addEventListener('mouseover', ev => {
  const btn = ev.target.closest('[data-hg-proxy-btn]');
  if (!btn) return;
  // mouseover 在按钮内子元素间移动会反复触发——只在「进入按钮」这一次
  // （relatedTarget 不在按钮内）才拉数据 + 重臂定时器，否则悬停时每秒
  // 好几发请求。
  if (btn.contains(ev.relatedTarget)) return;
  _hgProxyHoverAnchor = btn;
  hgProxyRefreshState();
  _hgLoadsPaint(btn);
  _hgLoadsTickStart(btn);
});
document.addEventListener('mouseout', ev => {
  const btn = ev.target.closest('[data-hg-proxy-btn]');
  if (!btn) return;
  // 同上：移去按钮内部的子元素不算离开
  if (btn.contains(ev.relatedTarget)) return;
  _hgProxyHoverAnchor = null;
  _hgLoadsHide();
});

function hgProxyRefreshState() {
  const fetchIt = async () => {
    try {
      const r = await fetch('/api/proxy/status');
      const j = await r.json();
      let txt = '· 未运行', cls = ' off';
      if (j.already_running || j.running) {
        // a451（用户实锤「要么运行中要么重试中，不能运行中（重试中）」）：
        // 重试是「处理中」的独立状态，不与运行中叠加——有在途重试就只显示
        // 重试中（既省宽度不换行，也让用户一眼判断当前是否被限流重试）。
        const retrying = !!(j.running && j.snapshot && j.snapshot.in_flight_retries > 0);
        txt = retrying ? '· 37349 重试中' : '· 37349 运行中';
        cls = ' on';
      } else if (j.port_busy) {
        txt = '· 端口被占'; cls = ' err';
      }
      document.querySelectorAll('[data-hg-proxy-state]').forEach(el => {
        el.textContent = txt;
        el.className = 'hg-proxy-state' + cls;
      });
      // a448：悬浮卡的负载数据（无数据时置空，悬浮不出卡）
      _hgProxyLoads = (j.model_loads && j.model_loads.length) ? j.model_loads : null;
      // a450：卡片在场时跟着刷新（悬停定时器 20s 一拉，数据回来就重绘）
      if (_hgProxyHoverAnchor && _hgLoadsTip && _hgLoadsTip.style.display !== 'none') {
        if (_hgProxyLoads) _hgLoadsPaint(_hgProxyHoverAnchor);
        else _hgLoadsHide();
      }
    } catch (_) {}
  };
  fetchIt();
}
document.addEventListener('click', ev => {
  const btn = ev.target.closest('[data-hg-proxy-btn]');
  if (btn && typeof buildProxyTab === 'function') buildProxyTab();
});
// 事件通知（不轮询）：后端在代理状态变化点广播 SSE 信号，前端收到即拉一次
// status 同步显示。连接断开时 EventSource 自动重连；首屏状态由页面加载时
// 的 hgProxyRefreshState() 拉取。
try {
  const hgProxyES = new EventSource('/api/proxy/events');
  hgProxyES.onmessage = () => hgProxyRefreshState();
} catch (_) {}
hgProxyRefreshState();

// v3.5.243（开发期缓存穿透坑提醒）：页面 JS 的 ?v= 由后端长驻进程注入，
// 后端不重启则 URL 不变→浏览器命中旧缓存（用户刷新/重启页面均无效）。
// 加载时实时对比：页面注入版本 vs 后端当前版本，不一致提示重启工具。
(function () {
  try {
    var pageVer = (window._HG_VER || '').replace('v', '');
    if (!pageVer) return;
    fetch('/api/harness/version').then(r => r.json()).then(j => {
      var live = (j && j.harness) || '';
      if (live && pageVer !== live) {
        showBanner('工具内核已更新（页面 ' + pageVer + ' → 后端 ' + live
          + '）——请完全重启工具生效', 8000, true);
      }
    }).catch(() => {});
  } catch (_) {}
})();
