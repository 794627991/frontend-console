// hgstate.js（a654）：跨模块显式状态 API——state store 化试点。
//
// 背景：state.js 的 44 个 defineProperty 存取器把跨文件共享状态以「全局
// 可变态」暴露，读写点分散、来源不可追踪（本会话事故的最大教训是同一
// 状态存在多条通路）。本模块提供最小的 get/set/subscribe，试点迁移
// rolesCache / agentModelsTried 两个状态；验证方法论后再决定是否推广。
//
// 纪律（试点验收）：
//   - 迁移状态的**全部**读写必须经 HgState；不得再出现裸变量/直挂 window。
//   - 未迁移状态维持原存取器不动（不做大爆炸）。
const _m = new Map();
const _subs = new Map();

const HgState = {
  get(key, dflt) {
    return _m.has(key) ? _m.get(key) : dflt;
  },
  set(key, val) {
    _m.set(key, val);
    const subs = _subs.get(key);
    if (subs) {
      subs.forEach(function (fn) {
        try { fn(val); } catch (_) {}
      });
    }
  },
  has(key) { return _m.has(key); },
  del(key) { _m.delete(key); },
  subscribe(key, fn) {
    if (typeof fn !== 'function') return function () {};
    let s = _subs.get(key);
    if (!s) _subs.set(key, s = new Set());
    s.add(fn);
    return function () { s.delete(fn); };
  },
  keys() { return Array.from(_m.keys()); }
};

window.HgState = HgState;
