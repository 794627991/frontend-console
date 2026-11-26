// ============================================================
// docview / core —— DocInstance：生命周期、顶栏、横幅、错误态、变更轮询
//
// 设计原则 P1（文档 5.2）：引擎不依赖任何一个宿主的状态对象。主界面标签页
// 与 harness 分屏都只是「一个容器」，本文件不认识 connections / conn / _sub，
// 宿主把容器交进来，实例自己管自己。
//
// 生命周期（6.2.9）：
//   建立 → parse+render（只有首屏被看见时才真的渲染）
//   切走 → display:none，实例保留，**变更轮询暂停**
//   切回 → 恢复轮询，容器尺寸变了就重新适宽
//   关闭 → destroy()：停轮询、断开 ResizeObserver、销毁渲染器、移除监听
//
// 文件变更（6.1.8）：revision = `大小:修改时间毫秒`；活动实例每 4 秒查一次，
// 页面不可见时跳过。变了出横幅，**不自动重载**（A09）。
// ============================================================

import { kindOfPath, parseLocator, formatLocator, KIND_IMAGE } from './anchor.js';
import { docxOutline, docxUnits, pdfOutline, pdfUnits, pptxOutline, pptxUnits,
         xlsxOutline, xlsxUnits, imageOutline } from './outline.js';
import { findTextRange, paintRanges, clearHighlight, scrollRangeIntoView } from './hl.js';
import { esc } from './esc.js';

const POLL_MS = 4000;
const MAX_BYTES = 100 * 1024 * 1024;   // 统一 100MiB（6.1.9）

/** 各渲染器注册表。加载顺序：docview/index.js 先 import 各渲染器再 import core。 */
const RENDERERS = {};

export function registerRenderer(kind, factory) {
  RENDERERS[kind] = factory;
}

/** 渲染器接口（6.1.1）：parse / render / goTo / highlight / find / viewState / destroy。 */
export async function mount(container, opts) {
  const path = String(opts.path || '');
  const kind = opts.kind || kindOfPath(path);
  if (!kind) throw new Error('不支持的文档类型：' + path);
  if (!RENDERERS[kind]) throw new Error('没有 ' + kind + ' 的渲染器');
  return new DocInstance(container, { ...opts, path, kind });
}

class DocInstance {
  constructor(container, opts) {
    this.container = container;
    this.path = opts.path;
    this.kind = opts.kind;
    this.host = opts.host || 'main';
    this.title = this.path.split(/[\\/]/).pop();
    this.info = { path: this.path, kind: this.kind, title: this.title,
                  bytes: 0, revision: '', units: [], outline: [] };
    this._listeners = {};
    this._destroyed = false;
    this._pollTimer = 0;
    this._pollWarm = 0;
    this._reloadingNow = false;
    this._ro = null;
    this._renderer = null;
    this._at = '';
    this._buildShell();
    this.ready = this._load(opts);
  }

  // ---------- 事件 ----------

  on(ev, cb) {
    (this._listeners[ev] || (this._listeners[ev] = [])).push(cb);
    return this;
  }

  _emit(ev, arg) {
    for (const cb of this._listeners[ev] || []) {
      try { cb(arg); } catch (e) { console.warn('[docview] 监听器抛错', ev, e); }
    }
  }

  // ---------- 骨架（6.2.7） ----------

  _buildShell() {
    const root = document.createElement('div');
    root.className = 'dv-root';
    root.innerHTML = `
      <div class="dv-bar">
        <span class="dv-name" title="${esc(this.path)}">${esc(this.title)}</span>
        <span class="dv-pos"></span>
        <span class="dv-spacer"></span>
        <span class="dv-find-wrap" hidden>
          <input class="dv-find" type="search" placeholder="查找" spellcheck="false">
          <span class="dv-find-n"></span>
          <button class="btn ghost dv-find-prev" title="上一个（Shift+Enter）">上</button>
          <button class="btn ghost dv-find-next" title="下一个（Enter）">下</button>
        </span>
        <button class="btn ghost dv-find-btn" title="面板内查找">查找</button>
        <button class="btn ghost dv-open-tab" title="在主界面标签页打开（唯一的编辑入口在那里）">在主界面打开</button>
      </div>
      <div class="dv-note" hidden><span class="dv-note-t"></span><span class="dv-note-x" title="关闭说明">✕</span></div>
      <div class="dv-body"><div class="dv-status">正在加载…</div></div>
    `;
    this.container.appendChild(root);
    this.root = root;
    this.bodyEl = root.querySelector('.dv-body');
    this.posEl = root.querySelector('.dv-pos');
    this.noteEl = root.querySelector('.dv-note');

    // 文件名点击复制路径（6.2.7）
    root.querySelector('.dv-name').onclick = () => {
      const t = this.path;
      try {
        navigator.clipboard.writeText(t).then(
          () => this._flashName('已复制路径'), () => {});
      } catch (_) {}
    };
    root.querySelector('.dv-open-tab').onclick = () => {
      if (typeof window.openOfficeFile === 'function') window.openOfficeFile(this.path);
    };
    root.querySelector('.dv-note-x').onclick = () => { this.noteEl.hidden = true; };

    // 查找框（200ms 防抖，回车循环，对照 4.2.11）
    const findBtn = root.querySelector('.dv-find-btn');
    const findWrap = root.querySelector('.dv-find-wrap');
    const findInput = root.querySelector('.dv-find');
    findBtn.onclick = () => {
      findWrap.hidden = !findWrap.hidden;
      if (!findWrap.hidden) { findInput.focus(); findInput.select(); }
    };
    let ft = 0;
    findInput.oninput = () => {
      clearTimeout(ft);
      ft = setTimeout(() => this.find(findInput.value, false), 200);
    };
    // 2026-11-26 用户实测：「查找作用？点了关键字，点查找，也不能跳转啊！
    // 没有跳转的相关 UI 啊」。原实现有滚动，但（a）没有上/下一次的按钮，
    // 用户不知道还能再点，（b）首次输入时 _findIdx 就自增到第 2 个，
    // 看起来像「没跳到第一个」。现在：输入 = 从第 1 处开始；Enter = 下一处；
    // Shift+Enter / 「上」= 上一处。
    findInput.onkeydown = (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.find(findInput.value, true, e.shiftKey ? -1 : +1);
      }
      if (e.key === 'Escape') { findWrap.hidden = true; this._findIdx = null; clearHighlight('dv-hit'); }
    };
    root.querySelector('.dv-find-next').onclick = () => this.find(findInput.value, true, +1);
    root.querySelector('.dv-find-prev').onclick = () => this.find(findInput.value, true, -1);
    this._findInput = findInput;
    this._findN = root.querySelector('.dv-find-n');

    // 内容区滚动 → 更新位置提示（6.2.7；docx 不显示）
    this._onScroll = () => { if (!this._scrollRaf) this._scrollRaf = requestAnimationFrame(() => {
      this._scrollRaf = 0;
      this._updatePos();
    }); };
    this.bodyEl.addEventListener('scroll', this._onScroll, { passive: true });

    // Ctrl + 滚轮缩放（2026-11-26 用户令：「正常 word、pdf 都应该有 ctrl+
    // 鼠标滚轮放大才对啊！」）。之前没有任何滚轮处理，浏览器默认的
    // ctrl+滚轮会缩放**整个应用界面**——而 Electron 里那个默认行为被禁用，
    // 所以表现成「完全没反应」。这里自己接：按文档区缩放，不动应用界面。
    this._onWheel = (e) => {
      if (!e.ctrlKey) return;              // 普通滚轮保持滚动
      if (!this._renderer || typeof this._renderer.zoom !== 'function') return;
      e.preventDefault();                  // 阻止浏览器整页缩放
      // deltaY < 0 = 向上滚 = 放大
      const step = e.deltaY < 0 ? +1 : -1;
      try {
        this._zoomPct = this._renderer.zoom(step);
      } catch (_) { return; }
      this._showZoomToast();
    };
    // passive: false —— 要 preventDefault 必须显式声明，否则浏览器忽略它
    this.bodyEl.addEventListener('wheel', this._onWheel, { passive: false });

    // 容器尺寸变化重新适宽（6.2.8，防抖 150ms）
    if (typeof ResizeObserver !== 'undefined') {
      let rt = 0;
      this._ro = new ResizeObserver(() => {
        clearTimeout(rt);
        rt = setTimeout(() => {
          if (this._destroyed) return;
          if (this._renderer && typeof this._renderer.resize === 'function') this._renderer.resize();
        }, 150);
      });
      this._ro.observe(this.container);
    }
    this._resizeTimer = 0;
  }

  _flashName(text) {
    const el = this.root.querySelector('.dv-name');
    if (!el) return;
    const old = this.title;
    el.textContent = text;
    setTimeout(() => { if (el.isConnected) el.textContent = old; }, 1200);
  }

  _status(html) {
    const el = this.bodyEl.querySelector('.dv-status');
    if (el) { if (html) { el.innerHTML = html; } else el.remove(); return el; }
    if (!html) return null;
    const d = document.createElement('div');
    d.className = 'dv-status';
    d.innerHTML = html;
    this.bodyEl.insertBefore(d, this.bodyEl.firstChild);
    return d;
  }

  // ---------- 加载 ----------

  async _load(opts) {
    try {
      const bytes = await this._fetchBytes();
      if (this._destroyed) return this;
      this.info.bytes = bytes.byteLength;
      this.buf = bytes;   // 渲染器按 inst.buf 取原始字节（docx/xlsx/pptx/image）
      this.info.revision = await this._revisionOf();

      const factory = RENDERERS[this.kind];
      const renderer = await factory(this, { bytes, opts: opts || {} });
      if (this._destroyed) { try { renderer.destroy(); } catch (_) {} return this; }
      this._renderer = renderer;

      // parse 产出大纲与 units
      if (typeof renderer.parse === 'function') {
        const parsed = await renderer.parse(bytes, this);
        if (parsed) {
          this.info.outline = parsed.outline || [];
          this.info.units = parsed.units || [];
          this.info.blocks = parsed.blocks || [];
        }
      }

      this._status('');
      if (typeof renderer.render === 'function') await renderer.render(this.bodyEl, this);
      if (this._destroyed) return this;

      this._startPoll();
      this._emit('ready', this);
      this._updatePos();
      return this;
    } catch (e) {
      if (this._destroyed) return this;
      const msg = (e && e.message) || String(e);
      this._status('<div class="office-err">' + esc(msg) + '</div>');
      this._emit('error', msg);
      throw e;
    }
  }

  async _fetchBytes() {
    const r = await fetch('/api/office/read?path=' + encodeURIComponent(this.path));
    if (!r.ok) throw new Error('文件读取失败（HTTP ' + r.status + '）');
    const buf = await r.arrayBuffer();
    if (buf.byteLength > MAX_BYTES) {
      throw new Error('文件超过 100MB（' + (buf.byteLength / 1048576).toFixed(0) + 'MB），请用资源管理器打开');
    }
    return buf;
  }

  /** revision = `大小:修改时间毫秒`（6.1.8）。
   *  **必须与后端 src/doc_store.revision_of 完全一致**——历史的坑：原来读
   *  /api/file_info 的 mtime（秒，浮点），前端算 `x*1000` 四舍五入得
   *  1748916100，后端 `int(round(x*1000))` 得 1748916099852，两串不等 →
   *  每次 search/read 都判缓存失效、重新等前端解析，工具侧 504 超时。
   *  现在统一走 /api/doc/stat，它给的就是后端算好的字符串。 */
  async _revisionOf() {
    try {
      const r = await fetch('/api/doc/stat?path=' + encodeURIComponent(this.path));
      const j = await r.json();
      if (j && j.ok && j.revision) return String(j.revision);
    } catch (_) {}
    return '';
  }

  // ---------- 文件变更：自动同步 ----------
  //
  // 2026-11-26 用户令（针对「文件已在磁盘上更改」横幅）：
  //   「如果必须要有，首先要正确，其次关闭能不能放在和忽略通行？或者直接
  //    去掉？反正 AI 改的，只要能同步就行了？不用让我知道吧？自动重新加载
  //    不就行了？」
  //
  // 结论：**去掉横幅，改成自动重载**。理由：
  //   · 这层预览是只读的，用户没有未保存的编辑会被这次重载破坏；
  //   · 变更只可能来自外部（AI 或别的程序），用户要的是「看到最新的」，
  //     不是「被问一句要不要看」；
  //   · 横幅本身还占掉一大块纵向空间，窄分屏里代价更大。
  //
  // 保留最小心的部分：**重载保留用户位置**（锚点）与滚动比例，否则正在
  // 读的文档被刷回顶端，比不刷新还糟。

  _startPoll() {
    this._stopPoll();
    // 两轮预热：刚加载完的那一次比对没有意义（基线还没稳住）
    this._pollWarm = 2;
    this._pollTimer = setInterval(() => this._pollOnce(), POLL_MS);
  }

  _stopPoll() {
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = 0; }
  }

  async _pollOnce() {
    if (this._destroyed || !this._pollTimer) return;
    if (this._reloadingNow) return;
    // 页面不可见时跳过（6.1.8）
    if (document.visibilityState === 'hidden') return;
    const rev = await this._revisionOf();
    if (this._destroyed || !rev) return;
    if (this._pollWarm > 0) {
      this._pollWarm -= 1;
      this.info.revision = rev;
      return;
    }
    if (rev === this.info.revision) return;
    // 图片变了也没什么可重载的
    if (this.kind === KIND_IMAGE) return;
    await this._autoReload(rev);
  }

  /** 文件在磁盘上变了：静默重载并尽量回到原来的位置。 */
  async _autoReload(newRev) {
    if (this._reloadingNow || this._destroyed) return;
    this._reloadingNow = true;
    // 记下当前位置：有锚点用锚点，否则用滚动比例（模态里都够用）
    const keepAt = this._at || '';
    const body = this.bodyEl;
    const ratio = body && body.scrollHeight > body.clientHeight
      ? body.scrollTop / (body.scrollHeight - body.clientHeight) : 0;
    try {
      await this.reload();
      if (this._destroyed) return;
      this.info.revision = newRev || await this._revisionOf();
      // 还原位置：优先锚点（精确），退回滚动比例（近似）
      let restored = false;
      if (keepAt) {
        try { restored = !!(this.locate(keepAt) || {}).found; } catch (_) {}
      }
      if (!restored && ratio > 0.001 && this.bodyEl) {
        const b = this.bodyEl;
        b.scrollTop = Math.round((b.scrollHeight - b.clientHeight) * ratio);
      }
    } catch (e) {
      // 重载失败不能把原来的文档弄没——错误态已由 _load 铺好
      if (window.console) console.warn('[docview] 自动重载失败', e);
    } finally {
      this._reloadingNow = false;
    }
  }

  // ---------- 对外接口 ----------

  /** 滚到锚点。锚点文本或 Locator 都接受。返回 { found, at }。 */
  locate(anchor) {
    if (!anchor) return { found: false, at: '' };
    const loc = typeof anchor === 'string' ? parseLocator(this.kind, anchor) : anchor;
    if (!loc) return { found: false, at: '' };
    const at = formatLocator(loc);
    this._at = at;
    let ok = false;
    if (this._renderer && typeof this._renderer.goTo === 'function') {
      try { ok = this._renderer.goTo(loc, this) !== false; } catch (e) {
        console.warn('[docview] goTo 失败', e); ok = false;
      }
    }
    this._updatePos();
    this._emit('location', { at, found: ok });
    return { found: ok, at };
  }

  /** 只判定锚点是否有对应元素，**不滚动、不高亮**。
   *  show_in_viewer 要逐个回报 found，不能拿 reveal 去试——那会互相覆盖高亮。 */
  probe(anchor) {
    const loc = typeof anchor === 'string' ? parseLocator(this.kind, anchor) : anchor;
    if (!loc) return false;
    if (this._renderer && typeof this._renderer.probe === 'function') {
      try { return !!this._renderer.probe(loc, this); } catch (_) { return false; }
    }
    // 没有 probe 实现的渲染器：用 revealTarget 拿元素但不涂
    if (this._renderer && typeof this._renderer.revealTarget === 'function') {
      try { return !!this._renderer.revealTarget(loc, '', this); } catch (_) { return false; }
    }
    return false;
  }

  /** show_in_viewer：滚到第一个目标，高亮全部，显示说明条。 */
  reveal(targets, note, seq) {
    const list = (targets || []).filter(t => t && t.anchor);
    if (!list.length) return { found: false, at: '' };
    // 同一 seq 用户关掉后不再弹（6.2.7）
    if (seq != null && this._dismissedSeq === seq) return { found: false, at: '' };

    const ranges = [];
    let firstAt = '', any = false;
    for (const t of list) {
      const loc = parseLocator(this.kind, t.anchor);
      if (!loc) continue;
      const at = formatLocator(loc);
      if (!firstAt) firstAt = at;
      if (this._renderer && typeof this._renderer.revealTarget === 'function') {
        const r = this._renderer.revealTarget(loc, t.quote, this);
        if (r) {
          if (r.range) ranges.push(r.range);
          if (r.el) { r.el.classList.add('dv-revealed'); any = true; }
          if (r.range) any = true;
        }
      }
    }
    if (ranges.length) {
      clearHighlight('dv-reveal');
      paintRanges(ranges, 'dv-reveal');
    }
    if (firstAt) this.locate(firstAt);
    if (note) {
      const t = this.noteEl.querySelector('.dv-note-t');
      t.textContent = String(note).slice(0, 500);
      this.noteEl.hidden = false;
      this._noteSeq = seq;
      this.noteEl.querySelector('.dv-note-x').onclick = () => {
        this.noteEl.hidden = true;
        if (seq != null) this._dismissedSeq = seq;
      };
    }
    this._updatePos();
    return { found: any, at: firstAt };
  }

  /** 面板内查找。返回 { found, count }（异步时是 Promise）。
   *  @param {boolean} step  是否在已有结果里前后移动（Enter / 上 / 下）
   *  @param {number}  dir   +1 下一处、-1 上一处（step 时生效）
   *  渲染器可以提供 `findAsync(quote)`——PDF 的文字层是懒建的，同步 findAll
   *  在页面还没渲染时必然返回空（用户实测：「点查找也不能跳转」），
   *  所以 PDF 用异步版：先按已缓存的页文本找出命中页、渲染该页、再取 Range。 */
  async find(quote, step, dir) {
    const q = String(quote || '').trim();
    if (!q) { clearHighlight('dv-hit'); if (this._findN) this._findN.textContent = ''; return { found: false, count: 0 }; }
    // 查询词变了 → 结果作废，必须重算（否则挪位置是在老结果上转圈）
    if (this._findQ !== q) { this._findIdx = null; }
    this._findQ = q;
    const token = (this._findToken = (this._findToken || 0) + 1);
    clearHighlight('dv-hit');
    let hits = [];
    const R = this._renderer;
    if (R && typeof R.findAsync === 'function') {
      try { hits = (await R.findAsync(q, this)) || []; } catch (_) { hits = []; }
      // 期间用户又改了关键字 → 这次结果作废
      if (this._destroyed || token !== this._findToken) return { found: false, count: 0 };
    } else if (R && typeof R.findAll === 'function') {
      try {
        const rs = R.findAll(q, this) || [];
        for (const r of rs) if (r) hits.push(r);
      } catch (_) {}
    }
    if (!hits.length) {
      // DOM 全量：按块逐个找（一次 findTextRange 只给第一处）
      const blocks = this.bodyEl.querySelectorAll('p, li, td, th, h1, h2, h3, h4, h5, h6, article, section');
      for (const b of blocks) {
        const r = findTextRange(b, q, true);
        if (r) hits.push(r);
      }
    }
    if (!hits.length) {
      if (this._findN) this._findN.textContent = '无匹配';
      this._findIdx = null;
      return { found: false, count: 0 };
    }
    paintRanges(hits, 'dv-hit');
    if (step && this._findIdx != null) {
      const n = hits.length;
      this._findIdx = ((this._findIdx + (dir || 1)) % n + n) % n;
    } else {
      this._findIdx = 0;
    }
    // **必须等一帧再滚**：高亮刚涂上、布局可能还没结算，直接量 rect 会拿到
    // 旧位置（尤其 docx 的 transform 缩放）。聚焦那一条用 dv-hit-cur 标出来，
    // 让用户一眼看出「当前跳到的是这一处」。
    const cur = hits[this._findIdx];
    this.bodyEl.querySelectorAll('.dv-hit-cur').forEach(el => el.classList.remove('dv-hit-cur'));
    requestAnimationFrame(() => {
      scrollRangeIntoView(cur, this.bodyEl);
      try {
        // 标记「当前这一处」：落点常是行内 span，描边套在它上面会碎成一条条。
        // 往上找到最近的块级容器再标，视觉上才是「这一整段被选中了」。
        let el = cur && cur.startContainer;
        if (el && el.nodeType !== 1) el = el.parentElement;
        while (el && el !== this.bodyEl &&
               !/^(P|LI|TD|TH|H[1-6]|ARTICLE|SECTION|DIV|TR)$/.test(el.tagName)) {
          el = el.parentElement;
        }
        if (el && el !== this.bodyEl) el.classList.add('dv-hit-cur');
      } catch (_) {}
    });
    if (this._findN) this._findN.textContent = (this._findIdx + 1) + '/' + hits.length;
    return { found: true, count: hits.length };
  }

  /** 当前视图状态（get_view / report_view 用）。 */
  viewState() {
    return { path: this.path, kind: this.kind, at: this._at,
             selection: { text: String(window.getSelection ? window.getSelection().toString() : '').slice(0, 4000) } };
  }

  async reload() {
    this._status('正在重新加载…');
    try {
      if (this._renderer && typeof this._renderer.destroy === 'function') {
        try { this._renderer.destroy(); } catch (_) {}
      }
      this._renderer = null;
      this.bodyEl.innerHTML = '';
      await this._load({});
    } catch (_) { /* 错误态已由 _load 铺好 */ }
  }

  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this._stopPoll();
    try { if (this._ro) this._ro.disconnect(); } catch (_) {}
    this._ro = null;
    try { this.bodyEl.removeEventListener('scroll', this._onScroll); } catch (_) {}
    try { if (this._renderer && typeof this._renderer.destroy === 'function') this._renderer.destroy(); } catch (_) {}
    this._renderer = null;
    clearHighlight('dv-reveal');
    clearHighlight('dv-hit');
    if (this.root && this.root.parentNode) this.root.parentNode.removeChild(this.root);
    this.root = null;
  }

  // ---------- 内部 ----------

  /** Ctrl+滚轮时短暂显示当前缩放百分比（没有按钮了，需要这一下反馈）。 */
  _showZoomToast() {
    if (!this.root) return;
    let t = this._zoomToast;
    if (!t) {
      t = document.createElement('div');
      t.className = 'dv-zoom-toast';
      // 挂到 root（position: relative 的 .dv-root）而不是 bodyEl——
      // bodyEl 是滚动容器，浮层会跟着内容滚走
      this.root.appendChild(t);
      this._zoomToast = t;
    }
    t.textContent = Math.round(this._zoomPct || 100) + '%';
    t.classList.add('on');
    clearTimeout(this._zoomToastT);
    this._zoomToastT = setTimeout(() => { if (t.isConnected) t.classList.remove('on'); }, 700);
  }

  // 2026-11-26 用户令：缩放按钮删掉（「- 100% + 完全没效果 不行直接删了」）。
  // 那个控件从来没接上——`_applyZoomUi` 靠 `renderer.zoom()` 判断是否显示，
  // 而 docx 渲染器没有 zoom 方法，于是按钮隐藏；加上 `[hidden]` 被
  // `display:flex` 盖掉（见 docview.css 的兜底），按钮一直显示但点了没反应。
  // 缩放的替代方案是 Ctrl+滚轮（见 _onWheel），对文档阅读更自然。

  _updatePos() {
    if (!this.posEl) return;
    // docx 不显示位置（6.2.7）
    if (this.kind === 'docx' || this.kind === KIND_IMAGE) { this.posEl.textContent = ''; return; }
    let txt = '';
    if (this._renderer && typeof this._renderer.position === 'function') {
      try { txt = this._renderer.position(this.bodyEl, this) || ''; } catch (_) {}
    }
    this.posEl.textContent = txt;
    this._emit('location', { at: this._at, text: txt });
  }
}
