// ============================================================
// 文件类型图标体系：手绘 SVG,按后缀区分(用户需求:图标跟随后缀绑定,
// 文件主体 + 左下角像素化小机器人角标——呼应工具 logo 的机器人形象)。
// 设计:16x16 网格 viewBox,通用文件纸形 + 后缀专属元素/字标 + 左下角
// 3x3 像素机器人头角标(青色 accent,与主题变量联动由 CSS 处理)。
// 内联 SVG 字符串(非 <img>):随 CSS 变量着色,免 HTTP 请求,离线可用。
// ============================================================

// 像素小机器人角标(左下角)——app.ico logo 缩小复刻:深蓝灰 squircle 底 +
// 蓝机身黑描边 + 天线青球 + 镜头同心圆(白环蓝心) + 橙腮红两点。
// 初版"方脸双眼像素风"被用户否定(太丑、不还原真身 logo),按 logo 逐层重绘。
const _robotBadge = `
  <g class="fi-robot">
    <rect x="2" y="12" width="11" height="11" rx="2.2" fill="var(--bg-deep)"/>
    <rect x="7.2" y="13" width="0.6" height="2" fill="var(--bg-deep)" stroke="var(--accent)" stroke-width="0.5"/>
    <circle cx="7.5" cy="12.6" r="1" fill="var(--accent)"/>
    <rect x="3" y="15" width="9" height="6" rx="2.6" fill="var(--bg-deep)" stroke="var(--accent)" stroke-width="0.8"/>
    <circle cx="7.5" cy="18" r="2.3" fill="var(--bg-deep)"/>
    <circle cx="7.5" cy="18" r="1.7" fill="var(--accent)" opacity="0.25" stroke="var(--accent)" stroke-width="0.45"/>
    <circle cx="7.5" cy="18" r="0.75" fill="var(--accent)"/>
    <circle cx="6.9" cy="17.3" r="0.3" fill="#fff"/>
    <circle cx="4.4" cy="19.3" r="0.45" fill="#f98d55"/>
    <circle cx="10.6" cy="19.3" r="0.45" fill="#f98d55"/>
  </g>`;

// 文件主体纸形(圆角折角纸)+ 可选的"内容元素"由各类型自定义
function _fileShape(body, color) {
  return `
  <path class="fi-paper" d="M4 2.5 h9 l3.5 3.5 v11 a1.5 1.5 0 0 1 -1.5 1.5 h-11 a1.5 1.5 0 0 1 -1.5 -1.5 v-13 a1.5 1.5 0 0 1 1.5 -1.5 z"
        fill="${color}" fill-opacity="0.22" stroke="${color}" stroke-width="1.2"/>
  <path d="M13 2.5 l3.5 3.5 h-3.5 z" fill="${color}" fill-opacity="0.45"/>
  ${body}`;
}

// 各后缀的图标定义:body 是主体内的内容元素/字标
const _icons = {
  // 纯文本:三行"文字"横线
  txt: _fileShape(`
    <rect x="6" y="7" width="7" height="1.2" rx="0.6" fill="currentColor" opacity="0.75"/>
    <rect x="6" y="9.5" width="7" height="1.2" rx="0.6" fill="currentColor" opacity="0.55"/>
    <rect x="6" y="12" width="4.5" height="1.2" rx="0.6" fill="currentColor" opacity="0.35"/>`, '#7aa2c8'),

  // 日志:卷轴感——竖排时间轴点+行线,左上角"LOG"太挤,用时钟元素
  log: _fileShape(`
    <circle cx="7.5" cy="8.5" r="2.2" fill="none" stroke="#4fd1a1" stroke-width="1.1"/>
    <path d="M7.5 7.3 v1.4 l1 0.7" fill="none" stroke="#4fd1a1" stroke-width="1" stroke-linecap="round"/>
    <rect x="10.5" y="7" width="4" height="1" rx="0.5" fill="currentColor" opacity="0.5"/>
    <rect x="10.5" y="9.5" width="4" height="1" rx="0.5" fill="currentColor" opacity="0.4"/>
    <rect x="6" y="12.5" width="8.5" height="1" rx="0.5" fill="currentColor" opacity="0.3"/>`, '#4fd1a1'),

  // C 源码:大写字母 C 字标
  c: _fileShape(`
    <text x="10.2" y="13.2" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="8.5" fill="#5cb3ff">C</text>`, '#5cb3ff'),

  // C 头文件:H 字标
  h: _fileShape(`
    <text x="10.2" y="13.2" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="8.5" fill="#5cb3ff">H</text>`, '#5cb3ff'),

  // C++:C 加双加号
  cpp: _fileShape(`
    <text x="9" y="13.2" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="8" fill="#5cb3ff">C</text>
    <text x="12.3" y="11.2" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="5" fill="#5cb3ff">+</text>
    <text x="12.3" y="14.2" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="5" fill="#5cb3ff">+</text>`, '#5cb3ff'),

  // JSON:花括号对
  json: _fileShape(`
    <text x="10.2" y="13.5" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="8" fill="#e8a25b">{ }</text>`, '#e8a25b'),

  // Markdown:M 字标 + 分隔线
  md: _fileShape(`
    <text x="10.2" y="13" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="8" fill="#b08cd9">M</text>
    <rect x="6" y="14" width="8" height="1.1" rx="0.55" fill="#b08cd9" opacity="0.6"/>`, '#b08cd9'),

  // ini/cfg/conf 配置:齿轮
  ini: _fileShape(`
    <circle cx="10" cy="10" r="2.6" fill="none" stroke="#d2a8ff" stroke-width="1.2"/>
    <circle cx="10" cy="10" r="1" fill="#d2a8ff"/>
    <rect x="9.4" y="6.4" width="1.2" height="1.6" rx="0.4" fill="#d2a8ff"/>
    <rect x="9.4" y="12" width="1.2" height="1.6" rx="0.4" fill="#d2a8ff"/>
    <rect x="6.4" y="9.4" width="1.6" height="1.2" rx="0.4" fill="#d2a8ff"/>
    <rect x="12" y="9.4" width="1.6" height="1.2" rx="0.4" fill="#d2a8ff"/>`, '#d2a8ff'),

  // Python:双蛇形(简化双色方块)
  py: _fileShape(`
    <rect x="7" y="6.5" width="4" height="2" rx="1" fill="#ffd43b" opacity="0.9"/>
    <rect x="9.5" y="9.5" width="4" height="2" rx="1" fill="#5cb3ff" opacity="0.9"/>
    <rect x="7" y="12.5" width="4" height="2" rx="1" fill="#ffd43b" opacity="0.7"/>`, '#ffd43b'),

  // shell/bat/ps1:终端提示符 >_
  sh: _fileShape(`
    <path d="M6.5 7.5 l3 2.5 -3 2.5" fill="none" stroke="#8fd494" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
    <rect x="10.5" y="12" width="3.5" height="1.2" rx="0.6" fill="#8fd494"/>`, '#8fd494'),

  // yaml/yml:层进树线
  yaml: _fileShape(`
    <rect x="6" y="7" width="1.2" height="8" rx="0.6" fill="currentColor" opacity="0.6"/>
    <rect x="8" y="8.5" width="1.2" height="5" rx="0.6" fill="currentColor" opacity="0.45"/>
    <rect x="8" y="9" width="5" height="1" rx="0.5" fill="currentColor" opacity="0.55"/>
    <rect x="8" y="11" width="4" height="1" rx="0.5" fill="currentColor" opacity="0.45"/>
    <rect x="10" y="10.5" width="4" height="1" rx="0.5" fill="currentColor" opacity="0.5"/>
    <rect x="10" y="12.5" width="3" height="1" rx="0.5" fill="currentColor" opacity="0.4"/>`, '#56b8d9'),

  // hex/二进制:0x 字标 + 二进制位
  hex: _fileShape(`
    <text x="10.2" y="12.8" text-anchor="middle" font-family="Consolas,monospace" font-weight="bold"
          font-size="6.5" fill="#e0727f">0x</text>
    <rect x="6.5" y="13.8" width="1.4" height="1.4" rx="0.3" fill="#e0727f" opacity="0.8"/>
    <rect x="8.3" y="13.8" width="1.4" height="1.4" rx="0.3" fill="#e0727f" opacity="0.5"/>
    <rect x="10.1" y="13.8" width="1.4" height="1.4" rx="0.3" fill="#e0727f" opacity="0.8"/>
    <rect x="11.9" y="13.8" width="1.4" height="1.4" rx="0.3" fill="#e0727f" opacity="0.4"/>`, '#e0727f'),
};

// 默认(未知后缀/笔记 .note 等):通用纸形 + 圆点
_icons._default = _fileShape(`
  <circle cx="10.2" cy="10" r="1.8" fill="currentColor" opacity="0.5"/>`, '#7aa2c8');

// 后缀 → 图标 key(复数归并同形)
const FILE_ICON_EXT = {
  '.txt': 'txt', '.note': 'txt',
  '.log': 'log',
  '.c': 'c', '.h': 'h',
  '.cpp': 'cpp', '.hpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp',
  '.json': 'json', '.csv': 'json',
  '.md': 'md',
  '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini', '.toml': 'ini', '.properties': 'ini',
  '.py': 'py', '.pyw': 'py',
  '.sh': 'sh', '.bat': 'sh', '.cmd': 'sh', '.ps1': 'sh',
  '.yaml': 'yaml', '.yml': 'yaml',
  '.bin': 'hex', '.hex': 'hex', '.dat': 'hex', '.img': 'hex', '.elf': 'hex',
};

// 生成文件类型图标 HTML(inline SVG)。name: 文件名或带后缀的路径
function fileIconHtml(name, size) {
  const n = (name || '').toLowerCase();
  const dot = n.lastIndexOf('.');
  const ext = dot > 0 ? n.slice(dot) : '';
  const key = FILE_ICON_EXT[ext] || '_default';
  const sz = size || 14;
  return `<svg class="fi fi-${key}" width="${sz}" height="${sz}" viewBox="0 0 22 22" aria-hidden="true">${_icons[key]}${_robotBadge}</svg>`;
}
