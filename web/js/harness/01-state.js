// harness 共享可变状态(v3.0 自 buildClaudeHarnessTab 闭包绑定提升为脚本全局;
// DOM/查询类初始化赋值仍在 main.js 的 buildClaudeHarnessTab 内原位执行,时机不变)
let _hgWrap;   // wrap → _hgWrap
let _hgConn;   // conn → _hgConn
let _hgQ;   // q → _hgQ
let _hgFlow;   // flow → _hgFlow
let _hgJumpBtm;   // jumpBtm → _hgJumpBtm（v3.2.8 一键跳底浮动钮）
let _hgInput;   // input → _hgInput
let _hgStateEl;   // stateEl → _hgStateEl
let _hgCostEl;   // costEl → _hgCostEl
let _hgSendBtn;   // sendBtn → _hgSendBtn
let _hgTitleEl;   // titleEl → _hgTitleEl
let _hgCwdEl;   // cwdEl → _hgCwdEl
let _hgAttsEl;   // attsEl → _hgAttsEl
let _hgListEl;   // listEl → _hgListEl
let _hgSearchEl;   // searchEl → _hgSearchEl
let _hgFileEl;   // fileEl → _hgFileEl
let _hgOverlayEl;   // overlayEl → _hgOverlayEl
let _hgMentionEl;   // mentionEl → _hgMentionEl
let _hgActEl;   // actEl → _hgActEl
let _hgScrollBottom;   // scrollBottom → _hgScrollBottom
let _codeIO;
let _hgLeftNearBottom;
let _hgCtxInFlight;
let _histBusy;
let queueEl;
let quoteEl;
let quoteBodyEl;
let qDrag;
let dynEl;
let _hgAiPanel;
let _hgRolesCache;
let _dynRaf;
let _agentModelsTried;
let _subPaneEl;
let _subTabsEl;
let _subBodyEl;
let _subRes;
let _subX;
let visIndEl;
let visBtnEl;
