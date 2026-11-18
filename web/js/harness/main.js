// harness main(v3.0):buildClaudeHarnessTab 语句体+壳——DOM 拼装/事件绑定/散落赋值。
function buildClaudeHarnessTab(opts = {}) {
  for (const pid in connections) {
    const c = connections[pid];
    if (c && c.meta && c.meta.kind === 'harness') { switchTab(pid); return; }
  }
  const portId = 'harness:gui';
  const tab = document.createElement('div');
  tab.className = 'tab';
  tab.dataset.portId = portId;
  tab.innerHTML = `<span class="led"></span><span class="tab-ico claude-ico"></span><span class="label">Claude 对话</span><span class="baud"></span><span class="close" title="关闭">✕</span>`;
  tab.onclick = (e) => { if (e.target.classList.contains('close')) { e.stopPropagation(); _harnessClose(portId); return; } switchTab(portId); };

  _hgWrap = document.createElement('div');
  _hgWrap.className = 'term-area';
  _hgWrap.dataset.portId = portId;
  _hgWrap.style.display = 'none';
  _hgWrap.innerHTML = `
    <div class="hg">
      <div class="hg-side">
        <div class="hg-side-head">
          <button class="hg-new-btn" data-hg-new title="新建会话">✚ 新建会话</button>
          <button class="hg-new-btn hg-recover-btn" data-hg-recover title="扫描磁盘上的会话记录，找回列表里消失的会话（异常丢失/误删都可找回）">⟲ 恢复会话</button>
        </div>
        <div class="hg-search-wrap"><input autocomplete="off" class="hg-search" data-hg-search placeholder="搜索会话" spellcheck="false" name="hg_search"></div>
        <div class="hg-sessions" data-hg-sessions></div>
        <button class="hg-prompt-btn" data-hg-vision title="识图配置（MCP 识图模型/端点映射/提示词）">${ICO16.eye} 识图配置</button>
        <button class="hg-prompt-btn" data-hg-roles-cfg title="三角色配置：开关/三槽模型（主会话/设计/审核）/端点角色映射/审核模式与分级线（保存后下条消息热更生效）。双形态：轻主力=主会话直干所有活+设计+审核两个代理；重主力=直干+审核兜底">${ICO16.users} 三角色</button>
        <button class="hg-prompt-btn" data-hg-prompt title="管理自定义提示词（全局/项目，会话启动时注入）">${ICO16.book} 提示词</button>
        <button class="hg-prompt-btn" data-hg-skills-btn title="技能仓库：发现/安装/管理 Claude 技能（skills.sh），支持离线包与中文汉化">${ICO16.puzzle} 技能仓库</button>
        <button class="hg-prompt-btn" data-hg-proxy-btn title="Claude 代理：重试代理（429/5xx 自动重试）+ 用量统计。点开代理面板">
          <img src="/ico/proxy.png" alt="proxy" style="width:14px;height:14px;vertical-align:-2px;"> Proxy
          <span class="hg-proxy-state" data-hg-proxy-state>检测中…</span>
        </button>
        <button class="hg-prompt-btn hg-login-side" data-hg-login-toggle title="机器人凭据与登录账号。指示灯=机器人在线状态，用户名颜色=登录状态。点击展开配置">
          <span class="hg-login-dot off" data-hg-login-dot></span>
          <span class="hg-login-botlabel">机器人</span>
          <span class="hg-login-userlabel" data-hg-login-text>未登录</span>
        </button>
        <div class="hg-login-pop" data-hg-login-pop style="display:none">
          <div data-hg-login-off>
            <div class="hg-pop-row hg-robot-hint">账号登录（用于代理与额度）</div>
            <input class="hg-login-inp" data-hg-login-user placeholder="用户名" spellcheck="false" autocomplete="username" name="hg_login_user">
            <div class="hg-inp-wrap">
              <input class="hg-login-inp" data-hg-login-pwd type="password" placeholder="密码" autocomplete="current-password" name="hg_login_pwd">
              <button class="hg-inp-eye" type="button" data-hg-eye title="显示密码" aria-label="显示密码">${ICO16.eye}</button>
            </div>
            <button class="hg-prompt-btn" data-hg-login-btn>登录</button>
          </div>
          <div class="hg-robot-box">
            <div class="hg-pop-row hg-robot-head">
              <span class="hg-robot-title">机器人凭据</span>
              <span class="hg-login-dot off" data-hg-robot-dot></span>
              <span class="hg-robot-state" data-hg-robot-state></span>
            </div>
            <div class="hg-robot-fields">
              <input class="hg-login-inp" data-hg-robot-id placeholder="App ID" spellcheck="false" autocomplete="off" name="hg_robot_id">
              <div class="hg-inp-wrap">
                <input class="hg-login-inp" data-hg-robot-secret type="password" placeholder="App Secret" autocomplete="new-password" name="hg_robot_secret">
                <button class="hg-inp-eye" type="button" data-hg-eye title="显示密钥" aria-label="显示密钥">${ICO16.eye}</button>
              </div>
              <button class="hg-prompt-btn hg-robot-save" data-hg-robot-save title="保存后立即用该机器人重连">保存机器人</button>
            </div>
          </div>
          <div data-hg-login-on style="display:none">
            <div class="hg-pop-row"><span data-hg-login-name class="hg-login-userlabel">已登录</span><button class="hg-pop-logout" data-hg-logout-btn title="登出（不影响机器人）">登出</button></div>
          </div>
        </div>
      </div>
      <div class="hg-main">
        <div class="hg-top">
          <span class="hg-cwd lv-btn" data-hg-cwd title="会话项目目录"></span>
          <span class="hg-title" data-hg-title>新会话</span>
          <span class="hg-flex1"></span>
          <span class="hg-vis-ind" data-hg-visind style="display:none"></span>
          <span class="hg-top-state" data-hg-state></span>
        </div>
        <div class="hg-flowwrap">
          <nav class="hg-rail" data-hg-rail aria-label="回合导航（ZCode 同款快速跳转）"></nav>
          <div class="hg-flow" data-hg-flow></div>
          <button class="hg-jumpbtm" data-hg-jumpbtm title="跳到最新消息" aria-label="跳到最新消息"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v14"/><path d="M5 12l7 7 7-7"/></svg></button>
          <button class="hg-dyn-capsule" data-hg-dyncaps title="会话动态：点开分屏动态页 / 动态页激活时再点收起（子代理运行中点按直达实况）" style="position:absolute;top:10px;right:14px;z-index:7;display:inline-flex;align-items:center;gap:7px;padding:4px 12px;border-radius:999px;">
            <span class="hg-caps-dot"></span>
            <span class="hg-caps-st" data-hg-caps-st>就绪</span>
            <span class="hg-caps-dur" data-hg-caps-dur></span>
            <span class="hg-caps-ag" data-hg-caps-ag></span>
            <span class="hg-caps-ctx" data-hg-caps-ctx></span>
          </button>
        </div>
        <div class="hg-card-wrap">
          <div class="hg-queue" data-hg-queue style="display:none"></div>
          <div class="hg-quote" data-hg-quote style="display:none">
            <span class="hg-quote-tag">引用</span>
            <span class="hg-quote-body" data-hg-quote-body></span>
            <button class="hg-quote-x" data-hg-quote-x title="取消引用">✕</button>
          </div>
          <div class="hg-atts" data-hg-atts style="display:none"></div>
          <div class="hg-input-card">
            <div class="hg-ask-dock" data-hg-askdock></div>
            <div class="hg-card-head">
              <button class="hg-proj" data-hg-proj title="选择项目目录（新会话直接在该目录下打开）">${ICO16.folder} <span data-hg-projname>选择项目</span> ▾</button>
            </div>
            <div class="hg-input-stack">
              <div class="hg-input-overlay" data-hg-overlay aria-hidden="true"></div>
              <textarea name="hg_input" class="hg-input" data-hg-input rows="1" placeholder="给 Claude 发消息，@ 引用文件，/ 选择技能 · 可直接粘贴图片" spellcheck="false"></textarea>
            </div>
            <div class="hg-mention-drop" data-hg-mention style="display:none"></div>
            <div class="hg-card-foot">
              <button class="hg-chip hg-chip-ico" data-hg-att title="添加附件（文档会以路径给模型读取）">${ICO.plus}</button>
              <button class="hg-chip hg-chip-ico" data-hg-snip title="截图并标注（Snipaste 式框选/箭头/马赛克/文字；确认后自动挂为附件并复制剪贴板）">${ICO.camera}</button>
              <button class="hg-chip" data-hg-perm title="工具执行权限：自动执行（点击切换每次确认）">${ICO.shield}</button>
              <button class="hg-chip hg-chip-ico" data-hg-skill title="加载技能（插入 /技能名）">${ICO.zap}</button>
              <span class="hg-flex1"></span>
              <span class="hg-activity" data-hg-activity style="display:none"></span>
              <span class="hg-cost" data-hg-cost></span>
              <button class="hg-chip" data-hg-think title="思考深度（对新会话生效；等级越高思考越充分）">默认 ▾</button>
              <button class="hg-chip" data-hg-model title="选择模型（对新会话生效）">模型 ▾</button>
              <button class="hg-send" data-hg-send title="发送（Enter）" aria-label="发送">
                <svg class="hg-ic-send" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.4 21 12 4 4.6v5.5l10.6 1.9L4 13.9z"/></svg>
                <svg class="hg-ic-stop" viewBox="0 0 24 24" aria-hidden="true"><rect x="4.5" y="4.5" width="15" height="15" rx="3"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="hg-subpane" data-hg-subpane style="display:none">
        <div class="hg-sub-resizer" data-hg-subres title="拖拽调宽"></div>
        <div class="hg-sub-wrap">
          <div class="hg-sub-head">
            <div class="hg-sub-tabs" data-hg-subtabs></div>
            <button class="hg-sub-x" data-hg-subx title="收起窗格（手动打开的窗格回合结束不自动收起；收起后点消息流子代理行或面板条目可重开）">✕</button>
          </div>
          <div class="hg-sub-body" data-hg-subbody></div>
        </div>
      </div>
      <input type="file" data-hg-file multiple style="display:none" name="hg_file">
    </div>`;
  const es = termArea.querySelector('.empty-state');
  if (es) es.remove();
  tabs.insertBefore(tab, tabs.querySelector('.tab-bar-actions'));
  if (typeof _initTabDrag === 'function') _initTabDrag(tab);
  termArea.appendChild(_hgWrap);
  // 机器人凭据输入的 dirty 监听必须在 DOM 就位后立刻挂上——它由本模板
  // 动态注入，shell.js 模块级那轮 querySelectorAll 扑空；晚到的话首屏
  // status 失败时用户清空 App ID 的意图会被后续回填抹掉
  if (typeof hgRobotWire === 'function') {
    _hgWrap.querySelectorAll('[data-hg-robot-id]').forEach(hgRobotWire);
  }
  if (typeof hgEyeWire === 'function') {
    _hgWrap.querySelectorAll('[data-hg-eye]').forEach(hgEyeWire);
  }
  if (typeof hgSecretWire === 'function') {
    _hgWrap.querySelectorAll('[data-hg-robot-secret]').forEach(hgSecretWire);
  }
  // 登录条 DOM 随 tab 创建——创建后立刻拉一次登录态（页面加载时的首轮
  // 渲染发生在 DOM 存在之前，会扑空停在「未登录」默认态）
  if (typeof hgLoginRefresh === 'function') setTimeout(hgLoginRefresh, 150);
  // 开启 Claude 联动：确保重试代理在跑（无则后台拉起无 headroom 的轻量
  // 代理，30s 未就绪自动回退直连）。fire-and-forget，不阻塞 tab 打开。
  fetch('/api/proxy/ensure', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{"for_claude":true}' }).catch(() => {});
  if (typeof hgProxyRefreshState === 'function') setTimeout(hgProxyRefreshState, 300);

  _hgConn = {
    portId,
    meta: { kind: 'harness', label: 'Claude 对话', cwd: '' },
    tab, wrap: _hgWrap,
    sse: null, onResumePoll: null,
  };
  connections[portId] = _hgConn;
  _HG.conn = _hgConn;
  _HG.cache = {};
  _HG.atts = [];
  _HG.attsBy = {};   // v2.3.0：未发送附件按会话暂存（切走存/切回恢复，用户实锤丢图）
  _HG.sid = null;
  _HG.rowById = {}; _HG.uidN = 0; _HG.run = null;
  _HG.think = null; _HG.grp = null; _HG.histNav = null; _HG.mention = null;
  switchTab(portId);

  _hgQ = (s) => _hgWrap.querySelector(s);
  _hgFlow = _hgQ('[data-hg-flow]'), _hgInput = _hgQ('[data-hg-input]'),
        _hgAskDockEl = _hgQ('[data-hg-askdock]'),   // v3.4.61：ask 面板 dock（输入卡上方）
        _hgJumpBtm = _hgQ('[data-hg-jumpbtm]'), _hgRailEl = _hgQ('[data-hg-rail]'),
        _hgStateEl = _hgQ('[data-hg-state]'), _hgCostEl = _hgQ('[data-hg-cost]'),
        _hgSendBtn = _hgQ('[data-hg-send]'), _hgTitleEl = _hgQ('[data-hg-title]'),
        _hgCwdEl = _hgQ('[data-hg-cwd]'), _hgAttsEl = _hgQ('[data-hg-atts]'),
        _hgListEl = _hgQ('[data-hg-sessions]'), _hgSearchEl = _hgQ('[data-hg-search]'),
        _hgFileEl = _hgQ('[data-hg-file]'), _hgOverlayEl = _hgQ('[data-hg-overlay]'),
        _hgMentionEl = _hgQ('[data-hg-mention]'), _hgActEl = _hgQ('[data-hg-activity]');
  _hgRailBind();   // v3.2.10：轨道点击绑定（builder 内元素就绪后）
  // v3.5.296（用户实锤「两个会话都在活跃，但看不出来该会话活跃」）：会话行
  // busy ● 只在 SSE 特定时机随 refreshSessions 重渲——非当前会话的 busy
  // 变化根本不触发列表刷新。10s 周期对账（本地亚秒级接口，开销可忽略），
  // 配合行首 spinner（renderList）让活跃态可见
  setInterval(() => { try { refreshSessions(); } catch (_) {} }, 10000);
  // v2.24 大会话 DOM 卸载（见 _hgFlowUnloadInit）：切走 tab 快照清空、切回恢复
  _HG.flowEl = _hgFlow;
  _HG.flowSnap = '';

  // v3.4.67（用户实锤「如果我已经在底，所有输出都必须渲染到底」）：粘底跟读。
  // 旧判据「渲染后量距 >150px=在看历史」有个致命时序：Edit/MultiEdit diff 卡
  // 生而展开一次 append 数百 px，渲染后量距必超 150——贴底跟读被误判成看
  // 历史，从此每条增量都不再拽底（用户被甩下，手动滚才能跟上）。改 scroll
  // 事件维护粘底标志（滞后带防抖：<120 置真 / >150 置假，中间保持）——渲染
  // 前的贴底状态被记住，渲染后无条件拽底；用户真翻上去（>150）才放权，拉回
  // 底部（<120）自动恢复跟随。
  _HG.stickBtm = true;
  // v3.4.69e（用户实锤「F12 没反应」）：WebView2 无 DevTools——页面内诊断
  // 系统。全局环形日志（最近 60 条，时间+标签+消息），顶栏 ⓘ 钮点击弹出。
  // 重建/重渲/审计/自愈全路径埋点，替代控制台排查切回丢失问题
  _HG.diag = [];
  window._hgDiag = function(tag, msg) {
    try {
      var t = new Date();
      var ts = ('0' + t.getHours()).slice(-2) + ':' + ('0' + t.getMinutes()).slice(-2) + ':' + ('0' + t.getSeconds()).slice(-2);
      (_HG.diag = _HG.diag || []).push('[' + ts + '] ' + tag + ' · ' + msg);
      if (_HG.diag.length > 60) _HG.diag.shift();
    } catch (_) {}
  };
  _hgDiag('boot', (window._HG_VER || 'v?') + ' 会话页构建完成');
  // v3.5.0+（用户拍板「harness 版本与工具版本分离」）：静态 _HG_VER 仅首屏
  // 兜底，启动即拉单一源覆盖（bump 只改 src/harness/__init__.py 一处）；
  // 工具发版版本（APP_VERSION）一并取回供 ⓘ 双行显示
  fetch('/api/harness/version').then(r => r.json()).then(j => {
    if (!j || !j.ok || !j.harness) return;
    window._HG_VER = 'v' + j.harness;
    window._APP_VER = j.app || '';
  }).catch(() => {});
  // a628（用户令「harness 的这个完全由 log 系统取代，ⓘ 标记可以删了」）：
  // 顶栏 ⓘ 诊断按钮删除——职能由后端 log 系统取代（启动行打 harness+工具
  // 双版本，流水经 console hook/worker 回传进 backend_log）。_hgDiag 环形
  // 缓冲与版本 fetch 保留（其余埋点/_HG_VER 消费者仍依赖）。
  // a271（性能追踪实锤：滚动 handler 同步读 scrollHeight/scrollTop → 419 次
  // Layout 中 262 次被滚动事件强制同步触发 = 翻页一卡一卡真身）。rAF 合帧：
  // 读几何挪进 requestAnimationFrame（与渲染同帧合并，多次 scroll 一帧只算一次）
  let _scrollRaf = 0;
  _hgFlow.addEventListener('scroll', () => {
    if (_scrollRaf) return;
    _scrollRaf = requestAnimationFrame(() => {
      _scrollRaf = 0;
      if (_HG.noScroll) return;   // 历史重建的程序性 scrollTop 写入不污染粘底态
      const gap = _hgFlow.scrollHeight - _hgFlow.scrollTop - _hgFlow.clientHeight;
      if (gap < 120) _HG.stickBtm = true;
      else if (gap > 150) _HG.stickBtm = false;
    });
  });
  _hgScrollBottom = (force) => {
    if (_HG.noScroll) return;   // v2.16：历史重建期间不滚（几百行逐行 append 会反复重排）
    // v2.20：用户翻上去看历史时不抢滚动条（用户实测「看之前思考时 AI 一回复
    // 就被拉到最下面」）。force=true（自己发消息、切会话回底）不受限。
    // v3.4.67：粘底跟读优先——stickBtm（渲染前在底）时无条件拽底，大块渲染
    // 把底推远也不再误判；仅用户真翻上去（scroll 判 >150 置假）才回旧判据。
    if (!force && !_HG.stickBtm &&
        _hgFlow.scrollHeight - _hgFlow.scrollTop - _hgFlow.clientHeight > 150) return;
    _hgFlow.scrollTop = _hgFlow.scrollHeight;
    // 布局二次兜底：活动指示条弹出/气泡内图片加载等会在同帧稍后改变 flow 高度，
    // 下一帧再滚一次，保证"发送后我的消息在底部"（v2.5 用户反馈修复）
    requestAnimationFrame(() => { _hgFlow.scrollTop = _hgFlow.scrollHeight; });
  };

  // ==================== 交互式提问卡片（v2.17）====================
  // 模型调 mcp__harness__ask_user → 后端 emit kind:'ask' → 这里渲染成可点选项。
  // 提交后 POST /ask/answer，后端唤醒阻塞中的 MCP 工具调用，模型拿到选择继续。

  // 卡片状态存在 dataset 而非 JS 属性：切走再切回走的是 innerHTML 快照路径
  // （_HG.cache），元素被重建、JS 属性全丢，但 dataset 随 HTML 一起回来。
  // 这与 v2.12 把抽屉开合委托化是同一个坑。

  // 每题作答齐备判定：选项选中 or 自由输入有内容（v2.24.3 输入也算作答）

  // 点击选项（flow 委托调用）：单选置换、多选切换


  // 用户提交后定稿卡片：显示已选、禁用交互

  // ==================== markdown / 代码块 ====================
  // v2.24 懒高亮：代码块进视口才增强+高亮（IntersectionObserver 单例，滚到
  // 哪亮到哪；懒抽屉点开时其内容也经此通道——挂在视口内的即刻触发）
  _codeIO = null;

  // ==================== 附件 chip / 图片预览 ====================

  // ==================== 过程抽屉（v2.7：非回答过程全部收进折叠抽屉）====
  // v2.11：双抽屉——「思考」（thinking 段）与「执行」（工具调用）各一个，
  // 都靠 AI 侧（左）对齐放 AI 气泡上方；busy 且 AI 尚未输出文本时，思考
  // 抽屉组头动画显示「AI 正在思考中…」，回复结束才定稿收尾。
  // v2.12：抽屉开合改为 flow 级事件委托——innerHTML 快照恢复（切会话再切回）
  // 不丢监听器；多个抽屉各自独立开合互不影响。
  // ==================== 抽屉/工具展开状态的持久化 ====================
  // 用户诉求：关掉 tab 再打开历史会话，「思考/工具展开情况不能丢」。
  // 同一 tab 内切走再切回走 innerHTML 快照，DOM 状态本来就保真；关 tab 后
  // 只能按 transcript 重建，默认值全会复位。v3.2.1：位置键开合记忆已整体
  // 退役（跨代际同键碰撞误开新行，用户实锤「终端默认全部不收起」；详见
  // 03-ask-md.js _hgLoadOpen 注）——重建统一默认收起，用户点开过的经快照
  // dataset（userToggled）忠实保留。hg-open:<sid> 仓仅剩 sub:<agentId>
  // 语义键（agentId 稳定，不受扩段/收缩重渲的行号漂移影响）。
  // 动机（v2.46 原始记录）：扩段/收缩是全量重渲，renderHistSub 建段恒默认
  // 折叠，用户已展开的段被收回——不只是观感，段区高度突变直接破坏扩段锚
  // 定精度（Playwright 实测：展开态 8858px 重渲后自行收回 5931px，锚定落点
  // 漂 2900+px）。重建期由 renderHistSub 读取恢复。

  // ---- 消息组基元（v2.18）----
  // 组 = .h-grp{ .h-grp-proc{ .h-turn-head(已工作 Ns ›) + .h-turn-body{ .h-drawer.think
  // + .h-tl 工具时间线 } } + AI 气泡们 }（v3.2：ZCode 式回合闭合结构——工作区
  // 整体可收成一行「已工作 X」，正文永远可见；.h-drawer.exec 为 v3.1 前旧快照
  // 兼容形态）。
  // 每轮 renderUser 开新组，思考/工具归属自己的消息组（用户点名：所有思考
  // 挤一个抽屉里分不清是哪次思考、哪个消息触发的执行）。活状态（counts/
  // segCount/t0）存 dataset——innerHTML 快照恢复后 JS 属性全丢，dataset 随
  // HTML 回来（与 v2.12 userToggled 进 dataset 同一个坑的对策）。
  // 占位气泡：AI 消息泡未输出内容时的活泼文案轮换（用户明确要求，每轮独立）
  // v2.20（3.png）：切回 busy 会话后占位气泡复活。快照恢复的 grpFromDom
  // ph:null 不认 DOM 里的 ph 元素（timer 轮换永久丢失，文案冻结）；transcript
  // 重建的 renderUser(live=false) 压根不建 ph——两条路径切回「正在回复」的
  // 会话都看不到「AI 正在思考中…」。恢复条件收紧到尾部未定稿组且尚无正文，
  // 已有正文/已定稿的会话不补（避免凭空多出气泡）。
  // flow 级事件委托：抽屉组头/工具折叠行点击 → 只切自己
  // （v2.12 修「点一个全展开」+「切会话再切回后点不开」——innerHTML 快照恢复
  //   不丢监听器，每行每抽屉独立开合）
  // v2.24.3：提问卡片自由输入——输入即视为该题已作答（放行提交）；回车直接提交
  _hgFlow.addEventListener('input', (e) => {
    if (e.target.classList && e.target.classList.contains('h-ask-x')) {
      // v3.4.60：草稿写回 value attribute——innerHTML 快照才带得走（.value 是
      // DOM property 不序列化），切会话往返草稿不丢
      e.target.setAttribute('value', e.target.value);
      const card = e.target.closest('.h-ask');
      if (card) askCheckDone(card);
    }
  });
  _hgFlow.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('h-ask-x')) {
      e.preventDefault();
      const card = e.target.closest('.h-ask');
      const sb = card && card.querySelector('.h-ask-submit');
      if (sb && !sb.disabled) askSubmit(card.dataset.hgAsk);
    }
  });
  // v3.4.61：ask 面板 dock 委托三件套（dock 在 _hgFlow 外，flow 委托物理收不到
  // ——队列条 :1030 同款容器自绑；快照恢复 innerHTML 不丢监听器）。
  // flow 上的原 ask 分支保留作老代卡安全网（老快照 pending 卡迁移后已入 dock，
  // 纯老 done 卡仍在 flow）
  if (_hgAskDockEl) {
    _hgAskDockEl.addEventListener('click', (e) => {
      const aPg = e.target.closest('.h-ask-pgv');
      if (aPg) { const c = aPg.closest('.h-ask'); if (c) askPage(c, parseInt(aPg.dataset.hgPg || '0', 10)); return; }
      const aOpt = e.target.closest('.h-ask-opt');
      if (aOpt) { askPick(aOpt); return; }
      const aSend = e.target.closest('.h-ask-submit');
      if (aSend) { askSubmit(aSend.dataset.hgAskSend); return; }
      const aIgn = e.target.closest('.h-ask-ignore');
      if (aIgn) { askSubmit(aIgn.dataset.hgAskSend, true); return; }
    });
    _hgAskDockEl.addEventListener('input', (e) => {
      if (e.target.classList && e.target.classList.contains('h-ask-x')) {
        e.target.setAttribute('value', e.target.value);   // 草稿随 innerHTML 快照走
        const card = e.target.closest('.h-ask');
        if (card) askCheckDone(card);
      }
    });
    _hgAskDockEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('h-ask-x')) {
        e.preventDefault();
        const card = e.target.closest('.h-ask');
        const sb = card && card.querySelector('.h-ask-submit');
        if (sb && !sb.disabled) askSubmit(card.dataset.hgAsk);
      }
    });
  }
  function _hgFlowClick(e) {
    // 批2（迁出主窗）：段头/结论行/段内行三分支退役——主窗零 .h-subblock，
    // 子过程唯一入口=单行卡（agRow 分支）+胶囊/目录（各自入口）；旧快照
    // 残留的段 DOM 由批3 switchTo 剥离，不在此兼容
    // v2.35（P0-2）：子代理消息行/工具行点击 → 重开实时窗格并切到对应
    // tab（✕ 收起后同一子代理还在跑时的重开入口；窗格已开=切 tab）
    // v2.35.1（F1/F7）：行内交互子元素放行——折叠头(.h-tool-head 展开/收起)、
    // 复制钮(.h-tool-copy 与气泡内 .hg-code-copy)、折叠体(.h-tool-coll)是
    // 既有交互（v2.12 起委托在此链后段），不得被整行重开劫持
    const subRow = e.target.closest('[data-hg-sub]');
    if (subRow && !e.target.closest('.h-tool-head, .h-tool-copy, .h-tool-coll, .hg-code-copy')) {
      _subReopen(subRow.dataset.hgSub); return;
    }
    // 批3（迁出主窗）：协作回传通知行点击 → 开对端窗格（转写全量；miss 走漏斗）
    const ntRow = e.target.closest('.h-sub-notify[data-hg-peer]');
    if (ntRow) { _subReopen(ntRow.dataset.hgPeer); return; }
    // v2.35（P1-5）：「已转交」线点击 → 说明（线只标记转交本身——协作过程
    // v2.47 起聚在紧随其后的「协作 · …」段，点段头「▣ 回放」可围观；回传
    // 以 📥 气泡呈现）
    if (e.target.closest('.h-switch[data-peer]')) {
      // v2.37R6：stale 线点击给核实口径
      const swp = e.target.closest('.h-switch[data-peer]');
      if (swp.dataset.stale === '1') {
        showBanner('该等待线超 30 分钟未回传，疑似残留——回传若到达会自动定格', 3200);
        return;
      }
      // v3.5.160（v3.5.159 引入、本轮修订）：id 形态 peer（=真实 agentId）点击直达该
      // 子代理全链回放（原 Task+历次续派同文件天然全链）。v3.5.160 全审F6：
      // 名字形态撤 peerSent 反查——键域歧义（同名多收信方反查到首个任意
      // 包装 tid，跳错档案比不跳更糟），落回说明 banner（段头回放走完整
      // 解析漏斗，身份可靠）；识图/真跨会话协作同走 banner
      const _peer = swp.dataset.peer || '';
      if (/^[0-9a-zA-Z_-]{8,64}$/.test(_peer)) {
        _subReplay('peer:' + _peer, 'SendMessage',
          (typeof _peerDesc === 'function' ? _peerDesc(_peer, '') : '')
            || ((_HG.peerNames || {})[_peer] || _peer.slice(-6)), _peer, true);
        return;
      }
      showBanner('此线只标记转交——协作过程聚在下方「协作」段（段头「▣ 回放」可围观），回传到达将归入其协作段', 3200);
      return;
    }
    // v3.5.233b（自测矩阵实锤「点归档条进不去只读」）：快照恢复的归档条
    // 无 onclick（innerHTML 序列化不带事件）——改 flow 级事件委托，无论
    // hint 来自渲染器还是快照恢复都可点
    const _arch = e.target.closest('.h-archive-hint');
    if (_arch) {
      document.dispatchEvent(new CustomEvent('hg-ro-enter'));
      return;
    }
    // v3.5.161（用户需求「后台任务点不开，看不到在执行什么」）：任务卡点击
    // → v3.5.182 回退：该分支调用的 _taskOutToggle 已随后台任务功能整体
    // 回退（c806f01）不存在，点击即抛 ReferenceError——分支整体移除
    // 交互提问卡片（v2.17）：选项点击 / 提交
    // v3.4.60（ZCode 方案）：多题分页翻页——必须排在 done 折叠分支之前，
    // 否则展开回看时点翻页会被折叠 toggle 吞掉
    const aPg = e.target.closest('.h-ask-pgv');
    if (aPg) { const c = aPg.closest('.h-ask'); if (c) askPage(c, parseInt(aPg.dataset.hgPg || '0', 10)); return; }
    // v3.3.2(D8)：已提交 ask 卡点击开合——折叠态看摘要，点开回看选择情况
    // （pgr=分页器区域排除：点「1/2」数字不触发折叠）
    const _aDone = e.target.closest('.h-ask.done');
    if (_aDone && !e.target.closest('.h-ask-opt') && !e.target.closest('.h-ask-pgr')) { _aDone.classList.toggle('collapsed'); return; }
    const aOpt = e.target.closest('.h-ask-opt');
    if (aOpt) { askPick(aOpt); return; }
    const aSend = e.target.closest('.h-ask-submit');
    if (aSend) { askSubmit(aSend.dataset.hgAskSend); return; }
    const aIgn = e.target.closest('.h-ask-ignore');
    if (aIgn) { askSubmit(aIgn.dataset.hgAskSend, true); return; }
  // a115R（用户实锤「刷新后展开仍 10fps 级卡顿」）：重内容跳过 max-height
  // 动画——展开动画期间重体内容每帧全量布局（content-visibility 只救
  // 「不相交」的折叠态，动画中相交救不了）。
  // a120Q（用户实锤「思考/bash 展开掉帧没解决」）：旧判据读 body.
  // scrollHeight——两个坑：①折叠体在 CV 估高下恒 240px 占位（真高从未
  // 布局），1600px 阈值**从未触发过**＝跳动画一直空转；②实测该读在
  // 「流内已物化内容多」的状态下付一次全流强制布局（56-86ms 的展开
  // 卡顿直接来自这行）。改判**内容文本量**（textContent 是 DOM 属性，
  // CV/布局双盲区免疫，零强制布局）：>6k 字符≈展开体 >1600px 即重卡
  // 直达开合。selector 含 .h-turn-body：回合体 grid 1fr→0fr 过渡展开=
  // 百级工具行逐帧物化，同判同治（host 传组元素，no-anim 由 CSS 后代
  // 选择器命中体内）
  function _hgHeavySkip(host) {
    if (!host) return;
    const body = host.querySelector(
      '.h-turn-body, .h-tool-coll, .h-drawer-body, .h-think-seg-body');
    if (!body) return;
    let heavy = false;
    try { heavy = (body.textContent || '').length > 6000; } catch (_) {}
    // a120R（新档案实锤「轻卡展开还是有点卡」）：展开动画期间卡高度逐帧
    // 变化 → .h-tl flex 容器每帧重走 flex 算法（LayoutNG 逐子测量）——
    // 档案里动画帧 Layout 42-46ms×2/帧，与卡内容大小无关（241 字符的小卡
    // 一样 25fps），纯容器规模税。主时间线（.h-tl 直系子行）或所在查阅组
    // （.h-tl-grp-body——组在主 tl 内，组内卡展开同样逐帧重走外层）行数
    // >80 即不播动画
    if (!heavy) {
      try {
        const tl = host.closest('.h-tl');
        const gb = host.closest('.h-tl-grp-body');
        heavy = (tl && tl.childElementCount > 80)
             || (gb && gb.childElementCount > 80);
      } catch (_) {}
    }
    if (!heavy) return;
    host.classList.add('no-anim');
    requestAnimationFrame(() => requestAnimationFrame(() => {
      host.classList.remove('no-anim');
    }));
  }
  const dHead = e.target.closest('.h-drawer-head');
    if (dHead) {
      const box = dHead.closest('.h-drawer');
      if (box) {
        if (!box.classList.contains('open')) _hgHeavySkip(box);
        box.classList.toggle('open');
        box.dataset.userToggled = '1';       // 写进 DOM——快照恢复后依然记得用户碰过
        // v3.2.1：撤 _hgSaveOpen 位置键持久化（跨代际碰撞误开新行，用户定调
        // 重建统一默认收起）；开合在当前 DOM 生命周期内有效
      }
      return;
    }
    // 思考段条目（v2.18）：段头点击 → 只切该段（开=懒渲染填 / 合=丢弃清空）
    const sHead = e.target.closest('.h-think-seg-head');
    if (sHead) {
      const seg = sHead.closest('.h-think-seg');
      if (seg) {
        const opening = !seg.classList.contains('open');
        if (opening) { _histLazyFill(seg); _hgHeavySkip(seg); } else _histLazyDrop(seg);
        seg.classList.toggle('open');
      }
      return;
    }
    // v2.21：段尾右下角「收起 ⌄」→ 收该段（读完整段后原地收，不用滚回顶部）
    const sFold = e.target.closest('.h-think-seg-fold');
    if (sFold) {
      const seg = sFold.closest('.h-think-seg');
      if (seg) { _histLazyDrop(seg); seg.classList.remove('open'); }
      return;
    }
    // 代码块/Bash 命令复制钮（v2.12 委托化——快照恢复后行内绑定会失活）。
    // v2.44R：本分支必须在 .h-tool-head 分支之前——段内抽屉的复制钮是 head
    // 内的 span，后置会被 head 开合分支先截走（点了变开合不变复制）
    const cp = e.target.closest('.hg-code-copy, .h-tool-copy');
    if (cp) {
      // 复制内容就近取：代码块取同容器 pre>code 文本；Bash 行取 .h-tool-arg 文本
      const codeBox = cp.closest('.hg-code');
      // v3.5.249：open 态优先取折叠体内的 .h-tool-arg——hist 行头部 arg 是
      // slice(0,80) 真截断，复制必须取体部 summary 全文；live 行体部无 arg
      // 自然回落行首（live arg 本就是全文）
      const _cpBox = cp.closest('.h-tool');
      // a63：体部候选加 .h-tool-cmd（bash 命令纯文本 pre 全文）——否则
      // bash 复制回落行首摘要（80 字真截断，v3.5.249 同坑）
      const _cpArg = (_cpBox && _cpBox.classList.contains('open')
        && _cpBox.querySelector('.h-tool-coll .h-tool-arg, .h-tool-coll .h-tool-cmd'))
        || (_cpBox && _cpBox.querySelector('.h-tool-arg'));
      const txt = codeBox ? codeBox.querySelector('pre > code')?.textContent.replace(/\n$/, '')
        : _cpArg && _cpArg.textContent;
      if (txt) copyText(txt).then(ok => {
        if (ok) { const orig = cp.textContent; cp.textContent = '✓';
          setTimeout(() => cp.textContent = orig, 1500); }
      });
      return;
    }
    // v3.2：回合折叠头（已工作 X ›）——点开/收起整段工作区（思考+时间线）
    const tnHead = e.target.closest('.h-turn-head');
    if (tnHead) {
      const proc = tnHead.closest('.h-grp-proc');
      const body = proc && proc.querySelector('.h-turn-body');
      if (body) {
        // a120Q：回合体开合=百级工具行的 grid 过渡逐帧物化（大会话最重的
        // 展开卡顿）——重体跳动画（textContent 判，展开前体还在场）
        if (body.classList.contains('closed')) _hgHeavySkip(proc || body);
        body.classList.toggle('closed');
        tnHead.dataset.userToggled = '1';
        if (!body.classList.contains('closed')) {
          // 展开时懒回填顺带触发（组内折叠行仍各自懒加载，这里只管布局态）
          _hgScrollBottom();
        }
        // a120P：回合体开合=组高巨变（百级工具行）——开合动画（grid 1fr→0fr
        // 过渡 300ms）落地后重钉该组 CV 估高种子，防下次反物化→物化时按
        // 旧种子再修一帧（滚动条跳变）
        const _gp = proc && proc.closest('.h-grp');
        if (_gp && typeof _hgPinIntrinsicHeights === 'function')
          setTimeout(() => _hgPinIntrinsicHeights(_gp), 420);
      }
      return;
    }
    // v3.2：查阅聚组头（🔍 查阅 · N 搜索 · M 文件）——切换子行树开合
    // v3.2.1：撤 _hgSaveOpen 位置键持久化——键按 DOM 位置索引链编，跨代际
    // （回滚截断/扩段窗移/v3.1↔v3.2 结构差）同键指向不同元素，旧记录误开
    // 新行还误标 userToggled（用户实锤「终端默认全部不收起」）。开合只在
    // 当前 DOM 生命周期内有效，重建统一默认收起（用户定调）
    const expHead = e.target.closest('.h-tl-grp-head');
    if (expHead) {
      const grpEl = expHead.closest('.h-tl-grp');
      if (grpEl) {
        const opening = !grpEl.classList.contains('open');
        grpEl.classList.toggle('open');
        grpEl.dataset.userToggled = '1';
        if (opening) grpEl.querySelectorAll('.h-tool').forEach(_histLazyFill);
        else grpEl.querySelectorAll('.h-tool').forEach(_histLazyDrop);
      }
      return;
    }
    // v3.2：oneclick 工具行（Bash 终端卡）——整行点击展开/收起输出
    // v3.2R1(P1)：输出体（.h-tool-coll）内的点击不折叠——展开后用户要在
    // 输出文本里点选/定位，整行命中会把卡片收起来打断选词
    const ocRow = e.target.closest('.h-tool.oneclick');
    if (ocRow && !e.target.closest('.h-tool-coll')) {
      const opening = !ocRow.classList.contains('open');
      // a120R（用户实锤「bash 展开还是卡」）：oneclick 专属通道漏挂
      // heavy-skip——bash 终端卡全走本分支且早退，tHead 分支的跳动画
      // 永远轮不到；大会话巨时间线（flex 逐帧重走）里 bash 卡动画照样
      // 25fps。补挂同款判定（textContent>6k 或时间线>80 行=直达开合）
      if (opening) { _histLazyFill(ocRow); _hgHeavySkip(ocRow); }
      else _histLazyDrop(ocRow);
      // v3.4.88：识图卡展开时懒填折叠体（完整 prompt+回传全文——不入
      // _histLazyFill 的 hi/raw 账，独立体）
      if (opening && ocRow.classList.contains('h-vision')) _hgVisionFillBody(ocRow);
      ocRow.classList.toggle('open');
      return;
    }
    // v3.2.6（ZCode 子智能体模式）：单行任务卡（.h-tool.agentline）——整行
    // 点击=开右侧窗格（live 实况 / 已结束回放），不再折叠展开（对照 ZCode
    // canToggle=false 产品边界：过程细节统一在窗格时间线查看）
    // v3.2.6R2（审计F1+用户实锤）：agentId 三源兜底——agents 档案 → 行自带
    // hgSubr → 面板回放档（agentsRpl 按 type+desc 匹配）
    // v3.2.31（bug5② 终态兜底）：全 miss 不再只弹 banner（用户实锤「点了没
    // 反应」）——打开子智能体目录 tab（常驻伪 tab，任何状态必有可见响应），
    // banner 降为目录内的辅助提示。任何子代理行点击必开窗格
    const agRow = e.target.closest('.h-tool.agentline');
    if (agRow) {
      const pid = agRow.dataset.tid || '';
      // v4.0.1（用户硬性要求「无条件能点开任意子代理」）：原先只在档案
      // （_HG.agents[pid]）存在时才走 _subReopen，档案缺失就直接弹
      // 「没有 agentId 记录」——但 _subReopen 自己就有完整漏斗
      //（regSync 重查 → 后端 subagent_resolve 扫转写）。档案缺失恰恰是
      // 最需要该漏斗的场景，此处却提前放弃，等于把可救的行判死。
      // 改为**无条件**进漏斗：行上有 tid 就一定尝试解析到真实 agentId。
      if (pid) { _subReopen(pid); return; }
      let aid = agRow.dataset.hgSubr || '';
      if (!aid) {
        const _ty = agRow.dataset.hgSubType || '', _ds = (agRow.dataset.hgSubDesc || '').slice(0, 40);
        const _hit = (((_HG.dyn || {}).agentsRpl) || []).find(r =>
          r && r.agentId && (r.type || '') === _ty && String(r.desc || '').slice(0, 40) === _ds);
        if (_hit) { aid = _hit.agentId; agRow.dataset.hgSubr = aid; }
      }
      // 批2（迁出主窗）：点击统一收敛 _subReopen（内含 done/running 分诊
      //（_subReplay/_subReplay(force,alive)）+miss 时 regSync→resolve 漏斗）
      if (aid) { _subReopen(aid); return; }
      _subDirOpen();
      showBanner('该子代理行没有 taskId/agentId——已打开子智能体目录，可从列表进入', 3000);
      return;
    }
    const tHead = e.target.closest('.h-tool-head');
    if (tHead) {
      const row = tHead.closest('.h-tool');
      if (row) {
        const opening = !row.classList.contains('open');
        if (opening) { _histLazyFill(row); _hgHeavySkip(row); } else _histLazyDrop(row);
        row.classList.toggle('open');
      }
      return;
    }
    // 附件图片 chip → Lightbox
    const img = e.target.closest('[data-img]');
    if (img) openLightbox(img.dataset.img);
    // v3.1h：用户消息复制（原文，含 markdown 源）
    const uc = e.target.closest('.h-ucopy');
    if (uc) {
      const m = uc.closest('.h-msg.user');
      // v3.1h(F6):纯图消息 rtext 为空——取气泡渲染文本(占位文案),不复制空串
      const ut = (m?.dataset.rtext || '').trim() ||
                 ((m?.querySelector('.h-bubble') || m)?.textContent || '').trim();
      Promise.resolve(copyText(ut)).then(okFlag => {
        if (!okFlag) return;   // v3.1h(F5):复制失败不亮 ✓
        uc.textContent = '✓';
        setTimeout(() => { uc.innerHTML = ICO16.clipboard; }, 900);
      });
      return;
    }
    // v2.22：用户消息重发（气泡右上刷新钮）——同内容再走一遍发送管线
    const rb = e.target.closest('.h-resend');
    // v3.5.51：只读模式无变更类操作（重发/编辑走输入态，RO 内拦截）
    if (rb && _HG.readonly) { showBanner('只读模式下不能重发', 2000, true); return; }
    if (rb) {
      const m = rb.closest('.h-msg.user');
      let atts = null;
      try { atts = JSON.parse(m?.dataset.ratts || 'null'); } catch(_) {}
      const text = m?.dataset.rtext || '';
      if (_HG.busy) queuePush({ text, images: atts?.images || [], files: atts?.files || [] });
      else dispatch(text, atts?.images || [], atts?.files || [], true);
      return;
    }
    // v3.1h：AI 消息复制（渲染后纯文本走剪贴板）——hover 下方浮现的 📋
    const cb = e.target.closest('.h-acopy');
    if (cb) {
      const m = cb.closest('.h-msg.asst');
      const t = ((m?.querySelector('.h-bubble') || m)?.textContent || m?.dataset.rtext || '').trim();
      if (!t) return;   // v3.1h(F6):无可复制内容不动作
      Promise.resolve(copyText(t)).then(okFlag => {
        if (!okFlag) return;   // v3.1h(F5):复制失败不亮 ✓
        cb.textContent = '✓';
        setTimeout(() => { cb.innerHTML = ICO16.clipboard; }, 900);
      });
      return;
    }
    // v2.22：编辑后重发——原文与附件填回输入框，改完正常发送
    const eb = e.target.closest('.h-edit');
    // v3.5.51：只读模式拦截（编辑后重发属变更态）
    if (eb && _HG.readonly) { showBanner('只读模式下不能编辑重发', 2000, true); return; }
    if (eb) {
      const m = eb.closest('.h-msg.user');
      let atts = null;
      try { atts = JSON.parse(m?.dataset.ratts || 'null'); } catch(_) {}
      _hgInput.value = m?.dataset.rtext || '';
      _hgInput.style.height = 'auto';
      _hgInput.style.height = Math.min(_hgInput.scrollHeight, 200) + 'px';
      renderOverlay(_hgInput.value);
      _HG.atts = [];
      (atts?.images || []).forEach(p => _HG.atts.push(
        { name: String(p).split(/[\\/]/).pop(), path: p, size: 0, isImg: true }));
      (atts?.files || []).forEach(p => _HG.atts.push(
        { name: String(p).split(/[\\/]/).pop(), path: p, size: 0, isImg: false }));
      renderAtts();
      _hgInput.focus();
      _hgScrollBottom();
    }
  }
  // v3.5.50：click 委托绑定（handler 提取为命名函数——只读层 RO flow 复用同款交互）
  _hgFlow.addEventListener('click', _hgFlowClick);
  // 组定稿（result / 新一轮 renderUser / 正文切组）：徽章 + 未手动碰过时自动收

  // ==================== 气泡基元 ====================
  // ==================== v2.24.5 微信式时间条 ====================
  // 距上一条时间 >5 分钟才插（微信同款），插在触发消息前；格式分级：
  // 今天 HH:mm / 昨天 HH:mm / 今年 M月d日 HH:mm / 跨年 yyyy年M月d日。

  // _hgEchoDup（user_echo 兜底去重）：纯 ZCode 式下乐观渲染退役，本判重
  // 的原始动机（快照里已有乐观气泡，重放 echo 双画）随之消失——但保留为
  // 通用防线：与最后一条用户气泡同文同附件=已画过（任何来源的重复 echo，
  // 如重放窗边界，仍被拦）。
  // v2.37（P1-C）：头像色板哈希——纯 CSS 语义变量（--hgd-*/--accent），零写死
  // 色零外部资源；同名恒同色（按首字符 charCode 取模）

  // ==================== v2.43 子代理会话段（主 flow 化）====================
  // 用户定调：子代理的会话要和主会话一样——有气泡、有思考、有工具调用，
  // 段头标「头像名+角色 · 模型」；子代理的操作不再整合进主会话的组统计
  // （组头胶囊只剩主链动作；Agent 派发卡本身仍属主链）。
  // 段是 flow 里的结构化容器（.h-subblock），挂当前主组根内——派发后主链
  // 续写的内容 append 在段之后，时序不乱；段不参与主链组管线（grpFinalize/
  // 回滚锚点/grpEnsure 回扫均不感知段）。段的 DOM 即持久源：innerHTML 快照
  // 携带全部行与 dataset，切回按 data-hg-subblock 认回（内存档丢失不重建）。
  // v2.43.1（R-FAIL1/次要③）：段认回——DOM 里有段则建档 + 回收段内工具行
  // id 映射。不新建、不重启计时、不改状态（认回语义中性）；段不在返回 null。
  // 供 _subBlkGet / 完成信号兜底 / 快照重扫共用。
  // 段头绘制：头像（取色字符=类型优先，同型恒同色）+「角色 · 模型」+悬浮说明
  // ==================== v2.45 子代理段两层收纳 / v2.48 时序节 ====================
  // 用户实测（CDP）：主 flow 2419 节点中两个子代理段占 1788（74%），每轮协作
  // +800~1000 节点线性涨；段内「思考/Bash/思考/Bash…」交替平铺不像主会话的
  // 「思考+工具收纳」。两层收纳：
  //   第一层：完成段默认折叠——段体（head 以下）收起，只留段头 + 结论行
  //   （.h-subblock-sum，最后一条 text 前 120 字灰小结）；点段头/结论行 toggle，
  //   展开态段头右侧「▣ 回放」「⧉ 窗格」小按钮走原窗格动作；运行中段也可
  //   手动收起（后台继续跑，秒表照走）。
  //   第二层（v2.48 重设计）：段体**按时序切节**——用户实锤 v2.45「全段两类
  //   各一大抽屉」丢失时序（回放窗格有时序、主窗口段没有），定调「和主会话
  //   一样！思考+工具和会话气泡联系起来」。节（.h-subsec）=两次 text 气泡
  //   之间的过程行聚合：连续 thinking 行进「💭 思考 N 次」抽屉 + 其后连续
  //   tool/result 行进「⚡ 工具 M 次」抽屉，两抽屉并列节内（思考在前）；
  //   text 气泡独立节间（打断当前节），下一 think/tool 开新节——节序=时序，
  //   与主会话「组=思考抽屉+执行抽屉+正文气泡」同构。运行中即逐节成形
  //   （实时追加进「当前节」=body 最后一个 .h-subsec，无节则新建），不再
  //   等完成一次性聚合。
  // 铁律：段 DOM 是唯一持久源——节结构（.h-subsec/抽屉节点）与折叠态
  // （.collapsed 类 + CSS）都随 innerHTML 快照携带；旧 v2.45 两抽屉快照与
  // 平铺快照恢复时由 _subSecNormalize 按行序重排为节结构（幂等）；折叠
  // display:none 不影响 DOM 操作，运行段实时追加照常。
  // 节内抽屉（cls='think'|'exec'）：缺则建（思考抽屉排在工具抽屉前——节的
  // 规范形态是先思考块后工具块；复用主链 .h-drawer 样式语言）
  // 节计数徽章 + 空抽屉隐藏（与主链 grpFromDom「空壳胶囊不显示」同语义；
  // 思考抽屉体孩子全是 .h-think-seg、工具抽屉体 .h-tool/.h-tool-res 都算次）
  // 当前开放节：body 最后一个孩子若是 .h-subsec 即当前节（text 气泡在节后
  // 落 body 尾，天然断节——下一行再走本函数时最后孩子是气泡，开新节）；
  // 否则新建节落 body 尾。「追加进当前节」与「text 断节」由此一对位置规则
  // 闭环，无需额外状态位
  // 段头右侧动作钮（v2.47 需求1：不限完成段——运行段也画；数据源=段头
  // dataset：hgSubr=回放、hgSub=实况窗格）。hgSubr 在实时路径由
  // _subBlkFinish 后补（协作段建段即落）——补后需重画（幂等）。钮态由
  // dataset 自决：协作段无 hgSub 不画窗格钮（无实况流）、未落 hgSubr 无回放钮
  // 节化落点路由：think/tool 行进当前节的对应抽屉并刷新计数；text/note 落
  // body 尾（气泡=节间边界）。实时 SSE、历史 renderHistSub、轮询全喂三路共用
  // 段体节化归一（幂等）：三种历史形态 → 节结构。
  // ① v2.45 两抽屉快照（body 直子 .h-drawer.sub）：抽屉行按 v2.45 自身呈现序
  //   （先思考块后工具块、气泡在后）抽出平铺到体首，再走②；交错序在该形态
  //   落盘时已丢，重排只保呈现序不变（不编造）。
  // ② 平铺行（v2.44 运行快照/上一步产物）：按 body 子序遍历，连续 think/tool
  //   行就地裹进节（节插在该行原位置——时序精确），text/note 原地断节。
  // ③ 已节化：无动作。节结构是此后唯一增量形态，②只会来自旧快照。
  // 段体聚合入口（_subBlkState done 语义唯一调用）：确保结论行/箭头/动作钮
  // 铁件在位 + 节化归一。v2.48 运行期已逐节成形，这里对节化体是幂等空转；
  // 旧快照恢复后完成（认回路径不经过 _subSecNormalize 的兜底）由此补齐
  // 段头运行态 + 秒表（子代理一跑几分钟，主流不动——秒表是「还活着」的判据；
  // 与主链 Agent 派发卡的秒表同源职责）。计时器自守：段 DOM 脱离 flow 即停
  // 段头定格（Task tool_result / task_notification / 历史段）：✓/✗ + 用时。
  // 不依赖窗格 tab 存活（tab 被上限逐出/✕ 关闭都不断档）。
  // v2.44：用户定调「完成的话，记录完成用时」——t0（段建时刻，认回恢复后
  // 为真实起点）→ 定格时刻的时长随状态落文案；历史段（b.hist，无真实 t0）
  // 标「历史」不编造数字；t0 缺失（认回已完成段）只显状态
  // 段内活动思考段收口（时长定格）。段边界=段内下一条非思考行（与主链
  // endThinking 的调用点对偶，但只关段内自己的段，不碰主链 _HG.think）
  // ---- 段内行（实时路径；历史 sub_* 行的构建逻辑同源复用）----
  // v2.44：段内折叠行工厂——用户实锤段内形态割裂（Read/Grep 单行无展开体、
  // Bash 展开带全文），定调段内一律「默认收起一行：图标+名+摘要+状态徽章
  // [+耗时]，点开看输入详情/结果全文」。text 行保持气泡（没被否定）。
  // 抽屉头构建与历史段行（renderHistSub）共用本函数——两条路径的头结构
  // 字节级同源，快照/认回/委托都零特判
  // 实时段内工具行：不管 cfg 是 one-line 还是 collapsible 都进抽屉（主链行
  // 不受影响，沿用各自形态）。body 初始放输入详情；结果到达由 _subToolResult
  // 追加进折叠体——「点开才展开」展开的就是输入+结果全文
  // v2.44：col 类工具的输入详情体（主链 col 分支与段内抽屉共用，避免两处
  // 维护 diff/todo/question/md 四种渲染口径）
  // 段内思考段壳工厂：实时（_subThink，流式计时）/ 历史（renderHistSub，
  // hi 懒渲）/ 回填（_subBlkMergeThinks，raw 懒渲）三路同构——差异只在
  // dataset（t0/hi/raw），结构零分叉（快照/委托/样式都吃同一形态）
  // 思考：段内思考段（.h-think-seg.sub，同主链分段结构/折叠交互——flow 级
  // 委托天然覆盖段内段头/收起钮）。v2.44 默认收起（用户原话「思考…也压成
  // 抽屉，点开才展开」）。数据源（v2.46 起）：SSE 不转发子代理 thinking
  // （实测落盘 146 块上流 0 块）——实时思考由 .output 增量轮询喂入本函数，
  // 完成回填（_subBlkMergeThinks）兜轮询未起跑的段
  // v2.55R：窗格思考行工厂（镜像与 _subFeed 共用——两处内联必然漂移）
  // v2.57R：窗格工具行工厂——折叠气泡（头行=状态点+工具名+摘要，点开才
  // 显示输入/结果详情，与思考行同交互）；tuid 供结果回点、done 定格
  // v2.55：轮询喂入的思考/文本同步镜像到实况窗格 tab（tab 存在才镜像）——
  // SSE 不转发子代理 thinking/text，旧窗格只剩工具行（用户实锤「窗格只有
  // 工具」）；协作段窗格钮放开后此处是窗格全量数据的增量来源
  // 文本：段内 md 气泡（归属已在段头，行内不再重复头像/徽章）
  // 工具行入段（renderToolUse 的 isSub 分支调用——行本体仍由 renderToolUse
  // 构建，保证与主链工具行同构，只是落点从主链执行抽屉改到段体）
  // 段内工具结果：徽章+耗时进头部，结果全文进折叠体（成功默认藏、错误自动
  // 展开——与历史段行/主链错误口径一致）。v2.44：旧版只亮徽章、错误补行外
  // 挂文本，段内点开也看不到结果全文——用户定调「点开才展开」展开的必须
  // 是详情+结果，不再是「成功只亮徽章」
  // v2.28.16：「回滚」按钮授予（用户定调三连，终版语义）：按钮挂在
  // 【每个定下来的 AI 回合的最后一条消息】上——回合完成（result）授予，
  // 之后不摘（每个回合边界都是合法回滚点；生成中的回合没有按钮）。
  // can-rewind 类随 innerHTML 快照序列化；点击走 flow 级事件委托——
  // 快照克隆丢 onclick 的既有解法（同 h-macts）。
  // v2.28.12：回滚后重拉转写重建消息流（丢弃的回合从界面消失）
  // v2.20：模型切换分割线（会话内换模型即时生效的可见反馈）
  // v2.27.23：超窗续命分割线——[系统] 历史注入后台化的可见标记（一行带过）
  // v2.34：审计警示气泡——light 形态回合结算审计的可见出口（warn 档唯一
  // 动作；auto 档续发补审指令时也先出这条）。红色居中卡片，区别于用户/
  // AI 气泡与灰色 raw 行：这是 harness 的裁决信息，用户必须知情。回放路径
  // （role='audit' 行）与实时（kind='audit' 事件）共用，切会话形态一致。
  // v2.27.3：识图/跨会话协作的过程可见性（用户定调：全程要有反馈）——
  // 转交 = 分割线；回传 = 专属气泡。原实现回传内容直接被丢弃（user 事件
  // 只处理 tool_result），结论"凭空消失"，只有主会话转述才可见。
  // v2.28.3：定格指定识图分割线（多调用并发时 peerWait 单槽不够用——
  // 每条线按 tool_use_id 对应自己的元素，各自定格互不干扰）
  // v2.35：定格时落 data-done（epoch ms）——面板「协作代理」行与输入框
  // 「等待协作回传」态都从线的 dataset 派生，随 innerHTML 快照序列化
  // v2.28.3：回合终结（result/中断/进程退出）仍未回传的识图线——停表并
  // 标注，不让秒表空转到天荒地老
  // v2.28：识图 MCP 转交线历史回看——静态渲染（后端已算好 dur），无计时器
  // v2.35.1（观察项补齐）：与实时线同构落 dataset（peer/t0/done/psum）——面板
  // 「协作」行与输入框等待态对两条路径一致。历史行一律定格：dur 有值用真实
  // 完成时刻（t0+dur，60s 窗自然滤掉旧行）；无值=历史未完成，不冒充在等
  // v2.3.2：等待计时器独立函数——快照恢复（switchTo innerHTML 重建）后
  // 原 interval 已死、计时冻结在快照时刻；恢复路径对未定格线重挂 interval。
  // v2.35.2（P1 多槽）：计时器挂线元素（d._peerTimer）——每条线独立停/走，
  // 重挂防叠（快照恢复连点/重复恢复场景）；_HG.peerWait 仍指向最新一条
  //（识图 sweep 等旧调用方的兼容单槽）。
  // v2.35.2（P1 多槽）：停单条线的计时器（并释放指向它的 peerWait 单槽）
  // v2.35.2（P1 多槽）：定格单条转交线（文案/耗时/dataset，面板与等待态收口）
  // v2.35.2（P1 多槽）：回传到达按**协作方名**配对定格——回传事件只有发信方
  // 名（renderPeer 的 name / 代播的 from-name），与转交线的 data-peer（收信
  // 方名）同名对上；同名多条按 FIFO 取最早未定格；无匹配退最早未定格
  //（与旧单槽行为等价的兜底）。交错时序（relay1,relay2,peer1,peer2）自此
  // 各对各的线，不再串。
  // v2.37R6（陈旧 pending 自愈）：①兜底复核——回合终结时对仍 pending 的
  // 线批量核实其 peer 转写是否存在 final result：有=定格「已回传」，无=
  // 标「状态未知」而非永久「等待中」；②显示上限——pending 超 30 分钟在
  // 秒表 tick 里标 stale（疑似残留），停表防无限秒表误导。均落 dataset
  //（随快照序列化，切会话往返不复发）。
  // v2.49：协作段定位——回传全文入段的第一步。四锚合并（SendMessage 续派的
  // 段 pid 有两个键域：实时段=CLI 包装 tool_use_id、历史段（后端
  // _inject_subagent_blocks 经 resumedAgentId 注入）=真实 agentId——单查必漏，
  // 必须双源）：
  // ① 段头 data-hg-subr===name：实时协作段建段即落（peerSent 反查真实 id）、
  //    完成段 _subBlkFinish 补落、历史段恒落——三路同键（真实 agentId）
  // ② peerSent 映射反查：to===name 的键=包装 tool_use_id → 段 data-hg-subblock
  //    （实时键域，快照恢复后 peerSent 已丢但段 DOM 在，由①③④兜）
  // ③ pid 直配 .h-subblock[data-hg-subblock=name]（历史键域：name=真实
  //    agentId 时命中后端注入段）
  // ④ .h-subblock[data-hg-collab] 段名文案全等 '协作 · '+name 前 24 字
  //    （名字形态——实时建段 label 用 to 原文，name 与 to 同名即中）
  // 识图名显式 return null——识图转交/回传形态原样保留（需求唯一例外）。
  // 多候选取舍：未完成（运行中段优先承接）> data-hg-collab > DOM 序
  // v2.49：回传全文落段体尾——结论行覆写「📥 回传：…」（与 _subText 同截断
  // 口径：前 120 字 + title 400；折叠态段体不可见时回传摘要仍露在段头下），
  // 段体尾追加 tag 行 + md 气泡。全程 textContent/mdBubble，无 innerHTML 拼
  // 接用户串（回传正文是对端会话产物，按不可信输入处理）
  // v2.49R1（复审2）：fullFeed 段（SendMessage 续派全喂持久标记）完成 drain
  // 会把转写全部 text 喂进段——含对端最后一条 text，它与本路回传正文同源
  // 同文；直接追加=同文双份。入段前比对段体尾最后一个 .h-msg.sub（renderMd
  // 确定性渲染，两路 textContent 归一后等价即同文）——等价则原位包裹复用
  // 该气泡（不追加第二份，保留其一）；不等价照常追加
  // v2.20：压缩过程动态分割线。CLI 只给「开始/结束」两个信号，没有进度
  // 百分比——给真实信息：耗时秒表 + 被压缩的上下文规模，不编假数字。

  // ==================== 历史重建（切回会话时按 transcript 行还原气泡/抽屉）====
  // v2.16：从 switchTo 里抽出来，并补上 thinking 行——history 里的「思考过程」
  // 抽屉此前完全丢失（后端 transcript_for 不产出，前端也不认 role='thinking'）。
  // v2.18：重建与流式走同一条路径（renderUser(live=false) / startThinking /
  // endThinking / renderHistTool）——旧 renderHistThinking 把一轮多段 thinking
  // 合并进一个 holder 的分叉删掉，思考分段两条路径一致。
  // v2.43：历史子代理段行渲染。sub_open 建段（历史段恒 done——jsonl 里
  // 出现即已完结）；其余行进段体。段头数据后端注入（agent/type/model/desc），
  // 点击段头开回放窗格（与面板回放入口同源同款）。

  // ==================== v2.24.1 气泡视口化（已回退）====================
  // 曾实现「壳+滚入渲染/滚出销毁」，但 renderUser/renderAsst 承担组管线边界
  // （定稿/开组/asstText 判定），壳化绕过管线 → 思考/工具挂错组。正确性
  // 优先回退；未来重做必须保留管线调用、只懒填 bubble 内容。
  // v2.24 懒抽屉：展开时按 dataset.hi 从 _HG.histAll 取原始数据现渲染
  // （快照恢复后 dataset 仍在、histAll 同生命周期在——两条路径都成立）。
  // 用户定调「闭合即丢弃」：收起时清空 body 并重置懒标记——开才消耗、
  // 合即零占用（反复开关重渲染单段 markdown ~几十 ms，可接受）。
  // v2.43.2（R2-缺口A/限制B）：懒填行点校验——行角色/归属与行所在容器对得
  // 上才允许填。覆盖边界（与 _histPrefixFp 互补）：指纹只保 [0..histStart)
  // 不可见前缀的中插变更；可见窗口（尾 50 行）内的塌缩/插入不动前缀，旧
  // dataset.hi 对新 histAll 仍会错位——本校验在填错之前拦下。

  // ==================== thinking 分段条目（v2.18：用户点名重写）====
  // 旧版一轮所有 thinking 挤一个抽屉正文里，分不清哪次思考；
  // 现在每段 thinking 一个可折叠条目（.h-think-seg），组头统计「思考 N 次」。
  // 段边界：text / tool_use 块到来（handleEvent 里 endThinking，调用点不变）。
  // 段起始时间存 seg.dataset.t0——快照恢复后可续算，JS 属性会丢。
  // ==================== v2.27：后台回复后切回，焦点不在最新回复 ====================
  // 根因：切走 tab 后容器 display:none，后台 SSE 照常收事件渲染，但
  // display:none 容器里 scrollBottom 全部失效（scrollHeight=0，scrollTop 写
  // 不进）——切回时视口停在离开瞬间的偏移，而内容已长出一大截。修法：
  // MutationObserver 盯容器 style（正是 switchTab 翻 display 的位置），
  // 离开时记下是否贴底，切回时若贴底强制回底一次（双 rAF 等 display:flex
  // 生效、布局回填后再滚，否则又算出 0 尺寸）。翻历史中切走的不拽底。
  _hgLeftNearBottom = false;
  new MutationObserver(() => {
    if (_hgWrap.style.display === 'none') {
      _hgLeftNearBottom = isNearBottom();
    } else if (_hgLeftNearBottom) {
      _hgLeftNearBottom = false;
      requestAnimationFrame(() => requestAnimationFrame(() => _hgScrollBottom(true)));
    }
    // a272（用户实锤「打开终端再切回 claude 导轨立即异常」）：claude 容器
    // display:none 期间 layout 全部归零——切回瞬间 _hgRailActive 的 offsetTop
    // 二分全读到 0/stale 值，act 判定错乱（贴底特判也可能读到旧 scrollHeight）。
    // 切回显示后双 rAF（等布局回填）重算一次活动刻度
    if (_hgWrap.style.display !== 'none') {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        try { _hgRailActiveRaf(); } catch (_) {}
      }));
    }
  }).observe(_hgWrap, { attributes: true, attributeFilter: ['style'] });
  // 活动思考段组头状态：本组尚无 AI 正文时脉动「思考中…」，其余实时计时
  // v2.18.1：组级判据（全局 asstText 在正文切组后语义漂移——新组思考该重新脉动）
  // 段头计时文案（_hgFmtDur）

  // ==================== 工具调用渲染（源 toolConfigs + ToolRenderer + BashCommandDisplay）====================



  // 连续同名工具分组（源 toolGrouping.ts：run≥2 → 折叠为一行 ×N + preview）。
  // 流式场景 tool_result 事件只往已有行上挂状态、不新增行，所以 run 的边界
  // 是"新视觉元素"：文本/thinking 块、异名或折叠类工具、用户消息、result。
  // 分组成员（第 2 个起）不单独渲染，其结果状态聚合到组头（错误显红）。


  // 工具结果挂接（源 shouldHideToolResult：成功藏、错误永远显）


  // ==================== 活动指示（源 ActivityIndicator）====================
  // v2.19：原来它是一条独立的横栏，杵在输入卡上方（带边框、停止钮），用户
  // 点名「这个栏不要了」——改成输入卡底部行里的一个小胶囊，和上下文环并排。
  // 停止钮一并删除：右下角那颗圆钮本就是停止态（setBusy 已切成 ■ + stopGen），
  // 同一动作两个入口，留着只是噪音。
  let _actWordIdx = 0;
  // v2.7：压缩等特殊状态覆盖活动词（word=null 恢复轮换）

  // ==================== 上下文用量环（v2.3 问题4：替代金额显示）====================
  // v2.16 口径修正：旧实现把 result 事件 usage 的 input+cache_read+cache_creation
  // +output 相加当作「上下文用量」，但那算的是**本轮消耗量**——cache_read 是缓存
  // 命中的读取量，一轮十几万属正常且便宜，多轮对话里它必然累积撞满窗口，于是
  // 环恒为满环、橙色警示恒亮（用户实测标题「上下文 5941.0K / 200.0K tokens（100%）」,
  // 5941K ≈ 本会话 30 轮的 Σ）。一个恒满的指标等于没有指标。
  // 真正该表达的是「离上限还有多远」= 最近一轮喂进模型的输入总量
  // （input + cache_read + cache_creation；output 是产出，不占输入窗口）。
  // 窗口取 modelUsage.<model>.contextWindow（CLI 权威值），缺失回退 256K。
  // 切回旧会话/重开 tab 时 result 事件不重放，故按 sid 持久化恢复。

  // v2.20：每轮结束（result/interrupted/exit 任意原因）拉一次真实上下文用量。
  // v2.21：改为 5s 定时轮询（用户要求实时刷新）——后端 /ctx 是 jsonl 尾部
  // 1MB 倒扫，单次几毫秒，5s 一次无性能感；生成中 jsonl 也在流式落盘，
  // 能看到上下文实时增长。页面隐藏时跳过、上一请求未回时不再叠加。
  _hgCtxInFlight = false;
  setInterval(() => { if (!document.hidden) _hgCtxPoll(); }, 5000);

  // busy 自愈（a142 复装·v4 版）：事件丢失/竞态让 _HG.busy 与后端脱节时
  // 5s 轮询会话列表纠偏（v2.26 原版；其 `!_HG.sse` 门在 v4 下恒死随批G
  // 删除，对抗审 P3-3 裁定恢复安全网——门改为 v4 投影 store 在场，只读
  // 期/无会话期照旧不跑）
  setInterval(() => {
    if (_HG.readonly) return;
    if (document.hidden || !_HG.sid || !_HG.v4Cur) return;
    fetch('/api/harness/sessions').then(r => r.json()).then(j => {
      if (!j || !j.ok) return;
      const s = (j.sessions || []).find(x => x.sid === _HG.sid);
      if (s && !!s.busy !== _HG.busy) setBusy(!!s.busy, s.busy_since);
    }).catch(() => {});
  }, 5000);

  // ==================== CLI 事件 → 渲染 ====================

  // ==================== SSE ====================

  // ==================== 会话切换 ====================
  // ==================== v2.24 滚动窗口式历史加载（大会话 DOM 瘦身）====================
  // 根因（对照实验闭环）：大会话数千条消息全量渲染 → 数万 DOM 节点，即便
  // harness tab 切走（display:none）仍拖累渲染进程（内存/GC）——所有拖动
  // （文件拖入/命令库排序/tab 换位）卡 ~12s；空会话不卡、关 tab 恢复。
  // 方案（用户定调：省 + 流畅第一）：恢复会话只渲染尾部 HIST_PAGE 条；
  // 上滑到顶自动扩一段；拉回底部自动收缩回尾部段——DOM 恒定 1~2 段。
  // 扩/收都从新起点全量重渲（renderHistLine 顺序敏感：thinking/工具归组依赖
  // 时序，prepend 乱序会组错乱），扩段锚定滚动、收缩回贴底。
  // v2.43.1（R-FAIL3）/ v2.43.2（R2）：histAll 前缀指纹——[0..n) 行的
  // role/text/agent 长度滚动哈希。主链转写是尾追加，但三类中插变更会移动
  // 既有索引：①子代理段 stub 塌缩（「最近 3 段全量」窗口随新派发后移，
  // 早前全量段缩成单行段头）②审计警示卡按 ts 并入（v2.34.1 既有机制）
  // ③他窗回滚截断。快照恢复沿用旧 DOM 的 dataset.hi/histStart 账目，遇
  // 中插变更即错位。
  // 覆盖边界（三层互补）：本指纹只保 [0..histStart) 不可见前缀——恢复拉
  // 取后比对，不符→非忙碌整体重渲自愈，忙碌降级（弃 histAll+histStale 哨
  // 兵随快照，下次恢复强制重渲）；可见窗口（尾 50 行）内的塌缩不动前缀，
  // 由 _histLazyLineOk 懒填点校验兜底（填错之前拦下）；降级态下的懒填走
  // 同款指纹/stale 校验，绝不喂错位账目。

  _histBusy = false;   // 重渲期间防 scroll 重入
  // v2.37R4（DOM 收缩）：增量摘头——目标保留尾部 HIST_PAGE 行。按行尾戳
  // （dataset.hEnd，_histRender 逐行落）划组：无戳孩子属于下一个带戳孩子
  // （同一条线的先导元素），整组同进退。无任何戳（旧快照 DOM）=安全放弃。
  // 视口用 scrollHeight 差回锚 scrollTop——可见内容一个像素都不动。
  // 账目联动：histStart 同步前移（saveCache 存的就是收缩后的窗口值，
  // rewind 双钳制不受影响）；扩段（上滑）仍走 _histRefresh 全量重渲，
  // 账目由 _histRender 重建，往复互逆不漂移
  // v2.25：只拉 transcript 存 histAll、不重渲——快照恢复路径补数据用
  // （切会话时 histAll 被清防串会话，快照里「已点开」的懒段要补填就得有数据）
  // v2.24.11 扩/收缩前必须重拉 transcript：histAll 是切会话时拉的快照，
  // 流式期间的新消息（用户刚发的+AI 回复）不在里面——直接用旧快照重渲会
  // 把它们从界面上抹掉（用户实测「消息突然没了」；jsonl 完好=纯显示层丢失）
  // v3.2.8：一键跳底——离底浮现的浮动钮，点击直跳 flow 底（贴底即触发
  // 既有增量收缩，DOM 顺带瘦身；瞬时跳：长距离 smooth 滚动慢且晕）
  if (_hgJumpBtm) _hgJumpBtm.onclick = () => {
    _hgFlow.scrollTop = _hgFlow.scrollHeight;
    _hgJumpBtm.classList.remove('show');
  };
  // v3.5.172（用户澄清）：上滑自动扩段不需要——更早历史的唯一入口是顶部
  // 「前 N 轮已归档」条 → 点击进只读模式（全历史都在那里看）。主流保持
  // 最近 20 回合，轻且稳
  // v2.28.16：回滚按钮事件委托——按消息文本锚点回滚（每个定下的回合边界
  // 都可回滚到那里）。按钮 innerHTML 随气泡生成/随快照克隆，直绑 onclick
  // 会丢（同 h-macts 既有解法），flow 级委托一次永在
  async function _hgFlowClick2(e) {
    // v3.5.11：超长用户消息折叠切换——委托绑一次（快照恢复 onclick 不
    // 序列化），按钮文案随态换（▾ 展开 / ▴ 收起）
    const fbtn = e.target.closest('[data-hg-fold]');
    if (fbtn && _hgFlow.contains(fbtn)) {
      e.stopPropagation();
      const host = fbtn.closest('.h-msg.user.longfold');
      if (host) {
        host.classList.toggle('open');
        fbtn.innerHTML = host.classList.contains('open') ? '收起 ▴' : '展开全文 ▾';
      }
      return;
    }
    // v3.4.95（用户需求）：全部收起——所有回合折叠体（含活跃组）一口气
    // add('closed')；定稿组本就收着，实际生效的是用户展开过+当前活跃组
    const _cbtn = e.target.closest('[data-hg-collapse]');
    if (_cbtn && _hgFlow.contains(_cbtn)) {
      e.stopPropagation();
      let _n = 0;
      _hgFlow.querySelectorAll('.h-grp .h-turn-body').forEach(tb => {
        if (!tb.classList.contains('closed')) { tb.classList.add('closed'); _n++; }
      });
      if (_n) showBanner('已收起 ' + _n + ' 个工作区', 1600);
      return;
    }
    const btn = e.target.closest('[data-hg-rewind]');
    // v3.5.51：只读模式拦截回滚（历史查看态严禁变更操作）
    if (btn && _HG.readonly) { showBanner('只读模式下不能回滚', 2000, true); return; }
    if (!btn || !_hgFlow.contains(btn)) return;
    e.stopPropagation();
    if (_HG.busy) { showBanner('AI 正在回复，结束后再回滚', 2400, true); return; }
    if (!_HG.sid) { showBanner('当前没有活动会话', 2000, true); return; }
    const host = btn.closest('.h-msg.asst');
    // v3.4.40：只有回合末结论（can-rewind 授予）可回滚——中间正文无资格，
    // 防 hover 显条/其它路径误触把过程中之后的全部截断
    if (!host || !host.classList.contains('can-rewind')) return;
    const anchor = host && host.dataset.rwa;
    if (!anchor) { showBanner('这条消息没有回滚锚点', 2400, true); return; }
    btn.disabled = true;
    try {
      const r = await fetch('/api/harness/rewind', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: _HG.sid, anchor})});
      const j = await r.json();
      if (!j.ok) { showBanner('回滚失败：' + (j.err || '未知'), 3600, true); return; }
      showBanner(j.msg, 3600);
      // v4-only：回滚换代走 epoch——不再跑 V3 重渲链，携水位强制重订阅让
      // 服务端裁决 snapshot 接管（换代提示行由后端 emit 落新 feed，随快照到达）
      var _c = _HG.v4Cur;
      if (_c && _c.sid === _HG.sid && !_c.store._closed) {
        _c.store._forceSnapshot = true;
        _c.store._scheduleReconnect();
      }
    } catch(err) { showBanner('回滚失败：' + err, 3000, true); }
    btn.disabled = false;
  }
  // v3.5.50：同上（async 变更类 handler）
  _hgFlow.addEventListener('click', _hgFlowClick2);
  // a271：rAF 合帧（同 236 行处追踪实锤——scroll 事件里同步读 scrollHeight
  // = 强制同步布局；本 handler 原 passive:true 只解掉了 preventDefault 警告，
  // 几何读仍逐事件同步。合帧后 60Hz 滚动每帧至多 1 次读）
  let _scrollRaf2 = 0;
  _hgFlow.addEventListener('scroll', () => {
    if (_scrollRaf2) return;
    _scrollRaf2 = requestAnimationFrame(() => {
      _scrollRaf2 = 0;
      // v3.2.8：一键跳底钮显隐——离底 >350px 浮现（任何渲染态都要刷新）
      if (_hgJumpBtm) {
        const _dj = _hgFlow.scrollHeight - _hgFlow.scrollTop - _hgFlow.clientHeight;
        _hgJumpBtm.classList.toggle('show', _dj > 350);
      }
      _hgRailActiveRaf();   // v3.2.10：轨当前项跟随视口
      // v2.35.2（P0 切会话信息丢失根因）：histLive 门（语义同前，详见 git 史）
      if (!_HG.histAll || !_HG.histLive || _HG.busy || _histBusy) return;
      const shown = _HG.histAll.length - _HG.histStart;
      // v3.2.12：扩段/收缩分支随分页退役——恒全量渲染（详见 git 史）
    });
  }, { passive: true });
  // v3.5.61（用户拍板「入口重复了，按钮不要」）：顶栏「📖 只读模式」按钮已撤
  // ——唯一入口=归档提示点击（04-groups 经全局事件转发，fc/fc2 闭包内私有）
  document.addEventListener('hg-ro-enter', () => {
    if (_HG.readonly || !_HG.sid) return;
    window.HgRO && HgRO.enter(_HG.sid, { fc: _hgFlowClick, fc2: _hgFlowClick2 });
  });

  // ==================== v2.3.11 只读模式（独立积木 harness-readonly.js）====================
  // ZCode 方案完整重构：默认只显结论，「已工作 Xs」总开关分级展开过程（思考/
  // 工具行二级折叠）。实现全部在 web/js/harness-readonly.js（window.HgReadonly），
  // 这里只做依赖注入薄适配——闭包助手打包传过去，零全局耦合。



  // v2.19：多模态判定（口径与后端 /models 的 mm 一致；会话列表打 👁 用）
  fetch('/api/harness/models').then(r => r.json())
    .then(j => {
      if (!j || !j.ok) return;
      _HG.models = j; renderList();
      // v2.20：预取回来时当前会话若已切入且 model=None（跑的是默认模型），
      // 补显示默认名——switchTo 时 _HG.models 可能还没到，chip 空过一次
      const s = _HG.sessions.find(x => x.sid === _HG.sid);
      const sm = (s && s.model) || j.default;
      if (sm && !_HG.model) {
        _HG.model = sm;
        _hgQ('[data-hg-model]').innerHTML = esc(sm) + ' ▾';
      }
    })
    .catch(() => {});

  // ==================== 会话列表 ====================

  // ==================== 消息排队（v2.20，参考 ZCode 交互）====================
  // 当前回复执行中继续输入 → 不再被「正在回复中」拦下，而是排进队列：
  // 输入卡上方出现排队条（⠿ 草稿缩略 + ↑立即 / ✎编辑 / 🗑删除），当前
  // 回复结束（result/interrupted → setBusy(false)）自动依序发送。
  // 队列按 sid 隔离，切会话各看各的。
  queueEl = _hgQ('[data-hg-queue]');
  // ==================== 引用消息（v2.27，微信同款）====================
  // 右键消息气泡 → 「引用」→ 输入卡上方出引用条（只读，✕ 取消）→ 发送时
  // 拼成「[引用 xx 的消息]…[我的问题]…」——引用内容随消息落转写，AI 能
  // 同时看到被引原文和用户新表达，历史回看也完整。
  quoteEl = _hgQ('[data-hg-quote]');
  quoteBodyEl = _hgQ('[data-hg-quote-body]');
  _hgQ('[data-hg-quote-x]').onclick = () => setQuote(null);
  // 右键消息气泡 → 迷你菜单（贴鼠标）。只做引用一项，克制。
  _hgFlow.addEventListener('contextmenu', (e) => {
    // 命中范围：正文气泡(.h-msg)，或右键思考/执行抽屉(.h-drawer)时落到
    // 所在消息组的 AI 正文——用户视角「右键这条回复」不分抽屉还是正文
    // v3.1h（用户实锤「离老远都能出现」）：只认右键命中正文气泡本身——
    // 组内思考段/工具行/空白不再回落引用首条 AI 正文
    const m = e.target.closest('.h-msg');
    if (!m || !_hgFlow.contains(m)) return;
    e.preventDefault();
    const old = _hgWrap.querySelector('.hg-ctxmenu');
    if (old) old.remove();
    const who = m.classList.contains('user') ? '我' : 'AI';
    // 用户气泡优先 dataset.rtext（发送原文，干净）；AI 气泡取正文——
    // clone 后剔除 button/抽屉钮等 UI 元素再取文本，避免混入「复制」等字样
    let text = (m.dataset && m.dataset.rtext) || '';
    if (!text) {
      const b = m.querySelector('.h-bubble');
      if (b) {
        const c = b.cloneNode(true);
        c.querySelectorAll('button').forEach(x => x.remove());
        text = c.innerText || c.textContent || '';
      }
    }
    text = (text || '').trim();
    if (!text) return;
    const menu = document.createElement('div');
    menu.className = 'hg-ctxmenu';
    menu.innerHTML = `<div class="hg-ctx-item" data-hg-ctx-quote>❝ 引用此消息</div>`;
    // v2.27.2：fixed 定位直接用视口坐标挂 body——之前 absolute 挂 flow 换算
    // 内容坐标，实测会随滚动/祖先定位飞走（用户截图菜单贴顶）。fixed 永远
    // 贴鼠标，与滚动无关（微信同款）。
    menu.style.position = 'fixed';
    menu.style.left = '0'; menu.style.top = '0';
    document.body.appendChild(menu);
    let x = e.clientX, y = e.clientY;
    if (x + menu.offsetWidth > window.innerWidth - 8) x = window.innerWidth - menu.offsetWidth - 8;
    if (y + menu.offsetHeight > window.innerHeight - 8) y = window.innerHeight - menu.offsetHeight - 8;
    menu.style.left = Math.max(4, x) + 'px';
    menu.style.top = Math.max(4, y) + 'px';
    menu.querySelector('[data-hg-ctx-quote]').onclick = () => {
      menu.remove();
      setQuote({ who, text });
    };
    const close = (ev) => {
      if (menu.contains(ev.target)) return;
      menu.remove();
      document.removeEventListener('mousedown', close, true);
      window.removeEventListener('resize', close, true);
    };
    setTimeout(() => {
      document.addEventListener('mousedown', close, true);
      window.addEventListener('resize', close, true);
    }, 0);
  });
  // v2.25：拖动排序状态。拖拽中挂起 renderQueue 重建——重建会把被抓住的
  // 元素从文档摘下，pointer capture 随之失效，拖到一半掉链子。
  qDrag = null;               // {from, i, after, item}
  // v2.25：排队条拖动排序。用 pointer 事件而非 HTML5 dnd——dnd 在 WebView2
  // 里要额外处理 drop 目标判定，pointer 直接按行中线算落点更稳。
  // 抓手是唯一拖动入口（data-i 标在抓手上，不靠 closest 反查，避免点到
  // 按钮时误判）。
  queueEl.addEventListener('pointerdown', (e) => {
    const grip = e.target.closest('.hg-q-grip');
    if (!grip || e.button !== 0) return;
    const item = grip.closest('.hg-q-item');
    if (!item) return;
    e.preventDefault();
    qDrag = { i: +grip.dataset.i, target: null, item };
    item.classList.add('dragging');
    grip.setPointerCapture(e.pointerId);
  });
  queueEl.addEventListener('pointermove', (e) => {
    if (!qDrag) return;
    const items = Array.from(queueEl.querySelectorAll('.hg-q-item'));
    let target = items.length;            // 默认落到末尾
    let after = false;
    for (let k = 0; k < items.length; k++) {
      const r = items[k].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { target = k; after = false; break; }
      target = k + 1; after = true;
    }
    if (target === qDrag.target && after === qDrag.after) return;
    qDrag.target = target;
    qDrag.after = after;
    items.forEach(x => x.classList.remove('drop-before', 'drop-after'));
    const ref = items[target];
    if (ref) ref.classList.add(after ? 'drop-after' : 'drop-before');
  });
  queueEl.addEventListener('pointerup', () => qEndDrag(true));
  queueEl.addEventListener('pointercancel', () => qEndDrag(false));
  queueEl.addEventListener('click', (e) => {
    const b = e.target.closest('[data-qact]');
    if (!b) return;
    const key = _hgQueueKey(), arr = _HG.queues[key] || [];
    const i = +b.dataset.i;
    if (i >= arr.length) return;
    // v3.1（#10）：队列条目操作全部走服务端账本（本地删只是乐观 UI，
    // input_discarded/input_promoted 事件会按 id 对账；无 id=POST 未返回
    // 的窄窗口，本地直接删，后端账本里它还在——事件晚到再对齐）
    // v3.4.78（用户实锤「编辑掉的测试1 复活在待发送区又被发出」）：
    // **原始 bug**——旧 _qact 在 splice 之后重读 arr[i]，读到的是被删条目的
    // 下一条或 undefined：单条队列 del/edit 空转不发（服务端条目残留→复活
    // →被泵发出，即用户 repro）、多条队列误发下一条的 id（静默误杀无辜
    // 条目）。作废可靠性三层修：①条目对象显式传参（不再按下标回读）；
    // ②POST 响应校验（非 ok/异常 → 指纹追杀兜底）；③指纹按 sid 分域
    // （30s 有效，cap 20），input_admitted 迟到回号时命中补杀（reducer
    // input_admitted 分支内联消费）
    const _qKillMark = (it) => {
      const fp = String((it && it.text) || '').slice(0, 200)
        .replace(/\s+/g, ' ').trim().slice(0, 80);
      if (!fp) return;
      _HG.qKill = _HG.qKill || {};
      const bag = _HG.qKill[_HG.sid] = _HG.qKill[_HG.sid] || [];
      bag.push({ fp, at: Date.now() });
      if (bag.length > 20) bag.shift();
    };
    const _qact = (act, it, extra, killFallback) => {
      if (it && it.id) {
        // v3.5.109：迁移 apiPost 统一写包装（失败 banner 义务化）
        apiPost('/api/harness/queue_act',
                Object.assign({ sid: _HG.sid, id: it.id, act }, extra || {}),
                { label: '队列操作失败' }).then(res => {
          if (killFallback && !res.ok) _qKillMark(it);
        });
      } else if (killFallback) {
        _qKillMark(it);   // 无 id 兜底（id 由 queuePush 同步预生成，常态不达）
      }
    };
    if (b.dataset.qact === 'del') {
      const it = arr.splice(i, 1)[0]; renderQueue();
      _qact('del', it, null, true);
    } else if (b.dataset.qact === 'edit') {
      const it = arr.splice(i, 1)[0]; renderQueue();
      _qact('del', it, null, true);
      _hgInput.value = it.text || '';
      renderOverlay(_hgInput.value);
      if ((it.images || []).length || (it.files || []).length)
        showBanner('附件不随草稿返回，请重新添加', 3000, true);
      _hgInput.focus();
    } else if (b.dataset.qact === 'now') {
      // v3.1：立即发送=提到队首+中断当前回合（后端回合终结泵自然先发它）
      const it = arr.splice(i, 1)[0];
      arr.unshift(it); renderQueue();
      _qact('now', it);   // v3.4.78：显式传条目（旧代码 splice 后回读 arr[i] 发错对象）
      stopGen();               // interrupted → 后端 _turn_end → 800ms 泵发队首
    }
  });
  // ==================== v2.32 会话动态（六分区监视器；v3.3 分屏化）====================
  // 设计文档 docs/设计_2026-09-20_右侧会话动态面板.md。监视器=纯派生：
  // 不持状态机，一切从 _HG + sessions + localStorage 派生；骨架 v3.3 起改为
  // 分屏伪 tab __dyn__ 懒建（14-subpane _subDynOpen，旧 index.html 静态节点/
  // #aiPanel 换装形态整体废止）——dynEl 在 _subDynOpen 里赋值，此处不绑。
  // 事件驱动 rAF 合并全量重渲；秒表是全局单例 interval 只改 textContent。
  _hgRolesCache = null;   // 最近一次 /roles 响应（动态页三角色行与左侧按钮同源）

  // ---- 派生态与入口 ----
  _dynRaf = 0;

  // ==================== v2.35 运行派生态（P0-1②③ / P1-4 / P1-5）====================
  // 输入框/面板的「等待类」状态全部派生自已有事实（agents 档案 + 转交线
  // dataset），不另持状态机——快照往返后从 DOM 即可重建，零序列化负担。
  // v2.37（P1-E）：协作包装判定——CLI 对 SendMessage 委托的独立会话会包装
  // 成后台 Task（subagent_type 非本工具角色名）。后台 + 非角色类型一律按
  // 协作对待：不开实况窗格 tab（独立会话事件流不经过本会话，开了必是空白
  // tab），归面板 C 区协作行。宁可误杀真实后台通用代理的可围观性（罕见，
  // 主 flow 仍有灰行），不再伪装能点开实况。
  // （v2.53：「重」角标已按用户要求移除，_HEAVY_AGENTS 随之删除）
  // ---- P1-4：子代理模型名（起跑预显示；实跑模型由子代理 assistant 事件覆盖）----
  _agentModelsTried = false;         // 只拉一次（失败允许重试）
  // P0-2：手动重开子代理实时窗格（面板运行中条目 / 消息流子代理行点击入口）
  // v2.38：已完成且带 agentId 的代理 → 回放窗格（数据源转写，历史也能看）；
  // 切会话后档案丢失 → 提示语更新为回放口径
  // v2.37（P1-E）：摘除一个窗格 tab（协作包装误开/超限让位共用）——内容、
  // 序表、激活态一并清；最后一个 tab 顺带收起窗格

  // v2.39：详情卡构建抽纯函数——_dynAgents 重渲（秒表 tick/SSE 都触发
  // renderSideStatus）是 innerHTML 全量覆盖，插入在行后的详情卡每次都被
  // 冲掉（用户实锤「点击展开后不一会又缩回去」）。展开态记 dyn.agentDetailOpen，
  // _dynAgents 重建后按 id 恢复插回。
  // v3.3：动态页点击委托迁至 13-panel _hgDynClick（骨架随 _subDynOpen 懒建，绑定随骨架走）

  // ---- 渲染（分区独立重建，空区 hidden）----
  // v2.37（P0-B）：分区隔离——任何一区抛异常不再饿死后续区（旧实现单 rAF
  // 回调内顺序执行，首区异常=后面全部保持初始 hidden，「面板只剩 A 区」的
  // 形态）；异常落 console 带 [hg-dyn] 标记供现场取证
  // 秒级计时：全局单例 interval（闭包随 tab 重开重执行，直接 setInterval 会
  // 叠加）；仅分屏展开且动态页激活时可见才动（v3.3：旧 hg-mode 守卫随换装废止），且只改 textContent 不重建 DOM。
  if (!window._hgDynTick) {
    window._hgDynTick = setInterval(() => {
      // v2.37（P0-B/F③）：自愈先于可见性守卫（v3.3 改分屏口径）——①动态页
      // sc 被重建后 dynEl 失联（ detached 节点真值仍为真，渲染进死节点=动态
      // 页只见初始态）→ 重联重渲；②消息流里未定格转交线的秒表计时器丢失
      //（快照恢复遗漏/异常路径清掉）→ 按 dataset 重挂。两者都是每秒一次的
      // 廉价扫描。
      try {
        if (!dynEl || !dynEl.isConnected) {
          const nd = document.querySelector('[data-hg-dyn]');
          if (nd && nd !== dynEl) { dynEl = nd; renderSideStatus(); }
        }
      } catch(_) {}
      try {
        _hgPeerStaleSweep();   // v2.37R6：>30min 标疑似残留并停表
        _hgFlow.querySelectorAll('.h-switch[data-peer]:not([data-done]):not([data-stale]):not([data-unknown]), .h-tool.h-vision[data-peer]:not([data-done]):not([data-stale]):not([data-unknown])').forEach(rl => {
          if (!rl._peerTimer) _hgPeerTimerStart(rl, +(rl.dataset.t0 || 0) || Date.now());
        });
      } catch(_) {}
      // v3.2.31：胶囊计时秒表走字（先于可见性守卫——分屏收起时胶囊仍可见，
      // 其计时/脉冲必须活着）
      try { _hgDynCapsulePaint(); } catch(_) {}
      // v3.3 守卫改分屏口径：分屏展开且动态页激活才走字（胶囊 paint 在守卫前
      // 无条件执行，计时不受影响）；dynEl 并入守卫——动态页未建时不查
      if (document.hidden || !_subPaneEl || _subPaneEl.style.display !== 'flex'
          || _sub.active !== _SUB_DYN || !dynEl) return;
      dynEl.querySelectorAll('[data-t0]').forEach(el => {
        el.textContent = _hgFmtDur(Math.max(1, Math.round((Date.now() - +(el.dataset.t0 || 0)) / 1000)));
      });
      // 状态区活动词跟随（压缩等特殊词以 actEl 为准，面板同词）
      if (_HG.busy) {
        const src = _hgActEl.querySelector('[data-hg-aw]');
        const stEl = dynEl.querySelector('[data-hg-d-st]');
        if (stEl && src && src.classList.contains('hg-act-special')) stEl.textContent = src.textContent;
      }
    }, 1000);
  }
  // v3.3：_hgPanelEnterHook 随换装面板废止——roles/agentModels 拉取移到
  // _subDynOpen（用户点开动态页才拉，点击天然节流）
  renderSideStatus();                    // 闭包（重）执行完先刷一遍（如重开 tab 恢复现场）

  // ==================== v2.33 子代理实时窗格 ====================
  // 主会话派 Agent(dev/reviewer/executor…) 时，聊天区右侧自动弹出可调宽窗格，
  // 按 parent_tool_use_id 精确分流显示各子代理的实时文本/工具调用（并行多开
  // 分 tab）。定位：临时实时镜像视图——主 flow 的灰色 sub 行照旧保留（历史
  // 完整性不动），回合终结窗格收起（主 flow 是唯一持久记录处）。
  _subPaneEl = _hgQ('[data-hg-subpane]');
  _subTabsEl = _hgQ('[data-hg-subtabs]');
  _subBodyEl = _hgQ('[data-hg-subbody]');
  // a93（用户实锤「tab 多时只能手动拖滚动条」）：子窗格 tab 条滚轮横向
  // 滚动——滚动容器是父级 .hg-sub-head（overflow-x:auto）。无溢出/已到
  // 边时不吞滚轮（放行页面滚动）
  if (_subTabsEl) {
    _subTabsEl.addEventListener('wheel', (e) => {
      const sc = _subTabsEl.parentElement;
      if (!sc) return;
      const max = sc.scrollWidth - sc.clientWidth;
      if (max <= 0) return;
      const d = (Math.abs(e.deltaY) >= Math.abs(e.deltaX)) ? e.deltaY : e.deltaX;
      if ((sc.scrollLeft <= 0 && d < 0) || (sc.scrollLeft >= max - 1 && d > 0)) return;
      sc.scrollLeft += d;
      e.preventDefault();
    }, { passive: false });
  }
  // v2.35（P0-3）：manual=用户手动打开/重开的窗格——回合终结不自动收起，
  // 只有 ✕ 手动关；自动弹出的窗格（Task 起跑）保持原行为（回合终结收起）。
  // v2.38：历史子代理回放窗格——数据源是子代理自己的转写（独立 session
  // jsonl，经 /subagent_replay 按 agentId 取），不是内存事件流；切会话快照
  // 往返后内容随 DOM 保留，仍可重开重拉（源在转写，永远可重建）
  // v2.41：不可回放结论记忆（agentId 全局唯一作键）——found=false 即转写
  // 文件不存在（旧会话/被清理/跨会话协作），重拉永远同结果；记入本集后
  // 再点「回放该子代理过程」直接出示结论不发请求。同 tab 防重由既有
  // sc.dataset.replayed 承担（fetch 前写入、found=false 不清除即早退），本集
  // 补 tab 被上限逐出/_subDrop 后重开的场景（新 sc 无标记，否则会重拉）。
  // v2.42：后端已加新版 CLI tasks 转写兜底源，found=false 场景收窄但仍有
  // （转写被清理等），文案同步改中性不再断言具体原因
  // force=true：协作段「⧉ 窗格」路径——每次点击强制重拉全量（清防重标记），
  // 关掉再打开都有数据（用户实锤：途中关掉再开就空了）
  // 窗格重设计 P1-4：cap 删首不再静默——首删插「⬆ 已省略 N 行」提示条占住
  // 头部，其后每删一条只累进计数（不重复插）；提示条自身占 1 个行名额。
  // 回放路径 noCap 绕过本函数，语义不变
  // 窗格重设计 P1-3（复审勘误）：元素直挂的必要性只在懒高亮——
  // _codeLazyEnhance 的 IO observe 的是元素实例，字符串通道（outerHTML→
  // innerHTML 克隆）进 DOM 的新节点永不被 observe、永不增强。链接拦截不
  // 构成理由：renderMd 自身就 return t.innerHTML，直绑监听器每次渲染必丢
  // （与通道无关），窗格链接点击实际由 init.js 的 document 捕获阶段全局
  // 拦截器兜底。窗格不进快照（无 innerHTML 重建），IO 绑定随元素存活到
  // tab 关闭
  // 窗格重设计 P1-3：窗格 md 行工厂——renderMd 内核 + 复用 .h-bubble 全局
  // 排版规则（p/pre/code/ul），窗格窄列字号由 .hg-sub-msgmd 收敛（.h-msg
  // 作用域的气泡 padding 不命中本行）；高亮走懒增强——子代理长代码白高亮
  // 是 CPU 大户，滚到视口才亮
  // v2.43：段头收尾共用（_subClose 常规收尾 + _hgAgentsSweep 中断/退出兜底）
  // ——定格态 + 补回放入口（agentId 已落档时）：快照恢复后实时档案
  // （_HG.agents）丢失，段头凭 hgSubr 仍可开回放窗格（转写数据源永远可
  // 重建）；运行态段头只有 hgSub（live 入口），语义由 .done 类分派。
  // v2.43.1（R-FAIL1）：adopt 先行——切会话往返后 _HG.subBlk 已清而段 DOM
  // 在（快照恢复），完成信号直达本函数也能定格；aidForce=完成信号自带的
  // agentId（tool_result 文本提取 / task_notification.task_id），档案缺失时
  // hgSubr 靠它补上。
  // 思考回填取数：subagent_replay 端点（与段头回放窗格/历史注入同源）。会话
  // 切走即弃（段 DOM 已随快照冻结，切回由历史路径重渲接管，不重复插）
  // v2.47（需求2）：协作段无转写占位（幂等，hgCollabNote 防重）——只在段体
  // 确无任何过程行时插一句说明；完成状态仍以段头定格为准
  // 思考行归节（v2.48 大简化）：replay 行序=时序，段内 text 气泡=节边界——
  // 每条思考归入它「右侧最近边界气泡」之前的节（v2.44 分桶定位算法退役：
  // 不再按工具行名对位，思考进节的 think 抽屉而非插在具体工具行前）。
  // 边界映射：replay text 行序 ↔ 段内气泡序。uncapped 恒等；capped（note
  // 截断）头区从 0 顺数、尾区对齐段内**最后 tailTextN 张**气泡；中段省略区
  // 的思考右侧边界=首张尾区气泡（归入其前节——时序上确在其前，成立）。
  // 无边界可归（无 text / 尾随思考）→ body 尾部的节（尾非节则尾建——v2.48R
  // 修正：尾随思考的时序在最后一条 text 之后）。note 省略行落段尾。
  // 段内已有任何思考段即整体跳过（「全有或全无」——轮询喂过/未来 CLI 直转
  // 场景防混插重复；正文走 dataset.raw 懒渲，_histLazyFill raw 分支接管）
  // ==================== v2.46 运行中实时思考（.output 增量轮询） ====================
  // 背景（v2.44 实证）：CLI stream-json 不转发子代理 thinking（112 事件 0 块），
  // 但 tasks\<agentId>.output 实时落盘含全部思考块——运行期从后端
  // /subagent_tail 增量读（offset 只读新增字节，按行边界切防截断半行/多字节），
  // 解析新增 thinking 块插段内思考折叠行（_subThink，与历史/回填三路同构）。
  // 性能：2s 单例轮询；仅有「运行中 + taskId 在手 + 段在场」的代理才发请求
  //（每会话常态 0-2 个），单次增量几 KB——代理完成（段 done）/切会话
  //（subBlk 清）自然停。与完成回填（_subBlkMergeThinks）的防重：回填守卫
  // 「段内已有思考整体跳过」已覆盖两套布局（b.body 后代查询）。
  // 注：轮询插的思考行无 dataset.hi/raw（增量流式内容，快照/lazyDrop 语义
  // 下不可复原也不可丢——_histLazyDrop 对无标记行不动，一致）。
  // v2.47（需求2）：协作段纳入轮询且全喂——SendMessage 续派的独立会话过程
  // 不经过本会话事件流（collab 的实况空白正是 v2.37 不开段的原因），轮询
  // 转写是其唯一实时来源：thinking 之外 text/tool_use/tool_result 也喂
  //（_subText/renderToolUse(isSub)/_subToolResult，行序=到达序 FIFO 配对
  // 成立）。真实子代理维持 think-only——其 text/tool 已由 SSE 事件流覆盖，
  // 轮询再喂必重复。
  _HG.subTail = {};        // agentId → 已消费字节 offset（复审#5：subTailSeg 初始化随段删）
  // collab 全喂判定：档案 collab 且其派发行确为 SendMessage（peerSent 在档）
  // ——只有 SendMessage 续派才保证「独立会话、本会话无事件流」（轮询是唯一
  // 源，全喂不重复）。被 v2.37「宁可误杀」收进 collab 的真实后台代理事件流
  // 照常到达（text/tool 已由 SSE 覆盖），全喂必重复——它们维持 think-only。
  // 档案缺失（切会话往返）：读建段时落的持久标记 hgFullfeed（peerSent 真实
  // id 命中才落，随快照携带）。v2.47R（复审2）：不能看 hgSubr/data-hg-collab
  // 双证——_subBlkFinish 对所有段落 hgSubr（误杀形态完成瞬间也落），双证
  // 会被误杀形态攻破致 drain 全量重插
  // v2.47（需求2）：协作段 DOM 兜底轮询——段 dataset 即全部所需（随快照
  // 携带）：data-hg-collab 标记 + 段头 hgSubr（建段时 peerSent 反查的真实
  // agentId）。切会话往返（agents 清空）后由此续喂；认回复活秒表（t0 从
  // 段头「运行中 Ns」还原）。offset 续账在消费点 _subTailFetch 入口统一做
  //（复审1：不依赖轮询节拍，drain 直达也能续对位置防双份插入）
  // v2.46R（P2）：定格 drain——等在途拉取收敛（定格前 tick 的最后一发）后
  // 连拉到文件尾无推进为止（≤6 轮防异常循环），随后回填。完成兜底：轮询
  // 从未插过思考（subTail 无档）时 drain 空转、回填照常全量
  // v2.46R（P5）：单例防护——关-开 tab 重建会叠加 interval（N 倍请求+并发
  // 同 offset 双份插入，_hgDynTick 同款教训先例）；重建时先清旧的再挂当前
  // 闭包的（只保最新的，防旧闭包 flow 引用已脱离 DOM 的元素）
  if (window._hgSubTailTick) clearInterval(window._hgSubTailTick);
  window._hgSubTailTick = setInterval(_subThinkPollTick, 2000);
  if (_subTabsEl) _subTabsEl.onclick = (e) => {
    // 窗格重设计 P1-1/P1-2：单-tab ✕——✕ 在 [data-hg-subtab] 容器内部，
    // 分支必须放在激活分支之前并 return（否则点 ✕ 变切 tab）。运行态要在
    // drop 之前取（drop 后 tab 档案即散）；运行中给去向 toast——任务在后台
    // 继续，面板子代理区/主 flow 子代理行随时可重开（_subReopen）
    const xc = e.target.closest('[data-hg-subclose]');
    if (xc) {
      e.stopPropagation();
      const tid = xc.dataset.hgSubclose;
      const wasRun = !!(_sub.tabs[tid] && _sub.tabs[tid].run);
      _subDrop(tid);
      if (wasRun) showBanner('已关闭视图——任务继续后台运行，可在面板子代理区重新打开', 3200);
      return;
    }
    const t = e.target.closest('[data-hg-subtab]');
    if (t) {
      // v3.3R（全审 P3）：伪 tab（动态/目录）点击入口与 _subDynOpen/_subDirOpen
      // 同口径置 manual——分屏若是 Task 自动开的（manual=false），用户点 tab 条
      // 切过来阅读，回合终结不该把整个分屏收走
      if (t.dataset.hgSubtab === _SUB_DIR || t.dataset.hgSubtab === _SUB_DYN) _sub.manual = true;
      _subActivate(t.dataset.hgSubtab);
    }
  };
  // 窗格重设计：窗格体行内交互全走 body 级事件委托——行是流式动态 append +
  // cap 删首，逐行直绑不可维护且 innerHTML 重建即丢（主 flow v2.12 的坑）。
  // md 代码块复制钮本在 flow 委托里，但窗格在 flow 外够不着，此处补一条
  // 同款分支。onclick 覆盖式绑定（闭包随 harness tab 重开重执行）
  if (_subBodyEl) _subBodyEl.onclick = (e) => {
    // v3.2：子代理目录行——点行开该代理视图（live 实况/已结束回放）
    const dirRow = e.target.closest('[data-hg-dir]');
    if (dirRow && dirRow.dataset.hgDir) {
      _subDirRowClick(dirRow.dataset.hgDir, dirRow.dataset.hgDirRpl === '1');
      return;
    }
    // v2.37R6+：回放长文本行折叠切换（展开 ∨ / 收起 ∧）——纯视觉层
    const foldTog = e.target.closest('.hg-sub-fold-tog');
    if (foldTog) {
      const wrap = foldTog.closest('.hg-sub-fold-wrap');
      if (wrap) {
        const opening = wrap.classList.toggle('open');
        foldTog.textContent = opening ? '收起 ∧' : '展开 ∨';
      }
      return;
    }
    // md 代码块复制钮（就近取同容器 pre>code 文本）
    const cp = e.target.closest('.hg-code-copy');
    if (cp) {
      const codeBox = cp.closest('.hg-code');
      const code = codeBox && codeBox.querySelector('pre > code');
      if (code) copyText(code.textContent.replace(/\n$/, '')).then(ok => {
        if (ok) { const orig = cp.textContent; cp.textContent = '✓';
          setTimeout(() => cp.textContent = orig, 1500); }
      });
      return;
    }
    // P2-6（v3.2.6 时间线化）：窗格思考段——首展懒渲染（dataset.raw →
    // renderMd，_histLazyFill 同款），再点收起清体（与主链开合同出口）
    const thHead = e.target.closest('.h-think-seg-head');
    if (thHead) {
      const seg = thHead.closest('.h-think-seg');
      if (seg) {
        const opening = !seg.classList.contains('open');
        if (opening) _histLazyFill(seg); else _histLazyDrop(seg);
        seg.classList.toggle('open');
      }
      return;
    }
    // v3.2.6：窗格回合头（工作中/已工作 X ›）——切时间线体开合（定稿默认
    // 收起；手动开合记 userToggled，防定稿时把用户正看着的体收走）
    const stgl = e.target.closest('.h-turn-head[data-hg-subtgl]');
    if (stgl) {
      const proc = stgl.closest('.h-grp-proc');
      const body = proc && proc.querySelector('.h-turn-body');
      if (body) {
        body.classList.toggle('closed');
        stgl.dataset.userToggled = '1';
      }
      return;
    }
    // v3.2.6：窗格查阅聚组头——子行树开合（组内工具行无 hi，开合即布局态）
    const sgrp = e.target.closest('.h-tl-grp-head');
    if (sgrp) {
      const grpEl = sgrp.closest('.h-tl-grp');
      if (grpEl) {
        grpEl.classList.toggle('open');
        grpEl.dataset.userToggled = '1';
      }
      return;
    }
    // v3.2.6：窗格工具行头——展开/收起详情（结果文本在折叠体内）
    const pTool = e.target.closest('.h-tool-head');
    if (pTool) {
      const trow = pTool.closest('.h-tool');
      if (trow) trow.classList.toggle('open');
      return;
    }
  };
  _subRes = _hgQ('[data-hg-subres]');
  if (_subRes) _subRes.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const right = _subPaneEl.getBoundingClientRect().right;
    // v3.2.31：分屏拖拽升级——百分比口径（25%~75% 聊天区总宽），localStorage
    // 记忆 hg-subpane-pct（14-subpane _hgSubPctGet/_hgSubPctApply 同源）。
    // 拖拽中 .hg-main flex 收缩、聊天区总宽（=hg 宽−会话栏）恒定，分母稳定
    const region = _hgSubRegion() || 1;
    const move = (ev) => {
      const pct = Math.min(75, Math.max(25, (right - ev.clientX) / region * 100));
      _hgSubPctApply(pct);
      try { localStorage.setItem(_subPanePctKey(), pct.toFixed(2)); } catch(_) {}   // v3.4.22：写入当前档位键（窄/宽分档记忆）
    };
    const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
  _subX = _hgQ('[data-hg-subx]');
  if (_subX) _subX.onclick = () => {
    if (_subPaneEl) _subPaneEl.style.display = 'none';
    _sub.manual = false;   // v2.35（P0-3）：手动关即退出「回合终结不自动收起」模式
  };
  // ==================== v3.3：会话动态胶囊绑定（分屏化）====================
  // 胶囊=分屏唯一开关，四分支状态机：
  // ① 有运行中子代理 → 直达最新派发代理的实况 tab（联动保留，_subReopen 内
  //    自带 _subShow+manual=true）；
  // ② 分屏未开 → 开分屏激活「动态」伪 tab（_subDynOpen 懒建）；
  // ③ 动态页激活中再点 → 收分屏（manual 复位，同 ✕ 语义）；
  // ④ 分屏开着但在他 tab（纯自动实况等，动态页未建）→ 切回/补建动态页。
  // try/catch 兜底：分屏 DOM 缺失等异常不阻断 builder 后续装配
  try {
    const _capsBtn = _hgQ('[data-hg-dyncaps]');
    if (_capsBtn) _capsBtn.onclick = () => {
      try {
        const _runTids = Object.keys(_HG.agents || {})
          .filter(k => !((_HG.agents || {})[k] || {}).done)
          .sort((a, b) => ((_HG.agents[a].t0 || 0) - (_HG.agents[b].t0 || 0)));
        // v3.5.324（用户批注「多个子代理时，点一下 全部打开(所有子代理)」）：
        // 运行中的全部逐个 _subReopen（每个全量铺底+续流），最终激活最新
        // 派发的（循环内逐次 activate，最后一个胜出）；tab 上限 6 逐出旧照旧
        // a93T：状态（动态页）也要在场——此前此分支只建目录/版本漏状态
        if (_runTids.length) { for (const t of _runTids) _subReopen(t); _subDirEnsure(); if (typeof _subDynEnsure === 'function') _subDynEnsure(); return; }
        const _open = _subPaneEl && _subPaneEl.style.display === 'flex';
        if (!_open) { _subDynOpen(); _subDirEnsure(); return; }
        if (_sub.active === _SUB_DYN) {
          _subPaneEl.style.display = 'none';
          _sub.manual = false;
          return;
        }
        // _subActivate 对未注册 tab 静默早退——动态页未建时必须走 _subDynOpen
        if (!_sub.tabs[_SUB_DYN]) { _subDynOpen(); _subDirEnsure(); return; }
        _sub.manual = true;
        _subActivate(_SUB_DYN);
        _subDirEnsure();
      } catch(_) {}
      _hgDynCapsulePaint();              // 兜底路径也收敛视觉态（open/attn 派生）
    };
    try { localStorage.removeItem('hg-dyn-caps'); } catch(_) {}   // v3.3：旧面板偏好废止，清残留（不再读取，残留本无害）
    _hgDynCapsulePaint();
  } catch(_) {}

  // v2.3.9 组头点击：折叠/展开（localStorage 记忆），不影响选会话
  _hgListEl.addEventListener('click', (e) => {
    const grp = e.target.closest('.hg-grp');
    if (grp) {
      e.stopPropagation();
      const key = 'hg-grp:' + grp.dataset.grp + ':closed';
      const closed = grp.classList.toggle('closed');
      try { closed ? localStorage.setItem(key, '1') : localStorage.removeItem(key); } catch(_) {}
      renderList();
    }
  });
  // v2.2.1：相对时间随钟表 tick 且对话中实时刷新（用户实锤：对话进行中
  // 列表仍定格旧时间——refreshSessions 只在回复结束才拉，60s 只重渲旧数据
  // 没用）。v3.5.296b2（全审 G1）：旧 60s interval 收编删除——builder 内
  // 10s 周期对账（v3.5.296）已完整覆盖其职责，双周期并存只多打重复请求。
  _hgListEl.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-act]');
    if (act) {
      e.stopPropagation();
      const sid = act.dataset.sid;
      if (act.dataset.act === 'del') {
        const ok = await hgConfirm('删除会话', '删除后该会话从列表移除（~/.claude 转写保留）。确定删除？');
        if (!ok) return;
        await fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid})});
        delete _HG.cache[sid];

        if (_HG.tasksBy) delete _HG.tasksBy[sid];      // A组T2：v216 桶随删清
        if (_HG.liveAgentsBy) delete _HG.liveAgentsBy[sid];
        delete _HG.attsBy[sid];   // v2.3.0：暂存附件随会话清
        delete _HG.queues[sid];   // v2.25：排队草稿随会话清（审计 §三.9）
        // 上下文窗口/坏数据阈值是按 sid 的两张映射，删除会话不回收会随
        // 会话总数单调增长（同 sid 被重新 attach 还会命中已删遗留值）
        if (_HG.ctxWinBy) delete _HG.ctxWinBy[sid];
        if (_HG.ctxBadMaxBy) delete _HG.ctxBadMaxBy[sid];
        if (_HG.modelBySid) delete _HG.modelBySid[sid];
        // a612：子代理 tab 记忆也按 sid 存，删除会话时回收（同 ctxWinBy，
        // 不删会随会话总数单调增长，且同 sid 重建时认领到已删的旧 tab）
        try { _subActiveBySidForget(sid); } catch (_) {}
        // 二轮 P1-2：v4 权威快照垫片键随会话删清（数十~数百 KB/会话，
        // WebView2 同源 ~5MB 配额，不删则 a60R 冷启垫片静默失效）
        try { localStorage.removeItem('hg_v4snap:' + sid + ':main'); } catch(_) {}
        try { localStorage.removeItem('hg-open:' + sid); localStorage.removeItem('hg-ctx:' + sid); } catch(_) {}   // v2.16：连开合/用量记录一起清
        if (_HG.sid === sid) switchTo(null); else refreshSessions();
      } else if (act.dataset.act === 'rename') {
        const s = _HG.sessions.find(x => x.sid === sid);
        const t = await hgPrompt('重命名会话', '会话名称', (s && s.title) || '');
        if (t === null) return;
        await fetch('/api/harness/rename', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid, title: t})});
        refreshSessions();
        if (_HG.sid === sid) { _hgTitleEl.textContent = t || '会话'; _hgConn.tab.querySelector('.label').textContent = _hgTitleEl.textContent; }
      }
      return;
    }
    const item = e.target.closest('.hg-item');
    if (item && item.dataset.sid) switchTo(item.dataset.sid);
  });
  _hgSearchEl.addEventListener('input', renderList);

  // ==================== 发送 ====================
  _hgQ('[data-hg-new]').onclick = newChat;


  // v2.20：发送核心从 send() 抽出——排队泵（queuePump）发送队列项走同一
  // 条路（乐观渲染 + POST + 回滚）。restoreInput=true 时失败把文本放回
  // 输入框（手动发送场景）；排队项失败只 banner（文本无处可回）。
  // ==================== 内建斜杠命令（v2.21）====================
  // harness 跑的是 claude -p headless：CLI 的交互式命令（/resume /clear…）
  // 到不了进程。输入 / 开头且命中下表 → 前端本地执行（不排队、不发后端，
  // busy 时也即时生效）；其余 /xxx 照常发送，技能/项目自定义命令不受影响。
  // v2.25：CLI 纯交互命令——harness 跑的是 claude -p（headless 无 TTY），
  // 这些命令进去没有渲染面，直接发送只会被模型当普通文本白白消费一轮
  // 回复。本地拦下说明去向，不进对话。
  // v2.21：从模型菜单点击分支抽出——/model 名 复用同一条切换路径
  // 输入 / 前缀即弹 CLI 式命令菜单：内建命令 + 技能一起过滤，↑↓ 选择、
  // Enter/Tab 执行、Esc 关闭；继续打字收窄，出现空格/其他内容即关
  // ==================== 技能中文描述（v2.27「技能需要翻译」）====================
  // 菜单此前一直空白：后端 /skills 给的是 desc 字段，前端读的却是
  // s.description——字段名对不上，描述从没渲染出来过。这里顺带给常见
  // 英文技能配中文一句话说明（命中优先显示；未命中的显示原 desc，
  // 用户自装的中文技能天然中文）。
  // v2.27「技能需要翻译」长期方案：静态映射兜底常见技能；新装技能的英文
  // desc 由后端调 settings.json 配的模型翻译，落 ~/.serialconsole_pro/
  // skill_zh_cache.json 持久缓存——零人工维护，缓存命中后零延迟。



  _hgSendBtn.onclick = () => { _HG.busy ? stopGen() : send(); };

  // ---- 键盘链（源 useChatComposerState：命令菜单 → mention → 历史 → Enter）----
  _hgInput.addEventListener('keydown', (e) => {
    if (handleMentionKey(e)) return;                    // @ 下拉优先
    if (handleSlashKey(e)) return;                      // / 命令菜单次之（v2.21）
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault(); send(); return;
    }
    if (handleHistoryKey(e)) return;                     // ↑↓ 历史
    if (e.key === 'Escape' && _HG.busy) { e.preventDefault(); stopGen(); }
  });
  _hgInput.addEventListener('input', () => {
    _hgInput.style.height = 'auto';
    _hgInput.style.height = Math.min(_hgInput.scrollHeight, 200) + 'px';
    renderOverlay(_hgInput.value);
    updateMention();
    slashMenuUpdate();          // v2.21：/ 前缀弹内建命令+技能菜单
  });

  // ---- 输入历史（源 useInputHistory：空框 ↑ 回溯、到底恢复 draft）----

  // ---- @ 文件引用（源 useFileMentions：触发/下拉/键盘/插入/高亮）----
  // v2.15：跨会话要清空。它是闭包常量，switchTo/newChat/_harnessClose 都够不到，
  // 旧实现下在会话 A 用 @ 引用过文件后切到 cwd 完全不同的会话 B，overlay 的
  // 路径高亮仍按 A 的路径匹配（串味）。所有切会话/新建入口统一调它。
  _hgMentionEl.addEventListener('mousedown', (e) => {
    const it = e.target.closest('.hg-mention-item');
    if (it && _HG.mention) { e.preventDefault(); selectMention(_HG.mention.files[+it.dataset.mi]); }
  });
  // 高亮 overlay：与 textarea 同字体同 padding 的镜像层，只画 @ 引用路径的
  // 底色高亮，文字本身透明；textarea 文字正常显示叠在其上（源 renderInputWithMentions，
  // 原版是透明文字+镜像层，这里反过来更稳——镜像层透明文字+真文字在上）。
  _hgInput.addEventListener('scroll', () => { _hgOverlayEl.scrollTop = _hgInput.scrollTop; _hgOverlayEl.scrollLeft = _hgInput.scrollLeft; });

  // ==================== 附件 ====================
  // v2.19：缩略图原来直接拿本地绝对路径当 <img src>（http 页面加载不了盘符路径）
  // → 破图占位符，且破图时浏览器把文件名当 alt 渲染出来，紧跟着又拼了一遍
  // a.name，于是显示成「🖼 2.png 2.png」。改走 /api/harness/file 只读路由；
  // alt 留空、onerror 直接隐藏图片（宁可只剩文件名，也不出破图框）。
  _hgAttsEl.addEventListener('click', (e) => {
    const x = e.target.closest('.hg-att-x');
    if (x) { _HG.atts.splice(+x.dataset.i, 1); renderAtts(); }
  });
  _hgQ('[data-hg-att]').onclick = () => _hgFileEl.click();
  // v2.3.12 内置截图：公共入口 window.harnessSnipStart 已升级为工具级模块
  // web/js/snip.js（用户定调：截图不局限 Claude——确认后复制剪贴板必有，
  // Claude 对话在场才顺带挂附件）。📷 按钮走等比适配路径（不切窗口）。
  _hgQ('[data-hg-snip]').onclick = () => window.harnessSnipStart && window.harnessSnipStart(false);
  _hgFileEl.addEventListener('change', () => { uploadFiles([..._hgFileEl.files]); _hgFileEl.value = ''; });
  _hgInput.addEventListener('paste', (e) => {
    const fs = [...(e.clipboardData?.files || [])].filter(f => f && f.size);
    if (fs.length) { e.preventDefault(); uploadFiles(fs); }
  });
  // v2.2.1：按磁盘路径直接加附件（拖拽进对话 tab 的文件走这——文件已在盘上，
  // 无需上传复制，Claude 直接 Read 原路径）。图片限 20MB（防撑爆上下文），
  // 其他类型不限（大日志让 Claude 自己 Read 更合理）。
  window.harnessAddFilesByPath = async (paths) => {
    let added = 0;
    for (const p of (paths || [])) {
      const name = String(p).split(/[\\/]/).pop() || 'file';
      const isImg = _HARNESS_IMG_EXT.test(name);
      if (isImg) {
        try {
          const j = await (await fetch('/api/file_info', {method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: p})})).json();
          if (j.ok && j.size > 20 * 1024 * 1024) {
            showBanner(`「${name}」超过 20MB，跳过`, 3000, true); continue;
          }
        } catch(_) {}
      }
      _HG.atts.push({name, path: p, size: 0, isImg});
      added++;
    }
    if (added) {
      renderAtts();
      showBanner(added === 1 ? '已加为对话附件（发送时随消息带上）' : `已加 ${added} 个附件`, 2500);
      _hgInput.focus();
    }
  };

  // ==================== popover（技能/模型）====================
  _hgQ('[data-hg-skill]').onclick = async (e) => {
    if (_HG.pop === 'skill') { closePop(); return; }
    const anchor = e.currentTarget;
    if (!_HG.skills) {
      try {
        const j = await (await fetch('/api/harness/skills')).json();
        _HG.skills = (j.ok && j.skills) || [];
        _HG.skillZh = (j.ok && j.zh) || {};
      } catch(_) { _HG.skills = []; }
    }
    _skillZhSync();
    const items = _HG.skills.length
      ? _HG.skills.map(s => `<div class="hg-pop-item" data-skill="${esc(s.name)}"><b>/${esc(s.name)}</b><span>${esc(_skillDesc(s).slice(0, 60))}</span></div>`).join('')
      : '<div class="hg-pop-empty">未发现技能（~/.claude/skills 或项目 .claude/skills）</div>';
    openPop('skill', anchor, `<div class="hg-pop-title">技能</div>${items}`);
  };
  // v2.25：每次打开都重拉——配置方案切换会改 settings.json 的模型映射，
  // 旧实现只在 tab 存续期拉一次，切方案后模型下拉仍显示旧网关的模型
  // （后端已按 settings.json mtime 失效缓存，这里配合即时拉新）。
  _hgQ('[data-hg-model]').onclick = async (e) => {
    if (_HG.pop === 'model') { closePop(); return; }
    const anchor = e.currentTarget;
    await fetchModels();
    const cur = _HG.model || _HG.models.default;
    // v2.19：多模态模型打 👁——这类模型的会话自己读图
    // v2.28.1：两态——真多模态 👁 / 其余全部走 MCP 通道（无需标记）
    const mmSet = new Set(_HG.models.mm || []);
    const items = (_HG.models.models || []).map(m =>
      `<div class="hg-pop-item${m === cur ? ' on' : ''}" data-model="${esc(m)}"><b>${esc(m)}</b>${
        mmSet.has(m) ? `<span title="多模态：可直接读图">${_HG_EYE} 多模态</span>`
        : ''}${m === _HG.models.default ? '<span>默认</span>' : ''}</div>`).join('')
      || '<div class="hg-pop-empty">读取 settings.json 模型映射失败</div>';
    openPop('model', anchor, `<div class="hg-pop-title">模型（会话内切换即时生效，上下文保留）</div>${items}`);
  };
  _hgWrap.addEventListener('click', async (e) => {
    // v2.21：命令菜单点选（内建命令直接执行，技能插入待补参）
    const sit = e.target.closest('.hg-pop.slash .hg-pop-item');
    if (sit) {
      e.stopPropagation();
      slashPick((_HG.slashList || [])[+sit.dataset.i]);
      return;
    }
    const si = e.target.closest('[data-skill]');
    if (si) {
      _hgInput.value = (_hgInput.value ? _hgInput.value.replace(/\s*$/, ' ') : '') + '/' + si.dataset.skill + ' ';
      renderOverlay(_hgInput.value);
      closePop(); _hgInput.focus(); return;
    }
    // v2.20：项目目录下拉（最近目录 + 浏览）
    const di = e.target.closest('[data-dir]');
    if (di) {
      const d = di.dataset.dir;
      closePop();
      if (d === '__browse__') {
        let dir = '';
        if (window.pywebview && pywebview.api && pywebview.api.pick_dir)
          dir = await pywebview.api.pick_dir() || '';
        if (dir) setProj(dir);
      } else if (d) setProj(d);
      return;
    }
    const pe = e.target.closest('[data-perm]');
    if (pe) {
      _HG.perm = pe.dataset.perm || 'auto';
      permChipLabel();
      if (!_HG.dirty) {
        if (_HG.sid) {
          fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
          switchTo(null);
        }
        showBanner('权限「' + _HG_PERMS[_HG.perm] + '」将用于当前新会话', 2400);
      } else showBanner('当前会话已有对话，权限将在新建会话生效', 2800);
      closePop(); return;
    }
    const tk = e.target.closest('[data-think]');
    if (tk) {
      _HG.thinkLv = tk.dataset.think || null;
      thinkChipLabel();
      if (!_HG.dirty) {
        if (_HG.sid) {
          fetch('/api/harness/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({sid: _HG.sid})}).catch(() => {});
          switchTo(null);
        }
        showBanner('思考等级「' + (_HG.thinkLv ? _HG_THINKS[_HG.thinkLv] : '默认') + '」将用于当前新会话', 2400);
      } else showBanner('当前会话已有对话，思考等级将在新建会话生效', 2800);
      closePop(); return;
    }
    const mi = e.target.closest('[data-model]');
    if (mi) {
      // v2.20（强需求）：会话内直接换模型——后端 quiet 杀进程 + --resume
      // 同 session 重启，上下文连续，新模型下次回复即生效；SSE 回
      // model_switched 事件在消息流里渲染分割线。不再要求新建会话。
      // v2.21：逻辑抽到 applyModel，/model 名 命令复用同一条路
      applyModel(mi.dataset.model);
      closePop(); return;
    }
    // v2.20 修复：.hg-proj 也持有自己的 popover（原豁免只认 .hg-chip，
    // 点项目选择器 → onclick 刚 openPop → 冒泡到这里又 closePop，
    // 菜单闪一下就没了，表现为「项目下拉无效」）
    if (!e.target.closest('.hg-pop') && !e.target.closest('.hg-chip')
        && !e.target.closest('.hg-proj')) closePop();
  });
  if (_HG.model) _hgQ('[data-hg-model]').innerHTML = esc(_HG.model) + ' ▾';

  // ==================== 项目目录（v2.7；v2.20 改版）====
  // 参考 ZCode 布局：选择器挪到输入卡顶部（📁 目录名 ▾），下拉给最近
  // 目录 + 浏览。持久化 + 最近目录列表（localStorage）；切回历史会话时
  // cwd 同步过来——同项目连续开会话不必每轮重选。
  try { _HG.cwd = localStorage.getItem('hg-last-cwd') || null; } catch(_) {}
  _hgQ('[data-hg-proj]').onclick = (e) => {
    if (_HG.pop === 'proj') { closePop(); return; }
    const cur = _HG.cwd;
    const dirs = (cur ? [cur] : []).concat(_hgCwdHist().filter(d => d !== cur));
    const items = dirs.map(d =>
      `<div class="hg-pop-item${d === cur ? ' on' : ''}" data-dir="${esc(d)}"><b>${esc(d.split(/[\\/]/).pop() || d)}</b><span>${esc(d)}</span></div>`).join('')
      || '<div class="hg-pop-empty">还没有选择过项目目录</div>';
    openPop('proj', e.currentTarget,
      `<div class="hg-pop-title">项目目录（新会话打开在此）</div>${items}` +
      `<div class="hg-pop-item" data-dir="__browse__"><b>浏览其他目录…</b></div>`);
  };
  projChipLabel();

  // ==================== 权限 / 思考等级（v2.20，参考 ZCode）====
  // 权限：auto=工具直接执行（现状）；confirm=写操作前用 ask_user 卡片确认。
  // 思考等级：→ 后端 MAX_THINKING_TOKENS。都是新会话参数（同模型 chip 语义）。
  _hgQ('[data-hg-perm]').onclick = (e) => {
    if (_HG.pop === 'perm') { closePop(); return; }
    const items = Object.keys(_HG_PERMS).map(k =>
      `<div class="hg-pop-item${k === _HG.perm ? ' on' : ''}" data-perm="${k}"><b>${_HG_PERMS[k]}</b><span>${k === 'auto' ? '工具直接执行' : '写文件/改状态前弹卡片确认'}</span></div>`).join('');
    openPop('perm', e.currentTarget, `<div class="hg-pop-title">权限（对新会话生效）</div>${items}`);
  };
  _hgQ('[data-hg-think]').onclick = (e) => {
    if (_HG.pop === 'think') { closePop(); return; }
    const items = `<div class="hg-pop-item${!_HG.thinkLv ? ' on' : ''}" data-think=""><b>默认</b><span>CLI 自主决定</span></div>` +
      Object.keys(_HG_THINKS).map(k =>
        `<div class="hg-pop-item${k === _HG.thinkLv ? ' on' : ''}" data-think="${k}"><b>${_HG_THINKS[k]}</b><span>${_HG_THINK_TOK[k]} tokens</span></div>`).join('');
    openPop('think', e.currentTarget, `<div class="hg-pop-title">思考等级（对新会话生效）</div>${items}`);
  };
  permChipLabel(); thinkChipLabel();

  // ==================== 识图状态指示（v2.28.2 简化）====================
  // 识图会话退役、MCP 接管后，识图过程直接显示在对话流里（📤 转交线+秒表 →
  // 📥 回传气泡），无需 3s 轮询/冒泡/状态机——按钮只静态反映开关态。
  visIndEl = _hgQ('[data-hg-visind]');
  visBtnEl = _hgQ('[data-hg-vision]');
  if (visIndEl) visIndEl.style.display = 'none';   // 顶栏指示器退役
  paintVisionBtn();
  // 保存/开关变化后由面板流程刷新——简单起见每 30s 兜底刷一次
  setInterval(paintVisionBtn, 30000);

  // ==================== 三角色（v2.38 整合）====================
  // v2.38：「三角色」快捷开关按钮删除（与配置面板重复，用户实锤「这俩
  // 配置重复了」）——启用/停用统一走「三角色」配置面板里的开关（保存
  // POST /roles 全量含 enabled）。这里只做启动缓存预热：主气泡的角色
  // 徽章（重主力/轻主力）渲染要读 _hgRolesCache。
  _hgRolesFetch();

  // ==================== 识图配置（v2.28.2：MCP 后端）====================
  // 识图双通道（v2.28.5）：主通道=网关内置 mcp__4_5v_mcp__analyze_image
  // （服务端执行）；兜底=本地 mcp__vision__analyze_image（harness_vision_mcp，
  // 主通道失败后传本地路径）。此处配置的是兜底通道的模型/端点映射/提示词。
  // 这里配置 MCP 的识图模型/端点映射/提示词——多方案适配：不同 base_url
  // 方案可各配各的识图模型（lanz 配 Lanz 系、bigmodel 配 glm 系）。
  // 配置即行为：MCP 每次调用时读盘，改完即刻生效，无需重启会话。
  _hgQ('[data-hg-vision]').onclick = async () => {
    let j = null;
    try { j = await (await fetch('/api/harness/vision')).json(); } catch(_) {}
    if (!j || !j.ok) { showBanner('读取识图配置失败', 3000, true); return; }
    const saved = await hgVisionManager(j);
    if (saved === null) return;                 // 取消不动
    try {
      const r = await fetch('/api/harness/vision', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(saved)});
      const jr = await r.json();
      if (!jr.ok) { showBanner(jr.err || '保存失败', 3000, true); return; }
      // v3.5.101：后端已同步激活方案快照的识图配置（来回切方案不再还原）；
      // 同步失败显式告警。
      const vs = (jr.vision || {});
      showBanner((saved.enabled ? '识图配置已保存（MCP 通道，即刻生效）' : '识图已关闭')
        + (vs.synced ? '，方案「' + vs.synced + '」快照已同步' : ''), vs.sync_err ? 7000 : 3000);
      if (vs.sync_err) showBanner(vs.sync_err, 7000, true);
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
  // 识图配置界面（v2.28.2）：开关 + MCP 识图模型 + 端点映射 + 提示词 +
  // 真多模态名单（可恢复默认）。返回对象=保存；null=取消。

  // ==================== 三角色配置（v2.34 起）====================
  // 整节配置入口（此前只能手改 config.json）：开关/模型池（三槽：主会话/
  // 轻模型/重模型）/端点角色映射/审计模式/分级线。唯一入口（快捷开关按钮
  // 已删，开关在面板里）。保存走 POST /roles（merge 写盘）：模型池/分级线
  // 在引导词里 → 指纹热更下条消息换词重启 + agents 重生成；audit_mode 回合
  // 结算读盘即时生效。模式与识图面板同款（hgVisionManager）。
  // 配置面板打开主体抽函数——按钮与面板 C 区三角色行共用
  _hgQ('[data-hg-roles-cfg]').onclick = openRolesCfg;
  // 三角色配置界面：开关 + 形态展示（只读）+ 三档下拉（轻/中/重，v3.5.0
  // 实跑模型命中哪档=哪形态）+ 设计者/审计者槽（折叠在「工作方式说明」）
  // + 端点角色映射 + 审计模式/分级线。返回对象=保存；null=取消。

  // ==================== 自定义提示词（v2.8：多条目 + 全局/项目作用域）====
  // 每个会话进程启动时后端 --append-system-prompt 注入（新会话/复活同路径）：
  // 启用的全局条目对全部会话生效；项目条目只对 cwd 目录名匹配的会话生效。
  // 入口在左栏最底部（用户指定位置）；管理界面 = 条目列表 + 每条
  // v2.27：恢复会话——列表唯一来源是注册表 claude_harness.json，它一旦被
  // 清（写入撕裂/多开覆盖）会话就"看不见"了，但转写还在磁盘上。这里扫出
  // 注册表里没有的 jsonl 让用户手动找回（异常丢失/误删都能自救）。
  _hgQ('[data-hg-recover]').onclick = async () => {
    showBanner('正在扫描磁盘上的会话记录…', 2000);
    let items = [];
    try {
      const j = await (await fetch('/api/harness/recoverable')).json();
      if (!j.ok) { showBanner(j.err || '扫描失败', 3000, true); return; }
      items = j.items || [];
    } catch(e) { showBanner('扫描失败：' + e, 3000, true); return; }
    const ov = document.createElement('div');
    ov.className = 'hg-modal-ov';
    const fmtSize = (n) => n >= 1048576 ? (n/1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n/1024)) + ' KB';
    const shortCwd = (c) => String(c || '').replace(/\//g, '\\').split('\\').filter(Boolean).slice(-1)[0] || '未知项目';
    ov.innerHTML = `<div class="hg-modal hg-modal-recover"><div class="hg-modal-title">⟲ 恢复会话</div>
      <div class="hg-modal-body hg-recover-hint">以下是磁盘上有记录、但不在当前列表里的会话。恢复只是找回入口，不启动任何进程；点开会话发消息即自动续上原上下文。</div>
      <div class="hg-recover-list"></div>
      <div class="hg-modal-acts"><button class="btn ghost" data-hg-r-close>关闭</button></div></div>`;
    const _hgListEl = ov.querySelector('.hg-recover-list');
    // a459：关闭必须走 hgModalTrack 包过的 close（先退册再摘 DOM）——绑裸
    // close 会让收口表条目连着 detached DOM 一直留到 tab 销毁（a453 声称
    // 修掉的泄漏在唯一调用点上其实没修到）。注册在下方 appendChild 后，
    // 拿到返回的 tracked close 再绑按钮。
    const close = () => ov.remove();
    function render() {
      if (!items.length) {
        _hgListEl.innerHTML = '<div class="hg-list-empty">没有可恢复的会话——列表里的会话和磁盘记录是对得上的</div>';
        return;
      }
      _hgListEl.innerHTML = items.map((it, i) => it._done
        ? `<div class="hg-r-item done"><span class="hg-r-title">✓ ${esc(it.title)}</span><span class="hg-r-meta">已恢复到列表</span></div>`
        : `<div class="hg-r-item">
             <div class="hg-r-info">
               <div class="hg-r-title" title="${esc(it.title)}">${esc(it.title)}</div>
               <div class="hg-r-meta">${_harnessRelTime(it.last_active)} · 你的消息×${it.human || 0}${it.human_more ? '+' : ''} · ${fmtSize(it.size)} · ${esc(shortCwd(it.cwd))}</div>
             </div>
             <button class="btn ghost hg-r-btn" data-i="${i}">恢复</button>
           </div>`).join('');
      _hgListEl.querySelectorAll('.hg-r-btn').forEach(btn => {
        btn.onclick = async () => {
          const it = items[+btn.dataset.i];
          btn.disabled = true; btn.textContent = '恢复中…';
          try {
            const j = await (await fetch('/api/harness/recover', {method:'POST',
              headers:{'Content-Type':'application/json'},
              body: JSON.stringify({session_id: it.session_id, title: it.title})})).json();
            if (!j.ok) { showBanner(j.err || '恢复失败', 3000, true); btn.disabled = false; btn.textContent = '恢复'; return; }
            it._done = true;
            render();
            refreshSessions();
            showBanner('已找回：' + it.title, 2400);
          } catch(e) { showBanner('恢复失败：' + e, 3000, true); btn.disabled = false; btn.textContent = '恢复'; }
        };
      });
    }
    render();
    document.body.appendChild(ov);
    // a452（审计 P1）：自建弹窗也要进收口表——关 Claude tab 时统一关掉，
    // 否则弹窗盖在全窗上，点\"恢复\"还会对已销毁面板发 /api/harness/recover
    try { if (typeof hgModalTrack === 'function') {
      const _tc = hgModalTrack(ov, close);
      if (_tc) ov.querySelector('[data-hg-r-close]').onclick = _tc;
    } } catch (_) {}
  };
  // 备注/作用域/开关/编辑/删除，整表保存。
  _hgQ('[data-hg-skills-btn]').onclick = () => skRepoOpen();
  _hgQ('[data-hg-prompt]').onclick = async () => {
    let prompts = [];
    try { prompts = (await (await fetch('/api/harness/system_prompt?cwd=' + encodeURIComponent(_HG.cwd || ''))).json()).prompts || []; }
    catch(_) {}
    const saved = await hgPromptManager(prompts, _HG.cwd || '');
    if (saved === null) return;   // 取消不动
    try {
      const r = await fetch('/api/harness/system_prompt', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify({prompts: saved})});
      const j = await r.json();
      if (!j.ok) { showBanner(j.err || '保存失败', 3000, true); return; }
      showBanner(saved.length ? `已保存 ${saved.length} 条提示词，新会话/复活后生效` : '提示词已清空', 2400);
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  };
  // 提示词管理界面：条目卡片列表（备注入卡片头，正文 textarea 编辑）。
  // 返回新数组=保存；null=取消。卡片上的状态即时反映到返回值。

  // ==================== 轻量模态（铁律2）====================

  // a272R（用户实锤刷新后仍复现）：switchTab 切回走的是 conn.onResumePoll——
  // 这里是切回时的权威钩子。双 rAF 等布局回填后重算活动刻度（display:none
  // 期间 offsetTop 全归零，立即算必错）
  _hgConn.onResumePoll = () => {
    if (_HG.conn === _hgConn) _hgInput.focus();
    // a273R2：切回不再清缓存——保留 tab 可见期间建立的可信 offsetTop，
    // 布局没变（没新消息）缓存依然正确；有新消息 railSync 自然失效重建。
    // 双 rAF 后只重算活动刻度
    requestAnimationFrame(() => requestAnimationFrame(() => {
      try { _hgRailActiveRaf(); } catch (_) {}
    }));
  };

  // ==================== 初始 ====================
  showWelcome();
  _hgDrawCtxRing(0, 0);   // 启动占位：分母未知（0=等 /ctx），放 256K 会被实时链当分母画假百分比
  (async () => {
    await refreshSessions();
    const last = _HG.sessions.find(s => s.has_history);
    if (last) switchTo(last.sid);
    else _hgInput.focus();
  })();
  return _hgConn;
}

  // ==================== v3.2.10：回合导航轨（ZCode ConversationTurnNavigator 同款）====================
  // 会话左缘竖向刻度轨：每条用户提问一枚刻度，悬停 title 预览、点击跳转到该
  // 回合；当前视口所在回合高亮 + 轨自滚跟随。未渲染回合（在 histStart 之上）
  // 按行号先扩窗（_histRefresh 到该行）再凭 data-turn-hi 定位——**无封顶**，
  // 任何回合任何时候可达（DOM 防爆=折叠回合+懒抽屉+渐进加载，非封顶）
  function _hgRailSync() {
    // v3.5.79（用户实锤「回滚按钮历史会话不出现」）：所有渲染完成路径
    //（历史/快照恢复/重建/实时）都过这里——逐组授予回滚钮（结论=每组根区
    // 末条正文；组内中间输出不授的约束在 grpFinalize turnEnd，幂等安全）
    try { _hgGrantRewind(); } catch (_) {}
    const rail = _hgRailEl;
    if (!rail) return;
    const items = [];
    // v3.5.191r1（用户实锤「导航轨乱」）：v3.5.191 渲染窗口化后 histStart>0
    // 是常态——原①区把窗口外全部回合列成无 DOM 死刻度（165 枚点了没反应），
    // 轨被灌爆。窗口外回合的入口是归档条→只读模式，轨只显示 DOM 在场的回合。
    // ② 已渲染区：flow 里的 user 气泡（盖章或快照旧 DOM 都认）
    _hgFlow.querySelectorAll('.h-msg.user').forEach(el => {
      // 内网报告修复（P1）：turnHi 是可重定位的稳定标识——v4 重建 DOM 后
      // el 引用失联时按 data-turn-hi 重找（见 _hgRailBind），不再存死引用
      items.push({ hi: +(el.dataset.turnHi || -1), key: el.dataset.turnHi || '',
        el, txt: (el.textContent || '').replace(/\s+/g, ' ').trim() });
    });
    if (items.length < 2) {
      rail.classList.remove('show'); rail.innerHTML = '';
      _HG.railItems = null; return;
    }
    // v3.5.210（用户定调「回退最开始的均匀轨最美观；装不下加上下指示
    // 翻页」）：均匀刻度（原版形态），轨自滚跟随 act 既有（_hgRailActive
    // 居中），上下翻页钮由 _hgRailPagers 挂顶/尾（溢出才显示）
    // v3.5.210b（用户实锤「重合了」——sticky 翻页钮与刻度叠压）：轨重构
    // 为「▲ + 刻度滚动区 + ▼」三段——按钮固定轨顶/尾（flex 首尾元素），
    // 刻度在独立 .hg-rail-scroll 内滚动，物理上不可能与按钮重叠
    rail.innerHTML = '<button class="hg-rail-pg up" title="更早" hidden>▲</button>' +
      '<div class="hg-rail-scroll">' + items.map((it, k) =>
        `<button class="hg-rail-t" data-rk="${k}" title="${esc(it.txt.slice(0, 160))}" ` +
        `aria-label="跳转到第 ${k + 1} 条提问"><i></i></button>`).join('') + '</div>' +
      '<button class="hg-rail-pg dn" title="更近" hidden>▼</button>';
    _hgRailPagers(rail);
    _HG.railItems = items;
    _HG.railCacheTops = null;   // a273R：条目重建，位置缓存同步失效
    rail.classList.add('show');
    _hgRailActive();
  }
  // v3.5.210b：翻页钮显隐+滚动（刻度区 .hg-rail-scroll 独立滚动，按钮
  // 固定轨首尾 flex 元素——不 sticky 不叠刻度）
  function _hgRailPagers(rail) {
    const sc = rail.querySelector('.hg-rail-scroll');
    const up = rail.querySelector('.hg-rail-pg.up');
    const dn = rail.querySelector('.hg-rail-pg.dn');
    if (!sc || !up || !dn) return;
    const upd = () => {
      const of = sc.scrollHeight - sc.clientHeight > 8;
      up.hidden = !of || sc.scrollTop <= 8;
      dn.hidden = !of || sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 8;
    };
    up.onclick = (e) => { e.stopPropagation(); sc.scrollTop -= sc.clientHeight * 0.8; };
    dn.onclick = (e) => { e.stopPropagation(); sc.scrollTop += sc.clientHeight * 0.8; };
    sc.onscroll = upd;
    requestAnimationFrame(upd);
    setTimeout(upd, 300);
  }
  function _hgRailActive() {
    const rail = _hgRailEl;
    const items = _HG.railItems;
    if (!rail || !items || !items.length) return;
    // a273R（用户精确描述「只在最上和最下」）：切 tab 后 offsetTop 在
    // content-visibility:auto 元素上返回估高（contain-intrinsic-size）而非
    // 真实位置——中间刻度估高 > scrollTop+80，二分全不命中=兜底 act=0。
    // 修：预计算 offsetTop 缓存（_hgRailCacheTops），二分在纯数值上跑。
    // 缓存刷新时机：切回 tab（onResumePoll）+ railSync 重建后 + 首次调用
    if (!_HG.railCacheTops || _HG.railCacheTops.length !== items.length) {
      _HG.railCacheTops = items.map(it =>
        (it.el && it.el.isConnected) ? it.el.offsetTop : -1);
    }
    const tops = _HG.railCacheTops;
    const _atBtm = _hgFlow.scrollHeight - _hgFlow.scrollTop - _hgFlow.clientHeight <= 4;
    const st = _hgFlow.scrollTop + 80;
    let act = -1;
    if (_atBtm) act = items.length - 1;
    else {
      // a273R2：offsetTop 在 content-visibility:auto + display:none 切换后
      // 不可信（估高≠真高）。双轨策略：有**可信缓存**（tab 可见期间建的）
      // 用缓存二分；无缓存/缓存可疑（结果落 0 但 scrollTop 不小）用
      // scroll 比例近似定位——近似保证中间跟随，宁可偏差不丢跟随
      let lo = 0, hi = items.length - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (tops[mid] >= 0 && tops[mid] <= st) { act = mid; lo = mid + 1; }
        else hi = mid - 1;
      }
      // 自愈：二分落空（act<0/0）但 scrollTop 明显不在顶部=布局数据不可信
      if (act <= 0 && _hgFlow.scrollTop > 200 && items.length > 2) {
        const ratio = _hgFlow.scrollTop /
          Math.max(1, _hgFlow.scrollHeight - _hgFlow.clientHeight);
        act = Math.min(items.length - 1, Math.max(0,
          Math.round(ratio * (items.length - 1))));
        // 顺手用当前滚动位置修正缓存（下次二分直接命中）
        if (act > 0 && act < items.length) {
          const el = items[act] && items[act].el;
          if (el && el.isConnected) {
            // 从近似锚点向两侧扩散，用真实 offsetTop 重建局部缓存
            for (let k = 0; k < items.length; k++) {
              const e2 = items[k] && items[k].el;
              if (e2 && e2.isConnected) tops[k] = e2.offsetTop;
            }
          }
        }
      }
    }
    if (act < 0) act = 0;
    const prev = rail.querySelector('.hg-rail-t.act');
    const _rsc2 = rail.querySelector('.hg-rail-scroll');
    const cur = _rsc2 ? _rsc2.children[act] : rail.children[act];
    if (prev === cur) return;
    if (prev) prev.classList.remove('act');
    if (cur) {
      cur.classList.add('act');
      const _rsc = rail.querySelector('.hg-rail-scroll');
      if (_rsc) {
        const want = (cur.offsetTop - _rsc.offsetTop) - _rsc.clientHeight / 2;
        if (Math.abs(want - _rsc.scrollTop) > 40
            && Math.abs(want - _rsc.scrollTop) < _rsc.scrollHeight) _rsc.scrollTop = want;
      }
    }
  }
  function _hgRailActiveRaf() {
    if (_railRaf) return;
    _railRaf = requestAnimationFrame(() => { _railRaf = 0; _hgRailActive(); });
  }
  function _hgRailBind() {
  if (_hgRailEl) _hgRailEl.addEventListener('click', (e) => {
    const t = e.target.closest('.hg-rail-t');
    if (!t) return;
    let it = _HG.railItems && _HG.railItems[+t.dataset.rk];
    if (!it) return;
    // 内网报告修复（P1）：失联不静默——①按稳定标识重找（v4 重建 DOM 后
    // el 失联但 data-turn-hi 还在）②重找失败再全量重同步一次按序号重取
    // ③仍失败给可见反馈（「点了没反应」是这类缺陷最难自助定位的形态）
    if ((!it.el || !it.el.isConnected) && it.key) {
      const rel = _hgFlow.querySelector(`.h-msg.user[data-turn-hi="${it.key}"]`);
      if (rel) it.el = rel;   // 顺手修缓存
    }
    if (!it.el || !it.el.isConnected) {
      try { _hgRailSync(); } catch (_) {}
      it = (_HG.railItems || [])[+t.dataset.rk];
      if (!it) return;
      if ((!it.el || !it.el.isConnected) && it.key) {
        const rel2 = _hgFlow.querySelector(`.h-msg.user[data-turn-hi="${it.key}"]`);
        if (rel2) it.el = rel2;
      }
      if (!it.el || !it.el.isConnected) {
        try { showBanner('该回合已不在当前视图，请刷新页面重试', 4000, true); } catch (_) {}
        return;
      }
    }
    // v3.5.207b（用户要求「点导轨点到底部就到底部，点到中间就到中间」）：
    // ①末刻度=视口贴 flow 底（原 block:'start' 只把最后回合头对齐视口顶，
    // 实测尾差 339px=「点了底部没到底」）；②RO 只读长内容（193 轮/10 万
    // px）smooth 动画慢且长距观感失控——即时跳转（主窗口保留 smooth）
    if (it.el && it.el.isConnected) {
      const _last = +t.dataset.rk === _HG.railItems.length - 1;
      if (_last) {
        // v3.5.212b（用户实锤「点末条动画没了直接跳底」）：末刻度同样走
        // 平滑滚动（RO 即时/主窗口 smooth），与中间刻度体验一致
        _hgFlow.scrollTo({ top: _hgFlow.scrollHeight, behavior: _HG.readonly ? 'auto' : 'smooth' });
        return;
      }
      it.el.scrollIntoView({ block: 'start',
        behavior: _HG.readonly ? 'auto' : 'smooth' });
      return;
    }
    // v4-only：未渲染回合（20 回合窗口外）由归档条入口承载——不再走
    // V3 的 _histRefresh 扩窗重拉（v4 下恒 no-op，已随批G 退役）
  });
  }
