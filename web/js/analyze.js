const ANALYZE_RE = {
  error:   /\b(error|fail|panic|fatal|denied|refused|abort|crash|oom|killed|segmentation fault|kernel panic|out of memory|call trace|page fault)\b/i,
  warning: /\b(warn|warning|deprecated|timeout|retry|overflow|hung|deadlock|corrupt|not found|not supported|invalid)\b/i,
  info:    /\b(info|notice|starting|started|stopped|detected|ready|linux version|systemd|mounting|booting|link is up|link is down)\b/i,
  success: /\b(success|succeed|succeeded|ok|done|complete|completed|passed)\b/i,
};
const ANALYZE_LABEL = { error: 'ERROR', warning: 'WARNING', info: 'INFO', success: 'SUCCESS' };

// 点击条目 → 跳到主终端对应行并高亮
// searchText 优先：在当前 buffer 重新搜索定位，避免行号因 reflow/resize 漂移导致跳错
function jumpToLine(rowIdx, searchText) {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.term) return;
  try {
    const buf = conn.term.buffer.active;
    let target = rowIdx;
    // 用文本重搜：行号可能因 reflow/resize/新数据流入而漂移，按内容定位最可靠
    if (searchText) {
      const needle = searchText.trim();
      const pref = needle.slice(0, Math.min(40, needle.length));
      // 从 rowIdx 起向上找最近的匹配行（漂移通常是小幅度，原行就在附近）
      // 若向上没找到，再从 rowIdx 向下找
      let found = -1;
      const match = (t) => t === needle || (t && pref && t.startsWith(pref));
      for (let r = Math.min(rowIdx, buf.length - 1); r >= 0; r--) {
        const ln = buf.getLine(r);
        if (!ln) continue;
        if (match(ln.translateToString(true).trim())) { found = r; break; }
      }
      if (found < 0) {
        for (let r = rowIdx + 1; r < buf.length; r++) {
          const ln = buf.getLine(r);
          if (!ln) continue;
          if (match(ln.translateToString(true).trim())) { found = r; break; }
        }
      }
      if (found >= 0) target = found;
    }
    // 边界保护
    target = Math.max(0, Math.min(target, buf.length - 1));
    // scrollToLine 把目标行滚到视图顶部
    conn.term.scrollToLine(target);
    conn.term.focus();
    // select 选中整行（蓝底高亮，xterm 内置最稳定）
    conn.term.select(0, target, conn.term.cols);
    // registerDecoration 加醒目背景（6 位 hex，不带 alpha）
    if (conn.term.registerDecoration) {
      const offset = Math.round(target - buf.ybase - buf.y);
      const dec = conn.term.registerDecoration({
        marker: conn.term.registerMarker(offset),
        x: 0,
        width: conn.term.cols,
        backgroundColor: '#00d4ff',
        layer: 'top',
      });
      if (dec) setTimeout(() => { try { dec.dispose(); } catch(e){} }, 2500);
    }
  } catch(e) {}
}

// 点击统计卡片 → 在下方列表显示该类别最近条目
function showAnalyzeList(kw) {
  if (!activePortId) return;
  const conn = connections[activePortId];
  if (!conn || !conn.term) return;
  const re = ANALYZE_RE[kw];
  if (!re) return;
  const buf = conn.term.buffer.active;
  const items = [];
  for (let r = 0; r < buf.length; r++) {
    const ln = buf.getLine(r);
    if (!ln) continue;
    const t = ln.translateToString(true);
    if (re.test(t)) items.push({ row: r, text: t.trim().slice(0, 100) });
  }
  $('analyzeListTitle').textContent = `最近 ${ANALYZE_LABEL[kw]}（${items.length} 条）`;
  const cl = $('clusterList');
  if (!items.length) {
    cl.innerHTML = `<div class="cmd-empty">无 ${ANALYZE_LABEL[kw]} 条目</div>`;
    return;
  }
  // 最近的在前（取最后 30 条倒序）
  const recent = items.slice(-30).reverse();
  cl.innerHTML = recent.map((it, i) =>
    `<div class="cluster-item" data-idx="${i}" title="${esc(it.text)}">${esc(it.text)}</div>`
  ).join('');
  // 点击条目 → 跳到对应行并选中高亮
  cl.querySelectorAll('.cluster-item').forEach((el, i) => {
    el.onclick = () => jumpToLine(recent[i].row, recent[i].text);
  });
}

function renderAnalyze() {
  if (!activePortId) { $('statCards').innerHTML = '<div class="cmd-empty">无活动连接</div>'; return; }
  const conn = connections[activePortId];
  if (!conn || !conn.term) return;
  // 统计已加载行（从 xterm buffer 读取）
  const buf = conn.term.buffer.active;
  // a243（复审 F1/F2/F3）：回退 a237 的增量计数——终端缓冲的三种变异使
  // 「length 锚」不可靠：a) 清屏/reset 使 length 塌缩（锚越界→计数冻结陈旧）；
  // b) CR/EL/ED2 原地重写不改变 length（复用分支冻结计数）；c) vim/htop 的
  // alt-screen 往返（锚跨缓冲共享→双倍计数）。正确性优先（用户铁律），
  // 恢复每轮全量扫描；性能代价=分析面板打开时 5s 一次（面板关闭零成本，
  // init.js 门控不变）
  const counts = {error:0, warning:0, info:0, success:0};
  for (let r = 0; r < buf.length; r++) {
    const ln = buf.getLine(r);
    if (!ln) continue;
    const t = ln.translateToString(true);
    const low = t.toLowerCase();
    if (ANALYZE_RE.error.test(low)) counts.error++;
    if (ANALYZE_RE.warning.test(low)) counts.warning++;
    if (ANALYZE_RE.info.test(low)) counts.info++;
    if (ANALYZE_RE.success.test(low)) counts.success++;
  }
  _renderAnaCards(counts);
}
function _renderAnaCards(c) {
  $('statCards').innerHTML = `
    <div class="stat-card err" data-kw="error" style="cursor:pointer" title="点击查看最近 ERROR 条目">
      <div class="label">ERROR</div><div class="value">${c.error}</div></div>
    <div class="stat-card warn" data-kw="warning" style="cursor:pointer" title="点击查看最近 WARNING 条目">
      <div class="label">WARNING</div><div class="value">${c.warning}</div></div>
    <div class="stat-card info" data-kw="info" style="cursor:pointer" title="点击查看最近 INFO 条目">
      <div class="label">INFO</div><div class="value">${c.info}</div></div>
    <div class="stat-card ok" data-kw="success" style="cursor:pointer" title="点击查看最近 SUCCESS 条目">
      <div class="label">SUCCESS</div><div class="value">${c.success}</div></div>
  `;
  // 点击统计卡片 → 下方列表显示该类别最近条目（不弹 banner）
  $('statCards').querySelectorAll('.stat-card').forEach(card => {
    card.onclick = () => showAnalyzeList(card.dataset.kw);
  });
}

// ---- 命令标签 ----
// 命令库：后端持久化（数据目录/cmdlib.json），跨端口/重启保留
// 内存缓存避免每次渲染都异步拉取

// 模块化一期：转 ES module——跨文件/Python 裸引用消费名挂 window。
// 清单由 eslint no-undef 神谕反推（零启发式）：本文件转模块后，其余
// 文件/Python 推送的裸标识符引用全部经 window 解析。
window.renderAnalyze = renderAnalyze;
