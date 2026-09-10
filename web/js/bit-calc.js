// ============================================================
// 程序员计算器（仿 Marvell Register Analyzer + 计算器合体）
// - 位宽 8/16/32/64 可选，BigInt 精确计算（64 位也零溢出）
// - 逐位格：点击翻转 0/1，按字节分 8 组着色（分域辨识）
// - 整值输入：Hex/Dec/Oct 三进制，实时联动位格
// - 位运算：AND OR XOR NOT << >>（带位数）字节序 Swap Clear
// - 表达式计算器：支持 0x 前缀 hex、二进制 0b、按位运算符、加减乘除
//   括号优先级（递归下降解析，纯前端零依赖——流畅守则：闲置零开销）
// ============================================================

// ---- 表达式解析（递归下降）：+ - * / % () & | ^ << >> ~ 一元 -
// 字面量支持 0x 0X(hex) 0b 0B(bin) 0o 0O(oct) 与纯 dec
function _bcEvalExpr(src, bits) {
  const MASK = (1n << BigInt(bits)) - 1n;
  let i = 0;
  const s = src.replace(/\s+/g, '');
  if (!s) throw new Error('空表达式');
  const peek = () => s[i];
  function parsePrimary() {
    if (peek() === '(') { i++; const v = parseAdd(); if (peek() !== ')') throw new Error('括号不匹配'); i++; return v; }
    if (peek() === '~') { i++; return ~parsePrimary() & MASK; }
    if (peek() === '-' && (i + 1 < s.length)) { i++; return (-parsePrimary()) & MASK; }
    const m = /^0[xX][0-9a-fA-F]+|^0[bB][01]+|^0[oO][0-7]+|^[0-9]+/.exec(s.slice(i));
    if (!m) throw new Error('无法识别: ' + (s.slice(i, i + 8) || '(结尾)'));
    i += m[0].length;
    return BigInt(m[0]) & MASK;
  }
  // 优先级（低→高）：+ - → * / % → | → ^ → & → << >> → 一元/字面量
  // （C 语言同款：移位低于加减？不——C 里移位介于加减与比较之间、高于位与。
  //  这里定：加减最低，乘除次之，位或/异或/与再高，移位最高（程序员直觉：
  //  1<<3+1 想要 (1<<3)+1 就加括号，默认 1<<(3+1) 不符合 C 但符合 Marvell 工具习惯）
  function parseShift() {
    let v = parsePrimary();
    while (s[i] === '<' && s[i+1] === '<') { i += 2; const n = parsePrimary(); v = (v << n) & MASK; }
    while (s[i] === '>' && s[i+1] === '>') { i += 2; const n = parsePrimary(); v = v >> n; }
    return v;
  }
  function parseAnd() { let v = parseShift(); while (peek() === '&') { i++; v &= parseShift(); } return v; }
  function parseXor() { let v = parseAnd(); while (peek() === '^') { i++; v ^= parseAnd(); } return v; }
  function parseOr() { let v = parseXor(); while (peek() === '|') { i++; v |= parseXor(); } return v; }
  function parseMul() {
    let v = parseOr();
    while (peek() === '*' || peek() === '/' || peek() === '%') {
      const op = s[i++];
      const r = parseOr();
      if ((op === '/' || op === '%') && r === 0n) throw new Error('除零');
      v = op === '*' ? (v * r) & MASK : op === '/' ? v / r : v % r;
    }
    return v;
  }
  function parseAdd() {
    let v = parseMul();
    while (peek() === '+' || peek() === '-') {
      const op = s[i++];
      const r = parseMul();
      v = op === '+' ? (v + r) & MASK : (v - r) & MASK;
    }
    return v;
  }
  const v = parseAdd();
  if (i < s.length) throw new Error('多余字符: ' + s.slice(i, i + 8));
  return v;
}

// 单数字面量解析：0x/0b/0o 前缀或纯十进制 → BigInt（操作数框用）
function _bcParseNum(t) {
  t = String(t).trim().toLowerCase();
  if (/^0x[0-9a-f]+$/.test(t) || /^0b[01]+$/.test(t) || /^0o[0-7]+$/.test(t) || /^-?[0-9]+$/.test(t))
    return BigInt(t);
  throw new Error(t || '(空)');
}

// ---- 浮点表达式（DEC 科学模式）：小数点、^ 乘方、sqrt/log/ln 函数、0x 前缀 ----
// 与整数版平行的一条求值链（程序员整数/科学小数分开算，互不掺和）
function _bcEvalExprF(src) {
  let i = 0;
  const s = src.replace(/\s+/g, '');
  if (!s) throw new Error('空表达式');
  function parsePrimary() {
    const rest = s.slice(i);
    if (rest[0] === '(') { i++; const v = parseAdd(); if (s[i] !== ')') throw new Error('括号不匹配'); i++; return v; }
    const fn = /^(sqrt|log|ln|abs)\(/.exec(rest);
    if (fn) {
      i += fn[0].length;
      const v = parseAdd();
      if (s[i] !== ')') throw new Error('括号不匹配'); i++;
      return fn[1] === 'sqrt' ? Math.sqrt(v) : fn[1] === 'log' ? Math.log10(v)
           : fn[1] === 'abs' ? Math.abs(v) : Math.log(v);
    }
    if (rest.startsWith('1/(') || rest === '1/') {
      i += 2;   // 1/x 键插入 '1/'，x 位置接一个括号表达式或数字
      const v = parseUnary();
      if (v === 0) throw new Error('除零');
      return 1 / v;
    }
    const m = /^(0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)/.exec(rest);
    if (!m) throw new Error('无法识别: ' + (rest.slice(0, 8) || '(结尾)'));
    i += m[0].length;
    return /^0[xXbBoO]/.test(m[0]) ? Number(BigInt(m[0])) : Number(m[0]);
  }
  function parseUnary() { if (s[i] === '-') { i++; return -parseUnary(); } if (s[i] === '+') { i++; return parseUnary(); } return parsePrimary(); }
  function parsePow() { const v = parseUnary(); if (s[i] === '^') { i++; return Math.pow(v, parsePow()); } return v; }   // 乘方右结合
  function parseMul() {
    let v = parsePow();
    while (s[i] === '*' || s[i] === '/' || s[i] === '%') {
      const op = s[i++]; const r = parsePow();
      if ((op === '/' || op === '%') && r === 0) throw new Error('除零');
      v = op === '*' ? v * r : op === '/' ? v / r : v % r;
    }
    return v;
  }
  function parseAdd() {
    let v = parseMul();
    while (s[i] === '+' || s[i] === '-') { const op = s[i++]; const r = parseMul(); v = op === '+' ? v + r : v - r; }
    return v;
  }
  const v = parseAdd();
  if (i < s.length) throw new Error('多余字符: ' + s.slice(i, i + 8));
  return v;
}

// 无前缀按进制构造 BigInt：给 '0b'/'0o' 前缀再 BigInt()——按进制构造
// 不经过浮点（parseInt 是浮点解析，>2^53 丢精度，计算正确性红线）
function _bcParseRadix(t, radix) {
  const pre = radix === 16 ? '0x' : radix === 2 ? '0b' : radix === 8 ? '0o' : '';
  return BigInt(pre + t);
}

// ---- tab 构建（模式同 hex-viewer：tab + term-area wrap + connections 表）----
function buildBitCalcTab() {
  // 单例：已开就激活（计算器一个就够，不堆 tab）
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'bitcalc') { switchTab(pid); return; }
  }
  const portId = 'bitcalc:' + Date.now();
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico">🧮</span><span class="label">程序员计算器</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); closeEditorTab(portId); return; } switchTab(portId); };

  const wrap = document.createElement('div');
  wrap.className = 'term-area';
  wrap.dataset.portId = portId;
  wrap.style.display = 'none';
  wrap.innerHTML = `
    <div class="editor">
      <div class="log-viewer-toolbar">
        <select class="lv-btn" data-bc-bits title="寄存器位宽">
          <option value="8">8 位</option>
          <option value="16">16 位</option>
          <option value="32" selected>32 位</option>
          <option value="64">64 位</option>
        </select>
        <button class="lv-btn" data-bc-act="swap" title="字节序交换（大小端互换，仿 Marvell Swap）">⇄ Swap</button>
        <button class="lv-btn" data-bc-act="clear" title="清零（仿 Marvell Clear）">Clear</button>
        <span class="lv-info" data-bc-info></span>
      </div>
      <div class="bc-body">
        <!-- 位格区：按字节分组着色（分域辨识，仿 Marvell 8 组位号） -->
        <div class="bc-bits" data-bc-bits-grid></div>
        <!-- 整值三进制显示/输入（仿 Marvell Hex/Dec/Oct 单选 + MSB 输入框） -->
        <div class="bc-values">
          <label class="bc-vrow">HEX <input data-bc-v="16" spellcheck="false"></label>
          <label class="bc-vrow">DEC <input data-bc-v="10" spellcheck="false"></label>
          <label class="bc-vrow">OCT <input data-bc-v="8" spellcheck="false"></label>
          <label class="bc-vrow">BIN <input data-bc-v="2" spellcheck="false"></label>
        </div>
        <!-- 位运算速算：对当前值直接施加（带可选第二操作数） -->
        <div class="bc-opbar">
          <input class="bc-op2" data-bc-op2 placeholder="操作数 (0x.. / dec)" spellcheck="false">
          <button class="lv-btn" data-bc-op="and">AND</button>
          <button class="lv-btn" data-bc-op="or">OR</button>
          <button class="lv-btn" data-bc-op="xor">XOR</button>
          <button class="lv-btn" data-bc-op="not">NOT</button>
          <button class="lv-btn" data-bc-op="shl" title="左移（右侧「位数」框的位数）"><<</button>
          <button class="lv-btn" data-bc-op="shr" title="右移（右侧「位数」框的位数）">>></button>
          <span class="bc-shift-n"><input data-bc-shiftn value="1" style="width:34px"> 位</span>
        </div>
        <!-- 表达式计算器：完整运算（+ - * / % & | ^ ~ << >> 括号） -->
        <div class="bc-calc">
          <input class="bc-expr" data-bc-expr placeholder="表达式：如 (0x1F << 2) | 0b101 / 支持括号、0x/0b/0o 前缀、回车计算" spellcheck="false">
          <button class="lv-btn" data-bc-act="eval">=</button>
          <span class="bc-expr-res" data-bc-expr-res></span>
        </div>
        <!-- 点按键盘 + 时间戳 + 历史（仿 Windows 计算器：不止手动输入、有历史记录） -->
        <div class="bc-extra">
          <!-- 点按键盘：点击插入表达式框光标处（⌫/CE/= 也作用于表达式框），与手动输入完全打通。
               两模式（Windows 计算器同款分法）：
               HEX=程序员（A–F/位运算/整数）；DEC=科学（小数点/^ 乘方/函数） -->
          <div class="bc-keypad-wrap">
            <div class="bc-kp-modes">
              <button class="bc-kp-mode active" data-bc-kmode="hex">HEX 程序员</button>
              <button class="bc-kp-mode" data-bc-kmode="dec">DEC 科学</button>
            </div>
            <div class="bc-keypad" data-bc-keypad></div>
          </div>
          <div class="bc-side">
            <!-- 时间戳换算：Unix 秒/毫秒/0x → 本地+UTC+相对；datetime-local 反向出三形态 -->
            <div class="bc-box">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span class="bc-box-title">⏱ 时间戳</span>
                <input class="bc-expr" data-bc-ts-in placeholder="Unix 秒 / 毫秒 / 0x 时间戳" spellcheck="false" style="flex:1;min-width:150px;">
                <button class="lv-btn" data-bc-ts-now title="取当前时间戳（秒）">现在</button>
              </div>
              <div class="bc-ts-out" data-bc-ts-out></div>
              <div style="display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap;">
                <span style="color:var(--muted);font-size:11px;">反向</span>
                <input type="datetime-local" class="bc-dt" data-bc-ts-dt step="1">
              </div>
              <div class="bc-ts-out" data-bc-ts-rev></div>
            </div>
            <!-- 计算历史：= 成功即记录，点击条目回填表达式（持久化 config，重启不丢） -->
            <div class="bc-box">
              <div style="display:flex;align-items:center;gap:8px;">
                <span class="bc-box-title" style="flex:1;">🕘 历史</span>
                <button class="lv-btn" data-bc-hist-clear title="清空全部历史">清空</button>
              </div>
              <div class="bc-hlist" data-bc-hist-list></div>
            </div>
          </div>
        </div>
        <!-- 文件哈希：拖入或选择文件 → MD5/SHA1/SHA256/SHA512/CRC32（点值即复制） -->
        <div class="bc-hash" data-bc-hash
             style="border:1px dashed var(--border);border-radius:8px;padding:10px 12px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-weight:600;font-size:12px;">🔒 文件哈希</span>
            <button class="lv-btn" data-bc-hash-pick title="选择文件计算哈希">📂 打开文件</button>
            <span data-bc-hash-file style="color:var(--muted);font-size:12px;font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">拖入文件到此处，或点「打开文件」</span>
          </div>
          <div data-bc-hash-result style="display:none;margin-top:8px;font-family:var(--font-mono);font-size:12px;line-height:1.9;">
            <div data-bc-hash-rows></div>
          </div>
        </div>
      </div>
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(wrap);

  const conn = {
    portId,
    meta: { kind: 'bitcalc', label: '程序员计算器' },
    tab, wrap,
    bits: 32,
    value: 0n,
  };
  connections[portId] = conn;

  const grid = wrap.querySelector('[data-bc-bits-grid]');
  const inputs = wrap.querySelectorAll('[data-bc-v]');
  const infoEl = wrap.querySelector('[data-bc-info]');
  const exprRes = wrap.querySelector('[data-bc-expr-res]');

  const MASK = () => (1n << BigInt(conn.bits)) - 1n;
  const pad = (radix) => {
    if (radix === 16) return conn.bits / 4;
    if (radix === 2) return conn.bits;
    if (radix === 8) return Math.ceil(conn.bits / 3);
    return 0;
  };
  const fmt = (v, radix) => v.toString(radix).toUpperCase().padStart(pad(radix), '0');

  // 正在输入的框：document.activeElement 即正在敲的那个，render 时跳过
  // （输入中 inp.value 被覆盖会破坏光标位置）
  function render() {
    // 位格：MSB 在左（仿 Marvell 位号 31..0），按字节 8 组分色
    let html = '';
    for (let g = Math.ceil(conn.bits / 8) - 1; g >= 0; g--) {   // 高字节组在左
      html += '<div class="bc-bit-group">';
      for (let b = 7; b >= 0; b--) {
        const idx = g * 8 + b;
        if (idx >= conn.bits) continue;
        const on = (conn.value >> BigInt(idx)) & 1n;
        html += `<div class="bc-bit${on ? ' on' : ''}" data-bc-bit="${idx}" title="bit ${idx}"><span class="bc-bit-n">${idx}</span><span class="bc-bit-v">${on}</span></div>`;
      }
      html += '</div>';
    }
    grid.innerHTML = html;
    // 三进制联动（正在敲的框不动——保光标；activeElement 即焦点框，
    // 不依赖手动 _bcTyping 状态——状态机卡死时 render 会永久跳过该框，
    // 造成"HEX 空框其他正常"的不同步，用户实锤）
    const active = document.activeElement;
    inputs.forEach(inp => {
      if (inp === active) return;
      inp.value = fmt(conn.value, +inp.dataset.bcV);
    });
    infoEl.textContent = `${conn.bits} 位 · 0x${fmt(conn.value, 16)} · ${conn.value}(dec)`;
  }

  // 位格点击翻转（含按住拖动连翻不实现——单击已够用，流畅守则不做重的）
  grid.addEventListener('click', e => {
    const cell = e.target.closest('[data-bc-bit]');
    if (!cell) return;
    const idx = BigInt(cell.dataset.bcBit);
    conn.value = (conn.value ^ (1n << idx)) & MASK();
    render();
  });

  // 整值输入（任一进制框输入即解析，其他进制联动）。
  // 解析规则：带 0x/0b/0o 前缀按前缀进制；无前缀按框标注进制。
  inputs.forEach(inp => {
    inp.addEventListener('input', () => {
      const radix = +inp.dataset.bcV;
      const t = inp.value.trim().toLowerCase();
      if (!t) { conn.value = 0n; render(); return; }   // 清空=归零且必须 render——
      // 之前只置 0n 就 return，位格/DEC/OCT/BIN 全停在旧值造成不同步，用户实锤
      try {
        let v;
        if (/^0x[0-9a-f]+$/.test(t)) v = BigInt(t);
        else if (/^0b[01]+$/.test(t)) v = BigInt(t);
        else if (/^0o[0-7]+$/.test(t)) v = BigInt(t);
        // 无前缀：按框标注进制解析。HEX 框收 [0-9a-f]（'3d' 是合法 hex 值，
        // 不是"非法输入"——之前 /^0-9+$/ 把 '3d' 当非法 return 保持旧值，
        // 框里却留着用户敲的字符造成"HEX 空框/不同步"的观感，用户实锤）。
        // 按进制构造 BigInt（绝不能用 parseInt——浮点解析，64 位满宽输入
        // 超 2^53 丢精度，计算正确性红线）
        else if (radix === 16 && /^[0-9a-f]+$/.test(t)) v = _bcParseRadix(t, 16);
        else if (radix === 2 && /^[01]+$/.test(t)) v = _bcParseRadix(t, 2);
        else if (radix === 8 && /^[0-7]+$/.test(t)) v = _bcParseRadix(t, 8);
        else if (radix === 10 && /^[0-9]+$/.test(t)) v = BigInt(t);
        else return;   // 确实非法（如 DEC 框敲字母），保持旧值
        conn.value = v & MASK();
        // 联动其他进制框（正在输入的框不动——光标位置保不住）
        inputs.forEach(o => { if (o !== inp) o.value = fmt(conn.value, +o.dataset.bcV); });
        infoEl.textContent = `${conn.bits} 位 · 0x${fmt(conn.value, 16)} · ${conn.value}(dec)`;
      } catch (err) { /* 保持旧值 */ }
    });
    inp.addEventListener('blur', () => render());   // 失焦全量格式化（补前导零）
  });

  // 位宽切换：值截断到新位宽
  wrap.querySelector('[data-bc-bits]').addEventListener('change', e => {
    conn.bits = +e.target.value;
    conn.value &= MASK();
    render();
  });

  // 运算按钮（对当前值施加）：
  // AND/OR/XOR 用操作数框；NOT 无参；移位优先用操作数框、空则用位移位数框
  wrap.querySelectorAll('[data-bc-op]').forEach(btn => {
    btn.onclick = () => {
      const op = btn.dataset.bcOp;
      const op2raw = wrap.querySelector('[data-bc-op2]').value.trim().toLowerCase();
      const shn = BigInt(wrap.querySelector('[data-bc-shiftn]').value || '1');
      try {
        if (op === 'and' || op === 'or' || op === 'xor') {
          if (!op2raw) { exprRes.textContent = '需要操作数（左侧输入框）'; exprRes.classList.add('err'); return; }
          const o = _bcParseNum(op2raw);
          if (op === 'and') conn.value &= o;
          else if (op === 'or') conn.value |= o;
          else conn.value ^= o;
        } else if (op === 'not') {
          conn.value = ~conn.value & MASK();
        } else if (op === 'shl') {
          // 移位一律用「位数」框——操作数框只归 AND/OR/XOR，
          // 之前"操作数有值就优先"导致 << 一次跳 N 位不好预期
          conn.value = (conn.value << shn) & MASK();
        } else if (op === 'shr') {
          conn.value >>= shn;
        }
        exprRes.textContent = '';
        render();
      } catch (err) {
        exprRes.textContent = '操作数无效: ' + err.message;
        exprRes.classList.add('err');
      }
    };
  });

  // Swap/Clear
  wrap.querySelector('[data-bc-act="swap"]').onclick = () => {
    let v = 0n;
    const nBytes = conn.bits / 8;
    for (let b = 0; b < nBytes; b++) {
      const byte = (conn.value >> BigInt(b * 8)) & 0xFFn;
      v |= byte << BigInt((nBytes - 1 - b) * 8);
    }
    conn.value = v;
    render();
  };
  wrap.querySelector('[data-bc-act="clear"]').onclick = () => { conn.value = 0n; render(); };

  // ---- 表达式计算：HEX 模式结果进当前值（计算器与寄存器视图打通）；
  // DEC 科学模式走浮点求值器（小数域），结果只显示不进位格——寄存器是整数域
  const exprInp = wrap.querySelector('[data-bc-expr]');
  let kpMode = 'hex';   // 键盘模式（hex 程序员整数 / dec 科学小数），doEval 与键盘共用
  const doEval = () => {
    const src = exprInp.value.trim();
    if (!src) return;
    try {
      if (kpMode === 'dec') {
        const v = _bcEvalExprF(src);
        if (!isFinite(v)) throw new Error('结果非有限数');
        // 智能精度：整数结果不带小数尾巴；小数最多 12 位去尾零
        exprRes.textContent = '= ' + (Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(12))));
        exprRes.classList.remove('err');
      } else {
        conn.value = _bcEvalExpr(src, conn.bits);
        render();
        exprRes.textContent = '= 0x' + fmt(conn.value, 16) + ' · ' + conn.value;
        exprRes.classList.remove('err');
      }
      histAdd(src, exprRes.textContent);
    } catch (err) {
      exprRes.textContent = err.message;
      exprRes.classList.add('err');
    }
  };
  wrap.querySelector('[data-bc-act="eval"]').onclick = doEval;
  exprInp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); doEval(); }
  });

  // ---- 点按键盘：按钮插入表达式框光标处（与手动输入共用同一条求值链，零重复逻辑）。
  // 排布规则（对照官方计算器实拍修复 v3 的阶梯错位/空槽/缺 0）：
  //   6 列网格，数字 7-8-9/4-5-6/1-2-3 与 0/. 严格同列对齐（列 3-5，官方九宫格）；
  //   四则 ÷ × − + 独占右列（列 6）；位运算/函数独占左列（列 1）；
  //   顶行 CE/⌫/括号/%/±；A–F 独占一行（HEX），DEC 同一行换函数。
  //   键帽显示字符与实际插入 token 分离（÷→/ ×→* −→- ±→-），映射表 KP_TOK。
  //   模式切换键盘内容跟着换——不出现"DEC 高亮还摆着 A–F"的错配。
  const KP_TOK = { '÷':'/', '×':'*', '−':'-', '+':'+', '%':'%', '^':'^',
                   '(':null, ')':null, '.':'.', '±':'-', '1/x':'1/' };   // null=原样插入
  // 跨格键：[列跨度, 行跨度]——0 宽键填底行空洞（官方习惯），= 跨两行撑住右下角
  const KP_SPAN = { hex: { '0': [3, 1], '=': [1, 2] },
                    dec: { '0': [2, 1], '=': [1, 2] } };
  const KEYPADS = {
    hex: [   // 程序员：行2 字母 A–F 满行；行3-5 左列位运算 + 数字九宫格 + 右列四则
      ['CE','⌫','(',')','%','±'],
      ['A','B','C','D','E','F'],
      ['&','7','8','9','÷','<<'],
      ['|','4','5','6','×','>>'],
      ['^','1','2','3','−','='],
      ['~','0','','','+',''],
    ],
    dec: [   // 科学：行2 函数带开括号（与行1 括号去重）；行3-6 左列留空保持数字区不挪位
      ['CE','⌫','(',')','%','±'],
      ['sqrt(','log(','ln(','abs(','1/x','^'],
      ['','7','8','9','÷',''],
      ['','4','5','6','×',''],
      ['','1','2','3','−','='],
      ['','0','','.','+',''],
    ],
  };
  const keypad = wrap.querySelector('[data-bc-keypad]');
  const kpRender = () => {
    keypad.innerHTML = KEYPADS[kpMode].flatMap((row, r) => row.map((k, c) => {
      // 空槽不渲染（跨格键覆盖的格曾渲染 hidden div 与其重叠——v4 实测重叠无害
      // 但显式跳过更干净，且 dim 占位只为保网格感，跳过后布局依旧对齐）
      if (!k) return '';
      // 键帽显示去尾巴：多字符函数键 sqrt( → sqrt（单独的 ( ) 不剥——
      // v4 bug：endsWith('(') 把裸 ( 键也剥成空串，键帽空白被用户红框实锤）
      const disp = (k.length > 1 && k.endsWith('(')) ? k.slice(0, -1) : k;
      const [cs, rs] = KP_SPAN[kpMode][k] || [1, 1];
      const pos = (cs > 1 ? `grid-column:${c+1} / span ${cs};` : `grid-column:${c+1};`)
                + (rs > 1 ? `grid-row:${r+1} / span ${rs};` : `grid-row:${r+1};`);
      return `<div class="bc-key" data-bc-key="${esc(k)}" title="插入 ${esc(k)}" style="${pos}">${esc(disp)}</div>`;
    }).join('')).join('');
  };
  kpRender();
  // 模式切换：键盘换布 + 表达式框提示语同步（求值链 doEval 按 mode 分流）
  const exprPh = { hex: '表达式：如 (0x1F << 2) | 0b101 / 整数域，支持 0x/0b/0o 前缀、回车计算',
                   dec: '表达式：如 3.5*1.2+sqrt(2) / 小数域，支持 ^ 乘方、sqrt/log/ln、回车计算' };
  wrap.querySelectorAll('[data-bc-kmode]').forEach(btn => {
    btn.onclick = () => {
      kpMode = btn.dataset.bcKmode;
      wrap.querySelectorAll('[data-bc-kmode]').forEach(b => b.classList.toggle('active', b === btn));
      exprInp.placeholder = exprPh[kpMode];
      exprRes.textContent = '';
      kpRender();   // 键盘内容跟模式换（v3 的错配：DEC 高亮还摆着 A–F——实锤）
    };
  });
  keypad.addEventListener('click', e => {
    const cell = e.target.closest('[data-bc-key]');
    if (!cell || !cell.dataset.bcKey) return;
    const k = cell.dataset.bcKey;
    exprInp.focus();   // 插入前聚焦：selectionStart 才有效（没焦点时在末尾插）
    if (k === 'CE') { exprInp.value = ''; exprRes.textContent = ''; return; }
    if (k === '⌫') {
      const p = exprInp.selectionStart ?? exprInp.value.length;
      // 光标前若是多字符 token（<< >> sqrt( 等）整个删掉，符合按键直觉
      const before = exprInp.value.slice(0, p);
      const multi = ['sqrt(', 'log(', 'ln(', '<<', '>>'].find(t => before.endsWith(t));
      if (multi) exprInp.setRangeText('', p - multi.length, p, 'end');
      else exprInp.setRangeText('', Math.max(0, p - 1), p, 'end');
      return;
    }
    if (k === '=') { doEval(); return; }
    // 插入 token：KP_TOK 有映射用映射；括号/点/数字/字母直接贴；其余运算符两侧留空格
    let tok = Object.prototype.hasOwnProperty.call(KP_TOK, k) ? KP_TOK[k] : null;
    if (tok === null) tok = /[0-9a-fA-F.()]/.test(k) ? k : ' ' + k + ' ';
    const p = exprInp.selectionStart ?? exprInp.value.length;
    exprInp.setRangeText(tok, p, p, 'end');
  });

  // ---- 时间戳换算：程序员向——秒/毫秒/0x 自动识别 → 本地/UTC/相对时间；反向 datetime 出三形态 ----
  const tsIn = wrap.querySelector('[data-bc-ts-in]');
  const tsOut = wrap.querySelector('[data-bc-ts-out]');
  const tsDt = wrap.querySelector('[data-bc-ts-dt]');
  const tsRev = wrap.querySelector('[data-bc-ts-rev]');
  const tsNow = wrap.querySelector('[data-bc-ts-now]');
  const _p2 = (n) => String(n).padStart(2, '0');
  const _fmtDate = (d) => `${d.getFullYear()}-${_p2(d.getMonth()+1)}-${_p2(d.getDate())} ${_p2(d.getHours())}:${_p2(d.getMinutes())}:${_p2(d.getSeconds())}`;
  const _rel = (d) => {
    const diff = (Date.now() - d.getTime()) / 1000;
    const fut = diff < 0; const a = Math.abs(diff);
    let s;
    if (a < 60) s = Math.round(a) + ' 秒';
    else if (a < 3600) s = Math.round(a/60) + ' 分钟';
    else if (a < 86400) s = Math.round(a/3600) + ' 小时';
    else if (a < 86400*365) s = Math.round(a/86400) + ' 天';
    else s = (a/86400/365).toFixed(1) + ' 年';
    return fut ? s + '后' : s + '前';
  };
  const _tsRow = (lbl, val) =>
    `<div style="display:flex;gap:8px;align-items:baseline;">
       <span style="color:var(--muted);width:44px;flex-shrink:0;font-size:11px;">${lbl}</span>
       <span data-bc-ts-v="${esc(val)}" style="word-break:break-all;cursor:pointer;font-size:12px;" title="点击复制">${esc(val)}</span>
     </div>`;
  const _tsRevRender = () => {
    tsRev.innerHTML = '';
    if (!tsDt.value) return;
    const d = new Date(tsDt.value);
    if (isNaN(d)) return;
    const sec = Math.floor(d.getTime() / 1000);
    tsRev.innerHTML = _tsRow('秒', String(sec)) + _tsRow('毫秒', String(d.getTime())) + _tsRow('HEX', '0x' + sec.toString(16).toUpperCase());
  };
  // 点值即复制（与哈希面板同交互）
  [tsOut, tsRev].forEach(box => box.addEventListener('click', e => {
    const el = e.target.closest('[data-bc-ts-v]');
    if (!el) return;
    try { navigator.clipboard.writeText(el.dataset.bcTsV); showBanner('已复制 ' + el.dataset.bcTsV.slice(0, 20)); } catch(_){}
  }));
  const tsConvert = () => {
    const t = tsIn.value.trim().toLowerCase();
    tsOut.innerHTML = '';
    if (!t) return;
    let ms;
    try {
      if (/^0x[0-9a-f]+$/.test(t)) ms = Number(BigInt(t)) * 1000;          // 0x 视作秒
      else if (/^[0-9]{13,}$/.test(t)) ms = Number(t);                    // 13 位以上 → 毫秒
      else if (/^[0-9]+$/.test(t)) ms = Number(t) * 1000;                 // 常规秒
      else { tsOut.innerHTML = '<span style="color:var(--neon-red);font-size:11px;">无法识别（支持秒/毫秒/0x）</span>'; return; }
    } catch(_) { return; }
    const d = new Date(ms);
    if (isNaN(d)) { tsOut.innerHTML = '<span style="color:var(--neon-red);font-size:11px;">超出时间范围</span>'; return; }
    const utc = d.toISOString().replace('T', ' ').replace('.000Z', '');
    tsOut.innerHTML = _tsRow('本地', _fmtDate(d)) + _tsRow('UTC', utc) +
      `<div style="display:flex;gap:8px;align-items:baseline;">
         <span style="color:var(--muted);width:44px;flex-shrink:0;font-size:11px;">相对</span>
         <span style="font-size:12px;">${_rel(d)}</span>
       </div>` + _tsRow('HEX', '0x' + Math.floor(ms/1000).toString(16).toUpperCase());
  };
  tsIn.addEventListener('input', tsConvert);
  tsIn.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); tsConvert(); } });
  tsNow.onclick = () => { tsIn.value = String(Math.floor(Date.now() / 1000)); tsConvert(); };
  tsDt.addEventListener('change', _tsRevRender);
  tsDt.addEventListener('input', _tsRevRender);

  // ---- 计算历史：= 成功即记录（表达式→结果），点击条目回填表达式；config 持久化 ----
  const histList = wrap.querySelector('[data-bc-hist-list]');
  let histItems = [];   // [{expr, res}] 最新在前，上限 50
  const HIST_MAX = 50;
  const histRender = () => {
    if (!histItems.length) {
      histList.innerHTML = '<div style="color:var(--muted);font-size:11px;padding:4px 0;">尚无历史记录</div>';
      return;
    }
    histList.innerHTML = histItems.map((h, i) =>
      `<div class="bc-hitem" data-bc-hi="${i}" title="点击回填到表达式框">
         <span class="bc-hitem-e">${esc(h.expr)}</span>
         <span class="bc-hitem-r">${esc(h.res)}</span>
       </div>`).join('');
  };
  const histSave = () => {
    try { fetch('/api/theme', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({calc_history: histItems})}); } catch(_) {}
  };
  const histAdd = (expr, res) => {
    histItems = [{expr, res}, ...histItems.filter(h => h.expr !== expr)].slice(0, HIST_MAX);
    histRender(); histSave();
  };
  histList.addEventListener('click', e => {
    const it = e.target.closest('[data-bc-hi]');
    if (!it) return;
    exprInp.value = histItems[+it.dataset.bcHi].expr;
    exprInp.focus();
  });
  wrap.querySelector('[data-bc-hist-clear]').onclick = () => {
    histItems = []; histRender(); histSave();
  };
  // 启动拉取历史（config 持久化——Flask 端口随机，localStorage 按 origin 隔离读不回）
  (async () => {
    try {
      const j = await (await fetch('/api/theme')).json();
      if (Array.isArray(j.calc_history)) {
        histItems = j.calc_history
          .filter(h => h && typeof h.expr === 'string' && typeof h.res === 'string')
          .slice(0, HIST_MAX);
        histRender();
      }
    } catch(_) {}
  })();

  // ---- 文件哈希面板：拖入 / 打开 → /api/hash_file → 全套哈希（点值复制） ----
  const hashBox = wrap.querySelector('[data-bc-hash]');
  const hashFileEl = wrap.querySelector('[data-bc-hash-file]');
  const hashRowsEl = wrap.querySelector('[data-bc-hash-rows]');
  const hashResultEl = wrap.querySelector('[data-bc-hash-result]');
  const HASH_NAMES = [['md5','MD5'],['sha1','SHA1'],['sha256','SHA256'],['sha512','SHA512'],['crc32','CRC32']];
  const _hashFmtSize = (n) => n >= 1024*1024*1024 ? (n/1024/1024/1024).toFixed(2)+' GB'
    : n >= 1024*1024 ? (n/1024/1024).toFixed(1)+' MB' : n >= 1024 ? (n/1024).toFixed(1)+' KB' : n + ' B';
  async function _hashFile(path) {
    if (!path) return;
    hashFileEl.textContent = path.split(/[\\/]/).pop() + '（计算中…）';
    hashResultEl.style.display = 'none';
    try {
      const r = await fetch('/api/hash_file', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({path})});
      const j = await r.json();
      if (!j.ok) { hashFileEl.textContent = '❌ ' + (j.err || '计算失败'); return; }
      hashFileEl.textContent = `${path} （${_hashFmtSize(j.size)}）`;
      hashRowsEl.innerHTML = HASH_NAMES.map(([k, n]) =>
        `<div style="display:flex;gap:8px;align-items:baseline;">
           <span style="color:var(--muted);width:56px;flex-shrink:0;">${n}</span>
           <span data-bc-hash-v="${j[k]}" style="word-break:break-all;cursor:pointer;" title="点击复制">${esc(j[k])}</span>
         </div>`).join('');
      hashResultEl.style.display = '';
      hashRowsEl.querySelectorAll('[data-bc-hash-v]').forEach(el => {
        el.onclick = () => {
          try { navigator.clipboard.writeText(el.dataset.bcHashV); showBanner('已复制 ' + el.textContent.slice(0, 16) + '…'); } catch(_){}
        };
      });
    } catch(e) { hashFileEl.textContent = '❌ 请求失败: ' + e; }
  }
  wrap.querySelector('[data-bc-hash-pick]').onclick = async () => {
    try {
      const p = await pywebview.api.pick_any();
      if (p) _hashFile(p);
    } catch(e) { showBanner('文件选择器不可用: ' + e, 3000, true); }
  };
  conn.hashFile = _hashFile;   // 挂到 conn：openDroppedFile 拖到计算器 tab 时分发用
  // 拖入视觉反馈：dragover 高亮边框。真实路径处理不在这里——WebView2 拖文件
  // File.path 恒空（安全模型），pywebview 原生全局 drop_handler 独立于 JS 事件
  // 流（stopPropagation 阻不断），它拿 pywebviewFullPath 转 openDroppedFile，
  // 计算器 tab 激活时分发回 _hashFile（editor.js 分发头）。
  hashBox.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); hashBox.style.borderColor = 'var(--accent)'; });
  hashBox.addEventListener('dragleave', () => { hashBox.style.borderColor = 'var(--border)'; });
  hashBox.addEventListener('drop', e => { e.preventDefault(); hashBox.style.borderColor = 'var(--border)'; });

  render();
  switchTab(portId);
  refreshSidebar();
  return conn;
}
