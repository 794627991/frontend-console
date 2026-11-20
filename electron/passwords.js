'use strict';
// 工具内置密码存储（用户令 2026-11-20 终版：前端只弹“是否保存/选择账号”，
// 存储与加密在工具内部自行完成，不要求用户建库/输主密码）。
//
//  - 落盘：Electron safeStorage（Windows=DPAPI，绑定当前用户）加密整个 JSON；
//    文件在 userData/passwords.bin，不落明文、不进日志、不进 localStorage。
//  - 按精确 origin（scheme+host+port）存取；只允许 http(s)。
//  - 页面只能拿候选用户名（无密码）；选中后主进程才下发密码填表。
//  - 兼容旧版同路径的 passwords.bin（格式相同），用户已有条目直接沿用。
const { app, safeStorage } = require('electron');
const fs = require('fs');
const path = require('path');

const MAX_ENTRIES = 200;
const MAX_PW_LEN = 4096;
const MAX_USER_LEN = 256;

const FILE = () => path.join(app.getPath('userData'), 'passwords.bin');
let cache = null;

function blank() { return { version: 1, entries: [] }; }

function load() {
  if (cache) return cache;
  try {
    const buf = fs.readFileSync(FILE());
    const j = JSON.parse(safeStorage.decryptString(buf));
    cache = (j && Array.isArray(j.entries)) ? j : blank();
  } catch (_) {
    cache = blank();
  }
  return cache;
}

function persist() {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('系统加密不可用（safeStorage），拒绝明文落盘');
  }
  const buf = safeStorage.encryptString(JSON.stringify(cache));
  const dst = FILE();
  const tmp = dst + '.tmp';
  fs.writeFileSync(tmp, buf, { mode: 0o600 });
  try {
    fs.renameSync(tmp, dst);
  } catch (_) {
    fs.writeFileSync(dst, buf, { mode: 0o600 });
    try { fs.unlinkSync(tmp); } catch (_) {}
  }
}

function originOf(url) {
  try {
    const u = new URL(String(url || ''));
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
    return u.origin;
  } catch (_) { return ''; }
}

function normUser(u) {
  return String(u == null ? '' : u).slice(0, MAX_USER_LEN);
}

// 同一 origin 下按用户名去重，最近更新的排前面
function listForOrigin(origin) {
  const byUser = new Map();
  for (const e of load().entries) {
    if (e.origin !== origin) continue;
    const u = e.user || '';
    const old = byUser.get(u);
    if (!old || (e.updated || 0) > (old.updated || 0)) byUser.set(u, e);
  }
  return [...byUser.values()]
    .sort((a, b) => (b.updated || 0) - (a.updated || 0))
    .map((e) => ({ user: e.user || '', updated: e.updated || 0 }));
}

function find(origin, user) {
  const u = normUser(user);
  return load().entries.find((e) => e.origin === origin && (e.user || '') === u);
}

function reveal(origin, user) {
  const e = find(origin, user);
  if (!e) return { ok: false, err: '未找到条目' };
  return { ok: true, pw: e.password };
}

function upsert(origin, user, password) {
  if (!origin) throw new Error('非法 origin');
  const pw = String(password == null ? '' : password);
  if (!pw || pw.length > MAX_PW_LEN) throw new Error('密码为空或过长');
  const u = normUser(user);
  const c = load();
  const now = Date.now();
  const e = c.entries.find((x) => x.origin === origin && (x.user || '') === u);
  if (e) {
    if (e.password === pw) return { ok: true, unchanged: true };
    e.password = pw;
    e.updated = now;
  } else {
    c.entries.push({ origin, user: u, password: pw, created: now, updated: now });
    if (c.entries.length > MAX_ENTRIES) {
      c.entries.sort((a, b) => (a.updated || 0) - (b.updated || 0));
      c.entries.splice(0, c.entries.length - MAX_ENTRIES);
    }
  }
  persist();
  return { ok: true };
}

function remove(origin, user) {
  const u = normUser(user);
  const c = load();
  const i = c.entries.findIndex(
    (e) => e.origin === origin && (e.user || '') === u);
  if (i < 0) return { ok: false, err: '未找到条目' };
  c.entries.splice(i, 1);
  persist();
  return { ok: true };
}

module.exports = { originOf, listForOrigin, find, reveal, upsert, remove };
