// harness managers.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  async function paintVisionBtn() {
    let j = null;
    try { j = await (await fetch('/api/harness/vision_status')).json(); } catch(_) {}
    if (!visBtnEl) return;
    visBtnEl.innerHTML = _HG_EYE + ' 识图配置 <span class="hg-vstat ' +
      (j && j.ok && j.enabled ? 'ok' : 'off') + '">· ' +
      ((j && j.ok && j.enabled) ? '已启用（MCP）' : '未启用') + '</span>';
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
      const mapText = Object.entries(cfg.model_map || {})
        .map(([k, v]) => `${k}=${v}`).sort().join('\n');
      ov.innerHTML = `<div class="hg-modal hg-modal-vision"><div class="hg-modal-title">👁 识图配置</div>
        <div class="hg-modal-body hg-vision-hint">识图走 MCP 通道（analyze_image 工具，随会话常备，无后台进程）。此处配置 MCP 调用的识图模型与提示词，<b>保存即生效</b>。主会话模型是真多模态则直读，不经过这里。</div>
        <div class="hg-vision-row">
          <label class="hg-vision-switch"><input type="checkbox" data-hg-v-on${cfg.enabled ? ' checked' : ''}> 启用识图</label>
          <span class="hg-vision-state" style="font-size:11px;color:var(--muted);">MCP 通道 · 无后台进程</span>
        </div>
        <div class="hg-vision-grid">
          <label>识图模型（MCP 后端，需多模态；当前方案未命中下方映射时用此项）
            <select data-hg-v-model>${opts}</select></label>
        </div>
        <label class="hg-vision-prompt-lab">端点模型映射（每行一条：端点关键字=模型名——多方案适配，按当前 base_url 匹配，最长关键字命中优先）
          <textarea class="hg-vision-mm" data-hg-v-map spellcheck="false" style="height:56px;font-family:var(--font-mono);"
            placeholder="open.bigmodel.cn=glm-5.3-flash&#10;lanz.hikvision.com=Lanz-Medium-V">${esc(mapText)}</textarea></label>
        <label class="hg-vision-prompt-lab">多模态模型名单（逗号分隔，模型下拉的 👁 标记以此为准；名单外的模型一律走 MCP 识图通道）
          <input class="hg-vision-mm" data-hg-v-mm spellcheck="false"
                 value="${esc((cfg.mm_extra || []).join(', '))}"
                 placeholder="如：glm-5.3 flash, Lanz-Medium-V（前缀匹配，填一个即可覆盖其 [1M] 变体）"></label>
        <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
          <button class="btn ghost" data-hg-v-probe style="font-size:11px;">🔍 检测识图模型能否读图</button>
          <span data-hg-v-probe-out style="font-size:11px;color:var(--muted);"></span>
        </div>
        <label class="hg-vision-prompt-lab">识图提示词（作为识图请求的 system）
          <textarea class="hg-vision-prompt" data-hg-v-prompt spellcheck="false"></textarea></label>
        <div class="hg-modal-acts"></div></div>`;
      const acts = ov.querySelector('.hg-modal-acts');
      const close = (v) => { ov.remove(); resolve(v); };
      const ta = ov.querySelector('[data-hg-v-prompt]');
      const mapEl = ov.querySelector('[data-hg-v-map]');
      const modelEl = ov.querySelector('[data-hg-v-model]');
      const onEl = ov.querySelector('[data-hg-v-on]');
      const mmEl = ov.querySelector('[data-hg-v-mm]');
      ta.value = cfg.mcp_prompt || def.mcp_prompt || '';
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
        // v2.28.3：端点模型映射——发 "端点关键字=模型名" 字符串行（后端按此
        // 解析；此前误发 [k,v] 元组数组，后端 str() 后无 '=' 被静默丢弃）
        model_map: (mapEl.value || '').split(/\n+/).map(s => s.trim())
          .filter(x => x.includes('=')),
      }));
      ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
      ov.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
      _hgWrap.appendChild(ov);
      modelEl.focus();
    });
  }
  async function openRolesCfg() {
    let j = null;
    try { j = await (await fetch('/api/harness/roles')).json(); } catch(_) {}
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
      showBanner('👥 三角色配置已保存——模型槽/分级线随下条消息热更生效（agents 自动重生成），审计模式立即生效'
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
      const light = init.mode === 'light';
      const dm = init.default_model || '';
      const mkOpts = (cur) => {
        const ms = models.slice();
        if (cur && !ms.includes(cur)) ms.push(cur);   // 配置值不在当前方案表也保留可选项
        return ['<option value=""' + (cur ? '' : ' selected') + '>默认（按当前方案自动识别）</option>']
          .concat(ms.map(m => `<option value="${esc(m)}"${m === cur ? ' selected' : ''}>${esc(m)}</option>`))
          .join('');
      };
      // 设计者/审计者槽（v2.53）：读写 designer_model/reviewer_model 新键，
      // 留空=回退重池（heavy_model→自动）——与后端 resolve_agent_models
      // 回退链一致；旧 light/heavy 池键不再从面板暴露
      const designerCfg = cfg.designer_model || '';
      const reviewerCfg = cfg.reviewer_model || '';
      const mapText = Object.entries(cfg.model_map || {})
        .map(([k, v]) => `${k}=${v.executor},${v.coder}`).sort().join('\n');
      const am = cfg.audit_mode || 'auto';
      // 分级线三键：0 合法（最严档），不能用 || 兜底；缺键/非法回默认
      // 100/3/200（与后端 defaults 同源）
      const numOr = (v, d) => { const n = parseInt(v, 10);
        return Number.isFinite(n) ? Math.max(0, n) : d; };
      const l1 = numOr(cfg.l1_max_lines, 100);
      const l2l = numOr(cfg.l2_max_lines, 200);
      const dln = numOr(cfg.design_max_lines, 200);
      ov.innerHTML = `<div class="hg-modal hg-modal-vision hg-roles"><div class="hg-modal-title">👥 三角色配置<span class="hg-roles-mode">${light ? '轻主力' : '重模型直干'}</span></div>
        <div class="hg-modal-body">
          <div class="hg-roles-top">
            <label class="hg-vision-switch"><input type="checkbox" data-hg-r-on${cfg.enabled ? ' checked' : ''}> 启用三角色</label>
            <span class="hg-roles-modeinfo">当前形态：<b>${light ? '轻主力 · 直干+设计者+审计者' : '重模型直干 · 审计者兜底'}</b></span>
          </div>
          <details class="hg-roles-more"><summary>工作方式说明</summary>
            <div>双形态都<b>主会话直干所有活</b>（编码/执行/调试不派干活子代理）：主会话是轻模型 = 轻主力——配设计者 + 审计者两个代理；主会话是重模型（名字含 opus）= 直干 + 审计者兜底。保存后模型/分级线随下条消息热更生效（agents 自动重生成），审计模式立即生效。当前形态判定依据：${cfg.main_model ? `主会话槽显式配置 ${esc(cfg.main_model)}` : `实跑模型 ${esc(dm || '未设置')}（留空自动识别）`}。</div>
          </details>

          <div class="hg-roles-sec">模型分工</div>
          <div class="hg-roles-slot" title="主会话自己干所有活；显式配置优先参与形态判定（名字含 opus = 重模型直干，其余 = 轻主力），留空按实跑模型名自动识别">
            <span class="hg-roles-ico main">主</span>
            <span class="hg-roles-name">主会话<i>直干所有活 · 定形态</i></span>
            <select data-hg-r-main>${mkOpts(cfg.main_model || '')}</select>
          </div>
          <div class="hg-roles-slot" title="designer：只设计，出方案不干活。留空=回退代理池 heavy_model，再按当前方案自动识别">
            <span class="hg-roles-ico des">设</span>
            <span class="hg-roles-name">设计者<i>只设计 · 出方案</i></span>
            <select data-hg-r-designer>${mkOpts(designerCfg)}</select>
          </div>
          <div class="hg-roles-slot" title="reviewer：只审不改，PASS/FAIL 二选一。留空=回退代理池 heavy_model，再按当前方案自动识别">
            <span class="hg-roles-ico rev">审</span>
            <span class="hg-roles-name">审计者<i>只审不改 · PASS/FAIL</i></span>
            <select data-hg-r-reviewer>${mkOpts(reviewerCfg)}</select>
          </div>
          <div class="hg-roles-note">留空 = 回退代理池 → 按方案自动识别；显式配置优先</div>

          <div class="hg-roles-sec">分级线 <i>按单次直改行数 · 不计文件数 · 不做累计</i></div>
          <div class="hg-roles-line" title="单次直改总计 ≤ 此行数的小改（配置/常量/文案/注释级）主会话直接改，免审">
            <span>免审线</span><input type="number" min="0" max="100000" data-hg-r-l1 value="${l1}"><em>≤ 此行数直接改，免审</em>
          </div>
          <div class="hg-roles-line" title="单次直改超过此行数 = 大改，须审计者取证级全审；重模型形态即审计线（0=最严档）">
            <span>轻审线</span><input type="number" min="0" max="100000" data-hg-r-l2l value="${l2l}"><em>超线须审计者全审（0=最严）</em>
          </div>
          <div class="hg-roles-line" title="单次直改达到此行数的大改，动手前须先派设计者出方案——事中闸拦截+结算追责强制（0=不强制设计）">
            <span>设计线</span><input type="number" min="0" max="100000" data-hg-r-dl value="${dln}"><em>达线先出方案（0=不强制）</em>
          </div>
          <div class="hg-roles-line" title="回合结算兜底：盘点直改超线未派审计者——auto 自动续发要求补审，warn 仅红色警示，off 关闭">
            <span>审计模式</span>
            <select data-hg-r-am>
              <option value="auto"${am === 'auto' ? ' selected' : ''}>auto · 自动续发补审</option>
              <option value="warn"${am === 'warn' ? ' selected' : ''}>warn · 仅警示</option>
              <option value="off"${am === 'off' ? ' selected' : ''}>off · 关闭</option>
            </select><em>超线未审的兜底</em>
          </div>

          <div class="hg-roles-sec">端点角色映射 <i>按 base_url 匹配 · 优先于自动识别</i></div>
          <textarea class="hg-vision-mm" data-hg-r-map spellcheck="false" style="height:56px;font-family:var(--font-mono);"
            placeholder="open.bigmodel.cn=主会话模型,代理模型&#10;lanz.hikvision.com=Lanz-Flash,Lanz-Atuo">${esc(mapText)}</textarea>
          <div class="hg-roles-note">每行：端点关键字 = 主会话模型,代理模型（代理模型可省略 = 与主会话同）</div>
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
        // 三槽（空串=清除，回落自动识别/旧键降级）
        main_model: ov.querySelector('[data-hg-r-main]').value.trim(),
        // 设计者/审计者槽（v2.53 直白命名）：写 designer_model/reviewer_model
        // 新键，留空=回退重池/自动识别；旧 light/heavy 池键不再从面板写
        designer_model: ov.querySelector('[data-hg-r-designer]').value.trim(),
        reviewer_model: ov.querySelector('[data-hg-r-reviewer]').value.trim(),
        // 端点角色映射——发 "关键字=轻,重" 行（后端按行解析，与识图面板
        // model_map 的行式体验一致）
        model_map: (ov.querySelector('[data-hg-r-map]').value || '')
          .split(/\n+/).map(s => s.trim()).filter(x => x.includes('=')),
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
      ov.querySelector('[data-hg-r-main]').focus();
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
            `<input class="hg-prompt-note" placeholder="备注（如：中文注释规范）" value="${esc(it.note || '')}">` +
            `<select class="hg-prompt-scope">` +
            `<option value="global"${it.scope !== 'project' ? ' selected' : ''}>🌐 全局</option>` +
            `<option value="project"${it.scope === 'project' ? ' selected' : ''}>📁 项目</option>` +
            `</select>` +
            `<input class="hg-prompt-proj" placeholder="目录名" value="${esc(it.project || '')}"${it.scope === 'project' ? '' : ' style="display:none"'}${it.active === false ? ' title="当前项目不匹配（不会注入本会话）"' : ''}>` +
            `<button class="hg-prompt-onoff" title="启用/停用">${it.enabled ? '🟢' : '⚪'}</button>` +
            `<button class="hg-prompt-del" title="删除">✕</button></div>` +
            `<textarea class="hg-prompt-ta" spellcheck="false" placeholder="提示词正文…"></textarea>`;
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
