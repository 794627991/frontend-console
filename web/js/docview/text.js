// ============================================================
// docview / text —— 文本归一化与 UTF-16 安全截断
//
// 译自 ZCode 的 OR/src/domain/text.ts（文档 5.4 的清单）。三个使用场景：
//   1. 段落文本对齐（docx 的 p:N 靠文本前缀匹配到渲染元素，见 4.2.1）
//   2. read_document 的回传截断（后端按字节预算切，前端这里按 UTF-16 安全切）
//   3. 查找与高亮：两边必须用同一套归一化，否则中文全角空格/兼容字符对不上
//
// **代理对（surrogate pair）是硬性要求**：emoji 与部分生僻汉字在两个 UTF-16
// 码元里，截断切在中间会产出孤立代理项——JSON.stringify 出来是 \udXXX，
// Python json.loads 接受但它不是合法 Unicode 标量值，回传前端再渲染就是乱码
// （AC-3.12 专门验这一条）。
// ============================================================

/** 归一化：把所有空白（含换行）压成单个空格、去首尾。查找与对齐都用它。 */
export function normalize(s) {
  return String(s == null ? '' : s)
    .replace(/[\s 　]+/g, ' ')   // \s 已含 \r\n\t；另补不换行空格与全角空格
    .trim();
}

/** 只压空白的版本：保留换行（表格单元格文本靠换行拼接，见 4.2.1 的 t:N）。 */
export function normalizeKeepLines(s) {
  return String(s == null ? '' : s)
    .replace(/\r\n?/g, '\n')
    .replace(/[ 　\t]/g, ' ')
    .split('\n').map(l => l.replace(/ {2,}/g, ' ').trim()).join('\n')
    .trim();
}

/** 归一化后转小写——对齐时用，中文不受影响，英文标题大小写不该挡匹配。 */
export function foldText(s) {
  return normalize(s).toLowerCase();
}

/**
 * UTF-16 安全截断：不切开代理对。
 * @param {string} s
 * @param {number} n 最多保留多少个 UTF-16 码元
 */
export function truncate(s, n) {
  const t = String(s == null ? '' : s);
  const lim = Math.max(0, n | 0);
  if (t.length <= lim) return t;
  let cut = lim;
  // 切点前一个是高位代理（0xD800-0xDBFF）= 切在代理对中间，退一格
  const code = t.charCodeAt(cut - 1);
  if (code >= 0xd800 && code <= 0xdbff) cut -= 1;
  return t.slice(0, cut);
}

/** 按码点计数（给需要「字符数」而不是「码元数」的界面用）。 */
export function codePointLength(s) {
  let n = 0;
  const t = String(s == null ? '' : s);
  for (let i = 0; i < t.length; i += 1) {
    const c = t.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < t.length) {
      const d = t.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) i += 1;
    }
    n += 1;
  }
  return n;
}
