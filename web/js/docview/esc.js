// docview/esc —— HTML 转义。window.esc 是 harness 里定义的传统 script 全局，
// 在 module 里不能直接依赖它（加载顺序不保证），这里自带一份。
export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
