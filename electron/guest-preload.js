'use strict';
// P3 壳形态 guest preload（用户令 2026-11-20：壳内保存/自动填充）。
//
// 只做两件事：登录页自动填充、提交时把凭据交给主进程询问是否保存。
// 安全边界：
//  - 只在隔离世界运行（contextIsolation + sandbox），**不向页面暴露任何
//    对象/API**；页面只能通过正常 DOM 读写感知填充结果，与浏览器一致。
//  - 只在顶层 frame、http(s) 页面生效；不碰子帧/本地页/about:blank。
//  - 不打印、不落 localStorage、不发网络请求；凭据只走 ipcRenderer 到主进程。
//  - 自动填充只认精确 origin（主进程按 senderFrame.url 复核，页面伪造不了）。
const { ipcRenderer } = require('electron');

function isTop() {
  try { return window.top === window; } catch (_) { return false; }
}
function isWeb() {
  return location.protocol === 'http:' || location.protocol === 'https:';
}

if (isTop() && isWeb()) {
  let lastGesture = 0;
  let lastPointerEl = null;   // 判断 focus 是否来自“真的点在字段上”
  let lastPointerAt = 0;
  let lastKey = '';
  let lastKeyAt = 0;
  let suppressUntil = 0;      // 选中填充/提交后短暂抑制，防焦点回抢再弹层
  addEventListener('pointerdown', (e) => {
    lastGesture = Date.now();
    lastPointerEl = e.target;
    lastPointerAt = Date.now();
  }, true);
  addEventListener('keydown', (e) => {
    lastGesture = Date.now();
    lastKey = e.key;
    lastKeyAt = Date.now();
  }, true);

  function visible(el) {
    try {
      if (!el || el.disabled) return false;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return false;
      const st = getComputedStyle(el);
      return st.visibility !== 'hidden' && st.display !== 'none'
        && st.opacity !== '0';
    } catch (_) { return false; }
  }

  function passFields(root) {
    return Array.from((root || document).querySelectorAll('input[type="password"]'))
      .filter(visible);
  }

  function looksLikeNewPw(el) {
    return String(el.getAttribute('autocomplete') || '').toLowerCase()
      === 'new-password';
  }

  function findUser(form, pw) {
    const root = form || document;
    const all = Array.from(root.querySelectorAll('input')).filter(visible);
    const i = all.indexOf(pw);
    const before = i >= 0 ? all.slice(0, i) : all;
    const score = (el) => {
      if (el === pw || el.type === 'password' || el.type === 'hidden') return -1;
      const s = ((el.getAttribute('autocomplete') || '') + ' '
        + (el.name || '') + ' ' + (el.id || '') + ' '
        + (el.getAttribute('placeholder') || '')).toLowerCase();
      if ((el.getAttribute('autocomplete') || '') === 'username') return 10;
      if (el.type === 'email') return 7;
      if (/username|user|email|login|account|phone|mobile/.test(s)) return 6;
      if (el.type === 'text' || el.type === 'tel' || !el.type) return 1;
      return 0;
    };
    let best = null;
    let bs = 0;
    for (const el of before) {   // 同分取更靠近密码框（靠后）的
      const sc = score(el);
      if (sc >= bs && sc > 0) { bs = sc; best = el; }
    }
    return best;
  }

  function setVal(el, v) {
    try {
      const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
      if (d && d.set) d.set.call(el, v); else el.value = v;
    } catch (_) { try { el.value = v; } catch (_) { return; } }
    try {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (_) {}
  }

  // 自动填充已改成“点击/聚焦后选择式填充”（Edge 风格）：页面加载不再
  // 直接回填；点击登录框 → 主进程推候选 → 选中后才 fill。密码在选中前
  // 不会下发到页面。

  // 凭据捕获：表单 submit / 无 form 的登录按钮点击 / 密码框回车，三条入口。
  // 内网发布中心就是「单密码框 + 进入按钮、无 form、fetch 登录」——只监听
  // submit 会完全不触发（用户实测）。capture 阶段只读不拦；必须有近期用户
  // 手势，防页面自动触发弹保存框；单密码框、非 new-password、密码非空。
  const LOGIN_RE = /登录|登入|进入|提交|确定|下一步|继续|login|sign\s*in|submit|continue|next/i;
  let lastCap = { sig: '', t: 0 };

  function captureCreds(pw, userEl) {
    if (!pw || !pw.value) return;
    const sig = (userEl ? userEl.value : '') + '\u0000' + pw.value;
    const now = Date.now();
    // click 与 submit / Enter 可能连续触发同一份凭据：1.5s 同签名去重
    if (sig === lastCap.sig && now - lastCap.t < 1500) return;
    lastCap = { sig, t: now };
    suppressUntil = Date.now() + 1000;   // 提交后页面常把焦点抢回密码框
    try {
      ipcRenderer.send('fc-pw:guest-capture', {
        user: userEl ? userEl.value : '',
        password: pw.value,
      });
    } catch (_) {}
  }

  function singleLoginPw(root) {
    const pws = passFields(root || document);
    if (pws.length !== 1 || looksLikeNewPw(pws[0])) return null;
    return pws[0];
  }
  function recencyOK(e) {
    return !!(e.isTrusted || Date.now() - lastGesture < 10000);
  }

  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!form || form.tagName !== 'FORM' || !recencyOK(e)) return;
    const pw = singleLoginPw(form);
    if (!pw) return;
    captureCreds(pw, findUser(form, pw));
  }, true);

  // 无 form 的登录：按钮文案命中登录语义，且页面只有一个密码框。
  // 按钮在该 form 内时交给 submit（另有 1.5s 同签名去重兜底）。
  document.addEventListener('click', (e) => {
    if (!recencyOK(e)) return;
    const btn = e.target && e.target.closest
      ? e.target.closest('button, input[type=submit], input[type=button], [role="button"], a')
      : null;
    if (!btn) return;
    const pw = singleLoginPw(document);
    if (!pw) return;
    const form = btn.closest('form');
    if (form && form.contains(pw)) return;
    const label = (btn.textContent || btn.value
      || btn.getAttribute('aria-label') || '').trim();
    if (!LOGIN_RE.test(label)) return;
    captureCreds(pw, findUser(document, pw));
  }, true);

  // 无 form 登录靠回车触发的情况（只认密码框/用户名框上的 Enter）
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !recencyOK(e)) return;
    const t = e.target;
    if (!t || t.tagName !== 'INPUT') return;
    const pw = singleLoginPw(document);
    if (!pw) return;
    const u = findUser(t.closest('form') || document, pw);
    if (t !== pw && !(u && t === u)) return;
    captureCreds(pw, u);
  }, true);

  // ---- 选择式填充（Edge 风格）----
  // 用户点击/聚焦登录字段 → 上报字段 rect + nonce；主进程把候选（无密码）
  // 推给主 UI 弹层；选中后主进程把 {nonce,user,password} 推回这里才填。
  let suggestNonce = 0;
  let lastSuggestAt = 0;
  let lastSuggestField = null;

  function loginFieldOf(t) {
    if (!t || t.tagName !== 'INPUT') return null;
    const pw = singleLoginPw(document);
    if (!pw) return null;
    const u = findUser(pw.closest('form') || document, pw);
    return (t === pw || (u && t === u)) ? t : null;
  }

  // focus 是否来自用户真实操作：点在字段（或其 label）上，或 Tab 进入。
  // 页面的 autofocus / 提交后 JS 回焦不算——否则会在没点输入框时就弹。
  function suggestAllowedForFocus(t) {
    const now = Date.now();
    if (lastPointerEl && now - lastPointerAt < 1200) {
      if (lastPointerEl === t) return true;
      if (lastPointerEl.contains && lastPointerEl.contains(t)) return true;
      if (lastPointerEl.tagName === 'LABEL' && lastPointerEl.control === t) {
        return true;
      }
    }
    if (lastKey === 'Tab' && now - lastKeyAt < 1200) return true;
    return false;
  }

  function requestSuggest(field) {
    if (!field || !visible(field)) return;
    if (Date.now() < suppressUntil) return;
    const now = Date.now();
    if (now - lastSuggestAt < 250 && lastSuggestField === field) return;
    lastSuggestAt = now;
    lastSuggestField = field;
    suggestNonce = (suggestNonce + 1) % 1000000000;
    const r = field.getBoundingClientRect();
    try {
      ipcRenderer.send('fc-pw:suggest', {
        nonce: suggestNonce,
        rect: { left: r.left, top: r.top, width: r.width, height: r.height },
      });
    } catch (_) {}
  }

  document.addEventListener('click', (e) => {
    if (!recencyOK(e)) return;
    const f = loginFieldOf(e.target);
    if (f) requestSuggest(f);
  }, true);

  document.addEventListener('focusin', (e) => {
    // 只认真实用户操作（点在字段/label 或 Tab），autofocus 与提交后回焦不弹
    if (!suggestAllowedForFocus(e.target)) return;
    const f = loginFieldOf(e.target);
    if (f) requestSuggest(f);
  }, true);

  document.addEventListener('focusout', (e) => {
    if (!e.target || e.target.tagName !== 'INPUT' || !suggestNonce) return;
    try { ipcRenderer.send('fc-pw:guest-blur', suggestNonce); } catch (_) {}
  }, true);

  ipcRenderer.on('fc-pw:fill', (_e, d) => {
    if (!d || !suggestNonce || String(d.nonce) !== String(suggestNonce)) return;
    suggestNonce = 0;
    const pw = singleLoginPw(document);
    if (!pw) return;
    const u = findUser(pw.closest('form') || document, pw);
    if (u && d.user) setVal(u, d.user);
    setVal(pw, d.password || '');
    d.password = '';   // 尽量断开明文引用
    suppressUntil = Date.now() + 1500;   // 选中后点“进入”不再弹第二次
  });

  // 站点菜单（🔑）点“填充”走主进程直推，无候选 nonce；同样抑制回弹
  ipcRenderer.on('fc-pw:fill-now', (_e, d) => {
    if (!d || !d.password) return;
    const pw = singleLoginPw(document);
    if (!pw) return;
    const u = findUser(pw.closest('form') || document, pw);
    if (u && d.user) setVal(u, d.user);
    setVal(pw, d.password);
    d.password = '';
    suppressUntil = Date.now() + 1500;
  });
}
