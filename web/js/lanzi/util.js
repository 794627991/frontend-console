// lanzi/util.js — Lanzi 专栏公共小工具（a673 模块化拆分）
//
// 拆出来的原因：数字缩写、操作反馈保鲜期语义在额度/机器人/宿主三处都要用，
// 原先散在 panel.js 的单一大闭包里，拆文件后必须显式共享。

// HTML 转义：复用经典脚本 util.js 挂在 window 上的实现（单一真源），
// 在 ES module 里显式包一层，避免 no-undef 并让依赖关系可读。
export const esc = (s) => window.esc(s);

// 数字缩写（与后端 lanzi.api.fnum / 代理 _pxFnum 同口径）
export function lzFnum(n) {
  n = Number(n) || 0;
  if (n >= 1e8) return String(Math.round(n));
  if (n >= 1e4) return (n / 1e4).toFixed(1) + 'W';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
}

// token 缩写：1234567 → 1.23M
export function lzTok(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
}

// 操作反馈区（与代理面板同款保鲜期语义）：
//   点按钮的结果写 6s，期间轮询的状态文案让位——否则用户看不到自己刚点的结果。
// 返回三个绑定到同一个 msgEl 的函数，调用方按需取用。
export function mkMsgArea(msgEl) {
  function msg(text, bad) {
    msgEl.textContent = text || '';
    msgEl.style.color = bad ? 'var(--danger,#ff5468)' : 'var(--muted)';
    msgEl.style.display = text ? '' : 'none';   // 空态不占位
  }
  function msgKeep(text, bad) {
    msgEl.dataset.keep = '1';
    msgEl.dataset.keepUntil = String(Date.now() + 6000);
    msg(text, bad);
  }
  function msgHeld() {
    const until = parseInt(msgEl.dataset.keepUntil || '0', 10) || 0;
    return msgEl.dataset.keep === '1' && Date.now() < until;
  }
  return { msg, msgKeep, msgHeld };
}
