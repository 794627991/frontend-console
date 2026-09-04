async function loadBuffer(portId, conn) {
  if (conn.loadingHistory) return;
  conn.loadingHistory = true;
  try {
    const r = await fetch('/api/buffer?port_id=' + encodeURIComponent(portId) + '&n=500');
    const j = await r.json();
    // await 期间连接可能已关闭，term 已 dispose，校验后再写
    if (connections[portId] !== conn || !conn.term) return;
    const lines = j.lines || [];
    if (lines.length) {
      // 历史行是"逻辑行"（后端已按 \n 切分、\r 覆盖处理过），用 \r\n 写入 xterm
      const text = lines.map(l => l.text || '').join('\r\n');
      if (text) conn.term.write(text + '\r\n');
      conn.oldestSeq = lines[0].seq;
      conn.hasMore = j.has_more !== false;
    } else {
      conn.hasMore = false;
    }
    conn.kwDecorLastRow = 0;
    scheduleKwHighlight(conn);
    if (conn.autoScroll) conn.term.scrollToBottom();
    // flush 历史加载期间缓冲的实时数据
    if (conn.pendingRaw) {
      const pend = conn.pendingRaw; conn.pendingRaw = '';
      conn.term.write(pend);
      scheduleKwHighlight(conn);
      if (conn.autoScroll) conn.term.scrollToBottom();
    }
  } catch(e) {} finally {
    conn.loadingHistory = false;
  }
}

// 向上加载更早历史：xterm 不支持顶部插入，用 reset 重写（旧行+当前行）
async function loadOlder(portId, conn) {
  if (conn.loadingMore || !conn.hasMore || conn.oldestSeq == null || conn.loadingHistory) return;
  conn.loadingMore = true;
  try {
    const r = await fetch('/api/buffer?port_id=' + encodeURIComponent(portId) + '&n=500&before_seq=' + conn.oldestSeq);
    const j = await r.json();
    const lines = j.lines || [];
    if (lines.length) {
      const older = lines.map(l => l.text || '').join('\r\n');
      const curBuf = conn.term.buffer.active;
      const curLines = [];
      for (let r = 0; r < curBuf.length; r++) {
        const ln = curBuf.getLine(r);
        if (ln) curLines.push(ln.translateToString(true));
      }
      // 记住重写前用户视口顶行对应的行号，重写后恢复到同一逻辑行
      const vp = conn.xtermWrap.querySelector('.xterm-viewport');
      let topRowBefore = 0;
      try {
        const cellH = conn.term._core._renderService.dimensions.css.cell.height || 17;
        topRowBefore = conn.term.buffer.active.baseY + Math.round(vp.scrollTop / cellH);
      } catch(e) {}
      const allText = older + '\r\n' + curLines.join('\r\n');
      conn.term.reset();
      conn.term.write(allText);
      conn.kwDecorLastRow = 0;
      conn.kwDecorations.forEach(d => { try { d.dispose(); } catch(e){} });
      conn.kwDecorations = [];
      conn.oldestSeq = lines[0].seq;
      conn.hasMore = j.has_more !== false;
      scheduleKwHighlight(conn);
      // 恢复滚动位置：旧行插入后，原视口顶行下移了 lines.length 行
      try { conn.term.scrollToLine(topRowBefore + lines.length); } catch(e) {}
    } else {
      conn.hasMore = false;
    }
  } catch(e) {} finally {
    conn.loadingMore = false;
  }
}

// 跳到底部
function jumpToBottom(portId) {
  const conn = connections[portId];
  if (!conn || !conn.term) return;
  conn.autoScroll = true;
  conn.term.scrollToBottom();
  try { conn.term.focus(); } catch(e){}
}

// ============================================================
// 连接管理
// ============================================================
