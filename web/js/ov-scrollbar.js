// ============================================================
// a306：Office/PDF 自绘宽滚动条（用户令：只要终端同款宽条，细条不要存在）
// ------------------------------------------------------------
// 根因：WebView2 156 的 Fluent 滚动条绘制层无视 CSS 宽度——webkit 自定义条
// 之下原细条仍在（hover 显形）。终端 a237 的终局解法：scrollbar-width:none
// 彻底藏原生层（CDP 像素实测连 Fluent 层都能藏住）+ 自绘 14px 宽条。
// 本模块把同款自绘条挂到 office-body（word/单元格）与 ov-pdf-main（pdf）。
// 自绘条：右缘竖条 + 底缘横条，thumb 可拖、轨道点击翻页、悬停高亮、
// 滚动渐显（2s 无操作淡出，滚动立即显形——同终端语义）。
// ============================================================
(function () {
  const SB_W = 14, FADE_MS = 1800;

  function _ovSbMake() {
    const sb = document.createElement('div');
    sb.className = 'ov-sb';
    const th = document.createElement('div');
    th.className = 'ov-sb-th';
    sb.appendChild(th);
    return { sb, th };
  }

  function _ovSbInitV(host, key) {
    if (host[key]) return;
    const { sb, th } = _ovSbMake();
    sb.classList.add('ov-sb-v');
    host.appendChild(sb);
    const st = { sb, th, host, drag: false, hideT: 0, lastPaint: 0 };
    host[key] = st;

    const paint = () => {
      // rAF 合并（每帧最多一次）
      if (st.lastPaint) { requestAnimationFrame(st.lastPaint); return; }
      st.lastPaint = requestAnimationFrame(() => {
        st.lastPaint = 0;
        const sh = host.scrollHeight, ch = host.clientHeight;
        if (sh <= ch + 1) { sb.style.display = 'none'; return; }
        sb.style.display = '';
        const ratio = ch / sh;
        const h = Math.max(36, Math.round(ch * ratio));
        const top = (host.scrollTop / sh) * ch;
        th.style.height = h + 'px';
        th.style.transform = 'translateY(' + Math.max(0, Math.min(ch - h, top)) + 'px)';
      });
    };
    st.paint = paint;

    const show = () => {
      sb.classList.add('on');
      clearTimeout(st.hideT);
      st.hideT = setTimeout(() => sb.classList.remove('on'), FADE_MS);
    };
    st.show = show;

    host.addEventListener('scroll', () => { paint(); show(); }, { passive: true });

    // 拖拽 thumb
    th.addEventListener('mousedown', e => {
      e.preventDefault();
      st.drag = true;
      th.classList.add('drag');
      const startY = e.clientY, startTop = host.scrollTop;
      const move = ev => {
        const sh = host.scrollHeight, ch = host.clientHeight;
        const thH = th.getBoundingClientRect().height;
        const dy = ev.clientY - startY;
        host.scrollTop = startTop + dy * (sh / ch);
      };
      const up = () => {
        st.drag = false;
        th.classList.remove('drag');
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
    // 轨道点击翻页
    sb.addEventListener('mousedown', e => {
      if (e.target === th) return;
      const r = th.getBoundingClientRect();
      host.scrollTop += (e.clientY < r.top) ? -host.clientHeight : host.clientHeight;
    });
    paint();
  }

  function _ovSbInitH(host, key) {
    if (host[key]) return;
    const { sb, th } = _ovSbMake();
    sb.classList.add('ov-sb-h');
    host.appendChild(sb);
    const st = { sb, th, host, drag: false, hideT: 0, lastPaint: 0 };
    host[key] = st;

    const paint = () => {
      if (st.lastPaint) { requestAnimationFrame(st.lastPaint); return; }
      st.lastPaint = requestAnimationFrame(() => {
        st.lastPaint = 0;
        const sw = host.scrollWidth, cw = host.clientWidth;
        if (sw <= cw + 1) { sb.style.display = 'none'; return; }
        sb.style.display = '';
        const ratio = cw / sw;
        const w = Math.max(36, Math.round(cw * ratio));
        const left = (host.scrollLeft / sw) * cw;
        th.style.width = w + 'px';
        th.style.transform = 'translateX(' + Math.max(0, Math.min(cw - w, left)) + 'px)';
      });
    };
    st.paint = paint;
    const show = () => {
      sb.classList.add('on');
      clearTimeout(st.hideT);
      st.hideT = setTimeout(() => sb.classList.remove('on'), FADE_MS);
    };
    st.show = show;
    host.addEventListener('scroll', () => { paint(); show(); }, { passive: true });
    th.addEventListener('mousedown', e => {
      e.preventDefault();
      st.drag = true;
      th.classList.add('drag');
      const startX = e.clientX, startLeft = host.scrollLeft;
      const move = ev => {
        const sw = host.scrollWidth, cw = host.clientWidth;
        host.scrollLeft = startLeft + (ev.clientX - startX) * (sw / cw);
      };
      const up = () => {
        st.drag = false;
        th.classList.remove('drag');
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
    sb.addEventListener('mousedown', e => {
      if (e.target === th) return;
      const r = th.getBoundingClientRect();
      host.scrollLeft += (e.clientX < r.left) ? -host.clientWidth : host.clientWidth;
    });
    paint();
  }

  // 对外：给容器挂全套（竖+横）。幂等。
  window._ovSbMount = function (host) {
    if (!host || host._ovSbV) { // 已挂：重绘
      if (host && host._ovSbV) { host._ovSbV.paint(); host._ovSbH.paint(); }
      return;
    }
    _ovSbInitV(host, '_ovSbV');
    _ovSbInitH(host, '_ovSbH');
  };
})();
