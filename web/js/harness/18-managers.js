// harness managers.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  async function paintVisionBtn() {
    let j = null;
    try { j = await (await fetch('/api/harness/vision_status' +
      (_HG.sid ? '?sid=' + encodeURIComponent(_HG.sid) : ''))).json(); } catch(_) {}
    if (!visBtnEl) return;
    // v3.5.37（用户实锤「识图 MCP 还显示开着」误导）：后端按当前会话模型
    // 形态回 mode——多模态（inline）会话没有 MCP 识图工具，徽章显示
    // 「多模态直读」；非多模态会话才显示「已启用（MCP）」
    const _inline = j && j.mode === 'inline';
    const stTxt = !(j && j.ok && j.enabled) ? '未启用'
      : (_inline ? '多模态直读' : '已启用（MCP）');
    visBtnEl.innerHTML = _HG_EYE + ' 识图配置 <span class="hg-vstat ' +
      ((j && j.ok && j.enabled) ? 'ok' : 'off') + '">· ' + stTxt + '</span>';
  }
  function hgVisionManager(init) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const cfg = { ...(init.vision || {}) };
      const def = init.defaults || {};
      const models = init.models || [];
      const curModel = cfg.model || '';
      const opts = ['<option value=""' + (curModel ? '' : ' selected') + '>默认（' + 'glm-5.3-flash）</option>']
        .concat(models.map(m => `<option value="${esc(m)}"${m === curModel ? ' selected' : ''}>${esc(m)}</option>`))
        .join('');
      // v3.5.39（用户拍板「改成下拉选择」）→ v3.5.44（实锤「多点几次直接溢出
      // 屏幕了；要的是和上面同款下拉选择」）→ v3.5.46（草图重构定稿）：
      // 人工判定整块删除，并入模型行——模型下拉 + 🔍自动检测 + 强制指定
      // 三控件一行（强制指定=写 mm_user[name]=true 压过一切自动判定）
      ov.innerHTML = `<div class="hg-modal hg-modal-vision"><div class="hg-modal-title">识图配置</div>
        <div class="hg-modal-body hg-vision-hint">识图走 MCP 通道（analyze_image 工具，随会话常备，无后台进程）。此处配置 MCP 调用的识图模型与提示词，<b>保存即生效</b>。主会话模型是真多模态则直读，不经过这里。</div>
        <div class="hg-vision-row">
          <label class="hg-vision-switch"><input type="checkbox" data-hg-v-on${cfg.enabled ? ' checked' : ''} name="hg_v_on"> 启用识图</label>
          <span class="hg-vision-state" style="font-size:11px;color:var(--muted);">MCP 通道 · 无后台进程</span>
        </div>
        <label class="hg-vision-prompt-lab">识图模型（MCP 后端，需多模态；换 API 方案后在此重选）
          <div class="hg-vision-grid" style="align-items:center;margin-bottom:0;">
            <select data-hg-v-model style="flex:1;min-width:0;">${opts}</select>
            <button class="btn ghost" data-hg-v-probe style="flex:none;font-size:11px;" title="自动检测：发张测试图让该模型读——答对颜色即多模态（结果缓存，二次点秒回）">自动检测</button>
            <button class="btn ghost" data-hg-v-force style="flex:none;font-size:11px;" title="强制指定：以你的判断为准——强制认为当前选中的模型是多模态（压过一切自动检测与缓存，探测抽风时用）；再点一次取消强制">强制指定</button>
          </div>
          <div data-hg-v-probe-out style="font-size:11px;color:var(--muted);margin-top:3px;min-height:14px;"></div>
        </label>
        <label class="hg-vision-prompt-lab">多模态模型名单（逗号分隔，模型下拉的 👁 标记以此为准；名单外的模型一律走 MCP 识图通道）
          <input name="hg_v_mm" class="hg-vision-mm" data-hg-v-mm spellcheck="false"
                 value="${esc((cfg.mm_extra || []).join(', '))}"
                 placeholder="如：glm-5.3 flash, Lanz-Medium-V（前缀匹配，填一个即可覆盖其 [1M] 变体）" name="hg_v_mm"></label>
        <label class="hg-vision-prompt-lab">识图提示词（作为识图请求的 system）
          <textarea name="hg_v_prompt" class="hg-vision-prompt" data-hg-v-prompt spellcheck="false"></textarea></label>
        <div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };
      const ta = ov.querySelector('[data-hg-v-prompt]');
      const modelEl = ov.querySelector('[data-hg-v-model]');
      const onEl = ov.querySelector('[data-hg-v-on]');
      const mmEl = ov.querySelector('[data-hg-v-mm]');
      // v3.5.46（用户拍板草图重构定稿）：模型行三控件——下拉 + 🔍自动检测 +
      // 「强制指定」按键。点击强制=写 mm_user[当前模型]=true（压过一切自动
      // 判定与缓存，探测抽风时用）；再点一次取消强制。原人工判定区块
      // （多行手写/行式下拉）随本重构删除
      const forceEl = ov.querySelector('[data-hg-v-force]');
      const _mmUser = cfg.mm_user || {};
      ta.value = cfg.mcp_prompt || def.mcp_prompt || '';   // v3.5.49 补回：v3.5.46 重构时漏搬——textarea 恒空, 保存空值会覆盖用户提示词
      const _normEq = (a, b) => {
        const n = x => String(x || '').split('[')[0].trim().toLowerCase();
        return n(a) && n(a) === n(b);
      };
      const _forcedKey = () => Object.keys(_mmUser).find(k => _mmUser[k] === true && _normEq(k, modelEl.value));
      const _forcePaint = () => {
        const on = !!_forcedKey();
        forceEl.textContent = on ? '已强制 ✓' : '强制指定';
        forceEl.classList.toggle('primary', on);
      };
      forceEl.onclick = () => {
        const m = modelEl.value.trim();
        if (!m) { forceEl.title = '请先在左侧下拉选择模型'; return; }
        const k = _forcedKey();
        if (k) { delete _mmUser[k]; }          // 已强制 → 取消
        else { Object.keys(_mmUser).forEach(x => { if (_normEq(x, m)) delete _mmUser[x]; });
               _mmUser[m.toLowerCase()] = true; }
        _forcePaint();
        forceEl.title = on_text();
        function on_text() {
          return _forcedKey() ? '已强制为多模态（压过一切自动判定）——再点一次取消'
                              : '未强制——点击强制认为该模型是多模态';
        }
      };
      _forcePaint();
      // v2.25：运行时探测——发张纯红测试图让该模型 Read，答对即多模态并
      // 自动并入名单（后端缓存，二次点秒回）。拿不准网关模型名是什么能力
      // 时点一下就行，不用猜也不用记。
      const probeBtn = ov.querySelector('[data-hg-v-probe]');
      const probeOut = ov.querySelector('[data-hg-v-probe-out]');
      probeBtn.onclick = async () => {
        const m = modelEl.value.trim() || init.default_model || '';
        if (!m) { probeOut.textContent = '请先在上方选择识图模型'; return; }
        probeBtn.disabled = true;
        probeOut.textContent = '探测中——直读测试（真多模态检测），约 5~60s…';
        try {
          const r = await fetch('/api/harness/mm_probe', {method:'POST',
            headers:{'Content-Type':'application/json'}, body: JSON.stringify({model: m})});
          const j = await r.json();
          if (j && j.ok) {
            // v2.28.1 两态：inline ✅ 真多模态 / mcp 🔧 走 MCP 通道（默认）
            const icon = j.mode === 'inline' ? '✅' : '🔧';
            probeOut.textContent = icon + ' ' + (j.msg || '') + (j.cached ? '（缓存）' : '');
            if (j.mode === 'inline') {
              const cur = (mmEl.value || '').split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean);
              if (!cur.some(x => m === x || m.startsWith(x) || x.startsWith(m)))
                mmEl.value = ((mmEl.value || '').replace(/\s+$/, '') ? mmEl.value.replace(/\s+$/, '') + ', ' : '') + m;
            }
          } else probeOut.textContent = '探测失败：' + ((j && j.err) || '未知');
        } catch(e) { probeOut.textContent = '探测失败：' + e; }
        probeBtn.disabled = false;
      };
      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('恢复默认提示词', false, () => { ta.value = def.mcp_prompt || ''; ta.focus(); });
      mkBtn('保存', true, () => close({
        enabled: onEl.checked,
        model: modelEl.value.trim(),
        mcp_prompt: ta.value.trim(),
        // v2.25：多模态手补名单随保存落盘（后端按前缀匹配，覆盖 [1M] 变体）
        mm_extra: (ov.querySelector('[data-hg-v-mm]').value || '')
          .split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean),
        // v3.5.46：人工判定表——「强制指定」按键点击时已实时写 _mmUser
        // （toggle 强制/取消），保存时原样落盘
        mm_user: _mmUser,
        // v3.5.19：model_map 端点映射退役——识图模型就是上面的主选择框
      }));
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
      _hgWrap.appendChild(ov);
      modelEl.focus();
    });
  }
  async function openRolesCfg() {
    let j = null;
    try { j = await (await fetch('/api/harness/roles' + (_HG.sid ? '?sid=' + encodeURIComponent(_HG.sid) : ''))).json(); } catch(_) {}
    if (!j || !j.ok) { showBanner('读取三角色配置失败', 3000, true); return; }
    const saved = await hgRolesManager(j);
    if (saved === null) return;                 // 取消不动
    try {
      const r = await fetch('/api/harness/roles', {method:'POST',
        headers:{'Content-Type':'application/json'}, body: JSON.stringify(saved)});
      const jr = await r.json();
      if (!jr.ok) { showBanner(jr.err || '保存失败', 3000, true); return; }
      // 后端 clamp 回显消费：分级线被自动收紧（l1>l2l 等）时当场提示
      // 实际写盘值与原因，不再静默钳制。
      const cl = (jr.clamped || []).map(function(n) { return n.reason; });
      // v3.5.99：后端已同步激活方案快照的 harness_roles 节（来回切方案
      // 不再还原三角色配置）；同步失败显式告警。
      if (jr.sync_err) cl.push(jr.sync_err);
      showBanner('👥 三角色配置已保存——档位/分级线随下条消息热更生效（agents 自动重生成），审核模式立即生效'
        + (jr.synced ? '；方案「' + jr.synced + '」快照已同步' : '')
        + (cl.length ? '；⚠ ' + cl.join('；') : ''), cl.length ? 9000 : 4200);
      _hgRolesFetch();                          // 缓存刷新（气泡角色徽章同源）
    } catch(e) { showBanner('保存失败：' + e, 3000, true); }
  }
  function hgRolesManager(init) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const cfg = { ...(init.roles || {}) };
      const models = init.models || [];
      const mode = init.mode || 'mid';   // v3.5.0 三态：light/mid/heavy
      const modeTxt = { light: '轻主力', mid: '中主力', heavy: '重主力' }[mode] || '中主力';
      const dm = init.default_model || '';
      const mkOpts = (cur, emptyTxt) => {
        const ms = models.slice();
        if (cur && !ms.includes(cur)) ms.push(cur);   // 配置值不在当前方案表也保留可选项
        return ['<option value=""' + (cur ? '' : ' selected') + '>'
                + (emptyTxt || '默认（按当前方案自动识别）') + '</option>']
          .concat(ms.map(m => `<option value="${esc(m)}"${m === cur ? ' selected' : ''}>${esc(m)}</option>`))
          .join('');
      };
      // v3.5.0 判定依据行：实跑名 vs 命中档位（档位匹配静默失败可见化）
      const rs = init.resolved || {};
      const _hitTier = mode === 'light' ? '轻档' : (mode === 'heavy' ? '重档' : '中档');
      // v3.5.21（用户定调「同档位轻优先，必须能区分」）：实跑模型同时命中
      // 多档（如轻中同值）时显式标注按轻档算——规则可见，不再含糊
      const _norm = s => String(s || '').split('[')[0].trim().toLowerCase();
      const _dmN = _norm(dm);
      const _hits = [rs.light, rs.mid, rs.heavy].filter(t => t && _norm(t) === _dmN);
      const _multi = dm && _hits.length > 1
        ? `（该模型同时映射 ${_hits.length} 档，按轻>中>重 取轻档）` : '';
      const basisTxt = `实跑 ${dm || '未设置'} → ${_hitTier}${_multi}`;
      // 设计者/审计者槽（v2.53）：读写 designer_model/reviewer_model 新键，
      // 留空=回退重池（heavy_model→自动）——与后端 resolve_agent_models
      // 回退链一致；旧 light/heavy 池键不再从面板暴露
      const designerCfg = cfg.designer_model || '';
      const reviewerCfg = cfg.reviewer_model || '';
      const am = cfg.audit_mode || 'auto';
      // 分级线三键：0 合法（最严档），不能用 || 兜底；缺键/非法回默认
      // 100/3/200（与后端 defaults 同源）
      const numOr = (v, d) => { const n = parseInt(v, 10);
        return Number.isFinite(n) ? Math.max(0, n) : d; };
      const l1 = numOr(cfg.l1_max_lines, 100);
      const l2l = numOr(cfg.l2_max_lines, 200);
      const dln = numOr(cfg.design_max_lines, 200);
      ov.innerHTML = `<div class="hg-modal hg-modal-vision hg-roles"><div class="hg-modal-title">👥 三角色配置<span class="hg-roles-mode">${modeTxt}</span></div>
        <div class="hg-modal-body">
          <div class="hg-roles-top">
            <label class="hg-vision-switch"><input type="checkbox" data-hg-r-on${cfg.enabled ? ' checked' : ''} name="hg_r_on"> 启用三角色</label>
            <span class="hg-roles-modeinfo">当前形态：<b>${mode === 'light' ? '轻主力 · 直干+设计+审核' : mode === 'heavy' ? '重主力 · 直干+派发自由（免强制分级）' : '中主力 · 直干+审核兜底'}</b></span>
          </div>
          <details class="hg-roles-more"><summary>工作方式说明</summary>
            <div>三形态<b>派发都自由</b>（通用子代理按需随时可派），档位差别只在强制项：实跑模型命中<b>轻档</b> = 轻主力——<b>设计+审核必须</b>（分级线全档）；命中<b>中档</b> = 中主力——<b>审核必须</b>（审计线）；命中<b>重档</b> = 重主力——<b>零强制 · 派发随意</b>（最信任档：有想派的随时派，设计/审核/通用子代理都行，强制项一个没有）。档位默认联动 API 配置三槽（Haiku→轻 / Sonnet→中 / Opus→重，换方案自动跟随），下方下拉可显式覆盖。<b>怎么算轻/中/重：实跑模型与哪档值相同（剥 [1M] 后缀、不分大小写）就算哪档；同一模型映射多档时按 轻&gt;中&gt;重 取轻档</b>（轻中同值时算轻主力——想让它当中档，把中档下拉显式选成不同模型）；未匹配任何档按中档。保存后档位/分级线随下条消息热更生效（agents 自动重生成），审核模式立即生效。当前判定：${esc(basisTxt)}。</div>
            <div class="hg-roles-sec" style="margin-top:8px;">代理模型细调 <i>默认自动取重档 · 一般无需改</i></div>
            <div class="hg-roles-slot" title="designer：只设计，出方案不干活。留空=回退重档 heavy_model，再按当前方案自动识别">
              <span class="hg-roles-ico des">设</span>
              <span class="hg-roles-name">设计<i>只设计 · 出方案</i></span>
              <select data-hg-r-designer>${mkOpts(designerCfg)}</select>
            </div>
            <div class="hg-roles-slot" title="reviewer：只审不改，PASS/FAIL 二选一。留空=回退重档 heavy_model，再按当前方案自动识别">
              <span class="hg-roles-ico rev">审</span>
              <span class="hg-roles-name">审核<i>只审不改 · PASS/FAIL</i></span>
              <select data-hg-r-reviewer>${mkOpts(reviewerCfg)}</select>
            </div>
          </details>

          <div class="hg-roles-sec">模型档位 <i>默认联动 API 三槽 · 可自由改（显式优先）</i></div>
          <div class="hg-roles-slot" title="轻档。留空=默认取当前 API 方案的 Haiku 槽（ANTHROPIC_DEFAULT_HAIKU_MODEL），显式选择优先。轻主力：直干+设计/审核强制（分级线全档）">
            <span class="hg-roles-ico light">轻</span>
            <span class="hg-roles-name">轻档<i>轻主力 · 设计+审核必须</i></span>
            <select data-hg-r-light>${mkOpts(cfg.light_model || '', '默认（Haiku 槽：' + (rs.light || '未映射') + '）')}</select>
          </div>
          <div class="hg-roles-slot" title="中档。留空=默认取当前 API 方案的 Sonnet 槽（ANTHROPIC_DEFAULT_SONNET_MODEL），显式选择优先。中主力：直干+审核必须">
            <span class="hg-roles-ico mid">中</span>
            <span class="hg-roles-name">中档<i>中主力 · 审核必须</i></span>
            <select data-hg-r-mid>${mkOpts(cfg.mid_model || '', '默认（Sonnet 槽：' + (rs.mid || '未映射') + '）')}</select>
          </div>
          <div class="hg-roles-slot" title="重档。留空=默认取当前 API 方案的 Opus 槽（ANTHROPIC_DEFAULT_OPUS_MODEL），显式选择优先。重主力：直干+派发自由，零强制">
            <span class="hg-roles-ico main">重</span>
            <span class="hg-roles-name">重档<i>重主力 · 零强制 · 派发随意</i></span>
            <select data-hg-r-heavy>${mkOpts(cfg.heavy_model || '', '默认（Opus 槽：' + (rs.heavy || '未映射') + '）')}</select>
          </div>
          <div class="hg-roles-note">档位留空 = 联动 API 配置三槽（Haiku→轻 / Sonnet→中 / Opus→重，换方案自动跟随）；也可在此显式选择覆盖默认。<b>同一模型映射多档时按 轻&gt;中&gt;重 优先</b>——如轻中两档同值（图中 flash 场景），实跑该模型算轻档（轻主力）；未匹配按中档</div>

          <div class="hg-roles-sec">分级线 <i>按回合内直改累计行数 · 不计文件数</i></div>
          <div class="hg-roles-line" title="回合内直改累计 ≤ 此行数的小改（配置/常量/文案/注释级）主会话直接改，免审">
            <span>免审线</span><input type="number" min="0" max="100000" data-hg-r-l1 value="${l1}" name="hg_r_l1"><em>≤ 此行数直接改，免审</em>
          </div>
          <div class="hg-roles-line" title="回合内直改累计超过此行数 = 大改，须审核取证级全审；中主力形态即审核线（0=最严档）">
            <span>轻审线</span><input type="number" min="0" max="100000" data-hg-r-l2l value="${l2l}" name="hg_r_l2l"><em>超线须审核全审（0=最严）</em>
          </div>
          <div class="hg-roles-line" title="回合内直改累计达到此行数的大改，动手前须先派设计出方案——事中闸拦截+结算追责强制（0=不强制设计）">
            <span>设计线</span><input type="number" min="0" max="100000" data-hg-r-dl value="${dln}" name="hg_r_dl"><em>达线先出方案（0=不强制）</em>
          </div>
          <div class="hg-roles-line" title="回合结算兜底：盘点直改超线未派审核——auto 自动续发要求补审，warn 仅红色警示，off 关闭">
            <span>审核模式</span>
            <select name="hg_r_am" data-hg-r-am>
              <option value="auto"${am === 'auto' ? ' selected' : ''}>auto · 自动续发补审</option>
              <option value="warn"${am === 'warn' ? ' selected' : ''}>warn · 仅警示</option>
              <option value="off"${am === 'off' ? ' selected' : ''}>off · 关闭</option>
            </select><em>超线未审的兜底</em>
          </div>

        </div>
        <div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };
      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('保存', true, () => close({
        enabled: ov.querySelector('[data-hg-r-on]').checked,
        // v3.5.19R：三档显式配置（空=默认联动 API 三槽 Haiku/Sonnet/Opus）
        light_model: ov.querySelector('[data-hg-r-light]').value.trim(),
        mid_model: ov.querySelector('[data-hg-r-mid]').value.trim(),
        heavy_model: ov.querySelector('[data-hg-r-heavy]').value.trim(),
        // 设计者/审计者槽（折叠在「工作方式说明」里）：留空=回退重档/自动识别
        designer_model: ov.querySelector('[data-hg-r-designer]').value.trim(),
        reviewer_model: ov.querySelector('[data-hg-r-reviewer]').value.trim(),
        // v3.5.15/18：model_map 从三角色链全面退役——识图端点映射走独立
        // /vision 端点写 harness_vision 节，本面板与此键再无关系
        audit_mode: ov.querySelector('[data-hg-r-am]').value,
        // 分级线三键（0 合法=最严档），parseInt 后 Number.isFinite
        // 判非法回默认（与后端 defaults 同源 100/3/200）
        l1_max_lines: (() => { const v = parseInt(
          ov.querySelector('[data-hg-r-l1]').value, 10);
          return Number.isFinite(v) ? Math.max(0, v) : 100; })(),
        // v2.52：l2_max_files 不再提交——判定只看单次行数，文件数档退役
        //（盘上旧值保留无害，后端 clamp 仍读它兜底）
        l2_max_lines: (() => { const v = parseInt(
          ov.querySelector('[data-hg-r-l2l]').value, 10);
          return Number.isFinite(v) ? Math.max(0, v) : 200; })(),
        // v2.54 设计线：0=不强制设计（与其余线「0=最严」语义不同）
        design_max_lines: (() => { const v = parseInt(
          ov.querySelector('[data-hg-r-dl]').value, 10);
          return Number.isFinite(v) ? Math.max(0, v) : 200; })(),
      }));
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
      _hgWrap.appendChild(ov);
      ov.querySelector('[data-hg-r-light]').focus();
    });
  }
  function hgPromptManager(items, cwd) {
    return new Promise((resolve) => {
      const ov = document.createElement('div');
      ov.className = 'hg-modal-ov';
      const list = items.map(it => ({ ...it }));   // 工作副本，保存才落库
      ov.innerHTML = `<div class="hg-modal hg-modal-prompt"><div class="hg-modal-title">📜 自定义提示词</div>
        <div class="hg-modal-body hg-prompt-hint">会话启动时注入（新建/复活）。🌐 全局对所有会话生效；📁 项目只对目录名匹配的会话生效（填目录名如「串口控制台Pro」）。备注是给自己看的标签。</div>
        <div class="hg-prompt-list"></div>
        <div class="hg-modal-acts"></div></div>`;
      const _hgListEl = ov.querySelector('.hg-prompt-list');
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };

      function render() {
        _hgListEl.innerHTML = '';
        list.forEach((it, idx) => {
          const card = document.createElement('div');
          card.className = 'hg-prompt-item' + (it.enabled ? '' : ' off');
          card.innerHTML =
            `<div class="hg-prompt-item-head">` +
            `<input class="hg-prompt-note" placeholder="备注（如：中文注释规范）" value="${esc(it.note || '')}" name="hg_prompt_note">` +
            `<select name="hg_prompt_scope" class="hg-prompt-scope">` +
            `<option value="global"${it.scope !== 'project' ? ' selected' : ''}>🌐 全局</option>` +
            `<option value="project"${it.scope === 'project' ? ' selected' : ''}>📁 项目</option>` +
            `</select>` +
            `<input class="hg-prompt-proj" placeholder="目录名" value="${esc(it.project || '')}"${it.scope === 'project' ? '' : ' style="display:none"'}${it.active === false ? ' title="当前项目不匹配（不会注入本会话）"' : ''} name="hg_prompt_proj">` +
            `<button class="hg-prompt-onoff" title="启用/停用">${it.enabled ? '🟢' : '⚪'}</button>` +
            `<button class="hg-prompt-del" title="删除">✕</button></div>` +
            `<textarea name="hg_prompt_ta" class="hg-prompt-ta" spellcheck="false" placeholder="提示词正文…"></textarea>`;
          const ta = card.querySelector('.hg-prompt-ta');
          ta.value = it.text || '';
          ta.oninput = (e) => { it.text = e.target.value; };
          card.querySelector('.hg-prompt-note').oninput = (e) => { it.note = e.target.value; };
          card.querySelector('.hg-prompt-scope').onchange = (e) => {
            it.scope = e.target.value;
            card.querySelector('.hg-prompt-proj').style.display = it.scope === 'project' ? '' : 'none';
          };
          card.querySelector('.hg-prompt-proj').oninput = (e) => { it.project = e.target.value.trim(); };
          card.querySelector('.hg-prompt-onoff').onclick = () => { it.enabled = !it.enabled; render(); };
          card.querySelector('.hg-prompt-del').onclick = () => { list.splice(idx, 1); render(); };
          _hgListEl.appendChild(card);
        });
        if (!list.length)
          _hgListEl.innerHTML = '<div class="hg-prompt-empty">还没有提示词条目。点下方「＋ 新增」创建。</div>';
      }

      const mkBtn = (label, primary, fn) => {
        const b = document.createElement('button');
        b.className = 'btn' + (primary ? ' primary' : '');
        b.textContent = label; b.onclick = fn;
        acts.appendChild(b);
        return b;
      };
      mkBtn('取消', false, () => close(null));
      mkBtn('＋ 新增', false, () => {
        list.push({ id: '', scope: 'global', project: '', note: '', text: '', enabled: true, active: undefined });
        render();
        _hgListEl.lastElementChild && _hgListEl.lastElementChild.querySelector('.hg-prompt-ta').focus();
      });
      mkBtn('保存', true, () => {
        // 空正文条目丢弃；scope=project 但目录名为空 → 提示防误伤
        if (list.some(it => it.scope === 'project' && !it.project)) {
          showBanner('项目条目必须填目录名（或改回全局）', 3000, true);
          return;
        }
        close(list.filter(it => (it.text || '').trim()));
      });
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') close(null);
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) close(list.filter(it => (it.text || '').trim()));
      });
      _hgWrap.appendChild(ov);
      render();
    });
  }
