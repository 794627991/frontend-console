// ============================================================
// docview / linkify —— 聊天流里的文档路径识别与改写（文档 6.3.2）
//
// 规则表（6.3.2）：
//   形态                              识别
//   Markdown 链接 [文字](路径)          是（可带 #锚点）
//   行内代码里的路径                    是（支持反斜杠、空格）
//   裸路径 正斜杠 含目录分隔符/./开头     是
//   裸路径 反斜杠 盘符开头               是（**ZCode 不认，我方必须认**）
//   UNC \\服务器\共享\…                仅行内代码或引号里
//   带空格的路径                        仅行内代码或引号里
//   裸文件名，不带目录                   否（误报太多）
//   代码块里的路径                      否
//   已有的 <a href>                     不动
//
// 后缀：行号 :12 / :12:5 剥掉；锚点 #p:12 / #slide:3 保留当定位参数。
// 扩展名判断**先剥 # 后缀再比**（ZCode 拿整串比，带锚点的链接不生成卡片）。
//
// 防注入（6.3.3）：路径只经 data-doc-open 传（encodeURIComponent），元素一律
// 用 createElement + textContent 组装，不拼 HTML 字符串——注入面为零。
// 只接受白名单扩展名。
// ============================================================

const EXT = 'docx|doc|pdf|xlsx|xls|csv|pptx|ppt|png|jpe?g|gif|webp|bmp|ico|svg';
const EXT_RE = new RegExp('\\.(?:' + EXT + ')$', 'i');

/**
 * 裸路径正则。只认：
 *   盘符开头（D:\... / D:/...）
 *   或含目录分隔符（a/b.docx、./x.pdf、../y.pptx）
 * 不认裸文件名。
 */
// 允许的字符：非空白、非这些「明显不属于路径」的标点。中文、括号、空格不在
// 裸路径里出现（空格路径只认行内代码/引号形态）。
// 锚点段 `#p:12` 必须整体吃进匹配（否则链接文本会停在 # 前面、锚点被拆到外面）。
const BARE_RE = new RegExp(
  '(?:[A-Za-z]:[\\\\/]|\\.{0,2}[\\\\/])' +                       // 起点：盘符 或 / ./ ../ .\ ..\
  '[^\\s<>"\'`|?*]+?\\.(?:' + EXT + ')' +                         // 主体 + 扩展名
  '(?:#[-\\w:.!]+)?' +                                            // 可选锚点（整体归入）
  '(?=[\\s,，。；;、)）\\]】"\'`]|$)',                              // 右边界
  'gi');

/** 行号后缀：:12 或 :12:5（剥掉）。 */
function stripLineNo(s) {
  return String(s).replace(/:\d+(?::\d+)?$/, '');
}

/**
 * 判断一段文本是不是一个完整的、该被链接化的文档路径。
 * 用于行内代码与 Markdown 链接（这两处允许空格与 UNC）。
 * @returns {{path, at, ok}}
 */
export function asDocPath(text) {
  let s = String(text == null ? '' : text).trim();
  if (!s) return { path: '', at: '', ok: false };
  // 去掉包裹的引号
  s = s.replace(/^["'`](.*)["'`]$/, '$1').trim();
  if (!s) return { path: '', at: '', ok: false };
  // **带协议的绝不当本地路径**（6.3.2「已有的 <a href> 不动」）：
  // https://example.com/x.docx 的扩展名也命中白名单，不排掉就会把网页链接
  // 改成本地文档链接、还把 href 删了（实测踩到）。
  if (/^[a-z][a-z0-9+.-]*:/i.test(s) && !/^[a-z]:[\\/]/i.test(s)) {
    return { path: '', at: '', ok: false };
  }
  // 只接受白名单扩展名（先剥 # 后缀再比，6.3.2）
  const hashAt = s.indexOf('#');
  const bare = hashAt < 0 ? s : s.slice(0, hashAt);
  const at = hashAt < 0 ? '' : s.slice(hashAt + 1);
  const stripped = stripLineNo(bare);
  if (!EXT_RE.test(stripped)) return { path: '', at: '', ok: false };
  // 裸文件名（不含任何目录分隔符）不接受
  if (!/[\\/]/.test(stripped)) return { path: '', at: '', ok: false };
  return { path: stripped, at, ok: true };
}

/**
 * 在纯文本里找裸路径。返回 [{ index, length, path, at }]。
 * 供文本节点切片用。
 */
export function findBarePaths(text) {
  const s = String(text || '');
  const out = [];
  BARE_RE.lastIndex = 0;
  let m;
  while ((m = BARE_RE.exec(s)) !== null) {
    const raw = m[0];
    const idx = m.index;
    // 再校验一次（正则宽松，可能吃到句尾标点）
    const hashAt = raw.indexOf('#');
    const bare = stripLineNo(hashAt < 0 ? raw : raw.slice(0, hashAt));
    const at = hashAt < 0 ? '' : raw.slice(hashAt + 1);
    if (!EXT_RE.test(bare)) continue;
    if (!/[\\/]/.test(bare)) continue;
    out.push({ index: idx, length: raw.length, path: bare, at });
  }
  return out;
}

/**
 * 把一段 HTML 字符串里的文档路径改写成可点链接。
 * @param {string} html 已经过 markdown-it 渲染的 HTML
 * @returns {string}
 */
export function linkifyHtml(html) {
  if (!html || typeof html !== 'string') return html || '';
  let doc;
  try {
    doc = new DOMParser().parseFromString('<div id="dv-root">' + html + '</div>', 'text/html');
  } catch (_) { return html; }
  const root = doc.getElementById('dv-root');
  if (!root) return html;
  linkifyNode(root);
  return root.innerHTML;
}

/**
 * 就地改写一个**已在页面里**的 DOM 子树（不重新序列化，保住已绑的事件）。
 * ask-md 的 renderMd 用这个——先拿到容器再就地改，避免 innerHTML 往返。
 */
export function linkifyNode(root) {
  if (!root || !root.querySelectorAll) return root;
  const doc = root.ownerDocument || document;

  // ① 已有 <a href> 的：命中可点路径的改写（去掉原点击行为）
  root.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href') || '';
    const r = asDocPath(href);
    if (!r.ok) return;   // http(s) / 其它协议 / javascript: 一律不动
    a.setAttribute('data-doc-open', encodeURIComponent(r.path));
    if (r.at) a.setAttribute('data-doc-at', encodeURIComponent(r.at));
    a.classList.add('hg-doclink');
    // **删掉 href、改用 role=link + tabindex**。
    // 保留 href="#" 曾让合成 click 走「默认动作」路径而跳过监听器（实测：
    // dispatchEvent 连元素自身的 click 监听都不触发、defaultPrevented 却为
    // true）。删掉 href 后它是普通元素，事件正常冒泡；键盘可达性靠 tabindex
    // 与 role 补回来。
    a.removeAttribute('href');
    a.setAttribute('role', 'link');
    if (!a.hasAttribute('tabindex')) a.setAttribute('tabindex', '0');
  });

  // ② 文本节点：切裸路径。跳过 <a>、<pre>、<code>
  // 用 DOM 操作组装（不用 innerHTML 拼）——节点内容本来就是纯文本，再走一遍
  // HTML 字符串既多余又会二次转义（& 变成 &amp;amp;）
  const walk = (node) => {
    const kids = [...node.childNodes];
    for (const n of kids) {
      if (n.nodeType === 3) {
        const hits = findBarePaths(n.nodeValue);
        if (!hits.length) continue;
        const frag = doc.createDocumentFragment();
        let last = 0;
        for (const h of hits) {
          if (h.index > last) frag.appendChild(doc.createTextNode(n.nodeValue.slice(last, h.index)));
          const a = doc.createElement('a');
          a.className = 'hg-doclink';
          // 不设 href（见上：href="#" 会让合成 click 跳过监听器）；
          // role/tabindex 补键盘可达性
          a.setAttribute('role', 'link');
          a.setAttribute('tabindex', '0');
          a.setAttribute('data-doc-open', encodeURIComponent(h.path));
          if (h.at) a.setAttribute('data-doc-at', encodeURIComponent(h.at));
          a.textContent = n.nodeValue.slice(h.index, h.index + h.length);
          frag.appendChild(a);
          last = h.index + h.length;
        }
        if (last < n.nodeValue.length) frag.appendChild(doc.createTextNode(n.nodeValue.slice(last)));
        n.parentNode.replaceChild(frag, n);
      } else if (n.nodeType === 1) {
        const tag = n.tagName;
        if (tag === 'A' || tag === 'PRE' || tag === 'CODE' || tag === 'SCRIPT' || tag === 'STYLE') continue;
        walk(n);
      }
    }
  };
  walk(root);

  // ③ 行内代码：整个文本就是一个路径的，包起来（上一步跳过了 CODE）
  root.querySelectorAll('code').forEach((c) => {
    // 只处理不在 <pre> 里的行内代码
    if (c.closest('pre')) return;
    if (c.querySelector('.hg-doclink')) return;
    const r = asDocPath(c.textContent || '');
    if (!r.ok) return;
    const a = doc.createElement('a');
    a.className = 'hg-doclink';
    a.setAttribute('data-doc-open', encodeURIComponent(r.path));
    if (r.at) a.setAttribute('data-doc-at', encodeURIComponent(r.at));
    a.textContent = c.textContent;
    c.textContent = '';
    c.appendChild(a);
  });

  return root;
}
