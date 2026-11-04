// ============================================================
// a316：Office 通用自绘滚动条（直接移植终端 _termSbInit——用户实锤"终端条
// 都好好的"）。与 a306 失败版的关键差异：
//   ① 原生层用 scrollbar-width:none 全隐（终端同款——Fluent 覆盖层在 none
//      下不画，这是终端验证过的；a306 失败版当时 office-body 有 auto 残留）
//   ② 不搞渐隐显形类切换（a306 的 .on 显形链路在办公场景下各种不触发）
//     ——常驻显示，跟终端一致
//   ③ 定时器兜底重绘（终端同款 400ms），布局变化自动跟上
// 挂载：office docx 渲染完 / xlsx 打开时 window._ovSbMount(scroller)
// ============================================================
(function () {
  window._ovSbMount = function (scroller) {
    if (!scroller || scroller._ovSb) { // 幂等：已挂只重绘
      if (scroller && scroller._ovSb) scroller._ovSb.paint();
      return;
    }
    const sb = document.createElement('div');
    sb.className = 'hg-term-sb ov-term-sb';
    const th = document.createElement('div');
    th.className = 'hg-term-sb-th';
    sb.appendChild(th);
    scroller.appendChild(sb);   // 挂在 scroller 自身（fixed 样式见 CSS——不随内容滚走）
    const paint = () => {
      if (!scroller.isConnected) { clearInterval(st.timer); return; }
      const sh = scroller.scrollHeight, ch = scroller.clientHeight;
      if (sh <= ch + 4) { sb.style.display = 'none'; return; }
      sb.style.display = '';
      const trackH = sb.clientHeight;
      if (trackH <= 0) return;
      const thH = Math.max(36, Math.round(ch / sh * trackH));
      const maxTop = trackH - thH;
      th.style.height = thH + 'px';
      th.style.top = (maxTop > 0 ? scroller.scrollTop / (sh - ch) * maxTop : 0) + 'px';
    };
    const st = { el: sb, th, timer: 0, paint };
    scroller._ovSb = st;
    sb.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const trackH = sb.clientHeight, thH = th.offsetHeight;
      const maxTop = trackH - thH;
      if (e.target === th) {
        const startY = e.clientY, startScroll = scroller.scrollTop;
        const move = (ev) => {
          if (maxTop <= 0) return;
          scroller.scrollTop = startScroll +
            (ev.clientY - startY) / maxTop * (scroller.scrollHeight - scroller.clientHeight);
        };
        const up = () => {
          removeEventListener('mousemove', move);
          removeEventListener('mouseup', up);
        };
        addEventListener('mousemove', move);
        addEventListener('mouseup', up);
      } else {
        const y = e.clientY - sb.getBoundingClientRect().top;
        const cur = parseFloat(th.style.top) || 0;
        scroller.scrollTop += (y < cur ? -1 : 1) * scroller.clientHeight * 0.9;
      }
    });
    scroller.addEventListener('scroll', paint, { passive: true });
    st.timer = setInterval(paint, 400);
    paint();
  };
})();
