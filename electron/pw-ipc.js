'use strict';
// 工具内置密码填充 IPC（用户令终版：点密码框→候选；登录→保存提示）。
// 存储由 electron/passwords.js（safeStorage/DPAPI）完成，主 UI 不提供建库/
// 主密码/管理列表。安全边界：
//  - guest 只拿自己顶层 origin 的用户名列表（无密码）；选中后主进程才把
//    密码下发给该 guest preload 填表；子帧/伪造 origin 拒绝。
//  - 保存必须主 UI 确认；提示只含 origin/user。
function register({ ipcMain, getWin, store }) {
  const pending = new Map();
  const suggests = new Map();
  let seq = 0;

  function winRef() { return getWin && getWin(); }
  function isMainUi(event) {
    const win = winRef();
    return !!win && !win.isDestroyed() && event.sender === win.webContents;
  }
  function guestOrigin(event) {
    try {
      if (event.sender.getType() !== 'webview') return '';
      const f = event.senderFrame;
      if (!f || f.parent) return '';   // 只认顶层 frame
      return store.originOf(f.url);
    } catch (_) { return ''; }
  }
  function num(v, dft, max) {
    const n = Number(v);
    if (!Number.isFinite(n)) return dft;
    return Math.max(0, Math.min(max, n));
  }
  function sanitizeRect(r) {
    r = r || {};
    return {
      left: num(r.left, 0, 20000), top: num(r.top, 0, 20000),
      width: num(r.width, 0, 20000), height: num(r.height, 0, 20000),
    };
  }

  // 点登录框 → 该 origin 已存账号 → 主 UI 弹层（无密码）
  ipcMain.on('fc-pw:suggest', (event, data) => {
    const origin = guestOrigin(event);
    if (!origin) return;
    const win = winRef();
    if (!win || win.isDestroyed()) return;
    const nonce = String((data && data.nonce) || '').slice(0, 64);
    const rect = sanitizeRect(data && data.rect);
    for (const [k, s] of suggests) {
      if (s.sender === event.sender) { clearTimeout(s.timer); suggests.delete(k); }
    }
    let items = [];
    try { items = store.listForOrigin(origin); } catch (_) {}
    if (!items.length) {
      win.webContents.send('fc:pw-suggest-hide', { id: 0 });
      return;
    }
    const id = ++seq;
    const timer = setTimeout(() => {
      const s = suggests.get(id);
      if (!s) return;
      suggests.delete(id);
      const w = winRef();
      if (w && !w.isDestroyed()) w.webContents.send('fc:pw-suggest-hide', { id });
    }, 20000);
    suggests.set(id, { sender: event.sender, origin, nonce, items, timer });
    win.webContents.send('fc:pw-suggest', { id, origin, items, rect });
  });

  ipcMain.handle('fc-pw:fill', (event, id, index) => {
    if (!isMainUi(event)) return { ok: false, err: 'forbidden' };
    const s = suggests.get(Number(id));
    if (!s) return { ok: false, err: '候选已过期' };
    const item = s.items[Number(index)];
    if (!item) return { ok: false, err: '无效候选' };
    try {
      const r = store.reveal(s.origin, item.user);
      if (!r || !r.ok || !r.pw) throw new Error((r && r.err) || '读取失败');
      suggests.delete(Number(id));
      clearTimeout(s.timer);
      if (s.sender.isDestroyed()) return { ok: false, err: '页面已关闭' };
      s.sender.send('fc-pw:fill', {
        nonce: s.nonce, user: item.user || '', password: r.pw,
      });
      return { ok: true };
    } catch (e) {
      return { ok: false, err: String((e && e.message) || e) };
    }
  });

  ipcMain.handle('fc-pw:suggest-close', (event, id) => {
    if (!isMainUi(event)) return { ok: false, err: 'forbidden' };
    const s = suggests.get(Number(id));
    if (s) { suggests.delete(Number(id)); clearTimeout(s.timer); }
    return { ok: true };
  });

  ipcMain.on('fc-pw:guest-blur', (event, nonce) => {
    const hit = [...suggests.entries()].find(
      ([, s]) => s.sender === event.sender && s.nonce === String(nonce || ''));
    if (!hit) return;
    const [id, s] = hit;
    setTimeout(() => {
      if (suggests.get(id) !== s) return;
      suggests.delete(id);
      clearTimeout(s.timer);
      const w = winRef();
      if (w && !w.isDestroyed()) w.webContents.send('fc:pw-suggest-hide', { id });
    }, 400);
  });

  // 登录提交 → 主 UI 问“是否保存”（只含 origin/user）
  ipcMain.on('fc-pw:guest-capture', (event, data) => {
    const origin = guestOrigin(event);
    if (!origin || !data || typeof data !== 'object') return;
    const user = String(data.user == null ? '' : data.user).slice(0, 256);
    const password = String(data.password == null ? '' : data.password);
    if (!password || password.length > 4096) return;
    try {
      const cur = store.find(origin, user);
      if (cur && cur.password === password) return;   // 同款免打扰
    } catch (_) { return; }
    const win = winRef();
    if (!win || win.isDestroyed()) return;
    for (const [k, p] of pending) {
      if (p.origin === origin && p.user === user) {
        clearTimeout(p.timer);
        pending.delete(k);
      }
    }
    const id = ++seq;
    const timer = setTimeout(() => pending.delete(id), 60000);
    pending.set(id, { origin, user, password, timer });
    win.webContents.send('fc:pw-save-prompt', { id, origin, user });
  });

  ipcMain.handle('fc-pw:save', async (event, id) => {
    if (!isMainUi(event)) return { ok: false, err: 'forbidden' };
    const p = pending.get(Number(id));
    if (!p) return { ok: false, err: '提示已过期' };
    try {
      store.upsert(p.origin, p.user, p.password);
      pending.delete(Number(id));
      clearTimeout(p.timer);
      return { ok: true };
    } catch (e) {
      return { ok: false, err: String((e && e.message) || e) };
    }
  });

  ipcMain.handle('fc-pw:discard', (event, id) => {
    if (!isMainUi(event)) return { ok: false, err: 'forbidden' };
    const p = pending.get(Number(id));
    if (p) { pending.delete(Number(id)); clearTimeout(p.timer); }
    return { ok: true };
  });
}

module.exports = { register };
