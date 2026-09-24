// harness sse.js (v3.0 自 buildClaudeHarnessTab 拆出,定义体零改动,缩进保持原样)
  function handleEvent(o) {
    const typ = o.type;
    if (typ === 'system') {
      const sub = o.subtype;
      if (sub === 'init') {
        _HG.alive = true;
        // v2.35（P0-1）：stream-json 每回合起跑都发一条 system/init（stdin 开着
        // 实测）——第 2 个起=CLI 自发新回合（后台任务完成通知/协作回传续跑）。
        // 后端同规则已补置 busy（会话列表 5s 自愈轮询的方向源头），前端这里
        // 即时亮运行态不等轮询；revive 重启的新进程首 init 不在此列（闭包级
        // 计数跨 revive 连续，靠后端 send() 占位的路径不受影响）。
        _HG.initN = (_HG.initN || 0) + 1;
        if (_HG.initN > 1 && !_HG.busy) setBusy(true);
        else if (!_HG.busy) setBusy(false);
      } else if (sub === 'task_started' || sub === 'task_progress'
                 || sub === 'task_notification') {
        // v2.35（P1-4/P0-1②）：Task 生命周期系统事件（主链事件、不带
        // parent_tool_use_id，但带 tool_use_id 指回 Task 调用）——
        // · task_started：is_backgrounded 标记后台代理（主回合 result 不收
        //   掉它，收尾等 task_notification）；tool_use 事件丢失时兜底建行
        // · task_progress/task_notification：CLI 侧计的子代理用量
        //   （total_tokens/tool_uses/duration_ms）——assistant.message.usage
        //   被网关置零（实测 input/output 恒 0），这是唯一可靠用量源
        const tid = o.tool_use_id;
        // v2.37（P1-F①）：task_id → 友好名映射（协作行显示「审核·#2」这类，
        // 裸 id 收 title）
        if (o.task_id) {
          const lb = _AGENT_LABEL[o.subagent_type] || o.subagent_type || '';
          if (lb) _HG.peerNames[o.task_id] = lb;
        }
        // v2.37（P1-E）：协作包装（后台+非角色类型）——不开实况窗格 tab
        // （独立会话事件流不经过本会话，开了必空白；旧版本误开的就地清掉），
        // 建 collab 档案供面板 C 区协作行展示；回传定格走下方严格配对
        // v2.47（需求2）：打破「collab 不开段」——v2.37 当年不开是因为无实时
        // 数据源（开了必空白），现在 subagent_tail 轮询（v2.46）+ 转写三源已
        // 就绪：task_started 即建段壳（段头「协作 · 名字/类型」+状态点+秒表，
        // 插在当前组末尾=SendMessage 行后，时间排序天然成立），过程行由轮询
        // 从子代理转写增量喂入（见 _subThinkPollTick/_subTailFetch）。
        // taskId 修正：与真实代理同款 peerSent 反查（P4 实证 input.to=真实
        // agentId，与 subagents/agent-<id>.jsonl 同名）——包装 task_id 无转写，
        // 落它=轮询/回放/回填三路全断
        if (sub === 'task_started'
            && _isCollabWrap(o.subagent_type, o.is_backgrounded)) {
          _subDrop(tid);
          if (tid) {
            const _to = (_HG.peerSent || {})[tid];
            const _real = (_to && /^[0-9a-zA-Z_-]{8,64}$/.test(String(_to)))
              ? String(_to) : '';
            (_HG.agents || (_HG.agents = {}))[tid] = {
              type: o.subagent_type || 'Task', desc: o.description || '',
              t0: Date.now(), done: false, doneAt: 0,
              collab: true, bg: true, taskId: _real || (o.task_id || '') };
            // 段头名字优先用转交收件人（与「已转交」线同名对齐），否则角色
            // 类型名。段不挂 hgSub（无实况流，窗格钮不画）；真实 id 在手则
            // 建段即落 hgSubr——运行中即可「▣ 回放」围观转写，也是切会话
            // 往返后 DOM 兜底轮询的 id 来源（随快照携带）
            _subBlkGet(tid, { live: true, collab: true, bg: true, fold: true,
              label: '协作 · ' + ((_to && String(_to).slice(0, 24))
                || _AGENT_LABEL[o.subagent_type] || o.subagent_type || '代理'),
              model: '', type: o.subagent_type || 'Task',
              desc: o.description || '', done: false });
            if (_real) {
              const _cb = _HG.subBlk && _HG.subBlk[tid];
              if (_cb && _cb.head && _cb.root) {
                _cb.head.dataset.hgSubr = _real;
                _cb.head.dataset.hgSubType = o.subagent_type || 'Task';
                _cb.head.dataset.hgSubDesc = String(o.description || '').slice(0, 120);
                // v2.47R（复审2）：全喂持久标记——peerSent 真实 id 命中（确为
                // SendMessage 续派）才落，随快照携带。档案缺失时全喂判定唯一
                // 依据；不能看 hgSubr/data-hg-collab 双证——_subBlkFinish 对
                // 所有段落 hgSubr（误杀形态完成瞬间也会落），双证会被攻破
                _cb.root.dataset.hgFullfeed = '1';
                _subBlkActsPaint(_cb);
              }
            } else if (!_to) {
              // 误杀形态（collab 判定命中但无 peerSent=非 SendMessage 续派）：
              // 真实后台代理，事件流照常到达——补 hgSub 实况入口（与 v2.45
              // 运行段行为一致，围观不断路）。data-hg-collab 保留（无转写占位
              // 有内容守卫不误伤）；hgFullfeed 不落（全喂判定永不命中——事件
              // 流已覆盖，全喂必重复）
              const _cb = _HG.subBlk && _HG.subBlk[tid];
              if (_cb && _cb.head) {
                _cb.head.dataset.hgSub = tid;
                _subBlkActsPaint(_cb);
              }
            }
            renderSideStatus();
          }
        } else if (tid) {
          if (!_HG.agents && sub === 'task_started') _HG.agents = {};
          let a = _HG.agents && _HG.agents[tid];
          if (!a && _HG.agents && sub === 'task_started') {
            // 兜底建档（Task tool_use 已建档时零改动）：t0 用当下近似
            a = _HG.agents[tid] = {
              type: o.subagent_type || 'Task', desc: o.description || '',
              t0: Date.now(), done: false, doneAt: 0 };
            // v3.2.6：tool_use 丢失的兜底派发也补单行任务卡（子代理段已隐，
            // 无行=派发在主流不可见；'Task' 非 explore → 直挂时间线）
            if (!_HG.rowById[tid]) {
              const _agRow = _hgAgentRowBuild(tid, a.type, a.desc);
              _HG.rowById[tid] = _agRow;
              drawerCount('Task');
              _tlPlace(_agRow, 'Task', null);
            }
          }
          if (a) {
            if (sub === 'task_started') {
              a.bg = !!o.is_backgrounded;
              // v2.46R（P4）：SendMessage 续派的包装任务 task_id 是 CLI 包装
              // 新 id（peer-pair 审计实证异形 id 无转写），轮询/回填要的是
              // 真实 agentId——SendMessage tool_use 建线时已记
              // peerSent[tid]=input.to（8faf 会话实证 to=真实 id，与
              // subagents/agent-<id>.jsonl 同名），命中即用真实 id
              const _realTo = (_HG.peerSent || {})[tid];
              a.taskId = (_realTo && /^[0-9a-zA-Z_-]{8,64}$/.test(String(_realTo)))
                ? String(_realTo) : (o.task_id || '');
              // v3.2.6R（审计F1）：agentId 即刻回写单行卡——不等完成（切走
              // 会话时行已自带 hgSubr，回放入口随快照存活）
              if (a.taskId && /^[0-9a-zA-Z_-]{8,64}$/.test(a.taskId))
                _hgAgentRowBindAid(tid, (_HG.rowById || {})[tid]);
            } else {
              // v2.35.1（F3）：用量与收尾解耦——task_notification 是完成信号，
              // usage 缺失（失败态通知常见）也必须收档，否则面板/输入框永久
              // 卡「运行中」；有 usage 才记 tokens/工具数
              if (o.usage) {
                a.tokens = o.usage.total_tokens || 0;
                a.toolN = o.usage.tool_uses || 0;
              }
              if (sub === 'task_notification' && !a.done) {
                a.done = true; a.doneAt = Date.now();
                a.err = !!(o.status && o.status !== 'completed'
                           && o.status !== 'success');
                a.result = String(o.summary || '').trim().slice(0, 400) || a.result;
                _subClose(tid, a.err);
                // v3.2.6：单行任务卡定格（tool_result 丢失的兜底路径也要收
                // 徽章；正常路径 renderOneToolResult 先到，此处幂等覆写）
                _hgAgentRowState(tid, a.err, a.result);
              }
            }
            renderSideStatus();
          } else if (sub === 'task_notification') {
            // v2.43.1（R-FAIL1）：档案缺失（切会话往返 agents 清空）但段 DOM
            // 在 → 完成信号直达段头定格；aid 用通知自带的 task_id（与
            // task_started 同源），hgSubr 靠它补上
            // v2.47（需求2）：aid 优先 peerSent 反查的真实 agentId（协作段
            // 的包装 task_id 无转写，落它回放必空）——与 task_started 建档
            // 同源；名字形态（非 id）不可作转写定位，校验后回退
            const ab = _subBlkAdopt(tid);
            if (ab && !ab.root.classList.contains('done')) {
              const _pto = String(((_HG.peerSent || {})[o.tool_use_id]) || '');
              _subBlkFinish(tid,
                !!(o.status && o.status !== 'completed' && o.status !== 'success'),
                (/^[0-9a-zA-Z_-]{8,64}$/.test(_pto) ? _pto : '') || (o.task_id || ''));
              renderSideStatus();
            }
          }
        }
        // v2.37（P1-F②）：协作包装的完成通知——严格按名配对定格对应转交线
        // （不命中不兜底，防误冻无关在途线）。对有档案的真实子代理同样尝试
        // （它们无转交线，strict 不命中即 no-op）
        // v2.39 勘误：旧注释称「task_id 即 to 的 agentId 实测同源」——实为
        // CLI 包装新 id 与 to 恒不相等（回传气泡不显示的根因，见下）
        if (sub === 'task_notification') {
          const sum = String(o.summary || '').trim().slice(0, 120);
          // v2.39：SendMessage 续派的包装任务——task_id 是 CLI 包装新 id，
          // 先按建线时记的 tool_use_id→to 映射反查原线名（peerSent），命中
          // 即原线精确配对；原有 task_id/subagent_type 两级兜底不变。
          const sentTo = (_HG.peerSent || {})[o.tool_use_id];
          const _hit = _hgPeerFreezeByName(sentTo, sum, true)
              || _hgPeerFreezeByName(o.task_id, sum, true)
              || _hgPeerFreezeByName(o.subagent_type, sum, true);
          if (_hit) renderSideStatus();
          // v2.37R3（复审C）：仅协作语境上报（该 task 是 collab 档案，或本
          // 会话存在 pending 转交线）——普通 Task 子代理完成不记，防
          // paired=false 淹没取证信号；同源假设失效案例仍全落日志
          const _rec = tid ? ((_HG.agents || {})[tid] || {}) : {};
          if (_rec.collab || _hgPeerPending()) {
            try {
              fetch('/api/harness/peer_pair_log', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sid: _HG.sid, task: o.task_id || '',
                                       name: (_hit && _hit.dataset.peer) || '', ok: !!_hit }) })
                .catch(() => {});
            } catch(_) {}
          }
        }
      } else if (sub === 'status') {
        // v2.7：压缩状态（实测 CLI 事件：status:"compacting" 开始 / "requesting" 恢复）
        // v2.20：压缩是长动作（几十秒），只在底栏小胶囊提示不够醒目——
        // 消息流里插动态分割线（耗时秒表 + 压缩对象规模；CLI 不吐进度
        // 百分比，不编假数字）
        if (o.status === 'compacting') {
          if (!_HG.compacting) {
            _HG.compacting = true;
            _HG.compactSid = _HG.sid;   // v2.3.13：归属会话——计时器不许把线画进别的会话
            _HG.compactT0 = Date.now();
            try { _HG.compactUsed = (JSON.parse(localStorage.getItem(_hgCtxKey(_HG.sid)) || 'null') || {}).used || 0; } catch(_) { _HG.compactUsed = 0; }
            grpFinalize(true);
            renderCompaction(false);
            clearInterval(_HG.compactTimer);
            _HG.compactTimer = setInterval(() => {
              if (!_HG.compacting) return clearInterval(_HG.compactTimer);
              renderCompaction(false);
            }, 1000);
          }
          actWord('正在压缩上下文…');
        } else {
          if (_HG.compacting) _hgCompactionEnd();
          actWord(null);
        }
      } else if (sub === 'api_error' || sub === 'error') {
        renderRaw('⚠ ' + (o.error ? JSON.stringify(o.error).slice(0, 200) : JSON.stringify(o).slice(0, 200)));
      }
    } else if (typ === 'assistant') {
      const blocks = (o.message || {}).content || [];
      const isSub = !!o.parent_tool_use_id;
      // v2.35（P0-1 兜底）：主链 assistant 事件到达而前端还认为空闲 = 一条
      // 没观察到起点的回合正在跑（后端同规则已置 busy，这里即时亮，不等
      // 5s 自愈轮询——轮询间隔内徽章空窗正是用户看到的「运行状态消失」）
      if (!isSub && !_HG.busy && _HG.sid) setBusy(true);
      // v2.20：网关下 result 事件的 usage 常缺失（用户实测环恒 0%）——
      // assistant 事件的 message.usage 同口径（转写实测有值：input+cache_read+
      // cache_creation），到达即刷环，不依赖 result
      if (!isSub && (o.message || {}).usage)
        renderCtxRing({ usage: o.message.usage, modelUsage: o.modelUsage });
      // v2.35（P1-4）：子代理实跑模型——assistant 事件自带 message.model
      // （网关映射后的真名，优先于 frontmatter 预显示），首见即记入档案
      if (isSub && o.parent_tool_use_id && (o.message || {}).model
          && _HG.agents && _HG.agents[o.parent_tool_use_id]) {
        const _sa = _HG.agents[o.parent_tool_use_id];
        if (_sa.model !== o.message.model) {
          _sa.model = o.message.model;
          if (_sub.tabs[o.parent_tool_use_id]
              && _sub.tabs[o.parent_tool_use_id].model !== o.message.model) {
            _sub.tabs[o.parent_tool_use_id].model = o.message.model;
            _subTabsPaint();
          }
          // v2.43：段头标识随实跑模型刷新（段可能尚未建——_subBlkPaint 只画
          // 已建段，不建段不编造）
          _subBlkPaint(o.parent_tool_use_id,
            { label: _AGENT_LABEL[_sa.type] || _sa.type || '子代理',
              model: _sa.model, type: _sa.type, desc: _sa.desc });
          renderSideStatus();
        }
      }
      for (const b of blocks) {
        // v2.43：子代理事件全部入段（_subThink/_subText/renderToolUse(isSub)）
        // ——不再碰主链思考抽屉/正文气泡/run 归组/组统计；主链的 thinking
        // 段与 run 状态不被子代理事件打断（两路流各自独立）
        if (b.type === 'thinking' && b.thinking) {
          if (isSub) _subThink(o.parent_tool_use_id, b.thinking);
          else { closeRun(); appendThinking(b.thinking); }
        }
        else if (b.type === 'text' && b.text && b.text.trim()) {
          if (isSub) _subText(o.parent_tool_use_id, b.text);
          else { endThinking(); closeRun(); renderAsst(b.text, (o.message || {}).model || _HG.model || ''); }
        }
        else if (b.type === 'tool_use') {
          if (!isSub) endThinking();
          // v2.32 面板：TodoWrite 更新任务清单 + 首见时刻打标（事件无时间戳，
          // 近似值）+ 记最近清单行 id（点任务项跳消息流用）
          // v2.43：主链专属——子代理内部清单不再覆盖主会话面板
          if (b.name === 'TodoWrite' && !isSub && b.input && Array.isArray(b.input.todos)) {
            _HG.todos = b.input.todos;
            const d = _hgDyn(), now = Date.now();
            if (b.id) d.todoRowId = b.id;
            for (const t of _HG.todos) {
              const key = t.content || '';
              if (!(key in d.todoSeen)) d.todoSeen[key] = now;
            }
            renderSideStatus();
          }
          if ((b.name === 'Task' || b.name === 'Agent') && b.id && !isSub) {
            // v2.37（P1-E）：协作包装（后台+非角色类型）——SendMessage 委托的
            // 独立会话被 CLI 包装成后台 Task：无本会话事件流，开实况 tab 必
            // 空白。不开 tab、不建代理档（C 区协作行由同委派的转交线派生，
            // 数据源单一不重复）；旧版本已开的空白 tab 就地清掉
            const _ty = (b.input && (b.input.subagent_type || b.input.agent_type)) || b.name;
            if (_isCollabWrap(_ty, b.input && b.input.run_in_background)) {
              _subDrop(b.id);
            } else {
              (_HG.agents || (_HG.agents = {}))[b.id] = {
                type: _ty,
                desc: (b.input && b.input.description) || '',
                t0: Date.now(), done: false, doneAt: 0,
                // v2.35（P1-4）：起跑即预显模型——~/.claude/agents frontmatter
                // （_hgAgentModels 惰拉缓存）；子代理事件到达后以实跑
                // message.model 覆盖。读不到（内置代理 Explore/Plan 等）标「主链模型」
                model: _hgAgentModelPre(_ty) };
              _subOpen(b.id, _HG.agents[b.id].type, _HG.agents[b.id].desc);   // v2.33：窗格开 tab
            }
            renderSideStatus();
          }
          // v2.32 面板：回合内工具计数（主流工具；子代理内部调用不算）
          if (!isSub && b.name !== 'TodoWrite') _hgDyn().turnTools++;
          // v2.28.5：识图双通道——网关名（主通道，服务端执行无本地事件）与
          // 本地名 mcp__vision__analyze_image（兜底，客户端执行）。客户端执行
          // 的识图调用出 📤 转交线+秒表（替代工具卡），tool_result 到达时
          // 定格对应线并渲染 📥 回传气泡；按 id 记线，并行多图各对各的线
          if (!isSub && (b.name === 'mcp__vision__analyze_image'
                         || b.name === 'mcp__4_5v_mcp__analyze_image')) {
            const el = renderPeerRelay('识图');
            (_HG.visionCalls || (_HG.visionCalls = {}))[b.id] = el;
          } else {
            renderToolUse(b, isSub, o.parent_tool_use_id);
            // v2.27.3：转交识图/其他会话 = 强过程反馈，分割线比收起的工具行显眼
            // v2.39：记 tool_use_id → to 映射——SendMessage 续派后台代理时 CLI
            // 包装成新 Task，task_notification.task_id 是包装后的新 id，与线的
            // data.peer(=input.to) 永不相等 → strict 配对恒 miss → 线被标「状态
            // 未知」回传气泡不显示（用户实锤）。notification 时按 tool_use_id
            // 反查此映射即命中原线。
            if (!isSub && b.name === 'SendMessage' && b.input && b.input.to) {
              (_HG.peerSent || (_HG.peerSent = {}))[b.id] = b.input.to;
              // v2.49：协作归一子代理段——SendMessage 转交线隐藏（数据锚全保留：
              // dataset.t0/peer/done/psum 照写，面板协作行/定格配对/快照序列化
              // 链路不动），识图转交原形态保留（唯一例外）
              const _rEl = renderPeerRelay(b.input.to);
              if (_rEl && !String(b.input.to).includes('识图'))
                _rEl.style.display = 'none';
              // v2.58：续派（to=agentId 形态）立即建**新段**——轮询/回传/回填
              // 全部归属新段。旧实现等首个子代理事件才兜底建段（常缺失），续审
              // 内容经轮询流回旧段（用户实锤「咋又跑上一个审计会话里去了」）。
              // 识图不建（转交通道不同）
              if (/^[0-9a-zA-Z_-]{8,64}$/.test(String(b.input.to))) {
                const _aid = String(b.input.to);
                (_HG.agents || (_HG.agents = {}))[b.id] = {
                  type: 'SendMessage', desc: '', t0: Date.now(),
                  done: false, doneAt: 0, collab: true, bg: true, taskId: _aid };
                const _disp2 = (_HG.peerNames || {})[_aid] || _aid;
                const _nb2 = _subBlkGet(b.id, { live: true, collab: true,
                  bg: true, fold: true,
                  label: '审核 · ' + String(_disp2).slice(0, 24),
                  model: '', type: 'SendMessage', desc: '', done: false });
                if (_nb2) {
                  _nb2.head.dataset.hgSubr = _aid;
                  _nb2.head.dataset.hgSubType = 'SendMessage';
                  _nb2.root.dataset.hgFullfeed = '1';
                  _subBlkActsPaint(_nb2);
                }
                // 轮询/回传归属切换：该 agentId 的活跃段=新段（旧段即使档案
                // 未 done 也不再吃增量；offset 账共享——同一转写文件连续 append）
                (_HG.subTailSeg || (_HG.subTailSeg = {}))[_aid] = b.id;
              }
            }
          }
        }
      }
      // v2.33：子代理消息分流进实时窗格（主 flow 照旧画灰色 sub 行，双处显示）
      if (isSub) _subFeed(o.parent_tool_use_id, blocks);
      _hgScrollBottom();
    } else if (typ === 'user') {
      // v2.3.12：/compact 摘要行不渲染——它是模型续命记忆，显示成用户气泡是噪音
      // （历史重建路径后端已拦成 renew 行，这里挡实时流里漏网的）
      if (o.isCompactSummary) return;
      const c0 = (o.message || {}).content;
      // v2.33：子代理内部的 tool_result 也分流进窗格（user 事件同带
      // parent_tool_use_id；不属于已跟踪 tab 的忽略）
      // v2.43：结果同时挂回主 flow 段内工具行（段不依赖窗格 tab 存活——
      // tab 被上限逐出/✕ 关闭后徽章照常定格）
      if (Array.isArray(c0) && o.parent_tool_use_id
          && (_sub.tabs[o.parent_tool_use_id] || (_HG.subRows || {})[o.parent_tool_use_id]))
        for (const b of c0)
          if (b && b.type === 'tool_result') {
            // v2.55R：窗格回点统一收口进 _subToolResult（其尾部调 _subResult）——
            // 旧并联写法在 _subToolResult 自身镜像窗格后会造成双路径竞争
            _subToolResult(o.parent_tool_use_id, b);
          }
      // v2.32 面板：子代理回场——tool_result 对上在跑的 Task 即完成，
      // 顺手存结果摘要/失败标志（面板完成行展示用，纯前端两行）
      // v2.35：后台 Task（run_in_background）的 tool_result 只是「已派出」
      // 确认——代理还在跑，收尾等 task_notification（bg 标记来自 task_started）
      // v2.43.1（R-FAIL1）：档案缺失分支——切会话往返后 _HG.agents 被清空，
      // 重连回放的完成 tool_result 在旧代码三路全早退（agents 判空直跳），
      // 段头永久假「运行中」。兜底：段 DOM 在（快照恢复的 .h-subblock）即
      // 直接定格，agentId 从结果文本提（与下方档案路径同源正则）
      if (Array.isArray(c0)) {
        let hitAgent = false;
        for (const b of c0) {
          if (!(b && b.type === 'tool_result')) continue;
          const a = (_HG.agents || {})[b.tool_use_id];
          if (a && !a.done && !a.bg) {
            a.done = true;
            a.doneAt = Date.now();
            a.err = !!b.is_error;
            a.result = resultText(b).slice(0, 400);
            // v2.38：agentId 落档——Task tool_result 文本自带「agentId: xxx」
            //（与 task_started 的 task_id 同源），回放窗格靠它定位子代理转写
            a.agentId = a.taskId
              || (resultText(b).match(/(?<![a-zA-Z])agentId[:"':\s]+([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
            _subClose(b.tool_use_id, a.err);   // v2.33：窗格 tab 定格 ✓/✗
            hitAgent = true;
          } else if (!a) {
            const ab = _subBlkAdopt(b.tool_use_id);
            if (ab && !ab.root.classList.contains('done')) {
              const _aid = (resultText(b).match(/(?<![a-zA-Z])agentId[:"':\s]+([0-9a-zA-Z_-]{8,64})/i) || [])[1] || '';
              _subBlkFinish(b.tool_use_id, !!b.is_error, _aid);
              hitAgent = true;
            }
          }
        }
        if (hitAgent) renderSideStatus();
      }
      // v2.28.3：识图 MCP 回传——按 tool_use_id 在 pending 线里对号，
      // 定格它自己的分割线+渲染 📥 气泡（并行多图互不串线）
      if (Array.isArray(c0) && _HG.visionCalls) {
        const tr = c0.find(b => b && b.type === 'tool_result'
          && _HG.visionCalls[b.tool_use_id]);
        if (tr) {
          const el = _HG.visionCalls[tr.tool_use_id];
          delete _HG.visionCalls[tr.tool_use_id];
          const vtxt = Array.isArray(tr.content)
            ? tr.content.filter(x => x && x.type === 'text').map(x => x.text).join('\n')
            : String(tr.content || '');
          // 先定格本线再画气泡。renderPeer 的按名配对已排除识图跟踪中的线
          // （v2.35.2 R1），不会误冻还在跑的并行兄弟线；下方 pw 摘还仅剩
          // 单槽兼容兜底路径在用
          const pw = _HG.peerWait;
          _HG.peerWait = null;
          _hgVisionFreeze(el, !!tr.is_error);
          renderPeer('识图', vtxt.trim() || '（识图失败，无返回内容）');
          if (pw && pw.el !== el) _HG.peerWait = pw;   // 他线还在等，还回去继续计时
          _hgScrollBottom();
          return;
        }
      }
      // v2.27.3：跨会话回传（识图结论等）——专属气泡，不再凭空消失
      let peerText = '';
      if (typeof c0 === 'string' && c0.trim().startsWith('Another Claude session sent a message'))
        peerText = c0;
      else if (Array.isArray(c0)) {
        const tb = c0.find(b => b && b.type === 'text' && typeof b.text === 'string'
          && b.text.trim().startsWith('Another Claude session sent a message'));
        if (tb) peerText = tb.text;
      }
      if (peerText) {
        const nm = peerText.match(/from-name="([^"]*)"/);
        const body = peerText.match(/<cross-session-message[^>]*>([\s\S]*)<\/cross-session-message>/);
        renderPeer(nm ? nm[1] : '其他会话', (body ? body[1] : peerText).trim());
        return;
      }
      // v2.37（P1-F②）：agent-message 通知形态的协作回传——CLI 对 agent 会话
      // （含 SendMessage 委托的独立会话/协作包装 task）回传的另一包装，此前
      // 不被任何回传路径识别：原始 XML 被当普通 user 气泡渲染、对应转交线
      // 永远停在「等待结论回传」。识别→提取发信方与正文→renderPeer（内部
      // 按名配对定格转交线）。v2.37R2（复审5）：必须开闭标签对齐才判——
      // 用户手打的半个 <agent-message 标签不得误触发
      let agMsg = '';
      const _AG_MSG_RE = /<agent-message[^>]*>[\s\S]*<\/agent-message>/;
      if (typeof c0 === 'string' && _AG_MSG_RE.test(c0)) agMsg = c0;
      else if (Array.isArray(c0)) {
        const tb2 = c0.find(b => b && b.type === 'text' && _AG_MSG_RE.test(b.text || ''));
        if (tb2) agMsg = tb2.text;
      }
      if (agMsg) {
        const anm = agMsg.match(/from-name="([^"]*)"/) || agMsg.match(/\bname="([^"]*)"/);
        const abody = agMsg.match(/<agent-message[^>]*>([\s\S]*?)<\/agent-message>/);
        renderPeer(anm ? anm[1] : '协作代理',
                   (abody ? abody[1] : agMsg.replace(/<[^>]+>/g, '')).trim());
        return;
      }
      // 用户真实消息打断工具 run；工具结果事件不动 run（rendersNothing 思想）
      if (!Array.isArray(c0) || !c0.some(b => b && b.type === 'tool_result')) closeRun();
      const hasToolResult = Array.isArray(c0) && c0.some(b => b && b.type === 'tool_result');
      // v2.43：子代理 tool_result 不走主链 renderToolResult——段内工具行已从
      // rowById 迁到 _HG.subRows（旧路径会把段内结果画成主链执行抽屉的孤立
      // 结果行），段内配对在上方 _subToolResult 完成
      if (!o.isSynthetic && !o.parent_tool_use_id && hasToolResult) {
        renderToolResult(o);
        _hgScrollBottom();
      }
    } else if (typ === 'result') {
      _hgCompactionEnd();                  // v2.20：status 恢复事件若丢，result 兜底收压缩态
      endThinking();
      closeRun();
      _hgVisionSweep(true);                // v2.28.3：回合终结算清未回传的识图线
      // v2.32：回合终结——还在跑的子代理统一收尾（收不到 tool_result 的
      // 结束都不标失败；中断/退出的收尾在各自分支标「已中断」）
      _hgAgentsSweep(false);
      _subEnd();                           // v2.33：窗格收起（跑完随回合结束消失）
      _hgPeerVerifyPending();              // v2.37R6（兜底复核②）：pending 线追溯核实
      _hgTurnEnd(o.subtype === 'success' ? 'ok' : 'error',
                 typeof o.duration_ms === 'number' ? o.duration_ms : 0);
      _hgTurnSumRow();                     // v3.1：ZCode 式回合摘要行（查阅 · N 搜索 · N 文件）
      // v3.2.1R(F2/R2-1)：快照恢复后回合在切走期间结束——重放的 result 到达时
      // _HG.grp 已被 switchTo 置空，grpFinalize 早退 → 尾组永不定稿。认回尾组
      // 再定稿（_hgTailAdopt，phRemove 的 DOM 扫顺手清冻结占位气泡）；认回
      // 时传 hist——工时缺事实落无数字「已工作」，不用当前时钟虚增切走期间
      // 的空闲段（R2-3）
      const _adopted = _hgTailAdopt();
      // v3.2：定稿带冻结工时（CLI duration_ms——历史「已工作」绝不吃当前时钟）
      // 与中断标记（subtype 非 success → 「已停止」）
      grpFinalize(true, { durMs: (typeof o.duration_ms === 'number' ? o.duration_ms : 0),
                          interrupted: !!(o.subtype && o.subtype !== 'success'),
                          hist: _adopted,
                          turnEnd: true });   // v3.2.2：回合收尾——最终正文留在折叠头外
      // v2.18：本轮组定稿——用户没手动
                                          // 操作过且在底部跟读时自动收起（想看再点开，
                                          // 各抽屉独立开合）
      _hgGrantRewind();                    // v2.28.15：回合定稿——回滚按钮授予最后一条 AI 消息
      // v2.3 问题4：不显示金额，显示上下文用量环（⭕ 百分比，256K 实窗口径）
      renderCtxRing(o);
      setBusy(false);
      if (o.subtype && o.subtype !== 'success')
        renderRaw(`⚠ 回复异常结束：${o.subtype}${o.result ? ' — ' + String(o.result).slice(0, 200) : ''}`);
      refreshSessions();
    }
  }
  // ==================== v3.0 SSE 断点续传客户端（对照 ZCode subscribe(base)）====================
  // base={epoch,seq} 双字段水位：seq 防重放（原有），epoch 判日志重写
  // （/rewind 后旧 seq 空间作废，重放毫无意义只能重建）。ack 三态：
  //   resume   水位有效 → 增量帧直接走正常渲染
  //   snapshot 水位失效但事件流可表达 → 先清场，保留窗重放帧走正常渲染
  //   reset    epoch 不匹配 → 弃事件流，transcript 重建后以新水位重开
  // ka 心跳 5s 一发（命名事件，SSE 注释行 JS 不可见做不了看门狗）；20s
  // 无帧判死强制重连（对照 persistent-protocol KEEP_ALIVE=5s/ACK_TIMEOUT=20s）。
  function _hgSseResetLocal() {
    // 清场：内存态与 DOM 全部作废（switchTo 的重置块同款，供 snapshot/reset 用）
    endThinking(); closeRun();
    if (_HG.grp) phStopTimer(_HG.grp);
    _turnHeadStop();   // v3.2：回合秒表随清场全收（timer 不随 innerHTML 快照走，不收就漏）
    Object.values(_HG.subBlk || {}).forEach(b => { if (b && b.timer) clearInterval(b.timer); });
    _HG.rowById = {}; _HG.uidN = 0; _HG.run = null; _HG.grp = null; _HG.histNav = null;
    _HG.subRows = {}; _HG.subBlk = {}; _HG.subTail = {}; _HG.subTailSeg = {};
    _HG.histAll = null; _HG.histStart = 0; _HG.histLive = false; _HG.histStale = false;
    _HG.todos = null; _HG.agents = null; _HG.dyn = null;
    _HG.proj = null;   // v3.1：投影随清场作废（snapshot 重放将重建）
    _subReset();
    _HG.think = null; _HG.noScroll = false; _HG.openState = null;
    _HG.histLineTs = 0; _HG.histActTs = 0; _HG.thinkPend = null;   // v3.2.2 ts 账 + v3.2.5 pend 随清场作废
    _HG.echoFast = null; _HG.seq = 0;
    _hgFlow.innerHTML = '';
    _hgRailSync();   // v3.2.10：本地清场后收轨
  }
  function _hgSseRebuild(sid) {
    // reset 语义：事件流已无法表达真源（/rewind 换代）→ 弃快照缓存走
    // transcript 重建（switchTo 无缓存分支同款），完成后以新水位重开流。
    if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
    if (!sid || sid !== _HG.sid) return;
    delete _HG.cache[sid];
    _hgSseResetLocal();
    setBusy(false);
    fetch(`/api/harness/transcript?sid=${encodeURIComponent(sid)}`)
      .then(r => r.json())
      .then(j => {
        if (!j.ok || _HG.sid !== sid) return;
        _HG.seq = j.seq || 0; _HG.epoch = j.epoch || null; _HG.alive = !!j.alive;
        if (!j.lines.length) showWelcome();
        else _histRender(j.lines, Math.max(0, j.lines.length - _HG.HIST_PAGE),
                         { noFinalize: !!j.busy });   // v3.2.1R(F1)：尾组定稿在渲染器内；busy 活组留给 phResume
        if (j.busy) phResume(); else grpFinalize(true, { hist: true, turnEnd: true });   // 幂等兜底（v3.2R1(P0)：回放不吃时钟；v3.2.4R(F5) 对齐 switchTo turnEnd）
        _hgScrollBottom(true);
        setBusy(!!j.busy, j.busy_since);
        openSSE(sid, _HG.seq);
        refreshSessions();
      })
      .catch(() => {});
  }
  let _hgKaTimer = null;
  function _hgKaWatchdog() {
    // 看门狗单例：5s 巡检，20s 无帧（连 ka 都没到=流假死：代理静默断连/
    // 服务端卡死）强制关流重开——带当前水位续传，缺口由服务端 resume 补
    if (_hgKaTimer) return;
    _hgKaTimer = setInterval(() => {
      if (!_HG.sse || !_HG.sid) return;
      if (Date.now() - (_HG.lastFrameAt || 0) < 20000) return;
      const sid = _HG.sid;
      try { _HG.sse.close(); } catch(_) {}
      _HG.sse = null;
      openSSE(sid, _HG.seq);
    }, 5000);
  }
  function openSSE(sid, afterSeq) {
    if (_HG.sse) { try { _HG.sse.close(); } catch(_) {} _HG.sse = null; }
    _HG.initN = 0;   // v2.35：init 计数随流重置——新流首个 init=进程待机，不算回合起跑（跨会话/重开 tab 不残留）
    _HG.lastFrameAt = Date.now();
    if (!sid) return;
    _hgKaWatchdog();
    // v3.0：epoch 缺省（新会话/重建后首轮）后端按 snapshot 处理
    const ep = _HG.epoch ? `&epoch=${encodeURIComponent(_HG.epoch)}` : '';
    const es2 = new EventSource(`/api/harness/stream?sid=${encodeURIComponent(sid)}&after_seq=${afterSeq || 0}${ep}`);
    _HG.sse = es2;
    es2.addEventListener('ka', () => { _HG.lastFrameAt = Date.now(); });
    es2.addEventListener('ack', (ev) => {
      _HG.lastFrameAt = Date.now();
      let a; try { a = JSON.parse(ev.data); } catch(_) { return; }
      if (!a || !a.epoch) return;
      if (a.mode === 'reset') { _HG.epoch = a.epoch; _hgSseRebuild(sid); return; }
      _HG.epoch = a.epoch;
      // snapshot：服务端即将重放保留窗——先清场（ack 先于重放帧到达，
      // 事件顺序保证清场时机正确）
      if (a.mode === 'snapshot') _hgSseResetLocal();
    });
    es2.addEventListener('reset', (ev) => {
      // mid-stream reset（慢订阅者被服务端显式断开）——同样走转写重建
      let d = null; try { d = JSON.parse(ev.data); } catch(_) {}
      if (d && d.epoch) _HG.epoch = d.epoch;
      _hgSseRebuild(sid);
    });
    es2.onmessage = (ev) => {
      _HG.lastFrameAt = Date.now();
      let it;
      try { it = JSON.parse(ev.data); } catch(_) { return; }
      // v2.25：防重放——EventSource 断线自动重连用的还是创建时的旧
      // after_seq，后端把缓冲事件从旧位置重发一遍：user_echo 重放 × 乐观
      // 去重窗口已被首次消费清空 → 用户消息画出两条（用户实测「蹦出来
      // 两条我发的命令」）。同一会话内 seq 严格递增，≤当前值的一律是重放。
      if (it.seq) {
        if (it.seq <= _HG.seq) return;
        _HG.seq = it.seq;
      }
      // v3.1：信封先过前端投影（turn_*/subagent_*/input_* 与工具计数——
      // 新进程面板/回合摘要行的单一状态源；legacy 分派不受影响）
      try { _hgProjEvent(it); } catch(_) {}
      // v2.5：先 setBusy（弹活动指示条，改变 flow 高度）再渲染消息——
      // 渲染内部 scrollBottom 含 rAF 二次兜底，否则指示条挤出消息导致刚发的消息不在底
      if (it.kind === 'user_echo') {
        // v3.2.16（用户最后定调，复原收敛）：贴图占位回显——CLI 对每次贴图落
        // 两条 user 行（base64 块+上传附件渲染真图缩略 + "[Image: source: 路径]"
        // 纯回显）。回显标记一律从文本剥掉、路径不并入附件（上传 chips 已表
        // 达且可点开预览）；剥完空壳（无文字无他附件）整条不渲染——历史/实时
        // 同款，消息列内永远不出现图片链接行
        {
          const _ims = String(it.text || '').match(/\[Image: source: [^\]]+?\]/g);
          if (_ims) {
            it.text = String(it.text || '').replace(/\[Image: source: [^\]]+?\]/g, '').trim();
            if (!String(it.text || '').trim() && !(it.files || []).length) {
              _HG.echoFast = null;
              return;
            }
          }
        }
        // v3.2.12：中断/续跑机器标记行（CLI 在中断或自动续跑时落的 user 行）
        // ——非用户输入，整条不渲染（历史重建侧 transcript.py 同款过滤）
        if (/^(\[Request interrupted by user( for tool use)?\]|Continue from where you left off\.)/i.test(String(it.text || '').trim())) {
          _HG.echoFast = null;
          return;
        }
        setBusy(true);
        // v2.20：乐观渲染 → echo 到达即跳过（echoFast 只顶一条，连发两条
        // 相同文本时第二条照常走事件渲染，不会吞）
        if (_HG.echoFast && _HG.echoFast.text === (it.text || '')) _HG.echoFast = null;
        else if (!_hgEchoDup(it)) renderUser(it.text, it.images, it.files);
      }
      else if (it.kind === 'event') handleEvent(it.data);
      else if (it.kind === 'peer') { grpFinalize(true); renderPeer(it.name, it.text, it.to); }
      else if (it.kind === 'renew') { grpFinalize(true); renderRenew(it.text); }
      // v2.34：审计警示（light 回合结算违规）——回合已终结，定稿当前组再出红卡
      else if (it.kind === 'audit') { renderAudit(it.text); _hgScrollBottom(); }   // v3.2.27：撤 grpFinalize——警示入工作区不分割回合
      else if (it.kind === 'raw') renderRaw(it.text);
      else if (it.kind === 'ask') { grpFinalize(true); askRender(it); }
      else if (it.kind === 'ask_done') askDone(it);
      else if (it.kind === 'interrupted') {
        endThinking(); _hgVisionSweep(true);
        grpFinalize(true, { interrupted: true, hist: _hgTailAdopt(), turnEnd: true });   // v3.2.1R2(R2-1/R2-3)认回；v3.2.2 中断=回合收尾，正文留头外
        renderExit(it.text); setBusy(false);
        // v2.32：中断收尾——在跑的子代理标「已中断」（原缺口：只有 result
        // 分支收尾，点 ■ 停止后子代理假"运行中"+计时狂跳）
        _hgAgentsSweep(true); _hgTurnEnd('interrupt', 0);
        _subEnd();                         // v2.33：窗格收起
        // v2.15：通知 stopGen 兜底逻辑「事件到了」，别重复收尾
        try { document.dispatchEvent(new CustomEvent('hg-interrupted', {detail: _HG.sid})); } catch(_) {}
      }
      else if (it.kind === 'exit') {
        endThinking(); _hgVisionSweep(true); _HG.alive = false;
        grpFinalize(true, { hist: _hgTailAdopt(), turnEnd: true });   // v3.2.1R2(R2-1)认回；v3.2.2 退出=回合收尾，正文留头外
        renderExit(it.text); setBusy(false);
        _hgAgentsSweep(true); _hgTurnEnd('exit', 0);   // v2.32：同上，进程退出也收
        _subEnd();                         // v2.33：窗格收起
      }
      // v2.20：会话内切模型 → 消息流插一条分割线（「已切换模型 · xxx」）
      else if (it.kind === 'model_switched') {
        grpFinalize(true, { turnEnd: true });   // v3.2.2：切模型发生在回合间，正文留头外
        renderSwitch(it.text || '默认模型');
      }
    };
  }
  function _hgHasHistory(sid) {
    const s = _HG.sessions.find(x => x.sid === sid);
    return !!(s && s.has_history);
  }
  function saveCache() {
    if (!_HG.sid) return;
    // v2.28.13：echoFast 随快照保存——切走时 2420 行会清空它，但快照 html
    // 里已经带着乐观渲染的用户气泡；若 user_echo 尚未到达（快速切走），
    // 切回来重放的 echo 对不上已清空的去重窗口 → 双画（用户实锤 A→B→A
    // 出两条同文消息）。随快照存取，恢复后重放 echo 仍能命中跳过。
    // v2.37（P0-A）：窗口账目随快照存——恢复路径重建 histStart/histLive，
    // 使滚动扩收机制在快照态重新成立（此前快照恢复后 histLive=false 且
    // histStart 丢失，上滑扩段被 v2.35.2 的门拦死，历史够不着）
    _HG.cache[_HG.sid] = { html: _hgFlow.innerHTML, seq: _HG.seq,
                           epoch: _HG.epoch || null,
                           // v3.0 滚动记忆（对照 ZCode chatSessionScrollMemory 五元组）：
                           // 贴底记忆→切回回底（跟读新消息）；否则恢复钳制后的
                           // scrollTop——翻历史中途切走再切回，视口不再被拽到底
                           scroll: { top: _hgFlow.scrollTop, h: _hgFlow.scrollHeight,
                                     ch: _hgFlow.clientHeight, atBottom: isNearBottom() },
                           echoFast: _HG.echoFast || null,
                           histStart: _HG.histStart,
                           // v2.43.2（R3 复审 F-R3）：降级快照 histLive 恒 false
                           //（降级 return 在置 histLive 之前），恢复主路的
                           // histLive 门会把 'stale' 哨兵整个跳过=永久降级循环
                           //（上滑扩段被门死）——存 histLive 时把降级态并成
                           // true，保证哨兵能到达消费点
                           histLive: _HG.histLive || !!_HG.histStale,
                           // v2.43.1（R-FAIL3）：渲染时点的不可见前缀指纹——恢复
                           // 拉取后比对，中插变更（stub 塌缩/审计卡并入/他窗回滚）
                           // 即整体重渲，旧 DOM 的 hi/hEnd 账目不作数。
                           // v2.43.2（R2-缺口A）：降级态（histStale，已确认漂移但
                           // 忙碌不能重渲）存 'stale' 哨兵——histAll 虽空，下次
                           // 恢复仍强制重渲，漂移保护不随降级丢失
                           histFp: _HG.histStale ? 'stale'
                                   : (_HG.histAll ? _histPrefixFp(_HG.histAll, _HG.histStart | 0) : null),
                           // v3.2.28（用户实锤「切走再切回，工作区被截断，
                           // 回合完成后还是截断态」）：切走时存在未定稿组
                           // （回合进行中）→ 快照注定残缺（离开期间的过程行只
                           // 靠事件回放，环形缓冲有限会丢）——恢复端见此标记
                           // 弃快照走 transcript 全量重渲
                           openTurn: !!(function() {
                             const g = [..._hgFlow.querySelectorAll('.h-grp')].pop();
                             return g && g.dataset.finalized !== '1';
                           })() };
    // v2.25：快照 LRU 上限 10——大会话 innerHTML 每份可达数十 MB，无上限
    // 来回切会话会攒爆内存（审计 §三.8）
    // v3.1：keep-warm（对照 ZCode 延迟销毁）——超限快照不再即时 delete，
    // 保温 30s 后销毁；期间切回（A→B→A 快切）直接命中热快照零重建，
    // 切回动作本身会取消销毁定时器。稳态内存不变（30s 后照删）。
    const keys = Object.keys(_HG.cache);
    const warm = _HG.cacheWarm || (_HG.cacheWarm = {});
    for (const k of keys.slice(0, Math.max(0, keys.length - 10))) {
      if (warm[k]) continue;               // 已在保温期
      warm[k] = setTimeout(() => {
        delete warm[k];
        delete _HG.cache[k];
      }, 30000);
    }
  }
  function _histPrefixFp(lines, n) {
    if (!Array.isArray(lines) || lines.length < n) return 'short';
    let h = n | 0;
    for (let i = 0; i < n; i++) {
      const l = lines[i] || {};
      h = (Math.imul(h, 31) + String(l.role || '').length
           + (l.text ? String(l.text).length : 0)
           + (l.agent ? String(l.agent).length : 0)) | 0;
    }
    return String(h);
  }
  // v3.0：轮询兜底通道的 epoch 校验——/events 响应带 epoch，与自己水位
  // 不符（对端已换代）即走重建（与 SSE ack(reset) 同语义，轮询路径不再
  // 只有 seq 单字段盲区）。两处调用（switchTo 早返回/快照恢复）共用。
  function _hgEventsPoll(sid) {
    fetch(`/api/harness/events?sid=${encodeURIComponent(sid)}&after_seq=${_HG.seq}&epoch=${encodeURIComponent(_HG.epoch || '')}`)
      .then(r => r.json())
      .then(j => {
        if (!j.ok || _HG.sid !== sid) return;
        if (j.epoch && _HG.epoch && j.epoch !== _HG.epoch) { _hgSseRebuild(sid); return; }
        _hgProjSeed(j);                    // v3.1：投影/队列种子随轮询对齐服务端真相
        setBusy(!!j.busy, j.busy_since);
        if (j.busy) phResume();
      })
      .catch(() => { if (_HG.sid === sid) setBusy(false); });
  }
