// ============================================================
// docview / index —— 对外入口，挂 window.DocView
//
// 设计文档 6.1.1：
//   DocView.mount(container, {path, kind, host})
//   DocView.openInHarness(path, {at, by})
//   DocView.agentOpen(req_id, path, at)
//   DocView.agentShow(req_id, targets, note, seq)
//   DocView.restoreForSession(sid)
//
// 本文件先注册全部渲染器再暴露 mount——core 的 RENDERERS 表靠注册填充。
// 分屏那部分（harness-pane.js）在 Step 2 的第二段落接。
// ============================================================

import { registerRenderer, mount } from './core.js';
import { createDocxInstance } from './docx.js';
import { createPdfInstance } from './pdf.js';
import { createXlsxInstance } from './xlsx.js';
import { createPptxInstance } from './pptx.js';
import { createImageInstance } from './image.js';
import { kindOfPath, parseAnchor, DOC_EXTS, isDocPath } from './anchor.js';
import { linkifyHtml, linkifyNode } from './linkify.js';

registerRenderer('docx', createDocxInstance);
registerRenderer('pdf', createPdfInstance);
registerRenderer('xlsx', createXlsxInstance);
registerRenderer('pptx', createPptxInstance);
registerRenderer('image', createImageInstance);

const DocView = {
  mount,
  kindOfPath,
  parseAnchor,
  isDocPath,
  DOC_EXTS,
  linkifyHtml,
  linkifyNode,
};

// 分屏模块可用时补上那几个入口（模块加载顺序：index.js 最后 import 它们）
try {
  const pane = await import('./harness-pane.js');
  DocView.openInHarness = pane.openInHarness;
  DocView.agentOpen = pane.agentOpen;
  DocView.agentShow = pane.agentShow;
  DocView.restoreForSession = pane.restoreForSession;
  DocView.beforeReset = pane.beforeReset;
  // 后端推来的请求（Step 3，6.4.3）：sense.js 收到 ui_action 后调这两个
  DocView.onOpenRequest = pane.onOpenRequest;
  DocView.onShowRequest = pane.onShowRequest;
  // 「打开文件」伪 tab（2026-11-26 用户令：胶囊展开后与动态/目录同级）
  DocView.ensureDocOpenTab = pane.ensureDocOpenTab;
  DocView.openDocOpenTab = pane.openDocOpenTab;
  window._subDocOpenEnsure = pane.ensureDocOpenTab;
  // main.js 的 tab 点击分支用它在懒建前判断「这是文档面板的伪 tab」
  window._subDocOpenTids = [pane.DOCOPEN_TID];
} catch (e) {
  // 分屏模块还没就绪（或主界面形态下不需要）：其余接口照常可用
  if (window.console) console.warn('[docview] 分屏模块未加载', e && e.message);
}

window.DocView = DocView;
export default DocView;
