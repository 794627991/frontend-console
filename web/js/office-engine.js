// ============================================================
// 文档渲染引擎（2026-11-26）——pptx / xlsx 的新渲染实现
//
// 用户令（D01/D02/D04）：pptx 用 @aiden0z/pptx-renderer、xlsx 用
// @extend-ai/react-xlsx 的 wasm 引擎，默认打开一律只读；主界面标签页里
// 现有的 office 预览一并换新引擎（一套引擎两处用）；xlsx 自研编辑网格退役。
//
// **两个库都按 Step 0 实测的形态接**（V02/V03 的结论）：
//  · pptx-renderer 1.4.0 是自包含单文件（2.26MB，零外部 import），直接 import。
//  · xlsx-engine 的 dist 里有 5 个裸模块引用、还残留 process.env.NODE_ENV，
//    靠 index.html 的 importmap + window.process 替身解决。**不要**再把 dist
//    原样拷进来指望能用——实测必炸（见文档 10.2 的 V02 结论）。
//
// 与旧引擎的关系：本模块只做「渲染」，不碰 OnlyOffice 编辑链（D03 要求原样
// 不动）、不碰 PDF（A01 保持现有 pdf.js 链）。
// ============================================================

// 两个库都是几 MB 的 ES module：并发打开两个文档时只 import 一次。
//
// **路径必须是相对本模块文件的**（`../..` 回到站点根），不能写
// `vendor/...`——`import()` 的说明符按**模块文件位置**解析，不是按页面 URL。
// 实测踩过：写成 `vendor/pptx-renderer/...` 会被解析成
// `/web/js/vendor/pptx-renderer/...` → 404，报「缺少依赖」。
const _PPTX_URL = new URL('../../vendor/pptx-renderer/aiden0z-pptx-renderer.browser.es.js',
                          import.meta.url).href;
const _XLSX_URL = new URL('../../vendor/xlsx-engine/vanilla.js', import.meta.url).href;

// 两个库都是几 MB 的 ES module：并发打开两个文档时只 import 一次
let _pptxMod = null, _xlsxMod = null;

function _loadPptx() {
  if (!_pptxMod) _pptxMod = import(/* @vite-ignore */ _PPTX_URL);
  return _pptxMod;
}

function _loadXlsx() {
  if (!_xlsxMod) _xlsxMod = import(/* @vite-ignore */ _XLSX_URL);
  return _xlsxMod;
}

// 统一错误文案：库的异常多是英文栈，直接给用户看没意义
function _errText(e) {
  const m = (e && (e.message || e.reason && e.reason.message)) || String(e || '');
  if (/process is not defined/.test(m)) {
    return 'xlsx 引擎初始化失败：缺少运行环境替身（index.html 的 window.process）';
  }
  if (/Failed to resolve module specifier/.test(m)) {
    return 'xlsx 引擎缺少依赖：' + m.replace(/.*module specifier\s*/i, '');
  }
  if (/Failed to fetch dynamically imported module/.test(m)) {
    return '渲染库文件加载失败——vendor 目录可能不完整（' + m.slice(-80) + '）';
  }
  return m.slice(0, 300);
}

// ---------------------------------------------------------------
// pptx：PptxViewer 列表模式（按需挂载，大 PPT 不会一次渲染全部）
// 返回 { dispose() }，供关闭标签时清理（AC-1.12 要求无残留定时器/监听）
// ---------------------------------------------------------------
export async function openPptx(container, buf, opts) {
  opts = opts || {};
  const mod = await _loadPptx();
  const Viewer = mod.PptxViewer;
  if (!Viewer) throw new Error('pptx-renderer 里没有 PptxViewer 导出');

  const viewer = new Viewer(container, {
    fitMode: opts.fitMode || 'contain',
    // pdfjs 只在 PPT 内嵌 EMF 里含 PDF 时才用到（回退路径）。指向本地 vendor，
    // 不联网；关掉 cmap/standardFont 是它们不是必需，且能省一次 404。
    pdfjs: { workerSrc: '/vendor/pdfjs/pdf.worker.min.js',
             cMapUrl: false, standardFontDataUrl: false },
    onSlideError: (i, e) => {
      // 单页失败不该让整份文档白屏：把失败页号记到容器上，界面层统一提示
      (container.__slideErrors || (container.__slideErrors = [])).push(i + 1);
      if (window.console) console.warn('[pptx] 第 ' + (i + 1) + ' 页渲染失败:', e);
    },
    onRenderComplete: () => { if (opts.onDone) opts.onDone(); },
  });

  await viewer.open(new Uint8Array(buf));
  container.__pptxViewer = viewer;

  return {
    kind: 'pptx',
    slideCount: (viewer.getMountedSlides && viewer.getMountedSlides().length) || 0,
    errors: container.__slideErrors || [],
    goToSlide: (i) => viewer.goToSlide(i),
    setFitMode: (m) => viewer.setFitMode(m),
    setZoom: (p) => viewer.setZoom(p),
    // 用户令 D01「默认打开一律只读」：这个库本身就是只读渲染器，无编辑入口
    dispose() {
      // PptxViewer 没有公开 destroy；实测它内部挂了 ResizeObserver 与若干
      // window resize 监听（Viewer.d.ts 的 resizeObserver / windowResizeHandler），
      // 容器被移除后这些监听仍持有引用。清空容器并断开我们自己的引用，
      // 剩下的交给 GC——**不要**去调库的私有成员（升级即碎）。
      try { container.innerHTML = ''; } catch (_) {}
      try { delete container.__pptxViewer; } catch (_) {}
    },
  };
}

// ---------------------------------------------------------------
// xlsx：createXlsxViewer（vanilla 入口，不依赖 React）
// ---------------------------------------------------------------
export async function openXlsx(container, buf, opts) {
  opts = opts || {};
  // 引擎以 file: Uint8Array 启动；沿用实测通过的形态
  const mod = await _loadXlsx();
  if (!mod.createXlsxViewer) throw new Error('xlsx-engine 里没有 createXlsxViewer 导出');

  const el = document.createElement('div');
  el.className = 'ov-xlsx-host';
  el.style.cssText = 'position:absolute;inset:0;';
  container.appendChild(el);

  const viewer = mod.createXlsxViewer(el, {
    file: new Uint8Array(buf),
    // 只读（D01）：vanilla 视图默认就不可编辑；显式关掉一切写入口，
    // 免得后来改配置时误开（唯一编辑途径是 OnlyOffice，见 D02/D03）
    ...(opts.extra || {}),
  });
  if (viewer && viewer.ready && typeof viewer.ready.then === 'function') {
    await viewer.ready;
  }
  container.__xlsxViewer = viewer;

  const c = viewer && viewer.controller;
  return {
    kind: 'xlsx',
    controller: c,
    sheetName: c && c.activeSheet ? c.activeSheet.name : '',
    // V04 实测结论：控制器**只有单格接口**，没有批量读。
    //   getCellSnapshotAsync(workbookSheetIndex, row, col) -> {displayValue, formula}
    //   getCellDisplayValue(cell) / getCellFormula(cell)
    // 后端 read_document 的 xlsx 分支要按行窗口逐格攒批（文档 6.1.5）。
    readCell: c && c.getCellSnapshotAsync
      ? (row, col) => c.getCellSnapshotAsync(
          c.activeSheet && c.activeSheet.workbookSheetIndex != null
            ? c.activeSheet.workbookSheetIndex : 0, row, col)
      : null,
    dispose() {
      try { container.innerHTML = ''; } catch (_) {}
      try { delete container.__xlsxViewer; } catch (_) {}
    },
  };
}

// ---------------------------------------------------------------
// 统一入口：按类型挑引擎。返回 null 表示「本模块不管这种类型」
//（pdf / docx / 图片仍走 office-viewer.js 的既有链路）
// ---------------------------------------------------------------
export async function openDocument(container, kind, buf, opts) {
  try {
    if (kind === 'ppt') return await openPptx(container, buf, opts);
    if (kind === 'excel') return await openXlsx(container, buf, opts);
    return null;
  } catch (e) {
    throw new Error(_errText(e));
  }
}

window.OfficeEngine = { openDocument, openPptx, openXlsx, errText: _errText };
