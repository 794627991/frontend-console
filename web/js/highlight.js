const KW_RULES = [
  { cls: 'kw-error', re: /\b(error|fail|failed|failure|panic|oops|fatal|denied|refused|abort|crash|segfault|oom|killed|segmentation fault|no such file or directory|permission denied|operation not permitted|unable to handle|kernel panic|out of memory|oom-kill|oom killer|call trace|stack trace|core dump|bus error|page fault|null pointer|general protection fault|illegal instruction|division by zero|hung task|soft lockup|hard lockup)\b/gi },
  { cls: 'kw-warning', re: /\b(warn|warning|deprecated|timeout|retry|overflow|underrun|stall|hung|blocked|deadlock|leak|leaked|corrupt|corrupted|incomplete|missing|not found|not supported|invalid|broken|exhausted|degraded|overrun|underflow|bad blocks|read-only|filesystem corruption)\b/gi },
  { cls: 'kw-info', re: /\b(info|notice|starting|started|stopped|detected|found|loaded|ready|init|initializing|mounting|mounted|deactivated|booting|probe|probed|register|registered|enabled|disabled|linux version|systemd|udev|freeing|freed|allocated|setting up|configured|bringing up|link is up|link is down)\b/gi },
  { cls: 'kw-success', re: /\b(success|succeed|succeeded|ok|done|complete|completed|passed|ready)\b/gi },
];
const KW_COLOR = {
  'kw-error':'#ff4060', 'kw-warning':'#ff9d00', 'kw-info':'#00d4ff', 'kw-success':'#00ff9d',
};
// 节流：批量扫描新行，避免每个 chunk 都扫全缓冲
function scheduleKwHighlight(conn) {
  if (conn._kwTimer) return;
  conn._kwTimer = setTimeout(() => {
    conn._kwTimer = null;
    highlightNewKw(conn);
  }, 250);
}
function highlightNewKw(conn) {
  if (!conn.term || !conn.term.registerDecoration) return;
  const buf = conn.term.buffer.active;
  const totalRows = buf.length;
  // 增量扫描窗口：只扫自上次以来的新行 + 回溯 1 行防跨行漏扫。
  // 单次写入超大（如 loadBuffer 500 行）时窗口同样生效——首次从 0 开始全量属正常。
  const fromRow = Math.max(0, (conn.kwDecorLastRow || 0) - 1);
  for (let r = fromRow; r < totalRows; r++) {
    const line = buf.getLine(r);
    if (!line) continue;
    const text = line.translateToString(true);
    if (!text.trim()) continue;
    // 命令行高亮（# 后命令名）已放弃：ANSI 注入法会在逐字符 echo 流上重复输出（# ls# ls），
    // decoration foregroundColor 在 WebGL renderer 下不渲染。此处只做关键词（error/warning）高亮。
    const rules = KW_RULES;
    for (const rule of rules) {
      rule.re.lastIndex = 0;
      let m;
      while ((m = rule.re.exec(text)) !== null) {
        // kw-cmd 用捕获组 2 定位命令名本身，其余用整个匹配
        const grp = rule.grp || 0;
        const start = m.index + (m[grp] ? text.slice(m.index).indexOf(m[grp]) : 0);
        const matched = m[grp] || m[0];
        const end = start + matched.length;
        try {
          // registerMarker(e) 内部: ybase + y + e = 目标行 → e = r - ybase - y（相对偏移，非绝对行号）
          const offset = Math.round(r - buf.ybase - buf.y);
          const dec = conn.term.registerDecoration({
            marker: conn.term.registerMarker(offset),
            x: start,
            width: end - start,
            foregroundColor: KW_COLOR[rule.cls],
            layer: 'top',
          });
          if (dec) conn.kwDecorations.push(dec);
        } catch(e) {}
        if (m.index === rule.re.lastIndex) rule.re.lastIndex++;
      }
    }
  }
  conn.kwDecorLastRow = totalRows;
  // decoration 数量硬上限：每个 decoration 是一个 DOM overlay，超量是渲染卡顿重灾区。
  // 3000 折中：错误密集日志（几百行全是 error/warning）不丢高亮，又不至于拖垮渲染。
  // 超限丢最旧的（滚动出视野的早已无用）
  if (conn.kwDecorations.length > 3000) {
    const drop = conn.kwDecorations.splice(0, conn.kwDecorations.length - 3000);
    drop.forEach(d => { try { d.dispose(); } catch(e){} });
  }
}

// ============================================================
// 历史分页（xterm 滚动到底即实时流；向上翻历史用后端分页 API）
// ============================================================
